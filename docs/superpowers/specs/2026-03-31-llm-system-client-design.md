# Use App Service Principal for LLM Calls

**Date:** 2026-03-31
**Status:** Approved

## Problem

The app currently uses the user's workspace client (OBO token from `x-forwarded-access-token`) to make LLM calls via `ChatDatabricks`. This requires users to have workspace-level permissions on the model serving endpoint, which prevents consumers without those permissions from using the app.

## Decision

Switch `ChatDatabricks` model creation to use the app's system client (service principal) instead of the user's client. This is a targeted, single-function change.

## Scope

**Changes:**
- `src/services/agent_factory.py` — `_create_model()`: replace `get_user_client()` with `get_system_client()`
- `src/services/agent.py` — `SlideGeneratorAgent._create_model()`: same change, remove now-unused `get_user_client` import
- `src/core/databricks_client.py` — update docstrings for `get_user_client()` and module-level docstring to remove LLM from user-client responsibilities

**No changes to:**
- Tools (Genie, Vector Search, Model Endpoint, MCP, Agent Bricks) — these remain on the user client for identity-based access
- MLflow tracing — already authenticates via `DATABRICKS_TOKEN` env var (system client)
- Experiment creation and permission grants — already use system client
- Middleware — still sets up user client per-request (needed for tools)
- Local development — `get_user_client()` already falls back to the system client when no user token is present, so local dev already uses the system client for LLM calls

## Design

In `_create_model()` (agent_factory.py), the workspace client passed to `ChatDatabricks` changes from the request-scoped user client to the singleton system client:

```python
# Before
from src.core.databricks_client import get_user_client
user_client = get_user_client()
model = ChatDatabricks(..., workspace_client=user_client)

# After
from src.core.databricks_client import get_system_client
system_client = get_system_client()
model = ChatDatabricks(..., workspace_client=system_client)
```

## Consequences

- LLM calls are attributed to the app's service principal, not the end user. Per-user attribution at the serving layer is lost (product tracking header changes from `tellr-app-{hashed_user_id}` to `tellr-app-system`). MLflow tracing still records which user triggered each call, so auditability is preserved there.
- Users no longer need workspace-level model serving endpoint permissions to use the app
- The service principal's quota/rate limits apply to all LLM calls (shared across all users). The Foundation Model API pay-per-token endpoints do not have per-principal rate limits that would be a concern here.

## Testing

- `test_agent_factory.py` tests mock `_create_model` at the factory level — no updates needed
- `test_agent.py` and `test_default_config_integration.py` mock `get_user_client` inside `SlideGeneratorAgent._create_model()` — update mocks to `get_system_client`
- E2E tests should pass without change since the serving endpoint is accessible to the service principal
