# Export Test Suite

**One-Line Summary:** Integration tests for PPTX export functionality covering sync and async export, chart image handling, error scenarios, and large deck support.

---

## 1. Overview

The export test suite validates the `/api/export` endpoints for converting slide decks to downloadable formats. The primary focus is PPTX (PowerPoint) export, with support for async export jobs and chart image injection.

### Test File

| File | Test Count | Purpose |
|------|------------|---------|
| `tests/integration/test_export.py` | ~27 | PPTX export, async jobs, error handling |

---

## 2. Export Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/export/pptx` | POST | Synchronous PPTX export |
| `/api/export/pptx/async` | POST | Start async export job |
| `/api/export/pptx/poll/{job_id}` | GET | Check job progress |
| `/api/export/pptx/download/{job_id}` | GET | Download completed export |

---

## 3. Test Categories

### 3.1 PPTX Export Tests

**Goal:** Validate synchronous PPTX export functionality.

```
tests/integration/test_export.py::TestPPTXExport
```

| Test | Scenario | Expected |
|------|----------|----------|
| `test_pptx_export_requires_session_id` | Missing session_id | 422 |
| `test_pptx_export_session_not_found` | Invalid session | 404 |
| `test_pptx_export_no_slides` | Empty deck | 404 |
| `test_pptx_export_success` | Valid request | 200 + PPTX file |
| `test_pptx_export_filename` | Valid request | Content-Disposition with .pptx |
| `test_pptx_export_with_chart_images` | With chart data | 200 |
| `test_pptx_export_conversion_error` | Converter fails | 500 |
| `test_pptx_content_is_valid_zip` | Valid request | Response is valid ZIP |

**Content-Type:** `application/vnd.openxmlformats-officedocument.presentationml.presentation`

**PPTX Format:** PPTX files are ZIP archives; tests validate this structure.

---

### 3.2 Chart Image Handling

**Goal:** Validate chart image injection for accurate chart rendering.

```
tests/integration/test_export.py::TestPPTXExport
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_pptx_export_with_chart_images` | Chart images provided | Images passed to converter |
| `test_pptx_export_with_use_screenshot_false` | use_screenshot=False | Flag respected |

**Request Format:**
```json
{
  "session_id": "test-123",
  "use_screenshot": true,
  "chart_images": [
    [{"canvas_id": "chart_0", "base64_data": "data:image/png;base64,..."}],
    []
  ]
}
```

**Chart Images Array:** One inner array per slide; each contains chart screenshots for that slide.

---

### 3.3 HTML Export Tests

**Goal:** Verify HTML export endpoint status.

```
tests/integration/test_export.py::TestHTMLExport
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_html_export_endpoint_existence` | Check endpoint | Skip if not implemented |

**Note:** HTML export may not be implemented; test gracefully skips.

---

### 3.4 PDF Export Tests

**Goal:** Verify PDF export endpoint status.

```
tests/integration/test_export.py::TestPDFExport
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_pdf_export_endpoint_existence` | Check endpoint | Skip if not implemented |

**Note:** PDF export may not be implemented; test gracefully skips.

---

### 3.5 Export Error Tests

**Goal:** Validate error handling during export.

```
tests/integration/test_export.py::TestExportErrors
```

| Test | Scenario | Expected |
|------|----------|----------|
| `test_export_with_invalid_session` | Session not found | 404 |
| `test_export_with_empty_deck` | No slides | 404 |
| `test_export_with_malformed_html` | Invalid HTML | 200, 400, or 500 |
| `test_export_general_exception` | Unexpected error | 500 |

**Error Response:**
```json
{
  "detail": "PPTX conversion failed: Font not found"
}
```

---

### 3.6 Large Deck Export Tests

**Goal:** Validate export handles large decks.

```
tests/integration/test_export.py::TestLargeDeckExport
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_export_large_deck` | 25 slides | Completes successfully |
| `test_export_deck_with_many_charts` | 10 slides with charts | Completes successfully |

**Performance:** Large deck tests verify no timeouts or memory issues.

---

### 3.7 Async Export Tests

**Goal:** Validate async export job workflow.

```
tests/integration/test_export.py::TestAsyncPPTXExport
```

| Test | Scenario | Expected |
|------|----------|----------|
| `test_async_export_requires_session_id` | Missing session_id | 422 |
| `test_async_export_session_not_found` | Invalid session | 404 |
| `test_async_export_no_slides` | Empty deck | 404 |
| `test_async_export_starts_job` | Valid request | 200 + job_id |
| `test_poll_export_job_not_found` | Invalid job_id | 404 |
| `test_poll_export_job_in_progress` | Running job | 200 + progress |
| `test_download_export_job_not_found` | Invalid job_id | 404 |
| `test_download_export_job_not_ready` | Incomplete job | 400 |

**Async Response:**
```json
{
  "job_id": "test-job-123",
  "status": "pending",
  "total_slides": 3
}
```

**Poll Response:**
```json
{
  "status": "running",
  "progress": 5,
  "total_slides": 10,
  "error": null
}
```

---

### 3.8 Build Slide HTML Tests

**Goal:** Validate HTML building helper function.

```
tests/integration/test_export.py::TestBuildSlideHTML
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_build_slide_html_basic` | Basic slide | Valid HTML document |
| `test_build_slide_html_with_external_scripts` | With CDN scripts | Scripts included |
| `test_build_slide_html_with_scripts` | With inline scripts | Scripts in output |
| `test_build_slide_html_preserves_slide_content` | Slide HTML | Content preserved |

**Function:** `src/api/routes/export.py::build_slide_html(slide, slide_deck)`

---

## 4. Test Infrastructure

### Mock PPTX Converter

Tests mock the PPTX converter to avoid Playwright dependencies:

```python
@pytest.fixture
def mock_pptx_converter():
    """Mock the PPTX converter."""
    with patch("src.api.routes.export.HtmlToPptxConverterV3") as mock_class:
        converter = MagicMock()
        converter.convert_slide_deck = AsyncMock()
        mock_class.return_value = converter
        yield converter
```

### Creating Valid PPTX for Tests

Tests that verify PPTX content use python-pptx to create real files:

```python
from pptx import Presentation

pptx_path = tmp_path / "test.pptx"
prs = Presentation()
prs.slides.add_slide(prs.slide_layouts[6])
prs.save(str(pptx_path))
```

---

## 5. Running the Tests

```bash
# Run all export tests
pytest tests/integration/test_export.py -v

# Run PPTX tests only
pytest tests/integration/test_export.py::TestPPTXExport -v

# Run async export tests
pytest tests/integration/test_export.py::TestAsyncPPTXExport -v

# Run with coverage
pytest tests/integration/test_export.py --cov=src/api/routes/export --cov-report=html
```

---

## 6. Key Invariants

These invariants must NEVER be violated:

1. **Session required:** All export endpoints require valid session_id
2. **Non-empty deck:** Export fails with 404 if no slides exist
3. **Valid PPTX:** Successful export returns valid ZIP (PPTX format)
4. **Chart preservation:** Chart images provided in request are used in output
5. **Async completeness:** Download only available after job completes

---

## 7. Cross-References

- [Export Features](./export-features.md) - Export implementation details
- [API Routes Tests](./api-routes-tests.md) - Other endpoint tests
- [Slide Parser and Script Management](./slide-parser-and-script-management.md) - HTML parsing
