# API Overview

The Databricks tellr API is a RESTful API built with FastAPI that provides endpoints for generating, editing, and managing AI-generated slide presentations.

## Base URL

The API base URL depends on your deployment:

- **Local Development**: `http://localhost:8000`
- **Databricks Apps**: `https://<workspace-url>/apps/<app-name>`

All endpoints are prefixed with `/api`.

## Authentication

When running as a Databricks App, authentication is handled automatically via the Databricks Apps proxy. The proxy forwards the authenticated user's token in the `x-forwarded-access-token` header.

For local development, authentication uses the system Databricks client configured via environment variables:
- `DATABRICKS_HOST`
- `DATABRICKS_TOKEN`

## Versioning

The API version is included in the health check endpoint response. Current version: `0.3.0`

## Request/Response Format

### Request Headers

```
Content-Type: application/json
x-forwarded-access-token: <user-token> (when running as Databricks App)
```

### Response Format

All successful responses return JSON. Error responses follow standard HTTP status codes:

- `200 OK` - Successful request
- `201 Created` - Resource created successfully
- `204 No Content` - Successful deletion
- `400 Bad Request` - Invalid request parameters
- `404 Not Found` - Resource not found
- `409 Conflict` - Session is already processing another request
- `500 Internal Server Error` - Server error

### Error Response Format

```json
{
  "detail": "Error message describing what went wrong"
}
```

## Common Patterns

### Session-Based Operations

Most operations require a `session_id` to identify the conversation context. Sessions are created automatically on the first message or can be created explicitly via the sessions endpoint.

### Slide Context

When editing slides, operations accept a `slide_context` parameter that specifies which slides to operate on. The context includes contiguous slide indices.

### Streaming Responses

For long-running operations, the API supports Server-Sent Events (SSE) streaming. Use the `/api/chat/stream` endpoint for real-time slide generation updates.

### Async Processing

For very long operations, use the async endpoints:
1. Submit a request via `/api/chat/async` to get a `request_id`
2. Poll `/api/chat/poll/{request_id}` to check status
3. Retrieve results when complete

## Rate Limiting

Currently, rate limiting is handled via session locking. Only one request per session can be processed at a time. Concurrent requests to the same session will return `409 Conflict`.

## API Categories

- **[Sessions](./sessions.md)** - Session management and lifecycle
- **[Chat](./chat.md)** - Slide generation and conversation
- **[Slides](./slides.md)** - Slide CRUD operations
- **[Export](./export.md)** - PowerPoint and PDF export
- **[Verification](./verification.md)** - LLM-based slide verification
- **[Settings](./settings.md)** - Configuration management (profiles, prompts, styles)

## OpenAPI Schema

For complete API documentation including request/response schemas, see the [OpenAPI Schema](./openapi-schema.md) page or access the interactive Swagger UI at `/docs` when running the API locally.

