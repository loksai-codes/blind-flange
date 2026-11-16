"""The larger illustrative plant: size, sources, bypasses, and the headline route."""
import pytest

from blindflange import checks, store
from conftest import ROOT, check

SCENARIO = ROOT / "data" / "scenarios" / "gas_plant.yaml"


@pytest.fixture(scope="module")
def gas():
    c = store.build(SCENARIO)
    yield c
    c.close()


def test_plant_is_large_with_several_sources(gas):
    s = store.run(gas, "stats")[0]
    assert s["components"] >= 150 and s["active_permits"] == 5
    sources = [c for c in store.snapshot(gas)["components"] if c.get("pressure_source")]
    assert len(sources) >= 2


def test_no_standing_hazards_at_start_of_shift(gas):
    r = checks.survey(gas)
    assert (r.assessment_status, r.findings) == (checks.COMPLETE, [])


def test_headline_route_runs_through_a_bypass_and_is_at_least_six_hops(gas):
    r = check(gas, "PTW-2201")
    assert r.conflict_verdict == checks.BLOCK and r.baseline_shared_tags == {}
    f = r.findings[0]
    assert (f.code, f.permit, f.target) == ("PRESSURE_REACHES_TEMPORARY_BARRIER", "PTW-1230", "BF-230")
    assert len(f.path) - 1 >= 6
    assert "BV-231" in f.path and "XV-231" not in f.path      # around the listed isolation, not through it


def test_closing_the_bypass_clears_the_restart(gas):
    r = checks.evaluate(gas, checks.permit_request(store.load_permit(ROOT / "data/permits/PTW-2201.yaml")),
                        hypothetical=[{"tag": "BV-231", "to": "closed"}], record=False)
    assert r.conflict_verdict == checks.CLEAR
