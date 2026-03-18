# Settings API

Endpoints for managing session agent configuration, profiles, deck prompts, slide styles, and tool discovery.

## Agent Configuration

Session-bound agent configuration. Each session carries its own `agent_config` JSON that controls tools, slide style, deck prompt, and prompt overrides.

### Get Agent Config

**GET** `/api/sessions/{session_id}/agent-config`

Returns the agent configuration for a session.

**Response:**
```json
{
  "tools": [
    {"type": "genie", "space_id": "...", "space_name": "...", "description": "...", "conversation_id": "..."}
  ],
  "slide_style_id": 3,
  "deck_prompt_id": 7,
  "system_prompt": null,
  "slide_editing_instructions": null
}
```

### Update Agent Config

**PUT** `/api/sessions/{session_id}/agent-config`

Replace the full agent configuration for a session.

### Update Tools

**PATCH** `/api/sessions/{session_id}/agent-config/tools`

Add or remove tools from the session's agent configuration.

## Tool Discovery

### List Available Tools

**GET** `/api/tools/available`

Discover available Genie spaces and MCP servers that can be added to a session's tool list.

## Profiles

Profiles are named snapshots of agent configuration. Save a session's config as a profile, or load a profile into a session.

### List Profiles

**GET** `/api/profiles`

Returns a list of all saved profiles.

### Save Profile from Session

**POST** `/api/profiles/save-from-session/{session_id}`

Snapshot the current session's agent configuration as a named profile.

### Load Profile into Session

**POST** `/api/sessions/{session_id}/load-profile/{profile_id}`

Load a saved profile's agent configuration into a session, replacing the session's current config.

### Update Profile

**PUT** `/api/profiles/{profile_id}`

Update an existing profile.

### Delete Profile

**DELETE** `/api/profiles/{profile_id}`

Delete a profile.

## Deck Prompts

Deck prompts are templates that guide slide structure and content.

### List Deck Prompts

**GET** `/api/settings/deck-prompts`

List all deck prompts.

### Get Deck Prompt

**GET** `/api/settings/deck-prompts/{prompt_id}`

Get a specific deck prompt.

### Create Deck Prompt

**POST** `/api/settings/deck-prompts`

Create a new deck prompt.

### Update Deck Prompt

**PUT** `/api/settings/deck-prompts/{prompt_id}`

Update an existing deck prompt.

### Delete Deck Prompt

**DELETE** `/api/settings/deck-prompts/{prompt_id}`

Delete a deck prompt.

## Slide Styles

Slide styles define the visual appearance of generated slides.

### List Slide Styles

**GET** `/api/settings/slide-styles`

List all slide styles.

### Get Slide Style

**GET** `/api/settings/slide-styles/{style_id}`

Get a specific slide style.

### Create Slide Style

**POST** `/api/settings/slide-styles`

Create a new slide style.

### Update Slide Style

**PUT** `/api/settings/slide-styles/{style_id}`

Update an existing slide style.

### Delete Slide Style

**DELETE** `/api/settings/slide-styles/{style_id}`

Delete a slide style.

## Google Credentials

Manage Google OAuth client credentials for Google Slides export. Credentials are stored encrypted app-wide.

### Upload Google Credentials

**POST** `/api/admin/google-credentials`

Upload a `credentials.json` file obtained from Google Cloud Console. The file is validated, encrypted, and stored globally.

**Request:** `multipart/form-data` with `file` field containing `credentials.json`.

**Response:**
```json
{
  "success": true,
  "message": "Google credentials uploaded successfully"
}
```

### Get Google Credentials Status

**GET** `/api/admin/google-credentials/status`

Check whether credentials are configured.

**Response:**
```json
{
  "has_credentials": true
}
```

### Delete Google Credentials

**DELETE** `/api/admin/google-credentials`

Remove stored credentials. Returns 204 on success.

## Common Response Patterns

Most settings endpoints return detailed configuration objects. Error responses follow standard HTTP status codes:

- `200 OK` - Successful retrieval
- `201 Created` - Resource created
- `204 No Content` - Successful deletion
- `404 Not Found` - Resource not found
- `400 Bad Request` - Invalid configuration
- `500 Internal Server Error` - Server error
