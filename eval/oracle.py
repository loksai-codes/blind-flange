"""An independent traversal used only to check the graph queries.

This is a plain breadth-first search written from docs/SPEC.md, not from the
Cypher. It reads the same inputs an Evaluation records (its snapshot and its
request) and computes the hazard sets the evaluator reports: which (permit,
target, relation, source) pairs pressure reaches before and after the request.
If the Cypher and this disagree, one of them does not follow the spec.

It is never used to decide a result.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

BARRIER = {"closed", "installed"}
OPEN_END = "removed"
CHANGE_ID = "__change__"


def _stale_before(at: str, hours: float) -> str:
    t = datetime.fromisoformat(at.replace("Z", "+00:00")) - timedelta(hours=hours)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _uncertain(c: dict, stale_before: str) -> bool:
    return (c.get("state") or "unknown") == "unknown" or (c.get("observed_at") or "") < stale_before


def _passes(c: dict, possible: bool, stale_before: str) -> bool:
    state = c.get("state") or "unknown"
    if state not in BARRIER and state != OPEN_END and state != "unknown" and (c.get("observed_at") or "") >= stale_before:
        return True
    return possible and _uncertain(c, stale_before)


def _sources(comps: dict, energised: set, possible: bool, stale_before: str) -> list[str]:
    out = []
    for tag, c in comps.items():
        state = c.get("state") or "unknown"
        live = (c.get("pressure_source") or tag in energised) and state == "in_service" and (
            possible or (c.get("observed_at") or "") >= stale_before)
        maybe = possible and c.get("pressure_source") and state != OPEN_END and _uncertain(c, stale_before)
        if live or maybe:
            out.append(tag)
    return out


def exposures(comps: dict, adj: dict, permits: list[dict], candidate: str, energised: set,
              possible: bool, stale_before: str, max_hops: int) -> dict:
    """{(permit, target, relation, source): hops} for every target pressure reaches."""
    targets: dict[str, list[tuple[str, str]]] = {}
    for p in permits:
        if p["status"] != "active" and p["id"] != candidate:
            continue
        for t in p.get("works_on", []):
            targets.setdefault(t, []).append((p["id"], "WORKS_ON"))
        for t in p.get("relies_on", []):
            if comps[t].get("integrity") == "temporary":
                targets.setdefault(t, []).append((p["id"], "RELIES_ON"))
    out = {}
    for s in _sources(comps, energised, possible, stale_before):
        dist = {s: 0}
        queue = deque([s])
        while queue:
            a = queue.popleft()
            if dist[a] >= max_hops or not _passes(comps[a], possible, stale_before):
                continue
            for b in adj[a]:
                if b not in dist:
                    dist[b] = dist[a] + 1
                    queue.append(b)
        for x, h in dist.items():
            for permit, relation in targets.get(x, []):
                out[(permit, x, relation, s)] = h
            if comps[x].get("state") == OPEN_END and not targets.get(x):
                out[("", x, "OPEN_END", s)] = h
    return out


def hazards(evaluation: dict, default_max_hops: int = 100) -> dict:
    """The hazard labels an Evaluation should report, computed from its snapshot and request."""
    snap, req = evaluation["snapshot"], dict(evaluation["request"])
    comps = {c["tag"]: dict(c) for c in snap["components"]}
    adj = {t: [] for t in comps}
    for a, b in snap["connections"]:
        adj[a].append(b)
        adj[b].append(a)
    at = req.get("at") or snap["store"]["as_of"]
    stale_before = _stale_before(at, snap["store"]["max_age_hours"])
    max_hops = req.get("max_hops") or default_max_hops
    permits = [dict(p, status="active") for p in snap["permits"]]

    before = exposures(comps, adj, permits, "", set(), True, stale_before, max_hops)

    for h in req.get("hypothetical", []):
        comps[h["tag"]].update(state=h["to"], observed_at=at)
    if req["type"] == "permit":
        cand = dict(req["permit"], status="requested")
    elif req["type"] == "change":
        cand = {"id": CHANGE_ID, "operates": req["changes"], "status": "requested"}
    else:
        cand = {"id": CHANGE_ID, "status": "requested"}
    for op in cand.get("operates", []):
        comps[op["tag"]].update(state=op["to"], observed_at=at)
    for t in cand.get("energises", []):
        comps[t].update(state="in_service", observed_at=at)
    after = exposures(comps, adj, permits + [cand], cand["id"], set(cand.get("energises", [])),
                      True, stale_before, max_hops)

    def label(key):
        permit, target, relation, source = key
        return f"{relation} {target}" + (f" ({permit})" if permit and permit != cand["id"] else "") + f" from {source}"

    return {
        "existing": sorted(label(k) for k in before),
        "introduced": sorted(label(k) for k in after if k not in before),
        "remaining": sorted(label(k) for k in after if k in before),
        "resolved": sorted(label(k) for k in before if k not in after),
    }


def agrees(evaluation: dict) -> bool:
    """Does the graph's recorded result match the oracle on every hazard set?"""
    result = evaluation["result"]
    if result["assessment_status"] == "ERROR":
        return True                                     # nothing was assessed
    return hazards(evaluation) == result["hazards"]
