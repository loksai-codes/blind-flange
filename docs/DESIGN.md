# DESIGN.md: "Redline" (Blind Flange)

An engineering drawing, marked up. The page is cream drafting paper with a faint
Prussian-blue grid; the plant is drawn in blue linework; the conflict is marked in red,
the way an engineer redlines a P&ID. Red appears only where something is wrong or where
the reader should act.

Replaces the earlier "Mended in Gold" palette (indigo, celadon, gold). The fonts stay.

---

## 1. Colour

| Token | Name | Hex | Role |
|---|---|---|---|
| `--cream` | Ricotta Cream | `#F0E8D8` | Page (60%) |
| `--blue` | Prussian Blue | `#1B3350` | Text, linework, blue bands (30%) |
| `--red` | Lobster Red | `#F03A2A` | Accent (10%): the conflict path, markup, large display words |

### Derived

| Token | Hex | Use | Contrast |
|---|---|---|---|
| `--cream-2` | `#E8DDC8` | Raised paper (proof section, selected tab) | |
| `--blue-2` | `#142840` | Deeper band: video frame, terminal, footer | |
| `--red-ink` | `#B8281B` | Red for small text, solid buttons, BLOCK badge | 5.1:1 on cream; cream on it 5.1:1 |
| `--red-on-blue` | `#FF6A5C` | Red text on blue bands | 4.6:1 on blue |
| `--ink-muted` | `#4A5D74` | Secondary text on cream | 5.5:1 |
| `--on-blue-muted` | `#B9BFC6` | Secondary text on blue | 6.9:1 |
| `--line` | `rgba(27,51,80,.18)` | Hairlines | |
| `--line-strong` | `#7A8696` | Borders of interactive controls | 3.0:1 |
| `--grid` / `--grid-major` | blue at 5.5% / 9% | Drafting grid, 24px minor, 96px major | |

### Rules
- Lobster Red `#F03A2A` is 3.2:1 on cream: use it only for graphics and text 24px and larger.
  Small red text uses `--red-ink`.
- Blue text on cream is 10.5:1; cream on blue is 10.5:1.
- Red marks the conflict, the primary action, and section rules. Never body text, never large fills.
- No glows on the cream page. Depth comes from offset hard shadows (`6px 6px 0`) like a drawing
  stamp, and from the blue bands.

---

## 2. Typography

- **Display:** `Instrument Serif`, uppercase, line-height 0.88 to 0.9, `-0.01em`.
  The emphasised word is italic, lower case, in red: "The conflict is a *path*".
- **Text and UI:** `Inter`, 16px body, labels 11px uppercase at `0.22em`, weight 500 to 600.
- **Drawing labels and code:** system mono (`ui-monospace`, Cascadia Mono, Consolas).

```css
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@400;500;600&display=swap');
```

---

## 3. Layout

- Five sections, about five screens on desktop: hero, demo (blue band), how it works,
  proof (raised paper), try it (blue band), footer (deep blue).
- Container 1200px; side padding 48 / 32 / 16px.
- Spacing on a 4px scale: 4, 8, 12, 16, 24, 32, 48, 64, 96, 128.
- Section heads: display title left, a small label right with a 2px red rule above it.

---

## 4. Components

- **Solid button:** `--red-ink` with cream text; hover turns it blue. On blue bands: `--red`
  with blue text; hover turns it cream.
- **Outline button:** `--line-strong` border, blue text; hover red.
- **Badges:** BLOCK solid `--red-ink`; HOLD red outline; CLEAR solid blue; INCOMPLETE dashed blue.
- **Redline circle:** a hand-drawn red loop around the item at fault (the blind in the hero).
- **Title block:** a mono, boxed strip like a drawing's title block (drawing, plant, result).
- **Focus:** 2px outline, blue on cream, cream on blue bands, 3px offset.

---

## 5. Motion

- On load: the red underline draws under the headline, the red path draws along the pipes,
  the red circle closes around the blind, the result card rises. One dot travels the path.
- Ease-out `cubic-bezier(.2,.7,.2,1)`. No bounce. Everything stops under
  `prefers-reduced-motion`.

---

## 6. Tokens

```css
:root {
  --cream: #F0E8D8; --cream-2: #E8DDC8;
  --blue: #1B3350; --blue-2: #142840;
  --red: #F03A2A; --red-ink: #B8281B; --red-on-blue: #FF6A5C;
  --ink: var(--blue); --ink-muted: #4A5D74;
  --line: rgba(27,51,80,.18); --line-strong: #7A8696;
  --on-blue: #F0E8D8; --on-blue-muted: #B9BFC6;
  --font-display: 'Instrument Serif', serif;
  --font-ui: 'Inter', system-ui, sans-serif;
  --font-mono: ui-monospace, 'Cascadia Mono', Consolas, monospace;
}
```

## 7. Do and don't
- Do keep red rare: if everything is marked, nothing is.
- Do label the plants as illustrative wherever a drawing appears.
- Don't use Lobster Red for small text on cream.
- Don't add gradients or glows to the cream page.
