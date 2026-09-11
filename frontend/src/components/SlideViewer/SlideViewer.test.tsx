/**
 * SlideViewer — unit tests for B1.3's second behaviour change:
 *   unseenSlideIndices and hasUnseen both ignore status === 'fixed'.
 *
 * Without this test the only coverage is the existing E2E "unseen indicator
 * appears then clears" spec, which passes regardless of the fix because f2
 * stays 'open' in that fixture.
 *
 * Sabotage target: the `f.status !== 'fixed' &&` guard in the unseenSlideIndices
 * useMemo at SlideViewer.tsx:201.  Removing it causes the fixed-only case below
 * to go red (ribbon-unseen-0 appears when it should not).
 *
 * Design note: the drawer must start CLOSED.  ViewerBody marks all current-slide
 * findings as seen whenever drawerOpen===true && activeTab==='feedback'.  With the
 * drawer open, even a fixed finding enters `seen` after the first render, which
 * masks the unseenSlideIndices filter and makes both branches look identical.
 * Starting closed prevents the effect from firing — `seen` stays empty — so the
 * filter is the only thing distinguishing fixed from open.
 */
import { render, screen } from '@testing-library/react';
import { SlideViewer } from './SlideViewer';
import { ToastProvider } from '../../contexts/ToastContext';
import { SEEN_STORAGE_KEY } from './seenState';
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

const callbacks: DrawerCallbacks = {
  onApplyFinding: noop,
  onDismissFinding: noop,
  onDiscussFinding: noop,
};

/** Minimal one-slide deck — content_hash undefined so auto-verify skips it. */
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
        slide_id: 'slide-1',
        html: '<div>slide 1</div>',
        scripts: '',
      },
    ],
  };
}

function makeFinding(id: string, status: 'open' | 'fixed'): SlideFinding {
  return {
    id,
    slideIndex: 0,
    category: 'content',
    criterion: 'test',
    message: `Finding ${id}`,
    objective: true,
    status,
    seen: false,
  };
}

/** Start with the feedback drawer CLOSED so the mark-as-seen effect does not
 *  fire.  This is the only way to observe the unseenSlideIndices filter: with
 *  the drawer open, every finding on the current slide is added to `seen`
 *  during the first commit, masking the status guard. */
function startWithDrawerClosed() {
  localStorage.setItem(
    'tellr-viewer-view-state',
    JSON.stringify({ drawerOpen: false, drawerHeight: 180, activeTab: 'feedback' }),
  );
}

function renderViewer(findings: SlideFinding[]) {
  return render(
    <ToastProvider>
      <SlideViewer
        slideDeck={makeDeck()}
        deckKey="test-deck"
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
  // Start every test with the drawer closed so seen-marking is suppressed.
  startWithDrawerClosed();
});

afterEach(() => {
  localStorage.removeItem(SEEN_STORAGE_KEY);
});

// ── tests ─────────────────────────────────────────────────────────────────────

describe('SlideViewer — fixed findings excluded from unseen indicators', () => {
  it('slide with only a fixed unseen finding shows no unseen dot on the ribbon thumbnail', () => {
    renderViewer([makeFinding('fix1', 'fixed')]);

    // ribbon-unseen-0 is rendered only when unseenSlideIndices.has(0).
    // A fixed finding must NOT contribute to unseenSlideIndices.
    expect(screen.queryByTestId('ribbon-unseen-0')).not.toBeInTheDocument();
  });

  it('slide with an open unseen finding DOES show the unseen dot on the ribbon thumbnail', () => {
    renderViewer([makeFinding('open1', 'open')]);

    // An open, unseen finding must be counted (drawer is closed so seen stays empty).
    expect(screen.getByTestId('ribbon-unseen-0')).toBeInTheDocument();
  });

  it('slide with mixed findings: fixed ignored, open still triggers the dot', () => {
    renderViewer([makeFinding('fix2', 'fixed'), makeFinding('open2', 'open')]);

    // At least one open unseen finding → dot appears.
    expect(screen.getByTestId('ribbon-unseen-0')).toBeInTheDocument();
  });
});
