# 轻邮 · Gmail Unsubscriber v2

A local workspace for reviewing Gmail subscriptions, protecting important mail, and submitting explicit, auditable unsubscribe requests.

Status: restricted local trial. Real sender acceptance and long-term cessation of mail are not established; an uncertain receipt must not be resubmitted.

[中文说明](README_zh.md) · [使用手册](docs/V2_USAGE.md) · [Architecture](docs/V2_ARCHITECTURE.md)

## Start

Python 3.10+ is required. The command-line offline demo uses only the standard library; the macOS double-click launchers require a project virtual environment prepared below.

```bash
python3 app.py --demo
```

On macOS, double-click **体验演示.command** for the synthetic demo or **启动轻邮.command** for the real-account welcome screen. A real account is accessed only after you click Connect Gmail and complete authorization.

For Gmail access, prepare a project virtual environment and dependencies:

```bash
python3 -m venv .venv-v2
source .venv-v2/bin/activate
python -m pip install -r requirements-v2.lock
python app.py --live
```

Place your Google Desktop OAuth client file at `credentials.json`, or supply `--credentials /path/to/client.json`. v2 uses Gmail read-only authorization and a new token; it does not reuse the old root token or import old success history. Nothing is installed as a background service. Press Control+C in the launch terminal to stop.

## Workflow

Scan a bounded mailbox sample → inspect individual subscriptions → protect domains → select up to 20 subscriptions → review a short-lived plan → explicitly confirm → inspect per-item receipts.

- Local Chinese interface: search, categories, subscription details, batch review, protection rules, activity, cancellable scan progress, responsive layout.
- Account- and list-aware storage replaces sender-wide success filtering.
- A signed one-click request requires raw-message DKIM verification over the relevant headers. Unverifiable and ordinary webpage/mailto cases remain manual in Gmail.
- Untrusted endpoints cannot target local/private addresses. HTTPS connections are pinned to a verified public IP, carry no netrc credentials/cookies, and do not follow redirects or automatically retry.
- “Request accepted” is a server response, **not a guarantee that future email will stop**. Interrupted requests stay uncertain; they are not silently retried.
- The demo is synthetic and never contacts Gmail or unsubscribe sites. No paid AI or external analytics are required.

## Data and compatibility

Private data: `.local/v2-demo/` and `.local/v2-live/`, excluded from Git. Old files remain for historical audit; the `main.py` executable now launches v2. Old CLI subcommands are no longer the supported product entry point. Archived v1 READMEs are under `docs/legacy/`.

## Tests

```bash
python -m pip install -r requirements-v2-test.lock
python -m pytest tests_v2 -q
```

Synthetic tests establish local behavior; they do not establish provider acceptance or long-term cessation of email. Local trial records and private account data are excluded from the public repository. See [rebuild instructions](docs/V2_REBUILD.md) for the tested dependency versions.

MIT licensed. Original project by [birdindasky](https://github.com/birdindasky).
