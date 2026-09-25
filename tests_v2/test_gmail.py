"""Offline adapter tests: synthetic mail, SDK fakes, no real auth/DNS/HTTP."""

import base64
import hashlib
import json
import os
import sys
import threading
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gmail_unsubscriber import gmail


def metadata(identifier="a1", extra=()):
    return {"id": identifier, "internalDate": "1700000000000", "sizeEstimate": 600,
            "payload": {"headers": [
                {"name": "From", "value": "=?utf-8?b?5rWL6K+V?= <news@example.com>"},
                {"name": "Subject", "value": "=?utf-8?b?5paw6Ze7?="},
                {"name": "List-ID", "value": "News <NEWS.Example.Com>"},
                {"name": "List-Unsubscribe", "value": "<https://example.com/leave?token=synthetic>"},
                {"name": "List-Unsubscribe-Post", "value": "List-Unsubscribe=One-Click"},
                *extra,
            ]}}


class Request:
    def __init__(self, answer):
        self.answer = answer

    def execute(self, **kwargs):
        assert kwargs == {"num_retries": 0}
        if isinstance(self.answer, Exception):
            raise self.answer
        if callable(self.answer):
            return self.answer()
        return self.answer


class Service:
    def __init__(self, pages=(), messages=None, raw=None):
        self.pages = iter(pages)
        self.messages_by_id = messages or {}
        self.raw = raw
        self.calls = []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return Request(next(self.pages))

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        if kwargs["format"] == "raw":
            return Request({"id": kwargs["id"], "raw": base64.urlsafe_b64encode(self.raw).decode().rstrip("=")})
        return Request(self.messages_by_id.get(kwargs["id"], metadata(kwargs["id"])))

    def getProfile(self, **kwargs):
        self.calls.append(("profile", kwargs))
        return Request({"emailAddress": "TEST@EXAMPLE.COM"})


@pytest.fixture
def client(tmp_path):
    return gmail.GmailClient(str(tmp_path / "new-v2"), str(tmp_path / "synthetic-oauth.json"))


def test_constructor_and_disconnected_operations_never_touch_credentials(tmp_path, monkeypatch):
    spy = Mock(side_effect=AssertionError("unexpected file access"))
    monkeypatch.setattr(gmail.os, "open", spy)
    client = gmail.GmailClient(str(tmp_path / "new-v2"), str(tmp_path / "credentials.json"))
    with pytest.raises(gmail.GmailError, match="先连接"):
        client.scan(30, 10, "all", threading.Event(), None)
    with pytest.raises(gmail.GmailError, match="先连接"):
        client.verify_message("a1")
    assert not spy.called


def test_metadata_decodes_names_subject_list_id_but_never_authenticates():
    normalized = gmail.normalize_message(metadata(extra=[
        {"name": "Authentication-Results", "value": "mx.google.com; dkim=pass"},
        {"name": "DKIM-Signature", "value": "a=rsa-sha256; h=from:list-unsubscribe:list-unsubscribe-post; b=fake"},
    ]))
    assert normalized["sender_name"] == "测试"
    assert normalized["subject"] == "新闻"
    assert normalized["sender_email"] == "news@example.com"
    assert normalized["list_id"] == "news.example.com"
    assert normalized["authenticated"] is False
    assert normalized["date"] == "2023-11-14T22:13:20+00:00"
    assert normalized["snippet"] == ""


def test_duplicate_headers_retained_and_not_selected():
    result = gmail.normalize_message(metadata(extra=[
        {"name": "LIST-UNSUBSCRIBE", "value": "<https://attacker.example/leave>"},
        {"name": "FROM", "value": "attacker@example.org"},
    ]))
    assert len(result["_headers"]["list-unsubscribe"]) == 2
    assert result["list_unsubscribe"] == ""
    assert result["sender_email"] == ""
    assert result["authenticated"] is False


def test_scan_processes_each_page_before_listing_next_and_reports_real_counts(client):
    service = Service([{"messages": [{"id": "a1"}], "nextPageToken": "p2"}, {"messages": [{"id": "a2"}]}])
    client._service = service
    updates = []
    result = client.scan(30, 100, "promotions", threading.Event(), updates.append)
    assert [call[0] for call in service.calls] == ["list", "get", "list", "get"]
    assert result["status"] == "completed"
    assert (result["pages"], result["discovered"], result["fetched"], result["failed"]) == (2, 2, 2, 0)
    assert not result["next_page_available"]
    assert all(not item["authenticated"] for item in result["messages"])
    assert "category:promotions" in service.calls[0][1]["q"]
    assert "after:" in service.calls[0][1]["q"]
    assert service.calls[0][1]["maxResults"] == 100
    assert updates[-1]["status"] == "completed"
    assert all("messages" not in update for update in updates)


def test_scan_cap_is_partial_not_complete(client):
    client._service = Service([{"messages": [{"id": "a1"}], "nextPageToken": "p2"}])
    result = client.scan(0, 1, "all", threading.Event(), None)
    assert result["status"] == "partial"
    assert result["stop_reason"] == "message_limit"
    assert result["next_page_available"] is True


def test_scan_cancellation_preserves_results_and_stops_network(client):
    cancel = threading.Event()
    client._service = Service([{"messages": [{"id": "a1"}, {"id": "a2"}], "nextPageToken": "p2"}])

    def progress(state):
        if state["fetched"] == 1:
            cancel.set()

    result = client.scan(30, 100, "all", cancel, progress)
    assert result["status"] == "cancelled"
    assert len(result["messages"]) == 1
    assert result["discovered"] == 2
    assert len(client._service.calls) == 2


def test_cancelled_before_scan_does_not_call_sdk(client):
    client._service = Service()
    cancel = threading.Event()
    cancel.set()
    result = client.scan(30, 10, "all", cancel, None)
    assert result["status"] == "cancelled"
    assert not client._service.calls


@pytest.mark.parametrize("pages,expected", [
    ([ValueError("secret sdk url")], "failed"),
    ([{"messages": [{"id": "a1"}], "nextPageToken": "p2"}, ValueError("secret")], "partial"),
])
def test_listing_errors_never_become_empty_success(client, pages, expected):
    client._service = Service(pages)
    result = client.scan(30, 100, "all", threading.Event(), None)
    assert result["status"] == expected
    assert result["stop_reason"] == "list_error"
    assert "secret" not in json.dumps(result)


def test_failed_message_reported_as_partial(client):
    client._service = Service([{"messages": [{"id": "a1"}, {"id": "a2"}]}], {"a2": ValueError("secret")})
    result = client.scan(30, 10, "all", threading.Event(), None)
    assert result["status"] == "partial"
    assert result["stop_reason"] == "message_errors"
    assert result["fetched"] == result["failed"] == 1


def test_invalid_sender_counts_as_failed_without_poisoning_ingest(client):
    malformed = metadata("a2", extra=[{"name": "From", "value": "evil@example.org"}])
    client._service = Service([{"messages": [{"id": "a1"}, {"id": "a2"}]}], {"a2": malformed})
    result = client.scan(30, 10, "all", threading.Event(), None)
    assert result["status"] == "partial"
    assert result["failed"] == 1
    assert [message["id"] for message in result["messages"]] == ["a1"]


def test_repeated_page_token_is_partial_not_infinite(client):
    client._service = Service([
        {"messages": [{"id": "a1"}], "nextPageToken": "loop"},
        {"messages": [{"id": "a1"}], "nextPageToken": "loop"},
    ])
    result = client.scan(30, 10, "all", threading.Event(), None)
    assert result["status"] == "partial"
    assert result["stop_reason"] == "pagination_error"
    assert result["fetched"] == 1


def test_cancellation_interrupts_retry_backoff(client):
    client._service = Service()
    cancel = Mock()
    cancel.is_set.return_value = False
    cancel.wait.return_value = True
    factory = Mock(return_value=Request(TimeoutError()))
    with pytest.raises(gmail._Cancelled):
        client._request(factory, cancel)
    assert factory.call_count == 1
    cancel.wait.assert_called_once()


def test_retry_policy_recognizes_google_403_reason_but_not_permission_error():
    quota = Exception()
    quota.resp = SimpleNamespace(status=403)
    quota.content = b'{"error":{"errors":[{"reason":"userRateLimitExceeded"}]}}'
    assert gmail.GmailClient._retryable(quota)
    quota.content = b'{"error":{"errors":[{"reason":"forbidden"}]}}'
    assert not gmail.GmailClient._retryable(quota)


def synthetic_raw(signatures=None, extras=(), unsubscribe=None):
    signatures = signatures or ["a=rsa-sha256; h=from:list-unsubscribe:list-unsubscribe-post; d=example.com; s=test; b=fake"]
    lines = ["DKIM-Signature: " + value for value in signatures]
    lines += ["From: News <news@example.com>", "Subject: Synthetic fixture", "List-ID: News <news.example.com>",
              "List-Unsubscribe: " + (unsubscribe or "<https://example.com/leave?token=synthetic>"),
              "List-Unsubscribe-Post: List-Unsubscribe=One-Click", *extras, "", "Synthetic body.", ""]
    return "\r\n".join(lines).encode("ascii")


def install_fake_dkim(monkeypatch, outcomes=None, tamper_signed=False):
    calls = []

    class FakeDKIM:
        def __init__(self, raw, **kwargs):
            assert kwargs["timeout"] == gmail.DNS_TIMEOUT
            assert kwargs["minkey"] >= 1024
            parsed = BytesParser(policy=policy.default).parsebytes(raw)
            self.signed_headers = [(name.lower().encode(), (value + "\r\n").encode())
                                   for name, value in parsed.raw_items() if name.lower() in gmail.CRITICAL_HEADERS]
            if tamper_signed:
                self.signed_headers = [(name, b"<https://different.example/leave>\r\n" if name == b"list-unsubscribe" else value)
                                       for name, value in self.signed_headers]

        def verify(self, idx):
            calls.append(idx)
            value = (outcomes or {0: True}).get(idx, False)
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setitem(sys.modules, "dkim", SimpleNamespace(DKIM=FakeDKIM))
    return calls


def test_verify_uses_raw_and_binds_actual_signed_headers(client, monkeypatch):
    calls = install_fake_dkim(monkeypatch)
    client._service = Service(raw=synthetic_raw())
    result = client.verify_message("a1")
    assert result["authenticated"] is True
    assert result["verification_reason"] == "dkim_verified"
    assert result["list_unsubscribe"] == "<https://example.com/leave?token=synthetic>"
    assert calls == [0]
    assert [call[1]["format"] for call in client._service.calls] == ["metadata", "raw"]


def test_missing_dkim_dependency_does_not_fetch_raw(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "dkim", None)
    client._service = Service()
    client._messages["a1"] = gmail.normalize_message(metadata())
    result = client.verify_message("a1")
    assert result["authenticated"] is False
    assert result["verification_reason"] == "dkim_unavailable"
    assert result["sender_email"] == "news@example.com"
    assert not client._service.calls


def test_cold_preview_without_dkim_fetches_complete_metadata_only(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "dkim", None)
    client._service = Service()
    result = client.verify_message("a1")
    assert result["sender_email"] == "news@example.com"
    assert result["list_id"] == "news.example.com"
    assert result["authenticated"] is False
    assert result["verification_reason"] == "dkim_unavailable"
    assert len(client._service.calls) == 1
    assert client._service.calls[0][1]["format"] == "metadata"
    assert "From" in client._service.calls[0][1]["metadataHeaders"]


def test_cold_preview_with_unavailable_metadata_returns_empty(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "dkim", None)
    client._service = Service(messages={"a1": ValueError("secret")})
    assert client.verify_message("a1") == {}


def test_cold_preview_with_invalid_sender_returns_empty(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "dkim", None)
    client._service = Service(messages={"a1": metadata(extra=[{"name": "From", "value": "other@example.org"}])})
    assert client.verify_message("a1") == {}


def test_verification_failure_never_keeps_previous_authenticated_value(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "dkim", None)
    client._service = Service()
    client._messages["a1"] = {**gmail.normalize_message(metadata()), "authenticated": True}
    assert client.verify_message("a1")["authenticated"] is False


@pytest.mark.parametrize("extra", [
    "From: Other <other@example.com>",
    "List-Unsubscribe: <https://attacker.example/leave>",
    "List-Unsubscribe-Post: List-Unsubscribe=One-Click",
])
def test_duplicate_critical_headers_block_dkim_promotion(client, monkeypatch, extra):
    calls = install_fake_dkim(monkeypatch)
    client._service = Service(raw=synthetic_raw(extras=[extra]))
    result = client.verify_message("a1")
    assert result["authenticated"] is False
    assert result["verification_reason"] == "ambiguous_headers"
    assert calls == []


def test_missing_coverage_never_calls_crypto_verifier(client, monkeypatch):
    calls = install_fake_dkim(monkeypatch)
    client._service = Service(raw=synthetic_raw(signatures=["a=rsa-sha256; h=from:list-unsubscribe; b=fake"]))
    assert client.verify_message("a1")["authenticated"] is False
    assert calls == []


def test_valid_first_signature_cannot_borrow_second_signature_coverage(client, monkeypatch):
    calls = install_fake_dkim(monkeypatch, outcomes={0: True, 1: False})
    client._service = Service(raw=synthetic_raw(signatures=[
        "a=rsa-sha256; h=from; b=valid-but-insufficient",
        "a=rsa-sha256; h=from:list-unsubscribe:list-unsubscribe-post; b=invalid-but-covers",
    ]))
    assert client.verify_message("a1")["authenticated"] is False
    assert calls == [1]


def test_valid_second_signature_is_checked_at_its_actual_index(client, monkeypatch):
    calls = install_fake_dkim(monkeypatch, outcomes={0: False, 1: True})
    signature = "a=rsa-sha256; h=from:list-unsubscribe:list-unsubscribe-post; b=fake"
    client._service = Service(raw=synthetic_raw(signatures=[signature, signature]))
    assert client.verify_message("a1")["authenticated"] is True
    assert calls == [0, 1]


def test_verified_boolean_is_insufficient_when_signed_values_differ(client, monkeypatch):
    install_fake_dkim(monkeypatch, tamper_signed=True)
    client._service = Service(raw=synthetic_raw())
    assert client.verify_message("a1")["authenticated"] is False


@pytest.mark.parametrize("target", [
    "<https://one.example/leave>, <https://two.example/leave>",
    "<http://example.com/leave>",
    "<https://user:password@example.com/leave>",
    "<https://example.com:8443/leave>",
    "<https://example.com/leave#fragment>",
])
def test_ambiguous_or_invalid_https_target_remains_manual(client, monkeypatch, target):
    calls = install_fake_dkim(monkeypatch)
    client._service = Service(raw=synthetic_raw(unsubscribe=target))
    assert client.verify_message("a1")["authenticated"] is False
    assert calls == []


def test_dkim_failure_and_dns_exception_remain_unauthenticated(client, monkeypatch):
    install_fake_dkim(monkeypatch, outcomes={0: TimeoutError("secret DNS data")})
    client._service = Service(raw=synthetic_raw())
    result = client.verify_message("a1")
    assert result["authenticated"] is False
    assert "secret DNS" not in json.dumps(result)


def test_raw_size_preflight_blocks_download(client, monkeypatch):
    calls = install_fake_dkim(monkeypatch)
    oversized = metadata()
    oversized["sizeEstimate"] = gmail.MAX_RAW_BYTES + 1
    client._service = Service(messages={"a1": oversized})
    result = client.verify_message("a1")
    assert result["authenticated"] is False
    assert result["verification_reason"] == "size_limit"
    assert len(client._service.calls) == 1
    assert calls == []


def test_false_size_estimate_does_not_allow_oversized_payload(client, monkeypatch):
    calls = install_fake_dkim(monkeypatch)
    monkeypatch.setattr(gmail, "MAX_RAW_BYTES", 1000)
    client._service = Service(raw=b"x" * 1001)
    assert client.verify_message("a1")["authenticated"] is False
    assert calls == []


def credentials(scopes=gmail.SCOPES):
    return SimpleNamespace(valid=True, scopes=scopes, granted_scopes=scopes,
                           to_json=lambda: json.dumps({"token": "SYNTHETIC-NOT-A-CREDENTIAL", "scopes": list(scopes)}))


def test_atomic_token_write_is_private_and_does_not_touch_old_token(client, tmp_path):
    old = tmp_path / "token.json"
    old.write_text("OLD-SYNTHETIC-TOKEN")
    client._write_credentials(credentials())
    assert old.read_text() == "OLD-SYNTHETIC-TOKEN"
    assert client.token_path.stat().st_mode & 0o777 == 0o600
    assert not list(client.data_dir.glob(".token-*"))


def test_token_write_failure_preserves_previous_complete_file(client, monkeypatch):
    client._write_credentials(credentials())
    previous = client.token_path.read_bytes()
    monkeypatch.setattr(gmail.os, "replace", Mock(side_effect=OSError("test")))
    with pytest.raises(OSError):
        client._write_credentials(credentials())
    assert client.token_path.read_bytes() == previous
    assert not list(client.data_dir.glob(".token-*"))


def test_symlink_token_refused(client, tmp_path):
    client.data_dir.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    client.token_path.symlink_to(outside)
    with pytest.raises(gmail.GmailError):
        client._write_credentials(credentials())
    assert outside.read_text() == "untouched"


def test_old_modify_scope_is_not_loaded(client):
    client._write_credentials(credentials(("https://www.googleapis.com/auth/gmail.modify",)))
    assert client._load_credentials() is None


def test_symlink_data_directory_is_not_used_to_read_old_tokens(client, tmp_path):
    old_directory = tmp_path / "old"
    old_directory.mkdir()
    (old_directory / "token.json").write_text("must not read this")
    client.data_dir.symlink_to(old_directory, target_is_directory=True)
    with pytest.raises(gmail.GmailError, match="路径无效"):
        client._load_credentials()


def test_connect_uses_readonly_finite_timeout_and_returns_hashed_account(client, monkeypatch):
    import googleapiclient.discovery
    import google_auth_httplib2
    import httplib2
    fake_credentials = credentials()
    monkeypatch.setattr(client, "_load_credentials", lambda: None)
    monkeypatch.setattr(client, "_oauth_credentials", lambda: fake_credentials)
    http = Mock(return_value=object())
    monkeypatch.setattr(httplib2, "Http", http)
    monkeypatch.setattr(google_auth_httplib2, "AuthorizedHttp", Mock(return_value=object()))
    build = Mock(return_value=Service())
    monkeypatch.setattr(googleapiclient.discovery, "build", build)
    result = client.connect()
    assert result == {"email": "test@example.com", "account_id": hashlib.sha256(b"test@example.com").hexdigest()}
    assert "token" not in result
    http.assert_called_once_with(timeout=gmail.HTTP_TIMEOUT)
    assert build.call_args.kwargs["static_discovery"] is True


def test_broader_oauth_grant_is_rejected(client, monkeypatch):
    monkeypatch.setattr(client, "_load_credentials", lambda: None)
    monkeypatch.setattr(client, "_oauth_credentials", lambda: credentials((*gmail.SCOPES, "https://www.googleapis.com/auth/gmail.modify")))
    with pytest.raises(gmail.GmailError, match="只读授权"):
        client.connect()
    assert client._service is None
    assert not client.token_path.exists()


def test_oauth_wait_and_exchange_requests_have_timeouts(client, monkeypatch):
    # P1 validates the desktop client JSON before constructing the SDK flow.
    client.credentials_path.write_text(json.dumps({"installed": {"redirect_uris": ["http://localhost"], "client_id": "synthetic.apps.googleusercontent.com", "client_secret": "synthetic", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}))
    from google_auth_oauthlib.flow import InstalledAppFlow
    request = Mock(return_value="synthetic-response")
    flow = SimpleNamespace(oauth2session=SimpleNamespace(request=request), run_local_server=Mock(return_value=credentials()))
    constructor = Mock(return_value=flow)
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", constructor)
    client._oauth_credentials()
    assert constructor.call_args.kwargs["scopes"] == gmail.SCOPES
    assert flow.run_local_server.call_args.kwargs["timeout_seconds"] == gmail.OAUTH_TIMEOUT
    assert flow.run_local_server.call_args.kwargs["authorization_prompt_message"] == ""
    flow.oauth2session.request("POST", "https://oauth.invalid", timeout=None)
    assert request.call_args.kwargs["timeout"] == gmail.HTTP_TIMEOUT
