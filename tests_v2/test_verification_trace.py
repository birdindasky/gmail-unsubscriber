"""Synthetic trace checks. No Gmail, DNS or sender endpoints."""
import json
import threading
from unittest.mock import Mock

import dkim
import pytest

from gmail_unsubscriber.gmail import GmailClient, normalize_message
from gmail_unsubscriber.verification_trace import TraceError, VerificationTrace
from test_gmail import Service, metadata, synthetic_raw
from test_dkim_crypto import ephemeral_key, sign, BASE


def records(trace):
    return [json.loads(line) for line in trace.path.read_text().splitlines()]


def test_real_crypto_trace_is_private_and_ordered(tmp_path, monkeypatch, ephemeral_key):
    monkeypatch.setattr(dkim.DKIM.verify, '__defaults__', (0, lambda name, timeout: ephemeral_key.dns_record))
    client = GmailClient(str(tmp_path), str(tmp_path/'absent.json'))
    client._service = Service(raw=sign(BASE, ephemeral_key.private_pem))
    trace = VerificationTrace(tmp_path/'traces')
    assert client.verify_message('a1', trace=trace)['authenticated'] is True
    events = records(trace)
    assert [(e['operation'],e['state']) for e in events] == [
        ('verification','start'),('metadata','start'),('metadata','ok'),
        ('raw','start'),('raw','ok'),('dkim','start'),('dns','start'),
        ('dns','ok'),('dkim','verified'),('verification','verified')]
    assert [e['sequence'] for e in events] == list(range(1,len(events)+1))
    assert all(set(e)=={'sequence','time','operation','state','attempt','reason'} for e in events)
    encoded = trace.path.read_text()
    for secret in ('a1','example.test','Fixture','http','@','domainkey','private'):
        assert secret not in encoded
    assert trace.path.stat().st_mode & 0o777 == 0o600
    assert trace.path.parent.stat().st_mode & 0o777 == 0o700


def test_dns_failure_preserves_safe_failure_and_no_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(dkim, 'get_txt', Mock(side_effect=TimeoutError('PRIVATE_QUERY')))
    # Invalid signature reaches the crypto failure path without network; real
    # DNS failure itself is exercised using a fake verifier callback below.
    class Verifier:
        def __init__(self, *a, **kw): pass
        def verify(self, idx, dnsfunc): return dnsfunc(b'PRIVATE_QUERY')
    monkeypatch.setattr(dkim, 'DKIM', Verifier)
    client=GmailClient(str(tmp_path), 'absent.json'); client._service=Service(raw=synthetic_raw())
    trace=VerificationTrace(tmp_path/'traces')
    assert client.verify_message('a1', trace=trace)['authenticated'] is False
    assert any(e['operation']=='dns' and e['state']=='failed' for e in records(trace))
    assert records(trace)[-1]['state']=='unverified'
    assert 'PRIVATE_QUERY' not in trace.path.read_text()


def test_retries_count_sdk_calls_without_error_text(tmp_path):
    client=GmailClient(str(tmp_path),'absent.json'); client._service=Service()
    request=Mock(); request.execute.side_effect=[TimeoutError('PRIVATE'), {'ok':True}]
    cancel=Mock(); cancel.is_set.return_value=False; cancel.wait.return_value=False
    trace=VerificationTrace(tmp_path/'traces')
    assert client._request(lambda svc:request,cancel,trace)=={'ok':True}
    assert [(e['state'],e['attempt'],e['reason']) for e in records(trace)] == [
        ('start',1,'none'),('failed',1,'retryable'),('start',2,'none'),('ok',2,'none')]
    assert request.execute.call_count==2
    assert all(c.kwargs=={'num_retries':0} for c in request.execute.call_args_list)


def test_cancel_is_recorded_without_network(tmp_path):
    client=GmailClient(str(tmp_path),'absent.json'); client._service=Service()
    cancel=threading.Event(); cancel.set()
    trace=VerificationTrace(tmp_path/'traces')
    assert client.verify_message('a1', cancel, trace)=={}
    assert [e['state'] for e in records(trace)]==['start','cancelled']
    assert client._service.calls==[]


def test_trace_failure_propagates_before_network(tmp_path, monkeypatch):
    client=GmailClient(str(tmp_path),'absent.json'); client._service=Service()
    trace=VerificationTrace(tmp_path/'traces')
    monkeypatch.setattr(trace,'event',Mock(side_effect=TraceError('safe')))
    with pytest.raises(TraceError): client.verify_message('a1',trace=trace)
    assert client._service.calls==[]


def test_symlink_and_untrusted_event_rejected(tmp_path):
    real=tmp_path/'real'; real.mkdir(); (tmp_path/'alias').symlink_to(real, target_is_directory=True)
    with pytest.raises(TraceError): VerificationTrace(tmp_path/'alias')
    trace=VerificationTrace(real)
    with pytest.raises(TraceError): trace.event('PRIVATE_URL','ok')
    assert trace.path.read_text()==''


def test_app_write_failure_leaves_no_plan(tmp_path, monkeypatch):
    from gmail_unsubscriber.application import Application
    client=GmailClient(str(tmp_path),'absent.json'); client._service=Service()
    app=Application(tmp_path/'app',mode='live',gmail_client=client)
    app.account['connected']=True
    app.engine.ingest([normalize_message(metadata())])
    sid=app.state()['subscriptions'][0]['id']
    monkeypatch.setattr(VerificationTrace,'event',Mock(side_effect=TraceError('无法保存核验记录，已停止预览。')))
    app.start_preview([sid]); app._worker.join(3)
    state=app.state()
    assert not state['job']['running'] and state['job']['phase']=='failed'
    assert state['job']['plan'] is None and client._service.calls==[]
    assert state['subscriptions'][0]['verification_status']=='unverifiable'
