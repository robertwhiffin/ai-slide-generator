# Slides API

Endpoints for managing individual slides within a session's slide deck.

## Get Slides

Retrieve the current slide deck for a session.

**GET** `/api/slides`

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |

### Response

```json
{
  "session_id": "abc123",
  "slide_deck": {
    "slides": [
      {
        "slide_id": "slide_0",
        "html": "<div>...</div>"
      }
    ],
    "css": "...",
    "scripts": "..."
  },
  "slide_count": 10
}
```

## Reorder Slides

Change the order of slides in the deck.

**PUT** `/api/slides/reorder`

### Request Body

```json
{
  "session_id": "abc123",
  "new_order": [2, 0, 1, 3, 4]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |
| `new_order` | array | Yes | New order of slide indices (0-based) |

### Response

Returns the updated slide deck with slides in the new order.

## Update Slide

Update the HTML content of a specific slide.

**PATCH** `/api/slides/{index}`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `index` | integer | Yes | Slide index (0-based) |

### Request Body

```json
{
  "session_id": "abc123",
  "html": "<div>Updated slide content</div>"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |
| `html` | string | Yes | New HTML content for the slide |

### Response

Returns the updated slide object.

## Duplicate Slide

Create a copy of an existing slide.

**POST** `/api/slides/{index}/duplicate`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `index` | integer | Yes | Slide index to duplicate |

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

Returns the duplicated slide and updated slide deck.

## Delete Slide

Remove a slide from the deck.

**DELETE** `/api/slides/{index}`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `index` | integer | Yes | Slide index to delete |

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |

### Response

Returns the updated slide deck without the deleted slide.

## Update Slide Verification

Update or clear the verification result for a slide.

**PATCH** `/api/slides/{index}/verification`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `index` | integer | Yes | Slide index |

### Request Body

```json
{
  "session_id": "abc123",
  "verification": {
    "score": 0.95,
    "rating": "excellent",
    "explanation": "All data claims are accurate",
    "issues": []
  }
}
```

To clear verification, set `verification` to `null`:

```json
{
  "session_id": "abc123",
  "verification": null
}
```

### Response

Returns the updated slide deck with verification result persisted.

## Error Responses

### No Slides Available (404)

```json
{
  "detail": "No slides available"
}
```

### Session Busy (409)

```json
{
  "detail": "Session is currently processing another request. Please wait."
}
```

