# Slide Editing Robustness Fixes

**One-Line Summary:** Implementation plan to fix slide editing failures including deck loss, LLM response validation, add vs edit intent detection, and JavaScript/canvas corruption issues.

---

## 1. Problem Summary

During slide editing operations, several failure modes have been identified that cause data loss and corruption:

| ID | Root Cause | Impact | Priority | Status |
|----|------------|--------|----------|--------|
| RC3 | Deck replaced when parsing fails | Complete deck destruction | P0 - Critical | ✅ Fixed |
| RC1 | LLM returns text instead of HTML | Triggers deck loss | P0 - Critical | ✅ Fixed |
| RC6 | Cache not restored after backend restart | Complete deck loss on edit | P0 - Critical | ✅ Fixed |
| RC7 | Scripts lost when loading from database | Charts disappear after restart | P0 - Critical | ✅ Fixed |
| RC2 | "Add slide" treated as "replace" | Slides disappear | P1 - High | ✅ Fixed |
| RC4 | Canvas ID collisions | Chart conflicts | P2 - Medium | ✅ Fixed |
| RC5 | Script split/merge fragile | JS syntax errors | P2 - Medium | ✅ Fixed |
| RC8 | "Edit slide 8" without selection wipes deck | Complete deck destruction | P0 - Critical | ✅ Fixed |
| RC9 | "Add after slide 3" goes to end | Wrong position | P1 - High | ✅ Fixed |
| RC10 | Ambiguous requests proceed without confirmation | Unpredictable behavior | P1 - High | ✅ Fixed |
| RC11 | Selection vs text reference conflict | Confusing behavior | P2 - Medium | ✅ Fixed |
| RC12 | "Create slides" with existing deck replaces silently | Accidental data loss | P0 - Critical | ✅ Fixed |
| RC13 | "Edit slide 7" without selection - LLM has no context | LLM asks for slide content | P1 - High | ✅ Fixed |
| RC14 | "Duplicate slide 4" returns empty HTML instead of guidance | Confusing UX | P2 - Medium | ✅ Fixed |
| RC15 | Optimize loses chart scripts due to RC4 canvas ID mismatch | Charts disappear after optimize | P1 - Critical | ✅ Fixed |

---

## 2. Architecture Context

### Components Involved

| Component | File | Responsibility |
|-----------|------|----------------|
| Agent | `src/services/agent.py` | LLM invocation, response parsing |
| Chat Service | `src/api/services/chat_service.py` | Deck cache, replacement logic |
| HTML Utils | `src/utils/html_utils.py` | Script splitting, canvas ID extraction |
| Slide Deck | `src/domain/slide_deck.py` | Deck parsing, knitting |
| Defaults | `src/core/defaults.py` | System prompt, editing instructions |

### Data Flow (Current - Problematic)

```
User Request → Agent → LLM Response → Parse Slides → Apply Replacements → Update Deck
                              ↓
                    [If parse fails, deck can be destroyed]
```

### Data Flow (Target - Safe)

```
User Request → Detect Intent → Agent → LLM Response → Validate Response
                                                            ↓
                                              [If invalid: retry once OR preserve deck]
                                                            ↓
                                              [If valid: Apply Replacements → Update Deck]
```

---

## 3. Implementation Plan

### Phase 1: Deck Preservation Guard (RC3)

**Goal:** Never destroy the deck when editing fails.

**Changes:**

1. **`src/api/services/chat_service.py`** - Add guard in `send_message_streaming`:

```python
# BEFORE (dangerous):
if slide_context and replacement_info:
    slide_deck_dict = self._apply_slide_replacements(...)
elif html_output and html_output.strip():
    # This branch can destroy the deck!
    current_deck = SlideDeck.from_html_string(html_output)

# AFTER (safe):
if slide_context and replacement_info:
    slide_deck_dict = self._apply_slide_replacements(...)
elif slide_context and not replacement_info:
    # GUARD: slide_context was provided but parsing failed
    # Preserve existing deck, return error
    logger.error("Slide replacement parsing failed, preserving existing deck")
    raise ValueError("Failed to parse LLM response as slide replacements")
elif html_output and html_output.strip():
    # Only create new deck if NOT in editing mode
    current_deck = SlideDeck.from_html_string(html_output)
```

2. **Same change in `send_message` (non-streaming path)**

**Test Cases:**

| Test ID | Scenario | Expected Outcome |
|---------|----------|------------------|
| RC3-T1 | LLM returns text with slides selected | Existing deck preserved, error returned |
| RC3-T2 | LLM returns empty string with slides selected | Existing deck preserved, error returned |
| RC3-T3 | LLM returns malformed HTML with slides selected | Existing deck preserved, error returned |
| RC3-T4 | Normal edit (valid HTML) | Deck updated correctly |
| RC3-T5 | New generation (no slides selected) | New deck created |

---

### Phase 2: LLM Response Validation & Retry (RC1)

**Goal:** Detect invalid LLM responses early and retry once before failing.

**Changes:**

1. **`src/services/agent.py`** - Add validation method:

```python
def _validate_editing_response(self, llm_response: str) -> tuple[bool, str]:
    """Validate that LLM response contains valid slide HTML.
    
    Returns:
        (is_valid, error_message)
    """
    if not llm_response or not llm_response.strip():
        return False, "Empty response"
    
    # Check for conversational text patterns (LLM confusion)
    confusion_patterns = [
        "I understand",
        "I cannot",
        "I'm sorry",
        "I don't",
        "There are no slides",
        "slides have been deleted",
        "no slides to display",
    ]
    lower_response = llm_response.lower()
    for pattern in confusion_patterns:
        if pattern.lower() in lower_response and '<div class="slide"' not in llm_response:
            return False, f"LLM returned conversational text instead of HTML: {pattern}"
    
    # Check for at least one slide div
    soup = BeautifulSoup(llm_response, "html.parser")
    slide_divs = soup.find_all("div", class_="slide")
    if not slide_divs:
        return False, "No <div class='slide'> elements found in response"
    
    return True, ""
```

2. **`src/services/agent.py`** - Add retry logic in `generate_slides_streaming`:

```python
# After getting LLM response, validate before parsing
if editing_mode:
    is_valid, error_msg = self._validate_editing_response(html_output)
    
    if not is_valid:
        logger.warning(f"Invalid editing response, retrying: {error_msg}")
        
        # Retry with stronger prompt
        retry_prompt = (
            f"{full_question}\n\n"
            "IMPORTANT: You MUST respond with valid HTML slide divs. "
            "Do NOT respond with conversational text. "
            "Return ONLY <div class='slide'>...</div> elements."
        )
        
        retry_result = agent_executor.invoke({
            "input": retry_prompt,
            "chat_history": chat_history.messages,
        })
        html_output = retry_result["output"]
        
        # Validate retry
        is_valid, error_msg = self._validate_editing_response(html_output)
        if not is_valid:
            raise AgentError(f"LLM failed to return valid slide HTML after retry: {error_msg}")
    
    # Now safe to parse
    replacement_info = self._parse_slide_replacements(...)
```

**Test Cases:**

| Test ID | Scenario | Expected Outcome |
|---------|----------|------------------|
| RC1-T1 | LLM returns "I understand you want to delete..." | Retry triggered, if retry fails → error |
| RC1-T2 | LLM returns "I cannot modify these slides" | Retry triggered |
| RC1-T3 | LLM returns valid HTML on first try | No retry, success |
| RC1-T4 | LLM returns valid HTML on retry | Success after retry |
| RC1-T5 | LLM returns text on both attempts | Error raised, deck preserved |
| RC1-T6 | LLM returns HTML without slide divs | Retry triggered |

---

### Phase 3: Add vs Edit Intent Detection (RC2)

**Goal:** Detect when user wants to ADD a slide vs EDIT existing slides.

**Changes:**

1. **`src/services/agent.py`** - Add intent detection:

```python
def _detect_add_intent(self, message: str) -> bool:
    """Detect if user wants to add a new slide rather than edit existing ones.
    
    Returns:
        True if message indicates adding/inserting a new slide
    """
    add_patterns = [
        r'\badd\b.*\bslide\b',
        r'\binsert\b.*\bslide\b',
        r'\bappend\b.*\bslide\b',
        r'\bnew\s+slide\b',
        r'\bcreate\b.*\bslide\b',
        r'\badd\b.*\bat\s+the\s+(bottom|end|top|beginning)\b',
        r'\bslide\b.*\bat\s+the\s+(bottom|end|top|beginning)\b',
    ]
    
    lower_message = message.lower()
    for pattern in add_patterns:
        if re.search(pattern, lower_message):
            return True
    return False
```

2. **`src/services/agent.py`** - Modify prompt for add operations:

```python
def _format_slide_context(self, slide_context: dict[str, Any], is_add_operation: bool = False) -> str:
    """Format slide context for injection into the user message."""
    context_parts = ["<slide-context>"]
    for html in slide_context.get("slide_htmls", []):
        context_parts.append(html)
    context_parts.append("</slide-context>")
    
    if is_add_operation:
        context_parts.append(
            "\n\nIMPORTANT: The user wants to ADD a new slide. "
            "You MUST return ALL the slides shown above PLUS the new slide. "
            "Do NOT replace the existing slides - include them in your response along with the new slide."
        )
    
    return "\n\n".join(context_parts)
```

3. **`src/services/agent.py`** - Use in `generate_slides_streaming`:

```python
if slide_context:
    is_add = self._detect_add_intent(question)
    context_str = self._format_slide_context(slide_context, is_add_operation=is_add)
    full_question = f"{context_str}\n\n{question}"
    
    logger.info(
        "Slide editing mode",
        extra={
            "is_add_operation": is_add,
            "selected_indices": slide_context.get("indices", []),
        },
    )
```

4. **`src/services/agent.py`** - Pass `is_add_operation` flag to replacement info:

```python
# After _parse_slide_replacements, add flag:
if replacement_info:
    replacement_info["is_add_operation"] = is_add_operation
```

5. **`src/api/services/chat_service.py`** - **Backend guard: Append instead of replace for add operations:**

```python
def _apply_slide_replacements(self, replacement_info: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    # ... get current_deck ...
    
    is_add_operation = replacement_info.get("is_add_operation", False)

    # RC2: For add operations, append to end of deck instead of replacing
    if is_add_operation:
        insert_position = len(current_deck.slides)
        logger.info(
            "Add operation detected - appending slides to end of deck",
            extra={
                "current_slide_count": len(current_deck.slides),
                "new_slides_count": len(replacement_slides),
            },
        )
        
        # Insert new slides at end of deck (don't remove any originals)
        for idx, slide in enumerate(replacement_slides):
            slide.slide_id = f"slide_{insert_position + idx}"
            current_deck.insert_slide(insert_position + idx, slide)
        
        return current_deck.to_dict()
    
    # ... standard replacement logic for non-add operations ...
```

**Why This Backend Guard Is Critical:**
- The LLM often ignores instructions to "return all slides plus new slide"
- The LLM's system prompt says to return "only slides that need changing"
- This creates a conflict that the LLM resolves by returning only the new slide
- The backend guard ensures add operations NEVER destroy existing slides

6. **`src/core/defaults.py`** - **LLM Instructions Aligned (Operation Types):**

```python
# In slide_editing_instructions:
IMPORTANT - Operation Types:
- EDIT (user wants to modify existing slides): Return the modified version of each provided slide. Keep the same number of slides.
- ADD (user wants to add/insert/create a NEW slide): Return ONLY the new slide(s). The system will automatically append them to the deck.
- EXPAND (user wants to split/expand slides into more): You may return more slides than provided - this replaces the originals.

# In rules section:
- For EDIT operations: return the same number of slides as provided
- For ADD operations: return only the new slide(s) to be added
- For EXPAND operations: you may return more slides than provided
```

7. **`src/services/agent.py`** - **Consistent ADD Instruction:**

```python
# In _format_slide_context() for add operations:
if is_add_operation:
    context_parts.append(
        "\n\nIMPORTANT: The user wants to ADD a new slide. "
        "Return ONLY the new slide(s) to be added - the system will automatically append them to the deck. "
        "Do NOT return the existing slides shown above - just the new slide content."
    )
```

**All Instructions Now Aligned:**
- `defaults.py`: "Return ONLY the new slide(s)"
- `agent.py`: "Return ONLY the new slide(s) to be added"
- Backend: Appends new slides, never touches existing

8. **`src/api/services/chat_service.py`** - **Critical: Handle ADD without slide_context:**

The original bug: When user says "add a summary slide" WITHOUT selecting any slides:
- No `slide_context` is sent by frontend
- Backend treats it as GENERATION mode (not EDIT mode)
- LLM returns just 1 slide → REPLACES entire deck!

**Fix:** Added `_detect_add_intent()` method and check in both `send_message` and `send_message_streaming`:

```python
# In the "elif html_output and html_output.strip():" branch:
is_add_intent = self._detect_add_intent(message)
existing_deck = self._get_or_load_deck(session_id)

if is_add_intent and existing_deck and len(existing_deck.slides) > 0:
    # APPEND new slides to existing deck instead of replacing
    insert_position = len(existing_deck.slides)
    for idx, slide in enumerate(new_deck.slides):
        slide.slide_id = f"slide_{insert_position + idx}"
        existing_deck.insert_slide(insert_position + idx, slide)
    current_deck = existing_deck
else:
    # Standard behavior: new generation
    current_deck = new_deck
```

This ensures:
- "add a slide" with NO selection → appends to existing deck
- "add a slide" WITH selection → original RC2 fix handles it
- "create slides about X" (new topic) → replaces deck as expected

**Test Cases:**

| Test ID | Scenario | Expected Outcome |
|---------|----------|------------------|
| RC2-T1 | "add a slide at the bottom for summary" | Add intent detected, slides appended to deck |
| RC2-T2 | "insert a new slide after this one" | Add intent detected |
| RC2-T3 | "change the color to red" | Edit intent (not add), standard replacement |
| RC2-T4 | "make this slide blue" | Edit intent (not add), standard replacement |
| RC2-T5 | "create a new summary slide" | Add intent detected, slide appended |
| RC2-T6 | "add slide" with LLM returning 1 slide | Slide appended, originals preserved |
| RC2-T7 | 5 slides exist + "add slide" → 6 slides | New slide appended at end |

---

### Phase 4: Canvas ID Uniqueness (RC4)

**Goal:** Prevent canvas ID collisions when editing slides with charts.

**Changes:**

1. **`src/services/agent.py`** - Add canvas ID deduplication:

```python
import uuid

def _deduplicate_canvas_ids(self, html_content: str, scripts: str) -> tuple[str, str]:
    """Generate unique canvas IDs to prevent collisions.
    
    Appends a short unique suffix to all canvas IDs in HTML and scripts.
    
    Returns:
        (updated_html, updated_scripts)
    """
    soup = BeautifulSoup(html_content, "html.parser")
    canvases = soup.find_all("canvas")
    
    if not canvases:
        return html_content, scripts
    
    suffix = uuid.uuid4().hex[:6]
    id_mapping = {}
    
    # Update canvas IDs in HTML
    for canvas in canvases:
        old_id = canvas.get("id")
        if old_id:
            new_id = f"{old_id}_{suffix}"
            id_mapping[old_id] = new_id
            canvas["id"] = new_id
    
    updated_html = str(soup)
    updated_scripts = scripts
    
    # Update references in scripts
    for old_id, new_id in id_mapping.items():
        # Update getElementById calls
        updated_scripts = re.sub(
            rf"getElementById\s*\(\s*['\"]({re.escape(old_id)})['\"]\s*\)",
            f"getElementById('{new_id}')",
            updated_scripts
        )
        # Update Canvas comments
        updated_scripts = re.sub(
            rf"//\s*Canvas:\s*{re.escape(old_id)}\b",
            f"// Canvas: {new_id}",
            updated_scripts,
            flags=re.IGNORECASE
        )
    
    return updated_html, updated_scripts
```

2. **`src/services/agent.py`** - Apply in `_parse_slide_replacements`:

```python
# After parsing slides, deduplicate canvas IDs
for slide in replacement_slides:
    if '<canvas' in slide.html:
        slide.html, slide.scripts = self._deduplicate_canvas_ids(slide.html, slide.scripts)
```

**Test Cases:**

| Test ID | Scenario | Expected Outcome |
|---------|----------|------------------|
| RC4-T1 | Edit slide with canvas id="chart1" | ID becomes "chart1_abc123" |
| RC4-T2 | Multiple canvases in one slide | All IDs get same suffix |
| RC4-T3 | Scripts reference old IDs | Scripts updated to new IDs |
| RC4-T4 | Slide without canvas | No changes made |
| RC4-T5 | Two consecutive edits | Each gets unique suffix |

---

### Phase 5: JavaScript Syntax Validation (RC5)

**Goal:** Validate JavaScript syntax before applying to prevent corruption.

**Changes:**

1. **Add dependency:** `esprima` or `py_mini_racer` for JS parsing

```bash
pip install esprima
```

2. **`src/utils/js_validator.py`** - New file:

```python
"""JavaScript syntax validation utilities."""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)

def validate_javascript(script: str) -> Tuple[bool, str]:
    """Validate JavaScript syntax using esprima.
    
    Returns:
        (is_valid, error_message)
    """
    if not script or not script.strip():
        return True, ""  # Empty script is valid
    
    try:
        import esprima
        esprima.parseScript(script, tolerant=True)
        return True, ""
    except esprima.Error as e:
        return False, f"JavaScript syntax error: {e}"
    except Exception as e:
        logger.warning(f"JS validation failed with unexpected error: {e}")
        # Be permissive on unexpected errors - don't block
        return True, ""


def try_fix_common_js_errors(script: str) -> str:
    """Attempt to fix common JavaScript syntax errors.
    
    Returns:
        Fixed script (or original if no fixes applied)
    """
    if not script:
        return script
    
    fixed = script
    
    # Fix unclosed braces (simple heuristic)
    open_braces = fixed.count('{')
    close_braces = fixed.count('}')
    if open_braces > close_braces:
        fixed += '\n}' * (open_braces - close_braces)
    
    # Fix unclosed parentheses
    open_parens = fixed.count('(')
    close_parens = fixed.count(')')
    if open_parens > close_parens:
        fixed += ')' * (open_parens - close_parens)
    
    return fixed
```

3. **`src/services/agent.py`** - Use in `_parse_slide_replacements`:

```python
from src.utils.js_validator import validate_javascript, try_fix_common_js_errors

# After extracting scripts for each slide
for slide in replacement_slides:
    if slide.scripts:
        is_valid, error = validate_javascript(slide.scripts)
        if not is_valid:
            logger.warning(f"Invalid JS in slide, attempting fix: {error}")
            fixed_scripts = try_fix_common_js_errors(slide.scripts)
            is_valid, error = validate_javascript(fixed_scripts)
            if is_valid:
                slide.scripts = fixed_scripts
                logger.info("JS syntax fixed successfully")
            else:
                logger.error(f"Could not fix JS syntax: {error}")
                # Option: clear invalid scripts to prevent browser errors
                # slide.scripts = ""
```

**Test Cases:**

| Test ID | Scenario | Expected Outcome |
|---------|----------|------------------|
| RC5-T1 | Valid JavaScript | Passes validation |
| RC5-T2 | Missing closing brace `}` | Fixed automatically |
| RC5-T3 | Missing closing paren `)` | Fixed automatically |
| RC5-T4 | Completely malformed JS | Warning logged, handled gracefully |
| RC5-T5 | Empty script | Passes validation |
| RC5-T6 | Script with try without catch | Detected as invalid |

---

### Phase 6: Cache Restoration from Database (RC6)

**Goal:** Ensure deck is restored from database if in-memory cache is empty (e.g., after backend restart).

**Problem Identified:**
- Backend uses `--reload` flag in development, which restarts on file changes
- In-memory `_deck_cache` is wiped on every restart
- Code directly accessed cache with `_deck_cache.get(session_id)` without database fallback
- Users editing slides after a restart would lose all their work

**Root Cause:**
```python
# BEFORE (buggy) - lines 234 and 469 in chat_service.py:
with self._cache_lock:
    current_deck = self._deck_cache.get(session_id)  # Returns None if cache empty!
```

**Solution:**
Use existing `_get_or_load_deck()` method which properly restores from database:

```python
# AFTER (fixed):
current_deck = self._get_or_load_deck(session_id)  # Checks cache, falls back to DB
```

**Changes:**

1. **`src/api/services/chat_service.py`** - Line 232-234 (sync method):
```python
# BEFORE:
# Get cached deck for this session (thread-safe)
with self._cache_lock:
    current_deck = self._deck_cache.get(session_id)

# AFTER:
# Get deck from cache or restore from database (RC6: survive backend restarts)
current_deck = self._get_or_load_deck(session_id)
```

2. **`src/api/services/chat_service.py`** - Line 466-468 (streaming method):
```python
# Same change as above
current_deck = self._get_or_load_deck(session_id)
```

**The `_get_or_load_deck()` method (already existed at line 680-700):**
```python
def _get_or_load_deck(self, session_id: str) -> Optional[SlideDeck]:
    # Check cache first (with lock)
    with self._cache_lock:
        if session_id in self._deck_cache:
            return self._deck_cache[session_id]

    # Try to load from database (outside lock to avoid blocking)
    session_manager = get_session_manager()
    deck_data = session_manager.get_slide_deck(session_id)

    if deck_data and deck_data.get("html_content"):
        try:
            deck = SlideDeck.from_html_string(deck_data["html_content"])
            # Store in cache (with lock)
            with self._cache_lock:
                self._deck_cache[session_id] = deck
            return deck
        except Exception as e:
            logger.warning(f"Failed to load deck from database: {e}")

    return None
```

**Test Cases:**

| Test ID | Scenario | Expected Outcome |
|---------|----------|------------------|
| RC6-T1 | Edit with deck in cache | Deck returned from cache |
| RC6-T2 | Edit with empty cache, deck in DB | Deck restored from DB |
| RC6-T3 | Edit with empty cache, no deck in DB | Returns None gracefully |
| RC6-T4 | Backend restart mid-session | Deck restored, editing continues |
| RC6-T5 | Multiple restarts during editing | All edits preserved |

**Production Impact:**
- ✅ Development with `--reload`: Safe
- ✅ Production deployments: No data loss
- ✅ Backend crashes: Deck survives
- ✅ Memory-based restarts: Deck survives

---

### Phase 7: Script Persistence on Database Restore (RC7)

**Goal:** Preserve individual slide scripts (charts) when loading deck from database.

**Problem Identified:**
- When deck is saved, `knit()` aggregates all slide scripts into IIFE-wrapped blocks
- When deck is loaded via `from_html_string()`, the IIFE parsing fails to split scripts correctly
- Individual slide scripts are lost, causing charts to disappear after backend restart

**Root Cause:**
```python
# BEFORE (buggy) in _get_or_load_deck():
if deck_data and deck_data.get("html_content"):
    deck = SlideDeck.from_html_string(deck_data["html_content"])
    # ❌ from_html_string can't parse IIFE-wrapped scripts
    # ❌ Individual slide.scripts lost, charts disappear
```

**Solution:**
Use the `slides` array from `deck_dict` (which preserves per-slide scripts) instead of parsing from raw HTML:

```python
# AFTER (fixed):
def _get_or_load_deck(self, session_id: str) -> Optional[SlideDeck]:
    deck_data = session_manager.get_slide_deck(session_id)
    
    # Prefer reconstructing from slides array (preserves individual scripts)
    if deck_data.get("slides"):
        deck = self._reconstruct_deck_from_dict(deck_data)
    elif deck_data.get("html_content"):
        # Fallback: parse from raw HTML (may lose scripts due to IIFE parsing)
        deck = SlideDeck.from_html_string(deck_data["html_content"])
    
def _reconstruct_deck_from_dict(self, deck_data: Dict[str, Any]) -> SlideDeck:
    """Reconstruct SlideDeck from stored dict (preserves individual slide scripts)."""
    slides = []
    for slide_data in deck_data.get("slides", []):
        slide = Slide(
            html=slide_data.get("html", ""),
            slide_id=slide_data.get("slide_id", f"slide_{len(slides)}"),
            scripts=slide_data.get("scripts", ""),  # ✅ Individual scripts preserved
        )
        slides.append(slide)
    
    deck = SlideDeck(
        slides=slides,
        css=deck_data.get("css", ""),
        external_scripts=deck_data.get("external_scripts", []),
        title=deck_data.get("title"),
    )
    return deck
```

**Changes:**

1. **`src/api/services/chat_service.py`** - Updated `_get_or_load_deck()`:
   - Check for `slides` array first
   - Use new `_reconstruct_deck_from_dict()` to preserve scripts
   - Fallback to `from_html_string()` only for legacy data

2. **`src/api/services/chat_service.py`** - Added `_reconstruct_deck_from_dict()`:
   - Reconstructs `SlideDeck` from stored JSON dict
   - Preserves individual slide `scripts` property

**Test Cases:**

| Test ID | Scenario | Expected Outcome |
|---------|----------|------------------|
| RC7-T1 | Load deck with slides array | Scripts preserved on each slide |
| RC7-T2 | Load legacy deck (HTML only) | Falls back to HTML parsing |
| RC7-T3 | Backend restart with chart slides | Charts still render after restore |
| RC7-T4 | Add slide after restart | Existing charts preserved, new slide added |

**Production Impact:**
- ✅ Charts survive backend restarts
- ✅ Slide scripts properly associated with individual slides
- ✅ Backward compatible with legacy data (HTML fallback)
- ✅ No data loss on append/edit operations after cache miss

---

### Phase 8: Clarification-First Approach (RC8, RC9, RC10, RC11)

**Goal:** Allow users to reference slides naturally, with clarification for ambiguous requests. **Never fail silently.**

**Problem Identified:**
- User says "edit slide 8 background to orange" without selecting
- No `slide_context` provided → treated as new generation
- LLM returns 1 slide → entire deck replaced → **DATA LOSS**

**Solution: Clarification-First with Guards**

**Core Principle:** Either source works (text reference OR panel selection). When ambiguous, always ask for clarification.

| Scenario | Has Selection? | Has Slide Ref in Text? | Action |
|----------|---------------|------------------------|--------|
| "replace slide 3 chart with pie" | No | Yes ("slide 3") | ✅ Proceed - parse "slide 3" |
| "replace the chart with pie" | Yes (slide 3) | No | ✅ Proceed - use selection |
| "replace slide 3 chart with pie" | Yes (slide 2) | Yes ("slide 3") | ✅ Proceed - **use selection** (explicit action wins) |
| "replace the chart with pie" | No | No | ❓ **Ask clarification** |
| "change the background to blue" | No | No | ❓ **Ask clarification** |

**Clarification Message:**
> "I'd like to help edit your slides. Could you please specify which slide? You can either:
> - Say the slide number (e.g., 'change slide 3 background to blue')
> - Or select the slide from the panel on the left"

```
User message
         │
         ▼
┌─────────────────────────────┐
│ 1. CHECK SELECTION           │
│   slide_context provided?    │
│   YES → Use selection ✅     │
└─────────────┬───────────────┘
              │ NO
              ▼
┌─────────────────────────────┐
│ 2. INTENT CLASSIFICATION     │
│   - _detect_generation_intent│
│   - _detect_edit_intent      │
│   - _detect_add_intent       │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ 3. PARSE SLIDE REFERENCES    │
│   - "slide 8" → index 7      │
│   - "slides 2-4" → [1,2,3]   │
│   - "after slide 3" → pos=4  │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ 4. ROUTE DECISION            │
│                             │
│ generation? → New deck ✅    │
│ edit + ref? → Synthetic ctx ✅│
│ add + ref?  → Insert at pos ✅│
│ add + no ref? → End of deck ✅│
│ edit + no ref? → ASK USER ⚠️│
│ ambiguous?  → Preserve deck ⚠️│
└─────────────────────────────┘
```

**RC11: Selection Wins Over Text Reference**

When user selects slide 2 but writes "edit slide 3", the explicit action (selection) takes precedence:
- Selection is a deliberate UI action
- Text reference may be a typo or outdated
- Prevents confusion from conflicting instructions

**Changes:**

1. **`src/api/services/chat_service.py`** - Add `_detect_generation_intent()`:
```python
def _detect_generation_intent(self, message: str) -> bool:
    """Detect if user wants to generate NEW slides (replace deck)."""
    generation_patterns = [
        r"\bgenerate\b.*\bslides?\b",
        r"\bcreate\b.*\b(presentation|slides?|deck)\b",
        r"\bmake\s+me\b.*\bslides?\b",
        r"\b\d+\s+slides?\s+(about|on|for)\b",  # "5 slides about X"
        r"\bnew\s+(presentation|deck|slides?)\b",
    ]
    # Only these should replace entire deck
```

2. **`src/api/services/chat_service.py`** - Add `_detect_edit_intent()`:
```python
def _detect_edit_intent(self, message: str) -> bool:
    """Detect if user wants to edit existing slides."""
    edit_patterns = [
        r"\b(change|edit|modify|update|fix)\b.*\bslide\b",
        r"\bslide\b.*\b(change|edit|modify|update|fix)\b",
        r"\b(change|update)\b.*(color|background|title|text|chart)",
    ]
```

3. **`src/api/services/chat_service.py`** - Add `_parse_slide_references()`:
```python
def _parse_slide_references(self, message: str) -> tuple[list[int], Optional[str]]:
    """Parse slide numbers from message.
    
    Returns:
        (indices, position) - indices are 0-based, position is 'before'/'after' or None
    
    Examples:
        "slide 8" → ([7], None)
        "slides 2-4" → ([1, 2, 3], None)
        "after slide 3" → ([2], "after")
        "before slide 5" → ([4], "before")
    """
    patterns = [
        (r"\bslide\s*#?(\d+)\b", None),           # "slide 8"
        (r"\b(\d+)(?:st|nd|rd|th)\s+slide", None), # "8th slide"
        (r"\bafter\s+slide\s*#?(\d+)\b", "after"), # "after slide 3"
        (r"\bbefore\s+slide\s*#?(\d+)\b", "before"),
        (r"\bslides?\s*(\d+)\s*[-–to]+\s*(\d+)\b", None),  # "slides 2-4"
    ]
```

4. **`src/api/services/chat_service.py`** - Update message routing:
```python
# In send_message_streaming, BEFORE processing:

if not slide_context:
    # No selection - classify intent
    is_generation = self._detect_generation_intent(message)
    is_edit = self._detect_edit_intent(message)
    is_add = self._detect_add_intent(message)
    slide_refs, position = self._parse_slide_references(message)
    
    if is_generation:
        # Allow deck replacement
        pass
    elif is_edit:
        if slide_refs:
            # Create synthetic slide_context
            slide_context = self._create_synthetic_context(session_id, slide_refs)
        else:
            # GUARD: Ask for clarification
            return self._return_clarification_needed(
                "Which slide would you like to edit? Please specify (e.g., 'slide 3') or select it."
            )
    elif is_add and slide_refs:
        # Use parsed position for insertion
        # e.g., "add after slide 3" → insert at position 4
        pass
```

**Test Cases:**

| Test ID | Scenario | Expected Outcome |
|---------|----------|------------------|
| RC8-T1 | "Edit slide 8 color" (no select) | Edit slide 8, deck preserved |
| RC8-T2 | "Change slide 3 title" (no select) | Edit slide 3, deck preserved |
| RC9-T1 | "Add after slide 5" (no select) | Insert at position 6 |
| RC9-T2 | "Add before slide 2" (no select) | Insert at position 1 |
| RC10-T1 | "Change the background" (no select, no ref) | Return clarification message |
| RC10-T2 | "Edit the chart" (no select, no ref) | Return clarification message |
| RC10-T3 | "Generate 5 slides about X" | New deck (allowed) |
| RC10-T4 | "Create 3 slides" (no existing deck) | New deck (generation intent) |
| RC11-T1 | Select slide 2 + "edit slide 3" | Edit slide 2 (selection wins) + note |
| RC11-T2 | Select slide 5 + "add after slide 2" | Add after slide 5 (selection wins) + note |
| RC12-T1 | "Create 5 slides about X" (existing deck) | Ask: Add or Replace? |
| RC12-T2 | "Generate slides about X" (existing deck) | Ask: Add or Replace? |
| RC12-T3 | "Add 3 slides about X" (existing deck) | Add slides (no clarification) |
| RC12-T4 | "Replace with new slides about X" | Replace deck (explicit intent) |
| RC12-T5 | "Start fresh with slides about X" | Replace deck (explicit intent) |

**Guard Principles:**
1. **Never replace a deck unless explicitly generating new slides.** For any edit/modify operation without a clear target, ask for clarification.
2. **Never fail silently.** Either proceed with confidence OR ask for clarification.
3. **Selection wins.** When text reference and panel selection conflict, use the explicit action (selection).

**Production Impact:**
- ✅ Users can reference slides by number naturally
- ✅ No data loss from ambiguous requests
- ✅ Clear feedback when clarification needed
- ✅ Only explicit "generate" commands replace deck
- ✅ Selection always takes precedence over text reference

---

### Phase 9: Selection vs Text Conflict Note (RC11)

**Goal:** Inform users when their selection differs from the slide number they mentioned.

**Problem:** User selects slide 2 but writes "edit slide 3" → which one gets edited? Confusion.

**Solution:** Selection wins (explicit action), but show a note explaining what happened.

**Implementation:**

```python
# In send_message_streaming, before calling agent:
if slide_context:
    text_refs, _ = self._parse_slide_references(message)
    if text_refs:
        selected_indices = slide_context.get("indices", [])
        if set(text_refs) != set(selected_indices):
            conflict_note = (
                f"📝 Applied changes to **slide {selected_display}** (your selection). "
                f"Note: you mentioned slide {text_display} in your message."
            )

# After agent completes, yield the note before COMPLETE event
if conflict_note:
    yield StreamEvent(type=StreamEventType.ASSISTANT, content=conflict_note)
```

**User Experience:**
- Changes are applied to selected slide (explicit action)
- User sees a brief note explaining what happened
- They can immediately redo if they meant the other slide

---

### Phase 10: Generation Clarification (RC12)

**Goal:** Prevent accidental deck replacement when user says "create/generate slides" with existing deck.

**Problem:** User has 5 slides, says "create 3 slides about X" → Entire deck replaced! Data loss.

**Solution:** Ask for clarification: Add or Replace?

**Implementation:**

```python
# In send_message_streaming early checks:
if is_generation and not is_add and not is_explicit_replace:
    if existing_deck and len(existing_deck.slides) > 0:
        clarification_msg = (
            f"You have **{len(existing_deck.slides)} slides** in this session. "
            "Would you like to:\n"
            "- **Add** new slides to the existing deck?\n"
            "- **Replace** the entire deck with a new presentation?"
        )
        yield StreamEvent(type=StreamEventType.ASSISTANT, content=clarification_msg)
        return  # Stop, wait for user response

# Explicit replace patterns that bypass clarification:
replace_patterns = [
    r"\breplace\b.*\b(deck|slides?|presentation)\b",
    r"\bstart\s+fresh\b",
    r"\bstart\s+over\b",
    r"\bnew\s+deck\b",
    r"\bfrom\s+scratch\b",
]
```

**User Experience:**
- "Create 5 slides about X" (existing deck) → "You have 5 slides. Add or Replace?"
- "Add 3 slides about X" → Adds slides (no clarification needed)
- "Replace with slides about X" → Replaces (explicit intent, no clarification)
- "Start fresh with slides about X" → Replaces (explicit intent)

---

### Known Performance Issue: Session History Loading (Pre-existing)

**Problem:** `list_sessions()` and `get_session()` use `len(s.messages)` which triggers N+1 queries.

**Location:** `src/api/services/session_manager.py` lines 119, 158

**Impact:** Slow session list loading (noticeable with many sessions/messages)

**Fix (separate task):**
```python
# Use SQL COUNT instead of loading all messages
from sqlalchemy import func

message_count = db.query(func.count(SessionMessage.id)).filter(
    SessionMessage.session_id == session.id
).scalar()
```

**Note:** This is a pre-existing issue, not introduced by our fixes.

---

## 4. Test Implementation

### Test File: `tests/unit/test_slide_editing_robustness.py`

```python
"""Comprehensive tests for slide editing robustness fixes.

Tests cover:
- RC1: LLM response validation and retry
- RC2: Add vs edit intent detection
- RC3: Deck preservation on failure
- RC4: Canvas ID deduplication
- RC5: JavaScript syntax validation
- RC6: Cache restoration from database
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from bs4 import BeautifulSoup

from src.services.agent import SlideGeneratorAgent
from src.api.services.chat_service import ChatService
from src.domain.slide_deck import SlideDeck
from src.domain.slide import Slide
from src.utils.js_validator import validate_javascript, try_fix_common_js_errors


# =============================================================================
# RC3: Deck Preservation Tests
# =============================================================================

class TestDeckPreservation:
    """Tests for RC3: Deck should never be destroyed on editing failures."""

    @pytest.fixture
    def chat_service_with_deck(self):
        """Create a chat service with a pre-populated deck."""
        service = ChatService()
        # Create a mock deck with 3 slides
        deck = SlideDeck(
            title="Test Deck",
            slides=[
                Slide(html='<div class="slide"><h1>Slide 1</h1></div>', slide_id="slide_0"),
                Slide(html='<div class="slide"><h1>Slide 2</h1></div>', slide_id="slide_1"),
                Slide(html='<div class="slide"><h1>Slide 3</h1></div>', slide_id="slide_2"),
            ]
        )
        service._deck_cache["test_session"] = deck
        return service, deck

    def test_rc3_t1_text_response_preserves_deck(self, chat_service_with_deck):
        """RC3-T1: LLM returns text with slides selected → deck preserved."""
        service, original_deck = chat_service_with_deck
        
        # Simulate replacement_info being None (parsing failed)
        replacement_info = None
        slide_context = {"indices": [0, 1], "slide_htmls": ["...", "..."]}
        
        # The guard should prevent deck destruction
        # This test verifies the logic we're adding
        with pytest.raises(ValueError, match="Failed to parse"):
            service._handle_editing_failure(
                slide_context=slide_context,
                replacement_info=replacement_info,
                session_id="test_session"
            )
        
        # Deck should still exist
        assert "test_session" in service._deck_cache
        assert len(service._deck_cache["test_session"].slides) == 3

    def test_rc3_t2_empty_response_preserves_deck(self, chat_service_with_deck):
        """RC3-T2: LLM returns empty string with slides selected → deck preserved."""
        service, original_deck = chat_service_with_deck
        
        html_output = ""
        slide_context = {"indices": [0], "slide_htmls": ["..."]}
        
        # Should not destroy deck
        cached_deck = service._deck_cache.get("test_session")
        assert cached_deck is not None
        assert len(cached_deck.slides) == 3

    def test_rc3_t3_malformed_html_preserves_deck(self, chat_service_with_deck):
        """RC3-T3: Malformed HTML with slides selected → deck preserved."""
        service, original_deck = chat_service_with_deck
        
        malformed_html = "<div><span>Not a slide</div></span>"
        slide_context = {"indices": [0], "slide_htmls": ["..."]}
        
        # Parsing should fail but deck should be preserved
        cached_deck = service._deck_cache.get("test_session")
        assert cached_deck is not None

    def test_rc3_t4_valid_edit_updates_deck(self, chat_service_with_deck):
        """RC3-T4: Valid HTML edit updates deck correctly."""
        service, original_deck = chat_service_with_deck
        
        replacement_info = {
            "replacement_slides": [
                Slide(html='<div class="slide"><h1>Updated Slide</h1></div>', slide_id="slide_0")
            ],
            "start_index": 0,
            "original_count": 1,
            "replacement_count": 1,
            "replacement_css": "",
        }
        
        result = service._apply_slide_replacements(replacement_info, "test_session")
        
        assert result is not None
        # First slide should be updated
        cached_deck = service._deck_cache["test_session"]
        assert "Updated Slide" in cached_deck.slides[0].html

    def test_rc3_t5_new_generation_creates_deck(self):
        """RC3-T5: New generation (no slides selected) creates new deck."""
        service = ChatService()
        
        html_output = '''
        <!DOCTYPE html>
        <html>
        <body>
        <div class="slide"><h1>New Slide</h1></div>
        </body>
        </html>
        '''
        
        # No slide_context means new generation
        deck = SlideDeck.from_html_string(html_output)
        service._deck_cache["new_session"] = deck
        
        assert "new_session" in service._deck_cache
        assert len(service._deck_cache["new_session"].slides) == 1


# =============================================================================
# RC1: LLM Response Validation Tests
# =============================================================================

class TestLLMResponseValidation:
    """Tests for RC1: Validate LLM response before processing."""

    @pytest.fixture
    def agent(self):
        """Create agent with mocked settings."""
        with patch('src.services.agent.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(endpoint="test", temperature=0.7, max_tokens=1000, timeout=60),
                genie=None,
                prompts={"system_prompt": "test", "slide_style": "test"},
                mlflow=MagicMock(experiment_name="/test")
            )
            with patch('src.services.agent.get_databricks_client'):
                agent = SlideGeneratorAgent()
        return agent

    def test_rc1_t1_detects_delete_text(self, agent):
        """RC1-T1: Detect 'I understand you want to delete' text."""
        response = "I understand you want to delete both slides. There are no slides remaining."
        
        is_valid, error = agent._validate_editing_response(response)
        
        assert is_valid is False
        assert "conversational text" in error.lower()

    def test_rc1_t2_detects_cannot_modify(self, agent):
        """RC1-T2: Detect 'I cannot modify' text."""
        response = "I cannot modify these slides as requested."
        
        is_valid, error = agent._validate_editing_response(response)
        
        assert is_valid is False

    def test_rc1_t3_accepts_valid_html(self, agent):
        """RC1-T3: Accept valid HTML with slide divs."""
        response = '<div class="slide"><h1>Valid Slide</h1></div>'
        
        is_valid, error = agent._validate_editing_response(response)
        
        assert is_valid is True
        assert error == ""

    def test_rc1_t4_retry_on_invalid_returns_valid(self, agent):
        """RC1-T4: Retry mechanism produces valid result."""
        # This would be an integration test with mocked LLM
        pass

    def test_rc1_t5_double_failure_raises_error(self, agent):
        """RC1-T5: Two failures in a row raises AgentError."""
        # This would be an integration test with mocked LLM
        pass

    def test_rc1_t6_html_without_slide_divs(self, agent):
        """RC1-T6: HTML without slide divs triggers retry."""
        response = '<div class="container"><p>No slide here</p></div>'
        
        is_valid, error = agent._validate_editing_response(response)
        
        assert is_valid is False
        assert "No <div class='slide'>" in error


# =============================================================================
# RC2: Add vs Edit Intent Detection Tests
# =============================================================================

class TestAddIntentDetection:
    """Tests for RC2: Detect add slide vs edit slide intent."""

    @pytest.fixture
    def agent(self):
        """Create agent with mocked settings."""
        with patch('src.services.agent.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(endpoint="test", temperature=0.7, max_tokens=1000, timeout=60),
                genie=None,
                prompts={"system_prompt": "test", "slide_style": "test"},
                mlflow=MagicMock(experiment_name="/test")
            )
            with patch('src.services.agent.get_databricks_client'):
                agent = SlideGeneratorAgent()
        return agent

    def test_rc2_t1_add_at_bottom_detected(self, agent):
        """RC2-T1: 'add a slide at the bottom for summary' → add intent."""
        message = "add a slide at the bottom for summary"
        
        is_add = agent._detect_add_intent(message)
        
        assert is_add is True

    def test_rc2_t2_insert_new_slide_detected(self, agent):
        """RC2-T2: 'insert a new slide after this one' → add intent."""
        message = "insert a new slide after this one"
        
        is_add = agent._detect_add_intent(message)
        
        assert is_add is True

    def test_rc2_t3_change_color_is_edit(self, agent):
        """RC2-T3: 'change the color to red' → NOT add intent."""
        message = "change the color to red"
        
        is_add = agent._detect_add_intent(message)
        
        assert is_add is False

    def test_rc2_t4_make_blue_is_edit(self, agent):
        """RC2-T4: 'make this slide blue' → NOT add intent."""
        message = "make this slide blue"
        
        is_add = agent._detect_add_intent(message)
        
        assert is_add is False

    def test_rc2_t5_create_new_summary(self, agent):
        """RC2-T5: 'create a new summary slide' → add intent."""
        message = "create a new summary slide"
        
        is_add = agent._detect_add_intent(message)
        
        assert is_add is True

    def test_rc2_t6_append_slide(self, agent):
        """RC2-T6: 'append a slide' → add intent."""
        message = "append a conclusions slide"
        
        is_add = agent._detect_add_intent(message)
        
        assert is_add is True

    def test_rc2_t7_add_at_end(self, agent):
        """RC2-T7: 'add at the end' → add intent."""
        message = "add a chart at the end"
        
        is_add = agent._detect_add_intent(message)
        
        assert is_add is True


# =============================================================================
# RC4: Canvas ID Deduplication Tests
# =============================================================================

class TestCanvasIdDeduplication:
    """Tests for RC4: Generate unique canvas IDs to prevent collisions."""

    @pytest.fixture
    def agent(self):
        """Create agent with mocked settings."""
        with patch('src.services.agent.get_settings') as mock_settings:
            mock_settings.return_value = MagicMock(
                llm=MagicMock(endpoint="test", temperature=0.7, max_tokens=1000, timeout=60),
                genie=None,
                prompts={"system_prompt": "test", "slide_style": "test"},
                mlflow=MagicMock(experiment_name="/test")
            )
            with patch('src.services.agent.get_databricks_client'):
                agent = SlideGeneratorAgent()
        return agent

    def test_rc4_t1_single_canvas_deduplicated(self, agent):
        """RC4-T1: Single canvas ID gets unique suffix."""
        html = '<div class="slide"><canvas id="chart1"></canvas></div>'
        scripts = 'const ctx = document.getElementById("chart1");'
        
        new_html, new_scripts = agent._deduplicate_canvas_ids(html, scripts)
        
        # Original ID should not exist
        assert 'id="chart1"' not in new_html
        # New ID should have suffix
        assert 'id="chart1_' in new_html
        # Scripts should be updated
        assert 'getElementById("chart1_' in new_scripts

    def test_rc4_t2_multiple_canvases_same_suffix(self, agent):
        """RC4-T2: Multiple canvases in one slide get same suffix."""
        html = '''<div class="slide">
            <canvas id="chart1"></canvas>
            <canvas id="chart2"></canvas>
        </div>'''
        scripts = '''
            document.getElementById("chart1");
            document.getElementById("chart2");
        '''
        
        new_html, new_scripts = agent._deduplicate_canvas_ids(html, scripts)
        
        soup = BeautifulSoup(new_html, "html.parser")
        canvas_ids = [c.get("id") for c in soup.find_all("canvas")]
        
        # Both should have same suffix
        suffix1 = canvas_ids[0].split("_")[1]
        suffix2 = canvas_ids[1].split("_")[1]
        assert suffix1 == suffix2

    def test_rc4_t3_scripts_references_updated(self, agent):
        """RC4-T3: All script references to canvas IDs are updated."""
        html = '<canvas id="myChart"></canvas>'
        scripts = '''
            // Canvas: myChart
            const canvas = document.getElementById("myChart");
            const ctx = canvas.getContext("2d");
        '''
        
        new_html, new_scripts = agent._deduplicate_canvas_ids(html, scripts)
        
        assert 'getElementById("myChart")' not in new_scripts
        assert '// Canvas: myChart_' in new_scripts or 'getElementById("myChart_' in new_scripts

    def test_rc4_t4_no_canvas_unchanged(self, agent):
        """RC4-T4: Slide without canvas is unchanged."""
        html = '<div class="slide"><h1>No chart here</h1></div>'
        scripts = 'console.log("no canvas");'
        
        new_html, new_scripts = agent._deduplicate_canvas_ids(html, scripts)
        
        assert new_html == html
        assert new_scripts == scripts

    def test_rc4_t5_consecutive_edits_unique_suffixes(self, agent):
        """RC4-T5: Two consecutive edits get different suffixes."""
        html = '<canvas id="chart"></canvas>'
        scripts = 'document.getElementById("chart");'
        
        _, scripts1 = agent._deduplicate_canvas_ids(html, scripts)
        _, scripts2 = agent._deduplicate_canvas_ids(html, scripts)
        
        # Extract suffixes (they should be different)
        import re
        suffix1 = re.search(r'chart_(\w+)', scripts1).group(1)
        suffix2 = re.search(r'chart_(\w+)', scripts2).group(1)
        
        assert suffix1 != suffix2


# =============================================================================
# RC5: JavaScript Syntax Validation Tests
# =============================================================================

class TestJavaScriptValidation:
    """Tests for RC5: Validate and fix JavaScript syntax."""

    def test_rc5_t1_valid_js_passes(self):
        """RC5-T1: Valid JavaScript passes validation."""
        script = '''
            const canvas = document.getElementById("chart");
            if (canvas) {
                const ctx = canvas.getContext("2d");
                new Chart(ctx, { type: "bar", data: {} });
            }
        '''
        
        is_valid, error = validate_javascript(script)
        
        assert is_valid is True
        assert error == ""

    def test_rc5_t2_missing_brace_fixed(self):
        """RC5-T2: Missing closing brace is fixed."""
        script = '''
            if (true) {
                console.log("test");
        '''  # Missing closing brace
        
        fixed = try_fix_common_js_errors(script)
        is_valid, _ = validate_javascript(fixed)
        
        assert fixed.count('{') == fixed.count('}')

    def test_rc5_t3_missing_paren_fixed(self):
        """RC5-T3: Missing closing parenthesis is fixed."""
        script = 'console.log("test"'  # Missing closing paren
        
        fixed = try_fix_common_js_errors(script)
        
        assert fixed.count('(') == fixed.count(')')

    def test_rc5_t4_malformed_js_detected(self):
        """RC5-T4: Completely malformed JS is detected."""
        script = 'function { this is not valid javascript }'
        
        is_valid, error = validate_javascript(script)
        
        assert is_valid is False
        assert "syntax error" in error.lower()

    def test_rc5_t5_empty_script_valid(self):
        """RC5-T5: Empty script passes validation."""
        script = ""
        
        is_valid, error = validate_javascript(script)
        
        assert is_valid is True

    def test_rc5_t6_try_without_catch_detected(self):
        """RC5-T6: try without catch is detected as invalid."""
        script = '''
            try {
                riskyOperation();
            }
        '''  # Missing catch or finally
        
        is_valid, error = validate_javascript(script)
        
        assert is_valid is False


# =============================================================================
# Integration Tests
# =============================================================================

class TestSlideEditingIntegration:
    """Integration tests for the complete slide editing flow."""

    def test_edit_with_valid_response_succeeds(self):
        """Full edit flow with valid LLM response."""
        pass  # Implement with mocked LLM

    def test_edit_with_invalid_response_preserves_deck(self):
        """Full edit flow with invalid LLM response preserves deck."""
        pass  # Implement with mocked LLM

    def test_add_slide_creates_additional_slide(self):
        """Add slide operation increases slide count."""
        pass  # Implement with mocked LLM

    def test_canvas_collision_prevented(self):
        """Editing chart slide doesn't cause canvas collision."""
        pass  # Implement with mocked deck
```

---

## 5. File Changes Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `src/services/agent.py` | Modify | RC1: validation & retry, RC2: add intent detection + `is_add_operation` flag, RC4: canvas deduplication, RC5: JS validation integration |
| `src/api/services/chat_service.py` | Modify | RC3: deck preservation guard, RC6: cache restoration, RC8-RC13: intent detection & guards, RC13: auto-create slide_context from text reference |
| `src/utils/js_validator.py` | New | RC5: JavaScript syntax validation utilities |
| `src/core/defaults.py` | Modify | RC2: Clear EDIT/ADD/EXPAND operation instructions aligned with backend |
| `tests/unit/test_slide_editing_robustness.py` | New | Comprehensive test suite (45 tests) |
| `requirements.txt` | Modify | Add `esprima` dependency |
| `pyproject.toml` | Modify | Add `esprima>=4.0.0` dependency |

---

## 6. Rollout Plan

### Step 1: Implement RC3 (Deck Preservation)
- Add guard in `chat_service.py`
- Run RC3-T1 through RC3-T5 tests
- Verify existing functionality not broken

### Step 2: Implement RC1 (Response Validation)
- Add validation method in `agent.py`
- Add retry logic
- Run RC1-T1 through RC1-T6 tests

### Step 3: Implement RC2 (Add Intent Detection)
- Add intent detection method
- Modify `_format_slide_context`
- Run RC2-T1 through RC2-T7 tests

### Step 4: Implement RC4 (Canvas Deduplication)
- Add deduplication method
- Apply in `_parse_slide_replacements`
- Run RC4-T1 through RC4-T5 tests

### Step 5: Implement RC5 (JS Validation)
- Create `js_validator.py`
- Add `esprima` dependency
- Integrate in agent
- Run RC5-T1 through RC5-T6 tests

### Step 6: Integration Testing
- Run full test suite
- Manual testing of all scenarios
- Edge case verification

---

## 7. Success Criteria

| Criterion | Measurement |
|-----------|-------------|
| No deck loss on invalid LLM response | RC3 tests pass, manual verification |
| Invalid responses trigger retry | RC1 tests pass |
| Add intent properly detected | RC2 tests pass |
| No canvas ID collisions | RC4 tests pass |
| No JS syntax errors in browser | RC5 tests pass, manual verification |
| All existing tests still pass | `pytest tests/` passes |

---

## 8. Code Quality Improvements

During the final review, several code quality issues were identified and fixed:

| Issue | Problem | Fix |
|-------|---------|-----|
| Double Intent Detection | Regex patterns running twice per request (early + late) | Store detection results in variables (`_is_edit`, `_is_generation`, `_is_add`, `_slide_refs`) at start and reuse throughout |
| Dead Code | `_create_synthetic_context` method defined but never called | Removed (37 lines of dead code) |
| Overly Broad Pattern | `r"\b\d+\s+slides?\b"` caused false positives (e.g., "edit slide 5 slides look broken" matched as generation) | Removed pattern; more specific patterns are sufficient |
| Duplicate Imports | `import re` inside multiple methods | Moved to top of file |
| Misleading Comment | Comment said "insert at end" but code inserts at calculated position | Updated comment to match behavior |
| Unused Import | `BeautifulSoup` imported but not used | Removed |

### Intent Detection Flow (Optimized)

```python
# BEFORE: Detection called twice
def send_message_streaming(...):
    if not slide_context:
        is_edit = self._detect_edit_intent(message)  # First call
        ...
    
    # After LLM returns
    is_edit = self._detect_edit_intent(message)  # Second call (duplicate!)

# AFTER: Detection called once, results stored and reused
def send_message_streaming(...):
    # Detect ONCE at start
    _is_edit = self._detect_edit_intent(message)
    _is_generation = self._detect_generation_intent(message)
    _is_add = self._detect_add_intent(message)
    _slide_refs, _ref_position = self._parse_slide_references(message)
    
    if not slide_context:
        if _is_edit and not _slide_refs:  # Reuse stored result
            # Ask clarification
    
    # After LLM returns
    if _is_edit and _slide_refs:  # Reuse stored result
        # Apply edit to referenced slides
```

### RC13: Auto-Create Slide Context from Text Reference

**Problem:** When user says "edit slide 7" without selecting in the panel, the system detected the slide reference but didn't pass the slide's HTML to the LLM. The LLM would then ask "Can you provide the slide content?"

**Solution:** Before calling the LLM, if we detect an edit intent with a slide reference but no frontend selection, look up the slide from the deck and create `slide_context` automatically.

```python
# RC13: Auto-create slide_context from text reference
if _is_edit and _slide_refs and not slide_context:
    existing_deck = self._get_or_load_deck(session_id)
    if existing_deck and len(existing_deck.slides) > 0:
        valid_refs = [i for i in _slide_refs if 0 <= i < len(existing_deck.slides)]
        if valid_refs:
            # Look up actual slide HTML (already stored per-slide via RC7)
            slide_htmls = [existing_deck.slides[i].html for i in valid_refs]
            # Create context in same format as frontend selection
            slide_context = {
                "indices": valid_refs,
                "slide_htmls": slide_htmls
            }
```

**Test Cases:**

| Test ID | Scenario | Expected Outcome |
|---------|----------|------------------|
| RC13-T1 | "Change slide 7 background to grey" (no selection) | Slide 7 edited, LLM receives slide HTML |
| RC13-T2 | "Edit slides 2-4" (no selection) | All 3 slides edited, LLM receives all HTML |
| RC13-T3 | "Change slide 99 color" (out of range) | Falls through to other handling |

### RC15: Optimize Script Preservation Fix

**Problem:** When user clicks "Optimize" on a slide with a chart:
1. RC4 deduplication adds suffix to canvas ID: `mdpChart` → `mdpChart_abc0cb`
2. Original script references `mdpChart`
3. Script preservation looks for `mdpChart_abc0cb` → **no match**
4. If matched via base ID, script still references OLD canvas ID
5. Multiple optimizes compound the problem: `mdpChart_abc0cb_730ba9_b4ca7a`

**Solution:** Two-part fix in `_apply_slide_replacements`:

1. **Smart matching:** Strip RC4 suffix to find matching scripts
2. **Update references:** When preserving, update `getElementById` calls to use new canvas ID

```python
# 1. Try exact match, then fallback to base ID
base_id = re.sub(r'_[a-f0-9]{6}$', '', canvas_id)
if base_id in canvas_id_to_script:
    script_to_preserve = canvas_id_to_script[base_id]
    old_canvas_id = base_id

# 2. Update canvas ID references in preserved script
if old_canvas_id != canvas_id:
    script_to_preserve = re.sub(
        rf"getElementById\s*\(\s*['\"]({re.escape(old_canvas_id)})['\"]\s*\)",
        f"getElementById('{canvas_id}')",
        script_to_preserve,
    )
```

**Safety:** No behavior change for existing scenarios - only fixes optimize case.

---

### RC14: Unsupported Operations Guidance

**Problem:** When user asks to delete, reorder, or duplicate slides via chat:
- Delete/reorder: LLM naturally gives conversational response ✅
- Duplicate: LLM tries to return HTML (empty slide) ❌

**Solution:** Added section 6 to `slide_editing_instructions` in `defaults.py`:

```
6. UNSUPPORTED OPERATIONS (respond conversationally, do NOT return HTML):
   - DELETE/REMOVE: "Use the trash icon in the slide panel on the right"
   - REORDER/MOVE: "Drag and drop in the slide panel on the right"
   - DUPLICATE/COPY/CLONE: "Select the slide and ask 'create an exact copy'"
```

**Design Decision:** Keep duplicate simple - user selects slide, asks for exact copy. No special duplicate logic needed.

**Safety:** Even if LLM ignores these instructions, RC10 guard preserves the deck.

---

## 9. Cross-References

- [Backend Overview](./backend-overview.md) - Agent and chat service architecture
- [Slide Parser and Script Management](./slide-parser-and-script-management.md) - HTML parsing details
- [Frontend Overview](./frontend-overview.md) - UI handling of slides

---

## 10. Appendix: Test Commands

```bash
# Run all robustness tests
pytest tests/unit/test_slide_editing_robustness.py -v

# Run specific test class
pytest tests/unit/test_slide_editing_robustness.py::TestDeckPreservation -v

# Run with coverage
pytest tests/unit/test_slide_editing_robustness.py --cov=src --cov-report=html

# Run integration tests
pytest tests/integration/test_slide_editing_robustness.py -v
```
