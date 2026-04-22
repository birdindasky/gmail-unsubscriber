# Gmail Unsubscriber · Quick Reference

For the full manual, see [USAGE_GUIDE.md](USAGE_GUIDE.md).

---

## Activate the Environment (run once per new terminal)

```bash
source venv/bin/activate
```

---

## Option 1: Interactive Menu (recommended)

```bash
python3 main.py
```

Running it without any arguments opens the interactive menu:

```
╔══════════════════════════════════╗
║     Gmail Unsubscriber 📬        ║
╠══════════════════════════════════╣
║  1. Scan Emails                  ║
║  2. Run Unsubscribe              ║
║  3. View History                 ║
║  4. Manage Whitelist             ║
║  5. Settings                     ║
║  0. Exit                         ║
╚══════════════════════════════════╝
```

**Scan**: pick `1`, enter the day range and scope when prompted. Results are grouped by category. After scanning, the menu item shows a ✅ mark indicating cached results.

**Unsubscribe**: pick `2`. If a previous scan is cached, it's reused automatically — otherwise re-scan. Pick a category by letter, then enter numbers for the senders to unsubscribe from.

---

## Option 2: Command-Line Arguments (power users)

```bash
# Scan promotional emails from the last 30 days (view only, no unsubscribe)
python3 main.py scan

# Scan the entire history across all categories (recommended for first deep cleanup)
python3 main.py scan --days 0 --all

# Dry-run unsubscribe to preview what would happen (nothing is actually unsubscribed)
python3 main.py unsubscribe --dry-run

# Confirm each unsubscribe one by one (recommended for daily use)
python3 main.py unsubscribe --confirm

# Auto-unsubscribe every suggested sender (no per-sender prompt)
python3 main.py unsubscribe --confirm --auto

# Unsubscribe + move old promotional emails out of the inbox
python3 main.py unsubscribe --confirm --archive

# Add a domain to the whitelist (it will never be unsubscribed)
python3 main.py whitelist add example.com

# View unsubscribe history
python3 main.py history

# View logs (for debugging)
python3 main.py logs
```

---

## AI Model Configuration

Configure through the interactive menu — no environment variables needed:

```bash
python3 main.py
# → pick 5. Settings
# → pick 1. Configure AI Provider
# → choose provider (1–9)
# → paste your API key
# → connection is tested automatically
# → ✅ saved
```

**Supported providers**: OpenAI, Anthropic Claude, MiniMax, DeepSeek, Moonshot, Qwen (Tongyi), Zhipu GLM, Ollama (local), and any OpenAI-compatible service (custom entry).

Config is saved to `user_config.json` in the project root (already in `.gitignore`, never pushed to git).

**Seamless upgrade for legacy users**: if you previously configured MiniMax or Anthropic via environment variables, the first run of the new version migrates the settings automatically — no re-entry needed.

**AI calls are cached**: the same sender address only triggers the AI once, and the result is reused throughout the current run. This avoids calling the AI 100 times for 100 emails from the same domain.

---

## First-Time Deep Cleanup

### Interactive Mode

1. Run `python3 main.py`
2. Pick `1. Scan`, enter `0` for days, and choose "all" for scope
3. Review the categorized results; add senders you want to keep to the whitelist (pick `4`)
4. Pick `2. Unsubscribe` and unsubscribe by category

### Command-Line Mode

```bash
# 1. Scan to see which promotional senders exist
python3 main.py scan --days 0 --all

# 2. Add any senders you want to keep to the whitelist
python3 main.py whitelist add example.com

# 3. Dry-run to verify the plan
python3 main.py unsubscribe --dry-run --days 0 --all

# 4. Actually unsubscribe
python3 main.py unsubscribe --confirm --days 0 --all
```

---

## Key Notes

- Running `python3 main.py` with no arguments opens the interactive menu
- `scan` only scans — it does **not** unsubscribe. `unsubscribe` has its own internal scan step
- `--days 0` means scan all historical emails (no time limit); expect a wait on large mailboxes
- `--all` scans every category (default is only Gmail's Promotions label)
- `--auto` must be combined with `--confirm`
- After unsubscribing, old emails remain in the inbox — add `--archive` to move them out
- Scan results are automatically grouped by category (e-commerce, newsletters, social, etc.)
