# -*- coding: utf-8 -*-
"""
AI 分类模块 - 支持 MiniMax 和 Anthropic 两种 AI 提供商
功能：
1. classify_with_ai() — 判断邮件是否为广告（关键词命中 1 条时触发）
2. categorize_with_ai() — 判断发件人所属邮件类别
"""

import json
import logging
import os

import config

logger = logging.getLogger(__name__)


def _get_anthropic_client():
    import anthropic
    api_key = config.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
    return anthropic.Anthropic(api_key=api_key)


def _get_openai_client():
    from openai import OpenAI
    api_key = config.MINIMAX_API_KEY or os.environ.get("MINIMAX_API_KEY", "")
    return OpenAI(api_key=api_key, base_url=config.MINIMAX_BASE_URL)


def _call_anthropic(prompt: str) -> str:
    client = _get_client()
    message = client.messages.create(
        model=config.AI_MODEL,
        max_tokens=config.AI_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def _call_minimax(prompt: str) -> str:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model=config.MINIMAX_MODEL,
        max_tokens=config.AI_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


def _call_ai(prompt: str) -> str:
    provider = getattr(config, "AI_PROVIDER", "anthropic")
    if provider == "minimax":
        return _call_minimax(prompt)
    else:
        return _call_anthropic(prompt)


def _parse_json_response(text: str) -> dict:
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def _check_ai_available() -> tuple[bool, str]:
    if not config.USE_AI_CLASSIFIER:
        return False, "AI 分类已关闭"
    provider = getattr(config, "AI_PROVIDER", "anthropic")
    if provider == "minimax":
        api_key = config.MINIMAX_API_KEY or os.environ.get("MINIMAX_API_KEY", "")
    else:
        api_key = config.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning(f"未配置 {provider} API Key，跳过 AI 分类")
        return False, f"未配置 API Key，跳过 AI 分类"
    return True, ""


# 保留旧函数名用于向后兼容
_get_client = _get_anthropic_client


def classify_with_ai(sender: str, subject: str, snippet: str) -> tuple[bool, str]:
    """
    调用 AI 判断邮件是否为商业广告/促销邮件。
    Returns: (是否为广告, 判断理由)
    """
    available, reason = _check_ai_available()
    if not available:
        return False, reason

    prompt = (
        "判断以下邮件是否为商业广告或促销邮件。"
        '只回答 JSON，格式：{"is_ad": true/false, "reason": "一句话理由"}\n\n'
        f"发件人：{sender}\n"
        f"主题：{subject}\n"
        f"摘要：{snippet[:200]}"
    )

    try:
        text = _call_ai(prompt)
        data = _parse_json_response(text)
        is_ad = bool(data.get("is_ad", False))
        reason = data.get("reason", "")
        logger.debug(f"AI 判定：{'广告' if is_ad else '非广告'} — {reason}")
        return is_ad, reason
    except json.JSONDecodeError as e:
        logger.warning(f"AI 返回格式解析失败：{e}")
        return False, f"AI 返回格式解析失败：{e}"
    except Exception as e:
        logger.warning(f"AI 分类调用失败：{e}")
        return False, f"AI 调用失败：{e}"


def categorize_with_ai(sender: str, subject: str) -> str:
    """
    调用 AI 判断发件人所属的邮件类别。
    Returns: 类别名（如 "电商购物"），失败时返回 "其他"
    """
    categories_str = "、".join(config.CATEGORY_NAMES)
    prompt = (
        f"根据发件人和邮件主题，判断这封邮件属于以下哪个类别：{categories_str}\n"
        '只回答 JSON，格式：{"category": "类别名"}\n\n'
        f"发件人：{sender}\n"
        f"主题：{subject}"
    )

    try:
        text = _call_ai(prompt)
        data = _parse_json_response(text)
        category = data.get("category", "其他")
        if category not in config.CATEGORY_NAMES:
            logger.debug(f"AI 返回未知类别 '{category}'，回退到'其他'")
            return "其他"
        return category
    except Exception as e:
        logger.warning(f"AI 分类调用失败：{e}")
        return "其他"
