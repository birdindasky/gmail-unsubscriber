"""Explicit, read-only Gmail access for v2; no unsubscribe requests live here.

Sources checked 2026-09-18: Gmail v1 users.messages (2026-05-06),
users.messages.list (2026-04-15), auth/scopes (2026-09-10), and Format
(2025-03-24), at https://developers.google.com/workspace/gmail/api/ .
RFC 8058 sections 3-4 require a valid DKIM signature over both unsubscribe
headers. RFC 8601 section 7.1 explains why Authentication-Results text is
not proof. RFC 6376 section 6.1.3 requires body and header verification.
RFC 2919 sections 6/8 define case-insensitive List-ID identity, not trust.
https://www.rfc-editor.org/rfc/rfc8058.html
https://www.rfc-editor.org/rfc/rfc8601.html
https://www.rfc-editor.org/rfc/rfc6376.html
https://www.rfc-editor.org/rfc/rfc2919.html
dkimpy's author-published API: https://pymilter.org/pydkim/dkim.DKIM-class.html
Package/version: https://pypi.org/project/dkimpy/1.1.8/

Metadata is always unauthenticated. Only verify_message may promote a raw
message, using one successful dkimpy signature and its actual signed headers.
The library/DNS can fail on old or transformed mail; that means manual review,
not proof of malicious mail. This does not establish URL safety or user consent.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import inspect
import json
import logging
import os
import random
import re
import stat
import tempfile
import threading
import time
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser, HeaderParser
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from .verification_trace import TraceError

SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)
HTTP_TIMEOUT = 20
OAUTH_TIMEOUT = 180
DNS_TIMEOUT = 3
MAX_RAW_BYTES = 5 * 1024 * 1024
MAX_TOKEN_BYTES = 128 * 1024
MAX_SCAN_MESSAGES = 5000
MAX_PAGES = 100
MAX_SIGNATURES = 8
PAGE_SIZE = 100
MAX_ATTEMPTS = 3
METADATA_HEADERS = (
    "From", "Subject", "Date", "List-ID", "List-Unsubscribe",
    "List-Unsubscribe-Post",
)
CRITICAL_HEADERS = frozenset(("from", "list-unsubscribe", "list-unsubscribe-post"))
MESSAGE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class GmailError(RuntimeError):
    """Safe public error: never includes request URLs, tokens, or SDK text."""
    def __init__(self, message, code="connection_failed"):
        super().__init__(message)
        self.code = code


def connection_error(error, stage="authorization"):
    """Classify known exception types/statuses without publishing SDK text."""
    name = type(error).__name__
    status = getattr(getattr(error, "resp", None), "status", None)
    if name in {"RefreshError", "InvalidGrantError"} or status == 401:
        return GmailError("授权令牌已失效。请重新连接并完成 Google 授权；若仍失败，请按使用说明重置本应用授权。", "token_expired")
    if name in {"AccessDeniedError", "MismatchingStateError"} or (stage == "authorization" and isinstance(error, (TimeoutError, AttributeError))):
        return GmailError("授权尚未完成或已取消。请重试连接，并在 Google 页面完成授权。", "authorization_incomplete")
    if status == 403:
        return GmailError("当前授权权限不符。请重新连接，仅授予 Gmail 只读权限。", "scope_mismatch")
    if isinstance(error, (OSError, ConnectionError, TimeoutError)) or name in {"TransportError", "ConnectionError", "Timeout", "ServerNotFoundError"}:
        return GmailError("网络连接失败。请检查网络后重新连接，已有数据会保留。", "network_failed")
    return GmailError("连接未完成。请重新连接并完成 Google 授权。", "authorization_incomplete")


class _Cancelled(Exception):
    pass


def dkim_available() -> bool:
    try:
        return importlib.util.find_spec("dkim") is not None
    except (ImportError, ValueError):
        return False


def _unfold(value: str) -> str:
    value = re.sub(r"\r?\n[ \t]+", " ", value)
    if any(c in value for c in ("\r", "\n", "\x00")):
        raise ValueError("invalid header")
    return value.strip()


def _display(value: str) -> str:
    try:
        text = str(make_header(decode_header(_unfold(value))))
        return " ".join(text.split())[:1000]
    except (ValueError, LookupError, UnicodeError):
        return ""


def _single(headers: dict[str, list[str]], name: str) -> str:
    values = headers.get(name, [])
    if len(values) != 1:
        return ""
    try:
        return _unfold(values[0])
    except ValueError:
        return ""


def normalize_message(message: dict) -> dict:
    """Normalize metadata without trusting authentication-looking headers.

    `_headers` retains all occurrences. Ambiguous singleton fields are empty,
    so consumers cannot accidentally choose a favorable duplicate.
    """
    headers: dict[str, list[str]] = {}
    for header in message.get("payload", {}).get("headers", []):
        name, value = header.get("name"), header.get("value")
        if isinstance(name, str) and isinstance(value, str):
            headers.setdefault(name.lower(), []).append(value)
    sender_email = sender_name = ""
    sender = _single(headers, "from")
    if sender:
        try:
            parsed = HeaderParser(policy=policy.default).parsestr("From: " + sender + "\n\n")["From"]
            addresses = parsed.addresses
            if not parsed.defects and len(addresses) == 1 and addresses[0].domain:
                sender_email = addresses[0].addr_spec.lower()
                sender_name = _display(addresses[0].display_name)
        except (ValueError, IndexError, AttributeError):
            pass
    list_id = ""
    list_value = _single(headers, "list-id")
    if list_value:
        # List-ID is an unstructured field in the standard email parser.
        parsed_list = HeaderParser(policy=policy.default).parsestr("List-ID: " + list_value + "\n\n")
        match = re.fullmatch(r"[^<>]*<([A-Za-z0-9][A-Za-z0-9_.+\-]{0,252})>\s*", str(parsed_list["List-ID"]))
        if match:
            list_id = match.group(1).lower()
    date = ""
    try:
        if message.get("internalDate") is not None:
            dt = datetime.fromtimestamp(int(message["internalDate"]) / 1000, timezone.utc)
        else:
            dt = parsedate_to_datetime(_single(headers, "date"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        date = dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return {
        "id": str(message.get("id", "")),
        "thread_id": str(message.get("threadId", "")),
        "sender_email": sender_email,
        "sender_name": sender_name,
        "subject": _display(_single(headers, "subject")),
        "snippet": "",  # Metadata scans deliberately do not request body snippets.
        "date": date,
        "list_id": list_id,
        "list_unsubscribe": _single(headers, "list-unsubscribe"),
        "list_unsubscribe_post": _single(headers, "list-unsubscribe-post"),
        "authenticated": False,
        "_headers": headers,
        "size_estimate": message.get("sizeEstimate", 0),
    }


def _https_target(value: str) -> str | None:
    """Conservative RFC 2369 syntax check; transport must still check SSRF."""
    targets = re.findall(r"<([^<>]+)>", value)
    if not targets or re.sub(r"<[^<>]+>", "", value).strip(" ,\t"):
        return None
    https = []
    for target in targets:
        if any(ord(c) <= 32 or ord(c) >= 127 for c in target):
            return None
        try:
            parts = urlsplit(target)
            if parts.scheme.lower() == "https":
                if not parts.hostname or parts.username or parts.password or parts.fragment or parts.port not in (None, 443):
                    return None
                https.append(target)
            elif parts.scheme.lower() != "mailto":
                return None
        except ValueError:
            return None
    return https[0] if len(https) == 1 else None


def _signature_tags(value: str) -> dict[str, str]:
    tags = {}
    for part in _unfold(value).split(";"):
        if not part.strip():
            continue
        key, separator, val = part.strip().partition("=")
        if not separator or key in tags or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ValueError("invalid signature tags")
        tags[key] = val.strip()
    return tags


def _same_header(left: str, right: str) -> bool:
    # dkimpy's canonicalized values include the terminal CRLF.
    return re.sub(r"[ \t]+", " ", _unfold(left.rstrip("\r\n"))) == re.sub(r"[ \t]+", " ", _unfold(right))


def _verified_raw(raw: bytes, response: dict, dkim_module, trace=None) -> dict:
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    raw_headers = [{"name": name, "value": value} for name, value in parsed.raw_items()]
    normalized = normalize_message({**response, "payload": {"headers": raw_headers}})
    normalized["verification_reason"] = "unverified"
    headers = normalized["_headers"]
    if parsed.defects or any(len(headers.get(name, [])) != 1 for name in CRITICAL_HEADERS):
        normalized["verification_reason"] = "ambiguous_headers"
        return normalized
    if not normalized["sender_email"] or normalized["list_unsubscribe_post"] != "List-Unsubscribe=One-Click":
        return normalized
    if not _https_target(normalized["list_unsubscribe"]):
        normalized["verification_reason"] = "ambiguous_target"
        return normalized
    signatures = headers.get("dkim-signature", [])
    if not 1 <= len(signatures) <= MAX_SIGNATURES:
        return normalized
    # Suppress dependency logging: it may contain full signed headers/URLs.
    quiet_logger = logging.Logger("gmail_v2_dkim_private", level=logging.CRITICAL + 1)
    quiet_logger.addHandler(logging.NullHandler())
    for index, signature in enumerate(signatures):
        try:
            tags = _signature_tags(signature)
            names = {h.strip().lower() for h in tags.get("h", "").split(":")}
            if not CRITICAL_HEADERS.issubset(names):
                continue
            # Conservative policy: SHA1 and partially signed bodies remain manual.
            if tags.get("a") not in ("rsa-sha256", "ed25519-sha256") or "l" in tags:
                continue
            verifier = dkim_module.DKIM(raw, timeout=DNS_TIMEOUT, minkey=1024, logger=quiet_logger)
            if trace is None:
                valid = verifier.verify(idx=index)
            else:
                # Wrap the verifier's actual resolver (also preserves isolated
                # dependency-injected DNS in callers/tests).
                parameter = inspect.signature(verifier.verify).parameters["dnsfunc"]
                resolver = parameter.default
                if resolver is inspect.Parameter.empty:
                    resolver = dkim_module.get_txt
                def traced_dns(name, timeout=DNS_TIMEOUT):
                    trace.event("dns", "start")
                    try:
                        answer = resolver(name, timeout=timeout)
                    except Exception:
                        trace.event("dns", "failed", reason="terminal")
                        raise
                    trace.event("dns", "ok" if answer else "failed", reason="none" if answer else "no_answer")
                    return answer
                trace.event("dkim", "start", attempt=index + 1)
                try:
                    valid = verifier.verify(idx=index, dnsfunc=traced_dns)
                except TraceError:
                    raise
                except Exception:
                    trace.event("dkim", "failed", attempt=index + 1, reason="terminal")
                    raise
                trace.event("dkim", "verified" if valid is True else "unverified", attempt=index + 1)
            if valid is not True:
                continue
            signed: dict[str, list[str]] = {}
            for name, value in verifier.signed_headers:
                signed.setdefault(name.decode("ascii").lower(), []).append(value.decode("ascii"))
            if all(
                len(signed.get(name, [])) == 1
                and _same_header(signed[name][0], headers[name][0])
                for name in CRITICAL_HEADERS
            ):
                normalized["authenticated"] = True
                normalized["verification_reason"] = "dkim_verified"
                return normalized
        except TraceError:
            raise
        except Exception:
            # Malformed data, missing optional algorithm, DNS and crypto failures
            # all fail closed. Never expose exception text (it may contain mail).
            continue
    return normalized


class GmailClient:
    """No file access or network until explicit connect(); serial HTTP access."""

    def __init__(self, data_dir: str, credentials_path: str):
        self.data_dir = Path(data_dir).expanduser().absolute()
        self.credentials_path = Path(credentials_path).expanduser().absolute()
        self.token_path = self.data_dir / "token.json"
        self._service = None
        self._credentials = None
        self._io_lock = threading.RLock()
        self._messages: dict[str, dict] = {}
        self.credentials_validity = "unchecked"
        self._scope_mismatch = False
        self.email = ""
        self.account_id = ""

    def _load_credentials(self):
        from google.oauth2.credentials import Credentials
        if self.data_dir.is_symlink():
            raise GmailError("授权文件路径无效。")
        try:
            fd = os.open(self.token_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as token_file:
            info = os.fstat(token_file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_TOKEN_BYTES:
                raise GmailError("本应用的授权文件无效，请重新连接。")
            data = json.loads(token_file.read(MAX_TOKEN_BYTES + 1))
        # Passing SCOPES to Credentials can mask the token's stored scope set.
        # Check the file first; never silently reuse an old modify grant.
        if set(data.get("scopes", [])) != set(SCOPES):
            self._scope_mismatch = True
            return None
        return Credentials.from_authorized_user_info(data, scopes=SCOPES)

    def _write_credentials(self, credentials):
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.data_dir.is_symlink() or self.token_path.is_symlink():
            raise GmailError("授权文件路径无效。")
        encoded = credentials.to_json().encode("utf-8")
        if len(encoded) > MAX_TOKEN_BYTES:
            raise GmailError("授权文件过大。")
        fd, temporary = tempfile.mkstemp(prefix=".token-", dir=self.data_dir)
        try:
            with os.fdopen(fd, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.token_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _validate_client_file(self):
        try:
            with self.credentials_path.open("rb") as source:
                data = json.loads(source.read(MAX_TOKEN_BYTES + 1))
            installed = data.get("installed")
            if not isinstance(installed, dict) or not all(isinstance(installed.get(k), str) and installed[k] for k in ("client_id", "client_secret", "auth_uri", "token_uri")):
                raise ValueError()
            redirects = installed.get("redirect_uris")
            if not isinstance(redirects, list) or not redirects or any(not isinstance(uri, str) or not uri.startswith(("http://localhost", "http://127.0.0.1")) for uri in redirects):
                raise ValueError()
            # Prevent a malformed client file from redirecting authorization secrets.
            if installed["auth_uri"] != "https://accounts.google.com/o/oauth2/auth" or installed["token_uri"] != "https://oauth2.googleapis.com/token":
                raise ValueError()
            self.credentials_validity = "valid"
        except FileNotFoundError:
            self.credentials_validity = "missing"
            raise GmailError("找不到 OAuth 客户端文件。请下载 Google 桌面应用客户端 JSON，并放到显示的配置路径后重试。", "credentials_missing") from None
        except (ValueError, TypeError, AttributeError, OSError):
            self.credentials_validity = "invalid"
            raise GmailError("客户端文件格式无效。请在 Google Cloud 创建桌面应用 OAuth 客户端，重新下载 JSON 后重试。", "credentials_invalid") from None

    def _oauth_credentials(self):
        self._validate_client_file()
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), scopes=SCOPES)
        request = flow.oauth2session.request

        def bounded_request(*args, **kwargs):
            kwargs["timeout"] = HTTP_TIMEOUT
            return request(*args, **kwargs)

        flow.oauth2session.request = bounded_request
        return flow.run_local_server(
            host="127.0.0.1", port=0, timeout_seconds=OAUTH_TIMEOUT,
            authorization_prompt_message="", success_message="连接完成，可以关闭此窗口。",
            prompt="consent", include_granted_scopes="false",
        )

    def connect(self) -> dict:
        """User-triggered OAuth only, using this v2 data directory's token."""
        with self._io_lock:
            self._service = None
            self._credentials = None
            self.email = self.account_id = ""
            self._messages.clear()
            stage = "token"
            self._scope_mismatch = False
            try:
                import httplib2
                from google.auth.transport.requests import Request
                from google_auth_httplib2 import AuthorizedHttp
                from googleapiclient.discovery import build

                try:
                    credentials = self._load_credentials()
                except (ValueError, KeyError, TypeError):
                    raise GmailError("本应用授权令牌无效。请按使用说明重置授权文件后重新连接。", "token_expired") from None
                if self._scope_mismatch:
                    raise GmailError("已保存的权限与 Gmail 只读权限不符。请按说明重置本应用授权后重新连接。", "scope_mismatch")
                if credentials and not credentials.valid and credentials.refresh_token:
                    request = Request()
                    try:
                        credentials.refresh(lambda *a, **kw: request(*a, **{**kw, "timeout": HTTP_TIMEOUT}))
                    except Exception as error:
                        raise connection_error(error, "refresh") from None
                if not credentials or not credentials.valid:
                    stage = "authorization"
                    credentials = self._oauth_credentials()
                actual_scopes = getattr(credentials, "granted_scopes", None) or credentials.scopes
                if set(actual_scopes or ()) != set(SCOPES):
                    raise GmailError("连接需要独立的 Gmail 只读授权，请重新授权。", "scope_mismatch")
                stage = "profile"
                transport = AuthorizedHttp(credentials, http=httplib2.Http(timeout=HTTP_TIMEOUT))
                service = build("gmail", "v1", http=transport, cache_discovery=False, static_discovery=True)
                profile = service.users().getProfile(userId="me", fields="emailAddress").execute(num_retries=0)
                email = str(profile.get("emailAddress", "")).strip().lower()
                if not re.fullmatch(r"[^\s@]+@[^\s@]+", email):
                    raise GmailError("无法确认 Gmail 账号，请重新连接。")
                self._write_credentials(credentials)
                self._credentials = credentials
                self._service = service
                self.email = email
                self.account_id = hashlib.sha256(email.encode("utf-8")).hexdigest()
                return {"email": email, "account_id": self.account_id}
            except GmailError:
                raise
            except Exception as error:
                raise connection_error(error, stage) from None

    def _require_connected(self):
        if self._service is None:
            raise GmailError("请先连接 Gmail。")

    @staticmethod
    def _retryable(error: Exception) -> bool:
        status = getattr(getattr(error, "resp", None), "status", None)
        if status in (429, 500, 502, 503, 504):
            return True
        if status == 403:
            try:
                reasons = json.loads(error.content).get("error", {}).get("errors", [])
                return any(r.get("reason") in ("rateLimitExceeded", "userRateLimitExceeded") for r in reasons)
            except (ValueError, TypeError, AttributeError):
                return False
        return isinstance(error, (OSError, TimeoutError, ConnectionError))

    def _request(self, factory, cancel: threading.Event, trace=None, operation="metadata"):
        for attempt in range(MAX_ATTEMPTS):
            if cancel.is_set():
                raise _Cancelled()
            if trace:
                trace.event(operation, "start", attempt=attempt + 1)
            try:
                with self._io_lock:
                    self._require_connected()
                    result = factory(self._service).execute(num_retries=0)
            except TraceError:
                raise
            except Exception as error:
                retry = self._retryable(error) and attempt + 1 < MAX_ATTEMPTS
                if trace:
                    trace.event(operation, "failed", attempt=attempt + 1, reason="retryable" if retry else "terminal")
                if not retry:
                    raise
                if cancel.wait(min(8, 2 ** attempt) + random.random() * 0.25):
                    raise _Cancelled() from None
            else:
                if trace:
                    trace.event(operation, "ok", attempt=attempt + 1)
                return result

    def scan(self, days: int, limit: int, scope: str, cancel: threading.Event, progress, on_batch=None) -> dict:
        self._require_connected()
        if type(days) is not int or not 0 <= days <= 3650 or type(limit) is not int or not 1 <= limit <= MAX_SCAN_MESSAGES:
            raise GmailError("扫描范围无效：最多扫描 5000 封邮件。")
        if scope not in ("promotions", "all"):
            raise GmailError("请选择促销邮件或全部邮件。")
        query = "-in:sent -in:drafts -in:trash -in:spam"
        if days:
            query += f" after:{int(time.time()) - days * 86400}"
        if scope == "promotions":
            query += " category:promotions"
        result = {"messages": [], "status": "running", "pages": 0, "discovered": 0,
                  "fetched": 0, "failed": 0, "stop_reason": "", "next_page_available": False}
        seen, page_tokens = set(), set()
        token = None
        batch = []

        def flush():
            if batch and on_batch:
                on_batch(list(batch), {key: value for key, value in result.items() if key != "messages"})
                batch.clear()

        def emit():
            if progress:
                progress({key: value for key, value in result.items() if key != "messages"})

        emit()
        try:
            while result["discovered"] < limit:
                if cancel.is_set():
                    raise _Cancelled()
                arguments = {"userId": "me", "q": query, "maxResults": min(PAGE_SIZE, limit - result["discovered"]),
                             "includeSpamTrash": False, "fields": "messages/id,nextPageToken"}
                if token:
                    arguments["pageToken"] = token
                try:
                    page = self._request(lambda svc: svc.users().messages().list(**arguments), cancel)
                except _Cancelled:
                    raise
                except Exception as error:
                    result.update(status="partial" if result["pages"] else "failed", stop_reason="network_error" if isinstance(error, (OSError, TimeoutError, ConnectionError)) else "list_error", next_page_available=True)
                    break
                result["pages"] += 1
                next_token = page.get("nextPageToken")
                result["next_page_available"] = bool(next_token)
                stubs = []
                for stub in page.get("messages", []):
                    identifier = str(stub.get("id", ""))
                    if identifier in seen:
                        continue
                    if result["discovered"] >= limit:
                        result["next_page_available"] = True
                        break
                    seen.add(identifier)
                    result["discovered"] += 1
                    stubs.append(identifier)
                emit()
                for identifier in stubs:
                    if cancel.is_set():
                        raise _Cancelled()
                    try:
                        if not MESSAGE_ID.fullmatch(identifier):
                            raise ValueError("invalid id")
                        message = self._request(lambda svc: svc.users().messages().get(
                            userId="me", id=identifier, format="metadata", metadataHeaders=list(METADATA_HEADERS),
                            fields="id,threadId,internalDate,sizeEstimate,payload/headers"), cancel)
                        if str(message.get("id")) != identifier:
                            raise ValueError("message mismatch")
                        normalized = normalize_message(message)
                        if not normalized["sender_email"]:
                            raise ValueError("missing or ambiguous sender")
                        if on_batch:
                            batch.append(normalized)
                        else:
                            result["messages"].append(normalized)
                        self._messages[identifier] = normalized
                        result["fetched"] += 1
                    except _Cancelled:
                        raise
                    except Exception as error:
                        result["failed"] += 1
                        if isinstance(error, (OSError, TimeoutError, ConnectionError)):
                            result.update(status="partial", stop_reason="network_error", next_page_available=True)
                            break
                    if len(batch) >= 20:
                        flush()
                    emit()
                flush()
                emit()
                if result["status"] != "running":
                    break
                if not next_token:
                    break
                if next_token in page_tokens:
                    result.update(status="partial", stop_reason="pagination_error")
                    break
                if result["pages"] >= MAX_PAGES:
                    result.update(status="partial", stop_reason="page_limit")
                    break
                page_tokens.add(next_token)
                token = next_token
            if result["status"] == "running":
                if result["next_page_available"]:
                    result.update(status="partial", stop_reason="message_limit")
                elif result["failed"]:
                    result.update(status="partial", stop_reason="message_errors")
                else:
                    result.update(status="completed", stop_reason="exhausted")
        except _Cancelled:
            result.update(status="cancelled", stop_reason="cancelled", next_page_available=True)
        flush()
        emit()
        return result

    def verify_message(self, message_id: str, cancel=None, trace=None) -> dict:
        if trace is None:
            return self._verify_message(message_id, cancel)
        trace.event("verification", "start")
        try:
            result = self._verify_message(message_id, cancel, trace)
        except TraceError:
            raise
        except Exception:
            trace.event("verification", "failed", reason="terminal")
            raise
        stopped = cancel is not None and cancel.is_set()
        trace.event("verification", "cancelled" if stopped else "verified" if result.get("authenticated") is True else "unverified",
                    reason="cancelled" if stopped else "none")
        return result

    def _verify_message(self, message_id: str, cancel=None, trace=None) -> dict:
        """Explicit selected-item preflight; never called by scan().

        Returns a complete normalized message, or {} if no trustworthy message
        identity can be retrieved. Every failure removes authentication; callers
        must also invalidate earlier authentication when they receive {}.
        """
        self._require_connected()
        if not isinstance(message_id, str) or not MESSAGE_ID.fullmatch(message_id):
            raise GmailError("邮件标识无效。")
        fallback = dict(self._messages.get(message_id, {}))
        metadata = None
        cancel = cancel if cancel is not None else threading.Event()
        if not fallback.get("sender_email"):
            try:
                metadata = self._request(lambda svc: svc.users().messages().get(
                    userId="me", id=message_id, format="metadata", metadataHeaders=list(METADATA_HEADERS),
                    fields="id,threadId,internalDate,sizeEstimate,payload/headers"), cancel, trace)
                if str(metadata.get("id")) != message_id:
                    return {}
                fallback = normalize_message(metadata)
                if not fallback["sender_email"]:
                    return {}
                self._messages[message_id] = dict(fallback)
            except TraceError:
                raise
            except Exception:
                return {}
        fallback.update(authenticated=False, verification_reason="unverified")
        try:
            import dkim
        except ImportError:
            fallback["verification_reason"] = "dkim_unavailable"
            return fallback
        try:
            # Always check size immediately before RAW, even for cached messages.
            if metadata is None:
                metadata = self._request(lambda svc: svc.users().messages().get(
                    userId="me", id=message_id, format="metadata", fields="id,sizeEstimate"), cancel, trace)
            if str(metadata.get("id")) != message_id or not 0 < int(metadata.get("sizeEstimate", 0)) <= MAX_RAW_BYTES:
                fallback["verification_reason"] = "size_limit"
                return fallback
            response = self._request(lambda svc: svc.users().messages().get(
                userId="me", id=message_id, format="raw", fields="id,threadId,internalDate,raw"), cancel, trace, "raw")
            encoded = response.get("raw", "")
            if str(response.get("id")) != message_id or not isinstance(encoded, str) or len(encoded) > ((MAX_RAW_BYTES + 2) // 3) * 4:
                return fallback
            raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            if not raw or len(raw) > MAX_RAW_BYTES:
                return fallback
            verified = _verified_raw(raw, response, dkim, trace)
            if verified.get("sender_email"):
                return verified
            fallback["verification_reason"] = verified.get("verification_reason", "unverified")
            return fallback
        except TraceError:
            raise
        except Exception:
            return fallback
