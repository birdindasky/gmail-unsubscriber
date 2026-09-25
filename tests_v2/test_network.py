import socket
from unittest.mock import Mock

import pytest
from gmail_unsubscriber import network


@pytest.mark.parametrize("url", [
    "http://public.example/unsub", "file:///etc/passwd", "https://127.0.0.1/x",
    "https://[::1]/x", "https://169.254.169.254/x", "https://10.0.0.1/x",
    "https://localhost/x", "https://user:pass@example.com/x", "https://example.com:8080/x",
    "https://example.com/x#y", "https://example.com/\r\nX:evil",
])
def test_rejects_unsafe_urls_before_dns(url, monkeypatch):
    dns = Mock(side_effect=AssertionError("must not resolve"))
    monkeypatch.setattr(network.socket, "getaddrinfo", dns)
    assert network.submit_one_click(url)["status"] == "failed"
    assert not dns.called


def test_mixed_dns_public_private_is_rejected(monkeypatch):
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ])
    with pytest.raises(network.UnsafeURL):
        network.resolve_public("example.com")


@pytest.mark.parametrize("code,ctype,expected", [(204,"","accepted"),(200,"text/html","uncertain"),(302,"","uncertain"),(500,"","failed")])
def test_no_redirects_or_environment_credentials(code, ctype, expected, monkeypatch, tmp_path):
    netrc = tmp_path / "netrc"
    netrc.write_text("default login SYNTHETIC password SYNTHETIC\n")
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("HTTPS_PROXY", "http://fake-proxy.invalid:8080")
    monkeypatch.setattr(network, "resolve_public", lambda host: "8.8.8.8")
    response = Mock(status=code)
    response.getheader.return_value = ctype
    connection = Mock()
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    monkeypatch.setattr(network, "PinnedHTTPSConnection", factory)
    assert network.submit_one_click("https://example.com/unsubscribe?t=opaque")["status"] == expected
    factory.assert_called_once_with("example.com", "8.8.8.8")
    connection.request.assert_called_once()
    args, kwargs = connection.request.call_args
    assert args == ("POST", "/unsubscribe?t=opaque")
    assert kwargs["body"] == b"List-Unsubscribe=One-Click"
    assert not {h.lower() for h in kwargs["headers"]} & {"authorization", "cookie", "proxy-authorization"}


def test_timeout_does_not_claim_failure_or_retry(monkeypatch):
    monkeypatch.setattr(network, "resolve_public", lambda _: "8.8.8.8")
    conn = Mock()
    conn.getresponse.side_effect = TimeoutError("credential=SYNTHETIC")
    monkeypatch.setattr(network, "PinnedHTTPSConnection", lambda *a: conn)
    result = network.submit_one_click("https://example.com/unsubscribe")
    assert result["status"] == "uncertain"
    assert "SYNTHETIC" not in result["detail"]
    assert conn.request.call_count == 1
