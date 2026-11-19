/**
 * Presenter view, Task 6: the private presenter window at /sessions/:sessionId/present.
 *
 *   - It loads the deck with api.getSlides and renders, for the slide presentation mode reports: "Slide N of M",
 *     the slide title (first h1/h2 of the slide HTML, else "Slide N"), an m:ss elapsed clock, Read aloud (the talk
 *     track), Coming up (next slide's title and first talk-track paragraph, or "End of deck"), the "On screen now"
 *     and "Up next" sandboxed previews, a Notes drawer, and a bottom bar with Back, Next, Notes and link status.
 *   - Presentation mode is the only source of truth: Next/Back (buttons and keys) post `cmd` messages and the
 *     shown slide changes only when a `state` message arrives.
 *   - "Slides: linked" while state messages arrive; after 3 s of silence "Slides: not linked" and an
 *     "Open presentation" button that focuses the opener, or opens the editor in a NEW tab.
 *   - A posted deckVersion that differs from the one seen before triggers a refetch; when the fetched deck still
 *     differs from the posted version, it says "Slides changed. Reopen the presentation to see them."
 *   - A first-run hint shows once (localStorage `tellr-presenter-hint-seen`). The page is read-only.
 *
 * The test plays the slides window over an in-memory BroadcastChannel fake on globalThis (same name delivers to
 * the other instances, synchronously, never to itself).
 *
 * SABOTAGE targets:
 *   - move the shown slide on the presenter's own Next, without a state message -> "do not move" RED.
 *   - change the link timeout to 30 s                                           -> "not linked after 3 seconds" RED.
 *   - window.location.assign the editor from "Open presentation"               -> "with no opener" RED.
 *   - always open /edit from "Open presentation", whatever my_permission says   -> "view-only presenter" RED.
 *   - never refetch on a new deckVersion                                        -> "new deckVersion" RED.
 *   - set the hint key only on dismiss, or never                               -> "first-run hint" RED.
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SlideDeck } from '../../types/slide';

vi.mock('../../services/api', () => ({
  api: { getSlides: vi.fn() },
}));

import { api } from '../../services/api';
import { PresenterPage } from './PresenterPage';

// ---------------------------------------------------------------------------------------------------------------
// In-memory BroadcastChannel fake.
type Listener = (e: MessageEvent) => void;

class FakeBroadcastChannel {
  static channels = new Map<string, Set<FakeBroadcastChannel>>();

  readonly name: string;
  onmessage: Listener | null = null;
  closed = false;
  private listeners = new Set<Listener>();

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

  addEventListener(type: string, listener: Listener) {
    if (type === 'message') this.listeners.add(listener);
  }

  removeEventListener(type: string, listener: Listener) {
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

// ---------------------------------------------------------------------------------------------------------------
// Fixtures.
const HINT = 'Share only the slides window. Full screen on one screen will cover this window.';
const HINT_KEY = 'tellr-presenter-hint-seen';

function deck(version = 4): SlideDeck {
  const slides = [
    {
      html: '<div class="slide"><h1>Revenue up</h1><p>Q3 revenue grew 12%.</p></div>',
      talk_track: 'Beat 1a.\n\nBeat 1b.',
      speaker_notes: 'Know 1.',
    },
    {
      html: '<div class="slide"><p>Kicker</p><h2>Margin holds</h2><p>Gross margin 61%.</p></div>',
      talk_track: 'Beat 2a.\n\nBeat 2b.',
      speaker_notes: 'Know 2: source is finance.gl.',
    },
    {
      html: '<div class="slide"><p>Close the quarter</p></div>',
      talk_track: 'Beat 3a.\n\nBeat 3b.',
      speaker_notes: 'Know 3.',
    },
  ];
  return {
    title: 'Deck',
    slide_count: slides.length,
    css: '',
    external_scripts: [],
    scripts: '',
    version,
    slides: slides.map((s, i) => ({
      index: i,
      slide_id: `s${i}`,
      scripts: '',
      talk_track_source: 'model',
      speaker_notes_source: 'model',
      ...s,
    })),
  } as unknown as SlideDeck;
}

const getSlides = vi.mocked(api.getSlides);

/** `my_permission` sits beside `slide_deck` in GET /api/sessions/{id}/slides; omitted unless a test passes it. */
function respondWith(d: SlideDeck, my_permission?: 'CAN_VIEW' | 'CAN_EDIT' | 'CAN_MANAGE') {
  return my_permission ? { session_id: 's1', slide_deck: d, my_permission } : { session_id: 's1', slide_deck: d };
}

/** Flush pending promises (the mocked fetch) and the React work they schedule, without moving the clock. */
async function flush() {
  await act(async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve();
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** The test's stand-in for the presentation-mode window: posts state, records what the presenter sends. */
function slidesWindow() {
  const received: unknown[] = [];
  const channel = new FakeBroadcastChannel('tellr-present:s1');
  channel.onmessage = (e) => received.push(e.data);
  return {
    received,
    cmds: () => received.filter((m) => (m as { type?: string })?.type === 'cmd'),
    state(index: number, deckVersion: number | null = 4, total = 3) {
      act(() => channel.postMessage({ type: 'state', index, total, deckVersion }));
    },
    close: () => channel.close(),
  };
}

async function renderPresenter() {
  const view = render(
    <MemoryRouter initialEntries={['/sessions/s1/present']}>
      <Routes>
        <Route path="/sessions/:sessionId/present" element={<PresenterPage />} />
        <Route path="/sessions/:sessionId/edit" element={<div>EDITOR ROUTE</div>} />
      </Routes>
    </MemoryRouter>,
  );
  await flush();
  return view;
}

function drawerOpen(): boolean {
  const el = screen.queryByTestId('presenter-notes-drawer');
  if (!el) return false;
  try {
    expect(el).toBeVisible();
    return true;
  } catch {
    return false;
  }
}

function pressKey(key: string) {
  fireEvent.keyDown(document.body, { key });
}

/** jsdom's window.opener cannot be spied on; define it per test and remove it afterwards. */
function setOpener(value: unknown) {
  Object.defineProperty(window, 'opener', { configurable: true, writable: true, value });
}

function iframeByTitle(title: string): HTMLIFrameElement | null {
  return document.querySelector(`iframe[title="${title}"]`);
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeBroadcastChannel.channels.clear();
  vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
  localStorage.clear();
  getSlides.mockReset();
  getSlides.mockResolvedValue(respondWith(deck()));
});

afterEach(() => {
  setOpener(null);
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------------------------------------------
describe('PresenterPage', () => {
  it('loads the deck for the route session and shows slide 1, not linked, before any state arrives', async () => {
    await renderPresenter();

    expect(getSlides).toHaveBeenCalledWith('s1');
    expect(screen.getByText('Slide 1 of 3')).toBeInTheDocument();
    expect(screen.getByText('Revenue up')).toBeInTheDocument();
    expect(screen.getByText('Beat 1a.')).toBeInTheDocument();
    expect(screen.getByText('Slides: not linked')).toBeInTheDocument();
  });

  it('renders every section for the slide presentation mode reports', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(1);

    // Header: position, title (the first h1/h2, not the kicker paragraph), clock.
    expect(screen.getByText('Slide 2 of 3')).toBeInTheDocument();
    expect(screen.getByText('Margin holds')).toBeInTheDocument();
    expect(screen.getByText(/\b0:00\b/)).toBeInTheDocument();

    // Read aloud: this slide's talk track, one paragraph per beat.
    expect(screen.getByText('Read aloud')).toBeInTheDocument();
    expect(screen.getByText('Beat 2a.')).toBeInTheDocument();
    expect(screen.getByText('Beat 2b.')).toBeInTheDocument();
    expect(screen.queryByText(/Beat 1a\./)).toBeNull();

    // Coming up: the next slide's title (fallback "Slide 3": it has no h1/h2) and only its first beat.
    expect(screen.getByText('Coming up')).toBeInTheDocument();
    expect(screen.getByText('Slide 3')).toBeInTheDocument();
    expect(screen.getByText(/Beat 3a\./)).toBeInTheDocument();
    expect(screen.queryByText(/Beat 3b\./)).toBeNull();

    // Previews: passive sandboxed frames of the current and the next slide.
    const onScreen = iframeByTitle('On screen now');
    const upNext = iframeByTitle('Up next');
    expect(onScreen).not.toBeNull();
    expect(upNext).not.toBeNull();
    expect(onScreen!.getAttribute('sandbox')).toBe('allow-scripts');
    expect(upNext!.getAttribute('sandbox')).toBe('allow-scripts');
    expect(onScreen!.getAttribute('srcdoc')).toContain('Margin holds');
    expect(upNext!.getAttribute('srcdoc')).toContain('Close the quarter');

    // Bottom bar.
    expect(screen.getByRole('button', { name: /^back/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^next/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /notes/i })).toBeInTheDocument();
    expect(screen.getByText('Slides: linked')).toBeInTheDocument();
  });

  it('the elapsed clock advances in m:ss', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(0);
    expect(screen.getByText(/\b0:00\b/)).toBeInTheDocument();

    await advance(65_000);
    expect(screen.getByText(/\b1:05\b/)).toBeInTheDocument();
    expect(screen.queryByText(/\b0:00\b/)).toBeNull();
  });

  it('on the last slide, Coming up reads "End of deck" and there is no Up next preview', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(2);

    expect(screen.getByText('Slide 3 of 3')).toBeInTheDocument();
    // Title fallback in the header: slide 3 has no h1/h2.
    expect(screen.getByText('Slide 3')).toBeInTheDocument();
    expect(screen.getByText('End of deck')).toBeInTheDocument();
    expect(iframeByTitle('On screen now')).not.toBeNull();
    expect(iframeByTitle('Up next')).toBeNull();
  });

  // Sabotage target: step the presenter's own index on Next/Back instead of waiting for presentation mode.
  it('Next and Back buttons post cmd messages and do not move until a state message arrives', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(1);

    fireEvent.click(screen.getByRole('button', { name: /^next/i }));
    expect(slides.cmds()).toEqual([expect.objectContaining({ type: 'cmd', action: 'next' })]);
    expect(screen.getByText('Slide 2 of 3')).toBeInTheDocument();
    expect(screen.getByText('Beat 2a.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^back/i }));
    expect(slides.cmds()).toEqual([
      expect.objectContaining({ type: 'cmd', action: 'next' }),
      expect.objectContaining({ type: 'cmd', action: 'prev' }),
    ]);
    expect(screen.getByText('Slide 2 of 3')).toBeInTheDocument();

    // Presentation mode answers: only now does the presenter move.
    slides.state(2);
    expect(screen.getByText('Slide 3 of 3')).toBeInTheDocument();
    expect(screen.getByText('Beat 3a.')).toBeInTheDocument();
  });

  it('Right, Space, Left and Backspace post next/prev and do not move until a state message arrives', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(1);

    pressKey('ArrowRight');
    pressKey(' ');
    pressKey('ArrowLeft');
    pressKey('Backspace');

    expect(slides.cmds()).toEqual([
      expect.objectContaining({ type: 'cmd', action: 'next' }),
      expect.objectContaining({ type: 'cmd', action: 'next' }),
      expect.objectContaining({ type: 'cmd', action: 'prev' }),
      expect.objectContaining({ type: 'cmd', action: 'prev' }),
    ]);
    expect(screen.getByText('Slide 2 of 3')).toBeInTheDocument();

    slides.state(0);
    expect(screen.getByText('Slide 1 of 3')).toBeInTheDocument();
  });

  it('N toggles the Notes drawer with the current slide notes, and Esc closes it', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(1);
    expect(drawerOpen()).toBe(false);

    pressKey('n');
    expect(drawerOpen()).toBe(true);
    expect(screen.getByTestId('presenter-notes-drawer')).toHaveTextContent('Know 2: source is finance.gl.');

    pressKey('N');
    expect(drawerOpen()).toBe(false);

    pressKey('n');
    expect(drawerOpen()).toBe(true);
    pressKey('Escape');
    expect(drawerOpen()).toBe(false);

    // Neither key is a slide command.
    expect(slides.cmds()).toEqual([]);
  });

  it('the Notes button in the bottom bar toggles the drawer, like N', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(0);
    expect(drawerOpen()).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: /notes/i }));
    expect(drawerOpen()).toBe(true);
    expect(screen.getByTestId('presenter-notes-drawer')).toHaveTextContent('Know 1.');

    fireEvent.click(screen.getByRole('button', { name: /notes/i }));
    expect(drawerOpen()).toBe(false);
  });

  // Review Focus 4: presentation mode closed while the presenter stays open.
  it('shows not linked after 3 seconds of silence', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(0);
    expect(screen.getByText('Slides: linked')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Open presentation' })).toBeNull();

    await advance(2999);
    expect(screen.getByText('Slides: linked')).toBeInTheDocument();

    await advance(1);
    expect(screen.getByText('Slides: not linked')).toBeInTheDocument();
    expect(screen.queryByText('Slides: linked')).toBeNull();
    expect(screen.getByRole('button', { name: 'Open presentation' })).toBeInTheDocument();

    // Next and Back still work without throwing, and the slide stays put.
    expect(() => {
      fireEvent.click(screen.getByRole('button', { name: /^next/i }));
      fireEvent.click(screen.getByRole('button', { name: /^back/i }));
    }).not.toThrow();
    expect(screen.getByText('Slide 1 of 3')).toBeInTheDocument();

    // A heartbeat from a reopened presentation links it again.
    slides.state(0);
    expect(screen.getByText('Slides: linked')).toBeInTheDocument();
  });

  it('each state message restarts the 3 second link timer', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(0);

    for (let i = 0; i < 5; i++) {
      await advance(1000);
      slides.state(0);
    }
    expect(screen.getByText('Slides: linked')).toBeInTheDocument();
  });

  it('"Open presentation" focuses the window that opened the presenter', async () => {
    const opener = { focus: vi.fn() };
    setOpener(opener);
    const open = vi.spyOn(window, 'open').mockReturnValue(null);

    await renderPresenter();
    await advance(3000);

    fireEvent.click(screen.getByRole('button', { name: 'Open presentation' }));
    expect(opener.focus).toHaveBeenCalledTimes(1);
    expect(open).not.toHaveBeenCalled();
  });

  it('"Open presentation" with no opener opens the editor in a new tab, never replacing the presenter', async () => {
    setOpener(null);
    const open = vi.spyOn(window, 'open').mockReturnValue(null);

    await renderPresenter();
    await advance(3000);

    fireEvent.click(screen.getByRole('button', { name: 'Open presentation' }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(open.mock.calls[0][0]).toBe('/sessions/s1/edit');
    expect(open.mock.calls[0][1]).toBe('_blank');

    // The presenter is still here: no in-app navigation to the editor route.
    expect(screen.queryByText('EDITOR ROUTE')).toBeNull();
    expect(screen.getByText('Slides: not linked')).toBeInTheDocument();
  });

  // Sabotage target: always opens /edit, ignoring my_permission.
  it('a view-only presenter opens the view page when there is no opener', async () => {
    setOpener(null);
    getSlides.mockResolvedValue(respondWith(deck(), 'CAN_VIEW'));
    const open = vi.spyOn(window, 'open').mockReturnValue(null);

    await renderPresenter();
    await advance(3000);

    fireEvent.click(screen.getByRole('button', { name: 'Open presentation' }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(open.mock.calls[0][0]).toBe('/sessions/s1/view');
    expect(open.mock.calls[0][1]).toBe('_blank');

    // The presenter is still here: no in-app navigation away.
    expect(screen.queryByText('EDITOR ROUTE')).toBeNull();
    expect(screen.getByText('Slides: not linked')).toBeInTheDocument();
  });

  // Sabotage target: never refetch on a deckVersion change.
  it('a state message with a new deckVersion refetches the deck', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    expect(getSlides).toHaveBeenCalledTimes(1);

    // Same version as the fetched deck: no refetch, even across heartbeats.
    slides.state(0, 4);
    slides.state(0, 4);
    await flush();
    expect(getSlides).toHaveBeenCalledTimes(1);

    getSlides.mockResolvedValue(respondWith(deck(5)));
    slides.state(0, 5);
    await flush();
    expect(getSlides).toHaveBeenCalledTimes(2);
    expect(getSlides).toHaveBeenLastCalledWith('s1');

    // The refetched deck matches: no further fetch on the next heartbeat, and no mismatch warning.
    slides.state(0, 5);
    await flush();
    expect(getSlides).toHaveBeenCalledTimes(2);
    expect(screen.queryByText('Slides changed. Reopen the presentation to see them.')).toBeNull();
  });

  it('says the slides changed when the fetched deck version differs from the one presentation mode posts', async () => {
    const slides = slidesWindow();
    // Chat edited the deck after Present opened: the server is on version 6, presentation mode still shows 4.
    getSlides.mockResolvedValue(respondWith(deck(6)));
    await renderPresenter();

    slides.state(0, 4);
    await flush();
    expect(screen.getByText('Slides changed. Reopen the presentation to see them.')).toBeInTheDocument();

    // It does not refetch on every heartbeat for the same posted version.
    const calls = getSlides.mock.calls.length;
    slides.state(0, 4);
    slides.state(0, 4);
    await flush();
    expect(getSlides.mock.calls.length).toBe(calls);
  });

  it('the first-run hint shows the exact text once and is gone after reload', async () => {
    const first = await renderPresenter();
    expect(screen.getByText(HINT)).toBeInTheDocument();
    expect(localStorage.getItem(HINT_KEY)).not.toBeNull();
    first.unmount();

    await renderPresenter();
    expect(screen.queryByText(HINT)).toBeNull();
  });

  it('the hint stays hidden when it was already seen', async () => {
    localStorage.setItem(HINT_KEY, '1');
    await renderPresenter();
    expect(screen.queryByText(HINT)).toBeNull();
  });

  // Sabotage target: leave the channel open, or the link timer pending, when the presenter page goes away.
  it('closing the presenter leaves the channel and leaves no timer behind', async () => {
    const slides = slidesWindow();
    const view = await renderPresenter();
    slides.state(0);
    expect(FakeBroadcastChannel.channels.get('tellr-present:s1')?.size).toBe(2);

    view.unmount();
    expect(FakeBroadcastChannel.channels.get('tellr-present:s1')?.size).toBe(1);
    // A state message after close reaches nobody and throws nothing.
    expect(() => slides.state(1)).not.toThrow();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('PageDown and PageUp step like Right and Left, for presentation clickers', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(1);

    pressKey('PageDown');
    pressKey('PageUp');
    expect(slides.cmds()).toEqual([
      expect.objectContaining({ type: 'cmd', action: 'next' }),
      expect.objectContaining({ type: 'cmd', action: 'prev' }),
    ]);
    expect(screen.getByText('Slide 2 of 3')).toBeInTheDocument();
  });

  it('renders no editor control', async () => {
    const slides = slidesWindow();
    const { container } = await renderPresenter();
    slides.state(1);
    pressKey('n');

    expect(container.querySelector('textarea, input, select, [contenteditable="true"], [contenteditable=""]')).toBeNull();
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(screen.queryByRole('button', { name: /save/i })).toBeNull();
  });
});
