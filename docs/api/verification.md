# Verification API

Endpoints for verifying slide accuracy using LLM as Judge against Genie source data.

## Verify Slide

Verify a slide's numerical accuracy against the Genie data used to generate it.

**POST** `/api/verification/{slide_index}`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `slide_index` | integer | Yes | Slide index to verify (0-based) |

### Request Body

```json
{
  "session_id": "abc123"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |

### Response

```json
{
  "score": 0.95,
  "rating": "excellent",
  "explanation": "All numerical claims match the source data. The revenue figures are accurate.",
  "issues": [],
  "duration_ms": 2500,
  "trace_id": "mlflow_trace_abc123",
  "genie_conversation_id": "genie_conv_xyz789",
  "error": false,
  "error_message": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `score` | float | Verification score (0.0-1.0) |
| `rating` | string | Rating category (e.g., "excellent", "good", "needs_review") |
| `explanation` | string | Detailed explanation of verification results |
| `issues` | array | List of identified issues or discrepancies |
| `duration_ms` | integer | Verification processing time in milliseconds |
| `trace_id` | string | MLflow trace ID for debugging |
| `genie_conversation_id` | string | Genie conversation ID used for verification |
| `error` | boolean | Whether an error occurred |
| `error_message` | string | Error message if verification failed |

### Verification Process

1. Extracts slide content and numerical claims
2. Retrieves Genie conversation data used during generation
3. Uses MLflow's make_judge API to compare slide content with source data
4. Returns semantic similarity score and detailed analysis

Verification results are automatically saved by content hash, so they persist even when the deck is regenerated.

## Submit Feedback

Submit human feedback on a verification result. Feedback is logged to MLflow for model improvement.

**POST** `/api/verification/{slide_index}/feedback`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `slide_index` | integer | Yes | Slide index |

### Request Body

```json
{
  "session_id": "abc123",
  "is_positive": true,
  "rationale": "The verification correctly identified all accurate claims",
  "trace_id": "mlflow_trace_abc123"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |
| `is_positive` | boolean | Yes | Whether feedback is positive |
| `rationale` | string | No | Explanation of feedback |
| `trace_id` | string | No | MLflow trace ID to link feedback to |

### Response

```json
{
  "status": "success",
  "message": "Feedback submitted successfully",
  "linked_to_trace": true
}
```

## Get Genie Link

Get the Genie conversation URL for reviewing source data.

**GET** `/api/verification/genie-link`

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |

### Response

```json
{
  "has_genie_conversation": true,
  "url": "https://<workspace>/genie/conversations/xyz789",
  "genie_conversation_id": "genie_conv_xyz789"
}
```

If no Genie conversation exists:

```json
{
  "has_genie_conversation": false,
  "url": null,
  "genie_conversation_id": null
}
```

## Error Responses

### Session Not Found (404)

```json
{
  "detail": "Session not found: abc123"
}
```

### Slide Not Found (404)

```json
{
  "detail": "Slide index 5 out of range (0-9)"
}
```

### No Genie Data (400)

```json
{
  "detail": "No Genie conversation found for this session"
}
```

