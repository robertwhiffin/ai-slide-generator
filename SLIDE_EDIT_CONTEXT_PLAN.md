# Slide-Specific Editing Implementation Plan

## Overview

Implement functionality to allow users to select specific slides and request AI modifications, similar to Cursor's `@` mention logic. The system will inject selected slide HTML into the chat context, send to the LLM for modification, parse the response, and replace the original slides with the updated versions.

## Core Design Philosophy

**LLM has creative freedom**: The LLM receives slide HTML without index markers and can return any number of slides. This enables:
- **Expansion**: User selects 2 slides → LLM returns 3-4 slides with more detail
- **Condensation**: User selects 3 slides → LLM returns 1 summarized slide
- **1:1 Modification**: User selects 2 slides → LLM returns 2 modified slides

The backend tracks which indices were selected, removes those slides, and inserts whatever the LLM returns at that position.

**Key differences from index-based approach:**
- ❌ Old: LLM receives `<slide-context index="2">` and returns `<slide-replacement index="2">`
- ✅ New: LLM receives `<slide-context>` (all slides together) and returns raw slide divs
- ❌ Old: Parser matches indices to validate 1:1 replacement
- ✅ New: Parser extracts all slides and backend handles variable-length replacement
- ❌ Old: Strict requirement that input count = output count
- ✅ New: Output count can be any number (expansion/condensation supported)

## Key Design Decisions

### Contiguous Selection Only
- Users can only select contiguous slides (e.g., slides 2-3-4)
- Non-contiguous selections (e.g., slides 2-3-5) are not allowed
- Simplifies replacement logic and user mental model

### Variable-Length Replacement Operations
- Selected slides are deleted as a contiguous block
- New slides from LLM are inserted at the same starting position
- Example: User selects slides 2,3,4 (3 slides) → LLM returns 5 slides → Original 3 deleted, new 5 inserted at position 2
- Final deck size adjusts accordingly (net change = replacement_count - original_count)

### HTML Injection Pattern
- Selected slide HTML(s) is injected into the chat message before sending to LLM
- Format: `<slide-context> (slide htmls) </slide-context>` marker
- LLM instructions updated to understand this context format

### Response Parsing Strategy
- LLM returns only HTML slide divs (consistent with existing system prompt)
- Backend parser extracts ALL `<div class="slide">` elements from response
- No index tracking in LLM response - parser just collects slides in order
- Backend knows original indices and handles the delete + insert operation

---

## Phase 1: Backend Implementation & Testing

### 1.1 Data Model Extensions

#### 1.1.1 Update `ChatRequest` Model
**File:** `src/api/models/requests.py`

Add new fields:
```python
class SlideContext(BaseModel):
    """Context about selected slides for editing."""
    indices: list[int] = Field(
        description="Contiguous list of slide indices (0-based) to edit"
    )
    slide_htmls: list[str] = Field(
        description="HTML content of selected slides in order"
    )
    
    @validator('indices')
    def validate_contiguous(cls, v):
        """Ensure indices are contiguous."""
        if len(v) < 2:
            return v
        sorted_indices = sorted(v)
        for i in range(len(sorted_indices) - 1):
            if sorted_indices[i+1] - sorted_indices[i] != 1:
                raise ValueError("Slide indices must be contiguous")
        return sorted_indices


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    message: str = Field(...)
    max_slides: int = Field(default=10, ge=1, le=50)
    slide_context: Optional[SlideContext] = Field(
        default=None,
        description="Optional context of slides to edit"
    )
```

**Validation Rules:**
- `slide_context` is optional (None for normal generation)
- When present, indices must be contiguous
- Number of `slide_htmls` must match number of `indices`

#### 1.1.2 Add Response Metadata
**File:** `src/api/models/responses.py`

Add fields to track replacement operations:
```python
class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    # ... existing fields ...
    
    replacement_info: Optional[dict] = Field(
        default=None,
        description="Information about slide replacements performed"
    )
    # replacement_info structure:
    # {
    #     "start_index": 2,           # Where replacement started
    #     "original_count": 2,        # How many slides were replaced
    #     "replacement_count": 3,     # How many slides were inserted
    #     "net_change": 1,            # Difference in slide count (+1)
    #     "operation": "edit"
    # }
```

### 1.2 Prompt Engineering

#### 1.2.1 Add Slide Editing Prompt
**File:** `config/prompts.yaml`

Add new section:
```yaml
slide_editing_instructions: |
  SLIDE EDITING MODE:
  
  When you receive slide context in the format:
  <slide-context>
    [HTML content of slide(s)]
  </slide-context>
  
  This means the user wants to modify these specific slides. Your response should:
  
  1. UNDERSTAND THE REQUEST:
     - Analyze what the user wants to change (colors, data, layout, content, etc.)
     - Review the existing HTML structure and styling
     - Maintain consistency with the overall deck design
     - The user may ask to expand, condense, split, or modify the provided slides
  
  2. RETURN REPLACEMENT HTML:
     - Return ONLY slide divs: <div class="slide">...</div>
     - You can return MORE or FEWER slides than provided (e.g., expand 2 slides into 3)
     - Each slide should be a complete, self-contained <div class="slide">...</div>
     - Maintain 1280x720 dimensions per slide
     - Do NOT wrap slides in <slide-replacement> tags - just return the raw slide divs
  
  3. FOLLOW THESE RULES:
     - Return ONLY the replacement slide HTML, not the entire deck
     - Do NOT include any explanatory text outside the slide HTML
     - Each slide must be self-contained and complete
     - Maintain brand colors, typography, and styling guidelines
     - If you need data, use query_genie_space tool first
     - You have creative freedom on how many slides to return
  
  4. EXAMPLE FLOW:
     User provides:
     <slide-context>
       <div class="slide">...quarterly sales data...</div>
       <div class="slide">...sales by region...</div>
     </slide-context>
     
     User message: "Expand these into more detailed slides with charts"
     
     Your response (3 slides from 2):
     <div class="slide">
       <h1>Q1 Sales Performance</h1>
       ...chart...
     </div>
     <div class="slide">
       <h1>Q2-Q3 Sales Growth</h1>
       ...chart...
     </div>
     <div class="slide">
       <h1>Regional Breakdown</h1>
       ...detailed regional data...
     </div>
  
  5. ERROR HANDLING:
     - If you cannot fulfill the request, return a single slide explaining why
     - If data is needed but unavailable, state this clearly in a slide
     - Ensure all returned HTML is valid
```

#### 1.2.2 Update System Prompt
**File:** `config/prompts.yaml`

Modify `system_prompt` to include conditional editing mode:
```yaml
system_prompt: |
  You are an expert data analyst and presentation creator with access to tools...
  
  [existing content...]
  
  OPERATIONAL MODES:
  
  1. GENERATION MODE (default):
     When no slide context is provided, generate a complete new slide deck following all guidelines above.
  
  2. EDITING MODE:
     When slide context is provided (marked with <slide-context> tags), you are editing existing slides.
     Follow the SLIDE EDITING MODE instructions to modify and return replacement slides.
  
  [existing content continues...]
```

### 1.3 Agent Modifications

#### 1.3.1 Extend `SlideGeneratorAgent`
**File:** `src/services/agent.py`

Add method to format slide context for injection:

```python
def _format_slide_context(self, slide_context: dict) -> str:
    """
    Format slide context for injection into user message.
    
    Args:
        slide_context: Dict with 'indices' and 'slide_htmls' keys
    
    Returns:
        Formatted string warpped with slide-context markers
    """
    context_parts = ['<slide-context>']
    
    for idx, html in zip(slide_context['indices'], slide_context['slide_htmls']):
        context_parts.append(html)
    context_parts.append('</slide-context>')
    return '\n\n'.join(context_parts)
```

Modify `generate_slides` to handle slide context:

```python
def generate_slides(
    self,
    question: str,
    session_id: str,
    max_slides: int = 10,
    slide_context: dict | None = None,  # NEW PARAMETER
    genie_space_id: str | None = None,
) -> dict[str, Any]:
    """
    Generate HTML slides from a natural language question.
    
    Args:
        question: Natural language question
        session_id: Session identifier
        max_slides: Maximum number of slides
        slide_context: Optional dict with selected slide context
                      Format: {'indices': [2,3], 'slide_htmls': ['<div...', '<div...']}
        genie_space_id: Optional Genie space ID
    
    Returns:
        Dictionary with html, messages, metadata, and replacement_info
    """
    # ... existing setup ...
    
    # Inject slide context if provided
    if slide_context:
        context_str = self._format_slide_context(slide_context)
        # Prepend context to user question
        full_question = f"{context_str}\n\n{question}"
        logger.info(
            "Slide editing mode",
            extra={
                "selected_indices": slide_context['indices'],
                "slide_count": len(slide_context['indices'])
            }
        )
    else:
        full_question = question
        logger.info("Slide generation mode")
    
    # Format input for agent
    agent_input = {
        "input": full_question,
        "max_slides": max_slides,
        "chat_history": chat_history.messages,
    }
    
    # Invoke agent
    result = self.agent_executor.invoke(agent_input)
    
    # Extract and parse response
    html_output = result["output"]
    
    # Parse response based on mode
    if slide_context:
        replacement_info = self._parse_slide_replacements(
            html_output, 
            slide_context['indices']
        )
        parsed_output = replacement_info
    else:
        replacement_info = None
        parsed_output = {"html": html_output, "type": "full_deck"}
    
    # ... rest of method ...
    
    return {
        "html": html_output,
        "messages": messages,
        "metadata": metadata,
        "session_id": session_id,
        "genie_conversation_id": session["genie_conversation_id"],
        "replacement_info": replacement_info,  # NEW
        "parsed_output": parsed_output,  # NEW
    }
```

#### 1.3.2 Add Response Parser
**File:** `src/services/agent.py`

```python
def _parse_slide_replacements(
    self, 
    llm_response: str, 
    original_indices: list[int]
) -> dict[str, Any]:
    """
    Parse LLM response to extract slide replacements.
    
    The LLM is free to return any number of slides (more or fewer than provided).
    We extract all <div class="slide"> elements and return them as replacements
    for the original contiguous block.
    
    Args:
        llm_response: Raw HTML response from LLM
        original_indices: List of original indices that were provided as context
                         (used to know where to insert replacements)
    
    Returns:
        Dict with replacement information:
        {
            'replacement_slides': ['<div class="slide">...</div>', ...],
            'original_indices': [2, 3],  # The indices that will be replaced
            'start_index': 2,             # Where to start replacement
            'original_count': 2,          # How many slides were selected
            'replacement_count': 3,       # How many slides are being returned
            'success': True,
            'error': None
        }
    
    Raises:
        AgentError: If parsing fails or no valid slides found
    """
    from bs4 import BeautifulSoup
    
    # Parse HTML response
    soup = BeautifulSoup(llm_response, 'html.parser')
    
    # Extract all slide divs
    slide_divs = soup.find_all('div', class_='slide')
    
    if not slide_divs:
        raise AgentError(
            "No slide divs found in LLM response. "
            "Expected at least one <div class='slide'>...</div>"
        )
    
    # Convert to HTML strings
    replacement_slides = [str(slide_div) for slide_div in slide_divs]
    
    # Validate each slide
    for i, slide_html in enumerate(replacement_slides):
        if not slide_html.strip():
            raise AgentError(f"Slide {i} is empty")
        if 'class="slide"' not in slide_html:
            raise AgentError(f"Slide {i} missing class='slide'")
    
    logger.info(
        "Parsed slide replacements",
        extra={
            "original_count": len(original_indices),
            "replacement_count": len(replacement_slides),
            "start_index": original_indices[0] if original_indices else 0,
        }
    )
    
    return {
        'replacement_slides': replacement_slides,
        'original_indices': original_indices,
        'start_index': original_indices[0] if original_indices else 0,
        'original_count': len(original_indices),
        'replacement_count': len(replacement_slides),
        'success': True,
        'error': None,
    }
```

### 1.4 Service Layer Updates

#### 1.4.1 Update `ChatService`
**File:** `src/api/services/chat_service.py`

Modify to handle slide context:

```python
def send_message(
    self,
    message: str,
    max_slides: int = 10,
    slide_context: dict | None = None,  # NEW
) -> dict[str, Any]:
    """
    Process a chat message and return response.
    
    Args:
        message: User's message
        max_slides: Maximum slides to generate
        slide_context: Optional slide editing context
    
    Returns:
        Dict with slide_deck, messages, and metadata
    """
    # Generate slides with agent
    result = self.agent.generate_slides(
        question=message,
        session_id=self.session_id,
        max_slides=max_slides,
        slide_context=slide_context,  # Pass through
    )
    
    # Handle based on mode
    if slide_context and result.get('replacement_info'):
        # Editing mode: apply replacements to existing deck
        slide_deck_dict = self._apply_slide_replacements(
            result['parsed_output']  # Pass the full parsed_output dict
        )
    else:
        # Generation mode: parse full HTML
        slide_deck_dict = self._parse_slide_deck(result['html'])
    
    return {
        "slide_deck": slide_deck_dict,
        "messages": result['messages'],
        "metadata": result['metadata'],
        "replacement_info": result.get('replacement_info'),
    }


def _apply_slide_replacements(
    self,
    replacement_info: dict[str, Any]
) -> dict[str, Any]:
    """
    Apply slide replacements to the current slide deck.
    
    This handles variable-length replacements:
    - Remove original slides at indices [start:start+count]
    - Insert new slides at start position
    
    Args:
        replacement_info: Dict from _parse_slide_replacements with:
            - replacement_slides: List of new slide HTML strings
            - start_index: Where to start replacement
            - original_count: How many slides to remove
            - replacement_count: How many slides to insert
    
    Returns:
        Updated slide deck as dictionary
    """
    if self.current_deck is None:
        raise ValueError("No current deck to apply replacements to")
    
    start_idx = replacement_info['start_index']
    original_count = replacement_info['original_count']
    replacement_slides = replacement_info['replacement_slides']
    
    # Validate indices
    if start_idx < 0 or start_idx >= len(self.current_deck.slides):
        raise ValueError(f"Start index {start_idx} out of range")
    if start_idx + original_count > len(self.current_deck.slides):
        raise ValueError(f"Replacement range exceeds deck size")
    
    # Remove original slides
    for _ in range(original_count):
        self.current_deck.remove_slide(start_idx)
    
    logger.info(f"Removed {original_count} slides starting at index {start_idx}")
    
    # Insert new slides
    for i, slide_html in enumerate(replacement_slides):
        new_slide = Slide(
            html=slide_html, 
            slide_id=f"slide_{start_idx + i}"
        )
        self.current_deck.insert_slide(new_slide, start_idx + i)
    
    logger.info(
        f"Inserted {len(replacement_slides)} slides at index {start_idx}",
        extra={
            "original_count": original_count,
            "replacement_count": len(replacement_slides),
            "net_change": len(replacement_slides) - original_count,
        }
    )
    
    # Convert to dict and return
    return self.current_deck.to_dict()
```

### 1.5 Testing Script

#### 1.5.1 Create Test Script
**File:** `test_slide_editing.py`

```python
"""
Test script for slide editing functionality.

This script tests the complete flow:
1. Generate initial slide deck
2. Select specific slides for editing
3. Send edit request with slide context
4. Verify replacements are applied correctly
"""

import logging
from pathlib import Path

from src.models.slide_deck import SlideDeck
from src.services.agent import create_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_slide_editing_flow():
    """Test complete slide editing flow."""
    
    print("\n" + "="*80)
    print("PHASE 1: Generate Initial Slide Deck")
    print("="*80 + "\n")
    
    # Step 1: Generate initial slides
    agent = create_agent()
    session_id = agent.create_session()
    
    initial_question = "Create 5 slides about quarterly sales performance"
    
    result = agent.generate_slides(
        question=initial_question,
        session_id=session_id,
        max_slides=5,
    )
    
    initial_html = result['html']
    print(f"Generated initial deck with {result['metadata']['tool_calls']} tool calls")
    
    # Parse into SlideDeck
    deck = SlideDeck.from_html_string(initial_html)
    print(f"Parsed deck: {len(deck)} slides")
    
    # Save initial deck
    output_dir = Path("output/slide_editing_test")
    output_dir.mkdir(parents=True, exist_ok=True)
    deck.save(output_dir / "initial_deck.html")
    print(f"Saved initial deck to {output_dir / 'initial_deck.html'}")
    
    print("\n" + "="*80)
    print("PHASE 2: Edit Specific Slides")
    print("="*80 + "\n")
    
    # Step 2: Select slides 2 and 3 for editing
    selected_indices = [2, 3]
    selected_htmls = [deck.slides[i].to_html() for i in selected_indices]
    
    slide_context = {
        'indices': selected_indices,
        'slide_htmls': selected_htmls,
    }
    
    edit_question = "Change the color scheme to blue and add more emphasis on positive trends"
    
    print(f"Editing slides {selected_indices}")
    print(f"Edit request: {edit_question}\n")
    
    # Step 3: Send edit request
    edit_result = agent.generate_slides(
        question=edit_question,
        session_id=session_id,
        max_slides=5,
        slide_context=slide_context,
    )
    
    # Step 4: Verify replacements
    replacement_info = edit_result.get('replacement_info')
    if not replacement_info:
        print("ERROR: No replacement info returned")
        return False
    
    print(f"Replacement info: {replacement_info}")
    
    if not replacement_info['success']:
        print(f"ERROR: Replacement failed: {replacement_info.get('error')}")
        return False
    
    # Step 5: Apply replacements to deck
    replacements = edit_result['parsed_output']['replacements']
    
    for idx, new_html in replacements.items():
        print(f"Replacing slide {idx}")
        from src.models.slide import Slide
        deck.slides[idx] = Slide(html=new_html, slide_id=f"slide_{idx}")
    
    # Save edited deck
    deck.save(output_dir / "edited_deck.html")
    print(f"\nSaved edited deck to {output_dir / 'edited_deck.html'}")
    
    # Step 6: Verify structure
    print("\n" + "="*80)
    print("VERIFICATION")
    print("="*80 + "\n")
    
    print(f"Total slides in deck: {len(deck)}")
    print(f"Replaced indices: {replacement_info['replaced_indices']}")
    print(f"Edit successful: {replacement_info['success']}")
    
    # Save individual slides for inspection
    slides_dir = output_dir / "slides"
    slides_dir.mkdir(exist_ok=True)
    
    for idx, slide in enumerate(deck.slides):
        slide_html = deck.render_slide(idx)
        (slides_dir / f"slide_{idx}.html").write_text(slide_html)
    
    print(f"Saved individual slides to {slides_dir}")
    
    return True


def test_edge_cases():
    """Test edge cases and error handling."""
    
    print("\n" + "="*80)
    print("EDGE CASE TESTS")
    print("="*80 + "\n")
    
    agent = create_agent()
    session_id = agent.create_session()
    
    # Test 1: Single slide edit (1:1)
    print("Test 1: Single slide edit (1:1)")
    # ... implementation ...
    
    # Test 2: Expansion (2 slides → 3+ slides)
    print("\nTest 2: Expansion - ask to expand 2 slides into more detail")
    # ... implementation ...
    
    # Test 3: Condensation (3 slides → 1 slide)
    print("\nTest 3: Condensation - ask to summarize 3 slides into 1")
    # ... implementation ...
    
    # Test 4: Non-contiguous selection (should fail validation)
    print("\nTest 4: Non-contiguous selection (should fail)")
    # ... implementation ...
    
    # Test 5: Edit without context (normal generation)
    print("\nTest 5: Normal generation without context")
    # ... implementation ...


if __name__ == "__main__":
    try:
        success = test_slide_editing_flow()
        if success:
            print("\n✅ All tests passed!")
        else:
            print("\n❌ Tests failed")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.exception("Test failed with exception")
    
    # Run edge case tests
    try:
        test_edge_cases()
    except Exception as e:
        print(f"\n❌ Edge case tests failed: {e}")
        logger.exception("Edge case test failed")
```

### 1.6 Unit Tests

#### 1.6.1 Add Parser Tests
**File:** `tests/unit/test_slide_replacements.py`

```python
"""Unit tests for slide replacement parsing."""

import pytest
from src.services.agent import SlideGeneratorAgent, AgentError


class TestSlideReplacementParsing:
    """Test slide replacement parsing logic."""
    
    def test_parse_same_number_replacements(self):
        """Test parsing when LLM returns same number of slides."""
        agent = SlideGeneratorAgent()
        
        llm_response = '''
        <div class="slide">Modified slide 1</div>
        <div class="slide">Modified slide 2</div>
        '''
        
        result = agent._parse_slide_replacements(llm_response, [2, 3])
        
        assert result['success'] is True
        assert result['original_count'] == 2
        assert result['replacement_count'] == 2
        assert result['start_index'] == 2
        assert len(result['replacement_slides']) == 2
    
    def test_parse_expansion(self):
        """Test parsing when LLM expands 2 slides into 3."""
        agent = SlideGeneratorAgent()
        
        llm_response = '''
        <div class="slide">New slide 1</div>
        <div class="slide">New slide 2</div>
        <div class="slide">New slide 3</div>
        '''
        
        result = agent._parse_slide_replacements(llm_response, [2, 3])
        
        assert result['success'] is True
        assert result['original_count'] == 2
        assert result['replacement_count'] == 3
        assert len(result['replacement_slides']) == 3
    
    def test_parse_condensation(self):
        """Test parsing when LLM condenses 3 slides into 1."""
        agent = SlideGeneratorAgent()
        
        llm_response = '''
        <div class="slide">Condensed slide</div>
        '''
        
        result = agent._parse_slide_replacements(llm_response, [2, 3, 4])
        
        assert result['success'] is True
        assert result['original_count'] == 3
        assert result['replacement_count'] == 1
        assert len(result['replacement_slides']) == 1
    
    def test_parse_no_slides_error(self):
        """Test error when no slides found in response."""
        agent = SlideGeneratorAgent()
        
        llm_response = '''
        <p>Sorry, I couldn't generate slides</p>
        '''
        
        with pytest.raises(AgentError, match="No slide divs found"):
            agent._parse_slide_replacements(llm_response, [2, 3])
    
    def test_parse_validates_slide_class(self):
        """Test that parser validates slide class attribute."""
        agent = SlideGeneratorAgent()
        
        # Valid slide
        llm_response = '''<div class="slide">Valid</div>'''
        result = agent._parse_slide_replacements(llm_response, [2])
        assert result['success'] is True
        
        # Parser should extract divs with class="slide" only
        # BeautifulSoup's find_all will handle this
```

---

## Phase 2: Frontend Implementation

### 2.1 UI Components

#### 2.1.1 Slide Selection Interface
**File:** `frontend/src/components/SlidePanel/SlideSelection.tsx`

Create new component for slide selection:

```typescript
import React, { useState } from 'react';
import { Slide } from '../../types/slide';

interface SlideSelectionProps {
  slides: Slide[];
  onSelectionChange: (selectedIndices: number[]) => void;
}

export const SlideSelection: React.FC<SlideSelectionProps> = ({
  slides,
  onSelectionChange,
}) => {
  const [selectedIndices, setSelectedIndices] = useState<number[]>([]);

  const handleSlideClick = (index: number, event: React.MouseEvent) => {
    if (event.shiftKey && selectedIndices.length > 0) {
      // Shift-click: select range
      const lastSelected = selectedIndices[selectedIndices.length - 1];
      const start = Math.min(lastSelected, index);
      const end = Math.max(lastSelected, index);
      const range = Array.from({ length: end - start + 1 }, (_, i) => start + i);
      setSelectedIndices(range);
      onSelectionChange(range);
    } else if (event.ctrlKey || event.metaKey) {
      // Ctrl/Cmd-click: toggle selection (only if contiguous)
      const newSelection = selectedIndices.includes(index)
        ? selectedIndices.filter(i => i !== index)
        : [...selectedIndices, index].sort((a, b) => a - b);
      
      // Validate contiguous
      if (isContiguous(newSelection)) {
        setSelectedIndices(newSelection);
        onSelectionChange(newSelection);
      } else {
        // Show error toast
        console.warn('Selection must be contiguous');
      }
    } else {
      // Regular click: single selection
      setSelectedIndices([index]);
      onSelectionChange([index]);
    }
  };

  const isContiguous = (indices: number[]): boolean => {
    if (indices.length <= 1) return true;
    const sorted = [...indices].sort((a, b) => a - b);
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i] - sorted[i - 1] !== 1) return false;
    }
    return true;
  };

  return (
    <div className="slide-selection">
      {slides.map((slide, index) => (
        <div
          key={slide.slide_id}
          className={`slide-thumbnail ${
            selectedIndices.includes(index) ? 'selected' : ''
          }`}
          onClick={(e) => handleSlideClick(index, e)}
        >
          <div className="slide-number">{index + 1}</div>
          <div 
            className="slide-preview"
            dangerouslySetInnerHTML={{ __html: slide.html }}
          />
        </div>
      ))}
    </div>
  );
};
```

#### 2.1.2 Selection Badge Component
**File:** `frontend/src/components/ChatPanel/SelectionBadge.tsx`

Show which slides are currently selected:

```typescript
import React from 'react';

interface SelectionBadgeProps {
  selectedIndices: number[];
  onClear: () => void;
}

export const SelectionBadge: React.FC<SelectionBadgeProps> = ({
  selectedIndices,
  onClear,
}) => {
  if (selectedIndices.length === 0) return null;

  const rangeText = selectedIndices.length === 1
    ? `Slide ${selectedIndices[0] + 1}`
    : `Slides ${selectedIndices[0] + 1}-${selectedIndices[selectedIndices.length - 1] + 1}`;

  return (
    <div className="selection-badge">
      <span className="badge-icon">📎</span>
      <span className="badge-text">Editing: {rangeText}</span>
      <button 
        className="badge-clear"
        onClick={onClear}
        aria-label="Clear selection"
      >
        ×
      </button>
    </div>
  );
};
```

### 2.2 State Management

#### 2.2.1 Update App State
**File:** `frontend/src/App.tsx`

Add state for slide selection:

```typescript
const [selectedSlideIndices, setSelectedSlideIndices] = useState<number[]>([]);

const handleSelectionChange = (indices: number[]) => {
  setSelectedSlideIndices(indices);
};

const clearSelection = () => {
  setSelectedSlideIndices([]);
};
```

#### 2.2.2 Create Selection Context
**File:** `frontend/src/contexts/SelectionContext.tsx`

```typescript
import React, { createContext, useContext, useState } from 'react';
import { Slide } from '../types/slide';

interface SelectionContextType {
  selectedIndices: number[];
  selectedSlides: Slide[];
  setSelection: (indices: number[], slides: Slide[]) => void;
  clearSelection: () => void;
  hasSelection: boolean;
}

const SelectionContext = createContext<SelectionContextType | undefined>(undefined);

export const SelectionProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [selectedIndices, setSelectedIndices] = useState<number[]>([]);
  const [selectedSlides, setSelectedSlides] = useState<Slide[]>([]);

  const setSelection = (indices: number[], slides: Slide[]) => {
    setSelectedIndices(indices);
    setSelectedSlides(slides);
  };

  const clearSelection = () => {
    setSelectedIndices([]);
    setSelectedSlides([]);
  };

  return (
    <SelectionContext.Provider
      value={{
        selectedIndices,
        selectedSlides,
        setSelection,
        clearSelection,
        hasSelection: selectedIndices.length > 0,
      }}
    >
      {children}
    </SelectionContext.Provider>
  );
};

export const useSelection = () => {
  const context = useContext(SelectionContext);
  if (!context) {
    throw new Error('useSelection must be used within SelectionProvider');
  }
  return context;
};
```

### 2.3 API Integration

#### 2.3.1 Update API Service
**File:** `frontend/src/services/api.ts`

Extend `sendMessage` to include slide context:

```typescript
export interface SlideContext {
  indices: number[];
  slide_htmls: string[];
}

export interface SendMessageParams {
  message: string;
  maxSlides?: number;
  slideContext?: SlideContext;
}

export const sendMessage = async ({
  message,
  maxSlides = 10,
  slideContext,
}: SendMessageParams): Promise<ApiResponse> => {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      max_slides: maxSlides,
      slide_context: slideContext,
    }),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
};
```

#### 2.3.2 Update Message Sending Logic
**File:** `frontend/src/components/ChatPanel/ChatPanel.tsx`

```typescript
const handleSendMessage = async (message: string) => {
  // Check if slides are selected
  const slideContext = selectedIndices.length > 0
    ? {
        indices: selectedIndices,
        slide_htmls: selectedIndices.map(i => slideDeck.slides[i].html),
      }
    : undefined;

  try {
    const response = await sendMessage({
      message,
      maxSlides: 10,
      slideContext,
    });

    // Handle response
    if (response.replacement_info) {
      // Editing mode: apply replacements
      applyReplacements(response);
    } else {
      // Generation mode: replace entire deck
      setSlideDeck(response.slide_deck);
    }

    // Clear selection after successful edit
    if (slideContext) {
      clearSelection();
    }
  } catch (error) {
    console.error('Failed to send message:', error);
  }
};
```

### 2.4 Replacement Application

#### 2.4.1 Create Replacement Handler
**File:** `frontend/src/utils/slideReplacements.ts`

```typescript
import { SlideDeck, Slide } from '../types/slide';

export interface ReplacementInfo {
  start_index: number;
  original_count: number;
  replacement_count: number;
  net_change: number;
  operation: string;
}

export interface ReplacementResponse {
  slide_deck: SlideDeck;
  replacement_info: ReplacementInfo;
}

export const applyReplacements = (
  currentDeck: SlideDeck,
  response: ReplacementResponse
): SlideDeck => {
  const { start_index, original_count } = response.replacement_info;
  
  // Clone the current deck
  const newDeck = { ...currentDeck };
  const newSlides = [...currentDeck.slides];
  
  // Remove original slides
  newSlides.splice(start_index, original_count);
  
  // Insert replacement slides at the same position
  const replacementSlides = response.slide_deck.slides;
  newSlides.splice(start_index, 0, ...replacementSlides);
  
  // Update deck
  newDeck.slides = newSlides;
  newDeck.slide_count = newSlides.length;
  
  return newDeck;
};

export const getReplacementSummary = (info: ReplacementInfo): string => {
  const { original_count, replacement_count, net_change } = info;
  
  if (net_change === 0) {
    return `Replaced ${original_count} slide${original_count > 1 ? 's' : ''}`;
  } else if (net_change > 0) {
    return `Expanded ${original_count} slide${original_count > 1 ? 's' : ''} into ${replacement_count} (+${net_change})`;
  } else {
    return `Condensed ${original_count} slide${original_count > 1 ? 's' : ''} into ${replacement_count} (${net_change})`;
  }
};
```

### 2.5 UX Enhancements

#### 2.5.1 Visual Feedback
- Highlight selected slides with border/background
- Show selection badge in chat input area
- Disable slide navigation during editing
- Show loading state during replacement

#### 2.5.2 Error Handling
- Validate contiguous selection in UI
- Show error message for non-contiguous attempts
- Handle backend errors gracefully
- Provide retry mechanism

#### 2.5.3 Keyboard Shortcuts
- `Cmd/Ctrl + Click`: Add to selection
- `Shift + Click`: Select range
- `Escape`: Clear selection
- `Enter`: Send message with context

---

## Testing Strategy

### Phase 1 Testing
1. **Unit Tests**: Parser logic, validation, edge cases
2. **Integration Tests**: Agent with slide context, replacement flow
3. **Manual Testing**: Run `test_slide_editing.py` script
4. **Output Inspection**: Verify HTML structure of replaced slides

### Phase 2 Testing
1. **Component Tests**: SlideSelection, SelectionBadge
2. **Integration Tests**: API calls with slide context
3. **E2E Tests**: Full user flow from selection to replacement
4. **Manual QA**: Test various edit scenarios

### Test Scenarios
1. **Single Slide Edit (1:1)**: Select one slide, modify color
2. **Multi-Slide Edit (1:1)**: Select 3 slides, change layout (returns 3)
3. **Expansion (1:N)**: Select 2 slides, expand into 4 slides
4. **Condensation (N:1)**: Select 3 slides, condense into 1 slide
5. **Content Replacement**: Replace data in slides
6. **Style Changes**: Modify typography, colors across multiple slides
7. **Data-Driven Edit**: Edit slides requiring Genie data
8. **Error Cases**: Invalid selection, parsing failures, no slides returned

---

## Success Criteria

### Phase 1
- ✅ Backend accepts slide context in request
- ✅ Agent formats slide context for LLM
- ✅ LLM returns properly formatted replacements
- ✅ Parser extracts replacement HTML correctly
- ✅ Replacements apply to correct slide indices
- ✅ Test script runs successfully
- ✅ Unit tests pass

### Phase 2
- ✅ Users can select contiguous slides
- ✅ Selection UI shows clear visual feedback
- ✅ Chat input shows selected slide context
- ✅ API sends slide context correctly
- ✅ Replacements apply immediately in UI
- ✅ Error states handled gracefully
- ✅ Keyboard shortcuts work

---

## Implementation Timeline

### Phase 1: Backend (Estimated 2-3 days)
- Day 1: Data models, prompt engineering
- Day 2: Agent modifications, parser implementation
- Day 3: Testing script, unit tests, debugging

### Phase 2: Frontend (Estimated 3-4 days)
- Day 1: Selection UI components
- Day 2: State management, context
- Day 3: API integration, replacement logic
- Day 4: UX polish, error handling, testing

**Total Estimated Time**: 5-7 days

---

## Risks & Mitigations

### Risk 1: LLM Doesn't Follow Format
**Mitigation**: Parser extracts any `<div class="slide">` elements found, very forgiving

### Risk 2: Context Window Overflow
**Mitigation**: Limit selection to 5 slides max, compress HTML if needed

### Risk 3: Inconsistent Styling After Edit
**Mitigation**: Provide clear style guidelines in prompt, validate output structure

### Risk 4: Variable-Length Replacements Confuse Users
**Mitigation**: Show clear feedback (e.g., "Expanded 2 slides into 3") and allow undo

### Risk 5: LLM Returns Unexpected Slide Count
**Mitigation**: Accept any count, show summary to user, provide undo option

---

## Future Enhancements

### Post-MVP Features
1. **Non-contiguous Selection**: Allow gaps with more complex logic
2. **Slide Insertion**: Insert new slides at selected position
3. **Slide Deletion**: Remove selected slides
4. **Undo/Redo**: Track edit history with full state snapshots
5. **Diff View**: Show before/after comparison for edits
6. **Batch Operations**: Apply same edit to multiple slide sets
7. **Template Reuse**: Save edited slides as templates
8. **Smart Suggestions**: Suggest "Expand" or "Condense" based on selection
9. **Preview Mode**: Show proposed changes before applying
10. **Edit History**: Track all edits made to each slide

### Optimization Opportunities
1. **Context Compression**: Minimize HTML sent to LLM
2. **Incremental Updates**: Only send changed elements
3. **Client-Side Parsing**: Parse replacements in browser
4. **Caching**: Cache frequent edit patterns

---

## Appendix

### A. Example Request/Response

**Request (1:1 Replacement):**
```json
{
  "message": "Make these slides use blue color scheme and add more charts",
  "max_slides": 10,
  "slide_context": {
    "indices": [2, 3],
    "slide_htmls": [
      "<div class=\"slide\">...existing slide 2...</div>",
      "<div class=\"slide\">...existing slide 3...</div>"
    ]
  }
}
```

**Response (1:1 Replacement):**
```json
{
  "slide_deck": {
    "slides": [
      {"index": 0, "html": "<div class=\"slide\">...modified blue slide...</div>"},
      {"index": 1, "html": "<div class=\"slide\">...modified blue slide...</div>"}
    ]
  },
  "messages": [...],
  "metadata": {...},
  "replacement_info": {
    "start_index": 2,
    "original_count": 2,
    "replacement_count": 2,
    "net_change": 0,
    "operation": "edit"
  }
}
```

**Request (Expansion):**
```json
{
  "message": "Expand these two slides into more detailed slides",
  "slide_context": {
    "indices": [2, 3],
    "slide_htmls": ["...", "..."]
  }
}
```

**Response (Expansion - 2 slides → 4 slides):**
```json
{
  "replacement_info": {
    "start_index": 2,
    "original_count": 2,
    "replacement_count": 4,
    "net_change": 2,
    "operation": "edit"
  }
}
```

### B. Prompt Examples

**User with context (Single slide edit):**
```
<slide-context>
<div class="slide">
  <h1>Sales Overview</h1>
  <p>Q3 sales data...</p>
</div>
</slide-context>

Make this slide use Lava 600 (#EB4A34) for headers and add a bar chart
```

**LLM response (Single slide):**
```html
<div class="slide">
  <h1 style="color: #EB4A34;">Sales Overview</h1>
  <p>Q3 sales data showing strong growth...</p>
  <canvas id="salesChart"></canvas>
  <script>
    const canvas = document.getElementById('salesChart');
    if (canvas) {
      // Chart.js code...
    }
  </script>
</div>
```

**User with context (Expansion request):**
```
<slide-context>
<div class="slide">
  <h1>Quarterly Performance</h1>
  <p>All quarters summarized...</p>
</div>
</slide-context>

Break this into separate slides for each quarter with more detail
```

**LLM response (1 slide → 4 slides):**
```html
<div class="slide">
  <h1>Q1 Performance</h1>
  <p>Detailed Q1 analysis...</p>
</div>
<div class="slide">
  <h1>Q2 Performance</h1>
  <p>Detailed Q2 analysis...</p>
</div>
<div class="slide">
  <h1>Q3 Performance</h1>
  <p>Detailed Q3 analysis...</p>
</div>
<div class="slide">
  <h1>Q4 Performance</h1>
  <p>Detailed Q4 analysis...</p>
</div>
```

### C. Error Messages

| Error | User Message | Technical Detail |
|-------|-------------|------------------|
| Non-contiguous selection | "Please select slides in a continuous range (e.g., 2-3-4)" | Validation failed in ChatRequest |
| No slides in response | "AI didn't return any slides. Please try again with a clearer request." | Parser found no `<div class="slide">` elements |
| Invalid HTML | "Generated slides have formatting issues. Please rephrase your request." | Parser validation failed on slide structure |
| Replacement range error | "Cannot apply changes to selected slides. Please refresh and try again." | Start index or count out of range |

---

## Summary of Design Approach

### What Makes This Design Flexible

1. **No Index Coupling**: LLM doesn't need to track or return indices
2. **Simple Parsing**: Just extract all `<div class="slide">` elements
3. **Natural Requests**: Users can say "expand this" or "combine these" naturally
4. **Minimal Validation**: Only validate slide structure, not count matching
5. **Future-Proof**: Easy to add slide insertion/deletion later

### Implementation Highlights

| Component | Key Feature |
|-----------|-------------|
| **Prompt** | Explicitly states LLM can return any number of slides |
| **Parser** | Extracts slides without index matching |
| **SlideDeck** | Already has `remove_slide()` and `insert_slide()` methods |
| **Frontend** | Shows net change feedback ("+2 slides", "-1 slide") |
| **Metadata** | Tracks original_count vs replacement_count |

---

## Questions for Review

1. Should we support slide insertion/deletion in Phase 1, or strictly replacement?
   - **Decision**: Variable-length replacement (which is delete + insert)

2. What's the maximum number of slides that can be selected at once?
   - **Recommendation**: Limit to 5 to avoid context overflow

3. Should selection persist across chat messages?
   - **Decision**: Clear selection after successful edit

4. How to handle unexpected slide counts from LLM?
   - **Decision**: Accept any count, show clear feedback to user

5. Should we show a diff/preview before applying replacements?
   - **Decision**: Phase 3 feature, not MVP - apply immediately with undo option
