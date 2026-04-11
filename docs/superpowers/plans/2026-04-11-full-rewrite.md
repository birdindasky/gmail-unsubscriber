# Gmail 智能退订器全面重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全面重构 Gmail 退订工具：修复假 mailto 退订、引入 SQLite 历史记录防重复、Gmail 批量 API 提速 10 倍、Claude AI 辅助分类（可开关）、退订后自动打标签和可选归档，最后附上详细使用说明。

**Architecture:** 新增 `database.py`（SQLite 状态管理）和 `ai_classifier.py`（Claude AI 判断）；升级 `scanner.py` 用批量 API 并过滤已退订发件人；升级 `classifier.py` 集成 AI；升级 `unsubscriber.py` 修复 mailto 并加入标签/归档；升级 `main.py` 新增 history 命令和新参数；最后写详细使用说明。

**Tech Stack:** Python 3.9+, Gmail API v1, anthropic SDK, sqlite3（标准库）, pytest, unittest.mock

---

## 文件结构

| 状态 | 路径 | 职责 |
|------|------|------|
| 新增 | `database.py` | SQLite 封装：退订历史、扫描记录、用户白名单 |
| 新增 | `ai_classifier.py` | Claude AI 判断单封邮件是否为广告 |
| 新增 | `tests/__init__.py` | pytest 包标记 |
| 新增 | `tests/test_database.py` | database.py 的单元测试 |
| 新增 | `tests/test_ai_classifier.py` | ai_classifier.py 的单元测试 |
| 新增 | `tests/test_classifier.py` | classifier.py 改动后的测试 |
| 新增 | `tests/test_scanner.py` | scanner.py 批量 API 和过滤功能测试 |
| 新增 | `tests/test_unsubscriber.py` | unsubscriber.py 修复后的测试 |
| 升级 | `config.py` | 新增 AI 开关、SQLite 路径；精简 SUSPICIOUS_SENDER_KEYWORDS |
| 升级 | `scanner.py` | 批量 API + 已退订过滤 + 促销标签优先 |
| 升级 | `classifier.py` | AI 集成 + message_ids 追踪 |
| 升级 | `unsubscriber.py` | 修复 mailto + 添加标签 + 归档 |
| 升级 | `main.py` | history 命令 + --archive / --no-ai / --all 参数 |
| 升级 | `requirements.txt` | 新增 anthropic |
| 新增 | `docs/USAGE_GUIDE.md` | 详细中文使用说明 |

---

## Task 1: 更新 requirements.txt 和 config.py

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: 在 requirements.txt 末尾追加 anthropic**

将 `requirements.txt` 改为：
```
google-auth>=2.0.0
google-auth-oauthlib>=1.0.0
google-auth-httplib2>=0.1.0
google-api-python-client>=2.0.0
requests>=2.28.0
beautifulsoup4>=4.11.0
lxml>=4.9.0
anthropic>=0.40.0
```

- [ ] **Step 2: 安装新依赖**

```bash
cd /Users/bossoffice/gmail-unsubscriber
source venv/bin/activate
pip install anthropic
```

预期输出包含：`Successfully installed anthropic-...`

- [ ] **Step 3: 更新 config.py — 新增 AI 配置和 SQLite 路径**

在 `config.py` 文件末尾（`add_to_user_whitelist` 函数之后）追加：

```python
# ────────────────────────────────────────────────────────────────
#  AI 分类配置
# ────────────────────────────────────────────────────────────────

# 是否启用 Claude AI 辅助分类（关键词命中 1 条时触发）
USE_AI_CLASSIFIER = True

# Anthropic API Key（也可通过环境变量 ANTHROPIC_API_KEY 设置）
ANTHROPIC_API_KEY = ""

# 使用的 Claude 模型（haiku 最快最便宜）
AI_MODEL = "claude-haiku-4-5-20251001"

# AI 回复的最大 token 数（只需简短 JSON）
AI_MAX_TOKENS = 150

# ────────────────────────────────────────────────────────────────
#  数据库配置
# ────────────────────────────────────────────────────────────────

# SQLite 数据库文件路径
DB_PATH = os.path.join(os.path.dirname(__file__), "gmail-unsubscriber.db")
```

- [ ] **Step 4: 精简 SUSPICIOUS_SENDER_KEYWORDS — 移除过宽泛的词**

将 `config.py` 中的 `SUSPICIOUS_SENDER_KEYWORDS` 列表替换为：

```python
SUSPICIOUS_SENDER_KEYWORDS = [
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "newsletter", "promo", "promotion", "marketing",
    "offers", "deals", "sales", "shop", "store",
    "广告", "推广", "营销", "促销", "优惠",
]
```

（移除了 `"info"`, `"hello"`, `"hi"`, `"contact"`, `"team"`, `"notification"`, `"alert"`, `"updates"`, `"digest"`, `"通知"`——这些词太常见会误伤正经邮件。）

- [ ] **Step 5: 创建 tests/__init__.py**

创建空文件 `tests/__init__.py`（内容为空即可，让 pytest 识别为包）。

- [ ] **Step 6: 确认 .gitignore 包含新文件**

检查 `.gitignore`，确保包含以下行（如没有则追加）：
```
gmail-unsubscriber.db
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt config.py tests/__init__.py .gitignore
git commit -m "chore: add anthropic dep, AI/DB config, refine suspicious keywords"
```

---

## Task 2: 新建 database.py 和测试

**Files:**
- Create: `database.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_database.py`：

```python
# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import pytest

# 让测试能找到项目根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """每个测试使用独立的临时数据库文件。"""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setenv("TEST_DB_PATH", db_file)
    import config
    monkeypatch.setattr(config, "DB_PATH", db_file)
    import database
    importlib.reload(database)
    database.init_db()
    return db_file


import importlib


def test_init_db_creates_tables(tmp_db):
    import sqlite3
    conn = sqlite3.connect(tmp_db)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "unsubscribed_senders" in tables
    assert "scan_history" in tables
    assert "user_whitelist" in tables


def test_record_unsubscribe_and_check(tmp_db):
    import database
    database.record_unsubscribe("spam@example.com", "Spam Co", "one_click", True)
    assert database.is_already_unsubscribed("spam@example.com") is True


def test_is_already_unsubscribed_false_for_unknown(tmp_db):
    import database
    assert database.is_already_unsubscribed("unknown@example.com") is False


def test_failed_unsubscribe_not_counted_as_done(tmp_db):
    import database
    database.record_unsubscribe("fail@example.com", "Fail Co", "link_click", False)
    assert database.is_already_unsubscribed("fail@example.com") is False


def test_get_history_returns_records(tmp_db):
    import database
    database.record_unsubscribe("a@x.com", "A", "one_click", True)
    database.record_unsubscribe("b@x.com", "B", "mailto", True)
    history = database.get_history(limit=10)
    assert len(history) == 2
    emails = {r["sender_email"] for r in history}
    assert "a@x.com" in emails
    assert "b@x.com" in emails


def test_record_scan(tmp_db):
    import database
    database.record_scan(days=30, total_emails=500, candidates=15, unsubscribed=10)
    import sqlite3
    conn = sqlite3.connect(tmp_db)
    row = conn.execute("SELECT * FROM scan_history").fetchone()
    conn.close()
    assert row is not None


def test_add_to_whitelist_and_get(tmp_db):
    import database
    result = database.add_to_user_whitelist("mybank.com")
    assert result is True
    domains = database.get_user_whitelist()
    assert "mybank.com" in domains


def test_add_to_whitelist_duplicate_returns_false(tmp_db):
    import database
    database.add_to_user_whitelist("mybank.com")
    result = database.add_to_user_whitelist("mybank.com")
    assert result is False
```

- [ ] **Step 2: 运行测试确认全部失败**

```bash
cd /Users/bossoffice/gmail-unsubscriber
source venv/bin/activate
python -m pytest tests/test_database.py -v
```

预期：`ImportError: No module named 'database'`（模块还不存在）

- [ ] **Step 3: 创建 database.py**

```python
# -*- coding: utf-8 -*-
"""
数据库模块 - SQLite 状态管理
管理三张表：退订历史、扫描记录、用户白名单
"""

import sqlite3
import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化数据库，创建所需的三张表（如已存在则跳过）。"""
    conn = _get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS unsubscribed_senders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_email    TEXT NOT NULL UNIQUE,
            sender_name     TEXT,
            unsubscribed_at TEXT NOT NULL,
            method          TEXT,
            success         INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS scan_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at      TEXT NOT NULL,
            days            INTEGER,
            total_emails    INTEGER,
            candidates      INTEGER,
            unsubscribed    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS user_whitelist (
            domain          TEXT PRIMARY KEY,
            added_at        TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    logger.debug("数据库初始化完成")


def record_unsubscribe(sender_email: str, sender_name: str, method: str, success: bool) -> None:
    """记录退订操作（成功或失败）。已存在的记录会被覆盖更新。"""
    conn = _get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO unsubscribed_senders
            (sender_email, sender_name, unsubscribed_at, method, success)
        VALUES (?, ?, ?, ?, ?)
        """,
        (sender_email, sender_name, datetime.now().isoformat(), method, int(success)),
    )
    conn.commit()
    conn.close()
    logger.debug(f"退订记录已保存：{sender_email}（{'成功' if success else '失败'}）")


def is_already_unsubscribed(sender_email: str) -> bool:
    """检查该发件人是否已成功退订过（只有 success=1 才算）。"""
    conn = _get_connection()
    row = conn.execute(
        "SELECT id FROM unsubscribed_senders WHERE sender_email = ? AND success = 1",
        (sender_email,),
    ).fetchone()
    conn.close()
    return row is not None


def get_history(limit: int = 50) -> list[dict]:
    """返回退订历史记录，按时间倒序。"""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM unsubscribed_senders ORDER BY unsubscribed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_scan(days: int, total_emails: int, candidates: int, unsubscribed: int) -> None:
    """记录一次扫描操作的统计数据。"""
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO scan_history (scanned_at, days, total_emails, candidates, unsubscribed)
        VALUES (?, ?, ?, ?, ?)
        """,
        (datetime.now().isoformat(), days, total_emails, candidates, unsubscribed),
    )
    conn.commit()
    conn.close()


def add_to_user_whitelist(domain: str) -> bool:
    """
    将域名加入用户白名单。
    返回 True 表示新增成功，False 表示已存在。
    """
    domain = domain.lower().strip()
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO user_whitelist (domain, added_at) VALUES (?, ?)",
            (domain, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        logger.info(f"白名单新增：{domain}")
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_user_whitelist() -> list[str]:
    """返回用户自定义白名单域名列表。"""
    conn = _get_connection()
    rows = conn.execute("SELECT domain FROM user_whitelist").fetchall()
    conn.close()
    return [r["domain"] for r in rows]
```

- [ ] **Step 4: 运行测试确认全部通过**

```bash
python -m pytest tests/test_database.py -v
```

预期：所有测试 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: add database.py with SQLite history, scan records, whitelist"
```

---

## Task 3: 新建 ai_classifier.py 和测试

**Files:**
- Create: `ai_classifier.py`
- Create: `tests/test_ai_classifier.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_ai_classifier.py`：

```python
# -*- coding: utf-8 -*-
import os
import sys
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_ai_response(is_ad: bool, reason: str) -> MagicMock:
    """构造模拟的 Anthropic API 响应对象。"""
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
```

- [ ] **Step 2: 运行测试确认全部失败**

```bash
python -m pytest tests/test_ai_classifier.py -v
```

预期：`ImportError: No module named 'ai_classifier'`

- [ ] **Step 3: 创建 ai_classifier.py**

```python
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
        return False, "未配置 ANTHROPIC_API_KEY，跳过 AI 分类"

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
```

- [ ] **Step 4: 运行测试确认全部通过**

```bash
python -m pytest tests/test_ai_classifier.py -v
```

预期：所有测试 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ai_classifier.py tests/test_ai_classifier.py
git commit -m "feat: add ai_classifier.py with Claude AI toggle and error handling"
```

---

## Task 4: 升级 scanner.py（批量 API + 已退订过滤）

**Files:**
- Modify: `scanner.py`
- Create: `tests/test_scanner.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_scanner.py`：

```python
# -*- coding: utf-8 -*-
import os
import sys
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scanner


def _make_msg(msg_id, sender_email, subject="Test", labels=None):
    """构造模拟的 Gmail API 邮件对象。"""
    return {
        "id": msg_id,
        "threadId": f"thread-{msg_id}",
        "snippet": "test snippet",
        "labelIds": labels or [],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": f"Sender <{sender_email}>"},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Thu, 10 Apr 2026 10:00:00 +0800"},
            ],
            "body": {"data": ""},
            "parts": [],
        },
    }


def test_filter_already_unsubscribed(monkeypatch, tmp_path):
    """已退订的发件人不应出现在扫描结果中。"""
    import config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    import importlib
    import database
    importlib.reload(database)
    database.init_db()
    database.record_unsubscribe("spam@old.com", "Old Spam", "one_click", True)

    msg1 = _make_msg("id1", "spam@old.com", "广告")
    msg2 = _make_msg("id2", "legit@work.com", "Meeting")

    mock_service = MagicMock()

    with patch.object(scanner, "_list_all_messages", return_value=[{"id": "id1"}, {"id": "id2"}]), \
         patch.object(scanner, "_fetch_messages_batch", return_value=[msg1, msg2]):
        results = scanner.scan_emails(mock_service, days=30)

    sender_emails = [r["sender_email"] for r in results]
    assert "spam@old.com" not in sender_emails
    assert "legit@work.com" in sender_emails


def test_parse_sender_extracts_email():
    email_addr, domain = scanner._parse_sender("Google <no-reply@google.com>")
    assert email_addr == "no-reply@google.com"
    assert domain == "google.com"


def test_parse_sender_bare_email():
    email_addr, domain = scanner._parse_sender("spam@example.com")
    assert email_addr == "spam@example.com"
    assert domain == "example.com"


def test_fetch_messages_batch_returns_list():
    """_fetch_messages_batch 应返回解析后的邮件列表。"""
    msg = _make_msg("abc", "test@example.com")
    mock_service = MagicMock()

    captured_callback = {}

    def fake_batch_http_request(callback):
        captured_callback["fn"] = callback
        batch = MagicMock()

        def fake_execute():
            # 模拟 batch 回调：request_id="0", response=msg, exception=None
            captured_callback["fn"]("0", msg, None)

        batch.execute = fake_execute
        batch.add = MagicMock()
        batch._requests = {"0": True}
        return batch

    mock_service.new_batch_http_request.side_effect = fake_batch_http_request

    results = scanner._fetch_messages_batch(mock_service, [{"id": "abc"}])
    assert len(results) == 1
    assert results[0]["sender_email"] == "test@example.com"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_scanner.py -v
```

预期：部分测试失败（`_fetch_messages_batch` 函数不存在）

- [ ] **Step 3: 重写 scanner.py**

```python
# -*- coding: utf-8 -*-
"""
邮件扫描模块 - 从 Gmail 获取邮件列表及详情
使用 Gmail 批量 API 提升性能，并过滤已退订的发件人。
"""

import base64
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from googleapiclient.errors import HttpError

import database

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 100
MAX_RETRIES = 3
RETRY_DELAY = 2


def _retry_request(func, *args, **kwargs):
    """带重试机制的 API 请求包装器。"""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            if e.resp.status in (429, 500, 503):
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(f"API 请求失败（{e.resp.status}），{wait}s 后重试...")
                time.sleep(wait)
                last_error = e
            else:
                raise
    raise last_error


def scan_emails(service, days: int = 30, scan_all: bool = False) -> list[dict]:
    """
    扫描最近 N 天内收到的邮件，返回邮件详情列表。
    默认优先扫描 CATEGORY_PROMOTIONS 标签；--all 时扫描全部邮件。
    已退订的发件人自动过滤。

    Args:
        service:   Gmail API 服务对象
        days:      向前扫描的天数
        scan_all:  True 时扫描全部邮件，False 时仅扫描促销标签

    Returns:
        list[dict]: 邮件详情列表
    """
    since_date = datetime.now() - timedelta(days=days)
    after_timestamp = int(since_date.timestamp())

    if scan_all:
        query = f"after:{after_timestamp}"
        label_desc = "全部邮件"
    else:
        query = f"after:{after_timestamp} category:promotions"
        label_desc = "促销邮件"

    logger.info(f"扫描最近 {days} 天的{label_desc}")
    print(f"\n📬 正在扫描最近 {days} 天的{label_desc}...")

    message_stubs = _list_all_messages(service, query)
    total = len(message_stubs)
    logger.info(f"共找到 {total} 封邮件，开始批量解析...")
    print(f"   共找到 {total} 封邮件，正在批量解析详情...\n")

    if total == 0:
        return []

    emails = _fetch_messages_batch(service, message_stubs)

    # 过滤已退订的发件人
    already_done = set()
    filtered = []
    for em in emails:
        sender_email = em.get("sender_email", "")
        if database.is_already_unsubscribed(sender_email):
            if sender_email not in already_done:
                already_done.add(sender_email)
                logger.debug(f"跳过已退订发件人：{sender_email}")
        else:
            filtered.append(em)

    if already_done:
        print(f"   ⏭️  跳过 {len(already_done)} 个已退订的发件人\n")

    print(f"✅ 扫描完成，共解析 {len(emails)} 封邮件，过滤后剩余 {len(filtered)} 封\n")
    logger.info(f"扫描完成：{len(emails)} 封邮件，过滤 {len(already_done)} 个已退订发件人")
    return filtered


def _fetch_messages_batch(service, message_stubs: list[dict]) -> list[dict]:
    """
    使用 Gmail 批量 API 获取邮件详情。
    每批最多 100 封，比逐封请求快约 10 倍。

    Args:
        service:       Gmail API 服务对象
        message_stubs: 包含 id 字段的邮件存根列表

    Returns:
        list[dict]: 解析后的邮件详情列表
    """
    results = []

    def callback(request_id, response, exception):
        if exception is not None:
            logger.warning(f"批量请求失败（request_id={request_id}）：{exception}")
            return
        try:
            parsed = _parse_message(response)
            if parsed:
                results.append(parsed)
        except Exception as e:
            logger.warning(f"邮件解析失败：{e}")

    # 分批处理，每批最多 MAX_BATCH_SIZE 封
    for batch_start in range(0, len(message_stubs), MAX_BATCH_SIZE):
        batch_stubs = message_stubs[batch_start:batch_start + MAX_BATCH_SIZE]
        batch = service.new_batch_http_request(callback=callback)

        for stub in batch_stubs:
            batch.add(
                service.users().messages().get(
                    userId="me",
                    id=stub["id"],
                    format="full",
                )
            )

        try:
            batch.execute()
        except Exception as e:
            logger.error(f"批量请求执行失败：{e}")

    return results


def _list_all_messages(service, query: str) -> list[dict]:
    """分页获取所有符合查询条件的邮件存根。"""
    messages = []
    page_token = None

    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            response = _retry_request(
                service.users().messages().list(**kwargs).execute
            )
        except HttpError as e:
            logger.error(f"获取邮件列表失败：{e}")
            break

        messages.extend(response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return messages


def _parse_message(msg: dict) -> Optional[dict]:
    """将 Gmail API 返回的原始邮件对象解析为结构化字典。"""
    try:
        payload = msg.get("payload", {})
        headers = {
            h["name"].lower(): h["value"]
            for h in payload.get("headers", [])
        }
        sender_raw = headers.get("from", "")
        sender_email, sender_domain = _parse_sender(sender_raw)
        body_text, body_html = _extract_body(payload)

        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "subject": headers.get("subject", "（无主题）"),
            "sender": sender_raw,
            "sender_email": sender_email,
            "sender_domain": sender_domain,
            "date": headers.get("date", ""),
            "list_unsubscribe": headers.get("list-unsubscribe"),
            "list_unsubscribe_post": headers.get("list-unsubscribe-post"),
            "snippet": msg.get("snippet", ""),
            "body_text": body_text,
            "body_html": body_html,
            "labels": msg.get("labelIds", []),
            "_headers": headers,
        }
    except Exception as e:
        logger.warning(f"解析邮件失败：{e}")
        return None


def _parse_sender(sender_raw: str) -> tuple[str, str]:
    """从发件人字段提取邮箱地址和域名。"""
    if "<" in sender_raw and ">" in sender_raw:
        start = sender_raw.index("<") + 1
        end = sender_raw.index(">")
        email_addr = sender_raw[start:end].strip().lower()
    else:
        email_addr = sender_raw.strip().lower()

    domain = email_addr.split("@")[-1] if "@" in email_addr else ""
    return email_addr, domain


def _extract_body(payload: dict) -> tuple[str, str]:
    """递归提取邮件正文（纯文本和 HTML）。"""
    body_text, body_html = "", ""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        body_text = _decode_base64(body_data)
    elif mime_type == "text/html" and body_data:
        body_html = _decode_base64(body_data)
    elif "parts" in payload:
        for part in payload["parts"]:
            pt, ph = _extract_body(part)
            if pt and not body_text:
                body_text = pt
            if ph and not body_html:
                body_html = ph

    return body_text, body_html


def _decode_base64(data: str) -> str:
    """解码 Gmail API 使用的 URL-safe Base64 编码。"""
    try:
        import base64
        padded = data + "=" * (4 - len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug(f"Base64 解码失败：{e}")
        return ""
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_scanner.py -v
```

预期：所有测试 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add scanner.py tests/test_scanner.py
git commit -m "feat: upgrade scanner.py with batch API and already-unsubscribed filter"
```

---

## Task 5: 升级 classifier.py（AI 集成 + message_ids 追踪）

**Files:**
- Modify: `classifier.py`
- Create: `tests/test_classifier.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_classifier.py`：

```python
# -*- coding: utf-8 -*-
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import classifier


def _make_email(sender_email, subject, labels=None, list_unsub=None, snippet=""):
    return {
        "id": "test-id-001",
        "sender": f"Sender <{sender_email}>",
        "sender_email": sender_email,
        "sender_domain": sender_email.split("@")[-1],
        "subject": subject,
        "snippet": snippet,
        "body_text": "",
        "body_html": "",
        "labels": labels or [],
        "list_unsubscribe": list_unsub,
        "list_unsubscribe_post": None,
        "sample_html": "",
    }


def test_whitelisted_sender_not_unsubscribed():
    em = _make_email("no-reply@google.com", "Google 通知", ["CATEGORY_PROMOTIONS"])
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is False
    assert "白名单" in reason


def test_sensitive_keyword_not_unsubscribed():
    em = _make_email("alerts@bank.unknown.com", "您的验证码是 123456")
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is False
    assert "敏感" in reason


def test_two_conditions_marked_as_ad():
    em = _make_email(
        "promo@shop.example.com",
        "限时折扣！",
        labels=["CATEGORY_PROMOTIONS"],
        list_unsub="<https://example.com/unsub>",
    )
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is True


def test_one_condition_triggers_ai_when_enabled():
    em = _make_email(
        "newsletter@example.com",
        "Weekly Update",
        list_unsub="<https://example.com/unsub>",
    )
    with patch("classifier.ai_classifier.classify_with_ai", return_value=(True, "AI判定为广告")):
        result, reason = classifier.should_unsubscribe(em, use_ai=True)
    assert result is True
    assert "AI" in reason


def test_one_condition_no_ai_not_unsubscribed():
    em = _make_email(
        "newsletter@example.com",
        "Weekly Update",
        list_unsub="<https://example.com/unsub>",
    )
    result, reason = classifier.should_unsubscribe(em, use_ai=False)
    assert result is False


def test_classify_emails_tracks_message_ids():
    emails = [
        _make_email("spam@ads.com", "大促销", ["CATEGORY_PROMOTIONS"],
                    list_unsub="<https://ads.com/unsub>"),
        _make_email("spam@ads.com", "再促销", ["CATEGORY_PROMOTIONS"],
                    list_unsub="<https://ads.com/unsub>"),
    ]
    emails[0]["id"] = "id-001"
    emails[1]["id"] = "id-002"

    result = classifier.classify_emails(emails, use_ai=False)
    groups = result["to_unsubscribe"]
    assert len(groups) == 1
    assert set(groups[0]["message_ids"]) == {"id-001", "id-002"}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_classifier.py -v
```

预期：部分失败（`should_unsubscribe` 缺少 `use_ai` 参数，`classify_emails` 缺少 `message_ids`）

- [ ] **Step 3: 重写 classifier.py**

```python
# -*- coding: utf-8 -*-
"""
分类模块 - 判断邮件是否应该退订
采用「白名单优先 + 多条件叠加 + 可选 AI 二次确认」策略。

判断逻辑（按优先级）：
1. 白名单命中 → 绝对不退订
2. 含敏感关键词 → 绝对不退订
3. 关键词条件 2+ → 标记退订
4. 关键词条件恰好 1 → 交给 Claude AI 判断（可关闭）
5. 默认 → 不退订
"""

import logging
import re

import ai_classifier
import config

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
#  白名单检查
# ────────────────────────────────────────────────────────────────

def is_whitelisted(sender: str) -> bool:
    """检查发件人是否在白名单中（内置 + 用户自定义）。"""
    if not sender:
        return False

    domain = sender.split("@")[-1].lower().strip() if "@" in sender else sender.lower().strip()
    domain = re.sub(r"[<>\s]", "", domain)

    all_whitelist = config.get_all_whitelist_domains()

    for white_domain in all_whitelist:
        white_domain = white_domain.lower().strip()
        if domain == white_domain:
            return True
        if domain.endswith("." + white_domain):
            return True
        if "." not in white_domain and domain.endswith("." + white_domain):
            return True

    return False


# ────────────────────────────────────────────────────────────────
#  敏感内容检查
# ────────────────────────────────────────────────────────────────

def is_sensitive(email_data: dict) -> bool:
    """检查邮件是否包含敏感关键词。含敏感词则绝对不退订。"""
    check_text = " ".join([
        email_data.get("subject", ""),
        email_data.get("snippet", ""),
        email_data.get("body_text", "") or "",
    ]).lower()

    for keyword in config.SENSITIVE_KEYWORDS:
        if keyword.lower() in check_text:
            logger.debug(f"检测到敏感关键词：「{keyword}」")
            return True
    return False


# ────────────────────────────────────────────────────────────────
#  广告内容检查
# ────────────────────────────────────────────────────────────────

def is_advertisement(email_data: dict) -> tuple[bool, list[str]]:
    """
    检查邮件是否满足广告特征条件。
    返回 (是否判定为广告, 命中的条件列表)。
    需满足 2+ 条件才判定为广告。
    """
    matched_conditions = []

    subject = email_data.get("subject", "").lower()
    snippet = email_data.get("snippet", "").lower()
    body_text = (email_data.get("body_text", "") or "").lower()
    sender = email_data.get("sender", "").lower()
    sender_email = email_data.get("sender_email", "").lower()
    labels = email_data.get("labels", [])
    list_unsub = email_data.get("list_unsubscribe")

    check_text = f"{subject} {snippet} {body_text}"

    # 条件 1：含广告关键词
    matched_ad_kw = [kw for kw in config.AD_KEYWORDS if kw.lower() in check_text]
    if matched_ad_kw:
        matched_conditions.append(
            f"含广告关键词：{', '.join(matched_ad_kw[:3])}"
            + ("..." if len(matched_ad_kw) > 3 else "")
        )

    # 条件 2：发件人含可疑关键词
    sender_check = f"{sender} {sender_email}"
    matched_sender_kw = [kw for kw in config.SUSPICIOUS_SENDER_KEYWORDS if kw.lower() in sender_check]
    if matched_sender_kw:
        matched_conditions.append(f"发件人含可疑关键词：{', '.join(matched_sender_kw[:2])}")

    # 条件 3：含 List-Unsubscribe 头部
    if list_unsub:
        matched_conditions.append("含 List-Unsubscribe 头部")

    # 条件 4：Gmail 自动归类为促销
    if "CATEGORY_PROMOTIONS" in labels:
        matched_conditions.append("Gmail 自动归类为促销邮件")

    # 条件 5：noreply 地址
    local_part = sender_email.split("@")[0] if "@" in sender_email else sender_email
    if re.match(r"^(noreply|no.reply|donotreply|do.not.reply)$", local_part, re.I):
        matched_conditions.append("发件人为 noreply 地址")

    is_ad = len(matched_conditions) >= 2
    return is_ad, matched_conditions


# ────────────────────────────────────────────────────────────────
#  最终决策
# ────────────────────────────────────────────────────────────────

def should_unsubscribe(email_data: dict, use_ai: bool = True) -> tuple[bool, str]:
    """
    综合所有规则，给出是否应该退订的最终判断。

    Args:
        email_data: 邮件详情字典
        use_ai:     是否允许调用 Claude AI（False 时跳过 AI 判断）

    Returns:
        tuple[bool, str]: (是否建议退订, 判断理由)
    """
    sender_email = email_data.get("sender_email", "")

    # 第一道防线：白名单
    if is_whitelisted(sender_email):
        return False, f"发件人域名在白名单中（{email_data.get('sender_domain', '')}）"

    # 第二道防线：敏感内容
    if is_sensitive(email_data):
        return False, "邮件含敏感关键词（验证码/订单/账单等），已跳过"

    # 广告特征判断
    is_ad, conditions = is_advertisement(email_data)

    if is_ad:
        return True, "命中广告特征：" + "；".join(conditions)

    # 恰好命中 1 个条件 → 交给 AI 判断
    if len(conditions) == 1 and use_ai:
        ai_result, ai_reason = ai_classifier.classify_with_ai(
            sender=email_data.get("sender", ""),
            subject=email_data.get("subject", ""),
            snippet=email_data.get("snippet", ""),
        )
        if ai_result:
            return True, f"AI 判定为广告：{ai_reason}（辅助条件：{conditions[0]}）"

    return False, "未达到广告判定标准，跳过"


# ────────────────────────────────────────────────────────────────
#  批量分类
# ────────────────────────────────────────────────────────────────

def classify_emails(emails: list[dict], use_ai: bool = True) -> dict:
    """
    对邮件列表进行批量分类，按发件人归组。

    Args:
        emails:  邮件详情列表
        use_ai:  是否允许 AI 辅助判断

    Returns:
        dict: {
            "to_unsubscribe": 建议退订的发件人列表,
            "skipped": 跳过的邮件数量
        }
    """
    sender_groups: dict[str, dict] = {}

    for em in emails:
        sender_email = em.get("sender_email", "unknown")
        decision, reason = should_unsubscribe(em, use_ai=use_ai)

        if not decision:
            continue

        if sender_email not in sender_groups:
            sender_groups[sender_email] = {
                "sender_email": sender_email,
                "sender": em.get("sender", sender_email),
                "sender_domain": em.get("sender_domain", ""),
                "count": 0,
                "reasons": set(),
                "sample_subjects": [],
                "message_ids": [],          # 新增：所有该发件人的邮件 ID
                "list_unsubscribe": em.get("list_unsubscribe"),
                "list_unsubscribe_post": em.get("list_unsubscribe_post"),
                "sample_html": em.get("body_html", ""),
                "sample_id": em.get("id", ""),
            }

        group = sender_groups[sender_email]
        group["count"] += 1
        group["reasons"].add(reason)
        group["message_ids"].append(em.get("id", ""))  # 新增

        if len(group["sample_subjects"]) < 3:
            group["sample_subjects"].append(em.get("subject", ""))

        # 优先用有 list_unsubscribe 的邮件作为样本
        if em.get("list_unsubscribe") and not group.get("list_unsubscribe"):
            group["list_unsubscribe"] = em["list_unsubscribe"]
            group["list_unsubscribe_post"] = em.get("list_unsubscribe_post")
            group["sample_html"] = em.get("body_html", "")
            group["sample_id"] = em.get("id", "")

    result = sorted(
        [{**g, "reasons": list(g["reasons"])} for g in sender_groups.values()],
        key=lambda x: x["count"],
        reverse=True,
    )

    skipped = len(emails) - sum(g["count"] for g in result)
    return {"to_unsubscribe": result, "skipped": skipped}
```

- [ ] **Step 4: 更新 config.py 中的 get_all_whitelist_domains 以支持 SQLite 白名单**

在 `config.py` 中，将 `get_all_whitelist_domains` 函数替换为以下内容（同时保留 JSON 迁移兼容性）：

```python
def get_all_whitelist_domains() -> list[str]:
    """返回内置白名单 + 用户自定义白名单（从 SQLite 读取）的合集。"""
    try:
        import database
        user_domains = database.get_user_whitelist()
    except Exception:
        # 数据库未初始化时回退到 JSON 文件
        user_domains = load_user_whitelist()
    return list(set(WHITELIST_DOMAINS + user_domains))
```

- [ ] **Step 5: 运行测试确认通过**

```bash
python -m pytest tests/test_classifier.py -v
```

预期：所有测试 `PASSED`

- [ ] **Step 6: Commit**

```bash
git add classifier.py config.py tests/test_classifier.py
git commit -m "feat: upgrade classifier.py with AI fallback and message_ids tracking"
```

---

## Task 6: 升级 unsubscriber.py（修复 mailto + 标签 + 归档）

**Files:**
- Modify: `unsubscriber.py`
- Create: `tests/test_unsubscriber.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_unsubscriber.py`：

```python
# -*- coding: utf-8 -*-
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unsubscriber


def test_unsubscribe_via_one_click_success():
    with patch("unsubscriber.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        result = unsubscriber.unsubscribe_via_one_click("https://example.com/unsub")
    assert result["success"] is True
    assert result["method"] == "one_click_post"


def test_unsubscribe_via_one_click_failure():
    with patch("unsubscriber.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=404)
        result = unsubscriber.unsubscribe_via_one_click("https://example.com/unsub")
    assert result["success"] is False


def test_unsubscribe_via_mailto_sends_email():
    mock_service = MagicMock()
    mock_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "sent-id"}

    mailto_info = {"mailto_email": "unsub@example.com", "mailto_subject": "unsubscribe"}
    result = unsubscriber.unsubscribe_via_mailto(mailto_info, service=mock_service)

    assert result["success"] is True
    assert result["method"] == "mailto"
    mock_service.users.return_value.messages.return_value.send.assert_called_once()


def test_unsubscribe_via_mailto_no_service():
    mailto_info = {"mailto_email": "unsub@example.com", "mailto_subject": "unsubscribe"}
    result = unsubscriber.unsubscribe_via_mailto(mailto_info, service=None)
    assert result["success"] is False
    assert "service" in result["message"]


def test_unsubscribe_via_mailto_no_email():
    result = unsubscriber.unsubscribe_via_mailto({"mailto_email": ""}, service=MagicMock())
    assert result["success"] is False


def test_create_or_get_label_existing():
    mock_service = MagicMock()
    mock_service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"id": "Label_123", "name": "已退订"}]
    }
    label_id = unsubscriber.create_or_get_label(mock_service, "已退订")
    assert label_id == "Label_123"
    # 不应调用 create
    mock_service.users.return_value.labels.return_value.create.assert_not_called()


def test_create_or_get_label_creates_new():
    mock_service = MagicMock()
    mock_service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": []
    }
    mock_service.users.return_value.labels.return_value.create.return_value.execute.return_value = {
        "id": "Label_new", "name": "已退订"
    }
    label_id = unsubscriber.create_or_get_label(mock_service, "已退订")
    assert label_id == "Label_new"


def test_label_sender_emails_calls_modify():
    mock_service = MagicMock()
    unsubscriber.label_sender_emails(mock_service, ["id1", "id2"], "Label_123")
    assert mock_service.users.return_value.messages.return_value.modify.call_count == 2


def test_archive_sender_emails_removes_inbox():
    mock_service = MagicMock()
    unsubscriber.archive_sender_emails(mock_service, ["id1", "id2"])
    calls = mock_service.users.return_value.messages.return_value.modify.call_args_list
    assert len(calls) == 2
    for c in calls:
        body = c[1].get("body", c[0][0] if c[0] else {})
        # 验证 removeLabelIds 包含 INBOX（通过 kwargs 或 args）
        call_kwargs = c.kwargs if hasattr(c, 'kwargs') else c[1]
        assert "INBOX" in str(c)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_unsubscriber.py -v
```

预期：新增的函数（`create_or_get_label`, `label_sender_emails`, `archive_sender_emails`）不存在

- [ ] **Step 3: 重写 unsubscriber.py**

```python
# -*- coding: utf-8 -*-
"""
退订执行模块 - 通过多种方式实际执行退订操作
支持三种退订方式（按优先级）：
1. List-Unsubscribe-Post（RFC 8058 一键退订，最标准）
2. List-Unsubscribe mailto（通过 Gmail API 实际发送退订邮件）
3. 从邮件正文中提取退订链接（点击链接退订）

退订成功后支持：
- 给该发件人所有邮件打「已退订」标签
- 可选：归档（移出收件箱）该发件人的历史邮件
"""

import base64
import logging
import re
import time
import urllib.parse
from email.mime.text import MIMEText
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10
REQUEST_INTERVAL = 2

UNSUBSCRIBE_LINK_KEYWORDS = [
    "unsubscribe", "opt-out", "optout", "opt_out",
    "remove", "cancel", "退订", "取消订阅", "取消接收",
    "退出", "不再接收", "停止接收",
]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

UNSUBSCRIBE_LABEL_NAME = "已退订"


# ────────────────────────────────────────────────────────────────
#  解析 List-Unsubscribe 头部
# ────────────────────────────────────────────────────────────────

def get_list_unsubscribe_url(headers_or_value) -> dict:
    """解析 List-Unsubscribe 头部，提取 HTTP URL 和 mailto 地址。"""
    raw_value = (
        headers_or_value.get("list-unsubscribe", "")
        if isinstance(headers_or_value, dict)
        else (headers_or_value or "")
    )

    result = {
        "http_url": None,
        "mailto": None,
        "mailto_email": None,
        "mailto_subject": None,
    }

    for entry in re.findall(r"<([^>]+)>", raw_value):
        entry = entry.strip()
        if (entry.startswith("https://") or entry.startswith("http://")) and not result["http_url"]:
            result["http_url"] = entry
        elif entry.startswith("mailto:") and not result["mailto"]:
            result["mailto"] = entry
            parsed = _parse_mailto(entry)
            result["mailto_email"] = parsed["email"]
            result["mailto_subject"] = parsed["subject"]

    return result


def _parse_mailto(mailto_str: str) -> dict:
    """解析 mailto: 字符串，提取邮箱和 subject 参数。"""
    rest = mailto_str[7:] if mailto_str.startswith("mailto:") else mailto_str
    if "?" in rest:
        email_part, params_str = rest.split("?", 1)
        params = urllib.parse.parse_qs(params_str)
        subject = params.get("subject", [None])[0]
    else:
        email_part, subject = rest, None
    return {"email": email_part.strip(), "subject": subject}


# ────────────────────────────────────────────────────────────────
#  退订方式 1：一键退订（RFC 8058 POST）
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_one_click(url: str) -> dict:
    """向 URL 发送 POST 请求，执行 RFC 8058 一键退订。"""
    logger.info(f"尝试一键退订（POST）：{url}")
    try:
        response = requests.post(
            url,
            data={"List-Unsubscribe": "One-Click"},
            headers={**DEFAULT_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )
        time.sleep(REQUEST_INTERVAL)
        success = response.status_code in (200, 201, 202, 204)
        return {
            "success": success,
            "method": "one_click_post",
            "message": f"一键退订{'成功' if success else '失败'}（HTTP {response.status_code}）",
            "status_code": response.status_code,
        }
    except requests.exceptions.Timeout:
        return {"success": False, "method": "one_click_post", "message": "请求超时", "status_code": None}
    except Exception as e:
        return {"success": False, "method": "one_click_post", "message": f"连接失败：{e}", "status_code": None}


# ────────────────────────────────────────────────────────────────
#  退订方式 2：发送退订邮件（通过 Gmail API）
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_mailto(mailto_info: dict, service=None) -> dict:
    """
    通过 Gmail API 实际发送退订邮件。
    需要传入 service 对象（由 auth.get_gmail_service() 提供）。
    """
    email_addr = mailto_info.get("mailto_email", "")
    subject = mailto_info.get("mailto_subject") or "unsubscribe"

    if not email_addr:
        return {"success": False, "method": "mailto", "message": "无法解析退订邮箱地址"}

    if service is None:
        return {"success": False, "method": "mailto",
                "message": "未提供 Gmail service，无法发送退订邮件"}

    try:
        raw = _build_email_raw(to_email=email_addr, subject=subject)
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        logger.info(f"退订邮件已通过 Gmail API 发送至：{email_addr}")
        return {
            "success": True,
            "method": "mailto",
            "message": f"退订邮件已发送至 {email_addr}（主题：{subject}）",
        }
    except Exception as e:
        logger.error(f"发送退订邮件失败：{e}")
        return {"success": False, "method": "mailto", "message": f"发送退订邮件失败：{e}"}


def _build_email_raw(to_email: str, subject: str) -> str:
    """构造退订邮件并转为 Gmail API 所需的 base64 格式。"""
    msg = MIMEText("Please unsubscribe me from your mailing list.\n\nThank you.")
    msg["to"] = to_email
    msg["subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


# ────────────────────────────────────────────────────────────────
#  退订方式 3：从邮件正文提取退订链接
# ────────────────────────────────────────────────────────────────

def unsubscribe_via_link(html_body: str) -> dict:
    """从邮件 HTML 正文中提取退订链接，发送 GET 请求。"""
    if not html_body:
        return {"success": False, "method": "link_click",
                "message": "邮件正文为空，无法提取退订链接", "found_url": None, "status_code": None}

    unsubscribe_url = _find_unsubscribe_link(html_body)
    if not unsubscribe_url:
        return {"success": False, "method": "link_click",
                "message": "未在邮件正文中找到退订链接", "found_url": None, "status_code": None}

    logger.info(f"找到退订链接：{unsubscribe_url[:80]}")
    try:
        response = requests.get(
            unsubscribe_url, headers=DEFAULT_HEADERS,
            timeout=HTTP_TIMEOUT, allow_redirects=True,
        )
        time.sleep(REQUEST_INTERVAL)
        success = response.status_code in (200, 201, 202, 204)
        return {
            "success": success,
            "method": "link_click",
            "message": f"退订链接已访问（HTTP {response.status_code}）",
            "found_url": unsubscribe_url,
            "status_code": response.status_code,
        }
    except Exception as e:
        return {"success": False, "method": "link_click",
                "message": f"访问退订链接失败：{e}", "found_url": unsubscribe_url, "status_code": None}


def _find_unsubscribe_link(html_body: str) -> Optional[str]:
    """从 HTML 中找到最可能是退订链接的 URL（优先取最后一个）。"""
    try:
        soup = BeautifulSoup(html_body, "lxml")
    except Exception:
        soup = BeautifulSoup(html_body, "html.parser")

    candidates = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        if not (href.startswith("http://") or href.startswith("https://")):
            continue
        text = a_tag.get_text(strip=True).lower()
        for kw in UNSUBSCRIBE_LINK_KEYWORDS:
            if kw in text or kw in href.lower():
                candidates.append(href)
                break

    return candidates[-1] if candidates else None


# ────────────────────────────────────────────────────────────────
#  Gmail 标签管理
# ────────────────────────────────────────────────────────────────

def create_or_get_label(service, label_name: str = UNSUBSCRIBE_LABEL_NAME) -> str:
    """
    在 Gmail 中获取或创建指定名称的标签，返回标签 ID。

    Args:
        service:    Gmail API 服务对象
        label_name: 标签名称，默认「已退订」

    Returns:
        str: 标签 ID
    """
    labels_resp = service.users().labels().list(userId="me").execute()
    for label in labels_resp.get("labels", []):
        if label["name"] == label_name:
            return label["id"]

    new_label = service.users().labels().create(
        userId="me",
        body={
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    logger.info(f"已创建 Gmail 标签：{label_name}（ID: {new_label['id']}）")
    return new_label["id"]


def label_sender_emails(service, message_ids: list[str], label_id: str) -> None:
    """给指定邮件列表打上标签。"""
    for msg_id in message_ids:
        try:
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [label_id]},
            ).execute()
        except Exception as e:
            logger.warning(f"给邮件 {msg_id} 打标签失败：{e}")
    logger.debug(f"已给 {len(message_ids)} 封邮件打上标签 {label_id}")


def archive_sender_emails(service, message_ids: list[str]) -> None:
    """将指定邮件从收件箱移到归档（移除 INBOX 标签）。"""
    for msg_id in message_ids:
        try:
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["INBOX"]},
            ).execute()
        except Exception as e:
            logger.warning(f"归档邮件 {msg_id} 失败：{e}")
    logger.debug(f"已归档 {len(message_ids)} 封邮件")


# ────────────────────────────────────────────────────────────────
#  统一退订入口
# ────────────────────────────────────────────────────────────────

def execute_unsubscribe(
    sender_group: dict,
    service=None,
    dry_run: bool = True,
    archive: bool = False,
) -> dict:
    """
    对一个发件人执行退订操作（统一入口）。

    Args:
        sender_group: classifier.classify_emails() 返回的发件人分组字典
        service:      Gmail API 服务对象（退订后打标签/归档需要）
        dry_run:      True 表示试运行（只分析，不实际执行）
        archive:      True 表示退订成功后同时归档该发件人的历史邮件

    Returns:
        dict: {
            "sender_email", "sender", "dry_run",
            "attempted_method", "success", "message", "details"
        }
    """
    sender_email = sender_group.get("sender_email", "unknown")
    sender = sender_group.get("sender", sender_email)
    list_unsub_raw = sender_group.get("list_unsubscribe")
    list_unsub_post = sender_group.get("list_unsubscribe_post", "")
    html_body = sender_group.get("sample_html", "")
    message_ids = sender_group.get("message_ids", [])

    result = {
        "sender_email": sender_email,
        "sender": sender,
        "dry_run": dry_run,
        "attempted_method": None,
        "success": False,
        "message": "",
        "details": {},
    }

    # ── 试运行模式 ──
    if dry_run:
        available_methods = []
        if list_unsub_raw:
            unsub_info = get_list_unsubscribe_url(list_unsub_raw)
            if unsub_info["http_url"]:
                has_post = list_unsub_post and "List-Unsubscribe=One-Click" in list_unsub_post
                method_name = "一键退订（POST）" if has_post else "HTTP 链接（GET）"
                available_methods.append(f"✓ {method_name}：{unsub_info['http_url'][:60]}...")
            if unsub_info["mailto_email"]:
                available_methods.append(f"✓ mailto 退订：{unsub_info['mailto_email']}")
        if html_body:
            link = _find_unsubscribe_link(html_body)
            if link:
                available_methods.append(f"✓ 正文退订链接：{link[:60]}...")

        result["success"] = bool(available_methods)
        result["message"] = "试运行：发现以下退订方式" if available_methods else "试运行：未找到可用退订方式"
        result["details"]["available_methods"] = available_methods
        return result

    # ── 实际执行 ──
    logger.info(f"开始退订：{sender_email}")

    # 方式 1 & 2：List-Unsubscribe
    if list_unsub_raw:
        unsub_info = get_list_unsubscribe_url(list_unsub_raw)

        if unsub_info["http_url"]:
            has_one_click = list_unsub_post and "List-Unsubscribe=One-Click" in list_unsub_post
            if has_one_click:
                attempt = unsubscribe_via_one_click(unsub_info["http_url"])
            else:
                try:
                    resp = requests.get(
                        unsub_info["http_url"], headers=DEFAULT_HEADERS,
                        timeout=HTTP_TIMEOUT, allow_redirects=True,
                    )
                    time.sleep(REQUEST_INTERVAL)
                    attempt = {
                        "success": resp.status_code in (200, 201, 202, 204),
                        "method": "http_get",
                        "message": f"HTTP GET（状态码 {resp.status_code}）",
                        "status_code": resp.status_code,
                    }
                except Exception as e:
                    attempt = {"success": False, "method": "http_get",
                               "message": f"HTTP GET 失败：{e}", "status_code": None}

            result["details"]["http"] = attempt
            if attempt["success"]:
                result.update({"attempted_method": attempt["method"],
                               "success": True, "message": attempt["message"]})
                _post_unsubscribe_actions(service, message_ids, archive)
                return result

        if unsub_info["mailto_email"]:
            attempt = unsubscribe_via_mailto(unsub_info, service=service)
            result["details"]["mailto"] = attempt
            if attempt["success"]:
                result.update({"attempted_method": "mailto",
                               "success": True, "message": attempt["message"]})
                _post_unsubscribe_actions(service, message_ids, archive)
                return result

    # 方式 3：正文链接
    if html_body:
        attempt = unsubscribe_via_link(html_body)
        result["details"]["link"] = attempt
        if attempt["success"]:
            result.update({"attempted_method": "link_click",
                           "success": True, "message": attempt["message"]})
            _post_unsubscribe_actions(service, message_ids, archive)
            return result

    result["message"] = "未找到可用的退订方式"
    logger.warning(f"退订失败：{sender_email}")
    return result


def _post_unsubscribe_actions(service, message_ids: list[str], archive: bool) -> None:
    """退订成功后：打标签 + 可选归档。"""
    if not service or not message_ids:
        return
    try:
        label_id = create_or_get_label(service)
        label_sender_emails(service, message_ids, label_id)
        logger.info(f"已给 {len(message_ids)} 封邮件打上「已退订」标签")
    except Exception as e:
        logger.warning(f"打标签失败（不影响退订结果）：{e}")

    if archive:
        try:
            archive_sender_emails(service, message_ids)
            logger.info(f"已归档 {len(message_ids)} 封邮件")
        except Exception as e:
            logger.warning(f"归档失败（不影响退订结果）：{e}")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_unsubscriber.py -v
```

预期：所有测试 `PASSED`

- [ ] **Step 5: Commit**

```bash
git add unsubscriber.py tests/test_unsubscriber.py
git commit -m "feat: upgrade unsubscriber.py with real mailto, Gmail labels and archive"
```

---

## Task 7: 升级 main.py（history 命令 + 新参数）

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 在 main.py 顶部添加 database 导入**

在 `import auth` 那组导入语句旁，追加：

```python
import database
```

- [ ] **Step 2: 在 main.py 的 main() 函数中，调用 database.init_db()**

找到 `main()` 函数中 `setup_logging(verbose=args.verbose)` 一行，在其后添加：

```python
    database.init_db()
```

- [ ] **Step 3: 修改 cmd_scan，传入 scan_all 和 use_ai 参数，并记录扫描结果**

将 `cmd_scan` 函数替换为：

```python
def cmd_scan(args: argparse.Namespace) -> None:
    """扫描邮件并展示分析结果（不执行退订）。"""
    print("=" * 60)
    print("  Gmail 广告邮件扫描器")
    print("=" * 60)

    service = auth.get_gmail_service()
    use_ai = not args.no_ai
    emails = scanner.scan_emails(service, days=args.days, scan_all=args.all)

    if not emails:
        print("📭 最近邮件为空或扫描结果为零。")
        return

    result = classifier.classify_emails(emails, use_ai=use_ai)
    to_unsub = result["to_unsubscribe"]
    skipped = result["skipped"]

    # 记录本次扫描
    database.record_scan(
        days=args.days,
        total_emails=len(emails),
        candidates=len(to_unsub),
        unsubscribed=0,
    )

    print(f"\n📊 扫描报告")
    print(f"   总邮件数：{len(emails)}")
    print(f"   建议退订发件人数：{len(to_unsub)}")
    print(f"   已跳过邮件数（白名单/敏感）：{skipped}")
    print()

    if not to_unsub:
        print("✅ 未发现需要退订的广告邮件。")
        return

    print("─" * 60)
    print("  建议退订的发件人列表：")
    print("─" * 60)

    for i, group in enumerate(to_unsub, 1):
        print(f"\n  [{i}] {group['sender']}")
        print(f"      邮箱：{group['sender_email']}")
        print(f"      邮件数量：{group['count']} 封")
        print(f"      判定依据：{group['reasons'][0] if group['reasons'] else '无'}")
        if group.get("sample_subjects"):
            print(f"      邮件主题示例：")
            for s in group["sample_subjects"][:3]:
                print(f"        · {s[:60]}{'...' if len(s) > 60 else ''}")
        has_unsub = "✓" if group.get("list_unsubscribe") else "✗"
        print(f"      支持 List-Unsubscribe：{has_unsub}")

    print()
    print("─" * 60)
    print(f"  运行 'python main.py unsubscribe --dry-run' 预览退订操作")
    print(f"  运行 'python main.py unsubscribe --confirm' 开始退订")
    print("─" * 60)

    logger.info(f"扫描完成：{len(to_unsub)} 个发件人建议退订，{skipped} 封邮件已跳过")
```

- [ ] **Step 4: 修改 cmd_unsubscribe，传入 service、use_ai、archive 参数，并记录退订结果**

将 `cmd_unsubscribe` 函数替换为：

```python
def cmd_unsubscribe(args: argparse.Namespace) -> None:
    """执行退订操作。"""
    dry_run = args.dry_run
    confirm_mode = args.confirm
    auto_mode = args.auto
    archive = getattr(args, "archive", False)
    use_ai = not getattr(args, "no_ai", False)

    if dry_run:
        print("=" * 60)
        print("  Gmail 退订工具 - 试运行模式（不会实际执行退订）")
        print("=" * 60)
    elif confirm_mode:
        mode_desc = "自动确认" if auto_mode else "逐个确认"
        print("=" * 60)
        print(f"  Gmail 退订工具 - {mode_desc}模式{'（退订后归档）' if archive else ''}")
        print("=" * 60)
        if not auto_mode:
            print("\n⚠️  注意：即将对以下发件人执行退订操作。")
            print("   退订后，对方将停止向您发送邮件。\n")

    days = getattr(args, "days", 30)
    scan_all = getattr(args, "all", False)
    service = auth.get_gmail_service()
    emails = scanner.scan_emails(service, days=days, scan_all=scan_all)

    if not emails:
        print("📭 未找到邮件。")
        return

    result = classifier.classify_emails(emails, use_ai=use_ai)
    to_unsub = result["to_unsubscribe"]

    if not to_unsub:
        print("✅ 未发现需要退订的广告邮件。")
        return

    print(f"\n📋 找到 {len(to_unsub)} 个建议退订的发件人\n")

    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, group in enumerate(to_unsub, 1):
        sender_email = group["sender_email"]
        sender_display = group.get("sender", sender_email)
        count = group["count"]

        print(f"[{i}/{len(to_unsub)}] {sender_display}")
        print(f"         邮箱：{sender_email}  |  邮件数：{count} 封")
        if group.get("reasons"):
            print(f"         原因：{group['reasons'][0]}")

        if confirm_mode and not auto_mode:
            user_skipped = False
            while True:
                answer = input(f"\n         退订这个发件人？[y/n/q（退出）] ").strip().lower()
                if answer in ("y", "yes", "是"):
                    break
                elif answer in ("n", "no", "否"):
                    print(f"         ⏭️  跳过 {sender_email}")
                    skip_count += 1
                    print()
                    user_skipped = True
                    break
                elif answer in ("q", "quit", "exit"):
                    print("\n用户退出，已停止退订。")
                    _print_summary(success_count, skip_count, fail_count)
                    return
                else:
                    print("         请输入 y（退订）、n（跳过）或 q（退出）")
            if user_skipped:
                continue

        exec_result = unsubscriber.execute_unsubscribe(
            group, service=service, dry_run=dry_run, archive=archive
        )

        if dry_run:
            methods = exec_result.get("details", {}).get("available_methods", [])
            if methods:
                print(f"         🔍 [试运行] 发现退订方式：")
                for m in methods:
                    print(f"              {m}")
            else:
                print(f"         ⚠️  [试运行] 未发现退订方式")
        elif exec_result["success"]:
            print(f"         ✅ 退订成功：{exec_result['message']}")
            success_count += 1
            database.record_unsubscribe(
                sender_email=sender_email,
                sender_name=sender_display,
                method=exec_result.get("attempted_method", "unknown"),
                success=True,
            )
        else:
            print(f"         ❌ 退订失败：{exec_result['message']}")
            fail_count += 1
            database.record_unsubscribe(
                sender_email=sender_email,
                sender_name=sender_display,
                method="failed",
                success=False,
            )

        print()

    if not dry_run:
        _print_summary(success_count, skip_count, fail_count)
        database.record_scan(
            days=days,
            total_emails=len(emails),
            candidates=len(to_unsub),
            unsubscribed=success_count,
        )

    logger.info(f"退订任务完成：成功={success_count}，跳过={skip_count}，失败={fail_count}")
```

- [ ] **Step 5: 添加 cmd_history 函数**

在 `cmd_whitelist` 函数之前，插入以下函数：

```python
def cmd_history(args: argparse.Namespace) -> None:
    """查看历史退订记录。"""
    limit = getattr(args, "limit", 50)
    history = database.get_history(limit=limit)

    if not history:
        print("📭 暂无退订历史记录。")
        print("   运行 'python main.py unsubscribe --confirm' 开始退订。")
        return

    print(f"\n📋 退订历史记录（共 {len(history)} 条，最近 {limit} 条）")
    print("─" * 60)

    method_labels = {
        "one_click_post": "一键退订（POST）",
        "http_get": "HTTP 链接退订",
        "mailto": "退订邮件发送",
        "link_click": "正文链接退订",
        "failed": "退订失败",
        "unknown": "未知方式",
    }

    for i, record in enumerate(history, 1):
        status = "✅" if record["success"] else "❌"
        method = method_labels.get(record.get("method", ""), record.get("method", ""))
        ts = record["unsubscribed_at"][:16].replace("T", " ")
        print(f"\n  [{i}] {record.get('sender_name', record['sender_email'])}")
        print(f"      邮箱：{record['sender_email']}")
        print(f"      时间：{ts}  方式：{method}  {status}")

    print()
    print("─" * 60)
```

- [ ] **Step 6: 更新 build_parser()，新增所有参数和 history 子命令**

将 `build_parser()` 函数替换为：

```python
def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="gmail-unsubscriber",
        description="Gmail 广告邮件自动退订工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  %(prog)s scan                              扫描最近 30 天促销邮件
  %(prog)s scan --days 60 --all             扫描最近 60 天全部邮件
  %(prog)s scan --no-ai                     不使用 AI 辅助判断
  %(prog)s unsubscribe --dry-run            预览将要退订的发件人
  %(prog)s unsubscribe --confirm            逐个确认执行退订
  %(prog)s unsubscribe --confirm --auto     自动退订所有建议发件人
  %(prog)s unsubscribe --confirm --archive  退订并归档旧邮件
  %(prog)s history                          查看退订历史
  %(prog)s whitelist add taobao.com         加入白名单
  %(prog)s whitelist list                   查看白名单
  %(prog)s logs                             查看运行日志
        """,
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细调试日志")

    subparsers = parser.add_subparsers(dest="command", metavar="命令")
    subparsers.required = True

    # ── scan ──
    scan_parser = subparsers.add_parser("scan", help="扫描邮件，分析广告发件人")
    scan_parser.add_argument("--days", "-d", type=int, default=30, metavar="N",
                             help="扫描最近 N 天的邮件（默认：30）")
    scan_parser.add_argument("--all", action="store_true",
                             help="扫描全部邮件（默认只扫促销标签）")
    scan_parser.add_argument("--no-ai", action="store_true", dest="no_ai",
                             help="不使用 Claude AI 辅助判断")
    scan_parser.set_defaults(func=cmd_scan)

    # ── unsubscribe ──
    unsub_parser = subparsers.add_parser("unsubscribe", help="执行退订操作")
    unsub_parser.add_argument("--days", "-d", type=int, default=30, metavar="N",
                              help="扫描最近 N 天的邮件（默认：30）")
    unsub_parser.add_argument("--all", action="store_true",
                              help="扫描全部邮件（默认只扫促销标签）")
    unsub_parser.add_argument("--no-ai", action="store_true", dest="no_ai",
                              help="不使用 Claude AI 辅助判断")
    unsub_parser.add_argument("--archive", action="store_true",
                              help="退订成功后归档该发件人的旧邮件")
    unsub_mode = unsub_parser.add_mutually_exclusive_group(required=True)
    unsub_mode.add_argument("--dry-run", action="store_true", dest="dry_run",
                            help="试运行：展示将要退订的发件人，不实际执行")
    unsub_mode.add_argument("--confirm", action="store_true", dest="confirm",
                            help="确认模式：逐个询问用户")
    unsub_parser.add_argument("--auto", action="store_true",
                              help="自动确认所有退订（需配合 --confirm）")
    unsub_parser.set_defaults(func=cmd_unsubscribe)

    # ── history ──
    history_parser = subparsers.add_parser("history", help="查看退订历史记录")
    history_parser.add_argument("--limit", type=int, default=50, metavar="N",
                                help="显示最近 N 条记录（默认：50）")
    history_parser.set_defaults(func=cmd_history)

    # ── whitelist ──
    wl_parser = subparsers.add_parser("whitelist", help="管理白名单域名")
    wl_sub = wl_parser.add_subparsers(dest="whitelist_action", metavar="操作")
    wl_sub.required = True
    wl_add = wl_sub.add_parser("add", help="添加域名到白名单")
    wl_add.add_argument("domain", help="要加入白名单的域名，如 example.com")
    wl_sub.add_parser("list", help="查看当前白名单")
    wl_parser.set_defaults(func=cmd_whitelist)

    # ── logs ──
    logs_parser = subparsers.add_parser("logs", help="查看运行日志")
    logs_parser.set_defaults(func=cmd_logs)

    return parser
```

- [ ] **Step 7: 更新 cmd_whitelist 函数以使用 database 模块**

将 `cmd_whitelist` 函数中 `add` 分支替换为：

```python
    if args.whitelist_action == "add":
        domain = args.domain.lower().strip()
        if domain in config.WHITELIST_DOMAINS:
            print(f"ℹ️  '{domain}' 已在内置白名单中，无需重复添加。")
            return
        success = database.add_to_user_whitelist(domain)
        if success:
            print(f"✅ 已将 '{domain}' 加入白名单")
            logger.info(f"白名单新增：{domain}")
        else:
            print(f"ℹ️  '{domain}' 已在用户白名单中，无需重复添加。")

    elif args.whitelist_action == "list":
        user_domains = database.get_user_whitelist()
        builtin_count = len(config.WHITELIST_DOMAINS)
        print(f"\n📋 白名单概览")
        print(f"   内置域名数：{builtin_count} 个")
        print(f"   用户自定义：{len(user_domains)} 个\n")
        if user_domains:
            print("  用户自定义白名单：")
            for d in sorted(user_domains):
                print(f"    · {d}")
        else:
            print("  用户自定义白名单：（空）")
        print()
```

- [ ] **Step 8: 验证 main.py 能正常解析命令（无需 credentials）**

```bash
cd /Users/bossoffice/gmail-unsubscriber
source venv/bin/activate
python main.py --help
python main.py history
python main.py whitelist list
```

预期：`--help` 显示所有命令；`history` 显示"暂无退订历史记录"；`whitelist list` 显示白名单概览

- [ ] **Step 9: 运行全部测试确认无回归**

```bash
python -m pytest tests/ -v
```

预期：所有测试 `PASSED`

- [ ] **Step 10: Commit**

```bash
git add main.py
git commit -m "feat: upgrade main.py with history cmd, --archive, --no-ai, --all flags"
```

---

## Task 8: 写详细中文使用说明

**Files:**
- Create: `docs/USAGE_GUIDE.md`

- [ ] **Step 1: 创建 docs/USAGE_GUIDE.md**

创建文件 `docs/USAGE_GUIDE.md`，内容如下：

````markdown
# Gmail 智能退订器 · 详细使用说明

> 一个帮您自动清理 Gmail 广告邮件订阅的工具。安全、可靠、有记忆。

---

## 目录

1. [这个工具能做什么](#1-这个工具能做什么)
2. [首次配置（只需做一次）](#2-首次配置只需做一次)
3. [日常使用流程](#3-日常使用流程)
4. [所有命令详解](#4-所有命令详解)
5. [Claude AI 辅助判断](#5-claude-ai-辅助判断)
6. [白名单管理](#6-白名单管理)
7. [查看历史记录](#7-查看历史记录)
8. [常见问题](#8-常见问题)
9. [安全说明](#9-安全说明)

---

## 1. 这个工具能做什么

- **扫描**：自动分析 Gmail 中最近的广告/促销邮件
- **退订**：用三种方式尝试退订（一键 POST、发退订邮件、点退订链接）
- **标记**：退订成功后在 Gmail 里打上「已退订」标签，一目了然
- **归档**：可选择把旧的广告邮件从收件箱移走（不删除）
- **记忆**：记住退订过的发件人，下次不会重复处理
- **AI 辅助**：遇到模棱两可的邮件，可以请 Claude AI 帮忙判断

**绝对不会做的事：**
- 不会删除任何邮件
- 不会碰白名单里的发件人（银行、Google、政府等）
- 不会在没有您确认的情况下自动退订

---

## 2. 首次配置（只需做一次）

### 第一步：安装依赖

```bash
cd /Users/bossoffice/gmail-unsubscriber
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 第二步：获取 Google API 凭证

这一步让程序能读取您的 Gmail。操作步骤：

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建一个新项目（名字随意，如 "Gmail Unsubscriber"）
3. 左侧菜单 → **API 和服务** → **启用 API 和服务**
4. 搜索 **Gmail API** → 启用
5. 左侧菜单 → **凭据** → **创建凭据** → **OAuth 客户端 ID**
6. 应用类型选 **桌面应用**
7. 点击下载，将文件重命名为 `credentials.json`
8. 将 `credentials.json` 放入 `/Users/bossoffice/gmail-unsubscriber/` 目录

### 第三步：首次授权

```bash
python main.py scan --days 7
```

首次运行会弹出浏览器，请登录您的 Gmail 账号并点击「允许」。授权只需做一次，之后会自动记住。

---

## 3. 日常使用流程

**推荐的标准流程（五步走）：**

```bash
# 激活虚拟环境（每次打开终端后需要运行一次）
source venv/bin/activate

# 第一步：扫描，看看有哪些广告发件人
python main.py scan

# 第二步：如果扫描结果里有重要联系人，把他们加白名单
python main.py whitelist add 某公司.com

# 第三步：试运行，预览将要执行的操作（安全，不会真的退订）
python main.py unsubscribe --dry-run

# 第四步：确认没问题后，逐个确认执行退订
python main.py unsubscribe --confirm

# 第五步：隔几天再扫一次，看看效果
python main.py scan
```

---

## 4. 所有命令详解

### `scan` — 扫描邮件

```bash
python main.py scan [选项]
```

| 选项 | 说明 | 示例 |
|------|------|------|
| `--days N` | 扫描最近 N 天（默认 30） | `--days 60` |
| `--all` | 扫描全部邮件（默认只扫促销标签） | `--all` |
| `--no-ai` | 不使用 AI 辅助判断 | `--no-ai` |

**示例：**
```bash
python main.py scan                    # 扫描最近 30 天的促销邮件
python main.py scan --days 90 --all   # 扫描最近 3 个月的全部邮件
python main.py scan --no-ai           # 只用关键词判断，不调用 AI
```

---

### `unsubscribe` — 执行退订

```bash
python main.py unsubscribe --dry-run | --confirm [选项]
```

**必须选一个模式（二选一）：**

| 模式 | 说明 |
|------|------|
| `--dry-run` | 试运行，只展示会退订什么，不实际执行 |
| `--confirm` | 实际执行，默认逐个询问您 |

**可选参数：**

| 选项 | 说明 |
|------|------|
| `--auto` | 配合 `--confirm` 使用，自动确认所有退订（不逐个询问） |
| `--archive` | 退订成功后，把该发件人的旧邮件从收件箱移到归档 |
| `--days N` | 扫描最近 N 天（默认 30） |
| `--all` | 扫描全部邮件 |
| `--no-ai` | 不使用 AI |

**示例：**
```bash
# 试运行（最安全，先看看会发生什么）
python main.py unsubscribe --dry-run

# 逐个确认执行（推荐）
python main.py unsubscribe --confirm

# 全自动执行（不询问，直接全部退订）
python main.py unsubscribe --confirm --auto

# 退订 + 归档旧邮件（收件箱会变干净）
python main.py unsubscribe --confirm --archive

# 扫描最近 60 天，逐个确认，退订后归档
python main.py unsubscribe --days 60 --confirm --archive
```

**逐个确认时的操作说明：**
- 输入 `y` 或回车 → 退订这个发件人
- 输入 `n` → 跳过，不退订
- 输入 `q` → 立即停止，不再处理后续发件人

---

### `history` — 查看退订历史

```bash
python main.py history [--limit N]
```

查看所有退订过的发件人记录，包括时间、退订方式、是否成功。

```bash
python main.py history          # 显示最近 50 条记录
python main.py history --limit 20  # 只显示最近 20 条
```

---

### `whitelist` — 管理白名单

```bash
python main.py whitelist add <域名>   # 添加域名到白名单
python main.py whitelist list         # 查看白名单
```

**示例：**
```bash
# 把公司邮件域名加入白名单（不会被退订）
python main.py whitelist add mycompany.com

# 查看当前白名单
python main.py whitelist list
```

**内置白名单已包含（无需手动添加）：**
- 银行：工商银行、招商银行、PayPal 等
- 科技公司：Google、Apple、Microsoft、GitHub 等
- 中国平台：淘宝、京东、163 邮箱等
- 政府机构：gov.cn 等
- 教育机构：.edu 结尾的域名

---

### `logs` — 查看运行日志

```bash
python main.py logs
```

显示最新日志文件的最后 50 行，用于排查问题。

---

## 5. Claude AI 辅助判断

### 工作原理

当一封邮件的广告特征**恰好命中 1 个条件**（不够确定是广告），程序会把邮件的发件人、主题、摘要发给 Claude AI 判断。AI 只回答"是广告/不是广告"，不会接触邮件正文。

### 配置 API Key

有两种方式配置：

**方式一：修改 config.py（永久生效）**
```python
ANTHROPIC_API_KEY = "sk-ant-xxxxxxxxxxxx"
```

**方式二：环境变量（推荐，更安全）**
```bash
export ANTHROPIC_API_KEY="sk-ant-xxxxxxxxxxxx"
python main.py scan
```

如果没有配置 API Key，AI 判断会自动跳过，不影响基本功能。

### 关闭 AI

```bash
python main.py scan --no-ai           # 本次扫描不用 AI
python main.py unsubscribe --no-ai    # 本次退订不用 AI
```

或者在 `config.py` 中永久关闭：
```python
USE_AI_CLASSIFIER = False
```

### 费用参考

使用的是 Claude Haiku 模型，速度快且便宜。1000 封模糊邮件的 AI 判断费用约 **$0.01 美元**（约 0.07 元人民币）。大多数情况下，只有少数邮件会触发 AI 判断。

---

## 6. 白名单管理

白名单分两层：

1. **内置白名单**：银行、Google、政府等，写死在代码里，不会误退订
2. **用户自定义白名单**：您自己添加的域名，存在本地数据库里

```bash
# 添加白名单
python main.py whitelist add mycompany.com    # 公司邮件
python main.py whitelist add newsletter.com  # 您想保留的订阅

# 查看白名单
python main.py whitelist list
```

**什么时候需要手动添加白名单？**
- 公司内部系统发的通知邮件
- 您真心想收到的某个 newsletter
- 扫描结果里出现了不该退订的发件人

---

## 7. 查看历史记录

```bash
python main.py history
```

输出示例：
```
📋 退订历史记录（共 15 条，最近 50 条）
────────────────────────────────────────────────────────────
  [1] 某购物平台 <newsletter@shop.example.com>
      邮箱：newsletter@shop.example.com
      时间：2026-04-11 09:30  方式：一键退订（POST）  ✅

  [2] 广告邮件 <promo@ads.example.com>
      邮箱：promo@ads.example.com
      时间：2026-04-11 09:31  方式：退订邮件发送  ✅

  [3] 某服务通知
      邮箱：info@service.example.com
      时间：2026-04-11 09:32  方式：退订失败  ❌
```

已退订的发件人**下次扫描不会再出现**，无需担心重复处理。

---

## 8. 常见问题

**Q：程序说"未发现需要退订的广告邮件"，但我明明有很多广告邮件？**

A：可能原因：
1. 这些广告邮件比较老，超出了扫描天数。试试 `--days 90` 扫更多天
2. Gmail 没有把这些邮件分到促销标签，试试加 `--all` 参数扫全部邮件
3. 这些发件人在白名单里。用 `python main.py whitelist list` 查看

**Q：退订成功了，但邮件还在收件箱里？**

A：这是正常的。退订只是告诉对方"别再发了"，不会删除已有邮件。如果想清理旧邮件，下次退订时加 `--archive` 参数，会把旧邮件移到 Gmail 归档。

**Q：退订失败是什么意思？**

A：对方的退订系统没有响应或返回了错误。这种情况下您需要手动打开邮件，点击邮件底部的「退订」链接。

**Q：担心误退订重要邮件怎么办？**

A：有三道保护：
1. 内置白名单（银行、Google 等绝对不会被退订）
2. 敏感词检测（含验证码、订单、账单的邮件跳过）
3. 先用 `--dry-run` 看一遍，确认没问题再用 `--confirm` 执行

**Q：想取消之前的退订怎么办？**

A：本工具不支持重新订阅（每个网站的重新订阅方式不同）。需要的话，请直接访问对方网站手动重新订阅。

**Q：credentials.json 怎么获取？**

A：参考本文档第 2 节「首次配置」，或查看 `docs/USAGE.md` 的详细图文说明。

---

## 9. 安全说明

| 内容 | 保护措施 |
|------|---------|
| Google 账号 | 使用 OAuth 2.0，程序拿到的是临时授权令牌，不是您的密码 |
| 授权令牌 | 保存在 `token.json`，已加入 .gitignore，不会上传到 git |
| API 凭证 | `credentials.json` 已加入 .gitignore，不会上传到 git |
| Anthropic API Key | 建议用环境变量设置，不要写进代码文件 |
| 数据库文件 | `gmail-unsubscriber.db` 已加入 .gitignore，只在本地 |
| 邮件内容 | AI 判断只发送发件人+主题+摘要，不发送邮件正文 |
| 退订操作 | 不删除任何邮件，只发退订请求 |

**随时撤销授权的方法：**
访问 [Google 账号安全设置](https://myaccount.google.com/permissions)，找到您的 OAuth 应用，点击撤销即可。
````

- [ ] **Step 2: 运行全套测试，确认重构后无回归**

```bash
cd /Users/bossoffice/gmail-unsubscriber
source venv/bin/activate
python -m pytest tests/ -v --tb=short
```

预期：所有测试 `PASSED`

- [ ] **Step 3: 验证命令行帮助正常**

```bash
python main.py --help
python main.py scan --help
python main.py unsubscribe --help
python main.py history --help
python main.py whitelist --help
```

预期：每个命令都显示完整的帮助信息

- [ ] **Step 4: Commit**

```bash
git add docs/USAGE_GUIDE.md
git commit -m "docs: add comprehensive Chinese usage guide"
```

- [ ] **Step 5: 最终汇总 commit（tag）**

```bash
git tag v2.0.0 -m "v2.0.0: full rewrite with AI, SQLite, batch API, labels, archive"
```

---

## 自检结果

**Spec 覆盖：**
- ✅ SQLite 历史记录 → Task 2
- ✅ Claude AI 分类开关 → Task 3 + Task 5
- ✅ Gmail 批量 API → Task 4
- ✅ 已退订发件人过滤 → Task 4
- ✅ 修复 mailto 实际发送 → Task 6
- ✅ 退订后打 Gmail 标签 → Task 6
- ✅ 可选归档 → Task 6（`--archive`）
- ✅ history 命令 → Task 7
- ✅ --no-ai / --archive / --all 参数 → Task 7
- ✅ 精简可疑发件人关键词 → Task 1
- ✅ message_ids 追踪 → Task 5
- ✅ 详细使用说明 → Task 8

**类型一致性：**
- `classify_emails()` 返回的 `sender_group` 包含 `message_ids: list[str]` ✅
- `execute_unsubscribe(group, service, dry_run, archive)` 签名一致 ✅
- `database.record_unsubscribe(sender_email, sender_name, method, success)` 在 Task 2 定义，Task 7 调用一致 ✅
- `scanner.scan_emails(service, days, scan_all)` 在 Task 4 定义，Task 7 调用一致 ✅
- `classifier.classify_emails(emails, use_ai)` 在 Task 5 定义，Task 7 调用一致 ✅
