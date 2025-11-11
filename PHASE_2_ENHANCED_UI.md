# Phase 2: Enhanced UI - Drag-and-Drop and Editing

## Goal
Add rich UI interactions: drag-and-drop slide reordering, HTML editing modal, and slide manipulation (duplicate, delete). Still single-session, but the backend will be prepared for multi-session support.

## Prerequisites
- ✅ Phase 1 complete and tested
- ✅ Basic chat and slide viewing working
- ✅ Backend and frontend running locally

## Success Criteria
- ✅ User can drag-and-drop slides to reorder them
- ✅ User can click "Edit" to modify slide HTML
- ✅ User can duplicate slides
- ✅ User can delete slides
- ✅ Changes persist within the session (backend stores updated deck)
- ✅ Visual feedback during drag operations
- ✅ HTML validation before saving edits

## Architecture Changes for Phase 2
- **Backend**: Add endpoints for slide manipulation (still single-session)
- **Frontend**: Add drag-and-drop library, Monaco editor, new UI components
- **State Management**: Keep slide deck in sync with backend
- **Preparation**: All APIs accept optional `session_id` parameter for Phase 4

---

## Implementation Steps

### Step 1: Backend - Slide Manipulation Endpoints (Estimated: 3-4 hours)

#### 1.1 Update Chat Service

**`src/api/services/chat_service.py`**

Add methods for slide manipulation:

```python
class ChatService:
    def __init__(self):
        self.agent = create_agent()
        self.session_id = self.agent.create_session()
        self.slide_deck = None
    
    # ... existing send_message method ...
    
    def get_slides(self) -> dict:
        """
        Get current slide deck.
        
        Phase 4: Add session_id parameter
        """
        if not self.slide_deck:
            return None
        return self.slide_deck.to_dict()
    
    def reorder_slides(self, new_order: List[int]) -> dict:
        """
        Reorder slides based on new index order.
        
        Args:
            new_order: List of indices in new order (e.g. [2, 0, 1])
            # session_id: Optional[str] = None  # For Phase 4
        
        Returns:
            Updated slide deck
        """
        if not self.slide_deck:
            raise ValueError("No slide deck available")
        
        # Validate indices
        if len(new_order) != len(self.slide_deck.slides):
            raise ValueError("Invalid reorder: wrong number of indices")
        
        if set(new_order) != set(range(len(self.slide_deck.slides))):
            raise ValueError("Invalid reorder: invalid indices")
        
        # Reorder slides
        new_slides = [self.slide_deck.slides[i] for i in new_order]
        self.slide_deck.slides = new_slides
        
        # Update indices
        for idx, slide in enumerate(self.slide_deck.slides):
            slide.slide_id = f"slide_{idx}"
        
        return self.slide_deck.to_dict()
    
    def update_slide(self, index: int, html: str) -> dict:
        """
        Update a single slide's HTML.
        
        Args:
            index: Slide index to update
            html: New HTML content (must include <div class="slide">)
            # session_id: Optional[str] = None  # For Phase 4
        
        Returns:
            Updated slide
        """
        if not self.slide_deck:
            raise ValueError("No slide deck available")
        
        if index < 0 or index >= len(self.slide_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")
        
        # Validate HTML has slide wrapper
        if '<div class="slide"' not in html:
            raise ValueError("HTML must contain <div class='slide'> wrapper")
        
        # Update slide
        self.slide_deck.slides[index] = Slide(html=html, slide_id=f"slide_{index}")
        
        return {
            "index": index,
            "slide_id": f"slide_{index}",
            "html": html
        }
    
    def duplicate_slide(self, index: int) -> dict:
        """
        Duplicate a slide.
        
        Args:
            index: Slide index to duplicate
            # session_id: Optional[str] = None  # For Phase 4
        
        Returns:
            New slide
        """
        if not self.slide_deck:
            raise ValueError("No slide deck available")
        
        if index < 0 or index >= len(self.slide_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")
        
        # Clone slide
        cloned = self.slide_deck.slides[index].clone()
        
        # Insert after original
        self.slide_deck.insert_slide(cloned, index + 1)
        
        # Update slide IDs
        for idx, slide in enumerate(self.slide_deck.slides):
            slide.slide_id = f"slide_{idx}"
        
        return self.slide_deck.to_dict()
    
    def delete_slide(self, index: int) -> dict:
        """
        Delete a slide.
        
        Args:
            index: Slide index to delete
            # session_id: Optional[str] = None  # For Phase 4
        
        Returns:
            Updated slide deck
        """
        if not self.slide_deck:
            raise ValueError("No slide deck available")
        
        if index < 0 or index >= len(self.slide_deck.slides):
            raise ValueError(f"Invalid slide index: {index}")
        
        if len(self.slide_deck.slides) <= 1:
            raise ValueError("Cannot delete last slide")
        
        # Remove slide
        self.slide_deck.remove_slide(index)
        
        # Update slide IDs
        for idx, slide in enumerate(self.slide_deck.slides):
            slide.slide_id = f"slide_{idx}"
        
        return self.slide_deck.to_dict()
```

#### 1.2 Add Slide Endpoints

**`src/api/routes/slides.py`** (new file)

```python
from fastapi import APIRouter, HTTPException
from typing import List
from pydantic import BaseModel

router = APIRouter(prefix="/api/slides", tags=["slides"])

# Import global service from chat.py
from .chat import chat_service

class ReorderRequest(BaseModel):
    new_order: List[int]

class UpdateSlideRequest(BaseModel):
    html: str

@router.get("")
async def get_slides():
    """
    Get current slide deck.
    
    Phase 4: Add session_id query parameter
    """
    try:
        result = chat_service.get_slides()
        if not result:
            raise HTTPException(status_code=404, detail="No slides available")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/reorder")
async def reorder_slides(request: ReorderRequest):
    """
    Reorder slides.
    
    Phase 4: Add session_id to request body
    """
    try:
        result = chat_service.reorder_slides(request.new_order)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{index}")
async def update_slide(index: int, request: UpdateSlideRequest):
    """
    Update a single slide's HTML.
    
    Phase 4: Add session_id query parameter
    """
    try:
        result = chat_service.update_slide(index, request.html)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{index}/duplicate")
async def duplicate_slide(index: int):
    """
    Duplicate a slide.
    
    Phase 4: Add session_id query parameter
    """
    try:
        result = chat_service.duplicate_slide(index)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{index}")
async def delete_slide(index: int):
    """
    Delete a slide.
    
    Phase 4: Add session_id query parameter
    """
    try:
        result = chat_service.delete_slide(index)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

#### 1.3 Update Main App

**`src/api/main.py`**

Add slides router:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import chat, slides

app = FastAPI(title="AI Slide Generator")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(chat.router)
app.include_router(slides.router)  # NEW
```

#### 1.4 Test Backend

```bash
# Get slides
curl http://localhost:8000/api/slides

# Reorder slides (swap first two)
curl -X PUT http://localhost:8000/api/slides/reorder \
  -H "Content-Type: application/json" \
  -d '{"new_order": [1, 0, 2, 3, 4]}'

# Update slide HTML
curl -X PATCH http://localhost:8000/api/slides/0 \
  -H "Content-Type: application/json" \
  -d '{"html": "<div class=\"slide\"><h1>Updated</h1></div>"}'

# Duplicate slide
curl -X POST http://localhost:8000/api/slides/0/duplicate

# Delete slide
curl -X DELETE http://localhost:8000/api/slides/0
```

---

### Step 2: Frontend - Install Dependencies (Estimated: 30 min)

```bash
cd frontend

# Drag-and-drop library
npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities

# Monaco editor (VS Code editor)
npm install @monaco-editor/react

# Icons
npm install react-icons
```

---

### Step 3: Frontend - Update API Client (Estimated: 1 hour)

**`src/services/api.ts`**

Add new methods:

```typescript
export const api = {
  // ... existing sendMessage and healthCheck ...

  /**
   * Get current slide deck
   * Phase 4: Add sessionId parameter
   */
  async getSlides(/* sessionId?: string */): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides`);
    
    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to fetch slides');
    }
    
    return response.json();
  },

  /**
   * Reorder slides
   * Phase 4: Add sessionId parameter
   */
  async reorderSlides(
    newOrder: number[]
    /* sessionId?: string */
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/reorder`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_order: newOrder }),
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to reorder slides');
    }

    return response.json();
  },

  /**
   * Update a single slide
   * Phase 4: Add sessionId parameter
   */
  async updateSlide(
    index: number,
    html: string
    /* sessionId?: string */
  ): Promise<Slide> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ html }),
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to update slide');
    }

    return response.json();
  },

  /**
   * Duplicate a slide
   * Phase 4: Add sessionId parameter
   */
  async duplicateSlide(
    index: number
    /* sessionId?: string */
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}/duplicate`, {
      method: 'POST',
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to duplicate slide');
    }

    return response.json();
  },

  /**
   * Delete a slide
   * Phase 4: Add sessionId parameter
   */
  async deleteSlide(
    index: number
    /* sessionId?: string */
  ): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides/${index}`, {
      method: 'DELETE',
    });

    if (!response.ok) {
      throw new ApiError(response.status, 'Failed to delete slide');
    }

    return response.json();
  },
};
```

---

### Step 4: Frontend - Drag-and-Drop Implementation (Estimated: 3-4 hours)

#### 4.1 Update Slide Panel with DnD

**`src/components/SlidePanel/SlidePanel.tsx`**

```typescript
import React, { useState } from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { SlideDeck } from '../../types/slide';
import { SlideTile } from './SlideTile';
import { api } from '../../services/api';

interface SlidePanelProps {
  slideDeck: SlideDeck | null;
  onSlideChange: (slideDeck: SlideDeck) => void;
}

export const SlidePanel: React.FC<SlidePanelProps> = ({ slideDeck, onSlideChange }) => {
  const [isReordering, setIsReordering] = useState(false);
  
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;

    if (!over || !slideDeck) return;
    
    if (active.id !== over.id) {
      const oldIndex = slideDeck.slides.findIndex(s => s.slide_id === active.id);
      const newIndex = slideDeck.slides.findIndex(s => s.slide_id === over.id);

      // Optimistic update
      const newSlides = arrayMove(slideDeck.slides, oldIndex, newIndex);
      onSlideChange({ ...slideDeck, slides: newSlides });

      // Persist to backend
      setIsReordering(true);
      try {
        const newOrder = newSlides.map((_, idx) => 
          slideDeck.slides.findIndex(s => s.slide_id === newSlides[idx].slide_id)
        );
        const updatedDeck = await api.reorderSlides(newOrder);
        onSlideChange(updatedDeck);
      } catch (error) {
        console.error('Failed to reorder:', error);
        // Revert on error
        onSlideChange(slideDeck);
        alert('Failed to reorder slides');
      } finally {
        setIsReordering(false);
      }
    }
  };

  const handleDeleteSlide = async (index: number) => {
    if (!slideDeck) return;
    
    if (!confirm(`Delete slide ${index + 1}?`)) return;

    try {
      const updatedDeck = await api.deleteSlide(index);
      onSlideChange(updatedDeck);
    } catch (error) {
      console.error('Failed to delete:', error);
      alert('Failed to delete slide');
    }
  };

  const handleDuplicateSlide = async (index: number) => {
    if (!slideDeck) return;

    try {
      const updatedDeck = await api.duplicateSlide(index);
      onSlideChange(updatedDeck);
    } catch (error) {
      console.error('Failed to duplicate:', error);
      alert('Failed to duplicate slide');
    }
  };

  const handleUpdateSlide = async (index: number, html: string) => {
    if (!slideDeck) return;

    try {
      await api.updateSlide(index, html);
      // Fetch updated deck
      const updatedDeck = await api.getSlides();
      onSlideChange(updatedDeck);
    } catch (error) {
      console.error('Failed to update:', error);
      throw error; // Re-throw for editor to handle
    }
  };

  if (!slideDeck) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50">
        <div className="text-center text-gray-500">
          <p className="text-lg font-medium">No slides yet</p>
          <p className="text-sm mt-2">Send a message to generate slides</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="sticky top-0 z-10 p-4 bg-white border-b">
        <h2 className="text-lg font-semibold">{slideDeck.title}</h2>
        <p className="text-sm text-gray-500">
          {slideDeck.slide_count} slide{slideDeck.slide_count !== 1 ? 's' : ''}
          {isReordering && ' • Reordering...'}
        </p>
      </div>

      {/* Slide Tiles with Drag-and-Drop */}
      <div className="p-4 space-y-4">
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={slideDeck.slides.map(s => s.slide_id)}
            strategy={verticalListSortingStrategy}
          >
            {slideDeck.slides.map((slide, index) => (
              <SlideTile
                key={slide.slide_id}
                slide={slide}
                slideDeck={slideDeck}
                index={index}
                onDelete={() => handleDeleteSlide(index)}
                onDuplicate={() => handleDuplicateSlide(index)}
                onUpdate={(html) => handleUpdateSlide(index, html)}
              />
            ))}
          </SortableContext>
        </DndContext>
      </div>
    </div>
  );
};
```

#### 4.2 Update Slide Tile for DnD and Actions

**`src/components/SlidePanel/SlideTile.tsx`**

```typescript
import React, { useMemo, useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { FiEdit, FiCopy, FiTrash2, FiMove } from 'react-icons/fi';
import { Slide, SlideDeck } from '../../types/slide';
import { HTMLEditorModal } from './HTMLEditorModal';

interface SlideTileProps {
  slide: Slide;
  slideDeck: SlideDeck;
  index: number;
  onDelete: () => void;
  onDuplicate: () => void;
  onUpdate: (html: string) => Promise<void>;
}

export const SlideTile: React.FC<SlideTileProps> = ({
  slide,
  slideDeck,
  index,
  onDelete,
  onDuplicate,
  onUpdate,
}) => {
  const [isEditing, setIsEditing] = useState(false);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: slide.slide_id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  // Build complete HTML for iframe
  const slideHTML = useMemo(() => {
    return `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ${slideDeck.external_scripts.map(src => 
    `<script src="${src}"></script>`
  ).join('\n  ')}
  <style>${slideDeck.css}</style>
</head>
<body>
  ${slide.html}
  <script>${slideDeck.scripts}</script>
</body>
</html>
    `.trim();
  }, [slide.html, slideDeck.css, slideDeck.scripts, slideDeck.external_scripts]);

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        className="bg-white rounded-lg shadow-md overflow-hidden"
      >
        {/* Slide Header with Actions */}
        <div className="px-4 py-2 bg-gray-100 border-b flex items-center justify-between">
          <div className="flex items-center space-x-2">
            {/* Drag Handle */}
            <button
              {...attributes}
              {...listeners}
              className="cursor-grab active:cursor-grabbing text-gray-500 hover:text-gray-700"
              title="Drag to reorder"
            >
              <FiMove size={18} />
            </button>
            
            <span className="text-sm font-medium text-gray-700">
              Slide {index + 1}
            </span>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center space-x-1">
            <button
              onClick={() => setIsEditing(true)}
              className="p-1 text-blue-600 hover:bg-blue-50 rounded"
              title="Edit HTML"
            >
              <FiEdit size={16} />
            </button>
            
            <button
              onClick={onDuplicate}
              className="p-1 text-green-600 hover:bg-green-50 rounded"
              title="Duplicate"
            >
              <FiCopy size={16} />
            </button>
            
            <button
              onClick={onDelete}
              className="p-1 text-red-600 hover:bg-red-50 rounded"
              title="Delete"
            >
              <FiTrash2 size={16} />
            </button>
          </div>
        </div>

        {/* Slide Preview */}
        <div className="relative bg-gray-200" style={{ paddingBottom: '56.25%' }}>
          <iframe
            srcDoc={slideHTML}
            title={`Slide ${index + 1}`}
            className="absolute top-0 left-0 w-full h-full border-0"
            sandbox="allow-scripts"
            style={{
              transform: 'scale(1)',
              transformOrigin: 'top left',
            }}
          />
        </div>
      </div>

      {/* HTML Editor Modal */}
      {isEditing && (
        <HTMLEditorModal
          html={slide.html}
          onSave={async (newHtml) => {
            await onUpdate(newHtml);
            setIsEditing(false);
          }}
          onCancel={() => setIsEditing(false)}
        />
      )}
    </>
  );
};
```

---

### Step 5: Frontend - HTML Editor Modal (Estimated: 3-4 hours)

#### 5.1 Create Editor Modal Component

**`src/components/SlidePanel/HTMLEditorModal.tsx`**

```typescript
import React, { useState } from 'react';
import Editor from '@monaco-editor/react';

interface HTMLEditorModalProps {
  html: string;
  onSave: (html: string) => Promise<void>;
  onCancel: () => void;
}

export const HTMLEditorModal: React.FC<HTMLEditorModalProps> = ({
  html,
  onSave,
  onCancel,
}) => {
  const [editedHtml, setEditedHtml] = useState(html);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validateHTML = (html: string): string | null => {
    // Check for required slide wrapper
    if (!html.includes('<div class="slide"')) {
      return 'HTML must contain <div class="slide"> wrapper';
    }

    // Basic HTML validation (check for balanced tags)
    const openDivs = (html.match(/<div/g) || []).length;
    const closeDivs = (html.match(/<\/div>/g) || []).length;
    
    if (openDivs !== closeDivs) {
      return 'Unbalanced <div> tags detected';
    }

    return null;
  };

  const handleSave = async () => {
    setError(null);

    // Validate
    const validationError = validateHTML(editedHtml);
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsSaving(true);
    try {
      await onSave(editedHtml);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white rounded-lg shadow-xl w-[90%] h-[90%] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between">
          <h2 className="text-xl font-semibold">Edit Slide HTML</h2>
          <button
            onClick={onCancel}
            className="text-gray-500 hover:text-gray-700"
            disabled={isSaving}
          >
            ✕
          </button>
        </div>

        {/* Editor */}
        <div className="flex-1 overflow-hidden">
          <Editor
            height="100%"
            defaultLanguage="html"
            value={editedHtml}
            onChange={(value) => setEditedHtml(value || '')}
            theme="vs-light"
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              wordWrap: 'on',
              formatOnPaste: true,
              formatOnType: true,
            }}
          />
        </div>

        {/* Error Display */}
        {error && (
          <div className="px-6 py-3 bg-red-50 border-t border-red-200">
            <p className="text-sm text-red-600">{error}</p>
          </div>
        )}

        {/* Footer */}
        <div className="px-6 py-4 border-t flex items-center justify-between">
          <div className="text-sm text-gray-500">
            Make sure to keep the <code>&lt;div class="slide"&gt;</code> wrapper
          </div>
          
          <div className="flex space-x-3">
            <button
              onClick={onCancel}
              disabled={isSaving}
              className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400"
            >
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
```

---

### Step 6: Update App Layout (Estimated: 30 min)

**`src/components/Layout/AppLayout.tsx`**

Update to pass `onSlideChange` callback:

```typescript
import React, { useState } from 'react';
import { ChatPanel } from '../ChatPanel/ChatPanel';
import { SlidePanel } from '../SlidePanel/SlidePanel';
import { SlideDeck } from '../../types/slide';

export const AppLayout: React.FC = () => {
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="bg-blue-600 text-white px-6 py-4 shadow-md">
        <h1 className="text-xl font-bold">AI Slide Generator</h1>
        <p className="text-sm text-blue-100">
          Phase 2 - Drag & Drop, Edit • Single Session
        </p>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat Panel */}
        <div className="w-[30%] border-r">
          <ChatPanel onSlidesGenerated={setSlideDeck} />
        </div>

        {/* Slide Panel */}
        <div className="flex-1">
          <SlidePanel 
            slideDeck={slideDeck} 
            onSlideChange={setSlideDeck}  {/* NEW */}
          />
        </div>
      </div>
    </div>
  );
};
```

---

### Step 7: Testing (Estimated: 2-3 hours)

#### 7.1 Test Drag-and-Drop

1. Generate slides with 5+ slides
2. Try dragging slides:
   - Drag by the move icon
   - Drop between other slides
   - Verify order changes
   - Verify backend persists order (check with API call)
3. Test edge cases:
   - Drag first slide to last
   - Drag last slide to first
   - Quick successive drags

#### 7.2 Test HTML Editing

1. Click "Edit" button on a slide
2. Monaco editor should open
3. Modify HTML content
4. Try invalid HTML (remove `<div class="slide">`)
   - Should show error
   - Should not save
5. Save valid HTML
   - Modal should close
   - Slide should update
   - Changes should persist

#### 7.3 Test Duplicate

1. Click duplicate button
2. New slide should appear immediately after
3. Verify it's a copy (same content)
4. Edit the duplicate
5. Verify original is unchanged

#### 7.4 Test Delete

1. Click delete button
2. Confirmation dialog should appear
3. Confirm deletion
4. Slide should disappear
5. Remaining slides should renumber
6. Try deleting until 1 slide left
   - Should not allow deleting last slide

#### 7.5 Test Integration

1. Generate slides via chat
2. Reorder them
3. Send follow-up message
4. Verify new slides append/replace correctly
5. Verify you can still edit reordered slides

---

### Step 8: Polish UI (Estimated: 2-3 hours)

#### 8.1 Add Visual Feedback

- **Drag overlay**: Show dragged slide as overlay
- **Drop indicator**: Show where slide will be dropped
- **Loading states**: Show spinners during API calls
- **Success feedback**: Brief success message after save

#### 8.2 Improve Accessibility

- **Keyboard navigation**: Tab through buttons
- **Aria labels**: Add labels for screen readers
- **Focus management**: Focus editor when modal opens
- **Escape key**: Close modal on ESC

#### 8.3 Error Handling

- **Network errors**: Show user-friendly messages
- **Invalid HTML**: Show validation errors
- **Retry logic**: Allow retry on failed operations

---

### Step 9: Documentation (Estimated: 1 hour)

**`README_PHASE2.md`**

```markdown
# AI Slide Generator - Phase 2 Enhanced UI

## New Features in Phase 2
- ✅ Drag-and-drop slide reordering
- ✅ HTML editor (Monaco) for slide editing
- ✅ Duplicate slides
- ✅ Delete slides
- ✅ Visual feedback during operations
- ✅ Validation before saving edits

## Still Single Session
- No multi-session support yet (Phase 4)
- Changes persist only within current session
- Backend prepared for multi-session (optional params)

## Usage

### Reordering Slides
1. Click and hold the move icon (☰) on any slide
2. Drag to desired position
3. Drop to reorder
4. Changes save automatically

### Editing Slides
1. Click the edit icon (✏️) on any slide
2. Monaco editor opens with HTML
3. Make changes
4. Click "Save Changes"
5. Validation checks for `<div class="slide">` wrapper

### Other Actions
- **Duplicate**: Click copy icon to create a duplicate
- **Delete**: Click trash icon (confirms before deleting)

## Technical Notes

### Backend Changes
- New endpoints: `/api/slides/*`
- All endpoints accept optional `session_id` (prepared for Phase 4)
- Slide IDs regenerate after operations

### Frontend Changes
- `@dnd-kit` for drag-and-drop
- Monaco editor for HTML editing
- Optimistic UI updates
- Error handling and rollback

## Known Limitations
- Still single session only
- No session persistence (restart clears state)
- No undo/redo
- No multi-user collaboration
```

---

## Phase 2 Complete Checklist

### Backend
- [ ] Slide manipulation methods in ChatService
- [ ] Slide endpoints (reorder, update, duplicate, delete)
- [ ] Validation logic (HTML, indices, etc.)
- [ ] Error handling with appropriate status codes
- [ ] Manual curl tests pass

### Frontend
- [ ] @dnd-kit dependencies installed
- [ ] Monaco editor installed
- [ ] API client methods added
- [ ] Drag-and-drop working smoothly
- [ ] HTML editor modal working
- [ ] Edit/duplicate/delete buttons working
- [ ] Validation preventing invalid edits
- [ ] Error messages display properly
- [ ] Visual feedback during operations

### Integration
- [ ] Drag operations persist to backend
- [ ] Edit operations persist to backend
- [ ] Optimistic updates work
- [ ] Error rollback works
- [ ] Follow-up messages still work
- [ ] No console errors

### Documentation
- [ ] README updated with Phase 2 features
- [ ] Usage instructions clear
- [ ] Known limitations documented
- [ ] Phase 4 preparation noted

---

## Estimated Total Time: 17-23 hours

- Backend: 3-4 hours
- Frontend Setup: 1-2 hours
- Drag-and-Drop: 3-4 hours
- HTML Editor: 3-4 hours
- Testing: 2-3 hours
- Polish: 2-3 hours
- Documentation: 1-2 hours

---

## Next Steps

After Phase 2 is complete:
1. Gather UX feedback
2. Test on different browsers
3. Proceed to **Phase 3**: Databricks Apps deployment

