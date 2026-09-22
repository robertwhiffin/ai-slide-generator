# Shared Graph Draft Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an administrator explicitly save prompt and model-setting edits for one Agent Definition into the shared Graph Draft, with canonical hashing, accountable optimistic concurrency, and lossless stale-edit recovery.

**Architecture:** Keep `GraphConfiguration` as the small aggregate facade and add one deep draft-write module behind it. The module reconstructs and validates complete `DefinitionContent` under exclusive aggregate locks, while the HTTP adapter accepts only the five #263-owned fields; the frontend keeps per-agent form state locally and crosses the write seam only when the administrator selects **Save Draft**.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL 15, React 19, TypeScript 5.9, Vitest, Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` (especially §§5.4, 7.2, 10, 11.1, 13.1, 14–17), GitHub issues #258 and #263.

## Global Constraints

- Start from reviewed #260 head `7897cbc0190155ba70c80945047c6be5b99a1481`; do not weaken its bootstrap, integrity, read-lock, immutable-release, or CI-collection guarantees.
- At execution time load `executing-plans-tellr` alongside `superpowers:subagent-driven-development`; run the plan-vs-code corrections pre-pass before Task 1 and attach the corrections ledger to every implementer/reviewer brief.
- Use the shared Python environment with `uv run --no-sync`; never install a package or create a virtual environment. Leave the ignored `frontend/node_modules` symlink unchanged.
- The public save request exposes exactly `prompt_text`, exact `endpoint_name`, `temperature`, `max_tokens`, and `top_p`, plus the optimistic `lock_version`; `agent_key` is the path identity.
- A public save cannot set `agent_key`, `definition_version`, schema overlay, assembly rules, protected identities, base/revision IDs, candidate hash, audit fields, evidence, or release state.
- Validate in #263 only nonblank prompt/endpoint, exact endpoint text, finite `temperature`/`top_p` in `[0, 1]`, and positive integral `max_tokens`. Endpoint discovery, endpoint existence/connectivity, arbitrary-URL policy, and structured-output capability belong to #266.
- Reconstruct and canonical-hash the complete persisted `DefinitionContent`; never introduce a five-field hash. Preserve the reviewed v1 overlay and assembly policy unchanged.
- Every write uses one explicit transaction, exclusive locks on the singleton draft parent and selected draft-agent row, exact aggregate validation, a database transaction timestamp, and a nonblank trusted request principal.
- An explicit valid same-content save increments `lock_version` and updates audit metadata, but returns `changed: false`; evidence applicability changes only when the canonical hash changes.
- A stale save returns the stable `409` envelope defined below, preserves both candidates, performs no write, and never partially overwrites another agent or the parent audit token.
- Emit only `Clean`, `Unsaved`, and `Needs test` for model agents. `Test failed`, `Awaiting review`, and `Approved` remain #267 work backed by immutable evidence.
- Historical evidence is never updated or invalidated. Applicability is identity-based: candidate hash (and, in #267, test-case version) either matches or it does not; exact reversion to an eligible earlier hash may reuse evidence.
- Ordinary typing, validation, selection changes, tab changes, remounts, conflict actions, and navigation never save. Only **Save Draft** issues the `PUT`.
- Backend authorization precedes body parsing or prompt leakage. A non-admin or missing/blank trusted principal receives `403` without echoing submitted content and without reaching the write module.
- Tests prove observable identities, values, hashes, mappings, audit data, and lock transitions. Counts alone are not concurrency evidence.
- Every task uses RED/GREEN TDD and independently falsifies the new test by sabotaging a different production line, confirming the sabotage is on the executed path, observing RED, restoring it, and observing GREEN.
- Files shared by successive tasks are edited sequentially. Each task is committed before the next begins, using the exact commit message shown in that task.

---

## Product rulings fixed by this plan

1. `changed` in a save response means “this operation changed the candidate hash,” not “the draft differs from the published release.” Therefore a repeated explicit save of the current candidate returns `changed: false` while still advancing the shared lock and audit metadata. UI `Needs test` is calculated independently from saved candidate hash versus published hash.
2. The endpoint string is retained exactly. #263 rejects only blank/whitespace-only text and numeric syntax/bounds; #266 owns discovery, existence, connectivity, arbitrary-URL decisions, and structured-output checks.
3. Until #267 adds immutable run/verdict queries, the status vocabulary is exactly `Clean`, `Unsaved`, and `Needs test` (plus Foreman’s existing `Deterministic · read-only`).
4. #263 does not alter `SchemaOverlay`, `AssemblyRules`, `DefinitionContent.validate_role_assembly`, protected bundle identities, schema-contract identities, or any v1 overlay/assembly rule.
5. A stale response is useful data, not a failed generic detail string: it echoes the submitted five-field candidate and returns the current selected server candidate plus current draft metadata.
6. Conflict **Keep local** adopts the returned server baseline and new lock token while retaining the submitted local form, ready for a later explicit retry. Conflict **Reload** adopts the server form and retains the submitted form as a visible recovery copy until the user restores or dismisses it. Neither action writes.

## Stable interfaces and wire contracts

### Backend module interface

Create `src/services/graph_configuration_draft.py` with these public facade types and methods:

```python
from dataclasses import dataclass
from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from src.services.graph_configuration_workbench import (
    DraftDefinitionSnapshot,
    DraftMetadataSnapshot,
)
from src.services.graph_definition_manifest import AgentKey, DefinitionContent


@dataclass(frozen=True)
class EditableModelDraft:
    prompt_text: str
    endpoint_name: str
    temperature: float
    max_tokens: int
    top_p: float


@dataclass(frozen=True)
class DraftSaveResult:
    draft: DraftMetadataSnapshot
    definition: DraftDefinitionSnapshot
    changed: bool


ClientCandidateT = TypeVar("ClientCandidateT")


@dataclass(frozen=True)
class DraftSaveConflict(Generic[ClientCandidateT]):
    expected_lock_version: int
    current_lock_version: int
    client_candidate: ClientCandidateT
    draft: DraftMetadataSnapshot
    definition: DraftDefinitionSnapshot


DraftSaveOutcome = DraftSaveResult | DraftSaveConflict[ClientCandidateT]


class DraftContentRejected(ValueError):
    """A trusted caller proposed content outside the draft-writer contract."""


```

Facade method signatures (implemented in full in Task 1):

```text
_GraphConfigurationDraft.save_editable_model_draft(
    self,
    session: Session,
    *,
    agent_key: AgentKey,
    expected_lock_version: int,
    candidate: EditableModelDraft,
    actor: str,
) -> DraftSaveResult | DraftSaveConflict[EditableModelDraft]

_GraphConfigurationDraft.save_draft_content(
    self,
    session: Session,
    *,
    expected_lock_version: int,
    content: DefinitionContent,
    actor: str,
) -> DraftSaveResult | DraftSaveConflict[DefinitionContent]
```

`save_draft_content` is the trusted downstream seam for #264 and #265. It may change the five model/prompt values, `schema_overlay`, or `assembly_rules`, but rejects a mismatch in `agent_key`, `definition_version`, `protected_assembly`, or `schema_contract` relative to the locked stored candidate. Both facade methods use the same private locked writer, hash function, audit update, and conflict construction.

`EditableModelDraft` is deliberately a domain command rather than an HTTP model. The writer itself therefore validates exact types, finiteness, bounds, and nonblank text before it locks or writes; route validation is an earlier UX/security layer, not the only correctness layer. `DraftContentRejected` represents caller-controlled invalid commands/invariant changes; `GraphConfigurationIntegrityError` remains reserved for persisted aggregate corruption.

### HTTP operation

`PUT /api/admin/agent-definitions/draft/{agent_key}` accepts:

```json
{
  "lock_version": 4,
  "candidate": {
    "prompt_text": "Exact authored text",
    "model": {
      "endpoint_name": "databricks-claude-opus-4-6",
      "temperature": 0.7,
      "max_tokens": 60000,
      "top_p": 0.95
    }
  }
}
```

Every request model uses `ConfigDict(extra="forbid", strict=True)`. Validators reject whitespace-only prompt and endpoint without trimming or rewriting accepted values. `temperature` and `top_p` reject booleans, strings, NaN, infinities, and values outside `[0, 1]`; `max_tokens` rejects booleans, strings, fractions, zero, and negatives.

Success `200`:

```json
{
  "draft": {
    "draft_id": 1,
    "base_release_id": 41,
    "base_version_number": 1,
    "lock_version": 5,
    "updated_by": "admin@example.com",
    "updated_at": "2026-09-22T12:00:00Z"
  },
  "definition": {
    "base_revision_id": 11,
    "candidate_hash": "64-lowercase-hex",
    "definition_version": 2,
    "prompt_text": "Exact authored text",
    "model": {
      "endpoint_name": "databricks-claude-opus-4-6",
      "temperature": 0.7,
      "max_tokens": 60000,
      "top_p": 0.95
    },
    "schema_overlay": {"field_overrides": {}, "additional_optional_fields": []},
    "assembly_rules": {"format_version": 1, "separator": "\n\n", "blocks": []},
    "protected_assembly": {"version": 1, "digest": "64-lowercase-hex"},
    "schema_contract": {"version": 1, "digest": "64-lowercase-hex"}
  },
  "changed": true
}
```

The example’s empty `blocks` is only envelope notation; actual successful content retains the locked valid v1 block sequence. The server response returns the protected/full content so clients rehydrate from authority, but the request cannot send it.

Stale `409` (the route projects the domain command’s flat `endpoint_name`/numeric members into the same nested `model` wire shape used by the request):

```json
{
  "code": "stale_draft",
  "expected_lock_version": 4,
  "current_lock_version": 5,
  "client_candidate": {
    "prompt_text": "Submitted local text",
    "model": {
      "endpoint_name": "custom-endpoint-exact-name",
      "temperature": 0.2,
      "max_tokens": 4096,
      "top_p": 0.8
    }
  },
  "server": {
    "draft": {
      "draft_id": 1,
      "base_release_id": 41,
      "base_version_number": 1,
      "lock_version": 5,
      "updated_by": "winner@example.com",
      "updated_at": "2026-09-22T12:00:00Z"
    },
    "definition": {
      "base_revision_id": 11,
      "candidate_hash": "64-lowercase-hex",
      "definition_version": 2,
      "prompt_text": "Winning server text",
      "model": {
        "endpoint_name": "databricks-claude-opus-4-6",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95
      },
      "schema_overlay": {"field_overrides": {}, "additional_optional_fields": []},
      "assembly_rules": {"format_version": 1, "separator": "\n\n", "blocks": []},
      "protected_assembly": {"version": 1, "digest": "64-lowercase-hex"},
      "schema_contract": {"version": 1, "digest": "64-lowercase-hex"}
    }
  }
}
```

Stable `422`:

```json
{
  "code": "invalid_draft",
  "errors": [
    {
      "field": "candidate.model.temperature",
      "code": "out_of_range",
      "message": "Temperature must be between 0 and 1."
    }
  ]
}
```

Use these field names: `agent_key`, `lock_version`, `candidate.prompt_text`, `candidate.model.endpoint_name`, `candidate.model.temperature`, `candidate.model.max_tokens`, and `candidate.model.top_p`. Extra input reports its full dotted location with code `extra_forbidden`; malformed JSON uses field `$`, code `invalid_json`, message `Request body must be valid JSON.` Exact messages for owned fields are defined in Task 3 tests.

### Frontend state interface

`frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts` exports:

```typescript
export type DraftStatus = 'Clean' | 'Unsaved' | 'Needs test';
export type DraftNumberInput = number | '';
export type EditableDraftField =
  | 'prompt_text'
  | 'endpoint_name'
  | 'temperature'
  | 'max_tokens'
  | 'top_p';

export interface EditableModelDraftForm {
  prompt_text: string;
  endpoint_name: string;
  temperature: DraftNumberInput;
  max_tokens: DraftNumberInput;
  top_p: DraftNumberInput;
}

export interface DraftEditorEntry {
  publishedHash: string;
  saved: DraftDefinition;
  local: EditableModelDraftForm;
  fieldErrors: Partial<Record<EditableDraftField, string>>;
  conflict: DraftSaveConflictResponse | null;
  recoveryCandidate: EditableModelDraft | null;
  saving: boolean;
}

export interface DraftEditorState {
  draft: DraftMetadata;
  byAgent: Record<AgentKey, DraftEditorEntry>;
}

export function createDraftEditorState(
  workbench: AgentDefinitionWorkbenchResponse,
): DraftEditorState;
export function draftStatus(entry: DraftEditorEntry): DraftStatus;
export function validateDraftForm(form: EditableModelDraftForm):
  | { ok: true; candidate: EditableModelDraft }
  | { ok: false; errors: Partial<Record<EditableDraftField, string>> };
```

The reducer/hook actions are `edit`, `saveStarted`, `saveSucceeded`, `saveInvalid`, `saveConflicted`, `reloadServer`, `keepLocal`, `restoreRecovery`, and `dismissRecovery`. Later UI tickets consume these exports rather than inventing another lock, hash, conflict, or autosave model.

## Plan-vs-code shared interface and file table

All “verified” entries below were re-probed at `7897cbc01` on 2026-09-22; executors re-run the commands in the execution pre-pass because the plan is not runtime evidence.

| Shared seam/file | Verified current fact | #263 change and stable handoff | Ordering |
| --- | --- | --- | --- |
| `src/services/graph_configuration.py` | `GraphConfiguration(_GraphConfigurationWorkbench, _GraphConfigurationBootstrap)` is the only public facade. | Compose `_GraphConfigurationDraft`; re-export the draft types only. #264/#265 call `save_draft_content`; routes call `save_editable_model_draft`. | Task 1 only. |
| `src/services/graph_configuration_workbench.py` | `read_workbench(Session) -> GraphWorkbenchSnapshot` holds shared parent locks and validates singleton, active base, exact seven mappings, compatible revisions, exact seven draft rows, and hashes. | Extract private “parents locked → validate/project snapshot” logic; keep public read behavior byte-for-byte equivalent; give the writer one internal exclusive parent/selected-row loader. | Task 1 before PostgreSQL tests. |
| `src/services/graph_configuration_content.py` | `_PERSISTED_CONTENT_FIELDS` exactly equals all 13 ORM content columns; row reconstruction and canonical hash validation already centralize semantic content. | Reuse unchanged. All writes apply `definition_content_values`; no second field registry. | Read-only in every task. |
| `src/services/graph_definition_manifest.py` | `DefinitionContent.canonical_payload()` includes agent/version, five fields, overlay, assembly, and both protected identities; finite decimals normalize; assembly is still v1-closed. | Reuse unchanged. #263 must not broaden overlay/assembly. | Read-only in every task. |
| `src/database/models/graph_configuration.py` | Draft id check is `id = 1`; child PK is `(graph_draft_id, agent_key)`; content checks cover nonblank text and numeric ranges; releases/revisions are immutable artifacts. | No schema or migration. Writer updates one `graph_draft_agent` and the singleton `graph_draft` only. | Read-only in every task. |
| `src/services/graph_configuration_draft.py` | Does not exist. | Cohesive lock/validate/rebuild/hash/audit/conflict/rollback module; trusted full-content handoff. | Create Task 1; exercise Task 2. |
| `src/api/schemas/agent_definitions.py` | GET response flattens the shared content snapshot and forbids extras. | Append strict write/request/success/409/422 types; do not alter GET shape. | Task 3. |
| `src/api/routes/agent_definitions.py` | Router-level `Depends(require_admin)` protects GET; `get_db` closes but does not commit. | Add one `PUT`; parse body only after auth/principal dependencies; writer owns transaction. | Task 3. |
| `src/core/user_context.py` / `_authz.py` | Production admin check fails closed, local/test admin bypass exists, and `require_current_user()` raises a runtime error rather than an HTTP contract. | Reuse `get_current_user()` in a route-local `require_draft_write_principal()` returning stable `403`; never accept actor from JSON. | Task 3; no edits to these files. |
| `tests/integration/test_agent_definition_workbench_postgres.py` | Real QueuePool/PostgreSQL test proves reader/writer waiting; CI `integration-graph` already names this file. | Add forced two-writer same-version interleavings and rollback/timestamp assertions. No CI workflow edit is required unless the pre-pass disproves collection. | Task 2. |
| `frontend/src/api/agentDefinitions.ts` | GET types/client only; StrictMode read coalescing is deliberate. | Add stable save types/client and preserve structured error JSON. Never coalesce writes. | Task 4. |
| `draftEditorState.ts` / `useDraftEditor.ts` / `DefinitionEditor.tsx` | Do not exist; current state is selected node + per-mount tab only. | Extract per-agent local state, status, validation, save, and conflict recovery so #264/#265/#266 extend panels without redefining semantics. | Tasks 4–6 sequentially. |
| `AgentDefinitionWorkbench.tsx` | Read-only prompt/model panels; `DefinitionPanel key={agent_key}` remounts; one GET on lazy admin-tab mount. | Compose extracted editor/state; retain per-agent local edits across remount/selection/tab changes; keep Output Schema/Assembly read-only and isolated testing unavailable. | Task 5 then Task 6. |
| component fixture/test and Playwright spec | Complete #260 read fixture, 90-unit-test baseline, exact browser route mock; E2E matrix already includes `agent-definition-workbench`. | Extend endpoint-specific mocks and replace only obsolete “no Save” assertion; keep Run/Approve/Publish/History/Rollback forbidden. | Tasks 4–6 sequentially. |

## Exact no-scope list

- No database model, DDL, migration, seed-manifest, bootstrap definition, release mapping, release interval, or published revision mutation.
- No Agent Test Run/evidence model, invalidation flag, evidence update/delete, readiness query, isolated execution, approval, rejection, publication, history, or rollback.
- No schema-overlay editing/validation (#264), assembly editing/policy changes (#265), or endpoint discovery/existence/connectivity/capability policy (#266).
- No `Test failed`, `Awaiting review`, or `Approved` statuses (#267).
- No runtime graph resolution, model invocation, conversation pin, trace, graph fan-out, legacy monolith, export model, feedback model, or LLM-judge change.
- No tool assignment/toggle/grant behavior, Data Analyst tool binding, or Foreman configurability.
- No autosave, debounce save, navigation save, merge algorithm, private draft, field-level collaborative merge, or last-write-wins fallback.
- No client-supplied actor, timestamp, hash, identity, revision/base ID, release data, schema overlay, or assembly rules.
- No endpoint alias normalization, URL rewrite, family upgrade, live catalog lookup, live serving call, or arbitrary URL decision.
- No broad redesign of the existing admin layout, Output Schema/Assembly panes, or isolated-testing placeholder.

## Execution pre-pass and cause baseline

Before Task 1, create the ignored `.superpowers/2026-09-22-shared-graph-draft-editing/PLAN-CORRECTIONS.md`. Record either “no corrections” or exact overrides to this plan. Re-probe, do not copy the table above:

```bash
git status --short --branch
git rev-parse HEAD
rg -n "class GraphConfiguration|read_workbench|_PERSISTED_CONTENT_FIELDS|canonical_payload|def get_db|require_admin|require_current_user" \
  src/services/graph_configuration.py \
  src/services/graph_configuration_workbench.py \
  src/services/graph_configuration_content.py \
  src/services/graph_definition_manifest.py \
  src/core/database.py src/api/routes/_authz.py src/core/user_context.py
rg -n "test_agent_definition_workbench_postgres|agent-definition-workbench" \
  .github/workflows/test.yml frontend/tests/e2e/agent-definition-workbench.spec.ts
git diff -- src/api/schemas/agent_definitions.py frontend/src/api/agentDefinitions.ts
git diff --cached -- src/api/schemas/agent_definitions.py frontend/src/api/agentDefinitions.ts
readlink frontend/node_modules
```

The accepted fresh baseline at plan time is cause-based, not merely numeric:

- Backend/workbench: **40 passed**. It covers canonical manifest/content mapping, bootstrap/read integrity, admin route confidentiality, and the existing real-PostgreSQL reader/writer lock proof; no #263 write contract exists yet.
- Frontend unit: **90 passed**. It covers the #260 read-only workbench and surrounding frontend suite; the existing “no Save Draft” assertion is expected to be replaced by #263 positive save coverage.
- Frontend typecheck: **passed**. Existing GET wire types and fixtures agree; there are no save types yet.
- PostgreSQL availability is an environmental cause, not a count: the race test must actually run against a reachable `TELLR_TEST_POSTGRES_URL`, show two distinct backend PIDs and an observed lock waiter, and must not be reported green if skipped.

After every task, compare failure causes with this list. Schema/ORM/dependency changes are outside scope; if any appear, stop and correct scope rather than accepting a same-count baseline.

---

### Task 1: Deep Draft-Write Module and Trusted Full-Content Seam

**Review question:** Does one small facade interface now own complete-content reconstruction, protected-field preservation, canonical hashing, explicit transaction/audit semantics, and lossless conflict results without duplicating the content registry or weakening the existing read aggregate?

**Files:**
- Create: `src/services/graph_configuration_draft.py`
- Modify: `src/services/graph_configuration.py:11-54`
- Modify: `src/services/graph_configuration_workbench.py:167-321`
- Create: `tests/unit/test_graph_configuration_draft.py`
- Test: `tests/unit/test_graph_definition_content_mapping.py`
- Test: `tests/unit/test_agent_definition_workbench_routes.py` (read regression only)

**Interfaces:**
- Consumes: `definition_content_from_row(row) -> DefinitionContent`, `definition_content_values(content) -> dict[str, object]`, `definition_content_hash(content) -> str`, current snapshot dataclasses, and exact aggregate rules in `_GraphConfigurationWorkbench`.
- Produces: `EditableModelDraft`, `DraftSaveResult`, generic `DraftSaveConflict[T]`, the two facade methods declared above, and a private exclusive locked-snapshot seam shared with the read module.

- [ ] **Step 1: Write hash-coverage and exact-five-field adapter tests**

Add parametrized tests that start from the Architect v1 content and use Pydantic `model_copy` with an explicit update dictionary for each in-memory serialization probe. Change each canonical path independently and assert a different `definition_content_hash` for `agent_key`, `definition_version`, `prompt_text`, all four `model` members, `schema_overlay`, `assembly_rules`, both `protected_assembly` members, and both `schema_contract` members.

`model_copy` intentionally bypasses role-assembly revalidation for the `agent_key` and assembly probes; these objects are never passed to the writer or persisted. Also assert `canonical_payload()` contains exactly the nested paths represented by all 13 `DEFINITION_CONTENT_COLUMN_NAMES`, so the test proves serialization coverage without expanding validity policy.

Add a save test with this exact candidate:

```python
candidate = EditableModelDraft(
    prompt_text="Architect draft changed by #263",
    endpoint_name=" custom-endpoint-name ",
    temperature=0.25,
    max_tokens=4096,
    top_p=0.8,
)
```

Assert the five saved values match exactly (including endpoint spaces), the other eight persisted paths equal the before-snapshot, the new candidate hash equals `definition_content_hash(definition_content_from_row(row))`, `changed is True`, lock advances `0 -> 1`, actor is exact, timestamp is timezone-aware, and all revision/release/mapping identities and values are unchanged.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run --no-sync pytest -q \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_definition_content_mapping.py
```

Expected: collection fails because `src.services.graph_configuration_draft` and the facade methods do not exist. Existing content-mapping tests remain green when selected alone.

- [ ] **Step 3: Refactor the locked read projection without changing public GET behavior**

In `graph_configuration_workbench.py`, extract private helpers with these signatures:

```text
_GraphConfigurationWorkbench._lock_current_parents(
    self, session: Session, *, exclusive: bool
) -> tuple[GraphRelease, GraphDraft]

_GraphConfigurationWorkbench._snapshot_locked_workbench(
    self,
    session: Session,
    *,
    release: GraphRelease,
    draft: GraphDraft
) -> GraphWorkbenchSnapshot

_GraphConfigurationWorkbench._read_workbench_for_draft_write(
    self,
    session: Session,
    *,
    agent_key: AgentKey
) -> GraphWorkbenchSnapshot
```

`read_workbench` calls `_lock_current_parents(exclusive=False)` and then `_snapshot_locked_workbench`. The write loader calls `_lock_current_parents(exclusive=True)`, then executes this selected-row lock before projection:

```python
selected = session.scalar(
    select(GraphDraftAgent)
    .where(
        GraphDraftAgent.graph_draft_id == draft.id,
        GraphDraftAgent.agent_key == agent_key,
    )
    .with_for_update()
)
if selected is None:
    raise GraphConfigurationIntegrityError(
        f"shared draft is missing selected role {agent_key!r}"
    )
```

The snapshot helper retains every current exact-set, base-release, role-compatible mapping, and hash assertion. Do not import the manifest or substitute defaults.

- [ ] **Step 4: Implement the cohesive writer and compose the facade**

Implement both public methods as transaction owners:

```python
def save_editable_model_draft(
    self,
    session: Session,
    *,
    agent_key: AgentKey,
    expected_lock_version: int,
    candidate: EditableModelDraft,
    actor: str,
) -> DraftSaveResult | DraftSaveConflict[EditableModelDraft]:
    self._validate_actor_lock_and_editable_candidate(
        actor, expected_lock_version, candidate
    )
    with session.begin():
        snapshot = self._read_workbench_for_draft_write(
            session, agent_key=agent_key
        )
        current = self._selected_model_node(snapshot, agent_key)
        if expected_lock_version != snapshot.draft.lock_version:
            return DraftSaveConflict(
                expected_lock_version=expected_lock_version,
                current_lock_version=snapshot.draft.lock_version,
                client_candidate=candidate,
                draft=snapshot.draft,
                definition=current.draft,
            )
        payload = current.draft.content.model_dump(mode="python")
        payload["prompt_text"] = candidate.prompt_text
        payload["model"] = {
            "endpoint_name": candidate.endpoint_name,
            "temperature": candidate.temperature,
            "max_tokens": candidate.max_tokens,
            "top_p": candidate.top_p,
        }
        content = DefinitionContent.model_validate(payload)
        return self._write_locked_content(
            session,
            snapshot=snapshot,
            current=current,
            content=content,
            actor=actor,
        )
```

`save_draft_content` derives `agent_key` from its validated `DefinitionContent`, uses the same lock-first/stale-first flow, and calls `_write_locked_content`. Before applying values it compares locked/current and proposed `agent_key`, `definition_version`, `protected_assembly`, and `schema_contract`; mismatch performs no flush.

Use `DraftContentRejected`, not `GraphConfigurationIntegrityError`, for invalid caller input. `_validate_actor_lock_and_editable_candidate` requires `type(expected_lock_version) is int`, a nonnegative version, `actor.strip()`, nonblank prompt/endpoint, `type(max_tokens) is int and max_tokens > 0`, numeric-but-not-boolean temperature/top-p, `math.isfinite`, and inclusive `[0, 1]` bounds. `save_draft_content` raises the same type for a proposed protected identity/version/key mismatch. The HTTP adapter converts only `DraftContentRejected` to `422`; persisted `GraphConfigurationIntegrityError` remains a nonleaking `500`.

`_write_locked_content` must:

```python
old_hash = current.draft.candidate_hash
new_hash = definition_content_hash(content)
for column_name, value in definition_content_values(content).items():
    setattr(selected_row, column_name, value)
selected_row.candidate_hash = new_hash
timestamp = session.scalar(select(func.current_timestamp()))
if timestamp is None:
    raise GraphConfigurationIntegrityError(
        "database did not return a transaction timestamp"
    )
if timestamp.tzinfo is None:
    timestamp = timestamp.replace(tzinfo=timezone.utc)
draft_parent.lock_version += 1
draft_parent.updated_by = actor
draft_parent.updated_at = timestamp
session.flush()
```

Return snapshots built from the flushed rows, with the selected `base_revision_id` from the active release mapping and `changed=(new_hash != old_hash)`. Actor validation requires `actor.strip()` to be nonempty; optimistic version requires a nonnegative integer and rejects `bool`.

Compose the facade as:

```python
class GraphConfiguration(
    _GraphConfigurationDraft,
    _GraphConfigurationWorkbench,
    _GraphConfigurationBootstrap,
):
    """Read, edit, or atomically bootstrap the Graph Configuration aggregate."""
```

Re-export `EditableModelDraft`, `DraftSaveResult`, `DraftSaveConflict`, and `DraftContentRejected` from `graph_configuration.py`.

- [ ] **Step 5: Add same-content, protected-invariant, validation, and rollback tests**

Assert an identical valid candidate returns `changed is False`, changes no candidate hash/content, advances the lock, and updates actor/time. Assert whitespace-only prompt/endpoint, NaN/infinity/out-of-range temperature/top-p, nonpositive/nonintegral max tokens, blank actor, and negative/bool lock versions fail with no mutation.

Call `save_draft_content` with a valid changed schema overlay to prove the generic writer carries full content through one hash/write seam. The current v1 validator intentionally admits no changed assembly; #265 will evolve that validator and then consume the same writer without changing lock/hash/audit mechanics. Separately submit changed `agent_key`, `definition_version`, protected assembly identity, and schema-contract identity and assert each is rejected without mutation.

Install a SQLAlchemy `before_flush` listener that raises `RuntimeError("forced flush failure")`; assert candidate values/hash, parent lock/actor/time, all revisions, all release mappings, and active release interval are byte-for-byte unchanged in a fresh session after the exception. Assert a stale call returns both client and server data and leaves the complete database snapshot unchanged.

- [ ] **Step 6: Run GREEN and the read-path regression**

Run:

```bash
uv run --no-sync pytest -q \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py
```

Expected: all selected tests pass; existing GET contract, confidentiality, exact topology, and corruption failures remain unchanged.

- [ ] **Step 7: Falsify the task’s tests**

Controller sabotage: temporarily assign `selected_row.candidate_hash = old_hash` after applying changed content. Confirm the marker is inside `_write_locked_content`, run `test_each_editable_field_rebuilds_the_complete_canonical_hash`, and observe a hash/content mismatch failure. Restore and observe GREEN.

Reviewer sabotage (different target): temporarily remove the protected-identity comparison for `schema_contract`. Confirm the removed guard is the executed `save_draft_content` path, run `test_trusted_full_content_writer_rejects_protected_identity_changes`, and observe RED. Restore and observe GREEN.

- [ ] **Step 8: Commit Task 1**

```bash
git add \
  src/services/graph_configuration.py \
  src/services/graph_configuration_draft.py \
  src/services/graph_configuration_workbench.py \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_definition_content_mapping.py
git commit -m "feat: add shared Graph Draft writer (#263)"
```

---

### Task 2: Real-PostgreSQL Write/Write Serialization and CI Proof

**Review question:** Do concurrent administrators serialize at the actual PostgreSQL locks so exactly one same-version write wins and the loser receives a complete stale result with no partial overwrite or deadlock?

**Files:**
- Modify: `tests/integration/test_agent_definition_workbench_postgres.py`
- Test: `.github/workflows/test.yml:410-461` (read-only unless pre-pass finds collection removed)
- Test: `tests/unit/test_ci_collects_integration_tests.py` (read-only unless pre-pass finds collection removed)

**Interfaces:**
- Consumes: Task 1 facade methods/outcomes and the existing `postgres_engine` QueuePool fixture.
- Produces: forced, observable PostgreSQL race/rollback/timestamp evidence collected by the existing `integration-graph` CI job.

- [ ] **Step 1: Write the forced two-writer race test**

Parameterize `(winner_key, loser_key)` as `("architect", "builder")` and `("builder", "architect")`. Give each thread its own `Session`, the same expected lock `0`, distinct candidates and actors, and capture `pg_backend_pid()`.

Record normalized SQL in an `after_cursor_execute` listener and assert it contains exclusive locks for both the singleton parent query and the selected `graph_draft_agent` query. Pause the winner immediately after the singleton parent `FOR UPDATE` is acquired. Start the loser, query `pg_stat_activity` from an observer connection until the loser has `wait_event_type = 'Lock'`, then release the winner. Assert:

```python
assert winner_pid != loser_pid
assert observed_waiter is True
assert isinstance(winner_outcome, DraftSaveResult)
assert isinstance(loser_outcome, DraftSaveConflict)
assert loser_outcome.expected_lock_version == 0
assert loser_outcome.current_lock_version == 1
assert loser_outcome.client_candidate == loser_candidate
assert loser_outcome.definition.content.prompt_text == winner_candidate.prompt_text
```

Reload and assert exact winner content/hash, `lock_version == 1`, winner actor/time, unchanged losing row, exact seven draft keys, exact seven release mappings, and unchanged revisions/release interval.

- [ ] **Step 2: Run the race and verify RED**

Before the first run, temporarily remove the selected `graph_draft_agent` row’s `.with_for_update()` call from Task 1’s write loader and mark the changed line `# TASK2_RED_OMIT_SELECTED_LOCK`. Confirm with `rg -n TASK2_RED_OMIT_SELECTED_LOCK src/services/graph_configuration_workbench.py` that the sabotage is on the executed path, then run:

```bash
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  uv run --no-sync pytest -q \
  tests/integration/test_agent_definition_workbench_postgres.py \
  -k "two_writers"
```

Expected: RED because the SQL assertion cannot find the required exclusive selected-row lock. Restore the Task 1 lock immediately, confirm the marker is absent, and rerun to establish GREEN before extending the assertions. If the test is skipped, PostgreSQL is unavailable and this step is not complete; use the CI PostgreSQL job or a reachable local URL.

- [ ] **Step 3: Add DB-time and rollback assertions**

Extend the statement listener to assert the writer emitted `CURRENT_TIMESTAMP`. Assert the persisted timezone-aware `updated_at` equals the timestamp returned by the database statement, not a monkeypatched Python clock.

Add a PostgreSQL `before_flush` failure test equivalent to Task 1’s rollback assertion, including unchanged parent audit fields and immutable artifacts. Run both agent-order parameters with a timeout so a deadlock fails rather than hangs.

- [ ] **Step 4: Run GREEN and prove CI collection**

Run:

```bash
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  uv run --no-sync pytest -q \
  tests/integration/test_agent_definition_workbench_postgres.py
uv run --no-sync pytest -q \
  tests/unit/test_ci_collects_integration_tests.py
```

Expected: all PostgreSQL tests execute (zero skips), both lock-order parameters observe a waiter, and the CI collection guard passes because `.github/workflows/test.yml` already names this file in `integration-graph`.

- [ ] **Step 5: Falsify the concurrency evidence**

Controller sabotage: temporarily remove `.with_for_update()` from the singleton parent query. Confirm the marker is absent from the executed SQL, run the two-writer test, and observe RED because no loser waiter is observed and/or both operations report success. Restore and observe GREEN.

Reviewer sabotage (different target): temporarily compare `expected_lock_version` only before acquiring the lock. Confirm both workers execute that pre-lock comparison, run the race, and observe RED because both accept version `0` or overwrite state. Restore and observe GREEN.

- [ ] **Step 6: Commit Task 2**

```bash
git add tests/integration/test_agent_definition_workbench_postgres.py
git commit -m "test: prove Graph Draft save serialization (#263)"
```

Do not stage `.github/workflows/test.yml` unless the pre-pass found the file absent from the existing job and the correction ledger explicitly required restoring it.

---

### Task 3: Stable Admin Save Route, Strict DTOs, and Nonleaking Authorization

**Review question:** Does the HTTP interface expose exactly five mutable fields, stable `200/409/422` envelopes, and a trusted nonblank actor while rejecting unauthorized callers before body parsing, service access, or prompt leakage?

**Files:**
- Modify: `src/api/schemas/agent_definitions.py`
- Modify: `src/api/routes/agent_definitions.py`
- Modify: `tests/unit/test_agent_definition_workbench_routes.py`

**Interfaces:**
- Consumes: Task 1 `EditableModelDraft`, `DraftSaveResult`, `DraftSaveConflict`; existing response snapshots; `get_current_user()` and router-level `require_admin`.
- Produces: strict save DTOs, stable error payloads, and `PUT /api/admin/agent-definitions/draft/{agent_key}`.

- [ ] **Step 1: Write exact route-contract tests**

Add tests for:

- changed save `200` with exact top-level keys `draft`, `definition`, `changed`, exact full definition response, lock `0 -> 1`, trusted actor, and unchanged Graph Version/release IDs;
- repeated identical save `200`, `changed: false`, and lock/audit advance;
- stale `409` exactly matching the envelope above and preserving DB state;
- one parametrized `422` case for every field/rule, including strict-number rejection and extra fields `candidate.schema_overlay`, `candidate.model.model_alias`, top-level `updated_by`, `candidate_hash`, and `release_id`;
- unknown key and `foreman` as `422` field `agent_key`, code `unknown_agent`;
- malformed JSON as the stable `$` error;
- non-admin + malformed/secret body returns only `403 {"detail":"Admin access required"}`, never calls body parsing/writer, and response text contains neither submitted prompt nor endpoint;
- admin-bypassed local request with missing or whitespace principal returns `403 {"detail":"Authenticated principal required"}` before writer access;
- persisted integrity error maps to existing nonleaking `500` without candidate/hash details.

- [ ] **Step 2: Run route tests and verify RED**

Run:

```bash
uv run --no-sync pytest -q \
  tests/unit/test_agent_definition_workbench_routes.py \
  -k "save_draft or non_admin_put or principal"
```

Expected: RED because the PUT route and DTOs do not exist.

- [ ] **Step 3: Add strict request/response models and deterministic error conversion**

Append models named:

```python
class _StrictDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EditableModelDraftModelRequest(_StrictDraftRequest):
    endpoint_name: str
    temperature: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    max_tokens: Annotated[int, Field(gt=0)]
    top_p: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class EditableModelDraftRequest(_StrictDraftRequest):
    prompt_text: str
    model: EditableModelDraftModelRequest


class DraftSaveRequest(_StrictDraftRequest):
    lock_version: Annotated[int, Field(ge=0)]
    candidate: EditableModelDraftRequest


class DraftSaveSuccessResponse(_AttributeResponse):
    draft: DraftMetadataResponse
    definition: DraftDefinitionResponse
    changed: bool


class DraftFieldErrorResponse(BaseModel):
    field: str
    code: str
    message: str


class DraftValidationErrorResponse(BaseModel):
    code: Literal["invalid_draft"]
    errors: list[DraftFieldErrorResponse]


class DraftSaveConflictServerResponse(BaseModel):
    draft: DraftMetadataResponse
    definition: DraftDefinitionResponse


class DraftSaveConflictResponse(BaseModel):
    code: Literal["stale_draft"]
    expected_lock_version: int
    current_lock_version: int
    client_candidate: EditableModelDraftRequest
    server: DraftSaveConflictServerResponse
```

Add `field_validator("prompt_text", mode="after")` and `field_validator("endpoint_name", mode="after")` methods that reject `not value.strip()` and return the accepted value unchanged. The request’s exact shape is `lock_version` and `candidate {prompt_text, model {endpoint_name, temperature, max_tokens, top_p}}`. Define a route helper that converts `json.JSONDecodeError` and Pydantic `ValidationError.errors()` into ordered dotted `DraftValidationErrorResponse` entries. Map known Pydantic codes to `blank`, `out_of_range`, `positive_integer`, `finite_number`, `strict_type`, or `extra_forbidden`, with these owned messages:

```text
Prompt text must not be blank.
Endpoint name must not be blank.
Temperature must be between 0 and 1.
Maximum tokens must be a positive integer.
Top-p must be between 0 and 1.
```

- [ ] **Step 4: Implement auth-first body parsing and outcome mapping**

Add:

```python
def require_draft_write_principal() -> str:
    actor = get_current_user()
    if actor is None or not actor.strip():
        raise HTTPException(
            status_code=403,
            detail="Authenticated principal required",
        )
    return actor
```

Use an `async def` route accepting `Request`, raw `agent_key: str`, `actor: Annotated[str, Depends(require_draft_write_principal)]`, and DB session. Parse `await request.json()` inside the handler only after router/principal dependencies succeed, validate the key against `GRAPH_V1_AGENT_KEYS`, then validate `DraftSaveRequest` and call the facade. Do not declare the Pydantic body as a FastAPI parameter, because that would return the framework’s generic validation envelope and could parse secret content before the explicit contract.

Map `DraftSaveResult` to `200`. For `DraftSaveConflict`, explicitly build the flat-to-nested projection below, then return `JSONResponse(status_code=409, content=conflict_response.model_dump(mode="json"))`:

```python
client_candidate = EditableModelDraftRequest(
    prompt_text=conflict.client_candidate.prompt_text,
    model=EditableModelDraftModelRequest(
        endpoint_name=conflict.client_candidate.endpoint_name,
        temperature=conflict.client_candidate.temperature,
        max_tokens=conflict.client_candidate.max_tokens,
        top_p=conflict.client_candidate.top_p,
    ),
)
```

Return `JSONResponse(status_code=422, content=validation_response.model_dump(mode="json"))` for request validation or `DraftContentRejected`. Map `GraphConfigurationIntegrityError` to the same stable nonleaking `500` used by GET. Actor never comes from the body.

- [ ] **Step 5: Run GREEN and full backend/workbench regression**

Run:

```bash
uv run --no-sync pytest -q \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py
```

Expected: exact `GET` remains unchanged; all PUT contract/security tests pass.

- [ ] **Step 6: Falsify security and field isolation**

Controller sabotage: temporarily add `schema_overlay: dict[str, object] | None = None` to the public request candidate. Confirm the request parser accepts it, run `test_put_rejects_every_protected_or_server_owned_field`, and observe RED. Restore and observe GREEN.

Reviewer sabotage (different target): temporarily fall back to `actor = get_current_user() or "anonymous"`. Confirm the writer receives `anonymous`, run `test_put_requires_nonblank_trusted_principal_before_write`, and observe RED. Restore and observe GREEN.

- [ ] **Step 7: Commit Task 3**

```bash
git add \
  src/api/schemas/agent_definitions.py \
  src/api/routes/agent_definitions.py \
  tests/unit/test_agent_definition_workbench_routes.py
git commit -m "feat: expose admin Graph Draft save contract (#263)"
```

---

### Task 4: Typed Save Client and Reusable Per-Agent Editor State

**Review question:** Are transport errors and all local/saved/server/conflict states represented once in reusable pure TypeScript, with exact status precedence and no implicit write mechanism?

**Files:**
- Modify: `frontend/src/api/agentDefinitions.ts`
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts`
- Modify: `frontend/tests/fixtures/mocks.ts`

**Interfaces:**
- Consumes: Task 3 exact JSON envelopes and existing `DraftDefinition`, `DraftMetadata`, `AgentKey` types.
- Produces: exported `EditableModelDraft`, save request/success/conflict/validation types, `saveDraftDefinition`, structured `AgentDefinitionApiError.payload`, and the pure state interface specified above.

- [ ] **Step 1: Write API/state RED tests**

Test that `saveDraftDefinition('architect', request)` issues exactly one `PUT` to `/api/admin/agent-definitions/draft/architect`, sends `Content-Type: application/json`, and serializes no protected or server-owned key. Test that `409` and `422` throw `AgentDefinitionApiError` preserving the typed payload object, while GET detail behavior remains compatible.

For state, assert:

```typescript
expect(draftStatus(cleanEntry)).toBe('Clean');
expect(draftStatus({ ...cleanEntry, local: changedLocal })).toBe('Unsaved');
expect(draftStatus({ ...cleanEntry, saved: changedSaved })).toBe('Needs test');
expect(draftStatus({ ...changedSavedEntry, local: changedAgain })).toBe('Unsaved');
```

Assert initialization creates independent entries for exactly seven model agents, excludes Foreman, and deep-copies nested model values. Validate blank fields, finite bounds, and positive integer tokens locally with the same messages as backend. Assert edit actions touch only one agent and never invoke `fetch`.

- [ ] **Step 2: Run focused Vitest and verify RED**

Run:

```bash
cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts
```

Expected: RED because the state module/save client types do not exist.

- [ ] **Step 3: Implement stable transport types and one-shot PUT client**

Export `EditableModelDraft` in exact wire shape:

```typescript
export interface EditableModelDraft {
  prompt_text: string;
  model: WorkbenchModel;
}
```

Add `DraftSaveRequest`, `DraftSaveSuccessResponse`, `DraftFieldError`, `DraftValidationErrorResponse`, and `DraftSaveConflictResponse` mirroring Task 3. Change `AgentDefinitionApiError` to retain `readonly payload: unknown` while continuing to derive `detail` for GET-style errors. `saveDraftDefinition` performs one direct `fetch`; it must not share `workbenchRequest` or retry automatically.

- [ ] **Step 4: Implement pure local state/status/validation**

Implement structural conversion functions between `DraftDefinition`, `EditableModelDraft`, and `EditableModelDraftForm`. `draftStatus` uses this strict order:

```typescript
if (!editableFormsEqual(entry.local, formFromDefinition(entry.saved))) return 'Unsaved';
if (entry.saved.candidate_hash === entry.publishedHash) return 'Clean';
return 'Needs test';
```

Reducer actions update one keyed entry immutably. `saveSucceeded` adopts returned draft/definition and clears selected field/conflict errors; `saveConflicted` stores both candidates without changing the local form; `keepLocal` adopts the server baseline/global lock but leaves local form; `reloadServer` adopts server baseline/local form and copies `client_candidate` to `recoveryCandidate`; restore/dismiss affect only recovery state.

- [ ] **Step 5: Run GREEN and typecheck**

Run:

```bash
cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts
cd frontend && npm run typecheck
```

Expected: focused tests and TypeScript build pass; GET callers still compile.

- [ ] **Step 6: Falsify status precedence and transport isolation**

Controller sabotage: swap `Unsaved` and hash comparisons in `draftStatus`. Confirm the dirty-changed fixture executes both conditions, run the state test, and observe RED (`Needs test` incorrectly masks `Unsaved`). Restore and observe GREEN.

Reviewer sabotage (different target): add `schema_overlay` from the saved definition to the serialized PUT candidate. Confirm it appears in the captured request JSON, run the API serialization test, and observe RED. Restore and observe GREEN.

- [ ] **Step 7: Commit Task 4**

```bash
git add \
  frontend/src/api/agentDefinitions.ts \
  frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts \
  frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts \
  frontend/tests/fixtures/mocks.ts
git commit -m "feat: add Graph Draft editor state (#263)"
```

---

### Task 5: Explicit Prompt/Model Editor with Persistent Local Drafts

**Review question:** Can an administrator edit exactly the five owned values, retain unsaved state across agent/tab/remount interactions, see truthful status, and save only through the explicit button?

**Files:**
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/useDraftEditor.ts`
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx`

**Interfaces:**
- Consumes: Task 4 reducer/state, `saveDraftDefinition`, current read-only Output Schema/Assembly rendering.
- Produces: `useDraftEditor(workbench)`, focused `DefinitionEditor`, exact five controls, explicit save, and stable state/components for #264/#265/#266.

- [ ] **Step 1: Replace the obsolete no-Save guard with positive RED tests**

Keep Run, Approve, Reject, Review & Publish, Publish, History, and Rollback forbidden. Add tests that edit all five accessible controls, switch Architect → Builder → Architect, switch all tabs, hide/show the Admin tab, and assert Architect’s values and `Unsaved` status survive.

Spy on `fetch` and assert zero PUTs after every keystroke, blur, validation, agent selection, tab selection, Admin-tab switch, rerender, and StrictMode remount. Click **Save Draft** once and assert exactly one PUT using the current global lock and exact five-field candidate.

Add success tests: changed save adopts returned server content/hash/lock, displays `Needs test`, leaves Graph Version/base release unchanged, and preserves another agent’s local unsaved form. Repeated same-content save adopts the incremented lock and `changed: false` without claiming `Clean` if candidate hash still differs from published.

- [ ] **Step 2: Run the component tests and verify RED**

Run:

```bash
cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx
```

Expected: RED because prompt/model controls, status, hook, and Save Draft do not exist.

- [ ] **Step 3: Implement the hook as the sole side-effect owner**

`useDraftEditor(workbench)` initializes `useReducer(draftEditorReducer, workbench, createDraftEditorState)` once and exports:

```typescript
{
  state,
  edit(agentKey, field, value),
  save(agentKey): Promise<void>,
  reloadServer(agentKey),
  keepLocal(agentKey),
  restoreRecovery(agentKey),
  dismissRecovery(agentKey),
}
```

`save` first calls `validateDraftForm`; invalid input dispatches `saveInvalid` and returns without fetch. Valid input dispatches `saveStarted`, awaits one `saveDraftDefinition`, then dispatches success, typed `422`, typed `409`, or a nonfield request error. No `useEffect`, timeout, blur handler, selection handler, or reducer action calls the save client.

- [ ] **Step 4: Implement the focused editor and compose it into the workbench**

`DefinitionEditor` receives the selected `ModelAgentNode`, selected `DraftEditorEntry`, and hook actions. Prompt tab renders a labelled `<textarea>`; Model tab renders labelled exact endpoint text and number inputs for Temperature, Maximum tokens, and Top-p. Output Schema and Assembly continue rendering the full server-owned read-only JSON from `entry.saved`.

Render the exact `draftStatus(entry)` near the selected agent and in graph navigation. Disable Save only while the selected entry is saving or local validation is invalid; never hide it for a valid same-content explicit save. Preserve tab state by agent in the extracted component or keep panels mounted; do not use `key={agent_key}` to discard local state. Foreman remains read-only with no Save button/status from the three-value vocabulary.

- [ ] **Step 5: Run GREEN, all frontend unit tests, and typecheck**

Run:

```bash
cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts \
  src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx
cd frontend && npm run test:unit
cd frontend && npm run typecheck
```

Expected: component/state tests pass, the frontend suite remains green, and the accepted 90-test baseline increases only by the added tests.

- [ ] **Step 6: Falsify explicit-save and per-agent persistence**

Controller sabotage: temporarily call `save(selectedAgent)` from the endpoint input `onChange`. Confirm the spy sees the executed branch, run `test_typing_navigation_and_remount_never_save`, and observe RED from unexpected PUT count. Restore and observe GREEN.

Reviewer sabotage (different target): temporarily initialize local form inside `DefinitionEditor` so it resets on agent change. Confirm the component remount executes that initializer, run `test_unsaved_values_survive_agent_and_tab_changes`, and observe RED. Restore and observe GREEN.

- [ ] **Step 7: Commit Task 5**

```bash
git add \
  frontend/src/components/Admin/AgentDefinitionWorkbench/useDraftEditor.ts \
  frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx \
  frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx \
  frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx
git commit -m "feat: edit and save Graph Draft definitions (#263)"
```

---

### Task 6: Conflict Recovery, Browser Contract, and Final Regression

**Review question:** Does the shipped browser flow preserve both stale candidates, make Reload/Keep local lossless and write-free, render field-level validation, and retain all backend/CI/security guarantees end to end?

**Files:**
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx`
- Modify: `frontend/tests/fixtures/mocks.ts`
- Modify: `frontend/tests/e2e/agent-definition-workbench.spec.ts`

**Interfaces:**
- Consumes: Tasks 3–5 stable save/conflict/error/state interfaces.
- Produces: accessible conflict comparison/recovery UI, exact backend validation rendering, Playwright request-count proof, and final #263 acceptance evidence.

- [ ] **Step 1: Write component conflict/validation RED tests**

Return a `409` where client and server prompt/endpoint differ. Assert the UI shows both candidates, expected/current locks, status `Unsaved`, and **Reload server** / **Keep local** actions.

Click **Keep local** and assert server lock/baseline update, local client form survives, no second PUT occurs, and a later manual Save uses the refreshed lock. In a separate test click **Reload server** and assert server form becomes current, no PUT occurs, the submitted candidate remains visible as a recovery copy, **Restore submitted values** makes it local/Unsaved without saving, and **Dismiss** removes only the recovery copy.

Return stable `422` errors for all five fields and assert each message is associated with its labelled input, with no opaque-only toast. Assert conflict/validation actions do not alter any other agent’s local form.

- [ ] **Step 2: Run component tests and verify RED**

Run:

```bash
cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx \
  -t "conflict|422|recovery"
```

Expected: RED because comparison/recovery UI is not rendered.

- [ ] **Step 3: Implement accessible lossless recovery UI**

Render a blocking conflict panel labelled **Draft changed on the server** with current and submitted prompt/endpoint/model values and both lock versions. Wire buttons only to reducer actions. Render `recoveryCandidate` in a separate **Submitted values retained for recovery** panel with Restore and Dismiss. Field errors use `aria-describedby` and `role="alert"`; a transport failure that is neither `409` nor `422` remains a contained request alert.

Do not fetch a fresh workbench on conflict: the `409` server object is the authoritative selected definition/lock and avoids overwriting dirty forms for other agents.

- [ ] **Step 4: Add Playwright save/no-autosave/conflict tests**

Extend the existing route mocks with `SAVE_ENDPOINT = '**/api/admin/agent-definitions/draft/*'` and captured request bodies. Browser assertions:

1. Type in all five fields, switch agent and tabs, and observe zero PUTs.
2. Save once; assert exact JSON, lock `0`, one PUT, returned lock `1`, `Needs test`, unchanged Graph Version 1.
3. Produce `409`; assert both candidates visible, Keep local performs zero extra PUTs, explicit retry uses current lock.
4. Produce `409` again; Reload uses server values, retains recovery copy, and performs zero extra PUTs.
5. Produce `422`; assert exact field message beside the input.
6. Retain existing lazy single GET, topology, Foreman, error containment, and small-viewport assertions.

- [ ] **Step 5: Run Playwright, unit/type checks, and backend regressions**

Run:

```bash
cd frontend && npx playwright test \
  tests/e2e/agent-definition-workbench.spec.ts \
  --project=chromium --workers=1
cd frontend && npm run test:unit
cd frontend && npm run typecheck
uv run --no-sync pytest -q \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py \
  tests/unit/test_ci_collects_integration_tests.py
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  uv run --no-sync pytest -q \
  tests/integration/test_agent_definition_workbench_postgres.py
```

Expected: all commands pass; PostgreSQL reports zero skips; browser PUT counts match each explicit Save only.

- [ ] **Step 6: Falsify browser recovery and backend rollback independently**

Controller sabotage: temporarily clear `client_candidate` when handling `409`. Confirm the conflict reducer executes that branch, run the Playwright conflict test, and observe RED because submitted text cannot be displayed/restored. Restore and observe GREEN.

Reviewer sabotage (different target): temporarily increment the parent lock before comparing `expected_lock_version`. Confirm the PostgreSQL loser executes that line, run the write/write race, and observe RED because stale processing mutates the lock/audit snapshot. Restore and observe GREEN.

- [ ] **Step 7: Run final scope and diff checks**

Run:

```bash
git diff --check
git diff --name-only 7897cbc01..HEAD
rg -n "autosave|debounce|Test failed|Awaiting review|Approved|schema_overlay.*DraftSaveRequest|assembly_rules.*DraftSaveRequest" \
  src/services/graph_configuration_draft.py \
  src/api/schemas/agent_definitions.py \
  src/api/routes/agent_definitions.py \
  frontend/src/api/agentDefinitions.ts \
  frontend/src/components/Admin/AgentDefinitionWorkbench
git status --short
```

Expected changed production files are limited to the draft module/facade/read refactor, admin save schema/route, and extracted workbench API/state/editor modules; no ORM, migration, manifest, runtime, evidence, publication, or package file changes appear. Matches in read response types or the explicit “no autosave” test language are allowed; public save DTOs and UI status emitters must have no forbidden scope.

- [ ] **Step 8: Commit Task 6**

```bash
git add \
  frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx \
  frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx \
  frontend/tests/fixtures/mocks.ts \
  frontend/tests/e2e/agent-definition-workbench.spec.ts
git commit -m "test: cover Graph Draft conflict recovery (#263)"
```

## Final whole-branch review handoff

After Task 6, run a whole-branch review against `7897cbc01` using the correction ledger. Require the reviewer to provide:

- a writer-by-writer table proving the route adapter and trusted full-content operation converge on one locked writer;
- a rollback ruling covering stale, validation, forced flush, and concurrent loser paths;
- a request-field table proving no protected/server-owned value enters from HTTP;
- a status/event table proving only explicit Save writes and only the three #263 statuses emit;
- a downstream ruling that #264/#265/#266 can consume the full-content writer and extracted state/components without redefining lock, audit, conflict, or hash semantics;
- a merge/no-merge verdict and every deferred finding explicitly assigned to #264, #265, #266, or #267.

The branch is complete only when the final tests above are green, all planned sabotage pairs have demonstrated RED then GREEN, PostgreSQL race tests executed rather than skipped, and `git diff --check` is clean.
