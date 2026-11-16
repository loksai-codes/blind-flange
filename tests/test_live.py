"""Store mode: a snapshot is assessed at its as_of; a live store is assessed now."""
import subprocess
import sys

import pytest

from blindflange import checks, store
from conftest import ROOT, SCENARIO, check

LATER = "2026-11-20T09:00:00Z"            # four days after the scenario's as_of


@pytest.fixture
def frozen(monkeypatch):
    """Pin 'now' so the tests do not depend on today's date."""
    def pin(value):
        monkeypatch.setattr(store, "now", lambda: value)
    pin(LATER)
    return pin


@pytest.fixture
def live(tmp_path, frozen):
    snap = tmp_path / "snap.rl"
    store.build(SCENARIO, snap).close()
    out = tmp_path / "shift.rl"
    store.shift_start(snap, out)
    conn = store.connect(out)
    yield conn
    conn.close()


def test_built_stores_are_snapshots(conn):
    assert store.info(conn)["mode"] == "snapshot"


def test_shift_start_makes_a_live_store_starting_now(live):
    info = store.info(live)
    assert (info["mode"], info["as_of"]) == ("live", LATER)


def test_live_store_with_old_observations_is_incomplete(live):
    r = check(live, "PTW-0850")
    assert (r.assessment_status, r.conflict_verdict) == (checks.INCOMPLETE, None)
    assert (r.assessed_at, r.mode) == (LATER, "live")


def test_live_store_observed_this_shift_is_complete(live):
    with store.write(live):                                    # a full round: every state re-observed now
        for c in store.snapshot(live)["components"]:
            store.set_state(live, c["tag"], c["state"], LATER, "operator round")
    r = check(live, "PTW-0850")
    assert (r.assessment_status, r.conflict_verdict, r.unknowns) == (checks.COMPLETE, checks.CLEAR, [])


def test_snapshot_results_do_not_depend_on_todays_date(conn, frozen):
    frozen("2026-11-15T07:00:00Z")
    a = checks.evaluate(conn, checks.permit_request(store.load_permit(ROOT / "data/permits/PTW-0511.yaml")),
                        record=False).to_dict()
    frozen("2030-01-01T00:00:00Z")
    b = checks.evaluate(conn, checks.permit_request(store.load_permit(ROOT / "data/permits/PTW-0511.yaml")),
                        record=False).to_dict()
    assert a == b and a["mode"] == "snapshot" and a["assessed_at"] == "2026-11-15T06:00:00Z"


def test_live_replay_uses_the_recorded_assessment_time(live, frozen):
    r = check(live, "PTW-0850")
    frozen("2027-06-01T00:00:00Z")
    assert checks.replay(live, r.evaluation_id)[2]


def test_freshness_lists_observations_older_than_the_threshold(live, conn):
    old = store.stale_observations(live)
    assert old and all(o["observed_at"] < "2026-11-19T21:00:00Z" for o in old)
    assert store.stale_observations(conn) == []                  # a snapshot is fresh at its own as_of


def test_every_result_prints_the_assessment_time_and_mode(tmp_path):
    rl = tmp_path / "s.rl"
    store.build(SCENARIO, rl).close()
    r = subprocess.run([sys.executable, "-m", "blindflange", "check", str(ROOT / "data/permits/PTW-0850.yaml"),
                        "--store", str(rl)], capture_output=True, text=True)
    assert "assessed at 2026-11-15T06:00:00Z (snapshot store)" in r.stdout


def test_shift_start_and_freshness_commands(tmp_path):
    snap = tmp_path / "snap.rl"
    store.build(SCENARIO, snap).close()
    out = tmp_path / "shift.rl"
    r = subprocess.run([sys.executable, "-m", "blindflange", "shift", "start", "--from", str(snap), "-o", str(out),
                        "--as-of", LATER], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    f = subprocess.run([sys.executable, "-m", "blindflange", "freshness", "--store", str(out), "--at", LATER],
                       capture_output=True, text=True)
    assert f.returncode == 0 and "threshold 12 h" in f.stdout and "RLV-504" in f.stdout


def test_live_store_ages_observations_as_the_shift_goes_on(live, frozen):
    with store.write(live):                                    # a full round at the start of the shift
        for c in store.snapshot(live)["components"]:
            store.set_state(live, c["tag"], c["state"], LATER, "operator round")
    assert check(live, "PTW-0850").assessment_status == checks.COMPLETE
    frozen("2026-11-20T22:00:00Z")                             # 13 hours later, nothing re-observed
    r = check(live, "PTW-0850")
    assert (r.assessment_status, r.assessed_at) == (checks.INCOMPLETE, "2026-11-20T22:00:00Z")
