# System Architecture

## Overall Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                  User (CLI / Interactive Menu)                   │
│    python main.py  ·  scan / unsubscribe / whitelist / history   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│  CLI parsing · interactive menu · logging init · scan cache ·    │
│                     workflow orchestration                       │
└──┬────────┬──────────┬──────────────────┬──────────────┬────────┘
   │        │          │                  │              │
   ▼        ▼          ▼                  ▼              ▼
┌─────┐ ┌────────┐ ┌───────────┐   ┌──────────────┐ ┌──────────┐
│auth │ │scanner │ │ classifier│   │ unsubscriber │ │ database │
│ .py │ │ .py    │ │  .py      │   │  .py         │ │  .py     │
│OAuth│ │3-thread│ │whitelist/ │   │3 unsubscribe │ │SQLite    │
│auth │ │concurr.│ │ad & sens. │   │methods: HTTP/│ │persist:  │
│     │ │+ retry │ │keyword    │   │mailto/body   │ │unsub'd + │
│     │ │Gmail API│ │+ AI assist│   │  link        │ │history   │
└──┬──┘ └───┬────┘ └─────┬─────┘   └──────┬───────┘ └────┬─────┘
   │        │            │                │              │
   │        │            ▼                │              │
   │        │   ┌─────────────────┐       │              │
   │        │   │ ai_classifier.py│       │              │
   │        │   │ 9-provider reg. │       │              │
   │        │   │ 2-layer cache   │       │              │
   │        │   └────────┬────────┘       │              │
   │        │            │                │              │
   │        ▼            ▼                ▼              │
   │     ┌─────────────────────────────────────┐         │
   └────▶│           config.py                 │◀────────┘
         │ whitelist/keywords/domain cats/     │
         │           USE_AI_CLASSIFIER         │
         └─────────────────────────────────────┘
```

## Data Flow

```
Gmail server
    │
    │ Gmail API (OAuth 2.0 auth)
    ▼
scanner.scan_emails()
    │ 3-thread concurrent metadata fetch, auto retry on 429/SSL
    │ database.is_already_unsubscribed() filters already-unsubscribed senders
    │ returns email list (subject/sender/headers/Gmail labels)
    ▼
classifier.classify_emails()
    │
    ├─ is_whitelisted()         → whitelisted domain  → skip
    ├─ is_sensitive()           → sensitive keyword   → skip
    ├─ is_advertisement()       → ≥ 2 criteria hit    → mark for unsubscribe
    └─ exactly 1 criterion hit  → ai_classifier.classify_with_ai()
                                  (called once per sender, cached in _ai_cache)
    │
    │ returns list grouped by sender
    ▼
classifier.categorize_groups()
    │ groups by domain (e-commerce/news/social/…)
    │ unknown domain → ai_classifier.categorize_with_ai()
    │                  (called once per domain, cached in domain_cat_cache)
    ▼
main._last_scan caches the result (reused by interactive menu)
    ▼
unsubscriber.execute_unsubscribe()
    │
    ├─ Method 1: List-Unsubscribe POST (RFC 8058 one-click unsubscribe)
    ├─ Method 2: List-Unsubscribe mailto (send unsubscribe email)
    └─ Method 3: parse HTML body, extract unsubscribe link, send GET request
    │
    ▼
database writes history · prints result · writes to log file
```

---

## Architecture Decisions

### Why use the Gmail API instead of reading email files directly?

Processing `.eml` files directly or reading email via IMAP requires storing account passwords, which is a security risk. The Gmail API uses OAuth 2.0 — it's like letting a courier into your home with a key that only opens one specific room (a token), rather than handing them your front door key. Tokens expire, so even if one leaks the damage is limited, and you can revoke them at any time from your Google account settings.

### Why use a "whitelist-first" strategy?

Bank verification codes, hospital appointment reminders, government notices… these emails must never be mistakenly unsubscribed. The whitelist acts as an "exempt lane": no matter how much an email looks like an ad, if the sender is on the whitelist, it passes through. Wrongly unsubscribing from one important email can have serious consequences (missing a payment reminder, losing a verification code); receiving a few more ads is just mildly annoying. Better to miss some ads than to harm an important email.

### Why does ad classification require "2 or more" criteria to match?

A single criterion is too easy to get wrong:
- Just "contains the word 'discount'" (e.g., `优惠` in Chinese) → banks also send "preferential rate" (`优惠利率`) notices
- Just "sender is noreply" → GitHub notifications are also from noreply
- Just "has List-Unsubscribe" → that's a legitimate email header

Multiple signals must appear together before we can be confident that an email is an ad. It's like deciding whether someone is a scammer — one suspicious point isn't enough; several signals need to stack up before you draw a conclusion.

### Why process by sender groups instead of email by email?

The same advertiser may have sent you 100 emails. A single unsubscribe action solves the whole problem — there's no need to send 100 unsubscribe requests to the same sender (which could actually trigger their anti-scraping defenses). Grouping by sender means one unsubscribe is enough, and the UI is clearer too — "unsubscribe from this sender" fits a user's mental model better than "unsubscribe from these 100 emails".

### Why prefer List-Unsubscribe over clicking links in the email body?

`List-Unsubscribe` is the standard email header defined in RFC 2369 and RFC 8058 — the sender's "official" unsubscribe mechanism. Reputable email service providers (Mailchimp, SendGrid, etc.) all support it, and it's typically idempotent (repeated requests give the same result). By comparison, unsubscribe links in the email body:
1. May simply be tracking links designed to identify "real users"
2. May redirect to a page that asks you to fill in a CAPTCHA
3. May be broken

So the priority order is: RFC 8058 POST → List-Unsubscribe HTTP → List-Unsubscribe mailto → body link.

### Why support 9 AI providers?

Different users have different needs: mainland Chinese users want low latency and low cost (MiniMax, DeepSeek, Qwen, Zhipu, Moonshot); users with international network access can pick OpenAI or Anthropic Claude; users running locally can use Ollama; and a custom endpoint serves as a fallback for any OpenAI-compatible service. `ai_classifier.py` maintains a `PROVIDERS` registry (9 entries), each recording the protocol type (`openai` or `anthropic`), default model, base_url, etc.; `_call_ai()` dispatches by protocol to the corresponding SDK, and adding a new provider only requires adding one row to the registry.

AI provider selection and API keys are no longer stored in `config.py` or environment variables. They're now kept in `user_config.json` (managed by `user_config.py`, already in `.gitignore`), configured through the interactive menu, with automatic migration from legacy environment variables on first launch.

MiniMax's M-series are reasoning models, and a response may contain only a `ThinkingBlock` without a standalone `TextBlock`. For this reason, `_extract_text_from_response()` has a fallback: it first looks for `text`, and if not found, it uses a regex to pull JSON out of `thinking`.

### Why cache AI decisions in two layers (sender + domain)?

The same advertiser may have hundreds of emails, and asking the AI about every one is both slow and expensive. The first layer, `_ai_cache`, keys on `sender_email` to cache "is this sender an advertiser?". The second layer, `domain_cat_cache`, keys on `sender_domain` to cache "what category does this domain belong to?". In testing, 10,000 emails typically trigger only tens to hundreds of AI calls — the vast majority hit the cache. Caches live only in process memory (valid for a single run) and are recomputed on the next run, so any misclassification isn't permanently locked in.

### Why scan with 3 concurrent threads rather than more?

The Gmail API has an implicit per-user concurrency limit, and exceeding it triggers 429 rate limiting. Three threads with a 0.15-second per-request interval work out to around 20 req/s, which testing shows to be the sweet spot for "fast and stable". Each thread keeps its own `Gmail service` object (via `thread_local`), avoiding SSL and connection-pool issues that come with cross-thread sharing. Metadata fetch failures retry automatically (429, 500, 503, SSL, network errors), so large scans complete even over unstable proxies.

### Why cache scan results in `_last_scan`?

In the interactive menu flow, users typically go "take a look → decide to unsubscribe" as two steps. Re-scanning on each step (especially across 14,000+ historical emails) would be a terrible experience. `main._last_scan` keeps the previous scan's classification results within a single run and reuses them by default when unsubscribing; users can also trigger a fresh scan manually. CLI mode (`scan` / `unsubscribe` as independent commands) retains its original behavior, so the two don't interfere.

### Why a dry-run mode?

To prevent mistakes. Just like running `SELECT` before actually deleting rows from a database, dry-run lets users see "what would happen if this ran" and confirm before actually doing it. It's especially important for non-technical users — run `--dry-run` first, check the results look reasonable, then re-run with `--confirm`.

### Why not just delete the emails?

Unsubscribing only tells the sender "stop sending me more"; it's not about cleaning up emails you've already received. Deleting emails is destructive and irreversible. If the program ever misjudges and deletes an important email, the user may lose important information. Unsubscribing only affects the future, not the past — the most conservative, safest strategy. Users who want to clean up existing ad emails can do so manually in the Gmail UI.

---

## Module Dependencies

```
main.py
 ├── auth.py            (get_gmail_service)
 ├── scanner.py         (scan_emails)
 │    ├── auth.py       (each thread gets its own service)
 │    └── database.py   (filter already-unsubscribed senders)
 ├── classifier.py      (classify_emails, categorize_groups)
 │    ├── config.py     (whitelist/keywords/domain category tables)
 │    └── ai_classifier.py (classify_with_ai, categorize_with_ai; PROVIDERS registry)
 │                      ├── config.py     (USE_AI_CLASSIFIER / AI_MAX_TOKENS)
 │                      └── user_config.py (active provider & API key)
 ├── unsubscriber.py    (execute_unsubscribe)
 │    └── (requests, beautifulsoup4 - third-party libs)
 ├── database.py        (SQLite: unsubscribed + history)
 ├── config.py          (whitelist command operates on it directly)
 └── user_config.py     (migrate_from_env on startup; _interactive_settings writes config)
```

There are no circular dependencies. `config.py` and `user_config.py` sit at the bottom (they depend on no other local modules), and both `ai_classifier.py` and `database.py` depend only on them, so they can be tested independently.

---

## Security Considerations

| Risk | Mitigation |
|------|------------|
| OAuth token leak | `token.json` is in `.gitignore`; on write it's `chmod 0o600`, readable/writable only by the current user |
| Mistakenly unsubscribing important emails | Whitelist + sensitive-keyword double protection + 2-criteria threshold |
| Ad link tracking | Use the List-Unsubscribe header (preferred) rather than body links |
| Malicious unsubscribe links (scheme abuse) | `unsubscriber._is_safe_http_url()` allows only `http://` / `https://`, rejects `javascript:` / `file:` / `data:` / `mailto:`, etc. |
| Account credential leak | `credentials.json` is in `.gitignore`; auto `chmod 0o600` on first load |
| Local database PII exposure | `gmail-unsubscriber.db` (containing scanned sender emails) is `chmod 0o600` after `init_db()` |
| Operational mistakes | `--dry-run` mode + `--confirm` one-by-one confirmation mode |
| Rate limiting | Both scanner and unsubscriber use request intervals and retry logic (429/500/503/SSL/network errors with exponential backoff); if a single email still fails after 3 retries, a WARNING is logged rather than being silently skipped |
| AI API key leak | Stored in `user_config.json` (already in `.gitignore`), never written into the codebase; displayed with masking (first 6 + last 6 chars); `sk-...` / `pk-...` / `Bearer ...` etc. in exception logs are replaced with `[REDACTED]` by `_mask_secrets()` |
| AI endpoint leaking email content | Only sender, subject, and snippet are sent — the email body is never transmitted |
