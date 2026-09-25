"""Loopback-only web boundary. Never logs request headers, tokens or email content."""
from __future__ import annotations
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit

from .core import DomainError

WEB = Path(__file__).parent / "web"


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, application, port=0):
        self.application = application
        self.session_token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.authority = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.authority}"


class Handler(BaseHTTPRequestHandler):
    server_version = "Lightmail/2"
    def log_message(self, *args):
        pass

    def response(self, status, data, content_type="application/json; charset=utf-8"):
        body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def error(self, status, code, message):
        self.response(status, {"error": {"code": code, "message": message}})

    def trusted(self, api=False):
        if self.headers.get_all("Host") != [self.server.authority]:
            self.error(403, "host_rejected", "访问地址不匹配，请使用启动时显示的本机地址。")
            return False
        if self.headers.get("Origin") not in (None, self.server.origin) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.error(403, "origin_rejected", "已拒绝其他网站发起的操作。")
            return False
        if api and not hmac.compare_digest(self.headers.get("X-Session-Token", ""), self.server.session_token):
            self.error(403, "session_required", "会话已失效，请刷新页面。")
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path)
        if not self.trusted(api=path.path.startswith("/api/")):
            return
        try:
            if path.path == "/favicon.ico":
                return self.response(204, b"", "image/x-icon")
            if path.path == "/api/state":
                return self.response(200, self.server.application.state())
            if path.path == "/api/manual":
                sid = parse_qs(path.query).get("id", [""])[0]
                return self.response(200, {"url": self.server.application.manual_link(sid)})
            static = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"), "/styles.css": ("styles.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8")}
            if path.path not in static:
                return self.error(404, "not_found", "找不到这个页面。")
            name, mime = static[path.path]
            content = (WEB / name).read_bytes()
            if name == "index.html":
                content = content.replace(b"__SESSION_TOKEN__", self.server.session_token.encode())
            self.response(200, content, mime)
        except DomainError as exc:
            self.error(getattr(exc, "status", 400), getattr(exc, "code", "invalid"), str(exc))
        except Exception:
            self.error(500, "internal", "暂时无法读取，请稍后重试。")

    def do_POST(self):
        if not self.trusted(api=True):
            return
        if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
            return self.error(415, "json_required", "请求必须使用 JSON。")
        try:
            sizes = self.headers.get_all("Content-Length") or []
            if len(sizes) != 1:
                raise ValueError()
            size = int(sizes[0])
            if not 0 < size <= 32768:
                return self.error(413, "too_large", "请求过大。")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.error(400, "invalid_json", "请求格式无效。")
        app = self.server.application
        routes = {
            "/api/scan": lambda: app.scan(payload),
            "/api/scan/cancel": app.cancel_scan,
            "/api/jobs/cancel": app.cancel_job,
            "/api/protections": lambda: app.protect(payload),
            "/api/preview": lambda: app.start_preview(payload.get("ids")),
            "/api/execute": lambda: app.start_execute(payload),
            "/api/demo/reset": app.reset_demo,
            "/api/connect": app.connect,
        }
        handler = routes.get(urlsplit(self.path).path)
        if handler is None:
            return self.error(404, "not_found", "找不到这个操作。")
        try:
            self.response(202 if urlsplit(self.path).path in {"/api/scan", "/api/connect", "/api/preview", "/api/execute"} else 200, handler())
        except DomainError as exc:
            self.error(getattr(exc, "status", 400), getattr(exc, "code", "invalid"), str(exc))
        except Exception:
            self.error(500, "internal", "操作未完成，已有记录已保留。请刷新后查看结果。")

    def do_OPTIONS(self):
        self.error(403, "cross_origin_rejected", "不允许跨站访问。")
