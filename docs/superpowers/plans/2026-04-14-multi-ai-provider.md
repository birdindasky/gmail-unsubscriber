# 多 AI 提供商 + 交互式配置 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Gmail 退订工具支持 8 家主流 AI + 自定义兜底，通过交互式菜单配置 API Key，无需改环境变量。

**Architecture:** 新建 `user_config.py` 模块管理 `user_config.json` 持久化；`ai_classifier.py` 加入 `PROVIDERS` 注册表按 `protocol`（openai / anthropic）分发 SDK 调用；`main.py` 扩展设置菜单；首次启动自动从环境变量迁移。

**Tech Stack:** Python 3.9+、`openai` SDK（已在 requirements 中）、`anthropic` SDK（已有）、`json` 标准库持久化、`pytest` 单元测试。

**参考设计文档：** `docs/superpowers/specs/2026-04-14-multi-ai-provider-design.md`

---

## 文件结构

**新建：**
- `user_config.py` — 负责 `user_config.json` 的读写、迁移、脱敏展示
- `tests/test_user_config.py` — `user_config` 模块的单元测试

**修改：**
- `ai_classifier.py` — 加 `PROVIDERS` 注册表、OpenAI 协议支持、`test_connection()`，配置源从 `user_config` 读取
- `config.py` — 删除 AI 提供商相关常量（保留 `USE_AI_CLASSIFIER` 开关）
- `main.py` — 重写 `_interactive_settings()`；在 `main()` 启动时调 `user_config.migrate_from_env()`
- `tests/test_ai_classifier.py` — 更新现有测试，改用新的 client 获取路径
- `.gitignore` — 加入 `user_config.json`
- `README.md` / `docs/USAGE.md` / `docs/USAGE_GUIDE.md` / `docs/ARCHITECTURE.md` / `docs/FILE_OVERVIEW.md` — 说明更新

**删除：** 无（纯加法 + 重构）

---

## 术语与签名约定

整个计划统一使用以下函数签名，避免前后矛盾：

```python
# user_config.py
def load_config() -> dict
def save_config(config: dict) -> None
def get_active_provider() -> Optional[dict]  # 返回 {"id": str, "api_key": str, "model": str, "base_url": Optional[str]} 或 None
def set_active_provider(provider_id: str, api_key: str, model: str, base_url: Optional[str] = None) -> None
def migrate_from_env() -> bool  # True 表示发生了迁移
def mask_key(key: str) -> str

# ai_classifier.py
PROVIDERS: dict[str, dict]  # 参见 Task 3
def test_connection(provider_id: str, api_key: str, model: str, base_url: Optional[str] = None) -> tuple[bool, str]
def _call_openai(prompt: str, provider: dict) -> str
def _call_anthropic(prompt: str, provider: dict) -> str
```

配置文件字段：

```json
{
  "ai_provider": "deepseek",
  "providers": {
    "deepseek": {"api_key": "sk-xxx", "model": "deepseek-chat"},
    "custom":   {"api_key": "sk-xxx", "model": "my-model", "base_url": "https://api.example.com/v1"}
  }
}
```

---

## Task 1: `.gitignore` 添加 `user_config.json`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: 在 `.gitignore` 中加入 `user_config.json`**

在 `.gitignore` 文件 `user_whitelist.json` 那一行之后加入一行：

```
# 用户自定义白名单（本地配置）
user_whitelist.json

# AI 提供商配置（含 API Key，绝不上传）
user_config.json
```

- [ ] **Step 2: 验证 .gitignore 生效**

```bash
touch user_config.json
git status --short
```

预期输出不应包含 `user_config.json`（只有 `M .gitignore` 这行）。验证后删除：`rm user_config.json`

- [ ] **Step 3: 提交**

```bash
git add .gitignore
git commit -m "chore: gitignore user_config.json"
```

---

## Task 2: 创建 `user_config.py` — 基础读写

**Files:**
- Create: `user_config.py`
- Create: `tests/test_user_config.py`

- [ ] **Step 1: 写失败测试**（读写往返 + 文件不存在 + 损坏 JSON + 脱敏）

写入 `tests/test_user_config.py`：

```python
# -*- coding: utf-8 -*-
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_load_missing_file_returns_empty(tmp_path, monkeypatch):
    import user_config
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(tmp_path / "missing.json"))
    assert user_config.load_config() == {"ai_provider": None, "providers": {}}


def test_load_save_roundtrip(tmp_path, monkeypatch):
    import user_config
    path = str(tmp_path / "cfg.json")
    monkeypatch.setattr(user_config, "CONFIG_FILE", path)
    cfg = {"ai_provider": "deepseek", "providers": {"deepseek": {"api_key": "sk-abc", "model": "deepseek-chat"}}}
    user_config.save_config(cfg)
    assert user_config.load_config() == cfg


def test_load_corrupted_json_returns_empty(tmp_path, monkeypatch):
    import user_config
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(path))
    result = user_config.load_config()
    assert result == {"ai_provider": None, "providers": {}}


def test_mask_key_long():
    import user_config
    assert user_config.mask_key("sk-abcdefghijklmnopqrstuv") == "sk-abc***...pqrstuv"


def test_mask_key_short():
    import user_config
    assert user_config.mask_key("short") == "sk-***"


def test_mask_key_empty():
    import user_config
    assert user_config.mask_key("") == "（未设置）"
```

- [ ] **Step 2: 确认测试失败**

```bash
source venv/bin/activate
pytest tests/test_user_config.py -v
```

预期：全部失败（`ModuleNotFoundError: No module named 'user_config'`）。

- [ ] **Step 3: 实现 `user_config.py` 基础读写 + 脱敏**

创建 `user_config.py`：

```python
# -*- coding: utf-8 -*-
"""
用户 AI 配置管理 - 读写 user_config.json，支持环境变量迁移和 Key 脱敏。
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_config.json")


def load_config() -> dict:
    """加载配置文件。文件不存在或损坏时返回空配置。"""
    default = {"ai_provider": None, "providers": {}}
    if not os.path.exists(CONFIG_FILE):
        return default
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        data.setdefault("ai_provider", None)
        data.setdefault("providers", {})
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"user_config.json 读取失败（{e}），将当作未配置处理")
        return default


def save_config(config: dict) -> None:
    """保存配置到文件。"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def mask_key(key: str) -> str:
    """脱敏展示：前 6 位 + ***... + 后 6 位。"""
    if not key:
        return "（未设置）"
    if len(key) < 15:
        return "sk-***"
    return f"{key[:6]}***...{key[-6:]}"


def get_active_provider() -> Optional[dict]:
    """返回当前活跃提供商信息，未配置时返回 None。"""
    cfg = load_config()
    pid = cfg.get("ai_provider")
    if not pid:
        return None
    provider = cfg.get("providers", {}).get(pid)
    if not provider or not provider.get("api_key"):
        return None
    return {
        "id": pid,
        "api_key": provider["api_key"],
        "model": provider.get("model", ""),
        "base_url": provider.get("base_url"),
    }


def set_active_provider(provider_id: str, api_key: str, model: str, base_url: Optional[str] = None) -> None:
    """设置活跃提供商并保存。"""
    cfg = load_config()
    entry = {"api_key": api_key, "model": model}
    if base_url:
        entry["base_url"] = base_url
    cfg.setdefault("providers", {})[provider_id] = entry
    cfg["ai_provider"] = provider_id
    save_config(cfg)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_user_config.py -v
```

预期：6 项全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add user_config.py tests/test_user_config.py
git commit -m "feat: add user_config module for AI provider persistence"
```

---

## Task 3: `user_config.py` 添加 `migrate_from_env()`

**Files:**
- Modify: `user_config.py`
- Modify: `tests/test_user_config.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_user_config.py` 末尾追加：

```python
def test_migrate_from_env_minimax(tmp_path, monkeypatch):
    import user_config
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
    import user_config
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    assert user_config.migrate_from_env() is True
    provider = user_config.get_active_provider()
    assert provider["id"] == "anthropic"
    assert provider["api_key"] == "sk-ant-test"


def test_migrate_skips_if_config_exists(tmp_path, monkeypatch):
    import user_config
    path = tmp_path / "cfg.json"
    path.write_text('{"ai_provider": "deepseek", "providers": {"deepseek": {"api_key": "x", "model": "y"}}}')
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(path))
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-should-not-overwrite")

    assert user_config.migrate_from_env() is False
    # 原配置应保持不变
    assert user_config.get_active_provider()["id"] == "deepseek"


def test_migrate_no_env_returns_false(tmp_path, monkeypatch):
    import user_config
    monkeypatch.setattr(user_config, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)

    assert user_config.migrate_from_env() is False
    assert user_config.get_active_provider() is None
```

- [ ] **Step 2: 确认测试失败**

```bash
pytest tests/test_user_config.py::test_migrate_from_env_minimax -v
```

预期：FAIL（`AttributeError: module 'user_config' has no attribute 'migrate_from_env'`）。

- [ ] **Step 3: 实现 `migrate_from_env()`**

在 `user_config.py` 文件末尾追加：

```python
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
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_user_config.py -v
```

预期：10 项全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add user_config.py tests/test_user_config.py
git commit -m "feat: auto-migrate AI config from env vars on first run"
```

---

## Task 4: `ai_classifier.py` 添加 `PROVIDERS` 注册表

**Files:**
- Modify: `ai_classifier.py:11-28`

- [ ] **Step 1: 在 `ai_classifier.py` 顶部（`import` 之后、`_get_anthropic_client` 之前）插入 `PROVIDERS` 常量**

读取 `ai_classifier.py:11-19` 确认 `import config` 后的位置，然后在那里插入：

```python
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
```

- [ ] **Step 2: 运行现有测试确认无回归**

```bash
pytest tests/ -v
```

预期：已有测试继续通过（本步只是新增常量，未修改任何函数）。

- [ ] **Step 3: 提交**

```bash
git add ai_classifier.py
git commit -m "feat: add PROVIDERS registry for 9 AI providers"
```

---

## Task 5: `ai_classifier.py` 重构为按协议分发

**Files:**
- Modify: `ai_classifier.py` — 重写 `_get_client`、`_call_ai`、`_call_minimax`、`_call_anthropic`、`_check_ai_available`

- [ ] **Step 1: 写失败测试**（OpenAI 协议分发）

在 `tests/test_ai_classifier.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行新测试确认失败**

```bash
pytest tests/test_ai_classifier.py::test_call_ai_routes_openai_protocol -v
```

预期：FAIL（函数 `_call_openai` 不存在）。

- [ ] **Step 3: 重写 `ai_classifier.py` 的调用分发部分**

打开 `ai_classifier.py`，**保留** 顶部的 `import` 和 Task 4 新加的 `PROVIDERS` 常量，把从 `def _get_anthropic_client():` 开始、到 `def _check_ai_available()` 结束的**整段函数定义**替换为以下内容（包括底部那行 `_get_client = _get_anthropic_client` 一并删除）：

```python
import user_config


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
        max_tokens=1024,
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
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip() if resp.choices else ""


def _call_ai(prompt: str) -> str:
    """按活跃提供商的 protocol 分发调用。"""
    provider = user_config.get_active_provider()
    if not provider:
        raise RuntimeError("未配置 AI 提供商")
    meta = PROVIDERS.get(provider["id"])
    if not meta:
        raise ValueError(f"未知提供商：{provider['id']}")
    if meta["protocol"] == "openai":
        return _call_openai(prompt, provider)
    elif meta["protocol"] == "anthropic":
        return _call_anthropic(prompt, provider)
    else:
        raise ValueError(f"未知协议：{meta['protocol']}")


def _check_ai_available() -> tuple[bool, str]:
    if not config.USE_AI_CLASSIFIER:
        return False, "AI 分类已关闭"
    provider = user_config.get_active_provider()
    if not provider:
        return False, "未配置 AI 提供商，跳过 AI 分类"
    return True, ""
```

**同时删除旧代码：** 删掉原来的 `_get_anthropic_client`、`_get_minimax_client`、`_call_minimax`（新版 `_call_anthropic` 已统一替代）、以及底部向后兼容的 `_get_client = _get_anthropic_client` 行。

- [ ] **Step 4: 运行所有测试检查现有测试的兼容性**

```bash
pytest tests/test_ai_classifier.py -v
```

预期：**旧测试会失败**（它们 patch 的是 `_get_client`，该函数已不存在）。新测试应通过 3 项。记录下旧测试的失败名称，Task 6 会修复。

- [ ] **Step 5: 提交**

```bash
git add ai_classifier.py tests/test_ai_classifier.py
git commit -m "refactor: route AI calls by provider protocol"
```

---

## Task 6: 修复 `test_ai_classifier.py` 旧测试

**Files:**
- Modify: `tests/test_ai_classifier.py`（前两个测试 `test_classify_ad_email` / `test_classify_non_ad_email`、`test_categorize_with_ai` 如有）

- [ ] **Step 1: 查看当前失败的测试**

```bash
pytest tests/test_ai_classifier.py -v 2>&1 | grep -E "FAIL|PASS"
```

记录失败的测试名。

- [ ] **Step 2: 重写失败的测试改用新 patch 路径**

`tests/test_ai_classifier.py` 开头保留原 imports，然后把 `test_classify_ad_email` 和 `test_classify_non_ad_email` 替换为：

```python
def test_classify_ad_email():
    import ai_classifier
    with patch("ai_classifier.user_config") as mock_uc, \
         patch("ai_classifier._call_anthropic", return_value=json.dumps({"is_ad": True, "reason": "促销邮件，含折扣信息"})), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
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
        mock_uc.get_active_provider.return_value = {
            "id": "anthropic", "api_key": "sk-ant-test", "model": "claude-haiku-4-5", "base_url": None,
        }
        is_ad, reason = ai_classifier.classify_with_ai(
            sender="noreply@github.com",
            subject="Your pull request was merged",
            snippet="Your PR #123 has been merged into main"
        )
    assert is_ad is False
```

同时检查文件中若还有其他引用 `ai_classifier._get_client`、`config.AI_MODEL`、`config.AI_MAX_TOKENS`、`config.ANTHROPIC_API_KEY` 的旧测试，按上述模式统一替换（patch `user_config` + `_call_anthropic` 或 `_call_openai`）。

- [ ] **Step 3: 跑全部测试确认通过**

```bash
pytest tests/ -v
```

预期：所有测试（含新加的）PASS。

- [ ] **Step 4: 提交**

```bash
git add tests/test_ai_classifier.py
git commit -m "test: update ai_classifier tests for new provider routing"
```

---

## Task 7: `ai_classifier.py` 添加 `test_connection()`

**Files:**
- Modify: `ai_classifier.py`（追加函数）
- Modify: `tests/test_ai_classifier.py`（追加测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_ai_classifier.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 确认失败**

```bash
pytest tests/test_ai_classifier.py::test_test_connection_success -v
```

预期：FAIL（`test_connection` 不存在）。

- [ ] **Step 3: 在 `ai_classifier.py` 末尾追加 `test_connection()`**

```python
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
```

同时在文件顶部 import 区域加：

```python
from typing import Optional
```

（若已 import 则跳过）

- [ ] **Step 4: 跑测试**

```bash
pytest tests/test_ai_classifier.py -v
```

预期：全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add ai_classifier.py tests/test_ai_classifier.py
git commit -m "feat: add test_connection() for validating AI credentials"
```

---

## Task 8: 清理 `config.py` 中的 AI 提供商常量

**Files:**
- Modify: `config.py:165-190`

- [ ] **Step 1: 删除旧的 AI 提供商常量**

打开 `config.py`，定位到第 165-190 行（AI 配置区域），**只保留** `USE_AI_CLASSIFIER = True`，删除其他：

删除前：
```python
# ────────────────────────────────────────────────────────────────
#  AI 分类配置
# ────────────────────────────────────────────────────────────────

USE_AI_CLASSIFIER = True

# Anthropic API Key（也可通过环境变量 ANTHROPIC_API_KEY 设置）
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

AI_MODEL = "claude-haiku-4-5-20251001"

AI_MAX_TOKENS = 150

# ────────────────────────────────────────────────────────────────
#  MiniMax AI 配置
# ────────────────────────────────────────────────────────────────

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_MODEL = "MiniMax-M2.7"
MINIMAX_BASE_URL = "https://api.minimaxi.com/anthropic"

AI_PROVIDER = os.environ.get("AI_PROVIDER", "minimax")
```

删除后：
```python
# ────────────────────────────────────────────────────────────────
#  AI 分类总开关
# ────────────────────────────────────────────────────────────────

# 是否启用 AI 辅助分类（关键词命中 1 条时触发）
# 具体提供商、API Key、模型均由 user_config.json 管理
# 通过 python3 main.py → 菜单「5. 设置」→「配置 AI 提供商」交互配置
USE_AI_CLASSIFIER = True
```

- [ ] **Step 2: 跑所有测试**

```bash
pytest tests/ -v
```

预期：全部 PASS。若有任何测试因引用已删除常量失败，在测试里把相关引用删掉或 patch 掉。

- [ ] **Step 3: 提交**

```bash
git add config.py tests/
git commit -m "refactor: remove AI provider constants from config.py"
```

---

## Task 9: `main.py` 启动时自动迁移环境变量

**Files:**
- Modify: `main.py:806-`（`main()` 函数开头）

- [ ] **Step 1: 查看 `main()` 入口位置**

```bash
grep -n "^def main" main.py
```

预期输出：`806:def main() -> None:`

- [ ] **Step 2: 在 `main()` 的日志初始化之后、真正处理命令之前插入迁移调用**

读取 `main.py:806-825` 确认当前结构，然后在 `setup_logging(...)` 之后、`if args.command is None` 之前插入：

```python
    # 首次启动：尝试从环境变量迁移 AI 配置
    import user_config
    if user_config.migrate_from_env():
        print("🔄 检测到环境变量中的 AI 配置，已自动迁移到 user_config.json")
        provider = user_config.get_active_provider()
        if provider:
            from ai_classifier import PROVIDERS
            name = PROVIDERS.get(provider["id"], {}).get("name", provider["id"])
            print(f"✅ 当前使用 {name}（模型：{provider['model']}）\n")
```

- [ ] **Step 3: 手动测试迁移**

```bash
# 备份现有配置
[ -f user_config.json ] && mv user_config.json user_config.json.bak

# 模拟老用户
export MINIMAX_API_KEY="sk-cp-test-migration"
python3 -c "import user_config; print(user_config.migrate_from_env()); print(user_config.get_active_provider())"

# 清理
rm -f user_config.json
[ -f user_config.json.bak ] && mv user_config.json.bak user_config.json
unset MINIMAX_API_KEY
```

预期：打印 `True` 和完整的 provider dict。

- [ ] **Step 4: 跑全部测试**

```bash
pytest tests/ -v
```

预期：全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add main.py
git commit -m "feat: auto-migrate env vars to user_config.json on startup"
```

---

## Task 10: `main.py` 重写 `_interactive_settings()` 菜单

**Files:**
- Modify: `main.py:576-590`（现有 `_interactive_settings()` 整段替换）

- [ ] **Step 1: 写简单的集成测试**（可选但推荐）

在 `tests/test_interactive.py` 末尾追加：

```python
def test_mask_key_integration():
    """验证设置菜单使用的脱敏函数能处理正常 Key。"""
    import user_config
    result = user_config.mask_key("sk-abcdefghijklmnopqrstuv")
    assert "..." in result
    assert result.startswith("sk-abc")
```

跑 `pytest tests/test_interactive.py::test_mask_key_integration -v` 应通过。

- [ ] **Step 2: 替换 `_interactive_settings()` 整个函数**

打开 `main.py`，找到 `def _interactive_settings():`（约第 576 行），把该函数整体替换为：

```python
def _interactive_settings() -> None:
    """交互式设置菜单。"""
    import user_config
    from ai_classifier import PROVIDERS, test_connection

    while True:
        provider = user_config.get_active_provider()
        if provider:
            meta = PROVIDERS.get(provider["id"], {})
            status = f"{meta.get('name', provider['id'])} / {provider['model']}"
        else:
            status = "未配置"

        print("\n╔══════════════════════════════════╗")
        print("║       ⚙️  设置                    ║")
        print("╠══════════════════════════════════╣")
        print(f"║  1. 配置 AI 提供商 (当前：{status})")
        print( "║  2. 查看当前配置")
        print( "║  0. 返回")
        print( "╚══════════════════════════════════╝")

        choice = input("请选择：").strip()
        if choice == "1":
            _configure_ai_provider()
        elif choice == "2":
            _show_current_ai_config()
        elif choice == "0":
            return
        else:
            print("❌ 无效选择")


def _configure_ai_provider() -> None:
    """交互式配置 AI 提供商。"""
    import user_config
    from ai_classifier import PROVIDERS, test_connection

    # 固定顺序展示
    order = ["openai", "anthropic", "minimax", "deepseek", "moonshot", "qwen", "zhipu", "ollama", "custom"]
    print("\n请选择 AI 提供商：")
    for i, pid in enumerate(order, 1):
        meta = PROVIDERS[pid]
        print(f"  {i}. {meta['name']:<22} ({meta['key_hint']})")
    print("  0. 返回")

    sel = input("请选择：").strip()
    if sel == "0":
        return
    try:
        idx = int(sel) - 1
        provider_id = order[idx]
    except (ValueError, IndexError):
        print("❌ 无效选择")
        return

    meta = PROVIDERS[provider_id]
    print(f"\n【{meta['name']}】")

    # 自定义提供商额外询问 base_url 和 model
    base_url = meta["base_url"]
    if provider_id == "custom":
        base_url = input("请输入 base_url: ").strip()
        if not base_url:
            print("❌ base_url 不能为空")
            return
        model = input("请输入 model: ").strip()
        if not model:
            print("❌ model 不能为空")
            return
    else:
        model = meta["default_model"]

    api_key = input(f"请输入 API Key ({meta['key_hint']}): ").strip()
    if not api_key:
        print("❌ API Key 不能为空")
        return

    # 非自定义且有默认模型时，允许用户替换
    if provider_id != "custom":
        ans = input(f"默认模型：{model}，使用默认吗？(Y/n): ").strip().lower()
        if ans == "n":
            model = input("请输入模型名: ").strip()
            if not model:
                print("❌ 模型名不能为空")
                return

    print("\n🔍 测试连接中...")
    ok, msg = test_connection(provider_id, api_key, model, base_url)
    if not ok:
        print(f"❌ 连接失败：{msg}")
        print("   配置未保存，请检查 Key / 模型 / 网络后重试")
        return

    user_config.set_active_provider(provider_id, api_key, model, base_url if provider_id == "custom" else None)
    print(f"✅ 连接成功！已保存配置。当前使用：{meta['name']}（模型：{model}）")


def _show_current_ai_config() -> None:
    """查看当前 AI 配置（Key 脱敏）。"""
    import user_config
    from ai_classifier import PROVIDERS

    provider = user_config.get_active_provider()
    if not provider:
        print("\n当前未配置 AI 提供商。")
        print("运行设置菜单 → 1. 配置 AI 提供商 进行配置。")
        return

    meta = PROVIDERS.get(provider["id"], {})
    print("\n当前 AI 配置：")
    print(f"  提供商：{meta.get('name', provider['id'])}")
    print(f"  模型：  {provider['model']}")
    print(f"  Key：   {user_config.mask_key(provider['api_key'])}")
    if provider.get("base_url"):
        print(f"  Base URL：{provider['base_url']}")
    import config
    print(f"  AI 总开关：{'开启' if config.USE_AI_CLASSIFIER else '关闭'}")
```

- [ ] **Step 3: 手动冒烟测试**

```bash
python3 main.py
```

进入菜单选 `5` → `1`，选一个提供商（如 DeepSeek）测试流程。用一个**故意错误**的 Key（如 `sk-wrong`）测试连接失败会回到菜单。然后 Ctrl+C 退出，**不真正保存**（或保存后再手动删除 `user_config.json`）。

- [ ] **Step 4: 跑全部测试**

```bash
pytest tests/ -v
```

预期：全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add main.py tests/test_interactive.py
git commit -m "feat: interactive AI provider configuration menu"
```

---

## Task 11: 更新文档

**Files:**
- Modify: `README.md`
- Modify: `docs/USAGE.md`
- Modify: `docs/USAGE_GUIDE.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/FILE_OVERVIEW.md`

- [ ] **Step 1: `README.md` 更新 AI 支持段**

找到 `## 🤖 AI 支持` 段，替换为：

```markdown
## 🤖 AI 支持

支持 8 家主流 AI 提供商 + 自定义兜底，通过菜单交互式配置（无需改环境变量）：

**直接运行 → 菜单 → 5. 设置 → 1. 配置 AI 提供商**，30 秒搞定。

内置支持：**OpenAI、Anthropic Claude、MiniMax、DeepSeek、Moonshot(Kimi)、通义千问、智谱 GLM、Ollama**，以及任何 OpenAI 兼容接口（自定义入口）。

- 配置保存在 `user_config.json`（已加入 `.gitignore`）
- 同一发件人只调用一次 AI（结果缓存到运行结束），节省费用
- 首次启动会自动从环境变量迁移老配置，无感升级
- 未配置 AI 时自动跳过，不影响基本功能
```

- [ ] **Step 2: `docs/USAGE.md` 替换「AI 模型配置」整段**

找到 `## AI 模型配置` 整节，替换为：

```markdown
## AI 模型配置

通过交互菜单配置即可，无需改环境变量：

```bash
python3 main.py
# → 选 5. 设置
# → 选 1. 配置 AI 提供商
# → 选择提供商（1-9）
# → 粘贴 API Key
# → 自动测试连接
# → ✅ 保存
```

**支持的提供商：** OpenAI、Anthropic Claude、MiniMax、DeepSeek、Moonshot、通义千问、智谱 GLM、Ollama（本地），以及任何 OpenAI 兼容服务（自定义入口）。

配置保存在项目根目录的 `user_config.json`（加入 `.gitignore`，不会上传 git）。

**老用户无感迁移**：如果您之前通过环境变量配置过 MiniMax / Anthropic，首次运行新版本会自动迁移，不需要重新填。

**AI 调用是缓存的**：同一个发件人邮箱只会调用一次 AI，结果在本次运行内复用，避免对同一域名的 100 封邮件做 100 次 AI 请求。
```

- [ ] **Step 3: `docs/USAGE_GUIDE.md` 替换「9. AI 辅助判断（可选）」整节**

找到 `## 9. AI 辅助判断（可选）` 整节（到 `## 10. 安全说明` 之前），替换为：

```markdown
## 9. AI 辅助判断（可选）

### 一键配置：使用交互菜单

```bash
python3 main.py
# 选择 5. 设置
# 选择 1. 配置 AI 提供商
```

按提示选择提供商、粘贴 API Key、确认模型，程序会自动测试连接，成功后立即保存。

### 支持的提供商

| 提供商 | 协议 | 备注 |
|--------|------|------|
| OpenAI | OpenAI | 模型：gpt-4o-mini（默认） |
| Anthropic Claude | Anthropic | 模型：claude-haiku-4-5（默认） |
| MiniMax | Anthropic 兼容 | 国内模型，费用低 |
| DeepSeek | OpenAI 兼容 | 国内模型，费用低 |
| Moonshot (Kimi) | OpenAI 兼容 | 国内模型 |
| 通义千问 | OpenAI 兼容 | 阿里云 |
| 智谱 GLM | OpenAI 兼容 | GLM-4-Flash 默认 |
| Ollama (本地) | OpenAI 兼容 | 自己电脑跑，免费 |
| 自定义 | OpenAI 兼容 | 任何 OpenAI 协议服务都能接 |

### 配置文件位置

所有配置存于项目根目录 `user_config.json`（已加入 `.gitignore`，不会上传 git）：

```json
{
  "ai_provider": "deepseek",
  "providers": {
    "deepseek": {"api_key": "sk-...", "model": "deepseek-chat"}
  }
}
```

### AI 调用会被缓存

- **按发件人缓存**：同一个发件人邮箱，AI 只会被问一次，后续同发件人的邮件直接复用结果
- **按域名缓存**：归类阶段，同一个域名也只问一次
- 缓存只在本次运行内有效，重新启动程序后重新计算

### 关闭 AI

```bash
python3 main.py scan --no-ai              # 本次不用 AI
python3 main.py unsubscribe --no-ai ...   # 本次不用 AI
```

或者在 `config.py` 中永久关闭：
```python
USE_AI_CLASSIFIER = False
```

### 老用户无感迁移

如果您之前通过 `export MINIMAX_API_KEY=...` 等环境变量配置过，首次启动新版本会自动生成 `user_config.json`，您不需要做任何事。

### 查看当前配置

交互菜单 → 5. 设置 → 2. 查看当前配置。API Key 会脱敏展示（前 6 位 + 后 6 位）。
```

- [ ] **Step 4: `docs/ARCHITECTURE.md` 更新架构图和决策说明**

在 `docs/ARCHITECTURE.md` 的架构图里，把 `config.py` 下面那行加上 `user_config.json`：

找到：
```
└──────▶│           config.py                 │◀────────┘
         │ 白名单/关键词/AI 提供商开关/域名分类 │
         └─────────────────────────────────────┘
```

替换为：
```
└──────▶│           config.py                 │◀────────┘
         │ 白名单/关键词/USE_AI 总开关/域名分类│
         └─────────────────────────────────────┘
                         ▲
                         │（AI 提供商配置独立）
         ┌───────────────┴───────────────────┐
         │     user_config.py                │
         │  user_config.json（运行时写入）    │
         │  管理活跃提供商 + API Key + 模型   │
         └───────────────────────────────────┘
```

同时在"设计决策"区域加一节：

```markdown
### 为什么把 AI 提供商配置从 `config.py` 搬到 `user_config.json`？

`config.py` 是代码的一部分（跟随版本管理），而 API Key 是每个用户独立的秘密。硬编码在 `config.py` 意味着要么用户自己改代码（容易误提交到 git），要么走环境变量（对小白不友好）。

独立的 `user_config.json`：
- 加入 `.gitignore`，不会误上传
- 通过交互菜单读写，用户不用改代码、不用改 shell 配置
- 格式是通用 JSON，出问题时用户能直接打开看一眼
- 首次启动时自动从环境变量迁移，老用户无感升级

提供商元数据（`base_url`、`default_model`、协议）仍然硬编码在 `ai_classifier.py` 的 `PROVIDERS` 字典里——这些是代码的一部分，不是秘密，跟着版本走。
```

- [ ] **Step 5: `docs/FILE_OVERVIEW.md` 新增 `user_config.py` 一节**

在 `ai_classifier.py` 这一节之前（或 `config.py` 节之后）插入：

```markdown
---

## `user_config.py` — 用户 AI 配置管理

**职责：** 管理 `user_config.json` 的读写、首次启动的环境变量迁移、API Key 脱敏展示。和 `config.py`（代码内置的常量）分开，目的是把**每个用户独有的秘密配置**（API Key）和**跟随代码的公共常量**（白名单、关键词）解耦。

**关键函数：**

| 函数名 | 说明 |
|--------|------|
| `load_config()` | 加载 `user_config.json`，不存在或损坏时返回空配置 |
| `save_config(config)` | 保存配置到文件 |
| `get_active_provider()` | 返回当前活跃提供商信息；未配置返回 `None` |
| `set_active_provider(id, api_key, model, base_url=None)` | 设置活跃提供商并保存 |
| `migrate_from_env()` | 首次启动时从环境变量迁移，返回是否发生迁移 |
| `mask_key(key)` | 脱敏展示（前 6 + `***...` + 后 6） |

**配置文件格式（`user_config.json`）：**

```json
{
  "ai_provider": "deepseek",
  "providers": {
    "deepseek": {"api_key": "sk-...", "model": "deepseek-chat"}
  }
}
```

**被哪些模块调用：**
- `ai_classifier.py` 调用 `get_active_provider()` 拿当前配置
- `main.py` 启动时调 `migrate_from_env()`，设置菜单中调 `set_active_provider()` / `mask_key()` / `get_active_provider()`

**依赖：**
- 标准库：`json`、`logging`、`os`、`typing`
```

同时刷新 `ai_classifier.py` 一节的描述：把"MiniMax / Anthropic 双提供商"改为"9 家提供商按协议分发（OpenAI / Anthropic 两种协议）"；把函数表中 `_get_client` 系列换成 `_call_openai` / `_call_anthropic` / `test_connection`。

- [ ] **Step 6: 跑全部测试 + 语法检查**

```bash
pytest tests/ -v
python3 -c "import user_config, ai_classifier, main"
```

预期：测试全 PASS，三个模块都能成功 import（无语法错误）。

- [ ] **Step 7: 提交**

```bash
git add README.md docs/
git commit -m "docs: describe multi-AI provider and interactive config"
```

---

## Task 12: 端到端手动测试（最终验收）

**Files:** 无代码变更

- [ ] **Step 1: 环境变量迁移测试**

```bash
# 清空配置
rm -f user_config.json

# 设环境变量模拟老用户
export MINIMAX_API_KEY="sk-cp-your-real-minimax-key"
export AI_PROVIDER="minimax"

# 启动
python3 main.py
```

预期：启动时打印「🔄 检测到环境变量中的 AI 配置，已自动迁移…」，`user_config.json` 生成。

- [ ] **Step 2: 菜单配置测试**

```bash
python3 main.py
# 选 5 → 1 → 选提供商 → 填 Key → 默认模型 y
# 连接成功后保存
```

预期：`user_config.json` 中 `ai_provider` 字段更新。

- [ ] **Step 3: 错误 Key 处理测试**

菜单中重新配置，故意输错 Key。预期：打印「❌ 连接失败」，配置未保存（`user_config.json` 保持之前的正确配置）。

- [ ] **Step 4: 扫描+分类实测**

```bash
python3 main.py
# 选 1 → 扫描最近 30 天
```

预期：扫描过程中 AI 调用日志里能看到"通过新提供商"的请求被发出；无异常报错。

- [ ] **Step 5: 查看配置**

菜单 → 5 → 2。预期：Key 以脱敏形式显示（前 6 + `***...` + 后 6）。

- [ ] **Step 6: 清理环境变量，重新启动验证**

```bash
unset MINIMAX_API_KEY
unset AI_PROVIDER
python3 main.py
```

预期：仍然能读取 `user_config.json` 中的配置，菜单「查看配置」正常显示。

- [ ] **Step 7: 如一切正常，打标签**

```bash
git log --oneline -15   # 快速查看本轮所有提交
```

（不强制打 tag，但可选 `git tag v2-multi-ai-provider` 方便日后回溯）

---

## 验收标准

- [ ] 所有 pytest 测试通过（原 47 + 新增约 15+ = 62+）
- [ ] 新老用户均无感使用：有环境变量的自动迁移，无环境变量的菜单配置
- [ ] API Key 文件 `user_config.json` 不会被 git 追踪
- [ ] 9 个提供商中至少一个真实 Key 能走通完整扫描流程
- [ ] 所有文档（README / USAGE / USAGE_GUIDE / ARCHITECTURE / FILE_OVERVIEW）描述一致，无矛盾

---

（计划结束）
