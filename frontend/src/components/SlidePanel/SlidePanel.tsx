import React, { useEffect, useState, useRef, useCallback, forwardRef, useImperativeHandle } from 'react';
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
import type { Slide, SlideDeck } from '../../types/slide';
import { SlideTile } from './SlideTile';
import { PresentationMode } from '../PresentationMode';
import { api } from '../../services/api';
import { useSelection } from '../../contexts/SelectionContext';
import { exportSlideDeckToPDF } from '../../services/pdf_client';
import { useSession } from '../../contexts/SessionContext';
import { useToast } from '../../contexts/ToastContext';

interface SlideContext {
  indices: number[];
  slide_htmls: string[];
}

interface SlidePanelProps {
  slideDeck: SlideDeck | null;
  rawHtml: string | null;
  onSlideChange?: (slideDeck: SlideDeck) => void;
  scrollToSlide?: { index: number; key: number } | null;
  onSendMessage?: (content: string, slideContext?: SlideContext) => void;
  onExportStatusChange?: (status: string | null) => void;
  versionKey?: string;
  readOnly?: boolean;
  canManage?: boolean;
  lockedBy?: string | null;
  onVerificationComplete?: () => void;
}

export interface SlidePanelHandle {
  exportPDF: () => void;
  exportPPTX: () => void;
  exportHTML: () => void;
  openPresentationMode: () => void;
}

type ViewMode = 'tiles' | 'rawhtml' | 'rawtext';

const EMPTY_MENTIONS: Array<{ id: number; user_name: string; content: string; created_at: string }> = [];
const EPOCH_ISO = new Date(0).toISOString();

function SlidePanelComponent(props: SlidePanelProps, ref: React.Ref<SlidePanelHandle>) {
  const { slideDeck, rawHtml: _rawHtml, onSlideChange, scrollToSlide, onSendMessage, onExportStatusChange, versionKey: _versionKey, readOnly = false, canManage = false, lockedBy = null, onVerificationComplete } = props;
  const [_isReordering, setIsReordering] = useState(false);
  const [viewMode, _setViewMode] = useState<ViewMode>('tiles');
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [isExportingPPTX, setIsExportingPPTX] = useState(false);
  const [_exportProgress, setExportProgress] = useState<{ current: number; total: number; status: string } | null>(null);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);
  const [isPresentationMode, setIsPresentationMode] = useState(false);
  const [optimizingSlideIndex, setOptimizingSlideIndex] = useState<number | null>(null);
  const { selectedIndices, setSelection, clearSelection } = useSelection();
  const { sessionId } = useSession();
  const { showToast } = useToast();
  const slideRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // Batch comment counts per slide (single request instead of N+1)
  const [commentCountsBySlide, setCommentCountsBySlide] = useState<Record<string, number>>({});

  const refreshCommentCounts = useCallback(() => {
    if (!sessionId) return;
    api.listComments(sessionId).then(({ comments }) => {
      const counts: Record<string, number> = {};
      for (const c of comments) {
        counts[c.slide_id] = (counts[c.slide_id] || 0) + 1;
      }
      setCommentCountsBySlide(counts);
    }).catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    refreshCommentCounts();
  }, [refreshCommentCounts]);

  // Mentions per slide (for notification badges)
  const [mentionsBySlide, setMentionsBySlide] = useState<Record<string, Array<{ id: number; user_name: string; content: string; created_at: string }>>>({});
  const [mentionsLastSeenMap, setMentionsLastSeenMap] = useState<Record<string, string>>(() => {
    try {
      const stored = localStorage.getItem('tellr_mentions_last_seen_map');
      return stored ? JSON.parse(stored) : {};
    } catch { return {}; }
  });

  const fetchMentions = useCallback(() => {
    if (!sessionId) return;
    api.listMentions(sessionId).then(({ mentions }) => {
      const bySlide: Record<string, Array<{ id: number; user_name: string; content: string; created_at: string }>> = {};
      for (const m of mentions) {
        if (!bySlide[m.slide_id]) bySlide[m.slide_id] = [];
        bySlide[m.slide_id].push({ id: m.id, user_name: m.user_name, content: m.content, created_at: m.created_at });
      }
      setMentionsBySlide(bySlide);
    }).catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    fetchMentions();
  }, [fetchMentions]);

  const handleMarkMentionsSeen = useCallback((slideId: string) => {
    const now = new Date().toISOString();
    setMentionsLastSeenMap(prev => {
      const next = { ...prev, [slideId]: now };
      localStorage.setItem('tellr_mentions_last_seen_map', JSON.stringify(next));
      return next;
    });
  }, []);

  // Auto-verification state
  const [isAutoVerifying, setIsAutoVerifying] = useState(false);
  const [verifyingSlides, setVerifyingSlides] = useState<Set<number>>(new Set());
  const autoVerifyTriggeredRef = useRef<Set<string>>(new Set());
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  const deckEditCounterRef = useRef(0);
  const slideDeckRef = useRef(slideDeck);
  slideDeckRef.current = slideDeck;
  
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const refreshDeck = async () => {
    if (!sessionId || !onSlideChange) return;
    const result = await api.getSlides(sessionId);
    if (result.slide_deck) onSlideChange(result.slide_deck);
  };

  const isVersionConflict = (error: unknown): boolean =>
    error instanceof Error && 'status' in error && (error as any).status === 409;

  const handleDragEnd = async (event: DragEndEvent) => {
    if (readOnly) return;
    const { active, over } = event;

    if (!over || !slideDeck) return;
    
    if (active.id !== over.id) {
      const oldIndex = slideDeck.slides.findIndex(s => s.slide_id === active.id);
      const newIndex = slideDeck.slides.findIndex(s => s.slide_id === over.id);

      const newSlides = arrayMove(slideDeck.slides, oldIndex, newIndex);
      onSlideChange?.({ ...slideDeck, slides: newSlides });

      if (!sessionId) {
        alert('Session not initialized');
        onSlideChange?.(slideDeck);
        return;
      }

      setIsReordering(true);
      const editId = ++deckEditCounterRef.current;
      try {
        const newOrder = newSlides.map((_, idx) => 
          slideDeck.slides.findIndex(s => s.slide_id === newSlides[idx].slide_id)
        );
        await api.reorderSlides(newOrder, sessionId);
        const result = await api.getSlides(sessionId);
        if (result.slide_deck && deckEditCounterRef.current === editId) {
          onSlideChange?.(result.slide_deck);
        }
        clearSelection();
      } catch (error) {
        console.error('Failed to reorder:', error);
        if (isVersionConflict(error)) {
          alert('This deck was modified by another user. Refreshing to latest version.');
          await refreshDeck();
        } else {
          onSlideChange?.(slideDeck);
          alert('Failed to reorder slides');
        }
      } finally {
        setIsReordering(false);
      }
    }
  };

  const handleDeleteSlide = async (index: number) => {
    if (readOnly || !slideDeck || !sessionId) return;
    
    if (!confirm(`Delete slide ${index + 1}?`)) return;

    const editId = ++deckEditCounterRef.current;
    try {
      await api.deleteSlide(index, sessionId);
      const result = await api.getSlides(sessionId);
      if (result.slide_deck && deckEditCounterRef.current === editId) {
        onSlideChange?.(result.slide_deck);
      }
      clearSelection();
    } catch (error) {
      console.error('Failed to delete:', error);
      if (isVersionConflict(error)) {
        alert('This deck was modified by another user. Refreshing to latest version.');
        await refreshDeck();
      } else {
        alert('Failed to delete slide');
      }
    }
  };

  const handleUpdateSlide = async (index: number, html: string) => {
    if (readOnly || !slideDeck || !sessionId) return;

    const editId = ++deckEditCounterRef.current;
    try {
      await api.updateSlide(index, html, sessionId);
      const result = await api.getSlides(sessionId);
      if (result.slide_deck && deckEditCounterRef.current === editId) {
        onSlideChange?.(result.slide_deck);
      }
      clearSelection();
    } catch (error) {
      console.error('Failed to update:', error);
      if (isVersionConflict(error)) {
        alert('This deck was modified by another user. Refreshing to latest version.');
        await refreshDeck();
      }
      throw error;
    }
  };

  const handleVerificationUpdate = async (index: number, verification: import('../../types/verification').VerificationResult | null) => {
    if (readOnly || !slideDeck || !sessionId) return;

    try {
      await api.updateSlideVerification(index, sessionId, verification);

      if (verification !== null && onSlideChange) {
        const currentDeck = slideDeckRef.current || slideDeck;
        const updatedSlides = [...currentDeck.slides];
        updatedSlides[index] = { ...updatedSlides[index], verification };
        onSlideChange({ ...currentDeck, slides: updatedSlides });
      }
    } catch (error) {
      console.error('Failed to update verification:', error);
    }
  };

  const handleOptimizeLayout = (index: number) => {
    if (readOnly || !slideDeck || !onSendMessage || optimizingSlideIndex !== null) return;

    const slide = slideDeck.slides[index];
    if (!slide) return;

    setOptimizingSlideIndex(index);
    clearSelection();

    const slideContext = {
      indices: [index],
      slide_htmls: [slide.html],
    };

    const message = `Optimize the layout of this slide to make good use of the slide real estate whilst preventing content overflow. Return only the HTML for this slide, no other text.

      CRITICAL REQUIREMENTS:
      1. Preserve ALL <canvas> elements exactly - do NOT modify, remove, rename, or change their id attributes
      2. Keep all canvas elements in the same positions relative to their containers
      3. Do NOT modify any chart-related HTML structure
      4. Only adjust spacing, padding, margins, font sizes, and positioning of text and container elements
      5. Maintain the 1280x720px slide dimensions
      6. Do NOT add, remove, or modify any <script> tags - chart scripts are handled separately

      Focus on optimizing text layout, container sizing, and spacing while keeping all chart elements completely unchanged.`;

    onSendMessage(message, slideContext);
  };

  useEffect(() => {
    if (optimizingSlideIndex !== null) {
      setOptimizingSlideIndex(null);
    }
  }, [slideDeck]);

  const handleExportPDF = async () => {
    if (!slideDeck || isExportingPDF) return;

    setIsExportingPDF(true);
    setShowExportMenu(false);
    onExportStatusChange?.('Exporting PDF...');
    try {
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const filename = `${slideDeck.title || 'slides'}_${timestamp}.pdf`;
      
      await exportSlideDeckToPDF(slideDeck, filename, {
        format: 'a4',
        orientation: 'landscape',
        scale: 1.2,
        waitForCharts: 2000,
        imageQuality: 0.85,
      });
    } catch (error) {
      console.error('PDF export failed:', error);
      const message = error instanceof Error 
        ? error.message 
        : 'Failed to export PDF. Please try again.';
      alert(message);
    } finally {
      setIsExportingPDF(false);
      onExportStatusChange?.(null);
    }
  };

  const handleExportPPTX = async () => {
    if (!slideDeck || !sessionId || isExportingPPTX) return;

    setIsExportingPPTX(true);
    setShowExportMenu(false);
    setExportProgress({ current: 0, total: slideDeck.slides.length, status: 'Starting...' });
    onExportStatusChange?.('Starting export...');

    try {
      const blob = await api.exportToPPTX(
        sessionId, 
        true, 
        slideDeck,
        (progress, total, status) => {
          setExportProgress({ current: progress, total, status });
          onExportStatusChange?.(status);
        }
      );
      
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const timestamp = new Date().toISOString().slice(0, 10);
      a.download = `${slideDeck.title || 'slides'}_${timestamp}.pptx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      onExportStatusChange?.(null);
      showToast('PPTX downloaded', 'success');
    } catch (error) {
      console.error('PPTX export failed:', error);
      const message = error instanceof Error 
        ? error.message 
        : 'Failed to export PPTX. Please try again.';
      alert(message);
    } finally {
      setIsExportingPPTX(false);
      setExportProgress(null);
      onExportStatusChange?.(null);
    }
  };

  const handleSaveAsHTML = () => {
    if (!slideDeck) return;

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
      .map((src: string) => `<script src="${src}"></script>`)
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
    .slide-wrapper {
      width: 100%;
      max-width: 1280px;
      margin: 0 auto;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      page-break-after: always;
    }
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
    .slide-container > * {
      width: 100%;
      min-height: 100%;
    }
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
      try {
        ${slideDeck.scripts || ''}
      } catch (err) {
        console.error('Chart initialization error:', err);
      }
    }

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
  };

  useImperativeHandle(ref, () => ({
    exportPDF: handleExportPDF,
    exportPPTX: handleExportPPTX,
    exportHTML: handleSaveAsHTML,
    openPresentationMode: () => setIsPresentationMode(true),
  }));

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

  useEffect(() => {
    if (scrollToSlide != null && viewMode === 'tiles') {
      const slideElement = slideRefs.current.get(scrollToSlide.index);
      if (slideElement) {
        slideElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [scrollToSlide, viewMode]);

  const runAutoVerification = useCallback(async (slidesToVerify: Array<{ index: number; contentHash: string }>) => {
    if (!sessionId || slidesToVerify.length === 0 || isAutoVerifying) return;
    const capturedSessionId = sessionId;

    const editIdAtStart = deckEditCounterRef.current;
    setIsAutoVerifying(true);
    console.log(`[Auto-verify] Starting verification for ${slidesToVerify.length} slides`);

    setVerifyingSlides(new Set(slidesToVerify.map(s => s.index)));

    const verificationPromises = slidesToVerify.map(async ({ index, contentHash }) => {
      try {
        autoVerifyTriggeredRef.current.add(contentHash);
        console.log(`[Auto-verify] Verifying slide ${index + 1} (hash: ${contentHash.substring(0, 8)}...)`);
        await api.verifySlide(capturedSessionId, index);
        console.log(`[Auto-verify] Slide ${index + 1} verified`);
        return { index, success: true };
      } catch (error) {
        console.error(`[Auto-verify] Failed to verify slide ${index + 1}:`, error);
        return { index, success: false, error };
      }
    });

    await Promise.all(verificationPromises);

    if (sessionIdRef.current !== capturedSessionId) {
      console.log('[Auto-verify] Session changed, discarding stale results');
      setIsAutoVerifying(false);
      setVerifyingSlides(new Set());
      return;
    }

    try {
      const result = await api.getSlides(capturedSessionId);
      const currentDeck = slideDeckRef.current;
      if (result.slide_deck && currentDeck && deckEditCounterRef.current === editIdAtStart) {
        const serverSlides = result.slide_deck.slides || [];
        const mergedSlides = currentDeck.slides.map((localSlide) => {
          const match = serverSlides.find(
            (s: { content_hash?: string }) => s.content_hash && s.content_hash === localSlide.content_hash
          );
          if (match?.verification) {
            return { ...localSlide, verification: match.verification };
          }
          return localSlide;
        });
        onSlideChange?.({ ...currentDeck, slides: mergedSlides });
      }
    } catch (error) {
      console.error('[Auto-verify] Failed to refresh verification:', error);
    }

    setVerifyingSlides(new Set());
    setIsAutoVerifying(false);
    console.log('[Auto-verify] Completed');

    onVerificationComplete?.();
  }, [sessionId, isAutoVerifying, onSlideChange, onVerificationComplete]);

  useEffect(() => {
    if (!slideDeck || !sessionId || isAutoVerifying) return;

    const slidesNeedingVerification = slideDeck.slides
      .map((slide, index) => ({
        index,
        slide,
        contentHash: slide.content_hash || '',
      }))
      .filter(({ slide, contentHash }) => {
        if (slide.verification) return false;
        if (!contentHash) return false;
        if (autoVerifyTriggeredRef.current.has(contentHash)) return false;
        return true;
      });

    if (slidesNeedingVerification.length > 0) {
      console.log(`[Auto-verify] Found ${slidesNeedingVerification.length} slides needing verification`);
      runAutoVerification(slidesNeedingVerification);
    }
  }, [slideDeck, sessionId, isAutoVerifying, runAutoVerification]);

  useEffect(() => {
    autoVerifyTriggeredRef.current.clear();
    setIsAutoVerifying(false);
    setVerifyingSlides(new Set());
  }, [sessionId]);

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
    <div className="h-full flex flex-col bg-gray-50" data-testid="slide-panel">
      {lockedBy && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2.5 flex items-center gap-2">
          <svg className="w-4 h-4 text-amber-600 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          <span className="text-sm text-amber-800">
            <span className="font-semibold">{lockedBy}</span> is currently editing this session. You can view slides, add comments, and mention users but cannot edit slides.
          </span>
        </div>
      )}
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
              readOnly={readOnly}
              commentCount={commentCountsBySlide[slide.slide_id] ?? 0}
              onCommentCountRefresh={refreshCommentCounts}
              mentions={mentionsBySlide[slide.slide_id] ?? EMPTY_MENTIONS}
              mentionsLastSeen={mentionsLastSeenMap[slide.slide_id] ?? EPOCH_ISO}
              onMarkMentionsSeen={() => handleMarkMentionsSeen(slide.slide_id)}
              onMentionsRefresh={fetchMentions}
              canManage={canManage}
            />
          </div>
        ))}
                </SortableContext>
              </DndContext>
            </div>
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
}

export const SlidePanel = forwardRef(SlidePanelComponent);
