"""The Cypher against an independent breadth-first walk (eval/oracle.py) on random plants."""
import random

import pytest

from blindflange import checks, store
import oracle
from conftest import AS_OF, tiny

STALE = "2026-11-14T00:00:00Z"


def random_plant(rng: random.Random):
    n = rng.randint(6, 18)
    comps = []
    for i in range(n):
        kind = rng.choice(["line", "line", "valve", "valve", "valve", "vessel", "pump", "blind"])
        tag = f"{kind[0].upper()}{i}"
        if kind == "valve":
            state = rng.choice(["open", "open", "closed", "unknown", "removed"])
        elif kind == "blind":
            state = rng.choice(["installed", "not_installed", "unknown"])
        elif kind == "line":
            state = rng.choice(["in_service", "in_service", "in_service", "removed"])
        else:
            state = rng.choice(["in_service", "shutdown", "unknown"])
        c = {"tag": tag, "kind": kind, "state": state}
        if kind in ("vessel", "pump"):
            c["pressure_source"] = rng.random() < 0.6
        if kind == "blind":
            c["integrity"] = rng.choice(["rated", "temporary"])
        if rng.random() < 0.15:
            c["observed_at"] = STALE
        if rng.random() < 0.05:
            c.pop("state")
        comps.append(c)
    tags = [c["tag"] for c in comps]
    edges = set()
    for i in range(1, n):                                       # a random tree ...
        edges.add((tags[rng.randrange(i)], tags[i]))
    for _ in range(rng.randint(0, n // 2)):                     # ... plus loops and bypasses
        a, b = rng.sample(tags, 2)
        if (a, b) not in edges and (b, a) not in edges:
            edges.add((a, b))
    permits = []
    for j in range(rng.randint(1, 3)):
        permits.append({"id": f"PTW-{j}", "works_on": rng.sample(tags, 1),
                        "relies_on": rng.sample(tags, rng.randint(0, 2))})
    return comps, sorted(edges), permits


def random_request(rng, comps):
    valves = [c for c in comps if c["kind"] == "valve"]
    if valves and rng.random() < 0.6:
        v = rng.choice(valves)
        return checks.change_request([{"tag": v["tag"], "to": rng.choice(["open", "closed", "removed"])}])
    equip = [c for c in comps if c["kind"] in ("pump", "vessel")]
    tags = [c["tag"] for c in comps]
    p = {"id": "PTW-R", "works_on": rng.sample(tags, 1)}
    if equip:
        p["energises"] = [rng.choice(equip)["tag"]]
    return checks.permit_request(p)


@pytest.mark.parametrize("seed", range(120))
def test_graph_matches_the_oracle_on_random_plants(seed):
    rng = random.Random(seed)
    comps, edges, permits = random_plant(rng)
    conn = tiny(comps, edges, permits)
    try:
        r = checks.evaluate(conn, random_request(rng, comps), max_hops=rng.choice([3, 6, 100]))
        e = store.get_evaluation(conn, r.evaluation_id)
    finally:
        conn.close()
    if r.assessment_status == checks.ERROR:
        pytest.skip(f"random request was invalid: {r.error}")
    assert oracle.hazards(e) == r.hazards


def test_oracle_is_not_trivially_empty():
    hits = 0
    for seed in range(120):
        rng = random.Random(seed)
        comps, edges, permits = random_plant(rng)
        conn = tiny(comps, edges, permits)
        try:
            r = checks.evaluate(conn, random_request(rng, comps), record=False)
        finally:
            conn.close()
        hits += bool(r.hazards.get("introduced") or r.hazards.get("existing"))
    assert hits > 40
