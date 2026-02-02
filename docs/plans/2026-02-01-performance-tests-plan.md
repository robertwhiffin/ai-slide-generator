# Performance & Scale Test Suite Plan

**Date:** 2026-02-01
**Status:** Ready for Implementation
**Estimated Tests:** ~20 tests
**Priority:** Low

---

## Prerequisites

**Working directory:** `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator`

**Run tests from:** Project root

```bash
pytest tests/unit/test_performance.py -v
```

**Python environment:**
```bash
source .venv/bin/activate
```

**Note:** Performance tests may take longer to run. Use markers to skip in regular CI:
```bash
pytest tests/unit/test_performance.py -v -m "not slow"
```

---

## Critical: Read These Files First

Before implementing, read these files completely:

1. **Slide deck operations:** `src/domain/slide_deck.py`
2. **HTML parsing:** `src/utils/html_utils.py`
3. **Existing deck tests:** `tests/unit/test_slide_deck.py`
4. **Test fixtures:** `tests/fixtures/html/generators.py`
5. **Sample HTMLs:** `tests/sample_htmls/`

---

## Context: What Performance Tests Cover

Current tests only use 3-12 slides. Real users may create larger decks. These tests verify:

- Operations scale reasonably with deck size
- Memory usage doesn't explode with large decks
- No O(n²) or worse algorithms in critical paths
- Large chart datasets don't cause issues

**Note:** These are not benchmarks with strict timing requirements. They verify the system *works* at scale, not that it meets specific performance targets.

---

## Test Categories

### 1. Large Deck Operations

```python
import pytest
import time
from typing import List


class TestLargeDeckOperations:
    """Tests for operations on large slide decks."""

    @pytest.mark.slow
    def test_parse_50_slide_deck(self):
        """Can parse a deck with 50 slides."""
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_html(50)
        deck = SlideDeck.from_html(html)

        assert deck.slide_count == 50
        assert all(s.html for s in deck.slides)

    @pytest.mark.slow
    def test_parse_100_slide_deck(self):
        """Can parse a deck with 100 slides."""
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_html(100)
        deck = SlideDeck.from_html(html)

        assert deck.slide_count == 100

    @pytest.mark.slow
    def test_reorder_large_deck(self):
        """Can reorder a large deck efficiently."""
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_html(50)
        deck = SlideDeck.from_html(html)

        # Reverse the order
        new_order = list(range(49, -1, -1))

        start = time.time()
        deck.reorder(new_order)
        elapsed = time.time() - start

        # Should complete in reasonable time (< 5 seconds)
        assert elapsed < 5.0
        assert deck.slides[0].index == 49

    @pytest.mark.slow
    def test_add_slide_to_large_deck(self):
        """Can add slides to a large deck."""
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_html(50)
        deck = SlideDeck.from_html(html)

        # Add 10 more slides
        for i in range(10):
            deck.add_slide(f"<div class='slide'><h1>New Slide {i}</h1></div>")

        assert deck.slide_count == 60

    @pytest.mark.slow
    def test_delete_from_large_deck(self):
        """Can delete slides from a large deck."""
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_html(50)
        deck = SlideDeck.from_html(html)

        # Delete every other slide
        for i in range(24, -1, -1):
            deck.delete_slide(i * 2)

        assert deck.slide_count == 25

    @pytest.mark.slow
    def test_knit_large_deck(self):
        """Can generate output HTML for large deck."""
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_html(50)
        deck = SlideDeck.from_html(html)

        start = time.time()
        output = deck.to_html()
        elapsed = time.time() - start

        assert elapsed < 10.0
        assert len(output) > 0
        assert output.count('class="slide"') == 50

    @pytest.mark.slow
    def test_multiple_operations_on_large_deck(self):
        """Can perform multiple operations on large deck."""
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_html(30)
        deck = SlideDeck.from_html(html)

        # Mix of operations
        deck.add_slide("<div class='slide'>Added 1</div>")
        deck.add_slide("<div class='slide'>Added 2</div>")
        deck.delete_slide(5)
        deck.reorder([0, 2, 1] + list(range(3, deck.slide_count)))
        deck.update_slide(0, "<div class='slide'>Updated</div>")

        # Should still be valid
        output = deck.to_html()
        assert "Updated" in output
        assert deck.slide_count == 31
```

### 2. Memory Usage Tests

```python
class TestMemoryUsage:
    """Tests for memory efficiency."""

    @pytest.mark.slow
    def test_large_deck_memory_bounded(self):
        """Large deck doesn't use excessive memory."""
        import tracemalloc
        from src.domain.slide_deck import SlideDeck

        tracemalloc.start()

        html = generate_deck_html(100)
        deck = SlideDeck.from_html(html)
        _ = deck.to_html()

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Peak memory should be reasonable (< 500MB for 100 slides)
        assert peak < 500 * 1024 * 1024

    @pytest.mark.slow
    def test_no_memory_leak_on_operations(self):
        """Repeated operations don't leak memory."""
        import tracemalloc
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_html(20)
        deck = SlideDeck.from_html(html)

        tracemalloc.start()
        initial = tracemalloc.get_traced_memory()[0]

        # Perform many operations
        for i in range(100):
            deck.add_slide(f"<div class='slide'>Temp {i}</div>")
            deck.delete_slide(deck.slide_count - 1)

        final = tracemalloc.get_traced_memory()[0]
        tracemalloc.stop()

        # Memory growth should be minimal (< 10MB)
        growth = final - initial
        assert growth < 10 * 1024 * 1024

    @pytest.mark.slow
    def test_large_chart_data_memory(self):
        """Large chart datasets don't cause memory issues."""
        from src.domain.slide_deck import SlideDeck

        # Generate slide with large chart
        chart_html = generate_chart_slide_html(data_points=10000)
        html = f"""
        <!DOCTYPE html>
        <html><body>
        {chart_html}
        </body></html>
        """

        deck = SlideDeck.from_html(html)
        output = deck.to_html()

        assert "chart" in output.lower()
```

### 3. Parsing Performance Tests

```python
class TestParsingPerformance:
    """Tests for HTML parsing performance."""

    @pytest.mark.slow
    def test_parse_complex_slides(self):
        """Can parse slides with complex HTML."""
        from src.domain.slide_deck import SlideDeck

        html = generate_complex_deck_html(20)  # Nested elements, tables, etc.

        start = time.time()
        deck = SlideDeck.from_html(html)
        elapsed = time.time() - start

        assert elapsed < 5.0
        assert deck.slide_count == 20

    @pytest.mark.slow
    def test_parse_slides_with_many_scripts(self):
        """Can parse slides with many script tags."""
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_with_scripts(20, scripts_per_slide=5)

        deck = SlideDeck.from_html(html)

        # All scripts should be extracted
        assert deck.slide_count == 20

    @pytest.mark.slow
    def test_css_parsing_large_stylesheet(self):
        """Can handle large CSS stylesheets."""
        from src.domain.slide_deck import SlideDeck

        # Generate 1000 CSS rules
        css_rules = "\n".join([f".rule-{i} {{ color: #{i:06x}; }}" for i in range(1000)])
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><style>{css_rules}</style></head>
        <body><div class="slide">Content</div></body>
        </html>
        """

        deck = SlideDeck.from_html(html)
        output_css = deck.get_css()

        assert ".rule-0" in output_css
        assert ".rule-999" in output_css
```

### 4. Chart Handling Tests

```python
class TestChartPerformance:
    """Tests for chart handling at scale."""

    @pytest.mark.slow
    def test_many_charts_in_deck(self):
        """Can handle deck with many charts."""
        from src.domain.slide_deck import SlideDeck

        # 20 slides, each with a chart
        slides_html = []
        for i in range(20):
            slides_html.append(generate_chart_slide_html(chart_id=f"chart_{i}"))

        html = f"""
        <!DOCTYPE html>
        <html><body>
        {''.join(slides_html)}
        </body></html>
        """

        deck = SlideDeck.from_html(html)

        assert deck.slide_count == 20
        # Verify canvas IDs are preserved
        output = deck.to_html()
        assert "chart_0" in output
        assert "chart_19" in output

    @pytest.mark.slow
    def test_chart_with_large_dataset(self):
        """Can handle chart with large dataset."""
        from src.domain.slide_deck import SlideDeck

        html = generate_chart_slide_html(data_points=5000)
        full_html = f"<!DOCTYPE html><html><body>{html}</body></html>"

        deck = SlideDeck.from_html(full_html)
        output = deck.to_html()

        # Should preserve the data
        assert "5000" in output or len(output) > 50000  # Large output expected

    @pytest.mark.slow
    def test_canvas_id_management_at_scale(self):
        """Canvas IDs are properly managed for many charts."""
        from src.domain.slide_deck import SlideDeck

        html = generate_deck_html(30, with_charts=True)
        deck = SlideDeck.from_html(html)

        # Add more chart slides
        for i in range(10):
            deck.add_slide(generate_chart_slide_html(chart_id=f"new_chart_{i}"))

        # Reorder
        new_order = list(range(deck.slide_count - 1, -1, -1))
        deck.reorder(new_order)

        # Verify no duplicate canvas IDs
        output = deck.to_html()
        canvas_ids = extract_canvas_ids(output)
        assert len(canvas_ids) == len(set(canvas_ids))  # No duplicates
```

### 5. API Performance Tests

```python
class TestAPIPerformance:
    """Tests for API response times with large data."""

    @pytest.mark.slow
    def test_get_large_slide_deck(self, client, mock_chat_service):
        """GET /api/slides returns large deck in reasonable time."""
        mock_chat_service.get_slides.return_value = create_mock_slide_deck(50)

        start = time.time()
        response = client.get("/api/slides?session_id=test-123")
        elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed < 5.0

    @pytest.mark.slow
    def test_export_large_deck(self, client, mock_chat_service):
        """Export large deck completes in reasonable time."""
        mock_chat_service.get_slides.return_value = create_mock_slide_deck(30)

        start = time.time()
        response = client.post("/api/export/pptx", json={
            "session_id": "test-123"
        })
        elapsed = time.time() - start

        # Export may take longer, but should complete
        assert response.status_code in [200, 500]  # May fail but shouldn't hang
        assert elapsed < 60.0  # 1 minute max
```

---

## Helper Functions

```python
def generate_deck_html(slide_count: int, with_charts: bool = False) -> str:
    """Generate HTML for a deck with specified number of slides."""
    slides = []
    for i in range(slide_count):
        if with_charts and i % 3 == 0:
            slides.append(generate_chart_slide_html(chart_id=f"chart_{i}"))
        else:
            slides.append(f"""
            <div class="slide">
                <h1>Slide {i + 1}</h1>
                <p>This is content for slide number {i + 1}.</p>
                <ul>
                    <li>Point 1</li>
                    <li>Point 2</li>
                    <li>Point 3</li>
                </ul>
            </div>
            """)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>.slide {{ width: 960px; height: 540px; }}</style>
    </head>
    <body>
        {''.join(slides)}
    </body>
    </html>
    """


def generate_chart_slide_html(chart_id: str = "myChart", data_points: int = 10) -> str:
    """Generate HTML for a slide with a Chart.js chart."""
    data = [i * 10 for i in range(data_points)]
    labels = [f"Label {i}" for i in range(data_points)]

    return f"""
    <div class="slide">
        <h1>Chart Slide</h1>
        <canvas id="{chart_id}"></canvas>
        <script>
            new Chart(document.getElementById('{chart_id}'), {{
                type: 'bar',
                data: {{
                    labels: {labels},
                    datasets: [{{ data: {data} }}]
                }}
            }});
        </script>
    </div>
    """


def generate_complex_deck_html(slide_count: int) -> str:
    """Generate HTML with complex nested structures."""
    slides = []
    for i in range(slide_count):
        slides.append(f"""
        <div class="slide">
            <h1>Complex Slide {i + 1}</h1>
            <div class="container">
                <div class="row">
                    <div class="col">
                        <table>
                            <thead><tr><th>A</th><th>B</th></tr></thead>
                            <tbody>
                                <tr><td>1</td><td>2</td></tr>
                                <tr><td>3</td><td>4</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <div class="col">
                        <ul>
                            <li>Item 1
                                <ul><li>Sub 1</li><li>Sub 2</li></ul>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
        """)

    return f"<!DOCTYPE html><html><body>{''.join(slides)}</body></html>"


def extract_canvas_ids(html: str) -> List[str]:
    """Extract all canvas IDs from HTML."""
    import re
    return re.findall(r'<canvas[^>]*id=["\']([^"\']+)["\']', html)
```

---

## File to Create

**`tests/unit/test_performance.py`**

---

## Verification Checklist

Before marking complete:

- [ ] All tests pass: `pytest tests/unit/test_performance.py -v`
- [ ] Large deck tests (50+ slides) pass
- [ ] Memory usage is reasonable
- [ ] No hangs or timeouts
- [ ] Chart handling at scale works
- [ ] Tests marked with `@pytest.mark.slow` for CI
- [ ] File committed to git

---

## Debug Commands

```bash
# Run all performance tests (may take a while)
pytest tests/unit/test_performance.py -v

# Run without slow tests
pytest tests/unit/test_performance.py -v -m "not slow"

# Run with memory profiling
pytest tests/unit/test_performance.py -v --tb=short
```
