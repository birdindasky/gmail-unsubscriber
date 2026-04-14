import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

import user_config


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    cfg = tmp_path / "user_config.json"
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(cfg))
    return cfg


def test_load_missing_file_returns_empty(tmp_config):
    result = user_config.load_config()
    assert result == {"ai_provider": None, "providers": {}}


def test_load_corrupted_json_returns_empty(tmp_config):
    tmp_config.write_text("{ not valid json")
    result = user_config.load_config()
    assert result == {"ai_provider": None, "providers": {}}


def test_save_then_load_roundtrip(tmp_config):
    data = {"ai_provider": "minimax",
            "providers": {"minimax": {"api_key": "sk-abc", "model": "MiniMax-M2", "base_url": None}}}
    user_config.save_config(data)
    assert json.loads(tmp_config.read_text()) == data
    assert user_config.load_config() == data


def test_mask_key_long():
    masked = user_config.mask_key("sk-abcdef1234567890xyz")
    assert masked.startswith("sk-abc")
    assert masked.endswith("890xyz")
    assert "***" in masked


def test_mask_key_short():
    # short keys (<= 12 chars) get fully masked
    assert user_config.mask_key("short") == "***"
    assert user_config.mask_key("") == "***"


def test_get_and_set_active_provider(tmp_config):
    assert user_config.get_active_provider() is None
    user_config.set_active_provider("minimax", "sk-xyz", "MiniMax-M2")
    active = user_config.get_active_provider()
    assert active["id"] == "minimax"
    assert active["api_key"] == "sk-xyz"
    assert active["model"] == "MiniMax-M2"
    assert active["base_url"] is None


def test_migrate_from_env_minimax(tmp_path, monkeypatch):
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-test")
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert user_config.migrate_from_env() is True
    provider = user_config.get_active_provider()
    assert provider["id"] == "minimax"
    assert provider["api_key"] == "sk-cp-test"
    assert provider["model"] == "MiniMax-M2"


def test_migrate_from_env_anthropic(tmp_path, monkeypatch):
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    assert user_config.migrate_from_env() is True
    provider = user_config.get_active_provider()
    assert provider["id"] == "anthropic"
    assert provider["api_key"] == "sk-ant-test"


def test_migrate_skips_if_config_exists(tmp_path, monkeypatch):
    path = tmp_path / "cfg.json"
    path.write_text('{"ai_provider": "deepseek", "providers": {"deepseek": {"api_key": "x", "model": "y"}}}')
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(path))
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-should-not-overwrite")

    assert user_config.migrate_from_env() is False
    assert user_config.get_active_provider()["id"] == "deepseek"


def test_migrate_no_env_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)

    assert user_config.migrate_from_env() is False
    assert user_config.get_active_provider() is None
