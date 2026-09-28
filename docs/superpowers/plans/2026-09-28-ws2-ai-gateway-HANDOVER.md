# Workstream 2 — Unity AI Gateway: handover

**Date:** 2026-09-28 · **Branch:** `feat/langgraph-core` at `b9bacf8b5` (pushed) · **For:** a fresh agent starting workstream 2

The umbrella PRD (`docs/superpowers/specs/2026-07-30-tellr-agentic-rebuild-prd-design.md`,
§3, §8.1, §9.3, §10, §12, §16.6 item 4) says *what* workstream 2 must deliver. This
document records the state of the code it starts from. Every fact below was checked
against the code at `b9bacf8b5`, and references are `file:line` at that commit. Treat them
as locators and re-check them before relying on them.

## 0. Before you start

- **Nothing is designed yet.** There is no workstream-2 spec or plan. Start with
  brainstorming and a spec (`docs/superpowers/specs/`), settle the open decisions in §8,
  then write a plan. Load `executing-plans-tellr` alongside
  `superpowers:subagent-driven-development` to execute it (see `CLAUDE.md`).
- **Environment rules:**
  - The Python environment is a shared pyenv: never run `pip install`, `npm install`,
    `uv`, or create a `.venv`.
  - Never touch the `ai_slide_generator` database.
  - PostgreSQL integration tests use
    `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`. Run one file
    at a time, and treat any skip as a failed run.
  - The Apps BUILD phase resolves only `packages/databricks-tellr-app/pyproject.toml`.
- **Baselines.** The unit-test baseline has two known failures, the
  `test_deploy_autoscaling` `TestGetOrCreateLakebase` pair (#276). `test_usage_service`
  flakes near 00:00 UTC (#278), which matters because workstream 2 will likely extend
  `usage_service`. Compare failures by cause, not by count.
- **GitHub:** use the personal account `robertwhiffin`, never the EMU account
  (`docs/agents/issue-tracker.md`).
- **Deploying:** use the `deploy-tellr-dev` skill, and always deploy to a `devloop`
  instance. On 2026-09-28 PyPI's cached index went stale for hours; the skill records the
  diagnosis and the direct-URL fallback. Two live instances exist, and neither may be
  redeployed without asking:
  - `epic258` is the user's working instance, on dev28.
  - `epic258-admin` runs dev30.
- **`main` is 59 commits ahead of the branch.** It has 0.4.3, the SDR-4437 security PRs
  and the secret-backed Fernet key deploy mode. `deploy.py` and `app.yaml.template` are
  exactly the files a Gateway change is likely to touch, and `main` changed both, so
  consider merging `main` into the branch before editing them.

## 1. What already exists (from workstream 9, epic #258)

- **Per-role model configuration.** Each of the seven graph roles (architect,
  data_analyst, builder, build_reviewer, fixer, fix_reviewer, deck_reviewer) carries
  `ModelConfiguration` (`src/services/graph_definition_manifest.py:98-102`):
  - `endpoint_name`, an **exact** endpoint name;
  - `temperature`, `max_tokens` and `top_p`.

  This is stored in Lakebase as a versioned agent definition and fixed per immutable
  Graph Release. Admins edit it in the Agent Definition Workbench (`/admin`). Every
  conversation is pinned to the release that was active when it started.
- **Seed.** All seven roles are seeded with `databricks-claude-opus-4-6`, max_tokens 60000,
  temperature 0.7 and top_p 0.95 (`src/services/agent_definition_manifest_v1.py:3`). This
  is Lakebase data, not a runtime constant.
- **Endpoint discovery** (`src/services/model_endpoint_catalog.py:163-211`):
  - lists serving endpoints as the app service principal, keeping only those with a
    `foundation_model` served entity (`:180-191`);
  - **consequence:** a Gateway-fronted external-model or provisioned endpoint would not
    appear in the list, and is reachable only by typing a custom name.
- **Validation on draft save** (`src/services/graph_configuration_draft.py:275-310`):
  - a local name policy (`model_endpoint_catalog.py:92-103`);
  - a remote `serving_endpoints.get`, which requires an exact name, `READY`, and
    `config_update == NOT_UPDATING`. The live probe of 2026-09-28 found all 54 system
    endpoints satisfy this (see the comment on #266).
  - **It does not read `ai_gateway`.**
- **Runtime resolution:**
  1. `AgentRuntime.run` (`src/services/agent_runtime.py:564-590`).
  2. `PersistedGraphReleaseLoader.resolve` (`src/services/persisted_graph_release.py:146-187`),
     which keeps a per-process cache. That is safe only because releases are immutable.
  3. `saved_model_configuration` (`agent_runtime.py:802`).
  4. `ChatDatabricks(endpoint=<exact name>)`, with no indirection.
- **Fail-closed.** A graph turn never falls back to the monolith or to
  `DEFAULT_CONFIG["llm"]`, and never substitutes the latest release (`chat_service.py:241-275`,
  typed 503). A workstream-2 endpoint fallback must not reintroduce a code default for
  pinned graph turns.

## 2. Every LLM call site in `src/`

CD means `databricks_langchain.ChatDatabricks`. It wraps the OpenAI client, so its errors
are `openai.*` exceptions, and it retries twice by default. OAI means the raw
`get_open_ai_client()`.

| # | Call site | Endpoint chosen by | Client | Identity | Token usage | ws2 status |
|---|---|---|---|---|---|---|
| G1 | **Graph, all 7 roles**: `DatabricksModelAdapter.invoke` → `bind_structured_output_model` (`agent_runtime.py:206-245, 333-375`). Callers in `src/services/graph/nodes.py` | Pinned release's role config | CD (`use_ai_gateway=True`, `agent_runtime.py:327`) | App SP (`agent_runtime.py:327-331`) | **Discarded** (no `include_raw`) | → Gateway (ws2a) |
| G2 | #266 saved-candidate probe (`model_endpoint_probe.py:130-160`) | Draft candidate | CD (`use_ai_gateway=True`) | SP | not captured | → Gateway (ws2a) |
| G3 | #267 workbench test runs (`agent_runtime.py:592-691, 893-914`) | Draft or published | CD (`use_ai_gateway=True`), `timeout=120`, `max_retries=0` | SP | **Captured** by `_TokenUsageCallback` (`:255-300`) into `agent_test_run.input_tokens/output_tokens` | → Gateway (ws2a) |
| M1 | Monolith `SlideGeneratorAgent._create_model` (`src/services/agent.py:436-467`) and `agent_factory._create_model` (`agent_factory.py:50-83`) | **Hardcoded** `DEFAULT_CONFIG["llm"]["endpoint"]` (`src/core/defaults.py:29-36`) | CD | SP | no | unchanged, ws2b |
| MCP | `create_deck` / `edit_deck` (`src/api/mcp_server.py`) run on the monolith | = M1 | = M1 | = M1 | no | unchanged, ws2b |
| T1/T2 | Session titles, monolith and **graph** paths (`chat_service.py:1447-1458`, `:2002-2012`) | `SESSION_TITLE_MODEL = "system.ai.claude-opus-4-6"` (`src/core/defaults.py:238`), via `build_session_title_model()` (`session_naming.py`); `max_tokens=50` | CD (`use_ai_gateway=True`) | **OBO user** | no; failures swallowed | → Gateway (ws2a) |
| J1/J2 | Verification judge, direct and MLflow backends (`src/services/evaluation/llm_judge.py:204-229, 368-388`) | DEFAULT_CONFIG | CD / MLflow | SP | no | unchanged, ws2b |
| F1 | Feedback assistant (`src/api/services/feedback_service.py:44-85, 295`) | `FEEDBACK_LLM_ENDPOINT` env, default `databricks-gemma-3-12b` | CD | SP | no | unchanged, ws2b |
| X1/X2 | PPTX and Google Slides converters (`html_to_pptx.py:51, 520-540`; `html_to_google_slides.py:342, 824-835`) | `DEFAULT_MODEL = "system.ai.claude-sonnet-4-5"` (`html_to_pptx.py:52`, `html_to_google_slides.py:343`) | `DatabricksOpenAI(use_ai_gateway=True)` via `gateway_openai_client` (`src/services/gateway_openai.py`); extended thinking | SP | no | → Gateway (ws2a) |
| V1 | Config validator (`src/services/config_validator.py:100-115`) | DEFAULT_CONFIG | CD | env default | no (no route caller found) | unchanged, ws2b |
| U1 | User-configured tools (`tools/model_endpoint_tool.py`, `tools/agent_bricks_tool.py`): user data calls, not app LLM calls | User's tool config | REST | OBO user | no | unchanged, ws2b |

Search results:
- `with_structured_output(` occurs once in `src` (`agent_runtime.py:241`).
- `usage_metadata` occurs only at `agent_runtime.py:259-267`.
- Hardcoded endpoint strings: `defaults.py:31`, `html_to_pptx.py:51`,
  `html_to_google_slides.py:342`, `feedback_service.py:44`.

## 3. Usage, cost and the admin dashboard today

- **Data:** `usage_events` (`src/database/models/usage_event.py`) records only login,
  deck_created and deck_retrieved. It has no token or cost columns, and its writer's dedup
  caches are per-process (`src/api/services/usage_events.py:29-32`).
- **Dashboard:** `usage_service.py` → `/api/admin/usage/{summary,daily,top-users,funnel,retention,heatmap}`
  → `frontend/src/components/Admin/UsageDashboard.tsx`, shown as the Usage tab. **It has
  no token, cost or model-call metric.**
- **Invocation logging:** the identity log (`src/services/agent_runtime_identity.py:95-151`)
  allow-lists release, role, revision and content-hash fields. **It must never log a user
  or session id** (#260 amendment).
- **Gateway:** there is no AI Gateway, inference-table or rate-limit code anywhere in
  `src`, `tests` or `docs/technical`. The SDK does support it:
  - `AiGatewayConfig`, usage tracking, inference tables, rate limits keyed on
    endpoint / service_principal / user / user_group, and `put_ai_gateway`;
  - the app pins `databricks-sdk==0.120.0`, but the local shared environment has 0.112.0.

## 4. Rate limits (429s) today

Nothing recognises a model 429, and there is no in-app rate limiter.
- **Graph path:**
  1. `openai.RateLimitError` becomes `ModelProviderUnavailableError`
     (`agent_runtime.py:344-375`), after the client's two retries.
  2. That becomes `PinnedInvocationEndpointError` (`:835-840`).
  3. Nodes re-raise it, so **one 429 on any role aborts the whole turn**.
  4. The user sees "Pinned graph configuration is unavailable"
     (`chat_service.py:1949-1978`, code `pinned_graph_configuration_unavailable`).

  A quota problem is indistinguishable from a dead endpoint.
- **Monolith path:**
  - the sync `POST /api/chat` returns an HTTP 500 (`chat.py:427-432`; see also #286);
  - SSE leaks the raw provider text (`chat.py:600-605`);
  - async and MCP jobs fail with `str(e)`.
- **Elsewhere:** the judge and exports return 500s; title failures are swallowed.

## 5. Config surfaces

- **`app.yaml.template`** (`packages/databricks-tellr/databricks_tellr/_templates/`) has no
  LLM, endpoint or gateway variable. It is substituted in `deploy.py:1400-1410`.
- **Deploy does not add a serving-endpoint `AppResource`**, so it never grants the service
  principal CAN_QUERY. `user_api_scopes` does include `serving.serving-endpoints`
  (`deploy.py:1523-1530`).
- **LLM env vars read in `src`:** only `FEEDBACK_LLM_ENDPOINT`.
- **App settings:** `AppSettings` (`src/core/settings_db.py`) has no LLM field apart from
  `llm_judge_backend`.
- **Graph endpoint choice** already lives in Lakebase per role (§1). The non-graph sites
  have no configuration surface today.

## 6. Constraints workstream 2 must respect

1. **OBO data rule** (PRD §12.1, §16): OBO-derived data must never be written to a store
   with coarser grants. Graph prompts carry Genie and tool output fetched under the user's
   token.
   - **Gateway inference tables and payload logging are therefore the pattern §16 already
     ruled out.**
   - Usage tracking (token counts and requester, no payload) is a different category.
   - The spec must say explicitly which Gateway features are enabled.
2. **Identity:** every production model call except the session titles goes out as the
   **app service principal**. Gateway usage tracking and per-user rate limits would see
   one principal, so per-user or per-session attribution needs one of:
   - OBO model calls, which means users need CAN_QUERY. That reverses the stated rule at
     `agent.py:440-442`.
   - Request-level usage context.
   - App-side capture.
3. **Multi-worker coherence:** production runs 4 uvicorn processes, so any app-side
   counter or quota must live in Lakebase. Per-process caches exist today:
   - `get_agent_runtime` `lru_cache`;
   - the release loader cache;
   - the model-endpoint tool cache.
4. **Pinned seams:**
   - Exactly one structured-output binding (`tests/unit/test_agent_runtime.py:430-442,
     1397-1422`).
   - The production adapter passes no transport options (`:1490-1497`).
   - `run()` keeps 4 positional arguments at every call site (`tests/unit/test_graph_nodes.py:229`).

   New routing or usage data must travel on existing objects, such as
   `AgentAssemblyContext`, which is how the session ids travel.
5. **Typed errors:** runtime and probe errors are classified by type. They never read
   exception text or echo provider payloads (`model_endpoint_probe.py:136-142`). A quota
   error should get its own typed code, following the pattern of
   `pinned_graph_configuration_unavailable`.
6. **Exact endpoint names (#266):** definitions store exact names, and validation rejects
   anything shaped like a URL or path. A Gateway "alias" design must reconcile with this
   and with release immutability.
7. **Observability is non-fatal** (PRD §9.3): usage recording must never fail a turn.
8. **UC-agnostic** (PRD §8.2 struck): Tellr requires no Unity Catalog catalog or schema. A
   dashboard that reads UC system tables (`system.serving.*`, `system.billing.*`) must be
   squared with that.

## 7. Related open issues

- **#277** — `model_endpoint_tool` does not validate the endpoint name. It is the same
  validation seam workstream 2 would extend.
- **#286** — sync `/api/chat` ignores engine mode; it is the route that 500s on a
  monolith 429.
- **#278** — the `test_usage_service` midnight flake.
- **#13** — the OpenAI reasoning-model response format; relevant if the Gateway fronts
  non-Claude or reasoning models.

No open issue covers the AI Gateway, usage tracking or rate limits themselves.

## 8. Open decisions for the workstream-2 spec

1. **Provisioning** (PRD §12): who creates and owns the Gateway-fronted endpoint —
   FE-provided, per-workspace, or app-managed via `deploy.py` / `put_ai_gateway`? Does
   deploy grant the service principal CAN_QUERY through an `AppResource`?
2. **What "route via Gateway" means:**
   - Is enabling `ai_gateway` on the existing system pay-per-token endpoints enough, or is
     a new app-owned endpoint needed? A new one would be excluded from discovery.
   - Must draft validation check `ai_gateway.usage_tracking_config.enabled`?
3. **Attribution identity:** stay on the service principal and attribute through request
   context or app-side capture, or move model calls to OBO? Verify on the platform whether
   Gateway usage tracking can carry a session or user identifier.
4. **App-side token capture:** if the Gateway cannot attribute per session, extend the #267
   callback to production? That touches the pinned seams and the no-user/session-id log
   rule. The per-call rows would live in Lakebase, holding token counts only.
5. **Dashboard source:** Lakebase next to `usage_events`, or UC system tables (§6.8)?
6. **Cost:** where do per-token prices come from? Is cost attributed per user, per session
   or per deck?
7. **Inference tables and payload logging:** state explicitly that they are off (§6.1).
   Guardrails stay deferred (PRD §8.1).
8. **Coverage:** which non-graph call sites are in scope — titles, judge, feedback, exports,
   validator? The monolith and MCP are due for deletion in a later PR. Where does each one's
   endpoint configuration live, given "no hardcoded model endpoint remains"?
9. **Rate-limit UX:**
   - Separate a 429 from `PinnedInvocationEndpointError`.
   - Should a 429 on one slide's builder or reviewer degrade that slide or abort the turn?
   - Keep, tune or disable the client's two retries?
   - What code and message should MCP callers get?
10. **Rate-limit policy:** who sets the limits (per user, per service principal, per
    endpoint)? Is any app-side quota needed? If so it must be Lakebase-backed.
11. **Releases:** does moving to a Gateway endpoint require publishing a new Graph Release
    through the workbench, or an app-level override? An override conflicts with the #266
    exact-name rule and with release immutability.
