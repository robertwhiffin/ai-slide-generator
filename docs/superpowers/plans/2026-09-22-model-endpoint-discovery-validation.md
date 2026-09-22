# Exact Model Endpoint Discovery and Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans-tellr` and `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exact Databricks foundation-model endpoint discovery and custom endpoint-name validation to the Graph Draft model editor without alias drift, silent failure, or a second draft writer.

**Architecture:** An injected `ModelEndpointCatalog` owns the Serving Endpoints API contract and deterministic fakes. Its collision-free adapter/types/tests land first while predecessor tickets finish. After reviewed #265 and #264 are merged locally, #266 extends #263's one locked full-content save pipeline; its model editor fetches the catalog separately, searches locally, and persists only the selected parent endpoint name. A #266-owned, explicit probe loads the exact saved candidate server-side and exercises the actual `ChatDatabricks.with_structured_output` seam under runtime identity; it does not wait for or depend on #267's versioned test-case system.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL 15, Databricks SDK 0.112.0, React 19, TypeScript 5.9, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` §§6, 7.1–7.2, 10–17; GitHub #266; `docs/research/2026-09-22-databricks-model-endpoint-discovery.md`; `docs/superpowers/plans/2026-09-22-shared-graph-draft-editing.md`.

## Global Constraints

- Task 0 is a non-implementation, non-mutating preflight and is mandatory before Task 1. It fails if `.venv` exists, records the absolute shared interpreter, inventories Task 1's installed-SDK/fake/test seams, captures cause-based Task 1 baselines, and creates the overriding `.superpowers/sdd/2026-09-22-model-endpoint-discovery-validation/PLAN-CORRECTIONS.md`. It records a distinct pre-integration `TASK1_BASE` for Task 1's review; it must not set the final `IMPLEMENTATION_BASE`. Task 1 is the only pre-integration implementation task; it starts from reviewed #260 code and creates only `model_endpoint_catalog.py` plus its focused test, and must not edit a file owned by #261, #263, #264, or #265.
- Before Task 2, rebase onto one concrete reviewed **local** `feat/langgraph-core` commit containing #260, #261, #263, #265, and #264; never use or fetch a remote integration branch and never use `447791d7a`. Record full predecessor heads, prove all five are ancestors, and prove the integration commit is an ancestor of the rebased branch `HEAD`. Only after that proof, set final `IMPLEMENTATION_BASE` to this exact integration commit; all whole-branch review packages use that post-rebase value.
- Local shared-file integration order is exactly **#265, then #264, then #266**. #266 merges locally only after its whole-branch review; #267 starts only from that reviewed local #266 merge. No PR or push is part of this plan.
- Use `/Users/robert.whiffin/.pyenv/shims/python -m pytest` literally in every backend command; never use bare `python`, run uv/pip/install, or create `.venv`. Stop if `.venv` exists.
- SDK 0.112.0 supplies argument-free `WorkspaceClient.serving_endpoints.list() -> Iterator[ServingEndpoint]`, `get(name: str) -> ServingEndpointDetailed`, and Public Preview `get_open_api(name)`; `query()` has no `response_format` argument.
- Include a discovered item only when non-null `config.served_entities[*].foundation_model` exists. Persist exact parent `endpoint.name`, not task/prefix/display/served-entity/family/alias. No dedicated `system.ai` API is verified.
- The one list has no paging/search/filter: sort/search locally. Empty success is distinct from forbidden/unavailable. Never reuse `routes/tools.py` heuristic or exception-to-empty behavior.
- Manual input is a name only. A deterministic local endpoint-name policy rejects URL-shaped input before stale comparison and makes no SDK call. Only after the locked snapshot is current does remote validation perform exact `get(name)`, exact returned-name equality, then READY/config-update state. Do not invent universal provider HTTP mappings.
- List/get/model-serving scope does not establish inference permission. OpenAPI is diagnostic, not structured-output proof. Final capability acceptance is the #266-owned explicit saved-candidate endpoint probe under runtime identity at the actual `ChatDatabricks.with_structured_output` seam; it accepts no endpoint override and is not #267's versioned test-run system.
- Seeded `databricks-claude-opus-4-6` and every saved name never auto-advance from discovery, refresh, retry, or rendering.
- #263 remains the only writer/route. Save-time endpoint validation is registered in its pipeline; same-content explicit saves still lock/audit and return `changed:false`.
- Every PostgreSQL module has `pytestmark = pytest.mark.postgres` and explicit CI collection enrollment. Every PostgreSQL command in this plan must execute with **zero skips**; an unavailable server is a failed gate, never accepted concurrency evidence.
- Execute with `executing-plans-tellr` plus `superpowers:subagent-driven-development`. Task 0 creates `PLAN-CORRECTIONS.md` and attaches it to Task 1's implementer/reviewer briefs. Before Task 2, extend that same file—do not replace it—with the complete integrated per-task self-consistency and pairwise producer/consumer/shared-file tables, exact current owners/callers, and baseline failure/skip **causes**; attach it to every later implementer/reviewer brief and re-derive causes after runtime/schema changes. Task 1's package is `TASK1_BASE..TASK1_HEAD`; after rebase, record a fresh per-task `TASK_BASE` and `TASK_HEAD` for every Task 2–6 package. No task package uses `IMPLEMENTATION_BASE`; that post-rebase base is reserved for the final whole-branch range only. Every task is RED→GREEN with distinct controller/reviewer sabotage on executed production seams; assert calls, values, identities, locks, rollback, and codes—not counts alone.

## Mandatory initial preflight (Task 0, before Task 1)

Task 0 is read-only with respect to production and test implementation. It may create only the execution ledger `PLAN-CORRECTIONS.md`; it must not edit application/test files, install anything, create an environment, or touch remotes. Run every command from the repository root:

```bash
git status --short --branch
git rev-parse HEAD
test ! -e .venv
test -x /Users/robert.whiffin/.pyenv/shims/python
/Users/robert.whiffin/.pyenv/shims/python --version
/Users/robert.whiffin/.pyenv/shims/python -c 'import inspect; from importlib.metadata import version; from databricks.sdk.service import serving; print(version("databricks-sdk")); print(inspect.signature(serving.ServingEndpointsAPI.list)); print(inspect.signature(serving.ServingEndpointsAPI.get)); print("foundation_model" in inspect.signature(serving.ServedEntityOutput).parameters)'
test ! -e src/services/model_endpoint_catalog.py
test ! -e tests/unit/test_model_endpoint_catalog.py
rg -n "WorkspaceClient|serving_endpoints|model_factory|client_factory|with_structured_output|Fake" \
  src/services/agent_runtime.py tests/unit/test_agent_runtime.py \
  src/api/routes/tools.py tests/unit/test_ci_collects_integration_tests.py
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_agent_runtime.py \
  tests/unit/test_ci_collects_integration_tests.py
test ! -e .venv
```

Record the literal interpreter `/Users/robert.whiffin/.pyenv/shims/python`, its version, the installed SDK signatures/field result, current SDK owner/callers, the absent intended Task 1 paths, deterministic fake seams, CI test seam, and the exact pass/fail/skip/warning **causes** from the two-module baseline. Create `.superpowers/sdd/2026-09-22-model-endpoint-discovery-validation/PLAN-CORRECTIONS.md` with either explicit overrides or `No corrections`, `TASK1_BASE=$(git rev-parse HEAD)`, and a Task 1 file/interface/test table. Attach this exact file to both Task 1 briefs. Task 1's review package is exactly `TASK1_BASE..TASK1_HEAD`; final `IMPLEMENTATION_BASE` is deliberately absent until the Task 2 integration gate. A missing module, changed SDK signature, unexpected baseline cause, any skip, or `.venv` blocks Task 1 until ruled on; do not normalize it to a count.

### Task 0: Environment, Task 1 seam inventory, and cause baseline

**Files:** Create only `.superpowers/sdd/2026-09-22-model-endpoint-discovery-validation/PLAN-CORRECTIONS.md` as an execution artifact. Do not modify production or test implementation.

**Interfaces:** Produces the pre-integration `TASK1_BASE`, absolute-interpreter/SDK/fake/test inventory, exact baseline cause set, and binding correction ledger consumed by every implementer and reviewer. It does not produce final `IMPLEMENTATION_BASE`.

- [ ] Run the mandatory initial preflight exactly as written; stop on `.venv`, a missing required seam, any skip, or an unexplained failure/warning cause.
- [ ] Write the exact observations and Task 1 consistency table to `PLAN-CORRECTIONS.md`; do not copy claims from this plan when the checked source disagrees.
- [ ] Attach the ledger to Task 1's implementer and reviewer briefs and require explicit acknowledgment of every override. This task has no implementation commit.

## Mandatory local integration and stricter corrections re-probe (after Task 1, before Task 2)

Task 1 may run before this gate because both files are new and collision-free. Before Task 2, confirm #265 and #264 passed their task reviews and whole-branch reviews and were merged **locally** into `feat/langgraph-core` after reviewed #260, #261, and #263. Do not fetch, push, or refer to an `origin/integration/*` branch.

Record full SHAs for the reviewed #260, #261, #263, #265, and #264 heads plus `INTEGRATION_BASE=$(git rev-parse feat/langgraph-core)`. For each reviewed head run `git merge-base --is-ancestor <head> "$INTEGRATION_BASE"`; all must return zero. Assert `INTEGRATION_BASE != 447791d7a`, rebase the #266 branch while retaining Task 1, and run `git merge-base --is-ancestor "$INTEGRATION_BASE" HEAD`; do **not** assert equality because Task 1 is intentionally retained above the base. Then record `TASK1_REBASED_HEAD=$(git rev-parse HEAD)`, set `IMPLEMENTATION_BASE="$INTEGRATION_BASE"` in the same corrections ledger, and assert `git merge-base --is-ancestor "$IMPLEMENTATION_BASE" HEAD`. Retain the original `TASK1_BASE` only for the Task 1 package. Before Task 2, compare `git log --format='%H %s' "$IMPLEMENTATION_BASE".."$TASK1_REBASED_HEAD"` with the ledger's Task 1 rebased commit(s); it must contain Task 1 only, no predecessor integration commit.

Run a stricter SDD workspace/pre-pass before Task 2. Re-run `test ! -e .venv`, re-probe with `/Users/robert.whiffin/.pyenv/shims/python`, and append an integration addendum to the existing `PLAN-CORRECTIONS.md`; never discard the Task 0 observations. Inventory every catalog/local-policy/facade/writer/route/client/editor/runtime-probe owner and caller, record baseline failure and skip causes, and include one row for every task's code/test/file consistency plus every cross-task shared seam. Re-read the integrated #263 writer/envelope/frontend state, #264 schema registry/runtime composition, #265 assembly runtime/editor, #261 persisted failure and identity-sink behavior, current SDK source, PostgreSQL fixtures, and CI collection. Rule on every mismatch before dispatch; no second writer, remote base, `routes/tools.py` reuse, endpoint override, or compatibility guess is allowed. The addendum may add renamed/final predecessor test files, but it may not remove any PostgreSQL module explicitly listed in Task 6's final matrix or accept a server-unavailable skip.

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
    def validate_custom_endpoint_remote(self, name: str) -> None: ...

def validate_endpoint_name_policy(name: str) -> None: ...
```

`DatabricksModelEndpointCatalog` calls `list()` once and includes a parent once when any served entity has `foundation_model`; display metadata comes only from that object. It never accesses `task`, deprecated `served_models`, OpenAPI, or query. `PermissionDenied` maps to forbidden, `ResourceDoesNotExist` from get to unknown, and other `DatabricksError`/transport errors to unavailable. A URL is a left-whitespace-tolerant `http://`, `https://`, `//`, or `<scheme>://` prefix; accepted names are never trimmed.

`validate_endpoint_name_policy` is pure and owns only deterministic name policy, including URL rejection; it never receives or calls an SDK client. `validate_custom_endpoint_remote` assumes local policy already passed and owns only `get(name)`, exact returned-name equality, readiness, and update-state checks. The draft-save pipeline must call the local policy before comparing the submitted lock version, then call the remote method only after the existing locked snapshot has proved the request current. A stale request can therefore never cause remote I/O, while a stale request containing a locally invalid URL still receives the ordered local `422`.

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

The 200 list may be empty; backend order is `(display_name or name).casefold(), name`. Browser search matches name/display/description locally.

Create `src/services/model_endpoint_probe.py`. It exports `StructuredOutputProbeCode = Literal["unsupported_structured_output", "endpoint_probe_forbidden", "structured_output_probe_failed"]`, `StructuredOutputProbeFailure(code, message, retryable)`, `StructuredOutputProbeAdapter.probe(endpoint_name: str) -> None`, immutable `SavedEndpointProbeIdentity(agent_key, endpoint_name, candidate_hash, lock_version)`, and `ModelEndpointProbeService.probe_saved_candidate(session, *, agent_key, expected_lock_version)`. Production constructs the same runtime-identity `ChatDatabricks` client and uses the same extracted structured-binding helper as `AgentRuntime`, while tests use deterministic outcomes. It maps only `NotImplementedError` raised by the binding seam to unsupported, `PermissionDenied` to forbidden, and every other provider/transport exception to ambiguous probe failure; it never parses exception text. The service reads/copies the exact server-side candidate and endpoint, rejects a stale lock before invocation, and accepts no endpoint, URL, host, token, prompt, schema, or arbitrary payload from the request. It invokes a code-owned minimal synthetic prompt and `_StructuredOutputProbeResponse(result: Literal["ok"])`; it writes no draft, audit, chat, deck, test case, or approval state.

The admin-only operation is:

```text
POST /api/admin/agent-definitions/draft/{agent_key}/model-endpoint-probe
request:  {"lock_version": int}
200:      {"code":"structured_output_probe_succeeded","endpoint_name":str,"candidate_hash":str,"lock_version":int}
403:      {"code":"endpoint_probe_forbidden","message":str,"retryable":false,"endpoint_name":str,"candidate_hash":str,"lock_version":int}
409:      existing coherent #263 stale-draft envelope
422:      {"code":"unsupported_structured_output","message":str,"retryable":false,"endpoint_name":str,"candidate_hash":str,"lock_version":int}
503:      {"code":"structured_output_probe_failed","message":str,"retryable":true,"endpoint_name":str,"candidate_hash":str,"lock_version":int}
```

Only an explicit structured-binding/capability rejection from the adapter maps to `unsupported_structured_output`; ambiguous provider/transport failures remain `structured_output_probe_failed`, because the verified API has no universal negative capability signal. The UI exposes an explicit **Test structured output** action and the exact sanitized result; success does not approve anything. #267 later consumes the same structured-binding helper for durable versioned test runs, but #266 neither depends on nor implements that broader subsystem.

---

### Task 1: Catalog adapter, local endpoint-name policy, and deterministic fake

**Files:**
- Create: `src/services/model_endpoint_catalog.py`
- Create: `tests/unit/test_model_endpoint_catalog.py`

**Interfaces:** Consumes Task 0's attached `PLAN-CORRECTIONS.md`. Produces the stable pure `validate_endpoint_name_policy` function, remote-only catalog port above, and `FakeModelEndpointCatalog` with queued discovery outcomes, name-keyed remote-validation outcomes, `list_calls`, and `validated_names`.

- [ ] **Step 1: Write failing adapter tests**

Build SDK-shaped `SimpleNamespace` fixtures. Assert one no-argument list call, foundation-field selection, task-only exclusion, deduplication of two foundation entities under one parent, exact space-containing name, deterministic sort, and empty success. Assert forbidden/unavailable remain typed failures. Test `validate_endpoint_name_policy` independently: every URL shape maps to the URL table row without constructing or calling an SDK adapter, while accepted input is preserved verbatim. Test `validate_custom_endpoint_remote` independently: accepted input calls get exactly once; returned-name mismatch, READY, every update state, unknown, forbidden, and unavailable map to the table. Assert neither OpenAPI nor query is accessed. Assert every fake outcome needs no SDK mock.

- [ ] **Step 2: Run RED**

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q tests/unit/test_model_endpoint_catalog.py
```

Expected: collection fails because the module does not exist.

- [ ] **Step 3: Implement minimal production/fake behavior**

Use `getattr(endpoint.config, "served_entities", None) or ()` and `getattr(entity, "foundation_model", None) is not None`. Require a nonblank parent name; missing identity is unavailable, never fabricated. Preserve accepted text verbatim, make results tuples, and map only the named SDK exception classes.

- [ ] **Step 4: Run GREEN and falsify discovery classification**

Run the Task 1 command. Controller sabotage: replace foundation detection with `endpoint.task` tagged `TASK1_CONTROLLER_TASK_HEURISTIC_SABOTAGE`; the task-only exclusion test must be RED on the executed path, then restore/remove the marker and rerun GREEN. Reserve a different reviewer target: remove exact detail-name equality under `TASK1_REVIEWER_EXACT_NAME_SABOTAGE`; the alias-response test must go RED, then restore and rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add src/services/model_endpoint_catalog.py tests/unit/test_model_endpoint_catalog.py
git commit -m "feat: add exact model endpoint catalog (#266)"
```

---

### Task 2: Two-phase endpoint validation in #263's one draft-save pipeline

**Files:**
- Modify: `src/services/graph_configuration_draft.py`
- Modify: `src/services/graph_configuration.py`
- Modify: `tests/unit/test_graph_configuration_draft.py`
- Modify: `tests/integration/test_agent_definition_workbench_postgres.py`
- Modify: `tests/unit/test_ci_collects_integration_tests.py` and `.github/workflows/test.yml` only if the existing module is not explicitly collected.

**Interfaces:** Consumes the extended `PLAN-CORRECTIONS.md`, #263 `save_editable_model_draft`, `save_draft_content`, `_write_locked_content`, `DraftContentRejected`, and Task 1. Produces two explicitly ordered phases in the #263 facade: pure `validate_endpoint_name_policy(content.model.endpoint_name)` before stale comparison and injected `RemoteEndpointDraftValidator(Protocol).validate(content: DefinitionContent) -> None` only after the locked snapshot is current. Production's validator delegates the exact unchanged `content.model.endpoint_name` to `ModelEndpointCatalog.validate_custom_endpoint_remote`.

- [ ] **Step 1: Write failing pipeline and PostgreSQL tests**

Use a recording fake remote validator. For both public saves, prove #263 command/round-trip/immutable and other deterministic local validation runs first and a coherent aggregate is locked. Prove exact ordering with two explicit cases: (1) URL-shaped endpoint plus stale lock returns the ordered one-item `422 invalid_draft` URL issue, writes nothing, and records zero SDK/remote-validator calls; (2) locally valid endpoint plus stale lock returns the coherent exact seven-role `409`, writes nothing, and records zero SDK/remote-validator calls. A non-stale complete reconstructed `DefinitionContent` is remotely validated exactly once immediately before the existing writer. Assert every remote table error gives the exact ordered one-item issue and no content/hash/lock/audit/release/interval mutation. Assert valid same-content validates, advances audit/lock, and returns `changed:false`; force flush failure after validation and prove rollback from a fresh session.

In the PostgreSQL module add `pytestmark = pytest.mark.postgres` when absent. Use a blocking deterministic remote validator, prove two database PIDs plus a lock waiter, prove winner writes, and prove the locally valid stale loser neither invokes remote validation nor overwrites. Retain this stale-loser concurrency proof in addition to the unit ordering cases. Inspect the CI guard/workflow; add the existing filename only if absent.

- [ ] **Step 2: Run RED**

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_graph_configuration_draft.py -k endpoint
TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/integration/test_agent_definition_workbench_postgres.py -k endpoint
```

Expected: unit tests fail because no endpoint extension exists. The PostgreSQL command must connect, exercise distinct real PIDs, and report zero skips; an unavailable-server skip is a failed gate and Task 2 cannot be reviewed complete.

- [ ] **Step 3: Implement the one registered extension**

After #263 reconstructs/round-trips `DefinitionContent`, checks immutable fields, and takes the existing locked snapshot, execute the pure endpoint-name policy in the established deterministic local-validation order. Translate local `EndpointValidationFailure` immediately to the table `DraftValidationIssue`; this precedes stale comparison and performs no SDK work. If local validation succeeds, compare the submitted lock and return the coherent stale result before any remote work. Only for the current locked snapshot call the injected remote validator once, translate its `EndpointValidationFailure`, then call the pre-existing `_write_locked_content`. Production composition makes the adapter with `get_system_client`; it never accepts host/token/name from a browser except the candidate endpoint already reconstructed by #263. Do not retry, log endpoint text, add an ORM column, query another selected row, or add a writer/hash/route.

- [ ] **Step 4: Run GREEN and falsify distinct paths**

Run both Task 2 commands with PostgreSQL zero skips. Replace remote validation with `if False: self._remote_endpoint_validator.validate(content)  # TASK2_VALIDATOR_BYPASS_SABOTAGE`; forbidden validation test must be RED because save writes. Restore and rerun GREEN. Reserve a different reviewer target: move the remote validator above the stale return under `TASK2_REVIEWER_STALE_REMOTE_SABOTAGE`; both the valid-stale unit test and stale-loser concurrency test must be RED because the loser calls the fake catalog, then restore and rerun GREEN. Separately confirm the invalid-plus-stale URL case remains `422` with zero remote calls.

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
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_agent_definition_workbench_routes.py \
  -k 'model_endpoints or endpoint_validation or non_admin'
```

Expected: new discovery contract fails because DTOs/route/dependency are absent.

- [ ] **Step 3: Implement strict route/DTOs**

Append Pydantic `SystemModelEndpointResponse`, `SystemModelDiscoveryResponse`, and `ModelEndpointCatalogErrorResponse` with `extra="forbid"`; item DTOs have no request fields. Add the GET beneath `/workbench` on the existing admin router. Obtain catalog after router-level authorization; map only `ModelEndpointCatalogFailure` to exact envelope/status, and retain existing nonleaking unexpected-error policy. Keep #263 raw-body parsing/principal dependency before its PUT body; it invokes the composed facade rather than `get` directly.

- [ ] **Step 4: Run GREEN and falsify observable discovery failure**

Run the Task 3 command. Controller sabotage: return `{"items": []}  # TASK3_CONTROLLER_EMPTY_ON_ERROR_SABOTAGE` for unavailable; the unavailable test must be RED on the executed path, then restore and rerun GREEN. Reserve a different reviewer target: temporarily declare a typed Pydantic body in the PUT signature under `TASK3_REVIEWER_BODY_BEFORE_AUTH_SABOTAGE`; the secret malformed non-admin test must go RED, then restore auth-first raw parsing and rerun GREEN.

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

Add two component-level manual-entry save flows using a non-URL exact name that does not appear in discovery. In the success flow, type the name, save once, inspect the JSON request, and assert #263's request contains only `lock_version` plus `candidate`, whose only editable leaves are exactly `prompt_text`, `model.endpoint_name`, `model.temperature`, `model.max_tokens`, and `model.top_p`; `endpoint_name` equals the typed text byte-for-byte and there is no discovery metadata, URL, host, token, display name, docs, description, task, or provider field. Return the normal #263 save response and prove the editor retains that exact saved name. In the failure/correction flow, return a typed one-item server `invalid_draft` issue for `candidate.model.endpoint_name` (for example `endpoint_unknown`), assert an accessible typed field error whose sanitized text contains neither the entered endpoint nor secret/provider payload, and prove all unsaved form values remain intact. Correct the endpoint explicitly and retry; the second PUT again has only the same five editable leaves and succeeds without remounting. Keep the URL-shaped local case as a separate zero-PUT proof.

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

In `DefinitionEditor`, keep catalog state `idle | loading | ready | empty | error`, search, request ID, and last good list local to the workbench. Fetch on first Model-tab opening and explicit refresh. Loading/error announces with `aria-live="polite"`; failure uses `role="alert"`; refresh stays enabled for recovery. The custom field remains the #263 `endpoint_name` control and selection is only a setter. Match Task 1 URL detection locally; when Save receives #263's typed server `invalid_draft`, bind `candidate.model.endpoint_name` to the custom field without clearing or normalizing any unsaved value, and allow explicit correction/retry through the same one writer. The PUT serializer remains closed to `lock_version` plus exactly the five editable candidate leaves. Do not transmit a display name, URL, token, host, or catalog metadata in save payload.

- [ ] **Step 4: Run GREEN and falsify exact UI identity**

Run both Task 4 commands. Controller sabotage: set selection to `item.display_name ?? item.name  // TASK4_CONTROLLER_DISPLAY_NAME_SABOTAGE`; the exact-selection test must be RED on the executed path, then restore and rerun GREEN. Reserve a different reviewer target: invoke `onSave(agentKey)` from the selection handler under `TASK4_REVIEWER_SELECTION_AUTOSAVE_SABOTAGE`; the no-autosave test must go RED, then restore/remove the marker and rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/agentDefinitions.ts frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx frontend/tests/fixtures/mocks.ts
git commit -m "feat: add model endpoint editor discovery (#266)"
```

---

### Task 5: #266-owned structured-output capability probe

**Files:**
- Create: `src/services/model_endpoint_probe.py`
- Create: `tests/unit/test_model_endpoint_probe.py`
- Modify: `src/services/agent_runtime.py`
- Modify: `tests/unit/test_agent_runtime.py`
- Modify: `src/services/graph_configuration_workbench.py`
- Modify: `src/services/graph_configuration.py`
- Modify: `tests/unit/test_graph_configuration_workbench.py`
- Modify: `src/api/schemas/agent_definitions.py`
- Modify: `src/api/routes/agent_definitions.py`
- Modify: `tests/unit/test_agent_definition_workbench_routes.py`

**Interfaces:** Produces the stable saved-candidate probe contract above. Extract one structured-binding helper from the current runtime adapter so both normal `AgentRuntime` invocation and `DatabricksStructuredOutputProbe` construct `ChatDatabricks` with the injected runtime `workspace_client`, bind with `with_structured_output(schema)`, and then invoke. The probe service reads a complete immutable candidate snapshot plus `candidate_hash` and `lock_version` from the existing #263/#264/#265 workbench/facade. It never accepts or persists a client endpoint/schema/prompt/payload/identity and never implements #267 test cases, runs, evidence, verdicts, or approvals.

- [ ] **Step 1: Write failing helper/service/route tests**

At the runtime boundary, inject recording `model_factory`/`client_factory` and assert both normal invocation and probe use the same extracted structured-binding helper, exact saved endpoint as `endpoint`, runtime-identity client as `workspace_client`, and `with_structured_output(schema)` before invoke. No discovery display/family alias may appear. Deterministic adapter outcomes cover success, explicit unsupported binding/capability rejection, inference permission denial, and ambiguous provider/transport failure; assert exact sanitized codes/status/retryability and no raw exception text.

At the service/route boundary, seed different exact endpoints for two roles and assert the server loads the selected role's saved candidate/hash/lock and calls the probe exactly once. Request body is exactly `{"lock_version": n}`; endpoint/URL/host/token/prompt/schema/payload/identity/extras are rejected. Stale lock returns the coherent existing `409` before a probe call. Non-admin malformed/extra bodies return authorization before parsing with no body echo. Success/failure writes no candidate/hash/lock/audit/revision/release/chat/deck row, and a concurrent later save cannot change the identity reported for the already-copied probe snapshot. No test performs a live Databricks invocation.

- [ ] **Step 2: Run RED**

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_model_endpoint_probe.py \
  tests/unit/test_agent_runtime.py -k 'structured_output or model_endpoint_probe'
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_graph_configuration_workbench.py \
  tests/unit/test_agent_definition_workbench_routes.py \
  -k 'model_endpoint_probe or auth_before_probe_body'
```

Expected: collection/behavior fails because the probe module, shared binding helper, facade operation, DTOs, and route do not exist. There is no #267 prerequisite.

- [ ] **Step 3: Implement the narrow probe**

Extract the helper without changing #261's persisted-release selection, #264 canonical/diagnostic projection, #265 prompt assembly, callback identity-sink ordering, or provider conversion. The code-owned probe response schema is only `result: Literal["ok"]`; its prompt contains no user or draft content. Classify only explicit adapter outcomes: unsupported capability → `422 unsupported_structured_output`; permission denial → `403 endpoint_probe_forbidden`; ambiguous provider/transport → `503 structured_output_probe_failed`; success → exact `200`. Load/copy the candidate snapshot before network work and return its endpoint/hash/lock identity; do not hold a database lock during the remote invocation and do not mutate anything. Keep existing admin/principal dependencies before raw-body parsing.

- [ ] **Step 4: Run GREEN and falsify request ownership**

Run both Task 5 commands. Controller sabotage: accept an optional request endpoint and prefer it over the saved candidate under marker `TASK5_CONTROLLER_ENDPOINT_OVERRIDE_SABOTAGE`; verify the strict-body/server-owned-endpoint test goes RED on the executed path, restore/remove the marker, and rerun GREEN. Reserve a distinct reviewer target: bypass the extracted `with_structured_output` helper under `TASK5_REVIEWER_STRUCTURED_BINDING_SABOTAGE`; the shared-binding test must go RED, then restore and rerun GREEN.

- [ ] **Step 5: Commit**

```bash
git add \
  src/services/model_endpoint_probe.py \
  src/services/agent_runtime.py \
  src/services/graph_configuration_workbench.py \
  src/services/graph_configuration.py \
  src/api/schemas/agent_definitions.py \
  src/api/routes/agent_definitions.py \
  tests/unit/test_model_endpoint_probe.py \
  tests/unit/test_agent_runtime.py \
  tests/unit/test_graph_configuration_workbench.py \
  tests/unit/test_agent_definition_workbench_routes.py
git commit -m "feat: probe saved endpoint structured output (#266)"
```

---

### Task 6: Probe UI, browser recovery, and complete verification

**Files:** Modify the mandatory-gate-reprobed integrated owners, expected to include `frontend/src/api/agentDefinitions.ts`, `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx`, `useDraftEditor.ts`, `draftEditorState.ts`, `draftEditorState.test.ts`, `AgentDefinitionWorkbench.test.tsx`, `frontend/tests/fixtures/mocks.ts`, and `frontend/tests/e2e/agent-definition-workbench.spec.ts`.

**Interfaces:** Adds an explicit **Test structured output** action for the current saved candidate. Extend the one integrated aggregate pending-operation/request-ID gate (Save plus #264/#265 upgrades) with Probe; never create a second controller. Probe sends only current `lock_version`, is disabled while local endpoint edits are unsaved or another operation is pending, and reports the exact returned endpoint/hash/lock identity. Editing, selecting, refreshing, tabbing, or rendering never saves, probes, aliases, or advances an endpoint.

- [ ] **Step 1: Write failing client/state/component/browser tests**

Keep every Task 4 catalogue test. Add exact parser tests for all probe responses/statuses and malformed bodies. Prove Probe sends only `lock_version`; uses saved endpoint even when discovery shows a newer family member; makes no PUT; shares one pending gate across every role and Save/Upgrade/Probe; rejects stale/out-of-order request IDs; preserves A2→A3 and seven-role 409 recovery; clears an old probe result when the local endpoint changes; never claims approval; and renders sanitized unsupported/forbidden/unavailable messages with explicit retry only when `retryable:true`.

In Playwright exercise first Model-tab fetch, local search, refresh exposing a newer entry while the seed remains exact, explicit selection/save of the exact name, then explicit Probe of that saved candidate. Add a separate manual non-URL custom endpoint success flow: enter an exact name absent from discovery, save, assert the PUT has only `lock_version` plus a candidate with the five editable leaves, contains the exact name, and has no discovery metadata, URL, host, token, display name, docs, description, task, or provider. Return success and prove exact retention before probing the saved candidate. Add a manual server-validation-failure flow: first PUT returns a typed one-item `candidate.model.endpoint_name` issue with sanitized non-leaking copy; assert the entire unsaved form remains, correct the name, retry explicitly through the same PUT, and prove success without remount. Cover success, unsupported structured output, forbidden, unavailable/retry recovery, empty discovery, URL rejection with zero PUT/probe, and catalogue 503 recovery without remount. Assert catalogue GET has no endpoint/token/host/URL query/body and probe POST has only the lock.

- [ ] **Step 2: Run RED**

```bash
(cd frontend && npm run test:unit -- \
  src/components/Admin/AgentDefinitionWorkbench/draftEditorState.test.ts \
  src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.test.tsx)
(cd frontend && npx playwright test \
  tests/e2e/agent-definition-workbench.spec.ts \
  --project=chromium --workers=1 -g 'model endpoint')
```

Expected: probe client/parser/state/control/browser behavior is absent while all earlier catalogue behavior stays green.

- [ ] **Step 3: Implement and run GREEN**

Parse before reducer dispatch; reuse the integrated request-ID/ref gate and saved candidate snapshot. The explicit button calls only the Task 5 route and never `ServingEndpointsAPI.query`, OpenAPI negative inference, `AgentRuntime.run_candidate`, or any #267 route. Controller sabotage: assign the first refreshed item to endpoint form state under `TASK6_CONTROLLER_AUTO_ADVANCE_SABOTAGE`; the no-drift test must go RED on the executed path, then restore and rerun GREEN. Give the reviewer a different target, such as allowing Probe while endpoint edits are unsaved.

- [ ] **Step 4: Run the complete zero-skip/cause-based matrix**

```bash
/Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/unit/test_model_endpoint_catalog.py \
  tests/unit/test_model_endpoint_probe.py \
  tests/unit/test_graph_configuration_draft.py \
  tests/unit/test_graph_configuration_workbench.py \
  tests/unit/test_agent_definition_workbench_routes.py \
  tests/unit/test_agent_runtime.py \
  tests/unit/test_persisted_agent_runtime.py \
  tests/unit/test_prompt_assembler.py \
  tests/unit/test_agent_schema_registry.py \
  tests/unit/test_ci_collects_integration_tests.py

TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/integration/test_graph_configuration_bootstrap_postgres.py

TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/integration/test_graph_configuration_constraints_postgres.py

TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/integration/test_persisted_graph_runtime_failures_postgres.py

TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/integration/test_conversation_pin_migration_postgres.py

TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/integration/test_conversation_pin_creation_postgres.py

TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/integration/test_agent_definition_workbench_postgres.py

TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres \
  /Users/robert.whiffin/.pyenv/shims/python -m pytest -q \
  tests/integration/test_agent_schema_overlay_postgres.py

(cd frontend && npm run test:unit)
(cd frontend && npm run typecheck)
(cd frontend && npx playwright test \
  tests/e2e/agent-definition-workbench.spec.ts \
  --project=chromium --workers=1)
```

Record a separate result line for each PostgreSQL command, including module name, passes, **zero skips**, and warning causes. A missing/unreachable server, missing concrete module, or server-unavailable skip fails that command and the final gate. The listed set is mandatory: graph configuration bootstrap/constraints, persisted runtime failures, conversation pin migration/creation, Task-owned workbench validation/concurrency, and predecessor schema overlay. Task 0 and the stricter re-probe may add renamed or final #261/#263/#264/#265 PostgreSQL modules to `PLAN-CORRECTIONS.md`, but may not remove, combine, replace, or waive any module in this concrete set. Compare exact failure/skip/warning causes with the corrections baseline, not counts.

- [ ] **Step 5: Commit, exact-base whole-branch review, and local merge**

Commit UI/browser changes with `test: prove exact endpoint discovery and probe (#266)`. Read final `IMPLEMENTATION_BASE` from the corrections ledger and assert it equals the recorded `INTEGRATION_BASE`, is an ancestor of `HEAD`, and is not the pre-integration `TASK1_BASE`. Record `git log --format='%H %s' "$IMPLEMENTATION_BASE"..HEAD` and compare it to the ledger's rebased Task 1, Tasks 2–6, and review-approved #266 fix commits: the range must contain those #266 commits only and no #261/#263/#265/#264 predecessor commit. Generate the review package from exactly that proven `IMPLEMENTATION_BASE..HEAD` range and dispatch the most capable reviewer with all deferred/parked/ruling ledger lines and the range proof. Require a writer-by-writer table, stale/rollback/no-write ruling, runtime/probe structured-binding comparison, complete failure-code table, and merge/no-merge verdict. Use one fix wave and one scoped re-review if needed. Only after a clean verdict, merge #266 **locally** into `feat/langgraph-core` after #264; do not push or open a PR. #267 begins from that reviewed local merge.

## Final whole-branch review handoff

- [ ] Use the mandatory local integration gate before Task 2 and retain its exact `INTEGRATION_BASE`; never defer the rebase until final review. Preserve Task 0's `TASK1_BASE` for its task review only, then prove final `IMPLEMENTATION_BASE == INTEGRATION_BASE`, `IMPLEMENTATION_BASE` is an ancestor of `HEAD`, and `IMPLEMENTATION_BASE..HEAD` contains only rebased #266 work before generating the whole-branch package.
- [ ] Re-probe installed 0.112.0 source: no list arguments, get/name present, `ServedEntityOutput.foundation_model` present, no assumed `system_ai` property.
- [ ] Audit diff for `routes/tools.py`, `task.startswith`, `served_models`, exception-to-empty, URL forwarding, alias rewrite, auto-upgrade, `query(response_format`, and endpoint override fields; none is allowed.
- [ ] Confirm deterministic catalog/probe fakes, route injection, pure local endpoint-name policy, remote-after-current-lock writer validator, frontend mocks/intercepts, and runtime model/client factories; CI never invokes Databricks.
- [ ] Confirm empty/forbidden/unavailable/unknown/name mismatch/readiness/update states/URL/unsupported/probe failure remain separately observable; confirm invalid-plus-stale URL is ordered `422`/no-write/zero-SDK, valid-plus-stale is coherent seven-role `409`/zero-remote-call, the concurrent stale loser never calls remote validation, and same-content audit, rollback, exact seed, no alias drift, and recovery have cause-based coverage.
- [ ] Confirm component and Playwright evidence for manual non-URL success and typed server-failure/correction/retry: only #263's five editable candidate leaves, exact name retention, no discovery/URL/host/token fields, non-leaking typed error, retained unsaved form, and the separate URL zero-PUT proof.
- [ ] Confirm no implementation dependency on #267 exists; #266 itself owns the explicit structured-output probe and #267 remains downstream.
- [ ] Run `rg -n -i -e 'tb''d' -e 'to''do' -e 'implement'\ 'later' -e 'fill'\ 'in' -e 'appropriate'\ 'error' -e 'handle'\ 'edge' -e 'similar'\ 'to'\ 'task' docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`; expect no matches. Remove all sabotage markers before final commit.

Plan complete at `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`; execute only through the stated serialized shared-file sequence.
