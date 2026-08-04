import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Edit3, LayoutGrid, Trash2 } from 'lucide-react';
import { Button } from '@/ui/button';
import { Tooltip } from '../common/Tooltip';
import type { SlideDeck } from '../../types/slide';
import type { VerificationResult } from '../../types/verification';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';
import { ViewerProvider, useViewer } from '../../contexts/ViewerContext';
import { SlideStage } from './SlideStage';
import { ThumbnailRibbon } from './ThumbnailRibbon';
import { FeedbackDrawer } from './FeedbackDrawer';
import { loadSeen, markSeen } from './seenState';
import { HTMLEditorModal } from '../SlidePanel/HTMLEditorModal';
import { VerificationBadge } from '../SlidePanel/VerificationBadge';
import { ConfirmDialog } from '../ConfirmDialog';
import { PresentationMode } from '../PresentationMode';
import { api } from '../../services/api';
import { useAutoVerification } from '../../hooks/useAutoVerification';

interface SlideContext {
  indices: number[];
  slide_htmls: string[];
}

interface SlideViewerProps {
  slideDeck: SlideDeck | null;
  deckKey: string;                 // scopes seen-state; use the session id
  findings: SlideFinding[];
  callbacks: DrawerCallbacks;
  onReorder: (from: number, to: number) => void;
  // CRUD props (optional — absent in read-only contexts)
  onSlideChange?: (slideDeck: SlideDeck) => void;
  onSendMessage?: (content: string, slideContext?: SlideContext) => void;
  readOnly?: boolean;
  lockedBy?: string | null;
  onVerificationComplete?: () => void;
  sessionId?: string | null;
}

export interface SlideViewerHandle {
  openPresentationMode: () => void;
}

/**
 * True when focus is somewhere that consumes arrow keys, so paging must not fire.
 * Checked on the active element rather than relying on stopPropagation, so future
 * editable regions on the stage (workstream 8) are covered automatically.
 *
 * Shadow roots: if a shadow host is focused, document.activeElement is the host
 * element, not the inner shadow element. For this app there are no shadow-DOM inputs
 * in the viewer, so this is a non-issue — a shadow host is not a typing target.
 *
 * Iframes: when focus moves inside the slide iframe, keydown events fire in the
 * iframe's separate browsing context and never reach the parent window listener.
 * In the parent, document.activeElement becomes the <iframe> element itself
 * (tagName 'IFRAME'). isTypingTarget returns false for IFRAME, so paging keys
 * still fire when focus is on the iframe — correct behaviour for this viewer.
 */
function isTypingTarget(el: Element | null): boolean {
  if (!el) return false;
  const node = el as HTMLElement;
  if (node.isContentEditable) return true;
  const tag = node.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

// Internal: renders the viewer body, always within a ViewerProvider.
const ViewerBody = forwardRef<
  SlideViewerHandle,
  Omit<SlideViewerProps, 'slideDeck'> & { slideDeck: SlideDeck }
>(({
  slideDeck, deckKey, findings, callbacks, onReorder,
  onSlideChange, onSendMessage, readOnly = false, lockedBy = null,
  onVerificationComplete, sessionId,
}, ref) => {
  const { currentIndex, next, prev, first, last, activeTab, drawerOpen } = useViewer();
  const [seen, setSeen] = useState<Set<string>>(() => loadSeen(deckKey));
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const stageRef = useRef<HTMLDivElement | null>(null);

  // Stage CRUD state
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  // Capture the slide index at the moment the modal is opened so that concurrent
  // paging (Finding 4) cannot redirect the edit/delete onto a different slide.
  const [indexWhenOpened, setIndexWhenOpened] = useState<number>(0);

  // Verification results keyed by slide_id (not array index) so deck mutations
  // (delete, reorder) cannot shift the index → result mapping (Finding 6).
  const [verificationResults, setVerificationResults] = useState<
    Map<string, VerificationResult | undefined>
  >(() => {
    const m = new Map<string, VerificationResult | undefined>();
    slideDeck.slides.forEach((s) => { m.set(s.slide_id, s.verification); });
    return m;
  });
  const [isManualVerifying, setIsManualVerifying] = useState(false);
  // Per-slide stale tracking: a Set of slide_ids edited after their last verification.
  const [staleSlideIds, setStaleSlideIds] = useState<Set<string>>(new Set());
  const [isPresentationMode, setIsPresentationMode] = useState(false);
  const deckEditCounterRef = useRef(0);
  const slideDeckRef = useRef(slideDeck);
  slideDeckRef.current = slideDeck;

  const isVersionConflict = (error: unknown): boolean =>
    error instanceof Error && 'status' in error && (error as { status: unknown }).status === 409;

  const refreshDeck = async () => {
    if (!sessionId || !onSlideChange) return;
    const result = await api.getSlides(sessionId);
    if (result.slide_deck) onSlideChange(result.slide_deck);
  };

  // Sync verification results (keyed by slide_id) when deck changes.
  // Also clear all stale flags — a fresh deck fetch means verifications are current.
  useEffect(() => {
    setVerificationResults(prev => {
      const m = new Map(prev);
      slideDeck.slides.forEach((s) => {
        if (s.verification !== m.get(s.slide_id)) m.set(s.slide_id, s.verification);
      });
      return m;
    });
    setStaleSlideIds(new Set());
  }, [slideDeck]);

  // When the deck changes, reload persisted seen-state and clear transient dismissals.
  // dismissed must also reset: a finding dismissed in deck A must not suppress a
  // finding with the same id in deck B (or leave ghost entries filtering findings
  // that don't exist in the new deck).
  useEffect(() => {
    setSeen(loadSeen(deckKey));
    setDismissed(new Set());
  }, [deckKey]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(document.activeElement)) return;
      // Finding 4: suppress paging while the HTML editor or delete confirm dialog is open.
      if (isEditing || showDeleteConfirm) return;
      switch (e.key) {
        case 'ArrowRight': case 'ArrowDown': case 'PageDown': e.preventDefault(); next(); break;
        case 'ArrowLeft':  case 'ArrowUp':   case 'PageUp':   e.preventDefault(); prev(); break;
        case 'Home': e.preventDefault(); first(); break;
        case 'End':  e.preventDefault(); last();  break;
        // Escape returns focus from the drawer (or anywhere outside the stage) to the stage.
        // `=== false` is intentional here: when stageRef is null, optional chaining yields
        // `undefined`, and `undefined !== false`, so the body is skipped — correct, because
        // there is nothing to focus. Using `!stageRef.current?.contains(...)` would be wrong:
        // `!undefined === true` would attempt focus on a null ref. When focus IS inside the
        // stage, contains() returns `true` → `true === false` → skip (already focused). When
        // focus is elsewhere, contains() returns `false` → `false === false` → focus moves.
        case 'Escape':
          if (stageRef.current?.contains(document.activeElement) === false) {
            stageRef.current?.focus();
          }
          break;
        default: break;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [next, prev, first, last, isEditing, showDeleteConfirm]);

  const visible = useMemo(
    () => findings.filter(f => !dismissed.has(f.id)),
    [findings, dismissed],
  );

  // Risk: if the parent passes a fresh array literal for `findings` on every render,
  // `visible` (and therefore `currentFindings`) will be a new array every render.
  // The seen-marking effect below would re-run every render, though the early-return
  // guard prevents an infinite loop. Task 8 wires the parent — flag this to ensure
  // the findings prop is stabilised (e.g. via useMemo or useRef) at the call site.
  const currentFindings = useMemo(
    () => visible.filter(f => f.slideIndex === currentIndex),
    [visible, currentIndex],
  );

  const unseenSlideIndices = useMemo(() => {
    const set = new Set<number>();
    for (const f of visible) if (!seen.has(f.id)) set.add(f.slideIndex);
    return set;
  }, [visible, seen]);

  // Viewing the feedback tab for a slide marks that slide's findings as read (spec §5.1.1).
  //
  // Why `seen` is absent from the dependency array:
  //   This effect SETS `seen` via setSeen — including `seen` directly would cause the
  //   effect to re-run every time it marks something, producing an update loop.
  //   The current value is read through the functional-update callback (`prev`), which
  //   is safe: React guarantees `prev` is the latest committed value. The early-return
  //   `if (unread.length === 0) return prev` returns the SAME Set reference, so React
  //   does not schedule a re-render — the loop is genuinely broken, not just throttled.
  //
  // `seen` is never referenced in this effect body (only `prev` inside the setter), so
  // eslint's react-hooks/exhaustive-deps does not flag it as missing — no disable needed.
  useEffect(() => {
    if (!drawerOpen || activeTab !== 'feedback') return;
    const ids = currentFindings.map(f => f.id);
    if (ids.length === 0) return;
    setSeen(prev => {
      const unread = ids.filter(id => !prev.has(id));
      if (unread.length === 0) return prev;      // same reference → no re-render
      markSeen(deckKey, unread);
      return new Set([...prev, ...unread]);
    });
  }, [drawerOpen, activeTab, currentFindings, deckKey]);

  const handleDismiss = useCallback((findingId: string) => {
    setDismissed(prev => new Set(prev).add(findingId));
    markSeen(deckKey, [findingId]);
    setSeen(prev => new Set(prev).add(findingId));
    callbacks.onDismissFinding(findingId);
  }, [callbacks, deckKey]);

  // CRUD handlers for the stage toolbar.
  // Both use `indexWhenOpened` (captured at modal-open time) rather than `currentIndex`
  // so that paging after the modal opens cannot redirect the operation to a different slide.
  const handleDeleteConfirm = async () => {
    if (!sessionId || !onSlideChange) return;
    setShowDeleteConfirm(false);
    const editId = ++deckEditCounterRef.current;
    try {
      await api.deleteSlide(indexWhenOpened, sessionId);
      const result = await api.getSlides(sessionId);
      if (result.slide_deck && deckEditCounterRef.current === editId) {
        onSlideChange(result.slide_deck);
      }
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

  const handleUpdateSlide = async (html: string) => {
    if (!sessionId || !onSlideChange) return;
    const editId = ++deckEditCounterRef.current;
    const slideId = slideDeck.slides[indexWhenOpened]?.slide_id;
    try {
      await api.updateSlide(indexWhenOpened, html, sessionId);
      const result = await api.getSlides(sessionId);
      if (result.slide_deck && deckEditCounterRef.current === editId) {
        onSlideChange(result.slide_deck);
      }
      if (slideId) {
        setStaleSlideIds(prev => new Set(prev).add(slideId));
      }
    } catch (error) {
      console.error('Failed to update:', error);
      if (isVersionConflict(error)) {
        alert('This deck was modified by another user. Refreshing to latest version.');
        await refreshDeck();
      }
      throw error;
    }
  };

  const handleVerify = async () => {
    if (!sessionId || isManualVerifying) return;
    const slideId = slideDeck.slides[currentIndex]?.slide_id;
    setIsManualVerifying(true);
    try {
      const result = await api.verifySlide(sessionId, currentIndex);
      const verification: VerificationResult = {
        ...result,
        rating: result.rating as VerificationResult['rating'],
        timestamp: new Date().toISOString(),
      };
      if (slideId) {
        setVerificationResults(prev => new Map(prev).set(slideId, verification));
        setStaleSlideIds(prev => {
          const next = new Set(prev);
          next.delete(slideId);
          return next;
        });
      }
      // Persist to server
      try {
        await api.updateSlideVerification(currentIndex, sessionId, verification);
        const currentDeck = slideDeckRef.current;
        if (onSlideChange && currentDeck) {
          const updatedSlides = [...currentDeck.slides];
          updatedSlides[currentIndex] = { ...updatedSlides[currentIndex], verification };
          onSlideChange({ ...currentDeck, slides: updatedSlides });
        }
      } catch {
        // Non-fatal — UI already updated
      }
      onVerificationComplete?.();
    } catch (error) {
      console.error('Verification failed:', error);
    } finally {
      setIsManualVerifying(false);
    }
  };

  // Finding 3: "Optimize layout" for the current slide via the chat agent.
  const handleOptimizeLayout = useCallback(() => {
    if (!onSendMessage) return;
    const slide = slideDeck.slides[currentIndex];
    if (!slide) return;
    const slideContext: SlideContext = {
      indices: [currentIndex],
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
  }, [onSendMessage, currentIndex, slideDeck.slides]);

  // Finding 2: auto-verify newly-generated slides on the viewer path.
  useAutoVerification({
    slideDeck,
    sessionId: sessionId ?? null,
    onVerificationComplete,
    onSlideChange,
    deckEditCounterRef,
  });

  // Expose presentation mode control via ref
  useImperativeHandle(ref, () => ({
    openPresentationMode: () => setIsPresentationMode(true),
  }));

  const currentSlide = slideDeck.slides[currentIndex];

  return (
    <div data-testid="slide-viewer" className="flex h-full min-h-0 flex-1">
      {/* Delete confirm dialog */}
      <ConfirmDialog
        open={showDeleteConfirm}
        title="Delete Slide"
        message={`Delete slide ${indexWhenOpened + 1}?`}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setShowDeleteConfirm(false)}
      />

      {/* HTML editor modal */}
      {isEditing && currentSlide && (
        <HTMLEditorModal
          html={slideDeck.slides[indexWhenOpened]?.html ?? currentSlide.html}
          slideDeck={slideDeck}
          slide={slideDeck.slides[indexWhenOpened] ?? currentSlide}
          onSave={async (html) => {
            await handleUpdateSlide(html);
            setIsEditing(false);
          }}
          onCancel={() => setIsEditing(false)}
        />
      )}

      {/* Presentation mode */}
      {isPresentationMode && (
        <PresentationMode
          slideDeck={slideDeck}
          onExit={() => setIsPresentationMode(false)}
          startIndex={currentIndex}
        />
      )}

      <ThumbnailRibbon
        slideDeck={slideDeck}
        unseenSlideIndices={unseenSlideIndices}
        onReorder={onReorder}
      />
      <div className="flex min-h-0 flex-1 flex-col">
        {/* Stage toolbar — per-slide CRUD controls */}
        {!readOnly && currentSlide && (
          <div
            data-testid="stage-toolbar"
            className="flex shrink-0 items-center justify-between border-b border-border bg-card px-3 py-1.5"
          >
            {lockedBy && (
              <span className="text-xs text-amber-700">
                <span className="font-medium">{lockedBy}</span> is editing
              </span>
            )}
            <div className="ml-auto flex items-center gap-1">
              {/* Finding 5: wrap VerificationBadge so data-testid reaches the DOM */}
              <span data-testid="stage-verification-badge">
                <VerificationBadge
                  slideIndex={currentIndex}
                  sessionId={sessionId ?? ''}
                  verificationResult={verificationResults.get(currentSlide.slide_id)}
                  isVerifying={isManualVerifying}
                  onVerify={handleVerify}
                  isStale={staleSlideIds.has(currentSlide.slide_id)}
                />
              </span>
              {/* Finding 3: Optimize layout button */}
              {onSendMessage && (
                <Tooltip text="Optimize layout">
                  <Button
                    data-testid="stage-optimize-layout"
                    variant="ghost"
                    size="icon"
                    onClick={handleOptimizeLayout}
                    className="h-7 w-7"
                    aria-label="Optimize slide layout"
                  >
                    <LayoutGrid className="size-3.5" />
                  </Button>
                </Tooltip>
              )}
              <Tooltip text="Edit slide HTML">
                <Button
                  data-testid="stage-edit-slide"
                  variant="ghost"
                  size="icon"
                  onClick={() => {
                    setIndexWhenOpened(currentIndex);
                    setIsEditing(true);
                  }}
                  className="h-7 w-7"
                  aria-label="Edit slide HTML"
                >
                  <Edit3 className="size-3.5" />
                </Button>
              </Tooltip>
              <Tooltip text="Delete slide" align="end">
                <Button
                  data-testid="stage-delete-slide"
                  variant="ghost"
                  size="icon"
                  onClick={() => {
                    setIndexWhenOpened(currentIndex);
                    setShowDeleteConfirm(true);
                  }}
                  className="h-7 w-7 text-destructive hover:text-destructive"
                  aria-label="Delete slide"
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </Tooltip>
            </div>
          </div>
        )}

        {/* tabIndex makes the stage a focus target so Escape can return focus here. */}
        <div ref={stageRef} tabIndex={-1} className="flex min-h-0 flex-1 outline-none">
          <SlideStage
            slides={slideDeck.slides}
            css={slideDeck.css}
            externalScripts={slideDeck.external_scripts}
          />
        </div>
        <FeedbackDrawer
          findings={currentFindings}
          hasUnseen={currentFindings.some(f => !seen.has(f.id))}
          callbacks={{ ...callbacks, onDismissFinding: handleDismiss }}
        />
      </div>
    </div>
  );
});

ViewerBody.displayName = 'ViewerBody';

export const SlideViewer = forwardRef<SlideViewerHandle, SlideViewerProps>(
  ({ slideDeck, ...rest }, ref) => {
    if (!slideDeck || slideDeck.slides.length === 0) {
      return (
        <div
          data-testid="slide-viewer-empty"
          className="flex flex-1 items-center justify-center text-sm text-muted-foreground"
        >
          No slides yet — generate a deck to get started.
        </div>
      );
    }
    return (
      <ViewerProvider slideCount={slideDeck.slides.length}>
        <ViewerBody ref={ref} slideDeck={slideDeck} {...rest} />
      </ViewerProvider>
    );
  }
);

SlideViewer.displayName = 'SlideViewer';
