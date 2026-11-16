from pathlib import Path

import pytest

from blindflange import checks, store

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "data" / "scenarios" / "condensate_unit.yaml"


def permit(pid):
    return store.load_permit(ROOT / "data" / "permits" / f"{pid}.yaml")


@pytest.fixture
def conn():
    c = store.build(SCENARIO)
    yield c
    c.close()


def codes(result):
    return [f.code for f in result.findings]


def test_start_pump_a_is_blocked_with_a_path_and_no_shared_tag(conn):
    r = checks.check(conn, permit("PTW-0511"))
    assert r.verdict == checks.BLOCK
    f = r.findings[0]
    assert f.code == "PRESSURE_REACHES_TEMPORARY_BARRIER"
    assert f.permit == "PTW-0504"
    assert f.path == ["P-A", "L-PD-A", "RLV-504", "L-RL-504", "BF-504"]
    assert r.baseline_shared_tags == {}


def test_closing_one_valve_clears_the_conflict(conn):
    with store.transaction(conn, commit=True):
        store.set_state(conn, "RLV-504", "closed")
    assert checks.check(conn, permit("PTW-0511")).verdict == checks.CLEAR


def test_check_is_a_dry_run(conn):
    checks.check(conn, permit("PTW-0511"))
    ids = [r["id"] for r in store.rows(conn, "MATCH (p:Permit) RETURN p.id AS id ORDER BY id")]
    assert ids == ["PTW-0504", "PTW-0840"]


def test_blocked_permit_is_not_stored_on_approve(conn):
    checks.check(conn, permit("PTW-0511"), approve=True)
    assert not store.rows(conn, "MATCH (p:Permit {id: 'PTW-0511'}) RETURN p.id AS id")


def test_approve_stores_permit_and_applies_state_changes(conn):
    with store.transaction(conn, commit=True):
        store.set_state(conn, "RLV-504", "closed")
    checks.check(conn, permit("PTW-0511"), approve=True)
    got = store.rows(conn, "MATCH (p:Permit {id: 'PTW-0511'}) RETURN p.status AS s")
    assert got == [{"s": "active"}]
    assert store.component(conn, "SV-A")["state"] == "open"
    assert store.component(conn, "P-A")["state"] == "in_service"


def test_operating_a_relied_on_valve_is_blocked(conn):
    r = checks.check(conn, permit("PTW-0845"))
    assert r.verdict == checks.BLOCK
    assert "ISOLATION_REMOVED" in codes(r)


def test_unlisted_route_into_open_work_is_found(conn):
    r = checks.check(conn, permit("PTW-0846"))
    assert r.verdict == checks.BLOCK
    assert r.findings[0].path == ["FW-HDR", "XV-9", "E-1"]
    assert r.baseline_shared_tags == {}


def test_shared_isolation_is_a_hold(conn):
    r = checks.check(conn, permit("PTW-0847"))
    assert r.verdict == checks.HOLD
    assert codes(r) == ["SHARED_ISOLATION"]


def test_open_isolation_valve_is_blocked(conn):
    r = checks.check(conn, permit("PTW-0849"))
    assert set(codes(r)) == {"ISOLATION_NOT_IN_PLACE", "WORKSITE_NOT_ISOLATED"}


@pytest.mark.parametrize("pid", ["PTW-0848", "PTW-0850", "PTW-0851"])
def test_safe_permits_are_clear(conn, pid):
    assert checks.check(conn, permit(pid)).verdict == checks.CLEAR


def test_state_change_that_breaks_an_isolation_is_blocked(conn):
    assert checks.check_state_change(conn, "EV-1", "open").verdict == checks.BLOCK
    assert checks.check_state_change(conn, "RLV-504", "closed").verdict == checks.CLEAR


def test_closing_a_permit_reports_isolations_still_needed(conn):
    checks.check(conn, permit("PTW-0847"), approve=True)
    with store.transaction(conn, commit=True):
        still = store.close_permit(conn, "PTW-0840")
    assert still == [{"tag": "EV-2", "permits": ["PTW-0847"]}]


def test_unknown_tag_is_rejected(conn):
    bad = {"id": "PTW-9999", "works_on": ["NOPE-1"]}
    with pytest.raises(store.StoreError):
        checks.check(conn, bad)


def test_no_standing_hazards_at_start_of_shift(conn):
    assert checks.standing_hazards(conn) == []


def test_cli_runs_as_a_python_module(tmp_path):
    import subprocess
    import sys
    out = tmp_path / "s.rl"
    built = subprocess.run([sys.executable, "-m", "blindflange", "build", str(SCENARIO), "-o", str(out)],
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    checked = subprocess.run([sys.executable, "-m", "blindflange", "check",
                              str(ROOT / "data" / "permits" / "PTW-0511.yaml"), "--store", str(out)],
                             capture_output=True, text=True)
    assert checked.returncode == 2, checked.stderr
    assert checked.stdout.startswith("BLOCK  PTW-0511")
