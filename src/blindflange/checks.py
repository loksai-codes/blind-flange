"""The checks. Each finding carries the graph path that proves it.

A permit is checked by writing it into the store as 'requested' inside a
transaction, asking the graph what would change, and rolling back. Approval is
the same steps with a commit, so what was checked is exactly what is stored.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import store

BLOCK, HOLD, CLEAR = "BLOCK", "HOLD", "CLEAR"

SEVERITY = {
    "PRESSURE_REACHES_OPEN_WORK": BLOCK,
    "PRESSURE_REACHES_TEMPORARY_BARRIER": BLOCK,
    "WORKSITE_NOT_ISOLATED": BLOCK,
    "ENERGISES_WORKSITE": BLOCK,
    "ISOLATION_REMOVED": BLOCK,
    "ISOLATION_NOT_IN_PLACE": BLOCK,
    "SHARED_ISOLATION": HOLD,
}

EXPLAIN = {
    "PRESSURE_REACHES_OPEN_WORK":
        "Pressure would reach {target}, where {permit} has broken containment.",
    "PRESSURE_REACHES_TEMPORARY_BARRIER":
        "Pressure would reach {target}, a temporary barrier that {permit} relies on. "
        "It has not been pressure-tested.",
    "WORKSITE_NOT_ISOLATED":
        "{target} is not isolated from live pressure. The listed isolations do not close every route.",
    "ENERGISES_WORKSITE":
        "This permit energises {target} while {permit} is working on it.",
    "ISOLATION_REMOVED":
        "This permit changes {target}, which {permit} relies on as an isolation.",
    "ISOLATION_NOT_IN_PLACE":
        "{target} is listed as an isolation but is not in an isolating state.",
    "SHARED_ISOLATION":
        "{target} is also an isolation for {permit}. It must stay in place until both permits close.",
}


@dataclass
class Finding:
    code: str
    severity: str
    target: str
    permit: str | None = None          # the other permit involved, if any
    permit_title: str | None = None
    source: str | None = None
    path: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Result:
    permit: str
    title: str
    verdict: str
    findings: list[Finding]
    baseline_shared_tags: dict[str, list[str]]   # permit id -> tags, from plain tag matching

    def to_dict(self) -> dict:
        d = asdict(self)
        d["baseline_verdict"] = "FLAG" if self.baseline_shared_tags else "PASS"
        return d


def _finding(code: str, target: str, permit=None, title=None, source=None, path=None) -> Finding:
    msg = EXPLAIN[code].format(target=target, permit=permit or "another permit")
    return Finding(code, SEVERITY[code], target, permit, title, source, path or [], msg)


def exposures(conn, candidate: str = "", live=(), opened=(), closed=()) -> dict[tuple, dict]:
    """Worksites and temporary barriers that pressure reaches, keyed by (permit, target).

    Keeps the shortest evidence path for each key.
    """
    out: dict[tuple, dict] = {}
    for r in store.rows(conn, store.query("exposures"), candidate=candidate,
                        assume_live=list(live), assume_open=list(opened), assume_closed=list(closed)):
        out.setdefault((r["permit"], r["target"]), r)      # rows arrive ordered by hops
    return out


def findings_for(conn, pid: str) -> list[Finding]:
    """All findings for a permit that is already in the store (requested or active)."""
    what = store.rows(conn, store.query("whatif"), id=pid)[0]
    before = exposures(conn)
    after = exposures(conn, candidate=pid, live=what["live"], opened=what["open"], closed=what["closed"])
    found: list[Finding] = []

    for row in store.rows(conn, store.query("direct"), id=pid, assume_closed=what["closed"]):
        other = None if row["code"] == "ISOLATION_NOT_IN_PLACE" else row["permit"]
        found.append(_finding(row["code"], row["target"], other, row["title"] if other else None))

    direct = {(f.permit, f.target) for f in found}
    for key, row in after.items():
        if key in before:
            continue                                   # already true before this permit: not its doing
        owner, target = key
        if owner == pid:
            code = "WORKSITE_NOT_ISOLATED" if row["relation"] == "WORKS_ON" else "PRESSURE_REACHES_TEMPORARY_BARRIER"
            found.append(_finding(code, target, None, None, row["source"], row["path"]))
        else:
            code = ("PRESSURE_REACHES_OPEN_WORK" if row["relation"] == "WORKS_ON"
                    else "PRESSURE_REACHES_TEMPORARY_BARRIER")
            if (owner, target) not in direct:
                found.append(_finding(code, target, owner, row["title"], row["source"], row["path"]))
    order = {BLOCK: 0, HOLD: 1}
    return sorted(found, key=lambda f: (order[f.severity], f.code, f.target))


def verdict(findings: list[Finding]) -> str:
    if any(f.severity == BLOCK for f in findings):
        return BLOCK
    return HOLD if findings else CLEAR


def baseline(conn, pid: str) -> dict[str, list[str]]:
    """The naive check: does this permit share an equipment tag with an active permit?"""
    got = store.rows(conn,
                     "MATCH (p:Permit {id: $id})-[]->(c:Component)<-[]-(q:Permit {status: 'active'}) "
                     "WHERE q.id <> p.id RETURN q.id AS permit, collect(DISTINCT c.tag) AS tags ORDER BY permit",
                     id=pid)
    return {r["permit"]: sorted(r["tags"]) for r in got}


def check(conn, permit: dict, approve: bool = False) -> Result:
    """Check a permit. With approve=True, store it as active if it is not blocked."""
    pid = permit["id"]
    with store.transaction(conn, commit=False):
        store.write_permit(conn, permit, status="requested")
        found = findings_for(conn, pid)
        shared = baseline(conn, pid)
    result = Result(pid, permit.get("title", pid), verdict(found), found, shared)
    if approve and result.verdict != BLOCK:
        with store.transaction(conn, commit=True):
            store.write_permit(conn, permit, status="requested")
            store.activate(conn, pid)
    return result


def check_state_change(conn, tag: str, state: str) -> Result:
    """Would changing one component's state hurt any active permit?"""
    store.component(conn, tag)
    op = {"id": "__state_change__", "title": f"Set {tag} to {state}", "kind": "operation",
          "operates": [{"tag": tag, "to": state}]}
    return check(conn, op)


def standing_hazards(conn) -> list[Finding]:
    """Exposures that exist right now, with no new permit involved."""
    out = []
    for (owner, target), row in exposures(conn).items():
        code = "PRESSURE_REACHES_OPEN_WORK" if row["relation"] == "WORKS_ON" else "PRESSURE_REACHES_TEMPORARY_BARRIER"
        out.append(_finding(code, target, owner, row["title"], row["source"], row["path"]))
    return out
