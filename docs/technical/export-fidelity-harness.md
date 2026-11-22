# Export Fidelity Harness

**One-Line Summary:** `scripts/export_fidelity/run.py` exports a fixture deck through the production snapshot engine, renders the result in PowerPoint and Google Slides, and compares every slide with the browser's own rendering of it, so a change to the export can be measured against what the user sees.

---

## 1. What it measures

The PowerPoint and Google Slides exports ([Export Features](export-features.md)) are judged by one question: does the exported slide look like the slide in the UI, in the app the user opens it in? The harness answers it per slide, for a fixture deck:

1. it builds every slide's export document with the production `build_slide_html`, so it exercises exactly what the export routes hand the sidecar;
2. it renders the **truth**: a 1280×720 Chromium screenshot of the slide as the UI shows it (`render_truth.cjs`), and the page's rendered text (`truth/<slide>.txt`). Each slide's truth document is built by the UI's own code, not a copy of it ([The truth document](#the-truth-document));
3. it runs the production export, `build_pptx_huashu`, to `export.pptx` (written for PowerPoint, `target="pptx"`), recording each slide's `[html2pptx] slide summary` line in `summaries.json`, and reports **text loss**: the words the browser renders that the `.pptx` lacks, leaving out each slide's hidden text (the words the page reads that the slide does not show, from the summary's `hiddenText`). A word (white space and default-ignorable code points removed, NFKC-folded, lower-cased) is found when one text box or table cell holds it, read alone, or when it lies across the joins of a chain of neighbouring text boxes, each box's text run on into the next's. An atomic inline (an inline-block numeral, a chip) is a text box of its own, written after the text around it, so a word the page runs across its edge ("1Financials", "Iceberg,") is written in two boxes, and those are neighbours: two unturned boxes of one line (`wrap="none"`) that run the same way, share a line (overlap by more than half the shorter's height) and whose texts meet within an atomic inline's edge, the head's text starting from 0.25 em before the tail's ends to 1.5 em after it, in the larger of the two boxes' sizes (their runs that are no superscript or subscript). A text's ends are its box's less the slack the snapshot gives the box on the side its alignment grows (6% + 4 px). Each box runs on into its nearest such neighbour; at most the first 1,024 boxes are read. Boxes merely written one after the other are not run together, so a lost chip, whose letters end and start the boxes either side of where it was ("Customer Dat**a** · **I**nsights"), is still lost (Task 15 H2, fix round 1). The sidecar's own check (`text_check.cjs`) reads the slide model's items the same way, with the same constants;
4. it renders the deck in the apps asked for: PowerPoint (`--powerpoint`), Google Slides (`--gslides`: a second export written for Google Slides, `export-gslides.pptx`, converted through Drive as the Google Slides export does, whose text loss is checked too), and LibreOffice (`--lo`);
5. it writes a side-by-side comparison per slide, a score per slide and app, and `summary.md`: one table row per slide with its scores (against a baseline run's, with `--baseline`), each deck's text loss, MODEL DROPS and captures.

The default corpus is `tests/fixtures/export_fidelity/`: `deck.css` and `deck.json` (the deck's CSS, scripts and title) and 17 slides in `slides/`, each built around the constructs that once exported badly (gradients and SVG art, agenda grids, SVG and Chart.js charts, Harvey-ball and balance-sheet tables, pills, timelines, pseudo-element bullets, waterfalls, progress bars, code and gradient text, rotated labels, overlapping images, dense zebra tables, and hidden graphics).

### The truth document

The truth is the slide the user sees, which is not always the export document laid out: the UI's document frames the slide with the slide-host frame contract (`slideHostFrameStyle`), which the export's shell deliberately omits (`build_slide_html`), so a design-system template whose `<section>` wrapper has no height of its own shows its ground in the UI and the page's dark `html, body` ground in the export document. A truth rendered from the export document judged such slides against that dark ground (Task 15, H1).

So `scripts/export_fidelity/ui_document.mjs` builds each slide's truth document with the frontend's own `frontend/src/services/slideDocument.ts`, bundled unchanged with the frontend's esbuild and imported from memory, with the options the slide viewer's stage passes (`SlideStage.tsx`): `buildSlideDocument(slide.html, {css, externalScripts, scripts, extraHeadStyle: SLIDE_PREVIEW_RESET_STYLE})`. A change to `slideDocument.ts` reaches the truth at once. The fixture format holds the deck's scripts only (`deck.json` `scripts`), which the export runs on every slide; the UI runs each slide's own, so each slide's UI document runs the deck's, each of a deck's scripts guarding on its own element as the app's do. The documents are written to `ui-documents/`; `documents/` keeps the export's.

**What it needs installed:** the frontend's dependencies, `npm ci` in `frontend/` (the harness uses `frontend/node_modules/esbuild`, which Vite brings). Without them, or with an install esbuild cannot build with (its platform binary missing: `npm ci --omit=optional`, or a `node_modules` copied from another platform), the run stops before it writes anything, with exit code 2 and one `[export-fidelity]` line on stderr saying that the UI truth bundles `slideDocument.ts` with the frontend's esbuild, which is not installed or cannot build it, to run `npm ci` in `frontend/`, and esbuild's own first line. Any other failure to build the UI's documents stops it the same way, on one line naming its cause; `ui_document.mjs` writes no document unless it has built them all.

**Against the earlier truth** (the export document, at engine `7d77df77` with `--pin-fonts`), the UI's truth is the same, pixel for pixel, on 42 of the 44 corpus slides. On the other two it is the UI's own drawing:
- `11-chartjs-canvas` (10,949 px): the UI runs the slide's script inline at the end of `<body>`, so Chart.js draws the legend at once, before DM Sans has loaded, in the canvas's fallback face (Times), and lays the doughnut out around that legend; the export document runs its scripts after its chart wait, with DM Sans loaded. The UI's drawing is the same over four renders.
- `slide-content` (5 px, one level of 255, on a faint diagonal SVG line): the export's shell paints `html` white (`background: #ffffff`), which the UI's leaves to the canvas. That one rule added to the UI document reproduces the export document's pixels exactly.

`harness.json` records what the truth renders (`truth`), and against a baseline `summary.md` says when the baseline's truth was rendered another way (a run from before the record rendered the export document) and names every slide whose truth image differs from the baseline's, pixel for pixel: those slides' scores move with the truth as well as the export.

## 2. Running it

From the repo root, with the sidecar's `node_modules` extracted (`services/pptx-emit-huashu/setup.sh`), a Playwright Chromium installed, and the frontend's dependencies installed (`npm ci` in `frontend/`, for the truth's esbuild):

```bash
uv run --with pymupdf --with pillow python scripts/export_fidelity/run.py \
    tests/fixtures/export_fidelity --out /tmp/fidelity --powerpoint --gslides
```

| Option | What it adds |
|---|---|
| `--powerpoint` | Opens `export.pptx` in Microsoft PowerPoint for Mac, saves it as PDF and rasterises each page (`powerpoint/`) as [§3](#3-which-renderers-to-trust) describes. PowerPoint briefly shows a window. The deck's fonts must be installed locally (DM Sans and DM Mono for the corpus). |
| `--gslides` | Exports the deck for Google Slides, uploads it to Drive as a Slides presentation and downloads each slide's thumbnail (`gslides/`). Uses gcloud application-default credentials and the quota project in `GOOGLE_QUOTA_PROJECT`. The presentation is left in Drive, named `tellr-export-fidelity <timestamp>`, so it can be opened and inspected; its URL is printed and written to `gslides_url.txt`. Delete it by hand when finished. |
| `--lo` | Renders `export.pptx` with LibreOffice (`libreoffice/`). A smoke check only; see below. |
| `--only 04 05` | Runs only the slides whose names start with these prefixes. |
| `--pin-fonts` | Loads the deck's webfonts from committed files instead of Google Fonts: each `@import` of `fonts.googleapis.com` in `deck.css` becomes the latin faces Google serves for that import, embedded as `data:` (`PINNED_FONT_IMPORTS` in `run.py`, files under `tests/fixtures/export_snapshot/fonts`). Google now and then answers one import with another font file, which moves text widths and PowerPoint scores by about 0.08 between runs, so use it whenever two runs are compared (before and after a change). An import with no pinned faces, or a slide that loads Google Fonts itself, stops the run with an error naming it. Without the option the deck loads its live fonts, as the app does. |
| `--baseline DIR` | Sets each slide's scores in `summary.md` against those of an earlier run, `DIR` being that run's `--out`: `2.36 → 2.13`, a mean row over the slides both runs scored, and every slide more than 0.05 worse in either app. A baseline whose PDFs were rasterised another way is not compared in PowerPoint or LibreOffice ("not compared: raster differs"), only in Google Slides. Use a baseline run of this harness with `--pin-fonts`, the same fixture and the same apps. |

## 3. Which renderers to trust

PowerPoint for Mac and Google Slides are the truth: they are the applications users open the exports in, and the engine is calibrated against both. LibreOffice substitutes fonts it lacks and lays text out by its own metrics, so a LibreOffice difference says nothing on its own; use it only to see that a deck opens and every slide has its items. macOS Quick Look is not a renderer to judge by either.

**How an app's PDF is rasterised.** PowerPoint's PDF embeds each picture at twice its slide size, with an alpha mask and `/Interpolate true`. Drawn by MuPDF at the slide's own 1280 px, such a picture's light rules come out dark (corpus slide 03's two rows of EBEBEB gridline at B2B2B1 and B4B4B2; at 4×, E9EAE9 and D0D1D0), and a mark in the ground's own colour shows a fringe, where the UI, and Apple's Quartz drawing the same PDF, show neither (Task 14 Phase A, H1). So `rasterise_pdf` draws every page at 4 times the slide's size (5120×2880) and box-filters it down to 1280×720, each pixel the mean of the 16 it covers, which comes out closer to Quartz's raster (measured in `CALIBRATION.md`, H1); LibreOffice's PDF is drawn the same way. The method is recorded as `pdfRaster` in each run's `harness.json`. A run from before this method, or with another, scores PowerPoint differently, so `summary.md` compares no PowerPoint or LibreOffice score with a baseline whose `pdfRaster` differs, and says so; to compare with such a run, rasterise its kept `powerpoint/export.pdf` again with `rasterise_pdf` and score it with `compare`. Google Slides is scored from its LARGE thumbnail (1600 px wide), resized to 1280×720, which this does not change.

## 4. Reading the output

Everything lands in `--out`:

| Path | What it is |
|---|---|
| `documents/<slide>.html` | The export document of each slide, as the routes build it. |
| `ui-documents/<slide>.html` | The UI's document of each slide, as the slide viewer builds it ([The truth document](#the-truth-document)). |
| `truth/<slide>.png`, `truth/<slide>.txt` | The browser's rendering of the UI's document, and its rendered text: the reference. |
| `export.pptx`, `export-gslides.pptx` | The decks written for PowerPoint and for Google Slides. |
| `summaries.json`, `summaries-gslides.json` | Each slide's summary line, in slide order (`null` for a slide the export failed): item counts by kind, pictures and captures, `hiddenText`, `target`, `modelDrops`. |
| `failures.json`, `failures-gslides.json` | The slides the export rejected, as the routes report them. |
| `text_loss.json`, `text_loss-gslides.json` | Per slide, the words the browser renders that are in no item of that deck and are not hidden text. The run also prints them ("Text missing from the export: none" when there are none). |
| `harness.json` | The run's fixture, its slide count, how its PDFs were rasterised (`pdfRaster`) and what its truth renders (`truth`), which `summary.md` checks a baseline against. |
| `powerpoint/`, `gslides/`, `libreoffice/` | Each app's rendering of each slide. |
| `compare/<slide>.png` | One sheet per slide: the truth, then each app's rendering, side by side and labelled. |
| `scores.json` | Per slide and app, the mean per-pixel difference from the truth (0 is identical; lower is closer). |
| `summary.md` | One row per slide: each app's score (`baseline → now` with `--baseline`), each deck's text loss (`pptx / gslides`), MODEL DROPS and captures taken / failed, or "export failed" for a slide a deck lacks; a mean row; and, with a baseline, every slide more than 0.05 worse, and whether the truth is the baseline's (its document, and the slides whose truth image changed). Paste it into a ledger as it is. |

Read the scores as a guide to where to look, not as a grade: anti-aliasing, a sub-pixel text width or a picture's resampling all add a little, so compare a score with the same slide's score before a change, not with another slide's. The comparison sheets say what a score cannot: whether a line wrapped, a box moved or a colour changed.

A line on stderr starting `MODEL DROPS:` names a slide whose model Node dropped part of (its summary's `modelDrops`): the slide exported without that part, and the cause is in that slide's log. A healthy run has none.

## 5. The calibration record

`scripts/export_fidelity/CALIBRATION.md` records how the engine's text constants were fitted against PowerPoint and Google Slides renders of a probe deck (`tests/fixtures/export_snapshot/text_calibration.html`): the first-line offset (`FIRST_LINE_A`, `FIRST_LINE_B`, `FIRST_LINE_C`), the size the renderers draw a superscript or subscript run at (`SUPERSCRIPT_SIZE_FACTOR`), and how far Google Slides lowers a line that holds a larger run (`GOOGLE_LINE_GROWTH_PER_PX`), with the residuals each leaves. The tests read the constants from that file and fail when the code and the record disagree (`tests/unit/test_export_snapshot_line_spacing.py`). To re-measure:

```bash
uv run --with pymupdf --with pillow python scripts/export_fidelity/calibrate_text.py --out /tmp/calib
uv run --with pymupdf python scripts/export_fidelity/measure_script_lines.py \
    --out /tmp/script-lines --powerpoint --gslides
```

## 6. Cross-References

- [Export Features](export-features.md) — the snapshot engine and the export routes
- [Google Slides Integration](google-slides-integration.md) — the Drive conversion
