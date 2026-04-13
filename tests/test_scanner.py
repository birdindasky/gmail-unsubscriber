# -*- coding: utf-8 -*-
import os
import sys
import threading
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

    # _fetch_messages_batch 返回已解析的邮件，所以需要先解析
    parsed1 = scanner._parse_message(msg1)
    parsed2 = scanner._parse_message(msg2)

    mock_service = MagicMock()

    with patch.object(scanner, "_list_all_messages", return_value=[{"id": "id1"}, {"id": "id2"}]), \
         patch.object(scanner, "_fetch_messages_batch", return_value=[parsed1, parsed2]):
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
    """_fetch_messages_batch 应返回解析后的邮件列表（逐封请求模式）。"""
    msg = _make_msg("abc", "test@example.com")
    mock_service = MagicMock()

    mock_service.users.return_value.messages.return_value.get.return_value.execute.return_value = msg

    with patch("scanner._get_thread_service", return_value=mock_service), \
         patch("scanner.time") as mock_time:
        mock_time.sleep = MagicMock()
        results = scanner._fetch_messages_batch(mock_service, [{"id": "abc"}])

    assert len(results) == 1
    assert results[0]["sender_email"] == "test@example.com"


def test_fetch_messages_batch_concurrent():
    """_fetch_messages_batch 应使用多线程并发获取邮件。"""
    msgs = [_make_msg(f"id-{i}", f"test{i}@example.com") for i in range(6)]
    stubs = [{"id": f"id-{i}"} for i in range(6)]

    call_count = {"n": 0}
    original_lock = threading.Lock()

    def mock_execute_factory(msg):
        def mock_execute():
            with original_lock:
                call_count["n"] += 1
            return msg
        return mock_execute

    mock_service = MagicMock()
    def mock_get(**kwargs):
        msg_id = kwargs["id"]
        idx = int(msg_id.split("-")[1])
        result = MagicMock()
        result.execute = mock_execute_factory(msgs[idx])
        return result

    mock_service.users.return_value.messages.return_value.get = mock_get

    with patch("scanner._get_thread_service", return_value=mock_service), \
         patch("scanner.time") as mock_time:
        mock_time.sleep = MagicMock()
        results = scanner._fetch_messages_batch(mock_service, stubs)

    assert len(results) == 6
    assert call_count["n"] == 6
