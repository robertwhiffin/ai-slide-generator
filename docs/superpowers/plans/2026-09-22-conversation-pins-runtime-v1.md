# Conversation Pins and Persisted Graph V1 Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every new browser/API root conversation an immutable pin to the active Graph Release, migrate existing graph conversations to Graph Version 1, and execute every model-driven Graph Node from that exact persisted release with auditable trace and UI identity.

**Architecture:** A conversation-pin module owns the schema/backfill, active-release row lock, immutable session pin, and safe presentation status behind narrow interfaces. A persisted-release loader validates and caches a complete seven-role immutable snapshot by exact release ID; `AgentRuntime` resolves only through that loader, evaluates the stored V1 assembly, resolves exact protected contracts, and traces the resolved identity through an injected port. The graph loads the session pin once per turn and propagates it through state, both `Send` fan-outs, and every retry, while the monolith and deterministic Foreman remain unchanged.

**Tech Stack:** Python 3.11, SQLAlchemy 2, PostgreSQL 15/Lakebase, FastAPI, Pydantic v2, LangGraph, MLflow tracing, React 19, TypeScript, Vitest, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` (GitHub issues #258 and #261)

## Global Constraints

- Work from reviewed #260 head `7897cbc0190155ba70c80945047c6be5b99a1481`; before Task 1, re-probe every path and interface below and record corrections in ignored `.superpowers/issue-261-plan-corrections.md`.
- The exact model-driven role set is `architect`, `data_analyst`, `builder`, `build_reviewer`, `fixer`, `fix_reviewer`, and `deck_reviewer`; every loaded release must contain each role exactly once before any one role is returned or cached.
- Foreman remains deterministic and never calls `AgentRuntime`; the legacy monolith, MCP execution, exports, feedback, judge, contributor creation, duplicate creation, and mixed-version collaboration UI do not change in #261.
- Graph Version is `graph_release.version_number`; it is the user-facing ordinal and is never confused with the internal `graph_release.id` Conversation Pin.
- `user_sessions.graph_release_id` is nullable for upgraded legacy rows and references `graph_release.id` with `ON DELETE RESTRICT`; a null pin means explicit legacy/no-graph state and never means “use active”.
- Existing graph-capable rows backfill to Graph Version 1 only after Graph Version 1 exists. Legacy rows retain null. The backfill is idempotent and never rewrites any non-null pin.
- New explicit-root and browser chat-auto-created sessions select, lock, verify, and write the active release in the same transaction. Existing session IDs are returned without mutating their pin.
- Production persisted execution has no manifest, compatibility source, active/latest release, or model-default fallback. Missing Lakebase, release, mapping, revision, protected bundle, schema contract, or endpoint fails explicitly.
- Release caches are keyed only by exact immutable release ID and are populated only after the complete release and all seven revision hashes/contracts validate.
- The Conversation Pin enters `GraphState` from the database, cannot be supplied through `initial`, survives both `Send` fan-outs and safety retries, and is passed separately from model payload so internal IDs do not enter authored prompts.
- Traces carry exact integer `graph_version`, integer `graph_release_id`, string `agent_key`, integer `agent_definition_revision_id`, and lowercase SHA-256 `content_hash` through an injected tracing port.
- Conversation responses expose only `graph_version`, `active_graph_version`, and `is_older_than_active`; they do not expose release IDs, revision IDs, hashes, prompts, endpoint settings, schema, or assembly configuration.
- “Start new conversation with latest” calls the normal pinned root-creation interface, switches only after it succeeds, and never updates or patches the old conversation.
- PostgreSQL—not SQLite—is the authority for foreign-key retention, partial active-release uniqueness, and row-lock concurrency. Concurrency tests force and observe both lock orders from a third connection.
- The Python environment uses shared pyenv site-packages. Never install packages and never create a virtual environment. The Apps BUILD dependency file is `packages/databricks-tellr-app/pyproject.toml`.
- Every new Playwright spec is added to the explicit matrix in `.github/workflows/test.yml`; automated graph tests replace only external model behavior with deterministic adapters.
- The accepted starting baseline at `7897cbc01` is 220 focused migration/bootstrap/runtime/graph/chat tests passing. After schema, ORM, or runtime-interface changes, re-run the focused set and compare failure causes and skipped test identities, not only counts.

## Rulings from the current-code probe

1. **Creation capability before message one.** `CreateSessionRequest` has only `session_id` and `title`; `ChatRequest` has message/config but no engine selection; `AgentConfig` describes tools/style/template/deck settings; and the browser pre-creates a session without a message. The sole current engine selector is the root owner’s earliest user message containing exact phrase `USE AGENT MODE`. Therefore #261 treats the explicit browser/API root endpoint and both browser chat auto-create limbs as graph-capable and pins them eagerly, while transcript selection continues to decide graph versus monolith execution. Pinning does not route a plain-message conversation onto the graph. Lower-level callers such as MCP, tour fixtures, and direct monolith helpers retain `graph_capable=False` unless their owning route opts in.
2. **Existing contributors.** Backfill classification follows `resolve_engine_mode`: use the root owner (`COALESCE(parent_session_id, id)`) and its earliest `role='user'` message ordered by `(created_at, id)`. Thus an existing contributor whose root resolves graph-capable receives the same V1 pin during migration. New contributor and duplicate creation remain untouched and nullable for #262.
3. **Startup ordering.** `_run_migrations()` owns only the additive existing-schema column/FK/index. `init_database()` keeps the order `init_db()` → `bootstrap_graph_configuration()` → `backfill_conversation_pins()` before all workers and before later backfills/seeds.
4. **Null and missing behavior.** A graph turn on a null pin raises `ConversationPinMissingError`. An absent exact release raises `GraphReleaseNotFoundError`. Neither condition consults the active release.
5. **Safe response shape.** Routes and UI receive the three version presentation fields only. Internal release identity remains in persistence, graph state, runtime diagnostics, and traces.
6. **Tracing seam.** `AgentRuntime` wraps the exact resolved model invocation with `AgentInvocationTracePort.invoke(identity, callback)`. Tests inject a recorder; the production adapter creates an MLflow span and sets the five required attributes before calling the model.

## Planned file map and ownership

| File | Responsibility | Task ownership |
|---|---|---|
| `src/domain/conversation_engine.py` | Exact transcript marker and pure graph-selection predicate shared by route classification and migration | Task 1 |
| `src/database/models/session.py` | Nullable restrictive Conversation Pin ORM column/relationship | Task 1 |
| `src/core/database.py` | Existing-schema additive pin column, FK, and index | Task 1 |
| `src/services/conversation_pins.py` | V1 backfill, active-release lock/retry, pin load, and safe status deep module | Tasks 1, 2, then 7 sequentially |
| `packages/databricks-tellr-app/databricks_tellr_app/run.py` | Bootstrap-before-backfill pre-fork startup order | Task 1 |
| `src/api/services/session_manager.py` | Transactional root creation and response serialization | Tasks 2 then 7 sequentially |
| `src/api/routes/sessions.py`, `src/api/routes/chat.py` | Opt-in graph-capable root creation and explicit failure mapping | Task 2 |
| `src/services/persisted_graph_release.py` | Exact-ID seven-revision loader and immutable cache | Task 3 |
| `src/services/agent_runtime_tracing.py` | Trace identity/port and MLflow adapter | Task 4 |
| `src/services/agent_runtime.py` | Persisted-only production definition resolution, stored V1 assembly, exact contracts, model invocation | Task 4 |
| `src/services/graph/state.py`, `builder.py`, `nodes.py`, `routers.py` | Pin entry, state/fan-out/retry propagation, all seven model-driven calls | Task 5 |
| `frontend/src/contexts/SessionContext.tsx` | Current conversation version status | Task 8 |
| `frontend/src/components/Conversation/GraphVersionStatus.tsx` | Badge, older state, and explicit start-latest control | Task 8 |
| `frontend/src/components/Layout/AppLayout.tsx` | Mount status and create/switch behavior | Task 8 |
| `.github/workflows/test.yml` | CI collection for the new Playwright spec | Task 8 |
| `tests/integration/test_graph_mode_turn.py` | Shipped graph-mode failure posture, then exact pin→release→revision acceptance seam | Tasks 6 then 9 sequentially |

---

### Task 1: Add the nullable Conversation Pin and bootstrap-ordered V1 backfill

**Files:**
- Create: `src/domain/conversation_engine.py`
- Create: `src/services/conversation_pins.py`
- Create: `tests/integration/test_conversation_pin_migration_postgres.py`
- Modify: `src/database/models/session.py:86-199`
- Modify: `src/core/database.py:417-617`
- Modify: `src/api/services/chat_service.py:118-209`
- Modify: `packages/databricks-tellr-app/databricks_tellr_app/run.py:43-93`
- Modify: `tests/unit/test_database_migrations.py`
- Modify: `tests/unit/test_startup_migrations.py:26-119`
- Modify: `tests/unit/test_encryption.py:225-305`

**Interfaces:**
- Produces: `selects_graph_engine(content: str | None) -> bool` using exact case-sensitive phrase `USE AGENT MODE`.
- Produces: `BackfillResult(graph_release_id: int, graph_version: int, pinned_count: int)` and `backfill_conversation_pins(session_factory: sessionmaker) -> BackfillResult`.
- Preserves: `resolve_engine_mode(session_id: Optional[str]) -> str` and `_selects_agent_mode(content)` behavior byte-for-byte by delegating to the pure predicate.
- Produces for Tasks 2/5/7: nullable `UserSession.graph_release_id: int | None` with relationship `graph_release` and named FK `fk_user_sessions_graph_release` using `ON DELETE RESTRICT`.

- [ ] **Step 1: Write real-PostgreSQL RED tests for existing-schema upgrade, classification, identity, idempotence, and retention**

Create an old `user_sessions` table without `graph_release_id`, run `_run_migrations()`, bootstrap V1, then call the backfill. Seed these exact cases before the upgrade:

```python
cases = {
    "root_graph": [user("USE AGENT MODE make a deck")],
    "root_graph_tie": [
        user("USE AGENT MODE first", created_at=tied_time, id=10),
        user("plain second", created_at=tied_time, id=11),
    ],
    "root_legacy": [user("plain first"), user("USE AGENT MODE later")],
    "root_empty": [],
    "contributor_of_graph": contributor(parent="root_graph"),
    "contributor_of_legacy": contributor(parent="root_legacy"),
    "already_pinned": pinned_to(release_id=historical_release_id),
}
```

Assert exact identities, not only a count:

```python
assert pins == {
    "root_graph": v1_id,
    "root_graph_tie": v1_id,
    "root_legacy": None,
    "root_empty": None,
    "contributor_of_graph": v1_id,
    "contributor_of_legacy": None,
    "already_pinned": historical_release_id,
}
assert second_run == BackfillResult(v1_id, 1, 0)
assert pins_after_second_run == pins
```

Inspect `pg_constraint.confdeltype == 'r'`, the nullable catalog column, and index `ix_user_sessions_graph_release_id`. Attempting to delete a release referenced by a session must be rejected; also assert changing the ORM/migration FK to `CASCADE` makes the catalog assertion red, so the immutable release trigger is not the only reason the test passes.

- [ ] **Step 2: Write startup-order RED tests**

Extend `test_init_database_runs_profile_and_session_migrations` so the exact prefix is:

```python
assert calls[:3] == [
    ("init_db", None),
    ("bootstrap_graph_configuration", "SESSION_FACTORY"),
    ("backfill_conversation_pins", "SESSION_FACTORY"),
]
```

Add failure cases proving bootstrap failure never calls backfill and backfill failure exits with code 1 before profile/session/slide/default migrations. Update every `init_database()` test stub to provide the new backfill symbol; do not weaken their existing full-order assertions.

- [ ] **Step 3: Run RED commands**

```bash
uv run --no-sync pytest -q -m postgres tests/integration/test_conversation_pin_migration_postgres.py
uv run --no-sync pytest -q tests/unit/test_database_migrations.py tests/unit/test_startup_migrations.py tests/unit/test_encryption.py
```

Expected: missing column/module/backfill assertions fail. If PostgreSQL is unreachable, stop; a skip is not evidence for this task.

- [ ] **Step 4: Implement schema migration and deterministic backfill**

Add the ORM field:

```python
graph_release_id = Column(
    Integer,
    ForeignKey(
        "graph_release.id",
        name="fk_user_sessions_graph_release",
        ondelete="RESTRICT",
    ),
    nullable=True,
    index=True,
)
graph_release = relationship("GraphRelease", foreign_keys=[graph_release_id])
```

Append `_migrate_conversation_pin_schema(conn, inspector, schema, _qual, is_sqlite)` before graph mutation guards and owner reassignment. PostgreSQL adds the nullable integer column, named restrictive FK, and index idempotently using catalog/inspector checks. SQLite adds the nullable column and index for local compatibility; fresh SQLite schemas receive the ORM FK from `create_all()`, while the real existing-schema FK proof remains PostgreSQL.

In `conversation_engine.py` define:

```python
AGENT_MODE_PHRASE = "USE AGENT MODE"

def selects_graph_engine(content: str | None) -> bool:
    return bool(content) and AGENT_MODE_PHRASE in content
```

In `backfill_conversation_pins`, open one transaction, require the unique release whose `version_number == 1`, calculate each root owner’s first user row by `row_number() over (partition by session_id order by created_at, id)`, select root and contributor session IDs whose owner’s row 1 matches the predicate, and update only rows where `graph_release_id IS NULL`. Do not load the manifest and do not select the active/latest release.

- [ ] **Step 5: Wire the pre-fork order**

Immediately after successful `bootstrap_graph_configuration()` in `init_database()` call:

```python
from src.services.conversation_pins import backfill_conversation_pins

pin_result = backfill_conversation_pins(get_session_local())
logger.info(
    "Conversation Pin backfill ready: release_id=%s version=%s pinned=%s",
    pin_result.graph_release_id,
    pin_result.graph_version,
    pin_result.pinned_count,
)
```

Any error exits startup with code 1. Keep it pre-fork and before profile/session agent-config backfills.

- [ ] **Step 6: Verify GREEN and falsify all load-bearing guards**

Run both Step 3 commands. Then independently sabotage: reverse `(created_at, id)` ordering; omit the contributor owner hop; remove the `IS NULL` update guard; move startup backfill before bootstrap; change `RESTRICT` to `CASCADE`. Confirm the relevant test fails for each mutation, restore, and re-run green.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/domain/conversation_engine.py src/services/conversation_pins.py src/database/models/session.py src/core/database.py src/api/services/chat_service.py packages/databricks-tellr-app/databricks_tellr_app/run.py tests/integration/test_conversation_pin_migration_postgres.py tests/unit/test_database_migrations.py tests/unit/test_startup_migrations.py tests/unit/test_encryption.py
git commit -m "feat: migrate graph conversation pins (#261)"
```

### Task 2: Linearize explicit-root and chat auto-creation with publication

**Files:**
- Create: `tests/unit/test_conversation_pin_creation.py`
- Create: `tests/integration/test_conversation_pin_creation_postgres.py`
- Modify: `src/services/conversation_pins.py`
- Modify: `src/api/services/session_manager.py:689-762`
- Modify: `src/api/routes/sessions.py:73-113`
- Modify: `src/api/routes/chat.py:168-299`
- Modify: `tests/unit/test_chat_session_creation.py`

**Interfaces:**
- Consumes: nullable `UserSession.graph_release_id` from Task 1.
- Produces: `PinnedRelease(release_id: int, graph_version: int)`.
- Produces: `ActiveGraphReleaseUnavailableError`, `ConversationPinMissingError`, and `lock_active_graph_release(db: Session, *, attempts: int = 3) -> PinnedRelease`.
- Changes: `SessionManager.create_session(self, user_id=None, title=None, session_id=None, created_by=None, agent_config=None, *, graph_capable: bool = False) -> Dict[str, Any]`.
- Route policy: `POST /api/sessions` and both new-session limbs of `_maybe_create_session()` pass `graph_capable=True`; MCP/tour/direct monolith callers retain the default `False`.

- [ ] **Step 1: Write behavior-level creation RED tests**

Cover all creation shapes:

```python
@pytest.mark.parametrize("session_id,agent_config", [
    (None, None),
    (None, {}),
    ("client-id", None),
    ("client-id", {}),
    ("client-id", {"tools": []}),
])
def test_browser_chat_auto_creation_pins_active_release(
    session_id, agent_config, session_manager, session_factory, active_release
):
    request = ChatRequest(
        session_id=session_id,
        message="plain browser message",
        agent_config=agent_config,
    )
    assert _maybe_create_session(request, session_manager) is True
    with session_factory() as db:
        row = db.scalar(
            select(UserSession).where(UserSession.session_id == request.session_id)
        )
        assert row is not None
        assert row.graph_release_id == active_release.id
```

Assert the explicit root route and each missing-ID/client-generated-missing-ID chat limb return/create the exact active release ID. Assert an existing ID is returned without modifying an existing non-null pin or upgrading a legacy null. Assert no active release rolls back the new row and returns a stable 503 detail from the explicit route. Assert `get_or_create_contributor_session()` and `duplicate_session()` still create null pins, documenting #262 ownership without changing those methods.

- [ ] **Step 2: Write forced PostgreSQL lock-order RED tests**

Use two worker connections plus the existing third-connection waiter observer. A test-only publisher must lock the active row `FOR UPDATE`, close it, insert a structurally complete cloned release/version, and copy all seven mappings in one transaction.

Force both exact schedules:

1. Creation locks R1; publisher is observed waiting; creation flushes and commits pin R1; publisher closes R1 and commits R2.
2. Publisher locks and commits R2 first while creation is observed waiting on R1; creation re-queries after seeing R1 closed and commits pin R2.

Assert the waiter PID is truly lock-waiting, exact release IDs/versions/intervals, exactly one new session, and no stale pin after the publication linearization point.

- [ ] **Step 3: Run RED commands**

```bash
uv run --no-sync pytest -q tests/unit/test_conversation_pin_creation.py tests/unit/test_chat_session_creation.py
uv run --no-sync pytest -q -m postgres tests/integration/test_conversation_pin_creation_postgres.py
```

Expected: creation rows have null pins, client-ID/no-config auto-create misses the manager path, and concurrency assertions fail.

- [ ] **Step 4: Implement the active-release lock/retry and one-transaction insert**

Use a new statement snapshot on every attempt:

```python
def lock_active_graph_release(db: Session, *, attempts: int = 3) -> PinnedRelease:
    for _ in range(attempts):
        candidate_id = db.scalar(
            select(GraphRelease.id).where(GraphRelease.effective_to.is_(None))
        )
        if candidate_id is None:
            continue
        release = db.scalar(
            select(GraphRelease)
            .where(GraphRelease.id == candidate_id)
            .with_for_update()
        )
        if release is not None and release.effective_to is None:
            return PinnedRelease(release.id, release.version_number)
    raise ActiveGraphReleaseUnavailableError("No active Graph Release is available")
```

Inside the existing `get_db_session()` transaction, return an existing session before locking. For a new `graph_capable=True` row, lock first, assign `graph_release_id=pin.release_id`, add, and flush. Return `graph_version` from the same locked row. A flush or lock failure rolls back both selection and insert through the context manager.

- [ ] **Step 5: Make browser/API ownership explicit**

The sessions route passes `graph_capable=True` and maps only `ActiveGraphReleaseUnavailableError` to HTTP 503. Refactor `_maybe_create_session` so existence is checked whether or not `agent_config` was supplied; both new-session branches call `create_session(graph_capable=True)` alongside their existing named arguments. Existing-session agent-config synchronization remains behaviorally unchanged. Do not infer capability from `agent_config` or the message phrase.

- [ ] **Step 6: Verify GREEN and sabotage both lock orders**

Run Step 3. Temporarily move active selection outside `get_db_session()`, remove `with_for_update()`, remove the post-lock `effective_to` check, and stop retrying after a closed candidate. Each mutation must make at least one forced-order test fail while the observer still proves overlap. Restore and re-run green.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/services/conversation_pins.py src/api/services/session_manager.py src/api/routes/sessions.py src/api/routes/chat.py tests/unit/test_conversation_pin_creation.py tests/unit/test_chat_session_creation.py tests/integration/test_conversation_pin_creation_postgres.py
git commit -m "feat: pin graph roots at release lock (#261)"
```

### Task 3: Load and cache complete immutable releases by exact ID

**Files:**
- Create: `src/services/persisted_graph_release.py`
- Create: `tests/unit/test_persisted_graph_release.py`
- Modify: `src/services/graph_configuration.py:1-54` (exports only)

**Interfaces:**
- Consumes: `GraphRelease`, `GraphReleaseAgent`, `AgentDefinitionRevision`, `validate_definition_hash()`, `definition_content_from_row()`, and `GRAPH_V1_AGENT_KEYS`.
- Produces: `ResolvedDefinition(graph_release_id: int, graph_version: int, revision_id: int, content_hash: str, content: DefinitionContent)`.
- Produces: `ResolvedGraphRelease(release_id: int, graph_version: int, definitions: Mapping[AgentKey, ResolvedDefinition])` with immutable mapping.
- Produces: `PersistedGraphReleaseLoader.load(release_id: int) -> ResolvedGraphRelease` and `.resolve(release_id: int, agent_key: str) -> ResolvedDefinition`.
- Produces errors: `GraphReleaseNotFoundError`, `GraphReleaseIncompleteError`, and existing `GraphConfigurationIntegrityError` for invalid content/hash.

- [ ] **Step 1: Write exact-loader RED tests**

Tests seed two releases with distinct IDs and role prompts. Assert requesting closed R1 returns R1, never active R2. Assert exactly one joined database read on first R1 load, zero reads on repeated roles/R1 loads, and an independent read for R2. Assert no error is cached by repairing an initially incomplete release and successfully loading it on the next call.

For each corruption, assert no partial snapshot enters the cache: missing one key with total six, duplicate/wrong key, incompatible revision role, missing revision, malformed persisted `DefinitionContent`, and content-hash mismatch. Test absence by exact ID even when another active release exists.

- [ ] **Step 2: Run RED**

```bash
uv run --no-sync pytest -q tests/unit/test_persisted_graph_release.py
```

Expected: import failure for `persisted_graph_release`.

- [ ] **Step 3: Implement the immutable complete-release loader**

Use one joined query constrained only by `GraphRelease.id == release_id`; do not include `effective_to IS NULL`:

```python
rows = session.execute(
    select(GraphRelease, GraphReleaseAgent, AgentDefinitionRevision)
    .join(GraphReleaseAgent, GraphReleaseAgent.graph_release_id == GraphRelease.id)
    .join(
        AgentDefinitionRevision,
        AgentDefinitionRevision.id == GraphReleaseAgent.agent_definition_revision_id,
    )
    .where(GraphRelease.id == release_id)
).all()
```

Require the exact seven-key set and seven rows; validate mapping key equals revision/content key and recompute every hash using `validate_definition_hash`. Build all seven `ResolvedDefinition` values first, then publish a `MappingProxyType` snapshot into a lock-protected `dict[int, ResolvedGraphRelease]`. Unknown `agent_key` fails before database access. Do not import the v1 manifest or `CodeOwnedAgentDefinitionSource`.

- [ ] **Step 4: Verify GREEN and falsify cache/full-validation behavior**

Run Step 2. Sabotage by validating only the requested role, keying the cache by `(release_id, agent_key)`, replacing the exact-ID predicate with active release, and skipping hash recomputation. Confirm the matching test fails, restore, and re-run green.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/services/persisted_graph_release.py src/services/graph_configuration.py tests/unit/test_persisted_graph_release.py
git commit -m "feat: load exact persisted graph releases (#261)"
```

### Task 4: Cut AgentRuntime to persisted definitions and inject exact trace identity

**Files:**
- Create: `src/services/agent_runtime_tracing.py`
- Create: `tests/unit/test_persisted_agent_runtime.py`
- Modify: `src/services/agent_runtime.py:60-516`
- Modify: `tests/unit/test_agent_runtime.py`
- Modify: `tests/unit/test_agent_resolution_prompt.py`
- Modify: `tests/unit/test_graph_definition_manifest.py`
- Modify: `tests/unit/test_deck_level_spec_change.py`

**Interfaces:**
- Consumes: `PersistedGraphReleaseLoader.resolve(release_id, agent_key) -> ResolvedDefinition`.
- Produces: `AgentRuntime.run(agent_key: str, graph_release_id: int, payload: dict[str, Any], assembly_context: AgentAssemblyContext) -> AgentInvocationResult`.
- Produces: `AgentInvocationIdentity(graph_version: int, graph_release_id: int, agent_key: str, agent_definition_revision_id: int, content_hash: str)`.
- Produces: `AgentInvocationTracePort.invoke(identity: AgentInvocationIdentity, call: Callable[[], BaseModel]) -> BaseModel` with adapters `MlflowAgentInvocationTracePort` and `RecordingAgentInvocationTracePort` used only in tests.
- Changes diagnostics to include `graph_version`, `graph_release_id`, `agent_definition_revision_id`, and `content_hash` in addition to existing model/contract/latency fields.
- Production factory: `get_agent_runtime() -> AgentRuntime` constructs a persisted loader from `get_session_local()` and never calls `AgentRuntime.compatibility()`.

- [ ] **Step 1: Write persisted-runtime and trace RED tests**

Inject a fake loader with two releases whose Architect prompts/endpoints differ. Assert exact release ID selects exact content, trace identity matches the resolved row, the trace callback encloses the model invocation, and diagnostics match trace fields. Assert loader/Lakebase/release errors propagate without model or trace invocation.

Assert strict identity failures for unavailable protected assembly `(version, digest)` and incompatible role-specific schema contract. Assert stored assembly rules determine order/conditions and an unknown/malformed block fails explicitly. V1’s empty overlay is accepted; any non-empty overlay fails with an explicit unsupported-overlay error owned by the future overlay ticket rather than being silently ignored.

Assert `get_agent_runtime()` uses `PersistedGraphReleaseLoader`. Monkeypatch `CodeOwnedAgentDefinitionSource.resolve`, manifest loading, `DEFAULT_CONFIG`, and an active-release query to raise if touched; a persisted run must still succeed.

- [ ] **Step 2: Run RED**

```bash
uv run --no-sync pytest -q tests/unit/test_persisted_agent_runtime.py tests/unit/test_agent_runtime.py tests/unit/test_agent_resolution_prompt.py tests/unit/test_graph_definition_manifest.py tests/unit/test_deck_level_spec_change.py
```

Expected: new `run` signature/identity/trace tests fail.

- [ ] **Step 3: Implement stored V1 definition conversion and assembly**

Convert `ResolvedDefinition.content` to `AgentModelConfiguration`, `ProtectedPromptIdentity`, and role-specific `SchemaContractIdentity`. Evaluate `content.assembly_rules.blocks` in stored order: authored prompt, condition-matching exact protected block, JSON payload with the stored literal indent/default, and terminal structured-output binding validation. Require the terminal binding exactly once and last. The model-facing payload never contains `graph_release_id`.

Keep `_ProtectedPromptBundleRegistry` and `_SchemaContractRegistry` exact `(version, digest)` registries. They may contain V1 only in #261, but they must be keyed registries rather than “current” substitution. Do not fall back from an unknown identity.

- [ ] **Step 4: Implement trace-port wrapping and production construction**

The load/contract/assembly sequence creates:

```python
identity = AgentInvocationIdentity(
    graph_version=resolved.graph_version,
    graph_release_id=resolved.graph_release_id,
    agent_key=agent_key,
    agent_definition_revision_id=resolved.revision_id,
    content_hash=resolved.content_hash,
)
output = self._trace_port.invoke(
    identity,
    lambda: self._model_adapter.invoke(
        configuration=configuration,
        schema=schema,
        prompt=prompt,
    ),
)
```

The MLflow adapter starts span `graph_agent_invocation` and sets attributes named exactly `graph_version`, `graph_release_id`, `agent_key`, `agent_definition_revision_id`, and `content_hash` before calling the model. It records status/error without swallowing the model exception.

Retain `CodeOwnedAgentDefinitionSource` only for v1 generator/parity tests. It is not accepted by the production runtime factory and is never an exception fallback.

- [ ] **Step 5: Verify GREEN and sabotage identity/fallback protections**

Run Step 2. Separately remove `content_hash` from trace identity, change loader resolution to active release, substitute the current protected bundle for an unknown identity, and bypass stored assembly ordering. Confirm the focused test fails for each, restore, and re-run green.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/services/agent_runtime.py src/services/agent_runtime_tracing.py tests/unit/test_persisted_agent_runtime.py tests/unit/test_agent_runtime.py tests/unit/test_agent_resolution_prompt.py tests/unit/test_graph_definition_manifest.py tests/unit/test_deck_level_spec_change.py
git commit -m "feat: execute persisted graph definitions (#261)"
```

### Task 5: Propagate the immutable pin through GraphState, fan-out, retries, and all seven roles

**Files:**
- Modify: `src/services/graph/state.py:157-296`
- Modify: `src/services/graph/builder.py:187-282`
- Modify: `src/services/graph/nodes.py:451-634,1186-1261,1269-2800`
- Modify: `src/services/graph/routers.py:120-193`
- Modify: `tests/unit/test_graph_builder.py`
- Modify: `tests/unit/test_graph_routers.py`
- Modify: `tests/unit/test_graph_nodes.py`
- Modify: `tests/unit/test_graph_state.py`

**Interfaces:**
- Consumes: `load_conversation_pin(session_id: str) -> int` from `conversation_pins`; it raises `ConversationPinMissingError` for absent/null session pins.
- Adds: required runtime state key `graph_release_id: int` to `GraphState`.
- Changes: `rereview_committed_slides(session_id: str, graph_release_id: int, spec: DeckSpec, brand: Dict[str, Any]) -> Dict[str, Any]`.
- Consumes: Task 4 `AgentRuntime.run(agent_key, graph_release_id, payload, assembly_context)`.
- Preserves: `invoke_graph(session_id: str, initial: Optional[Dict[str, Any]] = None, *, emitter: Any = None, principal: Optional[str] = None, describe_only: bool = False, request_id: Optional[str] = None) -> Dict[str, Any]`, deterministic `foreman_node`, and graph routing topology.

- [ ] **Step 1: Write state-entry and fan-out RED tests**

Assert `invoke_graph` loads exactly one persisted pin before graph invocation, overwrites a hostile `initial={"graph_release_id": other_id}`, and fails before `get_graph().invoke` for a null/missing pin. Capture the first `Send("builder", payload)` and the second `Send("build_reviewer", payload)` and assert both contain the same integer pin.

Prove the second assertion is non-vacuous by checking the builder result record and refan payload independently; do not construct the expected payload with `build_branch_payload()`.

- [ ] **Step 2: Write all-call-path and retry RED tests**

Inject one recording runtime and exercise these exact call sites:

- Architect, including its `rereview_committed_slides` Build Reviewer calls.
- Data Analyst.
- Builder initial call and safety-gate retry.
- Build Reviewer fan-out.
- Fixer initial call and safety-gate retry.
- Fix Reviewer.
- Deck Reviewer.

Every record must equal the state/branch pin. Force both retries with unsafe first HTML and safe second HTML. Assert `foreman_node` records no runtime call. Add a monolith dispatch regression assertion outside graph invocation so the changed runtime signature cannot leak into `ChatService`’s legacy branch.

- [ ] **Step 3: Run RED**

```bash
uv run --no-sync pytest -q tests/unit/test_graph_builder.py tests/unit/test_graph_routers.py tests/unit/test_graph_nodes.py tests/unit/test_graph_state.py
```

Expected: the pin is absent and existing runtime calls use the old signature.

- [ ] **Step 4: Seed immutable state and copy it across both fan-outs**

In `invoke_graph`, load the pin before creating state, then assign it after `dict(initial or {})` so caller input cannot override it. Add it to structured logging. In `build_branch_payload`, copy `graph_release_id`; preserve that key in the builder’s stored `record`, so `dict(record)` in `build_reviewer_refan_router` carries it without a database read.

- [ ] **Step 5: Convert every model-driven invocation**

State-reached nodes use `state["graph_release_id"]`; branch-reached nodes use `payload["graph_release_id"]`. Pass the ID as the second runtime argument at all ten existing call sites (seven roles plus rereview and two safety retries). For Builder, copy the full branch payload into the returned record but remove `graph_release_id` from the model payload before prompt assembly:

```python
graph_release_id = int(payload["graph_release_id"])
model_payload = {key: value for key, value in payload.items() if key != "graph_release_id"}
out = get_agent_runtime().run(
    "builder",
    graph_release_id,
    model_payload,
    AgentAssemblyContext(design_system_active),
).output
record = {**payload, "html": html, "scripts": out.scripts}
```

Apply the same separate-identity rule to retry/review/fix payloads. Do not add a runtime call to Foreman.

- [ ] **Step 6: Verify GREEN and falsify distinct propagation paths**

Run Step 3. Independently remove the pin from `build_branch_payload`, remove it from Builder’s returned record, let `initial` override the DB pin, and pass active release in one retry. Confirm a distinct test fails for each sabotage, restore, and re-run green.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/services/graph/state.py src/services/graph/builder.py src/services/graph/nodes.py src/services/graph/routers.py tests/unit/test_graph_builder.py tests/unit/test_graph_routers.py tests/unit/test_graph_nodes.py tests/unit/test_graph_state.py
git commit -m "feat: propagate graph release pins (#261)"
```

### Task 6: Prove explicit failures and unchanged legacy execution at route/runtime seams

**Files:**
- Create: `tests/integration/test_persisted_graph_runtime_failures_postgres.py`
- Modify: `src/api/services/chat_service.py:990-1134,1798-2008`
- Modify: `tests/integration/test_graph_mode_turn.py` only for focused failure cases that do not share Task 9 fixtures

**Interfaces:**
- Consumes: `ConversationPinMissingError`, `GraphReleaseNotFoundError`, protected-bundle/schema errors, and persisted-loader database failures.
- Preserves: `ChatService.send_message_streaming(self, session_id: str, message: str, slide_context: Optional[Dict[str, Any]] = None, request_id: Optional[str] = None, image_ids: Optional[List[str]] = None, is_first_message_override: Optional[bool] = None, engine_mode: str = "monolith") -> Generator[StreamEvent, None, None]` and `_send_message_streaming_graph(self, session_id: str, message: str, *, is_first_message: bool = False, request_id: Optional[str] = None) -> Generator[StreamEvent, None, None]`.
- Produces: graph-mode failure events/errors that name the failure class and pinned release identity where available, without selecting another release.

- [ ] **Step 1: Write RED failure-posture tests**

Against real PostgreSQL, prove separately: null pin, deleted/absent exact release ID (with FK checks deferred only inside the test transaction), incomplete release, unavailable protected assembly, incompatible schema, and database connection failure. Seed a valid newer active release in every missing-pinned-release case and assert it is never invoked.

At the shipped streaming seam, assert a graph failure produces no model call and does not rewrite deck/session pin state. Run a plain monolith turn with persisted loader and trace port poisoned; it must complete through the existing monolith path without touching either.

- [ ] **Step 2: Run RED**

```bash
uv run --no-sync pytest -q -m postgres tests/integration/test_persisted_graph_runtime_failures_postgres.py
uv run --no-sync pytest -q tests/integration/test_graph_mode_turn.py -k 'missing_pin or missing_release or monolith_ignores_persisted_runtime'
```

Expected: error typing/stream handling assertions are not yet satisfied.

- [ ] **Step 3: Keep failures explicit at the graph seam**

Allow typed persisted-runtime errors to escape `invoke_graph` into the existing graph-stream error handling with stable class names and safe messages. Do not catch and retry with `get_agent_runtime().compatibility()`, active release, manifest, or `DEFAULT_CONFIG`. Do not alter the monolith branch below the graph dispatch.

- [ ] **Step 4: Verify GREEN and sabotage fallback guards**

Run Step 2. Add a temporary active-release fallback in the loader call and confirm the missing-release test selects the wrong model and fails. Make the monolith branch instantiate persisted runtime and confirm its poison test fails. Restore and re-run green.

- [ ] **Step 5: Commit Task 6**

```bash
git add src/api/services/chat_service.py tests/integration/test_persisted_graph_runtime_failures_postgres.py tests/integration/test_graph_mode_turn.py
git commit -m "test: enforce persisted graph failure posture (#261)"
```

### Task 7: Return safe Graph Version presentation fields from session interfaces

**Files:**
- Modify: `src/services/conversation_pins.py`
- Modify: `src/api/services/session_manager.py:689-817,943-1023`
- Modify: `src/api/routes/sessions.py:73-137,372-419`
- Create: `tests/unit/test_conversation_graph_version_responses.py`
- Modify: `tests/integration/test_api_routes.py`

**Interfaces:**
- Produces: `ConversationGraphVersion(graph_version: int | None, active_graph_version: int, is_older_than_active: bool)`.
- Produces: `get_conversation_graph_version(db: Session, session: UserSession) -> ConversationGraphVersion`.
- Extends create/get/list dictionaries with `graph_version`, `active_graph_version`, and `is_older_than_active` only.
- Preserves all route authorization and deck/contributor presentation fields.

- [ ] **Step 1: Write RED response-contract and authorization tests**

Cover pinned-active, pinned-historical, and legacy-null root sessions for create/get/list. Expected fields are:

```python
active = {"graph_version": 2, "active_graph_version": 2, "is_older_than_active": False}
old = {"graph_version": 1, "active_graph_version": 2, "is_older_than_active": True}
legacy = {"graph_version": None, "active_graph_version": 2, "is_older_than_active": False}
```

Recursively assert responses contain none of `graph_release_id`, `revision_id`, `content_hash`, `prompt_text`, `endpoint_name`, `schema_overlay`, or `assembly_rules`. Assert existing 401/403 behavior is unchanged.

- [ ] **Step 2: Run RED**

```bash
uv run --no-sync pytest -q tests/unit/test_conversation_graph_version_responses.py tests/integration/test_api_routes.py -k 'graph_version or create_session or get_session or list_sessions'
```

Expected: version fields are absent.

- [ ] **Step 3: Implement one safe presentation helper and use it everywhere**

Resolve pinned version by exact FK ID and active version by `effective_to IS NULL`. Missing referenced release or missing/multiple active releases raises a graph-configuration integrity error; it never fabricates a version. For list responses, use one active-version read plus an outer join/alias for pinned release to avoid N+1 queries. The create response uses the `PinnedRelease` already held by Task 2.

- [ ] **Step 4: Verify GREEN and sabotage safe/old-state calculations**

Run Step 2. Temporarily compare release IDs instead of `version_number`, expose `graph_release_id`, and treat null as active. Confirm the corresponding tests fail, restore, and re-run green.

- [ ] **Step 5: Commit Task 7**

```bash
git add src/services/conversation_pins.py src/api/services/session_manager.py src/api/routes/sessions.py tests/unit/test_conversation_graph_version_responses.py tests/integration/test_api_routes.py
git commit -m "feat: expose safe conversation graph versions (#261)"
```

### Task 8: Add the Graph Version badge and explicit start-latest UX

**Files:**
- Create: `frontend/src/components/Conversation/GraphVersionStatus.tsx`
- Create: `frontend/src/components/Conversation/GraphVersionStatus.test.tsx`
- Create: `frontend/tests/e2e/conversation-graph-version.spec.ts`
- Modify: `frontend/src/services/api.ts:101-125,383-407`
- Modify: `frontend/src/contexts/SessionContext.tsx:9-145`
- Modify: `frontend/src/components/Layout/AppLayout.tsx:180-193,440-500,573-587,741-762,1033-1055`
- Modify: `.github/workflows/test.yml:691-765`

**Interfaces:**
- Extends TypeScript `Session` and `OptionalSessionInfo` with `graph_version: number | null`, `active_graph_version: number`, `is_older_than_active: boolean`.
- Extends `SessionContextType` with immutable current `graphVersion`, `activeGraphVersion`, and `isGraphVersionOlder` state, reset on local new session and atomically set on switch/create.
- Produces component props `graphVersion`, `activeGraphVersion`, `isOlder`, `onStartLatest`, and `isStartingLatest`.

- [ ] **Step 1: Write component RED tests**

Assert an active pin renders `Graph Version 2` and no action. An old pin renders `Graph Version 1`, `Older than active Graph Version 2`, and a button with exact accessible name `Start new conversation with latest`. A null legacy state renders no misleading badge/action. Double-click while pending makes exactly one callback.

- [ ] **Step 2: Write Playwright RED flow**

Mock session A as version 1/active 2. Assert the badge and old-state action. On click, intercept exactly one `POST /api/sessions`, return new session B version 2, assert navigation/current session switches to B, and assert no `PATCH`/`PUT`/`DELETE` request targets A. Make creation return 503 in a second case and assert A remains current with its version/action intact.

- [ ] **Step 3: Run RED**

```bash
cd frontend && npm test -- --run src/components/Conversation/GraphVersionStatus.test.tsx
cd frontend && npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1
```

Expected: component/spec and fields do not exist.

- [ ] **Step 4: Implement typed state, badge, and create-then-switch**

Mount `GraphVersionStatus` in the active conversation header subtitle/adjacent slot. Implement the action in `AppLayout` as:

```typescript
const created = await api.createSession();
const restored = await switchSession(created.session_id, created);
setSlideDeck(restored.slideDeck);
setRawHtml(restored.rawHtml);
navigate(`/sessions/${created.session_id}/edit`);
```

Do not call `createNewSession()` before the request succeeds; that would abandon the old conversation on a 503. Do not reuse duplicate-session behavior. Add `conversation-graph-version` to the workflow matrix.

- [ ] **Step 5: Verify GREEN, typecheck, and sabotage immutability**

```bash
cd frontend && npm test -- --run src/components/Conversation/GraphVersionStatus.test.tsx
cd frontend && npx tsc --noEmit
cd frontend && npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1
uv run --no-sync pytest -q tests/unit/test_e2e_matrix_covers_specs.py
```

Temporarily implement the action as a patch to A and confirm the request guard fails. Switch local session before the POST and confirm the 503 case fails. Remove the older comparison and confirm the component test fails. Restore and re-run green.

- [ ] **Step 6: Commit Task 8**

```bash
git add frontend/src/components/Conversation/GraphVersionStatus.tsx frontend/src/components/Conversation/GraphVersionStatus.test.tsx frontend/tests/e2e/conversation-graph-version.spec.ts frontend/src/services/api.ts frontend/src/contexts/SessionContext.tsx frontend/src/components/Layout/AppLayout.tsx .github/workflows/test.yml
git commit -m "feat: show and upgrade conversation graph version (#261)"
```

### Task 9: Prove the shipped graph-mode path, trace identity, and full regression gate

**Files:**
- Modify: `tests/integration/test_graph_mode_turn.py`
- Create: `tests/integration/test_conversation_pin_acceptance_postgres.py`
- Modify: `tests/unit/test_rc_graph_ci.py` only if its shipped graph collection list is explicit

**Interfaces:**
- Consumes the public root route, shipped `ChatService.send_message_streaming(session_id, message, engine_mode="graph")`, real compiled graph, real persisted loader, and recording trace port.
- Replaces only `AgentModelAdapter` with deterministic role outputs; no graph node, release loader, runtime, router, or session manager is mocked.
- Produces one acceptance proof from persisted session pin through all executed model roles and traces.

- [ ] **Step 1: Add the PostgreSQL shipped-seam acceptance test**

Bootstrap V1; create old root A pinned V1; publish a test-only structurally complete V2 with one distinct role prompt/hash; create new root B through the public root route; then execute shipped graph turns. Assert:

- A remains pinned to V1 and resolves V1 revision/hash after V2 becomes active.
- B pins V2 and resolves V2 revision/hash.
- Captured first and second fan-out payloads carry their actor session’s exact release ID.
- Every deterministic model invocation trace contains matching graph version/release/role/revision/hash.
- Foreman emits no model invocation/trace.
- The model adapter receives the stored endpoint/model settings and no tools.
- The session responses show A old and B active; starting latest creates a third ID and never changes A.

- [ ] **Step 2: Add a complete role/call matrix assertion**

Record `(agent_key, graph_release_id, agent_definition_revision_id, content_hash)` for Architect, Data Analyst, Builder, Build Reviewer, Fixer, Fix Reviewer, Deck Reviewer, Builder retry, Fixer retry, and committed-slide rereview. Assert each entry equals the chosen release’s persisted mapping and no call resolves against the currently active release unless that is also the conversation pin.

- [ ] **Step 3: Run focused acceptance and the supplied baseline set**

```bash
uv run --no-sync pytest -q -m postgres \
  tests/integration/test_conversation_pin_migration_postgres.py \
  tests/integration/test_conversation_pin_creation_postgres.py \
  tests/integration/test_persisted_graph_runtime_failures_postgres.py \
  tests/integration/test_conversation_pin_acceptance_postgres.py

uv run --no-sync pytest -q \
  tests/unit/test_database_migrations.py \
  tests/unit/test_startup_migrations.py \
  tests/unit/test_graph_configuration_models.py \
  tests/unit/test_graph_configuration_bootstrap.py \
  tests/unit/test_agent_runtime.py \
  tests/unit/test_persisted_graph_release.py \
  tests/unit/test_persisted_agent_runtime.py \
  tests/unit/test_conversation_pin_creation.py \
  tests/unit/test_conversation_graph_version_responses.py \
  tests/unit/test_chat_session_creation.py \
  tests/unit/test_graph_builder.py \
  tests/unit/test_graph_routers.py \
  tests/unit/test_graph_nodes.py \
  tests/unit/test_graph_state.py \
  tests/integration/test_graph_mode_turn.py
```

Expected: all pass with no new skip. Record failing causes/skipped identities if environment-dependent; never accept a matching count with different causes.

- [ ] **Step 4: Run frontend/CI gates**

```bash
cd frontend && npm test -- --run
cd frontend && npx tsc --noEmit
cd frontend && npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1
uv run --no-sync pytest -q tests/unit/test_e2e_matrix_covers_specs.py tests/unit/test_rc_graph_ci.py
git diff --check
```

- [ ] **Step 5: Perform final independent sabotages**

Use sabotage targets not already used by the task reviewer: corrupt V2 Architect’s persisted prompt while retaining its hash; drop `graph_release_id` only from the reviewer refan; record active rather than pinned release in the trace port; and make start-latest reuse A’s ID. Confirm the acceptance/E2E tests go red for the respective defects, restore, and re-run all Step 3/4 commands.

- [ ] **Step 6: Commit Task 9**

```bash
git add tests/integration/test_graph_mode_turn.py tests/integration/test_conversation_pin_acceptance_postgres.py tests/unit/test_rc_graph_ci.py
git commit -m "test: prove pinned graph runtime end to end (#261)"
```

## Plan-vs-code self-review and collision order

Before Task 1, the executor must re-run the probes in this table and write any mismatch as an explicit override in `.superpowers/issue-261-plan-corrections.md`. Tasks sharing a file execute in the listed order; they are not parallel work.

| Shared interface/file | Current fact at `7897cbc01` | Planned owner/order | Correction trigger |
|---|---|---|---|
| `UserSession` | No release FK; all writers at manager lines 738, 865, 1190, 3038 | Task 1 schema; Task 2 root manager only | Any new writer or FK already present |
| `_run_migrations` | One `engine.begin()` chain; graph mutation guards precede owner reassignment | Task 1 inserts pin schema before guards/reassignment | Transaction or helper ordering changed |
| Startup | `init_db` then graph bootstrap then profile/session/slide backfills | Task 1 inserts pin backfill immediately after bootstrap | Bootstrap moved or factory signature changed |
| Engine classifier | Owner’s earliest user message, ordered time then ID, exact phrase | Task 1 pure predicate/backfill parity | Stored engine marker/config appears |
| `SessionManager.create_session` | Own transaction, existing-ID early return, five positional/default params | Task 2 creation then Task 7 response | Transaction ownership/signature changed |
| New contributor/duplicate | Direct `UserSession` writers with null prospective pin | No production edit in #261 | #262 lands first; rebase and remove conflicting assertions |
| Release model | `GraphRelease` SCD2 and restrictive complete mappings | Tasks 2/3 | Publication interface lands; prefer it over test publisher |
| Content mapping | `definition_content_from_row` and `validate_definition_hash` are canonical | Task 3 reuses both | New canonical loader exists |
| `AgentRuntime.run` | `(agent_key, payload, assembly_context)`; production factory is compatibility | Task 4 single signature cutover | Persisted source/trace port already landed |
| Runtime calls | Ten calls at nodes lines 590, 1387, 1757, 1964, 1975, 2071, 2294, 2305, 2424, 2774 | Task 5 converts all together | Count/path changes; enumerate anew |
| Fan-outs | `build_branch_payload` then Builder record then `dict(record)` reviewer refan | Task 5 only | A third `Send` site appears |
| Session responses | Dicts from create/get/list; no graph fields | Task 7 after Task 2 | Pydantic response model replaces dicts |
| Frontend session state | `Session` omits graph fields; `switchSession` commits title/id/trace URL | Task 8 only | A dedicated conversation metadata store appears |
| `test_graph_mode_turn.py` | Shipped compiled-graph harness with deterministic external fakes | Task 6 focused failures, then Task 9 acceptance sequentially | Harness construction changes |

## Explicit no-scope boundaries

- Do not pin new contributor or duplicate rows; #262 owns their active-release locking and mixed-release behavior.
- Do not add shared-deck mixed-version warnings or actor/deck mutation attribution; #262 owns those surfaces.
- Do not add draft writes, publication product interfaces, rollback, approvals, tests/evidence, or workbench editing; later #258 child issues own them. Concurrency tests use a test-only structurally complete publisher.
- Do not implement editable schema overlays or arbitrary assembly rules. #261 executes/validates persisted V1 and fails explicitly on unsupported non-empty overlays or unknown rules.
- Do not change tool grants or bind tools to Data Analyst.
- Do not modify Foreman into a model-driven/configurable node.
- Do not change legacy monolith, MCP execution, exports, feedback models, or the LLM judge.
- Do not expose prompts, model settings, hashes, revision IDs, or release database IDs to non-admin conversation responses.
- Do not make old conversations auto-upgrade and do not infer a null pin as active/latest.

## Spec coverage matrix

| Requirement | Proof task |
|---|---|
| Nullable FK, bootstrap before backfill, deterministic graph/legacy classification, preserved nulls, idempotence, RESTRICT | Task 1 |
| Root explicit/chat auto-create one-transaction active-row locking and both lock orders | Task 2 |
| Existing contributors included in backfill; new contributor/duplicate owned by #262 | Tasks 1/2 rulings and tests |
| Complete exact-ID seven-revision load/cache with no fallback | Task 3 |
| Exact persisted prompt/model/assembly/protected/schema identity and unavailable dependency failures | Tasks 3/4/6 |
| Pin in state, both fan-outs, every role, rereview, and retries | Task 5 |
| Foreman deterministic and legacy monolith unchanged | Tasks 5/6/9 |
| Trace version/release/role/revision/hash through injected port | Tasks 4/9 |
| Safe response fields, badge, older state, explicit create/switch latest | Tasks 7/8 |
| Real PostgreSQL and shipped graph-mode coverage | Tasks 1/2/6/9 |
| Route/component/Playwright/CI coverage | Tasks 2/7/8/9 |

## Final completion gate

Implementation is complete only when every task commit is independently reviewable, the plan-corrections pre-pass has no unresolved interface mismatch, all RED tests were observed before implementation, reviewer and controller sabotage different production lines, the focused baseline has no new failure/skip cause, PostgreSQL lock waiters were observed for both schedules, the Playwright spec is in CI, and `git diff --check` is clean.
