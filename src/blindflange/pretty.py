"""Styled terminal output for a result: a verdict card and each finding's path drawn as a rail.

Shapes data only; decides nothing. Used only when standard output is a terminal that can
show colour (or --color always); pipes, files, --json and the tests get render.result_text.
Standard library only.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap

from . import checks

GLYPHS = "╭╮╰╯─│┌└●◆✖■✔?→·▌"

_SGR = {"reset": "0", "bold": "1", "dim": "2", "italic": "3",
        "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36", "grey": "90",
        "on_red": "97;41", "on_green": "30;42", "on_yellow": "30;43", "on_magenta": "97;45", "on_blue": "97;44"}
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

BADGE = {checks.BLOCK: "on_red", checks.HOLD: "on_yellow", checks.CLEAR: "on_green"}
SEVERITY = {checks.BLOCK: "red", checks.HOLD: "yellow", "UNCONFIRMED": "yellow"}
TARGET = {
    "PRESSURE_REACHES_TEMPORARY_BARRIER": "untested blind",
    "PRESSURE_REACHES_OPEN_WORK": "open work",
    "PRESSURE_REACHES_OPEN_END": "open end: pipe open here",
    "WORKSITE_NOT_ISOLATED": "this request's worksite",
}


# ---------------------------------------------------------------- when to use it

def _windows_vt() -> bool:
    """Turn on ANSI escape handling in a Windows console. True if it is on."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(mode.value & 4) or bool(k.SetConsoleMode(h, mode.value | 4))
    except Exception:
        return False


def wanted(choice: str | None = "auto", stream=None) -> bool:
    """Whether to draw styled output: --color always/never, else NO_COLOR, FORCE_COLOR, then a terminal."""
    stream = stream or sys.stdout
    if choice == "never":
        return False
    if choice == "always" or os.environ.get("FORCE_COLOR"):
        try:
            GLYPHS.encode(stream.encoding or "ascii")
        except (UnicodeEncodeError, LookupError):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                return False
        _windows_vt()
        return True
    try:
        GLYPHS.encode(stream.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        return False
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty()) and _windows_vt()


# ---------------------------------------------------------------- small helpers

def st(text, *styles: str) -> str:
    codes = ";".join(_SGR[s] for s in styles if s)
    return f"\x1b[{codes}m{text}\x1b[0m" if codes else str(text)


def vlen(text: str) -> int:
    return len(_ANSI.sub("", text))


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - vlen(text))


def clip(text: str | None, width: int) -> str:
    text = text or ""
    return text if len(text) <= width else text[: width - 1] + "…"


def _width() -> int:
    return max(72, min(shutil.get_terminal_size((100, 24)).columns - 2, 104))


def _when(ts: str | None) -> str:
    return (ts or "").replace("T", " ").replace(":00Z", " UTC").replace("Z", " UTC")


def _state(s: dict) -> str:
    state = s.get("state") or "unknown"
    colour = {"closed": ("green",), "installed": ("green",), "removed": ("red", "bold"), "unknown": ("yellow",),
              "shutdown": ("grey",), "not_installed": ("yellow",), "in_service": ("grey",),
              "open": ("yellow", "bold")}.get(state, ())
    shown = st(state, *colour)
    if s.get("changed_by_request"):
        return st(s.get("was") or "unknown", "dim") + st(" → ", "magenta") + st(state, "magenta", "bold")
    return shown


# ---------------------------------------------------------------- the card

def _card(r: checks.Result, w: int) -> list[str]:
    req = r.request
    if r.assessment_status == checks.ERROR:
        badge, word = "on_magenta", "ERROR"
    elif r.conflict_verdict:
        badge, word = BADGE[r.conflict_verdict], r.conflict_verdict
    else:
        badge, word = "on_yellow", "NO VERDICT"
    title = f"{st(req['id'], 'bold')}  {req.get('title') or ''}" if req.get("id") else (req.get("title") or "")
    first = f"{st(f' {word} ', badge, 'bold')}  {title}"
    facts = [f"assessment {st(r.assessment_status, 'bold')}",
             f"verdict {st(r.conflict_verdict or 'none', 'bold')}"]
    if r.revision is not None:
        facts.append(f"revision {r.revision}")
    if r.evaluation_id:
        facts.append(st(r.evaluation_id, "cyan"))
    second = st(" · ", "grey").join(facts)
    third = st(f"assessed at {_when(r.assessed_at)} ({r.mode or 'snapshot'} store)", "grey") if r.assessed_at else ""
    inner = w - 4
    rows = [first, second] + ([third] if third else [])
    edge = "grey"
    out = [st("╭" + "─" * (w - 2) + "╮", edge)]
    out += [st("│", edge) + " " + pad(clip_ansi(x, inner), inner) + " " + st("│", edge) for x in rows]
    out.append(st("╰" + "─" * (w - 2) + "╯", edge))
    if r.hypothetical:
        out.append("  " + st("what-if", "magenta", "bold") + "  "
                   + ", ".join(f"{h['tag']} {st('→', 'magenta')} {h['to']}" for h in r.hypothetical)
                   + st("  (assumed for this check; not applied to the store)", "grey"))
    return out


def clip_ansi(text: str, width: int) -> str:
    """Clip text that may hold escape codes to a visible width."""
    if vlen(text) <= width:
        return text
    out, seen = [], 0
    for part in re.split(r"(\x1b\[[0-9;]*m)", text):
        if part.startswith("\x1b["):
            out.append(part)
            continue
        room = width - 1 - seen
        if room <= 0:
            continue
        out.append(part[:room])
        seen += min(len(part), room)
    return "".join(out) + "…\x1b[0m"


# ---------------------------------------------------------------- a finding

def _rail(f: checks.Finding, steps: list[dict], w: int, assumed: set = frozenset()) -> list[str]:
    """assumed: tags whose state the what-if set, as opposed to the request."""
    tw = max(len(s["tag"]) for s in steps)
    sw = max(vlen(_state(s)) for s in steps)
    room = w - (4 + 2 + tw + 2 + 2 + sw) - 16
    nw = min(max(len(s.get("name") or "") for s in steps), max(24, min(52, room)))
    out = []
    last = len(steps) - 1
    for i, s in enumerate(steps):
        rail = "┌" if i == 0 else "└" if i == last else "│"
        note = ""
        changed = st("what-if", "magenta") if s["tag"] in assumed else st("this request", "magenta")
        if i == 0:
            note = st("● live source", "cyan") + (st(", started by ", "cyan") + changed
                                                  if s.get("changed_by_request") else "")
        elif i == last:
            what = TARGET.get(f.code, "reached")
            if f.permit and f.code != "WORKSITE_NOT_ISOLATED":
                what += f" · {f.permit} relies on it" if "BARRIER" in f.code else f" · {f.permit}"
            note = st("✖ " + what, SEVERITY.get(f.severity, "red"), "bold")
        elif s.get("changed_by_request"):
            note = st("◆ ", "magenta") + changed
        if s.get("unconfirmed"):
            note = (note + "  " if note else "") + st("? unconfirmed", "yellow")
        rail_c = st(rail, SEVERITY.get(f.severity, "red"))
        tag = st(s["tag"].ljust(tw), "bold")
        name = st(clip(s.get("name"), nw).ljust(nw), "grey")
        line = f"    {rail_c} {tag}  {name}  {pad(_state(s), sw)}"
        if note and vlen(line) + 2 + vlen(note) > w:
            out.append(line.rstrip())
            cont = st("│" if i != last else " ", SEVERITY.get(f.severity, "red"))
            out.append(f"    {cont} {' ' * tw}  {note}")
        else:
            out.append(f"{line}  {note}".rstrip())
        beside = s.get("barriers_beside") or []
        if beside:
            shown = [f"{b['tag']} {b['state']}" for b in beside[:4]]
            more = f" +{len(beside) - 4}" if len(beside) > 4 else ""
            cont = "│" if i != last else " "
            out.append(f"    {st(cont, SEVERITY.get(f.severity, 'red'))} {' ' * tw}  "
                       + st("■ beside: " + ", ".join(shown) + more, "green", "dim"))
    return out


def _finding(i: int, f: checks.Finding, steps: list[dict] | None, w: int, assumed: set = frozenset()) -> list[str]:
    colour = SEVERITY.get(f.severity, "red")
    tags = [f.severity, "proven" if f.certainty == checks.PROVEN else "possible",
            "new" if f.origin == checks.INTRODUCED else "existing"]
    head = f"  {st(str(i), colour, 'bold')} {st('▌', colour)}{st(f.code, 'bold')}"
    right = st(" · ".join(tags), colour)
    gap = max(2, w - vlen(head) - vlen(right))
    out = ["", head + " " * gap + right]
    for line in textwrap.wrap(f.message, w - 6):
        out.append("    " + line)
    if f.permit:
        out.append("    " + st("other permit", "grey") + f"  {st(f.permit, 'bold')}  {f.permit_title or ''}".rstrip())
    if steps and len(steps) > 1:
        out.append("")
        out += _rail(f, steps, w, assumed)
    elif len(f.path) > 1:
        out.append("    " + st(" → ", "grey").join(f.path))
    for e in f.evidence:
        out.append("    " + st("evidence", "grey") + "  " + e)
    facts = []
    if len(f.path) > 1:
        n = len(f.path) - 1
        facts.append(st(f"{n} hop{'s' if n != 1 else ''}", "bold"))
        others = [s for s in f.sources if s != f.path[0]]
        if others:
            facts.append("also from " + ", ".join(others[:3]) + (f" +{len(others) - 3}" if len(others) > 3 else ""))
        if f.possible_sources:
            facts.append("possibly " + ", ".join(f.possible_sources[:3])
                         + (" +more" if len(f.possible_sources) > 3 else ""))
        if f.other_service_sources:
            facts.append(f"{len(f.other_service_sources)} other-service source"
                         f"{'s' if len(f.other_service_sources) != 1 else ''} (--json)")
    if facts:
        out.append("")
        out += ["    " + line for line in textwrap.wrap(st(" · ", "grey").join(facts), 10_000)]
    if f.uncertain and not (steps and len(steps) > 1):
        out.append("    " + st("? unconfirmed: " + ", ".join(f.uncertain), "yellow"))
    if f.against_flow:
        out.append("    " + st("against declared flow: " + ", ".join(f.against_flow), "yellow"))
    return out


# ---------------------------------------------------------------- the whole result

def result_pretty(r: checks.Result, steps: list[list[dict]] | None = None) -> str:
    """steps[i] is report.path_steps for finding i, or None to draw the path as a plain line."""
    w = _width()
    out = _card(r, w)
    if r.error:
        out += ["", "  " + st("Not assessed: ", "magenta", "bold") + r.error]
        return "\n".join(out)
    for i, f in enumerate(r.findings, 1):
        out += _finding(i, f, (steps or [None] * len(r.findings))[i - 1], w, {h["tag"] for h in r.hypothetical})
    if not r.findings:
        if r.assessment_status == checks.COMPLETE:
            out += ["", "  " + st("✔ No conflicts with active permits or the current plant state.", "green", "bold")]
        else:
            out += ["", "  " + st("No conflict established, but the assessment is incomplete.", "yellow", "bold")]
    for reason in r.incomplete_reasons:
        if "search stopped" in reason:
            out += ["", "  " + st(f"Incomplete: {reason}.", "yellow")]
    other = [u for u in r.unknowns if not u.get("relevant")]
    if other:
        out += ["", "  " + st("Unconfirmed elsewhere (not on any route that matters here): ", "grey")
                + ", ".join(f"{u['tag']} ({u['reason']})" for u in other)]
    if r.request.get("type") == "permit":
        out.append("")
        label = st("tag matching alone", "grey")
        if r.baseline_shared_tags:
            pairs = "; ".join(f"{p}: {', '.join(t)}" for p, t in r.baseline_shared_tags.items())
            out.append(f"  {label}  {st('FLAG', 'yellow', 'bold')}  shared tags with {pairs}")
        else:
            line = f"  {label}  {st('PASS', 'bold')}  shares no tag with any active permit"
            if r.conflict_verdict == checks.BLOCK:
                line += st(", so it would miss this", "red")
            out.append(line)
    return "\n".join(out)
