# MCP Deck Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo also load `executing-plans-tellr`.

Execution: chained

**Goal:** Tellr's MCP returns the deck links first and a small, honest HTML preview (no fonts, no raster images, ≤10 slides, whole result ≤150 KB) instead of a duplicated multi-MB payload.

**Architecture:** Two pure helper modules (`src/utils/preview_css.py`, `src/utils/preview_images.py`) and one assembler (`src/services/mcp_deck_preview.py`) turn a persisted deck dict into preview HTML. `src/api/mcp_server.py` stops substituting images/fonts for MCP, builds a links-first JSON payload, and returns it plus the preview as two `TextContent` items.

**Tech Stack:** Python 3, FastAPI, `mcp==1.27.0` FastMCP, SQLAlchemy, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-18-mcp-deck-preview-design.md` — read it first; it holds the owner's decisions and the **[call]** markers.

## Global Constraints

- Preview copy, exact, lowercase `tellr`:
  - top strip: `preview — open the full deck in tellr` (linked to `deck_url`)
  - image notice: `image not shown in preview, see full deck in tellr`
  - trailing notice: `N more slides — see full deck in tellr` (`1 more slide — see full deck in tellr` for one)
- `MAX_PREVIEW_SLIDES = 10`; `MCP_RESULT_BUDGET_BYTES = 150_000` (UTF-8 bytes of item 1 text + item 2 text).
- Inline-SVG cap: `SVG_INLINE_MAX_BYTES = 10_240` (decoded SVG text bytes).
- No base64 anywhere in the preview HTML. No `{{image:…}}` / `{{ds-asset:…}}` handle left in it either.
- `{{image:…}}` handles (image library) are ALWAYS replaced by the notice, never looked up — no DB read, no privacy-guard path. Only design-system SVG assets and SVG `data:` URIs already in the deck are inlined (plan-time narrowing of spec rule 6; the spec's intent — no raster bytes, small logos stay — holds).
- No new dependencies. Run everything with `uv run` in the worktree (`uv sync --extra dev` first).
- Legacy (monolith) engine code untouched. Persisted decks, the editor, `/view`, exports and the app's HTML download unchanged.
- The two MCP deck tools must not gain an `outputSchema` / `structuredContent`.
- Commit messages end with `Co-authored-by: Isaac <no-reply@databricks.com>`.
- Never commit the owner's easyJet export or any real customer deck as a fixture.

## Review Focus

1. **Tailwind-style / escaped / attribute selectors** (`.md\:flex`, `[data-x] .y`, `:is(.a, .b)`): the CSS trimmer must keep anything it cannot classify — pinned in Task 1 (`test_trim_keeps_unclassifiable_selectors`).
2. **`<img>` written with single quotes, no quotes, or a `srcset`**: every form must lose its raster data — pinned in Task 2 (`test_img_src_quote_forms_and_srcset`).
3. **A Legacy or hand-edited deck whose persisted HTML already holds base64 data URIs** (no handles): the preview still carries no base64 — pinned in Task 3 (`test_preview_of_inline_data_uri_deck_has_no_base64`).
4. **Non-ASCII slide text** (é, —, emoji): the budget counts UTF-8 bytes, not characters — pinned in Task 3 (`test_budget_counts_utf8_bytes`).
5. **A deck with zero slides** (architect asked a question on create): one content item, no HTML, a note — pinned in Task 4 (`test_get_deck_of_empty_deck_has_one_item`).

---

### Task 1: Preview CSS — drop embedded fonts, Google Fonts imports, conservative trim

Models: test=opus impl=sonnet

**Files:**
- Create: `src/utils/preview_css.py`
- Test: `tests/unit/test_preview_css.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `FontFaces = dict[str, set[tuple[int, int]]]` — family name → `{(ital, weight)}` with `ital` 0/1.
  - `strip_embedded_font_faces(css: str) -> tuple[str, FontFaces]` — removes every `@font-face { … }` whose `src` contains `data:` or `{{ds-asset:`; returns the remaining CSS and the removed faces. `@font-face` with only `http(s):` srcs stays and is not reported.
  - `google_fonts_imports(faces: FontFaces) -> str` — one `@import url('https://fonts.googleapis.com/css2?family=<Name+With+Plus>:ital,wght@<i,w;…>&display=swap');` line per family, families sorted, tuples sorted, `\n`-joined; `""` for no faces.
  - `trim_css(css: str, used_text: str) -> str` — comments removed, minified, rules pruned (rules below).

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_preview_css.py`:
  - `test_strip_removes_data_uri_font_faces_and_reports_them`: CSS with three `@font-face` (DM Sans 400 normal `data:font/ttf;base64,AAAA`, DM Sans 700 italic `{{ds-asset:7}}`, Inter 400 `https://example.com/inter.woff2`) + `.a{color:red}` → returned CSS contains no `data:`, no `ds-asset`, still contains `inter.woff2` and `.a{color:red}`; faces == `{"DM Sans": {(0, 400), (1, 700)}}`.
  - `test_strip_parses_weight_keywords_and_ranges`: `font-weight: normal` → 400, `bold` → 700, `100 900` → both 100 and 900; `font-style: oblique` → ital 1; quoted and unquoted family names give the same key.
  - `test_google_fonts_imports_one_line_per_family`: `{"DM Sans": {(0,400),(1,400),(0,700)}, "DM Mono": {(0,500)}}` → exactly
    `@import url('https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,500&display=swap');\n@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,700;1,400&display=swap');`; `google_fonts_imports({}) == ""`.
  - `test_trim_drops_only_rules_whose_names_are_absent`: `.used{a:1} .unused{b:2} #gone{c:3} .used .unused{d:4} .used, .unused{e:5}` with `used_text='<div class="used">'` → keeps `.used{a:1}` and `.used{e:5}` (the comma list loses only its dead selector), drops the rest.
  - `test_trim_keeps_root_vars_element_rules_and_at_rules`: `:root{--x:1}`, `body{margin:0}`, `@keyframes spin{from{a:1}to{a:2}}`, `@import url('https://x');`, `@page{size:a4}` all survive with `used_text=""`.
  - `test_trim_recurses_into_media_and_drops_empty_media`: `@media (min-width:1px){.used{a:1}.unused{b:2}}` keeps only `.used`; `@media print{.unused{b:2}}` disappears entirely.
  - `test_trim_survives_comment_before_import` (the spike's real bug): `/* header */\n@import url('https://f');\n/* c */ :root{--bg:#123}\n.slide.dark{background:var(--bg)}` with `used_text='class="slide dark"'` → output contains `@import url('https://f')`, `:root{--bg:#123}` and `.slide.dark{background:var(--bg)}`.
  - `test_trim_keeps_unclassifiable_selectors`: with `used_text='class="a"'`, `.md\:flex{a:1}` (contains `\`) and `:is(.a, .b) p{c:1}` / `.x:not(.y){e:1}` (contain `(`; the commas inside `:is(...)` are not selector separators) are all kept; `[data-x] .zz{b:1}` and `.qq{d:1}` are dropped (classifiable, `zz`/`qq` absent).
  - `test_trim_counts_names_in_scripts_text`: `.chart-tip{a:1}` kept when `used_text` contains `el.classList.add('chart-tip')`.
  - `test_minify_keeps_descendant_pseudo_space`: `.a :hover{x:1}` stays `.a :hover{x:1}` (never strip whitespace before `:` or around `>`/`+`/`~`); whitespace runs collapse to one space; spaces adjacent to `{`, `}`, `;` and the last `;` before `}` are removed.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_preview_css.py -v` — expected: FAIL (module not found).

- [ ] **Step 3: Implement `src/utils/preview_css.py`.** A small brace-matching scanner over comment-stripped CSS (strings and `url(...)` may contain braces/semicolons — skip over quoted strings while scanning). Statement at-rules (`@import`, `@charset`, `@namespace`) end at `;`. A rule's selectors split on top-level commas (depth 0 of `()`/`[]`). A selector is **dead** iff it contains neither `\` nor `(`, and at least one `.name` / `#name` token in it is not a whole word of `used_text` (word = `[A-Za-z0-9_-]+`, so `slide` in `class="slide dark"` counts). Everything else is kept. Recurse into `@media` / `@supports` / `@container` / `@layer` blocks; keep every other at-rule block verbatim.

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_preview_css.py -v` — expected: PASS.

- [ ] **Step 5: Commit** `feat(mcp): preview CSS — strip embedded fonts, Google Fonts imports, safe trim`.

---

### Task 2: Preview images — notice for rasters, small SVGs as text

Models: test=opus impl=sonnet

**Files:**
- Create: `src/utils/preview_images.py`
- Modify: `src/services/design_system_service.py` (add `get_small_svg_assets` after `get_assets_base64`, ~line 2303)
- Test: `tests/unit/test_preview_images.py`

**Interfaces:**
- Consumes: `DS_ASSET_PLACEHOLDER_PATTERN` (`src/utils/ds_asset_utils.py`), `IMAGE_PLACEHOLDER_PATTERN` (`src/utils/image_utils.py`).
- Produces:
  - `IMAGE_NOTICE = "image not shown in preview, see full deck in tellr"`
  - `SVG_INLINE_MAX_BYTES = 10_240`
  - `svg_data_uri(svg_text: str) -> str` — `data:image/svg+xml,` + percent-encoded text (XML prolog and comments removed, whitespace between tags collapsed). `#`, `%`, `"`, `'`, `<`, `>` are always encoded; the result never contains `;base64`.
  - `NOTICE_IMG_SRC: str` — a `data:image/svg+xml,` text URI (no base64) drawing a light-grey box (`#EEF0F2`, 1px `#C8CDD2` border) with `IMAGE_NOTICE` centred. The box fills the `<img>`'s own size and the text stays legible, not stretched; how (viewBox / `preserveAspectRatio` choice) is the implementer's. Under 600 bytes.
  - `hide_images_in_html(html: str, svg_assets: Mapping[int, str]) -> tuple[str, int]`
  - `hide_images_in_css(css: str, svg_assets: Mapping[int, str]) -> tuple[str, int]`
  - Both return the new text and how many images were hidden. Rules for a source value: `{{image:T}}` → hidden; `{{ds-asset:N}}` with `N in svg_assets` → `svg_data_uri(svg_assets[N])`, else hidden; `data:image/svg+xml;base64,…` → decode, inline as text if ≤ `SVG_INLINE_MAX_BYTES` else hidden; `data:image/svg+xml,…` (text) → kept if ≤ cap else hidden; any other `data:image/…` → hidden; `http(s):` and relative URLs untouched.
  - In HTML: an `<img>` `src` (double, single or no quotes) that is hidden becomes `NOTICE_IMG_SRC`, and its `alt` becomes `IMAGE_NOTICE`; any `srcset` attribute containing `data:` or a handle is removed; then `hide_images_in_css` runs over the whole HTML string so `style="background:url(…)"` is covered.
  - In CSS: a hidden `url(…)` (quoted or not) becomes `none`; an inlined one becomes `url("<svg_data_uri>")`.
  - `design_system_service.get_small_svg_assets(db: Session, asset_ids: Iterable[int], *, design_system_id: Optional[int], max_bytes: int) -> dict[int, str]` — one query filtered on `id IN ids`, `design_system_id == design_system_id`, `mime == "image/svg+xml"`, `size_bytes <= max_bytes`; values are UTF-8-decoded `data` (undecodable rows skipped). `design_system_id=None` → `{}` (fail-closed, like `get_assets_base64`).

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_preview_images.py` (SQLite fixture as in `tests/unit/test_mcp_server.py:58-89` for the service test):
  - `test_raster_handles_and_data_uris_become_the_notice`: `<img src="{{image:abc}}">`, `<img src="data:image/png;base64,iVBORw0KGgo=">`, `<img src="{{ds-asset:9}}">` (9 not in `svg_assets`) → 3 hidden; output has no `base64`, no `{{`, and contains `NOTICE_IMG_SRC` three times and `alt="image not shown in preview, see full deck in tellr"`.
  - `test_small_ds_svg_is_inlined_as_text`: `svg_assets={4: '<?xml version="1.0"?><!-- c --><svg xmlns="http://www.w3.org/2000/svg"><path fill="#FF3621" d="M0 0"/></svg>'}`, `<img src="{{ds-asset:4}}">` → 0 hidden; output contains `data:image/svg+xml,` and `%23FF3621`, no `#FF3621` inside the src, no `<?xml`, no `<!--`.
  - `test_base64_svg_data_uri_inlined_or_hidden_by_size`: a 200-byte SVG as base64 → inlined text, 0 hidden; a 20 KB SVG as base64 → notice, 1 hidden.
  - `test_img_src_quote_forms_and_srcset`: `<img src='{{image:a}}'>`, `<img src={{image:b}} alt=x>`, `<img src="https://e.com/p.png" srcset="data:image/png;base64,AAAA 2x">` → first two get the notice (2 hidden); third keeps its https src and loses the `srcset`; no `base64` in output.
  - `test_css_urls_hidden_become_none_and_svgs_inline`: `.h{background:#fff url({{image:z}}) no-repeat}` → `.h{background:#fff none no-repeat}`, 1 hidden; `.l{background-image:url('{{ds-asset:4}}')}` with 4 in `svg_assets` → `url("data:image/svg+xml,…")`, 0 hidden.
  - `test_inline_style_background_in_html_is_hidden`: `<div style="background-image:url(data:image/jpeg;base64,/9j/)">` → `none`, 1 hidden.
  - `test_get_small_svg_assets_filters_scope_mime_and_size`: DS A with a 100-byte SVG (kept), a 20 KB SVG (excluded), a PNG (excluded), a TTF (excluded); DS B with an SVG (excluded when asking for A); `design_system_id=None` → `{}`.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_preview_images.py -v` — expected: FAIL (module/function not found).

- [ ] **Step 3: Implement** `src/utils/preview_images.py` and `get_small_svg_assets`. Regex over `<img\b[^>]*>` tags for the HTML side; `url\(\s*(['"]?)(.*?)\1\s*\)` for CSS. `urllib.parse.quote(text, safe=" =:/;,.-_()!*~")` gives the required encoding (it encodes `#%"'<>`).

- [ ] **Step 4: Run** `uv run pytest tests/unit/test_preview_images.py -v` — expected: PASS.

- [ ] **Step 5: Commit** `feat(mcp): preview images — raster notice, small SVGs as text`.

---

### Task 3: Preview assembler + real-deck measuring script

Models: test=opus impl=sonnet

**Files:**
- Create: `src/services/mcp_deck_preview.py`
- Create: `scripts/measure_mcp_preview.py`
- Test: `tests/unit/test_mcp_deck_preview.py`

**Interfaces:**
- Consumes: Task 1 (`strip_embedded_font_faces`, `google_fonts_imports`, `trim_css`), Task 2 (`hide_images_in_html`, `hide_images_in_css`, `IMAGE_NOTICE`), `SlideDeck.from_dict` / `to_html_document` (`src/domain/slide_deck.py:111`, `:539`).
- Produces:
  - `MAX_PREVIEW_SLIDES = 10`, `MCP_RESULT_BUDGET_BYTES = 150_000`
  - `@dataclass(frozen=True) class DeckPreview: html: Optional[str]; slides_shown: int; slides_total: int; images_hidden: int; note: str` with `def as_payload(self) -> dict` returning `{"included": html is not None, "slides_shown", "slides_total", "images_hidden", "note"}`.
  - `build_deck_preview(deck_dict: dict, *, title: Optional[str], deck_url: str, svg_assets: Mapping[int, str], max_html_bytes: int, max_slides: int = MAX_PREVIEW_SLIDES) -> DeckPreview` — `deck_dict` is the persisted snapshot with slide-number tokens already substituted and NO image/ds-asset substitution. Does not mutate `deck_dict`.
  - `ds_asset_ids_in(deck_dict: dict) -> set[int]` — every `{{ds-asset:N}}` id in slides' html and `css` **after** embedded font faces are removed (so font ids are never fetched).
  - `note` copy (exact): all shown → `Showing all {n} slides as a preview (standard fonts, images not shown). Open the full deck in tellr.`; some shown → `Showing {k} of {n} slides as a preview (standard fonts, images not shown). Open the full deck in tellr.`; nothing fits → `This deck is too large to preview here. Open the full deck in tellr.`; no slides → `This deck has no slides yet. Open it in tellr.` (`slide` singular when n == 1.)

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_mcp_deck_preview.py` (synthetic decks only):
  - `test_preview_caps_at_ten_slides_with_more_notice`: 14 tiny slides → `slides_shown == 10`, `slides_total == 14`; html contains `4 more slides — see full deck in tellr`; slide 11's unique text absent.
  - `test_preview_shows_every_slide_when_under_cap`: 3 slides → all three texts present, no "more slide" text; note == the "Showing all 3 slides…" copy.
  - `test_one_more_slide_singular`: 11 slides → `1 more slide — see full deck in tellr`.
  - `test_top_strip_links_to_deck_url`: html contains `preview — open the full deck in tellr` inside an `<a` whose `href="https://t.example/sessions/s1/edit"`; a `deck_url` containing `"` is attribute-escaped.
  - `test_scripts_only_for_shown_slides`: slide 0 script `new Chart('c0')`, slide 11 script `new Chart('c11')` → html contains `c0`, not `c11`.
  - `test_preview_drops_fonts_and_adds_google_import`: deck css with a `data:font/ttf;base64,…` DM Sans face → html has no `base64`, has `fonts.googleapis.com/css2?family=DM+Sans`.
  - `test_preview_of_inline_data_uri_deck_has_no_base64`: slides holding `data:image/png;base64,…` and a 15 KB base64 SVG, css with a base64 font → `"base64" not in html`, `images_hidden == 2`.
  - `test_budget_stops_before_the_slide_that_would_cross`: 6 slides of ~30 KB text each, `max_html_bytes=100_000` → `slides_shown` is the largest k whose html fits, `len(html.encode()) <= 100_000`, html has the "more slides" notice.
  - `test_budget_counts_utf8_bytes`: slides of `"é—😀" * N` sized so characters fit but UTF-8 bytes do not → fewer slides shown than a character count would allow.
  - `test_nothing_fits_gives_no_html`: one slide larger than `max_html_bytes` → `html is None`, `slides_shown == 0`, note == too-large copy.
  - `test_empty_deck`: `{"slides": []}` → `html is None`, note == no-slides copy.
  - `test_ds_asset_ids_skip_font_faces`: css `@font-face{src:url({{ds-asset:1}})}` + `.l{background:url({{ds-asset:2}})}` + slide `<img src="{{ds-asset:3}}">` → `{2, 3}`.
  - `test_input_deck_not_mutated`: deep-copy before, compare after.
  - `test_css_trimmed_to_shown_slides`: css `.only-on-slide-12{x:1}` dropped when slide 12 is not shown, kept when it is.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_mcp_deck_preview.py -v` — expected: FAIL.

- [ ] **Step 3: Implement `build_deck_preview`.** Order: strip embedded fonts from `css` → `google_fonts_imports` → hide images in css and in each slide's html. Then for `k` from `min(n, max_slides)` down to 1: build `SlideDeck.from_dict({...deck, "slides": first k, "css": imports + trim_css(css, shown html + shown scripts)}, title=title)`, `to_html_document()`, insert the top strip right after `<body>` and the more-slides notice (when `k < n`) before the trailing `<script>` block or `</body>`; return the first that fits `max_html_bytes`. Strip and notice are inline-styled `<div>`s (system-ui, 14px, dark `#1B3139` strip, white text, link colour `#FF5F46`); `deck_url` passes through `html.escape(..., quote=True)`.

- [ ] **Step 4: Implement `scripts/measure_mcp_preview.py`** (dev tool, not shipped behaviour): `uv run python -m scripts.measure_mcp_preview <file>... [--out DIR]`. Input: an HTML export (`SlideDeck.from_html_string(...).to_dict()`) or an MCP probe JSON (`body.result.content[0].text` → `deck`). Prints one line per file: original bytes, preview bytes, slides shown/total, images hidden; `--out` writes `<name>.preview.html`. `svg_assets={}` (inputs carry data URIs already). `deck_url="https://tellr.example/sessions/preview/edit"`, `max_html_bytes=MCP_RESULT_BUDGET_BYTES`.

- [ ] **Step 5: Run** `uv run pytest tests/unit/test_mcp_deck_preview.py -v` — PASS. Then the real-deck check (local only, never committed): `uv run python -m scripts.measure_mcp_preview ~/tellr-loop/easyjet---lakebase-sync-spend-risk-check--nov-2026-.html ~/tellr-loop/2026-11-17-mcp-agent-mode/probes/out-e2e/get_deck_17LLQ7.json ~/tellr-loop/2026-11-17-mcp-agent-mode/probes/out-e2e/get_deck_qh-mwL.json --out /tmp/preview-check` — expected: every preview < 60 KB, 0 `base64` in each output (`grep -c base64` → 0). Record the numbers in the ledger. If a file is missing, record that and continue.

- [ ] **Step 6: Commit** `feat(mcp): build the deck preview (≤10 slides, budgeted) + measuring script`.

---

### Task 4: MCP responses — links first, two content items, docs

Models: test=opus impl=sonnet

**Files:**
- Modify: `src/api/mcp_server.py` (tool decorators/descriptions; `_create_deck_impl` ~424; `_render_deck_response` ~567 replaced; `_get_deck_status_impl` ~677; `_edit_deck_impl` ~986; `_get_deck_impl` ~1087)
- Modify: `tests/unit/test_mcp_server.py` (every assertion on `deck`, `html_document`, `messages`; the three ds-asset tests at ~2702–2813 rewritten for the preview)
- Modify: `tests/integration/test_mcp_endpoint.py` (wire test)
- Modify: `docs/technical/mcp-server.md`, `docs/technical/mcp-integration-guide.md`

**Interfaces:**
- Consumes: Task 3 (`build_deck_preview`, `ds_asset_ids_in`, `DeckPreview`, `MCP_RESULT_BUDGET_BYTES`), Task 2 (`get_small_svg_assets`, `SVG_INLINE_MAX_BYTES`), `substitute_deck_slide_numbers`, `resolve_active_design_system_id`.
- Produces:
  - `@dataclass class McpToolReply: payload: dict; preview_html: Optional[str] = None` with `def to_content(self) -> list[TextContent]` — item 1 `json.dumps(payload, ensure_ascii=False, indent=2)`, item 2 `preview_html` verbatim when not None.
  - `_deck_links(session_id: str, base_url: str) -> dict` → `{"deck_url": …, "deck_view_url": …}` (the existing URL rules).
  - `_get_deck_status_impl(...) -> McpToolReply` (every branch); `_get_deck_impl(...) -> McpToolReply`; `_create_deck_impl` / `_edit_deck_impl` still return `dict`.
  - `get_deck_status` / `get_deck` tools: `@mcp.tool(..., structured_output=False)`, return `(await _impl(...)).to_content()`.

Payload key order (a contract; `list(payload)` is asserted):
- create/edit: `deck_url, deck_view_url, session_id, request_id, status`
- status pending/running/failed: `deck_url, deck_view_url, session_id, request_id, status, progress|error` (as today)
- status ready: `deck_url, deck_view_url, session_id, request_id, status, title, slide_count, preview, reply, deck_changed, replacement_info, metadata` — no `deck`, `html_document`, `messages`
- get_deck: `deck_url, deck_view_url, session_id, title, slide_count, preview`

Budget: serialize the payload once with `preview` holding the longest possible note and 6-digit counts, `max_html_bytes = MCP_RESULT_BUDGET_BYTES - len(item1.encode()) - 256`. SVG assets: `get_small_svg_assets(db, ds_asset_ids_in(deck), design_system_id=resolve_active_design_system_id(session_id), max_bytes=SVG_INLINE_MAX_BYTES)` inside `get_db_session()`. The MCP path no longer calls `substitute_deck_dict_images` / `substitute_deck_dict_ds_assets` (leave the functions; other callers use them).

Tool descriptions: `create_deck`/`edit_deck` say they return `deck_url` at once and the caller should show it; `get_deck_status`/`get_deck` say the response is a JSON part (links first) plus a second part that is a **preview** HTML of at most 10 slides with standard fonts and images not shown, that the full deck and all editing are at `deck_url`, and to show `deck_url` to the user.

- [ ] **Step 1: Write the failing tests.** In `tests/unit/test_mcp_server.py`:
  - Update existing ready/get_deck tests to `result.payload[...]` / `result.preview_html`, asserting the new key order with `list(result.payload) == [...]` and absence of `deck`, `html_document`, `messages`.
  - `test_create_deck_returns_links_first` and `test_edit_deck_returns_links_first`: `list(result)[:2] == ["deck_url", "deck_view_url"]`, values from `_deck_links`.
  - `test_pending_status_returns_links_first`.
  - `test_ready_status_includes_preview_even_when_deck_unchanged`: a `deck_changed: false` agent turn on a deck with slides → `preview_html` not None.
  - `test_get_deck_of_empty_deck_has_one_item`: `to_content()` length 1, `payload["preview"]["included"] is False`.
  - `test_whole_result_under_budget`: deck of 10 slides × 40 KB text → `sum(len(c.text.encode()) for c in reply.to_content()) <= 150_000`, links present in item 1.
  - Rewrite the ds-asset tests (old ~2702–2813) as `test_preview_inlines_scoped_small_svg_and_drops_fonts`, `test_preview_does_not_resolve_foreign_design_system_asset`, `test_preview_without_design_system_resolves_nothing`: font bytes' base64 never in `preview_html`; scoped small SVG appears as `data:image/svg+xml,`; a foreign/unscoped asset's bytes never appear; no `{{ds-asset:` left.
  - `test_deck_tools_have_no_output_schema`: `await mcp.list_tools()` → `outputSchema is None` for all four.
  In `tests/integration/test_mcp_endpoint.py`: `test_get_deck_returns_links_json_then_preview_html` — JSON-RPC `tools/call get_deck` (patch the session manager/permission like `test_permission_denied_on_other_users_deck`) → `result` has no `structuredContent`, `content` has 2 text items, `json.loads(content[0].text)` first key `deck_url`, `content[1].text` starts with `<!doctype html>` and contains `preview — open the full deck in tellr`.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_mcp_server.py tests/integration/test_mcp_endpoint.py -v` — expected: the new/updated tests FAIL.

- [ ] **Step 3: Implement** the `mcp_server.py` changes above.

- [ ] **Step 4: Update docs:** `docs/technical/mcp-server.md` (response shapes, the two content items, preview rules and copy, removed fields as a breaking change, the 150 KB / 10-slide limits) and `docs/technical/mcp-integration-guide.md` (Streamlit example renders `content[1].text`; the per-tool table at ~519).

- [ ] **Step 5: Run** `uv run pytest tests/unit/test_mcp_server.py tests/integration/test_mcp_endpoint.py tests/unit/test_preview_css.py tests/unit/test_preview_images.py tests/unit/test_mcp_deck_preview.py -v` — PASS; then `uv run pytest tests/unit -q -x -p no:cacheprovider` and compare failure causes with the pre-pass baseline.

- [ ] **Step 6: Commit** `feat(mcp)!: links first and a small preview instead of the full deck payload`.

---

## Order and parallelism

Tasks 1 and 2 are independent of each other; Task 3 depends on 1 and 2; Task 4 depends on 3. The chain runs them in order 1 → 2 → 3 → 4.

Outside the chain (the top-level does these after the PR is open): deploy the branch to a new devloop instance, run create → poll → ready and `get_deck` through the real MCP endpoint, record the whole `tools/call` response size and render the preview; put the numbers in the PR body.
