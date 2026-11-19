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

**Single spacing is 1.2 x the font size (ruling R1).** PowerPoint and Google Slides draw 100%
line spacing at 1.2 x the font size, whatever the font's own metrics. DM Sans and DM Mono have
hhea, typo and win metrics of 1.302 to 1.322 em, and Arial and Georgia 1.09 to 1.15, and all four
measured at 1.2 em. The browser's `line-height: normal` is the font's metrics (83 px for DM Sans
at 64 px). Written as a percentage of that natural height, as first planned, every line came out
about 8% short: up to 8.5 px per line pair at 64 px in PowerPoint, 8.2 px in Google.

**Spacing encoding (ruling R2, option C).** In a block the browser laid out on more than one line:

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

The brief's probe set is DM Sans and DM Mono at 13, 16, 20, 32, 42 and 64 px, each at
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
absorbs it.

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
line's size, plus the browser's growth of the line over `GOOGLE_LINE_GROWTH_PER_PX` (A4; task-11
ruling R11g), because Google sizes the whole line by the run's written size. Google then sets
the line on the browser's baseline (+0.52 px at 20 px, +1.05 px at 40 px) and draws the script
glyph at **0.800** of the browser's size on a line the browser did not grow. Placement wins over
glyph size there: an accepted Google Slides trade-off (ruling R11i).

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

R11g's first measurement, on 2026-11-18, read 5.57 and 11.13 px. The value is DM Sans's: another
face's ascent ratio moves it by a few percent, a fraction of a px per line. With it, the deck for
Google places a superscript's later line −0.56 px from the browser's (20 px, line-height 29 px).

## A5: script lines in PowerPoint

PowerPoint places a line holding a script run by its other runs, with two exceptions (task-11
findings r4, Important 2):

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
--powerpoint`, 2026-11-19), against the engine before these two rules. The first nine are the
re-review's cases; all are DM Sans at 20 px unless named:

| case | before: line 1 | before: line 2 | now: line 1 | now: line 2 |
|---|---|---|---|---|
| one line, superscript inside it (R11g's case) | +0.06 | - | +0.06 | - |
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

## Runs behind this record

| run | engine state | Google Slides presentation |
|---|---|---|
| 1 | spcPct of the natural height, constants 0, factor 1 | https://docs.google.com/presentation/d/12WlmWH9GqYiH6InYpCxWAK9AFYHSG1z9M7e38ek9C0w/edit |
| 2 | spcPct of 1.2 x size throughout (option B's encoding), constants 0 | https://docs.google.com/presentation/d/1gO5lNFvmgb-dhHEBEx8YpVr06GQmiHokH3FN92FSP2Y/edit |
| 3 | option C, constants 0, factor 0.646 (the fit) | https://docs.google.com/presentation/d/12miGQiWr6npw4PFPbGnoLrb876WTyDIZz9MAryOjpG0/edit |
| 4 | option C, the constants above (verification) | https://docs.google.com/presentation/d/1XS2dxYxfkzb0C9hEzaWOho8dwzPO4SZ1MJF1Pk6aGYw/edit |

A4 and A5 (2026-11-19) were measured on presentations the script deletes by id once read.

To re-run (PowerPoint will briefly open a window):

    uv run --with pymupdf --with pillow python scripts/export_fidelity/calibrate_text.py --out /tmp/calib
    uv run --with pymupdf python scripts/export_fidelity/measure_script_lines.py \
        --out /tmp/script-lines --powerpoint --gslides
