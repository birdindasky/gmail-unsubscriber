# -*- coding: utf-8 -*-
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import classifier


def _make_email(sender_email, subject, labels=None, list_unsub=None, snippet=""):
    return {
        "id": "test-id-001",
        "sender": f"Sender <{sender_email}>",
        "sender_email": sender_email,
        "sender_domain": sender_email.split("@")[-1],
        "subject": subject,
        "snippet": snippet,
        "body_text": "",
        "body_html": "",
        "labels": labels or [],
        "list_unsubscribe": list_unsub,
        "list_unsubscribe_post": None,
        "sample_html": "",
    }


def test_whitelisted_sender_not_unsubscribed():
    em = _make_email("no-reply@google.com", "Google 通知", ["CATEGORY_PROMOTIONS"])
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is False
    assert "白名单" in reason


def test_sensitive_keyword_not_unsubscribed():
    em = _make_email("alerts@bank.unknown.com", "您的验证码是 123456")
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is False
    assert "敏感" in reason


def test_two_conditions_marked_as_ad():
    em = _make_email(
        "promo@shop.example.com",
        "限时折扣！",
        labels=["CATEGORY_PROMOTIONS"],
        list_unsub="<https://example.com/unsub>",
    )
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is True


def test_one_condition_triggers_ai_when_enabled():
    em = _make_email(
        "newsletter@example.com",
        "Weekly Update",
        list_unsub="<https://example.com/unsub>",
    )
    with patch("classifier.ai_classifier.classify_with_ai", return_value=(True, "AI判定为广告")):
        result, reason = classifier.should_unsubscribe(em, use_ai=True)
    assert result is True
    assert "AI" in reason


def test_one_condition_no_ai_not_unsubscribed():
    em = _make_email(
        "newsletter@example.com",
        "Weekly Update",
        list_unsub="<https://example.com/unsub>",
    )
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is False


def test_classify_emails_tracks_message_ids():
    emails = [
        _make_email("spam@ads.com", "大促销", ["CATEGORY_PROMOTIONS"],
                    list_unsub="<https://ads.com/unsub>"),
        _make_email("spam@ads.com", "再促销", ["CATEGORY_PROMOTIONS"],
                    list_unsub="<https://ads.com/unsub>"),
    ]
    emails[0]["id"] = "id-001"
    emails[1]["id"] = "id-002"

    result = classifier.classify_emails(emails, use_ai=False)
    groups = result["to_unsubscribe"]
    assert len(groups) == 1
    assert set(groups[0]["message_ids"]) == {"id-001", "id-002"}
