# Architect Stage Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Subagent execution also requires executing-plans-tellr. Read the task brief and PLAN-CORRECTIONS.md before work.

**Goal:** Let the Agent-mode architect understand “this slide” as the slide on stage when the message was sent.

**Architecture:** Expose a synchronous snapshot getter through the existing SlideViewer ref. Carry optional `stage_slide: {slide_number, slide_id?}` through both transports and the queue into turn-scoped graph state. Resolve the stable ID against the current deck’s rows, then use slide_numbering to give the architect a content-only stage entry; never send the ID to the model.

**Tech Stack:** Existing React/TypeScript, FastAPI/Pydantic, LangGraph, Vitest and pytest. No dependencies or database migrations.

**Spec:** User-approved behavior on 2026-11-12: use the slide on stage at send time, not a later navigation selection. Explicit slide references and whole-deck requests take precedence. Agent mode only; Legacy is frozen. Builder decisions from fresh-context review are recorded below.

## Implementation handoff and integration follow-up (2026-11-12)

Implementation, independent reviews and targeted live validation completed: train 6/6; held-out 6/6 production checks and 5/5 trusted judges, with the user explicitly approving deterministic-only validation for the untrusted move judge. Conservative total model estimate: USD 7.881 of the USD 15 cap. At the initial uncommitted handoff, the backend had 16,021 passing tests, 127 skips and one HEAD-comparison guard failure; frontend 3,479 passed and build/typecheck passed. No integration action had then been authorized. See `evals/README.md` and the plan’s SDD verification ledger.

The user subsequently authorized opening a PR for CI and standing up a fresh devloop instance in parallel, iterating until CI is green and the instance is healthy. This authorizes the necessary feature-branch commits, pushes and dev pre-release publication/deployments, not merging the PR or deploying production. The user selected `tellr-dev-oauth`; no PAT access is authorized. The HEAD-comparison guard must be rechecked after committing, and CI/deployment outcomes recorded in the execution ledger.

## Global Constraints

- Agent mode only. Do not reinterpret or refactor Legacy slide_context handling.
- Capture synchronously before ensureGraphCapableRoot() or any other await.
- Slide Number is 1-based; map to Slide Position with slide_numbering, never arithmetic.
- Append optional arguments with backward-compatible defaults; callers without a stage keep working.
- Never include session, user, turn, release or database slide identifiers in model-facing stage data.
- Use this worktree’s .venv through uv run; no global dependency changes.
- Do not commit, push, deploy or alter live Graph Releases without user instruction.

## Review Focus

1. Navigation during a pending persistence await does not change the captured snapshot (Task 1).
2. Empty decks, hidden Spec view, historical previews and session switches do not supply a stale stage (Task 1).
3. Reorder preserves the staged slide’s identity; deletion/ambiguous identity never falls back to another slide occupying its old number (Task 3).
4. Later turns without a stage never inherit an earlier checkpoint’s stage (Task 3).
5. SSE and polling carry the same snapshot, while explicit targets/whole-deck requests remain authoritative (Tasks 2 and 3).

## Builder Decisions After Fresh Review

- Use the existing imperative ref, not lifted ViewerProvider/global selection state.
- With a visible stage, unqualified local edits such as “make the title bigger” default to that slide. Looking at a slide alone does not request an edit; questions and discussion stay non-mutating.
- Explicit targets and deck-wide scope win. Do not add stage data to slide_references or force target_positions.
- Relative phrases (“next slide”, “previous slide”) use the stage and numbering only when the requested action and existing target are clear. Ask on ambiguity; do not silently interpret “add the next slide” as editing an existing slide.
- Send stable slide_id when available. Resolve it solely among the current session’s committed rows. Missing/deleted/duplicate supplied IDs resolve to no stage, never a fallback number. Without an ID (older slide data), resolve the positive slide_number via slide_numbering.
- Model-facing stage_slide is null or exactly {slide_number, position}, reflecting the identified slide’s current location. A deleted stage means ambiguous local edits need clarification, not another target.
- Spec view and historical preview supply no stage. Copy the snapshot before awaiting; no HTML or identifiers enter model context.
- Existing conversations keep their Graph Release pins. All receive stage data; revised instructions ship through the ordinary packaged-release mechanism, not a silent pin rewrite.

## Baseline

- Frontend: all 3,444 unit tests pass with NODE_OPTIONS=--no-experimental-webstorage. Without this option Node 26’s experimental storage conflicts with jsdom localStorage (31 failures); no source fix required.
- Relevant backend transport/numbering/prompt baseline: 448 passed. Full non-live unit baseline also ran successfully; detailed result in execution ledger.

---

### Task 1: Capture and send the staged slide snapshot

Models: test=opus impl=sonnet

**Files:**
- Modify: frontend/src/types/slide.ts; frontend/src/components/SlideViewer/SlideViewer.tsx; frontend/src/components/Layout/AppLayout.tsx; frontend/src/components/ChatPanel/ChatPanel.tsx; frontend/src/services/api.ts.
- Test: frontend/src/components/SlideViewer/SlideViewer.stageContext.test.tsx; frontend/src/components/ChatPanel/ChatPanel.stageContext.test.tsx; frontend/src/components/Layout/AppLayout.stageContext.test.tsx; frontend/src/services/api.stageContext.test.ts.

**Interfaces:**
- Export StageSlideContext = { slide_number: number; slide_id?: string } from frontend/src/types/slide.ts.
- Add SlideViewerHandle.getStageSlide(): StageSlideContext | undefined and optional ChatPanel prop getStageSlide?: () => StageSlideContext | undefined.
- Append stageSlide?: StageSlideContext to sendChatMessage, streamChat, startPolling and submitChatAsync. Serialize as optional stage_slide JSON.

- [x] Write behavioral tests for next/previous/ribbon selection, empty viewer and remount/reset. Assert the getter returns the displayed slide’s identity and 1-based number, not index/position.
- [x] Write ChatPanel tests proving Agent sends the captured object, Legacy omits it, and stage changes/object mutation during pending ensureGraphCapableRoot cannot retarget the send. Preserve visible user message.
- [x] Add a runtime AppLayout boundary test for viewer-to-chat wiring, Spec/preview suppression and session reset. Existing AppLayoutSpecToggle.test.ts is source-only, not behavioral coverage.
- [x] Test actual SSE/polling JSON from api.ts, with/without stage.
- [x] Run new tests red; feature-absence assertions must fail, not harness/import errors.
- [x] Implement the synchronous getter, Agent-only snapshot copy before first await, AppLayout visibility guard and API transport forwarding. Preserve existing parameter positions and Legacy context.
- [x] Run focused tests, frontend typecheck and full frontend unit suite with the Node option. Report exact commands/results; no commits.

### Task 2: Carry the snapshot through backend transports

Models: test=opus impl=sonnet

**Files:**
- Modify: src/api/schemas/requests.py; src/api/routes/chat.py; src/api/services/job_queue.py; src/api/services/chat_service.py.
- Test: tests/unit/test_stage_slide_wiring.py. Regression: tests/unit/test_engine_mode_wiring.py.

**Interfaces:**
- Add request StageSlideContext with slide_number: strict positive int and slide_id: optional nonempty string (max 256); optional ChatRequest.stage_slide defaults None.
- Graph-only queue payload key stage_slide contains request.stage_slide.model_dump() or None; do not change the Legacy-only sync route.
- Append stage_slide: Optional[Dict[str, Any]] = None through queue helper, ChatService.send_message_streaming and keyword-only _send_message_streaming_graph. send_message_streaming already ends with user_message_persisted; append AFTER it.
- invoke_graph initial receives architect_message and raw stage_slide (including None to clear prior turns).

- [x] Write schema tests for positive numbers, optional/missing ID and stage, invalid number values (0, negative, float, bool, numeric string), empty/oversized ID and malformed objects.
- [x] Write route/worker/service tests exercising SSE, async queue, both context-propagation worker branches and graph entry. Assert both identity and number survive unchanged; Legacy has no stage behavior.
- [x] Run focused tests red, then add minimal forwarding preserving existing positional signatures and Legacy semantics.
- [x] Run uv run pytest tests/unit/test_stage_slide_wiring.py tests/unit/test_engine_mode_wiring.py -q and related chat/queue regressions; expected all pass.

### Task 3: Resolve a fresh, identity-safe architect stage reference

Models: test=opus impl=opus

**Files:**
- Modify: src/services/graph/state.py; src/services/graph/builder.py; src/services/graph/nodes.py; src/domain/slide_numbering.py; src/services/agent_model_payload.py; tests/fixtures/model_payload_keys.py; src/core/skills/architect.py; src/services/agent_definition_manifest_v1.py; CONTEXT.md.
- Test: tests/unit/test_slide_numbering.py; tests/unit/test_architect_stage_context.py; tests/unit/test_architect_edit_prompt.py; tests/unit/test_graph_definition_manifest.py; tests/unit/test_packaged_release_loader.py.

**Interfaces:**
- Declare GraphState.stage_slide: Optional[dict] with JSON-native scoped wrapper; register stage_slide: None in state._EMPTY_FOR.
- invoke_graph wraps the raw incoming stage with scoped(turn_id, value) EVERY invocation, omission included. architect_node reads only through scoped_vals.
- Extend architect_slide_payload(..., *, describe_only=False, stage_slide: Mapping | None = None, slide_rows: Sequence[Mapping] | None = None). Keep existing callers valid; widen return type for nullable object.
- Resolve supplied stable ID uniquely among slide_rows, get its current position, and find the matching slide_numbering entry. No ID: look up supplied slide_number. Invalid/missing identity or describe_only: stage_slide=None.
- Payload retains existing keys and adds stage_slide (null or exactly {slide_number, position}) to both allowlists.

- [x] Write mapping tests with positions [3, 8, 15], reorder with stable identity, deletion/duplicate/foreign identity refusing number fallback, invalid/no-stage/describe-only cases, and unchanged explicit slide_references.
- [x] Capture actual architect model payloads. Exercise a compiled/checkpointed graph boundary across two invoke_graph calls; second call without stage clears the first. Retry and analyst loop retain the same turn’s stage. Raw IDs must not reach the model.
- [x] Run tests red, then implement scoped channel, per-invocation reset, session-row mapping and sanitized payload. Never force edit targets from selection.
- [x] Update authored architect instructions and its packaged prompt together: local edit default, deictic phrases, explicit/deck-wide precedence, non-mutating questions, ambiguity/no-stage clarification, and relative-reference boundaries. Verify actual assembled/shipped prompt; do not claim literal-text checks prove live model behavior.
- [x] Preserve every other manifest field/role; update only intentionally changed prompt hash pins. No schema/protected identity or persisted pin changes. Document Stage Slide in CONTEXT.md.
- [x] Run focused graph/numbering/prompt/payload/shipping tests, then full non-live backend unit suite and full frontend suite/typecheck/build. Diagnose failure causes, not counts.
- [x] Sabotage forwarding and per-turn reset separately; verify targeted tests go red, restore, verify green. Reviewer uses different sabotage targets.
- [x] Run one whole-branch Tellr code review, address findings and verify. Leave work uncommitted; preserve ledger until integration is chosen.

### Task 4: Whole-branch fix wave and stage-aware model validation

Models: test=opus impl=opus

**Authority:** Whole-branch review I1/I2/M1. User approved adding stage-aware eval cases and live train/held-out validation capped at USD 15, selected the tellr-dev workspace, and explicitly chose OAuth instead of PAT. No live calls until OAuth login succeeds; no PAT access. No tuning/search or reference/scorer changes are authorized.

**Files:** Architect stage prompt/packaged manifest and matching pins/lifecycle recording; AppLayout comment; image-tool eval generator/8 payloads/parity test; six new stage-context cases on each architect split, reproducible case-authoring helper and focused tests/key/case-list pins. Existing case/reference/calibration content and harness scoring stay unchanged except image payload stage_slide:null parity alignment.

**Interfaces:** New stage cases named stage_restyle_deck, stage_explicit_other, stage_deictic_title, stage_unqualified_title, stage_question and stage_move. Payload stage_slide is a non-null {slide_number, position} from the relevant split's deck. Existing production model schema/operation semantics remain authoritative.

- [x] Independent test author adds failing image-pack production-key parity and stage-case coverage tests; defines six train/six held-out references/calibrations using each split’s own fixtures. Do not alter existing references, calibrations, judges, scorers or prices.
- [x] One fix implementer handles I1/I2/M1 together: wire/reproduce the new case definitions, align image-tool payloads, clarify that requests about a kind of element across the deck remain deck-wide while a single slide’s content edit defaults to stage, update source/packaged prompt and exact matching pins, and correct the outdated Spec-view comment. Preserve independently authored tests.
- [x] Verify changed cases/schema/scorers and old case contents locally; run affected suites. Retain the known uncommitted-HEAD guard unchanged.
- [x] Calibrate and run architect validation only, using the user-authenticated tellr-dev-oauth profile, synthetic fixtures, existing scoring and a running total of est_cost_usd. Stop before the USD 15 cap; held-out results aggregate only and no iterative held-out tuning. No model-setting change or optimisation sweep.
- [x] One scoped final re-review of the entire fix wave, then final verification and honest report of any residual findings, live-model results and the HEAD-sensitive guard. No commits/push/deploy without user instruction.
