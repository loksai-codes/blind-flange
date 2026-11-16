import sys
from pathlib import Path

import pytest

from blindflange import checks, store

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "data" / "scenarios" / "condensate_unit.yaml"
sys.path.insert(0, str(ROOT / "eval"))          # the oracle lives with the eval

AS_OF = "2026-11-15T06:00:00Z"


def permit(pid):
    return store.load_permit(ROOT / "data" / "permits" / f"{pid}.yaml")


def check(conn, pid_or_permit, **kw):
    p = permit(pid_or_permit) if isinstance(pid_or_permit, str) else pid_or_permit
    return checks.evaluate(conn, checks.permit_request(p), **kw)


def change(conn, *pairs, **kw):
    return checks.evaluate(conn, checks.change_request([{"tag": t, "to": s} for t, s in pairs]), **kw)


def set_now(conn, tag, state, at=AS_OF):
    with store.write(conn):
        store.set_state(conn, tag, state, at, "test")


def codes(result):
    return [f.code for f in result.findings]


def tiny(components, connections, permits=(), as_of=AS_OF, max_age_hours=12):
    """An in-memory store from plain lists. Components default to observed at as_of."""
    comps = []
    for c in components:
        c = dict(c)
        c.setdefault("name", c["tag"])
        if c.get("state") is not None:
            c.setdefault("observed_at", as_of)
        comps.append({k: v for k, v in c.items() if v is not None})
    snap = {"store": {"revision": 1, "as_of": as_of, "max_age_hours": max_age_hours, "plant": "test"},
            "components": comps, "connections": [list(p) for p in connections],
            "permits": [dict(p) for p in permits]}
    return store.from_snapshot(snap)


@pytest.fixture
def conn():
    c = store.build(SCENARIO)
    yield c
    c.close()
