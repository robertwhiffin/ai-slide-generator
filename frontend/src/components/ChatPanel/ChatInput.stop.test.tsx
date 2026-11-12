/**
 * Interrupt generation, Task 9: ChatInput's stop mode, and restoring the last draft.
 *
 * Contract (plan docs/superpowers/plans/2026-11-12-interrupt-generation.md, Task 9 + Global
 * Constraints, copy verbatim):
 *   - New props `generating?: boolean`, `onStop?: () => void`, `restoreDraftKey?: number`.
 *   - While `generating && onStop`:
 *       - the send button is replaced by a `type="button"` stop button: lucide `Ban`, `text-red-600`,
 *         aria-label `Stop generating`, title `Stop generating (Esc)`, `data-testid="chat-stop"`;
 *       - the stop button is enabled even though the textarea is disabled;
 *       - the hint reads `Esc to cancel · Enter to send · Shift+Enter new line`.
 *   - No `onStop` (a Legacy deck, or the SSE transport): today's send button and hint, even while
 *     generating.
 *   - When `restoreDraftKey` changes to a new non-zero value: restore the last submitted text AND
 *     attachments (kept at submit, preview URLs included), put the cursor at the end, and focus the
 *     textarea once it is enabled.
 *
 * Copy is asserted as literals, so a wrong constant cannot pass. The copy module itself is pinned
 * in stopGenerationCopy.test.ts.
 * Harness: the real ChatInput; `api.uploadImage` mocked (precedent: ChatInput.imageRequest.test.tsx).
 *
 * SABOTAGE (for the reviewer):
 *   - stop button rendered beside (not instead of) Send   -> test_stop_button_replaces_send_while_generating RED.
 *   - stop button `type="submit"`                         -> same test RED (type, and the typed text is sent).
 *   - stop button disabled with the input                 -> test_stop_button_enabled_while_input_disabled RED.
 *   - stop button shown on `generating` alone             -> test_no_stop_button_without_onStop RED.
 *   - generating hint shown without onStop                -> test_no_stop_button_without_onStop RED.
 *   - restore text only (attachments not kept)            -> test_restore_draft_key_restores_text_and_attachments RED.
 *   - attachments restored without preview URLs           -> same test RED (img src).
 *   - no focus after restore / focus while disabled only  -> the two restore tests RED.
 *   - restore on every render with a non-zero key         -> test_same_restore_key_does_not_restore_again RED.
 */
import type { ComponentProps } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChatInput } from './ChatInput';

const h = vi.hoisted(() => ({ uploadImage: vi.fn() }));

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return { ...actual, api: { uploadImage: h.uploadImage } };
});

const HINT = 'Enter to send · Shift+Enter new line';
const GENERATING_HINT = 'Esc to cancel · Enter to send · Shift+Enter new line';
const STOP_NAME = 'Stop generating';
const STOP_TITLE = 'Stop generating (Esc)';
const THUMB = 'data:image/png;base64,iVBORw0KGgo=';
const DRAFT = 'Build a Q3 deck from the revenue table';

type InputProps = ComponentProps<typeof ChatInput>;
/** Task 9's new props, spelled out so this file reads the same before and after they land. */
type StopProps = { generating?: boolean; onStop?: () => void; restoreDraftKey?: number };

const onSend = vi.fn();
const onStop = vi.fn();

/** The ChatInput as ChatPanel renders it, with `props` on top. */
const ui = (props: Partial<InputProps> & StopProps = {}) => {
  const all = { onSend, disabled: false, ...props } as InputProps;
  return <ChatInput {...all} />;
};

const textarea = () => screen.getByTestId('chat-input') as HTMLTextAreaElement;
const stopButton = () => screen.getByRole('button', { name: STOP_NAME });
const queryStopButton = () => screen.queryByRole('button', { name: STOP_NAME });
const sendButton = () => screen.getByRole('button', { name: 'Send' });
const querySendButton = () => screen.queryByRole('button', { name: 'Send' });

afterEach(() => {
  cleanup();
  onSend.mockReset();
  onStop.mockReset();
  h.uploadImage.mockReset();
});

describe('ChatInput stop mode', () => {
  it('test_stop_button_replaces_send_while_generating', () => {
    const { rerender } = render(ui({ generating: true, onStop }));
    // Typed but not sent: clicking stop must not submit the form.
    fireEvent.change(textarea(), { target: { value: 'half-written thought' } });

    expect(querySendButton()).toBeNull();
    const stop = stopButton();
    expect(screen.getByTestId('chat-stop')).toBe(stop);
    expect(stop).toHaveAttribute('type', 'button');
    expect(stop).toHaveAttribute('title', STOP_TITLE);
    // The red stop sign in the send arrow's place, among the input's own buttons.
    expect(stop.querySelector('svg.lucide-ban')).not.toBeNull();
    expect(stop.querySelector('svg.lucide-send')).toBeNull();
    expect(stop.matches('.text-red-600') || stop.querySelector('.text-red-600') !== null).toBe(true);
    expect(screen.getByTitle('Attach image').parentElement?.contains(stop)).toBe(true);

    fireEvent.click(stop);

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
    expect(textarea()).toHaveValue('half-written thought');

    // The generation ends: the send arrow is back.
    rerender(ui({ generating: false, onStop }));
    expect(queryStopButton()).toBeNull();
    expect(screen.queryByTestId('chat-stop')).toBeNull();
    expect(sendButton()).toBeEnabled();
  });

  it('test_stop_button_enabled_while_input_disabled', () => {
    // As ChatPanel renders it mid-turn: input disabled, nothing typed.
    render(ui({ disabled: true, generating: true, onStop }));

    expect(textarea()).toBeDisabled();
    expect(stopButton()).toBeEnabled();

    fireEvent.click(stopButton());

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
  });

  it('test_generating_hint_copy', () => {
    const { rerender } = render(ui({ disabled: true, generating: true, onStop }));

    expect(screen.getByText(GENERATING_HINT, { exact: true })).toBeInTheDocument();
    expect(screen.getByText('Esc to cancel · Enter to send · Shift+Enter new line')).toBeInTheDocument();
    expect(screen.queryByText(HINT, { exact: true })).toBeNull();

    rerender(ui({ disabled: false, generating: false, onStop }));

    expect(screen.getByText(HINT, { exact: true })).toBeInTheDocument();
    expect(screen.queryByText(/Esc to cancel/)).toBeNull();
  });

  it('test_no_stop_button_without_onStop', () => {
    // Legacy deck (or SSE): ChatPanel passes no onStop, even while a turn runs.
    render(ui({ disabled: true, generating: true }));

    expect(queryStopButton()).toBeNull();
    expect(screen.queryByTestId('chat-stop')).toBeNull();
    expect(sendButton()).toBeDisabled();
    expect(screen.getByText(HINT, { exact: true })).toBeInTheDocument();
    expect(screen.queryByText(/Esc to cancel/)).toBeNull();
  });
});

describe('ChatInput draft restore', () => {
  /** Attach one uploaded image, type DRAFT, press Enter. Returns after the send. */
  async function attachTypeAndSend(container: HTMLElement) {
    h.uploadImage.mockResolvedValue({ id: 'img-1', thumbnail_base64: THUMB });
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [new File(['x'], 'chart.png', { type: 'image/png' })] } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument());

    fireEvent.change(textarea(), { target: { value: DRAFT } });
    fireEvent.keyDown(textarea(), { key: 'Enter' });

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenLastCalledWith(DRAFT, ['img-1']);
    // Sent: the box is empty again.
    expect(textarea()).toHaveValue('');
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
    expect(container.querySelector('img')).toBeNull();
  }

  function expectDraftRestored(container: HTMLElement) {
    const box = textarea();
    expect(box).toBeEnabled();
    expect(box).toHaveValue(DRAFT);
    expect(box).toHaveFocus();
    expect(box.selectionStart).toBe(DRAFT.length);
    expect(box.selectionEnd).toBe(DRAFT.length);
    // The attachment is back, with its preview.
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument();
    const imgs = Array.from(container.querySelectorAll('img'));
    expect(imgs.map((i) => i.getAttribute('src'))).toEqual([THUMB]);
  }

  it('test_restore_draft_key_restores_text_and_attachments', async () => {
    const { container, rerender } = render(ui({ onStop, restoreDraftKey: 0 }));
    await attachTypeAndSend(container);

    // The turn runs, then is stopped and rolled back: ChatPanel re-enables the input and bumps the key.
    rerender(ui({ disabled: true, generating: true, onStop, restoreDraftKey: 0 }));
    textarea().blur();
    expect(textarea()).not.toHaveFocus();
    rerender(ui({ disabled: false, generating: false, onStop, restoreDraftKey: 1 }));

    expectDraftRestored(container);

    // Sending again sends the same text and the same image.
    fireEvent.keyDown(textarea(), { key: 'Enter' });
    expect(onSend).toHaveBeenCalledTimes(2);
    expect(onSend).toHaveBeenLastCalledWith(DRAFT, ['img-1']);
  });

  it('test_restore_draft_key_while_disabled_focuses_once_enabled', async () => {
    const { container, rerender } = render(ui({ onStop, restoreDraftKey: 0 }));
    await attachTypeAndSend(container);

    rerender(ui({ disabled: true, generating: true, onStop, restoreDraftKey: 0 }));
    textarea().blur();
    // The key is bumped a render before the input is enabled again.
    rerender(ui({ disabled: true, generating: false, onStop, restoreDraftKey: 1 }));
    expect(textarea()).not.toHaveFocus();
    rerender(ui({ disabled: false, generating: false, onStop, restoreDraftKey: 1 }));

    expectDraftRestored(container);
  });

  it('test_same_restore_key_does_not_restore_again', async () => {
    const { container, rerender } = render(ui({ onStop, restoreDraftKey: 0 }));
    await attachTypeAndSend(container);
    rerender(ui({ disabled: true, generating: true, onStop, restoreDraftKey: 0 }));
    rerender(ui({ disabled: false, generating: false, onStop, restoreDraftKey: 1 }));
    expect(textarea()).toHaveValue(DRAFT);

    // The user rewrites the restored draft and drops the image; a later render keeps key 1.
    fireEvent.change(textarea(), { target: { value: 'Something else' } });
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    rerender(ui({ disabled: false, generating: false, onStop, restoreDraftKey: 1, placeholder: 'Ask again' }));

    expect(textarea()).toHaveValue('Something else');
    expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
  });
});
