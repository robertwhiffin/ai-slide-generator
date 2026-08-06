import React, { useCallback, useRef } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '@/ui/button';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';
import { useViewer } from '../../contexts/ViewerContext';

interface FeedbackDrawerProps {
  findings: SlideFinding[];        // already scoped to the current slide
  callbacks: DrawerCallbacks;
  hasUnseen: boolean;
}

const CATEGORY_LABEL: Record<SlideFinding['category'], string> = {
  content: 'Content',
  design: 'Design',
  narrative: 'Narrative',
};

export const FeedbackDrawer: React.FC<FeedbackDrawerProps> = ({ findings, callbacks, hasUnseen }) => {
  const { drawerOpen, setDrawerOpen, drawerHeight, setDrawerHeight, activeTab, setActiveTab } = useViewer();
  // Captures the pointer's starting Y and the drawer's starting height at drag begin.
  const dragStart = useRef<{ y: number; h: number } | null>(null);

  // Pointer down: record drag origin and capture the pointer so moves/up fire
  // even when the pointer moves fast and leaves the thin handle element.
  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      dragStart.current = { y: e.clientY, h: drawerHeight };
      // Capture on the target (the handle div) so subsequent move/up events
      // continue to fire on it even if the pointer leaves the element bounds.
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [drawerHeight],
  );

  // Pointer move: grow the drawer when dragging up (startY - currentY > 0).
  // setDrawerHeight already clamps to [96, 480] — no re-clamp needed here.
  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragStart.current) return;
      setDrawerHeight(dragStart.current.h + (dragStart.current.y - e.clientY));
    },
    [setDrawerHeight],
  );

  // Clear drag state on both pointer-up and pointer-cancel (e.g. browser gesture
  // interruption), so the handle cannot be left stuck in drag mode.
  const onDragEnd = useCallback(() => {
    dragStart.current = null;
  }, []);

  return (
    <div data-testid="feedback-drawer" className="flex flex-col border-t border-border bg-card">
      {drawerOpen && (
        // Resize handle: visually 1px but padded to 8px tall for an ergonomic
        // grab target. aria-role and label make it accessible.
        <div
          data-testid="drawer-resize-handle"
          role="separator"
          aria-label="Drag to resize feedback drawer"
          aria-orientation="horizontal"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onDragEnd}
          onPointerCancel={onDragEnd}
          className="flex cursor-row-resize items-center py-[3.5px]"
        >
          {/* The visible 1px line sits inside the padded hit area. */}
          <div className="h-px w-full bg-border hover:bg-primary/40" />
        </div>
      )}

      <div className="flex items-center gap-1 px-2 py-1">
        {/* Tabbed shell: one tab today; 'notes' lands as a second tab later
            (spec §5.1). Building the shell now makes that additive. */}
        <button
          type="button"
          data-testid="drawer-tab-feedback"
          data-active={activeTab === 'feedback' ? 'true' : 'false'}
          onClick={() => setActiveTab('feedback')}
          className={[
            'relative rounded-t px-3 py-1.5 text-xs font-medium',
            activeTab === 'feedback' ? 'bg-muted text-foreground' : 'text-muted-foreground',
          ].join(' ')}
        >
          AI feedback
          {/* hasUnseen is a boolean — not a count (spec §5.2). */}
          {hasUnseen && (
            <span
              data-testid="drawer-tab-unseen"
              aria-label="Unread AI feedback"
              className="ml-2 inline-block size-2 rounded-full bg-amber-500 align-middle"
            />
          )}
        </button>

        <Button
          variant="ghost"
          size="icon"
          aria-label={drawerOpen ? 'Collapse feedback drawer' : 'Expand feedback drawer'}
          data-testid="drawer-toggle"
          onClick={() => setDrawerOpen(!drawerOpen)}
          className="ml-auto size-7"
        >
          {drawerOpen ? <ChevronDown className="size-4" /> : <ChevronUp className="size-4" />}
        </Button>
      </div>

      {drawerOpen && (
        <div
          data-testid="drawer-body"
          style={{ height: drawerHeight }}
          className="overflow-y-auto px-3 pb-3"
        >
          {/* Stays-on-empty: when there are no findings, show the empty state —
              never auto-switch tabs (spec §5.3). */}
          {findings.length === 0 ? (
            <p data-testid="drawer-empty" className="py-4 text-xs text-muted-foreground">
              No feedback for this slide.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {findings.map(f => (
                <li
                  key={f.id}
                  data-testid={`finding-${f.id}`}
                  className="rounded-md border border-border p-2"
                >
                  <div className="mb-1 flex items-center gap-2">
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                      {CATEGORY_LABEL[f.category]}
                    </span>
                  </div>
                  <p className="mb-2 text-xs text-foreground">{f.message}</p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      data-testid={`finding-apply-${f.id}`}
                      onClick={() => callbacks.onApplyFinding(f.id)}
                    >
                      Apply
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      data-testid={`finding-dismiss-${f.id}`}
                      onClick={() => callbacks.onDismissFinding(f.id)}
                    >
                      Dismiss
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      data-testid={`finding-discuss-${f.id}`}
                      onClick={() => callbacks.onDiscussFinding(f.id)}
                    >
                      Discuss
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
