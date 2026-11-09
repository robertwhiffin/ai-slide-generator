/**
 * Chat image generation, Unit I (Task 8): the chat input's "Generate image" entry point.
 *
 * Contract: docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md, "Unit I interface",
 * Entry points:
 *   ChatInput gets the prop `imageRequest?: { slideCount: number }`. When set, it renders a labelled
 *   button "Generate image" in the hint row, which opens GenerateImageRequestDialog and calls
 *   `onSend(generateImageMessage(...))`.
 * Absent prop: no button (ChatPanel passes it only when the feature is available and the deck is not
 * legacy, pinned in ChatPanel.generatedImages.test.tsx).
 *
 * The REAL dialog is used, so these tests also pin that ChatInput hands it `slideCount`.
 *
 * Choices this test pins where CORRECTIONS is silent:
 *   - the dialog's message is sent as `onSend(message)` with NO image ids (the second argument is
 *     undefined), and the dialog closes;
 *   - while the input is `disabled` (a turn is running, read-only, preview) the button is disabled;
 *   - Cancel closes the dialog and sends nothing;
 *   - text already typed in the chat box is left alone.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatInput } from './ChatInput';

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return { ...actual, api: { uploadImage: vi.fn() } };
});

const HINT = 'Enter to send · Shift+Enter new line';

function renderInput(props: { imageRequest?: { slideCount: number }; disabled?: boolean } = {}) {
  const onSend = vi.fn();
  render(<ChatInput onSend={onSend} disabled={props.disabled ?? false} imageRequest={props.imageRequest} />);
  return { onSend };
}

const generateButton = () => screen.getByRole('button', { name: 'Generate image' });
const queryGenerateButton = () => screen.queryByRole('button', { name: 'Generate image' });
const dialog = () => screen.getByRole('dialog');

/** The smallest ancestor of `from` that also contains `target`. */
function commonRow(from: HTMLElement, target: HTMLElement): HTMLElement {
  let row: HTMLElement | null = from.parentElement;
  while (row && !row.contains(target)) row = row.parentElement;
  expect(row, 'the two elements share an ancestor').not.toBeNull();
  return row as HTMLElement;
}

afterEach(() => cleanup());

describe('ChatInput "Generate image"', () => {
  it('renders no Generate image button without the imageRequest prop', () => {
    renderInput();
    expect(screen.getByText(HINT)).toBeInTheDocument();
    expect(queryGenerateButton()).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('renders the button in the hint row when imageRequest is set, with no dialog open', () => {
    renderInput({ imageRequest: { slideCount: 4 } });

    const button = generateButton();
    const textarea = screen.getByTestId('chat-input');
    expect(button.closest('form')).toBe(textarea.closest('form'));
    // In the hint's row, below the textarea: the smallest box holding hint and button has no textarea.
    expect(commonRow(screen.getByText(HINT), button).contains(textarea)).toBe(false);
    // A plain button: it must not submit the chat form.
    expect(button).toHaveAttribute('type', 'button');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens the dialog with the deck’s slides as the For-slide choices', () => {
    renderInput({ imageRequest: { slideCount: 3 } });
    fireEvent.click(generateButton());

    const select = within(dialog()).getByRole('combobox', { name: 'For slide' });
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['None', '1', '2', '3']);
  });

  it('submitting the dialog sends its exact message with no image ids, and closes it', () => {
    const { onSend } = renderInput({ imageRequest: { slideCount: 4 } });
    fireEvent.click(generateButton());

    fireEvent.change(within(dialog()).getByRole('textbox', { name: 'Describe the image' }), {
      target: { value: 'A shield for data security' },
    });
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Icon' }));
    const select = within(dialog()).getByRole('combobox', { name: 'For slide' }) as HTMLSelectElement;
    const two = within(select).getByRole('option', { name: '2' }) as HTMLOptionElement;
    fireEvent.change(select, { target: { value: two.value } });
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Send to chat' }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0]).toBe('Generate 3 icon options for slide 2: A shield for data security');
    expect(onSend.mock.calls[0][1]).toBeUndefined();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('leaves the text typed in the chat box alone', () => {
    const { onSend } = renderInput({ imageRequest: { slideCount: 0 } });
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: 'half-written thought' } });

    fireEvent.click(generateButton());
    fireEvent.change(within(dialog()).getByRole('textbox', { name: 'Describe the image' }), {
      target: { value: 'A rocket' },
    });
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Send to chat' }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0]).toBe('Generate 3 illustration options: A rocket');
    expect(screen.getByTestId('chat-input')).toHaveValue('half-written thought');
  });

  it('Cancel closes the dialog and sends nothing', () => {
    const { onSend } = renderInput({ imageRequest: { slideCount: 4 } });
    fireEvent.click(generateButton());
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(onSend).not.toHaveBeenCalled();
  });

  it('is disabled while the input is disabled', () => {
    renderInput({ imageRequest: { slideCount: 4 }, disabled: true });
    expect(generateButton()).toBeDisabled();
    fireEvent.click(generateButton());
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
