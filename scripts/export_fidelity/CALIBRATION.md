# Text calibration: PowerPoint for Mac and Google Slides

Recorded 2026-11-17. Measured with `scripts/export_fidelity/calibrate_text.py` on the probe deck
`tests/fixtures/export_snapshot/text_calibration.html`, exported through the snapshot engine and
rendered in Microsoft PowerPoint for Mac (PDF, re-rasterised at 4x) and Google Slides (Drive
conversion, 1600 px thumbnails), against the browser at device scale 2. PowerPoint opens the deck
written for it (`build_pptx_huashu(..., target="pptx")`), Google Slides the one written for it
(`target="gslides"`), as the two exports do. All values are CSS px at 1280 px width, renderer
minus browser (+ is lower or wider in the renderer). A4 and A5 are measured from the text of each
app's PDF with `scripts/export_fidelity/measure_script_lines.py`. D4, D5 and D6 at the end
record probes of shapes, shadows and dashes, made the same way.

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
tracking, italics, the browser's synthetic bold and U+2011, in dotted borders and in native
tables: X1, D1, D12, D8, D6, D7 and D13 below). A 28 px line opening a paragraph whose
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

### D8, extended: symbols outside WGL4 (Task 15 B8, 2026-11-22)

A run written in Arial, Times New Roman or Courier New (N4, below) has the apps' copies of those
faces, whose coverage is WGL4 and little more: the face the container drew may cover more (Liberation
2.1.5 has ◔◑◕), but the apps draw the face written. Probe decks of the 983 symbols outside WGL4
(categories Sm, So, Sk, Sc and No, U+2000 to U+2BFF) that Office for Mac's MS PGothic and MS Gothic
both hold, each written in five faces, rendered in PowerPoint for Mac and converted through Drive,
every glyph's face and advance read from the two PDFs:

| written | PowerPoint for Mac | Google Slides |
|---|---|---|
| MS PGothic | MS PGothic, all 983 | MS PGothic, all 983 (⅒ U+2152 drawn as a box, 1.0 em against 0.918) |
| MS Gothic | MS Gothic, all 983 | MS Gothic, all 983 (⅒ as a box) |
| Arial | Cambria Math 401, Segoe UI Symbol 337, MS Gothic 157, Apple Color Emoji 60, Arial 26 | MS PGothic 951, Arial 20, Noto Color Emoji 12 |
| Times New Roman | Cambria Math 370, Segoe UI Symbol 329, MS Mincho 157, Times New Roman 67, Apple Color Emoji 60 | MS PMincho 952, Times New Roman 19, Noto Color Emoji 12 |
| Courier New | Cambria Math 409, Segoe UI Symbol 337, MS Mincho 157, Apple Color Emoji 60, Courier New 18 | MS Gothic 970, Noto Color Emoji 12, Courier New 1 |

Of the other 982, MS PGothic's advance agrees between the apps within 0.005 em on every one, and the
glyphs match on the contact sheets. Arial draws 19 of them itself in both apps (currency signs
U+20A0–U+20B1, ℗, ⅓, ⅔, ◌, ♯), Times New Roman the same less ℗, Courier New none. On the Harvey
quarters (`probe-symbols`): written in Arial or Times New Roman, PowerPoint draws ◔◑◕ from Segoe UI
Symbol at 0.861 em beside ○● at 0.604 em, Google from MS PGothic or MS PMincho at 0.50 em; in MS
PGothic both apps draw all of them alike (○● 1.0 em, the quarters 0.5 em, its own design). The UI
itself draws them from two faces on a Mac (○● in Times New Roman, ◔◑◕ in Menlo), and Apps'
Chromium in Liberation, all at about 0.60 em.

**The choice.** MS PGothic (MS Gothic in a monospace run) is the one face PowerPoint and Google
both draw these characters in, glyph for glyph, so each is a run of its own in it wherever the run's
written face lacks it: for Arial, Times New Roman and Courier New, every one but the few that face
draws itself (`TABLE_FACE_SYMBOLS`); for a webfont, the ones the coverage probe says it lacks, a
symbol its fallback face draws itself going to that face. The set is `SYMBOL_COVERAGE` in
`snapshot_text_metrics.mjs` (982 code points, 94 ranges). Windows was not probed: on non-Japanese
Windows MS Gothic and MS PGothic come with the optional Japanese Supplemental Fonts, and without
them PowerPoint falls back per glyph, as it does for these characters in any other face. A
character outside both sets (a letter of a script Liberation lacks, CJK, emoji) stays in its run.

## N3: the faces of the export's container (Task 15 B8, 2026-11-22)

Measured on a throwaway app on the dev workspace running the sidecar's own `setup.sh`, tarballs and
Playwright Chromium 147 (headless shell), against Chrome 158 on the Mac, each element's text width
from its Range and its faces from `CSS.getPlatformFontsForNode`.

**The base image** has DejaVu Sans, Sans Mono and Serif (regular and bold, no italics) and Debian's
fontconfig. Every stack with no webfont drew DejaVu: Helvetica, Arial and the DS-off stack at 1.14
to 1.20 of the Mac's width, Times New Roman and fontless text at 1.24 to 1.34 (drawn in DejaVu
Sans, the last resort, because Chromium refuses DejaVu Serif for "Times New Roman"), Courier New
0.90 to 1.01.

**The bundle** (Liberation 2.1.5 and `scripts/sidecar_fonts/fonts.conf.in`). Over 12 sizes (11 to
56 px), weights 400, 600 and 700 and both styles, every stack named after a core font, the DS-off
stack, `sans-serif`, `serif` and fontless text lays out at 1.0000 of the Mac's width; Menlo against
Liberation Mono 0.9968; `system-ui` (SF on the Mac) a median of 1.0056, 0.92 to 1.09 at the
extremes of SF's optical sizes. How the config was settled:
- `<dir prefix="relative">` is not read by fontconfig 2.13.1: `setup.sh` writes the absolute path;
- each alias puts the Liberation face first in the request (`prepend`), since Chromium (Skia)
  accepts a match only when its family equals the first family requested, the name asked for, or
  a metric-compatible twin of it (its own list holds Arial, Times New Roman and Courier New, not
  Helvetica, Times or Courier);
- the base image's fonts stay listed (without them ✓★◆ were drawn as boxes), but a request naming
  DejaVu is renamed to a family nothing has and matched to Liberation Sans, which Chromium refuses
  for it, so `"DejaVu Sans", Arial` draws Arial's face as on a Mac; appending Liberation Sans to
  every request instead made `Arimo` resolve too, which no desktop does;
- including the base image's `/etc/fonts/fonts.conf` instead of the self-contained config resolves
  every stack alike, except that Arimo and Tinos resolve through its metric aliases;
- launch time with the bundle: 65 to 98 ms, as without.

**Hinting.** Headless Chromium on Linux hints glyph outlines fully, which rounds advances: DM Sans,
DM Mono and Barlow lines (330 lines, sizes 12 to 42 px, weights 400 to 700) were 0.952 to 1.079 of
the Mac's width (median 1.0075). With `--font-render-hinting=none` they are 0.9996 to 1.0004. The
flag changes no width on the Mac, nor for the Liberation faces.

**CJK and emoji** have no face in the container, before or after: 数据湖仓平台, データレイクハウス and
🚀✅📈 are drawn as Liberation's replacement glyph, 0.74 to 0.88 of the Mac's width. Noto Sans CJK
(release Sans2.004, `00_NotoSansCJK.ttc.zip`) is 95 MB, almost three times the whole wheel.

## N4: the face a run with no webfont is written in (Task 15 B8, 2026-11-22)

**The probe.** Each family of the run's stack is set alone, on the run's own distinct characters,
with the coverage probe font after it (`snapshot_text_metrics.mjs` resolveWrittenFaces); the first
family whose probe is narrower than 4 em a character somewhere draws it. On 35 tokens (generics,
system aliases, core fonts, absent and installed faces), each probed on "Hello" this way, the test
agreed with the face the protocol reported on both machines. Two findings follow from it:
`-apple-system` and the `ui-*` generics draw nothing in Chrome 158 or 147 (a stack goes on past
them), and `cursive`, `fantasy`, `math` and `emoji` draw nothing in the container (its text is set
in the standard face, Liberation Serif), so they are written Times New Roman.

**Accuracy, every run of the 19 matrix decks and both corpora** (162 export documents), the engine's
written family against the face the protocol reports for the text node that holds the run, mapped
through the metric table (a hidden macOS face such as `.SF NS` as Arial, a loaded webfont as
itself):

| | runs | agree | disagree | ambiguous | unmatched |
|---|---|---|---|---|---|
| Apps (bundle, Chromium 147) | 3,314 | 3,147 | 0 | 49 | 118 |
| Mac (Chrome 158) | 3,316 | 3,135 | 13 | 50 | 118 |

The 13 on the Mac are architecture-on's DM Sans, which the deck names without loading and the
owner's Mac has installed as static fonts: the protocol names the 500 static "DM Sans Medium", and
the engine writes the family, "DM Sans", by the rule for a family the page did not load (its own
name, bold from 600). Ambiguous runs are text in several nodes drawn in different faces; unmatched,
generated text (markers, pseudo-elements). The CDP read itself was not adopted: it reports the faces
a node's glyphs came from, not which character each drew, so a node of fallback characters alone
(a row of Harvey balls) names a fallback face, and the run's face still needs the stack's order.

**Time.** On Apps, the two 28-slide decks, three runs each, the engines alternating: long-off 25.26
→ 25.63 s (median, +1.5 %), long-on 25.72 → 25.93 s (+0.8 %), 7 to 13 ms a slide.

## D4 and D5: shadow layers

Measured 2026-11-21 (Task 14 B2), on a probe deck rendered in PowerPoint for Mac (its PDF at
1280 px) and converted through Drive (1600 px thumbnails, box-filtered to 1280).

**A shape's shadow follows its fill's alpha, in both apps.** A 160 × 100 white rect on white
casting black at alpha 0.5, 16 px at 45°, blur 0; the shadow's level beside the rect (255 is
none, 128 the full shadow), and under the rect where its fill lets it through:

| fill | PowerPoint beside / under | Google Slides beside / under |
|---|---|---|
| alpha 1 | 126 / 255 | 127 / 255 |
| alpha 0.5 | 191 / 223 | 191 / 223 |
| alpha 0.1 | 242 / 243 | 242 / 243 |
| alpha 0.01 | 253 / 253 | 254 / 254 |
| alpha 0 (transparency 100) | 255 / 255 | 255 / 255 |
| no fill, a 1 px outline | the outline's own shadow alone, a thin offset frame | the same |

So no shape casts a full shadow unless it is filled opaque, and both apps draw a shadow under
a translucent fill, through it, where the browser (which paints a box-shadow outside the border
box only) shows what lies beneath the box. A shape carries one outer shadow (`a:outerShdw`).
B2 drew each box-shadow layer the box's own shape could not carry as a shape of its own under
the box, filled opaque so it showed nothing but its shadow. B5 replaced those shapes with one
fitted shadow on the box itself (below), so that a moved box leaves nothing behind.

**The blur needs no calibration.** CSS blur radius B is written as `blurRad` B (in points of
px). White 240 × 160 boxes, 14 px round, on F9F7F4, black at alpha 0.5; the darkening below
the box summed over 60 px, and where it ends (the last px at ≥ 0.5 level):

| layer | Chrome | PowerPoint | Google Slides |
|---|---|---|---|
| `0 8px 20px` | 1098, 33 px | 1103, 25 px | 1009, 22 px |
| `0 2px 6px` | 301, 8 px | 285, 6 px | 257, 5 px |
| `0 24px 48px` | 3114, 59+ px | 3048, 59+ px | 2961, 59+ px |
| `0 8px 20px`, 1B3139 at 0.08 | 140, 25 px | 149, 19 px | 124, 18 px |

The total matches within 10 %; both apps fall off a little more steeply than Chrome's Gaussian.

### The fitted shadow (B5)

Decided 2026-11-21 by the owner, built 2026-11-22 (Task 14 B5). One shape carries one outer
shadow (`a:outerShdw`) in either app, and that is how a person gives a box a shadow there. So a
box's `box-shadow` layers are written as one shadow on the box's own shape, and no shape is drawn
for a shadow alone. One layer with no spread is written as it is. Any other set of layers (two or
more, or one with a spread, which an outer shadow has none of) is written as **the one layer
closest to them all together**, fitted from the layers themselves (`snapshot_borders.mjs`
fittedLayer):

1. **The model** (CSS Backgrounds 3: a shadow is the border box offset, spread, and blurred by a
   Gaussian of half the blur radius). Far from the corners, a layer with offset (x, y), blur B
   (σ = B / 2), spread s and alpha a covers a point d px outside a long edge of the box, n its
   outward normal, `a · Q((d − (x, y)·n − s) / σ)`, where Q is the standard normal's upper tail
   (a step where B is 0). Layers compose as `1 − ∏(1 − c)`.
2. **The points.** The four edges (bottom, top, right, left) at d = k·R/64, k = 0..64, R the
   layers' reach (the largest |x| + |y| + max(spread, 0) + 2B) plus 1 px.
3. **The error** of a single layer (x, y, B, a) with no spread: its coverage less theirs,
   squared, summed over those points.
4. **The search.** For each offset and blur the best alpha is solved in closed form (least
   squares, clamped to 0..1). Offset and blur are found on a grid of 9 points an axis, narrowed
   4 times to the best point one step either side: the offset within the layers' own, widened
   either way by their largest spread (a spread moves an edge as an offset does), the blur from
   0 to their largest plus twice their largest spread.
5. **The colour** is the layers' colours, each weighted by what it covers alone over the same
   points.
6. Lengths are kept to 0.01 px and alpha to 0.001; at most 16 layers are fitted, the first
   listed. A fit with no alpha to keep (under 0.001) writes no shadow; a layer written as it is
   keeps its own alpha, however faint.
7. **The budget.** One set of layers is fitted once, and a slide makes at most 64 fits (each
   costs 6–10 ms): past them, a box carries its first layer as it is, as before the fit, and one
   `[html2pptx] box-shadow fits: N box(es) past the 64 fits a slide makes carry their first
   shadow layer` line counts them.

The fits this gives (the engine's, read back from the deck; the tests pin the first two):

| `box-shadow` | fitted layer |
|---|---|
| `--shadow-md`: `0 2px 6px`, `0 8px 20px`, 1B3139 at 0.08 each | `0 5.13px 14.34px`, 1B3139 at 0.139 |
| `--shadow-sm`: `0 1px 2px` at 0.06, `0 1px 3px` at 0.08 | `0 1px 2.58px`, 1B3139 at 0.137 |
| `--shadow-lg`: `0 8px 24px`, `0 24px 48px`, 1B3139 at 0.10 each | `0 16px 38.63px`, 1B3139 at 0.184 |
| Tailwind `shadow-md`: `0 4px 6px -1px`, `0 2px 4px -2px`, black at 0.1 | `0 3.18px 4.12px`, black at 0.117 |
| Tailwind `shadow-lg`: `0 10px 15px -3px`, `0 4px 6px -4px`, black at 0.1 | `0 7.82px 9.70px`, black at 0.103 |
| Tailwind `shadow-2xl`, one layer: `0 25px 50px -12px`, black at 0.25 | `0 24.06px 36.71px`, black at 0.174 |
| a glow, one layer: `0 0 12px 4px`, FF5F46 at 0.3 | `0 0 15.94px`, FF5F46 at 0.47 |
| one layer with no spread, `0 2px 8px` 1B3139 at 0.08 | itself |

B2's coarser fit of `--shadow-md` (0.5 px and 1 px steps) was `0 5px 15px` at 0.14.

**What no box shape can carry.**
- **A box with no fill casts no shadow.** Neither app casts a shadow from an unfilled shape (the
  table above), and an outline would cast only a thin offset frame of itself, which the browser
  does not paint. Before B2 such an outline carried the first layer; B2 drew shadow shapes filled
  with the colour beneath; neither is written now.
- **A translucent box casts the fitted shadow itself**, as before B2: both apps draw it scaled by
  the fill's alpha, and through the fill.
- **No opaque fill can show:** no shape is drawn but the box's own.

**Rings.** A spread-only layer is a ring, drawn as before (D2). The box's one shadow paints where
its first shadow layer does, so a ring listed before that layer is drawn over the box (it lies
outside the border box and covers nothing of the box), and any other ring under it.

## D6: dotted borders in Google Slides

Measured 2026-11-21 (Task 14 B2). Lines 400 px long, read from each app's PDF (dash arrays in
pt, at 1.5 pt for a 2 px line) and from the Slides API:

| written | PowerPoint | Drive converts to | Google Slides draws |
|---|---|---|---|
| `sysDot` | [w w] | DOT | [w 3w] |
| `dot` | [w 3w] | DOT | [w 3w] |
| `sysDash` | [3w w] | DASH | [4w 3w] |
| `dash` | [4w 3w] | DASH | [4w 3w] |
| `custDash` 1:1, 1:0.5 or 1:2 | as written | DASH_DOT | [4w 3w w 3w] |

DOT is [w 3w] at 1, 2 and 4 px, on lines and outlines alike: no dash Drive offers is the 1:1
dot CSS paints. A custom-geometry stroke holding its centre line twice, as two subpaths, the
second starting two widths along, keeps both subpaths in Drive (stored as a freeform line,
`lineType` unset), and Drive starts the dash afresh on each: in its thumbnails the dots are 1:1
at 1, 2 and 3 px (period 4 px at 2 px), straight and closed. PowerPoint draws the same stroke
as one sysDot line, the passes on the same dots. So the deck for Google Slides writes a dotted
border so (`emit_dotted.cjs`); the deck for PowerPoint keeps sysDot.

**Where the dots fall.** Chrome draws a thin dotted side's dots on whole px, one width on and one
off, laid back from the side's right or bottom end: its last dot ends there, and what the length
leaves over is a narrower gap after its first dot (sides of 97 to 549 px at 1, 2 and 3 px, all
four sides; one of twelve, 100 px starting at 10.3 px, put the narrow gap before its last dot
instead). A dash runs from its path's start, so the Google passes start at that end.

**Result** (`slide-azure-flow-example`'s dotted column separators, 2 px, read down the first
one's centre at 1280 px): the dot period is UI 4.00 px, Google 8.00 → 4.00 px, PowerPoint 4.00
px (unchanged); the dot centres sit at 0.50 px past a period in the UI, 0.41 in Google and 1.34
in PowerPoint (the deck for PowerPoint runs its lines from the top, as before).

## D10: dotted table-cell borders

Measured 2026-11-21 (Task 14 B3). Native tables whose cells write one edge's border on both
sides (as the deck writes every collapsed edge), at 1, 2 and 3 px, each dash written into the
cells' `a:lnB`/`a:lnT`, read from each app's PDF (dash arrays in pt) and from the Slides API's
`tableBorderProperties.dashStyle`:

| written on a cell border | PowerPoint | Drive converts to | Google Slides draws |
|---|---|---|---|
| `sysDot` | [w w] | DOT | [w 3w] |
| `dot` | [w 3w] | DOT | [w 3w] |
| `sysDash` | [3w w] | DASH | [4w 3w] |

A cell border is one `a:ln` (`a:lnL`, `a:lnR`, `a:lnT`, `a:lnB` in `a:tcPr`), a preset or a custom
dash and nothing more: it holds no second stroke, so the two-pass dotted stroke of D6 cannot be
one, and Drive converts every `custDash` to DASH_DOT (D6). So both decks write a dotted cell
border `sysDot`: PowerPoint draws CSS's 1:1 dot, Google Slides its DOT, a dot one width long
every four widths. pptxgenjs writes a table border only solid or `sysDash`, so the dotted sides
are written dashed and their `prstDash` rewritten once the deck is written
(`emit_table.cjs dotTableBorders`). A border Drive sees `noFill` on one side of an edge and a line
on the other it drops, whichever its dash: the deck writes each edge on both cells.

**Result** (the engine's own export of a table with 2 px dotted rules and a 1 px dotted column
rule, read from each app's PDF): PowerPoint draws [w w] at 1 and 2 px (before, written
`sysDash`: [3w w]); Google Slides [w 3w] (before: [4w 3w]). For the 2 px rule, dash and period:

| | dash | period |
|---|---|---|
| UI (CSS dotted) | 2 px | 4 px |
| PowerPoint, before → after | 6 → 2 px | 8 → 4 px |
| Google Slides, before → after | 8 → 2 px | 14 → 8 px |

## D7: seams between filled table cells

Measured 2026-11-21 (Task 14 B3), in PowerPoint's PDF of the corpora, rasterised at 1280 px by
MuPDF and by Apple's Quartz. For every interior column line between two cells of one row filled
alike, the pixel columns either side of it over the row's middle half; a seam is one straying
more than 6 levels from the fill. Cell fills that meet between two pixels anti-alias into a
lighter column; Chrome snaps every box edge to a whole pixel and paints none.

The first fix put every grid line on the whole px nearest the browser's. That cleared the
seams but blurred each 1 px rule, centred on its line, over two pixel rows (corpus 05,
PowerPoint 2.26 → 2.41), and it cost Google Slides, which drew no seam: none of its views
shows a CSS px as a whole pixel (its thumbnails are 1.25 px to one), so the moved edges only
fell between its pixels (`slide-data-table` 1.17 → 1.57). So, as built:
- the deck for PowerPoint puts each grid line where Chrome paints its border: the border's
  first edge on the whole px nearest the browser's, so a line with no border lies on that px
  and a 1 px rule's centre half a px past it (`snapshot_table.mjs snappedLines`; a line takes
  the width most of its slots draw, the wider on a tie);
- the deck for Google Slides keeps the browser's grid.

| PowerPoint's PDF, seam pixel columns (MuPDF / Quartz), worst stray | before | after |
|---|---|---|
| corpus 05, 8 interior lines in filled rows | 8 / 6, 55 levels | 0 / 0, 1 level |
| corpus 15, 16 lines | 6 / 8, 54 | 0 / 0, 1 |
| `slide-data-table`, 20 lines | 1 / 1, 46 | 0 / 0, 1 |

Corpus 05's 1 px rule at 403 px, down x = 300: UI DCE0E2 on one pixel row; before, two blended
rows; after, DCE0E2 on that one row.

## D11: corners of different radii

Measured 2026-11-21 (Task 14 B4). Twelve 240 × 120 px boxes on a white slide, each written by
pptxgenjs as one construct and as CSS (`border-radius` per corner) for the truth, every edge on
a multiple of 4 CSS px so that it is a whole pixel of Google's 1.25× thumbnail too (a row at
y = 270 px, between its pixels, scored about 1.1 in Google whatever its construct). Each box,
grown by 6 px, is scored as the harness scores a slide (mean difference from the UI), with the
pixels off by more than 64 levels: PowerPoint's PDF at 4× box-filtered (H1), Google's LARGE
thumbnail.

| box | construct | PowerPoint | Google Slides | Drive keeps it as |
|---|---|---|---|---|
| 16 px top corners | one roundRect, the largest radius (before) | 0.71, 118 px off | 0.97, 118 px off | ROUND_RECTANGLE |
| | `round2SameRect` (adj1, adj2) | 0.01, 0 | 0.29, 0 | ROUND_2_SAME_RECTANGLE |
| | custom path, `arcTo` | 0.01, 0 | 0.29, 0 | CUSTOM |
| | custom path, polygon | 0.01, 0 | 0.28, 0 | custom |
| 4, 12, 24 and 36 px corners | one roundRect (before) | 4.32, 710 | 4.57, 728 | ROUND_RECTANGLE |
| | custom path, `arcTo` | 0.02, 0 | 0.29, 0 | CUSTOM |
| | custom path, polygon | 0.02, 0 | 0.28, 0 | custom |
| 16 px left corners | custom path, `arcTo` | 0.01, 0 | 0.28, 0 | CUSTOM |
| 48 × 24 px top-left ellipse | custom path, `arcTo` | 0.01, 0 | 0.29, 0 | CUSTOM |
| 16 px top corners, 4 px border | `round2SameRect` | 0.10, 2 | 0.43, 2 | ROUND_2_SAME_RECTANGLE |
| | custom path, `arcTo` | 0.10, 2 | 0.42, 2 | CUSTOM |

A uniform 16 px roundRect scores 0.01 in PowerPoint and 0.29 in Google on the same rows: both
apps draw every per-corner construct to that floor. So the deck writes, for both apps, the
preset where it fits exactly (top corners one circle, bottom ones another, each at most half
the short side, where `round2SameRect` pins its adjustments), which stays a preset with its
handles in both, and a custom path of one quarter `arcTo` per rounded corner otherwise
(`emit_model.cjs`). pptxgenjs writes a preset's two adjustments only through `angleRange`,
each value × 60000.

The same probe for `round1Rect` (adj: the top-right corner alone) and `round2DiagRect` (adj1:
the top left and bottom right; adj2: the top right and bottom left), written as the emitter
writes them (`rectRadius` for the one adjustment, `angleRange` for the two), measured
2026-11-22:

| box | construct | PowerPoint | Google Slides | Drive keeps it as |
|---|---|---|---|---|
| 16 px top-right corner | one roundRect (before) | 1.05, 177 px off | 1.32, 177 px off | ROUND_RECTANGLE |
| | `round1Rect` | 0.00, 0 | 0.28, 0 | ROUND_1_RECTANGLE |
| | custom path, `arcTo` | 0.00, 0 | 0.28, 0 | CUSTOM |
| 40 px top-right corner | `round1Rect` | 0.01, 0 | 0.29, 0 | ROUND_1_RECTANGLE |
| 16 px top-left and bottom-right | one roundRect (before) | 0.71, 118 | 0.98, 118 | ROUND_RECTANGLE |
| | `round2DiagRect` | 0.01, 0 | 0.29, 0 | ROUND_2_DIAGONAL_RECTANGLE |
| 24 px TL and BR, 8 px TR and BL | `round2DiagRect` | 0.01, 0 | 0.29, 0 | ROUND_2_DIAGONAL_RECTANGLE |
| | custom path, `arcTo` | 0.01, 0 | 0.29, 0 | CUSTOM |
| 20 px TR and BL | `round2DiagRect` | 0.01, 0 | 0.28, 0 | ROUND_2_DIAGONAL_RECTANGLE |
| 60 px TL and BR, half the short side | `round2DiagRect` | 0.02, 0 | 0.31, 0 | ROUND_2_DIAGONAL_RECTANGLE |
| 16 px top right, 4 px border | `round1Rect` | 0.10, 3 | 0.40, 3 | ROUND_1_RECTANGLE |
| 24/8 px diagonals, 4 px border | `round2DiagRect` | 0.09, 0 | 0.48, 0 | ROUND_2_DIAGONAL_RECTANGLE |

So both presets draw exactly where their pairs fit, as `round2SameRect` does, and the emitter
writes them too (`cornerPreset`): `round2SameRect` for a top and a bottom pair, `round2DiagRect`
for two diagonal pairs, `round1Rect` for a top-right corner alone, each corner a circle of at
most half the short side; any other mix stays a custom path.

**Result** (a probe corpus of three slides through the harness: card headers and footers, a
24/6 px header, a shadowed top-rounded card, a segmented control, a progress bar's fill, a
speech bubble, an elliptical box, bordered and dotted boxes, a box a frame clips, a ringed chip,
a turned leaf and a shadowed diagonal box), baseline engine → B4, PowerPoint / Google: slide
scores 0.71 → 0.64 / 1.23 → 1.17, 1.26 → 1.06 / 1.84 → 1.78 and 1.23 → 1.08 / 1.44 → 1.29;
pixels off by more than 48 levels in the squares of the 17 boxes' corners 2197 → 228 in
PowerPoint and 2287 → 472 in Google. What is left is not the corners' shape (crops at 5×): a
dotted border's dot phase, Google's softer stroke edges (the same before and after), and text
inside a large corner's square.

## D12: the browser's synthetic bold in Google Slides

Measured 2026-11-22 (Task 14 B6) on a probe page whose DM Mono and DM Sans each load 400 and 500
alone, so a bold request (600 or 700) is the browser's synthetic bold of the 500 face, which
Chrome draws at that face's own advances (the 700 and 500 lines measure alike, 159.44 px). One
slide per construct, each written by the engine's own emitter for Google Slides and converted
through Drive. Placement is read from Google's PDF (each run's first and last glyph box, MuPDF)
and from the LARGE thumbnail (the run's ink edges against Chrome's render at 1.25×), minus the
browser's Range rect; ink is the run's summed ink in Google's PDF at 2× over Chrome's at 2×
(render_truth `--scale=2`).

| written (typeface, bold) | the Slides API reads | Google draws | right-aligned run's edges, PDF | thumbnail | the run after a left-aligned one starts | ink at 2× |
|---|---|---|---|---|---|---|
| `DM Mono Medium` + bold (the construct before B6) | DM Mono, 700 | DMMono-Regular, faux bold | −5.6 to −10.0 px, both edges | left edge −5.6 to −9.6 | +4.7 px | 0.97–1.03 |
| `DM Mono` + bold | DM Mono, 700 | the same | the same | the same | the same | the same |
| `DM Mono Bold` | DM Mono, 700 | the same | the same | the same | the same | the same |
| `DM Mono SemiBold` | DM Mono, 500 | DMMono-Medium | 0.00 | 0.00 | 0.00 | 0.78–0.80 |
| **`DM Mono Medium`** | DM Mono, 500 | DMMono-Medium | **0.00** | **0.00** | **0.00** | **0.78–0.80** |
| `DM Mono Medium` with a 0.4 pt run outline | DM Mono, 500 (the outline dropped) | DMMono-Medium | 0.00 | 0.00 | 0.00 | 0.78–0.80 |
| `DM Sans Medium` + bold (before B6) | DM Sans, 700 | DMSans-Bold, a Bold the page did not load | left edge −6.5, right +0.04 | left −7.2 | +3.3 | 0.98–1.00 |
| `DM Sans SemiBold` | DM Sans, 600 | DMSans-SemiBold | left edge −3.7 | left −4.0 | +1.9 | 0.90–0.92 |
| **`DM Sans Medium`** | DM Sans, 500 | DMSans-Medium | **within 0.06** | **0.00** | **0.00** | **0.78–0.79** |

The controls, the page's own 500 and 400 runs, draw 0.89 and 0.87 of Chrome's ink at 2× in Google's
PDF: Google draws plain text about 11 % lighter than Chrome at that scale. Against them the face
alone is 10–12 % lighter than Chrome's synthetic bold. At 1×, the harness's truth scale, Chrome's
synthetic bold adds no ink measurable (Phase C), so there the face alone matches the UI's weight.

Two facts decide it. Drive converts a bold flag to weight 700, whatever face is named; and Google
lays out a faux bold wider than it draws it (about 0.4 px a glyph at 15 px; in the thumbnail the
glyphs are drawn at that wider pitch, in the PDF at the font's own and the run shifted), and a
real Bold it has, but the page did not load, at that Bold's own advances. Only the face alone puts
the run's edges within 0.5 px of the browser's, in both alignments and both families (the ruling:
placement first). So the deck for Google Slides writes the browser's synthetic bold as the lighter
face with bold off (`emit_typography.cjs` typefaceFor, from `model.fonts`); the deck for PowerPoint
keeps the face plus bold, which PowerPoint draws at the face's advances (Phase C: UI 1181.75,
PowerPoint 1182.35). Google Slides has no character spacing, so no tracking could take up the faux
bold's advance.

**What was measured, and what follows from it.** The measured cases are the browser's synthetic
bold of the 500 face, in two families Google hosts: DM Mono, which has no 700, and DM Sans, which
has one the page did not load. The rule reaches further by the same mechanism, unmeasured. Drive
turns any bold flag into weight 700. So for a lighter face (600 on 400, 800 on 300) Google likewise
draws a faux bold of a weight it has, or a real Bold, never the face the browser drew. And a loaded
webfont Google does not host gets no face of its own there either way; its run is the face alone
too.

## D13: a rounded table's corner pieces in Google Slides

Measured 2026-11-22 (Task 14 B6). A rounded clip's corner cell is unfilled in the `a:tbl` and its
fill drawn as a custom shape under the table, the cell cut to the arc (D5). In the deck for Google
Slides, which keeps the browser's grid (D7), that shape meets its neighbours between pixels.

**How Google draws them** (a probe slide: coral fills at ten fractional offsets, f = 0.0 to 0.9 of a
thumbnail pixel, on both axes; the cover of the edge's pixel row in the LARGE thumbnail):

| drawn as | f = 0 | f = 0.1 | 0.3 | 0.5 | 0.7 | 0.9 |
|---|---|---|---|---|---|---|
| a native table cell | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| a preset rect | 1.0 | 0.88 | 0.75 | 0.50 | 0.25 | 0.12 |
| a custom path | 1.0 | 0.88 | 0.75 | 0.50 | 0.25 | 0.12 |

The thumbnail draws a native cell without anti-aliasing, filling each pixel whose top left corner
it holds, and a shape anti-aliased at its exact place. Google's PDF draws both as vectors at the
same coordinates (the cells to within 0.0012 px of the pieces).

**`slide-data-table`, every straight edge of its four pieces** (the profile 3 px either side of each
edge, the median along its straight part; the largest channel difference against the same deck
with the corner cells filled natively, whose cell edges lie on the same lines, and against Chrome
at the same scale):

| edge | thumbnail, against native / UI (native's own) | Google's PDF at 1× / 2×, against native |
|---|---|---|
| top-left piece, right (inner, x = 356.484, coral beside coral) | 73 / 73 (0) | 0 / 0 |
| top-left and top-right, bottom (inner, y = 252.781, white below) | 0 / 12 (12) | 0 / 0 |
| top-right piece, left (inner, x = 989.484) | 0 / 35 (35, Chrome's own seam at 1.25×) | 0 / 1 |
| top-left and top-right, top (outer, y = 206.781) | 92 / 43 (49) | 0 / 0 |
| top-left, left (outer, x = 88); top-right, right (x = 1192) | 0 / 11 (11) | 0, 10 (the native cell 0.003 px short) |
| the white pieces, every edge | 0 | 0–3 |

The seam at x = 356.5 is where the native cell's edge moves away from the piece's (445.605 to 446
in the thumbnail, the pixel between them 0.605 coral over white: ff9e8f); at 989.484 it moves over
the piece (1236.855 to 1237) and hides it. Which edges seam is a matter of phase, so the fix is
general: **an inner edge runs under its opaque native neighbour**, which paints over the overlap.
A probe of two-cell tables (a piece under the unfilled cell, its native coral neighbour) at 16
phases, along a column line and a row line (the worst seam, levels):

| run under by | LARGE thumbnail (1.25×) | MEDIUM (0.625×) | PDF 0.625× | PDF 1× | PDF 2× |
|---|---|---|---|---|---|
| 0 px (before B6) | 162 | 116 | 46 | 46 | 45 |
| **1 px** | **0** | **0** | 7 | **0** | **0** |
| 2 px | 0 | 0 | 0 | 0 | 0 |

At 0 px the PDF's figures are what two native cells meeting on a fractional line show there (on
`slide-data-table` the piece's edges equal the native comparator's in the PDF), so 1 px clears
the native cells' bar everywhere it was measured, and leaves a moved table's corner pieces 1 px
over their cell. As built (`snapshot.mjs` pushTable and `CORNER_RUN_UNDER_PX`, the deck for
Google alone; `snapshot_table.mjs` runUnderPolygon, over the table's own slot grid): each side whose every slot across is an opaque native cell moves out by 1 px, or half that
row's or column's size where that is less; the corner square between two such sides only where
the slot across the corner is opaque too; never under another corner cell. On `slide-data-table`
the seam at x = 356.5 is then 0 levels in the thumbnail (73 before), its other edges are as they
were there, and in Google's PDF its inner edges match the UI (0) where native cell boundaries
still show MuPDF's 9 to 45 levels.

**The outer edges stay on the browser's lines.** At the top edge the thumbnail drops the native
cells' partial row (258.477: they start at 259) where the piece paints it at half cover, so the
piece's top row differs from its neighbours' by 92 levels. Against Chrome at 1.25× the piece is the
nearer (43 levels, the native cells 49), and in Google's PDF the piece and the cells are identical.
No shape is drawn as the cells are (the table above), so the only way to match them in the
thumbnail is to move the piece's outer edges onto its pixel grid (ceil(edge × 1.25) / 1.25), and
that splits them from the cells in the PDF: 50, 100 and 86 levels at 1×, 1.25× and 2×, where before
they were 0. So they are left where the browser has them.

**Ending the run-under short of the outer edges** (B6 fix round 1, a probe of `slide-data-table`:
each coral piece's strips ending 1 px short of the table's top, left and right edges, against the
pieces as built). Where a piece's strip meets the table's top edge, as built:
- the thumbnail's light top row runs on to x = 356.8 (its pixel 446);
- Google's PDF draws the edge's anti-aliased row a little darker there, where the strip's top
  and its neighbour cell's overlap: 17–19 levels at 1× and 40–47 at 2×, over one or two pixels.

Ended short, the light row stops one thumbnail pixel sooner and the darker pixels go. But the top
pixel of the seam comes back:
- in the thumbnail at (445, 259), 48–55 levels;
- in the PDF, 28–33 levels at 1× and 4–8 at 2×.

The PDF does not stay at 0, so the strips run to the table's edges, as built.

## H1: rasterising an app's PDF

Measured 2026-11-21 (Task 14 B4) on the PDFs PowerPoint saved of both corpora at `09ceb289`.
PowerPoint embeds each picture at twice its slide size, with an alpha mask and
`/Interpolate true`. MuPDF drawing a page at 1280 px draws such a picture's light rules dark:
corpus slide 03's gridline, EBEBEB on two pixel rows in the UI, is B2B2B1 and B4B4B2; drawn at
4× (5120 px) and box-filtered to 1280 px it is E9EAE9 and D0D1D0, the first row the UI's grey. A synthetic page reproduces it from the embedding alone (a 2× masked
picture 0.36 px off the grid: a rule's weight 140 at 1×, 49 at 4×, its own 20).

| PowerPoint mean, same PDFs | 1× | 4×, box-filtered |
|---|---|---|
| in-repo corpus (17) | 1.865 | 1.824 |
| design-system corpus (27) | 1.706 | 1.615 |

Google Slides is unchanged (its thumbnails are not rasterised by the harness). The 4× raster
lowers 12 of 17 and 20 of 27 slides' scores; it raises 8 by more than 0.05 (corpus 05, 08, 09,
15 and 16 by 0.10 to 0.17; `slide-medallion` 0.20, `slide-journey` 0.09,
`slide-executive-summary` 0.07), all at the edges of text and shapes, where neither raster's
anti-aliasing is Chrome's. Against Apple's Quartz drawing the same PDF, the 4× raster is closer
on 6 of the 9 slides probed (03 1.70 → 1.48, 09 2.11 → 1.74, 15 1.37 → 1.15, 16 0.84 → 0.77,
`slide-data-table` 1.65 → 1.23, `slide-medallion` 2.01 → 1.70) and within 0.01 on the other 3.

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
(`docs/superpowers/plans/2026-11-16-export-fidelity-progress.md`, B1). D4, D5 and D6 (B2) were
measured the same way, on probe decks of shapes and lines and on Chrome screenshots at device
scale 4. The fitted shadow (B5, 2026-11-22) is computed, not measured; its result was measured on
the design-system corpus (`docs/superpowers/plans/2026-11-16-export-fidelity-progress.md`, B5).
D10 and D7 (B3) were measured on probe decks of native tables and on the two corpora's
PowerPoint PDFs. D11 (B4) was measured on a probe deck of
boxes and on a probe corpus through the harness, H1 (B4) on the two corpora's PowerPoint PDFs. D12
and D13 (B6, 2026-11-22) were measured on probe decks the engine's own emitter wrote for Google
Slides (a page of synthetic-bold runs in the deck's faces, the data table's model with its
corner pieces varied, and fills at fractional offsets), converted through Drive, their PDFs and
LARGE and MEDIUM thumbnails read and the presentations deleted by id, and on the two corpora's
Google decks. N3, N4 and D8's symbols (B8, 2026-11-22) were measured on a throwaway app on the dev
workspace running the sidecar's own bootstrap and Chromium, read through the DevTools protocol,
against the Mac's Chrome, and on probe decks of symbols written in each candidate face, rendered in
PowerPoint for Mac and converted through Drive, their PDFs read and the presentations deleted by id;
the app was deleted afterwards (`docs/superpowers/plans/2026-11-16-export-fidelity-progress.md`,
B8).

To re-run (PowerPoint will briefly open a window):

    uv run --with pymupdf --with pillow python scripts/export_fidelity/calibrate_text.py --out /tmp/calib
    uv run --with pymupdf python scripts/export_fidelity/measure_script_lines.py \
        --out /tmp/script-lines --powerpoint --gslides
