# Settings API

Endpoints for managing configuration profiles, deck prompts, slide styles, AI infrastructure, and Genie spaces.

## Profiles

Configuration profiles bundle together Genie spaces, slide styles, deck prompts, and LLM settings.

### List Profiles

**GET** `/api/settings/profiles`

Returns a list of all profiles.

### Get Default Profile

**GET** `/api/settings/profiles/default`

Returns the default profile configuration.

### Get Profile

**GET** `/api/settings/profiles/{profile_id}`

Get detailed configuration for a specific profile.

### Create Profile

**POST** `/api/settings/profiles`

Create a new profile with basic information.

### Create Profile with Config

**POST** `/api/settings/profiles/with-config`

Create a profile with all configuration in one request (wizard mode).

### Update Profile

**PUT** `/api/settings/profiles/{profile_id}`

Update an existing profile.

### Delete Profile

**DELETE** `/api/settings/profiles/{profile_id}`

Delete a profile.

### Set Default Profile

**POST** `/api/settings/profiles/{profile_id}/set-default`

Set a profile as the default.

### Duplicate Profile

**POST** `/api/settings/profiles/{profile_id}/duplicate`

Create a copy of an existing profile.

### Load Profile

**POST** `/api/settings/profiles/{profile_id}/load`

Hot-reload a profile configuration.

### Reload All Profiles

**POST** `/api/settings/profiles/reload`

Reload all profiles from the database.

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

## Prompts Configuration

Manage prompt configuration for profiles.

### Get Prompts Config

**GET** `/api/settings/prompts/{profile_id}`

Get prompt configuration for a profile.

### Update Prompts Config

**PUT** `/api/settings/prompts/{profile_id}`

Update prompt configuration (deck prompt and slide style selection).

## AI Infrastructure

Manage LLM endpoint and MLflow settings.

### Get AI Infrastructure Config

**GET** `/api/settings/ai-infra/{profile_id}`

Get AI infrastructure configuration for a profile.

### Update AI Infrastructure Config

**PUT** `/api/settings/ai-infra/{profile_id}`

Update AI infrastructure configuration.

### Validate AI Infrastructure

**POST** `/api/settings/ai-infra/validate`

Validate AI infrastructure settings.

### List Available Endpoints

**GET** `/api/settings/ai-infra/endpoints/available`

List available LLM endpoints in the workspace.

## Genie Spaces

Manage Genie space connections.

### List Available Genie Spaces

**GET** `/api/settings/genie/available`

List all available Genie spaces in the workspace.

### Get Genie Space

**GET** `/api/settings/genie/{profile_id}`

Get Genie space configuration for a profile.

### Create/Update Genie Space

**POST** `/api/settings/genie/{profile_id}`

Set Genie space for a profile.

### Update Genie Space

**PUT** `/api/settings/genie/space/{space_id}`

Update a Genie space configuration.

### Delete Genie Space

**DELETE** `/api/settings/genie/space/{space_id}`

Delete a Genie space configuration.

### Lookup Genie Space

**GET** `/api/settings/genie/lookup/{space_id}`

Get details about a specific Genie space.

### Validate Genie Space

**POST** `/api/settings/genie/validate`

Validate Genie space configuration.

## Common Response Patterns

Most settings endpoints return detailed configuration objects. Error responses follow standard HTTP status codes:

- `200 OK` - Successful retrieval
- `201 Created` - Resource created
- `204 No Content` - Successful deletion
- `404 Not Found` - Resource not found
- `400 Bad Request` - Invalid configuration
- `500 Internal Server Error` - Server error

