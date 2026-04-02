# Configuration Validation Feature

## Overview

The configuration validation feature tests components of a profile's configuration to ensure they are working correctly before use. Validation is performed against settings loaded from the database for a given `profile_id`.

> **Note:** This validator is currently unused. It is exported from `src/services/__init__.py` but has no API route, no frontend caller, and no backend caller. It may be orphaned/legacy code.

## Components Tested

### 1. LLM Endpoint
- **Test**: Sends a simple "hello" message to the backend's fixed LLM endpoint (from `DEFAULT_CONFIG`)
- **Validates**:
  - Endpoint is accessible
  - Authentication is working
  - Model responds correctly
- **Error Example**: "Failed to call LLM: Endpoint not found"

### 2. Genie Space (Optional)
- **Test**: Starts a conversation and executes query "Return a table of how many rows you have per table" against the profile's configured Genie space
- **Validates**:
  - The Genie space exists and is accessible
  - User has permissions to query the space
  - Space contains data
- **Error Example**: "Failed to query Genie: Permission denied"
- **Prompt-only mode**: When `self.settings.genie` is not configured, validation is skipped with success message "Genie not configured (prompt-only mode)"

### 3. MLflow Experiment
- **Not currently validated.** The `validate_all()` method does not call an MLflow validation step. Only LLM and Genie are tested.

## Agent Config Validation (Pydantic)

The `agent_config` JSON is validated by Pydantic models on every write (`PUT /api/sessions/{id}/agent-config` and `PATCH /api/sessions/{id}/agent-config/tools`). This ensures structural correctness (valid tool types, required fields) before persistence.

## API Endpoint

There is no API endpoint for this validator. The previously documented `POST /api/config/validate/{session_id}` route does not exist in the codebase. The file `src/api/routes/config/validation.py` does not exist either.

The validator can only be invoked programmatically via the convenience function:

```python
from src.services.config_validator import validate_profile_configuration

results = validate_profile_configuration(profile_id=42)
```

**Response shape:**
```json
{
  "success": true,
  "profile_id": 42,
  "profile_name": "My Profile",
  "results": [
    {
      "component": "LLM",
      "success": true,
      "message": "Successfully connected to LLM endpoint: ...",
      "details": "Response received: Hello! How can I help you today?..."
    },
    {
      "component": "Genie",
      "success": true,
      "message": "Successfully connected to Genie space: 01abc123...",
      "details": "Query executed and returned message, data"
    }
  ]
}
```

## Frontend Integration

There is currently no frontend integration. No frontend code calls a validation endpoint or invokes the validator.

## Backend Implementation

### Service Layer
**File**: `src/services/config_validator.py`

The validator is profile-based. It takes a `profile_id`, loads settings from the database via `load_settings_from_database(profile_id)`, and validates components using those settings.

```python
class ConfigurationValidator:
    """Validates configuration by testing each component."""

    def __init__(self, profile_id: int):
        self.profile_id = profile_id
        self.settings = None
        self.results: List[ValidationResult] = []

    def validate_all(self) -> Dict[str, Any]:
        """Run all validation tests."""
        self.settings = load_settings_from_database(self.profile_id)
        self._validate_llm()      # Test LLM endpoint
        if self.settings.genie:
            self._validate_genie() # Test Genie space
        return results
```

The class is exported from `src/services/__init__.py` alongside a convenience function `validate_profile_configuration(profile_id)`.

### API Layer

No route exists. There is no API layer for this feature.

## Use Cases

### 1. Profile Setup
After configuring a profile's tools, validate to ensure all components are working.

### 2. Troubleshooting
When experiencing issues, run validation to identify which component is failing.

### 3. Permission Verification
Verify that user has necessary permissions to use LLM endpoints and Genie spaces.

## Error Handling

Each component validation is independent:
- If LLM fails, Genie test still runs
- Specific error messages help identify the exact issue
- Details field provides additional context (endpoint names, space IDs, etc.)

## Cleanup

The Genie validation automatically cleans up:
- Test conversation is deleted after validation
- No permanent data is created during testing

## Future Enhancements

Potential improvements:
- Wire up an API route so the frontend can trigger validation
- Add MLflow experiment validation
- Add validation for individual configuration components (not just full profile)
- Add performance metrics (response time, latency)
- Add validation history/logs
- Add automatic validation on profile save
- Add validation scheduling (periodic health checks)

