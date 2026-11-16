"""The evaluator: the one place a result is decided.

A request (a permit, or a set of state changes) is assessed by writing it into
the store inside a transaction, asking the graph what changes, and rolling back.
Approval is the same steps with a commit, so what was checked is exactly what is
stored. Every interface (CLI, agent tools, eval) calls `evaluate` here.

The graph decides what is reached and by which path (queries/*.cypher). This
module only sorts those rows into findings and applies the result rules in
docs/REQUIREMENTS.md section 8.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import store, validate

BLOCK, HOLD, CLEAR = "BLOCK", "HOLD", "CLEAR"
UNCONFIRMED = "UNCONFIRMED"                     # a POSSIBLE finding: it decides nothing, it makes the result INCOMPLETE
COMPLETE, INCOMPLETE, ERROR = "COMPLETE", "INCOMPLETE", "ERROR"
PROVEN, POSSIBLE = "PROVEN", "POSSIBLE"
INTRODUCED, EXISTING = "introduced", "existing"

CHANGE_ID = "__change__"                        # id of the temporary permit that carries a state change

SEVERITY = {
    "PRESSURE_REACHES_OPEN_WORK": BLOCK,
    "PRESSURE_REACHES_TEMPORARY_BARRIER": BLOCK,
    "PRESSURE_REACHES_OPEN_END": BLOCK,
    "WORKSITE_NOT_ISOLATED": BLOCK,
    "ENERGISES_WORKSITE": BLOCK,
    "ISOLATION_REMOVED": BLOCK,
    "ISOLATION_NOT_IN_PLACE": BLOCK,
    "SHARED_ISOLATION": HOLD,
    "WORKSITE_SHARED": HOLD,
}

EXPLAIN = {
    "PRESSURE_REACHES_OPEN_WORK":
        "Pressure {would} reach {target}, where {permit} has broken containment.",
    "PRESSURE_REACHES_TEMPORARY_BARRIER":
        "Pressure {would} reach {target}, a temporary barrier that {permit} relies on. "
        "It has not been pressure-tested.",
    "PRESSURE_REACHES_OPEN_END":
        "Pressure {would} reach {target}, which is removed. The pipe is open there.",
    "WORKSITE_NOT_ISOLATED":
        "{target} {is} not isolated from live pressure. The listed isolations do not close every route.",
    "ENERGISES_WORKSITE":
        "This request energises {target} while {permit} is working on it.",
    "ISOLATION_REMOVED":
        "This request changes {target}, which {permit} relies on as an isolation.",
    "ISOLATION_NOT_IN_PLACE":
        "{target} is listed as an isolation but is not confirmed in an isolating state.",
    "SHARED_ISOLATION":
        "{target} is also an isolation for {permit}. It must stay in place until both permits close.",
    "WORKSITE_SHARED":
        "{permit} is already working on {target}. Two jobs on one opened item is a dependency to review.",
}


@dataclass
class Finding:
    code: str
    severity: str                       # BLOCK | HOLD | UNCONFIRMED: the effect on the result
    origin: str                         # introduced (by this request) | existing (already in the plant)
    certainty: str                      # PROVEN | POSSIBLE
    target: str
    permit: str | None = None           # the other permit involved, if any
    permit_title: str | None = None
    sources: list[str] = field(default_factory=list)       # same service as the target, or a declared tie-in
    other_service_sources: list[str] = field(default_factory=list)  # also reach it, through no declared tie-in
    path: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)    # unconfirmed components the path passes
    against_flow: list[str] = field(default_factory=list) # hops that run against a declared one-way flow
    evidence: list[str] = field(default_factory=list)     # graph edges, for one-hop findings
    message: str = ""


@dataclass
class Result:
    request: dict                       # {type, id, title}
    assessment_status: str              # COMPLETE | INCOMPLETE | ERROR
    conflict_verdict: str | None        # BLOCK | HOLD | CLEAR | None
    findings: list[Finding] = field(default_factory=list)
    hazards: dict = field(default_factory=dict)        # existing / introduced / remaining / resolved
    incomplete_reasons: list[str] = field(default_factory=list)
    unknowns: list[dict] = field(default_factory=list)  # unconfirmed components, disclosed
    baseline_shared_tags: dict = field(default_factory=dict)
    hypothetical: list[dict] = field(default_factory=list)
    revision: int | None = None
    assessed_at: str | None = None
    mode: str | None = None             # snapshot (assessed at the store's as_of) or live (assessed now)
    max_hops: int | None = None
    error: str | None = None
    evaluation_id: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["baseline_verdict"] = "FLAG" if self.baseline_shared_tags else "PASS"
        return d

    @property
    def verdict(self) -> str:
        """One word for people: the verdict, or INCOMPLETE / ERROR when there is none."""
        return self.conflict_verdict or self.assessment_status


# ---------------------------------------------------------------- requests

def permit_request(permit: dict) -> dict:
    return {"type": "permit", "id": permit.get("id") if isinstance(permit, dict) else None, "permit": permit}


def change_request(changes: list[dict]) -> dict:
    return {"type": "change", "id": CHANGE_ID, "changes": changes}


def parse_changes(items: list[str]) -> list[dict]:
    """['RLV-504=closed', ...] -> [{'tag': 'RLV-504', 'to': 'closed'}, ...]"""
    out = []
    for s in items:
        if "=" not in s:
            raise store.StoreError(f"a change looks like TAG=STATE, got {s!r}")
        tag, to = s.split("=", 1)
        out.append({"tag": tag.strip(), "to": to.strip()})
    return out


def _describe(req: dict) -> dict:
    if req["type"] == "survey":
        return {"type": "survey", "id": None, "title": "Hazards in the plant as it stands"}
    if req["type"] == "permit":
        p = req["permit"] if isinstance(req["permit"], dict) else {}
        return {"type": "permit", "id": p.get("id"), "title": p.get("title", p.get("id"))}
    text = ", ".join(f"{c.get('tag')} {c.get('to')}" for c in req["changes"] if isinstance(c, dict))
    return {"type": "change", "id": None, "title": f"Set {text}"}


def _as_permit(conn, req: dict) -> dict:
    """The request as a permit to write into the graph. Raises ValidationError on bad input."""
    if req["type"] == "survey":
        return {"id": CHANGE_ID, "title": "Survey", "kind": "survey"}
    if req["type"] == "permit":
        permit = req["permit"]
        problems = validate.permit(permit)
        if problems:
            raise store.ValidationError("request", problems)
        if permit["id"] == CHANGE_ID:
            raise store.ValidationError("request", [f"permit id {CHANGE_ID} is reserved"])
        return permit
    changes = req["changes"]
    problems = validate.changes(changes)
    if not problems:
        problems = validate.changes(changes, store.kinds_for(conn, [c["tag"] for c in changes]))
    if problems:
        raise store.ValidationError("request", problems)
    return {"id": CHANGE_ID, "title": _describe(req)["title"], "kind": "state_change", "operates": changes}


# ---------------------------------------------------------------- graph reads

def _exposures(conn, candidate: str, possible: bool, stale_before: str, max_hops: int) -> dict:
    """Rows from exposures.cypher keyed by (permit, target, relation, source), shortest first."""
    out: dict[tuple, dict] = {}
    for r in store.rows(conn, store.query("exposures", max_hops), candidate=candidate,
                        possible=possible, stale_before=stale_before):
        out.setdefault((r["permit"], r["target"], r["relation"], r["source"]), r)
    return out


def _beyond(conn, candidate: str, stale_before: str, max_hops: int) -> int:
    return store.rows(conn, store.query("bound", max_hops), candidate=candidate,
                      stale_before=stale_before)[0]["beyond"]


def _code(owner: str, relation: str, pid: str) -> str:
    if relation == "OPEN_END":
        return "PRESSURE_REACHES_OPEN_END"
    if relation == "RELIES_ON":
        return "PRESSURE_REACHES_TEMPORARY_BARRIER"
    return "WORKSITE_NOT_ISOLATED" if owner == pid else "PRESSURE_REACHES_OPEN_WORK"


def _message(code: str, target: str, permit: str | None, certainty: str, origin: str,
             against_flow: list[str] | tuple = ()) -> str:
    would = "could" if certainty == POSSIBLE else ("would" if origin == INTRODUCED else "already can")
    is_ = "may be" if certainty == POSSIBLE else "is"
    msg = EXPLAIN[code].format(target=target, permit=permit or "another permit", would=would, is_=is_,
                               **{"is": is_})
    if against_flow:
        msg += f" The route runs against declared flow at {', '.join(against_flow)}."
    if origin == EXISTING:
        msg += " This hazard exists already; the request does not remove it."
    return msg


# ---------------------------------------------------------------- the assessment

def assess(conn, req: dict, hypothetical: list[dict] | tuple = (), max_hops: int | None = None,
           at: str | None = None) -> Result:
    """Assess one request against the store. Changes nothing: everything is rolled back.

    Raises ValidationError for unusable input; `evaluate` turns that into an ERROR result.
    """
    info = store.info(conn)
    at = store.assessment_time(info, at)
    stale_before = store.hours_before(at, info["max_age_hours"])
    hops = store.DEFAULT_MAX_HOPS if max_hops is None else max_hops
    if validate.max_hops(hops):
        raise store.ValidationError("request", validate.max_hops(hops))
    hypothetical = list(hypothetical)
    if hypothetical:
        problems = validate.changes(hypothetical, where="what-if") or validate.changes(
            hypothetical, store.kinds_for(conn, [h["tag"] for h in hypothetical]), where="what-if")
        if problems:
            raise store.ValidationError("what-if", problems)

    with store.transaction(conn, commit=False):
        permit = _as_permit(conn, req)
        pid = permit["id"]
        before_proven = _exposures(conn, "", False, stale_before, hops)
        before_possible = _exposures(conn, "", True, stale_before, hops)
        beyond_before = _beyond(conn, "", stale_before, hops)
        for h in hypothetical:
            store.set_state(conn, h["tag"], h["to"], at, "what-if")
        store.write_permit(conn, permit, status="requested", validate_input=req["type"] == "permit")
        store.apply(conn, pid, at)
        after_proven = _exposures(conn, pid, False, stale_before, hops)
        after_possible = _exposures(conn, pid, True, stale_before, hops)
        beyond_after = _beyond(conn, pid, stale_before, hops)
        direct = store.rows(conn, store.query("direct"), id=pid, stale_before=stale_before)
        shared = {r["permit"]: sorted(r["tags"]) for r in store.rows(conn, store.query("baseline"), id=pid)}
        unknowns = store.run(conn, "uncertain", stale_before=stale_before)

    found: list[Finding] = []
    for row in direct:
        other = row["permit"] or None
        certainty = POSSIBLE if row["uncertain"] else PROVEN
        sev = UNCONFIRMED if certainty == POSSIBLE else SEVERITY[row["code"]]
        found.append(Finding(row["code"], sev, INTRODUCED, certainty, row["target"], other, row["title"],
                             evidence=row["evidence"], path=[row["target"]],
                             uncertain=[row["target"]] if row["uncertain"] else [],
                             message=_message(row["code"], row["target"], other, certainty, INTRODUCED)))
    # A BLOCK one-hop finding already explains a path to the same place; a HOLD one does not.
    direct_keys = {(f.permit, f.target) for f in found if f.severity == BLOCK}

    # Sort every pressure exposure after the change by certainty and origin, then
    # group by (permit, target, code) so each hazard is one finding with all its sources.
    # Sources are listed only if they share the target's service or reach it through a
    # declared tie-in; the rest are kept apart (pressure levels are not modelled, so a
    # utility header "reaching" a process line backwards is not worth showing).
    tie_ins = set(info.get("tie_ins") or [])
    groups: dict[tuple, dict] = {}
    for key, row in after_possible.items():
        if key in after_proven:
            certainty, row = PROVEN, after_proven[key]
            origin = EXISTING if key in before_proven else INTRODUCED
        else:
            certainty = POSSIBLE
            origin = EXISTING if key in before_possible else INTRODUCED
        owner = row["permit"]
        code = _code(owner, row["relation"], pid)
        other = None if owner in ("", pid) else owner
        if origin == INTRODUCED and (other, row["target"]) in direct_keys:
            continue                                   # already reported with its one-hop evidence
        g = groups.setdefault((code, row["target"], other, origin, certainty),
                              {"row": row, "sources": [], "other": []})
        tied = (row["source_service"] == row["target_service"]
                or f"{row['source_service']}>{row['target_service']}" in tie_ins)
        g["sources" if tied else "other"].append(row["source"])
        if row["hops"] < g["row"]["hops"]:
            g["row"] = row
    # A hazard proven from one source is not made uncertain by another source whose only
    # route is unconfirmed (an unknown valve, or against declared flow): fold those sources in.
    for key in [k for k in groups if k[4] == POSSIBLE]:
        proven = key[:4] + (PROVEN,)
        if proven in groups:
            groups[proven]["sources"] += groups[key]["sources"]
            groups[proven]["other"] += groups[key]["other"]
            del groups[key]
    for (code, target, other, origin, certainty), g in groups.items():
        row = g["row"]
        if certainty == POSSIBLE:
            sev = UNCONFIRMED
        elif origin == EXISTING:
            sev = HOLD                                 # a standing hazard: review, never CLEAR
        else:
            sev = SEVERITY[code]
        found.append(Finding(code, sev, origin, certainty, target, other, row["title"] if other else None,
                             sources=sorted(set(g["sources"])),
                             other_service_sources=sorted(set(g["other"]) - set(g["sources"])),
                             path=row["path"], uncertain=row["uncertain"], against_flow=row["against_flow"],
                             message=_message(code, target, other, certainty, origin, row["against_flow"])))

    order = {BLOCK: 0, HOLD: 1, UNCONFIRMED: 2}
    found.sort(key=lambda f: (order[f.severity], f.origin != INTRODUCED, f.code, f.target, f.permit or ""))

    def label(key):
        permit_id, target, relation, source = key
        return f"{relation} {target}" + (f" ({permit_id})" if permit_id and permit_id != pid else "") + f" from {source}"

    hazards = {
        "existing": sorted(label(k) for k in before_possible),
        "introduced": sorted(label(k) for k in after_possible if k not in before_possible),
        "remaining": sorted(label(k) for k in after_possible if k in before_possible),
        "resolved": sorted(label(k) for k in before_possible if k not in after_possible),
        "proven": sorted(label(k) for k in after_proven),
    }

    reasons = []
    if beyond_before or beyond_after:
        reasons.append(f"the search stopped at its bound of {hops} hops; "
                       f"{max(beyond_before, beyond_after)} components lie further out")
    relevant = set()
    for f in found:
        if f.certainty == POSSIBLE:
            relevant.update(f.uncertain)
            why = []
            if f.uncertain or not f.against_flow:
                why.append(f"unconfirmed state: {', '.join(f.uncertain) or f.target}")
            if f.against_flow:
                why.append(f"a route against declared flow: {', '.join(f.against_flow)}")
            reasons.append(f"{f.code} at {f.target} depends on {' and '.join(why)}")
    disclosed = [dict(u, relevant=u["tag"] in relevant) for u in unknowns]

    incomplete = bool(reasons)
    if any(f.severity == BLOCK for f in found):
        verdict = BLOCK
    elif any(f.severity == HOLD for f in found):
        verdict = HOLD
    elif incomplete:
        verdict = None
    else:
        verdict = CLEAR
    return Result(_describe(req), INCOMPLETE if incomplete else COMPLETE, verdict, found, hazards, reasons,
                  disclosed, shared, hypothetical, info["revision"], at, info["mode"], hops)


def evaluate(conn, req: dict, hypothetical=(), max_hops: int | None = None, at: str | None = None,
             kind: str = "check", record: bool = True) -> Result:
    """Assess a request and record the Evaluation. Bad input gives an ERROR result, also recorded."""
    try:
        result = assess(conn, req, hypothetical, max_hops, at)
    except store.ValidationError as e:
        info = store.info(conn)
        result = Result(_describe(req), ERROR, None, error="; ".join(e.problems),
                        hypothetical=list(hypothetical), revision=info["revision"],
                        assessed_at=store.assessment_time(info, at), mode=info["mode"], max_hops=max_hops)
    except store.StaleRevisionError:
        raise
    except store.StoreError as e:
        info = store.info(conn)
        result = Result(_describe(req), ERROR, None, error=str(e), hypothetical=list(hypothetical),
                        revision=info["revision"], assessed_at=store.assessment_time(info, at), mode=info["mode"],
                        max_hops=max_hops)
    if record:
        # Record the resolved assessment time, so a live evaluation replays at the time it was made.
        stored_req = dict(req, hypothetical=list(hypothetical), max_hops=max_hops, at=result.assessed_at or at)
        result.evaluation_id = store.record_evaluation(conn, kind, stored_req, _for_record(result),
                                                       store.snapshot(conn))
    return result


def _for_record(result: Result) -> dict:
    d = result.to_dict()
    d.pop("evaluation_id", None)
    return d


def replay(conn, eid: str) -> tuple[dict, dict, bool]:
    """Re-run a recorded evaluation on its own snapshot. Returns (recorded, replayed, same)."""
    e = store.get_evaluation(conn, eid)
    req = dict(e["request"])
    hypothetical = req.pop("hypothetical", [])
    max_hops = req.pop("max_hops", None)
    at = req.pop("at", None)
    copy = store.from_snapshot(e["snapshot"])
    try:
        again = evaluate(copy, req, hypothetical, max_hops, at, record=False)
    finally:
        copy.close()
    replayed = _for_record(again)
    return e["result"], replayed, replayed == e["result"]


# ---------------------------------------------------------------- writes behind a check

def approve(conn, permit: dict, expect_revision: int | None = None, max_hops: int | None = None,
            at: str | None = None) -> tuple[Result, bool]:
    """Assess a permit; store it as active only if the verdict is CLEAR or HOLD."""
    return _decide_and_write(conn, permit_request(permit), "approve", expect_revision, max_hops, at, force=False)


def set_states(conn, changes: list[dict], expect_revision: int | None = None, max_hops: int | None = None,
               at: str | None = None, by: str = "blindflange set", force: bool = False,
               observed_at: str | None = None) -> tuple[Result, bool]:
    """Assess state changes; write them only if the verdict is CLEAR or HOLD (or force).

    The written state is stamped with observed_at (default: now) and `by`.
    """
    return _decide_and_write(conn, change_request(changes), "set", expect_revision, max_hops, at, force, by,
                             observed_at)


def _decide_and_write(conn, req, kind, expect_revision, max_hops, at, force, by=None, observed_at=None):
    current = store.info(conn)["revision"]
    if req["type"] == "change":
        problems = validate.observation(by, observed_at)
        if problems:
            result = Result(_describe(req), ERROR, None, revision=current, max_hops=max_hops,
                            error="; ".join(problems))
            result.evaluation_id = store.record_evaluation(conn, kind, dict(req, by=by, observed_at=observed_at),
                                                           _for_record(result), store.snapshot(conn))
            return result, False
    if expect_revision is not None and expect_revision != current:
        result = Result(_describe(req), ERROR, None, revision=current, max_hops=max_hops,
                        error=f"stale revision: prepared against revision {expect_revision}, "
                              f"store is at revision {current}. Check it again.")
        result.evaluation_id = store.record_evaluation(conn, kind, dict(req, expect_revision=expect_revision),
                                                       _for_record(result), store.snapshot(conn))
        return result, False
    result = evaluate(conn, req, (), max_hops, at, kind=kind)
    if result.assessment_status == ERROR:
        return result, False
    if result.conflict_verdict not in (CLEAR, HOLD) and not force:
        return result, False
    stamp = store.now()
    with store.write(conn, expect_revision=current):
        if req["type"] == "permit":
            store.write_permit(conn, req["permit"], status="requested")
            store.activate(conn, req["permit"]["id"], stamp)
        else:
            for c in req["changes"]:
                store.set_state(conn, c["tag"], c["to"], at=store.timestamp(observed_at) if observed_at else stamp,
                                by=by)
    return result, True


def close(conn, pid: str, expect_revision: int | None = None) -> list[dict]:
    with store.write(conn, expect_revision):
        return store.close_permit(conn, pid, store.now())


def survey(conn, max_hops: int | None = None, at: str | None = None) -> Result:
    """Hazards that exist right now, with no request: an empty change assessed."""
    return assess(conn, {"type": "survey", "id": CHANGE_ID}, (), max_hops, at)
