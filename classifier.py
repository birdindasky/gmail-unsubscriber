# -*- coding: utf-8 -*-
"""
分类模块 - 判断邮件是否应该退订
采用「白名单优先 + 多条件叠加」策略，尽量避免误退订重要邮件。

判断逻辑（按优先级）：
1. 白名单命中 → 绝对不退订
2. 含敏感关键词 → 绝对不退订
3. 同时满足以下 2+ 条件 → 标记为应退订：
   - 含广告关键词
   - 发件人含可疑关键词
   - 含 List-Unsubscribe 头部
   - 带有 Gmail CATEGORY_PROMOTIONS 标签
"""

import logging
import re
from typing import Optional

import config

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
#  白名单检查
# ────────────────────────────────────────────────────────────────

def is_whitelisted(sender: str) -> bool:
    """
    检查发件人是否在白名单中。

    白名单匹配规则：
    - 完整域名匹配（如 "google.com"）
    - 子域名匹配（如 "mail.google.com" 匹配白名单中的 "google.com"）
    - 顶级域名后缀匹配（如 "edu" 匹配所有 .edu 结尾的域名）

    Args:
        sender: 发件人邮箱地址或域名

    Returns:
        bool: True 表示在白名单内，不应退订
    """
    if not sender:
        return False

    # 提取域名部分
    if "@" in sender:
        domain = sender.split("@")[-1].lower().strip()
    else:
        domain = sender.lower().strip()

    # 去掉尖括号等多余字符
    domain = re.sub(r"[<>\s]", "", domain)

    all_whitelist = config.get_all_whitelist_domains()

    for white_domain in all_whitelist:
        white_domain = white_domain.lower().strip()
        # 完整匹配
        if domain == white_domain:
            logger.debug(f"白名单完整匹配：{domain} == {white_domain}")
            return True
        # 子域名匹配（domain 以 .white_domain 结尾）
        if domain.endswith("." + white_domain):
            logger.debug(f"白名单子域名匹配：{domain} 属于 {white_domain}")
            return True
        # 顶级域名后缀匹配（如白名单中有 "edu"，匹配所有 .edu 结尾）
        if "." not in white_domain and domain.endswith("." + white_domain):
            logger.debug(f"白名单后缀匹配：{domain} 结尾为 .{white_domain}")
            return True

    return False


# ────────────────────────────────────────────────────────────────
#  敏感内容检查
# ────────────────────────────────────────────────────────────────

def is_sensitive(email_data: dict) -> bool:
    """
    检查邮件是否包含敏感关键词（验证码、订单、银行账单等）。
    含敏感词的邮件绝对不退订，哪怕看起来像广告。

    Args:
        email_data: scanner 模块返回的邮件详情字典

    Returns:
        bool: True 表示含敏感内容，不应退订
    """
    subject = email_data.get("subject", "").lower()
    snippet = email_data.get("snippet", "").lower()
    body_text = (email_data.get("body_text", "") or "").lower()

    check_text = f"{subject} {snippet} {body_text}"

    for keyword in config.SENSITIVE_KEYWORDS:
        if keyword.lower() in check_text:
            logger.debug(f"检测到敏感关键词：「{keyword}」")
            return True

    return False


# ────────────────────────────────────────────────────────────────
#  广告内容检查
# ────────────────────────────────────────────────────────────────

def is_advertisement(email_data: dict) -> tuple[bool, list[str]]:
    """
    检查邮件是否为广告/促销邮件，并返回命中的条件列表。
    需要满足 2 个或以上条件才判定为广告（减少误判）。

    条件列表：
    1. 主题/正文含广告关键词
    2. 发件人名称或地址含可疑关键词
    3. 存在 List-Unsubscribe 邮件头部
    4. Gmail 自动分类为促销邮件（CATEGORY_PROMOTIONS 标签）
    5. 发件人地址为 noreply/no-reply 类型

    Args:
        email_data: scanner 模块返回的邮件详情字典

    Returns:
        tuple[bool, list[str]]:
            - bool: True 表示判定为广告
            - list[str]: 命中的条件说明列表（用于日志和用户展示）
    """
    matched_conditions = []

    subject = email_data.get("subject", "").lower()
    snippet = email_data.get("snippet", "").lower()
    body_text = (email_data.get("body_text", "") or "").lower()
    sender = email_data.get("sender", "").lower()
    sender_email = email_data.get("sender_email", "").lower()
    labels = email_data.get("labels", [])
    list_unsub = email_data.get("list_unsubscribe")

    # 条件 1：主题或正文含广告关键词
    check_text = f"{subject} {snippet} {body_text}"
    matched_ad_keywords = [
        kw for kw in config.AD_KEYWORDS
        if kw.lower() in check_text
    ]
    if matched_ad_keywords:
        matched_conditions.append(
            f"含广告关键词：{', '.join(matched_ad_keywords[:3])}"
            + ("..." if len(matched_ad_keywords) > 3 else "")
        )

    # 条件 2：发件人含可疑关键词
    sender_check = f"{sender} {sender_email}"
    matched_sender_kws = [
        kw for kw in config.SUSPICIOUS_SENDER_KEYWORDS
        if kw.lower() in sender_check
    ]
    if matched_sender_kws:
        matched_conditions.append(
            f"发件人含可疑关键词：{', '.join(matched_sender_kws[:2])}"
        )

    # 条件 3：存在 List-Unsubscribe 头部
    if list_unsub:
        matched_conditions.append("含 List-Unsubscribe 头部")

    # 条件 4：Gmail 自动分类为促销
    if "CATEGORY_PROMOTIONS" in labels:
        matched_conditions.append("Gmail 自动归类为促销邮件")

    # 条件 5：发件人是 noreply 类型
    local_part = sender_email.split("@")[0] if "@" in sender_email else sender_email
    if re.match(r"^(noreply|no.reply|donotreply|do.not.reply)$", local_part, re.I):
        matched_conditions.append("发件人为 noreply 地址")

    # 需要满足 2+ 条件才判定为广告（单条件太容易误判）
    is_ad = len(matched_conditions) >= 2

    if is_ad:
        logger.debug(
            f"判定为广告（{len(matched_conditions)} 条件命中）：{email_data.get('subject', '')}"
        )

    return is_ad, matched_conditions


# ────────────────────────────────────────────────────────────────
#  最终决策
# ────────────────────────────────────────────────────────────────

def should_unsubscribe(email_data: dict) -> tuple[bool, str]:
    """
    综合所有规则，给出是否应该退订的最终判断。

    判断流程：
    1. 白名单命中 → 否（绝对保护）
    2. 含敏感关键词 → 否（保护重要邮件）
    3. 判定为广告 → 是（附上理由）
    4. 默认 → 否（保守策略）

    Args:
        email_data: scanner 模块返回的邮件详情字典

    Returns:
        tuple[bool, str]:
            - bool: True 表示建议退订
            - str: 判断理由（用于展示给用户）
    """
    sender_email = email_data.get("sender_email", "")
    subject = email_data.get("subject", "（无主题）")

    # 第一道防线：白名单检查
    if is_whitelisted(sender_email):
        reason = f"发件人域名在白名单中（{email_data.get('sender_domain', '')}）"
        logger.debug(f"白名单保护：{subject}")
        return False, reason

    # 第二道防线：敏感内容检查
    if is_sensitive(email_data):
        reason = "邮件含敏感关键词（验证码/订单/账单等），已跳过"
        logger.debug(f"敏感内容保护：{subject}")
        return False, reason

    # 广告判断
    is_ad, conditions = is_advertisement(email_data)
    if is_ad:
        reason = "命中广告特征：" + "；".join(conditions)
        return True, reason

    # 默认：不退订（保守策略）
    reason = "未达到广告判定标准（需至少 2 项特征），跳过"
    return False, reason


# ────────────────────────────────────────────────────────────────
#  批量分类辅助函数
# ────────────────────────────────────────────────────────────────

def classify_emails(emails: list[dict]) -> dict[str, list]:
    """
    对邮件列表进行批量分类，按发件人归组。

    Args:
        emails: scanner 模块返回的邮件详情列表

    Returns:
        dict: 包含两个键：
            - "to_unsubscribe": 建议退订的发件人列表（去重），
              每项为 {"sender_email", "sender", "count", "reasons", "sample_subjects"}
            - "skipped": 跳过的邮件数量
    """
    # 按发件人邮箱归组
    sender_groups: dict[str, dict] = {}

    for em in emails:
        sender_email = em.get("sender_email", "unknown")
        decision, reason = should_unsubscribe(em)

        if not decision:
            continue

        if sender_email not in sender_groups:
            sender_groups[sender_email] = {
                "sender_email": sender_email,
                "sender": em.get("sender", sender_email),
                "sender_domain": em.get("sender_domain", ""),
                "count": 0,
                "reasons": set(),
                "sample_subjects": [],
                "list_unsubscribe": em.get("list_unsubscribe"),
                "list_unsubscribe_post": em.get("list_unsubscribe_post"),
                "sample_html": em.get("body_html", ""),
                "sample_id": em.get("id", ""),
            }

        group = sender_groups[sender_email]
        group["count"] += 1
        group["reasons"].add(reason)

        if len(group["sample_subjects"]) < 3:
            group["sample_subjects"].append(em.get("subject", ""))

        # 优先用有 list_unsubscribe 的邮件作为样本
        if em.get("list_unsubscribe") and not group.get("list_unsubscribe"):
            group["list_unsubscribe"] = em["list_unsubscribe"]
            group["list_unsubscribe_post"] = em.get("list_unsubscribe_post")
            group["sample_html"] = em.get("body_html", "")
            group["sample_id"] = em.get("id", "")

    # 将 reasons set 转为 list，并按邮件数量排序
    result = sorted(
        [
            {**g, "reasons": list(g["reasons"])}
            for g in sender_groups.values()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    skipped = len(emails) - sum(g["count"] for g in result)

    return {
        "to_unsubscribe": result,
        "skipped": skipped,
    }
