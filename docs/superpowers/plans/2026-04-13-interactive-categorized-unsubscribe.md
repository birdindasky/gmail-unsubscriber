# Interactive Categorized Unsubscribe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add interactive terminal menu, email categorization with category-based unsubscribe, 3-thread concurrent scanning, and MiniMax AI support to the Gmail unsubscriber tool.

**Architecture:** The existing CLI pipeline (scan → classify → unsubscribe) stays intact. We layer an interactive menu on top of `main.py` that reuses the same underlying functions. Scanning gets parallelized via ThreadPoolExecutor. Classification gains a categorization step that groups senders by email type. AI calls get a provider abstraction to support both MiniMax and Anthropic.

**Tech Stack:** Python 3.9, Gmail API, openai (for MiniMax), anthropic, SQLite, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `config.py` | Modify | Add MiniMax config, EMAIL_CATEGORIES domain mapping, category list |
| `ai_classifier.py` | Modify | Add MiniMax provider, add `categorize_with_ai()` function |
| `scanner.py` | Modify | Rewrite `_fetch_messages_batch` to use 3-thread concurrency |
| `classifier.py` | Modify | Add `categorize_groups()` function |
| `main.py` | Modify | Add interactive menu system, category display, category-based unsubscribe |
| `README.md` | Modify | Update usage instructions |
| `docs/USAGE.md` | Modify | Update command reference, add interactive mode docs |
| `requirements.txt` | Modify | Add `openai` dependency |
| `tests/test_scanner.py` | Modify | Add concurrent fetch test |
| `tests/test_ai_classifier.py` | Modify | Add MiniMax and categorize tests |
| `tests/test_classifier.py` | Modify | Add categorize_groups test |
| `tests/test_interactive.py` | Create | Tests for interactive menu input handling |

---

### Task 1: Add MiniMax Config and Email Categories to config.py

**Files:**
- Modify: `config.py:166-187` (after existing AI config section)

- [ ] **Step 1: Add MiniMax configuration and EMAIL_CATEGORIES to config.py**

Add these sections after the existing AI config block (after line 179):

```python
# ────────────────────────────────────────────────────────────────
#  MiniMax AI 配置
# ────────────────────────────────────────────────────────────────

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_MODEL = "MiniMax-Text-01"
MINIMAX_BASE_URL = "https://api.minimax.chat/v1"

# AI 提供商选择："minimax" 或 "anthropic"
AI_PROVIDER = os.environ.get("AI_PROVIDER", "minimax")

# ────────────────────────────────────────────────────────────────
#  邮件类别定义 & 域名映射
# ────────────────────────────────────────────────────────────────

EMAIL_CATEGORIES = [
    {"name": "电商购物", "icon": "🛒"},
    {"name": "社交媒体", "icon": "📱"},
    {"name": "金融理财", "icon": "💰"},
    {"name": "新闻资讯", "icon": "📰"},
    {"name": "娱乐游戏", "icon": "🎮"},
    {"name": "餐饮外卖", "icon": "🍔"},
    {"name": "旅行出行", "icon": "✈️"},
    {"name": "科技服务", "icon": "💻"},
    {"name": "其他", "icon": "📧"},
]

CATEGORY_NAMES = [c["name"] for c in EMAIL_CATEGORIES]
CATEGORY_ICONS = {c["name"]: c["icon"] for c in EMAIL_CATEGORIES}

DOMAIN_TO_CATEGORY = {
    # 电商购物
    "taobao.com": "电商购物", "tmall.com": "电商购物", "jd.com": "电商购物",
    "pinduoduo.com": "电商购物", "amazon.com": "电商购物", "amazon.cn": "电商购物",
    "ebay.com": "电商购物", "shopee.com": "电商购物", "lazada.com": "电商购物",
    "aliexpress.com": "电商购物", "walmart.com": "电商购物", "target.com": "电商购物",
    "bestbuy.com": "电商购物", "etsy.com": "电商购物", "shein.com": "电商购物",
    "suning.com": "电商购物", "dangdang.com": "电商购物", "vip.com": "电商购物",
    # 社交媒体
    "linkedin.com": "社交媒体", "facebook.com": "社交媒体", "instagram.com": "社交媒体",
    "twitter.com": "社交媒体", "x.com": "社交媒体", "weibo.com": "社交媒体",
    "tiktok.com": "社交媒体", "douyin.com": "社交媒体", "xiaohongshu.com": "社交媒体",
    "reddit.com": "社交媒体", "discord.com": "社交媒体", "snapchat.com": "社交媒体",
    "pinterest.com": "社交媒体", "quora.com": "社交媒体", "zhihu.com": "社交媒体",
    # 金融理财
    "eastmoney.com": "金融理财", "xueqiu.com": "金融理财", "futu.com": "金融理财",
    "lufax.com": "金融理财", "creditkarma.com": "金融理财", "mint.com": "金融理财",
    "robinhood.com": "金融理财", "coinbase.com": "金融理财", "binance.com": "金融理财",
    # 新闻资讯
    "36kr.com": "新闻资讯", "huxiu.com": "新闻资讯", "toutiao.com": "新闻资讯",
    "substack.com": "新闻资讯", "medium.com": "新闻资讯", "nytimes.com": "新闻资讯",
    "wsj.com": "新闻资讯", "bbc.com": "新闻资讯", "cnn.com": "新闻资讯",
    "reuters.com": "新闻资讯", "bloomberg.com": "新闻资讯", "theguardian.com": "新闻资讯",
    "sspai.com": "新闻资讯", "infoq.cn": "新闻资讯",
    # 娱乐游戏
    "steampowered.com": "娱乐游戏", "epicgames.com": "娱乐游戏", "ea.com": "娱乐游戏",
    "blizzard.com": "娱乐游戏", "playstation.com": "娱乐游戏", "xbox.com": "娱乐游戏",
    "netflix.com": "娱乐游戏", "spotify.com": "娱乐游戏", "hulu.com": "娱乐游戏",
    "iqiyi.com": "娱乐游戏", "bilibili.com": "娱乐游戏", "youku.com": "娱乐游戏",
    # 餐饮外卖
    "meituan.com": "餐饮外卖", "ele.me": "餐饮外卖", "doordash.com": "餐饮外卖",
    "ubereats.com": "餐饮外卖", "grubhub.com": "餐饮外卖", "deliveroo.com": "餐饮外卖",
    "starbucks.com": "餐饮外卖", "mcdonalds.com": "餐饮外卖", "dominos.com": "餐饮外卖",
    "grabfood.com": "餐饮外卖", "foodpanda.com": "餐饮外卖",
    # 旅行出行
    "ctrip.com": "旅行出行", "booking.com": "旅行出行", "airbnb.com": "旅行出行",
    "expedia.com": "旅行出行", "trip.com": "旅行出行", "agoda.com": "旅行出行",
    "skyscanner.com": "旅行出行", "kayak.com": "旅行出行", "tripadvisor.com": "旅行出行",
    "uber.com": "旅行出行", "lyft.com": "旅行出行", "didi.com": "旅行出行",
    "grab.com": "旅行出行", "klook.com": "旅行出行",
    # 科技服务
    "heroku.com": "科技服务", "vercel.com": "科技服务", "netlify.com": "科技服务",
    "digitalocean.com": "科技服务", "vultr.com": "科技服务", "linode.com": "科技服务",
    "notion.so": "科技服务", "slack.com": "科技服务", "atlassian.com": "科技服务",
    "jetbrains.com": "科技服务", "figma.com": "科技服务", "canva.com": "科技服务",
    "zoom.us": "科技服务", "dropbox.com": "科技服务", "grammarly.com": "科技服务",
    "openai.com": "科技服务", "anthropic.com": "科技服务",
}
```

- [ ] **Step 2: Add openai to requirements.txt**

Append to the end of `requirements.txt`:

```
openai>=1.0.0
```

- [ ] **Step 3: Install the new dependency**

Run: `source venv/bin/activate && pip install openai>=1.0.0`

- [ ] **Step 4: Run existing tests to verify nothing breaks**

Run: `source venv/bin/activate && python -m pytest tests/ -v --tb=short`
Expected: All 32 tests pass.

- [ ] **Step 5: Commit**

```bash
git add config.py requirements.txt
git commit -m "feat: add MiniMax config and email category definitions"
```

---

### Task 2: Add MiniMax Provider and categorize_with_ai to ai_classifier.py

**Files:**
- Modify: `ai_classifier.py`
- Modify: `tests/test_ai_classifier.py`

- [ ] **Step 1: Write failing tests for MiniMax provider and categorize_with_ai**

Add to `tests/test_ai_classifier.py`:

```python
def test_minimax_classify_ad_email():
    """MiniMax 提供商应能正确判断广告邮件。"""
    import ai_classifier
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"is_ad": True, "reason": "促销邮件"})
    mock_client.chat.completions.create.return_value = mock_response

    with patch("ai_classifier._get_openai_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-Text-01"
        mock_config.MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
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
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"is_ad": False, "reason": "系统通知"})
    mock_client.chat.completions.create.return_value = mock_response

    with patch("ai_classifier._get_openai_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.USE_AI_CLASSIFIER = True
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-Text-01"
        mock_config.MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
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
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"category": "电商购物"})
    mock_client.chat.completions.create.return_value = mock_response

    with patch("ai_classifier._get_openai_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-Text-01"
        mock_config.MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
        mock_config.AI_MAX_TOKENS = 150
        mock_config.CATEGORY_NAMES = ["电商购物", "社交媒体", "其他"]

        category = ai_classifier.categorize_with_ai("淘宝", "限时折扣")

    assert category == "电商购物"


def test_categorize_with_ai_invalid_returns_other():
    """AI 返回无效类别时应回退到'其他'。"""
    import ai_classifier
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({"category": "不存在的类别"})
    mock_client.chat.completions.create.return_value = mock_response

    with patch("ai_classifier._get_openai_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-Text-01"
        mock_config.MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
        mock_config.AI_MAX_TOKENS = 150
        mock_config.CATEGORY_NAMES = ["电商购物", "社交媒体", "其他"]

        category = ai_classifier.categorize_with_ai("unknown@xyz.com", "Hello")

    assert category == "其他"


def test_categorize_with_ai_error_returns_other():
    """AI 调用失败时应回退到'其他'。"""
    import ai_classifier
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("timeout")

    with patch("ai_classifier._get_openai_client", return_value=mock_client), \
         patch("ai_classifier.config") as mock_config:
        mock_config.AI_PROVIDER = "minimax"
        mock_config.MINIMAX_API_KEY = "test-key"
        mock_config.MINIMAX_MODEL = "MiniMax-Text-01"
        mock_config.MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
        mock_config.AI_MAX_TOKENS = 150
        mock_config.CATEGORY_NAMES = ["电商购物", "其他"]

        category = ai_classifier.categorize_with_ai("x@y.com", "test")

    assert category == "其他"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_ai_classifier.py -v --tb=short`
Expected: New tests FAIL (functions don't exist yet).

- [ ] **Step 3: Implement MiniMax provider and categorize_with_ai**

Replace the entire `ai_classifier.py` with:

```python
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
    client = _get_anthropic_client()
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
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/ -v --tb=short`
Expected: All tests pass (old anthropic tests + new minimax tests + categorize tests).

- [ ] **Step 5: Commit**

```bash
git add ai_classifier.py tests/test_ai_classifier.py
git commit -m "feat: add MiniMax AI provider and categorize_with_ai function"
```

---

### Task 3: Parallelize Scanner with 3-Thread Concurrency

**Files:**
- Modify: `scanner.py:114-158` (the `_fetch_messages_batch` function)
- Modify: `tests/test_scanner.py`

- [ ] **Step 1: Write failing test for concurrent fetch**

Add to `tests/test_scanner.py`:

```python
def test_fetch_messages_batch_concurrent():
    """_fetch_messages_batch 应使用多线程并发获取邮件。"""
    msgs = [_make_msg(f"id-{i}", f"test{i}@example.com") for i in range(6)]
    stubs = [{"id": f"id-{i}"} for i in range(6)]

    call_count = {"n": 0}
    original_lock = threading.Lock()

    def mock_execute_factory(msg):
        def mock_execute():
            with original_lock:
                call_count["n"] += 1
            return msg
        return mock_execute

    mock_service = MagicMock()
    def mock_get(**kwargs):
        msg_id = kwargs["id"]
        idx = int(msg_id.split("-")[1])
        result = MagicMock()
        result.execute = mock_execute_factory(msgs[idx])
        return result

    mock_service.users.return_value.messages.return_value.get = mock_get

    import threading
    with patch("scanner.time") as mock_time:
        mock_time.sleep = MagicMock()
        results = scanner._fetch_messages_batch(mock_service, stubs)

    assert len(results) == 6
    assert call_count["n"] == 6
```

Also add `import threading` at the top of the test file if not present.

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest tests/test_scanner.py::test_fetch_messages_batch_concurrent -v --tb=short`
Expected: FAIL (current sequential implementation doesn't use thread-local services correctly in this test setup, but the test should at least run).

- [ ] **Step 3: Rewrite _fetch_messages_batch with ThreadPoolExecutor**

Replace `_fetch_messages_batch` in `scanner.py` (lines 114-158) with:

```python
def _fetch_messages_batch(service, message_stubs: list[dict]) -> list[dict]:
    """
    使用 3 线程并发获取邮件 metadata，遇到 429 自动退避重试。
    每个线程维护独立的请求间隔以控制总 QPS。
    """
    results = []
    total = len(message_stubs)
    results_lock = threading.Lock()
    progress_lock = threading.Lock()
    progress = {"done": 0}

    def fetch_one(stub):
        svc = service
        parsed = None
        for attempt in range(MAX_RETRIES):
            try:
                msg = svc.users().messages().get(
                    userId="me",
                    id=stub["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "List-Unsubscribe",
                                     "List-Unsubscribe-Post", "Date"],
                ).execute()
                parsed = _parse_message(msg)
                break
            except HttpError as e:
                if e.resp.status in (429, 500, 503):
                    wait = RETRY_DELAY * (attempt + 1)
                    logger.debug(f"{e.resp.status} 错误，{wait}s 后重试（第 {attempt+1} 次）...")
                    time.sleep(wait)
                else:
                    logger.warning(f"获取邮件失败（{stub['id']}）：{e}")
                    break
            except Exception as e:
                logger.warning(f"邮件解析失败（{stub['id']}）：{e}")
                break

        time.sleep(REQUEST_SLEEP)

        with progress_lock:
            progress["done"] += 1
            done = progress["done"]
            if done % PROGRESS_INTERVAL == 0 or done == total:
                print(f"   进度：{done}/{total} 封...")

        return parsed

    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = {executor.submit(fetch_one, stub): stub for stub in message_stubs}
        for future in as_completed(futures):
            result = future.result()
            if result:
                with results_lock:
                    results.append(result)

    return results
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/ -v --tb=short`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add scanner.py tests/test_scanner.py
git commit -m "perf: parallelize email scanning with 3-thread concurrency"
```

---

### Task 4: Add categorize_groups to classifier.py

**Files:**
- Modify: `classifier.py`
- Modify: `tests/test_classifier.py`

- [ ] **Step 1: Write failing test for categorize_groups**

Add to `tests/test_classifier.py`:

```python
def test_categorize_groups_by_domain():
    """categorize_groups 应根据域名分配类别。"""
    groups = [
        {"sender_email": "promo@taobao.com", "sender": "淘宝", "sender_domain": "taobao.com",
         "count": 10, "reasons": ["广告"], "sample_subjects": ["打折"], "message_ids": ["id1"],
         "list_unsubscribe": None, "list_unsubscribe_post": None, "sample_html": "", "sample_id": "id1"},
        {"sender_email": "news@36kr.com", "sender": "36氪", "sender_domain": "36kr.com",
         "count": 5, "reasons": ["广告"], "sample_subjects": ["日报"], "message_ids": ["id2"],
         "list_unsubscribe": None, "list_unsubscribe_post": None, "sample_html": "", "sample_id": "id2"},
        {"sender_email": "spam@unknown.xyz", "sender": "Unknown", "sender_domain": "unknown.xyz",
         "count": 3, "reasons": ["广告"], "sample_subjects": ["Hi"], "message_ids": ["id3"],
         "list_unsubscribe": None, "list_unsubscribe_post": None, "sample_html": "", "sample_id": "id3"},
    ]
    with patch("classifier.ai_classifier.categorize_with_ai", return_value="其他"):
        result = classifier.categorize_groups(groups, use_ai=False)

    assert "电商购物" in result
    assert "新闻资讯" in result
    assert "其他" in result
    assert len(result["电商购物"]) == 1
    assert result["电商购物"][0]["sender_email"] == "promo@taobao.com"


def test_categorize_groups_with_ai():
    """当域名未命中且 AI 开启时，应调用 AI 分类。"""
    groups = [
        {"sender_email": "spam@mystery.xyz", "sender": "Mystery Shop", "sender_domain": "mystery.xyz",
         "count": 3, "reasons": ["广告"], "sample_subjects": ["Buy now"], "message_ids": ["id1"],
         "list_unsubscribe": None, "list_unsubscribe_post": None, "sample_html": "", "sample_id": "id1"},
    ]
    with patch("classifier.ai_classifier.categorize_with_ai", return_value="电商购物") as mock_ai:
        result = classifier.categorize_groups(groups, use_ai=True)

    mock_ai.assert_called_once_with("Mystery Shop", "Buy now")
    assert "电商购物" in result
    assert len(result["电商购物"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest tests/test_classifier.py::test_categorize_groups_by_domain -v --tb=short`
Expected: FAIL with AttributeError (function doesn't exist yet).

- [ ] **Step 3: Implement categorize_groups in classifier.py**

Add at the end of `classifier.py`, before the final line:

```python
# ────────────────────────────────────────────────────────────────
#  按类别归组
# ────────────────────────────────────────────────────────────────

def categorize_groups(groups: list[dict], use_ai: bool = True) -> dict[str, list[dict]]:
    """
    将发件人分组按邮件类别归组。

    Args:
        groups:  classify_emails() 返回的 to_unsubscribe 列表
        use_ai:  是否使用 AI 判断未知域名的类别

    Returns:
        dict: {类别名: [发件人分组列表]}，只包含非空类别
    """
    categorized: dict[str, list[dict]] = {}

    for group in groups:
        domain = group.get("sender_domain", "")
        category = config.DOMAIN_TO_CATEGORY.get(domain)

        if not category:
            for mapped_domain, mapped_cat in config.DOMAIN_TO_CATEGORY.items():
                if domain.endswith("." + mapped_domain):
                    category = mapped_cat
                    break

        if not category and use_ai:
            sender = group.get("sender", "")
            subject = group["sample_subjects"][0] if group.get("sample_subjects") else ""
            category = ai_classifier.categorize_with_ai(sender, subject)

        if not category:
            category = "其他"

        if category not in categorized:
            categorized[category] = []
        categorized[category].append(group)

    return categorized
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `source venv/bin/activate && python -m pytest tests/ -v --tb=short`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add classifier.py tests/test_classifier.py
git commit -m "feat: add categorize_groups for email category grouping"
```

---

### Task 5: Build Interactive Menu System in main.py

**Files:**
- Modify: `main.py`
- Create: `tests/test_interactive.py`

- [ ] **Step 1: Write tests for interactive menu helpers**

Create `tests/test_interactive.py`:

```python
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import parse_selection, format_category_summary


def test_parse_selection_single():
    assert parse_selection("1", 5) == [0]


def test_parse_selection_multiple_comma():
    assert parse_selection("1,3,5", 5) == [0, 2, 4]


def test_parse_selection_all():
    assert parse_selection("all", 5) == [0, 1, 2, 3, 4]


def test_parse_selection_invalid():
    assert parse_selection("abc", 5) == []


def test_parse_selection_out_of_range():
    assert parse_selection("99", 5) == []


def test_parse_selection_zero_returns_empty():
    assert parse_selection("0", 5) == []


def test_format_category_summary():
    categorized = {
        "电商购物": [
            {"sender_email": "a@taobao.com", "count": 10},
            {"sender_email": "b@jd.com", "count": 5},
        ],
        "新闻资讯": [
            {"sender_email": "c@36kr.com", "count": 3},
        ],
    }
    lines = format_category_summary(categorized)
    assert len(lines) == 2
    assert "电商购物" in lines[0]
    assert "2 个发件人" in lines[0]
    assert "15 封" in lines[0]
    assert "新闻资讯" in lines[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && python -m pytest tests/test_interactive.py -v --tb=short`
Expected: FAIL (functions don't exist yet).

- [ ] **Step 3: Add helper functions and interactive menu to main.py**

Add the following helper functions after the `_print_summary` function (after line 281):

```python
# ────────────────────────────────────────────────────────────────
#  交互式菜单辅助函数
# ────────────────────────────────────────────────────────────────

def parse_selection(user_input: str, total: int) -> list[int]:
    """
    解析用户输入的选择，返回 0-based 索引列表。
    支持：单个编号（"1"）、逗号分隔（"1,3,5"）、all。
    输入 "0" 或无效内容返回空列表。
    """
    user_input = user_input.strip().lower()
    if user_input == "all":
        return list(range(total))
    if user_input == "0":
        return []

    indices = []
    for part in user_input.split(","):
        part = part.strip()
        if part.isdigit():
            num = int(part)
            if 1 <= num <= total:
                indices.append(num - 1)
    return indices


def format_category_summary(categorized: dict) -> list[str]:
    """
    格式化类别摘要行列表。
    返回如 ["  [A] 🛒 电商购物（2 个发件人，15 封）", ...] 的列表。
    """
    import config as _cfg
    lines = []
    for i, (cat_name, groups) in enumerate(categorized.items()):
        letter = chr(ord("A") + i)
        icon = _cfg.CATEGORY_ICONS.get(cat_name, "📧")
        sender_count = len(groups)
        email_count = sum(g["count"] for g in groups)
        lines.append(f"  [{letter}] {icon} {cat_name}（{sender_count} 个发件人，{email_count} 封）")
    return lines
```

- [ ] **Step 4: Run tests to verify helpers pass**

Run: `source venv/bin/activate && python -m pytest tests/test_interactive.py -v --tb=short`
Expected: All tests pass.

- [ ] **Step 5: Add the full interactive menu system to main.py**

Add after the helper functions (before `build_parser`):

```python
# ────────────────────────────────────────────────────────────────
#  交互式菜单
# ────────────────────────────────────────────────────────────────

def interactive_menu() -> None:
    """交互式主菜单入口。"""
    setup_logging()
    database.init_db()

    while True:
        print()
        print("╔══════════════════════════════════╗")
        print("║      Gmail 邮件退订工具 📬       ║")
        print("╠══════════════════════════════════╣")
        print("║  1. 扫描邮件                     ║")
        print("║  2. 执行退订                     ║")
        print("║  3. 查看退订历史                 ║")
        print("║  4. 管理白名单                   ║")
        print("║  5. 设置                         ║")
        print("║  0. 退出                         ║")
        print("╚══════════════════════════════════╝")

        choice = input("\n请选择 > ").strip()

        if choice == "1":
            _interactive_scan()
        elif choice == "2":
            _interactive_unsubscribe()
        elif choice == "3":
            _interactive_history()
        elif choice == "4":
            _interactive_whitelist()
        elif choice == "5":
            _interactive_settings()
        elif choice == "0":
            print("\n👋 再见！")
            break
        else:
            print("❌ 无效选择，请输入 0-5 的数字。")


def _ask_scan_params() -> tuple:
    """交互式询问扫描参数，返回 (days, scan_all, use_ai)。"""
    print("\n── 扫描设置 ──")
    days_input = input("  扫描最近几天的邮件？（默认 30，输入 0 扫全部历史）> ").strip()
    days = int(days_input) if days_input.isdigit() else 30

    scope = input("  扫描范围？ 1=仅促销邮件（默认） 2=全部邮件 > ").strip()
    scan_all = scope == "2"

    ai_choice = input("  使用 AI 辅助判断？ 1=是（默认） 2=否 > ").strip()
    use_ai = ai_choice != "2"

    return days, scan_all, use_ai


def _do_scan_and_classify(days, scan_all, use_ai):
    """执行扫描和分类，返回 (categorized, to_unsub, emails_count)。"""
    service = auth.get_gmail_service()
    emails = scanner.scan_emails(service, days=days, scan_all=scan_all)

    if not emails:
        print("📭 未找到邮件。")
        return None, None, 0

    result = classifier.classify_emails(emails, use_ai=use_ai)
    to_unsub = result["to_unsubscribe"]

    if not to_unsub:
        print("✅ 未发现需要退订的广告邮件。")
        return None, None, len(emails)

    categorized = classifier.categorize_groups(to_unsub, use_ai=use_ai)
    return categorized, to_unsub, len(emails)


def _display_categories(categorized: dict) -> None:
    """展示分类结果摘要。"""
    print(f"\n📊 扫描完成！按类别分组：\n")
    lines = format_category_summary(categorized)
    for line in lines:
        print(line)
    print()


def _interactive_scan() -> None:
    """交互式扫描。"""
    days, scan_all, use_ai = _ask_scan_params()
    categorized, to_unsub, total = _do_scan_and_classify(days, scan_all, use_ai)

    if not categorized:
        return

    _display_categories(categorized)

    total_senders = sum(len(g) for g in categorized.values())
    total_emails = sum(g["count"] for groups in categorized.values() for g in groups)
    print(f"  共 {total_senders} 个发件人建议退订，{total_emails} 封邮件")
    print(f"\n  运行选项 2「执行退订」可按类别退订。")

    database.record_scan(
        days=days, total_emails=total,
        candidates=total_senders, unsubscribed=0,
    )


def _interactive_unsubscribe() -> None:
    """交互式退订（按类别）。"""
    days, scan_all, use_ai = _ask_scan_params()

    archive_choice = input("  退订后归档旧邮件？ 1=否（默认） 2=是 > ").strip()
    archive = archive_choice == "2"

    categorized, to_unsub, total = _do_scan_and_classify(days, scan_all, use_ai)
    if not categorized:
        return

    service = auth.get_gmail_service()
    cat_keys = list(categorized.keys())

    success_count = 0
    skip_count = 0
    fail_count = 0

    while True:
        _display_categories(categorized)
        print("  输入字母展开类别 / all 退订全部 / 0 返回主菜单")
        choice = input("\n> ").strip().lower()

        if choice == "0":
            break
        elif choice == "all":
            for cat_name, groups in categorized.items():
                s, sk, f = _unsubscribe_groups(groups, service, archive)
                success_count += s
                skip_count += sk
                fail_count += f
            _print_summary(success_count, skip_count, fail_count)
            break
        elif len(choice) == 1 and choice.isalpha():
            idx = ord(choice) - ord("a")
            if 0 <= idx < len(cat_keys):
                cat_name = cat_keys[idx]
                groups = categorized[cat_name]
                icon = config.CATEGORY_ICONS.get(cat_name, "📧")
                print(f"\n{icon} {cat_name} — {len(groups)} 个发件人：\n")
                for j, g in enumerate(groups, 1):
                    print(f"  [{j}] {g.get('sender', g['sender_email'])} ({g['sender_email']}) — {g['count']}封")
                print(f"\n  输入编号退订（如 1,3,5）/ all 退订全部 / 0 返回")
                sel = input("> ").strip()
                indices = parse_selection(sel, len(groups))
                if indices:
                    selected = [groups[i] for i in indices]
                    s, sk, f = _unsubscribe_groups(selected, service, archive)
                    success_count += s
                    skip_count += sk
                    fail_count += f
            else:
                print("❌ 无效选择。")
        else:
            print("❌ 无效输入。请输入字母、all 或 0。")

    if success_count or fail_count:
        database.record_scan(
            days=days, total_emails=total,
            candidates=len(to_unsub), unsubscribed=success_count,
        )


def _unsubscribe_groups(groups: list[dict], service, archive: bool) -> tuple[int, int, int]:
    """对一组发件人执行退订，返回 (成功, 跳过, 失败) 数量。"""
    success = skip = fail = 0
    for g in groups:
        sender_email = g["sender_email"]
        sender_display = g.get("sender", sender_email)

        print(f"\n  正在退订：{sender_display} ({sender_email})")
        exec_result = unsubscriber.execute_unsubscribe(
            g, service=service, dry_run=False, archive=archive
        )
        if exec_result["success"]:
            print(f"  ✅ 退订成功：{exec_result['message']}")
            success += 1
            database.record_unsubscribe(
                sender_email=sender_email,
                sender_name=sender_display,
                method=exec_result.get("attempted_method", "unknown"),
                success=True,
            )
        else:
            print(f"  ❌ 退订失败：{exec_result['message']}")
            fail += 1

    return success, skip, fail


def _interactive_history() -> None:
    """交互式查看退订历史。"""
    import argparse
    args = argparse.Namespace(limit=50)
    cmd_history(args)


def _interactive_whitelist() -> None:
    """交互式白名单管理。"""
    print("\n── 白名单管理 ──")
    print("  1. 查看白名单")
    print("  2. 添加域名到白名单")
    print("  0. 返回")
    choice = input("\n> ").strip()

    if choice == "1":
        import argparse
        args = argparse.Namespace(whitelist_action="list", func=cmd_whitelist)
        cmd_whitelist(args)
    elif choice == "2":
        domain = input("  请输入要添加的域名（如 example.com）> ").strip()
        if domain:
            import argparse
            args = argparse.Namespace(whitelist_action="add", domain=domain, func=cmd_whitelist)
            cmd_whitelist(args)
    elif choice == "0":
        return
    else:
        print("❌ 无效选择。")


def _interactive_settings() -> None:
    """交互式设置。"""
    print("\n── 当前设置 ──")
    provider = getattr(config, "AI_PROVIDER", "anthropic")
    print(f"  AI 模型：{provider}")
    if provider == "minimax":
        key = config.MINIMAX_API_KEY
        print(f"  MiniMax API Key：{'已配置' if key else '❌ 未配置（设置环境变量 MINIMAX_API_KEY）'}")
    else:
        key = config.ANTHROPIC_API_KEY
        print(f"  Anthropic API Key：{'已配置' if key else '❌ 未配置（设置环境变量 ANTHROPIC_API_KEY）'}")
    print(f"  AI 辅助分类：{'开启' if config.USE_AI_CLASSIFIER else '关闭'}")
    print()
    print("  提示：修改 AI 提供商请设置环境变量 AI_PROVIDER=minimax 或 AI_PROVIDER=anthropic")
    print("  提示：API Key 请设置环境变量 MINIMAX_API_KEY 或 ANTHROPIC_API_KEY")
```

- [ ] **Step 6: Modify the main() function to support interactive mode**

Replace the existing `main()` function (lines 496-517) with:

```python
def main() -> None:
    if len(sys.argv) == 1:
        try:
            interactive_menu()
        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            sys.exit(0)
        return

    parser = build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    database.init_db()
    logger.info(f"启动命令：{' '.join(sys.argv)}")

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n\n用户中断，程序退出。")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"程序异常退出：{e}")
        print(f"\n❌ 程序遇到未预期的错误：{e}")
        print(f"   详细信息请查看日志：{LOG_FILE}")
        sys.exit(1)
```

- [ ] **Step 7: Also update cmd_scan to show categories**

Replace the `cmd_scan` function (lines 85-143) with:

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

    categorized = classifier.categorize_groups(to_unsub, use_ai=use_ai)

    print("─" * 60)
    print("  按类别分组的退订建议：")
    print("─" * 60)

    for cat_name, groups in categorized.items():
        icon = config.CATEGORY_ICONS.get(cat_name, "📧")
        total_count = sum(g["count"] for g in groups)
        print(f"\n  {icon} {cat_name}（{len(groups)} 个发件人，{total_count} 封）")

        for i, group in enumerate(groups, 1):
            print(f"    [{i}] {group['sender']}")
            print(f"        邮箱：{group['sender_email']}  |  {group['count']} 封")
            if group.get("reasons"):
                print(f"        依据：{group['reasons'][0]}")

    print()
    print("─" * 60)
    print(f"  运行 'python main.py unsubscribe --dry-run' 预览退订操作")
    print(f"  或直接运行 'python main.py' 进入交互式菜单")
    print("─" * 60)

    logger.info(f"扫描完成：{len(to_unsub)} 个发件人建议退订，{skipped} 封邮件已跳过")
```

- [ ] **Step 8: Run all tests**

Run: `source venv/bin/activate && python -m pytest tests/ -v --tb=short`
Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add main.py tests/test_interactive.py
git commit -m "feat: add interactive terminal menu with category-based unsubscribe"
```

---

### Task 6: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/USAGE.md`

- [ ] **Step 1: Update README.md**

Replace the entire `README.md` with:

```markdown
# Gmail 智能退订器

自动识别并退订 Gmail 中的商业广告邮件，同时安全跳过重要邮件（银行、政府、医疗、工作等）。

## 🛡️ 安全特性

- **白名单优先**：银行、Google、政府、医疗等重要发件人一律跳过
- **默认 dry-run**：所有操作先预览再执行，不会误退订
- **不删除邮件**：只退订，不动收件箱
- **逐个确认**：默认逐个确认每个发件人

## 🚀 3 步快速启动

```bash
# 1. 克隆项目
cd /path/to/gmail-unsubscriber

# 2. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 获取 Google OAuth 凭证
# 参考 docs/USAGE.md 完成 Google Cloud Console 配置
# 将 credentials.json 放入项目根目录

# 4. 首次运行（会弹出浏览器授权）
python3 main.py
```

## 📖 两种使用方式

### 方式一：交互式菜单（推荐新手）

直接运行，跟着菜单操作：

```bash
python3 main.py
```

菜单会引导你完成扫描、按类别退订、管理白名单等操作。

### 方式二：命令行参数（高级用户）

```bash
python3 main.py scan                              # 扫描最近 30 天
python3 main.py scan --days 0 --all               # 扫全部历史
python3 main.py unsubscribe --dry-run             # 预览退订
python3 main.py unsubscribe --confirm             # 逐个确认退订
python3 main.py unsubscribe --confirm --auto      # 自动退订全部
```

## 🤖 AI 支持

支持两种 AI 模型辅助判断：

- **MiniMax**（默认）：设置环境变量 `MINIMAX_API_KEY`
- **Anthropic Claude**：设置环境变量 `ANTHROPIC_API_KEY` 和 `AI_PROVIDER=anthropic`

## 📖 文档

- [快速上手指南](./docs/USAGE.md) - 详细使用说明
- [架构设计](./docs/ARCHITECTURE.md) - 设计与思路
- [文件说明](./docs/FILE_OVERVIEW.md) - 代码结构

## ⚠️ 安全提示

1. **默认是预览模式**：`--dry-run` 不会真正退订
2. **白名单机制**：重要邮件不会被退订
3. **不删除任何邮件**：退订和删除是独立操作
4. **OAuth 安全**：使用 Gmail API 而非 IMAP 密码
```

- [ ] **Step 2: Update docs/USAGE.md**

Replace the entire `docs/USAGE.md` with:

```markdown
# Gmail 退订工具 · 使用指南

详细说明请看 [USAGE_GUIDE.md](USAGE_GUIDE.md)。

---

## 激活环境（每次打开终端后运行一次）

```bash
source venv/bin/activate
```

---

## 方式一：交互式菜单（推荐）

```bash
python3 main.py
```

直接运行，不带任何参数，会进入交互式菜单：

```
╔══════════════════════════════════╗
║      Gmail 邮件退订工具 📬       ║
╠══════════════════════════════════╣
║  1. 扫描邮件                     ║
║  2. 执行退订                     ║
║  3. 查看退订历史                 ║
║  4. 管理白名单                   ║
║  5. 设置                         ║
║  0. 退出                         ║
╚══════════════════════════════════╝
```

**扫描**：选择 1，按提示输入扫描天数和范围，完成后邮件会按类别分组展示。

**退订**：选择 2，扫描完成后按字母选择类别展开，输入编号选择退订的发件人。

---

## 方式二：命令行参数（高级用户）

```bash
# 扫描最近 30 天的促销邮件（只看，不退订）
python3 main.py scan

# 扫描全部历史邮件 + 全部分类（首次深度清理推荐）
python3 main.py scan --days 0 --all

# 试运行退订，预览将要发生什么（不会真的退订）
python3 main.py unsubscribe --dry-run

# 逐个确认执行退订（推荐日常使用）
python3 main.py unsubscribe --confirm

# 自动退订所有建议发件人（不逐个询问）
python3 main.py unsubscribe --confirm --auto

# 退订 + 把旧广告邮件移出收件箱
python3 main.py unsubscribe --confirm --archive

# 把某个域名加入白名单（不再被退订）
python3 main.py whitelist add 某公司.com

# 查看退订历史
python3 main.py history

# 查看日志（排查问题用）
python3 main.py logs
```

---

## AI 模型配置

工具支持两种 AI 提供商，用于辅助判断模糊邮件和自动分类：

### MiniMax（默认）

```bash
export MINIMAX_API_KEY="你的MiniMax API Key"
```

### Anthropic Claude

```bash
export AI_PROVIDER=anthropic
export ANTHROPIC_API_KEY="你的Anthropic API Key"
```

在交互菜单的「设置」中可查看当前 AI 配置状态。

---

## 首次深度清理流程

### 交互模式

1. 运行 `python3 main.py`
2. 选择 1 扫描，天数输入 0，范围选全部
3. 查看分类结果，把不想退订的加白名单（选择 4）
4. 选择 2 退订，按类别选择退订

### 命令行模式

```bash
# 1. 扫描，看看有哪些广告发件人
python3 main.py scan --days 0 --all

# 2. 把不想退订的加白名单
python3 main.py whitelist add 某公司.com

# 3. 试运行，确认无误
python3 main.py unsubscribe --dry-run --days 0 --all

# 4. 正式执行退订
python3 main.py unsubscribe --confirm --days 0 --all
```

---

## 关键说明

- 直接运行 `python3 main.py`（无参数）进入交互式菜单
- `scan` 只扫描，**不退订**；`unsubscribe` 内部会自己扫描
- `--days 0` 表示扫全部历史邮件（无时间限制），邮件多时需要等待
- `--all` 扫全部分类，默认只扫 Gmail 的促销标签
- `--auto` 必须配合 `--confirm` 一起使用
- 退订后旧邮件仍在收件箱，加 `--archive` 可以顺手移走
- 扫描结果自动按邮件类别分组（电商、新闻、社交等）
```

- [ ] **Step 3: Run all tests one final time**

Run: `source venv/bin/activate && python -m pytest tests/ -v --tb=short`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/USAGE.md
git commit -m "docs: update README and USAGE for interactive menu and MiniMax support"
```
