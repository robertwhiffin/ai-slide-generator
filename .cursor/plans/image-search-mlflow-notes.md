# Plan notes (mirror)

See the canonical plan in your Cursor plans folder (`image_search_and_mlflow_fixes_4b29caea.plan.md`) for:

- **uv lock:** run `uv lock && uv sync` on your machine; the agent environment often cannot reach `pypi-proxy.dev.databricks.com`.
- **Image tags:** JSONB column + migration + direct `.contains()` on Postgres.
- **MLflow UC:** `docs/technical/mlflow-uc-tracing.md` and `src/core/mlflow_tracing.py`.
