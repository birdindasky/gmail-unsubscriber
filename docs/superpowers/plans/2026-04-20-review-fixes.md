## Status

Completed 2026-04-20. All 10 tasks applied and committed. Test baseline 80 → 94 (14 new tests added, all green).

| # | Task | Commit |
|---|------|--------|
| 1 | chmod 600 on token.json + credentials.json | `6becbff` |
| 2 | chmod 600 on SQLite db after init | `312ed88` |
| 3 | Scanner log exhausted retries + None-guard | `fa37871` |
| 4 | Fix dead whitelist branch + drop bogus TLD tokens | `5caa7dd` |
| 5 | Rename misleading "skipped" label | `2814a1a` |
| 6 | Drop dead JSON whitelist fallback | `662076e` |
| 7 | Drop unused imports + simplify token set | `62d979d` |
| 8 | Fix doc path + generalize AI help text | `6837a58` |
| 9 | Mask API key patterns in exception logs | `414f66d` |
| 10 | Reject non-http(s) unsubscribe URLs | `a0014e0` |

Execution note: Codex applied Task 1's `auth.py` edit but could not commit due to a sandbox denial on `.git/` writes; remaining edits and all commits were made directly by Claude in-session. The original Codex blocker is therefore resolved, not outstanding.

---

# Gmail Unsubscriber — 2026-04-20 Review Fixes Plan

> **For Codex (execution agent):** Apply each task below in order. For every task: read the file, make the edit, run the listed verification, and only advance once it passes. Tests must all pass at the end. Use `python -m pytest` from the project venv.

**Goal:** Apply the 12 quick-win correctness, security, and cleanup fixes identified in the 2026-04-20 code review. No feature additions, no refactors beyond what is listed.

**Architecture:** Point edits across 8 files in `/Users/bossoffice/gmail-unsubscriber/`. No new files. No new dependencies. Tests in `tests/` must continue to pass; add or update tests only where a task says so.

**Tech stack:** Python 3.10+, stdlib, existing deps (`google-api-python-client`, `google-auth-oauthlib`, `requests`, `beautifulsoup4`, `anthropic`, `openai`). Test runner: `pytest`.

**Ground rules for execution:**
- Never touch `credentials.json`, `token.json`, `gmail-unsubscriber.db`, or anything in `venv/`, `venv-py39-backup/`, `logs/`, `__pycache__/`, `.pytest_cache/`.
- Keep all user-visible Chinese strings in Chinese; keep all log strings in their current language.
- After each task, run `python -m pytest -q` — it must pass (or be no worse than baseline).
- Make one git commit per task with a clear message. Do NOT force-push, do NOT amend.
- If a task's verification fails and you cannot fix it cleanly in a second attempt, STOP and leave a note at the top of this file under `## Blockers` instead of silently skipping.

---

## Task 1: Tighten file permissions on token.json

**Files:** `auth.py`

**Why:** `token.json` contains a live Gmail OAuth refresh token with `gmail.modify` scope. Currently written with default umask (644 = world-readable). Must be 600.

- [ ] **Step 1:** In `auth.py`, replace lines 100–105 (the `with open(TOKEN_FILE, "w") as f: ...` block) with:

```python
        # 保存令牌到文件，下次免登录（权限 600，避免其他用户读取刷新令牌）
        try:
            fd = os.open(
                TOKEN_FILE,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(fd, "w") as f:
                f.write(creds.to_json())
            # 兜底：若文件已存在，os.open 不会改权限，显式修正一次
            os.chmod(TOKEN_FILE, 0o600)
            logger.debug(f"令牌已保存到 {TOKEN_FILE}")
        except IOError as e:
            logger.warning(f"保存令牌失败（不影响本次使用）：{e}")
```

- [ ] **Step 2:** Also in `auth.py`, right after the `CREDENTIALS_FILE` existence check succeeds (inside `authenticate()`, after line 56 but before the `creds = None` on line 58), add a best-effort chmod so `credentials.json` is also 600 on disk:

```python
    # 兜底：凭据文件若权限过宽则收紧为 0o600（不影响 Google 的使用）
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except OSError:
        pass
```

- [ ] **Step 3:** Verify:
  - `python -c "import ast; ast.parse(open('auth.py').read())"` → no output (syntax OK)
  - `python -m pytest tests/ -q` → passes
  - (Manual, not required for CI) After next auth run, `ls -l token.json credentials.json` shows `-rw-------`

- [ ] **Step 4:** Commit:
```bash
git add auth.py
git commit -m "sec: chmod 600 on token.json and credentials.json"
```

---

## Task 2: Tighten SQLite DB permissions

**Files:** `database.py`

**Why:** `gmail-unsubscriber.db` contains sender emails and scan history. Created 644 by SQLite default. Not secret but PII — make it 600.

- [ ] **Step 1:** In `database.py`, add `import os` next to the existing `import sqlite3` at the top. Then inside `init_db()`, after the `conn.close()` on line 50 and before `logger.debug(...)` on line 51, insert:

```python
    # 确保数据库文件权限为 0o600（包含扫描历史等 PII）
    try:
        os.chmod(config.DB_PATH, 0o600)
    except OSError:
        pass
```

- [ ] **Step 2:** Verify:
  - `python -c "import database; database.init_db()"` → no error
  - `ls -l gmail-unsubscriber.db` → `-rw-------`
  - `python -m pytest tests/ -q` → passes

- [ ] **Step 3:** Commit:
```bash
git add database.py
git commit -m "sec: chmod 600 on SQLite db after init"
```

---

## Task 3: Scanner — log exhausted retries + None-guard

**Files:** `scanner.py`

**Why:** `_fetch_messages_batch.fetch_one` silently drops messages after 3× 429/500/503 — user gets an under-count with no warning. Also `_retry_request` raises `last_error` without a None guard (future-proofing).

- [ ] **Step 1:** In `scanner.py`, change the inner `fetch_one` loop. After the `for attempt in range(MAX_RETRIES)` loop (line 174–199) finishes without `parsed` being set due to repeated retriable errors, add a WARNING log. Replace lines 171–199 with:

```python
    def fetch_one(stub):
        svc = _get_thread_service()
        parsed = None
        last_retriable_status: Optional[int] = None
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
                    last_retriable_status = e.resp.status
                    wait = RETRY_DELAY * (attempt + 1)
                    logger.debug(f"{e.resp.status} 错误，{wait}s 后重试（第 {attempt+1} 次）...")
                    time.sleep(wait)
                else:
                    logger.warning(f"获取邮件失败（{stub['id']}）：{e}")
                    break
            except (ssl.SSLError, ConnectionError, OSError) as e:
                last_retriable_status = -1
                wait = RETRY_DELAY * (attempt + 1)
                logger.debug(f"网络错误，{wait}s 后重试（第 {attempt+1} 次）：{e}")
                time.sleep(wait)
            except Exception as e:
                logger.warning(f"邮件解析失败（{stub['id']}）：{e}")
                break
        else:
            # for-else：未 break 说明所有 attempt 都用光了且最终无结果
            if parsed is None and last_retriable_status is not None:
                logger.warning(
                    f"邮件 {stub['id']} 重试 {MAX_RETRIES} 次仍失败（最后状态 "
                    f"{last_retriable_status}），已跳过"
                )
```

- [ ] **Step 2:** In `_retry_request` (line 46–65), guard against `last_error` being `None`. Replace the final `raise last_error` on line 65 with:

```python
    raise last_error if last_error else RuntimeError("重试请求失败但无错误信息")
```

- [ ] **Step 3:** Add a test that exhausted-retry is logged. Add to `tests/test_scanner.py` (create if it doesn't exist — check first):

```python
import logging
from unittest.mock import MagicMock, patch

import scanner


def test_fetch_one_logs_warning_when_retries_exhausted(caplog):
    """Verify a message whose API call 429s 3 times is reported, not silent."""
    fake_service = MagicMock()
    # users().messages().get().execute() always raises a 429 HttpError
    from googleapiclient.errors import HttpError

    class _Resp:
        status = 429
        reason = "rate"

    err = HttpError(_Resp(), b"rate limited")
    fake_service.users().messages().get.return_value.execute.side_effect = err

    with patch.object(scanner, "_get_thread_service", return_value=fake_service), \
         patch.object(scanner.time, "sleep", return_value=None), \
         caplog.at_level(logging.WARNING, logger="scanner"):
        result = scanner._fetch_messages_batch(
            fake_service, [{"id": "abc123"}], workers=1, request_sleep=0
        )

    assert result == []
    assert any("abc123" in r.message and "重试" in r.message for r in caplog.records)
```

- [ ] **Step 4:** Verify:
  - `python -m pytest tests/test_scanner.py -q` → passes
  - `python -m pytest -q` → passes

- [ ] **Step 5:** Commit:
```bash
git add scanner.py tests/test_scanner.py
git commit -m "scanner: log exhausted retries + None-guard _retry_request"
```

---

## Task 4: Classifier — fix `is_whitelisted` dead branch + drop unusable TLD tokens

**Files:** `classifier.py`, `config.py`

**Why:** `classifier.py:53` branch `"." not in white_domain and domain.endswith("." + white_domain)` is a strict subset of line 51 (always redundant). Worse, `WHITELIST_DOMAINS` includes bogus single-word entries (`"edu"`, `"utility"`, `"telecom"`) that either match nothing (since there's no leading dot) or produce bizarre false positives if subdomain happens to end with `.utility`. Delete the dead branch and the unusable entries; keep `edu.cn` and real domains.

- [ ] **Step 1:** In `classifier.py`, replace lines 47–55 with:

```python
    for white_domain in all_whitelist:
        white_domain = white_domain.lower().strip()
        if not white_domain:
            continue
        if domain == white_domain or domain.endswith("." + white_domain):
            return True

    return False
```

- [ ] **Step 2:** In `config.py`, edit `WHITELIST_DOMAINS` (lines 14–54). Remove the three bare tokens `"edu"` (line 46), `"utility"` (line 53), `"telecom"` (line 53). Keep everything else intact — `edu.cn`, `.gov.cn`, individual university domains stay. Do NOT reformat the rest of the list.

Before (lines 46 and 53 — context):
```python
    "edu", "edu.cn", "coursera.org", "edx.org", "khanacademy.org",
...
    "utility", "telecom",
```

After:
```python
    "edu.cn", "coursera.org", "edx.org", "khanacademy.org",
...
    # (line removing "utility", "telecom")
```

- [ ] **Step 3:** Add/extend a test in `tests/test_classifier.py` (create if missing):

```python
import classifier
import config


def test_is_whitelisted_exact_match(monkeypatch):
    monkeypatch.setattr(config, "get_all_whitelist_domains", lambda: ["google.com"])
    assert classifier.is_whitelisted("alice@google.com") is True


def test_is_whitelisted_subdomain(monkeypatch):
    monkeypatch.setattr(config, "get_all_whitelist_domains", lambda: ["google.com"])
    assert classifier.is_whitelisted("alice@mail.google.com") is True


def test_is_whitelisted_not_a_match(monkeypatch):
    monkeypatch.setattr(config, "get_all_whitelist_domains", lambda: ["google.com"])
    assert classifier.is_whitelisted("alice@evilgoogle.com") is False


def test_is_whitelisted_angle_brackets(monkeypatch):
    monkeypatch.setattr(config, "get_all_whitelist_domains", lambda: ["google.com"])
    assert classifier.is_whitelisted("<alice@google.com>") is True
```

- [ ] **Step 4:** Verify:
  - `python -m pytest tests/test_classifier.py -q` → passes
  - `python -m pytest -q` → passes

- [ ] **Step 5:** Commit:
```bash
git add classifier.py config.py tests/test_classifier.py
git commit -m "classifier: fix dead whitelist branch + drop unusable TLD tokens"
```

---

## Task 5: Rename misleading "skipped" label

**Files:** `main.py`

**Why:** `result["skipped"] = len(emails) - sum(g["count"] for g in result)` counts **any** email not flagged for unsubscribe, not just whitelist/sensitive hits. The label "白名单/敏感" misleads the user. Rename to the accurate "未建议退订".

- [ ] **Step 1:** In `main.py` line 179, change:

```python
    print(f"   已跳过邮件数（白名单/敏感）：{skipped}")
```

to:

```python
    print(f"   未建议退订的邮件数：{skipped}")
```

- [ ] **Step 2:** Verify:
  - `python -m pytest -q` → passes (no test expected to break)
  - `grep -n "白名单/敏感" main.py` → no matches

- [ ] **Step 3:** Commit:
```bash
git add main.py
git commit -m "ui: correct misleading 'skipped' label in scan summary"
```

---

## Task 6: Remove dead JSON whitelist code in config.py

**Files:** `config.py`

**Why:** `load_user_whitelist`, `save_user_whitelist`, `add_to_user_whitelist` (lines 123–163) + `USER_WHITELIST_FILE` (line 120) are a fallback path from the JSON era. Canonical storage is SQLite (`database.get_user_whitelist` / `add_to_user_whitelist`). `main.py:828` already calls `database.add_to_user_whitelist`, not `config.add_to_user_whitelist`. The DB-first path in `get_all_whitelist_domains` tries SQLite and only falls back to JSON on exception — SQLite init is idempotent at startup so the fallback is unreachable in practice.

- [ ] **Step 1:** In `config.py`, delete:
  - Line 120: `USER_WHITELIST_FILE = ...`
  - Lines 123–138: `load_user_whitelist`, `save_user_whitelist`
  - Lines 152–163: `add_to_user_whitelist`

- [ ] **Step 2:** Simplify `get_all_whitelist_domains` (lines 141–149) to just use the DB:

```python
def get_all_whitelist_domains() -> list[str]:
    """返回内置白名单 + 用户自定义白名单（SQLite）的合集。"""
    import database
    try:
        user_domains = database.get_user_whitelist()
    except Exception:
        user_domains = []
    return list(set(WHITELIST_DOMAINS + user_domains))
```

- [ ] **Step 3:** Remove the now-unused `import json` at line 7 of `config.py` (keep `import os` — still used by `DB_PATH`).

- [ ] **Step 4:** Search for any lingering references:
  - `grep -n "USER_WHITELIST_FILE\|load_user_whitelist\|save_user_whitelist\|config.add_to_user_whitelist" .` (project root, not venv/) → must be empty.

- [ ] **Step 5:** Verify:
  - `python -m pytest -q` → passes
  - `python -c "import config; print(config.get_all_whitelist_domains()[:3])"` → prints a list (no error)

- [ ] **Step 6:** Commit:
```bash
git add config.py
git commit -m "cleanup: drop dead JSON whitelist fallback, SQLite is canonical"
```

---

## Task 7: Drop stray imports & unused var

**Files:** `ai_classifier.py`, `main.py`, `classifier.py`

- [ ] **Step 1:** In `ai_classifier.py` line 11, delete `import os` (unused).
- [ ] **Step 2:** In `main.py`, delete the three duplicate `import argparse` statements inside helper functions at lines 626, 640, 646. `argparse` is already imported at module top (line 28).
- [ ] **Step 3:** In `classifier.py`, simplify `_extract_sender_tokens` (lines 152–162). `tokens` is already a subset of `expanded`. Replace the function body with:

```python
def _extract_sender_tokens(sender_display: str, sender_domain: str) -> set[str]:
    """将发件人名称和域名切成词元，避免 brand 名称里的子串误判。"""
    raw = f"{sender_display} {sender_domain}".lower()
    parts = re.findall(r"[\w\u4e00-\u9fff]+", raw)
    expanded = set(parts)
    for part in parts:
        expanded.update(p for p in re.split(r"[_\-.]+", part) if p)
    return expanded
```

- [ ] **Step 4:** Verify:
  - `python -c "import ai_classifier, main, classifier"` → no `NameError`
  - `python -m pytest -q` → passes

- [ ] **Step 5:** Commit:
```bash
git add ai_classifier.py main.py classifier.py
git commit -m "cleanup: drop unused import os, duplicate argparse imports, redundant token set"
```

---

## Task 8: Fix doc/help text mismatches

**Files:** `auth.py`, `main.py`

**Why:** `docs/USAGE.md` is a 3-line stub; real guide is `docs/USAGE_GUIDE.md`. And the CLI's `--no-ai` help still says "Claude AI" even though 9 providers are supported.

- [ ] **Step 1:** In `auth.py` line 54, change:

```python
            print("   请参考 docs/USAGE.md 中的「Google Cloud Console 配置步骤」")
```

to:

```python
            print("   请参考 docs/USAGE_GUIDE.md 中的「Google Cloud Console 配置步骤」")
```

- [ ] **Step 2:** In `main.py` lines 948 and 962, change both occurrences of:

```python
                             help="不使用 Claude AI 辅助判断")
```

to:

```python
                             help="不使用 AI 辅助判断")
```

(Exact indentation must match the existing argparse block — preserve trailing whitespace/commas.)

- [ ] **Step 3:** Verify:
  - `grep -n "Claude AI" main.py auth.py` → no results
  - `python main.py scan --help 2>&1 | grep -i "no-ai"` → shows "不使用 AI 辅助判断"
  - `python -m pytest -q` → passes

- [ ] **Step 4:** Commit:
```bash
git add auth.py main.py
git commit -m "docs: fix doc path reference and generalize AI help text"
```

---

## Task 9: Mask API keys in exception logs

**Files:** `ai_classifier.py`, `unsubscriber.py`

**Why:** Provider 401/403 responses sometimes echo the API key (or a long prefix). `logger.warning(f"... {e}")` persists that into `logs/*.log`. Cheap to mask.

- [ ] **Step 1:** Add a small helper at the top of `ai_classifier.py` (right after `logger = logging.getLogger(__name__)` on line 18):

```python
_SECRET_RE = re.compile(r"(?i)\b(sk|pk|api[_-]?key)[\w\-]{8,}")


def _mask_secrets(text: str) -> str:
    """Redact anything that looks like an API key / long secret in log strings."""
    return _SECRET_RE.sub("[REDACTED]", text)
```

(Note: `re` is already imported at line 12.)

- [ ] **Step 2:** In `ai_classifier.py`, update the three exception-log lines to mask the exception string before logging. Specifically:

- Line 221–222:
```python
    except json.JSONDecodeError as e:
        logger.warning(f"AI 返回格式解析失败：{_mask_secrets(str(e))}")
        return False, f"AI 返回格式解析失败：{e}"
```

- Line 223–225:
```python
    except Exception as e:
        logger.warning(f"AI 分类调用失败：{_mask_secrets(str(e))}")
        return False, f"AI 调用失败：{e}"
```

- Line 253–255 (`categorize_with_ai`):
```python
    except Exception as e:
        logger.warning(f"AI 分类调用失败：{_mask_secrets(str(e))}")
        return "其他"
```

Note: the returned tuple/string (shown to the user in the interactive menu) keeps the original `e` — we're only masking what goes to persistent log files.

- [ ] **Step 3:** In `unsubscriber.py`, the risky lines are `logger.error(f"发送退订邮件失败：{e}")` (line 151). The Gmail service error can echo tokens. Add a minimal inline mask:

```python
import re as _re  # (add near the top if not present; `re` already imported via unsubscriber.py:16)
```

Then in `unsubscribe_via_mailto`'s except block (line 150–152), replace with:

```python
    except Exception as e:
        safe = re.sub(r"(?i)\b(sk|pk|Bearer|access_token)[=:\s]\S+", "[REDACTED]", str(e))
        logger.error(f"发送退订邮件失败：{safe}")
        return {"success": False, "method": "mailto", "message": f"发送退订邮件失败：{e}"}
```

- [ ] **Step 4:** Add a test in `tests/test_ai_classifier.py` (create if missing):

```python
import ai_classifier


def test_mask_secrets_hides_api_key():
    text = "Unauthorized: key=sk-ant-abc1234567890xyz invalid"
    out = ai_classifier._mask_secrets(text)
    assert "sk-ant-abc1234567890xyz" not in out
    assert "[REDACTED]" in out


def test_mask_secrets_leaves_normal_text():
    assert ai_classifier._mask_secrets("simple error msg") == "simple error msg"
```

- [ ] **Step 5:** Verify:
  - `python -m pytest tests/test_ai_classifier.py -q` → passes
  - `python -m pytest -q` → passes

- [ ] **Step 6:** Commit:
```bash
git add ai_classifier.py unsubscriber.py tests/test_ai_classifier.py
git commit -m "sec: mask API key patterns in provider/mail exception logs"
```

---

## Task 10: Reject unsafe URL schemes in unsubscribe requests

**Files:** `unsubscriber.py`

**Why:** `unsubscribe_via_one_click`, the inline HTTP GET in `execute_unsubscribe`, and `unsubscribe_via_link` all pass email-derived URLs straight to `requests` with `allow_redirects=True`. A malicious `List-Unsubscribe` value or `<a href="...">` in email HTML can be `javascript:`, `file:`, `data:`, or anything else `requests` supports via adapters. Reject anything that's not `http://` or `https://` up-front; also reject the final response URL if a redirect chain landed on a non-http(s) scheme.

Scope note: full SSRF hardening (blocking private IPs) is a "bigger change" not in this plan.

- [ ] **Step 1:** Add a shared helper at the top of `unsubscriber.py` (after `DEFAULT_HEADERS` on line 45):

```python
_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _is_safe_http_url(url: str) -> bool:
    """True only if url is plain http(s). Blocks javascript:, file:, data:, ftp:, etc."""
    if not isinstance(url, str):
        return False
    url = url.strip().lower()
    return url.startswith(_ALLOWED_URL_SCHEMES)
```

- [ ] **Step 2:** At the top of `unsubscribe_via_one_click` (line 97), reject bad URLs before calling `requests.post`:

```python
def unsubscribe_via_one_click(url: str) -> dict:
    """向 URL 发送 POST 请求，执行 RFC 8058 一键退订。"""
    if not _is_safe_http_url(url):
        return {"success": False, "method": "one_click_post",
                "message": f"拒绝非 http(s) URL：{url[:80]}", "status_code": None}
    logger.info(f"尝试一键退订（POST）：{url}")
    ...
```

- [ ] **Step 3:** Inside `unsubscribe_via_link` (line 167), after `_find_unsubscribe_link` returns a URL, guard before the GET:

```python
    if not _is_safe_http_url(unsubscribe_url):
        return {"success": False, "method": "link_click",
                "message": f"拒绝非 http(s) 链接：{unsubscribe_url[:80]}",
                "found_url": unsubscribe_url, "status_code": None}
```

(Insert between lines 177 and 179, right before `logger.info(f"找到退订链接：...`.)

- [ ] **Step 4:** In `execute_unsubscribe`'s inline HTTP GET branch (lines 383–402), reject before calling `requests.get`:

```python
        if unsub_info["http_url"]:
            if not _is_safe_http_url(unsub_info["http_url"]):
                attempt = {
                    "success": False, "method": "http_get",
                    "message": f"拒绝非 http(s) URL：{unsub_info['http_url'][:80]}",
                    "status_code": None,
                }
                result["details"]["http"] = attempt
            else:
                has_one_click = list_unsub_post and "List-Unsubscribe=One-Click" in list_unsub_post
                ...
```

Keep the existing `if has_one_click:` branch body intact; just nest it inside the new `else`. Ensure indentation is preserved and `result["details"]["http"] = attempt` still runs on both paths.

- [ ] **Step 5:** Also reject dangerous `href` schemes during link extraction. In `_find_unsubscribe_link` line 252, the current check is:

```python
        if not (href.startswith("http://") or href.startswith("https://")):
            continue
```

This already rejects `mailto:`, `javascript:`, etc. — no change needed. But add a case-insensitive guard since HTML can say `HREF="JAVASCRIPT:..."`:

```python
        href_lower = href.lower()
        if not (href_lower.startswith("http://") or href_lower.startswith("https://")):
            continue
```

- [ ] **Step 6:** Add tests in `tests/test_unsubscriber.py` (create if missing):

```python
import unsubscriber


def test_is_safe_http_url_accepts_https():
    assert unsubscriber._is_safe_http_url("https://example.com/x") is True


def test_is_safe_http_url_accepts_http():
    assert unsubscriber._is_safe_http_url("http://example.com/x") is True


def test_is_safe_http_url_rejects_javascript():
    assert unsubscriber._is_safe_http_url("javascript:alert(1)") is False


def test_is_safe_http_url_rejects_file():
    assert unsubscriber._is_safe_http_url("file:///etc/passwd") is False


def test_is_safe_http_url_rejects_data():
    assert unsubscriber._is_safe_http_url("data:text/html,<script>") is False


def test_unsubscribe_via_one_click_rejects_javascript():
    result = unsubscriber.unsubscribe_via_one_click("javascript:alert(1)")
    assert result["success"] is False
    assert "拒绝" in result["message"]


def test_unsubscribe_via_link_rejects_javascript_anchor():
    html = '<a href="JAVASCRIPT:alert(1)">unsubscribe</a>'
    result = unsubscriber.unsubscribe_via_link(html)
    # The href filter drops it before it's even a candidate
    assert result["success"] is False
    assert "未在邮件正文中找到退订链接" in result["message"] or "拒绝" in result["message"]
```

- [ ] **Step 7:** Verify:
  - `python -m pytest tests/test_unsubscriber.py -q` → passes
  - `python -m pytest -q` → passes

- [ ] **Step 8:** Commit:
```bash
git add unsubscriber.py tests/test_unsubscriber.py
git commit -m "sec: reject non-http(s) unsubscribe URLs to prevent scheme abuse"
```

---

## Final Check

After all 10 tasks are committed:

- [ ] **Full test pass:** `python -m pytest -q` — every test green.
- [ ] **Import sanity:** `python -c "import auth, database, scanner, classifier, config, ai_classifier, unsubscriber, main"` — no errors.
- [ ] **CLI sanity:** `python main.py --help` runs without traceback.
- [ ] **Git log check:** `git log --oneline -10` shows ~10 small focused commits on top of the pre-plan HEAD. No commit touches more than its stated scope.
- [ ] **Leave status note:** Append a line to the TOP of this plan file:

```markdown
## Status

Completed 2026-04-20 by Codex. All 10 tasks passed verification.
```

(Or, if anything failed, document it under `## Blockers` as described in the ground rules.)
