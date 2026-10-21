/**
 * #314 Task 6: the manual "insert a blank slide" affordance (plan D9, AC1, AC5, AC6; corrections C18,
 * C19, C21).
 *
 * What an editor sees and what the server is asked:
 *   - Stage toolbar "New slide" (`stage-insert-slide`) inserts AFTER the current slide:
 *     `api.insertSlide(currentIndex + 1, sessionId)`, then `api.getSlides`, then the REFETCHED deck goes
 *     to `onSlideChange`.
 *   - The ribbon has exactly n + 1 gaps, `ribbon-insert-0 .. ribbon-insert-n`, one before every
 *     thumbnail and one after the last; gap k inserts at k.
 *   - The inserted slide (named by the response's `inserted_slide_id`) becomes the current slide once the
 *     refetched deck has rendered, whatever else the refetch changed (C18). The append case
 *     (`ribbon-insert-3` on three slides) is the one that exposes selecting before the new deck renders:
 *     `setCurrentIndex` clamps to the rendered slide count.
 *   - While a drag is active the gaps stay mounted and laid out but are `invisible pointer-events-none`
 *     (C19: collapsing them at drag start shifts every sortable rect dnd-kit just measured).
 *   - Editors only (AC5): `readOnly`, or no `onSlideChange`, renders neither control. Each absence is
 *     paired with a positive in the same test (C18), because an absence alone is green on today's code.
 *   - `insertDisabled` (AppLayout passes `isGenerating`) disables both controls.
 *   - A 409 / 423 shows the server's own text in a toast and refetches (AC6); anything else shows
 *     "Failed to insert slide". A second click while an insert is in flight sends nothing.
 *   - A refetch superseded by a later deck edit (`deckEditCounterRef` moved on) is dropped AND the
 *     pending selection is cleared (C18), so a later deck holding the inserted slide does not yank the
 *     selection.
 *
 * Harness: the api module is mocked (ApiError stays the real class); `localStorage` is stubbed with
 * `vi.stubGlobal` because local Node 26 has none (the env baseline of SlideViewer.test.tsx); the viewer
 * sits inside a stateful parent that, like AppLayout, re-renders it with whatever deck `onSlideChange`
 * receives. Decks carry no `content_hash`, so auto-verification never fires.
 *
 * Drag driver: dnd-kit's KeyboardSensor. Space on a thumbnail (the sortable activator) starts a drag
 * synchronously (DndContext `onDragStart`); after one macrotask the sensor listens on the document, where
 * Escape cancels (`onDragCancel`) and Space ends (`onDragEnd`). Gap visibility is read from the gap's
 * own wrapper chain (the gap button and its ancestors below the nearest element that also holds a
 * thumbnail), so classes on the gap's InsertGap wrapper count, and classes that would also hide the
 * thumbnails do not.
 *
 * SABOTAGE (each run against a throwaway implementation, then reverted; see the Task 6 report):
 *   - toolbar inserts at `currentIndex` instead of `currentIndex + 1`      -> "toolbar" RED (args).
 *   - the `readOnly` gate removed from the controls                        -> "readOnly" RED.
 *   - gaps numbered from 1                                                 -> gap count/order and
 *                                                                             "ribbon-insert-0" RED.
 *   - gaps unmounted / display:none during a drag                          -> "drag" RED.
 *   - select by `inserted_position` straight after the response (clamp)    -> "append" RED.
 *   - select the first new id (`fresh[0]`) instead of the inserted id      -> "another editor's slide" RED.
 *   - apply the refetch after supersession                                 -> "superseded" RED.
 *   - keep the pending selection after supersession                        -> "superseded" RED.
 * Added by the Task 6 reviewer (each run against the real implementation, then restored):
 *   - the synchronous `insertingRef` guard removed (disabled state kept)   -> "two clicks before React
 *                                                                             re-renders" RED.
 *   - the hover/focus reveal kept on the gap button mid-drag               -> "drag" RED.
 *   - the gap button never revealed (bare `invisible`)                     -> "drag" RED (idle check).
 *   - ViewerProvider's shrink clamp back to `setIndex(slideCount - 1)`     -> "shrank the deck" RED.
 *   - `insertDisabled={isGenerating}` dropped from AppLayout               -> "AppLayout wiring" RED.
 */
import { useState } from 'react';
import type { Mock } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { SlideViewer } from './SlideViewer';
import { ToastProvider } from '../../contexts/ToastContext';
import { api, ApiError } from '../../services/api';
import type { SlideDeck } from '../../types/slide';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';
import appLayoutSource from '../Layout/AppLayout.tsx?raw';

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
const BUSY_DETAIL = 'Something is still running on this deck. Wait for it to finish, then try again.';
const LOCKED_DETAIL = 'Session is locked by Alice Example';
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
  return {
    ...deckOf(ids, 'from-insert-response'),
    inserted_slide_id: insertedId,
    inserted_position: insertedPosition,
  };
}

/** What GET /api/sessions/:id/slides answers. */
function slidesResponse(deck: SlideDeck) {
  return { session_id: SID, slide_deck: deck };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// ── harness ───────────────────────────────────────────────────────────────────

const onSlideChangeSpy = vi.fn();
const onReorder = vi.fn();

interface HarnessProps {
  initial: SlideDeck;
  readOnly?: boolean;
  withOnSlideChange?: boolean;
  insertDisabled?: boolean;
}

/** Like AppLayout: owns the deck, re-renders the viewer with whatever `onSlideChange` receives. */
function Harness({ initial, readOnly = false, withOnSlideChange = true, insertDisabled = false }: HarnessProps) {
  const [deck, setDeck] = useState<SlideDeck>(initial);
  const onSlideChange = (next: SlideDeck) => {
    onSlideChangeSpy(next);
    setDeck(next);
  };
  return (
    <SlideViewer
      slideDeck={deck}
      deckKey={SID}
      findings={NO_FINDINGS}
      callbacks={callbacks}
      onReorder={onReorder}
      onSlideChange={withOnSlideChange ? onSlideChange : undefined}
      readOnly={readOnly}
      sessionId={SID}
      insertDisabled={insertDisabled}
    />
  );
}

function renderHarness(props: HarnessProps) {
  const view = render(
    <ToastProvider>
      <Harness {...props} />
    </ToastProvider>,
  );
  return {
    ...view,
    rerenderHarness: (next: HarnessProps) =>
      view.rerender(
        <ToastProvider>
          <Harness {...next} />
        </ToastProvider>,
      ),
  };
}

// ── queries ───────────────────────────────────────────────────────────────────

const thumb = (i: number) => screen.getByTestId(`ribbon-thumb-${i}`);
const gap = (k: number) => screen.getByTestId(`ribbon-insert-${k}`);
const gaps = () => screen.queryAllByTestId(/^ribbon-insert-\d+$/);
const newSlideButton = () => screen.getByTestId('stage-insert-slide');

function expectCurrent(i: number) {
  expect(thumb(i)).toHaveAttribute('data-current', 'true');
}

/** The gap button plus its ancestors below the nearest element that also contains a thumbnail. */
function gapChain(el: HTMLElement): HTMLElement[] {
  const chain: HTMLElement[] = [];
  let node: HTMLElement | null = el;
  while (node && !node.querySelector('[data-testid^="ribbon-thumb-"]')) {
    chain.push(node);
    node = node.parentElement;
  }
  return chain;
}

const chainHasClass = (el: HTMLElement, cls: string) => gapChain(el).some((n) => n.classList.contains(cls));

/** Hidden for a drag the C19 way: invisible and inert, but mounted and still taking up its space. */
function expectHiddenWithoutReflow(el: HTMLElement) {
  expect(el).toBeInTheDocument();
  expect(chainHasClass(el, 'invisible')).toBe(true);
  expect(chainHasClass(el, 'pointer-events-none')).toBe(true);
  for (const node of gapChain(el)) {
    expect(node.classList.contains('hidden')).toBe(false);
    expect(window.getComputedStyle(node).display).not.toBe('none');
    // The drag state wins over the hover/focus reveal (supervisor ruling): `visibility: visible` on a
    // descendant overrides an `invisible` ancestor, so no reveal variant may sit in the chain mid-drag.
    const reveals = Array.from(node.classList).filter((c) => /(^|:)visible$/.test(c));
    expect(reveals).toEqual([]);
  }
}

/** Usable again: no element of the gap's own chain swallows pointer events. */
function expectInteractive(el: HTMLElement) {
  expect(el).toBeInTheDocument();
  expect(chainHasClass(el, 'pointer-events-none')).toBe(false);
  // Reachable by a pointer: either never hidden, or revealed on hover (D9 "+ on hover").
  const hoverReveal = gapChain(el).some((n) =>
    Array.from(n.classList).some((c) => /hover:/.test(c) && /(visible|opacity)/.test(c)),
  );
  expect(chainHasClass(el, 'invisible') ? hoverReveal : true).toBe(true);
}

/** Let every pending promise callback and zero-delay timer run, inside act. */
async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function toastContainer() {
  return screen.getByTestId('toast-container');
}

// ── setup / teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
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
  onReorder.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── toolbar "New slide" ───────────────────────────────────────────────────────

describe('toolbar "New slide"', () => {
  it('on slide 2 inserts at position 2, refetches, hands the refetched deck up and selects the new slide', async () => {
    const refetched = deckOf(['A', 'B', 'NEW', 'C'], 'from-refetch');
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['A', 'B', 'NEW', 'C'], 'NEW', 2));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(refetched));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    fireEvent.click(thumb(1)); // the user is on slide 2
    expectCurrent(1);
    expect(newSlideButton()).toHaveTextContent('New slide');
    fireEvent.click(newSlideButton());

    await waitFor(() => expect(onSlideChangeSpy).toHaveBeenCalledTimes(1));
    // After the current slide; no html (the server builds the deck's blank shell).
    expect(mockedApi.insertSlide).toHaveBeenCalledTimes(1);
    expect(mockedApi.insertSlide).toHaveBeenCalledWith(2, SID);
    // Then the refetch, and the REFETCHED deck (not the insert response) goes to the parent.
    expect(mockedApi.getSlides).toHaveBeenCalledWith(SID);
    expect(mockedApi.insertSlide.mock.invocationCallOrder[0]).toBeLessThan(
      mockedApi.getSlides.mock.invocationCallOrder[0],
    );
    expect(onSlideChangeSpy.mock.calls[0][0]).toBe(refetched);

    // The inserted slide (NEW, at 2 in the rendered deck) is now current.
    await waitFor(() => expectCurrent(2));
    expect(thumb(1)).toHaveAttribute('data-current', 'false');
  });
});

// ── ribbon gaps ───────────────────────────────────────────────────────────────

describe('ribbon gaps', () => {
  it('renders exactly n + 1 gaps, 0..n, one before every thumbnail and one after the last', () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    const ids = gaps().map((el) => el.getAttribute('data-testid'));
    expect(ids).toHaveLength(4);
    expect([...ids].sort()).toEqual(['ribbon-insert-0', 'ribbon-insert-1', 'ribbon-insert-2', 'ribbon-insert-3']);
    expect(screen.queryByTestId('ribbon-insert-4')).not.toBeInTheDocument();
    // Siblings of the sortable thumbnails, never nested in one (a click would also select that slide).
    gaps().forEach((el) => expect(el.closest('[data-testid^="ribbon-thumb-"]')).toBeNull());

    // Document order: gap0 thumb0 gap1 thumb1 gap2 thumb2 gap3 (gap k sits where slide k will land).
    const sequence = [gap(0), thumb(0), gap(1), thumb(1), gap(2), thumb(2), gap(3)];
    for (let i = 0; i < sequence.length - 1; i += 1) {
      expect(
        sequence[i].compareDocumentPosition(sequence[i + 1]) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it.each([0, 1, 2, 3])('ribbon-insert-%i inserts at its own index', async (k) => {
    const after = ['A', 'B', 'C'];
    after.splice(k, 0, 'NEW');
    mockedApi.insertSlide.mockResolvedValue(insertResponse(after, 'NEW', k));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(after)));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    fireEvent.click(gap(k));

    await waitFor(() => expect(mockedApi.insertSlide).toHaveBeenCalledTimes(1));
    expect(mockedApi.insertSlide).toHaveBeenCalledWith(k, SID);
    await flush();
  });

  it('the append gap selects the appended slide once the new deck has rendered (the clamp case)', async () => {
    const refetched = deckOf(['A', 'B', 'C', 'NEW'], 'from-refetch');
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['A', 'B', 'C', 'NEW'], 'NEW', 3));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(refetched));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    expectCurrent(0);

    fireEvent.click(gap(3));

    await waitFor(() => expect(onSlideChangeSpy).toHaveBeenCalledTimes(1));
    expect(mockedApi.insertSlide).toHaveBeenCalledWith(3, SID);
    expect(onSlideChangeSpy.mock.calls[0][0]).toBe(refetched);
    await waitFor(() => expectCurrent(3));
  });

  it("selects the inserted slide, not another editor's slide that arrived in the same refetch", async () => {
    // Someone else's X landed at 1 meanwhile: NEW is at 3 in the refetch, X is the first unseen id,
    // and NEW's response position (2) now holds B.
    const refetched = deckOf(['A', 'X', 'B', 'NEW', 'C'], 'from-refetch');
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['A', 'X', 'B', 'NEW', 'C'], 'NEW', 2));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(refetched));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    fireEvent.click(gap(2));

    await waitFor(() => expect(onSlideChangeSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expectCurrent(3));
    expect(thumb(1)).toHaveAttribute('data-current', 'false');
    expect(thumb(2)).toHaveAttribute('data-current', 'false');
  });

  it('selects the inserted slide even when the refetch is not pure growth (C18)', async () => {
    // Another editor deleted A meanwhile: same slide count, NEW at 1.
    const refetched = deckOf(['B', 'NEW', 'C'], 'from-refetch');
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['B', 'NEW', 'C'], 'NEW', 2));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(refetched));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    expectCurrent(0);

    fireEvent.click(gap(2));

    await waitFor(() => expect(onSlideChangeSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expectCurrent(1));
  });

  it('selects the inserted slide even when the refetch shrank the deck below the old current index (C18)', async () => {
    // The user is on E (index 4). Meanwhile another editor deleted C, D and E: the refetch holds three
    // slides with NEW at 1. ViewerProvider's shrink clamp must not overwrite the selection with
    // `slideCount - 1` (B) after the pending-selection effect has chosen NEW.
    const refetched = deckOf(['A', 'NEW', 'B'], 'from-refetch');
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['A', 'NEW', 'B'], 'NEW', 1));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(refetched));
    renderHarness({ initial: deckOf(['A', 'B', 'C', 'D', 'E']) });
    fireEvent.click(thumb(4));
    expectCurrent(4);

    fireEvent.click(gap(1));

    await waitFor(() => expect(onSlideChangeSpy).toHaveBeenCalledTimes(1));
    await flush();
    expectCurrent(1);
    expect(thumb(2)).toHaveAttribute('data-current', 'false');
  });

  it('hides every gap during a drag without unmounting or collapsing it, and restores them after (C19)', async () => {
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });
    expect(gaps()).toHaveLength(4);
    const before = [0, 1, 2, 3].map(gap);
    before.forEach(expectInteractive);

    // Drag 1: start (Space on a thumbnail), then cancel (Escape).
    fireEvent.keyDown(thumb(1), { code: 'Space', key: ' ' });
    expect(gaps()).toHaveLength(4);
    for (const k of [0, 1, 2, 3]) {
      const el = gap(k);
      expect(el).toBe(before[k]); // the same node: never unmounted and remounted
      expectHiddenWithoutReflow(el);
    }
    await flush(); // the KeyboardSensor attaches its document listener after a macrotask
    fireEvent.keyDown(document, { code: 'Escape', key: 'Escape' });
    await waitFor(() => gaps().forEach(expectInteractive));
    expect(gaps()).toHaveLength(4);

    // Drag 2: start, then drop (Space again) -> onDragEnd also restores them.
    fireEvent.keyDown(thumb(0), { code: 'Space', key: ' ' });
    [0, 1, 2, 3].forEach((k) => expectHiddenWithoutReflow(gap(k)));
    await flush();
    fireEvent.keyDown(document, { code: 'Space', key: ' ' });
    await waitFor(() => gaps().forEach(expectInteractive));
    expect(gaps()).toHaveLength(4);
  });
});

// ── who sees the controls (AC5) ──────────────────────────────────────────────

describe('editors only', () => {
  it('readOnly renders neither control; the same viewer as an editor renders both', () => {
    const initial = deckOf(['A', 'B', 'C']);
    const { rerenderHarness } = renderHarness({ initial, readOnly: true });

    // The toolbar and the ribbon are there; the insert controls are not.
    expect(screen.getByTestId('stage-toolbar')).toBeInTheDocument();
    expect(thumb(2)).toBeInTheDocument();
    expect(screen.queryByTestId('stage-insert-slide')).not.toBeInTheDocument();
    expect(gaps()).toHaveLength(0);

    rerenderHarness({ initial, readOnly: false });
    expect(newSlideButton()).toBeInTheDocument();
    expect(gaps()).toHaveLength(4);
  });

  it('no onSlideChange renders neither control; with onSlideChange both render', () => {
    const initial = deckOf(['A', 'B', 'C']);
    const { rerenderHarness } = renderHarness({ initial, withOnSlideChange: false });

    expect(screen.getByTestId('stage-toolbar')).toBeInTheDocument();
    expect(thumb(2)).toBeInTheDocument();
    expect(screen.queryByTestId('stage-insert-slide')).not.toBeInTheDocument();
    expect(gaps()).toHaveLength(0);

    rerenderHarness({ initial, withOnSlideChange: true });
    expect(newSlideButton()).toBeInTheDocument();
    expect(gaps()).toHaveLength(4);
  });

  it('insertDisabled disables the toolbar button and every gap; clearing it enables them', async () => {
    const initial = deckOf(['A', 'B', 'C']);
    mockedApi.insertSlide.mockResolvedValue(insertResponse(['A', 'NEW', 'B', 'C'], 'NEW', 1));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(['A', 'NEW', 'B', 'C'])));
    const { rerenderHarness } = renderHarness({ initial, insertDisabled: true });

    expect(newSlideButton()).toBeDisabled();
    expect(gaps()).toHaveLength(4);
    gaps().forEach((el) => expect(el).toBeDisabled());
    fireEvent.click(newSlideButton());
    gaps().forEach((el) => fireEvent.click(el));
    await flush();
    expect(mockedApi.insertSlide).not.toHaveBeenCalled();

    rerenderHarness({ initial, insertDisabled: false });
    expect(newSlideButton()).not.toBeDisabled();
    gaps().forEach((el) => expect(el).not.toBeDisabled());
    fireEvent.click(newSlideButton());
    await waitFor(() => expect(mockedApi.insertSlide).toHaveBeenCalledTimes(1));
    expect(mockedApi.insertSlide).toHaveBeenCalledWith(1, SID);
    await flush();
  });
});

// ── refusals and failures (AC6) ──────────────────────────────────────────────

describe('refusals and failures', () => {
  it.each([
    [409, BUSY_DETAIL],
    [423, LOCKED_DETAIL],
  ])('a %i shows the server text in a toast and refetches the deck', async (status, detail) => {
    const refetched = deckOf(['A', 'B', 'C'], 'from-refetch');
    mockedApi.insertSlide.mockRejectedValue(new ApiError(status, detail));
    mockedApi.getSlides.mockResolvedValue(slidesResponse(refetched));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    fireEvent.click(newSlideButton());

    await waitFor(() => expect(within(toastContainer()).getByText(detail)).toBeInTheDocument());
    expect(within(toastContainer()).queryByText('Failed to insert slide')).not.toBeInTheDocument();
    await waitFor(() => expect(onSlideChangeSpy).toHaveBeenCalledTimes(1));
    expect(mockedApi.getSlides).toHaveBeenCalledWith(SID);
    expect(onSlideChangeSpy.mock.calls[0][0]).toBe(refetched);
  });

  it.each([
    ['a 500 ApiError', () => new ApiError(500, 'psycopg2.OperationalError: server closed the connection')],
    ['a network TypeError', () => new TypeError('Failed to fetch')],
  ])('%s shows "Failed to insert slide", not its own message, and the control works again', async (_label, makeError) => {
    const error = makeError();
    mockedApi.insertSlide.mockRejectedValueOnce(error);
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(['A', 'B', 'C'])));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    fireEvent.click(newSlideButton());

    await waitFor(() =>
      expect(within(toastContainer()).getByText('Failed to insert slide')).toBeInTheDocument(),
    );
    expect(within(toastContainer()).queryByText(error.message)).not.toBeInTheDocument();

    // The in-flight guard is released after a failure.
    mockedApi.insertSlide.mockResolvedValueOnce(insertResponse(['A', 'NEW', 'B', 'C'], 'NEW', 1));
    await waitFor(() => expect(newSlideButton()).not.toBeDisabled());
    fireEvent.click(newSlideButton());
    await waitFor(() => expect(mockedApi.insertSlide).toHaveBeenCalledTimes(2));
    await flush();
  });
});

// ── concurrency ───────────────────────────────────────────────────────────────

describe('in flight and superseded', () => {
  it('a second click while an insert is in flight sends nothing; once it settles, a click sends again', async () => {
    const pending = deferred<ReturnType<typeof insertResponse>>();
    mockedApi.insertSlide.mockReturnValueOnce(pending.promise);
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(['A', 'NEW', 'B', 'C'], 'from-refetch')));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    fireEvent.click(newSlideButton());
    expect(mockedApi.insertSlide).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(newSlideButton()).toBeDisabled());

    fireEvent.click(newSlideButton());
    fireEvent.click(gap(0));
    fireEvent.click(gap(3));
    await flush();
    expect(mockedApi.insertSlide).toHaveBeenCalledTimes(1);

    await act(async () => {
      pending.resolve(insertResponse(['A', 'NEW', 'B', 'C'], 'NEW', 1));
    });
    await waitFor(() => expect(onSlideChangeSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(newSlideButton()).not.toBeDisabled());

    mockedApi.insertSlide.mockResolvedValueOnce(insertResponse(['A', 'NEW', 'B', 'NEW2', 'C'], 'NEW2', 3));
    fireEvent.click(gap(3));
    await waitFor(() => expect(mockedApi.insertSlide).toHaveBeenCalledTimes(2));
    expect(mockedApi.insertSlide).toHaveBeenLastCalledWith(3, SID);
    await flush();
  });

  it('two clicks before React re-renders (the disabled state not painted yet) send one insert', async () => {
    // Both clicks land inside ONE act, so React has not re-rendered between them: the buttons are
    // still enabled in the DOM and only the synchronous in-flight guard can refuse the second.
    const pending = deferred<ReturnType<typeof insertResponse>>();
    mockedApi.insertSlide.mockReturnValueOnce(pending.promise);
    mockedApi.getSlides.mockResolvedValue(slidesResponse(deckOf(['NEW', 'A', 'B', 'C'], 'from-refetch')));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    await act(async () => {
      gap(0).click();
      newSlideButton().click();
      gap(3).click();
    });
    expect(mockedApi.insertSlide).toHaveBeenCalledTimes(1);
    expect(mockedApi.insertSlide).toHaveBeenCalledWith(0, SID);

    await act(async () => {
      pending.resolve(insertResponse(['NEW', 'A', 'B', 'C'], 'NEW', 0));
    });
    await waitFor(() => expect(onSlideChangeSpy).toHaveBeenCalledTimes(1));
    expect(mockedApi.insertSlide).toHaveBeenCalledTimes(1);
  });

  it('a refetch superseded by a later deck edit is dropped and does not take the selection later (C18)', async () => {
    const insertCall = deferred<ReturnType<typeof insertResponse>>();
    const deleteCall = deferred<SlideDeck>();
    const insertRefetch = deckOf(['A', 'NEW', 'B', 'C'], 'insert-refetch');
    const deleteRefetch = deckOf(['A', 'NEW', 'C'], 'delete-refetch');
    mockedApi.insertSlide.mockReturnValueOnce(insertCall.promise);
    mockedApi.deleteSlide.mockReturnValueOnce(deleteCall.promise);
    mockedApi.getSlides
      .mockResolvedValueOnce(slidesResponse(insertRefetch))
      .mockResolvedValueOnce(slidesResponse(deleteRefetch));
    renderHarness({ initial: deckOf(['A', 'B', 'C']) });

    fireEvent.click(thumb(2)); // the user is on slide 3
    expectCurrent(2);

    // 1. Insert before B; the server has not answered yet.
    fireEvent.click(gap(1));
    expect(mockedApi.insertSlide).toHaveBeenCalledWith(1, SID);

    // 2. Meanwhile the user deletes the current slide: a later deck edit.
    fireEvent.click(screen.getByTestId('stage-delete-slide'));
    fireEvent.click(within(screen.getByTestId('confirm-dialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(mockedApi.deleteSlide).toHaveBeenCalledTimes(1));

    // 3. The insert answers; its refetch is now stale and must not reach the parent.
    await act(async () => {
      insertCall.resolve(insertResponse(['A', 'NEW', 'B', 'C'], 'NEW', 1));
    });
    await waitFor(() => expect(mockedApi.getSlides).toHaveBeenCalledTimes(1));
    await flush();
    expect(onSlideChangeSpy).not.toHaveBeenCalled();

    // 4. The delete lands; its deck holds NEW at 1, which must NOT be selected now.
    await act(async () => {
      deleteCall.resolve(deleteRefetch);
    });
    await waitFor(() => expect(onSlideChangeSpy).toHaveBeenCalledTimes(1));
    expect(onSlideChangeSpy.mock.calls[0][0]).toBe(deleteRefetch);
    await flush();
    expectCurrent(2);
    expect(thumb(1)).toHaveAttribute('data-current', 'false');
  });
});

// ── AppLayout wiring (D9: disabled while a turn runs) ─────────────────────────

describe('AppLayout wiring', () => {
  // Read as text, like AppLayoutSpecToggle.test.ts: a jsdom render of AppLayout needs the whole app
  // shell. This pins only the wiring; Task 9's Playwright proves the controls are disabled mid-turn.
  it("passes useGeneration()'s isGenerating to the viewer as insertDisabled", () => {
    const viewers = appLayoutSource.match(/<SlideViewer\b[\s\S]*?\/>/g) ?? [];
    expect(viewers).toHaveLength(1);
    expect(viewers[0]).toMatch(/\binsertDisabled=\{isGenerating\}/);
    expect(appLayoutSource).toMatch(/const \{[^}]*\bisGenerating\b[^}]*\} = useGeneration\(\);/);
  });
});
