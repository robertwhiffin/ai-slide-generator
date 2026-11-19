import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, ChevronUp } from 'lucide-react';
import { Button } from '@/ui/button';
import { CATEGORY_LABEL, type DrawerCallbacks, type SlideFinding } from '../../types/finding';
import { useViewer } from '../../contexts/ViewerContext';
import { findingPlainText } from '../../utils/findingText';

interface FeedbackDrawerProps {
  findings: SlideFinding[];        // already scoped to the current slide
  callbacks: DrawerCallbacks;
  hasUnseen: boolean;
  /** A turn is running: Apply and Discuss send a chat message, so they wait (Dismiss sends nothing). */
  actionsDisabled?: boolean;
  speakerNotes?: string;
  talkTrack?: string;
  /** The current slide's id; a change resets both drafts. */
  slideKey?: string;
  /** Absent = read-only viewer (no editor). Each call carries only the saved box's field. */
  onSaveNotes?: (fields: { speaker_notes?: string; talk_track?: string }) => Promise<void>;
}

interface PresenterTextBoxProps {
  idPrefix: 'drawer-talk' | 'drawer-notes';
  label: string;
  sublabel: string;
  placeholder: string;
  saveLabel: string;
  errorText: string;
  value: string;
  slideKey?: string;
  onSave: (text: string) => Promise<void>;
}

const PresenterTextBox: React.FC<PresenterTextBoxProps> = ({
  idPrefix, label, sublabel, placeholder, saveLabel, errorText, value, slideKey, onSave,
}) => {
  // The draft resets when this box's own field changes or the slide switches.
  // An unsaved draft is discarded on a slide switch (accepted).
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setDraft(value);
  }, [slideKey, value]);
  useEffect(() => {
    setFailed(false);
  }, [slideKey]);
  const save = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    setFailed(false);
    try {
      await onSave(draft);
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }, [onSave, saving, draft]);
  const labelId = `${idPrefix}-label`;
  const subId = `${idPrefix}-sublabel`;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline gap-2">
        <span id={labelId} className="text-xs font-medium text-foreground">{label}</span>
        <span id={subId} className="text-[11px] text-muted-foreground">{sublabel}</span>
      </div>
      <textarea
        data-testid={`${idPrefix}-input`}
        aria-labelledby={labelId}
        aria-describedby={subId}
        placeholder={placeholder}
        value={draft}
        maxLength={20000}
        onChange={e => setDraft(e.target.value)}
        rows={4}
        className="w-full resize-y rounded-md border border-border bg-background p-2 text-xs text-foreground"
      />
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          data-testid={`${idPrefix}-save`}
          disabled={saving || draft === value}
          onClick={save}
        >
          {saveLabel}
        </Button>
        {failed && (
          <span data-testid={`${idPrefix}-error`} role="alert" className="text-xs text-destructive">
            {errorText}
          </span>
        )}
      </div>
    </div>
  );
};

export const FeedbackDrawer: React.FC<FeedbackDrawerProps> = ({
  findings,
  callbacks,
  hasUnseen,
  actionsDisabled = false,
  speakerNotes = '',
  talkTrack = '',
  slideKey,
  onSaveNotes,
}) => {
  const { drawerOpen, setDrawerOpen, drawerHeight, setDrawerHeight, activeTab, setActiveTab } = useViewer();
  // Captures the pointer's starting Y and the drawer's starting height at drag begin.
  const dragStart = useRef<{ y: number; h: number } | null>(null);
  // Findings whose technical details are expanded, keyed by finding id. Collapsed
  // by default, per finding, not persisted (#316): the plain message leads and the
  // reviewer's text is absent from the DOM until asked for.
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(() => new Set());
  const toggleDetails = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const saveTalk = useCallback((text: string) => onSaveNotes!({ talk_track: text }), [onSaveNotes]);
  const saveNotesField = useCallback((text: string) => onSaveNotes!({ speaker_notes: text }), [onSaveNotes]);

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
    <div data-testid="feedback-drawer" data-escape-owner className="flex flex-col border-t border-border bg-card">
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
        {/* Tabbed shell: AI feedback and Notes. The unread dot belongs to AI feedback. */}
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
        <button
          type="button"
          data-testid="drawer-tab-notes"
          data-active={activeTab === 'notes' ? 'true' : 'false'}
          onClick={() => setActiveTab('notes')}
          className={[
            'relative rounded-t px-3 py-1.5 text-xs font-medium',
            activeTab === 'notes' ? 'bg-muted text-foreground' : 'text-muted-foreground',
          ].join(' ')}
        >
          Notes
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
          {activeTab === 'notes' ? (
            onSaveNotes ? (
              <div className="flex flex-col gap-3 py-2">
                <PresenterTextBox
                  idPrefix="drawer-talk"
                  label="Talk track"
                  sublabel="What you say."
                  placeholder="Add a talk track for this slide."
                  saveLabel="Save talk track"
                  errorText="Could not save the talk track."
                  value={talkTrack}
                  slideKey={slideKey}
                  onSave={saveTalk}
                />
                <PresenterTextBox
                  idPrefix="drawer-notes"
                  label="Notes"
                  sublabel="What you need to know."
                  placeholder="Add notes for this slide."
                  saveLabel="Save notes"
                  errorText="Could not save the notes."
                  value={speakerNotes}
                  slideKey={slideKey}
                  onSave={saveNotesField}
                />
                <p data-testid="drawer-notes-hint" className="text-[11px] text-muted-foreground">
                  Chat rewrites the talk track only when it rebuilds the slide.
                </p>
              </div>
            ) : talkTrack.trim() !== '' || speakerNotes.trim() !== '' ? (
              <div className="flex flex-col gap-2 py-2">
                {talkTrack.trim() !== '' && (
                  <p data-testid="drawer-talk" className="whitespace-pre-wrap break-words text-xs text-foreground">
                    {talkTrack}
                  </p>
                )}
                {speakerNotes.trim() !== '' && (
                  <p data-testid="drawer-notes" className="whitespace-pre-wrap break-words text-xs text-foreground">
                    {speakerNotes}
                  </p>
                )}
              </div>
            ) : (
              <p data-testid="drawer-notes-empty" className="py-4 text-xs text-muted-foreground">
                No speaker notes for this slide.
              </p>
            )
          ) : findings.length === 0 ? (
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
                  <div className="mb-2">
                    <p
                      data-testid={`finding-plain-${f.id}`}
                      className="mb-1 text-xs text-foreground"
                    >
                      {findingPlainText(f)}
                    </p>
                    {f.message.trim() !== '' && (
                      <button
                        type="button"
                        data-testid={`finding-details-toggle-${f.id}`}
                        aria-expanded={expandedIds.has(f.id)}
                        onClick={() => toggleDetails(f.id)}
                        className="inline-flex items-center gap-0.5 text-[11px] text-muted-foreground hover:text-foreground"
                      >
                        {expandedIds.has(f.id) ? (
                          <ChevronDown className="size-3" aria-hidden="true" />
                        ) : (
                          <ChevronRight className="size-3" aria-hidden="true" />
                        )}
                        {expandedIds.has(f.id) ? 'Hide details' : 'Show details'}
                      </button>
                    )}
                    {f.message.trim() !== '' && expandedIds.has(f.id) && (
                      <p
                        data-testid={`finding-details-${f.id}`}
                        className="mt-1 whitespace-pre-wrap break-words text-[11px] text-muted-foreground"
                      >
                        {f.message}
                      </p>
                    )}
                  </div>
                  {f.status === 'fixed' ? (
                    <span
                      data-testid={`finding-status-${f.id}`}
                      className="inline-block rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      Fixed
                    </span>
                  ) : (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        data-testid={`finding-apply-${f.id}`}
                        disabled={actionsDisabled}
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
                        disabled={actionsDisabled}
                        onClick={() => callbacks.onDiscussFinding(f.id)}
                      >
                        Discuss
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
