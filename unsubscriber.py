# -*- coding: utf-8 -*-
"""
退订执行模块 - 通过多种方式实际执行退订操作
支持三种退订方式（按优先级）：
1. List-Unsubscribe-Post（一键退订，最标准）
2. List-Unsubscribe mailto（发邮件退订）
3. 从邮件正文中提取退订链接（点击链接退订）
"""

import logging
import re
import smtplib
import time
import urllib.parse
from email.mime.text import MIMEText
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# HTTP 请求超时（秒）
HTTP_TIMEOUT = 10

# 请求间隔（秒），避免发送太快被视为机器人
REQUEST_INTERVAL = 2

# 退订链接识别关键词
UNSUBSCRIBE_LINK_KEYWORDS = [
    "unsubscribe", "opt-out", "optout", "opt_out",
    "remove", "cancel", "退订", "取消订阅", "取消接收",
    "退出", "不再接收", "停止接收",
]

# HTTP 请求头，模拟普通浏览器
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ────────────────────────────────────────────────────────────────
#  解析 List-Unsubscribe 头部
# ────────────────────────────────────────────────────────────────

def get_list_unsubscribe_url(headers_or_value) -> dict:
    """
    解析 List-Unsubscribe 头部，提取 HTTP URL 和 mailto 地址。

    List-Unsubscribe 格式可能为：
    - "<https://example.com/unsub>, <mailto:unsub@example.com>"
    - "<mailto:unsub@example.com?subject=unsubscribe>"
    - "<https://example.com/unsub>"

    Args:
        headers_or_value: 可以是字典（邮件 headers）或直接的 List-Unsubscribe 字符串值

    Returns:
        dict: {
            "http_url": str or None,   # HTTP 退订链接
            "mailto": str or None,     # mailto 退订地址（含 subject 参数）
            "mailto_email": str or None,  # 仅邮箱地址部分
            "mailto_subject": str or None,  # mailto subject 参数
            "has_one_click": bool,     # 是否支持一键退订 (RFC 8058)
        }
    """
    if isinstance(headers_or_value, dict):
        raw_value = headers_or_value.get("list-unsubscribe", "")
    else:
        raw_value = headers_or_value or ""

    result = {
        "http_url": None,
        "mailto": None,
        "mailto_email": None,
        "mailto_subject": None,
        "has_one_click": False,
    }

    if not raw_value:
        return result

    # 提取所有 <...> 中的值
    entries = re.findall(r"<([^>]+)>", raw_value)

    for entry in entries:
        entry = entry.strip()
        if entry.startswith("https://") or entry.startswith("http://"):
            if not result["http_url"]:
                result["http_url"] = entry
        elif entry.startswith("mailto:"):
            if not result["mailto"]:
                result["mailto"] = entry
                # 解析 mailto 中的邮箱和 subject
                parsed = _parse_mailto(entry)
                result["mailto_email"] = parsed["email"]
                result["mailto_subject"] = parsed["subject"]

    return result


def _parse_mailto(mailto_str: str) -> dict:
    """解析 mailto: 字符串，提取邮箱地址和参数。"""
    # 去掉 mailto: 前缀
    rest = mailto_str[7:] if mailto_str.startswith("mailto:") else mailto_str

    if "?" in rest:
        email_part, params_str = rest.split("?", 1)
        params = urllib.parse.parse_qs(params_str)
        subject = params.get("subject", [None])[0]
        body = params.get("body", [None])[0]
    else:
        email_part = rest
        subject = None
        body = None

    return {
        "email": email_part.strip(),
        "subject": subject,
        "body": body,
    }


# ────────────────────────────────────────────────────────────────
#  退订方式 1：一键退订（RFC 8058 POST 请求）
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_one_click(url: str) -> dict:
    """
    通过 RFC 8058 一键退订：向 URL 发送 POST 请求。
    这是最标准、最可靠的退订方式，不需要人工点击网页。

    Args:
        url: List-Unsubscribe 中的 HTTP URL

    Returns:
        dict: {
            "success": bool,
            "method": "one_click_post",
            "message": str,
            "status_code": int or None,
        }
    """
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

        if response.status_code in (200, 201, 202, 204):
            logger.info(f"一键退订成功（HTTP {response.status_code}）")
            return {
                "success": True,
                "method": "one_click_post",
                "message": f"一键退订请求已发送（HTTP {response.status_code}）",
                "status_code": response.status_code,
            }
        else:
            logger.warning(f"一键退订返回异常状态码：{response.status_code}")
            return {
                "success": False,
                "method": "one_click_post",
                "message": f"服务器返回 HTTP {response.status_code}",
                "status_code": response.status_code,
            }
    except requests.exceptions.Timeout:
        return {"success": False, "method": "one_click_post",
                "message": "请求超时", "status_code": None}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "method": "one_click_post",
                "message": f"连接失败：{e}", "status_code": None}
    except Exception as e:
        logger.error(f"一键退订异常：{e}")
        return {"success": False, "method": "one_click_post",
                "message": f"未知错误：{e}", "status_code": None}


# ────────────────────────────────────────────────────────────────
#  退订方式 2：发送退订邮件（mailto）
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_mailto(mailto_info: dict) -> dict:
    """
    通过发送邮件的方式退订。
    注意：此方式需要 SMTP 配置，macOS 上建议用 Gmail SMTP。
    简化实现：直接构造退订邮件内容并返回，需用户手动发送。

    Args:
        mailto_info: get_list_unsubscribe_url() 返回的字典

    Returns:
        dict: {
            "success": bool,
            "method": "mailto",
            "message": str,
            "mailto_address": str,
            "suggested_subject": str,
        }
    """
    email_addr = mailto_info.get("mailto_email", "")
    subject = mailto_info.get("mailto_subject", "unsubscribe")

    if not email_addr:
        return {
            "success": False,
            "method": "mailto",
            "message": "无法解析退订邮箱地址",
            "mailto_address": "",
            "suggested_subject": "",
        }

    logger.info(f"生成 mailto 退订信息：{email_addr}，主题：{subject}")

    # 返回退订信息（由调用方决定是否实际发送）
    return {
        "success": True,
        "method": "mailto",
        "message": f"退订邮件信息已生成，目标地址：{email_addr}",
        "mailto_address": email_addr,
        "suggested_subject": subject or "unsubscribe",
    }


# ────────────────────────────────────────────────────────────────
#  退订方式 3：从邮件正文提取退订链接
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_link(html_body: str) -> dict:
    """
    从邮件 HTML 正文中提取退订链接，然后发送 GET 请求。

    提取规则：
    1. 查找文本含退订关键词的 <a> 标签
    2. 验证链接为有效 HTTP URL
    3. 优先选择最底部的退订链接（通常更准确）

    Args:
        html_body: 邮件的 HTML 正文内容

    Returns:
        dict: {
            "success": bool,
            "method": "link_click",
            "message": str,
            "found_url": str or None,
            "status_code": int or None,
        }
    """
    if not html_body:
        return {
            "success": False,
            "method": "link_click",
            "message": "邮件正文为空，无法提取退订链接",
            "found_url": None,
            "status_code": None,
        }

    # 从 HTML 中提取退订链接
    unsubscribe_url = _find_unsubscribe_link(html_body)

    if not unsubscribe_url:
        return {
            "success": False,
            "method": "link_click",
            "message": "未在邮件正文中找到退订链接",
            "found_url": None,
            "status_code": None,
        }

    logger.info(f"找到退订链接：{unsubscribe_url[:80]}...")

    # 发送 GET 请求模拟点击
    try:
        response = requests.get(
            unsubscribe_url,
            headers=DEFAULT_HEADERS,
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )
        time.sleep(REQUEST_INTERVAL)

        if response.status_code in (200, 201, 202, 204):
            return {
                "success": True,
                "method": "link_click",
                "message": f"退订链接已访问（HTTP {response.status_code}）",
                "found_url": unsubscribe_url,
                "status_code": response.status_code,
            }
        else:
            return {
                "success": False,
                "method": "link_click",
                "message": f"访问退订链接返回 HTTP {response.status_code}",
                "found_url": unsubscribe_url,
                "status_code": response.status_code,
            }
    except requests.exceptions.Timeout:
        return {"success": False, "method": "link_click",
                "message": "访问退订链接超时", "found_url": unsubscribe_url,
                "status_code": None}
    except Exception as e:
        logger.error(f"访问退订链接异常：{e}")
        return {"success": False, "method": "link_click",
                "message": f"访问退订链接失败：{e}", "found_url": unsubscribe_url,
                "status_code": None}


def _find_unsubscribe_link(html_body: str) -> Optional[str]:
    """
    从 HTML 中找到最可能是退订的链接。

    Args:
        html_body: HTML 字符串

    Returns:
        str or None: 退订链接 URL
    """
    try:
        soup = BeautifulSoup(html_body, "lxml")
    except Exception:
        try:
            soup = BeautifulSoup(html_body, "html.parser")
        except Exception:
            return None

    candidates = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        text = a_tag.get_text(strip=True).lower()

        # 跳过非 HTTP 链接
        if not (href.startswith("http://") or href.startswith("https://")):
            continue

        # 检查链接文本或 URL 本身是否含退订关键词
        href_lower = href.lower()
        for keyword in UNSUBSCRIBE_LINK_KEYWORDS:
            if keyword in text or keyword in href_lower:
                candidates.append(href)
                break

    if not candidates:
        return None

    # 返回最后找到的退订链接（通常在邮件底部，更准确）
    return candidates[-1]


# ────────────────────────────────────────────────────────────────
#  统一退订入口
# ────────────────────────────────────────────────────────────────

def execute_unsubscribe(sender_group: dict, dry_run: bool = True) -> dict:
    """
    对一个发件人执行退订操作（统一入口）。
    按优先级尝试三种退订方式：
    1. List-Unsubscribe HTTP 一键退订
    2. List-Unsubscribe mailto
    3. 邮件正文退订链接

    Args:
        sender_group: classifier.classify_emails() 返回的发件人分组字典，需包含：
            - sender_email: 发件人邮箱
            - sender: 发件人完整信息
            - list_unsubscribe: List-Unsubscribe 头部值
            - list_unsubscribe_post: List-Unsubscribe-Post 头部值
            - sample_html: 邮件 HTML 正文样本
        dry_run: True 表示试运行（只打印，不实际执行）

    Returns:
        dict: {
            "sender_email": str,
            "sender": str,
            "dry_run": bool,
            "attempted_method": str or None,
            "success": bool,
            "message": str,
            "details": dict,  # 各方式的尝试结果
        }
    """
    sender_email = sender_group.get("sender_email", "unknown")
    sender = sender_group.get("sender", sender_email)
    list_unsub_raw = sender_group.get("list_unsubscribe")
    list_unsub_post = sender_group.get("list_unsubscribe_post", "")
    html_body = sender_group.get("sample_html", "")

    result = {
        "sender_email": sender_email,
        "sender": sender,
        "dry_run": dry_run,
        "attempted_method": None,
        "success": False,
        "message": "",
        "details": {},
    }

    if dry_run:
        # 试运行：分析可用的退订方式，不实际执行
        available_methods = []
        if list_unsub_raw:
            unsub_info = get_list_unsubscribe_url(list_unsub_raw)
            if unsub_info["http_url"]:
                has_post = list_unsub_post and "List-Unsubscribe=One-Click" in list_unsub_post
                method_name = "一键退订（POST）" if has_post else "HTTP 链接（GET）"
                available_methods.append(f"✓ {method_name}：{unsub_info['http_url'][:60]}...")
            if unsub_info["mailto_email"]:
                available_methods.append(f"✓ mailto 退订：{unsub_info['mailto_email']}")
        if html_body:
            link = _find_unsubscribe_link(html_body)
            if link:
                available_methods.append(f"✓ 正文退订链接：{link[:60]}...")

        if available_methods:
            result["success"] = True
            result["message"] = "试运行：发现以下退订方式（实际未执行）"
            result["details"]["available_methods"] = available_methods
        else:
            result["message"] = "试运行：未找到可用的退订方式"
            result["details"]["available_methods"] = []

        logger.info(f"[试运行] {sender_email}: {result['message']}")
        return result

    # 实际执行退订
    logger.info(f"开始退订：{sender_email}")

    # 方式 1：List-Unsubscribe HTTP（优先）
    if list_unsub_raw:
        unsub_info = get_list_unsubscribe_url(list_unsub_raw)

        if unsub_info["http_url"]:
            # 检查是否支持一键退订（RFC 8058）
            has_one_click = (
                list_unsub_post
                and "List-Unsubscribe=One-Click" in list_unsub_post
            )

            if has_one_click:
                attempt = unsubscribe_via_one_click(unsub_info["http_url"])
            else:
                # 降级为 GET 请求
                try:
                    resp = requests.get(
                        unsub_info["http_url"],
                        headers=DEFAULT_HEADERS,
                        timeout=HTTP_TIMEOUT,
                        allow_redirects=True,
                    )
                    time.sleep(REQUEST_INTERVAL)
                    attempt = {
                        "success": resp.status_code in (200, 201, 202, 204),
                        "method": "http_get",
                        "message": f"HTTP GET 请求（状态码 {resp.status_code}）",
                        "status_code": resp.status_code,
                    }
                except Exception as e:
                    attempt = {
                        "success": False,
                        "method": "http_get",
                        "message": f"HTTP GET 失败：{e}",
                        "status_code": None,
                    }

            result["details"]["http"] = attempt
            if attempt["success"]:
                result["attempted_method"] = attempt["method"]
                result["success"] = True
                result["message"] = attempt["message"]
                return result

        # 方式 2：mailto 退订（备选）
        if unsub_info["mailto_email"]:
            attempt = unsubscribe_via_mailto(unsub_info)
            result["details"]["mailto"] = attempt
            if attempt["success"]:
                result["attempted_method"] = "mailto"
                result["success"] = True
                result["message"] = (
                    f"请手动发送退订邮件至：{attempt['mailto_address']}\n"
                    f"   主题：{attempt['suggested_subject']}"
                )
                return result

    # 方式 3：从正文提取退订链接（最后手段）
    if html_body:
        attempt = unsubscribe_via_link(html_body)
        result["details"]["link"] = attempt
        if attempt["success"]:
            result["attempted_method"] = "link_click"
            result["success"] = True
            result["message"] = attempt["message"]
            return result

    # 所有方式都失败了
    result["message"] = "未找到可用的退订方式（无 List-Unsubscribe 头部，也未找到退订链接）"
    logger.warning(f"退订失败：{sender_email}：{result['message']}")
    return result
