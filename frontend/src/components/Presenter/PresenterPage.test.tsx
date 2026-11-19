/**
 * Presenter view, Task 6: the private presenter window at /sessions/:sessionId/present.
 *
 *   - It loads the deck with api.getSlides and renders, for the slide presentation mode reports: "Slide N of M",
 *     the slide title (first h1/h2 of the slide HTML, else "Slide N"), an m:ss elapsed clock, Read aloud (the talk
 *     track), Coming up (next slide's title and first talk-track paragraph, or "End of deck"), the "On screen now"
 *     and "Up next" sandboxed previews, a Notes panel, and a bottom bar with Back, Next and Notes.
 *   - Presentation mode is the only source of truth: Next/Back (buttons and keys) post `cmd` messages and the
 *     shown slide changes only when a `state` message arrives.
 *   - The Notes panel (N, the Notes button, Esc) slides in from the right as an overlay on the "Up next" column:
 *     from the Up next label row down to just above the bottom bar. The header, Read aloud, Coming up and
 *     "On screen now" stay exactly as they are (author, 2026-11-19).
 *   - There is no link status and no "Open presentation" button in this release (author, 2026-11-19).
 *   - A posted deckVersion that differs from the one seen before triggers a refetch; when the fetched deck still
 *     differs from the posted version, it says "Slides changed. Reopen the presentation to see them."
 *   - A first-run hint shows once (localStorage `tellr-presenter-hint-seen`). The page is read-only.
 *
 * The test plays the slides window over an in-memory BroadcastChannel fake on globalThis (same name delivers to
 * the other instances, synchronously, never to itself).
 *
 * SABOTAGE targets:
 *   - move the shown slide on the presenter's own Next, without a state message -> "do not move" RED.
 *   - render the Notes panel in the flow below the previews                     -> "overlays only the Up next" RED.
 *   - leave the panel's transform at rest when it opens                         -> "slides in" RED.
 *   - narrow the top section while the panel is open                            -> "exactly as they were" RED.
 *   - never refetch on a new deckVersion                                        -> "new deckVersion" RED.
 *   - set the hint key only on dismiss, or never                               -> "first-run hint" RED.
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
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

function respondWith(d: SlideDeck) {
  return { session_id: 's1', slide_deck: d };
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
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------------------------------------------
describe('PresenterPage', () => {
  it('loads the deck for the route session and shows slide 1 before any state arrives', async () => {
    await renderPresenter();

    expect(getSlides).toHaveBeenCalledWith('s1');
    expect(screen.getByText('Slide 1 of 3')).toBeInTheDocument();
    expect(screen.getByText('Revenue up')).toBeInTheDocument();
    expect(screen.getByText('Beat 1a.')).toBeInTheDocument();
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

  it('the Notes panel names this slide: a small eyebrow, a Notes heading, then the notes', async () => {
    getSlides.mockResolvedValue(
      respondWith({
        ...deck(),
        slides: deck().slides.map((sl, i) =>
          i === 0 ? { ...sl, speaker_notes: 'Para one.\n\nPara two.' } : sl,
        ),
      } as SlideDeck),
    );
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(0);
    pressKey('n');

    const panel = screen.getByTestId('presenter-notes-drawer');
    expect(within(panel).getByText(/^notes · this slide$/i)).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: 'Notes' })).toBeInTheDocument();
    // One paragraph per block of the notes.
    expect(within(panel).getByText('Para one.').tagName).toBe('P');
    expect(within(panel).getByText('Para two.').tagName).toBe('P');
  });

  it('a slide without notes says so in the panel', async () => {
    getSlides.mockResolvedValue(
      respondWith({ ...deck(), slides: deck().slides.map((sl) => ({ ...sl, speaker_notes: '' })) } as SlideDeck),
    );
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(0);
    pressKey('n');
    expect(screen.getByTestId('presenter-notes-drawer')).toHaveTextContent('No speaker notes for this slide.');
  });

  // Sabotage target: render the panel in the page flow below the previews (the old bottom drawer),
  // or pin it to the whole page instead of the Up next column.
  it('the Notes panel overlays only the Up next column, above the bottom bar', async () => {
    const slides = slidesWindow();
    const { container } = await renderPresenter();
    slides.state(1);

    const footer = container.querySelector('footer')!;
    const onScreen = iframeByTitle('On screen now')!.closest('figure')!;
    const upNext = iframeByTitle('Up next')!.closest('figure')!;
    const previews = onScreen.parentElement!;
    expect(upNext.parentElement).toBe(previews);
    const onScreenBefore = onScreen.outerHTML;
    const upNextBefore = upNext.outerHTML;

    pressKey('n');
    const panel = screen.getByTestId('presenter-notes-drawer');

    // Positioned over the previews row, not in the flow: it shares the previews box with Up next,
    // and that box is its positioning box.
    expect(panel.parentElement).toBe(previews);
    expect(getComputedStyle(previews).position).toBe('relative');
    const style = getComputedStyle(panel);
    expect(style.position).toBe('absolute');
    expect(style.top).toBe('0px');
    expect(style.right).toBe('0px');
    expect(style.bottom).toBe('0px');
    // Its left edge is Up next's: half the row plus half the 24px column gap.
    expect(style.left.replace(/\s+/g, '')).toBe('calc(50%+12px)');
    expect(getComputedStyle(previews).columnGap || getComputedStyle(previews).gap).toMatch(/^24px/);
    expect(panel.contains(footer)).toBe(false);

    // The previews themselves do not change; the panel sits on top of Up next.
    expect(onScreen.outerHTML).toBe(onScreenBefore);
    expect(upNext.outerHTML).toBe(upNextBefore);
  });

  // Sabotage target: narrow or move the top section when the panel opens.
  it('opening the panel leaves the header, Read aloud and Coming up exactly as they were', async () => {
    const slides = slidesWindow();
    const { container } = await renderPresenter();
    slides.state(1);

    const sectionOf = (label: string) => screen.getByText(label).closest('section')!;
    const top = () =>
      [container.querySelector('main > header')!, sectionOf('Read aloud'), sectionOf('Coming up')].map(
        (el) => el.outerHTML,
      );
    const before = top();

    pressKey('n');
    expect(top()).toEqual(before);
    const panel = screen.getByTestId('presenter-notes-drawer');
    for (const el of [sectionOf('Read aloud'), sectionOf('Coming up')]) expect(panel.contains(el)).toBe(false);

    pressKey('Escape');
    expect(top()).toEqual(before);
  });

  it('on the last slide the panel still opens over the Up next column, beside On screen now', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(2);
    pressKey('n');

    const panel = screen.getByTestId('presenter-notes-drawer');
    expect(drawerOpen()).toBe(true);
    expect(panel).toHaveTextContent('Know 3.');
    expect(panel.parentElement).toBe(iframeByTitle('On screen now')!.closest('figure')!.parentElement);
  });

  // Sabotage target: leave the transform at rest, or drop the reduced-motion opt-out.
  it('the Notes panel slides in from the right with a short transition, and none under reduced motion', async () => {
    const slides = slidesWindow();
    await renderPresenter();
    slides.state(0);

    const panel = screen.getByTestId('presenter-notes-drawer');
    expect(panel.style.transform).toMatch(/translateX\(10[0-9]%\)/);
    expect(panel).toHaveAttribute('aria-hidden', 'true');
    expect(panel.className).toMatch(/\btransition-/);
    expect(panel.className).toMatch(/\bmotion-reduce:transition-none\b/);

    pressKey('n');
    expect(panel.style.transform).toMatch(/^(none|translateX\(0(px|%)?\))$/);
    expect(panel).not.toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByRole('button', { name: 'Show notes' })).toHaveAttribute('aria-pressed', 'true');

    pressKey('Escape');
    expect(panel.style.transform).toMatch(/translateX\(10[0-9]%\)/);
    expect(screen.getByRole('button', { name: 'Show notes' })).toHaveAttribute('aria-pressed', 'false');
  });

  // The author moved link status and "Open presentation" to a later pull request (2026-11-19).
  it('shows no link status and no Open presentation button, before, during or after state messages', async () => {
    const linkStatus = () => screen.queryByText(/slides:\s*(not\s+)?linked/i);
    const openButton = () => screen.queryByRole('button', { name: /open presentation/i });

    const slides = slidesWindow();
    await renderPresenter();
    expect(linkStatus()).toBeNull();
    expect(openButton()).toBeNull();

    slides.state(0);
    expect(linkStatus()).toBeNull();
    expect(openButton()).toBeNull();

    // Long silence: still nothing, and the slide stays put.
    await advance(10_000);
    expect(linkStatus()).toBeNull();
    expect(openButton()).toBeNull();
    expect(screen.getByText('Slide 1 of 3')).toBeInTheDocument();
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

  // Sabotage target: leave the channel open, or the clock pending, when the presenter page goes away.
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
