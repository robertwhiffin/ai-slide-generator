/**
 * Interrupt generation, Task 9: ConfirmDialog's initial focus and its Escape.
 *
 * Contract (plan docs/superpowers/plans/2026-11-12-interrupt-generation.md, Task 9):
 *   - New prop `initialFocus?: 'confirm' | 'cancel'`, default `'confirm'`, so every existing caller
 *     keeps today's focus on the confirm button. The stop dialog passes `'cancel'`, so an Enter
 *     pressed by reflex keeps generating instead of discarding the slides.
 *   - The dialog's window Escape handler calls `e.preventDefault()` before `onCancel()`, so any other
 *     window Escape listener (Task 10's useEscapeToStop, registered after it) sees the dialog
 *     already handled the key, and does not stop a generation while a dialog is open.
 *
 * The stop dialog's copy is used for realism (title, buttons); ConfirmDialog itself is generic.
 *
 * SABOTAGE (for the reviewer):
 *   - ignore `initialFocus` (always focus confirm)          -> test_initial_focus_cancel_focuses_cancel_button RED.
 *   - default `initialFocus` to 'cancel'                    -> test_default_focus_unchanged RED.
 *   - no preventDefault in the Escape handler               -> test_escape_prevents_default RED.
 *   - preventDefault on every key                           -> test_escape_prevents_default RED (the 'a' key).
 *   - preventDefault after a listener that runs later / no onCancel -> same test RED.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { ConfirmDialog } from './ConfirmDialog';

const TITLE = 'Stop generating?';
const KEEP = 'Keep generating';
const DISCARD = 'Stop and discard';
const MESSAGE =
  'Your slides are being built (2 of 5 done). If you stop now, every slide built so far is thrown away and the deck goes back to how it was before you sent this message.';

const listeners: Array<(e: KeyboardEvent) => void> = [];

afterEach(() => {
  for (const l of listeners.splice(0)) window.removeEventListener('keydown', l);
  cleanup();
});

describe('ConfirmDialog initial focus', () => {
  it('test_initial_focus_cancel_focuses_cancel_button', () => {
    render(
      <ConfirmDialog
        open
        title={TITLE}
        message={MESSAGE}
        confirmLabel={DISCARD}
        cancelLabel={KEEP}
        variant="danger"
        initialFocus="cancel"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: KEEP })).toHaveFocus();
    expect(screen.getByRole('button', { name: DISCARD })).not.toHaveFocus();
  });

  it('test_default_focus_unchanged', () => {
    // An existing caller (no initialFocus): focus stays on the confirm button.
    render(
      <ConfirmDialog
        open
        title="Delete deck?"
        message="This cannot be undone."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Delete' })).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Cancel' })).not.toHaveFocus();
  });
});

describe('ConfirmDialog Escape', () => {
  it('test_escape_prevents_default', () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        title={TITLE}
        message={MESSAGE}
        confirmLabel={DISCARD}
        cancelLabel={KEEP}
        initialFocus="cancel"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    // Another window keydown listener, registered after the dialog's (as useEscapeToStop is).
    const seen: Array<{ key: string; defaultPrevented: boolean }> = [];
    const later = (e: KeyboardEvent) => seen.push({ key: e.key, defaultPrevented: e.defaultPrevented });
    window.addEventListener('keydown', later);
    listeners.push(later);

    // A key that is not Escape is left alone.
    const other = new KeyboardEvent('keydown', { key: 'a', bubbles: true, cancelable: true });
    (document.activeElement ?? document.body).dispatchEvent(other);
    expect(other.defaultPrevented).toBe(false);
    expect(onCancel).not.toHaveBeenCalled();

    // Escape, pressed where focus is (the Keep generating button), bubbling up to window.
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    (document.activeElement ?? document.body).dispatchEvent(escape);

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(escape.defaultPrevented).toBe(true);
    expect(seen).toEqual([
      { key: 'a', defaultPrevented: false },
      { key: 'Escape', defaultPrevented: true },
    ]);
  });
});
