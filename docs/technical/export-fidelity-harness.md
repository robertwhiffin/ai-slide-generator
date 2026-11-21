# Export Fidelity Harness

**One-Line Summary:** `scripts/export_fidelity/run.py` exports a fixture deck through the production snapshot engine, renders the result in PowerPoint and Google Slides, and compares every slide with the browser's own rendering of it, so a change to the export can be measured against what the user sees.

---

## 1. What it measures

The PowerPoint and Google Slides exports ([Export Features](export-features.md)) are judged by one question: does the exported slide look like the slide in the UI, in the app the user opens it in? The harness answers it per slide, for a fixture deck:

1. it builds every slide's export document with the production `build_slide_html`, so it exercises exactly what the export routes hand the sidecar;
2. it renders the **truth**: a 1280×720 Chromium screenshot of each document (`render_truth.cjs`), and the page's rendered text (`truth/<slide>.txt`);
3. it runs the production export, `build_pptx_huashu`, to `export.pptx` (written for PowerPoint, `target="pptx"`), recording each slide's `[html2pptx] slide summary` line in `summaries.json`, and reports **text loss**: the words the browser renders that the `.pptx` lacks, leaving out each slide's hidden text (the words the page reads that the slide does not show, from the summary's `hiddenText`);
4. it renders the deck in the apps asked for: PowerPoint (`--powerpoint`), Google Slides (`--gslides`: a second export written for Google Slides, `export-gslides.pptx`, converted through Drive as the Google Slides export does, whose text loss is checked too), and LibreOffice (`--lo`);
5. it writes a side-by-side comparison per slide, a score per slide and app, and `summary.md`: one table row per slide with its scores (against a baseline run's, with `--baseline`), each deck's text loss, MODEL DROPS and captures.

The default corpus is `tests/fixtures/export_fidelity/`: `deck.css` and `deck.json` (the deck's CSS, scripts and title) and 17 slides in `slides/`, each built around the constructs that once exported badly (gradients and SVG art, agenda grids, SVG and Chart.js charts, Harvey-ball and balance-sheet tables, pills, timelines, pseudo-element bullets, waterfalls, progress bars, code and gradient text, rotated labels, overlapping images, dense zebra tables, and hidden graphics).

## 2. Running it

From the repo root, with the sidecar's `node_modules` extracted (`services/pptx-emit-huashu/setup.sh`) and a Playwright Chromium installed:

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
| `--baseline DIR` | Sets each slide's scores in `summary.md` against those of an earlier run, `DIR` being that run's `--out`: `2.36 → 2.13`, a mean row over the slides both runs scored, and every slide more than 0.05 worse in either app. Use a baseline run of this harness with `--pin-fonts`, the same fixture and the same apps. |

## 3. Which renderers to trust

PowerPoint for Mac and Google Slides are the truth: they are the applications users open the exports in, and the engine is calibrated against both. LibreOffice substitutes fonts it lacks and lays text out by its own metrics, so a LibreOffice difference says nothing on its own; use it only to see that a deck opens and every slide has its items. macOS Quick Look is not a renderer to judge by either.

**How an app's PDF is rasterised.** PowerPoint's PDF embeds each picture at twice its slide size, with an alpha mask and `/Interpolate true`. Drawn by MuPDF at the slide's own 1280 px, such a picture's light rules come out dark (corpus slide 03's two rows of EBEBEB gridline at B2B2B1 and B4B4B2; at 4×, E9EAE9 and D0D1D0), and a mark in the ground's own colour shows a fringe, where the UI, and Apple's Quartz drawing the same PDF, show neither (Task 14 Phase A, H1). So `rasterise_pdf` draws every page at 4 times the slide's size (5120×2880) and box-filters it down to 1280×720, each pixel the mean of the 16 it covers, which comes out closer to Quartz's raster (measured in `CALIBRATION.md`, H1); LibreOffice's PDF is drawn the same way. The method is recorded as `pdfRaster` in each run's `harness.json`. A run from before this method, or with another, scores PowerPoint differently, so `summary.md` says when its baseline's `pdfRaster` differs; to compare with such a run, rasterise its kept `powerpoint/export.pdf` again with `rasterise_pdf` and score it with `compare`. Google Slides is scored from its LARGE thumbnail (1600 px wide), resized to 1280×720, which this does not change.

## 4. Reading the output

Everything lands in `--out`:

| Path | What it is |
|---|---|
| `documents/<slide>.html` | The export document of each slide, as the routes build it. |
| `truth/<slide>.png`, `truth/<slide>.txt` | The browser's rendering and rendered text: the reference. |
| `export.pptx`, `export-gslides.pptx` | The decks written for PowerPoint and for Google Slides. |
| `summaries.json`, `summaries-gslides.json` | Each slide's summary line, in slide order (`null` for a slide the export failed): item counts by kind, pictures and captures, `hiddenText`, `target`, `modelDrops`. |
| `failures.json`, `failures-gslides.json` | The slides the export rejected, as the routes report them. |
| `text_loss.json`, `text_loss-gslides.json` | Per slide, the words the browser renders that are in no item of that deck and are not hidden text. The run also prints them ("Text missing from the export: none" when there are none). |
| `harness.json` | The run's fixture, its slide count and how its PDFs were rasterised (`pdfRaster`), which `summary.md` checks a baseline against. |
| `powerpoint/`, `gslides/`, `libreoffice/` | Each app's rendering of each slide. |
| `compare/<slide>.png` | One sheet per slide: the truth, then each app's rendering, side by side and labelled. |
| `scores.json` | Per slide and app, the mean per-pixel difference from the truth (0 is identical; lower is closer). |
| `summary.md` | One row per slide: each app's score (`baseline → now` with `--baseline`), each deck's text loss (`pptx / gslides`), MODEL DROPS and captures taken / failed, or "export failed" for a slide a deck lacks; a mean row; and, with a baseline, every slide more than 0.05 worse. Paste it into a ledger as it is. |

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
