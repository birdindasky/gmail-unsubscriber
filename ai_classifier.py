# -*- coding: utf-8 -*-
"""
AI 分类模块 - 使用 Claude AI 判断邮件是否为广告
只在关键词判断命中恰好 1 个条件时触发，处理模糊地带。
"""

import json
import logging
import os

import config

logger = logging.getLogger(__name__)


def _get_client():
    """创建 Anthropic 客户端（分离出来便于测试 mock）。"""
    import anthropic
    api_key = config.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
    return anthropic.Anthropic(api_key=api_key)


def classify_with_ai(sender: str, subject: str, snippet: str) -> tuple[bool, str]:
    """
    调用 Claude AI 判断邮件是否为商业广告/促销邮件。

    Args:
        sender:  发件人名称或邮箱
        subject: 邮件主题
        snippet: 邮件摘要（前 200 字）

    Returns:
        tuple[bool, str]: (是否为广告, 判断理由)
        出错或 AI 关闭时返回 (False, 原因说明)
    """
    if not config.USE_AI_CLASSIFIER:
        return False, "AI 分类已关闭"

    api_key = config.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning("未配置 ANTHROPIC_API_KEY，跳过 AI 分类")
        return False, "未配置 API Key，跳过 AI 分类"

    prompt = (
        "判断以下邮件是否为商业广告或促销邮件。"
        "只回答 JSON，格式：{\"is_ad\": true/false, \"reason\": \"一句话理由\"}\n\n"
        f"发件人：{sender}\n"
        f"主题：{subject}\n"
        f"摘要：{snippet[:200]}"
    )

    try:
        client = _get_client()
        message = client.messages.create(
            model=config.AI_MODEL,
            max_tokens=config.AI_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        # 去掉可能的 markdown 代码块包装
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
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
