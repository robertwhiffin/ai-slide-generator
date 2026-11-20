# Exports that match the UI: snapshot-then-emit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. In this repo also load `executing-plans-tellr` (sabotage-verify every test, plan-vs-code pre-pass, `Models:` tiers). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PPTX and Google Slides exports match the Tellr UI 1:1 and stay editable. The huashu sidecar's mutate-then-walk converter is replaced by a read-only snapshot of the rendered page, element-isolated captures for what cannot be native, and an emitter that writes only constructs PowerPoint and Drive's importer keep.

**Architecture:** Per slide, `render_slide.cjs` replaces `html2pptx.js` and runs five stages:
1. load and settle the page;
2. a layout-neutral preprocess: the background transfer plus guarded pseudo-element materialization;
3. `snapshot.mjs`, a single read-only `page.evaluate` that returns a JSON slide model;
4. `capture.cjs`, isolated screenshots for picture items;
5. `emit_model.cjs`, which writes the model to pptxgenjs.

During development the new engine sits behind `TELLR_EXPORT_ENGINE=snapshot`, so the existing 134 sidecar tests keep running on the old engine until Task 13 flips the default and deletes the old code.

**Tech Stack:** Node 22 (ESM `.mjs` page sources, CJS `.cjs` Node modules), Playwright 1.59 + Chromium, pptxgenjs 3.12.0 (already in `package.json`), Python 3.11 + pytest (`uv run`), python-pptx and lxml for XML assertions. Harness: pymupdf, Pillow, Microsoft PowerPoint for Mac (AppleScript), and Google Drive and Slides REST.

**Spec:** `docs/superpowers/specs/2026-11-16-export-fidelity-snapshot-emit-design.md`. RC numbers and § references below point into it.

**Branch and environment:**
- All work is on `feat/export-revamp`. Commits are authored as RickTY94 (the repo-local git config is already set) and end with `Co-authored-by: Isaac <no-reply@databricks.com>`. Push to `origin feat/export-revamp`; never `main`; no PR until the owner asks.
- Run `uv sync --extra dev` once in the repo root.
- `TMP` in commands below is the job scratch directory, `/Users/tariq.yaaqba/.claude/jobs/937bacb3/tmp`. The local design-system corpus is `$TMP/ds_fixture`; it is never committed.
- The sidecar's `node_modules` is extracted from `services/pptx-emit-huashu/node_modules.tar.gz` (gitignored). DM Sans and DM Mono static fonts are installed in `~/Library/Fonts`.

## Global Constraints

- **Dependencies:** no new npm dependencies, and `services/pptx-emit-huashu/package.json` is unchanged, so the committed `node_modules.tar.gz` and `sys-libs-bullseye.tar.gz` stay valid and are not regenerated.
- **Images:** embedded from `data:` only, as `data:image/png;base64,…` from capture or a raster `data:` `<img>` src (SDR-4437). The sidecar env allowlist in `pptx_from_html_huashu.py` is unchanged.
- **Hostile slide script:**
  - Every DOM traversal in page-side code goes through the pristine-realm accessors and bounded collection helpers in `dom_access.mjs`: no `Array.from`, spread, `for…of` or `.forEach` on a live DOM collection, and no raw `querySelectorAll`.
  - Every loop over DOM-derived data is bounded by `COLLECTION_ITEM_LIMIT` (1,000,000) or `WALK_STEP_LIMIT` (4,096).
- **Determinism:** for identical rendered pages the `.pptx` is byte-identical apart from the masked `docProps/core.xml` timestamps. Item and capture ids are sequence numbers in DOM pre-order; there are no random ids, clocks or map-iteration order dependencies. The hostile-twin tests compare whole artifacts.
- **Logging:** page and Node diagnostics carry the `[preprocess]` or `[html2pptx]` prefix and go to stderr. These existing strings must survive unchanged: `[preprocess] no slide root:`, `wrapper candidates (none)`, `several element children`, `resolved NO root`, `[preprocess] collection`.
- **Units:** the slide model is in CSS px on a 1280×720 slide. The emitter converts `in = px / 96` and `pt = px * 0.75`. Table-cell margins go to pptxgenjs in **inches, each < 1**, because it reads a value ≥ 1 as points.
- **Wrapper interface unchanged:** `build_pptx_huashu(title, slides_html, *, bypass_validation=False) -> (bytes, failures)`, the `emit_deck.mjs` stdin payload, and the `__HUASHU_RESULT__` sentinel. `bypassValidation` turns validation errors into warnings.
- **pptxgenjs run-option inheritance:** during paragraph assembly, any falsy run option (`bold: false`, `italic: false`, `charSpacing: 0`) is overwritten by the same option on the shape. So text styling goes on **runs only**, and shape-level options carry only geometry (`x y w h rotate wrap valign margin inset fit`).
- **Python:** run through `uv run` and never `pip install`. Harness-only libraries are passed with `uv run --with pymupdf --with pillow`.
- **Models:** every task is `test=opus impl=opus`, and reviewers are Opus. The owner's global instruction requires Opus for every subagent in superpowers workflows, overriding the tiering guidance in `executing-plans-tellr` §9.

## Review Focus

1. **A 20-slide, chart-heavy deck stays inside `SIDECAR_TIMEOUT_SECONDS` (180 s).** One capture per chart must not push a real deck past the timeout. Pinned in Task 7 (a timing test over 20 copies of fixture slide 03).
2. **Slides with CSS entrance animations or transitions export their settled state.** A deck that fades content in must not export it half-transparent. Pinned in Task 1 (`document.getAnimations()` finished before the snapshot; a fixture with a 1 s fade-in).
3. **Non-webfont families never get weight-named typefaces.** `font-family: system-ui, Arial` at 600 must emit `Arial` plus bold, never "Arial SemiBold", which PowerPoint would replace with a default font. Pinned in Task 3.
4. **CJK, emoji and right-to-left text survive with their order.** These lines are measured with `Range` like any text. RTL blocks set `rtlMode`. Pinned in Task 3.
5. **Deck CSS that fights the capture isolation.** A rule like `.x { visibility: visible !important }` on an unrelated element must not leak into a chart's capture. Pinned in Task 7 by the id-specificity boost.

---

### Task 1: Engine switch, shared DOM access, orchestrator, boxes and paint order

**Models:** `test=opus impl=opus`

**Files:**
- Create: `services/pptx-emit-huashu/dom_access.mjs`
  - Exports `DOM_ACCESS_SOURCE`: one JS source string that defines, in the page, everything below.
  - `capturePristineDomAccess()` and `domAccess()`.
  - `childNodesOf`, `elementChildrenOf`, `nodeListToArray`, `queryAll`, `queryAllWithin`, `queryOne`, and `reportCollectionLoss(prefix, what, where)`.
  - The constants `COLLECTION_ITEM_LIMIT` and `WALK_STEP_LIMIT`.
  - The code is **moved** from `preprocess.mjs` lines 302–556 (same accessors, same bounds, same comments trimmed to one line each). It is not rewritten. `reportCollectionLoss` takes the log prefix so both `[preprocess]` and `[html2pptx]` callers keep their strings.
- Create: `services/pptx-emit-huashu/snapshot.mjs`, exporting `SNAPSHOT_SOURCE`, an async IIFE source string `DOM_ACCESS_SOURCE + snapshot body` that returns the slide model. Task 1 builds the skeleton with background, boxes and paint order; later tasks add text, tables and lists.
- Create: `services/pptx-emit-huashu/emit_model.cjs` with `emitSlide(pres, model, captures) -> slide`. Task 1: background, shapes, lines, images.
- Create: `services/pptx-emit-huashu/render_slide.cjs` with `renderSlide(htmlFile, pres, options) -> { slide, summary }`, the per-slide orchestrator.
- Modify: `services/pptx-emit-huashu/emit_deck.mjs`. When `payload.engine === 'snapshot'`, call `require('./render_slide.cjs').renderSlide`; otherwise call `html2pptx` as today. Notes and failure handling are unchanged.
- Modify: `src/services/pptx_from_html_huashu.py`. `build_pptx_huashu` adds `"engine": os.environ.get("TELLR_EXPORT_ENGINE", "legacy")` to the payload. Task 13 removes this.
- Modify: `scripts/export_fidelity/run.py`. Add `--engine {legacy,snapshot}`, which sets `TELLR_EXPORT_ENGINE` before `export_pptx`.
- Create: `tests/fixtures/export_snapshot_support.py`, shared test helpers.
- Create: `tests/fixtures/export_snapshot/` for small single-slide fixture documents, as needed by the tests.
- Test: `tests/unit/test_export_snapshot_boxes.py`

**Interfaces:**
- Produces (`export_snapshot_support.py`):
  ```python
  requires_huashu_sidecar: pytest.MarkDecorator   # same gate as test_export_inline_svg.py
  DECK_CSS: str            # tests/fixtures/export_fidelity/deck.css (the brand corpus CSS)
  def export_slides(bodies: list[str], *, css: str = DECK_CSS, scripts: str = "",
                    external_scripts: tuple[str, ...] = (), engine: str = "snapshot",
                    monkeypatch: pytest.MonkeyPatch) -> tuple[bytes, list[dict]]
      # builds each body with src.api.routes.export.build_slide_html, sets HUASHU_PIPELINE_ENABLED=1
      # and TELLR_EXPORT_ENGINE=engine, calls build_pptx_huashu(..., bypass_validation=True)
  @dataclass
  class Run: text: str; typeface: str; bold: bool; italic: bool; size_pt: float; color: str
             spc_pt: float; baseline: str | None; underline: bool; strike: bool; soft_break_before: bool
  @dataclass
  class Para: runs: list[Run]; align: str; line_spacing_pct: float | None; rtl: bool
  @dataclass
  class Shape: kind: str            # 'text' | 'shape' | 'line' | 'picture' | 'table'
               geometry: str | None  # prstGeom name: 'rect' | 'roundRect' | 'ellipse' | 'line'
               x: float; y: float; w: float; h: float   # CSS px
               rotation: float; wrap: str | None         # bodyPr wrap: 'square' | 'none'
               fill: str | None; fill_alpha: float | None
               line: str | None; line_w_pt: float | None; line_dash: str | None
               paras: list[Para]; text: str
               image: bytes | None; table: "Table | None"; adj: int | None
  def slide_shapes(pptx: bytes, index: int = 0) -> list[Shape]   # in z-order (spTree order)
  def slide_background(pptx: bytes, index: int = 0) -> str | None # srgbClr of <p:bg>
  def text_shapes(shapes, contains: str) -> list[Shape]
  def overlaps(a: Shape, b: Shape, tolerance_px: float = 0.5) -> bool
  ```
- Produces (the slide model, documented in a JSDoc block at the top of `snapshot.mjs`):
  ```js
  // SlideModel = { width, height, background: {color} | {image}, items: Item[], captures: Capture[],
  //                reference: {hiddenText: string}, stats: {...} }
  // Item (sorted by paint order before return; each has a stable `id` = DOM pre-order sequence):
  //  {kind:'shape', x,y,w,h, geometry:'rect'|'roundRect'|'ellipse', radius,
  //   fill:{color:'RRGGBB', alpha}|null, line:{color, alpha, widthPx, dash:'solid'|'dash'|'dot'}|null,
  //   shadow:{color, alpha, blurPx, offsetPx, angle}|null, rotate}
  //  {kind:'line', x1,y1,x2,y2, color, alpha, widthPx, dash}
  //  {kind:'image', x,y,w,h, src:'data:…'|null, captureId:'c<n>'|null, rotate}
  //  {kind:'text', …}  (Task 2)       {kind:'table', …}  (Task 10)
  // Capture = {id, x,y,w,h, mode:'subtree'|'box', selector:'[data-tellr-capture="c<n>"]'}
  ```
- Produces (`render_slide.cjs`): `async renderSlide(htmlFile, pres, { bypassValidation, preProcessSource }) -> { slide, summary }`. The `{ slide }` shape matches `html2pptx`'s return, so `emit_deck.mjs`'s `addNotes` keeps working.

- [ ] **Step 1: Write the failing tests** in `test_export_snapshot_boxes.py`. All use `export_slides`, engine `snapshot`.
  - A 40×40 div with `border-radius: 50%` and background `#FF5F46` produces exactly one shape with `geometry == 'ellipse'`, `fill == 'FF5F46'` and box `(x, y, w, h)` within 0.5 px of the browser rect. The test reads the rect with Playwright on the same document via a helper `browser_rect(document_html, selector)` added to the support module. Today's engine emits `roundRect`.
  - A 200×100 card with `border-radius: 12px`, `background: #fff`, `box-shadow: 0 2px 8px rgba(27,49,57,.08)` and `border: 1px solid #DCE0E2` produces a `roundRect`, with `adj` within 1% of `round(12 / 100 * 100000)`, an outer shadow, line `DCE0E2` at 0.75 pt, and a box inset by half the border width.
  - `background: rgba(255,95,70,0.10)` produces a fill with alpha 0.10 ± 0.01.
  - **Paint order:**
    - an absolutely positioned div with `z-index: 2` that comes **earlier** in the DOM than a static sibling with a background is emitted **after** it in `spTree`;
    - a `z-index: -1` child is emitted before its parent's in-flow sibling's background;
    - flex items are painted atomically: card A's text follows card A's background and precedes card B's background.
  - The slide root's `#1B3139` background lands in `<p:bg>`, which reuses `slide_background`.
  - **Review Focus 2:** a box with `animation: fadeIn 1s` from opacity 0 to 1 exports with no fill transparency.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_export_snapshot_boxes.py -q`. Expected: FAIL. `TELLR_EXPORT_ENGINE` is ignored, so the old engine runs and the geometry and order assertions fail. Record each failure cause in the ledger.
- [ ] **Step 3: Implement.**
  - `dom_access.mjs`: move the accessor code verbatim. `preprocess.mjs` keeps its own copy until Task 13 (no behaviour change before the flip).
  - **`render_slide.cjs`, browser and page:**
    - Launch the browser exactly as `html2pptx.js` lines 1111–1122 do, including `env` and `channel`.
    - `newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2 })`. A device scale factor does not change CSS layout; it makes captures 2x.
    - Forward console messages as today: `[preprocess]` and `[html2pptx]` lines to stderr, everything else to stdout.
  - **`render_slide.cjs`, settle:** `goto`, then `networkidle` (4 s), then `document.fonts.ready`. Then the canvas preflight and wait, reimplemented from `html2pptx.js` lines 1198–1292 using `DOM_ACCESS_SOURCE`. Then `document.getAnimations().forEach(a => a.finish())`, inside a try.
  - **`render_slide.cjs`, preprocess and snapshot:**
    - Run the preprocess exactly as `html2pptx.js` lines 1299–1320 do, keeping the `[preprocess]` log lines and the `resolved NO root` line.
    - Run `bodyDimensions` validation with the same three message texts as `getBodyDimensions`, `validateDimensions` and `validateTextBoxPosition`.
    - Then `model = await page.evaluate(SNAPSHOT_SOURCE)`, then `captures = await captureAll(page, model.captures)` (Task 7; Task 1 passes an empty map), then `slide = emitSlide(pres, model, captures)`.
    - Validation errors throw unless `bypassValidation`, as today.
  - **`snapshot.mjs`, the walk:** a depth-first walk from `document.body`, with an explicit stack bounded by `WALK_STEP_LIMIT` × `COLLECTION_ITEM_LIMIT`. Per element it reads `getComputedStyle` and `getBoundingClientRect`, carrying the cumulative opacity, the clip rect (Task 6) and the paint context.
  - **`snapshot.mjs`, boxes:** an element with a non-transparent background colour, a non-zero border or an outer box-shadow emits a `shape`. The rules:
    - `geometry = 'ellipse'` when all four radii ≥ 50% of the matching side;
    - otherwise `roundRect` when the maximum radius > 0, with `radius = min(maxRadius, min(w, h) / 2)`;
    - otherwise `rect`.
    - A uniform border becomes the shape line, with the box inset by `width / 2` on every side so the stroke centre sits where CSS paints it. Non-uniform borders are Task 8.
  - **Paint order:** each item carries `order: number[]`, compared lexicographically. Use this algorithm, adapted to the accessors:
    ```js
    // ctx = {prefix:number[]} is the current REAL stacking context; paint = number[] is where this
    // element's own non-context content is painted (a pseudo-context for positioned z:auto, flex and
    // grid items, and inline-blocks).
    function placement(el, s, parentStyle, ctx, paint, seq) {
      const positioned = s.position !== 'static';
      const zAuto = s.zIndex === 'auto';
      const flexItem = /flex|grid/.test(parentStyle.display);
      const real = (positioned && !zAuto) || (flexItem && !zAuto) || parseFloat(s.opacity) < 1 ||
                   s.transform !== 'none' || s.filter !== 'none' || s.isolation === 'isolate' ||
                   s.mixBlendMode !== 'normal' || (s.clipPath && s.clipPath !== 'none');
      const z = zAuto ? 0 : parseInt(s.zIndex, 10) || 0;
      if (real) { const prefix = ctx.prefix.concat(z < 0 ? [1, z, seq] : z > 0 ? [6, z, seq] : [5, 0, seq]);
                  return { ctx: { prefix }, paint: prefix, box: prefix.concat([0, 0, 0]) }; }
      if (positioned || flexItem || /^inline-(block|flex|grid|table)$/.test(s.display)) {
        const group = (positioned ? ctx.prefix : paint).concat(positioned ? [5, 0, seq] : [4, 0, seq]);
        return { ctx, paint: group, box: group.concat([0, 0, 0]) }; }
      const layer = s.float !== 'none' ? 3 : 2;
      return { ctx, paint, box: paint.concat([layer, 0, seq]) };
    }
    // Text and inline decorations of a block painted with `paint` use paint.concat([4, 0, blockSeq, sub]),
    // sub 0 for decorations and 1 for its text box, so pills paint under their own text.
    // Replaced content (img/svg/canvas) uses paint.concat([4, 0, seq, 0]).
    ```
    Sort `items` by `order` (ties broken by `id`) before returning.
  - **`emit_model.cjs`:**
    - Background: `{color}`, or `{data}` for an image.
    - `shape`: `slide.addShape(pres.ShapeType[geometry], { x, y, w, h (in), fill: { color, transparency: round((1 - alpha) * 100) }, line: line ? { color, width: pt, dashType } : { type: 'none' }, rectRadius: radius / 96, shadow, rotate })`.
    - `line`: `addShape(line, …)` with `flipV` when `y2 < y1`.
    - `image`: `addImage({ data, x, y, w, h, rotate })`, with data from `captures.get(captureId)` or `src`. Skip and count when absent.
  - **`emit_deck.mjs`:** engine switch only.
- [ ] **Step 4: Run** the Task 1 tests. Expected: PASS. Then run `uv run pytest tests/unit -q -k "export or huashu"`. Expected: the same 134 pass, because they all run the legacy engine.
  - Sabotage checks (different from the reviewer's): drop the `ellipse` branch, so the ellipse test goes red; reverse the sort, so the paint-order tests go red; remove `getAnimations().finish()`, so the fade test goes red. Restore each, and grep for the markers.
- [ ] **Step 5: Commit.** `feat(export): snapshot engine skeleton — shared DOM access, boxes, paint order (behind TELLR_EXPORT_ENGINE)`

---

### Task 2: Text blocks — grouping, lines and geometry

**Models:** `test=opus impl=opus`

**Files:**
- Create: `services/pptx-emit-huashu/snapshot_text.mjs`. Exports `TEXT_SOURCE`, the page-side functions `collectTextBlocks(el, s, paint, seq)` and `layoutInlineRun(nodes, container, s)`. `snapshot.mjs` concatenates it.
- Modify: `snapshot.mjs` (call text collection), `emit_model.cjs` (text items).
- Create: `services/pptx-emit-huashu/emit_text.cjs` with `emitText(slide, item)`, required by `emit_model.cjs`.
- Test: `tests/unit/test_export_snapshot_text_layout.py`

**Interfaces:**
- Produces, the text item:
  ```js
  // {kind:'text', id, order, x,y,w,h, rotate:null, wrap:boolean, align:'left'|'center'|'right'|'justify',
  //  rtl:boolean, paragraphs:[{lineSpacingPct:number|null, lines:[{runs:Run[]}]}]}
  // Run = {text, family, weight, italic, sizePx, color:'RRGGBB', alpha, letterSpacingPx, underline,
  //        strike, baseline:null|'super'|'sub'}   (Task 3 fills the typography fields; Task 2 emits
  //        family/sizePx/color/weight>=600→bold)
  ```
- Consumes: the Task 1 walk (`paint`, `seq`, the cumulative opacity).

- [ ] **Step 1: Write the failing tests** using the corpus CSS. Each test asserts on shapes from `slide_shapes`.
  - **Footer (RC2):** the fixture-03 footer (logo `<img>`, brand text span and `pg` span in a `space-between` flex row) gives three items: a picture, a text box "Meridian Components · FY2024 review", and a text box "3 / 16".
    - The brand text box does not overlap the picture (`overlaps` is False).
    - The page-number box's right edge is within 2 px of the footer's right content edge, plus slack.
    - No text box contains both "review" and "3 / 16".
  - **Agenda grid (RC2):** each agenda row gives "01" and "Financial position" as **separate** text boxes, with "01" left of the title. There is no box with text `01Financial`.
  - **Bare text after a block child** (upstream #56, the fixture-17 body): the text "Then bare text that follows…" is present as its own box below "Block child first".
  - **Icon plus bare text** (#56): "Open source" and "+7.5 vs baseline" are present.
  - **Line breaks:** a 900 px-wide 42 px title that wraps to 2 lines in the browser gives one text box with exactly 2 lines. Line 2 starts with a soft break (`<a:br/>`), the paragraph count is 1, and the joined text equals the browser's line texts, which the test reads with a Range helper in `browser_lines(document_html, selector)`. A single-line label gives `wrap == 'none'`.
  - **Slack and alignment:**
    - a left-aligned single-line box has `x` equal to the browser text left ± 0.5 px, and `w` ≥ 1.06 × the browser text width + 4 px;
    - a centred line keeps its centre within 1 px of the browser's;
    - a right-aligned line keeps its right edge within 1 px of the browser's, so it grows leftward.
  - **No raw source whitespace:** no run text contains `\n` or two consecutive spaces for `white-space: normal` content (RC3's raw whitespace).
  - **`white-space: pre`:** a `<pre>` block with leading spaces keeps them as NBSP in the run text.
- [ ] **Step 2: Run** the Task 2 tests. Expected: FAIL, because text items are not emitted yet. Record the causes.
- [ ] **Step 3: Implement.**
  - **Text blocks (§3 Text):** a block is an element whose display is not `inline` or `contents`, plus anonymous runs.
    - For a block container, walk `childNodesOf(el)`. Consecutive inline-level nodes form one *inline run*: text nodes, `display: inline` elements and atomic inlines (`inline-block`, `inline-flex`, `inline-grid`, `inline-table`, `img`, `svg`, `canvas`, `video`). A block-level child ends the run and is walked as its own block.
    - For a flex or grid container, every child element is its own block (blockified), and each run of non-whitespace text nodes is its own anonymous run.
    - Never descend into `svg` or `canvas` subtrees for text. This fixes RC3.
  - **`layoutInlineRun`:**
    1. Tokenize each text node, honouring `white-space`. For `normal`, `nowrap` and `pre-line`, split on `/(\s+)/`. For `pre` and `pre-wrap`, keep spaces as NBSP and split lines on `\n`.
    2. For every word and space token, take a `Range` on `[start, end)` and read `getClientRects()` through an index loop over its `length`. A token with no rect is a collapsed space: drop it.
    3. Cluster lines in DOM order:
       ```js
       // a token starts a new line when it is a <br>, or when its rect does not overlap the current line's
       // vertical range AND it starts left of the previous token's right edge (wrap moved it back).
       const newLine = br || (rect.top >= line.bottom - 1 && rect.left < prev.right - 1);
       ```
    4. Drop a space token at a line start or end. Merge consecutive tokens with equal run style into one run.
  - **Geometry:**
    - The text bounds are the union of the line rects.
    - For `left` alignment (and `start` in LTR), `x` is the bounds' left.
    - For `center`, `right` (and `end`) and `justify`, `x` and `w` come from the container's content box: its rect minus padding and border.
    - Slack is `extra = w * 0.06 + 4`. Add it to `w`, and shift `x` by `0`, `extra / 2` or `extra` for left, centre and right.
    - `y` is the first line's top minus `firstLineOffset`. Task 2 uses 0; Task 4 calibrates it.
    - `h` is the last line's bottom minus the first line's top.
    - `wrap` is `lines.length > 1`.
  - **Paragraphs:** start a new paragraph when a line's largest run `sizePx` or the container's computed `line-height` differs from the previous line's. Otherwise lines after the first set `softBreakBefore: true` on their first run.
  - **`emit_text.cjs`:**
    - Shape options are geometry only: `{ x, y, w, h, wrap, valign: 'top', margin: 0, inset: 0, fit: 'none', align, rtlMode }`.
    - The text array has one object per run. The last run of each paragraph except the final one gets `breakLine: true`; the first run of a soft-broken line gets `softBreakBefore: true`.
    - Run options are the full style. Never put style on the shape (Global Constraints).
- [ ] **Step 4: Run** the Task 2 and Task 1 tests. Expected: PASS.
  - Sabotage checks: merge flex children back into one run, so the footer test goes red; switch line clustering to `top` dedupe, so the line-count test goes red; set slack to 0, so the slack test goes red.
- [ ] **Step 5: Commit.** `feat(export): snapshot text blocks — per flex/grid item boxes, browser lines, slack, no svg text leak`

---

### Task 3: Run typography

**Models:** `test=opus impl=opus`

**Files:**
- Create: `services/pptx-emit-huashu/emit_typography.cjs`. Exports `typefaceFor(family, weight, loadedWeights)`, `runOptions(run)` and `blendOver(color, alpha, backdrop)`.
- Modify: `snapshot_text.mjs` (run style fields, backdrop resolution, loaded font faces in `model.fonts`), `emit_text.cjs`.
- Test: `tests/unit/test_export_snapshot_typography.py`

**Interfaces:**
- Produces:
  ```js
  // model.fonts = { '<family>': [100..900 weights present in document.fonts with status 'loaded'] }
  typefaceFor('DM Sans', 600, [400,500,600,700]) -> { fontFace: 'DM Sans SemiBold', bold: false }
  typefaceFor('DM Sans', 700, ...)              -> { fontFace: 'DM Sans', bold: true }
  typefaceFor('Arial', 600, [])                 -> { fontFace: 'Arial', bold: true }   // not a loaded webfont
  typefaceFor('Impact', 700, [])                -> { fontFace: 'Impact', bold: false } // single-weight font
  const WEIGHT_NAMES = {100:'Thin',200:'ExtraLight',300:'Light',500:'Medium',600:'SemiBold',800:'ExtraBold',900:'Black'};
  blendOver('1B3139', 0.5, 'F9F7F4') -> hex of each channel round(c*a + b*(1-a))
  ```

- [ ] **Step 1: Write the failing tests.**
  - **Weights:**
    - a 42 px title at weight 600 in DM Sans gives runs with typeface `DM Sans SemiBold` and `b` absent or false;
    - weight 700 gives `DM Sans` plus `b="1"`;
    - weight 500 gives `DM Sans Medium`;
    - **Review Focus 3:** `font-family: system-ui, Arial` at 600 gives `Arial` plus bold.
  - **Element style inherited into runs (RC7, upstream PR #10):** `<h1 style="font-weight:700">Top<br>Bottom</h1>` gives every run bold. `<h2>` (600) containing a `<span style="color:#FF3621">59%</span>` gives every run `DM Sans SemiBold`, with the span run coloured `FF3621`.
  - **Per-run family:** a DM Sans paragraph containing `<code class="dk-chip">SKU-7</code>` gives the `SKU-7` run typeface `DM Mono`.
  - **Letter spacing:** `.dk-eyebrow` (13 px, `letter-spacing: .16em`) gives `spc` = round(13 × 0.16 × 0.75 × 100) ± 1.
  - **Transforms:** `text-transform: uppercase` gives upper-case run text.
  - **Super and subscript:** `profit<sup>1</sup>` gives a run "1" with `baseline` 30000. The text-loss oracle on fixture 09 reports nothing missing.
  - **Opacity (RC7):**
    - a paragraph with `opacity: .5` in `#1B3139` on `#F9F7F4` gives a solid run colour equal to `blendOver('1B3139', .5, 'F9F7F4')`, with no `<a:alpha>` on the run;
    - `color: rgba(255,255,255,.7)` on navy gives the blend against `1B3139`.
  - **Gradient text:** `.dk-gradtext` gives a visible run whose colour is the middle stop of the gradient, never transparent.
  - **Review Focus 4:**
    - a paragraph `季度收入增长 12% 🎉` gives its text intact, in order;
    - `<p dir="rtl">مرحبا بالعالم</p>` gives a paragraph with `rtl="1"` and the text intact.
- [ ] **Step 2: Run.** Expected: FAIL. Record the causes.
- [ ] **Step 3: Implement.**
  - **Run fields** from the computed style of the text node's parent element:
    - `family`: the first family in `fontFamily` that is not a generic keyword or `system-ui`/`-apple-system`/`BlinkMacSystemFont`, quotes stripped. When the stack holds only generics, map `sans-serif` → `Arial`, `serif` → `Times New Roman`, `monospace` → `Courier New`.
    - `weight`: `parseInt(fontWeight)`, rounded to the nearest 100.
    - Also `italic`, `sizePx`, `letterSpacingPx` (`normal` → 0), `underline` and `strike` (from `textDecorationLine`).
    - `baseline`: `super` or `sub` from `verticalAlign`.
    - `text-transform` is applied to the token text.
  - **Colour (backdrop and alpha):**
    - Walk up from the text's element for the nearest ancestor with a background-colour alpha ≥ 0.99; otherwise use the slide background.
    - Effective alpha = colour alpha × cumulative opacity.
    - Emit `blendOver(color, alpha, backdropOver)`, where `backdropOver` is the nearest backdrop. A translucent ancestor background is first blended over its own backdrop.
  - **Gradient text:** when `webkitBackgroundClip` or `backgroundClip` is `text` and the colour is transparent, parse the `backgroundImage` gradient's stops and take the middle one (reuse the stop parser in `preprocess.mjs::rasterizeGradientToDataURL`, moved into `snapshot_text.mjs`).
  - **`model.fonts`:** iterate `document.fonts` with its own iterator, which is a FontFaceSet, not a DOM collection. Bound it with `COLLECTION_ITEM_LIMIT`. Collect `family → weights` for faces whose `status === 'loaded'`, where a weight `"100 900"` range expands to all hundreds.
  - **`runOptions(run)`:** `{ fontFace, bold, italic, fontSize: sizePx * 0.75, color, charSpacing: letterSpacingPx * 0.75, underline: underline ? { style: 'sng' } : undefined, strike: strike ? 'sngStrike' : undefined, superscript, subscript }`.
  - `rtl` comes from `direction`.
- [ ] **Step 4: Run** Tasks 1–3. Expected: PASS.
  - Sabotage checks: emit `bold: weight >= 600` everywhere, so the weight tests go red; drop the blend, so the opacity test goes red; drop the `sup` mapping, so the oracle reports "1" missing.
- [ ] **Step 5: Commit.** `feat(export): run typography — weight-named faces, tracking, per-run family, super/sub, pre-blended colour`

---

### Task 4: Line spacing and first-line placement, calibrated against PowerPoint and Google Slides

**Models:** `test=opus impl=opus`

**Files:**
- Create: `scripts/export_fidelity/calibrate_text.py`. It renders a probe deck through the snapshot engine, opens it in PowerPoint (`run.render_with_powerpoint`) and Google Slides (`run.render_with_google_slides`), measures the ink-top and line pitch of each probe line in the PNGs against the browser truth, and prints the fitted constants.
- Create: `tests/fixtures/export_snapshot/text_calibration.html`. Probe lines at 13, 16, 20, 32, 42 and 64 px in DM Sans and DM Mono; line-heights `normal`, 1.08, 1.3, 1.45 and 1.6; one and three lines each.
- Modify: `snapshot_text.mjs` (natural line-height probe), `emit_text.cjs` (`lineSpacingMultiple`, first-line offset).
- Test: `tests/unit/test_export_snapshot_line_spacing.py`

**Interfaces:**
- Produces:
  ```js
  // snapshot: naturalLineHeightPx(family, weight, style, sizePx) measured in-page with an offscreen probe
  //   <div style="position:absolute;left:-10000px;top:0;visibility:hidden;font:…;line-height:normal">Hg</div>
  //   appended to documentElement, read, removed (cached per key). Offscreen absolute: no layout effect.
  // paragraph.lineSpacingPct = lines>1 ? round(1000 * cssLineHeightPx / naturalLineHeightPx) / 10 : null
  // emit: firstLineOffsetPx(pct, naturalPx, contentPx) — constants FIRST_LINE_A, FIRST_LINE_B from calibration
  ```

- [ ] **Step 1: Write the failing tests.**
  - The fixture-01 three-line cover title (`line-height: 1.08`) gives a paragraph whose `<a:lnSpc><a:spcPct>` value equals `round(1.08 × 64 / naturalLineHeight(DM Sans 600, 64) × 100000)` ± 500, and **no** `<a:spcPts>` anywhere in the slide (RC6).
  - A single-line label has no `<a:lnSpc>` at all (upstream pitfall 6).
  - Pinned constants: `FIRST_LINE_A` and `FIRST_LINE_B` in `emit_text.cjs` equal the values recorded in `scripts/export_fidelity/CALIBRATION.md`, so a test fails if someone edits one without the other.
- [ ] **Step 2: Run the calibration**:
  ```bash
  uv run --with pymupdf --with pillow python scripts/export_fidelity/calibrate_text.py --out "$TMP/calib"
  ```
  It prints, for each renderer, the measured ink-top error and pitch error per probe at offset 0, plus least-squares `A` and `B` for `offset = A × (pct/100 − 1) × naturalPx + B × sizePx`.
  - Choose the pair that minimises the maximum error across PowerPoint **and** Google; it may differ from each renderer's own optimum.
  - Write the chosen values, both renderers' residuals and the date into `scripts/export_fidelity/CALIBRATION.md`.
- [ ] **Step 3: Implement** `lineSpacingMultiple` (pct / 100) per paragraph and `y -= firstLineOffsetPx(...)` with the chosen constants. Re-run the calibration script. The acceptance criterion: on both renderers, the maximum ink-top error is ≤ 2 px and the pitch error ≤ 1 px at 1280 px width. Record the residuals in `CALIBRATION.md`.
- [ ] **Step 4: Run** Tasks 1–4. Expected: PASS.
  - Sabotage check: emit `lineSpacing` in points, so the `spcPts` assertion goes red.
- [ ] **Step 5: Commit.** `feat(export): percentage line spacing and calibrated first-line placement (PowerPoint + Google Slides)`

---

### Task 5: Inline decorations and atomic inline boxes

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `snapshot_text.mjs`. Collect decorations, split segments at atomic inlines.
- Test: `tests/unit/test_export_snapshot_inline.py`

**Interfaces:**
- Produces: for an inline element with a background colour, a border or padding, one `shape` item per `getClientRects()` fragment, with `order = paint + [4, 0, blockSeq, 0, elSeq]`. When a line holds an atomic inline, that line's tokens on each side of the atomic become separate single-line text items (`wrap: false`) at their own bounds.

- [ ] **Step 1: Write the failing tests.**
  - **Delta pills (fixture 06):**
    - every `▲ 0.30x` pill gives one `roundRect` filled `CDEDE1`, its rect matching the browser's within 0.5 px;
    - its text box lies inside the pill rect, plus slack, with a single line (`wrap == 'none'`);
    - the `▲` and the number share one line.
  - **Code chip in a sentence (RC13, fixture 09):**
    - the chip shape sits on the same line as "Mix shift toward…", its top within 2 px of the line's text top;
    - the sentence text is one box containing "with SKU-7 now 31% of revenue";
    - there is no gap of two spaces.
  - **Icon badge (fixture 12):**
    - the icon is a separate picture;
    - "Plant automation" and "80%" are separate text items;
    - the "Plant automation" box starts to the right of the icon's right edge.
  - **Legend swatches (fixture 03):** empty `span.sw` swatches give three filled shapes, not lost (RC8).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces. An empty inline element (no text) that has a background still emits its shape.
- [ ] **Step 4: Run** Tasks 1–5. Expected: PASS.
  - Sabotage checks: skip the per-fragment rects and use the element's bounding rect, so the two-line chip case goes red (add one); stop splitting at atomics, so the icon-badge test goes red.
- [ ] **Step 5: Commit.** `feat(export): inline pills, chips and swatches as shapes under their text; split lines at inline graphics`

---

### Task 6: Visibility, clipping and off-slide content

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `snapshot.mjs` (clip rect propagation, skip rules, `reference.hiddenText`).
- Test: `tests/unit/test_export_snapshot_visibility.py`

- [ ] **Step 1: Write the failing tests.**
  - **Screen-reader-only content (RC10):** the `.sr-only` table in fixture 03 produces no text containing "Year" or "FY20 905". Its words appear in `model.reference.hiddenText`, so the text-loss oracle does not report them.
  - **Hidden and transparent:** `visibility: hidden` and `opacity: 0` elements produce nothing.
  - **Clipping:** a child clipped by an `overflow: hidden` parent to zero area produces nothing. A child partly clipped keeps its shape, intersected with the clip rect.
  - **Off-slide content:** a decoration positioned at `right: -40px` beyond the slide is kept but clipped to the slide rect. An element entirely below y = 720 produces nothing, and the export succeeds.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the visibility rules from spec §3:
  - carry `clip` (intersection of every `overflow` ancestor's padding box and of `clip: rect()` on absolutely positioned ancestors) down the walk, starting from the slide rect;
  - shapes are intersected with `clip`;
  - text tokens whose rect falls outside `clip` (intersection < 2 px) are dropped, and their words appended to `reference.hiddenText`.
- [ ] **Step 4: Run** Tasks 1–6. Expected: PASS.
  - Sabotage check: stop intersecting, so the sr-only test goes red.
- [ ] **Step 5: Commit.** `feat(export): skip hidden and clipped content; clip shapes to their overflow ancestors`

---

### Task 7: Capture — element-isolated screenshots

**Models:** `test=opus impl=opus`

**Files:**
- Create: `services/pptx-emit-huashu/capture.cjs` with `captureAll(page, captures) -> Map<id, dataUri>`.
- Modify: `snapshot.mjs` (capture targets), `render_slide.cjs` (call `captureAll`).
- Test: `tests/unit/test_export_snapshot_capture.py`

**Interfaces:**
- Consumes: `model.captures`.
- Produces: the isolation CSS. Each `:not(#…)` adds id-level specificity, so the rule beats deck classes; this is the same trick as `SLIDE_ROOT_RESET_STYLE`'s `#tellr-root-reset-boost`.
  ```js
  function isolationCss(id, mode) {
    const target = `[data-tellr-capture="${id}"]`;
    const boost = ':not(#tellr-capture-a):not(#tellr-capture-b):not(#tellr-capture-c)';
    return `html${boost}, body${boost} { background: transparent !important; }\n` +
      `*${boost} { visibility: hidden !important; }\n` +
      (mode === 'subtree'
        ? `${target}${boost}, ${target} *${boost} { visibility: visible !important; }`
        : `${target}${boost} { visibility: visible !important; color: transparent !important;` +
          ` -webkit-text-fill-color: transparent !important; text-shadow: none !important; }`);
  }
  // capture: handle = await page.addStyleTag({content}); buf = await page.screenshot({clip, omitBackground:true,
  //          type:'png'}); await handle.evaluate(n => n.remove());  — sequential, in capture-id order.
  ```

- [ ] **Step 1: Write the failing tests.**
  - **SVG chart (RC4, fixture 03):**
    - the chart picture's PNG is 2x its box (±1 px);
    - pixel sampling at the centre of the FY24 bar gives `FF3621` ± 6 per channel, never black;
    - the gridline row holds `DCE0E2`-ish pixels;
    - the polyline area under the line is **not** filled: the sampled pixel between line and bars equals transparent or the slide ground.
  - **Harvey balls (RC8, fixture 04):** each ball gives a picture whose PNG has dark pixels in the expected sector (half-filled vs full). Its row label text is still a text item.
  - **Filtered logo (fixture 16):** the `filter: brightness(0) invert(1)` logo PNG's opaque pixels are white (≥ 240).
  - **Script-drawn canvas (fixture 17):** the canvas gives a picture with green `00A972` pixels.
  - **Progress fill (fixture 12):** the gradient fill gives a box-only picture whose left pixel is `FF3621`-ish and right pixel `FF5F46`-ish. Its track remains a native `roundRect`.
  - **Isolation:** with an extra rule `.dk-legend { visibility: visible !important }`, the chart capture holds no legend text pixels. A chart overlapped by an absolute caption box does not bake the caption into the PNG (Review Focus 5).
  - **Determinism:** two exports of fixture 03 have equal `structural_manifest` (import it from `test_export_svg_raster`).
  - **Review Focus 1:** 20 copies of fixture 03 export in under 120 s on the dev Mac, recorded with `record_property`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **Capture targets** (`mode` is `subtree` unless stated):
    - inline `svg`, `canvas` and `video`;
    - an `img` whose src is not a raster `data:image/(png|jpeg|gif|webp)`, or that has a `filter`, a border radius, a `box-shadow` (spread outlines included), `object-fit`/`object-position` cropping, or a partial clip. A shadowed `img` is captured with its rect inflated like a box-only target, so its outline or shadow is in the picture;
    - **box-only** targets: elements whose background has any gradient or `url()`, or that have `filter`, `backdrop-filter`, `mix-blend-mode`, `clip-path` or `mask` on a painted box.
  - Each target gets the `data-tellr-capture="c<seq>"` attribute (attribute selectors do not affect layout) and an `image` item at the target rect. For box-only targets with an outer shadow, inflate the rect by `max(|offset|) + blur + spread`.
  - `captureAll` captures in id order, so the output is deterministic.
  - A capture error logs `[html2pptx] capture failed: c<n> <message>` and leaves the item without data; `emit_model` then skips it and counts it in the summary.
  - Captured pixels already include the target's cumulative opacity, so the emitter applies no extra transparency to pictures.
  - Remove `rasterizeCanvases`, `rasterizeInlineSvgs` and `rasterizeSvgDataUriImages` from the snapshot path only. They are still in the legacy preprocess until Task 13.
- [ ] **Step 4: Run** Tasks 1–7. Expected: PASS.
  - Sabotage checks: drop the boost, so the isolation test goes red; switch to `element.screenshot()`, which bakes in overlapping content, so the overlap test goes red.
- [ ] **Step 5: Commit.** `feat(export): element-isolated 2x captures for charts, canvases, filtered images and gradient boxes`

---

### Task 8: Per-side borders, outline shadows and pseudo-element materialization

**Models:** `test=opus impl=opus`

**Files:**
- Create: `services/pptx-emit-huashu/pseudo.mjs`. Exports `PSEUDO_SOURCE`, defining `materializePseudoElements()`, which returns `{ pseudo: 'none' | 'materialized' | 'reverted', count }`.
- Modify: `render_slide.cjs`, which runs `PSEUDO_SOURCE` after the preprocess and before the snapshot, adding `result.pseudo` to the summary. Also `snapshot.mjs` (non-uniform borders and spread shadows).
- Test: `tests/unit/test_export_snapshot_pseudo_borders.py`

**Interfaces:**
- Produces:
  - Non-uniform borders become one `line` item per painted side, inset by half the width. Dash comes from `border-*-style` (`dashed` → `dash`, `dotted` → `dot`).
  - `box-shadow: 0 0 0 Npx C` becomes a shape outline of width N, outside the box, with the box expanded by N/2.
  - Materialization: each `::before`/`::after` with `content` other than `none` or `normal` becomes a `<span data-tellr-pseudo="before|after">` holding the full computed style. Every property in the computed declaration is copied except `content`, `counter-increment`, `counter-reset` and `counter-set`. The host gets `data-tellr-pseudo-host~="before|after"`, and one injected rule switches the original off:
    ```css
    [data-tellr-pseudo-host~="before"]:not(#tellr-pseudo-boost)::before,
    [data-tellr-pseudo-host~="after"]:not(#tellr-pseudo-boost)::after { content: none !important; }
    ```
  - Text comes from `content`: string literals (CSS escapes decoded), `open-quote`/`close-quote` → `“`/`”`, `attr(x)`, and `counter(name[, style])` / `counters(name, sep[, style])`. Counters are evaluated by a document-order counter model: `counter-reset`/`counter-set`/`counter-increment` on elements and their pseudo-elements, nested scopes per CSS Lists 3 §4, and styles `decimal`, `decimal-leading-zero`, `lower-alpha`/`upper-alpha`, `lower-roman`/`upper-roman`, `disc`/`circle`/`square`.
  - **Layout guard:** record every element's rect before. After materializing, if any element moved by more than 0.5 px, remove all spans, attributes and the rule, log `[preprocess] pseudo materialization moved layout; reverted (<n> elements moved, first: <tag.class>)`, and return `reverted`.

- [ ] **Step 1: Write the failing tests.**
  - **Square bullets (fixture 09 `.dk-list li::before`):** four 12×12 `roundRect`s filled `FF5F46`, each left of its `li` text at the browser's rect ± 0.5 px.
  - **Accent bar (`.dk-accent-bar::before`):** one 5 px-wide shape, coral, full height minus 8 px.
  - **Journey and timeline dots:** these are present in the DS-style fixture `tests/fixtures/export_snapshot/pseudo_dots.html`, which follows the design-system `slide-journey` markup pattern (written for this test, not copied).
  - **Counter content:** `.steps { counter-reset: s } .step::before { counter-increment: s; content: counter(s, decimal-leading-zero) }` over three steps gives texts "01", "02" and "03".
  - **Guard:** a fixture whose `::before` is `display: block; height: 40px` while the copied span picks up a different `line-height` (forced with `.host > span { line-height: 3 }`) logs `reverted`. Nothing else in the slide changes against the engine with materialization disabled (compare `slide_shapes`).
  - **Borders:** a blockquote with `border-left: 6px solid #FF5F46` gives one vertical `line` of 4.5 pt. A dashed bottom border gives `prstDash` `dash`. `box-shadow: 0 0 0 2px #1B3139` gives an outline of 1.5 pt.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** to the Interfaces. Use `getComputedStyle(el, '::before')`. Walk elements with the `dom_access` helpers.
- [ ] **Step 4: Run** Tasks 1–8. Expected: PASS.
  - Sabotage checks: remove the guard's comparison, so the guard test goes red; copy `counter-increment`, so the counter test reads "02, 04, 06" and goes red.
- [ ] **Step 5: Commit.** `feat(export): materialize ::before/::after (with counters, layout-guarded); per-side borders and outline shadows`

---

### Task 9: List markers

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `snapshot_text.mjs`.
- Test: `tests/unit/test_export_snapshot_lists.py`

- [ ] **Step 1: Write the failing tests.**
  - **`<ol>` (fixture 14):** three marker items "1.", "2." and "3." (not bullets, RC8), each right-aligned with its right edge within 3 px of where the browser draws the marker. That position is measured by the test from a screenshot column scan of the marker glyph.
  - `<ol start="4" reversed>` gives "4.", "3." and "2.".
  - **`list-style: none`** (fixture 16 `ul`): no marker items, and no `bullet` in any paragraph.
  - **Default `ul`:** "•" markers.
  - **`list-style-position: inside`:** the marker text is prepended to the first run, with no separate item.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** markers for `display: list-item` with `list-style-type` other than `none` and no `::marker` `content: none`.
  - The index follows the `ol`'s `start`/`reversed`/`value` attributes; text by type uses the Task 8 counter-style formatter.
  - The marker is a single-line text item, using the `li`'s first-run style.
  - It is right-aligned at `x_right = liContentLeft - markerGap`, where `markerGap = 0.5 × sizePx`. Task 14 verifies and adjusts the constant against the browser screenshot.
- [ ] **Step 4: Run** Tasks 1–9. Expected: PASS.
  - Sabotage check: map every type to "•", so the `ol` test goes red.
- [ ] **Step 5: Commit.** `feat(export): list markers as the browser numbers them; honour list-style none`

---

### Task 10: Native tables

**Models:** `test=opus impl=opus`

**Files:**
- Create: `services/pptx-emit-huashu/snapshot_table.mjs`, exporting `TABLE_SOURCE`, which defines `collectTable(tableEl)`.
- Create: `services/pptx-emit-huashu/emit_table.cjs` with `emitTable(slide, item)`.
- Modify: `snapshot.mjs`. Native-table detection; cells' text and boxes owned by the table.
- Test: `tests/unit/test_export_snapshot_tables.py`

**Interfaces:**
- Produces:
  ```js
  // {kind:'table', x,y, colWidths:number[], rowHeights:number[],
  //  cells:[{row, col, rowspan, colspan, fill:{color,alpha}|null,
  //          borders:{top,right,bottom,left: {color, alpha, widthPx, dash}|null},
  //          padding:{top,right,bottom,left}, valign:'top'|'middle'|'bottom', align,
  //          paragraphs: Paragraph[] | null   // null → text emitted as overlay items instead
  //  }]}
  ```
- Collapsed-border resolution, applied when `border-collapse: collapse`:
  ```js
  // For every shared edge, the winner is the wider border; on equal width, style order
  // double > solid > dashed > dotted, then the cell earlier in DOM order. The winner is written on BOTH cells'
  // sides, so PowerPoint/Drive never see one cell's 'none' contradicting its neighbour's line.
  ```

- [ ] **Step 1: Write the failing tests.**
  - **Balance sheet (fixture 05, RC1):**
    - two `graphicFrame` tables with **disjoint** x-ranges, matching each browser table rect ± 1 px;
    - `gridCol` widths sum to the table width ± 1 px;
    - the section row "Current assets" is one cell spanning 3 columns (`gridSpan="3"`);
    - the header fill is `FF5F46`, with header runs `DM Sans SemiBold`;
    - the total row's top border is `1B3139`, written on the total row's `lnT` **and** the previous row's `lnB` (collapsed-border rule);
    - the grand row is filled `1B3139` with white runs;
    - the indented row's left margin equals 26 px in EMU ± 1%;
    - all margins are < 1 inch.
  - **Scorecard (fixture 04, RC1/RC9):**
    - the source caption text box lies **below** the table's bottom edge;
    - the row labels are SemiBold (RC9);
    - the FY2024 column cells are filled `FF5F46` at alpha 0.10;
    - each Harvey ball is a picture overlaid **inside** its cell rect;
    - the "Strength · current ratio…" cell is native-table text with "Strength" bold.
  - **Pills table (fixture 06):** the "So what" callout's shape does not overlap the table frame (RC1), and every pill picture or shape lies inside its "Change" cell.
  - **Nested table:** a `<table>` inside a `<td>` makes the outer table emit as positioned items (no `graphicFrame`), with all text present.
  - **Google round-trip** (marked `requires_google_slides`, skipped without gcloud ADC): converting fixture 05 through Drive and reading the Slides JSON gives tables whose bottom-border colour on the "Total current assets" row is `1B3139` in every column. This re-verifies the spec §3 row on per-cell borders, and Task 13 corrects that row's wording.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **Native when:** the table's display is `table`, it holds no nested `table`, and every cell's content is inline-level or atomic graphics.
  - **Grid:** column edges are the sorted unique cell left and right x positions (merged within 0.5 px), and the same for rows from cell tops and bottoms. A cell's indices and spans come from the edge indexes.
  - **Fill precedence:** cell, then `tr`, then the row group, then the table; the table's own fill stays a `shape` under the frame, emitted by the walker.
  - **Cell text:** a cell whose lines contain no atomic inline gets `paragraphs` from `layoutInlineRun`. Otherwise `paragraphs: null` and the text is emitted as overlay text items.
  - **Ownership:** the walker skips box emission for `table` borders, `thead`, `tbody`, `tfoot`, `tr`, `td` and `th` (owned by the table). It still emits the table's own background, radius and shadow, and still visits cell descendants for pills, pictures and captures.
  - **`emitTable`:** `slide.addTable(rows, { x, y, w, colW, rowH, autoPage: false })`. Each cell gets:
    - `{ text: runs[], options: { fill, border: [t, r, b, l] as { type: 'solid' | 'dash' | 'none', pt, color }, margin: [t, r, b, l] in inches, valign, align, colspan, rowspan } }`;
    - per-run `runOptions`, from Task 3;
    - paragraph `lineSpacingMultiple`;
    - the inherited-option rule from Global Constraints (no style on table-level options).
- [ ] **Step 4: Run** Tasks 1–10, and the Google test when ADC is present. Expected: PASS.
  - Sabotage checks: write each cell's own borders without collapse resolution, so the `lnB`/`lnT` assertion goes red; place the caption using the old `display: none` flatten, so the caption-below test goes red.
- [ ] **Step 5: Commit.** `feat(export): native editable tables — exact grid, merges, collapsed borders, cell graphics overlaid`

---

### Task 11: Rotated text

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `snapshot_text.mjs`.
- Test: `tests/unit/test_export_snapshot_rotation.py`

- [ ] **Step 1: Write the failing tests.**
  - **Fixture 13's `rotate(-90deg)` label "GOVERNED DATA" (RC12):**
    - one text item, `rot` = 270° (PowerPoint units 16200000), single line, `wrap == 'none'`;
    - the unrotated box `w` × `h` equals `offsetWidth` × `offsetHeight` ± 1 px;
    - its centre equals the browser bounding-box centre ± 1 px.
  - **Arbitrary angle:** a `rotate(12deg)` tag gives `rot` 12°.
  - **Fixture 2x2 axis label** (DS-style, written for this test): "EFFORT →" is one line.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - When the text container or an ancestor has a transform with rotation (`atan2(b, a)` of the matrix ≠ 0), the nearest rotated element's text becomes one item.
  - Its geometry: the unrotated `offsetWidth` × `offsetHeight` box, centred on the bounding rect's centre, with `rotate` = angle in degrees normalised to 0–359.
  - Its lines come from the element's text in DOM order, split by `<br>` and block children. Range rects are axis-aligned under rotation, so line clustering is not used here.
- [ ] **Step 4: Run** Tasks 1–11. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(export): rotated text keeps its unrotated box, angle and single line`

---

### Task 12: Checks — text-loss, summary line and validations

**Models:** `test=opus impl=opus`

**Files:**
- Create: `services/pptx-emit-huashu/text_check.cjs` with `missingWords(reference, emitted, hidden) -> string[]` and `textLossLine(reference, items, hidden) -> string | null`. The second collects text from text items, table cells and list markers, then formats the log line.
- Modify: `render_slide.cjs`. After capture, read the reference with `page.evaluate`: hide `svg`/`canvas`, then read `document.body.innerText`. This runs after every capture, so it cannot affect output. Then log:
  - `[html2pptx] text missing: <json array>` when non-empty;
  - always one `[html2pptx] slide summary <json>`, with `{ text, shapes, lines, pictures, tables, captures, captureFailures, pseudo }`.
- Modify: `scripts/export_fidelity/run.py`. `check_text_loss` treats a slide absent from the `.pptx` as all text missing (upstream PR #59) and reads `model.reference.hiddenText` from the summary line, so hidden words are not reported.
- Test: `tests/unit/test_export_snapshot_checks.py`

- [ ] **Step 1: Write the failing tests.**
  - `missingWords('Revenue up 10.7%', 'Revenueup10.7%', '') == []`, `missingWords('profit1', 'profit', '') == ['profit1']`, and hidden words are excluded. These run through `node -e` against `text_check.cjs`.
  - Exporting fixture 03 with the engine logs one `slide summary` line with `pictures ≥ 2` and `captureFailures == 0`, and no `text missing` line.
  - `textLossLine(reference, items, hidden)` is the function `render_slide.cjs` logs from. Given a synthetic model whose text items omit the word "Liquidity" from a reference containing it, it returns a line starting `[html2pptx] text missing:` that names `Liquidity`. Given a complete model, it returns `null`. This runs as a Node unit test (`node -e`) over hand-built item arrays, so it needs no browser.
  - In the harness, a `.pptx` with one slide for a two-slide reference reports slide 2's words as missing.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as above. `missingWords` compares normalised words (whitespace removed, lower-cased) as substrings of the normalised concatenated emitted text.
- [ ] **Step 4: Run** Tasks 1–12. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(export): per-slide text-loss check and summary line on stderr`

---

### Task 13: Flip to the snapshot engine; delete the legacy converter; port the tests

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `emit_deck.mjs`. Always `renderSlide`; remove the engine switch and the `html2pptx` require.
- Delete: `services/pptx-emit-huashu/html2pptx.js`. This is the vendored, pre-rewrite upstream file (spec "Code provenance").
- Modify: `preprocess.mjs`. Keep only `transferSlideRootBackground`, the slide-root locator and `reportNoSlideRoot`, with their comments, reading through `DOM_ACCESS_SOURCE` (imported from `dom_access.mjs`, not its local copy). Delete:
  - `flattenMonospaceCodeBlocks`, `wrapInlineRunsIn`, `wrapBareTextInDivs`, `replaceBackgroundImageWithImg`;
  - `rasterizeGradientToDataURL`, kept only as the shared stop parser moved in Task 3;
  - `peelBackgroundsOffTextTags`, `flattenTables`, `emitInlineBackgrounds`, `rasterizeCanvases`, `rasterizeSvgDataUriImages`, `rasterizeInlineSvgs`, `containFitRect`, `coverFitSourceRect`.

  The result object becomes `{ bgTransferred }`.
- Modify: `src/services/pptx_from_html_huashu.py`. Remove the `engine` payload field. Update the module docstring (it still says "local-only" and names `html2pptx.js`).
- Modify: `scripts/export_fidelity/run.py`. Remove `--engine`.
- Modify: `.github/workflows/publish.yml` and `publish-dev.yml`. The post-build verify step also asserts that `render_slide.cjs`, `snapshot.mjs`, `snapshot_text.mjs`, `snapshot_table.mjs`, `pseudo.mjs`, `dom_access.mjs`, `capture.cjs`, `emit_model.cjs`, `emit_text.cjs`, `emit_typography.cjs`, `emit_table.cjs` and `text_check.cjs` are in the wheel under `databricks_tellr_app/_assets/sidecars/pptx-emit-huashu/`.
- Modify: existing tests that pin removed internals:
  - `tests/unit/test_export_svg_raster.py`: the huashu golden manifests are regenerated with `REGEN_ENV=1`, and each changed entry is justified in the commit message. Its PNG-dimension assertions become "2x the box" (capture).
  - `tests/unit/test_export_inline_svg.py`: assert the icon is a captured picture.
  - `tests/unit/test_export_collection_iteration_hostile_realm.py`: the twin count comparison now compares preprocess `{ bgTransferred }` **and** the `slide summary` JSON from stderr. The docstring's line references are updated.
  - `tests/unit/test_export_csp.py`: its `flattenTables` comment.
  - `tests/unit/test_pptx_from_html_huashu_image_src.py`: its `html2pptx.js` paths become `render_slide.cjs` and `emit_model.cjs`. **Keep every assertion's intent: non-`data:` sources are never embedded.**
  - `test_export_snapshot_*.py`: drop the `engine` argument (default is the only engine).
- Modify: docs.
  - `docs/technical/export-features.md`: replace the "Table fidelity differs by route" paragraph and the "Known export limitations" paragraph; describe the five stages.
  - Create `docs/technical/export-fidelity-harness.md`: running `run.py` (`--powerpoint --gslides --lo`), trusted renderers, the text-loss oracle, `CALIBRATION.md`, and reading `compare/` and `scores.json`.
  - `.claude/skills/tellr-code-review/SKILL.md` §2: name the new sidecar files and the wheel assertion.
  - Spec §3: correct the "Native table" row to the Task 10 Google result.
- Test: the whole sidecar suite.

- [ ] **Step 1: Run the full sidecar suite on the snapshot engine before deleting anything:**
  ```bash
  TELLR_EXPORT_ENGINE=snapshot uv run pytest tests/unit -q -k "export or huashu"
  ```
  Record each failure **by cause** (`executing-plans-tellr` §3) and classify it as one of:
  - (a) pins a removed internal (port it);
  - (b) a real regression in the new engine (fix it in the owning task's module, with a new test);
  - (c) a golden that legitimately changed (regenerate and justify).
- [ ] **Step 2:** Flip, delete and port, per Files.
- [ ] **Step 3: Run** `uv run pytest tests/unit -q`. Expected: everything passes except the known unrelated baseline causes recorded before Task 1. Also run `bash services/pptx-emit-huashu/build-artifacts.sh`, then `TELLR_INCLUDE_HUASHU_SIDECAR=1 uv run python -m build --wheel packages/databricks-tellr-app` and the extended verify snippet from the workflow, locally. Expected: the new files are present.
  - Sabotage check: rename `capture.cjs` in a scratch copy of the build tree, so the verify snippet fails.
- [ ] **Step 4: Commit.** `refactor(export): snapshot engine is the export; delete vendored html2pptx.js and mutating preprocess passes; port tests, docs, CI checks`

---

### Task 14: Fidelity verification on both corpora

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `scripts/export_fidelity/run.py`. The `compare/` sheets include the PowerPoint render, and a `summary.md` table is written with per-slide scores against the baseline, text-loss and capture counts.
- Create: `docs/superpowers/plans/2026-11-16-export-fidelity-progress.md`, the ledger: baselines, results, rulings and corrections, per `executing-plans-tellr` §8.

- [ ] **Step 1: Run** the harness, both renderers, on the in-repo corpus and the local design-system corpus (`$TMP/ds_fixture`):
  ```bash
  uv run --with pymupdf --with pillow python scripts/export_fidelity/run.py tests/fixtures/export_fidelity --out "$TMP/fid-after" --powerpoint --gslides
  ```
- [ ] **Step 2: Review every slide's** UI | PowerPoint | Google Slides sheet against every RC in the spec. Record in the ledger a line per slide: what still differs, its cause, and its fix. Each fix:
  - goes into the owning module;
  - comes with a new failing test, red first, in that task's test file;
  - is re-run on both corpora.

  The loop ends when:
  - no slide shows an RC defect;
  - no slide's score is worse than its baseline in either renderer;
  - text-loss is empty everywhere.
- [ ] **Step 3: Record** the final scores table and the links to the Google Slides decks in the ledger. Commit the sheets' summary only, not the images.
- [ ] **Step 4: Commit.** `test(export): fidelity verified on finance and design-system corpora in PowerPoint and Google Slides`

---

### Task 15: Dev build, devloop deploy and real-deck verification

**Models:** `test=opus impl=opus`. This task is operational and has no code.

Follow `.claude/skills/deploy-tellr-dev/SKILL.md` exactly. The owner's account is RickTY94 (the `gh` active account). The workspace profile is `fe-vm-tellr-dev`, where the skill says `tellr-dev`.

- [ ] **Step 1:**
  ```bash
  git push origin feat/export-revamp
  gh workflow run publish-dev.yml --ref feat/export-revamp
  ```
  Then `gh run list --workflow publish-dev.yml --limit 1`, then `gh run watch <id> --exit-status`. Confirm `200 OK` and `View at: https://pypi.org/project/databricks-tellr-app/<version>/` from `gh run view <id> --log`. Never gate on an index listing.
- [ ] **Step 2:**
  ```bash
  ./scripts/deploy_local.sh create --env devloop --instance export-revamp --profile fe-vm-tellr-dev --from-pypi <version>
  ```
  This is the first deploy, so `create`. Then `databricks apps get db-tellr-dev-export-revamp --profile fe-vm-tellr-dev -o json` until `app_status.state=RUNNING` and `active_deployment.status.state=SUCCEEDED`. A 502 from `/health` during the startup backfill is normal.
- [ ] **Step 3:** In the deployed app, check that `/api/export/pptx/editable/huashu/available` reports available. Then generate decks with the corpus patterns:
  - a balance sheet with two tables;
  - a scorecard with Harvey balls;
  - an SVG combo chart with a callout;
  - delta pills;
  - a timeline;
  - KPI cards;
  - an architecture slide on the Databricks design system.

  Export each to PPTX and Google Slides. Render both through the harness's `render_with_powerpoint` and thumbnails, and record the results with links in the ledger.
- [ ] **Step 4: Do not delete the app.** Record its URL, instance id and version in the ledger. Keep it for at least 2 months from its deploy date; the owner tests it by hand.
