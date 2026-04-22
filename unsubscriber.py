# -*- coding: utf-8 -*-
"""
Unsubscribe execution module - performs unsubscribe actions in several ways.
Supports three unsubscribe methods, in priority order:
1. List-Unsubscribe-Post (RFC 8058 one-click unsubscribe)
2. List-Unsubscribe mailto (sends an unsubscribe email through Gmail API)
3. Unsubscribe link extracted from the email body

After a successful unsubscribe it can also:
- apply the "Unsubscribed" label to that sender's emails
- optionally archive old emails from that sender
"""

import base64
import logging
import re
import time
import urllib.parse
from email.mime.text import MIMEText
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10
REQUEST_INTERVAL = 2

UNSUBSCRIBE_LINK_KEYWORDS = [
    "unsubscribe", "opt-out", "optout", "opt_out",
    "remove", "cancel", "退订", "取消订阅", "取消接收",
    "退出", "不再接收", "停止接收",
]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

UNSUBSCRIBE_LABEL_NAME = "Unsubscribed"

_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _is_safe_http_url(url: str) -> bool:
    """True only if url is plain http(s). Blocks javascript:, file:, data:, ftp:, etc."""
    if not isinstance(url, str):
        return False
    url = url.strip().lower()
    return url.startswith(_ALLOWED_URL_SCHEMES)


# ────────────────────────────────────────────────────────────────
#  Parse the List-Unsubscribe header
# ────────────────────────────────────────────────────────────────

def get_list_unsubscribe_url(headers_or_value) -> dict:
    """Parse the List-Unsubscribe header and extract the HTTP URL and mailto address."""
    raw_value = (
        headers_or_value.get("list-unsubscribe", "")
        if isinstance(headers_or_value, dict)
        else (headers_or_value or "")
    )

    result = {
        "http_url": None,
        "mailto": None,
        "mailto_email": None,
        "mailto_subject": None,
    }

    for entry in re.findall(r"<([^>]+)>", raw_value):
        entry = entry.strip()
        if (entry.startswith("https://") or entry.startswith("http://")) and not result["http_url"]:
            result["http_url"] = entry
        elif entry.startswith("mailto:") and not result["mailto"]:
            result["mailto"] = entry
            parsed = _parse_mailto(entry)
            result["mailto_email"] = parsed["email"]
            result["mailto_subject"] = parsed["subject"]

    return result


def _parse_mailto(mailto_str: str) -> dict:
    """Parse a mailto: string and extract the email address and subject parameter."""
    rest = mailto_str[7:] if mailto_str.startswith("mailto:") else mailto_str
    if "?" in rest:
        email_part, params_str = rest.split("?", 1)
        params = urllib.parse.parse_qs(params_str)
        subject = params.get("subject", [None])[0]
    else:
        email_part, subject = rest, None
    return {"email": email_part.strip(), "subject": subject}


# ────────────────────────────────────────────────────────────────
#  Unsubscribe method 1: one-click unsubscribe (RFC 8058 POST)
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_one_click(url: str) -> dict:
    """Send a POST request to the URL and perform RFC 8058 one-click unsubscribe."""
    if not _is_safe_http_url(url):
        return {"success": False, "method": "one_click_post",
                "message": f"Rejected non-http(s) URL: {url[:80]}", "status_code": None}
    logger.info(f"Trying one-click unsubscribe (POST): {url}")
    try:
        response = requests.post(
            url,
            data={"List-Unsubscribe": "One-Click"},
            headers={**DEFAULT_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )
        time.sleep(REQUEST_INTERVAL)
        success = response.status_code in (200, 201, 202, 204)
        return {
            "success": success,
            "method": "one_click_post",
            "message": f"One-click unsubscribe {'succeeded' if success else 'failed'} (HTTP {response.status_code})",
            "status_code": response.status_code,
        }
    except requests.exceptions.Timeout:
        return {"success": False, "method": "one_click_post", "message": "Request timed out", "status_code": None}
    except Exception as e:
        return {"success": False, "method": "one_click_post", "message": f"Connection failed: {e}", "status_code": None}


# ────────────────────────────────────────────────────────────────
#  Unsubscribe method 2: send an unsubscribe email through Gmail API
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_mailto(mailto_info: dict, service=None) -> dict:
    """
    Send an actual unsubscribe email through the Gmail API.
    Requires a service object from auth.get_gmail_service().
    """
    email_addr = mailto_info.get("mailto_email", "")
    subject = mailto_info.get("mailto_subject") or "unsubscribe"

    if not email_addr:
        return {"success": False, "method": "mailto", "message": "Could not parse unsubscribe email address"}

    if service is None:
        return {"success": False, "method": "mailto",
                "message": "No Gmail service provided; cannot send unsubscribe email"}

    try:
        raw = _build_email_raw(to_email=email_addr, subject=subject)
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        logger.info(f"Unsubscribe email sent through Gmail API to: {email_addr}")
        return {
            "success": True,
            "method": "mailto",
            "message": f"Unsubscribe email sent to {email_addr} (subject: {subject})",
        }
    except Exception as e:
        safe = re.sub(r"(?i)\b(sk|pk|Bearer|access_token)[=:\s]\S+", "[REDACTED]", str(e))
        logger.error(f"Failed to send unsubscribe email: {safe}")
        return {"success": False, "method": "mailto", "message": f"Failed to send unsubscribe email: {e}"}


def _build_email_raw(to_email: str, subject: str) -> str:
    """Build an unsubscribe email and convert it to the base64 format expected by Gmail API."""
    msg = MIMEText("Please unsubscribe me from your mailing list.\n\nThank you.")
    msg["to"] = to_email
    msg["subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


# ────────────────────────────────────────────────────────────────
#  Unsubscribe method 3: extract an unsubscribe link from the email body
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_link(html_body: str) -> dict:
    """Extract an unsubscribe link from the email HTML body and send a GET request."""
    if not html_body:
        return {"success": False, "method": "link_click",
                "message": "Email body is empty; cannot extract an unsubscribe link", "found_url": None, "status_code": None}

    unsubscribe_url = _find_unsubscribe_link(html_body)
    if not unsubscribe_url:
        return {"success": False, "method": "link_click",
                "message": "No unsubscribe link found in the email body", "found_url": None, "status_code": None}

    if not _is_safe_http_url(unsubscribe_url):
        return {"success": False, "method": "link_click",
                "message": f"Rejected non-http(s) link: {unsubscribe_url[:80]}",
                "found_url": unsubscribe_url, "status_code": None}

    logger.info(f"Found unsubscribe link: {unsubscribe_url[:80]}")
    try:
        response = requests.get(
            unsubscribe_url, headers=DEFAULT_HEADERS,
            timeout=HTTP_TIMEOUT, allow_redirects=True,
        )
        time.sleep(REQUEST_INTERVAL)
        success = response.status_code in (200, 201, 202, 204)
        return {
            "success": success,
            "method": "link_click",
            "message": f"Visited unsubscribe link (HTTP {response.status_code})",
            "found_url": unsubscribe_url,
            "status_code": response.status_code,
        }
    except Exception as e:
        return {"success": False, "method": "link_click",
                "message": f"Failed to visit unsubscribe link: {e}", "found_url": unsubscribe_url, "status_code": None}


def _fetch_html_body(service, message_id: str) -> str:
    """Fetch the HTML body for a single email on demand."""
    if not service or not message_id:
        return ""
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        _, html = _extract_body_from_payload(msg.get("payload", {}))
        return html
    except Exception as e:
        logger.warning(f"Failed to fetch email body on demand ({message_id}): {e}")
        return ""


def _extract_body_from_payload(payload: dict) -> tuple[str, str]:
    """Recursively extract plain-text and HTML bodies from the payload."""
    import base64 as _b64
    body_text, body_html = "", ""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    def _decode(data: str) -> str:
        try:
            padded = data + "=" * (4 - len(data) % 4)
            return _b64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except Exception:
            return ""

    if mime_type == "text/plain" and body_data:
        body_text = _decode(body_data)
    elif mime_type == "text/html" and body_data:
        body_html = _decode(body_data)
    elif "parts" in payload:
        for part in payload["parts"]:
            pt, ph = _extract_body_from_payload(part)
            if pt and not body_text:
                body_text = pt
            if ph and not body_html:
                body_html = ph

    return body_text, body_html


def _find_unsubscribe_link(html_body: str) -> Optional[str]:
    """Find the most likely unsubscribe URL in HTML, preferring the last candidate."""
    try:
        soup = BeautifulSoup(html_body, "lxml")
    except Exception:
        soup = BeautifulSoup(html_body, "html.parser")

    candidates = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        href_lower = href.lower()
        if not (href_lower.startswith("http://") or href_lower.startswith("https://")):
            continue
        text = a_tag.get_text(strip=True).lower()
        for kw in UNSUBSCRIBE_LINK_KEYWORDS:
            if kw in text or kw in href.lower():
                candidates.append(href)
                break

    return candidates[-1] if candidates else None


# ────────────────────────────────────────────────────────────────
#  Gmail label management
# ────────────────────────────────────────────────────────────────

def create_or_get_label(service, label_name: str = UNSUBSCRIBE_LABEL_NAME) -> str:
    """
    Get or create the Gmail label with the given name and return its label ID.
    """
    labels_resp = service.users().labels().list(userId="me").execute()
    for label in labels_resp.get("labels", []):
        if label["name"] == label_name:
            return label["id"]

    new_label = service.users().labels().create(
        userId="me",
        body={
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    logger.info(f"Created Gmail label: {label_name} (ID: {new_label['id']})")
    return new_label["id"]


def label_sender_emails(service, message_ids: list, label_id: str) -> None:
    """Apply a label to the given list of emails."""
    for msg_id in message_ids:
        try:
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [label_id]},
            ).execute()
        except Exception as e:
            logger.warning(f"Failed to apply label to email {msg_id}: {e}")
    logger.debug(f"Applied label {label_id} to {len(message_ids)} emails")


def archive_sender_emails(service, message_ids: list) -> None:
    """Archive the given emails by removing the INBOX label."""
    for msg_id in message_ids:
        try:
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["INBOX"]},
            ).execute()
        except Exception as e:
            logger.warning(f"Failed to archive email {msg_id}: {e}")
    logger.debug(f"Archived {len(message_ids)} emails")


# ────────────────────────────────────────────────────────────────
#  Unified unsubscribe entry point
# ────────────────────────────────────────────────────────────────

def execute_unsubscribe(
    sender_group: dict,
    service=None,
    dry_run: bool = True,
    archive: bool = False,
) -> dict:
    """
    Execute unsubscribe actions for one sender group.

    Args:
        sender_group: Sender-group dictionary returned by classifier.classify_emails()
        service: Gmail API service object used for labeling/archiving after success
        dry_run: If True, only analyze available methods without executing them
        archive: If True, archive old emails from this sender after success
    """
    sender_email = sender_group.get("sender_email", "unknown")
    sender = sender_group.get("sender", sender_email)
    list_unsub_raw = sender_group.get("list_unsubscribe")
    list_unsub_post = sender_group.get("list_unsubscribe_post", "")
    html_body = sender_group.get("sample_html", "")
    message_ids = sender_group.get("message_ids", [])

    result = {
        "sender_email": sender_email,
        "sender": sender,
        "dry_run": dry_run,
        "attempted_method": None,
        "success": False,
        "message": "",
        "details": {},
    }

    # ── Dry-run mode ──
    if dry_run:
        available_methods = []
        if list_unsub_raw:
            unsub_info = get_list_unsubscribe_url(list_unsub_raw)
            if unsub_info["http_url"]:
                has_post = list_unsub_post and "List-Unsubscribe=One-Click" in list_unsub_post
                method_name = "One-click unsubscribe (POST)" if has_post else "HTTP link (GET)"
                available_methods.append(f"✓ {method_name}：{unsub_info['http_url'][:60]}...")
            if unsub_info["mailto_email"]:
                available_methods.append(f"✓ mailto unsubscribe: {unsub_info['mailto_email']}")
        if not html_body:
            sample_id = sender_group.get("sample_id", "")
            html_body = _fetch_html_body(service, sample_id)
        if html_body:
            link = _find_unsubscribe_link(html_body)
            if link:
                available_methods.append(f"✓ body unsubscribe link: {link[:60]}...")

        result["success"] = bool(available_methods)
        result["message"] = (
            "Dry run: found the following unsubscribe methods"
            if available_methods else
            "Dry run: no usable unsubscribe method found"
        )
        result["details"]["available_methods"] = available_methods
        return result

    # ── Live execution ──
    logger.info(f"Starting unsubscribe: {sender_email}")

    # Methods 1 & 2: List-Unsubscribe
    if list_unsub_raw:
        unsub_info = get_list_unsubscribe_url(list_unsub_raw)

        if unsub_info["http_url"]:
            if not _is_safe_http_url(unsub_info["http_url"]):
                attempt = {
                    "success": False, "method": "http_get",
                    "message": f"Rejected non-http(s) URL: {unsub_info['http_url'][:80]}",
                    "status_code": None,
                }
            else:
                has_one_click = list_unsub_post and "List-Unsubscribe=One-Click" in list_unsub_post
                if has_one_click:
                    attempt = unsubscribe_via_one_click(unsub_info["http_url"])
                else:
                    try:
                        resp = requests.get(
                            unsub_info["http_url"], headers=DEFAULT_HEADERS,
                            timeout=HTTP_TIMEOUT, allow_redirects=True,
                        )
                        time.sleep(REQUEST_INTERVAL)
                        attempt = {
                            "success": resp.status_code in (200, 201, 202, 204),
                            "method": "http_get",
                            "message": f"HTTP GET (status code {resp.status_code})",
                            "status_code": resp.status_code,
                        }
                    except Exception as e:
                        attempt = {"success": False, "method": "http_get",
                                   "message": f"HTTP GET failed: {e}", "status_code": None}

            result["details"]["http"] = attempt
            if attempt["success"]:
                result.update({"attempted_method": attempt["method"],
                               "success": True, "message": attempt["message"]})
                _post_unsubscribe_actions(service, message_ids, archive)
                return result

        if unsub_info["mailto_email"]:
            attempt = unsubscribe_via_mailto(unsub_info, service=service)
            result["details"]["mailto"] = attempt
            if attempt["success"]:
                result.update({"attempted_method": "mailto",
                               "success": True, "message": attempt["message"]})
                _post_unsubscribe_actions(service, message_ids, archive)
                return result

    # Method 3: body link (body was not fetched during scan, so fetch on demand here)
    if not html_body:
        sample_id = sender_group.get("sample_id", "")
        html_body = _fetch_html_body(service, sample_id)

    if html_body:
        attempt = unsubscribe_via_link(html_body)
        result["details"]["link"] = attempt
        if attempt["success"]:
            result.update({"attempted_method": "link_click",
                           "success": True, "message": attempt["message"]})
            _post_unsubscribe_actions(service, message_ids, archive)
            return result

    result["message"] = "No usable unsubscribe method found"
    logger.warning(f"Unsubscribe failed: {sender_email}")
    return result


def _post_unsubscribe_actions(service, message_ids: list, archive: bool) -> None:
    """After a successful unsubscribe: apply the label, then optionally archive."""
    if not service or not message_ids:
        return
    try:
        label_id = create_or_get_label(service)
        label_sender_emails(service, message_ids, label_id)
        logger.info(f"Applied the '{UNSUBSCRIBE_LABEL_NAME}' label to {len(message_ids)} emails")
    except Exception as e:
        logger.warning(f"Labeling failed (does not affect unsubscribe result): {e}")

    if archive:
        try:
            archive_sender_emails(service, message_ids)
            logger.info(f"Archived {len(message_ids)} emails")
        except Exception as e:
            logger.warning(f"Archiving failed (does not affect unsubscribe result): {e}")
