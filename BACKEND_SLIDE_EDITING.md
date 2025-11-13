# Backend Implementation: Slide-Specific Editing

## Overview

Implement backend functionality to support slide-specific editing with variable-length replacements. The LLM receives selected slide HTML and can return any number of slides (expansion, condensation, or 1:1 modification).

**Key Deliverable**: Interactive test script demonstrating the complete editing flow.

## Core Design Principles

1. **LLM Creative Freedom**: No index markers in LLM context; can return any number of slides
2. **Contiguous Selection Only**: Users select consecutive slides (e.g., 2-3-4, not 2-3-5)
3. **Variable-Length Replacement**: Delete original block, insert new slides at same position
4. **Simple Parsing**: Extract all `<div class="slide">` elements without index matching

## Implementation Phases

### Phase 1: Data Models

#### 1.1 Request Model Extension
**File**: `src/api/models/requests.py`

Add `SlideContext` model:
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
```

Update `ChatRequest`:
```python
class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    message: str = Field(...)
    max_slides: int = Field(default=10, ge=1, le=50)
    slide_context: Optional[SlideContext] = Field(
        default=None,
        description="Optional context of slides to edit"
    )
```

**Validation Rules**:
- `slide_context` is optional (None for normal generation)
- When present, indices must be contiguous
- Number of `slide_htmls` must match number of `indices`

#### 1.2 Response Model Extension
**File**: `src/api/models/responses.py`

Add metadata to track replacements:
```python
class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    # ... existing fields ...
    
    replacement_info: Optional[dict] = Field(
        default=None,
        description="Information about slide replacements performed"
    )
    # Structure:
    # {
    #     "start_index": 2,           # Where replacement started
    #     "original_count": 2,        # How many slides were replaced
    #     "replacement_count": 3,     # How many slides were inserted
    #     "net_change": 1,            # Difference in slide count
    #     "operation": "edit"
    # }
```

### Phase 2: Prompt Engineering

#### 2.1 Slide Editing Instructions
**File**: `config/prompts.yaml`

Add new `slide_editing_instructions` section:

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

#### 2.2 System Prompt Update
**File**: `config/prompts.yaml`

Add conditional mode to existing `system_prompt`:

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

### Phase 3: Agent Modifications

#### 3.1 Slide Context Formatting
**File**: `src/services/agent.py`

Add method to format slide context:

```python
def _format_slide_context(self, slide_context: dict) -> str:
    """
    Format slide context for injection into user message.
    
    Args:
        slide_context: Dict with 'indices' and 'slide_htmls' keys
    
    Returns:
        Formatted string wrapped with slide-context markers
    """
    context_parts = ['<slide-context>']
    
    for html in slide_context['slide_htmls']:
        context_parts.append(html)
    
    context_parts.append('</slide-context>')
    return '\n\n'.join(context_parts)
```

#### 3.2 Generate Slides Extension
**File**: `src/services/agent.py`

Modify `generate_slides` method signature and implementation:

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
    
    # ... existing message/metadata extraction ...
    
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

#### 3.3 Replacement Parser
**File**: `src/services/agent.py`

Add new parsing method:

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
    
    Returns:
        Dict with replacement information:
        {
            'replacement_slides': ['<div class="slide">...</div>', ...],
            'original_indices': [2, 3],
            'start_index': 2,
            'original_count': 2,
            'replacement_count': 3,
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

### Phase 4: Service Layer

#### 4.1 ChatService Updates
**File**: `src/api/services/chat_service.py`

Extend `send_message` method:

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
        slide_context=slide_context,
    )
    
    # Handle based on mode
    if slide_context and result.get('replacement_info'):
        # Editing mode: apply replacements to existing deck
        slide_deck_dict = self._apply_slide_replacements(
            result['parsed_output']
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
```

Add replacement application method:

```python
def _apply_slide_replacements(
    self,
    replacement_info: dict[str, Any]
) -> dict[str, Any]:
    """
    Apply slide replacements to the current slide deck.
    
    Handles variable-length replacements:
    - Remove original slides at indices [start:start+count]
    - Insert new slides at start position
    
    Args:
        replacement_info: Dict from _parse_slide_replacements
    
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
    from src.models.slide import Slide
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
    
    return self.current_deck.to_dict()
```

**Note**: Route handler updates (`src/api/routes/chat.py`) are **intentionally deferred to the Frontend Phase**. The interactive test script calls the agent directly, so API endpoint changes are not needed or tested in the backend phase. This keeps the backend focused on core logic that is actually validated.

### Phase 5: Interactive Test Script (Key Deliverable)

#### 5.1 Test Script Structure
**File**: `test_slide_editing_interactive.py`

Create comprehensive interactive test script:

```python
"""
Interactive test script for slide editing functionality.

This script demonstrates the complete editing flow:
1. Generate initial slide deck
2. Display slides with indices
3. Prompt user to select slides for editing
4. Send edit request with slide context
5. Display results and verify replacements
6. Save all outputs for inspection
"""

import logging
from pathlib import Path
from datetime import datetime
from src.models.slide_deck import SlideDeck
from src.services.agent import create_agent
from src.models.slide import Slide

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def print_header(title: str):
    """Print formatted section header."""
    print("\n" + "="*80)
    print(f"  {title}")
    print("="*80 + "\n")


def print_slide_summary(deck: SlideDeck):
    """Print summary of slides in deck."""
    print(f"Deck contains {len(deck)} slides:\n")
    for i, slide in enumerate(deck.slides):
        # Extract title from slide HTML (simple extraction)
        html = slide.to_html()
        if '<h1>' in html:
            title = html.split('<h1>')[1].split('</h1>')[0][:50]
        elif '<h2>' in html:
            title = html.split('<h2>')[1].split('</h2>')[0][:50]
        else:
            title = "Untitled slide"
        print(f"  [{i}] {title}")


def test_1to1_replacement():
    """Test 1:1 slide replacement (same number in and out)."""
    print_header("TEST 1: 1:1 Replacement (2 slides → 2 slides)")
    
    # Create agent and session
    agent = create_agent()
    session_id = agent.create_session()
    
    # Generate initial deck
    print("Generating initial 5-slide deck about quarterly sales...")
    result = agent.generate_slides(
        question="Create 5 slides about quarterly sales performance with key metrics",
        session_id=session_id,
        max_slides=5,
    )
    
    deck = SlideDeck.from_html_string(result['html'])
    print(f"✓ Generated {len(deck)} slides")
    print_slide_summary(deck)
    
    # Save initial deck
    output_dir = Path("output/slide_editing_test")
    output_dir.mkdir(parents=True, exist_ok=True)
    deck.save(output_dir / "test1_initial.html")
    
    # Select slides for editing
    selected_indices = [2, 3]
    selected_htmls = [deck.slides[i].to_html() for i in selected_indices]
    
    print(f"\nSelecting slides {selected_indices} for editing...")
    print(f"Edit request: Change to blue color scheme\n")
    
    # Send edit request
    slide_context = {
        'indices': selected_indices,
        'slide_htmls': selected_htmls,
    }
    
    edit_result = agent.generate_slides(
        question="Change these slides to use a blue color scheme (#1E40AF for headers)",
        session_id=session_id,
        max_slides=5,
        slide_context=slide_context,
    )
    
    # Display replacement info
    replacement_info = edit_result['replacement_info']
    print("Replacement Results:")
    print(f"  Start index: {replacement_info['start_index']}")
    print(f"  Original count: {replacement_info['original_count']}")
    print(f"  Replacement count: {replacement_info['replacement_count']}")
    print(f"  Net change: {replacement_info['replacement_count'] - replacement_info['original_count']}")
    print(f"  Success: {replacement_info['success']}")
    
    # Apply replacements to deck
    start = replacement_info['start_index']
    count = replacement_info['original_count']
    
    # Remove original slides
    for _ in range(count):
        deck.remove_slide(start)
    
    # Insert replacement slides
    for i, slide_html in enumerate(replacement_info['replacement_slides']):
        new_slide = Slide(html=slide_html, slide_id=f"slide_{start + i}")
        deck.insert_slide(new_slide, start + i)
    
    print(f"\n✓ Applied replacements")
    print_slide_summary(deck)
    
    # Save edited deck
    deck.save(output_dir / "test1_edited_1to1.html")
    print(f"\n✓ Saved to {output_dir / 'test1_edited_1to1.html'}")
    
    return True


def test_expansion():
    """Test expansion (2 slides → 4 slides)."""
    print_header("TEST 2: Expansion (2 slides → 4 slides)")
    
    agent = create_agent()
    session_id = agent.create_session()
    
    # Generate initial deck
    print("Generating initial 4-slide deck...")
    result = agent.generate_slides(
        question="Create 4 slides: title, overview of annual sales, regional breakdown, conclusion",
        session_id=session_id,
        max_slides=4,
    )
    
    deck = SlideDeck.from_html_string(result['html'])
    print(f"✓ Generated {len(deck)} slides")
    print_slide_summary(deck)
    
    output_dir = Path("output/slide_editing_test")
    deck.save(output_dir / "test2_initial.html")
    
    # Select slides 1 and 2 (overview and regional)
    selected_indices = [1, 2]
    selected_htmls = [deck.slides[i].to_html() for i in selected_indices]
    
    print(f"\nSelecting slides {selected_indices} for expansion...")
    print(f"Edit request: Expand into more detailed slides\n")
    
    slide_context = {
        'indices': selected_indices,
        'slide_htmls': selected_htmls,
    }
    
    edit_result = agent.generate_slides(
        question="Expand these 2 slides into 4 more detailed slides with quarterly breakdowns",
        session_id=session_id,
        max_slides=10,
        slide_context=slide_context,
    )
    
    replacement_info = edit_result['replacement_info']
    print("Replacement Results:")
    print(f"  Original: {replacement_info['original_count']} slides")
    print(f"  Replacement: {replacement_info['replacement_count']} slides")
    print(f"  Net change: +{replacement_info['replacement_count'] - replacement_info['original_count']}")
    
    # Apply replacements
    start = replacement_info['start_index']
    count = replacement_info['original_count']
    
    for _ in range(count):
        deck.remove_slide(start)
    
    for i, slide_html in enumerate(replacement_info['replacement_slides']):
        new_slide = Slide(html=slide_html, slide_id=f"slide_{start + i}")
        deck.insert_slide(new_slide, start + i)
    
    print(f"\n✓ Deck now has {len(deck)} slides (was {4})")
    print_slide_summary(deck)
    
    deck.save(output_dir / "test2_edited_expansion.html")
    print(f"\n✓ Saved to {output_dir / 'test2_edited_expansion.html'}")
    
    return True


def test_condensation():
    """Test condensation (3 slides → 1 slide)."""
    print_header("TEST 3: Condensation (3 slides → 1 slide)")
    
    agent = create_agent()
    session_id = agent.create_session()
    
    # Generate initial deck with verbose slides
    print("Generating initial 6-slide deck...")
    result = agent.generate_slides(
        question="Create 6 slides about product features, with slides 2-4 covering different feature categories",
        session_id=session_id,
        max_slides=6,
    )
    
    deck = SlideDeck.from_html_string(result['html'])
    print(f"✓ Generated {len(deck)} slides")
    print_slide_summary(deck)
    
    output_dir = Path("output/slide_editing_test")
    deck.save(output_dir / "test3_initial.html")
    
    # Select 3 slides to condense
    selected_indices = [2, 3, 4]
    selected_htmls = [deck.slides[i].to_html() for i in selected_indices]
    
    print(f"\nSelecting slides {selected_indices} for condensation...")
    print(f"Edit request: Condense into a single summary slide\n")
    
    slide_context = {
        'indices': selected_indices,
        'slide_htmls': selected_htmls,
    }
    
    edit_result = agent.generate_slides(
        question="Condense these 3 feature slides into 1 comprehensive summary slide",
        session_id=session_id,
        max_slides=6,
        slide_context=slide_context,
    )
    
    replacement_info = edit_result['replacement_info']
    print("Replacement Results:")
    print(f"  Original: {replacement_info['original_count']} slides")
    print(f"  Replacement: {replacement_info['replacement_count']} slides")
    print(f"  Net change: {replacement_info['replacement_count'] - replacement_info['original_count']}")
    
    # Apply replacements
    start = replacement_info['start_index']
    count = replacement_info['original_count']
    
    for _ in range(count):
        deck.remove_slide(start)
    
    for i, slide_html in enumerate(replacement_info['replacement_slides']):
        new_slide = Slide(html=slide_html, slide_id=f"slide_{start + i}")
        deck.insert_slide(new_slide, start + i)
    
    print(f"\n✓ Deck now has {len(deck)} slides (was {6})")
    print_slide_summary(deck)
    
    deck.save(output_dir / "test3_edited_condensation.html")
    print(f"\n✓ Saved to {output_dir / 'test3_edited_condensation.html'}")
    
    return True


def test_interactive_mode():
    """Interactive mode where user can repeatedly edit slides."""
    print_header("TEST 4: Interactive Mode")
    
    agent = create_agent()
    session_id = agent.create_session()
    
    # Generate initial deck
    initial_prompt = input("Enter initial deck prompt (or press Enter for default): ").strip()
    if not initial_prompt:
        initial_prompt = "Create 5 slides about data engineering best practices"
    
    print(f"\nGenerating deck from: '{initial_prompt}'...")
    result = agent.generate_slides(
        question=initial_prompt,
        session_id=session_id,
        max_slides=10,
    )
    
    deck = SlideDeck.from_html_string(result['html'])
    print(f"✓ Generated {len(deck)} slides")
    
    output_dir = Path("output/slide_editing_test/interactive")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    iteration = 0
    deck.save(output_dir / f"deck_v{iteration}.html")
    
    while True:
        print("\n" + "-"*80)
        print_slide_summary(deck)
        print("-"*80)
        
        # Get user input
        print("\nOptions:")
        print("  1. Edit slides (enter indices like '2,3' or '0-2')")
        print("  2. Add new slides (not implemented in Phase 1)")
        print("  3. Save and exit")
        
        choice = input("\nChoice: ").strip()
        
        if choice == "3":
            print("\n✓ Exiting interactive mode")
            break
        
        if choice == "1":
            # Get indices
            indices_input = input("Enter slide indices (e.g., '2,3' or '1-3'): ").strip()
            
            # Parse indices
            if '-' in indices_input:
                start, end = map(int, indices_input.split('-'))
                selected_indices = list(range(start, end + 1))
            else:
                selected_indices = [int(x.strip()) for x in indices_input.split(',')]
            
            # Validate
            if any(i >= len(deck) or i < 0 for i in selected_indices):
                print("❌ Invalid indices")
                continue
            
            # Get edit instruction
            edit_instruction = input("What changes do you want to make? ").strip()
            if not edit_instruction:
                print("❌ No instruction provided")
                continue
            
            # Prepare context
            selected_htmls = [deck.slides[i].to_html() for i in selected_indices]
            slide_context = {
                'indices': selected_indices,
                'slide_htmls': selected_htmls,
            }
            
            # Execute edit
            print("\nProcessing edit...")
            edit_result = agent.generate_slides(
                question=edit_instruction,
                session_id=session_id,
                max_slides=10,
                slide_context=slide_context,
            )
            
            # Apply replacements
            replacement_info = edit_result['replacement_info']
            start = replacement_info['start_index']
            count = replacement_info['original_count']
            
            for _ in range(count):
                deck.remove_slide(start)
            
            for i, slide_html in enumerate(replacement_info['replacement_slides']):
                new_slide = Slide(html=slide_html, slide_id=f"slide_{start + i}")
                deck.insert_slide(new_slide, start + i)
            
            print(f"✓ Replaced {count} slides with {replacement_info['replacement_count']} slides")
            
            # Save iteration
            iteration += 1
            deck.save(output_dir / f"deck_v{iteration}.html")
            print(f"✓ Saved version {iteration}")


def main():
    """Run all tests."""
    print_header("Slide Editing Backend Tests")
    
    print("Available tests:")
    print("  1. Test 1:1 Replacement (2 slides → 2 slides)")
    print("  2. Test Expansion (2 slides → 4 slides)")
    print("  3. Test Condensation (3 slides → 1 slide)")
    print("  4. Interactive Mode (manual testing)")
    print("  5. Run all automated tests")
    
    choice = input("\nSelect test (1-5): ").strip()
    
    try:
        if choice == "1":
            test_1to1_replacement()
        elif choice == "2":
            test_expansion()
        elif choice == "3":
            test_condensation()
        elif choice == "4":
            test_interactive_mode()
        elif choice == "5":
            test_1to1_replacement()
            test_expansion()
            test_condensation()
            print_header("All Tests Complete")
            print("Check output/slide_editing_test/ for results")
        else:
            print("Invalid choice")
    
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        logger.exception("Test error")


if __name__ == "__main__":
    main()
```

### Phase 6: Unit Tests

#### 6.1 Parser Unit Tests
**File**: `tests/unit/test_slide_replacements.py`

```python
"""Unit tests for slide replacement parsing."""

import pytest
from src.services.agent import SlideGeneratorAgent, AgentError


class TestSlideReplacementParsing:
    """Test slide replacement parsing logic."""
    
    def test_parse_same_number_replacements(self):
        """Test parsing when LLM returns same number of slides."""
        # Implementation details
        pass
    
    def test_parse_expansion(self):
        """Test parsing when LLM expands 2 slides into 3."""
        pass
    
    def test_parse_condensation(self):
        """Test parsing when LLM condenses 3 slides into 1."""
        pass
    
    def test_parse_no_slides_error(self):
        """Test error when no slides found in response."""
        pass


class TestSlideContextValidation:
    """Test slide context validation."""
    
    def test_contiguous_validation_passes(self):
        """Test that contiguous indices pass validation."""
        pass
    
    def test_non_contiguous_validation_fails(self):
        """Test that non-contiguous indices fail validation."""
        pass
```

## Testing Strategy

### Validation Checklist

- [ ] Data models accept slide context correctly
- [ ] Non-contiguous indices are rejected
- [ ] Agent formats slide context with proper markers
- [ ] LLM receives slide HTML in context
- [ ] Parser extracts all slide divs correctly
- [ ] Parser handles variable slide counts
- [ ] Replacement slides apply to correct indices
- [ ] Deck size adjusts correctly after replacement
- [ ] All outputs save properly

### Test Scenarios

1. **1:1 Replacement**: Select 2 slides, modify styling, get 2 back
2. **Expansion**: Select 2 slides, request expansion, get 4 back
3. **Condensation**: Select 3 slides, request summary, get 1 back
4. **Single Slide Edit**: Select 1 slide, modify content
5. **Error Handling**: Invalid indices, no slides returned, malformed HTML

### Output Inspection

For each test, verify:
- Initial deck HTML saved
- Edited deck HTML saved
- Individual slide HTML files saved
- Replacement metadata logged
- Slide count changes correctly

## Success Criteria

### Functional Requirements
- ✅ Backend accepts `slide_context` in requests
- ✅ Agent injects slide HTML into LLM prompt
- ✅ LLM returns valid replacement slides
- ✅ Parser extracts all `<div class="slide">` elements
- ✅ Variable-length replacements work (expansion/condensation/1:1)
- ✅ Slides apply to correct indices in deck
- ✅ Interactive test script demonstrates all scenarios

### Code Quality
- ✅ Type hints on all new methods
- ✅ Comprehensive docstrings
- ✅ Logging at appropriate levels
- ✅ Error handling with clear messages
- ✅ Unit test coverage for core logic

## Timeline

**Estimated: 2-3 days**

- **Day 1** (4-6 hours)
  - Data model extensions
  - Prompt engineering updates
  - Agent modifications (formatting + generation)

- **Day 2** (4-6 hours)
  - Parser implementation
  - Service layer updates (chat_service.py)
  - Basic testing with agent directly

- **Day 3** (3-4 hours)
  - Interactive test script (key deliverable)
  - Unit tests
  - Documentation
  - Output verification

## Files Modified

### New Files
- `test_slide_editing_interactive.py` - Interactive test script (KEY DELIVERABLE)
- `tests/unit/test_slide_replacements.py` - Unit tests

### Modified Files
- `src/api/models/requests.py` - Add SlideContext model
- `src/api/models/responses.py` - Add replacement_info field
- `config/prompts.yaml` - Add slide editing instructions
- `src/services/agent.py` - Add context formatting and parsing
- `src/api/services/chat_service.py` - Add replacement application

**Note**: `src/api/routes/chat.py` is intentionally **not** modified in backend phase. Route handler updates will be done in Frontend Phase when the API is actually consumed and tested.

## Appendix

### Example Flow

**Input to Agent:**
```
<slide-context>
<div class="slide">
  <h1>Q1 Sales</h1>
  <p>Revenue: $1M</p>
</div>
<div class="slide">
  <h1>Q2 Sales</h1>
  <p>Revenue: $1.2M</p>
</div>
</slide-context>

Expand these into 4 slides with quarterly breakdowns and charts
```

**Output from LLM:**
```html
<div class="slide">
  <h1>Q1 Sales Overview</h1>
  <p>Revenue: $1M</p>
  <canvas id="chart1"></canvas>
</div>
<div class="slide">
  <h1>Q1 Regional Breakdown</h1>
  <p>Details...</p>
</div>
<div class="slide">
  <h1>Q2 Sales Overview</h1>
  <p>Revenue: $1.2M</p>
</div>
<div class="slide">
  <h1>Q2 Regional Breakdown</h1>
  <p>Details...</p>
</div>
```

**Replacement Info:**
```json
{
  "start_index": 2,
  "original_count": 2,
  "replacement_count": 4,
  "net_change": 2,
  "success": true
}
```

### Error Messages

| Error | Message |
|-------|---------|
| Non-contiguous indices | "Slide indices must be contiguous" |
| No slides in response | "No slide divs found in LLM response" |
| Empty slide | "Slide {i} is empty" |
| Index out of range | "Start index {idx} out of range" |

