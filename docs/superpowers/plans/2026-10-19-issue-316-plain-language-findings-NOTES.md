# Issue #316: plain-language review findings — notes for the reviewer

**Branch:** `feat/316-plain-language-findings` (base `679d2f21`)
**Plan:** `docs/superpowers/plans/2026-10-19-issue-316-plain-language-findings.md`. The plan-vs-code corrections (C1–C13) and the plan review are kept outside the repo, in the supervisor ledger. Every place where a correction changed the plan is listed under "Deviations" below.
**Eval spend:** $0 of the $15 cap. No reviewer prompt, schema or payload changed, so there was nothing to evaluate.

## What shipped, by acceptance criterion

**AC1: findings shown in the UI (drawer and chat) carry a plain-language message.**

- **Drawer.** Each finding leads with `plainMessage`, for example "Some text was hard to read against its background. This was fixed automatically." (`FeedbackDrawer.tsx`).
- **Chat, Apply and Discuss.** The request leads with `Please fix this on slide N: <plainIssue>` or `I'd like to discuss this on slide N: <plainIssue>`. The issue sentence alone is used, so a request never says "it was left unchanged" in the user's own voice (`AppLayout.tsx`, `utils/findingText.ts`).
- **Chat, deck-review advisory.** Plain lines with no criterion slug:
  - one line per deck-level criterion;
  - repeats merged as "(noted N times)";
  - any other criterion gets the generic line "One of the slides may need a closer look.";
  - then a closing line (`_advisory_text` in `src/services/graph/nodes.py`).

  The no-findings sentence is byte-identical to before.

**AC1: the technical detail remains available to the fixer.**

- `Finding` is unchanged, and so are the fixer, fix-reviewer and architect payloads.
- Task 2 pins every agent route to `message` verbatim with exactly `Finding`'s keys and no plain copy: the fixer payload, the fix-reviewer payload, the persisted record, and the next turn's `previous_deck_review` (`TestReviewersKeepTheTechnicalMessage`).

**AC1: optionally, behind a "details" disclosure.** There are two disclosures:

- **Drawer.** A per-finding **Show details / Hide details** toggle, with these properties:
  - collapsed by default;
  - keyed by finding id, and not persisted;
  - the technical text is absent from the DOM until the toggle is opened.
- **Chat.** `Message.tsx` folds everything after the `"\n\nReviewer's details:\n"` separator behind a closed native `<details>` labelled "Reviewer's details".
  - It applies to exactly two strictly matched, role-bound shapes: a user Apply/Discuss request and the assistant deck advisory.
  - It is render-only. What is sent, stored, polled and returned by MCP is unchanged, so the architect still gets the detail.

**AC2: the source of the plain text is decided without casually changing frozen schemas.**

- The text is deterministic copy in a new pure module, `src/domain/finding_copy.py`.
- It is derived at read time from `criterion`, the registry's `objective` and `status`, and never from `message`.
- It is projected as two keys in `_finding_to_camel`: `plainMessage` and `plainIssue`.
- These are never a `Finding` field, are never persisted, and never appear in a prompt.
- **No digest moved.** The frozen-path guard below is empty, the schema/digest tests are green, and there was no promote, contract re-record or eval.

## Decisions made on the user's behalf

1. **Option (c), deterministic copy, over (a) a new reviewer output field and (b) a rewrite step.**
   - Against (a): `Finding` is nested in `SlideReviewOutput`/`DeckReviewOutput`, and the schema digest hashes `model_json_schema()`. Even an optional field no model fills would move the v1 and v2 digests of build_reviewer, fix_reviewer and deck_reviewer. The plan reviewer verified this by computing the schema. (a) would also need a prompt migration, and `promote.py` refuses build_reviewer, which is a transition source. `_HISTORICAL_DIGESTS` is the sanctioned route for additive changes, so (a) is possible, but it costs more than this issue justifies.
   - Against (b): it adds a model call per slide, with the latency, cost and new failure mode that brings.
   - Against both: the output is still unguaranteed prose, and old persisted findings would lack it.
   - What (c) gives: zero cost, and old findings render for free.
   - **The trade-off is specificity.** The drawer says "Some text…", not "The 'NOTE' label…". The specifics are one click away. Extracting a subject from `message` was rejected as a trap: it is a regex over model prose that can pull out CSS or class names.
2. **A second key, `plainIssue`, for the Apply/Discuss lead**, so the user's request does not end with a status sentence.
3. **Apply/Discuss still send the technical text, collapsed in the bubble.**
   - The architect's payload has no slide findings, so without the detail Apply could not know what to fix.
   - A hidden agent-only channel would need a new `ChatRequest` field, a pinned payload key and a prompt change: the digest and promote work that (c) avoids.
4. **Hybrid deck advisory.** It shows plain lines, then the reviewer's messages under the same collapsible separator.
   - The deck reviewer's messages carry the only actionable slide references.
   - Sibling #321's `metadata.details` mechanism is unmerged, so this PR cannot depend on it. It uses a content-shape parse instead and leaves `_surface_notice` untouched.
   - `info` rows are not replayed to the architect, so the details never become agent context.
   - Follow-up: move both shapes onto #321's `metadata.details` once #321 merges.
5. **Wording follows #321's style**: second person allowed in action lines, 1-based slide numbers, contractions. The copy rules are enforced by a banned-pattern sweep over every string: no digits, hex, px, rgb/hsl, ratios, WCAG/AA, underscores, criterion slugs or role names.
6. **Copy table (D8 in the plan)**: one present-tense and one past-tense sentence per criterion, plus four status sentences:
   - "This was fixed automatically."
   - "This was not fixed automatically."
   - "This is a judgement call, so it was left for you to decide."
   - "This has been addressed." (no producer today)
7. **Contrast.** The chat-bubble details text uses full-opacity `text-primary-foreground` on the user bubble (5.20:1). The `/80` variant would be 3.91:1, below AA, which is this issue's own subject. The assistant bubble uses `text-muted-foreground` (4.61:1 light, 6.92:1 dark).

## Deviations from the plan, and why

- **Corrections C1–C13 applied.** The main ones:
  - The frozen-path guard was rewritten with inline pathspecs. Under zsh the planned `$FROZEN` variable became one pathspec, so the guard could never fail.
  - The fixture-literal regex was tightened so it does not match e2e test bodies.
  - The blob-path "never written back" test checks `verification_map`, which is where the write actually lands.
  - The Task 7 negative tests were made non-vacuous (exact separator; `not.toBeVisible()`).
- **Task 2 had no separate Haiku "implementer".** It is tests only and needs no production change, so the test author sabotage-verified its own tests and the supervisor added one more sabotage.
- **Task 4: the reviewer added test 8.** Expansion now follows the finding id across dismiss and reorder. A sabotage that keyed expansion by array index had left all 74 tests green. SlideViewer never remounts the drawer, so index keying would show the next finding's technical text unasked.
- **Whole-branch review fixes:**
  - M1: the docstrings wrongly said the integration suites pin the no-findings sentence. They compare against `_advisory_text([])` itself; the real pin is `test_no_findings_line_is_byte_identical`.
  - M2: "the plain copy never reaches a model" was false, because Apply/Discuss carry `plainIssue`. Reworded.
  - M3: the advisory's shape (bullets, line joins, `thing`/`things`, "(noted N times)") had no cross-language pin. `frontend/tests/fixtures/deckAdvisoryGoldens.json` (11 cases) is now recomputed by a Python test and parsed by vitest. Sabotage proof: changing the plain-line bullets to `* ` and regenerating the golden turns 8 TS tests red, where before every hand-copied test stayed green.

## Test evidence

**Suites at HEAD.**

| Suite | Result |
|---|---|
| Python unit | 9419 passed, 135 skipped, 0 failed. Baseline 9166/135/0. The failure cause-set is empty before and after. |
| Integration subset (graph_orchestration, architect_reply_is_persisted) | 29 passed |
| CI "Integration: General" files plus graph-mode turns, run locally by the branch reviewer | 243 passed, 1 skipped |
| vitest | 1306/1306 |
| `tsc -b` | 0 |
| `vite build` | OK |
| Lint | No new errors in touched files. AppLayout's 4 pre-existing errors are untouched. CI runs no lint. |

**E2E.** All mocked, run locally with an installed-Chrome channel, because the bundled headless shell for Playwright 1.57 is missing from the shared cache. CI installs its own browsers.

| Specs | Result |
|---|---|
| findings-drawer | 8 |
| chat-ui | 28 |
| slide-viewer, spec-view, app-tour | 51 |
| deck-review-flag, incremental-slide-delivery | passed |
| Branch reviewer's sweep: the above plus viewer-readonly | 96 passed |

No new spec files were added, so the CI matrix is unchanged.

**Frozen-path guard.** Both the `git diff` and the `git status --untracked` forms printed nothing, comparing against `679d2f21` for: `finding.py`, `skill_io.py`, `src/core/skills`, the v1 manifest, `agent_schema_registry.py`, `prompt_assembler.py`, `agent_model_payload.py`, `model_payload_keys.py`, `graphLifecycleContract.json`, `evals/` and the tour fixture. The self-check confirmed the guard can fail: adding the plan directory to the guard made it list the plan file.

**Sabotage runs.** Each production line was broken, the guarding test confirmed red, then the line was restored and confirmed green. A selection:

| Area | Sabotage | Result |
|---|---|---|
| Copy module | issue tense ignores status | 36 red |
| Copy module | stored objective used instead of the registry's | 23 red |
| Copy module | `message` appended into the plain text | 127 red |
| Copy module | slide criteria pass through to the advisory | 1 red |
| Copy module | copy injected into a `CRITERIA` description | prompt-leak test red |
| Copy module | ~20 further variants | all red |
| Agents keep detail | fixer payload `message` replaced | red |
| Agents keep detail | `plain_message` key added | red |
| Agents keep detail | fix-reviewer payload drops a key | red |
| Agents keep detail | architect `previous_deck_review` message replaced | red |
| Agents keep detail | stored record altered | red |
| Read path | `plainIssue = plainMessage` | 8 red |
| Read path | keys only when open | 2 red |
| Read path | extra non-allowlisted key | 9 red |
| Read path | spec-view literal missing a key | conformance red and tsc TS2741 |
| Deck advisory | blank messages kept | red |
| Deck advisory | singular header dropped | red |
| Deck advisory | details reversed | red |
| Deck advisory | dedup by criterion | red |
| Deck advisory | closing line on the empty list | red |
| Deck advisory | SSE content differs from polled content | red |
| Deck advisory | `request_id` None | poll leg red |
| Deck advisory | store keeps plain copy | red |
| Drawer | details truncated | 3 red |
| Drawer | index-keyed expansion | red after test 8 was added |
| Drawer | single-line separator | 10 red |
| Drawer | untrimmed `plainIssue` | 4 red |
| Drawer | TS separator changed | TS and the Python pin red |
| Drawer | toggle on open findings only | red |
| Apply/Discuss (e2e) | Apply uses the Discuss writer | red |
| Apply/Discuss (e2e) | drawer shows `message` | red |
| Chat collapse | role-agnostic parse | 3 red |
| Chat collapse | header suffix dropped | red |
| Chat collapse | legacy lead accepted | red |
| Chat collapse | details duplicated into the lead | 6 red |
| Chat collapse | TS-only edit to `CLOSING` | Python pin, 13 vitest and the e2e reload test red |
| Chat collapse | summary label changed | 3 red |

**Cross-language probe.** The real Python `_advisory_text` was run over 234 combinations, and the TS parser was applied to each output. 232 split correctly, and the 2 expected nulls (empty list, all-blank messages) stayed null.

## CI history

- **Round 1** (head `5f8610cb`, run `39407610221`): green on the first push.
  - 65 checks passed. 2 were skipped by design: `deploy`, and `Agentic Behaviour (layer 3)`.
  - Passing checks include Unit Tests, Frontend Unit Tests, Frontend Build, Wheel Build, every Integration job (General, Graph Orchestration, Streaming, Slides, …) and all 50 E2E matrix specs (findings-drawer, chat-ui, spec-view, slide-viewer, app-tour and the rest).
  - No reruns were needed, and nothing was flaky.
- The only later push changes this notes file.

## Follow-ups

- **Converge with #321 (PR #332).** Once it merges, move both chat shapes (the Apply/Discuss request details and the deck-advisory details) onto its `metadata.details` payload and its "Details" disclosure. Then drop the content-shape parse in `findingText.ts`/`Message.tsx`.
  - The copy style already matches #332's `user_notices.py`: second person in action lines, 1-based slide numbers, contractions.
  - Decide then whether finding copy should share a module with the notice catalogue.
- **Eval for the new Apply/Discuss phrasing.** Add an architect eval case in #313's harness covering the new phrasing.
- **Optional deck-advisory copy polish.** Use a plural deck-grain line when the count is above 1, and a singular closing line for "1 thing".

## Known gaps and follow-ups

- **Less specific drawer text.** For example "Some text…" rather than "the 'NOTE' label". This is accepted under Decision 1. The `plainMessage`/`plainIssue` keys are the seam if a richer source is added later.
- **Chat rows stored before this change stay as they were.** That means old `- arc_gap: <message>` advisories and old `Please apply this review suggestion…` bubbles. The drawer is unaffected, because its text is derived at read time.
- **Deck advisory edge cases:**
  - A deck-reviewer message containing newlines breaks the `- ` bullet shape inside the collapsed details. This is cosmetic, and the lead and parser are unaffected.
  - "One of the slides may need a closer look (noted 3 times)." can read as one slide flagged three times. It is a defensive fallback, because the deck reviewer is told to report deck-level criteria only.
  - "None of these…" reads oddly after "1 thing".
- **The app-tour e2e mock has no plain keys**, so that spec's drawer shows the fallback copy. It asserts visibility only.
- **No eval covers the new Apply/Discuss phrasing.** The architect now reads `Please fix this on slide N: <plain issue>` plus the details. The old phrasing had no eval either. This is a candidate for #313's harness.
- **Follow-up:** move both chat shapes onto #321's `metadata.details` once #321 merges.
- **Pre-existing and out of scope:** read-only viewers still see the drawer's Apply/Discuss buttons. That gating is unchanged from base.

## Merge hotspots with sibling branches

The branch reviewer simulated the merges with `git merge-tree`:

- **#313, #317, #318, #323:** clean.
- **#319:** one doc-table-row conflict.
- **#321:** three conflicts, all resolved by keeping both sides:
  - `Message.tsx`: 2 hunks;
  - `test_graph_nodes.py`: 1 import line;
  - `frontend-overview.md`: rows.

The merged trees were green.

## Not verified locally

- Postgres-marked suites, which self-skip locally; CI runs them.
- Real-backend e2e. All the specs this branch touches use mocks.
