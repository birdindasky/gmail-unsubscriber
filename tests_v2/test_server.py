"""HTTP boundary checks use an ephemeral loopback server, never external services."""
import http.client
import json
import threading
from unittest.mock import Mock

import pytest
from gmail_unsubscriber.server import LocalServer


@pytest.fixture
def server():
    app = Mock()
    app.state.return_value = {"account":{"mode":"demo"}}
    instance = LocalServer(app)
    worker = threading.Thread(target=instance.serve_forever, daemon=True)
    worker.start()
    yield instance
    instance.shutdown()
    instance.server_close()
    worker.join(2)


def request(server, path, method="GET", payload=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1",server.server_port, timeout=3)
    hdr = {"X-Session-Token":server.session_token}
    hdr.update(headers or {})
    body = None
    if payload is not None:
        body = json.dumps(payload)
        hdr.setdefault("Content-Type", "application/json")
    conn.request(method,path,body=body,headers=hdr)
    response=conn.getresponse()
    result=(response.status,dict(response.getheaders()),response.read())
    conn.close()
    return result


def test_state_requires_session(server):
    status, _, _ = request(server,"/api/state",headers={"X-Session-Token":"wrong"})
    assert status == 403
    assert not server.application.state.called


@pytest.mark.parametrize("headers", [{"Host":"evil.example"},{"Origin":"https://evil.example"},{"Sec-Fetch-Site":"cross-site"}])
def test_rebinding_and_cross_site_rejected(server,headers):
    assert request(server,"/api/state",headers=headers)[0] == 403
    assert not server.application.state.called


def test_valid_state_and_security_headers(server):
    status, headers, body=request(server,"/api/state")
    assert status == 200 and json.loads(body)["account"]["mode"] == "demo"
    assert headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "Access-Control-Allow-Origin" not in headers


def test_invalid_json_and_media_type_cannot_execute(server):
    assert request(server,"/api/execute","POST",[],{})[0] == 400
    assert request(server,"/api/execute","POST",{}, {"Content-Type":"text/plain"})[0] == 415
    assert not server.application.execute.called


@pytest.mark.parametrize("path", ["/../token.json","/credentials.json","/work/audit","/%2e%2e/token.json"])
def test_static_path_allowlist(server,path):
    assert request(server,path)[0] == 404


def test_internal_error_does_not_expose_credential(server):
    server.application.state.side_effect=RuntimeError("SYNTHETIC_SECRET")
    status,_,body=request(server,"/api/state")
    assert status==500 and b"SYNTHETIC_SECRET" not in body
