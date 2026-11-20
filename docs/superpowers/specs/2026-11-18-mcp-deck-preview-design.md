# Tellr MCP deck preview — design

Status: written 2026-11-18. The owner went autonomous mid-design ("start the build, I will
review tomorrow"), so the calls marked **[call]** were made without them; the rest is what they
decided in conversation.

## Intent

Genie One calls Tellr's MCP server to make a deck and wants to show the user a preview inside
Genie One. Today that is impossible, for two reasons the owner saw in a real Genie One thread:

1. **The response is huge.** A ready `get_deck_status` / `get_deck` reply was 196 KB on logfood
   and 2.1 MB on a devloop deck with a design system. Genie One keeps only the **first 180 KB of
   the whole tool result**, so the end was cut off.
2. **The link to the deck comes last.** `deck_url` is the final field, after the HTML, so it is
   the first thing a truncating client loses. `create_deck` returns no link at all, even though
   the session exists the moment it returns.

Genie One cannot render a `text/html` item. Its model **reads the HTML and retypes it** to show
it, so every byte of preview costs Genie One output tokens and time, and base64 is the worst
case: random characters, expensive to retype, and one wrong character breaks an image.

The fix: Tellr returns the link first and returns a **preview** of the deck — small by
construction, honest that it is a preview, and pointing at tellr for the real thing.

## Evidence (2026-11-18 spike, `/tmp/preview-spike/`, not committed)

A real 7-slide deck the owner exported (`easyjet---lakebase-sync-spend-risk-check--nov-2026-.html`,
1,016 KB; customer data, so **never commit it as a fixture**):

| Version | Size |
|---|---|
| Original | 1,016 KB |
| Embedded fonts removed, nothing else | 59 KB |
| + CSS rules that style nothing in the slides cut, CSS minified | 37 KB |
| + SVG logos as URL-encoded text instead of base64 | 34 KB |

978 KB of the original was 12 base64 TTF files (DM Sans / DM Mono). The slides themselves are
1–2.5 KB each. Rendered side by side, the 34 KB version is visually the same as the original
(layout, colours, cards, table, Chart.js chart, logos); with a Google Fonts link for DM Sans /
DM Mono even the type matches. The devloop e2e decks from PR #392 show the same shape: 3 slides →
2.1 MB, of which ~1 MB is fonts, sent twice (once in `deck.css`, once in `html_document`).

The spike's first CSS trimmer **broke the deck** (it treated a comment before `@import` as part
of a rule and swallowed `:root`), so the real trimmer must be conservative and tested against
real decks.

## Goals

- `create_deck` and `edit_deck` return `deck_url` and `deck_view_url` immediately.
- Every MCP response that names a deck puts the links first, where truncation can never reach
  them.
- A ready response carries a **preview** of the deck that is small by construction: no embedded
  fonts, no raster images, CSS cut to what the shown slides use, at most **10 slides**.
- The preview says it is a preview, in lowercase **tellr**, and points at the full deck.
- The whole tool result stays under **150 KB** (headroom under Genie One's 180 KB) for any deck.

## Non-goals

- Changing what the Tellr app shows, saves, exports or downloads. The preview exists only in MCP
  responses; persisted decks, the editor, `/view`, PPTX/Google Slides export and the app's HTML
  download are untouched.
- Server-side PNG thumbnails (would need a headless browser per call).
- Font subsetting / WOFF2 conversion (fonts are dropped from the preview instead).
- Making Genie One render HTML natively.
- Any change to Legacy (monolith) mode behaviour beyond what the shared response code gives it
  (`get_deck` can still read an old Legacy deck; it gets the same preview).

## Anti-goals (a failure even if it technically works)

- A preview that looks broken: lost backgrounds, serif fallback text, missing theme colours,
  broken image icons. A smaller preview that misrepresents the deck is worse than none.
- A runtime "shrink until it fits" ladder that degrades quality step by step. The owner wants the
  response small **by design**; the size measurement is only a safety net and a slide counter.
- Losing the links in any shape of response.
- Any base64 in the preview.

## What callers see

### Wire format **[call, from Genie One's suggestion]**

A ready `get_deck_status` and every `get_deck` return **two text content items**:

1. **Item 1 — JSON**, links first (key order is part of the contract):
   `deck_url`, `deck_view_url`, `session_id`, then the rest (below). No HTML in it.
2. **Item 2 — the preview HTML, raw** (a plain `text` item, not JSON-escaped, not a `text/html`
   resource — Genie One renders neither, and plain text is what every client reads).

When there is nothing to preview (a deck with no slides, e.g. a create turn where the architect
asked a question first) only item 1 is returned.

The tool result must not also carry `structuredContent` duplicating the payload (FastMCP will add
one if the tool gets an output schema — see Hazards).

### `create_deck`, `edit_deck`

Unchanged except two new keys, first: `deck_url`, `deck_view_url`, then `session_id`,
`request_id`, `status: "pending"`.

### `get_deck_status`

- Pending / running / failed: one JSON item, `deck_url` and `deck_view_url` first **[call]**, then
  the existing fields.
- Ready: item 1 carries `deck_url`, `deck_view_url`, `session_id`, `request_id`,
  `status: "ready"`, `title`, `slide_count`, `preview` (below), `reply`, `deck_changed`,
  `replacement_info`, `metadata` (unchanged sub-keys). Item 2 is the preview HTML.
- **Removed:** `deck` (the structured per-slide copy — owner decision), `html_document` (the HTML
  now travels as item 2), `messages` (the turn transcript; `reply` already carries the answer —
  **[call]**, the owner did not object when it was proposed).
- **[call]** A ready turn carries the preview item whenever the deck has slides, including a turn
  with `deck_changed: false` (the architect answered or asked instead of editing). MCP is
  stateless, so Tellr cannot know whether the caller still holds an earlier preview, and the owner
  asked for the link and the HTML every time. (An earlier draft omitted it on unchanged turns; the
  builder check showed why that was wrong.)

### `get_deck`

Item 1: `deck_url`, `deck_view_url`, `session_id`, `title`, `slide_count`, `preview`. Item 2:
the preview HTML (always, when the deck has slides).

### The `preview` object (in item 1)

`included` (bool — whether item 2 is present), `slides_shown`, `slides_total`, `images_hidden`
(count of images replaced by the notice), `note` (a one-line human sentence the calling model can
repeat, e.g. "Showing 10 of 14 slides as a preview; open the full deck in tellr."). Exact naming
is the builder's, but it must let a caller tell the user, without parsing HTML, that this is a
partial preview.

### Tool descriptions

Each tool's description must say the HTML is a **preview** (standard fonts, images not shown, at
most 10 slides) and that the full deck — and all editing — is at `deck_url`. The model reading
the description must be told to show `deck_url` to the user.

## The preview HTML

Built from the deck **as Tellr serves it today** (the same snapshot `_render_deck_response` uses,
after slide-number tokens), but with these rules. The builder decides the module and pipeline;
the rules are the contract.

1. **Slides:** the first slides in deck order, **at most 10** (owner decision), and only whole
   slides. Each shown slide keeps its own scripts (Chart.js etc.); scripts of slides not shown are
   dropped. If slides are left out, the preview ends with a notice:
   "N more slides — see full deck in tellr" (linked to `deck_url`).
2. **Size safety net:** the whole tool result (item 1 + item 2, UTF-8 bytes) must not exceed
   150 KB. Slides are added in order while they fit; a slide that would cross 150 KB stops the
   preview there (and the "N more slides" notice says so). This is a measurement, not a ladder —
   nothing else about the preview changes with size. If not even the first slide fits, item 2 is
   omitted and `preview.note` says the deck is too large to preview. **150 KB is a hard ceiling,
   not a target:** the owner chose the 10-slide cap over a smaller byte budget (e.g. 40 KB), so
   there is no soft target and no per-slide budget. A typical 10-slide preview lands around
   35–60 KB (spike: 7 slides → 34 KB) and never comes near the ceiling.
3. **Top strip:** the preview starts with a slim strip: "preview — open the full deck in tellr",
   linking to `deck_url`. Lowercase "tellr" everywhere in preview copy (owner decision).
4. **Fonts:** no embedded font data. Every `@font-face` whose `src` is a `data:` URI or a
   `{{ds-asset:ID}}` handle is removed. **[call]** For each removed family, add a Google Fonts
   `@import` (one per family, so an unknown family's 400 can't spoil the rest), asking for the
   weights/styles the removed rules declared. Where the viewer blocks it, text falls back to the
   deck's own font stack (`'DM Sans', system-ui, …`), which the spike showed still looks right.
   `@font-face` rules that already point at an `https:` URL and existing `@import`s stay.
5. **Raster images are never embedded.** Every image that is not a small SVG — `{{image:ID}}`
   handles, `{{ds-asset:ID}}` handles that resolve to a raster type, and any `data:image/...` URI
   already present in slide HTML or CSS — is replaced by a notice that reads
   **"image not shown in preview, see full deck in tellr"** (owner's wording, lowercase). For an
   `<img>`, the notice keeps the image's box (size and position) so layout holds — e.g. a light
   grey box with the sentence, as a tiny inline SVG `src` or a sized element; the builder chooses.
   **[call]** For a raster CSS `url()` background, the `url()` is dropped (no notice drawn): the
   rule's background colour, gradient or anything else stays, so the slide keeps its ground
   (the anti-goal's "lost backgrounds" is about colours and theme, which this keeps). It still
   counts in `images_hidden`, so `preview.note` can say images were left out. Image bytes are
   never read from the database for a raster image the preview will not show — both
   `image_assets` and `design_system_asset` carry `mime`, so the decision needs no byte read.
6. **SVG logos and icons [call]:** an SVG asset of at most ~10 KB (decoded) is inlined as
   URL-encoded text (`data:image/svg+xml,…`, with `#` and quotes escaped — the spike broke logos by
   leaving `#` raw), not base64. Larger SVGs are treated as images (rule 5). Inline `<svg>` markup
   already in a slide is left alone. This covers design-system assets and SVG `data:` URIs already
   in the deck; `{{image:…}}` library handles always get the notice, even when the image is an
   SVG, so the preview never reads the image library (and never needs its ephemeral-image privacy
   guard) — **[call]**, made at plan time.
7. **CSS [call]:** comments removed, whitespace minified, and rules dropped only when they
   **certainly** style nothing in the shown slides: a rule goes only if one of its selectors' class
   or id names appears nowhere in the shown slides' HTML **or scripts**. `:root`, custom
   properties, `@keyframes`, `@import`, element selectors and anything the trimmer cannot
   classify are kept. `@media` / `@supports` are trimmed recursively. When in doubt, keep.
8. **External scripts** (the Chart.js CDN tag) stay as they are; they cost a few bytes.
9. **Escaping:** the existing `to_html_document` XSS guards (title escaping, `</style>` stripping,
   http(s)-only script srcs) still apply to the preview.

## Hazards in the current code the builder must close

- **Duplicated payload.** `_render_deck_response` returns the deck twice (`deck` and
  `html_document`). Both go.
- **FastMCP `structuredContent`.** With mcp 1.27, `convert_result` emits structured content too
  whenever the tool has an output schema, which would duplicate the whole response. Today the
  wire shows none (`-> dict`); returning a list of content items or a `CallToolResult` must keep
  it that way. A test must assert the serialized `tools/call` result has no `structuredContent`
  copy of the preview.
- **Image bytes read for nothing.** `substitute_deck_dict_images` reads every image blob; the
  preview path must not.
- **Tests and docs that pin the old shape:** `tests/unit/test_mcp_server.py` (and any other test
  reading `html_document` / `deck` / `messages` from an MCP response), `docs/technical/mcp-server.md`,
  `docs/technical/mcp-integration-guide.md` (its Streamlit example renders `html_document`).

## Constraints

- No Legacy-engine changes (Legacy mode is frozen; this is MCP response code shared by both).
- No new dependencies **[call]** (Pillow is not needed now that images are never re-encoded; no
  fontTools). If the builder finds a CSS parser genuinely necessary, it goes in
  `packages/databricks-tellr-app/pyproject.toml` and the root `pyproject.toml` via `uv lock`.
- The preview is computed per call; it must stay cheap (no DB reads of raster image bytes, no
  browser). A few milliseconds of string work is fine.
- Breaking change for MCP callers (fields removed/moved). PR #392's MCP changes are unreleased
  and already breaking, so this ships in the same release. The PR's `## What's new` gets one user
  bullet (Genie One / vibe previews and the link arriving straight away).

## Left to the builder

- Module layout (e.g. a `deck_preview` service), and whether the preview is built from the deck
  dict or from `SlideDeck`.
- The exact notice/strip markup and styling, and the exact `preview` key names.
- How the 150 KB check is computed (it must count what goes on the wire: both items' text).
- How content items are returned from FastMCP (list of `TextContent` or `CallToolResult`), as long
  as the hazard above is covered.

## How we'll know it works

- **Unit tests** on synthetic decks (never the easyJet file): fonts gone, Google Fonts import per
  family, raster images replaced by the exact notice, small SVG inlined as text, large SVG
  replaced, CSS trimmer keeps `:root`/vars/`@media`/element rules and survives a comment before
  `@import`, 10-slide cap + "N more slides" notice, 150 KB stop, scripts only for shown slides,
  links first in item 1, no `structuredContent` duplicate, `create_deck`/`edit_deck` carry links.
- **Local real-deck check:** run the preview builder over the easyJet export (from
  `~/tellr-loop/`, never committed) and over the PR #392 e2e decks in
  `~/tellr-loop/2026-11-17-mcp-agent-mode/probes/out-e2e/`; record sizes; render original vs
  preview and compare by eye (the spike's side-by-side method).
- **Devloop:** deploy the branch to a new devloop instance; through the real MCP endpoint run
  create → poll → ready and `get_deck` on a design-system deck with several slides (and one with an
  AI-generated or uploaded image if image generation is available there); record the **whole
  `tools/call` response size**, check links come first, the preview renders, and the result is
  under 150 KB. Results go in the PR body.
- **Genie One** is connected to logfood's Tellr, not to a devloop, so the live Genie One check
  waits for a release; the owner does it.
