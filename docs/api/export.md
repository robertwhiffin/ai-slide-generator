# Export API

Endpoints for exporting slide decks to PowerPoint (PPTX) and Google Slides formats.

## Export PPTX (Synchronous)

Export a slide deck to PowerPoint format. This is a synchronous operation that may take time for large decks.

**POST** `/api/export/pptx`

### Request Body

```json
{
  "session_id": "abc123",
  "use_screenshot": true,
  "chart_images": [
    [
      {
        "canvas_id": "chart_0",
        "base64_data": "data:image/png;base64,..."
      }
    ]
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |
| `use_screenshot` | boolean | No | Whether to use screenshots for charts (default: true) |
| `chart_images` | array | No | Client-side captured chart images per slide |

### Response

Returns a PPTX file as a download with `Content-Type: application/vnd.openxmlformats-officedocument.presentationml.presentation`.

## Export PPTX (Async)

Submit an export job for async processing. Returns immediately with a job ID.

**POST** `/api/export/pptx/async`

### Request Body

Same as synchronous endpoint.

### Response

```json
{
  "job_id": "job_abc123",
  "status": "pending"
}
```

## Poll Export Job

Check the status of an async export job.

**GET** `/api/export/pptx/poll/{job_id}`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_id` | string | Yes | Job identifier from async submission |

### Response

```json
{
  "job_id": "job_abc123",
  "status": "completed",
  "file_path": "/tmp/export_abc123.pptx"
}
```

### Status Values

- `pending` - Job is queued
- `processing` - Export is in progress
- `completed` - Export completed successfully
- `failed` - Export failed with error

## Download Export

Download the completed export file.

**GET** `/api/export/pptx/download/{job_id}`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_id` | string | Yes | Job identifier |

### Response

Returns the PPTX file as a download if the job is completed, otherwise returns an error.

## Chart Image Capture

For best results, capture chart images client-side before exporting:

1. Render each slide with Chart.js
2. Capture canvas elements as base64 PNG images
3. Include in `chart_images` array (one array per slide)

This ensures charts are rendered correctly in the exported PowerPoint.

## Google Slides Export

Export a slide deck to a new Google Slides presentation. Requires Google OAuth credentials configured on the profile and the user to have completed the OAuth authorization flow.

### Check Auth Status

**GET** `/api/export/google-slides/auth/status?profile_id=1`

Returns whether the current user is authorized for the given profile.

```json
{
  "authorized": true
}
```

### Get Auth URL

**GET** `/api/export/google-slides/auth/url?profile_id=1`

Returns the Google OAuth consent URL. The frontend opens this in a popup window.

```json
{
  "url": "https://accounts.google.com/o/oauth2/auth?..."
}
```

### OAuth Callback

**GET** `/api/export/google-slides/auth/callback?code=AUTH_CODE&profile_id=1`

Handles the OAuth redirect. Exchanges the authorization code for tokens, encrypts, and stores them. Returns an HTML page that notifies the opener window and closes itself.

### Export to Google Slides

**POST** `/api/export/google-slides`

```json
{
  "session_id": "abc123",
  "profile_id": 1,
  "chart_images": [
    [{"canvas_id": "chart_0", "base64_data": "data:image/png;base64,..."}]
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |
| `profile_id` | integer | Yes | Profile with Google credentials |
| `chart_images` | array | No | Client-side captured chart images per slide |

**Response:**
```json
{
  "presentation_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUii7Vhkl2W5t_XlJM1Q",
  "presentation_url": "https://docs.google.com/presentation/d/1Bxi.../edit"
}
```

**Error Responses:**
- `400` — No credentials configured for profile
- `401` — User not authorized (OAuth flow incomplete)
- `404` — No slides available
- `500` — Conversion or API failure

For full details on the OAuth2 flow and credential management, see [Google Slides Integration](../technical/google-slides-integration.md).

## Error Responses

### Session Not Found (404)

```json
{
  "detail": "Session not found: abc123"
}
```

### Export Failed (500)

```json
{
  "detail": "Failed to export PPTX: <error details>"
}
```

