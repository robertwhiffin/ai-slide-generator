# Conversation Pins and Persisted Graph V1 Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Before Task 1 load executing-plans-tellr, write .superpowers/issue-261-plan-corrections.md, and treat it as an override. Reviewers sabotage a different guarded production line, show red, restore, then show green.

**Goal:** Migrate graph-capable conversations to Graph Version 1, pin explicitly graph-capable new root conversations atomically, and execute each graph model invocation from its exact persisted release.

**Architecture:** conversation_pins is the deep persistence module for schema/backfill, active-release locking, exact pin loading, and safe version projection. PersistedGraphReleaseLoader loads a complete immutable release snapshot by ID; AgentRuntime consumes it with an injected identity sink. Graph entry loads the pin once, then state and both Send payloads transport it to every model-driven node.

**Tech Stack:** Python 3.11, SQLAlchemy 2, PostgreSQL 15/Lakebase, FastAPI, Pydantic v2, LangGraph, structured application logging, React 19, TypeScript, Vitest, Playwright, pytest.

**Spec:** docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md; GitHub #258, #261, #262; .superpowers/issue-261-preflight.md in the #260 worktree.

## Global constraints and authority rulings

- Re-probe paths/signatures against the execution base before Task 1. Python site-packages are shared: do not install packages or create an environment. Apps BUILD uses packages/databricks-tellr-app/pyproject.toml. Start and finish with test ! -d .venv, which python, and python --version; stop unless it is the shared pyenv Python 3.11 interpreter. Every backend command in this plan is python -m pytest, never uv.
- Roles are exactly architect, data_analyst, builder, build_reviewer, fixer, fix_reviewer, and deck_reviewer. Foreman remains deterministic. Do not change monolith, MCP, exports, feedback, judge, tools, or candidate/workbench operations.
- user_sessions.graph_release_id is nullable, ON DELETE RESTRICT, and immutable once written. Null means legacy/no-graph, never active/latest.
- **Strict ticket boundary:** #261 changes only explicit POST /api/sessions root creation. It must not edit src/api/routes/chat.py, _maybe_create_session, contributor/duplicate creation, or mixed-release UI: #262 explicitly owns all of those.
- **Pre-message capability ruling:** the browser is the explicit graph-capable root caller. CreateSessionRequest.graph_capable defaults false for non-browser API callers, while AppLayout.handleNewSession sends graphCapable: true before any first user message and Start-latest does likewise. This gives the ordinary browser root a pin before transcript-marker graph selection. A pinned browser root may take a monolith turn; UI calls it Pinned Graph Version, never claims that graph execution already happened. Chat auto-create remains #262. Cost if wrong: changing browser default capability only changes this route/request contract; it does not rewrite pins.
- Persisted production execution has no manifest, code-owned/compatibility source, active/latest, default endpoint, or current-contract fallback. Cache complete validated snapshots only by exact release ID. A code-owned compatibility adapter is test-only and cannot be returned by get_agent_runtime.
- The final #260 PRD amendment prohibits MLflow production/development tracing and retention of field-engineer work. Production identity handling is a structured application-log sink containing only graph version, release ID, role, revision ID, content hash, outcome, and error class; it never logs payload, prompt, output, session/user ID, tools, or slide HTML, and writes no Lakebase/UC trace row. Tests use an in-memory recording sink.
- Public response fields are only graph_version, active_graph_version, and is_older_than_active; no internal/revision/prompt/endpoint/schema data leaks.
- Every new PostgreSQL file starts pytestmark = pytest.mark.postgres and is explicitly added to integration-graph in .github/workflows/test.yml.

## Dependency ledger

| Producer | Exact interface | Consumer |
|---|---|---|
| Task 1 | backfill_conversation_pins(session_factory: sessionmaker) -> BackfillResult | startup |
| Task 2 | lock_active_graph_release(db: Session) -> PinnedRelease; load_conversation_pin(session_factory: sessionmaker, session_id: str) -> int | Tasks 3, 5 |
| Task 3 | PersistedGraphReleaseLoader.resolve(graph_release_id: int, agent_key: str) -> ResolvedDefinition | Task 4 |
| Task 4 | AgentRuntime.run(agent_key: str, graph_release_id: int, payload: dict[str, Any], assembly_context: AgentAssemblyContext) -> AgentInvocationResult | Task 5 |
| Task 5 | GraphState.graph_release_id: int and graph-entry pin loading | Tasks 6, 9 |
| Task 7 | get_conversation_graph_version(db: Session, session: UserSession) -> ConversationGraphVersion | Task 8 |

### Task 1: Nullable schema, deterministic backfill, and boot ordering

**Files:**

- Create: src/domain/conversation_engine.py, src/services/conversation_pins.py, tests/integration/test_conversation_pin_migration_postgres.py
- Modify: src/database/models/session.py, src/core/database.py, src/api/services/chat_service.py, packages/databricks-tellr-app/databricks_tellr_app/run.py, tests/unit/test_database_migrations.py, tests/unit/test_startup_migrations.py, tests/unit/test_encryption.py

**Produces:**

~~~
AGENT_MODE_PHRASE = "USE AGENT MODE"
def selects_graph_engine(content: str | None) -> bool:
    return bool(content) and AGENT_MODE_PHRASE in content

@dataclass(frozen=True)
class BackfillResult:
    graph_release_id: int
    graph_version: int
    pinned_count: int

def backfill_conversation_pins(session_factory: sessionmaker) -> BackfillResult:
    with session_factory.begin() as db:
        return _backfill_in_transaction(db)
~~~

- [ ] Write pytestmark = pytest.mark.postgres RED tests from a pre-column user_sessions table. Run _run_migrations, bootstrap V1, then seed graph root, tied-timestamp roots ordered by ID, legacy root with a later marker, empty root, graph/legacy contributors, and a historical pre-pinned row. Assert the complete exact identity map and second call BackfillResult(v1_id, 1, 0). Inspect nullable catalog field, fk_user_sessions_graph_release with confdeltype == "r", and ix_user_sessions_graph_release_id; change FK to cascade briefly and require red.
- [ ] Add startup RED assertions that the prefix is exactly init_db, bootstrap_graph_configuration, backfill_conversation_pins, and bootstrap/backfill failure exits 1 before profile/session/slide backfills. Extend every startup stub with the new import.
- [ ] Run:

~~~bash
python -m pytest -q -m postgres tests/integration/test_conversation_pin_migration_postgres.py
python -m pytest -q tests/unit/test_database_migrations.py tests/unit/test_startup_migrations.py tests/unit/test_encryption.py
~~~

- [ ] Add:

~~~python
graph_release_id = Column(Integer, ForeignKey(
    "graph_release.id", name="fk_user_sessions_graph_release", ondelete="RESTRICT"
), nullable=True, index=True)
graph_release = relationship("GraphRelease", foreign_keys=[graph_release_id])
~~~

Add _migrate_conversation_pin_schema(conn, inspector, schema, _qual, is_sqlite) inside _run_migrations, before mutation guards/reassignment. PostgreSQL adds nullable integer, named FK, index idempotently; SQLite adds nullable integer/index only. Implement the pure predicate and make existing engine selection delegate without behavioral change.
- [ ] Implement one-transaction set backfill: select V1 by version_number == 1; identify each root owner’s first user message with row_number() over (partition by session_id order by created_at, id); update only matching graph rows where pin is null. Do not query active/latest or manifest.
- [ ] After successful bootstrap call backfill_conversation_pins(get_session_local()), log ID/version/count, and fail startup on exception. Run GREEN, sabotage IS NULL and root-owner join independently, restore, commit.

### Task 2: Explicit-root linearization and a produced pin-loader interface

**Files:**

- Modify: src/api/schemas/requests.py, src/api/routes/sessions.py, src/api/services/session_manager.py
- Create: tests/unit/test_conversation_pin_creation.py, tests/integration/test_conversation_pin_creation_postgres.py

**Produces:**

~~~python
class CreateSessionRequest(BaseModel):
    session_id: Optional[str]
    title: Optional[str]
    graph_capable: bool = False

@dataclass(frozen=True)
class PinnedRelease:
    release_id: int
    graph_version: int

class ActiveGraphReleaseUnavailableError(RuntimeError): pass
class ConversationPinMissingError(RuntimeError): pass
class ConversationSessionNotFoundError(RuntimeError): pass

MAX_ACTIVE_RELEASE_LOCK_SCANS = 2

def lock_active_graph_release(db: Session) -> PinnedRelease:
    for scan in range(MAX_ACTIVE_RELEASE_LOCK_SCANS):
        release = db.execute(_active_release_for_update()).scalar_one_or_none()
        if release is not None:
            return PinnedRelease(release.id, release.version_number)
        if scan == 0:
            continue
    raise ActiveGraphReleaseUnavailableError("no active Graph Release")

def load_conversation_pin(session_factory: sessionmaker, session_id: str) -> int:
    with session_factory() as db:
        row = db.scalar(select(UserSession).where(UserSession.session_id == session_id))
        if row is None:
            raise ConversationSessionNotFoundError(session_id)
        if not isinstance(row.graph_release_id, int):
            raise ConversationPinMissingError(session_id)
        return row.graph_release_id
~~~

- [ ] RED-test False/omitted API creation as null, graph_capable=True creation as exact active pin, existing supplied IDs as immutable, and only this route maps missing active release to 503. Assert Task 2 does not edit/import chat auto-create.
- [ ] Write real-PG forced concurrency tests with independent factories and existing waiter helpers. Publication-first: creator's first active-row scan sees R1 and blocks; publisher closes R1/inserts R2/commits; the same blocked statement returns no matching row; the bounded second statement locks R2; assert created root commits R2. Creation-first: creator locks R1 and flushes pinned root; publisher waits on R1; assert root commits R1, then publisher commits R2. Observe each blocked backend from a third connection, including the retry scan count. Start every new PostgreSQL module with the module marker.
- [ ] Run:

~~~bash
python -m pytest -q tests/unit/test_conversation_pin_creation.py
python -m pytest -q -m postgres tests/integration/test_conversation_pin_creation_postgres.py
~~~

- [ ] Change the existing signature only by appending:

~~~python
def create_session(self, user_id: Optional[str] = None, title: Optional[str] = None,
                   session_id: Optional[str] = None, created_by: Optional[str] = None,
                   agent_config: Optional[Dict[str, Any]] = None,
                   graph_capable: bool = False) -> Dict[str, Any]:
~~~

Keep existing-ID return before locking. For a new graph-capable row in the existing transaction, call the lock helper, set pin, add, flush. _active_release_for_update() is select(GraphRelease).where(GraphRelease.effective_to.is_(None)).with_for_update(). The second scan is a fresh READ COMMITTED statement only after the first scan returned no row; its bounded purpose is the publication-first R1→R2 handoff, not fallback. Route passes only request.graph_capable and catches only ActiveGraphReleaseUnavailableError.
- [ ] Implement loader with one external-session lookup: absent raises ConversationSessionNotFoundError; null/non-int raises ConversationPinMissingError; success returns int(pin); it does not query GraphRelease. GREEN; sabotage lock, predicate, null guard separately; restore, commit.

### Task 3: Exact complete persisted-release loader

**Files:** Create src/services/persisted_graph_release.py, tests/unit/test_persisted_graph_release.py.

**Produces:**

~~~python
class PersistedRuntimeError(RuntimeError): pass
class GraphReleaseNotFoundError(PersistedRuntimeError): pass
class GraphReleaseIncompleteError(PersistedRuntimeError): pass
class PersistedConfigurationUnavailableError(PersistedRuntimeError): pass
class PinnedInvocationEndpointError(PersistedRuntimeError): pass

@dataclass(frozen=True)
class ResolvedDefinition:
    graph_version: int; graph_release_id: int; agent_key: str
    agent_definition_revision_id: int; content_hash: str
    content: DefinitionContent

class PersistedGraphReleaseLoader:
    def __init__(self, *, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory
        self._cache: dict[int, dict[str, ResolvedDefinition]] = {}

    def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition:
        return self._load_complete_release(graph_release_id)[agent_key]
~~~

- [ ] RED-test seven complete mappings, exact-ID cache, V1/V2 distinction, absent release, zero mapping, six mapping, null/missing revision, wrong/duplicate role, altered hash, and no active/latest lookup. Count exactly one release-anchored read before an uncached result. For all seven persisted V1 rows assert ResolvedDefinition.content is typed DefinitionContent, content.assembly_rules is typed AssemblyRules, and exact typed parsing rejects a wrong format_version, separator, block order, block condition, or terminal binding.
- [ ] Implement one GraphRelease-anchored outer-join query through mapping/revision. No release row raises NotFound; null mapping/revision, duplicate/unexpected/missing role raises Incomplete. Build each content with validate_definition_hash, which calls definition_content_from_row and therefore validates DefinitionContent/AssemblyRules; convert Pydantic/ValueError to PersistedConfigurationUnavailableError with code invalid_persisted_definition. Cache only the typed full snapshot after all seven validate. Never substitute current identity.
- [ ] GREEN; sabotage outer join to inner and cache before validation; restore, commit.

### Task 4: Persisted runtime and trace interface

**Files:**

- Create: src/services/agent_runtime_identity.py, tests/unit/test_persisted_agent_runtime.py
- Modify: src/services/agent_runtime.py, tests/unit/test_agent_resolution_prompt.py, tests/unit/test_agent_runtime.py, tests/unit/test_graph_definition_manifest.py, tests/unit/test_graph_configuration_bootstrap.py, tests/unit/test_deck_level_spec_change.py, tests/agentic/gates.py, tests/integration/test_graph_live_real_model.py

**Produces:**

~~~python
@dataclass(frozen=True)
class AgentInvocationIdentity:
    graph_version: int; graph_release_id: int; agent_key: str
    agent_definition_revision_id: int; content_hash: str

class AgentInvocationIdentitySink(Protocol):
    def invoke(self, identity: AgentInvocationIdentity,
               callback: Callable[[], BaseModel]) -> BaseModel:
        raise NotImplementedError

class RecordingAgentInvocationIdentitySink:
    def __init__(self) -> None:
        self.calls: list[AgentInvocationIdentity] = []
    def invoke(self, identity: AgentInvocationIdentity,
               callback: Callable[[], BaseModel]) -> BaseModel:
        self.calls.append(identity)
        return callback()

class LoggingAgentInvocationIdentitySink:
    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger
    def invoke(self, identity: AgentInvocationIdentity,
               callback: Callable[[], BaseModel]) -> BaseModel:
        try:
            result = callback()
        except Exception as exc:
            self._logger.info("persisted_agent_invocation", extra={
                **identity.__dict__, "outcome": "error", "error_class": type(exc).__name__,
            })
            raise
        self._logger.info("persisted_agent_invocation", extra={
            **identity.__dict__, "outcome": "success", "error_class": None,
        })
        return result
~~~

- [ ] RED-test construction with persisted_release_loader, model_adapter, identity_sink; invoke run("architect", 41, payload, AgentAssemblyContext(False)); assert persisted endpoint/schema/contracts/identity and all five identity fields. The logging sink test captures one record with only identity, outcome, error_class; assert no prompt, payload, output, session/user identifier, or model response. Make removed-endpoint provider call throw: require PinnedInvocationEndpointError contains endpoint plus release/revision identity, excludes prompt/payload, records error outcome, and never tries default endpoint.
- [ ] Replace constructor/method exactly:

~~~python
def __init__(self, *, persisted_release_loader: PersistedGraphReleaseLoader,
             model_adapter: AgentModelAdapter, identity_sink: AgentInvocationIdentitySink) -> None:
    self._persisted_release_loader = persisted_release_loader
    self._model_adapter = model_adapter
    self._identity_sink = identity_sink
def run(self, agent_key: str, graph_release_id: int, payload: dict[str, Any],
        assembly_context: AgentAssemblyContext) -> AgentInvocationResult:
    definition = self._persisted_release_loader.resolve(graph_release_id, agent_key)
    return self._run_resolved(definition, payload, assembly_context)
~~~

Implement _assemble_v1_prompt(content: DefinitionContent, protected: _ProtectedPromptBundle, payload: dict[str, Any], context: AgentAssemblyContext) -> str: require content.assembly_rules == AssemblyRules.model_validate(assembly_rules_for(content.agent_key)); append authored prompt; append each protected block only for its exact condition; append json.dumps(payload, indent=2, default=str) for payload_json; require structured_output_binding as terminal and use resolved schema for model binding; join text blocks with content.assembly_rules.separator. Require the V1 empty SchemaOverlay contract before schema resolution. Parity-test this evaluator against tests/unit/test_graph_definition_manifest.py literal replay for every role, design-system active/inactive, and build-reviewer deck-brief present/absent.
- [ ] Convert exceptions at the loader/runtime seam: SQLAlchemyError or session-factory failure -> PersistedConfigurationUnavailableError(code="lakebase_unavailable"); DefinitionContent/Pydantic validation -> code="invalid_persisted_definition"; ProtectedPromptBundleUnavailableError -> code="protected_bundle_unavailable"; IncompatibleSchemaContractError -> code="schema_contract_unavailable"; endpoint adapter exception -> PinnedInvocationEndpointError. Do not convert ordinary model output validation/review findings: node recovery remains valid for those.
- [ ] get_agent_runtime() constructs persisted loader, Databricks adapter, and LoggingAgentInvocationIdentitySink. It never calls compatibility. Retain AgentRuntime.compatibility only as a test-only constructor backed by CodeOwnedAgentDefinitionSource and RecordingAgentInvocationIdentitySink; it accepts the same four-argument run interface and ignores graph_release_id only after validating it is positive. Migrate every named direct caller and its final gate: test_agent_resolution_prompt, test_agent_runtime, test_graph_definition_manifest, test_graph_configuration_bootstrap, test_deck_level_spec_change, tests/agentic/gates, and test_graph_live_real_model. Run focused suites, commit.

### Task 5: Pin entry/state/fan-out propagation and all fixture migration

**Files:** Modify src/services/graph/builder.py, state.py, nodes.py, routers.py, tests/unit/conftest_graph.py, tests/integration/conftest_stub_skills.py, tests/integration/conftest.py, tests/unit/test_graph_{builder,routers,nodes,state}.py, tests/unit/test_deck_level_spec_change.py, tests/integration/test_graph_mode_turn.py.

- [ ] RED-test injected loader result, hostile initial["graph_release_id"], both Send payloads, Builder retry, Fixer retry, and rereview propagation.
- [ ] Change entry:

~~~python
def invoke_graph(session_id: str, initial: Optional[Dict[str, Any]] = None, *,
                 emitter: Any = None, principal: Optional[str] = None,
                 describe_only: bool = False, request_id: Optional[str] = None,
                 pin_loader: Callable[[sessionmaker, str], int] = load_conversation_pin
                 ) -> Dict[str, Any]:
    graph_release_id = pin_loader(get_session_local(), session_id)
~~~

Overwrite any initial pin in state.update; declare GraphState.graph_release_id; copy it in build_branch_payload, Builder record, and reviewer dict(record) re-fan.
- [ ] Convert every runtime call explicitly: Architect/Data Analyst/Deck Reviewer use state["graph_release_id"]; Builder/retry and Build Reviewer use payload["graph_release_id"]; Fixer/retry/Fix Reviewer use state. Change rereview_committed_slides(session_id, spec, brand, graph_release_id) and every direct test caller.
- [ ] Migrate SkillStub, _CallBudget, SkillRecorder, and CallableAgentRuntime to run(self, name: str, graph_release_id: int, payload: dict, assembly_context: Any) and record the ID. In graph_turn_env bootstrap V1, persist the session pin, store self.graph_release_id, and add "graph_release_id": self.graph_release_id to _GraphTurnEnv._turn_state before state.update(initial or {}); after update overwrite it again so hostile initial cannot replace it. Assert every recorder call sees that ID. Re-run orchestration, deck-spec-change, sweeper, architect persistence, row alignment, graph-mode turn, plus all Task 4 compatibility suites. GREEN; sabotage initial overwrite, each Send, retry, rereview, and fixture state seed independently; restore, commit.

### Task 6: Typed persisted failures escape later node recovery

**Files:** Modify src/services/graph/nodes.py, src/api/services/chat_service.py, tests/integration/test_graph_mode_turn.py; create tests/integration/test_persisted_graph_runtime_failures_postgres.py. This is the only Task 6 chat_service edit; Task 1 owns its selector delegation.

- [ ] RED-test null pin at shipped graph seam; direct real-loader nonexistent ID; incomplete release; unavailable protected contract; database failure; removed endpoint; poisoned runtime on monolith. Seed newer active release and assert zero fallback calls. Corrupt Builder and Deck Reviewer mappings separately and require typed graph failure, not placeholder/advisory. For every case assert stream event has type ERROR, error exactly "Pinned graph configuration is unavailable", and metadata exactly {"code": "pinned_graph_configuration_unavailable"}; it includes no exception name, release ID, endpoint, prompt, payload, or output.
- [ ] Add:

~~~python
def _raise_if_persisted_runtime_failure(exc: Exception) -> None:
    if isinstance(exc, PersistedRuntimeError):
        raise exc
~~~

Call it first in broad recovery blocks for Builder, Build Reviewer, Fixer, Fix Reviewer, Deck Reviewer, and rereview. Preserve ordinary output/model recovery. At graph chat seam catch only PersistedRuntimeError, log exception class/release ID server-side through the identity-safe logger, and emit the exact safe stream event above; do not stringify the exception and do not change monolith path.
- [ ] Do not defer a non-deferrable FK or delete immutable release to create dangling state. Direct loader proves absent ID; shipped seam proves null pin. GREEN; sabotage active fallback, one re-raise, and monolith isolation; restore, commit.

### Task 7: Safe session version projection

**Files:** Modify src/services/conversation_pins.py, src/api/services/session_manager.py, src/api/routes/sessions.py, tests/integration/test_api_routes.py; create tests/unit/test_conversation_graph_version_responses.py.

**Produces:**

~~~python
@dataclass(frozen=True)
class ConversationGraphVersion:
    graph_version: int | None
    active_graph_version: int
    is_older_than_active: bool
def get_conversation_graph_version(db: Session, session: UserSession) -> ConversationGraphVersion:
    active = _require_active_graph_release(db)
    pinned = _pinned_graph_release_or_none(db, session.graph_release_id)
    return ConversationGraphVersion(
        graph_version=None if pinned is None else pinned.version_number,
        active_graph_version=active.version_number,
        is_older_than_active=bool(pinned and pinned.version_number < active.version_number),
    )
~~~

- [ ] RED-test create/get/list for active, historical, null pins; recursively reject private fields; null is (None, 2, False). Assert list uses one active query and pinned outer join rather than N+1.
- [ ] Merge helper output into existing/new/unpinned response dictionaries; missing referent/active is integrity error. Reuse Task 2's PinnedRelease for success creation. GREEN; sabotage release-ID comparison, leaked ID, null-active; restore, commit.

### Task 8: Browser pre-message capability, accurate badge, and Start-latest

**Files:** Create frontend/src/components/Conversation/GraphVersionStatus.tsx, its test, and frontend/tests/e2e/conversation-graph-version.spec.ts; modify frontend/src/services/api.ts, contexts/SessionContext.tsx, components/Layout/AppLayout.tsx, .github/workflows/test.yml.

- [ ] Define:

~~~ts
type GraphVersionStatusProps = {
  graphVersion: number | null; activeGraphVersion: number; isOlder: boolean;
  onStartLatest: () => Promise<void>; isStartingLatest: boolean;
};
~~~

Extend Session and OptionalSessionInfo with graph_version, active_graph_version, is_older_than_active. Change api.createSession options exactly to { sessionId?: string; title?: string; graphCapable?: boolean }; serialize graph_capable: options?.graphCapable ?? false. SessionContextType gains graphVersion: number | null, activeGraphVersion: number | null, isGraphVersionOlder: boolean, and setConversationGraphVersion(info: Pick<OptionalSessionInfo, "graph_version" | "active_graph_version" | "is_older_than_active">): void. createNewSession resets all three to null/null/false; switchSession obtains/copies these three fields with title/deck data and commits them in its existing atomic non-cancelled block; failed restore calls createNewSession and therefore resets them.
- [ ] RED-test active/old/null rendering and context reset/restore/switch. Add an ordinary New Session -> first USE AGENT MODE E2E: intercept POST /api/sessions, require {session_id: generatedId, graph_capable: true} before the chat request; return pinned-version fields; submit marker; assert graph-stream request uses that same persisted ID. This test is the browser half of pre-message capability; Task 9 is the PostgreSQL/graph half. Existing A(v1/active-v2) Start-latest test requires one POST body with graph_capable true, switches to B(v2), and makes no mutation to A; 503 retains A/context fields.
- [ ] Implement normal new-root creation as graph-capable before the first message, retaining current local UUID flow:

~~~ts
// AppLayout.handleNewSession, after createNewSession() returns newId
const created = await api.createSession({ sessionId: newId, graphCapable: true });
setConversationGraphVersion(created);

// GraphVersionStatus.onStartLatest
const latest = await api.createSession({ graphCapable: true });
const restored = await switchSession(latest.session_id, latest);
setSlideDeck(restored.slideDeck); setRawHtml(restored.rawHtml);
navigate("/sessions/" + latest.session_id + "/edit");
~~~

For normal creation, on 503 retain the freshly local null-version session and surface error; do not send a graph turn. Add Playwright specs to matrix. Run Vitest, tsc --noEmit, Playwright, E2E matrix guard; sabotage graphCapable serialization, context restore, patch-A, and pre-switch; restore, commit.

### Task 9: Deterministic real-PostgreSQL acceptance and CI enrollment

**Files:** Create tests/integration/test_conversation_pin_acceptance_postgres.py; modify tests/integration/test_graph_mode_turn.py, .github/workflows/test.yml.

- [ ] Build real PostgreSQL migration/models/bootstrap, real loader/runtime/compiled graph/checkpointer and RecordingAgentInvocationIdentitySink; replace only AgentModelAdapter. Capture real router sends without replacing the graph: save routers.Send, monkeypatch routers.Send with recording_send(node, arg) that appends copy.deepcopy(arg) to sent[node] then returns saved_Send(node, arg). Assert sent["builder"] and sent["build_reviewer"] after each turn.
- [ ] Give the adapter a complete deque state machine. It extracts session_id from the final JSON payload in the assembled prompt, looks up (session_id, turn_number), verifies the next expected role, and returns its typed schema constructor. Execute A turn 1 fully before A turn 2, then B turn 1; no call is allowed after its deque is empty.

| Conversation / turn | Exact role sequence and output |
|---|---|
| A / 1 on V1 | architect ask_data; data_analyst synthesis; architect build one SlideSpec; builder unsafe HTML; builder safe HTML retry; build_reviewer objective overflow Finding; fixer unsafe HTML; fixer safe HTML retry; fix_reviewer empty findings; deck_reviewer empty findings |
| A / 2 on V1 | architect edit with changed deck-level audience; rereview build_reviewer objective overflow Finding; builder safe rebuilt HTML; build_reviewer empty findings; deck_reviewer empty findings |
| B / 1 on V2 | architect ask_data; data_analyst synthesis; architect build one SlideSpec; builder unsafe HTML; builder safe HTML retry; build_reviewer objective overflow Finding; fixer unsafe HTML; fixer safe HTML retry; fix_reviewer empty findings; deck_reviewer empty findings |

Use exact current schemas: ArchitectOutput(intent="ask_data", message="need data", data_request=DataRequest(question="revenue")) then ArchitectOutput(intent="build", message="build", deck_spec=make_deck_spec(1)); AnalystOutput(outcome="success", synthesis="fixture synthesis", sources=["fixture://source"]); BuilderOutput(position=0, html=UNSAFE_HTML, scripts="") then BuilderOutput(position=0, html=SAFE_HTML, scripts=""); SlideReviewOutput(slide_index=0, verdict="surfaced", findings=[objective_finding(0)]) or SlideReviewOutput(slide_index=0, verdict="clean", findings=[]); FixerOutput(position=0, html=UNSAFE_HTML, scripts="", changed=True) then FixerOutput(position=0, html=SAFE_FIXED_HTML, scripts="", changed=True); DeckReviewOutput(findings=[]). Set UNSAFE_HTML to an img tag with source https://attacker.com/b.png; set SAFE_HTML to builder_html(0) and SAFE_FIXED_HTML to fixed_html(0). Assert expected ordered (session_id, turn, role, graph_release_id, revision_id, content_hash) after every turn, including two Builder and two Fixer calls in A/B first turns and the complete A-second-turn rebuild tail.
- [ ] Explicitly create root A graph-capable on V1; test-publish complete V2; create B graph-capable; execute the state machine. Assert every identity matches persisted mapping; every log/recorded sink identity does likewise; both captured Send lists carry exact pins; Foreman has no sink call; A is still V1/old and B V2/active; latest makes C without changing A.
- [ ] Add all four files to integration-graph: migration, creation, persisted-failures, acceptance. Run tests/unit/test_ci_collects_integration_tests.py; this task owns backend CI after Task 8's Playwright edit.
- [ ] Run this concrete final gate; record failing causes and skipped test identities before/after each schema or runtime-interface change:

~~~bash
python -m pytest -q -m postgres \
  tests/integration/test_conversation_pin_migration_postgres.py \
  tests/integration/test_conversation_pin_creation_postgres.py \
  tests/integration/test_persisted_graph_runtime_failures_postgres.py \
  tests/integration/test_conversation_pin_acceptance_postgres.py
python -m pytest -q \
  tests/unit/test_database_migrations.py \
  tests/unit/test_startup_migrations.py \
  tests/unit/test_conversation_pin_creation.py \
  tests/unit/test_persisted_graph_release.py \
  tests/unit/test_persisted_agent_runtime.py \
  tests/unit/test_agent_resolution_prompt.py \
  tests/unit/test_agent_runtime.py \
  tests/unit/test_graph_definition_manifest.py \
  tests/unit/test_graph_configuration_bootstrap.py \
  tests/unit/test_graph_builder.py tests/unit/test_graph_routers.py \
  tests/unit/test_graph_nodes.py tests/unit/test_graph_state.py \
  tests/unit/test_deck_level_spec_change.py \
  tests/integration/test_graph_mode_turn.py \
  tests/integration/test_deck_spec_change_turn.py \
  tests/integration/test_sweeper_describe_only.py \
  tests/unit/test_ci_collects_integration_tests.py \
  tests/unit/test_e2e_matrix_covers_specs.py
cd frontend && npm test -- --run
cd frontend && npx tsc --noEmit
cd frontend && npx playwright test tests/e2e/conversation-graph-version.spec.ts --project=chromium --workers=1
git diff --check
~~~

Final independent sabotages are V2 prompt/hash corruption, reviewer re-fan pin deletion, active ID trace, and C reusing A ID. Restore each, rerun the affected gate, then commit:

~~~bash
git add docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md .github/workflows/test.yml tests/integration
git commit -m "test: prove pinned graph runtime end to end (#261)"
~~~

## Sequential collision table

| File/interface | Required order |
|---|---|
| conversation_pins.py | Tasks 1 → 2 → 7 |
| session_manager.py, routes/sessions.py | Tasks 2 → 7 |
| agent_runtime.py | Tasks 3 → 4 → 5 |
| graph/nodes.py | Task 5 propagation → Task 6 typed failures |
| test_deck_level_spec_change.py | Task 4 runtime → Task 5 rereview pin |
| chat_service.py | Task 1 selector delegation → Task 6 stream failure contract |
| test_graph_mode_turn.py | Task 5 → Task 6 → Task 9 |
| .github/workflows/test.yml | Task 8 Playwright → Task 9 integration files |

## Completion gate

Re-probe this ledger before execution; compare failure causes after every schema/runtime change; show distinct controller/reviewer sabotage evidence; prove all four PostgreSQL files have markers and workflow enrollment; run test ! -d .venv, which python, python --version, python -m pytest -q tests/unit/test_ci_collects_integration_tests.py tests/unit/test_e2e_matrix_covers_specs.py, git diff --check, and git status --short.
