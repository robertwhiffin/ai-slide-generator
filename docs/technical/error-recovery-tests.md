# Error Recovery Test Suite

**One-Line Summary:** Unit tests for error handling and recovery across LLM, Genie, and database failures, plus graceful degradation when services are unavailable.

---

## 1. Overview

The error recovery test suite validates that the system handles failures gracefully across all external dependencies. Tests verify that errors are caught, state is preserved, and the system remains usable after failures.

### Test File

| File | Test Count | Purpose |
|------|------------|---------|
| `tests/unit/test_error_recovery.py` | ~28 | LLM, Genie, DB errors, state recovery |

---

## 2. External Dependencies Tested

| Dependency | Failure Modes | Impact |
|------------|---------------|--------|
| LLM (Databricks) | Timeout, rate limit, auth, connection | Slide generation fails |
| Genie API | Space not found, permission, timeout | Data queries fail |
| Database | Connection lost, constraints, deadlock | State persistence fails |
| MLflow | Tracking unavailable | Observability degrades |

---

## 3. Test Categories

### 3.1 LLM Error Handling

**Goal:** Validate LLM failures are handled gracefully with clear error messages.

```
tests/unit/test_error_recovery.py::TestLLMErrorHandling
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_llm_timeout_raises_timeout_error` | Request times out | `LLMInvocationError` with "timed out" |
| `test_llm_auth_failure_clear_message` | 401 Unauthorized | Error mentions "unauthorized" or "auth" |
| `test_llm_invalid_response_handled` | Canvas without script | `AgentError` about canvas/chart |
| `test_llm_empty_response_handled` | Empty string response | Returns valid (empty) result |
| `test_llm_connection_error_propagates` | Connection refused | `AgentError` with "connection" |
| `test_llm_rate_limit_error_propagates` | 429 Too Many Requests | Error mentions "rate" or "429" |

**Exception Hierarchy:**
```
AgentError (base)
├── LLMInvocationError
└── ToolExecutionError
```

---

### 3.2 Genie Error Handling

**Goal:** Validate Genie API failures are handled with helpful messages.

```
tests/unit/test_error_recovery.py::TestGenieErrorHandling
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_genie_space_not_found` | Invalid space_id | `GenieToolError` with "space" |
| `test_genie_query_timeout` | Query times out | `GenieToolError` with "timeout" |
| `test_genie_permission_denied` | 403 Forbidden | Error mentions "access" or "forbidden" |
| `test_genie_empty_result_handled` | No rows returned | Returns empty result (not error) |
| `test_genie_not_configured_error` | `genie = None` | Error mentions "not configured" |
| `test_genie_conversation_init_failure` | Init fails | `GenieToolError` with "failed" |
| `test_genie_retry_on_transient_error` | Fails twice, then succeeds | Returns result after 3 attempts |

**Empty Result Handling:**
```python
# Empty result returns valid structure, not error
result = {
    "data": "",
    "message": "",
    "conversation_id": "conv-123"
}
```

---

### 3.3 Database Error Handling

**Goal:** Validate database failures don't corrupt state.

```
tests/unit/test_error_recovery.py::TestDatabaseErrorHandling
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_db_connection_lost_during_save` | `OperationalError` on commit | Exception propagated |
| `test_db_session_not_found_error` | Query returns None | `SessionNotFoundError` |
| `test_db_integrity_error_on_duplicate` | Constraint violation | `IntegrityError` propagated |

**Session Manager Pattern:**
```python
with get_db_session() as session:
    # Operations here
    # __exit__ handles commit/rollback
```

---

### 3.4 State Recovery Tests

**Goal:** Validate state consistency after errors.

```
tests/unit/test_error_recovery.py::TestStateRecovery
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_session_not_found_raises_agent_error` | Invalid session_id | `AgentError` with "Session not found" |
| `test_can_retry_after_error` | First call fails, second succeeds | Second call works |
| `test_session_survives_agent_error` | LLM fails mid-operation | Session state unchanged |
| `test_clear_session_removes_state` | Clear session | Session removed, get raises error |

**Key Invariant:** Failed operations must not modify session state.

```python
# Session state preserved after error
session_before = agent.get_session(session_id)
try:
    agent.generate_slides("Create slides", session_id=session_id)  # Fails
except AgentError:
    pass
session_after = agent.get_session(session_id)
assert session_before["genie_conversation_id"] == session_after["genie_conversation_id"]
```

---

### 3.5 Graceful Degradation Tests

**Goal:** Validate system works with reduced functionality when services are down.

```
tests/unit/test_error_recovery.py::TestGracefulDegradation
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_agent_works_without_genie` | `genie = None` | Session created, tools empty |
| `test_mlflow_failure_doesnt_break_agent` | MLflow unavailable | Agent initializes normally |
| `test_genie_failure_in_tool_propagates_error` | Genie tool fails | `GenieToolError` propagated |

**Prompt-Only Mode:**
```python
# Without Genie, agent works but has no tools
agent = SlideGeneratorAgent()  # genie = None
tools = agent._create_tools_for_session(session_id)
assert len(tools) == 0  # No Genie tool available
```

---

### 3.6 Exception Hierarchy Tests

**Goal:** Validate exception class relationships for proper error handling.

```
tests/unit/test_error_recovery.py::TestExceptionHierarchy
```

| Test | Assertion |
|------|-----------|
| `test_agent_error_is_base` | `issubclass(AgentError, Exception)` |
| `test_llm_invocation_error_inherits` | `issubclass(LLMInvocationError, AgentError)` |
| `test_tool_execution_error_inherits` | `issubclass(ToolExecutionError, AgentError)` |
| `test_genie_tool_error_inherits` | `issubclass(GenieToolError, Exception)` |
| `test_can_catch_agent_errors` | Both LLM and Tool errors caught by `AgentError` |

**Exception Imports:**
```python
from src.services.agent import AgentError, LLMInvocationError, ToolExecutionError
from src.services.tools import GenieToolError
```

---

## 4. Test Infrastructure

### Mock Settings Fixtures

```python
@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = Mock()
    settings.llm.endpoint = "test-endpoint"
    settings.llm.timeout = 120
    settings.genie = Mock()
    settings.genie.space_id = "test-space-id"
    return settings

@pytest.fixture
def mock_settings_no_genie():
    """Mock settings without Genie for prompt-only mode."""
    settings = Mock()
    # ... same as above ...
    settings.genie = None  # No Genie
    return settings
```

### Agent with All Mocks

```python
@pytest.fixture
def agent_with_mocks(mock_settings, mock_client, mock_mlflow, mock_langchain_components):
    """Create agent with all dependencies mocked."""
    with patch("src.services.agent.get_settings") as mock_get_settings:
        # ... many patches ...
        agent = SlideGeneratorAgent()
        return agent
```

---

## 5. Running the Tests

```bash
# Run all error recovery tests
pytest tests/unit/test_error_recovery.py -v

# Run specific category
pytest tests/unit/test_error_recovery.py::TestLLMErrorHandling -v

# Run with logging visible
pytest tests/unit/test_error_recovery.py -v -s --log-cli-level=DEBUG

# Run single test
pytest tests/unit/test_error_recovery.py -k "test_llm_timeout" -v
```

---

## 6. Key Invariants

These invariants must NEVER be violated:

1. **State preservation:** Failed operations must not modify existing state
2. **Error clarity:** Error messages must indicate the failure type clearly
3. **Retry safety:** System must accept new requests after any error
4. **Graceful degradation:** Missing services reduce features, don't crash
5. **Exception hierarchy:** All agent errors catchable via `AgentError`

---

## 7. Debugging Error Scenarios

When investigating error recovery issues:

1. Check exception type matches expected hierarchy
2. Verify state was not modified on failure
3. Check logs for retry attempts (if applicable)
4. Verify graceful fallback when service unavailable

**Log Patterns:**
- `LLM request timed out after X seconds`
- `Genie query failed: <error>`
- `Database operation failed, rolling back`

---

## 8. Cross-References

- [Backend Overview](./backend-overview.md) - Agent architecture
- [Multi-User Concurrency](./multi-user-concurrency.md) - Session locking
- [Lakebase Integration](./lakebase-integration.md) - Genie configuration
- [Database Configuration](./database-configuration.md) - Persistence layer
