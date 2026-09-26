# Databricks model-endpoint discovery: revalidation for #266

**Date:** 2026-09-22

**Scope:** research only. This note makes no production-code or test change.
**Question:** what current, supported Databricks contract can discover selectable
Databricks-hosted endpoints, and what can be established before saving a custom
endpoint name?

## Decision

Use the workspace **Serving Endpoints API** through
`WorkspaceClient.serving_endpoints` as the only verified workspace-discovery
contract.  From `list()`, classify a selectable Databricks-hosted endpoint by a
non-null `config.served_entities[*].foundation_model`; retain the parent endpoint
`name` verbatim as the selectable and persisted value.  Do not use the generic
`task` heuristic, a name prefix, a catalogue entry, or a model family label as
identity.

For custom input, accept an endpoint **name** only; reject URL-shaped input
locally and use `get(name)` to check existence and state.  The endpoint must be
revalidated at the actual isolated workbench invocation.  Discovery/list/get and
OpenAPI inspection cannot prove that the runtime identity can invoke an endpoint
with the exact structured-output protocol used by `ChatDatabricks`.

## Verified external facts

### Discovery, response shape, and search

- The GA operation is `GET /api/2.0/serving-endpoints`, requires the
  `model-serving` API scope, takes no documented request parameters, and returns
  an optional `endpoints` array.  It has no documented pagination, server-side
  search, or filter parameter.  Fetch the one returned collection, then sort and
  search it locally. [List API][list-api]
- A listed endpoint has `name`, `state`, `config`, and optional `task`.  The
  relevant current config collection is `config.served_entities`; `served_models`
  is explicitly deprecated.  A served entity can include a Public Preview
  `foundation_model` object with `name`, `display_name`, `docs`, and
  `description`, or an `external_model` whose `provider`, `name`, and `task`
  identify an external provider configuration. [List API][list-api]
- `state.ready` says whether the endpoint is queryable: `READY` only when all
  active served entities are ready, otherwise `NOT_READY`.  `state.config_update`
  documents `NOT_UPDATING`, `IN_PROGRESS`, `UPDATE_FAILED`, and
  `UPDATE_CANCELED`; an in-progress update bars another update. [List API][list-api]
- A Foundation Model API catalogue entry is labelled **Endpoint name**.  It is a
  public supported-model catalogue, not a workspace listing or an authorization
  decision; it also records replacements of individual endpoint names. [Supported
  models][supported-models]
- The installed `databricks-sdk` is **0.112.0**.  Its generated
  `ServingEndpointsAPI.list(self) -> Iterator[ServingEndpoint]` makes one GET to
  `/api/2.0/serving-endpoints`; there are no list arguments.  `get(self,
  name: str) -> ServingEndpointDetailed` calls
  `/api/2.0/serving-endpoints/{name}`. [SDK source v0.112.0][sdk-serving]

### No verified dedicated `system.ai` catalogue API

- Current installed-SDK introspection found `WorkspaceClient.serving_endpoints`,
  but no `system_ai`, `foundation_models`, or `model_serving` service property.
  The installed generated serving module contains the `foundation_model` response
  field above, not a separate discovery operation.  The same is true of the
  official SDK v0.112.0 source inspected below. [SDK source v0.112.0][sdk-serving]
- Therefore the design document's phrase “`system.ai` models” is product
  vocabulary, not evidence for an API namespace.  No dedicated workspace
  system-model API was verified.  Do not implement against an assumed
  `system.ai` REST or SDK operation.

### Exact-name validation, state, scopes, and permissions

- `GET /api/2.0/serving-endpoints/{name}` (SDK `get(name)`) is the supported
  endpoint-detail operation.  It requires `model-serving`; the API models `name`
  as the required path parameter.  The detail result contains `name`, `id`,
  `permission_level`, `state`, active `config`, and `pending_config`.  The ID is
  the value used by the Permissions API. [Get API][get-api] [SDK source
  v0.112.0][sdk-serving]
- Invocation is `POST /serving-endpoints/{name}/invocations` and requires both
  `model-serving` and `model-serving-inference`.  Thus list/get scope is not an
  invocation authorization proof. [Query API][query-api]
- Serving-endpoint ACL levels include `CAN_VIEW`, `CAN_QUERY`, and `CAN_MANAGE`.
  Databricks' management documentation shows granting `CAN_QUERY` to query an
  endpoint; permission modification requires `CAN_MANAGE`. [Endpoint
  permissions][endpoint-permissions]
- The installed SDK exposes
  `get_permissions(serving_endpoint_id)` and
  `get_permission_levels(serving_endpoint_id)`; both use the endpoint system ID,
  not its display label. [SDK source v0.112.0][sdk-serving]
- The current documentation verifies the *scope* requirements, but does not give
  a complete list/get visibility matrix or a universal endpoint-error/status-code
  mapping.  In particular, do **not** infer `CAN_QUERY` from a successful list or
  get, and do not promise a specific HTTP code for unknown, forbidden, or
  unavailable endpoints.  The production adapter must distinguish a successful
  empty discovery from a raised SDK/transport failure; tests should use
  deterministic fakes for those outcomes. [List API][list-api] [Get API][get-api]

### Readiness, configuration failures, and structured output

- Reject a custom endpoint as not currently usable when `state.ready != READY`.
  Surface `IN_PROGRESS`, `UPDATE_FAILED`, and `UPDATE_CANCELED` separately as
  observed state rather than claiming they identify a particular HTTP failure.
  Databricks also documents that configuration updates can fail with
  `PERMISSION_DENIED` when the recorded endpoint creator no longer has workspace
  membership or required entity grants. [List API][list-api] [Endpoint
  management][endpoint-management]
- `GET /api/2.0/serving-endpoints/{name}/openapi` is **Public Preview**, requires
  `model-serving`, and returns `text/plain`; it describes the endpoint's
  supported paths plus input/output formats and data types.  The current SDK
  method is `get_open_api(self, name: str) -> GetOpenApiResponse`, whose
  `contents` is a binary stream. [OpenAPI API][openapi-api] [SDK source
  v0.112.0][sdk-serving]
- This OpenAPI response is an inspection artifact, not a documented
  `structured_output` capability flag.  It can support a conservative positive
  check only if the returned schema explicitly declares the request shape needed
  by the chosen runtime.  Its absence or inability to obtain the schema is not
  primary-source proof that the endpoint lacks structured output.
- Databricks documents `response_format` structured outputs for its OpenAI
  compatible chat-completions usage, with model-specific constraints (for
  example, Claude permits `json_schema`, forbids streaming with
  `response_format`, and cannot combine it with tools/tool choice).  The
  installed `ServingEndpointsAPI.query()` signature has **no**
  `response_format` parameter, so that SDK method must not be used as proof or
  as the #266 structured-output validator. [Structured outputs][structured-output]
  [SDK source v0.112.0][sdk-serving]

### Endpoint names, aliases, and persistence

The verified API and catalogue expose endpoint *names*.  No primary source
examined promises that a family/marketing alias is stable, resolves to a canonical
endpoint, or is safe to persist.  The supported-model catalogue itself records
that named endpoints can be replaced.  Consequently #266 should persist only the
exact parent `ServingEndpoint.name` returned by discovery or the exact custom
string confirmed by `get(name)`; it must never rewrite, advance, or infer a newer
family endpoint.  A submitted custom string should be accepted only when the
returned `detail.name` exactly equals it.  This equality rule is a conservative
application policy, not a Databricks alias guarantee. [Supported models][supported-models]

## Verified repository facts

- The design requires exact endpoint names, says the seeded
  `databricks-claude-opus-4-6` must not float to a newer model, and calls for
  injected production adapters with deterministic fakes. [Design spec][design-spec]
- The v1 manifest currently seeds all seven definitions with that exact endpoint.
  `AgentRuntime` passes `configuration.endpoint_name` to `ChatDatabricks` and
  then unconditionally invokes `with_structured_output(schema)`; its constructor
  already has `model_factory` and `client_factory` injection seams. [Manifest][manifest]
  [Runtime adapter][runtime-adapter]
- `src/api/routes/tools.py` is not the #266 boundary: it calls the user client’s
  `serving_endpoints.list()`, classifies “foundation” by the top-level `task`, and
  turns every exception into `{"items": []}`.  That conflicts with both the
  current `foundation_model` response contract and #266's observable-failure
  requirement. [Existing generic discovery][existing-discovery]
- #263 owns the draft writer and the future shared transactional validation seam;
  the collision audit assigns #266 the isolated catalog/fakes first and serialises
  its route/client/editor integration after the #263 seam. [#263 plan][draft-plan]
  [Collision audit][collision-audit]

## Recommended implementation boundary

Create an injected `ModelEndpointCatalog` adapter with no React or draft-writer
knowledge:

```python
class ModelEndpointCatalog(Protocol):
    def list_system_models(self) -> DiscoveryResult: ...
    def validate_custom_endpoint(self, name: str) -> EndpointValidation: ...
```

- `list_system_models`: make exactly one `serving_endpoints.list()` call;
  include a parent endpoint once if at least one active served entity has
  `foundation_model`; retain `endpoint.name` exactly; carry foundation metadata
  only for display; locally sort/search in the caller.
- `validate_custom_endpoint`: reject URL-shaped values; call `get(name)`; require
  exact response-name equality and `READY`; expose config-update state; do not
  attempt alias resolution.  Map known application outcomes such as
  `unknown`, `not_ready`, `forbidden`, and `unavailable` only from adapter
  exception/result categories—not invented provider HTTP codes.
- Capability: do not label an endpoint structured-output-compatible merely from
  list/get metadata or its name.  At most record an explicit OpenAPI positive
  signal; the isolated test using the same `ChatDatabricks` binding remains the
  authoritative acceptance check.  If product requires save-time rejection for
  capability, it needs a separately specified, runtime-compatible probe and
  policy for its cost/side effects; current primary sources do not supply one.
- Integrate that port synchronously into #263's single validation pipeline under
  its existing transaction, rather than adding a parallel route or reusing
  `routes/tools.py`.  Fakes need successful discovery, empty success, list/get
  access failure, transport failure, unknown name, non-ready/update-failed name,
  OpenAPI unavailable/without positive evidence, and exact-name success.

## Unsupported assumptions and unknowns

| Claim | Status / consequence |
| --- | --- |
| A dedicated, paginated `system.ai` model API exists | **Not verified.** Use Serving Endpoints list; no pagination/search/filter contract exists there. [List API][list-api] [SDK source v0.112.0][sdk-serving] |
| `task` or a name prefix identifies a Databricks-hosted model | **Unsupported.** Use `foundation_model` for discovered system entries. [List API][list-api] |
| Listing or getting proves the runtime can query | **Unsupported.** Query requires an additional API scope and endpoint ACLs; verify under runtime identity in an isolated run. [Query API][query-api] [Endpoint permissions][endpoint-permissions] |
| OpenAPI always exposes `response_format` or deterministically proves structured output | **Unsupported.** It is Public Preview opaque text and has no documented capability flag. [OpenAPI API][openapi-api] |
| Any model-family alias is durable or may be automatically upgraded | **Unsupported.** Persist exact names only; never auto-advance the seed. [Supported models][supported-models] |
| Stable provider HTTP status/error-code mappings for all failures | **Unknown.** Keep them out of the UI contract and normalize only adapter-observed error categories. [List API][list-api] [Get API][get-api] |

## Corrections to the 447791d prior note

1. The central discovery conclusion remains Serving Endpoints plus
   `foundation_model`, but current API documentation makes `foundation_model`
   **Public Preview** and labels OpenAPI **Public Preview**; neither should be
   described as a GA structured-capability contract.
2. The prior recommendation that OpenAPI absence/incompatibility return a definite
   `unsupported_structured_output` overclaimed.  The schema is useful evidence,
   but the documented contract does not make it a universal capability oracle.
3. The installed/current SDK is now recorded precisely as 0.112.0.  Its
   `query()` does not accept `response_format`; a runtime-compatible behavioral
   test, not this method, is required for final structured-output validation.
4. A `get(name)` exact-name equality check remains prudent, but it is explicitly
   an application policy—not evidence that Databricks documents canonical alias
   resolution.

## Sources and inspection record

All external sources below are first-party Databricks documentation or the
official Databricks SDK source, re-read on 2026-09-22.  Installed-SDK facts were
also introspected with the shared Python 3.11 environment; no environment was
created or changed.

- [List API][list-api]
- [Get API][get-api]
- [OpenAPI API][openapi-api]
- [Query API][query-api]
- [Endpoint permissions][endpoint-permissions]
- [Endpoint management][endpoint-management]
- [Structured outputs][structured-output]
- [Supported models][supported-models]
- [Official SDK source v0.112.0][sdk-serving] — inspected locally at
  `/Users/robert.whiffin/.pyenv/versions/3.11.0/lib/python3.11/site-packages/databricks/sdk/service/serving.py`:
  `EndpointState` 1361–1409, `FoundationModel` 1704–1750,
  `ServedEntityOutput` 2714–2899, and `ServingEndpointsAPI` 4038–4725.

[list-api]: https://docs.databricks.com/api/model-serving/v1/list-inference-endpoints
[get-api]: https://docs.databricks.com/api/model-serving/v1/get-inference-endpoint
[openapi-api]: https://docs.databricks.com/api/model-serving/v1/get-inference-endpoint-schema
[query-api]: https://docs.databricks.com/api/model-serving-query/v1/query
[endpoint-permissions]: https://docs.databricks.com/en/machine-learning/model-serving/manage-serving-endpoints.html#manage-permissions-on-a-model-serving-endpoint
[endpoint-management]: https://docs.databricks.com/en/machine-learning/model-serving/create-manage-serving-endpoints.html#identity-and-access
[structured-output]: https://docs.databricks.com/en/machine-learning/model-serving/structured-outputs.html
[supported-models]: https://docs.databricks.com/en/machine-learning/foundation-model-apis/supported-models.html
[sdk-serving]: https://github.com/databricks/databricks-sdk-py/blob/v0.112.0/databricks/sdk/service/serving.py
[design-spec]: ../superpowers/specs/2026-09-21-agent-definition-workbench-design.md
[draft-plan]: ../superpowers/plans/2026-09-22-shared-graph-draft-editing.md
[collision-audit]: /Users/robert.whiffin/Documents/slide-gen-branch-eval/ai-slide-generator/.worktrees/issue-260-bootstrap/.superpowers/wave2-262-264-265-266-collision-audit.md
[manifest]: ../../src/services/agent_definition_manifest_v1.py
[runtime-adapter]: ../../src/services/agent_runtime.py
[existing-discovery]: ../../src/api/routes/tools.py
