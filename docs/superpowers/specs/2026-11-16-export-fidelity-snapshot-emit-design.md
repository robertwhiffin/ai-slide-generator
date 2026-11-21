# Exports that match the UI: snapshot-then-emit for PPTX and Google Slides — design

Date: 2026-11-16. Status: draft for owner review. Branch: `feat/export-revamp`.

Decisions are marked **(decided)** when the owner made them and **(my call)** when the
designer made them and the owner has not yet confirmed them. Unmarked text describes the
code as it stands or what was measured.

## Intent

Users export a deck to PowerPoint or Google Slides and get something that does not look
like what they built. Text overlaps, items swap order, charts turn black, footers collide,
table captions jump, and visual pieces vanish. The owner's bar: **what I see in the Tellr
UI is what I get in the export, 1:1, and everything stays editable.** That is real text
boxes, real shapes and real tables. It is not a picture of the slide.

This rebuilds the converter core of the huashu export path so that it reads the slide the
browser rendered, instead of rewriting the HTML and measuring the rewrite. It also maps
the result onto the PowerPoint and Google Slides constructs that survive, and adds a harness
that measures fidelity against PowerPoint and Google Slides themselves.

## How export works today

- **PDF** is built in the browser: each slide is rendered in a sandboxed frame, captured as
  an image, and placed on a PDF page. It is pictures only, and it is not part of this work.
- **PowerPoint** is built on the server by the huashu path,
  `POST /api/export/pptx/editable/huashu/from-html`:
  - `build_slide_html` makes one HTML document per slide, and `build_pptx_huashu` pipes
    them to `services/pptx-emit-huashu/emit_deck.mjs`;
  - per slide, `html2pptx.js` opens the page in Chromium, runs `preprocess.mjs` (a chain of
    DOM **mutations**), walks the mutated DOM, and writes pptxgenjs shapes;
  - if huashu is unavailable, the frontend falls back to the records path
    (`/from-records`).
- **Google Slides**, `POST /api/export/google-slides/from-huashu`, builds that same `.pptx`
  and uploads it to the user's Drive with conversion to Google Slides. Drive's importer
  turns it into a native Slides deck, and Tellr returns the link. Every Google Slides
  defect is therefore either a defect in our `.pptx` or a quirk of Drive's importer, and
  this design has to handle both.
- **Fonts arrive** because Chromium loads the deck's webfonts while rendering, the family
  name is written into the file, and Google Slides hosts DM Sans and DM Mono. PowerPoint
  shows them when they are installed on the viewer's machine.

## Goals

1. The exported PowerPoint file and the Google Slides deck look like the UI: same
   positions, same line breaks, same typography (weight, tracking, line spacing,
   opacity), same shapes and stacking. Nothing overlaps that does not overlap on screen;
   nothing is missing; nothing extra appears. **(decided)**
2. Everything with a native equivalent stays native and editable: text, boxes, borders,
   circles, lines, tables, list markers, CSS-drawn bullets and dots. Only what has no
   native equivalent becomes a picture: SVG and Chart.js charts, canvases, conic and
   radial gradients, filters. **(decided)**
3. Every defect class found in the investigation has a fixture slide and a test that
   fails on today's code and passes after the change.
4. Fidelity is measured against **PowerPoint for Mac** and **Google Slides**, the
   applications users open. Neither is approximated by another renderer.
5. Silent text loss becomes visible, in the harness and in the app log.

## Non-goals

- The inline editor revamp. **(decided: separate session, own spec)**
- PDF export.
- The records fallback (`/from-records`, `exportWalkerSource.ts`), which only runs when
  huashu is unavailable.
- Inheriting a brand's `.pptx` master and layouts (see *Prior art*).
- Fonts Google Slides does not host. They fall back in Slides exactly as they do today.

## Anti-goals (a failure even if it technically works)

- A slide that looks right but is one picture, or whose text is not editable.
- A fix that makes one corpus slide right and moves another; every harness run is
  compared slide by slide against the baseline.
- Text that disappears without a log line saying so.
- Weakening the existing hardening: hostile slide script must still neither hang the
  export nor blind it, images stay `data:`-only, and the sidecar keeps its env allowlist.

## Root causes (measured)

Evidence came from four sources:

- the owner's 15-slide export (Google Slides JSON and thumbnails);
- `scripts/export_fidelity/run.py` on two corpora: 17 in-repo finance slides and the 27
  design-system templates (local only), each rendered as browser truth and as the real
  export opened in PowerPoint and in Google Slides;
- probe decks converted through Drive;
- a reading of the code.

| # | Root cause | Where | What the user sees |
|---|---|---|---|
| RC1 | **Measure-after-mutate.** Preprocess passes change layout (`display:none` on tables, new `<p>`s, inline-block wrappers, block `<img>`s). Later passes and the walker then read the reflowed layout, not what the user saw | `preprocess.mjs` (all passes), walker | Table caption jumps above the table; two side-by-side tables stacked on one another; a `flex:1` callout balloons over the table beside it |
| RC2 | **Flex and grid items merged into one paragraph.** `wrapInlineRunsIn` wraps every run of inline children of a `div` in one `<p>`, but each flex or grid child is its own box | `preprocess.mjs::wrapInlineRunsIn` | Footer logo drawn over the text and page number glued on ("review12 / 15"); legends, agenda "01The lakehouse", KPI and stat labels, Gantt "Q1Q2Q3Q4" and progress "automation80%" run together |
| RC3 | **Case-sensitive tag check.** `svg.tagName` is lowercase, so `BLOCK_TAGS.has('SVG')` misses it. The SVG is wrapped in a `<p>`, and its `<text>` content is emitted with raw source whitespace | `preprocess.mjs::isInlineNode` | Stray "905 968 1,042…" text columns on every SVG chart |
| RC4 | **SVG raster loses document CSS.** SVGs are serialized standalone, so class- and variable-based `fill`, `stroke`, `font-*` and webfonts are lost. A CSS `filter` on `<img>` is ignored | `rasterizeInlineSvgs`, image emit | Black bars, filled black polylines, serif chart labels, missing gridlines and swatches; white-on-navy logos turn dark |
| RC5 | **Text boxes sized to the exact browser width.** Drive ignores `wrap="none"` (probe). Weight 600 is written as bold (700, wider). `valign: middle` grows an extra wrapped line upward | walker + `addElements` | "Q1 / 2025", "Start growth / capex", "Thank / you", titles colliding with eyebrows, two-line chips; the same titles wrap in PowerPoint too |
| RC6 | **Exact line spacing.** Drive converts `spcPts` to a percentage of the font's natural line height (probe: 22.5 pt on 13.5 pt becomes 166%, about 2.0× the font size instead of 1.67×) | `addElements` | Multi-line titles and paragraphs taller in Slides, pushing into content below |
| RC7 | **Typography dropped.** No letter spacing; weights collapsed to bold or not; element-level bold and italic lost when the element contains any inline tag; run-level font family not written; `<sup>`, `<sub>`, `<code>`, `<a>`, `<small>`, `<mark>` text dropped or unstyled; opacity on text ignored (and Drive drops text alpha, probe); `background-clip:text` text invisible | `parseInlineFormatting`, walker | Eyebrow tracking lost everywhere; `<br>` titles in regular weight; mono numerals turn sans; footnote markers vanish (caught by the text-loss check); faded text at full strength in both apps; gradient headline words invisible |
| RC8 | **Visuals the walker cannot see.** `::before` and `::after` content; gradients on non-root elements; conic gradients; empty inline swatches; `border-radius:50%` written as a 1-inch rounded rectangle; table radius and shadow; `blockquote` borders; `list-style:none` ignored; `<ol>` turned into bullets; canvases drawn by slide script | walker (shapes from `div` only, list handler), `rasterizeCanvases` | Square bullets, accent bars, timeline and journey dots gone; progress fills empty; Harvey balls gone (finance deck and the design system's own comparison template); circles become squircles; a script-drawn canvas missing |
| RC9 | **Table flattening copies only some cell styles** (no weight, italic, letter spacing, line height or vertical alignment) and appends cell `div`s at the end of `body` | `flattenTables` | Bold headers and row labels lost; cells paint above later content |
| RC10 | **Visibility not honoured.** `visibility`, `opacity:0`, `clip` and the visually-hidden pattern are ignored | walker | Screen-reader-only tables exported as visible text |
| RC11 | **Paint order follows the DOM,** not CSS stacking (z-index, positioned elements) | walker | Cells and pills drawn over callouts; decorative layers in front of text |
| RC12 | **Rotated text** gets its box from the rotated rect with wrapping on | walker | Vertical "GOVERNED DATA" wraps letter by letter |
| RC13 | **Inline badges pulled out of their sentence** and re-centred in the ancestor | `emitInlineBackgrounds` | A code chip jumps above its line and leaves a gap ("with  now 31%"); icons float above their labels |

RC5's wrapping, RC6, and the text-alpha half of RC7 come from Drive's importer. Every other
cause hits PowerPoint and Google Slides alike.

### What Drive's importer keeps (probe decks, 2026-11-16)

| Construct | Kept? | Consequence |
|---|---|---|
| `wrap="none"` | **No**, text still wraps | Keep browser line breaks explicitly and give boxes width slack |
| Typeface `DM Sans SemiBold` / `DM Sans Medium` | **Yes**, as weight 600 / 500 | Write non-400/700 weights into the typeface name. The static DM Sans fonts carry these legacy family names (name ID 1), so PowerPoint resolves them too |
| `spc` (letter spacing) | Yes | Write `charSpacing` |
| Exact line spacing (`spcPts`) | Converted to % of the natural line height | Write percentage spacing, of the renderers' single spacing (1.2 × the font size, as built: see §3 Spacing) |
| Text alpha | **No** | Pre-blend text colour against its backdrop |
| Fill transparency | Yes | Keep fill transparency |
| `ellipse` preset | Yes | Use it for circles |
| Superscript run | Yes | Use superscript and subscript run options |
| Native table (`a:tbl`) | Yes: geometry, fills, margins, weights, alignment and per-cell borders. The two borders missing in the probe were edges the probe wrote on one cell only, against a neighbour's `noFill`. Written on both cells, every collapsed edge survives: converted through Drive, the balance-sheet fixture's total-row lines and a collapse test deck's edges are the browser's colour (and width) in every column (`test_export_snapshot_tables.py`, opt-in Google test) | Use native tables; resolve shared edges the way CSS collapses borders and write the winner on **both** cells |

## Prior art: huashu-design upstream

Tellr's export path vendors `alchaincyf/huashu-design` (MIT, about 29.6k stars; see
https://github.com/alchaincyf/huashu-design). The commit history and issues show the
author met the same problems and moved on from the code Tellr vendored:

| Date | Upstream change | Link |
|---|---|---|
| 2026-04-19 | v1.0 with `scripts/html2pptx.js` (the four-rule path) | commit `7d7bab4a82` |
| 2026-04-24 | Community PR: element bold/italic lost when a title contains `<br>`. This is our RC7; it was closed unmerged during a cleanup | https://github.com/alchaincyf/huashu-design/pull/10 |
| 2026-05-08 | **Tellr vendors `html2pptx.js`** (commit `d8b612c6` here) | — |
| 2026-09-15 | New third path: `scripts/pptx_from_rendered.py` and `references/pptx-from-rendered-html.md`. It reads the browser's rendered coordinates, so visual HTML needs no rewriting | https://github.com/alchaincyf/huashu-design/commit/c4b83675d1 |
| 2026-09-22 | `html2pptx.js` removed ("based on Anthropic pptx skill") and replaced by a clean-room rewrite | https://github.com/alchaincyf/huashu-design/commit/65942f7d50, https://github.com/alchaincyf/huashu-design/commit/3112c47123 |
| 2026-09-30 | Issue: bare text beside an `<svg>` or block child silently dropped; the text check missed it | https://github.com/alchaincyf/huashu-design/issues/56 |
| 2026-10-30 | Text verification also covers missing slides (v3.1.0) | https://github.com/alchaincyf/huashu-design/pull/59 |
| 2026-11-10 | SVG and canvas indices tracked separately; hidden SVG regression tests (v3.3.0, the latest) | https://github.com/alchaincyf/huashu-design/pull/61, https://github.com/alchaincyf/huashu-design/releases/tag/v3.3.0 |

What the author says, and what we take from it:

- **The four-rule path is the wrong tool for Tellr's HTML.** `references/editable-pptx.md`
  says: *never run html2pptx on freely-written visual HTML — measured pass rate < 30%.*
  Tellr's slides are free-form model output. The preprocess passes were an attempt to force
  them into the four rules, and RC1–RC3 and RC13 are that attempt's side effects.
- **Reading rendered coordinates is the right path** for existing visual HTML. That is the
  principle of this design, and it is what the author built for his own users two months
  ago.
- **Everything in his rendered-coordinates exporter that applies to Tellr is adopted**,
  item by item below. Where Tellr needs more (native tables, Google Slides, CSS-drawn
  visuals, hostile slide script), the design extends it. Each item lands in *Design* and
  is covered by a fixture or test.

#### Upstream item by item

| Upstream technique or fix (source) | In this design | Where |
|---|---|---|
| Read the browser's rendered rects, not the source (`pptx_from_rendered.py`) | **Adopted**, the core of approach B | §3 |
| Collapse source whitespace as the browser does; drop empty runs (pitfall 1) | **Adopted**, `white-space`-aware | §3 Text |
| Apply `text-transform` to run text | **Adopted** | §3 Text |
| Run style: size, bold ≥ 600, italic, underline, colour, letter spacing as `spc` | **Adopted and extended**: real 100–900 weights via typeface names, strike-through, super/subscript, per-run family | §3, §5 |
| Base metrics on the largest run (pitfall 2) | **Adopted** | §3 Text |
| Count lines by overlapping y-ranges (pitfall 3) | **Adopted** | §3 Text |
| Mixed sizes: one box per `<br>` segment so spacing cannot collide (pitfall 4) | **Adopted, refined**: a new paragraph inside one box on size change, giving the same spacing guarantee with fewer boxes to edit | §3 Text |
| Single-line text gets no-wrap plus padding (pitfall 5) | **Adopted and extended**: also explicit width slack, because Drive ignores no-wrap; multi-line text keeps the UI's breaks | §3 Text |
| No exact spacing on single lines (pitfall 6) | **Adopted** | §3 Text |
| Multi-line spacing as exact points from the measured line box | **Replaced** by percentage spacing, because Drive mis-scales exact points (RC6). PowerPoint honours both | §3, §5 |
| Centred and right-aligned text uses the container width; bare text uses its own bounds | **Adopted** | §3 Text |
| Walk child nodes so bare text beside an `<svg>` or block child is kept (issue #56) | **Adopted**, plus a fixture built from his repro | §3, fixture 17 |
| Opacity multiplied down the ancestor chain, written as alpha | **Adopted and extended**: fills keep transparency; text colour is pre-blended, because Drive drops text alpha | §3, §5 |
| Shapes: background, uniform border, radius as `min(0.5, r / min(w, h))`, opacity | **Adopted and extended**: per-side borders, dashed and dotted, `ellipse` for circles, outer shadow | §3, §5 |
| Empty inline decorations (highlight bars, strikes) as their own shapes | **Adopted and extended** to pills and chips, per line fragment | §3 Text |
| Rotation of decorative shapes from the transform matrix | **Adopted**, also for text (unrotated box plus angle) | §3 |
| Picture corners baked into PNG alpha | **Adopted**: isolated capture bakes radius and clipping in | §4 |
| `box-shadow: 0 0 0 Npx` drawn as a picture border | **Adopted** for pictures and shapes: a spread-only shadow becomes an outline | §3 Boxes |
| SVG and canvas as screenshots, not hundreds of shapes | **Adopted and improved**: isolation (nothing overlapping is baked in), device scale 2, transparent background | §4 |
| SVG and canvas indices tracked separately; hidden SVG regression (PR #61) | **Bug class removed**: targets are addressed by marker attribute, not index. His regression cases are fixtures | §3, fixture 17 |
| Text-loss check against rendered `innerText`, SVG and canvas excluded (#56) | **Adopted** in the harness and as an in-pipeline log line | §6, harness |
| Missing slides count as missing text (PR #59) | **Adopted**: an expected slide that is absent reports all its text as missing | §6, harness |
| Trusted renderers only: PowerPoint, Keynote or WPS yes; Quick Look no; LibreOffice drops fonts | **Adopted**: PowerPoint for Mac and Google Slides are the truth | §8 |
| Delivery font ≠ layout font; write the East Asian (`a:ea`) and complex-script (`a:cs`) typefaces too | **Adopted**: the CSS family goes into latin, ea and cs, so CJK and RTL text keep the face | §5 |
| Single-weight fonts (e.g. Impact) are never bolded (clean-room `html2pptx.js`) | **Adopted** | §5 |
| Build on a client `.pptx` master: strip sample slides, unblock the layout, skip the logo (`--template`) | **Not adopted**: needs a brand master per design system and a python-pptx emitter, and does not change 1:1 fidelity | Non-goals |
| `data-pptx-merge` hint (clean-room path) | **Not applicable**: an authoring hint for hand-written HTML. Tellr's HTML is generated, and §3's block grouping already gives one box per text block | — |
| Four-rule validations (overflow, bottom margin) | **Kept as today**: warnings under `bypassValidation` | §6 |

#### What this design adds beyond upstream

- **Google Slides:** percentage spacing, typeface-encoded weights, pre-blended text colour,
  and width slack. Upstream has no Google Slides export.
- **Native, editable tables:** upstream emits loose text boxes.
- **CSS-drawn visuals:** `::before`/`::after`, and gradients, conic gradients, filters and
  blend modes captured as box-only pictures.
- **Layout fidelity:** CSS stacking order; clipped and visually-hidden content skipped;
  list markers as the browser numbers them.
- **Kept from Tellr's hardening:** the hostile-realm protections, `data:`-only images, the
  slide-root background, per-slide failure reporting and stderr diagnostics. Upstream
  needs none of these.

**Code provenance.** Tellr's `services/pptx-emit-huashu/html2pptx.js` is the pre-rewrite
file that upstream removed as based on Anthropic's pptx skill. It carries no licence
header and ships in this public repo and the PyPI wheel. This design deletes it: the
extraction, emission and validation code is replaced, and the remaining orchestration is
rewritten. No vendored code is carried over, and no upstream code is copied; techniques
are reimplemented and credited in comments. Whether a historical clean-up is needed is
the owner's call and outside this spec.

## Approaches considered

- **A. Patch each defect in place.** Fastest first fixes, but RC1, RC2 and RC11 are
  structural: every mutating pass would need its own layout guarantee. The repo history
  already holds about 20 targeted fixes on this pipeline.
- **B. Snapshot-then-emit.** Read the untouched rendered page once, produce a
  geometry-exact slide model, and write it with constructs PowerPoint and Drive both keep.
  This removes RC1, RC2 and RC11 as a class and gives every other cause one place to be
  fixed. **(decided)**
- **C. A picture of each slide with a text layer.** Visually exact, but shapes are not
  editable and files are large. Rejected on editability. **(decided)**

## Decisions made with the owner

- Approach B. **(decided)**
- Everything that can be native stays native and editable; only what PowerPoint and Slides
  cannot represent becomes a picture. **(decided)**
- Charts are high-resolution pictures taken from the slide, with their titles, legends and
  labels as editable text. **(decided)**
- All work happens on `feat/export-revamp`: commits and pushes there, nothing on `main`, and no
  PR until the owner asks. **(decided)**
- The owner reviews this spec and then the plan before implementation. After that, the work
  runs autonomously through implementation, tests and the dev deploy. **(decided)**
- The dev build is deployed with the repo's `deploy-tellr-dev` skill to a `devloop`
  instance on the FEVM dev workspace, and kept for at least 2 months from its deploy date.
  **(decided)**
- DM Sans and DM Mono are installed on the dev Mac, and the harness may drive PowerPoint.
  **(decided)**

## Design

### 1. Pipeline

```
build_slide_html ─▶ emit_deck.mjs ─▶ render_slide.cjs (per slide)
                                       1. load + settle (networkidle, every font face loaded,
                                          canvas wait, animations finished)
                                       2. preprocess.mjs   layout-neutral only (§2)
                                       3. pseudo.mjs       ::before/::after/::marker via CDP (§2)
                                          snapshot.mjs     read-only extraction → slide model (§3),
                                          model_check.cjs  validated in Node (§3)
                                       4. capture          element-isolated screenshots (§4)
                                       5. emit_model.cjs   slide model → pptxgenjs (§5),
                                                           for the renderer target (§3)
                                       6. checks           text-loss + summary line (§6)
```

`render_slide.cjs` replaces `html2pptx.js`. Interfaces that stay exactly as they are:

- the routes, `build_slide_html`, and `build_pptx_huashu` with its `(bytes, failures)`
  contract;
- `emit_deck.mjs`'s stdin and stderr protocol (`__HUASHU_RESULT__`) and `bypassValidation`;
- `[preprocess]` and `[html2pptx]` lines routed to stderr;
- the SDR-4437 rules: images embedded from `data:` only, and the sidecar env allowlist.

### 2. Preprocess becomes layout-neutral

Kept: `transferSlideRootBackground` and its `bgTransferred` result, the pristine-realm
accessors, and bounded iteration. All of these are pinned by the slide-root and
hostile-realm tests.

**Pseudo-elements are read, not materialized** (as built). Inserting a span for each
`::before` and `::after` shifts structural selectors (`:nth-child`, `:first-child`), which
restyled real decks, so nothing is inserted. `pseudo.mjs` reads every `::before`,
`::after` and list `::marker` from Node through the Chrome DevTools Protocol, read-only:
its box (`DOM.getBoxModel`), its rendered text, counters included, from the layout
(`DOMSnapshot`), and its computed style. Hosts are tied to page elements by a
layout-neutral marker attribute. A pseudo-element's items take its host's paint order:
`::before` as the host's first child, `::after` as its last. One that needs a picture (a
gradient, an image) is captured by isolating `[host]::before` or `::after`.

Removed:
- `flattenMonospaceCodeBlocks`, `wrapBareTextInDivs`, `replaceBackgroundImageWithImg`;
- `rasterizeSvgDataUriImages`, `rasterizeInlineSvgs`, `rasterizeCanvases`;
- `peelBackgroundsOffTextTags`, `flattenTables`, `emitInlineBackgrounds`.

Their jobs move to the snapshot and the capture.

### 3. Snapshot: read-only extraction (`snapshot.mjs`)

One `page.evaluate`, reading the DOM through the same pristine-realm accessors and
bounded collections as today. It changes nothing except `data-tellr-*` marker attributes,
which address capture targets.

**Visibility.** An element is skipped when any of these holds:
- `display:none` or `visibility:hidden`;
- cumulative opacity 0;
- zero area, or entirely outside the slide;
- clipped to under 2 px by `clip`, `clip-path` or an `overflow` ancestor (the
  visually-hidden pattern).

**Paint order.** Items follow CSS painting order. Within each stacking context the order
is:
1. the context's own background;
2. negative z-index children;
3. in-flow blocks;
4. floats;
5. inline content;
6. positioned `z-index:auto` or `0` elements, in DOM order;
7. positive z-index.

Every item carries its order key, so the emitted stacking matches the screen.

**Boxes.** For each painted element, the snapshot records:
- background colour, with alpha kept as fill transparency;
- each border side: a uniform border becomes the shape outline, otherwise one line per
  side, keeping `dashed` and `dotted`;
- all four corner radii;
- outer `box-shadow`, every layer, in the order CSS paints them (the last listed lowest):
  - a spread-only layer is a ring: the box's outline when it is opaque, listed first and the
    box has no uniform border, else an unfilled shape of its own. A translucent ring shows
    what lies under it, never the box's fill, so its box keeps its fill at the border box
    (as built, Task 14 B2);
  - a blurred or offset layer is an outer shadow. One shape carries one, and neither app
    casts a shadow from an unfilled shape or more than a faint one from a translucent fill.
    So the box's own shape carries the first layer when its fill is opaque, and every other
    layer is a *shadow shape* under the box: its border box (shrunk by a negative spread),
    unoutlined, named "Shadow", filled so it shows nothing but its shadow: with the box's own
    colour under an opaque box, else with the one colour the export paints beneath it. Where
    no one colour lies beneath (text, a picture, a shape's edge, a picture ground), the
    shadow shapes are dropped and the box keeps its first layer, as before (as built, B2);
- cumulative opacity.

An overflow box with round corners clips to its rounded padding box. The clip carries that
box, which a native table's corner cells read (Tables).

Gradients of any kind, background images, `filter`, `mix-blend-mode`, `clip-path` and
masks go to capture as a box-only picture; the box's text stays separate and editable.

**Text.** Text is grouped into *text blocks*: the nearest block container, flex item, grid
item, table cell or list item. Bare text between block children forms its own anonymous
block (upstream issue #56). Each block becomes one text box.
- **Position.** Geometry comes from `Range.getClientRects()` of the block's text, not the
  element box, so a logo or icon beside the text can never overlap it.
  - Left-aligned text uses its text bounds.
  - Centred and right-aligned text uses the container's content width, so the alignment
    survives a slightly different font rendering.
- **Lines.**
  - Visual lines are found by clustering fragment rects whose vertical ranges overlap,
    never by de-duplicating `top`.
  - Whitespace is collapsed the way the browser collapses it, honouring `white-space`, and
    runs left empty are dropped.
- **Line breaks are the browser's.** Lines of one size end in a soft break inside one
  paragraph. A line whose largest run differs in size or line-height starts a new
  paragraph with its own spacing, because PowerPoint spacing is per paragraph. **(my call,
  see *Calls made without the owner*)**
- **Metrics.** Line spacing, slack and the first-line offset use the largest run in the
  block, never the container's inherited font-size.
- **Wrapping.** A block that is one line in the browser gets `wrap="none"`, which
  PowerPoint honours, and natural spacing. Every box also gets width slack, because Drive
  ignores `wrap="none"`. The slack is 6% plus 4 px, extended in the direction its
  alignment allows.
- **Spacing.** PowerPoint and Google Slides draw 100% spacing at 1.2 × the font size,
  whatever the font's metrics, so a multi-line block's spacing is written against that
  (as built; `scripts/export_fidelity/CALIBRATION.md`). A line height up to 1.2 × the
  paragraph's largest run is a percentage of it (`<a:spcPct>`), the lines soft breaks in
  one paragraph. A looser line height is single spacing with every line a paragraph of its
  own, and the leading beyond single as space before each line after the first
  (`<a:spcBef>`), where the two renderers agree. Vertical anchor is `top`. The first-line
  offset is calibrated against PowerPoint and Google Slides renders of a probe deck and
  pinned by a test.
- **Runs** carry:
  - font: family (the first face in the stack the document loaded), weight, italic, size;
  - colour, pre-blended against the resolved backdrop for any alpha or opacity;
  - letter spacing, `text-transform`, underline and strike-through;
  - superscript and subscript, and preserved `white-space`.

  `background-clip:text` falls back to the gradient's middle stop as a solid colour.
- **Inline decorations.** Inline elements with a background, border or padding (pills,
  chips, `<mark>`, `<kbd>`) emit a shape at each of their per-line fragment rects, under
  the text. An inline element whose horizontal margin, border and padding take space is a
  segment boundary, as an atomic inline is: its line is cut at both its ends, its own text
  is a segment inside its decoration, and the text after it keeps its exact x. So a
  sentence with a chip in it exports as several single-line boxes, each where the browser
  drew it (as built).
- **Inline boxes.** Inline atomic boxes (inline images, inline SVGs, `inline-block`s) split
  the line into segments, so the text after them keeps its exact x position.

**Lists.**
- Each list item's `::marker` is read through the DevTools protocol (§2), so its text
  (`•`, `1.`, `a.` and so on), its box and its own computed style are Chrome's, numbering
  (`start`, `reversed`) included.
- A marker outside its item is a single-line text item of its own, where its glyphs end.
  An inside marker is a token of its item's first line when the text runs straight on
  from it, and a segment of its own when a gap follows it.
- `list-style-image` is a picture at the marker's box. `list-style:none` emits none. No
  paragraph is ever a native PowerPoint bullet.

**Rotated text.** Text under a rotation, or set sideways by a vertical writing mode,
emits the unrotated box (from `offsetWidth/Height`), the angle, and browser line breaks.

**Model validation** (as built). The model is built in the slide's own realm, whose
script may have replaced the page's built-ins, so Node checks it before any use
(`model_check.cjs`): capture ids `c<n>` and unique, finite numeric geometry, known item
kinds, image items that reference a capture that exists, a table grid of at least one row
and one column. An invalid item is dropped and counted in the slide summary's
`modelDrops`; the rest of the slide exports.

**Renderer target** (as built). PowerPoint and Google Slides draw a few constructs
differently. On lines that hold a superscript or subscript run: the size of a script run, a
word joiner after a script run that ends its line (PowerPoint only), and a later line's
growth as space before. In any text: each run's tracking (PowerPoint for Mac kerns no DM
Sans, so its deck folds each run's kerning in, with no optical-size band; Google's keeps
A1), an italic webfont run's typeface (for PowerPoint its italic static's own name with
italic off; for Google the family plus italic), and U+2011 (written as U+002D for Google).
In any box: a dotted border (for PowerPoint dashed `sysDot`, one width on and one off; for
Google, whose every dot dash is one on and three off, one unfilled custom shape drawing the
centre line twice, the second pass two widths along).
`build_pptx_huashu(..., target=...)` names the app the deck is for: `"pptx"` (the download)
or `"gslides"` (the Google Slides route). Only those constructs branch. In the Google deck a
script glyph on a line the browser did not grow is drawn at 0.8 of its size, an accepted
trade-off: the line sits where the browser has it.

**Pictures.** These become capture targets:
- `<img>` (`data:` only), `<canvas>`, `<video>` posters and inline `<svg>`;
- elements whose painting cannot be native.

An `<img>` with a raster `data:` source and no filter, radius or clipping is embedded
directly. Everything else is captured, which also bakes in rounded corners, because
PowerPoint pictures have no radius.

**Tables.** A `<table>` whose cells hold text, with any inline formatting, becomes a
**native table**. It carries:
- exact column widths and row heights from the rendered cells;
- `colspan` and `rowspan`;
- per-cell padding as margins;
- fill (cell over row over table);
- all four borders on every cell;
- vertical alignment;
- runs under the same rules as text blocks;
- table radius and shadow, as a shape under the table;
- where a rounded clip (a wrapper's `border-radius` with `overflow: hidden`) cuts a filled
  cell, the cell is unfilled in the table, and its fill is a custom shape under the table,
  the cell cut to the rounded padding box (as built, B2: an `a:tc` cannot be clipped).

A cell holding an image, SVG, Harvey ball or block layout keeps the native table, and that
content is overlaid as its own items at its measured rect. A table containing a nested
table is emitted as positioned items. **(my call)**

### 4. Capture: element-isolated screenshots

Each capture target is taken from the **original, untouched page**:
1. An isolation stylesheet makes every element `visibility:hidden` except the target
   subtree. Visibility does not change layout.
2. The target's rect is screenshotted at device scale 2 with a transparent background.
   Box-only captures also make the target's text transparent.
3. The stylesheet is removed.

This captures exactly what the browser paints, including the deck's CSS, webfonts, CSS
variables, filters and clipping, and nothing that merely overlaps the target. It fixes
RC4, the gradient and filter cases of RC8, and script-drawn and tainted canvases. A failed
capture logs and skips that target; it never drops the slide.

### 5. Emitter (`emit_model.cjs`)

Writes the model with pptxgenjs, choosing constructs that both PowerPoint and Drive keep:
- **Weights:** 400 is `Family`, 700 is `Family` plus bold, and every other weight is
  `Family <Weight name>` (`Light`, `Medium`, `SemiBold`, `ExtraBold` and so on).
- **Font names:** the deck's CSS family is written, not the browser's fallback.
- **Text:** `charSpacing` in points; percentage line spacing; zero insets; browser line
  breaks; `valign: top`.
- **Shapes:**
  - `ellipse` for circles;
  - rounded rectangles with the radius converted to the preset's adjustment, relative to
    the short side (`min(0.5, r / min(w, h))`);
  - per-side lines, fill transparency and outer shadow.
- **Tables:** `addTable` with explicit `colW` and `rowH`, margins, and all four borders on
  every cell.
- **Pictures:** placed at their rect, in stacking order.

### 6. Checks and diagnostics

- Validation keeps today's behaviour under `bypassValidation`: warn instead of throw.
- **Text-loss check per slide.** The slide's rendered `innerText`, without SVG and canvas,
  is compared with the emitted text. Anything missing is logged as
  `[html2pptx] text missing: …` on stderr, so text loss is visible in the app log.
- One `[html2pptx]` summary line per slide on stderr: item counts per kind, captures taken
  and failed, the pseudo-elements read, the slide's hidden text, the renderer target and
  `modelDrops`.

### 7. Error handling

- **A capture fails.** Log `[html2pptx] capture failed: <marker> <reason>`, omit the
  item, keep the slide.
- **A model item fails validation.** Drop it, count it in `modelDrops`, export the rest
  of the slide.
- **The snapshot throws.** The slide is reported in `failures`, as today, so the
  partial-export toast names it.
- **Hostile slide script.** Termination is guaranteed by the bounded collections and walk
  limits carried over from today's code, and correctness by the pristine accessors.

### 8. Documentation

- `docs/technical/export-features.md`: replace the table-fidelity paragraph and the
  known-limitations list, and describe the new stages.
- New `docs/technical/export-fidelity-harness.md`: how to run the harness, which renderers
  to trust and why, and how to read its output.
- `.claude/skills/tellr-code-review/SKILL.md`: its huashu bundling checklist names the
  sidecar files; update it to the new file set.

## Constraints

- **No new npm dependencies.** The sidecar ships as committed `node_modules.tar.gz` and
  `sys-libs-bullseye.tar.gz`, which CI cannot rebuild (see the bundling chain in
  `.claude/skills/tellr-code-review/SKILL.md`). The design uses only the Playwright and
  pptxgenjs already in `package.json`, so the tarballs stay valid and are not regenerated.
- **Packaging.** `setup.py` copies the whole `services/pptx-emit-huashu/` directory into
  the wheel, so new files ship without packaging changes. The publish workflows'
  post-build check is extended to assert that the new sidecar files are in the wheel, so a
  build missing them fails rather than shipping a broken export.
- **Python environment.** Commands run through the per-worktree uv `.venv` (`uv sync
  --extra dev`, `uv run`), per `CLAUDE.md`. Harness-only libraries (pymupdf, Pillow) are
  passed with `uv run --with`, and the app's dependencies are not changed.
- **Sidecar time budget.** `SIDECAR_TIMEOUT_SECONDS` (180 s) covers the whole deck.
  Capture adds one screenshot per graphic. The harness records per-slide time, and the plan
  keeps a 20-slide chart-heavy deck well inside the budget.

## How we'll know it works

- **Fixtures.** `tests/fixtures/export_fidelity/` holds 17 slides covering every root cause
  and upstream's own regression cases: bare text beside an SVG, bare text after a block
  child, a hidden SVG before a visible one, mixed SVG and canvas, fractional opacity and
  `text-transform`. The 27 design-system templates stay local: they are brand assets and
  the repo is public.
- **Tests.** One pytest file per concern, using real Chromium and gated like today's
  sidecar tests. They assert on the emitted slide XML:
  - typeface names for weights, `spc`, percentage spacing, line breaks and blended colour;
  - `ellipse`, per-side lines and pseudo-element shapes;
  - stacking order;
  - `a:tbl` with `gridCol` widths and merged cells;
  - no hidden text;
  - captured pictures present and correctly sized, with chart colours sampled from the PNG;
  - text-loss check output.

  Each new test is first run against today's code and must fail. This is the
  `executing-plans-tellr` sabotage check.
- **The existing 134 sidecar tests** pass. Tests that pin an internal this design removes
  are ported to assert the same user-visible contract:
  - the SVG raster golden manifests are regenerated, with each changed entry justified;
  - "same counts as the benign twin" now uses the snapshot summary;
  - the `flattenTables` references in `test_export_csp` are updated.
- **Harness.** `scripts/export_fidelity/run.py --powerpoint --gslides` runs on both corpora
  after each task group. The plan's progress notes record:
  - side-by-side images (UI | PowerPoint | Google Slides);
  - per-slide difference scores, with none worse than the baseline;
  - text-loss results;
  - a visual check of every root cause.
- **Dev deploy.** A `.devN` built from `feat/export-revamp` is published to PyPI and deployed to
  a dedicated `devloop` instance. There, fresh decks (balance sheet, scorecards, charts,
  timelines, architecture) are generated and exported to both formats, then checked by the
  owner by hand. The app is kept for at least 2 months from its deploy date.

## Left to the builder

- How the slide model is split into modules within the sidecar, as long as each file has
  one job.
- Exact slack and offset constants, set by calibration against PowerPoint and Google Slides
  and pinned by tests.
- Whether capture runs once per target or batches targets that do not overlap.

## Calls made without the owner (review these)

1. **Keep the UI's line breaks.** Exports match the UI line for line. The trade-off is that
   an edited paragraph keeps those breaks until the user removes them. The alternative,
   letting PowerPoint and Slides re-wrap, edits more naturally but cannot guarantee the same
   lines.
2. **Native tables** for text tables, with cell graphics overlaid. A table containing a
   nested table becomes positioned items.
3. **Harvey balls, progress fills and other gradient or conic visuals** become pictures,
   while their text stays editable.
4. **The records fallback is left as it is.** It only runs when huashu is unavailable.
