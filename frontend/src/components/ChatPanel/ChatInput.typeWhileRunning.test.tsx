/**
 * Type while a turn runs: ChatInput's half.
 *
 * Contract: on an Agent deck ChatPanel no longer locks the box for a running turn. It passes
 * `disabled: false, generating: true, onStop`, and the input itself holds back every send until the
 * turn ends:
 *   - the box takes typing; Enter does nothing and keeps the text; once `generating` is false, Enter
 *     sends it;
 *   - the expanded editor takes typing, but its Send is disabled; "Done Editing" puts the text in the box;
 *   - "Generate image" (which sends straight away) is disabled;
 *   - the hint reads `Esc to cancel · Send when this finishes · Shift+Enter new line`.
 * Escape in the box (useEscapeToStop.test.tsx, and through the real panel in ChatPanel.stop.test.tsx) and
 * the stopped turn's draft replacing a newer one typed meanwhile (ChatPanel.stop.test.tsx) are tested there.
 *
 * Copy is asserted as literals. Harness: the real ChatInput; `api.uploadImage` mocked (not used here).
 *
 * SABOTAGE (for the reviewer):
 *   - handleSubmit not held while generating           -> test_enter_holds_the_text_until_the_turn_ends RED.
 *   - expanded editor's Send left enabled              -> test_expanded_editor_edits_but_cannot_send RED.
 *   - expanded editor's textarea locked as well         -> same test RED.
 *   - "Generate image" left enabled                     -> test_generate_image_is_held_while_generating RED.
 *   - old hint kept                                     -> test_generating_hint_says_send_when_it_finishes RED.
 */
import type { ComponentProps } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ChatInput } from './ChatInput';

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return { ...actual, api: { uploadImage: vi.fn() } };
});

const GENERATING_HINT = 'Esc to cancel · Send when this finishes · Shift+Enter new line';
const NEXT = 'Now add a slide on churn';

const onSend = vi.fn();
const onStop = vi.fn();

type InputProps = ComponentProps<typeof ChatInput>;
/** As ChatPanel renders it on an Agent deck: mid-turn, the box is not locked. */
const ui = (props: Partial<InputProps> = {}) => (
  <ChatInput onSend={onSend} onStop={onStop} disabled={false} generating {...props} />
);

const textarea = () => screen.getByTestId('chat-input') as HTMLTextAreaElement;

afterEach(() => {
  cleanup();
  onSend.mockReset();
  onStop.mockReset();
});

describe('ChatInput while a turn runs', () => {
  it('test_enter_holds_the_text_until_the_turn_ends', () => {
    const { rerender } = render(ui());

    expect(textarea()).toBeEnabled();
    fireEvent.change(textarea(), { target: { value: NEXT } });
    fireEvent.keyDown(textarea(), { key: 'Enter' });

    expect(onSend).not.toHaveBeenCalled();
    expect(textarea()).toHaveValue(NEXT);

    // The turn ends: the same Enter now sends what was typed.
    rerender(ui({ generating: false }));
    expect(textarea()).toHaveValue(NEXT);
    fireEvent.keyDown(textarea(), { key: 'Enter' });

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith(NEXT, undefined);
    expect(textarea()).toHaveValue('');
  });

  it('test_expanded_editor_edits_but_cannot_send', () => {
    render(ui());
    fireEvent.change(textarea(), { target: { value: 'Now add' } });

    fireEvent.click(screen.getByTitle('Expand editor (for long prompts)'));
    const modalBox = screen.getAllByRole('textbox').find((b) => b !== textarea()) as HTMLTextAreaElement;
    const modalSend = screen.getByText('Send', { selector: 'span' }).closest('button') as HTMLButtonElement;

    expect(modalBox).toBeEnabled();
    fireEvent.change(modalBox, { target: { value: NEXT } });
    expect(modalSend).toBeDisabled();
    fireEvent.click(modalSend);
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Done Editing' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(textarea()).toHaveValue(NEXT);
  });

  it('test_generate_image_is_held_while_generating', () => {
    const { rerender } = render(ui({ imageRequest: { slideCount: 3 } }));

    expect(screen.getByRole('button', { name: 'Generate image' })).toBeDisabled();

    rerender(ui({ generating: false, imageRequest: { slideCount: 3 } }));
    expect(screen.getByRole('button', { name: 'Generate image' })).toBeEnabled();
  });

  it('test_generating_hint_says_send_when_it_finishes', () => {
    render(ui());

    expect(screen.getByText(GENERATING_HINT, { exact: true })).toBeInTheDocument();
    expect(screen.queryByText(/Enter to send/)).toBeNull();
  });
});
