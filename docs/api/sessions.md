# Sessions API

Session management endpoints for creating, listing, and managing conversation sessions.

## Create Session

Create a new conversation session.

**POST** `/api/sessions`

### Request Body

```json
{
  "title": "Q3 Revenue Analysis",
  "profile_id": 1,
  "profile_name": "Production"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | No | Session title |
| `profile_id` | integer | No | Profile ID to associate this session with |
| `profile_name` | string | No | Profile name (cached for display in session history) |

`created_by` is automatically set to the authenticated user. `visibility` defaults to `'private'`. When `profile_id` is provided, the session is associated with that profile and appears in profile-filtered history views.

### Response

```json
{
  "session_id": "abc123",
  "title": "Q3 Revenue Analysis",
  "created_by": "user@example.com",
  "visibility": "private",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

## List Sessions

List sessions owned by the current user, optionally filtered by profile.

**GET** `/api/sessions`

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | No | Maximum sessions to return (1-100, default: 50) |
| `profile_id` | integer | No | Filter by profile ID (shows only sessions for that profile) |

Sessions are automatically scoped to the authenticated user (`created_by = current_user`). Legacy sessions (where `created_by` is `NULL`) are accessible to any authenticated user.

### Response

```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "title": "Q3 Revenue Analysis",
      "created_by": "user@example.com",
      "visibility": "private",
      "profile_id": 1,
      "profile_name": "Production",
      "created_at": "2024-01-15T10:30:00Z",
      "last_activity": "2024-01-15T11:00:00Z"
    }
  ],
  "count": 1
}
```

## Get Session

Get detailed information about a specific session.

**GET** `/api/sessions/{session_id}`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |

### Response

```json
{
  "session_id": "abc123",
  "title": "Q3 Revenue Analysis",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "message_count": 5
}
```

## Get Session Messages

Retrieve all messages in a session.

**GET** `/api/sessions/{session_id}/messages`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |

### Response

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Create a 10-slide presentation about Q3 revenue",
      "timestamp": "2024-01-15T10:30:00Z"
    },
    {
      "role": "assistant",
      "content": "I'll create a presentation about Q3 revenue...",
      "timestamp": "2024-01-15T10:30:05Z"
    }
  ]
}
```

## Get Session Slides

Get the slide deck for a session.

**GET** `/api/sessions/{session_id}/slides`

### Path Parameters

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
  }
}
```

## Update Session

Rename a session.

**PATCH** `/api/sessions/{session_id}`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `title` | string | Yes | New session title |

### Response

```json
{
  "session_id": "abc123",
  "title": "Updated Title",
  "updated_at": "2024-01-15T11:00:00Z"
}
```

## Delete Session

Delete a session and all associated data.

**DELETE** `/api/sessions/{session_id}`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |

### Response

`204 No Content`

## Cleanup Sessions

Delete multiple sessions at once.

**POST** `/api/sessions/cleanup`

### Request Body

```json
{
  "session_ids": ["abc123", "def456"]
}
```

### Response

```json
{
  "deleted": 2,
  "session_ids": ["abc123", "def456"]
}
```

## Export Session

Export a session's slide deck.

**POST** `/api/sessions/{session_id}/export`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |

### Response

Returns the exported file (PPTX or PDF) as a download.

