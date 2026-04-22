#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail auto-unsubscribe tool - main entry point.
Usage: python main.py <command> [options]

Commands:
  scan              Scan email only; do not unsubscribe
  unsubscribe       Execute unsubscribe actions
  history           View unsubscribe history
  whitelist         Manage the whitelist
  logs              View logs

Examples:
  python main.py scan --days 30
  python main.py scan --all --no-ai
  python main.py unsubscribe --dry-run
  python main.py unsubscribe --confirm
  python main.py unsubscribe --confirm --auto
  python main.py unsubscribe --confirm --archive
  python main.py history
  python main.py history --limit 20
  python main.py whitelist add example.com
  python main.py whitelist list
  python main.py logs
"""

import argparse
import logging
import os
import ssl
import sys
import warnings
from datetime import datetime
from typing import Optional

# Suppress low-level environment warnings from third-party libraries and show our own message instead.
warnings.filterwarnings("ignore", category=FutureWarning, module=r"google(\.|$)")
warnings.filterwarnings("ignore", message=r".*LibreSSL.*", module=r"urllib3(\.|$)")

import auth
import classifier
import config
import database
import scanner
import unsubscriber

# ────────────────────────────────────────────────────────────────
#  Logging setup
# ────────────────────────────────────────────────────────────────

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, f"gmail-unsubscriber-{datetime.now().strftime('%Y%m%d')}.log")


def setup_logging(verbose: bool = False) -> None:
    """Initialize logging to both console and file."""
    os.makedirs(LOG_DIR, exist_ok=True)

    level = logging.DEBUG if verbose else logging.INFO

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # File handler with detailed formatting
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root_logger.addHandler(file_handler)

    # Console handler with compact formatting
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING if not verbose else logging.DEBUG)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger.addHandler(console_handler)


logger = logging.getLogger(__name__)
DEFAULT_FULL_SCAN_MAX_MESSAGES = 2000


def get_runtime_warnings(version_info=None, openssl_version: Optional[str] = None) -> list[str]:
    """Return runtime notices that should be shown to the user."""
    if version_info is None:
        version_info = sys.version_info
    if openssl_version is None:
        openssl_version = getattr(ssl, "OPENSSL_VERSION", "")

    notices = []
    if tuple(version_info[:2]) < (3, 10):
        notices.append(
            "Your Python version is too old (detected "
            f"{version_info[0]}.{version_info[1]}). Python 3.10+ is recommended."
        )

    if "LibreSSL" in openssl_version:
        notices.append(
            "Your Python SSL backend is LibreSSL, which may cause compatibility issues "
            "with some HTTPS / API requests. Python built on OpenSSL 1.1.1+ is recommended."
        )

    return notices


def print_runtime_warnings() -> None:
    """Print concise, actionable runtime notices at startup."""
    notices = get_runtime_warnings()
    if not notices:
        return

    print("⚠️  Runtime notices:", file=sys.stderr)
    for notice in notices:
        print(f"   - {notice}", file=sys.stderr)
    print("   - Recommended: recreate the virtual environment, then run `python -m pytest`.", file=sys.stderr)
    print(file=sys.stderr)


def resolve_scan_limit(args: argparse.Namespace) -> Optional[int]:
    """Apply the default safety cap for very large scan jobs."""
    max_messages = getattr(args, "max_messages", None)
    if max_messages:
        return max_messages

    if getattr(args, "days", None) == 0 and getattr(args, "all", False) and not getattr(args, "full_scan", False):
        print(
            f"⚠️  Detected an 'all history + all mail' scan. By default only the first "
            f"{DEFAULT_FULL_SCAN_MAX_MESSAGES} emails will be processed."
        )
        print("   To run the full scan, explicitly add `--full-scan`.")
        print()
        return DEFAULT_FULL_SCAN_MAX_MESSAGES

    return None


# ────────────────────────────────────────────────────────────────
#  Command: scan
# ────────────────────────────────────────────────────────────────

def cmd_scan(args: argparse.Namespace) -> None:
    """Scan email and show the analysis result without unsubscribing."""
    print("=" * 60)
    print("  Gmail Promotional Email Scanner")
    print("=" * 60)

    service = auth.get_gmail_service()
    use_ai = not args.no_ai
    emails = scanner.scan_emails(
        service,
        days=args.days,
        scan_all=args.all,
        max_messages=resolve_scan_limit(args),
    )

    if not emails:
        print("📭 No recent email found, or the scan result was empty.")
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

    print(f"\n📊 Scan report")
    print(f"   Total emails: {len(emails)}")
    print(f"   Senders recommended for unsubscribe: {len(to_unsub)}")
    print(f"   Emails not recommended for unsubscribe: {skipped}")
    print()

    if not to_unsub:
        print("✅ No promotional emails need unsubscribing.")
        return

    categorized = classifier.categorize_groups(to_unsub, use_ai=use_ai)

    print("─" * 60)
    print("  Unsubscribe suggestions grouped by category:")
    print("─" * 60)

    for cat_name, groups in categorized.items():
        icon = config.CATEGORY_ICONS.get(cat_name, "📧")
        total_count = sum(g["count"] for g in groups)
        print(f"\n  {icon} {cat_name} ({len(groups)} senders, {total_count} emails)")

        for i, group in enumerate(groups, 1):
            print(f"    [{i}] {group['sender']}")
            print(f"        Email: {group['sender_email']}  |  {group['count']} emails")
            if group.get("reasons"):
                print(f"        Reason: {group['reasons'][0]}")

    print()
    print("─" * 60)
    print(f"  Run 'python main.py unsubscribe --dry-run' to preview unsubscribe actions")
    print(f"  Or run 'python main.py' to open the interactive menu")
    print("─" * 60)

    logger.info(f"Scan complete: {len(to_unsub)} senders recommended for unsubscribe, {skipped} emails skipped")


# ────────────────────────────────────────────────────────────────
#  Command: unsubscribe
# ────────────────────────────────────────────────────────────────

def cmd_unsubscribe(args: argparse.Namespace) -> None:
    """Execute unsubscribe actions."""
    dry_run = args.dry_run
    confirm_mode = args.confirm
    auto_mode = args.auto
    archive = getattr(args, "archive", False)
    use_ai = not getattr(args, "no_ai", False)

    if auto_mode and not confirm_mode:
        print("❌ --auto must be used together with --confirm. Example: python main.py unsubscribe --confirm --auto")
        sys.exit(1)

    if dry_run:
        print("=" * 60)
        print("  Gmail Unsubscribe Tool - Dry Run Mode (no unsubscribe action will be executed)")
        print("=" * 60)
    elif confirm_mode:
        mode_desc = "Auto-confirm" if auto_mode else "Manual confirmation"
        print("=" * 60)
        print(f"  Gmail Unsubscribe Tool - {mode_desc}{' (archive after unsubscribe)' if archive else ''}")
        print("=" * 60)
        if not auto_mode:
            print("\n⚠️  Warning: unsubscribe actions will be attempted for the senders below.")
            print("   After unsubscribing, those senders should stop emailing you.\n")

    days = getattr(args, "days", 30)
    scan_all = getattr(args, "all", False)
    service = auth.get_gmail_service()
    emails = scanner.scan_emails(
        service,
        days=days,
        scan_all=scan_all,
        max_messages=resolve_scan_limit(args),
    )

    if not emails:
        print("📭 No email found.")
        return

    result = classifier.classify_emails(emails, use_ai=use_ai)
    to_unsub = result["to_unsubscribe"]

    if not to_unsub:
        print("✅ No promotional emails need unsubscribing.")
        return

    print(f"\n📋 Found {len(to_unsub)} senders recommended for unsubscribe\n")

    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, group in enumerate(to_unsub, 1):
        sender_email = group["sender_email"]
        sender_display = group.get("sender", sender_email)
        count = group["count"]

        print(f"[{i}/{len(to_unsub)}] {sender_display}")
        print(f"         Email: {sender_email}  |  Email count: {count}")
        if group.get("reasons"):
            print(f"         Reason: {group['reasons'][0]}")

        if confirm_mode and not auto_mode:
            user_skipped = False
            while True:
                answer = input(f"\n         Unsubscribe this sender? [y/n/q (quit)] ").strip().lower()
                if answer in ("y", "yes"):
                    break
                elif answer in ("n", "no"):
                    print(f"         ⏭️  Skipped {sender_email}")
                    skip_count += 1
                    print()
                    user_skipped = True
                    break
                elif answer in ("q", "quit", "exit"):
                    print("\nUser quit. Unsubscribe stopped.")
                    _print_summary(success_count, skip_count, fail_count)
                    return
                else:
                    print("         Enter y (unsubscribe), n (skip), or q (quit)")
            if user_skipped:
                continue

        exec_result = unsubscriber.execute_unsubscribe(
            group, service=service, dry_run=dry_run, archive=archive
        )

        if dry_run:
            methods = exec_result.get("details", {}).get("available_methods", [])
            if methods:
                print(f"         🔍 [Dry run] Found unsubscribe methods:")
                for m in methods:
                    print(f"              {m}")
            else:
                print(f"         ⚠️  [Dry run] No unsubscribe method found")
        elif exec_result["success"]:
            print(f"         ✅ Unsubscribe succeeded: {exec_result['message']}")
            success_count += 1
            database.record_unsubscribe(
                sender_email=sender_email,
                sender_name=sender_display,
                method=exec_result.get("attempted_method", "unknown"),
                success=True,
            )
        else:
            print(f"         ❌ Unsubscribe failed: {exec_result['message']}")
            fail_count += 1

        print()

    if not dry_run:
        _print_summary(success_count, skip_count, fail_count)
        database.record_scan(
            days=days,
            total_emails=len(emails),
            candidates=len(to_unsub),
            unsubscribed=success_count,
        )

    logger.info(f"Unsubscribe run complete: success={success_count}, skipped={skip_count}, failed={fail_count}")


def _print_summary(success: int, skipped: int, failed: int) -> None:
    """Print the unsubscribe summary."""
    print()
    print("─" * 60)
    print("  Unsubscribe Summary")
    print("─" * 60)
    print(f"  ✅ Successfully unsubscribed: {success} senders")
    print(f"  ⏭️  Skipped: {skipped} senders")
    print(f"  ❌ Failed: {failed} senders")
    print("─" * 60)
    if failed > 0:
        print("  Tip: unsubscribe usually fails because the sender does not support automation.")
        print("  You can open the email manually and click the unsubscribe link at the bottom.")
    print()


# ────────────────────────────────────────────────────────────────
#  Interactive menu helpers
# ────────────────────────────────────────────────────────────────

def parse_selection(user_input: str, total: int) -> list[int]:
    """
    Parse the user's selection input and return a list of 0-based indexes.
    Supports a single number ("1"), comma-separated values ("1,3,5"), and all.
    Returns an empty list for "0" or invalid input.
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
    Format category summary lines.
    Returns a list like ["  [A] 🛒 E-commerce (2 senders, 15 emails)", ...].
    """
    lines = []
    for i, (cat_name, groups) in enumerate(categorized.items()):
        letter = chr(ord("A") + i)
        icon = config.CATEGORY_ICONS.get(cat_name, "📧")
        sender_count = len(groups)
        email_count = sum(g["count"] for g in groups)
        lines.append(f"  [{letter}] {icon} {cat_name} ({sender_count} senders, {email_count} emails)")
    return lines


# ────────────────────────────────────────────────────────────────
#  Interactive Menu
# ────────────────────────────────────────────────────────────────

_last_scan = {"categorized": None, "to_unsub": None, "total": 0, "days": 0}


def interactive_menu() -> None:
    """Open the interactive main menu."""
    setup_logging()
    database.init_db()

    while True:
        has_scan = _last_scan["categorized"] is not None
        scan_hint = " ✅" if has_scan else ""

        print()
        print("╔══════════════════════════════════╗")
        print("║       Gmail Unsubscriber 📬      ║")
        print("╠══════════════════════════════════╣")
        print(f"║  1. Scan email{scan_hint}               {'  ' if has_scan else '   '}║")
        print("║  2. Unsubscribe                    ║")
        print("║  3. View history                   ║")
        print("║  4. Manage whitelist               ║")
        print("║  5. Settings                       ║")
        print("║  0. Exit                           ║")
        print("╚══════════════════════════════════╝")

        choice = input("\nChoose > ").strip()

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
            print("\n👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice. Enter a number from 0 to 5.")


def _ask_scan_params() -> tuple:
    """Ask for scan settings and return (days, scan_all, use_ai, max_messages)."""
    print("\n── Scan Settings ──")
    days_input = input("  Scan how many recent days? (default 30, enter 0 for all history) > ").strip()
    days = int(days_input) if days_input.isdigit() else 30

    scope = input("  Scan scope? 1=Promotions only (default) 2=All mail > ").strip()
    scan_all = scope == "2"

    ai_choice = input("  Use AI-assisted classification? 1=Yes (default) 2=No > ").strip()
    use_ai = ai_choice != "2"

    limit_input = input("  Max emails to process? (default no limit; enter a number for faster validation) > ").strip()
    max_messages = int(limit_input) if limit_input.isdigit() and int(limit_input) > 0 else None

    return days, scan_all, use_ai, max_messages


def _do_scan_and_classify(days, scan_all, use_ai, max_messages=None):
    """Run the scan and classification, returning (categorized, to_unsub, emails_count)."""
    service = auth.get_gmail_service()
    emails = scanner.scan_emails(
        service,
        days=days,
        scan_all=scan_all,
        max_messages=max_messages,
    )

    if not emails:
        print("📭 No email found.")
        return None, None, 0

    result = classifier.classify_emails(emails, use_ai=use_ai)
    to_unsub = result["to_unsubscribe"]

    if not to_unsub:
        print("✅ No advertising emails need unsubscribing.")
        return None, None, len(emails)

    categorized = classifier.categorize_groups(to_unsub, use_ai=use_ai)
    return categorized, to_unsub, len(emails)


def _display_categories(categorized: dict) -> None:
    """Show the category summary."""
    print(f"\n📊 Scan complete. Grouped by category:\n")
    lines = format_category_summary(categorized)
    for line in lines:
        print(line)
    print()


def _interactive_scan() -> None:
    """Run the interactive scan flow."""
    days, scan_all, use_ai, max_messages = _ask_scan_params()
    categorized, to_unsub, total = _do_scan_and_classify(days, scan_all, use_ai, max_messages)

    if not categorized:
        _last_scan["categorized"] = None
        return

    _last_scan["categorized"] = categorized
    _last_scan["to_unsub"] = to_unsub
    _last_scan["total"] = total
    _last_scan["days"] = days

    _display_categories(categorized)

    total_senders = sum(len(g) for g in categorized.values())
    total_emails = sum(g["count"] for groups in categorized.values() for g in groups)
    print(f"  {total_senders} senders are recommended for unsubscribe, across {total_emails} emails")
    print(f"\n  Choose 2 \"Unsubscribe\" to use these scan results right away.")

    database.record_scan(
        days=days, total_emails=total,
        candidates=total_senders, unsubscribed=0,
    )


def _interactive_unsubscribe() -> None:
    """Run interactive unsubscribe by category, preferring the last scan results."""
    if _last_scan["categorized"]:
        print("\n  Previous scan results were found. Reuse them?")
        reuse = input("  1=Use previous results (default) 2=Scan again > ").strip()
        if reuse != "2":
            categorized = _last_scan["categorized"]
            to_unsub = _last_scan["to_unsub"]
            total = _last_scan["total"]
            days = _last_scan["days"]
        else:
            days, scan_all, use_ai, max_messages = _ask_scan_params()
            categorized, to_unsub, total = _do_scan_and_classify(days, scan_all, use_ai, max_messages)
            if not categorized:
                return
    else:
        days, scan_all, use_ai, max_messages = _ask_scan_params()
        categorized, to_unsub, total = _do_scan_and_classify(days, scan_all, use_ai, max_messages)
        if not categorized:
            return

    archive_choice = input("  Archive old emails after unsubscribing? 1=No (default) 2=Yes > ").strip()
    archive = archive_choice == "2"

    service = auth.get_gmail_service()
    cat_keys = list(categorized.keys())

    success_count = 0
    skip_count = 0
    fail_count = 0

    while True:
        _display_categories(categorized)
        print("  Enter a letter to expand a category / all to unsubscribe everything / 0 to return")
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
                print(f"\n{icon} {cat_name} - {len(groups)} senders:\n")
                for j, g in enumerate(groups, 1):
                    print(f"  [{j}] {g.get('sender', g['sender_email'])} ({g['sender_email']}) - {g['count']} emails")
                print(f"\n  Enter numbers to unsubscribe (for example 1,3,5) / all to unsubscribe all / 0 to return")
                sel = input("> ").strip()
                indices = parse_selection(sel, len(groups))
                if indices:
                    selected = [groups[i] for i in indices]
                    s, sk, f = _unsubscribe_groups(selected, service, archive)
                    success_count += s
                    skip_count += sk
                    fail_count += f
            else:
                print("❌ Invalid choice.")
        else:
            print("❌ Invalid input. Enter a letter, all, or 0.")

    if success_count or fail_count:
        database.record_scan(
            days=days, total_emails=total,
            candidates=len(to_unsub), unsubscribed=success_count,
        )


def _unsubscribe_groups(groups: list[dict], service, archive: bool) -> tuple[int, int, int]:
    """Unsubscribe a group of senders and return counts for (success, skipped, failed)."""
    success = skip = fail = 0
    for g in groups:
        sender_email = g["sender_email"]
        sender_display = g.get("sender", sender_email)

        print(f"\n  Unsubscribing: {sender_display} ({sender_email})")
        exec_result = unsubscriber.execute_unsubscribe(
            g, service=service, dry_run=False, archive=archive
        )
        if exec_result["success"]:
            print(f"  ✅ Unsubscribe succeeded: {exec_result['message']}")
            success += 1
            database.record_unsubscribe(
                sender_email=sender_email,
                sender_name=sender_display,
                method=exec_result.get("attempted_method", "unknown"),
                success=True,
            )
        else:
            print(f"  ❌ Unsubscribe failed: {exec_result['message']}")
            fail += 1

    return success, skip, fail


def _interactive_history() -> None:
    """Open interactive unsubscribe history."""
    args = argparse.Namespace(limit=50)
    cmd_history(args)


def _interactive_whitelist() -> None:
    """Open interactive whitelist management."""
    print("\n── Whitelist Management ──")
    print("  1. View whitelist")
    print("  2. Add a domain to the whitelist")
    print("  0. Return")
    choice = input("\n> ").strip()

    if choice == "1":
        args = argparse.Namespace(whitelist_action="list", func=cmd_whitelist)
        cmd_whitelist(args)
    elif choice == "2":
        domain = input("  Enter the domain to add (for example example.com) > ").strip()
        if domain:
            args = argparse.Namespace(whitelist_action="add", domain=domain, func=cmd_whitelist)
            cmd_whitelist(args)
    elif choice == "0":
        return
    else:
        print("❌ Invalid choice.")


def _interactive_settings() -> None:
    """Open the interactive settings menu."""
    import user_config
    from ai_classifier import PROVIDERS

    while True:
        provider = user_config.get_active_provider()
        if provider:
            meta = PROVIDERS.get(provider["id"], {})
            status = f"{meta.get('name', provider['id'])} / {provider['model']}"
        else:
            status = "Not configured"

        print("\n╔══════════════════════════════════╗")
        print("║       ⚙️  Settings               ║")
        print("╠══════════════════════════════════╣")
        print(f"║  1. Configure AI provider ({status})")
        print( "║  2. View current config")
        print( "║  0. Return")
        print( "╚══════════════════════════════════╝")

        choice = input("Choose: ").strip()
        if choice == "1":
            _configure_ai_provider()
        elif choice == "2":
            _show_current_ai_config()
        elif choice == "0":
            return
        else:
            print("❌ Invalid choice")


def _configure_ai_provider() -> None:
    """Configure the AI provider interactively."""
    import user_config
    from ai_classifier import PROVIDERS, test_connection

    order = ["openai", "anthropic", "minimax", "deepseek", "moonshot", "qwen", "zhipu", "ollama", "custom"]
    print("\nChoose an AI provider:")
    for i, pid in enumerate(order, 1):
        meta = PROVIDERS[pid]
        print(f"  {i}. {meta['name']:<22} ({meta['key_hint']})")
    print("  0. Return")

    sel = input("Choose: ").strip()
    if sel == "0":
        return
    try:
        idx = int(sel) - 1
        if idx < 0 or idx >= len(order):
            print("❌ Invalid choice")
            return
        provider_id = order[idx]
    except (ValueError, IndexError):
        print("❌ Invalid choice")
        return

    meta = PROVIDERS[provider_id]
    print(f"\n[{meta['name']}]")

    base_url = meta["base_url"]
    if provider_id == "custom":
        base_url = input("Enter base_url: ").strip()
        if not base_url:
            print("❌ base_url cannot be empty")
            return
        model = input("Enter model: ").strip()
        if not model:
            print("❌ model cannot be empty")
            return
    else:
        model = meta["default_model"]

    import getpass
    api_key = getpass.getpass(f"Enter API key ({meta['key_hint']}): ").strip()
    if not api_key:
        print("❌ API key cannot be empty")
        return

    if provider_id != "custom":
        ans = input(f"Default model: {model}. Use it? (Y/n): ").strip().lower()
        if ans == "n":
            model = input("Enter model name: ").strip()
            if not model:
                print("❌ Model name cannot be empty")
                return

    print("\n🔍 Testing connection...")
    ok, msg = test_connection(provider_id, api_key, model, base_url)
    if not ok:
        print(f"❌ Connection failed: {msg}")
        print("   Configuration was not saved. Check the key, model, and network, then try again.")
        return

    user_config.set_active_provider(
        provider_id, api_key, model,
        base_url,
    )
    from ai_classifier import invalidate_provider_cache
    invalidate_provider_cache()
    print(f"✅ Connection successful. Configuration saved. Current provider: {meta['name']} (model: {model})")


def _show_current_ai_config() -> None:
    """Show the current AI configuration with the key masked."""
    import user_config
    from ai_classifier import PROVIDERS

    provider = user_config.get_active_provider()
    if not provider:
        print("\nNo AI provider is currently configured.")
        print("Open Settings -> 1. Configure AI provider to set one up.")
        return

    meta = PROVIDERS.get(provider["id"], {})
    print("\nCurrent AI configuration:")
    print(f"  Provider: {meta.get('name', provider['id'])}")
    print(f"  Model:    {provider['model']}")
    print(f"  Key:      {user_config.mask_key(provider['api_key'])}")
    if provider.get("base_url"):
        print(f"  Base URL: {provider['base_url']}")
    print(f"  AI enabled: {'On' if config.USE_AI_CLASSIFIER else 'Off'}")


# ────────────────────────────────────────────────────────────────
#  Command: history
# ────────────────────────────────────────────────────────────────

def cmd_history(args: argparse.Namespace) -> None:
    """View unsubscribe history."""
    limit = getattr(args, "limit", 50)
    history = database.get_history(limit=limit)

    if not history:
        print("📭 No unsubscribe history yet.")
        print("   Run 'python main.py unsubscribe --confirm' to get started.")
        return

    print(f"\n📋 Unsubscribe history ({len(history)} records, latest {limit})")
    print("─" * 60)

    method_labels = {
        "one_click_post": "One-click unsubscribe (POST)",
        "http_get": "HTTP link unsubscribe",
        "mailto": "Unsubscribe email",
        "link_click": "Body link unsubscribe",
        "failed": "Failed unsubscribe",
        "unknown": "Unknown method",
    }

    for i, record in enumerate(history, 1):
        status = "✅" if record["success"] else "❌"
        method = method_labels.get(record.get("method", ""), record.get("method", ""))
        ts = record["unsubscribed_at"][:16].replace("T", " ")
        print(f"\n  [{i}] {record.get('sender_name', record['sender_email'])}")
        print(f"      Email:  {record['sender_email']}")
        print(f"      Time:   {ts}  Method: {method}  {status}")

    print()
    print("─" * 60)


# ────────────────────────────────────────────────────────────────
#  Command: whitelist
# ────────────────────────────────────────────────────────────────

def cmd_whitelist(args: argparse.Namespace) -> None:
    """Manage the user-defined whitelist."""
    if args.whitelist_action == "add":
        domain = args.domain.lower().strip()
        if domain in config.WHITELIST_DOMAINS:
            print(f"ℹ️  '{domain}' is already in the built-in whitelist.")
            return
        success = database.add_to_user_whitelist(domain)
        if success:
            print(f"✅ Added '{domain}' to the whitelist")
            print(f"   Emails from this domain will not be unsubscribed.")
            logger.info(f"Whitelist entry added: {domain}")
        else:
            print(f"ℹ️  '{domain}' is already in the user whitelist.")

    elif args.whitelist_action == "list":
        user_domains = database.get_user_whitelist()
        builtin_count = len(config.WHITELIST_DOMAINS)

        print(f"\n📋 Whitelist overview")
        print(f"   Built-in domains: {builtin_count} (banking, Google, tech, government, health, education, etc.)")
        print(f"   User-defined domains: {len(user_domains)}\n")

        if user_domains:
            print("  User-defined whitelist:")
            for d in sorted(user_domains):
                print(f"    · {d}")
        else:
            print("  User-defined whitelist: (empty)")
            print("  Use 'python main.py whitelist add <domain>' to add one")

        print()
        print("  Built-in whitelist categories (sample):")
        categories = {
            "Banking & Finance": ["icbc.com.cn", "paypal.com", "alipay.com"],
            "Google": ["google.com", "gmail.com", "youtube.com"],
            "Tech Companies": ["apple.com", "microsoft.com", "github.com"],
            "Government": ["gov.cn", "gov.com"],
            "Education": ["edu", "edu.cn", "coursera.org"],
        }
        for cat, examples in categories.items():
            print(f"    {cat}: {', '.join(examples)}")
        print()


# ────────────────────────────────────────────────────────────────
#  Command: logs
# ────────────────────────────────────────────────────────────────

def cmd_logs(args: argparse.Namespace) -> None:
    """View the log files and the latest log content."""
    if not os.path.exists(LOG_DIR):
        print("📁 The log directory does not exist yet.")
        return

    log_files = sorted(
        [f for f in os.listdir(LOG_DIR) if f.endswith(".log")],
        reverse=True
    )

    if not log_files:
        print("📭 No log files yet.")
        return

    print(f"\n📁 Log directory: {LOG_DIR}\n")
    print("  Log files:")
    for f in log_files[:10]:
        fpath = os.path.join(LOG_DIR, f)
        size = os.path.getsize(fpath)
        print(f"    · {f}  ({size // 1024} KB)")

    # Show the last 50 lines of the latest log
    latest = os.path.join(LOG_DIR, log_files[0])
    print(f"\n  Latest log ({log_files[0]}) - last 50 lines:")
    print("─" * 60)
    try:
        with open(latest, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-50:]:
                print(f"  {line.rstrip()}")
    except IOError as e:
        print(f"  Could not read log: {e}")
    print("─" * 60)


# ────────────────────────────────────────────────────────────────
#  CLI Argument Definitions
# ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="gmail-unsubscriber",
        description="Gmail promotional email auto-unsubscribe tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s scan                              Scan promotional emails from the last 30 days
  %(prog)s scan --days 60 --all             Scan all emails from the last 60 days
  %(prog)s scan --no-ai                     Disable AI-assisted classification
  %(prog)s unsubscribe --dry-run            Preview which senders would be unsubscribed
  %(prog)s unsubscribe --confirm            Confirm each unsubscribe interactively
  %(prog)s unsubscribe --confirm --auto     Auto-unsubscribe all recommended senders
  %(prog)s unsubscribe --confirm --archive  Unsubscribe and archive old emails
  %(prog)s history                          View unsubscribe history
  %(prog)s whitelist add taobao.com         Add a domain to the whitelist
  %(prog)s whitelist list                   View the whitelist
  %(prog)s logs                             View runtime logs
        """,
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose debug logging")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # ── scan ──
    scan_parser = subparsers.add_parser("scan", help="Scan email and analyze advertising senders")
    scan_parser.add_argument("--days", "-d", type=int, default=30, metavar="N",
                             help="Scan email from the last N days (default: 30; 0 = scan all history)")
    scan_parser.add_argument("--all", action="store_true",
                             help="Scan all mail (default scans only the Promotions label)")
    scan_parser.add_argument("--max-messages", type=int, metavar="N",
                             help="Process at most the first N emails, useful for sampling large runs")
    scan_parser.add_argument("--full-scan", action="store_true",
                             help="When using --days 0 --all, disable the default safety cap and run the full scan")
    scan_parser.add_argument("--no-ai", action="store_true", dest="no_ai",
                             help="Disable AI-assisted classification")
    scan_parser.set_defaults(func=cmd_scan)

    # ── unsubscribe ──
    unsub_parser = subparsers.add_parser("unsubscribe", help="Run unsubscribe actions")
    unsub_parser.add_argument("--days", "-d", type=int, default=30, metavar="N",
                              help="Scan email from the last N days (default: 30)")
    unsub_parser.add_argument("--all", action="store_true",
                              help="Scan all mail (default scans only the Promotions label)")
    unsub_parser.add_argument("--max-messages", type=int, metavar="N",
                              help="Process at most the first N emails, useful for sampling large runs")
    unsub_parser.add_argument("--full-scan", action="store_true",
                              help="When using --days 0 --all, disable the default safety cap and run the full scan")
    unsub_parser.add_argument("--no-ai", action="store_true", dest="no_ai",
                              help="Disable AI-assisted classification")
    unsub_parser.add_argument("--archive", action="store_true",
                              help="Archive old emails from that sender after a successful unsubscribe")
    unsub_mode = unsub_parser.add_mutually_exclusive_group(required=True)
    unsub_mode.add_argument("--dry-run", action="store_true", dest="dry_run",
                            help="Dry run: show which senders would be unsubscribed without executing")
    unsub_mode.add_argument("--confirm", action="store_true", dest="confirm",
                            help="Confirmation mode: ask before each unsubscribe")
    unsub_parser.add_argument("--auto", action="store_true",
                              help="Auto-confirm all unsubscribes (must be used with --confirm)")
    unsub_parser.set_defaults(func=cmd_unsubscribe)

    # ── history ──
    history_parser = subparsers.add_parser("history", help="View unsubscribe history")
    history_parser.add_argument("--limit", type=int, default=50, metavar="N",
                                help="Show the latest N records (default: 50)")
    history_parser.set_defaults(func=cmd_history)

    # ── whitelist ──
    wl_parser = subparsers.add_parser("whitelist", help="Manage whitelist domains")
    wl_sub = wl_parser.add_subparsers(dest="whitelist_action", metavar="ACTION")
    wl_sub.required = True
    wl_add = wl_sub.add_parser("add", help="Add a domain to the whitelist")
    wl_add.add_argument("domain", help="Domain to whitelist, for example example.com")
    wl_sub.add_parser("list", help="View the current whitelist")
    wl_parser.set_defaults(func=cmd_whitelist)

    # ── logs ──
    logs_parser = subparsers.add_parser("logs", help="View runtime logs")
    logs_parser.set_defaults(func=cmd_logs)

    return parser


# ────────────────────────────────────────────────────────────────
#  Main Entry Point
# ────────────────────────────────────────────────────────────────

def main() -> None:
    import user_config
    if user_config.migrate_from_env():
        print("✅ Migrated AI configuration from environment variables to user_config.json")

    print_runtime_warnings()

    if len(sys.argv) == 1:
        try:
            interactive_menu()
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            sys.exit(0)
        return

    parser = build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    database.init_db()
    logger.info(f"Startup command: {' '.join(sys.argv)}")

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting.")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Program exited with an exception: {e}")
        print(f"\n❌ The program hit an unexpected error: {e}")
        print(f"   See the log for details: {LOG_FILE}")
        sys.exit(1)


if __name__ == "__main__":
    main()
