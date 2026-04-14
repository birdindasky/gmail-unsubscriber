# -*- coding: utf-8 -*-
import os
import sys
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_ai_response(is_ad: bool, reason: str) -> MagicMock:
    mock_response = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = json.dumps({"is_ad": is_ad, "reason": reason})
    mock_response.content = [text_block]
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


def _make_minimax_response(text_content):
    """构造 MiniMax (Anthropic 格式) 的 mock 响应，模拟推理模型返回。"""
    thinking_block = MagicMock()
    thinking_block.type = "thinking"
    thinking_block.thinking = "让我想想..."
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text_content
    mock_response = MagicMock()
    mock_response.content = [thinking_block, text_block]
    return mock_response


def test_minimax_classify_ad_email():
    """MiniMax 提供商应能正确判断广告邮件。"""
    import ai_classifier
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_minimax_response(
        json.dumps({"is_ad": True, "reason": "促销邮件"})
    )

    with patch("ai_classifier._get_minimax_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-M2.7"
        mock_config.MINIMAX_BASE_URL = "https://api.minimaxi.com/anthropic"
        mock_config.AI_MAX_TOKENS = 150

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
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_minimax_response(
        json.dumps({"is_ad": False, "reason": "系统通知"})
    )

    with patch("ai_classifier._get_minimax_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-M2.7"
        mock_config.MINIMAX_BASE_URL = "https://api.minimaxi.com/anthropic"
        mock_config.AI_MAX_TOKENS = 150

        is_ad, reason = ai_classifier.classify_with_ai(
            sender="noreply@github.com",
            subject="PR merged",
            snippet="Your PR was merged"
        )

    assert is_ad is False


def test_categorize_with_ai_returns_category():
    """categorize_with_ai 应返回有效类别名。"""
    import ai_classifier
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_minimax_response(
        json.dumps({"category": "电商购物"})
    )

    with patch("ai_classifier._get_minimax_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-M2.7"
        mock_config.MINIMAX_BASE_URL = "https://api.minimaxi.com/anthropic"
        mock_config.AI_MAX_TOKENS = 150
        mock_config.CATEGORY_NAMES = ["电商购物", "社交媒体", "其他"]

        category = ai_classifier.categorize_with_ai("淘宝", "限时折扣")

    assert category == "电商购物"


def test_categorize_with_ai_invalid_returns_other():
    """AI 返回无效类别时应回退到'其他'。"""
    import ai_classifier
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_minimax_response(
        json.dumps({"category": "不存在的类别"})
    )

    with patch("ai_classifier._get_minimax_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-M2.7"
        mock_config.MINIMAX_BASE_URL = "https://api.minimaxi.com/anthropic"
        mock_config.AI_MAX_TOKENS = 150
        mock_config.CATEGORY_NAMES = ["电商购物", "社交媒体", "其他"]

        category = ai_classifier.categorize_with_ai("unknown@xyz.com", "Hello")

    assert category == "其他"


def test_categorize_with_ai_error_returns_other():
    """AI 调用失败时应回退到'其他'。"""
    import ai_classifier
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("timeout")

    with patch("ai_classifier._get_minimax_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-M2.7"
        mock_config.MINIMAX_BASE_URL = "https://api.minimaxi.com/anthropic"
        mock_config.AI_MAX_TOKENS = 150
        mock_config.CATEGORY_NAMES = ["电商购物", "其他"]

        category = ai_classifier.categorize_with_ai("x@y.com", "test")

    assert category == "其他"
