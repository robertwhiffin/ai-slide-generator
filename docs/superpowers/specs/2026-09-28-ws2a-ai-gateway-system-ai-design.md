# Workstream 2a — Route model calls through Unity AI Gateway (`system.ai.*`)

**Date:** 2026-09-28 · **Branch:** `feat/ws2a-ai-gateway` (from `feat/langgraph-core` at `8f3382c93`)
**Parent:** umbrella PRD `docs/superpowers/specs/2026-07-30-tellr-agentic-rebuild-prd-design.md` §8.1, §10
**Starting-state facts:** `docs/superpowers/plans/2026-09-28-ws2-ai-gateway-HANDOVER.md`

## 1. Purpose

Workstream 2 is split in two. This spec covers **2a**, the minimum viable change:
Tellr calls models through Unity AI Gateway, and the Agent Definition Workbench offers
and accepts `system.ai.*` models. This replaces the Foundation Model API
`/serving-endpoints` transport for the call sites in scope. Once this lands, admins can
switch to any model the workspace's Gateway exposes without a code change.

Everything else in the original workstream 2 moves to a new **workstream 2b** (§10).

### 1.1 Success criteria

1. Every graph model call (all seven roles, the #266 saved-candidate probe and the #267
   workbench test runs) is sent to `{host}/ai-gateway/mlflow/v1`.
2. The workbench model picker lists exactly the chat-capable models that the Gateway
   endpoint list returns, shown as `system.ai.<model>`. A draft cannot be saved with any
   other name.
3. PPTX and Google Slides export call the model through the Gateway.
4. Session-title generation, on both the monolith path and the graph path, calls the
   model through the Gateway.
5. Conversations pinned to existing releases, whose roles name `databricks-*` endpoints,
   continue to work unchanged and without republishing.
6. A graph turn on a model newer than the v1 seed (for example
   `system.ai.claude-opus-5-5`) succeeds on a devloop instance.

### 1.2 Non-goals

- Token, cost or per-user/per-session attribution, and the admin dashboard.
- Rate-limit policy, 429 handling or new error codes.
- Gateway request tags, usage-tracking configuration, inference tables, payload logging
  and guardrails.
- The monolith agent, the MCP door, the verification judge, the feedback assistant and
  the config validator. Their call sites keep calling `/serving-endpoints`.
- Making endpoint choices for export or titles configurable. They become Gateway-named
  constants in this workstream.

## 2. Platform facts this design relies on

Probed live against the `tellr-dev` workspace on 2026-09-28. Task 0 (§4) re-proves the
facts marked *(Task 0)* across the full model list.

| Fact | Evidence |
|---|---|
| `POST {host}/ai-gateway/mlflow/v1/chat/completions` accepts `model: "system.ai.<model>"` and returns the OpenAI chat-completion shape, including `usage`. | `system.ai.claude-opus-4-6`, `system.ai.claude-opus-5-5`, `system.ai.claude-sonnet-4-5`, `system.ai.claude-haiku-4-5`, `system.ai.gpt-6-sol`, `system.ai.gpt-oss-120b` and `system.ai.gemma-3-12b` all answered. |
| The same route also accepts the legacy `databricks-*` names. | `databricks-claude-haiku-4-5` and `databricks-claude-opus-5-5` answered. |
| `GET {host}/api/ai-gateway/v2/endpoints` lists Gateway endpoints named `databricks-<model>`, each with one `PAY_PER_TOKEN_FOUNDATION_MODEL` destination. | The workspace returned 43 endpoints and no page token. |
| **Naming rule:** Gateway endpoint `databricks-<model>` is invoked as `system.ai.<model>`. The UC registered-model name (for example `system.ai.databricks-claude-opus-5-5` or `system.ai.gemma-3-12b-it`) is **not** invocable and returns 404. *(Task 0)* | This was derived from probes. No documentation for it was found. |
| `GET {host}/api/ai-gateway/v2/endpoints/<name>` returns one endpoint, including `supported_api_types`. Chat models include `mlflow/v1/chat/completions`. The list response omits `supported_api_types`. | Seen on `databricks-claude-opus-5-5` and `databricks-gpt-6-sol`. |
| The list is not exhaustive. `databricks-gpt-6-sol` is absent from the list, but the per-name lookup and invocation both work. | This is an accepted gap (§5.1). |
| Region-restricted models appear invocable by name but fail with 404 `NOT_FOUND` at call time. | `system.ai.claude-fable-5-1` returned "not available in your region". |
| `ChatDatabricks.with_structured_output` works through the Gateway route and returns the parsed object. | Probe with a two-field pydantic schema on `system.ai.claude-opus-4-6`. |
| Extended thinking works through the route. `message.content` is a list whose reasoning item has the shape `{"type": "reasoning", "summary": [{"type": "summary_text", "text", "signature"}]}`, followed by the text item. | `system.ai.claude-sonnet-4-5` with `thinking.budget_tokens=1024`. |
| An unknown model raises `openai.NotFoundError` (404). | `system.ai.nope`. |

### 2.1 Client libraries

- `databricks-langchain` **≥ 0.19.0** adds `ChatDatabricks(model=..., use_ai_gateway=True)`.
  The flag makes the client use base URL `{host}/ai-gateway/mlflow/v1`, with no fallback
  to `/serving-endpoints`. `endpoint=` is deprecated in favour of `model=`. The default
  structured-output method is still `function_calling`.
- `databricks-openai` **≥ 0.14.0** adds `DatabricksOpenAI(workspace_client=...,
  use_ai_gateway=True)` with the same base URL. The SDK's
  `serving_endpoints.get_open_ai_client()` is deprecated in favour of this class.
- The app currently pins `databricks-langchain==0.9.0` and does not depend on
  `databricks-openai`.
- The upstream floors (`langchain>=1.0.0`, `databricks-ai-bridge>=0.20/0.21`,
  `databricks-ai-search>=0.73`, `mlflow>=3.10.1`, `unitycatalog-langchain>=0.3.0`) are all
  met by existing pins. The one new transitive package is `unitycatalog-openai[databricks]`.

## 3. Scope

| Call site (handover §2) | In 2a | Change |
|---|---|---|
| G1: graph, all seven roles | Yes | Model factory uses the Gateway (§6) |
| G2: #266 saved-candidate probe | Yes | Same factory (§6) |
| G3: #267 workbench test runs | Yes | Same factory (§6) |
| X1/X2: PPTX and Google Slides export | Yes | `DatabricksOpenAI` through the Gateway, with a `system.ai` constant (§7) |
| T1/T2: session titles, monolith and graph paths | Yes | Through the Gateway, with a `system.ai` constant, still OBO (§8) |
| Workbench discovery and draft validation | Yes | Gateway list and lookup (§5) |
| M1, MCP, J1/J2, F1, V1 | No | Moved to 2b |

## 4. Task 0 — dependency and platform proof (gates all other work)

1. **Merge `main` into `feat/ws2a-ai-gateway`.** `main` is about 50 commits ahead and
   changes `packages/databricks-tellr-app/pyproject.toml`.
2. **Pin the new versions** in `packages/databricks-tellr-app/pyproject.toml`, the only
   file the Apps BUILD phase resolves:
   - `databricks-langchain==0.20.0`, the latest tag at the time of writing;
   - add `databricks-openai==0.17.1`;
   - use exact pins, following the file's existing practice;
   - update the stale `databricks-langchain==0.9.0` comment about `openai`.

   Mirror the pins in the repo-root `pyproject.toml` and `requirements.txt`, which also pin
   `databricks-langchain`. Never `pip install` into the shared environment.
3. **Prove the build.** Publish a `.devN` and deploy it to a **new** `devloop` instance.
   Do not redeploy `epic258` or `epic258-admin`. The Apps BUILD must resolve inside its
   time budget, and the app must start and pass its startup migration.
4. **Prove the naming rule.** Write a one-off script, which is not product code and is
   not committed under `src/`. It runs as the dev profile against the dev workspace:
   - list the Gateway endpoints;
   - look up each one by name;
   - for every endpoint whose `supported_api_types` contains
     `mlflow/v1/chat/completions`, invoke `system.ai.<model>` with a one-token request;
   - record any endpoint where the rule does not hold, other than region blocks.

   **Record the result in the plan's corrections file.**
5. **Prove OBO through the Gateway.** On the devloop instance, the first message of a new
   session must produce a generated title, not the fallback. This shows that a
   user-scoped Apps token (`serving.serving-endpoints` scope) is accepted by the Gateway
   route.

**Stop condition:** if step 3 cannot be made to resolve, or step 5 shows that OBO tokens
are rejected, stop and return to the user before building further. Known fallbacks:
- for the build, a hand-built Gateway OpenAI client with the same base URL and the SDK's
  bearer-auth pattern, keeping `databricks-langchain==0.9.0`;
- for OBO, a user decision on moving titles to the service principal.

## 5. Model catalog and draft validation

### 5.1 Discovery (`src/services/model_endpoint_catalog.py`)

`DatabricksModelEndpointCatalog.list_system_models` changes source. Instead of
`serving_endpoints.list()` filtered to `foundation_model` served entities, it calls
`GET /api/ai-gateway/v2/endpoints` as the app service principal, through the existing
bounded discovery client, using the SDK's generic `api_client.do`.

For each returned endpoint:
- a name of the form `databricks-<model>` is surfaced as `system.ai.<model>`;
- names without the `databricks-` prefix are dropped, because the naming rule gives
  them no invocable `system.ai` name.

The list response carries no `supported_api_types`, so discovery does **not** filter by
API type. It shows every mapped entry, so embedding models such as `system.ai.bge_large_en_v1_5`
appear in the picker. Save-time validation (§5.3) rejects them with a clear message.
This is a deliberate choice:
- a name heuristic would be fragile;
- a per-entry lookup would add roughly 40 requests to every picker load.

Hiding non-chat models is a 2b follow-up if it proves confusing.

**Custom names are removed.** The workbench offers only listed models, and the
free-text custom-endpoint path in the UI and the API is removed. Models the list omits
(for example `gpt-6-sol` today) cannot be chosen. That is accepted: the Gateway list is
the source of truth.

The existing failure codes (`catalog_forbidden`, `catalog_unavailable`), the bounded
client timeouts and the typed-error rules (never echo provider text) are unchanged.

### 5.2 Local name policy (`validate_endpoint_name_policy` and the draft validator)

A **new draft save** requires the name to match `^system\.ai\.[a-z0-9][a-z0-9._-]*$`,
with a new typed code `endpoint_not_gateway_model`. The existing URL and path-metacharacter
rejection stays, and runs first.

Stored releases are never re-validated, so pinned `databricks-*` names remain valid for
execution (§6.2).

### 5.3 Remote check on save (`validate_custom_endpoint_remote` → renamed)

This replaces the `serving_endpoints.get` + `READY` + `NOT_UPDATING` check with a Gateway
lookup:
1. Map `system.ai.<model>` to `databricks-<model>`.
2. Call `GET /api/ai-gateway/v2/endpoints/databricks-<model>` through the existing bounded
   catalog client (5 s retry, 3 s HTTP), which runs under the draft lock.
3. Map the result:

   | Result | Code |
   |---|---|
   | 404 | `endpoint_not_found` (existing) |
   | Permission denied | existing forbidden code |
   | Transport failure | existing unavailable code |
   | `supported_api_types` does not contain `mlflow/v1/chat/completions` | new code `endpoint_not_chat_model` |

The name is still passed through the path-policy check before interpolation.

Region blocks are not detectable here. They surface at invocation, and the #266 probe
already classifies an invocation `NotFound`.

### 5.4 Frontend

The workbench model picker (`/admin`) removes the custom-name entry and displays
`system.ai.*` names. New codes get user-facing messages next to the existing endpoint
codes. No other UI change is made.

## 6. Graph runtime

### 6.1 Model factory (`src/services/agent_runtime.py`)

`DatabricksModelAdapter._default_model_factory` constructs
`ChatDatabricks(model=..., use_ai_gateway=True, ...)`.

`bind_structured_output_model` currently passes `endpoint=configuration.endpoint_name`.
It changes to `model=`, which is the non-deprecated keyword. The factory's other
arguments are unchanged.

Because the flag lives in the default factory, all three users of the binding seam (the
production adapter, the #266 probe and the #267 test-run adapter) go through the Gateway
without any other change.

**Pinned seams stay unedited and must pass as they are** (handover §6.4):
- exactly one `with_structured_output` binding, with no `include_raw`;
- the production adapter passes no `transport_options`, and `use_ai_gateway` is not a
  transport option;
- `run()` keeps four positional arguments.

If a seam test asserts on the `endpoint=` keyword, it is updated only for the
`endpoint=` → `model=` rename. That edit is listed explicitly in the plan's corrections
file.

### 6.2 Legacy names

A pinned release whose role names `databricks-claude-opus-4-6` is invoked with that
name, unchanged, through the Gateway route, which accepts it (§2). No name rewriting
happens at runtime. The v1 seed manifest is not changed.

### 6.3 Fail-closed

There is no fallback to `/serving-endpoints`, `DEFAULT_CONFIG` or a later release. Gateway
errors are `openai.*` exceptions, which are already in the adapter's classified tuple, so
they surface as `ModelProviderUnavailableError` → `PinnedInvocationEndpointError`,
exactly as today.

### 6.4 Model-endpoint tool (U1)

`tools/model_endpoint_tool.py` and `tools/agent_bricks_tool.py` are user data calls, not
app LLM calls, and are unchanged.

## 7. Export (PPTX and Google Slides)

In `src/services/html_to_pptx.py` and `src/services/html_to_google_slides.py`:
- `self.ws_client.serving_endpoints.get_open_ai_client()` becomes
  `DatabricksOpenAI(workspace_client=self.ws_client, use_ai_gateway=True)`;
- `DEFAULT_MODEL` becomes `"system.ai.claude-sonnet-4-5"`.

The extended-thinking request (`extra_body.thinking`), the budgets and the truncation
retries are unchanged. A unit test feeds the reasoning-block shape recorded in §2 through
each converter's content parser and asserts that only the text is used. The
`model_endpoint` constructor override stays.

## 8. Session titles

Both call sites in `src/api/services/chat_service.py` (the monolith `run_title_gen` and
the graph-path title step) construct:

```python
ChatDatabricks(model=SESSION_TITLE_MODEL, use_ai_gateway=True,
               max_tokens=50, temperature=0.3, workspace_client=get_user_client())
```

`SESSION_TITLE_MODEL = "system.ai.claude-opus-4-6"` is a new constant in
`src/core/defaults.py`. It keeps current behaviour. Changing it to a cheaper model is a
one-line follow-up. The two sites share one helper, so the construction exists once.

`DEFAULT_CONFIG["llm"]` is unchanged, because the monolith still reads it. The identity
stays OBO, and title failures are still swallowed and logged. Task 0 step 5 proves the
title is actually generated.

## 9. Testing

**Unit tests:**
- the default factory passes `model=` and `use_ai_gateway=True`;
- the export clients and the title helper are constructed with `use_ai_gateway=True` and
  the `system.ai` constants;
- catalog mapping covers:
  - `databricks-X` → `system.ai.X`;
  - dropping names without the `databricks-` prefix;
  - failure codes;
- the local policy accepts `system.ai.*` and rejects:
  - `databricks-*`;
  - URL-shaped names;
  - path-shaped names;
  - empty slugs;
- the remote check covers:
  - a 404;
  - a permission denial;
  - a transport failure;
  - a non-chat `supported_api_types`;
  - success;
- the export parser handles the recorded reasoning-block shape.

**Rules** (from `executing-plans-tellr`):
- every test a reviewer approves is sabotage-verified;
- baselines are compared by failure cause (known: the `TestGetOrCreateLakebase` pair,
  #276, and the `test_usage_service` midnight flake, #278);
- PostgreSQL integration tests run one file at a time, and a skip counts as a failure.

**Live acceptance** on the Task 0 devloop instance:
1. The picker lists `system.ai.*` models only.
2. Draft a role on `system.ai.claude-opus-5-5`, save it, probe it and publish it.
3. A new conversation completes a graph turn on it.
4. A conversation pinned to the pre-existing release still completes a turn.
5. PPTX and Google Slides export each succeed.
6. A new session gets a generated title.

## 10. Workstream 2b (new, deferred)

The PRD is amended to split workstream 2. Workstream 2b owns everything from the
original §8.1 and handover §8 that 2a does not deliver:
- per-user and per-session attribution;
- token and cost capture;
- the admin dashboard;
- rate-limit policy and 429 UX;
- Gateway request tags (`Databricks-Ai-Gateway-Request-Tags` was seen in use; attribution
  is worth investigating);
- the remaining call sites (monolith, MCP, judge, feedback, validator), and removing the
  last hardcoded endpoints;
- making the export and title models configurable.

The handover document remains 2b's starting-state reference. 2a updates its §2 table to
mark the migrated sites.

## 11. Documentation changes

The PRD amendment covers:
- §8.1 status;
- §10, where row 2 splits into 2a and 2b;
- §3, the platform-criteria status after 2a.

Other changes:
- the handover's §2 table is updated;
- the workbench and admin docs under `docs/technical/` describe `system.ai` model
  selection and the removal of custom names.

## 12. Risks

| Risk | Mitigation |
|---|---|
| The naming rule is undocumented and could change or have exceptions. | Task 0 proves it across the full list. A change would affect only discovery and validation, because runtime passes the stored name through. |
| The dependency bump breaks the Apps BUILD resolver. | Task 0 gates all other work, and a fallback is recorded. |
| The Gateway rejects OBO tokens, so titles silently stop. | Task 0 step 5, with a stop condition. |
| The Gateway list omits models, as seen with `gpt-6-sol`. | Accepted by decision. Revisit in 2b if it bites. |
| `databricks-langchain` 0.9 → 0.20 changes other behaviour used elsewhere (Genie, vector search, `ChatDatabricks` message handling). | The full unit and integration baseline is compared by cause, and the live acceptance covers a full graph turn. |
