/**
 * #314 Task 8: the new-slide indicator in the viewer (plan D10, AC10; corrections C18, C20; review m6,
 * m7, n5, n6).
 *
 * What a user sees when slides appear:
 *   - After a deck that only ADDS slides (diffed by slide_id against the last SERVER deck), the first new
 *     slide (deck order) becomes current and is scrolled into view; every new thumbnail carries a "New"
 *     chip (`ribbon-new-${index}`, inside its Thumb, which also gets `data-new="true"`), and an sr-only
 *     `role="status"` line says "Slide N added". All of it clears after NEW_SLIDE_INDICATOR_MS (5000 ms),
 *     measured from the latest growth.
 *   - Mid-turn views (synthetic `build-N` ids, from SSE slide_ready or polling) never flag anything, and
 *     do not move the baseline: the end-of-turn refetch is diffed against the pre-turn deck. Polling's
 *     first poll replaces EVERY position (cursor 0), so this matters most in production (m7).
 *   - A manual insert (Task 6's toolbar) selects the slide it inserted whenever that id is in the deck
 *     (C18), even when another editor's slide arrived first in deck order and even when the refetch is not
 *     pure growth; the chips still mark every new slide.
 *   - A deckKey change (session switch, e.g. to a duplicated session sharing ids, n5) resets the baseline
 *     BEFORE diffing, so it flags nothing, and drops a lingering pending selection.
 *   - The first mount flags nothing. Read-only viewers get the indicator too (n6, kept).
 * Every absence is paired with a positive in the same test (C18): an absence alone is green today.
 *
 * Harness: as SlideInsert.test.tsx (api mocked, ToastProvider, `localStorage` stubbed with vi.stubGlobal:
 * local Node 26 has none). A stateful parent stands in for AppLayout: `deliver(deck, deckKey?)` sets the
 * deck (and key) in ONE state update, as AppLayout's handleSlideReady / refetch / switchSession do (the
 * latter commits sessionId and deck in one batch, SessionContext.switchSession). Fake timers drive the
 * 5 s expiry; promise chains are flushed with microtask turns inside act.
 *
 * SABOTAGE (run against a throwaway implementation in /tmp/issue314-ui-t8, then reverted):
 *   - diff against the previous RENDER's deck (baseline moved by synthetic views)  -> SSE, polling RED.
 *   - synthetic check dropped                                                     -> SSE, polling RED.
 *   - select from the insert handler, before the new deck renders (the clamp)     -> "the clamp without a
 *                                                                                    fallback" RED.
 *   - select during ViewerBody's render instead of in the effect                  -> every selecting test
 *                                                                                    RED (afterEach guard).
 *   - baseline reset AFTER the diff on a deckKey change                           -> "deckKey" RED.
 *   - no deckKey reset at all                                                     -> "deckKey" RED.
 *   - pending selection only on pure growth                                       -> "not pure growth" RED.
 *   - fresh[0] over the pending id                                                -> "another editor" RED.
 *   - no fresh[0] fallback                                                        -> every agent-path test RED.
 *   - pending kept across a deckKey change                                        -> "lingering pending" RED.
 *   - a new timer per growth without clearing the old one                         -> "restarts" RED.
 *   - indicator gated on !readOnly                                                -> "read-only" RED.
 *   - baseline not replaced after a non-growth deck                               -> "replace" RED.
 *   - chip rendered beside the Thumb / no data-new / status not sr-only or 0-based -> RED.
 * Reviewer additions, sabotaged on the REAL implementation:
 *   - no unmount cleanup of the expiry timer                                      -> "outlives" RED.
 *   - an effect cleanup stopping the timer on every deck change (chips stick)     -> "adds nothing" RED.
 *   - any deck inside the window restarting the 5 s                               -> "adds nothing" RED.
 *   - chips kept across a deckKey change                                          -> "chips still up" RED.
 */
import { useState } from 'react';
import type { Mock, MockInstance } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { SlideViewer } from './SlideViewer';
import { ToastProvider } from '../../contexts/ToastContext';
import { api } from '../../services/api';
import type { SlideDeck } from '../../types/slide';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>();
  return {
    ...actual,
    api: {
      getSlides: vi.fn(),
      insertSlide: vi.fn(),
      deleteSlide: vi.fn(),
      verifySlide: vi.fn(),
    },
  };
});

const mockedApi = api as unknown as {
  getSlides: Mock;
  insertSlide: Mock;
  deleteSlide: Mock;
  verifySlide: Mock;
};

// ── environment ───────────────────────────────────────────────────────────────

/** In-memory Storage: local Node 26 exposes no `localStorage` to the jsdom environment. */
class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length() { return this.store.size; }
  clear() { this.store.clear(); }
  getItem(key: string) { return this.store.has(key) ? this.store.get(key)! : null; }
  key(i: number) { return Array.from(this.store.keys())[i] ?? null; }
  removeItem(key: string) { this.store.delete(key); }
  setItem(key: string, value: string) { this.store.set(key, String(value)); }
}

// ── fixtures ──────────────────────────────────────────────────────────────────

const SID = 'sess-314';
const DUP = 'sess-314-duplicate';
const NO_FINDINGS: SlideFinding[] = [];
const noop = () => undefined;
const callbacks: DrawerCallbacks = {
  onApplyFinding: noop,
  onDismissFinding: noop,
  onDiscussFinding: noop,
};

/** A deck whose slides carry the given ids (no content_hash: auto-verify stays out of the way). */
function deckOf(ids: string[], title = 'Deck'): SlideDeck {
  return {
    title,
    slide_count: ids.length,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: ids.map((id, index) => ({
      index,
      slide_id: id,
      html: `<div class="slide"><h1>${id}</h1></div>`,
      scripts: '',
    })),
  };
}

/** What POST /api/slides answers (Task 3, m6): the deck plus the inserted id and landed position. */
function insertResponse(ids: string[], insertedId: string, insertedPosition: number) {
  return { ...deckOf(ids, 'from-insert-response'), inserted_slide_id: insertedId, inserted_position: insertedPosition };
}

const slidesResponse = (deck: SlideDeck) => ({ session_id: SID, slide_deck: deck });

// ── harness ───────────────────────────────────────────────────────────────────

const onSlideChangeSpy = vi.fn();
let push: (deck: SlideDeck, deckKey?: string) => void = () => {
  throw new Error('harness not mounted');
};

interface HarnessProps {
  initial: SlideDeck;
  initialKey?: string;
  readOnly?: boolean;
  withOnSlideChange?: boolean;
  /** false: the parent drops what onSlideChange hands up (setSlideDeckGated rejecting a stale version). */
  acceptDecks?: boolean;
}

/** Like AppLayout: owns the deck and its key, re-renders the viewer with whatever it is given. */
function Harness({
  initial,
  initialKey = SID,
  readOnly = false,
  withOnSlideChange = true,
  acceptDecks = true,
}: HarnessProps) {
  const [view, setView] = useState({ deck: initial, key: initialKey });
  push = (deck, key) => setView((prev) => ({ deck, key: key ?? prev.key }));
  const onSlideChange = (next: SlideDeck) => {
    onSlideChangeSpy(next);
    if (acceptDecks) setView((prev) => ({ ...prev, deck: next }));
  };
  return (
    <SlideViewer
      slideDeck={view.deck}
      deckKey={view.key}
      findings={NO_FINDINGS}
      callbacks={callbacks}
      onReorder={noop}
      onSlideChange={withOnSlideChange ? onSlideChange : undefined}
      readOnly={readOnly}
      sessionId={view.key}
    />
  );
}

function renderHarness(props: HarnessProps) {
  return render(
    <ToastProvider>
      <Harness {...props} />
    </ToastProvider>,
  );
}

/** The parent sets a new deck (and, for a session switch, a new key) in one update. */
function deliver(ids: string[], deckKey?: string) {
  act(() => push(deckOf(ids), deckKey));
}

/** Let promise chains (insert -> refetch -> onSlideChange) and the effects they cause run. */
async function settle() {
  await act(async () => {
    for (let i = 0; i < 20; i += 1) await Promise.resolve();
  });
}

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

// ── queries ───────────────────────────────────────────────────────────────────

const thumb = (i: number) => screen.getByTestId(`ribbon-thumb-${i}`);
const thumbs = () => screen.getAllByTestId(/^ribbon-thumb-\d+$/);
const chipIds = () =>
  screen.queryAllByTestId(/^ribbon-new-\d+$/).map((el) => el.getAttribute('data-testid')).sort();
const status = () => screen.queryByTestId('new-slide-status');
const newSlideButton = () => screen.getByTestId('stage-insert-slide');

function expectCurrent(i: number) {
  expect(thumb(i)).toHaveAttribute('data-current', 'true');
  for (const el of thumbs()) {
    if (el !== thumb(i)) expect(el).toHaveAttribute('data-current', 'false');
  }
}

/** Exactly these thumbnails are marked new: a chip inside the Thumb and data-new="true"; no others. */
function expectNew(...indices: number[]) {
  expect(chipIds()).toEqual(indices.map((i) => `ribbon-new-${i}`).sort());
  thumbs().forEach((el, i) => {
    if (indices.includes(i)) {
      expect(el).toHaveAttribute('data-new', 'true');
      const chip = within(el).getByTestId(`ribbon-new-${i}`);
      expect(chip).toHaveTextContent('New');
    } else {
      expect(el).not.toHaveAttribute('data-new', 'true');
    }
  });
  if (indices.length === 0) expect(status()).toBeNull();
  else expect(status()).not.toBeNull();
}

const scrollIntoView = () => Element.prototype.scrollIntoView as unknown as Mock;

// ── setup / teardown ─────────────────────────────────────────────────────────

// Selecting during ViewerBody's render (instead of in the effect, after the deck renders) is functionally
// invisible here, because ViewerProvider has already re-rendered with the new slide count; React reports
// it as a setState on another component during render. That report is the only signal, so every test
// fails on it.
let consoleError: MockInstance<typeof console.error>;

beforeEach(() => {
  consoleError = vi.spyOn(console, 'error');
  vi.useFakeTimers();
  vi.stubGlobal('localStorage', new MemoryStorage());
  // Drawer closed: keeps the seen-marking effect out of these tests.
  localStorage.setItem(
    'tellr-viewer-view-state',
    JSON.stringify({ drawerOpen: false, drawerHeight: 180, activeTab: 'feedback' }),
  );
  vi.stubGlobal('alert', vi.fn());
  mockedApi.getSlides.mockReset();
  mockedApi.insertSlide.mockReset();
  mockedApi.deleteSlide.mockReset();
  mockedApi.verifySlide.mockReset().mockResolvedValue({});
  onSlideChangeSpy.mockReset();
  scrollIntoView().mockClear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  const renderPhaseUpdates = consoleError.mock.calls
    .map((args) => String(args[0]))
    .filter((message) => message.includes('while rendering a different component'));
  consoleError.mockRestore();
  expect(renderPhaseUpdates, 'the viewer set state during render; select in the effect instead').toEqual([]);
});

// ── the indicator ────────────────────────────────────────────────────────────

describe('the new-slide indicator', () => {
  it('flags nothing on the first mount; a deck adding a slide selects it, chips it, announces it, for 5 s', () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    // First mount: nothing is new.
    expectCurrent(0);
    expectNew();

    scrollIntoView().mockClear();
    deliver(['A', 'B', 'NEW', 'C']);

    expectCurrent(2);
    expectNew(2);
    const line = status()!;
    expect(line).toHaveAttribute('role', 'status');
    expect(line).toHaveClass('sr-only');
    expect(line).toHaveTextContent('Slide 3 added');
    // Selected AND scrolled into view.
    expect(scrollIntoView().mock.contexts).toContain(thumb(2));

    advance(4999);
    expectNew(2);

    advance(1);
    expectNew();
    expect(status()).toBeNull();
    // The selection stays where the indicator put it.
    expectCurrent(2);
  });

  it('several new slides: the first in deck order is selected, every one is chipped', () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    fireEvent.click(thumb(2));
    expectCurrent(2);

    deliver(['A', 'X', 'B', 'Y', 'C']);

    expectCurrent(1);
    expectNew(1, 3);
  });

  it('the 5 s run from the latest growth: a second growth restarts the timer', () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    deliver(['A', 'B', 'N1', 'C']);
    expectNew(2);

    advance(3000);
    deliver(['A', 'B', 'N1', 'C', 'N2']);
    expectCurrent(4);
    expect(chipIds()).toContain('ribbon-new-4');

    // Past the FIRST growth's 5 s: the second growth's chip is still up.
    advance(2500);
    expect(chipIds()).toContain('ribbon-new-4');
    expect(status()).not.toBeNull();

    // 5 s after the second growth: everything is cleared.
    advance(2500);
    expectNew();
  });

  it('a deck that adds nothing during the 5 s (a mid-turn view, a reorder) neither cancels nor extends the expiry', () => {
    // Reviewer addition. Guards an effect cleanup that stops the timer on EVERY deck change: the chips would
    // then never clear after any deck update inside the window (a slide_ready, a reorder, a verification
    // refresh).
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    deliver(['A', 'B', 'NEW', 'C']);
    expectNew(2);

    advance(2000);
    deliver(['A', 'build-1', 'NEW', 'C']); // a mid-turn view: synthetic, nothing new
    expectNew(2);
    advance(1000);
    deliver(['A', 'B', 'NEW', 'C']); // back to the server deck (same ids): nothing new
    expectNew(2);
    deliver(['B', 'A', 'NEW', 'C']); // a reorder: nothing new
    expectNew(2);

    // 5 s after the growth, not after the last deck: everything is cleared.
    advance(1999);
    expectNew(2);
    advance(1);
    expectNew();
    expectCurrent(2);
  });

  it('no expiry timer outlives the viewer: unmounting while chips are up leaves no timer behind', () => {
    // Reviewer addition. React no longer warns about a setState after unmount, so a leaked timer is
    // otherwise invisible; count the pending fake timers instead.
    const view = renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    const idle = vi.getTimerCount();
    deliver(['A', 'B', 'NEW', 'C']);
    expectNew(2);
    // Positive in the same test: the growth did schedule the expiry.
    expect(vi.getTimerCount()).toBe(idle + 1);

    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('a replace (a slide removed and another added) flags nothing; the next pure growth does', () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    fireEvent.click(thumb(2));

    deliver(['A', 'X', 'C']);
    expectNew();
    expectCurrent(2);

    deliver(['A', 'X', 'C', 'Y']);
    expectNew(3);
    expectCurrent(3);
  });
});

// ── mid-turn views (SSE and polling) ─────────────────────────────────────────

describe('mid-turn views never flag, and the refetch is diffed against the pre-turn deck', () => {
  it('SSE shape: [A,B,C] -> [A,build-1,C] -> [A,NEW,B,C] flags only NEW', () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    deliver(['A', 'build-1', 'C']);
    expectNew();
    expectCurrent(0);

    deliver(['A', 'NEW', 'B', 'C']);
    expectNew(1);
    expectCurrent(1);
    expect(status()).toHaveTextContent('Slide 2 added');
  });

  it('polling shape (m7): every position build-N, then a revision replace, then the refetch flags only NEW', () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    // The first poll (cursor 0) releases every position, replacing each slide by index.
    deliver(['build-0', 'build-1', 'build-2']);
    expectNew();
    // A slide_revisions replace, and the fourth position.
    deliver(['build-0', 'build-1', 'build-2', 'build-3']);
    expectNew();
    expectCurrent(0);

    // The end-of-turn refetch.
    deliver(['A', 'NEW', 'B', 'C']);
    expectNew(1);
    expectCurrent(1);
  });
});

// ── deckKey changes (n5) ─────────────────────────────────────────────────────

describe('a deckKey change resets the baseline before diffing (n5)', () => {
  it('switching to a duplicated session with more slides flags nothing; growth there then flags', () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']), initialKey: SID });

    // duplicate_session copies the slide ids: the duplicate holds A, B, C and two more.
    deliver(['A', 'B', 'C', 'D', 'E'], DUP);
    expectNew();
    expectCurrent(0);

    // The new session's deck is the baseline now: a slide added there is flagged.
    deliver(['A', 'B', 'C', 'D', 'E', 'F']);
    expectNew(5);
    expectCurrent(5);
  });

  it('chips still up when the session switches are cleared, even on a duplicate holding the flagged id', () => {
    // Reviewer addition: the switch clears the chips as well as the baseline.
    renderHarness({ initial: deckOf(['A', 'B', 'C']), initialKey: SID });
    deliver(['A', 'B', 'NEW', 'C']);
    expectNew(2);

    advance(1000);
    // duplicate_session copies the slide ids, NEW included.
    deliver(['A', 'B', 'NEW', 'C', 'D'], DUP);
    expectNew();
    advance(10_000);
    expectNew();

    // Positive in the same test: growth in the new session is flagged, for its own full 5 s.
    deliver(['A', 'B', 'NEW', 'C', 'D', 'E']);
    expectNew(5);
    advance(4999);
    expectNew(5);
    advance(1);
    expectNew();
  });

  it('a pending selection left behind by a rejected refetch does not take the selection in another session', async () => {
    // The parent drops the insert's refetch (setSlideDeckGated refusing a stale version), so the pending id
    // is never consumed. A duplicate made afterwards holds that id.
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['A', 'NEW', 'B', 'C'], 'NEW', 1));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(['A', 'NEW', 'B', 'C'])));
    renderHarness({ initial: deckOf(['A', 'B', 'C']), acceptDecks: false });

    fireEvent.click(newSlideButton());
    await settle();
    expect(onSlideChangeSpy).toHaveBeenCalledTimes(1);
    expectCurrent(0);
    expectNew();

    deliver(['A', 'NEW', 'B', 'C', 'D'], DUP);
    expectCurrent(0);
    expectNew();

    // Positive in the same test: the switched-to deck behaves normally.
    deliver(['A', 'NEW', 'B', 'C', 'D', 'E']);
    expectNew(5);
    expectCurrent(5);
  });
});

// ── manual insert (Task 6's toolbar) ─────────────────────────────────────────

describe('a manual insert selects the slide it inserted (m6, C18)', () => {
  it("selects the inserted slide even when another editor's slide arrived first in deck order; both are chipped", async () => {
    // The user is on B; "New slide" inserts at 2. Meanwhile another editor's X landed at 1, so the refetch
    // holds X at 1 (the first new id in deck order) and NEW at 3; the response's position (2) now holds B.
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['A', 'B', 'NEW', 'C'], 'NEW', 2));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(['A', 'X', 'B', 'NEW', 'C'])));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    fireEvent.click(thumb(1));

    fireEvent.click(newSlideButton());
    await settle();

    expect(mockedApi.insertSlide).toHaveBeenCalledWith(2, SID);
    expect(onSlideChangeSpy).toHaveBeenCalledTimes(1);
    expectCurrent(3);
    expectNew(1, 3);
  });

  it('the append case: selected once the grown deck has rendered (the clamp), and chipped', async () => {
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['A', 'B', 'C', 'NEW'], 'NEW', 3));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(['A', 'B', 'C', 'NEW'])));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    fireEvent.click(thumb(2));

    fireEvent.click(newSlideButton());
    await settle();

    expect(mockedApi.insertSlide).toHaveBeenCalledWith(3, SID);
    expectCurrent(3);
    expectNew(3);
    expect(status()).toHaveTextContent('Slide 4 added');
  });

  it('the clamp without a fallback: an append past the old count, in a refetch that is not pure growth', async () => {
    // Another editor replaced A with D meanwhile, so nothing is "new" and no fresh[0] fallback can rescue a
    // selection made too early: only selecting after the 4-slide deck renders reaches index 3 (the old
    // render's setCurrentIndex clamps to 2).
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['A', 'B', 'C', 'NEW'], 'NEW', 3));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(['B', 'C', 'D', 'NEW'])));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    fireEvent.click(thumb(2));

    fireEvent.click(newSlideButton());
    await settle();

    expect(mockedApi.insertSlide).toHaveBeenCalledWith(3, SID);
    expectCurrent(3);
    expectNew();
  });

  it('selects the inserted slide when the refetch is not pure growth, and chips nothing', async () => {
    // Another editor deleted A meanwhile: the refetch is a replace, so nothing is "new", but the slide the
    // user just inserted is still the one selected.
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['B', 'NEW', 'C'], 'NEW', 1));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(['B', 'NEW', 'C'])));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    expectCurrent(0);

    fireEvent.click(newSlideButton());
    await settle();

    expect(mockedApi.insertSlide).toHaveBeenCalledWith(1, SID);
    expectCurrent(1);
    expectNew();
  });
});

// ── who sees it (n6) ─────────────────────────────────────────────────────────

describe('read-only viewers', () => {
  it('get the indicator too: no insert controls, nothing on mount, the added slide selected and chipped', () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']), readOnly: true, withOnSlideChange: false });
    expect(screen.queryByTestId('stage-insert-slide')).not.toBeInTheDocument();
    expectNew();
    expectCurrent(0);

    deliver(['A', 'B', 'C', 'NEW']);
    expectNew(3);
    expectCurrent(3);
    expect(status()).toHaveTextContent('Slide 4 added');
  });
});
