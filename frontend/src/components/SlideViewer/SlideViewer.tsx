import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { SlideDeck } from '../../types/slide';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';
import { ViewerProvider, useViewer } from '../../contexts/ViewerContext';
import { SlideStage } from './SlideStage';
import { ThumbnailRibbon } from './ThumbnailRibbon';
import { FeedbackDrawer } from './FeedbackDrawer';
import { loadSeen, markSeen } from './seenState';

interface SlideViewerProps {
  slideDeck: SlideDeck | null;
  deckKey: string;                 // scopes seen-state; use the session id
  findings: SlideFinding[];
  callbacks: DrawerCallbacks;
  onReorder: (from: number, to: number) => void;
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
 * Iframes: when focus moves inside the sandboxed slide iframe, document.activeElement
 * in the parent is the <iframe> element itself (tagName 'IFRAME'). isTypingTarget
 * returns false for IFRAME, so paging keys still fire. This is CORRECT — the stage
 * iframe uses sandbox="allow-scripts" (no allow-forms), so there are no real input
 * fields inside it that a user can type into. Paging whilst focused on the iframe
 * is expected and desirable behaviour.
 */
function isTypingTarget(el: Element | null): boolean {
  if (!el) return false;
  const node = el as HTMLElement;
  if (node.isContentEditable) return true;
  const tag = node.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

const ViewerBody: React.FC<Omit<SlideViewerProps, 'slideDeck'> & { slideDeck: SlideDeck }> = ({
  slideDeck, deckKey, findings, callbacks, onReorder,
}) => {
  const { currentIndex, next, prev, first, last, activeTab, drawerOpen } = useViewer();
  const [seen, setSeen] = useState<Set<string>>(() => loadSeen(deckKey));
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const stageRef = useRef<HTMLDivElement | null>(null);

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
  }, [next, prev, first, last]);

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

  return (
    <div data-testid="slide-viewer" className="flex h-full min-h-0 flex-1">
      <ThumbnailRibbon
        slideDeck={slideDeck}
        unseenSlideIndices={unseenSlideIndices}
        onReorder={onReorder}
      />
      <div className="flex min-h-0 flex-1 flex-col">
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
};

export const SlideViewer: React.FC<SlideViewerProps> = ({ slideDeck, ...rest }) => {
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
      <ViewerBody slideDeck={slideDeck} {...rest} />
    </ViewerProvider>
  );
};
