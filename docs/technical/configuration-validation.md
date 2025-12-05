# Configuration Validation Feature

## Overview

The configuration validation feature tests all components of a profile configuration to ensure they are working correctly before use.

## Components Tested

### 1. LLM Endpoint
- **Test**: Sends a simple "hello" message to the configured LLM endpoint
- **Validates**: 
  - Endpoint is accessible
  - Authentication is working
  - Model responds correctly
- **Error Example**: "Failed to call LLM: Endpoint not found"

### 2. Genie Space
- **Test**: Executes query "Return a table of how many rows you have per table"
- **Validates**:
  - Genie space exists and is accessible
  - User has permissions to query the space
  - Space contains data
- **Error Example**: "Failed to query Genie: Permission denied"

### 3. MLflow Experiment
- **Test**: Creates or accesses the configured MLflow experiment
- **Validates**:
  - Experiment path is valid
  - User has write permissions
  - Tracking URI is configured correctly
- **Error Example**: "Failed to create MLflow experiment: Directory does not exist"

## API Endpoint

### POST `/api/config/validate/{profile_id}`

**Request:**
```http
POST /api/config/validate/1
```

**Response:**
```json
{
  "success": true,
  "profile_id": 1,
  "profile_name": "default",
  "results": [
    {
      "component": "LLM",
      "success": true,
      "message": "Successfully connected to LLM endpoint: databricks-claude-sonnet-4-5",
      "details": "Response received: Hello! How can I help you today?..."
    },
    {
      "component": "Genie",
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

**Error Response:**
```json
{
  "success": false,
  "profile_id": 1,
  "profile_name": "default",
  "results": [
    {
      "component": "LLM",
      "success": false,
      "message": "Failed to call LLM: Endpoint not found",
      "details": "Endpoint: databricks-invalid-endpoint"
    }
  ]
}
```

## Frontend Integration

The validation button is integrated into the ProfileDetail view in "View" mode.

### Location
- Profile Detail Modal → View Mode → Configuration Validation section
- Click "Test Configuration" button to run validation

### UI Flow
1. User clicks "Test Configuration" button
2. Button shows loading spinner with "Testing Configuration..."
3. Backend runs validation tests (LLM, Genie, MLflow)
4. Results displayed with:
   - Overall status (✅ All Tests Passed / ❌ Configuration Issues Detected)
   - Individual component results with pass/fail indicators
   - Detailed messages and error information
   - Help text explaining what each test does

### Visual Indicators
- ✅ Green background for passing tests
- ❌ Red background for failing tests
- Loading spinner during validation
- Detailed error messages for troubleshooting

## Backend Implementation

### Service Layer
**File**: `src/services/config/config_validator.py`

```python
class ConfigurationValidator:
    """Validates configuration by testing each component."""
    
    def validate_all(self) -> Dict[str, Any]:
        """Run all validation tests."""
        self._validate_llm()      # Test LLM endpoint
        self._validate_genie()    # Test Genie query
        self._validate_mlflow()   # Test MLflow experiment
        return results
```

### API Layer
**File**: `src/api/routes/config/validation.py`

Provides REST endpoint for triggering validation.

## Use Cases

### 1. Profile Setup
After creating or editing a profile, validate to ensure all components are configured correctly.

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

