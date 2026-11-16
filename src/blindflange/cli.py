"""Command line: build a store, assess permits and state changes, what-if, hand over, replay."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import checks, render, store, validate

ARROW = " -> "
EXIT = {checks.CLEAR: 0, checks.HOLD: 0, checks.BLOCK: 2}


def _exit_code(r: checks.Result) -> int:
    if r.assessment_status == checks.ERROR:
        return 1
    if r.conflict_verdict is None:
        return 3
    return EXIT[r.conflict_verdict]


def _emit(r: checks.Result, as_json: bool) -> None:
    print(json.dumps(r.to_dict(), indent=2) if as_json else render.result_text(r))


def _changes(items: list[str]) -> list[dict]:
    """Accept TAG=STATE pairs, or the older form TAG STATE."""
    if len(items) == 2 and not any("=" in s for s in items):
        return [{"tag": items[0], "to": items[1]}]
    return checks.parse_changes(items)


def cmd_build(a) -> int:
    conn = store.build(a.scenario, a.out)
    s = store.run(conn, "stats")[0]
    conn.close()
    print(f"Built {a.out}: {s['components']} components, {s['connections']} connections, "
          f"{s['active_permits']} active permits.")
    return 0


def cmd_check(a) -> int:
    permit = store.load_permit(a.permit)
    conn = store.connect(a.store)
    try:
        r = checks.evaluate(conn, checks.permit_request(permit), max_hops=a.max_hops, at=a.at)
    finally:
        conn.close()
    _emit(r, a.json)
    return _exit_code(r)


def cmd_approve(a) -> int:
    permit = store.load_permit(a.permit)
    conn = store.connect(a.store)
    try:
        r, written = checks.approve(conn, permit, a.revision, a.max_hops, a.at)
    finally:
        conn.close()
    _emit(r, a.json)
    if not a.json:
        print(f"\n  Approved and written to {a.store}." if written
              else "\n  Not approved. Nothing was written.")
    return _exit_code(r) if written or r.assessment_status == checks.ERROR else max(_exit_code(r), 2)


def cmd_set(a) -> int:
    changes = _changes(a.changes)
    conn = store.connect(a.store)
    try:
        before = {c["tag"]: store.component(conn, c["tag"])["state"] for c in changes
                  if store.run(conn, "component", tag=c["tag"])}
        r, written = checks.set_states(conn, changes, a.revision, a.max_hops, a.at,
                                       by=a.by, force=a.force, observed_at=a.observed_at)
    finally:
        conn.close()
    if not written:
        _emit(r, a.json)
        if not a.json and r.assessment_status != checks.ERROR:
            print("\n  State not changed. Resolve the findings, or use --force to override.")
        return 1 if r.assessment_status == checks.ERROR else 2
    if a.json:
        print(json.dumps(dict(r.to_dict(), written=True), indent=2))
    else:
        if r.findings:
            print(render.result_text(r) + "\n")
        for c in changes:
            print(f"{c['tag']}: {before.get(c['tag'], '?')} -> {c['to']}")
    return 0


def cmd_whatif(a) -> int:
    hypothetical = checks.parse_changes(a.set)
    conn = store.connect(a.store)
    try:
        if a.permit:
            req = checks.permit_request(store.load_permit(a.permit))
            r = checks.evaluate(conn, req, hypothetical, a.max_hops, a.at, kind="what-if")
        else:
            r = checks.evaluate(conn, checks.change_request(hypothetical), (), a.max_hops, a.at, kind="what-if")
    finally:
        conn.close()
    _emit(r, a.json)
    return _exit_code(r)


def cmd_close(a) -> int:
    conn = store.connect(a.store)
    try:
        still = checks.close(conn, a.permit_id, a.revision)
    finally:
        conn.close()
    print(f"Closed {a.permit_id}.")
    for s in still:
        print(f"  Keep {s['tag']} in place: still an isolation for {', '.join(s['permits'])}.")
    return 0


def cmd_reach(a) -> int:
    hypothetical = checks.parse_changes(a.set or [])
    if hypothetical:                                  # the what-if writes inside a rolled-back transaction
        with store.scratch_copy(a.store) as conn:
            got = _reach(conn, a, hypothetical)
    else:
        conn = store.connect(a.store, read_only=True)
        try:
            got = _reach(conn, a, hypothetical)
        finally:
            conn.close()
    return _print_reach(a, got, hypothetical)


def _reach(conn, a, hypothetical) -> list[dict]:
    store.component(conn, a.tag)
    info = store.info(conn)
    at = store.assessment_time(info, a.at)
    stale_before = store.hours_before(at, info["max_age_hours"])
    problems = validate.changes(hypothetical, store.kinds_for(conn, [h["tag"] for h in hypothetical])) \
        if hypothetical else []
    if problems:
        raise store.ValidationError("what-if", problems)
    with store.transaction(conn, commit=False):
        for h in hypothetical:
            store.set_state(conn, h["tag"], h["to"], at, "what-if")
        return store.rows(conn, store.query("reach", a.max_hops), tag=a.tag, stale_before=stale_before)


def _print_reach(a, got, hypothetical) -> int:
    if a.json:
        print(json.dumps(got, indent=2))
        return 0
    head = f"If {a.tag} is live, pressure could reach {len(got)} items"
    print(head + (" (what-if: " + ", ".join(f"{h['tag']}={h['to']}" for h in hypothetical) + ")" if hypothetical else "") + ":")
    for r in got:
        stop = "  <- stops here" if r["state"] in ("closed", "installed") else (
            "  <- open end" if r["state"] == "removed" else "")
        unc = f"  (via unconfirmed {', '.join(r['uncertain'])})" if r["uncertain"] else ""
        if r.get("against_flow"):
            unc += f"  (against declared flow at {', '.join(r['against_flow'])})"
        print(f"  {r['hops']:>2} hop{'s' if r['hops'] != 1 else ' '}  {r['tag']:<10} {r['kind']:<13} {r['state']}{stop}{unc}")
    return 0


def cmd_handover(a) -> int:
    conn = store.connect(a.store, read_only=True)
    try:
        info = store.info(conn)
        permits = store.rows(conn, store.query("handover"))
        off = store.run(conn, "not_normal")
        unconfirmed = store.run(conn, "uncertain", stale_before=store.stale_before(info))
    finally:
        conn.close()
    with store.scratch_copy(a.store) as conn:  # the survey writes inside a rolled-back transaction
        survey = checks.survey(conn, a.max_hops)
    if a.json:
        print(json.dumps({"store": info, "permits": permits, "not_normal": off, "unconfirmed": unconfirmed,
                          "survey": survey.to_dict()}, indent=2))
        return 0
    print(f"SHIFT HANDOVER  {a.store}  ({info['mode']} store, assessed at {store.assessment_time(info)}, "
          f"revision {info['revision']})")
    print(f"\nActive permits ({len(permits)})")
    for p in permits:
        print(f"  {p['permit']}  {p['title']}")
        print(f"     works on:  {', '.join(p['works_on']) or '-'}")
        print(f"     relies on: {', '.join(p['relies_on']) or '-'}")
    print(f"\nNot in normal state ({len(off)})")
    for c in off:
        print(f"  {c['tag']:<10} {c['state']:<13} (normally {c['normal']})  {c['name']}")
    print(f"\nUnconfirmed states ({len(unconfirmed)})")
    for u in unconfirmed:
        print(f"  {u['tag']:<10} {u['state']:<13} {u['reason']}, observed {u['observed_at'] or 'never'}")
    print(f"\nStanding hazards ({len(survey.findings)})  assessment {survey.assessment_status}")
    for f in survey.findings:
        print(f"  [{f.severity}] {f.code}: {f.message}")
        if len(f.path) > 1:
            print(f"     {ARROW.join(f.path)}")
    for reason in survey.incomplete_reasons:
        if "search stopped" in reason:
            print(f"  Incomplete: {reason}.")
    return 0


def cmd_shift_start(a) -> int:
    info = store.shift_start(a.source, a.out, a.as_of, a.max_age_hours)
    print(f"Started a live store {a.out} from {a.source}: assessed at the current time from now on, "
          f"shift start {info['as_of']}, observations older than {info['max_age_hours']} h count as stale.")
    return 0


def cmd_freshness(a) -> int:
    conn = store.connect(a.store, read_only=True)
    try:
        info = store.info(conn)
        at = store.assessment_time(info, a.at)
        old = store.stale_observations(conn, a.at)
    finally:
        conn.close()
    if a.json:
        print(json.dumps({"assessed_at": at, "mode": info["mode"], "max_age_hours": info["max_age_hours"],
                          "stale": old}, indent=2))
        return 0
    print(f"{a.store}: {info['mode']} store, assessed at {at}, threshold {info['max_age_hours']:g} h "
          f"(observed before {store.hours_before(at, info['max_age_hours'])} is stale)")
    if not old:
        print("  Every observation is within the threshold.")
    for o in old:
        print(f"  {o['tag']:<10} {o['state']:<13} observed {o['observed_at']} by {o['observed_by'] or '?'}")
    return 0


def cmd_find(a) -> int:
    words = re.findall(r"[A-Za-z0-9]+", a.text)
    if not words:
        raise store.StoreError("nothing to search for")
    conn = store.connect(a.store, read_only=True)
    try:
        got = store.run(conn, "find", q=" OR ".join(words))
    finally:
        conn.close()
    for r in got:
        print(f"  {r['tag']:<10} {r['name']}")
    if not got:
        print("  No matching components.")
    return 0


def cmd_evaluations(a) -> int:
    conn = store.connect(a.store, read_only=True)
    try:
        got = store.list_evaluations(conn)
    finally:
        conn.close()
    if a.json:
        print(json.dumps(got, indent=2))
        return 0
    if not got:
        print("  No evaluations recorded.")
    for e in got:
        print(f"  {e['id']:<9} {e['at']}  rev {e['revision']:<3} {e['kind']:<8} {e['request_id'] or '-':<12} "
              f"{e['assessment_status']:<10} {e['conflict_verdict'] or '-'}")
    return 0


def cmd_show(a) -> int:
    conn = store.connect(a.store, read_only=True)
    try:
        e = store.get_evaluation(conn, a.evaluation_id)
    finally:
        conn.close()
    if a.json:
        print(json.dumps(e, indent=2))
        return 0
    r = _result_from_dict(e["result"])
    r.evaluation_id = e["id"]
    print(f"{e['id']}  recorded {e['at']}  kind {e['kind']}  revision {e['revision']}\n")
    print(render.result_text(r))
    return 0


def cmd_replay(a) -> int:
    conn = store.connect(a.store, read_only=True)
    try:
        d = checks.replay_details(conn, a.evaluation_id)
    finally:
        conn.close()
    recorded, replayed = d["recorded"], d["replayed"]
    old = d["recorded_rules"] if d["recorded_rules"] is not None else "unknown (recorded before versioning)"
    print(f"{a.evaluation_id}: recorded {recorded['conflict_verdict'] or recorded['assessment_status']}, "
          f"replayed {replayed['conflict_verdict'] or replayed['assessment_status']} "
          f"(recorded under rules v{old}, replayed under rules v{d['current_rules']}).")
    if d["same"]:
        print("  Reproduced exactly from the recorded snapshot.")
        return 0
    diff = sorted(k for k in recorded if recorded.get(k) != replayed.get(k))
    print(f"  Differs in: {', '.join(diff)}")
    if d["recorded_rules"] != d["current_rules"]:
        print("  Expected if the rules changed between those versions; see the rules history in docs/SPEC.md.")
    else:
        print("  Same rules version, different result: this record does not reproduce.")
    return 1


def cmd_report(a) -> int:
    from . import report
    conn = store.connect(a.store, read_only=True)
    try:
        e = store.get_evaluation(conn, a.evaluation_id)
    finally:
        conn.close()
    html = report.evaluation_html(e)
    out = a.out or f"{a.evaluation_id}.html"
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    print(f"Wrote {out}")
    return 0


def cmd_mcp(a) -> int:
    from . import agent
    return agent.serve(a.store, a.permits)


def cmd_validate(a) -> int:
    """List every problem in a plant, scenario or permit file."""
    data = store.load_yaml(a.file)
    if isinstance(data, dict) and "components" in data:
        what, problems = "plant", validate.plant(data)
    elif isinstance(data, dict) and "plant" in data:
        what, problems = "scenario", []
        try:
            store.load_scenario(a.file)
        except store.ValidationError as e:
            problems = [p if e.source == str(a.file) else f"{e.source}: {p}" for p in e.problems]
    elif isinstance(data, dict) and "id" in data:
        what, problems = "permit", validate.permit(data)
        if not problems and a.store:
            conn = store.connect(a.store, read_only=True)
            try:
                tags = {t for k in ("works_on", "relies_on", "energises") for t in data.get(k, [])}
                tags |= {o["tag"] for o in data.get("operates", [])}
                problems = validate.permit(data, store.kinds_for(conn, tags))
            finally:
                conn.close()
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


def _result_from_dict(d: dict) -> checks.Result:
    d = dict(d)
    d.pop("baseline_verdict", None)
    d["findings"] = [checks.Finding(**f) for f in d["findings"]]
    return checks.Result(**d)


class _Parser(argparse.ArgumentParser):
    """Usage errors are one line and exit 1, so exit 2 always means BLOCK or refused."""

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


def _hops(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {value!r}") from None
    problems = validate.max_hops(n)
    if problems:
        raise argparse.ArgumentTypeError(problems[0])
    return n


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = _Parser(prog="blindflange", description=__doc__,
                 epilog="Exit codes: 0 CLEAR or HOLD (or done), 1 error, 2 BLOCK or refused, "
                        "3 INCOMPLETE with no verdict.")
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=_Parser)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_, description=help_)
        p.set_defaults(fn=fn)
        return p

    def assessment_options(p, revision=False):
        p.add_argument("--store", required=True, help="the .rl store")
        p.add_argument("--json", action="store_true", help="machine-readable output")
        p.add_argument("--max-hops", type=_hops, default=None, help="search bound (default 100)")
        p.add_argument("--at", help="assess as of this time (default: now for a live store, as_of for a snapshot)")
        if revision:
            p.add_argument("--revision", type=int, help="refuse if the store is no longer at this revision")

    p = add("build", cmd_build, "create a store from a scenario file")
    p.add_argument("scenario")
    p.add_argument("-o", "--out", required=True)

    p = add("check", cmd_check, "assess a permit; records an Evaluation, changes nothing else")
    p.add_argument("permit", help="permit YAML file")
    assessment_options(p)

    p = add("approve", cmd_approve, "assess a permit and store it as active if CLEAR or HOLD")
    p.add_argument("permit", help="permit YAML file")
    assessment_options(p, revision=True)

    p = add("set", cmd_set, "record a state change, refused if it is not CLEAR or HOLD")
    p.add_argument("changes", nargs="+", help="TAG=STATE pairs, e.g. RLV-504=closed")
    assessment_options(p, revision=True)
    p.add_argument("--force", action="store_true", help="write even if blocked")
    p.add_argument("--by", default="blindflange set", help="who observed or made the change")
    p.add_argument("--observed-at", help="when the state was observed (default: now)")

    p = add("whatif", cmd_whatif, "assess hypothetical state changes, with or without a permit; changes nothing")
    p.add_argument("--set", action="append", required=True, metavar="TAG=STATE", help="hypothetical change (repeat)")
    p.add_argument("--permit", help="also assess this permit on top of the changes")
    assessment_options(p)

    p = add("close", cmd_close, "close an active permit")
    p.add_argument("permit_id")
    p.add_argument("--store", required=True)
    p.add_argument("--revision", type=int)

    p = add("reach", cmd_reach, "show what a component could pressurise")
    p.add_argument("tag")
    p.add_argument("--store", required=True)
    p.add_argument("--set", action="append", metavar="TAG=STATE", help="hypothetical change (repeat)")
    p.add_argument("--max-hops", type=_hops, default=None)
    p.add_argument("--at")
    p.add_argument("--json", action="store_true")

    p = add("handover", cmd_handover, "print the shift handover summary")
    p.add_argument("--store", required=True)
    p.add_argument("--max-hops", type=_hops, default=None)
    p.add_argument("--json", action="store_true")

    p = add("shift", cmd_shift_start, "start a live store for a shift (assessed at the current time)")
    p.add_argument("action", choices=["start"])
    p.add_argument("--from", dest="source", required=True, help="the store to start from (it is copied)")
    p.add_argument("-o", "--out", required=True, help="the new live store (.rl)")
    p.add_argument("--as-of", help="shift start time (default: now)")
    p.add_argument("--max-age-hours", type=float, help="observations older than this are stale (default: the store's)")

    p = add("freshness", cmd_freshness, "list observations older than the store's threshold")
    p.add_argument("--store", required=True)
    p.add_argument("--at", help="assess as of this time (default: now for a live store, as_of for a snapshot)")
    p.add_argument("--json", action="store_true")

    p = add("find", cmd_find, "find equipment tags from free text")
    p.add_argument("text")
    p.add_argument("--store", required=True)

    p = add("evaluations", cmd_evaluations, "list recorded evaluations")
    p.add_argument("--store", required=True)
    p.add_argument("--json", action="store_true")

    p = add("show", cmd_show, "show a recorded evaluation")
    p.add_argument("evaluation_id")
    p.add_argument("--store", required=True)
    p.add_argument("--json", action="store_true")

    p = add("replay", cmd_replay, "re-run a recorded evaluation on its snapshot and compare")
    p.add_argument("evaluation_id")
    p.add_argument("--store", required=True)

    p = add("report", cmd_report, "write an HTML evidence report for a recorded evaluation")
    p.add_argument("evaluation_id")
    p.add_argument("--store", required=True)
    p.add_argument("-o", "--out", help="output .html file (default EVAL-n.html)")

    p = add("mcp", cmd_mcp, "serve the agent tools (assess_change, what_if, ...) over MCP stdio")
    p.add_argument("--store", required=True)
    p.add_argument("--permits", help="folder of written permit requests (YAML), for list_requests and permit_id")

    p = add("validate", cmd_validate, "list every problem in a plant, scenario or permit file")
    p.add_argument("file")
    p.add_argument("--store", help="also check a permit's tags against this store")

    a = ap.parse_args(argv)
    return _run(a)


if __name__ == "__main__":
    sys.exit(main())
