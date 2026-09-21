# Graph Version 1 Bootstrap and Read-Only Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the seven current model-driven Agent Definitions as immutable Graph Version 1, seed the shared Graph Draft and required synthetic smoke cases exactly once, and expose the aggregate through an admin-only read API and read-only workbench.

**Architecture:** A static packaged v1 manifest freezes the exact #259 compatibility definitions and feeds one advisory-locked bootstrap transaction. A `GraphConfiguration` deep module owns canonical hashing, bootstrap invariants, and aggregate reads; SQLAlchemy models enforce closed roles, role-compatible mappings, restrictive deletion, content uniqueness, and one active PostgreSQL release. A dedicated admin router and lazily mounted three-pane frontend browse the aggregate without changing production graph execution.

**Tech Stack:** Python 3.11, SQLAlchemy, PostgreSQL/Lakebase, FastAPI, Pydantic v2, React 19, TypeScript, Vitest, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` (issue #260 scope)

## Global Constraints

- The exact editable role keys are `architect`, `data_analyst`, `builder`, `build_reviewer`, `fixer`, `fix_reviewer`, and `deck_reviewer` in that order.
- Foreman is deterministic topology only: it has no Agent Definition, prompt, model, revision, draft row, or editable controls.
- The v1 endpoint is exactly `databricks-claude-opus-4-6`; model parameters, prompt bytes, schema identities, and protected-assembly identities must match `CodeOwnedAgentDefinitionSource` at commit `ab8b8ac87`.
- The packaged v1 manifest is static bootstrap input. Once any Graph Release exists, startup never loads it, compares it, repairs from it, or uses it as a runtime fallback.
- Graph Version is the positive UI ordinal `version_number`, never an internal row ID.
- One Graph Release maps all seven roles to role-compatible immutable revisions; every mapping and draft completeness check compares the exact key set, not only a count.
- Exactly one release may have `effective_to IS NULL`, enforced by PostgreSQL partial unique index `uq_graph_release_one_active`.
- All release and revision foreign keys use `ON DELETE RESTRICT`; no graph-configuration relationship cascades deletion.
- `agent_test_case` is created here and bootstrap seeds one active required version-1 synthetic case per editable role. Test execution and run/evidence persistence remain issue #267.
- Production `AgentRuntime` remains on `CodeOwnedAgentDefinitionSource` until issue #261 supplies Conversation Pins and persisted release resolution.
- Every graph-definition backend route is protected by router-level `Depends(require_admin)`; frontend route gating is UX only.
- Legacy `tool_grants` stay code-owned and inert. They are absent from persistence, API responses, and the workbench.
- No Python dependency installation is allowed; the repository uses shared pyenv site-packages. Frontend dependencies use the checked-in lockfile.
- New frontend E2E specs must be listed in the explicit matrix in `.github/workflows/test.yml`.

## Non-goals

- Conversation Pins, session migration/backfill, graph-state propagation, persisted runtime resolution, and trace identities (#261/#262).
- Draft writes, optimistic save conflicts, and editable prompt/model controls (#263).
- Editable schema overlays, custom prompt assembly, model discovery, test execution, approvals, readiness, publication after v1, history, or rollback (#264–#270).
- Production fallback removal and full lifecycle contraction (#271).
- Tool assignment/binding, prompt-quality rewrites, legacy monolith model configuration, and configurable Foreman behavior.

---

### Task 1: Freeze and validate the static Graph Version 1 manifest

**Files:**
- Create: `src/services/graph_definition_manifest.py`
- Create: `src/services/agent_definition_manifest_v1.py`
- Create: `scripts/generate_graph_definition_manifest_v1.py`
- Create: `tests/unit/test_graph_definition_manifest.py`
- Read only: `src/services/agent_runtime.py`

**Interfaces:**
- Produces: `DefinitionContent`, `GraphV1Manifest`, `load_graph_v1_manifest() -> GraphV1Manifest`, `definition_content_hash(content: DefinitionContent) -> str`, and `assembly_rules_for(agent_key: str) -> dict[str, object]`.
- Consumes: `MODEL_DRIVEN_AGENT_KEYS` and `CodeOwnedAgentDefinitionSource` only in the one-shot generator and parity tests; the production loader reads only the static generated Python snapshot, and imports that large module only inside the loader call.
- Produces for Task 3: seven validated immutable candidates with lowercase SHA-256 hashes.

The generated Python module stores one static JSON string named
`GRAPH_VERSION_1_MANIFEST_JSON`. Keeping the resource in a Python module is
load-bearing: the deployed Apps wheel currently declares `include_package_data=False`
and does not ship arbitrary `src/**/*.json` package data. The JSON string has this
exact top-level shape:

```json
{
  "manifest_version": 1,
  "definitions": [
    {
      "agent_key": "architect",
      "definition_version": 2,
      "prompt_text": "exact generated snapshot",
      "model": {
        "endpoint_name": "databricks-claude-opus-4-6",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95
      },
      "schema_overlay": {
        "field_overrides": {},
        "additional_optional_fields": []
      },
      "assembly_rules": {
        "format_version": 1,
        "separator": "\n\n",
        "blocks": [
          {"kind": "authored_prompt", "condition": "always"},
          {"kind": "protected", "name": "slide_frame_constraints", "condition": "design_system_inactive"},
          {"kind": "protected", "name": "design_system_precedence", "condition": "design_system_active"},
          {"kind": "payload_json", "condition": "always", "indent": 2, "default": "str"},
          {"kind": "structured_output_binding", "condition": "always", "binding": "langchain.with_structured_output", "terminal": true}
        ]
      },
      "protected_assembly": {"version": 1, "digest": "64 lowercase hex characters"},
      "schema_contract": {"version": 1, "digest": "64 lowercase hex characters"}
    }
  ]
}
```

`blocks` freezes today's ordered behavior using only the approved conditions `always`,
`design_system_active`, `design_system_inactive`, and `payload_has_deck_brief`:
authored prompt; the Build Reviewer deck-brief protected block only for
`build_reviewer`; frame constraints when design system is inactive; design-system
precedence when active; JSON payload serialization with indent 2/default `str`; and
terminal `langchain.with_structured_output` binding. Unknown block kinds or conditions
fail validation before hashing. This does not claim the future universal trust-boundary
assembly is already active.

- [ ] **Step 1: Write failing manifest and hash tests**

```python
def test_packaged_v1_manifest_matches_exact_compatibility_definitions():
    manifest = load_graph_v1_manifest()
    assert tuple(item.agent_key for item in manifest.definitions) == MODEL_DRIVEN_AGENT_KEYS
    source = CodeOwnedAgentDefinitionSource()
    for item in manifest.definitions:
        current = source.resolve(item.agent_key)
        assert item.prompt_text == current.prompt_text
        assert item.definition_version == current.definition_version
        assert item.model.model_dump() == dataclasses.asdict(current.model_configuration)
        assert item.protected_assembly.model_dump() == {
            "version": current.protected_prompt.version,
            "digest": current.protected_prompt.digest,
        }
        assert item.schema_contract.model_dump() == {
            "version": current.schema_contract.version,
            "digest": current.schema_contract.digest,
        }


def test_v1_definition_versions_are_frozen_at_two():
    assert {item.definition_version for item in load_graph_v1_manifest().definitions} == {2}


def test_hash_covers_every_semantic_field():
    original = load_graph_v1_manifest().definitions[0]
    baseline = definition_content_hash(original)
    mutations = semantic_mutations(original)
    assert mutations
    assert {definition_content_hash(item) for item in mutations}.isdisjoint({baseline})


def test_manifest_contains_no_foreman_or_tool_grants():
    raw = json.loads(GRAPH_VERSION_1_MANIFEST_JSON)
    assert {item["agent_key"] for item in raw["definitions"]} == set(MODEL_DRIVEN_AGENT_KEYS)
    def assert_no_tool_grants(value):
        if isinstance(value, dict):
            assert "tool_grants" not in value
            for nested in value.values():
                assert_no_tool_grants(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_no_tool_grants(nested)

    assert_no_tool_grants(raw)


@pytest.mark.parametrize("agent_key", MODEL_DRIVEN_AGENT_KEYS)
@pytest.mark.parametrize("design_system_active", [False, True])
def test_manifest_assembly_replays_exact_runtime_prompt(agent_key, design_system_active):
    definition = CodeOwnedAgentDefinitionSource().resolve(agent_key)
    payload = (
        {"deck_brief": "Synthetic brief"}
        if agent_key == "build_reviewer"
        else {"synthetic": True}
    )
    runtime = AgentRuntime.compatibility()
    actual = runtime._assemble_prompt(
        definition,
        runtime._protected_prompts.resolve(definition.protected_prompt),
        payload,
        AgentAssemblyContext(design_system_active),
    )
    manifest_definition = definition_by_key(load_graph_v1_manifest(), agent_key)
    replayed = replay_literal_v1_rules(manifest_definition, payload, design_system_active)
    assert replayed.prompt == actual
    assert replayed.terminal_binding == "langchain.with_structured_output"
    assert manifest_definition.assembly_rules.blocks[-1].kind == "structured_output_binding"
```

`semantic_mutations` is a test utility that changes exactly one of: prompt byte, endpoint, temperature, max tokens, top-p, overlay, assembly block/order, protected version/digest, or schema version/digest. Expected values are literal and never computed by the hash implementation.
`replay_literal_v1_rules` is a test-only evaluator with expected block names,
conditions, and ordering written as literals; it never calls `assembly_rules_for()` or
the generator. Add literal assertions that the six non-reviewer roles have the exact
five-block plan, Build Reviewer has the conditional deck-brief block in position 2,
and truthy/falsy `deck_brief` changes only that protected block.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python -m pytest -q tests/unit/test_graph_definition_manifest.py -m 'not live'
```

Expected: import/file-not-found failures because the manifest module and packaged resource do not exist.

- [ ] **Step 3: Implement the typed loader, canonical hash, and one-shot generator**

Use frozen dataclasses/Pydantic models with `extra='forbid'`. Canonical hashing serializes this exact semantic object with `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, and `allow_nan=False`; excludes IDs/audit/timestamps; preserves prompt whitespace; and returns lowercase SHA-256 hex.

```python
def definition_content_hash(content: DefinitionContent) -> str:
    payload = content.canonical_payload()
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@lru_cache(maxsize=1)
def load_graph_v1_manifest() -> GraphV1Manifest:
    from src.services.agent_definition_manifest_v1 import GRAPH_VERSION_1_MANIFEST_JSON

    manifest = GraphV1Manifest.model_validate_json(GRAPH_VERSION_1_MANIFEST_JSON)
    manifest.assert_complete(MODEL_DRIVEN_AGENT_KEYS)
    return manifest
```

Merely importing `graph_definition_manifest` must not import the generated snapshot.
The generator resolves each compatibility definition, converts it to the exact manifest
contract, explicitly omits `legacy_tool_grants`, and writes a deterministic Python
module containing the indented JSON string. Run it once to create the checked-in
module; production never imports or executes the generator.

- [ ] **Step 4: Verify GREEN and sabotage the hash and assembly guards**

Run the focused test. Temporarily remove `top_p` from `canonical_payload` and confirm
the semantic hash test fails. Independently invert the design-system-active condition
and swap the payload/terminal block order, confirming the literal behavioral parity
tests fail for each sabotage. Restore every mutation and confirm the suite passes.
Record all RED/GREEN outputs in the task report.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/services/graph_definition_manifest.py src/services/agent_definition_manifest_v1.py scripts/generate_graph_definition_manifest_v1.py tests/unit/test_graph_definition_manifest.py
git commit -m "feat: freeze Graph Version 1 manifest (#260)"
```

---

### Task 2: Add the constrained graph-configuration persistence aggregate

**Files:**
- Create: `src/database/models/graph_configuration.py`
- Modify: `src/database/models/__init__.py`
- Modify: `src/core/database.py`
- Create: `tests/unit/test_graph_configuration_models.py`
- Create: `tests/integration/test_graph_configuration_constraints_postgres.py`

**Interfaces:**
- Consumes: role keys and `DefinitionContent` contract from Task 1.
- Produces: `AgentDefinitionRevision`, `GraphRelease`, `GraphReleaseAgent`, `GraphDraft`, `GraphDraftAgent`, and `AgentTestCase` ORM models.
- Produces for Task 3: metadata-created tables with named constraints, restrictive relationships, and PostgreSQL mutation guards for published artifacts.

Use singular table names from the approved design. JSON columns are `JSON().with_variant(JSONB(), "postgresql")`; audit timestamps are timezone-aware database timestamps. All role-bearing tables repeat the exact closed-role `CHECK`.

Required tables:

| Table | Required columns and constraints |
|---|---|
| `agent_definition_revision` | Integer `id`; role; positive `definition_version`; 64-char hash; prompt/model/overlay/assembly/protected/schema content; audit; unique `(agent_key, content_hash)` and `(id, agent_key)`; model ranges; nonblank endpoint/prompt; digest lengths. |
| `graph_release` | Integer `id`; unique positive `version_number`; restrictive self-FKs for predecessor/restore; nonblank note/audit; valid SCD2 interval; partial unique active index. |
| `graph_release_agent` | PK `(graph_release_id, agent_key)`; restrictive release FK; composite restrictive FK `(revision_id, agent_key) -> agent_definition_revision(id, agent_key)`. |
| `graph_draft` | Singleton small-int PK constrained to `1`; restrictive base release FK; nonnegative lock version; audit. |
| `graph_draft_agent` | PK `(graph_draft_id, agent_key)`; restrictive draft FK; candidate hash plus the same semantic definition columns and checks, including positive `definition_version`. |
| `agent_test_case` | Integer `id`; role; nonblank name; positive version; non-null `is_active`/`is_required` with database defaults true; non-null `synthetic_payload`/`assembly_context` JSON; non-null created/updated principal and timestamp; unique `(agent_key, name, version)`. |

- [ ] **Step 1: Write failing metadata and real-PostgreSQL constraint tests**

```python
def test_graph_configuration_tables_are_registered():
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


@pytest.mark.postgres
def test_release_mapping_rejects_cross_role_revision(postgres_engine):
    with postgres_engine.begin() as conn:
        ids = insert_architect_revision_and_builder_release(conn)
        with pytest.raises(IntegrityError):
            conn.execute(
                GraphReleaseAgent.__table__.insert().values(
                    graph_release_id=ids.release_id,
                    agent_key="builder",
                    agent_definition_revision_id=ids.architect_revision_id,
                )
            )


@pytest.mark.postgres
def test_database_rejects_second_active_release(postgres_engine):
    insert_release(postgres_engine, version_number=1, effective_to=None)
    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            insert_release(conn, version_number=2, effective_to=None)
    assert active_release_versions(postgres_engine) == [1]
```

Also test exact named checks, unknown role rejection, duplicate role/hash rejection,
restrictive deletion of referenced releases/revisions, singleton draft, invalid
intervals, and a closed release coexisting with the one active release. Against real
PostgreSQL, raw SQL must be unable to update/delete a definition revision or published
mapping, delete a release, reopen/second-close a release, or change any release field
other than the single legal `effective_to: NULL -> non-NULL` transition.

- [ ] **Step 2: Run the tests and verify RED**

```bash
python -m pytest -q tests/unit/test_graph_configuration_models.py -m 'not live'
python -m pytest -q tests/integration/test_graph_configuration_constraints_postgres.py -m postgres
```

Expected: model imports/tables are missing.

- [ ] **Step 3: Implement and register the six ORM models**

The one-active index must be a constant-expression partial index:

```python
Index(
    "uq_graph_release_one_active",
    text("(1)"),
    unique=True,
    postgresql_where=text("effective_to IS NULL"),
    sqlite_where=text("effective_to IS NULL"),
)
```

The mapping compatibility boundary must be the composite foreign key, not an application-only comparison:

```python
ForeignKeyConstraint(
    ["agent_definition_revision_id", "agent_key"],
    ["agent_definition_revision.id", "agent_definition_revision.agent_key"],
    name="fk_graph_release_agent_compatible_revision",
    ondelete="RESTRICT",
)
```

Model parameters stored as `Numeric(7, 6)` read back as `Decimal`. Task 1's canonical
adapter must normalize JSON floats and ORM decimals to the same plain non-exponent
scalar (`0.7 == Decimal("0.700000")`, `0.95 == Decimal("0.950000")`) before hashing,
while rejecting NaN/infinity. Add manifest-to-database round-trip hash coverage.

Do not add duplicate hand-written `CREATE TABLE` migration SQL. Import/export every
model from `src/database/models/__init__.py` so the existing
`Base.metadata.create_all()` path owns fresh-table DDL. Add idempotent PostgreSQL-only
trigger installation in `_run_migrations` after table creation and before shared-owner
reassignment:

```python
def _install_graph_configuration_mutation_guards(conn, schema, is_sqlite):
    if is_sqlite:
        return
    # agent_definition_revision and graph_release_agent: reject UPDATE/DELETE.
    # graph_release: reject DELETE; permit exactly one NULL -> non-NULL
    # effective_to close while every other column remains IS NOT DISTINCT FROM OLD.
```

Use schema-qualified function/trigger/table names and `CREATE OR REPLACE FUNCTION`
plus `DROP TRIGGER IF EXISTS`/`CREATE TRIGGER`, matching the repository migration
transaction. These guards are the database immutability boundary; application code
alone is not treated as sufficient.

- [ ] **Step 4: Verify GREEN and sabotage the compatibility/immutability constraints**

Run both suites. Temporarily remove the composite FK and confirm the cross-role test
goes red. Independently disable the revision trigger and confirm the raw-SQL mutation
test goes red. Restore both and rerun green. Record output.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/database/models/graph_configuration.py src/database/models/__init__.py src/core/database.py tests/unit/test_graph_configuration_models.py tests/integration/test_graph_configuration_constraints_postgres.py
git commit -m "feat: add Graph Release persistence constraints (#260)"
```

---

### Task 3: Bootstrap Graph Version 1, the shared draft, and required smoke cases atomically

**Files:**
- Create: `src/services/graph_configuration.py`
- Modify: `packages/databricks-tellr-app/databricks_tellr_app/run.py`
- Create: `tests/unit/test_graph_configuration_bootstrap.py`
- Create: `tests/integration/test_graph_configuration_bootstrap_postgres.py`
- Modify: `tests/unit/test_startup_migrations.py`

**Interfaces:**
- Consumes: static `load_graph_v1_manifest`, canonical hash, and ORM aggregate.
- Produces: `GraphConfiguration.bootstrap_v1(session_factory, *, actor="system:bootstrap", manifest_loader: Callable[[], GraphV1Manifest] | None = None) -> BootstrapResult` and module wrapper `bootstrap_graph_configuration(session_factory) -> BootstrapResult` for packaged startup.
- Produces: `GraphConfigurationIntegrityError` for partial/corrupt persisted aggregates.
- Produces for Task 4: `GraphConfiguration.read_workbench(session) -> GraphWorkbenchSnapshot` query boundary (implemented in Task 4).

`BootstrapResult` contains `created: bool`, `release_id: int`, and `version_number: int`. On PostgreSQL the transaction takes `pg_advisory_xact_lock(hashtext('tellr:graph-configuration-bootstrap:v1'))` before reading state.

The seven required cases use names `<agent_key>_required_smoke_v1`, version `1`, and
assembly context `{"design_system_active": false}`. Their payloads are literal,
non-sensitive snapshots of the current node-to-runtime boundary:

```python
REQUIRED_SMOKE_PAYLOADS = {
    "architect": {
        "session_id": "synthetic-architect",
        "conversation": [{"role": "user", "content": "Create a three-slide demo roadmap."}],
        "message": "Create a three-slide demo roadmap.",
        "current_deck_spec": None,
        "committed_slide_count": 0,
        "previous_deck_review": None,
        "available_design_contract": None,
        "template_sections": [],
        "resolved_style": "Synthetic demo style",
        "design_system_library": [],
    },
    "data_analyst": {
        "session_id": "synthetic-data-analyst",
        "data_request": "Summarize synthetic quarterly revenue of 10, 12, and 15.",
        "deck_purpose": "Demonstrate synthetic growth",
    },
    "builder": {
        "session_id": "synthetic-builder",
        "turn_id": "synthetic-turn",
        "initiated_by": "system:bootstrap",
        "position": 1,
        "slide_spec": {"position": 1, "title": "Synthetic roadmap", "purpose": "Show three phases"},
        "assumes": [],
        "hands_off": ["Phase 2 follows Phase 1"],
        "design_contract": {"design_system_id": None, "template_id": None},
        "resolved_data": {"facts": [], "figures": [], "sources": []},
        "section_html": "<section><h1>Roadmap</h1></section>",
        "section_css": ".slide { width: 1280px; height: 720px; }",
        "resolved_style": "Synthetic demo style",
        "design_system_active": False,
    },
    "build_reviewer": {
        "position": 1,
        "slide_spec": {"position": 1, "title": "Synthetic roadmap", "purpose": "Show three phases"},
        "resolved_style": "Synthetic demo style",
        "section_css": ".slide { width: 1280px; height: 720px; }",
        "resolved_data": {"facts": [], "figures": [], "sources": []},
        "html": "<div class='slide'><h1>Synthetic roadmap</h1></div>",
        "scripts": "",
        "deck_brief": {"purpose": "Demonstrate a synthetic roadmap", "audience": "Demo audience"},
    },
    "fixer": {
        "position": 1,
        "finding": {"criterion": "content_overflow", "message": "Synthetic title overflows"},
        "html": "<div class='slide'><h1>Synthetic roadmap title</h1></div>",
        "scripts": "",
        "slide_spec": {"position": 1, "title": "Synthetic roadmap", "purpose": "Show three phases"},
        "resolved_style": "Synthetic demo style",
        "section_css": ".slide { width: 1280px; height: 720px; }",
    },
    "fix_reviewer": {
        "position": 1,
        "finding": {"criterion": "content_overflow", "message": "Synthetic title overflows"},
        "change_summary": "Reduced the synthetic title size",
        "html": "<div class='slide'><h1 class='small'>Synthetic roadmap</h1></div>",
        "scripts": "",
        "slide_spec": {"position": 1, "title": "Synthetic roadmap", "purpose": "Show three phases"},
        "resolved_style": "Synthetic demo style",
        "section_css": ".slide { width: 1280px; height: 720px; }",
    },
    "deck_reviewer": {
        "session_id": "synthetic-deck-reviewer",
        "narrative_arc": ["Context", "Decision", "Action"],
        "call_to_action": "Approve the synthetic roadmap",
        "slide_count": 2,
        "slides": [
            {"position": 1, "html": "<div class='slide'><h1>Context</h1></div>"},
            {"position": 2, "html": "<div class='slide'><h1>Action</h1></div>"},
        ],
    },
}
```

Tests assert every persisted payload equals this literal mapping and can pass
unchanged through the corresponding `AgentRuntime` assembly/model-adapter seam.

- [ ] **Step 1: Write failing bootstrap/idempotence/rollback/startup tests**

```python
def test_fresh_bootstrap_creates_exact_complete_v1(session_factory):
    result = GraphConfiguration().bootstrap_v1(session_factory)
    assert result.created is True
    with session_factory() as session:
        assert exact_release_mapping(session, result.release_id) == expected_manifest_hashes()
        assert exact_draft_hashes(session) == expected_manifest_hashes()
        assert required_smoke_cases(session) == expected_smoke_case_identities()


def test_second_bootstrap_does_not_load_manifest_or_rewrite_rows(session_factory):
    service = GraphConfiguration()
    first = service.bootstrap_v1(session_factory)
    before = persisted_identity_snapshot(session_factory)
    second = service.bootstrap_v1(
        session_factory,
        manifest_loader=lambda: (_ for _ in ()).throw(AssertionError("manifest loaded")),
    )
    assert second == BootstrapResult(False, first.release_id, 1)
    assert persisted_identity_snapshot(session_factory) == before


def test_existing_active_v2_validates_current_state_without_loading_v1_manifest(
    session_factory, closed_v1_active_v2,
):
    sys.modules.pop("src.services.agent_definition_manifest_v1", None)
    result = GraphConfiguration().bootstrap_v1(session_factory)
    assert result == BootstrapResult(False, closed_v1_active_v2.release_id, 2)
    assert "src.services.agent_definition_manifest_v1" not in sys.modules


def test_bootstrap_failure_rolls_back_every_graph_artifact(session_factory):
    service = GraphConfiguration()

    def fail_after_flushed_mappings(session, *args, **kwargs):
        session.flush()
        raise InjectedBootstrapFailure("after flushed release mappings")

    service._insert_draft_and_cases = fail_after_flushed_mappings
    with pytest.raises(InjectedBootstrapFailure):
        service.bootstrap_v1(session_factory)
    assert graph_artifact_identities(session_factory) == EMPTY_GRAPH_ARTIFACTS
```

Use a monkeypatched narrow collaborator or test subclass rather than any shipped
`fail_after` flag. Run the rollback case both on a fully fresh database and with a
pre-existing reusable immutable revision, proving the latter survives unchanged while
all attempted release/draft/case writes roll back.
Add literal payload assertions and pass every case unchanged through an injected fake
model adapter. Add real PostgreSQL concurrency coverage proving two simultaneous
bootstraps return the same release identity and leave the exact same
mapping/draft/case identities. The concurrency test holds the first transaction after
its advisory lock, starts the second, observes a distinct backend PID waiting via
`pg_locks`/`pg_stat_activity`, and only then releases the first; unobserved overlap is
not accepted as concurrency evidence.

Startup tests assert this order:

```text
init_db -> bootstrap_graph_configuration -> migrate_profiles -> backfill_sessions
-> backfill_unmigrated_decks -> seed_defaults -> ensure_encryption_key
-> strip_retired_prompt_keys
```

and assert bootstrap failure aborts before workers start.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest -q tests/unit/test_graph_configuration_bootstrap.py tests/unit/test_startup_migrations.py -m 'not live'
python -m pytest -q tests/integration/test_graph_configuration_bootstrap_postgres.py -m postgres
```

Expected: `GraphConfiguration` and bootstrap calls are missing.

- [ ] **Step 3: Implement the deep bootstrap transaction**

The existing-release branch must validate the current active aggregate before
resolving or importing the v1 manifest:

```python
def bootstrap_v1(self, session_factory, *, actor="system:bootstrap", manifest_loader=None):
    with session_factory.begin() as session:
        self._take_bootstrap_lock(session)
        if session.scalar(select(exists().where(GraphRelease.id.is_not(None)))):
            snapshot = self._validate_current_graph(session)
            return BootstrapResult(False, snapshot.release_id, snapshot.version_number)
        if manifest_loader is None:
            from src.services.graph_definition_manifest import load_graph_v1_manifest

            manifest_loader = load_graph_v1_manifest
        manifest = manifest_loader()
        return self._insert_complete_v1(session, manifest, actor)
```

`_validate_current_graph` selects the sole active release (not the oldest/v1 release),
validates exact role-compatible mappings for every persisted release, validates the
singleton draft against the current active release, validates exact draft keys, and
proves each role has at least one active required Agent Test Case while allowing
additional/versioned cases. If no release exists, any pre-existing release mapping,
draft, draft-agent, or test-case row is corrupt partial state and fails; valid
unreferenced immutable revisions alone may be reused. Thus later closed v1 + active v2
startup remains valid and still never imports the v1 snapshot. Insertion uses one database timestamp, verifies
the exact seven-key revision/mapping/draft dictionaries after flush, seeds the seven
literal test cases, and commits once. Existing partial state raises
`GraphConfigurationIntegrityError`; it is never repaired. SQLite skips advisory
locking and is not concurrency evidence.

In packaged startup, call bootstrap immediately after `init_db()` and before existing data migrations/workers. Use `get_session_local()`; log and fail closed on exceptions.

- [ ] **Step 4: Verify GREEN and sabotage idempotence/rollback tests**

Run both suites. Temporarily import the generated snapshot at module scope and confirm
the active-v2 no-import test fails. Independently move `manifest_loader()` before the
existing-release branch and confirm the bomb-loader test fails. Restore and rerun
green. Separately verify the injected mid-transaction failure leaves all six tables
empty.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/services/graph_configuration.py packages/databricks-tellr-app/databricks_tellr_app/run.py tests/unit/test_graph_configuration_bootstrap.py tests/integration/test_graph_configuration_bootstrap_postgres.py tests/unit/test_startup_migrations.py
git commit -m "feat: bootstrap Graph Version 1 exactly once (#260)"
```

---

### Task 4: Expose one aggregate admin-only read interface

**Files:**
- Create: `src/api/schemas/agent_definitions.py`
- Create: `src/api/routes/agent_definitions.py`
- Modify: `src/api/main.py`
- Modify: `src/services/graph_configuration.py`
- Create: `tests/unit/test_agent_definition_workbench_routes.py`
- Verify: `tests/unit/test_route_authz_coverage.py`

**Interfaces:**
- Produces: `GraphConfiguration.read_workbench(session: Session) -> GraphWorkbenchSnapshot`.
- Produces: `GET /api/admin/agent-definitions/workbench` returning one consistent aggregate.
- Consumes in Task 5: JSON response models with `active_release`, `draft`, and ordered `nodes`.

The exact node order is Architect, Data Analyst, Builder, Build Reviewer, Foreman,
Fixer, Fix Reviewer, Deck Reviewer. The complete response contract is:

```json
{
  "active_release": {
    "release_id": 1,
    "version_number": 1,
    "previous_release_id": null,
    "restored_from_release_id": null,
    "release_note": "Bootstrap current code-owned Agent Definitions",
    "published_by": "system:bootstrap",
    "published_at": "2026-09-21T12:00:00Z",
    "effective_from": "2026-09-21T12:00:00Z",
    "effective_to": null
  },
  "draft": {
    "draft_id": 1,
    "base_release_id": 1,
    "base_version_number": 1,
    "lock_version": 0,
    "updated_by": "system:bootstrap",
    "updated_at": "2026-09-21T12:00:00Z"
  },
  "nodes": [
    {
      "agent_key": "architect",
      "display_name": "Architect",
      "execution_kind": "model",
      "editable": true,
      "changed": false,
      "published": {
        "revision_id": 1,
        "content_hash": "64 lowercase hex characters",
        "definition_version": 2,
        "prompt_text": "exact authored prompt",
        "model": {"endpoint_name": "databricks-claude-opus-4-6", "temperature": 0.7, "max_tokens": 60000, "top_p": 0.95},
        "schema_overlay": {"field_overrides": {}, "additional_optional_fields": []},
        "assembly_rules": {"format_version": 1, "separator": "\n\n", "blocks": [{"kind": "authored_prompt", "condition": "always"}, {"kind": "protected", "name": "slide_frame_constraints", "condition": "design_system_inactive"}, {"kind": "protected", "name": "design_system_precedence", "condition": "design_system_active"}, {"kind": "payload_json", "condition": "always", "indent": 2, "default": "str"}, {"kind": "structured_output_binding", "condition": "always", "binding": "langchain.with_structured_output", "terminal": true}]},
        "protected_assembly": {"version": 1, "digest": "64 lowercase hex characters"},
        "schema_contract": {"version": 1, "digest": "64 lowercase hex characters"}
      },
      "draft": {
        "base_revision_id": 1,
        "candidate_hash": "64 lowercase hex characters",
        "definition_version": 2,
        "prompt_text": "exact authored prompt",
        "model": {"endpoint_name": "databricks-claude-opus-4-6", "temperature": 0.7, "max_tokens": 60000, "top_p": 0.95},
        "schema_overlay": {"field_overrides": {}, "additional_optional_fields": []},
        "assembly_rules": {"format_version": 1, "separator": "\n\n", "blocks": [{"kind": "authored_prompt", "condition": "always"}, {"kind": "protected", "name": "slide_frame_constraints", "condition": "design_system_inactive"}, {"kind": "protected", "name": "design_system_precedence", "condition": "design_system_active"}, {"kind": "payload_json", "condition": "always", "indent": 2, "default": "str"}, {"kind": "structured_output_binding", "condition": "always", "binding": "langchain.with_structured_output", "terminal": true}]},
        "protected_assembly": {"version": 1, "digest": "64 lowercase hex characters"},
        "schema_contract": {"version": 1, "digest": "64 lowercase hex characters"}
      },
      "read_only_reason": null
    },
    {
      "agent_key": "foreman",
      "display_name": "Foreman",
      "execution_kind": "deterministic",
      "editable": false,
      "changed": false,
      "published": null,
      "draft": null,
      "read_only_reason": "Foreman is deterministic scheduling and routing code; it has no Agent Definition."
    }
  ]
}
```

The actual response contains all eight nodes. `effective_to`, both lineage IDs, model
node `read_only_reason`, and Foreman's `published`/`draft` are nullable exactly as
shown. `base_revision_id` is derived by joining `draft.base_release_id + agent_key` to
that release's mapping; it is not persisted on `graph_draft_agent`. Task 5's
TypeScript discriminated union mirrors these fields and nullability exactly. Internal
row IDs are opaque foreign-key identities; the UI labels releases only by
`version_number`.

- [ ] **Step 1: Write failing aggregate, corruption, and authorization tests**

```python
def test_admin_workbench_returns_exact_order_and_v1(admin_client, bootstrapped_db):
    response = admin_client.get("/api/admin/agent-definitions/workbench")
    assert response.status_code == 200
    body = response.json()
    assert body["active_release"]["version_number"] == 1
    assert [node["agent_key"] for node in body["nodes"]] == EXPECTED_TOPOLOGY_ORDER
    assert body["nodes"][4] == EXPECTED_FOREMAN_NODE


def test_non_admin_is_denied_before_prompts_are_loaded(non_admin_client, read_spy):
    response = non_admin_client.get("/api/admin/agent-definitions/workbench")
    assert response.status_code == 403
    read_spy.assert_not_called()
    assert "prompt_text" not in response.text


def test_corrupt_incomplete_release_fails_without_manifest_fallback(admin_client, corrupt_db):
    response = admin_client.get("/api/admin/agent-definitions/workbench")
    assert response.status_code == 500
    assert response.json()["detail"] == "Graph configuration is incomplete"
```

Force production-mode authorization, current user, negative admin-group probe, and reset the admin cache so the denial is real rather than the test-mode bypass.
Create the corrupt-route `TestClient` with `raise_server_exceptions=False`; separately
call the service and assert the precise `GraphConfigurationIntegrityError` cause.
Add a PostgreSQL service test that pauses after the parent snapshot lock, attempts a
concurrent draft/release state change, and proves the response is wholly before/after,
never a mixed aggregate.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest -q tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_route_authz_coverage.py -m 'not live'
```

Expected: missing router/schema/read method.

- [ ] **Step 3: Implement the snapshot read, response models, router, and registration**

```python
router = APIRouter(
    prefix="/api/admin/agent-definitions",
    tags=["admin", "agent-definitions"],
    dependencies=[Depends(require_admin)],
)


@router.get("/workbench", response_model=GraphWorkbenchResponse)
def get_agent_definition_workbench(db: Session = Depends(get_db)) -> GraphWorkbenchResponse:
    try:
        snapshot = GraphConfiguration().read_workbench(db)
    except GraphConfigurationIntegrityError:
        logger.exception("Persisted Graph Configuration is incomplete")
        raise HTTPException(status_code=500, detail="Graph configuration is incomplete")
    return GraphWorkbenchResponse.model_validate(snapshot, from_attributes=True)
```

The service verifies exactly one active release, exact seven-key mapping, singleton draft based on that release, exact seven-key draft rows, hash integrity, and role-compatible identities. It never calls the bootstrap manifest. Import and include the router explicitly in `src/api/main.py`.
Every nested response model sets `ConfigDict(from_attributes=True)` so adaptation from
the frozen snapshot dataclasses is deliberate and tested. The service establishes one
coherent read boundary by locking the active release and singleton draft together in
one joined `SELECT ... FOR SHARE` before reading their immutable mappings/revisions
and draft agents. Future draft/publication writers must take those parent locks before
mutation; #260 tests a forced interleaving rather than assuming multiple SELECTs are
coherent under READ COMMITTED.

- [ ] **Step 4: Verify GREEN and sabotage the authorization gate**

Run the focused tests. Temporarily remove the router-level dependency, confirm the explicit non-admin test both reaches the service and fails, restore it, and rerun green. Record output.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/api/schemas/agent_definitions.py src/api/routes/agent_definitions.py src/api/main.py src/services/graph_configuration.py tests/unit/test_agent_definition_workbench_routes.py
git commit -m "feat: expose admin Graph Version 1 workbench (#260)"
```

---

### Task 5: Build the lazily mounted read-only three-pane workbench

**Files:**
- Create: `frontend/src/api/agentDefinitions.ts`
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx`
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx`
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/index.ts`
- Modify: `frontend/src/components/Admin/AdminPage.tsx`
- Modify: `frontend/tests/fixtures/mocks.ts`
- Create: `frontend/tests/e2e/agent-definition-workbench.spec.ts`
- Modify: `.github/workflows/test.yml`
- Verify: `tests/unit/test_e2e_matrix_covers_specs.py`

**Interfaces:**
- Consumes: `GET /api/admin/agent-definitions/workbench` from Task 4.
- Produces: typed `getAgentDefinitionWorkbench()`, an `Agent Definitions` admin tab, and read-only responsive panes.
- Produces extension seams: #263 enables centre editing; #267 replaces the right placeholder with isolated testing.

The workbench must not fetch until the tab is selected. Left pane lists eight nodes and lets the admin select one. Centre exposes accessible Prompt, Model, Output Schema, and Assembly tabs (`tablist`/`tab`/`tabpanel`) for a model node, with Prompt selected by default and keyboard/selectable behavior; Foreman replaces the centre editor with only its deterministic explanation. Right pane says isolated testing is not available in this release. Header shows `Graph Version 1`, draft base version, and lock version. There are no Save Draft, Run, Approve, Reject, Review & Publish, Publish, or Rollback controls.

- [ ] **Step 1: Write failing component and Playwright behavior tests**

Write independently falsifiable component tests for loading, contained errors, exact
eight-node topology/order, Foreman selection, exact definition details, and forbidden
controls. Query the left navigation by role/button rather than ambiguous text. Inspect
all button/link accessible names with case-insensitive patterns that catch `Save Draft`,
`Run`, `Approve`, `Reject`, `Review & Publish`, `Publish`, and `Rollback`, including
longer labels rather than exact-name-only matches. Assert the four centre tabs have
correct accessible semantics, Prompt is selected deterministically, keyboard/click
selection changes the visible tabpanel, and Foreman has no model-definition tabs.

Playwright registers exact endpoint and identity mocks before navigation, counts only
`**/api/admin/agent-definitions/workbench`, asserts zero matching requests before the
Agent Definitions tab click and exactly one after, and asserts exact eight-node order
plus exact synthetic prompt/model/schema/assembly values through the centre tabs. Run
separate 403 and 500 cases and prove each error stays inside the panel while page
chrome and another admin tab remain usable. At a deliberately smaller viewport, prove
the documented three-pane overflow/collapse behavior rather than merely checking that
content remains somewhere in the DOM.

- [ ] **Step 2: Run tests and verify RED**

```bash
cd frontend && npm run test:unit -- AgentDefinitionWorkbench.test.tsx
cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1
```

Expected: missing module/spec behavior.

- [ ] **Step 3: Implement typed API and conditional workbench mount**

```tsx
{activeTab === 'agent_definitions' && (
  <div role="tabpanel" id="agent-definitions-panel" aria-labelledby="agent-definitions-tab">
    <AgentDefinitionWorkbench />
  </div>
)}
```

Do not follow existing permanently mounted hidden panels for this sensitive content. The API wrapper preserves HTTP status and FastAPI `detail` in a typed error. Implement the centre editor with accessible `tablist`/`tab`/`tabpanel` semantics and a deterministic Prompt default. Use a responsive grid with deliberate, testable horizontal overflow/collapse behavior; do not assume the existing `max-w-6xl` shell fits three panes. Add the E2E spec stem to the workflow matrix.

- [ ] **Step 4: Verify GREEN, typecheck, and prove lazy loading**

```bash
cd frontend && npm run test:unit -- AgentDefinitionWorkbench.test.tsx
cd frontend && npm run typecheck
cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts tests/e2e/admin-route-gate.spec.ts --project=chromium --workers=1
python -m pytest -q tests/unit/test_e2e_matrix_covers_specs.py -m 'not live'
```

Temporarily mount the component unconditionally, confirm the no-request-before-click Playwright assertion fails, restore conditional mounting, and rerun green. Record output.

- [ ] **Step 5: Commit Task 5**

```bash
git add frontend/src/api/agentDefinitions.ts frontend/src/components/Admin/AgentDefinitionWorkbench frontend/src/components/Admin/AdminPage.tsx frontend/tests/fixtures/mocks.ts frontend/tests/e2e/agent-definition-workbench.spec.ts .github/workflows/test.yml
git commit -m "feat: browse Graph Version 1 in admin (#260)"
```

---

## Final verification and acceptance evidence

After the five task reviews are clean, run:

```bash
python -m pytest -q \
  tests/unit/test_graph_definition_manifest.py \
  tests/unit/test_graph_configuration_models.py \
  tests/unit/test_graph_configuration_bootstrap.py \
  tests/unit/test_agent_definition_workbench_routes.py \
  tests/unit/test_startup_migrations.py \
  tests/unit/test_route_authz_coverage.py \
  tests/unit/test_e2e_matrix_covers_specs.py \
  -m 'not live'

python -m pytest -q \
  tests/integration/test_graph_configuration_constraints_postgres.py \
  tests/integration/test_graph_configuration_bootstrap_postgres.py \
  -m postgres

cd frontend && npm run test:unit
cd frontend && npm run typecheck
cd frontend && npx playwright test \
  tests/e2e/agent-definition-workbench.spec.ts \
  tests/e2e/admin-page.spec.ts \
  tests/e2e/admin-route-gate.spec.ts \
  --project=chromium --workers=1

python -m pytest -q -m 'not live'
git diff --check
git status --short
```

Compare full-suite failure causes with the baseline, not only the count. At `ab8b8ac87`, the accepted baseline is exactly two unrelated `tests/unit/test_deploy_autoscaling.py` causes: autoscaling availability returns `provisioned`, and autoscaling creation failure does not call the provisioned fallback. Any new failure cause blocks completion.

The final whole-branch reviewer must receive the complete diff plus the ledger's rulings/deferred findings and explicitly compare: all six table invariants, every writer/reader of v1 state, rollback-on-bootstrap-failure, static-manifest non-fallback behavior, backend authorization-before-read, and conditional frontend loading. A review-ready PR must include the plan, corrections, implementation commits, exact test evidence, and no unrelated files.
