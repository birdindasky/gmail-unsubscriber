"""P5 synthetic lifecycle and recovery checks; never opens real account data."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest
from gmail_unsubscriber.application import Application
from gmail_unsubscriber.core import DomainError, Engine, Store
from test_core import message

ROOT = Path(__file__).resolve().parents[1]


def test_close_waits_for_worker_and_closes_database(tmp_path):
    app = Application(tmp_path)
    completed = threading.Event()
    def work():
        app._cancel.wait(2)
        time.sleep(1.1)
        app.engine.protect('publisher.example')
        completed.set()
    app._start_job('synthetic', work)
    app.close()
    assert completed.is_set()
    with pytest.raises(Exception, match='closed'):
        app.store.connection.execute('select 1')
    reopened = Store(str(tmp_path / 'workspace.sqlite3'))
    assert Engine(reopened, 'demo').state()['protections']
    reopened.close()


def test_backup_restart_uncertain_protection_history_and_old_plan(tmp_path):
    data = tmp_path / 'data'
    app = Application(data, 'live', tmp_path / 'missing.json')
    calls = []
    engine = Engine(app.store, 'synthetic', mode='live', transport=lambda url: calls.append(url) or {'status':'uncertain'})
    engine.begin_scan({'days':30,'limit':100,'scope':'promotions'})
    engine.save_scan_batch([message(), message('def456', sender_email='other@other.example', list_id='other', list_unsubscribe='<https://other.example/leave>')], {'fetched':2})
    engine.finish_scan({'status':'completed','fetched':2})
    items = engine.state()['subscriptions']
    selected = next(x['id'] for x in items if x['domain']=='publisher.example')
    other = next(x['id'] for x in items if x['domain']=='other.example')
    old = engine.preview([other])
    engine.protect('other.example')
    with pytest.raises(DomainError):
        engine.execute(old['id'])
    plan = engine.preview([selected])
    assert engine.execute(plan['id'])['summary']['uncertain']==1
    before=engine.state()
    assert len(calls)==1
    app.close()
    shutil.copytree(data, tmp_path/'backup')
    shutil.copytree(tmp_path/'backup', tmp_path/'restored')
    for directory in (data, tmp_path/'restored'):
        store=Store(str(directory/'workspace.sqlite3'))
        restored=Engine(store,'synthetic',mode='live',transport=lambda u: pytest.fail('unexpected resend'))
        after=restored.state()
        for field in ('subscriptions','protections','activity','scan'):
            assert after[field]==before[field]
        for _ in range(3):
            assert restored.execute(plan['id'])['summary']['uncertain']==1
            preview=restored.preview([selected,other])
            assert preview['summary']['ready']==0
            assert restored.execute(preview['id'])['summary']['blocked']==2
        store.close()
    assert len(calls)==1


@pytest.mark.parametrize('launcher,mode', [('体验演示.command','demo'),('启动轻邮.command','live')])
def test_launcher_lifecycle_and_second_instance(tmp_path, launcher, mode):
    log=tmp_path/'process.log'
    command=['/bin/zsh',str(ROOT/launcher),'--no-browser','--data-dir',str(tmp_path/'data'),'--credentials',str(tmp_path/'missing.json')]
    for restart in range(2):
        with log.open('w') as output:
            proc=subprocess.Popen(command,cwd='/tmp',stdout=output,stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    text=log.read_text()
                    found=re.search(r'http://127\.0\.0\.1:\d+',text)
                    if found: break
                    assert proc.poll() is None, text
                    time.sleep(.05)
                assert found, text
                origin=found.group()
                html=urllib.request.urlopen(origin).read().decode()
                token=re.search(r'name="session-token" content="([^"]+)"',html).group(1)
                request=urllib.request.Request(origin+'/api/state',headers={'X-Session-Token':token})
                state=json.load(urllib.request.urlopen(request))
                assert state['account']['mode']==mode
                assert state['account']['connected']==(mode=='demo')
                assert not state['job']['running']
                if mode=='live':
                    assert state['stats']['messages']==0
                    assert not (tmp_path/'data'/'token.json').exists()
                second=subprocess.run(command,cwd='/tmp',capture_output=True,text=True,timeout=10)
                assert second.returncode==1
                assert '已有轻邮在运行' in second.stderr
            finally:
                if proc.poll() is None: proc.send_signal(signal.SIGINT)
                proc.wait(timeout=10)
            assert proc.returncode==0
        store=Store(str(tmp_path/'data'/'workspace.sqlite3'))
        assert store.connection.execute('pragma integrity_check').fetchone()[0]=='ok'
        store.close()


def test_missing_environment_and_mode_conflict(tmp_path):
    (tmp_path/'scripts').mkdir()
    shutil.copy(ROOT/'scripts/launch-v2.sh', tmp_path/'scripts/launch-v2.sh')
    result=subprocess.run(['/bin/zsh',str(tmp_path/'scripts/launch-v2.sh'),'demo'],capture_output=True,text=True)
    assert result.returncode==1 and 'environment_missing' in result.stderr
    result=subprocess.run([sys.executable,str(ROOT/'app.py'),'--demo','--live'],capture_output=True,text=True)
    assert result.returncode!=0 and 'not allowed' in result.stderr


def test_port_error_is_safe_and_releases_lock(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0)); listener.listen()
        result=subprocess.run([sys.executable,str(ROOT/'app.py'),'--demo','--no-browser','--data-dir',str(tmp_path),'--port',str(listener.getsockname()[1])],capture_output=True,text=True,timeout=10)
    assert result.returncode==1
    assert 'startup_failed' in result.stderr and 'Traceback' not in result.stderr
    from gmail_unsubscriber.runtime import InstanceLock
    with InstanceLock(tmp_path): pass


def test_fresh_demo_summary_matches_saved_messages(tmp_path):
    app=Application(tmp_path)
    state=app.state()
    assert state['scan']['saved']==state['scan']['imported']==state['stats']['messages']
    app.close()
