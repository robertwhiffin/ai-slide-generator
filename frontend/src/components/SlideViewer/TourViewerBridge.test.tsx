/**
 * App tour bridge — `tour:viewer` window event (plan Task 4).
 *
 * The tour cannot reach ViewerContext (it lives below SlideViewer's empty-state
 * early return), so ViewerBody listens for `tour:viewer` and SETS the current
 * slide index, drawer open state and drawer tab to the values in the payload:
 *   { index?: number; drawerOpen?: boolean; tab?: 'feedback' }
 *
 * Review Focus 5: a user may already have the drawer open (persisted under
 * `tellr-viewer-view-state`). The bridge must set, never toggle. The "already
 * open" test seeds the persisted state as OPEN before dispatching
 * drawerOpen:true, so a toggling implementation closes the drawer and goes red.
 *
 * Seen-state note (see SlideViewer.test.tsx): an open drawer on the feedback tab
 * marks the current slide's findings as seen. That does not affect these
 * assertions — seen findings still render in the drawer body.
 *
 * Drawer visibility: FeedbackDrawer renders `drawer-body` (and the finding rows
 * inside it) only when drawerOpen is true, so presence of `drawer-body` is the
 * open/closed signal.
 */
import { render, screen, act } from '@testing-library/react';
import { SlideViewer } from './SlideViewer';
import { ToastProvider } from '../../contexts/ToastContext';
import { SEEN_STORAGE_KEY } from './seenState';
import type { SlideDeck } from '../../types/slide';
import type { DrawerCallbacks, SlideFinding } from '../../types/finding';

vi.mock('../../services/api', () => ({
  api: {
    getSlides: vi.fn().mockResolvedValue({ slide_deck: null }),
    verifySlide: vi.fn().mockResolvedValue({}),
  },
}));

const VIEW_STATE_KEY = 'tellr-viewer-view-state';

const noop = () => undefined;

const callbacks: DrawerCallbacks = {
  onApplyFinding: noop,
  onDismissFinding: noop,
  onDiscussFinding: noop,
};

// Finding on slide 2 only: it renders in the drawer only when currentIndex === 2
// AND the drawer is open.
const finding: SlideFinding = {
  id: 'brief_not_delivered:abc:0',
  slideIndex: 2,
  category: 'content',
  criterion: 'brief_not_delivered',
  message: 'Demo finding message.',
  objective: false,
  status: 'open',
  seen: false,
};

// Every slide carries a stored verification so useAutoVerification skips them.
const deck: SlideDeck = {
  title: 'Demo',
  css: '',
  external_scripts: [],
  scripts: '',
  slide_count: 3,
  slides: [0, 1, 2].map((i) => ({
    index: i,
    slide_id: `s${i}`,
    html: `<div class="slide">S${i}</div>`,
    scripts: '',
    content_hash: `h${i}`,
    verification: {
      score: 0, rating: 'unknown', explanation: '', issues: [], duration_ms: 0, error: false,
    },
  })),
};

const findings = [finding];

function persistDrawer(open: boolean) {
  localStorage.setItem(
    VIEW_STATE_KEY,
    JSON.stringify({ drawerOpen: open, drawerHeight: 180, activeTab: 'feedback' }),
  );
}

function renderViewer() {
  return render(
    <ToastProvider>
      <SlideViewer
        slideDeck={deck}
        deckKey="demo"
        findings={findings}
        callbacks={callbacks}
        onReorder={noop}
        sessionId="demo-1"
      />
    </ToastProvider>,
  );
}

const fire = (detail: object) =>
  act(() => {
    window.dispatchEvent(new CustomEvent('tour:viewer', { detail }));
  });

const expectCurrent = (index: number) =>
  expect(screen.getByTestId(`ribbon-thumb-${index}`)).toHaveAttribute('data-current', 'true');

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.removeItem(SEEN_STORAGE_KEY);
  vi.restoreAllMocks();
});

describe('SlideViewer — tour:viewer bridge', () => {
  it('tour:viewer selects the slide by index', () => {
    persistDrawer(false);
    renderViewer();
    expectCurrent(0); // precondition: viewer starts on slide 0

    fire({ index: 2 });

    expectCurrent(2);
    expect(screen.getByTestId('ribbon-thumb-0')).toHaveAttribute('data-current', 'false');
  });

  it('an index-only event moves the slide and leaves the drawer state alone', () => {
    persistDrawer(false);
    renderViewer();

    fire({ index: 1 });

    expectCurrent(1);
    // drawerOpen absent from the payload → drawer must stay closed.
    expect(screen.queryByTestId('drawer-body')).not.toBeInTheDocument();
  });

  it('tour:viewer opens the drawer on the feedback tab and shows the slide finding', () => {
    // Start CLOSED so opening is the behaviour under test, not the default.
    persistDrawer(false);
    renderViewer();
    expect(screen.queryByTestId('drawer-body')).not.toBeInTheDocument(); // precondition

    fire({ index: 2, drawerOpen: true, tab: 'feedback' });

    expectCurrent(2);
    expect(screen.getByTestId('drawer-body')).toBeInTheDocument();
    expect(screen.getByTestId('drawer-tab-feedback')).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId(`finding-${finding.id}`)).toBeVisible();
  });

  it('tour:viewer sets drawerOpen=true even when already open (set, not toggle)', () => {
    // Drawer already open from earlier use (persisted view state) — Review Focus 5.
    persistDrawer(true);
    renderViewer();
    expect(screen.getByTestId('drawer-body')).toBeInTheDocument(); // precondition: open

    fire({ index: 2, drawerOpen: true, tab: 'feedback' });

    // A toggling implementation would close the drawer here.
    expect(screen.getByTestId('drawer-body')).toBeInTheDocument();
    expect(screen.getByTestId(`finding-${finding.id}`)).toBeVisible();

    // Re-entry (joyride Back/Next re-runs the step hook) must also leave it open.
    fire({ index: 2, drawerOpen: true, tab: 'feedback' });

    expect(screen.getByTestId('drawer-body')).toBeInTheDocument();
    expect(screen.getByTestId(`finding-${finding.id}`)).toBeVisible();
  });

  it('tour:viewer sets drawerOpen=false (closes an open drawer, keeps a closed one closed)', () => {
    persistDrawer(true);
    renderViewer();
    expect(screen.getByTestId('drawer-body')).toBeInTheDocument(); // precondition: open

    fire({ index: 1, drawerOpen: false });

    expectCurrent(1);
    expect(screen.queryByTestId('drawer-body')).not.toBeInTheDocument();

    fire({ index: 1, drawerOpen: false });

    expect(screen.queryByTestId('drawer-body')).not.toBeInTheDocument();
  });

  it('the listener is removed on unmount', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');

    const { unmount } = renderViewer();

    const added = addSpy.mock.calls.filter(([type]) => type === 'tour:viewer');
    expect(added).toHaveLength(1);
    const handler = added[0][1];

    unmount();

    // The exact handler that was registered must be the one removed.
    const removed = removeSpy.mock.calls.filter(([type]) => type === 'tour:viewer');
    expect(removed.map(([, h]) => h)).toContain(handler);
    expect(() => fire({ index: 1 })).not.toThrow();
  });
});
