"""The finding codes and the headline scenario on the condensate unit."""
import pytest

from blindflange import checks, store
from conftest import change, check, codes, permit, set_now


def test_start_pump_a_is_blocked_with_a_path_and_no_shared_tag(conn):
    r = check(conn, "PTW-0511")
    assert (r.conflict_verdict, r.assessment_status) == (checks.BLOCK, checks.COMPLETE)
    f = r.findings[0]
    assert f.code == "PRESSURE_REACHES_TEMPORARY_BARRIER"
    assert (f.permit, f.origin, f.certainty) == ("PTW-0504", checks.INTRODUCED, checks.PROVEN)
    assert f.path == ["P-A", "L-PD-A", "RLV-504", "L-RL-504", "BF-504"]
    assert r.baseline_shared_tags == {}


def test_closing_one_valve_clears_the_conflict(conn):
    set_now(conn, "RLV-504", "closed")
    r = check(conn, "PTW-0511")
    assert (r.conflict_verdict, r.assessment_status, r.findings) == (checks.CLEAR, checks.COMPLETE, [])


def test_check_changes_no_plant_state_or_permits_and_records_one_evaluation(conn):
    before = store.snapshot(conn)
    n = len(store.list_evaluations(conn))
    check(conn, "PTW-0511")
    assert store.snapshot(conn) == before
    assert len(store.list_evaluations(conn)) == n + 1


def test_blocked_permit_is_not_stored_on_approve(conn):
    r, written = checks.approve(conn, permit("PTW-0511"))
    assert r.conflict_verdict == checks.BLOCK and not written
    assert not store.run(conn, "permit_exists", id="PTW-0511")
    assert store.info(conn)["revision"] == 1


def test_approve_stores_permit_applies_state_changes_and_bumps_revision(conn):
    set_now(conn, "RLV-504", "closed")
    r, written = checks.approve(conn, permit("PTW-0511"))
    assert written and r.conflict_verdict == checks.CLEAR
    assert store.run(conn, "permit_exists", id="PTW-0511") == [{"status": "active"}]
    assert store.component(conn, "SV-A")["state"] == "open"
    assert store.component(conn, "P-A")["state"] == "in_service"
    assert store.info(conn)["revision"] == 3


def test_operating_a_relied_on_valve_is_isolation_removed_with_evidence(conn):
    r = check(conn, "PTW-0845")
    f = next(f for f in r.findings if f.code == "ISOLATION_REMOVED")
    assert (f.severity, f.permit, f.target) == (checks.BLOCK, "PTW-0840", "EV-2")
    assert f.evidence == ["PTW-0845 OPERATES EV-2 to open", "PTW-0840 RELIES_ON EV-2"]


def test_unlisted_route_into_open_work_is_found(conn):
    r = check(conn, "PTW-0846")
    f = r.findings[0]
    assert (f.code, f.permit, f.severity) == ("PRESSURE_REACHES_OPEN_WORK", "PTW-0840", checks.BLOCK)
    assert f.path == ["FW-HDR", "XV-9", "E-1"]
    assert r.baseline_shared_tags == {}


def test_shared_isolation_is_a_hold(conn):
    r = check(conn, "PTW-0847")
    assert r.conflict_verdict == checks.HOLD
    assert codes(r) == ["SHARED_ISOLATION"]
    assert r.findings[0].evidence == ["PTW-0847 RELIES_ON EV-2", "PTW-0840 RELIES_ON EV-2"]


def test_open_isolation_valve_is_blocked(conn):
    r = check(conn, "PTW-0849")
    assert r.conflict_verdict == checks.BLOCK
    assert set(codes(r)) == {"ISOLATION_NOT_IN_PLACE", "WORKSITE_NOT_ISOLATED"}
    worksite = next(f for f in r.findings if f.code == "WORKSITE_NOT_ISOLATED")
    assert worksite.path == ["P-B", "L-PD-B", "RLV-505", "L-RL-505"]


@pytest.mark.parametrize("pid", ["PTW-0848", "PTW-0850", "PTW-0851"])
def test_safe_permits_are_clear(conn, pid):
    r = check(conn, pid)
    assert (r.conflict_verdict, r.assessment_status) == (checks.CLEAR, checks.COMPLETE)


def test_energising_a_worksite_is_reported_with_its_own_code(conn):
    checks.approve(conn, permit("PTW-0851"))
    set_now(conn, "RLV-504", "closed")
    r = check(conn, "PTW-0511")
    f = next(f for f in r.findings if f.code == "ENERGISES_WORKSITE")
    assert (f.permit, f.target) == ("PTW-0851", "P-A")
    assert f.evidence == ["PTW-0511 ENERGISES P-A", "PTW-0851 WORKS_ON P-A"]


def test_starting_equipment_by_a_state_change_is_blocked(conn):
    r = change(conn, ("P-A", "in_service"))
    assert r.conflict_verdict == checks.BLOCK
    f = r.findings[0]
    assert (f.code, f.target) == ("PRESSURE_REACHES_TEMPORARY_BARRIER", "BF-504")


def test_set_refuses_a_blocked_change_and_writes_nothing(conn):
    r, written = checks.set_states(conn, [{"tag": "P-A", "to": "in_service"}])
    assert not written and r.conflict_verdict == checks.BLOCK
    assert store.component(conn, "P-A")["state"] == "shutdown"


def test_state_change_that_breaks_an_isolation_is_blocked(conn):
    assert change(conn, ("EV-1", "open")).conflict_verdict == checks.BLOCK
    assert change(conn, ("RLV-504", "closed")).conflict_verdict == checks.CLEAR


def test_closing_a_permit_reports_isolations_still_needed(conn):
    checks.approve(conn, permit("PTW-0847"))
    still = checks.close(conn, "PTW-0840")
    assert still == [{"tag": "EV-2", "permits": ["PTW-0847"]}]


def test_unknown_tag_is_an_error_result_not_an_exception(conn):
    r = check(conn, {"id": "PTW-9999", "works_on": ["NOPE-1"]})
    assert (r.assessment_status, r.conflict_verdict) == (checks.ERROR, None)
    assert "NOPE-1" in r.error


def test_every_finding_has_a_path_or_evidence(conn):
    for pid in ["PTW-0511", "PTW-0845", "PTW-0846", "PTW-0847", "PTW-0849"]:
        for f in check(conn, pid).findings:
            assert len(f.path) > 1 or f.evidence, (pid, f.code)


def test_survey_is_empty_at_start_of_shift_and_finds_a_standing_hazard(conn):
    assert checks.survey(conn).findings == []
    set_now(conn, "EV-1", "open")
    found = checks.survey(conn).findings
    assert [(f.code, f.target, f.origin) for f in found] == [("PRESSURE_REACHES_OPEN_WORK", "E-1", checks.EXISTING)]
