/**
 * E2 — findings drawer wiring tests.
 *
 * Covers:
 *   1. Grain routing: a finding with a deck-level criterion does NOT render in
 *      the FeedbackDrawer even when it carries a real slideIndex.
 *   2. Apply / Dismiss / Discuss button clicks fire the injected callbacks.
 *   3. Dismiss persists to seenState keyed (deckKey, finding.id).
 *   4. §K9 pair:
 *      Half 1 — a finding dismissed on a previous visit (pre-seened) is NOT
 *               re-highlighted as unseen on a subsequent render with the same id
 *               (same criterion + same slide content_hash → unchanged slide).
 *      Half 2 — a finding re-raised after an edit carries a new id
 *               (same criterion + new slide content_hash → edited slide) and
 *               IS highlighted as unseen.
 *
 * Sabotage targets documented inline per test.
 *
 * Design notes (matching SlideViewer.test.tsx):
 *  - Drawer starts CLOSED in every test.  ViewerBody marks current-slide
 *    findings as seen whenever drawerOpen===true && activeTab==='feedback',
 *    which would mask the grain-routing and K9 assertions.
 *  - All test findings sit on slideIndex:0, which is the initial currentIndex.
 *    A non-zero index causes the viewer to start on slide 0 with no findings,
 *    then require a navigation to reach the finding — the remount-hazard: a
 *    remount also resets currentIndex to 0.  Slide-0 findings avoid that trap.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { SlideViewer } from './SlideViewer';
import { ToastProvider } from '../../contexts/ToastContext';
import { markSeen, SEEN_STORAGE_KEY } from './seenState';
import type { SlideDeck } from '../../types/slide';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';

// ── mock the api module so no network calls fire ─────────────────────────────
vi.mock('../../services/api', () => ({
  api: {
    getSlides: vi.fn().mockResolvedValue({ slide_deck: null }),
    verifySlide: vi.fn().mockResolvedValue({}),
  },
}));

// ── helpers ───────────────────────────────────────────────────────────────────

const noop = () => undefined;

function makeCallbacks(overrides: Partial<DrawerCallbacks> = {}): DrawerCallbacks {
  return {
    onApplyFinding: noop,
    onDismissFinding: noop,
    onDiscussFinding: noop,
    ...overrides,
  };
}

/** Minimal one-slide deck — content_hash absent so auto-verify skips it. */
function makeDeck(): SlideDeck {
  return {
    title: 'Test Deck',
    slide_count: 1,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: [
      {
        index: 0,
        slide_id: 'slide-0',
        html: '<div>slide 0</div>',
        scripts: '',
      },
    ],
  };
}

function makeFinding(
  id: string,
  criterion: string,
  status: 'open' | 'fixed' = 'open',
): SlideFinding {
  return {
    id,
    slideIndex: 0,
    category: 'narrative',
    criterion,
    message: `Test finding (${criterion})`,
    objective: false,
    status,
    seen: false,
  };
}

/** Start with the feedback drawer CLOSED so the mark-as-seen effect does not
 *  fire during the test.  Drawer starts open by default (persisted in
 *  localStorage) so we must explicitly set it to closed. */
function startWithDrawerClosed() {
  localStorage.setItem(
    'tellr-viewer-view-state',
    JSON.stringify({ drawerOpen: false, drawerHeight: 180, activeTab: 'feedback' }),
  );
}

/** Start with the feedback drawer OPEN so finding content is rendered
 *  inside the scrollable body (required to assert text/test-ids inside it). */
function startWithDrawerOpen() {
  localStorage.setItem(
    'tellr-viewer-view-state',
    JSON.stringify({ drawerOpen: true, drawerHeight: 180, activeTab: 'feedback' }),
  );
}

function renderViewer(
  findings: SlideFinding[],
  callbacks: DrawerCallbacks = makeCallbacks(),
  deckKey = 'test-deck',
) {
  return render(
    <ToastProvider>
      <SlideViewer
        slideDeck={makeDeck()}
        deckKey={deckKey}
        findings={findings}
        callbacks={callbacks}
        onReorder={noop}
        sessionId={null}
        readOnly
      />
    </ToastProvider>,
  );
}

// ── setup / teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.removeItem(SEEN_STORAGE_KEY);
});

// ── 1. Grain routing: deck-level criterion finding does NOT appear ────────────
//
// Sabotage target: the `!DECK_LEVEL_CRITERIA.has(f.criterion)` guard in
// SlideViewer.tsx's `visible` useMemo.  Remove it and this test goes red
// (the arc_gap finding renders in the drawer).
//
// The test uses a REAL slideIndex (0 = current slide) so that the test
// is NOT a tautology: without the criterion filter, slideIndex === currentIndex
// is true and the finding WOULD pass the filter.

describe('E2 — grain routing', () => {
  it('finding with deck-level criterion (arc_gap) does not render in the drawer', () => {
    startWithDrawerOpen();
    const deckLevelFinding = makeFinding('arc_gap:deck-hash:0', 'arc_gap');

    renderViewer([deckLevelFinding]);

    // The drawer body should be open (we set it open above).
    expect(screen.getByTestId('drawer-body')).toBeInTheDocument();
    // The finding must NOT be rendered.
    expect(screen.queryByTestId('finding-arc_gap:deck-hash:0')).not.toBeInTheDocument();
    // Empty state must appear because no slide-level findings remain.
    expect(screen.getByTestId('drawer-empty')).toBeInTheDocument();
  });

  it('finding with deck-level criterion cross_slide_repetition is also excluded', () => {
    startWithDrawerOpen();
    const deckLevelFinding = makeFinding('cross_slide_repetition:deck-hash:0', 'cross_slide_repetition');

    renderViewer([deckLevelFinding]);

    expect(screen.queryByTestId('finding-cross_slide_repetition:deck-hash:0')).not.toBeInTheDocument();
    expect(screen.getByTestId('drawer-empty')).toBeInTheDocument();
  });

  it('finding with slide-level criterion (rogue_colour) IS rendered in the drawer', () => {
    startWithDrawerOpen();
    const slideLevelFinding: SlideFinding = {
      ...makeFinding('rogue_colour:slide-hash:0', 'rogue_colour'),
      category: 'design',
    };

    renderViewer([slideLevelFinding]);

    // Control: slide-level finding must appear, proving the filter is specific.
    expect(screen.getByTestId('finding-rogue_colour:slide-hash:0')).toBeInTheDocument();
  });
});

// ── 2. Action callbacks are fired when buttons are clicked ───────────────────
//
// Sabotage target: the button onClick bindings in FeedbackDrawer.tsx.
// Remove any of them and the corresponding mock assertion fires.

describe('E2 — action callbacks', () => {
  const openFinding = makeFinding('btn-test-open', 'rogue_colour', 'open');

  beforeEach(() => {
    startWithDrawerOpen();
  });

  it('Apply button fires onApplyFinding with the finding id', () => {
    const onApplyFinding = vi.fn();
    renderViewer([openFinding], makeCallbacks({ onApplyFinding }));

    fireEvent.click(screen.getByTestId('finding-apply-btn-test-open'));
    expect(onApplyFinding).toHaveBeenCalledTimes(1);
    expect(onApplyFinding).toHaveBeenCalledWith('btn-test-open');
  });

  it('Dismiss button fires onDismissFinding with the finding id', () => {
    const onDismissFinding = vi.fn();
    renderViewer([openFinding], makeCallbacks({ onDismissFinding }));

    fireEvent.click(screen.getByTestId('finding-dismiss-btn-test-open'));
    expect(onDismissFinding).toHaveBeenCalledTimes(1);
    expect(onDismissFinding).toHaveBeenCalledWith('btn-test-open');
  });

  it('Discuss button fires onDiscussFinding with the finding id', () => {
    const onDiscussFinding = vi.fn();
    renderViewer([openFinding], makeCallbacks({ onDiscussFinding }));

    fireEvent.click(screen.getByTestId('finding-discuss-btn-test-open'));
    expect(onDiscussFinding).toHaveBeenCalledTimes(1);
    expect(onDiscussFinding).toHaveBeenCalledWith('btn-test-open');
  });
});

// ── 3. Dismiss persists to seenState keyed (deckKey, finding.id) ─────────────
//
// Sabotage target: the `markSeen(deckKey, [findingId])` call in
// SlideViewer.tsx's handleDismiss.  Remove it and the assertion that
// localStorage carries the id goes red.

describe('E2 — dismiss seenState persistence', () => {
  it('clicking Dismiss marks the finding as seen in localStorage', async () => {
    startWithDrawerOpen();
    const finding = makeFinding('dismiss-persist-test', 'rogue_colour', 'open');

    renderViewer([finding], makeCallbacks(), 'persist-deck');

    fireEvent.click(screen.getByTestId('finding-dismiss-dismiss-persist-test'));

    // seenState stores per deck; finding id must be present under this deck key.
    const raw = localStorage.getItem(SEEN_STORAGE_KEY);
    expect(raw).not.toBeNull();
    const store = JSON.parse(raw!);
    expect(store['persist-deck']).toContain('dismiss-persist-test');
  });
});

// ── 4. §K9 pair: (criterion, subject_hash) composite key ────────────────────
//
// The §K9 pair demonstrates that BOTH the criterion AND the slide
// content_hash components of the id are load-bearing:
//
//   Half 1 — same criterion + same hash (unchanged slide) → id is the same →
//             finding already in seenState → NOT shown as unseen.
//
//   Half 2 — same criterion + new hash (edited slide) → id is different →
//             new finding NOT in seenState → shown as unseen.
//
// Sabotage isolation: sabotage half-1 and half-2 separately to confirm the
// right assertion fires each time.  See task-E2-report.md for sabotage results.

describe('E2 — §K9 dismissed-finding re-highlight pair', () => {
  it('K9 half 1: pre-seened id (unchanged slide) is NOT shown as unseen', () => {
    // Pre-populate seenState as if the finding was dismissed on a prior visit.
    // Id format: criterion_name:subject_hash:ordinal (ws4b's three-part rule).
    // Same criterion + SAME hash = same id = slide is unchanged.
    markSeen('k9-deck', ['rogue_colour:hash1:0']);
    startWithDrawerClosed();

    // Render with the SAME id — unchanged slide means same content hash.
    const finding = makeFinding('rogue_colour:hash1:0', 'rogue_colour');

    renderViewer([finding], makeCallbacks(), 'k9-deck');

    // Already seen: the unseen indicators must be absent.
    expect(screen.queryByTestId('ribbon-unseen-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('drawer-tab-unseen')).not.toBeInTheDocument();
  });

  it('K9 half 2: new id (edited slide, new hash) reads as unseen', () => {
    // Seeded seen-state contains the OLD id (hash1 = pre-edit content hash).
    markSeen('k9-deck', ['rogue_colour:hash1:0']);
    startWithDrawerClosed();

    // Render with a NEW id — same criterion but DIFFERENT hash (slide was edited).
    // The hash is the slide content hash, so an edit produces a new hash.
    const finding = makeFinding('rogue_colour:hash2:0', 'rogue_colour');

    renderViewer([finding], makeCallbacks(), 'k9-deck');

    // rogue_colour:hash2:0 is NOT in seenState → finding must be highlighted as unseen.
    expect(screen.getByTestId('ribbon-unseen-0')).toBeInTheDocument();
  });
});
