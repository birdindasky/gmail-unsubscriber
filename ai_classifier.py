# -*- coding: utf-8 -*-
"""
AI classification module - supports 9 AI providers, including custom
OpenAI-compatible endpoints.
Functions:
1. classify_with_ai() - decides whether an email is an ad
   (triggered when exactly 1 keyword condition matches)
2. categorize_with_ai() - decides which email category a sender belongs to
"""

import json
import logging
import re
from typing import Optional

import config
import user_config

logger = logging.getLogger(__name__)

_SECRET_RE = re.compile(r"(?i)\b(sk|pk|api[_-]?key)[\w\-]{8,}")


def _mask_secrets(text: str) -> str:
    """Redact anything that looks like an API key / long secret in log strings."""
    return _SECRET_RE.sub("[REDACTED]", text)


# ────────────────────────────────────────────────────────────────
#  Provider registry
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
        "name": "Qwen",
        "protocol": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-turbo",
        "key_hint": "sk-...",
    },
    "zhipu": {
        "name": "Zhipu GLM",
        "protocol": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "key_hint": "...",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "protocol": "openai",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3",
        "key_hint": "Any value",
    },
    "custom": {
        "name": "Custom OpenAI-Compatible",
        "protocol": "openai",
        "base_url": None,
        "default_model": None,
        "key_hint": "...",
    },
}


def _extract_text_from_response(message) -> str:
    """Extract text from an Anthropic SDK response, including ThinkingBlock-only replies."""
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
    """Get the active provider config, cached in-process to avoid repeated disk reads."""
    global _cached_provider
    if _cached_provider is not None:
        return _cached_provider
    provider = user_config.get_active_provider()
    if not provider:
        raise RuntimeError("No AI provider configured")
    meta = PROVIDERS.get(provider["id"])
    if meta and not provider.get("base_url") and meta.get("base_url"):
        provider["base_url"] = meta["base_url"]
    _cached_provider = provider
    return provider


def invalidate_provider_cache() -> None:
    """Clear the provider cache after configuration changes."""
    global _cached_provider
    _cached_provider = None


def _call_ai(prompt: str) -> str:
    """Dispatch the AI call based on the active provider protocol."""
    provider = _get_provider()
    meta = PROVIDERS.get(provider["id"])
    if not meta:
        raise ValueError(f"Unknown provider: {provider['id']}")
    if meta["protocol"] == "openai":
        return _call_openai(prompt, provider)
    elif meta["protocol"] == "anthropic":
        return _call_anthropic(prompt, provider)
    else:
        raise ValueError(f"Unknown protocol: {meta['protocol']}")


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
        return False, "AI classification is disabled"
    try:
        _get_provider()
    except RuntimeError:
        return False, "No AI provider configured; skipping AI classification"
    return True, ""


def classify_with_ai(sender: str, subject: str, snippet: str) -> tuple[bool, str]:
    """
    Use AI to decide whether an email is a commercial ad / promotional message.
    Returns: (is_ad, reason)
    """
    available, reason = _check_ai_available()
    if not available:
        return False, reason

    prompt = (
        "Decide whether the following email is a commercial advertisement or promotional email. "
        'Reply with JSON only, in the format {"is_ad": true/false, "reason": "one-sentence reason"}\n\n'
        f"Sender: {sender}\n"
        f"Subject: {subject}\n"
        f"Snippet: {snippet[:200]}"
    )

    try:
        text = _call_ai(prompt)
        data = _parse_json_response(text)
        is_ad = bool(data.get("is_ad", False))
        reason = data.get("reason", "")
        logger.debug(f"AI verdict: {'ad' if is_ad else 'not ad'} - {reason}")
        return is_ad, reason
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse AI response format: {_mask_secrets(str(e))}")
        return False, f"Failed to parse AI response format: {e}"
    except Exception as e:
        logger.warning(f"AI classification call failed: {_mask_secrets(str(e))}")
        return False, f"AI call failed: {e}"


def categorize_with_ai(sender: str, subject: str) -> str:
    """
    Use AI to decide which email category the sender belongs to.
    Returns a category name and falls back to the default category on failure.
    """
    available, _ = _check_ai_available()
    if not available:
        return "Other"

    categories_str = ", ".join(config.CATEGORY_NAMES)
    prompt = (
        f"Based on the sender and subject, decide which of the following categories this email belongs to: {categories_str}\n"
        'Reply with JSON only, in the format {"category": "category name"}\n\n'
        f"Sender: {sender}\n"
        f"Subject: {subject}"
    )

    try:
        text = _call_ai(prompt)
        data = _parse_json_response(text)
        category = data.get("category", "Other")
        if category not in config.CATEGORY_NAMES:
            logger.debug(f"AI returned unknown category '{category}', falling back to 'Other'")
            return "Other"
        return category
    except Exception as e:
        logger.warning(f"AI classification call failed: {_mask_secrets(str(e))}")
        return "Other"


def test_connection(provider_id: str, api_key: str, model: str, base_url: Optional[str] = None) -> tuple[bool, str]:
    """Test whether the given credentials can successfully call the AI provider."""
    meta = PROVIDERS.get(provider_id)
    if not meta:
        return False, f"Unknown provider: {provider_id}"

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
        return True, "Connection successful"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
