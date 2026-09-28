# Workstream 2a — Unity AI Gateway (`system.ai.*`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo, also load `executing-plans-tellr` (see `CLAUDE.md`).

**Goal:** Send every graph model call, both export converters and session-title generation
through Unity AI Gateway. The Agent Definition Workbench must offer only the `system.ai.*`
models that the Gateway lists.

**Architecture:**
- Bump `databricks-langchain` to 0.20.0 and add `databricks-openai` 0.17.1.
- Graph calls: the default model factory constructs
  `ChatDatabricks(model=..., use_ai_gateway=True)`, so the existing structured-output
  binding seam is unchanged.
- Export: the converters use `DatabricksOpenAI(use_ai_gateway=True)`.
- Discovery and remote draft validation read `/api/ai-gateway/v2/endpoints`.
- A new save-only validator requires a `system.ai.*` name whenever a save changes a role's
  model.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, databricks-sdk, databricks-langchain,
databricks-openai, openai, httpx, pytest; React + TypeScript + Vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-09-28-ws2a-ai-gateway-system-ai-design.md`. Read it in
full before starting. It holds the platform facts in §2 and the decisions this plan
implements.

## Global Constraints

- **Branch:** `feat/ws2a-ai-gateway`. Never push without the user's confirmation. Push as
  the personal `robertwhiffin` account, never the EMU account.
- **Shared environment:** the Python environment is a shared pyenv. **Never run
  `pip install`, `npm install` or `uv`, and never create a `.venv`.** The one exception is
  the human step in Task 0.
- **Build file:** the Apps BUILD phase resolves only
  `packages/databricks-tellr-app/pyproject.toml`.
- **Exact pins in the app file:** `databricks-langchain==0.20.0` and
  `databricks-openai==0.17.1`.
- **Root `pyproject.toml`** keeps its ranged style: `databricks-langchain>=0.19.0` and
  `databricks-openai>=0.14.0`.
- **`requirements.txt`** uses exact pins that match the app file.
- **Gateway chat base URL:** `{host}/ai-gateway/mlflow/v1`. Never `/serving-endpoints` for
  in-scope call sites, and never an automatic fallback to it.
- **Gateway endpoint list:** `GET /api/ai-gateway/v2/endpoints`. Per name:
  `GET /api/ai-gateway/v2/endpoints/{name}`. The chat API-type marker is
  `mlflow/v1/chat/completions`.
- **Naming rule:** Gateway endpoint `databricks-<model>` ↔ invocable name
  `system.ai.<model>`.
- **Name regex for a changed model:** `^system\.ai\.[a-z0-9][a-z0-9._-]*[a-z0-9]$`.
- **New codes:**
  - `endpoint_not_gateway_model`, message: "Model name must start with `system.ai.` and
    contain only lowercase letters, digits, hyphens, underscores and periods."
  - `endpoint_not_chat_model`, message: "Endpoint is not a chat model."
- **Constants:**
  - export `DEFAULT_MODEL = "system.ai.claude-sonnet-4-5"`;
  - `SESSION_TITLE_MODEL = "system.ai.claude-opus-4-6"` in `src/core/defaults.py`;
  - `DEFAULT_CONFIG["llm"]` is **unchanged**.
- **Out of scope; do not touch their model calls:** the monolith (`agent.py`,
  `agent_factory.py`), MCP, the judge (`llm_judge.py`), feedback (`feedback_service.py`) and
  `config_validator.py`.
- **Pinned seams must pass unedited:**
  - exactly one `with_structured_output` binding, with no `include_raw`;
  - the production adapter passes no `transport_options`;
  - `run()` keeps four positional arguments.
- **The only allowed seam-test edits** are the `endpoint` → `model` key rename (Task 1) and
  the `use_ai_gateway` key addition. List each one in the corrections file.
- **Typed errors** never echo provider text or endpoint names.
- **Deploys** go to a **new** devloop instance, `--env devloop --instance ws2a`. Never
  `devtest`. Never redeploy `epic258` or `epic258-admin`.
- **PostgreSQL integration tests:** run with
  `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, one file at a
  time. A skip counts as a failure. Never touch the `ai_slide_generator` database.
- **Baselines** are compared by failure cause. Known causes: the
  `test_deploy_autoscaling` `TestGetOrCreateLakebase` pair (#276), and the
  `test_usage_service` flake near 00:00 UTC (#278).

## Review Focus

These are the five input classes the spec implies but that no happy-path test covers,
most likely to bite first:

1. **Rollback to a pre-2a release.** Every role names `databricks-*`, and rollback must
   still succeed. It re-validates through `_save_local_validators`. → Task 4, Step 1, test
   `test_rollback_to_a_legacy_release_is_not_blocked_by_the_gateway_name_rule`.
2. **A prompt-only edit on a role still named `databricks-*`** must save, including its
   remote check. → Task 4, `test_unchanged_legacy_model_saves`; Task 3,
   `test_remote_check_looks_up_a_legacy_name_as_is`.
3. **Publishing a draft where only untouched roles still name `databricks-*`** must
   succeed. → Task 4, `test_publication_with_untouched_legacy_roles_is_not_blocked`.
4. **An embedding model picked from the list** (it appears in discovery) is refused at save
   with `endpoint_not_chat_model` and no leaked text. → Task 3,
   `test_remote_check_refuses_an_embedding_endpoint`.
5. **A saved draft whose role names a legacy model** shows that model visibly in the
   picker, where no radio option is checked, and does not silently drop it. → Task 7,
   `shows the current model when it is not in the discovered list`.

---

## File map

| File | Change | Task |
|---|---|---|
| `packages/databricks-tellr-app/pyproject.toml`, `pyproject.toml`, `requirements.txt` | Dependency pins | 0 |
| `tests/fixtures/mock_chat_completions.py` | Mock Gateway transport for real `ChatDatabricks` | 1 |
| `tests/unit/test_model_endpoint_probe.py` | Migrate `MockTransportWorkspace`, update kwargs assertion | 1 |
| `src/services/agent_runtime.py` | Default factory adds `use_ai_gateway=True`; binding passes `model=` | 1 |
| `tests/unit/test_agent_runtime.py` | Rename seam keys, new Gateway-path test | 1 |
| `src/services/model_endpoint_catalog.py` | Gateway discovery, Gateway remote check, new codes, name mapping | 2, 3 |
| `tests/unit/test_model_endpoint_catalog.py` | Rewrite discovery and remote tests for the Gateway API | 2, 3 |
| `src/services/graph_configuration_draft.py` | `_gateway_model_name_validator` in the two saves | 4 |
| `tests/unit/test_graph_configuration_draft.py` (+ route and integration tests that save a changed model) | New rule tests; changed-model fixtures move to `system.ai.*` | 3, 4 |
| `src/services/gateway_openai.py` (new) | One constructor for the export OpenAI client | 5 |
| `src/services/html_to_pptx.py`, `src/services/html_to_google_slides.py` | Gateway client and `system.ai` constant | 5 |
| `tests/unit/test_html_to_pptx.py`, `tests/unit/test_google_slides_converter.py` | Client and parser tests | 5 |
| `src/core/defaults.py`, `src/api/services/session_naming.py`, `src/api/services/chat_service.py` | `SESSION_TITLE_MODEL`, `build_session_title_model()`, both title sites | 6 |
| `tests/unit/test_session_naming.py` | Title model construction tests | 6 |
| `frontend/src/components/Admin/AgentDefinitionWorkbench/DefinitionEditor.tsx` (+ its test) | Remove the custom field; show the current model | 7 |
| PRD, handover, `docs/technical/backend-overview.md` | Docs | 8 |
| — | Live acceptance on devloop | 9 |

Corrections file: `docs/superpowers/plans/2026-09-28-ws2a-ai-gateway-CORRECTIONS.md`. It is
created in Task 0 and appended to by every task.


## Task documents

This plan is split into two task documents. Execute them in order, and treat this index as
part of every task's requirements.

- `2026-09-28-ws2a-ai-gateway-tasks-0-4.md` — Task 0 (merge, dependency bump, build and
  naming-rule proof), Tasks 1–4 (runtime, discovery, remote check, save rule).
- `2026-09-28-ws2a-ai-gateway-tasks-5-9.md` — Tasks 5–9 (export, titles, workbench UI,
  docs, live acceptance).
