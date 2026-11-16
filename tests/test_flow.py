"""Declared flow: a route against a one-way connection is POSSIBLE, never PROVEN."""
import pytest

from blindflange import checks, store, validate
from conftest import ROOT, check, tiny

SRC = {"tag": "SRC", "kind": "vessel", "state": "in_service", "pressure_source": True}
NRV = {"tag": "NRV", "kind": "check_valve", "state": "open"}
L1 = {"tag": "L1", "kind": "line", "state": "in_service"}
L2 = {"tag": "L2", "kind": "line", "state": "in_service"}
WORK = {"id": "PTW-W", "works_on": ["L2"]}


def test_route_with_the_flow_is_proven():
    c = tiny([SRC, L1, NRV, L2], [("SRC", "L1"), ("L1", "NRV", "forward"), ("NRV", "L2", "forward")])
    try:
        r = check(c, WORK)
        assert (r.assessment_status, r.conflict_verdict) == (checks.COMPLETE, checks.BLOCK)
        assert r.findings[0].against_flow == []
    finally:
        c.close()


def test_route_against_declared_flow_is_possible_not_proven():
    c = tiny([SRC, L1, NRV, L2], [("SRC", "L1"), ("L2", "NRV", "forward"), ("NRV", "L1", "forward")])
    try:
        r = check(c, WORK)
        assert (r.assessment_status, r.conflict_verdict) == (checks.INCOMPLETE, None)
        f = r.findings[0]
        assert (f.certainty, f.against_flow) == (checks.POSSIBLE, ["L1->NRV", "NRV->L2"])
        assert "against declared flow" in f.message
    finally:
        c.close()


def test_a_proven_hazard_is_not_made_incomplete_by_another_route_against_flow():
    # SRC reaches L2 with the flow; SRC2 reaches it only against the flow.
    src2 = {"tag": "SRC2", "kind": "vessel", "state": "in_service", "pressure_source": True}
    c = tiny([SRC, src2, L1, NRV, L2], [("SRC", "L2"), ("SRC2", "L1"), ("L2", "NRV", "forward"), ("NRV", "L1", "forward")])
    try:
        r = check(c, WORK)
        assert (r.assessment_status, r.conflict_verdict) == (checks.COMPLETE, checks.BLOCK)
        assert [f.certainty for f in r.findings] == [checks.PROVEN]
    finally:
        c.close()


def test_check_valve_connections_must_declare_flow():
    plant = {"components": [SRC, NRV], "connections": [["SRC", "NRV"]]}
    assert any("check valve" in p and "flow" in p for p in validate.plant(plant))
    plant["connections"] = [["SRC", "NRV", "sideways"]]
    assert any("forward" in p for p in validate.plant(plant))
    plant["connections"] = [["SRC", "NRV", "forward"]]
    assert validate.plant(plant) == []


@pytest.mark.parametrize("name", ["condensate_unit", "gas_plant"])
def test_every_check_valve_pump_and_compressor_in_the_plants_is_one_way(name):
    plant = store.load_plant(ROOT / "data" / "plants" / f"{name}.yaml")
    one_way = {c["tag"] for c in plant["components"] if c["kind"] in ("check_valve", "pump", "compressor")}
    assert one_way
    for conn in plant["connections"]:
        if one_way & set(conn[:2]):
            assert conn[2:] == ["forward"], conn


@pytest.mark.parametrize("kind", ["pump", "compressor"])
def test_machine_connections_must_declare_flow(kind):
    plant = {"components": [SRC, {"tag": "M", "kind": kind, "state": "shutdown"}], "connections": [["SRC", "M"]]}
    assert any("flow" in p for p in validate.plant(plant))


def test_pressure_backwards_through_a_stopped_pump_is_possible_not_proven():
    pump = {"tag": "P", "kind": "pump", "state": "shutdown"}
    suction, discharge = dict(L1, tag="LS"), dict(L2, tag="LD")
    # The live source is on the discharge side; the work is on the suction side.
    c = tiny([SRC, discharge, pump, suction], [("SRC", "LD"), ("LS", "P", "forward"), ("P", "LD", "forward")],
             permits=[{"id": "PTW-S", "works_on": ["LS"]}])
    try:
        r = checks.survey(c)
        assert (r.assessment_status, r.conflict_verdict) == (checks.INCOMPLETE, None)
        assert r.findings[0].against_flow == ["LD->P", "P->LS"]
    finally:
        c.close()


def test_condensate_headline_lists_pump_b_only_as_a_possible_source(conn):
    f = check(conn, "PTW-0511").findings[0]
    assert (f.certainty, f.path) == (checks.PROVEN, ["P-A", "L-PD-A", "RLV-504", "L-RL-504", "BF-504"])
    assert set(f.sources) == {"JT-DRUM", "P-A"} and f.possible_sources == ["P-B"]


def test_gas_headline_stays_proven_and_complete():
    conn = store.build(ROOT / "data" / "scenarios" / "gas_plant.yaml")
    try:
        r = check(conn, "PTW-2201")
    finally:
        conn.close()
    assert (r.assessment_status, r.conflict_verdict) == (checks.COMPLETE, checks.BLOCK)
    f = r.findings[0]
    assert (f.certainty, len(f.path) - 1, f.against_flow) == (checks.PROVEN, 12, [])


def test_flow_survives_snapshot_and_replay(conn):
    r = check(conn, "PTW-0511")
    snap = store.get_evaluation(conn, r.evaluation_id)["snapshot"]
    assert ["L-PD-A", "NRV-A", "forward"] in snap["connections"]
    assert checks.replay(conn, r.evaluation_id)[2]
