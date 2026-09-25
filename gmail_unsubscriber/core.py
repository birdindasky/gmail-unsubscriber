"""Offline domain model. Only an explicitly injected transport can send requests.

The authenticated flag is an adapter capability, never inferred from text or AI.
SQLite commits the pending record before calling transport. An interrupted send
therefore becomes uncertain on restart, and cannot be silently retried.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit


class DomainError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


_DEFAULT_DOMAINS = (
    "google.com", "gmail.com", "googlemail.com", "google.cn", "g.co",
    "icbc.com.cn", "ccb.com", "boc.cn", "abchina.com", "bankcomm.com",
    "cmbchina.com", "cmbc.com.cn", "cebbank.com", "psbc.com", "pingan.com.cn",
    "bank.pingan.com", "spdb.com.cn", "cgbchina.com.cn", "hxb.com.cn",
    "citicbank.com", "hsbc.com", "hsbc.com.cn", "chase.com",
    "bankofamerica.com", "citi.com", "wellsfargo.com",
)
_SENSITIVE = re.compile(
    r"验证码|安全提醒|密码|账单|对账单|银行卡|银行|支付|付款|发票|收据|医疗|就诊|处方|"
    r"体检|挂号|保单|报销|工资|合同|论文|导师|课程|面试|会员到期|"
    r"\b(?:password|security|verification|otp|invoice|receipt|bank|banking|"
    r"statement|payment|medical|prescription|appointment|payroll|contract)\b", re.I
)
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_PROCESS_SESSION = secrets.token_hex(16)
_ACTIVE_PLANS: set[tuple[str, str]] = set()
_ACTIVE_SCANS: set[tuple[str, str]] = set()
_PLAN_TTL = 300
_MAX_BATCH = 10000


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _text(value, limit=500):
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split())[:limit]


def _domain(value):
    if not isinstance(value, str):
        raise DomainError("请输入有效的域名。")
    value = value.strip().rstrip(".").lower()
    if value.startswith("@"):
        value = value[1:]
    try:
        value = value.encode("idna").decode("ascii")
    except (ValueError, UnicodeError):
        raise DomainError("请输入有效的域名。") from None
    if len(value) > 253 or "." not in value or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p)
        for p in value.split(".")
    ):
        raise DomainError("请输入域名，例如 example.com，不要填写网址。")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise DomainError("保护规则需要邮件域名，不能使用 IP 地址。")


def _sender(value):
    if not isinstance(value, str) or len(value) > 1024 or any(c in value for c in "\r\n\x00"):
        raise DomainError("邮件发件地址无效。")
    _, address = parseaddr(value)
    if address.count("@") != 1:
        raise DomainError("邮件发件地址无效。")
    local, domain = address.rsplit("@", 1)
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}", local):
        raise DomainError("邮件发件地址无效。")
    return local.lower() + "@" + _domain(domain)


def _date(value):
    try:
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            result = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        elif isinstance(value, str):
            try:
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                result = parsedate_to_datetime(value)
            if result.tzinfo is None:
                result = result.replace(tzinfo=timezone.utc)
        else:
            raise ValueError
        return result.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        # Stable fallback is important when metadata is re-ingested after verification.
        return "1970-01-01T00:00:00+00:00"


def _list_id(value):
    if not isinstance(value, str) or len(value) > 1000:
        return ""
    value = value.strip()
    match = re.fullmatch(r"[^<>]*<([^<>\s]+)>", value)
    candidate = match.group(1) if match else value
    return candidate.lower() if re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,255}", candidate) else ""


def _https_target(value):
    """A syntax gate; the real adapter must also validate DNS and pinned IPs."""
    if not value or any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        return None
    if re.search(r"%0[ad]", value, re.I):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.username is not None or p.password is not None or p.fragment:
            return None
        if p.port not in (None, 443) or not p.hostname:
            return None
        host = _domain(p.hostname)
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test")):
            return None
        return value, host
    except (ValueError, DomainError):
        return None


def _endpoint(message):
    header = message["list_unsubscribe"]
    # Anything ambiguous remains manual: duplicates, malformed framing or multiple HTTPS targets.
    targets = re.findall(r"<([^<>]+)>", header)
    remainder = re.sub(r"<[^<>]+>", "", header)
    valid_syntax = bool(targets) and not remainder.replace(",", "").strip()
    https = [target for target in targets if target.lower().startswith("https:")]
    safe = _https_target(https[0]) if valid_syntax and len(https) == 1 else None
    post = bool(re.fullmatch(r"List-Unsubscribe\s*=\s*One-Click", message["list_unsubscribe_post"].strip(), re.I))
    if safe and post and message["authenticated"] is True:
        return "one_click", safe[0], safe[1]
    host = safe[1] if safe else ""
    return ("manual" if header else "none"), "", host


def _verification(message):
    # Display-only classification. _endpoint remains the independent authority gate.
    candidate = dict(message, authenticated=True)
    if _endpoint(candidate)[0] != "one_click":
        return "none"
    if message.get("authenticated") is True:
        return "verified"
    return message.get("verification_status") if message.get("verification_status") in ("verifying", "unverifiable") else "pending"


def _normalize(message):
    if not isinstance(message, dict) or not isinstance(message.get("id"), str) or not _ID.fullmatch(message["id"]):
        raise DomainError("邮件标识无效，扫描结果未保存。")
    sender = _sender(message.get("sender_email"))
    header = message.get("list_unsubscribe", "")
    post = message.get("list_unsubscribe_post", "")
    if not isinstance(header, str):
        header = ""  # Duplicate or non-string headers can never authorize a request.
    if not isinstance(post, str):
        post = ""
    if len(header) > 8192 or len(post) > 1000:
        raise DomainError("邮件头超出安全长度，扫描结果未保存。")
    result = {
        "id": message["id"], "sender_email": sender,
        "sender_name": _text(message.get("sender_name"), 200),
        "subject": _text(message.get("subject"), 500),
        "snippet": _text(message.get("snippet"), 2000),
        "date": _date(message.get("date")), "list_id": _list_id(message.get("list_id", "")),
        "list_unsubscribe": header, "list_unsubscribe_post": post,
        "authenticated": message.get("authenticated") is True,
    }
    result["verification_status"] = _verification(dict(result, verification_status=message.get("verification_status")))
    # No List-ID: bind to the exact header target, never to just the sender.
    identity = [sender, "list", result["list_id"]] if result["list_id"] else [sender, "target", header]
    result["subscription_id"] = hashlib.sha256(_json(identity).encode()).hexdigest()[:32]
    return result


def _category(message):
    text = " ".join((message["sender_name"], message["subject"], message["snippet"]))
    if _SENSITIVE.search(text):
        return "工作与服务", True
    if re.search(r"优惠|促销|折扣|购物|商城|好物|订单|sale|discount|shop|offer", text, re.I):
        return "购物", False
    if re.search(r"社交|好友|关注|动态|community|social|friend|linkedin", text, re.I):
        return "社交", False
    if re.search(r"新闻|日报|周报|资讯|通讯|newsletter|digest|news|weekly", text, re.I):
        return "资讯", False
    return "其他", False


class Store:
    def __init__(self, path: str):
        if not isinstance(path, (str, os.PathLike)):
            raise DomainError("本地存储路径无效。", "storage_error", 500)
        self.path = str(path)
        self._scan_accounts = set()
        self.key = self.path if self.path == ":memory:" else str(Path(self.path).resolve())
        with _LOCKS_GUARD:
            self.lock = _LOCKS.setdefault(self.key, threading.RLock())
        try:
            if self.path != ":memory:":
                target = Path(self.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink():
                    raise OSError("symlink")
                fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
                os.close(fd)
                os.chmod(self.path, 0o600)
            self.connection = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=5)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA synchronous=FULL")
            with self.lock:
                self.connection.executescript('''
                    CREATE TABLE IF NOT EXISTS accounts (
                        id TEXT PRIMARY KEY, protection_revision INTEGER NOT NULL DEFAULT 0,
                        scan TEXT NOT NULL DEFAULT '{}');
                    CREATE TABLE IF NOT EXISTS protections (
                        account_id TEXT NOT NULL, domain TEXT NOT NULL, source TEXT NOT NULL,
                        PRIMARY KEY(account_id, domain));
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        account_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                        version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'new',
                        PRIMARY KEY(account_id, id));
                    CREATE TABLE IF NOT EXISTS messages (
                        account_id TEXT NOT NULL, id TEXT NOT NULL, subscription_id TEXT NOT NULL,
                        data TEXT NOT NULL, PRIMARY KEY(account_id, id));
                    CREATE INDEX IF NOT EXISTS message_subscription ON messages(account_id, subscription_id);
                    CREATE TABLE IF NOT EXISTS plans (
                        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires_at REAL NOT NULL,
                        protection_revision INTEGER NOT NULL, items TEXT NOT NULL,
                        state TEXT NOT NULL, result TEXT, owner TEXT);
                    CREATE TABLE IF NOT EXISTS executions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
                        subscription_id TEXT NOT NULL, plan_id TEXT NOT NULL, status TEXT NOT NULL,
                        created_at TEXT NOT NULL, owner TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS activity (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
                        created_at TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL,
                        status TEXT NOT NULL, detail TEXT NOT NULL);
                ''')
            self._recover()
        except (sqlite3.Error, OSError):
            raise DomainError("无法安全打开本地数据，请检查文件权限和可用空间。", "storage_error", 500) from None

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                yield self.connection
                self.connection.execute("COMMIT")
            except BaseException as exc:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                if isinstance(exc, sqlite3.Error):
                    raise DomainError("本地数据读写失败，本次操作已停止。", "storage_error", 500) from None
                raise

    def _recover(self):
        with self.transaction() as db:
            for account in db.execute("SELECT id,scan FROM accounts").fetchall():
                scan = json.loads(account["scan"])
                if scan.get("status") == "running" and (self.key, account["id"]) not in _ACTIVE_SCANS:
                    scan.update(status="interrupted", partial=True, ended_at=_now_iso(), end_reason="interrupted",
                                message="上次扫描中断，已保存结果保留；请手动重新扫描。")
                    db.execute("UPDATE accounts SET scan=? WHERE id=?", (_json(scan), account["id"]))
            rows = db.execute("SELECT * FROM plans WHERE state='executing'").fetchall()
            for row in rows:
                if row["owner"] == _PROCESS_SESSION and (self.key, row["id"]) in _ACTIVE_PLANS:
                    continue
                items = json.loads(row["items"])
                results = json.loads(row["result"] or "[]")
                completed = {item["id"] for item in results}
                for item in items:
                    if item["id"] in completed:
                        continue
                    execution = db.execute(
                        "SELECT id,status FROM executions WHERE account_id=? AND plan_id=? AND subscription_id=? ORDER BY id DESC LIMIT 1",
                        (row["account_id"], row["id"], item["id"]),
                    ).fetchone()
                    if execution and execution["status"] == "pending":
                        status, detail = "uncertain", "上次操作中断，远端是否接受未知。请到 Gmail 人工核对，不会自动重试。"
                        db.execute("UPDATE executions SET status='uncertain' WHERE id=?", (execution["id"],))
                        db.execute("UPDATE subscriptions SET status='uncertain' WHERE account_id=? AND id=?", (row["account_id"], item["id"]))
                    else:
                        status, detail = "blocked", "上次操作在发送此项前中断，请重新预览。"
                    results.append({"id": item["id"], "title": item["title"], "status": status, "detail": detail})
                db.execute("UPDATE plans SET state='complete',result=? WHERE id=?", (_json(results), row["id"]))
                _activity(db, row["account_id"], "恢复上次操作", "recovery", "uncertain", "发现中断的操作；未知结果不会自动重试。")

    def close(self):
        with self.lock:
            for account in self._scan_accounts:
                _ACTIVE_SCANS.discard((self.key, account))
            self._scan_accounts.clear()
            self.connection.close()


def _activity(db, account, title, kind, status, detail):
    db.execute("INSERT INTO activity(account_id,created_at,title,kind,status,detail) VALUES(?,?,?,?,?,?)", (account, _now_iso(), title, kind, status, detail))


def _result(items):
    return {"items": items, "summary": {status: sum(item["status"] == status for item in items) for status in ("accepted", "manual", "blocked", "failed", "uncertain")}}


class Engine:
    def __init__(self, store: Store, account_id: str, mode: str = "demo", transport=None):
        if not isinstance(account_id, str) or not account_id.strip() or len(account_id) > 320:
            raise DomainError("账号标识无效。")
        if mode not in ("demo", "live"):
            raise DomainError("运行模式无效。")
        if transport is not None and not callable(transport):
            raise DomainError("退订传输配置无效。")
        self.store, self.account_id, self.mode, self.transport = store, account_id, mode, transport
        with store.transaction() as db:
            added = db.execute("INSERT OR IGNORE INTO accounts(id) VALUES(?)", (account_id,)).rowcount
            if added:
                db.executemany("INSERT INTO protections(account_id,domain,source) VALUES(?,?,'default')", [(account_id, domain) for domain in _DEFAULT_DOMAINS])

    def ingest(self, messages: list[dict], scan_status: dict | None = None):
        if not isinstance(messages, list) or len(messages) > _MAX_BATCH:
            raise DomainError("扫描结果格式或数量无效。")
        normalized = [_normalize(message) for message in messages]
        with self.store.transaction() as db:
            self._ingest_into(db, normalized)
            if scan_status is not None:
                scan = self._scan_status(scan_status)
                db.execute("UPDATE accounts SET scan=? WHERE id=?", (_json(scan), self.account_id))
                _activity(db, self.account_id, "扫描结果已更新", "scan", scan["status"], scan["message"])
        return self.state()

    def ingest_scan(self, messages: list[dict], scan_status: dict | None = None):
        """Keep valid scan records; unsupported mail is a visible partial result.

        Only message validation and identity conflicts are isolated. Storage
        failures still abort atomically, rather than masquerading as bad mail.
        The strict ingest() path remains suitable for verification updates.
        """
        if not isinstance(messages, list) or len(messages) > _MAX_BATCH:
            raise DomainError("扫描结果格式或数量无效。")
        scan = self._scan_status(scan_status if scan_status is not None else {"status": "completed"})
        normalized, skipped = [], 0
        for message in messages:
            try:
                normalized.append(_normalize(message))
            except DomainError as error:
                if error.code != "invalid":
                    raise
                skipped += 1
        with self.store.transaction() as db:
            accepted, identities = [], {}
            for message in normalized:
                identifier = message["id"]
                if identifier not in identities:
                    old = db.execute("SELECT subscription_id FROM messages WHERE account_id=? AND id=?", (self.account_id, identifier)).fetchone()
                    identities[identifier] = old["subscription_id"] if old else message["subscription_id"]
                if identities[identifier] != message["subscription_id"]:
                    skipped += 1
                    continue
                accepted.append(message)
            self._ingest_into(db, accepted)
            scan["imported"] = len({message["id"] for message in accepted})
            scan["skipped"] = min(10**9, scan.get("skipped", 0) + skipped)
            scan["failed"] = min(10**9, scan.get("failed", 0) + skipped)
            if scan["failed"] or scan["skipped"]:
                scan["partial"] = True
                if scan["status"] not in ("cancelled", "failed"):
                    scan["status"] = "partial"
            scan = self._scan_status(scan)
            if skipped:
                scan["message"] = f"已保留有效扫描结果；{skipped} 封邮件因格式或身份冲突未导入，请到 Gmail 核对。"
            db.execute("UPDATE accounts SET scan=? WHERE id=?", (_json(scan), self.account_id))
            _activity(db, self.account_id, "扫描结果已更新", "scan", scan["status"], scan["message"])
        return self.state()

    def begin_scan(self, options):
        with self.store.transaction() as db:
            current = json.loads(db.execute("SELECT scan FROM accounts WHERE id=?", (self.account_id,)).fetchone()[0])
            if current.get("status") == "running":
                raise DomainError("扫描正在进行，请等待或停止。", "scan_in_progress", 409)
            scan = self._scan_status(dict(options, status="running", partial=False))
            scan.update(started_at=_now_iso(), imported=0, saved=0, duplicates=0, skipped=0, failed=0, batches=0, _saved_ids=[])
            db.execute("UPDATE accounts SET scan=? WHERE id=?", (_json(scan), self.account_id))
            _ACTIVE_SCANS.add((self.store.key, self.account_id))
            self.store._scan_accounts.add(self.account_id)
        return self.state()

    def save_scan_batch(self, messages, scan_status=None):
        if not isinstance(messages, list) or len(messages) > 100:
            raise DomainError("扫描批次最多保存 100 封邮件。")
        normalized, invalid = [], 0
        for message in messages:
            try:
                normalized.append(_normalize(message))
            except DomainError:
                invalid += 1
        with self.store.transaction() as db:
            scan = json.loads(db.execute("SELECT scan FROM accounts WHERE id=?", (self.account_id,)).fetchone()[0])
            if scan.get("status") != "running":
                raise DomainError("扫描任务已经结束。", "scan_not_running", 409)
            seen = set(scan.get("_saved_ids", []))
            accepted, new_ids, duplicate_ids = [], set(), set()
            identities = {}
            for message in normalized:
                identifier = message["id"]
                old = db.execute("SELECT subscription_id FROM messages WHERE account_id=? AND id=?", (self.account_id, identifier)).fetchone()
                identity = identities.setdefault(identifier, old[0] if old else message["subscription_id"])
                if identity != message["subscription_id"]:
                    invalid += 1
                    continue
                accepted.append(message)
                if identifier not in seen:
                    (duplicate_ids if old else new_ids).add(identifier)
                    seen.add(identifier)
            self._ingest_into(db, accepted)
            supplied = self._scan_status(scan_status or {})
            for key in ("processed", "discovered", "fetched", "pages_fetched"):
                if key in supplied:
                    scan[key] = supplied[key]
            scan["failed"] = max(scan.get("failed", 0), supplied.get("failed", 0))
            scan["skipped"] = scan.get("skipped", 0) + invalid
            scan["imported"] = scan.get("imported", 0) + len(new_ids)
            scan["duplicates"] = scan.get("duplicates", 0) + len(duplicate_ids)
            scan.update(saved=len(seen), _saved_ids=sorted(seen), batches=scan.get("batches", 0) + 1)
            db.execute("UPDATE accounts SET scan=? WHERE id=?", (_json(scan), self.account_id))
        return self.state()

    def finish_scan(self, scan_status):
        with self.store.transaction() as db:
            previous = json.loads(db.execute("SELECT scan FROM accounts WHERE id=?", (self.account_id,)).fetchone()[0])
            merged = dict(previous, **scan_status)
            for key in ("imported", "saved", "duplicates", "batches", "skipped"):
                merged[key] = previous.get(key, 0)
            merged["failed"] = max(previous.get("failed", 0), scan_status.get("failed", 0))
            status = merged.get("status", "completed")
            reason = merged.get("stop_reason")
            if reason == "network_error":
                status = "network_interrupted"
            elif reason in ("message_limit", "page_limit"):
                status = "limit"
            elif reason == "storage_error":
                status = "failed"
            if status == "running":
                status = "completed"
            if status == "completed":
                if merged.get("failed") or merged.get("skipped"):
                    status = "partial"
                elif not merged.get("fetched", merged.get("saved", 0)):
                    status = "empty"
            merged.update(status=status, end_reason=status, ended_at=_now_iso())
            scan = self._scan_status(merged)
            db.execute("UPDATE accounts SET scan=? WHERE id=?", (_json(scan), self.account_id))
            _activity(db, self.account_id, "扫描结果已更新", "scan", scan["status"], scan["message"])
            _ACTIVE_SCANS.discard((self.store.key, self.account_id))
            self.store._scan_accounts.discard(self.account_id)
        return self.state()

    def _ingest_into(self, db, normalized):
        affected = set()
        for message in normalized:
            old = db.execute("SELECT subscription_id,data FROM messages WHERE account_id=? AND id=?", (self.account_id, message["id"])).fetchone()
            if old and old["subscription_id"] != message["subscription_id"]:
                raise DomainError("同一邮件出现冲突的订阅身份，扫描结果未保存。", "message_conflict", 409)
            if old and old["data"] == _json(message):
                continue
            db.execute("INSERT INTO messages(account_id,id,subscription_id,data) VALUES(?,?,?,?) ON CONFLICT(account_id,id) DO UPDATE SET data=excluded.data", (self.account_id, message["id"], message["subscription_id"], _json(message)))
            affected.add(message["subscription_id"])
        for subscription_id in affected:
            rows = db.execute("SELECT data FROM messages WHERE account_id=? AND subscription_id=?", (self.account_id, subscription_id)).fetchall()
            samples = sorted((json.loads(row["data"]) for row in rows), key=lambda message: (message["date"], message["id"]), reverse=True)
            latest = samples[0]
            category, sensitive = _category(latest)
            # An older important message in the same list is still a reason to keep it.
            sensitive = sensitive or any(_category(message)[1] for message in samples[1:])
            method, url, host = _endpoint(latest)
            data = {
                "id": subscription_id, "title": latest["sender_name"] or latest["sender_email"],
                "sender_email": latest["sender_email"], "domain": latest["sender_email"].rsplit("@", 1)[1],
                "list_id": latest["list_id"], "count": len(samples), "last_seen": latest["date"],
                "sample_subjects": list(dict.fromkeys(message["subject"] for message in samples if message["subject"]))[:3],
                "category": "工作与服务" if sensitive else category, "sensitive": sensitive,
                "verification_status": _verification(latest), "method": method, "url": url, "url_host": host, "sample_message_id": latest["id"],
            }
            existing = db.execute("SELECT data FROM subscriptions WHERE account_id=? AND id=?", (self.account_id, subscription_id)).fetchone()
            if not existing:
                db.execute("INSERT INTO subscriptions(account_id,id,data,version,status) VALUES(?,?,?,1,'new')", (self.account_id, subscription_id, _json(data)))
            elif existing["data"] != _json(data):
                db.execute("UPDATE subscriptions SET data=?,version=version+1 WHERE account_id=? AND id=?", (_json(data), self.account_id, subscription_id))

    def reset_demo(self, messages: list[dict]):
        if self.mode != "demo":
            raise DomainError("真实邮箱模式不能重置演示数据。", "forbidden", 403)
        if not isinstance(messages, list) or len(messages) > _MAX_BATCH:
            raise DomainError("演示数据格式或数量无效。")
        normalized = [_normalize(message) for message in messages]
        with self.store.transaction() as db:
            running = db.execute("SELECT 1 FROM plans WHERE account_id=? AND state='executing'", (self.account_id,)).fetchone()
            if running:
                raise DomainError("请等待当前操作结束后再重置演示。", "execution_in_progress", 409)
            for table in ("messages", "subscriptions", "plans", "executions", "activity", "protections"):
                db.execute(f"DELETE FROM {table} WHERE account_id=?", (self.account_id,))
            db.execute("UPDATE accounts SET protection_revision=0,scan='{}' WHERE id=?", (self.account_id,))
            db.executemany("INSERT INTO protections(account_id,domain,source) VALUES(?,?,'default')", [(self.account_id, domain) for domain in _DEFAULT_DOMAINS])
            self._ingest_into(db, normalized)
            _activity(db, self.account_id, "演示数据已重置", "demo", "completed", "当前内容为合成演示邮件，不是用户邮箱数据。")
        return self.state()

    @staticmethod
    def _scan_status(value):
        if not isinstance(value, dict):
            raise DomainError("扫描状态格式无效。")
        status = value.get("status", "partial")
        if status not in ("idle", "running", "completed", "empty", "limit", "partial", "cancelled", "failed", "interrupted", "network_interrupted"):
            status = "partial"
        partial = value.get("partial") is True or status in ("partial", "cancelled", "failed", "limit", "interrupted", "network_interrupted")
        if status == "completed" and partial:
            status = "partial"
        result = {"status": status, "partial": partial, "message": {
            "idle": "尚未扫描。", "running": "正在扫描邮件。", "completed": "本次扫描完成。",
            "partial": "已保留部分扫描结果，尚未完整扫描。", "cancelled": "扫描已取消，已保留取得的结果。",
            "failed": "扫描未能完成，已保留取得的结果。",
            "empty": "本次范围没有邮件，未扩大扫描范围。", "limit": "已达到本次扫描上限，范围可能尚未读完。",
            "interrupted": "上次扫描中断，已保存结果保留；请手动重新扫描。",
            "network_interrupted": "网络中断，已保存结果保留；请检查连接后重试。",
        }[status]}
        for key in ("processed", "discovered", "fetched", "failed", "skipped", "imported", "pages_fetched", "days", "limit", "saved", "duplicates", "batches"):
            number = value.get(key)
            if type(number) is int and 0 <= number <= 10**9:
                result[key] = number
        if value.get("scope") in ("all", "promotions"):
            result["scope"] = value["scope"]
        if value.get("stop_reason") in ("network_error", "message_limit", "page_limit", "storage_error", "message_errors", "list_error", "pagination_error", "exhausted", "cancelled"):
            result["stop_reason"] = value["stop_reason"]
        for key in ("started_at", "ended_at"):
            value_at = value.get(key)
            if isinstance(value_at, str):
                try:
                    result[key] = datetime.fromisoformat(value_at).isoformat()
                except ValueError:
                    pass
        if value.get("end_reason") in ("completed", "empty", "limit", "cancelled", "partial", "failed", "interrupted", "network_interrupted"):
            result["end_reason"] = value["end_reason"]
        return result

    def _protections(self, db):
        return [dict(row) for row in db.execute("SELECT domain,source FROM protections WHERE account_id=? ORDER BY domain", (self.account_id,))]

    @staticmethod
    def _protected(domain, protections):
        return any(domain == item["domain"] or domain.endswith("." + item["domain"]) for item in protections)

    def _public(self, row, protections):
        data = json.loads(row["data"])
        data.pop("url", None)
        if "verification_status" not in data:
            sample = self.store.connection.execute("SELECT data FROM messages WHERE account_id=? AND id=?", (self.account_id, data["sample_message_id"])).fetchone()
            data["verification_status"] = _verification(json.loads(sample["data"])) if sample else "none"
        sensitive = data.pop("sensitive")
        protected = self._protected(data["domain"], protections)
        data["protected"] = protected
        if protected:
            recommendation, reason = "keep", "此域名已受保护，不会提交退订请求。"
        elif sensitive:
            recommendation, reason = "keep", "包含账号、付款、医疗或工作等重要信息，建议保留并人工核对。"
        elif data["verification_status"] in ("pending", "verifying"):
            recommendation, reason = "review", "发现一键退订候选，须核验签名后才能提交。"
        elif data["method"] == "one_click":
            recommendation, reason = "review", "存在经验证的一键退订头，请审阅后确认是否提交。"
        else:
            recommendation, reason = "manual", "缺少可验证的一键退订方式，请在 Gmail 中人工处理。"
        data.update(recommendation=recommendation, reason=reason)
        persisted = row["status"]
        data["status"] = "uncertain" if persisted == "pending" else persisted
        if persisted == "new":
            data["status"] = "blocked" if protected or sensitive else "manual" if data["method"] != "one_click" and data["verification_status"] not in ("pending", "verifying") else "new"
        return data

    def state(self):
        with self.store.transaction() as db:
            protections = self._protections(db)
            rows = db.execute("SELECT * FROM subscriptions WHERE account_id=? ORDER BY id", (self.account_id,)).fetchall()
            subscriptions = sorted((self._public(row, protections) for row in rows), key=lambda item: (item["last_seen"], item["id"]), reverse=True)
            activity = [dict(row) for row in db.execute("SELECT id,created_at,title,kind,status,detail FROM activity WHERE account_id=? ORDER BY id DESC LIMIT 200", (self.account_id,))]
            scan = json.loads(db.execute("SELECT scan FROM accounts WHERE id=?", (self.account_id,)).fetchone()["scan"])
            scan.pop("_saved_ids", None)
            count = db.execute("SELECT COUNT(*) FROM messages WHERE account_id=?", (self.account_id,)).fetchone()[0]
            return {"subscriptions": subscriptions, "protections": protections, "activity": activity,
                    "stats": {"subscriptions": len(subscriptions), "messages": count,
                              "review": sum(item["recommendation"] == "review" and item["status"] in ("new", "failed") for item in subscriptions),
                              "protected": sum(item["protected"] for item in subscriptions),
                              "accepted": sum(item["status"] == "accepted" for item in subscriptions),
                              "manual": sum(item["status"] == "manual" for item in subscriptions)},
                    "scan": scan or {"status": "idle", "partial": False, "message": "尚未扫描。"}}

    def protect(self, domain: str, enabled: bool = True):
        domain = _domain(domain)
        if type(enabled) is not bool:
            raise DomainError("保护设置必须为开启或关闭。")
        with self.store.transaction() as db:
            if enabled:
                changed = db.execute("INSERT OR IGNORE INTO protections(account_id,domain,source) VALUES(?,?,'user')", (self.account_id, domain)).rowcount
            else:
                changed = db.execute("DELETE FROM protections WHERE account_id=? AND domain=?", (self.account_id, domain)).rowcount
            if changed:
                db.execute("UPDATE accounts SET protection_revision=protection_revision+1 WHERE id=?", (self.account_id,))
                db.execute("UPDATE plans SET state='invalidated' WHERE account_id=? AND state='preview'", (self.account_id,))
                _activity(db, self.account_id, "保护规则已更新", "protection", "completed", "新的保护规则已生效，未执行的预览需要重新生成。")
        return self.state()

    @staticmethod
    def _ids(ids):
        if not isinstance(ids, list) or not ids or len(ids) > 500 or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{32}", item) for item in ids):
            raise DomainError("请选择 1 至 500 个有效订阅。")
        return list(dict.fromkeys(ids))

    def _rows_for(self, db, ids):
        rows = []
        for subscription_id in self._ids(ids):
            row = db.execute("SELECT * FROM subscriptions WHERE account_id=? AND id=?", (self.account_id, subscription_id)).fetchone()
            if not row:
                raise DomainError("所选订阅不存在，请刷新列表。", "not_found", 404)
            rows.append(row)
        return rows

    def message_ids_for(self, ids: list[str]) -> list[str]:
        with self.store.transaction() as db:
            return list(dict.fromkeys(json.loads(row["data"])["sample_message_id"] for row in self._rows_for(db, ids)))

    def clear_verification(self, ids: list[str]):
        """Invalidate adapter trust before fresh live preflight, without losing mail."""
        with self.store.transaction() as db:
            normalized = []
            for row in self._rows_for(db, ids):
                messages = db.execute("SELECT data FROM messages WHERE account_id=? AND subscription_id=?", (self.account_id, row["id"])).fetchall()
                for message in messages:
                    data = json.loads(message["data"])
                    data["authenticated"] = False
                    data["verification_status"] = "verifying"
                    normalized.append(data)
            self._ingest_into(db, normalized)
        return self.state()

    def finish_verification(self, ids):
        with self.store.transaction() as db:
            normalized = []
            for row in self._rows_for(db, ids):
                for message in db.execute("SELECT data FROM messages WHERE account_id=? AND subscription_id=?", (self.account_id, row["id"])):
                    data = json.loads(message["data"])
                    if data.get("authenticated") is not True:
                        data["verification_status"] = "unverifiable"
                        normalized.append(_normalize(data))
            self._ingest_into(db, normalized)
        return self.state()

    def _decision(self, row, protections):
        data = json.loads(row["data"])
        if self._protected(data["domain"], protections):
            return "blocked", "此域名已受保护，不会提交退订请求。"
        if data["sensitive"]:
            return "blocked", "包含重要信息，建议保留并到 Gmail 人工核对。"
        if row["status"] == "accepted":
            return "blocked", "此订阅的请求已接受，不会重复提交。"
        if row["status"] in ("pending", "uncertain"):
            return "blocked", "上次请求结果未知或仍在处理中，请人工核对，不会自动重试。"
        if data["method"] != "one_click":
            return "manual", "请在 Gmail 中人工处理；普通链接和未验签链接不会自动访问。"
        if self.transport is None:
            return "manual", "当前没有可用的退订传输，请在 Gmail 中人工处理。"
        return "ready", "将提交一次经验证的一键退订请求；接受请求不等于保证停止收信。"

    def preview(self, ids: list[str]):
        with self.store.transaction() as db:
            protections = self._protections(db)
            rows = self._rows_for(db, ids)
            items, stored = [], []
            for row in rows:
                data = json.loads(row["data"])
                status, reason = self._decision(row, protections)
                item = {key: data[key] for key in ("id", "title", "sender_email", "method", "url_host")}
                item.update(status=status, reason=reason)
                items.append(item)
                stored.append(dict(item, version=row["version"]))
            plan_id, expires = secrets.token_urlsafe(24), time.time() + _PLAN_TTL
            revision = db.execute("SELECT protection_revision FROM accounts WHERE id=?", (self.account_id,)).fetchone()[0]
            db.execute("INSERT INTO plans(id,account_id,expires_at,protection_revision,items,state) VALUES(?,?,?,?,?,'preview')", (plan_id, self.account_id, expires, revision, _json(stored)))
            return {"id": plan_id, "expires_at": expires, "items": items,
                    "summary": dict(selected=len(items), **{status: sum(item["status"] == status for item in items) for status in ("ready", "manual", "blocked")})}

    def execute(self, plan_id: str, cancel=None, progress=None):
        if not isinstance(plan_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", plan_id):
            raise DomainError("预览标识无效。")
        active_key = (self.store.key, plan_id)
        with self.store.transaction() as db:
            plan = db.execute("SELECT * FROM plans WHERE id=? AND account_id=?", (plan_id, self.account_id)).fetchone()
            if not plan:
                raise DomainError("找不到此预览，请重新选择订阅。", "not_found", 404)
            if plan["state"] == "complete":
                return _result(json.loads(plan["result"]))
            if plan["state"] == "executing":
                raise DomainError("此预览正在执行，请等待结果。", "execution_in_progress", 409)
            if plan["state"] == "invalidated":
                raise DomainError("保护规则已变化，请重新预览。", "plan_stale", 409)
            if time.time() >= plan["expires_at"]:
                raise DomainError("预览已过期，请重新预览后确认。", "plan_expired", 409)
            revision = db.execute("SELECT protection_revision FROM accounts WHERE id=?", (self.account_id,)).fetchone()[0]
            if revision != plan["protection_revision"]:
                raise DomainError("保护规则已变化，请重新预览。", "plan_stale", 409)
            items = json.loads(plan["items"])
            for item in items:
                row = db.execute("SELECT version FROM subscriptions WHERE account_id=? AND id=?", (self.account_id, item["id"])).fetchone()
                if not row or row["version"] != item["version"]:
                    raise DomainError("订阅信息已变化，请重新预览。", "plan_stale", 409)
            db.execute("UPDATE plans SET state='executing',result='[]',owner=? WHERE id=?", (_PROCESS_SESSION, plan_id))
            _ACTIVE_PLANS.add(active_key)
        results = []
        try:
            for item in items:
                with self.store.transaction() as db:
                    row = db.execute("SELECT * FROM subscriptions WHERE account_id=? AND id=?", (self.account_id, item["id"])).fetchone()
                    status, detail = self._decision(row, self._protections(db)) if row else ("blocked", "订阅已不可用，请重新扫描。")
                    if row and row["version"] != item["version"]:
                        status, detail = "blocked", "订阅信息已变化，未提交请求，请重新预览。"
                    # A manual/blocked preview is not upgraded by a concurrent change.
                    if item["status"] != "ready" and status == "ready":
                        status, detail = item["status"], item["reason"]
                    stopped = cancel.is_set() if hasattr(cancel, "is_set") else bool(cancel and cancel())
                    if stopped:
                        status, detail = "blocked", "操作已停止；此项尚未开始，未发送请求。"
                    if status == "ready":
                        url = json.loads(row["data"])["url"]
                        execution_id = db.execute("INSERT INTO executions(account_id,subscription_id,plan_id,status,created_at,owner) VALUES(?,?,?,'pending',?,?)", (self.account_id, item["id"], plan_id, _now_iso(), _PROCESS_SESSION)).lastrowid
                        db.execute("UPDATE subscriptions SET status='pending' WHERE account_id=? AND id=?", (self.account_id, item["id"]))
                if status == "ready":
                    if progress is not None:
                        progress(self.execution_progress(plan_id))
                    try:
                        response = self.transport(url)
                        status = response.get("status") if isinstance(response, dict) else None
                        if status not in ("accepted", "failed", "uncertain"):
                            status = "uncertain"
                    except Exception:
                        status = "uncertain"
                    detail = {"accepted": "请求已接受；是否停止收信仍需后续观察。", "failed": "请求未被接受，可核对后重新预览。", "uncertain": "无法确认远端是否接受请求，请在 Gmail 人工核对，不会自动重试。"}[status]
                    if self.mode == "demo" and status == "accepted":
                        detail = "演示：请求已接受（模拟结果），不代表真实邮箱已退订。"
                    with self.store.transaction() as db:
                        db.execute("UPDATE executions SET status=? WHERE id=?", (status, execution_id))
                        db.execute("UPDATE subscriptions SET status=? WHERE account_id=? AND id=?", (status, self.account_id, item["id"]))
                        results.append({"id": item["id"], "title": item["title"], "status": status, "detail": detail})
                        db.execute("UPDATE plans SET result=? WHERE id=?", (_json(results), plan_id))
                        _activity(db, self.account_id, "退订请求", "unsubscribe", status, detail)
                else:
                    with self.store.transaction() as db:
                        results.append({"id": item["id"], "title": item["title"], "status": status, "detail": detail})
                        db.execute("UPDATE plans SET result=? WHERE id=?", (_json(results), plan_id))
                        _activity(db, self.account_id, "订阅处理", "unsubscribe", status, detail)
                if progress is not None:
                    progress(self.execution_progress(plan_id))
            with self.store.transaction() as db:
                db.execute("UPDATE plans SET state='complete',result=? WHERE id=?", (_json(results), plan_id))
            return _result(results)
        finally:
            with self.store.lock:
                _ACTIVE_PLANS.discard(active_key)

    def execution_progress(self, plan_id):
        with self.store.transaction() as db:
            plan = db.execute("SELECT * FROM plans WHERE id=? AND account_id=?", (plan_id, self.account_id)).fetchone()
            if not plan:
                raise DomainError("找不到此操作。", "not_found", 404)
            receipts = json.loads(plan["result"] or "[]")
            by_id = {item["id"]: item for item in receipts}
            items = []
            for item in json.loads(plan["items"]):
                if item["id"] in by_id:
                    items.append(dict(by_id[item["id"]], phase="receipt"))
                else:
                    pending = db.execute("SELECT 1 FROM executions WHERE plan_id=? AND subscription_id=? AND status='pending'", (plan_id, item["id"])).fetchone()
                    items.append({"id": item["id"], "title": item["title"], "phase": "sending" if pending else "waiting", "status": "pending" if pending else "waiting"})
            return dict(_result(items), plan_id=plan_id, state=plan["state"])

    def manual_link(self, subscription_id: str) -> str:
        with self.store.transaction() as db:
            row = self._rows_for(db, [subscription_id])[0]
            message_id = json.loads(row["data"])["sample_message_id"]
            if not _ID.fullmatch(message_id):
                raise DomainError("此邮件不能生成安全的 Gmail 链接。")
            return "https://mail.google.com/mail/u/0/#all/" + message_id
