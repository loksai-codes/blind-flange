"""Render the README demo: real styled output, as an animated terminal window in one SVG file.

Runs each command below against a scratch copy of a committed store, with --color always, and
draws the output exactly as printed: the command types itself out, the result appears line by
line, then the next command. Standard library only. Development tool; nothing imports it.

Run:  python scripts/demo_svg.py            (writes docs/media/demo.svg)
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "media" / "demo.svg"
COLS = 100

SCENES = [  # (store, command shown after "python -m blindflange", hold seconds)
    ("gas_plant", "check data/permits/PTW-2201.yaml --store gas.rl", 7.0),
    ("gas_plant", "whatif --set BV-231=closed --permit data/permits/PTW-2201.yaml --store gas.rl", 4.5),
]

# Catppuccin Mocha, close to a modern dark terminal.
BG, FG, CHROME = "#1e1e2e", "#cdd6f4", "#313244"
FGC = {30: "#1e1e2e", 31: "#f38ba8", 32: "#a6e3a1", 33: "#f9e2af", 34: "#89b4fa", 35: "#cba6f7", 36: "#89dceb",
       90: "#7f849c", 97: "#ffffff"}
BGC = {41: "#e64553", 42: "#40a02b", 43: "#df8e1d", 44: "#1e66f5", 45: "#8839ef"}

FONT = 14.0
CW = FONT * 0.6          # monospace advance
LH = FONT * 1.42
PADX, TOP, BOTTOM = 22.0, 52.0, 22.0
TYPE_CPS = 38            # characters per second when typing
LINE_S = 0.035           # seconds between output lines
GAP = 0.6


def run(store_name: str, command: str, workdir: Path) -> str:
    rl = workdir / command.split("--store ")[1].split()[0]
    shutil.copy(ROOT / "stores" / f"{store_name}.rl", rl)
    args = [str(rl) if a == rl.name else a for a in command.split()]
    env = {**os.environ, "COLUMNS": str(COLS), "PYTHONIOENCODING": "utf-8"}
    env.pop("NO_COLOR", None)
    p = subprocess.run([sys.executable, "-m", "blindflange", *args, "--color", "always"], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    if not p.stdout.strip():
        raise SystemExit(f"no output from {command!r}: {p.stderr.strip()}")
    text = p.stdout.replace(str(rl), rl.name)
    rl.unlink()
    return text.rstrip("\n")


def segments(line: str):
    """[(text, style)] for one line of ANSI output."""
    out, st = [], {}
    for part in re.split(r"(\x1b\[[0-9;]*m)", line):
        m = re.fullmatch(r"\x1b\[([0-9;]*)m", part)
        if m:
            for c in [int(x) for x in m.group(1).split(";") if x] or [0]:
                if c == 0:
                    st = {}
                elif c == 1:
                    st["bold"] = True
                elif c == 2:
                    st["dim"] = True
                elif c in FGC:
                    st["fg"] = FGC[c]
                elif c in BGC:
                    st["bg"] = BGC[c]
        elif part:
            out.append((part, dict(st)))
    return out


def text_line(line: str, y: float) -> str:
    """One output line. Every run of text is placed at its column and fitted to its width, so
    glyphs from a fallback font cannot push the rest of the line out of alignment."""
    bgs, spans, col = [], [], 0
    for txt, s in segments(line):
        n = len(txt)
        x = PADX + col * CW
        if s.get("bg"):
            bgs.append(f'<rect x="{x:.1f}" y="{y - FONT + 1:.1f}" width="{n * CW:.1f}" height="{LH:.1f}" '
                       f'rx="3" fill="{s["bg"]}"/>')
        if txt.strip():
            attrs = [f'x="{x:.1f}"', f'textLength="{n * CW:.1f}"', 'lengthAdjust="spacingAndGlyphs"']
            if s.get("fg"):
                attrs.append(f'fill="{s["fg"]}"')
            if s.get("bold"):
                attrs.append('font-weight="700"')
            if s.get("dim"):
                attrs.append('fill-opacity="0.62"')
            spans.append(f'<tspan {" ".join(attrs)}>{html.escape(txt)}</tspan>')
        col += n
    return "".join(bgs) + (f'<text y="{y:.1f}" xml:space="preserve">{"".join(spans)}</text>' if spans else "")


def build(still: int | None = None) -> str:
    """The animated demo, or with still=N one scene drawn complete with no animation."""
    scenes = SCENES if still is None else [SCENES[still]]
    with tempfile.TemporaryDirectory() as tmp:
        outputs = [run(s, c, Path(tmp)) for s, c, _ in scenes]
    rows = max(len(o.splitlines()) for o in outputs) + 2
    width = PADX * 2 + COLS * CW
    height = TOP + rows * LH + BOTTOM

    # Timeline: each scene types its command, prints line by line, holds, then clears.
    t, plan = 0.4, []
    for (_, cmd, hold), out in zip(scenes, outputs):
        shown = f"python -m blindflange {cmd}"
        t_type = len(shown) / TYPE_CPS
        lines = out.splitlines()
        start, typed = t, t + t_type
        printed = typed + 0.35
        end = printed + len(lines) * LINE_S + hold
        plan.append((shown, lines, start, typed, printed, end))
        t = end + GAP
    total = t

    css, body, k = [], [], 0

    def pct(sec):
        return f"{100 * sec / total:.3f}%"

    def visible(a, b):
        nonlocal k
        if still is not None:
            return "on"
        k += 1
        name = f"v{k}"
        e = 0.02
        css.append(f"@keyframes {name}{{0%,{pct(max(a - e, 0))}{{opacity:0}}{pct(a)},{pct(b)}{{opacity:1}}"
                   f"{pct(b + e)},100%{{opacity:0}}}}.{name}{{opacity:0;animation:{name} {total:.2f}s infinite}}")
        return name

    for shown, lines, start, typed, printed, end in plan:
        y0 = TOP + FONT
        scene = visible(start, end)
        prompt = (f'<text y="{y0:.1f}" xml:space="preserve"><tspan x="{PADX:.1f}" fill="#a6e3a1" font-weight="700">$</tspan>'
                  f'<tspan x="{PADX + 2 * CW:.1f}" textLength="{len(shown) * CW:.1f}" '
                  f'lengthAdjust="spacingAndGlyphs">{html.escape(shown)}</tspan></text>')
        # A cover slides right in steps, uncovering one character at a time.
        k_cover = f"c{k}"
        n = len(shown)
        css.append(f"@keyframes {k_cover}{{0%,{pct(start)}{{transform:translateX(0)}}"
                   f"{pct(typed)},100%{{transform:translateX({n * CW:.1f}px)}}}}"
                   f".{k_cover}{{animation:{k_cover} {total:.2f}s steps({n}) infinite}}")
        if still is not None:
            k_cover = "gone"
        cover = (f'<rect class="{k_cover}" x="{PADX + 2 * CW:.1f}" y="{y0 - FONT:.1f}" width="{n * CW + 4:.1f}" '
                 f'height="{LH:.1f}" fill="{BG}"/>')
        out_lines = []
        for i, line in enumerate(lines):
            y = y0 + (i + 2) * LH
            drawn = text_line(line, y)
            if drawn:
                out_lines.append(f'<g class="{visible(printed + i * LINE_S, end)}">{drawn}</g>')
        body.append(f'<g class="{scene}">{prompt}{cover}{"".join(out_lines)}</g>')

    dots = "".join(f'<circle cx="{22 + 20 * i}" cy="20" r="6" fill="{c}"/>'
                   for i, c in enumerate(("#f38ba8", "#f9e2af", "#a6e3a1")))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" role="img" aria-label="Blind Flange in a terminal: restarting train B is BLOCK, with the 12-hop path through the open bypass BV-231; closing BV-231 makes it CLEAR.">
<title>Blind Flange terminal demo</title>
<style>
text{{font-family:'Cascadia Mono','JetBrains Mono','SF Mono',Menlo,Consolas,'DejaVu Sans Mono','Liberation Mono',monospace;font-size:{FONT}px;fill:{FG}}}
{"".join(css)}
</style>
<rect width="100%" height="100%" rx="12" fill="{BG}"/>
<rect width="100%" height="40" rx="12" fill="{CHROME}"/><rect y="28" width="100%" height="12" fill="{CHROME}"/>
{dots}
<text x="{width / 2:.0f}" y="25" text-anchor="middle" fill="#a6adc8" font-size="13">blindflange: permit conflict check</text>
{"".join(body)}
</svg>
"""


if __name__ == "__main__":
    # --still N writes one scene, complete and not animated, to demo-N.svg (for checking and stills).
    still = int(sys.argv[sys.argv.index("--still") + 1]) if "--still" in sys.argv else None
    svg = build(still)
    if still is not None:
        svg = svg.replace("</style>", ".gone{display:none}</style>")
    out = OUT if still is None else OUT.with_name(f"demo-{still}.svg")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(ROOT)} ({len(svg) // 1024} KB)")
