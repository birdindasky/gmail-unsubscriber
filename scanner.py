# -*- coding: utf-8 -*-
"""
邮件扫描模块 - 从 Gmail 获取邮件列表及详情
负责与 Gmail API 通信，拉取指定天数内的邮件，并解析出可供分类使用的结构化数据。
"""

import base64
import email
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Gmail API 单次最多返回的邮件数（官方上限 500）
MAX_RESULTS_PER_PAGE = 500

# API 请求失败时的重试次数
MAX_RETRIES = 3

# 重试等待时间（秒）
RETRY_DELAY = 2


def _retry_request(func, *args, **kwargs):
    """带重试机制的 API 请求包装器。"""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            if e.resp.status in (429, 500, 503):
                # 速率限制或服务器错误，等待后重试
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(f"API 请求失败（状态码 {e.resp.status}），{wait}s 后重试...")
                time.sleep(wait)
                last_error = e
            else:
                raise
    raise last_error


def scan_emails(service, days: int = 30) -> list[dict]:
    """
    扫描最近 N 天内收到的所有邮件，返回邮件详情列表。

    Args:
        service: Gmail API 服务对象（由 auth.get_gmail_service() 提供）
        days: 向前扫描的天数，默认 30 天

    Returns:
        list[dict]: 邮件详情列表，每条记录包含：
            - id: 邮件 ID
            - subject: 主题
            - sender: 发件人（格式："名字 <邮箱>" 或 "邮箱"）
            - sender_email: 仅发件人邮箱地址
            - sender_domain: 发件人域名
            - date: 发件日期字符串
            - list_unsubscribe: List-Unsubscribe 头部值（可能为 None）
            - list_unsubscribe_post: List-Unsubscribe-Post 头部值（可能为 None）
            - snippet: 邮件摘要（前 200 字符）
            - body_text: 纯文本正文
            - body_html: HTML 正文
            - labels: Gmail 标签列表
    """
    # 计算起始日期（Unix 时间戳）
    since_date = datetime.now() - timedelta(days=days)
    after_timestamp = int(since_date.timestamp())
    query = f"after:{after_timestamp}"

    logger.info(f"开始扫描最近 {days} 天的邮件（{since_date.strftime('%Y-%m-%d')} 至今）")
    print(f"\n📬 正在扫描最近 {days} 天的邮件...")

    # 获取邮件 ID 列表
    message_ids = _list_all_messages(service, query)
    total = len(message_ids)
    logger.info(f"共找到 {total} 封邮件，开始逐封解析...")
    print(f"   共找到 {total} 封邮件，正在解析详情...\n")

    emails = []
    for idx, msg_stub in enumerate(message_ids, 1):
        if idx % 50 == 0 or idx == total:
            print(f"   进度：{idx}/{total}", end="\r", flush=True)

        detail = get_email_detail(service, msg_stub["id"])
        if detail:
            emails.append(detail)

    print(f"\n✅ 扫描完成，成功解析 {len(emails)} 封邮件\n")
    logger.info(f"扫描完成，解析了 {len(emails)}/{total} 封邮件")
    return emails


def _list_all_messages(service, query: str) -> list[dict]:
    """
    分页获取所有符合查询条件的邮件 ID。

    Args:
        service: Gmail API 服务对象
        query: Gmail 搜索查询字符串

    Returns:
        list[dict]: 包含 id 和 threadId 的字典列表
    """
    messages = []
    page_token = None

    while True:
        kwargs = {
            "userId": "me",
            "q": query,
            "maxResults": MAX_RESULTS_PER_PAGE,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            response = _retry_request(
                service.users().messages().list(**kwargs).execute
            )
        except HttpError as e:
            logger.error(f"获取邮件列表失败：{e}")
            break

        batch = response.get("messages", [])
        messages.extend(batch)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    logger.debug(f"共获取到 {len(messages)} 个邮件 ID")
    return messages


def get_email_detail(service, msg_id: str) -> Optional[dict]:
    """
    获取单封邮件的完整详情。

    Args:
        service: Gmail API 服务对象
        msg_id: 邮件 ID

    Returns:
        dict: 邮件详情字典，解析失败时返回 None
    """
    try:
        msg = _retry_request(
            service.users().messages().get(
                userId="me",
                id=msg_id,
                format="full"
            ).execute
        )
    except HttpError as e:
        logger.warning(f"获取邮件 {msg_id} 详情失败：{e}")
        return None

    try:
        return _parse_message(msg)
    except Exception as e:
        logger.warning(f"解析邮件 {msg_id} 失败：{e}")
        return None


def _parse_message(msg: dict) -> dict:
    """
    将 Gmail API 返回的原始邮件对象解析为结构化字典。

    Args:
        msg: Gmail API 返回的原始邮件对象

    Returns:
        dict: 结构化邮件数据
    """
    payload = msg.get("payload", {})
    headers = {
        h["name"].lower(): h["value"]
        for h in payload.get("headers", [])
    }

    # 解析发件人
    sender_raw = headers.get("from", "")
    sender_email, sender_domain = _parse_sender(sender_raw)

    # 解析邮件正文
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
        # 原始 headers 供高级用途
        "_headers": headers,
    }


def _parse_sender(sender_raw: str) -> tuple[str, str]:
    """
    从发件人字段提取邮箱地址和域名。

    Args:
        sender_raw: 原始发件人字段，如 "Google <no-reply@google.com>"

    Returns:
        tuple: (邮箱地址, 域名)
    """
    # 尝试提取 <> 中的邮箱
    if "<" in sender_raw and ">" in sender_raw:
        start = sender_raw.index("<") + 1
        end = sender_raw.index(">")
        email_addr = sender_raw[start:end].strip().lower()
    else:
        email_addr = sender_raw.strip().lower()

    # 提取域名
    if "@" in email_addr:
        domain = email_addr.split("@")[-1]
    else:
        domain = ""

    return email_addr, domain


def _extract_body(payload: dict) -> tuple[str, str]:
    """
    递归提取邮件正文（纯文本和 HTML）。

    Args:
        payload: Gmail API 的 payload 对象

    Returns:
        tuple: (纯文本正文, HTML 正文)
    """
    body_text = ""
    body_html = ""

    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        body_text = _decode_base64(body_data)
    elif mime_type == "text/html" and body_data:
        body_html = _decode_base64(body_data)
    elif "parts" in payload:
        for part in payload["parts"]:
            part_text, part_html = _extract_body(part)
            if part_text and not body_text:
                body_text = part_text
            if part_html and not body_html:
                body_html = part_html

    return body_text, body_html


def _decode_base64(data: str) -> str:
    """
    解码 Gmail API 使用的 URL-safe Base64 编码。

    Args:
        data: Base64 编码的字符串

    Returns:
        str: 解码后的文本
    """
    try:
        # Gmail 使用 URL-safe base64，需要补齐填充
        padded = data + "=" * (4 - len(data) % 4)
        decoded_bytes = base64.urlsafe_b64decode(padded)
        return decoded_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"Base64 解码失败：{e}")
        return ""
