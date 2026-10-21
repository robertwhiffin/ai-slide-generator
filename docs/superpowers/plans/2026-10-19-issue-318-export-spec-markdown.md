# Export the deck spec as Markdown (#318) — Implementation Plan

> **For agentic workers:** load `superpowers:subagent-driven-development` **and** `executing-plans-tellr`
> (repo CLAUDE.md). Run the §2 plan-vs-code pre-pass before Task 1. Steps use `- [ ]` checkboxes.

**Date:** 2026-10-19
**Branch:** `feat/318-export-spec-markdown` (off `origin/main` 679d2f21). Worktree:
`/Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-318`. **Commits:** the supervisor commits each
reviewer-approved task (conventional message ending with `Co-authored-by: Isaac <no-reply@databricks.com>`); sub-agents never commit.
Nobody pushes unless the user asks.
**Revision:** r2 (2026-10-19) applies the supervisor's rulings on `~/tellr-loop/issues/issue-318/PLAN-REVIEW.md` (findings 1–20).
**Issue:** robertwhiffin/ai-slide-generator#318. No separate spec doc; the binding authority is the issue's
acceptance criteria plus the *Decisions* below. Decisions made without the author are review points (marked **[review]**).

## Goal

The Spec view gets an **Export spec as Markdown** action. It downloads a deterministic `.md` rendering of the deck spec
the view is showing. The renderer is a pure frontend function of `DeckSpec`. A checked-in golden pair
(`full.deck-spec.json` → `full.md`) pins its exact bytes, so a later backend or MCP renderer has a cross-language contract.

## Acceptance criteria (from the issue) and how each is met

| # | Criterion (verbatim) | How it is met | Proved by |
|---|---|---|---|
| AC1 | An "Export spec as Markdown" action in the Spec view downloads a `.md` rendering of the current deck spec. | A button in the Spec view header, accessible name `Export spec as Markdown` (Task 6). It calls `renderDeckSpecMarkdown` (Task 3) and `downloadTextFile` (Task 5). The file is named `<title-slug>-spec.md` with MIME `text/markdown;charset=utf-8`. It reads the spec the view is currently showing. | `SpecView.test.tsx` → *downloads exactly the rendered spec, named after the spec title* and *the export follows the deck* (Task 6); `spec-view.spec.ts` → *Export spec as Markdown downloads the rendered spec* and *a read-only viewer can export the spec* (Task 7, real browser download compared byte-for-byte with `full.md`). |
| AC2 | Rendering is deterministic and covers every `DeckSpec` / `SlideSpec` field users see in the Spec view. | **Determinism:** no clock, locale or randomness; fixed section order; LF only; one trailing newline (Task 3). **Coverage:** every field the Spec view shows is rendered, plus the title and the plan content it doesn't show. Only `template_section_index` is omitted, with a stated reason (Decision 2). | `deckSpecMarkdown.test.ts` → golden equality, *render twice*, *shuffled keys*, *fake clock*, *no locale grouping* (Task 3). `deckSpecMarkdownCoverage.test.tsx` has two guards (Task 4). The **field-classification guard** reads `src/domain/deck_spec.py`. The **Spec-view parity guard** checks that every piece of text the Spec view shows appears in the Markdown. |

## Context (verified 2026-10-19 against 679d2f21)

- **Models.** `src/domain/deck_spec.py` declares five `BaseModel` classes: `DesignContractRef` :26, `ResolvedFigure` :59,
  `ResolvedData` :65, `SlideSpec` :71 and `DeckSpec` :108.
  - `DeckSpec` fields: `title, audience, purpose, argument, call_to_action, narrative_arc: list[str], design_contract, resolved_data, slides: list[SlideSpec]`.
  - `SlideSpec` fields: `position: int, purpose, content_brief, assumes, hands_off, data_references: list[str], slide_type: Optional[str], template_section_index: Optional[int]`.
  - Validators: H1 non-empty title, L1, L3, unique positions. **No model change in this plan.**
- **TS mirror.** `frontend/src/types/slide.ts` :43–98, with `SlideDeck.deck_spec?: DeckSpec | null` at :133.
  - Guard: `frontend/src/services/__tests__/deckSpecConformance.test.ts`. It reads the `.py` file as text with
    `pythonClassBody` :103 and `pythonModelFields` :117 (both local functions today), plus `tsInterfaceFields` :131 and `MIRRORS` :84.
- **SpecView** (`frontend/src/components/SpecView/SpecView.tsx`).
  - Its header comment :1–31 states three properties: (1) read-only is structural; (2) ids, never compiled style (L3); (3) the view is a hint, never a mode.
  - `spec = slideDeck?.deck_spec ?? null` :71. There is no spec fetch.
  - The header's right-hand group holds the read-only hint and **Discuss** (`spec-discuss`) at :108–120.
  - Rendered: deck fields via `SpecField` :53 (`<dt>` label, `<dd>` value), the narrative arc `<ol>` :157 (as given), the
    design-contract ids :175–198 (`Design system #N`, `Template #N`, `Slide style #N`, or `No design system or slide style pinned`)
    and per-slide briefs :204–244 (as given, **not sorted**; label `Slide {position + 1}` :214; purpose, brief,
    `Assumes:`, `Hands off:`).
  - **Not rendered:** `title`, `resolved_data`, `data_references`, `slide_type`, `template_section_index`.
  - Values sit in elements with default `white-space: normal`, so an embedded newline displays as a space.
- **Mounting.** `AppLayout.tsx:1365` mounts `<SpecView slideDeck={displayDeck} …/>`. `displayDeck` (:843) is the save-point preview
  deck while previewing, else the live deck.
- **A save-point preview never carries `deck_spec`.** `AppLayout.tsx:735–737` sets the preview deck from `api.previewVersion`, i.e.
  `GET /api/slides/versions/{n}` (`slides.py:877`). That runs `session_manager.get_version` (:2653), which returns
  `json.loads(version.deck_json)` (:2681) as `"deck"` (:2719) and never adds `deck_spec`.
  - `deck_json` comes from `SlideDeck.to_dict()` (`src/domain/slide_deck.py:502`), which has no `deck_spec` key. The version's own
    `deck_spec_json` snapshot is used only by restore.
  - So while previewing, the Spec view shows its empty state, and the export button (hidden without a spec) is absent.
- **Read-only viewers see the spec.** `spec-view.spec.ts:640` (*someone on the read-only route sees the spec*). The spec rides
  `get_slides` (`src/api/routes/slides.py:114`, CAN_VIEW gate :133).
  - By contrast, the page header hides the **deck** Export menu on `/view` (`page-header.tsx:65`, :162; Present too, :262).
  - `docs/technical/url-routing.md:275` is stale: it lists `viewer-readonly.spec.ts` as 4 tests with "export available". The spec has
    5 tests, and none tests export. Task 8 fixes it.
- **Unvalidated JSON.** `_read_deck_spec` (`src/api/services/session_manager.py:168`) is `json.loads` without `DeckSpec` validation, and
  `_rewrite_deck_spec_slides` (`chat_service.py:3846`) deliberately carries through entries that no longer validate (e.g. a
  non-int `position`). The frontend can therefore receive:
  - specs missing the newer optional keys (`slide_type`, `template_section_index`), which must be treated like null;
  - specs missing fields the Spec view never reads (`resolved_data` and its parts, `data_references`), which the renderer defaults
    (Task 3);
  - non-integer numeric slots, which the renderer escapes (D4).
  - Today's writers all supply full specs: the architect via `DeckSpec`, `_BLANK_DECK_SPEC_ENTRY` (`chat_service.py:71`) and the tour fixture.
- **MCP.** The MCP server never exposes the spec: `src/api/mcp_server.py` has no `deck_spec` reference; `_get_deck_impl` is at :1069.
- **No reusable download helper exists.** `frontend/src/hooks/useDeckExport.ts` has two inline closures, :65–76 (PPTX) and :154–162 (HTML).
  Both revoke the object URL synchronously after `click()`.
  - The HTML path's Playwright test (`frontend/tests/e2e/export-ui.spec.ts:535–543`) asserts only `suggestedFilename()`.
  - No in-repo test reads download *content* after a synchronous revoke, so this plan defers the revoke (D7).
- **jsdom and vitest facts (probed 2026-10-19 under vitest).**
  - `URL.createObjectURL`/`revokeObjectURL` are **undefined**.
  - The jsdom `Blob` has **no `.text()`**, but `FileReader.readAsText` works.
  - jsdom's FileReader dispatches through `setImmediate` (`jsdom/lib/jsdom/living/file-api/FileReader-impl.js:76`). Default
    `vi.useFakeTimers()` therefore **stalls** it, while `vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })` leaves it
    working and still drives `setTimeout`.
  - `mdast-util-from-markdown` imports and parses under vitest's jsdom environment.
- **Parser availability.**
  - `mdast-util-from-markdown@2.0.3` (micromark 4.0.2, 100% CommonMark, no GFM) is installed. It is reached via `react-markdown`
    (a direct dependency) → `remark-parse`, and its lockfile entry is not `dev`.
  - `marked@14.0.0` comes in via `monaco-editor`. It is not a strict CommonMark parser.
- **The local npm registry is the Databricks proxy.** `npm config get registry` returns `https://npm-proxy.cloud.databricks.com/`. The
  committed lock has 0 proxy URLs and only `registry.npmjs.org` ones.
  - `npm install <pkg>` re-resolves the package to latest (`mdast-util-from-markdown` → 2.1.0) and writes proxy `resolved` URLs.
    A GitHub runner cannot reach that host, and it is an internal hostname in a public repo.
  - The hand-edit procedure in Task 3 was verified by the plan review: npm 11 leaves the diff at exactly two lines, and npm 10.9.9
    `npm ci --dry-run` passes.
- **Escaping prototype (inline node, re-run 2026-10-19 for r2).** The Task 3 escaper (with `@`, explicit whitespace and control sets, and
  `num`) was run over the 49 HOSTILE values × 10 slots. Every case produced only `root/heading/paragraph/text/list/listItem/strong`
  nodes, an unchanged block skeleton and a round-tripped text: 0 failures out of 490. Each listed escaper sabotage goes red.
  - The golden in Task 2 was generated by that prototype and re-parsed. Its heading sequence is `1,2×7,3×3,2,3×3`.
  - It has no `\r`, no trailing whitespace and exactly one trailing newline, and renders identically with every object's keys reversed.
- **Lint and CI.**
  - Repo-wide `npx eslint .` reports 63 errors and 9 warnings (pre-existing; 6 of them in `src/services/api.ts`). Every file this plan
    touches is lint-clean today, so lint **touched files only**.
  - eslint's `no-control-regex` fires on a `\u0000-\u001F` class but not on `\t\n\v\f\r` escapes (verified).
  - CI: Node `'20'` (`.github/workflows/test.yml:12`); the vitest job `frontend-unit-tests` (:603–625, `npm run test:unit` after `npm ci`);
    `spec-view` is in the E2E matrix (:732); backend runs `pytest tests/unit` (:136).
  - `tsc -b` typechecks `src/**` excluding `*.test.*` (`tsconfig.app.json`) and `tests/**/*.ts` (`tsconfig.e2e.json`).
- **Local baseline (2026-10-19, Node 26.12 / npm 11.20).**
  - `npx vitest run`: `3 failed | 28 passed` files and `20 failed | 1145 passed` tests. All 20 have one cause — *Cannot read
    properties of undefined (reading 'clear')* (Node 26's global `localStorage` shadowing jsdom's) — in
    `FindingsE2.test.tsx`, `SlideViewer.test.tsx` and `TourViewerBridge.test.tsx`. CI on Node 20 is green.
  - `npx tsc -b`: clean.
  - SpecView, deckReviewFlag and conformance suites: 40/40 green.
  - `uv run pytest tests/unit/test_deck_spec.py -q`: 49 passed.

## Decisions

### D1. Frontend-only rendering; no endpoint

The deck spec is rendered in the browser, from the `deck_spec` the Spec view already holds, by the pure function
`renderDeckSpecMarkdown(spec: DeckSpec): string`. There is no new route, no request, and no backend state.

- **WYSIWYG.** The export must be "the current deck spec": what the view shows. The file is computed at click time from the exact
  object the view renders, so the two cannot disagree, including mid-turn when the deck has just been replaced.
  - A save-point preview shows **no** spec today, because preview snapshots don't serve `deck_spec` (Context). The button is hidden there.
  - Making previews carry their spec is a backend follow-up (Out of scope). Once it lands, the frontend export follows automatically.
- **It preserves SpecView's stated design.** "There is no spec endpoint and no spec fetch" (SpecView.tsx:4–5). A fetch on click would be
  the first one.
- **It adds no permission surface.** The spec already reaches every CAN_VIEW reader through `get_slides`. An endpoint would need
  its own CAN_VIEW gate and route tests, duplicating one that `spec-view.spec.ts:652` already pins.
- **Multi-worker state is not the deciding factor.** A DB-reading endpoint would be multi-worker safe. Nothing here is cached in-process,
  and the frontend path has no server state at all.
- **MCP has no spec surface today.** So no consumer is blocked.
  **Follow-up, out of scope:** a Python `render_deck_spec_markdown(spec: DeckSpec) -> str` (e.g. in `src/domain/`) for an MCP tool
  or route. Its contract: reproduce `frontend/tests/fixtures/deck-spec-markdown/full.md` byte-for-byte from
  `DeckSpec.model_validate(full.deck-spec.json)`, with the same field classification (D2) and escaping rules (D4,
  documented in `docs/technical/export-features.md`). Task 2's Python test already keeps the fixture a valid `DeckSpec`.

**Who can export.** **[review]** Anyone who sees a spec in the Spec view, including the read-only `/view` route and a
non-lock-holder. This follows §7.5 "spec visibility rides deck visibility — nothing extra granted, nothing extra withheld". The export
carries nothing the viewer's browser does not already hold (the full `deck_spec` object is in the `get_slides` response).
The page header hides deck exports on `/view` (page-header.tsx:65), but that is a UI simplification (it also hides Present, :262), not a
data rule. If the author wants parity with the header, the change is to add a SpecView prop and gate the button. That is not view
state, so property 3 is not affected. See also D2's **[review]** on the Data section.

### D2. Field coverage

The export is the **spec**, not the deck. Nothing from `SlideDeck` other than `deck_spec` is read. In particular `css`, slide HTML,
findings and verification are never read. The renderer's signature takes a `DeckSpec`, so it structurally cannot read `css`
(L3). A test still proves it (Task 6).

| Field | Spec view shows it? | Markdown rendering | Why |
|---|---|---|---|
| `DeckSpec.title` | no (page header shows the session name) | `# {title}`; `# Untitled deck spec` if blank | A standalone document needs a heading; the same string drives the filename (D6). |
| `audience` | yes (`spec-audience`) | `## Audience` + paragraph | AC2 |
| `purpose` | yes | `## Purpose` + paragraph | AC2 |
| `argument` | yes | `## Argument` + paragraph | AC2 |
| `call_to_action` | yes, label "Call to action" | `## Call to action` + paragraph | AC2 |
| `narrative_arc` | yes, `<ol>` as given | `## Narrative arc` + `1. …` list in given order; `None.` if empty | Order is meaning (SpecView.tsx:151–153). |
| `design_contract` | yes | `## Design contract` + bullets | container |
| `DesignContractRef.design_system_id` | yes, `Design system #N` | `- Design system #N` (same words as the Spec view) | AC2; ids, never compiled content (L3) |
| `.template_id` | yes, `Template #N` | `- Template #N` | AC2 |
| `.slide_style_id` | yes, `Slide style #N` | `- Slide style #N` | AC2 |
| (all three null) | `No design system or slide style pinned` | the same sentence as a paragraph | Spec-view parity |
| `resolved_data` | no | `## Data` (after `## Slide briefs`) | It is the plan's evidence and its known holes. A reviewer outside the app needs it to judge the plan. **[review]** (below). |
| `ResolvedData.synthesis` | no | `### Synthesis` + paragraph | as above |
| `.figures` | no | `### Figures` + `- {key}: {value} (source: {source})`; `None.` if empty | Slide `data_references` name these keys. |
| `ResolvedFigure.key / value / source` | no | as above | as above |
| `.gaps` | no | `### Gaps` + bullets; `None.` if empty | The plan's admitted gaps. |
| `slides` | yes, as given | `## Slide briefs`, then `### Slide {position+1}` per slide **in the given order** (not sorted); `None.` if empty | Matches SpecView.tsx:205 and the pinned ordering tests (SpecView.test.tsx:199–220). |
| `SlideSpec.position` | yes, `Slide {position+1}` | the `### Slide N` heading, N = `position + 1` when `position` is an integer. Otherwise `### Slide {escapeText(position)}`: the escaped raw value, no arithmetic, so `'<b>x</b>'` gives `### Slide \<b\>x\</b\>` and null gives `### Slide Not set.` | 1-indexed, as in the Spec view. The non-integer case is reachable only through unvalidated JSON. It deliberately does not copy SpecView's JS coercion (`'<b>x</b>' + 1`), which a cross-language contract cannot reproduce. |
| `purpose` | yes (unlabelled) | `- **Purpose:** …` | AC2; labelled for a standalone reader |
| `content_brief` | yes (unlabelled) | `- **Content brief:** …` | AC2 |
| `assumes` | yes, `Assumes:` | `- **Assumes:** …` | AC2 |
| `hands_off` | yes, `Hands off:` | `- **Hands off:** …` | AC2 |
| `slide_type` | no | `- **Slide type:** …` when non-null; line **omitted** when null or absent | The design system's own name for the bound layout (`data-label`); user-meaningful. |
| `data_references` | no | `- **Data references:** a, b`; `None.` if empty | Ties each slide to its figures. |
| `template_section_index` | no | **omitted** | A 0-based machine binding index into the pinned template. `slide_type` carries the same binding by its human-facing `data-label`, and the two are validated as a pair (`invalid_slide_bindings`, `src/services/template_sections.py:458`). A bare `0` next to a 1-based "Slide 1" misleads. |

Empty scalar (after whitespace normalisation) → `Not set.` Empty list → `None.` Both are constants, never escaped.

A field the Spec view never reads may be absent in unvalidated JSON (Context). The renderer then defaults it:
- `resolved_data` defaults to `{}`, then `synthesis` to `''`, and `figures` and `gaps` to `[]`;
- `data_references` defaults to `[]`;
- so absent parts render `Not set.`/`None.` and never throw.

There is deliberately no tolerance for a missing `narrative_arc` or `slides`: SpecView itself requires them (SpecView.tsx:158, :205).

**[review] The Data section is exported, including `source`, for everyone who can see the Spec view (option a — supervisor ruling).**
- **Why:** sources are what a reviewer outside the app needs to check the figures. Every viewer already receives them in the
  `get_slides` JSON. The exporting user chooses whom to share the file with.
- **What it means:** the file carries values no UI surface shows. `source` holds warehouse identifiers (the fixture uses
  `warehouse.renewals`), and `synthesis`/`gaps` are architect notes.
- **Alternatives for the author:**
  - (b) omit `source`;
  - (c) omit `## Data` on `/view`, which needs the gating prop D1 describes.

**Known ambiguities (accepted, documented in Task 8).**
- A user value that is literally `None.` or `Not set.` reads the same as the placeholder.
- Data references are joined with `, `, and figures are rendered as `- {key}: {value}`. Both are ambiguous when a value itself
  contains `, ` or `: `.
- The structure (list items, headings) stays unambiguous; only the human reading of these lines is.

### D3. Guards: a field cannot be added and left out silently

Both guards live in `frontend/src/services/__tests__/deckSpecMarkdownCoverage.test.tsx` (Task 4). Both are behavioural.

**(a) Field-classification + mutation guard.**
- A `COVERAGE` table maps every model to every field: `'rendered'` or `{ excluded: '<reason>' }`.
- The test reads `src/domain/deck_spec.py?raw` with the shared Pydantic-source reader (Task 1, extracted from the conformance test so
  both guards parse identically). It asserts:
  1. the `BaseModel` classes in the file equal the keys of `COVERAGE`, and equal the keys of an `INSTANCES` accessor map over the golden fixture;
  2. for each class, the Python field set equals the `COVERAGE` keys (both directions);
  3. every fixture instance carries every Python field as an own key (so optional fields are present as `null`);
  4. **behaviour**, per leaf field per instance:
     - mutate a deep clone, choosing the mutation from the **Python annotation** (`str`/`Optional[str]` → sentinel; `int`/`Optional[int]` →
       `900000`; `list[str]` → append sentinel; `list[Model]` → `[]`);
     - a `'rendered'` field must change the output (and, for string-typed mutations, the parsed text must contain the sentinel);
     - an `excluded` field must leave the output **byte-identical**;
     - a bare-model field (`design_contract`, `resolved_data`) is `'rendered'` iff at least one of its model's fields is;
     - an unknown annotation throws ("extend the guard"), so the guard fails closed.

  New Python field → step 2 red. Marking a field rendered without rendering it → step 4 red. Starting to render an excluded field → step 4 red.

**(b) Spec-view parity guard.**
- Render `<SpecView>` and the Markdown from the **same** spec, over three fixtures: the golden; an "empty" spec (no contract ids, empty
  arc/slides/figures/gaps); and a slide-style-only spec.
- Collect the Spec-view text, excluding the header (`spec-view-header`, which holds controls, not spec content):
  - every element with no element children contributes its `textContent`, normalised with the test-side `normaliseText`, which
    restates D4's code-point sets independently of production code;
  - every direct non-blank text node of an element that has element children contributes too.
- Each text must appear, as a letter/number-bounded match, in some heading or paragraph text of the parsed Markdown.
- Anything added to the Spec view goes red until the export carries it, including labels ("Narrative arc", "Assumes:") and
  empty-state sentences. No `data-testid` is hand-picked.
- A precondition test pins that the collected set includes the audience value, `Slide 4` and `Design system #7`, so a broken
  collector cannot pass vacuously.

### D4. Escaping and multi-line values

- **Multi-line values are collapsed to one line.** Each value goes through three steps, with the sets defined by explicit code
  points rather than a regex `\s`, because JS and Python `\s` differ:
  1. **Remove** the control characters U+0000–U+0008, U+000E–U+001F, U+007F–U+0084 and U+0086–U+009F.
  2. **Collapse** every run of these whitespace characters to one U+0020:
     - U+0009–U+000D (tab, LF, VT, FF, CR);
     - U+0020, U+0085 (NEL, a line break, so it becomes a space rather than being deleted), U+00A0 and U+1680;
     - U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000 and U+FEFF.

     This is ECMAScript's `\s` plus NEL.
  3. **Trim.**
  - The Spec view already displays values this way (`white-space: normal`).
  - Every value then occupies exactly the line it starts on, which rules out setext underlines, lazy continuation, blank-line paragraph
    splits, indented code and table delimiter rows by construction.
  - Trade-off: a brief's intended line structure is flattened in both views. Changing that is a follow-up that must change both views together.
- **Backslash escaping** (CommonMark §2.4: any ASCII punctuation may be backslash-escaped):
  1. Everywhere: `` \ ` * _ [ ] < > # | ~ $ & @ ``.
     - These kill code spans, emphasis, links/images/reference definitions, autolinks/raw HTML, entity references, ATX
       closing sequences and blockquotes.
     - They also kill the GFM/GitHub-only table, strikethrough and math syntax, and `@` mentions. `\@` stops a pasted file from
       pinging people in a GitHub issue or PR. A CommonMark parser cannot see these, so they are pinned by their escape (the one
       string-match test, in Task 3).
     - `\` itself must be escaped, or an input backslash pairs with an inserted one (`\[x](y)` would become a link).
  2. At the start of a value, after step 1: a leading `-`, `+` or `=` gets a backslash (lists, thematic breaks, setext). A leading ordered
     marker `^\d{1,9}[.)]` followed by a space or end of string gets its `.`/`)` escaped (`2024\. A year`; `11.4%` is untouched).
  - These rules apply uniformly to every value in every position (H1, paragraph, list-item start, after a label), so no
    position-specific escaper exists to get wrong.
- **Numeric slots are values too.** `num(n)` returns `Number.isInteger(n) ? String(n) : escapeText(n)`.
  - Ids use it: `- Design system #{num(id)}`.
  - A slide heading is `### Slide {position + 1}` only when `position` is an integer, and `### Slide {escapeText(position)}` otherwise (D2).
  - With unvalidated JSON (Context), a string `position` such as `'<b>x</b>'` therefore yields inert text, not raw HTML.
- **Accepted, out of scope:**
  - GFM viewers may auto-link bare URLs/emails in values. The visible text is unchanged and the link target equals the text, so no
    hidden-target link can be injected.
  - `:emoji:` shortcodes and Unicode bidi/format characters pass through.
- **Tests parse the output** with `mdast-util-from-markdown` (D9). They assert:
  - the block skeleton is unchanged against a benign baseline;
  - node types stay within `root|heading|paragraph|text|list|listItem|strong`;
  - the bold-label set is unchanged;
  - the text round-trips.

  They do not string-match escapes, except for the GitHub-only characters `|`, `~`, `$` and `@`.

### D5. Determinism

- Same input → same bytes. There is no `Date`, no `toLocale*`/`Intl`, and no randomness. Integer ids and positions are rendered with
  `String(n)` via `num` (D4), never with locale formatting.
- **Fixed section order** (D2). Object keys are read by name, never by iteration.
- `narrative_arc` and `slides` keep their **given** order, matching SpecView.
- Blocks are joined by exactly one blank line. LF only, no trailing whitespace, no leading whitespace on any line, and exactly one
  trailing `\n`.
- **No generated-at line, version, session id or URL.** Each would break byte-identity (and leak ids); the file's mtime already records
  when it was exported.
- The renderer does not mutate its input (a deep-frozen spec renders).

### D6. Filename

`deckSpecMarkdownFilename(title)` → `<slug>-spec.md`, where:

- slug = `title.toLowerCase().normalize('NFC')`, with every run of characters outside `\p{L}\p{N}\p{M}` replaced by `-` and
  leading/trailing `-` stripped. Then it is cut to **60 code points** with `Array.from` (never a lone surrogate), and trailing `-` is
  stripped again.
- Empty → `deck`, giving `deck-spec.md`.
- This removes path separators, reserved characters (`<>:"|?*`), control characters, leading dots and emoji, and keeps letters in any script.
- At most 60 code points × 4 bytes + `-spec.md` = 248 UTF-8 bytes, within the 255-byte name limit.
- `toLowerCase` is locale-independent. The `-spec.md` suffix means the stem is never a bare Windows device name (`CON` → `con-spec.md`).
- **The spec's title is used, not the session name in the page header.** The file name then matches the document's H1, and stays a
  function of the spec alone (portable to D1's backend follow-up). **[review]** A user-renamed session can therefore export under the
  architect's title.

### D7. UI

- **Placement:** an `outline`, `size="sm"` `Button` in the SpecView header's right-hand group, between the read-only hint and **Discuss**.
- **Label:** a `FileDown` icon (lucide-react; verified the export is defined — a forwardRef object) and visible text `Export spec`.
  `aria-label` and `title` are `Export spec as Markdown`. That satisfies WCAG 2.5.3 label-in-name, because the visible words are a
  prefix of the name. `data-testid="spec-export-markdown"`.
- **No spec → hidden, not disabled.** There is nothing to export. The empty state already tells the user how to get a spec, and
  Discuss stays, because asking for a plan is the available action.
- **Never gated on `reviewInProgress` or generation.** The `deckReviewFlag.test.tsx:103–111` source scan forbids `disabled={…reviewInProgress…}`
  in SpecView.tsx. A behavioural test adds coverage for a conditional render too.
- **Properties kept:**
  1. A `<button>` is not an input, textarea, select or contenteditable, so the existing structural test stays green.
  2. Only `renderDeckSpecMarkdown(spec)` content is written (L3).
  3. The button takes no view state and emits none; it makes no request. It computes on click, with no memo, so it always reflects
     the current props.
- **Download:** a new `downloadTextFile(text, filename, mimeType)` in `frontend/src/utils/downloadFile.ts`.
  - Steps: create a `Blob`, then an object URL, attach a transient `<a download>` to `document.body`, `click()`, remove it, and
    **schedule** the revoke.
  - **The revoke is deferred (supervisor ruling):** `setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS)`, with an exported
    `REVOKE_DELAY_MS = 10_000`.
    - Safari and Firefox have historically failed downloads whose blob URL was revoked synchronously. Holding a small text blob
      for 10 s costs nothing.
    - This deliberately departs from the two synchronous paths in `useDeckExport.ts` (:65–76, :154–162). Their only Playwright test
      checks the filename, not the bytes.
  - MIME `text/markdown;charset=utf-8` (RFC 7763). No BOM.
  - `useDeckExport.ts` is **not** refactored onto it (out of scope).
- **AppLayout.tsx is not touched.** That keeps this branch out of the files the sibling branches #323, #321 and #319 edit.

### D8. Docs

- `docs/technical/export-features.md`: an overview bullet, plus a new section "Deck spec as Markdown (client-side)" covering location,
  who can export, contents/order, omitted field, escaping, determinism, filename, the golden contract and code pointers. Plus a line in
  *File Naming*.
- `docs/technical/frontend-overview.md`: rows for `SpecView.tsx` (currently missing from the component table),
  `services/deckSpecMarkdown.ts` and `utils/downloadFile.ts`, appended at the **end** of the table (sibling overlap, Global constraints).
- `docs/user-guide/01-generating-slides.md`: a new section, "Reviewing the Deck Spec", **after "Returning to a Previous Session"**
  (heading at :72, before `## Tips` :76). That is a distinct anchor from #316's and #323's sections. There is no existing user-guide
  page for the Spec view, and no screenshots are added.
- `docs/technical/url-routing.md:275`: correct the stale `viewer-readonly.spec.ts` row.
- `CONTEXT.md` has no deck-spec entries (its glossary covers graph configuration). No glossary change.

### D9. Test parser: declare `mdast-util-from-markdown` as a devDependency

- It is a real CommonMark parser, already installed at exactly `2.0.3` and already in the lockfile as a non-dev package.
- Declaring it (`"mdast-util-from-markdown": "^2.0.3"`) changes one line in `package.json` and one line in `package-lock.json`'s root
  `packages[""].devDependencies`. It downloads nothing, and the tests stop depending on `react-markdown`'s transitive tree.
- `mdast-util-to-string` and `@types/mdast` are **not** added. The test helper implements its own `plainText` and a minimal `MdNode`
  type, so nothing else needs declaring.
- `marked` is rejected: it is reachable only via monaco, and it is not strict CommonMark.
- Lockfile hygiene: the line is **hand-added**, and never added with `npm install <pkg>`, because the local registry is the Databricks
  proxy (Context). npm 11 runs locally and npm 10 in CI (Node 20). See Task 3, Step 1.

## Global constraints

- Work only in the worktree above. Never touch the primary checkout or other worktrees. No deploys (`publish-dev.yml`,
  `deploy_local.sh`). Never `git stash`. Never `pip install`; use `uv run`. Never `gh auth switch`.
- **Commits:** the supervisor commits each reviewer-approved task, with a conventional message ending
  `Co-authored-by: Isaac <no-reply@databricks.com>`. Sub-agents never commit. Nobody pushes unless the user asks.
- **Never run `npm install <pkg>` in this repo.** The local npm registry is the Databricks proxy. A package argument re-resolves to
  latest and writes `npm-proxy.cloud.databricks.com` URLs into the lock (Context). Dependency changes are hand-edited, then
  synced with argument-less `npm install --package-lock-only --ignore-scripts` (Task 3).
- **Sibling overlaps (all siblings still at 679d2f21):**
  - `docs/user-guide/01-generating-slides.md`:
    - #316 adds `## Review Feedback` after "Navigating Slides";
    - #323 adds `## Clearing the Chat` after "Iterating on Your Slides";
    - #319 and #321 edit the page.
    - This plan's section goes **after "Returning to a Previous Session"** instead.
  - `docs/technical/frontend-overview.md` component table: edited by #316, #319, #321 and #323. This plan **appends** its rows at the end
    of the table (after the `PresentationMode.tsx` row, :370).
  - `frontend/tests/e2e/spec-view.spec.ts`: #316 edits the `SLIDE0_FINDINGS` literals (:110–145). This plan keeps its additions out of
    :110–145: fixtures next to `COMPILED_DECK_CSS` (:43–48), tests inside the two describes.
- **Playwright and dev servers are shared state.** `playwright.config.ts` runs `npm run dev` on :3000 with `reuseExistingServer: true`, so
  another worktree's dev server would silently serve *its* code. Run e2e only while holding the session's Playwright/dev-server lock;
  otherwise CI's `E2E - spec-view` job is the gate.
- No change to `DeckSpec`/`SlideSpec` fields. If one ever becomes necessary, it must be mirrored in `frontend/src/types/slide.ts` and
  `deckSpecConformance.test.ts`, and the architect schema digest moves. Do not change agent prompts or pinned digests.
- Do not edit `AppLayout.tsx`, the chat panel, findings, architect prompts or tour copy. Siblings #323, #321, #319, #316, #313 and
  #314 own those areas.
- New tests must not touch `localStorage` (the Node 26 local failure cause).
- Frontend: `cd frontend && npx vitest run <file>`; `npm run test:unit`; `npm run build`; lint touched files with
  `npx eslint <files>`. Backend: `uv run pytest <file> -q`; full unit suite `uv run pytest tests/unit -n 4 -q`.
- Baselines are **cause-sets** (`executing-plans-tellr` §3). The frontend unit baseline is the 20 *reading 'clear'* failures above.
- Every test below names its **sabotage target**: the production line which, when broken, must turn it red. Verify each sabotage took
  effect: grep the marker and confirm it is on the executed path.

## File map

| File | Change | Task |
|---|---|---|
| `frontend/src/test/pydanticSource.ts` | Create — shared reader of Pydantic source text | 1 |
| `frontend/src/test/pydanticSource.test.ts` | Create | 1 |
| `frontend/src/services/__tests__/deckSpecConformance.test.ts` | Modify — import the two moved functions; no assertion changes | 1 |
| `frontend/tests/fixtures/deck-spec-markdown/full.deck-spec.json` | Create — golden input (cross-language contract) | 2 |
| `frontend/tests/fixtures/deck-spec-markdown/full.md` | Create — golden output, byte-exact | 2 |
| `frontend/tests/fixtures/deck-spec-markdown/.gitattributes` | Create — `* text eol=lf` | 2 |
| `tests/unit/test_deck_spec_markdown_fixture.py` | Create — fixture is a valid, fully spelled-out `DeckSpec`; `.md` is LF/UTF-8 | 2 |
| `frontend/package.json`, `frontend/package-lock.json` | Modify — devDependency `mdast-util-from-markdown` | 3 |
| `frontend/src/test/markdownStructure.ts` | Create — parse + structure helpers for tests | 3 |
| `frontend/src/services/deckSpecMarkdown.ts` | Create — renderer, filename, MIME constant | 3 |
| `frontend/src/services/__tests__/deckSpecMarkdown.test.ts` | Create | 3 |
| `frontend/src/services/__tests__/deckSpecMarkdownCoverage.test.tsx` | Create — guards (a) and (b) | 4 |
| `frontend/src/test/readBlobText.ts` | Create — FileReader-based Blob reader (jsdom Blob lacks `.text()`) | 5 |
| `frontend/src/utils/downloadFile.ts` | Create | 5 |
| `frontend/src/utils/downloadFile.test.ts` | Create | 5 |
| `frontend/src/components/SpecView/SpecView.tsx` | Modify — export button + header-comment note | 6 |
| `frontend/src/components/SpecView/SpecView.test.tsx` | Modify — export tests, header sabotage list | 6 |
| `frontend/tests/e2e/spec-view.spec.ts` | Modify — download tests | 7 |
| `docs/technical/export-features.md`, `docs/technical/frontend-overview.md`, `docs/technical/url-routing.md`, `docs/user-guide/01-generating-slides.md` | Modify | 8 |

**Sequencing.** 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.
- Tasks 1, 2 and 5 touch disjoint files and could run in any order, but they share one worktree, so run them sequentially.
- Task 3 needs 2. Task 4 needs 1 and 3. Task 6 needs 3 and 5. Task 7 needs 6.
- No two tasks edit the same file.

---

## Task 0: Pre-flight baseline

**Models:** test=sonnet impl=sonnet (controller-run; no new tests)

- [ ] Plan-vs-code pre-pass (`executing-plans-tellr` §2):
  - re-grep every `file:line` cited in *Context*;
  - confirm `lucide-react` exports `FileDown`: `node -e "console.log(typeof require('lucide-react').FileDown)"` in `frontend/` prints a
    defined type (`object`: it is a forwardRef), not `undefined`;
  - confirm the lock has no proxy URLs: `grep -c npm-proxy.cloud.databricks.com frontend/package-lock.json` prints `0`;
  - write `PLAN-CORRECTIONS.md` in the worktree root if anything differs.
- [ ] `uv sync --extra dev` in the worktree root (a `.venv` already exists). Confirm `frontend/node_modules` exists; do not reinstall.
- [ ] Record baselines as cause-sets:
  - `cd frontend && npx vitest run 2>&1 | grep -E "FAIL|Test Files|Tests "` (expect the 20 *reading 'clear'* failures in 3 files);
  - `npx tsc -b` (clean);
  - `uv run pytest tests/unit -n 4 -q` (record the failing causes, if any).

---

## Task 1: Shared Pydantic-source reader

**Models:** test=sonnet impl=haiku

**Files:** create `frontend/src/test/pydanticSource.ts` and `frontend/src/test/pydanticSource.test.ts`; modify
`frontend/src/services/__tests__/deckSpecConformance.test.ts`.

**Interface.**

```ts
// frontend/src/test/pydanticSource.ts
export function pythonClassBody(source: string, className: string): string;            // MOVED verbatim from deckSpecConformance.test.ts:103
export function pythonModelFields(source: string, className: string): string[];        // MOVED verbatim from :117
export function pythonModelFieldAnnotations(source: string, className: string): Map<string, string>; // NEW
export function pythonModelClasses(source: string): string[];                            // NEW
```

New functions (verified against the real `deck_spec.py`: they return the five classes and the exact annotations, e.g. `slide_type` →
`Optional[str]`, `figures` → `list[ResolvedFigure]`):

```ts
/** Field name -> annotation text ('Optional[int]', 'list[SlideSpec]', …), in declaration order. */
export function pythonModelFieldAnnotations(source: string, className: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const line of pythonClassBody(source, className).split('\n')) {
    // Same 4-space class-body rule as pythonModelFields; a default (`= None`) is not part of the annotation.
    const match = /^ {4}([a-z_][A-Za-z0-9_]*)\s*:\s*([^=]+?)\s*(?:=.*)?$/.exec(line);
    if (match) out.set(match[1], match[2].trim());
  }
  return out;
}

/** Every `class X(BaseModel):` in the source, in declaration order (docstrings stripped first). */
export function pythonModelClasses(source: string): string[] {
  const stripped = source.replace(/"""[\s\S]*?"""/g, '');
  return [...stripped.matchAll(/^class (\w+)\(BaseModel\):$/gm)].map((m) => m[1]);
}
```

The helper is a `.ts` file under `src/`, so `tsc -b` (tsconfig.app) typechecks it. It must be strict-clean, with no unused locals.

Steps:

- [ ] **Step 1 (test author):** write `pydanticSource.test.ts` against a **synthetic** Python source string. Do not pin
  `deck_spec.py`'s field list; that is the conformance test's job, and pinning it would make every model change touch this file. The
  source must contain:
  - a module docstring with a line `    fake_field: str`;
  - `class Inner(BaseModel):` with a docstring containing `    not_a_field: int`, then `a: str`, `b: Optional[int] = None`, and a
    `@field_validator` method whose body has `        local: int = 1`;
  - `class Outer(BaseModel):` with `items: list[Inner]` and `inner: Inner`.

  Assert:
  - `pythonModelClasses` → `['Inner', 'Outer']`;
  - `pythonModelFields(src, 'Inner')` → `['a', 'b']`;
  - annotations: `Inner` → `[['a','str'],['b','Optional[int]']]` and `Outer` → `[['items','list[Inner]'],['inner','Inner']]`;
  - a missing class throws.

  Then add one real-file test: for every class `pythonModelClasses(deckSpecPy)` returns, the annotation keys equal `pythonModelFields`,
  and the class list is non-empty. Import with `deckSpecPy from '../../../src/domain/deck_spec.py?raw'`
  (`frontend/src/test` → repo root is `../../../`). Create the module with the two new functions throwing `new Error('not implemented')`
  (moved ones not yet moved), and confirm red per assertion. Leave uncommitted.
  *Sabotage targets:*
  - drop the docstring strip (`fake_field`/`not_a_field` appear);
  - loosen ` {4}` to ` +` (`local` appears);
  - drop `(?:=.*)?`: the `b: Optional[int] = None` line stops matching, because `[^=]+?\s*$` cannot cross the `=`, so `b` disappears
    from the annotations.
- [ ] **Step 2 (implementer):**
  - **Move** `pythonClassBody` and `pythonModelFields`, with their comments, verbatim into the helper and export them.
  - In the conformance test, delete the local copies and `import { pythonClassBody, pythonModelFields } from '../../test/pydanticSource';`.
  - Keep `tsInterfaceFields` local, and keep the conformance header comment and every assertion byte-identical.
  - Implement the two new functions as given.
- [ ] **Step 3:**
  - `npx vitest run src/test/pydanticSource.test.ts src/services/__tests__/deckSpecConformance.test.ts` is green (conformance stays
    13/13), and `npx tsc -b` is clean.
  - The reviewer confirms the conformance diff is import-only, then sabotages `pythonModelFields` to `return []`: the conformance
    *parsed at all* test must go red. Restore it.

---

## Task 2: Golden fixture pair (cross-language contract) + backend validity test

**Models:** test=sonnet impl=haiku

**Files:** create `frontend/tests/fixtures/deck-spec-markdown/full.deck-spec.json`, `full.md` and `.gitattributes`, plus
`tests/unit/test_deck_spec_markdown_fixture.py`.

The test author **extracts** both fixture files from this plan file. **Do not retype them**: they are full of literal backslashes, and a
transcription slip would surface in Task 3 as a false renderer failure. They are the contract that Tasks 3, 4, 6 and 7 compare
against, and nobody edits them later without a format decision.

```bash
cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-318
PLAN=docs/superpowers/plans/2026-10-19-issue-318-export-spec-markdown.md
D=frontend/tests/fixtures/deck-spec-markdown
mkdir -p "$D"
sed -n '570,642p' "$PLAN" > "$D/full.deck-spec.json"
sed -n '648,719p'   "$PLAN" > "$D/full.md"
printf '* text eol=lf\n' > "$D/.gitattributes"
shasum -a 256 "$D/full.deck-spec.json" "$D/full.md"
```

Each `sed` range is exactly the fence body. `sed -n` ends each file with one LF.

The `shasum` output **must** be:

```
473f35ce77912267dbaca6966616444bdefe5d477e10843385cc6dec7369ab69  frontend/tests/fixtures/deck-spec-markdown/full.deck-spec.json
b40a7637597ac50ca307daf66002b0cdf27e992c5f16ab5f0441068d2ff68ef3  frontend/tests/fixtures/deck-spec-markdown/full.md
```

The JSON is 2510 bytes and the Markdown 1926 bytes. If either hash differs, the plan file was edited after these
ranges were computed: STOP and report. Do not hand-fix.

What the fixture deliberately carries:
- a gap in positions (0, 1, 3);
- a null and a non-null `slide_type`;
- an excluded field (`template_section_index` 0 / 12 / null; 12 is chosen so it does not occur anywhere in the rendered text);
- an empty scalar (`assumes: ""`) and an empty list;
- a CRLF inside a value;
- non-ASCII (`—`);
- characters exercising every escape class: `<b>`, a leading `2024.`, a leading `- `, `*`, `_`, `#`, `|`, `&`, `$`, `~` and a backtick.
- **Normalisation code points, written as JSON escapes.** Each is placed where the normalised text is the same as with a plain space
  (or nothing), so `full.md` is unchanged. A port that gets the code-point sets of D4 wrong produces a different file:
  - a tab `\t` in `audience`;
  - U+00A0 in `purpose`;
  - U+2028 in slide 0's `hands_off`;
  - U+0085 (NEL, collapsed to a space) in slide 1's `assumes`;
  - U+001F (removed) in slide 1's `purpose`.

`full.deck-spec.json`:

```json
{
  "title": "Renewal risk, Q3 — EMEA/APAC",
  "audience": "The regional sales leadership team,\twho own the renewal number.",
  "purpose": "Get the early-warning pipeline funded before the Q4\u00a0renewal wave.",
  "argument": "Churn is predictable a quarter ahead — and today nobody looks at <b>any</b> of it.",
  "call_to_action": "Approve two engineers for one quarter: our #1 priority.",
  "narrative_arc": [
    "Frame the problem: renewals are slipping and nobody can say which accounts.",
    "2024. The signal existed, but it arrived after the renewal date.",
    "- Close on the ask: fund the *early-warning* pipeline this quarter."
  ],
  "design_contract": {
    "design_system_id": 7,
    "template_id": 3,
    "slide_style_id": null
  },
  "resolved_data": {
    "synthesis": "Three quarters of churn history | aggregated by region & segment.",
    "figures": [
      {
        "key": "churn_rate",
        "value": "11.4%",
        "source": "warehouse.renewals"
      },
      {
        "key": "arr_at_risk",
        "value": "$4.2M (~30% of Q4)",
        "source": "finance.arr_snapshot"
      }
    ],
    "gaps": [
      "No data before FY23.",
      "The APAC `tier` column is unpopulated."
    ]
  },
  "slides": [
    {
      "position": 0,
      "purpose": "Open on the number nobody can explain.",
      "content_brief": "Title slide: the headline churn rate\r\nand the quarter it lands in.",
      "assumes": "Nothing. This is the first slide.",
      "hands_off": "The reader knows the number\u2028and wants to know why.",
      "data_references": [
        "churn_rate"
      ],
      "slide_type": "Cover",
      "template_section_index": 0
    },
    {
      "position": 1,
      "purpose": "Show the money\u001f at stake.",
      "content_brief": "One stat: ARR at risk, with its share of Q4.",
      "assumes": "The reader accepts the churn number from\u0085slide 1.",
      "hands_off": "The reader wants to know what fixing it costs.",
      "data_references": [
        "churn_rate",
        "arr_at_risk"
      ],
      "slide_type": "Stats",
      "template_section_index": 12
    },
    {
      "position": 3,
      "purpose": "Land the ask while the cause is still fresh.",
      "content_brief": "Closing slide: the two-engineer ask, scoped to one quarter.",
      "assumes": "",
      "hands_off": "The deck ends on a decision the reader can make in the room.",
      "data_references": [],
      "slide_type": null,
      "template_section_index": null
    }
  ]
}
```

`full.md`:

````markdown
# Renewal risk, Q3 — EMEA/APAC

## Audience

The regional sales leadership team, who own the renewal number.

## Purpose

Get the early-warning pipeline funded before the Q4 renewal wave.

## Argument

Churn is predictable a quarter ahead — and today nobody looks at \<b\>any\</b\> of it.

## Call to action

Approve two engineers for one quarter: our \#1 priority.

## Narrative arc

1. Frame the problem: renewals are slipping and nobody can say which accounts.
2. 2024\. The signal existed, but it arrived after the renewal date.
3. \- Close on the ask: fund the \*early-warning\* pipeline this quarter.

## Design contract

- Design system #7
- Template #3

## Slide briefs

### Slide 1

- **Purpose:** Open on the number nobody can explain.
- **Content brief:** Title slide: the headline churn rate and the quarter it lands in.
- **Assumes:** Nothing. This is the first slide.
- **Hands off:** The reader knows the number and wants to know why.
- **Slide type:** Cover
- **Data references:** churn\_rate

### Slide 2

- **Purpose:** Show the money at stake.
- **Content brief:** One stat: ARR at risk, with its share of Q4.
- **Assumes:** The reader accepts the churn number from slide 1.
- **Hands off:** The reader wants to know what fixing it costs.
- **Slide type:** Stats
- **Data references:** churn\_rate, arr\_at\_risk

### Slide 4

- **Purpose:** Land the ask while the cause is still fresh.
- **Content brief:** Closing slide: the two-engineer ask, scoped to one quarter.
- **Assumes:** Not set.
- **Hands off:** The deck ends on a decision the reader can make in the room.
- **Data references:** None.

## Data

### Synthesis

Three quarters of churn history \| aggregated by region \& segment.

### Figures

- churn\_rate: 11.4% (source: warehouse.renewals)
- arr\_at\_risk: \$4.2M (\~30% of Q4) (source: finance.arr\_snapshot)

### Gaps

- No data before FY23.
- The APAC \`tier\` column is unpopulated.
````

Note: the golden was generated and re-verified (r2) from exactly the JSON above, using the Task 3 format and escaper.

**Python test** (`tests/unit/test_deck_spec_markdown_fixture.py`; import style as in `tests/unit/test_deck_spec.py:17`):

```python
"""The deck-spec Markdown golden pair is a valid DeckSpec and a well-formed contract.

frontend/src/services/deckSpecMarkdown.ts renders full.deck-spec.json to full.md byte for
byte (vitest + e2e). It is also the contract any later backend/MCP renderer must reproduce
(docs/technical/export-features.md), so it must be a spec the backend would accept, it must
spell out every field explicitly, and the .md must survive any checkout unchanged.
"""
import json
from pathlib import Path

from src.domain.deck_spec import DeckSpec, DesignContractRef, ResolvedData, ResolvedFigure, SlideSpec

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "fixtures" / "deck-spec-markdown"


def _raw() -> dict:
    return json.loads((FIXTURE_DIR / "full.deck-spec.json").read_text(encoding="utf-8"))


def test_fixture_is_a_valid_deck_spec():
    DeckSpec.model_validate(_raw())


def test_fixture_round_trips_through_the_model_unchanged():
    # A value a validator would rewrite (e.g. a padded slide_type) would make the contract
    # describe input the backend never stores.
    raw = _raw()
    assert DeckSpec.model_validate(raw).model_dump() == raw


def test_fixture_spells_out_every_field_of_every_model():
    raw = _raw()
    assert set(raw) == set(DeckSpec.model_fields)
    assert set(raw["design_contract"]) == set(DesignContractRef.model_fields)
    assert set(raw["resolved_data"]) == set(ResolvedData.model_fields)
    assert raw["resolved_data"]["figures"] and raw["slides"]
    for figure in raw["resolved_data"]["figures"]:
        assert set(figure) == set(ResolvedFigure.model_fields)
    for slide in raw["slides"]:
        assert set(slide) == set(SlideSpec.model_fields)


def test_golden_markdown_is_lf_utf8_with_one_trailing_newline():
    data = (FIXTURE_DIR / "full.md").read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in data
    assert data.endswith(b"\n") and not data.endswith(b"\n\n")
    data.decode("utf-8")
```

Steps:

- [ ] **Step 1 (test author):** extract the fixtures with the `sed` block above, check both sha256 values, then write the Python test.
  Run `uv run pytest tests/unit/test_deck_spec_markdown_fixture.py -q`; it should be green on arrival (no production code).
  Sabotage each test and confirm red, then restore:
  - set `"slide_style_id": 5` (L1);
  - delete slide 3's `"template_section_index"` key;
  - pad `"slide_type": " Cover "` (round-trip strips it);
  - append `\r\n` to `full.md`.
- [ ] **Step 2 (implementer):** none. There is no production code. The reviewer re-runs the `shasum` line and diffs both fixtures
  against the plan's `sed` ranges.
- [ ] **Step 3:** `uv run pytest tests/unit/test_deck_spec_markdown_fixture.py tests/unit/test_deck_spec.py -q` is green.

---

## Task 3: The renderer and its unit tests

**Models:** test=opus impl=sonnet

**Files:**
- modify `frontend/package.json` and `frontend/package-lock.json`;
- create `frontend/src/test/markdownStructure.ts`, `frontend/src/services/deckSpecMarkdown.ts` and
  `frontend/src/services/__tests__/deckSpecMarkdown.test.ts`.

**Interface** (`frontend/src/services/deckSpecMarkdown.ts`):

```ts
import type { DeckSpec } from '../types/slide';

/** RFC 7763 media type, UTF-8, no BOM. */
export const DECK_SPEC_MARKDOWN_MIME = 'text/markdown;charset=utf-8';

/** Deterministic Markdown rendering of a deck spec. Pure: never reads anything but `spec`, never mutates it. */
export function renderDeckSpecMarkdown(spec: DeckSpec): string;

/** `<slug>-spec.md` from the spec title (D6); `deck-spec.md` when nothing survives sanitising. */
export function deckSpecMarkdownFilename(title: string): string;
```

**Format** — exactly the golden's shape (D2's order). Blocks are joined with `'\n\n'`, and the output ends with `'\n'`.
1. `# {title}`. A blank title gives `# Untitled deck spec`.
2. `## Audience`, `## Purpose`, `## Argument`, `## Call to action`, each followed by one paragraph value.
3. `## Narrative arc`, then the `1. ` … `n. ` lines (one block, joined with `'\n'`), or `None.`
4. `## Design contract`, then the `- Design system #{num(id)}` / `- Template #{num(id)}` / `- Slide style #{num(id)}` lines for the
   ids that are `!= null`, in that order, or `No design system or slide style pinned`.
5. `## Slide briefs`, then `None.` if there are no slides. Otherwise, per slide **in given order**, a heading and one bullet block:
   - The heading is `### Slide {position + 1}` when `Number.isInteger(position)`, else `### Slide {escapeText(position)}`
     (D2: the escaped raw value, no arithmetic; `null` gives `### Slide Not set.`).
   - The bullet block:
     - `- **Purpose:** …`
     - `- **Content brief:** …`
     - `- **Assumes:** …`
     - `- **Hands off:** …`
     - `- **Slide type:** …` (only if `slide_type != null`, so `undefined` behaves like `null`)
     - `- **Data references:** a, b` (each escaped, joined `', '`; `data_references ?? []`), or `None.`
6. `## Data`, from `const data: Partial<ResolvedData> = spec.resolved_data ?? {}`, then:
   - `### Synthesis` + a paragraph (`escapeText(data.synthesis)`, so an absent synthesis gives `Not set.`);
   - `### Figures` + `- {key}: {value} (source: {source})` lines from `data.figures ?? []`, or `None.`;
   - `### Gaps` + `- {gap}` lines from `data.gaps ?? []`, or `None.`

Rules:
- Every user value goes through `escapeText`, and every numeric slot through `num`, both given below. Renderer constants (labels,
  `None.`, `Not set.`) are never escaped.
- Read fields by name; never iterate `Object.keys`/`entries`.
- `spec.design_contract ?? {}` is acceptable defence, as are the `resolved_data`/`data_references` defaults above (D2: these are fields
  the Spec view never reads).
- Do **not** add tolerance for a missing `narrative_arc` or `slides`: SpecView itself requires them.

Escaper, `num` and filename (code given — re-verified for r2 by the 490-case prototype and by every row of the filename table below):

```ts
const NOT_SET = 'Not set.';
/** CommonMark §2.4 lets any ASCII punctuation be backslash-escaped; these are the ones with meaning (D4). `@` stops GitHub mentions. */
const ESCAPE_ANYWHERE = /[\\`*_[\]<>#|~$&@]/g;
/** D4 step 1, by code point: C0/C1 controls, except the whitespace ones and NEL (U+0085), which step 2 collapses. */
// eslint-disable-next-line no-control-regex -- removing control characters is this pattern's purpose
const CONTROL_CHARS = /[\u0000-\u0008\u000E-\u001F\u007F-\u0084\u0086-\u009F]/g;
/** D4 step 2, by code point: ECMAScript's whitespace plus NEL. Spelled out so a port to another language cannot drift. */
const WHITESPACE_RUN = /[\t\n\v\f\r \u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF]+/g;

function normalise(value: unknown): string {
  return String(value ?? '').replace(CONTROL_CHARS, '').replace(WHITESPACE_RUN, ' ').trim();
}

function escapeText(value: unknown): string {
  const text = normalise(value);
  if (!text) return NOT_SET;
  let out = text.replace(ESCAPE_ANYWHERE, (c) => `\\${c}`);
  if (/^[-+=]/.test(out)) out = `\\${out}`;                    // list / thematic break / setext
  return out.replace(/^(\d{1,9})([.)])(?= |$)/, '$1\\$2');      // ordered-list marker
}

/** Numeric slots (ids, position): an integer verbatim; anything else (unvalidated JSON) is escaped like text. */
function num(value: unknown): string {
  return Number.isInteger(value) ? String(value) : escapeText(value);
}

const SLUG_MAX_CODE_POINTS = 60;
export function deckSpecMarkdownFilename(title: string): string {
  const slug = Array.from(
    String(title ?? '').toLowerCase().normalize('NFC')
      .replace(/[^\p{L}\p{N}\p{M}]+/gu, '-')
      .replace(/^-+|-+$/g, ''),
  ).slice(0, SLUG_MAX_CODE_POINTS).join('').replace(/-+$/, '');
  return `${slug || 'deck'}-spec.md`;
}
```

**Test helper** (`frontend/src/test/markdownStructure.ts`, code given; typechecked by `tsc -b`):

```ts
/**
 * Test-only: parse Markdown with a real CommonMark parser (micromark via
 * mdast-util-from-markdown — strict CommonMark, no GFM) and read its STRUCTURE, so the
 * deck-spec Markdown tests assert what a reader's renderer will build, not escape strings.
 */
import { fromMarkdown } from 'mdast-util-from-markdown';

export interface MdNode { type: string; depth?: number; ordered?: boolean | null; value?: string; children?: MdNode[] }
export type Skeleton = { type: string; depth?: number; ordered?: boolean | null; children: Skeleton[] };

export const ALLOWED_NODE_TYPES: ReadonlySet<string> =
  new Set(['root', 'heading', 'paragraph', 'text', 'list', 'listItem', 'strong']);

export function parseMarkdown(markdown: string): MdNode { return fromMarkdown(markdown) as unknown as MdNode; }
/**
 * D4's normalisation, restated INDEPENDENTLY of the renderer (explicit code points), so an expectation
 * normalised here cannot inherit a production drift: controls removed, whitespace runs
 * (ECMAScript whitespace plus NEL) collapsed to one space, trimmed.
 */
// eslint-disable-next-line no-control-regex -- the control set is the point
const CONTROL = /[\u0000-\u0008\u000E-\u001F\u007F-\u0084\u0086-\u009F]/g;
const WHITESPACE = /[\t\n\v\f\r \u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF]+/g;
export function normaliseText(text: string): string { return text.replace(CONTROL, '').replace(WHITESPACE, ' ').trim(); }
export function plainText(node: MdNode): string {
  return typeof node.value === 'string' ? node.value : (node.children ?? []).map(plainText).join('');
}
function walk(node: MdNode, visit: (n: MdNode) => void): void { visit(node); (node.children ?? []).forEach((c) => walk(c, visit)); }
export function nodeTypes(root: MdNode): Set<string> { const s = new Set<string>(); walk(root, (n) => s.add(n.type)); return s; }
export function headings(root: MdNode): Array<[number, string]> {
  const out: Array<[number, string]> = [];
  walk(root, (n) => { if (n.type === 'heading') out.push([n.depth ?? 0, normaliseText(plainText(n))]); });
  return out;
}
export function strongTexts(root: MdNode): string[] {
  const out: string[] = []; walk(root, (n) => { if (n.type === 'strong') out.push(plainText(n)); }); return out;
}
/** Whitespace-normalised text of every heading and paragraph, document order. */
export function blockTexts(root: MdNode): string[] {
  const out: string[] = [];
  walk(root, (n) => { if (n.type === 'heading' || n.type === 'paragraph') out.push(normaliseText(plainText(n))); });
  return out;
}
/** Block structure with the expected inline content (text, strong) dropped; anything injected shows up. */
export function blockSkeleton(node: MdNode): Skeleton | null {
  if (node.type === 'text' || node.type === 'strong') return null;
  return {
    type: node.type, depth: node.depth, ordered: node.ordered,
    children: (node.children ?? []).map(blockSkeleton).filter((c): c is Skeleton => c !== null),
  };
}
```

Fixtures are imported in tests as raw text: `import goldenSpecJson from '../../../tests/fixtures/deck-spec-markdown/full.deck-spec.json?raw'`,
`import goldenMarkdown from '../../../tests/fixtures/deck-spec-markdown/full.md?raw'`, and
`const GOLDEN: DeckSpec = JSON.parse(goldenSpecJson)`. Always `structuredClone(GOLDEN)` before mutating.

Steps:

- [ ] **Step 1 (test author):**
  1. Declare the parser **by hand**. Never `npm install <pkg>`: the local registry is the Databricks proxy, and a package argument
     re-resolves to 2.1.0 and writes proxy URLs (Context).
     - Add the line `"mdast-util-from-markdown": "^2.0.3",` directly after `"jsdom": "^26.1.0",` in **two** places:
       `frontend/package.json` → `devDependencies` (:61), and `frontend/package-lock.json` → `packages[""].devDependencies` (:50).
     - Run `cd frontend && npm install --package-lock-only --ignore-scripts` with **no package argument**.
     - `git diff frontend/package.json frontend/package-lock.json` must be **exactly those two added lines**, and nothing else.
       The package entry `node_modules/mdast-util-from-markdown` keeps version 2.0.3 and gets no `"dev": true`, which is correct
       because react-markdown needs it at runtime.
     - `grep -c npm-proxy.cloud.databricks.com frontend/package-lock.json` must print `0`.
     - `npm ls mdast-util-from-markdown` shows `2.0.3` as a direct dependency, not extraneous.
     - If any check fails: `git checkout frontend/package.json frontend/package-lock.json`, then STOP and report. Do not improvise.
  2. Create `markdownStructure.ts` as given.
  3. Create `deckSpecMarkdown.ts` exporting the three symbols, with `throw new Error('not implemented')` bodies, so each test is red
     on its own assertion rather than on an import error.
  4. Write `deckSpecMarkdown.test.ts` with these groups, each test naming its sabotage target in a comment:
     - **Parser sanity (preconditions, own tests).** `parseMarkdown('# a\n\n<b>x</b>\n\n- y\n')` has `headings` `[[1,'a']]`, `nodeTypes`
       contains `html`, and its skeleton contains a `list`. This proves the helper is not blind to the injections the escaping tests
       look for.
     - **Golden.** `renderDeckSpecMarkdown(GOLDEN) === goldenMarkdown`, byte-exact.
       *Sabotage:* any format change (e.g. `## Audience` → `## Audience:`).
     - **Fixture integrity (own test).** The golden JSON genuinely carries `\r\n`, `<b>`, a beat starting `2024.` and one starting `- `,
       plus `*`, `_`, `#`, `|`, `&`, `$`, `~` and a backtick, a null and a non-null `slide_type`, a non-null `template_section_index`,
       `assumes: ''` and an empty `data_references`. It also carries, once decoded from their JSON escapes, a tab, U+00A0, U+2028,
       U+0085 and U+001F (check with `String.fromCharCode`, not by eye). If the fixture lost one, the matching half of the golden
       would be inert.
     - **Structure of the golden.**
       - `headings(parse(out))` equals exactly
         `[[1,'Renewal risk, Q3 — EMEA/APAC'],[2,'Audience'],[2,'Purpose'],[2,'Argument'],[2,'Call to action'],[2,'Narrative arc'],[2,'Design contract'],[2,'Slide briefs'],[3,'Slide 1'],[3,'Slide 2'],[3,'Slide 4'],[2,'Data'],[3,'Synthesis'],[3,'Figures'],[3,'Gaps']]`.
       - `nodeTypes ⊆ ALLOWED_NODE_TYPES`.
       - The set of `strongTexts` equals `{'Purpose:','Content brief:','Assumes:','Hands off:','Slide type:','Data references:'}`.
       - The ordered list under *Narrative arc* has item texts equal to the beats, normalised, **in given order**. That order is neither
         sorted nor reversed. *Sabotage:* `.sort()` or `.reverse()` on the arc.
     - **Escaping (D4), table-driven.**
       - **HOSTILE values** — at least:
         - headings and quotes: `'# injected heading'`, `'###### h6'`, `'Issue #'`, `'C# and F#'`, `'> quoted'`;
         - list markers: `'- bullet'`, `'+ bullet'`, `'* bullet'`, `'1. ordered'`, `'1) ordered'`, `'2024. a year'`;
         - breaks and setext: `'---'`, `'***'`, `'___'`, `'- - -'`, `'==='`, `'x\n==='`, `'x\n---'`;
         - code: `` '```js' ``, `'~~~'`, `'    indented code'`, `'\tindented code'`, `` '`inline code`' ``;
         - emphasis: `'*em*'`, `'**strong**'`, `'_em_'`, `'__strong__'`, `'snake_case_name'`;
         - links: `'[link](http://example.com)'`, `'![image](x.png)'`, `'[ref]: http://example.com'`, `'\\[link](http://x)'`;
         - HTML and autolinks: `'<b>bold</b>'`, `'<script>alert(1)</script>'`, `'<div>'`, `'<!-- comment -->'`, `'<http://example.com>'`, `'\\<b>x\\</b>'`;
         - entities and line breaks: `'&amp; &copy; &#35;'`, `'trailing backslash \\'`, `'hard  \nbreak'`;
         - multi-line: `'line one\nline two'`, `'a\r\n\r\nb'`, `'a\rb'`, `'para\n\n# heading after blank'`, `'a\u2028b\u2029c'`;
         - GFM: `'| a | b |\n|---|---|\n| 1 | 2 |'`, `'~~strike~~'`, `'$x$ and $4.2M'`.
       - **SLOTS** (setter functions on a clone of GOLDEN): `title`, `audience`, `synthesis`, `narrative_arc[0]`, `slides[0].purpose`,
         `slides[0].slide_type`, `slides[0].data_references[0]`, `figures[0].key`, `figures[0].value`, `gaps[0]`.
       - For every (slot, value), compare against the same slot set to `'benign value'`:
         - (i) `blockSkeleton` deep-equals the baseline's;
         - (ii) `nodeTypes ⊆ ALLOWED_NODE_TYPES`;
         - (iii) `strongTexts` equals the baseline's;
         - (iv) some `blockTexts` entry contains `normaliseText(value)`;
         - (v) the raw output has no `\r`, no line with leading or trailing space/tab, and no `\n\n\n`.
       - *Sabotage targets (each must go red):*
         - remove `#`, `<`, `` ` ``, `*`, `_`, `&` or `\` from `ESCAPE_ANYWHERE`, or remove **both** `[` and `]`. Removing only one
           bracket stays green, correctly: the remaining escape already breaks links;
         - delete the leading `[-+=]` rule;
         - delete the ordered-marker rule;
         - replace `WHITESPACE_RUN` with `/ +/g`.
     - **GitHub-only characters (the one string-match test, justified in D4).** With `audience = 'a | b ~~c~~ $d$ @team'`, the raw
       output contains the line `a \| b \~\~c\~\~ \$d\$ \@team`. *Sabotage:* drop `|`, `~`, `$` or `@` from the set.
     - **Control characters and NEL.** With `audience = 'nul\u0000 esc\u001b[31m bell\u0007 del\u007f us\u001fx nel\u0085end'`, the raw
       output contains the line `nul esc\[31m bell del usx nel end`: controls are removed, and NEL becomes a space.
       *Sabotage:* drop the `CONTROL_CHARS` replace (raw controls remain); move U+0085 from `WHITESPACE_RUN` into `CONTROL_CHARS`
       (gives `nelend`).
     - **Empty and optional (inline expected strings).**
       - An `EMPTY` spec — `title:'Empty plan'`, `audience:''`, `purpose:'   '`, `argument:'\n'`, `call_to_action:''`,
         `narrative_arc:[]`, all ids null, `resolved_data:{synthesis:'',figures:[],gaps:[]}`, `slides:[]` — renders **exactly**:

         ```
         # Empty plan\n\n## Audience\n\nNot set.\n\n## Purpose\n\nNot set.\n\n## Argument\n\nNot set.\n\n## Call to action\n\nNot set.\n\n## Narrative arc\n\nNone.\n\n## Design contract\n\nNo design system or slide style pinned\n\n## Slide briefs\n\nNone.\n\n## Data\n\n### Synthesis\n\nNot set.\n\n### Figures\n\nNone.\n\n### Gaps\n\nNone.\n
         ```

       - A slide-style-only contract (`slide_style_id: 5`) renders the block `## Design contract\n\n- Slide style #5\n\n`.
       - A title of `'   '` renders `# Untitled deck spec` as its first line.
       - A slide with `slide_type` **deleted** (pre-field JSON) renders byte-identically to the same slide with `slide_type: null`, and
         neither contains `Slide type`. *Sabotage:* `!== null`.
       - **Absent containers (D2 defaults).** Take a clone of GOLDEN, `delete` `resolved_data` and `delete` `slides[0].data_references`.
         Rendering does not throw. The output ends with
         `## Data\n\n### Synthesis\n\nNot set.\n\n### Figures\n\nNone.\n\n### Gaps\n\nNone.\n`, and slide 1's block contains
         `- **Data references:** None.`. `resolved_data: {}` gives the same Data section.
         *Sabotage:* drop `?? {}` or `?? []` (throws).
     - **Numeric slots (D4 `num`).** Take a clone of GOLDEN and set `slides[0].position = '<b>x</b>'` and
       `design_contract.design_system_id = '<b>x</b>'` (cast through `unknown`).
       - The raw output contains the lines `### Slide \<b\>x\</b\>` and `- Design system #\<b\>x\</b\>`.
       - `nodeTypes ⊆ ALLOWED_NODE_TYPES`.
       - `blockSkeleton` equals GOLDEN's.

       *Sabotage:* `### Slide ${s.position + 1}` without the integer check; `#${id}` without `num` (an `html` node appears).
     - **Slide order as given.** Positions `[0, 5, 2]` in that list order give slide headings `Slide 1, Slide 6, Slide 3` in that order.
       *Sabotage:* sort by position.
     - **Determinism.**
       - Render twice and compare (`===`).
       - Recursively reverse every object's key order (arrays untouched); `=== goldenMarkdown`. *Sabotage:* emit deck fields via
         `Object.entries`.
       - `vi.useFakeTimers()`, then `setSystemTime` to 2020-01-01, render, `setSystemTime` to 2031-06-15, render; the two are equal.
         Restore with `vi.useRealTimers()` in a `finally`. *Sabotage:* append `new Date().toISOString()`.
       - `design_system_id: 1234567` renders `- Design system #1234567`. *Sabotage:* `toLocaleString()`.
       - A deep-`Object.freeze`d clone of GOLDEN renders to the golden. *Sabotage:* in-place `slides.sort`.
     - **Filename.** A table of exact outputs:

       | input | output |
       |---|---|
       | `'Renewal risk, Q3 — EMEA/APAC'` | `renewal-risk-q3-emea-apac-spec.md` |
       | `'../../etc/passwd'` | `etc-passwd-spec.md` |
       | `'C:\\Users\\x\\deck.md'` | `c-users-x-deck-md-spec.md` |
       | `'.hidden'` | `hidden-spec.md` |
       | `'...'`, `''`, `'   '`, `'🚀🚀🚀'` | `deck-spec.md` |
       | `'CON'` | `con-spec.md` |
       | `'Prévisions T3 — Ventes'` | `prévisions-t3-ventes-spec.md` |
       | `'e\u0301te\u0301'` | `'\u00e9t\u00e9-spec.md'` (NFC) |
       | `'四半期レビュー'` | `四半期レビュー-spec.md` |
       | `'a\u0000b\u001fc'` | `a-b-c-spec.md` |
       | `'A'.repeat(200)` | `'a'.repeat(60) + '-spec.md'` |
       | `'x'.repeat(59) + ' yz'` | `'x'.repeat(59) + '-spec.md'` (cut, then no trailing `-`) |
       | `'𝒜'.repeat(100)` | `'𝒜'.repeat(60) + '-spec.md'` (astral: 60 code points, not 60 UTF-16 units) |
       | `'a' + '𝒜'.repeat(100)` | `'a' + '𝒜'.repeat(59) + '-spec.md'` |

       Then properties, over those inputs plus `'四'.repeat(300)`:
       - the output matches `/^[\p{L}\p{N}\p{M}]+(?:-[\p{L}\p{N}\p{M}]+)*-spec\.md$/u`;
       - it has no `/`, `\` or leading `.`;
       - `!/\p{Cs}/u.test(out)` (no lone surrogate);
       - its UTF-8 length is ≤ 255 bytes (`new TextEncoder().encode(out).length`).

       *Sabotage:*
       - `.slice(0, 60)` on the string instead of `Array.from`. Both astral rows go red on their exact output (30 code points), and
         `'a' + '𝒜'.repeat(100)` also leaves a lone surrogate (`\p{Cs}` property red);
       - drop the second `-+$` strip;
       - drop `normalize('NFC')`.

     Confirm red, test by test, for the right reason (the "not implemented" stub). Leave uncommitted.
- [ ] **Step 2 (implementer):**
  - Implement `renderDeckSpecMarkdown` to the format above, using the given `escapeText`/`normalise`/`num` and the D2 defaults, and
    paste `deckSpecMarkdownFilename` as given.
  - Do not edit tests or fixtures. If a test looks wrong, STOP and report; Opus rules.
- [ ] **Step 3:**
  - `npx vitest run src/services/__tests__/deckSpecMarkdown.test.ts` is green.
  - `npx tsc -b` is clean.
  - `npx eslint src/services/deckSpecMarkdown.ts src/test/markdownStructure.ts src/services/__tests__/deckSpecMarkdown.test.ts` is clean.
  - The reviewer runs a different subset of the listed sabotages from the test author (§1). Ledger which.

---

## Task 4: Field-coverage guards (D3)

**Models:** test=opus impl=sonnet

**Files:** create `frontend/src/services/__tests__/deckSpecMarkdownCoverage.test.tsx`.

Imports:
- `deckSpecPy from '../../../../src/domain/deck_spec.py?raw'` (the same path as the conformance test);
- `pythonModelClasses` and `pythonModelFieldAnnotations` from `../../test/pydanticSource`;
- the golden JSON (`?raw`);
- `renderDeckSpecMarkdown`;
- `parseMarkdown`, `blockTexts`, `normaliseText` and `plainText`;
- `SpecView` from `../../components/SpecView/SpecView`;
- `render` from `@testing-library/react`.

**(a) Classification + mutation.** Sketch (the test author owns the final code; keep it fail-closed):

```ts
type Coverage = 'rendered' | { excluded: string };
const COVERAGE: Record<string, Record<string, Coverage>> = {
  DeckSpec: { title: 'rendered', audience: 'rendered', purpose: 'rendered', argument: 'rendered', call_to_action: 'rendered',
              narrative_arc: 'rendered', design_contract: 'rendered', resolved_data: 'rendered', slides: 'rendered' },
  SlideSpec: { position: 'rendered', purpose: 'rendered', content_brief: 'rendered', assumes: 'rendered', hands_off: 'rendered',
               data_references: 'rendered', slide_type: 'rendered',
               template_section_index: { excluded: 'Machine binding index into the pinned template; slide_type names the same binding '
                 + 'by its data-label and the pair is validated together (invalid_slide_bindings). A 0-based index next to a 1-based '
                 + '"Slide N" heading misleads a reader.' } },
  DesignContractRef: { design_system_id: 'rendered', template_id: 'rendered', slide_style_id: 'rendered' },
  ResolvedData: { synthesis: 'rendered', figures: 'rendered', gaps: 'rendered' },
  ResolvedFigure: { key: 'rendered', value: 'rendered', source: 'rendered' },
};
/** Where each model's instances live in a spec (every instance is mutated, one at a time). */
const INSTANCES: Record<string, (s: DeckSpec) => object[]> = {
  DeckSpec: (s) => [s], SlideSpec: (s) => s.slides, DesignContractRef: (s) => [s.design_contract],
  ResolvedData: (s) => [s.resolved_data], ResolvedFigure: (s) => s.resolved_data.figures,
};
const SENTINEL = 'ZQXMUTSENTINEL';
function kindOf(annotation: string, models: string[]): 'str' | 'int' | 'list[str]' | 'list[model]' | 'model' {
  const inner = annotation.replace(/^Optional\[(.*)\]$/, '$1');
  if (inner === 'str') return 'str';
  if (inner === 'int') return 'int';
  if (inner === 'list[str]') return 'list[str]';
  const listOf = /^list\[(\w+)\]$/.exec(inner);
  if (listOf && models.includes(listOf[1])) return 'list[model]';
  if (models.includes(inner)) return 'model';
  throw new Error(`deck_spec.py annotation "${annotation}" has no mutation rule — extend this guard`);
}
```

Tests:
1. *the Python models were read at all*. `pythonModelClasses(deckSpecPy)` is non-empty and includes `DeckSpec`. This is a precondition
   in its own test.
2. *every model is classified and has an instance accessor*. The class list equals `Object.keys(COVERAGE)`, and equals
   `Object.keys(INSTANCES)`, sorted.
3. `it.each(models)` — *%s: COVERAGE lists exactly the Python fields*. Compare both directions, with a diff message naming the missing
   or stale field and saying "classify it as 'rendered' or { excluded: reason }".
4. *every excluded field states a reason*. The reason is a non-empty string of ≥ 20 characters.
5. `it.each(models)` — *%s: every fixture instance carries every field as an own key*. There must be ≥ 1 instance per model.
6. `it.each(leaf fields)` — *%s.%s behaves as classified*:
   - for each instance index `i`, take a clone, mutate instance `i`'s field by kind:
     - `str` → `SENTINEL`;
     - `int` → `900000`;
     - `list[str]` → `[...old, SENTINEL]`;
     - `list[model]` → `[]`;
   - `'rendered'` → the output differs from `renderDeckSpecMarkdown(GOLDEN)`. For `str`/`list[str]`, `plainText(parse(out))` also
     contains `SENTINEL`.
   - `excluded` → the output is byte-identical.
7. *a bare-model field is rendered iff its model renders something*. For `design_contract` and `resolved_data`.

*Sabotage targets:*
- stop emitting the `Data references` line (SlideSpec.data_references red);
- start emitting `template_section_index` (excluded red);
- emit `Slide type` only for `slides[0]` (red on instance 1);
- the reviewer adds a scratch field `notes: str` to `SlideSpec` in `deck_spec.py` (test 3 red; revert).

**(b) Spec-view parity.** Use three fixtures (`it.each`): `GOLDEN`; `EMPTY` (all ids null, `narrative_arc`, `slides`, `figures` and
`gaps` empty, scalar fields non-empty); and `SLIDE_STYLE` (GOLDEN with `design_contract: { design_system_id: null, template_id: null, slide_style_id: 5 }`).

```ts
function specViewTexts(container: HTMLElement): string[] {
  const view = container.querySelector('[data-testid="spec-view"]')!;
  const header = view.querySelector('[data-testid="spec-view-header"]')!;
  const out: string[] = [];
  for (const el of Array.from(view.querySelectorAll('*'))) {
    if (header.contains(el)) continue;
    if (el.children.length === 0) out.push(normaliseText(el.textContent ?? ''));
    else for (const n of Array.from(el.childNodes)) if (n.nodeType === Node.TEXT_NODE) out.push(normaliseText(n.textContent ?? ''));
  }
  return out.filter((t) => t !== '');
}
const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const appearsIn = (needle: string, hay: string[]) =>
  hay.some((h) => new RegExp(`(?<![\\p{L}\\p{N}])${escapeRe(needle)}(?![\\p{L}\\p{N}])`, 'u').test(h));
```

The deck is `{ title: 'Deck title differs from the spec title', slide_count: 0, css: '', external_scripts: [], scripts: '', slides: [], deck_spec: fixture }`,
rendered with `onDiscuss={() => undefined}`.

Tests:
- *precondition: the collector sees the populated spec*. For GOLDEN, the collected texts include the normalised audience, `Slide 4`,
  `Design system #7` and `Narrative arc`.
- `it.each(fixtures)` — *every piece of text the Spec view shows appears in the Markdown*. For each text, `appearsIn(t,
  blockTexts(parseMarkdown(renderDeckSpecMarkdown(fixture))))`. Failures are reported as the list of missing texts.

*Sabotage targets:*
- rename the renderer's `## Narrative arc` to `## Story`;
- change the renderer's `No design system or slide style pinned` wording (red on EMPTY);
- in SpecView.tsx, temporarily render `<span>{slide.template_section_index}</span>` inside each brief. This must go red on GOLDEN via
  `12`, which is why the fixture uses 12. Revert.

Steps:
- [ ] **Step 1 (test author):** write the file. It should be **green on arrival** against Task 3. Run every listed sabotage and paste the
  red output for each; restore and confirm green. Leave uncommitted.
- [ ] **Step 2 (implementer):** none expected. If a guard is red against Task 3's renderer, STOP and report: it is either a renderer
  defect or a guard defect, and Opus rules.
- [ ] **Step 3:** `npx vitest run src/services/__tests__/deckSpecMarkdownCoverage.test.tsx src/components/SpecView` is green, and
  `npx eslint` on the new file is clean.

---

## Task 5: Download helper

**Models:** test=sonnet impl=haiku

**Files:** create `frontend/src/test/readBlobText.ts`, `frontend/src/utils/downloadFile.ts` and `frontend/src/utils/downloadFile.test.ts`.

```ts
// frontend/src/test/readBlobText.ts — jsdom's Blob has no .text() (verified 2026-10-19); FileReader works.
export function readBlobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}
```

```ts
// frontend/src/utils/downloadFile.ts
/**
 * How long the object URL outlives the click. Safari and Firefox have historically failed a
 * download whose blob URL was revoked synchronously; a small text blob held for 10 s costs nothing.
 */
export const REVOKE_DELAY_MS = 10_000;

/**
 * Save `text` as a file named `filename`, through a transient object URL and <a download>.
 *
 * Deliberately NOT the synchronous revoke of hooks/useDeckExport.ts: that path's only Playwright
 * test checks the filename, not the bytes.
 */
export function downloadTextFile(text: string, filename: string, mimeType: string): void {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}
```

Test setup:
- Stub `URL.createObjectURL` and `URL.revokeObjectURL` with
  `Object.defineProperty(URL, '…', { configurable: true, writable: true, value: vi.fn(…) })`, because jsdom lacks both.
  `delete` them in `afterEach`.
- `vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { … })` records
  `this.download`, `this.getAttribute('href')` and `this.isConnected`. Without the stub, jsdom logs "not implemented: navigation".
- Keep an ordered call log across the three spies.
- **Fake timers:** `vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })` in `beforeEach`, and `vi.useRealTimers()` in
  `afterEach`. Fake *only* these. Default `vi.useFakeTimers()` also fakes `setImmediate`, which jsdom's FileReader uses, so
  `readBlobText` would never settle (verified, Context).

Steps:
- [ ] **Step 1 (test author):** with the module stubbed to throw, write tests asserting:
  - one Blob is created, with `type === 'text/markdown;charset=utf-8'` and `await readBlobText(blob) === 'héllo — wörld\n'`;
  - exactly one click, with `download === 'a-spec.md'`, the href equal to the created URL, and `isConnected === true` at click time;
  - the call order is `createObjectURL`, then `click`;
  - **revoke is deferred:**
    - immediately after the call, and again after `vi.advanceTimersByTime(REVOKE_DELAY_MS - 1)`, `revokeObjectURL` has **not** been called;
    - after one more `vi.advanceTimersByTime(1)` it has been called exactly once, with the created URL;
    - `REVOKE_DELAY_MS` is imported from the module, and the test also pins it to `10_000`;
  - afterwards `document.querySelectorAll('a[download]').length === 0`.

  *Sabotage:*
  - synchronous `URL.revokeObjectURL(url)` (red at "not yet called");
  - `setTimeout(…, 0)` (red at `REVOKE_DELAY_MS - 1`);
  - revoke a different URL (red);
  - drop `removeChild` (leftover anchor red);
  - click a detached anchor (`isConnected` red);
  - drop `type` (MIME red).

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer):** paste the code as given.
- [ ] **Step 3:** `npx vitest run src/utils/downloadFile.test.ts` is green; `npx eslint src/utils src/test/readBlobText.ts` is clean.

---

## Task 6: The Spec view's Export button

**Models:** test=opus impl=sonnet

**Files:** modify `frontend/src/components/SpecView/SpecView.tsx` and `frontend/src/components/SpecView/SpecView.test.tsx`.

Implementation shape (the implementer writes it; this is the intended diff):

```tsx
import { FileDown } from 'lucide-react';
import { DECK_SPEC_MARKDOWN_MIME, deckSpecMarkdownFilename, renderDeckSpecMarkdown } from '../../services/deckSpecMarkdown';
import { downloadTextFile } from '../../utils/downloadFile';
// …inside the header's `ml-auto` group, after the read-only hint span and before the Discuss Button:
{spec && (
  <Button
    data-testid="spec-export-markdown"
    size="sm"
    variant="outline"
    aria-label="Export spec as Markdown"
    title="Export spec as Markdown"
    onClick={() => downloadTextFile(
      renderDeckSpecMarkdown(spec),
      deckSpecMarkdownFilename(spec.title),
      DECK_SPEC_MARKDOWN_MIME,
    )}
  >
    <FileDown aria-hidden="true" />
    Export spec
  </Button>
)}
```

Add this paragraph to the header comment, after property 3:

```
 * EXPORT SPEC AS MARKDOWN (#318) keeps all three. It is a <button>, not an input. It
 * writes renderDeckSpecMarkdown(spec) only — that function takes a DeckSpec, never the
 * deck, so `slideDeck.css` cannot reach the file (L3). It takes no view state, emits
 * none and makes no request: it downloads the spec this component is already showing,
 * computed at click time from the current props. Shown only when there is a spec.
```

Tests to add to `SpecView.test.tsx`:
- Add a new `describe('SpecView — Export spec as Markdown')` block and extend the header *Sabotage targets* list.
- Use `GOLDEN` and `goldenMarkdown` via `?raw` from `'../../../tests/fixtures/deck-spec-markdown/…'`, and `readBlobText` from
  `'../../test/readBlobText'`.
- Stub the URL APIs and spy on anchor `click` as in Task 5. In this describe's `beforeEach`, call
  `vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })`; in `afterEach`, call `vi.useRealTimers()`. As in Task 5, fake only
  those, or `readBlobText` stalls.
- Build the deck with the existing `makeDeck(…)` (:123). Its `title` is `'Renewal risk, Q3'`, which differs from the golden spec's
  title, so a filename taken from the deck title is caught.
- Its `css` is the existing `COMPILED_DECK_CSS` (:43).

1. *offers Export spec as Markdown when the deck has a spec*. `getByRole('button', { name: 'Export spec as Markdown' })` is in the
   document, with visible text containing `Export spec`. *Sabotage:* remove the button.
2. *offers no export on a specless deck*. For `deck_spec` null, absent, and `slideDeck={null}`: `queryByTestId('spec-export-markdown')`
   is null, and `spec-discuss` is still present. *Sabotage:* render the button unconditionally.
3. *downloads exactly the rendered spec, named after the spec title*. After a click:
   - one click, with `download === 'renewal-risk-q3-emea-apac-spec.md'`;
   - the Blob `type === 'text/markdown;charset=utf-8'` and `await readBlobText(blob) === goldenMarkdown`;
   - revoke not yet called right after the click. After `vi.advanceTimersByTime(REVOKE_DELAY_MS)` (imported from
     `../../utils/downloadFile`), it has been called once with the created URL.

   *Sabotage:* filename from `slideDeck.title`; MIME `text/plain`; pass `spec.audience` instead of the rendered document.
4. *the export carries no compiled style content, though the deck's CSS is in scope* (L3 — a separate test from 3, like the existing
   finding-18b pair). The blob text has no `var(--`, `@media`, `@font-face`, or `/\{[^{}]*:[^{}]*\}/` match.
   *Sabotage:* write `renderDeckSpecMarkdown(spec) + slideDeck!.css`.
5. *the export follows the deck*. Define a local `const EXPORT_REVISED_AUDIENCE = 'The board only, revised before export.'` inside
   the new describe. The existing `REVISED_AUDIENCE` is describe-local (:242) and unreachable, and the existing describe is not
   touched. `rerender` with GOLDEN's audience replaced by it, then click. The blob contains the revised audience and not GOLDEN's
   (normalised) audience. *Sabotage:* `useMemo(() => renderDeckSpecMarkdown(spec!), [])`, or a
   `useRef` latch.
6. *the export issues no network request*. Use `vi.stubGlobal('fetch', vi.fn())` and spy on `XMLHttpRequest.prototype.open`; after a
   click neither is called. Clean up with `vi.unstubAllGlobals()`. *Sabotage:* `void fetch('/api/…')` in the handler.
7. *export stays offered and enabled while the deck review is in progress*. With `reviewInProgress`, the button is enabled and a click
   downloads. *Sabotage:* `{spec && !reviewInProgress && …}` or `disabled={reviewInProgress}`. The second is also caught by
   `deckReviewFlag.test.tsx:111`.
- The existing *renders no input, textarea or contenteditable* test (:295) must stay green unchanged. It proves the button did not
  break property 1.

Steps:
- [ ] **Step 1 (test author):** write tests 1–7; confirm 1, 3–7 red because the button is missing, and 2 green-but-meaningful (its
  sabotage is "render unconditionally", to be run in Step 3). Leave uncommitted.
- [ ] **Step 2 (implementer):** add the button and the header-comment paragraph. Do not touch `AppLayout.tsx`.
- [ ] **Step 3:**
  - `npx vitest run src/components/SpecView src/services/__tests__/deckSpecMarkdownCoverage.test.tsx` is green: SpecView (18 + 7),
    deckReviewFlag (9) and the coverage guards.
  - `npx eslint src/components/SpecView` is clean. `npm run build` is clean.
  - The reviewer runs the sabotages not run by the test author.

---

## Task 7: End-to-end download in the browser

**Models:** test=opus impl=sonnet

**Files:** modify `frontend/tests/e2e/spec-view.spec.ts`. It is already in the CI E2E matrix (`.github/workflows/test.yml:732`); no
workflow change and no new spec file.

Additions:
- Fixtures at the top, directly after `COMPILED_DECK_CSS` (:43–48). **Do not touch :110–145**: #316 edits the `SLIDE0_FINDINGS`
  literals there (Global constraints). The file already imports `readFileSync` (:23); the existing
  `../fixtures/graphLifecycleContract.ts` pattern resolves with `new URL(…, import.meta.url)`.
  ```ts
  const GOLDEN_DIR = new URL('../fixtures/deck-spec-markdown/', import.meta.url);
  const GOLDEN_SPEC = JSON.parse(readFileSync(new URL('full.deck-spec.json', GOLDEN_DIR), 'utf8'));
  const GOLDEN_MARKDOWN = readFileSync(new URL('full.md', GOLDEN_DIR), 'utf8');
  const GOLDEN_FILENAME = 'renewal-risk-q3-emea-apac-spec.md';

  async function exportSpec(page: Page) {
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export spec as Markdown' }).click();
    const download = await downloadPromise;
    return { filename: download.suggestedFilename(), text: readFileSync(await download.path(), 'utf8') };
  }
  ```
- In `test.describe('spec view toggle')` (:208, whose `beforeEach` serves `DECK_SPEC`; a per-test `mockDeckSpec` wins by LIFO, as
  the specless test at :613 does):
  - *Export spec as Markdown downloads the rendered spec, and asks the server for nothing*:
    1. `mockDeckSpec(page, GOLDEN_SPEC)`, `openDeck(page)`, `showSpec(page)`;
    2. wait for `spec-audience` to contain `GOLDEN_SPEC.audience` (the golden is what is showing);
    3. register a request log as in the Discuss test (:400), then call `exportSpec`;
    4. `filename === GOLDEN_FILENAME` and `text === GOLDEN_MARKDOWN` (byte-exact, so this covers UTF-8 `—` and the blob path);
    5. the text has no `var(--`, `@media` or `@font-face` (the served deck carries `COMPILED_DECK_CSS`);
    6. `requests.filter((r) => r.includes('/api/'))` equals `[]`.
  - *a specless deck offers no export*: `mockDeckSpec(page, null)`, open, show the spec; `spec-view-empty` is visible,
    `spec-export-markdown` has count 0, and `spec-discuss` is visible.
- In `test.describe('spec visibility rides deck visibility')` (:633):
  - *a read-only viewer can export the spec*: `mockDeckSpec(page, GOLDEN_SPEC)`, `openDeck(page, 'view')`, `chat-input` is disabled
    (genuinely read-only), show the spec, `exportSpec`; the filename and text equal the golden. (D1: the export rides spec visibility.)
- Extend the file header's *Sabotage targets* with: SpecView export onClick (wrong filename, wrong content), hiding the button on
  `/view`, and adding a fetch to the handler.

Steps:
- [ ] **Step 1 (test author):** write the tests. Run **only while holding the Playwright/dev-server lock**:
  `cd frontend && npx playwright test tests/e2e/spec-view.spec.ts --project=chromium --workers=1`. Expect green on arrival (Task 6 is
  in), then sabotage-verify in the browser:
  - change the `-spec.md` suffix (filename red);
  - pass `spec.audience` (content red);
  - add `void fetch('/api/sessions')` to the onClick (no-request assertion red);
  - remove the button (main and read-only export tests red; the specless test stays green — it is the shape test).

  A sabotage that hides the button **only** on `/view` cannot be written in SpecView: it takes no route or permission prop, which is
  D1's point. The read-only test pins the product decision against a future gating prop.
  Restore everything. If the lock is unavailable, record that the e2e is unrun locally and rely on CI `E2E - spec-view`; do not start
  a dev server.
- [ ] **Step 2 (implementer):** none expected. A red e2e with a green unit suite usually means a browser-only problem (download
  attribute, blob revoke timing, accessible name). STOP and report it.
- [ ] **Step 3:** `npx tsc -b` (tsconfig.e2e typechecks `tests/**/*.ts`) and `npx eslint tests/e2e/spec-view.spec.ts` are clean.

---

## Task 8: Docs

**Models:** test=sonnet impl=haiku (no test file; the sonnet reviewer checks every claim against the code)

- [ ] `docs/technical/export-features.md`:
  - Add to the Overview list: "**Deck spec (Markdown)**: client-side, from the Spec view — see *Deck spec as Markdown*."
  - Add a section **Deck spec as Markdown (client-side)**, covering:
    - **Where:** the Spec view header, *Export spec* (accessible name "Export spec as Markdown"); shown only when the deck has a spec.
    - **Who:** anyone who can see the Spec view, including `/view` (D1). The file includes the Data section, with figure sources (D2).
    - **Which spec:** the live deck's, as the view shows it. A save-point preview shows no spec today, because preview snapshots don't
      carry `deck_spec`, so there is nothing to export while previewing.
    - **What:** D2's order, and the omitted `template_section_index` with its reason. An absent `resolved_data` or `data_references`
      renders `Not set.`/`None.`.
    - **Normalisation, by code point** (not "`\s`": JavaScript and Python disagree on it):
      - remove U+0000–U+0008, U+000E–U+001F, U+007F–U+0084 and U+0086–U+009F;
      - collapse each run of U+0009–U+000D, U+0020, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F,
        U+3000 and U+FEFF to one space;
      - trim.
    - **Escaping:**
      - a backslash before each of `` \ ` * _ [ ] < > # | ~ $ & @ ``;
      - also before a leading `-`/`+`/`=`, and before the `.`/`)` of a leading `N.`/`N)` marker;
      - integer ids and positions are written verbatim. Any other value in a numeric slot is escaped as text, so a non-integer
        position gives `### Slide {escaped value}`, with no +1.
    - **Known ambiguities:**
      - a value that is literally `None.` or `Not set.` reads like the placeholder;
      - `, `-joined data references and `key: value` figures are ambiguous when a value itself contains `, ` or `: `.
    - **Determinism:** D5.
    - **Filename:** D6.
    - **Download:** a Blob, an object URL and `<a download>`. The object URL is revoked `REVOKE_DELAY_MS` (10 s) after the click,
      not synchronously.
    - **No route, no request.**
    - **The contract:** `frontend/tests/fixtures/deck-spec-markdown/full.deck-spec.json` → `full.md`, byte-exact. Any other renderer
      must reproduce it, and changing the format means updating `full.md` in the same change.
    - **Code:** `frontend/src/services/deckSpecMarkdown.ts`, `frontend/src/utils/downloadFile.ts` and
      `frontend/src/components/SpecView/SpecView.tsx` (repo-root paths).
  - *File Naming*:
    - replace the opening "Both export formats use timestamped filenames:" with "PDF and PPTX filenames are timestamped; the deck
      spec's is not:";
    - add `- **Deck spec**: {title-slug}-spec.md (no timestamp; deck-spec.md when the title has no letters or digits)`.
- [ ] `docs/technical/frontend-overview.md`, *Component Responsibilities* table — **append** three rows at the **end** of the table,
  after the `src/components/PresentationMode/PresentationMode.tsx` row (:370). Do not interleave them: #316, #319, #321 and #323 edit
  rows above. Keep this table's own convention of frontend-relative `src/…` paths, as every existing row does.
  - `src/components/SpecView/SpecView.tsx`: read-only view of `deck_spec`, toggled with Slides; Discuss hands off to the chat; Export
    spec downloads Markdown. Touchpoints: none (reads the deck in hand).
  - `src/services/deckSpecMarkdown.ts`: pure, deterministic `DeckSpec` → Markdown, plus the filename. Touchpoints: none.
  - `src/utils/downloadFile.ts`: saves a string as a file through an object URL, with a deferred revoke. Touchpoints: none.
- [ ] `docs/technical/url-routing.md:275`: replace the stale `tests/viewer-readonly.spec.ts` row with:

  ```
  | `tests/viewer-readonly.spec.ts` | 5 | Disabled chat, read-only slides, hidden session buttons, verification badge kept; spec export on `/view` is covered by `spec-view.spec.ts` |
  ```

  - It makes no claim about deck export, which the page header hides on `/view`.
  - Leave the section's historical totals line alone.
- [ ] `docs/user-guide/01-generating-slides.md`: add a new `## Reviewing the Deck Spec` section after `## Returning to a Previous Session`
  (:72) and before `## Tips` (:76). Do not put it after "Navigating Slides", which is #316's anchor. Plain second person, no
  screenshots:
  - Click **Spec** above the slide viewer to see the plan the agents work from.
  - It is read-only; click **Discuss** to change it in the chat.
  - Click **Export spec** to download it as a Markdown file named after the deck, for review or sharing outside Tellr. The file holds
    everything in the Spec view, plus each slide's type, the data it uses, and the data gaps the agents recorded.
- [ ] The reviewer greps that each doc claim matches the code:
  - labels, the filename pattern, the section names (`Data`, not `Resolved data`) and the omitted field;
  - the two code-point sets, which must equal `CONTROL_CHARS`/`WHITESPACE_RUN` in `deckSpecMarkdown.ts`;
  - the escape set, which must equal `ESCAPE_ANYWHERE`;
  - `REVOKE_DELAY_MS`.

---

## Task 9: Verification and whole-branch review

**Models:** test=opus impl=sonnet (controller runs the gates; the whole-branch review is Opus)

- [ ] `cd frontend && npm run test:unit`: the failing-cause set equals Task 0's (the 20 *reading 'clear'* failures in the same three
  files) and nothing else. New suites are all green.
- [ ] `npm run build`, plus `npx eslint` over every touched or new frontend file, are clean.
- [ ] `uv run pytest tests/unit -n 4 -q`: the failing-cause set equals the baseline, plus the new file green.
- [ ] E2E `spec-view.spec.ts`, under the lock (or recorded as CI-gated).
- [ ] **Sabotage ledger.** Every reviewer-approved test from Tasks 1–7 has had its listed sabotage run, red pasted, then restored.
  Grep for leftover markers (`ZQXMUT`, `notes: str`, `Story`, `text/plain`).
- [ ] `git diff --stat` touches only the File-map files. `AppLayout.tsx`, `slide.ts`, `deck_spec.py` and the prompts are unchanged.
  The `package.json` and `package-lock.json` diffs are one added line each (Task 3).
- [ ] `grep -c npm-proxy.cloud.databricks.com frontend/package-lock.json` prints `0`.
- [ ] `shasum -a 256` of the two fixtures still equals the values pinned in Task 2.
- [ ] **Whole-branch review (Opus).** Ask explicitly for:
  - (1) a writer-by-writer check that every value-writing site in the renderer goes through `escapeText`;
  - (2) a ruling that SpecView's three properties hold;
  - (3) a merge/no-merge verdict. Hand it the **[review]** items: D1 viewer export, D2 Data section with sources, D6 spec-title filename.
- [ ] **Commits:** the supervisor has committed each reviewer-approved task as it landed. Each commit has a conventional message,
  ending with `Co-authored-by: Isaac <no-reply@databricks.com>`, and is made as its own `git commit` command. Sub-agents never
  commit. No push unless the user asks.

---

## Out of scope (follow-ups)

- A backend or MCP renderer, endpoint or tool (D1). The contract is the golden pair. MCP must first expose the spec at all.
- Import or editing from Markdown. The spec stays conversational, with a single write path.
- Other spec formats (PDF, DOCX, JSON).
- Design-system and template **names** instead of ids (it would need a fetch; it should change the Spec view and the export together).
- Showing `resolved_data`, `slide_type` or `data_references` in the Spec view itself.
- Refactoring `useDeckExport.ts`'s two inline download closures onto `downloadTextFile`.
- Tour, WelcomeModal and Help copy mentioning the export (`tourSteps.test.ts` pins the copy).
- Adding the spec export to the page-header Export menu, and the header's `/view` hiding of deck exports.
- **Save-point previews carry no spec.** `get_version` (`session_manager.py:2653`) should serve `version.deck_spec_json` as
  `deck["deck_spec"]`.
  - Then the Spec view, and with it this export, would show the previewed version's plan.
  - Today the preview falls into SpecView's empty state, whose copy ("decks built before the architect…") is misleading there.
- Preserving intended line structure in multi-line values (both views flatten it today).
- GFM autolinking of bare URLs or emails, and Unicode bidi/format characters in values.
- Sibling issues #323, #321, #319, #316, #313 and #314. #314 (insert a slide) changes positions, not fields; the export reads positions
  as given.

## Open risks

1. **[review] Viewer export and the Data section (D1, D2).** The spec export is available on `/view`, while the header hides deck
   exports there. The file includes the `Data` section, with figure `source` identifiers and architect notes that no UI surface shows.
   - Ruling: keep option (a). A reviewer outside the app needs the sources to check the figures, every viewer already receives them in
     the `get_slides` JSON, and the exporter chooses whom to share with.
   - Alternatives: (b) omit `source`; (c) omit `## Data` on `/view` (needs a gating prop).
2. **[review] Filename from the spec title (D6).** It can differ from a session name the user renamed in the header.
3. **Lockfile and the Databricks npm proxy.** The local registry is `npm-proxy.cloud.databricks.com`.
   - `npm install <pkg>` would re-resolve `mdast-util-from-markdown` to 2.1.0 and write proxy `resolved` URLs. CI's runner cannot
     reach those, and they would leak an internal hostname into a public repo. The fallback would also leave `package.json` and the
     lock out of sync, failing `npm ci` on Node 20.
   - Mitigation: hand-edit the two lines, run argument-less `npm install --package-lock-only --ignore-scripts`, require a two-line
     diff, and require `grep -c npm-proxy…` = 0 (Task 3, Task 9).
   - CI's `npm ci` is the final word.
4. **Revoke timing.** Resolved by deferring the revoke `REVOKE_DELAY_MS` (10 s), which avoids the historical Safari/Firefox
   synchronous-revoke failures.
   - The residual risk is test-side only. Default `vi.useFakeTimers()` stalls jsdom's FileReader, so Tasks 5 and 6 fake only
     `setTimeout`/`clearTimeout`.
   - `useDeckExport.ts` keeps its synchronous revokes (out of scope).
5. **Playwright name matching is substring and case-insensitive.** `getByRole('button', { name: 'Export' })` (used 16× in
   `export-ui.spec.ts`/`slide-operations-ui.spec.ts`) would also match "Export spec as Markdown" whenever the Spec pane is *visible*.
   Today those tests never show the pane, and a hidden pane is out of the accessibility tree. A future test that does should use
   `exact: true`.
6. **Raw readability.** Escaping makes the raw file noisier (`churn\_rate`, `\$4.2M`, `\#1`). It renders cleanly. This is the price of
   structural safety.
7. **The golden is a contract.** Any intentional format change must update `full.md`, the docs, and (later) the backend renderer
   together. Task 4's guard and the Python fixture test make silent drift red.
8. **Node 26 local unit failures** (`localStorage`). None of the new tests touch storage. Judge regressions by cause, not count.

## Self-review (plan author)

1. **Coverage.**
   - AC1 is covered by Tasks 3, 5, 6 and 7. AC2 by Tasks 3 and 4.
   - All nine of the brief's decision points are resolved. D9 adds the parser decision.
   - The requested tests exist: golden, escaping, empty/optional, determinism, both guards, the component button, and the e2e download
     with its filename.
   - Every test has a sabotage target.
2. **Placeholder scan.** None. Every task names its files, interfaces, tests and commands.
3. **Symbols.** Every existing symbol cited was grepped on 2026-10-19 at 679d2f21, and re-grepped for r2.
   - New exported symbols: `renderDeckSpecMarkdown`, `deckSpecMarkdownFilename`, `DECK_SPEC_MARKDOWN_MIME`, `downloadTextFile`,
     `REVOKE_DELAY_MS`, `readBlobText`, `pythonModelFieldAnnotations`, `pythonModelClasses`, and the `markdownStructure` helpers
     (`normaliseText` replaces r1's `normaliseWhitespace`).
   - Module-private: `escapeText`, `normalise` and `num`.
   - They are defined here and used consistently.
4. **Same-file sequencing.** No two tasks edit one file. Shared readers (fixtures, `deck_spec.py`) are read-only after Task 2.
5. **Model tags.** Every task carries `Models:` with test ≥ impl.

## Revision r2 — rulings applied (PLAN-REVIEW.md)

| # | Change |
|---|---|
| 1 | Task 3 Step 1.1 hand-edits the two lines and runs an argument-less `npm install --package-lock-only`. It requires an exact two-line diff and 0 proxy URLs. "Never `npm install <pkg>`" is added to Global constraints, the grep to Tasks 0 and 9, and Open risk 3 is rewritten. |
| 2 | Previews carry no `deck_spec`. Context, D1 WYSIWYG and the Task 8 "Which spec" line are corrected. The "label a preview" item is replaced by the `get_version` follow-up. |
| 3 | Filename rows: `'𝒜'.repeat(100)` and `'a' + '𝒜'.repeat(100)`, with the sabotage rationale. |
| 4 | Defaults for `resolved_data` (and its parts) and `data_references`, plus an *absent containers* test. There is still no tolerance for `narrative_arc`/`slides`. |
| 5 | `num()`. An integer `position` gives `Slide {position+1}`, anything else the escaped raw value. Ids go through `num`. Adds a *numeric slots* test with `position: '<b>x</b>'`. |
| 6 | D2 **[review]**: keep the Data section with sources (option a), with the rationale and options (b)/(c). Open risk 1 is updated. |
| 7 | The "older doc claims" clause is dropped from D1. Task 8 fixes `url-routing.md:275`. |
| 8 | User-guide section moves after "Returning to a Previous Session". frontend-overview rows are appended at the end. `spec-view.spec.ts` stays out of :110–145. The overlaps are listed in Global constraints. |
| 9 | Deferred revoke: `REVOKE_DELAY_MS = 10_000`. Task 5 tests it with `toFake: ['setTimeout','clearTimeout']`, because default fake timers stall jsdom's FileReader (probed). Task 6 test 3 is updated, and D7, Open risk 4 and the docs follow. |
| 10 | Task 2 extracts the fixtures with `sed` ranges and checks the pinned sha256 values; no retyping. |
| 11 | The golden JSON gains a tab, U+00A0, U+2028, U+0085 and U+001F, and `full.md` is unchanged. The code-point sets are explicit in D4, the code and the docs. |
| 12–16, 20 | Both brackets in the bracket sabotage; a local `EXPORT_REVISED_AUDIENCE`; the Task 1 sabotage symptom; the lint baseline (63 errors / 9 warnings); "FileDown is defined"; File Naming wording, `SpecView.test.tsx:295`, `test.yml:603–625`, `vi.useRealTimers()`. |
| 17 | NEL (U+0085) is whitespace. The control test uses `nel\u0085end` → `nel end`. |
| 18 | The ambiguities are noted in D2 and in the docs. |
| 19 | `@` is added to `ESCAPE_ANYWHERE` and to the GitHub-only string test. |
| supervisor | Commit policy (the supervisor commits, sub-agents never do). Repo-root `frontend/src/…` paths in the export-features doc text. |
