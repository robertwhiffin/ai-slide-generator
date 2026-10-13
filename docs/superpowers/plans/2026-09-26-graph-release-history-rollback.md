# Graph Release History and Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: use `executing-plans-tellr` and `superpowers:subagent-driven-development` together. The issues and the design are binding. This plan is a hypothesis until Task 0 records code-verified corrections, and every #268/#269 shape in it is a hypothesis until Task 0 phase B re-probes it. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give administrators an immutable Graph Release history (author, note, timestamps, changed roles, predecessor, exact definitions, evidence, rollback lineage), field-level comparison between the active release and any historical release, and an emergency rollback that republishes a selected historical seven-definition mapping as the **next** Graph Version, links that release's evidence as `historical_restore`, calls no model, and serializes with publication, draft saves, evidence cleanup and all four conversation-creation paths.

**Architecture:** Task 1 (Phase A, implementable on `a08389ec3`) adds a lock-free, statement-coherent history read model in a new module that touches no #268/#269 file. Everything else is Phase B, after reviewed #268 and #269 are integrated locally. Rollback is a **thin caller of #269's publication core**: a new `_GraphConfigurationRollback` mixin takes #269's L0 parent lock and L1 draft-agent lock, loads and structurally validates the historical mapping, locks the source release's linked evidence, and calls `_commit_locked_publication(..., contents=<historical>, evidence=<historical_restore links>, restored_from_release_id=<source>)`. Because the core reuses revisions by `(agent_key, content_hash)`, every historical revision is reused, the next version is `max + 1`, and no interval is reopened. The only addition beyond "publish-with-old-content" is the Q7 three-way draft rebase (below). HTTP handlers join #269's release handlers on the one admin router; the React Release History tab is added to #269's Review & Publish page and uses that page's one reducer, one request counter and one in-flight gate.

**Tech Stack:** Python 3.11, SQLAlchemy 2, PostgreSQL 15/Lakebase (SQLite only for unit and route tests), FastAPI, Pydantic v2, React 19, TypeScript 5.9, react-router-dom, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` §§5.2–5.6 (release, mapping, draft, evidence, pins), §11.4 (the publication transaction rollback reuses), §12 (Rollback), §13.2 (the Release History tab), §§14–17. **Binding issues:** #270 (all ten acceptance criteria), #258 (user stories 38–41, 54). **Consumes:** #269 (the publication core and page; not implemented when this plan was written), #268 (readiness, verdicts, cleanup; in progress), #267 (evidence tables, merged at `a08389ec3`). **Exposes to:** #271 (AC7 "rolls back, and observes a new Graph Version").

## Global constraints and execution protocol

- Task 0 runs before any implementation dispatch. It creates `.superpowers/sdd/2026-09-26-graph-release-history-rollback/PLAN-CORRECTIONS.md`, whose **first line says it overrides this plan**, and records a cause-based baseline. Attach that exact file to **every** implementer and reviewer brief, including Task 1. `.superpowers/` is gitignored (`.gitignore:101`); never commit SDD evidence except the ledger `progress.md`, which is force-added.
- **Phase A** is Task 1 only. It is implementable on the current integration head (`feat/langgraph-core` containing #259–#267; this plan was written at `a08389ec3`). It creates only `src/services/graph_release_history.py`, `tests/unit/test_graph_release_history.py`, `tests/integration/test_graph_release_history_postgres.py`, and one line in `.github/workflows/test.yml`. It touches no #268/#269-owned file and does not modify the `GraphConfiguration` facade (which #269 modifies).
- **Phase B** (Tasks 2–9) starts only after the Task 0 phase-B re-probe passes against one concrete **local** integration commit containing reviewed #268 and reviewed #269 (merged in that order, per #269's plan Task 9). Record immutable `TASK1_BASE` (before Task 1) and `INTEGRATION_BASE` (before Task 2) as distinct files; never overwrite either; rebase the Task 1 commit above `INTEGRATION_BASE` and prove `INTEGRATION_BASE..HEAD` is exactly the rebased Task 1 plus Tasks 2–9.
- Every #269 fact below is labelled **"assumed from #269's plan, re-probe at Task 0 phase B"**. Its sources are read-only: `.worktrees/issue-269-plan/docs/superpowers/plans/2026-09-25-graph-release-publication.md` and `.worktrees/issue-269-plan/.superpowers/sdd/2026-09-25-graph-release-publication/{PLAN-CORRECTIONS.md,progress.md}` (30 corrections; where they differ from the plan, the corrections win). Every #268 fact is assumed from #269's plan's "Consumed #267/#268 outputs" table as corrected. Never modify, move, or copy any other worktree's files, and never read or edit the user's untracked draft plans in the main worktree. Where #269's plan is silent, this plan does not invent the shape; it names the gap in "Open questions".
- Invoke `/Users/robert.whiffin/.pyenv/shims/python -m pytest` exactly, with `PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr` where `<worktree>` is the absolute implementation-worktree path. Unit and route runs use `DATABASE_URL=sqlite:///<worktree>/.superpowers/sdd/2026-09-26-graph-release-history-rollback/unit.sqlite` (the file is disposable; tests build their own in-memory engines). Run `test ! -e .venv` before and after every backend gate. Never run `pip`, `uv`, `npm install`, or create an environment: the pyenv site-packages is shared with parallel agents.
- PostgreSQL gates use `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`; the `postgres_engine` fixture (`tests/integration/conftest.py:235`) creates and drops a throwaway `tellr_int_*` database. Any ad-hoc probe script creates and drops its own throwaway database in `finally` and proves the drop. Never connect to or modify `ai_slide_generator`.
- Every new PostgreSQL file starts `pytestmark = pytest.mark.postgres`, is named in the `integration-graph` job's `run:` block in `.github/workflows/test.yml` (at `a08389ec3`: lines 447–473), is accepted by `tests/unit/test_ci_collects_integration_tests.py`, and executes with **zero skips**, recorded per file. Concurrency assertions prove backend PIDs, observed waiting (`pg_stat_activity.wait_event_type = 'Lock'` **and** `pg_blocking_pids(waiter)` containing the blocker's PID, via #269's `_await_blocked_by`), and exact identities, versions, mappings, intervals, pins, draft hashes and evidence rows — never counts alone.
- Waiter PIDs are captured **before** the blocking statement (#269 Correction 5): a test subclass overrides `_lock_current_parents` to run `SELECT pg_backend_pid()` and set a "PID recorded" event before `super()`; creators use the `before_cursor_execute` recipe at `tests/integration/test_mixed_release_creation_postgres.py:245–253`. `after_cursor_execute` is used only to pause a blocker after its lock statement.
- Run Playwright only from `frontend` with checked-in dependencies: `(cd frontend && npx playwright test <spec> --project=chromium --workers=1)`. Never run `npx` at the repository root.
- **Admin routes** live on the one existing admin router, prefix `/api/admin/agent-definitions` (`src/api/routes/agent_definitions.py:97–101`, `dependencies=[Depends(require_admin)]`). #270 adds no router and does not touch `src/api/main.py`. If Task 0-B finds #269 registered a second router, #270 adds its handlers beside #269's release handlers and still does not touch `main.py`; record which in corrections.
- **Evidence rows** are immutable except their four verdict columns (`trg_agent_test_run_evidence_immutable`, `src/core/database.py:1098`). Rollback never inserts, updates or deletes an `agent_test_run` row; it only inserts `graph_release_test_run` link rows. Every `agent_test_run` query filters `run_kind = 'candidate'` (the column is closed to `candidate`/`published_baseline`, `graph_configuration.py:452–455`).
- **No model call, no remote call.** Rollback performs no model invocation, no endpoint-catalog or remote endpoint validation, and no structured-output probe; it never constructs `AgentRuntime`, `AgentTestWorkbench`, or a model adapter. Therefore no transaction is ever held across a model call on this path (Task 3 and Task 6 prove it with must-not-run fakes). No session, user, turn or release identifier reaches any model, and log records carry key names only (see "Log contract").
- **Frontend:** the Release History tab lives on #269's Review & Publish page, not in the workbench panel. It extends that page's **one** reducer, uses its **one** request counter, and joins its **one** in-flight gate (publish and rollback can never be in flight together). The workbench panel gains no control, so `ALLOWED_ACTION_NAMES` in `frontend/tests/fixtures/forbiddenActionNames.ts` is **unchanged** by #270 and the two tests pinning its length (at `a08389ec3`: `AgentDefinitionWorkbench.test.tsx:351` and `tests/e2e/agent-definition-workbench.spec.ts:1505`, both `toHaveLength(5)`; #268 and #269 will raise the number — record it at Task 0-B) are not edited. Every accessible name #270 adds is distinct from, and neither a substring nor a superstring of, any existing accessible name on the page (Task 8 proves it). Tests query #270 names with `exact: true`.
- Before each task record `TASK_BASE=$(git rev-parse HEAD)`; after implementation, fixes and restored controller sabotage record `TASK_HEAD`; generate the review package from exactly `TASK_BASE..TASK_HEAD` (never `HEAD~1`). The controller and the reviewer each sabotage the **different** production seam assigned in the task, verify the marker with `rg` on the executed path, capture a real RED on the predicted test, restore exactly, prove marker removal and `git diff --exit-code` on the touched file, and capture GREEN. Tell the reviewer which sabotage the controller already ran. A sabotage that does not RED is a plan defect: stop and record it in corrections.
- All SDD artifacts (corrections, bases, briefs, reports, packages) live under `.superpowers/sdd/2026-09-26-graph-release-history-rollback/`.
- Local merge only. No push, PR, remote merge, publish, or GitHub write is part of this plan.

## Verified code facts this plan relies on (file:line at `a08389ec3`)

| Symbol | Location | Fact |
|---|---|---|
| `AgentDefinitionRevision` | `src/database/models/graph_configuration.py:159–190` | unique `(agent_key, content_hash)` `:180–184` and `(id, agent_key)` `:185–189` |
| `GraphRelease` | same file `:193–245` | `previous_release_id`, `restored_from_release_id` both self-FKs `ON DELETE RESTRICT` (`:209–220`); strict `ck_graph_release_interval` `:233–236`; unique `version_number`; partial unique `uq_graph_release_one_active` `:238–244` |
| `GraphReleaseAgent` | same file `:248–274` | PK `(graph_release_id, agent_key)`; composite FK to `(revision.id, revision.agent_key)` |
| `GraphDraft` / `GraphDraftAgent` | same file `:277–304` / `:307–325` | singleton `id = 1`; `lock_version`; agent rows carry content columns + `candidate_hash`, no audit columns |
| `AgentTestCase` | same file `:328–370` | versioned rows; unique `(agent_key, name, version)` |
| `AgentTestRun` | same file `:373–490` | `run_kind IN ('candidate','published_baseline')` `:452–455`; verdict columns `verdict`, `verdict_reviewer`, `verdict_at`, `verdict_notes` `:421–425`; approved ⇒ completed and passing `:472–476` |
| `GraphReleaseTestRun` | same file `:493–537` | PK `(graph_release_id, agent_test_run_id)`; `evidence_kind IN ('approval','historical_restore')` `:526–529`; `source_release_id` non-null iff `historical_restore` `:530–533`; all FKs RESTRICT; index on `agent_test_run_id` `:536` |
| mutation guards | `src/core/database.py:935–1121` | revision/mapping rows immutable; a release allows only its first `effective_to` NULL→non-NULL; deferred `trg_graph_release_exactly_one_active` (`:1110–1120`); `trg_agent_test_run_evidence_immutable` (`:1098`) |
| `read_workbench` | `src/services/graph_configuration_workbench.py:179–186` | shared parent locks then snapshot |
| `_lock_current_parents` | same file `:188–238` | one statement `FOR UPDATE OF graph_release, graph_draft` (or `FOR SHARE`); row count ≠ 1 raises; no handoff retry at this commit (#269 Task 2 adds it) |
| `_snapshot_locked_workbench` | same file `:240–361` | `changed = draft_row.candidate_hash != revision.content_hash` |
| validator tuples | `src/services/graph_configuration_draft.py:346–352` | `local_candidate_validators = (_assembly_candidate_validator, _schema_overlay_candidate_validator)`; `post_stale_validators = ()` |
| `_run_candidate_validators` | same file `:368–378` | raises `DraftContentRejected(*issues)` |
| `_endpoint_name_policy_validator` | same file `:276–284` | local, no network; composed only by `_save_local_validators` `:380–387` |
| `_write_locked_content` | same file `:991–1029` | the one draft-content writer; content assignment `:999–1002`; parent audit `:1009–1011` (#269 extracts `_advance_locked_draft`) |
| `_assembly_candidate_validator` | same file `:226–234` | `PromptAssembler.validate` raises `ProtectedAssemblyBundleUnavailable` (a `PromptAssemblyRejected`) when a revision's protected bundle is not registered (`src/services/prompt_assembler.py:412–426`) |
| `_schema_overlay_candidate_validator` | same file `:250–268` | reports an unresolvable schema contract as `schema_contract` issue |
| `PersistedGraphReleaseLoader` | `src/services/persisted_graph_release.py:91–164` | resolves any release by exact **id**, active or closed; caches by id |
| `_validate_complete_snapshot` | same file `:167–204` | static; seven role-compatible, hash-valid mappings or `GraphReleaseIncompleteError` |
| `lock_active_graph_release` | `src/services/conversation_pins.py:66–74` | `FOR UPDATE` on the active row; `MAX_ACTIVE_RELEASE_LOCK_SCANS = 2` (`:55`) |
| `get_conversation_graph_version` | same file `:101–113` | `is_older_than_active` compares **version numbers** |
| admin router | `src/api/routes/agent_definitions.py:97–101` | prefix `/api/admin/agent-definitions`, `require_admin` |
| `require_draft_write_principal` | same file `:104–112` | 403 on blank principal |
| `_is_storable_row_id` / 404 idiom | same file `:1066–1067`, `:1178–1193` | out-of-range integer path ids → 404 `HTTPException` |
| `AgentRuntime` | `src/services/agent_runtime.py:796–807`, `run` `:829–835` | keyword ctor `(persisted_release_loader, model_adapter, identity_sink)`; four-argument `run` |
| `RecordingAgentInvocationIdentitySink` | `src/services/agent_runtime_identity.py:62` | records `calls`, `successes`, `error_classes` |
| `DeterministicFakeModelAdapter` | `tests/fixtures/deterministic_model_adapter.py:85` | #267's fake |
| forbidden-action rule | `frontend/tests/fixtures/forbiddenActionNames.ts:17–18`, `:31–37` | stems include `publish|history|rollback`; five exact exemptions |
| admin route gate | `frontend/src/App.tsx:27–33`, `:53` | `RequireAdmin`; only `/admin` exists at this commit |
| CI guard | `tests/unit/test_ci_collects_integration_tests.py` | every integration file named in a job or excluded with a reason |
| route test fixture | `tests/unit/test_agent_definition_workbench_routes.py:118–157`, `_force_admin` `:202` | SQLite `StaticPool` + bootstrap |
| PG route stack | `tests/integration/test_agent_definition_workbench_postgres.py:1284–1310` | `real_route_stack` fixture |
| ORM release builder | `tests/integration/test_conversation_pin_acceptance_postgres.py:125–182` | `_publish_v2` pattern: close, insert, map seven new revisions |

**Absent at `a08389ec3` (expected):** `graph_configuration_publication.py`, any readiness/verdict/cleanup service (#268), the Review & Publish page, any `/releases` route, and `_lock_current_parents`' handoff retry.

## Consumed #269 interfaces (every row: assumed from #269's plan, re-probe at Task 0 phase B)

| # | Interface (as #269's plan + corrections define it) | #270 use |
|---|---|---|
| I1 | `_GraphConfigurationPublication._commit_locked_publication(session, *, release_row, draft_row, snapshot, contents, evidence, release_note, actor, restored_from_release_id) -> PublishedRelease`; caller holds L0; `contents` has exactly the seven keys; compares `database_transaction_timestamp(session)` with `as_utc_aware(release_row.effective_from)` (C3/C4); allocates `max(version_number) + 1` and requires it equal `active + 1`; closes the old interval before inserting; writes seven mappings and reads them back; links `evidence` through `link_release_evidence`; rebases the draft parent via `_advance_locked_draft` | the whole rollback write |
| I2 | `PublishedRelease(release, previous_release_id, changed_agent_keys, mappings: Mapping[AgentKey, PublishedMapping(agent_key, agent_definition_revision_id, content_hash, reused)], evidence, draft)`; `PublicationConflict(expected_lock_version, current_lock_version, active_release_id, active_version_number, draft)`; `PublicationRejected(*issues)`; `PublicationNotReady(locked_gaps, readiness)` with `PublicationGap(agent_key, test_case_id, code)` (C1) | rollback result, stale result, 422 family; readiness negative proof |
| I3 | `EvidenceLink(agent_test_run_id, agent_key, test_case_id, evidence_kind, source_release_id)` and `EvidenceKind = Literal["approval","historical_restore"]`; `link_release_evidence(session, *, release_id, evidence)` inserts and reads back exactly | historical-restore links |
| I4 | the evidence gate: `PublicationEvidenceGate` Protocol and the production `ApprovalEvidenceGate` (L2 unfiltered case `FOR SHARE` then re-select, per C29; L3 run `FOR UPDATE`; filters `run_kind='candidate'`, C30) | rollback does **not** call a gate; Task 3 proves historical links never satisfy `ApprovalEvidenceGate` |
| I5 | the global lock order and `_lock_current_parents(exclusive=True)` with the bounded two-scan handoff retry (#269 Task 2); `_lock_all_draft_agents(session, *, draft_id)` (L1, `ORDER BY agent_key`, `FOR UPDATE`) | L0 and L1 |
| I6 | `_validate_publication_request` built on `_actor_and_lock_issues(actor, lock_version)` with the note rules `strict_type` → `blank` → `too_long` (2000 code points) (C10, C17) | rollback request validation |
| I7 | preview and field diffs: `definition_field_diffs(published: DefinitionContent, candidate: DefinitionContent) -> tuple[FieldDiff, ...]`, `FieldDiff(field, published, candidate)`, fixed field vocabulary over `canonical_payload()` (#269 Task 5) | comparison and rollback preview |
| I8 | the release page: `ReviewAndPublishPage` at `/admin/agent-definitions/review` inside `RequireAdmin`, tabs `Changes & Approvals` and `Definition Diff`, `reviewAndPublishReducer`, `lineDiff`, client `getReleasePreview`/`publishRelease` throwing `AgentDefinitionApiError`, `data-testid`s from #269 Task 6 | Release History tab and rollback flow |
| I9 | HTTP: `GET /release-preview`, `POST /releases` (success **200**, C10), `409 stale_publication`, `409 publication_not_ready`, the location of those handlers | #270 handlers sit beside them; acceptance publishes v2–v7 through them |
| I10 | C14 trigger `trg_agent_test_run_linked_verdict_immutable` (verdict columns frozen on any linked run) | protects source-linked evidence |
| I11 | C2: bootstrap `_validate_current_graph` takes `_lock_current_parents(exclusive=False)` first | boot during rollback is safe |
| I12 | test harness: `_NoEvidenceGate`, `_save_prompt`, `_await_blocked_by` (`tests/integration/postgres_concurrency_helpers.py`), the Task 3 creator-ordering file `test_graph_release_session_ordering_postgres.py`, and Task 8's `test_graph_release_publication_acceptance_postgres.py` | reused, extended, never copied |

#269's plan is **silent** on: whether `_commit_locked_publication` asserts anything about `restored_from_release_id` beyond writing it (only `test_core_writes_restored_from_verbatim`); whether its `_validate_changed_candidates` accepts a contents mapping (it takes snapshot nodes); the `FieldDiff` wire model name; whether its page has its own forbidden-name sweep; the page's in-flight gate implementation. #270 does not assume any of these; each is a Task 0-B probe row.

Consumed #268 facts (assumed, via #269's plan as corrected): `cleanup_unpublished_test_runs(session, *, per_case_limit=20)` taking `graph_draft FOR SHARE` before its `DELETE` and never deleting a linked run; `record_verdict(...)` locking the run `FOR UPDATE`; readiness keyed by candidate hash, case version, completed, checks passed, `run_kind='candidate'`, and never reading `graph_release_test_run`.

## Q7 ruling — the draft on rollback is **three-way rebased**, not reset and not merely re-parented

**Question (deferred from #269):** on rollback, does the shared draft's content reset to the restored mapping, or keep its candidates and only rebase?

**Ruling:** per role, compare the draft candidate with the **pre-rollback active** revision:

| Draft role before rollback | Effect | Code |
|---|---|---|
| clean (`candidate_hash == active hash`) and the restored hash differs | candidate content is set to the restored revision's content | `reset` |
| clean and the restored hash equals the active hash | nothing to do | `unchanged` |
| pending edit (`candidate_hash != active hash`) | candidate kept exactly | `kept` |

The parent is rebased once by the core (`base_release_id = new`, `lock_version + 1`).

**Why the text settles it:**
- §5.4 and §11.4 step 10 say the draft is **rebased** onto the new release. For a publication, parent-only and three-way coincide: every changed role was just published. For a rollback they diverge. Only three-way leaves each role in the same relation to its new base as it had to its old one.
- Parent-only would leave every clean role holding the rolled-back-from (v7) content, now shown as `changed` against v8. Its v7 approvals are still eligible, because they are keyed by hash. The next Review & Publish would then be ready to re-publish the content the emergency rollback removed. That defeats §12's purpose.
- Reset-all silently destroys saved, unpublished edits. User story 17 requires "concurrent editing cannot silently lose changes", and nothing in history records draft content.

**Cost if wrong:** the effect is confined to Task 3's draft step and Task 2's `draft_effect` preview field. Reset-all or parent-only is a one-function change plus its tests. This is listed under open questions for user confirmation because it is user-visible.

**Consequence for #269's "one draft writer" rule:** rollback must write `graph_draft_agent` rows for `reset` roles. It must not become a second content writer. Task 3 therefore extracts the column-and-hash assignment from `_write_locked_content` into `_assign_locked_candidate(row, content) -> None`. It is the only code that writes draft-agent content, and both callers use it. The parent audit stays with `_advance_locked_draft`, which the core calls exactly once.

## Stable interfaces (produced by this plan)

`src/services/graph_release_history.py` (Task 1; standalone functions over a `Session`, no mixin):

```python
@dataclass(frozen=True)
class ReleaseRef:
    release_id: int
    version_number: int

@dataclass(frozen=True)
class ReleaseHistoryEntry:
    release_id: int
    version_number: int
    is_active: bool
    release_note: str
    published_by: str
    published_at: datetime
    effective_from: datetime
    effective_to: datetime | None
    previous: ReleaseRef | None
    restored_from: ReleaseRef | None
    restored_by: tuple[ReleaseRef, ...]          # later releases whose restored_from is this one, ascending
    changed_agent_keys: tuple[AgentKey, ...]     # vs predecessor mapping, GRAPH_V1_AGENT_KEYS order; v1 lists all seven

@dataclass(frozen=True)
class ReleaseDefinition:
    agent_key: AgentKey
    agent_definition_revision_id: int
    content_hash: str
    content: DefinitionContent

@dataclass(frozen=True)
class ReleaseEvidence:
    agent_test_run_id: int
    agent_key: AgentKey
    test_case_id: int
    test_case_version: int
    evidence_kind: Literal["approval", "historical_restore"]
    source: ReleaseRef | None                    # non-None iff historical_restore
    verdict: str | None
    verdict_reviewer: str | None
    verdict_at: datetime | None
    execution_status: str
    deterministic_checks_passed: bool
    run_at: datetime

@dataclass(frozen=True)
class ReleaseDetail:
    entry: ReleaseHistoryEntry
    definitions: Mapping[AgentKey, ReleaseDefinition]   # exactly seven, MappingProxyType
    evidence: tuple[ReleaseEvidence, ...]               # ordered (GRAPH_V1_AGENT_KEYS index, test_case_id, run id)

class GraphVersionNotFound(LookupError):
    version_number: int

def list_release_history(session: Session) -> tuple[ReleaseHistoryEntry, ...]      # newest first
def read_release_detail(session: Session, *, version_number: int) -> ReleaseDetail
```

`src/services/graph_configuration_rollback.py` (Tasks 2–3):

```python
DraftEffect = Literal["reset", "kept", "unchanged"]

@dataclass(frozen=True)
class AgentComparison:
    agent_key: AgentKey
    active_revision_id: int
    historical_revision_id: int
    same_revision: bool
    field_diffs: tuple[FieldDiff, ...]           # #269 FieldDiff; published=active, candidate=historical

@dataclass(frozen=True)
class ReleaseComparison:
    active: ReleaseRef
    historical: ReleaseRef
    agents: tuple[AgentComparison, ...]          # exactly seven, GRAPH_V1_AGENT_KEYS order

RollbackBlock = Literal["source_is_active", "matches_active", "incompatible"]

@dataclass(frozen=True)
class RollbackPreview:
    source: ReleaseRef
    active: ReleaseRef
    next_version_number: int
    lock_version: int
    default_release_note: str                    # f"Roll back to Graph Version {source.version_number}."
    comparison: ReleaseComparison
    evidence: tuple[EvidenceLink, ...]           # the links a rollback would write
    draft_effect: Mapping[AgentKey, DraftEffect] # exactly seven
    issues: tuple[DraftValidationIssue, ...]     # structural, fields "definitions.<key>.<field>"
    blocked: RollbackBlock | None                # first applicable, in the order listed

@dataclass(frozen=True)
class RestoredRelease:
    published: PublishedRelease                  # #269 I2; published.release.restored_from_release_id == source.release_id
    source: ReleaseRef
    draft_effect: Mapping[AgentKey, DraftEffect]

@dataclass(frozen=True)
class RollbackSourceActive:
    active: ReleaseRef

@dataclass(frozen=True)
class RollbackMatchesActive:
    active: ReleaseRef
    source: ReleaseRef

class RollbackIncompatible(ValueError):
    source: ReleaseRef
    issues: tuple[DraftValidationIssue, ...]     # non-empty

RollbackOutcome = RestoredRelease | PublicationConflict | RollbackSourceActive | RollbackMatchesActive

class _GraphConfigurationRollback(_GraphConfigurationPublication):
    def compare_with_active(self, session, *, version_number: int) -> ReleaseComparison: ...
    def preview_rollback(self, session, *, version_number: int) -> RollbackPreview: ...
    def restore_release(self, session, *, version_number: int, expected_lock_version: int,
                        release_note: str, actor: str) -> RollbackOutcome: ...
```

`GraphVersionNotFound` (from Task 1) is raised by all three for an unknown version. `RollbackIncompatible` and `PublicationRejected` are raised; the rest are returned. `_GraphConfigurationDraft._assign_locked_candidate(row: GraphDraftAgent, content: DefinitionContent) -> None` (Task 3) is the one draft-agent content assignment.

**`restore_release` check order** (a failing check writes nothing):

1. Request shape: `version_number` int ≥ 1 (else `PublicationRejected` issue `version_number/strict_type`), then #269's actor/lock/note issues. All of this runs before any lock.
2. L0, then L1, then the snapshot.
3. The source exists (else `GraphVersionNotFound`).
4. The lock version is not stale (else `PublicationConflict`).
5. The source is not the active release (else `RollbackSourceActive`).
6. The source's seven revision ids are not identical to the active mapping (else `RollbackMatchesActive`).
7. Structural validation passes (else `RollbackIncompatible`).
8. L3 evidence lock.
9. The core writes.
10. The draft resets are applied.
11. The read-back verifies.

`preview_rollback` evaluates the same checks 3, 5, 6 and 7 without raising. It uses shared locks and returns `blocked` and `issues`.

## HTTP contract (Task 6; on the one admin router)

| Route | Success | Errors |
|---|---|---|
| `GET /api/admin/agent-definitions/releases` | `200 {"active_release": Ref, "releases": [Entry…]}` newest first | non-admin 403 |
| `GET …/releases/{version_number}` | `200 {"release": Entry, "definitions": {"<key>": {"agent_definition_revision_id", "content_hash", "content": <canonical_payload()>}×7}, "evidence": [Evidence…]}` | 404 `{"detail": "Graph Version not found"}` |
| `GET …/releases/{version_number}/comparison` | `200 {"active_release": Ref, "release": Ref, "agents": [{"agent_key", "active_revision_id", "historical_revision_id", "same_revision", "field_diffs": [{"field", "active", "historical"}]}×7]}` | 404 |
| `GET …/releases/{version_number}/rollback-preview` | `200 {"source": Ref, "active_release": Ref, "next_version_number", "lock_version", "default_release_note", "restorable": bool, "blocked": null\|"source_is_active"\|"matches_active"\|"incompatible", "issues": [{"field","code","message"}], "agents": <comparison agents>, "evidence": [{"agent_test_run_id","agent_key","test_case_id"}], "draft_effect": {"<key>": "reset"\|"kept"\|"unchanged"}×7}` | 404 |
| `POST …/releases/{version_number}/rollback` body `{"lock_version": int, "release_note": str}` (`extra="forbid"`, strict) | `200 {"release": ActiveReleaseResponse, "restored_from": Ref, "previous_release_id": int, "changed_agents": [AgentKey…], "mappings": {"<key>": {"agent_definition_revision_id", "content_hash", "reused": true}×7}, "evidence": [{"agent_test_run_id","agent_key","test_case_id","evidence_kind":"historical_restore","source_release_id"}], "draft": DraftMetadataResponse, "draft_effect": {…×7}}` | 403 blank principal; 404; `422 {"code":"invalid_rollback","errors":[…]}`; `422 {"code":"rollback_incompatible","source":Ref,"errors":[…]}`; `409 {"code":"stale_rollback","expected_lock_version","current_lock_version","active_release":Ref,"draft":DraftMetadataResponse}`; `409 {"code":"rollback_source_active","active_release":Ref}`; `409 {"code":"rollback_matches_active","active_release":Ref,"source":Ref}`; `500 {"detail":"Graph configuration is incomplete"}` |

- `Ref` is `{"release_id": int, "version_number": int}`.
- `Entry` is the snake_case projection of `ReleaseHistoryEntry`: `previous`, `restored_from` and `restored_by` are `Ref`s, and `changed_agents` is `changed_agent_keys`.
- A `version_number` outside `_is_storable_row_id` is a 404, following the existing idiom.
- Malformed JSON returns `422 invalid_rollback` with `{"field":"$","code":"invalid_json","message":"Request body must be valid JSON."}`, matching #269's publish route.

## Lock order

The global order (#269 plan line 200 as amended by C13 and C29) is:

**(L0) active `graph_release` → (L0) `graph_draft` → (L1) `graph_draft_agent` by `agent_key` → (L2) `agent_test_case` by `id`, unfiltered `FOR SHARE` then a re-select → (L3) `agent_test_run` by `id`.**

Every locker takes an ordered, prefix-respecting subsequence.

| # | Lock | Mode | Rollback takes it? | Why / conflict |
|---|---|---|---|---|
| L0 | active release + draft, one statement via `_lock_current_parents(exclusive=True)` with the handoff retry | `FOR UPDATE OF graph_release, graph_draft` | first statement | linearization point with session creation (release row) and with publication, draft saves, readiness, cleanup and bootstrap (draft row) |
| L1 | all seven `graph_draft_agent` rows, `ORDER BY agent_key`, via #269's `_lock_all_draft_agents` | `FOR UPDATE` | second | the `reset` writes; dominated by L0 |
| L2 | `agent_test_case` | — | **skipped** | rollback gates on no case; historical evidence is linked as-is, never re-verified against current cases (§12: bypasses model tests and approvals) |
| L3 | the source release's linked `agent_test_run` rows (`JOIN graph_release_test_run ON graph_release_id = source`), `run_kind='candidate'`, `ORDER BY agent_test_run.id` | `FOR SHARE OF agent_test_run` | third | #268 cleanup cannot delete them (FK RESTRICT) and I10 freezes their verdicts; the share lock makes a concurrent verdict writer's `FOR UPDATE` wait visibly rather than race the trigger, and matches #269's thin-caller description |
| implicit | FK `KEY SHARE` on the **closed** source `graph_release` row (from `restored_from_release_id` and `source_release_id`), on revision rows, and on linked run rows | automatic | during writes | nobody locks a closed release or a revision `FOR UPDATE`, so it cannot conflict. `KEY SHARE` on runs is compatible with L3 `FOR SHARE` |

**No lock in history reads.** `list_release_history` and `read_release_detail` take no row locks. One statement reads the release set, and every later statement is filtered to those ids. Releases, mappings, revisions and links are insert-only or immutable, so the result is a coherent snapshot as of that first statement. `compare_with_active` and `preview_rollback` take `_lock_current_parents(exclusive=False)` (`FOR SHARE`), exactly like `read_workbench`, because the draft effect must be coherent with the active release.

**Deadlock-freedom (the whole-branch reviewer must re-derive it):**
- Session creation holds only L0-release.
- The draft writer takes L0, then L1.
- Publication takes L0 → L1 → L2 → L3.
- Rollback takes L0 → L1 → L3.
- #268 cleanup takes L0-draft `FOR SHARE`, then L3 deletes.
- The #268 verdict writer takes only L3.
- #267's run transaction 2 re-locks L0 and then inserts. Its FK `KEY SHARE` on the active release comes after its own L0 (C13).
- Bootstrap validation takes L0 `FOR SHARE` (I11).

Every one of these follows the global order, so no cycle exists.

## Seam and producer/consumer table

| Seam | Producer | Consumer(s) | Contract |
|---|---|---|---|
| `list_release_history`, `read_release_detail`, `GraphVersionNotFound`, `ReleaseRef` | Task 1 | Tasks 2, 3, 6, 9; #271 | lock-free, first-statement coherent; exact projections above |
| `_commit_locked_publication` | #269 Task 1 (I1) | Task 3 `restore_release` | caller holds L0; seven contents; `restored_from_release_id` written verbatim |
| `_lock_current_parents` + handoff retry | #260 / #269 Task 2 (I5) | Tasks 2–3 | zero-row scan retried once |
| `_lock_all_draft_agents` | #269 Task 1 (I5) | Task 3 | L1 |
| `EvidenceLink`, `link_release_evidence` | #269 Tasks 1, 4 (I3) | Task 3 | `historical_restore` links with `source_release_id` |
| `ApprovalEvidenceGate` | #269 Task 4 (I4) | Task 3 negative proof; Task 9 | never counts `historical_restore` links |
| `_actor_and_lock_issues`, note rules, `PublicationRejected` | #269 Task 1 (I6) | Task 3 | identical triples; `version_number` issue prepended |
| `definition_field_diffs`, `FieldDiff` | #269 Task 5 (I7) | Task 2 | `published` = active, `candidate` = historical |
| `_assign_locked_candidate` | Task 3 (extracted from `_write_locked_content`) | `_write_locked_content`, `restore_release` | sets content columns and `candidate_hash`; never touches the parent |
| `compare_with_active`, `preview_rollback`, `restore_release` | Tasks 2–3 | Task 6 routes; Task 9; #271 AC7 | tables above |
| history/rollback HTTP | Task 6 | Tasks 7–9; #271 Playwright | HTTP contract above |
| Release History tab | Task 7 | Task 8 Playwright; #271 journey | `data-testid`s in Task 7 |
| `reviewAndPublishReducer`, page counter and gate | #269 Task 6 (I8) | Task 7 | extended, never duplicated |

Shared files and how #270 composes:

| File | Prior owners | #270 change | Rule |
|---|---|---|---|
| `src/services/graph_configuration_draft.py` | #263–#265, #269 | Task 3: extract `_assign_locked_candidate` | `_write_locked_content` behaviour byte-identical; all draft suites green |
| `src/services/graph_configuration.py` | #260, #263, #269 | Task 2: prepend `_GraphConfigurationRollback` to the bases; export names | MRO `(_GraphConfigurationRollback, _GraphConfigurationPublication, _GraphConfigurationDraft, _GraphConfigurationWorkbench, _GraphConfigurationBootstrap)` per Task 0-B |
| `src/services/graph_configuration_publication.py`, `graph_release_evidence.py` | #269 | **no change** | consumed only |
| `src/api/routes/agent_definitions.py` (or #269's release-route module per Task 0-B) | #263–#269 | Task 6: five handlers | no existing handler edited |
| `src/api/schemas/` | #263–#269 | Task 6: new `src/api/schemas/graph_release_history.py` | imports `ActiveReleaseResponse`, `DraftMetadataResponse`, `DraftFieldErrorResponse` |
| `frontend/src/api/agentDefinitions.ts` | #263–#269 | Task 7: append types, parsers, five functions | no existing parser changed |
| `frontend/src/components/Admin/GraphRelease/*` | #269 | Task 7: third tab, reducer slice | #269 tests stay green |
| `.github/workflows/test.yml` | many | Tasks 1, 3, 4, 5, 9: append files | CI guard green |

## Log contract

Rollback emits exactly one record per outcome, at INFO, with message `graph_release_rollback`. Its `extra` is:
- `outcome`: one of `restored`, `stale`, `not_found`, `source_active`, `matches_active`, `incompatible`, `rejected`, `integrity_error`;
- `agent_keys`: the sorted role key names changed (restored) or the offending role key names (incompatible), otherwise `[]`.

On `integrity_error` it adds `error_class` (the class name only) and logs at ERROR through `logger.exception`, the existing idiom. No record carries a release note, an actor, prompt text, a content hash, a release id or a version number. Task 6 pins this with `caplog`.

## Review Focus

1. **Restoring a release that was itself a rollback.** Restoring v8 (which restores v3) while v9 is active must produce v10 with `restored_from == v8`. It links every run linked to v8, whether an `approval` or a `historical_restore` link, as `historical_restore` with `source_release_id == v8.id`. There must be no duplicate-PK 500 and no transitive guess about v3. Test: Task 3 `test_restore_a_restoration_links_its_links_with_the_selected_source`.
2. **Restoring v1 (bootstrap, no evidence).** The rollback succeeds with `evidence == ()`, exactly zero link rows, and every revision reused. Test: Task 3 `test_restore_v1_links_no_evidence`.
3. **Double-submit after success.** A second POST with the same `lock_version` returns exactly `409 stale_rollback` naming the new release. It never creates a second new version. Test: Task 4 `test_sequential_rollback_retry_is_stale` and Task 6 route test.
4. **An admin's unpublished edit survives rollback and is still not ready.** A pending edit is `kept`. Afterwards readiness blocks it, and `ApprovalEvidenceGate` refuses it, even though the new release links approved runs for the same case. Test: Task 3 `test_historical_restore_evidence_never_satisfies_readiness`.
5. **Two-digit Graph Versions in the UI.** With versions 1–12, `Roll back to Graph Version 1` and `Roll back to Graph Version 12` each resolve to exactly one control when queried with `exact: true`. Test: Task 8 scenario (g).

---

## Task 0: Correct the plan against code and record cause baselines

**Files (ignored execution evidence only, except the ledger):**
- `.superpowers/sdd/2026-09-26-graph-release-history-rollback/PLAN-CORRECTIONS.md`
- `.superpowers/sdd/2026-09-26-graph-release-history-rollback/TASK1_BASE`
- `.superpowers/sdd/2026-09-26-graph-release-history-rollback/INTEGRATION_BASE`
- `.superpowers/sdd/2026-09-26-graph-release-history-rollback/predecessor-heads.md`
- `.superpowers/sdd/2026-09-26-graph-release-history-rollback/reports/`
- `.superpowers/sdd/2026-09-26-graph-release-history-rollback/packages/`
- `.superpowers/sdd/2026-09-26-graph-release-history-rollback/progress.md` (ledger; force-added)

- [ ] **Step 1: Resolve the workspace and base.** Record `git rev-parse HEAD` in immutable `TASK1_BASE`; prove `a08389ec3` (Merge #267) is its ancestor; run `test ! -e .venv`; confirm `/Users/robert.whiffin/.pyenv/shims/python --version` is 3.11.

- [ ] **Step 2: Write the Phase A corrections table.** First line: `This file overrides docs/superpowers/plans/2026-09-26-graph-release-history-rollback.md wherever they disagree.` Re-verify every row of "Verified code facts" with `sed -n`/`rg` and record actual lines. Add one row per task for internal consistency and one per shared file/seam. Rule on every mismatch before Task 1. Minimum probes:

```bash
W=<implementation worktree>
rg -n "class GraphRelease\b|class GraphReleaseAgent|class GraphReleaseTestRun|class AgentTestRun|run_kind|ck_graph_release_test_run" $W/src/database/models/graph_configuration.py
rg -n "trg_agent_test_run_evidence_immutable|trg_graph_release_exactly_one_active|def _install_graph_configuration_mutation_guards" $W/src/core/database.py
rg -n "def _lock_current_parents|def read_workbench|def _snapshot_locked_workbench" $W/src/services/graph_configuration_workbench.py
rg -n "local_candidate_validators|post_stale_validators|def _write_locked_content|def _run_candidate_validators" $W/src/services/graph_configuration_draft.py
rg -n "def _validate_complete_snapshot|class PersistedGraphReleaseLoader" $W/src/services/persisted_graph_release.py
rg -n "graph_release_history|restore_release|rollback" $W/src $W/frontend/src || echo "absent: expected"
rg -n "ALLOWED_ACTION_NAMES|toHaveLength\(" $W/frontend/tests/fixtures/forbiddenActionNames.ts $W/frontend/tests/e2e/agent-definition-workbench.spec.ts $W/frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx
```

- [ ] **Step 3: Record baseline causes, not counts.** Each command preceded and followed by `test ! -e .venv`:

```bash
cd $W && DATABASE_URL=sqlite:///$W/.superpowers/sdd/2026-09-26-graph-release-history-rollback/unit.sqlite \
  PYTHONPATH=$W:$W/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_graph_configuration_models.py tests/unit/test_graph_configuration_bootstrap.py \
  tests/unit/test_graph_configuration_workbench.py tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_persisted_graph_release.py tests/unit/test_agent_definition_workbench_routes.py \
  tests/unit/test_agent_test_workbench.py tests/unit/test_conversation_pin_creation.py \
  tests/unit/test_ci_collects_integration_tests.py
for f in test_graph_configuration_bootstrap_postgres test_graph_configuration_constraints_postgres \
         test_agent_definition_workbench_postgres test_conversation_pin_creation_postgres \
         test_mixed_release_creation_postgres test_conversation_creator_exclusions_postgres \
         test_conversation_pin_acceptance_postgres test_persisted_graph_runtime_failures_postgres; do
  TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  PYTHONPATH=$W:$W/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -rs tests/integration/$f.py
done
```

Record every failing node id with its first causal assertion or traceback, and every skip with its reason, in `reports/preflight-phase-a.md`. A skip in any PostgreSQL file is a blocker, not a baseline.

- [ ] **Step 4 (phase B re-probe, before Task 2).** After reviewed #268 and #269 are integrated **locally**, record `INTEGRATION_BASE` and each predecessor's final reviewed head in `predecessor-heads.md`. Prove each head is an ancestor (never use mid-PR SHAs). Rebase Task 1 above `INTEGRATION_BASE`, and prove `INTEGRATION_BASE..HEAD` is exactly the rebased Task 1.

Then re-probe and record, for each of I1–I12 and each #268 fact:
- the exact symbol, module, signature, field names and wire names;
- whether `_commit_locked_publication` accepts `restored_from_release_id` and `historical_restore` links end-to-end (run #269's `test_core_writes_restored_from_verbatim`);
- the exact module holding #269's release handlers, and whether a second router exists;
- the `FieldDiff` wire model name;
- the page's reducer, action names, counter and gate implementation;
- whether #269's page carries a forbidden-name sweep (if it does, stop and see Open question 5);
- the new `ALLOWED_ACTION_NAMES` length;
- the #268 readiness callable, cleanup and verdict entry points and their lock statements;
- whether the handoff retry landed in `_lock_current_parents`.

Minimum probes:

```bash
rg -n "def _commit_locked_publication|def _lock_all_draft_agents|def _validate_publication_request|def _actor_and_lock_issues|class PublishedRelease|class PublicationConflict|class EvidenceLink|def link_release_evidence|class ApprovalEvidenceGate|def definition_field_diffs|class FieldDiff|_MAX_PARENT_LOCK_SCANS" $W/src/services
rg -n "release-preview|\"/releases\"|APIRouter\(" $W/src/api/routes
rg -n "trg_agent_test_run_linked_verdict_immutable" $W/src/core/database.py
rg -n "reviewAndPublishReducer|Release History|forbidsActionName|data-testid=\"release-" $W/frontend/src $W/frontend/tests
rg -n "def cleanup_unpublished_test_runs|def record_verdict|def draft_readiness|with_for_update" $W/src/services/agent_test_workbench.py $W/src/services
PYTHONPATH=$W:$W/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -c "
from src.services.graph_configuration import GraphConfiguration
print([c.__name__ for c in GraphConfiguration.__mro__])"
```

Re-derive every baseline cause after integration, and add #268's and #269's unit, PostgreSQL and frontend files to the baseline loop. Do not dispatch Task 2 until every consumed row is ruled on.

---

## Task 1 (Phase A): Immutable release history read model

**Files:**
- Create: `src/services/graph_release_history.py`
- Create: `tests/unit/test_graph_release_history.py`
- Create: `tests/integration/test_graph_release_history_postgres.py`
- Modify: `.github/workflows/test.yml` (append the new PostgreSQL file to `integration-graph`)

**Interfaces:**
- Consumes: ORM models (`graph_configuration.py:159–537`); `validate_definition_hash` (`src/services/graph_configuration_content.py`); `PersistedGraphReleaseLoader._validate_complete_snapshot` semantics (`persisted_graph_release.py:167–204`, reimplemented through the same `validate_definition_hash`, not imported privately); `GRAPH_V1_AGENT_KEYS`.
- Produces: everything under `graph_release_history.py` in "Stable interfaces".

- [ ] **Step 1: Write RED unit tests (SQLite).** Build releases with a test helper `_append_release(factory, *, prompt_suffixes: dict[str, str], note, actor, restored_from=None) -> int`. It follows `tests/integration/test_conversation_pin_acceptance_postgres.py:125–182`: close the active release at `max(now, effective_from + 1µs)`, insert the next version with `previous_release_id`, and map a new revision for each role in `prompt_suffixes` while reusing the predecessor's revision for the others. With a `restored_from` id, it reuses that release's seven revision ids verbatim. Evidence rows are ORM-seeded `AgentTestRun(run_kind='candidate', execution_status='completed', deterministic_checks_passed=True, verdict='approved', …)` plus `GraphReleaseTestRun` links. Tests:
  - `test_history_lists_every_version_newest_first_with_exact_lineage`: bootstrap v1; v2 changes architect; v3 changes builder; v4 restores v2. The result is `[4, 3, 2, 1]`. v4 has `previous == Ref(v3)`, `restored_from == Ref(v2)` and `changed_agent_keys == ("builder",)`: v2's builder is v1's, so v4 differs from v3 only in builder. v2 has `restored_by == (Ref(v4),)` and `changed_agent_keys == ("architect",)`. v1 has `previous is None` and `changed_agent_keys == GRAPH_V1_AGENT_KEYS`. Only v4 has `is_active`. Every `effective_to` is equal to the next version's `effective_from`, compared after reading both back in a fresh session.
  - `test_detail_has_exact_seven_definitions_and_ordered_evidence`: `read_release_detail(version_number=2)` has seven definitions whose revision ids and hashes equal the mapping, and whose `content` equals `validate_definition_hash(...)` of each row. The evidence is exactly one `ReleaseEvidence(run_id, "architect", case.id, 1, "approval", None, "approved", …)`. For v4, with a `historical_restore` link to the same run with `source_release_id = v2`, the evidence is `(…, "historical_restore", Ref(v2), …)`.
  - `test_unknown_version_raises_not_found`: versions `0`, `99` → `GraphVersionNotFound` with `.version_number` set.
  - `test_linked_non_candidate_run_is_an_integrity_error`: link a `run_kind='published_baseline'` run to v2 → `read_release_detail` raises `GraphConfigurationIntegrityError("release evidence references a non-candidate run")`. The `run_kind='candidate'` filter plus a comparison of filtered and unfiltered link counts is the rule. The query never silently drops the row.
  - `test_incomplete_mapping_is_an_integrity_error`: on SQLite (no guards), delete one mapping row of v2 → `GraphConfigurationIntegrityError`.

- [ ] **Step 2: Run RED.** `test ! -e .venv`; `DATABASE_URL=sqlite:///…/unit.sqlite PYTHONPATH=… /Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_graph_release_history.py`; `test ! -e .venv`. Expected: `ModuleNotFoundError: No module named 'src.services.graph_release_history'`.

- [ ] **Step 3: Implement.** Core of `list_release_history`:

```python
def list_release_history(session: Session) -> tuple[ReleaseHistoryEntry, ...]:
    """Every Graph Release, newest first, as of this function's first statement.

    Releases, mappings and links are insert-only and immutable, so filtering every
    later statement to the ids read here yields one coherent snapshot without locks.
    """
    releases = list(session.scalars(select(GraphRelease).order_by(GraphRelease.version_number.desc())))
    if not releases:
        raise GraphConfigurationIntegrityError("graph configuration has no release")
    ids = [r.id for r in releases]
    mappings: dict[int, dict[str, int]] = {rid: {} for rid in ids}
    for rid, key, rev in session.execute(
        select(GraphReleaseAgent.graph_release_id, GraphReleaseAgent.agent_key,
               GraphReleaseAgent.agent_definition_revision_id)
        .where(GraphReleaseAgent.graph_release_id.in_(ids))):
        mappings[rid][key] = rev
    if any(set(m) != _EXPECTED_AGENT_KEYS for m in mappings.values()):
        raise GraphConfigurationIntegrityError("release mapping rows are incomplete")
    by_id = {r.id: r for r in releases}
    active = [r for r in releases if r.effective_to is None]
    if len(active) != 1:
        raise GraphConfigurationIntegrityError("graph configuration must have exactly one active release")
    ref = lambda rid: None if rid is None else ReleaseRef(rid, by_id[rid].version_number)
    restored_by: dict[int, list[ReleaseRef]] = {rid: [] for rid in ids}
    for r in sorted(releases, key=lambda r: r.version_number):
        if r.restored_from_release_id is not None:
            restored_by[r.restored_from_release_id].append(ReleaseRef(r.id, r.version_number))
    entries = []
    for r in releases:
        prior = mappings.get(r.previous_release_id) if r.previous_release_id else None
        changed = tuple(k for k in GRAPH_V1_AGENT_KEYS
                        if prior is None or prior[k] != mappings[r.id][k])
        entries.append(ReleaseHistoryEntry(
            release_id=r.id, version_number=r.version_number, is_active=r.effective_to is None,
            release_note=r.release_note, published_by=r.published_by, published_at=r.published_at,
            effective_from=r.effective_from, effective_to=r.effective_to,
            previous=ref(r.previous_release_id), restored_from=ref(r.restored_from_release_id),
            restored_by=tuple(restored_by[r.id]), changed_agent_keys=changed))
    return tuple(entries)
```

`read_release_detail` calls `list_release_history` (whose first statement fixes the set), finds the entry or raises `GraphVersionNotFound`, and loads the seven revisions by id. It validates each with `validate_definition_hash(row, expected_hash=row.content_hash, label=f"revision {row.id}")` and requires `row.agent_key == key`. It then reads links joined to `AgentTestRun` with `AgentTestRun.run_kind == "candidate"`, compares against `count(*)` of the release's links, and orders the result by `(GRAPH_V1_AGENT_KEYS.index(agent_key), test_case_id, run id)`.

- [ ] **Step 4: Write RED PostgreSQL test** `tests/integration/test_graph_release_history_postgres.py` (`pytestmark = pytest.mark.postgres`):
  - `test_history_is_coherent_when_a_release_commits_between_statements`. After bootstrap and v2, register an `after_cursor_execute` listener for the history thread. On the first statement matching `FROM GRAPH_RELEASE ORDER BY GRAPH_RELEASE.VERSION_NUMBER DESC`, it commits v3 on another connection with the `_append_release` recipe (guards installed, first-close only). The listener fires exactly once. The result lists exactly `[2, 1]`, with v2 `is_active is True`, and raises nothing. A second call lists `[3, 2, 1]`.
  - `test_history_takes_no_row_lock`: a `before_cursor_execute` recorder over `list_release_history` and `read_release_detail` sees no statement containing `FOR UPDATE`, `FOR SHARE` or `FOR KEY SHARE`. This runs on PostgreSQL because SQLite never renders these clauses, so the test would be vacuous there. It pins the no-lock rule so a later change cannot silently add a lock.
  - `test_history_reads_under_guards_and_restored_lineage_is_exact`: this is the unit lineage scenario on PostgreSQL. It asserts exact `effective_to == next.effective_from` equality on aware datetimes.

- [ ] **Step 5: GREEN.** Unit file; the PostgreSQL file (zero skips); `tests/unit/test_ci_collects_integration_tests.py` after the workflow edit; `tests/unit/test_persisted_graph_release.py` unchanged. Compare causes with Task 0.

- [ ] **Step 6: Sabotage.**
  - **Controller:** compute `changed` against the release's own mapping (`prior = mappings[r.id]`). Predicted RED: `test_history_lists_every_version_newest_first_with_exact_lineage`, because v2's `changed_agent_keys` is `()`.
  - **Reviewer:** build `restored_from=ref(r.previous_release_id)`. Predicted RED: the v4 `restored_from == Ref(v2)` assertion, which observes `Ref(v3)`, on both SQLite and PostgreSQL.
  - Restore each, prove the marker is gone, and re-run GREEN.

- [ ] **Step 7: Commit.**

```bash
git add src/services/graph_release_history.py tests/unit/test_graph_release_history.py \
  tests/integration/test_graph_release_history_postgres.py .github/workflows/test.yml
git commit -m "feat: immutable graph release history read model (#270)"
```

**Phase A ends here. Do not start Task 2 until Task 0 Step 4 passes.**

---

## Task 2: Active-vs-historical comparison, structural validation, and rollback preview

**Files:**
- Create: `src/services/graph_configuration_rollback.py` (`_GraphConfigurationRollback` with `compare_with_active`, `preview_rollback`, and the private helpers `_load_source`, `_structural_issues`, `_draft_effect`, `_historical_evidence(lock=False)`)
- Modify: `src/services/graph_configuration.py` (bases and `__all__`)
- Create: `tests/unit/test_graph_release_rollback.py`

**Interfaces:**
- Consumes: Task 1 (`list_release_history` for version → id resolution, `GraphVersionNotFound`, `ReleaseRef`); I5 `_lock_current_parents(exclusive=False)`; `_snapshot_locked_workbench`; I7 `definition_field_diffs`/`FieldDiff`; the validator tuples and `_run_candidate_validators` (`graph_configuration_draft.py:346–378`); `validate_definition_hash`; I3 `EvidenceLink`.
- Produces: `compare_with_active`, `preview_rollback`, `ReleaseComparison`, `AgentComparison`, `RollbackPreview`, `DraftEffect`, `RollbackBlock`, and `_structural_issues(contents: Mapping[AgentKey, DefinitionContent]) -> tuple[DraftValidationIssue, ...]`.

- [ ] **Step 1: Write RED unit tests (SQLite, v1 backdated one hour as in #269's Task 1).** Build v2 (architect +A), v3 (builder +B) and v4 (architect +C) through #269's real `publish_draft` with #269's test-only `_NoEvidenceGate`. The gate is imported from `tests/unit/test_graph_release_publication.py` by its underscore name, or defined locally if Task 0-B shows it is file-private.
  - `test_compare_active_with_historical_lists_seven_roles_with_exact_diffs`: `compare_with_active(version_number=2)` with v4 active. `agents` has seven entries in `GRAPH_V1_AGENT_KEYS` order. Architect has `same_revision is False` and `field_diffs == (FieldDiff("prompt_text", <v4 text>, <v2 text>),)`. Builder differs (v2 has v1's builder). The other five have `same_revision is True` and `field_diffs == ()`.
  - `test_preview_names_next_version_lineage_evidence_and_default_note`: `preview_rollback(version_number=2)`. `next_version_number == 5`, `source == Ref(v2)`, `active == Ref(v4)`, `lock_version == <current>`, `default_release_note == "Roll back to Graph Version 2."`, `blocked is None`, `issues == ()`. `evidence` equals the v2 links (none under `_NoEvidenceGate`, so `()`); the evidence-bearing variant is Task 9 step 6.
  - `test_preview_draft_effect_is_three_way`: before the preview, save a pending builder edit (+P). `draft_effect == {"architect": "reset", "builder": "kept", <other five>: "unchanged"}`. Architect is clean and the restored content differs. Builder has a pending edit. The others are clean and identical.
  - `test_preview_blocks_source_active_then_matches_active`: `preview_rollback(version_number=4)` gives `blocked == "source_is_active"`. Then publish v5 = the exact v2 mapping (save architect back to v2 text and builder back to v1 text, then publish). `preview_rollback(version_number=2)` then gives `blocked == "matches_active"`.
  - `test_incompatible_historical_release_is_reported_per_role`: monkeypatch `src.services.graph_configuration_draft._PROMPT_ASSEMBLER` with `PromptAssembler(bundles=<defaults minus v2 architect's (version, digest)>)`, keeping v4's architect bundle if it differs. The preview gives `blocked == "incompatible"`, and `issues` begins with `DraftValidationIssue("definitions.architect.protected_assembly.<version|digest>", "protected_bundle_unavailable", "Protected assembly bundle is unavailable.")`. The exact field is per `resolve_bundle` (`prompt_assembler.py:414`). No write occurs; compare the artefact tuples before and after.
  - `test_unknown_version_is_not_found`: `compare_with_active(version_number=99)` and `preview_rollback(version_number=99)` raise `GraphVersionNotFound`.
  - `test_preview_is_read_only_and_calls_no_model`: construct the facade with `remote_endpoint_validator=_MustNotRun()`, a fake whose `validate` raises `AssertionError`. Monkeypatch `src.services.agent_runtime.AgentRuntime.__init__` to raise. The preview succeeds, and the artefact tuples are unchanged.

- [ ] **Step 2: Run RED** (expected: `ModuleNotFoundError: src.services.graph_configuration_rollback`).

- [ ] **Step 3: Implement.**

```python
_CHECKS = ("source_is_active", "matches_active", "incompatible")


class _GraphConfigurationRollback(_GraphConfigurationPublication):
    """Rollback: a thin caller of #269's publication core with historical content."""

    def _load_source(self, session, *, version_number: int):
        release = session.scalar(select(GraphRelease).where(GraphRelease.version_number == version_number))
        if release is None:
            raise GraphVersionNotFound(version_number)
        rows = session.execute(
            select(GraphRelease, GraphReleaseAgent, AgentDefinitionRevision)
            .outerjoin(GraphReleaseAgent, GraphReleaseAgent.graph_release_id == GraphRelease.id)
            .outerjoin(AgentDefinitionRevision,
                       AgentDefinitionRevision.id == GraphReleaseAgent.agent_definition_revision_id)
            .where(GraphRelease.id == release.id)).all()
        try:
            resolved = PersistedGraphReleaseLoader._validate_complete_snapshot(release, rows)
        except GraphReleaseIncompleteError as exc:
            raise GraphConfigurationIntegrityError("historical release is incomplete") from exc
        return release, {k: resolved[k] for k in GRAPH_V1_AGENT_KEYS}

    def _structural_issues(self, contents):
        issues: list[DraftValidationIssue] = []
        for key in GRAPH_V1_AGENT_KEYS:
            for validators in (self.local_candidate_validators, self.post_stale_validators):
                try:
                    self._run_candidate_validators(validators, contents[key])
                except DraftContentRejected as rejection:
                    issues.extend(DraftValidationIssue(f"definitions.{key}.{i.field}", i.code, i.message)
                                  for i in rejection.issues)
                    break   # the writer's phase rule: a failed local phase skips the post-stale phase
        return tuple(issues)

    @staticmethod
    def _draft_effect(snapshot, restored_hashes):
        effect = {}
        for node in snapshot.nodes:
            if node.execution_kind != "model":
                continue
            if node.draft.candidate_hash != node.published.content_hash:
                effect[node.agent_key] = "kept"
            elif restored_hashes[node.agent_key] == node.published.content_hash:
                effect[node.agent_key] = "unchanged"
            else:
                effect[node.agent_key] = "reset"
        return MappingProxyType(effect)

    def _historical_evidence(self, session, *, source_release_id: int, lock: bool):
        statement = (
            select(AgentTestRun)
            .join(GraphReleaseTestRun, GraphReleaseTestRun.agent_test_run_id == AgentTestRun.id)
            .where(GraphReleaseTestRun.graph_release_id == source_release_id,
                   AgentTestRun.run_kind == "candidate")
            .order_by(AgentTestRun.id))
        if lock:
            statement = statement.with_for_update(read=True, of=AgentTestRun)          # L3
        runs = list(session.scalars(statement))
        linked = session.scalar(select(func.count()).select_from(GraphReleaseTestRun)
                                .where(GraphReleaseTestRun.graph_release_id == source_release_id))
        if linked != len(runs):
            raise GraphConfigurationIntegrityError("release evidence references a non-candidate run")
        order = {k: i for i, k in enumerate(GRAPH_V1_AGENT_KEYS)}
        return tuple(EvidenceLink(r.id, r.agent_key, r.test_case_id, "historical_restore", source_release_id)
                     for r in sorted(runs, key=lambda r: (order[r.agent_key], r.test_case_id, r.id)))
```

- `compare_with_active` and `preview_rollback` run inside `with session.begin():`. They take `release_row, draft_row = self._lock_current_parents(session, exclusive=False)`, then `snapshot = self._snapshot_locked_workbench(...)`, then `_load_source`.
- Comparison diffs come from `definition_field_diffs(active_content, historical_content)`.
- `blocked` is the first applicable check in `_CHECKS` order:
  - `source.id == release_row.id` gives `source_is_active`;
  - identical revision ids on all seven gives `matches_active`;
  - non-empty `_structural_issues` gives `incompatible`.
- `issues` are computed even when an earlier check blocks, so the UI can show them.
- `evidence` comes from `_historical_evidence(session, source_release_id=source.id, lock=False)`; Task 3 calls the same query with `lock=True` (L3).
- Structural validation uses exactly the two tuples #269's publication gate uses, never the remote endpoint validator. This decision is recorded, and rollback does no network work (spec §12, "structural validation").
- Add `_GraphConfigurationRollback` first in `GraphConfiguration`'s bases and export the new public names.

- [ ] **Step 4: GREEN.** This file plus `tests/unit/test_graph_release_publication.py`, `tests/unit/test_graph_release_preview.py` (#269), `tests/unit/test_graph_configuration_draft.py`, `tests/unit/test_graph_configuration_workbench.py`, and `tests/unit/test_graph_release_history.py`.

- [ ] **Step 5: Sabotage.**
  - **Controller:** make `_structural_issues` return `()`. Predicted RED: `test_incompatible_historical_release_is_reported_per_role`, where `blocked` is `None`.
  - **Reviewer:** in `_draft_effect`, compare `node.draft.candidate_hash` with `restored_hashes[...]` instead of `node.published.content_hash`. Predicted RED: `test_preview_draft_effect_is_three_way`. Architect becomes `kept`, because its draft (v4 text) differs from the restored v2 text.
  - Restore each.

- [ ] **Step 6: Commit** `git add src/services/graph_configuration_rollback.py src/services/graph_configuration.py tests/unit/test_graph_release_rollback.py && git commit -m "feat: compare graph releases and preview a rollback (#270)"`

---

## Task 3: Restore a historical release as the next Graph Version

**Files:**
- Modify: `src/services/graph_configuration_rollback.py` (`restore_release`, `_validate_rollback_request`, `_verify_rebased_draft`; calls Task 2's `_historical_evidence` with `lock=True`)
- Modify: `src/services/graph_configuration_draft.py` (extract `_assign_locked_candidate` from `_write_locked_content`)
- Modify: `tests/unit/test_graph_release_rollback.py`
- Create: `tests/integration/test_graph_release_rollback_postgres.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:**
- Consumes: I1, I2, I3, I5, I6; Task 2 helpers; #268 readiness callable and I4 `ApprovalEvidenceGate` (negative proof only); `AgentRuntime`, `PersistedGraphReleaseLoader`, `RecordingAgentInvocationIdentitySink`, `DeterministicFakeModelAdapter` (executability proof only).
- Produces: `restore_release`, `RestoredRelease`, `RollbackSourceActive`, `RollbackMatchesActive`, `RollbackIncompatible`; `_assign_locked_candidate`.

- [ ] **Step 1: Write RED unit tests (SQLite).**
  - `test_restore_v3_while_v7_active_produces_v8_restoring_v3`. Publish v2–v7, each changing architect (`+2` … `+7`), through #269's `publish_draft` with `_NoEvidenceGate`. Then call `restore_release(version_number=3, expected_lock_version=L, release_note="Emergency: back to 3", actor="oncall@example.com")`. Assert all of the following:
    - `published.release.version_number == 8`, `previous_release_id == v7.id`, `published.release.restored_from_release_id == v3.id`, `source == Ref(v3)`;
    - all seven `mappings` equal v3's revision ids with `reused is True`, and `changed_agent_keys == ("architect",)`;
    - no new `agent_definition_revision` row exists (id set unchanged);
    - v7's `effective_to == v8.effective_from`, and v3's `effective_to` is unchanged (read back fresh);
    - version numbers are `{1..8}`, each exactly once;
    - the draft `base_release_id == v8.id` and `lock_version == L + 1`;
    - `list_release_history()[0]` is v8 with `restored_from == Ref(v3)`.
  - `test_restore_resets_clean_roles_and_keeps_pending_edits`: before the rollback, save builder +P (pending). `draft_effect == {"architect": "reset", "builder": "kept", …: "unchanged"}`. After the rollback:
    - `read_workbench` shows architect `changed is False` with a draft hash equal to v3's architect hash;
    - builder `changed is True` with its exact pre-rollback candidate hash and content;
    - the rest are unchanged;
    - lock advanced exactly once.
  - `test_stale_lock_returns_conflict_and_writes_nothing`: expected `L - 1` returns exactly `PublicationConflict(expected_lock_version=L-1, current_lock_version=L, active_release_id=v7.id, active_version_number=7, draft=<current>)`. The artefact tuples (revisions, releases with intervals, mappings, links, draft parent, draft agents) are identical before and after.
  - `test_refusals_write_nothing`, parametrized:
    - unknown version gives `GraphVersionNotFound`;
    - version 7 gives `RollbackSourceActive(Ref(v7))`;
    - a matching mapping gives `RollbackMatchesActive`;
    - an incompatible bundle (Task 2's monkeypatch) raises `RollbackIncompatible` with the Task 2 issue first;
    - request issues raise `PublicationRejected` with issues exactly in the order `version_number`, `actor`, `lock_version`, `release_note`. Cases: `version_number=0`, `True`, `"3"`; note `""`, `"   "`, `None`, 2001 characters; actor `""`.
    For each, the artefact tuples are identical, and for request issues a spy proves `_lock_current_parents` was never called.
  - `test_note_is_stored_verbatim`: `"  keep  "` stored exactly; 2000 characters accepted.
  - `test_rollback_calls_no_model_or_remote_validator`: facade built with `remote_endpoint_validator=_MustNotRun()`. `AgentRuntime.__init__`, `AgentTestWorkbench.__init__` and `CatalogRemoteEndpointDraftValidator.validate` are monkeypatched to raise `AssertionError`. The rollback succeeds.
  - `test_assign_locked_candidate_is_the_only_content_writer`: `_write_locked_content` behaviour is unchanged. Covered by the existing `test_graph_configuration_draft.py` in the gate. Also assert with `inspect.getsource` that `_write_locked_content` calls `_assign_locked_candidate`; this is a structural pin reviewed, not relied on.

- [ ] **Step 2: Run RED** (expected: `AttributeError: … has no attribute 'restore_release'`).

- [ ] **Step 3: Implement.** In `graph_configuration_draft.py`:

```python
    @staticmethod
    def _assign_locked_candidate(row: GraphDraftAgent, content: DefinitionContent) -> None:
        """The one draft-agent content write: columns and canonical candidate hash."""
        for column_name, value in definition_content_values(content).items():
            setattr(row, column_name, value)
        row.candidate_hash = definition_content_hash(content)
```

`_write_locked_content` replaces its column loop and hash assignment with `_GraphConfigurationDraft._assign_locked_candidate(locked.selected_row, content)`. `old_hash`/`new_hash` are computed exactly as before. In `graph_configuration_rollback.py`:

```python
    def restore_release(self, session, *, version_number, expected_lock_version, release_note, actor):
        self._validate_rollback_request(version_number, actor, expected_lock_version, release_note)
        with session.begin():
            release_row, draft_row = self._lock_current_parents(session, exclusive=True)   # L0
            draft_rows = {r.agent_key: r for r in
                          self._lock_all_draft_agents(session, draft_id=draft_row.id)}       # L1
            snapshot = self._snapshot_locked_workbench(session, release=release_row, draft=draft_row)
            source, resolved = self._load_source(session, version_number=version_number)
            if expected_lock_version != draft_row.lock_version:
                return PublicationConflict(expected_lock_version, draft_row.lock_version,
                                           release_row.id, release_row.version_number, snapshot.draft)
            active_ref = ReleaseRef(release_row.id, release_row.version_number)
            source_ref = ReleaseRef(source.id, source.version_number)
            if source.id == release_row.id:
                return RollbackSourceActive(active_ref)
            active_ids = {n.agent_key: n.published.revision_id for n in snapshot.nodes
                          if n.execution_kind == "model"}
            if all(resolved[k].agent_definition_revision_id == active_ids[k] for k in GRAPH_V1_AGENT_KEYS):
                return RollbackMatchesActive(active_ref, source_ref)
            contents = {k: resolved[k].content for k in GRAPH_V1_AGENT_KEYS}
            issues = self._structural_issues(contents)
            if issues:
                raise RollbackIncompatible(source_ref, issues)
            evidence = self._historical_evidence(session, source_release_id=source.id, lock=True)  # L3
            effect = self._draft_effect(snapshot, {k: resolved[k].content_hash for k in GRAPH_V1_AGENT_KEYS})
            published = self._commit_locked_publication(
                session, release_row=release_row, draft_row=draft_row, snapshot=snapshot,
                contents=contents, evidence=evidence, release_note=release_note, actor=actor,
                restored_from_release_id=source.id)
            if not all(m.reused for m in published.mappings.values()):
                raise GraphConfigurationIntegrityError("rollback materialized a new revision")
            for key, code in effect.items():
                if code == "reset":
                    self._assign_locked_candidate(draft_rows[key], contents[key])
            session.flush()
            self._verify_rebased_draft(session, draft_row=draft_row, effect=effect,
                                       before=snapshot, restored=contents)
            return RestoredRelease(published, source_ref, effect)
```

- `_validate_rollback_request` prepends a `version_number` `strict_type` issue for a non-int, a bool, or a value below 1. It then appends #269's `_actor_and_lock_issues` and note issues, and raises `PublicationRejected`.
- `_verify_rebased_draft` re-snapshots through `_snapshot_locked_workbench(session, release=<new release row>, draft=draft_row)`. It requires `reset`/`unchanged` roles to be `changed is False`, and `kept` roles to keep their exact prior `candidate_hash`. Otherwise it raises `GraphConfigurationIntegrityError`.
- `RollbackIncompatible` is raised inside `session.begin()`, so the transaction rolls back. No write precedes it.

- [ ] **Step 4: Write RED PostgreSQL tests** in `tests/integration/test_graph_release_rollback_postgres.py`. Every test starts `pytestmark = pytest.mark.postgres`, bootstraps, and publishes v2–v7 through #269's **real** `publish_draft` and `ApprovalEvidenceGate`. Evidence is produced through #267's `execute_candidate_run` with `DeterministicFakeModelAdapter` and #268's `record_verdict`. If Task 0-B shows either cannot be driven from a test, fall back to ORM seeding and record that. So v3 links approved run `R3` for architect's required case.
  - `test_v8_restores_v3_with_exact_intervals_mappings_and_evidence`. Everything in the SQLite happy path, plus:
    - `graph_release_test_run` rows for v8 are exactly `{(v8.id, R3, 'historical_restore', v3.id)}`;
    - v3's own `(v3.id, R3, 'approval', NULL)` row is unchanged;
    - `agent_test_run` rows (id, verdict columns) are byte-identical before and after, and no new run exists;
    - aware-datetime equality `v7.effective_to == v8.effective_from == v8.published_at == draft.updated_at`.
  - `test_injected_failure_rolls_back_every_row`, parametrized over stage:
    - `interval_closed`: `UPDATE GRAPH_RELEASE SET EFFECTIVE_TO`;
    - `mappings_read_back`: `SELECT GRAPH_RELEASE_AGENT.AGENT_KEY`;
    - `evidence_linked`: `INSERT INTO GRAPH_RELEASE_TEST_RUN`;
    - `draft_reset`: `UPDATE GRAPH_DRAFT_AGENT SET`;
    - `commit`: #269 C8's test-only deferred constraint trigger.
    Use #269 C8's listener recipe on the rollback thread. Assert that the exact injected error is raised; that it fired once; that the artefact tuples equal "before" exactly; that a fresh `lock_active_graph_release` returns v7; and that an un-injected retry with the same lock produces version **8** (no gap).
  - `test_restore_a_restoration_links_its_links_with_the_selected_source` (Review Focus 1). After v8 restores v3, publish v9 (architect +9, approval R9). Restore v8 and get v10 with `restored_from == v8.id`. Its links are exactly `{(v10, R3, 'historical_restore', v8.id)}`. `list_release_history` gives v8 `restored_by == (Ref(v10),)` and v3 `restored_by == (Ref(v8),)`.
  - `test_restore_v1_links_no_evidence` (Review Focus 2): restore v1 while v7 is active. v8 has zero link rows and seven reused bootstrap revisions.
  - `test_pinned_historical_releases_remain_readable_and_executable`:
    - Before the rollback, `SessionManager().create_session(session_id="pinned-v7", created_by=…, graph_capable=True)` pins v7, using the `managed_session` patches from `test_conversation_pin_acceptance_postgres.py:375–385`.
    - After the rollback:
      - `load_conversation_pin(factory, "pinned-v7") == v7.id`;
      - `get_conversation_graph_version` reports `(7, 8, True)`;
      - a new `pinned-v8` conversation pins v8.
    - An `AgentRuntime(persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory), model_adapter=DeterministicFakeModelAdapter(...), identity_sink=RecordingAgentInvocationIdentitySink())` runs `architect` against closed v7, closed v3 and active v8. Each run uses the seeded architect smoke case's payload and `AgentAssemblyContext` (construct per `agent_runtime.py:151`; record the exact constructor at Task 0-B). Assert:
      - each run completes;
      - the sink's `successes` carry `graph_release_id` equal to v7, v3 and v8 in turn, and the architect revision id of each mapping;
      - v8's revision id equals v3's.
  - `test_historical_restore_evidence_never_satisfies_readiness` (Review Focus 4):
    - After v8 restores v3 (link `R3 historical_restore`), save architect with new content H.
    - #268 readiness reports architect's required case as blocking.
    - `publish_draft(..., evidence_gate=ApprovalEvidenceGate(readiness=<production callable>))` returns exactly `PublicationNotReady(locked_gaps=(PublicationGap("architect", case.id, "no_eligible_approval"),), …)`.
    - Nothing is written.
    - Also save the kept-edit variant, a builder edit made before the rollback. It is still not ready after the rollback, although v8 links approved runs for builder's case from v3 if v3 changed builder. Make v3 change builder too, so the link exists.

- [ ] **Step 5: GREEN.** Unit files; this PostgreSQL file (zero skips); #269's `test_graph_release_publication_postgres.py` and `test_graph_release_evidence_postgres.py`; `test_agent_definition_workbench_postgres.py`; `test_agent_schema_overlay_postgres.py`; the CI guard.

- [ ] **Step 6: Sabotage.**
  - **Controller:** pass `restored_from_release_id=None` to the core. Predicted RED: `test_restore_v3_while_v7_active_produces_v8_restoring_v3` (SQLite) and `test_v8_restores_v3_…` (PostgreSQL), which observe `None`.
  - **Reviewer:** delete the `reset` loop (parent-only rebase). Predicted RED: `test_restore_resets_clean_roles_and_keeps_pending_edits`. `_verify_rebased_draft` raises `GraphConfigurationIntegrityError`, because architect is still `changed`.
  - Restore each.

- [ ] **Step 7: Commit** `git add src/services/graph_configuration_rollback.py src/services/graph_configuration_draft.py tests/unit/test_graph_release_rollback.py tests/integration/test_graph_release_rollback_postgres.py .github/workflows/test.yml && git commit -m "feat: restore a historical graph release as the next version (#270)"`

---

## Task 4: Rollback against publication, rollback, draft saves and verdicts — forced orderings

**Files:**
- Create: `tests/integration/test_graph_release_rollback_ordering_postgres.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:**
- Consumes: Task 3; #269 `publish_draft`, `_NoEvidenceGate`/`_save_prompt`, and `_await_blocked_by` (I12); #268 `record_verdict`; the PID-capture subclass pattern (#269 C5).
- Produces: proof that rollback linearizes at L0 with every other L0 writer.

All tests seed v1–v4 (architect changed each time, approvals linked) and restore v2 while v4 is active unless stated. The blocker pause is an `after_cursor_execute` listener on the named thread. It fires after that thread's first statement containing `FOR UPDATE`, and records its normalized text. The test then asserts that the text contains `FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT` (C6).

- [ ] **Step 1: Write RED tests.**
  - `test_rollback_first_then_publication_is_stale`:
    - The `rollback` thread pauses after L0. A publisher with expected lock L starts. Assert `_await_blocked_by(waiter=publisher_pid, blocker=rollback_pid)`.
    - Release the rollback. It returns `RestoredRelease` with version 5 and `restored_from == v2`.
    - The publisher returns exactly `PublicationConflict(L, L+1, <v5 id>, 5, <draft>)`.
    - The release set is `{1..5}`, and only v5 is active.
  - `test_publication_first_then_rollback_is_stale_and_not_v6`:
    - The publisher pauses after L0. Assert that the rollback (expected lock L) is blocked by the publisher PID.
    - Release the publisher. It returns v5.
    - The rollback returns exactly `PublicationConflict(L, L+1, <v5 id>, 5, …)` after scanning twice (a statement recorder shows two L0 executions: the handoff retry).
    - No v6 exists.
  - `test_two_rollbacks_one_winner_one_exact_stale_conflict`, parametrized over which thread wins (both restore v2 with lock L): the winner produces v5; the loser returns `PublicationConflict(L, L+1, v5, 5, …)`; exactly five releases exist.
  - `test_sequential_rollback_retry_is_stale` (Review Focus 3): restore v2, then restore v2 again with the same lock. The result is `PublicationConflict` naming v5, and there is no v6.
  - `test_draft_save_first_then_rollback_is_stale` and `test_rollback_first_then_draft_save_is_stale_not_500`, in both orders:
    - Save-first: the rollback is blocked by the saver PID, then returns stale with `current_lock_version == L+1`. Draft content is exactly the saver's.
    - Rollback-first: the saver is blocked by the rollback PID, then returns `DraftSaveConflict` whose server draft is `base_version_number == 5`, with reset roles carrying v2's hashes. It is never a `GraphConfigurationIntegrityError`.
  - `test_workbench_read_during_rollback_sees_coherent_new_release`: the reader (`read_workbench`, `FOR SHARE`) is blocked by the rollback PID. After release it returns active v5, and every reset role has `changed is False`.
  - `test_verdict_change_on_source_linked_run_waits_then_is_refused`:
    - The rollback pauses after its L3 statement. The listener matches `FROM AGENT_TEST_RUN JOIN GRAPH_RELEASE_TEST_RUN … FOR SHARE OF AGENT_TEST_RUN`.
    - `record_verdict(run_id=R2, verdict="rejected", …)` on thread `verdict` is observed blocked by the rollback PID. Its PID is captured by wrapping #268's entry point per C5.
    - Release the rollback. It returns v5, linking R2 as `historical_restore`.
    - The verdict writer fails with `IntegrityError` SQLSTATE `23514` (I10). R2 stays `approved`, and both links exist.

- [ ] **Step 2: RED.** Missing file or imports only. This task adds no production code unless a real ordering defect appears. If one does, stop and add a corrections row before fixing.

- [ ] **Step 3: GREEN.** Run each file separately with zero skips: this file, Task 3's file, #269's `test_graph_release_publication_postgres.py` and `test_graph_release_evidence_postgres.py`, and `test_agent_definition_workbench_postgres.py`. Then the CI guard.

- [ ] **Step 4: Sabotage.**
  - **Controller:** in `restore_release`, use `self._lock_current_parents(session, exclusive=False)`. Predicted RED: `test_two_rollbacks_one_winner_one_exact_stale_conflict` at `_await_blocked_by`. The loser shares the lock and is not blocked. If the run proceeds, `DeadlockDetected` or a unique violation follows; record the observed cause.
  - **Reviewer:** delete the `expected_lock_version != draft_row.lock_version` branch in `restore_release`. Predicted RED: `test_publication_first_then_rollback_is_stale_and_not_v6`, which observes `RestoredRelease(version_number=6)`.
  - Restore each, prove the marker is gone, and re-run GREEN.

- [ ] **Step 5: Commit** `git add tests/integration/test_graph_release_rollback_ordering_postgres.py .github/workflows/test.yml && git commit -m "test: force rollback orderings against publication, saves and verdicts (#270)"`

---

## Task 5: Rollback against conversation creation (every creator) and evidence cleanup

**Files:**
- Modify: `tests/integration/test_graph_release_session_ordering_postgres.py` (#269's creator-ordering file; append, do not copy)
- Modify: `tests/integration/test_graph_release_rollback_ordering_postgres.py`

**Interfaces:**
- Consumes: `CREATORS`, `_create`, `_creator_patches`, `_backend_pid` (`tests/integration/test_mixed_release_creation_postgres.py:27`, `:129`, `:175`, `:125`) as #269 Task 3 imports them; Task 3; #268 `cleanup_unpublished_test_runs`.
- Produces: proof that rollback linearizes with all four creation paths at the release row and cannot lose evidence to cleanup.

- [ ] **Step 1: Write RED tests** (parametrized over `CREATORS`; seed v1–v4 with #269's recipe; `contributor`/`duplicate` sources pinned to v4).
  - `test_rollback_first_each_creator_pins_the_restoring_release`:
    - The rollback pauses after L0. The creator is observed blocked by the rollback PID (`before_cursor_execute` PID).
    - Release the rollback. The creator's per-scan row counts equal the sequence #269 Task 3 asserts for publication.
    - The creator's pin is the v5 id, and `graph_version == 5`. The source session still pins v4.
  - `test_creation_first_rollback_waits_and_creator_keeps_v4`:
    - The creator pauses after `INSERT INTO user_sessions`. The rollback is blocked by the creator PID, and its `pg_stat_activity.query` contains `FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT`.
    - Release: the creator pins v4. The rollback returns v5 with `previous_release_id == v4.id`.
    - `get_conversation_graph_version` for the creator gives `(4, 5, True)`.
  - `test_creator_behind_fully_flushed_rollback_never_sees_partial_release`, parametrized over `CREATORS` × {`rollback`, `commit`}:
    - The rollback pauses after its last draft-agent `UPDATE GRAPH_DRAFT_AGENT SET` (all writes flushed), and the creator is observed blocked.
    - `rollback`: an injected error pins exactly v4, and v4 is still active.
    - `commit`: the creator pins exactly v5.
  - In the ordering file, `test_cleanup_first_then_rollback` and `test_rollback_first_then_cleanup`:
    - Seed architect's required case with 25 runs. `R2` (linked to v2 as `approval`) is the oldest, outside the latest 20.
    - Cleanup-first: cleanup pauses after its `graph_draft FOR SHARE`, and the rollback is observed blocked by the cleanup PID. After release, cleanup deletes exactly the ineligible unlinked ids (exact set per #268's rule, recorded at Task 0-B). The rollback links exactly R2.
    - Rollback-first: cleanup is observed blocked by the rollback PID. After release, R2 is retained with two links.
    - In both orders the retained set includes R2.

- [ ] **Step 2: RED → Step 3: GREEN.** No production change is expected. Run each file separately with zero skips: both files, `test_mixed_release_creation_postgres.py`, `test_conversation_pin_creation_postgres.py`, `test_conversation_creator_exclusions_postgres.py`, `test_conversation_pin_acceptance_postgres.py`. Then the CI guard.

- [ ] **Step 4: Sabotage.**
  - **Controller:** in `restore_release`, replace the L0 statement with one locking only `graph_draft` `FOR UPDATE` and reading the release unlocked. Predicted RED: `test_rollback_first_each_creator_pins_the_restoring_release` for every creator at `_await_blocked_by`. The creator pins v4 and commits.
  - **Reviewer:** set `MAX_ACTIVE_RELEASE_LOCK_SCANS = 1` in `conversation_pins.py:55`. Predicted RED: the rollback-first test for every creator, with `ActiveGraphReleaseUnavailableError`.
  - Restore each.

- [ ] **Step 5: Commit** `git add tests/integration/test_graph_release_session_ordering_postgres.py tests/integration/test_graph_release_rollback_ordering_postgres.py && git commit -m "test: prove rollback linearizes with conversation creation and cleanup (#270)"`

---

## Task 6: Admin HTTP routes for history, comparison, preview and rollback

**Files:**
- Modify: the module holding #269's release handlers on the one admin router (expected `src/api/routes/agent_definitions.py`; Task 0-B records it)
- Create: `src/api/schemas/graph_release_history.py`
- Create: `tests/unit/test_graph_release_history_routes.py`

**Interfaces:**
- Consumes: Tasks 1–3; `require_draft_write_principal`; `ActiveReleaseResponse`, `DraftMetadataResponse`, `DraftFieldErrorResponse` (`src/api/schemas/agent_definitions.py`); #269's publish-route malformed-JSON and 422 helpers (reuse, do not copy).
- Produces: the "HTTP contract" table.

- [ ] **Step 1: Write RED route tests.** Use the SQLite fixture from `tests/unit/test_agent_definition_workbench_routes.py:118–157`, plus v1 backdating, with v2–v4 built through `publish_draft` and `_NoEvidenceGate`.
  - **Admin:** non-admin `GET` of all four reads and the `POST` returns 403, and neither the service nor `request.json` is called (pattern: the existing non-admin tests). A blank principal on `POST` returns 403.
  - **Reads:** exact bodies for list, detail, comparison and preview (compare full JSON documents). Detail `definitions.<key>.content` equals `canonical_payload()`. Version `99` and `2**31` return 404 `{"detail": "Graph Version not found"}`.
  - **Rollback outcomes:** success is exactly 200 with seven `reused: true` mappings. Also exact bodies for `stale_rollback`, `rollback_source_active`, `rollback_matches_active`, `rollback_incompatible` (monkeypatched bundle) and `invalid_rollback` (malformed JSON, extra key, non-int lock, blank note, 2001-character note). An integrity error returns 500 `{"detail": "Graph configuration is incomplete"}`.
  - **No model or remote work:** `app.dependency_overrides` makes `get_remote_endpoint_draft_validator`, `get_model_endpoint_catalog`, `get_structured_output_probe` and `get_agent_test_workbench` raise `AssertionError`. Every new route still succeeds, which proves the handlers do not depend on them.
  - **Log contract:** `caplog` at INFO captures exactly one `graph_release_rollback` record per call. Its `extra` keys are exactly `{"outcome", "agent_keys"}` (plus `error_class` on the integrity case). For the success case, no record text or extra value contains the note, the actor, a hash, a release id or `"3"` as a version.
  - **Registration:** `test_rollback_routes_register_once_on_the_one_router` asserts each of the five method+path pairs exists exactly once in `src.api.main.app.routes`. It also asserts that `src/api/main.py` is unchanged against `INTEGRATION_BASE` (`git diff --exit-code INTEGRATION_BASE -- src/api/main.py`, run in the gate, not in pytest).

- [ ] **Step 2: RED** (404 for every new path).

- [ ] **Step 3: Implement.**
  - `RollbackRequest` is `ConfigDict(extra="forbid", strict=True)` with `lock_version: int` (`ge=0`) and `release_note: str`, with no `max_length`: the service is the one authority (#269 C10).
  - Parse only inside the handler, after dependencies. Run the service with `run_in_threadpool`, following the existing blocking-DB idiom.
  - Map outcomes:
    - `GraphVersionNotFound` → 404;
    - `PublicationRejected` → 422 `invalid_rollback`;
    - `RollbackIncompatible` → 422 `rollback_incompatible`;
    - `PublicationConflict` → 409 `stale_rollback`;
    - `RollbackSourceActive` / `RollbackMatchesActive` → 409;
    - `GraphConfigurationIntegrityError` → 500 with `logger.exception`.
  - Emit the one log record per the contract.

- [ ] **Step 4: GREEN.** This file, #269's `tests/unit/test_graph_release_routes.py`, and `tests/unit/test_agent_definition_workbench_routes.py`. Then `git diff --exit-code $(cat .superpowers/sdd/2026-09-26-graph-release-history-rollback/INTEGRATION_BASE) -- src/api/main.py`.

- [ ] **Step 5: Sabotage.**
  - **Controller:** remove `Depends(require_draft_write_principal)` from the rollback handler, and pass `actor=""`. Predicted RED: the blank-principal test, which observes 422 or 500 instead of 403.
  - **Reviewer:** add `validator: Annotated[RemoteEndpointDraftValidator, Depends(get_remote_endpoint_draft_validator)]` to the rollback handler signature. Predicted RED: the no-model/remote dependency test, where the raising override fires.
  - Restore each.

- [ ] **Step 6: Commit** `git commit -m "feat: admin HTTP for graph release history and rollback (#270)"` with the exact files.

---

## Task 7: Typed client and the Release History tab

**Files:**
- Modify: `frontend/src/api/agentDefinitions.ts` (append types, strict parsers, and `listGraphReleases`, `getGraphRelease`, `compareGraphRelease`, `getRollbackPreview`, `rollbackGraphRelease`)
- Create: `frontend/src/components/Admin/GraphRelease/ReleaseHistoryTab.tsx`
- Create: `frontend/src/components/Admin/GraphRelease/ReleaseHistoryTab.test.tsx`
- Modify: `frontend/src/components/Admin/GraphRelease/reviewAndPublishState.ts` and `.test.ts` (#269's one reducer: add the history slice and rollback phases)
- Modify: `frontend/src/components/Admin/GraphRelease/ReviewAndPublishPage.tsx` (third tab; wire the shared counter and gate)
- Modify: `frontend/src/api/agentDefinitions.test.ts` if #269 created it (else parser tests live in the reducer test)

**Interfaces:**
- Consumes: Task 6 wire; I8 (#269's reducer, counter, gate, `lineDiff`, `AgentDefinitionApiError`).
- Produces the following `data-testid`s:
  - `release-history-tab`, `release-history-row-<version>`, `release-history-detail`, `release-comparison`;
  - `rollback-preview`, `rollback-note-input`, `rollback-confirm-button`, `rollback-cancel-button`, `rollback-blocked-panel`, `rollback-stale-alert`, `rollback-success-panel`.
- Accessible names added:
  - tab `Release History` (spec §13.2);
  - per-row buttons `Inspect Graph Version N` and, on every non-active row, `Roll back to Graph Version N`;
  - textarea label `Rollback note`;
  - buttons `Confirm rollback` and `Cancel rollback`;
  - row badges (text, not controls) `Active` and `Restores Graph Version M`.

- [ ] **Step 1: RED Vitest.**
  - **Reducer.** Add history phases `idle | loading | ready | error`; inspection `none | loading | shown`; and rollback phases `closed | previewLoading | confirming | rollingBack | stale | blocked | invalid | restored | error`.
    - `confirm` is allowed only from `confirming` with `preview.restorable`, `note.trim() !== ''` and `note.length <= 2000`, and only while the page gate is free.
    - While `rollingBack`, `publish` is refused; while `publishing`, `openRollback` and `confirm` are refused. This is the one gate.
    - The preview note starts as `default_release_note`, and an edited note survives a stale reload.
    - `restored` triggers exactly one history refetch and one release-preview refetch.
    - Out-of-order history or preview answers are dropped by the one request counter.
  - **Parsers** reject: missing or extra keys; `draft_effect` without exactly seven keys or with values outside `reset|kept|unchanged`; `blocked` outside its three values or null; a success body whose mappings are not all `reused: true`; evidence whose `evidence_kind` is not `historical_restore`.
  - **Component (mocked fetch):**
    - rows newest first, showing author, note, published time, `effective_from`/`effective_to`, predecessor, changed roles and `Restores Graph Version M`;
    - the active row shows `Active` and has no rollback button;
    - `Inspect Graph Version 2` shows seven definitions, evidence rows (kind, source version, verdict), and field diffs against active, with `prompt_text` rendered through `lineDiff`;
    - `Roll back to Graph Version 2` issues exactly one preview GET and zero POSTs, then shows the lineage sentence `Graph Version 5 will restore Graph Version 2 (predecessor Graph Version 4).`, the seven mappings, the draft effect (`Reset to restored content` / `Pending edit kept` / `Unchanged`) and the evidence count;
    - a `blocked` preview disables `Confirm rollback` and lists the issues, with the text `The active release is unchanged.`;
    - a blank note disables confirm;
    - one POST per click;
    - 409 `stale_rollback` shows an alert naming the current lock version and active Graph Version, with the page's existing reload action (no automatic retry);
    - 422 `rollback_incompatible` lists the issues; 422 `invalid_rollback` shows the note error beside the textarea;
    - success shows `Graph Version 5 restores Graph Version 2` and `The shared draft is now based on Graph Version 5`, and the history list shows v5 first.

- [ ] **Step 2: RED** `(cd frontend && npm run test:unit -- src/components/Admin/GraphRelease)`.

- [ ] **Step 3: Implement.** The tab is rendered by `ReviewAndPublishPage` as a third tab after `Definition Diff`. It dispatches only into the page reducer; `ReleaseHistoryTab` owns no `useReducer`, request counter or gate.

- [ ] **Step 4: GREEN.** Run Vitest for `src/components/Admin/GraphRelease` and `src/components/Admin/AgentDefinitionWorkbench` (unchanged, including the `ALLOWED_ACTION_NAMES` length test at the Task 0-B value). Then `(cd frontend && npm run typecheck)`, and `(cd frontend && npx eslint src/api/agentDefinitions.ts src/components/Admin/GraphRelease)`.

- [ ] **Step 5: Sabotage.**
  - **Controller:** drop `note.trim() !== ''` from the confirm guard. Predicted RED: "a blank note disables confirm".
  - **Reviewer:** give rollback its own in-flight flag instead of the page gate. Predicted RED: the reducer test "publish is refused while rollingBack".
  - Restore each.

- [ ] **Step 6: Commit** `git commit -m "feat: release history, inspection and rollback in the admin UI (#270)"`.

---

## Task 8: Browser proof, name-collision rule, and route gate

**Files:**
- Create: `frontend/tests/e2e/graph-release-history.spec.ts`
- Modify: `frontend/tests/e2e/admin-route-gate.spec.ts` only if #269 did not already cover `/admin/agent-definitions/review` for non-admins (Task 0-B)

**Interfaces:** Consumes Task 6 wire via `page.route` mocks and Task 7 `data-testid`s. Produces the browser seam #271 extends.

- [ ] **Step 1: RED Playwright tests.**
  - **(a) Inspection:** history renders seven versions with the `Restores Graph Version 3` badge on v8. Inspecting v3 shows definitions, evidence and diffs.
  - **(b) Confirmation:** `Roll back to Graph Version 3` issues exactly one preview GET and zero POSTs. Then `Confirm rollback` issues exactly one POST, whose body is `{"lock_version": <preview lock>, "release_note": "Roll back to Graph Version 3."}`.
  - **(c) Failure paths:** 422 `rollback_incompatible` shows the blocked panel and zero further POSTs. 409 `stale_rollback` shows the alert, keeps the typed note, and reloads with exactly one GET.
  - **(d) Success:** v8 appears first. The Changes & Approvals tab refetch shows `Draft base: Graph Version 8`.
  - **(e) No-flash:** a non-admin visiting `/admin/agent-definitions/review` is redirected with no admin content flash.
  - **(f) Name collisions:** on the page in states `ready`, `confirming`, `blocked` and `restored` (fixture with versions 1–8), collect every interactive control's accessible name, both #269's and #270's. Assert no two distinct names are equal, and none is a case-insensitive substring of another.
  - **(g) Two-digit versions** (Review Focus 5): with versions 1–12, `getByRole('button', { name: 'Roll back to Graph Version 1', exact: true })` and the same for `12` each resolve to exactly one element.
  - **(h) Workbench sweep unchanged:** the workbench forbidden sweep in `agent-definition-workbench.spec.ts` still passes, still flags `Release history` and `Rollback release`, and no #270 control renders inside the workbench panel.

- [ ] **Step 2: RED** `(cd frontend && npx playwright test tests/e2e/graph-release-history.spec.ts --project=chromium --workers=1)`.

- [ ] **Step 3: Implement.** Spec and fixture edits only. Any production fix needs a corrections row.

- [ ] **Step 4: GREEN.** Run each of these with `--project=chromium --workers=1`: this spec, #269's `graph-release-review.spec.ts`, `agent-definition-workbench.spec.ts`, `admin-route-gate.spec.ts` and `admin-page.spec.ts`.

- [ ] **Step 5: Sabotage.**
  - **Controller:** render `Roll back to Graph Version N` on the active row too. Predicted RED: (a)'s "active row has no rollback control" assertion.
  - **Reviewer:** rename `Cancel rollback` to `Rollback`. Predicted RED: (f). `Rollback` is a case-insensitive substring of `Confirm rollback`.
  - Restore each.

- [ ] **Step 6: Commit** `git commit -m "test: browser proof for release history and rollback (#270)"`.

---

## Task 9: Real-PostgreSQL HTTP acceptance — restoring v3 while v7 is active produces v8

**Files:**
- Create: `tests/integration/test_graph_release_rollback_acceptance_postgres.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:** Consumes the shipped admin router over real PostgreSQL with the `real_route_stack` recipe (`tests/integration/test_agent_definition_workbench_postgres.py:1284–1310`), #267's routes with `DeterministicFakeModelAdapter`, #268's verdict route, and #269's publish route. Extends #269's Task 8 acceptance pattern rather than rewriting it.

- [ ] **Step 1: RED test** `test_restore_v3_while_v7_active_over_http`. The flow:
  1. Bootstrap. For `n` in 2..7, via HTTP only: PUT an architect draft `+n`; POST its required case run; POST verdict `approved`; POST `/releases` with the current lock. Assert 200 and `version_number == n`. For `n == 3` also change builder, and approve builder's run.
  2. Create conversation `c7` (pins v7).
  3. PUT a pending fixer edit, without approving it.
  4. GET `/releases`: versions `[7..1]`, v7 active.
  5. GET `/releases/3/comparison`: architect and builder `same_revision: false`, exact `prompt_text` diffs.
  6. GET `/releases/3/rollback-preview`: `next_version_number == 8`, `restorable is true`, `draft_effect == {"architect": "reset", "builder": "reset", "fixer": "kept", …: "unchanged"}`, and `evidence` run ids == v3's approval run ids.
  7. POST `/releases/3/rollback` with the preview's lock: exact 200. `release.version_number == 8`, `restored_from == {v3}`, seven `reused: true` mappings equal v3's, and evidence exactly v3's runs as `historical_restore` with `source_release_id == v3`.
  8. A second identical POST: exact 409 `stale_rollback` naming v8.
  9. GET `/releases`: v8 first with `restored_from` v3 and `previous` v7; v3 `restored_by == [v8]`; no version reused (`[8..1]`).
  10. `c7` still pins v7, and a new conversation pins v8.
  11. GET the workbench: base v8; architect and builder clean; fixer changed and still blocking readiness.
  12. POST `/releases` with the current lock: exact 409 `publication_not_ready` naming fixer's case only.

- [ ] **Step 2: RED → Step 3: GREEN.** No production change is expected. Zero skips; CI guard green.

- [ ] **Step 4: Sabotage.**
  - **Controller:** in `restore_release` and `preview_rollback`, pass `source_release_id=release_row.id` (the active release) to `_historical_evidence` instead of `source.id`. Predicted RED: step 6/7 evidence ids, which observe v7's run ids.
  - **Reviewer:** make `_draft_effect` return `reset` for every role whose restored hash differs (reset-all). Predicted RED: step 6's `fixer: kept`, and step 11's fixer changed/blocking assertion.
  - Restore each.

- [ ] **Step 5: Commit** `git commit -m "test: end-to-end rollback acceptance over admin HTTP (#270)"`.

---

## Task 10: Whole-slice verification, whole-branch review, and local merge

- [ ] **Backend matrix.** Each run is preceded and followed by `test ! -e .venv`, and uses the exact interpreter, `PYTHONPATH` and `DATABASE_URL=sqlite:///…`:

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_graph_release_history.py tests/unit/test_graph_release_rollback.py \
  tests/unit/test_graph_release_history_routes.py tests/unit/test_graph_release_publication.py \
  tests/unit/test_graph_release_evidence.py tests/unit/test_graph_release_preview.py \
  tests/unit/test_graph_release_routes.py tests/unit/test_graph_configuration_bootstrap.py \
  tests/unit/test_graph_configuration_draft.py tests/unit/test_graph_configuration_workbench.py \
  tests/unit/test_graph_configuration_models.py tests/unit/test_persisted_graph_release.py \
  tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_agent_test_workbench.py \
  tests/unit/test_conversation_pin_creation.py tests/unit/test_ci_collects_integration_tests.py
# plus every #268 unit file recorded at Task 0-B
```

- [ ] **PostgreSQL matrix.** One command per file, zero skips each:
  - this plan's files: `test_graph_release_history_postgres.py`, `test_graph_release_rollback_postgres.py`, `test_graph_release_rollback_ordering_postgres.py`, `test_graph_release_rollback_acceptance_postgres.py`;
  - #269's files: `test_graph_release_publication_postgres.py`, `test_graph_release_session_ordering_postgres.py`, `test_graph_release_evidence_postgres.py`, `test_graph_release_publication_acceptance_postgres.py`;
  - existing files: `test_graph_configuration_bootstrap_postgres.py`, `test_graph_configuration_constraints_postgres.py`, `test_agent_definition_workbench_postgres.py`, `test_agent_schema_overlay_postgres.py`, `test_conversation_pin_creation_postgres.py`, `test_conversation_pin_migration_postgres.py`, `test_mixed_release_creation_postgres.py`, `test_conversation_creator_exclusions_postgres.py`, `test_conversation_pin_acceptance_postgres.py`, `test_persisted_graph_runtime_failures_postgres.py`, `test_mixed_release_collaboration_acceptance_postgres.py`;
  - every #268 PostgreSQL file.
- [ ] **Frontend matrix.** Vitest for `src/components/Admin/GraphRelease src/components/Admin/AgentDefinitionWorkbench`; `npm run typecheck`; ESLint on touched files; Playwright `graph-release-history.spec.ts`, `graph-release-review.spec.ts`, `agent-definition-workbench.spec.ts`, `admin-route-gate.spec.ts`, `admin-page.spec.ts`. Compare causes, not counts.
- [ ] **Controller final sabotage** on a seam no task used: in #269's `ApprovalEvidenceGate.lock_and_verify`, additionally accept any approved candidate run linked to the **active** release, of any kind, for a changed role's case, regardless of hash. Predicted RED: `test_historical_restore_evidence_never_satisfies_readiness`, which publishes instead of returning `PublicationNotReady`. Restore.
- [ ] **Whole-branch review** from exactly `INTEGRATION_BASE..HEAD`. Attach proof that it is the rebased Task 1 plus Tasks 2–9 only. Run it on the most capable reviewer, with `PLAN-CORRECTIONS.md`, all reports, every ledger ruling and deferred item, and all sabotage evidence. Require:
  1. **Writer-by-writer table:** `restore_release`, `_commit_locked_publication` as called by rollback, `_assign_locked_candidate` and its two callers, `_advance_locked_draft`, `link_release_evidence`, the #268 verdict writer and cleanup, session creation, and bootstrap validation. For each: locks in order, rows written, timestamp source, and rollback behaviour.
  2. **Lock-order table re-derived from code,** including implicit FK `KEY SHARE` on the closed source release, revisions and runs, with the deadlock-freedom argument.
  3. **No-write ruling for every non-success outcome:** `PublicationRejected`, `PublicationConflict`, `GraphVersionNotFound`, `RollbackSourceActive`, `RollbackMatchesActive`, `RollbackIncompatible`, integrity errors, and each injected stage.
  4. **Model-path confirmation:** no path from any #270 route or service reaches `AgentRuntime`, an adapter, a catalog, a probe or the remote endpoint validator. No transaction is held across a model call.
  5. **Thin-caller confirmation:** rollback adds no second publication core, no second draft-content writer, no second router, no second reducer, counter or gate, and no `main.py` change.
  6. **Q7 review:** the three-way rebase against §5.4, §11.4 and §12.
  7. **Log and model-identifier contract review.**
  8. **Merge/no-merge verdict.** Allow one fix wave and one scoped re-review.
- [ ] **Pre-merge gate.** Re-resolve the final reviewed #268/#269 heads and the current local root. Prove each head and `INTEGRATION_BASE` are ancestors of both. Recompute the reviewed diff as `INTEGRATION_BASE..HEAD`, and refuse the merge if local-root reconciliation changes it. If any predecessor advanced: rebase, refresh corrections and baselines, and rerun the affected reviews.
- [ ] **Local merge only.** Merge into `feat/langgraph-core` locally after #269, and record the merge commit in the ledger. No push, no PR. #271 starts from that commit.

## Open questions for controller ruling

1. **Q7 confirmation (user-visible).** This plan rules a three-way rebase: clean roles reset, pending edits kept. User confirmation is recommended before Task 3. The alternatives are reset-all, which destroys saved unpublished edits, and parent-only, which primes re-publication of the rolled-back content. Changing the ruling affects only `_draft_effect`/the reset loop and their tests.
2. **Rolling back to a release whose mapping equals the active one.** The plan refuses it with `409 rollback_matches_active`, and also refuses the active release itself. Confirm that a no-op release should not be creatable.
3. **Evidence when the source was itself a rollback.** The plan links every run linked to the selected source, whatever its kind, with `source_release_id = the selected source` (Review Focus 1). The design's "its source release" could instead mean the release that originally approved the run. Confirm.
4. **v1's `changed_agents`.** The plan lists all seven roles, since every definition was introduced. The alternative is an empty list with an `initial` flag. Confirm.
5. **Forbidden-name sweep on #269's page.** The plan assumes the sweep covers only the workbench panel. If #269's page gains its own sweep, the parametrized names `Roll back to Graph Version N` and `Inspect Graph Version N` cannot be exempted by exact whole name. A policy ruling is then needed before Task 7, for example a page-specific allowed pattern owned by the release page's own guard.
6. **Stale token.** Rollback uses the draft `lock_version`, as publication does, so an unrelated draft save between preview and confirm makes the rollback `409 stale_rollback`. For an emergency path, should the token instead be the active release id alone? That would change the draft-save ordering expectations in Task 4.
7. **Log content.** The plan logs only the outcome code and role key names; no version numbers or ids. Confirm that version numbers must also stay out of logs.
8. **Route module.** If #269 lands a second router despite the one-router rule, #270 follows #269's module and still leaves `main.py` untouched. Confirm, or route the fix to #269.
9. **Structural validation scope.** The plan runs the two local validator tuples, covering protected bundle and schema contract resolvability plus assembly and overlay validity, over all seven historical roles. It does **not** run the remote endpoint check, since rollback does no network work. A historical endpoint that has since been removed therefore rolls back successfully and fails at pinned invocation, per spec §15. Confirm.
