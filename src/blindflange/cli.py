"""Command line: build a store, check and approve permits, change states, hand over."""
from __future__ import annotations

import argparse
import json
import re
import sys

from . import checks, store

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
    permit = store.load_yaml(a.permit)
    conn = store.connect(a.store)
    try:
        r = checks.check(conn, permit, approve=approve)
    finally:
        conn.close()
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
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="blindflange", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
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

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except store.StoreError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
