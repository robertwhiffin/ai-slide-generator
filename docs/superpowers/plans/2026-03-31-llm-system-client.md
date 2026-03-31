# LLM System Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch LLM calls from the user workspace client to the app's service principal (system) workspace client so users without workspace-level permissions can use the app.

**Architecture:** Replace `get_user_client()` with `get_system_client()` in both `_create_model()` functions (agent_factory.py and agent.py). Update docstrings to reflect the change. Tools remain on the user client.

**Tech Stack:** Python, databricks-langchain, databricks-sdk

**Spec:** `docs/superpowers/specs/2026-03-31-llm-system-client-design.md`

---

### Task 1: Update `_create_model()` in `agent_factory.py`

**Files:**
- Modify: `src/services/agent_factory.py:48-58`

- [ ] **Step 1: Change import and client in `_create_model()`**

Replace the user client with the system client:

```python
# Line 48: change import
from src.core.databricks_client import get_system_client

# Line 51: change client call
system_client = get_system_client()

# Line 58: change kwarg
workspace_client=system_client,
```

The full function (lines 37-70) should read:

```python
def _create_model():
    """Create LangChain Databricks model using backend defaults.

    Uses the fixed LLM configuration from DEFAULT_CONFIG. LLM settings
    are NOT user-configurable — they are backend infrastructure defaults.

    Uses the system client (service principal) so that users do not need
    workspace-level permissions on the model serving endpoint.

    Returns:
        ChatDatabricks model instance
    """
    from databricks_langchain import ChatDatabricks

    from src.core.databricks_client import get_system_client

    llm_config = DEFAULT_CONFIG["llm"]
    system_client = get_system_client()

    model = ChatDatabricks(
        endpoint=llm_config["endpoint"],
        temperature=llm_config["temperature"],
        max_tokens=llm_config["max_tokens"],
        top_p=0.95,
        workspace_client=system_client,
    )

    logger.info(
        "Agent factory: ChatDatabricks model created",
        extra={
            "endpoint": llm_config["endpoint"],
            "temperature": llm_config["temperature"],
            "max_tokens": llm_config["max_tokens"],
        },
    )

    return model
```

- [ ] **Step 2: Run existing tests to verify nothing breaks**

Run: `python -m pytest tests/unit/test_agent_factory.py -v`
Expected: All tests PASS (they mock `_create_model` at the factory level, so they don't see the internal change)

- [ ] **Step 3: Commit**

```bash
git add src/services/agent_factory.py
git commit -m "feat: use system client for LLM calls in agent factory"
```

---

### Task 2: Update `_create_model()` in `agent.py`

**Files:**
- Modify: `src/services/agent.py:319-348`

- [ ] **Step 1: Change client call in `SlideGeneratorAgent._create_model()`**

The method at line 319 should change to use `get_system_client()` (already imported at line 31):

```python
def _create_model(self) -> ChatDatabricks:
    """Create LangChain Databricks model with system client.

    Creates a new ChatDatabricks instance per request using the
    system WorkspaceClient (service principal). This ensures users
    do not need workspace-level permissions on the serving endpoint.
    """
    try:
        from src.core.defaults import DEFAULT_CONFIG
        system_client = get_system_client()
        llm_config = DEFAULT_CONFIG["llm"]

        model = ChatDatabricks(
            endpoint=llm_config["endpoint"],
            temperature=llm_config["temperature"],
            max_tokens=llm_config["max_tokens"],
            top_p=llm_config["top_p"],
            workspace_client=system_client,
        )

        logger.info(
            "ChatDatabricks model created with system client",
            extra={
                "endpoint": llm_config["endpoint"],
                "temperature": llm_config["temperature"],
                "max_tokens": llm_config["max_tokens"],
            },
        )

        return model
    except Exception as e:
        raise AgentError(f"Failed to create ChatDatabricks model: {e}") from e
```

- [ ] **Step 2: Remove unused `get_user_client` import**

In `src/services/agent.py` line 32, remove `get_user_client` from the import block (it is no longer used anywhere in agent.py):

```python
# Before (lines 27-33)
from src.core.databricks_client import (
    ...
    get_system_client,
    get_user_client,
    ...
)

# After — remove the get_user_client line
from src.core.databricks_client import (
    ...
    get_system_client,
    ...
)
```

- [ ] **Step 3: Run existing tests to verify they pass**

Run: `python -m pytest tests/unit/test_agent.py::TestSlideGeneratorAgent::test_create_model_valid -v`
Expected: FAIL — test still mocks `get_user_client` which no longer exists in agent.py. We fix this next.

- [ ] **Step 4: Update test mock to use `get_system_client`**

In `tests/unit/test_agent.py` line 139, change:

```python
# Before
with patch("src.services.agent.get_user_client") as mock_user_client:
    mock_user_client.return_value = MagicMock()
    model = agent_with_mocks._create_model()

# After
with patch("src.services.agent.get_system_client") as mock_system_client:
    mock_system_client.return_value = MagicMock()
    model = agent_with_mocks._create_model()
```

- [ ] **Step 5: Update test mock in `test_default_config_integration.py`**

In `tests/unit/test_default_config_integration.py` lines 17-44, change:

```python
# Before (line 17)
with patch("src.services.agent.get_user_client") as mock_user_client, \
# ...
    mock_user_client.return_value = MagicMock()
# ...
    workspace_client=mock_user_client.return_value,

# After
with patch("src.services.agent.get_system_client") as mock_system_client, \
# ...
    mock_system_client.return_value = MagicMock()
# ...
    workspace_client=mock_system_client.return_value,
```

- [ ] **Step 6: Run all affected tests**

Run: `python -m pytest tests/unit/test_agent.py tests/unit/test_default_config_integration.py tests/unit/test_agent_factory.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/services/agent.py tests/unit/test_agent.py tests/unit/test_default_config_integration.py
git commit -m "feat: use system client for LLM calls in SlideGeneratorAgent"
```

---

### Task 3: Update docstrings in `databricks_client.py`

**Files:**
- Modify: `src/core/databricks_client.py:1-15,492-501`

- [ ] **Step 1: Update module-level docstring**

Change line 6 from:
```python
2. User Client (request-scoped): Uses forwarded user token for Genie/LLM/MLflow
```
to:
```python
2. User Client (request-scoped): Uses forwarded user token for Genie queries and tools
```

- [ ] **Step 2: Update `get_user_client()` docstring**

Change line 494 from:
```python
Get the user-scoped WorkspaceClient for Genie/LLM/MLflow operations.
```
to:
```python
Get the user-scoped WorkspaceClient for Genie queries and tool operations.
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/unit/ -v --tb=short`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/core/databricks_client.py
git commit -m "docs: update client docstrings to reflect LLM using system client"
```
