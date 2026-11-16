"""Measure the project's published numbers and write them where they are published.

Runs the tests, the eval and (unless --skip-mutations) the mutation tests, writes
docs/stats.json, and rewrites every marked number in README.md, docs/index.html
and docs/REQUIREMENTS.md. A marked number looks like
    <!--stat:tests_passed-->239<!--/stat-->
tests/test_docs.py fails if a published number no longer matches.

Run:  python scripts/stats.py                 (about 5 minutes with mutations)
      python scripts/stats.py --skip-mutations (keeps the last mutation result)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATS = ROOT / "docs" / "stats.json"
PUBLISHED = [ROOT / "README.md", ROOT / "docs" / "index.html", ROOT / "docs" / "REQUIREMENTS.md"]
MARK = re.compile(r"<!--stat:(\w+)-->(.*?)<!--/stat-->")
SELF_TEST = "tests/test_docs.py::test_published_numbers_match_the_measured_ones"


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True,
                          env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"})


def collected() -> tuple[int, int]:
    """(all tests, random-plant oracle tests) as pytest collects them."""
    r = _run("-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider")
    ids = [l for l in r.stdout.splitlines() if "::" in l]
    return len(ids), sum("test_graph_matches_the_oracle_on_random_plants" in l for l in ids)


def eval_numbers() -> dict:
    text = (ROOT / "eval" / "results.md").read_text(encoding="utf-8")

    def grab(pattern):
        m = re.search(pattern, text)
        if not m:
            raise SystemExit(f"eval/results.md has no line matching {pattern!r}")
        return m.groups()

    matched, cases = grab(r"Graph check: (\d+) of (\d+) cases")
    g_stop, risky, t_stop, permit_risky = grab(r"Risky requests stopped .*?: graph (\d+) of (\d+); "
                                               r"tag matching (\d+) of (\d+)")
    oracle, _ = grab(r"Oracle agreement on every hazard set: (\d+) of (\d+)")
    replay, _ = grab(r"reproduced exactly by replay: (\d+) of (\d+)")
    rows = [l for l in text.splitlines() if l.startswith("| ") and " / " in l]
    no_verdict = sum(1 for l in rows if l.split("|")[3].strip().startswith("none"))
    return {"eval_cases": int(cases), "eval_matched": int(matched), "eval_no_verdict": no_verdict,
            "risky_stopped_by_graph": f"{g_stop} of {risky}", "tag_matching_stopped": f"{t_stop} of {permit_risky}",
            "oracle_agreed": int(oracle), "replay_same": int(replay)}


def measure(mutations: bool) -> dict:
    # The test that checks these numbers runs last, after they are published (see __main__).
    r = _run("-m", "pytest", "-q", "-p", "no:cacheprovider", "--deselect", SELF_TEST)
    m = re.search(r"(\d+) passed", r.stdout)
    failed = re.search(r"(\d+) failed", r.stdout)
    if r.returncode != 0 or not m:
        raise SystemExit("the tests do not pass; fix them before publishing numbers\n" + r.stdout[-2000:])
    total, random_plants = collected()
    e = _run("eval/compare.py")
    if e.returncode != 0:
        raise SystemExit("the eval has misses; fix them before publishing numbers\n" + e.stdout[-2000:])
    stats = {"tests_passed": int(m.group(1)) + 1, "tests_total": total, "tests_failed": int(failed.group(1)) if failed else 0,
             "random_plants": random_plants, **eval_numbers()}
    if mutations:
        sys.path.insert(0, str(ROOT / "scripts"))
        import mutations as mut
        results = mut.run_all()
        stats["mutations_total"] = len(results)
        stats["mutations_caught"] = sum(r["caught"] for r in results)
        stats["mutations"] = results
    else:
        old = json.loads(STATS.read_text(encoding="utf-8")) if STATS.exists() else {}
        for k in ("mutations_total", "mutations_caught", "mutations"):
            if k in old:
                stats[k] = old[k]
    if "mutations_total" in stats:
        stats["mutations_caught_text"] = f"{stats['mutations_caught']} of {stats['mutations_total']}"
    return stats


def publish(stats: dict) -> list[str]:
    changed = []
    for path in PUBLISHED:
        text = path.read_text(encoding="utf-8")

        def fill(m):
            key = m.group(1)
            if key not in stats:
                raise SystemExit(f"{path.name}: unknown stat {key!r}")
            return f"<!--stat:{key}-->{stats[key]}<!--/stat-->"

        new = MARK.sub(fill, text)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed.append(path.name)
    return changed


if __name__ == "__main__":
    s = measure(mutations="--skip-mutations" not in sys.argv)
    STATS.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in s.items() if k != "mutations"}, indent=2))
    print("updated:", ", ".join(publish(s)) or "nothing (already current)")
    check = _run("-m", "pytest", "-q", "-p", "no:cacheprovider", SELF_TEST)
    if check.returncode != 0:
        raise SystemExit("the published numbers do not check out:\n" + check.stdout[-2000:])
    print("published numbers verified by", SELF_TEST)
