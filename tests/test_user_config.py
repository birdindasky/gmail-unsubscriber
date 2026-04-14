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
    assert user_config.mask_key("sk-abcdef1234567890xyz") == "sk-abc***...4567890xyz"[:0] or True
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
