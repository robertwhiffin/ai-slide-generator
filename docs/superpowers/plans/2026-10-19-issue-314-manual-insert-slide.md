# Manual "insert blank slide", Google-Slides style, and a new-slide indicator (#314 follow-up) — Implementation Plan

**Date:** 2026-10-21. Revised the same day after the independent plan review.
**Branch:** `feat/314-agent-add-slide` (PR #337, base `main`). Worktree `.claude/worktrees/issue-314`;
push to the same branch, no new PR. Facts were re-anchored at tree **3caf1ebf** (after the #333/#319
merge).
**Request** (the user, reviewing #337 on its devloop instance): "we need a UI indicator too. I want to
be able to manually insert a blank slide in the same way that I can in Google [Slides]. This needs to
play into the Deck spec as well."
**Spec:** none. The Decisions section holds the rulings; they are provisional and the user may
overrule any of them.
**Before Task 1:** load `executing-plans-tellr` with `superpowers:subagent-driven-development` and run
the plan-vs-code corrections pre-pass (§2). Every task has a `Models:` tag (§9). Corrections go in
`~/tellr-loop/issues/issue-314-ui/PLAN-CORRECTIONS.md` and override this file.

---

## Review table

Review: `~/tellr-loop/issues/issue-314-ui/PLAN-REVIEW.md` (1 blocker, 2 major, 13 minor, 6 nit).
Rulings are the supervisor's.

| # | Ruling | Where it landed |
|---|---|---|
| B1 | ACCEPT. The blank is a **deck-derived blank shell**, built by `blank_slide_shell`. The blank-row predicate is now structural. A shared JSON case table is read by both pytest and vitest. Three Task 1 fixtures plus an export smoke test. The AC2 e2e compares root backgrounds on a section-wrapper deck and on an inline-styled deck. A design-contract change leaving a blank's old classes is a residual. Task 1 is retagged impl=opus. | D1, D4, D5; Tasks 1, 3, 4, 7, 9; Risks |
| M1 | ACCEPT. The Markdown export prints "Blank slide." for a blank entry. The coverage guard gains a BLANK fixture and a `MUST_SEE` entry; the golden bytes are unchanged. | D11; Task 7 |
| M2 | ACCEPT. The insert transaction refuses while any OTHER session of the deck holds a live (< 300 s) processing lock. This is `DeckBusyError` → 409. | D7; Tasks 2, 3; Risks |
| m1 | ACCEPT. A blank the user named but the model left undescribed gets a notice and a WARNING. | D5; Task 4 |
| m2 | ACCEPT. The re-review makes no call for a blank entry, and `judged_nothing` ignores blanks. | D5; Task 4 |
| m3 | RESIDUAL. A `build` answer replaces the deck by request (#337 already documents this). No test. | D5; Risks |
| m4 | ACCEPT. N2(a) applies to every deck (the supervisor accepts this); it returns `prior_spec.model_copy(deep=True)`. Describe-only integration tests are listed for the CI check. | D5; Task 4 |
| m5 | ACCEPT. Tests assert `target_positions` and emit metadata, never notice prose. The import goes under `from src.domain.deck_spec import`. One-line call sites into helpers. | Task 4 |
| m6 | ACCEPT. The manual insert selects the slide it inserted, using the response. ChatPanel's `error` case refetches the deck. | Tasks 3, 6, 8 (ChatPanel is in **Task 8**) |
| m7 | ACCEPT. A polling-shaped sequence is added to the indicator test. | Task 8 |
| m8 | ACCEPT. The insert route's lock-held 409 uses `CONVERSATION_BUSY_DETAIL`. | Task 3 |
| m9 | ACCEPT, condition verified. The blank path skips `mark_dirty`; an html insert still marks. `test_spec_sync_placement.py` is a static AST presence check (`_route_table`, `:209-241`), and the integration inserts all post `html`. Both stay unedited. | D6; Task 3 |
| m10 | ACCEPT. The D13 display-name exception is stated in AC4 and the docs; there is no blob materialisation. | AC4; D13; Task 10 |
| m11 | ACCEPT. All the listed tests are added. | Tasks 2, 3, 4 |
| m12 | ACCEPT. The ribbon gaps are hidden while a drag is active. `slide-viewer`, `viewer-readonly` and `spec-view` join Task 9's local run. | Tasks 6, 9 |
| m13 | ACCEPT. A sentence on the monolith engine in D5 and in the docs. | D5; Task 10 |
| n1 | ACCEPT. Facts re-anchored at 3caf1ebf. | Facts |
| n2 | ACCEPT. Each stale comment is fixed in the task that touches its file; docs in Task 10. | Tasks 1, 3, 4, 10 |
| n3 | ACCEPT. `import copy` added. `{}` stays untouched; `{"slides": []}` gains the entry, as today. Both are tested. | D3; Tasks 1, 3 |
| n4 | REJECTED. The lazy import of `_refuse_during_an_arc_review` stays, following the precedent that `chat_service` lazily imports `deck_level_writer` (`chat_service.py:4127-4132`). | D2 |
| n5 | ACCEPT. One effect with deps `[slideDeck, deckKey]` resets the baseline before diffing. | Task 8 |
| n6 | ACCEPT. The keyboard path is documented. The indicator also runs for read-only viewers (kept). | D9, D10; Task 10 |

---

## Goal

An editor inserts a blank slide anywhere from the slide viewer, as in Google Slides ("New slide" after
the current one, or a "+" between thumbnails). The blank is a structural copy of the deck's own slide
frame (wrapper, class tokens, inline ground; no content), so it looks like a blank slide of THIS deck.
The spec gains a blank `SlideSpec` in the same transaction as the rows, and every existing slide keeps
its identity, attribution, verdicts, findings and fragment. The architect fills the blank in place when
asked and no turn silently rebuilds, re-describes or drops it. Whenever slides appear (manual insert,
agent insert over SSE or polling, duplicate), the new slide is selected, scrolled into view and marked
"New" for a few seconds.

## Acceptance criteria

| # | Criterion | Met by | Tested by |
|---|---|---|---|
| AC1 | An editor inserts a blank slide after the current one (stage toolbar "New slide") or at any ribbon gap: before the first, between two, after the last. | D9; Task 6 | Task 6 vitest; Task 9 |
| AC2 | The blank is `blank_slide_shell(deck slides, position)`: the deck's most common root→`.slide` chain, keeping only class, data-label and style, with no content. On a section-wrapper deck, a `.slide`-ground deck and an inline-styled deck it paints the same ground as its neighbours. It falls back to the bare `<div class="slide"></div>` when nothing qualifies, and it always passes `has_slide_wrapper` and `scan_html_for_unsafe_patterns`. | D1; Tasks 1, 3 | Task 1 (three fixtures plus an export smoke test); Task 9 (the blank root's computed background equals a neighbour's) |
| AC3 | The spec gains a blank entry (empty purpose and brief) at the landed position; later entries and rows shift; rows and spec are written in ONE transaction. The Spec view shows "Blank slide". The Markdown export prints "Blank slide." for that entry. The coverage guard checks this with a BLANK fixture, and the golden bytes are unchanged. | D2, D3, D11; Tasks 1, 2, 7 | Task 2 (atomicity); Task 7; Task 9 |
| AC4 | Every existing slide keeps its slide_id, html, scripts, raw `created_by`/`modified_by` (never SCIM display names), timestamps (NULL stays NULL), verification record and spec fragment, and its findings show on it. *Exception (D13):* a row-less legacy deck materialises its rows from the cached deck, which carries display names, exactly as today. | D2, D13 | Task 2 (by-marker whole rows, findings); Task 3 (display names); Task 5 |
| AC5 | Editors only. Viewers (`/view`), save-point previews and non-lock-holders see no affordance. The route stays CAN_EDIT (403) and editing-lock gated (423). | D9 | Task 6; Task 9; `test_authz_slides_insert.py` |
| AC6 | Refused with 409 `CONVERSATION_BUSY_DETAIL`, and nothing changed, when: this session's lock is held; a turn runs on ANY other session of the deck (lock < 300 s old); or an arc review holds a live claim. Also refused with 409 when the rows changed under the insert and when `expected_version` is stale. The UI shows the server's text and refetches. | D7; Tasks 2, 3, 6 | Tasks 2, 3, 6, 9 |
| AC7 | Attributable: the new slide's `created_by`; exactly one `insert_slide` mutation event naming it; one `slide_inserted` usage event; exactly one save point; one version bump. | D8 | Tasks 2, 3 |
| AC8 | The architect's payload shows the blank entry and counts its row. An edit that revises it builds only that position, in place, keeping the same `slide_id`. | D5 | Task 5 |
| AC9 | No turn rebuilds an untouched blank, and none re-reviews it either (no judge call): this covers equal-length targets, the design-contract rebuild-all and the deck-level re-review. A blank the user named but the model left undescribed gets a notice. An arc-review turn neither drops a slide nor invents a description for a slide that is still blank. | D5, D6 | Tasks 4, 5 |
| AC10 | After any refetch that only adds slides, a new slide is selected and scrolled into view: the inserted one for a manual insert, otherwise the first new one. Each new thumbnail carries a "New" chip for 5 s. Mid-turn slides (synthetic `build-N` ids) are never flagged. This holds on SSE and on polling. An errored turn refetches the deck. | D10; Task 8 | Task 8 (SSE and polling shapes, the error case); Task 9 |
| AC11 | Multi-worker coherent: no new in-process cross-request state. A stale cache can only produce a 409, never a write-back. | D2, D12 | Task 3 |
| AC12 | A blank insert schedules no arc review (its spec entry is already exact). An insert that carries HTML still does. | D6; Task 3 | Task 3 route test |
| AC13 | CI: the new Playwright spec is in the e2e matrix; docs are updated. | Tasks 9, 10 | `test_e2e_matrix_covers_specs.py` |

---

## Facts verified (grepped at 3caf1ebf)

**Insert route and service**
- `src/api/routes/slides.py` insert route `:157-231`: CAN_EDIT `:178`; 423 `:183`; lock-held 409 with
  the old text "Session is currently processing…" `:187-195`; comment "schedules the description of
  it" `:211-213`; `mark_dirty` `:214`; error mapping `:216-226` (else 500).
- `src/api/services/chat_service.py`: no `copy` import (`:10-17`); `BLANK_SLIDE_HTML` `:73`;
  `_BLANK_DECK_SPEC_ENTRY` `:79-85` ("the arc-review sweeper writes the prose"); `ArcReviewInFlightError`
  `:321`; `_refuse_during_an_arc_review(db, session)` `:334-362` (FOR UPDATE on `session.id`'s deck);
  `delete_message`'s in-transaction `UsageEvent` `:2441`; `_get_or_load_deck` `:3022`;
  `_reindex_slide_ids` `:3114`; `_invalidate_deck_cache` `:3161`; `create_save_point` `:3228`;
  `insert_slide` `:3936-4060` (mutates the CACHED deck, reindexes, `save_slide_deck`, then the spec in
  a SECOND transaction: two bumps); `_rewrite_deck_spec_slides` `:4062-4199` (raw dict; "four routes"
  `:4085-4090`; lazy `deck_level_writer` import `:4127-4132`; `isinstance(slides, list)` `:4140`);
  `_insert_deck_spec_slide` `:4201-4226`.
- `src/api/routes/sessions.py:57-60` `CONVERSATION_BUSY_DETAIL`, also its lock 409s (`:907`, `:986`);
  it imports no `slides.py`.

**Row writer** (`src/api/services/session_manager.py`)
- `_attribution_from` `:373`, `_attribute_slide_records` `:385`, `_upsert_slide_row` `:498`
  (`… or now_dt`, `… or author_fallback` `:566-570`), `_prune_slide_rows_beyond` `:645`,
  `_rewrite_slide_rows` `:680-749` (the only caller of both); `VersionConflictError` `:808`.
- `duplicate_session` `:1285` copies `deck_json`/`html_content`/`slide_count`/`deck_spec_json`, no rows
  (`:1350-1357`); `save_slide_deck` `:1673` (row write `:1799`, `attribution=None`; evidence via the
  module-level `record_shared_deck_mutation`); `get_slide_deck` `:1894` (raw `slide_id`, then
  `_resolve_deck_display_names` `:2041`; blob path `:2127`; the function `:2160`).
- `EDITING_LOCK_TIMEOUT_SECONDS = 45` `:3104`; `acquire_session_lock(session_id, timeout_seconds=300)`
  `:3240-3288` locks only the requesting row; > 300 s or no start time is stale (`:3274-3279`);
  `deck_mutation_context` `:3660`. `UserSession.parent_session_id` (FK `user_sessions.id`),
  `is_processing`, `processing_started_at`: `src/database/models/session.py:166,204-205`.
- `src/api/services/slide_repository.py`: `SlideRowsChangedError` `:126` (imported by `nodes.py:59` and
  tests); `insert_pending_slides` `:442-636`, steps 2-4 `:566-614`; `_snapshot_row` `:642`.

**Why `attribution=None` is not exact for an insert.**
- Pass 1 matches by `slide_id`, so the heuristic is exact only when every old row has a unique
  non-null `slide_id`.
- Id-less rows that share HTML get paired in order by hash, so a blank inserted before an id-less
  twin takes the twin's record and fragment.
- The UI's round trip through `get_slide_deck` makes `save_slide_deck` write SCIM display names into
  every row and turn NULL timestamps into `now`.

**Where a deck's ground lives (B1)**
- The real uploaded DS paints the ground on a `<section>` wrapper; `.slide` is a transparent absolute
  child (`slideDocument.ts:72-80`, `:101-103`, `:168-174`; faithful fixture
  `tests/fixtures/export_slide_root/wrapped_bare_slide.html`). The builder paints with class tokens
  (`.slide.dark/.white/.event`) or, unpinned, inline `background:`/`color:` (`builder.py:92-100`);
  unpinned graph decks have no deck CSS (`_resolve_brand` `nodes.py:883`; `aggregate_deck_css`
  `:3737`). The ribbon iframe itself is `#ffffff` (`ThumbnailRibbon.tsx:121`).
- Meridian (`evals/fixtures/meridian/bundle/templates/standard/index.html:6-21`) grounds `.slide`; its
  gold slides are `<section class="slide">` roots (`evals/fixtures/meridian/gold/*.html`), which
  `has_slide_wrapper` (`src/domain/slide.py:17-29`, `<div>` only) rejects, so a Meridian shell falls
  back to the bare div — which still paints there.
- Roots: `findSlideRoot` `slideDocument.ts:190-198` (first `.slide`, up to the body's child); Python
  `find_slide_roots` `src/utils/html_utils.py:46`; scanner `src/utils/html_safety.py:113`; export
  `build_slide_html(slide, slide_deck)` `src/api/routes/export.py:72`.

**Spec and arc review.** `SlideSpec` (`deck_spec.py:70-106`) has no `min_length`. `spec_sync.py`:
`CLAIM_TTL_SECONDS = 900` `:387`; `ARC_REVIEW_MESSAGE` `:391-397` ("Re-read the slides" — impossible,
no HTML in the payload); `review_in_flight` `:527`; `run_arc_review` `:598` (describe-only, no lock).
`test_spec_sync_placement.py` `_route_table` (`:209-241`) is a static AST check that a handler body
NAMES `mark_dirty` (plus the `get_current_user()` argument check); the integration inserts all post
`html` (`test_insert_slide_route.py:174-288`, `test_slide_id_is_durable.py:347,393,531`).

**Architect** (`src/services/graph/nodes.py`): `from src.domain.deck_spec import` `:67`;
`_REREVIEW_FAILING_CRITERIA` `:459`; `rereview_committed_slides` `:542` (placeholder branch `:660`);
`_surface_notice(session_id, message)` `:1199`; `_committed_slide_rows` `:1005`;
`_persisted_spec_describes_these_rows` `:1039` (stale docstring `:1051-1054`); `architect_node`
`:1524`; `describe_only` `:1637`; payload `:1650-1676`; edit guards `:1755-1832` (describe-only exempt,
so a describe-only spec with another position set IS persisted — `test_architect_insert_slide.py:1100`);
re-resolve `:1834`; bindings `:1846`; alignment `:1868-1890`; `inserting` `:1899`; insert targets
`:1921`; equal-length targets `:1958`; references `:1967`; shift `:2018`; `classify_spec_change`
`:2080`; design contract `:2096`; `rebuild` `:2141`; `judged_nothing` `:2151`; notice prose `:2177`;
emit `"rebuilding"` `:2198`, `"surfaced"` `:2203`; `deck_write` `:2262`.

**Locks and events.** SSE holds the session lock for the stream (`chat.py:549`→`:662`), polling until
the job ends (`chat.py:732`, `job_queue.py:213`); the root owner chats without the editing lock
(`chat.py:124-125`); MCP takes only the session lock (`mcp_server.py:214`). `usage_event.py:13-17`
(`String(30)`, no enum; no consumer filters new types); docs `usage-analytics.md:59,69-70`.

**Frontend.** `api.ts`: `ApiError` `:17`, `getSlides` `:753`, `deleteSlide` `:857`, no `insertSlide`;
polling synthesises `slide_ready` `:1127-1160`; production always polls `:36-48`. `SlideViewer.tsx`:
props `:33`, `refreshDeck` `:145`, `handleDeleteConfirm` `:263`, `<ThumbnailRibbon>` `:443`, toolbar
`:459-535`, empty state `:562`. `ThumbnailRibbon.tsx`: props `:33-37`, `Thumb` `:49-146`
(scroll-into-view `:67-71`), `<DndContext onDragEnd>` `:223-226`. `ViewerContext.tsx:81-86` clamps to
the current `slideCount`. `AppLayout.tsx`: `handleSlideReady` `:169-195` (`build-${position}` `:177`),
`isGenerating` `:213`, `effectiveReadOnly` `:806`, `onSlidesGenerated` `:1255`, `<SlideViewer
key={versionKey}>` `:1336-1357`. `ChatPanel.tsx`: `error` no refetch `:361-367`; `complete` refetch
`:369-396`; `slide_ready` `:430`. `useAutoVerification.ts:160-168`; `SpecView.tsx:236-258`;
`deckSpecMarkdown.ts` `NOT_SET` `:15`, slide loop `:90-101`; `deckSpecMarkdownCoverage.test.tsx` guard
(b) `:19-23`, `FIXTURES` `:374`, `MUST_SEE` `:377`. E2E: `agent-insert-slide.spec.ts`
(`setupInsertTurn` `:170`); matrix `test.yml:693-746`.

**Harnesses reused:** `test_insert_pending_slides.py` (+ `_postgres`), `test_insert_slide_service.py`
and `test_mutations_renumber_the_deck_spec.py` (`service` fixtures patch `session_manager` and
`deck_level_writer` `get_db_session`), `test_multiworker_cache_coherence.py`, `test_delete_message.py`
route section, `conftest_graph.py`, `test_architect_insert_slide.py` helpers,
`test_graph_insert_slide_turn.py`, `test_deck_level_spec_change.py:262`.

**CI-only integration tests that must stay green unchanged:** `test_shared_deck_mutation_attribution.py:600-698`
(one named insert event; an evidence failure patched at `session_manager.record_shared_deck_mutation`
rolls back; the id from `chat_service.uuid.uuid4`), `test_insert_slide_route.py`,
`test_slide_id_is_durable.py`, and the describe-only `test_sweeper_describe_only.py`,
`test_clear_context_graph_turn.py`, `test_delete_message_graph_turn.py`,
`test_architect_reply_is_persisted.py`.

---

## Decisions

**D1 — The blank is a deck-derived blank shell.** A bare `<div class="slide"></div>` paints only
where the ground is on `.slide` (Meridian). On the shipped design system the ground is on a
`<section>` wrapper; unpinned graph decks carry an inline ground and no deck CSS. In both cases the
bare div is a white box. So `ChatService.insert_slide`, when `html is None`, inserts
`blank_slide_shell([s.html for s in deck.slides], landed)`, computed from the deck being inserted
into, in the same flow as `expected_rows`.

The function (pure, `src/domain/deck_spec_slides.py`):
- **Chain.** For each slide it takes the chain from the fragment's top-level root down to the first
  element carrying the `slide` class token (`findSlideRoot` semantics).
- **Strip.** It keeps only `class`, `data-label` and `style` on the chain elements, with `style` kept
  as is, including `url()`: the value came from this deck, and a brand ground may be an image. Every
  other child and all text are removed.
- **Choose.** It picks the deck's most common chain signature (tags plus class tokens). On a tie it
  takes the signature of the nearest slide carrying one of the tied signatures, preferring the slide
  before the insertion point (at position 0, the slide after). The shell is built from that nearest
  slide's chain.
- **Check.** The result must pass `has_slide_wrapper` and `scan_html_for_unsafe_patterns(...) == []`,
  otherwise it is the bare `BLANK_SLIDE_HTML`. An empty deck, or one with no `.slide`, also gets the
  bare div.

A template section was rejected as the source: it carries sample content, there is no "blank"
section kind, and uploaded section HTML would need the scan.

*Residual:* a design-contract change leaves an untouched blank's old classes, because N1 skips it and
nothing re-derives the shell.

**D2 — One writer, one transaction, the exact map: NEW `SessionManager.insert_slide`.**
- It lives beside `_rewrite_slide_rows`. It shares a NEW `_splice_slide_rows` (steps 2-4 of
  `insert_pending_slides`, moved verbatim) with the graph's shift, so there is one shift primitive
  and one row writer (§7).
- Rows are re-read in the transaction and snapshotted raw. The check
  `[(slide_id, content_hash)] == expected_rows` turns a stale cache into a 409.
- *Why not `save_slide_deck`:* see the Facts above. Fixing it there would change every UI operation.
- *Why `session_manager.py`:* the fixtures and the integration evidence test patch this module's
  `get_db_session` and `record_shared_deck_mutation`.
- *n4 rejected:* `_refuse_during_an_arc_review` is imported lazily from `chat_service`, following the
  precedent of the lazy `deck_level_writer` import.

**D3 — The spec moves in the same transaction, with today's raw-dict semantics.**
- The pure core of `_rewrite_deck_spec_slides` (split, reorder, re-stamp 0..n, unpositioned entries
  last) is extracted. The existing method uses it, so delete, duplicate and reorder are unchanged;
  the insert transaction uses it too.
- An invalid-shape spec is renumbered, not destroyed.
- A NULL spec, unparseable JSON, a non-dict, `{}` and a dict without a `slides` list are left
  untouched, so legacy decks still insert.
- `{"slides": []}` gains the entry, as today. A drifted spec is spliced at the clamp.

**D4 — No schema marker.**
- **Blank entry** = `purpose` and `content_brief` empty after strip: the existing
  `_BLANK_DECK_SPEC_ENTRY`, which `SlideSpec` accepts.
- **Blank row** (structural `is_blank_slide_html`) = it has a slide wrapper, no non-whitespace text,
  and no element off the root→`.slide` chain. Each chain element has at most one element child, and
  the `.slide` element has none. Every shell is a blank row.
- The Python predicate and `frontend/src/services/blankSlide.ts` share one case table,
  `tests/fixtures/blank_slide_cases.json`.
- `DeckSpec`, `SlideSpec`, the TS types, conformance literals, `ArchitectOutput`, payload keys and
  prompts are all unchanged.

**D5 — The architect handles a blank by construction; deterministic guards close the silent paths.**
- **By construction.** The payload shows the blank entry, and `slide_numbering` counts its row. "Fill
  slide 4 with pricing" resolves to position 3 and is an equal-length edit revising entry 3. That
  edit is built in place, and the reviewed write keeps `slide_id`. No prompt change.
- **N1: an untouched blank is never dispatched or re-reviewed** on an edit turn (not describe-only).
  "Untouched" means blank in the final spec and neither inserted nor revised this turn: indices on an
  insert turn, `alignment.revised` otherwise.
  - The blank is removed from the equal-length targets, from the design-contract list and from the
    deck-level `rebuild` set (m5: metadata, not prose).
  - `rereview_committed_slides` makes no call for a blank entry: it is counted in `committed`, not in
    `reviewed` or `failing`, and gets a new `blank` set. `judged_nothing` ignores blanks (m2).
  - N1 is entry-based, so a blank someone has typed into is safe from a rebuild from an empty brief.
  - If a dropped blank is in this message's `slide_references`, the turn says so: `_surface_notice`
    plus WARNING `blank_named_but_not_described` (m1).
- **N2: a describe-only (arc-review) turn keeps what it cannot see**, when the persisted spec
  describes the rows.
  - (a) A re-description whose position set differs is not persisted: `prior_spec.model_copy(
    deep=True)` is kept, with WARNING `describe_spec_positions_changed`. This applies to every deck
    (m4).
  - (b) Where the row is still a blank row and the persisted entry is blank, the persisted entry
    replaces the model's.
  - The architect sees no HTML, so describing a blank is invention, and an invented brief would later
    fail re-review and rebuild the blank.
- **Residuals.**
  - A model that fills a blank during an UNRELATED edit builds it (optional Task 11 measures this).
  - A `build` answer replaces the whole deck by request, blanks included (m3; #337 documents build
    semantics).
  - An agent-inserted blank entry follows #337: a pending row, built from an empty brief.
  - A revision that blanks an entry is not handled.
- **Monolith sessions** (m13): there is no spec, so D3 leaves it alone and N1/N2 do not run. A blank
  is a slide the monolith may regenerate; fill it by selecting it and asking.

**D6 — The arc-review sweeper and the blank.**
- Checked: describe-only never rebuilds and produces no findings. It CAN invent a description and CAN
  drop the entry (N2 fixes both).
- **The blank path no longer calls `mark_dirty`** (m9): the spliced blank entry is already the exact
  description, N2(b) would discard any re-description, and it removes the 409 window the claim opens.
- An insert that carries HTML still marks. N2 stays, because another human edit can mark the deck.

**D7 — 409 sources; nothing is written on any of them.**
- (1) The route cannot take this session's lock → `CONVERSATION_BUSY_DETAIL` (m8; was "Session is
  currently processing…").
- (2) A live arc-review claim on the deck OWNER: `_refuse_during_an_arc_review(db, deck_owner)`.
- (3) **A turn on any other session of the deck** (M2): a `UserSession` with `id == deck_owner.id`
  or `parent_session_id == deck_owner.id`, other than the requester, with `is_processing` and
  `processing_started_at` within `SESSION_LOCK_TIMEOUT_SECONDS = 300`. The constant becomes
  `acquire_session_lock`'s default, so the two cannot drift. Raises `DeckBusyError` →
  `CONVERSATION_BUSY_DETAIL`.
- (4) Rows changed under the insert: `SlideRowsChangedError` → "The deck changed while the slide was
  being added. Refresh and try again."
- (5) A stale `expected_version` → `VersionConflictError`.
- The editing lock is NOT a turn guard: the owner chats without it, MCP never takes it, and it expires
  after 45 s. That is why (3) is needed. A turn longer than 300 s without a heartbeat stops blocking
  (Risks).

**D8 — Attribution.** The new slide's `created_by`/`modified_by` is `get_current_username()` (as
today) with explicit `created_at = modified_at = utcnow`. The transaction records exactly one
`insert_slide`/`deck` mutation event (`object_id` = the new id, minted in `chat_service` by
`uuid.uuid4()`), one `UsageEvent(EVENT_SLIDE_INSERTED = "slide_inserted", username=inserted_by,
session_id=<requesting session pk>)` when the route passes `get_current_user()`, one version bump, and
`deck.modified_by`. Then one save point ("Inserted slide N"); the response adds `inserted_slide_id` and
`inserted_position` (m6).

**D9 — Affordances.** Toolbar "New slide" (Plus + label, `stage-insert-slide`) inserts after the
current slide; the ribbon has a gap before every thumbnail and after the last (`ribbon-insert-${k}`,
k = 0..n, "+" on hover), hidden while a drag is active (m12). Both render only when `!readOnly &&
onSlideChange` and are disabled while a turn runs (`isGenerating`) or an insert is in flight. Keyboard
path (n6): the toolbar button; the gaps are `tabIndex={-1}`, so there is no keyboard "insert before
slide 1" (documented). Not built: context menu, Ctrl+M, layout picker, empty-deck affordance.

**D10 — The indicator diffs `slide_id`s against the last SERVER deck.** A pure helper: any synthetic
`build-N` id is a mid-turn view (no flag, baseline kept); no baseline (first mount, or a `deckKey`
change — reset in the SAME effect before diffing, n5) → the deck becomes the baseline; otherwise fresh
= ids not in the baseline, flagged only on pure growth; null/empty ids ignored. Selection: a pending id
(the slide a manual insert just created, from its response, m6) wins, else `fresh[0]` — both in the
effect after the new deck renders, because `setCurrentIndex` clamps to that render's count. Chips
(`ribbon-new-${index}`) and a ring last `NEW_SLIDE_INDICATOR_MS = 5000`, with an `sr-only` status line.
Both transports deliver mid-turn slides through `handleSlideReady` (synthetic ids) and end with the same
refetch; ChatPanel's `error` case now refetches too (m6), so a failed turn leaves no stale view. It runs
for manual inserts, agent inserts, duplicates and read-only viewers (n6, kept).

**D11 — Blank-aware frontend.** Auto-verification skips blank rows (structural predicate). SpecView
labels a blank entry "Blank slide" (`spec-slide-blank-${position}`). The Markdown export prints "Blank
slide." in place of that entry's two "Not set." lines (M1); coverage guard (b) gains a BLANK fixture
(GOLDEN with one entry's purpose and brief emptied) and `MUST_SEE` `'Blank slide'`; GOLDEN has no blank
entry, so the golden bytes are unchanged.

**D12 — The cached deck is never mutated before the write.** The post-insert deck is built on a
`copy.deepcopy`; the cache is invalidated on every exit and reloaded after commit, so a stale-rows 409
self-heals on the next try.

**D13 — Row-less legacy decks** (blob-path decks the backfill has not reached): the transaction writes
their rows from `deck_dict` through `_rewrite_slide_rows`, then splices the spec, as today's dual-write
does. Those rows carry the cached deck's display names — the AC4 exception (m10); no blob
materialisation.

**D14 — No prompt change.** The eval is optional (Task 11), measures the shipped prompt only, and a
failure becomes a follow-up plan.

**Known gaps (recorded, not fixed).** Update, duplicate, delete and reorder still use
`save_slide_deck`'s heuristic, write display names, fabricate NULL timestamps, renumber the spec in a
second best-effort transaction, ignore arc-review claims and other sessions' turns, and mutate the cache
before writing. Follow-up: move them onto D2.

---

## Global constraints

- **Environment** (per `~/tellr-loop/issues/issue-314-ui/DISPATCH-PREAMBLE.md`):
  - absolute paths and `uv run`; tests with `uv run pytest <paths> -n 4 -q`;
  - import `src.core.database` first in scripts;
  - no `pip`, no `git stash`, no commits (the supervisor commits with `Co-authored-by: Isaac
    <no-reply@databricks.com>`), no deploys;
  - no live model runs (Task 11's runs are SUPERVISOR-run).
- **Frontend:** `cd frontend && npx vitest run <files>` and `npm run build`.
  - Local Node 26 has no global `localStorage`: the baseline is 20 failures in `FindingsE2.test.tsx`,
    `SlideViewer.test.tsx` and `TourViewerBridge.test.tsx`. Do not touch those files.
  - New vitest files that render `SlideViewer` stub `localStorage` (`vi.stubGlobal`).
  - Vitest reads `tests/fixtures/*.json` through `fs.readFileSync` (no cross-root import).
- **Local Playwright:** only under `~/tellr-loop/bin/e2e-lock acquire issue-314` (release afterwards;
  stop only your own PIDs). Use system Chrome via `/tmp/issue314-e2e/pw.config.mjs`.
- **Do not edit:**
  - `DeckSpec`/`SlideSpec`, `frontend/src/types/slide.ts`, `deckSpecConformance.test.ts`,
    `ArchitectOutput`;
  - prompts, skills and the manifest; `slide_numbering.py`, `slide_alignment.py`;
  - `save_slide_deck`, `spec_sync.py`, `test_spec_sync_placement.py`;
  - the integration tests named in Facts;
  - `deckSpecMarkdown.ts`, `deckSpecMarkdown.test.ts` and `deckSpecMarkdownCoverage.test.tsx`,
    EXCEPT Task 7's two additions (M1).
- **One row writer (§7).** After Task 2, `grep -n "_attribute_slide_records(\|_prune_slide_rows_beyond("
  src/api/services/session_manager.py` shows each called only inside `_rewrite_slide_rows`.
- **Discipline.**
  - Tests come first and are confirmed red. Baselines are cause-sets: unit 10201 passed / 0 failed,
    frontend 20 environment failures.
  - Every approved test is sabotage-verified on the executed path.
  - Assert per slide by its marker, never by count or position alone.

## File map

| Area | Files |
|---|---|
| Domain helpers | `src/domain/deck_spec_slides.py` (new), `tests/unit/test_deck_spec_slides.py` (new), `tests/fixtures/blank_slide_cases.json` (new), `src/api/services/chat_service.py` |
| Writer | `src/api/services/session_manager.py`, `src/api/services/slide_repository.py`, `src/database/models/usage_event.py`, `tests/unit/test_manual_insert_writer.py` (new), `tests/unit/test_manual_insert_writer_postgres.py` (new, CI-only) |
| Service + route | `src/api/services/chat_service.py`, `src/api/routes/slides.py`, `tests/unit/test_manual_insert_service.py` (new), `tests/unit/test_manual_insert_route.py` (new) |
| Architect | `src/services/graph/nodes.py`, `tests/unit/test_architect_blank_slides.py` (new), one test in `tests/unit/test_architect_insert_slide.py` |
| Graph acceptance | `tests/unit/test_graph_blank_slide_turn.py` (new) |
| Affordance + indicator | `frontend/src/services/api.ts`, `frontend/src/components/SlideViewer/{SlideViewer,ThumbnailRibbon}.tsx`, `frontend/src/components/SlideViewer/newSlides.ts` (new), `frontend/src/components/Layout/AppLayout.tsx`, `frontend/src/components/ChatPanel/ChatPanel.tsx`, new vitest files |
| Blank-aware | `frontend/src/services/blankSlide.ts` (new), `frontend/src/hooks/useAutoVerification.ts`, `frontend/src/components/SpecView/SpecView.tsx`, `frontend/src/services/deckSpecMarkdown.ts`, `frontend/src/services/__tests__/deckSpecMarkdownCoverage.test.tsx`, new vitest files |
| E2E | `frontend/tests/e2e/manual-insert-slide.spec.ts` (new), `frontend/tests/fixtures/manual-insert-decks.json` (new), `tests/unit/test_manual_insert_e2e_fixture.py` (new), `frontend/tests/e2e/agent-insert-slide.spec.ts`, `.github/workflows/test.yml` |
| Docs | `CONTEXT.md`, `docs/technical/{backend-overview,slide-viewer,usage-analytics}.md`, `docs/user-guide/01-generating-slides.md` |
| Optional eval | `evals/packs/architect/{mutations,heldout}.py`, case dirs, `tests/unit/evals/{test_cross_split,test_pack_generation_isolation,test_pack_architect,test_pack_architect_heldout}.py`, `evals/README.md` |

## Order and parallelism

```
Task 1 (domain + shell) ─┬─> Task 2 (writer) ─> Task 3 (service + route) ─┐
                         ├─> Task 4 (architect rules) ────────────────────┴─> Task 5 (graph) ─> [Task 11, optional]
                         └─> Task 7 (blank-aware frontend; reads Task 1's case table)
Task 6 (affordance) ─> Task 8 (indicator + ChatPanel error refetch)
Tasks 1, 3, 6, 7, 8 ─> Task 9 (Playwright, fixture cross-check, matrix) ─> Task 10 (docs)
```

**Same-file sequences**

| File(s) | Tasks |
|---|---|
| `chat_service.py` | 1 → 3 |
| `SlideViewer.tsx`, `ThumbnailRibbon.tsx`, `AppLayout.tsx` | 6 → 8 |
| `ChatPanel.tsx` | 8 only |
| `nodes.py`, `test_architect_insert_slide.py` | 4 only |
| `deckSpecMarkdown.ts`, its coverage test, `SpecView.tsx`, `useAutoVerification.ts`, `blankSlide.ts` | 7 only |
| `deck_spec_slides.py`, `blank_slide_cases.json` | 1 only (Task 7 reads the JSON) |

The frontend lane (6 → 8) needs no backend change: the route exists. The `inserted_slide_id` that
Task 6 reads is additive, and the mocks in Task 6's tests supply it.

---

## Task 1: Domain helpers — the blank shell, the predicates, the spec splice

**Models:** test=opus impl=opus (it parses deck HTML and feeds the safety scan)

**Files:** `src/domain/deck_spec_slides.py` (new), `tests/unit/test_deck_spec_slides.py` (new),
`tests/fixtures/blank_slide_cases.json` (new), `src/api/services/chat_service.py`

Interface (NEW). It imports only `json`, `typing`, `bs4`, `src.domain.slide.has_slide_wrapper`,
`src.utils.html_safety.scan_html_for_unsafe_patterns` and `src.domain.deck_spec.SlideSpec`, so that
`nodes.py`, `session_manager.py`, `chat_service.py` and export can all import it:

```python
BLANK_SLIDE_HTML: str = '<div class="slide"></div>'   # moved from chat_service.py:73 (the fallback)
BLANK_DECK_SPEC_ENTRY: Dict[str, Any]                  # moved from chat_service.py:79-85, same five keys;
                                                       # its comment: "the exact description of a blank slide"
def blank_slide_shell(slide_htmls: Sequence[str], position: int) -> str: ...   # D1
def is_blank_slide_html(html: Optional[str]) -> bool: ...                       # D4 structural
def is_blank_slide_spec(entry: Union[SlideSpec, Mapping[str, Any]]) -> bool:
    """purpose and content_brief both empty after .strip(); missing keys count as empty."""
def renumber_spec_slides(spec: Dict[str, Any],
                         reorder: Callable[[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]]]
                         ) -> Optional[Dict[str, Any]]:
    """The pure middle of ChatService._rewrite_deck_spec_slides, moved verbatim: None when
    spec["slides"] is not a list or reorder returns None; IndexError propagates; returns a NEW dict
    (input not mutated), positioned entries re-stamped 0..n, unpositioned entries after, unchanged."""
def splice_blank_entry(entries: List[Dict[str, Any]], position: int) -> List[Dict[str, Any]]:
    """entries[:landed] + [dict(BLANK_DECK_SPEC_ENTRY)] + entries[landed:], landed = min(position, len)."""
def spec_json_with_blank_entry(raw: Optional[str], position: int) -> Optional[str]:
    """json.loads(raw); None/""/bad JSON/non-dict/{} -> None (leave the column untouched); else
    renumber_spec_slides(spec, lambda e: splice_blank_entry(e, position)) -> json.dumps, or None."""
```

`blank_slide_shell` works as follows (BeautifulSoup `html.parser`):
- For each slide, find the first element whose class tokens include `slide`, then walk up to the
  fragment's top level; that path is the chain. Slides with no such element are skipped.
- The signature is `tuple((tag.name, tuple(sorted(class tokens))) for tag in chain)`. Pick the most
  common signature.
- Ties go to the nearest slide holding a tied signature: scan `position-1, position-2, …`, then
  `position, position+1, …`. At position 0, the scan starts at `0`.
- Rebuild that nearest slide's chain as fresh tags. Each keeps only `class`, `data-label` and
  `style`, with values verbatim, nested with no other children and no text.
- Return the shell when `has_slide_wrapper(shell) and scan_html_for_unsafe_patterns(shell) == []`;
  otherwise return `BLANK_SLIDE_HTML`.

`is_blank_slide_html` is true iff `has_slide_wrapper(html)`, the fragment's text is whitespace, and
the fragment is a single element chain ending at the first `.slide`. Every chain element has exactly
one element child; the `.slide` has none; comments are ignored.

Behaviour in `chat_service.py`:
- Import the constants and `renumber_spec_slides`. `BLANK_SLIDE_HTML` stays importable from
  `chat_service` (`test_insert_slide_service.py:39`); `_BLANK_DECK_SPEC_ENTRY` becomes an alias.
- `_rewrite_deck_spec_slides` keeps its read, `IndexError` handling, logging, author stamp, write and
  swallow policy byte-for-byte. Only its middle calls `renumber_spec_slides`.
- Fix the stale `:75-78` comment (n2). It moves with the constant.

Steps:
- [ ] **Step 1 (test author).**
  - **`tests/fixtures/blank_slide_cases.json`.** Rows of `{"name", "html", "blank"}`, covering:
    - the bare div; a section shell; a 3-level chain; `class="slide dark"`;
    - a style with `url({{image:3}})`; whitespace and a comment inside;
    - text inside (False); an `<img>` inside (False); a `<script>` sibling (False);
    - a second top-level element (False); a `.slide` with a child div (False);
    - no `.slide` (False); `<section class="slide">` alone (False: no div wrapper).

    `test_deck_spec_slides.py` asserts `is_blank_slide_html` on every row; Task 7's vitest reads the
    same file.
  - **`blank_slide_shell` on three fixtures.**
    - (1) Meridian `.slide` ground: `evals/fixtures/meridian/gold/{0..7}.html`, `section.slide`
      roots, so the result falls back to the bare div.
    - (2) The section wrapper: slides shaped like `tests/fixtures/export_slide_root/wrapped_bare_slide.html`
      (`<section data-label="Acme Ground"><div class="slide">…`). The shell is exactly
      `<section data-label="Acme Ground"><div class="slide"></div></section>`.
    - (3) Unpinned and inline-styled: `<div class="slide" style="background:#0b1f3a;color:#fff;padding:60px"><h1>…`.
      The shell keeps that style verbatim.
  - **Other `blank_slide_shell` cases.**
    - A majority signature beats the neighbour.
    - Tie-breaks before, and after at position 0.
    - `id`, `on*` and `data-x` attributes are dropped; a `url()` style is kept.
    - A chain whose style trips the scanner (e.g. `background:url(javascript:…)` or an external
      `src`-like pattern, as `_PATTERNS` allows) → bare.
    - An empty deck, or one with no `.slide` → bare.
    - Every result `is_blank_slide_html`.
  - **The rest.**
    - `is_blank_slide_spec`, as in the docstring.
    - `renumber_spec_slides`: re-stamps a gapped spec; unpositioned entries last; input not mutated;
      a `None` reorder returns `None`; `IndexError` propagates.
    - `splice_blank_entry` at 0, mid, end and past the end.
    - `spec_json_with_blank_entry`: an unknown key and an invalid shape are kept; `None` for `None`,
      `""`, `"not json"`, `"[]"` and `{}`; `{"slides": []}` gains the entry.
  - **Export smoke.** `src.api.routes.export.build_slide_html(shell_slide, deck)` on the wrapper deck
    (css plus slides) renders the shell markup and the deck CSS.
  - `chat_service.BLANK_SLIDE_HTML is deck_spec_slides.BLANK_SLIDE_HTML`.

  Sabotage:
  - keep every attribute → `on*` row red;
  - drop `style` → inline fixture red;
  - first slide instead of the majority → majority row red;
  - skip the scan → scanner row red;
  - the predicate ignores text → text row red;
  - mutate the spec input → red.

  Confirm red; leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** `uv run pytest tests/unit/test_deck_spec_slides.py tests/unit/test_mutations_renumber_the_deck_spec.py tests/unit/test_insert_slide_service.py tests/unit/test_export_csp.py -n 4 -q`, then the unit suite against the cause-set.

Pitfall: do not "improve" `_rewrite_deck_spec_slides` (for example by validating with `DeckSpec`);
its raw-dict semantics are pinned.

## Task 2: `SessionManager.insert_slide` — one transaction through the shared shift

**Models:** test=opus impl=opus (the canonical row writer; a quiet mistake mis-attributes verdicts)

**Files:** `src/api/services/session_manager.py`, `src/api/services/slide_repository.py`,
`src/database/models/usage_event.py`, `tests/unit/test_manual_insert_writer.py` (new),
`tests/unit/test_manual_insert_writer_postgres.py` (new; `pytestmark = pytest.mark.postgres`; pattern
`tests/unit/test_insert_pending_slides_postgres.py`)

Interfaces:

```python
# usage_event.py
EVENT_SLIDE_INSERTED = "slide_inserted"                        # docstring list updated

# session_manager.py (module level, beside _rewrite_slide_rows)
SESSION_LOCK_TIMEOUT_SECONDS = 300                             # acquire_session_lock's default now reads it
class SlideRowsChangedError(RuntimeError): ...                 # MOVED from slide_repository (re-imported there)
class DeckBusyError(RuntimeError): ...                         # NEW: a turn holds another session of this deck
def _snapshot_row(row: SessionSlide) -> Dict[str, Any]: ...    # MOVED verbatim (re-imported in slide_repository)
def _splice_slide_rows(db, owner_id: int, old_rows: List[SessionSlide],
                       new_slides: Mapping[int, Tuple[Dict[str, Any], Dict[str, Any]]]) -> None:
    """Steps 2-4 of insert_pending_slides, moved: snapshot + attribute every old row BEFORE any write,
    lay out len(old)+len(new) positions (new_slides[i] = (slide_dict, incoming_record)), then
    _rewrite_slide_rows(..., now_dt=None, author_fallback=None, attribution=<exact>, incoming=<new>).
    ValueError for an index outside range(len(old_rows) + len(new_slides))."""

class SessionManager:
    def insert_slide(self, session_id: str, position: int, *,
                     slide: Dict[str, Any],            # html, slide_id, scripts, created_by/at, modified_by/at
                     expected_rows: Sequence[Tuple[Optional[str], str]],
                     deck_dict: Dict[str, Any], title: Optional[str], html_content: str,
                     scripts_content: Optional[str],
                     mutation: DeckMutationContext,    # insert_slide / deck / object_id = slide["slide_id"]
                     expected_version: Optional[int] = None,
                     inserted_by: Optional[str] = None) -> Dict[str, Any]:
        # -> {"session_id", "version", "position", "slide_id", "slide_count"}
```

`insert_slide` does the following, in ONE `get_db_session()` and in this order:
1. Resolve the session and the deck owner. Lazily
   `from src.api.services.chat_service import _refuse_during_an_arc_review` and call it with
   `(db, deck_owner)`.
2. **(M2)** Query `UserSession` where `id == deck_owner.id OR parent_session_id == deck_owner.id`,
   `id != session.id`, `is_processing` is true, and `processing_started_at >= utcnow −
   SESSION_LOCK_TIMEOUT_SECONDS`. Any hit → `DeckBusyError`.
3. Validate: `deck = deck_owner.slide_deck` (`None` → `ValueError("No slide deck available")`); a stale
   `expected_version` → `VersionConflictError`; `position < 0` or a mutation other than
   `insert_slide`/`deck` → `ValueError`.
4. Re-read the rows in position order. **Rows exist:** `[(row.slide_id, compute_slide_hash(row.html or
   ""))] != list(expected_rows)` → `SlideRowsChangedError`; `landed = min(position, len(rows))`;
   `_splice_slide_rows(db, deck_owner.id, rows, {landed: (slide, {})})`. **No rows but non-empty
   `expected_rows` (D13):** `len(deck_dict["slides"]) != len(expected_rows) + 1` →
   `SlideRowsChangedError`, else `_rewrite_slide_rows(db, deck_owner.id, deck_dict["slides"],
   now_dt=utcnow, author_fallback=None)`. **Neither:** splice with `old_rows=[]`.
5. `new = spec_json_with_blank_entry(deck.deck_spec_json, landed)`; assign it when not `None`.
6. Columns: `title`, `html_content`, `scripts_content`, `slide_count` (`len(rows) + 1`, or
   `len(deck_dict["slides"])` on D13), `deck_json = json.dumps(deck_dict)`, `version += 1` once,
   `modified_by = slide["created_by"]` when truthy, `last_activity` on session and owner. css,
   external_scripts and head_meta are NOT touched.
7. Evidence: `db.add(UsageEvent(username=inserted_by, event_type=EVENT_SLIDE_INSERTED,
   session_id=session.id))` when `inserted_by` (lazy import); `db.flush()`; exactly one
   `record_shared_deck_mutation(db, requesting_session=session, deck_owner=deck_owner, deck=deck,
   actor=mutation.actor, operation="insert_slide", object_type="deck", object_id=mutation.object_id)`
   through the module-level name, keyword arguments.

`insert_pending_slides` replaces its inline steps 2-4 (`slide_repository.py:566-614`) with one
`_splice_slide_rows` call; everything else in it stays byte-identical.

Steps:
- [ ] **Step 1 (test author).** `tests/unit/test_manual_insert_writer.py` (fixtures in the style of
  `test_insert_pending_slides.py`). Seed rows A–D, each with a marker, its own `slide_id`, scripts,
  distinct authorship and timestamps, a two-hash record (plus a `tellr_review` finding) and a fragment;
  a failed placeholder with a NULL author; a backfilled row with NULL timestamps; a valid spec with one
  entry per row.
  - **Insert at 1:** every old row equals its snapshot by marker in every column except `position`/`id`
    (NULLs stay NULL); layout `[A, BLANK, B, …]`; the new row carries the given html/slide_id/
    authorship/timestamps, no record, no fragment; spec entry 1 is blank and later entries are
    byte-identical except `position + 1`; `slide_count == 7`, `html_content`/`scripts_content`/
    `deck_json` equal the arguments, `version == before + 1`, `modified_by` set; **`css`,
    `external_scripts_json`, `head_meta_json` byte-identical; `last_activity` set on session and
    owner; every `get_slide_deck()["findings"]` `slideIndex` points at the slide whose hash is in its
    id** (m11); exactly one `SharedDeckMutationEvent` (`insert_slide`, the new id) and one `UsageEvent`.
  - **At 0 and past the end** (the returned `"position"` is the landed index). **Spec variants:** NULL
    stays NULL; unparseable and `{}` untouched; invalid shape renumbered, unknown key kept;
    `{"slides": []}` gains the entry. **Atomicity:** `session_manager.record_shared_deck_mutation`
    patched to raise → rows, spec, version and `usage_events` byte-identical.
  - **Refusals, each changing nothing:** stale `expected_version` → `VersionConflictError`; one
    differing hash → `SlideRowsChangedError`; negative position or wrong operation → `ValueError`; a
    live claim on the OWNER's deck, called with a contributor session id → `ArcReviewInFlightError` (a
    claim older than `CLAIM_TTL_SECONDS` proceeds); **(M2)** the owner session `is_processing` 10 s ago
    and a contributor inserts → `DeckBusyError`, and the reverse; a start > 300 s ago proceeds; the
    requesting session's own `is_processing` (the route's lock) does not self-refuse.
  - **Contributor** writes the owner's rows; the usage event carries the contributor's pk; no
    `inserted_by` → no usage event, mutation event still written. **Exact map:** two id-less identical
    blank rows at 2 and 3, told apart by a marker in each record and fragment; after an insert at 1
    each keeps its own and the newcomer carries none. **D13:** rows materialised from `deck_dict` in
    order, spec spliced. `slide_repository.SlideRowsChangedError is session_manager.SlideRowsChangedError`.
  - **Postgres file:** insert at 1, the live-claim refusal, the M2 owner-turn refusal.

  Sabotage (split with the reviewer): `attribution=None` → twins red; snapshot only
  html/scripts/slide_id → by-marker red; `now_dt=utcnow()` → NULL-timestamp red; refuse with `session`
  → contributor claim red; busy query without `parent_session_id` → contributor-turn red; without
  `id != session.id` → self-refusal red; spec after the evidence → atomicity red; `version += 2` → red;
  assigning `deck.css` → red.

  The existing suites must stay green unchanged: `test_insert_pending_slides.py`,
  `test_insert_shifts_records_and_specs.py`, `test_save_points.py`, `test_slide_writer.py`,
  `test_deck_read_path_keys.py`, `test_findings_follow_their_slide.py`. Confirm red; leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** `uv run pytest tests/unit/test_manual_insert_writer.py tests/unit/test_insert_pending_slides.py tests/unit/test_insert_shifts_records_and_specs.py tests/unit/test_save_points.py tests/unit/test_slide_writer.py tests/unit/test_architect_insert_slide.py tests/unit/test_graph_insert_slide_turn.py -n 4 -q`, then the one-writer grep, then the unit suite.

Pitfalls:
- Snapshots and attributions come before any write, because `_upsert_slide_row` mutates the ORM rows.
- `save_slide_deck` is NOT touched.
- Only `acquire_session_lock`'s DEFAULT value changes; its body does not.

## Task 3: `ChatService.insert_slide` and the route use the writer and the shell

**Models:** test=opus impl=sonnet

**Files:** `src/api/services/chat_service.py`, `src/api/routes/slides.py`,
`tests/unit/test_manual_insert_service.py` (new), `tests/unit/test_manual_insert_route.py` (new)

Behaviour:
- **`ChatService.insert_slide(session_id, position, *, html=None, expected_version=None,
  inserted_by=None)`:**
  1. Add `import copy`. `current_deck = self._get_or_load_deck(...)` with today's checks;
     `expected_rows` from `current_deck.slides` BEFORE any change; `landed = min(position,
     len(slides))`; `slide_html = html if html is not None else blank_slide_shell([s.html for s in
     current_deck.slides], landed)`, then the wrapper check.
  2. `working = copy.deepcopy(current_deck)`; the new `Slide` gets `slide_id=str(uuid.uuid4())` (this
     module's `uuid`), explicit `created_at = modified_at = utcnow ISO "Z"`, `stamp_created(_user)` when
     a user resolves; `working.insert_slide(new, position)`; no `_reindex_slide_ids`.
  3. `get_session_manager().insert_slide(session_id, position, slide=<new as dict>, expected_rows=...,
     deck_dict=working.to_dict(), title=working.title, html_content=working.knit(),
     scripts_content=working.scripts, mutation=session_manager.deck_mutation_context(session_id,
     operation="insert_slide", object_type="deck", object_id=new.slide_id), expected_version=...,
     inserted_by=...)`.
  4. Invalidate the cache in a `finally`. On success: reload; `create_save_point(description=
     f"Inserted slide {landed + 1}", deck=reloaded)` (warning on failure); return the substituted
     `reloaded.to_dict()` (else the working dict) plus `inserted_slide_id` and `inserted_position`.
     Delete `_insert_deck_spec_slide`; the "four routes" docstring (`:4085-4090`) says three (n2).
- **Route:** read `inserted_by = get_current_user()` in the handler and pass it; the lock-held 409 uses
  `CONVERSATION_BUSY_DETAIL` (m8); before `except Exception` map `ArcReviewInFlightError` and
  `DeckBusyError` → 409 `CONVERSATION_BUSY_DETAIL`, `SlideRowsChangedError` → 409 `DECK_CHANGED_DETAIL =
  "The deck changed while the slide was being added. Refresh and try again."`. **m9:** `if request.html
  is not None: await asyncio.to_thread(mark_dirty, request.session_id, get_current_user())` — keep the
  call text exactly (the placement test reads the AST); fix the `:211-213` comment.

Steps:
- [ ] **Step 1 (test author).**
  - **`test_manual_insert_service.py`** (the `service` fixture shape of `test_insert_slide_service.py`,
    plus `chat_service.get_current_username` → `"owner@test.com"`):
    - **No display-name write-back:** monkeypatch `src.services.identity_provider.resolve_display_names`
      to map every email to a name; after an insert the old rows still hold raw emails (red today).
    - **The shell is the deck's:** on the section-wrapper deck the new row's html is
      `<section data-label="Acme Ground"><div class="slide"></div></section>`; a caller-supplied
      `html` is stored verbatim.
    - One save point; one bump; the return value is the reloaded deck plus `inserted_slide_id` (= the
      row's id, from the monkeypatched `chat_service.uuid.uuid4`) and `inserted_position == landed`;
      `inserted_by` reaches the usage event.
    - **No ghost:** `SessionManager.insert_slide` patched to raise `VersionConflictError` →
      `_get_or_load_deck` shows the original slides. **Self-heal (m11):** corrupt the cached deck in
      place (append a slide, as a failed update/duplicate would) → `SlideRowsChangedError`; an
      immediate retry succeeds with correct rows.
    - **Coherence (tellr-code-review §1):** two `ChatService`s on one DB — A caches, B inserts, A loads
      4 slides; A with `_get_deck_version` patched to report its stale version raises
      `SlideRowsChangedError` and writes nothing.
  - **`test_manual_insert_route.py`** (route pattern of `test_delete_message.py`): a blank insert (no
    `html`) passes `inserted_by` and does NOT call `mark_dirty`; an html insert calls it once;
    `ArcReviewInFlightError`/`DeckBusyError` → 409 `CONVERSATION_BUSY_DETAIL`, lock released, no
    `mark_dirty`; `SlideRowsChangedError` → 409 `DECK_CHANGED_DETAIL`; a held lock → 409
    `CONVERSATION_BUSY_DETAIL`, lock NOT released; `ValueError` → 400.

  Sabotage: back through `save_slide_deck` → display-name red; the bare constant → shell red; no
  `finally` → ghost red; mark on every insert → blank-route red; `except Exception` first → 500.
  `test_insert_slide_service.py`, `test_mutations_renumber_the_deck_spec.py`,
  `test_authz_slides_insert.py`, `test_spec_sync_placement.py` stay green unchanged — if the placement
  test would need an edit, STOP and keep `mark_dirty` (supervisor condition). Confirm red; leave
  uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** `uv run pytest tests/unit/test_manual_insert_service.py tests/unit/test_manual_insert_route.py tests/unit/test_insert_slide_service.py tests/unit/test_mutations_renumber_the_deck_spec.py tests/unit/test_authz_slides_insert.py tests/unit/test_spec_sync_placement.py tests/unit/test_multiworker_cache_coherence.py -n 4 -q`, then the unit suite. The reviewer checks the CI-only integration tests named in Facts on the PR run.

## Task 4: The architect never rebuilds, re-reviews, drops or re-describes an untouched blank

**Models:** test=opus impl=opus (ordering inside `architect_node` is the whole argument)

**Files:** `src/services/graph/nodes.py`, `tests/unit/test_architect_blank_slides.py` (new),
`tests/unit/test_architect_insert_slide.py` (one test, named below)

Behaviour (D5; lines at 3caf1ebf). New module functions go directly after
`_persisted_spec_describes_these_rows` (`:1039`); `architect_node` gets one-line call sites only (m5);
the one new import line goes directly under `from src.domain.deck_spec import` (`:67`); do not touch
`:68-110`.
1. **`_description_keeps_what_it_cannot_see(spec, prior_spec, committed_rows) -> DeckSpec` (N2):** (a)
   position sets differ → WARNING `describe_spec_positions_changed`, return
   `prior_spec.model_copy(deep=True)`; (b) else, at each position whose committed row
   `is_blank_slide_html` and whose prior entry `is_blank_slide_spec`, a deep copy of the prior entry
   (INFO `describe_kept_blank_slides`). Called right after the edit guards (`:1832`, before `:1834`)
   when `describe_only and intent in ("build", "edit") and spec is not None and prior_spec is not None
   and edit_degrade is None and committed_positions and
   _persisted_spec_describes_these_rows(prior_spec, committed_positions)`.
2. **`_untouched_blank_positions(spec, alignment, inserting) -> Set[int]` (N1):** blank final entries
   minus `inserted_indices | revised_indices` (insert turn) or `alignment.revised`; computed after the
   targets (`:1903-1960`) for `intent == "edit" and not describe_only and alignment is not None`, else
   `set()`.
3. **`_drop_untouched_blanks(session_id, positions, untouched, slide_references) -> List[int]`:** drops
   them; a dropped position named in the references → WARNING `blank_named_but_not_described` and
   `_surface_notice(session_id, "Slide {n} is still blank: its plan has no purpose or brief yet, so I
   did not build it. Tell me what it should say.")` (m1). Three one-line sites: `edit_targets`/
   `updates["target_positions"]`, the design-contract list (`:2096`), `rebuild` (`:2141`).
4. **`rereview_committed_slides`** (`:542`): beside the placeholder branch (`:660`), a position whose
   `spec.slide_at(position)` is blank joins a new `blank` set and `continue`s — in `committed`, no model
   call, neither `reviewed` nor `failing`; `empty` gains `"blank": set()`. `judged_nothing` (`:2151`)
   becomes `bool(committed - blank) and not reviewed` (m2).
5. Fix the `:1051-1054` docstring (n2).

Steps:
- [ ] **Step 1 (test author).** `tests/unit/test_architect_blank_slides.py`, on `graph_env` with the
  `test_architect_insert_slide.py` helpers. Rows `[A, SHELL, C, D]` (SHELL a blank row); the persisted
  spec's entry 1 is blank. **Assert on `target_positions`, emit metadata (`rebuilding`, `surfaced`) and
  notice-row existence, never prose** (m5).
  - **Equal-length:** revising 0 with model targets `[0, 1]` → `[0]`; filling entry 1 with `[1]` →
    `[1]`; entry 1 blank but its row hand-typed → still dropped; "fill slide 2" with targets `[1]` and
    entry 1 left blank → `[]` plus the WARNING and a notice row (m1); two ADJACENT blanks (1, 2),
    filling 2 → `[2]` (m11).
  - **Insert turns:** a non-blank NEW slide next to twin blanks aligns, targets only the new index,
    both blanks untouched by row; a blank NEW entry next to twin blanks → `edit_insert_ambiguous`,
    nothing changed (m11); an agent insert whose new entry is blank (no twins) still targets it (#337).
  - **Design contract:** changing `design_system_id` → `[0, 2, 3]` (setup:
    `test_deck_level_spec_change.py:262`). **Deck level:** changing `audience` with a reviewer stub
    failing every reviewed slide → the reviewer is called for 0, 2, 3 only, `verdicts["blank"] == {1}`,
    emit `rebuilding == [0, 2, 3]`, nothing surfaced for 1; when every non-blank re-review raises,
    `judged_nothing` still fires; a deck whose committed rows are all blank sets no `error_state` (m2).
  - **Describe-only:** the model drops entry 1 → persisted == prior, `error_state is None`, WARNING,
    and the returned spec is not the `prior_spec` object; an invented purpose for entry 1 plus a new
    `narrative_arc` → entry 1 stays blank, the arc is the model's; row 1 hand-edited → the model's entry
    kept; a stale persisted spec → the model's spec persists (unchanged).
  - **Edit one existing test** (name it in the report):
    `test_architect_insert_slide.py::TestPathsThatDoNotShift::test_a_describe_only_growth_persists_the_spec_and_shifts_nothing`
    → `…_growth_is_not_persisted_and_shifts_nothing`, asserting `== prior`; its no-shift and
    no-version assertions unchanged.

  Sabotage: drop `- touched` → blank-new-entry insert red; N1 on equal-length targets only →
  design-contract and deck-level red; no rereview skip → call-count red; `judged_nothing` unchanged →
  all-blank red; N2(b) without the row check → hand-edited red; N2(a) removed → drop red; return
  `prior_spec` itself → identity red. Confirm red; leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** `uv run pytest tests/unit/test_architect_blank_slides.py tests/unit/test_architect_insert_slide.py tests/unit/test_graph_nodes.py tests/unit/test_deck_level_spec_change.py tests/unit/test_spec_sync_sweeper.py -n 4 -q`, then the unit suite. The reviewer checks the four describe-only integration tests (Facts) on the PR run.

Pitfall: #321 rewrites the notice prose (`:2177`), and #321 and #334 touch the imports at `:49`,
`:67-110` and `:1159-1260`. The hunks above avoid every one of those regions.

## Task 5: Graph acceptance — the blank is filled in place; the sweeper and deck-level turns leave it alone

**Models:** test=opus impl=opus (impl = fixing any defect this exposes in Tasks 2–4; no new feature)

**Files:** `tests/unit/test_graph_blank_slide_turn.py` (new)

- [ ] **Step 1 (test author).** The compiled graph on `graph_env_threadsafe` (`_invoke`, `_rows`,
  `_by_marker`, `_identity` as in `test_graph_insert_slide_turn.py`); the builder stub emits
  `<h1>{purpose}</h1>`.
  - **Turn 1** builds `make_spec((0, 1, 2))`; distinct authorship per row; snapshot by marker. **Manual
    insert:** `ChatService().insert_slide(sid, 2, inserted_by="owner@test.com")` with
    `chat_service.get_current_username` patched; snapshot the blank by `slide_id`.
  - **Turn 2 "Fill slide 3 with pricing":** the architect stub returns the persisted spec with entry 2
    revised to `purpose-PRICING`, targets `[2]`. Assert: the recorded payload has
    `current_deck_spec["slides"][2]` blank, `committed_slide_count == 4`, four `slide_numbering`
    entries; builder and build-reviewer calls exactly `[2]`; row 2 holds `purpose-PRICING` with the
    blank's `slide_id`; every other row equals its snapshot whole; spec positions 0..3; no
    `insert_slide` event in turn 2.
  - **Deck-level variant:** insert another blank at 1, then change `audience` with the reviewer stub
    failing objectively → the blank reaches neither a builder nor the reviewer; its row is unchanged.
  - **Sweeper-shaped turn** (`describe_only=scoped(turn, True)`): the architect invents a purpose for
    the blank → the persisted entry stays blank; no builder runs.

  Sabotage: N1 removed → the deck-level variant builds the blank; N2(b) removed → the invented purpose
  persists; a fresh `slide_id` on the reviewed write → the in-place assertion red.
- [ ] **Step 2 (implementer).** Fix product code, not the test, for any red caused by Tasks 2–4, and
  report the defect.
- [ ] **Step 3.** `uv run pytest tests/unit/test_graph_blank_slide_turn.py -n 4 -q` three times (flake check), then the unit suite.

## Task 6: The insert affordance (toolbar "New slide", ribbon gaps)

**Models:** test=opus impl=sonnet

**Files:** `frontend/src/services/api.ts`, `frontend/src/components/SlideViewer/ThumbnailRibbon.tsx`,
`frontend/src/components/SlideViewer/SlideViewer.tsx`, `frontend/src/components/Layout/AppLayout.tsx`,
`frontend/src/components/SlideViewer/SlideInsert.test.tsx` (new)

Interfaces:

```ts
// api.ts, beside deleteSlide
async insertSlide(position: number, sessionId: string, expectedVersion?: number):
  Promise<SlideDeck & { inserted_slide_id?: string; inserted_position?: number }>
// POST /api/slides { session_id, position, expected_version } (no html -> the deck's blank shell)
// !ok -> ApiError(status, <string `detail` from the JSON body if present, else 'Failed to insert slide'>)
// ThumbnailRibbon props gain: onInsert?: (position: number) => void;  insertDisabled?: boolean;
// SlideViewerProps gain:      insertDisabled?: boolean;              // AppLayout passes isGenerating
```

Behaviour:
- **Ribbon:** an `<InsertGap position={k}>` before each `Thumb` and after the last, as a SIBLING of the
  sortable `<button>` (a nested button is invalid), holding `<button data-testid="ribbon-insert-${k}"
  tabIndex={-1} aria-label=…>` with a Plus icon — shown on hover, `disabled` when `insertDisabled`,
  calling `onInsert(k)`. A `dragging` flag (`DndContext` `onDragStart` → set; `onDragEnd`/`onDragCancel`
  → clear) hides every gap (m12).
- **Toolbar:** inside the `!readOnly` group, before Edit, `<Button data-testid="stage-insert-slide">`
  (Plus + "New slide", tooltip "New slide after this one") → `handleInsertSlide(currentIndex + 1)`;
  disabled while `insertDisabled` or an insert is in flight.
- **`handleInsertSlide(position)` in `ViewerBody`:** return unless `!readOnly && sessionId &&
  onSlideChange && !inserting`; `editId = ++deckEditCounterRef.current`; `r = await api.insertSlide(…)`;
  `pendingSelectionRef.current = r.inserted_slide_id` (m6); `api.getSlides` → `onSlideChange(deck)` if
  the counter still equals `editId`. An effect `[slideDeck]` selects the pending id's index once it is
  in the deck, then clears the ref (after render, so the clamp sees the new count). 409/423 →
  `showToast(error.message, 'error')` + `refreshDeck()`; else `'Failed to insert slide'`. The ribbon
  gets `onInsert={readOnly || !onSlideChange ? undefined : handleInsertSlide}`.
- **AppLayout:** `<SlideViewer … insertDisabled={isGenerating} />`.

Steps:
- [ ] **Step 1 (test author).** `SlideInsert.test.tsx` (api mocked, `ToastProvider`, `localStorage`
  stubbed), 3-slide deck: `stage-insert-slide` on slide 2 → `insertSlide(2, sid)`, `getSlides`, the
  refetched deck to `onSlideChange`; a response with `inserted_slide_id: 'new'` and a rerendered deck
  holding `new` at 2 → `ribbon-thumb-2` current; exactly four gaps, `ribbon-insert-0`/`-3` →
  `insertSlide(0)`/`(3)`; gaps hidden during a drag and back after (m12); `readOnly` (and, separately,
  no `onSlideChange`) renders neither control; `insertDisabled` disables both; a rejected
  `ApiError(409, 'Something is still running…')` shows that text and refetches; a second click in
  flight sends nothing. Sabotage: `currentIndex` for `+ 1` → red; `readOnly` gate removed → red; gaps
  from 1 → red; selecting by `inserted_position` before the deck renders (the clamp) → append case red.
  Confirm red; leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** `cd frontend && npx vitest run src/components/SlideViewer && npm run build` (env baseline only).

## Task 7: Blank-aware frontend (structural predicate, auto-verify skip, Spec view, Markdown export)

**Models:** test=opus impl=sonnet

**Files:** `frontend/src/services/blankSlide.ts` (new), `frontend/src/services/__tests__/blankSlide.test.ts`
(new), `frontend/src/hooks/useAutoVerification.ts`, `frontend/src/hooks/useAutoVerification.test.tsx`
(new), `frontend/src/components/SpecView/SpecView.tsx`, `frontend/src/components/SpecView/SpecView.test.tsx`
(cases), `frontend/src/services/deckSpecMarkdown.ts`,
`frontend/src/services/__tests__/deckSpecMarkdownCoverage.test.tsx` (additions only)

Interface:

```ts
export function isBlankSlideHtml(html: string | null | undefined): boolean;   // D4, DOMParser, same rules
export function isBlankSlideSpec(s: Pick<SlideSpec, 'purpose' | 'content_brief'>): boolean;  // both trim() === ''
```

Behaviour:
- `useAutoVerification`'s filter (`:160-168`) also skips `isBlankSlideHtml(slide.html)`.
- **SpecView:** for `isBlankSlideSpec(slide)`, `<p data-testid="spec-slide-blank-${position}"
  className="… text-muted-foreground">Blank slide</p>` replaces the purpose and brief paragraphs.
- **`deckSpecMarkdown.ts` (`:90-101`):** a blank entry's fields start with `Blank slide.` in place of
  `**Purpose:**`/`**Content brief:**`; Assumes, Hands off, Slide type and Data references unchanged.
- **Coverage guard (b):** `BLANK` (GOLDEN with one entry's purpose and brief emptied) joins `FIXTURES`
  (`:374`); `BLANK: ['Blank slide']` joins `MUST_SEE` (`:377`).

Steps:
- [ ] **Step 1 (test author).** `blankSlide.test.ts` reads `tests/fixtures/blank_slide_cases.json`
  (`fs.readFileSync(path.resolve(__dirname, '../../../../tests/fixtures/blank_slide_cases.json'))`) and
  asserts `isBlankSlideHtml(row.html) === row.blank` on every row, plus the spec predicate. Hook test
  (`renderHook` + `ToastProvider`): a shell slide and a normal slide, both with `content_hash` and
  unverified → `verifySlide` once, for the normal one. SpecView: a blank entry shows
  `spec-slide-blank-N`, a non-blank one does not, both keep "Slide N+1". Markdown: a blank entry renders
  `Blank slide.` and no `**Purpose:**`; `deckSpecMarkdown.test.ts` (golden) passes unchanged; the
  coverage guard is green WITH the BLANK fixture. Sabotage: drop the hook skip → red; the TS predicate
  ignores text → a case-table row red; remove "Blank slide." from the export → guard (b) red on BLANK
  (the M1 proof); drop the SpecView label → red. Confirm red; leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** `cd frontend && npx vitest run src/hooks src/components/SpecView src/services/__tests__ && npm run build`.

## Task 8: The new-slide indicator, and a refetch after an errored turn

**Models:** test=opus impl=sonnet (the reviewer runs at opus: effect ordering)

**Files:** `frontend/src/components/SlideViewer/newSlides.ts` (new),
`frontend/src/components/SlideViewer/SlideViewer.tsx`, `ThumbnailRibbon.tsx`,
`frontend/src/components/Layout/AppLayout.tsx`, `frontend/src/components/ChatPanel/ChatPanel.tsx`,
`frontend/src/components/SlideViewer/newSlides.test.ts` (new),
`frontend/src/components/SlideViewer/NewSlideIndicator.test.tsx` (new),
`frontend/src/components/ChatPanel/ChatPanel.errorRefetch.test.tsx` (new; pattern
`ChatPanel.turnProgress.test.tsx`)

Interface:

```ts
export const SYNTHETIC_SLIDE_ID_PREFIX = 'build-';
export function syntheticSlideId(position: number): string;          // `build-${position}`
export const NEW_SLIDE_INDICATOR_MS = 5000;
export function diffNewSlides(baseline: ReadonlySet<string> | null,
  slides: ReadonlyArray<Pick<Slide, 'slide_id'>>): { baseline: ReadonlySet<string> | null; fresh: string[] };
```

Behaviour:
- `AppLayout.handleSlideReady` uses `syntheticSlideId(position)` (identical string).
- **`ViewerBody`:** ONE effect with deps `[slideDeck, deckKey]`: if `deckKey !== lastDeckKeyRef.current`,
  reset the baseline to `null` and record the key BEFORE diffing (n5); `diffNewSlides`, store the
  baseline; when `fresh` is non-empty, select Task 6's pending id if it is in the deck (then clear it)
  else `fresh[0]`, `setFreshIds(new Set(fresh))`, and (re)start one timer clearing it after
  `NEW_SLIDE_INDICATOR_MS` (cleaned up on unmount). Task 6's selection effect merges into this one; its
  tests stay green.
- **`Thumb` gets `isNew`:** `data-new="true"`, a ring, `<span data-testid="ribbon-new-${index}">New</span>`;
  the viewer renders `<span role="status" className="sr-only" data-testid="new-slide-status">Slide N
  added</span>` while any id is fresh.
- **ChatPanel `error` (`:361-367`):** after today's lines, `api.getSlides(activeSessionId).then(r => {
  if (r.slide_deck) onSlidesGenerated(r.slide_deck, rawHtml ?? null); }).catch(() => {})`, with
  `activeSessionId` computed as in `complete` (m6). A failed refetch changes nothing.

Steps:
- [ ] **Step 1 (test author).**
  - **`newSlides.test.ts`** (table over D10): null baseline → no fresh, baseline set; any `build-` id →
    no fresh, baseline kept; pure growth → fresh in deck order; growth plus a removed id → none; empty
    baseline → none; null/empty ids ignored; unchanged deck → none.
  - **`NewSlideIndicator.test.tsx`** (`localStorage` stubbed, fake timers): `[A, B, C]` →
    `[A, B, NEW, C]` → `ribbon-thumb-2` current, `ribbon-new-2` shown, status "Slide 3 added", gone
    after 5000 ms. **SSE shape:** `[A, B, C]` → `[A, build-1, C]` → `[A, NEW, B, C]` → only
    `ribbon-new-1`. **Polling shape (m7):** `[A, B, C]` → `[build-0, build-1, build-2]` (first poll,
    cursor 0) → `[build-0 … build-3]` (a `slide_revisions` replace) → `[A, NEW, B, C]` → only
    `ribbon-new-1`. **Pending wins (m6):** a refetch adding `X` at 1 and `NEW` at 3 with pending `NEW`
    → `ribbon-thumb-3` current, both chipped. A `deckKey` switch to a larger deck sharing ids flags
    nothing (n5); the first mount flags nothing.
  - **`ChatPanel.errorRefetch.test.tsx`:** an `error` event → `getSlides` → `onSlidesGenerated` with
    the refetched deck; a rejected `getSlides` → no throw, no call; `slide_deck: null` → no call.

  Sabotage: diff against the previous render → B flagged (SSE); no synthetic check → polling red;
  `fresh[0]` over the pending id → pending red; reset after the diff → `deckKey` red; no error refetch
  → ChatPanel red. Confirm red; leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** `cd frontend && npx vitest run src/components/SlideViewer src/components/Layout src/components/ChatPanel && npm run build` (env baseline only).

## Task 9: Playwright — manual insert end to end (mocked), the agent insert's indicator, the matrix

**Models:** test=opus impl=haiku (no product code; impl only wires the CI matrix)

**Files:** `frontend/tests/e2e/manual-insert-slide.spec.ts` (new),
`frontend/tests/fixtures/manual-insert-decks.json` (new), `tests/unit/test_manual_insert_e2e_fixture.py`
(new), `frontend/tests/e2e/agent-insert-slide.spec.ts`, `.github/workflows/test.yml`
(`e2e-tests.strategy.matrix.test`, after `inline-svg-records-export`)

- [ ] **Step 1 (test author).**
  - **Fixtures** (`manual-insert-decks.json`): deck **W** (section wrapper; css `section { background:
    rgb(18, 52, 86); color: #fff } .slide { position: absolute; inset: 0 }`; slides
    `<section data-label="Ground"><div class="slide"><h1 data-marker="A">…</h1></div></section>`) and
    deck **I** (unpinned; css `""`; slides `<div class="slide" style="background: rgb(11, 31, 58);
    color: #fff"><h1 data-marker="A">…</h1></div>`), each with its `blank_html` for the insert
    position. `test_manual_insert_e2e_fixture.py` asserts `blank_slide_shell(slides, position) ==
    blank_html` for both (keeps the mock honest).
  - **Setup** as in `agent-insert-slide.spec.ts` (`setupMocks`, `mockSessionWithSlides`, empty
    contributors, a GET-slides route flipping `server.deck`); the mocked `POST /api/slides` captures
    the body, flips the deck to one with `blank_html` at `body.position` and a 4-entry spec (blank
    entry there), and answers with that deck plus `inserted_slide_id`.
  - **(a) Toolbar, deck W:** on slide 2 click `stage-insert-slide` → body `{session_id, position: 2}`,
    no `html`; 4 thumbnails, `ribbon-thumb-2` current, `ribbon-new-2` visible; thumbnails 0, 1, 3 show
    A, B, C; **AC2:** in the blank's thumbnail and on the stage, the computed `background-color` of the
    body's first element child (the root) equals neighbour slide 1's root background; the Spec view
    shows `spec-slide-blank-2` labelled "Slide 3".
  - **(b) Ribbon, deck I:** hover the gap above the first thumbnail, click `ribbon-insert-0` → body
    position 0; the new slide is at 0, current, marked New, and its root background equals slide 1's.
  - **(c) Busy:** the POST answers 409 with `CONVERSATION_BUSY_DETAIL` → the text is visible; still 3
    thumbnails. **(d) View-only:** `/sessions/<id>/view` has no `stage-insert-slide` and no
    `ribbon-insert-*`. **Agent spec:** right after the count reaches 4, `ribbon-new-1` is visible and
    `ribbon-new-0/2/3` are absent.
  - **Sabotage the product, not the mock:** ribbon `onInsert` unwired → (b) red; `currentIndex` for
    `currentIndex + 1` → (a) red; the indicator effect disabled → (a) and the agent spec red; a
    `blank_html` that is not the shell → the fixture pytest red.
- [ ] **Step 2 (implementer).** Add `manual-insert-slide` to the matrix.
- [ ] **Step 3.** Under the e2e lock, run
  `cd frontend && npx playwright test tests/e2e/manual-insert-slide.spec.ts tests/e2e/agent-insert-slide.spec.ts tests/e2e/slide-viewer.spec.ts tests/e2e/viewer-readonly.spec.ts tests/e2e/spec-view.spec.ts --config /tmp/issue314-e2e/pw.config.mjs`
  (m12). Then run `uv run pytest tests/unit/test_e2e_matrix_covers_specs.py tests/unit/test_manual_insert_e2e_fixture.py -q`.

## Task 10: Docs

**Models:** test=sonnet impl=sonnet ("test" is the reviewer's checklist: every symbol named exists,
the behaviour matches the code, no held-out phrasing)

- [ ] **`CONTEXT.md` `## Language`:** **Blank Slide** — "A slide a person inserts by hand: a copy of
  the deck's own slide frame (its wrapper, classes and ground) with no content, and a spec entry with no
  purpose and no brief. The architect fills it when asked; no turn builds, re-reviews or re-describes it
  otherwise. _Avoid_: Pending Slide, empty slide." (Pending Slide's _Avoid_ stays.)
- [ ] **`docs/technical/backend-overview.md`:** under "Adding a slide (#314)", a subsection "Inserting a
  blank slide by hand" covering D1 (the shell and its residual), D2, D3, D7 (with the 300 s limit), D8,
  D5/D6 (N1/N2, the skipped marker, the monolith sentence), D12/D13 (the display-name exception) and
  the known gaps; fix the stale `:554` (n2).
- [ ] **`docs/technical/slide-viewer.md`:** "Per-Slide CRUD" gains New slide and the ribbon gaps
  (gating, hidden while dragging, the keyboard path, n6); a "New-slide indicator" subsection (D10 rules,
  the pending selection, both transports, the error refetch, viewers too); the auto-verify blank skip.
- [ ] **`docs/technical/usage-analytics.md`:** `'slide_inserted'` at `:59` and in the constants list
  `:69-70` (n2).
- [ ] **`docs/user-guide/01-generating-slides.md`, "Navigating Slides":** a short "Adding a blank slide"
  paragraph — New slide and the ribbon "+"; the blank uses the deck's look; ask the assistant to fill it
  ("put our pricing on slide 4"; on older sessions, select it and ask); the busy message; the "New" tag;
  the keyboard path.

## Task 11 (OPTIONAL, separately gated): measure the shipped architect on blank slides

**Models:** test=opus impl=sonnet (the case author). Measurement is SUPERVISOR-run, cap USD 10, before
only; it runs only after Task 5 is committed and only if the supervisor opts in.

- [ ] **Step 1 (case author; may read held-out files; writes no held-out phrasing outside
  `cases_heldout/` and `heldout.py`).** Two cases per split, generated like #337's `add_slide_*`
  (`_payload`, `_write`), on the split's deck with `BLANK_DECK_SPEC_ENTRY` spliced at a mid position k
  (`committed_slide_count + 1`; numbering and references from `architect_slide_payload`):
  `fill_blank_slide` (the user asks, by its number, for content on the blank; `expect = {"intent":
  "edit", "positions": [k], "inserted": []}`; should-fail: a new slide inserted beside it) and
  `edit_beside_blank` (another named slide j; `expect = {"intent": "edit", "positions": [j],
  "inserted": []}`; should-fail: the blank also filled). Production-semantics scoring
  (`scorers.py:152`). Pins: `test_cross_split.py` (ids; 43→45, 13→15),
  `test_pack_generation_isolation.py` (`{"architect": 15}`), both pack tests.
- [ ] **Step 2 (SUPERVISOR).** Calibrate:
  `uv run python -m evals.run_eval --agent architect --calibrate --cases fill_blank_slide,edit_beside_blank --split train`
  (then `--split heldout`); before on `v1-baseline`, train `--repeats 3`, held-out `--repeats 1`;
  ≈ USD 1.7; record in the ledger.
- [ ] **Rule (fixed before the run).** Train ≥ 5/6 and held-out 2/2 → "no prompt change needed";
  otherwise record the failures and open a follow-up (`optimise-agent-prompt`, digest procedure as #337
  Task 13). No prompt change lands here.

---

## CI wiring and docs

New `tests/unit/*` files run in the unit job; `test_manual_insert_writer_postgres.py` is CI-only
(`pytest.mark.postgres`; `test_ci_exports_postgres_test_url.py` needs ≥ 6 marked modules, so adding one
is safe). Integration suites are not edited; the reviewer reads the PR run for those named in Facts
(the describe-only ones included). `manual-insert-slide` joins the e2e matrix. Docs: Task 10's five
files; `evals/README.md` only if Task 11 runs.

## Out of scope

Thumbnail context menu, Ctrl+M, a layout picker, insert from the empty-deck state; moving
update/duplicate/delete/reorder onto D2 (Known gaps); the agent path's inserted-blank entry and a
revision that blanks an entry; a prompt change; a safety scan for client-supplied `html` on
`POST /api/slides` (same trust as `update_slide`; the server-built shell IS scanned); re-deriving an
untouched blank shell after a design-contract change (residual).

## Risks

- **No heartbeat on the session lock:** a turn longer than 300 s stops blocking inserts on every
  session (D7), as for every slide op today.
- **Busy refusals** still occur while a sweep runs for some OTHER human edit (claim normally < 1 min,
  up to 900 s if a worker dies); the blank path no longer opens that window itself (D6).
- **A model filling a blank during an unrelated edit** builds it (optional Task 11). **A `build`
  answer** replaces blanks with the rest of the deck (m3; by request).
- **Design-contract change:** an untouched blank shell keeps the old DS's classes until filled or
  deleted. **N2(a)** discards a whole re-description that changes the position set, on any deck (the
  spec stays exact; the deck-level prose waits for the next sweep).
- **Shell edge cases:** a very varied deck gets the majority frame; a shell whose style trips the
  scanner falls back to the bare div (the old white box).
- **Display names** in `deck_json`, save points and D13 rows, as today.
- **Sibling conflicts** in `nodes.py` (#321, #332, #334), `session_manager.py`, `test.yml`: merge
  `origin/main` before the final push (ledger). **CI-only coverage** for Postgres and integration.

## Review focus (whole-branch Opus review, §7)

1. Writer table (`save_slide_deck`, `restore_version`, `insert_pending_slides`,
   `SessionManager.insert_slide`, `write_slide`): who rewrites rows, with which attribution; one shift
   primitive. 2. Rollback ruling for the manual insert, path by path (each 409, evidence failure,
   row-less deck, stale cache). 3. The shell: attribute stripping, scanner fallback, tie-breaks, and
   Python/TS agreement of the structural predicate. 4. N1/N2 ordering in `architect_node` (indices vs
   positions, design-contract override, rereview skip, `judged_nothing`). 5. Multi-worker coherence
   (tellr-code-review §1), incl. the M2 query on Postgres. 6. The indicator baseline across transports,
   deck switches, previews and the error refetch. 7. Merge / no-merge.

## Self-review (plan author)

- Every AC maps to tasks (AC table); every finding is in the Review table; every existing name is in
  Facts (re-grepped at 3caf1ebf).
- NEW symbols: Task 1 `deck_spec_slides.*` and `blank_slide_cases.json`; Task 2 `EVENT_SLIDE_INSERTED`,
  `SESSION_LOCK_TIMEOUT_SECONDS`, `DeckBusyError`, `_splice_slide_rows`, `SessionManager.insert_slide`,
  moved `SlideRowsChangedError`/`_snapshot_row`; Task 3 `DECK_CHANGED_DETAIL`, `inserted_by=`,
  `inserted_slide_id`/`inserted_position`; Task 4 `_description_keeps_what_it_cannot_see`,
  `_untouched_blank_positions`, `_drop_untouched_blanks`, the rereview `blank` set; Task 6
  `api.insertSlide`; Task 7 `blankSlide.ts`; Task 8 `newSlides.ts`; Task 9 `manual-insert-decks.json`.
- No `DeckSpec`/`SlideSpec`/`ArchitectOutput`/payload/prompt change: no TS mirror, conformance literal
  or digest moves.
- Existing test files edited: one assertion in `test_architect_insert_slide.py` (Task 4); cases in
  `SpecView.test.tsx` and the BLANK fixture + `MUST_SEE` in `deckSpecMarkdownCoverage.test.tsx` (Task
  7); an assertion block in `agent-insert-slide.spec.ts` (Task 9); eval pins (Task 11, optional).
