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
import type { ComponentProps } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

// ===============================================================================================================
// Presenter view, Task 6: presentation mode opens the presenter window and is the only source of truth for it.
//
//   - P, the "Open presenter view" toolbar button, and a `p` forwarded over the tellr:slide-key bridge open the
//     presenter window for this session. window.open runs inside the key/click/message handler itself (no effect,
//     no timer), so the browser's user activation still applies (Review Focus 3).
//   - Without a sessionId the button is hidden and P does nothing.
//   - It posts {type:'state', index, total, deckVersion} on mount, on every slide change, and every second while open,
//     on the `tellr-present:<sessionId>` channel; deckVersion is the version of the deck it snapshotted on open.
//   - A `cmd` next / prev / goto from the presenter moves the slide, clamped to the deck.
//   - The N panel shows the talk track, then falls back to the notes, then to "No speaker notes for this slide."
//
// SABOTAGE targets:
//   - drop the heartbeat interval                       -> "every second" RED.
//   - render the N panel from notes first               -> "talk track first" RED.
//   - open the window from a useEffect or setTimeout    -> "inside the handler" assertions RED.
//   - skip the clamp on goto                            -> "clamped" RED.
//   - keep posting after unmount                        -> "stops posting" RED (the fake throws on a closed post).
// ===============================================================================================================

type ChannelListener = (e: MessageEvent) => void;

class FakeBroadcastChannel {
  static channels = new Map<string, Set<FakeBroadcastChannel>>();

  readonly name: string;
  onmessage: ChannelListener | null = null;
  closed = false;
  private listeners = new Set<ChannelListener>();

  constructor(name: string) {
    this.name = name;
    const peers = FakeBroadcastChannel.channels.get(name) ?? new Set<FakeBroadcastChannel>();
    peers.add(this);
    FakeBroadcastChannel.channels.set(name, peers);
  }

  postMessage(data: unknown) {
    if (this.closed) throw new DOMException('BroadcastChannel is closed', 'InvalidStateError');
    for (const peer of [...(FakeBroadcastChannel.channels.get(this.name) ?? [])]) {
      if (peer !== this && !peer.closed) peer.deliver(structuredClone(data));
    }
  }

  addEventListener(type: string, listener: ChannelListener) {
    if (type === 'message') this.listeners.add(listener);
  }

  removeEventListener(type: string, listener: ChannelListener) {
    if (type === 'message') this.listeners.delete(listener);
  }

  close() {
    this.closed = true;
    FakeBroadcastChannel.channels.get(this.name)?.delete(this);
  }

  private deliver(data: unknown) {
    const event = new MessageEvent('message', { data });
    this.onmessage?.(event);
    for (const listener of [...this.listeners]) listener(event);
  }
}

type PresenterSlide = { talk_track?: string; speaker_notes?: string };

function presenterDeck(slides: PresenterSlide[], version: number | null = 7): SlideDeck {
  return {
    title: 'Deck',
    slide_count: slides.length,
    css: '',
    external_scripts: [],
    scripts: '',
    ...(version === null ? {} : { version }),
    slides: slides.map((s, i) => ({
      index: i,
      slide_id: `p${i}`,
      html: `<div class="slide">Slide ${i + 1}</div>`,
      scripts: '',
      ...s,
    })),
  } as unknown as SlideDeck;
}

const THREE: PresenterSlide[] = [
  { talk_track: 'Say 1.', speaker_notes: 'Know 1.' },
  { talk_track: '', speaker_notes: 'Know 2.' },
  { talk_track: '', speaker_notes: '' },
];

const PRESENT_URL = '/sessions/s1/present';
const PRESENT_NAME = 'tellr-presenter-s1';
const PRESENT_FEATURES = 'popup,width=1200,height=760';

/** The test's stand-in for the presenter window on the session channel. */
function presenterWindow(sessionId = 's1') {
  const received: unknown[] = [];
  const channel = new FakeBroadcastChannel(`tellr-present:${sessionId}`);
  channel.onmessage = (e) => received.push(e.data);
  const states = () =>
    received.filter((m) => (m as { type?: string })?.type === 'state') as Array<{
      type: 'state';
      index: number;
      total: number;
      deckVersion: number | null;
    }>;
  return {
    received,
    states,
    lastState: () => states()[states().length - 1],
    send(cmd: { type: 'cmd'; action: 'next' | 'prev' | 'goto'; index?: number }) {
      act(() => channel.postMessage(cmd));
    },
    clear: () => {
      received.length = 0;
    },
    close: () => channel.close(),
  };
}

describe('PresentationMode presenter view', () => {
  const openedWindows: Array<{ focus: ReturnType<typeof vi.fn>; closed: boolean }> = [];
  let openSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    FakeBroadcastChannel.channels.clear();
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    openSpy = vi.spyOn(window, 'open').mockImplementation(() => {
      const w = { focus: vi.fn(), closed: false };
      openedWindows.push(w);
      return w as unknown as Window;
    });
  });

  afterEach(() => {
    // The opener may remember the window between tests; mark every fake closed so the next test opens afresh.
    for (const w of openedWindows) w.closed = true;
    openedWindows.length = 0;
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  function renderWithSession(d: SlideDeck = presenterDeck(THREE), sessionId: string | null = 's1') {
    const onExit = vi.fn();
    const props = { slideDeck: d, onExit, ...(sessionId === null ? {} : { sessionId }) };
    const view = render(<PresentationMode {...(props as ComponentProps<typeof PresentationMode>)} />);
    return { onExit, ...view };
  }

  // Review Focus 3: window.open must run inside the key handler, so the dispatch below is NOT wrapped in act.
  it('P opens the presenter window from inside the key handler', () => {
    renderWithSession();

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'p', bubbles: true, cancelable: true }));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith(PRESENT_URL, PRESENT_NAME, PRESENT_FEATURES);
    expect(openedWindows[0].focus).toHaveBeenCalled();
  });

  it('a second P reaches the same presenter window', () => {
    renderWithSession();

    press('P');
    const win = openedWindows[0];
    const focusesAfterFirst = win.focus.mock.calls.length;

    press('P');
    // Either a same-name window.open or a focus of the remembered window: never a different window.
    for (const call of openSpy.mock.calls) expect(call[1]).toBe(PRESENT_NAME);
    expect(openedWindows.filter((w) => !w.closed).length).toBeGreaterThanOrEqual(1);
    expect(win.focus.mock.calls.length + (openSpy.mock.calls.length - 1)).toBeGreaterThan(focusesAfterFirst);
  });

  it('the "Open presenter view" toolbar button opens the presenter window', () => {
    renderWithSession();

    fireEvent.click(screen.getByRole('button', { name: 'Open presenter view' }));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith(PRESENT_URL, PRESENT_NAME, PRESENT_FEATURES);
  });

  // Review Focus 3: P pressed inside the sandboxed slide frame arrives over the key bridge.
  it('a p forwarded from the slide iframe opens the presenter window inside the message handler', () => {
    renderWithSession();
    const frame = slideFrameWindow();

    window.dispatchEvent(new MessageEvent('message', { data: { type: 'tellr:slide-key', key: 'p' }, source: frame }));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith(PRESENT_URL, PRESENT_NAME, PRESENT_FEATURES);
  });

  // Whole-branch review: Cmd+P / Ctrl+P is the browser's print. Sabotage target: drop the modifier
  // check on the P case, so a held Cmd, Ctrl or Alt still opens the window and swallows the print.
  it.each([
    ['metaKey', 'p'],
    ['metaKey', 'P'],
    ['ctrlKey', 'p'],
    ['altKey', 'p'],
  ] as const)('P with %s held leaves the key to the browser (%s)', (modifier, key) => {
    renderWithSession();

    const event = new KeyboardEvent('keydown', { key, [modifier]: true, bubbles: true, cancelable: true });
    window.dispatchEvent(event);
    expect(openSpy).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);

    const frame = slideFrameWindow();
    window.dispatchEvent(
      new MessageEvent('message', { data: { type: 'tellr:slide-key', key, [modifier]: true }, source: frame }),
    );
    expect(openSpy).not.toHaveBeenCalled();
  });

  it('a p message from another source does not open the presenter window', () => {
    renderWithSession();

    window.dispatchEvent(new MessageEvent('message', { data: { type: 'tellr:slide-key', key: 'p' }, source: window }));
    expect(openSpy).not.toHaveBeenCalled();
  });

  it('a blocked pop-up does not break presenting', () => {
    openSpy.mockImplementation(() => null);
    const { onExit } = renderWithSession();

    expect(() => press('p')).not.toThrow();
    expect(openSpy).toHaveBeenCalledTimes(1);
    press('ArrowRight');
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
    expect(onExit).not.toHaveBeenCalled();
  });

  it('without a sessionId the presenter button is hidden and P does nothing', () => {
    renderWithSession(presenterDeck(THREE), null);

    expect(screen.queryByRole('button', { name: 'Open presenter view' })).toBeNull();
    press('p');
    press('P');
    expect(openSpy).not.toHaveBeenCalled();
  });

  it('posts a state message on mount with the index, total and snapshot deck version', () => {
    const presenter = presenterWindow();
    renderWithSession();

    expect(presenter.states().length).toBeGreaterThanOrEqual(1);
    expect(presenter.lastState()).toEqual({ type: 'state', index: 0, total: 3, deckVersion: 7 });
  });

  it('posts a state message on each slide change, without waiting for the heartbeat', () => {
    const presenter = presenterWindow();
    renderWithSession();
    presenter.clear();

    press('ArrowRight');
    expect(presenter.lastState()).toEqual({ type: 'state', index: 1, total: 3, deckVersion: 7 });
    press('End');
    expect(presenter.lastState()).toEqual({ type: 'state', index: 2, total: 3, deckVersion: 7 });
    press('Home');
    expect(presenter.lastState()).toEqual({ type: 'state', index: 0, total: 3, deckVersion: 7 });
  });

  // Sabotage target: drop the setInterval heartbeat.
  it('posts a state heartbeat every second while open', () => {
    const presenter = presenterWindow();
    renderWithSession();
    press('ArrowRight');
    presenter.clear();

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(presenter.states().length).toBeGreaterThanOrEqual(1);

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(presenter.states().length).toBeGreaterThanOrEqual(3);
    for (const s of presenter.states()) {
      expect(s).toEqual({ type: 'state', index: 1, total: 3, deckVersion: 7 });
    }
  });

  // Review Focus 4: closing presentation mode must go silent so the presenter can say "not linked".
  it('stops posting after presentation mode closes', () => {
    const presenter = presenterWindow();
    const { unmount } = renderWithSession();
    unmount();
    presenter.clear();

    expect(() =>
      act(() => {
        vi.advanceTimersByTime(5000);
      }),
    ).not.toThrow();
    expect(presenter.states()).toEqual([]);
  });

  // Sabotage targets: leave the channel open, or leave the heartbeat interval running, after presentation mode closes.
  it('closing presentation mode leaves the channel and clears the heartbeat', () => {
    const presenter = presenterWindow();
    const { unmount } = renderWithSession();
    // While open, presentation mode is a second member of the session channel.
    expect(FakeBroadcastChannel.channels.get('tellr-present:s1')?.size).toBe(2);

    unmount();
    // Only the presenter's end is left: presentation mode closed its own.
    expect(FakeBroadcastChannel.channels.get('tellr-present:s1')?.size).toBe(1);
    // A command after close reaches nobody and throws nothing.
    expect(() => presenter.send({ type: 'cmd', action: 'next' })).not.toThrow();

    // One-shot timers run out; a leaked heartbeat interval would still be pending.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(vi.getTimerCount()).toBe(0);
  });

  it('the posted deck version is the snapshot taken on open, and null when the deck has none', () => {
    const presenter = presenterWindow();
    const { rerender, onExit } = renderWithSession(presenterDeck(THREE, 7));

    // A later deck prop (chat edited the deck) does not change what the audience sees, nor the posted version.
    rerender(
      <PresentationMode
        {...({ slideDeck: presenterDeck(THREE, 8), onExit, sessionId: 's1' } as ComponentProps<typeof PresentationMode>)}
      />,
    );
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(presenter.lastState()!.deckVersion).toBe(7);
    cleanup();

    presenter.clear();
    renderWithSession(presenterDeck(THREE, null));
    expect(presenter.lastState()).toEqual({ type: 'state', index: 0, total: 3, deckVersion: null });
  });

  it('only posts on its own session channel', () => {
    const other = presenterWindow('s2');
    renderWithSession();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(other.received).toEqual([]);
  });

  it('a cmd from the presenter moves the slide and reports the new state', () => {
    const presenter = presenterWindow();
    renderWithSession();
    presenter.clear();

    presenter.send({ type: 'cmd', action: 'next' });
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
    expect(presenter.lastState()).toEqual({ type: 'state', index: 1, total: 3, deckVersion: 7 });

    presenter.send({ type: 'cmd', action: 'goto', index: 2 });
    expect(screen.getByText('3 / 3')).toBeInTheDocument();
    expect(presenter.lastState()).toMatchObject({ index: 2 });

    presenter.send({ type: 'cmd', action: 'prev' });
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
    expect(presenter.lastState()).toMatchObject({ index: 1 });
  });

  // Sabotage target: skip the clamp.
  it('cmd next, prev and goto are clamped to the deck', () => {
    const presenter = presenterWindow();
    renderWithSession();

    presenter.send({ type: 'cmd', action: 'prev' });
    expect(screen.getByText('1 / 3')).toBeInTheDocument();

    presenter.send({ type: 'cmd', action: 'goto', index: 99 });
    expect(screen.getByText('3 / 3')).toBeInTheDocument();

    presenter.send({ type: 'cmd', action: 'next' });
    expect(screen.getByText('3 / 3')).toBeInTheDocument();

    presenter.send({ type: 'cmd', action: 'goto', index: -4 });
    expect(screen.getByText('1 / 3')).toBeInTheDocument();
    expect(presenter.lastState()).toMatchObject({ index: 0 });
  });

  // Sabotage target: render the N panel from speaker_notes first.
  it('the N panel starts hidden and shows the talk track first, then notes, then the empty message', () => {
    renderWithSession();
    expect(panel()).toBeNull();

    press('n');
    expect(panel()).toHaveTextContent('Say 1.');
    expect(panel()).not.toHaveTextContent('Know 1.');

    press('ArrowRight');
    expect(panel()).toHaveTextContent('Know 2.');
    expect(screen.queryByTestId('presentation-notes-empty')).toBeNull();

    press('ArrowRight');
    expect(screen.getByTestId('presentation-notes-empty')).toHaveTextContent('No speaker notes for this slide.');
  });
});
