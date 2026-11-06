/**
 * Speaker notes, Task 10 (plan D6): a notes panel in presentation mode, toggled by N and a toolbar button.
 *
 *   - N (or n) toggles `presentation-notes`, which shows the CURRENT slide's notes as plain text, or
 *     `presentation-notes-empty` when the slide has none. The panel follows navigation.
 *   - The key goes through the one handler the iframe key bridge feeds, so an N forwarded as a
 *     `tellr:slide-key` message from the slide iframe toggles too; a message from any other source does not.
 *   - The toolbar button `presentation-notes-toggle` toggles the same state and reports it via aria-pressed.
 *   - Arrows, Home, End and Escape behave as before with the panel open; N typed into an input is ignored.
 *
 * SABOTAGE (each run against a throwaway implementation, then reverted):
 *   - drop the `case 'n'` / `case 'N'`                     -> N / bridge / existing-keys tests RED.
 *   - render notes from slide 0 whatever the current slide -> "follows navigation" RED.
 *   - render notes via dangerouslySetInnerHTML              -> "follows navigation" RED (an <i> appears).
 *   - `if (e.data.key === 'N') return;` in the bridge       -> "forwarded from the slide iframe" RED.
 *   - drop the `e.source` guard in the bridge               -> "another source" RED.
 *   - omit aria-pressed, or wire the button to a no-op      -> "toolbar button" RED.
 *   - drop the INPUT/TEXTAREA guard in the key handler      -> "input" RED.
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { SlideDeck } from '../../types/slide';
import { PresentationMode } from './PresentationMode';

const NOTES = ['N1', '', '<i>N3</i>'];

function deck(): SlideDeck {
  return {
    title: 'Deck',
    slide_count: NOTES.length,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: NOTES.map((n, i) => ({
      index: i,
      slide_id: `s${i}`,
      html: `<div class="slide">Slide ${i + 1}</div>`,
      scripts: '',
      speaker_notes: n,
    })),
  } as unknown as SlideDeck;
}

function renderPresentation() {
  const onExit = vi.fn();
  render(<PresentationMode slideDeck={deck()} onExit={onExit} />);
  return { onExit };
}

function press(key: string, target: Window | Element = window) {
  fireEvent.keyDown(target, { key });
}

function panel(): HTMLElement | null {
  return screen.queryByTestId('presentation-notes');
}

function slideFrameWindow(): Window {
  const iframe = document.body.querySelector('iframe');
  expect(iframe).not.toBeNull();
  expect(iframe!.contentWindow).not.toBeNull();
  return iframe!.contentWindow!;
}

function postKey(key: string, source: Window) {
  act(() => {
    window.dispatchEvent(
      new MessageEvent('message', { data: { type: 'tellr:slide-key', key }, source }),
    );
  });
}

describe('PresentationMode speaker notes panel', () => {
  // Sabotage target: drop the `case 'n'` from the key handler's switch.
  it("N toggles the notes panel with the current slide's notes", () => {
    renderPresentation();
    expect(panel()).toBeNull();

    press('n');
    expect(panel()).not.toBeNull();
    expect(panel()).toHaveTextContent('N1');

    press('n');
    expect(panel()).toBeNull();
  });

  // Sabotage target: read the notes of slide 0 (not currentSlideIndex), or render them as HTML.
  it('the panel follows slide navigation and renders notes as text', () => {
    renderPresentation();
    press('N');
    expect(panel()).toHaveTextContent('N1');

    press('ArrowRight');
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
    expect(panel()).not.toHaveTextContent('N1');
    expect(screen.getByTestId('presentation-notes-empty')).toBeInTheDocument();

    press('ArrowRight');
    expect(screen.getByText('3 / 3')).toBeInTheDocument();
    expect(screen.queryByTestId('presentation-notes-empty')).toBeNull();
    expect(panel()).toHaveTextContent('<i>N3</i>');
    expect(panel()!.querySelector('i')).toBeNull();
  });

  // Sabotage target: an early `return` for n/N in the tellr:slide-key bridge listener.
  it('an N forwarded from the slide iframe toggles the panel', () => {
    renderPresentation();
    const frame = slideFrameWindow();

    postKey('N', frame);
    expect(panel()).not.toBeNull();
    expect(panel()).toHaveTextContent('N1');

    postKey('N', frame);
    expect(panel()).toBeNull();
  });

  // Sabotage target: drop the `e.source !== iframeRef.current?.contentWindow` guard.
  it('a key message from another source is ignored', () => {
    renderPresentation();

    postKey('N', window);
    expect(panel()).toBeNull();

    // Control: the same message from the slide iframe does toggle, so the miss above is the source check.
    postKey('N', slideFrameWindow());
    expect(panel()).not.toBeNull();
  });

  // Sabotage target: omit aria-pressed, or leave the button's onClick unwired.
  it('the toolbar button toggles the panel and reports its state', () => {
    renderPresentation();
    const button = screen.getByTestId('presentation-notes-toggle');
    expect(button).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-pressed', 'true');
    expect(panel()).toHaveTextContent('N1');

    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-pressed', 'false');
    expect(panel()).toBeNull();
  });

  // Sabotage target: let the 'n' case fall through into (or replace) another case.
  it('existing keys still work with the panel open', () => {
    const { onExit } = renderPresentation();
    press('n');
    expect(panel()).not.toBeNull();
    expect(screen.getByText('1 / 3')).toBeInTheDocument();

    press('End');
    expect(screen.getByText('3 / 3')).toBeInTheDocument();
    press('ArrowLeft');
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
    press('Home');
    expect(screen.getByText('1 / 3')).toBeInTheDocument();
    expect(panel()).not.toBeNull();
    expect(onExit).not.toHaveBeenCalled();

    press('Escape');
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  // Sabotage target: drop the INPUT/TEXTAREA/contentEditable guard at the top of the key handler.
  it('N typed into an input is ignored', () => {
    renderPresentation();
    const input = document.createElement('input');
    document.body.appendChild(input);
    try {
      press('n', input);
      expect(panel()).toBeNull();

      // Control: the same key outside the input does toggle, so the miss above is the input guard.
      press('n');
      expect(panel()).not.toBeNull();
    } finally {
      input.remove();
    }
  });
});
