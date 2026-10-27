/**
 * Deck Mode toggle, Task 8: the Mode control that sits on the right of ChatInput's hint line.
 *
 * Contract (task brief + PLAN-CORRECTIONS Task 8 + Global Constraints, copy verbatim):
 *   - `DeckModeSelect({ value, locked, onChange })` renders the visible label `Mode`, a NATIVE
 *     `<select aria-label="Mode" data-testid="deck-mode-select" disabled={locked}>` with exactly the
 *     options `Agent mode` (`agent`) and `Legacy mode` (`legacy`), and an info icon
 *     (`data-testid="deck-mode-info"`).
 *   - The select is controlled: it always shows `value`, and a change calls `onChange(mode)`.
 *   - The info icon's popup (src/ui/tooltip) holds the three exact lines. It opens on hover and on
 *     focus, and still opens when the control is locked (so the trigger itself is never disabled).
 *   - The trigger sits inside ChatInput's <form>: it is a `type="button"` with an aria-label, so
 *     clicking it never submits the message.
 *   - It wraps its own TooltipProvider (C3), so it renders here with no provider ancestor.
 *
 * Radix TooltipContent renders its children twice (one visible copy, one VisuallyHidden
 * `role="tooltip"` copy), so `findByText(line)` would throw "multiple elements". Per C4 the popup is
 * read as `findByRole('tooltip')` + `toHaveTextContent(line)`.
 */
import type { FormEvent } from 'react';
import { describe, it, expect, vi, afterEach, beforeAll, afterAll } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import type { DeckMode } from '../../services/api';
import { DeckModeSelect } from './DeckModeSelect';

const POPUP_LINES = [
  'Agent mode: plans the deck, then builds it slide by slide, showing progress as it goes.',
  'Legacy mode: a less capable agent. Usually faster, but harder to converse with and to adapt to changes.',
  "You can change this until you send your first message. After that it's fixed for this deck.",
] as const;

const LABELS: Record<DeckMode, string> = { agent: 'Agent mode', legacy: 'Legacy mode' };

function renderSelect({ value = 'agent', locked = false }: { value?: DeckMode; locked?: boolean } = {}) {
  const onChange = vi.fn();
  const view = render(<DeckModeSelect value={value} locked={locked} onChange={onChange} />);
  return { onChange, view, select: () => screen.getByTestId('deck-mode-select') as HTMLSelectElement };
}

/** The info trigger: the `deck-mode-info` element itself if it is the button, else its button. */
function infoButton(): HTMLButtonElement {
  const info = screen.getByTestId('deck-mode-info');
  const button = info.closest('button');
  expect(button, 'the info icon is a <button> (or sits in one)').not.toBeNull();
  return button as HTMLButtonElement;
}

type Opener = 'hover' | 'focus';
async function openPopup(how: Opener) {
  const button = infoButton();
  if (how === 'hover') {
    fireEvent.pointerMove(button); // Radix opens on pointermove (not mouseenter)
  } else {
    // element.focus() fires focus AND focusin (React's onFocus listens to focusin).
    act(() => { button.focus(); });
  }
  return screen.findByRole('tooltip');
}

// jsdom harness fix, not a behaviour stub. Radix's popper (floating-ui) probes
// `element.matches(':popover-open')` and `element.matches(':modal')` on every position update. jsdom's
// selector engine (nwsapi 2.2.x) recurses on those pseudo-classes until the stack overflows; floating-ui
// catches the RangeError, but each overflow costs seconds, so an open tooltip stalls the event loop for
// 10 s+ and every popup test times out. Nothing here is in the top layer, so answer false, as a browser
// would. Every other selector goes to jsdom.
const nativeMatches = Element.prototype.matches;
beforeAll(() => {
  Element.prototype.matches = function matches(this: Element, selector: string) {
    if (/:(popover-open|modal)\b/.test(selector)) return false;
    return nativeMatches.call(this, selector);
  };
});
afterAll(() => {
  Element.prototype.matches = nativeMatches;
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe('DeckModeSelect', () => {
  it('shows Mode with Agent mode and Legacy mode options', () => {
    const { select } = renderSelect();

    expect(screen.getByText('Mode', { exact: true })).toBeInTheDocument(); // the visible label
    const el = select();
    expect(el.tagName).toBe('SELECT'); // native, not a custom listbox
    expect(screen.getByRole('combobox', { name: 'Mode' })).toBe(el);
    expect(Array.from(el.options).map((o) => [o.textContent, o.value])).toEqual([
      ['Agent mode', 'agent'],
      ['Legacy mode', 'legacy'],
    ]);
    expect(el.value).toBe('agent');
    expect(el).toBeEnabled();
    expect(screen.getByTestId('deck-mode-info')).toBeInTheDocument();
  });

  it.each<DeckMode>(['legacy', 'agent'])('is disabled and shows the stored mode when locked (%s)', (mode) => {
    const { select } = renderSelect({ value: mode, locked: true });

    expect(select()).toBeDisabled();
    expect(select().value).toBe(mode);
    expect(select().selectedOptions[0]?.textContent).toBe(LABELS[mode]);
  });

  it('shows the value it is given and follows it on re-render (a controlled select)', () => {
    const { select, view, onChange } = renderSelect({ value: 'legacy' });
    expect(select().value).toBe('legacy');
    expect(select()).toBeEnabled(); // unlocked: enabled whatever the value

    view.rerender(<DeckModeSelect value="agent" locked={false} onChange={onChange} />);
    expect(select().value).toBe('agent');
    view.rerender(<DeckModeSelect value="legacy" locked onChange={onChange} />);
    expect(select().value).toBe('legacy');
    expect(select()).toBeDisabled();
  });

  it('calls onChange with "legacy"', () => {
    const { select, onChange } = renderSelect({ value: 'agent' });

    fireEvent.change(select(), { target: { value: 'legacy' } });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('legacy');
  });

  it('calls onChange with "agent" when switching back', () => {
    const { select, onChange } = renderSelect({ value: 'legacy' });

    fireEvent.change(select(), { target: { value: 'agent' } });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('agent');
  });

  it('renders with no React warning (a controlled select with a defined value)', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const { select, view, onChange } = renderSelect({ value: 'agent' });
    fireEvent.change(select(), { target: { value: 'legacy' } });
    view.rerender(<DeckModeSelect value="legacy" locked onChange={onChange} />);

    expect(consoleError.mock.calls.map((c) => String(c[0]))).toEqual([]);
  });

  it.each<Opener>(['hover', 'focus'])('the info popup shows the three exact lines (%s)', async (how) => {
    renderSelect();
    expect(screen.queryByRole('tooltip')).toBeNull(); // closed until asked

    const tooltip = await openPopup(how);

    for (const line of POPUP_LINES) {
      expect(tooltip).toHaveTextContent(line);
    }
  });

  it.each<Opener>(['hover', 'focus'])('the popup still opens when locked (%s)', async (how) => {
    renderSelect({ value: 'legacy', locked: true });
    expect(screen.getByTestId('deck-mode-select')).toBeDisabled();
    expect(infoButton()).toBeEnabled(); // a disabled trigger gets no hover or focus

    const tooltip = await openPopup(how);

    for (const line of POPUP_LINES) {
      expect(tooltip).toHaveTextContent(line);
    }
  });

  it('the info icon is a type="button" with an aria-label', () => {
    renderSelect();
    const button = infoButton();

    expect(button).toHaveAttribute('type', 'button');
    expect(button.getAttribute('aria-label')?.trim()).toBeTruthy();
  });

  it('clicking the info icon inside a form does not submit it (ChatInput hosts it in its <form>)', () => {
    const onSubmit = vi.fn((e: FormEvent) => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <DeckModeSelect value="agent" locked={false} onChange={vi.fn()} />
        <button type="submit">Send</button>
      </form>,
    );

    fireEvent.click(infoButton());
    fireEvent.change(screen.getByTestId('deck-mode-select'), { target: { value: 'legacy' } });
    expect(onSubmit).not.toHaveBeenCalled();

    // Positive control: the harness does see a real submit.
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
