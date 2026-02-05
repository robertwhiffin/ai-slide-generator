# Testing Strategy Design: Orchestration Layer Test Suite

**Date:** 2026-01-30
**Status:** Design
**Author:** Claude (with Robert Whiffin)

---

## Problem Statement

The current test suite has extensive mocking but doesn't validate the core value of the application: **HTML manipulation integrity**. Since this is an orchestration layer that calls external services (Genie, LLM), the tests should focus on ensuring that any HTML operation (add, delete, edit, reorder) produces valid, renderable output.

---

## Core Invariant

```
Original_Deck + Operation(add|delete|edit|reorder) = Valid_Renderable_Deck
```

**"Valid" means:**
- No duplicate canvas IDs
- No JavaScript syntax errors (validated via esprima)
- No malformed HTML structure
- App parses it correctly (SlideDeck.from_html_string succeeds)
- Browser renders without console errors

---

## Test Architecture

### Layer 1: Unit Tests (Fast, Mocked)

**Purpose:** Validate HTML parsing and manipulation logic in isolation.

| Test Area | What It Validates |
|-----------|-------------------|
| `test_slide_parsing.py` | SlideDeck.from_html_string works for various HTML structures |
| `test_slide_add.py` | Adding slides integrates without corruption |
| `test_slide_delete.py` | Deleting slides preserves remaining deck integrity |
| `test_slide_edit.py` | Edited slides (from mock LLM responses) integrate correctly |
| `test_slide_reorder.py` | Reordering preserves canvas/script associations |
| `test_css_variations.py` | Operations work across different CSS styles |
| `test_canvas_integrity.py` | No duplicate canvas IDs after any operation |
| `test_script_integrity.py` | JavaScript syntax valid after any operation |

**Fixtures:**
- 3 CSS variants (Databricks theme, Minimal theme, AI-generated)
- 4 deck sizes (3, 6, 9, 12 slides)
- Multiple slide types (title, content, chart, table, quote)

### Layer 2: Integration Tests (Database + API)

**Purpose:** Validate full request/response cycle with real database.

| Test Area | What It Validates |
|-----------|-------------------|
| `test_chat_api.py` | Chat endpoint handles mock LLM responses correctly |
| `test_slides_api.py` | CRUD operations maintain deck integrity |
| `test_session_persistence.py` | Deck state persists correctly across requests |

**Setup:**
- Real PostgreSQL test database (or SQLite for speed)
- Mocked Genie (returns CSV data)
- Mocked LLM (returns pre-captured HTML responses)

### Layer 3: E2E Tests (Playwright)

**Purpose:** Validate browser rendering and UI operations.

| Test Area | What It Validates |
|-----------|-------------------|
| `test_ui_delete.spec.ts` | Delete from UI doesn't corrupt deck |
| `test_ui_edit.spec.ts` | Manual HTML edits don't corrupt deck |
| `test_ui_reorder.spec.ts` | Drag-and-drop reorder works correctly |
| `test_rendering.spec.ts` | No browser console errors after operations |

**Validation:** After each operation, check browser console for errors.

### Layer 4: Live LLM Integration (Optional, On-Demand)

**Purpose:** Validate that real LLM responses can be parsed and integrated.

| Test Area | What It Validates |
|-----------|-------------------|
| `test_live_generation.spec.ts` | Real LLM output parses without error |
| `test_live_editing.spec.ts` | Real LLM edit responses integrate correctly |

**Note:** Not for quality evaluation - only for parsing/integration validation.

---

## Test Fixtures

### CSS Variants

#### 1. Databricks Theme (`databricks-theme.css`)
The production CSS provided by Robert - comprehensive brand styling with CSS variables, responsive layouts, card components.

#### 2. Minimal Theme (`minimal-theme.css`)
Stripped-down CSS focusing on structure without heavy styling:
- Basic slide dimensions (1280x720)
- Simple typography
- Minimal color palette
- Chart canvas sizing

#### 3. No Custom CSS (AI-Generated)
Test decks where the LLM generates its own inline styles. Validates that the system handles arbitrary CSS approaches.

### HTML Fixtures by Slide Type

| Slide Type | Contains | Complexity |
|------------|----------|------------|
| Title Slide | h1, subtitle, author | Low |
| Content Slide | h2, paragraphs, bullet lists | Medium |
| Two-Column | Grid layout, multiple content areas | Medium |
| Three-Card | Card components, grid | Medium |
| Chart Slide | Canvas element, Chart.js script | High |
| Table Slide | HTML table with data | Medium |
| Quote Slide | Blockquote, citation | Low |
| Mixed Slide | Chart + text + list | High |

### Deck Size Variations

- **3 slides:** Title + 2 content (minimal deck)
- **6 slides:** Title + section + 4 content (typical small deck)
- **9 slides:** Title + 2 sections + 6 content (medium deck)
- **12 slides:** Title + 3 sections + 8 content (large deck)

---

## Validation Functions

### 1. HTML Structure Validation

```python
def validate_html_structure(html: str) -> ValidationResult:
    """
    Validates:
    - HTML parses without error (BeautifulSoup)
    - Required elements present (.slide divs)
    - Proper nesting (no orphaned tags)
    """
```

### 2. Canvas ID Validation

```python
def validate_canvas_ids(deck: SlideDeck) -> ValidationResult:
    """
    Validates:
    - No duplicate canvas IDs across all slides
    - Every canvas has a corresponding script
    - Every script references an existing canvas
    """
```

### 3. JavaScript Syntax Validation

```python
def validate_javascript_syntax(scripts: str) -> ValidationResult:
    """
    Validates:
    - JavaScript parses without error (esprima)
    - No syntax errors (missing brackets, etc.)
    - Chart.js initialization patterns are correct
    """
```

### 4. CSS Validation

```python
def validate_css_syntax(css: str) -> ValidationResult:
    """
    Validates:
    - CSS parses without error (tinycss2)
    - No malformed rules
    - Required selectors present (.slide)
    """
```

### 5. Browser Render Validation (Playwright)

```typescript
async function validateBrowserRender(page: Page): Promise<ValidationResult> {
    // Capture console errors during render
    const errors: string[] = [];
    page.on('console', msg => {
        if (msg.type() === 'error') errors.push(msg.text());
    });

    // Wait for slides to render
    await page.waitForSelector('.slide');

    // Check for Chart.js errors
    // Check for duplicate ID warnings

    return { valid: errors.length === 0, errors };
}
```

---

## Operation Test Matrix

For each operation, test across all combinations:

| Operation | CSS Variants | Deck Sizes | Slide Types |
|-----------|--------------|------------|-------------|
| Add | 3 | 4 | 8 |
| Delete | 3 | 4 | 8 |
| Edit | 3 | 4 | 8 |
| Reorder | 3 | 4 | 8 |

**Total combinations per operation:** 3 × 4 × 8 = 96

**Practical approach:** Use parameterized tests with representative samples rather than full matrix.

---

## Mock Strategy

### Genie Mock

```python
class MockGenieClient:
    """Returns predefined CSV data for any query."""

    def query(self, space_id: str, query: str) -> str:
        # Return relevant CSV based on query keywords
        if "sales" in query.lower():
            return SALES_CSV_DATA
        elif "revenue" in query.lower():
            return REVENUE_CSV_DATA
        else:
            return GENERIC_CSV_DATA
```

### LLM Mock

```python
class MockLLMClient:
    """Returns predefined HTML responses."""

    def __init__(self, fixtures_dir: Path):
        self.fixtures = load_fixtures(fixtures_dir)

    def generate(self, prompt: str, context: dict) -> str:
        # Determine operation type from prompt
        if "recolor" in prompt.lower():
            return self.fixtures["edit_recolor"]
        elif "add" in prompt.lower():
            return self.fixtures["add_slide"]
        else:
            return self.fixtures["generate_deck"]
```

### Fixture Loading

```python
# fixtures/
#   html/
#     databricks-theme/
#       3-slides.html
#       6-slides.html
#       9-slides.html
#       12-slides.html
#     minimal-theme/
#       ...
#     ai-generated/
#       ...
#   edits/
#     recolor-chart.html
#     reword-content.html
#     add-slide.html
#   csv/
#     sales-data.csv
#     revenue-data.csv
```

---

## CI/CD Integration

### GitHub Actions Workflow

```yaml
name: Test Suite

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run unit tests
        run: pytest tests/unit -v --tb=short

  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_db
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run integration tests
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/test_db
        run: pytest tests/integration -v --tb=short

  e2e-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install frontend dependencies
        run: cd frontend && npm ci
      - name: Install Playwright
        run: cd frontend && npx playwright install --with-deps chromium
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install backend dependencies
        run: pip install -e ".[dev]"
      - name: Run E2E tests
        run: cd frontend && npm run test:e2e
```

### Test Commands

```bash
# Run all unit tests (fast)
pytest tests/unit -v

# Run integration tests (needs database)
pytest tests/integration -v

# Run specific test category
pytest tests/unit/test_canvas_integrity.py -v

# Run E2E tests
cd frontend && npx playwright test

# Run E2E with UI (for debugging)
cd frontend && npx playwright test --ui

# Run live LLM tests (on-demand, needs credentials)
cd frontend && npx playwright test tests/live/ --project=live-llm
```

---

## File Structure

```
tests/
├── conftest.py                 # Shared pytest fixtures
├── fixtures/
│   ├── __init__.py
│   ├── html/
│   │   ├── databricks-theme/
│   │   │   ├── 3-slides.html
│   │   │   ├── 6-slides.html
│   │   │   ├── 9-slides.html
│   │   │   └── 12-slides.html
│   │   ├── minimal-theme/
│   │   │   └── ...
│   │   └── ai-generated/
│   │       └── ...
│   ├── edits/
│   │   ├── recolor-chart-input.html
│   │   ├── recolor-chart-output.html
│   │   ├── reword-content-input.html
│   │   ├── reword-content-output.html
│   │   └── add-slide-output.html
│   └── csv/
│       ├── sales-data.csv
│       └── revenue-data.csv
├── unit/
│   ├── __init__.py
│   ├── test_slide_parsing.py
│   ├── test_slide_add.py
│   ├── test_slide_delete.py
│   ├── test_slide_edit.py
│   ├── test_slide_reorder.py
│   ├── test_css_variations.py
│   ├── test_canvas_integrity.py
│   └── test_script_integrity.py
├── integration/
│   ├── __init__.py
│   ├── test_chat_api.py
│   ├── test_slides_api.py
│   └── test_session_persistence.py
└── validation/
    ├── __init__.py
    ├── html_validator.py
    ├── canvas_validator.py
    ├── script_validator.py
    └── css_validator.py

frontend/tests/
├── fixtures/
│   └── mocks.ts               # Existing mock data
├── e2e/
│   ├── test_ui_delete.spec.ts
│   ├── test_ui_edit.spec.ts
│   ├── test_ui_reorder.spec.ts
│   └── test_rendering.spec.ts
└── live/
    ├── test_live_generation.spec.ts
    └── test_live_editing.spec.ts
```

---

## Implementation Order

### Phase 1: Validation Infrastructure
1. Create validation module (`tests/validation/`)
2. Implement HTML structure validator
3. Implement canvas ID validator
4. Implement JavaScript syntax validator
5. Implement CSS validator

### Phase 2: Test Fixtures
1. Create fixture directory structure
2. Generate Databricks theme HTML fixtures (3, 6, 9, 12 slides)
3. Generate Minimal theme HTML fixtures
4. Generate AI-generated style fixtures
5. Create edit operation fixtures (input/output pairs)
6. Create CSV mock data

### Phase 3: Unit Tests
1. Implement test_slide_parsing.py
2. Implement test_slide_add.py
3. Implement test_slide_delete.py
4. Implement test_slide_edit.py
5. Implement test_slide_reorder.py
6. Implement test_canvas_integrity.py
7. Implement test_script_integrity.py

### Phase 4: Integration Tests
1. Set up test database configuration
2. Implement test_chat_api.py with mock LLM
3. Implement test_slides_api.py
4. Implement test_session_persistence.py

### Phase 5: E2E Tests
1. Update Playwright configuration
2. Implement browser console error capture
3. Implement test_ui_delete.spec.ts
4. Implement test_ui_edit.spec.ts
5. Implement test_ui_reorder.spec.ts
6. Implement test_rendering.spec.ts

### Phase 6: CI/CD
1. Create GitHub Actions workflow
2. Configure test parallelization
3. Set up test reporting

### Phase 7: Live LLM Tests (Optional)
1. Create configurable LLM test runner
2. Implement test_live_generation.spec.ts
3. Implement test_live_editing.spec.ts

---

## Success Criteria

1. **Unit tests run in < 30 seconds**
2. **Integration tests run in < 2 minutes**
3. **E2E tests run in < 5 minutes**
4. **All operations (add/delete/edit/reorder) have validation coverage**
5. **Canvas integrity validated after every operation**
6. **No false positives** (tests don't fail on valid HTML)
7. **No false negatives** (tests catch actual corruption)
8. **CI/CD pipeline runs on every PR**

---

## Open Questions

1. Should we use SQLite for faster integration tests, or always require PostgreSQL for accuracy?
2. How many slide type combinations are sufficient for confidence?
3. Should live LLM tests run nightly or on-demand only?

---

## Appendix: CSS Fixtures

### Databricks Theme (provided)
See user input - comprehensive brand CSS with variables, responsive layouts, card components.

### Minimal Theme (to generate)
```css
/* Minimal theme focusing on structure */
.slide {
  width: 1280px;
  height: 720px;
  padding: 40px;
  font-family: system-ui, sans-serif;
  background: #fff;
}

.slide h1, .slide h2 { margin: 0 0 20px 0; }
.slide p { margin: 0 0 16px 0; line-height: 1.5; }
.slide ul { margin: 0; padding-left: 24px; }
.slide canvas { max-width: 100%; height: auto; }
```

### AI-Generated (no custom CSS)
Test with decks where the LLM generates inline styles or its own `<style>` block without user-provided CSS template.
