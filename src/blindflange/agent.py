"""Agent tools over the Model Context Protocol (stdio), with no extra dependencies.

An agent reads a permit or a request in plain words, turns it into tags, and
calls these tools. The verdict always comes from the graph, through the same
evaluator the CLI uses. There is deliberately no tool that approves a permit or
changes plant state: agent calls can only append Evaluation records.

Run:  blindflange mcp --store stores/condensate_unit.rl --permits data/permits

With --permits, list_requests shows the written permit requests for this plant
and assess_change / what_if take a permit_id, so a job is checked as written
rather than as the agent reads it.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from . import __version__, checks, store, validate

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

_CHANGE = {"type": "object", "properties": {"tag": {"type": "string"}, "to": {"type": "string"}},
           "required": ["tag", "to"], "additionalProperties": False}
_PERMIT = {
    "type": "object",
    "description": "A permit request. Tags must exist in the plant (use find_tags).",
    "properties": {
        "id": {"type": "string"}, "title": {"type": "string"}, "kind": {"type": "string"},
        "description": {"type": "string"},
        "works_on": {"type": "array", "items": {"type": "string"}, "description": "where containment is broken"},
        "relies_on": {"type": "array", "items": {"type": "string"}, "description": "isolation points"},
        "energises": {"type": "array", "items": {"type": "string"}, "description": "equipment started"},
        "operates": {"type": "array", "items": _CHANGE, "description": "state changes the job needs"},
    },
    "required": ["id"], "additionalProperties": False,
}

_PERMIT_ID = {"type": "string",
              "description": "id of a written request from list_requests; it is assessed exactly as written"}

TOOLS = [
    {"name": "list_requests",
     "description": ("List the written permit requests for this plant: id, title, description and what each "
                     "job starts, opens or closes. Call this first when asked about a job, and assess a match "
                     "by permit_id, so every change the permit makes is checked, not only the ones the "
                     "question names. Read-only."),
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "assess_change",
     "description": ("Assess a proposed permit OR a set of state changes against the plant graph and every "
                     "active permit. Returns assessment_status (COMPLETE, INCOMPLETE, ERROR), conflict_verdict "
                     "(BLOCK, HOLD, CLEAR, or null when it cannot say), and findings, each with the path "
                     "through the piping that proves it. Records an Evaluation; changes nothing else. "
                     "Give exactly one of permit_id (a written request), permit or changes. A partial set "
                     "of changes can be CLEAR while the whole job is not: when a written request exists, "
                     "use permit_id."),
     "inputSchema": {"type": "object", "properties": {
         "permit_id": _PERMIT_ID,
         "permit": _PERMIT,
         "changes": {"type": "array", "items": _CHANGE, "description": "e.g. [{tag: P-A, to: in_service}]"},
         "max_hops": {"type": "integer", "minimum": 1, "maximum": 499}},
         "additionalProperties": False}},
    {"name": "what_if",
     "description": ("Assess hypothetical state changes, optionally with a permit on top (permit_id for a "
                     "written request, or permit), without changing the store. Reports hazards that exist, "
                     "are introduced, remain and are resolved. Records an Evaluation."),
     "inputSchema": {"type": "object", "properties": {
         "changes": {"type": "array", "items": _CHANGE, "minItems": 1},
         "permit_id": _PERMIT_ID,
         "permit": _PERMIT,
         "max_hops": {"type": "integer", "minimum": 1, "maximum": 499}},
         "required": ["changes"], "additionalProperties": False}},
    {"name": "reach",
     "description": "List everything pressure could reach from one component if it were live, with paths.",
     "inputSchema": {"type": "object", "properties": {"tag": {"type": "string"}},
                     "required": ["tag"], "additionalProperties": False}},
    {"name": "handover",
     "description": "Active permits, components not in their normal state, unconfirmed states and standing hazards.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "find_tags",
     "description": "Find equipment tags from free text, e.g. 'pump A relief valve'.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"], "additionalProperties": False}},
    {"name": "trace_path",
     "description": ("Explore the graph: the route between two components read three ways. 'proven' passes "
                     "only components whose state is known and current; 'possible' also passes unconfirmed "
                     "ones and runs against declared flow; 'physical' follows any connection and lists the "
                     "barriers (closed valves, installed blinds, removed items) on the way. A null route means "
                     "there is none under that reading. Read-only."),
     "inputSchema": {"type": "object", "properties": {"from": {"type": "string"}, "to": {"type": "string"}},
                     "required": ["from", "to"], "additionalProperties": False}},
    {"name": "explain_finding",
     "description": ("Explain one finding of a recorded evaluation step by step: each component on its path "
                     "with the state used, whether the request changed it, and the barriers holding beside "
                     "it. 'finding' is its number (1 = first) or its code. Read-only."),
     "inputSchema": {"type": "object", "properties": {
         "evaluation_id": {"type": "string"},
         "finding": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "string"}]}},
         "required": ["evaluation_id", "finding"], "additionalProperties": False}},
    {"name": "get_evaluation",
     "description": "Fetch a recorded Evaluation by id (e.g. EVAL-3), and whether replaying it reproduces it.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                     "required": ["id"], "additionalProperties": False}},
]


class ToolError(Exception):
    pass


LOCK_WAIT_SECONDS = 5.0                 # how long a tool call waits for a store another process holds


def _open(path: str, read_only: bool = False):
    """Open the store, waiting briefly if another process (the CLI, say) holds it."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            return store.connect(path, read_only=read_only)
        except store.StoreError as e:
            if "another process" not in str(e) or time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def _summary(r: checks.Result) -> dict:
    d = r.to_dict()
    d["findings"] = [{k: v for k, v in f.items() if v not in (None, [], "")} for f in d["findings"]]
    # Agents read a bare "baseline_verdict: PASS" as "the plant passed before". Say what it is.
    flagged = d.pop("baseline_verdict") == "FLAG"
    d["tag_matching_baseline"] = ("FLAG: shares a tag with an active permit" if flagged else
                                  "PASS: shares no tag with any active permit. Tag matching does not walk "
                                  "the piping; shown for comparison only, not the plant's state before")
    return d


def _request_files(permits_dir) -> list[tuple[Path, dict]]:
    """Every readable permit file in the folder, as (path, data)."""
    if not permits_dir:
        raise ToolError("no permits folder: start the server with --permits <dir> to read written requests")
    folder = Path(permits_dir)
    if not folder.is_dir():
        raise ToolError(f"permits folder not found: {permits_dir}")
    out = []
    for path in sorted(folder.glob("*.y*ml")):
        try:
            data = store.load_yaml(path)
        except store.StoreError:
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            out.append((path, data))
    return out


def _permit_tags(p: dict) -> set:
    tags = set()
    for key in ("works_on", "relies_on", "energises"):
        tags |= {t for t in p.get(key) or [] if isinstance(t, str)}
    tags |= {o.get("tag") for o in p.get("operates") or []
             if isinstance(o, dict) and isinstance(o.get("tag"), str)}
    return tags


def list_requests(store_path: str, permits_dir) -> dict:
    """Written requests whose every tag is in this plant. Requests for other plants are only counted."""
    files = _request_files(permits_dir)
    every_tag = set().union(*(_permit_tags(d) for _, d in files)) if files else set()
    conn = _open(store_path, read_only=True)
    try:
        known = set(store.kinds_for(conn, every_tag))
        rows = []
        for path, d in files:
            tags = _permit_tags(d)
            if not tags or not tags <= known:
                continue
            rows.append({"id": d["id"], "title": d.get("title"), "description": d.get("description"),
                         "kind": d.get("kind"), "works_on": d.get("works_on") or [],
                         "relies_on": d.get("relies_on") or [], "energises": d.get("energises") or [],
                         "operates": d.get("operates") or [], "file": path.name,
                         "already_active": bool(store.run(conn, "permit_exists", id=d["id"]))})
    finally:
        conn.close()
    return {"requests": rows, "other_plants": len(files) - len(rows)}


def load_request(permits_dir, permit_id: str) -> dict:
    """A written request by id, validated exactly as the CLI validates a permit file."""
    matches = [p for p, d in _request_files(permits_dir) if d.get("id") == permit_id]
    if not matches:
        raise ToolError(f"no written request {permit_id!r} (see list_requests)")
    if len(matches) > 1:
        raise ToolError(f"more than one file has id {permit_id!r}: " + ", ".join(m.name for m in matches))
    return store.load_permit(matches[0])


def call(store_path: str, name: str, args: dict, permits_dir=None) -> dict:
    """Run one tool. Returns plain data. Raises ToolError for bad arguments."""
    args = args or {}
    if name == "list_requests":
        return list_requests(store_path, permits_dir)
    if name in ("assess_change", "what_if"):
        permit, changes = args.get("permit"), args.get("changes")
        max_hops = args.get("max_hops")
        if max_hops is not None and validate.max_hops(max_hops):
            raise ToolError(validate.max_hops(max_hops)[0])
        if args.get("permit_id") is not None:
            if permit:
                raise ToolError("give 'permit_id' or 'permit', not both")
            if not isinstance(args["permit_id"], str):
                raise ToolError("'permit_id' must be a string")
            permit = load_request(permits_dir, args["permit_id"])
        if name == "assess_change":
            if bool(permit) == bool(changes):
                raise ToolError("give exactly one of 'permit_id', 'permit' or 'changes'")
            req, hyp = (checks.permit_request(permit), []) if permit else (checks.change_request(changes), [])
        else:
            if not changes:
                raise ToolError("'changes' is required")
            req, hyp = (checks.permit_request(permit), changes) if permit else (checks.change_request(changes), [])
        conn = _open(store_path)
        try:
            r = checks.evaluate(conn, req, hyp, max_hops, kind=f"agent:{name}")
        finally:
            conn.close()
        return _summary(r)
    if name == "reach":
        conn = _open(store_path, read_only=True)
        try:
            store.component(conn, args.get("tag", ""))
            info = store.info(conn)
            got = store.rows(conn, store.query("reach"), tag=args["tag"], stale_before=store.stale_before(info))
        finally:
            conn.close()
        return {"tag": args["tag"], "reaches": got}
    if name == "handover":
        conn = _open(store_path, read_only=True)
        try:
            info = store.info(conn)
            permits = store.rows(conn, store.query("handover"))
            off = store.run(conn, "not_normal")
            unconfirmed = store.run(conn, "uncertain", stale_before=store.stale_before(info))
        finally:
            conn.close()
        _open(store_path, read_only=True).close()        # wait for the lock, then work on a copy
        with store.scratch_copy(store_path) as conn:
            survey = checks.survey(conn)
        return {"store": info, "active_permits": permits, "not_normal": off, "unconfirmed": unconfirmed,
                "standing_hazards": _summary(survey)}
    if name == "find_tags":
        words = re.findall(r"[A-Za-z0-9]+", args.get("text", ""))
        if not words:
            raise ToolError("nothing to search for")
        conn = _open(store_path, read_only=True)
        try:
            return {"matches": store.run(conn, "find", q=" OR ".join(words))}
        finally:
            conn.close()
    if name == "trace_path":
        conn = _open(store_path, read_only=True)
        try:
            for key in ("from", "to"):
                store.component(conn, args.get(key, ""))
            stale = store.stale_before(store.info(conn))
            routes = {}
            for mode in ("proven", "possible", "physical"):
                got = store.rows(conn, store.query("trace"), **{"from": args["from"], "to": args["to"],
                                                                 "mode": mode, "stale_before": stale})
                routes[mode] = got[0] if got else None
        finally:
            conn.close()
        return {"from": args["from"], "to": args["to"], **routes}
    if name == "explain_finding":
        from . import report
        conn = _open(store_path, read_only=True)
        try:
            e = store.get_evaluation(conn, args.get("evaluation_id", ""))
        finally:
            conn.close()
        findings = e["result"].get("findings", [])
        which = args.get("finding")
        if isinstance(which, int) and 1 <= which <= len(findings):
            f = findings[which - 1]
        else:
            f = next((x for x in findings if x["code"] == which), None)
        if f is None:
            raise ToolError(f"no finding {which!r} in {e['id']} (it has {len(findings)})")
        keep = ("tag", "kind", "name", "state", "observed_at", "changed_by_request", "unconfirmed", "barriers_beside")
        steps = [{k: s[k] for k in keep} for s in report.path_steps(e, f)]
        result = e["result"]
        return {"evaluation_id": e["id"], "assessment_status": result["assessment_status"],
                "conflict_verdict": result["conflict_verdict"], "code": f["code"], "verdict": f["severity"],
                "origin": f["origin"], "certainty": f["certainty"], "message": f["message"],
                "other_permit": f.get("permit"), "steps": steps, "evidence": f.get("evidence", []),
                "against_flow": f.get("against_flow", []), "incomplete_reasons": result.get("incomplete_reasons", [])}
    if name == "get_evaluation":
        conn = _open(store_path, read_only=True)
        try:
            e = store.get_evaluation(conn, args.get("id", ""))
            d = checks.replay_details(conn, e["id"])
        finally:
            conn.close()
        e.pop("snapshot")
        return dict(e, replay_reproduces=d["same"], current_rules_version=d["current_rules"])
    raise ToolError(f"unknown tool {name!r}")


def handle(store_path: str, msg: dict, permits_dir=None) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    mid = msg.get("id")
    method = msg.get("method")
    if mid is None:
        return None                                     # notifications need no answer
    try:
        if method == "initialize":
            asked = (msg.get("params") or {}).get("protocolVersion")
            result = {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "blindflange", "version": __version__},
                      "instructions": ("Permit-to-work conflict checks over a plant piping graph. When asked "
                                       "about a job, call list_requests first and assess a matching written "
                                       "request by permit_id, exactly as written. Only if none matches, use "
                                       "find_tags to turn words into tags and assess the changes, and say "
                                       "which changes you assumed. Report the conflict_verdict and the path "
                                       "from the result; do not decide yourself. A null verdict means the "
                                       "tool could not say: report why.")}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            try:
                data = call(store_path, params.get("name"), params.get("arguments") or {}, permits_dir)
                result = {"content": [{"type": "text", "text": json.dumps(data, indent=1)}],
                          "structuredContent": data, "isError": False}
            except (ToolError, store.StoreError) as e:
                result = {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    except Exception as e:                              # never let one bad call end the session
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(store_path: str, permits_dir=None) -> int:
    store.connect(store_path, read_only=True).close()    # fail early if the store is unusable
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(store_path, msg, permits_dir)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
    return 0
