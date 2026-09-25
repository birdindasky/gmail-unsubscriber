"""Application orchestration: explicit account access, cancellable scans, review plans."""
from __future__ import annotations

import copy
import inspect
import uuid
import importlib.util
from pathlib import Path
import threading
from urllib.parse import urlencode, urlsplit, urlunsplit

from .core import DomainError, Engine, Store
from . import demo
from .network import submit_one_click


class Application:
    def __init__(self, data_dir, mode="demo", credentials_path=None, gmail_client=None):
        if mode not in {"demo", "live"}:
            raise ValueError("mode must be demo or live")
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)
        self.mode = mode
        self.store = Store(str(self.data_dir / "workspace.sqlite3"))
        self.client = gmail_client
        self.credentials_path = Path(credentials_path or Path(__file__).resolve().parent.parent / "credentials.json").expanduser().absolute()
        self._lock = threading.RLock()
        self._action_lock = threading.Lock()
        self._cancel = threading.Event()
        self._worker = None
        self.account = {"mode": mode, "connected": mode == "demo", "email": "demo@lightmail.example" if mode == "demo" else ""}
        self.engine = Engine(self.store, "demo" if mode == "demo" else "disconnected", mode=mode, transport=demo.submit if mode == "demo" else submit_one_click)
        self.job = {"running": False, "phase": "idle", "processed": 0, "message": "", "partial": False}
        if mode == "demo" and not self.engine.state()["subscriptions"]:
            rows = demo.messages()
            self.engine.ingest(rows, {"status": "completed", "fetched": len(rows), "saved": len(rows), "imported": len(rows)})

    def state(self):
        with self._lock:
            return {**self.engine.state(), "account": dict(self.account), "job": copy.deepcopy(self.job),
                    "setup": {"credentials_path": str(self.credentials_path), "exists": self.credentials_path.is_file(),
                              "validity": getattr(self.client, "credentials_validity", "unchecked") if isinstance(getattr(self.client, "credentials_validity", None), str) else "unchecked"},
                    "capabilities": {"dkim": importlib.util.find_spec("dkim") is not None, "live": self.mode == "live"}}

    def _start_job(self, phase, target):
        with self._lock:
            if self.job["running"] or not self._action_lock.acquire(blocking=False):
                raise DomainError("正在处理上一项操作，请稍候。", "busy", 409)
            self._cancel.clear()
            self.job = {"id": uuid.uuid4().hex, "items": [], "plan": None, "result": None, "error": None, "running": True, "kind": phase, "phase": phase, "processed": 0, "message": "正在准备…", "partial": False}
            def run():
                try:
                    target()
                except Exception as error:
                    from .gmail import GmailError
                    from .verification_trace import TraceError
                    safe = isinstance(error, (DomainError, GmailError, TraceError))
                    message = str(error) if safe else "操作未完成，已有数据已保留。请重试；若扫描写入失败，请检查磁盘空间。"
                    with self._lock:
                        self.job.update(phase="failed", message=message, partial=True,
                                        error={"code": getattr(error, "code", "operation_failed") if safe else "operation_failed", "message": message})
                finally:
                    with self._lock:
                        self.job["running"] = False
                    self._action_lock.release()
            self._worker = threading.Thread(target=run, name=f"lightmail-{phase}", daemon=True)
            self._worker.start()
            return {"started": True, "job_id": self.job["id"]}

    def connect(self):
        if self.mode != "live":
            raise DomainError("当前是演示邮箱。关闭后用 --live 启动，再连接自己的 Gmail。", "demo_mode", 409)
        def work():
            with self._lock:
                self.account["connected"] = False
            if self.client is None:
                from .gmail import GmailClient
                self.client = GmailClient(str(self.data_dir), str(self.credentials_path))
            info = self.client.connect()
            with self._lock:
                self.account.update(connected=True, email=info["email"])
                self.engine = Engine(self.store, info["account_id"], mode="live", transport=submit_one_click)
                self.job.update(phase="completed", message="Gmail 已连接。选择扫描范围后开始整理。")
        return self._start_job("connecting", work)

    @staticmethod
    def scan_options(payload):
        days, limit, scope = payload.get("days", 30), payload.get("limit", 100), payload.get("scope", "promotions")
        if type(days) is not int or not 0 <= days <= 3650 or type(limit) is not int or not 1 <= limit <= 2000:
            raise DomainError("天数应在 0–3650 之间，扫描上限应在 1–2000 之间。")
        if scope not in {"promotions", "all"}:
            raise DomainError("扫描范围无效。")
        return days, limit, scope

    def scan(self, payload):
        days, limit, scope = self.scan_options(payload)
        if not self.account["connected"]:
            raise DomainError("请先连接 Gmail。", "not_connected", 409)
        def progress(value=None, **kwargs):
            info = value if isinstance(value, dict) else kwargs
            with self._lock:
                self.job.update(processed=info.get("fetched", info.get("processed", 0)), message=info.get("message", "正在读取邮件列表…"))
        def work():
            self.engine.begin_scan({"days": days, "limit": limit, "scope": scope})
            if self.mode == "demo":
                rows = demo.messages()[:limit]
                cancelled = False
                for step in range(4):
                    if self._cancel.wait(0.12):
                        cancelled = True
                        break
                    progress({"fetched": int(len(rows) * (step + 1) / 4), "message": "正在整理演示邮箱…"})
                result = {"messages": rows if not cancelled else [], "status": "cancelled" if cancelled else ("partial" if limit < len(demo.messages()) else "completed"), "fetched": 0 if cancelled else len(rows), "stop_reason": "用户停止" if cancelled else "演示扫描"}
            else:
                try:
                    result = self.client.scan(days=days, limit=limit, scope=scope, cancel=self._cancel, progress=progress,
                                              on_batch=lambda rows, status: self.engine.save_scan_batch(rows, status))
                except Exception:
                    # Do not replace a committed scan with an apparent success.
                    try:
                        self.engine.finish_scan({"status": "partial", "stop_reason": "storage_error"})
                    except Exception:
                        pass  # The last committed running batch is recovered on restart.
                    raise
            scan_status = {key: value for key, value in result.items() if key != "messages"}
            scan_status["pages_fetched"] = result.get("pages", 0)
            if result.get("stop_reason") == "network_error":
                scan_status["status"] = "network_interrupted"
            elif result.get("stop_reason") == "message_limit":
                scan_status["status"] = "limit"
            if result.get("messages"):
                self.engine.save_scan_batch(result["messages"], scan_status)
            saved = self.engine.finish_scan(scan_status)["scan"]
            with self._lock:
                partial = saved["partial"]
                self.job.update(phase=saved["status"], processed=result.get("fetched", len(result.get("messages", []))), partial=partial,
                                message=saved["message"])
        return self._start_job("scanning", work)

    def cancel_scan(self):
        return self.cancel_job()

    def cancel_job(self):
        with self._lock:
            if self.job.get("running"):
                self._cancel.set()
                self.job.update(phase="stopping", message="正在停止：当前在途操作会等待结束；尚未开始的项目不会执行，已发送请求无法撤回。")
        return {"cancelled": True}

    @staticmethod
    def _validate_ids(ids):
        if not isinstance(ids, list) or not ids or len(ids) > 20 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise DomainError("请选择 1–20 个不同订阅进行预览。")

    def _preview(self, ids, cancel=None, observable=False):
        if self.mode == "live":
            if not self.account["connected"]:
                raise DomainError("请先连接 Gmail。", "not_connected", 409)
            self.engine.clear_verification(ids)
            try:
                message_ids = self.engine.message_ids_for(ids)
                for index, message_id in enumerate(message_ids):
                    if cancel is not None and cancel.is_set():
                        return None
                    if observable:
                        with self._lock:
                            self.job.update(processed=index, message=f"正在核验第 {index + 1} / {len(message_ids)} 项…")
                            self.job["items"][index]["phase"] = "verifying"
                    # Older fixture clients retain the original one-argument API.
                    parameters = inspect.signature(self.client.verify_message).parameters
                    kwargs = {"cancel": cancel} if "cancel" in parameters else {}
                    if "trace" in parameters:
                        from .verification_trace import VerificationTrace
                        trace = VerificationTrace(self.data_dir / "verification-traces")
                        kwargs["trace"] = trace
                        if observable:
                            with self._lock:
                                self.job["items"][index]["trace_id"] = trace.id
                    verified = self.client.verify_message(message_id, **kwargs)
                    if cancel is not None and cancel.is_set():
                        return None
                    if verified and verified.get("sender_email"):
                        self.engine.ingest([verified])
                    if observable:
                        with self._lock:
                            self.job["items"][index].update(phase="receipt", status="verified" if verified and verified.get("authenticated") is True else "unverifiable")
                            self.job["processed"] = index + 1
            finally:
                self.engine.finish_verification(ids)
        if cancel is not None and cancel.is_set():
            return None
        return self.engine.preview(ids)

    def start_preview(self, ids):
        self._validate_ids(ids)
        def work():
            selected = {row["id"]: row for row in self.engine.state()["subscriptions"]}
            with self._lock:
                # Preserve selection order, as Engine.message_ids_for does.
                self.job["items"] = [{"id": sid, "title": selected.get(sid, {}).get("title", ""),
                                      "sender_email": selected.get(sid, {}).get("sender_email", ""),
                                      "phase": "waiting"} for sid in ids]
            plan = self._preview(ids, self._cancel, True)
            with self._lock:
                self.job.update(phase="cancelled" if plan is None else "completed", plan=plan,
                                message="核验已停止，没有生成可执行计划。" if plan is None else "核验完成，请审阅操作计划。")
        return self._start_job("verifying", work)

    def preview(self, ids):
        self._validate_ids(ids)
        if not self._action_lock.acquire(blocking=False):
            raise DomainError("正在处理其他操作，请稍候。", "busy", 409)
        try:
            return self._preview(ids)
        finally:
            self._action_lock.release()

    @staticmethod
    def _validate_confirmation(payload):
        if payload.get("confirmed") is not True or not isinstance(payload.get("plan_id"), str):
            raise DomainError("请在预览中明确确认这份操作计划。", "confirmation_required", 400)

    def start_execute(self, payload):
        self._validate_confirmation(payload)
        def progress(value):
            with self._lock:
                self.job["items"] = value["items"]
                self.job["processed"] = sum(i.get("phase") == "receipt" for i in value["items"])
        def work():
            result = self.engine.execute(payload["plan_id"], cancel=self._cancel, progress=progress)
            with self._lock:
                self.job.update(phase="cancelled" if self._cancel.is_set() else "completed", result=result,
                                message="未开始项目已停止；已发送项目请查看回执。" if self._cancel.is_set() else "处理完成，请查看逐项回执。")
        return self._start_job("executing", work)

    def execute(self, payload):
        self._validate_confirmation(payload)
        if not self._action_lock.acquire(blocking=False):
            raise DomainError("正在处理其他操作，请稍候。", "busy", 409)
        try:
            return self.engine.execute(payload["plan_id"])
        finally:
            self._action_lock.release()

    def protect(self, payload):
        if not isinstance(payload.get("domain"), str) or type(payload.get("enabled", True)) is not bool:
            raise DomainError("请填写有效的域名。")
        self.engine.protect(payload["domain"], payload.get("enabled", True))
        with self._lock:
            self.job.pop("plan", None)
        return self.state()

    def manual_link(self, subscription_id):
        original = self.engine.manual_link(subscription_id)
        if self.mode == "live" and self.account["connected"]:
            # Bind navigation to the connected account instead of Gmail's u/0.
            parsed = urlsplit(original)
            return urlunsplit((parsed.scheme, parsed.netloc, "/mail/", urlencode({"authuser": self.account["email"]}), parsed.fragment))
        return original

    def reset_demo(self):
        if self.mode != "demo":
            raise DomainError("真实邮箱模式不能重置演示数据。", "live_mode", 403)
        if not self._action_lock.acquire(blocking=False):
            raise DomainError("请等待当前操作结束。", "busy", 409)
        try:
            self.engine.reset_demo(demo.messages())
            return self.state()
        finally:
            self._action_lock.release()

    def close(self):
        self._cancel.set()
        if self._worker and self._worker.is_alive():
            self._worker.join()
        self.store.close()
