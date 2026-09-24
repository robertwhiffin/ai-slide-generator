THIS FILE OVERRIDES `docs/superpowers/plans/2026-09-22-mixed-release-collaboration.md` FOR #262 EXECUTION.

# #262 post-integration plan corrections

Canonical corrections authority: `.superpowers/sdd/2026-09-22-mixed-release-collaboration/PLAN-CORRECTIONS.md`.
The old `.superpowers/issue-262-plan-corrections.md` location is stale and must not be
created or maintained as a second authority.

## Frozen execution identity

- Integration base: `795262c165cac2dc76e93e385139f9e857f74f79`.
- Rebased plan HEAD: `420ab9aa48138aa56d7c8d3f207b55c23ff03822`.
- The base is the merge base and an ancestor of HEAD.
- Reviewed #260 `29e03411487476383b34101b7b34513dbb917f26`, #261 implementation
  `88ebbf821511b0076ad6b39025a5ac06f031b51f`, #261 evidence
  `e9ab7f937dea063e155f9df8e24ac52fdaa6b754`, and reviewed #263
  `1d706e21b92aad68314da2e79bb4d1d5626663b7` are all ancestors of the base.
- Range-diff is exact and one-to-one:
  `43ea1b3a1 = 2d5282d5c`, `d9bf039e2 = 1e523de11`,
  `d0185d68d = 420ab9aa4`.
- The rebased interval changes only
  `docs/superpowers/plans/2026-09-22-mixed-release-collaboration.md`.
- #264 `ac69f62b6792d812f99eef53f725085bc90c61a6`, #265
  `3a3583c3061456d9292c43f9a1b45dffffca52be`, and #266
  `ce10838ac9951fb3728029cb42db56dbd0cb8efc` are not ancestors of HEAD. The #262
  interval edits none of their schema-overlay, assembly, endpoint/editor, or Graph
  Draft writer seams.

## Binding rulings

### C-0 — Frontend command spelling

Replace every Task 0/5/6 instruction to run `npm test -- --run` with
`npm run test:unit`, and replace `npx tsc --noEmit` with `npm run typecheck`.
The live `frontend/package.json` maps `test` to Playwright, `test:unit` to
`vitest run`, and `typecheck` to `tsc -b`.

Cost if wrong: unit tests may be mistaken for browser tests, or TypeScript project
references may not be checked the same way as the repository script.

### C-1 — Chat provided-ID creation must not depend on agent-config presence

Task 2's “both chat creation branches” means (a) no supplied session ID and (b) a
supplied client-generated ID that does not exist. Live `_maybe_create_session` only
calls `get_session` inside `if explicit_config`; a missing supplied ID with no
`agent_config` therefore falls through today and is auto-created later by
`create_chat_request`. Once Task 2 correctly forbids `create_chat_request` from
creating a `UserSession`, that request would become a 404 instead of taking the
message-aware lock.

Task 2 must check existence independently of whether config was supplied, create the
missing supplied ID with `graph_capable=selects_graph_engine(request.message)`, and
sync config only when config was supplied. Test marker and non-marker requests for
both supplied-missing-ID and no-ID branches. `create_chat_request` must then require
the already-created row and raise `SessionNotFoundError` when absent.

Cost if wrong: a browser/local client ID without config either becomes an unpinned
graph conversation through the fallback or unexpectedly changes from successful
creation to 404.

### C-2 — Duplicate must determine capability before constructing the new row

The live `duplicate_session` constructs and flushes `new_session` and `new_deck`
before it queries the source's earliest user marker and computes `carried_marker`.
The plan says the active release is locked immediately before `UserSession`
construction when and only when `carried_marker` is true. Task 2 must therefore move
the source-marker query/capability decision before the new `UserSession`, lock there,
assign only the newly locked release ID, then construct/flush the session and deck.
It must never copy the source pin.

Cost if wrong: publication can interleave between row creation and pin selection, or
the implementation may copy/source-infer a release contrary to #261's immutable
creation contract.

### C-3 — Sweeper null provenance is an exclusion, not a nullable graph event

The writer table's `run_arc_review` phrase “root actor/nullable pin” is invalid
against final #261. `invoke_graph` calls `load_conversation_pin`, which raises
`ConversationPinMissingError` for a null pin before any node or writer runs.
`run_arc_review` catches that failure, releases the claim, and returns `False`.

Task 3/6 must assert: a pinned root produces the normal graph deck event using that
root as actor and its exact release; a null-pinned legacy root produces no content
write and no mutation event and remains queued/retryable. Do not infer active/latest
or invent a nullable graph runtime identity.

Cost if wrong: the sweeper silently violates #261 by running a graph without a
persisted release, or acceptance expects an event for a write that never occurs.

### C-4 — Restore owns its event inside its existing transaction

`SessionManager.restore_version(session_id, version_number)` directly rewrites the
deck and materialized rows in one `get_db_session` transaction; it does not call any
of the three proposed mutation-aware writers. Task 3 must explicitly insert the
`restore_version/deck` event inside that same transaction after content flush and
before return, deriving actor from the requesting session and its persisted pin.
An event failure must roll back the restored deck, rows, message/version deletions,
and event together.

Cost if wrong: restore can commit content without evidence, or a later transaction
can double-count/lose the named event.

### C-5 — New-deck duplication is outside the shared-mutation aggregate

The exhaustive constructor audit finds `SessionManager.duplicate_session` directly
constructing a fresh `SessionSlideDeck`. This creates a new private root/deck rather
than mutating the source shared deck, so it emits no `SharedDeckMutationEvent`.
Task 2 still owns its creator pin and marker semantics. Task 3 tests must state this
exclusion so the constructor is not repeatedly rediscovered as an unclassified
writer.

Cost if wrong: recording it against the source would falsely claim a shared-deck
mutation; silently omitting the classification would leave the audit non-exhaustive.

### C-6 — Known focused-backend baseline cause must be repaired before GREEN claims

The mandatory focused matrix currently fails exactly these nodes:

- `tests/unit/test_session_duplicate.py::TestListSessionsIncludesDuplicatedDeck::test_deck_only_session_appears_in_list`
- `tests/unit/test_session_duplicate.py::TestListDeckOnlySessions::test_deck_only_returns_recent_decks_not_chat_sessions`

Both fail at `SessionManager.list_sessions -> get_conversation_graph_versions ->
_require_active_graph_release` with
`ConversationGraphReleaseIntegrityError: no active Graph Release`. The fixtures
predate #261's public projection invariant and create sessions without seeding a live
active release. This is one cause, not two product defects.

Before a task claims the focused matrix GREEN, add a real active release to these
fixtures (or their shared fixture) without weakening `_require_active_graph_release`.
The fix belongs with Task 2's existing duplicate-session test ownership and must be
reviewed as a fixture correction.

Cost if wrong: weakening production integrity would hide a missing/dangling release;
leaving the fixtures red prevents cause-based regression comparison.

### C-7 — Read-time authorship repair is a classified non-user content migration

`SessionManager.get_slide_deck` may persist missing authorship back into legacy
`deck_json` while reading. Alongside startup row backfill, verdict-only writes, dirty
claims, save-point snapshots, and export metadata, classify this one-time legacy
repair as non-user migration state with no collaboration event. It must not be used
as a generic exemption for user-initiated content changes.

Cost if wrong: reads could create misleading user mutation evidence, or a future
real writer could hide under an over-broad “backfill” exclusion.

### C-8 — Task 3 ownership follows durable writer seams, not mandatory file churn

Task 3's file list is an audit inventory, not a requirement to add attribution code
or duplicate assertions to every named file. Live `src/services/graph/routers.py`
only selects edges and constructs `Send` payloads; it performs no durable write and
already preserves `graph_release_id` in `build_reviewer_refan_router`. Live
`src/services/spec_sync.py` owns marker/lease metadata (`mark_dirty`,
`claim_due_marker`, `clear_marker`, `discard_marker`, `_release_claim`); its only
content path is `run_arc_review` delegating to the graph, whose writer contexts are
owned by `graph/nodes.py`.

The binding Task 3 fix ownership is therefore:

- `tests/unit/test_graph_nodes.py` proves every graph branch/state boundary creates
  the literal context and that `_write_reviewed_row`,
  `_placehold_failed_position`, `_land_original`, and
  `_reconcile_stale_fixes` preserve the exact object identity.
- `tests/integration/test_shared_deck_mutation_attribution.py` is the single real-
  transaction matrix for monolith, row/delete/placeholder/deck writers, direct
  operations, rollback, and named exclusions. It replaces attribution-only hunks
  in `test_slide_writer.py`, `test_deck_level_writer.py`,
  `test_save_slide_deck_dual_write.py`, `test_graph_mode_turn.py`,
  `test_insert_slide_route.py`, `test_task7_verification_and_restore.py`, and
  `test_sweeper_describe_only.py`; those suites remain in the focused regression
  command for their existing public behavior.
- `tests/unit/test_graph_routers.py` remains the router/release-payload owner and is
  regression-run unchanged; it must not mock or assert a durable writer that the
  production router does not call.

Cost if wrong: concentrating evidence at the transactional seam could miss an
owner-file-specific fixture or collection regression; the full named focused matrix
is still required to catch that without duplicating attribution contracts.

## Current gate result

Task 0 is `DONE_WITH_CONCERNS`: topology, inventory, PostgreSQL, frontend unit, and
typecheck evidence are complete. The PostgreSQL matrix has zero skips. The focused
backend matrix has the single explained C-6 fixture cause and is not GREEN. Task 1
remains blocked until an independent corrections review approves this file and the
two failing fixture nodes are assigned/accepted under C-6.

### C-9 — Task 4 executes as two ordered slices

Task 4 is split into two slices with a frozen file boundary. Both must be implemented and
independently reviewed before #262 merges into `feat/langgraph-core`; the split changes
ordering only, and changes no acceptance criterion.

**Slice 4A — Collaboration history API. Runs now, at base `cf9fa4c39`.**

Owns plan Task 4 bullets 3, 4, 5, 6, and the grouping/authorization halves of bullet 7.

- Create: `src/services/collaboration_history.py`,
  `tests/unit/test_collaboration_history.py`,
  `tests/integration/test_collaboration_history_api_postgres.py`
- Modify: `src/services/permission_service.py`, `src/api/services/session_manager.py`,
  `src/api/routes/sessions.py`, `tests/unit/test_deck_permission_routes.py`,
  `tests/integration/test_api_routes.py`, the CI enrollment guard and workflow
- Interfaces owned: `AuthorizedCollaborationRoot`, `authorized_collaboration_root`,
  `CollaborationReleaseGroup`, `get_collaboration_history`
- Explicitly excluded: `src/services/agent_runtime.py`,
  `src/services/agent_runtime_identity.py`, `src/services/graph/builder.py`,
  `src/services/graph/state.py`, `tests/unit/test_graph_nodes.py`, and every
  `AgentInvocationIdentity` field change

**Slice 4B — Runtime root/actor trace. Held until reviewed #265 is integrated into
`feat/langgraph-core` and this branch is rebased and re-probed onto the new head.**

Owns plan Task 4 bullets 1 and 2, plus the runtime-identity assertions in bullet 7.

- Modify: `src/services/agent_runtime_identity.py` (`AgentInvocationIdentity` gains
  `root_session_id` and `actor_session_id`), `src/services/agent_runtime.py`,
  `src/services/graph/builder.py`, `src/services/graph/state.py`,
  `tests/unit/test_graph_nodes.py`
- The distinct reviewer sabotage named in bullet 2 (removing root/actor/release from the
  build-reviewer `dict(record)` re-fan) stays with this slice.

**Evidence the boundary is real, probed at `cf9fa4c39` and `ce05e163e` on 2026-09-23.**

1. Slice 4A is data-complete at the current base. Task 1 already created
   `shared_deck_mutation_event` with `root_session_id`, `root_deck_id`,
   `actor_session_id`, `root_session_identity`, `root_deck_identity`,
   `actor_session_identity`, `graph_release_id`, `graph_version`, `operation`,
   `object_type`, `object_id`, and `occurred_at`; Task 3 already writes all of them
   through the immutable `DeckMutationContext`. `get_collaboration_history` reads that
   table and needs no interface from slice 4B.
2. The identity sink persists nothing. `LoggingAgentInvocationIdentitySink` and
   `RecordingAgentInvocationIdentitySink` in `agent_runtime_identity.py` only log or
   accumulate in memory, so widening `AgentInvocationIdentity` cannot change any row
   `get_collaboration_history` reads. Coupling between the slices is zero.
3. Slice 4A does not collide with #265. `git diff --name-only 795262c16 ce05e163e`
   lists `src/services/agent_runtime.py`, `src/services/graph_definition_manifest.py`,
   `src/services/prompt_assembler.py`, `src/core/skills/build_reviewer.py`,
   `src/core/skills/data_analyst.py`, and eight test modules. None of slice 4A's files
   appears. #265's own remaining Tasks 4, 5, and 6 own
   `graph_configuration_draft.py`, `graph_configuration.py`,
   `src/api/schemas/agent_definitions.py`, `src/api/routes/agent_definitions.py`, the
   workbench frontend, and four test modules — again disjoint from slice 4A.
4. Slice 4B against this base would compile against deleted symbols. #265 removed
   `_ProtectedPromptBundleRegistry`, `_ProtectedPromptBundle`, `_protected_prompt_material`,
   `AgentRuntime._assemble_v1_prompt`, and `ProtectedPromptBundleUnavailableError` from
   `agent_runtime.py` (34 insertions, 105 deletions), and made `assembly_rules` a required
   field of the frozen `AgentDefinition` and `assembly_stages` a required field of
   `AgentInvocationDiagnostics`. Any slice-4B test that constructs either dataclass from
   this base is missing a required argument once #265 merges — a break a textual merge
   does not report.
5. The slice-4B seam itself is narrow, which is why it is deferred rather than redesigned.
   `agent_runtime_identity.py`, `graph/builder.py`, and `graph/state.py` are untouched by
   #265; `AgentAssemblyContext` and the four-argument `AgentRuntime.run` signature are
   byte-identical on both heads. The blocker is the dataclass arity and the deleted
   symbols above, not the identity-threading design.

**Acceptance criteria are unchanged.** Issue #262 AC4 ("Every shared-deck mutation and
trace records the root deck, actor session, and actor's pinned release") is the only
criterion spanning both slices: its mutation clause is already satisfied by Task 3, and
its trace clause is slice 4B's. AC6 (grouping by actor and release, never labelling the
deck with the root session's version) is satisfied wholly by slice 4A. No criterion is
weakened, deferred past merge, or reinterpreted.

Cost if wrong: if the slices are in fact coupled, slice 4A ships a history projection that
slice 4B must revise, costing one extra scoped review of `collaboration_history.py`. That
is strictly cheaper than the alternative, which is writing slice 4B against five symbols
#265 has already deleted and two frozen dataclasses whose required-field sets have changed.

### C-10 — Inherited integration-head baseline cause, extending C-6's class

`tests/unit/test_deck_permission_routes.py::TestCreateSessionNoProfile::test_create_session_no_profile_params`
fails identically on `feat/langgraph-core` at `795262c16` and on this branch, in isolation
and in the full suite, at `src/services/conversation_pins.py:83`
(`ConversationGraphReleaseIntegrityError: no active Graph Release`). This branch does not
touch that file. It is the same cause class as C-6 — a fixture predating #261's public
projection invariant — at a site C-6 did not enumerate.

Slice 4A owns `tests/unit/test_deck_permission_routes.py`, so the fixture repair belongs to
it: seed a real active `GraphRelease`, and do not weaken `_require_active_graph_release`.
Because the failure is inherited, it is not evidence of slice 4A breakage and must not be
counted against it.

Cost if wrong: weakening the invariant would hide a missing or dangling release; leaving it
red prevents cause-based comparison in the file slice 4A must edit.

### C-11 — Four unrecorded regressions introduced by Tasks 1, 2, and 3

The ledger's Task 3 entry claims a full-unit cause audit that "retained three inherited
fixture causes". Live state contradicts it. Measured 2026-09-23 with
`PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr` from each worktree root:

- integration head `795262c16`, full `tests/unit`: 14 failed, 5176 passed, 110 skipped
- this branch `cf9fa4c39`, full `tests/unit`: 22 failed, 5215 passed, 110 skipped
- the seven newly-affected files in isolation: 91 passed / 0 failed on the integration
  head, 15 failed / 76 passed on this branch

The 15 are reproducible in isolation, so they are regressions, not ordering pollution.
Tasks 1/1b/2/3 also repaired seven inherited failures (`test_session_duplicate.py` ×2 per
C-6, `test_tour_ships_a_spec.py` ×5), which is why the counts nearly collide and the
regression went unrecorded. Four causes:

**R1 — `NOT NULL constraint failed: user_sessions.collaboration_identity` (7 tests).**
Task 1 added `collaboration_identity` to both `UserSession` (`session.py:107`) and
`SessionSlideDeck` (`session.py:274`) as `nullable=False` carrying only a Python-side
`default=uuid.uuid4`. A Python-side default fires only for ORM-mapper inserts, so every
raw-SQL insert path violates the constraint. Affected: `test_deck_permissions_migration.py`
×3, `test_deck_workspace_sharing_migration.py` ×1, `test_drop_config_prompt_columns.py` ×2,
`test_spec_dirty_marker.py` ×1 — all of which insert sessions or decks through raw SQL, as
migration tests must.

**Controller correction, 2026-09-23, after Task 3R — the sentence originally here was too
strong and is withdrawn.** It claimed any non-ORM insert "fails in production exactly as
these tests do". That is wrong on PostgreSQL. The base `cf9fa4c39` already carried, inside
`_migrate_shared_deck_mutation_schema` in `src/core/database.py`, a PostgreSQL branch that
backfills with `gen_random_uuid()` (`:724`), then `ALTER COLUMN collaboration_identity SET
DEFAULT gen_random_uuid()` (`:731`), then `SET NOT NULL` (`:737`). So a deployed PostgreSQL
database that has run `_run_migrations` already defaults the column, and the 15 failures
were SQLite-manifested. Task 3R found this by sabotaging only the model default and
observing PostgreSQL stay green; the controller confirmed the pre-existing `SET DEFAULT` on
the base.

The defect is real in a narrower form, and the repair still belongs in production code: the
ORM *metadata* did not declare the default, so `Base.metadata.create_all` emitted a column
with no default on **every** dialect and relied on a later repair migration to correct it.
Any path that builds schema from metadata is therefore wrong until that migration runs, and
the SQLite branch (`:708`, `ADD COLUMN ... NULL`) never reaches `SET NOT NULL` at all. The
accepted repair declares the default on the column itself so `create_all` emits it per
dialect, keeps `nullable=False`, keeps the migration's `SET DEFAULT` for already-deployed
databases, and keeps the `_reject_collaboration_identity_change` immutability guard at
`session.py:468`. Only then adjust fixtures.

**R2 — `ActiveGraphReleaseUnavailableError: no active Graph Release` at
`conversation_pins.py:74` (4 tests).** `test_engine_mode_selection.py::TestDuplicateCarriesTheMarker`
×4. C-2 correctly moved the capability decision and active-release lock ahead of
`UserSession` construction in `duplicate_session`, so duplication now requires a live active
release where it previously did not. The fixtures must seed one. Do not relax the lock, and
do not let duplication fall back to latest or to the source pin — C-2 forbids both.

**R3 — `'FakeDeckStore' object has no attribute 'deck_mutation_context'` at
`chat_service.py:4066` (3 tests).** `test_multiworker_cache_coherence.py` ×3. Task 3's
`DeckMutationContext` threading. The test double diverged from the real store, so the
multi-worker coherence suite has not exercised the threaded path at all. Treat this as a
coverage gap: the double must expose the real attribute with real semantics, and the three
tests must genuinely exercise the context-carrying path. Adding a bare attribute to silence
the `AttributeError` is not an acceptable repair.

**R4 — `'MockSessionForVersions' object has no attribute 'session_id'` at
`session_manager.py:2823` (1 test).** `test_save_points.py::TestVersionRestore::test_restore_valid_scenarios`.
C-4's restore event derives its actor from the requesting session and its persisted pin, so
`restore_version` now reads `session_id` from an object the double does not populate. Same
coverage-gap treatment as R3.

Cost if wrong: R1 left as a fixture-only repair ships a column that breaks every non-ORM
insert and leaves historical rows unbackfilled. R3 and R4 patched cosmetically leave two
reviewed tasks with production paths no test actually covers.

### C-12 — Task 3R precedes slice 4A

Ruling: Lane 2 does not begin slice 4A until the four C-11 causes are repaired and
independently reviewed as Task 3R. Rationale: slice 4A must edit
`test_deck_permission_routes.py`, whose only failing node is the inherited C-10 cause; with
15 unexplained regressions also live on the branch, no implementer or reviewer can separate
slice 4A's breakage from the pre-existing set, which is the exact condition the cause-based
baseline rule exists to prevent. C-10 stays with slice 4A because slice 4A owns that file;
C-11's four causes are Task 3R's.

Cost if wrong: one extra review cycle on Lane 2 before slice 4A starts, and #262's
critical path lengthens by that cycle. The alternative is dispatching slice 4A against a
baseline neither its implementer nor its reviewer can trust.

### C-13 — The CAN_VIEW rule has five checks, not four, and one is a fallback the plan omits

Task 4 says the SQL predicate is "extracted from the permission service's ownership,
direct-contributor, profile/group, and global-share rules" — four categories. Live
`PermissionService.get_deck_permission` (`src/services/permission_service.py:233`) has
**five** checks, and collapsing two of them silently narrows authorization:

1. Deck owner — `root.created_by == user_name`, granting implicit `CAN_MANAGE`, root only.
2. Direct user permission matched by `identity_id`.
3. **Fallback: direct user permission matched by `identity_name`.** The plan's single
   "direct-contributor" category covers checks 2 and 3 together. An implementer who writes
   one direct-contributor clause drops the name-matched grant, and every user granted by
   name receives a 404 from the history endpoint while the rest of the application grants
   them access.
4. Group-based permission via `group_ids`.
5. Workspace-wide sharing — `root.global_permission`, root sessions only, and only when the
   value is in `VALID_DECK_GLOBAL_PERMISSIONS` (`frozenset({CAN_VIEW, CAN_EDIT})`,
   `permission_service.py:43`). `CAN_MANAGE` is deliberately not a valid workspace share.

The function then returns the highest match by `PERMISSION_PRIORITY`
(`permission_service.py:35`, where `CAN_USE` and `CAN_VIEW` share priority 1).

The SQL predicate must reproduce all five checks, including the `identity_name` fallback and
the `VALID_DECK_GLOBAL_PERMISSIONS` filter. Slice 4A must prove equivalence with a test that
grants access by each of the five routes independently and asserts the endpoint admits all
five, plus a test that a `global_permission` of `CAN_MANAGE` does **not** grant workspace
access through the new predicate.

Cost if wrong: an authorization divergence in the one place Task 4 demands byte-identical
404 behaviour — either name-granted users are denied history the rest of the app gives them,
or an invalid workspace share is honoured.

### C-14 — The two existing root resolvers disagree about nesting depth, and the plan's SQL matches only one

Task 4 specifies `join root on root.id == coalesce(requested.parent_session_id, requested.id)`
— a single-hop resolution. The codebase contains two root resolvers that do not agree:

- `PermissionService._resolve_root_session` (`permission_service.py:217`) **walks the whole
  `parent_session_id` chain** with a `seen` cycle guard.
- `SessionManager._get_deck_owner_session` (`session_manager.py:916`) follows
  `parent_session_id` **exactly one hop** and returns.

The plan's SQL matches `_get_deck_owner_session` and contradicts `PermissionService`, which
is the very service the CAN_VIEW predicate is extracted from. At nesting depth 2 the new
endpoint's authorization would resolve a different root than `get_deck_permission` resolves,
so the predicate and the grant it is derived from would disagree.

Depth 2 appears reachable and must be proven or disproven before the predicate is written.
`get_or_create_contributor_session` (`session_manager.py:843`) resolves its parent at :864
with `self._get_session_or_raise(db, parent_session_id)` and does **not** require that
parent to be a root; the route at `src/api/routes/sessions.py:344-360` passes the caller's
`session_id` straight through, and its only guard rejects the case where the caller already
owns that session. So a viewer acting on a contributor's session id appears able to create a
contributor whose parent is itself a contributor.

Slice 4A must write a test that attempts to create a depth-2 chain. If it succeeds, the SQL
must walk the chain (bounded, with a cycle guard, matching `_resolve_root_session`) and the
divergence must be recorded as a pre-existing defect for the whole-branch review. If a guard
prevents it, name the guard and the single-hop `coalesce` stands. Do not assume either
answer, and do not "fix" contributor creation inside slice 4A — that is out of scope.

Cost if wrong: a contributor-of-a-contributor sees collaboration history for the wrong root
deck, or is denied history for a deck the rest of the application grants, and the plan's
"identical 404" acceptance is proven against the wrong root.

### C-15 — The four tripwire seams are real but live in three modules

Task 4's bullet 7 requires spying on `get_session`, `_get_session_or_raise`,
`_get_deck_owner_session` and `_get_root_session_or_400` and asserting zero calls on every
denied path. All four exist, but not where the plan's phrasing implies. Patch targets:

- `get_session` — `src/api/routes/sessions.py:380`, a route handler. Seven other
  `get_session*` definitions exist repo-wide, including `get_session_local` in
  `src/core/database.py:335` and `get_session_messages` in `sessions.py:607`; patch the
  exact one, not a name.
- `_get_session_or_raise` — a `SessionManager` method, `src/api/services/session_manager.py:3341`.
- `_get_deck_owner_session` — a `SessionManager` method, `src/api/services/session_manager.py:916`.
- `_get_root_session_or_400` — a module-level function in a **different route module**,
  `src/api/routes/deck_contributors.py:74`, not in `sessions.py`.

`src/api/routes/sessions.py` contains exactly one private helper, `_substitute_deck_images`
at :55, so there is no local helper cluster to patch.

Cost if wrong: a tripwire patched at the wrong import site asserts zero calls against a
function the route never reaches, producing a passing test that proves nothing — the
false-green shape this project's sabotage rule exists to catch.

### C-16 — C-14 is WITHDRAWN: depth 2 is unreachable, and the single-hop join is correct

**Controller error, corrected 2026-09-23 by slice 4A's evidence.** C-14 claimed depth-2 session
nesting "appears reachable" because `get_or_create_contributor_session` resolves its parent at
`session_manager.py:864` with `_get_session_or_raise` and does not require a root. That reading
stopped one statement too early. The very next statement is a guard:

    if parent.is_contributor_session:
        raise ValueError("Cannot create contributor session on another contributor session")

It sits at `session_manager.py:875-876` on this branch and at `:868` on the integration head
`795262c16`, attributed to `4144bbc46`, so it is pre-existing and no rebase introduced it or
could silently drop it. The controller independently confirmed both locations.

The guard covers every path. There are exactly two production writers of `parent_session_id`:
`session_manager.py:902`, which is behind the guard, and `:1253`, which writes `None`. The third
grep hit, `src/api/routes/sessions.py:365`, is a keyword argument to the guarded manager method,
not a database write.

**Ruling: the plan's single-hop `coalesce(requested.parent_session_id, requested.id)` join is
correct and stands.** Slice 4A proved equivalence rather than assuming it: for every contributor
row the manager creates, `PermissionService._resolve_root_session(...).id` equals
`db.get(UserSession, contributor.parent_session_id).id` equals `root.id`.

One divergence survives and is deliberately fail-closed and asserted: a hand-forced depth-2 row,
reachable only through raw SQL or a pre-guard legacy database, returns `None` from
`authorized_collaboration_root` because of the `root.parent_session_id IS NULL` requirement, while
`_resolve_root_session` would reach the real root. The two resolvers therefore still disagree
about depth. That is a **pre-existing defect carried to the whole-branch review**, not a slice-4A
defect, and contributor creation was correctly left untouched.

Cost of the original error: had slice 4A transcribed C-14 literally it would have built a
chain-walking SQL predicate with a cycle guard for a state the application cannot produce —
dead complexity in an authorization path, which is the worst place to carry it.

### C-17 — C-15's first tripwire target is inert by construction

**Controller error, corrected 2026-09-23 by slice 4A's evidence.** C-15 named
`src/api/routes/sessions.py:380` `get_session` as one of four tripwire seams to spy on. It cannot
work. `get_session` is a route handler, and the `APIRouter` captured the function object at
decoration time, so a module-level patch is unreachable from any other handler. A tripwire on it
can never fail, which makes it the exact false-green shape this project's sabotage discipline
exists to catch.

Slice 4A kept the tripwire because C-15 named it, documented the inertness at both patch sites,
and proved with a dedicated probe that nothing is lost: with its fifth tripwire removed, the
authorization sabotage still fires through `SessionManager._get_session_or_raise`. **C-15's
remaining three seams are sufficient**, and the correct count of load-bearing tripwires is three,
not four.

Cost of the original error: a reviewer could have read a permanently-green assertion as evidence
that a denied path avoids the legacy lookup.

### C-18 — the plan's Task 4 contains no 422 contract

**Controller error, corrected 2026-09-23.** The slice-4A brief and its dispatch both referred to
"the 422/404 contracts". `grep` over plan Task 4 returns **zero** occurrences of `422` and two of
`404`. Only the 404 contract exists; it is implemented and over-tested. The 422 was the
controller's invention, and slice 4A flagged it rather than fabricating tests for a contract that
does not exist — the correct response.

For the avoidance of doubt in later slices: 422 envelopes belong to ticket #265's draft-writer
work, not to #262's history API.

Cost of the original error: an implementer could have invented a 422 shape and a reviewer could
have approved tests for a requirement no spec contains.

### C-19 — plan Task 4 bullet 5's get/list/contributor/duplicate summary is deferred, not done

Slice 4A deliberately did not implement bullet 5's "Add safe summary to get/list/contributor/
duplicate", and asked for a ruling. **Ruling: the deferral is upheld for all four, and this
correction records it as an explicit open plan item so it is not mistaken for completed work.**

Reasons, in descending strength:

1. **`list` would be an N+1**, which bullet 3 of the same task explicitly forbids ("one grouped
   query/no N+1"). An explicit prohibition inside the task outranks bullet 5's convenience.
2. **`duplicate` is vacuous by construction.** Correction C-5 establishes that
   `SessionManager.duplicate_session` creates a new private root and deck and emits no
   `SharedDeckMutationEvent`, so a collaboration summary on it would always be empty.
3. **No consumer exists.** Plan Task 5, the only consumer, calls `api.getCollaborationHistory`
   and nothing else. Adding fields to `get` and `contributor` responses with no reader is
   speculative generality, and changing `get_session`'s response shape risks collateral breakage
   in test modules outside slice 4A's allowlist.

Acceptance is not at risk. Issue #262 AC5 ("Conversation and collaboration surfaces warn when one
shared deck has writers on multiple Graph Versions") is satisfied by Task 5 reading
`getCollaborationHistory` on the conversation surface; the bullet-5 summaries would have been an
additional delivery mechanism, not the only one.

**Binding follow-up:** Task 5's report must state explicitly whether it needed an inline summary
on `get` or `contributor` to avoid a second round-trip. If it did, that becomes a small additive
backend change reviewed with its real consumer. The whole-branch review must confirm AC5 against
verbatim issue text with this deferral on the record.

Cost if wrong: one additive backend change later, reviewed alongside the consumer that justifies
it, instead of an unused field shipped now.

### C-20 — C-17 refined: the inert tripwire is conditional, and there is a second blind spot

C-17 said the `sessions.get_session` tripwire "can never fail". That is narrower than stated, and
slice 4A's reviewer proved it by probe. The module global in `src/api/routes/sessions.py` **is**
the mock, so the likeliest defect — the history handler calling `get_session` in-module — WOULD
fire. Only router dispatch cannot reach it: registered endpoints probed `[False, False, False]`.
So the tripwire is conditional, not inert.

The reviewer also found an undisclosed second blind spot:
`deck_contributors._get_root_session_or_400` is live via module-attribute resolution, which is how
that module's own handlers call it, but is **bypassed by an import-time-bound reference** — proven
by a traceback from the real function with the mock count unchanged.

The three `SessionManager` class-attribute patches are **unconditionally** load-bearing; each
fires on a normal instance call. C-17's ruling that those three are sufficient stands.

Cost of the original overstatement: a reviewer could have deleted a tripwire that does catch the
most likely in-module regression.

### C-21 — controller ledger error: the residual cause split was inverted

The controller's slice-4A ledger entry claimed three of the six inherited failures were the
C-6/C-10 `no active Graph Release` cause class. That is wrong, and the controller's own earlier
measurement already contradicted it — the error was relaying the implementer's report instead of
cross-checking data already in hand.

Re-measured directly, twice:

- `tests/unit/test_style_exclusivity_chokepoint.py` ×3 fail at `conversation_pins.py:79` with
  `AttributeError: '_FakeSession' object has no attribute 'execute'` — a **diverged test double**,
  the same class as C-11's R3 and R4.
- `tests/unit/test_style_exclusivity_persistence_boundary.py` ×1 fails at
  `conversation_pins.py:83` with `ConversationGraphReleaseIntegrityError: no active Graph Release`
  — the C-6/C-10 fixture class.

So the fixture cause class has **one** further site, not three, and the diverged-double class has
three, not one. The node set is unaffected; what changes is the size and shape of the sweep the
whole-branch review should run — it is mostly a double-divergence sweep, not a fixture sweep.

Cost of the original error: the whole-branch review would have sized the wrong sweep and looked
for missing release fixtures where the real defect is test doubles drifting from production.

### C-22 — the dev-database prohibition was unsatisfiable as written

Slice 4A's reviewer disclosed that two of its probes drove `TestClient(app)`, whose
request-logging middleware at `src/api/middleware/request_logging.py:45-64` inserts a `RequestLog`
row into the reachable dev database `ai_slide_generator`. No migration ran and no schema changed.

This is pre-existing repo-wide behaviour of **every** `TestClient` test, including the new unit
module and therefore including slice 4A's own mandated gates. The controller's environment rule
"do not open the dev database" was consequently impossible to honour while running the gates it
also mandated.

Corrected rule for every later dispatch in this ticket: do not **migrate, alter or drop** the dev
database `ai_slide_generator`, and do not read from it as evidence. Incidental `RequestLog` inserts
from `TestClient` are accepted and expected. The reviewer flagged the conflict rather than silently
breaking either rule, which is the correct response.

Cost of the original error: an agent could have skipped a mandated gate to honour an impossible
constraint, or run it and concluded it had violated the rules.

### C-23 — the exclusive frontend resource is the whole test lane, not just Playwright

The #258 resume brief's cross-lane table serialises only "Playwright / port 3000". That is too
narrow, and acting on it alone would have corrupted evidence. Probed 2026-09-24:

- The Vite dep-optimise cache lives at
  `.worktrees/issue-260-bootstrap/frontend/node_modules/.vite` — **inside the single physical
  `node_modules`** that five worktrees symlink.
- Neither `frontend/vite.config.ts` nor any vitest config sets a `cacheDir`, so there is no
  per-worktree override.

So two worktrees running `npm run test:unit` concurrently write the same dep-optimise cache, not
merely the same `node_modules`. Review A flagged this as a concurrency race; the cross-lane table
did not carry it forward.

**Binding rule: the frontend test lane is exclusive across the whole epic — Vitest as well as
Playwright.** One ticket at a time may run any frontend test command. Backend-only lanes remain
freely concurrent, and PostgreSQL remains safe concurrently under the four-lane connection cap.

This is why #262 Task 5 is being held behind #265 Task 5's fix round rather than run beside it,
even though slice 4A unblocked it and its frontend files (`frontend/src/services/api.ts`,
`SessionContext`, `GraphVersionStatus`, `AppLayout`, `deck-history`) are genuinely disjoint from
the Agent Definition Workbench cluster.

Giving each worktree its own `cacheDir` would lift the constraint, but `vite.config.ts` is shared
with #264, #265 and #266 and is in none of their task file lists, so that is not a change to make
unilaterally mid-epic. Recorded as an option for the whole-branch review.

Cost if wrong: two lanes' frontend evidence could interleave through one dep cache, producing a
false green or a false red with no error — the same silent-wrong-result shape as
`reuseExistingServer: true`, which is exactly the failure this project already knows to serialise.

### C-24 — EPIC-WIDE: a test that imports the constant it asserts is not a guard for that constant's value

Found by #262 Task 5 while filling its clause-to-mutation table, and generalisable well beyond
this ticket, so it is recorded here as binding for every remaining task in epic #258.

`MixedReleaseWarning.test.tsx` imported `PROVENANCE_LIST_LABEL`, `DISCLOSURE_LABEL`, the warning
text and the unavailable text **from the component under test**. Mutation M27 renamed the list
label to a string that nests inside the disclosure's accessible name — the exact Playwright
strict-mode collision class this epic has already paid for twice — and **all 20 unit tests stayed
green**. Only the Playwright spec caught it, because the spec uses literals. The same weakness left
every mandated-wording clause unguarded at unit level.

The fix is to assert literals. After replacing all four constants with literals, M27b plus the
three wording mutations (M31 warning, M32 disclosure, M33 unavailable) all RED.

**Binding rule: where a brief mandates exact wording, the test asserting it must carry the literal,
not an import of the constant that produces it.** Importing the constant makes the test agree with
the implementation by construction, so it can never disagree with the requirement.

This is a distinct defect from the same-call self-reference found in #265 Task 4, where a test
compared against `PromptAssembler.legacy_v1_prompt_source(...)` — that was a computed value; this
is a named constant. Both collapse expected and actual onto one source, and both survive every
review that reads the assertion without asking where its expected side comes from.

Cost if wrong: every mandated-wording acceptance criterion in the epic is satisfied by a test that
cannot fail when the wording changes.

### C-25 — C-19's premise is imprecise; the deferral stands on its other two grounds

C-19 rejected a safe summary on `list` on the grounds that it "would be an N+1", which plan Task 4
bullet 3 forbids. Task 5's independent reviewer confirmed the controller's own suspicion: **a single
grouped query over all listed roots is not an N+1**, so bullet 3 never actually blocked
`deck-history`, and C-19's stated premise is too strong.

C-19's *conclusion* nonetheless stands, on its two surviving grounds: a summary on `duplicate` is
vacuous by construction under C-5, and no consumer existed. Task 5 answered C-19's binding
follow-up with a measured **no** — it needed no inline summary, because `getCollaborationHistory`
is initiated at `SessionContext.tsx:161-164` before `await api.getSlides` at `:169` and its landing
is never awaited before commit (`void collaborationLoad.then` at `:196`), so it adds **zero commit
latency on every path, including deckless**. The reviewer verified that and noted the author had
undersold it.

And the deferral is no longer load-bearing for acceptance, because the second AC5 surface turns out
to be the share dialog rather than `deck-history` — see C-26 — and that surface is already scoped to
one deck, so the existing endpoint answers it with no backend change.

Recorded so a later reader does not rely on the N+1 reasoning, and so nobody re-derives a
prohibition that was never there.

### C-26 — AC5's second surface is the share dialog, and three of the reasons it was skipped are wrong

Task 5 shipped the conversation surface and disclosed that AC5's verbatim text names two
("Conversation and collaboration surfaces warn…"). Its independent reviewer ruled on all three parts
and **refuted the author's reasoning by building the alternative**.

**It is a gap, but a narrow one, and the design doc constrains its shape.** The design doc at
`docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md:254-261` splits the
obligations more finely than the AC does: the **conversation surface warns**, while **history and
audit views group** the evidence by actor and release. §17.2:662 uses the **singular** — "the
shared-deck version warning" — and AC6 separately carries the grouping duty. So "collaboration
surfaces" denotes the sharing and history views, and the design assigns them grouping rather than
warning. This is a placement gap for one small component, not a missing capability, and it does not
block the ticket.

**The surface is the share dialog, and it needs no file outside Task 5's Files block.** The author
rejected it partly because `DeckContributorsManager.tsx` is outside its block — that objection is
mistaken. The dialog **body** is rendered by `AppLayout.tsx:1475-1499`, which the block already
owns. The reviewer proved it by building a probe that edited only `AppLayout.tsx` and
`MixedReleaseWarning.tsx`, both owned.

**The duplicate-accessible-name argument is refuted, measured three ways.** Coexistence is real
(`dialog_open_and_both_placements_visible = true`), but the conclusion that no disambiguation
escapes Playwright's case-insensitive substring matching is false: (a) a **distinct wording** rather
than a suffix escapes entirely — with both placements live, `change_provenance_count = 1` and
`who_changed_count = 1` under Playwright's *default* matching; (b) `exact: true` rescues even a pure
suffix, and **11 spec files in this repo already use it**, for example
`deck-prompts-ui.spec.ts:322`; (c) container-scoped locators work, and the repo already scopes
against this very overlay class at `slide-operations-ui.spec.ts:399`. The author considered only
suffixes.

Incidental evidence that the application already lives with this class of collision:
`getByRole('button', {name:'Share'})` resolves to two elements because it also matches the
deck-title button "Shared deck".

**The one real obstacle the author did not name**, and which the fix must handle: the conversation's
copy sits behind the overlay, so it is not *clickable* while the dialog is open. That is an overlay
property and is fixed by scoping the locator, not by renaming.

Cost if wrong: a second placement that duplicates an accessible name and makes an existing
conversation-surface assertion ambiguous — which is why the fix must assert the disambiguation
rather than assume it.

### C-27 — EPIC-WIDE: a mutation harness must assert its anchor count

Found by #262 Task 5's fix round, and it generalises to every mutation this epic still runs.

Its N1 mutation anchor used six-space indentation, copied from a `loadFailed` branch, while the
main return's root `<div>` sits at four. The harness reported **`anchor count 0`** and refused to
patch, so the mis-aim surfaced immediately.

The insight is what would have happened otherwise: **had the anchor been merely non-unique rather
than absent, a `replace(..., 1)` would have silently mutated the wrong element and produced a RED
that proves something else entirely.** A mis-aimed mutation that still REDs is worse than one that
REDs nothing, because nothing about the result looks wrong — you get a green-to-red transition and
a plausible story, and the clause you meant to pin stays unguarded.

**Binding rule: any mutation harness in this epic asserts the number of anchor matches before
patching, and fails on any count other than the one expected.** Zero means the aim is wrong; more
than one means the patch location is ambiguous. Both must stop the run rather than proceed.

This is the third consecutive round on that task where the implementer's first aim was wrong, and
the anchor-count assertion is what caught it every time — which is also why "I hit a zero and
re-aimed" has been such a reliable quality signal in this epic: the agents that report zeros are
the ones whose harnesses can detect them.

Cost if wrong: a clause recorded as guarded by a mutation that actually exercised a different line.

### C-29 — EPIC-WIDE: an anchor-count assertion is necessary but NOT sufficient

C-27 required every mutation harness to assert its anchor count, on the grounds that a non-unique
anchor silently mutates the wrong line and yields a RED proving something else. That rule is right
and it has already caught four mis-aims. Slice 4B found its limit.

Its **M9d REDed nothing with a perfectly correct anchor count of 1.** The patch filtered the session
IDs out of `**dict(record)` in the build-reviewer re-fan — the right line, uniquely matched — while
the explicit re-declaration immediately below **silently restored them**. The mutation was
syntactically precise and semantically inert.

**So the anchor count proves you patched the line you aimed at. It does not prove the patch changed
behaviour.** A zero with a correct anchor count means one of two things and you must distinguish
them: your aim is wrong, or your aim is right and something downstream compensates. The second is
the more dangerous reading, because the compensating path is usually the thing your clause was
supposed to pin.

**Binding addition: when a mutation REDs nothing at a correct anchor count, prove the patch was
observed** — assert the mutated value actually reaches the assertion under test, or mutate the
compensating path as well. Do not record the zero and move on, and do not conclude the clause is
unguarded without that check. Slice 4B re-aimed to M9e rather than reporting a blank, which is the
correct handling.

Cost if wrong: a clause recorded as unguarded when it is guarded, or recorded as guarded by a
mutation that never changed anything.

### C-30 — C-9's slice-4B file list was incomplete; nodes.py and routers.py are required

**Controller error.** C-9 defined slice 4B's Modify list as `agent_runtime_identity.py`,
`agent_runtime.py`, `graph/builder.py`, `graph/state.py` and `tests/unit/test_graph_nodes.py`. That
list cannot satisfy the bullets it was written to scope.

**Six of plan Task 4 bullet 1's seven named handoffs live in `src/services/graph/nodes.py`**, and the
`dict(record)` re-fan that bullet 2 names explicitly lives in `src/services/graph/routers.py`.
Neither file appears in C-9's list for either slice, nor in the plan's own Task 4 Files block — so
the omission is inherited from the plan and C-9 reproduced it rather than catching it.

Slice 4B exceeded the list by exactly those two files and disclosed it. Both are disjoint from slice
4A's surface and from #265's integrated diff, so nothing collided. **Ruling: the two files are added
to slice 4B's authorized set retroactively.** This is the same class as C-18 — a boundary written
from the plan's text rather than from the code the text describes.

Cost if wrong: an implementer either stops and asks on a boundary that was never satisfiable, or
exceeds it silently. Disclosing it was the right response to a defective list.

### C-31 — plan Task 4 bullet 2's isolation requirement is self-contradictory as worded

Bullet 2 requires a sabotage that removes root/actor/release from the reviewer's `dict(record)`
re-fan such that "only the re-review identity test must go RED". Slice 4B measured that this is
unachievable as written, and the reason is in the plan itself.

**Two distinct clauses share that one expression**: the reviewer must *receive* the provenance, and
the re-fan must *re-declare* it from state rather than trust a checkpointed record. Any sabotage of
that expression REDs both, because both are true properties of the same line. The literal version —
stripping the release as well — REDs **six pre-existing tests**. And making the re-fan the *sole*
source would require `build_branch_payload` not to declare the IDs, which bullet 2 **also mandates**.

**Ruling: the achievable and correct reading is the discrimination the requirement protects, not the
count it names.** Slice 4B's best-aimed variant, M9e, REDs three tests — all three re-fan and trace
tests — with **zero pre-existing tests and zero other node's identity test** affected. That is
precisely the property "only the re-review identity test" was reaching for: the sabotage must not
disturb any other node's identity handling. Accept three REDs with that isolation over one RED that
cannot exist.

Cost if wrong: a reviewer holds the slice to a literal count that no implementation can produce, and
the loop burns rounds on an unsatisfiable clause.

### C-32 — CORRECTS #264's correction 41: this is a BREACHED WRITTEN CONTRACT, not an uncovered surface

**Controller error, and it matters because the wrong framing would have sent both whole-branch
reviews looking for a policy decision instead of a violation.**

Correction 41 in #264's ledger states that "neither ticket's privacy contract covers application
logs". That is false. `docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md:21` covers
it explicitly, by closed allow-list, and names the prohibited category verbatim:

> Production identity handling is a structured application-log sink containing **only** graph
> version, release ID, role, revision ID, content hash, outcome, and error class; **it never logs
> payload, prompt, output, session/user ID**, tools, or slide HTML, and writes no Lakebase/UC trace
> row.

Seven permitted fields, and "session/user ID" named as prohibited. The controller verified every
link in the chain:

- `AgentInvocationIdentity` now has **seven** fields, two of which are `root_session_id` and
  `actor_session_id`.
- `LoggingAgentInvocationIdentitySink` logs `**identity.__dict__`, so both reach the record.
- The guard at `tests/unit/test_persisted_agent_runtime.py:839` is
  `for forbidden in ("prompt", "payload", "output", "session_id", "user_id", "response"): assert not
  hasattr(record, forbidden)` — an **exact attribute-name** check. `hasattr(record, "session_id")` is
  False while both new fields are present, so the needle misses.
- **The suite passes: 75 passed.** A documented prohibition was breached and nothing went red.

That is correction C-24's failure class one level up: a guard that checks a **name** rather than a
**property**. C-24 concerned a test importing the constant it asserts; this is a test forbidding a
literal field name rather than pinning the permitted set.

**Ruling: this is Critical and the fix is not optional.** Replace `**identity.__dict__` with an
explicit `_LOGGED_FIELDS` allow-list, and replace the name-forbidding guard with one that asserts
the **exact emitted field set** — which closes the naming weakness permanently rather than adding
one more needle. The plan's bullet 2 requires the fields on the *identity*; it does not require the
*sink* to emit them, so nothing in the plan is sacrificed by the fix.

If the identifiers are instead to be accepted in the log, the #261 plan text and that guard must be
amended **explicitly and by the user**, since the prohibition traces to a PRD amendment. Silent
acceptance is the one outcome to refuse.

Latency note, not mitigation: this is latent only because the root logger sits at WARNING, which
flips the moment anyone calls the `setup_logging()` that already exists in the repo.

Cost of the original error: both whole-branch reviews would have weighed a policy question that had
already been decided in writing, and the naming-based guard would have survived to miss the next
field too.

### C-33 — EPIC-WIDE, and it patches a hole in my own C-32: back up the MUTABLE SET, not the current drift

C-32 (in #264's ledger) told agents to re-take `cp` backups after any commit. Slice 4B followed it and
was bitten anyway, because the rule named *when* to re-take without naming *what to enumerate*.

Its harness enumerated the backup set from `git diff --name-only HEAD` — which, **immediately after a
commit, lists nothing**. So the re-take produced an **empty** backup set, `state.py` was mutated by M5
and never restored, and every later mutation ran on a poisoned tree.

**The detection signature is worth as much as the rule:** it surfaced because M23 through M26, touching
**three unrelated files**, all REDed the **same four** `TestARealTurn` tests. A phantom common RED set
across unrelated mutations means your tree is dirty, not that you found a common cause.

**Binding, and it supersedes C-32's enumeration step:** back up the **mutable set** — the files the run
intends to touch — rather than whatever currently differs from HEAD. And make `restore()`
**self-enforcing**: assert the tree came back (porcelain against the snapshot contract) and **abort the
run** rather than continue. Slice 4B's harness now does both, re-ran all 31 mutations from scratch, and
reported 31 anchor counts as expected, 30 RED, 1 deliberate blank, 0 restore aborts.

This is the third distinct trap in this family — C-27 (assert the anchor count), C-32 (re-take after a
commit), and now the enumeration source. Each was found by a different agent, and each was found
because someone disbelieved a number rather than banking it.

Cost of my original error: an agent obeying C-32 exactly could produce an empty backup set and never
know.
