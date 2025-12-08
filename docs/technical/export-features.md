# Export Features - PDF and PPTX

## Overview

The AI Slide Generator supports exporting slide decks in two formats:
- **PDF**: Client-side generation using browser APIs
- **PPTX**: Server-side generation using LLM-powered conversion

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
   - The export is processed on the server
   - Wait for the conversion to complete (may take 10-30 seconds depending on slide count)
   - A PPTX file will be downloaded automatically
   - Filename format: `{slide_deck_title}_{timestamp}.pptx`

### Export Status

- The export button shows "Exporting..." with a spinner while processing
- The dropdown menu closes automatically when an export starts
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

### PPTX Export (Server-Side)

**Location**: `src/services/html_to_pptx.py`

**Technology Stack**:
- `python-pptx`: Creates PowerPoint presentations
- `playwright`: Captures screenshots of HTML slides
- LLM (Databricks Claude Sonnet 4.5): Analyzes HTML and generates slide layouts

**Process**:
1. Backend receives export request with slide HTML
2. For each slide:
   - Optionally captures screenshot using Playwright (if `use_screenshot=True`)
   - LLM analyzes HTML structure and content
   - LLM generates Python code to create PowerPoint slide
   - Code is executed to add slide to presentation
3. Presentation is saved and returned as file download

**Features**:
- ✅ Native PowerPoint format (.pptx)
- ✅ Editable charts (extracted from Chart.js data)
- ✅ Professional layouts with proper spacing
- ✅ Preserves colors, fonts, and styling
- ✅ No overlapping elements
- ✅ Responsive to different slide layouts

**Configuration**:
```python
{
  use_screenshot: True  # Use Playwright screenshots for charts
}
```

**Limitations**:
- Requires server processing (10-30 seconds per slide)
- Requires LLM API access (Databricks endpoint)
- Requires Playwright installation for screenshots
- Async operation (not instant)

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
- `exportToPPTX()` method for server-side export
- Handles blob download
- Error handling and API communication

### Backend Components

**Export Route** (`src/api/routes/export.py`):
- `POST /api/export/pptx` endpoint
- Validates slide deck availability
- Builds HTML for each slide (includes scripts and styles)
- Calls `HtmlToPptxConverterV3` service
- Returns PPTX file as `FileResponse`

**PPTX Converter Service** (`src/services/html_to_pptx.py`):
- `HtmlToPptxConverterV3` class
- LLM-powered HTML to PPTX conversion
- Handles screenshot capture (Playwright)
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
- **With Screenshot**: Chart area is captured as PNG image and inserted into slide
- **Without Screenshot**: Chart data is extracted from JavaScript and converted to native PowerPoint charts using `CategoryChartData`
- Chart.js data extraction looks for:
  - `rawData` arrays
  - `datasets` arrays
  - `new Chart()` configurations
  - `labels` and `data` variables

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

**Problem**: Export takes too long
- **Solution**: PPTX export processes each slide sequentially with LLM calls. For many slides, this can take 10-30 seconds per slide. This is expected behavior.

**Problem**: Elements overlapping in PPTX
- **Solution**: The LLM prompts include strict positioning constraints. If overlaps occur, the prompts may need adjustment in `src/services/html_to_pptx.py`.

**Problem**: Charts not appearing in PPTX
- **Solution**: 
  - Ensure `use_screenshot=True` if you want chart images
  - Check that Chart.js data exists in the HTML if using data extraction
  - Verify Playwright is installed if using screenshots

**Problem**: "ModuleNotFoundError: No module named 'pptx'"
- **Solution**: Install dependencies: `pip install python-pptx playwright && playwright install`

## Best Practices

1. **For PDF Export**:
   - Use when you need quick, client-side export
   - Best for presentations with many slides (faster)
   - Good for sharing/viewing (universal format)

2. **For PPTX Export**:
   - Use when you need editable PowerPoint files
   - Best for presentations that need further editing
   - Good for professional presentations with native charts

3. **Chart Considerations**:
   - PDF: Charts are images (not editable)
   - PPTX: Charts can be editable if data extraction works, or images if using screenshots

## Future Enhancements

Potential improvements for export features:

- [ ] Batch export options (export multiple formats at once)
- [ ] Export progress indicator for PPTX (showing slide-by-slide progress)
- [ ] Custom export templates (different layouts/styles)
- [ ] Export preview before download
- [ ] Export scheduling/automation
- [ ] Compression options for PDF
- [ ] Export quality presets (high/medium/low)

## Related Documentation

- [Backend Overview](../technical/backend-overview.md) - Backend architecture
- [Frontend Overview](../technical/frontend-overview.md) - Frontend architecture
- [Slide Parser & Script Management](../technical/slide-parser-and-script-management.md) - How slides are structured
- [Export Implementation Guide](./export-pdf-pptx-implementation.md) - Detailed implementation plan

