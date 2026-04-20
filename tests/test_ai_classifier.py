# -*- coding: utf-8 -*-
import os
import sys
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))



def test_classify_ad_email():
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", return_value=json.dumps({"is_ad": True, "reason": "促销邮件，含折扣信息"})), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MAX_TOKENS = 1024
        mock_uc.get_active_provider.return_value = {
            "id": "anthropic", "api_key": "sk-ant-test", "model": "claude-haiku-4-5", "base_url": None,
        }

        is_ad, reason = ai_classifier.classify_with_ai(
            sender="promo@shop.example.com",
            subject="限时 5 折优惠！",
            snippet="亲爱的会员，本周末特别促销……"
        )

    assert is_ad is True
    assert "折扣" in reason


def test_classify_non_ad_email():
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", return_value=json.dumps({"is_ad": False, "reason": "这是系统通知邮件"})), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MAX_TOKENS = 1024
        mock_uc.get_active_provider.return_value = {
            "id": "anthropic", "api_key": "sk-ant-test", "model": "claude-haiku-4-5", "base_url": None,
        }

        is_ad, reason = ai_classifier.classify_with_ai(
            sender="noreply@github.com",
            subject="Your pull request was merged",
            snippet="Your PR #123 has been merged into main"
        )

    assert is_ad is False


def test_ai_disabled_returns_false():
    import ai_classifier
    with patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = False

        is_ad, reason = ai_classifier.classify_with_ai(
            sender="promo@shop.com",
            subject="大促销",
            snippet="买一送一"
        )

    assert is_ad is False
    assert "关闭" in reason


def test_missing_api_key_returns_false():
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_uc.get_active_provider.return_value = None

        is_ad, reason = ai_classifier.classify_with_ai(
            sender="promo@shop.com",
            subject="大促销",
            snippet="买一送一"
        )

    assert is_ad is False
    assert "未配置" in reason or "跳过" in reason


def test_api_error_returns_false():
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", side_effect=Exception("Connection timeout")), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MAX_TOKENS = 1024
        mock_uc.get_active_provider.return_value = {
            "id": "anthropic", "api_key": "sk-ant-test", "model": "claude-haiku-4-5", "base_url": None,
        }

        is_ad, reason = ai_classifier.classify_with_ai("x@y.com", "test", "test")

    assert is_ad is False
    assert "失败" in reason



def test_minimax_classify_ad_email():
    """MiniMax 提供商应能正确判断广告邮件。"""
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", return_value=json.dumps({"is_ad": True, "reason": "促销邮件"})), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MAX_TOKENS = 1024
        mock_uc.get_active_provider.return_value = {
            "id": "minimax", "api_key": "sk-cp-test", "model": "MiniMax-M2", "base_url": None,
        }

        is_ad, reason = ai_classifier.classify_with_ai(
            sender="promo@shop.example.com",
            subject="限时折扣！",
            snippet="今天打五折"
        )

    assert is_ad is True
    assert "促销" in reason


def test_minimax_classify_non_ad():
    """MiniMax 应能识别非广告邮件。"""
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", return_value=json.dumps({"is_ad": False, "reason": "系统通知"})), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MAX_TOKENS = 1024
        mock_uc.get_active_provider.return_value = {
            "id": "minimax", "api_key": "sk-cp-test", "model": "MiniMax-M2", "base_url": None,
        }

        is_ad, reason = ai_classifier.classify_with_ai(
            sender="noreply@github.com",
            subject="PR merged",
            snippet="Your PR was merged"
        )

    assert is_ad is False


def test_categorize_with_ai_returns_category():
    """categorize_with_ai 应返回有效类别名。"""
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", return_value=json.dumps({"category": "电商购物"})), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MAX_TOKENS = 1024
        mock_config.CATEGORY_NAMES = ["电商购物", "社交媒体", "其他"]
        mock_uc.get_active_provider.return_value = {
            "id": "minimax", "api_key": "sk-cp-test", "model": "MiniMax-M2", "base_url": None,
        }

        category = ai_classifier.categorize_with_ai("淘宝", "限时折扣")

    assert category == "电商购物"


def test_categorize_with_ai_invalid_returns_other():
    """AI 返回无效类别时应回退到'其他'。"""
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", return_value=json.dumps({"category": "不存在的类别"})), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MAX_TOKENS = 1024
        mock_config.CATEGORY_NAMES = ["电商购物", "社交媒体", "其他"]
        mock_uc.get_active_provider.return_value = {
            "id": "minimax", "api_key": "sk-cp-test", "model": "MiniMax-M2", "base_url": None,
        }

        category = ai_classifier.categorize_with_ai("unknown@xyz.com", "Hello")

    assert category == "其他"


def test_categorize_with_ai_error_returns_other():
    """AI 调用失败时应回退到'其他'。"""
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", side_effect=Exception("timeout")), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MAX_TOKENS = 1024
        mock_config.CATEGORY_NAMES = ["电商购物", "其他"]
        mock_uc.get_active_provider.return_value = {
            "id": "minimax", "api_key": "sk-cp-test", "model": "MiniMax-M2", "base_url": None,
        }

        category = ai_classifier.categorize_with_ai("x@y.com", "test")

    assert category == "其他"


def test_call_ai_routes_openai_protocol():
    """选 DeepSeek（openai 协议）时应调用 _call_openai。"""
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_openai", return_value='{"is_ad": true, "reason": "t"}') as mock_oai, \
         patch("ai_classifier._call_anthropic") as mock_anthropic, \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_uc.get_active_provider.return_value = {
            "id": "deepseek", "api_key": "sk-x", "model": "deepseek-chat", "base_url": None,
        }
        is_ad, _ = ai_classifier.classify_with_ai("s", "subj", "snip")
    assert is_ad is True
    assert mock_oai.called
    assert not mock_anthropic.called


def test_call_ai_routes_anthropic_protocol():
    """选 MiniMax（anthropic 协议）时应调用 _call_anthropic。"""
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", return_value='{"is_ad": false, "reason": "t"}') as mock_anthropic, \
         patch("ai_classifier._call_openai") as mock_oai, \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_uc.get_active_provider.return_value = {
            "id": "minimax", "api_key": "sk-cp-x", "model": "MiniMax-M2", "base_url": None,
        }
        is_ad, _ = ai_classifier.classify_with_ai("s", "subj", "snip")
    assert is_ad is False
    assert mock_anthropic.called
    assert not mock_oai.called


def test_no_provider_skips_ai():
    """未配置提供商时直接返回 False，不调 AI。"""
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_uc.get_active_provider.return_value = None
        is_ad, reason = ai_classifier.classify_with_ai("s", "subj", "snip")
    assert is_ad is False
    assert "未配置" in reason or "跳过" in reason


def test_test_connection_success():
    import ai_classifier
    with patch("ai_classifier._call_openai", return_value="hi"):
        ok, msg = ai_classifier.test_connection(
            "deepseek", "sk-abc", "deepseek-chat", None
        )
    assert ok is True
    assert "成功" in msg


def test_test_connection_auth_fail():
    import ai_classifier

    def _raise(*a, **kw):
        raise Exception("401 Unauthorized: invalid api key")

    with patch("ai_classifier._call_openai", side_effect=_raise):
        ok, msg = ai_classifier.test_connection(
            "deepseek", "sk-bad", "deepseek-chat", None
        )
    assert ok is False
    assert "401" in msg or "无效" in msg or "Unauthorized" in msg


def test_test_connection_unknown_provider():
    import ai_classifier
    ok, msg = ai_classifier.test_connection("not-a-provider", "x", "x", None)
    assert ok is False
    assert "未知" in msg


def test_mask_secrets_hides_api_key():
    import ai_classifier
    text = "Unauthorized: key=sk-ant-abc1234567890xyz invalid"
    out = ai_classifier._mask_secrets(text)
    assert "sk-ant-abc1234567890xyz" not in out
    assert "[REDACTED]" in out


def test_mask_secrets_leaves_normal_text():
    import ai_classifier
    assert ai_classifier._mask_secrets("simple error msg") == "simple error msg"
