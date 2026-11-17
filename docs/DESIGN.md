# DESIGN.md — "Mended in Gold" (Naosu)

Kintsugi-inspired landing page: a dark, cool indigo page with a warm gold accent and a soft celadon (pale jade) for type.
Rule from the source: **warm page → cool accent, cool page → warm accent.** This page is cool (indigo), so the accent is warm (gold).

---

## 1. Colour palette (exact)

| Token | Name | Hex | RGB | Role |
|---|---|---|---|---|
| `--indigo` | Indigo | `#0B1325` | 11, 19, 37 | Page background, base surface |
| `--celadon` | Celadon | `#A9CDBE` | 169, 205, 190 | Headline type, ceramic, secondary text |
| `--gold` | Gold | `#F2B53A` | 242, 181, 58 | Accent: gold seams, glows, highlights, hover |

These hex codes are the ones printed on the source swatches. Pixel sampling of the screenshot agrees with them within video-compression error (`#0B1326`, `#A5D0BD`).

### Supporting tints (derived)

| Token | Hex | Use |
|---|---|---|
| `--indigo-900` | `#070D1A` | Deepest shadow, vignette edges |
| `--indigo-800` | `#0B1325` | = base |
| `--indigo-700` | `#141E36` | Raised surfaces, cards |
| `--line` | `rgba(169, 205, 190, 0.35)` | Hairlines, pill-button border |
| `--text-muted` | `rgba(169, 205, 190, 0.65)` | Nav links, footer meta |
| `--gold-glow` | `rgba(242, 181, 58, 0.45)` | Glows and light bloom around the gold seams |

### Proportion
- ~80% Indigo (background)
- ~15% Celadon (type and ceramic)
- ~5% Gold (accent only. Never use it for body text or large fills.)

---

## 2. Typography

The swatch card names the colours but not the fonts, so the fonts below are the closest matches I could identify by eye. Confirm them with a font-ID tool such as WhatTheFont if you need the original typeface.

### Display / Headline: "MENDED IN GOLD"
- **Font:** `Instrument Serif` (Google Fonts). Fallbacks: `Bodoni Moda`, `Playfair Display`, serif
- Style: condensed, high-contrast, sharp serifs, ALL CAPS
- Weight: 400
- Size: `clamp(4rem, 9vw, 8.5rem)`
- Line-height: `0.88` (lines nearly touch)
- Letter-spacing: `-0.01em`
- Colour: `--celadon`, with thin gold "crack" lines and drips over the letters (texture or SVG overlay)

### Logo: "NAOSU"
- **Font:** `Inter` (or any geometric sans), weight 500
- Uppercase, letter-spacing `0.45em`, size `14px`, colour `--celadon`

### Nav / UI labels: REPAIRS · GALLERY · VISIT
- **Font:** `Inter`, weight 500
- Size `10–11px`, uppercase, letter-spacing `0.28em`
- Colour: `--text-muted`; on hover, `--gold`

### Meta line: "URUSHI LACQUER · 24K GOLD · 6 TO 8 WEEKS"
- **Font:** `Inter`, weight 500, size `10px`, uppercase, letter-spacing `0.22em`
- Colour `--text-muted`, separated by a centred dot ` · `

```css
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter:wght@400;500;600&display=swap');
```

---

## 3. Layout (desktop, 16:9 hero)

```
┌──────────────────────────────────────────────────────────────┐
│ NAOSU                REPAIRS  GALLERY  VISIT  (SEND US YOUR BREAK →) │
│                                                              │
│  MENDED                         [ shattered celadon bowl,     │
│  IN GOLD                          gold seams, floating ]      │
│                                                              │
│                                  [ dark stone plinth ]        │
│ URUSHI LACQUER · 24K GOLD · 6 TO 8 WEEKS                     │
└──────────────────────────────────────────────────────────────┘
```
- Container padding: `48px` sides, `32px` top
- Nav: logo on the left, links and CTA on the right, gap `48px`
- Headline: left column, vertically centred, about 45% of the width
- Hero image: right column, bowl breaking apart above a rough dark stone plinth
- Meta line: bottom-left, `32px` from the bottom edge

---

## 4. Components

### CTA pill: "SEND US YOUR BREAK →"
```css
.cta {
  font: 500 10px/1 'Inter', sans-serif;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--celadon);
  padding: 8px 16px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  transition: all .25s ease;
}
.cta:hover { border-color: var(--gold); color: var(--gold); }
```

---

## 5. Imagery and effects
- **Lighting:** a single warm light source; gold seams glow and drip, with tiny floating gold particles (embers)
- **Background:** Indigo with a subtle dark grunge or plaster texture and a warm bloom behind the object
- **Ceramic:** matte celadon glaze, cracked into large shards, with every seam filled in gold
- **Base:** rough, near-black volcanic stone

```css
.hero { background:
  radial-gradient(60% 60% at 70% 55%, rgba(242,181,58,.18), transparent 70%),
  var(--indigo); }
.gold-glow { filter: drop-shadow(0 0 12px var(--gold-glow)); }
```

---

## 6. CSS tokens

```css
:root {
  --indigo: #0B1325;
  --celadon: #A9CDBE;
  --gold: #F2B53A;

  --indigo-900: #070D1A;
  --indigo-700: #141E36;
  --line: rgba(169,205,190,.35);
  --text-muted: rgba(169,205,190,.65);
  --gold-glow: rgba(242,181,58,.45);

  --font-display: 'Instrument Serif', 'Bodoni Moda', 'Playfair Display', serif;
  --font-ui: 'Inter', system-ui, sans-serif;
}
body { background: var(--indigo); color: var(--celadon); font-family: var(--font-ui); }
h1   { font-family: var(--font-display); text-transform: uppercase; line-height: .88; }
```

## 7. Tailwind (optional)
```js
colors: { indigo: '#0B1325', celadon: '#A9CDBE', gold: '#F2B53A' },
fontFamily: { display: ['Instrument Serif','serif'], ui: ['Inter','sans-serif'] }
```
