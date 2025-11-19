# Phase 3: API Endpoints

**Duration:** Days 6-7  
**Status:** Complete ✅  
**Prerequisites:** Phase 2 Complete (Backend Services)  
**Completion Date:** November 19, 2025

## Objectives

- Create REST API endpoints for all configuration operations
- Implement request/response Pydantic models
- Add error handling and HTTP status codes
- Integrate with FastAPI dependency injection
- Document API with OpenAPI/Swagger
- Add authentication/authorization checks

## Files to Create

```
src/api/
├── routes/
│   └── config/
│       ├── __init__.py
│       ├── profiles.py
│       ├── ai_infra.py
│       ├── genie.py
│       ├── mlflow.py
│       └── prompts.py
└── models/
    └── config/
        ├── __init__.py
        ├── requests.py
        └── responses.py
```

## Implementation Summary

### Step 1: Request/Response Models

**File:** `src/api/models/config/requests.py`

Create Pydantic models for all API requests:
- `ProfileCreate`, `ProfileUpdate`
- `AIInfraConfigUpdate`
- `GenieSpaceCreate`, `GenieSpaceUpdate`
- `MLflowConfigUpdate`
- `PromptsConfigUpdate`

**File:** `src/api/models/config/responses.py`

Create response models:
- `ProfileSummary`, `ProfileDetail`
- `AIInfraConfig`, `GenieSpace`, `MLflowConfig`, `PromptsConfig`
- `ConfigHistoryEntry`
- Standard error responses

### Step 2: Profile Endpoints

**File:** `src/api/routes/config/profiles.py`

Implement:
- `GET /api/config/profiles` - List all profiles
- `GET /api/config/profiles/{id}` - Get profile details
- `GET /api/config/profiles/default` - Get default profile
- `POST /api/config/profiles` - Create profile
- `PUT /api/config/profiles/{id}` - Update profile
- `DELETE /api/config/profiles/{id}` - Delete profile
- `POST /api/config/profiles/{id}/set-default` - Set as default
- `POST /api/config/profiles/{id}/duplicate` - Duplicate profile
- `POST /api/config/profiles/{id}/load` - Load profile for session

### Step 3: Configuration Endpoints

Create routes for each config domain:

**AI Infrastructure** (`ai_infra.py`):
- GET/PUT for AI config
- GET for available endpoints

**Genie** (`genie.py`):
- CRUD operations for Genie spaces
- Set default space

**MLflow** (`mlflow.py`):
- GET/PUT for experiment name

**Prompts** (`prompts.py`):
- GET/PUT for prompts
- Validate placeholders

### Step 4: Error Handling

Implement consistent error handling:
- 400: Validation errors
- 403: Permission denied
- 404: Not found
- 409: Conflict (e.g., duplicate name)
- 500: Server errors

### Step 5: Wire Up Routes

Update `src/api/main.py` to include config routes:

```python
from src.api.routes.config import (
    profiles_router,
    ai_infra_router,
    genie_router,
    mlflow_router,
    prompts_router,
)

app.include_router(profiles_router, prefix="/api/config", tags=["config"])
app.include_router(ai_infra_router, prefix="/api/config", tags=["config"])
app.include_router(genie_router, prefix="/api/config", tags=["config"])
app.include_router(mlflow_router, prefix="/api/config", tags=["config"])
app.include_router(prompts_router, prefix="/api/config", tags=["config"])
```

## Testing

Create integration tests for all endpoints:

```python
# tests/integration/test_config_api.py

def test_list_profiles(client):
    response = client.get("/api/config/profiles")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_create_profile(client):
    data = {
        "name": "test-profile",
        "description": "Test",
        "copy_from_profile_id": null
    }
    response = client.post("/api/config/profiles", json=data)
    assert response.status_code == 201
    assert response.json()["name"] == "test-profile"

# Test all CRUD operations for each domain
```

## Deliverables

- [x] All API routes implemented ✅
- [x] Request/response models defined ✅
- [x] Error handling consistent ✅
- [x] OpenAPI documentation generated ✅
- [x] Integration tests passing (24/24) ✅
- [x] API accessible via Swagger UI ✅

## Next Steps

Proceed to **Phase 4: Application Settings Integration**.

