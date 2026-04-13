# -*- coding: utf-8 -*-
"""
邮件扫描模块 - 从 Gmail 获取邮件列表及详情
使用 Gmail 批量 API 提升性能，并过滤已退订的发件人。
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from googleapiclient.errors import HttpError

import database

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 100
MAX_RETRIES = 3
RETRY_DELAY = 2


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
    raise last_error


def scan_emails(service, days: int = 30, scan_all: bool = False) -> list[dict]:
    """
    扫描最近 N 天内收到的邮件，返回邮件详情列表。
    默认优先扫描 CATEGORY_PROMOTIONS 标签；scan_all=True 时扫描全部邮件。
    已退订的发件人自动过滤。
    """
    since_date = datetime.now() - timedelta(days=days)
    after_timestamp = int(since_date.timestamp())

    if scan_all:
        query = f"after:{after_timestamp}"
        label_desc = "全部邮件"
    else:
        query = f"after:{after_timestamp} category:promotions"
        label_desc = "促销邮件"

    logger.info(f"扫描最近 {days} 天的{label_desc}")
    print(f"\n📬 正在扫描最近 {days} 天的{label_desc}...")

    message_stubs = _list_all_messages(service, query)
    total = len(message_stubs)
    logger.info(f"共找到 {total} 封邮件，开始批量解析...")
    print(f"   共找到 {total} 封邮件，正在批量解析详情...\n")

    if total == 0:
        return []

    emails = _fetch_messages_batch(service, message_stubs)

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


def _fetch_messages_batch(service, message_stubs: list[dict]) -> list[dict]:
    """
    使用 Gmail 批量 API 获取邮件详情，返回原始 Gmail API 响应列表。
    每批最多 100 封，比逐封请求快约 10 倍。
    """
    results = []

    def callback(request_id, response, exception):
        if exception is not None:
            logger.warning(f"批量请求失败（request_id={request_id}）：{exception}")
            return
        try:
            parsed = _parse_message(response)
            if parsed:
                results.append(parsed)
        except Exception as e:
            logger.warning(f"邮件解析失败：{e}")

    for batch_start in range(0, len(message_stubs), MAX_BATCH_SIZE):
        batch_stubs = message_stubs[batch_start:batch_start + MAX_BATCH_SIZE]
        batch = service.new_batch_http_request(callback=callback)

        for stub in batch_stubs:
            batch.add(
                service.users().messages().get(
                    userId="me",
                    id=stub["id"],
                    format="full",
                )
            )

        try:
            batch.execute()
        except Exception as e:
            logger.error(f"批量请求执行失败：{e}")

    return results


def _list_all_messages(service, query: str) -> list[dict]:
    """分页获取所有符合查询条件的邮件存根。"""
    messages = []
    page_token = None

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
        body_text, body_html = _extract_body(payload)

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
            "body_text": body_text,
            "body_html": body_html,
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


def _extract_body(payload: dict) -> tuple[str, str]:
    """递归提取邮件正文（纯文本和 HTML）。"""
    body_text, body_html = "", ""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        body_text = _decode_base64(body_data)
    elif mime_type == "text/html" and body_data:
        body_html = _decode_base64(body_data)
    elif "parts" in payload:
        for part in payload["parts"]:
            pt, ph = _extract_body(part)
            if pt and not body_text:
                body_text = pt
            if ph and not body_html:
                body_html = ph

    return body_text, body_html


def _decode_base64(data: str) -> str:
    """解码 Gmail API 使用的 URL-safe Base64 编码。"""
    try:
        import base64
        padded = data + "=" * (4 - len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"Base64 解码失败：{e}")
        return ""
