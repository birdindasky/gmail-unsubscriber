# -*- coding: utf-8 -*-
"""
分类模块 - 判断邮件是否应该退订
采用「白名单优先 + 多条件叠加 + 可选 AI 二次确认」策略。

判断逻辑（按优先级）：
1. 白名单命中 → 绝对不退订
2. 含敏感关键词 → 绝对不退订
3. 关键词条件 2+ → 标记退订
4. 关键词条件恰好 1 → 交给 Claude AI 判断（可关闭）
5. 默认 → 不退订
"""

import logging
import re

import ai_classifier
import config

logger = logging.getLogger(__name__)

FEEDBACK_SURVEY_KEYWORDS = [
    "survey", "feedback", "questionnaire", "exit interview",
    "问卷", "调查", "反馈", "改进建议",
]

CANCELLATION_CONTEXT_KEYWORDS = [
    "unsubscribe", "unsubscribed", "cancel subscription", "cancellation",
    "取消订阅", "取消了", "离开", "为何取消",
]


# ────────────────────────────────────────────────────────────────
#  白名单检查
# ────────────────────────────────────────────────────────────────

def is_whitelisted(sender: str) -> bool:
    """检查发件人是否在白名单中（内置 + 用户自定义）。"""
    if not sender:
        return False

    domain = sender.split("@")[-1].lower().strip() if "@" in sender else sender.lower().strip()
    domain = re.sub(r"[<>\s]", "", domain)

    all_whitelist = config.get_all_whitelist_domains()

    for white_domain in all_whitelist:
        white_domain = white_domain.lower().strip()
        if not white_domain:
            continue
        if domain == white_domain or domain.endswith("." + white_domain):
            return True

    return False


# ────────────────────────────────────────────────────────────────
#  敏感内容检查
# ────────────────────────────────────────────────────────────────

def is_sensitive(email_data: dict) -> bool:
    """检查邮件是否包含敏感关键词。含敏感词则绝对不退订。"""
    check_text = " ".join([
        email_data.get("subject", ""),
        email_data.get("snippet", ""),
        email_data.get("body_text", "") or "",
    ]).lower()

    for keyword in config.SENSITIVE_KEYWORDS:
        if keyword.lower() in check_text:
            logger.debug(f"检测到敏感关键词：「{keyword}」")
            return True
    return False


def is_post_cancellation_feedback(email_data: dict) -> bool:
    """识别“取消后反馈调查”类邮件，避免误当作可退订营销邮件。"""
    if email_data.get("list_unsubscribe"):
        return False

    check_text = " ".join([
        email_data.get("subject", ""),
        email_data.get("snippet", ""),
        email_data.get("body_text", "") or "",
    ]).lower()

    has_feedback = any(keyword in check_text for keyword in FEEDBACK_SURVEY_KEYWORDS)
    has_cancellation_context = any(keyword in check_text for keyword in CANCELLATION_CONTEXT_KEYWORDS)
    return has_feedback and has_cancellation_context


# ────────────────────────────────────────────────────────────────
#  广告内容检查
# ────────────────────────────────────────────────────────────────

def is_advertisement(email_data: dict) -> tuple[bool, list[str]]:
    """
    检查邮件是否满足广告特征条件。
    返回 (是否判定为广告, 命中的条件列表)。
    需满足 2+ 条件才判定为广告。
    """
    matched_conditions = []

    subject = email_data.get("subject", "").lower()
    snippet = email_data.get("snippet", "").lower()
    body_text = (email_data.get("body_text", "") or "").lower()
    sender = email_data.get("sender", "").lower()
    sender_email = email_data.get("sender_email", "").lower()
    labels = email_data.get("labels", [])
    list_unsub = email_data.get("list_unsubscribe")

    check_text = f"{subject} {snippet} {body_text}"

    # 条件 1：含广告关键词
    matched_ad_kw = [kw for kw in config.AD_KEYWORDS if kw.lower() in check_text]
    if matched_ad_kw:
        matched_conditions.append(
            f"含广告关键词：{', '.join(matched_ad_kw[:3])}"
            + ("..." if len(matched_ad_kw) > 3 else "")
        )

    # 条件 2：发件人显示名称或域名含可疑关键词（不含 local part，避免误判）
    sender_domain = email_data.get("sender_domain", "").lower()
    sender_display = sender.split("<")[0].strip() if "<" in sender else ""
    sender_tokens = _extract_sender_tokens(sender_display, sender_domain)
    matched_sender_kw = [
        kw for kw in config.SUSPICIOUS_SENDER_KEYWORDS
        if kw.lower() in sender_tokens
    ]
    if matched_sender_kw:
        matched_conditions.append(f"发件人含可疑关键词：{', '.join(matched_sender_kw[:2])}")

    # 条件 3：含 List-Unsubscribe 头部
    if list_unsub:
        matched_conditions.append("含 List-Unsubscribe 头部")

    # 条件 4：Gmail 自动归类为促销
    if "CATEGORY_PROMOTIONS" in labels:
        matched_conditions.append("Gmail 自动归类为促销邮件")

    # 条件 5：noreply 地址
    local_part = sender_email.split("@")[0] if "@" in sender_email else sender_email
    if re.match(r"^(noreply|no.reply|donotreply|do.not.reply)$", local_part, re.I):
        matched_conditions.append("发件人为 noreply 地址")

    is_ad = len(matched_conditions) >= 2
    return is_ad, matched_conditions


def _extract_sender_tokens(sender_display: str, sender_domain: str) -> set[str]:
    """将发件人名称和域名切成词元，避免 brand 名称里的子串误判。"""
    raw = f"{sender_display} {sender_domain}".lower()
    parts = re.findall(r"[\w\u4e00-\u9fff]+", raw)
    expanded = set(parts)
    for part in parts:
        expanded.update(p for p in re.split(r"[_\-.]+", part) if p)
    return expanded


# ────────────────────────────────────────────────────────────────
#  最终决策
# ────────────────────────────────────────────────────────────────

_ai_cache: dict[str, tuple[bool, str]] = {}


def should_unsubscribe(email_data: dict, use_ai: bool = True) -> tuple[bool, str]:
    """
    综合所有规则，给出是否应该退订的最终判断。

    Args:
        email_data: 邮件详情字典
        use_ai:     是否允许调用 Claude AI（False 时跳过 AI 判断）

    Returns:
        tuple[bool, str]: (是否建议退订, 判断理由)
    """
    sender_email = email_data.get("sender_email", "")

    # 第一道防线：白名单
    if is_whitelisted(sender_email):
        return False, f"发件人域名在白名单中（{email_data.get('sender_domain', '')}）"

    # 第二道防线：敏感内容
    if is_sensitive(email_data):
        return False, "邮件含敏感关键词（验证码/订单/账单等），已跳过"

    # 第三道防线：取消后反馈调查，不属于邮件列表退订目标
    if is_post_cancellation_feedback(email_data):
        return False, "邮件属于取消后的反馈调查，不是可执行退订的订阅邮件"

    # 广告特征判断
    is_ad, conditions = is_advertisement(email_data)

    if is_ad:
        return True, "命中广告特征：" + "；".join(conditions)

    # 恰好命中 1 个条件 → 交给 AI 判断（同一发件人只调一次）
    if len(conditions) == 1 and use_ai:
        if sender_email in _ai_cache:
            ai_result, ai_reason = _ai_cache[sender_email]
        else:
            ai_result, ai_reason = ai_classifier.classify_with_ai(
                sender=email_data.get("sender", ""),
                subject=email_data.get("subject", ""),
                snippet=email_data.get("snippet", ""),
            )
            _ai_cache[sender_email] = (ai_result, ai_reason)
        if ai_result:
            return True, f"AI 判定为广告：{ai_reason}（辅助条件：{conditions[0]}）"

    return False, "未达到广告判定标准，跳过"


# ────────────────────────────────────────────────────────────────
#  批量分类
# ────────────────────────────────────────────────────────────────

def classify_emails(emails: list[dict], use_ai: bool = True) -> dict:
    """
    对邮件列表进行批量分类，按发件人归组。

    Args:
        emails:  邮件详情列表
        use_ai:  是否允许 AI 辅助判断

    Returns:
        dict: {"to_unsubscribe": [...], "skipped": int}
    """
    sender_groups: dict[str, dict] = {}
    total = len(emails)
    print(f"\n🔍 正在分类 {total} 封邮件...")

    for idx, em in enumerate(emails, 1):
        if idx % 50 == 0 or idx == total:
            print(f"   分类进度：{idx}/{total} 封...")
        sender_email = em.get("sender_email", "unknown")
        decision, reason = should_unsubscribe(em, use_ai=use_ai)

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
                "message_ids": [],
                "list_unsubscribe": em.get("list_unsubscribe"),
                "list_unsubscribe_post": em.get("list_unsubscribe_post"),
                "sample_html": em.get("body_html", ""),
                "sample_id": em.get("id", ""),
            }

        group = sender_groups[sender_email]
        group["count"] += 1
        group["reasons"].add(reason)
        group["message_ids"].append(em.get("id", ""))

        if len(group["sample_subjects"]) < 3:
            group["sample_subjects"].append(em.get("subject", ""))

        if em.get("list_unsubscribe") and not group.get("list_unsubscribe"):
            group["list_unsubscribe"] = em["list_unsubscribe"]
            group["list_unsubscribe_post"] = em.get("list_unsubscribe_post")
            group["sample_html"] = em.get("body_html", "")
            group["sample_id"] = em.get("id", "")

    result = sorted(
        [{**g, "reasons": list(g["reasons"])} for g in sender_groups.values()],
        key=lambda x: x["count"],
        reverse=True,
    )

    skipped = len(emails) - sum(g["count"] for g in result)
    return {"to_unsubscribe": result, "skipped": skipped}


# ────────────────────────────────────────────────────────────────
#  按类别归组
# ────────────────────────────────────────────────────────────────

def categorize_groups(groups: list[dict], use_ai: bool = True) -> dict[str, list[dict]]:
    """
    将发件人分组按邮件类别归组。

    Args:
        groups:  classify_emails() 返回的 to_unsubscribe 列表
        use_ai:  是否使用 AI 判断未知域名的类别

    Returns:
        dict: {类别名: [发件人分组列表]}，只包含非空类别
    """
    categorized: dict[str, list[dict]] = {}
    total = len(groups)
    ai_count = 0
    domain_cat_cache: dict[str, str] = {}

    for i, group in enumerate(groups, 1):
        domain = group.get("sender_domain", "")
        category = config.DOMAIN_TO_CATEGORY.get(domain)

        if not category:
            for mapped_domain, mapped_cat in config.DOMAIN_TO_CATEGORY.items():
                if domain.endswith("." + mapped_domain):
                    category = mapped_cat
                    break

        if not category and use_ai:
            if domain in domain_cat_cache:
                category = domain_cat_cache[domain]
            else:
                ai_count += 1
                print(f"   🤖 AI 分类中 ({ai_count})：{domain}...")
                sender = group.get("sender", "")
                subject = group["sample_subjects"][0] if group.get("sample_subjects") else ""
                category = ai_classifier.categorize_with_ai(sender, subject)
                domain_cat_cache[domain] = category

        if not category:
            category = "其他"

        if category not in categorized:
            categorized[category] = []
        categorized[category].append(group)

    return categorized
