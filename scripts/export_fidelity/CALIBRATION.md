# Text calibration: PowerPoint for Mac and Google Slides

Recorded 2026-11-17. Measured with `scripts/export_fidelity/calibrate_text.py` on the probe deck
`tests/fixtures/export_snapshot/text_calibration.html`, exported through the snapshot engine and
rendered in Microsoft PowerPoint for Mac (PDF, re-rasterised at 4x) and Google Slides (Drive
conversion, 1600 px thumbnails), against the browser at device scale 2. PowerPoint opens the deck
written for it (`build_pptx_huashu(..., target="pptx")`), Google Slides the one written for it
(`target="gslides"`), as the two exports do. All values are CSS px at 1280 px width, renderer
minus browser (+ is lower or wider in the renderer). A4 and A5 are measured from the text of each
app's PDF with `scripts/export_fidelity/measure_script_lines.py`.

The tests read the constants from this file: each sits on a line of its own, once, and
`services/pptx-emit-huashu/emit_text.cjs` and `emit_typography.cjs` define the same values
(`tests/unit/test_export_snapshot_line_spacing.py`).

## The constants

    FIRST_LINE_A = 0.8241
    FIRST_LINE_B = 1.4338
    FIRST_LINE_C = -1.5
    SUPERSCRIPT_SIZE_FACTOR = 0.646
    GOOGLE_LINE_GROWTH_PER_PX = 0.96

There is no subscript factor: both renderers shrink a subscript run exactly as they shrink a
superscript one (A2 below). `GOOGLE_LINE_GROWTH_PER_PX` is A4's.

## The rules these constants serve

**Single spacing is 1.2 x the font size.** PowerPoint and Google Slides draw 100%
line spacing at 1.2 x the font size, whatever the font's own metrics. DM Sans and DM Mono have
hhea, typo and win metrics of 1.302 to 1.322 em, and Arial and Georgia 1.09 to 1.15, and all four
measured at 1.2 em. The browser's `line-height: normal` is the font's metrics (83 px for DM Sans
at 64 px). Written as a percentage of that natural height, as first planned, every line came out
about 8% short: up to 8.5 px per line pair at 64 px in PowerPoint, 8.2 px in Google.

**Spacing encoding.** In a block the browser laid out on more than one line:

- a line height up to 1.2 x the paragraph's largest run is `<a:lnSpc><a:spcPct>` of
  `cssLineHeight / (1.2 x fontSize)` (90% for the corpus titles at 1.08), with the lines as soft
  breaks in one paragraph;
- a looser line height (including `line-height: normal` for DM Sans, 1.30 em) is single spacing,
  `spcPct` 100%, with every line its own paragraph, and the leading beyond single,
  `(cssLineHeight - 1.2 x fontSize) x 0.75` pt, as `<a:spcBef><a:spcPts>` on the lines after
  the first.

Above 100% the renderers disagree on where the first line goes: Google adds the extra leading
below a line, PowerPoint about 0.63 of it above. So no single box top serves both apps, and the
best brief model left 8.6 px. With single spacing and space before, they agree. Line spacing is
never points (`spcPts` inside `<a:lnSpc>`): Drive converts it to a percentage of the natural
height and mis-scales it (RC6). A one-line block has no `<a:lnSpc>` (upstream pitfall 6).

**First-line placement.** The snapshot's box top is the browser's first glyph top (the top of the
text's Range rects). The emitter raises it by

    offset = A x (pct/100 - 1) x 1.2 x sizePx + B x sizePx + C x ascentPx

- `pct` is the first paragraph's `spcPct`, at most 100. It is 100 for a single line and for a
  loose block.
- `sizePx` is its largest run's font size.
- `ascentPx` is that run's ascent in the browser, from glyph top to baseline. It is read in the
  page with a baseline probe and rounded as Chrome rounds it (63 px for DM Sans at 64 px, 38 for
  Arial at 42).

The ascent term is what makes the offset font-aware. Both renderers set a single-spaced first line
by its font size, while the browser sets it by the font's ascent. Without the term, DM Sans, Arial
and Georgia spread over 5.4 px at 42 px.

The constants are a minimax fit over both renderers (Lawson's algorithm in
`calibrate_text.py`; checked against an exact linear program). The minimax optimum is not unique:
every solution stops at about 1.66 px, which is where PowerPoint and Google disagree on the same
probes. Among those, these values have the lowest RMS of the ones checked (0.79 px). `C = -1`
(so a pure "renderer baseline at B x size") reaches the same maximum with an RMS of 0.80 to 0.88.

## Residuals with these constants (the verification run)

Google Slides: https://docs.google.com/presentation/d/1XS2dxYxfkzb0C9hEzaWOho8dwzPO4SZ1MJF1Pk6aGYw/edit

The acceptance probe set is DM Sans and DM Mono at 13, 16, 20, 32, 42 and 64 px, each at
line-heights `normal`, 1.08, 1.3, 1.45 and 1.6, on one line and on three. That is 120 probes. The
deck adds Arial and Georgia at 42 px, 20 more.

| renderer | probes | max ink-top error | max pitch error per line pair | max pitch error per probe (mean of its pairs) |
|---|---|---|---|---|
| PowerPoint | DM Sans + DM Mono (120) | 1.48 | 2.00 | 1.12 |
| PowerPoint | all four fonts (140) | 1.67 | 2.00 | 1.12 |
| Google Slides | DM Sans + DM Mono (120) | 1.59 | 0.75 | 0.25 |
| Google Slides | all four fonts (140) | 1.59 | 0.75 | 0.25 |

Acceptance is ink-top ≤ 2 px and pitch ≤ 1 px at 1280 px width:

- **Ink-top:** met on both renderers, every font.
- **Pitch:** met on Google Slides. PowerPoint is over the limit in some pairs, as explained next.

**PowerPoint's pitch residual is its own line granularity, not the space before.** Read straight
from the PDF PowerPoint saves, its baselines sit on a 0.24 pt (1/300 in) grid. Its spacing of two
identical consecutive lines differs by about 1 pt: for example 14.88 pt then 16.08 pt where 15.75 pt
was asked for, a mean within 0.4 px. The same per-pair spread appears whatever the encoding, on the
loose probes:

| encoding (loose probes, three lines) | PowerPoint per pair / per probe | Google per pair / per probe |
|---|---|---|
| spcPct of the natural line height (the first plan) | 8.50 / 7.87 | 8.20 / 7.70 |
| spcPct of 1.2 x size, above 100% (option B) | 1.75 / 0.62 | 0.72 / 0.28 |
| single spacing + spcBef (option C, shipped) | 2.00 / 1.12 | 0.66 / 0.20 |

The tight probes (`spcPct` below 100%, the same in options B and C) show PowerPoint's 1.75 px per
pair too. Option C costs PowerPoint about 0.5 px of per-probe pitch against option B. Option B
costs 8.6 px of first-line error. PowerPoint's worst probe means are:

- −1.12 px, 13 px at 1.45: −0.93 px against the CSS line height in PowerPoint's own PDF
  baselines; the rest is the browser's half-pixel snapping;
- +1.00 px, 32 and 42 px at 1.6.

Every other probe is within ±0.75 px.

### Every spacing probe

`ink-top` is the first line's ink-top error. `pitch` lists each line pair's error, with the mean in
brackets.

| probe | encoding | spcPct | spcBef pt | PowerPoint ink-top | PowerPoint pitch (mean) | Google ink-top | Google pitch (mean) |
|---|---|---|---|---|---|---|---|
| DM Sans 600 64px lh normal x3 | space-before | 100.0 | 4.65 | -1.23 | +0.75, -0.25 (+0.25) | +1.52 | -0.06, -0.07 (-0.07) |
| DM Sans 600 64px lh 1.08 x3 | percent | 90.0 | - | -1.48 | +0.00, +0.50 (+0.25) | +1.59 | +0.23, +0.04 (+0.13) |
| DM Sans 600 64px lh 1.3 x3 | space-before | 100.0 | 4.8 | -1.23 | +0.75, -0.25 (+0.25) | +1.52 | +0.20, +0.20 (+0.20) |
| DM Sans 600 64px lh 1.45 x3 | space-before | 100.0 | 12 | -1.48 | +0.50, -1.00 (-0.25) | +1.52 | -0.20, -0.20 (-0.20) |
| DM Sans 600 64px lh 1.6 x3 | space-before | 100.0 | 19.2 | -1.23 | +0.75, -2.00 (-0.62) | +1.46 | +0.40, -0.60 (-0.10) |
| DM Sans 600 64px lh normal x1 | single | - | - | -1.23 | - | +1.52 | - |
| DM Sans 600 64px lh 1.08 x1 | single | - | - | -1.23 | - | +1.46 | - |
| DM Sans 600 64px lh 1.3 x1 | single | - | - | -1.23 | - | +1.52 | - |
| DM Sans 600 64px lh 1.45 x1 | single | - | - | -1.48 | - | +1.52 | - |
| DM Sans 600 64px lh 1.6 x1 | single | - | - | -1.23 | - | +1.46 | - |
| DM Mono 400 64px lh normal x3 | space-before | 100.0 | 4.65 | -1.23 | +0.75, -0.25 (+0.25) | +1.52 | -0.06, -0.07 (-0.07) |
| DM Mono 400 64px lh 1.08 x3 | percent | 90.0 | - | -1.48 | +0.00, +0.50 (+0.25) | +1.59 | +0.23, +0.04 (+0.13) |
| DM Mono 400 64px lh 1.3 x3 | space-before | 100.0 | 4.8 | -1.23 | +0.75, -0.25 (+0.25) | +1.52 | +0.20, +0.20 (+0.20) |
| DM Mono 400 64px lh 1.45 x3 | space-before | 100.0 | 12 | -1.48 | +0.50, -1.00 (-0.25) | +1.52 | -0.20, -0.20 (-0.20) |
| DM Mono 400 64px lh 1.6 x3 | space-before | 100.0 | 19.2 | -1.23 | +0.75, -2.00 (-0.62) | +1.46 | +0.40, -0.60 (-0.10) |
| DM Mono 400 64px lh normal x1 | single | - | - | -1.23 | - | +1.52 | - |
| DM Mono 400 64px lh 1.08 x1 | single | - | - | -1.23 | - | +1.46 | - |
| DM Mono 400 64px lh 1.3 x1 | single | - | - | -1.23 | - | +1.52 | - |
| DM Mono 400 64px lh 1.45 x1 | single | - | - | -1.48 | - | +1.52 | - |
| DM Mono 400 64px lh 1.6 x1 | single | - | - | -1.23 | - | +1.46 | - |
| DM Sans 600 42px lh normal x3 | space-before | 100.0 | 3.45 | -0.06 | -0.25, -0.25 (-0.25) | +1.39 | +0.02, -0.12 (-0.05) |
| DM Sans 600 42px lh 1.08 x3 | percent | 90.0 | - | +0.19 | +0.50, -0.50 (+0.00) | +1.51 | +0.34, -0.75 (-0.20) |
| DM Sans 600 42px lh 1.3 x3 | space-before | 100.0 | 3.15 | -0.06 | -0.25, +0.75 (+0.25) | +1.41 | -0.42, +0.51 (+0.05) |
| DM Sans 600 42px lh 1.45 x3 | space-before | 100.0 | 7.88 | +0.19 | +0.25, +0.25 (+0.25) | +1.29 | -0.04, -0.04 (-0.04) |
| DM Sans 600 42px lh 1.6 x3 | space-before | 100.0 | 12.6 | +0.19 | +1.00, +1.00 (+1.00) | +1.29 | +0.20, +0.20 (+0.20) |
| DM Mono 400 42px lh normal x3 | space-before | 100.0 | 3.45 | -0.06 | -0.25, -0.25 (-0.25) | +1.39 | +0.02, -0.12 (-0.05) |
| DM Mono 400 42px lh 1.08 x3 | percent | 90.0 | - | +0.19 | +0.50, -0.50 (+0.00) | +1.51 | +0.34, -0.75 (-0.20) |
| DM Mono 400 42px lh 1.3 x3 | space-before | 100.0 | 3.15 | -0.06 | -0.25, +0.75 (+0.25) | +1.41 | -0.42, +0.51 (+0.05) |
| DM Mono 400 42px lh 1.45 x3 | space-before | 100.0 | 7.88 | +0.19 | +0.25, +0.25 (+0.25) | +1.29 | -0.04, -0.04 (-0.04) |
| DM Mono 400 42px lh 1.6 x3 | space-before | 100.0 | 12.6 | +0.19 | +1.00, +1.00 (+1.00) | +1.29 | +0.20, +0.20 (+0.20) |
| DM Sans 600 42px lh normal x1 | single | - | - | -0.06 | - | +1.39 | - |
| DM Sans 600 42px lh 1.08 x1 | single | - | - | +0.19 | - | +1.41 | - |
| DM Sans 600 42px lh 1.3 x1 | single | - | - | -0.06 | - | +1.41 | - |
| DM Sans 600 42px lh 1.45 x1 | single | - | - | +0.19 | - | +1.29 | - |
| DM Sans 600 42px lh 1.6 x1 | single | - | - | +0.19 | - | +1.29 | - |
| DM Mono 400 42px lh normal x1 | single | - | - | -0.06 | - | +1.39 | - |
| DM Mono 400 42px lh 1.08 x1 | single | - | - | +0.19 | - | +1.41 | - |
| DM Mono 400 42px lh 1.3 x1 | single | - | - | -0.06 | - | +1.41 | - |
| DM Mono 400 42px lh 1.45 x1 | single | - | - | +0.19 | - | +1.29 | - |
| DM Mono 400 42px lh 1.6 x1 | single | - | - | +0.19 | - | +1.29 | - |
| Arial 400 42px lh normal x3 | percent | 95.2 | - | -0.92 | +0.00, +0.00 (+0.00) | -0.45 | -0.00, +0.00 (-0.00) |
| Arial 400 42px lh 1.08 x3 | percent | 90.0 | - | -1.67 | +0.50, -0.75 (-0.12) | -0.41 | +0.25, -0.51 (-0.13) |
| Arial 400 42px lh 1.3 x3 | space-before | 100.0 | 3.15 | -0.42 | -0.25, -0.50 (-0.38) | -0.67 | -0.33, +0.66 (+0.17) |
| Arial 400 42px lh 1.45 x3 | space-before | 100.0 | 7.88 | -0.17 | +0.00, -0.75 (-0.37) | -0.61 | -0.14, -0.02 (-0.08) |
| Arial 400 42px lh 1.6 x3 | space-before | 100.0 | 12.6 | -0.42 | +1.25, -0.50 (+0.38) | -0.61 | +0.20, +0.20 (+0.20) |
| Georgia 400 42px lh normal x3 | percent | 95.2 | - | -0.72 | -0.00, -0.00 (-0.00) | +0.10 | -0.10, +0.00 (-0.05) |
| Georgia 400 42px lh 1.08 x3 | percent | 90.0 | - | -0.97 | -0.00, -0.50 (-0.25) | -0.04 | +0.47, -0.64 (-0.09) |
| Georgia 400 42px lh 1.3 x3 | space-before | 100.0 | 3.15 | +0.03 | -0.25, -0.75 (-0.50) | -0.13 | -0.28, +0.58 (+0.15) |
| Georgia 400 42px lh 1.45 x3 | space-before | 100.0 | 7.88 | +0.03 | +0.50, -1.25 (-0.37) | -0.11 | -0.12, -0.09 (-0.11) |
| Georgia 400 42px lh 1.6 x3 | space-before | 100.0 | 12.6 | +0.28 | +0.75, -0.50 (+0.13) | -0.03 | +0.20, +0.20 (+0.20) |
| Arial 400 42px lh normal x1 | single | - | - | -0.42 | - | -0.61 | - |
| Arial 400 42px lh 1.08 x1 | single | - | - | -0.17 | - | -0.67 | - |
| Arial 400 42px lh 1.3 x1 | single | - | - | -0.42 | - | -0.67 | - |
| Arial 400 42px lh 1.45 x1 | single | - | - | -0.17 | - | -0.61 | - |
| Arial 400 42px lh 1.6 x1 | single | - | - | -0.42 | - | -0.61 | - |
| Georgia 400 42px lh normal x1 | single | - | - | +0.28 | - | -0.01 | - |
| Georgia 400 42px lh 1.08 x1 | single | - | - | +0.03 | - | -0.11 | - |
| Georgia 400 42px lh 1.3 x1 | single | - | - | +0.03 | - | -0.13 | - |
| Georgia 400 42px lh 1.45 x1 | single | - | - | +0.03 | - | -0.11 | - |
| Georgia 400 42px lh 1.6 x1 | single | - | - | +0.28 | - | -0.03 | - |
| DM Sans 600 32px lh normal x3 | space-before | 100.0 | 2.7 | -0.27 | +0.50, +0.75 (+0.63) | +1.11 | -0.13, +0.13 (+0.00) |
| DM Sans 600 32px lh 1.08 x3 | percent | 90.0 | - | -1.02 | -0.50, +0.75 (+0.12) | +1.19 | -0.49, +0.48 (-0.00) |
| DM Sans 600 32px lh 1.3 x3 | space-before | 100.0 | 2.4 | -0.27 | -0.50, +0.25 (-0.12) | +1.05 | -0.40, +0.60 (+0.10) |
| DM Sans 600 32px lh 1.45 x3 | space-before | 100.0 | 6 | -0.27 | +0.75, -0.25 (+0.25) | +0.98 | +0.40, -0.60 (-0.10) |
| DM Sans 600 32px lh 1.6 x3 | space-before | 100.0 | 9.6 | -0.27 | +1.00, +1.00 (+1.00) | +1.11 | +0.20, +0.20 (+0.20) |
| DM Mono 400 32px lh normal x3 | space-before | 100.0 | 2.7 | -0.27 | +0.50, +0.75 (+0.63) | +1.11 | -0.13, +0.13 (+0.00) |
| DM Mono 400 32px lh 1.08 x3 | percent | 90.0 | - | -1.02 | -0.50, +0.75 (+0.12) | +1.19 | -0.49, +0.48 (-0.00) |
| DM Mono 400 32px lh 1.3 x3 | space-before | 100.0 | 2.4 | -0.27 | -0.50, +0.25 (-0.12) | +1.05 | -0.40, +0.60 (+0.10) |
| DM Mono 400 32px lh 1.45 x3 | space-before | 100.0 | 6 | -0.27 | +0.75, -0.25 (+0.25) | +0.98 | +0.40, -0.60 (-0.10) |
| DM Mono 400 32px lh 1.6 x3 | space-before | 100.0 | 9.6 | -0.27 | +1.00, +1.00 (+1.00) | +1.11 | +0.20, +0.20 (+0.20) |
| DM Sans 600 32px lh normal x1 | single | - | - | -0.27 | - | +1.11 | - |
| DM Sans 600 32px lh 1.08 x1 | single | - | - | -0.27 | - | +1.11 | - |
| DM Sans 600 32px lh 1.3 x1 | single | - | - | -0.27 | - | +1.05 | - |
| DM Sans 600 32px lh 1.45 x1 | single | - | - | -0.27 | - | +0.98 | - |
| DM Sans 600 32px lh 1.6 x1 | single | - | - | -0.27 | - | +1.11 | - |
| DM Mono 400 32px lh normal x1 | single | - | - | -0.27 | - | +1.11 | - |
| DM Mono 400 32px lh 1.08 x1 | single | - | - | -0.27 | - | +1.11 | - |
| DM Mono 400 32px lh 1.3 x1 | single | - | - | -0.27 | - | +1.05 | - |
| DM Mono 400 32px lh 1.45 x1 | single | - | - | -0.27 | - | +0.98 | - |
| DM Mono 400 32px lh 1.6 x1 | single | - | - | -0.27 | - | +1.11 | - |
| DM Sans 400 20px lh normal x3 | space-before | 100.0 | 1.5 | +0.18 | +0.75, +0.50 (+0.62) | +0.63 | +0.10, -0.10 (+0.00) |
| DM Sans 400 20px lh 1.08 x3 | percent | 90.0 | - | -0.57 | -0.50, +1.75 (+0.62) | +0.85 | -0.40, +0.60 (+0.10) |
| DM Sans 400 20px lh 1.3 x3 | space-before | 100.0 | 1.5 | +0.18 | +0.75, +0.50 (+0.62) | +0.63 | +0.10, -0.10 (+0.00) |
| DM Sans 400 20px lh 1.45 x3 | space-before | 100.0 | 3.75 | +0.18 | +0.25, +0.50 (+0.38) | +0.75 | -0.02, -0.09 (-0.05) |
| DM Sans 400 20px lh 1.6 x3 | space-before | 100.0 | 6 | +0.18 | +0.00, +0.00 (+0.00) | +0.64 | +0.00, +0.00 (+0.00) |
| DM Mono 400 20px lh normal x3 | space-before | 100.0 | 1.5 | +0.18 | +0.75, +0.50 (+0.62) | +0.63 | +0.10, -0.10 (+0.00) |
| DM Mono 400 20px lh 1.08 x3 | percent | 90.0 | - | -0.57 | -0.50, +1.75 (+0.62) | +0.85 | -0.40, +0.60 (+0.10) |
| DM Mono 400 20px lh 1.3 x3 | space-before | 100.0 | 1.5 | +0.18 | +0.75, +0.50 (+0.62) | +0.63 | +0.10, -0.10 (+0.00) |
| DM Mono 400 20px lh 1.45 x3 | space-before | 100.0 | 3.75 | +0.18 | +0.25, +0.50 (+0.38) | +0.75 | -0.02, -0.09 (-0.05) |
| DM Mono 400 20px lh 1.6 x3 | space-before | 100.0 | 6 | +0.18 | +0.00, +0.00 (+0.00) | +0.64 | +0.00, +0.00 (+0.00) |
| DM Sans 400 20px lh normal x1 | single | - | - | +0.18 | - | +0.73 | - |
| DM Sans 400 20px lh 1.08 x1 | single | - | - | +0.18 | - | +0.64 | - |
| DM Sans 400 20px lh 1.3 x1 | single | - | - | +0.18 | - | +0.73 | - |
| DM Sans 400 20px lh 1.45 x1 | single | - | - | -0.07 | - | +0.64 | - |
| DM Sans 400 20px lh 1.6 x1 | single | - | - | +0.18 | - | +0.75 | - |
| DM Mono 400 20px lh normal x1 | single | - | - | +0.18 | - | +0.73 | - |
| DM Mono 400 20px lh 1.08 x1 | single | - | - | +0.18 | - | +0.64 | - |
| DM Mono 400 20px lh 1.3 x1 | single | - | - | +0.18 | - | +0.73 | - |
| DM Mono 400 20px lh 1.45 x1 | single | - | - | -0.07 | - | +0.64 | - |
| DM Mono 400 20px lh 1.6 x1 | single | - | - | +0.18 | - | +0.75 | - |
| DM Sans 400 16px lh normal x3 | space-before | 100.0 | 1.35 | -0.05 | -1.25, +0.50 (-0.38) | +0.62 | -0.07, +0.07 (+0.00) |
| DM Sans 400 16px lh 1.08 x3 | percent | 90.0 | - | -0.05 | +0.75, -0.75 (+0.00) | +0.78 | +0.09, -0.59 (-0.25) |
| DM Sans 400 16px lh 1.3 x3 | space-before | 100.0 | 1.2 | -0.05 | -1.00, +0.25 (-0.38) | +0.68 | -0.20, -0.20 (-0.20) |
| DM Sans 400 16px lh 1.45 x3 | space-before | 100.0 | 3 | -0.05 | -0.25, +1.00 (+0.38) | +0.55 | +0.20, +0.20 (+0.20) |
| DM Sans 400 16px lh 1.6 x3 | space-before | 100.0 | 4.8 | -0.05 | -0.75, +1.75 (+0.50) | +0.62 | -0.40, +0.60 (+0.10) |
| DM Mono 400 16px lh normal x3 | space-before | 100.0 | 1.35 | -0.05 | -1.25, +0.50 (-0.38) | +0.62 | -0.07, +0.07 (+0.00) |
| DM Mono 400 16px lh 1.08 x3 | percent | 90.0 | - | -0.05 | +0.75, -0.75 (+0.00) | +0.78 | +0.09, -0.59 (-0.25) |
| DM Mono 400 16px lh 1.3 x3 | space-before | 100.0 | 1.2 | -0.05 | -1.00, +0.25 (-0.38) | +0.68 | -0.20, -0.20 (-0.20) |
| DM Mono 400 16px lh 1.45 x3 | space-before | 100.0 | 3 | -0.05 | -0.25, +1.00 (+0.38) | +0.55 | +0.20, +0.20 (+0.20) |
| DM Mono 400 16px lh 1.6 x3 | space-before | 100.0 | 4.8 | -0.05 | -0.75, +1.75 (+0.50) | +0.62 | -0.40, +0.60 (+0.10) |
| DM Sans 400 16px lh normal x1 | single | - | - | -0.05 | - | +0.55 | - |
| DM Sans 400 16px lh 1.08 x1 | single | - | - | -0.05 | - | +0.68 | - |
| DM Sans 400 16px lh 1.3 x1 | single | - | - | -0.05 | - | +0.62 | - |
| DM Sans 400 16px lh 1.45 x1 | single | - | - | -0.05 | - | +0.62 | - |
| DM Sans 400 16px lh 1.6 x1 | single | - | - | -0.05 | - | +0.68 | - |
| DM Mono 400 16px lh normal x1 | single | - | - | -0.05 | - | +0.55 | - |
| DM Mono 400 16px lh 1.08 x1 | single | - | - | -0.05 | - | +0.68 | - |
| DM Mono 400 16px lh 1.3 x1 | single | - | - | -0.05 | - | +0.62 | - |
| DM Mono 400 16px lh 1.45 x1 | single | - | - | -0.05 | - | +0.62 | - |
| DM Mono 400 16px lh 1.6 x1 | single | - | - | -0.05 | - | +0.68 | - |
| DM Sans 400 13px lh normal x3 | space-before | 100.0 | 1.05 | -0.09 | +0.25, -1.00 (-0.38) | +0.35 | +0.07, +0.06 (+0.07) |
| DM Sans 400 13px lh 1.08 x3 | percent | 90.0 | - | -0.34 | -0.50, +0.75 (+0.12) | +0.56 | -0.10, +0.16 (+0.03) |
| DM Sans 400 13px lh 1.3 x3 | space-before | 100.0 | 0.97 | -0.09 | +0.25, -1.00 (-0.38) | +0.42 | -0.14, -0.12 (-0.13) |
| DM Sans 400 13px lh 1.45 x3 | space-before | 100.0 | 2.44 | -0.09 | -0.50, -1.75 (-1.12) | +0.35 | +0.01, -0.14 (-0.07) |
| DM Sans 400 13px lh 1.6 x3 | space-before | 100.0 | 3.9 | -0.09 | +0.00, -0.75 (-0.38) | +0.42 | -0.20, -0.20 (-0.20) |
| DM Mono 400 13px lh normal x3 | space-before | 100.0 | 1.05 | -0.09 | +0.25, -1.00 (-0.38) | +0.35 | +0.07, +0.06 (+0.07) |
| DM Mono 400 13px lh 1.08 x3 | percent | 90.0 | - | -0.34 | -0.50, +0.75 (+0.12) | +0.56 | -0.10, +0.16 (+0.03) |
| DM Mono 400 13px lh 1.3 x3 | space-before | 100.0 | 0.97 | -0.09 | +0.25, -1.00 (-0.38) | +0.42 | -0.14, -0.12 (-0.13) |
| DM Mono 400 13px lh 1.45 x3 | space-before | 100.0 | 2.44 | -0.09 | -0.50, -1.75 (-1.12) | +0.35 | +0.01, -0.14 (-0.07) |
| DM Mono 400 13px lh 1.6 x3 | space-before | 100.0 | 3.9 | -0.09 | +0.00, -0.75 (-0.38) | +0.42 | -0.20, -0.20 (-0.20) |
| DM Sans 400 13px lh normal x1 | single | - | - | -0.09 | - | +0.42 | - |
| DM Sans 400 13px lh 1.08 x1 | single | - | - | -0.09 | - | +0.42 | - |
| DM Sans 400 13px lh 1.3 x1 | single | - | - | -0.09 | - | +0.35 | - |
| DM Sans 400 13px lh 1.45 x1 | single | - | - | -0.09 | - | +0.42 | - |
| DM Sans 400 13px lh 1.6 x1 | single | - | - | -0.09 | - | +0.48 | - |
| DM Mono 400 13px lh normal x1 | single | - | - | -0.09 | - | +0.42 | - |
| DM Mono 400 13px lh 1.08 x1 | single | - | - | -0.09 | - | +0.42 | - |
| DM Mono 400 13px lh 1.3 x1 | single | - | - | -0.09 | - | +0.35 | - |
| DM Mono 400 13px lh 1.45 x1 | single | - | - | -0.09 | - | +0.42 | - |
| DM Mono 400 13px lh 1.6 x1 | single | - | - | -0.09 | - | +0.48 | - |

## A1: optical-size width compensation

The browser draws DM Sans (Google Fonts, `opsz` 9..40) at the automatic optical size. PowerPoint
and Google Slides draw the static opsz-14 cut, about 9% wider at title sizes. A run whose width at
`'opsz' 14` (a probe with its own letter-spacing) differs from the browser's by more than 0.5% gets
`spc = letterSpacing x 0.75 + (browserWidth - exportCutWidth) / n x 0.75` pt.

Ink width per line, browser -> renderer:

| probe | spc | PowerPoint | Google Slides |
|---|---|---|---|
| cover title, 64 px 600 (2 lines) | -267, -238 | 614.8 -> 613.8 (-0.16%); 651.6 -> 656.6 (+0.78%) | 613.9 (-0.14%); 650.9 (-0.10%) |
| "FY2024 delivered…", 42 px 600 | -165 | 1029.6 -> 1037.4 (+0.75%) | 1028.4 (-0.11%) |
| "Three drivers…", 42 px 600 | -170 | 736.5 -> 739.5 (+0.41%) | 736.0 (-0.08%) |
| 13 px body, 0.02em (no delta) | 20 | 298.6 -> 300.9 (+0.75%) | 298.3 (-0.11%) |
| 13 px eyebrow, 0.16em (no delta) | 156 | 216.6 -> 216.5 (-0.05%) | 216.1 (-0.26%) |

No title wraps in either app, and every line count matches the browser. Google is within 0.26%.
PowerPoint draws runs that carry `spc` up to 0.78% wider. That is consistent with the `kern="0"`
pptxgenjs writes beside every `spc`: PowerPoint stops kerning, Google keeps it. The box's 6% slack
absorbs it. The deck for PowerPoint now tracks the kerning in, with no band (X1 below); the deck
for Google Slides keeps this rule.

## A2: superscript and subscript size

`script / plain` ink height at the same browser size, over the browser's own ratio. With factor 1
the renderers drew:

| | 64 px PowerPoint | 64 px Google | 20 px PowerPoint | 20 px Google |
|---|---|---|---|---|
| superscript | 0.6759 | 0.6659 | 0.6161 | 0.6613 |
| subscript | 0.6759 | 0.6659 | 0.6161 | 0.6613 |

The factor, 0.646, is the minimax of these, ±4.6%. The emitter writes a script run
at the browser's size over it. With it applied, the rendered size over the browser's is:

| | 64 px PowerPoint | 64 px Google | 20 px PowerPoint | 20 px Google |
|---|---|---|---|---|
| super and sub | 1.025 | 1.029 | 1.000 | 1.016 |

**The Google column is the deck written for Google Slides** (`target="gslides"`, which
`calibrate_text.py` converts, as the Google Slides export does). Each probe here is a line of
script runs alone (`<sup>HH</sup>`), which that target does not cap, so the column is Google's own
shrink, the same in either deck. On a line with other text the target caps a script run at its
line's size, plus the browser's growth of the line over `GOOGLE_LINE_GROWTH_PER_PX` (A4),
because Google sizes the whole line by the run's written size. Google then sets
the line on the browser's baseline (+0.52 px at 20 px, +1.05 px at 40 px) and draws the script
glyph at **0.800** of the browser's size on a line the browser did not grow. Placement wins over
glyph size there: an accepted Google Slides trade-off.

## A3: render checks

- **Repair prompt: none.** PowerPoint opened, saved as PDF and closed every calibration deck with
  no dialog, in 5 to 10 s, five runs in all. That is although pptxgenjs writes an `<a:pPr>` before
  every run of a paragraph (up to 6 in one), which the schema does not allow. The repeats are
  identical (pinned by a test), so a reader that honours any of them gets the paragraph's spacing.
- **Unbordered shapes: no outline** in either app. `<a:ln></a:ln>`, with no fill and no width,
  draws nothing: at the box's edge the darkest luminance equals the fill (228). The bordered
  control is detected (0). The fill-less `<a:ln>` is kept (pinned by a test).
- **Justified text stretches** in both apps. Both justify every line but the last to the whole
  box, its 6% + 4 px slack included: PowerPoint by +35.0 px on a 520 px paragraph, Google by +29.5
  to +34.3 px. Justified text is therefore written left-aligned (right-aligned when right-to-left)
  with the browser's line breaks (pinned by a test). The lines then end where the browser's
  natural lines end (ragged right): 6.6 to 37.0 px short of the justified edge, and the last line
  within 1.7 px.

## A4: Google Slides' line growth per px of script excess

Google Slides sizes a line by every run on it. A script run written larger than the line's other
runs lowers the whole line, by `GOOGLE_LINE_GROWTH_PER_PX` px per px of the excess. The deck
written for Google caps a script run at its line's size plus the browser's own growth of that
line over this constant, so Google grows the line as the browser did
(`services/pptx-emit-huashu/emit_text.cjs` `scriptCapPx`).

**Method** (`measure_script_lines.py --gslides`, recorded 2026-11-19). "Revenue<sup>1</sup> grew"
on one line in DM Sans at 20 px and at 40 px is exported for both targets and converted through
Drive. The baselines are read from the text origins in Drive's PDF of each conversion. The deck
for PowerPoint writes the "1" at the browser's size over `SUPERSCRIPT_SIZE_FACTOR`, the deck for
Google at the line's size. So the excess is the difference of the two written sizes, and the
line's drop is the difference of the two baselines:

| line | excess written (px) | Google lowers the line (px) | per px |
|---|---|---|---|
| 20 px | 5.80 | 5.57 | 0.960 |
| 40 px | 11.60 | 11.14 | 0.960 |

The first measurement, on 2026-11-18, read 5.57 and 11.13 px. The value is DM Sans's: another
face's ascent ratio moves it by a few percent, a fraction of a px per line. With it, the deck for
Google places a superscript's later line −0.56 px from the browser's (20 px, line-height 29 px).

**Space before, where the cap writes no growth.** Google sets a paragraph's first
line by the paragraph's spacing, and the cap keeps a script run on it at the line's own size, so
its excess grows nothing there. A line with no script run has no cap at all. Both take the
browser's growth of the line as space before instead, as the deck for PowerPoint does
(`emit_text.cjs` `growthBeforePx`); only a line within its paragraph that holds a script run is
grown by the cap. Space before moves the line one px per px, as measured (2026-11-19): a later
paragraph's first line holding a superscript, its growth written at 1:1 and over the constant
(an XML edit of the same deck):

| later paragraph's first line (20 px block) | growth written | line's baseline |
|---|---|---|
| line-height 29 px, 24 px "Gamma" and a superscript | none (before) | −4.69 |
| the same | 1:1 | **−0.04** |
| the same | over 0.96 | +0.16 |
| line-height 1.45, 24 px "Gamma" and a superscript | 1:1 / over 0.96 | **−0.04** / +0.07 |
| line-height 29 px, 24 px line 1, then a superscript | 1:1 / over 0.96 | **+1.19** / +1.55 |

And lines with no script run, written without their growth and with it (`measure_script_lines.py`
probes `plain-*`, a 16 px paragraph; offsets of each line after the first):

| paragraph | without | with |
|---|---|---|
| line-height 1.4, a 28 px run on line 2 | −11.60, −16.35 | −2.62, +0.43 |
| line-height 1.6, a 20 px run on line 2 | −3.13, −5.97, −5.97 | +0.87, +0.43, +0.43 |
| line-height 26 px, a 20 px run on line 2 | −0.14, −1.58, −1.58 | −0.14, +0.42, +0.42 |

So a line with no script run takes its growth alike in both decks (the decks still differ in
tracking, italics and U+2011: X1, D1 and D8 below). A 28 px line opening a paragraph whose
spacing is tighter than single (66.7%) still sits 2.6 px high, in PowerPoint 3.6 px: that is
the two apps' spacing between paragraphs of different sizes, which no growth changes.

## A5: script lines in PowerPoint

PowerPoint places a line holding a script run by its other runs, with two
exceptions:

- it grows the line by the script run's enlarged size (the browser's over
  `SUPERSCRIPT_SIZE_FACTOR`) when that run ends the line, and only then. So the deck for
  PowerPoint writes a run after it in the line's own size and style holding a word joiner
  (U+2060). A space works as well vertically, but PowerPoint counts a trailing space in a
  right-aligned or centred line, which moved it left by the space's advance (5.33 px and 2.66 px
  at 20 px); the word joiner has none;
- it spaces a later line by its paragraph's spacing alone. So a later line whose box the browser
  grew (a superscript with a line height of its own raises it) opens a paragraph of its own, its
  growth added to its space before.

Baseline offsets in PowerPoint of the deck for PowerPoint (`measure_script_lines.py
--powerpoint`, 2026-11-19), against the engine before these two rules. The first nine are its
PowerPoint cases; all are DM Sans at 20 px unless named:

| case | before: line 1 | before: line 2 | now: line 1 | now: line 2 |
|---|---|---|---|---|
| one line, superscript inside it (the A4 case) | +0.06 | - | +0.06 | - |
| one line, superscript at its end | +5.18 | - | +0.06 | - |
| one line at 40 px, superscript at its end | +10.67 | - | +0.11 | - |
| one line, subscript at its end | +5.36 | - | -0.08 | - |
| line-height 29 px, superscript ends line 1 | +5.38 | +7.10 | -0.06 | +0.38 |
| line-height 22 px, superscript ends line 1 | +4.22 | +6.22 | -0.90 | -0.50 |
| line-height 22 px, superscript ends line 2 | -0.96 | -1.78 | -0.96 | -0.50 |
| line-height 29 px, superscript ends line 2 | -0.12 | -0.90 | -0.12 | +0.38 |
| line-height 29 px, superscript inside line 2 | -0.12 | -6.34 | -0.12 | +0.38 |
| line-height 22 px, superscript inside line 2 | -0.96 | -6.90 | -0.96 | -0.50 |
| line-height 29 px, 24 px "Gamma" and a superscript on line 2 | -0.12 | -6.34 | -0.12 | -2.18 |
| the same without the superscript | -0.12 | -1.68 | -0.12 | -1.68 |
| line-height 29 px, plain (control) | -0.12 | +0.32 | -0.12 | +0.32 |

The tight first line's −0.9 px is the first-line offset's residual at 22 / 24 = 91.7% spacing.
A paragraph's first line in a 24 px run sits 1.68 px high whether or not the line holds a
superscript: that is PowerPoint's spacing between paragraphs of different sizes, which these
rules do not change. A right-aligned and a centred line ending in a superscript keep their
place (−2.85 px and −1.42 px, as before).

The growth rule covers lines with no script run too: a larger run's own unitless line height,
or the block's strut beside a larger line, puts a later line lower than its spacing. The
probes (16 px paragraphs; each line after the first; before = the engine before the
growth rule):

| paragraph | before | now |
|---|---|---|
| line-height 1.4, a 28 px run on line 2 | −12.91, −17.98 | −3.63, −0.38 |
| line-height 1.6, a 20 px run on line 2 | −4.35, −7.35, −6.07 | −0.19, −0.63, +0.65 |
| line-height 26 px, a 20 px run on line 2 | −1.76, −3.76, −2.88 | −1.76, −0.88, −0.32 |

**Nudges.** A same-size `position: relative` move is no script: the run
stays plain, and since no run carries a move, it stands on its line's baseline. Whether a box
settles or moves is the box's: where every word of the whole box shares one move, the box is
placed where it is moved; in any other box each nudged word settles on its line's baseline (a
line all of it moved is then drawn off by its own move, and no line after it moves). Growth and
spacing are always read from the settled lines, so a move is never growth. A "…" shares the
move of the words of its line (20 px, line-height 29 px for three lines):

| case | as a script | every nudge settled | settled or moved per line | per box (the engine) |
|---|---|---|---|---|
| "Revenue ▲ 12% up", the ▲ up 3 px | +0.12 | +0.12 | +0.12 | +0.12 |
| the whole line up 3 px | +1.20 | +3.12 | −0.08 | −0.08 |
| the whole line down 4 px | +21.20 | −4.08 | +0.08 | +0.08 |
| a line cut by its "…", moved down 4 px | – | −4.08 | −4.08 | +0.08 |
| the same moved up 3 px | – | +2.92 | +0.04 | +0.04 |
| three lines, line 2 down 4 px | – | −0.12, −3.68, +0.76 | −0.12, +0.48, +4.60 | −0.12, −3.68, +0.76 |
| three lines, line 1 down 4 px | – | −4.12, +0.32, +0.76 | +0.04, +4.48, +4.60 | −4.12, +0.32, +0.76 |
| three lines, line 2 up 3 px | – | −0.12, +3.32, +0.76 | −0.12, +3.32, +3.32 | −0.12, +3.32, +0.76 |
| three lines in one span, down 4 px | – | −4.12, −3.68, −3.24 | +0.04, +0.48, +0.60 | +0.04, +0.48, +0.60 |

## X1: kerning in PowerPoint

Measured 2026-11-21 (Task 14 B1). PowerPoint for Mac draws DM Sans with no pair kerning: a probe
deck of `AVAVAVAV To Ty Yo Wa LT` at 30 pt measured 508.28 px with `kern` absent, `kern="0"` and
`kern="1200"` alike. It kerns Arial and Times New Roman (legacy `kern` tables) unless the run
says `kern="0"`: Arial 478.09 px absent, 515.80 with `kern="0"`, 478.09 with `kern="1200"`
(Times 466.20, 523.09, 466.20). pptxgenjs writes `kern="0"` beside every `spc`, so a run the deck
tracks is unkerned in PowerPoint whatever its face. PowerPoint puts a run's `spc` after each of
its characters, the last included: a run of ten H at `spc` 10 pt moves the run after it by ten
times 13.38 px.

So the deck for PowerPoint writes each run's tracking as its CSS letter-spacing plus
`unkernedTrackingPx`: the optical-size delta per character, (browser width − export cut) / n
with no dead band, plus the run's kerning, (export cut − export cut with `font-kerning: none`)
/ gaps, where gaps is n − 1 for a run that ends its line (its last character's tracking moves
nothing) and n for a run another follows on its line (its last character's tracking places the
next run where the browser does; the browser kerns no pair across two runs). The two divide
differently because one is advance and the other is ink: the optical-size delta is a difference
of every glyph's advance at two optical sizes, the last glyph's included, so spread over all n
characters it puts each glyph where the browser has it, with only the last glyph's ink ending its
share wide; kerning lies between characters alone, so it is spread over the gaps it closes. A
review A/B with n − 1 for both made fixture 01's PowerPoint score 0.64 worse. Both cuts are
probes in the page (`snapshot_text_metrics.mjs`). The deck for Google Slides, which kerns, keeps
A1.

**Measured on both corpora** (`run.py --pin-fonts --powerpoint`; every matched line of each
slide's PowerPoint PDF against the browser's, upright lines; px at 1280 wide, PowerPoint minus
browser; the browser's width less the letter space its last character's Range rect holds, which
a PDF glyph box does not):

| corpus | engine | median | median of \|error\| | largest \|error\| |
|---|---|---|---|---|
| in-repo (306 lines) | before (A1, kerning untracked) | +0.56 | 0.60 | 15.99 |
| in-repo | X1 with A1's 0.5% band kept | +0.19 | 0.27 | 4.32 |
| in-repo | X1, no band | +0.16 | 0.23 | 2.73 |
| in-repo | the shipped engine (X1, D1 and D8) | +0.16 | 0.23 | 2.73 |
| design system (392 lines) | before | +0.76 | 0.79 | 11.14 |
| design system | X1 with the band kept | +0.15 | 0.30 | 3.32 |
| design system | X1, no band | +0.15 | 0.30 | 3.32 |
| design system | the shipped engine (X1, D1 and D8) | +0.16 | 0.30 | 3.34 |

The two X1 rows of each corpus are one A/B, before D8. The shipped engine also writes → in
Arial (D8), which lengthens the design-system deck's lines that hold one. The band changes
nothing on the design-system deck, whose DM Sans has no optical-size axis, and dropping it
helps the in-repo deck's, so the deck for PowerPoint has none. The tracked 64 px
event title (`letter-spacing: .18em`) went from +11.14 to −1.12 px.

## D1: italic faces

Measured 2026-11-21 (Task 14 B1) with a probe deck written by pptxgenjs, one line per naming,
24 pt, rendered in PowerPoint for Mac (PDF) and converted through Drive (PDF export). The face is
the font each line's spans embed in the app's PDF; the width is the line's, less its code, in
px at 1280 wide.

The static DM Sans installed for PowerPoint names each italic but Bold Italic a family of its
own, with no italic bit: name ID 1 is "DM Sans Italic", "DM Sans Medium Italic", "DM Sans
SemiBold Italic" (subfamily Regular); only DMSans-BoldItalic is a member of "DM Sans" itself.

| typeface written | PowerPoint | Google Slides |
|---|---|---|
| `DM Sans` + italic | DMSans-BoldItalic, 717.88 | DMSans-Italic, 674.08 |
| `DM Sans Italic`, italic off | DMSans-Italic, 675.65 | Sansita-Italic, 572.35 |
| `DM Sans Italic` + italic | DMSans-Italic, 675.65 | Sansita-Italic, 572.35 |
| `DM Sans Medium` + italic | DMSans-Medium (upright), 699.26 | DMSans-MediumItalic, 686.66 |
| `DM Sans Medium Italic`, italic off | DMSans-MediumItalic, 689.01 | DMSans-MediumItalic, 686.66 |
| `DM Sans SemiBold Italic`, italic off | DMSans-SemiBoldItalic, 705.36 | DMSans-SemiBoldItalic, 703.04 |
| `DM Sans` + bold + italic | DMSans-BoldItalic, 717.88 | DMSans-BoldItalic, 714.94 |
| `DM Sans` (upright control) | DMSans-Regular, 671.38 | DMSans-Regular, 667.87 |
| `DM Sans Light Italic` (not installed) | DMSans-Light (upright), 664.34 | DMSans-LightItalic, 664.32 |

**Both static conventions.** Not every family's statics name italics so. DM Mono's are RIBBI
members of their family (DMMono-Italic: name ID 1 "DM Mono", subfamily Italic, the italic bit
set; full name "DM Mono Italic"), as most families' are. PowerPoint resolves the italic static's
name through the face's full name and style as well as name ID 1, so the one naming is right for
both (a second probe deck, 24 pt; pixel comparisons at 4x):

| typeface written | PowerPoint |
|---|---|
| `DM Mono` + italic | DMMono-Italic, 766.75 |
| `DM Mono Italic`, italic off | DMMono-Italic, 766.75, pixel-identical to the line above |
| `DM Mono Italic` + italic | DMMono-Italic, 766.75, pixel-identical |
| `DM Mono Medium` + italic (no Medium Italic installed) | DMMono-Medium (upright), 780.91 |
| `DM Sans Italic`, italic off | DMSans-Italic, 594.06 |
| `DM Sans Italic` + italic | DMSans-Italic, 594.06, slanted a second time (80,808 pixels differ) |

So the deck for PowerPoint writes an italic run of a loaded webfont as its italic static's
name, the weight's face plus "Italic", with italic off, and 700 as the family plus bold and
italic (its Bold Italic in either convention); the deck for Google Slides keeps the family plus
italic (`emit_typography.cjs` italicTypefaceFor). The webfonts themselves cannot tell the two
conventions apart: Google serves every italic webfont as a RIBBI member (`DM Sans 9pt`, Italic).
PowerPoint for Windows could not be probed here: whether it resolves the italic static's name for
a RIBBI family (by the full name, "<family> [weight ]Italic" in both conventions) as PowerPoint
for Mac does is unmeasured, an owner check.

**A variable install.** Google's variable DM Sans (`DMSans[opsz,wght].ttf` and its italic),
renamed `TellrProbeVar` so it could not meet the installed statics, installed for the probe and
removed after it, PowerPoint restarted: PowerPoint for Mac shows each file's default instance
alone, under its legacy name ID 1 (`TellrProbeVar 9pt`, so "DM Sans 9pt" for the real font).
`… 9pt` + italic is the italic file's default instance; `… 9pt Italic` falls back to the upright;
no other named instance (`… Medium`, `… Medium Italic`, the PostScript names) resolves, and the
bare family name is Calibri. With a variable install the deck's family itself does not resolve,
upright text included, so it cannot decide the italic naming; the statics' naming is the one
PowerPoint draws as the plain italic.

## D8: characters a webfont lacks

Measured 2026-11-21 (Task 14 B1).

**The browser.** Chrome on a Mac (CDP `CSS.getPlatformFontsForNode`, 100 px; advance and ink
box in em) draws what the deck's DM Sans lacks from faces the machine picks:

| character | after DM Sans | after DM Mono |
|---|---|---|
| ▲ U+25B2 | Hiragino Sans, advance 1.000, ink 0.90 × 0.79 | Menlo, 0.602, ink 0.60 |
| ▼ U+25BC | Lucida Grande, 0.980, ink 0.82 × 0.82 | Menlo, 0.602 |
| → U+2192 | Lucida Grande, 1.000, ink 0.78 × 0.42 | Menlo, 0.602 |
| ‑ U+2011, ‐ U+2010 | DM Sans's own hyphen-minus, 0.541 (as `-`) | DM Mono's, 0.600 |

The latin webfonts the decks load lack U+2010, U+2011, ▲, ▼ and → (→ is in the installed DM
Sans statics but outside Google's latin `unicode-range`). Linux Chromium picks other faces, or
none: what the browser itself falls back to is no choice for the export.

**The apps** (the probe deck of D1, PDF fonts and advances at 24 pt):

| written | PowerPoint | Google Slides |
|---|---|---|
| ▲▼ in DM Sans | Times New Roman, 0.99 | Arial, 0.99 |
| → in DM Sans | DM Sans (the static's), 0.78 | DM Sans, 0.78 |
| ▲▼→ in Arial | Arial, 0.99 / 1.00 | Arial, 0.99 / 1.00 |
| ▲▼→ in Times New Roman | Times New Roman, 0.99 / 1.00 | Times New Roman, 0.99 / 1.00 |
| ▲▼→ in Courier New | Courier New, 0.600 | Courier New, 0.600 |
| ▲▼ in DM Mono | Courier New, 0.600 | Courier New, 0.600 |
| "end‑to‑end" (U+2011), 48 px | DM Sans, 269.20 px | MS PGothic hyphens, 246.06 |
| "end‐to‐end" (U+2010) | Cambria Math hyphens, 249.20 | MS PGothic hyphens, 264.43 |
| "end-to-end" (U+002D) | DM Sans, 269.19 | DM Sans, 268.42 |
| U+2011 in Arial / Times New Roman | Arial's hyphen | MS PGothic / MS PMincho |

**The choice.** Of the faces PowerPoint for Windows and Mac and Google Slides all have, Arial,
Times New Roman and Courier New cover all of WGL4, in Office's copies, macOS's copies and in
Google; Verdana, Georgia, Trebuchet MS and Calibri lack ▲▼→. Arial and Times New Roman draw
▲▼→ alike (0.99 and 1.00 em), the browser's advance within 2% after DM Sans, where Courier
New's is 40% short; after DM Mono the browser's ▲ is 0.602 em and Courier New's cell 0.600,
where Arial's is 64% wide. So a character a loaded webfont lacks that WGL4 holds (ASCII aside)
is a run of its own in the face of the run's generic family: Courier New for monospace, Times
New Roman for serif, Arial otherwise (`snapshot_text.mjs` fallbackFaceOf). The ink of Arial's
▲ is 0.69 em against Hiragino's 0.90, the nearest the three apps share. Which characters a face
lacks is read from the face itself: each candidate is probed in the run's face with a font
whose every code point is one 4 em glyph after it (`coverage_font.mjs`), so a probe reaching
4 em is a character the face lacks, on any machine. A family the page did not load is the
viewer's own font and is not read.

The hyphens are drawn by the face itself in the browser, so they stay in their run, and are
written as each app draws them right: U+2010 as U+002D in both decks (PowerPoint draws it from
Cambria Math), U+2011 as U+002D in the deck for Google Slides alone (PowerPoint draws it as
the face's hyphen, and it keeps its no-break meaning there). U+2010 in place of U+2011 would not
do: Google draws it from MS PGothic too.

## Runs behind this record

| run | engine state | Google Slides presentation |
|---|---|---|
| 1 | spcPct of the natural height, constants 0, factor 1 | https://docs.google.com/presentation/d/12WlmWH9GqYiH6InYpCxWAK9AFYHSG1z9M7e38ek9C0w/edit |
| 2 | spcPct of 1.2 x size throughout (option B's encoding), constants 0 | https://docs.google.com/presentation/d/1gO5lNFvmgb-dhHEBEx8YpVr06GQmiHokH3FN92FSP2Y/edit |
| 3 | option C, constants 0, factor 0.646 (the fit) | https://docs.google.com/presentation/d/12miGQiWr6npw4PFPbGnoLrb876WTyDIZz9MAryOjpG0/edit |
| 4 | option C, the constants above (verification) | https://docs.google.com/presentation/d/1XS2dxYxfkzb0C9hEzaWOho8dwzPO4SZ1MJF1Pk6aGYw/edit |

A4 and A5 (2026-11-19) were measured on presentations the script deletes by id once read.
D1, X1 and D8 (2026-11-21) were measured on probe decks rendered in PowerPoint and converted
through Drive, whose presentation was deleted by id once read, and on the two corpora
(`docs/superpowers/plans/2026-11-16-export-fidelity-progress.md`, B1).

To re-run (PowerPoint will briefly open a window):

    uv run --with pymupdf --with pillow python scripts/export_fidelity/calibrate_text.py --out /tmp/calib
    uv run --with pymupdf python scripts/export_fidelity/measure_script_lines.py \
        --out /tmp/script-lines --powerpoint --gslides
