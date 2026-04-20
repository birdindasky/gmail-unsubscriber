# -*- coding: utf-8 -*-
"""
邮件扫描模块 - 从 Gmail 获取邮件列表及详情
使用小批量并发（3线程）提升性能，并过滤已退订的发件人。
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
REQUEST_SLEEP = 0.15   # 默认每个线程请求之间的休眠
CONCURRENT_WORKERS = 3  # 默认并发线程数（保守值，不触发 Gmail 并发限制）
PROGRESS_INTERVAL = 50  # 每处理多少封打印一次进度
LIST_PROGRESS_INTERVAL = 5  # 每拉取多少页打印一次列表阶段进度
LARGE_SCAN_THRESHOLD = 1000
VERY_LARGE_SCAN_THRESHOLD = 5000
ALL_MAIL_BASE_EXCLUDES = "-in:sent -in:drafts -in:trash -in:spam"

# 每个线程维护自己的 Gmail service 对象
_thread_local = threading.local()
_service_init_lock = threading.Lock()


def _get_thread_service():
    """获取当前线程的 Gmail service（每线程只创建一次）。"""
    if not hasattr(_thread_local, "service"):
        with _service_init_lock:
            if not hasattr(_thread_local, "service"):
                _thread_local.service = auth.get_gmail_service()
    return _thread_local.service


def _retry_request(func, *args, **kwargs):
    """带重试机制的 API 请求包装器。"""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            if e.resp.status in (429, 500, 503):
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(f"API 请求失败（{e.resp.status}），{wait}s 后重试...")
                time.sleep(wait)
                last_error = e
            else:
                raise
        except (ssl.SSLError, ConnectionError, OSError) as e:
            wait = RETRY_DELAY * (attempt + 1)
            logger.warning(f"网络连接错误，{wait}s 后重试（第 {attempt+1} 次）：{e}")
            time.sleep(wait)
            last_error = e
    raise last_error if last_error else RuntimeError("重试请求失败但无错误信息")


def _get_fetch_settings(total_messages: int) -> tuple[int, float]:
    """按任务规模选择 metadata 拉取并发度与请求间隔。"""
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
    扫描最近 N 天内收到的邮件，返回邮件详情列表。
    默认优先扫描 CATEGORY_PROMOTIONS 标签；scan_all=True 时扫描全部邮件。
    已退订的发件人自动过滤。
    """
    if days == 0:
        # days=0 表示不限时间，扫描全部历史邮件
        date_filter = ""
        time_desc = "全部历史"
    else:
        since_date = datetime.now() - timedelta(days=days)
        after_timestamp = int(since_date.timestamp())
        date_filter = f"after:{after_timestamp} "
        time_desc = f"最近 {days} 天"

    if scan_all:
        query = f"{date_filter}{ALL_MAIL_BASE_EXCLUDES}".strip()
        label_desc = "全部邮件（已排除已发送/草稿/垃圾箱/垃圾邮件）"
    else:
        query = f"{date_filter}category:promotions"
        label_desc = "促销邮件"

    logger.info(f"扫描{time_desc}的{label_desc}")
    print(f"\n📬 正在扫描{time_desc}的{label_desc}...")
    if max_messages:
        print(f"   最多处理前 {max_messages} 封邮件")

    message_stubs = _list_all_messages(service, query, max_messages=max_messages)
    total = len(message_stubs)
    logger.info(f"共找到 {total} 封邮件，开始批量解析...")
    print(f"   共找到 {total} 封邮件，正在批量解析详情...\n")

    if total >= VERY_LARGE_SCAN_THRESHOLD:
        print("   ⚠️  当前任务非常大，可能需要较长时间。")
        print("   提示：可加 --max-messages N 先做抽样验证。\n")
    elif total >= LARGE_SCAN_THRESHOLD:
        print("   ⏳ 当前样本较大，请耐心等待；程序会持续打印进度。\n")

    if total == 0:
        return []

    workers, request_sleep = _get_fetch_settings(total)
    print(f"   扫描配置：{workers} 线程 / 每请求间隔 {request_sleep:.2f}s\n")
    emails = _fetch_messages_batch(
        service,
        message_stubs,
        workers=workers,
        request_sleep=request_sleep,
    )

    # 过滤已退订的发件人
    already_done = set()
    filtered = []
    for em in emails:
        sender_email = em.get("sender_email", "")
        if database.is_already_unsubscribed(sender_email):
            if sender_email not in already_done:
                already_done.add(sender_email)
                logger.debug(f"跳过已退订发件人：{sender_email}")
        else:
            filtered.append(em)

    if already_done:
        print(f"   ⏭️  跳过 {len(already_done)} 个已退订的发件人\n")

    print(f"✅ 扫描完成，共解析 {len(emails)} 封邮件，过滤后剩余 {len(filtered)} 封\n")
    logger.info(f"扫描完成：{len(emails)} 封邮件，过滤 {len(already_done)} 个已退订发件人")
    return filtered


def _fetch_messages_batch(
    service,
    message_stubs: list[dict],
    workers: int = CONCURRENT_WORKERS,
    request_sleep: float = REQUEST_SLEEP,
) -> list[dict]:
    """
    并发获取邮件 metadata，遇到 429 自动退避重试。
    每个线程维护独立的请求间隔以控制总 QPS。
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
                    logger.debug(f"{e.resp.status} 错误，{wait}s 后重试（第 {attempt+1} 次）...")
                    time.sleep(wait)
                else:
                    logger.warning(f"获取邮件失败（{stub['id']}）：{e}")
                    break
            except (ssl.SSLError, ConnectionError, OSError) as e:
                last_retriable_status = -1
                wait = RETRY_DELAY * (attempt + 1)
                logger.debug(f"网络错误，{wait}s 后重试（第 {attempt+1} 次）：{e}")
                time.sleep(wait)
            except Exception as e:
                logger.warning(f"邮件解析失败（{stub['id']}）：{e}")
                break
        else:
            # for-else：未 break 说明所有 attempt 都用光了且最终无结果
            if parsed is None and last_retriable_status is not None:
                logger.warning(
                    f"邮件 {stub['id']} 重试 {MAX_RETRIES} 次仍失败（最后状态 "
                    f"{last_retriable_status}），已跳过"
                )

        time.sleep(request_sleep)

        with progress_lock:
            progress["done"] += 1
            done = progress["done"]
            if done % PROGRESS_INTERVAL == 0 or done == total:
                print(f"   进度：{done}/{total} 封...")

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
    """分页获取所有符合查询条件的邮件存根。"""
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
            logger.error(f"获取邮件列表失败：{e}")
            break

        messages.extend(response.get("messages", []))
        page_count += 1
        if page_count == 1 or page_count % LIST_PROGRESS_INTERVAL == 0:
            elapsed = int(time.time() - started_at)
            print(f"   列表进度：已拉取 {page_count} 页，累计 {len(messages)} 封（{elapsed}s）")

        if max_messages and len(messages) >= max_messages:
            messages = messages[:max_messages]
            print(f"   已达到上限：提前截断为前 {len(messages)} 封邮件")
            break

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return messages


def _parse_message(msg: dict) -> Optional[dict]:
    """将 Gmail API 返回的原始邮件对象解析为结构化字典。"""
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
            "subject": headers.get("subject", "（无主题）"),
            "sender": sender_raw,
            "sender_email": sender_email,
            "sender_domain": sender_domain,
            "date": headers.get("date", ""),
            "list_unsubscribe": headers.get("list-unsubscribe"),
            "list_unsubscribe_post": headers.get("list-unsubscribe-post"),
            "snippet": msg.get("snippet", ""),
            "body_text": "",   # metadata 格式不含正文，退订时按需获取
            "body_html": "",   # 见 unsubscriber._fetch_html_body()
            "labels": msg.get("labelIds", []),
            "_headers": headers,
        }
    except Exception as e:
        logger.warning(f"解析邮件失败：{e}")
        return None


def _parse_sender(sender_raw: str) -> tuple[str, str]:
    """从发件人字段提取邮箱地址和域名。"""
    if "<" in sender_raw and ">" in sender_raw:
        start = sender_raw.index("<") + 1
        end = sender_raw.index(">")
        email_addr = sender_raw[start:end].strip().lower()
    else:
        email_addr = sender_raw.strip().lower()

    domain = email_addr.split("@")[-1] if "@" in email_addr else ""
    return email_addr, domain
