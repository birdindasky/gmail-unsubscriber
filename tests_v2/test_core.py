"""Domain regression tests: synthetic email, temporary SQLite, injected transport only."""
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import threading

import pytest

from gmail_unsubscriber.core import DomainError, Engine, Store


def message(id="abc123", **changes):
    value = dict(id=id, sender_email="news@publisher.example", sender_name="合成周刊",
                 subject="每周新闻", snippet="本周资讯", date="2026-09-18T10:00:00+00:00",
                 list_id="Weekly <weekly.publisher.example>",
                 list_unsubscribe="<https://unsubscribe.publisher.example/leave?token=SYNTHETIC>",
                 list_unsubscribe_post="List-Unsubscribe=One-Click", authenticated=True)
    value.update(changes)
    return value


@pytest.fixture
def model(tmp_path):
    calls = []
    store = Store(str(tmp_path / "state.sqlite3"))
    def transport(url):
        calls.append(url)
        return {"status": "accepted", "detail": "REMOTE detail must not appear"}
    engine = Engine(store, "synthetic@account.example", transport=transport)
    yield engine, calls
    store.close()


def selected(engine):
    return [item["id"] for item in engine.state()["subscriptions"]]


def run(engine, ids=None):
    return engine.execute(engine.preview(ids or selected(engine))["id"])


def test_authenticated_one_click_is_explicit_acceptance_and_plan_replay(model):
    engine, calls = model
    engine.ingest([message()])
    plan = engine.preview(selected(engine))
    assert calls == []
    assert plan["summary"] == dict(selected=1, ready=1, manual=0, blocked=0)
    result = engine.execute(plan["id"])
    assert result["summary"]["accepted"] == 1
    assert "请求已接受" in result["items"][0]["detail"]
    assert engine.execute(plan["id"]) == result
    assert run(engine)["summary"]["blocked"] == 1
    assert len(calls) == 1


@pytest.mark.parametrize("authenticated", [False, "true", "false", 1, [True], {"pass": True}, None])
def test_only_exact_boolean_adapter_capability_can_authorize(model, authenticated):
    engine, calls = model
    engine.ingest([message(authenticated=authenticated, is_ad="true", recommendation="unsubscribe",
                           classification={"is_ad": True}, authentication_results="mx.google.com; dkim=pass")])
    assert run(engine)["summary"]["manual"] == 1
    assert calls == []


@pytest.mark.parametrize("changes", [
    {"list_unsubscribe_post": ""},
    {"list_unsubscribe": "<mailto:leave@publisher.example>"},
    {"list_unsubscribe": "<http://publisher.example/leave>"},
    {"list_unsubscribe": ""},
    {"list_unsubscribe": "<https://one.example/u>, <https://two.example/u>"},
    {"list_unsubscribe": ["<https://one.example/u>", "<https://two.example/u>"]},
    {"list_unsubscribe_post": ["List-Unsubscribe=One-Click"]},
    {"list_unsubscribe": "https://publisher.example/unframed"},
    {"list_unsubscribe": "<https://publisher.example/u> malicious"},
    {"list_unsubscribe": "<https://user:pass@publisher.example/u>"},
    {"list_unsubscribe": "<https://127.0.0.1/u>"},
    {"list_unsubscribe": "<https://[::1]/u>"},
    {"list_unsubscribe": "<https://localhost/u>"},
    {"list_unsubscribe": "<https://thing.local/u>"},
    {"list_unsubscribe": "<https://publisher.example:8080/u>"},
    {"list_unsubscribe": "<https://publisher.example/u#fragment>"},
    {"list_unsubscribe": "<https://publisher.example/u%0d%0aHeader>"},
])
def test_ambiguous_or_non_one_click_headers_remain_manual(model, changes):
    engine, calls = model
    engine.ingest([message(**changes)])
    assert run(engine)["summary"]["manual"] == 1
    assert calls == []


def test_no_implicit_demo_success_or_body_url_visits(tmp_path):
    engine = Engine(Store(str(tmp_path / "state.sqlite3")), "demo")
    engine.ingest([message(snippet="Unsubscribe https://body.example/leave Cancel membership https://body.example/cancel")])
    assert run(engine)["summary"]["manual"] == 1


def test_protection_change_invalidates_preview_and_blocks_subdomains(model):
    engine, calls = model
    engine.ingest([message(sender_email="news@sub.publisher.example")])
    plan = engine.preview(selected(engine))
    engine.protect("publisher.example")
    with pytest.raises(DomainError) as error:
        engine.execute(plan["id"])
    assert error.value.code == "plan_stale"
    assert run(engine)["summary"]["blocked"] == 1
    assert calls == []
    assert engine.state()["subscriptions"][0]["protected"] is True


def test_protection_is_rechecked_even_if_revision_was_not_changed(model):
    engine, calls = model
    engine.ingest([message()])
    plan = engine.preview(selected(engine))
    with engine.store.transaction() as db:
        db.execute("INSERT INTO protections VALUES(?,?,'user')", (engine.account_id, "publisher.example"))
    assert engine.execute(plan["id"])["summary"]["blocked"] == 1
    assert calls == []


@pytest.mark.parametrize("sender", ['"Friends <club>" <notice@google.com>', "alert@mail.google.com", "notice@icbc.com.cn", "notice@mail.cmbchina.com"])
def test_builtin_google_and_bank_protections_parse_sender_correctly(model, sender):
    engine, calls = model
    engine.ingest([message(sender_email=sender)])
    assert run(engine)["summary"]["blocked"] == 1
    assert calls == []


def test_protection_suffix_cannot_be_spoofed(model):
    engine, _ = model
    engine.ingest([message(sender_email="news@google.com.attacker.example")])
    assert engine.state()["subscriptions"][0]["protected"] is False


def test_sensitive_content_kept_even_when_model_says_delete(model):
    engine, calls = model
    engine.ingest([message(subject="银行账单与验证码", recommendation="unsubscribe", is_ad=True)])
    assert engine.state()["subscriptions"][0]["recommendation"] == "keep"
    assert run(engine)["summary"]["blocked"] == 1
    assert calls == []


def test_list_identity_and_account_isolation(model):
    engine, calls = model
    engine.ingest([message("a", list_id="sports.publisher.example"), message("b", list_id="books.publisher.example")])
    ids = selected(engine)
    assert len(ids) == 2
    assert run(engine, [ids[0]])["summary"]["accepted"] == 1
    engine.ingest([message("c", list_id="books.publisher.example")])
    assert len(selected(engine)) == 2
    assert engine.state()["stats"]["messages"] == 3
    other = Engine(engine.store, "other@account.example", transport=lambda url: calls.append(url))
    assert other.state()["subscriptions"] == []
    with pytest.raises(DomainError) as error:
        other.preview(ids)
    assert error.value.code == "not_found"
    engine.protect("private.example")
    assert "private.example" not in {p["domain"] for p in other.state()["protections"]}
    assert other.state()["activity"] == []


def test_without_list_id_identity_binds_exact_target(model):
    engine, _ = model
    engine.ingest([message("a", list_id="", list_unsubscribe="<https://publisher.example/a>"),
                   message("b", list_id="", list_unsubscribe="<https://publisher.example/b>")])
    assert len(selected(engine)) == 2
    assert run(engine, [selected(engine)[0]])["summary"]["accepted"] == 1
    assert engine.state()["stats"]["review"] == 1


def test_message_reingest_updates_auth_without_duplicate_count(model):
    engine, _ = model
    engine.ingest([message(authenticated=False)])
    ids = selected(engine)
    assert engine.message_ids_for(ids) == ["abc123"]
    old = engine.preview(ids)
    assert old["summary"]["manual"] == 1
    engine.ingest([message(authenticated=True)])
    assert engine.state()["stats"]["messages"] == 1
    assert engine.state()["subscriptions"][0]["count"] == 1
    with pytest.raises(DomainError) as error:
        engine.execute(old["id"])
    assert error.value.code == "plan_stale"
    assert engine.preview(ids)["summary"]["ready"] == 1
    engine.ingest([message(authenticated=True)])
    assert engine.state()["subscriptions"][0]["count"] == 1


def test_expiry_and_cross_account_plan_rejected(model, monkeypatch):
    engine, calls = model
    engine.ingest([message()])
    plan = engine.preview(selected(engine))
    other = Engine(engine.store, "other")
    with pytest.raises(DomainError) as error:
        other.execute(plan["id"])
    assert error.value.code == "not_found"
    monkeypatch.setattr("gmail_unsubscriber.core.time.time", lambda: plan["expires_at"] + 1)
    with pytest.raises(DomainError) as error:
        engine.execute(plan["id"])
    assert error.value.code == "plan_expired"
    assert calls == []


def test_transaction_failure_preserves_previous_scan_and_protections(model):
    engine, _ = model
    engine.ingest([message()], {"status": "completed", "processed": 1})
    engine.protect("personal.example")
    before = engine.state()
    with engine.store.transaction() as db:
        db.execute("CREATE TRIGGER fail_write BEFORE INSERT ON messages WHEN NEW.id='fail' BEGIN SELECT RAISE(ABORT,'synthetic write failure'); END")
    with pytest.raises(DomainError) as error:
        engine.ingest([message("good"), message("fail")], {"status": "running", "processed": 3})
    assert error.value.code == "storage_error"
    assert engine.state() == before


def test_protection_read_failure_never_fails_open(model):
    engine, calls = model
    engine.ingest([message()])
    plan = engine.preview(selected(engine))
    with engine.store.transaction() as db:
        db.execute("ALTER TABLE protections RENAME TO unavailable_protections")
    with pytest.raises(DomainError) as error:
        engine.execute(plan["id"])
    assert error.value.code == "storage_error"
    assert calls == []


def test_remote_errors_details_do_not_leak_and_uncertain_cannot_retry(model):
    engine, calls = model
    secret = "Bearer SYNTHETIC-CREDENTIAL api_key=HIDDEN https://private.example/?token=SECRET"
    def explode(url):
        calls.append(url)
        raise RuntimeError(secret)
    engine.transport = explode
    engine.ingest([message()])
    result = run(engine)
    assert result["summary"]["uncertain"] == 1
    assert run(engine)["summary"]["blocked"] == 1
    assert len(calls) == 1
    serialized = json.dumps(engine.state(), ensure_ascii=False) + json.dumps(result)
    for text in ("SYNTHETIC-CREDENTIAL", "api_key", "token=SECRET", "REMOTE detail"):
        assert text not in serialized
    assert "token=SYNTHETIC" not in json.dumps(engine.state())


@pytest.mark.parametrize("response,expected", [({}, "uncertain"), ({"status": "true"}, "uncertain"),
    ({"status": "failed", "detail": "token=secret"}, "failed"),
    ({"status": "uncertain"}, "uncertain"), (None, "uncertain")])
def test_transport_result_validation(model, response, expected):
    engine, _ = model
    engine.transport = lambda url: response
    engine.ingest([message()])
    result = run(engine)
    assert result["summary"][expected] == 1
    assert "token=secret" not in json.dumps(result)


def test_committed_pending_is_visible_to_transport_before_send(model):
    engine, _ = model
    observed = []
    def transport(url):
        con = sqlite3.connect(engine.store.path)
        observed.append(con.execute("SELECT status FROM executions").fetchone()[0])
        con.close()
        return {"status": "accepted"}
    engine.transport = transport
    engine.ingest([message()])
    assert run(engine)["summary"]["accepted"] == 1
    assert observed == ["pending"]


def test_concurrent_plans_for_same_subscription_send_at_most_once(model):
    engine, calls = model
    engine.ingest([message()])
    plans = [engine.preview(selected(engine)) for _ in range(2)]
    barrier = threading.Barrier(3)
    results, failures = [], []
    def execute(plan):
        barrier.wait()
        try:
            results.append(engine.execute(plan["id"]))
        except BaseException as exc:
            failures.append(exc)
    threads = [threading.Thread(target=execute, args=(plan,)) for plan in plans]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)
    assert failures == []
    assert len(calls) == 1
    assert sum(result["summary"]["accepted"] for result in results) == 1


def test_concurrent_same_plan_returns_idempotent_result(model):
    engine, calls = model
    engine.ingest([message()])
    plan = engine.preview(selected(engine))
    barrier = threading.Barrier(3)
    outcomes = []
    def execute():
        barrier.wait()
        try:
            outcomes.append(engine.execute(plan["id"]))
        except DomainError as exc:
            outcomes.append(exc.code)
    threads = [threading.Thread(target=execute) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)
    assert len(calls) == 1
    assert len(outcomes) == 2
    assert all(value == "execution_in_progress" or value["summary"]["accepted"] == 1 for value in outcomes)


def test_process_crash_recovers_pending_without_resend(tmp_path):
    path = tmp_path / "restart.sqlite3"
    script = '''
import json,os,sys
from gmail_unsubscriber.core import Engine,Store
engine=Engine(Store(sys.argv[1]),'crash-account',transport=lambda url: os._exit(23))
engine.ingest([json.loads(sys.argv[2])])
plan=engine.preview([engine.state()['subscriptions'][0]['id']])
engine.execute(plan['id'])
'''
    result = subprocess.run([sys.executable, "-c", script, str(path), json.dumps(message())], cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
    assert result.returncode == 23, result.stderr.decode()
    calls = []
    store = Store(str(path))
    engine = Engine(store, "crash-account", transport=lambda url: calls.append(url))
    assert engine.state()["subscriptions"][0]["status"] == "uncertain"
    old_plan = store.connection.execute("SELECT id FROM plans").fetchone()[0]
    assert engine.execute(old_plan)["summary"]["uncertain"] == 1
    assert run(engine)["summary"]["blocked"] == 1
    assert calls == []
    store.close()


def test_partial_scan_is_visible_and_previous_history_is_preserved(model):
    engine, _ = model
    engine.ingest([message()])
    run(engine)
    engine.protect("personal.example")
    engine.ingest([message("new", list_id="another.publisher.example")], {"status": "partial", "processed": 1, "message": "Bearer SECRET"})
    state = engine.state()
    assert state["scan"]["partial"] is True
    assert state["stats"]["accepted"] == 1
    assert state["stats"]["messages"] == 2
    assert "personal.example" in {p["domain"] for p in state["protections"]}
    assert "SECRET" not in json.dumps(state)


def test_safe_manual_link_and_malicious_message_id_rejection(model):
    engine, calls = model
    engine.ingest([message(id="19afabcdef", list_unsubscribe="<mailto:unsubscribe@publisher.example>")])
    assert engine.manual_link(selected(engine)[0]) == "https://mail.google.com/mail/u/0/#all/19afabcdef"
    with pytest.raises(DomainError):
        engine.ingest([message(id="x/../../?url=https://attacker.example")])
    assert calls == []


def test_database_permissions_are_tightened_on_existing_file(tmp_path):
    path = tmp_path / "database.sqlite3"
    store = Store(str(path))
    store.close()
    os.chmod(path, 0o644)
    store = Store(str(path))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    store.close()


def test_demo_reset_is_atomic_and_does_not_touch_other_accounts(model):
    engine, _ = model
    engine.ingest([message()])
    other = Engine(engine.store, "other", mode="live")
    other.ingest([message("other")])
    before_other = other.state()
    engine.protect("personal.example")
    result = engine.reset_demo([message("replacement", list_id="new.example")])
    assert result["stats"]["messages"] == 1
    assert engine.message_ids_for(selected(engine)) == ["replacement"]
    assert "personal.example" not in {p["domain"] for p in result["protections"]}
    assert other.state() == before_other
    before = engine.state()
    with pytest.raises(DomainError):
        engine.reset_demo([message("same", list_id="a.example"), message("same", list_id="b.example")])
    assert engine.state() == before
    with pytest.raises(DomainError) as error:
        other.reset_demo([])
    assert error.value.status == 403


def test_new_store_in_same_process_does_not_recover_active_plan(model):
    engine, _ = model
    engine.ingest([message()])
    snapshots = []
    def transport(url):
        second = Store(engine.store.path)
        other = Engine(second, engine.account_id)
        snapshots.append(second.connection.execute("SELECT state FROM plans").fetchone()[0])
        second.close()
        return {"status": "accepted"}
    engine.transport = transport
    assert run(engine)["summary"]["accepted"] == 1
    assert snapshots == ["executing"]


def test_new_protection_stops_later_items_in_current_batch(model):
    engine, calls = model
    engine.ingest([message("a", list_id="a.publisher.example"), message("b", list_id="b.publisher.example")])
    def transport(url):
        calls.append(url)
        engine.protect("publisher.example")
        return {"status": "accepted"}
    engine.transport = transport
    result = run(engine)
    assert result["summary"]["accepted"] == 1
    assert result["summary"]["blocked"] == 1
    assert len(calls) == 1


def test_a_list_success_does_not_hide_another_list_from_same_sender(model):
    engine, calls = model
    engine.ingest([message("sports", list_id="sports.publisher.example"), message("books", list_id="books.publisher.example")])
    mapping = {item["list_id"]: item["id"] for item in engine.state()["subscriptions"]}
    run(engine, [mapping["sports.publisher.example"]])
    engine.ingest([message("books2", list_id="books.publisher.example")])
    assert engine.preview([mapping["books.publisher.example"]])["summary"]["ready"] == 1
    assert run(engine, [mapping["books.publisher.example"]])["summary"]["accepted"] == 1
    assert len(calls) == 2


def test_demo_acceptance_is_explicitly_simulated(model):
    engine, _ = model
    engine.ingest([message()])
    result = run(engine)
    assert "演示" in result["items"][0]["detail"]
    assert "模拟" in result["items"][0]["detail"]


def test_clear_verification_removes_persisted_trust_preserves_identity_and_count(model):
    engine, calls = model
    engine.ingest([message("first"), message("second"), message("other", list_id="other.publisher.example")])
    subs = {item["list_id"]: item for item in engine.state()["subscriptions"]}
    selected_id = subs["weekly.publisher.example"]["id"]
    other_id = subs["other.publisher.example"]["id"]
    plan = engine.preview([selected_id])
    assert plan["summary"]["ready"] == 1
    state = engine.clear_verification([selected_id])
    after = {item["id"]: item for item in state["subscriptions"]}
    assert after[selected_id]["count"] == 2
    assert after[selected_id]["method"] == "manual"
    assert after[other_id]["method"] == "one_click"
    assert state["stats"]["messages"] == 3
    assert engine.preview([selected_id])["summary"]["manual"] == 1
    with pytest.raises(DomainError) as error:
        engine.execute(plan["id"])
    assert error.value.code == "plan_stale"
    stored = engine.store.connection.execute("SELECT data FROM messages WHERE subscription_id=?", (selected_id,)).fetchall()
    assert all(json.loads(row[0])["authenticated"] is False for row in stored)
    engine.ingest([message("second", authenticated=True)])
    assert engine.preview([selected_id])["summary"]["ready"] == 1
    assert engine.state()["stats"]["messages"] == 3
    assert calls == []


@pytest.mark.parametrize("bad", [
    message("quoted", sender_email='"odd local"@publisher.example'),
    message("oversized", list_unsubscribe="<https://publisher.example/" + "x" * 8192 + ">"),
    message("invalid_sender", sender_email=""),
    message("unsafe/id"),
    None,
])
def test_scan_ingest_retains_valid_mail_and_reports_unsupported_entries(model, bad):
    engine, calls = model
    state = engine.ingest_scan([message("valid", authenticated=False), bad], {"status": "completed", "fetched": 2, "failed": 0})
    assert state["stats"]["messages"] == 1
    assert engine.message_ids_for(selected(engine)) == ["valid"]
    assert state["scan"]["status"] == "partial"
    assert state["scan"]["partial"] is True
    assert state["scan"]["skipped"] == state["scan"]["failed"] == 1
    assert state["scan"]["imported"] == 1
    assert run(engine)["summary"]["manual"] == 1
    assert calls == []


def test_scan_ingest_skips_conflicts_against_existing_and_same_batch(model):
    engine, calls = model
    engine.ingest([message("existing", list_id="original.publisher.example")])
    original = engine.state()["subscriptions"][0]
    engine.protect("publisher.example")
    state = engine.ingest_scan([
        message("valid", list_id="valid.publisher.example"),
        message("existing", list_id="conflicting.publisher.example"),
        message("valid", list_id="another.publisher.example"),
        message("other", list_id="other.publisher.example"),
    ], {"status": "completed", "failed": 2})
    assert state["stats"]["messages"] == 3
    assert state["scan"]["imported"] == 2
    assert state["scan"]["skipped"] == 2
    assert state["scan"]["failed"] == 4
    assert state["scan"]["partial"] is True
    after = {item["id"]: item for item in state["subscriptions"]}
    assert after[original["id"]]["list_id"] == "original.publisher.example"
    assert after[original["id"]]["count"] == 1
    assert all(item["protected"] for item in after.values())
    assert run(engine)["summary"]["blocked"] == 3
    assert calls == []


def test_scan_ingest_cannot_downgrade_database_failure_to_skipped_mail(model):
    engine, _ = model
    engine.ingest([message("original")], {"status": "completed", "processed": 1})
    before = engine.state()
    with engine.store.transaction() as db:
        db.execute("CREATE TRIGGER fail_scan_write BEFORE INSERT ON messages WHEN NEW.id='disk_failure' BEGIN SELECT RAISE(ABORT,'synthetic disk failure'); END")
    with pytest.raises(DomainError) as error:
        engine.ingest_scan([message("valid"), message("invalid", sender_email=""), message("disk_failure")])
    assert error.value.code == "storage_error"
    assert engine.state() == before


def test_strict_ingest_keeps_rejecting_entire_malformed_update(model):
    engine, _ = model
    engine.ingest([message("original")])
    before = engine.state()
    with pytest.raises(DomainError):
        engine.ingest([message("new"), message("unsupported", sender_email='"odd local"@publisher.example')])
    assert engine.state() == before


def test_scan_ingest_all_unsupported_is_partial_and_retains_old_history(model):
    engine, _ = model
    engine.ingest([message("old")])
    run(engine)
    state = engine.ingest_scan([message("invalid", sender_email="")])
    assert state["stats"]["messages"] == state["stats"]["accepted"] == 1
    assert state["scan"]["status"] == "partial"
    assert state["scan"]["imported"] == 0
    assert state["scan"]["skipped"] == 1


def test_scan_ingest_clean_cancelled_and_duplicate_counts(model):
    engine, _ = model
    state = engine.ingest_scan([message("same"), message("same")], {"status": "cancelled", "fetched": 1})
    assert state["scan"]["status"] == "cancelled"
    assert state["scan"]["partial"] is True
    assert state["scan"]["imported"] == 1
    assert state["scan"]["skipped"] == state["scan"]["failed"] == 0
    assert state["stats"]["messages"] == 1
    state = engine.ingest_scan([], {"status": "completed", "fetched": 0})
    assert state["scan"]["status"] == "completed"
    assert state["scan"]["partial"] is False
    assert state["scan"]["imported"] == 0
