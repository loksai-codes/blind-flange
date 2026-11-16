"""Command line: build a store, check and approve permits, change states, hand over."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import checks, store, validate

ARROW = " -> "


def _print_result(r: checks.Result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(r.to_dict(), indent=2))
        return
    label = r.title if r.permit.startswith("__") else f"{r.permit}  {r.title}"
    print(f"{r.verdict}  {label}")
    for i, f in enumerate(r.findings, 1):
        print(f"\n  {i}. [{f.severity}] {f.code}")
        print(f"     {f.message}")
        if f.permit:
            print(f"     Other permit: {f.permit}  {f.permit_title}")
        if f.path:
            n = len(f.path) - 1
            print(f"     Path ({n} hop{'s' if n != 1 else ''}): {ARROW.join(f.path)}")
    if not r.findings:
        print("\n  No conflicts found with active permits or current plant state.")
    if r.baseline_shared_tags:
        pairs = "; ".join(f"{p}: {', '.join(t)}" for p, t in r.baseline_shared_tags.items())
        print(f"\n  Tag matching alone: shared tags with {pairs}.")
    else:
        print("\n  Tag matching alone: no shared tags with any active permit, so it would pass.")


def cmd_build(a) -> int:
    conn = store.build(a.scenario, a.out)
    n = store.rows(conn, "MATCH (c:Component) RETURN count(c) AS n")[0]["n"]
    e = store.rows(conn, "MATCH ()-[r:CONNECTED_TO]->() RETURN count(r) AS n")[0]["n"]
    p = store.rows(conn, "MATCH (p:Permit) RETURN count(p) AS n")[0]["n"]
    conn.close()
    print(f"Built {a.out}: {n} components, {e} connections, {p} permits.")
    return 0


def cmd_check(a, approve: bool = False) -> int:
    permit = store.load_permit(a.permit)
    if approve:
        conn = store.connect(a.store)
        try:
            r = checks.check(conn, permit, approve=True)
        finally:
            conn.close()
    else:
        with store.dry_run(a.store) as conn:
            r = checks.check(conn, permit)
    _print_result(r, a.json)
    if approve and not a.json:
        print("\n  Not approved. Nothing was written." if r.verdict == checks.BLOCK
              else f"\n  Approved and written to {a.store}.")
    return {checks.CLEAR: 0, checks.HOLD: 0, checks.BLOCK: 2}[r.verdict]


def cmd_set(a) -> int:
    conn = store.connect(a.store)
    try:
        r = checks.check_state_change(conn, a.tag, a.state)
        if r.verdict == checks.BLOCK and not a.force:
            _print_result(r, a.json)
            if not a.json:
                print("\n  State not changed. Use --force to override.")
            return 2
        before = store.component(conn, a.tag)["state"]
        with store.transaction(conn, commit=True):
            store.set_state(conn, a.tag, a.state)
    finally:
        conn.close()
    print(f"{a.tag}: {before} -> {a.state}")
    return 0


def cmd_close(a) -> int:
    conn = store.connect(a.store)
    try:
        with store.transaction(conn, commit=True):
            still = store.close_permit(conn, a.permit_id)
    finally:
        conn.close()
    print(f"Closed {a.permit_id}.")
    for s in still:
        print(f"  Keep {s['tag']} in place: still an isolation for {', '.join(s['permits'])}.")
    return 0


def cmd_reach(a) -> int:
    conn = store.connect(a.store, read_only=True)
    try:
        store.component(conn, a.tag)
        got = store.rows(conn, store.query("reach"), tag=a.tag)
    finally:
        conn.close()
    if a.json:
        print(json.dumps(got, indent=2))
        return 0
    print(f"If {a.tag} is live, pressure reaches {len(got)} items:")
    for r in got:
        stop = "  <- stops here" if r["state"] in ("closed", "installed", "removed") else ""
        print(f"  {r['hops']:>2} hop{'s' if r['hops'] != 1 else ' '}  {r['tag']:<10} {r['kind']:<12} {r['state']}{stop}")
    return 0


def cmd_handover(a) -> int:
    conn = store.connect(a.store, read_only=True)
    try:
        permits = store.rows(conn, store.query("handover"))
        off = store.rows(conn, "MATCH (c:Component) WHERE c.state <> c.normal "
                               "RETURN c.tag AS tag, c.name AS name, c.state AS state, c.normal AS normal ORDER BY tag")
        hazards = [f.to_dict() for f in checks.standing_hazards(conn)]
    finally:
        conn.close()
    if a.json:
        print(json.dumps({"permits": permits, "not_normal": off, "hazards": hazards}, indent=2))
        return 0
    print(f"SHIFT HANDOVER  {a.store}\n\nActive permits ({len(permits)})")
    for p in permits:
        print(f"  {p['permit']}  {p['title']}")
        print(f"     works on:  {', '.join(p['works_on']) or '-'}")
        print(f"     relies on: {', '.join(p['relies_on']) or '-'}")
    print(f"\nNot in normal state ({len(off)})")
    for c in off:
        print(f"  {c['tag']:<10} {c['state']:<10} (normally {c['normal']})  {c['name']}")
    print(f"\nStanding hazards ({len(hazards)})")
    for h in hazards:
        print(f"  {h['code']}: {h['message']}\n     {ARROW.join(h['path'])}")
    return 0


def cmd_find(a) -> int:
    words = re.findall(r"[A-Za-z0-9]+", a.text)
    if not words:
        raise store.StoreError("nothing to search for")
    conn = store.connect(a.store, read_only=True)
    try:
        got = store.rows(conn,
                         "CALL db.index.fulltext.queryNodes('component_text', $q) YIELD node, score "
                         "RETURN node.tag AS tag, node.name AS name, score ORDER BY score DESC LIMIT 5",
                         q=" OR ".join(words))
    finally:
        conn.close()
    for r in got:
        print(f"  {r['tag']:<10} {r['name']}")
    if not got:
        print("  No matching components.")
    return 0


def cmd_validate(a) -> int:
    """List every problem in a plant, scenario or permit file."""
    data = store.load_yaml(a.file)
    if isinstance(data, dict) and "components" in data:
        what, problems = "plant", validate.plant(data)
    elif isinstance(data, dict) and "plant" in data:
        what, problems = "scenario", []
        try:
            store.load_scenario(a.file)                     # the scenario, its plant, and permit tags
        except store.ValidationError as e:
            problems = [p if e.source == str(a.file) else f"{e.source}: {p}" for p in e.problems]
    elif isinstance(data, dict) and "id" in data:
        what, problems = "permit", validate.permit(data)
        if not problems and a.store:
            with store.dry_run(a.store) as conn:
                tags = sorted({t for k in ("works_on", "relies_on", "energises") for t in data.get(k, [])}
                              | {o["tag"] for o in data.get("operates", [])})
                kinds = {r["tag"]: r["kind"] for r in store.rows(
                    conn, "MATCH (c:Component) WHERE c.tag IN $tags RETURN c.tag AS tag, c.kind AS kind",
                    tags=tags)}
            problems = validate.permit(data, kinds)
    else:
        raise store.StoreError(f"{a.file}: not a plant (components), scenario (plant) or permit (id) file")
    for p in problems:
        print(f"  {p}")
    if problems:
        print(f"{len(problems)} problem{'s' if len(problems) != 1 else ''} in {a.file}", file=sys.stderr)
        return 1
    note = " (tags not checked; add --store to check them)" if what == "permit" and not a.store else ""
    print(f"{a.file}: valid {what}{note}")
    return 0


class _Parser(argparse.ArgumentParser):
    """Usage errors are one line and exit 1, so exit 2 always means BLOCK."""

    def error(self, message):
        self.exit(1, f"error: {message} (see '{self.prog} -h')\n")


def _run(a) -> int:
    try:
        return a.fn(a)
    except store.StoreError as e:
        print(f"error: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 0
    except Exception as e:                                  # never show a traceback
        if os.environ.get("BLINDFLANGE_DEBUG"):
            raise
        detail = str(e).splitlines()[0] if str(e) else ""
        print(f"error: unexpected {type(e).__name__}{': ' + detail if detail else ''} "
              f"(set BLINDFLANGE_DEBUG=1 for a traceback)", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = _Parser(prog="blindflange", description=__doc__,
                 epilog="Exit codes: 0 done (CLEAR or HOLD), 1 error, 2 BLOCK or refused.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_, description=help_)
        p.set_defaults(fn=fn)
        return p

    p = add("build", cmd_build, "create a store from a scenario file")
    p.add_argument("scenario")
    p.add_argument("-o", "--out", required=True)
    for name, fn, h in (("check", cmd_check, "check a permit without changing the store"),
                        ("approve", lambda a: cmd_check(a, approve=True), "check a permit and store it if not blocked")):
        p = add(name, fn, h)
        p.add_argument("permit", help="permit YAML file")
        p.add_argument("--store", required=True)
        p.add_argument("--json", action="store_true")
    p = add("set", cmd_set, "change a valve, blind or equipment state")
    p.add_argument("tag")
    p.add_argument("state")
    p.add_argument("--store", required=True)
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")
    p = add("close", cmd_close, "close an active permit")
    p.add_argument("permit_id")
    p.add_argument("--store", required=True)
    p = add("reach", cmd_reach, "show what a component would pressurise")
    p.add_argument("tag")
    p.add_argument("--store", required=True)
    p.add_argument("--json", action="store_true")
    p = add("handover", cmd_handover, "print the shift handover summary")
    p.add_argument("--store", required=True)
    p.add_argument("--json", action="store_true")
    p = add("find", cmd_find, "find equipment tags from free text")
    p.add_argument("text")
    p.add_argument("--store", required=True)
    p = add("validate", cmd_validate, "list every problem in a plant, scenario or permit file")
    p.add_argument("file")
    p.add_argument("--store", help="also check a permit's tags against this store")

    a = ap.parse_args(argv)
    return _run(a)


if __name__ == "__main__":
    sys.exit(main())
