# -*- coding: utf-8 -*-
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unsubscriber


def test_unsubscribe_via_one_click_success():
    with patch("unsubscriber.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        result = unsubscriber.unsubscribe_via_one_click("https://example.com/unsub")
    assert result["success"] is True
    assert result["method"] == "one_click_post"


def test_unsubscribe_via_one_click_failure():
    with patch("unsubscriber.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=404)
        result = unsubscriber.unsubscribe_via_one_click("https://example.com/unsub")
    assert result["success"] is False


def test_unsubscribe_via_mailto_sends_email():
    mock_service = MagicMock()
    mock_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "sent-id"}

    mailto_info = {"mailto_email": "unsub@example.com", "mailto_subject": "unsubscribe"}
    result = unsubscriber.unsubscribe_via_mailto(mailto_info, service=mock_service)

    assert result["success"] is True
    assert result["method"] == "mailto"
    mock_service.users.return_value.messages.return_value.send.assert_called_once()


def test_unsubscribe_via_mailto_no_service():
    mailto_info = {"mailto_email": "unsub@example.com", "mailto_subject": "unsubscribe"}
    result = unsubscriber.unsubscribe_via_mailto(mailto_info, service=None)
    assert result["success"] is False
    assert "service" in result["message"]


def test_unsubscribe_via_mailto_no_email():
    result = unsubscriber.unsubscribe_via_mailto({"mailto_email": ""}, service=MagicMock())
    assert result["success"] is False


def test_create_or_get_label_existing():
    mock_service = MagicMock()
    mock_service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"id": "Label_123", "name": "已退订"}]
    }
    label_id = unsubscriber.create_or_get_label(mock_service, "已退订")
    assert label_id == "Label_123"
    mock_service.users.return_value.labels.return_value.create.assert_not_called()


def test_create_or_get_label_creates_new():
    mock_service = MagicMock()
    mock_service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": []
    }
    mock_service.users.return_value.labels.return_value.create.return_value.execute.return_value = {
        "id": "Label_new", "name": "已退订"
    }
    label_id = unsubscriber.create_or_get_label(mock_service, "已退订")
    assert label_id == "Label_new"


def test_label_sender_emails_calls_modify():
    mock_service = MagicMock()
    unsubscriber.label_sender_emails(mock_service, ["id1", "id2"], "Label_123")
    assert mock_service.users.return_value.messages.return_value.modify.call_count == 2


def test_archive_sender_emails_removes_inbox():
    mock_service = MagicMock()
    unsubscriber.archive_sender_emails(mock_service, ["id1", "id2"])
    assert mock_service.users.return_value.messages.return_value.modify.call_count == 2
    # 验证 INBOX 出现在调用参数中
    all_calls = str(mock_service.users.return_value.messages.return_value.modify.call_args_list)
    assert "INBOX" in all_calls
