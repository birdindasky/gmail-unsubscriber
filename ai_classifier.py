# -*- coding: utf-8 -*-
"""
AI 分类模块 - 支持 9 种 AI 提供商（含自定义 OpenAI 兼容入口）
功能：
1. classify_with_ai() — 判断邮件是否为广告（关键词命中 1 条时触发）
2. categorize_with_ai() — 判断发件人所属邮件类别
"""

import json
import logging
import re
from typing import Optional

import config
import user_config

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
#  提供商注册表
# ────────────────────────────────────────────────────────────────

PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "key_hint": "sk-...",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "protocol": "anthropic",
        "base_url": None,
        "default_model": "claude-haiku-4-5",
        "key_hint": "sk-ant-...",
    },
    "minimax": {
        "name": "MiniMax",
        "protocol": "anthropic",
        "base_url": "https://api.minimaxi.com/anthropic",
        "default_model": "MiniMax-M2",
        "key_hint": "sk-cp-...",
    },
    "deepseek": {
        "name": "DeepSeek",
        "protocol": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "key_hint": "sk-...",
    },
    "moonshot": {
        "name": "Moonshot (Kimi)",
        "protocol": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "key_hint": "sk-...",
    },
    "qwen": {
        "name": "通义千问",
        "protocol": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-turbo",
        "key_hint": "sk-...",
    },
    "zhipu": {
        "name": "智谱 GLM",
        "protocol": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "key_hint": "...",
    },
    "ollama": {
        "name": "Ollama (本地)",
        "protocol": "openai",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3",
        "key_hint": "随便填",
    },
    "custom": {
        "name": "自定义 OpenAI 兼容",
        "protocol": "openai",
        "base_url": None,
        "default_model": None,
        "key_hint": "...",
    },
}


def _extract_text_from_response(message) -> str:
    """从 Anthropic SDK 响应中提取文本，兼容推理模型只返回 ThinkingBlock 的情况。"""
    for block in message.content:
        if getattr(block, "type", "") == "text" and hasattr(block, "text"):
            return block.text.strip()
    for block in message.content:
        if getattr(block, "type", "") == "thinking" and hasattr(block, "thinking"):
            return block.thinking.strip()
    return ""


def _call_anthropic(prompt: str, provider: dict) -> str:
    import anthropic
    kwargs = {"api_key": provider["api_key"]}
    if provider.get("base_url"):
        kwargs["base_url"] = provider["base_url"]
    client = anthropic.Anthropic(**kwargs)
    message = client.messages.create(
        model=provider["model"],
        max_tokens=getattr(config, "AI_MAX_TOKENS", 1024),
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_text_from_response(message)


def _call_openai(prompt: str, provider: dict) -> str:
    import openai
    kwargs = {"api_key": provider["api_key"]}
    if provider.get("base_url"):
        kwargs["base_url"] = provider["base_url"]
    client = openai.OpenAI(**kwargs)
    resp = client.chat.completions.create(
        model=provider["model"],
        max_tokens=getattr(config, "AI_MAX_TOKENS", 1024),
        messages=[{"role": "user", "content": prompt}],
    )
    content = resp.choices[0].message.content if resp.choices else ""
    return (content or "").strip()


_cached_provider: Optional[dict] = None


def _get_provider() -> dict:
    """获取活跃提供商配置（进程内缓存，避免每次 AI 调用都读磁盘）。"""
    global _cached_provider
    if _cached_provider is not None:
        return _cached_provider
    provider = user_config.get_active_provider()
    if not provider:
        raise RuntimeError("未配置 AI 提供商")
    meta = PROVIDERS.get(provider["id"])
    if meta and not provider.get("base_url") and meta.get("base_url"):
        provider["base_url"] = meta["base_url"]
    _cached_provider = provider
    return provider


def invalidate_provider_cache() -> None:
    """清除提供商缓存（配置变更后调用）。"""
    global _cached_provider
    _cached_provider = None


def _call_ai(prompt: str) -> str:
    """按活跃提供商的 protocol 分发调用。"""
    provider = _get_provider()
    meta = PROVIDERS.get(provider["id"])
    if not meta:
        raise ValueError(f"未知提供商：{provider['id']}")
    if meta["protocol"] == "openai":
        return _call_openai(prompt, provider)
    elif meta["protocol"] == "anthropic":
        return _call_anthropic(prompt, provider)
    else:
        raise ValueError(f"未知协议：{meta['protocol']}")


def _parse_json_response(text: str) -> dict:
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    for match in re.finditer(r'\{[^{}]+\}', text):
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            continue
    raise json.JSONDecodeError("No JSON found", text, 0)


def _check_ai_available() -> tuple[bool, str]:
    if not config.USE_AI_CLASSIFIER:
        return False, "AI 分类已关闭"
    try:
        _get_provider()
    except RuntimeError:
        return False, "未配置 AI 提供商，跳过 AI 分类"
    return True, ""


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
    available, _ = _check_ai_available()
    if not available:
        return "其他"

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


def test_connection(provider_id: str, api_key: str, model: str, base_url: Optional[str] = None) -> tuple[bool, str]:
    """测试给定凭证能否成功调用 AI。返回 (是否成功, 消息)。"""
    meta = PROVIDERS.get(provider_id)
    if not meta:
        return False, f"未知提供商：{provider_id}"

    probe_provider = {
        "id": provider_id,
        "api_key": api_key,
        "model": model,
        "base_url": base_url or meta.get("base_url"),
    }
    try:
        if meta["protocol"] == "openai":
            _call_openai("Say hi in one word.", probe_provider)
        else:
            _call_anthropic("Say hi in one word.", probe_provider)
        return True, "连接成功"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
