# -*- coding: utf-8 -*-
"""
Classification module - decides whether an email should be unsubscribed.
Uses a "whitelist first + stacked signals + optional AI double-check" strategy.

Decision flow, in priority order:
1. Whitelist hit -> never unsubscribe
2. Sensitive keyword hit -> never unsubscribe
3. 2+ keyword conditions -> mark for unsubscribe
4. Exactly 1 keyword condition -> let AI decide (optional)
5. Default -> do not unsubscribe
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
#  Whitelist check
# ────────────────────────────────────────────────────────────────

def is_whitelisted(sender: str) -> bool:
    """Check whether the sender is whitelisted (built-in + user-defined)."""
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
#  Sensitive content check
# ────────────────────────────────────────────────────────────────

def is_sensitive(email_data: dict) -> bool:
    """Check whether the email contains sensitive keywords. If so, never unsubscribe."""
    check_text = " ".join([
        email_data.get("subject", ""),
        email_data.get("snippet", ""),
        email_data.get("body_text", "") or "",
    ]).lower()

    for keyword in config.SENSITIVE_KEYWORDS:
        if keyword.lower() in check_text:
            logger.debug(f"Detected sensitive keyword: {keyword}")
            return True
    return False


def is_post_cancellation_feedback(email_data: dict) -> bool:
    """Detect post-cancellation feedback surveys so they are not treated as marketing mail."""
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
#  Ad signal check
# ────────────────────────────────────────────────────────────────

def is_advertisement(email_data: dict) -> tuple[bool, list[str]]:
    """
    Check whether the email matches ad signal conditions.
    Returns (is_ad, matched_conditions).
    At least 2 conditions must match to classify it as an ad.
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

    # Condition 1: contains ad keywords
    matched_ad_kw = [kw for kw in config.AD_KEYWORDS if kw.lower() in check_text]
    if matched_ad_kw:
        matched_conditions.append(
            f"Contains ad keywords: {', '.join(matched_ad_kw[:3])}"
            + ("..." if len(matched_ad_kw) > 3 else "")
        )

    # Condition 2: sender display name or domain contains suspicious keywords
    sender_domain = email_data.get("sender_domain", "").lower()
    sender_display = sender.split("<")[0].strip() if "<" in sender else ""
    sender_tokens = _extract_sender_tokens(sender_display, sender_domain)
    matched_sender_kw = [
        kw for kw in config.SUSPICIOUS_SENDER_KEYWORDS
        if kw.lower() in sender_tokens
    ]
    if matched_sender_kw:
        matched_conditions.append(f"Sender contains suspicious keywords: {', '.join(matched_sender_kw[:2])}")

    # Condition 3: has a List-Unsubscribe header
    if list_unsub:
        matched_conditions.append("Has List-Unsubscribe header")

    # Condition 4: Gmail automatically categorized it as promotional
    if "CATEGORY_PROMOTIONS" in labels:
        matched_conditions.append("Gmail auto-categorized it as promotional")

    # Condition 5: noreply address
    local_part = sender_email.split("@")[0] if "@" in sender_email else sender_email
    if re.match(r"^(noreply|no.reply|donotreply|do.not.reply)$", local_part, re.I):
        matched_conditions.append("Sender is a noreply address")

    is_ad = len(matched_conditions) >= 2
    return is_ad, matched_conditions


def _extract_sender_tokens(sender_display: str, sender_domain: str) -> set[str]:
    """Tokenize sender name and domain to avoid false matches on brand substrings."""
    raw = f"{sender_display} {sender_domain}".lower()
    parts = re.findall(r"[\w\u4e00-\u9fff]+", raw)
    expanded = set(parts)
    for part in parts:
        expanded.update(p for p in re.split(r"[_\-.]+", part) if p)
    return expanded


# ────────────────────────────────────────────────────────────────
#  Final decision
# ────────────────────────────────────────────────────────────────

_ai_cache: dict[str, tuple[bool, str]] = {}


def should_unsubscribe(email_data: dict, use_ai: bool = True) -> tuple[bool, str]:
    """
    Apply all rules and return the final unsubscribe decision.

    Args:
        email_data: Email details dictionary
        use_ai: Whether AI is allowed as a secondary check

    Returns:
        tuple[bool, str]: (should_unsubscribe, reason)
    """
    sender_email = email_data.get("sender_email", "")

    # First line of defense: whitelist
    if is_whitelisted(sender_email):
        return False, f"Sender domain is whitelisted ({email_data.get('sender_domain', '')})"

    # Second line of defense: sensitive content
    if is_sensitive(email_data):
        return False, "Email contains sensitive keywords (verification code/order/bill/etc.); skipped"

    # Third line of defense: post-cancellation feedback surveys
    if is_post_cancellation_feedback(email_data):
        return False, "Email is a post-cancellation feedback survey, not an actionable subscription email"

    # Ad signal evaluation
    is_ad, conditions = is_advertisement(email_data)

    if is_ad:
        return True, "Matched ad signals: " + "; ".join(conditions)

    # Exactly 1 matched condition -> let AI decide, once per sender
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
            return True, f"AI classified as ad: {ai_reason} (supporting signal: {conditions[0]})"

    return False, "Did not meet the ad threshold; skipped"


# ────────────────────────────────────────────────────────────────
#  Batch classification
# ────────────────────────────────────────────────────────────────

def classify_emails(emails: list[dict], use_ai: bool = True) -> dict:
    """
    Classify a list of emails and group them by sender.

    Args:
        emails: List of email detail dictionaries
        use_ai: Whether AI-assisted decisions are allowed

    Returns:
        dict: {"to_unsubscribe": [...], "skipped": int}
    """
    sender_groups: dict[str, dict] = {}
    total = len(emails)
    print(f"\n🔍 Classifying {total} emails...")

    for idx, em in enumerate(emails, 1):
        if idx % 50 == 0 or idx == total:
            print(f"   Classification progress: {idx}/{total} emails...")
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
#  Group by category
# ────────────────────────────────────────────────────────────────

def categorize_groups(groups: list[dict], use_ai: bool = True) -> dict[str, list[dict]]:
    """
    Group sender groups by email category.

    Args:
        groups: The to_unsubscribe list returned by classify_emails()
        use_ai: Whether AI is allowed to classify unknown domains

    Returns:
        dict: {category_name: [sender_group_list]}, excluding empty categories
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
                print(f"   🤖 AI categorizing ({ai_count}): {domain}...")
                sender = group.get("sender", "")
                subject = group["sample_subjects"][0] if group.get("sample_subjects") else ""
                category = ai_classifier.categorize_with_ai(sender, subject)
                domain_cat_cache[domain] = category

        if not category:
            category = "Other"

        if category not in categorized:
            categorized[category] = []
        categorized[category].append(group)

    return categorized
