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


def test_scan_emails_passes_max_messages():
    mock_service = MagicMock()
    parsed = scanner._parse_message(_make_msg("id1", "test@example.com"))

    with patch.object(scanner, "_list_all_messages", return_value=[{"id": "id1"}]) as mock_list, \
         patch.object(scanner, "_fetch_messages_batch", return_value=[parsed]):
        scanner.scan_emails(mock_service, days=0, scan_all=True, max_messages=123)

    mock_list.assert_called_once_with(
        mock_service,
        scanner.ALL_MAIL_BASE_EXCLUDES,
        max_messages=123,
    )


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
        results = scanner._fetch_messages_batch(mock_service, stubs, workers=3, request_sleep=0)

    assert len(results) == 6
    assert call_count["n"] == 6


def test_get_fetch_settings_by_size():
    assert scanner._get_fetch_settings(100) == (3, 0.15)
    assert scanner._get_fetch_settings(300) == (4, 0.08)
    assert scanner._get_fetch_settings(1000) == (5, 0.05)
    assert scanner._get_fetch_settings(5000) == (6, 0.03)


def test_list_all_messages_respects_limit():
    mock_service = MagicMock()
    first_page = {
        "messages": [{"id": "1"}, {"id": "2"}],
        "nextPageToken": "page-2",
    }
    second_page = {
        "messages": [{"id": "3"}, {"id": "4"}],
    }
    mock_service.users.return_value.messages.return_value.list.side_effect = [
        MagicMock(execute=MagicMock(return_value=first_page)),
        MagicMock(execute=MagicMock(return_value=second_page)),
    ]

    with patch("scanner.time.time", side_effect=[0, 1]):
        results = scanner._list_all_messages(mock_service, "category:promotions", max_messages=3)

    assert results == [{"id": "1"}, {"id": "2"}, {"id": "3"}]


def test_list_all_messages_prints_progress(capsys):
    mock_service = MagicMock()
    first_page = {"messages": [{"id": "1"}]}
    mock_service.users.return_value.messages.return_value.list.return_value.execute.return_value = first_page

    with patch("scanner.time.time", return_value=0):
        scanner._list_all_messages(mock_service, "category:promotions")

    captured = capsys.readouterr()
    assert "List progress" in captured.out


def test_scan_all_query_excludes_non_inbox_buckets():
    mock_service = MagicMock()
    parsed = scanner._parse_message(_make_msg("id1", "test@example.com"))

    with patch.object(scanner, "_list_all_messages", return_value=[{"id": "id1"}]) as mock_list, \
         patch.object(scanner, "_fetch_messages_batch", return_value=[parsed]):
        scanner.scan_emails(mock_service, days=0, scan_all=True)

    query = mock_list.call_args.args[1]
    assert "-in:sent" in query
    assert "-in:drafts" in query
    assert "-in:trash" in query
    assert "-in:spam" in query


def test_fetch_one_logs_warning_when_retries_exhausted(caplog):
    """Verify a message whose API call 429s 3 times is reported, not silent."""
    import logging
    from googleapiclient.errors import HttpError

    fake_service = MagicMock()

    class _Resp:
        status = 429
        reason = "rate"

    err = HttpError(_Resp(), b"rate limited")
    fake_service.users().messages().get.return_value.execute.side_effect = err

    with patch.object(scanner, "_get_thread_service", return_value=fake_service), \
         patch.object(scanner.time, "sleep", return_value=None), \
         caplog.at_level(logging.WARNING, logger="scanner"):
        result = scanner._fetch_messages_batch(
            fake_service, [{"id": "abc123"}], workers=1, request_sleep=0
        )

    assert result == []
    assert any("abc123" in r.message and "retries" in r.message for r in caplog.records)
