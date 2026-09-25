"""P1 orchestration: isolated service fakes, no credential or network access."""
import json
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from gmail_unsubscriber.application import Application
from gmail_unsubscriber.core import DomainError
from gmail_unsubscriber.gmail import GmailClient, GmailError
from test_gmail import Service, metadata


def live(tmp_path, client=None):
    app = Application(tmp_path / 'data', mode='live', credentials_path=tmp_path / 'synthetic.json', gmail_client=client)
    app.account.update(connected=True, email='synthetic@example.com')
    return app


def done(app):
    app._worker.join(4)
    assert not app._worker.is_alive()
    return app.state()


def test_default_and_setup_never_reads_file(tmp_path, monkeypatch):
    app = live(tmp_path)
    app.credentials_path.write_text('SYNTHETIC_SECRET')
    monkeypatch.setattr(Path, 'open', Mock(side_effect=AssertionError('must not read')))
    assert Application.scan_options({}) == (30, 100, 'promotions')
    setup = app.state()['setup']
    assert setup['exists'] and setup['validity'] == 'unchecked'


@pytest.mark.parametrize('code', ['credentials_missing', 'credentials_invalid', 'authorization_incomplete', 'token_expired', 'scope_mismatch', 'network_failed'])
def test_connect_classified_failure_then_retry(tmp_path, code):
    client = Mock()
    client.connect.side_effect = [GmailError('安全的重试说明', code), {'email':'synthetic@example.com', 'account_id':'fixture'}]
    app = live(tmp_path, client)
    app.account['connected'] = False
    app.connect()
    state = done(app)
    assert state['job']['error'] == {'code': code, 'message':'安全的重试说明'}
    assert not state['account']['connected']
    app.connect()
    assert done(app)['account']['connected']


def test_raw_sdk_error_never_exposed(tmp_path):
    client = Mock()
    client.connect.side_effect = RuntimeError('SYNTHETIC_SECRET https://auth.invalid/?token=secret')
    app = live(tmp_path, client)
    app.connect()
    state = done(app)
    assert 'SYNTHETIC_SECRET' not in json.dumps(state)
    assert state['job']['error']['code'] == 'operation_failed'


def test_slow_preview_cancel_double_click_and_protection(tmp_path):
    entered, release = threading.Event(), threading.Event()
    client = Mock()
    def verify(identifier):
        entered.set()
        assert release.wait(3)
        return {}
    client.verify_message.side_effect = verify
    app = live(tmp_path, client)
    from gmail_unsubscriber.gmail import normalize_message
    app.engine.ingest([normalize_message(metadata())])
    item = app.state()['subscriptions'][0]
    assert item['verification_status'] == 'pending' and item['recommendation'] == 'review'
    app.start_preview([item['id']])
    assert entered.wait(2)
    assert app.state()['job']['items'][0]['phase'] == 'verifying'
    with pytest.raises(DomainError, match='上一项'):
        app.start_preview([item['id']])
    app.protect({'domain':'example.com'})
    app.cancel_job()
    assert app.state()['job']['phase'] == 'stopping'
    release.set()
    state = done(app)
    assert state['job']['plan'] is None
    assert state['job']['phase'] == 'cancelled'
    assert state['subscriptions'][0]['protected']
    assert state['subscriptions'][0]['verification_status'] == 'unverifiable'


def test_slow_execution_progress_cancel_and_reload_are_readonly(tmp_path):
    app = Application(tmp_path)
    rows = [r for r in app.state()['subscriptions'] if r['recommendation'] == 'review' and r['method'] == 'one_click'][:2]
    assert len(rows) == 2
    plan = app.preview([r['id'] for r in rows])
    entered, release = threading.Event(), threading.Event()
    calls = []
    def transport(url):
        calls.append(url)
        entered.set()
        assert release.wait(3)
        raise TimeoutError('SYNTHETIC_SECRET')
    app.engine.transport = transport
    app.start_execute({'plan_id':plan['id'], 'confirmed':True})
    assert entered.wait(2)
    for _ in range(4):
        items = app.state()['job']['items']
        assert items[0]['phase'] == 'sending' and items[1]['phase'] == 'waiting'
    app.cancel_job()
    release.set()
    state = done(app)
    assert len(calls) == 1
    assert state['job']['result']['items'][0]['status'] == 'uncertain'
    assert state['job']['result']['items'][1]['status'] == 'blocked'
    app.execute({'plan_id':plan['id'], 'confirmed':True})
    assert len(calls) == 1
    assert 'SYNTHETIC_SECRET' not in json.dumps(state)


def test_scan_batches_persist_and_duplicate_counts(tmp_path):
    client = GmailClient(str(tmp_path / 'client'), str(tmp_path / 'synthetic.json'))
    app = live(tmp_path, client)
    for imported, duplicate in [(2,0),(0,2)]:
        client._service = Service([{'messages':[{'id':'a1'}], 'nextPageToken':'two'}, {'messages':[{'id':'a2'}]}])
        app.scan({})
        state = done(app)
        assert state['scan']['status'] == 'completed'
        assert state['scan']['imported'] == imported
        assert state['scan']['duplicates'] == duplicate
        assert state['scan']['saved'] == 2 and state['stats']['messages'] == 2
        assert state['scan']['days'] == 30 and state['scan']['limit'] == 100
        assert state['scan']['started_at'] and state['scan']['ended_at']

from test_dkim_crypto import ephemeral_key, local_dns, no_external_network, sign, BASE


@pytest.mark.parametrize('variant,ready', [('valid',1),('tampered',0),('unsigned',0),('missing_dependency',0)])
def test_real_shape_scan_to_preview_uses_real_crypto(tmp_path, monkeypatch, ephemeral_key, local_dns, variant, ready):
    import sys
    from email.parser import BytesParser
    from email import policy
    # Keep the public-shaped endpoint required by production URL policy.
    body = BASE.replace(b"https://example.test/", b"https://example.com/")
    raw = sign(body, ephemeral_key[0])
    if variant == 'tampered':
        raw = raw.replace(b'Hello synthetic body.', b'Changed synthetic body.')
    elif variant == 'unsigned':
        raw = body
    elif variant == 'missing_dependency':
        monkeypatch.setitem(sys.modules, 'dkim', None)
    message = {'id':'a1', 'internalDate':'1700000000000','sizeEstimate':len(raw),
               'payload':{'headers':[{'name':k, 'value':v} for k,v in BytesParser(policy=policy.default).parsebytes(raw).raw_items()]}}
    client = GmailClient(str(tmp_path / 'client'), str(tmp_path / 'synthetic.json'))
    client._service = Service([{'messages':[{'id':'a1'}]}], {'a1':message}, raw=raw)
    app = live(tmp_path, client)
    transport = Mock(side_effect=AssertionError('preview must never send'))
    app.engine.transport = transport
    app.scan({})
    state = done(app)
    row = state['subscriptions'][0]
    assert row['verification_status'] == 'pending'
    assert row['recommendation'] == 'review'
    assert not transport.called
    app.start_preview([row['id']])
    state = done(app)
    assert state['job']['plan']['summary']['ready'] == ready
    assert state['subscriptions'][0]['verification_status'] == ('verified' if ready else 'unverifiable')
    assert not transport.called
    assert 'list=original' not in json.dumps(state)


@pytest.mark.parametrize('kind,expected', [('empty','empty'),('limit','limit'),('network','network_interrupted'),('partial','partial')])
def test_scan_ending_is_distinct(tmp_path, monkeypatch, kind, expected):
    client = GmailClient(str(tmp_path / 'client'), str(tmp_path / 'synthetic.json'))
    if kind == 'empty':
        pages, messages = [{}], {}
    elif kind == 'limit':
        pages, messages = [{'messages':[{'id':'a1'}], 'nextPageToken':'more'}], {}
    elif kind == 'network':
        pages, messages = [{'messages':[{'id':'a1'}], 'nextPageToken':'more'}, OSError('SYNTHETIC_SECRET')], {}
        monkeypatch.setattr('gmail_unsubscriber.gmail.MAX_ATTEMPTS', 1)
    else:
        pages, messages = [{'messages':[{'id':'a1'},{'id':'a2'}]}], {'a2':ValueError('SYNTHETIC_SECRET')}
    client._service = Service(pages, messages)
    app = live(tmp_path, client)
    app.scan({'limit':1} if kind == 'limit' else {})
    state = done(app)
    assert state['scan']['status'] == expected
    assert 'SYNTHETIC_SECRET' not in json.dumps(state)
    assert sum(call[0] == 'list' for call in client._service.calls) == (2 if kind == 'network' else 1)


def test_verification_progress_labels_preserve_selected_order(tmp_path):
    from gmail_unsubscriber.gmail import normalize_message
    first = normalize_message(metadata('a1'))
    second = dict(first, id='a2', sender_email='second@other.example.com', sender_name='Second list', list_id='second.other.example.com')
    entered, release = threading.Event(), threading.Event()
    observed = []
    client = Mock()
    def verify(identifier):
        observed.append(identifier)
        if len(observed) == 1:
            entered.set()
            assert release.wait(3)
        return {}
    client.verify_message.side_effect = verify
    app = live(tmp_path, client)
    app.engine.ingest([first, second])
    selected = list(reversed(app.state()['subscriptions']))
    ids = [row['id'] for row in selected]
    message_ids = app.engine.message_ids_for(ids)
    app.start_preview(ids)
    assert entered.wait(2)
    items = app.state()['job']['items']
    assert [(item['id'],item['title'],item['sender_email']) for item in items] == [(row['id'],row['title'],row['sender_email']) for row in selected]
    assert items[0]['phase'] == 'verifying' and items[1]['phase'] == 'waiting'
    release.set()
    done(app)
    assert observed == message_ids
