import React, { useState } from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import type { SlideDeck } from '../../types/slide';
import { SlideTile } from './SlideTile';
import { api } from '../../services/api';

interface SlidePanelProps {
  slideDeck: SlideDeck | null;
  rawHtml: string | null;
  onSlideChange: (slideDeck: SlideDeck) => void;
}

type ViewMode = 'tiles' | 'rawhtml' | 'rawtext';

export const SlidePanel: React.FC<SlidePanelProps> = ({ slideDeck, rawHtml, onSlideChange }) => {
  const [isReordering, setIsReordering] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('tiles');
  
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
    <div className="h-full flex flex-col bg-gray-50">
      {/* Header with Tabs */}
      <div className="bg-white border-b">
        <div className="p-4">
          <h2 className="text-lg font-semibold">{slideDeck.title}</h2>
          <p className="text-sm text-gray-500">
            {slideDeck.slide_count} slide{slideDeck.slide_count !== 1 ? 's' : ''}
            {isReordering && ' • Reordering...'}
          </p>
        </div>
        
        {/* Tab Navigation */}
        <div className="flex border-t">
          <button
            onClick={() => setViewMode('tiles')}
            className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
              viewMode === 'tiles'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-800 hover:border-gray-300'
            }`}
          >
            Parsed Slides
          </button>
          <button
            onClick={() => setViewMode('rawhtml')}
            className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
              viewMode === 'rawhtml'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-800 hover:border-gray-300'
            }`}
            disabled={!rawHtml}
          >
            Raw HTML (Rendered)
          </button>
          <button
            onClick={() => setViewMode('rawtext')}
            className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
              viewMode === 'rawtext'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-600 hover:text-gray-800 hover:border-gray-300'
            }`}
            disabled={!rawHtml}
          >
            Raw HTML (Text)
          </button>
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-hidden">
        {viewMode === 'tiles' && (
          <div className="h-full overflow-y-auto">
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
        )}

        {viewMode === 'rawhtml' && rawHtml && (
          <div className="h-full flex flex-col">
            <div className="p-4 bg-yellow-50 border-b border-yellow-200">
              <p className="text-sm text-yellow-800">
                <strong>Raw HTML (Rendered):</strong> This is the original HTML returned by the AI, rendered in an iframe. Compare with "Parsed Slides" to identify parsing issues.
              </p>
            </div>
            <div className="flex-1 p-4 overflow-hidden">
              <div className="h-full bg-white rounded-lg shadow-md overflow-hidden">
                <iframe
                  srcDoc={rawHtml}
                  title="Raw HTML Preview"
                  className="w-full h-full border-0"
                  sandbox="allow-scripts"
                />
              </div>
            </div>
          </div>
        )}

        {viewMode === 'rawtext' && rawHtml && (
          <div className="h-full flex flex-col">
            <div className="p-4 bg-purple-50 border-b border-purple-200">
              <p className="text-sm text-purple-800">
                <strong>Raw HTML (Text):</strong> The original HTML source code from the AI. Use this to inspect the structure and find issues.
              </p>
            </div>
            <div className="flex-1 p-4 overflow-auto">
              <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg text-xs overflow-auto">
                <code>{rawHtml}</code>
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
