# Export API

Endpoints for exporting slide decks to PowerPoint (PPTX) format.

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

