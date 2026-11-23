# Export Features - PDF, PPTX, and Google Slides

## Overview

The AI Slide Generator supports exporting slide decks in three formats, plus the deck spec as Markdown:
- **PDF**: Client-side generation using browser APIs
- **PPTX**: Server-side render of the deck HTML by the snapshot engine (the `services/pptx-emit-huashu/` sidecar) — `POST /api/export/pptx/editable/huashu/from-html`, with `/pptx/editable/from-records` as the fallback
- **Google Slides**: Synchronous server-side export — the same engine writes a deck for Google Slides, which is uploaded to Drive, which converts it to native editable Slides
- **Deck spec (Markdown)**: client-side, from the Spec view — see *Deck spec as Markdown*.

All export options are accessible through a unified dropdown menu in the slide panel (PDF, PPTX, Google Slides); the deck spec exports via a separate button in the Spec view header.

### The export routes, and which are live

| Route | Status | Notes |
|---|---|---|
| `POST /api/export/pptx/editable/huashu/from-html` | **Live — primary** | What the Export → PowerPoint button calls. Deterministic render of the deck HTML by the snapshot engine (below) |
| `POST /api/export/pptx/editable/from-records` | **Live — fallback** | DOM-walker records → pptxgenjs. Fires on a `503` **or** when the error text indicates the pipeline is unavailable or installing — not status-code-only |
| `POST /api/export/google-slides/from-huashu` | **Live — primary** | Synchronous; renders the deck for Google Slides (`target="gslides"`) and uploads it to Drive for conversion. Returns `presentation_id`, `presentation_url`, `total_slides`, `succeeded`, `failures` |
| `POST /api/export/google-slides/from-records` | **Live — fallback** | The Google equivalent of the records fallback |
| `POST /api/export/pptx/editable/from-images` | Live, unreachable | Rasterised path, reached only when `fontMode === 'screenshot'`, which no UI surface passes |
| `POST /api/export/pptx` · `/pptx/async` | **Legacy** | LLM code-generation; superseded, and **no caller exists in this repository's frontend** |
| `POST /api/export/google-slides` | **Legacy** | LLM code-generation twin; superseded, no caller in this repository's frontend |

PDF export is client-side and is not a route.

**Table fidelity differs by route.** The snapshot engine writes a `<table>` the browser laid out as a plain grid as **one native, editable table** (`<a:tbl>`): the browser's own column widths and row heights, spans, fills, collapsed borders (resolved as CSS collapses them and written on both cells of each edge, which Drive keeps; a dotted one dotted) and cell margins. In the deck for PowerPoint the grid lies where Chrome paints it, on whole pixels, so filled cells meet with no seam. A table inside a rounded `overflow: hidden` wrapper has its corner cells unfilled and their fills drawn as shapes cut to the wrapper's arcs, under the table; in the deck for Google Slides, which draws a native cell on whole pixels and a shape anti-aliased, each of those shapes runs 1 px under the opaque cells beside it, so no light seam shows where they meet. A table no `<a:tbl>` can draw becomes editable positioned items instead (see *What the export trades away* below). The records fallback's DOM walker produces no records for `<td>`/`<th>`, so on that path cells are flattened into absolutely-positioned elements: faithful in position, not editable *as a table*. The legacy code-generation path prompts an LLM to write `python-pptx` with `add_table`, so it *can* produce a native table, though not reliably per run.

**A deck's leading webfont `@import` must stay first in its stylesheet.** `@import` is only valid at the top of a stylesheet, so anything prepended to the deck's CSS discards it and the export silently falls back to a system font. The Python `build_slide_html` builder achieves this by emitting the deck's CSS in its **own** `<style>` element. `buildStandaloneDeckDocument` instead concatenates deck and wrapper CSS into a single `<style>`, and remains correct only because the deck's CSS is placed first within it.

**No universal `* { box-sizing }` rule is applied** by either export builder, so slide content keeps the browser default. The resets that do exist are narrower than "scoped to `html, body`" — the Python builder's shell reset omits `box-sizing` entirely, and the preview host applies `box-sizing: border-box` to the host's direct child rather than to the document shell. See [Slide Host Frame Contract](slide-host-frame-contract.md).

**The export document gives inherited text what the UI's document gives it.** Neither shell sets a font, or any other inherited property, so a slide's text that takes its font from `<body>` is drawn in the browser's default face in both (Times on the Mac) and breaks its lines in the same places. The Python builder's shell used to set `font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif`, so such text was drawn in SF or the container's fallback in the export and broke differently: a real deck's "So what" paragraph was 4 lines in the UI and 5 in the export (Task 15, N2). `tests/unit/test_export_document_ui_parity.py` reads both shells and fails when either declares an inherited property the other does not. The deck names such text Times New Roman, the face metric-compatible with the one the browser draws it in (Times on the Mac, Liberation Serif on Databricks Apps): *Fonts and the face written*, below.

**Known export limitations.** The PowerPoint and Google Slides exports trade a few things away on purpose (*What the export trades away*, below). The PDF and screenshot paths do not carry the deck's webfont, so they render in a fallback face.

## The snapshot engine (PowerPoint and Google Slides)

Both live server-side routes run `build_pptx_huashu` (`src/services/pptx_from_html_huashu.py`), which runs the Node sidecar `services/pptx-emit-huashu/emit_deck.mjs` over the deck's slide documents (`build_slide_html`). For each slide, `render_slide.cjs` loads the complete document in headless Chromium (Playwright, 1280×720, device scale 2) and takes it through five stages:

1. **Load and settle.** Network idle; every font face the text asks for loaded (`pageFontsSettled`); every `<canvas>` given a drawing buffer (`waitForCanvases`, for Chart.js); then every CSS animation and transition finished, so a deck that fades content in exports its settled, opaque state; then the fonts again, for text an animation's end state set.
2. **The slide root's ground.** `preprocess.mjs` moves the slide root's background onto `<body>`, which becomes the slide background. A ground holding a `data:` image (a photo or pattern, under a scrim gradient or not) stays on the root instead, and is captured whole, as the browser fits it, as the slide's background picture. Nothing that moves layout runs: the page is read as the browser laid it out.
3. **Snapshot.** Each `::before`, `::after` and list `::marker` is read through the Chrome DevTools Protocol (`pseudo.mjs`): Chrome's own text, box and counters, read-only, with nothing inserted into the page. Then one read-only `page.evaluate` (`snapshot.mjs`, with `snapshot_borders.mjs`, `snapshot_text*.mjs` and `snapshot_table.mjs`) turns the page into a slide model: shapes, lines, text blocks with the browser's line breaks and runs, native tables, and picture targets, in CSS paint order. The slide's own script built the realm the model was made in, so Node validates the model before any use (`model_check.cjs`): an item it could not have written (a forged capture id, non-finite geometry, an unknown kind, an empty table grid) is dropped and counted (`modelDrops` in the slide summary), and the rest exports.
4. **Capture.** What PowerPoint and Slides cannot draw natively (gradients, background images, filters, inline SVG, canvas, images that are not raster `data:`) is an element-isolated 2× screenshot of the original page (`capture.cjs`); the element's text, children and pseudo-elements stay native.
5. **Emit.** `emit_model.cjs` writes the model to a pptxgenjs slide (`emit_text.cjs`, `emit_table.cjs`, `emit_typography.cjs`, `units.cjs`): typefaces named by weight (and, for PowerPoint, an italic by its italic static) for the webfonts the page loaded, any other text named by the face the browser drew it in, by a name every app draws with that face's metrics (*Fonts and the face written*, below), each character the written face lacks in the apps a run of its own in a face every app has (Arial, Times New Roman or Courier New, by the run's generic family; MS PGothic, or MS Gothic for monospace, for a symbol outside WGL4), line spacing written against the renderers' single spacing of 1.2 × the font size (a percentage up to it, space before each line above it), colours pre-blended against their backdrop, pictures from `data:` only (SDR-4437), and each box with its own corners: one circle on all four is a rounded rectangle; a top pair and a bottom pair of circles the preset `round2SameRect`, two diagonal pairs `round2DiagRect`, a top-right corner alone `round1Rect` (each corner at most half the short side); and any other mix (a left-only, an elliptical or an all-different corner) a custom path of one quarter arc per rounded corner. A border the same on all four sides is the box's outline. One that differs between sides is a line along each painted side, except on a box whose corners round: there each solid side is the region CSS paints for it, a filled custom shape between the rounded border box and the rounded padding box, which follows the corners and tapers to nothing where a neighbouring side has no width, divided from a differently painted neighbour by the line from the border box's corner through the padding box's, as Chrome divides it; neighbouring sides painted alike are one shape (a dashed or dotted side stays a line).

Then each slide's checks print, on stderr, a `[html2pptx] text missing:` line when a word of the page's rendered text is in no exported item (a word is found in one item's text, or across neighbouring text items: a word the page runs across an atomic inline's edge, such as an inline-block numeral and the word after it, is written in two items side by side on one line, its pieces meeting within the atomic inline's edge, which a lost chip's two sides do not), and always one `[html2pptx] slide summary {json}` line (item counts, captures, `hiddenWords`, `target`, `modelDrops`, `blockedRequests`, `closedPopups`). The text-missing line is `{"slideIndex", "words"}`: the slide, and how many of its words are missing; the words themselves are logged only with the debug text on (*What reaches the app's log*, below). The wrapper echoes them into the app log, and the export-fidelity harness reads them ([Export Fidelity Harness](export-fidelity-harness.md)).

**What a slide's page may load** (`request_guard.cjs`). The export loads each slide from a `file:` URL, and nothing in a page stops its script navigating it elsewhere: one line of slide script used to export `file:///etc/hosts`, or a directory's listing, and on Databricks Apps any user who can edit a slide could have read the container's files into a deck. So each slide runs in a browser context of its own whose every request Node decides, through Playwright's routing, whatever the document says:
- allowed: the slide's own file URL, exactly; `data:` and `blob:`; and an https request, on https's own port and without credentials, to a host the slide CSP allows for its kind of request: a script `script-src`'s (`cdn.jsdelivr.net`, `cdn.tailwindcss.com`), a stylesheet `style-src`'s (`fonts.googleapis.com`), a font `font-src`'s (`cdn.jsdelivr.net`, `fonts.gstatic.com`). The hosts are `SLIDE_CSP`'s own: `src/utils/html_safety.py` derives them (`slide_csp_request_hosts`, which refuses a CSP source it could not mirror) and the wrapper passes them in the stdin payload as `allowedHosts`; a payload without them loads no https host;
- aborted, with `ERR_ABORTED` (a frame commits no error page): any other `file:`, `http:`, a loopback or link-local address, any other host, a frame's navigation anywhere but the slide; WebSockets are closed before they connect, and popups (`window.open`) are closed. The slide summary counts both (`blockedRequests`, `closedPopups`);
- failed: a main-frame navigation away from the slide, by a request (`location`, a meta refresh) or not (a `blob:` URL): the slide is stopped at once, its browser closed, and it fails with "the slide's page navigated away from the slide", the failure the routes report (`X-Huashu-Failures`); the rest of the deck exports.

Playwright's routing sees a redirect chain's first request alone, so a redirect from a CSP host is followed unchecked; what a slide loads from those hosts is a script, a stylesheet or a font, whose bytes the page cannot read, and a document, which would show what it reached, is never allowed to them.

**A slide's deadline.** Each slide has `SLIDE_DEADLINE_MS`, 30 s, from its browser's launch to its last read (`render_slide.cjs`). A slide whose script blocks its page (a busy loop) used to hang the deck until the 180 s sidecar timeout, losing every slide; now it is stopped at its deadline, its browser closed, and it fails alone with "the slide did not finish within 30 s"; the deck goes on. Measured: the slowest slide of both corpora and three matrix decks takes 3.2 s on a dev Mac (a Chart.js slide), the median 1.0 s, and Apps renders a slide in about a Mac's time; the engine's own bounded waits add up to 26 s, so the deadline fails no slide those waits let through, and a deck with one blocked slide keeps 150 s for the rest.

**What reaches the app's log.** Every line the sidecar prints on stderr is echoed into the app's log (`[huashu-emit] …`), which every manager of the app reads, outside Tellr's per-deck permissions. So no line holds a slide's own text: the summary counts its hidden words (`hiddenWords`), the text-loss line counts its lost words, a validation message names the text box it quotes by its length, and a message a slide's page made (a read that failed, a slide's failure) is said by its length; a failure that holds no page text (a browser that cannot launch, a slide past its deadline or one that left itself) is logged whole. What a page logs itself with the engine's prefixes, `[preprocess]` and `[html2pptx]` (to stderr), or anything else (to stdout, which the wrapper never echoes), is cut at 1,000 characters, at most 100 messages a slide per stream, and the rest counted. `TELLR_EXPORT_DEBUG_TEXT=1` adds the words: the summary's `hiddenText`, a second text-loss line naming them, the quotes and the messages. No app passes it: it is not in the sidecar's env allowlist. The export-fidelity harness adds it for its own runs (`sidecar_debug_text`), since it reads each slide's hidden text. A failure's whole message stays in the failure list, which goes to the user who exported the deck.

**Temporary files.** The sidecar writes each slide's HTML to a file for its browser to load, in a `huashu-deck-*` directory it removes however the deck ends; and it runs with a `TMPDIR` of its own, the export's `TemporaryDirectory` (which holds the written deck), made where its `TMPDIR` would otherwise be. So what a sidecar ended at its timeout leaves, its slides and its browsers' profiles, is removed with that directory.

**Renderer target.** `build_pptx_huashu(..., target=...)` names the app the deck is written for: `"pptx"` (PowerPoint, the download) or `"gslides"` (the Google Slides route). The two draw a few constructs apart, so only those are written differently: lines that hold a superscript or subscript run (A4, A5); each run's tracking, which for PowerPoint folds in the run's kerning, since PowerPoint for Mac kerns no DM Sans (X1); an italic run of a webfont, which for PowerPoint is its italic static's own name, since PowerPoint draws the family plus italic as Bold Italic (D1); a bold run only a lighter loaded face meets (the browser's synthetic bold), which for Google Slides is that face alone, since Drive makes any bold flag weight 700 and Google lays such a bold out wider than it draws it, so right-aligned figures ended short (D12); a hyphen the face lacks (D8); a native table's grid, which for PowerPoint lies on whole pixels (D7), and its rounded corner fills, which for Google Slides run 1 px under their opaque neighbour cells (D13); and a dotted border, which for Google Slides is one custom shape drawing the border's centre line twice, two widths apart, since every dot dash Drive has draws one width on and three off (D6). The measurements are in `scripts/export_fidelity/CALIBRATION.md`.

**Fonts and the face written.** Text whose stack has no webfont the page loaded is laid out in the machine's own faces, so the export's container ships faces a desktop has, and the deck names the face the browser drew (Task 15 B8, N3 and N4):
- **The container's faces.** The sidecar's font bundle, `services/pptx-emit-huashu/fonts-liberation.tar.gz` (2.4 MB: Liberation Sans, Serif and Mono 2.1.5, regular, bold, italic and bold italic, their OFL licence, and `fonts.conf.in`), is extracted by `setup.sh` at boot into `fonts/`, whole or not at all: into a staging directory made fresh for the boot first (`mktemp -d`, `fonts-staging.XXXXXX`, beside `fonts/`), moved into place once `tar` has succeeded and stamped, so an extraction cut off part way is done again on the next boot, one that fails leaves the bundle in place as it was, and a staging directory an earlier boot could not remove blocks no later one. For a whole bundle alone `setup.sh` writes `fonts/fonts.conf`, with that directory's absolute path, and the wrapper sets `FONTCONFIG_FILE` to it (`sidecar_subprocess_env`). Nothing in the font step stops the boot: Chromium is still installed. **The upgrade-boot window:** `setup.sh` runs in the background while the app starts (the app template's boot command), and on a boot whose bundle is newer than the one in place it moves the old `fonts/` aside, moves the new one in and only then writes its `fonts/fonts.conf`. For that moment, two renames and the config's writing, no config is in place, so an export that starts then gets no `FONTCONFIG_FILE`, and its text with no loaded webfont is laid out in the base image's DejaVu. A boot whose bundle is unchanged has no such window, and nor has a first boot, whose exports wait for Chromium, which `setup.sh` installs after the font step (until then the export is unavailable, 503). `setup.sh` logs to `$HUASHU_SETUP_LOG`, `/tmp/huashu-setup.log` when it is not set, and the diagnostics below read the same. Operators can see the bundle: `GET /api/export/pptx/editable/huashu/available` (admins) answers `checks.font_bundle`, whether `fonts/fonts.conf` is in place, and logs server-side the config's path, how many Liberation faces are beside it and setup's `[setup] … fonts` lines; the export's availability does not depend on it. Arial and Helvetica, Times New Roman and Times, Courier New and Courier, and `sans-serif`, `system-ui`, `serif` and `monospace` are their metric-compatible Liberation faces; a name the container has no face for (Inter, Segoe UI, Roboto) draws nothing, so the stack goes on to its next family, as on a desktop that lacks it, and a stack with none left is set in the standard face, Liberation Serif, as a Mac sets it in Times. The base image's DejaVu stays for the characters Liberation lacks (check marks, stars), but no stack can name it. On Linux Chromium also lays glyphs out unhinted (`--font-render-hinting=none`), so a webfont's advances are not rounded. Measured on Apps' Chromium against the Mac's: every such stack lays out at 1.0000 of the Mac's widths (12 sizes, 3 weights, italics), webfont lines within 0.0004 (they were 0.95 to 1.08), and on the 19 real decks of the Task 15 matrix the Apps export and the laptop's export of the same HTML have a median single-line width ratio of 1.000, with 2 of 1,539 text boxes breaking differently (133 of 1,527 before), both on a deck that names DM Sans without loading it, which the owner's Mac has installed. The bundle is built reproducibly from a pinned release by `scripts/sidecar_fonts/build_fonts_tarball.py`; it adds 2.4 MB to the wheel (34.2 MB, from 32.0 MB).
- **The face written** (`snapshot_text_metrics.mjs` resolveWrittenFaces). Each family of the run's stack is probed alone on the run's own characters, with a font after it whose every glyph is 4 em wide (`coverage_font.mjs`): the first that draws any of them is the one the browser's font matching took, which agreed with the DevTools protocol (`CSS.getPlatformFontsForNode`) on the runs of the matrix decks and both corpora that could be compared: on Apps on all 3,147, none against; on a Mac on 3,135, and 13 differ in name only (a deck names DM Sans without loading it and the Mac has its statics installed: the protocol names the 500 static "DM Sans Medium", and the run is written "DM Sans", by the rule for a family the page did not load; `scripts/export_fidelity/CALIBRATION.md` N4). It is written:
  - Arial for Arial, Helvetica, Liberation Sans and Arimo; Times New Roman for Times New Roman, Times, Liberation Serif and Tinos; Courier New for Courier New, Courier, Liberation Mono and Cousine;
  - a generic or system face as the face the container draws for it: `sans-serif` and `system-ui` (SF on a Mac) Arial, `serif` Times New Roman, `monospace` Courier New; `cursive`, `fantasy`, `emoji` and `math` draw nothing in the container, so Times New Roman;
  - Times New Roman where nothing in the stack draws, which is text with no font of its own;
  - a webfont the page loaded later in the stack by its own name (and weight); any other face installed on the machine as itself (a laptop's own fonts); never the container's own DejaVu, a face the page did not load. A webfont the page loaded is the page's own bytes, so it is written by its own name whatever that is, DejaVu included.
  
  `font-family: system-ui, Arial` at 600 is Arial plus bold. A table cell's own face is resolved the same way.
- **Symbols.** 982 characters outside WGL4 (superscript digits, currency, arrows, mathematical operators, enclosed numbers, box drawing, the Harvey quarters ◔◑◕, ✓, ★ and other dingbats) are drawn alike, glyph for glyph, by MS PGothic and MS Gothic in PowerPoint and Google Slides. Written in Arial or Times New Roman, PowerPoint for Mac draws them from Segoe UI Symbol, Cambria Math or Apple Color Emoji at 0.72 to 1.12 em, and Google from MS PGothic. So such a character is a run of its own in MS PGothic (MS Gothic in a monospace run) wherever the written face lacks it: always for Arial, Times New Roman and Courier New, bar the 19 each draws itself, and where the coverage probe says a webfont lacks it (`SYMBOL_COVERAGE`, measured: `scripts/export_fidelity/CALIBRATION.md` D8).
- **Time.** On Apps the 28-slide real decks take 0.8 to 1.5 % longer than before (7 to 13 ms a slide).

**Determinism.** Identical rendered pages give byte-identical `.pptx` files, apart from the timestamps in `docProps/core.xml`: item and capture ids are sequence numbers in document order. Two exports of the same deck can still differ slightly when the page itself differs: **live Google Fonts responses vary**. Google now and then serves a different DM Sans binary for the same `@import` (measured: 4 of 40 fresh loads), whose glyph widths differ by a fraction of a px, so text widths in the export move with it. The variance is external to the engine. The unit tests load nothing from the network: every export a test runs gives the sidecar no host, so its request guard aborts any live fetch and the test fails naming it (`tests/unit/conftest.py`), and the test documents embed the corpus's webfonts (`DECK_CSS`, `pinned_font_css`) and write a vendored Chart.js inline (`tests/fixtures/export_snapshot_support.py`), so exports compare byte for byte.

**Time and limits.**
- A slide takes about 1.5 s on a dev Mac (measured 2026-11-20: 1 slide 1.5 s, 5 slides 6.4 s, 17 slides 25.0 s; one browser per slide). That is about 8% slower than the converter it replaced (1.47 against 1.36 s per slide, same corpus, Chrome channel and Playwright).
- One sidecar run is bounded by `SIDECAR_TIMEOUT_SECONDS`, 180 s, as before: decks of more than about 120 slides time out. A timed-out sidecar is ended with every Chromium it launched (`run_sidecar_process`), and the route answers 504. Each slide is bounded by `SLIDE_DEADLINE_MS`, 30 s, past which it fails alone (*A slide's deadline*, above).
- Each worker process runs at most `TELLR_SIDECAR_CONCURRENCY` sidecars at once (default 1; a node and Chromium tree takes about 790 MB). At most `TELLR_SIDECAR_QUEUE` more exports (default 15) wait for a slot, each for up to `TELLR_SIDECAR_WAIT_SECONDS` (default 60 s). An export past either bound is answered **429**, `Retry-After: 60`, "Exports are busy right now. Please try again in a minute.", which the UI shows as it is (no fallback). Waiting exports hold threads of the worker's threadpool (40), so the queue keeps the rest free for every other request.
- The Databricks Apps proxy ends a request after about **300 s** (measured on 2026-11-20: requests of 30 to 185 s returned 200, one of 310 s got 502 at 300.4 s). With the defaults, the slowest route, Google Slides, answers within it: 60 s of waiting, the 180 s run, and the Drive upload, whose every request fails after 60 s without an answer (`DRIVE_HTTP_TIMEOUT_SECONDS`), a 502 "Drive upload failed". Bounds set past these limits are warned about in the log when the app starts.

### The export summary line

Every export logs one line once it ends, however it ends, so export times and memory can be read from a deployed app's logs. Each build is measured the same way, from this same line. The test corpus, measured on a dev Mac when it had 17 slides (2026-11-21; no cgroup there, so both container keys are `null`):

```text
[huashu] export summary {"target":"pptx","slides":17,"slidesExported":17,"failures":0,"outcome":"ok","waitSeconds":0.0,"runSeconds":22.834,"secondsPerSlide":1.343,"peakRssMb":837.6,"containerPeakMb":null,"containerWorkingSetMb":null,"pptxBytes":1560992,"sidecarConcurrency":1,"queueBound":15}
```

| Key | What it holds |
|---|---|
| `target` | `pptx` (the PowerPoint download) or `gslides` (the Google Slides route) |
| `slides` | The slides the export was asked for |
| `slidesExported` | The slides in the deck it wrote; 0 when it wrote none |
| `failures` | The slide failures it returned: one per slide that failed, or one for a sidecar that failed before any slide |
| `outcome` | `ok`: a deck, no slide failed. `partial`: a deck, some slides failed. `failed`: no deck, because every slide failed or the sidecar did. `timeout`: the run passed `SIDECAR_TIMEOUT_SECONDS`. `busy`: refused, HTTP 429 |
| `waitSeconds` | The time spent waiting for a sidecar slot; 0 for an export refused at once |
| `runSeconds` | The sidecar's wall time; `null` when no sidecar ran (`busy`) |
| `secondsPerSlide` | `runSeconds / slides`; `null` with it |
| `peakRssMb` | The most resident memory (RSS, in MiB) the sidecar's process tree held at once: node and every Chromium it launched. Playwright starts each browser in a process group of its own, so the tree is found through the parent chain, not the group. It is read every 0.25 s while the sidecar runs, in one pass of `/proc` (Linux) or `ps` (macOS), and the largest reading is kept. `null` when no sidecar ran or a reading failed |
| `containerPeakMb` | The most memory the whole container's cgroup held during the export, in MiB: its `memory.current` (cgroup v2), else its `memory.usage_in_bytes` (v1), page cache included. It is read in the same passes as `peakRssMb`, and the largest reading during the export is kept, not the cgroup's lifetime `memory.peak`. `null` where there is no cgroup (macOS), when no sidecar ran, or when the cgroup could not be read |
| `containerWorkingSetMb` | The most the container's working set reached during the export, in MiB: its usage less the page cache nothing has used lately (`memory.stat`'s `inactive_file`, v1's `total_inactive_file`), never below 0, as the kubelet and cAdvisor count it. Each reading is taken whole in one pass, so its peak need not fall where the usage peaked. `null` as for `containerPeakMb`, and where `memory.stat` gives no inactive file figure |
| `pptxBytes` | The size of the deck; 0 when it wrote none |
| `sidecarConcurrency` | `TELLR_SIDECAR_CONCURRENCY` for the worker |
| `queueBound` | `TELLR_SIDECAR_QUEUE` for the worker |

The line carries counts and timings only: no slide content, title, notes, user or file path. A call stopped before any export starts logs none: an unknown target, or the pipeline unavailable on this deployment (503). A memory reading that fails never fails or slows the export. The process tree and the cgroup are read apart, and fail apart. A process table that cannot be read nulls `peakRssMb` only, and a cgroup that cannot be read or parsed nulls the two container keys only. A `[huashu] export memory of … not read` warning says which and why, unless the export had logged its line already.

**The three memory figures.** Each answers its own question:
- **`peakRssMb` compares builds.** It is this export's own processes only, summed per process. Memory the processes share (Chromium's shared libraries and its shared memory between its processes) is counted in each, so it is an upper bound for the export, measured the same way on every build.
- **`containerPeakMb` is the container's whole usage.** It covers every worker of the app and every export running then, with shared pages counted once. It also holds the page cache, file data the kernel keeps in memory and gives back under pressure. So it can read higher than `peakRssMb`, with the app, the other exports and the cache in it. It can also read lower, because `peakRssMb` counts each shared page once per process. It always bounds the working set from above.
- **`containerWorkingSetMb` judges headroom.** It is that usage less the inactive page cache: the memory the container cannot give back quickly. This is the figure the kubelet and cAdvisor watch against the limit.

To judge whether memory is comfortable, read `containerWorkingSetMb` against the container's limit. Each worker logs the limit once, when it starts:

```text
[huashu] container memory limit 4096.0 MB
```

**Which cgroup is read.** The container's own cgroup, as `/proc/self/cgroup` names it: the `0::<path>` line under cgroup v2, the memory controller's line under v1. The path is looked for under `/sys/fs/cgroup` (v2) or `/sys/fs/cgroup/memory` (v1), where a host's whole tree is mounted. Where it is not there, the container sees its own cgroup as that root, through a private cgroup namespace or a bind-mounted view, and the root is read. A path that climbs out (`..`) means the process sits outside the cgroup root it sees, so that root is not its own cgroup. Nothing is read for that cgroup version: the container keys are `null`, and the limit line says `none`. The limit is the smallest set on that cgroup or on any cgroup above it in view, since each of them charges it: a pod's limit sits on the pod's cgroup, above its container's. It is read from `memory.max` (`max` means none), else `memory.limit_in_bytes` (v1's largest value means none). The line says `none` when no limit is set, or when there is no cgroup (macOS).

**Reading the lines on Apps.** These were measured on 2026-11-21 with the Databricks CLI v1.20.0, read-only, against a deployed app. `databricks apps logs` needs an OAuth (U2M) profile. It refuses a PAT profile with "OAuth Token not supported for current auth type pat". Sign in with `databricks auth login --host <workspace-host> -p <oauth-profile>`, as for reading deploy logs (`.claude/skills/deploy-tellr-dev`).
- **To collect every summary the log service holds,** about 5 days back, run:

  ```bash
  databricks apps logs <app> --profile <oauth-profile> --search "huashu] export summary" --tail-lines 100000 \
    | grep "huashu] export summary"
  ```

  `--search` sends the term to the log service, which answers in about 3 s. One measured run reached back about 5 days, 11,088 entries. Its match is loose (it returns other lines too), so the `grep` keeps only the summaries. The same with `--search "container memory limit"` finds the startup limit lines.
- **Without `--search`, only the latest window comes back.** Even `--tail-lines 100000` reached only about 728 lines, about 5.6 hours of this app's log, and the default is 200 lines.
- **`--tail-lines 0` does not return.** It streams live lines until it is interrupted.
- **To watch exports as they run,** run:

  ```bash
  databricks apps logs <app> --profile <oauth-profile> --follow | grep --line-buffered "huashu] export summary"
  ```

- **To keep what a command shows in a file as well,** add `--output-file <path>`.
- **To leave each line's JSON,** add one of the following. Every Apps log line starts with its time and `[APP]`:

  ```bash
  … | sed -n 's/.*huashu] export summary //p' | jq -c .
  … | sed -n 's/.*huashu] export summary //p' \
      | jq -r '[.target, .outcome, .slides, .runSeconds, .peakRssMb, .containerWorkingSetMb] | @tsv'
  ```

The summary and the limit lines have their own logger, `src.services.pptx_from_html_huashu.telemetry` at INFO, which writes each record to stderr as one line. It does not go through the app's root handler. In a worker, that handler is FastMCP's `RichHandler`, which wraps a long message into narrow pieces where stderr is not a terminal, as on Apps. Through it, even the line's prefix would be split.

### What the export trades away

These are deliberate, each the closest a slide can come in an editable file:
- **Line breaks are the UI's.** Each line is the browser's line: a block of one line is written `wrap="none"`, and every box carries a little width slack, so a slightly wider font in PowerPoint or Slides never re-wraps a line. Editing a line does not re-flow the lines after it, as it would in a text box typed from scratch.
- **Tables are native, with exceptions.** A table becomes editable positioned items (cell boxes as shapes, cell text as text boxes) when no `<a:tbl>` can draw it: card tables (`border-collapse: separate` with visible spacing and painted cells), a table a clip cuts part of, the outer table of a nested pair, and overlapping row and column spans.
- **A sentence with chips is several boxes.** An inline element with padding, a border or a margin (a chip, a `<kbd>`) cuts its line, so each piece is a text box of its own at the browser's exact position.
- **Some mixed corners are freeforms.** A box whose corners round by different radii stays a preset when one draws it exactly (`16px 16px 0 0`, the rounded-top rectangle; `16px 0`, the diagonal one; `0 16px 0 0`, the one-corner one), whose handles still work; any other mix is a custom shape, which moves and recolours whole but scales its corners with it when resized.
- **Charts are pictures.** A chart's SVG or canvas is a high-resolution picture; titles, legends and labels written in HTML stay editable text.
- **Google Slides superscripts are a little small.** In the deck written for Google Slides, a superscript or subscript on a line the browser did not grow is drawn at 0.8 of its browser size, so the line itself sits where the browser has it.
- **A Mac's system face is written as the container's.** Text the Mac draws in SF (`system-ui`, `-apple-system`) or another face no app has (Apple Chancery for `cursive`) is written as the face the export's container draws for it (Arial, Times New Roman), whose widths the deck on Apps is laid out at. The laptop's own export of such text keeps the Mac's layout, up to 9 % off the written face's widths at the extremes of SF's optical sizes.
- **Symbols are MS PGothic.** A symbol outside WGL4 is written in MS PGothic or MS Gothic, which every app draws alike, at its advance (0.5 em for the Harvey quarters, where the browser lays out 0.6). On Windows those faces come with the Japanese fonts: where a machine lacks them, PowerPoint falls back per glyph, as it does for these characters in any other face.
- **CJK and emoji have no face in the export's container.** The container ships no CJK or emoji fonts (Noto Sans CJK alone is 95 MB zipped, almost three times the whole wheel), so such text is laid out at the replacement glyph's width (0.74 to 0.88 of a Mac's) and shows empty boxes in a captured picture; the deck keeps every character, and each app draws it in its own fallback face.
- **The Google export is its own variant.** The Google Slides route writes a deck for Google Slides (`target="gslides"`), not the PowerPoint download, so the two files can differ on lines with script runs.

## User Guide

### How to Export

1. **Access Export Menu**
   - Click the blue "Export" button in the top-right of the slide panel
   - A dropdown menu will appear with two options:
     - "Export as PDF" (document icon)
     - "Export as PowerPoint" (file icon)

2. **Export as PDF**
   - Click "Export as PDF"
   - The export process runs entirely in your browser
   - A PDF file will be downloaded automatically
   - Filename format: `{slide_deck_title}_{timestamp}.pdf`

3. **Export as PowerPoint**
   - Click "Export as PowerPoint"
   - The primary path sends only `session_id` to the **synchronous** snapshot-engine route and downloads the returned PPTX blob — there is no job/poll cycle
   - If that pipeline is unavailable on the deployment (HTTP 503, or an error naming the pipeline as unavailable or still installing), the UI extracts DOM records client-side and retries through the records fallback
   - If the worker is busy (HTTP 429, see *Time and limits*), the UI shows "Exports are busy right now. Please try again in a minute." and does not fall back
   - A PPTX file will be downloaded automatically when complete
   - Filename format: `{slide_deck_title}_{timestamp}.pptx`

### Export Status

- The export button shows "Generating PPTX…" while the primary path runs, and "Falling back to records pipeline (slower)…" if the fallback is taken
- The dropdown menu closes automatically when an export starts
- A **partial** export is reported loudly: a persistent error toast names each slide that failed, because the downloaded file is silently missing them
- If an error occurs, the message is surfaced to the user

## Technical Details

### PDF Export (Client-Side)

**Location**: `frontend/src/services/pdf_client.ts`

**Technology Stack**:
- `html2canvas`: Converts HTML slides to canvas images
- `jsPDF`: Generates PDF from canvas images

**Process**:
1. Each slide is rendered in a hidden iframe (1280×720px) with `sandbox="allow-scripts"` (no `allow-same-origin`)
2. A trusted bootstrap inside the frame waits for Chart.js, force-sizes the slide root, and rasterizes the slide
3. The child returns a JPEG data URL over `postMessage`; the parent authenticates `event.source`, a per-frame channel ID, and the request ID

html2canvas 1.4.1 is still bundled into the export `srcdoc` from the npm package (not a CDN). It cannot clone through a nested iframe here: nested frames inherit `sandbox="allow-scripts"` and become a different unique origin, so the library cannot read the clone document. Full-slide capture therefore inlines computed styles and draws via SVG `foreignObject` in the export frame itself. Chart canvases are still read with `canvas.toDataURL` in that same frame.
4. Adds the image to a PDF page (maintains 16:9 aspect ratio)
5. Repeats for all slides, tearing down each frame
6. Downloads the complete PDF

Persisted slide JavaScript can paint the export document but cannot read the Tellr SPA, call `/api` as the exporter, or fall back to an unsandboxed frame.

**Features**:
- ✅ No server load (runs entirely in browser)
- ✅ Fast processing
- ✅ Works offline
- ✅ Preserves Chart.js visualizations
- ✅ Optimized file size (JPEG compression, 1.2x scale)

**Configuration**:
```typescript
{
  format: 'a4',           // Page format
  orientation: 'landscape', // Page orientation
  scale: 1.2,              // Image scale (quality vs size)
  waitForCharts: 2000,     // Wait time for charts (ms)
  imageQuality: 0.85       // JPEG quality (0-1)
}
```

**Limitations**:
- File size can be large for many slides (typically 5-15MB per slide)
- Requires modern browser with canvas support
- Charts are rendered as images (not editable in PDF)

### PPTX Export (Server-Side Async) — legacy

> **Historical note.** The LLM code-generation path described in this section
> (`src/services/html_to_pptx.py`, `POST /api/export/pptx` and its `/async`
> twin, and the `export_job_queue` worker) is **superseded** by the huashu
> render above and is no longer the route the UI calls: no caller exists in
> this repository's checked-in frontend, though external direct callers cannot
> be ruled out from here. It re-runs per-slide code generation on every request and is
> therefore non-deterministic. The code still exists but should be treated as
> legacy; the detail below is retained for readers working on that code and is
> not a description of current export behaviour.

**Location**: 
- `src/api/routes/export.py` - API endpoints
- `src/api/services/export_job_queue.py` - Background worker and job queue
- `src/services/html_to_pptx.py` - LLM-powered converter

**Technology Stack**:
- `python-pptx`: Creates PowerPoint presentations
- `asyncio`: Background job queue with thread pool execution
- `svgpathtools` + `Pillow`: Pure-Python SVG-to-PNG conversion for image library assets
- LLM (Databricks Claude Sonnet 4.5): Analyzes HTML and generates slide layouts

**Process**:
1. Frontend captures Chart.js charts as base64 images client-side
2. Frontend calls `POST /api/export/pptx/async` to initiate export
3. Backend validates request and queues job, returns job ID immediately
4. Background worker (in thread pool) processes the export:
   - Fetches slide deck from database
   - Builds complete HTML for each slide (including `{{image:ID}}` → base64 substitution)
   - Extracts base64-embedded content images from HTML, saves as files in a per-slide assets directory, and replaces `<img src="data:image/...;base64,...">` with filename references
   - For each slide, LLM generates Python code to create PowerPoint slide (receiving clean HTML + image filenames, not raw base64)
   - Code is executed to add slide to presentation
   - Progress is updated after each slide
5. Frontend polls `GET /api/export/pptx/poll/{job_id}` for status/progress
6. When complete, frontend downloads via `GET /api/export/pptx/download/{job_id}`

**Features**:
- ✅ Native PowerPoint format (.pptx)
- ✅ Async with polling (avoids proxy timeouts)
- ✅ Real-time progress updates (slide X of Y)
- ✅ Client-side chart capture for accurate chart images
- ✅ Professional layouts with proper spacing
- ✅ Preserves colors, fonts, and styling
- ✅ No overlapping elements
- ✅ Background worker runs in thread pool (non-blocking)

**Configuration**:
```python
{
  use_screenshot: True  # Include client-captured chart images
}
```

**Limitations**:
- Requires server processing (5-15 seconds per slide)
- Requires LLM API access (Databricks endpoint)
- Polling interval: 2 seconds
- Maximum poll attempts: 300 (10 minute timeout)

## Architecture

### Frontend Components

**Export Button & Dropdown** (`frontend/src/components/SlidePanel/SlidePanel.tsx`):
- Blue-themed export button with download icon
- Dropdown menu with blue accents matching app theme
- Loading states for both export types
- Error handling with user-friendly messages

**PDF Service** (`frontend/src/services/pdf_client.ts`):
- Builds the slide document (CSP first, then the trusted export runtime)
- Asks `runSandboxedExportFrame` for a JPEG; does not read `iframe.contentDocument`
- Optimizes image quality vs file size
- Preserves subtitle spacing and canvas sizing inside the child runtime

**Sandboxed export frame** (`frontend/src/services/sandboxedExportFrame.ts` + `exportFrameRuntime.ts`):
- Shared controller for PDF, screenshot-PPTX, Chart.js canvas capture, and DOM-record export
- Opaque origin (`sandbox="allow-scripts"` only)
- html2canvas 1.4.1 is bundled from the npm package into the `srcdoc`; it is not loaded from a CDN
- Child CSP remains `SLIDE_CSP` (`connect-src 'none'`, no `unsafe-eval`, no `blob:`)

**API Client** (`frontend/src/services/api.ts`):
- `startPPTXExport()` - Initiates async export job
- `pollPPTXExport()` - Polls for job status and progress
- `downloadPPTX()` - Downloads completed PPTX file
- `exportToPPTX()` - Orchestrates the full async flow with progress callback
- Client-side chart capture before export

### Backend Components

**Export Route** (`src/api/routes/export.py`):
- `POST /api/export/pptx/async` - Initiates export job, returns job ID immediately
- `GET /api/export/pptx/poll/{job_id}` - Returns job status and progress
- `GET /api/export/pptx/download/{job_id}` - Serves completed PPTX file
- Validates slide deck availability before queuing

**Export Job Queue** (`src/api/services/export_job_queue.py`):
- Database-backed job tracking via `ExportJob` SQLAlchemy model
- `asyncio.Queue` for local worker dispatch within each process
- Background worker processes jobs in thread pool
- Thread pool execution prevents blocking event loop during LLM calls
- Progress tracking per job (slides completed / total) stored in DB
- Job cleanup is TTL-based: `GET /api/export/pptx/download/{job_id}` is idempotent and does not delete anything; a background sweep (`export_cleanup_loop`, every 5 min) removes completed/error jobs older than 30 min (DB row + temp file)
- Multi-worker safe: any process can read job status from the shared database

**PPTX Converter Service** (`src/services/html_to_pptx.py`):
- `HtmlToPptxConverterV3` class
- LLM-powered HTML to PPTX conversion
- Extracts base64-embedded content images (`_extract_and_save_content_images()`) before sending HTML to LLM
- Converts SVG images to PNG via `_svg_to_png()` using `svgpathtools` + `Pillow` (pure Python, no system dependencies)
- Generates and executes Python code for slide creation
- Ensures proper positioning and no overlaps

### Google Slides Export (Server-Side)

**Location:**
- `src/api/routes/google_slides.py` — API endpoints (auth + export); `_upload_session_deck` is the one Drive upload both export routes share
- `src/api/routes/admin.py` — Google credential management endpoints (upload, status, delete)
- `src/services/google_slides_auth.py` — OAuth2 flow and token management
- `src/services/pptx_from_html_huashu.py` — the snapshot engine's wrapper (`target="gslides"`)
- `src/services/drive_uploader.py` — the Drive upload, which converts the PPTX to Slides
- `src/services/html_to_google_slides.py` — the legacy LLM converter (no UI caller)

**Technology Stack:**
- Google Drive API: uploads the PPTX with `mimeType=application/vnd.google-apps.presentation`, which converts it to a native Slides presentation
- `google-auth-oauthlib`: OAuth2 authorization flow
- Fernet encryption (`cryptography`): Encrypts credentials and tokens at rest

**Process:**
1. Admin uploads `credentials.json` globally (one-time setup)
2. User authorizes via Google OAuth popup (one-time per user)
3. User clicks "Export to Google Slides"
4. Frontend calls `POST /api/export/google-slides/from-huashu` with the `session_id`
5. Backend checks the user may view the deck and is authorized, builds each slide's HTML, and runs the snapshot engine for Google Slides (`build_pptx_huashu(..., bypass_validation=True, target="gslides")`)
6. The PPTX is uploaded to Drive (a re-export replaces the session's earlier presentation), which converts it; every Drive request is bounded by `DRIVE_HTTP_TIMEOUT_SECONDS`
7. The response carries `presentation_id`, `presentation_url`, `total_slides`, `succeeded` and `failures`, in one synchronous round-trip
8. On a 503, which the route answers only where the sidecar cannot run (not installed or not enabled on the deployment, `HuashuUnavailableError`), the frontend falls back to `/from-records`. Every other failure it shows as the route words it, falling back on none: a 429 (the worker's exports are busy), a 504 (the sidecar ran past its timeout, `HuashuTimeoutError`) or a 500 (it failed otherwise). The PPTX route answers the same statuses

**Features:**
- Produces editable Google Slides (not static images), from the same snapshot of the page as the PowerPoint export
- Global credential storage (encrypted)
- Per-user OAuth tokens (multi-user safe)
- Stale token/credential auto-cleanup

**Configuration:**
- Google Cloud project with Slides API + Drive API enabled
- OAuth 2.0 Desktop Client credentials (`credentials.json`)
- Fernet encryption key for credentials/token storage — lives either in the `encryption_keys` Lakebase table (default) or in a Databricks secret injected as `TELLR_ENCRYPTION_KEY` (secret-backed deployments; see `docs/technical/databricks-app-deployment.md`)

**Limitations:**
- Requires Google Cloud project setup
- Requires user interaction for initial OAuth consent
- Processing time: about 1.5 s per slide for the render, plus the Drive upload (4–20 s measured)

For full technical details, see [Google Slides Integration](./google-slides-integration.md).

## Positioning Constraints (legacy LLM path)

The legacy LLM converter (`html_to_pptx.py`) prompts with strict positioning constraints to prevent overlapping elements. The snapshot engine needs none: it writes every item where the browser drew it.


- **Slide dimensions**: 10" wide × 7.5" tall
- **Safe bounds**: left ≥ 0.5", top ≥ 0.5", left + width ≤ 9.5", top + height ≤ 7.0"
- **Title**: left=0.5-1.0", top=0.5-1.0", height=1.0-1.5", ends ≤ 2.0", font ≤ 44pt
- **Subtitle**: left=0.5-1.0", top ≥ 2.3" (0.3" gap), height=0.8-1.0", ends ≤ 3.5", font ≤ 28pt
- **Body**: top ≥ 4.0", left ≥ 0.5", ends ≤ 7.0", font ≤ 18pt
- **Text wrapping**: Enabled on all text frames
- **No overlaps**: Verified for all element pairs

## Chart Handling

### PDF Export
- Charts are rendered as images in the PDF
- Chart.js visualizations are captured via canvas
- Charts appear exactly as they do in the browser

### PPTX and Google Slides Export (snapshot engine)

A chart's `<svg>` or `<canvas>` is captured server-side from the rendered page, after the export has waited for every canvas to be drawn and every animation to finish: a 2× picture at the chart's place. Its HTML title, legend and labels stay editable text. Nothing is captured in the browser tab, which may be closed or hidden while the export runs.

### PPTX Export (legacy LLM path)

**Chart Images (client-side capture)**:
- Charts are captured as base64 PNG images in the browser before export
- The frontend identifies all `<canvas>` elements within chart containers
- Canvas images are sent to the server as part of the export request
- Chart images are saved to a per-slide assets directory and referenced by filename in the LLM prompt

**Content Images (server-side extraction)**:
- Slides may contain `<img>` tags with base64 data URIs (e.g. uploaded logos or photos injected via `{{image:ID}}` placeholders)
- Before the LLM call, `_extract_and_save_content_images()` scans the HTML for `<img src="data:image/...;base64,...">` tags
- Each image is decoded and saved to the assets directory as `content_image_0.png`, `content_image_1.jpg`, etc.
- **SVG-to-PNG conversion**: SVG images (`image/svg+xml`) are automatically converted to PNG using `svgpathtools` + `Pillow` (pure Python). The converter parses SVG `<path>` elements, samples bezier curves to polygon points, and rasterizes them onto a Pillow RGBA canvas. This is required because `python-pptx` and Google Slides API only support raster image formats.
- The HTML `src` attribute is replaced with the filename so the LLM receives clean, compact HTML
- Extracted content image filenames are merged into the chart images list, so the LLM receives unified `add_picture()` instructions for all image assets

**LLM prompt integration**:
- Both chart and content image filenames are listed in the LLM user prompt via the `screenshot_note`
- The LLM system prompt includes a `CONTENT IMAGES` section instructing it to call `slide.shapes.add_picture()` for any `content_image_*.png` files
- This ensures images are positioned in the PowerPoint slide at their HTML layout location

## File Naming

PDF and PPTX filenames are timestamped; the deck spec's is not:

- **PDF**: `{slide_deck_title}_{YYYY-MM-DDTHH-MM-SS}.pdf`
- **PPTX**: `{slide_deck_title}_{YYYY-MM-DD}.pptx`
- **Deck spec**: `{title-slug}-spec.md` (no timestamp; `deck-spec.md` when the title has no letters or digits)

If the slide deck has no title, "slides" is used as the default for PDF and PPTX; see *Deck spec as Markdown* below for the spec's naming.

## Deck spec as Markdown (client-side)

**Where.** The Spec view header, **Export spec** button (accessible name "Export spec as Markdown"); shown only when the deck has a spec.

**Who.** Anyone who can see the Spec view, including `/view` (read-only viewers). The export carries the full `deck_spec` object, which every viewer already receives in the `get_slides` JSON. The file includes the Data section with each figure's source (`(source: …)`), which the Spec view itself does not show.

**Which spec.** The live deck's spec, as the Spec view shows it. A save-point preview carries no `deck_spec`, so the button is hidden while previewing.

**What.** The spec is rendered in a fixed section order:
1. Title (`# {title}`; `# Untitled deck spec` when blank)
2. Audience (`## Audience`)
3. Purpose (`## Purpose`)
4. Argument (`## Argument`)
5. Call to action (`## Call to action`)
6. Narrative arc (`## Narrative arc`, as a numbered list in the given order)
7. Design contract (`## Design contract`, ids only: `Design system #N`, `Template #N`, `Slide style #N`; `No design system or slide style pinned` when none is set)
8. Slide briefs (`## Slide briefs`, then `### Slide N` per slide in the given order, with Purpose, Content brief, Assumes, Hands off, Slide type when set, Look (when set), and Data references)
9. Data (`## Data`, with Synthesis, Figures, and Gaps)

The field `template_section_index` is omitted: it is a 0-based machine index into a pinned template, while `slide_type` carries the same binding by its human-facing label. A bare index next to a 1-based "Slide 1" heading would mislead. An empty value renders as `Not set.` and an empty list as `None.`; absent `resolved_data` or `data_references` render the same way.

**Known ambiguities.** A value that is literally `None.` or `Not set.` reads like the placeholder. Data references are joined with `, ` and figures are written `key: value`, so both are ambiguous when a value itself contains `, ` or `: `. The structure (headings, list items) stays unambiguous; only the human reading of those lines is.

**Normalisation, by code point** (not `\s`: JavaScript and Python disagree on it):
- Remove U+0000–U+0008, U+000E–U+001F, U+007F–U+0084 and U+0086–U+009F
- Collapse each run of U+0009–U+000D, U+0020, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000 and U+FEFF to one space
- Trim

**Escaping** (CommonMark §2.4):
- Backslash before each of `` \ ` * _ [ ] < > # | ~ $ & @ ``
- Also before a leading `-`/`+`/`=`, and before the `.`/`)` of a leading ordered-list marker: 1 to 9 digits, then `.` or `)`, then a space or the end of the value (e.g., `2024\. A year`; `11.4%` and a 10-digit number are left alone)
- Integer ids are written verbatim, and an integer position as `position + 1`; any other value in a numeric slot is escaped as text, so a non-integer position gives `### Slide {escaped value}`, with no +1
- **Pasting into GitHub.** GitHub honours the `\|` and `\~` escapes, so a pasted export forms no table or strikethrough. Its math, `@`-mention, `#N` issue-reference and bare-URL/email autolinking run after Markdown parsing and ignore backslash escapes (checked against GitHub's markdown API, 2026-10-20): a value like `$4 to $5` can render as inline math, `@name` still mentions, and the fixed `Design system #7` / `Template #3` lines link to issues 7 and 3 of the repo they are pasted into. None of these changes the document structure, and no link hides a target behind different text. `$` and `@` are still escaped because other renderers (e.g. pandoc's dollar-math and citations) honour the escape.

**Determinism.** No clock, locale or randomness. Fixed section order; object keys read by name, never by iteration. `narrative_arc` and `slides` keep their given order. Blocks joined by exactly one blank line; LF only, no trailing whitespace, one trailing newline.

**Filename.** `deckSpecMarkdownFilename(title)` → `{slug}-spec.md`, where slug is the title lowercased and normalized to NFC, with every run of characters that are not letters, digits or marks replaced by `-`, leading and trailing `-` stripped, truncated to 60 code points, trailing `-` stripped again. A title with nothing left after that yields `deck-spec.md`.

**Download.** A `Blob`, an object URL and `<a download>`. The object URL is revoked 10 seconds (REVOKE_DELAY_MS) after the click, not synchronously, to avoid historical Safari/Firefox download failures. MIME type: `text/markdown;charset=utf-8`.

**No route, no request.** The export computes on click from the spec the Spec view already holds, with no server round-trip.

**The contract.** `frontend/tests/fixtures/deck-spec-markdown/full.deck-spec.json` → `full.md`, byte-exact. Any backend or MCP renderer must reproduce it; changing the format means updating both the code and this fixture in the same change.

**Code.** `frontend/src/services/deckSpecMarkdown.ts` (renderer, section order, labels, escape sets, code-point constants CONTROL_CHARS / WHITESPACE_RUN, `deckSpecMarkdownFilename`, `DECK_SPEC_MARKDOWN_MIME`), `frontend/src/utils/downloadFile.ts` (downloadTextFile function, REVOKE_DELAY_MS constant), and `frontend/src/components/SpecView/SpecView.tsx` (Export spec button in the header's right-hand group).

## Troubleshooting

### PDF Export Issues

**Problem**: White space in PDF
- **Solution**: This is usually resolved by the current implementation. If it persists, check that slides are exactly 1280×720px.

**Problem**: Charts not appearing
- **Solution**: The export waits for Chart.js to render. If charts still don't appear, check browser console for Chart.js errors.

**Problem**: Large file size
- **Solution**: File size is optimized with JPEG compression (quality 0.85) and 1.2x scale. For smaller files, reduce `imageQuality` or `scale` in the export options.

**Problem**: First slide content trimmed
- **Solution**: The implementation includes special handling for the first slide with additional wait time and canvas cropping logic.

### PPTX and Google Slides Export Issues (snapshot engine)

**Problem**: "Exports are busy right now. Please try again in a minute." (HTTP 429)
- **Solution**: The worker already runs its sidecars and holds its full queue (`TELLR_SIDECAR_CONCURRENCY`, `TELLR_SIDECAR_QUEUE`), or the export waited `TELLR_SIDECAR_WAIT_SECONDS` for a slot. Retry after a minute; for sustained load, raise the concurrency within the memory the app has (about 790 MB per sidecar).

**Problem**: The export falls back to the records pipeline ("Falling back to records pipeline (slower)…")
- **Solution**: The sidecar is not available on this deployment (HTTP 503): it needs `HUASHU_PIPELINE_ENABLED=1`, node, the sidecar's `node_modules` and a Playwright Chromium, which the app's boot installs with `setup.sh`. Until that finishes, the fallback is expected.

**Problem**: "Drive upload failed" (HTTP 502)
- **Solution**: Drive refused the upload or did not answer within `DRIVE_HTTP_TIMEOUT_SECONDS`. The deck was rendered; the app log names the Drive error.

**Problem**: A slide is missing text, or `MODEL DROPS` appears in the harness
- **Solution**: Read the slide's `[html2pptx] text missing:` and `slide summary` lines in the app log: the first says how many words the slide lost, and `modelDrops` counts model items that failed validation and were left out. To see the words, export the deck locally with `TELLR_EXPORT_DEBUG_TEXT=1` through the export-fidelity harness, which passes it to its sidecar; no deployed app logs them.

**Problem**: A slide fails with "the slide's page navigated away from the slide"
- **Solution**: Its script set `location`, ran a meta refresh, or opened a `blob:` page in the main frame. An export reads nothing but its own slide, so the slide is stopped; remove the navigation from the slide.

**Problem**: A slide fails with "the slide did not finish within 30 s"
- **Solution**: Its script kept the page busy (a loop that never yields, or an endless re-render). The rest of the deck exported; fix the slide's script.

### PPTX Export Issues (legacy LLM path)

**Problem**: Export fails with "No slide deck available"
- **Solution**: Ensure you have generated slides before attempting export. The export requires an active slide deck.

**Problem**: Export times out (504 Gateway Timeout)
- **Solution**: The async polling architecture handles long exports. If timeouts still occur:
  - Check that the backend logs show "Export worker picked up job"
  - Verify the export_worker is running (check startup logs)
  - The 10-minute polling timeout may need extension for very large decks

**Problem**: Progress stuck at 0
- **Solution**: Check backend logs for errors in `process_export_job`. The worker may have encountered an error fetching slides or during LLM calls.

**Problem**: Elements overlapping in PPTX
- **Solution**: The LLM prompts include strict positioning constraints. If overlaps occur, the prompts may need adjustment in `src/services/html_to_pptx.py`.

**Problem**: Charts not appearing in PPTX
- **Solution**:
  - Ensure charts are visible on screen before exporting (client-side capture requires rendered charts)
  - Check browser console for errors during chart capture
  - Verify the chart container has a valid `<canvas>` element

**Problem**: Uploaded images show as text/filename in PPTX instead of rendering
- **Solution**:
  - Check backend logs for "Extracted content image" messages to confirm extraction is running
  - Verify the `<img>` tag uses a standard `data:image/(png|jpeg|gif|svg+xml);base64,...` format
  - The LLM system prompt must include the `CONTENT IMAGES` section (check `pptx_prompts_defaults.py` or the profile's custom prompts)

**Problem**: "ModuleNotFoundError: No module named 'pptx'"
- **Solution**: Install dependencies: `pip install python-pptx`

## Best Practices

1. **For PDF Export**:
   - Use when you need quick, client-side export
   - Best for presentations with many slides (faster)
   - Good for sharing/viewing (universal format)

2. **For PPTX Export**:
   - Use when you need editable PowerPoint files
   - Best for presentations that need further editing
   - The export renders the deck server-side and waits for charts and animations itself; the browser tab can be left

3. **Chart Considerations**:
   - PDF: Charts are images (not editable)
   - PPTX: Charts are captured as images from the browser, preserving exact appearance

## Future Enhancements

Potential improvements for export features:

- [ ] Batch export options (export multiple formats at once)
- [x] Export progress indicator for PPTX (showing slide-by-slide progress) - **Implemented**
- [ ] Custom export templates (different layouts/styles)
- [ ] Export preview before download
- [ ] Export scheduling/automation
- [ ] Compression options for PDF
- [ ] Export quality presets (high/medium/low)
- [x] Persistent job storage (survive server restarts) - **Implemented** (DB-backed ExportJob model)
- [x] Google Slides export - **Implemented** (OAuth2, encrypted credential storage, the snapshot engine's deck converted by Drive)

## Related Documentation

- [Backend Overview](../technical/backend-overview.md) - Backend architecture
- [Frontend Overview](../technical/frontend-overview.md) - Frontend architecture
- [Slide Parser & Script Management](../technical/slide-parser-and-script-management.md) - How slides are structured
- [Google Slides Integration](../technical/google-slides-integration.md) - OAuth2 flow, encryption, the Drive conversion
- [Export Fidelity Harness](../technical/export-fidelity-harness.md) - Measuring the exports against the UI in PowerPoint and Google Slides

