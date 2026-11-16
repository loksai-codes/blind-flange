"""Evaluation records, replay, revisions, the single writer and reproducible builds."""
import json

import pytest

from blindflange import checks, store
from conftest import SCENARIO, check, permit, set_now


def test_every_evaluation_is_recorded_with_a_snapshot(conn):
    r = check(conn, "PTW-0511")
    e = store.get_evaluation(conn, r.evaluation_id)
    assert (e["kind"], e["request_id"], e["conflict_verdict"]) == ("check", "PTW-0511", "BLOCK")
    assert e["revision"] == 1
    assert {"store", "components", "connections", "permits"} <= set(e["snapshot"])
    assert len(e["snapshot"]["components"]) == 35


def test_rejected_requests_are_recorded_too(conn):
    r = check(conn, {"id": "PTW-9999", "works_on": ["NOPE-1"]})
    e = store.get_evaluation(conn, r.evaluation_id)
    assert e["assessment_status"] == "ERROR"


def test_replay_reproduces_a_recorded_result(conn):
    r = check(conn, "PTW-0511")
    recorded, replayed, same = checks.replay(conn, r.evaluation_id)
    assert same and replayed["conflict_verdict"] == "BLOCK"


def test_old_evaluation_reopened_after_the_plant_changed_still_reproduces(conn):
    old = check(conn, "PTW-0511")
    set_now(conn, "RLV-504", "closed")
    assert check(conn, "PTW-0511").conflict_verdict == checks.CLEAR
    recorded, replayed, same = checks.replay(conn, old.evaluation_id)
    assert same and replayed["conflict_verdict"] == "BLOCK"


def test_replay_detects_a_tampered_record(conn):
    r = check(conn, "PTW-0511")
    conn.execute("MATCH (e:Evaluation {id: $id}) SET e.result = $res",
                 {"id": r.evaluation_id, "res": json.dumps(dict(checks._for_record(r), conflict_verdict="CLEAR"))})
    assert checks.replay(conn, r.evaluation_id)[2] is False


def test_what_if_changes_nothing_but_appends_an_evaluation(conn):
    before = store.snapshot(conn)
    r = checks.evaluate(conn, checks.permit_request(permit("PTW-0511")),
                        hypothetical=[{"tag": "RLV-504", "to": "closed"}], kind="what-if")
    assert r.conflict_verdict == checks.CLEAR
    assert store.snapshot(conn) == before
    assert store.get_evaluation(conn, r.evaluation_id)["kind"] == "what-if"


def test_what_if_reports_hazards_remaining_after_the_change(conn):
    set_now(conn, "EV-1", "open")
    r = checks.evaluate(conn, checks.change_request([{"tag": "XV-9", "to": "closed"}]),
                        hypothetical=[], kind="what-if")
    assert r.conflict_verdict == checks.HOLD
    assert r.hazards["remaining"] == ["WORKS_ON E-1 (PTW-0840) from JT-DRUM", "WORKS_ON E-1 (PTW-0840) from MOL",
                                      "WORKS_ON E-1 (PTW-0840) from P-B"]


def test_stale_revision_is_refused_and_recorded(conn):
    set_now(conn, "RLV-504", "closed")                       # revision 1 -> 2
    r, written = checks.approve(conn, permit("PTW-0511"), expect_revision=1)
    assert not written and r.assessment_status == checks.ERROR and "stale revision" in r.error
    assert not store.run(conn, "permit_exists", id="PTW-0511")
    assert store.get_evaluation(conn, r.evaluation_id)["assessment_status"] == "ERROR"
    r, written = checks.approve(conn, permit("PTW-0511"), expect_revision=2)
    assert written


def test_stale_revision_on_set_writes_nothing(conn):
    r, written = checks.set_states(conn, [{"tag": "RLV-504", "to": "closed"}], expect_revision=7)
    assert not written and store.component(conn, "RLV-504")["state"] == "open"


def test_write_bumps_revision_and_rejects_stale_inside_the_transaction(conn):
    with pytest.raises(store.StaleRevisionError):
        with store.write(conn, expect_revision=5):
            store.set_state(conn, "RLV-504", "closed", "2026-11-15T06:00:00Z", "test")
    assert store.component(conn, "RLV-504")["state"] == "open"
    assert store.info(conn)["revision"] == 1


def test_a_second_writer_is_refused(tmp_path):
    out = tmp_path / "s.rl"
    store.build(SCENARIO, out).close()
    first = store.connect(out)
    try:
        with pytest.raises(store.StoreError, match="another process"):
            store.connect(out)
    finally:
        first.close()
    store.connect(out).close()                               # free again once the writer exits


def test_build_is_reproducible(tmp_path):
    a, b = store.build(SCENARIO), store.build(SCENARIO)
    try:
        assert store.snapshot(a) == store.snapshot(b)
    finally:
        a.close()
        b.close()


def test_missing_store_is_not_created(tmp_path):
    with pytest.raises(store.StoreError, match="not found"):
        store.connect(tmp_path / "nope.rl")
    assert not (tmp_path / "nope.rl").exists()


def test_store_path_must_end_in_rl(tmp_path):
    with pytest.raises(store.StoreError, match=r"\.rl"):
        store.build(SCENARIO, tmp_path / "s.db")


def _count(conn, cypher):
    return conn.execute(cypher).data()[0]["n"]


def test_evaluations_of_the_same_plant_state_share_one_snapshot(conn):
    ids = [check(conn, pid).evaluation_id for pid in ("PTW-0511", "PTW-0845", "PTW-0850")]
    assert _count(conn, "MATCH (s:Snapshot) RETURN count(s) AS n") == 1
    assert _count(conn, "MATCH (:Evaluation)-[:ASSESSED]->(:Snapshot) RETURN count(*) AS n") == 3
    assert all(store.get_evaluation(conn, i)["snapshot"]["store"]["revision"] == 1 for i in ids)


def test_a_new_plant_state_gets_a_new_snapshot(conn):
    check(conn, "PTW-0511")
    set_now(conn, "RLV-504", "closed")
    check(conn, "PTW-0511")
    assert _count(conn, "MATCH (s:Snapshot) RETURN count(s) AS n") == 2


def test_a_snapshot_id_is_the_hash_of_its_content(conn):
    import hashlib
    check(conn, "PTW-0511")
    s = conn.execute("MATCH (s:Snapshot) RETURN s.id AS id, s.data AS data").data()[0]
    assert s["id"] == "SNAP-" + hashlib.sha256(s["data"].encode("utf-8")).hexdigest()[:16]


def test_replay_refuses_a_snapshot_whose_content_was_altered(conn):
    r = check(conn, "PTW-0511")
    conn.execute("MATCH (s:Snapshot) SET s.data = replace(s.data, '\"open\"', '\"closed\"')")
    with pytest.raises(store.StoreError, match="altered"):
        checks.replay(conn, r.evaluation_id)
