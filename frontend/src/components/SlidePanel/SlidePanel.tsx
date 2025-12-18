import React, { useEffect, useState, useRef, useCallback } from 'react';
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
import { api, type StreamEvent } from '../../services/api';
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
  const [optimizingSlideIndex, setOptimizingSlideIndex] = useState<number | null>(null);
  const cancelOptimizeRef = useRef<(() => void) | null>(null);
  const { selectedIndices, setSelection, clearSelection } = useSelection();
  const { sessionId } = useSession();
  const slideRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  
  // Auto-verification state
  const [isAutoVerifying, setIsAutoVerifying] = useState(false);
  const [verifyingSlides, setVerifyingSlides] = useState<Set<number>>(new Set());
  const autoVerifyTriggeredRef = useRef<Set<string>>(new Set()); // Track which content hashes we've tried to verify
  
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
        await api.reorderSlides(newOrder, sessionId);
        // Fetch full deck to get verification merged from verification_map
        const result = await api.getSlides(sessionId);
        if (result.slide_deck) {
          onSlideChange(result.slide_deck);
        }
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
      await api.deleteSlide(index, sessionId);
      // Fetch full deck to get verification merged from verification_map
      const result = await api.getSlides(sessionId);
      if (result.slide_deck) {
        onSlideChange(result.slide_deck);
      }
      clearSelection();
    } catch (error) {
      console.error('Failed to delete:', error);
      alert('Failed to delete slide');
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

  const handleVerificationUpdate = async (index: number, verification: import('../../types/verification').VerificationResult | null) => {
    if (!slideDeck || !sessionId) return;

    try {
      // Save verification to backend but DON'T replace the whole deck
      // This prevents overwriting other slide data (like charts)
      await api.updateSlideVerification(index, sessionId, verification);
      
      // Update only the verification field locally
      const updatedSlides = [...slideDeck.slides];
      updatedSlides[index] = { ...updatedSlides[index], verification: verification || undefined };
      onSlideChange({ ...slideDeck, slides: updatedSlides });
    } catch (error) {
      console.error('Failed to update verification:', error);
      // Don't throw - verification persistence is non-critical
    }
  };

  const handleOptimizeLayout = (index: number) => {
    if (!slideDeck || !sessionId || optimizingSlideIndex !== null) return;

    const slide = slideDeck.slides[index];
    if (!slide) return;

    setOptimizingSlideIndex(index);
    clearSelection();

    const slideContext = {
      indices: [index],
      slide_htmls: [slide.html],
    };

    const message = `Optimize the layout of the slide to prevent content overflow. Return only the HTML for this slide, no other text.

      CRITICAL REQUIREMENTS:
      1. Preserve ALL <canvas> elements exactly - do NOT modify, remove, rename, or change their id attributes
      2. Keep all canvas elements in the same positions relative to their containers
      3. Do NOT modify any chart-related HTML structure
      4. Only adjust spacing, padding, margins, font sizes, and positioning of text and container elements
      5. Maintain the 1280x720px slide dimensions
      6. Do NOT add, remove, or modify any <script> tags - chart scripts are handled separately

      Focus on optimizing text layout, container sizing, and spacing to prevent content overflow while keeping all chart elements completely unchanged.`;

    // Handle streaming events
    const handleStreamEvent = (event: StreamEvent) => {
      switch (event.type) {
        case 'error':
          console.error('Optimize layout error:', event.error);
          alert(event.error || 'Failed to optimize layout');
          setOptimizingSlideIndex(null);
          break;

        case 'complete':
          setOptimizingSlideIndex(null);
          // Always fetch full deck to get verification merged from verification_map
          api.getSlides(sessionId).then((result) => {
            if (result.slide_deck) {
              onSlideChange(result.slide_deck);
            }
          }).catch((err) => {
            console.error('Failed to fetch updated slides:', err);
            alert('Failed to fetch updated slides after optimization');
          });
          break;
      }
    };

    // Start streaming
    cancelOptimizeRef.current = api.sendChatMessage(
      sessionId,
      message,
      slideContext,
      handleStreamEvent,
      (err) => {
        console.error('Optimize layout error:', err);
        alert(err.message || 'Failed to optimize layout');
        setOptimizingSlideIndex(null);
      }
    );
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (cancelOptimizeRef.current) {
        cancelOptimizeRef.current();
      }
    };
  }, []);

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

  // Auto-verify slides that don't have verification
  const runAutoVerification = useCallback(async (slidesToVerify: Array<{ index: number; contentHash: string }>) => {
    if (!sessionId || slidesToVerify.length === 0 || isAutoVerifying) return;

    setIsAutoVerifying(true);
    console.log(`[Auto-verify] Starting verification for ${slidesToVerify.length} slides`);

    // Mark all slides as being verified
    setVerifyingSlides(new Set(slidesToVerify.map(s => s.index)));

    // Verify slides in parallel
    const verificationPromises = slidesToVerify.map(async ({ index, contentHash }) => {
      try {
        // Mark this content hash as attempted (prevent re-triggering)
        autoVerifyTriggeredRef.current.add(contentHash);
        
        console.log(`[Auto-verify] Verifying slide ${index + 1} (hash: ${contentHash.substring(0, 8)}...)`);
        await api.verifySlide(sessionId, index);
        console.log(`[Auto-verify] Slide ${index + 1} verified`);
        return { index, success: true };
      } catch (error) {
        console.error(`[Auto-verify] Failed to verify slide ${index + 1}:`, error);
        return { index, success: false, error };
      }
    });

    await Promise.all(verificationPromises);

    // Refresh slides to get updated verification results (merged from verification_map)
    try {
      const result = await api.getSlides(sessionId);
      if (result.slide_deck) {
        onSlideChange(result.slide_deck);
      }
    } catch (error) {
      console.error('[Auto-verify] Failed to refresh slides:', error);
    }

    setVerifyingSlides(new Set());
    setIsAutoVerifying(false);
    console.log('[Auto-verify] Completed');
  }, [sessionId, isAutoVerifying, onSlideChange]);

  // Effect to trigger auto-verification when slides change
  useEffect(() => {
    if (!slideDeck || !sessionId || isAutoVerifying) return;

    // Find slides that need verification (no verification and not already attempted)
    const slidesNeedingVerification = slideDeck.slides
      .map((slide, index) => ({
        index,
        slide,
        contentHash: slide.content_hash || '',
      }))
      .filter(({ slide, contentHash }) => {
        // Skip if already has verification
        if (slide.verification) return false;
        // Skip if no content hash (shouldn't happen, but be safe)
        if (!contentHash) return false;
        // Skip if we've already tried to verify this content
        if (autoVerifyTriggeredRef.current.has(contentHash)) return false;
        return true;
      });

    if (slidesNeedingVerification.length > 0) {
      console.log(`[Auto-verify] Found ${slidesNeedingVerification.length} slides needing verification`);
      runAutoVerification(slidesNeedingVerification);
    }
  }, [slideDeck, sessionId, isAutoVerifying, runAutoVerification]);

  // Clear auto-verify tracking when session changes
  useEffect(() => {
    autoVerifyTriggeredRef.current.clear();
  }, [sessionId]);

  const handleSaveAsHTML = () => {
    if (!slideDeck) return;

    // Generate HTML for each slide with its own container
    const slidesHtml = slideDeck.slides
      .map((slide, index) => {
        const slideScripts = slide.scripts || '';
        return `
    <div class="slide-wrapper" data-slide-index="${index}">
      <div class="slide-container">
        ${slide.html}
      </div>
      ${slideScripts ? `<script>
        (function() {
          ${slideScripts}
        })();
      </script>` : ''}
    </div>`;
      })
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
  ${externalScriptsHtml}
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }
    html, body {
      width: 100%;
      height: 100%;
      overflow: auto;
      background: #f9fafb;
    }
    body {
      padding: 40px 20px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 40px;
    }
    /* Slide wrapper - contains each slide with spacing */
    .slide-wrapper {
      width: 100%;
      max-width: 1280px;
      margin: 0 auto;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      page-break-after: always; /* For printing */
    }
    /* Slide container - maintains 16:9 aspect ratio */
    .slide-container {
      width: 1280px;
      height: 720px;
      max-width: 100%;
      max-height: calc(100vh - 80px);
      position: relative;
      background: #ffffff;
      overflow: auto;
      box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
      border-radius: 8px;
    }
    /* Ensure slide content fills container */
    .slide-container > * {
      width: 100%;
      min-height: 100%;
    }
    /* Chart canvas scaling */
    canvas {
      max-width: 100%;
      height: auto;
    }
    ${slideDeck.css}
  </style>
</head>
<body>
  ${slidesHtml}
  <script>
    // Wait for Chart.js to be available before running scripts
    function waitForChartJs(callback, maxAttempts = 50) {
      let attempts = 0;
      const check = () => {
        attempts++;
        if (typeof Chart !== 'undefined') {
          callback();
        } else if (attempts < maxAttempts) {
          setTimeout(check, 100);
        } else {
          console.error('Chart.js failed to load');
        }
      };
      check();
    }

    function initializeCharts() {
      console.log('Initializing charts for all slides...');
      try {
        // Individual slide scripts are already executed in their own IIFEs above
        // Deck-level scripts (if any) are also already wrapped in IIFEs
        ${slideDeck.scripts || ''}
        console.log('Charts initialized successfully');
      } catch (err) {
        console.error('Chart initialization error:', err);
      }
    }

    // Initialize charts after DOM is ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        waitForChartJs(initializeCharts);
      });
    } else {
      waitForChartJs(initializeCharts);
    }
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
              {isAutoVerifying && ` • Verifying ${verifyingSlides.size} slide${verifyingSlides.size !== 1 ? 's' : ''}...`}
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
              sessionId={sessionId || ''}
              onDelete={() => handleDeleteSlide(index)}
              onUpdate={(html) => handleUpdateSlide(index, html)}
              onVerificationUpdate={(verification) => handleVerificationUpdate(index, verification)}
              isAutoVerifying={verifyingSlides.has(index)}
              onOptimize={() => handleOptimizeLayout(index)}
              isOptimizing={optimizingSlideIndex === index}
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
