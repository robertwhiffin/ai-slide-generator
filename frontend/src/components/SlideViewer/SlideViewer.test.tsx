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
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '../../services/api';
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
    // Task 9: the notes-only save, and the HTML save it must never fall back to.
    updateSlideNotes: vi.fn(),
    updateSlide: vi.fn(),
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

// ── tests — SlideViewer.tsx:201 (unseenSlideIndices) ─────────────────────────
//
// Sabotage target: `f.status !== 'fixed' &&` in unseenSlideIndices at :201.
// Removing it causes the fixed-only ribbon test to go red.

describe('SlideViewer — fixed findings excluded from unseenSlideIndices (:201)', () => {
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

// ── tests — SlideViewer.tsx:525 (hasUnseen prop to FeedbackDrawer) ────────────
//
// This is a DISTINCT site from :201.  Removing `f.status !== 'fixed' &&` from
// :525 only leaves all three ribbon tests above GREEN (they drive unseenSlideIndices
// via :201, which is untouched), but makes the tests below RED.  That split is the
// proof that this group covers :525 and not :201 again.
//
// The drawer tab header (including drawer-tab-unseen) is always rendered regardless
// of whether the drawer is open or closed, so startWithDrawerClosed() still works:
// the mark-as-seen effect is suppressed (drawerOpen===false → early return), keeping
// `seen` empty, which is what lets the status filter at :525 be the deciding factor.

describe('SlideViewer — fixed findings excluded from hasUnseen prop (:525)', () => {
  it('current slide with only a fixed unseen finding shows no unseen dot on the drawer tab', () => {
    renderViewer([makeFinding('fix3', 'fixed')]);

    // drawer-tab-unseen appears only when hasUnseen is true.
    // A fixed finding on the current slide must NOT set hasUnseen.
    expect(screen.queryByTestId('drawer-tab-unseen')).not.toBeInTheDocument();
  });

  it('current slide with an open unseen finding DOES show the unseen dot on the drawer tab', () => {
    renderViewer([makeFinding('open3', 'open')]);

    // An open unseen finding on the current slide must set hasUnseen.
    expect(screen.getByTestId('drawer-tab-unseen')).toBeInTheDocument();
  });
});

// ── Presenter plan Task 4: the drawer's two boxes inside the viewer ──────────
//
// The plain renderViewer above is read-only with sessionId={null}. These tests
// need an editable viewer: sessionId "s1", an onSlideChange spy, readOnly false,
// and the drawer persisted OPEN on the Notes tab. Paging uses the window
// keydown listener (SlideViewer.tsx onKeyDown), which skips typing targets, so
// focus must stay off the textareas when a test pages.

/** Two slides with distinct talk tracks and notes; no content_hash, so auto-verify stays idle. */
function makeNotesDeck(
  notes: [string, string] = ['N1', 'N2'],
  talk: [string, string] = ['T1', 'T2'],
): SlideDeck {
  return {
    title: 'Notes Deck',
    slide_count: 2,
    css: '',
    external_scripts: [],
    scripts: '',
    slides: [
      {
        index: 0, slide_id: 'slide-1', html: '<div>slide 1</div>', scripts: '',
        speaker_notes: notes[0], speaker_notes_source: 'model',
        talk_track: talk[0], talk_track_source: 'model',
      },
      {
        index: 1, slide_id: 'slide-2', html: '<div>slide 2</div>', scripts: '',
        speaker_notes: notes[1], speaker_notes_source: 'model',
        talk_track: talk[1], talk_track_source: 'model',
      },
    ],
  };
}

function openOnNotesTab() {
  localStorage.setItem(
    'tellr-viewer-view-state',
    JSON.stringify({ drawerOpen: true, drawerHeight: 180, activeTab: 'notes' }),
  );
}

function renderEditableViewer(deck: SlideDeck, { readOnly = false }: { readOnly?: boolean } = {}) {
  openOnNotesTab();
  const onSlideChange = vi.fn();
  const utils = render(
    <ToastProvider>
      <SlideViewer
        slideDeck={deck}
        deckKey="notes-deck"
        findings={[]}
        callbacks={callbacks}
        onReorder={noop}
        sessionId="s1"
        onSlideChange={onSlideChange}
        readOnly={readOnly}
      />
    </ToastProvider>,
  );
  return { ...utils, onSlideChange };
}

const nextSlide = () => fireEvent.keyDown(window, { key: 'ArrowRight' });
// Each box lives on its own drawer tab, so each getter selects that tab first.
const showTalkTab = () => fireEvent.click(screen.getByTestId('drawer-tab-talk'));
const showNotesTab = () => fireEvent.click(screen.getByTestId('drawer-tab-notes'));
const talkEditor = () => {
  showTalkTab();
  return screen.getByTestId('drawer-talk-input') as HTMLTextAreaElement;
};
const notesEditor = () => {
  showNotesTab();
  return screen.getByTestId('drawer-notes-input') as HTMLTextAreaElement;
};
const clickTalkSave = () => {
  showTalkTab();
  fireEvent.click(screen.getByTestId('drawer-talk-save'));
};
const clickNotesSave = () => {
  showNotesTab();
  fireEvent.click(screen.getByTestId('drawer-notes-save'));
};

/** The second argument of the first api.updateSlideNotes call: the fields object. */
function sentFields(): Record<string, unknown> {
  return vi.mocked(api.updateSlideNotes).mock.calls[0][1] as unknown as Record<string, unknown>;
}

describe('SlideViewer: Talk track and Notes tabs (presenter Task 4)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getSlides).mockResolvedValue({ slide_deck: null } as never);
  });

  it('both boxes follow the current slide', () => {
    // Sabotage target: pass slides[0]'s fields (or a fixed index) instead of currentSlide's.
    renderEditableViewer(makeNotesDeck());
    expect(talkEditor().value).toBe('T1');
    expect(notesEditor().value).toBe('N1');

    nextSlide();
    expect(talkEditor().value).toBe('T2');
    expect(notesEditor().value).toBe('N2');
  });

  it('a draft survives a tab switch on the same slide, and the next slide resets it', () => {
    // Sabotage target: key the drawer (or its drafts) on the active tab, or stop passing slideKey.
    renderEditableViewer(makeNotesDeck());
    fireEvent.change(talkEditor(), { target: { value: 'T1, being edited.' } });
    fireEvent.change(notesEditor(), { target: { value: 'N1, being edited.' } });
    fireEvent.click(screen.getByTestId('drawer-tab-feedback'));
    expect(talkEditor().value).toBe('T1, being edited.');
    expect(notesEditor().value).toBe('N1, being edited.');

    nextSlide();
    expect(notesEditor().value).toBe('N2');
    expect(talkEditor().value).toBe('T2');
  });

  it('a slide with no talk_track value shows an empty talk box', () => {
    // Sabotage target: pass currentSlide.talk_track through unguarded (undefined reaches the textarea).
    const deck = makeNotesDeck();
    delete deck.slides[0].talk_track;
    delete deck.slides[0].talk_track_source;
    renderEditableViewer(deck);
    expect(talkEditor().value).toBe('');
    expect(notesEditor().value).toBe('N1');
  });

  it('saving the talk track sends { talk_track } for the current slide, then refreshes the deck', async () => {
    // Sabotage target: send the notes too, pass a bare string, save through api.updateSlide,
    // or pass index 0 / slides[0].slide_id from a stale closure.
    const refreshed = makeNotesDeck(['N1', 'N2'], ['T1', 'T2, then the chart.']);
    refreshed.slides[1].talk_track_source = 'user';
    vi.mocked(api.updateSlideNotes).mockResolvedValue({
      index: 1, slide_id: 'slide-2', talk_track: 'T2, then the chart.', speaker_notes: 'N2', version: 2,
    } as never);
    vi.mocked(api.getSlides).mockResolvedValue({ slide_deck: refreshed } as never);

    const { onSlideChange } = renderEditableViewer(makeNotesDeck());
    nextSlide();
    expect(talkEditor().value).toBe('T2');

    // A dirty notes draft must not ride along with the talk save.
    fireEvent.change(notesEditor(), { target: { value: 'N2, unsaved.' } });
    fireEvent.change(talkEditor(), { target: { value: 'T2, then the chart.' } });
    clickTalkSave();

    await waitFor(() => expect(onSlideChange).toHaveBeenCalledWith(refreshed));
    const saveMock = vi.mocked(api.updateSlideNotes);
    expect(saveMock).toHaveBeenCalledTimes(1);
    expect(saveMock.mock.calls[0].slice(0, 4)).toEqual([1, { talk_track: 'T2, then the chart.' }, 's1', 'slide-2']);
    expect(Object.keys(sentFields())).toEqual(['talk_track']);
    expect(api.updateSlide).not.toHaveBeenCalled();
    // The refresh follows the save, for the same session.
    expect(api.getSlides).toHaveBeenCalledWith('s1');
    const getSlidesOrder = vi.mocked(api.getSlides).mock.invocationCallOrder;
    expect(Math.max(...getSlidesOrder)).toBeGreaterThan(saveMock.mock.invocationCallOrder[0]);
  });

  it('saving the notes sends { speaker_notes } for the current slide, then refreshes the deck', async () => {
    // Sabotage target: send the talk track too, or keep the old bare-string second argument.
    const refreshed = makeNotesDeck(['N1', 'N2, then the chart.']);
    refreshed.slides[1].speaker_notes_source = 'user';
    vi.mocked(api.updateSlideNotes).mockResolvedValue({
      index: 1, slide_id: 'slide-2', talk_track: 'T2', speaker_notes: 'N2, then the chart.', version: 2,
    } as never);
    vi.mocked(api.getSlides).mockResolvedValue({ slide_deck: refreshed } as never);

    const { onSlideChange } = renderEditableViewer(makeNotesDeck());
    nextSlide();
    expect(notesEditor().value).toBe('N2');

    fireEvent.change(talkEditor(), { target: { value: 'T2, unsaved.' } });
    fireEvent.change(notesEditor(), { target: { value: 'N2, then the chart.' } });
    clickNotesSave();

    await waitFor(() => expect(onSlideChange).toHaveBeenCalledWith(refreshed));
    const saveMock = vi.mocked(api.updateSlideNotes);
    expect(saveMock).toHaveBeenCalledTimes(1);
    expect(saveMock.mock.calls[0].slice(0, 4)).toEqual([1, { speaker_notes: 'N2, then the chart.' }, 's1', 'slide-2']);
    expect(Object.keys(sentFields())).toEqual(['speaker_notes']);
    expect(api.updateSlide).not.toHaveBeenCalled();
    expect(api.getSlides).toHaveBeenCalledWith('s1');
    const getSlidesOrder = vi.mocked(api.getSlides).mock.invocationCallOrder;
    expect(Math.max(...getSlidesOrder)).toBeGreaterThan(saveMock.mock.invocationCallOrder[0]);
  });

  it('a version conflict on a talk-track save alerts, refreshes the deck, and only the talk box shows its error', async () => {
    // Sabotage target: swallow the error in the save handler instead of rethrowing it to the drawer.
    const conflict = Object.assign(new Error('Deck was modified by another user'), { status: 409 });
    vi.mocked(api.updateSlideNotes).mockRejectedValue(conflict);
    const latest = makeNotesDeck(['N1', 'N2'], ['Someone else\'s T1', 'T2']);
    vi.mocked(api.getSlides).mockResolvedValue({ slide_deck: latest } as never);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined);

    try {
      const { onSlideChange } = renderEditableViewer(makeNotesDeck());
      fireEvent.change(talkEditor(), { target: { value: 'T1, edited.' } });
      clickTalkSave();

      expect(await screen.findByTestId('drawer-talk-error')).toBeInTheDocument();
      expect(screen.queryByTestId('drawer-notes-error')).toBeNull();
      expect(vi.mocked(api.updateSlideNotes).mock.calls[0][1]).toEqual({ talk_track: 'T1, edited.' });
      expect(alertSpy).toHaveBeenCalledTimes(1);
      await waitFor(() => expect(onSlideChange).toHaveBeenCalledWith(latest));
      expect(api.updateSlide).not.toHaveBeenCalled();
    } finally {
      alertSpy.mockRestore();
    }
  });

  it('a version conflict on a notes save alerts, refreshes the deck, and the notes box shows its error', async () => {
    // Sabotage target: swallow the error in the save handler instead of rethrowing it to the drawer.
    const conflict = Object.assign(new Error('Deck was modified by another user'), { status: 409 });
    vi.mocked(api.updateSlideNotes).mockRejectedValue(conflict);
    const latest = makeNotesDeck(['Someone else\'s N1', 'N2']);
    vi.mocked(api.getSlides).mockResolvedValue({ slide_deck: latest } as never);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined);

    try {
      const { onSlideChange } = renderEditableViewer(makeNotesDeck());
      fireEvent.change(notesEditor(), { target: { value: 'N1, edited.' } });
      clickNotesSave();

      expect(await screen.findByTestId('drawer-notes-error')).toHaveTextContent('Could not save the notes.');
      expect(screen.queryByTestId('drawer-talk-error')).toBeNull();
      expect(vi.mocked(api.updateSlideNotes).mock.calls[0][1]).toEqual({ speaker_notes: 'N1, edited.' });
      expect(alertSpy).toHaveBeenCalledTimes(1);
      await waitFor(() => expect(onSlideChange).toHaveBeenCalledWith(latest));
      expect(api.updateSlide).not.toHaveBeenCalled();
    } finally {
      alertSpy.mockRestore();
    }
  });

  it('a read-only viewer shows both fields as text and gets no editors', () => {
    // Sabotage target: drop `readOnly ||` from the onSaveNotes gate, or stop passing talkTrack to the drawer.
    renderEditableViewer(makeNotesDeck(), { readOnly: true });

    for (const show of [showTalkTab, showNotesTab]) {
      show();
      expect(document.querySelector('textarea')).toBeNull();
      for (const id of ['drawer-talk-input', 'drawer-talk-save', 'drawer-notes-input', 'drawer-notes-save']) {
        expect(screen.queryByTestId(id)).toBeNull();
      }
    }
    showTalkTab();
    expect(screen.getByTestId('drawer-talk')).toHaveTextContent('T1');
    showNotesTab();
    expect(screen.getByTestId('drawer-notes')).toHaveTextContent('N1');

    nextSlide();
    expect(screen.getByTestId('drawer-notes')).toHaveTextContent('N2');
    showTalkTab();
    expect(screen.getByTestId('drawer-talk')).toHaveTextContent('T2');
  });
});
