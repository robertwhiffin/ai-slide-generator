import React, { useEffect, useState, useRef } from 'react';
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
import { FiPlay, FiDownload, FiFile, FiFileText, FiCode } from 'react-icons/fi';
import type { Slide, SlideDeck } from '../../types/slide';
import { SlideTile } from './SlideTile';
import { PresentationMode } from '../PresentationMode';
import { api } from '../../services/api';
import { useSelection } from '../../contexts/SelectionContext';
import { exportSlideDeckToPDF } from '../../services/pdf_client';
import { useSession } from '../../contexts/SessionContext';

const isDebugMode = (): boolean => {
  const urlParams = new URLSearchParams(window.location.search);
  return urlParams.get('debug')?.toLowerCase() === 'true' || localStorage.getItem('debug')?.toLowerCase() === 'true';
};

interface SlidePanelProps {
  slideDeck: SlideDeck | null;
  rawHtml: string | null;
  onSlideChange: (slideDeck: SlideDeck) => void;
  scrollToSlide?: { index: number; key: number } | null;
}

type ViewMode = 'tiles' | 'rawhtml' | 'rawtext';

export const SlidePanel: React.FC<SlidePanelProps> = ({ slideDeck, rawHtml, onSlideChange, scrollToSlide }) => {
  const [isReordering, setIsReordering] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('tiles');
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [isExportingPPTX, setIsExportingPPTX] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);
  const [isPresentationMode, setIsPresentationMode] = useState(false);
  const { selectedIndices, setSelection, clearSelection } = useSelection();
  const { sessionId } = useSession();
  const slideRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  
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
      if (!sessionId) {
        alert('Session not initialized');
        onSlideChange(slideDeck);
        return;
      }

      setIsReordering(true);
      try {
        const newOrder = newSlides.map((_, idx) => 
          slideDeck.slides.findIndex(s => s.slide_id === newSlides[idx].slide_id)
        );
        const updatedDeck = await api.reorderSlides(newOrder, sessionId);
        onSlideChange(updatedDeck);
        clearSelection();
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
    if (!slideDeck || !sessionId) return;
    
    if (!confirm(`Delete slide ${index + 1}?`)) return;

    try {
      const updatedDeck = await api.deleteSlide(index, sessionId);
      onSlideChange(updatedDeck);
      clearSelection();
    } catch (error) {
      console.error('Failed to delete:', error);
      alert('Failed to delete slide');
    }
  };

  const handleDuplicateSlide = async (index: number) => {
    if (!slideDeck || !sessionId) return;

    try {
      const updatedDeck = await api.duplicateSlide(index, sessionId);
      onSlideChange(updatedDeck);
      clearSelection();
    } catch (error) {
      console.error('Failed to duplicate:', error);
      alert('Failed to duplicate slide');
    }
  };

  const handleUpdateSlide = async (index: number, html: string) => {
    if (!slideDeck || !sessionId) return;

    try {
      await api.updateSlide(index, html, sessionId);
      // Fetch updated deck
      const result = await api.getSlides(sessionId);
      if (result.slide_deck) {
        onSlideChange(result.slide_deck);
      }
      clearSelection();
    } catch (error) {
      console.error('Failed to update:', error);
      throw error; // Re-throw for editor to handle
    }
  };

  const handleExportPDF = async () => {
    if (!slideDeck || isExportingPDF) return;

    setIsExportingPDF(true);
    setShowExportMenu(false);
    try {
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const filename = `${slideDeck.title || 'slides'}_${timestamp}.pdf`;
      
      await exportSlideDeckToPDF(slideDeck, filename, {
        format: 'a4',
        orientation: 'landscape',
        scale: 1.2, // Optimized for file size vs quality
        waitForCharts: 2000,
        imageQuality: 0.85, // JPEG quality (good balance)
      });
    } catch (error) {
      console.error('PDF export failed:', error);
      const message = error instanceof Error 
        ? error.message 
        : 'Failed to export PDF. Please try again.';
      alert(message);
    } finally {
      setIsExportingPDF(false);
    }
  };

  const handleExportPPTX = async () => {
    if (!slideDeck || !sessionId || isExportingPPTX) return;
    
    setIsExportingPPTX(true);
    setShowExportMenu(false);
    
    try {
      const blob = await api.exportToPPTX(sessionId, true);
      
      // Create download link
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const timestamp = new Date().toISOString().slice(0, 10);
      a.download = `${slideDeck.title || 'slides'}_${timestamp}.pptx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('PPTX export failed:', error);
      const message = error instanceof Error 
        ? error.message 
        : 'Failed to export PPTX. Please try again.';
      alert(message);
    } finally {
      setIsExportingPPTX(false);
    }
  };

  useEffect(() => {
    if (!slideDeck) {
      clearSelection();
      return;
    }

    const validIndices = selectedIndices.filter(
      index => index >= 0 && index < slideDeck.slides.length,
    );

    if (validIndices.length !== selectedIndices.length) {
      const slides: Slide[] = validIndices
        .map(index => slideDeck.slides[index])
        .filter((slide): slide is Slide => Boolean(slide));
      setSelection(validIndices, slides);
    }
  }, [slideDeck, selectedIndices, clearSelection, setSelection]);

  // Close export menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target as Node)) {
        setShowExportMenu(false);
      }
    };
    
    if (showExportMenu) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showExportMenu]);

  // Scroll to slide when scrollToSlide changes
  useEffect(() => {
    if (scrollToSlide != null && viewMode === 'tiles') {
      const slideElement = slideRefs.current.get(scrollToSlide.index);
      if (slideElement) {
        slideElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [scrollToSlide, viewMode]);
  const handleSaveAsHTML = () => {
    if (!slideDeck) return;

    const slidesHtml = slideDeck.slides
      .map((slide) => `<section>${slide.html}</section>`)
      .join('\n');

    const externalScriptsHtml = slideDeck.external_scripts
      .map((src) => `<script src="${src}"></script>`)
      .join('\n');

    const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${slideDeck.title || 'Presentation'}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/white.css">
  ${externalScriptsHtml}
  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #000;
    }
    .reveal-viewport {
      display: flex;
      justify-content: center;
      align-items: center;
      width: 100%;
      height: 100%;
    }
    .reveal {
      width: 100%;
      height: 100%;
    }
    .reveal .slides {
      text-align: left;
    }
    .reveal .slides section {
      height: 100%;
      width: 100%;
      padding: 0;
      box-sizing: border-box;
    }
    .reveal .slides section .slide {
      width: 100% !important;
      height: 100% !important;
      min-height: 100% !important;
      max-height: 100% !important;
      position: relative;
      box-sizing: border-box;
    }
    .reveal canvas {
      max-width: 100%;
    }
    ${slideDeck.css}
  </style>
</head>
<body>
  <div class="reveal-viewport">
    <div class="reveal">
      <div class="slides">
        ${slidesHtml}
      </div>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
  <script>
    function waitForChartJs(callback, maxAttempts = 50) {
      let attempts = 0;
      const check = () => {
        attempts++;
        if (typeof Chart !== 'undefined') {
          callback();
        } else if (attempts < maxAttempts) {
          setTimeout(check, 100);
        }
      };
      check();
    }

    function initializeCharts() {
      ${slideDeck.scripts}
    }

    Reveal.initialize({
      hash: true,
      controls: true,
      progress: true,
      slideNumber: true,
      overview: true,
      width: 1280,
      height: 720,
      margin: 0,
      minScale: 0.1,
      maxScale: 2.0,
      center: true,
      transition: 'slide',
      display: 'flex'
    }).then(() => {
      waitForChartJs(initializeCharts);
    });
  </script>
</body>
</html>`;

    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(slideDeck.title || 'presentation').replace(/[^a-z0-9]/gi, '-').toLowerCase()}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    // Close the dropdown menu
    setShowExportMenu(false);
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
        <div className="p-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">{slideDeck.title}</h2>
            <p className="text-sm text-gray-500">
              {slideDeck.slide_count} slide{slideDeck.slide_count !== 1 ? 's' : ''}
              {isReordering && ' • Reordering...'}
              {isExportingPDF && ' • Exporting PDF...'}
              {isExportingPPTX && ' • Exporting PowerPoint...'}
            </p>
          </div>
          
          {/* Export Dropdown Menu and Present Button */}
          <div className="flex items-center">
            <div className="relative" ref={exportMenuRef}>
              <button
                onClick={() => setShowExportMenu(!showExportMenu)}
                disabled={!slideDeck || isExportingPDF || isExportingPPTX}
                className={`
                  flex items-center space-x-2 px-4 py-2 rounded-l-lg transition-colors
                  ${!slideDeck || isExportingPDF || isExportingPPTX
                    ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                  }
                `}
                title="Export slides"
              >
                {(isExportingPDF || isExportingPPTX) ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent"></div>
                    <span>Exporting...</span>
                  </>
                ) : (
                  <>
                    <FiDownload size={18} />
                    <span>Export</span>
                  </>
                )}
              </button>
              
              {showExportMenu && !isExportingPDF && !isExportingPPTX && (
                <div className="absolute right-0 mt-2 w-48 bg-white rounded-lg shadow-lg border border-blue-200 py-1 z-50">
                  <button
                    onClick={handleExportPDF}
                    className="w-full text-left px-4 py-2 hover:bg-blue-50 flex items-center space-x-2 text-gray-700 hover:text-blue-700 transition-colors"
                  >
                    <FiFileText size={18} className="text-blue-600" />
                    <span>Export as PDF</span>
                  </button>
                  <button
                    onClick={handleExportPPTX}
                    className="w-full text-left px-4 py-2 hover:bg-blue-50 flex items-center space-x-2 text-gray-700 hover:text-blue-700 transition-colors"
                  >
                    <FiFile size={18} className="text-blue-600" />
                    <span>Export as PowerPoint</span>
                  </button>
                  <button
                    onClick={handleSaveAsHTML}
                    className="w-full text-left px-4 py-2 hover:bg-blue-50 flex items-center space-x-2 text-gray-700 hover:text-blue-700 transition-colors"
                  >
                    <FiCode size={18} className="text-blue-600" />
                    <span>Save as HTML</span>
                  </button>
                </div>
              )}
            </div>
            <button
              onClick={() => setIsPresentationMode(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-r-lg hover:bg-blue-700 transition-colors border-l border-blue-500"
            >
              <FiPlay size={16} />
              Present
            </button>
          </div>
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
            Generated Slides
          </button>
          {isDebugMode() && (
            <>
              <button
                onClick={() => rawHtml && setViewMode('rawhtml')}
                className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
                  !rawHtml
                    ? 'border-transparent text-gray-300 cursor-not-allowed'
                    : viewMode === 'rawhtml'
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-600 hover:text-gray-800 hover:border-gray-300'
                }`}
                disabled={!rawHtml}
                title={!rawHtml ? 'Generate slides first to enable this view' : 'View raw HTML rendered in iframe'}
              >
                Raw HTML (Rendered)
              </button>
              <button
                onClick={() => rawHtml && setViewMode('rawtext')}
                className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
                  !rawHtml
                    ? 'border-transparent text-gray-300 cursor-not-allowed'
                    : viewMode === 'rawtext'
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-600 hover:text-gray-800 hover:border-gray-300'
                }`}
                disabled={!rawHtml}
                title={!rawHtml ? 'Generate slides first to enable this view' : 'View raw HTML source code'}
              >
                Raw HTML (Text)
              </button>
            </>
          )}
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-hidden">
        {viewMode === 'tiles' && (
          <div className="h-full overflow-y-auto">
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
          <div
            key={slide.slide_id}
            ref={(el) => {
              if (el) {
                slideRefs.current.set(index, el);
              } else {
                slideRefs.current.delete(index);
              }
            }}
          >
            <SlideTile
              slide={slide}
              slideDeck={slideDeck}
              index={index}
              onDelete={() => handleDeleteSlide(index)}
              onDuplicate={() => handleDuplicateSlide(index)}
              onUpdate={(html) => handleUpdateSlide(index, html)}
            />
          </div>
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

      {isPresentationMode && slideDeck && (
        <PresentationMode
          slideDeck={slideDeck}
          onExit={() => setIsPresentationMode(false)}
          startIndex={0}
        />
      )}
    </div>
  );
};
