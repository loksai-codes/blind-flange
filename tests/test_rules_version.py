"""Every evaluation records the rules version it was made under; replay reports it."""
import hashlib
import json
import subprocess
import sys

from blindflange import checks, model, store
from conftest import ROOT, SCENARIO, check


def test_rules_fingerprint_matches_the_declared_version():
    digest = hashlib.sha256()
    for name in model.RULES_FILES:
        digest.update((ROOT / "queries" / f"{name}.cypher").read_bytes().replace(b"\r\n", b"\n"))
    assert digest.hexdigest()[:16] == model.RULES_SHA, (
        "a rule-defining query changed: bump model.RULES_VERSION, set model.RULES_SHA to "
        f"{digest.hexdigest()[:16]!r}, and add a line to the rules history in docs/SPEC.md")


def test_spec_lists_every_rules_version():
    spec = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    for v in range(1, model.RULES_VERSION + 1):
        assert f"| {v} |" in spec, f"docs/SPEC.md has no rules history line for version {v}"


def test_an_evaluation_records_the_rules_version(conn):
    r = check(conn, "PTW-0511")
    assert store.get_evaluation(conn, r.evaluation_id)["rules_version"] == model.RULES_VERSION


def test_replay_reports_both_versions_when_the_rules_changed(tmp_path):
    rl = tmp_path / "s.rl"
    store.build(SCENARIO, rl).close()
    conn = store.connect(rl)
    try:
        r = check(conn, "PTW-0511")
        old = dict(checks._for_record(r), conflict_verdict="CLEAR")      # as an older rule set decided it
        conn.execute("MATCH (e:Evaluation {id: $id}) SET e.rules_version = 1, e.result = $res",
                     {"id": r.evaluation_id, "res": json.dumps(old, sort_keys=True)})
        d = checks.replay_details(conn, r.evaluation_id)
        assert (d["recorded_rules"], d["current_rules"], d["same"]) == (1, model.RULES_VERSION, False)
    finally:
        conn.close()
    out = subprocess.run([sys.executable, "-m", "blindflange", "replay", r.evaluation_id, "--store", str(rl)],
                         capture_output=True, text=True).stdout
    assert f"recorded under rules v1, replayed under rules v{model.RULES_VERSION}" in out
    assert "the rules changed" in out
