import json
import threading
from types import SimpleNamespace
import pytest
from gmail_unsubscriber.gmail import GmailClient, GmailError, connection_error
from test_gmail import Service


def test_client_missing_invalid_and_valid_are_distinct(tmp_path):
    client = GmailClient(str(tmp_path / 'data'), str(tmp_path / 'client.json'))
    with pytest.raises(GmailError) as caught:
        client._validate_client_file()
    assert caught.value.code == 'credentials_missing'
    client.credentials_path.write_text('{"client_secret":"SYNTHETIC_SECRET"}')
    with pytest.raises(GmailError) as caught:
        client._validate_client_file()
    assert caught.value.code == 'credentials_invalid'
    assert 'SYNTHETIC_SECRET' not in str(caught.value)
    client.credentials_path.write_text(json.dumps({'installed':{'redirect_uris':['http://localhost'], 'client_id':'synthetic', 'client_secret':'SYNTHETIC_SECRET','auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token'}}))
    client._validate_client_file()
    assert client.credentials_validity == 'valid'
    assert client._service is None


@pytest.mark.parametrize('error,stage,code', [
    (OSError('SYNTHETIC_SECRET'), 'profile', 'network_failed'),
    (TimeoutError('SYNTHETIC_SECRET'), 'authorization', 'authorization_incomplete'),
    (type('RefreshError',(Exception,),{})('SYNTHETIC_SECRET'), 'refresh', 'token_expired'),
])
def test_safe_connection_classifier(error, stage, code):
    result = connection_error(error, stage)
    assert result.code == code and 'SYNTHETIC_SECRET' not in str(result)


def test_flush_before_next_page_and_cancel_flushes_tail(tmp_path):
    client = GmailClient(str(tmp_path), str(tmp_path / 'synthetic.json'))
    client._service = Service([{'messages':[{'id':'a1'}], 'nextPageToken':'two'}, {'messages':[{'id':'a2'}, {'id':'a3'}]}])
    cancel = threading.Event()
    batches = []
    def save(rows, status):
        batches.append([row['id'] for row in rows])
        if len(batches) == 1:
            assert len(client._service.calls) == 2
    def progress(status):
        if status['fetched'] == 2:
            cancel.set()
    result = client.scan(30,100,'promotions',cancel,progress,on_batch=save)
    assert batches == [['a1'],['a2']]
    assert result['status'] == 'cancelled' and result['messages'] == []


def test_disk_failure_is_not_swallowed_as_bad_message(tmp_path):
    client = GmailClient(str(tmp_path), str(tmp_path / 'synthetic.json'))
    client._service = Service([{'messages':[{'id':'a1'}], 'nextPageToken':'two'}, {'messages':[{'id':'a2'}]}])
    saved = []
    def save(rows, status):
        if saved:
            raise OSError('synthetic disk full')
        saved.extend(rows)
    with pytest.raises(OSError, match='disk full'):
        client.scan(30,100,'promotions',threading.Event(),None,on_batch=save)
    assert [r['id'] for r in saved] == ['a1']
