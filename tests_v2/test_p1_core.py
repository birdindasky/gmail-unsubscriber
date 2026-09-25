"""P1 core evidence: isolated synthetic databases and transport, no network."""
import json
import os
import sqlite3
import subprocess
import sys
import threading

import pytest

from gmail_unsubscriber.core import DomainError, Engine, Store


def mail(identifier='a', **changes):
    value = dict(id=identifier, sender_email=f'{identifier}@publisher.example',
                 subject='Synthetic newsletter', date='2026-09-18T10:00:00+00:00',
                 list_id=f'{identifier}.publisher.example',
                 list_unsubscribe='<https://publisher.example/unsubscribe?token=SYNTHETIC>',
                 list_unsubscribe_post='List-Unsubscribe=One-Click', authenticated=False)
    value.update(changes)
    return value


def ids(engine):
    return [s['id'] for s in engine.state()['subscriptions']]


def test_candidate_states_never_grant_authority(tmp_path):
    calls = []
    store = Store(str(tmp_path / 'state.sqlite'))
    engine = Engine(store, 'synthetic', transport=lambda url: calls.append(url))
    engine.ingest([mail()])
    sub = engine.state()['subscriptions'][0]
    assert (sub['verification_status'], sub['recommendation'], sub['status']) == ('pending', 'review', 'new')
    assert engine.preview(ids(engine))['summary']['ready'] == 0
    old = engine.preview(ids(engine))
    engine.clear_verification(ids(engine))
    assert engine.state()['subscriptions'][0]['verification_status'] == 'verifying'
    engine.finish_verification(ids(engine))
    assert engine.state()['subscriptions'][0]['verification_status'] == 'unverifiable'
    with pytest.raises(DomainError, match='变化'):
        engine.execute(old['id'])
    engine.ingest([mail(authenticated=True)])
    assert engine.state()['subscriptions'][0]['verification_status'] == 'verified'
    assert engine.preview(ids(engine))['summary']['ready'] == 1
    assert calls == []
    store.close()


@pytest.mark.parametrize('stop', ['cancel', 'protect'])
def test_inflight_progress_readable_and_next_item_stopped(tmp_path, stop):
    entered, release, cancel = threading.Event(), threading.Event(), threading.Event()
    calls, results = [], []
    def transport(url):
        calls.append(url)
        entered.set()
        assert release.wait(5)
        return {'status': 'uncertain'}
    store = Store(str(tmp_path / 'state.sqlite'))
    engine = Engine(store, 'synthetic', transport=transport)
    engine.ingest([mail('a', authenticated=True), mail('b', authenticated=True)])
    plan = engine.preview(ids(engine))
    thread = threading.Thread(target=lambda: results.append(engine.execute(plan['id'], cancel=cancel)))
    thread.start()
    assert entered.wait(3)
    # A distinct connection observes pending committed before the transport returns.
    reader = Store(store.path)
    observer = Engine(reader, 'synthetic')
    assert [i['phase'] for i in observer.execution_progress(plan['id'])['items']] == ['sending', 'waiting']
    assert observer.state()['stats']['messages'] == 2
    with pytest.raises(DomainError) as error:
        engine.execute(plan['id'])
    assert error.value.code == 'execution_in_progress'
    if stop == 'cancel':
        cancel.set()
    else:
        observer.protect('publisher.example')
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert results[0]['summary']['uncertain'] == 1
    assert results[0]['summary']['blocked'] == 1
    assert len(calls) == 1
    assert engine.execute(plan['id']) == results[0]
    assert len(calls) == 1
    reader.close()
    store.close()


def test_batch_rollback_keeps_prior_commit_and_deduplicates(tmp_path, monkeypatch):
    store = Store(str(tmp_path / 'state.sqlite'))
    engine = Engine(store, 'synthetic')
    engine.begin_scan(dict(days=30, scope='promotions', limit=100))
    engine.save_scan_batch([mail('a')], {'fetched': 1})
    original = engine._ingest_into
    def disk_failure(db, messages):
        original(db, messages)
        raise sqlite3.OperationalError('synthetic disk full SECRET')
    monkeypatch.setattr(engine, '_ingest_into', disk_failure)
    with pytest.raises(DomainError) as error:
        engine.save_scan_batch([mail('b')], {'fetched': 2})
    assert 'SECRET' not in str(error.value)
    assert engine.state()['scan']['saved'] == 1
    assert engine.state()['stats']['messages'] == 1
    engine.finish_scan({'status': 'failed', 'fetched': 2})
    monkeypatch.setattr(engine, '_ingest_into', original)
    engine.begin_scan(dict(days=30, scope='promotions', limit=100))
    engine.save_scan_batch([mail('a'), mail('a'), mail('b')], {'fetched': 2})
    state = engine.finish_scan({'status': 'completed', 'fetched': 2})
    assert state['stats']['messages'] == 2
    assert state['scan']['imported'] == 1
    assert state['scan']['duplicates'] == 1
    assert state['scan']['saved'] == 2
    assert '_saved_ids' not in state['scan']
    store.close()


def test_process_exit_scan_recovers_committed_batch(tmp_path):
    path = str(tmp_path / 'state.sqlite')
    program = '''import json,os,sys
from gmail_unsubscriber.core import Engine,Store
e=Engine(Store(sys.argv[1]),'synthetic')
e.protect('keep.example')
e.begin_scan({'days':30,'limit':100,'scope':'promotions'})
e.save_scan_batch([json.loads(sys.argv[2])],{'fetched':1})
os._exit(17)
'''
    result = subprocess.run([sys.executable, '-c', program, path, json.dumps(mail())], capture_output=True)
    assert result.returncode == 17, result.stderr
    store = Store(path)
    engine = Engine(store, 'synthetic')
    state = engine.state()
    assert state['scan']['status'] == 'interrupted'
    assert state['scan']['saved'] == state['stats']['messages'] == 1
    assert any(p['domain'] == 'keep.example' for p in state['protections'])
    assert state['activity']
    store.close()


def test_old_v2_json_without_fields_is_compatible(tmp_path):
    path = str(tmp_path / 'old.sqlite')
    store = Store(path)
    engine = Engine(store, 'synthetic')
    engine.ingest([mail()])
    with store.transaction() as db:
        for table in ('messages', 'subscriptions'):
            row = db.execute(f'SELECT id,data FROM {table}').fetchone()
            data = json.loads(row['data'])
            data.pop('verification_status')
            db.execute(f'UPDATE {table} SET data=? WHERE id=?', (json.dumps(data), row['id']))
    store.close()
    store = Store(path)
    engine = Engine(store, 'synthetic')
    assert engine.state()['subscriptions'][0]['verification_status'] == 'pending'
    assert engine.preview(ids(engine))['summary']['ready'] == 0
    engine.clear_verification(ids(engine))
    engine.finish_verification(ids(engine))
    assert engine.state()['stats']['messages'] == 1
    store.close()


@pytest.mark.parametrize('status, count, expected', [('completed', 0, 'empty'), ('completed', 1, 'completed'), ('limit', 1, 'limit'), ('cancelled', 1, 'cancelled'), ('network_interrupted', 1, 'network_interrupted')])
def test_scan_end_reason(tmp_path, status, count, expected):
    store = Store(str(tmp_path / 'state.sqlite'))
    engine = Engine(store, 'synthetic')
    engine.begin_scan(dict(days=30, limit=100, scope='promotions'))
    engine.save_scan_batch([mail()] if count else [], {'fetched': count})
    scan = engine.finish_scan({'status': status, 'fetched': count})['scan']
    assert scan['status'] == scan['end_reason'] == expected
    assert scan['started_at'] and scan['ended_at']
    assert scan['limit'] == 100 and scan['scope'] == 'promotions'
    store.close()


def test_first_receipt_visible_while_second_send_is_pending(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def transport(url):
        calls.append(url)
        if len(calls) == 2:
            entered.set()
            assert release.wait(5)
        return {'status': 'accepted'}
    store = Store(str(tmp_path / 'state.sqlite'))
    engine = Engine(store, 'synthetic', transport=transport)
    engine.ingest([mail('a', authenticated=True), mail('b', authenticated=True)])
    plan = engine.preview(ids(engine))
    thread = threading.Thread(target=lambda: engine.execute(plan['id']))
    thread.start()
    assert entered.wait(3)
    progress = engine.execution_progress(plan['id'])
    assert [i['phase'] for i in progress['items']] == ['receipt', 'sending']
    assert progress['items'][0]['status'] == 'accepted'
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    store.close()


def test_two_plans_cannot_duplicate_an_inflight_request(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def transport(url):
        calls.append(url)
        entered.set()
        assert release.wait(5)
        return {'status': 'uncertain'}
    store = Store(str(tmp_path / 'state.sqlite'))
    engine = Engine(store, 'synthetic', transport=transport)
    engine.ingest([mail(authenticated=True)])
    first, second = engine.preview(ids(engine)), engine.preview(ids(engine))
    thread = threading.Thread(target=lambda: engine.execute(first['id']))
    thread.start()
    assert entered.wait(3)
    assert engine.execute(second['id'])['summary']['blocked'] == 1
    release.set()
    thread.join(5)
    assert len(calls) == 1
    store.close()


def test_invalid_batch_members_are_visible_partial(tmp_path):
    store = Store(str(tmp_path / 'state.sqlite'))
    engine = Engine(store, 'synthetic')
    engine.begin_scan({'days': 30, 'scope': 'promotions', 'limit': 100})
    engine.save_scan_batch([mail(), mail('bad', sender_email='invalid')], {'fetched': 2})
    scan = engine.finish_scan({'status': 'completed', 'fetched': 2})['scan']
    assert scan['status'] == 'partial'
    assert scan['skipped'] == 1 and scan['saved'] == 1
    store.close()


def test_close_and_reopen_marks_scan_interrupted(tmp_path):
    path = str(tmp_path / 'state.sqlite')
    store = Store(path)
    engine = Engine(store, 'synthetic')
    engine.begin_scan({'days': 30, 'scope': 'promotions', 'limit': 100})
    engine.save_scan_batch([mail()], {'fetched': 1})
    store.close()
    store = Store(path)
    assert Engine(store, 'synthetic').state()['scan']['status'] == 'interrupted'
    store.close()
