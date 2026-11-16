"""One test (at least) per modeling rule in docs/REQUIREMENTS.md section 8."""
import pytest

from blindflange import checks, store
from conftest import AS_OF, change, check, codes, set_now, tiny

SRC = {"tag": "SRC", "kind": "vessel", "state": "in_service", "pressure_source": True}


def line(tag, **kw):
    return dict({"tag": tag, "kind": "line", "state": "in_service"}, **kw)


def valve(tag, state="open", **kw):
    return dict({"tag": tag, "kind": "valve", "state": state}, **kw)


WORK = {"id": "PTW-1", "title": "Work on L2", "works_on": ["L2"]}


# Rule 1: pressure passes unless closed or an installed blind; the walk stops there.
def test_rule1_walk_stops_at_closed_valves_and_installed_blinds(conn):
    got = store.rows(conn, store.query("reach"), tag="P-A", stale_before="2026-11-14T18:00:00Z")
    tags = {r["tag"] for r in got}
    assert {"DV-A", "SV-A", "BF-504"} <= tags                  # reached ...
    assert not tags & {"L-DH", "L-SH", "PSV-504"}               # ... and not passed


# Rule 2: a removed component is an open end; a blind cannot be "removed".
def test_rule2_removed_component_is_an_open_end_that_is_not_passed():
    c = tiny([SRC, line("L1"), valve("V1"), line("L2")], [("SRC", "L1"), ("L1", "V1"), ("V1", "L2")])
    r = change(c, ("V1", "removed"))
    assert r.conflict_verdict == checks.BLOCK
    assert [(f.code, f.target, f.path) for f in r.findings] == [
        ("PRESSURE_REACHES_OPEN_END", "V1", ["SRC", "L1", "V1"])]


def test_rule2_removing_a_blind_is_rejected_as_ambiguous(conn):
    r = change(conn, ("BF-504", "removed"))
    assert (r.assessment_status, r.conflict_verdict) == (checks.ERROR, None)
    assert "ambiguous" in r.error


# Rule 3: unknown or stale state is never a barrier, and makes the result
# INCOMPLETE only when it matters.
def test_rule3_component_with_no_state_is_unknown_not_a_barrier():
    c = tiny([SRC, line("L1"), {"tag": "V1", "kind": "valve"}, line("L2")],
             [("SRC", "L1"), ("L1", "V1"), ("V1", "L2")], permits=[WORK])
    r = checks.survey(c)
    assert (r.assessment_status, r.conflict_verdict) == (checks.INCOMPLETE, None)
    f = r.findings[0]
    assert (f.code, f.certainty, f.uncertain) == ("PRESSURE_REACHES_OPEN_WORK", checks.POSSIBLE, ["V1"])


def test_rule3_unknown_state_off_every_relevant_route_is_disclosed_but_does_not_decide(conn):
    set_now(conn, "RLV-504", "closed")
    set_now(conn, "DR-A", "unknown")
    r = check(conn, "PTW-0511")
    assert (r.conflict_verdict, r.assessment_status) == (checks.CLEAR, checks.COMPLETE)
    assert [(u["tag"], u["relevant"]) for u in r.unknowns] == [("DR-A", False)]


def test_rule3_stale_closed_valve_does_not_count_as_isolation(conn):
    set_now(conn, "EV-1", "closed", at="2026-11-14T08:00:00Z")       # 22 h before as_of
    r = check(conn, "PTW-0850")
    assert (r.assessment_status, r.conflict_verdict) == (checks.INCOMPLETE, None)
    assert "EV-1" in r.findings[0].uncertain


def test_rule3_a_known_conflict_is_not_hidden_by_unrelated_uncertainty(conn):
    set_now(conn, "DR-A", "unknown")
    r = check(conn, "PTW-0511")
    assert r.conflict_verdict == checks.BLOCK


# Rule 4: an untested temporary blind that pressure reaches is a BLOCK; a rated one is not.
@pytest.mark.parametrize("integrity, verdict", [("temporary", checks.BLOCK), ("rated", checks.CLEAR)])
def test_rule4_temporary_blind_reached_is_block(integrity, verdict):
    blind = {"tag": "B1", "kind": "blind", "state": "installed", "integrity": integrity}
    c = tiny([SRC, valve("V1", "closed"), blind, line("L2")], [("SRC", "V1"), ("V1", "B1"), ("B1", "L2")],
             permits=[{"id": "PTW-1", "works_on": ["L2"], "relies_on": ["B1"]}])
    assert change(c, ("V1", "open")).conflict_verdict == verdict


# Rule 5: existing, introduced and remaining hazards are reported separately;
# "not newly caused" never means "no conflict".
def test_rule5_existing_hazard_is_hold_not_clear(conn):
    set_now(conn, "EV-1", "open")
    r = check(conn, "PTW-0850")
    assert r.conflict_verdict == checks.HOLD
    f = r.findings[0]
    assert (f.code, f.origin, f.severity) == ("PRESSURE_REACHES_OPEN_WORK", checks.EXISTING, checks.HOLD)
    assert r.hazards["remaining"] and not r.hazards["introduced"]


def test_rule5_request_that_removes_an_existing_hazard_reports_it_resolved(conn):
    set_now(conn, "EV-1", "open")
    r = change(conn, ("EV-1", "closed"))
    assert r.conflict_verdict == checks.CLEAR
    assert r.hazards["resolved"] and not r.hazards["remaining"]


def test_rule5_new_source_into_an_exposed_worksite_is_introduced(conn):
    set_now(conn, "EV-1", "open")
    r = check(conn, "PTW-0846")
    assert r.conflict_verdict == checks.BLOCK
    introduced = [f for f in r.findings if f.origin == checks.INTRODUCED]
    assert [f.sources for f in introduced] == [["FW-HDR"]]


# Rule 6: a search that reaches its bound is INCOMPLETE, never CLEAR.
def test_rule6_search_bound_gives_incomplete_never_clear(conn):
    set_now(conn, "RLV-504", "closed")
    assert check(conn, "PTW-0511").conflict_verdict == checks.CLEAR
    r = check(conn, "PTW-0511", max_hops=2)
    assert (r.assessment_status, r.conflict_verdict) == (checks.INCOMPLETE, None)
    assert any("bound of 2 hops" in x for x in r.incomplete_reasons)


def test_rule6_bound_above_relate_limit_is_rejected(conn):
    r = check(conn, "PTW-0511", max_hops=500)
    assert r.assessment_status == checks.ERROR


def test_rule6_bound_exactly_at_the_longest_route_is_complete():
    comps = [SRC] + [line(f"L{i}") for i in range(1, 6)]
    edges = [("SRC", "L1")] + [(f"L{i}", f"L{i + 1}") for i in range(1, 5)]
    c = tiny(comps, edges)
    assert checks.survey(c, max_hops=5).assessment_status == checks.COMPLETE
    assert checks.survey(c, max_hops=4).assessment_status == checks.INCOMPLETE


# Rule 7: checks use the final state only.
def test_rule7_a_permit_cannot_operate_the_same_component_twice(conn):
    p = {"id": "PTW-7", "operates": [{"tag": "SV-A", "to": "open"}, {"tag": "SV-A", "to": "closed"}]}
    assert check(conn, p).assessment_status == checks.ERROR


# Tied shortest paths: one finding, with a valid shortest path.
def test_tied_shortest_paths_give_one_finding_with_a_valid_path():
    comps = [SRC, valve("VA"), valve("VB"), line("L2")]
    edges = [("SRC", "VA"), ("SRC", "VB"), ("VA", "L2"), ("VB", "L2")]
    c = tiny(comps, edges, permits=[WORK])
    r = checks.survey(c)
    assert len(r.findings) == 1
    path = r.findings[0].path
    assert path[0] == "SRC" and path[-1] == "L2" and len(path) == 3
    assert {tuple(sorted(p)) for p in zip(path, path[1:])} <= {tuple(sorted(e)) for e in edges}


def test_assessment_time_moves_the_stale_threshold(conn):
    assert check(conn, "PTW-0850").assessment_status == checks.COMPLETE
    r = check(conn, "PTW-0850", at="2026-11-16T06:00:00Z")          # a day later, nothing re-observed
    assert r.assessment_status == checks.INCOMPLETE


def test_energising_non_source_equipment_makes_it_live():
    pump = {"tag": "P1", "kind": "pump", "state": "shutdown"}
    c = tiny([pump, line("L2")], [("P1", "L2")], permits=[WORK])
    r = check(c, {"id": "PTW-2", "energises": ["P1"]})
    assert r.conflict_verdict == checks.BLOCK and codes(r) == ["PRESSURE_REACHES_OPEN_WORK"]


def test_as_of_is_fixed_by_the_scenario(conn):
    assert store.info(conn)["as_of"] == AS_OF
