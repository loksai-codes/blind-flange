"""A static HTML evidence report for one recorded Evaluation.

Everything comes from the Evaluation record (its result and its snapshot), so
the report shows exactly what was decided and on what inputs. The page is one
self-contained file: inline SVG and CSS, no scripts, no network.
"""
from __future__ import annotations

import html
import math
import random

BARRIER = {"closed", "installed"}

CSS = """
:root { --bg:#fbfaf7; --fg:#1d1d1b; --muted:#6b6a65; --line:#c9c6bd; --card:#ffffff;
  --block:#b3261e; --hold:#9a6700; --clear:#1e7a3c; --unc:#b26b00; --path:#b3261e; --src:#7a1c15;
  --barrier:#1f4e79; --node:#efece4; }
@media (prefers-color-scheme: dark) { :root { --bg:#161614; --fg:#ecebe6; --muted:#a3a19a; --line:#4a4843;
  --card:#1f1f1c; --block:#ff8a80; --hold:#f2c14e; --clear:#7bd88f; --unc:#f2a33a; --path:#ff8a80;
  --src:#ffb4a9; --barrier:#8ab4e8; --node:#2b2a27; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 32px 0 8px; }
.meta { color: var(--muted); font-size: 13px; }
.verdict { display:inline-block; font-weight:700; padding:2px 10px; border-radius:4px; color:#fff; }
.BLOCK { background: var(--block); } .HOLD { background: var(--hold); } .CLEAR { background: var(--clear); }
.INCOMPLETE, .UNCONFIRMED { background: var(--unc); } .ERROR { background: #555; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 14px 16px; margin: 12px 0; }
.card h3 { margin: 0 0 6px; font-size: 15px; }
.tag { font-family: ui-monospace, Consolas, monospace; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
td, th { border-bottom: 1px solid var(--line); padding: 4px 8px; text-align: left; vertical-align: top; }
.note { color: var(--muted); font-size: 13px; }
svg text { fill: var(--fg); font: 11px ui-monospace, Consolas, monospace; }
svg .sub { fill: var(--muted); font-size: 10px; }
"""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _layout(tags: list[str], edges: list[tuple[str, str]], width: float, height: float) -> dict:
    """A deterministic force-directed layout (Fruchterman-Reingold)."""
    rng = random.Random(7)
    n = max(len(tags), 1)
    pos = {t: [width / 2 + width * 0.35 * math.cos(2 * math.pi * i / n) + rng.uniform(-5, 5),
               height / 2 + height * 0.35 * math.sin(2 * math.pi * i / n) + rng.uniform(-5, 5)]
           for i, t in enumerate(tags)}
    k = math.sqrt(width * height / n) * 0.75
    temp = width / 10
    for _ in range(260):
        disp = {t: [0.0, 0.0] for t in tags}
        for i, a in enumerate(tags):
            pa = pos[a]
            for b in tags[i + 1:]:
                pb = pos[b]
                dx, dy = pa[0] - pb[0], pa[1] - pb[1]
                d = math.hypot(dx, dy) or 0.01
                f = k * k / d
                disp[a][0] += dx / d * f
                disp[a][1] += dy / d * f
                disp[b][0] -= dx / d * f
                disp[b][1] -= dy / d * f
        for a, b in edges:
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            d = math.hypot(dx, dy) or 0.01
            f = d * d / k
            disp[a][0] -= dx / d * f
            disp[a][1] -= dy / d * f
            disp[b][0] += dx / d * f
            disp[b][1] += dy / d * f
        for t in tags:                                  # gentle pull to the centre keeps nodes off the walls
            disp[t][0] -= (pos[t][0] - width / 2) * 1.2
            disp[t][1] -= (pos[t][1] - height / 2) * 1.2
            dx, dy = disp[t]
            d = math.hypot(dx, dy) or 0.01
            pos[t][0] = min(width - 40, max(40, pos[t][0] + dx / d * min(d, temp)))
            pos[t][1] = min(height - 20, max(20, pos[t][1] + dy / d * min(d, temp)))
        temp *= 0.97
    return pos


def _plant_svg(snap: dict, result: dict) -> str:
    comps = {c["tag"]: c for c in snap["components"]}
    edges = [tuple(e) for e in snap["connections"]]
    tags = sorted(comps)
    w = 1060
    h = max(420, min(1600, int(9 * len(tags) + 300)))
    pos = _layout(tags, edges, w, h)
    lit_edges, lit_nodes, sources, targets = set(), set(), set(), set()
    for f in result.get("findings", []):
        p = f.get("path", [])
        lit_nodes.update(p)
        lit_edges.update(frozenset(e) for e in zip(p, p[1:]))
        if len(p) > 1:
            sources.add(p[0])
            targets.add(p[-1])
    uncertain = {u["tag"] for u in result.get("unknowns", [])}
    out = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
           f'aria-label="Plant graph with the evidence paths highlighted">']
    for a, b in edges:
        lit = frozenset((a, b)) in lit_edges
        out.append(f'<line x1="{pos[a][0]:.0f}" y1="{pos[a][1]:.0f}" x2="{pos[b][0]:.0f}" y2="{pos[b][1]:.0f}" '
                   f'stroke="var({"--path" if lit else "--line"})" stroke-width="{4 if lit else 1.2}"/>')
    for t in tags:
        c = comps[t]
        x, y = pos[t]
        state = c.get("state") or "unknown"
        if t in sources:
            fill = "var(--src)"
        elif state in BARRIER:
            fill = "var(--barrier)"
        elif t in uncertain:
            fill = "var(--unc)"
        elif t in lit_nodes:
            fill = "var(--path)"
        else:
            fill = "var(--node)"
        r = 7 if t in lit_nodes or state in BARRIER else 5
        shape = (f'<rect x="{x - r:.0f}" y="{y - r:.0f}" width="{2 * r}" height="{2 * r}" fill="{fill}" '
                 f'stroke="var(--fg)" stroke-width="0.6"/>' if c.get("kind") in ("valve", "check_valve",
                                                                                  "control_valve", "psv", "blind")
                 else f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="{fill}" stroke="var(--fg)" stroke-width="0.6"/>')
        weight = ' font-weight="700"' if t in lit_nodes else ""
        out.append(f'<g><title>{_e(t)}: {_e(c.get("name"))} ({_e(state)})</title>{shape}'
                   f'<text x="{x + 9:.0f}" y="{y + 4:.0f}"{weight}>{_e(t)}</text></g>')
    out.append("</svg>")
    return "".join(out)


def _path_svg(path: list[str], comps: dict, adj: dict, uncertain: set) -> str:
    """One finding's path as a strip, with the barriers that hold beside each step."""
    step, box_w, box_h, per_row = 160, 136, 46, 6
    on_path = set(path)
    holding = {t: [b for b in adj.get(t, []) if b not in on_path and (comps[b].get("state") in BARRIER)]
               for t in path}
    rows = [path[i:i + per_row] for i in range(0, len(path), per_row)]
    band = [box_h + 30 + 30 * max((len(holding[t]) for t in r), default=0) for r in rows]
    w = step * min(len(path), per_row) + 20
    h = sum(band) + 20
    out = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="Evidence path">']
    for i, t in enumerate(path):
        row, col = divmod(i, per_row)
        x = 10 + col * step
        oy = sum(band[:row])
        c = comps.get(t, {})
        state = c.get("state") or "unknown"
        last = i == len(path) - 1
        stroke = "var(--unc)" if t in uncertain else ("var(--path)" if (i == 0 or last) else "var(--line)")
        dash = ' stroke-dasharray="5 3"' if t in uncertain else ""
        out.append(f'<rect x="{x}" y="{oy + 10}" width="{box_w}" height="{box_h}" rx="5" fill="var(--card)" '
                   f'stroke="{stroke}" stroke-width="2"{dash}/>')
        out.append(f'<text x="{x + 8}" y="{oy + 29}" font-weight="700">{_e(t)}</text>')
        changed = f" (was {_e(c['was'])})" if c.get("was") else ""
        out.append(f'<text class="sub" x="{x + 8}" y="{oy + 45}">{_e(c.get("kind", ""))} · {_e(state)}{changed}</text>')
        if not last and col < per_row - 1:
            ax = x + box_w
            out.append(f'<line x1="{ax + 2}" y1="{oy + 33}" x2="{ax + step - box_w - 4}" y2="{oy + 33}" '
                       f'stroke="var(--path)" stroke-width="2.5"/>'
                       f'<path d="M{ax + step - box_w - 4},{oy + 28} l6,5 l-6,5 z" fill="var(--path)"/>')
        elif not last:
            out.append(f'<text x="{x + box_w + 4}" y="{oy + 37}" fill="var(--path)">&#8629;</text>')
        for j, b in enumerate(holding[t]):
            by = oy + 10 + box_h + 14 + j * 30
            out.append(f'<line x1="{x + box_w / 2}" y1="{oy + 10 + box_h}" x2="{x + box_w / 2}" y2="{by}" '
                       f'stroke="var(--barrier)" stroke-dasharray="2 2"/>')
            out.append(f'<text x="{x + 8}" y="{by + 12}" fill="var(--barrier)">⊣ {_e(b)} '
                       f'{_e(comps[b].get("state"))}</text>')
    out.append("</svg>")
    return "".join(out)


def evaluation_html(e: dict) -> str:
    result, snap, req = e["result"], e["snapshot"], e["request"]
    comps = {c["tag"]: dict(c) for c in snap["components"]}
    changes = list(req.get("hypothetical", []))
    if req.get("type") == "change":
        changes += req.get("changes", [])
    elif req.get("type") == "permit" and isinstance(req.get("permit"), dict):
        changes += req["permit"].get("operates", [])
        changes += [{"tag": t, "to": "in_service"} for t in req["permit"].get("energises", [])]
    for ch in changes:
        c = comps.get(ch.get("tag"))
        if c and c.get("state") != ch.get("to"):
            c["was"], c["state"] = c.get("state") or "unknown", ch["to"]
    snap = dict(snap, components=list(comps.values()))
    adj: dict[str, list[str]] = {t: [] for t in comps}
    for a, b in snap["connections"]:
        adj[a].append(b)
        adj[b].append(a)
    verdict = result.get("conflict_verdict") or result.get("assessment_status")
    request = result.get("request", {})
    title = f"{request.get('id') or ''} {request.get('title') or ''}".strip()
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
             f"<title>Blind Flange {_e(e['id'])}</title><style>{CSS}</style></head><body><main>"]
    parts.append(f"<p class='meta'>Blind Flange evidence report · {_e(e['id'])} · recorded {_e(e['at'])} · "
                 f"store revision {_e(e['revision'])} · plant: {_e(snap['store'].get('plant'))}</p>")
    parts.append(f"<h1><span class='verdict {_e(verdict)}'>{_e(verdict)}</span> {_e(title)}</h1>")
    parts.append(f"<p class='meta'>assessment_status <b>{_e(result.get('assessment_status'))}</b> · "
                 f"conflict_verdict <b>{_e(result.get('conflict_verdict') or 'none')}</b> · "
                 f"assessed as of {_e(result.get('assessed_at'))} · search bound {_e(result.get('max_hops'))} hops"
                 + (" · what-if: " + _e(", ".join(f"{h['tag']}={h['to']}" for h in req.get('hypothetical', [])))
                    if req.get("hypothetical") else "") + "</p>")
    if result.get("error"):
        parts.append(f"<div class='card'><h3>Not assessed</h3><p>{_e(result['error'])}</p></div>")
    unc = {u["tag"] for u in result.get("unknowns", [])}
    findings = result.get("findings", [])
    parts.append(f"<h2>Findings ({len(findings)})</h2>")
    if not findings and not result.get("error"):
        parts.append("<p>No conflicts found." + ("" if result.get("assessment_status") == "COMPLETE"
                                                 else " The assessment is incomplete.") + "</p>")
    for i, f in enumerate(findings, 1):
        tags = [f["origin"]] + (["possible"] if f["certainty"] == "POSSIBLE" else [])
        parts.append(f"<div class='card'><h3>{i}. <span class='verdict {_e(f['severity'])}'>{_e(f['severity'])}</span> "
                     f"<span class='tag'>{_e(f['code'])}</span> <span class='note'>({_e(', '.join(tags))})</span></h3>"
                     f"<p>{_e(f['message'])}</p>")
        if f.get("permit"):
            parts.append(f"<p class='note'>Other permit: <span class='tag'>{_e(f['permit'])}</span> "
                         f"{_e(f.get('permit_title'))}</p>")
        if len(f.get("path", [])) > 1:
            parts.append(f"<p class='note'>Path, {len(f['path']) - 1} hops. Barriers holding beside the route "
                         f"are shown underneath; dashed boxes are unconfirmed.</p>"
                         f"<div class='scroll'>{_path_svg(f['path'], comps, adj, set(f.get('uncertain', [])))}</div>")
            others = [s for s in f.get("sources", []) if s != f["path"][0]]
            if others:
                parts.append(f"<p class='note'>Also reached from: {_e(', '.join(others))}</p>")
            if f.get("other_service_sources"):
                parts.append(f"<p class='note'>Not listed as sources: {_e(', '.join(f['other_service_sources']))} "
                             f"(other services, no declared tie-in; pressure levels are not modelled).</p>")
        for ev in f.get("evidence", []):
            parts.append(f"<p class='note'>Evidence: <span class='tag'>{_e(ev)}</span></p>")
        parts.append("</div>")
    if result.get("incomplete_reasons"):
        parts.append("<h2>Why the assessment is incomplete</h2><ul>"
                     + "".join(f"<li>{_e(r)}</li>" for r in result["incomplete_reasons"]) + "</ul>")
    if result.get("unknowns"):
        parts.append("<h2>Unconfirmed states</h2><table><tr><th>Tag</th><th>State</th><th>Reason</th>"
                     "<th>Observed</th><th>On a route that matters</th></tr>"
                     + "".join(f"<tr><td class='tag'>{_e(u['tag'])}</td><td>{_e(u['state'])}</td><td>{_e(u['reason'])}</td>"
                               f"<td>{_e(u.get('observed_at') or 'never')}</td><td>{'yes' if u.get('relevant') else 'no'}</td></tr>"
                               for u in result["unknowns"]) + "</table>")
    hz = result.get("hazards", {})
    if hz:
        parts.append("<h2>Hazards before and after</h2><table>")
        for k in ("existing", "introduced", "remaining", "resolved"):
            parts.append(f"<tr><th>{k}</th><td class='tag'>{'<br>'.join(_e(x) for x in hz.get(k, [])) or '-'}</td></tr>")
        parts.append("</table>")
    if request.get("type") == "permit":
        shared = result.get("baseline_shared_tags") or {}
        parts.append("<h2>Tag matching baseline</h2><p>"
                     + (_e("; ".join(f"{p}: {', '.join(t)}" for p, t in shared.items())) if shared
                        else "No shared tags with any active permit: tag matching alone would pass this request.")
                     + "</p>")
    parts.append("<h2>Plant</h2><p class='note'>Red: the evidence paths (dark red: where they start). "
                 "Blue: closed valves and installed blinds. Amber: unconfirmed state. "
                 "Squares are valves and blinds.</p>")
    parts.append(f"<div class='scroll'>{_plant_svg(snap, result)}</div>")
    parts.append("<p class='note'>Decision support only. Not a safety system. The plant data is illustrative. "
                 "Generated by <span class='tag'>blindflange report</span> from the recorded evaluation; "
                 "<span class='tag'>blindflange replay</span> re-runs it from the same snapshot.</p>")
    parts.append("</main></body></html>")
    return "".join(parts)
