# MLflow traces in Unity Catalog

Tellr can store MLflow GenAI traces in Unity Catalog (OTEL-backed Delta tables) instead of the default control-plane artifact layout. That matches Databricks guidance for Apps where trace export to regional storage can fail, and it centralizes access control on UC.

**Reference:** [Store MLflow traces in Unity Catalog](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog) (Beta; regional and preview prerequisites apply).

## Requirements

- MLflow Python **3.11+** with Databricks extras (`mlflow[databricks]>=3.11`), as pinned in `packages/databricks-tellr-app/pyproject.toml`.
- **OpenTelemetry Collector for Delta Tables** must be available in the workspace. If experiment creation fails with `ENDPOINT_NOT_FOUND` and a message that **“OpenTelemetry Collector for Delta Tables” is unavailable**, UC trace linking is not enabled for that workspace yet—contact **Databricks support** to request access (see also [trace storage in UC](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog)). Workspace or account admins may need to enable related **OpenTelemetry on Databricks** preview features depending on region.
- A SQL warehouse ID the app identity can use (`CAN USE` on the warehouse).
- UC catalog/schema where the app’s identity can create tables (or use a pre-created schema).

When the OTel collector is **not** available, [`create_databricks_experiment`](../../src/core/mlflow_tracing.py) **falls back** to a normal MLflow experiment (no UC `trace_location`) so the app still gets an experiment and tracing can use the default backend; you lose UC Delta trace tables until the feature is enabled.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `TELLR_MLFLOW_UC_CATALOG` | UC catalog for OTEL trace tables (e.g. `main`). |
| `TELLR_MLFLOW_UC_SCHEMA` | UC schema (e.g. `mlflow_traces`). |
| `TELLR_MLFLOW_UC_TABLE_PREFIX` | Prefix for `_otel_spans`, `_otel_logs`, etc. (e.g. `tellr_stage`). |
| `MLFLOW_TRACING_SQL_WAREHOUSE_ID` | Warehouse used by the MLflow UI to read UC traces (and monitoring). |
| `TELLR_MLFLOW_SQL_WAREHOUSE_ID` | Optional alias; copied to `MLFLOW_TRACING_SQL_WAREHOUSE_ID` if the latter is unset. |

Implementation: [`src/core/mlflow_tracing.py`](../../src/core/mlflow_tracing.py). When all three `TELLR_MLFLOW_UC_*` values are set, **new** experiments are created with `trace_location=UnityCatalog(...)`. Existing experiments keep their original trace binding (Databricks does not allow changing UC trace location after creation).

## Grants

Grant the **Databricks App service principal** (and any user identities that must read traces in the UI):

1. `USE CATALOG` on the catalog.
2. `USE SCHEMA` on the schema.
3. `SELECT` and `MODIFY` on each `<table_prefix>_otel_*` table (see product docs; `ALL_PRIVILEGES` alone is not sufficient).

## Code paths

- [`SlideGeneratorAgent._ensure_user_experiment`](../../src/services/agent.py) and [`ChatService._ensure_user_experiment`](../../src/api/services/chat_service.py) create user-scoped experiments.
- [`evaluate_with_judge`](../../src/services/evaluation/llm_judge.py) may create an experiment if none is passed.

## Deployment

Generated `app.yaml` includes UC tracing env vars from [`packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template`](../../packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template). [`deploy.py`](../../packages/databricks-tellr/databricks_tellr/deploy.py) resolves values in this order (per field): optional `tellr.create(..., mlflow_tracing={...})` / `tellr.update(..., mlflow_tracing={...})` with template key names (`MLFLOW_TRACING_SQL_WAREHOUSE_ID`, `TELLR_MLFLOW_UC_*`), then the `mlflow_tracing` block (or flat keys) under the selected environment in `config/deployment.yaml` when using `config_yaml_path` or `scripts/deploy_local.py`, then deploy-time environment variables `TELLR_DEPLOY_MLFLOW_TRACING_SQL_WAREHOUSE_ID`, `TELLR_DEPLOY_MLFLOW_UC_CATALOG`, `TELLR_DEPLOY_MLFLOW_UC_SCHEMA`, `TELLR_DEPLOY_MLFLOW_UC_TABLE_PREFIX`. See [`config/deployment.example.yaml`](../../config/deployment.example.yaml).

## UC vs regional artifact storage (why both matter)

Tellr passes `trace_location=UnityCatalog(...)` when creating **new** experiments so MLflow can persist GenAI / OTEL trace data into **Unity Catalog Delta tables** under your chosen catalog, schema, and `<table_prefix>` (see product docs for exact table names; they follow the pattern `<prefix>_otel_*`).

Separately, MLflow 3’s Python client may **also** attempt to export trace payloads via HTTPS to **regional artifact storage** (`https://<region>.storage.cloud.databricks.com`, URLs often containing `mlflow-tracking` / `traces.json`). **Databricks Apps** frequently block or restrict that egress until the **regional storage FQDN** is allowlisted in the app network policy. If you see `Connection refused` to `*.storage.cloud.databricks.com` in app logs, traces may be incomplete in the UI until egress is fixed—even when UC env vars are correct.

**Operational summary:**

| Mechanism | Purpose |
|-----------|---------|
| `TELLR_MLFLOW_UC_*` + new experiment | Binds the experiment to **UC Delta** tables for trace/OTEL storage (primary goal for governance and many Apps setups). |
| Egress to `*.storage.cloud.databricks.com` | May still be required for some **MLflow 3 trace export** paths; coordinate with workspace admin if logs show failures to that host. |
| `MLFLOW_TRACING_SQL_WAREHOUSE_ID` | Warehouse the **MLflow UI** uses to **read** UC-backed trace data. |

## Verify UC tracing end-to-end

Work through these in order:

1. **Environment** — On the running app, confirm all of: `TELLR_MLFLOW_UC_CATALOG`, `TELLR_MLFLOW_UC_SCHEMA`, `TELLR_MLFLOW_UC_TABLE_PREFIX`, and `MLFLOW_TRACING_SQL_WAREHOUSE_ID` (non-empty, values match your UC target and a warehouse the app identity can use).

2. **Workspace features** — **OpenTelemetry on Databricks** enabled where required for your region (see [Databricks tracing in UC](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog)).

3. **Grants** — App **service principal** has `USE CATALOG`, `USE SCHEMA`, and table-level privileges on the `<prefix>_otel_*` tables (create if missing; `ALL_PRIVILEGES` alone may not be enough—see Databricks docs).

4. **New experiment** — UC `trace_location` is applied only when the experiment is **created** with those env vars set. Delete the existing per-user experiment at  
   `/Workspace/Users/<DATABRICKS_CLIENT_ID>/<user>/ai-slide-generator`  
   if it was created earlier without UC, then run Tellr again so [`create_databricks_experiment`](../../src/core/mlflow_tracing.py) runs with `trace_location=UnityCatalog(...)`.

5. **App logs** — After recreating the experiment, look for:  
   `Creating MLflow experiment with Unity Catalog traces: catalog=... schema=... prefix=...`  
   If you only see `Using existing user experiment` and never the line above, you are still on a pre-UC experiment.

6. **UC tables** — In a SQL warehouse (or editor), run:
   - `SHOW TABLES IN <catalog>.<schema> LIKE '<prefix>%';`  
   Expect tables whose names include `otel` (exact names depend on MLflow/Databricks version).
   - Optionally `SELECT COUNT(*) FROM <catalog>.<schema>.<prefix>_otel_spans LIMIT 1;` (adjust table name to what `SHOW TABLES` returns). Row counts should increase after slide/chat activity.

7. **MLflow UI** — Open the experiment under the SP path, ensure the UI can use the tracing warehouse (`MLFLOW_TRACING_SQL_WAREHOUSE_ID`) to query UC-backed traces.

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| Logs: `Connection refused` to `*.storage.cloud.databricks.com` | App egress / network policy; allowlist regional storage FQDN. |
| UC tables empty; experiment exists | Experiment created **before** UC env; delete experiment and retry, or wrong catalog/schema/prefix. |
| `experiment_id is missing` in trace warnings | Trace span emitted before `mlflow.set_experiment` on a code path (often transient); less critical than egress/UC binding. |
| No `UnityCatalog` in create log | Any of `TELLR_MLFLOW_UC_*` unset at process start, or import failure for `mlflow.entities.trace_location.UnityCatalog` (check `mlflow[databricks]>=3.11`). |
| Log: `UnityCatalog trace location requires mlflow>=3.11...` | The import `from mlflow.entities.trace_location import UnityCatalog` failed. Check the **installed** MLflow version in the log line (`mlflow.__version__=...`) and the exception text. **Fix:** ensure the app environment resolves `mlflow[databricks]>=3.11` (see `databricks-tellr-app` dependencies). If an older `mlflow` is pulled in by another package or a stale wheel, bump/rebuild the app package and redeploy so `pip install` installs MLflow **3.11+**. |
| Error: `OpenTelemetry Collector for Delta Tables` / `ENDPOINT_NOT_FOUND` when creating experiment | Workspace does not have the OTel collector service needed to **link** MLflow experiments to UC trace tables. Request enablement from Databricks. After redeploy with the fallback in `create_databricks_experiment`, Tellr uses a **non-UC** experiment unless you unset `TELLR_MLFLOW_UC_*` to avoid retrying UC on each new experiment name. |
| LLM judge: `storage.cloud.databricks.com` + `RESOURCE_DOES_NOT_EXIST` | `mlflow.genai.evaluate` still touches regional artifact storage for some trace paths. Allowlist egress, or rely on Tellr’s **direct LLM judge** fallback in [`llm_judge.py`](../../src/services/evaluation/llm_judge.py) (verification still returns a rating). |
| `ContextVar` / “different Context” during autolog | Disable LangChain autolog (default) or upgrade MLflow when fixes land; set `TELLR_MLFLOW_LANGCHAIN_AUTOLOG=1` only if you need autolog spans and your runtime avoids async context splits. |

### Confirm MLflow version on the app

After deploy, app logs from the improved warning include `mlflow.__version__`. You can also verify from a one-off command or notebook: `python -c "import mlflow; print(mlflow.__version__); from mlflow.entities.trace_location import UnityCatalog"`. **3.11.0 or newer** is required for `UnityCatalog`.
