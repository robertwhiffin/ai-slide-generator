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

- **Ruling (D4, D5), superseded by B5:** a shadow layer the box's own shape cannot carry is a *shadow shape*
  under the box: its border box (shrunk by a negative spread), unoutlined, named "Shadow" in the
  selection pane, filled opaque, since both apps scale a shape's shadow by its fill's alpha and
  cast none from an unfilled shape. Its fill is the box's own colour under an opaque box, else
  the one colour the export paints beneath it; where no one colour does, the shapes are dropped
  and the box keeps its first layer, as before. The box stays on top, so a click selects the
  box; a shadow shape is reached through the selection pane. pptxgenjs writes no groups, so the
  shapes are ordered under the box, not grouped with it (what a moved box leaves behind: the
  owner-facing notes and the owner decision below).
- **Ruling (D4, fix round 1), superseded by B5:** a ring listed before the first shadow (Tailwind's ring, then
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
  - *No longer applies since B5:* B2 drew a two-layer card's further layers as opaque copies of
    its shape under it (and an unfilled box's in the colour beneath), which a moved card left
    behind as a ghost. A box's layers are now its one fitted shadow on the box itself, so a
    moved card leaves nothing behind (B5).
  - A moved data table leaves behind its rounded corner pieces (coral above, white below),
    while its own corner cells, unfilled, move with it and show what is beneath them.
  - In the Google deck a dotted border is a freeform stroke, which moves and recolours whole
    but is not a preset line; a dotted box's border is a stroke separate from its box.

### Owner decision: how a box's extra shadow layers are written

**Decided 2026-11-21: (b), built in B5.** The measurements below are B2's, on the old raster.

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

### B4 fix round 1

- **D11, the presets:** `round2DiagRect` (two diagonal pairs) and `round1Rect` (a top-right
  corner alone) are written too where they fit exactly, measured in both apps like
  `round2SameRect` (`CALIBRATION.md` D11: within 0.00–0.02 in PowerPoint and at Google's floor,
  0.28–0.31; Drive keeps `ROUND_2_DIAGONAL_RECTANGLE` and `ROUND_1_RECTANGLE`). The ruling above
  now reads: the preset that draws a box exactly, `round2SameRect`, `round2DiagRect` or
  `round1Rect`, else the `arcTo` path.
- **D11, a corner either radius of which is 0** is square in the emitter too (it drew a
  chamfer), and `model_check.cjs` keeps a corner only with both radii above 0 or both 0, as the
  snapshot writes it.
- **summary.md:** a baseline rasterised another way is not compared in PowerPoint or
  LibreOffice ("not compared: raster differs"): their rows and means are the run's alone, and
  no rise of theirs is listed as worse. Google Slides is still compared.
- **Tests:** the custom-path tests walk the path as the apps draw it (every arc centred on its
  CSS corner's centre, every vertex, side and arc on CSS's outline), which the reviewer's
  misdrawn-path sabotage now turns red.

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/1Bezr8mS5WksUXdLffGfGLO_1IFRr0oKgR7GnvxRKcBE/edit
- Design-system corpus: https://docs.google.com/presentation/d/15Phr83mi5I7MhGlX89nHZC1h5ER5N7nWBz2-IyzPjuY/edit

The baseline, probe and D11-corpus presentations were deleted by id and confirmed gone
(`files.get` 404).

## Phase B, batch B5: one fitted shadow per box (the owner's option (b)), engine `fbf1e291`

Commit: `fbf1e291`. The owner chose option (b) (B2's "Owner decision"): a box's `box-shadow`
layers are its one outer shadow, on its own shape, the native construct of either app, so a
moved box leaves nothing behind. The method is in `scripts/export_fidelity/CALIBRATION.md` (D4
and D5, "The fitted shadow"). Both corpora were re-run with `run.py --pin-fonts --powerpoint
--gslides --baseline`, against a fresh baseline at `688f33b6` on the same 4x raster.

### Scores, baseline (`688f33b6`, B2's option (a)) → B5 (`fbf1e291`, option (b))

In-repo corpus (17 slides): both decks are byte-identical to the baseline's on every slide (its
one shadow, `.dk-card`'s, is one layer), and every score is the same: PowerPoint mean 1.82,
Google 2.40.

Design-system corpus (27 slides): only these four slides change, in either deck; every other
slide, the control set included, scores the same to the hundredth in both apps.

| Slide | What changes | PowerPoint (a) → (b) | Google (a) → (b) |
|---|---|---|---|
| slide-three-cards | three `--shadow-md` cards: one fitted shadow each | 1.06 → 1.08 | 0.99 → 1.02 |
| slide-kpi-dashboard | five `--shadow-sm` cards: one fitted shadow each | 2.05 → 2.06 | 1.93 → 1.91 |
| slide-medallion | its unfilled `.med-frame` casts none | 1.97 → 2.01 | 1.93 → 1.96 |
| slide-data-table | its unfilled table wrapper casts none | 1.65 → 1.69 | 1.17 → 1.20 |
| **mean, 27 slides** | | **1.615 → 1.619** | **1.514 → 1.517** |

| Control slide | PowerPoint | Google |
|---|---|---|
| 02-agenda-grid-rules | 1.15 → 1.15 | 1.78 → 1.78 |
| 05-balance-sheet-two-tables | 2.14 → 2.14 | 1.80 → 1.80 |
| 12-progress-bars-icons | 1.29 → 1.29 | 1.96 → 1.96 |
| slide-agenda | 0.87 → 0.87 | 0.96 → 0.96 |
| slide-lakehouse-blueprint | 2.40 → 2.40 | 2.04 → 2.04 |
| slide-stats | 1.05 → 1.05 | 1.09 → 1.09 |

No slide is worse than at `688f33b6` by more than 0.05 in either app; the four slides that
change are the ones B5 is for, each within +0.04 of (a). No text loss, no MODEL DROPS, in both
corpora and both decks.

### The shadows, measured

Below the first shadowed box, at its centre column: how far the shadow reaches (to under 1
level of darkening for the cards, 0.5 for the fainter `--shadow-sm` boxes) and the darkening
summed to the next element (UI / PowerPoint / Google, at 1280 px, the 4x raster):

| Slide | UI | (a) separate shadow shapes | (b) one fitted shadow |
|---|---|---|---|
| slide-three-cards (`--shadow-md`) | 26 px, 176 | 20 / 18 px, 160 / 142 | 15 / 13 px, 145 / 130 |
| slide-kpi-dashboard (`--shadow-sm`) | 4 px, 31 | 3 / 2 px, 24 / 11 | 2 / 3 px, 20 / 22 |
| slide-medallion (unfilled frame) | 3 px, 13 | 2 / 2 px, 14 / 6 | none / none |
| slide-data-table (unfilled wrapper) | 4 px, 33 | 3 / 2 px, 28 / 23 | none / none |

### Rulings from B5

- **Ruling (D4, B5):** one shadow per box. One layer with no spread is written as it is; any
  other set of layers is the one layer closest to them all, fitted by least squares in CSS's
  box-shadow model over the box's four edges (alpha in closed form, offset and blur on a grid
  narrowed four times, colour weighted by each layer's own coverage). `--shadow-md` is
  `0 5.13px 14.34px` 1B3139 at 0.139 and `--shadow-sm` `0 1px 2.58px` at 0.137; the tests pin
  both, and hold Tailwind's `shadow-lg` to a least-squares minimum of the model.
- **Ruling (D5, B5):** only a box that paints a fill casts its shadow. An unfilled box casts
  none: neither app casts a shadow from an unfilled shape, and an outline would cast only a thin
  frame of itself, which the browser does not paint. A translucent box casts the fitted shadow
  itself, as before B2 (both apps draw it scaled by the fill's alpha, through the fill). No shape
  is drawn for a shadow alone, so no opaque fill of the export's own can show.
- **Ruling (D4 fix round 1, B5):** the box's shadow paints where its first shadow layer does: a
  ring listed before that layer is drawn over the box (it lies outside the border box and covers
  nothing of it), any other ring under it. D2's translucent ring stays a shape of its own.
- **Removed:** the colour-beneath pass (`resolveShadowShapes`), the model's `role` field and its
  check, and the emitter's "Shadow" name. Tests guard that no shape is named "Shadow", that every
  shape paints a fill or an outline, and that a forged `role` names nothing.
- **Ruling (B5 fix round 1):** a single layer with a spread is fitted like several layers (an
  outer shadow has none), and the fit's offset may move by the layers' largest spread either way,
  as a spread moves an edge: Tailwind's `shadow-2xl` (`0 25px 50px -12px` at 0.25) is
  `0 24.06px 36.71px` at 0.174, a coral glow (`0 0 12px 4px` at 0.3) blur 15.94 at 0.47; layers
  with no spread fit exactly as before. A slide makes at most 64 fits (each 6–10 ms); past them a
  box carries its first layer as it is, counted in one `[html2pptx] box-shadow fits` line. A
  layer written as it is keeps its alpha however faint (0.004 under `opacity: 0.2`, 0.0008); only
  a fit with no alpha to keep writes no shadow.

### Owner-facing notes

- **A moved card leaves nothing behind.** Its shadow is its own (one outer shadow, editable in
  either app's shadow settings); its text was always a separate object.
- **The cost of (b):** a `--shadow-md` card's tail is 5 px shorter than with (a) in either app
  (15 / 13 px against the UI's 26), and an unfilled box (the data table's wrapper, the medallion
  frame) shows no shadow, where the UI shows a faint 3–4 px one.
- A moved data table still leaves its rounded corner pieces behind (B3), and in the Google deck a
  dotted box's border is a stroke separate from its box (B2).

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/1i0QhBby50i1QUdtkZn4QGPqnqfmOprwd9t2WjJEVR08/edit
- Design-system corpus: https://docs.google.com/presentation/d/1BCj-l0KtY67g2oRZbLkg84Ey8ao2LM2P5xrJ0roSkKE/edit

The baseline presentations were deleted by id and confirmed gone (`files.get` 404).

## Phase C: final verification at engine `8a72f600`

Phase C re-runs Phase A's verification on both corpora and both renderers, with pinned fonts, at
the branch head after B1–B5. It changes no engine code: the defects it finds are recorded here,
not fixed.

### How it was measured

- **Final runs.** `uv run --with pymupdf --with pillow python scripts/export_fidelity/run.py
  <corpus> --out <dir> --pin-fonts --powerpoint --gslides --baseline <legacy dir>` at
  `8a72f600`, on the in-repo corpus (17 slides) and the design-system corpus (27).
- **The legacy baseline on today's raster.** Phase A kept the legacy (`origin/main`) run's
  PowerPoint PDFs. Each was rasterised again with the harness's own `rasterise_pdf` (MuPDF at 4×,
  box-filtered to 1280 × 720) and scored with the harness's own `compare`, against Phase A's UI
  truth.
  - **One UI reference.** That truth is byte-identical to this run's, on all 44 slides.
  - **Google.** The legacy Google thumbnails are scored as they were; the harness does not
    rasterise Google.
  - **The raster record.** Each baseline's `harness.json` records the current `pdfRaster`, so
    `summary.md` compares both apps and flags no raster difference.
  - **The figures reproduce.** The re-rasterised legacy means reproduce Phase A's own 4×
    figures: PowerPoint 8.92 (in-repo) and 5.68 (design system). The Google means are unchanged
    at 8.86 and 5.78.
- **No run noise.** All four decks (two corpora, two targets) are byte-identical to B5's final
  run's, and every score equals B5's to the hundredth in both apps.
- **Beyond the scores.**
  - Every slide's sheet (UI | PowerPoint | Google | difference map) was inspected by eye, with
    zoomed crops and pixel profiles wherever something differed.
  - The line-placement check matched every browser line against both apps' own PDFs: PowerPoint's,
    and Google's Drive export.
  - The deck XML and both PDFs' fonts were read for each fix and carry-over item.

### Results

In-repo corpus (tests/fixtures/export_fidelity, 17 slides): **DEFECT 3, TRADE-OFF 7, MATCHES 7.**

| Slide | PowerPoint, legacy → final | Google, legacy → final | Tag | What differs, and the ruling or cause | Text loss (pptx / gslides) | MODEL DROPS (pptx / gslides) |
|---|---|---|---|---|---|---|
| 01-cover-gradient-svg-art | 11.01 → 3.23 | 10.72 → 2.82 | MATCHES | Gradient ground, SVG hexagon art, tracking and breaks as the UI | none / none | 0 / 0 |
| 02-agenda-grid-rules | 3.50 → 1.15 | 3.40 → 1.78 | MATCHES | Grid, rules and mono numerals as the UI; the grey subtitles are written in the UI's own colour (5A6F77) and only rasterise lighter | none / none | 0 / 0 |
| 03-svg-combo-chart-legend-callout | 16.32 → 2.06 | 17.08 → 2.67 | TRADE-OFF | Charts become pictures: the SVG combo chart, its data labels inside the picture; legend and callout native. Its gridlines are light now (H1) | none / none | 0 / 0 |
| 04-harvey-table-caption | 8.46 → 2.08 | 8.27 → 2.97 | TRADE-OFF | The in-repo deck's synthetic italic against the true italic, in the caption (regular weight now: D1). Harvey balls, highlighted column and native table match | none / none | 0 / 0 |
| 05-balance-sheet-two-tables | 13.65 → 2.14 | 13.52 → 1.80 | DEFECT | D12 (Google): the bold total rows' numbers and headers sit 1.9–2.7 px left of the plain rows in the same right-aligned columns. No PowerPoint seams (D7: 0 seam columns, MuPDF and Quartz) | none / none | 0 / 0 |
| 06-delta-pills-table-callout | 29.57 → 1.75 | 29.35 → 2.72 | DEFECT | D12 (Google): the bold FY24 / FY23 headers 1.7–2.4 px left of their columns. Synthetic italic source line (trade-off). Pills, ▲▼, table and callout match | none / none | 0 / 0 |
| 07-timeline-dots-mono-dates | 6.14 → 2.51 | 6.08 → 2.57 | MATCHES | Dots, rule and mono dates as the UI; the 22 px subtitle now ends where the UI's does (X1) | none / none | 0 / 0 |
| 08-kpi-cards-grid | 7.32 → 2.26 | 6.85 → 3.26 | TRADE-OFF | Ruling D8 (B1): ▲▼ in Arial, whose triangle ink is smaller than the UI's Hiragino Sans (advance within 4 %); synthetic italic source line | none / none | 0 / 0 |
| 09-pseudo-bullets-accent-quote | 7.92 → 2.14 | 8.34 → 3.55 | TRADE-OFF | Synthetic italic (the em phrase and the footnote); the SKU-7 chip sentence is several boxes; Google's superscript at 0.8 on a line that does not grow. Bullets, accent bar and quote border match | none / none | 0 / 0 |
| 10-svg-waterfall | 5.70 → 1.41 | 6.02 → 2.13 | TRADE-OFF | Charts become pictures (the waterfall); synthetic italic source line. The card matches | none / none | 0 / 0 |
| 11-chartjs-canvas | 2.86 → 1.06 | 2.75 → 1.63 | TRADE-OFF | Charts become pictures: the Chart.js doughnut with its canvas-drawn legend; cards and title native | none / none | 0 / 0 |
| 12-progress-bars-icons | 7.19 → 1.29 | 6.77 → 1.96 | MATCHES | Progress fills and icons (pictures, spec call 3) and the off-slide circle as the UI | none / none | 0 / 0 |
| 13-code-gradtext-rotated | 5.37 → 1.38 | 4.26 → 1.82 | TRADE-OFF | Gradient text becomes one solid colour; the code block and the turned GOVERNED DATA label match | none / none | 0 / 0 |
| 14-two-col-text-image-overlap | 4.94 → 1.76 | 5.48 → 2.15 | MATCHES | Colours exact (C9D3D6); light-on-dark strokes look thinner in both apps, which is Chrome's macOS text rendering in the truth | none / none | 0 / 0 |
| 15-dense-table-badges-zebra | 5.53 → 1.51 | 5.51 → 2.56 | DEFECT | D12 (Google): bold mono cells 2.1–2.5 px left of the plain rows, the margin column 4.7–5.6 px, its header 7.4 px. No PowerPoint seams (D7). Zebra rows and pills match | none / none | 0 / 0 |
| 16-closing-cta | 5.47 → 1.74 | 5.41 → 1.59 | MATCHES | As the UI | none / none | 0 / 0 |
| 17-mixed-content-hidden-graphics | 10.75 → 1.54 | 10.84 → 2.79 | MATCHES | Icons beside bare text, hidden graphics hidden, faded copy faded, the script-drawn canvas present | none / none | 0 / 0 |
| **mean** | **8.92 → 1.82** | **8.86 → 2.40** | | | | |

Design-system corpus (local `$TMP/ds_fixture`, 27 slides): **DEFECT 1, TRADE-OFF 8, MATCHES 18.**

| Slide | PowerPoint, legacy → final | Google, legacy → final | Tag | What differs, and the ruling or cause | Text loss (pptx / gslides) | MODEL DROPS (pptx / gslides) |
|---|---|---|---|---|---|---|
| slide-2x2-matrix | 5.74 → 1.97 | 5.12 → 1.73 | MATCHES | The plotted dot is 14 px with its 4 px pale ring in both apps (D2); matrix, turned axis label and bullets as the UI | none / none | 0 / 0 |
| slide-action-title | 5.56 → 1.48 | 6.53 → 2.27 | TRADE-OFF | Google's superscripts at 0.8 on lines that do not grow (2). Bars and callout native and matching; the italic footnote is regular weight (D1) | none / none | 0 / 0 |
| slide-agenda | 3.75 → 0.87 | 4.18 → 0.96 | MATCHES | As the UI | none / none | 0 / 0 |
| slide-azure-flow-example | 4.36 → 1.55 | 4.02 → 1.25 | TRADE-OFF | Ruling D8: the caption's → in Arial, 10–13 % wider than the UI's, the words after it −0.4 to +3.4 px. Google's dots 1:1 at the UI's 4 px period (D6); PowerPoint's ~1 px out of phase (B2, not changed, not visible) | none / none | 0 / 0 |
| slide-bold-title | 5.43 → 1.58 | 5.45 → 1.43 | MATCHES | As the UI. PowerPoint's faint logo mark is MuPDF's raster of the masked picture (22 levels; Quartz 4, UI 0, Google 1) | none / none | 0 / 0 |
| slide-charts | 4.13 → 0.79 | 4.46 → 0.83 | TRADE-OFF | Charts become pictures (both charts); titles and legends native | none / none | 0 / 0 |
| slide-closing | 4.41 → 0.81 | 4.18 → 0.71 | MATCHES | As the UI | none / none | 0 / 0 |
| slide-comparison | 5.12 → 1.22 | 5.39 → 1.44 | MATCHES | Harvey balls cut to their circles (D3); the italic legend regular weight (D1) | none / none | 0 / 0 |
| slide-content | 6.58 → 2.20 | 6.86 → 1.75 | MATCHES | As the UI | none / none | 0 / 0 |
| slide-cover | 7.32 → 2.31 | 7.04 → 1.83 | MATCHES | As the UI | none / none | 0 / 0 |
| slide-data-table | 6.20 → 1.69 | 6.54 → 1.20 | DEFECT | D12 (Google): the Cost (list) header 4.8 px left. D13 (Google): a light 1 px seam in the coral header where its rounded left corner piece meets the next cell. Unfilled wrapper casts no shadow (B5 trade-off). PowerPoint: rounded header, no seams | none / none | 0 / 0 |
| slide-event-cover | 6.17 → 2.07 | 6.38 → 1.27 | MATCHES | The tracked 64 px title ends within 1.1 px in both apps; in PowerPoint its glyphs after kerned pairs drift up to 3.7 px mid-line (X1, listed once below) | none / none | 0 / 0 |
| slide-executive-summary | 7.68 → 4.04 | 5.30 → 2.59 | TRADE-OFF | Ruling D8: the → in Arial, longer and thinner than the UI's, the text after it +3.1 px (PowerPoint) / +1.8 px (Google) | none / none | 0 / 0 |
| slide-industry-title | 9.43 → 2.34 | 9.14 → 2.93 | MATCHES | As the UI, the photo capture included | none / none | 0 / 0 |
| slide-journey | 3.08 → 1.30 | 3.42 → 0.75 | MATCHES | As the UI | none / none | 0 / 0 |
| slide-kpi-dashboard | 8.83 → 2.06 | 9.37 → 1.91 | TRADE-OFF | A fitted shadow's tail is a little short (4 → 2 / 3 px); ruling D8: the bold ▲ in Arial, 29–36 % wider, the delta text +3.0–3.2 px | none / none | 0 / 0 |
| slide-lakehouse-blueprint | 11.40 → 2.40 | 11.32 → 2.04 | MATCHES | As the UI (65 lines of dense diagram; chip markers are pictures) | none / none | 0 / 0 |
| slide-medallion | 5.30 → 2.01 | 5.69 → 1.96 | TRADE-OFF | Unfilled boxes carry no shadow (the frame); ruling D8: the CSS → in Arial Bold, thinner than the UI's. Corner tiles cut to the arcs (D3) | none / none | 0 / 0 |
| slide-milestones | 3.25 → 1.03 | 3.34 → 0.86 | MATCHES | As the UI, the current milestone's halo included | none / none | 0 / 0 |
| slide-reference-architecture | 5.88 → 1.77 | 5.75 → 1.96 | TRADE-OFF | Ruling D8: the → links (CSS content) in Arial, thinner than the UI's | none / none | 0 / 0 |
| slide-section | 3.88 → 0.74 | 4.32 → 1.38 | MATCHES | end-to-end at full width in Google (D8 hyphens) | none / none | 0 / 0 |
| slide-statement | 7.73 → 1.67 | 9.40 → 2.39 | MATCHES | As the UI | none / none | 0 / 0 |
| slide-stats | 5.06 → 1.05 | 5.41 → 1.09 | MATCHES | As the UI | none / none | 0 / 0 |
| slide-three-cards | 3.79 → 1.08 | 3.82 → 1.02 | TRADE-OFF | A fitted shadow's tail is a little short: 26 px in the UI, 15 / 13 px (one shadow per card) | none / none | 0 / 0 |
| slide-timeline | 3.77 → 0.62 | 4.06 → 0.82 | MATCHES | As the UI | none / none | 0 / 0 |
| slide-two-column | 5.76 → 1.82 | 5.95 → 1.44 | MATCHES | As the UI | none / none | 0 / 0 |
| slide-waterfall | 3.78 → 1.24 | 3.61 → 1.15 | MATCHES | Native bars, connectors and true-italic caption as the UI | none / none | 0 / 0 |
| **mean** | **5.68 → 1.62** | **5.78 → 1.52** | | | | |

**Means** (legacy → final, the same 4× raster): in-repo PowerPoint **8.92 → 1.82** and Google
**8.86 → 2.40**; design system PowerPoint **5.68 → 1.62** and Google **5.78 → 1.52**.

**Health.** Captures: 42 / 0 failed (in-repo) and 51 / 0 (design system) in each deck. No export
failures. `summary.md`, both corpora: "Worse than the baseline by more than 0.05: none."

**How a slide is tagged.**
- **MATCHES:** no difference from the UI beyond the rasterisers' anti-aliasing.
- **TRADE-OFF:** every difference is one an accepted ruling covers, and that ruling is named.
- **DEFECT:** the slide shows a difference no ruling covers. Its cause and owning module are
  below.
- **The UI's line breaks are kept on every slide**, so that trade-off is not repeated per slide.

### The brief's end conditions

1. **No slide shows an RC defect: NOT MET.** Four slides carry D12 in the Google deck (in-repo
   05, 06, 15; `slide-data-table`), RC7's family (a weight's construct). One also carries D13
   (`slide-data-table`), RC8's family (a table's radius).
   - Every other RC check holds in both apps: RC1 through RC13, each confirmed in the sheets and
     line checks, as listed below.
   - PowerPoint shows no defect on any slide.
2. **No slide scores worse than its legacy baseline, in either renderer: MET.** Every slide is
   better in both apps, by any margin, not only by 0.05. The smallest gains:
   - corpus 11 in both apps (PowerPoint 2.86 → 1.06, Google 2.75 → 1.63);
   - `slide-journey` in PowerPoint (3.08 → 1.30);
   - `slide-waterfall` in Google (3.61 → 1.15).
3. **Text loss is empty everywhere: MET.** Both decks of both corpora (`text_loss.json`,
   `text_loss-gslides.json`) are empty, with no MODEL DROPS.

**RC1–RC13 as seen.**
- **RC1:** the side-by-side tables (05) and captions sit in place.
- **RC2:** flex and grid items are separate boxes (agenda numerals, legends, KPI labels).
- **RC3:** no stray SVG text; chart text travels inside the picture.
- **RC4:** class-styled SVG colours are kept (03, 10, the design-system art).
- **RC5:** no line re-wraps. Every unmatched segment is a matcher artefact: SVG text, monospace
  and letter-spaced gaps, list markers, text-transform, or fallback-glyph splits.
- **RC6:** every matched line's baseline is within 2.3 px of the UI's in both apps.
- **RC7:** weights, tracking, mono, scripts and faded text hold, apart from D12.
- **RC8:** pseudo-element bullets, dots, rings, Harvey balls, the progress fills, table radius
  and shadow hold, apart from D13.
- **RC9:** bold headers, italics and alignment in native tables.
- **RC10:** hidden graphics stay hidden (17).
- **RC11:** pills sit under the callouts.
- **RC12:** the turned labels (13, 2x2-matrix) are on one line.
- **RC13:** the SKU-7 chip stays in its sentence (09).

### Defects found in Phase C (not fixed: Phase C changes no engine code)

| Id | Renderer | What differs from the UI | Cause (measured) | Proposed fix, owning module |
|---|---|---|---|---|
| D12 | Google | A bold run in a webfont whose heaviest loaded weight is lighter than 600 (DM Mono loads 400 and 500) is placed short. In a right-aligned cell it ends 1.7–7.4 px left of where the UI and PowerPoint end it; plain runs in the same columns are within 0.3 px. Seen on in-repo 05, 06, 15 and `slide-data-table` (30 runs, all DM Mono) | The deck writes the browser's synthetic bold as the lighter face plus bold (`DM Mono Medium`, `b="1"`; `emit_typography.cjs`, Task 3). Drive converts that to DM Mono at weight 700, which the family lacks. Google then draws DMMono-Regular with a 0.58 pt faux-bold stroke, but lays the run out about 0.44 px per glyph wider than it draws it. Its PDF puts the glyphs at DM Mono's own 8.4 px advance, with the line's right edge 5.2 px short over 13 glyphs | For the `gslides` target, probe what Google draws for `DM Mono Medium` without bold, and for the family plus bold. Pick the construct whose weight is closest and that Google lays out at the drawn width; if none, compensate the faux-bold advance in the run's tracking as A1 does. Pin it with a Google measurement. `emit_typography.cjs` (the gslides synthetic-bold construct). **Fixed in B6 (`2e23228d`):** the deck for Google writes the face alone; the runs' edges lie within 0.04 px of the UI on all four slides (B6 below) |
| D13 | Google | A light 1 px seam in `slide-data-table`'s coral header at x = 356.5, where the wrapper's rounded left corner piece meets the next header cell. Drive's 1600 px thumbnail shows ff9e8f in a ff5f46 bar, 73 levels; Google's own PDF at 2× shows 8. Every other cell boundary of the table shows 0 | The corner piece (B2's D5 construct: the corner cell unfilled, its fill a custom shape cut to the arc under the table) ends at the browser's fractional grid line. The Google deck keeps that grid unsnapped (B3's D7 ruling, PowerPoint only), so the piece's anti-aliased edge and the neighbour cell's meet with a gap of coverage. B2's concern 5 (a faint row along the piece's top edge) was this construct's other edge | In the Google deck, run the corner piece one px under its opaque neighbour cell (the cell paints over it), or snap that one inner edge. Measure in Google's thumbnail and PDF. `snapshot_table.mjs` / `emit_table.cjs` (the corner pieces). **Fixed in B6 (`2ccfb12d`):** in the Google deck each corner piece runs 1 px under its opaque neighbours; the seam is 0 levels in the thumbnail. The light top row is the pieces' outer edge, a measured residual (B6 below) |

**D12, the weight (measured; a residual, not the defect).** Chrome's synthetic bold of DM Mono
500 adds 19 % ink at 4× (a probe at weights 400, 500 and 700 on the deck's own faces). In the same
probe at 1×, the harness's truth scale, it adds none measurable: 700 draws with 500's ink. At 2×,
the sidecar's and a Retina display's scale, both apps' faux bold is heavier than Chrome's, against
the same slides' plain DM Mono runs:
- **PowerPoint**, 14–22 %: DMMono-Medium with a 1.42 pt stroke;
- **Google**, 9–17 %: DMMono-Regular with a 0.58 pt stroke.

In the 1× sheets, PowerPoint's bold mono rows therefore look clearly heavier than the UI's,
+22–37 % ink.

### Differences recorded under rulings outside the brief's trade-off list

- **D8's fallback faces (B1 ruling).** ▲▼→ are written in Arial (Courier New after a mono run),
  a face all three apps have, not the browser machine's own fallback (Hiragino Sans, Lucida
  Grande).
  - **In-repo:** the advances match within 4 %; Arial's triangle ink is smaller, visible on 08's
    deltas (B1's concern 4).
  - **Design system:** the → glyphs are 10–13 % wider than the UI's and look longer and thinner,
    and the bold ▲ is 29–36 % wider. The text after them moves −0.4 to +3.4 px.
  - **Correction (B1):** B1's note that Arial's → is the UI's 1.00 em held in its 100 px probe,
    not in these decks.
  - **Slides:** 08, azure-flow, executive-summary, kpi-dashboard, medallion and
    reference-architecture are tagged under this ruling.
- **X1's uniform tracking (B1 ruling).** PowerPoint for Mac kerns no DM Sans, so each run's
  kerning is folded into one `spc`. Each line keeps its width:
  - median +0.16 px;
  - largest 2.73 px (in-repo) and 3.34 px (design system), B1's figures exactly.

  But glyphs after a kerned pair sit a little off mid-line, at most 3.7 px on
  `slide-event-cover`'s 64 px tracked title. This is on every PowerPoint slide, so it is listed
  here once and not per slide.
- **PowerPoint's dotted lines (B2, not changed).** They run from their start, about 1 px out of
  phase with Chrome's dots, at the UI's 4 px period (`slide-azure-flow-example`); not visible.

### Checks beyond the sheets

- **Line placement** (every browser line against each app's PDF; the 95th percentile of
  |Δy| is 0.9–1.2 px throughout):

  | Corpus | App | Lines | Worst \|Δy\| | Median line width error | Worst width error |
  |---|---|---|---|---|---|
  | in-repo | PowerPoint | 311 | 2.0 px | +0.16 px | 2.73 px |
  | in-repo | Google | 298 | 1.57 px | 0.00 px | 4.50 px |
  | design system | PowerPoint | 399 | 2.3 px | +0.15 px | 3.34 px |
  | design system | Google | 394 | 1.87 px | 0.00 px | 3.42 px |
- **Fonts in the apps' PDFs.** Only the deck's faces plus Arial and Courier New (D8) are used.
  - DMSans-Italic is drawn for every DM Sans italic run; the three italic → are Arial Italic (D8).
  - No DMSans-BoldItalic (D1), Times New Roman, Cambria Math or MS PGothic appears.
  - Google's PDF embeds Calibri but draws no text with it.
- **Shadow tails** (B5's tool; UI / PowerPoint / Google), the same as B5's:
  - `slide-three-cards`: 26 / 15 / 13 px;
  - `slide-kpi-dashboard`: 4 / 2 / 3 px;
  - the unfilled medallion frame and table wrapper: 3–4 px / none / none.
- **Seams (D7)**, B3's tool on PowerPoint's PDF, MuPDF and Quartz: 0 seam columns on 44
  interior lines of corpus 05, corpus 15 and `slide-data-table`.
- **Determinism.** Two fresh pinned exports of each corpus, for both targets, have the same
  `structural_manifest` as each other and as the final run's decks: 146 entries (in-repo) and
  202 (design system).
- **Gate.** `uv run pytest tests/unit -q -p no:cacheprovider -k "export or huashu or google"`:
  1336 passed, 0 failed, 10 skipped.

### Carry-over items, re-checked at `8a72f600`

| Item | Verdict |
|---|---|
| Task 1: unbordered shapes write `<a:ln></a:ln>` | **No default outline.** 222 (in-repo) and 437 (design system) such shapes per deck. In Google's Slides API the rendered outlines equal the shapes with a real outline on every slide (16 / 16, 100 / 100); no PowerPoint render shows one |
| Task 2: justified text plus slack may stretch in PowerPoint | **No stretch.** Neither corpus has justified text (`algn="just"`: 0); a probe paragraph exports `algn="l"` with the browser's four breaks |
| Task 2: `<a:pPr>` after every `<a:br/>` | **No repair prompt.** All 7 and 15 `<a:br>` are followed by `<a:pPr>`; PowerPoint opened and saved both decks unattended |
| Task 4: DM Sans italic heavier in PowerPoint | **Fixed (D1).** PowerPoint draws DMSans-Italic for every italic run (`DM Sans Italic`, italic off); Google keeps `DM Sans` plus italic |
| Task 5: `a<br> <br>b` may drop the blank line | **Kept.** `alpha`, a blank paragraph, `bravo`, as `a<br><br>b` |
| Task 7: dark PowerPoint gridlines in the harness PNG | **Fixed (H1).** Gridlines are light (03, `slide-charts`); the one residual is `slide-bold-title`'s same-colour logo mark, 22 levels in MuPDF against Quartz's 4 |
| PowerPoint seams between filled cells | **Fixed (D7)** in PowerPoint's PDF under MuPDF and Quartz. PowerPoint's own window still cannot be captured (no Screen Recording permission); the owner can confirm on screen |
| Mixed-size paragraph-spacing residuals | **Not visible.** The worst matched baseline is 2.3 px off (PowerPoint, `slide-cover`'s display title); a two-line 11 px caption in `slide-lakehouse-blueprint` pitches 1.2 px tight in PowerPoint |
| Form-control text | **None in either corpus** |
| Cases neither corpus holds | D9 (a root image ground), D10 (dotted cell borders), D11 (mixed corner radii) and B4's Minor 1: measured on B3's and B4's probe corpora, not re-measured here |

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/123h1a4PxUpbQJ5veI_OoVMhfBPEUK5mNAeI1p7yraeE/edit
  ("Tellr export revamp — final, in-repo corpus (Phase C, pinned fonts, 8a72f600)")
- Design-system corpus: https://docs.google.com/presentation/d/1jpnwkWtbiq6b7Avc4549S0sq7S5k_ptkWvwVlXfaw5Y/edit
  ("Tellr export revamp — final, design-system corpus (Phase C, pinned fonts, 8a72f600)")

Phase C created no other presentation; a Drive query for presentations created during the run
returns these two. The decks earlier phases kept are untouched.


## Phase B, batch B6: the two Google defects Phase C found (D12, D13), engine `2ccfb12d`

Commits: `2e23228d` (D12) and `2ccfb12d` (D13). Only the deck for Google Slides changes; the deck
for PowerPoint is the same. The probes went through Drive, as the export does (the engine's own
emitter writing probe decks for Google Slides, Drive's PDF and LARGE and MEDIUM thumbnails read
back, the presentations deleted by id). They are recorded in
`scripts/export_fidelity/CALIBRATION.md` (D12, D13). Both corpora were re-run with `run.py
--pin-fonts --powerpoint --gslides --baseline`, against Phase C's final runs (`8a72f600`).

### Scores, Phase C (`8a72f600`) → B6 (`2ccfb12d`)

- **The PowerPoint decks** of both corpora are byte-identical to Phase C's, apart from the
  timestamps in `docProps/core.xml`, so every PowerPoint score is the same: in-repo 1.82, design
  system 1.62.
- **The Google decks** change on exactly the four slides below. On every other slide the slide
  XML is byte-identical and the Google score is the same to the hundredth.
- **What changes.** The synthetic-bold runs lose their bold flag (30 in all), and
  `slide-data-table`'s four corner pieces run 1 px under their neighbours. Nothing else changes.

| Slide | Defect | What changes in the Google deck | Google, Phase C → B6 |
|---|---|---|---|
| 05-balance-sheet-two-tables | D12 | 12 `DM Mono Medium` runs written without bold | 1.80 → **1.61** |
| 06-delta-pills-table-callout | D12 | 2 runs | 2.72 → **2.70** |
| 15-dense-table-badges-zebra | D12 | 15 runs | 2.56 → **2.29** |
| slide-data-table | D12, D13 | 1 run; the four corner pieces | 1.20 → **1.16** |
| **mean, in-repo (17)** | | | **2.398 → 2.370** |
| **mean, design system (27)** | | | **1.517 → 1.516** |

The control set (in-repo 02 and 12; `slide-agenda`, `slide-lakehouse-blueprint`, `slide-stats`)
is unchanged in both apps. `summary.md`, both corpora: "Worse than the baseline by more than
0.05: none."

**Health.**
- Text loss is none in both decks of both corpora, and MODEL DROPS 0.
- Captures: 42 / 0 failed and 51 / 0, as in Phase C.
- No export failures.
- **Determinism** (Phase C's tool): two fresh pinned exports of each corpus, for both targets,
  have the same `structural_manifest` as each other and as the final run's decks (146 and 202
  entries).
- **Gate.** `uv run pytest tests/unit -q -p no:cacheprovider -k "export or huashu or google"`:
  1353 passed, 0 failed, 12 skipped (Phase C: 1336 / 0 / 10). The two new skips are the opt-in
  Drive tests, which were run red and then green with `TELLR_GOOGLE_TESTS=1`.
- **Full suite.** `uv run pytest tests/unit -q -p no:cacheprovider -n 6`: 18015 passed, 0
  failed, 27 skipped.

### What was measured (UI / Phase C / B6, at 1280 px unless named)

**D12: where the synthetic-bold runs lie.** The line check matched every browser line against
Google's PDF; the figures are each slide's worst left-edge offset, and the bold segments' edges.

| Slide | Worst \|dx\|, Google | Bold segments' left and right edges against the UI |
|---|---|---|
| 05 (12 segments) | 2.19 → **0.03** px | −2.19 to −1.74 → **0.00 to +0.01** |
| 06 (2) | 1.88 → **0.03** | −1.88 → **0.00** |
| 15 (10) | 5.24 → **0.01** | −5.25 to −1.74 → **0.00 to +0.01** |
| `slide-data-table` ("Cost (list)", two segments) | 4.71 → **0.04** | −4.81 to −4.65 → **−0.12 to +0.04** |

Google now draws these runs as DMMono-Medium, where Phase C's PDF drew DMMono-Regular with a
faux-bold stroke. Against PowerPoint's PDF, every run's right edge is within −0.47 to +0.42 px;
in Phase C it was −7.35 to −0.52.

**D12: the weight.** Each figure is the synthetic-bold runs' ink in Google's PDF over the UI's
(the median); in brackets, against Google's own plain DM Mono runs on the slide.

| Slide | At 2× (Chrome at 2×), Phase C → B6 | At 1× (the harness's truth), Phase C → B6 |
|---|---|---|
| 05 | 0.95 (+9 %) → 0.76 (−13 %) | 1.01 (+15 %) → 0.83 (−6 %) |
| 06 | 1.01 (+17 %) → 0.80 (−7 %) | 1.13 (+31 %) → 0.90 (+5 %) |
| 15 | 1.00 (+15 %) → 0.79 (−9 %) | 1.14 (+28 %) → 0.92 (+3 %) |
| `slide-data-table` (one white-on-coral header) | 0.88 (+1 %) → 0.69 (−21 %) | 0.88 (−2 %) → 0.69 (−23 %) |

**D13: every straight edge of the four corner pieces.** Each is measured in Drive's thumbnail and
Google's PDF, against the same deck with its corner cells filled natively (the native comparator)
and against Chrome at the same scale.

| Edge | Thumbnail, against native / UI (native's own) | Google's PDF, 1× / 2×, against the UI (native's own) |
|---|---|---|
| top-left piece, right (inner, x = 356.484) | 73 / 73 → **0 / 0** (0) | 45 / 9 → **0 / 0** (45 / 9) |
| top-right piece, left (inner, x = 989.484) | 0 / 35 → 0 / 35 (35: Chrome's own seam at 1.25×) | 45 / 10 → **0 / 0** (45 / 9) |
| top pieces, bottom (inner, y = 252.781) | 0 / 12 → 0 / 12 (12) | 85 / 131 → **49 / 85** (85 / 131) |
| top pieces, top (outer, y = 206.781) | 92 / 43, unchanged (49) | 47 / 82, unchanged (47 / 82) |
| the outer left and right edges (x = 88, 1192) | 0 / 11, unchanged (11) | 11 / 13, unchanged |
| the white pieces, every edge | 0 / 0 to 19, unchanged (the same) | 0 to 22, unchanged (the same) |

### Rulings from B6

- **Ruling (D12, measured through Drive).** The deck for Google Slides writes the browser's
  synthetic bold as the lighter face alone (`emit_typography.cjs` typefaceFor, from
  `model.fonts`). The deck for PowerPoint keeps the face plus bold.
  - Drive converts a bold flag to weight 700 whatever face is named.
  - Google lays out a faux bold (DM Mono) wider than it draws it, and draws a Bold the page did
    not load (DM Sans at 400 and 500) at that Bold's advances.
  - Of the constructs probed (the face plus bold, the family plus bold, a "Bold"-named face, a
    "SemiBold"-named face, the face with a run outline, the face alone), only the face alone
    puts both alignments within 0.5 px of the browser in both families. A "SemiBold" name
    draws DM Mono's Medium too, but DM Sans's real SemiBold, 3.7 px wide; Drive drops a run
    outline.
  - Placement outranks weight, so the face alone is the construct.
  - **Measured, and extrapolated.** The measured cases are the browser's synthetic bold of the
    500 face in two Google-hosted families: DM Mono, with no 700, and DM Sans, with a 700 the
    page did not load. Lighter faces (600 on 400, 800 on 300), and loaded webfonts Google does
    not host, follow from the same mechanism, unmeasured: Drive turns any bold flag into 700.
- **Ruling (D13, measured through Drive).** In the deck for Google Slides a rounded table's corner
  piece runs 1 px under each opaque native cell beside it (`snapshot.mjs` pushTable,
  `CORNER_RUN_UNDER_PX`; `snapshot_table.mjs` runUnderPolygon, over the table's own slot
  grid).
  - **Why.** Drive's thumbnail draws a native cell without anti-aliasing, filling each pixel
    whose top left corner it holds, and any shape anti-aliased. So the piece and its neighbour
    left a part-covered pixel between them wherever the cell's edge moved away.
  - **Why 1 px.** It leaves no seam at any of 16 phases in the 1600 and 800 px thumbnails or
    the PDF at 1× and 2×.
  - **The limits.** Half a thinner row or column at most. The corner square only under an
    opaque diagonal neighbour, a notch otherwise. Never under another corner cell.
  - The table stays native, and its grid is still the browser's. The PowerPoint deck is
    unchanged.
- **Ruling (D13, the outer edges, measured).** A piece's outer edges stay on the browser's lines.
  - In Google's PDF they equal the native cells' (0 levels).
  - In the thumbnail the native cells drop their part-covered outer row, which the piece draws
    at its cover. The piece is the nearer the UI (43 levels against the cells' 49).
  - No shape is drawn on whole pixels as cells are: a preset rect and a path both draw at
    1 − f.
  - Moving the outer edges onto the thumbnail's grid would match the cells there, and split them
    from the cells by 50 to 100 levels in the PDF.
  - Snapping the whole Google table is ruled out (B3).
- **Residual (D12, the weight).**
  - At 2×, Google's Medium draws 7–13 % lighter than Chrome's synthetic bold, against its own
    plain runs.
  - At 1×, the harness's truth scale, it is −6 % to +5 %, where Phase C's faux bold was +15 % to
    +31 %.
  - The one white-on-coral header (`slide-data-table`'s "Cost (list)") is 21–23 % lighter.
- **Residual (D13).** The light top row along the coral pieces in the thumbnail stays (B2's
  concern 5), the outer-edge ruling above. It now ends 1 px further right, because the piece's
  run under its neighbour lies on the table's own top edge.

### B6 fix round 1

Commits: `8b7896c8`, `21eb955f` and `4e17eaea`, then the docs.

- **Every slot across a side** (the review's sabotage 10, checking only the first slot,
  survived every case).
  - **New cases** in the Google-deck corner test:
    - `span-corner`: a corner cell spanning two columns, the second slot below it
      translucent;
    - `span-neighbour`: a corner cell spanning two rows beside a header cell spanning two
      columns, the slot under that cell translucent.
  - The test now reads every slot across a side and the diagonal slots beyond a span.
  - **Sabotage 10** now turns 4 tests red; a spanning cell owning only its origin slot turns 2
    red.
- **Literal boxes.** A test pins the top left piece's box in px, worked out by hand from the grid
  lines, not from the engine's rule.
  - It runs on two tables laid out with `table-layout: fixed` and 50 px rows:
    - `fixed` (88, 160, 389, 211);
    - `fixed-span` (88, 160, 313, 261).
  - A first form read the boxes off the auto-laid bodies. Their lines move with the live webfont
    the tests' deck CSS loads, by up to 0.08 px between runs, and it failed in two of three
    repeated runs. The formula test reads the deck's own grid, so it never did.
- **D12's scope** is recorded: the 500 face of two Google-hosted families was measured, and the
  rest follows from the same mechanism, unmeasured (Rulings from B6).
- **The top-row residual, measured** (CALIBRATION.md D13). Ending the run-under 1 px short of the
  table's outer edges stops the light row a thumbnail pixel sooner. But the seam's top pixel comes
  back: 48–55 levels in the thumbnail, and 28–33 at 1× and 4–8 at 2× in the PDF. Not adopted.
  As built, the PDF's anti-aliased top row is 17–19 levels darker at 1× (40–47 at 2×) over the
  one or two pixels where the strip and its neighbour cell overlap.
- **The slot logic in one place.** The corner-piece helpers moved to `snapshot_table.mjs`. They
  read the visual slot grid `collectTable` builds from `slotsOf`, carried on the TableLayout, and
  `slotOwners` is gone. Both corpora's decks, both targets, are identical to B6's final decks
  (`structural_manifest`, 146 and 202 entries).
- **Gate.** `uv run pytest tests/unit -q -p no:cacheprovider -k "export or huashu or google"`:
  1359 passed, 0 failed, 12 skipped. **Full suite** (`-n 6`): 18021 passed, 0 failed, 27 skipped.

### Owner-facing notes

- In the Google deck a synthetic-bold run is its lighter face, not bold: the font menu shows
  "DM Mono Medium" with bold off. Turning bold on there gives Google's faux bold, laid out wide.
- A moved data table still leaves its corner pieces behind, while its unfilled corner cells move
  with it (B3). In the Google deck each piece is 1 px larger than its cell on the sides it shares
  with other cells.

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/1UONRIfb_fq9htA2SYCI-V9Vhd8yt-J_IGJdGRyQilHU/edit
  ("Tellr export revamp — B6, in-repo corpus (pinned fonts, 2ccfb12d)")
- Design-system corpus: https://docs.google.com/presentation/d/1JxHFUA4hF3Sl2IGQh7-2huWGkFTc3xhHX2y8RNKrU9U/edit
  ("Tellr export revamp — B6, design-system corpus (pinned fonts, 2ccfb12d)")

The probe and test presentations B6 created were deleted by id and confirmed gone (404). The decks
earlier phases kept are untouched.

## Task 15, batch B7: the export document, a turned label, one-sided rounded borders and two harness findings (N2, N5, N7, H1, H2), engine `bc23aa55`

Commits: `f8da5216` (H1), `afc913d7` (N2), `c05e0712` (H2), `d5ff1d5f` and `3e6d9fdd` (N5),
`bc23aa55` and `8c7aa34f` (N7), then this ledger. The defects come from the real-deck matrix
(`.superpowers/sdd/2026-11-16-export-fidelity-snapshot-emit/task-15-matrix-report.md` §4 and §12).
Both corpora and the four matrix decks the defects come from (long-on, long-off, finance-on,
architecture-off) were run with `run.py --pin-fonts --powerpoint --gslides`, and so was a probe
corpus of the new tests' fixtures.

### How it was measured

- **The truth is now the UI's document** (H1). Every run below renders its truth from the slide as
  the slide viewer builds it, with `frontend/src/services/slideDocument.ts` itself.
- **Corpora:** the branch head against B6's final runs (`2ccfb12d`), whose truth was the export
  document.
- **Matrix decks and the probe corpus:** the head against the engine at `7d77df77` (a `git archive`
  extract) driven by the new harness, so both sides are scored against the same UI truth.

### Scores

**Corpora, B6 (`2ccfb12d`) → B7 (`bc23aa55`).**
- All four decks (two corpora, each written for PowerPoint and for Google Slides) are
  byte-identical to B6's, apart from the timestamps in `docProps/core.xml`. No corpus box has the
  N7 pattern, no turned label is a flex container, and every corpus slide sets its own font.
- The truth is the same pixel for pixel on 42 of 44 slides. Only those two slides' scores can
  move, and only with the truth:

| Slide | Why the truth differs | PowerPoint | Google |
|---|---|---|---|
| 11-chartjs-canvas | The UI runs the slide's script inline, so Chart.js draws its legend before DM Sans loads, in Times, and lays the doughnut out around it; the export runs its scripts after its chart wait | 1.06 → 2.18 | 1.63 → 2.72 |
| slide-content | 5 px at one level of 255: the export shell paints `html` white, which the UI leaves to the canvas | 2.20 → 2.20 | 1.75 → 1.75 |
| **mean, in-repo (17)** | | **1.82 → 1.89** | **2.37 → 2.43** |
| **mean, design system (27)** | | **1.62 → 1.62** | **1.52 → 1.52** |

B6's own renders of slide 11, scored against the new truth, are 2.18 and 2.72 too, so like for
like nothing moved. `summary.md` lists slide 11 as worse in both apps, and says beside it that its
truth changed.

**Matrix decks, `7d77df77` → `bc23aa55`, on the same UI truth.**

| Deck | Slides | PowerPoint mean | Google mean | Scores better / same / worse | What changed |
|---|---|---|---|---|---|
| long-on (DS on) | 28 | 5.74 → **2.93** | 6.22 → **2.15** | 56 / 0 / 0 | N2: its text inherits body's font |
| finance-on (DS on) | 3 | 10.52 → **5.90** | 11.78 → **4.98** | 6 / 0 / 0 | N2 |
| long-off (DS off) | 28 | 4.92 → 4.90 | 5.00 → 4.98 | 22 / 34 / 0 | N7 on 02, 03, 13, 22, 27; N5 on 20 |
| architecture-off (DS off) | 3 | 6.26 → 6.23 | 5.68 → 5.69 | 5 / 0 / 1 (03, Google +0.03) | N7 on 01 and 03 |

`summary.md`, every deck: "Worse than the baseline by more than 0.05: none."

**The probe corpus** (the N7 test slide and the seven N5 variants, `7d77df77` → head): the rounded
sides slide 0.63 → 0.20 in PowerPoint and 0.93 → 0.47 in Google; every axis variant improves, by up
to 0.09.

**Health.** Text loss is none in every deck of every run, and MODEL DROPS 0; no capture or export
failed. Determinism (Phase C's tool): two fresh pinned exports each of both corpora and of long-off
(which holds the new N5 and N7 constructs), both targets, have the same `structural_manifest` as
each other and as the final run's decks (146, 202 and 167 entries).

**Tests.** 48 new, each red first for its defect at `7d77df77` (or a guard, shown red by
sabotage), and 32 sabotages, every one red.
- **Gate.** `uv run pytest tests/unit -q -p no:cacheprovider -k "export or huashu or google"`:
  1407 passed, 0 failed, 12 skipped (B6: 1359 / 0 / 12).
- **Full suite.** `uv run pytest tests/unit -q -p no:cacheprovider -n 6`: 18069 passed, 0 failed,
  27 skipped (B6: 18021 / 0 / 27).

### What was measured on each defect (UI / before / after, at 1280 px)

**N2, long-on 05's "So what" paragraph.** The UI's document draws it in `Times-Roman` (the DevTools
protocol's face) and breaks it into 4 lines. Before, the export document drew `.SFNS-Regular` and
both decks wrote 5 lines. Now the export document draws `Times-Roman`, and both decks write the
UI's 4 lines, broken in the same places in PowerPoint and Google. The deck names the face "Times",
the stack's first family (N4 is B8's).

**N5, long-off 20's "IMPACT"** (ink rows inside the 470 px axis box):

| | UI | PowerPoint | Google |
|---|---|---|---|
| before | 347–399 | 561–606 | 553–606 |
| after | 347–399 | **354–399** | **345–399** |

The word now starts where the UI's starts, in both apps; its other end differs only by each app's
face for "Inter" (N4). On the probe's pinned DM Sans, every variant's ink is the UI's to a pixel in
both apps: centred, flex-start, flex-end, no rotation, vertical-lr, a start item under
`text-align: center`, and two anonymous items. Before, every variant but flex-start lay elsewhere:
at an end of the axis, or, for the start item under `text-align: center`, at its middle.

**N7, the corners** (pixels within each box's two left corners more than 48 levels off the UI):

| Deck, slide | Boxes | PowerPoint | Google |
|---|---|---|---|
| long-off 02 | 5 | 340 → 0 | 325 → 5 |
| long-off 03 | 3 | 204 → 36 | 195 → 36 |
| long-off 13 | 5 | 577 → 206 | 553 → 177 |
| long-off 22 | 8 | 528 → 0 | 512 → 4 |
| long-off 27 | 4 | 272 → 0 | 260 → 2 |
| architecture-off 01 | 3 | 133 → 60 | 118 → 63 |
| **all** | 28 | **2054 → 302** | **1963 → 287** |

The 5× crops show each side following the corners and tapering, in both apps. What remains is the
fitted shadow's edge (long-off 13's tiles) and the 1 px grey border's anti-aliasing.

On the probe's boxes (each box's four corners, PowerPoint / Google, before → after):

| Case | Before | After |
|---|---|---|
| left-only | 69 / 126 | 1 / 2 |
| top-only | 157 / 191 | 1 / 1 |
| left and right, two colours | 424 / 441 | 9 / 12 |
| wider than the radius | 34 / 119 | 0 / 0 |
| elliptical | 446 / 503 | 9 / 14 |
| the accent card | 171 / 221 | 0 / 0 |
| turned | 60 / 85 | 1 / 3 |
| clipped | 139 / 139 | 1 / 2 |
| four alike | 217 / 337 | 6 / 4 |
| overlapping inner radii | 344 / 345 | 0 / 1 |
| guard: the uniform outline | 0 / 40 | 0 / 40 |
| guard: the square box | 0 / 99 | 0 / 99 |
| guard: the dashed side | 116 / 146 | 116 / 146 |

**H1, the truth.** On a template deck the truth now shows the slide's ground, as the UI does (the
test's template fixture: the section's F9F7F4, where the export document showed the page's
0E1A1F).

**H2, the text-loss comparison.** On the head's long-off decks the old comparison reports
"1Financials" and 4 more words (02), "1$45M", "2$30M" and "3210" (03), and "1Board" and 3 more
(27); on the matrix's dense-tpl18 decks, "Iceberg," and "Catalog,". The new one reports nothing.
The `7d77df77` engine logged the same words as `[html2pptx] text missing` on long-off; the head
logs none.

### Rulings from B7

- **Ruling (N2).** The export shell sets no inherited property the UI's shell does not, a font
  above all. Fontless text gets Chrome's default face (Times on the Mac); no named face replaces
  it. Every route builds through `build_slide_html`, and the frontend's capture shells set no font.
  The typeface the deck names for such text is B8's (N4).
- **Ruling (N5).** A flex or grid container's text is its anonymous items', which the container
  places. Each item is a turned item over its own text, written as unturned text's `'text'`
  placement writes it. A turn root whose text is its own keeps its layout box.
- **Ruling (N7, the construct).** A solid side of a box whose corners round is the region CSS
  paints for it: a filled `custGeom` polygon (the path support D3's clipped shapes use), its arcs
  within 0.05 px. It is not built of `arcTo` pieces: a side's arcs start and end at the dividing
  line, part-way round an elliptical quarter, and how the apps read a partial elliptical `arcTo`'s
  angles is unmeasured, where a polygon draws the same in both (D3). It is native and editable,
  and recolours and moves whole.
- **Ruling (N7, the geometry, measured against Chrome's pixels).** Inner radii are the outer ones
  less the border, floored at 0, and not scaled where they overlap their side (scaled, a 170 px
  corner beside a square one lost 17 of Chrome's border pixels). The dividing line runs from the
  border box's corner through the padding box's (Chrome's border painter). Neighbours painted
  alike are one path; four alike, two.
- **Ruling (N7, kept as before).** A uniform border stays the shape's outline, byte for byte. A
  square box, a dashed or dotted side, a fragment `box-decoration-break` slices, and a box whose
  padding box is empty keep a line per side.
- **Ruling (H1).** The harness's truth is the UI's document, built by `slideDocument.ts`; the
  fixture format's deck scripts run as each slide's scripts. The harness needs
  `frontend/node_modules` (`npm ci` in `frontend/`), and stops before exporting without it.
- **Ruling (H2).** A word is also found when it is written across items' edges: a suffix of one
  item, then whole items, then a prefix of another, each piece at an edge. A word over 64
  characters is not looked for in this way, because page script writes the reference. The
  sidecar's check and the harness's share the rule and the limit.
- **Residual (11-chartjs-canvas).** On a cold load the UI draws the corpus chart's legend in Times,
  and the export draws it in DM Sans. The truth records the UI as it is; the export is not changed
  to match a race in the UI.
- **Residual (N7, Google, architecture-off 03, +0.03).** All of it lies on the two part-covered
  rows of a 4 px band's straight middle at y 223.8. Chrome paints the border on whole pixels (rows
  224–227 at 1×). PowerPoint, before and after, and Google's path draw it where the model places
  it. The corners improve in both apps.
- **Limit (N7).** A dashed or dotted side of a rounded box is still a straight line.

### B7 fix round 1 (after B8; at `e455a046`)

Commits: `c7a95282`, `80be4c3a`, `179cf364`, `f2ba234e` and `e455a046`, then the docs.

- **H2: a word written across items is read only across neighbours on one line.** The review
  found B7's rule took a suffix of any item and a prefix of any other, so a lost "AI", "ML" or
  "KPI" chip was found from unrelated boxes. The original comparison had the same hole: it ran
  every item's text together in paint order, and a lost chip's two segments are consecutive in
  that order ("Customer Data" + "Insights" holds "ai"). Both are replaced.
  - **The rule.** Both twins find a word in one item's own text, or across the joins of a chain of
    neighbours. Neighbours are unturned one-line items of one direction that share a line (overlap
    by more than half the shorter's height, `snapshot_text.mjs`'s own rule). The head's text starts
    from 0.25 em before the tail's ends to 1.5 em after it, in the larger of their non-script
    sizes, each text's ends its box's less the snapshot's slack (6% + 4 px). Each item runs on into
    its nearest neighbour.
  - **The bound.** The search reads at most 1,024 items; no real slide paints more than 51. The
    chains are no longer than the slide's text, so B7's 64-character word limit is gone.
  - **Measured on the slide models.** An atomic inline's edge, slack removed, is 18 px (1 em) for
    long-off 02's numerals and 9 px (0.45 em) for dense-tpl18 03's chips. A lost chip on the
    review's probe leaves 43 to 51 px (2.1 to 2.5 em).
  - **Every real deck** (19 matrix decks, both corpora, both targets): 12,523 words are in one
    item, 26 across neighbours, and 6 hidden; none is lost. The 26 are B7's 14 and 12 footnote and
    chip joins the paint-order join used to find. The sidecar's own check logs no `text missing`
    line on any matrix deck.
  - **Real-loss controls**, red at `dc18ceac`: the review's probe with its chips lost, in both
    twins, in the review's order and in paint order; and a real export with its chip boxes taken out.
- **N7: a four-alike rounded border is one region.** B7 split four sides painted alike at the top
  left and bottom right dividing lines (its comments said top right and bottom left). Measured on a
  six-box probe against Chrome, on the band's interior pixels:

  | View | Two regions, on the dividing lines | One region |
  |---|---|---|
  | Google Slides' own drawing (thumbnail, 1600 px) | 19–64 levels lighter | 0 |
  | Both apps' PDFs, MuPDF at 8× | 42–63 | 0–1 |
  | The harness's PowerPoint view (1×) | 8–16 | 0–1 |

  The band elsewhere reads 0–1 in every view. The one region is the whole border area, its edge
  cut open along the top left dividing line. PowerPoint's own raster could not be read: its
  AppleScript PNG save writes nothing. No deck of the corpora or the matrix has the pattern; all
  stay byte-identical.
- **H1: a broken frontend install.** esbuild's JavaScript without its platform binary loads, and
  fails only when it builds. `ui_document.mjs` now stops on one `[export-fidelity]` line, exit 2,
  naming `npm ci` and esbuild's first line, and writes no document unless it has built them all.
  `main()` builds the UI's documents before it writes anything.
- **N7: the border-region geometry lives in `snapshot_borders.mjs`**, the code line for line, its
  helpers passed in through `env`. Byte-identical: both corpora, both targets, equal B8's final
  decks; long-off and architecture-off, both targets, equal their exports before the move and B8's
  matrix decks.
- **N2: the frontend capture shells are pinned.** `pdf_client.ts`, `pptx_client.ts` and
  `screenshotCapture.ts` each declare the inherited properties `SLIDE_PREVIEW_RESET_STYLE` does.
- **Harness**, both corpora, `--pin-fonts --powerpoint --gslides`, against B8's final runs. Scores
  are unchanged: PowerPoint / Google 1.89 / 2.43 and 1.62 / 1.52. The truth is pixel-identical, and
  the decks are byte-identical in both targets. No text is lost, and there are 0 MODEL DROPS.
- **Gate**, serial, `-k "(export or huashu or google) and not timeout"`: 1425 passed, 0 failed,
  13 skipped; the two other tests that name "timeout" (`test_export_routes_off_event_loop.py`): 2
  passed. **Full suite** (`-n 6`), without the timeout file: 18089 passed, 0 failed, 28 skipped. The
  timeout file's 120 tests did not run in this round: the session's permission check refused them,
  since their watcher kills every Playwright browser on the machine.

Google Slides decks kept for this round:
- In-repo corpus: https://docs.google.com/presentation/d/1A-UOX8j1qQSBrJ5ONB7AKaHcNHLSHPre5r3xnvjtRPw/edit
  ("Tellr export revamp — B7 r1, in-repo corpus (pinned fonts, e455a046)")
- Design-system corpus: https://docs.google.com/presentation/d/17iFvm07taYC42FQ1dSJByKfQUQZvC4uECejBTkdnbOM/edit
  ("Tellr export revamp — B7 r1, design-system corpus (pinned fonts, e455a046)")

The two seam-probe presentations this round created were deleted by id and confirmed gone (404).

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/1emBke93JxrI6tKvPdNTgRSQH8JKSD0h6AstyoWZne9c/edit
  ("Tellr export revamp — B7, in-repo corpus (pinned fonts, bc23aa55)")
- Design-system corpus: https://docs.google.com/presentation/d/1Qrbbgg01v3obJrrfYFpteJrb2nD11rSMV8FALiAEwig/edit
  ("Tellr export revamp — B7, design-system corpus (pinned fonts, bc23aa55)")

The matrix-deck and probe presentations B7 created (12) were deleted by id and confirmed gone (404).
The decks earlier phases kept, and the T15 decks, are untouched.

## Task 15, batch B8: text on Apps laid out and named as the user's machine draws it (N3, N4), engine `a2ce66e6`

Commits: `1d81452c` (N3: the font bundle, `setup.sh`, `FONTCONFIG_FILE`, the wheel), `ae4c6cfe`
(N3: unhinted glyph layout on Linux), `a2ce66e6` (N4: the face written; D8's symbols), then this
ledger. The defects come from the real-deck matrix
(`.superpowers/sdd/2026-11-16-export-fidelity-snapshot-emit/task-15-matrix-report.md` §4 N3 and
N4, §12). Dev build `0.5.9.dev3` (`a2ce66e6`) carries them; the wheel is 34.2 MB (32.0 MB at
`0.5.9.dev2`, +2.4 MB).

### How it was measured

- **On Apps.** A throwaway app on the dev workspace (`tellr-fonts-probe`) ran the published
  sidecar's own `setup.sh`, tarballs and Playwright Chromium 147, with the B7-head engine and the B8
  engine side by side: the container's faces and fontconfig, widths and faces through the DevTools
  protocol, and every matrix deck exported by each engine. Then the real route: `0.5.9.dev3` on a
  throwaway devloop instance (`fonts-probe`), a session of probe slides and matrix slides exported
  through `/api/export/pptx/editable/huashu/from-html`. Both apps were deleted afterwards.
- **Against the laptop.** The same export documents, built by the production `build_slide_html`,
  exported on the Mac by the same engine; single-line box widths and every box's lines compared
  (width = the box less the engine's slack, `(w - 4) / 1.06`).
- **Corpora:** both, `run.py --pin-fonts --powerpoint --gslides`, against B7's final runs.

### Scores

**Apps against the laptop, the 19 matrix decks** (single-line width ratio, median / p90 of the
deviation; text boxes whose lines differ):

| Deck | Before (B7 engine, base image) | breaks differ | After (B8, the bundle) | breaks differ |
|---|---|---|---|---|
| architecture-off | 1.123 / 18.0 % | 7 of 61 | **1.000 / 0.0 %** | **0** of 61 |
| architecture-on | 1.126 / 17.2 % | 6 of 38 | **0.980 / 6.6 %** | **2** of 38 |
| architecture-tpl17 | 1.000 / 3.7 % | 3 of 60 | **1.000 / 0.0 %** | **0** of 60 |
| dataviz-off | 1.135 / 20.0 % | 4 of 28 | **1.000 / 0.0 %** | **0** of 28 |
| dataviz-on | 1.263 / 32.6 % | 4 of 23 | **1.000 / 0.0 %** | **0** of 23 |
| dataviz-tpl18 | 1.002 / 2.8 % | 2 of 26 | **1.000 / 0.0 %** | **0** of 26 |
| dense-off | 1.145 / 18.7 % | 1 of 77 | **1.000 / 0.0 %** | **0** of 80 |
| dense-on | 1.260 / 31.6 % | 4 of 84 | **1.000 / 0.0 %** | **0** of 88 |
| dense-tpl18 | 0.995 / 4.2 % | 0 of 83 | **1.000 / 0.0 %** | **0** of 83 |
| edited-off | 1.154 / 21.4 % | 6 of 45 | **1.000 / 0.0 %** | **0** of 46 |
| edited-on | 1.293 / 35.2 % | 13 of 44 | **1.000 / 0.0 %** | **0** of 44 |
| finance-off | 1.169 / 22.4 % | 2 of 33 | **1.000 / 0.0 %** | **0** of 33 |
| finance-on | 1.240 / 34.7 % | 3 of 32 | **1.000 / 0.0 %** | **0** of 32 |
| finance-tpl18 | 0.999 / 2.5 % | 0 of 41 | **1.000 / 5.3 %** | **0** of 41 |
| long-off | 1.152 / 23.6 % | 24 of 309 | **1.000 / 0.0 %** | **0** of 311 |
| long-on | 1.250 / 32.3 % | 34 of 334 | **1.000 / 0.4 %** | **0** of 335 |
| strategy-off | 1.169 / 21.9 % | 10 of 68 | **1.000 / 0.0 %** | **0** of 69 |
| strategy-on | 1.262 / 32.7 % | 10 of 67 | **1.000 / 0.0 %** | **0** of 67 |
| strategy-tpl15 | 0.996 / 4.3 % | 0 of 74 | **1.000 / 0.0 %** | **0** of 74 |

All 19 decks are within the brief's ±1 % median. Two miss the p90 bound of 2.5 %, each explained:
- **architecture-on** names DM Sans without loading it, and the owner's Mac has it installed: the
  laptop draws DM Sans, Apps Liberation Sans (written Arial). Its 2 boxes with other breaks are
  these.
- **finance-tpl18** (5.3 %): its six delta pills' ▲ falls through DM Sans to `system-ui`, which is
  SF on the Mac, narrower, and Liberation Sans on Apps, whose ▲ is Arial's. D8 writes the ▲ in
  Arial, so on Apps the box now holds exactly what the apps draw; the laptop's is the Mac's
  system-face residual (Rulings, below).

The real route agreed: the devloop instance's export of 11 slides (two probe slides, finance-off,
strategy-off and long-off 16) has the same `structural_manifest` as the probe app's export of the
same documents with the B8 engine and the bundle, and against the laptop a median of 1.000, p90 0.05 %
and 0 of 137 boxes with other breaks.

**The laptop's export through Google and PowerPoint** (the brief's acceptance 2). finance-off and
strategy-off, written in Arial throughout, have none of N4's overlaps: "$2.48B" and "35.0%" are one
line each and clear of their labels, the subtitles clear the headings and the table, "Q2 2026" is one
line. PowerPoint's PDF embeds only Arial and Arial Bold (Calibri before). Scores against the UI,
PowerPoint / Google: finance-off 8.76 / 8.59, 7.82 / 7.66, 2.81 / 2.34; strategy-off 1.38 / 1.05,
1.80 / 1.74, 1.84 / 1.69, 1.26 / 1.24.

**Corpora, B7 (`bc23aa55`) → B8 (`a2ce66e6`).** All four decks are identical to B7's
(`structural_manifest`): every corpus run is a loaded webfont, so no typeface changes. Every score is
unchanged; means, PowerPoint / Google: in-repo 1.89 / 2.43, design system 1.62 / 1.52. `summary.md`,
both: "Worse than the baseline by more than 0.05: none."

**The face written, against the protocol.** Every run of the 19 matrix decks and both corpora (162
documents): on Apps 3,147 agree, 0 disagree, 49 ambiguous (text in nodes drawn in different faces),
118 unmatched (generated text); on the Mac 3,135 agree and 13 differ only in name (architecture-on's
installed "DM Sans Medium" static, written "DM Sans" by the rule for a family the page did not load).

**Characters that reach DejaVu on Apps.** None in any of the 162 documents: no text node is drawn,
even in part, in a face other than Liberation or a loaded webfont (a control slide of ✓★◆ shows
DejaVu, so the read can see it). ◔◑◕ on long-on 12 are Liberation Serif's own, written in MS
PGothic; ▲ is Liberation's, written in Arial. On the probe slide through the real route, ▲▼→ in an
Arial run are written Arial and ✓★◆ (DejaVu's on Apps) MS PGothic.

**Time.** On Apps, the 28-slide decks, three runs each with the engines alternating: long-off 25.26 →
25.63 s (median, +1.5 %), long-on 25.72 → 25.93 s (+0.8 %), 7 to 13 ms a slide. The 19 decks once
each: 118 slides 126.6 → 127.5 s (+0.7 %).

**Health.** Text loss is none in every deck of every run. Under the strict pre-H2 rule (`7d77df77`'s
`check_text_loss`, from a read-only extract), the final runs flag nothing, and the matrix decks,
laptop and Apps alike, flag only B7's two known patterns: inline-block numerals joined to the next
word (long-off 02, 03 and 27: "1Financials", "1$45M", "3210" and 9 more) and chip commas
(dense-tpl18 03: "Iceberg,", "Catalog,"); no other word. MODEL DROPS 0 and no capture failure
anywhere. Determinism: two fresh pinned exports of each corpus, both targets, match each other and
the final run (146 and 202 entries); two exports of long-off match, on the laptop and on Apps (167).

**Tests.** 46 new (test_huashu_font_bundle 23, test_export_snapshot_launch 3,
test_export_snapshot_drawn_faces 20), each red first at the parent commit (or a guard), and 36
sabotages, every one red; three first survived (quoting a generic, the webfont flag, the coverage
probe's family) and each got a case that then caught it. 3 typography tests were updated for the
intended changes (the platform stack is Arial; ✓ in DM Sans is MS PGothic).
- **Gate** (serial, the timeout test included): `uv run pytest tests/unit -q -p no:cacheprovider -k
  "export or huashu or google"` gave 1453 passed, 0 failed, 13 skipped (B7: 1407 / 0 / 12; the new
  skip is the fontconfig resolution test, which needs a fontconfig library, as on Linux CI).
- **Full suite:** `uv run pytest tests/unit -q -p no:cacheprovider -n 6` gave 18115 passed, 0
  failed, 28 skipped (B7: 18069 / 0 / 27).

### Rulings from B8

- **Ruling (N3, the faces).** The sidecar ships Liberation Sans, Serif and Mono 2.1.5, their four
  styles, metric-compatible with Arial, Times New Roman and Courier New, in
  `fonts-liberation.tar.gz` (2.4 MB), built reproducibly from the pinned release and its SHA-256 by
  `scripts/sidecar_fonts/build_fonts_tarball.py`. `setup.sh` extracts it as the other tarballs are
  and writes `fonts/fonts.conf` with absolute paths; `sidecar_subprocess_env` sets
  `FONTCONFIG_FILE`, the one variable the env allowlist gains. The extracted `fonts/` is never
  committed, uploaded or shipped.
- **Ruling (N3, the config).** The core fonts a desktop has and the generics `sans-serif`,
  `system-ui`, `serif` and `monospace` are their Liberation faces; any other name draws nothing,
  so a stack goes on as on a desktop, and fontless text is the standard face, Liberation Serif. The
  base image's DejaVu stays for the characters Liberation lacks and no stack can name it.
- **Ruling (N3, hinting).** On Linux Chromium lays glyphs out unhinted
  (`--font-render-hinting=none`); the Mac's launch is unchanged.
- **Ruling (N4).** A run whose family is no loaded webfont is written in the face the browser drew,
  found by probing each family of its stack alone on its characters (an in-page test of the
  browser's own matching; the protocol's per-node faces cannot attribute characters), by a name
  every app draws with its metrics: the table faces for their twins and for the generic and system
  faces (as the container draws them), Times New Roman where nothing draws, a later loaded webfont
  by its own name, any other installed face as itself, and never DejaVu. Review Focus 3 holds.
- **Ruling (D8, symbols).** A symbol outside WGL4 that MS PGothic and MS Gothic both draw alike in
  PowerPoint and Google (982, `SYMBOL_COVERAGE`) is a run of its own in MS PGothic (MS Gothic in a
  monospace run) wherever the written face lacks it in the apps: for Arial, Times New Roman and
  Courier New, all but the few each draws itself; for a webfont, by the coverage probe.
  `coverage_font.mjs` needed no change: its probe font covers every code point.
- **Residual (the Mac's system face).** Text a Mac draws in SF or another face no app has is
  written as the container's face: the deck on Apps is laid out at that face's widths, a laptop
  export at the Mac's (finance-tpl18's ▲, `system-ui` up to 9 % at SF's extremes).
- **Residual (symbol advances).** MS PGothic's Harvey quarters are 0.5 em where Apps lays them out
  at 0.6 em; centred in their cells, they sit where the browser's do.
- **Limit (Windows).** MS PGothic and MS Gothic are unprobed on Windows; on non-Japanese Windows
  they come with the optional Japanese Supplemental Fonts, and without them PowerPoint falls back
  per glyph, today's behaviour.
- **Limit (CJK and emoji).** The container has no CJK or emoji face (Noto Sans CJK alone is 95 MB
  zipped): such text is laid out at the replacement glyph's width and shows boxes in a picture, as
  before the bundle; the deck keeps every character.

### B8 fix round 1 (at `a4974a15`)

Commits: `ea15b8a5` and `a4974a15` (item 1), `01096995` (item 2), `024aaed7` (item 3), `4253ad7b`
(item 4), `eb373bf8` (item 5), `4f014e0c` (item 6), `adecdaf9` (item 7), then this ledger.

- **A deck's own loaded webfont named DejaVu is written as itself** (amends the N4 ruling's "never
  DejaVu"). B8 skipped it and wrote the next face of the stack; the controller's caution was about
  the container's fallback DejaVu alone. A loaded webfont is the page's own bytes, the same on the
  laptop and on Apps, and the face the layout was measured in.
  - **The rule.** `resolveWrittenFaces` returns early for every loaded webfont, and skips a
    stack's DejaVu token only where it is no loaded webfont. The container's DejaVu stays
    unwritten, guarded in the engine and by the sidecar's fontconfig (below).
  - **The cases.** `"DejaVu Sans", Arial` and `"Missing Face", "DejaVu Sans", sans-serif`, with
    the face loaded, are written "DejaVu Sans". A run of only characters it lacks keeps it too:
    ½ is written in Arial and ◔ in MS PGothic, by D8. The same slide with the face renamed Twin
    Sans is written alike.
  - **Cleanup.** The metrics module no longer takes `baseImageFace`, which it stopped calling; the
    output is byte-identical.
- **setup.sh extracts the font bundle whole or not at all.** The check keyed on
  `fonts/fonts.conf.in` and on `fonts/`'s mtime, which every boot's config write moves. So with
  B8's script, a bundle cut off halfway left 7 of 12 faces, with a config naming them, on every
  later boot. Now:
  - the bundle is extracted into `fonts-staging/`, then moved into place only once `tar` has
    succeeded (the old `fonts/` moved aside) and stamped (`fonts/.bundle-complete`);
  - the up-to-date check keys on the stamp. So a failed extraction is tried again on the next
    boot, and one that fails leaves the bundle in place as it was;
  - `fonts.conf` is written only for a stamped bundle, and one beside a partial bundle is removed;
  - every command of the font step runs in an `if` or `&&` list, so a failing `rm` or `touch`
    cannot end the script before the Chromium step. Steps 1 and 2 are unchanged;
  - `fonts-staging/` is kept out of git, deploy uploads and the wheel, as `fonts/` is.

  The same cut-off bundle through the new script leaves no faces and no config, and the next
  boot extracts all 12 faces (the release's bytes) and writes the config. The setup tests pass
  under bash and under dash, the container's `sh`.
- **The fontconfig's DejaVu rename is pinned by what it resolves.**
  - **The test.** The resolution test gains `"DejaVu Sans": "Liberation Sans"`. It first checks
    that the same config without its DejaVu rule matches DejaVu Sans itself, so the row proves the
    rename wherever it runs.
  - **Linux only; not run in this round.** The Mac has no fontconfig library and no DejaVu. The
    session's permission check refused fetching a wheel that bundles them, and the round made no
    deploys. Its control-config helper was checked on a config `setup.sh` wrote.
- **Reproducibility is proved on the tar stream.** The rebuild test compares the decompressed
  streams. The committed bundle, recompressed at another level, fails the old assertion and passes
  the new one.
- **Operators can see the bundle.**
  - `/api/export/pptx/editable/huashu/available` answers `checks.font_bundle`, and every slim
    check is now asserted to be a boolean.
  - Its server-side diagnostics add `fontconfig_file`, `liberation_faces` and
    `setup_log_font_lines`: setup's `[setup] … fonts` lines, read from the whole log, whose
    40-line tail Chromium's download output fills.
  - Availability is still not gated on the bundle; a test pins that.
- **The in-repo corpus gains a slide with no webfont.** `18-ds-off-stack-kpis-table-legend` sets
  the DS-off stack on KPI figures over their labels (finance-off 03's shape), a small table, and a
  ◔◑◕ / ✓ legend. Its first scores, PowerPoint / Google, are **2.93 / 2.48**, the same in a run of
  it alone; no text is lost, and there are 0 MODEL DROPS and 1 capture.
  - Both decks write it in Arial, with MS PGothic for its 9 symbols. PowerPoint's PDF embeds only
    Arial, Arial Bold and MS PGothic, and Google's conversion has only Arial and MS PGothic runs.
  - No figure wraps or overlaps its label in either app.
  - Both apps draw its Harvey quarters smaller than the UI does: they are MS PGothic's glyphs, by
    B8's D8 rule.
- **Wording.** The app.yaml template's bootstrap comment names the font bundle. export-features.md's
  accuracy figures now agree with CALIBRATION.md N4: on a Mac, 3,135 runs agree and 13 differ in
  name only.
- **Harness.** Both corpora, `--pin-fonts --powerpoint --gslides`, at `4f014e0c`, against B7 fix
  round 1's final runs.
  - **Scores.** Every shared slide's score is unchanged, and none is worse. The means, PowerPoint /
    Google, are 1.89 / 2.43 over the in-repo corpus's 17 shared slides and 1.62 / 1.52 for the
    design-system corpus.
  - **Decks.** The truth is pixel-identical on every shared slide. In both targets, slides 1 to 17
    and all 27 design-system slides are byte-identical to the baseline's. The in-repo decks differ
    only by slide 18 and the deck-level lists that name it.
  - **Health.** No text is lost, and there are 0 MODEL DROPS and no capture failures.
  - **Determinism.** Fresh pinned exports of both corpora at `a4974a15`, both targets, equal the
    final runs part for part.
- **Tests.** There are 11 new collected tests (test_export_snapshot_drawn_faces 2, one of them the
  inverted `never-dejavu` case it replaces; test_huashu_font_bundle 9). 5 tests are strengthened:
  the rebuild, the resolution, the two packaging tests and the slim-response leak test. The
  `document.fonts` helper now reads a face declared with no weight (`normal`) as 400. Each new
  test was red first at its parent, or is a guard.
  - **Sabotages.** 29 were red, every file restored byte for byte, and item 2's under dash too.
    Removing the early return for every webfont was green at first; the lacking-characters case
    added for it then caught it.
  - **Green, each explained.** Two leave what is under test unchanged: another deflate level, and
    the PAX tar format, which writes the same bytes. Dropping the engine's own DejaVu check shows
    only where DejaVu is installed, so on Linux.
- **Gate** (serial): `-k "(export or huashu or google) and not timeout"`, with
  `--ignore=tests/unit/test_pptx_from_html_huashu_timeout.py` so the file is not imported. Every
  test in that file has "timeout" in its id, so the selection is the same. It gave 1435 passed, 0
  failed, 13 skipped (B7 r1: 1425 / 0 / 13). The two other "timeout" tests: 2 passed.
- **Full suite** (`-n 6`), without the timeout file: 18099 passed, 0 failed, 28 skipped (B7 r1:
  18089 / 0 / 28).
- **The timeout file was not run in this round.** Its watcher kills every Playwright browser on the
  machine. Its pinned-corpus test now expects the 18 slides; the owner runs it.

Google Slides decks kept for this round:
- In-repo corpus: https://docs.google.com/presentation/d/1oDz9LnDlAqgAZRVFXznnKS26lmvvth-RabIBd-M6mWM/edit
  ("Tellr export revamp — B8 r1, in-repo corpus (pinned fonts, 4f014e0c)")
- Design-system corpus: https://docs.google.com/presentation/d/1EZvCSaWnhzxEOcALA0zxqqIWOHVC6lDBJFjPrFWPgR4/edit
  ("Tellr export revamp — B8 r1, design-system corpus (pinned fonts, 4f014e0c)")

The one probe presentation this round created was deleted by id and confirmed gone (404).

### Google Slides decks kept for the owner

- In-repo corpus: https://docs.google.com/presentation/d/1mrsZcZayX1iMWjNjkU2G4Yt4vB4PS-iCf_KVcSvGz_w/edit
  ("Tellr export revamp — B8, in-repo corpus (pinned fonts, a2ce66e6)")
- Design-system corpus: https://docs.google.com/presentation/d/1mn3hEPZ17MDrqn_4TALlk1RIBGNNNrH3jJSPTP61dXw/edit
  ("Tellr export revamp — B8, design-system corpus (pinned fonts, a2ce66e6)")

The probe and matrix presentations B8 created (5) were deleted by id and confirmed gone (404). The
decks earlier phases kept, and the T15 decks, are untouched.

## Final fix A: security, robustness and CI

The final whole-branch review's security, robustness and CI findings (C1, S1, I1, I2, I3, I4, M1,
M2, M4, M7, M8, M9, M12, M13). Fix B takes fidelity (I5 to I10, M3, M5, M6, M10, M11, the triage's
FIX lines). Commits `7d427e44..68459255` on `feat/export-revamp`, each pushed.

- **C1, the export page reads nothing but its slide and the CSP's hosts** (`7d427e44`).
  - **The guard.** Each slide renders in a browser context of its own whose every request Node
    decides (`request_guard.cjs`, Playwright routing). Allowed: the slide's own file URL exactly,
    `data:`, `blob:`, and https to the hosts `SLIDE_CSP` allows for that kind of request (scripts
    jsdelivr and Tailwind's, stylesheets Google Fonts, fonts jsdelivr and gstatic). Aborted with
    `ERR_ABORTED`, which commits no error page (measured: `failed` commits Chrome's error page
    naming the denied path): any other file, http, loopback and link-local, other hosts, frame
    navigations, WebSockets. Popups are closed. A main-frame navigation away (a request, or a
    `blob:` page, which is no request) stops the slide at once; it fails alone.
  - **One source for the hosts.** `html_safety.slide_csp_request_hosts` derives them from
    `SLIDE_CSP`, refusing a source it could not mirror; the wrapper passes them as
    `allowedHosts` in the stdin payload (optional: without it no https host loads).
  - **Measured first.** Routing intercepts `file:` for every request type; a redirect hop is not
    re-routed (so frames, which could show a redirect's page, get no CSP host); a `blob:`
    main-frame navigation is not routed (hence the main-frame URL watch); aborting a navigation
    during load hangs `page.goto` for its 30 s (hence stopping the slide, not waiting on it).
  - **Red first:** the unguarded engine leaked the file's text, the directory listing and the local
    server's page into the deck, a local picture into a capture, and hit the probe server at
    `/location`, `/popup`, `/fetch`, `/xhr`, `/socket`.
- **I1, a per-slide deadline** (`e398e9b6`). `SLIDE_DEADLINE_MS` is 30 s, launch to last read. The
  slowest slide of both corpora and the long-off, dataviz-tpl18 and finance-off matrix decks takes
  3.2 s on the Mac (a Chart.js slide), the median 1.0 s; the engine's own bounded waits add up to
  26 s, so the deadline fails no slide they let through. Red first: a blocked slide between two
  others lost the whole deck at a 90 s deck timeout; green, 2 slides and 1 failure in about 33 s.
- **I2, no temp files left behind** (`48c6c91f`). `emit_deck.mjs` removes its `huashu-deck-*`
  directory in a `finally`; the sidecar's `TMPDIR` is the export's `TemporaryDirectory`, made
  inside the `TMPDIR` it would otherwise get. The timeout file's browser watch matches a profile
  at any depth under its scope (checked by hand on a real export; the file itself is the owner's).
- **S1, deck content stays out of the app's logs** (`d92a6b56`). Counts by default: the summary's
  `hiddenWords`, the text-loss line's `{"slideIndex", "words"}`, a validation quote by its length,
  a page-made message by its length; errors that hold no page text carry `logMessage` and are
  logged whole. Page console lines are cut at 1,000 characters (the engine's longest, measured over
  its suites: 249), at most 100 a slide per stream. `TELLR_EXPORT_DEBUG_TEXT=1` adds the words; it
  is not in the env allowlist, and the harness adds it for its own runs (`sidecar_debug_text`).
  The Google Slides route logs an all-failed deck by its count.
- **I4, the export suites load nothing from the network** (`0f1b2d7f`). `tests/unit/conftest.py`
  gives every export no host and fails an export whose requests were aborted (the C1 module is
  `requests_blocked`; a `network` test gets the CSP's hosts). `DECK_CSS` embeds the corpus fonts;
  Chart.js 4.4.1 is vendored (npm's `chart.umd.js`, jsdelivr's hash pinned, MIT licence) and
  written inline; `measure.cjs` refuses a document that loads remotely. Running offline found the
  harness run, the depth-parity exports (a parsed deck's default Chart.js URL) and three
  pinned-fonts comparisons.
- **I3, CI runs the engine's suites** (`fdb20a10`). The `export-engine-tests` job (the unit job's
  triggers, plus a `sidecar` paths filter for the sidecar, the harness and the font build) extracts
  `node_modules.tar.gz`, installs Chromium with its system dependencies, runs `npm ci` in
  `frontend/`, and runs `-k "export or huashu or google" -n auto`, the timeout file included.
  Validated with the repo's workflow guards and the GitHub workflow JSON schema; actionlint is not
  installed here, and CI cannot run from here. Reproduced locally in a clean worktree with a fresh
  extract: without `frontend/node_modules` the UI-document tests skip (M7's gate verified by
  removing it: the test fails asking for `npm ci`), with it 1532 passed in 9 min 46 s at `-n 6`.
  Expected on a 4-vCPU runner: 25 to 35 minutes with setup (timeout 45). The suites have never run
  on Linux before this job, so its first run may show platform differences.
- **M1, M12** (`22047c47`): `HuashuUnavailableError` 503 (the only status the frontend falls back
  on), `HuashuTimeoutError` 504, any other `HuashuExportError` 500, on both routes.
- **M2** (`54e1b05a`): the model check keeps each number only in the range its XML attribute takes
  (alpha 0..1, lengths from 0, a line's width at most 2112 px, a shadow angle under a turn, a
  rotation a turn either way, a run's size 0 or 1 to 4000 pt, trackings 2000 pt either way,
  spacing at most 1584 pt, path points within 100 in). Insets and cell margins stay any finite
  number: they are signed (`ST_Coordinate32`), and a first version requiring 0 dropped real turned
  labels, whose top inset is -0.00002 px.
- **M4** (`ccf1e43f`): the Test PyPI build builds the artifacts, the wheel with the sidecar, and
  runs `verify_app_wheel.py`. **M7, M8** (`494d39ee`). **M9, M13** (`1ab65d05`): the gzip header
  pinned; a fresh `mktemp -d` staging directory per boot; the upgrade-boot window documented;
  `HUASHU_SETUP_LOG`. **Docs** (`68459255`).
- **Tests.** 162 new collected Python tests and 5 frontend: test_export_request_guard 62,
  test_export_slide_deadline 3, test_export_temp_files 6, test_export_log_hygiene 13,
  test_export_hermetic 7, test_ci_runs_the_export_engine_suites 4, test_export_route_statuses 6,
  test_google_slides_routes 4, the model ranges 52, test_huashu_font_bundle 4,
  test_verify_app_wheel_huashu 1. Each was red first, or is a guard.
  - **Sabotages.** 58 red, every file restored. One went green: aborting with `ERR_FAILED` left a
    captured frame's picture unchanged, because a capture never draws a frame's document; the test
    was removed, and the abort code's reason rests on the measurement above. The M8 skip runs on
    Linux alone.
- **Byte-identity.** Both corpora with `--pin-fonts --powerpoint --gslides` at `68459255`:
  `export.pptx` and `export-gslides.pptx` equal B8 r1's final runs part for part (core.xml aside),
  every PowerPoint and Google score equal, no text lost, 0 MODEL DROPS. The three matrix decks
  equal B8's `matrix/` runs, no text lost. Checked after each code commit as well.
- **Gate** (serial, as written, timeout file deselected): 1593 passed, 0 failed, 13 skipped (B8 r1:
  1435 / 0 / 13). **Full suite** (`-n auto`, without the timeout file): 18261 passed, 0 failed, 28
  skipped (B8 r1: 18099 / 0 / 28). **Frontend unit:** 3757 passed.
- **Not run as asked: the timeout file was run once by mistake** (a doc-reference sweep passed it
  to pytest): 124 passed in 3 minutes; the owner's and the MCP's Chrome stayed up, nothing was left.
  Its stubs and watch were updated for the new launch path and TMPDIR; the owner's run is still
  the check of record.
- **A local flake, not the code.** Three runs after this laptop's Chrome relaunched itself to apply
  its 158 update (02:29, `--restart`) each had one `measure.cjs` call time out at 120 s, its
  browser stuck before any page (no renderer) and left orphaned; none in the gates before or after.
  The orphans were ended. CI uses Linux's headless shell, not the Mac's Chrome.

Google Slides decks kept for this batch:
- In-repo corpus: https://docs.google.com/presentation/d/1H3EQG99EbalE-mvGX2Wucmp1B0BJHhasjPI5U6hDyP0/edit
  ("Tellr export revamp — fix A, in-repo corpus (pinned fonts, 68459255)")
- Design-system corpus: https://docs.google.com/presentation/d/1oD5WRJ_WxvMvefjaIOqbbdQZUC1iMqyX-lSZIkPfPGk/edit
  ("Tellr export revamp — fix A, design-system corpus (pinned fonts, 68459255)")

No other presentation was created; the earlier decks and the T15 decks are untouched.

## Final fix B: fidelity and the checks

The final whole-branch review's fidelity and check findings (I5 to I10, M3, M5, M6, M10, M11, the
triage's FIX lines) and Fix A's two residuals (WebRTC, page console text). Commits
`801b9fd9..1a4c0b52` and this ledger on `feat/export-revamp`, each pushed.

- **I5, a symbol takes the face its target draws at the UI's size** (`1122fd0b`). MS PGothic drew
  the Harvey quarters at about half the UI's size in both apps. Measured per glyph against the UI
  (Chrome on a Mac draws them from Menlo), at 1× and 2×, regular and bold (CALIBRATION D8, per
  target): the deck for PowerPoint writes 381 symbols in Segoe UI Symbol (the quarters among them),
  the deck for Google Slides 47 in JetBrains Mono (◔◕) and 142 in Noto Sans JP (◐◑, ★☆), as no face
  Google hosts draws all four; MS PGothic keeps the rest, MS Gothic a monospace run's. A face is
  written only for the symbols its app drew in it itself (coverage re-checked over the 982 per
  target), so none falls back or draws as a box. Slide 18: PowerPoint 2.93 → 2.93, Google 2.48 → 2.47, the quarters at about the UI's size in
  both (`fixB/crop-18-table.png`, `crop-18-legend.png`).
- **I6, a word read across words holds each whole** (`aab08052`). Both twins (`text_check.cjs`
  writtenIn, `run.py` _written_in): a word is inside one word of a text, or two or more of its words
  whole, one after the other; a word read across a join holds the tail's last word and the head's
  first. The same rule reads one item's own text, its white space and line ends ending words, so a
  short word lost inside one item between words that spell it is reported too. Red first through a
  real export: the B7 re-review's 16 px unpadded and `padding: 0 2px` chips, whose lost sides are
  neighbours. The docs say what is checked, and the 1,024-box bound is the first 1,024 boxes the rule
  can read: unturned one-line text boxes.
- **I7, the ellipsis and movedBody** (`130c39c8`). The "…" takes the move and body of the words
  the cut keeps; a moved line's movedBody bounds its words alone. New fixtures: the kept-move ellipsis
  lines (down and up) and the down-direction two-span line.
- **I8, measureProbes** (`826caa26`). Every declaration of a probe's style is `!important`
  (importantCss, which ends no declaration at a semicolon inside quotes); the fixed style also resets
  display, sizing, containment, writing mode and the transforms. A probe of text that paints with no
  positive width is unmeasured, its readers treat it as unread, and the pass says how many on an
  `[html2pptx] text metric probes` line.
- **I9, capitalize** (`801b9fd9`): the browser's word boundaries, each measured in Chrome.
- **I10, the corner pieces' neighbours** (`f4279654`): a short-row and an RTL rounded body make
  copying `slotCells` after the sort red; a span drift guard; the docstring; CALIBRATION D13's note.
- **The C1 residual, WebRTC** (`e9c195ef`). An init script takes `RTCPeerConnection` and
  `webkitRTCPeerConnection` away in every realm of the context (measured: the page, a fresh iframe,
  a srcdoc iframe, an `<object>`, a popup), and the browser launches with the
  `disable_non_proxied_udp` policy under both flag names (Chrome reads one, Chromium the other). A slide
  that tries every realm reaches neither a local STUN (UDP) nor TURN (TCP) listener; in a plain
  browser it reaches both. The policy alone measured to stop UDP but not TURN over TCP.
- **The S1 residual, page console text** (`614342b9`). Without `TELLR_EXPORT_DEBUG_TEXT=1` no page
  console text reaches the log, the engine's own page-side lines included (the page's realm builds
  them): one `[html2pptx] page console:` line a slide counts its messages by level and how many carry
  the engine's prefixes. With the flag, as before.
- **The `return DEFAULT_FACE`**: re-checked, not unreachable. `lackingFaceOf` never held one (the
  history from `a2ce66e6`); `snapshot_text.mjs` has two, `fallbackFaceOf`'s for a stack with no
  generic keyword (`"DM Sans"` alone) and `familyOf`'s for a stack with no family (a page's
  replaced style getters). Both stay.
- **M3, L146** (`7e1cc093`): no plan references in code or the export tests (a hygiene test scans
  them), no raw invisible characters; the font bundle rebuilt from the pinned release for
  `fonts.conf.in`. **M5, M6** (`c83c68fc`). **M10, L221** (`854ff521`). **M11** (`9058ac22`): the
  canvas wait was `page.waitForFunction`, whose predicate the slide CSP refused at once, so it waited
  for nothing: it now polls through `page.evaluate`, and says a canvas still without a buffer;
  `gradientMiddle` says a throw once a slide.
- **Triage**: L66, L93, L94, L97, L169, L173, L290 (`89bc1ce6`); L143, L144 (`1cbd44be`); L190,
  L195, L199, L200 (`64cd51fa`); L167 (`a137ebd2`): a word's Range rects are now read through the
  pristine realm, which a new DOMRectList hostile twin pins.

- **Harness** (both corpora, `--pin-fonts --powerpoint --gslides`, at `1a4c0b52`, against Fix A's
  final runs): in-repo corpus, only slide 18's part differs, in both decks, as I5 writes it; every
  other score equal, mean 1.95 → 1.95 (PowerPoint) and 2.44 → 2.44 (Google). Design-system corpus:
  both decks equal Fix A's part for part (core.xml aside), every score equal (1.62 / 1.52). No text
  lost in either deck of either corpus, 0 MODEL DROPS, nothing worse by more than 0.05. A second
  export of each corpus for each target is byte-identical to the run's. The I6 to I9 changes touch
  no corpus slide's output.
- **Tests.** The gate (`-k "(export or huashu or google) and not timeout"`, the timeout file
  ignored, `-n 6`): 1812 passed, 0 failed, 13 skipped (Fix A: 1593 / 0 / 13; 177 of the new ones
  are the source-hygiene test's case per source file). Full suite (`-n auto`, the timeout file
  ignored): 18484 passed, 0 failed, 28 skipped (Fix A: 18261 / 0 / 28). Every behavioural test was
  red first; 68 sabotages red, every file restored (`fixB/*sabotage-results.json`). Two went green
  first and were mended: a sabotage of the capitalize context that changed nothing (replaced by one
  that does), and the semicolon-in-a-family case, whose first fixture named an unloaded face
  (now a loaded one).
- **Not run, as asked:** `tests/unit/test_pptx_from_html_huashu_timeout.py`.
- **A local flake.** One orphaned Playwright Chromium (`playwright_chromiumdev_profile-*`, no
  page) was left after the gate, as in Fix A's runs; it was ended.

Google Slides decks kept for this batch (intermediate probe decks deleted by id):
- In-repo corpus: https://docs.google.com/presentation/d/1Xo1wLmW44v_p92F4rl5unmJNjH-OYFWv0CutnIW7pIA/edit
  ("Tellr export revamp — fix B, in-repo corpus (pinned fonts, 1a4c0b52)")
- Design-system corpus: https://docs.google.com/presentation/d/1nP3nPwLERMa8k-5ZW3VzqnI9t4qFiGyXPPgIziFRxFc/edit
  ("Tellr export revamp — fix B, design-system corpus (pinned fonts, 1a4c0b52)")

printf "\n"

cat /Users/tariq.yaaqba/.claude/jobs/937bacb3/tmp/fixC/ledger-draft.md

## Final fix C: the residuals of the final fix round

The combined re-review of Fix A and Fix B left two Important residuals (N1, N2) and three
Minor ones (N3, N4, N5), and M11's gradient line. Commits `59f82310..2deb3323` and this ledger
on `feat/export-revamp`, each pushed.

- **N1, the deadline bounds every step of a slide** (`bc878ca7`). Only the launch and the
  page's reads were raced against `SLIDE_DEADLINE_MS`; `newContext`, the request guard's
  routing, `newPage` and the `finally`'s close were waited for unbounded, and `stop()` only
  rejected a promise nobody awaited. Now every step is raced against the slide's stop, a
  launch carries the deadline as its Playwright timeout, and the slide's browser is closed
  within `BROWSER_CLOSE_TIMEOUT_MS` (5 s) or its process group killed (through the
  in-process server's handle, `browser._connection.toImpl(browser).options.browserProcess`,
  Playwright 1.59.1: the public API gives a launched browser no process; measured, a kill
  takes 0.02 s), which one `[html2pptx]` line says. A slide stopped before its page opened
  fails with "its browser stopped answering". A slide read whole whose browser will not close
  is kept: its reads are done. Red first through the real engine: a preload hangs one step of
  the middle slide of three (newContext, the guard's `context.route`, newPage, close) and
  records every earlier browser's process group at each launch and at node's exit (before
  Playwright's own exit handler). Red: each deck lost at the 90 s test timeout. Green: one
  failure, two slides, about 35 s, for each setup step; the close case, all three slides in
  about 10 s, the browser killed; no browser running at any launch or at exit. Six sabotages
  red. Without the kill, a never-closing browser's pipes keep node alive to the timeout, so
  the kill is what keeps the deck.
- **N2, the engine's diagnostics on a channel the page cannot write to** (`c427dbb7`).
  - Each pass says what it diagnoses with `diagnose(key, ...)` (`dom_access.mjs`): a key of
    the engine's own wordings, numbers it counted, the page's text as its length and first
    300 characters. 17 call sites in 7 modules, and the six "loss" texts the probes pass.
  - The entries are one string built in the pass's closure with string concatenation,
    `typeof`, comparison and a string's own length and characters, so it depends on no
    built-in the page can replace and needs no pristine realm (which a hostile page can
    deny, the very case the collection lines report). The brief named pristine-realm
    primitives; measured, they would not have been enough: Playwright's own page-side
    serializer calls the page's `Array.prototype.push` for every value an evaluate returns,
    and a page owning it dropped and forged entries of an array however it was built.
  - So Node reads each pass's result as a handle, its properties through the DevTools
    protocol (`render_slide.cjs` evaluatePass, `JSHandle.getProperties`), which runs no page
    script; a value that is an object is still serialized as `page.evaluate` does, so the
    model and the decks are unchanged.
  - `model_check.cjs` checkDiagnostics takes nothing but the engine's wordings
    (`DIAGNOSTIC_LINES`, `DIAGNOSTIC_PARTS`, slots `{n}` `{p}` `{w}` `{l}`): an entry that is
    none is dropped, on an `[html2pptx] model:` line, and counted in `modelDrops`.
    `log_line.cjs` diagnosticLine writes each with its pass's prefix, wordings always, page
    text by its length without the flag (`body children [<5 characters>]`, the line ending
    "(page text not logged: …)"), whole with it.
  - A pass keeps 100, a slide logs 100 lines, the rest counted on one
    `[html2pptx] diagnostics:` line.
  - Found on the way, fixed: the summary logged the background transfer's result and the
    animations' counts as the page's serializer handed them; a page owning
    `Array.prototype.push` wrote its own words into the summary without the flag (probed).
    Both are checked now and a bad one dropped and counted.
  - Residual, measured: a page that replaces `window.eval`, which Playwright's utility script
    calls with every evaluate's source, decides what any pass returns. Its diagnostics then
    still say nothing but the engine's wordings, page text in page slots by its length (a
    test pins it), but it can drop them, as it can replace the model.
  - Tests: every required string without the flag (`[preprocess] no slide root:`,
    `wrapper candidates (none)`, `several element children`, `resolved NO root`,
    `[preprocess] collection`, the last through a new wrapper-flood fixture); a page that
    replaces its console and owns `Array.prototype.push` (drops and forges in the engine's
    encoding); an error message holding the page's word; the `window.eval` takeover; the
    rewritten pass results; the bounds; the checker. The seven call sites that read fixed
    wordings through the flag (boxes, hostile realm, lists, tables ×2, slide root depth ×2,
    failures announced) read them without it; the other thirteen read the page's own text
    (hidden text, lost words, console forwarding) and keep it. 18 sabotages red; one went
    green first (it left the half-read entry to be rejected anyway) and was strengthened.
- **N3** (in `c427dbb7`): `dom_access.mjs`, `preprocess.mjs` and the wrapper's docstring said
  page console lines reach stderr; corrected, with the log hygiene module's docstring and the
  support helper's.
- **N4, CI deselects the live-CDN test** (`59f82310`): `-m "not network"`, the marker
  registered, the job's comment giving the hand-run command; a guard pins all three.
- **N5, a failed slide counts its page console too** (`6fcb6ed0`): the count line is written
  in the slide's `finally`, read or failed; once a slide is stopped its page's messages are
  neither forwarded nor counted. Of the first four sabotages two went green: once the
  slide's log stopped, the forwarding already returned early, so writing through the log as
  well was a second, redundant layer; it was removed, and both remaining sabotages are red.
- **M11's gradient line** reaches the log without the flag as a fixed wording (N2); its test
  reads it so.

- **Harness** (both corpora, `--pin-fonts --powerpoint --gslides`, at `2deb3323`, against Fix
  B's final runs): both decks of both corpora equal Fix B's part for part (core.xml aside).
  Every score is equal: in-repo corpus 1.95 → 1.95 (PowerPoint) and 2.44 → 2.44 (Google),
  design-system corpus 1.62 → 1.62 and 1.52 → 1.52; nothing worse by more than 0.05. No text
  lost in either deck of either corpus, no failures, 0 MODEL DROPS. No engine diagnostic is
  logged for any corpus slide.

- **Tests.** The gate (`-k "(export or huashu or google) and not timeout"`, the timeout file
  ignored, run serially): 1834 passed, 0 failed, 13 skipped, in 38 min (Fix B: 1812 / 0 / 13,
  at `-n 6`). Full suite (`-n 4`, the timeout file ignored): 18506 passed, 0 failed, 28
  skipped (Fix B: 18484 / 0 / 28). Every behavioural test was red first; 29 sabotages red
  (N1 6, N2 18, N4 3, N5 2), every file restored (`fixC/*sabotage-results.json`). A handle
  read costs about 0.6 ms more per pass than `page.evaluate` (measured, 1.14 against 0.51 ms).

- **Not run, as asked:** `tests/unit/test_pptx_from_html_huashu_timeout.py`. N1 changed the
  launch (a `timeout` option) and the close; its stubs were read against both and need no
  change: `BLOCKING_LAUNCH_PRELOAD` passes the options through and wraps the same
  `newContext`/`newPage`/`goto`, and `HUNG_SLIDE` still reaches its 10 s sidecar timeout
  before the 30 s deadline. One test seam elsewhere did need it: the log hygiene suite's
  throwing-page preload stubs `page.evaluateHandle` beside `page.evaluate`.

Google Slides decks kept for this batch (no other deck was made):
- In-repo corpus: https://docs.google.com/presentation/d/1_eoGwKs9FJxJvGJVUoNyHVF26e0lOzNsx2RCknRSmLc/edit
  ("Tellr export revamp — fix C, in-repo corpus (pinned fonts, 2deb3323)")
- Design-system corpus: https://docs.google.com/presentation/d/1bwgWxX_SkOlAzYnahymJpoYUUYhasZMuZq20YJ7D-kE/edit
  ("Tellr export revamp — fix C, design-system corpus (pinned fonts, 2deb3323)")
