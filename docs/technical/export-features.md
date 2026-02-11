# Export Features - PDF and PPTX

## Overview

The AI Slide Generator supports exporting slide decks in two formats:
- **PDF**: Client-side generation using browser APIs
- **PPTX**: Server-side async generation using LLM-powered conversion with polling

Both export options are accessible through a unified dropdown menu in the slide panel.

## User Guide

### How to Export

1. **Access Export Menu**
   - Click the blue "Export" button in the top-right of the slide panel
   - A dropdown menu will appear with two options:
     - "Export as PDF" (document icon)
     - "Export as PowerPoint" (file icon)

2. **Export as PDF**
   - Click "Export as PDF"
   - The export process runs entirely in your browser
   - A PDF file will be downloaded automatically
   - Filename format: `{slide_deck_title}_{timestamp}.pdf`

3. **Export as PowerPoint**
   - Click "Export as PowerPoint"
   - Charts are captured client-side before sending to server
   - The export runs asynchronously on the server with real-time progress updates
   - Progress displays "Processing slide X of Y..." during conversion
   - A PPTX file will be downloaded automatically when complete
   - Filename format: `{slide_deck_title}_{timestamp}.pptx`

### Export Status

- The export button shows "Exporting PowerPoint: Processing slide X of Y..." during PPTX export
- The dropdown menu closes automatically when an export starts
- Progress updates every 2 seconds via polling
- If an error occurs, an alert will display the error message

## Technical Details

### PDF Export (Client-Side)

**Location**: `frontend/src/services/pdf_client.ts`

**Technology Stack**:
- `html2canvas`: Converts HTML slides to canvas images
- `jsPDF`: Generates PDF from canvas images

**Process**:
1. Each slide is rendered in a hidden iframe (1280×720px)
2. Waits for Chart.js charts to fully render
3. Converts slide HTML to canvas using `html2canvas`
4. Adds canvas as image to PDF page (maintains 16:9 aspect ratio)
5. Repeats for all slides
6. Downloads the complete PDF

**Features**:
- ✅ No server load (runs entirely in browser)
- ✅ Fast processing
- ✅ Works offline
- ✅ Preserves Chart.js visualizations
- ✅ Optimized file size (JPEG compression, 1.2x scale)

**Configuration**:
```typescript
{
  format: 'a4',           // Page format
  orientation: 'landscape', // Page orientation
  scale: 1.2,              // Image scale (quality vs size)
  waitForCharts: 2000,     // Wait time for charts (ms)
  imageQuality: 0.85       // JPEG quality (0-1)
}
```

**Limitations**:
- File size can be large for many slides (typically 5-15MB per slide)
- Requires modern browser with canvas support
- Charts are rendered as images (not editable in PDF)

### PPTX Export (Server-Side Async)

**Location**: 
- `src/api/routes/export.py` - API endpoints
- `src/api/services/export_job_queue.py` - Background worker and job queue
- `src/services/html_to_pptx.py` - LLM-powered converter

**Technology Stack**:
- `python-pptx`: Creates PowerPoint presentations
- `asyncio`: Background job queue with thread pool execution
- LLM (Databricks Claude Sonnet 4.5): Analyzes HTML and generates slide layouts

**Process**:
1. Frontend captures Chart.js charts as base64 images client-side
2. Frontend calls `POST /api/export/pptx/async` to initiate export
3. Backend validates request and queues job, returns job ID immediately
4. Background worker (in thread pool) processes the export:
   - Fetches slide deck from database
   - Builds complete HTML for each slide
   - For each slide, LLM generates Python code to create PowerPoint slide
   - Code is executed to add slide to presentation
   - Progress is updated after each slide
5. Frontend polls `GET /api/export/pptx/poll/{job_id}` for status/progress
6. When complete, frontend downloads via `GET /api/export/pptx/download/{job_id}`

**Features**:
- ✅ Native PowerPoint format (.pptx)
- ✅ Async with polling (avoids proxy timeouts)
- ✅ Real-time progress updates (slide X of Y)
- ✅ Client-side chart capture for accurate chart images
- ✅ Professional layouts with proper spacing
- ✅ Preserves colors, fonts, and styling
- ✅ No overlapping elements
- ✅ Background worker runs in thread pool (non-blocking)

**Configuration**:
```python
{
  use_screenshot: True  # Include client-captured chart images
}
```

**Limitations**:
- Requires server processing (5-15 seconds per slide)
- Requires LLM API access (Databricks endpoint)
- Polling interval: 2 seconds
- Maximum poll attempts: 300 (10 minute timeout)

## Architecture

### Frontend Components

**Export Button & Dropdown** (`frontend/src/components/SlidePanel/SlidePanel.tsx`):
- Blue-themed export button with download icon
- Dropdown menu with blue accents matching app theme
- Loading states for both export types
- Error handling with user-friendly messages

**PDF Service** (`frontend/src/services/pdf_client.ts`):
- Handles iframe rendering and canvas conversion
- Manages Chart.js rendering wait times
- Optimizes image quality vs file size
- Handles edge cases (first slide, canvas sizing)

**API Client** (`frontend/src/services/api.ts`):
- `startPPTXExport()` - Initiates async export job
- `pollPPTXExport()` - Polls for job status and progress
- `downloadPPTX()` - Downloads completed PPTX file
- `exportToPPTX()` - Orchestrates the full async flow with progress callback
- Client-side chart capture before export

### Backend Components

**Export Route** (`src/api/routes/export.py`):
- `POST /api/export/pptx/async` - Initiates export job, returns job ID immediately
- `GET /api/export/pptx/poll/{job_id}` - Returns job status and progress
- `GET /api/export/pptx/download/{job_id}` - Serves completed PPTX file
- Validates slide deck availability before queuing

**Export Job Queue** (`src/api/services/export_job_queue.py`):
- Database-backed job tracking via `ExportJob` SQLAlchemy model
- `asyncio.Queue` for local worker dispatch within each process
- Background worker processes jobs in thread pool
- Thread pool execution prevents blocking event loop during LLM calls
- Progress tracking per job (slides completed / total) stored in DB
- Job cleanup after download (deletes DB row + temp file)
- Multi-worker safe: any process can read job status from the shared database

**PPTX Converter Service** (`src/services/html_to_pptx.py`):
- `HtmlToPptxConverterV3` class
- LLM-powered HTML to PPTX conversion
- Generates and executes Python code for slide creation
- Ensures proper positioning and no overlaps

## Positioning Constraints

The PPTX converter uses strict positioning constraints to prevent overlapping elements:

- **Slide dimensions**: 10" wide × 7.5" tall
- **Safe bounds**: left ≥ 0.5", top ≥ 0.5", left + width ≤ 9.5", top + height ≤ 7.0"
- **Title**: left=0.5-1.0", top=0.5-1.0", height=1.0-1.5", ends ≤ 2.0", font ≤ 44pt
- **Subtitle**: left=0.5-1.0", top ≥ 2.3" (0.3" gap), height=0.8-1.0", ends ≤ 3.5", font ≤ 28pt
- **Body**: top ≥ 4.0", left ≥ 0.5", ends ≤ 7.0", font ≤ 18pt
- **Text wrapping**: Enabled on all text frames
- **No overlaps**: Verified for all element pairs

## Chart Handling

### PDF Export
- Charts are rendered as images in the PDF
- Chart.js visualizations are captured via canvas
- Charts appear exactly as they do in the browser

### PPTX Export
- **Client-Side Capture**: Charts are captured as base64 PNG images in the browser before export
- The frontend identifies all `<canvas>` elements within chart containers
- Canvas images are sent to the server as part of the export request
- Chart images are inserted into PowerPoint slides at appropriate positions
- This approach ensures charts appear exactly as rendered in the browser

## File Naming

Both export formats use timestamped filenames:

- **PDF**: `{slide_deck_title}_{YYYY-MM-DDTHH-MM-SS}.pdf`
- **PPTX**: `{slide_deck_title}_{YYYY-MM-DD}.pptx`

If the slide deck has no title, "slides" is used as the default.

## Troubleshooting

### PDF Export Issues

**Problem**: White space in PDF
- **Solution**: This is usually resolved by the current implementation. If it persists, check that slides are exactly 1280×720px.

**Problem**: Charts not appearing
- **Solution**: The export waits for Chart.js to render. If charts still don't appear, check browser console for Chart.js errors.

**Problem**: Large file size
- **Solution**: File size is optimized with JPEG compression (quality 0.85) and 1.2x scale. For smaller files, reduce `imageQuality` or `scale` in the export options.

**Problem**: First slide content trimmed
- **Solution**: The implementation includes special handling for the first slide with additional wait time and canvas cropping logic.

### PPTX Export Issues

**Problem**: Export fails with "No slide deck available"
- **Solution**: Ensure you have generated slides before attempting export. The export requires an active slide deck.

**Problem**: Export times out (504 Gateway Timeout)
- **Solution**: The async polling architecture handles long exports. If timeouts still occur:
  - Check that the backend logs show "Export worker picked up job"
  - Verify the export_worker is running (check startup logs)
  - The 10-minute polling timeout may need extension for very large decks

**Problem**: Progress stuck at 0
- **Solution**: Check backend logs for errors in `process_export_job`. The worker may have encountered an error fetching slides or during LLM calls.

**Problem**: Elements overlapping in PPTX
- **Solution**: The LLM prompts include strict positioning constraints. If overlaps occur, the prompts may need adjustment in `src/services/html_to_pptx.py`.

**Problem**: Charts not appearing in PPTX
- **Solution**: 
  - Ensure charts are visible on screen before exporting (client-side capture requires rendered charts)
  - Check browser console for errors during chart capture
  - Verify the chart container has a valid `<canvas>` element

**Problem**: "ModuleNotFoundError: No module named 'pptx'"
- **Solution**: Install dependencies: `pip install python-pptx`

## Best Practices

1. **For PDF Export**:
   - Use when you need quick, client-side export
   - Best for presentations with many slides (faster)
   - Good for sharing/viewing (universal format)

2. **For PPTX Export**:
   - Use when you need editable PowerPoint files
   - Best for presentations that need further editing
   - Ensure charts are fully rendered before exporting (wait for animations to complete)
   - Keep the browser tab active during export for reliable chart capture

3. **Chart Considerations**:
   - PDF: Charts are images (not editable)
   - PPTX: Charts are captured as images from the browser, preserving exact appearance

## Future Enhancements

Potential improvements for export features:

- [ ] Batch export options (export multiple formats at once)
- [x] Export progress indicator for PPTX (showing slide-by-slide progress) - **Implemented**
- [ ] Custom export templates (different layouts/styles)
- [ ] Export preview before download
- [ ] Export scheduling/automation
- [ ] Compression options for PDF
- [ ] Export quality presets (high/medium/low)
- [x] Persistent job storage (survive server restarts) - **Implemented** (DB-backed ExportJob model)

## Related Documentation

- [Backend Overview](../technical/backend-overview.md) - Backend architecture
- [Frontend Overview](../technical/frontend-overview.md) - Frontend architecture
- [Slide Parser & Script Management](../technical/slide-parser-and-script-management.md) - How slides are structured

