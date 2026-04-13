# -*- coding: utf-8 -*-
import os
import sys
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_ai_response(is_ad: bool, reason: str) -> MagicMock:
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = json.dumps({"is_ad": is_ad, "reason": reason})
    return mock_response


def test_classify_ad_email():
    import ai_classifier
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_ai_response(True, "促销邮件，含折扣信息")

    with patch("ai_classifier._get_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MODEL = "claude-haiku-4-5-20251001"
        mock_config.AI_MAX_TOKENS = 150
        mock_config.ANTHROPIC_API_KEY = "test-key"

        is_ad, reason = ai_classifier.classify_with_ai(
            sender="promo@shop.example.com",
            subject="限时 5 折优惠！",
            snippet="亲爱的会员，本周末特别促销……"
        )

    assert is_ad is True
    assert "折扣" in reason


def test_classify_non_ad_email():
    import ai_classifier
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_ai_response(False, "这是系统通知邮件")

    with patch("ai_classifier._get_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MODEL = "claude-haiku-4-5-20251001"
        mock_config.AI_MAX_TOKENS = 150
        mock_config.ANTHROPIC_API_KEY = "test-key"

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
    with patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.ANTHROPIC_API_KEY = ""

        with patch.dict(os.environ, {}, clear=True):
            is_ad, reason = ai_classifier.classify_with_ai(
                sender="promo@shop.com",
                subject="大促销",
                snippet="买一送一"
            )

    assert is_ad is False
    assert "API Key" in reason


def test_api_error_returns_false():
    import ai_classifier
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("Connection timeout")

    with patch("ai_classifier._get_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_MODEL = "claude-haiku-4-5-20251001"
        mock_config.AI_MAX_TOKENS = 150
        mock_config.ANTHROPIC_API_KEY = "test-key"

        is_ad, reason = ai_classifier.classify_with_ai("x@y.com", "test", "test")

    assert is_ad is False
    assert "失败" in reason
