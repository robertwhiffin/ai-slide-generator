# Export fidelity: snapshot-then-emit for PPTX and Google Slides

**Branch:** `export-enhance` · **Status:** design, awaiting owner review

## 1. Goal

What a user sees on a slide in the Tellr UI is what they get in the exported PowerPoint
file and in Google Slides: same positions, same line breaks, same typography, same
shapes, nothing overlapping that does not overlap on screen, nothing missing, nothing
extra. Everything stays **editable**: text is real text, shapes are real shapes, tables
are real tables. Pixels are used only for what PowerPoint and Slides cannot represent
natively (SVG charts, canvases, unusual gradients, filters).

### What the owner said, and what is assumed

| Said by the owner | Assumed (open to correction) |
|---|---|
| Exports must be 1:1 with the UI, for PPTX and Google Slides | "1:1" is judged visually at slide scale, not pixel-identical antialiasing |
| Everything must be editable after export | A chart may stay a picture; its title, legend and surrounding text are editable |
| Cover every broken pattern, not only the reported examples | The design-system templates and a finance corpus are a representative sample |
| huashu is the live engine; work only on `export-enhance`; no PR to `main` until asked | The records fallback (`/from-records`, used only when huashu is unavailable) is unchanged |
| Deploy a dev build to the FEVM dev workspace via the repo's dev skill and keep it ≥ 1 week | — |

### Success criteria

1. Every defect class in §3 has a fixture slide in `tests/fixtures/export_fidelity/` and a
   test that fails on today's code and passes after the change.
2. On the two harness corpora (16 finance slides in-repo; 27 design-system templates
   locally), the Google Slides render shows none of the §3 defects on visual review, and
   the per-slide difference score (`scripts/export_fidelity/run.py`) does not regress on
   any slide versus the baseline.
3. The existing 134 sidecar tests pass, except where a test pins an internal that this
   design deliberately removes; each such test is ported to assert the same user-visible
   contract (listed in §8).
4. A real deck generated on the dev app exports to PPTX and Google Slides with the §3
   defects absent, verified by the owner by hand.

## 2. How export works today

`POST /api/export/pptx/editable/huashu/from-html` and `/google-slides/from-huashu` build
one HTML document per slide (`build_slide_html`), and `build_pptx_huashu` pipes them to
`services/pptx-emit-huashu/emit_deck.mjs`. Per slide, `html2pptx.js` (vendored from
huashu-design) opens the page in Playwright Chromium, runs `preprocess.mjs` (a series of
DOM **mutations**: wrap inline text in `<p>`, flatten tables into absolute `<div>`s,
rasterize SVGs, pull badges out of text, …), then walks the **mutated** DOM
(`extractSlideData`) and emits pptxgenjs shapes. Google Slides is that same `.pptx`
uploaded to Drive and converted.

## 3. Root causes (measured)

Evidence comes from the owner's 15-slide export, from `scripts/export_fidelity/run.py` on
both corpora (browser truth vs. Google Slides vs. LibreOffice), and from probe decks
converted through Drive.

| # | Root cause | Where | Observed symptoms |
|---|---|---|---|
| RC1 | **Measure-after-mutate.** Preprocess passes change layout (`display:none` on tables, new `<p>`s, inline-block wrappers, block `<img>`s), then later passes and the walker read the reflowed layout, not what the user saw | `preprocess.mjs` (all passes), walker | Table caption jumps above the table; two side-by-side tables stacked on one another; a `flex:1` callout balloons over the table beside it |
| RC2 | **Flex/grid items merged into one paragraph.** `wrapInlineRunsIn` wraps every contiguous inline child of a `div` in one `<p>`, but each flex/grid child is its own box | `preprocess.mjs::wrapInlineRunsIn` | Footer logo drawn over text and page number glued on ("review12 / 15"); legends, agenda "01The lakehouse", KPI/stat labels, Gantt "Q1Q2Q3Q4", progress "automation80%" run together |
| RC3 | **Case-sensitive tag check.** `svg.tagName` is lowercase `svg`, so `BLOCK_TAGS.has('SVG')` misses; the SVG is wrapped in a `<p>` and the walker emits its `<text>` content with raw source whitespace | `preprocess.mjs::isInlineNode` | Stray "905 968 1,042…" text columns on every SVG chart |
| RC4 | **SVG raster loses document CSS.** Inline SVGs are serialized standalone, so class/var-based `fill`/`stroke`/`font-*` and webfonts do not apply; CSS `filter` on `<img>` is ignored | `rasterizeInlineSvgs`, image emit | Black bars, filled black polylines, serif chart labels, missing gridlines and legend swatches; white-on-navy logos turn dark |
| RC5 | **Text boxes sized to the exact browser width**, and Drive ignores `wrap="none"` (probe: still wraps). Weight 600 is emitted as `bold` (700, wider). `valign: middle` makes an extra wrapped line grow upward | walker + `addElements` | "Q1 / 2025", "Start growth / capex", "Thank / you", titles colliding with eyebrows, chip text on two lines |
| RC6 | **Exact line spacing** (`spcPts`) is converted by Drive to a percentage of the font's natural line height (probe: 22.5 pt on 13.5 pt → 166%, i.e. ≈2.0× font size instead of 1.67×) | `addElements` (`lineSpacing`) | Every multi-line title/paragraph taller in Slides, pushing into the content below |
| RC7 | **Typography dropped.** No `charSpacing`; weights collapsed to bold/not; element-level bold/italic lost whenever the element contains any inline tag; run-level `font-family` not emitted; `<sup>/<sub>/<code>/<a>/<small>/<mark>` text dropped or unstyled; text opacity/alpha ignored (Drive drops text transparency — probe); `background-clip:text` text invisible | `parseInlineFormatting`, walker | Eyebrow tracking lost everywhere; `<br>` titles render regular weight; mono numerals turn sans; footnote markers vanish; faded text full-strength; gradient headline words invisible |
| RC8 | **Visuals the walker cannot see.** `::before/::after` content; gradients on non-root elements; conic gradients; empty inline swatches; `border-radius:50%` emitted as a 1-inch rounded rect; table radius/shadow; `blockquote` borders; `list-style:none` ignored; `<ol>` rendered as bullets | walker (DIV-only shapes, list handler) | Square bullets, accent bars, timeline/journey dots gone; progress fills empty; Harvey balls gone (finance deck and the DS comparison template); circles become squircles |
| RC9 | **Table flattening copies only some cell styles** (no weight, italic, letter-spacing, line-height, vertical-align) and appends cell `div`s at the end of `body` | `flattenTables` | Bold headers and row labels lost; cells paint above later content |
| RC10 | **Visibility not honoured.** Walker ignores `visibility`, `opacity:0`, `clip`/visually-hidden patterns | walker | Screen-reader-only tables exported as visible text |
| RC11 | **Paint order = DOM order**, not CSS stacking order (z-index, positioned elements) | walker | Flattened cells and pills drawn over callouts; decorative layers in front of text |
| RC12 | **Rotated text** box comes from the rotated rect with wrapping on | walker | Vertical "GOVERNED DATA" wraps letter by letter |
| RC13 | **Inline badges pulled out of their sentence** and re-centred in the ancestor | `emitInlineBackgrounds` | Code chip jumps above its line leaving a gap ("with  now 31%") |

RC5 (wrap), RC6 and the transparency half of RC7 are specific to Google's PPTX import;
every other cause hits both PPTX and Google Slides.

### Google import constraints (probe decks, 2026-11-16)

| Construct | Survives Drive import? | Consequence for the emitter |
|---|---|---|
| `wrap="none"` | **No** — text still wraps | Keep browser line breaks explicitly and give boxes width slack |
| Typeface `DM Sans SemiBold` / `DM Sans Medium` | **Yes** → weight 600 / 500 | Encode non-400/700 weights in the typeface name |
| `spc` (letter spacing) | Yes | Emit `charSpacing` |
| Exact line spacing `spcPts` | Converted to % of natural line height | Emit percentage spacing relative to the font's natural line height |
| Text `alpha` | **No** | Pre-blend text colour against its backdrop |
| Fill transparency | Yes | Keep fill transparency |
| `ellipse` preset | Yes | Use for circles |
| Superscript run | Yes | Use `superscript`/`subscript` run options |
| Native `<a:tbl>` | Yes: geometry, fills, margins, weights, alignment exact; per-cell borders partly lost | Use native tables; emit borders per cell explicitly and verify (§5.5) |

## 4. Approaches considered

- **A. Patch each defect in place.** Fastest first fixes, but RC1, RC2 and RC11 are
  structural: every mutating pass would need its own layout-invariance guarantee. The
  repo history already holds ~20 targeted export fixes on this pipeline.
- **B. Snapshot-then-emit (chosen).** Read the untouched rendered page once, produce a
  geometry-exact slide model, emit it with Google-safe choices. Removes RC1/RC2/RC11 as
  a class and gives every other cause a single place to be fixed.
- **C. Slide image with a text overlay.** Visually exact but shapes are not editable and
  files are large. Rejected: the owner requires editability.

### 4.1 Prior art: upstream huashu-design (the "Claude Design path")

The pipeline Tellr vendors is `alchaincyf/huashu-design`'s `html2pptx.js`. Its own
`references/editable-pptx.md` says it must only run on HTML written to its four hard
rules, and it warns: *never run html2pptx on freely-written visual HTML — measured pass
rate < 30%*. Tellr's slides are free-form LLM output, so today's export runs that path
outside its design envelope. The preprocess passes were an attempt to force arbitrary
HTML into the four rules, and RC1–RC3 and RC13 are that attempt's side effects.

Upstream's answer for existing visual HTML is a separate exporter,
`references/pptx-from-rendered-html.md` / `scripts/pptx_from_rendered.py`. It reads the
browser's **rendered coordinates** instead of the source, which is the principle of
approach B. Its documented pitfalls are adopted here:

| Upstream lesson | Where it lands in this design |
|---|---|
| Collapse source whitespace exactly as the browser does; drop runs that are empty after collapse | §5.3 Text |
| A container's font-size is often inherited; base metrics on the largest run in the block | §5.3 Text |
| Count lines by clustering rects whose y-ranges overlap, never by de-duplicating `top` | §5.3 Text |
| PowerPoint line spacing is per paragraph: lines of different size in one box overlap | §5.3 Text (new paragraph on size change) |
| Flex shrink-wrapped boxes have zero slack and lose their last word: single-line text gets no-wrap | §5.3 Text (no-wrap **and** slack, because Drive ignores no-wrap) |
| Single-line paragraphs must not get exact spacing | §5.3 Text |
| Charts and SVG become pictures: hundreds of rectangles are less editable than one image | §5.4, §6.3 |
| Verify the verifier: `qlmanage` hid four overlap bugs; LibreOffice drops fonts it cannot find; check text loss against `innerText`, an oracle independent of the extractor | §8 |
| Delivery font name ≠ layout font: keep the deck's CSS family names in the file | §5.5 |

Not adopted: upstream's template inheritance (building on a client `.pptx` master with
python-pptx). It needs the brand's `.pptx` master in the design system and a python-pptx
emitter. It does not change 1:1 fidelity, so it is outside this spec.

## 5. Design

### 5.1 Pipeline

```
build_slide_html ─▶ emit_deck.mjs ─▶ html2pptx.js (per slide)
                                       1. load + settle (unchanged: networkidle, fonts, canvas wait)
                                       2. preprocess.mjs  — layout-neutral only (5.2)
                                       3. snapshot.mjs    — read-only extraction → SlideModel (5.3)
                                       4. raster capture  — element-isolated screenshots (5.4)
                                       5. emit_model.cjs  — SlideModel → pptxgenjs (5.5)
```

Interfaces that stay exactly as they are: the routes, `build_slide_html`,
`build_pptx_huashu` and its `(bytes, failures)` contract, the stdin/stderr protocol of
`emit_deck.mjs` (`__HUASHU_RESULT__`), `bypassValidation`, `[preprocess]`/`[html2pptx]`
stderr routing, and the SDR-4437 rules (images embedded from `data:` only; sidecar env
allowlist).

### 5.2 Preprocess becomes layout-neutral

Kept: `transferSlideRootBackground` and its `bgTransferred` result contract (pinned by the
slide-root tests), with the pristine-realm accessors and bounded iteration unchanged.

Added: **pseudo-element materialization.** Every `::before`/`::after` whose `content` is
not `none` is replaced by a real `<span data-tellr-pseudo>` carrying the pseudo-element's
full computed style, and the original pseudo is suppressed by one injected rule scoped to
a marker attribute. Because the span has the same computed style in the same position,
layout is unchanged; this is **verified, not assumed**: rects of every element are
recorded before and compared after, and any element that moved by more than 0.5 px
reverts the materialization for that slide and logs `[preprocess] pseudo materialization
moved layout; reverted`.

Removed: `flattenMonospaceCodeBlocks`, `wrapBareTextInDivs`, `replaceBackgroundImageWithImg`,
`rasterizeSvgDataUriImages`, `rasterizeInlineSvgs`, `peelBackgroundsOffTextTags`,
`flattenTables`, `rasterizeCanvases`, `emitInlineBackgrounds`. Their jobs move into the
snapshot (read-only) and raster capture.

### 5.3 Snapshot: read-only extraction (`snapshot.mjs`)

Runs as one `page.evaluate`, reads the DOM through the same pristine-realm accessors and
bounded collections as today (hostile slide script must still neither hang nor blind the
export). It mutates nothing except `data-tellr-*` marker attributes used to address
raster targets.

**Visibility.** An element is skipped when `display:none`, `visibility:hidden`,
cumulative opacity 0, zero area, entirely outside the slide, or clipped to under 2 px by
`clip`/`clip-path`/an `overflow` ancestor (the visually-hidden pattern).

**Paint order.** Items are ordered by CSS painting order: per stacking context, the
context's own background, negative z-index children, in-flow blocks, floats, inline
content, positioned `z-index:auto/0` in DOM order, then positive z-index. Every item
carries its resolved order key, so emission order equals screen stacking.

**Boxes.** For each painted element: background colour (alpha kept as fill
transparency), each border side (uniform → shape outline; non-uniform → one line per
side, preserving `dashed`/`dotted`), border radius (all four corners; a circle/ellipse
when radius ≥ 50% → `ellipse`), outer box-shadow, and cumulative opacity. Linear
gradients, conic/radial gradients, background images, `filter`, `mix-blend-mode`,
`clip-path` and masks are routed to raster capture as a **box-only** raster (text is
captured separately and stays editable).

**Text.** Text is grouped into *text blocks*: the nearest block container, flex item,
grid item, table cell or list item. Each block becomes one text box.
- Geometry comes from `Range.getClientRects()` of its text, not the element box, so a
  logo or an inline image beside the text can never overlap it.
- **Visual lines** are found by clustering fragment rects whose vertical ranges overlap,
  never by de-duplicating `top`, because mixed-size runs on one line return rects with
  different tops.
- Source whitespace is collapsed the way the browser collapses it (`white-space`-aware),
  and runs that are empty after collapse are dropped.
- **Line breaks are the browser's.** Lines of the same size end in a soft break inside one
  paragraph. A line whose largest run differs in size or line-height starts a new
  paragraph with its own spacing, because PowerPoint spacing is per paragraph. Slides and
  PowerPoint therefore show exactly the UI's lines (owner decision, §6.1).
- Block metrics (line spacing, slack, first-line offset) use the **largest** run in the
  block, never the container's inherited font-size.
- A block that is a single line in the browser gets `wrap="none"` (honoured by
  PowerPoint) and natural line spacing.
- Every box gets width slack: 6% + 4 px, extended in the direction its alignment allows.
  Drive ignores `wrap="none"`, so the slack is what stops a slightly wider substitute
  rendering from wrapping a line again.
- Runs carry: family (first face in the stack the document actually loaded), weight,
  italic, size, colour pre-blended against the resolved backdrop for any alpha/opacity,
  letter-spacing, text-transform, underline/strike, super/subscript, and white-space
  (pre/nbsp preserved).
- `background-clip:text` falls back to the gradient's mid stop as solid text colour.
- Vertical anchor is `top`, with the first line placed from its measured line box.
- Multi-line spacing is a multiple of the font's natural line height, which is measured
  in-page with a `line-height: normal` probe. A percentage is the form both PowerPoint and
  Drive honour; exact points are mis-scaled by Drive (RC6).
- The first-line offset for each spacing value is calibrated against PowerPoint and
  Google Slides renders of a probe deck during implementation, and pinned by a test.
- Inline elements with background, border or padding (pills, chips, `<mark>`, `<kbd>`)
  emit a shape at each of their per-line fragment rects, painted under the text box.
  The text stays in the sentence, so it does not jump.
- Inline atomic boxes (inline images or SVGs, `inline-block`s) that sit inside a line
  split the block into per-line segments, so the text after them keeps its exact x.

**Lists.** `list-style-type` other than `none` emits its marker (`•`, `1.`, `a.` …) as
its own text item, right-aligned to the marker position. `list-style:none` emits none.

**Rotated text.** Text under a rotation emits the unrotated box (from `offsetWidth/Height`)
plus the angle, with browser line breaks, so it does not re-wrap letter by letter.

**Replaced and graphic content.** `<img>` (data: only), `<canvas>`, `<video>` posters
and inline `<svg>` become raster targets. An `<img>` with no filter, no clipping and a
raster `data:` source is embedded directly; everything else is captured.

**Tables.** A `<table>` whose cells hold only text (any inline formatting) becomes a
native table item. It carries:
- exact column widths and row heights from the rendered cells, and `colspan`/`rowspan`;
- per-cell padding as margins, fill (cell over row over table), per-side borders,
  vertical alignment, and runs with the same rules as text blocks;
- table radius and shadow, as a shape under the table.

A cell holding non-text content (an image, SVG, Harvey ball, nested table or block
layout) keeps the native table. Only that content is overlaid as its own items at its
measured rect. Exception: a table with a nested table becomes positioned items, for
exactness.

### 5.4 Raster capture (element-isolated screenshots)

Every raster target is captured from the **original, untouched page**: Playwright
temporarily applies an isolation stylesheet that makes every element `visibility:hidden`
except the target subtree. Visibility does not affect layout. It screenshots the
target's rect at device scale 2 with a transparent background. Box-only rasters also set
the target's text to transparent.

This captures exactly what the browser paints, with the deck's CSS, webfonts, CSS
variables, filters and clipping applied. It fixes RC4 and the conic/radial/gradient and
filter cases of RC8, and works for tainted canvases too. The isolation stylesheet is
removed after each capture. Capture failure for one target logs and skips that target;
it never drops the slide.

### 5.5 Emitter (`emit_model.cjs`)

Maps the model to pptxgenjs with the choices that survive both PowerPoint and Drive:
- **Weights:** 400 → `Family`, 700 → `Family` + bold, other weights → `Family <Weight
  name>` (`Medium`, `SemiBold`, `ExtraBold`, `Light`, …).
- **Text spacing:** `charSpacing` in points; `lineSpacingMultiple`; zero insets; soft
  breaks per browser line; `valign: top`.
- **Shapes:** `ellipse` for circles, `roundRect` with per-shape radius, per-side lines,
  fill transparency, outer shadow.
- **Tables:** `addTable` with explicit `colW`/`rowH`, margins and per-cell borders, all
  four sides written on every cell, so adjacent cells agree and Drive keeps them.
- **Images:** placed with the stacking order preserved.
- **Font names:** the deck's CSS family names are written into the file, not the
  browser's fallback. Machines and Slides that have the brand font render it.

The old `addElements`/`extractSlideData` code in `html2pptx.js` is deleted, not left
beside the new path.

### 5.6 Validation and diagnostics

The huashu design-rule validations keep their current behaviour under
`bypassValidation` (warn instead of throw). Each slide logs one `[html2pptx]` summary
line on stderr: item counts per kind, rasters captured, rasters failed, and whether the
pseudo materialization reverted. A slide can then be explained from the app log alone.

## 6. Decisions

### 6.1 Line breaks: keep the UI's lines

Every browser line ends where the UI ends it: a soft break between lines of one size, a
new paragraph where the size changes (§5.3). The export therefore shows the UI's lines
exactly. The trade-off is that editing a paragraph afterwards keeps those breaks;
PowerPoint and Slides will not re-flow it until the user removes them. The alternative (no breaks, wider boxes)
reflows naturally but cannot guarantee the same lines, because Drive's text measurement
differs slightly. **Default chosen: keep UI lines** — the owner's priority is 1:1. Owner
may overturn this at spec review.

### 6.2 Tables: native, editable tables

Native tables are editable as tables in both apps and the probe showed Drive keeps their
geometry exactly (§3). Cell graphics overlay the table rather than forcing the whole table
into loose boxes.

### 6.3 Charts: high-resolution pictures; the text around them stays editable

SVG and Chart.js charts are exported as 2x pictures captured from the page itself. This
is the only way they look exactly as they do in the UI. It is also the choice upstream
huashu-design and Claude's own Slides export make. A chart's title, legend, source line
and callouts are HTML, so they stay editable text.

The alternative is rebuilding Chart.js charts as **native** PowerPoint charts, with data
editable through "Edit Data". That is possible because the chart config is in the deck
script, but PowerPoint's and Slides' chart engines draw axes, labels and spacing
differently from Chart.js. Native charts would therefore not be 1:1. Hand-written SVG
charts carry no recoverable data, so they cannot become native at all. **Default chosen:
pictures.** The owner may ask for native Chart.js charts at spec review, accepting that
they will not match the UI exactly.

### 6.4 Out of scope

- The inline editor revamp (separate session, own spec).
- The records fallback path (`/from-records`, `exportWalkerSource.ts`), which only runs
  when huashu is unavailable.
- Fonts that Google Slides does not host: they fall back in Slides exactly as they do
  today. DM Sans and DM Mono are hosted.

## 7. Error handling

- A raster target fails: log `[html2pptx] raster failed: <selector-ish> <reason>`, omit
  it, and keep the slide.
- The pseudo-materialization layout check fails: revert it, log, and continue. Pseudo
  content is then missing on that slide, and the log names it.
- The snapshot throws: the slide is reported in `failures` with the message. This is the
  same contract as today, so the partial-export toast still names it.
- Hostile slide script: termination is guaranteed by the bounded collection and walk
  limits carried over from today's code, and correctness by the pristine accessors.

## 8. Testing

- **Fixtures:** `tests/fixtures/export_fidelity/` (16 slides, one or more defect classes
  each) is committed. The 27 design-system templates stay local because they are brand
  assets and the repo is public.
- **Unit tests (pytest, real Chromium, gated like today's sidecar tests).** One test file
  per concern asserts on the emitted slide XML:
  - text boxes: line count, soft breaks, typeface names for weights, `spc`, percentage
    line spacing, blended colour;
  - shapes: `ellipse`, per-side lines, pseudo-element shapes;
  - paint order;
  - native table: `a:tbl`, `gridCol` widths, merged cells;
  - absence of hidden text;
  - raster targets: PNGs present, correct aspect, non-blank, chart colours sampled from
    the PNG.

  Every new test is first run against today's code and must fail (sabotage check), per
  `executing-plans-tellr`.
- **Existing suite:** all 134 sidecar tests stay green. These tests pin internals this
  design removes; each is ported to assert the same user-visible contract:
  - `test_export_svg_raster` golden PNG manifests: regenerated, with each changed entry
    justified;
  - `test_export_collection_iteration_hostile_realm` "same counts as benign twin": counts
    now come from the snapshot summary;
  - `test_export_csp` comment references to `flattenTables`: updated.
- **Harness:** `scripts/export_fidelity/run.py` is re-run on both corpora after each task
  group. The visual review and per-slide scores are recorded in the plan's progress notes.
- **Trusted renderers only.** Upstream measured that renderers disagree.
  - Google Slides thumbnails are the truth for Slides.
  - **Microsoft PowerPoint for Mac**, driven by AppleScript to export a PDF, is the truth
    for PPTX. It is installed on the dev Mac and needs DM Sans and DM Mono installed
    locally (from the design system's own `fonts/`).
  - LibreOffice is a fast smoke check only; it cannot load the brand fonts.
  - `qlmanage` thumbnails are never used.
- **Text-loss oracle independent of the extractor.** The harness and a unit test compare
  each slide's rendered `innerText` with the text in the `.pptx`, ignoring whitespace and
  case, with SVG/canvas text excluded because it travels in the picture. The sidecar also
  runs this check per slide and logs `[html2pptx] text missing: …` on stderr, so silent
  text loss is visible in the app log.
- **Count check.** Pictures, shapes, tables and text boxes per slide are reported by the
  harness, so a regression that drops a class of item shows up as a number.
- **Dev deploy:** publish a `.devN` from `export-enhance` and deploy to a dedicated
  `devloop` instance on the FEVM dev workspace. Generate fresh decks there (balance sheet,
  scorecards, charts, timelines, architecture), export both formats, and compare. The app
  is not deleted, so the owner can test by hand for at least a week.

## 9. Documentation

- Update `docs/technical/export-features.md`: replace the "table fidelity" paragraph and
  the known-limitations list.
- Add a short `docs/technical/export-fidelity-harness.md` covering how to run the harness
  and read its output.
