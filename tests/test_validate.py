"""FR-04: observed_at and observed_by are validated wherever they enter."""
import subprocess
import sys

import pytest

from blindflange import checks, store, validate
from conftest import ROOT, SCENARIO

VALVE = {"tag": "V1", "kind": "valve", "state": "open"}
PLANT = {"components": [VALVE], "connections": []}


@pytest.mark.parametrize("bad", ["yesterday", "2026-13-40T00:00:00Z", 20261115, ""])
def test_plant_rejects_a_malformed_observed_at(bad):
    problems = validate.plant(dict(PLANT, components=[dict(VALVE, observed_at=bad)]))
    assert any("observed_at" in p for p in problems), problems


@pytest.mark.parametrize("bad", ["", "   ", 42, ["op"]])
def test_plant_rejects_a_malformed_observed_by(bad):
    problems = validate.plant(dict(PLANT, components=[dict(VALVE, observed_by=bad)]))
    assert any("observed_by" in p for p in problems), problems


def _scenario(tmp_path, observation):
    plant = tmp_path / "plant.yaml"
    plant.write_text("components:\n  - {tag: V1, kind: valve, state: open}\nconnections: []\n", encoding="utf-8")
    s = tmp_path / "s.yaml"
    s.write_text(f"plant: plant.yaml\nas_of: 2026-11-15T06:00:00Z\nobservations:\n  - {observation}\n",
                 encoding="utf-8")
    return s


@pytest.mark.parametrize("observation, field", [
    ("{tag: V1, state: closed, observed_at: noon}", "observed_at"),
    ("{tag: V1, state: closed, observed_by: 7}", "observed_by"),
    ("{tag: V1, state: closed, observed_by: ''}", "observed_by"),
])
def test_scenario_observations_are_validated(tmp_path, observation, field):
    with pytest.raises(store.ValidationError) as e:
        store.load_scenario(_scenario(tmp_path, observation))
    assert any(field in p for p in e.value.problems), e.value.problems


@pytest.mark.parametrize("by", ["", "   "])
def test_an_observation_needs_an_observer(conn, by):
    r, written = checks.set_states(conn, [{"tag": "RLV-504", "to": "closed"}], by=by)
    assert not written and r.assessment_status == checks.ERROR and "observer" in r.error
    assert store.component(conn, "RLV-504")["state"] == "open"


def test_cli_rejects_a_malformed_observed_at_and_writes_nothing(tmp_path):
    rl = tmp_path / "s.rl"
    store.build(SCENARIO, rl).close()
    r = subprocess.run([sys.executable, "-m", "blindflange", "set", "RLV-504=closed", "--observed-at", "tuesday",
                        "--store", str(rl)], capture_output=True, text=True)
    assert r.returncode == 1 and "Traceback" not in r.stderr + r.stdout
    assert "observed" in (r.stderr + r.stdout).lower()
    conn = store.connect(rl, read_only=True)
    try:
        assert store.component(conn, "RLV-504")["state"] == "open"
    finally:
        conn.close()
