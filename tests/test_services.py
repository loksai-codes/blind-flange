"""Services: utilities are segregated from process, and 'also reached from' respects them."""
import re

import pytest

from blindflange import checks, store, validate
from conftest import ROOT, check

PLANTS = {name: ROOT / "data" / "plants" / f"{name}.yaml" for name in ("condensate_unit", "gas_plant")}


@pytest.mark.parametrize("name", PLANTS)
def test_every_component_has_a_service(name):
    plant = store.load_plant(PLANTS[name])
    assert all(isinstance(c.get("service"), str) and c["service"] for c in plant["components"])


@pytest.mark.parametrize("name", PLANTS)
def test_every_cross_service_connection_is_a_declared_tie_in(name):
    plant = store.load_plant(PLANTS[name])
    service = {c["tag"]: c["service"] for c in plant["components"]}
    ties = {tuple(t) for t in plant.get("tie_ins", [])}
    for a, b, *_ in plant["connections"]:
        sa, sb = service[a], service[b]
        assert sa == sb or (sa, sb) in ties or (sb, sa) in ties, (a, sa, b, sb)


def test_instrument_air_is_not_connected_to_any_other_service():
    plant = store.load_plant(PLANTS["gas_plant"])
    service = {c["tag"]: c["service"] for c in plant["components"]}
    assert "instrument_air" in service.values()
    for a, b, *_ in plant["connections"]:
        if "instrument_air" in (service[a], service[b]):
            assert service[a] == service[b], (a, b)


def test_gas_headline_lists_only_same_service_or_tied_in_sources():
    conn = store.build(ROOT / "data" / "scenarios" / "gas_plant.yaml")
    try:
        f = check(conn, "PTW-2201").findings[0]
    finally:
        conn.close()
    assert set(f.sources) == {"K-220", "V-100", "V-110", "V-120", "WH-MAN"}
    assert f.possible_sources == ["L-EXP"]                     # only against non-return valve NRV-220
    assert set(f.other_service_sources) == {"C-400", "MOL", "P-310", "P-41C"}


def test_condensate_headline_hides_the_main_oil_line(conn):
    f = check(conn, "PTW-0511").findings[0]
    assert set(f.sources) == {"JT-DRUM", "P-A"}               # P-B only backwards through its own suction
    assert f.other_service_sources == ["MOL"]


def test_services_survive_snapshot_and_replay(conn):
    r = check(conn, "PTW-0511")
    snap = store.get_evaluation(conn, r.evaluation_id)["snapshot"]
    assert {c["tag"]: c["service"] for c in snap["components"]}["MOL"] == "oil"
    assert ["condensate", "oil"] in snap["store"]["tie_ins"]
    assert checks.replay(conn, r.evaluation_id)[2]


@pytest.mark.parametrize("plant, field", [
    ({"components": [{"tag": "V", "kind": "valve", "state": "open", "service": 3}]}, "service"),
    ({"components": [{"tag": "V", "kind": "valve", "state": "open"}], "tie_ins": [["a"]]}, "tie_ins"),
    ({"components": [{"tag": "V", "kind": "valve", "state": "open"}], "tie_ins": "a>b"}, "tie_ins"),
])
def test_service_and_tie_ins_are_validated(plant, field):
    assert any(field in p for p in validate.plant(plant))


def test_readme_says_pressure_levels_are_not_modelled():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r"pressure levels are not model+ed", readme, re.I)
