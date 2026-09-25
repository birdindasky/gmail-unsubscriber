from pathlib import Path
import threading
from unittest.mock import Mock

import pytest
from gmail_unsubscriber.application import Application
from gmail_unsubscriber.core import DomainError


def test_demo_startup_does_not_construct_gmail(tmp_path, monkeypatch):
    monkeypatch.setattr("socket.create_connection", Mock(side_effect=AssertionError("no network")))
    app = Application(tmp_path)
    state = app.state()
    assert state["account"]["mode"] == "demo"
    assert state["account"]["connected"]
    assert state["subscriptions"]
    assert app.client is None
    assert (tmp_path / "workspace.sqlite3").stat().st_mode & 0o777 == 0o600


def test_live_start_is_disconnected_without_touching_credentials(tmp_path):
    client = Mock()
    app = Application(tmp_path, mode="live", credentials_path=tmp_path / "does-not-exist", gmail_client=client)
    assert not app.state()["account"]["connected"]
    assert not client.mock_calls
    with pytest.raises(DomainError):
        app.scan({})
    with pytest.raises(DomainError):
        app.reset_demo()


@pytest.mark.parametrize("options", [{"limit":0},{"limit":-1},{"limit":2001},{"limit":True},{"days":-1},{"scope":"raw-query"}])
def test_scan_bounds(options):
    with pytest.raises(DomainError):
        Application.scan_options(options)


def test_confirmation_cannot_be_string_true(tmp_path):
    app = Application(tmp_path)
    with pytest.raises(DomainError):
        app.execute({"plan_id":"fake","confirmed":"true"})


def test_demo_scan_cancel_and_persistence(tmp_path):
    app = Application(tmp_path)
    count = len(app.state()["subscriptions"])
    app.scan({"limit":500})
    with pytest.raises(DomainError):
        app.scan({})
    app.cancel_scan()
    app._worker.join(3)
    state = app.state()
    assert not state["job"]["running"]
    assert state["job"]["partial"]
    assert len(state["subscriptions"]) == count
    again = Application(tmp_path)
    assert len(again.state()["subscriptions"]) == count


def test_protection_survives_restart(tmp_path):
    app = Application(tmp_path)
    app.protect({"domain":"shop-weekly.example","enabled":True})
    again = Application(tmp_path)
    rows = [s for s in again.state()["subscriptions"] if s["domain"] == "shop-weekly.example"]
    assert rows and all(s["protected"] for s in rows)


def test_demo_reset_keeps_mode_and_replaces_only_demo(tmp_path):
    app = Application(tmp_path)
    app.protect({"domain":"shop-weekly.example","enabled":True})
    state = app.reset_demo()
    assert state["account"]["mode"] == "demo"
    rows = [s for s in state["subscriptions"] if s["domain"] == "shop-weekly.example"]
    assert rows and not any(s["protected"] for s in rows)


def test_manual_link_selects_connected_gmail_account(tmp_path):
    from urllib.parse import parse_qs, urlsplit
    from gmail_unsubscriber import demo
    app = Application(tmp_path, mode="live", gmail_client=Mock())
    app.account.update(connected=True, email="reader+second@example.com")
    app.engine.ingest(demo.messages())
    row = app.state()["subscriptions"][0]
    target = urlsplit(app.manual_link(row["id"]))
    assert target.scheme == "https" and target.netloc == "mail.google.com"
    assert target.path == "/mail/"
    assert parse_qs(target.query) == {"authuser": ["reader+second@example.com"]}
    assert target.fragment.startswith("all/")
