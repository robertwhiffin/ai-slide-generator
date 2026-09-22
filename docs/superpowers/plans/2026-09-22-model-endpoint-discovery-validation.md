# Exact Model Endpoint Discovery and Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exact Databricks foundation-model endpoint discovery and custom endpoint-name validation to the Graph Draft model editor without alias drift, silent failure, or a second draft writer.

**Architecture:** An injected `ModelEndpointCatalog` owns the Serving Endpoints API contract and deterministic fakes. #266 extends #263's one locked full-content save pipeline; its model editor fetches the catalog separately, searches locally, and persists only the selected parent endpoint name.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL 15, Databricks SDK 0.112.0, React 19, TypeScript 5.9, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` §§6, 7.1–7.2, 10–17; GitHub #266; `docs/research/2026-09-22-databricks-model-endpoint-discovery.md`; `docs/superpowers/plans/2026-09-22-shared-graph-draft-editing.md`.

## Global Constraints

- Start only from a reviewed base with #260, #261, #263; rebase/re-probe before shared integration. Never use `447791d7a` as production base.
- Collision ordering is #265 shared integration, #264 shared integration, then #266 writer/route/client/editor/mocks/E2E. Catalog/types/fakes may land earlier.
- Use `/Users/robert.whiffin/.pyenv/shims/python` with `python -m pytest`; never run uv/pip/install/create `.venv`. Stop if `.venv` exists.
- SDK 0.112.0 supplies argument-free `WorkspaceClient.serving_endpoints.list() -> Iterator[ServingEndpoint]`, `get(name: str) -> ServingEndpointDetailed`, and Public Preview `get_open_api(name)`; `query()` has no `response_format` argument.
- Include a discovered item only when non-null `config.served_entities[*].foundation_model` exists. Persist exact parent `endpoint.name`, not task/prefix/display/served-entity/family/alias. No dedicated `system.ai` API is verified.
- The one list has no paging/search/filter: sort/search locally. Empty success is distinct from forbidden/unavailable. Never reuse `routes/tools.py` heuristic or exception-to-empty behavior.
- Manual input is a name only: locally reject URL-shaped input, exact `get(name)`, exact returned-name equality, then READY/config-update state. Do not invent universal provider HTTP mappings.
- List/get/model-serving scope does not establish inference permission. OpenAPI is diagnostic, not structured-output proof. Final capability acceptance is an explicit isolated workbench `AgentRuntime.run_candidate` call under runtime identity at the actual `ChatDatabricks.with_structured_output` seam.
- Seeded `databricks-claude-opus-4-6` and every saved name never auto-advance from discovery, refresh, retry, or rendering.
- #263 remains the only writer/route. Save-time endpoint validation is registered in its pipeline; same-content explicit saves still lock/audit and return `changed:false`.
- Every PostgreSQL module has `pytestmark = pytest.mark.postgres` and explicit CI collection enrollment; skipped PostgreSQL is environmental, never concurrency proof.
- Every task is RED→GREEN with distinct controller/reviewer sabotage; assert calls, values, identities, locks, rollback, and codes—not counts alone.

## Stable interfaces and error contracts

Create `src/services/model_endpoint_catalog.py`; this is the sole serving-SDK import boundary.

```python
from dataclasses import dataclass
from typing import Literal, Protocol

CatalogFailureCode = Literal["catalog_forbidden", "catalog_unavailable"]
EndpointValidationCode = Literal[
    "endpoint_url_not_allowed", "endpoint_unknown", "endpoint_forbidden",
    "endpoint_unavailable", "endpoint_name_mismatch", "endpoint_not_ready",
    "endpoint_update_in_progress", "endpoint_update_failed", "endpoint_update_canceled",
]

@dataclass(frozen=True)
class SystemModelEndpoint:
    name: str
    display_name: str | None
    description: str | None
    docs: str | None

@dataclass(frozen=True)
class SystemModelDiscovery:
    endpoints: tuple[SystemModelEndpoint, ...]

class ModelEndpointCatalogFailure(RuntimeError):
    code: CatalogFailureCode
    retryable: bool

class EndpointValidationFailure(ValueError):
    code: EndpointValidationCode
    message: str
    retryable: bool

class ModelEndpointCatalog(Protocol):
    def list_system_models(self) -> SystemModelDiscovery: ...
    def validate_custom_endpoint(self, name: str) -> None: ...
```

`DatabricksModelEndpointCatalog` calls `list()` once and includes a parent once when any served entity has `foundation_model`; display metadata comes only from that object. It never accesses `task`, deprecated `served_models`, OpenAPI, or query. `PermissionDenied` maps to forbidden, `ResourceDoesNotExist` from get to unknown, and other `DatabricksError`/transport errors to unavailable. A URL is a left-whitespace-tolerant `http://`, `https://`, `//`, or `<scheme>://` prefix; accepted names are never trimmed.

| Result | Code | Message | Retryable |
| --- | --- | --- | --- |
| URL-shaped input | `endpoint_url_not_allowed` | `Endpoint must be a Databricks endpoint name, not a URL.` | false |
| `ResourceDoesNotExist` | `endpoint_unknown` | `Endpoint name was not found.` | false |
| `PermissionDenied` | `endpoint_forbidden` | `Endpoint cannot be validated with this workspace identity.` | false |
| SDK/transport failure | `endpoint_unavailable` | `Endpoint validation is temporarily unavailable. Retry the save.` | true |
| detail name differs | `endpoint_name_mismatch` | `Endpoint validation did not return the exact requested name.` | false |
| non-READY/NOT_UPDATING | `endpoint_not_ready` | `Endpoint is not ready for invocation.` | true |
| IN_PROGRESS | `endpoint_update_in_progress` | `Endpoint configuration update is in progress.` | true |
| UPDATE_FAILED | `endpoint_update_failed` | `Endpoint configuration update failed.` | false |
| UPDATE_CANCELED | `endpoint_update_canceled` | `Endpoint configuration update was canceled.` | false |

Each table result becomes #263 `DraftValidationIssue("candidate.model.endpoint_name", code, message)` in its `422 invalid_draft` envelope. There is no save-time `unsupported_structured_output` result.

The discovery route contract is:

```text
GET /api/admin/agent-definitions/model-endpoints
200 {"items":[{"name":str,"display_name":str|null,"description":str|null,"docs":str|null}]}
403 {"code":"catalog_forbidden","message":str,"retryable":false}
503 {"code":"catalog_unavailable","message":str,"retryable":true}
```

The 200 list may be empty; backend order is `(display_name or name).casefold(), name`. Browser search matches name/display/description locally. The isolated runner records `structured_output_probe_succeeded` or `structured_output_probe_failed` from saved content plus a synthetic case and assembly context; it accepts no endpoint/URL override, and a failure cannot be approved.

---

### Task 1: Catalog adapter and deterministic fake

**Files:**
- Create: `src/services/model_endpoint_catalog.py`
- Create: `tests/unit/test_model_endpoint_catalog.py`

**Interfaces:** Produces the stable port above and `FakeModelEndpointCatalog` with queued discovery outcomes, name-keyed validation outcomes, `list_calls`, and `validated_names`.

- [ ] **Step 1: Write failing adapter tests**

Build SDK-shaped `SimpleNamespace` fixtures. Assert one no-argument list call, foundation-field selection, task-only exclusion, deduplication of two foundation entities under one parent, exact space-containing name, deterministic sort, and empty success. Assert forbidden/unavailable remain typed failures. Assert URL rejection makes zero SDK calls; accepted input calls get exactly once; returned-name mismatch, READY, every update state, unknown, forbidden, and unavailable map to the table. Assert neither OpenAPI nor query is accessed. Assert every fake outcome needs no SDK mock.

- [ ] **Step 2: Run RED**

```bash
python -m pytest -q tests/unit/test_model_endpoint_catalog.py
```

Expected: collection fails because the module does not exist.

- [ ] **Step 3: Implement minimal production/fake behavior**

Use `getattr(endpoint.config, "served_entities", None) or ()` and `getattr(entity, "foundation_model", None) is not None`. Require a nonblank parent name; missing identity is unavailable, never fabricated. Preserve accepted text verbatim, make results tuples, and map only the named SDK exception classes.

- [ ] **Step 4: Run GREEN and falsify two controls**

Run the Task 1 command. Replace foundation detection with `endpoint.task` tagged `TASK1_TASK_HEURISTIC_SABOTAGE`; the task-only exclusion test must be RED. Restore. Remove detail-name equality tagged `TASK1_EXACT_NAME_SABOTAGE`; the alias response test must be RED. Restore, remove both tags, rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add src/services/model_endpoint_catalog.py tests/unit/test_model_endpoint_catalog.py
git commit -m "feat: add exact model endpoint catalog (#266)"
```

---

### Task 2: One endpoint validator in #263's draft-save pipeline

**Files:**
- Modify: `src/services/graph_configuration_draft.py`
- Modify: `src/services/graph_configuration.py`
- Modify: `tests/unit/test_graph_configuration_draft.py`
- Modify: `tests/integration/test_agent_definition_workbench_postgres.py`
- Modify: `tests/unit/test_ci_collects_integration_tests.py` and `.github/workflows/test.yml` only if the existing module is not explicitly collected.

**Interfaces:** Consumes #263 `save_editable_model_draft`, `save_draft_content`, `_write_locked_content`, `DraftContentRejected`, and Task 1. Produces `EndpointDraftValidator(Protocol)` with `validate(content: DefinitionContent) -> None`, injected into the #263 facade.

- [ ] **Step 1: Write failing pipeline and PostgreSQL tests**

Use a recording fake validator. For both public saves, prove #263 command/round-trip/immutable validation runs first; a coherent aggregate is locked; a stale request returns the exact seven-role conflict without remote validation; and a non-stale complete reconstructed `DefinitionContent` is validated exactly once immediately before the existing writer. Assert every table error gives the exact ordered one-item issue and no content/hash/lock/audit/release/interval mutation. Assert valid same-content validates, advances audit/lock, and returns `changed:false`; force flush failure after validation and prove rollback from a fresh session.

In the PostgreSQL module add `pytestmark = pytest.mark.postgres` when absent. Use a blocking deterministic validator, prove two database PIDs plus a lock waiter, prove winner writes, and prove stale loser neither invokes validator nor overwrites. Inspect the CI guard/workflow; add the existing filename only if absent.

- [ ] **Step 2: Run RED**

```bash
python -m pytest -q tests/unit/test_graph_configuration_draft.py -k endpoint
python -m pytest -q tests/integration/test_agent_definition_workbench_postgres.py -k endpoint
```

Expected: unit tests fail because no endpoint extension exists. The PostgreSQL command either runs against distinct real PIDs or reports the fixture's explicit unavailable-server skip.

- [ ] **Step 3: Implement the one registered extension**

After #263 reconstructs/round-trips `DefinitionContent` and checks immutable fields, take the existing locked snapshot. Return the stale result before catalog validation. Otherwise call the injected validator once, translate `EndpointValidationFailure` to the table `DraftValidationIssue`, then call the pre-existing `_write_locked_content`. Production composition makes the adapter with `get_system_client`; it never accepts host/token/name from a browser except the already persisted candidate name. Do not retry, log endpoint text, add an ORM column, query another selected row, or add a writer/hash/route.

- [ ] **Step 4: Run GREEN and falsify distinct paths**

Run both Task 2 commands. Replace validation with `if False: self._endpoint_validator.validate(content)  # TASK2_VALIDATOR_BYPASS_SABOTAGE`; forbidden validation test must be RED because save writes. Restore. Move stale return below validation tagged `TASK2_STALE_REMOTE_SABOTAGE`; stale test must be RED because loser calls fake catalog. Restore and rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add src/services/graph_configuration_draft.py src/services/graph_configuration.py tests/unit/test_graph_configuration_draft.py tests/integration/test_agent_definition_workbench_postgres.py
git commit -m "feat: validate draft endpoint names (#266)"
```

Stage `tests/unit/test_ci_collects_integration_tests.py` and `.github/workflows/test.yml` only when inspection required their modification.

---

### Task 3: Authenticated discovery route and stable wire errors

**Files:**
- Modify: `src/api/schemas/agent_definitions.py`
- Modify: `src/api/routes/agent_definitions.py`
- Modify: `tests/unit/test_agent_definition_workbench_routes.py`

**Interfaces:** Consumes Task 1 catalog and Task 2 composed facade. Produces `GET /api/admin/agent-definitions/model-endpoints`; #263's existing PUT remains the only mutation interface.

- [ ] **Step 1: Write failing route tests**

Inject `FakeModelEndpointCatalog`. Assert populated response has only `items`; each item has exactly name/display_name/description/docs; seed spelling remains exact; output is deterministic; task/provider/ID are absent. Assert empty is `200 {"items":[]}`, forbidden is only documented 403, unavailable only documented 503, and neither becomes empty success.

For PUT, use a secret-looking URL as a non-admin and assert authorization occurs before JSON parsing/catalog/writer and response leaks neither prompt nor endpoint. As admin, assert all table outcomes serialize as a one-item `invalid_draft` error with no mutation. Assert GET workbench and generic tools routes never invoke this catalog.

- [ ] **Step 2: Run RED**

```bash
python -m pytest -q tests/unit/test_agent_definition_workbench_routes.py -k 'model_endpoints or endpoint_validation or non_admin'
```

Expected: new discovery contract fails because DTOs/route/dependency are absent.

- [ ] **Step 3: Implement strict route/DTOs**

Append Pydantic `SystemModelEndpointResponse`, `SystemModelDiscoveryResponse`, and `ModelEndpointCatalogErrorResponse` with `extra="forbid"`; item DTOs have no request fields. Add the GET beneath `/workbench` on the existing admin router. Obtain catalog after router-level authorization; map only `ModelEndpointCatalogFailure` to exact envelope/status, and retain existing nonleaking unexpected-error policy. Keep #263 raw-body parsing/principal dependency before its PUT body; it invokes the composed facade rather than `get` directly.

- [ ] **Step 4: Run GREEN and falsify errors/auth ordering**

Run the Task 3 command. Return `{"items": []}  # TASK3_EMPTY_ON_ERROR_SABOTAGE` for unavailable; unavailable test must be RED. Restore. Temporarily declare a typed Pydantic body in the PUT signature tagged `TASK3_BODY_BEFORE_AUTH_SABOTAGE`; secret malformed non-admin test must be RED. Restore raw request/auth-first parsing and rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add src/api/schemas/agent_definitions.py src/api/routes/agent_definitions.py tests/unit/test_agent_definition_workbench_routes.py
git commit -m "feat: expose model endpoint discovery (#266)"
```

---

### Task 4: Typed catalog client and accessible model-editor controls

**Files:**
- Modify: `frontend/src/api/agentDefinitions.ts`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx`
- Modify: `frontend/tests/fixtures/mocks.ts`

**Interfaces:** Consumes Task 3 and #263 editor state/actions. Produces `getSystemModelEndpoints(): Promise<SystemModelEndpoint[]>`, `ModelEndpointCatalogApiError`, `InvalidModelEndpointCatalogResponseError`, and Model-tab discovery controls that submit only #263's five editable values.

- [ ] **Step 1: Write failing parser/component tests**

Use #263's existing plain-record/exact-key parser helpers. Test populated names, empty success, malformed 200 item, valid forbidden/unavailable envelopes, and network failure. Malformed successful data throws `InvalidModelEndpointCatalogResponseError`; valid 403/503 throws `ModelEndpointCatalogApiError` containing status, code, retryable, and message.

Render `DefinitionEditor` with seed and catalog fixtures. Assert accessible **Refresh models**, labelled **Search discovered models**, exact-name selectable entries, and separately labelled advanced **Custom endpoint name**. Selection copies precisely item `name` into existing endpoint form state only; it leaves numeric values unchanged and makes no PUT. Search is local/case-insensitive and reports no match without changing selection. Empty says `No Databricks foundation-model endpoints are available to this identity.`; error preserves saved endpoint, exposes retry, and refresh replaces prior list only after success. URL-shaped custom input has accessible local table-message and zero PUT; newer item cannot move seed until explicit selection then Save; same-content Save remains enabled.

- [ ] **Step 2: Run RED**

```bash
(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)
(cd frontend && npm run typecheck)
```

Expected: tests/typecheck fail because client types and editor controls do not exist.

- [ ] **Step 3: Implement strict transport and editor state**

Export:

```ts
export interface SystemModelEndpoint {
  name: string;
  display_name: string | null;
  description: string | null;
  docs: string | null;
}
export class ModelEndpointCatalogApiError extends Error {
  readonly status: 403 | 503;
  readonly code: 'catalog_forbidden' | 'catalog_unavailable';
  readonly retryable: boolean;
}
export class InvalidModelEndpointCatalogResponseError extends Error {}
export function getSystemModelEndpoints(): Promise<SystemModelEndpoint[]>;
```

Read JSON once, require exact top/item keys and primitive/null values, and reject arrays/class instances as records. Never cache/coalesce refresh; each explicit click makes one GET, while a monotonic request ID prevents an older response overwriting the newest state.

In `DefinitionEditor`, keep catalog state `idle | loading | ready | empty | error`, search, request ID, and last good list local to the workbench. Fetch on first Model-tab opening and explicit refresh. Loading/error announces with `aria-live="polite"`; failure uses `role="alert"`; refresh stays enabled for recovery. The custom field remains the #263 `endpoint_name` control and selection is only a setter. Match Task 1 URL detection locally; server 422 wins after Save. Do not transmit a display name, URL, token, host, or catalog metadata in save payload.

- [ ] **Step 4: Run GREEN and falsify UI identity/autosave**

Run both Task 4 commands. Set selection to `item.display_name ?? item.name  // TASK4_DISPLAY_NAME_SABOTAGE`; exact selection test must be RED. Restore. Invoke `onSave(agentKey)` from selection handler tagged `TASK4_SELECTION_AUTOSAVE_SABOTAGE`; no-autosave test must be RED. Restore, remove markers, rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/agentDefinitions.ts frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx frontend/tests/fixtures/mocks.ts
git commit -m "feat: add model endpoint editor discovery (#266)"
```

---

### Task 5: Browser recovery and isolated structured-output acceptance

**Files:**
- Modify: `frontend/tests/e2e/agent-definition-workbench.spec.ts`
- Modify: `tests/unit/test_agent_runtime.py`
- Modify: `tests/unit/test_agent_definition_workbench_routes.py`

**Interfaces:** Consumes Tasks 1–4 plus #261 `AgentRuntime.run_candidate` and #267's isolated-test operation. Produces deterministic capability probe evidence; its request supplies saved candidate, synthetic test case, and assembly context, never a model endpoint override.

- [ ] **Step 1: Write failing browser/runtime tests**

In Playwright intercept workbench/catalog/save routes. Exercise first Model-tab fetch, local search, refresh exposing newer entry while seed remains exact, explicit selection/save exact name, empty refresh, forbidden recovery, unavailable recovery, and URL rejection with zero PUT. After 503, a successful Refresh clears error without remount. Assert catalog GET has no endpoint name/token/host/URL query or body.

In `test_agent_runtime.py`, inject recording `model_factory`/`client_factory`, run isolated candidate path with saved `DefinitionContent`, synthetic payload, and assembly context. Assert exact persisted endpoint is passed as `endpoint`, runtime identity client as `workspace_client`, `with_structured_output(schema)` runs before invoke, and no discovery display/family alias appears. Make deterministic structured model raise: result is `structured_output_probe_failed`, audit has endpoint identity, UI message is sanitized, retry is explicit, and approval is denied. Make it return canonical output: result is `structured_output_probe_succeeded`. No test performs a live invocation.

- [ ] **Step 2: Run RED**

```bash
(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1 -g 'model endpoint')
python -m pytest -q tests/unit/test_agent_runtime.py -k 'candidate and structured_output'
```

Expected: browser tests fail before controls exist. Runtime test fails until #261/#267 provide the saved-candidate isolated-run seam; if #267 is not merged, stop this final task rather than replacing it with direct SDK query or arbitrary endpoint request.

- [ ] **Step 3: Connect only the isolated-run seam**

At the rebased final integration head, have the existing isolated-test service call `AgentRuntime.run_candidate` using saved database content, selected synthetic case, and context. Record the two probe codes; retry creates a new run for the same candidate hash/case version and changes no draft hash/lock/audit/name. Do not call `ServingEndpointsAPI.query`, interpret OpenAPI as capability, or add an endpoint field to isolated-test HTTP input. Keep admin authorization before body processing.

- [ ] **Step 4: Run GREEN and falsify no-drift/binding**

Run both Task 5 commands. Assign first refreshed endpoint to form state tagged `TASK5_AUTO_ADVANCE_SABOTAGE`; browser no-drift test must be RED. Restore. Replace `model.with_structured_output(schema)` with `model  # TASK5_STRUCTURED_BINDING_SABOTAGE`; runtime probe test must be RED. Restore/remove tags and rerun GREEN, then run:

```bash
python -m pytest -q tests/unit/test_model_endpoint_catalog.py tests/unit/test_graph_configuration_draft.py tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_agent_runtime.py tests/integration/test_agent_definition_workbench_postgres.py
(cd frontend && npm run test:unit -- src/components/Admin/AgentDefinitionWorkbench)
(cd frontend && npx playwright test tests/e2e/agent-definition-workbench.spec.ts --project=chromium --workers=1)
```

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/e2e/agent-definition-workbench.spec.ts tests/unit/test_agent_runtime.py tests/unit/test_agent_definition_workbench_routes.py
git commit -m "test: prove model endpoint workbench flow (#266)"
```

## Final whole-branch review handoff

- [ ] Rebase to reviewed #260+#261+#263 then #265 then #264 integration head; record `git rev-parse HEAD` before #266 shared-file edits.
- [ ] Re-probe installed 0.112.0 source: no list arguments, get/name present, `ServedEntityOutput.foundation_model` present, no assumed `system_ai` property.
- [ ] Audit diff for `routes/tools.py`, `task.startswith`, `served_models`, exception-to-empty, URL forwarding, alias rewrite, auto-upgrade, `query(response_format`, and endpoint override fields; none is allowed.
- [ ] Confirm deterministic catalog fake, route injection, writer validator, frontend mocks/intercepts, and runtime model factory; CI never invokes Databricks.
- [ ] Confirm empty/forbidden/unavailable/unknown/name mismatch/readiness/update states/URL/probe failure remain separately observable; confirm stale loser/no-call, same-content audit, rollback, exact seed, and recovery have cause-based coverage.
- [ ] Run `rg -n -i -e 'tb''d' -e 'to''do' -e 'implement'\ 'later' -e 'fill'\ 'in' -e 'appropriate'\ 'error' -e 'handle'\ 'edge' -e 'similar'\ 'to'\ 'task' docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`; expect no matches. Remove all sabotage markers before final commit.

Plan complete at `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`; execute only through the stated serialized shared-file sequence.
