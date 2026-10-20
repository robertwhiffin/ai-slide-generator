# #318 Export the deck spec as Markdown — notes for the reviewer

- **Issue:** robertwhiffin/ai-slide-generator#318
- **Branch:** `feat/318-export-spec-markdown` (base `origin/main` 679d2f21)
- **Plan:** `docs/superpowers/plans/2026-10-19-issue-318-export-spec-markdown.md` (revision r2, after an
  independent plan review; the "Revision r2" table at its end lists what the review changed)
- Built test-first: for every task one agent wrote failing tests, a second implemented them, and a third
  reviewed by breaking production code and checking the tests went red. A final whole-branch review
  gave a **merge** verdict.

## What shipped, by acceptance criterion

| Acceptance criterion | How it is met | Proved by |
|---|---|---|
| An "Export spec as Markdown" action in the Spec view downloads a `.md` rendering of the current deck spec. | An **Export spec** button (accessible name "Export spec as Markdown") in the Spec view header, next to Discuss. It renders the spec the view is showing at click time and downloads `<slug>-spec.md` as `text/markdown;charset=utf-8`. It makes no request. | `SpecView.test.tsx` (7 new tests); `spec-view.spec.ts` e2e: the browser download equals `full.md` byte for byte, has the right name, makes no `/api/` request, and works on the read-only `/view` route. |
| Rendering is deterministic and covers every `DeckSpec`/`SlideSpec` field users see in the Spec view. | `renderDeckSpecMarkdown(spec)` is a pure function with a fixed section order. It renders every field the Spec view shows, plus the title, slide type, data references and the resolved data. Only `template_section_index` is left out, for a stated reason. | `deckSpecMarkdown.test.ts` (986 tests): the golden file, escaping, empty and optional fields, determinism and the filename. `deckSpecMarkdownCoverage.test.tsx` (64 tests): two guards that go red if a field is added and not exported. |

### Files
- `frontend/src/services/deckSpecMarkdown.ts`: the renderer, `deckSpecMarkdownFilename` and the MIME constant.
- `frontend/src/utils/downloadFile.ts`: `downloadTextFile`. It saves through a Blob and an object URL, and revokes the URL `REVOKE_DELAY_MS` (10 s) after the click.
- `frontend/src/components/SpecView/SpecView.tsx`: the button, plus a header-comment note on why the three SpecView properties still hold.
- Golden contract: `frontend/tests/fixtures/deck-spec-markdown/full.deck-spec.json` → `full.md`, byte-exact, with `eol=lf`.
  `tests/unit/test_deck_spec_markdown_fixture.py` checks that the JSON is a valid, fully spelled-out `DeckSpec` that round-trips through the model.
- Test helpers:
  - `frontend/src/test/pydanticSource.ts`: the Pydantic-source reader, moved out of `deckSpecConformance.test.ts` (an import-only change there) plus an annotation reader.
  - `frontend/src/test/markdownStructure.ts`: a real CommonMark parse.
  - `frontend/src/test/readBlobText.ts`.
- `frontend/package.json` and `package-lock.json`: one devDependency line each, `mdast-util-from-markdown ^2.0.3`. It was already installed at 2.0.3 through react-markdown. The lock has no internal-proxy URLs.
- Docs:
  - `docs/technical/export-features.md` has a new section.
  - `docs/technical/frontend-overview.md` has three rows.
  - `docs/user-guide/01-generating-slides.md` has a new "Reviewing the Deck Spec" section.
  - The stale viewer row in `docs/technical/url-routing.md` is fixed.

## Decisions made on your behalf (please confirm or overturn)

1. **Rendered in the frontend only; no new endpoint.**
   - The Spec view already holds the spec (`deck_spec` arrives with `get_slides`), and its design says "no spec fetch". An endpoint would add a permission surface and route tests for no consumer.
   - The MCP server does not expose the spec at all today.
   - Follow-up contract: a Python or MCP renderer must reproduce `full.md` from `full.deck-spec.json` byte for byte.
2. **Read-only `/view` visitors can export the spec.** This follows the existing "spec visibility rides deck visibility" rule; the viewer's browser already holds the whole spec.
   - The page header hides the *deck* exports on `/view`. If you want parity with that, gate the button on a new SpecView prop. That is view-independent, so the three properties still hold.
3. **The export carries more than the Spec view shows:**
   - the title, as the H1;
   - `slide_type`, when it is set;
   - `data_references`;
   - a `## Data` section: synthesis, figures as `key: value (source: …)`, and gaps.

   Sources are what a reviewer outside the app needs to check the figures. The alternatives were to omit `source`, or to omit `## Data` on `/view`.
   - Only `template_section_index` is excluded. It is a 0-based machine index, and `slide_type` names the same binding.
4. **Multi-line values are collapsed to one line.** The Spec view displays them that way too (`white-space: normal`), and it makes structural injection impossible by construction.
   - Every user value is then backslash-escaped, along with a leading `-`/`+`/`=` and a leading 1–9-digit ordered-list marker.
   - The control and whitespace sets are spelled out by code point, so a port to another language cannot drift.
5. **The filename comes from the spec's title, not the session name in the header:** `<slug>-spec.md`.
   - The slug keeps letters, digits and marks in any script, is NFC-normalised, and is cut at 60 code points.
   - The fallback is `deck-spec.md`.
   - A renamed session therefore exports under the architect's title.
6. **The button is hidden when there is no spec**, and never disabled or hidden during the deck review.
7. **The object URL is revoked 10 s after the click, not synchronously.** Synchronous revoke has historically broken Safari and Firefox downloads, and a text blob costs almost nothing to keep alive.
8. **`$` and `@` stay escaped, even though GitHub ignores those escapes** (see Known gaps). They are harmless, and renderers such as pandoc honour them.

## Deviations from the plan, and why
- **Task order.** Task 6 (the button) ran before Task 4 (the guards). They touch disjoint files, and the parity guard excludes the header that holds the button.
- **Reviewers added tests where a sabotage stayed green.** Each addition was then shown to go red under that sabotage:
  - long values: truncating values to 300 characters had left all 969 tests green;
  - a synthetic-DOM self-test for the parity collector;
  - an exact-output test that pins the 1–9 digit cap on the ordered-list marker;
  - a raw-byte BOM check, because jsdom's FileReader strips a BOM;
  - a second text/filename/MIME triple for the download helper;
  - a `class Kind(Enum)` trap for the Pydantic reader.
- **Plan-review finding 19 was wrong in its premise.** It claimed the `@` escape "stops GitHub mentions". Re-checking with GitHub's markdown API showed it does not. The code comment, one test title and the doc were corrected; behaviour is unchanged.
- **Outage.** The run was interrupted by an API budget 403, which killed every agent at once. The Task 4 test author died mid-sabotage, leaving a scratch `notes: str` field in `src/domain/deck_spec.py`. I reverted it, re-ran the sabotages that had not been verified (all red or green as expected), and had the task reviewed before committing.
- **Per-task review of Tasks 2 and 7 was done by the supervisor**, not a separate reviewer agent:
  - Task 2: a hash check plus a fresh sabotage.
  - Task 7: a read of the diff. Its opus author had already sabotage-verified in the browser.

## Test evidence

- **Frontend unit tests** (`npm run test:unit`, local Node 26): 2217 passed, 20 failed.
  - The 20 failures are exactly the baseline cause: Node 26's global `localStorage` shadows jsdom's, in FindingsE2, SlideViewer and TourViewerBridge.
  - The baseline before any change was the same 20, so the cause set is unchanged. CI runs Node 20.
- **New or changed suites:** all green.
  - renderer: 986
  - coverage guards: 64
  - SpecView: 25, plus deckReviewFlag: 9
  - download helper: 7
  - pydanticSource: 9, plus conformance: 13
- **Backend:** `uv run pytest tests/unit -n 4` gives 9170 passed, 135 skipped, 0 failed. The baseline was 9166, plus 4 new.
- **Build and lint:** `npm run build` OK. `tsc -b` clean. eslint clean on every touched file.
- **e2e:** `spec-view.spec.ts` passed 23/23 locally (20 existing tests plus 3 new), under the shared e2e lock.
  - It ran on the installed Google Chrome through a throwaway config. The bundled `chromium_headless_shell-1200` that Playwright 1.57 needs is missing from the local cache.
  - CI's `E2E - spec-view` job is the bundled-chromium gate.

**Sabotage runs.** Each broke the production line a test guards; each went red and was then restored. This is a selection; the full list is in the run ledger.

| Area | Broken | Went red |
|---|---|---|
| Escaping | each of `# [] - + = \ & < > backtick * _ \| ~ $ @` dropped from the escaper; the leading-marker rule; the ordered-marker rule; whitespace collapse narrowed to spaces | the parsed-structure matrix (14 slots × 62 hostile values), or the GFM string test |
| Content | arc sorted or reversed; slides sorted; heading taken from the list index; figure source dropped; one gap only; `,` join; Slide type moved before Assumes; values truncated | golden, structure, guard (a) |
| Determinism | `new Date()` appended; `Object.entries` order; `toLocaleString` on ids | golden, fake-clock, locale tests |
| Coverage guards | a new field `notes: str`; a new model; a `float` annotation; `template_section_index` rendered; `## Story` heading; a label renamed in SpecView; `template_section_index` shown in SpecView | guards (a) and (b) |
| Button | removed; name from the deck title; wrong MIME; wrong content; unconditional; CSS appended; memo or ref latch; fetch or XHR in the handler (sync or deferred); gated on review; moved outside the header | SpecView tests |
| Download | sync revoke; delay 0 or ±1; wrong URL; no removeChild; detached anchor; BOM; hardcoded name, MIME or text | downloadFile tests |
| Browser | `-plan.md` suffix; audience instead of the document; fetch before or after the download; button removed or unconditional | e2e |
| Fixture | L1 violation; a key deleted; a padded `slide_type`; CRLF, BOM or invalid UTF-8 in `full.md` | pytest |

## CI history
(Filled in after the PR's CI runs; see the PR.)

## Known gaps and follow-ups
- **Save-point previews show no spec.** `get_version` serves only `deck_json`, which never carries `deck_spec`. The Spec view therefore shows its empty state while previewing, and the button is hidden. This is pre-existing.
  - Follow-up: have `get_version` serve the version's `deck_spec_json` as `deck.deck_spec`.
- **Pasting into GitHub.** This was checked against GitHub's markdown API on 2026-10-20.
  - GitHub honours `\|` and `\~`.
  - Its math, @-mention, `#N` reference and bare-URL/email autolinking ignore backslash escapes. A value with two `$` on one line can render as inline math, `@name` still mentions, and the fixed `Design system #7` / `Template #3` lines link to issues 7 and 3 in whatever repo the file is pasted into.
  - The structure is unaffected. It is documented in `export-features.md`.
- **A spec with corrupt `resolved_data`** (e.g. `figures: [null]`, from a hand-edited column) still renders in the Spec view, but the click throws silently. No validated writer produces that.
  - A spec missing `narrative_arc` or `slides` crashes SpecView itself first, which is pre-existing behaviour.
- **A test hazard, not a defect today.** `export-ui.spec.ts:372/:483/:494` use `page.locator('header').getByText(/Exporting|Starting|Export/)`. SpecView's header is also a `<header>`, and `getByText` matches hidden elements.
  - This is safe while those mocks carry no `deck_spec`. If one ever does, the test fails loudly rather than passing falsely.
- **Not pinned by tests:** the button's `title` attribute, and its order relative to Discuss.
- **Backend or MCP renderer:** out of scope. The golden pair is its contract.
- **Pre-existing:** `tsconfig.app.json` excludes `*.test.*`, so `tsc -b` never type-checks test files. The reviewers type-checked this branch's test files with a throwaway config, and they were clean.

## Not verified locally
- The e2e on CI's bundled chromium. It was verified locally on Google Chrome; CI decides.
- Download behaviour in Safari and Firefox. That is the reason for the deferred revoke; it was not exercised.
