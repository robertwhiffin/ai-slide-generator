/**
 * Interrupt generation, Task 10: `useEscapeToStop`, the Escape half of "Stop generating (Esc)".
 *
 * Contract (task-10-brief.md "Interfaces"; spec "What the user sees": Escape works anywhere on the deck
 * page unless something else that uses Escape is open, which then handles it and the generation goes on):
 *   useEscapeToStop(active: boolean, onStop: () => void): void
 *   - one window `keydown` listener in the BUBBLE phase, registered once per `active` change, with
 *     `onStop` read from a ref (a listener re-registered every render would run after ConfirmDialog's);
 *   - calls `onStop` only for `key === 'Escape'`, and only when ALL hold:
 *       !e.defaultPrevented;
 *       document.querySelector('[role="dialog"]') is null;
 *       the target is not an input, textarea, select or [contenteditable], and is not inside a
 *       [data-escape-owner] element.
 *   - FeedbackDrawer's root carries `data-escape-owner`; PromptEditorModal (the expanded prompt
 *     editor, the one overlay with no role at all) gains `role="dialog"`.
 *
 * Every "not called" is paired in the same test with a positive (the same hook, a press it must act
 * on), so no absence passes because the listener was never there.
 *
 * Harness: the real hook in a tiny component; the real ConfirmDialog, PromptEditorModal and
 * FeedbackDrawer. FeedbackDrawer's ViewerContext is mocked: its provider reads localStorage, which
 * fails in this repo's local jsdom (the pre-existing SlideViewer cause in PLAN-CORRECTIONS C4).
 *
 * SABOTAGE (each measured RED by the test author against a throwaway reference hook, since deleted,
 * except the isContentEditable line, which is reasoned, not measured):
 *   - listener in the capture phase                          -> test_ignores_default_prevented RED (the
 *                                                               target's React onKeyDown has not run yet).
 *   - no defaultPrevented check                              -> test_ignores_default_prevented RED.
 *   - no [role="dialog"] check                               -> test_ignores_when_dialog_present,
 *                                                               test_confirm_dialog_escape_is_keep_generating RED.
 *   - no text-input exclusion (any one of the four)          -> that case of test_ignores_escape_in_text_input RED.
 *   - contenteditable via `isContentEditable` (jsdom: undefined) -> the contenteditable case RED.
 *   - `matches` instead of `closest` for data-escape-owner   -> test_ignores_escape_inside_escape_owner RED.
 *   - listener kept while inactive / added while inactive    -> test_ignores_when_inactive RED.
 *   - `[active, onStop]` deps (re-registered on every render) or a stale onStop
 *                                                            -> test_reads_latest_onStop_and_registers_once_per_active_change RED.
 *   - no `role="dialog"` on PromptEditorModal                -> test_prompt_editor_modal_counts_as_a_dialog RED.
 *   - no `data-escape-owner` on FeedbackDrawer's root        -> test_feedback_drawer_owns_escape RED.
 */
import { useState, type ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { useEscapeToStop } from './useEscapeToStop';
import { ConfirmDialog } from '../ConfirmDialog';
import { PromptEditorModal } from './PromptEditorModal';
import { FeedbackDrawer } from '../SlideViewer/FeedbackDrawer';
import { LoadProfileDialog, SaveProfileDialog } from '../AgentConfigBar/AgentConfigBar';
import { SaveAsDialog } from '../History/SaveAsDialog';
import { RevertConfirmModal } from '../SavePoints/RevertConfirmModal';
import { SurveyModal } from '../Feedback/SurveyModal';
import { WelcomeModal } from '../Tour/WelcomeModal';
import { api } from '../../services/api';

vi.mock('../../contexts/ViewerContext', () => ({
  useViewer: () => ({
    drawerOpen: true,
    setDrawerOpen: () => {},
    drawerHeight: 200,
    setDrawerHeight: () => {},
    activeTab: 'feedback',
    setActiveTab: () => {},
  }),
}));

vi.mock('../../contexts/TourContext', () => ({
  useTour: () => ({ showWelcome: true, startTour: () => {}, dismissWelcome: () => {} }),
}));

function Stopper({ active, onStop, children }: { active: boolean; onStop: () => void; children?: ReactNode }) {
  useEscapeToStop(active, onStop);
  return <>{children}</>;
}

/** A keydown that bubbles from `target` to window, as a real key press does. */
const press = (target: Element, key = 'Escape') => fireEvent.keyDown(target, { key, code: key });

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.querySelectorAll('[data-test-portal]').forEach((n) => n.remove());
});

describe('useEscapeToStop', () => {
  it('test_escape_calls_onStop_when_active (and no other key does)', () => {
    const onStop = vi.fn();
    render(<Stopper active onStop={onStop} />);

    press(document.body, 'Enter');
    press(document.body, 'a');
    expect(onStop).not.toHaveBeenCalled();

    press(document.body);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('test_ignores_when_inactive', () => {
    const onStop = vi.fn();
    const { rerender } = render(<Stopper active={false} onStop={onStop} />);
    press(document.body);
    expect(onStop).not.toHaveBeenCalled();

    // Positive: the same hook acts once it is active.
    rerender(<Stopper active onStop={onStop} />);
    press(document.body);
    expect(onStop).toHaveBeenCalledTimes(1);

    // And stops acting when the generation ends.
    rerender(<Stopper active={false} onStop={onStop} />);
    press(document.body);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('test_ignores_default_prevented', () => {
    const onStop = vi.fn();
    render(
      <Stopper active onStop={onStop}>
        {/* Something that owns Escape the React way: its onKeyDown runs at the root, before window's bubble listener. */}
        <div
          data-testid="handles-escape"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Escape') e.preventDefault(); }}
        >
          owner
        </div>
        <button type="button">plain</button>
      </Stopper>,
    );

    press(screen.getByTestId('handles-escape'));
    expect(onStop).not.toHaveBeenCalled();

    // A capture-phase handler that prevents it (a Radix-style layer) also wins.
    const prevent = (e: KeyboardEvent) => { if (e.key === 'Escape') e.preventDefault(); };
    document.addEventListener('keydown', prevent, true);
    press(screen.getByRole('button', { name: 'plain' }));
    document.removeEventListener('keydown', prevent, true);
    expect(onStop).not.toHaveBeenCalled();

    // Positive: an Escape nobody handled stops.
    press(screen.getByRole('button', { name: 'plain' }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('test_ignores_when_dialog_present', () => {
    const onStop = vi.fn();
    const { rerender } = render(
      <Stopper active onStop={onStop}>
        <div role="dialog" aria-label="Some dialog">
          <button type="button">in the dialog</button>
        </div>
        <button type="button">outside</button>
      </Stopper>,
    );

    // Anywhere in the document while a dialog is open, focus inside it or not.
    press(screen.getByRole('button', { name: 'in the dialog' }));
    press(screen.getByRole('button', { name: 'outside' }));
    press(document.body);
    expect(onStop).not.toHaveBeenCalled();

    // A dialog outside this React tree (a portal) counts too.
    rerender(<Stopper active onStop={onStop}><button type="button">outside</button></Stopper>);
    const portal = document.createElement('div');
    portal.setAttribute('role', 'dialog');
    portal.setAttribute('data-test-portal', '');
    document.body.appendChild(portal);
    press(screen.getByRole('button', { name: 'outside' }));
    expect(onStop).not.toHaveBeenCalled();

    // Positive: once no dialog is open, the same press stops.
    portal.remove();
    press(screen.getByRole('button', { name: 'outside' }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['input', <input key="t" data-testid="target" defaultValue="x" />],
    ['textarea', <textarea key="t" data-testid="target" defaultValue="x" />],
    ['select', <select key="t" data-testid="target" defaultValue="a"><option value="a">a</option></select>],
    ['contenteditable', <div key="t" data-testid="target" contentEditable suppressContentEditableWarning>x</div>],
  ])('test_ignores_escape_in_text_input (%s)', (_kind, field) => {
    const onStop = vi.fn();
    render(
      <Stopper active onStop={onStop}>
        {field}
        <button type="button">plain</button>
      </Stopper>,
    );

    press(screen.getByTestId('target'));
    expect(onStop).not.toHaveBeenCalled();

    // Positive: the same press from a button stops.
    press(screen.getByRole('button', { name: 'plain' }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('test_ignores_escape_inside_escape_owner', () => {
    const onStop = vi.fn();
    render(
      <Stopper active onStop={onStop}>
        <div data-escape-owner="">
          <button type="button">inside</button>
          <span>
            <a href="#deep">deep inside</a>
          </span>
        </div>
        <button type="button">outside</button>
      </Stopper>,
    );

    press(screen.getByRole('button', { name: 'inside' }));
    press(screen.getByRole('link', { name: 'deep inside' }));
    expect(onStop).not.toHaveBeenCalled();

    press(screen.getByRole('button', { name: 'outside' }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('test_reads_latest_onStop_and_registers_once_per_active_change', () => {
    const add = vi.spyOn(window, 'addEventListener');
    const remove = vi.spyOn(window, 'removeEventListener');
    const keydowns = (spy: typeof add | typeof remove) => spy.mock.calls.filter(([type]) => type === 'keydown').length;
    const first = vi.fn();
    const second = vi.fn();
    const third = vi.fn();

    const { rerender } = render(<Stopper active onStop={first} />);
    expect(keydowns(add)).toBe(1);

    // ChatPanel re-renders on every poll, each time with a new onStop identity.
    rerender(<Stopper active onStop={second} />);
    rerender(<Stopper active onStop={third} />);
    expect(keydowns(add), 'the listener was re-registered on a re-render').toBe(1);
    expect(keydowns(remove)).toBe(0);

    press(document.body);
    expect(third).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
    expect(second).not.toHaveBeenCalled();

    // A change of `active` is what (un)registers it.
    rerender(<Stopper active={false} onStop={third} />);
    expect(keydowns(remove)).toBe(1);
    rerender(<Stopper active onStop={third} />);
    expect(keydowns(add)).toBe(2);
  });

  it('test_confirm_dialog_escape_is_keep_generating (the real ConfirmDialog, re-rendered while open)', () => {
    const onStop = vi.fn();

    // A stop that opens the confirmation, as ChatPanel's confirm-first stop does.
    function Pane({ tick }: { tick: number }) {
      const [open, setOpen] = useState(true);
      useEscapeToStop(true, () => { onStop(); setOpen(true); });
      return (
        <>
          <span data-testid="tick">{tick}</span>
          <ConfirmDialog
            open={open}
            title="Stop generating?"
            message="Your slides are being built."
            confirmLabel="Stop and discard"
            cancelLabel="Keep generating"
            variant="danger"
            initialFocus="cancel"
            onConfirm={() => {}}
            onCancel={() => setOpen(false)}
          />
        </>
      );
    }

    const { rerender } = render(<Pane tick={1} />);
    // Re-render while the dialog is open: new onStop and onCancel identities.
    rerender(<Pane tick={2} />);
    rerender(<Pane tick={3} />);
    const keep = screen.getByRole('button', { name: 'Keep generating' });
    expect(keep).toHaveFocus();

    press(keep);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onStop).not.toHaveBeenCalled();

    // Positive: with the dialog gone, Escape is a stop again (and reopens it).
    press(document.body);
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('test_prompt_editor_modal_counts_as_a_dialog', () => {
    const onStop = vi.fn();
    const onSave = vi.fn();
    const { rerender } = render(
      <Stopper active onStop={onStop}>
        <PromptEditorModal
          initialText="A longer prompt"
          placeholder="Ask me to create slides..."
          onSave={onSave}
          onCancel={() => {}}
          onSend={() => {}}
          disabled={false}
        />
      </Stopper>,
    );

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    // Escape from one of its buttons (not its textarea, which the text-input rule would cover anyway).
    press(screen.getByRole('button', { name: 'Done Editing' }));
    expect(onSave).toHaveBeenCalledWith('A longer prompt'); // the editor took the Escape
    expect(onStop).not.toHaveBeenCalled();

    // Positive: with the editor closed, Escape stops.
    rerender(<Stopper active onStop={onStop}><button type="button">plain</button></Stopper>);
    press(screen.getByRole('button', { name: 'plain' }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('test_feedback_drawer_owns_escape', () => {
    const onStop = vi.fn();
    render(
      <Stopper active onStop={onStop}>
        <FeedbackDrawer
          findings={[]}
          callbacks={{ onApplyFinding: () => {}, onDismissFinding: () => {}, onDiscussFinding: () => {} }}
          hasUnseen={false}
        />
        <button type="button">outside</button>
      </Stopper>,
    );

    press(screen.getByTestId('drawer-tab-feedback'));
    press(screen.getByTestId('drawer-toggle'));
    expect(onStop).not.toHaveBeenCalled();

    press(screen.getByRole('button', { name: 'outside' }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });
});

// Final review F7: an overlay on the deck page with no role="dialog" let Escape stop the generation
// underneath it. The Agent config bar's Save/Load Profile dialogs stay reachable while a turn runs; the
// others' triggers are disabled then, but they get the role too.
describe('deck-page overlays count as dialogs (final review F7)', () => {
  class MemoryStorage implements Storage {
    private store = new Map<string, string>();
    get length() { return this.store.size; }
    clear() { this.store.clear(); }
    getItem(key: string) { return this.store.has(key) ? this.store.get(key)! : null; }
    key(i: number) { return Array.from(this.store.keys())[i] ?? null; }
    removeItem(key: string) { this.store.delete(key); }
    setItem(key: string, value: string) { this.store.set(key, String(value)); }
  }

  it.each<[string, () => ReactNode]>([
    ['Save as Profile', () => <SaveProfileDialog isOpen onClose={() => {}} onSave={() => {}} saving={false} />],
    ['Load Profile', () => <LoadProfileDialog isOpen onClose={() => {}} onLoad={() => {}} />],
    ['Save Session', () => <SaveAsDialog isOpen currentTitle="Otters" onSave={() => {}} onCancel={() => {}} />],
    [
      'Revert to Previous Version',
      () => (
        <RevertConfirmModal
          isOpen
          versionNumber={2}
          description="Generated 3 slides"
          currentVersion={4}
          onConfirm={() => {}}
          onCancel={() => {}}
        />
      ),
    ],
    ["How's your experience with tellr?", () => <SurveyModal isOpen onClose={() => {}} />],
    ['Welcome to Tellr', () => <WelcomeModal />],
  ])('test_overlay_counts_as_a_dialog (%s)', (name, overlay) => {
    vi.stubGlobal('localStorage', new MemoryStorage());
    vi.spyOn(api, 'listProfiles').mockResolvedValue([]);
    try {
      const onStop = vi.fn();
      const { rerender } = render(<Stopper active onStop={onStop}>{overlay()}</Stopper>);

      const dialog = screen.getByRole('dialog', { name });
      expect(dialog).toHaveAttribute('aria-modal', 'true');
      press(document.body);
      press(within(dialog).getAllByRole('button')[0]);
      expect(onStop, 'Escape under an open overlay stopped the generation').not.toHaveBeenCalled();

      // Positive: with the overlay closed, Escape stops.
      rerender(<Stopper active onStop={onStop}><button type="button">plain</button></Stopper>);
      press(screen.getByRole('button', { name: 'plain' }));
      expect(onStop).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
