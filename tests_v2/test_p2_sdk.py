"""Real SDK request encoding, with synthetic HTTP responses and no network."""
import json
import threading
from urllib.parse import parse_qs, urlsplit

import httplib2
from googleapiclient.discovery import build

from gmail_unsubscriber.gmail import GmailClient, METADATA_HEADERS


class SyntheticMetadataHttp:
    def __init__(self):
        self.header_queries = []

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        query = parse_qs(urlsplit(uri).query)
        assert method == "GET"
        if urlsplit(uri).path.endswith("/messages"):
            result = {"messages": [{"id": "synthetic1"}]}
        else:
            assert query["format"] == ["metadata"], "raw reads are forbidden in this fixture"
            requested = query.get("metadataHeaders", [])
            self.header_queries.append(requested)
            available = [{"name": "From", "value": "Example <sender@example.test>"},
                         {"name": "Subject", "value": "Synthetic subject"},
                         {"name": "List-ID", "value": "News <news.example.test>"}]
            # Model metadataHeaders filtering at the HTTP boundary. A tuple
            # string is not a header name, so it must not return all headers.
            result = {"id": "synthetic1", "internalDate": "1700000000000",
                      "sizeEstimate": 0,
                      "payload": {"headers": [h for h in available if h["name"] in requested]}}
        return httplib2.Response({"status": "200", "content-type": "application/json"}), json.dumps(result).encode()


def sdk_client(tmp_path):
    http = SyntheticMetadataHttp()
    client = GmailClient(str(tmp_path), str(tmp_path / "synthetic-client.json"))
    client._service = build("gmail", "v1", http=http, static_discovery=True, cache_discovery=False)
    return client, http


def test_real_sdk_scan_encodes_repeated_header_names(tmp_path):
    client, http = sdk_client(tmp_path)
    result = client.scan(30, 100, "promotions", threading.Event(), None)
    assert http.header_queries == [list(METADATA_HEADERS)]
    assert result["fetched"] == 1 and result["failed"] == 0
    assert result["messages"][0]["sender_email"] == "sender@example.test"
    assert result["messages"][0]["authenticated"] is False


def test_real_sdk_fallback_metadata_encodes_repeated_header_names(tmp_path):
    client, http = sdk_client(tmp_path)
    result = client.verify_message("synthetic1")
    assert http.header_queries == [list(METADATA_HEADERS)]
    assert result["sender_email"] == "sender@example.test"
    assert result["authenticated"] is False
    assert result["verification_reason"] in {"size_limit", "dkim_unavailable"}
