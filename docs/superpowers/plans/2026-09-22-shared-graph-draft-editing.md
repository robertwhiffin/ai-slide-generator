# Shared Graph Draft Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an administrator explicitly save prompt and model-setting edits for one Agent Definition into the shared Graph Draft, with canonical hashing, accountable optimistic concurrency, and lossless stale-edit recovery.

**Architecture:** Keep `GraphConfiguration` as the small aggregate facade and add one deep draft-write module behind it. The module reconstructs and validates complete `DefinitionContent` under exclusive aggregate locks, while the HTTP adapter accepts only the five #263-owned fields; the frontend keeps per-agent form state locally and crosses the write seam only when the administrator selects **Save Draft**.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL 15, React 19, TypeScript 5.9, Vitest, Testing Library, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` (especially §§5.4, 7.2, 10, 11.1, 13.1, 14–17), GitHub issues #258 and #263.

## Global Constraints

- The implementation fixed point is the commit that contains this corrected plan, not its parent. At execution start capture `git rev-parse HEAD` in the ignored `IMPLEMENTATION_BASE` file specified below, verify the ignored plan report names that exact commit, and use the captured value for every implementation diff/review. Separately, final #260 authority is `29e03411487476383b34101b7b34513dbb917f26`; do not weaken its bootstrap, integrity, no-manifest fallback, read-lock, immutable-release, or CI-collection guarantees.
- At execution time load `executing-plans-tellr` alongside `superpowers:subagent-driven-development`; run the plan-vs-code corrections pre-pass before Task 1 and attach the corrections ledger to every implementer/reviewer brief.
- Use only `/Users/robert.whiffin/.pyenv/shims/python` at Python 3.11 with `python -m pytest`; never run `uv`, install a package, or create a virtual environment. Stop if `.venv` exists. Leave the ignored `frontend/node_modules` symlink unchanged.
- The public save request exposes exactly `prompt_text`, exact `endpoint_name`, `temperature`, `max_tokens`, and `top_p`, plus the optimistic `lock_version`; `agent_key` is the path identity.
- A public save cannot set `agent_key`, `definition_version`, schema overlay, assembly rules, protected identities, base/revision IDs, candidate hash, audit fields, evidence, or release state.
- Validate in #263 only nonblank prompt/endpoint, exact endpoint text, finite `temperature`/`top_p` in `[0, 1]`, and positive integral `max_tokens`. Endpoint discovery, endpoint existence/connectivity, arbitrary-URL policy, and structured-output capability belong to #266.
- Reconstruct and canonical-hash the complete persisted `DefinitionContent`; never introduce a five-field hash. Preserve the reviewed v1 overlay and assembly policy unchanged.
- Every write uses one explicit transaction, exclusive locks on the singleton draft parent and selected draft-agent row, exact aggregate validation, a database transaction timestamp, and a nonblank trusted request principal.
- An explicit valid same-content save increments `lock_version` and updates audit metadata, but returns `changed: false`; evidence applicability changes only when the canonical hash changes.
- A stale save returns the stable `409` envelope defined below with one coherent locked server snapshot of all seven draft definitions, preserves the selected submitted candidate, performs no write, and never partially overwrites or misrepresents another agent or the parent audit token.
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
5. A stale response is useful aggregate data, not a failed generic detail string: it echoes the selected submitted five-field candidate and returns current draft metadata plus a role-keyed, exact-seven-definition snapshot built while the aggregate locks are held.
6. On every conflict, the client first merges all seven server baselines atomically: an entry clean against its old baseline adopts the server value as both `saved` and `local`; a locally dirty entry adopts the server value as `saved` while retaining `local`. For the selected entry, **Keep local** retains the submitted form and clears the blocking conflict; **Reload** adopts the server form and retains the submission as a visible recovery copy. Neither action writes.

## Stable interfaces and wire contracts

### Backend module interface

Create `src/services/graph_configuration_draft.py` with these public facade types and methods:

```python
from dataclasses import dataclass
from types import MappingProxyType
from typing import Generic, Mapping, TypeVar

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


@dataclass(frozen=True)
class DraftAggregateSnapshot:
    draft: DraftMetadataSnapshot
    definitions: Mapping[AgentKey, DraftDefinitionSnapshot]


ClientCandidateT = TypeVar("ClientCandidateT")


@dataclass(frozen=True)
class DraftSaveConflict(Generic[ClientCandidateT]):
    expected_lock_version: int
    current_lock_version: int
    client_candidate: ClientCandidateT
    server: DraftAggregateSnapshot


DraftSaveOutcome = DraftSaveResult | DraftSaveConflict[ClientCandidateT]


@dataclass(frozen=True)
class DraftValidationIssue:
    field: str
    code: str
    message: str


class DraftContentRejected(ValueError):
    issues: tuple[DraftValidationIssue, ...]

    def __init__(self, *issues: DraftValidationIssue) -> None:
        if not issues:
            raise ValueError("DraftContentRejected requires at least one issue")
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))

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
    agent_key: AgentKey,
    expected_lock_version: int,
    content: DefinitionContent,
    actor: str,
) -> DraftSaveResult | DraftSaveConflict[DefinitionContent]
```

`save_draft_content` is the trusted downstream seam for #264 and #265. Its explicit `agent_key` is the target row identity; callers must pass it independently from `content.agent_key`. It locks that target, forces the proposal through `DefinitionContent.model_validate(content.model_dump(mode="python"))`, and rejects a validated content key that differs from the explicit target. It may change the five model/prompt values, `schema_overlay`, or `assembly_rules`, but rejects a mismatch in `agent_key`, `definition_version`, `protected_assembly`, or `schema_contract` relative to the locked stored candidate. Both facade methods use the same private locked writer, hash function, audit update, and conflict construction.

Define the private locked carrier in `graph_configuration_workbench.py`, alongside the ORM and snapshot types it carries, so the workbench module does not import the new draft facade and no circular dependency is introduced:

```python
@dataclass
class _LockedDraftWriteAggregate:
    snapshot: GraphWorkbenchSnapshot
    release_row: GraphRelease
    draft_row: GraphDraft
    selected_row: GraphDraftAgent
    selected: ModelAgentNodeSnapshot
```

The draft module imports this private carrier from the workbench module. The private ORM interface is exact and admits no unlocked second lookup:

```text
_GraphConfigurationWorkbench._read_workbench_for_draft_write(
    self,
    session: Session,
    *,
    agent_key: AgentKey
) -> _LockedDraftWriteAggregate

_GraphConfigurationDraft._write_locked_content(
    self,
    session: Session,
    *,
    locked: _LockedDraftWriteAggregate,
    content: DefinitionContent,
    actor: str
) -> DraftSaveResult
```

The loader exclusively locks and returns the actual active `GraphRelease`, singleton `GraphDraft`, and selected `GraphDraftAgent` ORM identities, plus the exact aggregate snapshot and its selected model node. Conflict construction and mutation use those same objects. `_write_locked_content` must not call `session.get`, issue another selected-row query, or replace any returned ORM identity. It builds returned snapshots directly from `locked.draft_row`, `locked.selected_row`, and the already validated base-revision mapping in `locked.selected` after `flush()`.

`DraftAggregateSnapshot.definitions` is created as `MappingProxyType({node.agent_key: node.draft for node in snapshot.nodes if node.execution_kind == "model"})`, and its key set must equal `frozenset(GRAPH_V1_AGENT_KEYS)` before either a conflict or response is returned. It therefore carries one coherent locked server baseline for all seven roles.

`EditableModelDraft` is deliberately a domain command rather than an HTTP model. The writer itself therefore validates exact types, finiteness, bounds, and nonblank text before it locks or writes; route validation is an earlier UX/security layer, not the only correctness layer. Invalid commands raise `DraftContentRejected` with ordered `DraftValidationIssue(field, code, message)` values. `GraphConfigurationIntegrityError` remains reserved for persisted aggregate corruption.

The complete domain rejection table is authoritative; neither the writer nor its tests invent messages from Pydantic text:

| Condition | Field | Code | Message |
| --- | --- | --- | --- |
| `actor` is not a string | `actor` | `strict_type` | `Actor must be a string.` |
| `actor.strip()` is empty | `actor` | `blank` | `Actor must not be blank.` |
| lock is `bool` or not `int` | `lock_version` | `strict_type` | `Lock version must be an integer.` |
| lock is below zero | `lock_version` | `out_of_range` | `Lock version must be greater than or equal to 0.` |
| target key is not in `GRAPH_V1_AGENT_KEYS` | `agent_key` | `unknown_agent` | `Agent key must identify an editable model role.` |
| editable candidate is not `EditableModelDraft` | `candidate` | `strict_type` | `Candidate must be an editable model draft.` |
| prompt is not a string | `candidate.prompt_text` | `strict_type` | `Prompt text must be a string.` |
| prompt is whitespace-only | `candidate.prompt_text` | `blank` | `Prompt text must not be blank.` |
| endpoint is not a string | `candidate.model.endpoint_name` | `strict_type` | `Endpoint name must be a string.` |
| endpoint is whitespace-only | `candidate.model.endpoint_name` | `blank` | `Endpoint name must not be blank.` |
| temperature is `bool` or not `int`/`float` | `candidate.model.temperature` | `strict_type` | `Temperature must be a number.` |
| temperature is NaN/infinite | `candidate.model.temperature` | `finite_number` | `Temperature must be finite.` |
| temperature is outside `[0, 1]` | `candidate.model.temperature` | `out_of_range` | `Temperature must be between 0 and 1.` |
| max tokens is `bool` or not `int` | `candidate.model.max_tokens` | `strict_type` | `Maximum tokens must be an integer.` |
| max tokens is below one | `candidate.model.max_tokens` | `positive_integer` | `Maximum tokens must be a positive integer.` |
| top-p is `bool` or not `int`/`float` | `candidate.model.top_p` | `strict_type` | `Top-p must be a number.` |
| top-p is NaN/infinite | `candidate.model.top_p` | `finite_number` | `Top-p must be finite.` |
| top-p is outside `[0, 1]` | `candidate.model.top_p` | `out_of_range` | `Top-p must be between 0 and 1.` |
| trusted content is not `DefinitionContent` | `content` | `strict_type` | `Content must be a DefinitionContent value.` |
| forced `model_dump`/`model_validate` round trip fails | `content` | `invalid_content` | `Draft content must satisfy the DefinitionContent contract.` |
| validated content key differs from explicit target | `agent_key` | `immutable_field` | `Agent key must match the targeted draft definition.` |
| definition version differs from locked target | `definition_version` | `immutable_field` | `Definition version is immutable in a draft save.` |
| protected assembly differs from locked target | `protected_assembly` | `immutable_field` | `Protected assembly identity is immutable in a draft save.` |
| schema contract differs from locked target | `schema_contract` | `immutable_field` | `Schema contract identity is immutable in a draft save.` |

`save_editable_model_draft` accumulates applicable issues in the table order through top-p and raises once before locking. `save_draft_content` validates the common actor/lock/target rows in table order, then locks the explicit target; content type/round-trip and immutable comparisons produce issues in the remaining table order before the stale-version comparison. A stale valid proposal returns conflict, while invalid content never masquerades as a conflict. Each Step 5 parametrized case asserts the exact tuple shown here.

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

Stale `409` projects the flat domain command into the nested request shape and carries the complete locked server candidate set:

```typescript
interface DraftSaveConflictResponse {
  code: 'stale_draft';
  expected_lock_version: number;
  current_lock_version: number;
  client_candidate: EditableModelDraft;
  server: {
    draft: DraftMetadata;
    definitions: Record<AgentKey, DraftDefinition>;
  };
}
```

`server.definitions` has exactly the seven `AgentKey` properties (`architect`, `data_analyst`, `builder`, `build_reviewer`, `fixer`, `fix_reviewer`, `deck_reviewer`) serialized from one locked `DraftAggregateSnapshot`. Missing, extra, or duplicate role keys are an integrity failure, never a partial `409`.

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

### Frontend transport runtime interface

TypeScript declarations are not response validation. `frontend/src/api/agentDefinitions.ts` therefore exports pure parsers and one distinct invalid-body error:

```typescript
export class InvalidDraftSaveResponseError extends Error {}

export function parseDraftSaveSuccessResponse(
  value: unknown,
): DraftSaveSuccessResponse | null;
export function parseDraftSaveConflictResponse(
  value: unknown,
): DraftSaveConflictResponse | null;
export function parseDraftValidationErrorResponse(
  value: unknown,
): DraftValidationErrorResponse | null;
```

The parsers use `isPlainRecord`, `hasExactKeys`, `isFiniteNumber`, `isInteger`, and the literal `AGENT_KEYS` tuple. They accept no class instances/arrays where a record is required and validate these exact shapes recursively:

| Parser node | Exact required keys and value rules |
| --- | --- |
| `DraftMetadata` | `draft_id`, `base_release_id`, `base_version_number` positive integers; `lock_version` nonnegative integer; `updated_by`, `updated_at` strings |
| editable model | exact `endpoint_name`, `temperature`, `max_tokens`, `top_p`; string, finite `[0,1]`, positive integer, finite `[0,1]` respectively |
| editable candidate | exact `prompt_text`, `model`; string plus parsed editable model |
| schema overlay | exact `field_overrides`, `additional_optional_fields`; plain record plus string array |
| assembly rules | exact `format_version`, `separator`, `blocks`; literal `1`, literal `"\n\n"`, and an array where every block has the exact keys/literals of the existing `AssemblyBlock` union |
| content identity | exact `version`, `digest`; positive integer and lowercase 64-hex digest |
| draft definition | exact `base_revision_id`, `candidate_hash`, `definition_version`, `prompt_text`, `model`, `schema_overlay`, `assembly_rules`, `protected_assembly`, `schema_contract`; positive IDs/version, lowercase 64-hex hash, and recursively parsed nested values |
| `200` | exact `draft`, `definition`, `changed`; parsed metadata/definition and boolean |
| conflict server | exact `draft`, `definitions`; definitions is a plain record whose key set equals `AGENT_KEYS` and whose seven values parse as draft definitions |
| `409` | exact `code`, `expected_lock_version`, `current_lock_version`, `client_candidate`, `server`; literal `stale_draft`, nonnegative integer locks, parsed candidate/server, and `current_lock_version === server.draft.lock_version` |
| one field error | exact `field`, `code`, `message`; three strings |
| `422` | exact `code`, `errors`; literal `invalid_draft` and a nonempty array of parsed field errors |

Inside `parseDraftSaveConflictResponse`, after parsing `server.definitions` as a plain record, the exact-set gate is the literal line `if (!hasExactKeys(definitions, AGENT_KEYS)) return null;`; only then are the seven values parsed.

`saveDraftDefinition` reads JSON once. Status `200`, `409`, or `422` must pass its matching parser before return/throw; a malformed, six-role, eight-role, mistyped, array, `null`, or other non-object body throws `InvalidDraftSaveResponseError`. A valid `409`/`422` is preserved as the parsed `AgentDefinitionApiError.payload`. A non-JSON non-contract HTTP failure such as `500` keeps the fixed status/status-text message. The hook catches `InvalidDraftSaveResponseError` and dispatches matching `saveFailed` with `Unable to save draft because the server response was invalid.`; reducers never see an unparsed body.

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
  recoveryForm: EditableModelDraftForm | null;
  requestError: string | null;
}

export interface PendingDraftSave {
  requestId: number;
  agentKey: AgentKey;
  expectedLockVersion: number;
  submittedCandidate: EditableModelDraft;
}

export interface DraftEditorState {
  draft: DraftMetadata;
  byAgent: Record<AgentKey, DraftEditorEntry>;
  pendingSave: PendingDraftSave | null;
}

export function createDraftEditorState(
  workbench: AgentDefinitionWorkbenchResponse,
): DraftEditorState;
export function draftStatus(entry: DraftEditorEntry): DraftStatus;
export function validateDraftForm(form: EditableModelDraftForm):
  | { ok: true; candidate: EditableModelDraft }
  | { ok: false; errors: Partial<Record<EditableDraftField, string>> };
```

The reducer/hook actions are `edit`, `saveStarted`, `saveSucceeded`, `saveInvalid`, `saveRejected`, `saveConflicted`, `saveFailed`, `reloadServer`, `keepLocal`, `restoreRecovery`, and `dismissRecovery`. Save lifecycle actions have these exact payloads:

```typescript
{ type: 'saveStarted'; pending: PendingDraftSave }
{ type: 'saveSucceeded'; requestId: number; result: DraftSaveSuccessResponse }
{ type: 'saveRejected'; requestId: number; error: DraftValidationErrorResponse }
{ type: 'saveConflicted'; requestId: number; conflict: DraftSaveConflictResponse }
{ type: 'saveFailed'; requestId: number; message: string }
```

`pendingSave` is the one aggregate-wide write gate because `draft.lock_version` is aggregate-wide. `saveStarted` is a no-op unless `pendingSave === null`; the hook also checks before allocating an ID or calling `fetch`. While non-null, every role's Save button is disabled and attempts to save another role issue zero PUTs. The five form controls remain editable, so the reducer must preserve edits made after submission.

Every completion action first checks `state.pendingSave?.requestId === action.requestId`; a stale/duplicate response returns the identical state object. A current success must have `result.draft.lock_version === pending.expectedLockVersion + 1` and must not be lower than `state.draft.lock_version`. A current conflict must have `current_lock_version === server.draft.lock_version`, must be greater than `pending.expectedLockVersion`, and must not be lower than `state.draft.lock_version`. Any violation is the fixed invalid-response failure: clear `pendingSave`, set only the pending role's `requestError`, and preserve all draft/saved/local/conflict/recovery values. No transition decreases `state.draft.lock_version`.

For a matching success, adopt the returned server definition as `saved`; replace `local` only when it still equals `formFromCandidate(pending.submittedCandidate)`. Thus A2 submitted followed by local A3 resolves to `saved=A2`, `local=A3`, `Unsaved`. For a matching conflict, merge all seven server baselines as specified above, but preserve the selected role's current local form even when it has advanced beyond the submitted candidate. `reloadServer` copies that current `EditableModelDraftForm` (A3, including temporarily invalid input) to `recoveryForm` before adopting the server form; it never substitutes the older submitted A2. Restore/dismiss operate on `recoveryForm` only.

`saveRejected` maps the current `422`, clears `pendingSave`, and changes only the pending entry's field errors. `saveFailed` clears `pendingSave`, sets only the pending entry's `requestError`, performs no retry, and leaves every draft/saved/local/hash/conflict/recovery value unchanged. `requestError` clears on that entry’s next `edit` or `saveStarted`, and on its matching success/conflict; another role’s action cannot clear it. Later UI tickets consume these exports rather than inventing another lock, hash, pending-save, conflict, request-error, or autosave model.

## Plan-vs-code shared interface and file table

All “verified” entries below were re-probed on 2026-09-22 before the correction commit containing this plan; executors re-run the commands in the execution pre-pass at the captured implementation fixed point because the plan is not runtime evidence.

| Shared seam/file | Verified current fact | #263 change and stable handoff | Ordering |
| --- | --- | --- | --- |
| `src/services/graph_configuration.py` | `GraphConfiguration(_GraphConfigurationWorkbench, _GraphConfigurationBootstrap)` is the only public facade. | Compose `_GraphConfigurationDraft`; re-export the draft types only. #264/#265 call `save_draft_content(agent_key=..., content=...)`; routes call `save_editable_model_draft`. | Task 1 only. |
| `src/services/graph_configuration_workbench.py` | `read_workbench(Session) -> GraphWorkbenchSnapshot` holds shared parent locks and validates singleton, active base, exact seven mappings, compatible revisions, exact seven draft rows, and hashes. | Extract private “parents locked → validate/project snapshot” logic; keep public read behavior byte-for-byte equivalent; return `_LockedDraftWriteAggregate` containing the locked release/draft/selected ORM rows and exact snapshot. | Task 1 before PostgreSQL tests. |
| `src/services/graph_configuration_content.py` | `_PERSISTED_CONTENT_FIELDS` exactly equals all 13 ORM content columns; row reconstruction and canonical hash validation already centralize semantic content. | Reuse unchanged. All writes apply `definition_content_values`; no second field registry. | Read-only in every task. |
| `src/services/graph_definition_manifest.py` | `DefinitionContent.canonical_payload()` includes agent/version, five fields, overlay, assembly, and both protected identities; finite decimals normalize; assembly is still v1-closed. | Reuse unchanged. #263 must not broaden overlay/assembly. | Read-only in every task. |
| `src/database/models/graph_configuration.py` | Draft id check is `id = 1`; child PK is `(graph_draft_id, agent_key)`; content checks cover nonblank text and numeric ranges; releases/revisions are immutable artifacts. | No schema or migration. Writer updates one `graph_draft_agent` and the singleton `graph_draft` only. | Read-only in every task. |
| `src/services/graph_configuration_draft.py` | Does not exist. | Cohesive lock/validate/rebuild/hash/audit/conflict/rollback module; trusted full-content handoff. | Create Task 1; exercise Task 2. |
| `src/api/schemas/agent_definitions.py` | GET response flattens the shared content snapshot and forbids extras. | Append strict write/request/success/409/422 types; do not alter GET shape. | Task 3. |
| `src/api/routes/agent_definitions.py` | Router-level `Depends(require_admin)` protects GET; `get_db` closes but does not commit. | Add one `PUT`; parse body only after auth/principal dependencies; writer owns transaction. | Task 3. |
| `src/core/user_context.py` / `_authz.py` | Production admin check fails closed, local/test admin bypass exists, and `require_current_user()` raises a runtime error rather than an HTTP contract. | Reuse `get_current_user()` in a route-local `require_draft_write_principal()` returning stable `403`; never accept actor from JSON. | Task 3; no edits to these files. |
| `tests/integration/test_agent_definition_workbench_postgres.py` | Real QueuePool/PostgreSQL test proves reader/writer waiting; CI `integration-graph` already names this file. | Add forced two-writer same-version interleavings and rollback/timestamp assertions. No CI workflow edit is required unless the pre-pass disproves collection. | Task 2. |
| `frontend/src/api/agentDefinitions.ts` | GET types/client only; StrictMode read coalescing is deliberate. | Add stable save types/client and preserve structured error JSON. Never coalesce writes. | Task 4. |
| `draftEditorState.ts` / `useDraftEditor.ts` / `DefinitionEditor.tsx` | Do not exist; current state is selected node + per-mount tab only. | Extract per-agent local state plus one aggregate `pendingSave`, monotonic response ordering, status, validation, save, and lossless conflict recovery so #264/#265/#266 extend panels without redefining semantics. | Tasks 4–6 sequentially. |
| `AgentDefinitionWorkbench.tsx` | Read-only prompt/model panels; `DefinitionPanel key={agent_key}` remounts; one GET on lazy admin-tab mount. | Compose extracted editor/state; retain per-agent local edits across definition selection/tab changes; keep Output Schema/Assembly read-only and isolated testing unavailable. | Task 5 then Task 6. |
| `frontend/src/components/Admin/AdminPage.tsx` | The workbench is absent before first visit and unmounts whenever `activeTab !== 'agent_definitions'`. | Track first visit, preserve no-GET-before-visit, then keep the workbench mounted inside the hidden tabpanel so local editor state survives Admin-tab switches. | Task 5. |
| component fixture/test and Playwright spec | Complete #260 read fixture, 90-unit-test baseline, exact browser route mock; E2E matrix already includes `agent-definition-workbench`. | Extend endpoint-specific mocks and replace only obsolete “no Save” assertion; keep Run/Approve/Publish/History/Rollback forbidden. | Tasks 4–6 sequentially. |

## Exact no-scope list

- No database model, DDL, migration, seed-manifest, bootstrap definition, release mapping, release interval, or published revision mutation.
- No Agent Test Run/evidence model, invalidation flag, evidence update/delete, readiness query, isolated execution, approval, rejection, publication, history, or rollback.
- No schema-overlay editing/validation (#264), assembly editing/policy changes (#265), or endpoint discovery/existence/connectivity/capability policy (#266).
- No `Test failed`, `Awaiting review`, or `Approved` statuses (#267).
- No runtime graph resolution, model invocation, conversation pin, trace, graph fan-out, legacy monolith, export model, feedback model, or LLM-judge change.
- No tool assignment/toggle/grant behavior, Data Analyst tool binding, or Foreman configurability.
- No autosave, debounce save, navigation save, server-side content merge, private draft, field-level collaborative merge, or last-write-wins fallback. The required client merge only reconciles the coherent seven-role server baselines with already-local dirty forms; it never synthesizes field values or writes.
- No client-supplied actor, timestamp, hash, identity, revision/base ID, release data, schema overlay, or assembly rules.
- No endpoint alias normalization, URL rewrite, family upgrade, live catalog lookup, live serving call, or arbitrary URL decision.
- No broad redesign of the existing admin layout, Output Schema/Assembly panes, or isolated-testing placeholder.

## Execution pre-pass and cause baseline

Before Task 1, create the ignored `.superpowers/2026-09-22-shared-graph-draft-editing/PLAN-CORRECTIONS.md` and `IMPLEMENTATION_BASE`. Record either “no corrections” or exact overrides in the ledger. `IMPLEMENTATION_BASE` contains the full SHA of the commit that contains this corrected plan; it is immutable for the execution even as `HEAD` advances. Re-probe, do not copy the table above:

```bash
git status --short --branch
implementation_base="$(git rev-parse HEAD)"
test -n "$implementation_base"
rg -F "**Corrected plan commit:** \`$implementation_base\`" \
  .superpowers/issue-263-plan-report.md
mkdir -p .superpowers/2026-09-22-shared-graph-draft-editing
printf '%s\n' "$implementation_base" > \
  .superpowers/2026-09-22-shared-graph-draft-editing/IMPLEMENTATION_BASE
test "$(cat .superpowers/2026-09-22-shared-graph-draft-editing/IMPLEMENTATION_BASE)" = \
  "$implementation_base"
git merge-base --is-ancestor 29e03411487476383b34101b7b34513dbb917f26 HEAD
test ! -e .venv
test "$(command -v python)" = "/Users/robert.whiffin/.pyenv/shims/python"
python --version | rg '^Python 3\.11\.'
python -c 'import sys; assert sys.version_info[:2] == (3, 11); print(sys.executable)'
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

The exact cause baseline at the captured implementation fixed point is:

```bash
python -m pytest -q \
  tests/unit/test_graph_definition_manifest.py \
  tests/unit/test_graph_configuration_models.py \
  tests/unit/test_graph_configuration_bootstrap.py \
  tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py \
  tests/integration/test_graph_configuration_bootstrap_postgres.py \
  tests/integration/test_graph_configuration_constraints_postgres.py \
  tests/integration/test_agent_definition_workbench_postgres.py
```

Result: **95 passed, 0 failed, 0 skipped** in 14.78s. This exact file set covers manifest/hash policy, ORM constraints, bootstrap/integrity, content mapping, admin GET confidentiality/no-fallback behavior, PostgreSQL bootstrap/constraints, and the real reader/writer lock. Warning causes only: existing Pydantic class-config/validator deprecations, `langchain-community` sunset notice, and existing route-import Pydantic deprecations.

```bash
python -m pytest -q \
  tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py \
  tests/integration/test_agent_definition_workbench_postgres.py
```

Result: **21 passed, 0 failed, 0 skipped** in 1.63s. This is the narrow content/route/real-PostgreSQL workbench cause set used after backend tasks.

```bash
(cd frontend && npm run test:unit)
(cd frontend && npm run typecheck)
```

Results: **9 files / 90 tests passed** in 2.43s; typecheck passed. Warning causes only: stale `baseline-browser-mapping` and Browserslist data. The existing “no Save Draft” assertion is expected to be replaced by #263 positive save coverage; no other baseline cause may change silently.

PostgreSQL availability is an environmental cause, not a count: the race test must actually run against a reachable `TELLR_TEST_POSTGRES_URL`, show two distinct backend PIDs and an observed lock waiter, and must not be reported green if skipped. After every Python command, re-run `test ! -e .venv`; if it fails, stop and remove nothing until the controller inspects the unexpected environment mutation.

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
python -m pytest -q \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_definition_content_mapping.py
```

Expected: collection fails because `src.services.graph_configuration_draft` and the facade methods do not exist. Existing content-mapping tests remain green when selected alone.

- [ ] **Step 3: Refactor the locked read projection without changing public GET behavior**

In `graph_configuration_workbench.py`, define `_LockedDraftWriteAggregate` exactly as specified in the stable interface above and extract private helpers with these signatures:

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
) -> _LockedDraftWriteAggregate
```

`read_workbench` calls `_lock_current_parents(exclusive=False)` and then `_snapshot_locked_workbench`. `_lock_current_parents` uses this exact declared statement symbol so Task 2 can sabotage only the lock assignment without breaking syntax:

```python
parent_statement = (
    select(GraphRelease, GraphDraft)
    .select_from(GraphRelease)
    .join(GraphDraft, true())
    .where(GraphRelease.effective_to.is_(None))
)
if exclusive:
    parent_statement = parent_statement.with_for_update(
        of=(GraphRelease, GraphDraft)
    )
else:
    parent_statement = parent_statement.with_for_update(
        read=True,
        of=(GraphRelease, GraphDraft),
    )
parent_rows = session.execute(parent_statement).all()
```

The write loader calls `_lock_current_parents(exclusive=True)`, then executes this selected-row lock before projection, again with an explicit symbol:

```python
selected_statement = (
    select(GraphDraftAgent)
    .where(
        GraphDraftAgent.graph_draft_id == draft.id,
        GraphDraftAgent.agent_key == agent_key,
    )
)
selected_statement = selected_statement.with_for_update()
selected = session.scalar(selected_statement)
if selected is None:
    raise GraphConfigurationIntegrityError(
        f"shared draft is missing selected role {agent_key!r}"
    )
```

The snapshot helper retains every current exact-set, base-release, role-compatible mapping, and hash assertion. The write loader returns `_LockedDraftWriteAggregate(snapshot=..., release_row=release, draft_row=draft, selected_row=selected, selected=selected_node)` and verifies `selected_node.agent_key == selected.agent_key == agent_key`. Do not import the manifest, substitute defaults, or issue an unlocked re-query after returning this object.

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
        actor, expected_lock_version, agent_key, candidate
    )
    with session.begin():
        locked = self._read_workbench_for_draft_write(
            session, agent_key=agent_key
        )
        if expected_lock_version != locked.snapshot.draft.lock_version:
            return DraftSaveConflict(
                expected_lock_version=expected_lock_version,
                current_lock_version=locked.snapshot.draft.lock_version,
                client_candidate=candidate,
                server=self._draft_aggregate_snapshot(locked.snapshot),
            )
        payload = locked.selected.draft.content.model_dump(mode="python")
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
            locked=locked,
            content=content,
            actor=actor,
        )
```

Implement the trusted method with the independent target and forced round trip:

```python
def save_draft_content(
    self,
    session: Session,
    *,
    agent_key: AgentKey,
    expected_lock_version: int,
    content: DefinitionContent,
    actor: str,
) -> DraftSaveResult | DraftSaveConflict[DefinitionContent]:
    self._validate_common(actor, expected_lock_version, agent_key)
    if not isinstance(content, DefinitionContent):
        raise DraftContentRejected(
            DraftValidationIssue(
                "content", "strict_type", "Content must be a DefinitionContent value."
            )
        )
    with session.begin():
        locked = self._read_workbench_for_draft_write(
            session, agent_key=agent_key
        )
        try:
            validated = DefinitionContent.model_validate(
                content.model_dump(mode="python")
            )
        except (TypeError, ValueError) as exc:
            raise DraftContentRejected(
                DraftValidationIssue(
                    "content",
                    "invalid_content",
                    "Draft content must satisfy the DefinitionContent contract.",
                )
            ) from exc
        issues = self._immutable_content_issues(
            target_agent_key=agent_key,
            current=locked.selected.draft.content,
            proposed=validated,
        )
        if issues:
            raise DraftContentRejected(*issues)
        if expected_lock_version != locked.snapshot.draft.lock_version:
            return DraftSaveConflict(
                expected_lock_version=expected_lock_version,
                current_lock_version=locked.snapshot.draft.lock_version,
                client_candidate=validated,
                server=self._draft_aggregate_snapshot(locked.snapshot),
            )
        return self._write_locked_content(
            session, locked=locked, content=validated, actor=actor
        )
```

`_immutable_content_issues` compares `proposed.agent_key` to the explicit `target_agent_key` first, then loops over the exact `_IMMUTABLE_DRAFT_FIELDS = ("definition_version", "protected_assembly", "schema_contract")`; it emits the table's literal issues in that order. It never chooses the target from the proposal. Any rejection performs no flush.

Use `DraftContentRejected`, not `GraphConfigurationIntegrityError`, for invalid caller input. `_validate_common` and `_validate_actor_lock_and_editable_candidate` implement the complete literal table above and accumulate issues in its declared order. The HTTP adapter projects `exc.issues` in order to `DraftFieldErrorResponse`; persisted `GraphConfigurationIntegrityError` remains a nonleaking `500`.

`_write_locked_content` must:

```python
old_hash = locked.selected.draft.candidate_hash
new_hash = definition_content_hash(content)
for column_name, value in definition_content_values(content).items():
    setattr(locked.selected_row, column_name, value)
locked.selected_row.candidate_hash = new_hash
timestamp = session.scalar(select(func.current_timestamp()))
if timestamp is None:
    raise GraphConfigurationIntegrityError(
        "database did not return a transaction timestamp"
    )
if timestamp.tzinfo is None:
    timestamp = timestamp.replace(tzinfo=timezone.utc)
locked.draft_row.lock_version += 1
locked.draft_row.updated_by = actor
locked.draft_row.updated_at = timestamp
session.flush()
```

Return snapshots built directly from the flushed `locked.draft_row` and `locked.selected_row`, with the selected `base_revision_id` from `locked.selected.draft.base_revision_id` and `changed=(new_hash != old_hash)`. Actor validation requires `actor.strip()` to be nonempty; optimistic version requires a nonnegative integer and rejects `bool`. There is no `session.get()` or second selected-row `SELECT` in the write path.

Compose the facade as:

```python
class GraphConfiguration(
    _GraphConfigurationDraft,
    _GraphConfigurationWorkbench,
    _GraphConfigurationBootstrap,
):
    """Read, edit, or atomically bootstrap the Graph Configuration aggregate."""
```

Re-export `EditableModelDraft`, `DraftAggregateSnapshot`, `DraftSaveResult`, `DraftSaveConflict`, `DraftValidationIssue`, and `DraftContentRejected` from `graph_configuration.py`.

- [ ] **Step 5: Add same-content, protected-invariant, validation, and rollback tests**

Assert an identical valid candidate returns `changed is False`, changes no candidate hash/content, advances the lock, and updates actor/time. Assert whitespace-only prompt/endpoint, NaN/infinity/out-of-range temperature/top-p, nonpositive/nonintegral max tokens, blank actor, and negative/bool lock versions fail with no mutation.

Call `save_draft_content(agent_key="architect", ...)` with a valid Architect changed schema overlay to prove the generic writer carries full content through one hash/write seam. The current v1 validator intentionally admits no changed assembly; #265 will evolve that validator and then consume the same writer without changing lock/hash/audit mechanics. Pass a valid Builder `DefinitionContent` with `agent_key="architect"` and assert the exact `agent_key/immutable_field` issue with no mutation. Use `model_copy` to construct invalid content and prove the forced dump/validate round trip returns the exact `content/invalid_content` issue. Separately submit changed `definition_version`, protected assembly identity, and schema-contract identity and assert each exact table issue without mutation.

Install a SQLAlchemy `before_flush` listener that raises `RuntimeError("forced flush failure")`; assert candidate values/hash, parent lock/actor/time, all revisions, all release mappings, and active release interval are byte-for-byte unchanged in a fresh session after the exception. Assert every invalid `DraftContentRejected` has the exact ordered issues. Assert a stale call returns the client candidate plus an exact-seven `server.definitions` mapping from the locked snapshot and leaves the complete database snapshot unchanged.

- [ ] **Step 6: Run GREEN and the read-path regression**

Run:

```bash
python -m pytest -q \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py
```

Expected: all selected tests pass; existing GET contract, confidentiality, exact topology, and corruption failures remain unchanged.

- [ ] **Step 7: Falsify the task’s tests**

Controller sabotage: replace `locked.selected_row.candidate_hash = new_hash` with the line below, confirm the marker, run the named node, then restore the original line and rerun GREEN:

```python
locked.selected_row.candidate_hash = old_hash  # TASK1_CONTROLLER_HASH_SABOTAGE
```

```bash
rg -n 'TASK1_CONTROLLER_HASH_SABOTAGE' src/services/graph_configuration_draft.py
python -m pytest -q \
  tests/unit/test_graph_configuration_draft.py::test_each_editable_field_rebuilds_the_complete_canonical_hash
```

Expected sabotage result: RED because persisted content and candidate hash diverge.

Reviewer sabotage (different target): comment out only the `schema_contract` tuple member as shown, confirm the marker, run the named node, then restore the member and rerun GREEN:

```python
_IMMUTABLE_DRAFT_FIELDS = (
    "definition_version",
    "protected_assembly",
    # "schema_contract",  # TASK1_REVIEWER_IDENTITY_SABOTAGE
)
```

```bash
rg -n 'TASK1_REVIEWER_IDENTITY_SABOTAGE' src/services/graph_configuration_draft.py
python -m pytest -q \
  tests/unit/test_graph_configuration_draft.py::test_trusted_full_content_writer_rejects_protected_identity_changes
```

Expected sabotage result: RED because a changed schema-contract identity is accepted. Remove every sabotage marker and rerun the Task 1 GREEN command.

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

Before either thread starts, capture `original_by_key: dict[AgentKey, DefinitionContent]` from a locked/read snapshot. The winner candidate changes only `winner_key`; the loser candidate changes only `loser_key`.

Record normalized SQL in an `after_cursor_execute` listener and assert it contains exclusive locks for both the singleton parent query and the selected `graph_draft_agent` query. Pause the winner immediately after the singleton parent `FOR UPDATE` is acquired. Start the loser, query `pg_stat_activity` from an observer connection until the loser has `wait_event_type = 'Lock'`, then release the winner. Assert:

```python
assert winner_pid != loser_pid
assert observed_waiter is True
assert isinstance(winner_outcome, DraftSaveResult)
assert isinstance(loser_outcome, DraftSaveConflict)
assert loser_outcome.expected_lock_version == 0
assert loser_outcome.current_lock_version == 1
assert loser_outcome.client_candidate == loser_candidate
assert set(loser_outcome.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
assert (
    loser_outcome.server.definitions[winner_key].content.prompt_text
    == winner_candidate.prompt_text
)
assert (
    loser_outcome.server.definitions[loser_key].content
    == original_by_key[loser_key]
)
```

Reload and assert exact winner content/hash, `lock_version == 1`, winner actor/time, unchanged losing row, exact seven draft keys, exact seven release mappings, and unchanged revisions/release interval. The conflict’s `server.draft` equals the reloaded parent metadata; every `server.definitions[key]` equals the same reload’s candidate for that key.

- [ ] **Step 2: Run the race and verify RED**

Before the first run, replace the declared line `selected_statement = selected_statement.with_for_update()` with `selected_statement = selected_statement  # TASK2_RED_OMIT_SELECTED_LOCK`. Confirm the unique marker with `rg -n 'TASK2_RED_OMIT_SELECTED_LOCK' src/services/graph_configuration_workbench.py`, then run:

```bash
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  python -m pytest -q \
  tests/integration/test_agent_definition_workbench_postgres.py \
  -k "two_writers"
```

Expected: RED because the SQL assertion cannot find the required exclusive selected-row lock. Restore the exact `.with_for_update()` call immediately, confirm `! rg -n 'TASK2_RED_OMIT_SELECTED_LOCK' src/services/graph_configuration_workbench.py`, and rerun the same command to establish GREEN before extending the assertions. If the test is skipped, PostgreSQL is unavailable and this step is not complete; use the CI PostgreSQL job or a reachable local URL.

- [ ] **Step 3: Add DB-time and rollback assertions**

Extend the statement listener to assert the writer emitted `CURRENT_TIMESTAMP`. Assert the persisted timezone-aware `updated_at` equals the timestamp returned by the database statement, not a monkeypatched Python clock.

Add a PostgreSQL `before_flush` failure test equivalent to Task 1’s rollback assertion, including unchanged parent audit fields and immutable artifacts. Run both agent-order parameters with a timeout so a deadlock fails rather than hangs.

- [ ] **Step 4: Run GREEN and prove CI collection**

Run:

```bash
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  python -m pytest -q \
  tests/integration/test_agent_definition_workbench_postgres.py
python -m pytest -q \
  tests/unit/test_ci_collects_integration_tests.py
```

Expected: all PostgreSQL tests execute (zero skips), both lock-order parameters observe a waiter, and the CI collection guard passes because `.github/workflows/test.yml` already names this file in `integration-graph`.

- [ ] **Step 5: Falsify the concurrency evidence**

Controller sabotage: in the exact `if exclusive:` branch declared by Task 1, replace the complete three-line lock assignment with the no-op line below, confirm the marker, and run the race node. Restore the declared assignment and rerun GREEN.

```python
parent_statement = parent_statement  # TASK2_CONTROLLER_PARENT_LOCK_SABOTAGE
```

```bash
rg -n 'TASK2_CONTROLLER_PARENT_LOCK_SABOTAGE' src/services/graph_configuration_workbench.py
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  python -m pytest -q tests/integration/test_agent_definition_workbench_postgres.py \
  -k 'two_writers'
```

Expected sabotage result: RED because the loser is not observed waiting at the aggregate linearization lock and/or both writes succeed.

Reviewer sabotage (different target): inside the declared `save_editable_model_draft`, replace its post-lock stale condition with `if False and expected_lock_version != locked.snapshot.draft.lock_version:  # TASK2_REVIEWER_STALE_SABOTAGE`. Confirm with `rg -n 'TASK2_REVIEWER_STALE_SABOTAGE' src/services/graph_configuration_draft.py`, run `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres python -m pytest -q tests/integration/test_agent_definition_workbench_postgres.py -k 'two_writers'`, and observe RED. Restore `if expected_lock_version != locked.snapshot.draft.lock_version:`, remove the marker, and rerun that exact node GREEN.

Expected sabotage result: RED because the loser writes at lock 1 instead of returning the exact-seven conflict. Remove all sabotage markers and run Task 2 GREEN once more.

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
- stale `409` exactly matching the envelope above, with all seven role keys and values matching a GET performed after the winning write, while preserving DB state;
- the real cross-agent sequence: GET lock 0/A0/B0, save Builder B1 at lock 0, stale-save Architect A2 at lock 0, then assert the `409` reports lock 1, Architect A0, Builder B1, and all five other current candidates—never a selected-only response;
- one parametrized `422` case for every field/rule, including strict-number rejection and extra fields `candidate.schema_overlay`, `candidate.model.model_alias`, top-level `updated_by`, `candidate_hash`, and `release_id`;
- unknown key and `foreman` as `422` field `agent_key`, code `unknown_agent`;
- malformed JSON as the stable `$` error;
- non-admin + malformed/secret body returns only `403 {"detail":"Admin access required"}`, never calls body parsing/writer, and response text contains neither submitted prompt nor endpoint;
- admin-bypassed local request with missing or whitespace principal returns `403 {"detail":"Authenticated principal required"}` before writer access;
- persisted integrity error maps to existing nonleaking `500` without candidate/hash details.

- [ ] **Step 2: Run route tests and verify RED**

Run:

```bash
python -m pytest -q \
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
    definitions: dict[AgentKey, DraftDefinitionResponse]

    @model_validator(mode="after")
    def require_exact_role_set(self) -> "DraftSaveConflictServerResponse":
        if set(self.definitions) != set(GRAPH_V1_AGENT_KEYS):
            raise ValueError("conflict server definitions must contain all seven roles")
        return self


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

Map `DraftSaveResult` to `200`. For `DraftSaveConflict`, explicitly build the flat-to-nested client projection below and project every item from `conflict.server.definitions` through `DraftDefinitionResponse.model_validate(..., from_attributes=True)`, then return `JSONResponse(status_code=409, content=conflict_response.model_dump(mode="json"))`:

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

For `DraftContentRejected`, use the structured payload directly:

```python
validation_response = DraftValidationErrorResponse(
    code="invalid_draft",
    errors=[
        DraftFieldErrorResponse(
            field=issue.field,
            code=issue.code,
            message=issue.message,
        )
        for issue in exc.issues
    ],
)
```

Return `JSONResponse(status_code=422, content=validation_response.model_dump(mode="json"))` for request validation or structured domain rejection. Map `GraphConfigurationIntegrityError` to the same stable nonleaking `500` used by GET. Actor never comes from the body.

- [ ] **Step 5: Run GREEN and full backend/workbench regression**

Run:

```bash
python -m pytest -q \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py
```

Expected: exact `GET` remains unchanged; all PUT contract/security tests pass.

- [ ] **Step 6: Falsify security and field isolation**

Controller sabotage: add only the annotated Pydantic field `schema_overlay: dict[str, object] | None = None  # TASK3_CONTROLLER_DTO_SABOTAGE` to `EditableModelDraftRequest`; do not add an unannotated marker attribute. Confirm with `rg -n 'TASK3_CONTROLLER_DTO_SABOTAGE' src/api/schemas/agent_definitions.py`, run `python -m pytest -q tests/unit/test_agent_definition_workbench_routes.py::test_put_rejects_every_protected_or_server_owned_field`, and observe RED because the route accepts `candidate.schema_overlay`, not because model import failed. Remove the field/comment and rerun the exact node GREEN.

Reviewer sabotage (different target): replace `actor = get_current_user()` with `actor = get_current_user() or "anonymous"  # TASK3_REVIEWER_ACTOR_SABOTAGE`. Confirm with `rg -n 'TASK3_REVIEWER_ACTOR_SABOTAGE' src/api/routes/agent_definitions.py`, run `python -m pytest -q tests/unit/test_agent_definition_workbench_routes.py::test_put_requires_nonblank_trusted_principal_before_write`, and observe RED. Restore the trusted-only lookup, remove the marker, and rerun that exact node GREEN.

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

Test that `saveDraftDefinition('architect', request)` issues exactly one `PUT` to `/api/admin/agent-definitions/draft/architect`, sends `Content-Type: application/json`, and serializes no protected or server-owned key. Test that valid `409` and `422` throw `AgentDefinitionApiError` preserving the parsed payload object, while GET detail behavior remains compatible. Test the runtime parsers with a `200` missing/mistyping each required nested field, six-role and eight-role `409` bodies, mistyped/empty-error `422`, array, `null`, and scalar JSON; every invalid `200/409/422` throws `InvalidDraftSaveResponseError` before a reducer action can receive it.

Add the exact lost-update regression from C1: initialize lock 0 with Architect A0/Builder B0, feed `saveConflicted` for a stale Architect A2 whose coherent server snapshot is lock 1 with Architect A0/Builder B1, and assert Builder becomes `saved=B1`, `local=B1`, status `Needs test`; Architect becomes `saved=A0`, `local=A2`, status `Unsaved`; all other clean roles adopt their server values. Then dispatch `keepLocal` for Architect and assert no state path represents B0 as the clean Builder server value. Repeat with a locally dirty Builder B2 and assert `saved=B1`, `local=B2`, status `Unsaved`.

Add the aggregate ordering regressions from C2. Dispatch `saveStarted` for Architect request 1/A2/lock 0, edit Architect to A3 while pending, and dispatch request 1 success A2/lock 1: assert `saved=A2`, `local=A3`, `Unsaved`, and no loss. Repeat with request 1 conflict and assert local A3 survives; Reload stores A3 (not submitted A2) in `recoveryForm`. While request 1 is pending, dispatch Builder `saveStarted` request 2 and assert the identical state object/pending request 1 remains. After request 1 settles and request 2 succeeds at lock 2, dispatch delayed request 1 success/conflict at lock 1 and assert referential no-op, lock 2, and no entry regression. Dispatch a current response with a lower lock and assert fixed invalid-response failure clears pending without changing draft/forms.

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
(cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts)
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

Add `DraftSaveRequest`, `DraftSaveSuccessResponse`, `DraftFieldError`, `DraftValidationErrorResponse`, and `DraftSaveConflictResponse` mirroring Task 3; `DraftSaveConflictResponse.server.definitions` is `Record<AgentKey, DraftDefinition>`, never a partial map. Implement every parser and recursive exact-shape rule from the stable transport interface, including the literal `AGENT_KEYS` exact-set check. Change `AgentDefinitionApiError` to retain `readonly payload: unknown` while continuing to derive `detail` for GET-style errors. `saveDraftDefinition` performs one direct `fetch`, parses `200/409/422` before returning/throwing, must not share `workbenchRequest`, and never retries automatically. The hook maps a rejected `fetch` to `Unable to save draft. Check your connection and try again.`, a non-JSON HTTP failure to `Unable to save draft (500 Internal Server Error).` using the actual status/status text, and `InvalidDraftSaveResponseError` to `Unable to save draft because the server response was invalid.`

- [ ] **Step 4: Implement pure local state/status/validation**

Implement structural conversion functions between `DraftDefinition`, `EditableModelDraft`, and `EditableModelDraftForm`. `draftStatus` uses this strict order:

```typescript
if (!editableFormsEqual(entry.local, formFromDefinition(entry.saved))) return 'Unsaved';
if (entry.saved.candidate_hash === entry.publishedHash) return 'Clean';
return 'Needs test';
```

Implement `pendingSave` and every request-ID/monotonic/lossless transition exactly as declared in the stable state interface. The `saveStarted` case contains the literal gate `if (state.pendingSave !== null) return state;`. Every completion case begins with the literal `if (state.pendingSave?.requestId !== action.requestId) return state;`. The `saveConflicted` case binds `const serverDefinitions = action.conflict.server.definitions` only after matching the request ID and lock checks, then maps all seven entries in one transition. `saveFailed`/`saveRejected` identify their role from the matching pending request, clear the aggregate gate, and preserve every unrelated entry.

The matching-success entry update uses this literal lossless branch:

```typescript
const submittedForm = formFromCandidate(pending.submittedCandidate);
const nextLocal = editableFormsEqual(entry.local, submittedForm)
  ? formFromDefinition(action.result.definition)
  : entry.local;
```

Test a rejected `fetch` (`new TypeError("network down")`), a non-JSON `500` (`statusText="Internal Server Error"`), and invalid contract JSON: they produce the three exact messages above on only the pending role, clear pending, preserve draft/forms, and never retry.

- [ ] **Step 5: Run GREEN and typecheck**

Run:

```bash
(cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts)
(cd frontend && npm run typecheck)
```

Expected: focused tests and TypeScript build pass; GET callers still compile.

- [ ] **Step 6: Falsify aggregate ordering, runtime parsing, status, and transport isolation**

Ordering sabotage: replace `if (state.pendingSave !== null) return state;` with `if (false && state.pendingSave !== null) return state; // TASK4_PENDING_GATE_SABOTAGE`. Confirm with `rg -n 'TASK4_PENDING_GATE_SABOTAGE' frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`, run `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts -t "rejects a second aggregate save")`, and observe RED because Builder request 2 replaces pending Architect request 1. Restore the literal gate/remove the marker and rerun the exact node GREEN.

Parser sabotage: replace the exact-set guard `if (!hasExactKeys(definitions, AGENT_KEYS)) return null;` with `if (!AGENT_KEYS.every((key) => key in definitions)) return null; // TASK4_CONFLICT_PARSER_SABOTAGE`. Confirm with `rg -n 'TASK4_CONFLICT_PARSER_SABOTAGE' frontend/src/api/agentDefinitions.ts`, run `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts -t "rejects six-role and eight-role conflicts")`, and observe RED because the eight-role body is accepted. Restore the exact-set guard/remove the marker and rerun GREEN.

Controller sabotage: swap the first two conditions in `draftStatus` and append `// TASK4_CONTROLLER_STATUS_SABOTAGE` to the now-first hash comparison. Confirm with `rg -n 'TASK4_CONTROLLER_STATUS_SABOTAGE' frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`, run `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts -t "status precedence")`, and observe RED because `Needs test` masks `Unsaved`. Restore the original order/remove the marker and rerun the exact node GREEN.

Reviewer sabotage (different target): replace `body: JSON.stringify(request)` with the executable literal injection below. Confirm with `rg -n 'TASK4_REVIEWER_TRANSPORT_SABOTAGE' frontend/src/api/agentDefinitions.ts`, run `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts -t "serializes only editable fields")`, and observe RED because the captured request contains `schema_overlay`. Restore `body: JSON.stringify(request)`, remove the marker, and rerun the exact node GREEN.

```typescript
body: JSON.stringify({
  ...request,
  candidate: {
    ...request.candidate,
    schema_overlay: { TASK4_REVIEWER_TRANSPORT_SABOTAGE: true },
  },
}),
```

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

**Review question:** Can an administrator edit exactly the five owned values, retain unsaved state across agent selection, editor tabs, and the Admin Usage ↔ Agent Definitions tab lifecycle, see truthful status/errors, and save only through the explicit button?

**Files:**
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/useDraftEditor.ts`
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx`
- Modify: `frontend/src/components/Admin/AdminPage.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx`

**Interfaces:**
- Consumes: Task 4 reducer/state, `saveDraftDefinition`, current read-only Output Schema/Assembly rendering.
- Produces: `useDraftEditor(workbench)`, focused `DefinitionEditor`, exact five controls, explicit save, and stable state/components for #264/#265/#266.

- [ ] **Step 1: Replace the obsolete no-Save guard with positive RED tests**

Keep Run, Approve, Reject, Review & Publish, Publish, History, and Rollback forbidden. Add tests that edit all five accessible controls, switch Architect → Builder → Architect, switch all editor tabs, switch Admin Agent Definitions → Usage → Agent Definitions, and assert Architect’s form values and `Unsaved` status survive. Assert no workbench GET occurs before the first Agent Definitions visit, exactly one GET occurs after the visit-and-return sequence, and zero PUTs occur throughout that navigation.

Spy on `fetch` and assert zero PUTs after every keystroke, blur, validation, agent selection, editor-tab selection, and Admin-tab switch. Click **Save Draft** once and assert exactly one PUT using the current global lock and exact five-field candidate.

Add success tests: changed save adopts returned server content/hash/lock, displays `Needs test`, leaves Graph Version/base release unchanged, and preserves another agent’s local unsaved form. Repeated same-content save adopts the incremented lock and `changed: false` without claiming `Clean` if candidate hash still differs from published.

Add deferred-response tests: submit Architect A2, type A3 while the PUT promise is unresolved, resolve success A2/lock 1, and assert A3 remains visible with `Unsaved`. Repeat with conflict then Reload and assert the recovery form is A3, not submitted A2. While Architect is pending, switch to Builder and assert every Save is disabled and attempted activation produces no second PUT; after Architect settles, Builder can save with lock 1. The pure reducer test from Task 4 supplies the otherwise impossible duplicate old response after lock 2 and proves it cannot regress state.

- [ ] **Step 2: Run the component tests and verify RED**

Run:

```bash
(cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)
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

The hook owns `nextRequestIdRef` and `inFlightRequestIdRef`. `save` first returns immediately when `inFlightRequestIdRef.current !== null || state.pendingSave !== null`, then validates the selected form. Invalid input dispatches `saveInvalid` and returns without fetch. For valid input it synchronously allocates/sets the request ID, dispatches `saveStarted` with the exact submitted candidate and current lock, awaits one `saveDraftDefinition`, and includes that ID in success, typed `422`, typed `409`, or `saveFailed`. A `finally` clears the ref only when it still equals that request ID. This synchronous ref gate prevents two rapid calls before React rerenders; the reducer gate independently rejects a second action. There is no retry. No `useEffect`, timeout, blur handler, selection handler, or reducer action calls the save client.

- [ ] **Step 4: Implement the focused editor and compose it into the workbench**

`DefinitionEditor` declares these exact props, so all event handlers and sabotage steps target real symbols:

```typescript
interface DefinitionEditorProps {
  agentKey: AgentKey;
  node: ModelAgentNode;
  entry: DraftEditorEntry;
  saveDisabled: boolean;
  onEdit(agentKey: AgentKey, field: EditableDraftField, value: string): void;
  onSave(agentKey: AgentKey): Promise<void>;
  onReloadServer(agentKey: AgentKey): void;
  onKeepLocal(agentKey: AgentKey): void;
  onRestoreRecovery(agentKey: AgentKey): void;
  onDismissRecovery(agentKey: AgentKey): void;
}
```

Prompt tab renders a labelled `<textarea>`; Model tab renders labelled exact endpoint text and number inputs for Temperature, Maximum tokens, and Top-p. Output Schema and Assembly continue rendering the full server-owned read-only JSON from `entry.saved`.

Render the exact `draftStatus(entry)` near the selected agent and in graph navigation. Render `entry.requestError` as a selected-role `role="alert"`; other roles' errors remain contained in their entries. `saveDisabled` is true for every role whenever `state.pendingSave !== null`, and otherwise only for invalid local validation; never hide Save for a valid same-content explicit save. Keep the five controls enabled during the selected role's pending request so later A3 edits are retained by the lossless reducer rule. Preserve editor-tab state by agent in the extracted component or keep panels mounted; do not use `key={agent_key}` to discard local state. Foreman remains read-only with no Save button/status from the three-value vocabulary.

Preserve lazy loading before the first Admin Agent Definitions visit, but do not unmount the workbench after that visit. In `AdminPage.tsx` add:

```tsx
const [hasVisitedAgentDefinitions, setHasVisitedAgentDefinitions] = useState(false);
```

The Agent Definitions tab click sets `hasVisitedAgentDefinitions` to `true` before setting that tab active. Keep the existing tabpanel mounted/hidden behavior and render the workbench with `{hasVisitedAgentDefinitions && <AgentDefinitionWorkbench />}` rather than conditioning it on `activeTab`. This makes Usage ↔ Agent Definitions navigation preserve reducer state without issuing another GET.

- [ ] **Step 5: Run GREEN, all frontend unit tests, and typecheck**

Run:

```bash
(cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts \
  src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)
(cd frontend && npm run test:unit)
(cd frontend && npm run typecheck)
```

Expected: component/state tests pass, the frontend suite remains green, and the accepted 90-test baseline increases only by the added tests.

- [ ] **Step 6: Falsify explicit-save and Admin-tab persistence**

Lossless-response sabotage: replace the declared `nextLocal` ternary with `const nextLocal = formFromDefinition(action.result.definition); // TASK5_LOSSLESS_RESPONSE_SABOTAGE`. Confirm with `rg -n 'TASK5_LOSSLESS_RESPONSE_SABOTAGE' frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`, run `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx -t "retains A3 typed while A2 is pending")`, and observe RED because the delayed A2 success overwrites A3. Restore the declared branch/remove the marker and rerun GREEN.

Controller sabotage: in the endpoint input's declared handler, immediately after `onEdit(agentKey, 'endpoint_name', value)`, inject `void onSave(agentKey); // TASK5_CONTROLLER_AUTOSAVE_SABOTAGE`. Confirm with `rg -n 'TASK5_CONTROLLER_AUTOSAVE_SABOTAGE' frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx`, run `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx -t "typing and navigation never save")`, and observe RED from the unexpected PUT count. Remove the injected call/marker and rerun the same node GREEN.

Reviewer sabotage (different target): in `AdminPage.tsx`, replace `{hasVisitedAgentDefinitions && <AgentDefinitionWorkbench />}` with `{activeTab === 'agent_definitions' && <AgentDefinitionWorkbench />}{/* TASK5_REVIEWER_ADMIN_UNMOUNT_SABOTAGE */}`. Confirm with `rg -n 'TASK5_REVIEWER_ADMIN_UNMOUNT_SABOTAGE' frontend/src/components/Admin/AdminPage.tsx`, run `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx -t "Admin tab preserves unsaved draft")`, and observe RED because the form/status reset and a second GET occurs after Usage → Agent Definitions. Restore the visited-state conditional/remove the marker and rerun GREEN.

- [ ] **Step 7: Commit Task 5**

```bash
git add \
  frontend/src/components/Admin/AdminPage.tsx \
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

Return a `409` whose exact-seven `server.definitions` aggregate differs from the client in the selected Architect and whose Builder is newer on the server. Assert the UI shows both selected-role candidates, expected/current locks, status `Unsaved`, and **Reload server** / **Keep local** actions. Also assert the clean Builder entry adopts server B1 as both saved and local with `Needs test` while the stale save is on Architect. In a second case make Builder locally dirty at B2 before the Architect conflict; assert it adopts B1 as saved, retains B2 as local, and remains `Unsaved`. Every other role must also reconcile from the same exact-seven response.

Click **Keep local** and assert server lock/baseline update, current local form survives, no second PUT occurs, and a later manual Save uses the refreshed lock. In a separate test submit A2, type A3 before the `409` resolves, click **Reload server**, and assert server form becomes current, no PUT occurs, A3 (not submitted A2) remains visible as the recovery form, **Restore retained values** makes A3 local/Unsaved without saving, and **Dismiss** removes only the recovery form.

Return stable `422` errors for all five fields and assert each message is associated with its labelled input, with no opaque-only toast. Reject the request with a network error and separately with a non-JSON `500`; assert the exact transport message is contained in the selected role only, no retry occurs, editing or a new save clears it per the Task 4 transition table, and another role's form/error is unchanged. Return malformed `200`, six/eight-role `409`, mistyped `422`, and non-object JSON; each must show the fixed invalid-response alert, clear the aggregate pending gate, preserve every draft/form value, and permit a later explicit save.

- [ ] **Step 2: Run component tests and verify RED**

Run:

```bash
(cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx \
  -t "conflict|422|recovery|invalid response")
```

Expected: RED because comparison/recovery UI is not rendered.

- [ ] **Step 3: Implement accessible lossless recovery UI**

Render a blocking conflict panel labelled **Draft changed on the server** with server, submitted, and (when it differs) current-local prompt/endpoint/model values plus both lock versions. Wire buttons only to reducer actions. Render `recoveryForm` in a separate **Values retained for recovery** panel with Restore and Dismiss. Field errors use `aria-describedby` and `role="alert"`; a transport/invalid-body failure that is neither a valid `409` nor valid `422` remains a contained request alert.

Do not fetch a fresh workbench on conflict: the exact-seven `409 server` aggregate is authoritative. The reducer reconciles every role's saved baseline while retaining each locally dirty form, so no extra GET is needed and unrelated dirty forms are not overwritten.

- [ ] **Step 4: Add Playwright save/no-autosave/conflict tests**

Extend the existing route mocks with `SAVE_ENDPOINT = '**/api/admin/agent-definitions/draft/*'` and captured request bodies. Browser assertions:

1. Type in all five fields, switch agent and tabs, and observe zero PUTs.
2. Save once; assert exact JSON, lock `0`, one PUT, returned lock `1`, `Needs test`, unchanged Graph Version 1.
3. Produce an exact-seven `409` after server Builder B1 wins while the stale save targets Architect; assert both selected Architect candidates are visible, clean Builder reconciles to B1/`Needs test`, Keep local performs zero extra PUTs, and explicit retry uses the current global lock.
4. Produce `409` again; Reload uses server values, retains recovery copy, and performs zero extra PUTs.
5. Produce `422`; assert exact field message beside the input.
6. Hold Architect A2 PUT pending, type A3, switch to Builder, assert Builder Save is disabled/zero second PUT, resolve A2, and assert A3 remains `Unsaved`; then Builder can save with lock 1.
7. Produce malformed `200`, six/eight-role `409`, mistyped `422`, non-object JSON, a network error, and non-JSON `500`; assert selected-role request alerts, no retry, pending cleared, all forms preserved, and defined clearing behavior.
8. Retain existing lazy single GET (including the Usage round trip), topology, Foreman, error containment, and small-viewport assertions.

- [ ] **Step 5: Run Playwright, unit/type checks, and backend regressions**

Run:

```bash
(cd frontend && npx playwright test \
  tests/e2e/agent-definition-workbench.spec.ts \
  --project=chromium --workers=1)
(cd frontend && npm run test:unit)
(cd frontend && npm run typecheck)
python -m pytest -q \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_definition_content_mapping.py \
  tests/unit/test_agent_definition_workbench_routes.py \
  tests/unit/test_ci_collects_integration_tests.py
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  python -m pytest -q \
  tests/integration/test_agent_definition_workbench_postgres.py
```

Expected: all commands pass; PostgreSQL reports zero skips; browser PUT counts match each explicit Save only.

- [ ] **Step 6: Falsify browser recovery and backend rollback independently**

Controller sabotage: in the `saveConflicted` reducer case, replace `const serverDefinitions = action.conflict.server.definitions` with `const serverDefinitions = { ...action.conflict.server.definitions, builder: undefined as never } /* TASK6_CONTROLLER_ALL_ROLE_MERGE_SABOTAGE */`. Confirm with `rg -n 'TASK6_CONTROLLER_ALL_ROLE_MERGE_SABOTAGE' frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`, run `(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1 -g "cross-agent conflict")`, and observe RED because Builder does not adopt B1 from the Architect conflict response. Restore the exact original binding/remove the marker and rerun the exact Playwright node GREEN.

Ordering sabotage: in the `saveSucceeded` case replace `if (state.pendingSave?.requestId !== action.requestId) return state;` with `if (false && state.pendingSave?.requestId !== action.requestId) return state; // TASK6_STALE_RESPONSE_SABOTAGE`. Confirm with `rg -n 'TASK6_STALE_RESPONSE_SABOTAGE' frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`, run `(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts -t "ignores delayed lock-1 response after lock 2")`, and observe RED because the obsolete response regresses draft metadata/definition state. Restore the exact guard/remove the marker and rerun GREEN.

Reviewer sabotage (different target): immediately before the stale comparison in the declared `save_editable_model_draft`, inject `locked.draft_row.lock_version += 1  # TASK6_REVIEWER_STALE_MUTATION_SABOTAGE`. Confirm with `rg -n 'TASK6_REVIEWER_STALE_MUTATION_SABOTAGE' src/services/graph_configuration_draft.py`, run `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres python -m pytest -q tests/integration/test_agent_definition_workbench_postgres.py -k 'two_writers'`, and observe RED because the concurrent loser mutates the lock/audit snapshot instead of returning the unchanged winner aggregate. Remove the line/marker and rerun GREEN.

- [ ] **Step 7: Run final scope and diff checks**

Run:

```bash
git diff --check
implementation_base="$(cat \
  .superpowers/2026-09-22-shared-graph-draft-editing/IMPLEMENTATION_BASE)"
git diff --name-only "$implementation_base"..HEAD
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

After Task 6, read the captured implementation fixed point from `.superpowers/2026-09-22-shared-graph-draft-editing/IMPLEMENTATION_BASE` and run the whole-branch review against that exact commit using the correction ledger. The base must be the commit containing this corrected plan, while `29e03411487476383b34101b7b34513dbb917f26` remains the separate final #260 authority. Require the reviewer to provide:

- a writer-by-writer table proving the route adapter and trusted full-content operation converge on one locked writer;
- a rollback ruling covering stale, validation, forced flush, and concurrent loser paths;
- a request-field table proving no protected/server-owned value enters from HTTP;
- a status/event table proving only explicit Save writes and only the three #263 statuses emit;
- a downstream ruling that #264/#265/#266 can consume the full-content writer and extracted state/components without redefining lock, audit, conflict, or hash semantics;
- a merge/no-merge verdict and every deferred finding explicitly assigned to #264, #265, #266, or #267.

The branch is complete only when the final tests above are green, all planned sabotage pairs have demonstrated RED then GREEN, PostgreSQL race tests executed rather than skipped, and `git diff --check` is clean.
