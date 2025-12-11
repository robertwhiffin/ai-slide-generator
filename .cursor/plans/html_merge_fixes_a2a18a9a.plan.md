---
name: HTML Merge Fixes
overview: "Fix two confirmed bugs in slide editing: (1) CSS not being updated during edits, and (2) scripts being duplicated instead of replaced. Both issues stem from incomplete extraction and merging of LLM edit responses."
todos:
  - id: add-tinycss2
    content: Add tinycss2 dependency to requirements.txt
    status: pending
  - id: create-css-utils
    content: Create css_utils.py with parse_css_rules and merge_css functions
    status: pending
  - id: extract-css
    content: Add CSS extraction in _parse_slide_replacements
    status: pending
  - id: update-css-method
    content: Add update_css method to SlideDeck class
    status: pending
  - id: merge-css-in-service
    content: Call CSS merge in _apply_slide_replacements
    status: pending
  - id: script-fallback
    content: Add slide HTML canvas IDs as fallback for script correlation
    status: pending
  - id: add-tests
    content: Add unit tests for CSS and script merging
    status: pending
---

# HTML Merge Bug Fixes

## Project Context

**Application:** AI Slide Generator - A web application that uses LLMs (via Databricks) to generate and edit HTML slide presentations from natural language prompts.

**Tech Stack:**

- Backend: Python 3.11+, FastAPI, LangChain, BeautifulSoup
- Frontend: React/Vite/TypeScript
- Database: PostgreSQL (dev) / Lakebase (prod)

**Key Documentation:**

- `docs/technical/slide-parser-and-script-management.md` - HTML parsing architecture
- `docs/technical/backend-overview.md` - FastAPI/agent architecture
- `docs/technical/frontend-overview.md` - React state management

**Environment Setup:**

```bash
cd /path/to/ai-slide-generator
source .venv/bin/activate  # or: uv sync && source .venv/bin/activate
pytest tests/  # Run tests
uvicorn src.api.main:app --reload  # Start dev server on port 8000
```

---

## Architecture: Slide Edit Flow

When a user edits slides, the following flow occurs:

```
User selects slides + sends edit request
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ SlideGeneratorAgent.generate_slides()                        │
│   └─> LLM returns HTML with <div class="slide">, <style>,   │
│       and <script> blocks                                    │
│   └─> _parse_slide_replacements() extracts:                  │
│         • slide_divs (✓ working)                             │
│         • script_blocks (✓ working)                          │
│         • CSS (✗ NOT EXTRACTED - BUG 1)                      │
│   └─> Returns replacement_info dict                          │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ ChatService._apply_slide_replacements()                      │
│   └─> Removes old slides from deck                           │
│   └─> Inserts new slides                                     │
│   └─> Removes scripts for outgoing canvas IDs                │
│   └─> Adds replacement scripts (✗ FAILS when canvas ID       │
│       extraction fails - BUG 2)                              │
│   └─> CSS merge (✗ NOT IMPLEMENTED - BUG 1)                  │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
   SlideDeck.knit() → Final HTML returned to frontend
```

---

## Bug 1: CSS Not Updated During Edits

### Symptom

User asks LLM to change box color from red to blue. LLM correctly returns updated CSS, but the final deck retains the original red CSS.

### Evidence

- LLM response: `.stat-box { background: linear-gradient(135deg, #3C71AF...); }` (blue)
- Final deck: `.stat-box { background: linear-gradient(135deg, #EB4A34...); }` (still red)

### Root Cause

In `src/services/agent.py`, the `_parse_slide_replacements` method extracts slide divs and scripts but **completely ignores CSS**:

```python
# src/services/agent.py lines 433-435
soup = BeautifulSoup(llm_response, "html.parser")
slide_divs = soup.find_all("div", class_="slide")
script_blocks, script_canvas_ids = self._extract_script_blocks(soup)
# ❌ No CSS extraction here
```

The returned `replacement_info` dict (lines 465-478) has no CSS field:

```python
return {
    "replacement_slides": replacement_slides,
    "replacement_scripts": "\n".join(script_blocks) if script_blocks else "",
    "original_indices": original_indices,
    "start_index": start_index,
    "original_count": original_count,
    "replacement_count": replacement_count,
    "net_change": replacement_count - original_count,
    "success": True,
    "error": None,
    "operation": "edit",
    "canvas_ids": canvas_ids,
    "script_canvas_ids": script_canvas_ids,
    # ❌ No "replacement_css" field
}
```

---

## Bug 2: Scripts Duplicated Instead of Replaced

### Symptom

User asks to change chart color. The new script is appended alongside the old one instead of replacing it, causing duplicate Chart.js initialization and broken charts.

### Root Cause

The script replacement relies on canvas ID extraction to correlate scripts with canvases. When extraction fails, the script is appended as a new block instead of replacing the existing one.

**Failure path in `src/domain/slide_deck.py` lines 137-168:**

```python
def add_script_block(self, script_text: str, canvas_ids: List[str]) -> None:
    """Add (or replace) a script block for the provided canvas ids."""
    # ...
    if canvas_ids:
        self.remove_canvas_scripts(canvas_ids)  # ✓ Removes old if IDs found
    else:
        # Only matches if text is EXACTLY the same
        existing_key = next(
            (key for key, block in self.script_blocks.items()
             if block.text == cleaned and not block.canvas_ids),
            None,
        )
        if existing_key:
            self.script_blocks[existing_key].text = cleaned
            return
    
    # ❌ Falls through here if canvas_ids empty AND text changed
    # Creates NEW block instead of replacing
    key = self._generate_script_key(canvas_ids, len(self.script_blocks))
    block = ScriptBlock(key=key, text=cleaned, canvas_ids=set(canvas_ids))
    self.script_blocks[key] = block  # DUPLICATE!
```

**Why canvas ID extraction fails:**

The regex patterns in `src/utils/html_utils.py` may not match the LLM's script format:

```python
CANVAS_ID_PATTERN = re.compile(r"getElementById\s*\(\s*['\"]([\w\-.:]+)['\"]\s*\)")
QUERY_SELECTOR_PATTERN = re.compile(r"querySelector\s*\(\s*['\"]#([\w\-.:]+)['\"]\s*\)")
CANVAS_COMMENT_PATTERN = re.compile(r"//\s*Canvas:\s*([\w\-.:]+)", re.IGNORECASE)
```

If the LLM outputs a slightly different pattern, extraction returns empty list.

---

## Fix Implementation

### Step 1: Add tinycss2 Dependency

**File:** `requirements.txt`

**Action:** Add after `lxml==6.0.2`:

```
tinycss2==1.3.0
```

**Install:** `uv sync` or `pip install tinycss2==1.3.0`

---

### Step 2: Create CSS Utilities Module

**File:** `src/utils/css_utils.py` (NEW FILE)

```python
"""CSS parsing and merging utilities for slide deck editing."""
from __future__ import annotations

from typing import Dict

import tinycss2


def parse_css_rules(css_text: str) -> Dict[str, str]:
    """Parse CSS into a dict of {selector: declarations}.
    
    Args:
        css_text: Raw CSS string
        
    Returns:
        Dictionary mapping selectors to their declaration blocks
        
    Example:
        >>> parse_css_rules(".box { color: red; }")
        {'.box': 'color: red;'}
    """
    rules: Dict[str, str] = {}
    if not css_text:
        return rules
    
    try:
        parsed = tinycss2.parse_stylesheet(css_text, skip_whitespace=True)
        for rule in parsed:
            if rule.type == 'qualified-rule':
                selector = tinycss2.serialize(rule.prelude).strip()
                declarations = tinycss2.serialize(rule.content).strip()
                rules[selector] = declarations
    except Exception:
        # If parsing fails, return empty dict rather than crashing
        # The original CSS will be preserved
        pass
    
    return rules


def merge_css(existing_css: str, replacement_css: str) -> str:
    """Merge replacement CSS rules into existing CSS.
    
    Merge behavior:
 - Rules in replacement_css override matching selectors in existing_css
 - New selectors from replacement_css are appended
 - Existing selectors not in replacement_css are preserved
    
    Args:
        existing_css: Current deck CSS
        replacement_css: CSS from LLM edit response
        
    Returns:
        Merged CSS string
        
    Example:
        >>> existing = ".box { color: red; } .card { padding: 10px; }"
        >>> replacement = ".box { color: blue; }"
        >>> merge_css(existing, replacement)
        '.box { color: blue; }\n\n.card { padding: 10px; }'
    """
    existing_rules = parse_css_rules(existing_css)
    replacement_rules = parse_css_rules(replacement_css)
    
    if not replacement_rules:
        # Parsing failed or empty, return original unchanged
        return existing_css
    
    # Update existing with replacement (override matching, add new)
    existing_rules.update(replacement_rules)
    
    # Reconstruct CSS with consistent formatting
    css_parts = []
    for selector, declarations in existing_rules.items():
        css_parts.append(f"{selector} {{\n{declarations}\n}}")
    
    return '\n\n'.join(css_parts)
```

---

### Step 3: Add CSS Extraction to Agent

**File:** `src/services/agent.py`

**Action 1:** Add new method after `_extract_script_blocks` (around line 513):

```python
def _extract_css_from_response(self, soup: BeautifulSoup) -> str:
    """Extract CSS content from LLM response.
    
    Args:
        soup: BeautifulSoup parsed HTML
        
    Returns:
        Concatenated CSS from all <style> tags
    """
    css_parts = []
    for style_tag in soup.find_all('style'):
        if style_tag.string:
            css_parts.append(style_tag.string.strip())
    return '\n'.join(css_parts)
```

**Action 2:** Modify `_parse_slide_replacements` to extract and return CSS.

In the method (around line 435), add CSS extraction:

```python
# EXISTING (line 433-435):
soup = BeautifulSoup(llm_response, "html.parser")
slide_divs = soup.find_all("div", class_="slide")
script_blocks, script_canvas_ids = self._extract_script_blocks(soup)

# ADD after line 435:
replacement_css = self._extract_css_from_response(soup)
```

**Action 3:** Add `replacement_css` to the return dict (line 465-478):

```python
return {
    "replacement_slides": replacement_slides,
    "replacement_scripts": "\n".join(script_blocks) if script_blocks else "",
    "replacement_css": replacement_css,  # ← ADD THIS LINE
    "original_indices": original_indices,
    "start_index": start_index,
    "original_count": original_count,
    "replacement_count": replacement_count,
    "net_change": replacement_count - original_count,
    "success": True,
    "error": None,
    "operation": "edit",
    "canvas_ids": canvas_ids,
    "script_canvas_ids": script_canvas_ids,
}
```

---

### Step 4: Add update_css Method to SlideDeck

**File:** `src/domain/slide_deck.py`

**Action 1:** Add import at top of file (after line 12):

```python
from src.utils.css_utils import merge_css
```

**Action 2:** Add method after `add_script_block` (around line 169):

```python
def update_css(self, replacement_css: str) -> None:
    """Merge replacement CSS rules into deck CSS.
    
    Selectors in replacement_css override matching selectors in existing CSS.
    New selectors are appended. Existing selectors not in replacement are preserved.
    
    Args:
        replacement_css: CSS from edit response to merge
    """
    if not replacement_css or not replacement_css.strip():
        return
    self.css = merge_css(self.css, replacement_css)
```

---

### Step 5: Call CSS Merge in Chat Service

**File:** `src/api/services/chat_service.py`

**Action:** In `_apply_slide_replacements` method, add CSS merge after inserting replacement slides.

Insert after line 688 (after the "Inserted replacement slides" log statement):

```python
        logger.info(
            "Inserted replacement slides",
            extra={
                "replacement_count": len(replacement_slides),
                "net_change": len(replacement_slides) - original_count,
                "start_index": start_idx,
            },
        )

        # ─────────────────────────────────────────────────────────
        # ADD THIS BLOCK: Merge replacement CSS into deck
        # ─────────────────────────────────────────────────────────
        replacement_css = replacement_info.get("replacement_css", "")
        if replacement_css:
            current_deck.update_css(replacement_css)
            logger.info(
                "Merged replacement CSS",
                extra={"css_length": len(replacement_css)},
            )
        # ─────────────────────────────────────────────────────────

        replacement_script_canvas_ids = script_canvas_ids or extract_canvas_ids_from_script(
```

---

### Step 6: Fix Script Replacement Fallback

**File:** `src/api/services/chat_service.py`

**Action:** Modify the canvas ID fallback chain to use slide HTML canvas IDs.

Replace lines 690-692:

```python
# BEFORE:
replacement_script_canvas_ids = script_canvas_ids or extract_canvas_ids_from_script(
    replacement_scripts
)

# AFTER:
# Get canvas IDs from replacement SLIDES (authoritative source)
incoming_canvas_ids: list[str] = []
for slide_html in replacement_slides:
    incoming_canvas_ids.extend(extract_canvas_ids_from_html(slide_html))

# Fallback chain: script parsing → regex extraction → slide HTML
replacement_script_canvas_ids = (
    script_canvas_ids
    or extract_canvas_ids_from_script(replacement_scripts)
    or incoming_canvas_ids
)

logger.debug(
    "Script canvas ID resolution",
    extra={
        "from_script_parsing": script_canvas_ids,
        "from_regex": extract_canvas_ids_from_script(replacement_scripts) if not script_canvas_ids else None,
        "from_slide_html": incoming_canvas_ids if not script_canvas_ids else None,
        "resolved": replacement_script_canvas_ids,
    },
)
```

---

### Step 7: Add Unit Tests

**File:** `tests/unit/test_css_utils.py` (NEW FILE)

```python
"""Unit tests for CSS parsing and merging utilities."""
import pytest

from src.utils.css_utils import parse_css_rules, merge_css


class TestParseCssRules:
    """Tests for parse_css_rules function."""

    def test_parse_single_rule(self):
        """Parse a single CSS rule."""
        css = ".box { color: red; padding: 10px; }"
        result = parse_css_rules(css)
        
        assert ".box" in result
        assert "color: red" in result[".box"]

    def test_parse_multiple_rules(self):
        """Parse multiple CSS rules."""
        css = ".box { color: red; } .card { padding: 10px; }"
        result = parse_css_rules(css)
        
        assert len(result) == 2
        assert ".box" in result
        assert ".card" in result

    def test_parse_empty_css(self):
        """Empty CSS returns empty dict."""
        assert parse_css_rules("") == {}
        assert parse_css_rules(None) == {}

    def test_parse_invalid_css(self):
        """Invalid CSS returns empty dict without crashing."""
        result = parse_css_rules("not valid css {{{{")
        assert isinstance(result, dict)


class TestMergeCss:
    """Tests for merge_css function."""

    def test_override_existing_selector(self):
        """Replacement CSS overrides matching selectors."""
        existing = ".stat-box { background: red; }"
        replacement = ".stat-box { background: blue; }"
        
        result = merge_css(existing, replacement)
        
        assert "blue" in result
        assert "red" not in result

    def test_preserve_unmatched_selectors(self):
        """Selectors not in replacement are preserved."""
        existing = ".stat-box { background: red; } .card { padding: 10px; }"
        replacement = ".stat-box { background: blue; }"
        
        result = merge_css(existing, replacement)
        
        assert ".card" in result
        assert "padding" in result

    def test_add_new_selectors(self):
        """New selectors in replacement are added."""
        existing = ".box { color: red; }"
        replacement = ".new-class { margin: 5px; }"
        
        result = merge_css(existing, replacement)
        
        assert ".box" in result
        assert ".new-class" in result

    def test_empty_replacement_preserves_original(self):
        """Empty replacement returns original unchanged."""
        existing = ".box { color: red; }"
        
        result = merge_css(existing, "")
        
        assert result == existing


class TestCssMergeIntegration:
    """Integration tests for CSS merge in slide editing context."""

    def test_gradient_color_change(self):
        """Verify gradient backgrounds are correctly replaced."""
        existing = """.stat-box {
            background: linear-gradient(135deg, #EB4A34 0%, #d43d2a 100%);
            color: white;
        }"""
        replacement = """.stat-box {
            background: linear-gradient(135deg, #3C71AF 0%, #2d5a8f 100%);
            color: white;
        }"""
        
        result = merge_css(existing, replacement)
        
        assert "#3C71AF" in result
        assert "#EB4A34" not in result
```

---

## Validation Steps

After implementing all changes:

1. **Run unit tests:**
   ```bash
   pytest tests/unit/test_css_utils.py -v
   pytest tests/unit/test_slide_replacements.py -v
   ```

2. **Run full test suite:**
   ```bash
   pytest tests/ -v
   ```

3. **Manual testing:**

            - Start dev server: `uvicorn src.api.main:app --reload`
            - Open frontend at `http://localhost:5173`
            - Generate a slide deck with a colored box (e.g., stat card)
            - Select the slide and ask to change the color
            - Verify the color changes in the rendered slide
            - Check "Raw HTML" view to confirm CSS was updated
            - For charts: verify no duplicate Chart.js errors in browser console

4. **Check logs for new debug output:**
   ```bash
   tail -f logs/backend.log | grep -E "(Merged replacement CSS|Script canvas ID resolution)"
   ```


---

## Files Modified Summary

| File | Change Type | Description |

|------|-------------|-------------|

| `requirements.txt` | MODIFY | Add `tinycss2==1.3.0` |

| `src/utils/css_utils.py` | CREATE | CSS parsing and merge functions |

| `src/services/agent.py` | MODIFY | Add `_extract_css_from_response`, include CSS in replacement_info |

| `src/domain/slide_deck.py` | MODIFY | Add `update_css` method, import merge_css |

| `src/api/services/chat_service.py` | MODIFY | Call CSS merge, fix canvas ID fallback chain |

| `tests/unit/test_css_utils.py` | CREATE | Unit tests for CSS utilities |

---

## Rollback Plan

If issues arise:

1. The CSS merge uses graceful error handling - if `tinycss2` parsing fails, original CSS is preserved
2. The script fallback chain is additive - existing behavior preserved, new fallback added
3. To fully rollback: revert all modified files and remove `tinycss2` from requirements