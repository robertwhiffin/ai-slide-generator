# Mixed-release Collaboration Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: use executing-plans-tellr and superpowers:subagent-driven-development task-by-task. Before Task 1, write .superpowers/issue-262-plan-corrections.md, rebase onto final reviewed #261, and re-probe the gate below. Reviewers sabotage a distinct guarded production line, prove RED, restore, then prove GREEN.

**Goal:** Pin every remaining graph-capable conversation creation path and durably attribute every shared-deck mutation to its actor session and exact pinned Graph Release.

**Architecture:** #261's immutable session pin remains the only runtime release input. A new append-only mutation-event aggregate and one transactional attribution seam capture root deck/session separately from actor session/release. Graph state carries actor release; existing deck-owner resolution carries root identity. A privacy-safe grouped API drives accessible mixed-version UI/history.

**Tech Stack:** Python 3.11, SQLAlchemy 2, PostgreSQL/Lakebase, FastAPI, Pydantic v2, LangGraph, React 19, TypeScript, Vitest, Playwright, pytest.

**Spec:** docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md §5.6/§7.3; GitHub #262; docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md.

## Global constraints and rulings

- #262 is semantically blocked only by fully reviewed #261. It may use a reviewed #260+#261+#263 integration base, but #263 is not a behaviour dependency. Do not wait for #264–#266 or edit their schema-overlay, assembly, endpoint/editor, or Graph Draft writer seams.
- The supplied 000ad5937 contains only partial #261. Before implementation rebase to final reviewed #261, compare every declared interface below to source, write/review .superpowers/issue-262-plan-corrections.md for drift, and treat it as override. Preflight is not proof.
- Shared pyenv only: start/end each task with test ! -d .venv, which python, python --version; use python -m pytest; never uv, pip, install, or venv.
- Consume #261's immutable UserSession.graph_release_id, lock_active_graph_release, active-publication lock, persisted runtime, GraphState.graph_release_id, safe identity sink, version projection, GraphVersionStatus, and Start-latest. Existing pins never change.
- Graph capability is exact: chat auto-create is capable iff initiating selects_graph_engine(message) is true; contributors are capable at creation; duplicate is capable iff current carried_marker is true. Duplicate locks current active and never copies source pin. Null remains legacy/no-graph, never current active.
- Do not alter engine selection: a contributor's own earliest marker selects its graph turn, its own pin supplies its graph runtime, and _get_deck_owner_session continues to select the owner's deck. Monolith/MCP/tour/non-marker paths retain null provenance.
- Event evidence is authoritative, append-only, and distinct from application identity logs. No MLflow/Lakebase trace replacement. Events retain indefinitely, use ON DELETE RESTRICT, and PostgreSQL forbids UPDATE/DELETE.
- Event fields only: root session/deck IDs, actor session ID, nullable exact actor release/version, operation, object type/ID, timestamp, principal. Never payload/prompt/output/HTML/chat text/user ID. Pin/version are both null or both non-null; never infer from root/active.
- Every PostgreSQL module begins pytestmark = pytest.mark.postgres, is named in integration-graph, has an enrollment guard, and has zero skips.

## Mandatory rebase/re-probe gate

- [ ] Rebase onto final reviewed #261 (and optionally reviewed #263 integration); record base, #261 final commit and topology resolution in corrections.
- [ ] Probe signatures/callers for lock_active_graph_release, load_conversation_pin, version projection, identity sink, AgentRuntime.run, invoke_graph, graph state, all session creators, chat auto-create/fallback, save_slide_deck, SlideWriter, deck-level writer, direct CRUD/restore, and sweeper.
- [ ] Re-run #261 gate and compare failure/skip/warning causes, not counts:

    python -m pytest -q -m postgres tests/integration/test_conversation_pin_migration_postgres.py tests/integration/test_conversation_pin_creation_postgres.py tests/integration/test_persisted_graph_runtime_failures_postgres.py tests/integration/test_conversation_pin_acceptance_postgres.py
    python -m pytest -q tests/unit/test_conversation_pin_creation.py tests/unit/test_session_duplicate.py tests/unit/test_duplicate_session_carries_spec.py tests/unit/test_slide_writer.py tests/unit/test_deck_level_writer.py tests/integration/test_save_slide_deck_dual_write.py tests/integration/test_graph_mode_turn.py
    cd frontend && npm test -- --run && npx tsc --noEmit

## Exhaustive writer contract

| Writer | Content mutation | Required event | Actor/release |
| --- | --- | --- | --- |
| SessionManager.save_slide_deck | monolith/full deck + rows/prune | save_deck and save_deck_slides/deck | requesting session/pin |
| SlideWriter.write_slide/delete_slide | Builder/reviewer/fixer/placeholder row | write_slide or delete_slide/slide | graph actor/state pin |
| write_deck_level_columns | architect/reviewer deck columns | write_deck_level/deck | graph actor/state pin |
| ChatService insert/update/duplicate/delete/reorder | direct deck changes | named operation/deck | requesting session/pin |
| restore_version | deck plus materialized rows | restore_version/deck | requesting session/pin |
| run_arc_review | describe-only graph writer | normal graph event(s) | root actor/nullable pin |
| startup backfill, dirty claims, verdict-only, export metadata | non-content state | no event | none |

Before merge rerun rg for SessionSlideDeck(, SessionSlide(, save_slide_deck, write_deck_level_columns, write_slide, delete_slide, restore_version, insert_slide, update_slide, duplicate_slide, reorder_slides; any discovered production content writer must use this seam and be added to this table/test.

### Task 1: Append-only aggregate, migration, and attribution seam

**Files:**
- Create: src/services/shared_deck_attribution.py, tests/unit/test_shared_deck_attribution.py, tests/integration/test_shared_deck_mutation_migration_postgres.py
- Modify: src/database/models/session.py, src/core/database.py, .github/workflows/test.yml, tests/unit/test_database_migrations.py, tests/unit/test_ci_collects_integration_tests.py

**Interfaces:**

    class SharedDeckMutationEvent(Base):
        __tablename__ = "shared_deck_mutation_event"
        # non-null root_session_id/root_deck_id/actor_session_id/operation/object_type/occurred_at;
        # nullable pair graph_release_id/graph_version
    @dataclass(frozen=True, slots=True)
    class MutationActor:
        actor_session_id: str
        graph_release_id: int | None
        principal: str | None
    def record_shared_deck_mutation(db: Session, *, requesting_session: UserSession,
        deck_owner: UserSession, deck: SessionSlideDeck, actor: MutationActor,
        operation: Literal["save_deck","save_deck_slides","write_slide","delete_slide",
        "write_deck_level","insert_slide","update_slide","duplicate_slide",
        "reorder_slides","restore_version"], object_type: Literal["deck","slide"],
        object_id: str | None) -> SharedDeckMutationEvent: ...

- [ ] Write RED unit tests for root R1, contributor R2 on root R1, null actor, pin mismatch, missing actor/release, illegal operation/object pair, and field privacy. Assert root comes only from deck_owner; release/version only from actor row.
- [ ] Write marked PostgreSQL RED migration test from pre-table schema. Run _run_migrations twice; inspect named RESTRICT FKs, pair/group indexes, pair-null CHECK, and trigger. Insert then direct SQL UPDATE/DELETE must fail. Enroll/guard it before implementation.
- [ ] Add model with CHECK ((graph_release_id IS NULL) = (graph_version IS NULL)), closed operation/object checks, non-cascade relationships, grouping indexes root_deck_id+actor_session_id+graph_release_id and root_session_id+actor_session_id+graph_release_id+occurred_at. Add idempotent _migrate_shared_deck_mutation_events immediately after #261 pin migration; SQLite creates table/indexes, PostgreSQL also creates UPDATE/DELETE-rejecting trigger.
- [ ] Implement seam with no nested transaction/commit. Load actor in caller transaction, require supplied actor equals requester, resolve only GraphRelease.id == actor.graph_release_id, flush mutation first, then write root IDs from deck owner and actor IDs/version from actor. Never query active/latest.
- [ ] Run RED/GREEN:

    python -m pytest -q tests/unit/test_shared_deck_attribution.py tests/unit/test_database_migrations.py
    python -m pytest -q -m postgres tests/integration/test_shared_deck_mutation_migration_postgres.py
    python -m pytest -q tests/unit/test_ci_collects_integration_tests.py

- [ ] Sabotage release resolution to use owner pin; contributor-R2 test fails. Restore and commit: git commit -m "feat: add append-only shared deck attribution".

### Task 2: Remaining creation locks

**Files:**
- Modify: src/api/routes/chat.py, src/api/services/chat_service.py, src/api/services/session_manager.py, src/api/routes/sessions.py, unit tests for chat/duplicate/contributors
- Create: tests/integration/test_mixed_release_creation_postgres.py
- Modify: workflow and CI enrollment guard

**Consumes:** #261 lock helper. **Produces:** new capable actor pins before commit.

- [ ] RED-test both _maybe_create_session creation branches and ChatService fallback marker/non-marker; contributor R2 under root R1; contributor idempotency; graph-marker duplicate R2 from source R1; non-marker duplicate null; source never repins/copies; missing-active 503 only at relevant HTTP boundary.
- [ ] Set graph_capable=selects_graph_engine(request.message) solely in chat auto-create/fallback calls. In contributor creation return existing first, then lock before flush. In duplicate compute existing carried_marker; only when true lock immediately before UserSession construction; assign lock ID, never source pin. Do not alter marker rule, mode resolver, deck-owner semantics, MCP/tour/monolith.
- [ ] Map only ActiveGraphReleaseUnavailableError on chat/contributor/duplicate routes to #261's 503 detail.
- [ ] Marked PostgreSQL test parameterizes explicit root, chat auto-create, contributor, duplicate. For every path force both orderings: publication-first holds R1, creator blocks (third connection sees Lock), closes R1/inserts R2, retry pins exact R2 with [R1,R1]; creation-first flushes R1 target while publisher waits, commits R1 then publishes R2. Assert exact R1/R2/source/actor/root identities, versions, waiter helper evidence, zero skips.
- [ ] Sabotage duplicate to source-pin; R1-source/R2-active assertion fails. Restore, run focused unit/Postgres/CI tests, commit feat: pin mixed-release conversation creators.

### Task 3: One seam for every deck writer

**Files:**
- Modify: src/api/services/session_manager.py, src/api/services/slide_repository.py, src/api/services/deck_level_writer.py, src/api/services/chat_service.py, src/services/graph/nodes.py, src/services/spec_sync.py
- Create: tests/integration/test_shared_deck_mutation_attribution.py
- Modify: writer, graph, direct-route, restore, sweeper tests

**Consumes:** Task 1 seam and #261 state pin. **Produces:** same-transaction event rows for every contract-table writer.

- [ ] RED integration executes each production writer as root R1, contributor R2, and null legacy where applicable. Assert exact root deck/session, actor, exact actor release/version, principal, operation/object/id, count/order. Cover monolith save, graph row+deck writers, direct CRUD/reorder, restore, and sweeper.
- [ ] Extend only explicit signatures: SlideWriter.write_slide/delete_slide(..., mutation_actor: MutationActor | None = None) and write_deck_level_columns(..., mutation_actor=...). Graph nodes construct actor from state session_id, graph_release_id, initiated_by; preserve through #261 Send/retry/rereview. Direct/monolith/restore construct from requester/current principal. Reject explicit actor release differing from persisted actor pin.
- [ ] save_slide_deck flushes then records save_deck; with deck dict records save_deck_slides. Slide writer flushes before stable slide-ID event. Deck-level writer flushes/create then records. Direct higher-level ChatService operation records exactly once and suppresses underlying generic double-count. Use no attribution columns on content tables.
- [ ] Backfill, dirty claims, verdict-only, export metadata make no event. Sweeper is a normal graph write and uses root actor/its nullable pin.
- [ ] Sabotage deck-level seam call; graph deck changed/no event test fails. Restore; run focused writer/graph/direct/restore/sweeper tests; commit feat: attribute every shared deck mutation.

### Task 4: Trace root/actor and grouped collaboration API

**Files:**
- Create: src/services/collaboration_history.py, tests/unit/test_collaboration_history.py, tests/integration/test_collaboration_history_api_postgres.py
- Modify: src/services/agent_runtime_identity.py, src/services/agent_runtime.py, graph builder/state, session_manager.py, sessions route, runtime/version/API tests, workflow/CI guard

**Interfaces:**

    @dataclass(frozen=True)
    class AgentInvocationIdentity:
        graph_version: int; graph_release_id: int; agent_key: str
        agent_definition_revision_id: int; content_hash: str
        root_session_id: str; actor_session_id: str
    @dataclass(frozen=True)
    class CollaborationReleaseGroup:
        actor_session_id: str; actor_name: str | None
        graph_version: int | None; mutation_count: int; last_mutation_at: datetime
    def get_collaboration_history(db: Session, requested_session_id: str) -> tuple[bool, bool, list[CollaborationReleaseGroup]]: ...

- [ ] RED runtime test for contributor R2 graph on owner R1: sink root=owner, actor=contributor, release=R2; fanout/retry preserve IDs. Capture safe log: old safe identity/outcome/error fields plus only root/actor IDs, no principal/content/prompt/payload/output.
- [ ] In invoke_graph load actor pin via #261, resolve owner once, overwrite hostile initial root/actor IDs, declare/copy them in all Send payloads. IDs never select release; actor state pin does. Extend identity sink only—no MLflow/Lakebase trace.
- [ ] RED API/history test has root×A×R1, root×B×R2, legacy/null. Summary warning true only for two persisted non-null versions; legacy is separate. Group by actor + exact release, newest first, null label Legacy/no graph release; no root-version label. Require authorization first, root-deck constraint, single grouped query/no N+1.
- [ ] Implement sole history/projection module and safe GET collaboration-history; add safe summary to get/list/contributor/duplicate responses. Serialize actor session/name, graph version, count/time, warning and legacy flag only: no internal release ID, pin, prompt, content, user ID.
- [ ] Sabotage grouping by release without actor; two R2 actors collapse and fail. Restore; run focused runtime/API Postgres/CI tests; commit feat: expose mixed-release collaboration history.

### Task 5: Accessible UI and immutable Start-latest

**Files:**
- Create: frontend/src/components/Conversation/MixedReleaseWarning.tsx, its test, frontend/tests/e2e/mixed-release-collaboration.spec.ts
- Modify: frontend/src/services/api.ts, frontend/src/contexts/SessionContext.tsx, frontend/src/components/Conversation/GraphVersionStatus.tsx, frontend/src/components/Layout/AppLayout.tsx, frontend/src/components/Layout/deck-history.tsx, API helper/workflow

- [ ] Extend types and api.getCollaborationHistory with Task 4 safe fields only. Context gets collaboration state, resets in createNewSession, loads on successful switchSession, and honours existing cancellation generation.
- [ ] RED Vitest: two-version warning, no warning same release, explicit legacy wording, visible fetch failure without badge erasure, accessible role=status, focusable disclosure and labelled actor/release rows. Rows must use returned actor/release—not root badge.
- [ ] Implement warning text This shared deck has changes from multiple Graph Versions. Disclosure is Change provenance; each row is actor name/session ID, Graph Version N or Legacy/no graph release, count and timestamp. Render beside #261 badge only for persisted sessions; no connected-user/root inference.
- [ ] Extend Start-latest test: it creates new graphCapable:true session/switches to it and cannot PATCH/copy/repin original R1 history. Graph-marker duplicate has new active R2 while source stays R1.
- [ ] Playwright intercepts R1 owner/R2 contributor event: warning/history visible; click Start latest requires POST graph_capable:true and new ID; revisit original and assert unchanged R1/history. Legacy case never says active.
- [ ] Sabotage rows to use root graphVersion; R1/R2 unit/E2E fails. Restore; run npm test -- --run, npx tsc --noEmit, Playwright chromium spec; commit feat: show mixed-release collaboration.

### Task 6: Cross-writer acceptance and CI gate

**Files:**
- Create: tests/integration/test_mixed_release_collaboration_acceptance_postgres.py
- Modify: workflow, CI guards, matrix/RC graph tests; writer code/tests only if final audit finds an omitted writer.

- [ ] Marked acceptance creates R1 root, R2, capable contributor and marker duplicate; performs contributor graph row/deck writes, null legacy direct write, root write. Assert exact root deck/root session/actor/R1-R2-null identities, immutable pins, grouping/warning, no root inference; include all eight forced creation locking orderings.
- [ ] Execute contract rg audit and add any omitted writer before completion. Assert migration twice/idempotence, RESTRICT retention/trigger, grouped query count, authorization-before-disclosure.
- [ ] Cause-based final runs:

    python -m pytest -q -m postgres tests/integration/test_conversation_pin_migration_postgres.py tests/integration/test_conversation_pin_creation_postgres.py tests/integration/test_mixed_release_creation_postgres.py tests/integration/test_shared_deck_mutation_migration_postgres.py tests/integration/test_shared_deck_mutation_attribution.py tests/integration/test_collaboration_history_api_postgres.py tests/integration/test_mixed_release_collaboration_acceptance_postgres.py
    python -m pytest -q tests/unit/test_shared_deck_attribution.py tests/unit/test_collaboration_history.py tests/unit/test_slide_writer.py tests/unit/test_deck_level_writer.py tests/unit/test_ci_collects_integration_tests.py tests/unit/test_e2e_matrix_covers_specs.py tests/unit/test_rc_graph_ci.py
    cd frontend && npm test -- --run && npx tsc --noEmit && npx playwright test mixed-release-collaboration.spec.ts --project=chromium --workers=1
    git diff --check

- [ ] Sabotage trigger installation; PostgreSQL mutation-protection test goes RED. Restore, run all gates, commit test: verify mixed-release collaboration acceptance.

## Final self-review

- [ ] Map every #262 acceptance criterion to a task/test.
- [ ] Verify creation/mutation tables remain exhaustive; null provenance is never inferred; root, actor and release invariants/migration/idempotency/retention are exact.
- [ ] Confirm all lock tests assert exact R1/R2/source/actor/root and observed waiter PIDs.
- [ ] Confirm contributor marker/pin versus owner deck semantics; monolith/legacy isolation; log/event privacy; no N+1 or authorization leak; warning/history accessibility; Start-latest immutability; CI collection/zero skips.
- [ ] Scan no-placeholder terms, run git diff --check, leave clean.
