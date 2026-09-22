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
- Event evidence is authoritative, append-only, and distinct from application identity logs. No MLflow/Lakebase trace replacement. Events retain indefinitely and PostgreSQL forbids UPDATE/DELETE, but ordinary session/deck deletion remains supported: event FK columns are nullable ON DELETE SET NULL and immutable opaque root-session, root-deck, and actor-session UUID snapshots retain the grouping identity after deletion. No principal or username is stored.
- Event fields only: nullable live root session/deck and actor-session IDs; non-null opaque root-session/root-deck/actor-session snapshot UUIDs; nullable exact actor release/version; operation, object type/ID and timestamp. Never payload/prompt/output/HTML/chat text/principal/user ID. Pin/version are both null or both non-null; never infer from root/active.
- Deletion lifecycle ruling: SessionManager.delete_session and cleanup_expired_sessions delete the live root/actor/deck rows normally; FK SET NULL leaves immutable pseudonymous evidence. The DELETE route reports its existing success after an evidenced deletion. Cleanup isolates every expired session in its own transaction, logs and counts only successful deletes, and continues after an individual unexpected failure; it never rolls back a mixed expiry batch. No event is purged by application cleanup.
- Collaboration history is available only through one authorization-scoped lookup. It joins the requested owner-or-contributor session to its root and puts the full CAN_VIEW predicate in the same SQL WHERE clause; it returns a root only when that caller may view it. No unrestricted requested-session lookup, get_session, _get_session_or_raise, or _get_deck_owner_session may run before it. It exposes no username, principal, raw session ID, UUID, internal release ID, or deleted-session identity: groups receive response-local labels "Contributor 1", "Contributor 2" ordered by opaque actor UUID. Unknown, unauthorized owner, guessed contributor, missing contributor root, and deleted root all return the same 404 detail without an event query.
- Every PostgreSQL module begins pytestmark = pytest.mark.postgres, is named in integration-graph, has an enrollment guard, and has zero skips.

## Mandatory rebase/re-probe gate

- [ ] Rebase onto final reviewed #261 (and optionally reviewed #263 integration); record base, #261 final commit and topology resolution in corrections.
- [ ] Probe signatures/callers for lock_active_graph_release, load_conversation_pin, version projection, identity sink, AgentRuntime.run, invoke_graph, graph state, all UserSession constructors and create_session callers, create_chat_request, chat auto-create/fallback, MCP/tour/direct-service creators, delete_session, cleanup_expired_sessions, save_slide_deck, SlideWriter including commit_placeholder, deck-level writer, direct CRUD/spec rewrites/restore, and sweeper.
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

## Exhaustive creator and lifecycle audit

| Creator/lifecycle seam | Classification and required behaviour | Regression proof |
| --- | --- | --- |
| explicit SessionManager.create_session / POST sessions | capable only when graph_capable true; #261 lock | #261 two-ordering test retained |
| chat route _maybe_create_session, both branches | capable iff initiating message selects graph engine; lock before flush | R1/R2 forced ordering for both branches |
| ChatService send_message and streaming fallbacks | same message-aware capable rule; no unpinned graph fallback | direct-service marker/non-marker test |
| get_or_create_contributor_session | always capable; existing child returns untouched | R2 child/root-R1 ordering and idempotency test |
| duplicate_session | capable iff carried_marker; never copies source pin | R1 source/R2 duplicate ordering test |
| create_chat_request | never creates a graph-capable session: require a pre-existing session; absent session raises SessionNotFoundError and route returns 404 | direct invocation and polling-route regression |
| MCP create_session and tour phase creator | explicit graph_capable false; null pin, no active lock | exact null/tripwire tests |
| delete_session and DELETE route | live rows delete; event FKs SET NULL; opaque evidence remains; route success | real-PG root and actor delete tests |
| cleanup_expired_sessions | one transaction per candidate; successful count only; continues after failure | mixed expiry real-PG test |

The final audit also runs rg for UserSession(, create_session(, create_chat_request, delete_session, cleanup_expired_sessions, commit_placeholder, _placehold_failed_position, build_branch_payload, Send(, rereview_committed_slides and every retry record. Every discovered production seam is classified above before merge.

### Task 1: Append-only aggregate, migration, and attribution seam

**Files:**
- Create: src/services/shared_deck_attribution.py, tests/unit/test_shared_deck_attribution.py, tests/integration/test_shared_deck_mutation_migration_postgres.py
- Modify: src/database/models/session.py, src/core/database.py, .github/workflows/test.yml, tests/unit/test_database_migrations.py, tests/unit/test_ci_collects_integration_tests.py

**Interfaces:**

    class SharedDeckMutationEvent(Base):
        __tablename__ = "shared_deck_mutation_event"
        # nullable live root_session_id/root_deck_id/actor_session_id FKs, each SET NULL;
        # non-null root_session_identity/root_deck_identity/actor_session_identity UUID snapshots;
        # nullable pair graph_release_id/graph_version
    @dataclass(frozen=True, slots=True)
    class MutationActor:
        actor_session_id: str
        graph_release_id: int | None
    def record_shared_deck_mutation(db: Session, *, requesting_session: UserSession,
        deck_owner: UserSession, deck: SessionSlideDeck, actor: MutationActor,
        operation: Literal["save_deck","save_deck_slides","write_slide","delete_slide",
        "write_deck_level","insert_slide","update_slide","duplicate_slide",
        "reorder_slides","restore_version"], object_type: Literal["deck","slide"],
        object_id: str | None) -> SharedDeckMutationEvent: ...

- [ ] Write RED unit tests for root R1, contributor R2 on root R1, null actor, pin mismatch, missing actor/release, illegal operation/object pair, UUID snapshot generation and no principal/name/payload field. Assert root comes only from deck_owner; release/version only from actor row.
- [ ] Write marked PostgreSQL RED migration/lifecycle test from pre-table schema. Run _run_migrations twice; inspect nullable SET NULL live FKs, required UUID snapshot columns, pair/group indexes, pair-null CHECK, and trigger. Direct SQL UPDATE/DELETE must fail, including an attempt to null a still-live FK; delete root/deck and actor rows and assert the only permitted FK SET NULL transition leaves every snapshot/release/version/operation field unchanged. Enroll/guard it before implementation.
- [ ] Add immutable collaboration_identity UUID columns to UserSession and SessionSlideDeck through the registered idempotent migration; backfill random UUIDs exactly once and make fresh rows default UUIDs. Add event CHECK ((graph_release_id IS NULL) = (graph_version IS NULL)), closed operation/object checks, ON DELETE SET NULL FKs, snapshot grouping indexes root_deck_identity+actor_session_identity+graph_release_id and root_session_identity+actor_session_identity+graph_release_id+occurred_at. PostgreSQL trigger rejects DELETE and every UPDATE except a parent-delete FK action: all immutable event/snapshot fields must be byte-for-byte unchanged; each changed live FK must change only non-null to null; and its old parent row must no longer exist. Thus a direct nulling while parent exists fails, while root/deck/actor cascade succeeds. Add idempotent migration immediately after #261 pin migration; SQLite creates table/indexes and seam tests enforce append-only behaviour.
- [ ] Implement seam with no nested transaction/commit. Load actor in caller transaction, require supplied actor equals requester, resolve only GraphRelease.id == actor.graph_release_id, flush mutation first, then snapshot deck_owner/session UUIDs and actor UUID; live IDs are audit links only. Never query active/latest.
- [ ] Run RED/GREEN:

    python -m pytest -q tests/unit/test_shared_deck_attribution.py tests/unit/test_database_migrations.py
    python -m pytest -q -m postgres tests/integration/test_shared_deck_mutation_migration_postgres.py
    python -m pytest -q tests/unit/test_ci_collects_integration_tests.py

- [ ] Sabotage release resolution to use owner pin; contributor-R2 test fails. Separately sabotage FK SET NULL to RESTRICT; root-delete PostgreSQL test fails. Restore and commit: git commit -m "feat: add append-only shared deck attribution".

### Task 1b: Evidence-preserving deletion and expiry lifecycle

**Files:**
- Modify: src/api/services/session_manager.py, src/api/routes/sessions.py, tests/integration/test_shared_deck_mutation_migration_postgres.py
- Create: tests/unit/test_session_cleanup.py, tests/integration/test_shared_deck_mutation_lifecycle_postgres.py
- Modify: .github/workflows/test.yml, tests/unit/test_ci_collects_integration_tests.py

**Consumes:** Task 1 nullable live FKs plus opaque snapshots. **Produces:** ordinary deletion/expiry that keeps immutable evidence and never rolls back unrelated expiry candidates.

- [ ] Write real-PostgreSQL RED cases: delete root that owns an evidenced deck (deck cascade makes live root/deck FKs null, snapshots/release/version/grouping persist); delete evidenced contributor actor (actor FK null, actor snapshot grouping persists); delete a root causing contributor/deck cascade; and one cleanup call with old evidenced root, old evidenced actor, one old deliberately failing candidate and one old ordinary session. Assert route DELETE returns success for valid evidenced root, cleanup returns successful-delete count, surviving candidates are processed, failure is logged/retained, and no event row changes/deletes.
- [ ] Change delete_session only to delete the live session and surface normal SessionNotFoundError; do not purge/anonymize events because snapshots are already pseudonymous. Keep route's authorization, map no FK evidence failure to 500, and return its existing successful response.
- [ ] Rewrite cleanup_expired_sessions to select candidate IDs, then invoke a small _delete_expired_session(session_id) using one get_db_session transaction per ID. Catch SQLAlchemyError per candidate, log only opaque/internal session ID and exception class, continue, and increment only after commit. It must not bulk-delete or share one rollback scope. Do not schedule cleanup.
- [ ] Run RED/GREEN:

    python -m pytest -q tests/unit/test_session_cleanup.py
    python -m pytest -q -m postgres tests/integration/test_shared_deck_mutation_lifecycle_postgres.py tests/integration/test_shared_deck_mutation_migration_postgres.py
    python -m pytest -q tests/unit/test_ci_collects_integration_tests.py

- [ ] Sabotage cleanup back to one transaction around all candidates; mixed-expiry test must show later ordinary candidate not deleted and fail. Restore and commit feat: preserve collaboration evidence through session lifecycle.

### Task 2: Remaining creation locks

**Files:**
- Modify: src/api/routes/chat.py, src/api/services/chat_service.py, src/api/services/session_manager.py, src/api/routes/sessions.py, src/api/mcp_server.py, src/api/routes/tour.py, unit tests for chat/duplicate/contributors
- Create: tests/integration/test_mixed_release_creation_postgres.py, tests/integration/test_conversation_creator_exclusions_postgres.py
- Modify: workflow and CI enrollment guard

**Consumes:** #261 lock helper. **Produces:** new capable actor pins before commit.

- [ ] RED-test both _maybe_create_session creation branches and ChatService fallback marker/non-marker; contributor R2 under root R1; contributor idempotency; graph-marker duplicate R2 from source R1; non-marker duplicate null; source never repins/copies; missing-active 503 only at relevant HTTP boundary. Add a direct create_chat_request absent-session test requiring SessionNotFoundError/route 404 rather than unpinned insertion; add MCP/tour and direct create_session false tests with a lock-helper tripwire proving null pins/no lock.
- [ ] Set graph_capable=selects_graph_engine(request.message) solely in chat auto-create/fallback calls. In contributor creation return existing first, then lock before flush. In duplicate compute existing carried_marker; only when true lock immediately before UserSession construction; assign lock ID, never source pin. Change create_chat_request to require the route-created session rather than constructing UserSession. Make MCP/tour spell graph_capable=False. Do not alter marker rule, mode resolver, deck-owner semantics.
- [ ] Map only ActiveGraphReleaseUnavailableError on chat/contributor/duplicate routes to #261's 503 detail.
- [ ] Marked PostgreSQL test parameterizes explicit root, both chat creation branches, ChatService fallback, contributor, duplicate. For every capable path force both orderings: publication-first holds R1, creator blocks (third connection sees Lock), closes R1/inserts R2, retry pins exact R2 with [R1,R1]; creation-first flushes R1 target while publisher waits, commits R1 then publishes R2. Assert exact R1/R2/source/actor/root identities, versions, waiter helper evidence, zero skips. The exclusion file verifies create_chat_request cannot create, and MCP/tour/direct false creation remains null in real PostgreSQL.
- [ ] Sabotage duplicate to source-pin; R1-source/R2-active assertion fails. Separately restore UserSession construction in create_chat_request; direct absent-session test fails. Restore, run focused unit/Postgres/CI tests, commit feat: pin mixed-release conversation creators.

### Task 3: One seam for every deck writer

**Files:**
- Modify: src/api/services/session_manager.py, src/api/services/slide_repository.py, src/api/services/deck_level_writer.py, src/api/services/chat_service.py, src/services/graph/nodes.py, src/services/graph/routers.py, src/services/spec_sync.py
- Create: tests/integration/test_shared_deck_mutation_attribution.py
- Modify: tests/unit/test_slide_writer.py, tests/unit/test_deck_level_writer.py, tests/unit/test_graph_nodes.py, tests/unit/test_graph_routers.py, tests/integration/test_save_slide_deck_dual_write.py, tests/integration/test_graph_mode_turn.py, tests/integration/test_insert_slide_route.py, tests/integration/test_task7_verification_and_restore.py, tests/integration/test_sweeper_describe_only.py

**Consumes:** Task 1 seam and #261 state pin. **Produces:** same-transaction event rows for every contract-table writer.

- [ ] RED integration executes each production writer as root R1, contributor R2, and null legacy where applicable. Assert exact root deck/session, actor, exact actor release/version, no principal, operation/object/id, count/order. Cover monolith save, graph row+deck writers, direct CRUD/reorder, restore, sweeper, builder/reviewer/fixer failures, and stalled placeholder.
- [ ] Define and use the one explicit context:

    @dataclass(frozen=True, slots=True)
    class DeckMutationContext:
        actor: MutationActor
        operation: MutationOperation
        object_type: Literal["deck", "slide"]
        object_id: str | None = None
        suppress_nested_events: bool = False

    def save_slide_deck(..., mutation: DeckMutationContext | None = None) -> dict: ...
    def write_deck_level_columns(..., mutation: DeckMutationContext | None = None) -> dict: ...
    def SlideWriter.write_slide(..., mutation: DeckMutationContext | None = None) -> None: ...
    def SlideWriter.commit_placeholder(..., mutation: DeckMutationContext | None = None) -> None: ...

- [ ] Extend explicit signatures for SlideWriter.write_slide, delete_slide, commit_placeholder and write_deck_level_columns. _placehold_failed_position accepts mutation and passes it to commit_placeholder; builder, build_reviewer, fix_reviewer and placeholder_node construct/pass the branch/state actor. Test contributor R2/root R1 and legacy-null for all four paths. Sabotage only the commit_placeholder forwarding; every placeholder actor assertion must fail while ordinary write tests remain green.
- [ ] For each direct ChatService insert/update/duplicate/delete/reorder, create DeckMutationContext with its named operation before calling its first durable writer. Pass it to save_slide_deck or SlideWriter so record_shared_deck_mutation happens inside that writer's existing transaction; context suppresses save_deck, save_deck_slides and write_deck_level generic events. If event insertion fails, propagate the exception: the writer transaction rolls back content and no spec rewrite/savepoint executes. The later _rewrite_deck_spec_slides remains explicitly best-effort as current code: a spec failure is logged, content plus its one named event stay committed, and spec-dirty recovery remains scheduled. Its write_deck_level call receives no context and creates no second event.
- [ ] Test event-insert failure independently for insert, update, duplicate, delete and reorder: original rows/deck version remain unchanged, zero event rows, no savepoint/spec rewrite call. Test spec-rewrite failure separately: content commits, exactly one named event exists, no generic save_deck/write_deck_level event exists, and the operation returns its current successful response. For direct paths with SlideWriter, the same context reaches its first row mutation rather than a post-operation transaction.
- [ ] save_slide_deck flushes then records its supplied context; monolith uses save_deck and optional save_deck_slides. Slide writer flushes before stable slide-ID event. Deck-level writer flushes/create then records. Direct contexts make exactly one named event. Use no attribution columns on content tables.
- [ ] Backfill, dirty claims, verdict-only, export metadata make no event. Sweeper is a normal graph write and uses root actor/its nullable pin.
- [ ] Sabotage deck-level seam call; graph deck changed/no event test fails. Separately sabotage direct context propagation to None; exact-one named/direct rollback tests fail. Restore; run focused writer/graph/direct/restore/sweeper tests; commit feat: attribute every shared deck mutation.

### Task 4: Trace root/actor and grouped collaboration API

**Files:**
- Create: src/services/collaboration_history.py, tests/unit/test_collaboration_history.py, tests/integration/test_collaboration_history_api_postgres.py
- Modify: src/services/agent_runtime_identity.py, src/services/agent_runtime.py, src/services/graph/builder.py, src/services/graph/state.py, src/services/permission_service.py, src/api/services/session_manager.py, src/api/routes/sessions.py, tests/unit/test_collaboration_history.py, tests/unit/test_deck_permission_routes.py, tests/integration/test_api_routes.py, workflow/CI guard

**Interfaces:**

    @dataclass(frozen=True)
    class AgentInvocationIdentity:
        graph_version: int; graph_release_id: int; agent_key: str
        agent_definition_revision_id: int; content_hash: str
        root_session_id: str; actor_session_id: str
    @dataclass(frozen=True)
    class CollaborationReleaseGroup:
        actor_label: str
        graph_version: int | None; mutation_count: int; last_mutation_at: datetime
    @dataclass(frozen=True)
    class AuthorizedCollaborationRoot:
        root_session_id: int
        root_deck_id: int
    def authorized_collaboration_root(db: Session, *, requested_session_id: str,
        permission_context: PermissionContext) -> AuthorizedCollaborationRoot | None: ...
    def get_collaboration_history(db: Session, *, root: AuthorizedCollaborationRoot) -> tuple[bool, bool, list[CollaborationReleaseGroup]]: ...

- [ ] RED runtime test for contributor R2 graph on owner R1: sink root=owner, actor=contributor, release=R2. Instrument every handoff: foreman_router Send("builder", build_branch_payload(state, position)); build_branch_payload; builder unsafe-output retry_payload; build_reviewer Send("build_reviewer", dict(record)) re-fan; fixer retry_payload; fix_reviewer record; rereview_committed_slides(session_id, spec, brand, graph_release_id, root_session_id, actor_session_id). Exercise unsafe-output retry, surfaced finding to fixer/fix-reviewer, and re-review; assert immutable root/actor/release/version in every recorded payload, runtime identity-sink call and downstream row/deck event.
- [ ] In invoke_graph load actor pin via #261, resolve owner once, overwrite hostile initial root/actor IDs, declare/copy them in all Send payloads and retry/fix/re-review records. IDs never select release; actor state pin does. Extend identity sink only—no MLflow/Lakebase trace. Add a distinct sabotage that removes root/actor/release from the reviewer dict(record) re-fan; only the re-review identity test must go RED.
- [ ] RED API/history test has root×A×R1, root×B×R2, legacy/null. Summary warning true only for two persisted non-null versions; legacy is separate. Group internally by opaque actor UUID + exact release, newest first, assign response-local Contributor 1/Contributor 2 labels, null label Legacy/no graph release; no root-version label. Query is root-deck constrained and one grouped query/no N+1.
- [ ] Implement authorized_collaboration_root as the only endpoint entry lookup. Use requested = aliased(UserSession) and root = aliased(UserSession), join root on root.id == coalesce(requested.parent_session_id, requested.id), require root.parent_session_id IS NULL and a new SQL CAN_VIEW predicate extracted from the permission service's ownership, direct-contributor, profile/group, and global-share rules. The select returns only root.id and root.slide_deck.id, has requested.session_id == requested_session_id and the CAN_VIEW predicate in its WHERE, and returns None for every no-row condition. The route calls it once; if None, return the identical 404 before calling get_collaboration_history. It must not call get_session, _get_session_or_raise, _get_deck_owner_session, _get_root_session_or_400, or an unrestricted requested/root query.
- [ ] Implement sole history/projection module with get_collaboration_history accepting only AuthorizedCollaborationRoot, never a requested session ID. Add safe summary to get/list/contributor/duplicate only through the same authorization-scoped resolver. Serialize actor_label, graph version, count/time, warning and legacy flag only: no actor session/name, UUID, internal release ID, pin, prompt, content, user ID or principal.
- [ ] Tests run owner, CAN_VIEW, CAN_EDIT, CAN_MANAGE authorized cases and unknown session, unauthorized owner, guessed contributor, missing contributor root, and deleted root no-row cases. For every denied/no-row case, spy/tripwire old direct lookup/root-resolution seams get_session, _get_session_or_raise, _get_deck_owner_session and _get_root_session_or_400; assert zero calls, authorization-scoped join returns None, event/history query is never invoked, and response is byte-for-byte same 404 detail. Authorized cases prove the scoped join returns exactly one root before the one grouped event query.
- [ ] Sabotage grouping by release without opaque actor identity; two R2 actors collapse and fail. Independently replace authorized_collaboration_root with get_session plus root resolution; unauthorized/guessed-ID tripwire must fail before any history query. Restore; run focused runtime/API Postgres/CI tests; commit feat: expose mixed-release collaboration history.

### Task 5: Accessible UI and immutable Start-latest

**Files:**
- Create: frontend/src/components/Conversation/MixedReleaseWarning.tsx, its test, frontend/tests/e2e/mixed-release-collaboration.spec.ts
- Modify: frontend/src/services/api.ts, frontend/src/contexts/SessionContext.tsx, frontend/src/components/Conversation/GraphVersionStatus.tsx, frontend/src/components/Layout/AppLayout.tsx, frontend/src/components/Layout/deck-history.tsx, API helper/workflow

- [ ] Extend types and api.getCollaborationHistory with Task 4 safe fields only. Context gets collaboration state, resets in createNewSession, loads on successful switchSession, and honours existing cancellation generation.
- [ ] RED Vitest: two-version warning, no warning same release, explicit legacy wording, visible fetch failure without badge erasure, accessible role=status, focusable disclosure and labelled actor/release rows. Rows must use returned actor_label/release—not root badge—and assert no username, raw session ID, UUID or principal reaches DOM, accessibility tree, client type or mock request.
- [ ] Implement warning text This shared deck has changes from multiple Graph Versions. Disclosure is Change provenance; each row is server-provided Contributor N, Graph Version N or Legacy/no graph release, count and timestamp. Render beside #261 badge only for persisted authorized sessions; no connected-user/root inference or identity recovery.
- [ ] Extend Start-latest test: it creates new graphCapable:true session/switches to it and cannot PATCH/copy/repin original R1 history. Graph-marker duplicate has new active R2 while source stays R1.
- [ ] Playwright intercepts R1 owner/R2 contributor event with only opaque labels: warning/history visible; click Start latest requires POST graph_capable:true and new ID; revisit original and assert unchanged R1/history. Legacy case never says active. Intercept a 404 history response for a guessed contributor and assert generic unavailable state without a name/version disclosure.
- [ ] Sabotage rows to use root graphVersion; R1/R2 unit/E2E fails. Restore; run npm test -- --run, npx tsc --noEmit, Playwright chromium spec; commit feat: show mixed-release collaboration.

### Task 6: Cross-writer acceptance and CI gate

**Files:**
- Create: tests/integration/test_mixed_release_collaboration_acceptance_postgres.py
- Modify: workflow, CI guards, matrix/RC graph tests; writer code/tests only if final audit finds an omitted writer.

- [ ] Marked acceptance creates R1 root, R2, capable contributor and marker duplicate; performs contributor graph row/deck writes including builder failure and stall placeholders, null legacy direct write, root write. Assert exact root deck/root session/opaque actor/R1-R2-null identities, immutable pins, grouping/warning, no root inference; include all forced creation lock orderings.
- [ ] Execute both contract audits: content-writer rg and lifecycle/creator rg named above. Add any omitted writer/creator/placeholder/lifecycle seam before completion. Assert migration twice/idempotence, SET NULL snapshot retention after root/actor/deck cascade, trigger, grouped query count, and the exact history boundary: authorization-scoped owner/contributor-to-root join is the first and only lookup; denied/unknown/guessed/missing-root/deleted-root paths call no legacy unrestricted requested/root resolver, run no event query, and return identical 404.
- [ ] Cause-based final runs:

    python -m pytest -q -m postgres tests/integration/test_conversation_pin_migration_postgres.py tests/integration/test_conversation_pin_creation_postgres.py tests/integration/test_mixed_release_creation_postgres.py tests/integration/test_conversation_creator_exclusions_postgres.py tests/integration/test_shared_deck_mutation_migration_postgres.py tests/integration/test_shared_deck_mutation_lifecycle_postgres.py tests/integration/test_shared_deck_mutation_attribution.py tests/integration/test_collaboration_history_api_postgres.py tests/integration/test_mixed_release_collaboration_acceptance_postgres.py
    python -m pytest -q tests/unit/test_shared_deck_attribution.py tests/unit/test_session_cleanup.py tests/unit/test_collaboration_history.py tests/unit/test_slide_writer.py tests/unit/test_deck_level_writer.py tests/unit/test_ci_collects_integration_tests.py tests/unit/test_e2e_matrix_covers_specs.py tests/unit/test_rc_graph_ci.py
    cd frontend && npm test -- --run && npx tsc --noEmit && npx playwright test mixed-release-collaboration.spec.ts --project=chromium --workers=1
    git diff --check

- [ ] Sabotage trigger installation; PostgreSQL mutation-protection test goes RED. Restore, run all gates, commit test: verify mixed-release collaboration acceptance.

## Final self-review

- [ ] Map every #262 acceptance criterion to a task/test.
- [ ] Verify creation/mutation/lifecycle tables remain exhaustive; null provenance is never inferred; root, actor and release invariants/migration/idempotency/opaque-snapshot retention are exact.
- [ ] Confirm all lock tests assert exact R1/R2/source/actor/root and observed waiter PIDs.
- [ ] Confirm contributor marker/pin versus owner deck semantics; create_chat_request rejection and MCP/tour null exclusions; every Send/retry/fix/re-review payload and placeholder path; monolith/legacy isolation; log/event privacy; authorization-scoped join before all requested/root resolution, denied resolver/event-query tripwires, identical 404 non-enumeration/no N+1; warning/history accessibility; Start-latest immutability; CI collection/zero skips.
- [ ] Scan no-placeholder terms, run git diff --check, leave clean.
