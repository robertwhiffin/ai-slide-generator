# Graph Release Preview and Atomic Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: use `executing-plans-tellr` and `superpowers:subagent-driven-development` together. The spec and issue are binding; this plan is a hypothesis until Task 0 records code-verified corrections. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give administrators a dedicated Review & Publish page that previews every changed Agent Definition with field-level diffs and exact readiness, and publish the whole shared Graph Draft as one immutable seven-definition Graph Release in one PostgreSQL transaction that serializes with draft saves, conversation creation, verdicts, and evidence cleanup.

**Architecture:** A new `_GraphConfigurationPublication` mixin (composed into the existing `GraphConfiguration` facade) owns one gate-parametrized publication core, `_commit_locked_publication`, that materializes-or-reuses revisions by content hash, allocates the next Graph Version, closes the old SCD2 interval, inserts the new release and all seven mappings, links evidence, and rebases the draft. `publish_draft` is the draft-driven caller: it takes the **same** parent lock statement as the one locked draft writer (`_lock_current_parents(exclusive=True)`), runs the writer's own two validator tuples over every changed candidate, and delegates evidence to an injected `PublicationEvidenceGate`. Phase A (Tasks 1–3) builds and race-proves the core with a no-evidence test gate; Phase B (Tasks 4–8) binds the production `ApprovalEvidenceGate` to #267/#268 evidence, adds preview/publish HTTP routes, the React page, and the end-to-end acceptance seam. #270 rollback becomes a second thin caller of the same core with a `historical_restore` gate.

**Tech Stack:** Python 3.11, SQLAlchemy 2, PostgreSQL 15/Lakebase (SQLite only for unit/route tests), FastAPI, Pydantic v2, React 19, TypeScript 5.9, react-router-dom, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` §§5.1–5.6, 11.3–11.4, 12, 13.1–13.2, 14–17. **Binding issues:** #269 (all ten acceptance criteria), #258; contracts consumed from #262, #264, #265, #267, #268; contracts exposed to #270 and #271.

## Global constraints and execution protocol

- Task 0 runs before any implementation dispatch. It creates `.superpowers/sdd/2026-09-25-graph-release-publication/PLAN-CORRECTIONS.md`, whose **first line says it overrides this plan**, and records a cause-based baseline. Attach that exact file to **every** implementer and reviewer brief. `.superpowers/` is gitignored (`.gitignore:101`); never commit SDD evidence.
- **Phase A** (Tasks 1–3) is implementable on the current integration head (`feat/langgraph-core` containing #259–#265; plan written at `c040dbde0`). It creates only publication/core files and touches no #267/#268-owned file. **Phase B** (Tasks 4–9) starts only after the Task 0 phase-B re-probe passes against one concrete **local** integration commit containing reviewed #266, #267, and #268. Record immutable `TASK1_BASE` (before Task 1) and `INTEGRATION_BASE` (before Task 4) as distinct files; never overwrite either; rebase Phase A commits above `INTEGRATION_BASE` and prove `INTEGRATION_BASE..HEAD` is exactly rebased Tasks 1–3 plus Tasks 4–8.
- Every #267/#268 fact below is labelled **"assumed from the draft plan, re-probe at Task 0 phase B"**. The drafts are the user's untracked files in the main worktree (`docs/superpowers/plans/2026-09-23-agent-test-case-runs.md`, `2026-09-23-test-evidence-readiness.md`, `2026-09-23-agent-test-case-runs-CORRECTIONS.md`). Read them from `/Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/docs/superpowers/plans/`; never modify, move, copy into git, or commit them. Where the drafts are silent this plan does not invent their shape; it names the gap as an open question.
- Invoke `/Users/robert.whiffin/.pyenv/shims/python -m pytest` exactly, with `PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr` where `<worktree>` is the absolute worktree path. Run `test ! -e .venv` before and after every backend gate. Never run `pip`, `uv`, `npm install`, or create an environment: the pyenv site-packages is shared with parallel agents.
- PostgreSQL gates use `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres` (the `postgres_engine` fixture at `tests/integration/conftest.py:235` creates and drops a throwaway `tellr_int_*` database). Never connect to or modify the dev database `ai_slide_generator`.
- Every new PostgreSQL file starts `pytestmark = pytest.mark.postgres`, is named in the `integration-graph` job's `run:` block in `.github/workflows/test.yml` (currently lines ~447–474), is accepted by `tests/unit/test_ci_collects_integration_tests.py`, and executes with **zero skips** recorded per file. Concurrency assertions prove backend PIDs, observed waiting (`pg_stat_activity.wait_event_type = 'Lock'` **and** `pg_blocking_pids(waiter)` containing the blocker's PID), exact identities, content, hashes, intervals, pins and evidence — never counts alone.
- Run Playwright only from `frontend` with checked-in dependencies: `(cd frontend && npx playwright test <spec> --project=chromium --workers=1)`. Never run `npx` at the repository root.
- Preserve every existing contract: the four-argument `AgentRuntime.run`, exact-ID `PersistedGraphReleaseLoader`, no-fallback runtime, #263's `stale_draft` 409 family, `invalid_draft` 422 envelope, #264/#265 validators and upgrades, #261/#262 `lock_active_graph_release` protocol, and the PostgreSQL mutation guards installed by `_install_graph_configuration_mutation_guards` (`src/core/database.py:935–1081`).
- **One draft writer.** Publication does not add a second draft-content writer. It reuses `_lock_current_parents(exclusive=True)` (the writer's lock statement), the writer's `local_candidate_validators` / `post_stale_validators` tuples, and a parent-audit helper extracted from `_write_locked_content`. It writes only the draft **parent** row (`base_release_id`, `lock_version`, `updated_by`, `updated_at`); it never writes `graph_draft_agent`.
- Before each task record `TASK_BASE=$(git rev-parse HEAD)`; after implementation, fixes, and restored controller sabotage record `TASK_HEAD`; generate the review package from exactly `TASK_BASE..TASK_HEAD` (never `HEAD~1`). Every controller and reviewer sabotages the **different** production seam assigned in the task, verifies the marker with `rg` on the executed path, captures real RED, restores exactly, proves marker removal and a clean diff, and captures GREEN. Tell the reviewer which sabotage the controller already ran.
- All SDD artifacts (corrections, bases, briefs, reports, packages) live under `.superpowers/sdd/2026-09-25-graph-release-publication/`.
- Local merge only. No push, PR, remote merge, publish, or GitHub write is part of this plan.

## Verified code facts this plan relies on (file:line at `c040dbde0`)

| Symbol | Location | Fact the plan depends on |
|---|---|---|
| `AgentDefinitionRevision` | `src/database/models/graph_configuration.py:152–183` | `uq_agent_definition_revision_agent_hash (agent_key, content_hash)` and `uq_agent_definition_revision_id_agent (id, agent_key)` |
| `GraphRelease` | same file `:186–238` | `version_number` unique; `ck_graph_release_interval` is **strict** `effective_to > effective_from`; partial unique index `uq_graph_release_one_active` on `effective_to IS NULL` (PostgreSQL **and** SQLite, `:231–237`) |
| `GraphReleaseAgent` | same file `:241–267` | PK `(graph_release_id, agent_key)`; composite FK to `(revision.id, revision.agent_key)` `ON DELETE RESTRICT` |
| `GraphDraft` | same file `:270–297` | singleton `id = 1`; `base_release_id` FK; `lock_version >= 0` |
| `GraphDraftAgent` | same file `:300–318` | PK `(graph_draft_id, agent_key)`; `candidate_hash` |
| `AgentTestCase` | same file `:321–363` | `id`, `agent_key`, `name`, `version`, `is_active`, `is_required`; unique `(agent_key, name, version)` |
| mutation guards | `src/core/database.py:935–1081` | revision/mapping rows reject UPDATE/DELETE; a release allows only its first `effective_to` NULL→non-NULL update; a **deferred** constraint trigger requires exactly one active release at commit |
| `_GraphConfigurationWorkbench.read_workbench` | `src/services/graph_configuration_workbench.py:179–186` | shared (`FOR SHARE`) parent locks |
| `_lock_current_parents` | same file `:188–238` | one statement `SELECT graph_release, graph_draft … WHERE effective_to IS NULL FOR UPDATE OF graph_release, graph_draft` (or `FOR SHARE`); **any row count ≠ 1 raises `GraphConfigurationIntegrityError`** (`:210–227`); requires `draft.base_release_id == release.id` (`:234–237`) |
| `_snapshot_locked_workbench` | same file `:240–361` | validates the active mapping, hash-validates all revisions and draft rows; `changed = draft_row.candidate_hash != revision.content_hash` (`:325`) |
| `_read_workbench_for_draft_write` | same file `:363–408` | parents `FOR UPDATE`, then the selected `graph_draft_agent` `FOR UPDATE` |
| `ActiveReleaseSnapshot`, `DraftMetadataSnapshot` | same file `:39–59` | frozen dataclasses reused by publication results |
| `_GraphConfigurationDraft.local_candidate_validators` / `post_stale_validators` | `src/services/graph_configuration_draft.py:250–256` | the two validator tuples (assembly, schema overlay; post-stale empty) |
| `_run_candidate_validators` | same file `:258–268` | raises `DraftContentRejected(*issues)` |
| `DraftValidationIssue`, `DraftContentRejected` | same file `:103–117` | issue triple `field/code/message` |
| `_draft_aggregate_snapshot` | same file `:736–752` | exact-seven draft snapshot |
| `_write_locked_content` | same file `:754–793` | the one writer; timestamp from `select(func.current_timestamp())` (`:767–773`); parent audit at `:774–776` |
| `_GraphConfigurationBootstrap._database_timestamp` | `src/services/graph_configuration_bootstrap.py:84–93` | same timestamp idiom as the writer |
| bootstrap reuse-by-hash | same file `:215–241` | lookup `(agent_key, content_hash)`, `validate_definition_hash`, `canonical_payload()` equality, else `revision_from_definition` |
| `_validate_current_graph` | same file `:121–199` | on every boot: every release has exactly seven mappings (`:129–157`) and `draft.base_release_id == active.id` (`:164–168`) — so an un-rebased draft bricks the next boot |
| `revision_from_definition`, `validate_definition_hash`, `definition_content_values` | `src/services/graph_configuration_content.py:100–112`, `:128–146`, `:71–81` | content seam |
| `GraphConfiguration` facade | `src/services/graph_configuration.py:44–49`, `__all__` `:57–79` | mixin composition |
| `lock_active_graph_release` | `src/services/conversation_pins.py:66–74` | `SELECT graph_release WHERE effective_to IS NULL FOR UPDATE`, `MAX_ACTIVE_RELEASE_LOCK_SCANS = 2` (`:55`): retries once when the publication handoff makes the locked row stop matching |
| pin call sites | `src/api/services/session_manager.py:759` (root/chat), `:897` (contributor), `:1245` (duplicate) | all four creation paths use the one locker |
| `PersistedGraphReleaseLoader` | `src/services/persisted_graph_release.py:91–139` | caches by release **id** (`:96`, `:104–105`, `:138`); new release ids never collide |
| `DefinitionContent.canonical_payload` | `src/services/graph_definition_manifest.py:281–290` | numeric-normalized payload (`0.7 == Decimal('0.700000')`) |
| `ModelConfiguration.temperature` | same file `:96` | `float | Decimal` — raw `model_dump` diffs would be false positives |
| admin router | `src/api/routes/agent_definitions.py:51–55` | prefix `/api/admin/agent-definitions`, `dependencies=[Depends(require_admin)]` |
| `require_draft_write_principal` | same file `:58–66` | 403 on blank principal |
| router registration | `src/api/main.py:23`, `:484` | `app.include_router(agent_definitions.router)` |
| response models | `src/api/schemas/agent_definitions.py:301–319` | `ActiveReleaseResponse`, `DraftMetadataResponse`; `DraftFieldErrorResponse` used by routes |
| PG test harness | `tests/integration/postgres_concurrency_helpers.py:32`, `:202–212` | `_WAIT_SECONDS`, `_await_lock_waiters` |
| creator harness | `tests/integration/test_mixed_release_creation_postgres.py:26–34`, `:125–126`, `:129–172`, `:175–190` | `CREATORS`, `_backend_pid`, `_create`, `_creator_patches` (importable underscore names) |
| workbench PG pattern | `tests/integration/test_agent_definition_workbench_postgres.py:164–190`, `:1280–1304` | PID capture by overriding `_lock_current_parents`; `after_cursor_execute` pause; `real_route_stack` fixture |
| route unit fixture | `tests/unit/test_agent_definition_workbench_routes.py:117–135`, `:137–157` | SQLite `StaticPool` + bootstrap; `_force_admin` |
| forbidden-action rule | `frontend/tests/fixtures/forbiddenActionNames.ts` | `FORBIDDEN_ACTION_STEMS` includes `review\s*&\s*publish|publish`; `ALLOWED_ACTION_NAMES` has 3 entries (asserted in `frontend/tests/e2e/agent-definition-workbench.spec.ts:1462`) |
| workbench header / right pane | `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx:31–48`, `:139–144` | header shows Graph Version, draft base, lock version |
| admin route gate | `frontend/src/App.tsx:27–33`, `:53` | `RequireAdmin`; only `/admin` exists |
| workbench client | `frontend/src/api/agentDefinitions.ts:328`, `:698–722` | `AgentDefinitionApiError`; settled-request memo cleared on settle |

**Probed facts (read-only):** SQLite `CURRENT_TIMESTAMP` has **one-second** resolution (probe returned `datetime(2026, 9, 25, 14, 19, 31)`), so a SQLite publish within the bootstrap second violates `ck_graph_release_interval`.

**Reasoned, not probed (Task 2's RED test must prove it):** under PostgreSQL READ COMMITTED, a statement `SELECT graph_release, graph_draft … WHERE graph_release.effective_to IS NULL FOR UPDATE` that waits behind a committing publication re-checks the updated `graph_release` row, finds `effective_to` no longer NULL, and returns **zero rows**; the current `_lock_current_parents` then raises `GraphConfigurationIntegrityError` (HTTP 500) instead of letting the waiter see the new release. `lock_active_graph_release` already retries for exactly this handoff; the draft/workbench parent lock does not.

## Consumed #267/#268 outputs (every row: assumed from the draft plan, re-probe at Task 0 phase B)

| Output | Assumed shape (draft source) | #269 use | If absent/different |
|---|---|---|---|
| ORM `AgentTestRun`, table `agent_test_run` in `src/database/models/graph_configuration.py` | columns `id`, `test_case_id`, `test_case_version`, `agent_key`, `candidate_hash`, `execution_status` (`'completed'`…), `deterministic_checks_passed`, `verdict` (`'approved'|'rejected'|NULL`), `verdict_reviewer`, `verdict_at`, `run_at` (#267 draft lines ~76–150) | eligible-approval predicate; `FOR UPDATE` evidence lock | stop; correct Task 4 in `PLAN-CORRECTIONS.md` |
| check `ck_agent_test_run_approved_only_if_completed_and_passing` | #267 draft DDL | publication still revalidates in code; does not rely on it | revalidation remains |
| ORM `GraphReleaseTestRun`, table `graph_release_test_run` | PK `(graph_release_id, agent_test_run_id)`; `evidence_kind IN ('approval','historical_restore')`; `source_release_id` non-null iff `historical_restore`; all FKs `ON DELETE RESTRICT` (#267 draft lines ~160–190; spec §5.5) | Task 4 inserts `approval` links | stop; ruling required |
| readiness result `DraftReadinessResult(draft_lock_version, base_release_id, all_ready, blocking_agents, agents[AgentReadinessItem(agent_key, candidate_hash, is_changed_from_base, ready, cases[TestCaseReadinessItem(agent_key, test_case_id, test_case_name, test_case_version, status, blocking, run_id, run_verdict, run_checks_passed)])])` | #268 draft lines ~112–160 | preview body; `publication_not_ready` body | Task 0-B records the real type |
| readiness entry point `AgentTestWorkbench.draft_readiness(session)` | #268 draft; `AgentTestWorkbench.__init__(*, runtime)` per #267 draft | called **inside** the publication transaction | **silent** on whether it begins/commits a transaction and whether it needs an `AgentRuntime` — Open question Q4 |
| readiness wire `DraftReadinessResponse` and `GET /api/admin/graph-draft/readiness` | #268 draft lines ~191–222 | embedded verbatim in preview and 409 | Task 0-B records model name/module |
| cleanup `cleanup_unpublished_test_runs(session, *, per_case_limit=20) -> int` taking `graph_draft` `FOR SHARE` before its `DELETE` | #268 draft lines ~225–243, ~586 | cleanup-vs-publication ordering tests | lock boundary must be the draft row — Q2 |
| verdict writer `record_verdict(session, *, run_id, verdict, reviewer, notes, actor)` locking the run row `FOR UPDATE` | #268 draft lines ~67–108, ~414 | verdict-vs-publication ordering tests | Q3 |
| test-run execution route `POST /api/admin/agent-definitions/draft/{agent_key}/test-runs` and verdict route `POST /api/admin/agent-test-runs/{run_id}/verdict`; `DeterministicFakeModelAdapter` | #267 draft lines ~345–360; #268 draft ~165 | Task 8 acceptance only | fake adapter location is ambiguous in the draft (`tests/fake_adapters.py` **or** `src/services/testing/…`) — record at Task 0-B |
| frontend readiness client/parser and six-value `DraftStatus` | #268 draft Task 6 | Review & Publish page renders readiness | client function **name is not specified** by the draft — record at Task 0-B |

Not assumed (drafts are silent or contradictory): which run represents a case when several eligible approvals exist; whether a test-case "version" is a new row with a new `id`; whether #268's verdict writer may change a verdict on a run already linked to a release; whether #267 test-case writers take any draft lock. See Open questions.

**Cross-plan conflicts found (need controller ruling before Phase B):** #268's draft Task 5 "extends the existing publication transaction in `_GraphConfigurationBootstrap.publish_draft`" and its Task 6 step 4 adds a readiness panel to "the existing Review & Publish page". Neither exists before #269 (the #267 CORRECTIONS file ADVISORY-4 confirms no publication method exists). This plan assumes the ruling in Q1: **#269 owns the publication transaction, evidence linking, and the page; #268 delivers readiness, verdicts and cleanup only.**

## Stable interfaces (produced by this plan)

`src/services/graph_configuration_publication.py` (new):

```python
EvidenceKind = Literal["approval", "historical_restore"]

@dataclass(frozen=True)
class EvidenceLink:
    agent_test_run_id: int
    agent_key: AgentKey
    test_case_id: int
    evidence_kind: EvidenceKind
    source_release_id: int | None

@dataclass(frozen=True)
class PublicationNotReady:
    #: The (agent_key, test_case_id) pairs the gate could not lock eligible evidence for,
    #: in GRAPH_V1_AGENT_KEYS order then test_case_id order.  Authoritative.
    locked_gaps: tuple[tuple[AgentKey, int], ...]
    #: #268's readiness result computed inside the same transaction, for the wire body.
    readiness: object

class PublicationEvidenceGate(Protocol):
    def lock_and_verify(
        self,
        session: Session,
        *,
        snapshot: GraphWorkbenchSnapshot,
        changed_agent_keys: tuple[AgentKey, ...],
    ) -> tuple[EvidenceLink, ...] | PublicationNotReady: ...

@dataclass(frozen=True)
class PublishedMapping:
    agent_key: AgentKey
    agent_definition_revision_id: int
    content_hash: str
    reused: bool          # True iff the revision row existed before this transaction

@dataclass(frozen=True)
class PublishedRelease:
    release: ActiveReleaseSnapshot            # the new active release
    previous_release_id: int
    changed_agent_keys: tuple[AgentKey, ...]
    mappings: Mapping[AgentKey, PublishedMapping]   # exactly seven
    evidence: tuple[EvidenceLink, ...]
    draft: DraftMetadataSnapshot              # rebased draft

@dataclass(frozen=True)
class PublicationConflict:
    expected_lock_version: int
    current_lock_version: int
    active_release_id: int
    active_version_number: int
    draft: DraftMetadataSnapshot

@dataclass(frozen=True)
class NothingToPublish:
    draft: DraftMetadataSnapshot
    active_release_id: int
    active_version_number: int

class PublicationRejected(ValueError):   # the 422 family; never reached after a write
    issues: tuple[DraftValidationIssue, ...]

PublicationOutcome = PublishedRelease | PublicationConflict | NothingToPublish | PublicationNotReady

class _GraphConfigurationPublication(_GraphConfigurationDraft):
    def publish_draft(self, session: Session, *, expected_lock_version: int,
                      release_note: str, actor: str,
                      evidence_gate: PublicationEvidenceGate) -> PublicationOutcome: ...
    def preview_release(self, session: Session, *, readiness: Callable[[Session], object]
                        ) -> ReleasePreview: ...          # Task 5
    def _commit_locked_publication(self, session: Session, *, release_row: GraphRelease,
                                   draft_row: GraphDraft, snapshot: GraphWorkbenchSnapshot,
                                   contents: Mapping[AgentKey, DefinitionContent],
                                   evidence: tuple[EvidenceLink, ...], release_note: str,
                                   actor: str, restored_from_release_id: int | None
                                   ) -> PublishedRelease: ...
```

`src/services/graph_configuration_content.py` gains `database_transaction_timestamp(session) -> datetime` and `materialize_or_reuse_revision(session, content, *, actor, timestamp) -> tuple[AgentDefinitionRevision, bool]` (Task 1).

`src/services/graph_release_evidence.py` (new, Task 4): `ApprovalEvidenceGate(readiness: Callable[[Session], object])` implementing `PublicationEvidenceGate`, plus `link_release_evidence(session, *, release_id, evidence)`.

HTTP (new router `src/api/routes/graph_releases.py`, same prefix and `require_admin` dependency as the workbench router; Task 5):

```
GET  /api/admin/agent-definitions/release-preview
POST /api/admin/agent-definitions/releases        body {"lock_version": 7, "release_note": "…"}
```

| Outcome | Status | Exact body |
|---|---|---|
| published | `201` | `{"release": ActiveReleaseResponse, "previous_release_id": int, "changed_agents": [AgentKey…], "mappings": {"<agent_key>": {"agent_definition_revision_id": int, "content_hash": sha256, "reused": bool} ×7}, "evidence": [{"agent_test_run_id": int, "agent_key": AgentKey, "test_case_id": int, "evidence_kind": "approval"}], "draft": DraftMetadataResponse}` |
| invalid request / blank note / candidate invalid at publish | `422` | `{"code": "invalid_publication", "errors": [{"field", "code", "message"}]}`; blank note is `{"field":"release_note","code":"blank","message":"Release note must not be blank."}`; malformed JSON is `{"field":"$","code":"invalid_json","message":"Request body must be valid JSON."}`; candidate issues use `field = "definitions.<agent_key>.<issue.field>"` in `GRAPH_V1_AGENT_KEYS` order then issue order |
| stale lock version | `409` | `{"code": "stale_publication", "expected_lock_version": int, "current_lock_version": int, "active_release": {"release_id": int, "version_number": int}, "draft": DraftMetadataResponse}` |
| nothing changed | `409` | `{"code": "nothing_to_publish", "active_release": {"release_id", "version_number"}, "draft": DraftMetadataResponse}` |
| readiness gap at lock time | `409` | `{"code": "publication_not_ready", "gaps": [{"agent_key", "test_case_id"}], "readiness": <#268 DraftReadinessResponse verbatim>}` |
| integrity failure | `500` | `{"detail": "Graph configuration is incomplete"}` (existing family) |

Check order inside `publish_draft`: strict request shape and non-blank note (before any lock) → parent locks → stale → nothing-to-publish → candidate validators → evidence gate → writes. A stale request never reaches readiness; a rejected request writes nothing.

## Lock ordering (every lock #269 takes, in order)

Global order, which every locker must acquire as an **ordered prefix-respecting subsequence**: **(L0) active `graph_release` row → (L0) `graph_draft` row → (L1) `graph_draft_agent` rows by `agent_key` → (L2) `agent_test_case` rows by `id` → (L3) `agent_test_run` rows by `id`.** No locker may take an earlier lock after a later one.

| # | Lock | Mode | Taken by publication | Other holders (and their mode) | Conflict that serializes | Proved by |
|---|---|---|---|---|---|---|
| L0 | active `graph_release` + `graph_draft`, one statement (`_lock_current_parents(exclusive=True)`, bounded 2-scan retry added in Task 2) | `FOR UPDATE OF graph_release, graph_draft` | first statement | draft writer: same statement, `FOR UPDATE` (`workbench.py:363`); workbench read and #268 readiness (assumed): `FOR SHARE` both; session creation: release only `FOR UPDATE` (`conversation_pins.py:58–63`); #268 cleanup (assumed): draft only `FOR SHARE` | the release row is the session/publication **linearization point** (spec §5.6); the draft row is the draft-write/cleanup/publication boundary (spec §5.5) | Task 2 (writer, reader, publisher×publisher both orders); Task 3 (all seven creators, both orders); Task 4 (cleanup both orders) |
| L1 | all seven `graph_draft_agent` rows, `ORDER BY agent_key` | `FOR UPDATE` | after L0 | draft writer: selected row `FOR UPDATE` after L0 | dominated by L0; defensive against any future writer that skips L0 | Task 1 PostgreSQL statement-sequence test |
| L2 | active required `agent_test_case` rows of changed roles, `ORDER BY id` | `FOR SHARE` | Phase B, inside the gate | #267 case writers (assumed; lock mode unspecified) | a case cannot be deactivated/re-versioned between readiness and link | Task 4 (case-version-bump-first ordering) |
| L3 | exact eligible approved `agent_test_run` rows, `ORDER BY id` | `FOR UPDATE` | Phase B, inside the gate | #268 verdict writer: `FOR UPDATE` (assumed); #268 cleanup: `DELETE` row locks, only **after** its L0 draft `FOR SHARE` (assumed) | a verdict flip either commits first (publication's re-check drops the row → `publication_not_ready`) or waits for publication | Task 4 (verdict-first and publication-first) |
| implicit | FK `FOR KEY SHARE` on referenced `agent_definition_revision`, `graph_release`, `agent_test_run` rows during inserts | automatic | during writes | #267 test-run insert references `compared_release_id` → `KEY SHARE` on the active release, which **conflicts with L0 `FOR UPDATE`** | #267 must not hold a transaction open across a model call (assumed; re-probe) | Task 0-B probe of #267's run transaction boundary |

Write order inside the transaction (after all locks): materialize/reuse revisions → flush → allocate version (`max(version_number) + 1`, must equal active + 1) → set old `effective_to` → **flush** (the non-deferrable partial unique index `uq_graph_release_one_active` forbids inserting the new active row first) → insert new release → flush → insert seven mappings → flush and read back → insert evidence links → rebase draft parent → flush → commit (deferred exactly-one-active trigger fires here).

Deadlock-freedom argument (the whole-branch reviewer must re-derive it): session creation holds only L0-release; cleanup holds L0-draft (`FOR SHARE`) then L3; verdict writes hold only L3 (a #268 writer that also needs the draft **must** take L0-draft first — Task 0-B probe); the draft writer holds L0 then L1; publication holds L0 → L1 → L2 → L3. All acquisitions follow the global order, so no cycle exists. The one mixed-order risk is the implicit FK `KEY SHARE` a #267 run insert takes on the release row; it is safe only while that insert's transaction takes no L0-draft/L3 lock before it.

## Seam and producer/consumer table

| Seam | Producer | Consumer(s) | Contract |
|---|---|---|---|
| `database_transaction_timestamp` | Task 1 (moved from `bootstrap.py:84–93` / `draft.py:767–773`) | bootstrap, draft writer, publication | returns tz-aware transaction timestamp; raises `GraphConfigurationIntegrityError` on `None` — byte-identical behaviour |
| `materialize_or_reuse_revision` | Task 1 (extracted from `bootstrap.py:215–240`) | bootstrap `_insert_complete_v1`, publication core, #270 rollback | reuse iff `(agent_key, content_hash)` exists **and** `canonical_payload()` equal; never flushes |
| `_advance_locked_draft` | Task 1 (extracted from `draft.py:774–776`) | `_write_locked_content`, publication rebase | the one parent-audit writer |
| `_commit_locked_publication` | Task 1 | `publish_draft` (Task 1), #270 `restore_release` | caller holds L0 and supplies all seven contents |
| `PublicationEvidenceGate` | Task 1 | Phase A tests (`_NoEvidenceGate`, test-only), Task 4 `ApprovalEvidenceGate`, #270 historical-restore gate | no default; the production route always constructs `ApprovalEvidenceGate` |
| handoff retry in `_lock_current_parents` | Task 2 | draft writer (#263/#264/#265 operations), `read_workbench`, publication, #268 readiness (assumed to reuse the read pattern), #270 | a zero-row scan is retried once; a second zero-row or any multi-row result raises as today |
| `link_release_evidence` | Task 4 | core step 9, #270 | inserts `graph_release_test_run` rows and reads them back exactly |
| preview/publish routes and wire | Task 5 | Task 6 client, Task 8 acceptance, #271 AC7 | tables above |
| `ReviewAndPublishPage` + route `/admin/agent-definitions/review` | Task 6 | Task 7 Playwright, #270 (adds History/Rollback tabs), #271 Playwright journey | stable `data-testid`s listed in Task 6 |
| `forbiddenActionNames.ts` allowed list | Task 7 | #263/#264/#265 sweeps (existing), #267/#268 edits (assumed to add run/approve exemptions first) | adds exactly `'Review & Publish'` |

Shared files with landed tickets and how #269 composes:

| File | Landed owner(s) | #269 change | Composition rule |
|---|---|---|---|
| `src/services/graph_configuration_draft.py` | #263, #264, #265 | Task 1: extract `_advance_locked_draft`, switch `:767–773` to `database_transaction_timestamp` | no validator/ordering/precedence change; all #263/#264/#265 draft suites stay green |
| `src/services/graph_configuration_workbench.py` | #260, #263 | Task 2: bounded retry in `_lock_current_parents` | same statement text; only the zero-row path changes |
| `src/services/graph_configuration_bootstrap.py` | #260 | Task 1: call the two extracted helpers | bootstrap suites byte-identical results |
| `src/services/graph_configuration.py` | #260/#263 | Task 1: add `_GraphConfigurationPublication` to the MRO, export new names | `GraphConfiguration(_GraphConfigurationPublication, _GraphConfigurationDraft, _GraphConfigurationWorkbench, _GraphConfigurationBootstrap)` |
| `src/services/conversation_pins.py`, `session_manager.py` | #261, #262 | **no change** | publication closes the same row they lock |
| `src/api/routes/agent_definitions.py`, `src/api/schemas/agent_definitions.py` | #263–#265, #267/#268 (assumed) | **no change** (new router/schemas module instead) | imports `require_draft_write_principal`, `ActiveReleaseResponse`, `DraftMetadataResponse`, `DraftFieldErrorResponse`, and #268's readiness response |
| `src/api/main.py` | many | Task 5: one `include_router` | registered after `agent_definitions.router` |
| `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx` | #263–#265, #267/#268 (assumed) | Task 6: header link + changed count only | no state-machine change |
| `.github/workflows/test.yml` | many | Tasks 1, 3, 4, 8: append four files | collection guard green |

## Rollback as a thin caller (#270)

#270 adds `restore_release(session, *, source_release_id, expected_lock_version, release_note, actor)` to the same mixin. It (1) takes L0 through the same `_lock_current_parents(exclusive=True)`; (2) returns `PublicationConflict` on a stale lock version; (3) loads the source release's seven revisions through `PersistedGraphReleaseLoader._validate_complete_snapshot` semantics (`persisted_graph_release.py:166–204`) and runs the same two validator tuples over each historical content as its structural validation; (4) calls a `HistoricalRestoreEvidenceGate` that locks the source release's `graph_release_test_run` rows' runs `FOR SHARE` and returns `EvidenceLink(evidence_kind="historical_restore", source_release_id=source_release_id)` for each; (5) calls `_commit_locked_publication(..., contents=<historical contents>, evidence=<historical links>, restored_from_release_id=source_release_id)`. Because the core reuses revisions by `(agent_key, content_hash)`, every historical revision is reused with `reused=True`, the next version is `max + 1` (v8 restores v3), no interval is reopened, and the draft is rebased. #269 pins this seam with a core unit test that writes `restored_from_release_id` verbatim and accepts `historical_restore` links (Task 1 for the release column; Task 4 for the link kind). What rollback does to draft **content** is #270's decision (Q7); the core only rebases the parent.

## Seams #271 AC7 needs from #269

1. The HTTP pair `GET /release-preview` and `POST /releases` with the exact bodies above (Task 5), exercised end-to-end on real PostgreSQL by Task 8's acceptance test, which #271 extends rather than rewrites.
2. `GraphConfiguration().publish_draft(..., evidence_gate=ApprovalEvidenceGate(...))` with no test-only default gate; Task 5's route test asserts the gate type the route constructs.
3. `PublishedRelease.mappings` / `.evidence` expose exact revision and run ids so a later trace/loader assertion can be keyed to them.
4. Conversation pinning needs no new API: `SessionManager.create_session(..., graph_capable=True)` after publication pins the new id (Task 8 proves it).
5. The Review & Publish page at `/admin/agent-definitions/review` with stable `data-testid`s and mock contracts in its own Playwright spec (Tasks 6–7).
6. `_commit_locked_publication` for #270, so #271's "roll back and observe a new Graph Version" reuses the same core.

## Review Focus

1. **Second-resolution clocks.** On SQLite (route/unit tests) a publish in the same second as bootstrap would violate the strict `ck_graph_release_interval`. Expect an explicit `GraphConfigurationIntegrityError("publication timestamp does not follow the active release interval")` before any write, and unit fixtures that backdate v1 by one hour. PostgreSQL asserts exact contiguity `old.effective_to == new.effective_from == new.published_at == draft.updated_at`. Tests: Task 1 Steps 1 and 5.
2. **A request queued behind a publication.** A draft save or workbench read that waits on L0 while a publication commits must see the new release (409 `stale_draft` naming the rebased draft / a coherent new snapshot), never a 500. Test: Task 2.
3. **Content that reverts to an older release.** A changed role whose saved content equals a revision from an earlier (non-base) release must reuse that revision (`reused: true`), not hit the unique index as a 500. Test: Task 1 Step 5.
4. **Double-submit / retry after success.** A second POST with the same `lock_version` after a successful publish must be 409 `stale_publication` naming the just-created release, never a second release. Test: Task 2 (sequential) and Task 2 (concurrent).
5. **Whitespace-only or untrimmed release notes.** `"   "` → 422 before any lock; `"  keep  "` is stored verbatim. Test: Task 1 Step 1, Task 5.

---

## Task 0: Correct the plan against code and record cause baselines

**Files (ignored execution evidence only):**
- `.superpowers/sdd/2026-09-25-graph-release-publication/PLAN-CORRECTIONS.md`
- `.superpowers/sdd/2026-09-25-graph-release-publication/TASK1_BASE`
- `.superpowers/sdd/2026-09-25-graph-release-publication/INTEGRATION_BASE`
- `.superpowers/sdd/2026-09-25-graph-release-publication/predecessor-heads.md`
- `.superpowers/sdd/2026-09-25-graph-release-publication/reports/`
- `.superpowers/sdd/2026-09-25-graph-release-publication/packages/`

- [ ] **Step 1: Resolve the workspace and base.** Record `git rev-parse HEAD` in immutable `TASK1_BASE`; prove `c040dbde0` (Merge #264) is its ancestor; record whether #265's merge is an ancestor; run `test ! -e .venv`; confirm `/Users/robert.whiffin/.pyenv/shims/python --version` is 3.11.

- [ ] **Step 2: Write the Phase A corrections table.** First line: `This file overrides docs/superpowers/plans/2026-09-25-graph-release-publication.md wherever they disagree.` Re-verify every row of "Verified code facts" with `sed -n`/`rg` and record the actual lines. Add one row per task for internal consistency and one per shared file/seam in the seam tables. Rule on every mismatch before Task 1. Minimum probes:

```bash
W=/Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/.worktrees/issue-269-plan
rg -n "def _lock_current_parents|def _snapshot_locked_workbench|def _read_workbench_for_draft_write|def read_workbench" $W/src/services/graph_configuration_workbench.py
rg -n "local_candidate_validators|post_stale_validators|def _write_locked_content|current_timestamp|lock_version \+= 1" $W/src/services/graph_configuration_draft.py
rg -n "def _database_timestamp|content_hash == content_hash|canonical_payload" $W/src/services/graph_configuration_bootstrap.py
rg -n "MAX_ACTIVE_RELEASE_LOCK_SCANS|def lock_active_graph_release" $W/src/services/conversation_pins.py
rg -n "lock_active_graph_release" $W/src/api/services/session_manager.py
rg -n "def publish|publish_draft|GraphReleaseTestRun|agent_test_run" $W/src || echo "publication and evidence absent: expected in Phase A"
rg -n "ALLOWED_ACTION_NAMES|toHaveLength\(3\)" $W/frontend/tests
```

- [ ] **Step 3: Record baseline causes, not counts.** Run, each preceded and followed by `test ! -e .venv`:

```bash
cd $W && PYTHONPATH=$W:$W/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_graph_configuration_bootstrap.py tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_configuration_models.py tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_conversation_pin_creation.py \
  tests/unit/test_persisted_graph_release.py tests/unit/test_ci_collects_integration_tests.py
for f in test_graph_configuration_bootstrap_postgres test_graph_configuration_constraints_postgres \
         test_agent_definition_workbench_postgres test_agent_schema_overlay_postgres \
         test_conversation_pin_creation_postgres test_mixed_release_creation_postgres \
         test_conversation_pin_acceptance_postgres test_persisted_graph_runtime_failures_postgres; do
  TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  PYTHONPATH=$W:$W/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -rs tests/integration/$f.py
done
(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench)
(cd frontend && npm run typecheck)
```

Record every failing node ID with its first causal assertion/traceback and every skip with its reason in `reports/preflight-phase-a.md`. A skip in any PostgreSQL file is a blocker, not a baseline.

- [ ] **Step 4 (phase B re-probe, before Task 4).** After reviewed #266, #267 and #268 are integrated **locally**, record `INTEGRATION_BASE` and each predecessor's final reviewed head in `predecessor-heads.md` (prove each is an ancestor — do not use mid-PR SHAs; see #267 CORRECTIONS ADVISORY-3), rebase Tasks 1–3 above it, and prove `INTEGRATION_BASE..HEAD` is exactly the rebased Tasks 1–3. Re-probe and record, for every row of "Consumed #267/#268 outputs": the exact ORM class, columns, constraint names, method signatures, whether `draft_readiness` opens/commits its own transaction, whether it needs an `AgentRuntime`, the cleanup lock statement text, the verdict writer lock order (does it lock `graph_draft` and in which order?), the #267 test-run insert transaction boundary relative to the model call, the fake adapter location, the readiness wire model and frontend client names, and whether #268 shipped any publication code or Review & Publish page despite Q1. Minimum probes:

```bash
PYTHONPATH=$W:$W/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -c "
from src.database.models.graph_configuration import AgentTestRun, GraphReleaseTestRun
print(sorted(c.name for c in AgentTestRun.__table__.columns))
print(sorted(c.name for c in GraphReleaseTestRun.__table__.columns))
print(sorted(c.name for c in AgentTestRun.__table__.constraints if c.name))"
rg -n "def draft_readiness|def record_verdict|def cleanup_unpublished_test_runs|with_for_update|session.begin" $W/src/services/agent_test_workbench.py
rg -n "class DraftReadinessResponse|readiness" $W/src/api/schemas $W/src/api/routes
rg -n "DeterministicFakeModelAdapter" $W/src $W/tests
rg -n "readiness|DraftStatus" $W/frontend/src/api/agentDefinitions.ts $W/frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts
rg -n "def publish|Review & Publish|graph_release_test_run" $W/src $W/frontend/src
```

Re-derive every baseline cause after the integration (ORM/schema changed). Do not dispatch Task 4 until every consumed row is ruled on.

---

## Task 1: Publication core, shared helpers, and atomic single-publisher behaviour

**Files:**
- Modify: `src/services/graph_configuration_content.py` (add `database_transaction_timestamp`, `materialize_or_reuse_revision`)
- Modify: `src/services/graph_configuration_bootstrap.py:84–93`, `:208`, `:215–241` (call the helpers)
- Modify: `src/services/graph_configuration_draft.py:754–793` (extract `_advance_locked_draft`; use `database_transaction_timestamp`)
- Create: `src/services/graph_configuration_publication.py`
- Modify: `src/services/graph_configuration.py:11–79` (MRO and exports)
- Create: `tests/unit/test_graph_release_publication.py`
- Create: `tests/integration/test_graph_release_publication_postgres.py`
- Modify: `.github/workflows/test.yml` (append the new PostgreSQL file to `integration-graph`)

**Interfaces:**
- Consumes: `_lock_current_parents`, `_snapshot_locked_workbench`, the two validator tuples, `revision_from_definition`, `validate_definition_hash`, `DefinitionContent.canonical_payload`.
- Produces: everything in "Stable interfaces" except `preview_release`, plus `database_transaction_timestamp(session) -> datetime`, `materialize_or_reuse_revision(session, content, *, actor: str, timestamp: datetime) -> tuple[AgentDefinitionRevision, bool]`, `_GraphConfigurationDraft._advance_locked_draft(draft_row: GraphDraft, *, actor: str, timestamp: datetime) -> None`.

- [ ] **Step 1: Write RED unit tests (SQLite).** In `tests/unit/test_graph_release_publication.py` reuse the route-test engine recipe (`tests/unit/test_agent_definition_workbench_routes.py:117–135`) and backdate v1 because SQLite timestamps have one-second resolution:

```python
class _NoEvidenceGate:
    """Phase A only. Publishes without approval evidence; never constructed by a route."""
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
    def lock_and_verify(self, session, *, snapshot, changed_agent_keys):
        self.calls.append(tuple(changed_agent_keys))
        return ()

def _backdate_v1(factory) -> None:
    with factory.begin() as db:  # SQLite has no mutation-guard triggers
        db.execute(text("UPDATE graph_release SET effective_from = datetime('now','-1 hour'), "
                        "published_at = datetime('now','-1 hour') WHERE version_number = 1"))

def _save_prompt(factory, agent_key, suffix, *, lock):
    service = GraphConfiguration()
    with factory() as db:
        snap = service.read_workbench(db); db.rollback()
    content = next(n for n in snap.nodes if n.agent_key == agent_key).draft.content
    with factory() as db:
        out = service.save_editable_model_draft(
            db, agent_key=agent_key, expected_lock_version=lock, actor="editor@example.com",
            candidate=EditableModelDraft(prompt_text=content.prompt_text + suffix,
                endpoint_name=content.model.endpoint_name, temperature=float(content.model.temperature),
                max_tokens=content.model.max_tokens, top_p=float(content.model.top_p)))
    assert isinstance(out, DraftSaveResult)
    return out
```

Tests (each asserts exact ids/values, not counts):
- `test_publish_two_changed_roles_creates_v2_with_exact_seven_mappings`: save architect and builder (locks 0→1→2), `publish_draft(expected_lock_version=2, release_note="Tune two roles", actor="publisher@example.com", evidence_gate=gate)`; assert `PublishedRelease.release.version_number == 2`, `previous_release_id == v1.id`, `changed_agent_keys == ("architect", "builder")`, `gate.calls == [("architect", "builder")]`, mappings for the five unchanged roles equal v1's revision ids with `reused is True`, architect/builder ids are new with `reused is False` and `content_hash == definition_content_hash(saved content)`; v1 `effective_to == v2.effective_from == v2.published_at`; draft `base_release_id == v2.id`, `lock_version == 3`, `updated_by == "publisher@example.com"`; `read_workbench` afterwards shows every node `changed is False` and `active_release.release_id == v2.id`; `GraphConfiguration().bootstrap_v1(factory)` afterwards returns `BootstrapResult(False, v2.id, 2)`.
- `test_stale_lock_version_returns_conflict_and_writes_nothing`: expected lock 1 while current is 2 → `PublicationConflict(expected_lock_version=1, current_lock_version=2, active_release_id=v1.id, active_version_number=1, draft=<current>)`; revisions/releases/mappings/draft rows identical before/after; `gate.calls == []`.
- `test_nothing_changed_returns_nothing_to_publish`: fresh bootstrap, expected lock 0 → `NothingToPublish`; no writes; gate not called.
- `test_blank_note_and_bad_types_reject_before_any_lock` (parametrize `""`, `"   "`, `None`, `7`; lock `-1`, `True`; actor `""`) → `PublicationRejected` with exact ordered issues (`actor`, `lock_version`, `release_note`); assert (spy on `_lock_current_parents`) that the lock was never attempted — SQLite does not render `FOR UPDATE`, so a SQL-text assertion here would be vacuous — and nothing was written.
- `test_note_is_stored_verbatim`: `"  keep  "` stored exactly.
- `test_invalid_changed_candidate_rejects_with_prefixed_issues`: monkeypatch `_GraphConfigurationPublication.local_candidate_validators` to `(lambda c: (DraftValidationIssue("candidate.prompt_text", "x", "X."),) if c.agent_key == "builder" else (),)` → `PublicationRejected.issues == (DraftValidationIssue("definitions.builder.candidate.prompt_text", "x", "X."),)`; gate not called; no writes.
- `test_gate_not_ready_writes_nothing`: gate returns `PublicationNotReady(locked_gaps=(("architect", 1),), readiness="sentinel")` → returned verbatim; no writes.
- `test_core_writes_restored_from_verbatim` (seam for #270): call `_commit_locked_publication` directly inside `session.begin()` after `_lock_current_parents(exclusive=True)` with `restored_from_release_id=v1.id` and v1 contents → new release `restored_from_release_id == v1.id`, all seven `reused is True`.
- `test_same_second_timestamp_raises_before_write`: without backdating, publish → `GraphConfigurationIntegrityError("publication timestamp does not follow the active release interval")`; no writes.
- `test_bootstrap_and_writer_behaviour_unchanged_after_helper_extraction`: run the existing `tests/unit/test_graph_configuration_bootstrap.py` and `tests/unit/test_graph_configuration_draft.py` in the gate (no new test body; listed so the reviewer checks it).

- [ ] **Step 2: Run RED.** `test ! -e .venv`; `PYTHONPATH=$W:$W/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_graph_release_publication.py`; `test ! -e .venv`. Expected: `ModuleNotFoundError: src.services.graph_configuration_publication`.

- [ ] **Step 3: Extract the helpers.** In `graph_configuration_content.py`:

```python
def database_transaction_timestamp(session: Session) -> datetime:
    """The one tz-aware transaction timestamp used by every graph-configuration writer."""
    timestamp = session.scalar(select(func.current_timestamp()))
    if timestamp is None:
        raise GraphConfigurationIntegrityError("database did not return a transaction timestamp")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def materialize_or_reuse_revision(
    session: Session, content: DefinitionContent, *, actor: str, timestamp: datetime,
) -> tuple[AgentDefinitionRevision, bool]:
    """Return the immutable revision for ``content``: reused (False) or newly added (True).

    Never flushes; the caller flushes once for the whole release.
    """
    content_hash = definition_content_hash(content)
    revision = session.scalar(
        select(AgentDefinitionRevision).where(
            AgentDefinitionRevision.agent_key == content.agent_key,
            AgentDefinitionRevision.content_hash == content_hash,
        )
    )
    if revision is None:
        revision = revision_from_definition(content, actor=actor, timestamp=timestamp)
        session.add(revision)
        return revision, True
    existing = validate_definition_hash(
        revision, expected_hash=content_hash, label=f"reusable revision {revision.id}"
    )
    if existing.canonical_payload() != content.canonical_payload():
        raise GraphConfigurationIntegrityError(
            f"reusable revision {revision.id} does not match its hash"
        )
    return revision, False
```

Replace `bootstrap.py:84–93` with `return database_transaction_timestamp(session)` inside `_database_timestamp`, and the loop body `:218–240` with `revision, _created = materialize_or_reuse_revision(session, definition, actor=actor, timestamp=timestamp)`. In `graph_configuration_draft.py` add:

```python
    @staticmethod
    def _advance_locked_draft(draft_row, *, actor: str, timestamp) -> None:
        """The one draft-parent audit write: every successful draft or publication write."""
        draft_row.lock_version += 1
        draft_row.updated_by = actor
        draft_row.updated_at = timestamp
```

and make `_write_locked_content` use `timestamp = database_transaction_timestamp(session)` and `_GraphConfigurationDraft._advance_locked_draft(locked.draft_row, actor=actor, timestamp=timestamp)` in place of `:767–776`. Keep the statement text `SELECT CURRENT_TIMESTAMP` (the workbench PG test at `test_agent_definition_workbench_postgres.py:132–138` captures it).

- [ ] **Step 4: Implement the core.** Create `src/services/graph_configuration_publication.py` with the dataclasses from "Stable interfaces" and:

```python
_EXPECTED_AGENT_KEYS = frozenset(GRAPH_V1_AGENT_KEYS)
_BLANK_NOTE = DraftValidationIssue("release_note", "blank", "Release note must not be blank.")


class PublicationRejected(ValueError):  # noqa: N818 - stable public domain name
    def __init__(self, *issues: DraftValidationIssue) -> None:
        if not issues:
            raise ValueError("PublicationRejected requires at least one issue")
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


class _GraphConfigurationPublication(_GraphConfigurationDraft):
    def publish_draft(self, session, *, expected_lock_version, release_note, actor, evidence_gate):
        self._validate_publication_request(actor, expected_lock_version, release_note)
        with session.begin():
            release_row, draft_row = self._lock_current_parents(session, exclusive=True)
            self._lock_all_draft_agents(session, draft_id=draft_row.id)
            snapshot = self._snapshot_locked_workbench(session, release=release_row, draft=draft_row)
            if expected_lock_version != draft_row.lock_version:
                return PublicationConflict(
                    expected_lock_version=expected_lock_version,
                    current_lock_version=draft_row.lock_version,
                    active_release_id=release_row.id,
                    active_version_number=release_row.version_number,
                    draft=snapshot.draft,
                )
            model_nodes = {n.agent_key: n for n in snapshot.nodes if n.execution_kind == "model"}
            changed = tuple(k for k in GRAPH_V1_AGENT_KEYS if model_nodes[k].changed)
            if not changed:
                return NothingToPublish(snapshot.draft, release_row.id, release_row.version_number)
            self._validate_changed_candidates(model_nodes, changed)
            gate_result = evidence_gate.lock_and_verify(
                session, snapshot=snapshot, changed_agent_keys=changed
            )
            if isinstance(gate_result, PublicationNotReady):
                return gate_result
            return self._commit_locked_publication(
                session, release_row=release_row, draft_row=draft_row, snapshot=snapshot,
                contents={k: model_nodes[k].draft.content for k in GRAPH_V1_AGENT_KEYS},
                evidence=tuple(gate_result), release_note=release_note, actor=actor,
                restored_from_release_id=None,
            )

    def _lock_all_draft_agents(self, session, *, draft_id):
        rows = list(session.scalars(
            select(GraphDraftAgent).where(GraphDraftAgent.graph_draft_id == draft_id)
            .order_by(GraphDraftAgent.agent_key).with_for_update()
        ))
        if {row.agent_key for row in rows} != _EXPECTED_AGENT_KEYS or len(rows) != 7:
            raise GraphConfigurationIntegrityError("shared draft does not have the exact role key set")
        return rows

    def _validate_changed_candidates(self, model_nodes, changed):
        issues: list[DraftValidationIssue] = []
        for key in changed:
            try:
                self._run_candidate_validators(self.local_candidate_validators, model_nodes[key].draft.content)
                self._run_candidate_validators(self.post_stale_validators, model_nodes[key].draft.content)
            except DraftContentRejected as rejection:
                issues.extend(
                    DraftValidationIssue(f"definitions.{key}.{i.field}", i.code, i.message)
                    for i in rejection.issues
                )
        if issues:
            raise PublicationRejected(*issues)

    def _commit_locked_publication(self, session, *, release_row, draft_row, snapshot, contents,
                                   evidence, release_note, actor, restored_from_release_id):
        if set(contents) != _EXPECTED_AGENT_KEYS:
            raise GraphConfigurationIntegrityError("publication requires exactly seven definitions")
        timestamp = database_transaction_timestamp(session)
        if timestamp <= release_row.effective_from:
            raise GraphConfigurationIntegrityError(
                "publication timestamp does not follow the active release interval")
        created: dict[str, tuple[AgentDefinitionRevision, bool]] = {
            key: materialize_or_reuse_revision(session, contents[key], actor=actor, timestamp=timestamp)
            for key in GRAPH_V1_AGENT_KEYS
        }
        session.flush()
        published = {n.agent_key: n.published for n in snapshot.nodes if n.execution_kind == "model"}
        for key, (revision, was_created) in created.items():
            if published[key].content_hash == revision.content_hash and revision.id != published[key].revision_id:
                raise GraphConfigurationIntegrityError(f"unchanged role {key!r} did not reuse its revision")
        latest = session.scalar(select(func.max(GraphRelease.version_number)))
        if latest != release_row.version_number:
            raise GraphConfigurationIntegrityError("active release is not the latest Graph Version")
        release_row.effective_to = timestamp
        session.flush()  # close before insert: uq_graph_release_one_active is not deferrable
        new_release = GraphRelease(
            version_number=latest + 1, previous_release_id=release_row.id,
            restored_from_release_id=restored_from_release_id, release_note=release_note,
            published_by=actor, published_at=timestamp, effective_from=timestamp,
        )
        session.add(new_release)
        session.flush()
        session.add_all(
            GraphReleaseAgent(graph_release_id=new_release.id, agent_key=key,
                              agent_definition_revision_id=created[key][0].id)
            for key in GRAPH_V1_AGENT_KEYS
        )
        session.flush()
        readback = dict(session.execute(
            select(GraphReleaseAgent.agent_key, GraphReleaseAgent.agent_definition_revision_id)
            .where(GraphReleaseAgent.graph_release_id == new_release.id)).all())
        if readback != {key: created[key][0].id for key in GRAPH_V1_AGENT_KEYS}:
            raise GraphConfigurationIntegrityError("published release mapping is incomplete")
        self._link_evidence(session, release_id=new_release.id, evidence=evidence)
        draft_row.base_release_id = new_release.id
        self._advance_locked_draft(draft_row, actor=actor, timestamp=timestamp)
        session.flush()
        return PublishedRelease(...)  # build from new_release, created, evidence, draft_row

    def _link_evidence(self, session, *, release_id, evidence):
        if evidence:  # Phase A: no evidence table exists yet; Task 4 replaces this body
            raise GraphConfigurationIntegrityError("release evidence linking is not available")
```

`_validate_publication_request(actor, lock_version, note)` reuses `_validate_common`'s actor/lock checks (without `agent_key`) and appends `_BLANK_NOTE` when `note` is not a `str` (`code "strict_type"`, message `"Release note must be a string."`) or `not note.strip()`, raising `PublicationRejected` with issues ordered `actor`, `lock_version`, `release_note`. Fill `PublishedRelease` with `ActiveReleaseSnapshot` of `new_release`, `previous_release_id=release_row.id`, `changed_agent_keys` recomputed as keys whose `published[key].content_hash != created[key][0].content_hash`, the seven `PublishedMapping(key, id, content_hash, reused=not was_created)` in a `MappingProxyType`, `evidence`, and a `DraftMetadataSnapshot` of the rebased draft (`base_version_number=new_release.version_number`). Add `_GraphConfigurationPublication` first in the `GraphConfiguration` bases and export the new public names in `__all__`.

- [ ] **Step 5: Write RED PostgreSQL atomicity tests** in `tests/integration/test_graph_release_publication_postgres.py` (`pytestmark = pytest.mark.postgres`; bootstrap with `GraphConfiguration().bootstrap_v1(factory)`; no backdating needed):
- `test_publication_is_exact_and_contiguous_on_postgresql`: same assertions as the SQLite happy path plus `v1.effective_to == v2.effective_from == v2.published_at == draft.updated_at` exactly, and `PersistedGraphReleaseLoader(session_factory=factory).resolve(v2.id, "architect").agent_definition_revision_id == mappings["architect"].agent_definition_revision_id`; `resolve(v1.id, "architect")` still returns v1's revision (historical release readable).
- `test_failure_after_mappings_rolls_back_every_row`: subclass overriding `_link_evidence` to raise `RuntimeError("injected")`; capture `_immutable_graph_artifacts`-style tuples (revisions, releases with intervals, mappings, draft parent, draft agents) before; assert `pytest.raises(RuntimeError)`; after == before exactly; a new `create_session`-style `lock_active_graph_release` in a fresh session returns v1.
- `test_reverted_content_reuses_the_older_revision`: publish v2 (architect prompt +A), save architect back to v1's exact prompt, publish v3 → architect mapping id == v1's architect revision id, `reused is True`, `changed_agent_keys == ("architect",)`, no new `agent_definition_revision` row for architect.
- `test_publication_lock_statement_sequence`: an `after_cursor_execute` recorder on the publisher thread proves, in order, the first `FOR UPDATE` statement names both `GRAPH_RELEASE` and `GRAPH_DRAFT`, the next locks `GRAPH_DRAFT_AGENT` with `ORDER BY` agent key, and no `FOR UPDATE` precedes the parent lock (SQLite cannot prove this; PostgreSQL renders the clauses).
- `test_deferred_guard_accepts_close_and_insert_only_via_core`: after publication, a direct `UPDATE graph_release SET effective_to = NULL WHERE id = v1` raises `IntegrityError` (first-close guard still active).

- [ ] **Step 6: Run GREEN.** `test ! -e .venv`; unit gate `tests/unit/test_graph_release_publication.py tests/unit/test_graph_configuration_bootstrap.py tests/unit/test_graph_configuration_draft.py tests/unit/test_graph_definition_content_mapping.py tests/unit/test_agent_definition_workbench_routes.py`; PostgreSQL gates, one command per file, zero skips: `test_graph_release_publication_postgres.py`, `test_graph_configuration_bootstrap_postgres.py`, `test_agent_definition_workbench_postgres.py`, `test_agent_schema_overlay_postgres.py`; `tests/unit/test_ci_collects_integration_tests.py` after the workflow edit; `test ! -e .venv`. Compare cause sets against Task 0.

- [ ] **Step 7: Sabotage.** Controller: delete `draft_row.base_release_id = new_release.id` in `_commit_locked_publication` → RED on rebase/boot-validation assertions; restore; GREEN. Reviewer (different seam): make `materialize_or_reuse_revision` skip the lookup and always insert → RED on unchanged-reuse and reverted-content tests (unique violation); restore; GREEN.

- [ ] **Step 8: Commit.**

```bash
git add src/services/graph_configuration_content.py src/services/graph_configuration_bootstrap.py \
  src/services/graph_configuration_draft.py src/services/graph_configuration_publication.py \
  src/services/graph_configuration.py tests/unit/test_graph_release_publication.py \
  tests/integration/test_graph_release_publication_postgres.py .github/workflows/test.yml
git commit -m "feat: atomic graph release publication core (#269)"
```

---

## Task 2: Publication handoff for the draft parent lock; writer, reader and publisher races

**Files:**
- Modify: `src/services/graph_configuration_workbench.py:188–238`
- Modify: `tests/integration/test_graph_release_publication_postgres.py`
- Modify: `tests/integration/postgres_concurrency_helpers.py` (append `_await_blocked_by`)

**Interfaces:**
- Consumes: Task 1 `publish_draft`, `_NoEvidenceGate` (copy the test class into this file; it is test-only).
- Produces: `_lock_current_parents` that retries exactly once when the first scan returns zero rows; `_await_blocked_by(engine, *, waiter_pid: int, blocker_pid: int) -> bool` test helper.

- [ ] **Step 1: Write the helper and RED ordering tests.** Append to `postgres_concurrency_helpers.py`:

```python
def _await_blocked_by(engine, *, waiter_pid: int, blocker_pid: int) -> bool:
    """True once ``waiter_pid`` waits on a lock held by exactly ``blocker_pid``."""
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            blocked = observer.scalar(
                text(
                    "SELECT :blocker = ANY(pg_blocking_pids(:waiter)) AND EXISTS ("
                    " SELECT 1 FROM pg_stat_activity WHERE pid = :waiter"
                    " AND datname = current_database() AND wait_event_type = 'Lock')"
                ),
                {"waiter": waiter_pid, "blocker": blocker_pid},
            )
        if blocked:
            return True
        time.sleep(0.02)
    return False
```

Pause mechanism for every test in this task: an `after_cursor_execute` listener that, for the thread named `publisher-winner`/`publisher`, pauses after the first statement whose normalized text contains `FOR UPDATE`, `GRAPH_RELEASE` and `GRAPH_DRAFT` (pattern: `test_agent_definition_workbench_postgres.py:176–190`), and records `conn.connection.driver_connection.get_backend_pid()` for each thread. Tests:
- `test_publication_first_then_draft_save_gets_stale_not_500`: publisher holds L0 (paused), a draft save (`save_editable_model_draft`, expected lock = pre-publication lock) starts; assert `_await_blocked_by(waiter=saver_pid, blocker=publisher_pid)`; release; publisher returns `PublishedRelease` v2; saver returns `DraftSaveConflict(expected=L, current=L+1)` whose `server.draft.base_release_id == v2.id`, `server.draft.base_version_number == 2`; draft content unchanged by the saver. **Against the Task 1 code this RED fails with `GraphConfigurationIntegrityError("graph configuration parent snapshot is inconsistent")`** — record that exact cause in the report; if it does not fail that way, stop and record the PostgreSQL behaviour in `PLAN-CORRECTIONS.md`.
- `test_draft_save_first_then_publication_is_stale`: saver paused after its parent lock (thread `draft-winner`), publisher (expected lock L) observed blocked by saver PID; release; saver `DraftSaveResult` lock L+1; publisher `PublicationConflict(expected=L, current=L+1, active_release_id=v1.id, active_version_number=1)`; exactly one release exists (`{(id, version, effective_to IS NULL)}` == `{(v1.id, 1, True)}`).
- `test_publication_first_then_workbench_read_sees_new_release`: reader (`read_workbench`, `FOR SHARE`) blocked by publisher PID; after release it returns `active_release.release_id == v2.id`, `draft.base_release_id == v2.id`, every node `changed is False`.
- `test_two_publishers_one_winner_one_exact_stale_conflict` (parametrize which thread wins): both use expected lock L; winner paused on L0; loser blocked by winner PID; outcome: winner `PublishedRelease(version 2, previous v1)`, loser `PublicationConflict(expected=L, current=L+1, active_release_id=<winner's v2 id>, active_version_number=2)`; exactly two releases; v2 has exactly seven mappings; loser wrote no revision (revision id set == winner's set).
- `test_sequential_retry_after_success_is_stale`: publish, then publish again with the same lock → `PublicationConflict` naming v2; still two releases.

- [ ] **Step 2: Run RED.** `test ! -e .venv`; `TELLR_TEST_POSTGRES_URL=… PYTHONPATH=… python -m pytest -q -rs tests/integration/test_graph_release_publication_postgres.py`; `test ! -e .venv`. Expected RED: the three waiter tests fail with `GraphConfigurationIntegrityError`.

- [ ] **Step 3: Implement the bounded handoff retry** in `_lock_current_parents`, keeping the statement and diagnosis unchanged:

```python
_MAX_PARENT_LOCK_SCANS = 2  # mirrors conversation_pins.MAX_ACTIVE_RELEASE_LOCK_SCANS

        for scan in range(_MAX_PARENT_LOCK_SCANS):
            parent_rows = session.execute(parent_statement).all()
            # A zero-row scan is the publication handoff: the locked release was closed
            # by a committed publication and READ COMMITTED re-checked it.  Rescan once
            # to lock the newly active release; never retry a multi-row result.
            if parent_rows or scan + 1 == _MAX_PARENT_LOCK_SCANS:
                break
        if len(parent_rows) != 1:
            ...  # existing diagnosis, unchanged (lines 211–227)
```

- [ ] **Step 4: GREEN** with the Task 1 PostgreSQL files plus `test_agent_definition_workbench_postgres.py` and `test_agent_schema_overlay_postgres.py` (writer races must be unchanged), each separately, zero skips; unit `tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_graph_configuration_draft.py`.

- [ ] **Step 5: Sabotage.** Controller: `_MAX_PARENT_LOCK_SCANS = 1` → RED on the three waiter tests; restore. Reviewer: delete the `expected_lock_version != draft_row.lock_version` branch in `publish_draft` → RED on two-publisher and retry tests (a v3 appears); restore.

- [ ] **Step 6: Commit** `git add src/services/graph_configuration_workbench.py tests/integration/test_graph_release_publication_postgres.py tests/integration/postgres_concurrency_helpers.py && git commit -m "fix: let draft locks follow a committed graph publication (#269)"`

---

## Task 3: Conversation creation versus real publication, both lock orders, every creator

**Files:**
- Create: `tests/integration/test_graph_release_session_ordering_postgres.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:**
- Consumes: `publish_draft` (Task 1), `CREATORS`, `_create`, `_creator_patches`, `_backend_pid` from `tests/integration/test_mixed_release_creation_postgres.py:26`, `:125`, `:129`, `:175` (import the underscore names only, so no test function is re-collected); `_await_blocked_by` (Task 2).
- Produces: proof that the real publisher linearizes with all four creation paths at the release row.

- [ ] **Step 1: Write RED tests.** Seed: `GraphConfiguration().bootstrap_v1(factory)`; save one role; create source sessions for `contributor`/`duplicate` pinned to v1 exactly as `_seed` does at `test_mixed_release_creation_postgres.py:71–105` but **without** inserting a release (bootstrap owns v1). Parametrize over `CREATORS`.
- `test_publication_first_each_creator_pins_exact_new_release`: publisher (thread `publisher`) paused after L0; creator started; `_await_blocked_by(waiter=creator_pid, blocker=publisher_pid)`; release; creator scans exactly `[1, 1]` (listener on `FROM graph_release … FOR UPDATE`, as `:241–249`); creator pin == `PublishedRelease.release.release_id`; `graph_version == 2`; source session (contributor/duplicate) still pins v1.
- `test_creation_first_publisher_waits_and_creator_keeps_v1`: creator paused after `INSERT INTO user_sessions` (`:299–310`), publisher blocked by creator PID; release creator then publisher; creator pin == v1.id; publisher returns v2 with `previous_release_id == v1.id`; v1 `effective_to == v2.effective_from`; `get_conversation_graph_version` for the creator reports `graph_version=1, active_graph_version=2, is_older_than_active=True`.
- `test_new_conversation_after_publication_pins_new_and_old_retains`: sequential: create root R-old (v1), publish, create root R-new → pins `(v1.id, v2.id)` exactly.

- [ ] **Step 2: RED** — confirm failures are missing file/imports only, not harness bugs (this task adds no production code unless a real ordering defect appears; if one does, stop and add a corrections row before fixing).
- [ ] **Step 3: GREEN** each file separately with zero skips: this file, `test_mixed_release_creation_postgres.py`, `test_conversation_pin_creation_postgres.py`, `test_conversation_pin_acceptance_postgres.py`; `tests/unit/test_ci_collects_integration_tests.py`.
- [ ] **Step 4: Sabotage.** Controller: in `publish_draft` replace `self._lock_current_parents(session, exclusive=True)` with a statement locking only `graph_draft` `FOR UPDATE` and reading the release unlocked → RED on creation-first (no waiter observed / creator commits a stale pin after publication). Reviewer: set `MAX_ACTIVE_RELEASE_LOCK_SCANS = 1` in `conversation_pins.py:55` → RED on publication-first for every creator; restore.
- [ ] **Step 5: Commit** `git add tests/integration/test_graph_release_session_ordering_postgres.py .github/workflows/test.yml && git commit -m "test: prove session creation linearizes with real publication (#269)"`

**Phase A ends here. Do not start Task 4 until Task 0 Step 4 passes.**

---

## Task 4: Approval evidence gate, evidence links, and cleanup/verdict races

**Files (Phase B; paths of #267/#268 files per Task 0-B):**
- Create: `src/services/graph_release_evidence.py`
- Modify: `src/services/graph_configuration_publication.py` (`_link_evidence` delegates to `link_release_evidence`)
- Conditional on Q3 ruling: modify `src/core/database.py` near `:1038–1081` to add trigger `trg_agent_test_run_linked_verdict_immutable`
- Create: `tests/unit/test_graph_release_evidence.py`
- Create: `tests/integration/test_graph_release_evidence_postgres.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:**
- Consumes (assumed from the draft plans, re-probe at Task 0 phase B): `AgentTestRun`, `GraphReleaseTestRun`, `AgentTestCase`; #268 readiness callable; #268 `cleanup_unpublished_test_runs`; #268 `record_verdict`.
- Produces: `ApprovalEvidenceGate(readiness: Callable[[Session], object])`; `link_release_evidence(session, *, release_id: int, evidence: tuple[EvidenceLink, ...]) -> None`.

- [ ] **Step 1: Write RED PostgreSQL tests** (evidence rows created through #267's real `execute_candidate_run` with its deterministic fake adapter where the Task 0-B probe confirms it can be driven from a test; otherwise insert `AgentTestRun` rows with the ORM, recording that choice in corrections):
- `test_publication_links_newest_eligible_approval_per_required_case`: architect changed; two approved eligible runs for its required case (ids a < b, `run_at` a < b) → `evidence == (EvidenceLink(b, "architect", case.id, "approval", None),)`; one `graph_release_test_run` row `(v2.id, b, 'approval', NULL)`; `DELETE FROM agent_test_run WHERE id = b` → `IntegrityError`; unchanged roles have no links.
- `test_stale_hash_approval_is_not_ready_and_writes_nothing`: approval for the pre-save hash only → `PublicationNotReady(locked_gaps=(("architect", case.id),), readiness=<#268 result with architect blocking>)`; zero rows written anywhere.
- `test_case_version_bump_after_approval_is_not_ready`: per #267's versioning semantics recorded at Task 0-B.
- `test_cleanup_first_then_publication`: 25 runs for the architect case where the eligible approval is the **oldest** (outside the latest 20) and 5 ineligible runs are older than position 20; cleanup (thread `cleanup`) paused after its `graph_draft FOR SHARE` statement; publisher observed blocked by cleanup PID (`_await_blocked_by`); release; cleanup deletes exactly the ineligible ids (assert the exact retained id set); publisher links exactly the approval id.
- `test_publication_first_then_cleanup`: publisher paused after L3 (listener on the `agent_test_run … FOR UPDATE` statement); cleanup observed blocked by publisher PID; release; publisher links the approval; cleanup's retained set includes the linked id; the release-link `NOT EXISTS` exclusion and the FK both hold.
- `test_verdict_rejection_first_then_publication`: `record_verdict(..., "rejected")` paused before commit holding the run lock; publisher observed blocked by verdict PID; release; publisher returns `PublicationNotReady` naming the case; nothing written.
- `test_publication_first_then_verdict_change`: publisher paused after L3; verdict writer observed blocked by publisher PID; release; the linked evidence row exists; the verdict writer's outcome is exactly what Q3's ruling mandates (default recommendation: it fails with the new trigger's `IntegrityError` and the run stays `approved`).

- [ ] **Step 2: Write RED unit tests** for the gate's predicate construction on SQLite: only `verdict == "approved"`, `execution_status == "completed"`, `deterministic_checks_passed is True`, matching `test_case_id`, `test_case_version`, `agent_key` and the role's **current** candidate hash are returned; optional (non-required) and inactive cases never block and are never linked.

- [ ] **Step 3: RED run** of both files (expected: missing module).

- [ ] **Step 4: Implement** `graph_release_evidence.py`:

```python
class ApprovalEvidenceGate:
    """Lock and re-verify the exact approvals that satisfy the changed roles' gate."""

    def __init__(self, *, readiness: Callable[[Session], object]) -> None:
        self._readiness = readiness

    def lock_and_verify(self, session, *, snapshot, changed_agent_keys):
        hashes = {n.agent_key: n.draft.candidate_hash for n in snapshot.nodes
                  if n.execution_kind == "model"}
        cases = list(session.scalars(
            select(AgentTestCase)
            .where(AgentTestCase.agent_key.in_(changed_agent_keys),
                   AgentTestCase.is_active.is_(True), AgentTestCase.is_required.is_(True))
            .order_by(AgentTestCase.id).with_for_update(read=True)))              # L2
        runs = list(session.scalars(
            select(AgentTestRun)
            .where(or_(*(and_(AgentTestRun.test_case_id == c.id,
                              AgentTestRun.test_case_version == c.version,
                              AgentTestRun.agent_key == c.agent_key,
                              AgentTestRun.candidate_hash == hashes[c.agent_key]) for c in cases)),
                   AgentTestRun.verdict == "approved",
                   AgentTestRun.execution_status == "completed",
                   AgentTestRun.deterministic_checks_passed.is_(True))
            .order_by(AgentTestRun.id).with_for_update())) if cases else []       # L3
        chosen: dict[int, AgentTestRun] = {}
        for run in runs:                      # re-verify the locked row, never trust the query alone
            case = next(c for c in cases if c.id == run.test_case_id)
            if (run.verdict, run.execution_status, run.deterministic_checks_passed,
                    run.candidate_hash, run.test_case_version) != (
                    "approved", "completed", True, hashes[case.agent_key], case.version):
                continue
            best = chosen.get(case.id)
            if best is None or (run.run_at, run.id) > (best.run_at, best.id):
                chosen[case.id] = run
        order = {k: i for i, k in enumerate(GRAPH_V1_AGENT_KEYS)}
        gaps = tuple(sorted(((c.agent_key, c.id) for c in cases if c.id not in chosen),
                            key=lambda g: (order[g[0]], g[1])))
        if gaps:
            return PublicationNotReady(locked_gaps=gaps, readiness=self._readiness(session))
        return tuple(EvidenceLink(chosen[c.id].id, c.agent_key, c.id, "approval", None)
                     for c in sorted(cases, key=lambda c: (order[c.agent_key], c.id)))
```

A changed role with **zero** active required cases is itself a gap (`(agent_key, 0)` is not acceptable — record the ruling from Q5 and implement it; default: bootstrap guarantees ≥1 so treat absence as `GraphConfigurationIntegrityError`). `link_release_evidence` inserts one `GraphReleaseTestRun` per link, flushes, and reads back `{(run_id, kind, source)}` for the release, raising `GraphConfigurationIntegrityError` on mismatch. Replace the Phase A `_link_evidence` body with a call to it. If Q3 is ruled "freeze", add the trigger inside `_install_graph_configuration_mutation_guards` (idempotent `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER … BEFORE UPDATE OF verdict, verdict_reviewer, verdict_at, verdict_notes ON agent_test_run FOR EACH ROW WHEN (EXISTS …)` via a plpgsql function) and extend `test_graph_configuration_constraints_postgres.py`'s idempotence test.

- [ ] **Step 5: GREEN**: unit files; PostgreSQL per file with zero skips: this file, Task 1–3 files, #267/#268's PostgreSQL files recorded at Task 0-B, `test_graph_configuration_constraints_postgres.py`; CI guard.
- [ ] **Step 6: Sabotage.** Controller: drop the `AgentTestRun.candidate_hash == hashes[...]` term → RED on stale-hash test. Reviewer: remove `.with_for_update()` from the run query → RED on verdict-first (publisher not observed waiting; links a run that commits as rejected). Restore each.
- [ ] **Step 7: Commit** `git commit -m "feat: lock and link approval evidence during publication (#269)"` with the exact files touched.

---

## Task 5: Preview service, field diffs, and admin HTTP routes

**Files:**
- Modify: `src/services/graph_configuration_publication.py` (add `ReleasePreview`, `ChangedDefinitionPreview`, `FieldDiff`, `definition_field_diffs`, `preview_release`)
- Create: `src/api/schemas/graph_releases.py`
- Create: `src/api/routes/graph_releases.py`
- Modify: `src/api/main.py:23`, `:484` (import and `include_router` after `agent_definitions.router`)
- Create: `tests/unit/test_graph_release_preview.py`
- Create: `tests/unit/test_graph_release_routes.py`

**Interfaces:**
- Consumes: Tasks 1/4; #268 readiness callable and `DraftReadinessResponse` (assumed); `require_draft_write_principal` (`agent_definitions.py:58`); `ActiveReleaseResponse`, `DraftMetadataResponse`, `DraftFieldErrorResponse` (`schemas/agent_definitions.py:301–319`).
- Produces: routes and bodies in "Stable interfaces"; `definition_field_diffs(published: DefinitionContent, candidate: DefinitionContent) -> tuple[FieldDiff, ...]` where `FieldDiff(field: str, published: JsonValue, candidate: JsonValue)`; `ReleasePreview(draft, active_release, next_version_number, changed: tuple[ChangedDefinitionPreview, ...], readiness, validation_issues: tuple[DraftValidationIssue, ...], publishable: bool)`.

- [ ] **Step 1: RED unit tests for diffs.** Field vocabulary and order is fixed: `definition_version`, `prompt_text`, `model.endpoint_name`, `model.temperature`, `model.max_tokens`, `model.top_p`, `schema_overlay`, `assembly_rules`, `protected_assembly.version`, `protected_assembly.digest`, `schema_contract.version`, `schema_contract.digest`. Values come from `canonical_payload()` (so `0.7` vs `Decimal("0.700000")` yields **no** diff), `schema_overlay`/`assembly_rules` compare as whole JSON documents; only differing fields are returned; `json.dumps` of every value succeeds.

```python
_DIFF_FIELDS = (("definition_version",), ("prompt_text",), ("model", "endpoint_name"),
    ("model", "temperature"), ("model", "max_tokens"), ("model", "top_p"), ("schema_overlay",),
    ("assembly_rules",), ("protected_assembly", "version"), ("protected_assembly", "digest"),
    ("schema_contract", "version"), ("schema_contract", "digest"))

def definition_field_diffs(published, candidate):
    before, after = published.canonical_payload(), candidate.canonical_payload()
    diffs = []
    for path in _DIFF_FIELDS:
        old, new = before, after
        for segment in path:
            old, new = old[segment], new[segment]
        if old != new:
            diffs.append(FieldDiff(".".join(path), old, new))
    return tuple(diffs)
```

- [ ] **Step 2: RED route tests** (`tests/unit/test_graph_release_routes.py`, SQLite fixture copied from `test_agent_definition_workbench_routes.py:106–157` plus `_backdate_v1`; readiness and gate monkeypatched to deterministic fakes at the route module's factory function): non-admin GET/POST → 403 and neither the service nor `request.json` is called (pattern `:917–940`); blank-principal → 403; malformed JSON → exact 422; extra key / non-int lock / missing note → 422 `invalid_publication` ordered errors; blank note → exact 422; stale → exact 409 body; nothing to publish → exact 409; not ready → exact 409 embedding the fake readiness; success → exact 201 body with seven mappings; integrity error → 500 `{"detail":"Graph configuration is incomplete"}`; the route constructs `ApprovalEvidenceGate` (assert `type(captured_gate) is ApprovalEvidenceGate`); `test_main_app_registers_release_routes` asserts exactly `GET /api/admin/agent-definitions/release-preview` and `POST /api/admin/agent-definitions/releases` exist once. Preview: changed roles in `GRAPH_V1_AGENT_KEYS` order with exact `field_diffs`, `next_version_number == active + 1`, `publishable` true only when changed ≠ ∅, readiness all-ready, and no validation issues.

- [ ] **Step 3: RED run**, then **implement**. `preview_release` runs inside `with session.begin():` using `_lock_current_parents(exclusive=False)` + `_snapshot_locked_workbench` (the `read_workbench` pattern), collects validator issues without raising (same `definitions.<key>.` prefix), and calls `readiness(session)` in the same transaction. The router:

```python
router = APIRouter(prefix="/api/admin/agent-definitions", tags=["admin", "graph-releases"],
                   dependencies=[Depends(require_admin)])

def _readiness_callable() -> Callable[[Session], object]:
    """The one production binding to #268 readiness (shape recorded at Task 0-B)."""
    ...

@router.get("/release-preview", response_model=ReleasePreviewResponse)
def get_release_preview(db: Session = Depends(get_db)): ...

@router.post("/releases", status_code=201, response_model=PublishReleaseSuccessResponse)
async def publish_release(request: Request,
                          actor: Annotated[str, Depends(require_draft_write_principal)],
                          db: Session = Depends(get_db)): ...
```

`PublishReleaseRequest` is `ConfigDict(extra="forbid", strict=True)` with `lock_version: int` (`ge=0`) and `release_note: str`; parse only inside the handler after dependencies; map `PublicationRejected` → 422, `PublicationConflict` → `stale_publication`, `NothingToPublish` → `nothing_to_publish`, `PublicationNotReady` → `publication_not_ready` (`gaps` from `locked_gaps`, `readiness` via #268's response model), `GraphConfigurationIntegrityError` → 500 with `logger.exception`.

- [ ] **Step 4: GREEN**: `tests/unit/test_graph_release_preview.py tests/unit/test_graph_release_routes.py tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_graph_release_publication.py`.
- [ ] **Step 5: Sabotage.** Controller: remove the `not note.strip()` check in `_validate_publication_request` → RED (blank note reaches the DB check → 500). Reviewer: compute diffs from `model_dump(mode="python")` instead of `canonical_payload()` → RED on the Decimal no-false-diff test. Restore each.
- [ ] **Step 6: Commit** `git commit -m "feat: preview and publish graph releases over admin HTTP (#269)"`.

---

## Task 6: Typed client and the Review & Publish page

**Files:**
- Modify: `frontend/src/api/agentDefinitions.ts` (append release types, parsers and two functions)
- Create: `frontend/src/components/Admin/GraphRelease/ReviewAndPublishPage.tsx`
- Create: `frontend/src/components/Admin/GraphRelease/reviewAndPublishState.ts`
- Create: `frontend/src/components/Admin/GraphRelease/lineDiff.ts`
- Create: `frontend/src/components/Admin/GraphRelease/index.ts`
- Create: `frontend/src/components/Admin/GraphRelease/reviewAndPublishState.test.ts`
- Create: `frontend/src/components/Admin/GraphRelease/ReviewAndPublishPage.test.tsx`
- Create: `frontend/src/components/Admin/GraphRelease/lineDiff.test.ts`
- Modify: `frontend/src/App.tsx:53` (route `/admin/agent-definitions/review` inside `RequireAdmin`)
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx:31–48` (header: `Changed agents: N` and an `<a href="/admin/agent-definitions/review">Review & Publish</a>`; a plain anchor because the existing Vitest suites render the workbench without a Router)

**Interfaces:**
- Consumes: Task 5 wire; #268's readiness TypeScript type/parser (name recorded at Task 0-B — do not define a second readiness type).
- Produces: `getReleasePreview(): Promise<ReleasePreviewResponse>`, `publishRelease(request: PublishReleaseRequest): Promise<PublishReleaseSuccessResponse>` throwing `AgentDefinitionApiError` whose `payload` is the strictly parsed 409/422 body; `reviewAndPublishReducer`; page `data-testid`s `release-review-page`, `release-next-version`, `release-changes-tab`, `release-diff-tab`, `release-note-input`, `release-publish-button`, `release-stale-alert`, `release-not-ready-panel`, `release-success-panel`.

- [ ] **Step 1: RED Vitest.** Reducer states `loading | ready | publishing | stale | notReady | invalid | nothingToPublish | published | error`; transitions: `publish` allowed only from `ready` with `preview.publishable && note.trim() !== ''`; stale keeps the typed note and requires explicit `reloadPreview` (no automatic retry); `published` stores the new version and triggers exactly one preview refetch whose result shows `nothing_to_publish`-equivalent (no changed roles) and `Draft base: Graph Version N`. Parser tests reject any body with missing/extra keys, non-sha256 hashes, or fewer/more than seven mappings. `lineDiff` tests: LCS-based `[{kind: 'same'|'removed'|'added', text}]` for multi-line prompts, empty inputs, and identical inputs. Page tests (mocked fetch): renders all changed roles with each required case's readiness status text from #268 (`Needs test`, `Test failed`, `Awaiting review`, `Approved`), field diffs per role, next Graph Version, disabled Publish with a blank note or blocking readiness, 422 note error beside the textarea, 409 stale alert naming `current_lock_version` and active Graph Version with a `Reload preview` button, 409 not-ready gaps, success panel `Published Graph Version 2` and `The shared draft is now based on Graph Version 2`; exactly one POST per click; no `History` or `Rollback` control (they belong to #270).

- [ ] **Step 2: RED run**: `(cd frontend && npm run test:unit -- src/components/Admin/GraphRelease)`.

- [ ] **Step 3: Implement.** `lineDiff`:

```ts
export type DiffLine = { kind: 'same' | 'removed' | 'added'; text: string };

export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split('\n');
  const b = after.split('\n');
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0; let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { out.push({ kind: 'same', text: a[i] }); i += 1; j += 1; }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) { out.push({ kind: 'removed', text: a[i] }); i += 1; }
    else { out.push({ kind: 'added', text: b[j] }); j += 1; }
  }
  while (i < a.length) { out.push({ kind: 'removed', text: a[i] }); i += 1; }
  while (j < b.length) { out.push({ kind: 'added', text: b[j] }); j += 1; }
  return out;
}
```

The page has two tabs, `Changes & Approvals` and `Definition Diff` (spec §13.2; `Release History` is added by #270). `prompt_text` diffs render through `lineDiff`; other fields render `published → candidate` JSON. The page title is `Review & Publish`; the Publish button label is `Publish Graph Version {next}`.

- [ ] **Step 4: GREEN**: Vitest for `GraphRelease` and `AgentDefinitionWorkbench`; `(cd frontend && npm run typecheck)`; `(cd frontend && npx eslint src/api/agentDefinitions.ts src/components/Admin/GraphRelease src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx src/App.tsx)`.
- [ ] **Step 5: Sabotage.** Controller: drop `preview.publishable &&` from the publish guard → RED on disabled-button tests. Reviewer: make the stale handler call `publishRelease` again automatically → RED on the one-POST test. Restore each.
- [ ] **Step 6: Commit** `git commit -m "feat: review and publish graph releases in the admin UI (#269)"`.

---

## Task 7: Browser proof and forbidden-action rule update

**Files:**
- Create: `frontend/tests/e2e/graph-release-review.spec.ts`
- Modify: `frontend/tests/fixtures/forbiddenActionNames.ts` (append `'Review & Publish'` to `ALLOWED_ACTION_NAMES`)
- Modify: `frontend/tests/e2e/agent-definition-workbench.spec.ts:1462` (`toHaveLength` to the new exact count) and the Vitest twin in `AgentDefinitionWorkbench.test.tsx:242` if it asserts the length
- Modify: `frontend/tests/e2e/admin-route-gate.spec.ts` (non-admin visiting `/admin/agent-definitions/review` is redirected with no admin content flash)

**Interfaces:** Consumes Task 5 wire via `page.route` mocks and Task 6 `data-testid`s. Produces the browser seam #271 extends.

- [ ] **Step 1: RED Playwright tests**: (a) preview with two changed roles, readiness all approved, diff tab shows added/removed prompt lines; (b) readiness failure (`Awaiting review` case) disables publish and names the role/case; (c) stale 409 → alert, typed note retained, `Reload preview` issues exactly one GET and zero POSTs; (d) success 201 → success panel, refetched preview shows no changed roles and `Draft base: Graph Version 2`; the workbench link from `/admin` reaches the page; (e) 422 blank-note server response rendered beside the note; (f) the workbench forbidden sweep still passes with the new link and still flags `Publish draft`, `Release history`, `Rollback release`.
- [ ] **Step 2: RED** `(cd frontend && npx playwright test tests/e2e/graph-release-review.spec.ts --project=chromium --workers=1)`.
- [ ] **Step 3: Implement** fixture/spec edits only (no production change expected; any production fix needs a corrections row).
- [ ] **Step 4: GREEN**: the new spec, `agent-definition-workbench.spec.ts`, `admin-route-gate.spec.ts`, `admin-page.spec.ts`, each `--project=chromium --workers=1`.
- [ ] **Step 5: Sabotage.** Controller: change the workbench link label to `Publish draft` in `AgentDefinitionWorkbench.tsx` → RED on the forbidden sweep. Reviewer: remove the post-success preview refetch in `ReviewAndPublishPage.tsx` → RED on (d). Restore each.
- [ ] **Step 6: Commit** `git commit -m "test: browser proof for graph release review and publish (#269)"`.

---

## Task 8: Real-PostgreSQL HTTP acceptance flow (the #271 AC7 seam)

**Files:**
- Create: `tests/integration/test_graph_release_publication_acceptance_postgres.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:** Consumes the shipped routers (`agent_definitions.router`, #267/#268 routers, `graph_releases.router`) over real PostgreSQL with the `real_route_stack` recipe (`test_agent_definition_workbench_postgres.py:1280–1304`) and #267's deterministic fake adapter (location per Task 0-B).

- [ ] **Step 1: RED test** `test_edit_test_approve_preview_publish_pin_flow`: bootstrap; `SessionManager().create_session(session_id="old-root", created_by=…, graph_capable=True)` pins v1; PUT architect and builder drafts; run each role's required case through #267's route; approve each run through #268's verdict route; GET preview → exactly `["architect","builder"]` changed, exact `field_diffs[0] == {"field":"prompt_text",…}`, `next_version_number == 2`, `publishable is True`; POST with the previous lock → exact 409 `stale_publication`; POST with the current lock → exact 201 (seven mappings: five `reused: true` equal to v1 ids, two new; evidence ids equal the approved run ids); GET workbench → base v2, lock advanced by one, no changed nodes; `create_session("new-root")` pins v2 id; `old-root` still pins v1 and reports `is_older_than_active` true; `PersistedGraphReleaseLoader.resolve(v2_id, "builder")` returns the mapped revision; a second POST → `nothing_to_publish` or `stale_publication` exactly per its lock.
- [ ] **Step 2: RED → Step 3: GREEN** (no production change expected), zero skips, CI guard green.
- [ ] **Step 4: Sabotage.** Controller: make `get_conversation_graph_version` report the active version for pinned sessions (`conversation_pins.py:108`) → RED on the old-root assertion. Reviewer: make the gate choose the **oldest** eligible run → RED on exact evidence ids. Restore each.
- [ ] **Step 5: Commit** `git commit -m "test: end-to-end graph release publication acceptance (#269)"`.

---

## Task 9: Whole-slice verification, review, and local merge

- [ ] **Backend matrix** (each preceded/followed by `test ! -e .venv`, exact interpreter and `PYTHONPATH`):

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_graph_release_publication.py tests/unit/test_graph_release_evidence.py \
  tests/unit/test_graph_release_preview.py tests/unit/test_graph_release_routes.py \
  tests/unit/test_graph_configuration_bootstrap.py tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_configuration_models.py tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_conversation_pin_creation.py \
  tests/unit/test_persisted_graph_release.py tests/unit/test_ci_collects_integration_tests.py
# plus every #267/#268 unit file recorded at Task 0-B
```

- [ ] **PostgreSQL matrix**, one command per file, zero skips each: `test_graph_release_publication_postgres.py`, `test_graph_release_session_ordering_postgres.py`, `test_graph_release_evidence_postgres.py`, `test_graph_release_publication_acceptance_postgres.py`, `test_graph_configuration_bootstrap_postgres.py`, `test_graph_configuration_constraints_postgres.py`, `test_agent_definition_workbench_postgres.py`, `test_agent_schema_overlay_postgres.py`, `test_conversation_pin_creation_postgres.py`, `test_mixed_release_creation_postgres.py`, `test_conversation_pin_acceptance_postgres.py`, `test_persisted_graph_runtime_failures_postgres.py`, `test_mixed_release_collaboration_acceptance_postgres.py`, and every #267/#268 PostgreSQL file.
- [ ] **Frontend matrix**: Vitest `src/components/Admin/GraphRelease src/components/Admin/AgentDefinitionWorkbench`; `npm run typecheck`; ESLint on touched files; Playwright `graph-release-review.spec.ts`, `agent-definition-workbench.spec.ts`, `admin-route-gate.spec.ts`, `admin-page.spec.ts`. Compare causes, not counts.
- [ ] **Controller final sabotage** on a seam no task reviewer used: skip `_validate_changed_candidates` in `publish_draft` → RED on `test_invalid_changed_candidate_rejects_with_prefixed_issues`; restore.
- [ ] **Whole-branch review** from exactly `INTEGRATION_BASE..HEAD` (attach proof it is rebased Tasks 1–3 plus Tasks 4–8 only), on the most capable reviewer, with `PLAN-CORRECTIONS.md`, all reports, every ledger ruling/deferred item, and all sabotage evidence. Require: (1) a **writer-by-writer table** covering the draft writer (`_write_locked_content`), the parent-audit helper, bootstrap, publication core, evidence linker, #268 verdict writer and cleanup, and session creation — for each: locks taken in order, rows written, timestamp source, rollback behaviour; (2) the **lock-order table** re-derived from code, including implicit FK `KEY SHARE` locks, with the deadlock-freedom argument; (3) a **rollback/no-write ruling** for every non-success outcome (`PublicationRejected`, `PublicationConflict`, `NothingToPublish`, `PublicationNotReady`, integrity errors, injected mid-transaction failure); (4) confirmation that no route constructs a non-production gate and there is exactly one draft-content writer; (5) the #270 thin-caller seam review; (6) a **merge/no-merge verdict**. Allow one fix wave and one scoped re-review.
- [ ] **Pre-merge gate**: re-resolve the final reviewed #266/#267/#268 heads and the current local root; prove each and `INTEGRATION_BASE` are ancestors of both; recompute the reviewed diff as `INTEGRATION_BASE..HEAD`; refuse the merge if local-root reconciliation changes it; if any predecessor advanced, rebase, refresh corrections and baselines, rerun affected reviews.
- [ ] **Local merge only**: merge into `feat/langgraph-core` locally after #268, record the merge commit. No push, no PR. #270 starts from that commit.

## Open questions for controller ruling

- **Q1 (blocking Phase B).** #268's draft Task 5 extends a publication transaction and its Task 6 extends a Review & Publish page; neither exists before #269. Recommended ruling: #269 owns publication, evidence linking and the page; #268 ships readiness, verdicts, cleanup and (optionally) a readiness component #269 mounts.
- **Q2.** The cleanup lock boundary: this plan assumes #268's cleanup takes `graph_draft FOR SHARE` **before** any run row and never takes the release lock after run locks. Confirm or amend #268.
- **Q3.** May #268's verdict writer change the verdict of a run already linked through `graph_release_test_run`? "Evidence remains immutable" suggests no. Recommended: #269 adds a PostgreSQL trigger freezing verdict columns on linked runs (Task 4 conditional step).
- **Q4.** #268's `draft_readiness` must be callable inside the publication transaction without beginning/committing and without an `AgentRuntime` (the #267 draft makes `AgentTestWorkbench.__init__` require one). Which exact callable does the route bind?
- **Q5.** A changed role with no active required case: integrity error (bootstrap guarantees ≥1) or a readiness gap? When several eligible approvals exist for one case, this plan links the newest only — confirm, and confirm optional cases are never linked.
- **Q6.** Is "nothing to publish" `409 nothing_to_publish` (this plan) or a 422? Is `201` acceptable for publish success (existing admin writes use `200`)? Should release notes have a maximum length?
- **Q7 (for #270, recorded so the core stays thin).** On rollback, does the shared draft's content reset to the restored mapping or keep its candidates (rebasing only)?
- **Q8.** #267 test-case versioning: is a new version a new `agent_test_case` row with a new `id` (the unique `(agent_key, name, version)` suggests yes)? The gate keys on `(test_case_id, test_case_version)`; if versions share identity by `(agent_key, name)`, Task 4's predicate changes.
- **Q9.** Should #267's test-case writers and #268's verdict writer take the L0 draft lock (making the draft row the single evidence boundary), or is L2/L3 row locking sufficient?
