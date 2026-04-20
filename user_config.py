"""用户配置持久化（AI 提供商选择 + API Key）。

存储在项目根目录 user_config.json（已在 .gitignore 中排除）。
"""
import json
import os
from typing import Optional

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_config.json")

_EMPTY = {"ai_provider": None, "providers": {}}


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return _EMPTY.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _EMPTY.copy()
        data.setdefault("ai_provider", None)
        data.setdefault("providers", {})
        return data
    except (json.JSONDecodeError, OSError):
        return _EMPTY.copy()


def save_config(config: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG_FILE, 0o600)


def mask_key(key: str) -> str:
    if not key or len(key) <= 12:
        return "***"
    return f"{key[:6]}***...{key[-6:]}"


def get_active_provider() -> Optional[dict]:
    cfg = load_config()
    pid = cfg.get("ai_provider")
    if not pid:
        return None
    info = cfg.get("providers", {}).get(pid)
    if not info or not info.get("api_key"):
        return None
    return {
        "id": pid,
        "api_key": info["api_key"],
        "model": info.get("model"),
        "base_url": info.get("base_url"),
    }


def set_active_provider(provider_id: str, api_key: str, model: str,
                        base_url: Optional[str] = None) -> None:
    cfg = load_config()
    cfg["ai_provider"] = provider_id
    cfg.setdefault("providers", {})[provider_id] = {
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
    }
    save_config(cfg)


def migrate_from_env() -> bool:
    """首次启动时从环境变量迁移 AI 配置。已有配置则不迁移。返回是否迁移。"""
    if os.path.exists(CONFIG_FILE):
        return False

    provider_env = os.environ.get("AI_PROVIDER", "").strip().lower()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    minimax_key = os.environ.get("MINIMAX_API_KEY", "").strip()

    if provider_env == "anthropic" and anthropic_key:
        set_active_provider("anthropic", anthropic_key, "claude-haiku-4-5")
        return True
    if minimax_key:
        set_active_provider("minimax", minimax_key, "MiniMax-M2")
        return True
    if anthropic_key:
        set_active_provider("anthropic", anthropic_key, "claude-haiku-4-5")
        return True

    return False
