# API Routes Test Suite

**One-Line Summary:** Integration tests for HTTP layer behavior covering all FastAPI endpoints including chat, slides, sessions, verification, and error response consistency.

---

## 1. Overview

The API routes test suite validates the HTTP layer of the FastAPI backend. These tests verify request validation, response structure, error handling, and status codes without testing underlying business logic (services are mocked).

### Test File

| File | Test Count | Purpose |
|------|------------|---------|
| `tests/integration/test_api_routes.py` | ~70 | HTTP layer validation for all API endpoints |

---

## 2. Test Infrastructure

### Database Setup

Tests use an in-memory SQLite database with dependency injection:

```python
@pytest.fixture(scope="function")
def test_db_engine():
    """Create test database engine with SQLite in-memory."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
```

### Service Mocking

Services are mocked to isolate HTTP layer testing:

```python
@pytest.fixture
def mock_chat_service():
    """Mock the chat service for route testing."""
    with patch("src.api.routes.chat.get_chat_service") as mock_chat:
        with patch("src.api.routes.slides.get_chat_service") as mock_slides:
            service = MagicMock()
            mock_chat.return_value = service
            mock_slides.return_value = service
            yield service
```

---

## 3. Test Categories

### 3.1 Chat Endpoint Tests

**Goal:** Validate `/api/chat` endpoints for sync, async, and polling operations.

```
tests/integration/test_api_routes.py::TestChatEndpoints
```

| Test | Endpoint | Scenario | Expected |
|------|----------|----------|----------|
| `test_chat_requires_session_id` | POST `/api/chat` | Missing session_id | 422 |
| `test_chat_requires_message` | POST `/api/chat` | Missing message | 422 |
| `test_chat_empty_message_rejected` | POST `/api/chat` | Empty message | 422 |
| `test_chat_session_not_found` | POST `/api/chat` | Invalid session_id | 404 |
| `test_chat_session_busy` | POST `/api/chat` | Session locked | 409 |
| `test_chat_success` | POST `/api/chat` | Valid request | 200 |
| `test_chat_with_slide_context` | POST `/api/chat` | With slide selection | 200 |
| `test_chat_invalid_slide_context_non_contiguous` | POST `/api/chat` | Non-contiguous indices | 422 |
| `test_chat_internal_error` | POST `/api/chat` | Service throws | 500 |
| `test_chat_async_submit` | POST `/api/chat/async` | Async job creation | 200 + request_id |
| `test_chat_poll_not_found` | GET `/api/chat/poll/{id}` | Unknown request | 404 |
| `test_chat_poll_success` | GET `/api/chat/poll/{id}` | Valid request | 200 + status |

**Key Validation:** Slide context must have contiguous indices and matching HTML lengths.

---

### 3.2 Slide Endpoint Tests

**Goal:** Validate `/api/slides` endpoints for CRUD operations.

```
tests/integration/test_api_routes.py::TestSlideEndpoints
```

| Test | Endpoint | Scenario | Expected |
|------|----------|----------|----------|
| `test_get_slides_requires_session_id` | GET `/api/slides` | Missing session_id | 422 |
| `test_get_slides_not_found` | GET `/api/slides` | No slides exist | 404 |
| `test_get_slides_success` | GET `/api/slides` | Valid session | 200 |
| `test_reorder_slides_invalid_order_type` | PUT `/api/slides/reorder` | new_order not array | 422 |
| `test_reorder_slides_session_busy` | PUT `/api/slides/reorder` | Session locked | 409 |
| `test_reorder_slides_success` | PUT `/api/slides/reorder` | Valid reorder | 200 |
| `test_update_slide_success` | PATCH `/api/slides/{index}` | Valid update | 200 |
| `test_update_slide_session_busy` | PATCH `/api/slides/{index}` | Session locked | 409 |
| `test_delete_slide_success` | DELETE `/api/slides/{index}` | Valid delete | 200 |
| `test_duplicate_slide_success` | POST `/api/slides/{index}/duplicate` | Valid duplicate | 200 |
| `test_update_slide_verification_success` | PATCH `/api/slides/{index}/verification` | Valid verification | 200 |

**Key Invariant:** All mutating operations require session lock acquisition.

---

### 3.3 Session Endpoint Tests

**Goal:** Validate `/api/sessions` endpoints for session management.

```
tests/integration/test_api_routes.py::TestSessionEndpoints
```

| Test | Endpoint | Scenario | Expected |
|------|----------|----------|----------|
| `test_list_sessions_success` | GET `/api/sessions` | List all | 200 |
| `test_list_sessions_with_user_filter` | GET `/api/sessions?user_id=` | With filter | 200 |
| `test_list_sessions_limit_validation` | GET `/api/sessions?limit=` | Invalid limit | 422 |
| `test_create_session_success` | POST `/api/sessions` | Create new | 200 |
| `test_create_session_with_title` | POST `/api/sessions` | With title | 200 |
| `test_get_session_success` | GET `/api/sessions/{id}` | Valid session | 200 |
| `test_get_session_not_found` | GET `/api/sessions/{id}` | Invalid id | 404 |
| `test_update_session_success` | PATCH `/api/sessions/{id}` | Rename | 200 |
| `test_delete_session_success` | DELETE `/api/sessions/{id}` | Delete | 200 |
| `test_get_session_messages_success` | GET `/api/sessions/{id}/messages` | Get messages | 200 |
| `test_get_session_slides_success` | GET `/api/sessions/{id}/slides` | Get slides | 200 |
| `test_cleanup_expired_sessions` | POST `/api/sessions/cleanup` | Cleanup | 200 |
| `test_export_session_success` | POST `/api/sessions/{id}/export` | Export | 200 |

**Limit Validation:** `limit` parameter must be between 1 and 100.

---

### 3.4 Verification Endpoint Tests

**Goal:** Validate `/api/verification` endpoints for slide verification.

```
tests/integration/test_api_routes.py::TestVerificationEndpoints
```

| Test | Endpoint | Scenario | Expected |
|------|----------|----------|----------|
| `test_verify_slide_success` | POST `/api/verification/{index}` | Valid verification | 200 |
| `test_verify_slide_session_not_found` | POST `/api/verification/{index}` | Invalid session | 404 |
| `test_verify_slide_no_slides` | POST `/api/verification/{index}` | No slides | 404 |
| `test_verify_slide_index_out_of_range` | POST `/api/verification/{index}` | Invalid index | 404 |
| `test_verify_slide_no_genie_data` | POST `/api/verification/{index}` | No source data | 200 (unknown) |
| `test_submit_feedback_success` | POST `/api/verification/{index}/feedback` | Submit feedback | 200 |
| `test_get_genie_link_success` | GET `/api/verification/genie-link` | Has conversation | 200 |
| `test_get_genie_link_no_conversation` | GET `/api/verification/genie-link` | No conversation | 200 (false) |

**Verification Result:** Returns `rating: "unknown"` when no Genie data available.

---

### 3.5 Error Response Tests

**Goal:** Validate consistent error response format across all endpoints.

```
tests/integration/test_api_routes.py::TestErrorResponses
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_404_includes_detail` | Session not found | `detail` field present |
| `test_422_validation_errors_include_detail` | Invalid request | `detail` field present |
| `test_422_validation_errors_are_structured` | Validation failure | Array of `{loc, msg, type}` |
| `test_500_hides_internal_details` | Service error | No stack traces leaked |
| `test_409_conflict_message` | Session busy | Helpful message |
| `test_method_not_allowed` | Wrong HTTP method | 405 |
| `test_invalid_json_body` | Malformed JSON | 422 |

**Security:** 500 errors must not expose internal details like passwords or stack traces.

---

## 4. Running the Tests

```bash
# Run all API route tests
pytest tests/integration/test_api_routes.py -v

# Run specific endpoint category
pytest tests/integration/test_api_routes.py::TestChatEndpoints -v

# Run with coverage
pytest tests/integration/test_api_routes.py --cov=src/api/routes --cov-report=html

# Run single test
pytest tests/integration/test_api_routes.py -k "test_chat_session_busy" -v
```

---

## 5. Key Invariants

These invariants must NEVER be violated:

1. **Request validation:** Missing required fields return 422 with structured errors
2. **Session locking:** All mutating operations check and acquire session lock
3. **Error consistency:** All errors include `detail` field with helpful message
4. **Security:** 500 errors never expose internal implementation details
5. **Resource not found:** Missing resources return 404 with clear identification

---

## 6. Status Code Reference

| Code | Meaning | When Used |
|------|---------|-----------|
| 200 | Success | Successful operation |
| 404 | Not Found | Session, slide, or request not found |
| 409 | Conflict | Session is busy (locked by another request) |
| 422 | Validation Error | Missing/invalid fields, constraint violations |
| 500 | Internal Error | Unexpected service failures |

---

## 7. Cross-References

- [Backend Overview](./backend-overview.md) - FastAPI architecture
- [Streaming Tests](./streaming-tests.md) - SSE endpoint testing
- [Export Tests](./export-tests.md) - Export endpoint testing
- [Database Configuration](./database-configuration.md) - Session persistence
