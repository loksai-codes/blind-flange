"""Approval records planned states. Only an observation makes a state verified."""
from blindflange import checks, store
from conftest import check, permit, set_now, tiny

SRC = {"tag": "SRC", "kind": "vessel", "state": "in_service", "pressure_source": True}
PLANT = ([SRC, {"tag": "V1", "kind": "valve", "state": "open"}, {"tag": "L2", "kind": "line", "state": "in_service"}],
         [("SRC", "V1"), ("V1", "L2")])
CLOSE_V1 = {"id": "PTW-A", "title": "Close V1", "operates": [{"tag": "V1", "to": "closed"}]}
WORK_L2 = {"id": "PTW-B", "title": "Break L2", "works_on": ["L2"]}


def test_approval_records_planned_states_and_leaves_observations_alone(conn):
    set_now(conn, "RLV-504", "closed")
    before = {t: store.component(conn, t) for t in ("SV-A", "P-A")}
    r, written = checks.approve(conn, permit("PTW-0511"))
    assert written
    for tag, planned in (("SV-A", "open"), ("P-A", "in_service")):
        after = store.component(conn, tag)
        assert {k: after[k] for k in ("state", "observed_at", "observed_by")} == \
               {k: before[tag][k] for k in ("state", "observed_at", "observed_by")}
        assert (after["planned_state"], after["planned_by"]) == (planned, "PTW-0511")


def test_permit_isolated_only_by_a_planned_closure_is_incomplete():
    c = tiny(*PLANT)
    try:
        _, written = checks.approve(c, CLOSE_V1)
        assert written
        r = check(c, WORK_L2)
        assert (r.assessment_status, r.conflict_verdict) == (checks.INCOMPLETE, None)
        f = r.findings[0]
        assert (f.code, f.certainty, f.uncertain) == ("WORKSITE_NOT_ISOLATED", checks.POSSIBLE, ["V1"])
    finally:
        c.close()


def test_the_same_permit_is_block_when_the_valve_was_never_closed():
    c = tiny(*PLANT)
    try:
        r = check(c, WORK_L2)
        assert (r.assessment_status, r.conflict_verdict) == (checks.COMPLETE, checks.BLOCK)
    finally:
        c.close()


def test_an_observation_makes_the_planned_state_verified():
    c = tiny(*PLANT)
    try:
        checks.approve(c, CLOSE_V1)
        _, written = checks.set_states(c, [{"tag": "V1", "to": "closed"}], by="operator J. Doe")
        assert written
        v1 = store.component(c, "V1")
        assert (v1["state"], v1["observed_by"], v1["planned_state"]) == ("closed", "operator J. Doe", None)
        assert check(c, WORK_L2).conflict_verdict == checks.CLEAR
    finally:
        c.close()


def test_what_if_may_assume_the_planned_state():
    c = tiny(*PLANT)
    try:
        checks.approve(c, CLOSE_V1)
        r = checks.evaluate(c, checks.permit_request(WORK_L2), hypothetical=[{"tag": "V1", "to": "closed"}])
        assert (r.assessment_status, r.conflict_verdict) == (checks.COMPLETE, checks.CLEAR)
    finally:
        c.close()


def test_planned_states_survive_snapshot_and_replay():
    c = tiny(*PLANT)
    try:
        checks.approve(c, CLOSE_V1)
        r = check(c, WORK_L2)
        snap = store.get_evaluation(c, r.evaluation_id)["snapshot"]
        v1 = next(x for x in snap["components"] if x["tag"] == "V1")
        assert (v1["planned_state"], v1["planned_by"]) == ("closed", "PTW-A")
        assert checks.replay(c, r.evaluation_id)[2]
    finally:
        c.close()
