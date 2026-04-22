# Gmail Smart Unsubscriber · User Guide

> A tool that automatically cleans up promotional email subscriptions in your Gmail inbox. Safe, reliable, and remembers what it's done.

---

## Table of Contents

1. [What this tool does](#1-what-this-tool-does)
2. [First-time setup (one time only)](#2-first-time-setup-one-time-only)
3. [Understanding the two core commands](#3-understanding-the-two-core-commands)
4. [Recommended workflow](#4-recommended-workflow)
5. [All commands explained](#5-all-commands-explained)
6. [Whitelist management](#6-whitelist-management)
7. [Other commands](#7-other-commands)
8. [FAQ](#8-faq)
9. [AI assistance (optional)](#9-ai-assistance-optional)
10. [Security notes](#10-security-notes)

---

## 1. What this tool does

- **Scan**: Automatically analyzes promotional/marketing emails in your Gmail and lists unsubscribe candidates
- **Unsubscribe**: Automatically sends unsubscribe requests (tries three methods in order)
- **Label**: After a successful unsubscribe, tags the email with an "Unsubscribed" label in Gmail
- **Archive**: Optionally moves old promo emails from successful unsubscribes out of the inbox (does not delete)
- **Memory**: Remembers senders you've already unsubscribed from, so it won't process them again
- **AI assist**: When an email is ambiguous, AI helps make the call (supports 9 providers, configured via menu)

**What it will never do:**
- Never deletes any email
- Never touches whitelisted senders (banks, Google, government, etc.)

---

## 2. First-time setup (one time only)

> **Cross-platform note**: This tool is pure Python and **runs on Mac / Linux / Windows / WSL2**. Commands in this doc default to Mac/Linux syntax — Windows native users should check the "Windows adaptation" subsection below.

### Step 1: Install dependencies

```bash
cd /path/to/gmail-unsubscriber   # change to the actual project path
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # only needed if you want to run tests
```

> **Python version**: Please use **Python 3.10 or higher** if possible. The project may still work on older versions, but Google's dependencies have already posted end-of-regular-support notices for Python 3.9.

> Every time you open a new terminal window, you need to re-run `source venv/bin/activate` to activate the environment (you'll see `(venv)` appear at the start of your prompt).

#### 🪟 Windows adaptation

Windows native (PowerShell / CMD) commands differ slightly from Mac:

| Action | Mac / Linux / WSL2 | Windows native |
|------|-------------------|-------------|
| Activate virtualenv | `source venv/bin/activate` | `venv\Scripts\activate` |
| Set env var (temporary) | `export KEY=value` | `set KEY=value` (CMD)<br>`$env:KEY="value"` (PowerShell) |
| Set env var (permanent) | add to `~/.zshrc` or `~/.bashrc` | System Properties → Environment Variables, or PowerShell's `$PROFILE` |
| Path separator | `/` | `\` (Python code accepts both; use `\` on the command line) |

All other commands (`python3 main.py ...`) are identical. If you installed the official Python 3.x build, your command may be `python` instead of `python3` — just substitute whichever one you have.

#### 🐧 WSL2 users (recommended for Windows users)

WSL2 (Windows Subsystem for Linux 2) is essentially Ubuntu running inside Windows, so **commands are identical to Mac/Linux** — you don't have to remember two sets of syntax. We recommend this path for Windows users; it's the closest experience to Mac.

One-time setup inside WSL2:

```bash
# After entering your WSL2 terminal
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
cd ~                             # or wherever you want the project
git clone <this project repo URL> gmail-unsubscriber
cd gmail-unsubscriber
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Small WSL2 gotcha with OAuth browser auth**: WSL2 has no GUI, so during first-time auth the program will print a `http://localhost:xxxxx/?code=...` link. Copy that link into your Windows browser to complete authorization. Modern WSL2 (Windows 11 + latest version) already supports auto-launching the Windows browser, so most of the time it pops up on its own.

**WSL2 file paths**: Put the project inside the WSL2 filesystem (e.g. `~/gmail-unsubscriber`) — **do not put it under `/mnt/c/...`** (the Windows drive mount path), otherwise Python's read/write performance will fall off a cliff.

### Step 2: Get Google API credentials

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (any name, e.g. "Gmail Unsubscriber")
3. Left menu → **APIs & Services** → **Enable APIs and Services** → search for and enable **Gmail API**
4. Left menu → **Credentials** → **Create Credentials** → **OAuth Client ID**
5. Choose **Desktop app** as the application type, then click download
6. Rename the downloaded file to `credentials.json` and place it in the project root

```
gmail-unsubscriber/
├── credentials.json   ← put it here
├── main.py
└── ...
```

> ⚠️ `credentials.json` is the credential used to access Google services — never upload it to GitHub or share it with anyone. This file is already in `.gitignore`.

### Step 3: First-time OAuth authorization

The first time you run any command, the program will automatically open a browser and ask for authorization:

```bash
python3 main.py scan
```

1. Choose your Google account in the browser
2. When you see the "This app isn't verified by Google" warning: click **Advanced** → **Go to (unsafe)**
3. Check all permissions and click **Continue**
4. Once the browser shows authorization complete, return to your terminal

**Authorization only needs to be done once**; afterwards the saved `token.json` is used automatically.

---

## 3. Understanding the two core commands

This is the key to understanding the tool:

| Command | What it does | When to use |
|------|--------|---------------|
| `scan` | **Scan only, no unsubscribe**. Lists senders suggested for unsubscribing for your review | When you want to see what promo senders exist before deciding whether to unsubscribe |
| `unsubscribe` | **Scan + unsubscribe**. Internally does one scan first, then runs the unsubscribe | When you want to unsubscribe directly |

**CLI mode**: `scan` and `unsubscribe` each run their own scans independently. The value of `scan` is letting you **preview beforehand** so you can whitelist any domains you don't want to unsubscribe from, and then run `unsubscribe`.

**Interactive menu mode** (`python3 main.py` with no arguments): scan results are **cached automatically** for the current session. If you pick 1 (scan) in the menu and then 2 (unsubscribe), the program reuses the last scan result instead of re-scanning; you can also choose to re-scan. A ✅ next to "Scan email" in the menu means there's a cached result.

---

## 4. Recommended workflow

### First deep cleanup (suggested order)

```bash
# Step 1: activate the virtualenv
source venv/bin/activate

# Step 2: scan to see which promo senders exist
# Start with "all promotional emails in history" rather than scanning the whole inbox
python3 main.py scan --days 0

# Step 3: if the results include senders you don't want to unsubscribe from, whitelist their domains
python3 main.py whitelist add somecompany.com

# Step 4: dry-run the unsubscribe to see exactly what the program plans to do (no requests actually sent)
python3 main.py unsubscribe --dry-run --days 0

# Step 5: once it looks right, run the real unsubscribe (asks you one by one)
python3 main.py unsubscribe --confirm --days 0
```

### Full-history inbox sweep (sample first, then decide whether to go full)

```bash
# Start with a 500-message sample to check if the results look reasonable
python3 main.py scan --days 0 --all --max-messages 500 --no-ai

# Without --max-messages, the program still defaults to a 2000-message guard
python3 main.py scan --days 0 --all --no-ai

# Only use --full-scan when you're sure you want to sweep the entire inbox
python3 main.py scan --days 0 --all --full-scan --no-ai
```

> **Important**: `--all` expands the scan from "the Promotions tab" to "all received mail" (still excluding Sent, Drafts, Trash, and Spam by default), and it's noticeably slower. Always sample with `--max-messages` first.

### Routine maintenance (monthly, quick scan of the last 30 days)

```bash
source venv/bin/activate
python3 main.py unsubscribe --confirm --days 30
```

### Running tests (recommended after any code changes)

```bash
source venv/bin/activate
python -m pytest
```

If you see `No module named pytest`, it usually means you haven't installed the test dependencies, or you haven't activated the project's `venv`.

---

## 5. All commands explained

### `scan` — scan emails (look only, no unsubscribe)

```bash
python3 main.py scan [options]
```

| Option | Description | Default |
|------|------|--------|
| `--days N` | Scan the last N days; `0` means unlimited, scan all history | 30 days |
| `--all` | Scan all categories (default is only the Gmail Promotions tab) | off |
| `--max-messages N` | Process at most the first N messages; good for large-sample sanity checks | unlimited |
| `--full-scan` | With `--days 0 --all`, disables the default guard limit and runs a full scan | off |
| `--no-ai` | Don't use AI assistance, rule-based keywords only | AI on |

**Examples:**
```bash
python3 main.py scan                          # scan promo emails from the last 30 days
python3 main.py scan --days 90               # scan promo emails from the last 3 months
python3 main.py scan --days 0                # scan all historical promo emails
python3 main.py scan --days 0 --all          # scan all historical mail (default guard of 2000 messages)
python3 main.py scan --days 0 --all --max-messages 500
python3 main.py scan --days 0 --all --full-scan
python3 main.py scan --no-ai                 # no AI, rules only
```

**About the default guard for `--days 0 --all`:**
- If you don't pass `--max-messages`, the program processes only the first `2000` messages
- This prevents a first run from accidentally sweeping your entire inbox and making you wait forever
- If you really want a full scan, explicitly add `--full-scan`

---

### `unsubscribe` — run the unsubscribe

```bash
python3 main.py unsubscribe (--dry-run | --confirm) [options]
```

**One of these modes is required:**

| Mode | Description |
|------|------|
| `--dry-run` | Dry run: only shows what would be unsubscribed, **does not actually send unsubscribe requests** |
| `--confirm` | Run unsubscribe: asks you one by one for confirmation by default |

**Optional arguments:**

| Option | Description | Default |
|------|------|--------|
| `--auto` | Used with `--confirm`, auto-confirms every unsubscribe (no per-sender prompts) | off |
| `--archive` | After a successful unsubscribe, move that sender's old mail from the inbox to archive | off |
| `--days N` | Scan the last N days; `0` means unlimited, scan all history | 30 days |
| `--all` | Scan all categories (default is Promotions only) | off |
| `--max-messages N` | Process at most the first N messages; good for large-sample sanity checks | unlimited |
| `--full-scan` | With `--days 0 --all`, disables the default guard limit and runs a full scan | off |
| `--no-ai` | Don't use AI assistance | AI on |

**Examples:**
```bash
# Dry run to see what the program plans to unsubscribe from (safest, recommended for the first time)
python3 main.py unsubscribe --dry-run

# Unsubscribe with per-sender confirmation (recommended for everyday use)
python3 main.py unsubscribe --confirm

# Auto-unsubscribe from every suggested sender (no per-sender prompt)
python3 main.py unsubscribe --confirm --auto

# Unsubscribe + also move old promo emails out of the inbox
python3 main.py unsubscribe --confirm --archive

# Full-inbox dry run on a sample first, then decide whether to go full
python3 main.py unsubscribe --dry-run --days 0 --all --max-messages 500

# Scan all history, per-sender confirm, archive after unsubscribe (still 2000-message guard)
python3 main.py unsubscribe --confirm --archive --days 0 --all
```

**Key prompts during per-sender confirmation:**
- `y` or just Enter → unsubscribe from this sender
- `n` → skip, don't unsubscribe
- `q` → stop immediately and exit the program

---

## 6. Whitelist management

The whitelist has two layers:

- **Built-in whitelist**: banks, Google, Apple, governments, educational institutions, etc. — written into the code and never unsubscribed
- **User-defined whitelist**: domains you add yourself, stored in the local database

```bash
# View the whitelist (includes built-in categories and your own additions)
python3 main.py whitelist list

# Add a domain to the whitelist
python3 main.py whitelist add mycompany.com
python3 main.py whitelist add newsletter-i-like.com
```

**Categories already covered by the built-in whitelist (no need to add manually):**
- Banks & finance: ICBC, China Merchants Bank, PayPal, Alipay, etc.
- Tech companies: Google, Apple, Microsoft, GitHub, etc.
- Chinese platforms: Taobao, JD, 163 mail, etc.
- Government: gov.cn, gov.sg, irs.gov, etc.
- Education: edu.cn, mit.edu, stanford.edu, harvard.edu, coursera.org, etc. (matched by specific domains — we do not blanket-allow the `.edu` TLD)

---

## 7. Other commands

### `history` — view unsubscribe history

```bash
python3 main.py history             # show the most recent 50 unsubscribe records
python3 main.py history --limit 20  # show only the most recent 20
```

Senders you've already unsubscribed from **will not appear in the next scan**, so you don't have to worry about duplicates.

### `logs` — view run logs

```bash
python3 main.py logs
```

Shows the last 50 lines of the latest log file — useful for troubleshooting.

### `--verbose` — print detailed debug info

```bash
python3 main.py --verbose scan
python3 main.py --verbose unsubscribe --confirm
```

`--verbose` must come before the command name (right after `main.py`).

---

## 8. FAQ

**Q: I can't find any promo emails, but I clearly have a lot — why?**

A: Possible reasons:
1. The emails are outside the default 30-day window → try `--days 90` or `--days 0` (full history)
2. Gmail has categorized them outside the Promotions tab → add `--all`
3. If `--all` feels too slow, sample with `--max-messages 500` first, then decide on `--full-scan`
4. The sender is on the whitelist → run `python3 main.py whitelist list` to check

**Q: Roughly how long does scanning 10,000 emails take?**

A: Based on real-inbox testing of the current version, a rough estimate:
- **Scan and classify only**: about `10 to 15 minutes`
- **Scan + actually unsubscribe from a few candidate senders**: about `12 to 20 minutes`

Main factors that affect timing:
1. Whether you used `--all` (much slower than Promotions only)
2. Whether AI is enabled
3. How many senders actually end up being unsubscribed
4. Whether the Gmail API triggers retries

If you just want to see whether the results look reasonable, start with:
`python3 main.py scan --days 0 --all --max-messages 500 --no-ai`

**Q: The unsubscribe succeeded, but the old emails are still in my inbox?**

A: That's normal. Unsubscribing only tells the sender "stop sending" — it doesn't touch existing mail. To clean up old mail, add the `--archive` flag when unsubscribing.

**Q: What if an unsubscribe fails?**

A: The sender's unsubscribe system didn't respond. In that case, manually open the email and click the unsubscribe link at the bottom.

**Q: I'm worried about accidentally unsubscribing from something important — what's the safety net?**

A: Three layers of protection: (1) built-in whitelist (banks, Google, etc. are always skipped); (2) sensitive-keyword detection (emails containing verification codes, orders, or bills are skipped); (3) preview first with `--dry-run`.

**Q: What are `credentials.json` and `token.json`?**

A: `credentials.json` is the "ID card" Google issues to this app. `token.json` is the "access pass" saved after you authorize. Both files live only on your machine and are in `.gitignore`. If you delete `token.json`, the next run will re-prompt you for browser authorization.

**Q: Does AI assistance cost money?**

A: Yes, but very little. The default is MiniMax (a low-cost China-based model); you can switch to Anthropic Claude. Combined with the program's built-in **one-call-per-sender** cache, a 10,000-email scan typically only triggers a few dozen to a few hundred AI calls. Most emails are classified locally by rules at no cost. If no API key is configured, AI classification is automatically skipped without affecting basic functionality.

**Q: Can I use it with multiple Gmail accounts?**

A: Currently one project directory maps to one account. For multiple accounts, copy the project directory multiple times and authorize each one separately.

---

## 9. AI assistance (optional)

### One-click setup: use the interactive menu

```bash
python3 main.py
# Choose 5. Settings
# Choose 1. Configure AI provider
```

Follow the prompts to pick a provider, paste your API key, and confirm the model. The program will test the connection automatically and save it once it succeeds.

### Supported providers

| Provider | Protocol | Notes |
|--------|------|------|
| OpenAI | OpenAI | Model: gpt-4o-mini (default) |
| Anthropic Claude | Anthropic | Model: claude-haiku-4-5 (default) |
| MiniMax | Anthropic-compatible | China-based, low cost |
| DeepSeek | OpenAI-compatible | China-based, low cost |
| Moonshot (Kimi) | OpenAI-compatible | China-based |
| Qwen (Tongyi) | OpenAI-compatible | Alibaba Cloud |
| Zhipu GLM | OpenAI-compatible | GLM-4-Flash default |
| Ollama (local) | OpenAI-compatible | Runs on your own machine, free |
| Custom | OpenAI-compatible | Any OpenAI-protocol service works |

### Config file location

All config is stored in `user_config.json` in the project root (already in `.gitignore`, never uploaded to git):

```json
{
  "ai_provider": "deepseek",
  "providers": {
    "deepseek": {"api_key": "sk-...", "model": "deepseek-chat"}
  }
}
```

### AI calls are cached

- **Per-sender cache**: the same sender address only gets asked once; subsequent emails from the same sender reuse the result
- **Per-domain cache**: during the classification stage, the same domain is also only asked once
- Caches only live for the current run — they're recomputed on the next program start

### Turning AI off

```bash
python3 main.py scan --no-ai              # don't use AI this run
python3 main.py unsubscribe --no-ai ...   # don't use AI this run
```

Or turn it off permanently in `config.py`:
```python
USE_AI_CLASSIFIER = False
```

### Seamless migration for existing users

If you previously configured things via environment variables like `export MINIMAX_API_KEY=...`, the first launch of the new version will auto-generate `user_config.json` for you — no action needed.

### View current config

Interactive menu → 5. Settings → 2. View current config. API keys are shown masked (first 6 chars + last 6 chars).

---

## 10. Security notes

| Item | Protection |
|------|---------|
| Google account password | The program **never touches** your password — it uses OAuth 2.0 temporary tokens |
| OAuth token | Saved in `token.json`, already in .gitignore, never uploaded to git |
| API credentials | `credentials.json` is already in .gitignore, never uploaded to git |
| AI API key | Stored in `user_config.json` (already in `.gitignore`), never hard-coded; masked when displayed |
| Email content | AI classification only sends sender + subject + snippet — never the email body |
| Unsubscribe action | Only sends unsubscribe requests, **never deletes any email** |

**Revoke authorization any time:**
Visit [Google Account security settings](https://myaccount.google.com/permissions), find this app, and click revoke.
