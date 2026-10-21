# Issue #316: Plain-Language Review Findings (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILLS: `superpowers:subagent-driven-development` and `executing-plans-tellr` (repo CLAUDE.md). Run the plan-vs-code corrections pre-pass before Task 1. Steps use checkbox (`- [ ]`) syntax for tracking. Tests and implementation are written by different agents, in that order (skill §9).

**Date:** 2026-10-19 (revised the same day after plan review; see the Revision log at the end)
**Branch:** `feat/316-plain-language-findings` (worktree `.claude/worktrees/issue-316`), based on `origin/main` `679d2f21`. Do not commit. The supervisor commits.
**Issue:** robertwhiffin/ai-slide-generator#316, "Review feedback shown to users is too technical"

**Baselines measured 2026-10-19 on `679d2f21`. These are cause-sets, not counts (skill §3).**

- **Python.** `uv run pytest tests/unit -n 4 -q` gives 9166 passed, 135 skipped, 0 failed.
- **Vitest.** The full suite gives 1165 passed. `FeedbackDrawer.test.tsx` and `FindingsE2.test.tsx` give 12 passed.
- **Lint.**
  - `npx eslint .` gives **63 errors and 9 warnings**, all pre-existing. CI runs no lint. The record is `/Users/robert.whiffin/tellr-loop/issues/issue-316/baseline-fe-lint.txt`.
  - Of the files this plan touches, only `src/components/Layout/AppLayout.tsx` has findings: **4 errors**, at `:64` and `:100` (`react-refresh/only-export-components`), `:742` (`@typescript-eslint/no-explicit-any`) and `:1073` (`@typescript-eslint/no-unused-vars`, `_findingId`). It also has 2 warnings, at `:390` and `:788` (`react-hooks/exhaustive-deps`).
  - `Message.tsx`, `SlideViewer/*`, `types/finding.ts`, `tests/e2e/findings-drawer.spec.ts`, `tests/e2e/spec-view.spec.ts` and `tests/fixtures/findings.ts` are lint-clean.
  - **Rule: no NEW lint errors in files this branch touches.** Compare by rule id and message, not by line, because edits shift lines. **Never fix pre-existing lint in `AppLayout.tsx`.** #323 also edits that file.

**Goal:** Every review finding a deck author sees leads with plain language: in the feedback drawer, in the deck-review chat message, and in the chat bubble that Apply or Discuss sends. The reviewer's technical message is unchanged. It is still what the fixer, the fix reviewer and the architect receive. Wherever a user sees it, it sits behind a collapsed details disclosure.

**Architecture.**
- **Derivation.** The plain text is **derived at read time** from fields every finding already carries: `criterion`, `objective` (from the `CRITERIA` registry) and `status`. It never comes from `message`.
- **Copy module.** A new pure domain module, `src/domain/finding_copy.py`, holds one plain issue sentence per criterion (present and past tense), four status sentences, and the fixed strings of the deck advisory.
- **Projection.** The single read-path projection `_finding_to_camel` (`src/api/services/session_manager.py:191`) adds two projection-only keys:
  - `plainMessage`: issue plus status, shown in the drawer
  - `plainIssue`: the issue sentence alone, used as the lead of an Apply or Discuss request

  Every `get_slide_deck` path, both transports, the tour and shared decks go through that projection.
- **Chat.** The deck advisory (`_advisory_text`, `src/services/graph/nodes.py:1299`) and the Apply/Discuss requests share one wire shape: a plain lead, then the separator `"\n\nReviewer's details:\n"`, then the technical text verbatim. `Message.tsx` collapses that section with a strict content-shape match, for exactly those two shapes. The content that is sent and stored is unchanged by the render.
- **What does not change.** Nothing is added to `Finding`, to any reviewer output schema, to any prompt, or to any persisted record. So no schema digest moves and nothing needs promoting. Drawer findings persisted before this change render the same way as new ones (D6 scopes this claim).

**Tech stack:** FastAPI + Pydantic v2 (pytest, `uv run`). React 19 + Vite (vitest + Testing Library). Playwright e2e with a mocked API (`frontend/tests/e2e`).

---

## Acceptance criteria (verbatim from #316): how each is met and what proves it

| # | Acceptance (verbatim) | How it is met | Proving tests |
|---|---|---|---|
| AC1a | "Findings shown in the UI (drawer …) carry a plain-language message" | `_finding_to_camel` adds `plainMessage` and `plainIssue` (Task 3). `FeedbackDrawer` renders `plainMessage` and does not render `message` by default (Task 4). | `tests/unit/test_deck_read_path_keys.py::TestPlainMessage::*` (all three read paths, contributor read, fixed status, legacy record). `FeedbackDrawer.test.tsx` plain-message tests. `findings-drawer.spec.ts` "the drawer leads with the plain message …" |
| AC1b | "… (… and chat) carry a plain-language message" | The deck advisory leads with plain lines and a closing line. The reviewer's messages follow in a "Reviewer's details" section (Task 6), which `Message.tsx` collapses (Task 7). Apply and Discuss lead with `plainIssue`, with the technical text in the same collapsed section (Tasks 4, 5, 7). | `test_graph_nodes.py::TestDeckAdvisoryIsPlain::*`, including a real poll leg. `findingText.test.ts`. `Message.findingRequest.test.tsx`. `findings-drawer.spec.ts` Apply, Discuss and reload tests |
| AC1c | "the technical detail remains available to the fixer" | `Finding` is untouched. The fixer, fix-reviewer and architect payloads are pinned to carry the reviewer's `message` verbatim with exactly `Finding`'s keys (Task 2). The sent Apply/Discuss content carries the message verbatim (Tasks 4, 5). | `test_graph_nodes.py::TestReviewersKeepTheTechnicalMessage::*`. `findingText.test.ts` strict-equality tests. `findings-drawer.spec.ts` request-body assertions |
| AC1d | "and, optionally, behind a 'details' disclosure" | **Drawer:** a "Show details" toggle per finding, collapsed by default (Task 4). **Chat:** a native `<details>` "Reviewer's details" on both shapes, closed by default (Task 7). | `FeedbackDrawer.test.tsx` disclosure tests. `Message.findingRequest.test.tsx`. `findings-drawer.spec.ts` |
| AC2 | "Decide where the plain-language text comes from (reviewer output field vs. a rewrite step) without changing the frozen output schemas casually — they are pinned by digest." | Decision D1: option (c), deterministic and derived outside every pinned artefact. | `test_finding_copy.py::test_copy_is_not_rendered_into_any_prompt`. `test_finding_conformance.py::…::test_projection_only_fields_are_declared_in_ts_and_absent_from_finding`. `test_architect_edit_prompt.py::test_schema_contract_digests_unchanged`. Task 9's frozen-path guard, covering tracked and untracked files |

---

## Inventory

### A. Reviewers whose findings reach a user, and the fields they carry today

All findings are `src/domain/finding.py` `Finding` (fields at `finding.py:197-204`):

| Field | Type | Who sets it |
|---|---|---|
| `id` | `str` | node, `make_finding_id(criterion, subject_hash, ordinal)` in `_stamp_findings` (`nodes.py:1068-1108`) |
| `slide_index` | `int` (`-1` = deck) | node (`_stamp_findings`) |
| `category` | `content \| design \| narrative` | model, validated against `CRITERIA` (`finding.py:206-221`) |
| `criterion` | `str`, must be a `CRITERIA` key | model, validated |
| `message` | `str` | model. Free prose, written for the fixer: "Write a concrete, specific message" (`build_reviewer.py:55`) and "state what is wrong and leave the remedy to the fixer" (`build_reviewer.py:43-44`). The deck reviewer is told to "Write a concrete message citing which slides or arc beats are involved" (`deck_reviewer.py:32`). |
| `objective` | `bool` | model, then **re-derived from `CRITERIA`** by `_stamp_findings` |
| `status` | `open \| fixed` (default `open`) | node. `fix_reviewer_node` sets `fixed` (`nodes.py:2853-2857`). |
| `seen` | `bool` (default `False`) | initial value only |

There is **no** severity, summary, subject or plain field. The registry entry (`FindingCriterion`, `finding.py:58-65`) adds `name`, `category`, `level`, `objective` and `description`. The description is model-facing prompt text, rendered into the build reviewer's CRITERIA stage by `_criteria_stage` (`src/core/skills/build_reviewer.py:13-18`).

| Producer | Code | Output schema (`OUTPUT_SCHEMAS`, `src/domain/skill_io.py:251-259`) | Where its findings go | User-visible? |
|---|---|---|---|---|
| `build_reviewer` | `build_reviewer_node` `nodes.py:2342` | `SlideReviewOutput` (`finding.py:251`) | The row's `verification_record` via `_write_reviewed_row` (`nodes.py:1111`). If any finding is objective, they go to `fix_map[pos]` with `"finding": objective[0].model_dump()` (`nodes.py:2479`) and are persisted later by the fix reviewer or `_land_original` (`nodes.py:2511`). | **Yes**. These are the only slide findings ever persisted. |
| `fix_reviewer` | `fix_reviewer_node` `nodes.py:2754` | `SlideReviewOutput` | Its own `re_findings` (`nodes.py:2844`) **decide** fixed-or-original but are **never persisted**. The row is written with the build reviewer's `prior_findings`, with `status="fixed"` on the fixed criterion when the fix wins (`nodes.py:2853-2857`) and unchanged when it loses (`nodes.py:2875`). | Indirectly. It sets `status`. Its own messages never reach a user. |
| `deck_reviewer` | `deck_reviewer_node` `nodes.py:3296` | `DeckReviewOutput` (`finding.py:269`) | `deck_reviews` row via `save_deck_review` (`nodes.py:3498`). Chat advisory `_advisory_text(findings)` (`nodes.py:3499`), persisted as an `info` message (`_surface_notice`, `nodes.py:3522`) and emitted as SSE `ASSISTANT` (`nodes.py:3523-3527`). It never enters the `findings` channel or the drawer (§9 docstring). | **Yes**, in chat only |
| Deck-level re-review (build reviewer reused) | `rereview_committed_slides` `nodes.py:528` | `SlideReviewOutput` | Nothing persisted. The `surfaced` list (`nodes.py:724-733`) goes only into the architect's ASSISTANT event **metadata** (`nodes.py:1899`). The frontend never renders `metadata.surfaced`: `ChatPanel.tsx` reads only `tool_name`, `tool_input` and `sync_error`. | No |
| Tour demo | `_seed_verification` `src/api/routes/tour.py:192-226` from `src/api/fixtures/tour_demo_deck.json` `stages.build.findings` | n/a (hand-authored `brief_not_delivered`, `objective: false`) | Row `verification_record`, read through `get_slide_deck` | **Yes**, through the same projection |

**`change_summary`** (`FixerOutput`, `skill_io.py:221-229`) is carried only in the turn-scoped `fixed` channel (`nodes.py:2741`) and the fix-reviewer payload (`nodes.py:2821`). It is **not persisted** and cannot be read when the drawer renders. It is also model prose. It is not used (Decision D1).

### B. Every surface where finding text can reach a user

| # | Surface | Code | Today | Disposition |
|---|---|---|---|---|
| S1 | Feedback drawer finding row | `frontend/src/components/SlideViewer/FeedbackDrawer.tsx:128` renders `{f.message}` | Technical text | **Changed** (Task 4). Renders `plainMessage`; `message` sits behind "Show details", collapsed. |
| S2 | Read-path projection feeding S1, S4 and S5 | `_finding_to_camel` `session_manager.py:191-203`, `_deck_findings` `:206-235`, used by row-read `:1919`, `deck_json` blob `:2008` and legacy `:2035` | `model_dump()` camel-cased | **Changed** (Task 3). Adds `plainMessage` and `plainIssue`. One function covers all three paths, shared/contributor decks (`_get_deck_owner_session`) and the tour. |
| S3 | `SlideFinding` type | `frontend/src/types/finding.ts:4-13` | 8 fields | **Changed** (Task 3). Adds `plainMessage: string`, `plainIssue: string` and `PLAIN_MESSAGE_FALLBACK`. |
| S4 | Apply posts into chat as the user's message | `AppLayout.tsx:1062-1069`: `Please apply this review suggestion for slide N: ${finding.message}` | Technical text in the user's bubble | **Changed** (Tasks 4, 5, 7). Sent and stored content becomes `Please fix this on slide N: <plainIssue>` + separator + `<message verbatim>`. The bubble shows the lead and collapses the details (Message.tsx, S21). |
| S5 | Discuss posts into chat | `AppLayout.tsx:1078-1086` | Same | **Changed**, same shape, with the lead `I'd like to discuss this on slide N:` |
| S6 | Deck-review advisory in chat | `_advisory_text` `nodes.py:1299-1317` (`- {criterion}: {message}`) to `_surface_notice` (`info` row, read by `GET /chat/poll`) and `_emit(ASSISTANT)` (SSE) | Slug plus technical text, inline | **Changed** (Tasks 6, 7). Content becomes plain lines, a closing line, then separator plus one bullet per reviewer message, verbatim. The bubble collapses the details. The no-findings line stays byte-identical with no details section. `info` rows are never replayed to the architect (D5). |
| S7 | Tour demo drawer | `tour.py:192-226`, fixture `stages.build.findings["2"]` | The fixture's hand-written message (already fairly plain) | **Covered by S2.** No fixture change. The real tour path is pinned in Task 3. |
| S8 | Tour demo review advisory | fixture `stages.review.advisory` is the no-findings sentence, pinned by `tests/unit/test_tour_fixture_script.py:83-86` | Plain | Unchanged (D5 keeps that sentence byte-identical) |
| S9 | Tour step copy | `frontend/src/components/Tour/tourSteps.ts:209` (drawer step) | Describes Apply/Dismiss/Discuss | Unchanged. It does not quote finding text. |
| S10 | Per-slide `verification` blob (raw `tellr_review.findings` snake_case dumps) shipped to the client | row-read `session_manager.py` (`slide_dict["verification"]`) | Technical, **not rendered**. No `tellr_review` reader exists in `frontend/src` outside tests. | Out of scope. It is not a surface. |
| S11 | Verification badge | `frontend/src/components/SlidePanel/VerificationBadge.tsx:197` `explanation` | LLM-as-judge (Genie data accuracy), a different system from reviewer findings | Out of scope |
| S12 | Per-slide stage lines `Slide N reviewed: <verdict>.` / `Slide N fix reviewed: <verdict>.` | `nodes.py:2462`, `:2938` (SSE only) | No finding text | Out of scope (#319 consumes them) |
| S13 | Re-review notice and its `metadata.surfaced` | `nodes.py:1849-1909` | The notice has no finding text, and the metadata is not rendered | Out of scope |
| S14 | Failure and placeholder notices | `_placehold_failed_position` `nodes.py:1291-1295`, `_transient_failure_notice` `nodes.py:3000-3006`, deck-reviewer failure advisories `nodes.py:3442-3447`, `:3455-3459`, `:3503-3506` | Not findings | Out of scope (#321) |
| S15 | Save-point preview | `get_version` `session_manager.py:2653` returns `SlideDeck.to_dict()` snapshots (`chat_service.py:3040-3045`), which have no `findings` key. `AppLayout.tsx:955` falls back to `[]`. Preview chat history renders through the same `Message` component (`ChatPanel.tsx:400`). | No findings in the drawer. Chat as stored. | Drawer unchanged. Preview chat gets the S21 collapse for rows in the new shapes. |
| S16 | Exports (PDF/PPTX/Google Slides) | `src/api/routes/export.py` (its "findings" are HTML-safety scan results, `:147`) | No review findings | Out of scope |
| S17 | MCP tools | `get_deck_status` (`mcp_server.py:686`) returns `SlideDeck.from_dict(...).to_dict()`, which has no findings, **plus the turn transcript** from `get_messages_for_request` (`mcp_server.py:818-826`), which includes the deck advisory row | Advisory with slug plus message | **Changed, accepted.** After Task 6 the transcript carries the plain lines, the closing line and the "Reviewer's details" section with the deck reviewer's messages verbatim. MCP clients read plain text, so the actionable slide references are kept. |
| S18 | Admin Agent Test Run panel | `frontend/src/components/Admin/AgentDefinitionWorkbench/TestRunPanel.tsx:283` | Admin-only raw model output | Out of scope. It is technical by design. |
| S19 | The architect's own reply to a turn | model prose | n/a | Out of scope. The architect gets `previous_deck_review` with technical messages (`nodes.py:1532`) and may paraphrase them. Prompt changes are excluded (D1). |
| S20 | SpecView "deck review in progress" badge | `frontend/src/components/SpecView/SpecView.tsx:97-99` | No finding text | Out of scope |
| S21 | Chat message rendering | `frontend/src/components/ChatPanel/Message.tsx:126-143` (regular user/assistant branch: `whitespace-pre-wrap` content). The optimistic bubble (`ChatPanel.tsx:170,187-194`), reload (`:103-111`) and preview (`:400`) all render through it. | Content verbatim | **Changed** (Task 7). For role `user`, it collapses the details section of an Apply- or Discuss-shaped content. For role `assistant`, it collapses the details section of a deck-advisory-shaped content. The match is strict and **nothing else is parsed**. The tool and HTML branches (`:61-124`) are untouched. |
| S22 | Chat rows stored before this change | Old advisories (`- arc_gap: <message>`) and old Apply/Discuss bubbles (`Please apply this review suggestion for slide N: <technical>`) | Technical | **Unchanged, accepted** (D6). They render as stored, on reload and in preview. Legacy shapes are deliberately not parsed (R2: "never parse anything else"). |

**Transports.** Slide findings reach the client **only** through `get_slide_deck`. On SSE `complete`, `ChatPanel.tsx:290-304` refetches through `api.getSlides`, and graph-mode `COMPLETE` carries `slides=self.get_slides(...)` (`chat_service.py:2126-2130`). The polling transport synthesises the same events. The advisory is one string, written both to the polled `info` row and to the SSE event, and Task 6 pins the poll leg end to end.

**Multi-worker.** The derivation and the render parse are pure functions with no in-process state.

---

## Decisions

**D1. The plain text comes from option (c): deterministic copy derived from `criterion` (with `objective` from the registry) and `status`, computed at read time outside every pinned artefact.**

- **(a), a new reviewer output field: not chosen.** `Finding` is nested in `SlideReviewOutput` and `DeckReviewOutput`. The schema-contract digest material includes `schema.model_json_schema(mode="validation")` (`src/services/agent_schema_registry.py:251-258`), so a new field changes the JSON schema even if the model never fills it. That moves `_V1_DIGESTS` and `_V2_DIGESTS` (`:49-70`) for `build_reviewer`, `fix_reviewer` and `deck_reviewer`. The plan reviewer confirmed this by computing the schema.
  - There is a sanctioned route for exactly this kind of additive change. `_HISTORICAL_DIGESTS` (`agent_schema_registry.py:316-322`) keeps a superseded identity resolvable when "new fields [are] optional, nothing removed", and it has been used twice for `architect`. So (a) would be a deliberate, supported migration, not an impossibility.
  - It still costs more than this issue justifies:
    - **Prompt migration.** The model must be told to fill the field. That is a prompt change, and `build_reviewer` is the source of a `LegacyV1PromptTransition` (`src/services/prompt_assembler.py:243-245`). `evals/harness/promote.py:167-175` refuses that promotion without a deliberate migration.
    - **Leaks.** The field would travel everywhere `Finding.model_dump()` travels: fixer payload (`nodes.py:2479`/`:2663`), fix-reviewer payload (`:2820`), architect `previous_deck_review` (`:1490-1499`), persisted records, the msgpack checkpoint serde (`tests/integration/test_graph_orchestration.py:805-828`) and the frontend lifecycle contract.
    - **Old data.** Records persisted before the change would lack it.
    - **No guarantee.** A model-written "plain" field is still model prose, and nothing ensures it is free of hex codes.
- **(b), a rewrite step: rejected.**
  - It adds a model call per surfaced slide: latency inside an already minutes-long turn, cost, and a new failure mode that must not placehold a good slide.
  - It needs a new model-driven role (Agent Definition, schema, manifest, release) or an ungoverned side call.
  - Its output must be persisted, which changes the record shape and leaves old records without it.
  - The output is still unguaranteed prose.
- **(c) is chosen.** It has zero model cost, latency or failure modes, and needs no digest, prompt, manifest, eval or contract-fixture change. Old drawer findings render for free because nothing is stored. Every `CRITERIA` entry × status × objectivity is tested for banned content.
- **The trade-off is specificity.** The issue's example becomes "Some text was hard to read against its background. This was fixed automatically." rather than naming the "NOTE" label or "a lighter colour". The specifics stay one click away, in the drawer and in chat. The drawer is already scoped to one slide, so the location is implied. Two findings of the same criterion on one slide read the same except for their details.
- **Subject extraction (pulling a quoted label out of `message`) is rejected as a trap.** It is a regex over model prose. It can pull out class names, CSS values or injected slide text, cannot be fully tested, and quietly brings technical content back into the line this issue cleans up.
- **`change_summary` is not used.** It is not persisted (Inventory A), it is model prose, and it describes only the one criterion that was fixed.
- **Future seam.** `plainMessage` and `plainIssue` are the projection seam. A richer source can feed them later without a frontend change.

**D2. Where the copy lives and how it travels.**
- The new module `src/domain/finding_copy.py` is pure and imports only `src.domain.finding`. It is a **separate mapping**, not a new `FindingCriterion` field. `_criteria_stage` renders only `name`, `category`, `level`, `objective` and `description` (`build_reviewer.py:14-18`). A separate module therefore rules out prompt leakage by construction. `test_copy_is_not_rendered_into_any_prompt` (Task 1) pins it.
- The projection adds two keys in `_finding_to_camel`:
  - `plainMessage = plain_finding_message(f)`: issue plus status, for the drawer
  - `plainIssue = plain_finding_issue(f)`: the issue sentence alone, in status tense, for request leads
- Both are **projection-only**: not `Finding` fields, never persisted, never sent to a model.
- The conformance suite gets an explicit allowlist, `PROJECTION_ONLY_FIELDS = {"plainMessage", "plainIssue"}`, plus a guard that the snake-case names are **not** `Finding` fields (Task 3).

**D3. Drawer details disclosure: yes.**
- One toggle per finding, labelled "Show details" or "Hide details", collapsed by default.
- Its state is local and not persisted. The drawer already persists only open, height and tab.
- Expanded, it shows `message` verbatim (`whitespace-pre-wrap break-words`). Collapsed, the technical text is **not in the DOM**.
- It is rendered only when `message.trim()` is non-empty, for fixed and open findings alike.
- Opening it marks nothing seen and calls no drawer callback.

**D4. What Apply and Discuss post into chat.**
- **Content sent and stored:**
  - Apply: `` `${APPLY_REQUEST_LEAD} ${slideIndex+1}: ${plainIssue}` + REVIEWER_DETAILS_SEPARATOR + message ``
  - Discuss: the same, with `DISCUSS_REQUEST_LEAD`
  - Constants (`frontend/src/utils/findingText.ts`): `APPLY_REQUEST_LEAD = 'Please fix this on slide'`, `DISCUSS_REQUEST_LEAD = "I'd like to discuss this on slide"` and `REVIEWER_DETAILS_SEPARATOR = "\n\nReviewer's details:\n"`
  - The details part is omitted when `message` is blank. `message` is inserted verbatim. ChatPanel then trims the whole string before sending (`ChatPanel.tsx:170`), which is existing behaviour.
- **The lead uses `plainIssue`, not `plainMessage` (review #2).** Only open findings show Apply and Discuss. A lead that included the status sentence would make the user say "Please fix this … it was left unchanged", which contradicts itself and is noise to the architect.
- **The detail must be sent.** The request becomes the user's turn message, and the architect acts on it. The architect payload has no slide findings and no slide HTML (`nodes.py:1527-1543`, pinned by `tests/fixtures/model_payload_keys.py` and `src/services/agent_model_payload.py:56-69`). Without the detail it cannot know which label to recolour or what the brief missed.
- **The bubble hides it** behind a collapsed native `<details>` (D14). The sent and stored content stays complete, so the architect's input is unchanged by the render.
- **A hidden agent-only channel is rejected.** It would need a `ChatRequest` field (`src/api/schemas/requests.py:53`), a pinned architect payload key and a prompt change.
- `+1` stays because users speak 1-indexed. The text comes from pure helpers so it can be unit-tested.

**D5. Deck-review advisory: a hybrid content shape.**
- **The shape:** plain lines, then one closing line, then the same `REVIEWER_DETAILS_SEPARATOR` section carrying each deck-reviewer message verbatim, one `- ` bullet per finding in order.
- **Plain lines:**
  - The header line is `DECK_ADVISORY_HEADER_PREFIX + "{N} thing(s)" + DECK_ADVISORY_HEADER_SUFFIX`.
  - Each plain line is `deck_advisory_issue(criterion)`. For a `level="deck"` criterion that is the plain issue sentence. **Any other criterion gets the deck-grain line** `DECK_GRAIN_ISSUE` = "One of the slides may need a closer look." (review #5): nothing filters deck-reviewer findings by level, and a slide sentence ("This slide …") has no referent in a deck-wide message.
  - Lines are deduplicated by **line text** in first-seen order, with ` (noted N times)` when a line repeats (review #6). The header counts findings.
- **Closing line:** `DECK_ADVISORY_CLOSING` = "None of these were changed automatically. Reply here if you'd like any of them addressed." (review #7, R7).
- **Details section:** findings whose `message` is blank are skipped. If every message is blank, the separator section is omitted.
- **Why the details stay in the content.** The deck reviewer's messages are narrative and carry the only actionable references: which slides, which arc beats (`deck_reviewer.py:32`). Bare plain lines would drop them (review #3). `Message.tsx` collapses the section (D14), so the plain lines lead.
- **This is not #321's mechanism.** `_surface_notice`'s signature is unchanged and no `metadata.details` is written; that belongs to #321, an unmerged concurrent branch this PR cannot depend on. A follow-up is listed to move both of this PR's shapes onto #321's `metadata.details` after it merges.
- **The details never become agent context through replay.** The advisory is an `info` row, and both replay paths exclude `info`:
  - `_conversation` (`nodes.py:965-989`) admits only `_HUMAN_TYPES`/`_AI_TYPES` (`:199-200`)
  - `chat_service._hydrate_chat_history` (`chat_service.py:2441-2462`) skips `info`

  The architect still receives the deck findings with full messages next turn through `previous_deck_review` (`nodes.py:1474-1501`). Task 2 pins this.
- **The no-findings sentence stays byte-identical, with no details section:** "Deck review complete: no narrative issues found across the deck." The tour fixture (`test_tour_fixture_script.py:83-86`) and the integration suites (`tests/integration/test_graph_orchestration.py:395`, `test_architect_reply_is_persisted.py:77`) pin it.
- **Correction of the earlier wording (review #18).** Chat already has a disclosure idiom: `Message.tsx:25-59` `renderCollapsibleContent`, for tool output, HTML and tool calls. #321 plans a native `<details>` on top of the same branch.

**D6. Backward compatibility, scoped.**
- **Drawer.** Nothing is stored, so every finding record written before this change renders with `plainMessage` and `plainIssue`. That covers row `verification_record`, deck `verification_map` and `deck_reviews.findings_json`. No migration is needed.
  - A legacy dict missing `status` or `seen` gets the `Finding` defaults (`open`/`False`) in `findings_from_record` (`finding.py:318-346`).
  - A dict with a retired criterion is already dropped there. That is existing behaviour.
  - On the frontend, `findingPlainText` and `findingPlainIssue` fall back to `PLAIN_MESSAGE_FALLBACK` if a field is missing or blank. That covers an untyped mock (the app-tour e2e) and a stale API cache.
- **Chat.** Rows stored before this change stay as they were, on reload and in save-point preview: old advisories `- arc_gap: <message>` and old bubbles `Please apply this review suggestion for slide N: <technical>`. This is accepted. Legacy shapes are not parsed (S22).

**D7. The fixer's payload is unchanged.** `Finding`, `_stamp_findings`, `fix_map`, `fixer_node` and `fix_reviewer_node` are untouched. Task 2 pins:
- `payload["finding"]` for the fixer and the fix reviewer: `message` verbatim, keys exactly `Finding.model_fields`, no plain copy anywhere in the payload
- the architect's `previous_deck_review`
- the persisted record

**D8. The copy.** This is exact, for every `CRITERIA` entry (`finding.py:70-180`, 11 entries). Present tense is used for `open`, past tense for `fixed`.

| criterion | level / objective | present (open) | past (fixed) |
|---|---|---|---|
| `overflow` | slide / T | Some content runs past the edge of the slide. | Some content ran past the edge of the slide. |
| `contrast_failure` | slide / T | Some text is hard to read against its background. | Some text was hard to read against its background. |
| `rogue_colour` | slide / T | A colour on this slide is outside the deck's colour scheme. | A colour on this slide was outside the deck's colour scheme. |
| `distorted_image` | slide / T | An image looks stretched or squashed. | An image looked stretched or squashed. |
| `source_contradiction` | slide / T | A figure on this slide does not match the source data. | A figure on this slide did not match the source data. |
| `brief_not_delivered` | slide / F | This slide may not cover everything planned for it. | This slide did not cover everything planned for it. |
| `off_template_treatment` | slide / T | This slide's background or colours differ from its template. | This slide's background or colours differed from its template. |
| `layout_binding_mismatch` | slide / T | This slide does not use the layout planned for it. | This slide did not use the layout planned for it. |
| `arc_gap` | deck / F | The story has a gap or an unexplained jump between slides. | The story had a gap or an unexplained jump between slides. |
| `cross_slide_repetition` | deck / F | The same point is made on more than one slide. | The same point was made on more than one slide. |
| `missing_conclusion` | deck / F | The deck has no clear conclusion or call to action. | The deck had no clear conclusion or call to action. |
| *(unknown / legacy)* | — | Something here may need a closer look. | Something here needed a closer look. |

Status sentences, selected by `(objective, fixed)`:

| status | objective | sentence |
|---|---|---|
| `fixed` | True | This was fixed automatically. |
| `fixed` | False | This has been addressed. *(No producer today. A subjective finding can only be fixed by a human.)* |
| `open` | True | This was not fixed automatically. *(This holds whether the fix lost, the fixer failed, or a second objective criterion was never attempted.)* |
| `open` | False | This is a judgement call, so it was left for you to decide. *(Second person, per R7.)* |

- `plainMessage = f"{issue} {status_sentence}"` and `plainIssue = issue`.
- Worked example: an open `brief_not_delivered` (the tour) gives `plainMessage` "This slide may not cover everything planned for it. This is a judgement call, so it was left for you to decide." and `plainIssue` "This slide may not cover everything planned for it."
- The longest `plainMessage` is 122 characters (measured).

Fixed deck-advisory strings, all in `finding_copy.py`:

| Name | Value |
|---|---|
| `DECK_GRAIN_ISSUE` | One of the slides may need a closer look. |
| `DECK_ADVISORY_HEADER_PREFIX` | `"Deck review found "` |
| `DECK_ADVISORY_HEADER_SUFFIX` | `" to look at in how the deck reads as a whole:"` |
| `DECK_ADVISORY_CLOSING` | None of these were changed automatically. Reply here if you'd like any of them addressed. |
| `REVIEWER_DETAILS_SEPARATOR` | `"\n\nReviewer's details:\n"` (shared with the TS copy, pinned equal) |

**D9. Objectivity comes from the registry when the criterion is known.** `objective` is `CRITERIA[criterion].objective`, falling back to the stored `finding.objective` only for an unknown criterion. That matches `_stamp_findings` (`nodes.py:1078-1100`), so an old record whose model-supplied `objective` was wrong still reads correctly.

**D10. Unknown or legacy criterion.** It gets the generic copy (the last D8 row) and the status sentence from the stored `objective`. It never raises. An unrecognised `status` reads as open. The frontend `PLAIN_MESSAGE_FALLBACK` equals the generic present sentence, pinned by a Python conformance test.

**D11. Copy style rules, enforced by tests. Revised per R7, which matches #321's D1.**
- **Shape.** Whole sentences start with a capital and end with a full stop. The header prefix and suffix are fragments, so only the banned-pattern rules apply to them.
- **Person.** The second person is allowed where an action line reads more naturally, as in the closing line and the judgement-call sentence. Per-criterion issue sentences describe the slide and stay third person.
- **Banned in every copy string:** digits, `%`, `#hex`, `px`, `rgb(`/`hsl(`, `:1` ratios, `WCAG`/`AA`, underscores, backticks, `**`, any criterion slug, and any graph node or role name (`architect`, `foreman`, `builder`, `fixer`, `reviewer`, `analyst`).
- **Exemptions.** The separator is exempt: it is a label for the technical section, contains "Reviewer's", and is tested for its exact value instead. The advisory's header count and `(noted N times)` are the only digits, and they are produced in `nodes.py`, not stored in the copy module.
- **Numbering.** User-facing slide numbers are 1-based (`slideIndex + 1`).

**D12. Frozen artefacts are not touched.**
- Do not edit:
  - `src/domain/finding.py`, `src/domain/skill_io.py`, `src/core/skills/*`
  - `src/services/agent_definition_manifest_v1.py`, `src/services/agent_schema_registry.py`, `src/services/prompt_assembler.py`, `src/services/agent_model_payload.py`
  - `tests/fixtures/model_payload_keys.py`, `frontend/tests/fixtures/graphLifecycleContract.json`
  - `evals/**`, `src/api/fixtures/tour_demo_deck.json`
- There is no promote, no contract re-record and no live eval. Eval spend is $0 of the $15 cap.
- Two naming points, for the record. The schema ledger is `_V1_DIGESTS`/`_V2_DIGESTS` with `_HISTORICAL_DIGESTS` (`agent_schema_registry.py`). `_V2_DIGEST`/`_HISTORICAL_V2_DIGESTS` (`prompt_assembler.py:398-411`) are the *protected-assembly* (prompt) identity. **No test named `test_retained_bundle_ledger` exists** (grep, 2026-10-19).

**D13. Tour.**
- There is no fixture or step-copy change.
- The real tour drawer shows the derived plain text for its `brief_not_delivered` finding, and the scripted message moves under "Show details".
- The app-tour e2e mocks findings without `plainMessage` or `plainIssue` (`frontend/tests/e2e/app-tour.spec.ts:158-176`), so it exercises the frontend fallback. That is acceptable because it asserts only visibility (`:446`).
- The real tour path is pinned in Task 3.

**D14. The chat collapse (R2, R4).**
- **Where.** A frontend-only, render-time parse in `Message.tsx`'s regular branch, using pure parsers in `frontend/src/utils/findingText.ts`. `findingText.ts` sits in `utils/` beside #321's planned `messageDetails.ts`, because `FeedbackDrawer`, `AppLayout` and `Message` all import it.
- **Exactly two shapes, strictly matched:**
  - `splitFindingRequest(content)`, role `user` only. The lead must match `^(APPLY_REQUEST_LEAD|DISCUSS_REQUEST_LEAD) [1-9]\d*: [^\n]+$`.
  - `splitDeckAdvisory(content)`, role `assistant` only. The lead must match the full plain block: the header line (`[1-9]\d* things?` between the two header constants), one or more `- …` lines, then `DECK_ADVISORY_CLOSING`.
  - For both, the lead is everything before the **first** `REVIEWER_DETAILS_SEPARATOR`, and the remainder must be non-blank.
- **Everything else is rendered verbatim and never parsed.** That includes legacy shapes, the no-findings sentence, the opposite role, and HTML or tool messages. The HTML and tool branches run first and are untouched.
- **Markup.** `<details data-testid="message-reviewer-details">` with `<summary>Reviewer's details</summary>`, closed by default. This is the native idiom #321 uses, with a distinct test id so the two never collide.
- **Contrast.** On the user bubble (`bg-primary`, hsl 221 83% 53%) the details text uses full `text-primary-foreground`, white at **5.2:1**. `/80` opacity would give 3.91:1, below AA for 12px text, which is exactly this issue's subject (computed). On the assistant bubble it uses `text-muted-foreground` at 4.61:1 (light theme, computed).
- **Content is unchanged.** Sent, stored, polled and MCP content are byte-identical with or without the parser. Only the render differs.
- **Tests.** The new vitest file is `Message.findingRequest.test.tsx`. It is **not** `Message.test.tsx`, which #321 creates.
- **Follow-up.** Migrate both shapes onto #321's `metadata.details` after #321 merges (Out of scope).

---

## Global constraints

- **Scope.** Work only in `/Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316`, using absolute paths. Never touch the primary checkout or other worktrees. No `git stash`, no deploys, no `pip install`, no commits. Run Python via `uv run`; the `.venv` is synced.
- **Python tests.** `uv run pytest <path> -q`. The whole suite is `uv run pytest tests/unit -n 4 -q`. The integration suites used here run locally on SQLite (measured: `tests/integration/test_graph_orchestration.py` + `test_architect_reply_is_persisted.py`, 29 passed).
- **Frontend.**
  - Vitest: `cd frontend && NODE_OPTIONS=--no-experimental-webstorage npx vitest run <path>`. The flag is needed locally on Node 26; CI uses Node 20.
  - Type-check: `npx tsc -b`. It covers `tests/**/*.ts` through `tsconfig.e2e.json` but **excludes** `src/**/*.test.ts(x)` (`tsconfig.app.json:33`).
  - E2E: `npx playwright test tests/e2e/<spec>.spec.ts --project=chromium --workers=1`, against a mocked API.
- **Lint.** Run `npx eslint <files this task touched>` as its **own command**. Never chain it with `&&` before vitest or Playwright. The rule is no new errors compared with the header baseline. Do not fix pre-existing lint.
- **Quoting.** Copy strings contain apostrophes (`deck's`, `slide's`, `you'd`, `I'd`, `Reviewer's`). TS string literals holding them must be double-quoted, which the Python constant-capture regex expects.
- **Sibling scopes.** Do not touch failure or placeholder notices or `_surface_notice` (#321), stage lines or the chat placeholder (#319), clear-chat (#323), SpecView export (#318) or architect intent (#313). Shared files:
  - `nodes.py`: `_advisory_text` plus one import
  - `AppLayout.tsx`: the two finding handlers plus one import
  - `Message.tsx`: the regular branch only (textual merge with #321)
  - `frontend-overview.md:324`: one row (textual merge with #321)

## Review focus (for per-task and whole-branch reviewers)

1. **Technical text leaking into the plain line.** The plain text must be a function of `(criterion, status)` and the registry only. Pinned by `test_plain_text_ignores_the_reviewer_message` and the banned-content sweep.
2. **Plain copy leaking into an agent.** No plain copy may appear in any model payload, prompt, manifest or persisted finding record. Pinned by Task 2 and `test_copy_is_not_rendered_into_any_prompt`.
3. **Conformance semantics.** `PROJECTION_ONLY_FIELDS` must not become a bypass. Its members must be emitted by `_finding_to_camel`, declared in TS, and absent from `Finding.model_fields`.
4. **Read paths.** All three read paths and the contributor read carry both keys. A fixed-status record and a hand-written pre-change record both render.
5. **Parser strictness.** `splitFindingRequest`/`splitDeckAdvisory` must accept exactly what the writers emit and reject everything else. Role binding is part of the match. Python and TS constants are pinned equal.
6. **Both transports.** The SSE content of the advisory equals the poll-projected content (real `request_id` leg). The details section carries each reviewer message verbatim. `deck_reviews` keeps the messages. `info` rows are not replayed.
7. **The no-findings advisory is byte-identical** (tour and integration pins).

---

## File structure

| File | Change | Task |
|---|---|---|
| `src/domain/finding_copy.py` | **Create.** Copy table, helpers, deck-advisory constants, separator | 1 |
| `tests/unit/test_finding_copy.py` | **Create** | 1 |
| `tests/unit/test_graph_nodes.py` | Modify: new class `TestReviewersKeepTheTechnicalMessage` (T2); new class `TestDeckAdvisoryIsPlain` and one edited assertion (T6) | 2, 6 |
| `src/api/services/session_manager.py` | Modify `_finding_to_camel` (+1 import) | 3 |
| `frontend/src/types/finding.ts` | Modify: `plainMessage: string`, `plainIssue: string`, `PLAIN_MESSAGE_FALLBACK` | 3 |
| `tests/unit/test_finding_conformance.py` | Modify. T3: allowlist, `_ts_string_constant` helper, projection, fallback and fixture-literal tests. T4: separator pin. T7: deck-constant pins. | 3, 4, 7 |
| `tests/unit/test_deck_read_path_keys.py` | Modify: `_SLIDE_FINDING_KEYS`, new `TestPlainMessage` | 3 |
| `tests/unit/test_tour_staged_demo.py` | Modify: one new test | 3 |
| `frontend/tests/fixtures/findings.ts` (f1–f3), `frontend/tests/e2e/findings-drawer.spec.ts` (`sentinel`, `postReorderFinding`), `frontend/tests/e2e/spec-view.spec.ts` (`s0-dismiss-me`, `s0-keep-me`) | Modify: add `plainMessage` and `plainIssue` to the **seven** typed `SlideFinding` literals | 3 |
| `frontend/src/utils/findingText.ts` | **Create** (T4: plain getters, request leads, separator, request writers). Modify (T7: deck constants, parsers). | 4, 7 |
| `frontend/src/utils/findingText.test.ts` | **Create** (T4), modify (T7) | 4, 7 |
| `frontend/src/components/SlideViewer/FeedbackDrawer.tsx` | Modify: plain text plus disclosure | 4 |
| `frontend/src/components/SlideViewer/FeedbackDrawer.test.tsx` | Modify: literals, `renderDrawer` callbacks parameter, new tests | 4 |
| `frontend/src/components/Layout/AppLayout.tsx` | Modify `handleApplyFinding` / `handleDiscussFinding` (+1 import) | 5 |
| `frontend/tests/e2e/findings-drawer.spec.ts` | Modify. T5: Apply and Discuss bodies, drawer test. T7: bubble and reload tests. | 3, 5, 7 |
| `src/services/graph/nodes.py` | Modify `_advisory_text` (+1 import) | 6 |
| `frontend/src/components/ChatPanel/Message.tsx` | Modify: regular branch collapse | 7 |
| `frontend/src/components/ChatPanel/Message.findingRequest.test.tsx` | **Create** | 7 |
| `docs/technical/slide-viewer.md`, `docs/technical/frontend-overview.md`, `docs/user-guide/01-generating-slides.md` | Modify | 8 |

---

### Task 1: Plain-language copy module

Models: test=opus impl=haiku

The tests are the contract: banned content, coverage, status selection and deck grain. The implementation is the transcription below.

**Files:**
- Create: `src/domain/finding_copy.py`
- Create: `tests/unit/test_finding_copy.py`

**Interfaces (all new):**

```python
# src/domain/finding_copy.py
class PlainIssue(NamedTuple):
    present: str            # the finding is open
    past: str               # the finding has been fixed

PLAIN_ISSUES: Mapping[str, PlainIssue]     # exactly the CRITERIA keys (MappingProxyType)
GENERIC_ISSUE: PlainIssue                  # unknown / legacy criterion
FIXED_AUTOMATICALLY: str
ADDRESSED: str
NOT_FIXED_AUTOMATICALLY: str
LEFT_FOR_JUDGEMENT: str
DECK_GRAIN_ISSUE: str
DECK_ADVISORY_HEADER_PREFIX: str
DECK_ADVISORY_HEADER_SUFFIX: str
DECK_ADVISORY_CLOSING: str
REVIEWER_DETAILS_SEPARATOR: str

def plain_issue(criterion: str, *, fixed: bool = False) -> str: ...
def plain_status(*, objective: bool, fixed: bool) -> str: ...
def plain_finding_issue(finding: Finding) -> str: ...
def plain_finding_message(finding: Finding) -> str: ...
def deck_advisory_issue(criterion: str) -> str: ...
```

Implementation (the implementer transcribes this; strings are from D8):

```python
"""Plain-language copy for review findings (#316).

A reviewer's ``Finding.message`` is written for the fixer: concrete, specific and
technical (hex codes, sizes, contrast ratios).  A deck author needs one calm
sentence pair: what is wrong, and what happened to it.  That text is DERIVED here,
at read time, from fields every finding already carries (``criterion``, the
registry's ``objective``, ``status``) and NEVER from ``message``.

Deliberate, and pinned by tests/unit/test_finding_copy.py:

* Nothing here is a ``Finding`` field.  ``Finding`` is nested in the reviewers'
  output schemas, whose digests (``_V1_DIGESTS`` / ``_V2_DIGESTS`` in
  src/services/agent_schema_registry.py) hash the JSON schema; a field, even an
  optional one no model fills, would move them.
* Nothing here reaches a model.  ``CRITERIA`` is rendered into the build
  reviewer's prompt; this is a separate mapping so editing copy never edits a
  prompt.
* Derived, never stored, so findings persisted before this module existed render
  exactly like new ones.

The deck-advisory strings and REVIEWER_DETAILS_SEPARATOR are mirrored in
frontend/src/utils/findingText.ts, which parses the advisory to collapse its
details; tests/unit/test_finding_conformance.py pins the two copies equal.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, NamedTuple

from src.domain.finding import CRITERIA, Finding


class PlainIssue(NamedTuple):
    present: str
    past: str


PLAIN_ISSUES: Mapping[str, PlainIssue] = MappingProxyType(
    {
        "overflow": PlainIssue(
            "Some content runs past the edge of the slide.",
            "Some content ran past the edge of the slide.",
        ),
        "contrast_failure": PlainIssue(
            "Some text is hard to read against its background.",
            "Some text was hard to read against its background.",
        ),
        "rogue_colour": PlainIssue(
            "A colour on this slide is outside the deck's colour scheme.",
            "A colour on this slide was outside the deck's colour scheme.",
        ),
        "distorted_image": PlainIssue(
            "An image looks stretched or squashed.",
            "An image looked stretched or squashed.",
        ),
        "source_contradiction": PlainIssue(
            "A figure on this slide does not match the source data.",
            "A figure on this slide did not match the source data.",
        ),
        "brief_not_delivered": PlainIssue(
            "This slide may not cover everything planned for it.",
            "This slide did not cover everything planned for it.",
        ),
        "off_template_treatment": PlainIssue(
            "This slide's background or colours differ from its template.",
            "This slide's background or colours differed from its template.",
        ),
        "layout_binding_mismatch": PlainIssue(
            "This slide does not use the layout planned for it.",
            "This slide did not use the layout planned for it.",
        ),
        "arc_gap": PlainIssue(
            "The story has a gap or an unexplained jump between slides.",
            "The story had a gap or an unexplained jump between slides.",
        ),
        "cross_slide_repetition": PlainIssue(
            "The same point is made on more than one slide.",
            "The same point was made on more than one slide.",
        ),
        "missing_conclusion": PlainIssue(
            "The deck has no clear conclusion or call to action.",
            "The deck had no clear conclusion or call to action.",
        ),
    }
)

GENERIC_ISSUE = PlainIssue(
    "Something here may need a closer look.",
    "Something here needed a closer look.",
)

FIXED_AUTOMATICALLY = "This was fixed automatically."
ADDRESSED = "This has been addressed."
NOT_FIXED_AUTOMATICALLY = "This was not fixed automatically."
LEFT_FOR_JUDGEMENT = "This is a judgement call, so it was left for you to decide."

#: A deck-wide message cannot say "this slide": a non-deck criterion that reaches
#: the deck advisory gets this line instead.
DECK_GRAIN_ISSUE = "One of the slides may need a closer look."
DECK_ADVISORY_HEADER_PREFIX = "Deck review found "
DECK_ADVISORY_HEADER_SUFFIX = " to look at in how the deck reads as a whole:"
DECK_ADVISORY_CLOSING = (
    "None of these were changed automatically. "
    "Reply here if you'd like any of them addressed."
)
#: Splits a chat message's plain lead from the reviewer's technical text.  Shared
#: with the frontend's Apply/Discuss writer and the chat collapse.
REVIEWER_DETAILS_SEPARATOR = "\n\nReviewer's details:\n"


def plain_issue(criterion: str, *, fixed: bool = False) -> str:
    """One plain sentence naming what is (or was) wrong; generic for an unknown criterion."""
    issue = PLAIN_ISSUES.get(criterion, GENERIC_ISSUE)
    return issue.past if fixed else issue.present


def plain_status(*, objective: bool, fixed: bool) -> str:
    """One plain sentence saying what happened to the finding."""
    if fixed:
        return FIXED_AUTOMATICALLY if objective else ADDRESSED
    return NOT_FIXED_AUTOMATICALLY if objective else LEFT_FOR_JUDGEMENT


def plain_finding_issue(finding: Finding) -> str:
    """The issue sentence alone, tense by status (any status but "fixed" is open)."""
    return plain_issue(finding.criterion, fixed=finding.status == "fixed")


def plain_finding_message(finding: Finding) -> str:
    """The plain-language text the drawer shows for *finding*.

    Reads ``criterion`` and ``status`` only (never ``message``).  Objectivity is
    the registry's when the criterion is known, exactly as ``_stamp_findings``
    re-derives it; the stored value is used only for an unknown criterion.
    """
    fixed = finding.status == "fixed"
    registered = CRITERIA.get(finding.criterion)
    objective = registered.objective if registered is not None else bool(finding.objective)
    return f"{plain_finding_issue(finding)} {plain_status(objective=objective, fixed=fixed)}"


def deck_advisory_issue(criterion: str) -> str:
    """The deck advisory's line for *criterion*: its plain sentence if deck-level, else deck-grain."""
    registered = CRITERIA.get(criterion)
    if registered is not None and registered.level == "deck":
        return plain_issue(criterion)
    return DECK_GRAIN_ISSUE
```

- [ ] **Step 1 (test author): write `tests/unit/test_finding_copy.py`.** It needs these behavioural tests:
  - `test_every_criterion_has_copy_and_no_copy_lacks_a_criterion`: `set(PLAIN_ISSUES) == set(CRITERIA)` in both directions, with the missing and extra names in the message.
  - `test_plain_copy_never_carries_technical_detail`:
    - **Inputs.** Parametrise over every copy string a user can see:
      - each `PlainIssue.present`/`.past`, including `GENERIC_ISSUE`
      - the four status sentences
      - `DECK_GRAIN_ISSUE`, `DECK_ADVISORY_HEADER_PREFIX`, `DECK_ADVISORY_HEADER_SUFFIX`, `DECK_ADVISORY_CLOSING`
      - `plain_finding_message(f)` and `plain_finding_issue(f)` for every criterion × `status ∈ {open, fixed}` × `objective ∈ {True, False}` (build `f` with `Finding.model_construct` so a flipped objective is allowed)
    - **Banned.** No match (case-insensitive) for any of: `#[0-9a-f]{3,8}\b`, `\d`, `px\b`, `rgba?\(`, `hsla?\(`, `:\s*1\b`, `\bwcag\b`, `\baa\b`, `%`, `_`, `` ` ``, `\*\*`, `\b(architect|foreman|builder|fixer|reviewer|analyst)\b`. No `CRITERIA` key as a substring. The second person is allowed (R7).
    - **Shape.** Every whole sentence (not the two header fragments) matches `^[A-Z].*\.$`.
    - **Length.** Each full `plain_finding_message` is ≤ 140 characters.
  - `test_every_criterion_reads_differently`: all `present` strings are unique across criteria, and for every criterion `present != past`.
  - `test_status_and_objectivity_choose_the_status_sentence`:
    - For an objective criterion (`overflow`):
      - open gives `endswith(NOT_FIXED_AUTOMATICALLY)` and starts with `PLAIN_ISSUES["overflow"].present`
      - fixed gives `endswith(FIXED_AUTOMATICALLY)` and starts with `.past`
    - For a subjective criterion (`brief_not_delivered`): open gives `LEFT_FOR_JUDGEMENT`, and fixed gives `ADDRESSED`.
    - The four status sentences are pairwise distinct.
    - `plain_finding_issue(f)` is a prefix of `plain_finding_message(f)` in every case.
  - `test_the_issue_example_becomes_one_plain_sentence_pair`:
    - **Constant.** Define the module constant `ISSUE_316_MESSAGE` as the verbatim technical message from #316: `The "NOTE" label in the bottom callout is Coral #FF5F46 at 13px/700 over the box fill (rgba(255,95,70,0.12) composited on navy #1B3139 ≈ #2D3A3C), giving roughly 3.9:1 — below the 4.5:1 AA floor for text this size. The template's own dark-background eyebrow colour (#FFC9BF) clears AA; use that instead of raw coral.`
    - **Finding.** Use it on a real `Finding(criterion="contrast_failure", category="design", objective=True, status="fixed", …)`.
    - **Expected.** `plain_finding_message(...) == "Some text was hard to read against its background. This was fixed automatically."` and `plain_finding_issue(...) == "Some text was hard to read against its background."`.
    - **Absent.** Neither contains `#FF5F46`, `3.9:1`, `13px`, `NOTE` or `coral`.
  - `test_plain_text_ignores_the_reviewer_message`: two findings identical except for `message` (one empty, one `ISSUE_316_MESSAGE`) give identical `plain_finding_message` and `plain_finding_issue`.
  - `test_objectivity_comes_from_the_registry_when_the_criterion_is_known`: `Finding.model_construct(criterion="overflow", objective=False, status="open", …)` gives a message ending `NOT_FIXED_AUTOMATICALLY`.
  - `test_an_unknown_criterion_gets_the_generic_copy`: `model_construct(criterion="retired_criterion", objective=False, status="open")` returns exactly `f"{GENERIC_ISSUE.present} {LEFT_FOR_JUDGEMENT}"`, and `plain_issue("retired_criterion", fixed=True) == GENERIC_ISSUE.past`. It does not raise.
  - `test_an_unrecognised_status_reads_as_open`: `model_construct(status="weird", criterion="overflow")` gives the open variant for both helpers.
  - `test_deck_advisory_lines_never_say_this_slide`: `deck_advisory_issue(c) == PLAIN_ISSUES[c].present` for every `level == "deck"` criterion. Every other criterion, and `"retired_criterion"`, gives `DECK_GRAIN_ISSUE`. No output contains "this slide" (case-insensitive).
  - `test_the_separator_is_exact_and_never_occurs_in_copy`: `REVIEWER_DETAILS_SEPARATOR == "\n\nReviewer's details:\n"`, and it occurs in no copy string from the sweep. A plain line can therefore never be taken for the split point.
  - `test_copy_is_not_rendered_into_any_prompt`:
    - **Strings checked.** Every string from the sweep (except the two header fragments, which are too generic to scan for), plus the separator.
    - **Must not appear in any of:**
      - `src.core.skills.build_reviewer`: `INSTRUCTIONS`, `build_instructions()`, `BUILD_REVIEWER_CRITERIA_STAGE`, `BUILD_REVIEWER_AUTHORED_INSTRUCTIONS`, `DECK_BRIEF_REVIEW`
      - `src.core.skills.deck_reviewer.INSTRUCTIONS`, `src.core.skills.fix_reviewer.INSTRUCTIONS`, `src.core.skills.fixer.INSTRUCTIONS`
      - the raw text of `src/services/agent_definition_manifest_v1.py`
  - **Sabotage.** Record these in the test docstring:
    - Put `{message}` into `plain_finding_message`'s output: the ignores-message and banned-content tests go red.
    - Delete one `PLAIN_ISSUES` entry: the coverage test goes red.
    - Make `deck_advisory_issue` return `plain_issue(criterion)` unconditionally: the deck-grain test goes red.
  - **Confirm red.** It fails with `ImportError`, because the module does not exist yet. Leave the tests uncommitted.
- [ ] **Step 2 (implementer):** create `src/domain/finding_copy.py` exactly as above. Do not edit `src/domain/finding.py`.
- [ ] **Step 3: verify.**
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316
  uv run pytest tests/unit/test_finding_copy.py tests/unit/test_finding_schema.py tests/unit/test_agent_schema_registry.py "tests/unit/test_architect_edit_prompt.py::test_schema_contract_digests_unchanged" -q
  ```

---

### Task 2: Pin that every agent keeps the technical message

Models: test=opus impl=haiku

**This task adds tests only.** They are characterisation tests and must be **green on first run**, with no production change. If any is red, STOP and report: it means an agent payload already differs from what the plan assumes. The implementer runs the tests, performs the sabotage checks, and proves `nodes.py` is restored.

**Files:**
- Modify: `tests/unit/test_graph_nodes.py`.
  - Add `class TestReviewersKeepTheTechnicalMessage`.
  - Add `Finding` to the `from src.domain.finding import (...)` line (`:33`). Today it imports only `VERDICT_KEY, DeckReviewOutput, make_finding_id`.
  - Add `from src.domain.finding_copy import PLAIN_ISSUES, GENERIC_ISSUE, FIXED_AUTOMATICALLY, ADDRESSED, NOT_FIXED_AUTOMATICALLY, LEFT_FOR_JUDGEMENT, DECK_GRAIN_ISSUE`.

**Existing helpers to use (verified):**
- `graph_env` fixture: `graph_env.skills.set(role, value_or_callable)`, `graph_env.skills.calls_for(role)[i]["payload"]`, `graph_env.rows()`, `graph_env.seed_slides(htmls)`, `graph_env.state(**kw)`, `graph_env.deck_row()`, `graph_env.messages()` (`tests/unit/conftest_graph.py`)
- `conftest_graph.py`: `finding(criterion, *, message=…, slide_index=…)` (`:102`), `review_out` (`:205`), `fixer_out` (`:194`), `architect_build` (`:181`), `make_spec`
- `test_graph_nodes.py`: `_branch_payload(env, position, html=…)` (`:102`), `_fix_state(env, entries)` (`:2331`), `turn_scoped_merge`, `TURN` (`:98`)
- The chaining pattern to follow is at `test_graph_nodes.py:4535-4545`.

- [ ] **Step 1 (test author):** write these tests. Use a module constant `ISSUE_316_MESSAGE` (same text as Task 1) and a helper `_all_plain_copy()` that returns every user-visible copy string from `finding_copy`.
  - **`test_the_fixer_receives_the_build_reviewers_message_verbatim`.**
    - The build reviewer returns `review_out(0, [finding("contrast_failure", message=ISSUE_316_MESSAGE)])`.
    - `reviewed = build_reviewer_node(_branch_payload(graph_env, 0, html="<div class='slide'>built</div>"))`, then `fixer_node(_fix_state(graph_env, {0: reviewed["fix_map"]["vals"][0]}))` with `graph_env.skills.set("fixer", fixer_out)`.
    - Assert, on the fixer payload: `payload["finding"]["message"] == ISSUE_316_MESSAGE` (exact), `set(payload["finding"]) == set(Finding.model_fields)` and `payload["finding"]["criterion"] == "contrast_failure"`.
    - Also assert that no `_all_plain_copy()` string occurs in `json.dumps(payload)`, and that neither `plain_message`, `plainMessage`, `plain_issue` nor `plainIssue` occurs in it.
  - **`test_the_fix_reviewer_receives_the_same_finding_verbatim`.**
    - Continue the chain: merge `fixed["fix_map"]` with `turn_scoped_merge`, set `state["fixed"]` and `state["fix_target"]`, have `fix_reviewer` return `review_out(0)`, then call `fix_reviewer_node(state)`.
    - Make the same assertions on `calls_for("fix_reviewer")[0]["payload"]["finding"]`.
    - The written row's record (`json.loads(graph_env.rows()[0].verification_record)`) holds the finding with `message == ISSUE_316_MESSAGE` and `status == "fixed"`. No plain copy appears in the raw JSON.
  - **`test_the_persisted_record_of_a_surfaced_slide_holds_only_finding_fields`.**
    - The build reviewer returns a subjective `finding("brief_not_delivered", message="The brief asks for a timeline; the slide gives none.")`, so there is no fix path. Call `build_reviewer_node(...)`.
    - Each finding dict in the raw row JSON has keys exactly `set(Finding.model_fields)` and the message verbatim. No plain copy appears in the raw JSON.
  - **`test_the_next_architect_turn_receives_deck_findings_verbatim`.**
    - `graph_env.seed_slides(htmls)`. The deck reviewer returns `DeckReviewOutput(findings=[finding("arc_gap", slide_index=-1, message=NARRATIVE)])` with `NARRATIVE = "Slide 4 presents pilot results before slide 2 introduces the pilot."`. Call `deck_reviewer_node(graph_env.state(turn_id=TURN))`.
    - Then `graph_env.skills.set("architect", architect_build(make_spec((0, 1))))` and `architect_node(graph_env.state())`.
    - The architect payload's `previous_deck_review["findings"][0]` has `message == NARRATIVE` and keys exactly `set(Finding.model_fields)`. No plain copy occurs in `json.dumps(payload)`.
    - If the digest lookup misses, follow the seeded-HTML pattern of `test_calls_get_deck_review_with_db_deck_id_and_digest` (`:1405`). STOP and report rather than mocking `get_deck_review`, because the real store is the point.
  - **Docstring sabotage notes.** (1) In `fixer_node`, change `"finding": finding` (`nodes.py:2663`) to `{**finding, "message": "x"}`: test 1 goes red. (2) Add `"plain_message": "x"` there instead: the key-set assertion goes red.
- [ ] **Step 2 (implementer):** run the tests. They must pass with **no production change**. Perform the two sabotage checks, confirm red each time, then revert.
- [ ] **Step 3: verify.** The last command must exit 0. It proves no sabotage edit survived; review #20.
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316
  uv run pytest "tests/unit/test_graph_nodes.py::TestReviewersKeepTheTechnicalMessage" -q
  git diff --exit-code -- src/services/graph/nodes.py
  ```

---

### Task 3: Project `plainMessage` and `plainIssue` on the read path and declare them in TypeScript

Models: test=opus impl=haiku

The conformance-test edits are deliberate contract changes, made by the test author. The production change is a few lines plus transcription.

**Files:**
- Modify: `src/api/services/session_manager.py`. Change `_finding_to_camel` (`:191-203`), and add an import beside `from src.domain.finding import findings_from_record` (`:32`).
- Modify: `frontend/src/types/finding.ts`.
- Modify: `tests/unit/test_finding_conformance.py`, `tests/unit/test_deck_read_path_keys.py`, `tests/unit/test_tour_staged_demo.py`.
- Modify the **seven** typed `SlideFinding` literals, which `npx tsc -b` requires (review #10):
  - `frontend/tests/fixtures/findings.ts`: f1, f2, f3
  - `frontend/tests/e2e/findings-drawer.spec.ts`: `sentinel` (`:75`), `postReorderFinding` (`:124`)
  - `frontend/tests/e2e/spec-view.spec.ts`: `SLIDE0_FINDINGS` (`:123`), two entries

**Interfaces:**

```python
# session_manager.py — import: from src.domain.finding_copy import plain_finding_issue, plain_finding_message
# _finding_to_camel keeps its signature; appended after the generic loop:
    # Derived, read-time only (#316): never Finding fields (that would move the
    # reviewers' output-schema digests) and never persisted.  See
    # src/domain/finding_copy.py.
    camel["plainMessage"] = plain_finding_message(finding)
    camel["plainIssue"] = plain_finding_issue(finding)
    return camel
```

Update its docstring. The generic loop still mirrors `Finding` fields automatically. `plainMessage` and `plainIssue` are the projection-only keys, pinned by `PROJECTION_ONLY_FIELDS` in `tests/unit/test_finding_conformance.py`.

```ts
// frontend/src/types/finding.ts — SlideFinding gains (after `message`):
  plainMessage: string; // issue + status, derived at read time (src/domain/finding_copy.py via _finding_to_camel); NOT a Python Finding field
  plainIssue: string;   // the issue sentence alone (tense by status); same derivation; leads Apply/Discuss requests

// new export, after CATEGORY_LABEL:
/** Shown if a finding arrives without plainMessage/plainIssue (an untyped mock or a stale API cache). Equals
 *  GENERIC_ISSUE.present in src/domain/finding_copy.py — pinned by test_finding_conformance.py. */
export const PLAIN_MESSAGE_FALLBACK = "Something here may need a closer look.";
```

Values for the typed literals are transcriptions of D8. Use double-quoted strings.

| literal | criterion / objective / status | `plainMessage` | `plainIssue` |
|---|---|---|---|
| fixtures `f1` | rogue_colour / true / fixed | "A colour on this slide was outside the deck's colour scheme. This was fixed automatically." | "A colour on this slide was outside the deck's colour scheme." |
| fixtures `f2` | source_contradiction / true / open | "A figure on this slide does not match the source data. This was not fixed automatically." | "A figure on this slide does not match the source data." |
| fixtures `f3` | arc_gap / false / open | "The story has a gap or an unexplained jump between slides. This is a judgement call, so it was left for you to decide." | "The story has a gap or an unexplained jump between slides." |
| drawer-spec `sentinel` and `postReorderFinding` | brief_not_delivered / false / open | "This slide may not cover everything planned for it. This is a judgement call, so it was left for you to decide." | "This slide may not cover everything planned for it." |
| spec-view `s0-dismiss-me` | source_contradiction / true / open | "A figure on this slide does not match the source data. This was not fixed automatically." | "A figure on this slide does not match the source data." |
| spec-view `s0-keep-me` | rogue_colour / true / open | "A colour on this slide is outside the deck's colour scheme. This was not fixed automatically." | "A colour on this slide is outside the deck's colour scheme." |

- [ ] **Step 1 (test author): conformance and read-path tests.**
  - **`test_finding_conformance.py`.**
    - Add the module constant `PROJECTION_ONLY_FIELDS = {"plainMessage", "plainIssue"}`, with a comment: these are keys the read path derives; they are not `Finding` fields; they must never become one, because that would move the reviewer schema digests.
    - Add the helper `_ts_string_constant(path: Path, name: str) -> str` (review #22). It applies `re.search(rf"export const {name}(?:\s*:\s*string)?\s*=\s*(['\"])(.*?)\1\s*;", text)` and asserts `m` with `f"{name} not found in {path}"`, so it fails loudly. It returns `json.loads('"' + m.group(2).replace("\\'", "'") + '"')`, which decodes `\n`.
    - Change `test_no_extra_ts_fields_beyond_backend` to `extra = ts_fields - camel_fields - PROJECTION_ONLY_FIELDS`.
    - Add `test_projection_only_fields_are_declared_in_ts_and_absent_from_finding`: `PROJECTION_ONLY_FIELDS <= ts_fields`, and for each one `_camel_to_snake(name) not in Finding.model_fields`.
    - Add `test_finding_to_camel_adds_the_plain_keys_and_keeps_every_finding_field_verbatim`.
      - Import `from src.api.services.session_manager import _finding_to_camel`.
      - Use the `ISSUE_316_MESSAGE` contrast finding, once with status open and once with status fixed.
      - The result equals `{camel(k): v for k, v in f.model_dump().items()} | {"plainMessage": plain_finding_message(f), "plainIssue": plain_finding_issue(f)}`. That shows `message` is unchanged.
    - Change `test_read_path_entry_round_trips_back_into_a_domain_finding` to drop the `PROJECTION_ONLY_FIELDS` keys before rebuilding `Finding`. `Finding` silently ignores extra keys, so do not rely on that.
    - Add `test_ts_plain_message_fallback_is_the_python_generic_copy`: `_ts_string_constant(FINDING_TS, "PLAIN_MESSAGE_FALLBACK") == GENERIC_ISSUE.present`.
    - Add `test_typed_fixture_literals_carry_the_python_copy` (review #21).
      - In each of `frontend/tests/fixtures/findings.ts`, `frontend/tests/e2e/findings-drawer.spec.ts` and `frontend/tests/e2e/spec-view.spec.ts`, find every flat object literal matching `\{[^{}]*plainMessage[^{}]*\}`.
      - Assert the counts are exactly 3, 2 and 2.
      - From each, extract `criterion: '…'`, `objective: (true|false)`, `status: '…'` and the quoted `plainMessage` and `plainIssue` (quote-capturing as above).
      - Assert `plainMessage == plain_finding_message(m)` and `plainIssue == plain_finding_issue(m)`, where `m = Finding.model_construct(criterion=…, objective=…, status=…)`.
  - **`test_deck_read_path_keys.py`.**
    - Add `"plainMessage"` and `"plainIssue"` to `_SLIDE_FINDING_KEYS` (`:93`). `_assert_flat_finding_list` then checks presence in every path test.
    - Add `class TestPlainMessage`. `_write_findings` writes open, objective `overflow` findings, so `EXPECTED_MESSAGE = f"{PLAIN_ISSUES['overflow'].present} {NOT_FIXED_AUTOMATICALLY}"` and `EXPECTED_ISSUE = PLAIN_ISSUES['overflow'].present`.
      - Path tests, each asserting every entry's `plainMessage`, its `plainIssue`, and an unchanged `message`:
        - `test_row_read_path_derives_the_plain_keys` (`deck_with_spec`)
        - `test_blob_path_derives_the_plain_keys` (`deck_with_spec_but_no_rows`)
        - `test_legacy_fallback_derives_the_plain_keys` (`contributor_session_with_spec`, `get_slide_deck_as_contributor()`; this also covers the shared-deck contributor read)
      - `test_a_fixed_finding_reads_in_the_past_tense` (review #13).
        - Persist a `status="fixed"` `contrast_failure` finding through a hand-built record, using `write_slide_verification` under `fixture._patched()`, as `_write_findings` does.
        - Assert `plainMessage == f"{PLAIN_ISSUES['contrast_failure'].past} {FIXED_AUTOMATICALLY}"` and `plainIssue == PLAIN_ISSUES['contrast_failure'].past`.
      - `test_a_record_written_before_plain_messages_existed_still_renders`.
        - Hand-build the raw record `{h: {VERDICT_KEY: {"verdict": "surfaced", "findings": [{"id": f"contrast_failure:{h}:0", "slide_index": 0, "category": "design", "criterion": "contrast_failure", "message": ISSUE_316_MESSAGE, "objective": True}]}}}`. It has no `status` and no `seen`, as an older writer would produce. Persist it the same way.
        - Assert `plainMessage == f"{PLAIN_ISSUES['contrast_failure'].present} {NOT_FIXED_AUTOMATICALLY}"` and `message == ISSUE_316_MESSAGE`.
      - `test_the_plain_keys_are_never_written_back`. After `get_slide_deck()` on the row path, the raw `SessionSlide.verification_record` contains none of `plainMessage`, `plain_message`, `plainIssue` or `plain_issue`. On the blob path, `_stored_deck_json(fixture)` contains none of them either.
  - **`test_tour_staged_demo.py`.** Add `test_the_surfaced_finding_carries_plain_keys_and_keeps_its_scripted_detail`. After `_run_through(sid, "build")`, the single finding has:
    - `plainMessage == f"{PLAIN_ISSUES['brief_not_delivered'].present} {LEFT_FOR_JUDGEMENT}"`
    - `plainIssue == PLAIN_ISSUES['brief_not_delivered'].present`
    - `message == fx["stages"]["build"]["findings"]["2"][0]["message"]`
  - **Confirm red (review #8).** These should fail:
    - the read-path key-set assertions
    - the plain-key value tests
    - the fallback pin (`PLAIN_MESSAGE_FALLBACK not found`)
    - the fixture-literal test (no literal carries `plainMessage` yet, so the count is 0)
    - the `_finding_to_camel` equality test

    `test_read_path_entry_keys_are_exactly_the_declared_slidefinding_fields` stays **green** in the red state, because neither side has changed yet. It guards the half-implemented state, where only one side changed. Do not expect it red. Leave the tests uncommitted.
- [ ] **Step 2 (implementer):** make the `_finding_to_camel` change and import, add the `finding.ts` fields and constant, and update the seven typed literals. Edit no tests beyond the listed fixture literals.
- [ ] **Step 3: verify.**
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316
  uv run pytest tests/unit/test_finding_conformance.py tests/unit/test_deck_read_path_keys.py tests/unit/test_tour_staged_demo.py tests/unit/test_tour_fixture_script.py tests/unit/test_graph_lifecycle_playwright_contract.py -q
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx tsc -b
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx eslint src/types/finding.ts tests/fixtures/findings.ts tests/e2e/findings-drawer.spec.ts tests/e2e/spec-view.spec.ts
  ```

---

### Task 4: Drawer shows the plain message, with a collapsed details disclosure; request writers

Models: test=opus impl=sonnet

**Files:**
- Create: `frontend/src/utils/findingText.ts`
- Create: `frontend/src/utils/findingText.test.ts`
- Modify: `frontend/src/components/SlideViewer/FeedbackDrawer.tsx`
- Modify: `frontend/src/components/SlideViewer/FeedbackDrawer.test.tsx`
- Modify: `tests/unit/test_finding_conformance.py` (separator pin)

**Interfaces (new):**

```ts
// frontend/src/utils/findingText.ts
import { PLAIN_MESSAGE_FALLBACK, type SlideFinding } from '../types/finding';

/** Splits a chat message's plain lead from the reviewer's technical text. Mirrors
 *  REVIEWER_DETAILS_SEPARATOR in src/domain/finding_copy.py (pinned equal). */
export const REVIEWER_DETAILS_SEPARATOR = "\n\nReviewer's details:\n";
export const APPLY_REQUEST_LEAD = "Please fix this on slide";
export const DISCUSS_REQUEST_LEAD = "I'd like to discuss this on slide";

/** The drawer's plain-language line for a finding; never the technical message. */
export function findingPlainText(f: Pick<SlideFinding, 'plainMessage'>): string {
  const text = typeof f.plainMessage === 'string' ? f.plainMessage.trim() : '';
  return text || PLAIN_MESSAGE_FALLBACK;
}

/** The issue sentence alone, for request leads. */
export function findingPlainIssue(f: Pick<SlideFinding, 'plainIssue'>): string {
  const text = typeof f.plainIssue === 'string' ? f.plainIssue.trim() : '';
  return text || PLAIN_MESSAGE_FALLBACK;
}

function withReviewerDetails(lead: string, f: SlideFinding): string {
  return f.message.trim() ? `${lead}${REVIEWER_DETAILS_SEPARATOR}${f.message}` : lead;
}

/** Chat text for Apply: a plain lead for the user, the reviewer's text (verbatim) for the agents. */
export function applyFindingRequest(f: SlideFinding): string {
  return withReviewerDetails(`${APPLY_REQUEST_LEAD} ${f.slideIndex + 1}: ${findingPlainIssue(f)}`, f);
}

/** Chat text for Discuss, same shape. */
export function discussFindingRequest(f: SlideFinding): string {
  return withReviewerDetails(`${DISCUSS_REQUEST_LEAD} ${f.slideIndex + 1}: ${findingPlainIssue(f)}`, f);
}
```

**`FeedbackDrawer` behaviour.** The component signature is unchanged. Inside each `<li data-testid={`finding-${f.id}`}>`:
- **Plain text.** Replace `<p className="mb-2 text-xs text-foreground">{f.message}</p>` (`:128`) with `<p data-testid={`finding-plain-${f.id}`} className="mb-1 text-xs text-foreground">{findingPlainText(f)}</p>`. Import `findingPlainText` from `'../../utils/findingText'`.
- **Toggle.** When `f.message.trim() !== ''`, render `<button type="button" data-testid={`finding-details-toggle-${f.id}`} aria-expanded={isOpen}>`.
  - Label: `Show details` or `Hide details`.
  - Icon: `ChevronRight` or `ChevronDown`. Add `ChevronRight` to the existing `lucide-react` import.
  - Classes: `text-[11px] text-muted-foreground hover:text-foreground`.
- **Details.** Only while expanded, render `<p data-testid={`finding-details-${f.id}`} className="mt-1 whitespace-pre-wrap break-words text-[11px] text-muted-foreground">{f.message}</p>`.
- **State.** `useState<ReadonlySet<string>>(() => new Set())`, keyed by finding id and toggled immutably. Collapsed by default, not persisted, independent per finding.
- **Unchanged.** Keep `mb-2` spacing before the status and buttons block. The "Fixed" badge and Apply/Dismiss/Discuss stay as they are.

- [ ] **Step 1 (test author):**
  - **`findingText.test.ts`.** Use `TECH` = the #316 example verbatim, including the hex codes, `≈` and `—`.
    - `findingPlainText` returns the trimmed `plainMessage`, and `PLAIN_MESSAGE_FALLBACK` for `''`, `'   '` and `undefined` (cast).
    - `findingPlainIssue` behaves the same on `plainIssue`.
    - `applyFindingRequest({ slideIndex: 2, plainIssue: I, plainMessage: M, message: TECH, … })` **strictly equals** `` `Please fix this on slide 3: ${I}${REVIEWER_DETAILS_SEPARATOR}${TECH}` ``. It does not contain `M` (review #2).
    - The lead (the text before `REVIEWER_DETAILS_SEPARATOR`) does not contain `TECH`.
    - A blank `message` gives exactly the lead, with no separator.
    - `discussFindingRequest` behaves the same, with the `I'd like to discuss this on slide 3:` lead.
  - **`FeedbackDrawer.test.tsx`.**
    - Add `plainMessage` and `plainIssue` to the two existing literals.
    - Change the helper to `renderDrawer(findings: SlideFinding[], hasUnseen = false, cbs: DrawerCallbacks = callbacks)` (review #15).
    - Add `describe('FeedbackDrawer — plain message and details')`. `ViewerProvider` defaults to `drawerOpen: true` (`ViewerContext.tsx:17-18`), so clear `localStorage` in `beforeEach` and the drawer body renders without a click. The tests:
      1. `finding-plain-<id>` text equals `plainMessage`, and `screen.queryByText(TECH)` is null: the technical text is not in the DOM.
      2. The toggle starts at `aria-expanded="false"`. After a click it is `"true"`, and `getByTestId('finding-details-<id>').textContent === TECH` (strict, not normalised). A second click removes the details.
      3. With two findings, expanding one leaves the other's `finding-details-*` absent.
      4. `message: '   '` renders no toggle.
      5. `plainMessage: ''` makes `finding-plain-<id>` show `PLAIN_MESSAGE_FALLBACK`.
      6. Clicking the toggle calls none of `onApplyFinding`, `onDismissFinding` or `onDiscussFinding` (`vi.fn()` spies passed as `cbs`).
      7. A fixed finding still shows its plain text, the `Fixed` badge and a details toggle.
    - Sabotage notes in the header: rendering `f.message` in the plain `<p>` turns test 1 red. Initialising the expanded set with every id turns test 2 red.
  - **`test_finding_conformance.py`.** Add `test_ts_reviewer_details_separator_matches_python`: `_ts_string_constant(REPO_ROOT / "frontend/src/utils/findingText.ts", "REVIEWER_DETAILS_SEPARATOR") == finding_copy.REVIEWER_DETAILS_SEPARATOR`.
  - **Confirm red.** Leave the tests uncommitted.
- [ ] **Step 2 (implementer):** create `findingText.ts` as given and change `FeedbackDrawer.tsx`. Do not touch `SlideViewer.tsx`, `AppLayout.tsx` or `Message.tsx` in this task.
- [ ] **Step 3: verify.** Run each command separately.
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/components/SlideViewer/ src/utils/findingText.test.ts
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx tsc -b
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx eslint src/components/SlideViewer src/utils/findingText.ts src/utils/findingText.test.ts src/types/finding.ts
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316 && uv run pytest tests/unit/test_finding_conformance.py -q
  ```

---

### Task 5: Apply and Discuss send the plain lead plus the reviewer's details

Models: test=opus impl=haiku

**Files:**
- Modify: `frontend/src/components/Layout/AppLayout.tsx`: `handleApplyFinding` (`:1062-1069`) and `handleDiscussFinding` (`:1078-1086`), plus one import
- Modify: `frontend/tests/e2e/findings-drawer.spec.ts`

**Change.**
- In `handleApplyFinding`, replace the template literal with `handleSendMessage(applyFindingRequest(finding))`.
- In `handleDiscussFinding`, use `handleSendMessage(discussFindingRequest(finding))`.
- Import both from `'../../utils/findingText'`.
- Change nothing else in either handler: guards, chat expansion and dependency arrays stay as they are.
- Update the two handler comments: the lead is plain, the detail is for the agents, and `Message.tsx` collapses it (D4).
- Do **not** touch the pre-existing lint at `:1073` (`_findingId` in `handleDismissFinding`) or anywhere else in the file.

- [ ] **Step 1 (test author, e2e).** In `findings-drawer.spec.ts`, import `mockFindings` from `'../fixtures/findings'` and `REVIEWER_DETAILS_SEPARATOR` from `'../../src/utils/findingText'`. Let `f2 = mockFindings.find(f => f.id === 'f2')!`.
  - **Modify** "clicking Apply sends a chat request containing the finding message".
    - Keep the existing assertions, including `toContain('35%')`.
    - `body.message` **strictly equals** `` `Please fix this on slide 2: ${f2.plainIssue}${REVIEWER_DETAILS_SEPARATOR}${f2.message}` ``.
  - **New** `test.describe('findings-drawer — plain message first, details on request')`, test "the drawer leads with the plain message and hides the reviewer's details until asked".
    - Go to slide 1. `finding-plain-f2` has text `f2.plainMessage`.
    - `page.getByText(f2.message)` has count 0, and the toggle has `aria-expanded="false"`.
    - After clicking it, `finding-details-f2` has text `f2.message` and the toggle has `aria-expanded="true"`.
  - **New** "clicking Discuss sends the plain lead and the reviewer's details". Use the same route capture as the Apply test. Click `finding-discuss-f2`. `body.message` strictly equals `` `I'd like to discuss this on slide 2: ${f2.plainIssue}${REVIEWER_DETAILS_SEPARATOR}${f2.message}` ``.
  - **Confirm red.** Only the Apply and Discuss body tests are red, because AppLayout still posts the old text. The drawer test is **already green**, since Task 4 shipped the drawer (review #9). That is expected; do not stop. Leave the tests uncommitted.
- [ ] **Step 2 (implementer):** make the two handler edits and add the import.
- [ ] **Step 3: verify.** Run each command separately. Lint must report the same 4 pre-existing `AppLayout.tsx` errors (same rule ids and messages) and nothing new.
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx tsc -b
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx eslint src/components/Layout/AppLayout.tsx tests/e2e/findings-drawer.spec.ts
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx playwright test tests/e2e/findings-drawer.spec.ts tests/e2e/slide-viewer.spec.ts tests/e2e/spec-view.spec.ts tests/e2e/app-tour.spec.ts --project=chromium --workers=1
  ```

---

### Task 6: Deck-review advisory: plain lines, then the reviewer's details

Models: test=opus impl=sonnet

**Files:**
- Modify: `src/services/graph/nodes.py`. Change only `_advisory_text` (`:1299-1317`), plus one import beside the existing `src.domain.finding` import (`:64`):
  ```python
  from src.domain.finding_copy import (
      DECK_ADVISORY_CLOSING, DECK_ADVISORY_HEADER_PREFIX, DECK_ADVISORY_HEADER_SUFFIX,
      REVIEWER_DETAILS_SEPARATOR, deck_advisory_issue,
  )
  ```
  Do not touch `_surface_notice` (its signature stays the same and it writes no `metadata`), `_placehold_failed_position`, or any failure advisory in `deck_reviewer_node`. Those belong to #321.
- Modify: `tests/unit/test_graph_nodes.py`. Add `CRITERIA` to the `src.domain.finding` import and `DECK_ADVISORY_CLOSING, DECK_ADVISORY_HEADER_PREFIX, DECK_ADVISORY_HEADER_SUFFIX, REVIEWER_DETAILS_SEPARATOR, plain_issue` to the `finding_copy` import added in Task 2. Add `from src.services.graph.event_emitter import set_chat_request_id` (`set_event_emitter` is already imported from there, `:50`). Add `from src.api.services.session_manager import get_session_manager`. Call the function as `nodes._advisory_text`: it is not in the `from src.services.graph.nodes import (...)` block (`:51-63`); review #14.

**Interface.** The signature is unchanged: `_advisory_text(findings: List[Finding]) -> str`. New body (`Dict` is already imported, `nodes.py:52`):

```python
def _advisory_text(findings: List[Finding]) -> str:
    """Compose the deck-review advisory from findings alone (§5, Ruling C-3).

    ``DeckReviewOutput`` declares ``findings`` and nothing else, so the message is
    composed here.  Shape (#316): plain lines from src/domain/finding_copy.py
    (never a criterion slug), one closing line, then the REVIEWER_DETAILS_SEPARATOR
    section with each reviewer message verbatim — the only actionable slide
    references.  frontend/src/utils/findingText.ts matches exactly this shape to
    collapse the details; the strings are pinned equal by
    tests/unit/test_finding_conformance.py.  This is an ``info`` row, so neither
    replay path (``_conversation``, ``_hydrate_chat_history``) feeds it back to the
    architect.  The empty-list line is byte-identical to before: the tour fixture
    and the integration suites pin it, and a silent absence is indistinguishable
    from a review that never ran.
    """
    if not findings:
        return (
            "Deck review complete: no narrative issues found across the deck."
        )
    counts: Dict[str, int] = {}
    for finding in findings:
        line = deck_advisory_issue(finding.criterion)
        counts[line] = counts.get(line, 0) + 1
    total = len(findings)
    lines = [
        f"{DECK_ADVISORY_HEADER_PREFIX}{total} "
        f"{'thing' if total == 1 else 'things'}{DECK_ADVISORY_HEADER_SUFFIX}"
    ]
    for line, count in counts.items():  # first-seen order
        lines.append(f"- {line[:-1]} (noted {count} times)." if count > 1 else f"- {line}")
    lines.append(DECK_ADVISORY_CLOSING)
    text = "\n".join(lines)
    details = [f"- {finding.message}" for finding in findings if finding.message.strip()]
    if details:
        text += REVIEWER_DETAILS_SEPARATOR + "\n".join(details)
    return text
```

- [ ] **Step 1 (test author):**
  - **Edit** `TestDeckReviewerReview::test_persists_the_review_against_the_deck_digest_and_surfaces_info` (`:3261`). The slug assertion is at `:3288`. Replace `assert "arc_gap" in info[0]["content"]` with:
    - `head = info[0]["content"].partition(REVIEWER_DETAILS_SEPARATOR)[0]`
    - `assert plain_issue("arc_gap") in head`
    - `assert "arc_gap" not in head`

    This is an intended contract change. Note it in the commit message.
  - **New** `class TestDeckAdvisoryIsPlain`:
    - **`test_no_findings_line_is_byte_identical`.** `nodes._advisory_text([]) == "Deck review complete: no narrative issues found across the deck."`, and it does not contain `REVIEWER_DETAILS_SEPARATOR`.
    - **`test_one_finding_reads_as_plain_language_then_details`.**
      - Input: one `arc_gap` finding with `message=NARRATIVE_TECH = "arc_gap between narrative_arc[1] and positions 3,4 (#1B3139 callout)"`.
      - The output **equals** `"Deck review found 1 thing to look at in how the deck reads as a whole:\n- The story has a gap or an unexplained jump between slides.\nNone of these were changed automatically. Reply here if you'd like any of them addressed.\n\nReviewer's details:\n- arc_gap between narrative_arc[1] and positions 3,4 (#1B3139 callout)"`.
    - **`test_repeated_lines_collapse_with_a_count`.**
      - Input: findings `[arc_gap, missing_conclusion, arc_gap]`.
      - The header says `3 things`.
      - Line 2 is `- The story has a gap or an unexplained jump between slides (noted 2 times).` and line 3 is the `missing_conclusion` present sentence, in first-seen order.
      - The details section has three bullets, in input order.
    - **`test_slide_level_criteria_get_the_deck_grain_line`** (review #5).
      - Input: findings `[overflow, arc_gap, rogue_colour, brief_not_delivered]`, each with a distinctive message that does not itself contain "this slide".
      - The head (before the separator) contains exactly the line `- One of the slides may need a closer look (noted 3 times).`. The full stop moves after the count because of `line[:-1]`.
      - The `arc_gap` line comes second, in first-seen order.
      - The head has no line containing "this slide" (case-insensitive).
    - **`test_the_head_never_carries_a_slug_or_a_reviewer_message`.**
      - Inputs: every `CRITERIA` key in turn, each with a distinctive message such as `"MSG-<criterion>-#ABCDEF"`.
      - The head contains no `CRITERIA` key, no `_`, no `#`, and no substring of any message.
      - The details section is exactly `"\n".join(f"- {m}" for m in messages)`.
    - **`test_blank_reviewer_messages_add_no_details_section`.** With every message `"  "`, the output has no separator and ends with `DECK_ADVISORY_CLOSING`. With one blank and one real message, there is a single bullet.
    - **`test_both_transports_carry_the_same_advisory_and_the_details_verbatim`** (review #12).
      - **Setup.** `graph_env.seed_slides(htmls)`. The deck reviewer returns `arc_gap` with `M1 = "Slide 4 presents pilot results before slide 2 introduces the pilot."` and `missing_conclusion` with `M2 = "The final slide restates the agenda instead of a recommendation."`.
      - **Run.** Install an emitter with `queue.Queue()` and `set_event_emitter`, as `_run_and_capture` does (`:940-956`), and call `set_chat_request_id("req-316")`. Then call `deck_reviewer_node(graph_env.state(turn_id=TURN))`. In a `finally` block, call `set_event_emitter(None)` and `set_chat_request_id(None)`.
      - **SSE leg.** The one event with `metadata["node"] == "deck_reviewer"`.
      - **Poll leg.** `sm = get_session_manager()`, then `[sm.msg_to_stream_event(m) for m in sm.get_messages_for_request("req-316") if m["role"] != "user"]`. This is exactly what `GET /chat/poll` does (`src/api/routes/chat.py:901-914`). It must hold exactly one event.
      - **Parity.** `poll[0]["content"] == sse.content`.
      - **Content.** On that content:
        - `head, sep, details = content.partition(REVIEWER_DETAILS_SEPARATOR)`, and `sep` is non-empty
        - `details.split("\n") == [f"- {M1}", f"- {M2}"]`
        - neither `M1`, `M2` nor `"arc_gap"` is in `head`
      - **Store.** `[f.message for f in get_deck_review(db, graph_env.deck_row().id, compute_deck_digest(htmls))["findings"]] == [M1, M2]`: `deck_reviews` keeps the messages.
    - **Sabotage note.** Restoring `lines.append(f"- {finding.criterion}: {finding.message}")` turns the head tests red. Dropping the details block turns the transport test red.
  - **Confirm red.** Leave the tests uncommitted.
- [ ] **Step 2 (implementer):** replace `_advisory_text`'s body and add the import. Nothing else in `nodes.py` changes.
- [ ] **Step 3: verify.**
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316
  uv run pytest tests/unit/test_graph_nodes.py tests/unit/test_tour_fixture_script.py -q -n 4
  uv run pytest tests/integration/test_graph_orchestration.py tests/integration/test_architect_reply_is_persisted.py -q
  ```

---

### Task 7: Collapse the "Reviewer's details" section in chat bubbles

Models: test=opus impl=sonnet

**Sequencing.** This task runs after Task 5 (AppLayout) and Task 6 (advisory writer), so both shapes exist.

**Files:**
- Modify: `frontend/src/utils/findingText.ts` (add constants and parsers)
- Modify: `frontend/src/utils/findingText.test.ts`
- Modify: `frontend/src/components/ChatPanel/Message.tsx`. Change the regular branch only (`:126-143`). Leave the tool and HTML branches (`:61-124`) untouched.
- Create: `frontend/src/components/ChatPanel/Message.findingRequest.test.tsx`. It is **not** `Message.test.tsx`, which #321 creates.
- Modify: `frontend/tests/e2e/findings-drawer.spec.ts`
- Modify: `tests/unit/test_finding_conformance.py` (deck-constant pins)

**Interfaces (new, appended to `findingText.ts`):**

```ts
/** Mirrors src/domain/finding_copy.py (pinned equal by tests/unit/test_finding_conformance.py). */
export const DECK_ADVISORY_HEADER_PREFIX = "Deck review found ";
export const DECK_ADVISORY_HEADER_SUFFIX = " to look at in how the deck reads as a whole:";
export const DECK_ADVISORY_CLOSING =
  "None of these were changed automatically. Reply here if you'd like any of them addressed.";

export interface SplitMessage { lead: string; details: string }

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const FINDING_REQUEST_LEAD = new RegExp(
  `^(?:${escapeRegExp(APPLY_REQUEST_LEAD)}|${escapeRegExp(DISCUSS_REQUEST_LEAD)}) [1-9]\\d*: [^\\n]+$`,
);
const DECK_ADVISORY_LEAD = new RegExp(
  `^${escapeRegExp(DECK_ADVISORY_HEADER_PREFIX)}[1-9]\\d* things?${escapeRegExp(DECK_ADVISORY_HEADER_SUFFIX)}` +
  `\\n(?:- [^\\n]+\\n)+${escapeRegExp(DECK_ADVISORY_CLOSING)}$`,
);

function splitAt(content: string, lead: RegExp): SplitMessage | null {
  const at = content.indexOf(REVIEWER_DETAILS_SEPARATOR);
  if (at < 0) return null;
  const head = content.slice(0, at);
  const details = content.slice(at + REVIEWER_DETAILS_SEPARATOR.length);
  return lead.test(head) && details.trim() !== '' ? { lead: head, details } : null;
}

/** A user message written by applyFindingRequest/discussFindingRequest, else null. */
export const splitFindingRequest = (content: string): SplitMessage | null =>
  splitAt(content, FINDING_REQUEST_LEAD);

/** An assistant deck-review advisory written by nodes._advisory_text, else null. */
export const splitDeckAdvisory = (content: string): SplitMessage | null =>
  splitAt(content, DECK_ADVISORY_LEAD);
```

**`Message.tsx` (regular branch).** Import `splitDeckAdvisory` and `splitFindingRequest` from `'../../utils/findingText'`.

```tsx
  const isUser = message.role === 'user';
  // #316: collapse the reviewer's technical section of exactly the two shapes this
  // PR writes (Apply/Discuss requests from the user; the deck-review advisory from
  // the assistant).  Strict match, role-bound; any other content renders verbatim.
  // Render-only: what was sent and stored is unchanged.
  const split = isUser
    ? splitFindingRequest(message.content)
    : message.role === 'assistant'
      ? splitDeckAdvisory(message.content)
      : null;
  // Full-opacity foreground on the primary bubble: white on primary is 5.2:1;
  // /80 would be 3.9:1, below AA at this size.
  const detailsTone = isUser ? 'text-primary-foreground' : 'text-muted-foreground';
  ...
        <div className="whitespace-pre-wrap">
          {split ? split.lead : message.content}
        </div>
        {split && (
          <details className={`mt-2 text-xs ${detailsTone}`} data-testid="message-reviewer-details">
            <summary className="cursor-pointer select-none underline-offset-2 hover:underline">
              Reviewer's details
            </summary>
            <div className="mt-1 whitespace-pre-wrap break-words">{split.details}</div>
          </details>
        )}
```

- [ ] **Step 1 (test author):**
  - **`findingText.test.ts`, additions.**
    - **Round trips.** `splitFindingRequest(applyFindingRequest(f))` strictly equals `{ lead: \`Please fix this on slide 3: ${I}\`, details: TECH }`. The same holds for `discussFindingRequest`.
    - **The deck sample.** Build it from the TS constants exactly as `nodes._advisory_text` writes it: `` `${PREFIX}2 things${SUFFIX}\n- A.\n- B.\n${CLOSING}${SEP}- m1\n- m2` ``. `splitDeckAdvisory` returns `{ lead: <everything before SEP>, details: "- m1\n- m2" }`.
    - **`splitFindingRequest` returns `null` for:**
      - plain text with no separator
      - a valid lead plus the separator plus `'   '`
      - `"Hello\n\nReviewer's details:\nx"` (no lead)
      - a lead containing a newline
      - `on slide 0:`
      - the legacy `Please apply this review suggestion for slide 2: …`
      - a deck-advisory-shaped string
    - **`splitDeckAdvisory` returns `null` for:**
      - the no-findings sentence
      - the legacy `Deck review found 2 narrative issues:\n- arc_gap: …`
      - a sample with the closing line altered
      - a sample with `0 things`
      - a sample with no bullet lines
      - an Apply-shaped string
    - **Sabotage.** If both parsers always return `null`, the round trips and the bubble tests go red.
  - **`Message.findingRequest.test.tsx` (new).** Render `<Message message={{ role, content, timestamp: '' }} />`.
    1. **User Apply shape.** The lead is visible as text. The one `message-reviewer-details` element has `open === false`. The details body is `not.toBeVisible()`. After `fireEvent.click(summary)`, or setting `open = true`, its `textContent === TECH` exactly and it is visible.
    2. **User Discuss shape.** The same as test 1.
    3. **Assistant deck-advisory shape.** The plain block is visible, the details are collapsed, and their `textContent` is `"- m1\n- m2"`.
    4. **Apply shape with role `assistant`.** The content renders verbatim, with no `message-reviewer-details`. The role is part of the match.
    5. **Deck-advisory shape with role `user`.** Verbatim, with no disclosure.
    6. **An ordinary user message** containing `Reviewer's details:` mid-text renders verbatim, with no disclosure.
    7. **Legacy rows** (the old Apply bubble and the old slug advisory) and **the no-findings advisory** render verbatim, with no disclosure (D6).
    8. **User-bubble contrast.** The `<details>` className contains `text-primary-foreground` with no `/` opacity modifier on that token. This is a deliberate shape pin for contrast (D14).
    9. **The HTML branch is unaffected.** An assistant message containing `<!DOCTYPE html` still renders through `renderCollapsibleContent` (label `AI Assistant (HTML)`).
  - **`findings-drawer.spec.ts`, additions.** Import `mockSessionDetail` from `'../helpers/session-helpers'`, and `applyFindingRequest` plus the deck constants from `'../../src/utils/findingText'`. Scope assertions to `page.getByTestId('chat-panel')`.
    - **"Apply shows the plain lead in the chat bubble with the reviewer's details collapsed".**
      - Click `finding-apply-f2`.
      - The chat panel shows the text `` `Please fix this on slide 2: ${f2.plainIssue}` ``, and `chat.getByText(f2.message)` is not visible.
      - `chat.getByTestId('message-reviewer-details')` has count 1. After clicking its summary, `f2.message` is visible.
      - The captured `body.message` still contains `` `${REVIEWER_DETAILS_SEPARATOR}${f2.message}` ``, so the sent content is unchanged.
    - **"Discuss shows the plain lead in the chat bubble with the reviewer's details collapsed".** The same, with the Discuss lead.
    - **"persisted Apply-shaped and advisory-shaped messages reload collapsed".**
      - After `setupSession`, register a later route for `` apiPath(`/api/sessions/${TEST_SESSION_ID}`) `` (exact URL only; `route.fallback()` otherwise). It returns `{ ...mockSessionDetail, messages: [userRow, adviceRow] }`, where:
        - `userRow = { id: 1, role: 'user', content: applyFindingRequest(f2), message_type: 'user_query', created_at: '2026-10-19T10:00:00Z', metadata: null }`
        - `adviceRow` is an assistant `info` row whose content is built from the TS constants with one bullet and one details bullet
      - Open the deck. Both bubbles show their plain lead, two `message-reviewer-details` elements exist, and neither technical text is visible until its summary is clicked.
  - **`test_finding_conformance.py`.** Add `test_ts_deck_advisory_constants_match_python`, parametrised over `DECK_ADVISORY_HEADER_PREFIX`, `DECK_ADVISORY_HEADER_SUFFIX` and `DECK_ADVISORY_CLOSING`. For each, `_ts_string_constant(<findingText.ts>, name) == getattr(finding_copy, name)`. The helper fails loudly if a constant is missing.
  - **Confirm red.** Leave the tests uncommitted.
- [ ] **Step 2 (implementer):** add the constants and parsers to `findingText.ts`, and make the `Message.tsx` regular-branch change. Do not change `ChatPanel.tsx`, `MessageList.tsx`, `types/message.ts` or any backend file.
- [ ] **Step 3: verify.** Run each command separately.
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/utils/findingText.test.ts src/components/ChatPanel/
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx tsc -b
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx eslint src/components/ChatPanel/Message.tsx src/components/ChatPanel/Message.findingRequest.test.tsx src/utils/findingText.ts src/utils/findingText.test.ts tests/e2e/findings-drawer.spec.ts
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx playwright test tests/e2e/findings-drawer.spec.ts tests/e2e/chat-ui.spec.ts --project=chromium --workers=1
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316 && uv run pytest tests/unit/test_finding_conformance.py -q
  ```

---

### Task 8: Documentation

Models: test=sonnet impl=sonnet

There is no test file. The reviewer checks the prose against the merged code and runs the grep in Step 2.

**Files:**
- **`docs/technical/slide-viewer.md`.**
  - Replace the stale `SlideFinding` block (`:125-135`) with the current interface, including `criterion`, `objective`, `status`, `plainMessage` and `plainIssue`.
  - Replace the stale paragraph "Findings arrive as props … workstream 5 …" (`:147`) with the current flow: `get_slide_deck` → `_finding_to_camel` → `slideDeck.findings` → `AppLayout` → `SlideViewer`. Say that both plain keys are derived at read time by `src/domain/finding_copy.py`, from criterion, registry objectivity and status, and that they are never persisted and never `Finding` fields. Add one sentence on the digest rationale.
  - Add a "Plain message and details" subsection:
    - The drawer leads with `plainMessage`. "Show details", collapsed and not persisted, reveals the technical `message`.
    - Apply/Discuss send `<lead> <plainIssue>` + `REVIEWER_DETAILS_SEPARATOR` + `<message>`. The bubble collapses the details. The deck advisory uses the same separator.
    - Deck-level findings appear only in that advisory. Their detail also reaches the architect as `previous_deck_review`.
    - Add `frontend/src/utils/findingText.ts` to the Stack list and the component table.
  - Add an "Editing finding copy" how-to:
    - Edit `PLAIN_ISSUES`. A new `CRITERIA` entry needs a copy entry, or `test_finding_copy.py` goes red.
    - The deck-advisory strings and the separator have TS mirrors, pinned by `test_finding_conformance.py`. Editing one side alone fails that test.
    - Follow the style rules in D11.
- **`docs/technical/frontend-overview.md`.**
  - `:336` (`FeedbackDrawer` row): drop "(stubs until PRD workstream 5 ships)" and mention the plain message and the details toggle.
  - `:324` (`MessageList.tsx` & `Message.tsx` row): append "; collapses the reviewer's details section of finding requests and the deck-review advisory". #321 edits this same row, so expect a textual merge.
- **`docs/user-guide/01-generating-slides.md`.** Add `## Review Feedback` after "Navigating Slides". The second person is fine in the guide. It should say:
  - Each slide is checked as it lands.
  - The feedback drawer under the slide explains each point in plain words, and says whether it was fixed automatically, was not, or is a judgement call left to you.
  - **Show details** reveals the reviewer's technical note.
  - **Apply** asks the agents to fix it, **Dismiss** hides it, and **Discuss** moves it to chat. The technical note travels with the request but stays folded under "Reviewer's details" in the chat.
  - Deck-wide points (story gaps, repetition, a missing conclusion) appear as a chat message, with the reviewer's specifics folded underneath.

- [ ] **Step 1 (implementer):** write the changes above.
- [ ] **Step 2: verify.**
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316
  ! grep -n "workstream 5" docs/technical/slide-viewer.md docs/technical/frontend-overview.md
  grep -n "plainMessage" docs/technical/slide-viewer.md
  grep -n "plainIssue" docs/technical/slide-viewer.md
  grep -n "Show details" docs/user-guide/01-generating-slides.md
  grep -n "Reviewer's details" docs/technical/frontend-overview.md docs/user-guide/01-generating-slides.md
  ```

---

### Task 9: Whole-branch verification

Models: test=opus impl=opus

This is the controller plus the whole-branch Opus reviewer (skill §7). `test=` is the sabotage verifier.

- [ ] **Frozen-path guard (D12).** Both commands must print nothing. The second catches untracked files (review #19).
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316
  FROZEN="src/domain/finding.py src/domain/skill_io.py src/core/skills src/services/agent_definition_manifest_v1.py src/services/agent_schema_registry.py src/services/prompt_assembler.py src/services/agent_model_payload.py tests/fixtures/model_payload_keys.py frontend/tests/fixtures/graphLifecycleContract.json evals src/api/fixtures/tour_demo_deck.json"
  git diff --name-only origin/main -- $FROZEN
  git status --porcelain --untracked-files=all -- $FROZEN
  ```
- [ ] **Unit suite.** `uv run pytest tests/unit -n 4 -q`. The failing-cause set must equal the clean baseline. The only pre-existing tests intentionally edited are:
  - `test_finding_conformance.py`: allowlist, round trip
  - `test_deck_read_path_keys.py`: `_SLIDE_FINDING_KEYS`
  - `test_graph_nodes.py::TestDeckReviewerReview::test_persists_the_review_against_the_deck_digest_and_surfaces_info`: the slug assertion
- [ ] **Integration.** `uv run pytest tests/integration/test_graph_orchestration.py tests/integration/test_architect_reply_is_persisted.py -q`.
- [ ] **Frontend (review #4).** Run each as its **own** command, so a lint failure can never skip vitest:
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx tsc -b
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && NODE_OPTIONS=--no-experimental-webstorage npx vitest run
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx eslint $(cd .. && git diff --name-only origin/main -- frontend | sed 's#^frontend/##' | grep -E '\.(ts|tsx)$') $(cd .. && git ls-files --others --exclude-standard -- frontend | sed 's#^frontend/##' | grep -E '\.(ts|tsx)$')
  ```
  ```bash
  cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-316/frontend && npx playwright test tests/e2e/findings-drawer.spec.ts tests/e2e/slide-viewer.spec.ts tests/e2e/spec-view.spec.ts tests/e2e/app-tour.spec.ts tests/e2e/chat-ui.spec.ts --project=chromium --workers=1
  ```
  The lint rule is: on the touched files, only the 4 pre-existing `AppLayout.tsx` errors (same rule ids and messages) and its 2 warnings. Nothing new.
- [ ] **Sabotage-verify** every reviewer-approved test from Tasks 1 and 3–7, and re-run Task 2's two sabotages. Temporarily revert each production change, confirm red, then restore. At minimum:
  - return `message` from `plain_finding_message`
  - delete either `camel[...]` line
  - render `f.message` in `finding-plain-*`
  - revert the AppLayout handlers
  - restore the slug advisory line
  - make both parsers return `null`
  - add `/80` to the user-bubble tone

  After the pass, `git diff --exit-code` must hold for every production file against the pre-sabotage state.
- [ ] **Whole-branch review (Opus).**
  - Check every Inventory B row against the diff.
  - Confirm SSE/poll parity, and that `info` rows are not replayed (`_conversation`, `_hydrate_chat_history`).
  - Confirm sent and stored content is byte-identical with or without the `Message.tsx` parse.
  - Run the multi-worker checklist from `tellr-code-review`: no new in-process state.
  - Return a merge or no-merge verdict.
- [ ] **No live evals** ($0). Do not commit; hand back to the supervisor.

---

## CI wiring

- **Path filters.** `.github/workflows/test.yml` is path-filtered. `src/**` and `tests/**` trigger the backend unit and integration jobs. `frontend/**` triggers `frontend-build` (`npx tsc -b`, `vite build`), `frontend-unit-tests` (`npm run test:unit`, which picks up the new `src/utils/findingText.test.ts` and `Message.findingRequest.test.tsx` automatically) and the e2e matrix. **CI runs no lint.** The lint rule above is a local review gate.
- **No new Playwright spec.** Tasks 3, 5 and 7 extend `findings-drawer.spec.ts`, and Task 3 touches typed literals in `spec-view.spec.ts`. `findings-drawer`, `spec-view`, `slide-viewer`, `app-tour` and `chat-ui` are already in `e2e-tests.strategy.matrix.test` (`test.yml:696-732`), so `tests/unit/test_e2e_matrix_covers_specs.py` is unaffected.
- **Existing Playwright assertions on finding text.** Only `findings-drawer.spec.ts:201` (`expect(body.message).toContain('35%')`) asserts on finding text. It is kept, because the reviewer's details still carry f2's message. `slide-viewer.spec.ts` and `app-tour.spec.ts` assert on test ids and the `Fixed` badge only.
- **Typed literals (review #11).**
  - Typed `SlideFinding` literals under `tests/**` are type-checked by `tsc -b` through `tsconfig.e2e.json`. Those seven are updated in Task 3.
  - The typed `SlideFinding` literals in vitest files (`SlideViewer.test.tsx:64`, `FindingsE2.test.tsx:79` and `:178`, `TourViewerBridge.test.tsx:48`) are **typed but excluded from `tsc -b`** (`tsconfig.app.json:33`), and vitest does not type-check. They need no change; at runtime they render the fallback.

## Docs to update

- Task 8 updates `docs/technical/slide-viewer.md`, `docs/technical/frontend-overview.md` (two rows) and `docs/user-guide/01-generating-slides.md`.
- `docs/technical/feedback-system.md` is about the user-feedback survey widget, not review findings, so it is not touched.
- No technical doc describes the reviewers or `_advisory_text` (grep, 2026-10-19).

## Out of scope

- **#321**: failure, placeholder and stall notices, the deck-reviewer failure advisories (Inventory S14), `_surface_notice`'s signature, and `metadata.details`.
- **Follow-up to file:** migrate this PR's two content shapes (Apply/Discuss requests and the deck advisory) onto #321's `metadata.details` and its `Message` disclosure, after #321 merges. Then drop the content-shape parser.
- **#319**: per-slide stage lines and the chat stage placeholder (S12).
- **#323** (clear chat), **#318** (spec Markdown export), **#313** (architect intent evals).
- Reviewer prompts, output schemas, the v1 manifest, promote, evals and the frontend lifecycle contract (D1, D12).
- Naming the specific element in the plain line, by model rewrite or by extraction from `message` (D1).
- Collapsing **legacy** chat rows (S22, D6). Only the shapes this PR writes are parsed.
- An agent-only hidden context for Apply/Discuss (D4).
- A status-aware frontend fallback for version skew (review #22, optional). Declined: the state is transient, and a fixed finding there shows the generic line beside its "Fixed" badge.
- Also out of scope:
  - the LLM-as-judge verification badge (S11)
  - the admin test-run panel (S18)
  - exports (S16)
  - the architect's own prose (S19)
  - the Help page and WelcomeModal (a separate follow-up, per the tour plan)

## Risks

1. **Digest fallout.** None by construction: `Finding`, the skills, the manifest and the payload key sets are untouched. Pinned by:
   - `AgentSchemaRegistry()`, which fails closed
   - `test_schema_contract_digests_unchanged`
   - `test_copy_is_not_rendered_into_any_prompt`
   - `test_projection_only_fields_are_declared_in_ts_and_absent_from_finding`
   - the Task 9 frozen-path guard, which covers tracked and untracked files
2. **The conformance allowlist could become a bypass.** Mitigated by the absent-from-`Finding` guard and the exact `_finding_to_camel` equality test.
3. **Parser drift between Python and TS.** The separator and the three deck strings are pinned equal by quote-capturing, fail-loud tests. Task 7's vitest builds its sample exactly as `_advisory_text` composes it, so a change to the Python composition (for example the bullet prefix) is caught there only if the test author mirrors it. Review focus 5 covers this.
4. **Parser false positives.** A user could type an exact Apply-shaped message by hand. It would render collapsed, and it is still sent verbatim. This is harmless.
5. **A reviewer message containing HTML.** If a deck reviewer message embeds `<div class="slide">`, `Message.tsx`'s HTML branch takes the whole advisory first (existing behaviour, `:69-90`) and the plain lead is not shown. This is unlikely, and accepted.
6. **Multi-worker state.** There is none. Both the derivation and the parse are pure.
7. **Both transports.** Findings arrive only through `get_slide_deck` on both. The advisory is one string, and Task 6 pins the real poll leg.
8. **Tour.** The real path is pinned in Task 3. The app-tour e2e mock lacks the plain keys and shows the fallback, which is harmless because it asserts visibility only. The fixture and step copy are untouched, and the no-findings advisory is byte-identical.
9. **Product risk: less specific drawer lines.** The element name moves under "Show details". Two findings of the same criterion on one slide read the same. Accepted (D1).
10. **MCP clients now read the details section in plain text** (S17). They keep the actionable references, which is the intended outcome.
11. **Version skew.** A cached old frontend ignores the plain keys, and posts and renders as today. A new frontend on an old payload shows the fallback.
12. **Merge conflicts.** Each is a textual merge in a different region:
    - `nodes.py`: #321 edits notice functions; this plan edits `_advisory_text` and one import.
    - `AppLayout.tsx`: #323 edits one prop; this plan edits two handlers and one import.
    - `Message.tsx`: #321 adds a `message-details` `<details>` in the same regular branch.
    - `frontend-overview.md:324`: both PRs edit this row.

    Whichever PR lands second rebases.

## Claims recorded for the pre-pass (re-probe before Task 1)

- `Dict` is imported in `src/services/graph/nodes.py` (`:52`). Verified 2026-10-19.
- `ViewerProvider` defaults to an open drawer (`DEFAULT_VIEW_STATE.drawerOpen = true`, `frontend/src/contexts/ViewerContext.tsx:17-18`). Verified 2026-10-19.
- `get_messages_for_request` (`session_manager.py:3332`) filters only on `SessionMessage.request_id`, so a unit test can read rows stamped under `set_chat_request_id("req-316")` without a `ChatRequest` row. `msg_to_stream_event` (`:3370`) maps an `info` row to `type: "assistant"` with its `content`. Verified by reading 2026-10-19; not executed.
- `architect_node`'s next-turn digest equals the deck reviewer's stored digest for the same seeded HTML. Task 2's architect test assumes this; it has not been executed.
- jsdom and jest-dom treat the body of a closed `<details>` as not visible. #321's plan relies on the same behaviour; it has not been executed here.
- `test_retained_bundle_ledger` does not exist. The schema ledger names are `_V1_DIGESTS`/`_V2_DIGESTS`/`_HISTORICAL_DIGESTS` (`agent_schema_registry.py`). `_V2_DIGEST`/`_HISTORICAL_V2_DIGESTS` are the prompt-assembly identity (`prompt_assembler.py:398-411`).

## Revision log

Revised 2026-10-19 against `/Users/robert.whiffin/tellr-loop/issues/issue-316/PLAN-REVIEW.md` (0 blockers, 4 major, 19 minor) and the supervisor's rulings R2–R7.

- **R2 / review #1 and the 9a recommendation.**
  - Added **Task 7**: a frontend-only, strict, role-bound collapse of the "Reviewer's details" section in `Message.tsx`, using a native `<details>`.
  - It comes with shared constants and pure parsers in `frontend/src/utils/findingText.ts` (`withReviewerDetails` uses `REVIEWER_DETAILS_SEPARATOR`), the new `Message.findingRequest.test.tsx`, and e2e tests for Apply, Discuss and reload. It is tagged test=opus impl=sonnet and sequenced after AppLayout.
  - Contrast is computed and pinned: full `text-primary-foreground` is 5.2:1; `/80` is not used.
  - The separator is `"\n\nReviewer's details:\n"`, ending in a newline, so the same section reads cleanly for a one-paragraph request and for a bulleted advisory.
  - `findingText.ts` moved from `SlideViewer/` to `utils/` because three components import it.
- **R3 / review #2.** Added the second projection-only key `plainIssue` and the helper `plain_finding_issue`. Apply and Discuss leads use it, with a fallback; the drawer keeps `plainMessage`. Updated `PROJECTION_ONLY_FIELDS`, the TS type, `_SLIDE_FINDING_KEYS`, the exact-equality test, all seven literals and the e2e expectations.
- **R4 / review #3: the hybrid advisory.**
  - The content is plain lines, then a closing line, then the same separator section with every deck-reviewer message verbatim. Task 7 collapses it for the assistant role.
  - `_surface_notice` and `metadata.details` are untouched, since those are #321's.
  - The Python and TS strings are pinned equal by a quote-capturing, fail-loud regex (review #22).
  - The no-findings sentence is byte-identical.
  - The plan records that `info` rows are excluded from both replay paths, and that MCP `get_deck_status` now carries plain lines plus details (S17).
  - A follow-up to migrate onto #321's `metadata.details` is listed.
  - D5 was rewritten, and the "no disclosure widget" claim corrected (review #18).
  - The parity test now exercises the real poll leg and asserts the details verbatim and the `deck_reviews` contents (review #12).
- **R5 / review #4.** Recorded the lint baseline as a cause-set (63 errors and 9 warnings; AppLayout's 4 errors at `:64`, `:100`, `:742`, `:1073`). Lint runs only on touched files, as separate commands with no `&&` chains, under a "no new errors" rule. Pre-existing AppLayout lint is never fixed. Task 9's chain no longer skips vitest.
- **R6 / review #5 to #23, as written.**
  - **#5:** `DECK_GRAIN_ISSUE` for non-deck criteria, and a test that "this slide" never appears.
  - **#6:** `(noted N times)`.
  - **#7:** the new closing line.
  - **#8:** Task 3's false confirm-red claim removed.
  - **#9:** Task 5's drawer e2e noted as already green.
  - **#10:** seven literals.
  - **#11:** "typed but excluded from `tsc -b`".
  - **#12:** real poll leg.
  - **#13:** fixed-status read-path test.
  - **#14:** Task 6 imports named.
  - **#15:** `renderDrawer` callbacks parameter.
  - **#16:** D6 and the Goal scoped to the drawer; old chat rows stay as stored (S22).
  - **#17:** S17 marked as a changed surface.
  - **#19:** untracked-file guard.
  - **#20:** Task 2 ends with `git diff --exit-code -- src/services/graph/nodes.py`; Task 5 raised to test=opus.
  - **#21:** a fixture-literal conformance test tying `plainMessage`/`plainIssue` to the Python copy.
  - **#22:** fail-loud, quote-capturing constant pins. The optional status-aware fallback was declined (Out of scope).
  - **#23:** D1(a) reworded to acknowledge `_HISTORICAL_DIGESTS` as the sanctioned additive route, while still choosing (c).
- **R7 (wording style, which corrects the earlier brief).**
  - The second-person ban was removed from D11 and from Task 1's banned-pattern list, matching #321's D1 (second person, 1-based numbers). Every other ban stays.
  - The judgement-call sentence became "This is a judgement call, so it was left for you to decide.", and the closing line became "None of these were changed automatically. Reply here if you'd like any of them addressed."
  - Per-criterion issue sentences are unchanged.
  - The affected literals and examples were recomputed. The longest `plainMessage` is now 122 characters.
- **Task count is now 9:** a new Task 7 (chat collapse), with Docs and Verification moved to Tasks 8 and 9.
