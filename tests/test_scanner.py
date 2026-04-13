# -*- coding: utf-8 -*-
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scanner


def _make_msg(msg_id, sender_email, subject="Test", labels=None):
    """构造模拟的 Gmail API 邮件对象。"""
    return {
        "id": msg_id,
        "threadId": f"thread-{msg_id}",
        "snippet": "test snippet",
        "labelIds": labels or [],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": f"Sender <{sender_email}>"},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Thu, 10 Apr 2026 10:00:00 +0800"},
            ],
            "body": {"data": ""},
            "parts": [],
        },
    }


def test_filter_already_unsubscribed(monkeypatch, tmp_path):
    """已退订的发件人不应出现在扫描结果中。"""
    import config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    import importlib
    import database
    importlib.reload(database)
    database.init_db()
    database.record_unsubscribe("spam@old.com", "Old Spam", "one_click", True)

    msg1 = _make_msg("id1", "spam@old.com", "广告")
    msg2 = _make_msg("id2", "legit@work.com", "Meeting")

    mock_service = MagicMock()

    with patch.object(scanner, "_list_all_messages", return_value=[{"id": "id1"}, {"id": "id2"}]), \
         patch.object(scanner, "_fetch_messages_batch", return_value=[msg1, msg2]):
        results = scanner.scan_emails(mock_service, days=30)

    sender_emails = [r["sender_email"] for r in results]
    assert "spam@old.com" not in sender_emails
    assert "legit@work.com" in sender_emails


def test_parse_sender_extracts_email():
    email_addr, domain = scanner._parse_sender("Google <no-reply@google.com>")
    assert email_addr == "no-reply@google.com"
    assert domain == "google.com"


def test_parse_sender_bare_email():
    email_addr, domain = scanner._parse_sender("spam@example.com")
    assert email_addr == "spam@example.com"
    assert domain == "example.com"


def test_fetch_messages_batch_returns_list():
    """_fetch_messages_batch 应返回解析后的邮件列表。"""
    msg = _make_msg("abc", "test@example.com")
    mock_service = MagicMock()

    captured_callback = {}

    def fake_batch_factory(callback):
        captured_callback["fn"] = callback
        batch = MagicMock()

        def fake_execute():
            captured_callback["fn"]("0", msg, None)

        batch.execute = fake_execute
        batch.add = MagicMock()
        batch._requests = {"0": True}
        return batch

    mock_service.new_batch_http_request.side_effect = fake_batch_factory

    results = scanner._fetch_messages_batch(mock_service, [{"id": "abc"}])
    assert len(results) == 1
    assert results[0]["sender_email"] == "test@example.com"
