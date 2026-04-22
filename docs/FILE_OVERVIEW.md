# File Reference

This document walks through every Python file in the project, covering its responsibilities, core functions, and dependencies.

---

## `config.py` — Configuration Center

**Responsibility:** Holds all "hard-coded" configuration data, along with utility functions for dynamically modifying the user whitelist. Centralizing configuration in one place means you don't have to dig through every source file when making changes.

**Key data:**

| Variable | Type | Description |
|----------|------|-------------|
| `WHITELIST_DOMAINS` | `list[str]` | Built-in whitelist domains (100+ common organizations) |
| `AD_KEYWORDS` | `list[str]` | Ad keywords (30+ each in Chinese and English) |
| `SENSITIVE_KEYWORDS` | `list[str]` | Sensitive keywords (verification codes / orders / bills, etc.) |
| `SUSPICIOUS_SENDER_KEYWORDS` | `list[str]` | Suspicious sender keywords (noreply / newsletter, etc.) |
| `DOMAIN_TO_CATEGORY` | `dict[str, str]` | Domain-to-category mapping (for categorized display) |
| `CATEGORY_NAMES` | `list[str]` | All available categories (shopping / social / news, etc.) |
| `USE_AI_CLASSIFIER` | `bool` | Master switch for AI-assisted classification (AI provider choice and API key have been moved to `user_config.json`) |
| `AI_MAX_TOKENS` | `int` | Max token limit for AI calls |

**Key functions:**

| Function | Description |
|----------|-------------|
| `get_all_whitelist_domains()` | Returns the union of the built-in whitelist and the user-defined whitelist (SQLite) |

CRUD operations for the user-defined whitelist are handled by `database.py` (`add_to_user_whitelist`, `get_user_whitelist`). `config.py` only does one thing: merging the two sources into a single list.

**Called by:**
- `classifier.py` calls `get_all_whitelist_domains()`, `AD_KEYWORDS`, `SENSITIVE_KEYWORDS`, `SUSPICIOUS_SENDER_KEYWORDS`
- `main.py`'s `cmd_whitelist` calls `database.add_to_user_whitelist()` / `database.get_user_whitelist()`; it only uses `config.WHITELIST_DOMAINS` / `config.get_all_whitelist_domains()` for printing output

**Dependencies:**
- Standard library: `os`
- Lazy-loads `database` at runtime (to avoid circular dependencies between low-level modules)

---

## `auth.py` — Authentication

**Responsibility:** Handles everything related to Google OAuth 2.0. Think of it as a gatekeeper: it proves to Google that "I am the legitimate owner of this account," obtains a pass (access token), and hands that pass to the rest of the modules.

**Key functions:**

| Function | Description |
|----------|-------------|
| `authenticate()` | Runs the OAuth flow and returns a `Credentials` object |
| `get_gmail_service()` | Calls `authenticate()` and returns a Gmail API service object |

**Internal flow of `authenticate()`:**
1. Check whether `credentials.json` exists; if not, print an exit prompt (pointing at `docs/USAGE_GUIDE.md`)
2. On first load, defensively tighten `credentials.json` permissions to `0o600`
3. Check whether `token.json` exists; load it if it does
4. If the token is still valid, return immediately
5. If the token is expired but a refresh token exists, refresh automatically
6. If no valid token is available, launch the browser authorization flow (`InstalledAppFlow`)
7. On successful authorization, write `token.json` using `os.open(..., O_CREAT|O_WRONLY|O_TRUNC, 0o600)`, then follow up with `os.chmod(..., 0o600)` as a defensive fallback

**Called by:**
- `main.py` calls `get_gmail_service()` at the start of every command that needs Gmail access
- The returned `service` object is passed into `scanner.scan_emails(service, ...)`

**Dependencies:**
- `google-auth`: `google.oauth2.credentials.Credentials`, `google.auth.transport.requests.Request`
- `google-auth-oauthlib`: `InstalledAppFlow`
- `google-api-python-client`: `build`

**Important constants:**
```python
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
# modify scope: can read and change labels, but cannot permanently delete emails
```

---

## `scanner.py` — Email Scanner

**Responsibility:** Talks to the Gmail API — fetches email metadata in concurrent batches and parses it into structured data. Picture a team of three library assistants who each pull books off the shelf, open the covers (parse headers), and file tidy records for downstream modules to consume. Network hiccups are retried automatically, so the scan doesn't crash mid-way.

**Key functions:**

| Function | Description |
|----------|-------------|
| `scan_emails(service, days=30, scan_all=False)` | Main entry point: scans emails, filters out already-unsubscribed senders, and returns an email list. `days=0` means scan all history; `scan_all=True` means scan every Gmail category |
| `_fetch_messages_batch(service, stubs)` | Fetches email metadata across 3 concurrent threads, with built-in retries (internal) |
| `_get_thread_service()` | Each thread keeps its own Gmail service object (thread-local) |
| `_list_all_messages(service, query)` | Paginates through the message ID list (internal) |
| `_parse_message(msg)` | Parses a raw API object into a structured dict (internal) |
| `_parse_sender(sender_raw)` | Extracts the email address and domain from the "Name <email>" format (internal) |
| `_retry_request(func, ...)` | Generic retry wrapper that handles 429 / 500 / 503 / SSL / network errors |

**Concurrency and resilience:**
- Concurrent workers: `CONCURRENT_WORKERS = 3`, per-request delay: `REQUEST_SLEEP = 0.15s`, resulting in roughly 20 req/s
- Prints a progress update every 50 emails
- Automatic exponential backoff on: 429 (rate limit), 500 / 503 (server errors), `ssl.SSLError` / `ConnectionError` / `OSError` (network flakiness)
- If a single message still fails after `MAX_RETRIES = 3` attempts, a WARNING log is written (with the message ID and last status code) so emails are never silently dropped

**Already-unsubscribed filtering:** After parsing, `database.is_already_unsubscribed(sender_email)` is called for each email — matches are filtered out to avoid reprocessing.

**Return structure (per email):**
```python
{
    "id": "邮件ID",
    "subject": "主题",
    "sender": "Google <noreply@google.com>",
    "sender_email": "noreply@google.com",
    "sender_domain": "google.com",
    "date": "日期字符串",
    "list_unsubscribe": "<https://...>, <mailto:...>",  # may be None
    "list_unsubscribe_post": "List-Unsubscribe=One-Click",  # may be None
    "snippet": "邮件摘要前200字...",
    "body_text": "",   # metadata format does not include body; fetched on demand during unsubscribe
    "body_html": "",   # see unsubscriber._fetch_html_body()
    "labels": ["INBOX", "CATEGORY_PROMOTIONS"],
}
```

**Called by:**
- `main.py`'s `cmd_scan()`, `cmd_unsubscribe()`, and interactive menu all call `scan_emails()`

**Dependencies:**
- `google-api-python-client`: `HttpError`
- Local modules: `auth` (for the service), `database` (to filter already-unsubscribed senders)
- Standard library: `ssl`, `threading`, `concurrent.futures`, `logging`, `time`, `datetime`

---

## `classifier.py` — Email Classifier

**Responsibility:** Takes the parsed emails from `scanner` and decides "should this email be unsubscribed from?" Think of an experienced mail review officer who walks through a strict rule set and renders a well-reasoned verdict on each message.

**Decision flow (highest to lowest priority):**
```
Whitelisted domain?        → Never unsubscribe (highest priority)
     ↓ no
Contains sensitive word?   → Never unsubscribe (protect important emails)
     ↓ no
Matches 2+ ad conditions?  → Recommend unsubscribe
     ↓ no
Matches exactly 1?         → Delegate to AI (same-sender cache, one call only)
     ↓ AI says not an ad, or AI is disabled
Default                    → Do not unsubscribe (conservative)
```

**Key functions:**

| Function | Signature | Description |
|----------|-----------|-------------|
| `is_whitelisted(sender)` | `str → bool` | Check whether the sender is on the whitelist |
| `is_sensitive(email_data)` | `dict → bool` | Check whether the email contains sensitive words |
| `is_advertisement(email_data)` | `dict → (bool, list[str])` | Ad detection; returns the verdict plus the list of matched conditions |
| `should_unsubscribe(email_data, use_ai=True)` | `dict → (bool, str)` | Final decision; calls AI when exactly 1 condition matches |
| `classify_emails(emails, use_ai=True)` | `list[dict] → dict` | Batch classification, grouped by sender |
| `categorize_groups(groups, use_ai=True)` | `list[dict] → dict[str, list[dict]]` | Groups by email category (shopping / news / social / ...); calls AI for unknown domains |

**Two-layer AI cache (key optimization):**
- `_ai_cache: dict[str, tuple[bool, str]]` — caches "is this an ad?" by sender email; used by `should_unsubscribe`
- `domain_cat_cache: dict[str, str]` — caches category results by domain; used internally by `categorize_groups`
- The caches live only for the current process run, preventing any misclassification from becoming permanent

**The five conditions in `is_advertisement()`:**
1. Subject or body contains a keyword from `AD_KEYWORDS`
2. Sender name or address contains a keyword from `SUSPICIOUS_SENDER_KEYWORDS`
3. The email has a `List-Unsubscribe` header
4. Gmail automatically tagged it with `CATEGORY_PROMOTIONS`
5. Sender uses a `noreply` / `no-reply` style address

**`classify_emails()` return structure:**
```python
{
    "to_unsubscribe": [
        {
            "sender_email": "promo@shop.com",
            "sender": "某购物平台 <promo@shop.com>",
            "count": 15,          # number of emails from this sender
            "reasons": ["命中广告特征：含广告关键词；含 List-Unsubscribe 头部"],
            "sample_subjects": ["周年庆大促！", "限时折扣"],
            "list_unsubscribe": "<https://...>",
            "sample_html": "<html>...",  # HTML sample used for unsubscribe
        },
        ...
    ],
    "skipped": 120,  # emails not recommended for unsubscribe (whitelisted, sensitive, non-ad, etc.)
}
```

**Called by:**
- `main.py`'s `cmd_scan()`, `cmd_unsubscribe()`, and interactive menu call `classify_emails()` + `categorize_groups()`

**Dependencies:**
- Local modules: `config` (for whitelist and keywords), `ai_classifier` (for AI-assisted decisions)
- Standard library: `logging`, `re`

---

## `user_config.py` — User Configuration Persistence

**Responsibility:** User configuration persistence module. Stores the AI provider selection and API key in `user_config.json`. Exposes `load` / `save` / `get_active_provider` / `set_active_provider` / `mask_key` / `migrate_from_env`.

**Key functions:**

| Function | Description |
|----------|-------------|
| `load()` | Load the configuration from `user_config.json`; return empty defaults if the file doesn't exist |
| `save(config)` | Write the configuration to `user_config.json` |
| `get_active_provider()` | Return the currently active provider ID and its configuration dict |
| `set_active_provider(provider_id, api_key, model, base_url)` | Update the active provider and persist |
| `mask_key(key)` | Mask the API key for display (first 6 chars + `****` + last 6 chars) |
| `migrate_from_env()` | Migrate from legacy environment variables (`MINIMAX_API_KEY` / `ANTHROPIC_API_KEY` / `AI_PROVIDER`) into `user_config.json`; skip if already migrated |

**Called by:**
- `main.py` calls `migrate_from_env()` on startup
- `main._configure_ai_provider()` / `_show_current_ai_config()` call `set_active_provider()` / `get_active_provider()` / `mask_key()`
- `ai_classifier._check_ai_available()` / `_call_ai()` read the active provider configuration

**Dependencies:**
- Standard library: `json`, `os`
- No dependencies on other local modules (lowest layer)

---

## `ai_classifier.py` — AI-Assisted Decisions

**Responsibility:** Encapsulates the details of AI calls and exposes two capabilities to the outside world: "is this an ad?" and "what category does this belong to?" Ships with a `PROVIDERS` registry (9 providers) and dispatches requests by protocol (`openai` / `anthropic`), shielding `classifier.py` from provider-specific differences.

**`PROVIDERS` registry (9 providers):**

openai, anthropic, minimax, deepseek, moonshot, qwen, zhipu, ollama, custom. Each entry contains a protocol type, default model, and base_url (optional).

**Key functions:**

| Function | Description |
|----------|-------------|
| `test_connection(provider_id, api_key, model, base_url)` | Send a minimal prompt to probe whether the credentials work; returns `(success, message)` |
| `classify_with_ai(sender, subject, snippet)` | Determine whether an email is an ad; returns `(is_ad, reason)` |
| `categorize_with_ai(sender, subject)` | Determine which category the sender belongs to; returns a category name |
| `_call_ai(prompt)` | Dispatch to the OpenAI SDK / Anthropic SDK based on the active provider's protocol (internal) |
| `_extract_text_from_response(message)` | Pull text out of the response; handles reasoning models that only return a `ThinkingBlock` (internal) |
| `_parse_json_response(text)` | Tolerant JSON parsing; supports using a regex to extract JSON from chain-of-thought output (internal) |
| `_check_ai_available()` | Check whether AI is usable (master switch + active provider configuration) (internal) |

**Notable details:**
- **ThinkingBlock compatibility:** MiniMax's M-series are reasoning models whose responses may only contain a `ThinkingBlock` with no `TextBlock`. `_extract_text_from_response` falls back to the `thinking` field.
- **max_tokens:** MiniMax calls are forced to at least 1024 tokens to prevent reasoning content from being truncated.
- **Tolerant JSON parsing:** First try `json.loads`; if that fails, use the regex `\{[^{}]+\}` to find JSON inside the text.

**Called by:**
- `classifier.should_unsubscribe()` calls `classify_with_ai()` when exactly 1 ad condition matches
- `classifier.categorize_groups()` calls `categorize_with_ai()` for unknown domains
- `main._configure_ai_provider()` calls `test_connection()` to verify credentials

**Dependencies:**
- `anthropic` (Python SDK; also compatible with MiniMax's Anthropic-style endpoint)
- `openai` (Python SDK; for OpenAI-compatible providers)
- Local modules: `config` (`USE_AI_CLASSIFIER` / `AI_MAX_TOKENS`), `user_config` (active provider & key)
- Standard library: `json`, `logging`, `re`

**Log redaction:** In exception branches, `logger.warning(...)` runs the module-local `_mask_secrets()` over the message, using regex to redact long strings like `sk-...` / `pk-...` / `api_key...` (replaced with `[REDACTED]`), so API keys never accidentally end up in `logs/*.log`.

---

## `database.py` — Unsubscribe History and Persistence

**Responsibility:** Keeps a local SQLite ledger — who has been unsubscribed, when, and whether it succeeded. Like a sign-in sheet for every unsubscribe action: the next scan automatically skips senders already handled, so we don't pester the same party twice.

**Storage:**
- File location: `gmail-unsubscriber.db` at the project root (SQLite)
- Not committed to git (listed in `.gitignore`)
- `init_db()` runs `os.chmod(DB_PATH, 0o600)` at the end, so the list of scanned senders (PII) isn't readable by other local users

**Key functions:**

| Function | Description |
|----------|-------------|
| `init_db()` | Initialize the database and schema (auto-created on first run) |
| `record_unsubscribe(sender_email, sender, method, success, message)` | Record a single unsubscribe attempt |
| `is_already_unsubscribed(sender_email)` | Check whether this sender has already been successfully unsubscribed (used for scan-time filtering) |
| `get_history(limit=50)` | Query recent unsubscribe history |

**Called by:**
- `scanner.scan_emails()` calls `is_already_unsubscribed()` to filter the email list
- `unsubscriber.execute_unsubscribe()` calls `record_unsubscribe()` after a successful attempt
- `main.cmd_history()` and the interactive menu call `get_history()`

**Dependencies:**
- Standard library: `sqlite3`, `logging`, `datetime`

---

## `unsubscriber.py` — Unsubscribe Executor

**Responsibility:** Actually performs the unsubscribe action. Like an agent acting on your authorization, it contacts each sender through different methods and says "please remove me from your mailing list."

**Three unsubscribe methods (by priority):**

```
Method 1: One-click unsubscribe (RFC 8058)
          Send a POST request to the URL in List-Unsubscribe
          {"List-Unsubscribe": "One-Click"}
          ↓ on failure, try
Method 2: HTTP GET
          Send a GET request to the URL (simulating a browser click)
          ↓ if no HTTP URL, try mailto
Method 2.5: mailto unsubscribe
          Parse the mailto address and subject, prompt the user to send manually
          ↓ if no List-Unsubscribe, try
Method 3: Body link unsubscribe
          Find an <a> element whose text contains unsubscribe keywords in the HTML, send a GET request
```

**Key functions:**

| Function | Description |
|----------|-------------|
| `get_list_unsubscribe_url(headers_or_value)` | Parse the List-Unsubscribe header and extract the HTTP URL and mailto |
| `unsubscribe_via_one_click(url)` | Send an RFC 8058 POST request for one-click unsubscribe (runs `_is_safe_http_url` first) |
| `unsubscribe_via_mailto(mailto_info)` | Send the unsubscribe email via the Gmail API; exception logs redact `sk-*` / `Bearer`, etc. |
| `unsubscribe_via_link(html_body)` | Extract the unsubscribe link from the HTML body and send a GET request (also checks the scheme) |
| `execute_unsubscribe(sender_group, dry_run)` | Unified entry point; tries each method in priority order |
| `_find_unsubscribe_link(html_body)` | Extract the most likely unsubscribe link from the HTML (only accepts `http(s)` `href`s) |
| `_is_safe_http_url(url)` | URL scheme allowlist: only `http://` / `https://` pass; others (`javascript:` / `file:` / `data:` / `mailto:`, etc.) are rejected |

**`execute_unsubscribe()` return structure:**
```python
{
    "sender_email": "promo@shop.com",
    "sender": "某购物平台 <promo@shop.com>",
    "dry_run": False,
    "attempted_method": "one_click_post",  # method actually used
    "success": True,
    "message": "一键退订请求已发送（HTTP 200）",
    "details": {
        "http": {"success": True, "method": "one_click_post", ...},
    }
}
```

**Called by:**
- `main.py`'s `cmd_unsubscribe()` calls `execute_unsubscribe()`

**Dependencies:**
- `requests`: HTTP calls
- `beautifulsoup4` + `lxml`: HTML parsing for link extraction
- Standard library: `logging`, `re`, `time`, `urllib.parse`

---

## `main.py` — Main Entry Point, CLI, and Interactive Menu

**Responsibility:** The conductor. Two entry paths: command-line argument mode (for power users / scripts) and interactive menu mode (for newcomers). Orchestrates the other modules to get work done, then presents the results in a friendly way.

**Two usage modes:**

```
Without arguments    python3 main.py                 → launch the interactive menu
With arguments       python3 main.py scan ...        → CLI mode
```

**CLI command list:**

| Command | Function | Description |
|---------|----------|-------------|
| `scan [--days N] [--all] [--no-ai]` | `cmd_scan()` | Scan emails and show the classification report |
| `unsubscribe --dry-run` | `cmd_unsubscribe()` | Dry run: preview what would be unsubscribed without acting |
| `unsubscribe --confirm [--auto] [--archive]` | `cmd_unsubscribe()` | Per-item confirm / auto-confirm / archive after unsubscribe |
| `history [--limit N]` | `cmd_history()` | View unsubscribe history |
| `whitelist add <domain>` / `whitelist list` | `cmd_whitelist()` | Manage the user whitelist |
| `logs` | `cmd_logs()` | View runtime logs |

**Interactive menu commands (`interactive_menu()`):**

```
1. Scan emails          → _interactive_scan()
2. Run unsubscribe      → _interactive_unsubscribe() (reuses the last scan result)
3. View history         → _interactive_history()
4. Manage whitelist     → _interactive_whitelist()
5. Settings             → _interactive_settings()
   ├── 1. Configure AI provider  → _configure_ai_provider() (pick provider → enter key → test_connection → save)
   └── 2. Show current config    → _show_current_ai_config() (key is masked)
0. Exit
```

**Scan-result cache:** The module-level variable `_last_scan = {"categorized": ..., "to_unsub": ..., "total": ..., "days": ...}` stores the last scan result. After "Scan emails" runs in the menu, a ✅ marker appears to indicate a cache is available. Picking option 2 reuses it by default, with an option to rescan.

**Key functions:**

| Function | Description |
|----------|-------------|
| `setup_logging(verbose)` | Initialize the logging system (dual output: file + console) |
| `interactive_menu()` | Main loop for the interactive menu |
| `_do_scan_and_classify(days, scan_all, use_ai)` | Reusable scan + classify + categorize pipeline |
| `cmd_scan(args)` / `cmd_unsubscribe(args)` / `cmd_whitelist(args)` / `cmd_history(args)` / `cmd_logs(args)` | CLI command handlers |
| `parse_selection(user_input, total)` | Parse user input (supports `1,3,5-8` syntax) |
| `format_category_summary(categorized)` | Format the category summary |
| `build_parser()` | Build the argparse command-line parser |
| `main()` | Program entry point |

**Logging strategy:**
- File logs (`logs/gmail-unsubscriber-YYYYMMDD.log`): capture DEBUG level and above (everything)
- Console logs: WARNING and above only (unless `--verbose` is set)
- Rationale: users only need the key takeaways; detailed debug info is archived for later review

**Startup behavior:** `main()` calls `user_config.migrate_from_env()` before any command runs, silently migrating legacy environment-variable configs into `user_config.json`.

**Dependencies:**
- Local modules: `auth`, `scanner`, `classifier`, `unsubscriber`, `config`, `database`, `user_config` (all of them)
- Standard library: `argparse`, `logging`, `os`, `sys`, `datetime`
