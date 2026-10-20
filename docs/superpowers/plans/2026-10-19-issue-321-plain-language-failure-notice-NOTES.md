# #321 plain-language failure notices — notes for the reviewer

**Branch:** `feat/321-plain-language-failure-notice` (off `origin/main` `679d2f21`)
**Plan:** `docs/superpowers/plans/2026-10-19-issue-321-plain-language-failure-notice.md`, revised after a
fresh Opus plan review that accepted all 20 findings.

## What changed, by acceptance criterion

**AC1: the notice says in plain language what happened and what to do.**

- All wording now lives in one pure, stdlib-only module, `src/services/graph/user_notices.py`. It has
  12 notice kinds, each with a short `headline` and a full `text`, chosen by graph stage and failure
  class.
- Every agent-mode failure site in `src/services/graph/nodes.py` goes through it:
  - **builder:** a failure (`build_failed`) or a safety-gate block (`blocked_unsafe`)
  - **build review:** `check_failed`
  - **fix-review delivery:** `save_failed`
  - **stalled branch:** `stalled`
  - **unknown stage:** `slide_failed`, the safe fallback
  - **transient review or fix fault:** `kept_unreviewed` / `kept_unfixed`
  - **foreman END with unfinished slides:** `slides_unfinished`
  - **deck-level write, derivation and review failures:** the three `deck_*` kinds
- Each text says what happened and gives one action that works today:
  - "ask me to regenerate slide N" for slide failures
  - "choose Apply there" (the AI feedback drawer) when an automatic fix was skipped
  - "send your request again" when slides were left unfinished
  - "next time I build or edit slides" for deck-level failures
- Example: `Slide 3 was built but couldn't be checked, so it's shown as a placeholder — ask me to
  regenerate slide 3.`
- **Slide numbers are now 1-based and match the thumbnail ribbon.** The old notices printed the raw
  0-based position, so the issue's own example "Slide 1 … (build_reviewer: …)" was really the second
  slide. A user who typed "regenerate slide 1" would have rebuilt the wrong slide.
- Three other user-visible 0-based lines are also fixed (ruling R2):
  - the persisted architect summary "Rebuilding 1: [2]." now reads "Rebuilding slide 3."
  - the SSE-only "Slide N reviewed" progress line
  - the SSE-only "Slide N fix reviewed" progress line

  Data stays 0-based everywhere: event metadata, `error_state`, the log and the row marker.

**AC2: technical detail stays available but is not the headline.**

- **Row.** The `info` chat row stores `metadata={"details": {"stage", "error", "request_id"}}` in the
  existing `metadata_json` column. No migration.
  - `error` is the exception class name, or a fixed code: `model_temporarily_unavailable` for
    transient faults, the stall reason for a stalled slide.
  - It is never exception text, and never a `PersistedRuntimeError` subclass name (the #271 posture).
- **Polling, the production transport.** `msg_to_stream_event` forwards `metadata: {"details": …}`
  for notice rows only, and `metadata: null` for every other row. It never forwards a row's whole
  metadata, because a tool row's metadata carries its input.
- **Reload.** `GET /api/sessions/{id}` already returned `metadata`.
- **SSE.** The placeholder and foreman `ERROR` events and the deck-review `ASSISTANT` event carry
  `metadata.details`. The pre-commit placeholder event uses the short `headline`, because no
  placeholder exists yet when it is sent.
- **Frontend.** Under assistant messages that carry details, `Message.tsx` shows a collapsed native
  `<details>` disclosure labelled **Details** (Stage, Error, Request ID). This works on reload,
  polling and SSE. Old rows render exactly as before.
- **Logs.** Each notice writes one WARNING:
  `graph_failure_notice kind=… stage=… error=… positions=… request_id=… session_id=…`.
  - The fields are in the **message** because production logs only `%(message)s`
    (`databricks_client.py:306-310`; `setup_logging` has no caller).
  - `extra=` is kept for any structured handler added later.
  - The existing `logger.exception` tracebacks are unchanged.

**AC3 (optional): one-click "regenerate this slide". Deferred.** See decisions.

## Decisions made on your behalf

1. **No one-click regenerate button (R6).**
   - The placeholder is backend-authored HTML inside the slide iframe, and the frontend has no way to
     detect it.
   - A button on the chat notice would re-fire from stale history after the slide was already
     regenerated.
   - No eval pins whether the architect classifies a bare "Regenerate slide N" as an `edit` of
     position N-1. That is #313's territory.
   - The notice tells the user what to type instead. The architect's 1-indexed message rule and edit
     intent support it, and a misclassified typed request can be rephrased.
2. **Transient faults that fail the whole turn are out of scope (R3).** A transient model fault in the
   builder, in a review with no draft (every edit/regenerate turn), or in the deck review still fails
   the turn with "Pinned graph configuration is unavailable". Changing this changes the #271
   fail-closed contract and needs a product decision. See follow-ups 1 and 2.
3. **The safety-gate wording does not say "links".** The gate blocks external images, videos,
   scripts and stylesheets, and JS such as `eval`, inline handlers and navigation. It does not block
   ordinary `<a href>` hyperlinks. So the action reads "without images or videos from other
   websites".
4. **The SSE progress lines are fixed here** even though #319 works near them. #319's plan uses a
   progress tracker, not these strings. The change is two one-line numbering edits.
   **Heads-up for #319:** `nodes.py` "Slide N reviewed" / "fix reviewed" content is now 1-based.
5. **The log extra key is `request_id`**, the repo's existing convention for the chat request id.
   Positions in the log are labelled `positions=` because they are 0-based.
6. **Disclosure on assistant messages only.** Built from a native `<details>`, which is accessible
   and stateless. No new component or dependency.

## Deviations from the plan

- `unreviewed_slide_notice` takes no `error` argument. The code is fixed by construction, so a class
  name cannot leak (planner, accepted).
- `blocked_unsafe` wording was changed as in decision 3 (PLAN-CORRECTIONS C11; plan updated).
- The foreman notice is guarded with `if outstanding:` because the catalogue refuses an empty list.
  It is unreachable in practice, since `all_positions_committed` returning False implies at least one
  outstanding position. `error_state` is set either way.
- The plan's Task 6 "old strings are gone" grep cannot be empty, and that is expected:
  - The foreman keeps its technical message for `logger.error` and `error_state`.
  - `tests/unit/test_graph_user_notices.py` uses the old strings as negative examples.

## Test evidence

### Baselines (cause-sets)

| Suite | Baseline on `679d2f21` |
|---|---|
| `tests/unit` | 0 failures |
| 6 graph/chat/streaming integration files | 195 passed, 2 skipped |
| Frontend vitest (local Node 26) | 21 failures from two environment causes: `localStorage` is undefined in FindingsE2, SlideViewer and TourViewerBridge tests; one timeout under load. CI uses Node 20. |

### Final run on this branch

| Suite | Result |
|---|---|
| `tests/unit` | 9757 passed, 135 skipped, **0 failed** |
| `tests/integration` (all except `*_postgres.py`) | 504 passed, 16 skipped, **0 failed** |
| Frontend vitest | Only the `localStorage` environment cause remains (20 failed, 1161 passed) |
| `npm run build` | passes |
| ruff and eslint on touched files | no new problems vs baseline |

### Test structure

Tests and code were written by different agents. For each task, an Opus test author wrote the
failing tests and confirmed they were red. A Sonnet implementer made them green. An Opus reviewer
then sabotage-verified them, and the supervisor ran one more sabotage that nobody else had tried.

### Sabotage runs

In each run, a production line was broken, the named tests went red, and the line was restored.

- **Catalogue (Task 1).**
  - Using `position` instead of `position + 1` turned 401 tests red.
  - Mapping `build_reviewer` to `build_failed` turned the mapping, distinctness and catalogue tests
    red.
  - Appending `(stage: error)` to the text turned 366 tests red.
  - Putting "placeholder" in a headline turned the headline test red.
  - `import json` turned the purity test red.
  - The Oxford comma, a dropped `request_id`, a class name instead of the code, an unfrozen
    dataclass and a missing capital all went red.
  - **Two gaps were found and fixed:** the `(` check and an unknown `during` were unguarded.
  - **Supervisor:** disabling the acronym-CamelCase check turned 2 tests red. Reverting the "links"
    wording turned the catalogue pin red.
- **Row and projection (Task 2).**
  - Dropping the `metadata=` kwarg turned the row test red.
  - Forwarding metadata wholesale turned 9 tests red (tool, tour, route).
  - `request_id=None` turned the poll-visibility tests red.
  - Projecting `{"details", **metadata}` turned the details-only test red.
  - **One gap was found and fixed:** a details payload built outside the `try` was not caught.
  - **Supervisor:** reading `metadata.get("detail")` turned 3 tests red.
- **Wiring (Task 3).**
  - Restoring the old f-string turned the site tests and 3 integration tests red.
  - A pre-commit event using `text` instead of `headline` went red.
  - Dropping `error=exc` at the builder turned the safety-gate test red.
  - Leaving the request id out of the log args went red.
  - A foreman bypass of `_surface_failure_notice` turned the AST guard red.
  - A class name in the transient details went red.
  - Swapping `review_skipped` went red.
  - Reverting "Rebuilding …" turned the unit and integration tests red.
  - Reverting `slide_number` in the progress emits went red.
  - `unsafe=True` always turned 14 tests red.
  - `logger.info` instead of WARNING turned 12 tests red.
  - Row text equal to the headline turned 23 tests red.
  - **Two gaps were found and fixed:** the request id was only tested at the builder (now
    parametrised over 6 sites), and never-raise around the log line was untested.
  - **Supervisor:** a foreman `ERROR` event using the headline turned 1 test red.
- **Frontend (Task 4).**
  - Removing `details` from reload or from stream turned the matching test red.
  - Dropping the role check turned the user-message test red.
  - Rendering unconditionally turned 5 tests red.
  - `<details open>`, raw labels and the dt/dd order each went red.
  - **Two gaps were found and fixed:** a disclosure placed inside the content div, and a reload
    `?? msg.metadata` fallback (a tour row was added to the test).
  - **Supervisor:** an SSE-shaped progress event carrying string metadata was added to the stream
    test. A stream `?? event.metadata` fallback then turned it red.

### Whole-branch review

A fresh Opus review returned **MERGE-WITH-FIXES**: no code defects, and two doc corrections, which
were applied. Its writer-by-writer comparison found no drift between the notice writers. It also ruled
that rollback is safe:

- no migration, no GraphState key, no pinned-digest change
- old code ignores `metadata.details`

## CI history

See the PR checks. This section is updated after the final push.

## Not verified locally

- **Playwright.** The new `Failure notice details` test in `frontend/tests/e2e/chat-ui.spec.ts` (a
  mocked `page.route`) never ran locally, because the Chromium headless-shell binary is not installed
  on this machine. The shared browser cache was deliberately left alone. CI's `chat-ui` e2e leg is
  the check.
- **Postgres-marked suites** self-skip locally and run in CI. One of them counts the call sites:
  `test_mixed_release_collaboration_acceptance_postgres.py` requires exactly 4 placeholder call
  lines, each with `mutation=`. That count was verified by grep and by simulating its sweep.
- **No live model or eval run.** Eval spend: USD 0.

## Known gaps and follow-ups

1. **Product decision (R3a).** On a transient fault, should the turn placehold or keep the slide
   instead of failing? This covers:
   - a transient builder fault (`nodes.py` builder)
   - a transient review with no draft: every edit/regenerate turn, which is the turn these notices
     invite
   - a transient deck review after all slides landed
   - the architect's deck-level re-review

   Doing this changes the placeholder call-site count pinned by the mixed-release acceptance test.
2. **Transport decision (R3b).** Show plain-language turn-failure text for transient faults instead
   of "Pinned graph configuration is unavailable". This needs a second typed terminal envelope under
   the #271 fail-closed contract: `job_queue.py`, `chat.py` poll + SSE.
3. **#313.** Add an architect intent eval: "Regenerate slide 3" → `edit` with `target_positions=[2]`.
4. **One-click "Regenerate slide"** on placeholder slides, after 3.
5. **Older technical chat text, out of scope** (it predates this branch):
   - the architect's binding-degrade reply exposes `slide_type=… template_section_index=…`
     (`template_sections.py:481-497`)
   - the data_analyst `no_tool` message prints the raw reason and tool names
   - `SAFETY_RETRY_NOTICE` says "external network/resource access"
6. **Silent fix skip.** A non-transient fixer or fix-review failure lands the original slide with its
   findings and says nothing in chat. The transient path does say it.
7. **SSE (local dev only).**
   - A per-slide `ERROR` event ends ChatPanel's loading state mid-turn and shows only the headline.
   - `kept_*` and standalone deck-write notices appear on SSE only after a reload.
8. **Placeholder slide body.** It still reads "Slide generation failed." (`slide_repository.py:366-368`).
