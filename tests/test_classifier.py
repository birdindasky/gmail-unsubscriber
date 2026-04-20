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


def test_post_cancellation_feedback_not_unsubscribed():
    em = _make_email(
        "noreply@tm.openai.com",
        "我们希望了解你为何取消 ChatGPT Plus 订阅",
        labels=["CATEGORY_PROMOTIONS"],
        snippet="看到你要离开，我们深表遗憾。你是否愿意花几分钟时间分享取消订阅的原因并提供改进建议？本调查仅需几分钟。",
    )
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is False
    assert "反馈调查" in reason


def test_salesforce_brand_not_matched_by_sales_keyword():
    em = _make_email(
        "support@salesforce.com",
        "我们已接收到要求更改您的 Salesforce 客户电子邮件地址的请求。",
        labels=["CATEGORY_UPDATES"],
        snippet="我们最近收到请求，以更改用户名的 Salesforce 账户的电子邮件地址。",
    )
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is False
    assert "未达到广告判定标准" in reason


def test_sales_subdomain_still_matches_suspicious_sender_keyword():
    em = _make_email(
        "offers@sales.example.com",
        "新品推荐",
        labels=["CATEGORY_UPDATES"],
        snippet="本周活动",
    )
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is True
    assert "可疑关键词" in reason


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


def test_categorize_groups_by_domain():
    """categorize_groups 应根据域名分配类别。"""
    groups = [
        {"sender_email": "promo@taobao.com", "sender": "淘宝", "sender_domain": "taobao.com",
         "count": 10, "reasons": ["广告"], "sample_subjects": ["打折"], "message_ids": ["id1"],
         "list_unsubscribe": None, "list_unsubscribe_post": None, "sample_html": "", "sample_id": "id1"},
        {"sender_email": "news@36kr.com", "sender": "36氪", "sender_domain": "36kr.com",
         "count": 5, "reasons": ["广告"], "sample_subjects": ["日报"], "message_ids": ["id2"],
         "list_unsubscribe": None, "list_unsubscribe_post": None, "sample_html": "", "sample_id": "id2"},
        {"sender_email": "spam@unknown.xyz", "sender": "Unknown", "sender_domain": "unknown.xyz",
         "count": 3, "reasons": ["广告"], "sample_subjects": ["Hi"], "message_ids": ["id3"],
         "list_unsubscribe": None, "list_unsubscribe_post": None, "sample_html": "", "sample_id": "id3"},
    ]
    with patch("classifier.ai_classifier.categorize_with_ai", return_value="其他"):
        result = classifier.categorize_groups(groups, use_ai=False)

    assert "电商购物" in result
    assert "新闻资讯" in result
    assert "其他" in result
    assert len(result["电商购物"]) == 1
    assert result["电商购物"][0]["sender_email"] == "promo@taobao.com"


def test_categorize_groups_with_ai():
    """当域名未命中且 AI 开启时，应调用 AI 分类。"""
    groups = [
        {"sender_email": "spam@mystery.xyz", "sender": "Mystery Shop", "sender_domain": "mystery.xyz",
         "count": 3, "reasons": ["广告"], "sample_subjects": ["Buy now"], "message_ids": ["id1"],
         "list_unsubscribe": None, "list_unsubscribe_post": None, "sample_html": "", "sample_id": "id1"},
    ]
    with patch("classifier.ai_classifier.categorize_with_ai", return_value="电商购物") as mock_ai:
        result = classifier.categorize_groups(groups, use_ai=True)

    mock_ai.assert_called_once_with("Mystery Shop", "Buy now")
    assert "电商购物" in result
    assert len(result["电商购物"]) == 1
