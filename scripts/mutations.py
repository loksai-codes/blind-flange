"""Deliberate mutations of the checks. Each one must make at least one test fail.

Every mutation is applied to a temporary copy of the repository, never to the
working tree. The copy's package is put first on PYTHONPATH, laid out the way
an install lays it out, so the tests import the mutated code.

Run:  python scripts/mutations.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# name -> [(file, text that must occur exactly once, replacement)]
MUTATIONS: dict[str, list[tuple[str, str, str]]] = {
    "M1 unknown state treated as closed": [
        ("queries/exposures.cypher",
         "       OR ( $possible AND (coalesce(a.state, 'unknown') = 'unknown'\n",
         "       OR ( $possible AND (false\n"),
        ("queries/bound.cypher",
         "    WHERE NOT coalesce(a.state, 'unknown') IN ['closed', 'installed', 'removed']\n",
         "    WHERE NOT coalesce(a.state, 'closed') IN ['closed', 'installed', 'removed', 'unknown']\n"),
    ],
    "M2 search-bound check removed": [
        ("src/blindflange/checks.py",
         '    return store.rows(conn, store.query("bound", max_hops), candidate=candidate,\n'
         '                      stale_before=stale_before)[0]["beyond"]',
         "    return 0"),
    ],
    "M3 set skips the evaluator": [
        ("src/blindflange/checks.py",
         "    result = evaluate(conn, req, (), max_hops, at, kind=kind)\n",
         '    result = evaluate(conn, req, (), max_hops, at, kind=kind) if req["type"] == "permit" '
         "else Result(_describe(req), COMPLETE, CLEAR)\n"),
    ],
    "M4 approval writes verified observations": [
        ("src/blindflange/store.py", 'for stmt in statements(query("plan")):', 'for stmt in statements(query("apply")):'),
    ],
    "M5 truncated search returns CLEAR": [
        ("src/blindflange/checks.py", "    elif incomplete:\n        verdict = None",
         "    elif incomplete and not (beyond_before or beyond_after):\n        verdict = None"),
    ],
    "M6 existing hazards hidden": [
        ("src/blindflange/checks.py",
         "            sev = HOLD                                 # a standing hazard: review, never CLEAR",
         "            continue"),
    ],
    "M7 stale-revision check removed": [
        ("src/blindflange/store.py",
         "        if expect_revision is not None and expect_revision != current:\n            raise StaleRevisionError(",
         "        if False:\n            raise StaleRevisionError("),
        ("src/blindflange/checks.py",
         "    if expect_revision is not None and expect_revision != current:\n        result = Result(",
         "    if False:\n        result = Result("),
    ],
    "M8 replay always reports a match": [
        ("src/blindflange/checks.py", '    return e["result"], replayed, replayed == e["result"]',
         '    return e["result"], replayed, True'),
    ],
    "M9 shared worksite not detected": [
        ("queries/direct.cypher",
         "MATCH (p:Permit {id: $id})-[:WORKS_ON]->(v:Component)<-[:WORKS_ON]-(q:Permit {status: 'active'})\n"
         "WHERE q.id <> p.id",
         "MATCH (p:Permit {id: $id})-[:WORKS_ON]->(v:Component)<-[:WORKS_ON]-(q:Permit {status: 'active'})\n"
         "WHERE q.id <> p.id AND false"),
    ],
    "M10 observation accepted without an observer": [
        ("src/blindflange/validate.py", "    if not _text(by):\n", "    if False:\n"),
    ],
}

IGNORE = shutil.ignore_patterns(".git", ".venv", "build", "dist", "*.egg-info", "__pycache__", ".pytest_cache",
                                "*.rl", "work.rl")


def _layout(copy: Path) -> Path:
    """The package as an install lays it out: blindflange/ with queries/ and schema/ inside."""
    pkg = copy / "_pkg"
    shutil.rmtree(pkg, ignore_errors=True)
    shutil.copytree(copy / "src" / "blindflange", pkg / "blindflange", ignore=IGNORE)
    shutil.copytree(copy / "queries", pkg / "blindflange" / "queries", ignore=IGNORE)
    shutil.copytree(copy / "schema", pkg / "blindflange" / "schema", ignore=IGNORE)
    return pkg


def run_one(name: str, edits, python: str = sys.executable) -> dict:
    with tempfile.TemporaryDirectory(prefix="bf-mut-") as d:
        copy = Path(d) / "repo"
        shutil.copytree(ROOT, copy, ignore=IGNORE)
        for path, old, new in edits:
            p = copy / path
            text = p.read_text(encoding="utf-8")
            n = text.count(old)
            if n != 1:
                raise SystemExit(f"{name}: the text to mutate occurs {n} times in {path}; update scripts/mutations.py")
            p.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
        pkg = _layout(copy)
        env = dict(os.environ, PYTHONPATH=str(pkg), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([python, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"], cwd=copy, env=env,
                           capture_output=True, text=True)
        first = re.findall(r"^FAILED (\S+)", r.stdout, re.M)
        return {"name": name, "caught": r.returncode != 0, "first_failure": first[0] if first else None}


def run_all(python: str = sys.executable) -> list[dict]:
    return [run_one(name, edits, python) for name, edits in MUTATIONS.items()]


if __name__ == "__main__":
    results = run_all()
    for r in results:
        print(f"{'caught ' if r['caught'] else 'SURVIVED'}  {r['name']:<45} {r['first_failure'] or ''}")
    caught = sum(r["caught"] for r in results)
    print(f"{caught} of {len(results)} mutations caught")
    sys.exit(0 if caught == len(results) else 1)
