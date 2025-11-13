# Frontend Implementation: Slide-Specific Editing

## Overview

Implement frontend UI and interaction patterns to enable users to select specific slides, send edit requests with context, and apply variable-length replacements to the slide deck. This builds on the backend implementation and provides an intuitive Cursor-style `@` mention experience.

**Prerequisites**: Backend slide editing functionality (Phases 1-5) must be complete and tested via the interactive test script.

**Note on Phase 3**: The backend route handler updates (`src/api/routes/chat.py`) were intentionally deferred from the Backend Phase and are implemented here in Frontend Phase 3. This ensures the API endpoint is implemented and tested alongside its first consumer, providing immediate integration validation.

## Core Design Principles

1. **Visual Feedback**: Clear indication of selected slides
2. **Contiguous Selection**: Only allow consecutive slide ranges
3. **Context Badge**: Show selected slides like Cursor's file mentions
4. **Seamless Updates**: Apply replacements without full page reload
5. **Error Resilience**: Graceful handling of backend errors

## Implementation Phases

### Phase 1: UI Components

#### 1.1 Slide Selection Component
**File**: `frontend/src/components/SlidePanel/SlideSelection.tsx`

Create new component for slide selection interface:

```typescript
import React, { useState } from 'react';
import { Slide } from '../../types/slide';

interface SlideSelectionProps {
  slides: Slide[];
  selectedIndices: number[];
  onSelectionChange: (indices: number[]) => void;
}

export const SlideSelection: React.FC<SlideSelectionProps> = ({
  slides,
  selectedIndices,
  onSelectionChange,
}) => {
  const handleSlideClick = (index: number, event: React.MouseEvent) => {
    if (event.shiftKey && selectedIndices.length > 0) {
      // Shift-click: select range
      const lastSelected = selectedIndices[selectedIndices.length - 1];
      const start = Math.min(lastSelected, index);
      const end = Math.max(lastSelected, index);
      const range = Array.from({ length: end - start + 1 }, (_, i) => start + i);
      onSelectionChange(range);
    } else if (event.ctrlKey || event.metaKey) {
      // Ctrl/Cmd-click: toggle selection
      const newSelection = selectedIndices.includes(index)
        ? selectedIndices.filter(i => i !== index)
        : [...selectedIndices, index].sort((a, b) => a - b);
      
      // Validate contiguous
      if (isContiguous(newSelection)) {
        onSelectionChange(newSelection);
      } else {
        // Show warning
        showContiguousWarning();
      }
    } else {
      // Regular click: single selection
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

  const showContiguousWarning = () => {
    // Toast notification or inline message
    console.warn('Please select consecutive slides only');
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
          role="button"
          tabIndex={0}
        >
          <div className="slide-number">{index + 1}</div>
          <div 
            className="slide-preview"
            dangerouslySetInnerHTML={{ __html: slide.html }}
          />
          {selectedIndices.includes(index) && (
            <div className="selection-indicator">✓</div>
          )}
        </div>
      ))}
    </div>
  );
};
```

**Features**:
- Click to select single slide
- Shift+Click to select range
- Ctrl/Cmd+Click to toggle selection (with contiguous validation)
- Visual highlight for selected slides
- Selection indicator checkmark

#### 1.2 Selection Badge Component
**File**: `frontend/src/components/ChatPanel/SelectionBadge.tsx`

Show selected slides in chat input area (like Cursor's file badges):

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
      <span className="badge-text">{rangeText}</span>
      <button 
        className="badge-clear"
        onClick={onClear}
        aria-label="Clear selection"
        type="button"
      >
        ×
      </button>
    </div>
  );
};
```

**Features**:
- Shows compact range notation (e.g., "Slides 2-4")
- Clear button to deselect
- Styled like Cursor's @ mentions

#### 1.3 Replacement Feedback Component
**File**: `frontend/src/components/ChatPanel/ReplacementFeedback.tsx`

Show feedback when replacements are applied:

```typescript
import React from 'react';

interface ReplacementInfo {
  start_index: number;
  original_count: number;
  replacement_count: number;
  net_change: number;
  operation: string;
}

interface ReplacementFeedbackProps {
  replacementInfo: ReplacementInfo;
}

export const ReplacementFeedback: React.FC<ReplacementFeedbackProps> = ({
  replacementInfo,
}) => {
  const { original_count, replacement_count, net_change } = replacementInfo;
  
  const getMessage = () => {
    if (net_change === 0) {
      return `✓ Replaced ${original_count} slide${original_count > 1 ? 's' : ''}`;
    } else if (net_change > 0) {
      return `✓ Expanded ${original_count} slide${original_count > 1 ? 's' : ''} into ${replacement_count} (+${net_change})`;
    } else {
      return `✓ Condensed ${original_count} slide${original_count > 1 ? 's' : ''} into ${replacement_count} (${net_change})`;
    }
  };

  return (
    <div className="replacement-feedback success">
      {getMessage()}
    </div>
  );
};
```

**Features**:
- Shows what happened (1:1, expansion, condensation)
- Clear success indicator
- Net change in slide count

### Phase 2: State Management

#### 2.1 Selection Context
**File**: `frontend/src/contexts/SelectionContext.tsx`

Create React context for managing slide selection state:

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

**Features**:
- Centralized selection state
- Helper hook for easy access
- Clear API for updating selection

#### 2.2 App State Integration
**File**: `frontend/src/App.tsx`

Integrate selection provider into app:

```typescript
import { SelectionProvider } from './contexts/SelectionContext';

function App() {
  return (
    <SelectionProvider>
      {/* existing app structure */}
    </SelectionProvider>
  );
}
```

### Phase 3: API Integration

**Note**: This phase includes both frontend API client updates AND the backend route handler updates. The route handler was deferred from the backend phase because the frontend is its first real consumer, enabling proper integration testing.

#### 3.1 Backend Route Handler Updates
**File**: `src/api/routes/chat.py`

Update endpoint to handle slide context:

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a chat message and generate or edit slides.
    
    Supports two modes:
    1. Generation mode: slide_context is None
    2. Editing mode: slide_context contains selected slides
    """
    try:
        # Extract slide_context if provided
        slide_context = None
        if request.slide_context:
            slide_context = {
                'indices': request.slide_context.indices,
                'slide_htmls': request.slide_context.slide_htmls,
            }
        
        # Process message
        result = chat_service.send_message(
            message=request.message,
            max_slides=request.max_slides,
            slide_context=slide_context,
        )
        
        return ChatResponse(
            slide_deck=result['slide_deck'],
            messages=result['messages'],
            metadata=result['metadata'],
            replacement_info=result.get('replacement_info'),
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error processing chat request")
        raise HTTPException(status_code=500, detail="Internal server error")
```

#### 3.2 Type Definitions
**File**: `frontend/src/types/slide.ts`

Add types for slide editing:

```typescript
export interface SlideContext {
  indices: number[];
  slide_htmls: string[];
}

export interface ReplacementInfo {
  start_index: number;
  original_count: number;
  replacement_count: number;
  net_change: number;
  operation: string;
}

export interface ChatResponseWithReplacement extends ChatResponse {
  replacement_info?: ReplacementInfo;
}
```

#### 3.3 API Service Extension
**File**: `frontend/src/services/api.ts`

Extend API service to handle slide context:

```typescript
export interface SendMessageParams {
  message: string;
  maxSlides?: number;
  slideContext?: SlideContext;
}

export interface ApiResponse {
  slide_deck: SlideDeck;
  messages: Message[];
  metadata: any;
  replacement_info?: ReplacementInfo;
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
    const error = await response.json();
    throw new Error(error.detail || `API error: ${response.status}`);
  }

  return response.json();
};
```

**Features**:
- Optional slide context parameter
- Type-safe request/response
- Error handling

### Phase 4: Replacement Application Logic

#### 4.1 Replacement Utility
**File**: `frontend/src/utils/slideReplacements.ts`

Create utility functions for applying replacements:

```typescript
import { SlideDeck, Slide } from '../types/slide';
import { ReplacementInfo } from '../types/slide';

export interface ReplacementResponse {
  slide_deck: SlideDeck;
  replacement_info: ReplacementInfo;
}

/**
 * Apply slide replacements to the current deck.
 * 
 * This handles variable-length replacements:
 * - Remove slides at [start_index : start_index + original_count]
 * - Insert replacement slides at start_index
 */
export const applyReplacements = (
  currentDeck: SlideDeck,
  response: ReplacementResponse
): SlideDeck => {
  const { start_index, original_count } = response.replacement_info;
  const replacementSlides = response.slide_deck.slides;
  
  // Clone the current deck to avoid mutation
  const newSlides = [...currentDeck.slides];
  
  // Remove original slides and insert replacements
  newSlides.splice(start_index, original_count, ...replacementSlides);
  
  return {
    ...currentDeck,
    slides: newSlides,
    slide_count: newSlides.length,
  };
};

/**
 * Generate human-readable summary of replacement operation.
 */
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

/**
 * Validate that indices are contiguous.
 */
export const isContiguous = (indices: number[]): boolean => {
  if (indices.length <= 1) return true;
  const sorted = [...indices].sort((a, b) => a - b);
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] - sorted[i - 1] !== 1) return false;
  }
  return true;
};
```

### Phase 5: Component Integration

#### 5.1 Update ChatPanel
**File**: `frontend/src/components/ChatPanel/ChatPanel.tsx`

Integrate slide selection into chat flow:

```typescript
import { useSelection } from '../../contexts/SelectionContext';
import { SelectionBadge } from './SelectionBadge';
import { ReplacementFeedback } from './ReplacementFeedback';
import { sendMessage } from '../../services/api';
import { applyReplacements } from '../../utils/slideReplacements';

export const ChatPanel: React.FC<ChatPanelProps> = ({ slideDeck, setSlideDeck }) => {
  const { selectedIndices, selectedSlides, clearSelection } = useSelection();
  const [isLoading, setIsLoading] = useState(false);
  const [lastReplacement, setLastReplacement] = useState<ReplacementInfo | null>(null);

  const handleSendMessage = async (message: string) => {
    // Prepare slide context if slides are selected
    const slideContext = selectedIndices.length > 0
      ? {
          indices: selectedIndices,
          slide_htmls: selectedSlides.map(s => s.html),
        }
      : undefined;

    setIsLoading(true);
    setLastReplacement(null);

    try {
      const response = await sendMessage({
        message,
        maxSlides: 10,
        slideContext,
      });

      if (response.replacement_info) {
        // Editing mode: apply replacements to existing deck
        const updatedDeck = applyReplacements(slideDeck, {
          slide_deck: response.slide_deck,
          replacement_info: response.replacement_info,
        });
        setSlideDeck(updatedDeck);
        setLastReplacement(response.replacement_info);
        
        // Clear selection after successful edit
        clearSelection();
      } else {
        // Generation mode: replace entire deck
        setSlideDeck(response.slide_deck);
      }

      // Add messages to chat history
      // ... existing message handling ...

    } catch (error) {
      console.error('Failed to send message:', error);
      // Show error toast
      showError(error.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="chat-panel">
      {/* Chat history */}
      
      {/* Input area */}
      <div className="chat-input-container">
        {selectedIndices.length > 0 && (
          <SelectionBadge
            selectedIndices={selectedIndices}
            onClear={clearSelection}
          />
        )}
        
        <textarea
          value={inputMessage}
          onChange={(e) => setInputMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            selectedIndices.length > 0
              ? "Describe changes to selected slides..."
              : "Ask to generate or modify slides..."
          }
          disabled={isLoading}
        />
        
        <button onClick={() => handleSendMessage(inputMessage)} disabled={isLoading}>
          {isLoading ? 'Processing...' : 'Send'}
        </button>
      </div>
      
      {/* Feedback */}
      {lastReplacement && (
        <ReplacementFeedback replacementInfo={lastReplacement} />
      )}
    </div>
  );
};
```

**Features**:
- Shows selection badge when slides are selected
- Changes placeholder text based on mode
- Applies replacements automatically
- Clears selection after successful edit
- Shows replacement feedback

#### 5.2 Update SlidePanel
**File**: `frontend/src/components/SlidePanel/SlidePanel.tsx`

Integrate slide selection component:

```typescript
import { useSelection } from '../../contexts/SelectionContext';
import { SlideSelection } from './SlideSelection';

export const SlidePanel: React.FC<SlidePanelProps> = ({ slideDeck }) => {
  const { selectedIndices, setSelection } = useSelection();

  const handleSelectionChange = (indices: number[]) => {
    const selectedSlides = indices.map(i => slideDeck.slides[i]);
    setSelection(indices, selectedSlides);
  };

  return (
    <div className="slide-panel">
      <div className="slide-panel-header">
        <h2>Slides ({slideDeck.slide_count})</h2>
        {selectedIndices.length > 0 && (
          <span className="selection-count">
            {selectedIndices.length} selected
          </span>
        )}
      </div>
      
      <SlideSelection
        slides={slideDeck.slides}
        selectedIndices={selectedIndices}
        onSelectionChange={handleSelectionChange}
      />
    </div>
  );
};
```

### Phase 6: Styling

#### 6.1 Selection Styles
**File**: `frontend/src/components/SlidePanel/SlideSelection.css`

```css
.slide-selection {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 1rem;
  padding: 1rem;
}

.slide-thumbnail {
  position: relative;
  border: 2px solid transparent;
  border-radius: 8px;
  padding: 0.5rem;
  cursor: pointer;
  transition: all 0.2s ease;
  background: white;
}

.slide-thumbnail:hover {
  border-color: #3b82f6;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.2);
}

.slide-thumbnail.selected {
  border-color: #3b82f6;
  background: #eff6ff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.slide-number {
  position: absolute;
  top: 0.5rem;
  left: 0.5rem;
  background: #1e293b;
  color: white;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
  z-index: 10;
}

.slide-thumbnail.selected .slide-number {
  background: #3b82f6;
}

.selection-indicator {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  background: #3b82f6;
  color: white;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
}

.slide-preview {
  width: 100%;
  aspect-ratio: 16/9;
  overflow: hidden;
  border-radius: 4px;
  background: #f8fafc;
}

.slide-preview > * {
  transform: scale(0.15);
  transform-origin: top left;
  width: 1280px;
  height: 720px;
}
```

#### 6.2 Badge Styles
**File**: `frontend/src/components/ChatPanel/SelectionBadge.css`

```css
.selection-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.75rem;
  background: #eff6ff;
  border: 1px solid #3b82f6;
  border-radius: 6px;
  font-size: 0.875rem;
  margin-bottom: 0.5rem;
}

.badge-icon {
  font-size: 1rem;
}

.badge-text {
  color: #1e40af;
  font-weight: 500;
}

.badge-clear {
  background: none;
  border: none;
  color: #3b82f6;
  font-size: 1.25rem;
  cursor: pointer;
  padding: 0;
  margin: 0;
  line-height: 1;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: all 0.2s ease;
}

.badge-clear:hover {
  background: #3b82f6;
  color: white;
}
```

#### 6.3 Feedback Styles
**File**: `frontend/src/components/ChatPanel/ReplacementFeedback.css`

```css
.replacement-feedback {
  padding: 0.75rem 1rem;
  border-radius: 6px;
  margin-top: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
}

.replacement-feedback.success {
  background: #f0fdf4;
  border: 1px solid #22c55e;
  color: #166534;
}

.replacement-feedback.error {
  background: #fef2f2;
  border: 1px solid #ef4444;
  color: #991b1b;
}
```

### Phase 7: Error Handling & UX Enhancements

#### 7.1 Error States
**File**: `frontend/src/components/ChatPanel/ErrorDisplay.tsx`

```typescript
interface ErrorDisplayProps {
  error: string;
  onDismiss: () => void;
}

export const ErrorDisplay: React.FC<ErrorDisplayProps> = ({ error, onDismiss }) => {
  return (
    <div className="error-display">
      <span className="error-icon">⚠️</span>
      <span className="error-message">{error}</span>
      <button onClick={onDismiss} className="error-dismiss">×</button>
    </div>
  );
};
```

#### 7.2 Keyboard Shortcuts
**File**: `frontend/src/hooks/useKeyboardShortcuts.ts`

```typescript
import { useEffect } from 'react';
import { useSelection } from '../contexts/SelectionContext';

export const useKeyboardShortcuts = () => {
  const { clearSelection } = useSelection();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Escape to clear selection
      if (e.key === 'Escape') {
        clearSelection();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [clearSelection]);
};
```

#### 7.3 Loading States
**File**: `frontend/src/components/ChatPanel/LoadingIndicator.tsx`

```typescript
export const LoadingIndicator: React.FC = () => {
  return (
    <div className="loading-indicator">
      <div className="spinner" />
      <span>Processing slide edits...</span>
    </div>
  );
};
```

## Testing Strategy

### Component Tests
1. **SlideSelection**: Test selection logic, contiguous validation
2. **SelectionBadge**: Test display and clear functionality
3. **ReplacementFeedback**: Test different message types

### Integration Tests
1. **API Integration**: Test requests with slide context
2. **Replacement Application**: Test various replacement scenarios
3. **State Management**: Test selection context updates

### E2E Test Scenarios
1. Select single slide, modify color
2. Select multiple slides, expand into more
3. Select slides, condense into fewer
4. Test non-contiguous selection rejection
5. Test keyboard shortcuts

### Manual QA Checklist
- [ ] Can select single slide
- [ ] Can select range with Shift+Click
- [ ] Can toggle with Ctrl/Cmd+Click
- [ ] Non-contiguous selection shows warning
- [ ] Selection badge appears and updates
- [ ] Badge clear button works
- [ ] Placeholder text changes with selection
- [ ] Replacements apply correctly
- [ ] Selection clears after successful edit
- [ ] Feedback message shows correct info
- [ ] Escape key clears selection
- [ ] Loading states display properly
- [ ] Error messages display clearly

## Success Criteria

### Functional Requirements
- ✅ Users can select contiguous slides visually
- ✅ Selection state persists until edit completes
- ✅ Selection badge shows in chat input
- ✅ API sends slide context correctly
- ✅ Replacements apply immediately in UI
- ✅ Variable-length replacements work (expansion/condensation)
- ✅ Feedback shows what changed

### UX Requirements
- ✅ Clear visual feedback for selection
- ✅ Intuitive keyboard shortcuts
- ✅ Error states are user-friendly
- ✅ Loading states prevent confusion
- ✅ Smooth transitions and animations

### Code Quality
- ✅ TypeScript types for all new code
- ✅ Component tests for interactive elements
- ✅ Consistent styling with existing UI
- ✅ Accessible markup (ARIA labels, keyboard nav)

## Timeline

**Estimated: 3-4 days**

- **Day 1** (4-6 hours)
  - Selection component
  - Badge component
  - Context provider
  - Basic styling

- **Day 2** (4-6 hours)
  - API integration
    - Backend route handler (small Python change)
    - Frontend API client
  - Replacement utility
  - ChatPanel updates
  - SlidePanel updates

- **Day 3** (3-4 hours)
  - Error handling
  - Loading states
  - Keyboard shortcuts
  - Polish styling

- **Day 4** (2-3 hours)
  - Testing (component + E2E)
  - Bug fixes
  - Documentation

## Files Modified

### New Files
- `frontend/src/components/SlidePanel/SlideSelection.tsx`
- `frontend/src/components/SlidePanel/SlideSelection.css`
- `frontend/src/components/ChatPanel/SelectionBadge.tsx`
- `frontend/src/components/ChatPanel/SelectionBadge.css`
- `frontend/src/components/ChatPanel/ReplacementFeedback.tsx`
- `frontend/src/components/ChatPanel/ReplacementFeedback.css`
- `frontend/src/components/ChatPanel/ErrorDisplay.tsx`
- `frontend/src/components/ChatPanel/LoadingIndicator.tsx`
- `frontend/src/contexts/SelectionContext.tsx`
- `frontend/src/utils/slideReplacements.ts`
- `frontend/src/hooks/useKeyboardShortcuts.ts`

### Modified Files

**Backend:**
- `src/api/routes/chat.py` - Handle slide_context in endpoint (moved from Backend Phase)

**Frontend:**
- `frontend/src/App.tsx` - Add SelectionProvider
- `frontend/src/types/slide.ts` - Add SlideContext and ReplacementInfo types
- `frontend/src/services/api.ts` - Extend sendMessage with slideContext
- `frontend/src/components/ChatPanel/ChatPanel.tsx` - Integrate selection and replacements
- `frontend/src/components/SlidePanel/SlidePanel.tsx` - Add SlideSelection component

## Dependencies

### Required Backend Implementation (from Backend Phase)

**Must be complete before starting frontend:**
- ✅ `SlideContext` model in `src/api/models/requests.py`
- ✅ `replacement_info` field in `src/api/models/responses.py`
- ✅ Slide editing instructions in `config/prompts.yaml`
- ✅ `_format_slide_context()` and `_parse_slide_replacements()` in `src/services/agent.py`
- ✅ `generate_slides()` accepts `slide_context` parameter in `src/services/agent.py`
- ✅ `send_message()` accepts `slide_context` parameter in `src/api/services/chat_service.py`
- ✅ `_apply_slide_replacements()` method in `src/api/services/chat_service.py`
- ✅ Interactive test script validates all backend functionality

**Implemented during frontend Phase 3:**
- Route handler updates in `src/api/routes/chat.py` (enables end-to-end testing)

## Appendix

### User Flow Example

1. **User generates initial deck**
   - Sends message: "Create 5 slides about quarterly sales"
   - System generates 5 slides

2. **User selects slides for editing**
   - Clicks slide 2
   - Shift+clicks slide 4
   - Slides 2, 3, 4 are now selected
   - Badge appears: "📎 Slides 3-5"

3. **User requests edit**
   - Types: "Expand these into more detailed quarterly breakdowns"
   - Sends message

4. **System applies replacements**
   - Backend returns 6 slides (expansion from 3)
   - Frontend removes slides 2-4
   - Frontend inserts 6 new slides at position 2
   - Deck now has 8 slides total (was 5)
   - Feedback: "✓ Expanded 3 slides into 6 (+3)"

5. **Selection clears**
   - Badge disappears
   - User can make next request

### Error Scenarios

| Scenario | User Action | System Response |
|----------|-------------|-----------------|
| Non-contiguous selection | Select slides 1, 3 (skipping 2) | Show warning: "Please select consecutive slides" |
| Backend error | Send edit request | Show error message, retain selection |
| No slides returned | LLM returns empty | Show error: "No slides generated, please try again" |
| Network failure | API call fails | Show error with retry button |

### Accessibility Considerations

- Keyboard navigation for slide selection (Tab, Arrow keys)
- ARIA labels for slide thumbnails
- Screen reader announcements for selection changes
- Focus management after actions
- High contrast mode support

