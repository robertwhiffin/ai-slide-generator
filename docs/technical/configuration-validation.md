# Configuration Validation Feature

## Overview

The configuration validation feature tests components of a session's agent configuration to ensure they are working correctly before use. Validation is performed against the session's `agent_config` (validated with Pydantic models on every write).

## Components Tested

### 1. LLM Endpoint
- **Test**: Sends a simple "hello" message to the backend's fixed LLM endpoint
- **Validates**:
  - Endpoint is accessible
  - Authentication is working
  - Model responds correctly
- **Error Example**: "Failed to call LLM: Endpoint not found"

### 2. Genie Spaces (Optional)
- **Test**: Executes query "Return a table of how many rows you have per table" against each configured Genie space
- **Validates**:
  - Each Genie space exists and is accessible
  - User has permissions to query the space
  - Space contains data
- **Error Example**: "Failed to query Genie: Permission denied"
- **Prompt-only mode**: When no Genie tools are in the agent config, validation is skipped with success message "No Genie tools configured (prompt-only mode)"

### 3. MLflow Experiment
- **Test**: Creates or accesses the MLflow experiment
- **Validates**:
  - Experiment path is valid
  - User has write permissions
  - Tracking URI is configured correctly
- **Error Example**: "Failed to create MLflow experiment: Directory does not exist"

## Agent Config Validation (Pydantic)

The `agent_config` JSON is validated by Pydantic models on every write (`PUT /api/sessions/{id}/agent-config` and `PATCH /api/sessions/{id}/agent-config/tools`). This ensures structural correctness (valid tool types, required fields) before persistence.

## API Endpoint

### POST `/api/config/validate/{session_id}`

**Request:**
```http
POST /api/config/validate/abc123
```

**Response:**
```json
{
  "success": true,
  "session_id": "abc123",
  "results": [
    {
      "component": "LLM",
      "success": true,
      "message": "Successfully connected to LLM endpoint",
      "details": "Response received: Hello! How can I help you today?..."
    },
    {
      "component": "Genie: Sales Data",
      "success": true,
      "message": "Successfully connected to Genie space: 01abc123...",
      "details": "Query executed and returned data"
    },
    {
      "component": "MLflow",
      "success": true,
      "message": "Successfully accessed MLflow experiment: /Workspace/Users/...",
      "details": "Experiment ID: 12345"
    }
  ]
}
```

## Frontend Integration

The validation is available from the AgentConfigBar for the current session.

### UI Flow
1. User triggers configuration validation
2. Loading spinner shown during testing
3. Backend runs validation tests (LLM, each Genie space, MLflow)
4. Results displayed with:
   - Overall status
   - Individual component results with pass/fail indicators
   - Detailed messages and error information

## Backend Implementation

### Service Layer
**File**: `src/services/config/config_validator.py`

```python
class ConfigurationValidator:
    """Validates configuration by testing each component."""

    def validate_all(self) -> Dict[str, Any]:
        """Run all validation tests."""
        self._validate_llm()      # Test LLM endpoint
        # Genie validation for each configured tool
        for tool in self.agent_config.get("tools", []):
            if tool["type"] == "genie":
                self._validate_genie(tool)
        self._validate_mlflow()   # Test MLflow experiment
        return results
```

### API Layer
**File**: `src/api/routes/config/validation.py`

Provides REST endpoint for triggering validation against a session's agent config.

## Use Cases

### 1. Session Setup
After configuring tools via the AgentConfigBar, validate to ensure all components are working.

### 2. Troubleshooting
When experiencing issues, run validation to identify which component is failing.

### 3. Permission Verification
Verify that user has necessary permissions to use LLM endpoints, Genie spaces, and MLflow experiments.

### 4. Pre-Deployment Testing
Before deploying to production, validate that all configurations work in the target environment.

## Error Handling

Each component validation is independent:
- If LLM fails, Genie and MLflow tests still run
- Specific error messages help identify the exact issue
- Details field provides additional context (endpoint names, IDs, etc.)

## Cleanup

The Genie validation automatically cleans up:
- Test conversation is deleted after validation
- No permanent data is created during testing
- MLflow experiment is created if it doesn't exist (intentional - needed for actual use)

## Future Enhancements

Potential improvements:
- Add validation for individual configuration components (not just full profile)
- Add performance metrics (response time, latency)
- Add validation history/logs
- Add automatic validation on profile save
- Add validation scheduling (periodic health checks)

