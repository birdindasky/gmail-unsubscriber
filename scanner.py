# -*- coding: utf-8 -*-
"""
Email scanning module - fetches Gmail message lists and metadata.
Uses small-batch concurrency (3 threads) for speed and filters senders that were
already unsubscribed.
"""

import logging
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional

from googleapiclient.errors import HttpError

import auth
import database

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_SLEEP = 0.15   # Default pause between requests per thread
CONCURRENT_WORKERS = 3  # Default worker count; conservative to avoid Gmail rate issues
PROGRESS_INTERVAL = 50  # Print progress every N processed emails
LIST_PROGRESS_INTERVAL = 5  # Print list-stage progress every N pages
LARGE_SCAN_THRESHOLD = 1000
VERY_LARGE_SCAN_THRESHOLD = 5000
ALL_MAIL_BASE_EXCLUDES = "-in:sent -in:drafts -in:trash -in:spam"

# Each thread keeps its own Gmail service object
_thread_local = threading.local()
_service_init_lock = threading.Lock()


def _get_thread_service():
    """Get the Gmail service for the current thread, creating it once per thread."""
    if not hasattr(_thread_local, "service"):
        with _service_init_lock:
            if not hasattr(_thread_local, "service"):
                _thread_local.service = auth.get_gmail_service()
    return _thread_local.service


def _retry_request(func, *args, **kwargs):
    """Wrap an API request with retry logic."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            if e.resp.status in (429, 500, 503):
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(f"API request failed ({e.resp.status}); retrying in {wait}s...")
                time.sleep(wait)
                last_error = e
            else:
                raise
        except (ssl.SSLError, ConnectionError, OSError) as e:
            wait = RETRY_DELAY * (attempt + 1)
            logger.warning(f"Network error; retrying in {wait}s (attempt {attempt+1}): {e}")
            time.sleep(wait)
            last_error = e
    raise last_error if last_error else RuntimeError("Retried request failed without an error object")


def _get_fetch_settings(total_messages: int) -> tuple[int, float]:
    """Choose metadata fetch concurrency and pacing based on task size."""
    if total_messages >= VERY_LARGE_SCAN_THRESHOLD:
        return 6, 0.03
    if total_messages >= LARGE_SCAN_THRESHOLD:
        return 5, 0.05
    if total_messages >= 300:
        return 4, 0.08
    return CONCURRENT_WORKERS, REQUEST_SLEEP


def scan_emails(
    service,
    days: int = 30,
    scan_all: bool = False,
    max_messages: Optional[int] = None,
) -> list[dict]:
    """
    Scan emails received within the last N days and return email detail dictionaries.
    By default it scans the CATEGORY_PROMOTIONS label first; scan_all=True scans all mail.
    Already-unsubscribed senders are filtered automatically.
    """
    if days == 0:
        # days=0 means no time limit; scan full history
        date_filter = ""
        time_desc = "all history"
    else:
        since_date = datetime.now() - timedelta(days=days)
        after_timestamp = int(since_date.timestamp())
        date_filter = f"after:{after_timestamp} "
        time_desc = f"last {days} days"

    if scan_all:
        query = f"{date_filter}{ALL_MAIL_BASE_EXCLUDES}".strip()
        label_desc = "all mail (excluding sent/drafts/trash/spam)"
    else:
        query = f"{date_filter}category:promotions"
        label_desc = "promotional mail"

    logger.info(f"Scanning {label_desc} from {time_desc}")
    print(f"\n📬 Scanning {label_desc} from {time_desc}...")
    if max_messages:
        print(f"   Processing up to the first {max_messages} emails")

    message_stubs = _list_all_messages(service, query, max_messages=max_messages)
    total = len(message_stubs)
    logger.info(f"Found {total} emails; starting batch parsing")
    print(f"   Found {total} emails; parsing details in batches...\n")

    if total >= VERY_LARGE_SCAN_THRESHOLD:
        print("   ⚠️  This is a very large task and may take a while.")
        print("   Tip: use --max-messages N first to sample-check the results.\n")
    elif total >= LARGE_SCAN_THRESHOLD:
        print("   ⏳ This sample is large. Please wait; progress will keep printing.\n")

    if total == 0:
        return []

    workers, request_sleep = _get_fetch_settings(total)
    print(f"   Scan settings: {workers} threads / {request_sleep:.2f}s between requests\n")
    emails = _fetch_messages_batch(
        service,
        message_stubs,
        workers=workers,
        request_sleep=request_sleep,
    )

    # Filter senders that were already unsubscribed
    already_done = set()
    filtered = []
    for em in emails:
        sender_email = em.get("sender_email", "")
        if database.is_already_unsubscribed(sender_email):
            if sender_email not in already_done:
                already_done.add(sender_email)
                logger.debug(f"Skipping already unsubscribed sender: {sender_email}")
        else:
            filtered.append(em)

    if already_done:
        print(f"   ⏭️  Skipped {len(already_done)} already unsubscribed senders\n")

    print(f"✅ Scan complete: parsed {len(emails)} emails, {len(filtered)} remain after filtering\n")
    logger.info(f"Scan complete: parsed {len(emails)} emails, filtered {len(already_done)} unsubscribed senders")
    return filtered


def _fetch_messages_batch(
    service,
    message_stubs: list[dict],
    workers: int = CONCURRENT_WORKERS,
    request_sleep: float = REQUEST_SLEEP,
) -> list[dict]:
    """
    Fetch email metadata concurrently, backing off automatically on 429 responses.
    Each thread keeps its own pacing to control total request rate.
    """
    results = []
    total = len(message_stubs)
    results_lock = threading.Lock()
    progress_lock = threading.Lock()
    progress = {"done": 0}

    def fetch_one(stub):
        svc = _get_thread_service()
        parsed = None
        last_retriable_status: Optional[int] = None
        for attempt in range(MAX_RETRIES):
            try:
                msg = svc.users().messages().get(
                    userId="me",
                    id=stub["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "List-Unsubscribe",
                                     "List-Unsubscribe-Post", "Date"],
                ).execute()
                parsed = _parse_message(msg)
                break
            except HttpError as e:
                if e.resp.status in (429, 500, 503):
                    last_retriable_status = e.resp.status
                    wait = RETRY_DELAY * (attempt + 1)
                    logger.debug(f"{e.resp.status} error; retrying in {wait}s (attempt {attempt+1})...")
                    time.sleep(wait)
                else:
                    logger.warning(f"Failed to fetch email ({stub['id']}): {e}")
                    break
            except (ssl.SSLError, ConnectionError, OSError) as e:
                last_retriable_status = -1
                wait = RETRY_DELAY * (attempt + 1)
                logger.debug(f"Network error; retrying in {wait}s (attempt {attempt+1}): {e}")
                time.sleep(wait)
            except Exception as e:
                logger.warning(f"Failed to parse email ({stub['id']}): {e}")
                break
        else:
            # for-else: no break means every attempt was used and no result was produced
            if parsed is None and last_retriable_status is not None:
                logger.warning(
                    f"Email {stub['id']} still failed after {MAX_RETRIES} retries "
                    f"(last status {last_retriable_status}); skipped"
                )

        time.sleep(request_sleep)

        with progress_lock:
            progress["done"] += 1
            done = progress["done"]
            if done % PROGRESS_INTERVAL == 0 or done == total:
                print(f"   Progress: {done}/{total} emails...")

        return parsed

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_one, stub): stub for stub in message_stubs}
        for future in as_completed(futures):
            result = future.result()
            if result:
                with results_lock:
                    results.append(result)

    return results


def _list_all_messages(service, query: str, max_messages: Optional[int] = None) -> list[dict]:
    """Fetch all message stubs matching the query, page by page."""
    messages = []
    page_token = None
    page_count = 0
    started_at = time.time()

    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            response = _retry_request(
                service.users().messages().list(**kwargs).execute
            )
        except HttpError as e:
            logger.error(f"Failed to fetch email list: {e}")
            break

        messages.extend(response.get("messages", []))
        page_count += 1
        if page_count == 1 or page_count % LIST_PROGRESS_INTERVAL == 0:
            elapsed = int(time.time() - started_at)
            print(f"   List progress: {page_count} pages fetched, {len(messages)} emails total ({elapsed}s)")

        if max_messages and len(messages) >= max_messages:
            messages = messages[:max_messages]
            print(f"   Reached cap: truncated early to the first {len(messages)} emails")
            break

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return messages


def _parse_message(msg: dict) -> Optional[dict]:
    """Parse a raw Gmail API message object into a structured dictionary."""
    try:
        payload = msg.get("payload", {})
        headers = {
            h["name"].lower(): h["value"]
            for h in payload.get("headers", [])
        }
        sender_raw = headers.get("from", "")
        sender_email, sender_domain = _parse_sender(sender_raw)

        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "subject": headers.get("subject", "(No subject)"),
            "sender": sender_raw,
            "sender_email": sender_email,
            "sender_domain": sender_domain,
            "date": headers.get("date", ""),
            "list_unsubscribe": headers.get("list-unsubscribe"),
            "list_unsubscribe_post": headers.get("list-unsubscribe-post"),
            "snippet": msg.get("snippet", ""),
            "body_text": "",   # metadata does not include bodies; fetched later if needed
            "body_html": "",   # see unsubscriber._fetch_html_body()
            "labels": msg.get("labelIds", []),
            "_headers": headers,
        }
    except Exception as e:
        logger.warning(f"Failed to parse email: {e}")
        return None


def _parse_sender(sender_raw: str) -> tuple[str, str]:
    """Extract the email address and domain from a sender field."""
    if "<" in sender_raw and ">" in sender_raw:
        start = sender_raw.index("<") + 1
        end = sender_raw.index(">")
        email_addr = sender_raw[start:end].strip().lower()
    else:
        email_addr = sender_raw.strip().lower()

    domain = email_addr.split("@")[-1] if "@" in email_addr else ""
    return email_addr, domain
