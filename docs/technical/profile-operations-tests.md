# Agent Config Operations Test Suite

**One-Line Summary:** Playwright test coverage for AgentConfigBar, AgentConfigContext, tool management, and profile save/load operations.

---

## 1. Overview

The agent config operations test suite validates that session-bound configuration UI correctly interacts with the backend. This covers the AgentConfigBar (tool chips, add/remove tools), AgentConfigContext (config state management), and profile save/load workflows.

### Test Files

| File | Purpose |
|------|---------|
| `frontend/tests/e2e/agent-config-ui.spec.ts` | Mocked UI behavior tests for AgentConfigBar and config context |
| `frontend/tests/e2e/agent-config-integration.spec.ts` | Real backend tests for config persistence and profile operations |

### Testing Approach

- **Mocked UI tests**: Fast tests validating UI behavior without backend
- **Integration tests**: Real backend tests validating database persistence

---

## 2. Mocked UI Tests

These tests use mocked API responses for fast execution.

### 2.1 AgentConfigBar Tests

| Test | Validation |
|------|------------|
| `displays tool chips for configured Genie spaces` | Chips show space names |
| `shows add tool button` | Button visible and functional |
| `removes tool on chip dismiss` | Tool removed from config |
| `shows Genie conversation link on tool chip` | Link navigates to Genie |
| `shows empty state when no tools configured` | Prompt-only mode indicator |

### 2.2 AgentConfigContext Tests

| Test | Validation |
|------|------------|
| `provides agent config from session` | Config loaded on mount |
| `updates tools via PATCH endpoint` | API called correctly |
| `updates full config via PUT endpoint` | API called correctly |
| `loads profile into session` | Profile config replaces session config |
| `saves session config as profile` | Snapshot created |

### 2.3 Tool Discovery Tests

| Test | Validation |
|------|------------|
| `lists available Genie spaces` | Spaces fetched from discovery endpoint |
| `lists available MCP servers` | Servers fetched from discovery endpoint |
| `adds selected tool to session config` | Tool added via PATCH |

---

## 3. Integration Tests

These tests hit the real backend to validate database persistence.

### 3.1 Agent Config CRUD

| Test | Database Validation |
|------|---------------------|
| `session starts with default agent config` | Config JSON populated |
| `adding Genie space persists to agent_config` | Re-fetch shows new tool |
| `removing Genie space persists to agent_config` | Re-fetch shows tool removed |
| `updating slide style persists to agent_config` | Re-fetch shows new style ID |
| `updating deck prompt persists to agent_config` | Re-fetch shows new prompt ID |

### 3.2 Profile Save/Load

| Test | Behavior Validation |
|------|---------------------|
| `save session config as profile` | Profile created with agent_config JSON |
| `load profile into session updates agent_config` | Session config matches profile |
| `loading profile resets conversation IDs` | Genie conversation IDs cleared |
| `saved profile appears in profile list` | GET /api/profiles returns it |
| `delete profile removes from list` | Profile no longer returned |

### 3.3 Multiple Genie Spaces

| Test | Behavior Validation |
|------|---------------------|
| `session supports multiple Genie spaces` | Multiple tools in config |
| `each Genie space tracks its own conversation ID` | Independent conversation_id per tool |
| `removing one space preserves others` | Remaining tools unchanged |

---

## 4. Running the Tests

```bash
# Run only UI tests (fast, no backend needed)
npx playwright test tests/e2e/agent-config-ui.spec.ts

# Run only integration tests (requires backend at localhost:8000)
npx playwright test tests/e2e/agent-config-integration.spec.ts

# Run all agent config tests
npx playwright test tests/e2e/agent-config-*.spec.ts

# Run with headed browser for debugging
npx playwright test tests/e2e/agent-config-integration.spec.ts --headed
```

---

## 5. Key Invariants

These invariants must NEVER be violated:

1. **Session-bound config**: All configuration lives in the session's `agent_config` column
2. **Per-request agent**: Agent is built fresh from `agent_config` on every request
3. **Tool isolation**: Each Genie space has its own conversation ID
4. **Profile snapshots**: Profiles are copies of agent_config, not live references
5. **Config validation**: Pydantic validates `agent_config` on every write

---

## 6. Cross-References

- [Agent Config Flow](./profile-switch-genie-flow.md) - Session-bound configuration details
- [Deck Operations Tests](./deck-operations-tests.md) - Related test suite patterns
- [Edit Operations Tests](./edit-operations-tests.md) - LLM response validation tests
- [Frontend Overview](./frontend-overview.md) - Component architecture
