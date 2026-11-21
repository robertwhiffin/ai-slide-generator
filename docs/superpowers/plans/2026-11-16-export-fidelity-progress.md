# Export fidelity: verification ledger (Task 14)

Plan: `docs/superpowers/plans/2026-11-16-export-fidelity-snapshot-emit.md`.
Spec: `docs/superpowers/specs/2026-11-16-export-fidelity-snapshot-emit-design.md` (RC1–RC13).
Harness: `scripts/export_fidelity/run.py`, `docs/technical/export-fidelity-harness.md`.

This ledger records the baselines, the results and one line per corpus slide, judged against
the spec's root causes. It holds tables only: the comparison sheets and renders stay local.

## Phase A: verification at engine `d867eba8`, harness `3f4ed61e`

Phase A measures and changes no engine code. Its one code change is the harness's
`--pin-fonts` (commit `3f4ed61e`). Phase B fixes the defects below, red first, and re-runs
both corpora.

### How it was measured

- **Fonts pinned on both sides.** `run.py --pin-fonts` replaces each Google Fonts `@import` with
  the latin faces Google serves for that import, from committed OFL files. The in-repo corpus
  pins to exactly `pinned_font_css()`. The design-system deck imports DM Sans **without** an
  optical-size axis, so Google serves a different, weight-axis-only file; pinning it to the
  corpus file would have changed its UI (a 48 px bold title is 702.5 px wide with its own file
  and 645.4 px with the corpus file). It pins to its own faces, including the true italic,
  DM Mono 300 and Barlow. A 48 px probe measured pinned and live widths equal for both decks.
- **After.** The branch head, both corpora, both renderers:
  `uv run --with pymupdf --with pillow python scripts/export_fidelity/run.py <corpus> --out <dir> --pin-fonts --powerpoint --gslides`.
- **Before (legacy).** The `origin/main` extract has no harness, so its export ran through its
  own code:
  - documents built as the harness builds them, with main's `build_slide_html({"slide_id", "html"}, deck)`,
    using a deck CSS already pinned by the branch's `pinned_fonts_css`;
  - main's `build_pptx_huashu(title, [{"html", "notes": name}], bypass_validation=True)`,
    run from the extract with the branch's `.venv` python. Main has no `target`, so one deck
    serves both apps.

  It was then rendered with the branch harness's own `render_with_powerpoint`,
  `render_with_google_slides`, `check_text_loss` (without hidden text, since main logs no
  summaries) and `compare`.
- **One UI reference.** Both runs are scored against the after run's truth images. Main's
  documents differ only in the chart-init canvas step (Task 7). They render pixel-identical,
  except on corpus slide 17, where main's step wipes the script-drawn canvas the UI shows.
- **Beyond the scores.**
  - Each slide's sheet (UI | PowerPoint | Google | difference map) was inspected by eye, with
    zoomed crops where something differed.
  - A line-placement check matched every browser text line (Range rects, baseline from the
    font's ascent) against the glyph positions in PowerPoint's PDF and in Google's own PDF
    (Drive export).
  - Every matched line sits within **2.3 px** of the browser's baseline in both apps (95th
    percentile 1.0–1.2 px). No line re-wraps: every unmatched segment was checked by eye
    (hidden text, list markers, letter-spaced or monospaced gaps, fallback glyphs).

### Results

### In-repo corpus (tests/fixtures/export_fidelity, 17 slides)

| Slide | PowerPoint before → after | Google before → after | Text loss (after) | MODEL DROPS (pptx / gslides) | Captures (taken / failed) |
|---|---|---|---|---|---|
| 01-cover-gradient-svg-art | 10.99 → 4.35 | 10.72 → 2.82 | none | 0 / 0 | 2 / 0 |
| 02-agenda-grid-rules | 3.50 → 1.74 | 3.40 → 1.78 | none | 0 / 0 | 1 / 0 |
| 03-svg-combo-chart-legend-callout | 16.40 → 4.13 | 17.08 → 2.67 | none | 0 / 0 | 3 / 0 |
| 04-harvey-table-caption | 8.49 → 4.39 | 8.27 → 2.97 | none | 0 / 0 | 9 / 0 |
| 05-balance-sheet-two-tables | 13.75 → 2.91 | 13.52 → 1.80 | none | 0 / 0 | 1 / 0 |
| 06-delta-pills-table-callout | 29.54 → 4.17 | 29.35 → 2.72 | none | 0 / 0 | 1 / 0 |
| 07-timeline-dots-mono-dates | 6.06 → 4.69 | 6.08 → 2.57 | none | 0 / 0 | 1 / 0 |
| 08-kpi-cards-grid | 7.33 → 3.88 | 6.85 → 3.26 | none | 0 / 0 | 1 / 0 |
| 09-pseudo-bullets-accent-quote | 7.87 → 4.67 | 8.34 → 3.55 | none (before: profit1) | 0 / 0 | 1 / 0 |
| 10-svg-waterfall | 5.69 → 2.49 | 6.02 → 2.13 | none | 0 / 0 | 2 / 0 |
| 11-chartjs-canvas | 2.86 → 2.07 | 2.75 → 1.63 | none | 0 / 0 | 2 / 0 |
| 12-progress-bars-icons | 7.13 → 1.87 | 6.77 → 1.96 | none | 0 / 0 | 9 / 0 |
| 13-code-gradtext-rotated | 5.37 → 2.31 | 4.26 → 1.82 | none | 0 / 0 | 1 / 0 |
| 14-two-col-text-image-overlap | 4.99 → 2.51 | 5.48 → 2.15 | none | 0 / 0 | 0 / 0 |
| 15-dense-table-badges-zebra | 5.52 → 3.13 | 5.51 → 2.56 | none | 0 / 0 | 1 / 0 |
| 16-closing-cta | 5.46 → 3.09 | 5.41 → 1.59 | none | 0 / 0 | 1 / 0 |
| 17-mixed-content-hidden-graphics | 10.78 → 3.13 | 10.84 → 2.79 | none | 0 / 0 | 6 / 0 |
| **mean** | **8.93 → 3.27** | **8.86 → 2.40** | none | 0 / 0 | 42 / 0 |

Slides worse than the legacy baseline in either renderer: none. PowerPoint means with the 4x box-filtered raster (see the Task 7 item): before 8.92, after 3.22.

### Design-system corpus (local `$TMP/ds_fixture`, 27 slides)

| Slide | PowerPoint before → after | Google before → after | Text loss (after) | MODEL DROPS (pptx / gslides) | Captures (taken / failed) |
|---|---|---|---|---|---|
| slide-2x2-matrix | 5.71 → 3.64 | 5.12 → 1.75 | none | 0 / 0 | 0 / 0 |
| slide-action-title | 5.66 → 3.42 | 6.53 → 2.27 | none | 0 / 0 | 1 / 0 |
| slide-agenda | 3.69 → 2.09 | 4.18 → 0.96 | none | 0 / 0 | 0 / 0 |
| slide-azure-flow-example | 4.48 → 2.08 | 4.02 → 1.34 | none | 0 / 0 | 14 / 0 |
| slide-bold-title | 5.36 → 3.18 | 5.45 → 1.43 | none | 0 / 0 | 2 / 0 |
| slide-charts | 4.27 → 1.35 | 4.46 → 0.83 | none | 0 / 0 | 2 / 0 |
| slide-closing | 4.43 → 1.11 | 4.18 → 0.71 | none | 0 / 0 | 1 / 0 |
| slide-comparison | 5.12 → 2.44 | 5.39 → 1.50 | none | 0 / 0 | 0 / 0 |
| slide-content | 6.63 → 4.21 | 6.86 → 1.75 | none | 0 / 0 | 1 / 0 |
| slide-cover | 7.37 → 2.75 | 7.04 → 1.83 | none | 0 / 0 | 2 / 0 |
| slide-data-table | 6.15 → 2.35 | 6.54 → 1.19 | none | 0 / 0 | 0 / 0 |
| slide-event-cover | 6.19 → 3.88 | 6.38 → 1.27 | none | 0 / 0 | 2 / 0 |
| slide-executive-summary | 7.69 → 6.33 | 5.30 → 2.58 | none | 0 / 0 | 0 / 0 |
| slide-industry-title | 9.35 → 3.85 | 9.14 → 2.93 | none | 0 / 0 | 3 / 0 |
| slide-journey | 3.12 → 1.51 | 3.42 → 0.75 | none | 0 / 0 | 0 / 0 |
| slide-kpi-dashboard | 8.93 → 3.00 | 9.37 → 1.95 | none | 0 / 0 | 1 / 0 |
| slide-lakehouse-blueprint | 11.44 → 3.24 | 11.32 → 2.05 | none | 0 / 0 | 9 / 0 |
| slide-medallion | 5.29 → 3.49 | 5.69 → 1.96 | none | 0 / 0 | 0 / 0 |
| slide-milestones | 3.20 → 1.47 | 3.34 → 0.86 | none | 0 / 0 | 0 / 0 |
| slide-reference-architecture | 5.98 → 2.78 | 5.75 → 1.95 | none | 0 / 0 | 7 / 0 |
| slide-section | 3.86 → 1.29 | 4.32 → 2.31 | none | 0 / 0 | 1 / 0 |
| slide-statement | 7.80 → 3.77 | 9.40 → 2.39 | none | 0 / 0 | 1 / 0 |
| slide-stats | 5.05 → 1.32 | 5.41 → 1.09 | none | 0 / 0 | 0 / 0 |
| slide-three-cards | 3.73 → 2.19 | 3.82 → 1.17 | none | 0 / 0 | 3 / 0 |
| slide-timeline | 3.78 → 0.70 | 4.06 → 0.82 | none | 0 / 0 | 0 / 0 |
| slide-two-column | 5.78 → 2.84 | 5.95 → 1.44 | none | 0 / 0 | 0 / 0 |
| slide-waterfall | 4.03 → 2.46 | 3.61 → 1.15 | none | 0 / 0 | 1 / 0 |
| **mean** | **5.71 → 2.69** | **5.78 → 1.56** | none | 0 / 0 | 51 / 0 |

Slides worse than the legacy baseline in either renderer: none. PowerPoint means with the 4x box-filtered raster (see the Task 7 item): before 5.68, after 2.62.


Both corpora: no text loss, no MODEL DROPS, no export failures and no capture failures, in
either target. Every slide improved in both renderers. The legacy engine lost one word
(`profit1`, slide 09's superscript).

### Defects found (Phase B work)

| Id | Renderer | What differs from the UI | Cause (measured) | Proposed fix, owning module |
|---|---|---|---|---|
| D1 | PowerPoint | DM Sans **italic** runs drawn as **Bold Italic**: lines 15–42 px wider and visibly heavy (10 slides) | The run is `DM Sans` + `i="1"`. The installed statics name the regular italic's family `DM Sans Italic` (name ID 1, no italic bit), so the only italic member of family `DM Sans` is Bold Italic. PowerPoint's PDF embeds `DMSans-BoldItalic` for every such run; Google embeds `DMSans-Italic` | For the `pptx` target, write the italic static's own family (`DM Sans Italic`, `DM Sans Medium Italic`, …) with italic off. Google keeps `DM Sans` + italic. First probe both namings in PowerPoint, including a variable-font install. `emit_typography.cjs` |
| D2 | both | A translucent spread ring (`box-shadow: 0 0 0 4px rgba(…,.18)`) on a 14 px dot draws an 18 px solid dot with a 2 px halo | The ring becomes the shape's own outline on a shape grown by half the spread, and the fill grows with it, under the translucent ring | Keep the fill at the border box, with the ring as its own unfilled shape (or keep the merge for opaque rings only). `snapshot_borders.mjs` (`spreadRings`), `emit_model.cjs` |
| D3 | both | Harvey-ball fills (pseudo-elements inside a round `overflow:hidden` host) poke out of the circle as square corners | A rounded overflow container clips as its rectangle (deferred Task 6 minor) | Clip the children to the rounded padding box (the custom-geometry path the clipped circles already use), or capture such a host as one picture. `snapshot.mjs` (overflow clip) |
| D4 | both | Card shadows too short and faint: the UI's shadow tail is 26 px, the export's 6 px | Only the first `box-shadow` layer is kept (one `outerShdw` per shape). The design system's `--shadow-md` and `--shadow-lg` are two layers, and the larger one is dropped | Emit each further layer as its own shadow-casting shape under the box. `snapshot_borders.mjs` (`outerShadow`), `emit_model.cjs` |
| D5 | both | A rounded, shadowed table wrapper: square header corners and no shadow | The shadow sits on an unfilled `roundRect`, and neither app casts a shadow from `noFill`. The header cells' fills overpaint the wrapper's rounded corners | Give the shadow shape a fill hidden under the table, and clip the corner cells to the radius (or draw the header as a rounded shape under transparent cells). `emit_model.cjs`, `snapshot_table.mjs` / `emit_table.cjs` |
| D6 | Google | Dotted 2 px borders have twice the UI's dot spacing | `sysDot` converts to the Slides `DOT` dash, whose gap is about 3× the width | For the `gslides` target, use the dash that Drive maps to a 1:1 dot (probe `dot` and `custDash`). `emit_model.cjs` |
| D7 | PowerPoint | Light seams between filled table cells (header and total rows) | Per-cell fills meet at fractional px (`gridCol` 3104852 EMU = 325.97 px). They anti-alias into seams under **Apple's Quartz** as well as MuPDF, which corrects the Task 10 "MuPDF only" ruling. Snapping the grid to whole CSS px removed the seams in both renderers (probe) | Snap the column and row boundaries (absolute, not each width) to whole px. `emit_table.cjs` |
| D8 | both | Glyphs DM Sans lacks fall back to another face per app: ▲▼ come out smaller (Times New Roman or Courier New in PowerPoint, Arial in Google). In Google, U+2011 comes from MS PGothic, so "end‑to‑end" at 64 px is 29 px short | The run names only the deck family. Each app picks its own fallback, unlike Chrome | Write the face Chrome used for fallback glyphs, as their own run (CDP `CSS.getPlatformFontsForNode`). For the `gslides` target, write U+2011 as U+2010. `snapshot_text.mjs`, `emit_typography.cjs` |
| X1 | PowerPoint | Upright DM Sans lines run 0.5–1.8 % wider than the UI on every slide: titles +4.5 px median and +10.7 px at most, 22 px subtitles up to +9.6 px. Line breaks hold, inside the slack | PowerPoint for Mac applies no pair kerning to DM Sans. A probe with `kern` absent, `0` or added gave identical widths. Kerning is about 60 % of the excess (slide 07's subtitle: unkerned +5.5 px of +9.6 px). The rest is the optical-size delta's 0.5 % dead band (`OPTICAL_SIZE_THRESHOLD`) | For the `pptx` target, fold each run's kerning (measured with `font-kerning: none`) into its `spc`, and drop the dead band. `snapshot_text_metrics.mjs`, `emit_typography.cjs` |
| H1 | harness | PowerPoint 1 px picture gridlines look dark, and same-colour logo marks show a fringe, in the harness PNG only | MuPDF's 1× raster of the embedded 2× pictures. Quartz, and MuPDF at 4× box-filtered, match the UI | `run.py`: rasterise PowerPoint's PDF at 4× and box-filter it to 1280×720 (mean PowerPoint score −0.04 corpus, −0.08 design system). Also the brief's `summary.md`. `scripts/export_fidelity/run.py` |

### One line per slide

DEFECT, TRADE-OFF or MATCHES, judged against RC1–RC13. X1 (PowerPoint lines 0.5–1.8 % wide) is
on every slide, so it is listed once above and not repeated. "|Δy|" is the worst line baseline
offset, PowerPoint / Google.

**In-repo corpus.** DEFECT 7, TRADE-OFF 2, MATCHES 8.

| Slide | Tag | What still differs, cause → fix | \|Δy\| px |
|---|---|---|---|
| 01-cover-gradient-svg-art | MATCHES | Gradient ground, SVG art, tracking and breaks as the UI | 1.9 / 1.4 |
| 02-agenda-grid-rules | MATCHES | Grid, rules and mono numerals as the UI | 1.1 / 1.1 |
| 03-svg-combo-chart-legend-callout | MATCHES | The chart is a picture with editable legend text. Its darker gridlines are H1, not the export | 2.0 / 1.1 |
| 04-harvey-table-caption | DEFECT | D1: the italic caption is bold italic in PowerPoint, 42 px wider. Harvey balls, the highlighted column and the native table match | 0.6 / 1.2 |
| 05-balance-sheet-two-tables | DEFECT | D7: seams between the coral header and dark total-row cells in PowerPoint. Both native tables sit side by side, captions in place (RC1/RC9 fixed) | 1.1 / 0.9 |
| 06-delta-pills-table-callout | DEFECT | D1: the italic source line in PowerPoint. Pills, table and callout match; ▲▼ fall back to a slightly smaller glyph (D8) | 1.0 / 1.1 |
| 07-timeline-dots-mono-dates | MATCHES | Dots, rule and mono dates as the UI. The 22 px subtitle is +9.6 px in PowerPoint (X1) | 0.8 / 1.2 |
| 08-kpi-cards-grid | DEFECT | D1: the italic source line. D8: the ▲▼ deltas are visibly smaller in both apps | 0.7 / 1.2 |
| 09-pseudo-bullets-accent-quote | DEFECT | D1: the `<em>` phrase and the italic footnote are bold italic in PowerPoint (+16 px). Pseudo bullets, accent bar, quote border, chip and superscript match | 0.5 / 1.1 |
| 10-svg-waterfall | DEFECT | D1: the italic source line. The waterfall picture and its card match; the dark baseline is H1 | 1.1 / 1.2 |
| 11-chartjs-canvas | TRADE-OFF | The Chart.js doughnut, with its canvas-drawn legend, is one picture ("charts become pictures"); the cards and title are native | 1.1 / 1.1 |
| 12-progress-bars-icons | MATCHES | Progress fills, icons and the off-slide circle as the UI | 0.9 / 1.1 |
| 13-code-gradtext-rotated | TRADE-OFF | Gradient headline words are one solid colour, the gradient's middle (spec §3 Runs; Task 3 ruling). The code block and the turned "Governed data" label match | 0.5 / 1.1 |
| 14-two-col-text-image-overlap | MATCHES | As the UI. Light-on-dark text looks thinner in both apps, which is Chrome's macOS text rendering in the truth, not a weight change | 1.4 / 1.2 |
| 15-dense-table-badges-zebra | DEFECT | D7: seams between header and net-income cells in PowerPoint. Zebra rows and badges match | 1.0 / 1.0 |
| 16-closing-cta | MATCHES | As the UI | 1.4 / 1.6 |
| 17-mixed-content-hidden-graphics | MATCHES | Icons beside bare text, hidden graphics hidden, faded copy faded, the script-drawn canvas present (the legacy export lost it) | 0.9 / 1.1 |

**Design-system corpus.** DEFECT 9, TRADE-OFF 0, MATCHES 18.

| Slide | Tag | What still differs, cause → fix | \|Δy\| px |
|---|---|---|---|
| slide-2x2-matrix | DEFECT | D2: the plotted dot's translucent ring is drawn as a larger solid dot in both apps. The matrix, the turned axis label and the bullets match | 1.1 / 0.9 |
| slide-action-title | DEFECT | D1: the italic footnote in PowerPoint (+27 px). Bars and callout match | 0.7 / 0.9 |
| slide-agenda | MATCHES | As the UI | 1.2 / 1.2 |
| slide-azure-flow-example | DEFECT | D1: the italic caption (+38 px, PowerPoint). D6: the dotted column separators have double spacing in Google. D4: the `--shadow-md` cards lose their outer shadow layer | 1.5 / 0.7 |
| slide-bold-title | MATCHES | As the UI. The logo-mark fringe in the harness PNG is H1: Quartz shows none | 1.6 / 1.6 |
| slide-charts | MATCHES | Charts are pictures with native titles and legends. The gridlines are H1 | 0.7 / 1.1 |
| slide-closing | MATCHES | As the UI | 1.8 / 1.6 |
| slide-comparison | DEFECT | D3: the Harvey-ball fills show square corners outside their circles in both apps. D1: the italic legend labels in PowerPoint | 1.1 / 0.9 |
| slide-content | MATCHES | As the UI | 0.9 / 1.1 |
| slide-cover | MATCHES | As the UI | 2.3 / 1.7 |
| slide-data-table | DEFECT | D5: square header corners and no wrapper shadow, in both apps. D7: header seams in PowerPoint | 0.8 / 1.1 |
| slide-event-cover | MATCHES | As the UI. The tracked 64 px title is about +7 px in PowerPoint and −5 px in Google (glyph extent) | 1.5 / 1.4 |
| slide-executive-summary | MATCHES | As the UI. The highest PowerPoint score of the corpus is X1 summed over its 15 lines | 1.0 / 0.9 |
| slide-industry-title | MATCHES | As the UI, the photo capture included | 1.5 / 1.9 |
| slide-journey | MATCHES | As the UI | 1.0 / 1.1 |
| slide-kpi-dashboard | MATCHES | As the UI. The `--shadow-sm` second layer (D4) and the ▲ fallback (D8) are present but not visible at this size | 1.0 / 1.3 |
| slide-lakehouse-blueprint | MATCHES | As the UI (65 lines of dense diagram) | 1.0 / 0.7 |
| slide-medallion | MATCHES | As the UI | 1.0 / 0.9 |
| slide-milestones | MATCHES | As the UI | 0.6 / 1.1 |
| slide-reference-architecture | DEFECT | D1: the italic caption (+32 px, PowerPoint) | 1.2 / 0.7 |
| slide-section | DEFECT | D8: the non-breaking hyphens in the title are drawn from MS PGothic in Google, 29 px short | 1.1 / 1.5 |
| slide-statement | MATCHES | As the UI | 0.9 / 1.2 |
| slide-stats | MATCHES | As the UI | 1.3 / 1.8 |
| slide-three-cards | DEFECT | D4: card shadows are 6 px instead of the UI's 26 px tail, in both apps | 0.5 / 1.1 |
| slide-timeline | MATCHES | As the UI | 0.4 / 1.1 |
| slide-two-column | MATCHES | As the UI | 0.9 / 1.1 |
| slide-waterfall | DEFECT | D1: the italic caption (+21 px, PowerPoint) | 1.1 / 0.9 |

### Carry-over items

| Item | Verdict |
|---|---|
| Task 1: unbordered shapes write `<a:ln></a:ln>` | **No default outline.** 222 (corpus) and 432 (design system) such shapes. Google reports every one as an unrendered outline (Slides API), and no PowerPoint render shows one |
| Task 2: justified text plus slack may stretch in PowerPoint | **No stretch.** Neither corpus has `text-align: justify`. A probe paragraph exports `algn="l"` with the browser's four breaks, so nothing can stretch. The UI's flush right edge is not reproduced, by the Task 4 A3 ruling |
| Task 2: `<a:pPr>` after every `<a:br/>` | **No repair prompt.** Every `<a:br>` in both decks (7 and 15) is followed by `<a:pPr>`. PowerPoint opened all seven decks (after, before, three probe decks) and saved them to PDF unattended; a repair dialog would have blocked the script |
| Task 4: DM Sans italic heavier in PowerPoint | **Cause found: D1.** PowerPoint uses Bold Italic (the PDF embeds `DMSans-BoldItalic`). The fix is target-specific and needs a PowerPoint probe of the font namings, so it is Phase B |
| Task 5: `a<br> <br>b` may drop the blank line | **Kept.** The browser draws three lines (box 100.8 px = 3 × 33.6). The export writes `alpha`, a blank paragraph and `bravo`, identical to `a<br><br>b` |
| Task 7: dark PowerPoint gridlines in the harness PNG | **Harness artefact (H1).** The PDF raster through Quartz matches the UI. Method: MuPDF at 4× (5120 px) box-filtered to 1280×720, which also clears the logo-mark fringe. Means: corpus 3.27 → 3.22, design system 2.69 → 2.62. Adopt in `run.py` in Phase B |
| PowerPoint seams between filled cells | **Real in PowerPoint's PDF: D7.** Visible under Quartz too (not only MuPDF), and gone when the grid is snapped to whole px. PowerPoint's own window could not be captured: this session has no Screen Recording permission (`screencapture` cannot create an image), and PowerPoint's AppleScript "save as PNG/JPG" writes no files. The owner can confirm on screen: kept in-repo deck, slide 5, zoom 100 % |
| Mixed-size paragraph-spacing residuals (−1.68 / −3.63 / −2.62 px; half-leading) | **Not visible in the corpora.** Worst baseline offset of any matched line is 2.3 px in PowerPoint and 1.9 px in Google; the largest are the first lines of 60–88 px display text. No fix proposed from the corpora; the Task 15 decks are re-checked |
| Form-control text (`select`, `input`, `textarea`) | **None in either corpus.** Real decks are checked in Task 15 |

### Rulings and corrections from this verification

- **Correction (Task 10 ruling):** the table seams are not a MuPDF-only artefact. Apple's Quartz
  draws them from PowerPoint's PDF too, and snapping the grid to whole px removes them (D7).
- **Correction (Task 4 numbers):** PowerPoint is up to 1.8 % wider, not "up to +0.78 %"
  (X1). The `kern` attribute plays no part: PowerPoint for Mac does not kern DM Sans at all.
- **Ruling:** the design-system corpus pins its own Google files, not the in-repo corpus's.
  The two DM Sans files differ by 9 % in a 48 px title's width, and the truth must stay the
  owner's UI.
- **Ruling:** the "before" and "after" runs share one UI reference, the branch's
  `build_slide_html` truth. That is the UI the user sees: main's document wipes a
  script-drawn canvas the UI preview keeps (corpus 17).
- **Note:** the line-placement widths of letter-spaced lines include one trailing letter
  space on the browser side (a Range rect holds the spacing; a PDF glyph box does not).
  The event-cover figures above are corrected for it.

### Google Slides decks kept for the owner

- In-repo corpus (17 slides): https://docs.google.com/presentation/d/1Bsb0-izV34VDKCBGOM6YDrqJmqRVIQ7YgTvVGC4zvXw/edit
- Design-system corpus (27 slides): https://docs.google.com/presentation/d/10V2fOXlYx6o_pSo8j7qGfTWrk-Zs-dkD6QyhEHSSMKw/edit

The two legacy-run presentations were deleted by id and confirmed gone (`files.get` 404):
`1oGYCOUgeocQVgxwx7cOBuenpHY083fqTby2D9ly9U70` and `1cguwomh9alx4rG4dE_iB8KBCNsFUZBnJKbVLxYcFFDE`.

## Phase B, batch B1: typography (D1, X1, D8), engine `41e4bc2e`

Commits: `996e7dc6` D1, `b06e50ad` X1, `41e4bc2e` D8. The measurements, and the probes behind
each decision, are in `scripts/export_fidelity/CALIBRATION.md` (D1, X1, D8). Both corpora were
re-run with `run.py --pin-fonts --powerpoint --gslides`; the baseline is a fresh run at
`07fee925`, identical to Phase A's on every slide in both apps (no run-to-run noise).

### Scores, baseline (`07fee925`) → B1 (`41e4bc2e`)

In-repo corpus (17 slides):

| Slide | PowerPoint | Google |
|---|---|---|
| 01-cover-gradient-svg-art | 4.35 → 3.35 | 2.82 → 2.82 |
| 02-agenda-grid-rules | 1.74 → 1.23 | 1.78 → 1.78 |
| 03-svg-combo-chart-legend-callout | 4.13 → 2.28 | 2.67 → 2.67 |
| 04-harvey-table-caption | 4.39 → 2.36 | 2.97 → 2.97 |
| 05-balance-sheet-two-tables | 2.91 → 2.26 | 1.80 → 1.80 |
| 06-delta-pills-table-callout | 4.17 → 2.02 | 2.72 → 2.72 |
| 07-timeline-dots-mono-dates | 4.69 → 2.58 | 2.57 → 2.57 |
| 08-kpi-cards-grid | 3.88 → 2.16 | 3.26 → 3.26 |
| 09-pseudo-bullets-accent-quote | 4.67 → 2.02 | 3.55 → 3.55 |
| 10-svg-waterfall | 2.49 → 1.51 | 2.13 → 2.13 |
| 11-chartjs-canvas | 2.07 → 1.13 | 1.63 → 1.63 |
| 12-progress-bars-icons | 1.87 → 1.44 | 1.96 → 1.96 |
| 13-code-gradtext-rotated | 2.31 → 1.60 | 1.82 → 1.82 |
| 14-two-col-text-image-overlap | 2.51 → 1.86 | 2.15 → 2.15 |
| 15-dense-table-badges-zebra | 3.13 → 1.72 | 2.56 → 2.56 |
| 16-closing-cta | 3.09 → 1.57 | 1.59 → 1.59 |
| 17-mixed-content-hidden-graphics | 3.13 → 1.58 | 2.79 → 2.79 |
| **mean** | **3.27 → 1.92** | **2.40 → 2.40** |

Design-system corpus (27 slides):

| Slide | PowerPoint | Google |
|---|---|---|
| slide-2x2-matrix | 3.64 → 2.21 | 1.75 → 1.75 |
| slide-action-title | 3.42 → 1.59 | 2.27 → 2.27 |
| slide-agenda | 2.09 → 0.84 | 0.96 → 0.96 |
| slide-azure-flow-example | 2.08 → 1.67 | 1.34 → 1.34 |
| slide-bold-title | 3.18 → 1.63 | 1.43 → 1.43 |
| slide-charts | 1.35 → 0.97 | 0.83 → 0.83 |
| slide-closing | 1.11 → 0.92 | 0.71 → 0.71 |
| slide-comparison | 2.44 → 1.36 | 1.50 → 1.50 |
| slide-content | 4.21 → 2.22 | 1.75 → 1.75 |
| slide-cover | 2.75 → 2.46 | 1.83 → 1.83 |
| slide-data-table | 2.35 → 2.13 | 1.19 → 1.19 |
| slide-event-cover | 3.88 → 2.03 | 1.27 → 1.27 |
| slide-executive-summary | 6.33 → 3.97 | 2.58 → 2.59 |
| slide-industry-title | 3.85 → 2.39 | 2.93 → 2.93 |
| slide-journey | 1.51 → 1.21 | 0.75 → 0.75 |
| slide-kpi-dashboard | 3.00 → 2.23 | 1.95 → 1.95 |
| slide-lakehouse-blueprint | 3.24 → 2.73 | 2.05 → 2.05 |
| slide-medallion | 3.49 → 1.78 | 1.96 → 1.96 |
| slide-milestones | 1.47 → 1.18 | 0.86 → 0.86 |
| slide-reference-architecture | 2.78 → 1.97 | 1.95 → 1.96 |
| slide-section | 1.29 → 0.90 | 2.31 → 1.38 |
| slide-statement | 3.77 → 1.62 | 2.39 → 2.39 |
| slide-stats | 1.32 → 1.09 | 1.09 → 1.09 |
| slide-three-cards | 2.19 → 1.50 | 1.17 → 1.17 |
| slide-timeline | 0.70 → 0.61 | 0.82 → 0.82 |
| slide-two-column | 2.84 → 1.84 | 1.44 → 1.44 |
| slide-waterfall | 2.46 → 1.51 | 1.15 → 1.15 |
| **mean** | **2.69 → 1.72** | **1.56 → 1.53** |

No slide is worse in either app (the largest rise is +0.01, two Google slides). Every
PowerPoint slide improves. The Google deck changes only where D8 writes something else
(U+2011, →): `slide-section` 2.31 → 1.38. No text loss, no MODEL DROPS, in both corpora.

### D1: italic is drawn as Bold Italic in PowerPoint

| | Before | After |
|---|---|---|
| Italic glyphs in PowerPoint's PDF | DMSans-BoldItalic (258 in-repo, 364 design system) | DMSans-Italic (258; 358 + 3 arrows in Arial Italic) |
| Italic line width, the 10 slides (PowerPoint) | +1.5 to +41.9 px (every caption +14.8 or more) | −1.7 to +2.1 px |
| Google | DMSans-Italic | unchanged |

The deck for PowerPoint writes `<family> [Weight ]Italic` with italic off, and 700 as the family
plus bold and italic. The deck for Google keeps the family plus italic.

### X1: PowerPoint kerns no DM Sans

PowerPoint line width minus the browser's, px, upright lines (the browser's width less the
trailing letter space its Range rect holds):

| Corpus | Median | Median of \|error\| | Largest \|error\| |
|---|---|---|---|
| in-repo, before | +0.56 | 0.60 | 15.99 |
| in-repo, after | +0.16 | 0.23 | 2.73 |
| design system, before | +0.76 | 0.79 | 11.14 |
| design system, after | +0.16 | 0.30 | 3.34 |

Over all lines, italic included, the largest error goes from 41.86 to 2.73 px (in-repo) and from
37.57 to 3.34 px (design system). An A/B before D8 kept A1's 0.5 % band for PowerPoint: +0.19 /
0.27 / 4.32 in-repo against +0.16 / 0.23 / 2.73 without, and +0.15 / 0.30 / 3.32 both ways on
the design system, so the band is dropped for PowerPoint. Google's line widths are unchanged.

### D8: characters a webfont lacks

| | PowerPoint before → after | Google before → after |
|---|---|---|
| ▲▼ in DM Sans | Times New Roman → Arial | Arial → Arial |
| → in DM Sans | DM Sans (0.78 em) → Arial (1.00 em, the browser's 1.00) | DM Sans → Arial |
| ▲▼ in DM Mono | Courier New → Courier New | Courier New → Courier New |
| "end‑to‑end" (U+2011), 64 px, `slide-section` | +0.81 → −0.04 px | −30.05 px (MS PGothic) → +0.62 px |

Both apps now draw the same face for every such character. Arial's ▲ is 0.69 em tall, the
browser's Hiragino Sans 0.90 em: the nearest the three apps share.

### Rulings and corrections from B1

- **Ruling (D1):** the italic static's name, italic off, is right for both static
  conventions: DM Sans's own-family italics, and RIBBI families such as DM Mono, whose
  `DM Mono Italic` PowerPoint resolves to DMMono-Italic, pixel-identical to `DM Mono` plus
  italic. Italic on slants DM Sans Italic twice. With a variable install, PowerPoint for Mac
  resolves only each file's default instance (`DM Sans 9pt`), so the deck's family does not
  resolve at all and cannot decide the naming.
- **Correction (D8, the brief):** Google draws U+2010 from MS PGothic too, so the deck for
  Google writes U+2011 as U+002D, the face's own hyphen, not as U+2010. PowerPoint draws U+2011
  as the face's hyphen-minus (269.20 px against 269.19 for U+002D) and U+2010 from Cambria
  Math, so the deck for PowerPoint writes U+2010 as U+002D and keeps U+2011. The harness's
  text-loss check reads a hyphen as U+002D.
- **Ruling (D8):** the fallback face is the run's generic family's of Arial, Times New Roman
  and Courier New, which cover WGL4 in all three apps. Which characters a webfont lacks is
  read with a generated coverage probe font (`coverage_font.mjs`), the same on Linux Chromium
  as on a Mac; a family the page did not load is not read.
- **Ruling (X1):** a run's kerning is spread over n − 1 gaps when it ends its line, and n
  when another run follows it there. PowerPoint puts `spc` after every character, the last
  included (measured), and kerns Arial and Times New Roman unless `kern="0"`, which pptxgenjs
  writes with every `spc`.
- **Superseded (R11j′):** a deck with no script run is no longer the same for both targets.
  Tracking, italic naming and the hyphens are written per target; the cross-target tests take
  them out as they take out script sizes.
- **Owner check:** PowerPoint for Windows was not probed: the italic static's name for a RIBBI
  family, and `kern="0"` turning DM Sans kerning off, are measured on PowerPoint for Mac only.
- **Owner-facing note:** the PowerPoint download names an italic `DM Sans Italic`, which Google
  draws as Sansita. A user who uploads the downloaded .pptx to Drive by hand, rather than using
  the Google Slides export, gets the wrong italic face there.
- **Owner-facing note:** the Google Slides deck writes U+2011 as U+002D, so text copied out of
  it carries a plain hyphen, which a line may break after.

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/1PANCNIzpLm4c1qai-ByRBz_yto1XOInLIG6D8JAKBvs/edit
- Design-system corpus: https://docs.google.com/presentation/d/1qRod10oTAgRFDT-9hp3xgzCbHkcJUO91YGyGUx3S8Kg/edit

The baseline and probe presentations were deleted by id and confirmed gone (`files.get` 404):
`1s4GvZG0BsB7mOQvTyJfkA2X5UjCB61EsjCDvPcl2Tt8`, `18qHrxBxjZSV9JDzWIZzNr2tXT2XhyxS_cmzTw5jV9hg`
and `1ojKjuEjNudBDuhf_7gabGK9r71FC88nISm9nIXo8auM`.

## Phase B, batch B2: shapes and effects (D2, D4, D5, D6), engine `d661ee70`

Commits: `d476cb70` box-shadow layers and rings (D2, D4, D5's unfilled-box shadows),
`9c606b1c` table corners in a rounded clip (D5), `d661ee70` dotted borders for Google (D6). The
app probes behind each decision are in `scripts/export_fidelity/CALIBRATION.md` (D4 and D5, D6).
Both corpora were re-run with `run.py --pin-fonts --powerpoint --gslides`; the baseline is a
fresh run at `ef9f316c`, identical to B1's final run on every slide in both apps.

### Scores, baseline (`ef9f316c`) → B2 (`d661ee70`)

In-repo corpus (17 slides): both decks are byte-identical to the baseline's on every slide (no
slide holds a multi-layer or unfilled shadow, a translucent ring, a dotted border or a table in
a rounded clip), and every score is the same to the hundredth: PowerPoint mean 1.92, Google 2.40.

Design-system corpus (27 slides; the defect a slide's change is for):

| Slide | Defect | PowerPoint | Google |
|---|---|---|---|
| slide-2x2-matrix | D2 | 2.21 → 2.19 | 1.75 → 1.73 |
| slide-action-title |  | 1.59 → 1.59 | 2.27 → 2.27 |
| slide-agenda |  | 0.84 → 0.84 | 0.96 → 0.96 |
| slide-azure-flow-example | D6 | 1.67 → 1.67 | 1.34 → 1.25 |
| slide-bold-title |  | 1.63 → 1.63 | 1.43 → 1.43 |
| slide-charts |  | 0.97 → 0.97 | 0.83 → 0.83 |
| slide-closing |  | 0.92 → 0.92 | 0.71 → 0.71 |
| slide-comparison |  | 1.36 → 1.36 | 1.50 → 1.50 |
| slide-content |  | 2.22 → 2.22 | 1.75 → 1.75 |
| slide-cover |  | 2.46 → 2.46 | 1.83 → 1.83 |
| slide-data-table | D5 | 2.13 → 2.10 | 1.19 → 1.17 |
| slide-event-cover |  | 2.03 → 2.03 | 1.27 → 1.27 |
| slide-executive-summary |  | 3.97 → 3.97 | 2.59 → 2.59 |
| slide-industry-title |  | 2.39 → 2.39 | 2.93 → 2.93 |
| slide-journey |  | 1.21 → 1.21 | 0.75 → 0.75 |
| slide-kpi-dashboard | D4 | 2.23 → 2.21 | 1.95 → 1.93 |
| slide-lakehouse-blueprint |  | 2.73 → 2.73 | 2.05 → 2.05 |
| slide-medallion | D4, D5 | 1.78 → 1.77 | 1.96 → 1.93 |
| slide-milestones |  | 1.18 → 1.18 | 0.86 → 0.86 |
| slide-reference-architecture |  | 1.97 → 1.97 | 1.96 → 1.96 |
| slide-section |  | 0.90 → 0.90 | 1.38 → 1.38 |
| slide-statement |  | 1.62 → 1.62 | 2.39 → 2.39 |
| slide-stats |  | 1.09 → 1.09 | 1.09 → 1.09 |
| slide-three-cards | D4 | 1.50 → 1.31 | 1.17 → 0.99 |
| slide-timeline |  | 0.61 → 0.61 | 0.82 → 0.82 |
| slide-two-column |  | 1.84 → 1.84 | 1.44 → 1.44 |
| slide-waterfall |  | 1.51 → 1.51 | 1.15 → 1.15 |
| **mean** | | **1.72 → 1.71** | **1.53 → 1.52** |

Only the six slides tagged change, in either deck. No slide is worse in either app; every
changed slide improves in both. No text loss, no MODEL DROPS, no export or capture failures, in
both corpora and both targets.

### What was measured on each defect (UI / PowerPoint / Google, at 1280 px)

| Defect | Measure | UI | Before | After |
|---|---|---|---|---|
| D2 `slide-2x2-matrix` dot | solid dot, then pale ring, px across its middle | 14 / 8 | 18 / 4, 18 / 4 | 14 / 8, 13 / 9 |
| D4 `slide-three-cards` card | shadow tail below the card (to < 1 level) | 26 px | 5, 5 px | 21, 18 px |
| D4 | the same, darkening summed over 60 px | 176 | 27, 28 | 160, 142 |
| D5 `slide-data-table` header | coral px outside the two top corner arcs | 0 | 12, 12 | 0, 0 |
| D5 wrapper | shadow below the wrapper (≥ 0.5 level), summed | 4 px, 33 | 0 px, 0 | 3 px 26, 2 px 23 |
| D6 `slide-azure-flow-example` | dot period of the dotted separators | 4.00 px | 4.00, 8.00 px | 4.00, 4.00 px |
| D6 | dot centre, px past a period | 0.50 | 1.34, 5.58 (of 8) | 1.34, 0.41 |

`slide-kpi-dashboard` (five `--shadow-sm` cards) and `slide-medallion` (an unfilled, bordered
`--shadow-sm` frame, whose outline cast a thin offset shadow of itself before) improve by 0.01
to 0.03 in each app.

### Rulings and corrections from B2

- **Ruling (D4, D5):** a shadow layer the box's own shape cannot carry is a *shadow shape*
  under the box: its border box (shrunk by a negative spread), unoutlined, named "Shadow" in the
  selection pane, filled opaque, since both apps scale a shape's shadow by its fill's alpha and
  cast none from an unfilled shape. Its fill is the box's own colour under an opaque box, else
  the one colour the export paints beneath it; where no one colour does, the shapes are dropped
  and the box keeps its first layer, as before. The box stays on top, so a click selects the
  box; a shadow shape is reached through the selection pane. pptxgenjs writes no groups, so the
  shapes are ordered under the box, not grouped with it (what a moved box leaves behind: the
  owner-facing notes and the owner decision below).
- **Ruling (D4, fix round 1):** a ring listed before the first shadow (Tailwind's ring, then
  shadow) paints over that shadow, so when such a ring is a shape of its own the box carries no
  shadow and every shadow layer is a shadow shape, in CSS order. An opaque ring that is the box's
  outline is drawn with the box, over its shadow, and changes nothing.
- **Ruling (D5):** a rounded overflow clip is carried with the clip (`rounds`); a native table
  leaves a cell a rounded corner cuts unfilled and draws its fill as a custom shape under the
  table, cut to the corner. The table stays native and every cell keeps its text.
- **Correction (D6, the brief):** no dash Drive offers is a 1:1 dot. It converts `sysDot` and
  `dot` alike to DOT, one width on and three off, and every `custDash` to DASH_DOT. The deck for
  Google draws a dotted border as one custom shape holding its centre line twice, the second pass
  two widths along, run back from the right or bottom end, where Chrome lays its dots from.
- **Correction (Phase A, azure-flow):** `slide-azure-flow-example` renders no element with a
  box-shadow, so Phase A's D4 note on it was mistaken; its D6 separators are its B2 change.
- **Not changed:** a positive spread on a blurred layer is still not drawn (an outer shadow has
  none, and a grown shadow shape would show). A dotted table-cell border is still written dashed
  (pptxgenjs's table borders are solid or dashed). The deck for PowerPoint runs dotted lines from
  their start, so its dots sit 0.8 px off Chrome's; its spacing is right.
- **Limits (D5):** a corner cell's own outer border, written on its `a:tc`, still draws square
  past the wrapper's arc (an `a:tc` border cannot be clipped; the data table has none). A
  `<table>`'s own background shape (its fill, radius and shadow under the frame) does not read
  the clip's `rounds`: carried to B3, with D3, which clips shapes to a rounded clip.
- **Harness note:** one Google conversion (the in-repo deck, in the first after-run) drew every
  slide's text wider and lower, scoring 1.5 worse on average, although its deck was byte-identical
  to the baseline's. Converting the same file again reproduced the baseline on all 17 slides to
  the hundredth, and so did the final run. A Google regression on an unchanged deck is the
  conversion, not the export: re-convert before reading it as one.
- **Owner-facing notes (what a moved object leaves behind):**
  - A card's text and its box were already separate objects before B2: moving the box alone
    has always left its text in place.
  - A card with a two-layer shadow (every design-system `--shadow-md` and `--shadow-sm` card)
    has, under its box, a shadow shape that is an **opaque copy of the card's own shape, in the
    card's own colour, casting the soft shadow**. Moving the card alone leaves that copy behind,
    a visible ghost card where the card was. Select the card and its "Shadow" together (or
    delete the "Shadow") to move it cleanly.
  - An unfilled box's shadow shapes (the data table's wrapper, the medallion frame) are opaque
    copies of its shape in the slide's colour beneath, casting its shadow; they stay behind too.
  - A moved data table leaves behind its rounded corner pieces (coral above, white below),
    while its own corner cells, unfilled, move with it and show what is beneath them.
  - In the Google deck a dotted border is a freeform stroke, which moves and recolours whole
    but is not a preset line; a dotted box's border is a stroke separate from its box.

### Owner decision: how a box's extra shadow layers are written

| Option | What a moved card leaves | Shadow tail below a `--shadow-md` card (`slide-three-cards`), PowerPoint / Google | Summed darkening, PowerPoint / Google |
|---|---|---|---|
| UI | | 26 px | 176 |
| before B2 (first layer only) | nothing | 5 / 5 px | 27 / 28 |
| **(a)** separate shadow shapes (as built) | an opaque ghost of the card, with its shadow | 21 / 18 px | 160 / 142 |
| **(b)** one fitted shadow per box, no extra shapes (measured, not built) | nothing | 16 / 14 px | 146 / 141 |
| **(c)** (a), grouped with its box by post-processing into `p:grpSp` (not built) | nothing: the group moves whole | as (a) | as (a) |

- **(a)** keeps every layer: the closest look, and one more shape per extra layer.
- **(b)** is the one layer closest, by least squares over the profile below and beside the box,
  to the two layers' composite in CSS's box-shadow model: `0 5px 15px rgba(27,49,57,.14)` for
  `--shadow-md`. It needs no extra shapes, and its tail is 5 px (PowerPoint) and 4 px (Google)
  shorter than (a)'s. Slide scores, (a) against (b) rendered together: PowerPoint 1.31 / 1.33,
  Google 1.04 / 1.04. An unfilled box would still need (a)'s filled shape to cast at all.
- **(c)** groups each box with its shadow shapes, written after pptxgenjs (which writes no
  groups). A larger variant would group each card's pieces together, its text included. A
  click then selects the group first, and a second click its part.

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/1t2y0ty0JiPIsz-sLSgAM__1X2ybiA25Ct98x4nFRYkw/edit
- Design-system corpus: https://docs.google.com/presentation/d/1U4LrQh0t8VcmOsAsdoFPeHOWTVin4nw5Ys0mUsDKC4s/edit

The baseline, first-run, re-conversion and probe presentations were deleted by id and
confirmed gone (`files.get` 404).

## Phase B, batch B3: clipping, tables and the slide root's image ground (D3, D7, D9, D10), engine `6733070c`

Commits:
- `e468466f` table grid lines on whole px (D7, first form);
- `c0ca9dbe` what a rounded overflow box clips is cut to its round corners (D3, with the table's own
  background);
- `345a2849` a slide root's image ground is the slide's background picture (D9);
- `fd473854` dotted table-cell borders written `sysDot` (D10);
- `6733070c` the grid's rules kept crisp, the whole-px grid for the PowerPoint deck alone (D7, as
  built).

The app probes behind each decision are in `scripts/export_fidelity/CALIBRATION.md` (D10, D7).
Both corpora were re-run with `run.py --pin-fonts --powerpoint --gslides`; the baseline is a
fresh run at `3066f801`, identical to B2's final run on every slide in both apps.

### Scores, baseline (`3066f801`) → B3 (`6733070c`)

In-repo corpus (17 slides). The PowerPoint deck changes on its four native-table slides alone
(D7); every slide's XML in the Google deck is byte-identical to the baseline's.

| Slide | Defect | PowerPoint | Google |
|---|---|---|---|
| 04-harvey-table-caption | D7 | 2.36 → 2.13 | 2.97 → 2.97 |
| 05-balance-sheet-two-tables | D7 | 2.26 → 2.00 | 1.80 → 1.80 |
| 06-delta-pills-table-callout | D7 | 2.02 → 1.88 | 2.72 → 2.72 |
| 15-dense-table-badges-zebra | D7 | 1.72 → 1.38 | 2.56 → 2.56 |
| the other 13 slides | | unchanged to the hundredth | unchanged |
| **mean** | | **1.92 → 1.86** | **2.40 → 2.40** |

Design-system corpus (27 slides):

| Slide | Defect | PowerPoint | Google |
|---|---|---|---|
| slide-2x2-matrix |  | 2.19 → 2.19 | 1.73 → 1.73 |
| slide-action-title |  | 1.59 → 1.59 | 2.27 → 2.27 |
| slide-agenda |  | 0.84 → 0.84 | 0.96 → 0.96 |
| slide-azure-flow-example |  | 1.67 → 1.67 | 1.25 → 1.25 |
| slide-bold-title |  | 1.63 → 1.63 | 1.43 → 1.43 |
| slide-charts |  | 0.97 → 0.97 | 0.83 → 0.83 |
| slide-closing |  | 0.92 → 0.92 | 0.71 → 0.71 |
| slide-comparison | D3, D7 | 1.36 → 1.25 | 1.50 → 1.44 |
| slide-content |  | 2.22 → 2.22 | 1.75 → 1.75 |
| slide-cover |  | 2.46 → 2.46 | 1.83 → 1.83 |
| slide-data-table | D7 | 2.10 → 1.99 | 1.17 → 1.17 |
| slide-event-cover |  | 2.03 → 2.03 | 1.27 → 1.27 |
| slide-executive-summary |  | 3.97 → 3.97 | 2.59 → 2.59 |
| slide-industry-title |  | 2.39 → 2.39 | 2.93 → 2.93 |
| slide-journey |  | 1.21 → 1.21 | 0.75 → 0.75 |
| slide-kpi-dashboard |  | 2.21 → 2.21 | 1.93 → 1.93 |
| slide-lakehouse-blueprint | D3 | 2.73 → 2.72 | 2.05 → 2.04 |
| slide-medallion | D3 | 1.77 → 1.77 | 1.93 → 1.93 |
| slide-milestones |  | 1.18 → 1.18 | 0.86 → 0.86 |
| slide-reference-architecture |  | 1.97 → 1.97 | 1.96 → 1.96 |
| slide-section |  | 0.90 → 0.90 | 1.38 → 1.38 |
| slide-statement |  | 1.62 → 1.62 | 2.39 → 2.39 |
| slide-stats |  | 1.09 → 1.09 | 1.09 → 1.09 |
| slide-three-cards |  | 1.31 → 1.31 | 0.99 → 0.99 |
| slide-timeline |  | 0.61 → 0.61 | 0.82 → 0.82 |
| slide-two-column |  | 1.84 → 1.84 | 1.44 → 1.44 |
| slide-waterfall |  | 1.51 → 1.51 | 1.15 → 1.15 |
| **mean** | | **1.71 → 1.71** | **1.52 → 1.51** |

Only the slides tagged change, in either deck (in the Google deck only those D3 touches). No slide is worse in either app. No text
loss, no MODEL DROPS, no export or capture failures, in both corpora and both targets. Neither
corpus has a slide root painting an image or a dotted table border, so D9 and D10 are measured
on probe decks below.

**D9's probe corpus** (four slides: a `.slide` root painting a banded 400 px square `center /
cover` over black; a photo `center / cover` under a scrim gradient; a `<section>` root
painting the bands `right / contain` over 123456; the bands `contain` on a root with no colour,
body 2B0D08), the same harness against the baseline engine:

| Slide | PowerPoint | Google |
|---|---|---|
| 01 cover | 106.05 → 0.25 | 106.07 → 0.32 |
| 02 photo under a scrim | 55.21 → 0.64 | 55.26 → 0.61 |
| 03 contain, section root | 47.40 → 0.33 | 47.46 → 0.42 |
| 04 contain, body's colour beside it | 59.66 → 0.33 | 59.00 → 0.44 |

### What was measured on each defect (UI / PowerPoint / Google, at 1280 px)

| Defect | Measure | UI | Before | After |
|---|---|---|---|---|
| D3 `slide-comparison` | navy px outside the 19 Harvey balls' circles | 0 | 64, 46 | 0, 0 |
| D3 `slide-medallion` | tile px outside the frame's 12 px corner arcs (bottom left + bottom right) | 0 + 0 | 6 + 6, 6 + 6 | 0 + 0, 0 + 0 |
| D7 corpus 05 | seam pixel columns in PowerPoint's PDF, MuPDF / Quartz (8 interior lines in filled rows) | | 8 / 6 | 0 / 0 |
| D7 corpus 15 | the same (16 lines) | | 6 / 8 | 0 / 0 |
| D7 `slide-data-table` | the same (20 lines) | | 1 / 1 | 0 / 0 |
| D7 | worst stray from the fill beside a line, levels | | 53 to 55 | 0 to 1 |
| D7 corpus 05 | its 1 px rule at 403 px, down x = 300 | DCE0E2 on one row | two blended rows | DCE0E2 on one row |
| D9 cover | the ground's band edges down x = 1100 | 40, 680 | none (solid 000000) | 40, 680; 40, 680 |
| D9 contain | the letterbox edge across y = 250; the band edges | 560; 180, 360, 540 | none (solid 123456) | the same, both apps |
| D9 contain on body | the image's left and right edges across y = 450 | 280, 1000 | none (solid 2B0D08) | 280, 1000, both apps |
| D10 2 px dotted cell rule (probe deck) | dash / period | 2 / 4 px | PowerPoint 6 / 8 px, Google 8 / 14 px | PowerPoint 2 / 4 px, Google 2 / 8 px |

D3 and D7 meet in `slide-comparison` (its Harvey balls, and its native table), in
`slide-lakehouse-blueprint` (its rounded lanes, 12 paths cut to their corners) and in
`slide-data-table`'s PowerPoint deck (its grid; its corner pieces now meet the grid on whole
px). `slide-medallion`'s corners are right in both apps and score the same to the hundredth.

### Rulings and corrections from B3

- **Ruling (D3):** what an overflow box's round corners clip is cut to them with the existing
  custom-geometry clip, not captured: a shape's fill and outline (the outline open along the
  cut), a side line (ending where its centre line meets the arc), a native table's corner cells
  and its own background; a raster picture they cut is captured, cut as the browser cuts it.
  Text is never cut and stays native. This covers what the brief's capture alternative would
  have (a Harvey ball) and what it could not (a card's header band, which holds text).
- **Ruling (D7, measured):** the whole-px grid is the PowerPoint deck's alone, and a grid line
  lies where Chrome paints its border. The first form (`e468466f`), every line on the nearest
  whole px, cleared the seams but blurred each 1 px rule over two pixel rows (corpus 05,
  PowerPoint 2.26 → 2.41), and cost Google Slides, which drew no seam and shows no CSS px as a
  whole pixel in any view (its thumbnails are 1.25 px to one): `slide-data-table` 1.17 → 1.57,
  corpus 05 1.80 → 2.17. As built, a line's border starts on the whole px nearest the
  browser's (a line with no border lies on that px, a 1 px rule half a px past it); the deck
  for Google keeps the browser's grid. The snapshot is told the renderer for this one
  construct (R11g: a renderer-specific construct, chosen by measurement).
- **Ruling (D7):** the margins are measured from the snapped lines, so each cell's text stays
  where the browser set it; the corpus 05 margin test now measures from the browser's cell
  edge, as its rule (padding plus half the collapsed border, where the browser puts the
  content) says. The table's own box and the rounded boxes that cut its corner cells are
  snapped with the grid, so a grid line snapped past a wrapper's edge by a part of a px still
  lies on it.
- **Correction (B2, concern 5):** the faint row at a Google corner shape's top edge is not the
  seam family whole-px snapping fixes: Google shows no CSS px as a whole pixel, so its deck is
  left as it was.
- **Ruling (D9):** a slide root whose ground holds a `data:` image is the slide's `<p:bg>`
  picture: one *ground* capture of the whole slide as the browser paints it under the root's
  border and content (html, body and the white canvas kept, everything else hidden), each layer
  at its own size, position and repeat; the root's border is native over it, and its colour,
  copied to body (`bgTransferred: "image"`), is the fallback when the capture fails. A probe:
  Chrome paints html's ground (body's, when html has none) on the canvas whatever their
  visibility, but body's own ground under html's only when body shows, so both show in the
  ground capture.
- **Finding (D9, the legacy engine, measured on the test slides at `origin/main`):** a `div`
  root's `url()` ground became a nested `<img>` (`replaceBackgroundImageWithImg`), exported as
  a selectable picture item stretched to the slide (the 400 px square at 1280 × 720, no crop),
  over a slide-sized black shape and a solid `<p:bg>`; a photo under a scrim gradient became
  the gradient's first colour, the photo lost; a `<section>` root's image was lost.
- **Ruling (D10):** a dotted table-cell border is `sysDot` in both decks. pptxgenjs writes a
  table border only solid or `sysDash`, so the dotted sides are written dashed and their
  `prstDash` rewritten once the deck is written (`emit_table.cjs dotTableBorders`, with the
  zip library pptxgenjs writes with; a deck with none is written as before). Measured:
  PowerPoint draws `sysDot` as CSS's 1:1 dot; Drive converts `sysDot` and `dot` alike to its
  DOT, one on and three off.
- **Not done (D10, why):** D6's two-pass stroke cannot be a cell border. A cell border is one
  `a:ln` in `a:tcPr`, a preset or custom dash and nothing more, and Drive converts every
  `custDash` to DASH_DOT, so Google draws a dotted cell rule at twice CSS's period, its DOT, the
  nearest its tables have (before: a dash).
- **Limits:** a corner cell's own outer border still draws square past the wrapper's arc (B2's
  limit stands); a clipped shape's shadow still falls along the cut (Task 6); a rounded clip
  cuts no text. MuPDF's 1× raster of PowerPoint's PDF bleeds about 13 % across a fill edge that
  lies exactly on a pixel (corpus 05's header, row 183), where Quartz and the UI show none: the
  H1 family B4 addresses.
- **Owner-facing notes:**
  - A slide whose root paints a photo or pattern now exports it as the slide's background
    picture: it is not selectable or movable (Format Background in PowerPoint, Change
    background in Google Slides), as a slide ground should be; its colour, its border and the
    text over it stay native.
  - A Harvey ball's fill, a card's header band and the like in a rounded clipping box are now
    freeform shapes cut to the corners: they recolour and move whole, but are no longer
    preset rectangles.
  - In the Google deck a dotted table rule is Google's dot, spaced twice as wide as the UI's.

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/1uH2AVoDJvA_xO1lv-Kq_MD0hvIZT7MsBJQs_GEVY8_g/edit
- Design-system corpus: https://docs.google.com/presentation/d/1wSqLCtwzCQktYKY9F4T2y1Ae39JS0_xQr2FSPTUmh-w/edit

The baseline, intermediate-run and probe presentations were deleted by id and confirmed gone
(`files.get` 404).


## Phase B, batch B4: the harness raster, summary.md, mixed corner radii and B3's leftovers (H1, D11), engine `bbd78cdc`

Commits:
- `c5789a80` the harness draws an app's PDF at 4×, box-filtered, and writes `summary.md` (H1);
- `c172eac3` the model check keeps a ground picture only as the slide's one ground capture (B3 Minor 5);
- `918cf0bf` a failed dotted-cell rewrite writes the deck dashed instead of failing it (B3 Minors 3 and 4);
- `3beb5dc8` a native table's own background is cut by its clip snapped with the grid (B3 Minor 1);
- `bbd78cdc` a box whose corners round by different radii keeps each corner's own (D11).

Both corpora were re-run at `bbd78cdc` with `run.py --pin-fonts --powerpoint --gslides
--baseline`. The baseline is a fresh run at `09ceb289`, identical to B3's final run on every slide
in both apps; its PowerPoint PDFs were rasterised again with the new method (`rasterise_pdf`) and
scored with the harness's own `compare`, so both sides of every table below are on one raster.

### H1: the harness's raster of PowerPoint's PDF

`rasterise_pdf` draws each page at 4× the slide (5120 × 2880) with MuPDF and box-filters it to
1280 × 720; LibreOffice's PDF is drawn the same way. Measured on the same PDFs (engine
`09ceb289`), so only the raster differs:

| PowerPoint mean | 1× (before) | 4×, box-filtered |
|---|---|---|
| in-repo corpus (17) | 1.865 | 1.824 |
| design-system corpus (27) | 1.706 | 1.615 |

Google Slides is unchanged. The new raster lowers 12 of 17 and 20 of 27 PowerPoint scores, most
on slides with pictures (`slide-data-table` −0.34, `slide-lakehouse-blueprint` −0.32, corpus 03
and 13 −0.22). It **raises** eight by more than 0.05, because of the raster alone: corpus 05
+0.14, 08 +0.10, 09 +0.12, 15 +0.13, 16 +0.17; `slide-medallion` +0.20, `slide-journey` +0.09,
`slide-executive-summary` +0.07. The rises lie at text and shape edges (edge pixels carry them:
corpus 05 +0.149 a slide pixel, flat pixels −0.002), where neither raster's anti-aliasing is
Chrome's. Against Apple's Quartz drawing the same PDF, the 4× raster is closer on 6 of 9 slides
probed and within 0.01 on the other 3, those risen included (09: 2.11 → 1.74; 16: 0.84 → 0.77;
`slide-medallion` 2.01 → 1.70). Corpus slide 03's gridline, EBEBEB on two rows in the UI: 1×
B2B2B1 and B4B4B2; 4× E9EAE9 and D0D1D0 (`scripts/export_fidelity/CALIBRATION.md` H1).

**`summary.md`** (`run.py`, every run): one row per slide with each app's score, `baseline → now`
with `--baseline`, each deck's text loss, MODEL DROPS and captures taken / failed; a mean row over
the slides both runs scored; every slide more than 0.05 worse; and a note when the baseline's
`harness.json` records another raster. The tables below are the two runs' `summary.md`, as written.

### Scores, baseline (`09ceb289`, on the new raster) → B4 (`bbd78cdc`)

All four decks (two corpora, written for PowerPoint and for Google Slides) are byte-identical to
the baseline's, slide XML and media: neither corpus holds a painted box whose corners differ
(probed in the browser: only the design system's collapsed table header cells, whose radius CSS
does not apply), or a table ground in a rounded wrapper between pixels. Every score is unchanged
to the hundredth. No text loss in either deck, no MODEL DROPS, no export or capture failures.

In-repo corpus (17 slides):

| Slide | PowerPoint | Google Slides | Text loss (pptx / gslides) | MODEL DROPS (pptx / gslides) | Captures taken / failed (pptx; gslides) |
|---|---|---|---|---|---|
| 01-cover-gradient-svg-art | 3.23 → 3.23 | 2.82 → 2.82 | none / none | 0 / 0 | 2 / 0; 2 / 0 |
| 02-agenda-grid-rules | 1.15 → 1.15 | 1.78 → 1.78 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| 03-svg-combo-chart-legend-callout | 2.06 → 2.06 | 2.67 → 2.67 | none / none | 0 / 0 | 3 / 0; 3 / 0 |
| 04-harvey-table-caption | 2.08 → 2.08 | 2.97 → 2.97 | none / none | 0 / 0 | 9 / 0; 9 / 0 |
| 05-balance-sheet-two-tables | 2.14 → 2.14 | 1.80 → 1.80 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| 06-delta-pills-table-callout | 1.75 → 1.75 | 2.72 → 2.72 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| 07-timeline-dots-mono-dates | 2.51 → 2.51 | 2.57 → 2.57 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| 08-kpi-cards-grid | 2.26 → 2.26 | 3.26 → 3.26 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| 09-pseudo-bullets-accent-quote | 2.14 → 2.14 | 3.55 → 3.55 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| 10-svg-waterfall | 1.41 → 1.41 | 2.13 → 2.13 | none / none | 0 / 0 | 2 / 0; 2 / 0 |
| 11-chartjs-canvas | 1.06 → 1.06 | 1.63 → 1.63 | none / none | 0 / 0 | 2 / 0; 2 / 0 |
| 12-progress-bars-icons | 1.29 → 1.29 | 1.96 → 1.96 | none / none | 0 / 0 | 9 / 0; 9 / 0 |
| 13-code-gradtext-rotated | 1.38 → 1.38 | 1.82 → 1.82 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| 14-two-col-text-image-overlap | 1.76 → 1.76 | 2.15 → 2.15 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| 15-dense-table-badges-zebra | 1.51 → 1.51 | 2.56 → 2.56 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| 16-closing-cta | 1.74 → 1.74 | 1.59 → 1.59 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| 17-mixed-content-hidden-graphics | 1.54 → 1.54 | 2.79 → 2.79 | none / none | 0 / 0 | 6 / 0; 6 / 0 |
| **mean** | **1.82 → 1.82** | **2.40 → 2.40** |  |  |  |

Design-system corpus (27 slides):

| Slide | PowerPoint | Google Slides | Text loss (pptx / gslides) | MODEL DROPS (pptx / gslides) | Captures taken / failed (pptx; gslides) |
|---|---|---|---|---|---|
| slide-2x2-matrix | 1.97 → 1.97 | 1.73 → 1.73 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-action-title | 1.48 → 1.48 | 2.27 → 2.27 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| slide-agenda | 0.87 → 0.87 | 0.96 → 0.96 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-azure-flow-example | 1.55 → 1.55 | 1.25 → 1.25 | none / none | 0 / 0 | 14 / 0; 14 / 0 |
| slide-bold-title | 1.58 → 1.58 | 1.43 → 1.43 | none / none | 0 / 0 | 2 / 0; 2 / 0 |
| slide-charts | 0.79 → 0.79 | 0.83 → 0.83 | none / none | 0 / 0 | 2 / 0; 2 / 0 |
| slide-closing | 0.81 → 0.81 | 0.71 → 0.71 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| slide-comparison | 1.22 → 1.22 | 1.44 → 1.44 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-content | 2.20 → 2.20 | 1.75 → 1.75 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| slide-cover | 2.31 → 2.31 | 1.83 → 1.83 | none / none | 0 / 0 | 2 / 0; 2 / 0 |
| slide-data-table | 1.65 → 1.65 | 1.17 → 1.17 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-event-cover | 2.07 → 2.07 | 1.27 → 1.27 | none / none | 0 / 0 | 2 / 0; 2 / 0 |
| slide-executive-summary | 4.04 → 4.04 | 2.59 → 2.59 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-industry-title | 2.34 → 2.34 | 2.93 → 2.93 | none / none | 0 / 0 | 3 / 0; 3 / 0 |
| slide-journey | 1.30 → 1.30 | 0.75 → 0.75 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-kpi-dashboard | 2.05 → 2.05 | 1.93 → 1.93 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| slide-lakehouse-blueprint | 2.40 → 2.40 | 2.04 → 2.04 | none / none | 0 / 0 | 9 / 0; 9 / 0 |
| slide-medallion | 1.97 → 1.97 | 1.93 → 1.93 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-milestones | 1.03 → 1.03 | 0.86 → 0.86 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-reference-architecture | 1.77 → 1.77 | 1.96 → 1.96 | none / none | 0 / 0 | 7 / 0; 7 / 0 |
| slide-section | 0.74 → 0.74 | 1.38 → 1.38 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| slide-statement | 1.67 → 1.67 | 2.39 → 2.39 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| slide-stats | 1.05 → 1.05 | 1.09 → 1.09 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-three-cards | 1.06 → 1.06 | 0.99 → 0.99 | none / none | 0 / 0 | 3 / 0; 3 / 0 |
| slide-timeline | 0.62 → 0.62 | 0.82 → 0.82 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-two-column | 1.82 → 1.82 | 1.44 → 1.44 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| slide-waterfall | 1.24 → 1.24 | 1.15 → 1.15 | none / none | 0 / 0 | 1 / 0; 1 / 0 |
| **mean** | **1.61 → 1.61** | **1.51 → 1.51** |  |  |  |

### D11: corners of different radii, measured

**The construct probe** (12 boxes, CSS truth; full table in `CALIBRATION.md` D11): PowerPoint draws
`round2SameRect`, an `arcTo` custom path and a polygon path within 0.01–0.02 of the UI, Google at
its thumbnail floor (0.28–0.29, a uniform roundRect's), where one roundRect with the largest
radius scored 0.71 / 0.97 with 118 px off (16 px top corners) and 4.32 / 4.57 with about 720 px
off (4, 12, 24 and 36 px corners).

**The D11 probe corpus** through the harness (three slides of mixed-corner boxes: card headers
and footers, a 24/6 px header, a shadowed top-rounded card, a segmented control, a progress fill,
a speech bubble, an elliptical box, bordered and dotted boxes, a clipped box, a ringed chip, a
turned leaf, a shadowed diagonal box), baseline → B4:

| Slide | PowerPoint | Google Slides | Text loss (pptx / gslides) | MODEL DROPS (pptx / gslides) | Captures taken / failed (pptx; gslides) |
|---|---|---|---|---|---|
| 01-card-headers | 0.71 → 0.64 | 1.23 → 1.17 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| 02-tabs-bars-bubbles | 1.26 → 1.06 | 1.84 → 1.78 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| 03-clipped-and-ringed | 1.23 → 1.08 | 1.44 → 1.29 | none / none | 0 / 0 | 0 / 0; 0 / 0 |
| **mean** | **1.07 → 0.93** | **1.50 → 1.41** |  |  |  |

| D11 corpus, pixels off by more than 48 levels in the 17 boxes' corner squares | PowerPoint | Google |
|---|---|---|
| 01 card headers | 358 → 0 | 366 → 1 |
| 02 tabs, bars and bubbles | 804 → 192 | 872 → 432 |
| 03 clipped, ringed and turned | 1035 → 36 | 1049 → 39 |

What is left on slide 02 is no corner's shape (crops at 5×): the dotted box's dot phase, Google's
softer stroke edges (the same before and after), and text inside the elliptical box's 64 px corner
square. Every square corner is square and every rounded one rounds by its own radii, in both apps.

### B3's leftovers

- **Minor 1** (`3beb5dc8`): the table's own box in the PowerPoint deck is cut by its clip snapped
  with the grid (`snappedClip`, shared with the corner cells). A ground-filled table in a rounded
  wrapper at 160.4 px: its ground started 0.39 px below the grid (y 160.39 against 160); now it
  spans the frame exactly, on the snapped arcs. Neither corpus holds the case.
- **Minor 3** (`918cf0bf`): a failed dotted-cell rewrite ended the sidecar `[huashu] fatal`, exit
  99, every slide lost; now one `[huashu]` line, and the deck written dashed.
- **Minor 4** (`918cf0bf`): `pptxgenjsZipPath()` is the very jszip file pptxgenjs loads (test).
- **Minor 5** (`c172eac3`): a background's `captureId` must name the model's one `ground` capture.

### Rulings and corrections from B4

- **Ruling (H1, measured):** every PDF the harness reads (PowerPoint's, and LibreOffice's, the
  same artefact) is drawn by MuPDF at 4× the slide (5120 × 2880) and box-filtered to 1280 × 720,
  each pixel the mean of the 16 it covers; each run records the method as `pdfRaster` in
  `harness.json`, and `summary.md` flags a baseline that does not record the same one. The
  artefact reproduces from the embedding alone: a 2× picture with an alpha mask and
  `/Interpolate true` (as PowerPoint embeds Chrome's captures, clear pixels black), placed
  0.36 px off the grid, drew its EBEBEB 1 px rule over two rows at seven times its weight at 1×
  (`test_export_fidelity_harness.py`, with pymupdf).
- **Correction (H1, commit `c5789a80`'s message):** against Quartz the 4× raster is closer on 6
  of the 9 slides probed and within 0.01 on the other 3 (corpus 05 and 13 0.01 further,
  `slide-journey` equal), not "as close or closer on every slide".
- **Ruling (summary.md):** the Google deck's text loss is checked too
  (`text_loss-gslides.json`): the summary reports each deck, and "text loss is empty
  everywhere" includes the deck Google converts. Captures are counted per deck as taken
  (named less failed) / failed.
- **Ruling (D11, measured):** a box whose corners differ is the preset `round2SameRect` when its
  top corners are one circle and its bottom ones another, each at most half the short side
  (the preset pins its adjustments there), and otherwise a custom path of one `arcTo` quarter
  arc per rounded corner, elliptical where CSS's is. Both apps draw both constructs exactly
  (the probe above, `CALIBRATION.md` D11), so one construct serves both decks (R11g: no target branch). The preset is
  chosen for editability: Drive keeps it as `ROUND_2_SAME_RECTANGLE` and PowerPoint as its
  rounded-top rectangle, handles and all; the path is `CUSTOM` in Drive and a freeform with
  four arcs in PowerPoint (a polygon path would draw as well, with dozens of edit points).
  pptxgenjs writes a preset's two adjustments only through `angleRange` (each value × 60000),
  so adj1 and adj2 are passed as `adj / 60000`.
- **Ruling (D11):** the per-corner radii follow every shape a box makes: the border's centre
  line (each radius less half the border, the stroke-centre ruling per corner), a spread ring's
  (`ringRadius` per axis), a shadow spread's, the outline a clip cuts, the footprint and cover
  tests that fill shadow shapes, and Google's dotted stroke. A corner with either radius 0 is
  square, as CSS draws it. Four corners of one circle stay the `roundRect` they were, byte for byte.
- **Ruling (B3 Minor 3):** the guard is in `emit_deck.mjs`, which owns writing the deck and its
  `[huashu]` lines: a failed rewrite logs `[huashu] dotted table borders left dashed: their
  rewrite failed: <reason>` and writes the deck as pptxgenjs wrote it.
- **Ruling (B3 Minor 5):** a model with two ground captures came from no snapshot (it takes one
  at most), so both are dropped, as two captures sharing an id are, and a background naming
  either is reset as one naming an unknown capture is (to null: no ground of the slide's own).
- **Owner-facing notes:**
  - PowerPoint scores from runs before B4 are on the old raster: compare a new run with one of
    them only after rasterising its kept `powerpoint/export.pdf` again (`rasterise_pdf`);
    `summary.md` says so when a baseline's raster differs.
  - A box whose corners differ is a preset when one draws it exactly (a rounded-top card header
    keeps its handles), and otherwise a custom shape: it moves and recolours whole, but scales
    its corners with it when resized.

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/1Bezr8mS5WksUXdLffGfGLO_1IFRr0oKgR7GnvxRKcBE/edit
- Design-system corpus: https://docs.google.com/presentation/d/15Phr83mi5I7MhGlX89nHZC1h5ER5N7nWBz2-IyzPjuY/edit

The baseline, probe and D11-corpus presentations were deleted by id and confirmed gone
(`files.get` 404).
