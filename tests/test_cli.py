"""The command line, run as `python -m blindflange` in a subprocess."""
import json
import subprocess
import sys

import pytest

from conftest import ROOT, SCENARIO

PERMITS = ROOT / "data" / "permits"


def run(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "blindflange", *map(str, args)],
                          capture_output=True, text=True, cwd=cwd)


@pytest.fixture
def rl(tmp_path):
    out = tmp_path / "s.rl"
    built = run("build", SCENARIO, "-o", out)
    assert built.returncode == 0, built.stderr
    assert "35 components, 37 connections, 2 active permits" in built.stdout
    return out


def test_check_prints_block_with_the_path_and_exits_2(rl):
    r = run("check", PERMITS / "PTW-0511.yaml", "--store", rl)
    assert r.returncode == 2, r.stderr
    assert r.stdout.startswith("BLOCK")
    assert "P-A -> L-PD-A -> RLV-504 -> L-RL-504 -> BF-504" in r.stdout


def test_check_json_has_both_result_fields(rl):
    r = run("check", PERMITS / "PTW-0511.yaml", "--store", rl, "--json")
    d = json.loads(r.stdout)
    assert (d["assessment_status"], d["conflict_verdict"]) == ("COMPLETE", "BLOCK")
    assert d["evaluation_id"] == "EVAL-1"


def test_set_refuses_pump_start_then_closing_the_valve_clears_it(rl):
    r = run("set", "P-A=in_service", "--store", rl)
    assert r.returncode == 2 and "State not changed" in r.stdout
    r = run("set", "RLV-504", "closed", "--store", rl)
    assert r.returncode == 0 and "RLV-504: open -> closed" in r.stdout
    assert run("check", PERMITS / "PTW-0511.yaml", "--store", rl).returncode == 0


def test_whatif_changes_nothing(rl):
    r = run("whatif", "--set", "RLV-504=closed", "--permit", PERMITS / "PTW-0511.yaml", "--store", rl)
    assert r.returncode == 0 and r.stdout.startswith("CLEAR")
    assert run("check", PERMITS / "PTW-0511.yaml", "--store", rl).returncode == 2


def test_incomplete_exits_3(rl):
    r = run("check", PERMITS / "PTW-0511.yaml", "--store", rl, "--max-hops", "3")
    assert r.returncode == 3 and r.stdout.startswith("INCOMPLETE")


def test_stale_revision_is_refused(rl):
    run("set", "RLV-504=closed", "--store", rl)
    r = run("approve", PERMITS / "PTW-0511.yaml", "--store", rl, "--revision", "1")
    assert r.returncode == 1 and "stale revision" in r.stdout


def test_evaluations_replay_and_report(rl, tmp_path):
    run("check", PERMITS / "PTW-0511.yaml", "--store", rl)
    assert "EVAL-1" in run("evaluations", "--store", rl).stdout
    r = run("replay", "EVAL-1", "--store", rl)
    assert r.returncode == 0 and "Reproduced exactly" in r.stdout
    out = tmp_path / "e.html"
    assert run("report", "EVAL-1", "--store", rl, "-o", out).returncode == 0
    html = out.read_text(encoding="utf-8")
    assert "<svg" in html and "BF-504" in html


def test_handover_lists_permits_and_hazards(rl):
    r = run("handover", "--store", rl)
    assert r.returncode == 0
    assert "PTW-0504" in r.stdout and "Standing hazards (0)" in r.stdout


def test_bad_input_gives_one_line_errors_and_no_traceback(rl, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a list\n", encoding="utf-8")
    for args in (["check", bad, "--store", rl], ["check", PERMITS / "PTW-0511.yaml", "--store", tmp_path / "nope.rl"],
                 ["set", "BF-504=removed", "--store", rl], ["check", tmp_path / "missing.yaml", "--store", rl],
                 ["reach", "NOPE", "--store", rl], ["check", PERMITS / "PTW-0511.yaml", "--store", rl,
                                                    "--max-hops", "900"]):
        r = run(*args)
        assert r.returncode == 1, (args, r.stdout, r.stderr)
        assert "Traceback" not in r.stderr + r.stdout
    assert not (tmp_path / "nope.rl").exists()


def test_validate_lists_every_problem(tmp_path):
    bad = tmp_path / "p.yaml"
    bad.write_text("id: X\nworks_on: P-A\noperates: [{tag: SV-A}]\n", encoding="utf-8")
    r = run("validate", bad)
    assert r.returncode == 1
    assert "must be a list of tags" in r.stdout and "needs 'tag' and 'to'" in r.stdout


def test_handover_does_not_change_the_store_file(rl):
    before = rl.read_bytes()
    assert run("handover", "--store", rl).returncode == 0
    assert rl.read_bytes() == before
