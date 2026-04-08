# Prompt Mode Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the monolithic system prompt into composable prompt modules and introduce mode-aware agent construction so generation and editing each receive only the instructions they need.

**Architecture:** Extract prompt blocks from the single concatenated system prompt in `defaults.py` into named constants in a new `src/core/prompt_modules.py`. Provide `build_generation_system_prompt()` and `build_editing_system_prompt()` assembly functions. Thread a `mode` parameter from `ChatService` through `agent_factory` so the agent is built with only the relevant prompt.

**Tech Stack:** Python/FastAPI backend, LangChain agent, Pydantic config schemas

**Spec:** `docs/superpowers/specs/2026-03-31-prompt-mode-decoupling-design.md`

---

## Task ordering rationale

Tasks are ordered to keep the codebase buildable and testable at every commit. We start with the new module (no callers yet), then wire it into the factory, then simplify the agent, then update tests. Each task is independently committable except Tasks 2–4, which form an atomic group (the factory returns a new prompt shape that the agent must handle).

---

## Phase 1: Prompt Module Extraction

### Task 1: Create `src/core/prompt_modules.py`

**Files:**
- Create: `src/core/prompt_modules.py`
- Create: `tests/unit/test_prompt_modules.py`

- [ ] **Step 1: Write failing tests for prompt assembly**

Create `tests/unit/test_prompt_modules.py`:

```python
"""Tests for composable prompt module assembly."""
import pytest


class TestBuildGenerationPrompt:
    def test_includes_generation_rules(self):
        from src.core.prompt_modules import build_generation_system_prompt
        prompt = build_generation_system_prompt()
        assert "presentation creation" in prompt.lower() or "GENERATION" in prompt

    def test_includes_html_output_format(self):
        from src.core.prompt_modules import build_generation_system_prompt
        prompt = build_generation_system_prompt()
        assert "<!DOCTYPE html>" in prompt

    def test_excludes_editing_rules(self):
        from src.core.prompt_modules import build_generation_system_prompt
        prompt = build_generation_system_prompt()
        assert "EDITING_RULES" not in prompt
        assert "slide editing" not in prompt.lower() or "replacement" not in prompt.lower()

    def test_includes_shared_blocks(self):
        from src.core.prompt_modules import build_generation_system_prompt
        prompt = build_generation_system_prompt()
        assert "Chart.js" in prompt or "chart" in prompt.lower()

    def test_includes_deck_prompt_when_provided(self):
        from src.core.prompt_modules import build_generation_system_prompt
        prompt = build_generation_system_prompt(deck_prompt="Custom deck instructions")
        assert "Custom deck instructions" in prompt

    def test_includes_image_support(self):
        from src.core.prompt_modules import build_generation_system_prompt
        prompt = build_generation_system_prompt(image_guidelines="Use high-res images")
        assert "Use high-res images" in prompt


class TestBuildEditingPrompt:
    def test_includes_editing_rules(self):
        from src.core.prompt_modules import build_editing_system_prompt
        prompt = build_editing_system_prompt()
        assert "edit" in prompt.lower()

    def test_excludes_html_output_format(self):
        from src.core.prompt_modules import build_editing_system_prompt
        prompt = build_editing_system_prompt()
        assert "<!DOCTYPE html>" not in prompt

    def test_includes_shared_blocks(self):
        from src.core.prompt_modules import build_editing_system_prompt
        prompt = build_editing_system_prompt()
        assert "Chart.js" in prompt or "chart" in prompt.lower()

    def test_includes_deck_prompt_when_provided(self):
        from src.core.prompt_modules import build_editing_system_prompt
        prompt = build_editing_system_prompt(deck_prompt="Custom deck instructions")
        assert "Custom deck instructions" in prompt

    def test_includes_image_support(self):
        from src.core.prompt_modules import build_editing_system_prompt
        prompt = build_editing_system_prompt(image_guidelines="Use high-res images")
        assert "Use high-res images" in prompt


class TestModuleCoverage:
    def test_combined_prompts_cover_all_original_content(self):
        from src.core.prompt_modules import (
            BASE_PROMPT, GENERATION_RULES, EDITING_RULES,
            CHART_JS_RULES, HTML_OUTPUT_FORMAT, DATA_ANALYSIS_GUIDELINES,
        )
        assert len(BASE_PROMPT) > 0
        assert len(GENERATION_RULES) > 0
        assert len(EDITING_RULES) > 0
        assert len(CHART_JS_RULES) > 0
        assert len(HTML_OUTPUT_FORMAT) > 0
        assert len(DATA_ANALYSIS_GUIDELINES) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_prompt_modules.py -v --tb=short 2>&1 | tail -20`

Expected: FAIL — module doesn't exist yet.

- [ ] **Step 3: Implement prompt_modules.py**

Create `src/core/prompt_modules.py` with the following structure:

1. Extract `BASE_PROMPT` from `defaults.py` lines 41–50 (role definition + multi-turn support)
2. Extract `DATA_ANALYSIS_GUIDELINES` from lines 62–68
3. Extract `GENERATION_RULES` from lines 51–61 + 70–95
4. Extract `CHART_JS_RULES` from lines 96–115
5. Extract `HTML_OUTPUT_FORMAT` from lines 116–148
6. Extract `EDITING_RULES` from `slide_editing_instructions` lines 150–223
7. Add `EDITING_OUTPUT_FORMAT` — new block clarifying editing returns `<div class="slide">` fragments only
8. Move `IMAGE_SUPPORT` from `agent.py::_create_prompt`
9. Implement `build_generation_system_prompt(deck_prompt, slide_style, image_guidelines)`
10. Implement `build_editing_system_prompt(deck_prompt, slide_style, image_guidelines)`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_prompt_modules.py -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/prompt_modules.py tests/unit/test_prompt_modules.py
git commit -m "feat: extract composable prompt modules from monolithic system prompt

Create prompt_modules.py with named constants for each prompt block
and build_generation_system_prompt / build_editing_system_prompt
assembly functions. Generation excludes editing rules; editing
excludes HTML output format."
```

---

## Phase 2: Wire Mode Through Factory

### Task 2: Add `mode` parameter to agent_factory

**Files:**
- Modify: `src/services/agent_factory.py`
- Modify: `tests/unit/test_agent_factory.py`

- [ ] **Step 1: Write failing tests for mode-aware factory**

Add to `tests/unit/test_agent_factory.py`:

```python
def test_build_agent_generate_mode_excludes_editing(self):
    """Generate mode prompt should not contain editing instructions."""
    from src.services.agent_factory import _get_prompt_content
    prompts = _get_prompt_content(config, mode="generate")
    assert "slide editing" not in prompts["system_prompt"].lower()


def test_build_agent_edit_mode_excludes_generation(self):
    """Edit mode prompt should not contain DOCTYPE / full HTML format."""
    from src.services.agent_factory import _get_prompt_content
    prompts = _get_prompt_content(config, mode="edit")
    assert "<!DOCTYPE html>" not in prompts["system_prompt"]


def test_custom_system_prompt_bypasses_modules(self):
    """User-provided system_prompt override should be used as-is."""
    from src.services.agent_factory import _get_prompt_content
    config_with_override = AgentConfig(system_prompt="My custom prompt")
    prompts = _get_prompt_content(config_with_override, mode="generate")
    assert prompts["system_prompt"] == "My custom prompt"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_agent_factory.py -v --tb=short -k "mode" 2>&1 | tail -20`

Expected: FAIL — `mode` parameter not accepted yet.

- [ ] **Step 3: Update `_get_prompt_content` and `build_agent_for_request`**

In `src/services/agent_factory.py`:

1. Add `mode: str = "generate"` parameter to `_get_prompt_content`
2. When no custom override: call `build_generation_system_prompt(...)` or `build_editing_system_prompt(...)` based on mode
3. Set `slide_editing_instructions` to `None` (editing rules baked into assembled prompt)
4. Add `mode: str = "generate"` parameter to `build_agent_for_request`
5. Pass `mode` through to `_get_prompt_content`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_agent_factory.py -v --tb=short`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/agent_factory.py tests/unit/test_agent_factory.py
git commit -m "feat: add mode parameter to agent factory for prompt selection

_get_prompt_content and build_agent_for_request accept mode='generate'
or mode='edit'. Each mode assembles only the relevant prompt modules.
Custom system_prompt overrides bypass modular assembly."
```

---

### Task 3: Determine mode in ChatService before agent build

**Files:**
- Modify: `src/api/services/chat_service.py`

- [ ] **Step 1: Move RC13 slide_context synthesis before agent build**

In `send_message` and `send_message_streaming`:

1. Move slide_context synthesis (RC13 auto-detection, lines ~382–399) above `_build_agent_for_session` call
2. Determine `mode = "edit" if slide_context else "generate"` after synthesis
3. Pass `mode` to `_build_agent_for_session`

- [ ] **Step 2: Update `_build_agent_for_session`**

Accept `mode: str` parameter, pass through to `build_agent_for_request(agent_config, session_data, mode=mode)`.

- [ ] **Step 3: Verify no remaining late mode determination**

Run: `grep -n "slide_context" src/api/services/chat_service.py | head -20`

Confirm slide_context resolution happens before `_build_agent_for_session` in both code paths.

- [ ] **Step 4: Commit**

```bash
git add src/api/services/chat_service.py
git commit -m "feat: determine prompt mode in ChatService before agent build

Move RC13 slide_context synthesis above _build_agent_for_session.
Pass mode='edit' or mode='generate' through to the factory so the
agent is built with mode-specific prompts from the start."
```

---

### Task 4: Simplify `_create_prompt` in agent.py

**Files:**
- Modify: `src/services/agent.py`

- [ ] **Step 1: Simplify `_create_prompt` for pre-assembled prompts**

In `_create_prompt` (line 462):

1. Check if `system_prompt` is already fully assembled (new path)
2. If so, use it directly (only escaping `{}` for LangChain)
3. If not (legacy path), preserve the old concatenation logic

- [ ] **Step 2: Remove `IMAGE_SUPPORT` from agent.py**

The IMAGE_SUPPORT block has been moved to `prompt_modules.py`. Remove it from `_create_prompt` (it's now included in the assembled prompt).

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/unit/ -v --tb=short -x 2>&1 | tail -30`

Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add src/services/agent.py
git commit -m "refactor: simplify _create_prompt for pre-assembled prompt path

When prompt_modules assembles the full system prompt, _create_prompt
uses it directly. Legacy concatenation path preserved for backward
compatibility."
```

---

## Phase 3: Tests & Verification

### Task 5: End-to-end verification and test cleanup

**Files:**
- Modify: `tests/unit/test_prompt_modules.py` (add coverage tests)
- Modify: `tests/unit/test_agent_factory.py` (verify mode flows)

- [ ] **Step 1: Add prompt coverage assertion**

In `test_prompt_modules.py`, add a test that verifies the generation + editing prompts together cover all lines of the original monolithic prompt (no content lost during extraction).

- [ ] **Step 2: Run full backend test suite**

Run: `python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -40`

Expected: ALL PASS.

- [ ] **Step 3: Verify no remaining monolithic prompt assembly**

Run: `grep -rn "slide_editing_instructions" src/services/agent.py src/services/agent_factory.py`

Expected: Only vestigial references in the legacy path or set to `None`.

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "test: finalize prompt decoupling test coverage

Add coverage assertions for prompt module extraction completeness.
Verify mode flows end-to-end through factory and chat service."
```
