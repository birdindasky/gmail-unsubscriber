# -*- coding: utf-8 -*-
import os
import sys
import importlib
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = str(tmp_path / "test.db")
    import config
    monkeypatch.setattr(config, "DB_PATH", db_file)
    import database
    importlib.reload(database)
    database.init_db()
    return db_file


def test_init_db_creates_tables(tmp_db):
    import sqlite3
    conn = sqlite3.connect(tmp_db)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "unsubscribed_senders" in tables
    assert "scan_history" in tables
    assert "user_whitelist" in tables


def test_record_unsubscribe_and_check(tmp_db):
    import database
    database.record_unsubscribe("spam@example.com", "Spam Co", "one_click", True)
    assert database.is_already_unsubscribed("spam@example.com") is True


def test_is_already_unsubscribed_false_for_unknown(tmp_db):
    import database
    assert database.is_already_unsubscribed("unknown@example.com") is False


def test_failed_unsubscribe_not_counted_as_done(tmp_db):
    import database
    database.record_unsubscribe("fail@example.com", "Fail Co", "link_click", False)
    assert database.is_already_unsubscribed("fail@example.com") is False


def test_get_history_returns_records(tmp_db):
    import database
    database.record_unsubscribe("a@x.com", "A", "one_click", True)
    database.record_unsubscribe("b@x.com", "B", "mailto", True)
    history = database.get_history(limit=10)
    assert len(history) == 2
    emails = {r["sender_email"] for r in history}
    assert "a@x.com" in emails
    assert "b@x.com" in emails


def test_record_scan(tmp_db):
    import database
    database.record_scan(days=30, total_emails=500, candidates=15, unsubscribed=10)
    import sqlite3
    conn = sqlite3.connect(tmp_db)
    row = conn.execute("SELECT * FROM scan_history").fetchone()
    conn.close()
    assert row is not None


def test_add_to_whitelist_and_get(tmp_db):
    import database
    result = database.add_to_user_whitelist("mybank.com")
    assert result is True
    domains = database.get_user_whitelist()
    assert "mybank.com" in domains


def test_add_to_whitelist_duplicate_returns_false(tmp_db):
    import database
    database.add_to_user_whitelist("mybank.com")
    result = database.add_to_user_whitelist("mybank.com")
    assert result is False
