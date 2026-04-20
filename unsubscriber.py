# -*- coding: utf-8 -*-
"""
退订执行模块 - 通过多种方式实际执行退订操作
支持三种退订方式（按优先级）：
1. List-Unsubscribe-Post（RFC 8058 一键退订，最标准）
2. List-Unsubscribe mailto（通过 Gmail API 实际发送退订邮件）
3. 从邮件正文中提取退订链接（点击链接退订）

退订成功后支持：
- 给该发件人所有邮件打「已退订」标签
- 可选：归档（移出收件箱）该发件人的历史邮件
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

UNSUBSCRIBE_LABEL_NAME = "已退订"


# ────────────────────────────────────────────────────────────────
#  解析 List-Unsubscribe 头部
# ────────────────────────────────────────────────────────────────

def get_list_unsubscribe_url(headers_or_value) -> dict:
    """解析 List-Unsubscribe 头部，提取 HTTP URL 和 mailto 地址。"""
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
    """解析 mailto: 字符串，提取邮箱和 subject 参数。"""
    rest = mailto_str[7:] if mailto_str.startswith("mailto:") else mailto_str
    if "?" in rest:
        email_part, params_str = rest.split("?", 1)
        params = urllib.parse.parse_qs(params_str)
        subject = params.get("subject", [None])[0]
    else:
        email_part, subject = rest, None
    return {"email": email_part.strip(), "subject": subject}


# ────────────────────────────────────────────────────────────────
#  退订方式 1：一键退订（RFC 8058 POST）
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_one_click(url: str) -> dict:
    """向 URL 发送 POST 请求，执行 RFC 8058 一键退订。"""
    logger.info(f"尝试一键退订（POST）：{url}")
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
            "message": f"一键退订{'成功' if success else '失败'}（HTTP {response.status_code}）",
            "status_code": response.status_code,
        }
    except requests.exceptions.Timeout:
        return {"success": False, "method": "one_click_post", "message": "请求超时", "status_code": None}
    except Exception as e:
        return {"success": False, "method": "one_click_post", "message": f"连接失败：{e}", "status_code": None}


# ────────────────────────────────────────────────────────────────
#  退订方式 2：发送退订邮件（通过 Gmail API）
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_mailto(mailto_info: dict, service=None) -> dict:
    """
    通过 Gmail API 实际发送退订邮件。
    需要传入 service 对象（由 auth.get_gmail_service() 提供）。
    """
    email_addr = mailto_info.get("mailto_email", "")
    subject = mailto_info.get("mailto_subject") or "unsubscribe"

    if not email_addr:
        return {"success": False, "method": "mailto", "message": "无法解析退订邮箱地址"}

    if service is None:
        return {"success": False, "method": "mailto",
                "message": "未提供 Gmail service，无法发送退订邮件"}

    try:
        raw = _build_email_raw(to_email=email_addr, subject=subject)
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        logger.info(f"退订邮件已通过 Gmail API 发送至：{email_addr}")
        return {
            "success": True,
            "method": "mailto",
            "message": f"退订邮件已发送至 {email_addr}（主题：{subject}）",
        }
    except Exception as e:
        safe = re.sub(r"(?i)\b(sk|pk|Bearer|access_token)[=:\s]\S+", "[REDACTED]", str(e))
        logger.error(f"发送退订邮件失败：{safe}")
        return {"success": False, "method": "mailto", "message": f"发送退订邮件失败：{e}"}


def _build_email_raw(to_email: str, subject: str) -> str:
    """构造退订邮件并转为 Gmail API 所需的 base64 格式。"""
    msg = MIMEText("Please unsubscribe me from your mailing list.\n\nThank you.")
    msg["to"] = to_email
    msg["subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


# ────────────────────────────────────────────────────────────────
#  退订方式 3：从邮件正文提取退订链接
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_link(html_body: str) -> dict:
    """从邮件 HTML 正文中提取退订链接，发送 GET 请求。"""
    if not html_body:
        return {"success": False, "method": "link_click",
                "message": "邮件正文为空，无法提取退订链接", "found_url": None, "status_code": None}

    unsubscribe_url = _find_unsubscribe_link(html_body)
    if not unsubscribe_url:
        return {"success": False, "method": "link_click",
                "message": "未在邮件正文中找到退订链接", "found_url": None, "status_code": None}

    logger.info(f"找到退订链接：{unsubscribe_url[:80]}")
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
            "message": f"退订链接已访问（HTTP {response.status_code}）",
            "found_url": unsubscribe_url,
            "status_code": response.status_code,
        }
    except Exception as e:
        return {"success": False, "method": "link_click",
                "message": f"访问退订链接失败：{e}", "found_url": unsubscribe_url, "status_code": None}


def _fetch_html_body(service, message_id: str) -> str:
    """按需获取单封邮件的 HTML 正文（扫描阶段只拉了元数据时使用）。"""
    if not service or not message_id:
        return ""
    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        _, html = _extract_body_from_payload(msg.get("payload", {}))
        return html
    except Exception as e:
        logger.warning(f"按需获取邮件正文失败（{message_id}）：{e}")
        return ""


def _extract_body_from_payload(payload: dict) -> tuple[str, str]:
    """递归提取邮件正文（纯文本和 HTML）。"""
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
    """从 HTML 中找到最可能是退订链接的 URL（优先取最后一个）。"""
    try:
        soup = BeautifulSoup(html_body, "lxml")
    except Exception:
        soup = BeautifulSoup(html_body, "html.parser")

    candidates = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        if not (href.startswith("http://") or href.startswith("https://")):
            continue
        text = a_tag.get_text(strip=True).lower()
        for kw in UNSUBSCRIBE_LINK_KEYWORDS:
            if kw in text or kw in href.lower():
                candidates.append(href)
                break

    return candidates[-1] if candidates else None


# ────────────────────────────────────────────────────────────────
#  Gmail 标签管理
# ────────────────────────────────────────────────────────────────

def create_or_get_label(service, label_name: str = UNSUBSCRIBE_LABEL_NAME) -> str:
    """
    在 Gmail 中获取或创建指定名称的标签，返回标签 ID。
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
    logger.info(f"已创建 Gmail 标签：{label_name}（ID: {new_label['id']}）")
    return new_label["id"]


def label_sender_emails(service, message_ids: list, label_id: str) -> None:
    """给指定邮件列表打上标签。"""
    for msg_id in message_ids:
        try:
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [label_id]},
            ).execute()
        except Exception as e:
            logger.warning(f"给邮件 {msg_id} 打标签失败：{e}")
    logger.debug(f"已给 {len(message_ids)} 封邮件打上标签 {label_id}")


def archive_sender_emails(service, message_ids: list) -> None:
    """将指定邮件从收件箱移到归档（移除 INBOX 标签）。"""
    for msg_id in message_ids:
        try:
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["INBOX"]},
            ).execute()
        except Exception as e:
            logger.warning(f"归档邮件 {msg_id} 失败：{e}")
    logger.debug(f"已归档 {len(message_ids)} 封邮件")


# ────────────────────────────────────────────────────────────────
#  统一退订入口
# ────────────────────────────────────────────────────────────────

def execute_unsubscribe(
    sender_group: dict,
    service=None,
    dry_run: bool = True,
    archive: bool = False,
) -> dict:
    """
    对一个发件人执行退订操作（统一入口）。

    Args:
        sender_group: classifier.classify_emails() 返回的发件人分组字典
        service:      Gmail API 服务对象（退订后打标签/归档需要）
        dry_run:      True 表示试运行（只分析，不实际执行）
        archive:      True 表示退订成功后同时归档该发件人的历史邮件
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

    # ── 试运行模式 ──
    if dry_run:
        available_methods = []
        if list_unsub_raw:
            unsub_info = get_list_unsubscribe_url(list_unsub_raw)
            if unsub_info["http_url"]:
                has_post = list_unsub_post and "List-Unsubscribe=One-Click" in list_unsub_post
                method_name = "一键退订（POST）" if has_post else "HTTP 链接（GET）"
                available_methods.append(f"✓ {method_name}：{unsub_info['http_url'][:60]}...")
            if unsub_info["mailto_email"]:
                available_methods.append(f"✓ mailto 退订：{unsub_info['mailto_email']}")
        if not html_body:
            sample_id = sender_group.get("sample_id", "")
            html_body = _fetch_html_body(service, sample_id)
        if html_body:
            link = _find_unsubscribe_link(html_body)
            if link:
                available_methods.append(f"✓ 正文退订链接：{link[:60]}...")

        result["success"] = bool(available_methods)
        result["message"] = "试运行：发现以下退订方式" if available_methods else "试运行：未找到可用退订方式"
        result["details"]["available_methods"] = available_methods
        return result

    # ── 实际执行 ──
    logger.info(f"开始退订：{sender_email}")

    # 方式 1 & 2：List-Unsubscribe
    if list_unsub_raw:
        unsub_info = get_list_unsubscribe_url(list_unsub_raw)

        if unsub_info["http_url"]:
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
                        "message": f"HTTP GET（状态码 {resp.status_code}）",
                        "status_code": resp.status_code,
                    }
                except Exception as e:
                    attempt = {"success": False, "method": "http_get",
                               "message": f"HTTP GET 失败：{e}", "status_code": None}

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

    # 方式 3：正文链接（扫描时未拉正文，此处按需获取）
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

    result["message"] = "未找到可用的退订方式"
    logger.warning(f"退订失败：{sender_email}")
    return result


def _post_unsubscribe_actions(service, message_ids: list, archive: bool) -> None:
    """退订成功后：打标签 + 可选归档。"""
    if not service or not message_ids:
        return
    try:
        label_id = create_or_get_label(service)
        label_sender_emails(service, message_ids, label_id)
        logger.info(f"已给 {len(message_ids)} 封邮件打上「已退订」标签")
    except Exception as e:
        logger.warning(f"打标签失败（不影响退订结果）：{e}")

    if archive:
        try:
            archive_sender_emails(service, message_ids)
            logger.info(f"已归档 {len(message_ids)} 封邮件")
        except Exception as e:
            logger.warning(f"归档失败（不影响退订结果）：{e}")
