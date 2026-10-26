/**
 * Deck Mode toggle, Task 8: ChatInput's hint line.
 *
 * Contract (task brief + Global Constraints, copy verbatim):
 *   - The hint text is exactly `Enter to send · Shift+Enter new line` (U+00B7 middle dot); the old
 *     "Press Enter to send, Shift+Enter for new line" is gone.
 *   - New prop `modeControl?: React.ReactNode`, rendered on the right side of the hint row: after the
 *     existing line/char counter (shown while typing), in the row the hint sits in, below the
 *     textarea. It renders whether or not the input is disabled (a read-only view shows the control
 *     greyed, not hidden).
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatInput } from './ChatInput';

const HINT = 'Enter to send · Shift+Enter new line';

const follows = (a: Node, b: Node) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

/** The smallest ancestor of `from` that also contains `target`. */
function commonRow(from: HTMLElement, target: HTMLElement): HTMLElement {
  let row: HTMLElement | null = from.parentElement;
  while (row && !row.contains(target)) row = row.parentElement;
  expect(row, 'the two elements share an ancestor').not.toBeNull();
  return row as HTMLElement;
}

function renderInput(props: { disabled?: boolean; withSlot?: boolean } = {}) {
  const { disabled = false, withSlot = true } = props;
  const onSend = vi.fn();
  render(
    <ChatInput
      onSend={onSend}
      disabled={disabled}
      modeControl={withSlot ? <span data-testid="mode-slot">mode control</span> : undefined}
    />,
  );
  return { onSend };
}

describe('ChatInput hint line', () => {
  it('renders the shortened hint', () => {
    renderInput({ withSlot: false });

    expect(screen.getByText(HINT, { exact: true })).toBeInTheDocument();
    expect(screen.queryByText(/Press Enter to send/i)).toBeNull();
    expect(screen.queryByText(/for new line/i)).toBeNull();
  });

  it('renders the mode control slot', () => {
    renderInput();

    const slot = screen.getByTestId('mode-slot');
    const hint = screen.getByText(HINT, { exact: true });
    const textarea = screen.getByTestId('chat-input');

    // Part of ChatInput's form, below the textarea, on the right of the hint.
    expect(slot.closest('form')).not.toBeNull();
    expect(slot.closest('form')).toBe(textarea.closest('form'));
    expect(follows(textarea, slot)).toBe(true);
    expect(follows(hint, slot)).toBe(true);
    // In the hint's row: the smallest container holding the hint and the slot is not the one
    // holding the textarea.
    expect(commonRow(hint, slot).contains(textarea)).toBe(false);
  });

  it('places the mode control after the line/char counter while typing', () => {
    renderInput();
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: 'hello' } });

    const counter = screen.getByText('1 line · 5 chars');
    const slot = screen.getByTestId('mode-slot');
    const hint = screen.getByText(HINT, { exact: true });

    expect(follows(counter, slot)).toBe(true);
    expect(follows(hint, counter)).toBe(true);
    expect(commonRow(counter, slot).contains(screen.getByTestId('chat-input'))).toBe(false);
  });

  it('still renders the mode control when the input is disabled', () => {
    renderInput({ disabled: true });

    expect(screen.getByTestId('chat-input')).toBeDisabled();
    expect(screen.getByTestId('mode-slot')).toBeInTheDocument();
  });

  it('renders the hint and no slot when no mode control is given', () => {
    renderInput({ withSlot: false });

    expect(screen.getByText(HINT, { exact: true })).toBeInTheDocument();
    expect(screen.queryByTestId('mode-slot')).toBeNull();
  });
});
