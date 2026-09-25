"""Credential-free, public-only, pinned HTTPS transport for signed unsubscribe URLs.

No Requests/netrc/proxy discovery, cookies, redirects or automatic retries.
The only side effect offered is RFC 8058's fixed form POST.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urlunsplit


class UnsafeURL(ValueError):
    pass


def parse_public_url(url: str) -> tuple[str, str]:
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise UnsafeURL("退订地址格式无效")
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise UnsafeURL("只允许不含登录凭据的 HTTPS 地址")
        if parsed.port not in (None, 443) or parsed.fragment:
            raise UnsafeURL("退订地址不能包含其他端口或片段")
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except (ValueError, UnicodeError) as exc:
        raise UnsafeURL("退订地址格式无效") from exc
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid")):
        raise UnsafeURL("不能访问本机或内部地址")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or any(not part or len(part) > 63 for part in host.split(".")):
            raise UnsafeURL("退订地址必须使用完整公网域名")
    else:
        if not address.is_global or address.is_multicast:
            raise UnsafeURL("不能访问非公网地址")
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    return host, target


def resolve_public(host: str) -> str:
    results = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(result[4][0] for result in results))
    if not addresses:
        raise UnsafeURL("无法验证退订站点的网络地址")
    for value in addresses:
        address = ipaddress.ip_address(value.split("%", 1)[0])
        if not address.is_global or address.is_multicast:
            raise UnsafeURL("站点解析到非公网地址，已阻止访问")
    return addresses[0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, timeout: float = 12):
        super().__init__(hostname, port=443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the already validated IP; authenticate TLS against the original hostname.
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def submit_one_click(url: str) -> dict:
    try:
        host, target = parse_public_url(url)
        address = resolve_public(host)
    except UnsafeURL:
        return {"status": "failed", "detail": "地址未通过安全检查，未提交请求。请在 Gmail 中人工处理。"}
    except (OSError, ValueError):
        return {"status": "failed", "detail": "无法验证站点地址，未提交请求。"}
    conn = None
    try:
        conn = PinnedHTTPSConnection(host, address)
        conn.request("POST", target, body=b"List-Unsubscribe=One-Click", headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*", "User-Agent": "Lightmail/2.0", "Connection": "close",
        })
        response = conn.getresponse()
        status = response.status
        content_type = (response.getheader("Content-Type") or "").lower()
        if 200 <= status < 300:
            if content_type.split(";", 1)[0].strip() in {"text/html", "application/xhtml+xml"}:
                return {"status": "uncertain", "detail": "站点返回网页，无法确认请求是否受理。请在 Gmail 中人工核实。"}
            return {"status": "accepted", "detail": "站点已接受退订请求；是否停止发信仍需后续观察。"}
        if 300 <= status < 400:
            return {"status": "uncertain", "detail": "站点要求跳转，已停止后续访问。请人工核实。"}
        return {"status": "failed", "detail": f"站点未接受请求（HTTP {status}），未自动重试。"}
    except (OSError, ssl.SSLError, http.client.HTTPException):
        # A timeout after sending cannot prove the remote action was not applied.
        return {"status": "uncertain", "detail": "连接中断，无法确认请求是否送达。为避免重复提交，请人工核实。"}
    finally:
        if conn is not None:
            conn.close()
