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

MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_SLEEP = 0.12  # 每封请求之间休眠（约 8 req/s，不触发并发限制）
PROGRESS_INTERVAL = 20  # 每处理多少封打印一次进度


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
        query = f"{date_filter}".strip() or ""
        label_desc = "全部邮件"
    else:
        query = f"{date_filter}category:promotions"
        label_desc = "促销邮件"

    logger.info(f"扫描{time_desc}的{label_desc}")
    print(f"\n📬 正在扫描{time_desc}的{label_desc}...")

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
    逐封获取邮件 metadata，遇到 429 自动退避重试。
    放弃批量 API 是因为 Gmail 对同一用户有并发连接上限，
    批量请求在服务器端并行执行，很容易触发 429 并丢失数据。
    """
    results = []
    total = len(message_stubs)

    for i, stub in enumerate(message_stubs):
        if i > 0 and i % PROGRESS_INTERVAL == 0:
            print(f"   进度：{i}/{total} 封...")

        for attempt in range(MAX_RETRIES):
            try:
                msg = service.users().messages().get(
                    userId="me",
                    id=stub["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "List-Unsubscribe",
                                     "List-Unsubscribe-Post", "Date"],
                ).execute()
                parsed = _parse_message(msg)
                if parsed:
                    results.append(parsed)
                break
            except HttpError as e:
                if e.resp.status == 429:
                    wait = RETRY_DELAY * (attempt + 1)
                    logger.debug(f"429 速率限制，{wait}s 后重试（第 {attempt+1} 次）...")
                    time.sleep(wait)
                elif e.resp.status in (500, 503):
                    wait = RETRY_DELAY * (attempt + 1)
                    logger.warning(f"服务器错误 {e.resp.status}，{wait}s 后重试...")
                    time.sleep(wait)
                else:
                    logger.warning(f"获取邮件失败（{stub['id']}）：{e}")
                    break
            except Exception as e:
                logger.warning(f"邮件解析失败（{stub['id']}）：{e}")
                break

        time.sleep(REQUEST_SLEEP)

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


