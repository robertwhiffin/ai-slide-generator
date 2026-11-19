/**
 * FeedbackDrawer — unit tests for B1.3's behaviour change:
 *   open findings → all three action buttons visible
 *   fixed findings → action buttons suppressed, "Fixed" marker rendered
 *
 * Sabotage target: the `f.status === 'fixed'` branch in FeedbackDrawer.tsx.
 * Replace with `true &&` to see these tests go red.
 *
 * #316 (plan Task 4, D3): each finding leads with its plain-language
 * `plainMessage`; the reviewer's technical `message` sits behind a per-finding
 * "Show details" toggle, collapsed by default and absent from the DOM while
 * collapsed.  Sabotage notes for "plain message and details":
 *  - Render `f.message` in the plain `<p>` (`finding-plain-<id>`) instead of
 *    `findingPlainText(f)` -> test 1 goes red.
 *  - Initialise the expanded set with every finding id
 *    (`useState(() => new Set(findings.map(f => f.id)))`) -> test 2 goes red.
 *  - Keep one shared boolean (or one "expanded id") instead of a per-id set
 *    -> test 3 goes red.
 *  - Render the toggle unconditionally (drop the `message.trim()` guard)
 *    -> test 4 goes red.
 *  - Fall back to `f.message` when `plainMessage` is blank -> test 5 goes red.
 *  - Wire the toggle through a drawer callback -> test 6 goes red.
 *  - Render the toggle only on the open-finding branch -> test 7 goes red.
 *  - Key the expanded set by array index instead of `f.id` -> test 8 goes red.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FeedbackDrawer } from './FeedbackDrawer';
import { ViewerProvider } from '../../contexts/ViewerContext';
import { PLAIN_MESSAGE_FALLBACK, type DrawerCallbacks, type SlideFinding } from '../../types/finding';

const noop = () => undefined;

const callbacks: DrawerCallbacks = {
  onApplyFinding: noop,
  onDismissFinding: noop,
  onDiscussFinding: noop,
};

const openFinding: SlideFinding = {
  id: 'f-open',
  slideIndex: 0,
  category: 'content',
  criterion: 'test-criterion',
  message: 'An open finding',
  plainMessage: "Something here may need a closer look. This was not fixed automatically.",
  plainIssue: "Something here may need a closer look.",
  objective: true,
  status: 'open',
  seen: false,
};

const fixedFinding: SlideFinding = {
  id: 'f-fixed',
  slideIndex: 0,
  category: 'design',
  criterion: 'test-criterion-2',
  message: 'A fixed finding',
  plainMessage: "Something here needed a closer look. This was fixed automatically.",
  plainIssue: "Something here needed a closer look.",
  objective: true,
  status: 'fixed',
  seen: false,
};

function renderDrawer(findings: SlideFinding[], hasUnseen = false, cbs: DrawerCallbacks = callbacks) {
  return render(
    <ViewerProvider slideCount={1}>
      <FeedbackDrawer findings={findings} callbacks={cbs} hasUnseen={hasUnseen} />
    </ViewerProvider>,
  );
}

describe('FeedbackDrawer — status gate', () => {
  it('open finding renders all three action buttons', () => {
    renderDrawer([openFinding]);

    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();
    expect(screen.getByTestId('finding-dismiss-f-open')).toBeInTheDocument();
    expect(screen.getByTestId('finding-discuss-f-open')).toBeInTheDocument();
    expect(screen.queryByTestId('finding-status-f-open')).not.toBeInTheDocument();
  });

  it('fixed finding renders Fixed marker and no action buttons', () => {
    renderDrawer([fixedFinding]);

    expect(screen.queryByTestId('finding-apply-f-fixed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('finding-dismiss-f-fixed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('finding-discuss-f-fixed')).not.toBeInTheDocument();

    const marker = screen.getByTestId('finding-status-f-fixed');
    expect(marker).toBeInTheDocument();
    expect(marker).toHaveTextContent('Fixed');
  });

  it('mixed findings: fixed hides actions, open shows all three', () => {
    renderDrawer([fixedFinding, openFinding]);

    // Fixed finding
    expect(screen.queryByTestId('finding-apply-f-fixed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('finding-dismiss-f-fixed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('finding-discuss-f-fixed')).not.toBeInTheDocument();
    expect(screen.getByTestId('finding-status-f-fixed')).toHaveTextContent('Fixed');

    // Open finding
    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();
    expect(screen.getByTestId('finding-dismiss-f-open')).toBeInTheDocument();
    expect(screen.getByTestId('finding-discuss-f-open')).toBeInTheDocument();
    expect(screen.queryByTestId('finding-status-f-open')).not.toBeInTheDocument();
  });
});

// ── #316: plain message first, the reviewer's technical text on request ─────

/** The technical message quoted in #316, verbatim (hex codes, `≈`, `—`). */
const TECH =
  'The "NOTE" label in the bottom callout is Coral #FF5F46 at 13px/700 over the ' +
  'box fill (rgba(255,95,70,0.12) composited on navy #1B3139 ≈ #2D3A3C), ' +
  'giving roughly 3.9:1 — below the 4.5:1 AA floor for text this size. The ' +
  "template's own dark-background eyebrow colour (#FFC9BF) clears AA; use that " +
  'instead of raw coral.';

/** Plan D8 copy for contrast_failure (objective), as the projection derives it. */
const CONTRAST_OPEN_PLAIN =
  'Some text is hard to read against its background. This was not fixed automatically.';
const CONTRAST_FIXED_PLAIN =
  'Some text was hard to read against its background. This was fixed automatically.';

const contrastOpen: SlideFinding = {
  id: 'f-316',
  slideIndex: 0,
  category: 'design',
  criterion: 'contrast_failure',
  message: TECH,
  plainMessage: CONTRAST_OPEN_PLAIN,
  plainIssue: 'Some text is hard to read against its background.',
  objective: true,
  status: 'open',
  seen: false,
};

const contrastFixed: SlideFinding = {
  ...contrastOpen,
  id: 'f-316-fixed',
  plainMessage: CONTRAST_FIXED_PLAIN,
  plainIssue: 'Some text was hard to read against its background.',
  status: 'fixed',
};

const OVERFLOW_TECH =
  'The .kpi-row grid overflows the 1280x720 frame by 48px at the bottom edge.';

const overflowOpen: SlideFinding = {
  id: 'f-overflow',
  slideIndex: 0,
  category: 'design',
  criterion: 'overflow',
  message: OVERFLOW_TECH,
  plainMessage: 'Some content runs past the edge of the slide. This was not fixed automatically.',
  plainIssue: 'Some content runs past the edge of the slide.',
  objective: true,
  status: 'open',
  seen: false,
};

/** Re-queried on every call: never hold a toggle across a re-render. */
const toggleOf = (id: string) => screen.getByTestId(`finding-details-toggle-${id}`);

describe('FeedbackDrawer — plain message and details', () => {
  // ViewerProvider defaults to drawerOpen: true, so with no persisted view
  // state the drawer body renders without a click.
  beforeEach(() => {
    localStorage.clear();
  });

  it('1. leads with plainMessage and keeps the technical message out of the DOM', () => {
    renderDrawer([contrastOpen]);

    expect(screen.getByTestId('finding-plain-f-316').textContent).toBe(CONTRAST_OPEN_PLAIN);
    expect(screen.queryByText(TECH)).toBeNull();
    expect(screen.queryByTestId('finding-details-f-316')).toBeNull();
    // Absent, not merely hidden and not tucked into an attribute.
    expect(document.body.textContent).not.toContain(TECH);
    expect(document.body.innerHTML).not.toContain('#FF5F46');
  });

  it('2. the toggle starts collapsed, expands to the verbatim technical message, and collapses again', () => {
    renderDrawer([contrastOpen]);

    expect(toggleOf('f-316')).toBe(screen.getByRole('button', { name: 'Show details' }));
    expect(toggleOf('f-316')).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(toggleOf('f-316'));
    expect(toggleOf('f-316')).toHaveAttribute('aria-expanded', 'true');
    expect(toggleOf('f-316')).toHaveAccessibleName('Hide details');
    // Strict: byte-for-byte, not whitespace-normalised.
    expect(screen.getByTestId('finding-details-f-316').textContent).toBe(TECH);
    // The details add to the plain line; they do not replace it.
    expect(screen.getByTestId('finding-plain-f-316').textContent).toBe(CONTRAST_OPEN_PLAIN);

    fireEvent.click(toggleOf('f-316'));
    expect(toggleOf('f-316')).toHaveAttribute('aria-expanded', 'false');
    expect(toggleOf('f-316')).toHaveAccessibleName('Show details');
    expect(screen.queryByTestId('finding-details-f-316')).toBeNull();
    expect(screen.queryByText(TECH)).toBeNull();
  });

  it('3. expanding one finding leaves the others collapsed', () => {
    renderDrawer([contrastOpen, overflowOpen]);

    fireEvent.click(toggleOf('f-316'));
    expect(screen.getByTestId('finding-details-f-316').textContent).toBe(TECH);
    expect(toggleOf('f-overflow')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('finding-details-f-overflow')).toBeNull();
    expect(screen.queryByText(OVERFLOW_TECH)).toBeNull();

    // Independent per finding, not an accordion: opening the second keeps the
    // first open, and closing the first leaves the second open.
    fireEvent.click(toggleOf('f-overflow'));
    expect(screen.getByTestId('finding-details-f-316').textContent).toBe(TECH);
    expect(screen.getByTestId('finding-details-f-overflow').textContent).toBe(OVERFLOW_TECH);

    fireEvent.click(toggleOf('f-316'));
    expect(toggleOf('f-316')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('finding-details-f-316')).toBeNull();
    expect(toggleOf('f-overflow')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('finding-details-f-overflow').textContent).toBe(OVERFLOW_TECH);
  });

  it.each([
    ['whitespace-only', '   '],
    ['empty', ''],
  ])('4. a finding whose technical message is %s renders no toggle', (_label, message) => {
    renderDrawer([{ ...contrastOpen, id: 'f-blank', message }, overflowOpen]);

    expect(screen.getByTestId('finding-plain-f-blank').textContent).toBe(CONTRAST_OPEN_PLAIN);
    expect(screen.queryByTestId('finding-details-toggle-f-blank')).toBeNull();
    expect(screen.queryByTestId('finding-details-f-blank')).toBeNull();
    // Positive control in the same render, so the absence above is not vacuous:
    // the finding with a real message has its toggle, and it is the only one.
    expect(toggleOf('f-overflow')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getAllByRole('button', { name: 'Show details' })).toHaveLength(1);
    // The blank finding keeps its actions.
    expect(screen.getByTestId('finding-apply-f-blank')).toBeInTheDocument();
  });

  it.each([
    ['empty', ''],
    ['whitespace-only', '   '],
    ['missing', undefined],
  ])('5. a plainMessage that is %s shows PLAIN_MESSAGE_FALLBACK, never the technical message', (_label, plainMessage) => {
    renderDrawer([{ ...contrastOpen, plainMessage } as unknown as SlideFinding]);

    expect(screen.getByTestId('finding-plain-f-316').textContent).toBe(PLAIN_MESSAGE_FALLBACK);
    expect(screen.queryByText(TECH)).toBeNull();
    // The details are still one click away.
    expect(toggleOf('f-316')).toHaveAttribute('aria-expanded', 'false');
  });

  it('6. clicking the toggle calls none of the drawer callbacks', () => {
    const spies = {
      onApplyFinding: vi.fn(),
      onDismissFinding: vi.fn(),
      onDiscussFinding: vi.fn(),
    };
    renderDrawer([contrastOpen], false, spies);

    fireEvent.click(toggleOf('f-316'));
    fireEvent.click(toggleOf('f-316'));
    expect(spies.onApplyFinding).not.toHaveBeenCalled();
    expect(spies.onDismissFinding).not.toHaveBeenCalled();
    expect(spies.onDiscussFinding).not.toHaveBeenCalled();

    // Control: the spies really are the drawer's callbacks, so the silence
    // above is not vacuous.
    fireEvent.click(screen.getByTestId('finding-apply-f-316'));
    expect(spies.onApplyFinding).toHaveBeenCalledTimes(1);
    expect(spies.onApplyFinding).toHaveBeenCalledWith('f-316');
  });

  it('7. a fixed finding still shows its plain text, the Fixed badge and a details toggle', () => {
    renderDrawer([contrastFixed]);

    expect(screen.getByTestId('finding-plain-f-316-fixed').textContent).toBe(CONTRAST_FIXED_PLAIN);
    expect(screen.getByTestId('finding-status-f-316-fixed')).toHaveTextContent('Fixed');
    expect(screen.queryByTestId('finding-apply-f-316-fixed')).toBeNull();
    expect(screen.queryByText(TECH)).toBeNull();
    expect(toggleOf('f-316-fixed')).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(toggleOf('f-316-fixed'));
    expect(toggleOf('f-316-fixed')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('finding-details-f-316-fixed').textContent).toBe(TECH);
    expect(screen.getByTestId('finding-status-f-316-fixed')).toHaveTextContent('Fixed');
  });

  it('8. expansion follows the finding id, not its position, when the findings list changes', () => {
    // SlideViewer never remounts the drawer: a dismissal or a slide change only
    // hands it a new `findings` array.  Expansion keyed by array index would
    // then open a different finding's technical text un-asked.
    const tree = (fs: SlideFinding[]) => (
      <ViewerProvider slideCount={1}>
        <FeedbackDrawer findings={fs} callbacks={callbacks} hasUnseen={false} />
      </ViewerProvider>
    );
    const { rerender } = renderDrawer([contrastOpen, overflowOpen]);
    fireEvent.click(toggleOf('f-316'));
    expect(screen.getByTestId('finding-details-f-316').textContent).toBe(TECH);

    // f-316 dismissed: f-overflow moves into its slot and stays collapsed.
    rerender(tree([overflowOpen]));
    expect(toggleOf('f-overflow')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('finding-details-f-overflow')).toBeNull();
    expect(screen.queryByText(OVERFLOW_TECH)).toBeNull();

    // Reordered: f-316 returns in another slot and is still the expanded one.
    rerender(tree([overflowOpen, contrastOpen]));
    expect(toggleOf('f-316')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('finding-details-f-316').textContent).toBe(TECH);
    expect(toggleOf('f-overflow')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('finding-details-f-overflow')).toBeNull();
  });
});

// Final review F2: Apply and Discuss send a chat message, so they wait for a running turn (SlideViewer
// passes `actionsDisabled` while one runs). Dismiss sends nothing and stays.
describe('FeedbackDrawer — while a turn is running', () => {
  it('Apply and Discuss are disabled; Dismiss is not', () => {
    const onApplyFinding = vi.fn();
    const onDiscussFinding = vi.fn();
    const onDismissFinding = vi.fn();
    render(
      <ViewerProvider slideCount={1}>
        <FeedbackDrawer
          findings={[openFinding]}
          callbacks={{ onApplyFinding, onDiscussFinding, onDismissFinding }}
          hasUnseen={false}
          actionsDisabled
        />
      </ViewerProvider>,
    );

    expect(screen.getByTestId('finding-apply-f-open')).toBeDisabled();
    expect(screen.getByTestId('finding-discuss-f-open')).toBeDisabled();
    fireEvent.click(screen.getByTestId('finding-apply-f-open'));
    fireEvent.click(screen.getByTestId('finding-discuss-f-open'));
    expect(onApplyFinding).not.toHaveBeenCalled();
    expect(onDiscussFinding).not.toHaveBeenCalled();

    expect(screen.getByTestId('finding-dismiss-f-open')).toBeEnabled();
    fireEvent.click(screen.getByTestId('finding-dismiss-f-open'));
    expect(onDismissFinding).toHaveBeenCalledWith('f-open');
  });

  it('they are enabled by default', () => {
    renderDrawer([openFinding]);

    expect(screen.getByTestId('finding-apply-f-open')).toBeEnabled();
    expect(screen.getByTestId('finding-discuss-f-open')).toBeEnabled();
  });
});

// ── Talk track and notes (presenter plan Task 4): two tabs, one box each, each saved on its own ──

const NOTES_HINT = 'Chat rewrites the talk track only when it rebuilds the slide.';
const VIEW_STATE_KEY = 'tellr-viewer-view-state';

type PresenterFields = { speaker_notes?: string; talk_track?: string };
type SaveFn = (fields: PresenterFields) => Promise<void>;

interface NotesDrawerProps {
  findings?: SlideFinding[];
  hasUnseen?: boolean;
  speakerNotes?: string;
  talkTrack?: string;
  slideKey?: string;
  onSaveNotes?: SaveFn;
}

function notesTree({ findings = [], hasUnseen = false, ...rest }: NotesDrawerProps = {}) {
  return (
    <ViewerProvider slideCount={2}>
      <FeedbackDrawer findings={findings} callbacks={callbacks} hasUnseen={hasUnseen} {...rest} />
    </ViewerProvider>
  );
}

function renderNotesDrawer(props: NotesDrawerProps = {}) {
  return render(notesTree(props));
}

const openTalkTab = () => fireEvent.click(screen.getByTestId('drawer-tab-talk'));
const openNotesTab = () => fireEvent.click(screen.getByTestId('drawer-tab-notes'));
const openFeedbackTab = () => fireEvent.click(screen.getByTestId('drawer-tab-feedback'));
// Each getter first selects the box's own tab: a box exists only on its tab.
const talkInput = () => {
  openTalkTab();
  return screen.getByTestId('drawer-talk-input') as HTMLTextAreaElement;
};
const talkSave = () => {
  openTalkTab();
  return screen.getByTestId('drawer-talk-save');
};
const notesInput = () => {
  openNotesTab();
  return screen.getByTestId('drawer-notes-input') as HTMLTextAreaElement;
};
const notesSave = () => {
  openNotesTab();
  return screen.getByTestId('drawer-notes-save');
};

/** The single argument of the n-th onSaveNotes call. */
function savedFields(fn: { mock: { calls: unknown[][] } }, call = 0): PresenterFields {
  return fn.mock.calls[call][0] as PresenterFields;
}

const TAB_IDS = ['drawer-tab-feedback', 'drawer-tab-talk', 'drawer-tab-notes'] as const;

function expectActiveTab(active: (typeof TAB_IDS)[number]) {
  for (const id of TAB_IDS) {
    expect(screen.getByTestId(id)).toHaveAttribute('data-active', id === active ? 'true' : 'false');
  }
}

describe('FeedbackDrawer: Talk track and Notes tabs, one box each', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    localStorage.clear();
  });

  // ── The three tabs ──────────────────────────────────────────────────────────

  it('renders three tabs in order: AI feedback, Talk track, Notes', () => {
    // Sabotage target: drop the Talk track tab button, or put it after Notes.
    renderNotesDrawer({ talkTrack: 't', speakerNotes: 'n', slideKey: 's1' });
    const [feedback, talk, notes] = TAB_IDS.map(id => screen.getByTestId(id));
    expect(feedback).toHaveTextContent(/^AI feedback$/);
    expect(talk).toHaveTextContent(/^Talk track$/);
    expect(notes).toHaveTextContent(/^Notes$/);
    expect(feedback.compareDocumentPosition(talk) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(talk.compareDocumentPosition(notes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expectActiveTab('drawer-tab-feedback');

    openTalkTab();
    expectActiveTab('drawer-tab-talk');
    openNotesTab();
    expectActiveTab('drawer-tab-notes');
  });

  // ── Read-only ───────────────────────────────────────────────────────────────

  it('read-only: the Talk track tab shows only the talk track, as plain text, with no editors', () => {
    // Sabotage target: render the talk track with dangerouslySetInnerHTML, or show the notes on the Talk track tab.
    const talk = '<i>Say</i> this.\n\nThen ask the question.';
    const notes = '<b>bold</b>\n\nSecond';
    renderNotesDrawer({ talkTrack: talk, speakerNotes: notes, slideKey: 's1' });
    openTalkTab();

    const talkBody = screen.getByTestId('drawer-talk');
    expect(talkBody.textContent).toBe(talk);
    expect(talkBody.querySelector('i')).toBeNull();
    expect(screen.queryByTestId('drawer-notes')).toBeNull();
    expect(screen.queryByText(/Second/)).toBeNull();
    expect(document.querySelector('textarea')).toBeNull();
    for (const id of ['drawer-talk-input', 'drawer-talk-save', 'drawer-notes-input', 'drawer-notes-save', 'drawer-notes-hint']) {
      expect(screen.queryByTestId(id)).toBeNull();
    }
    expect(screen.queryByTestId('drawer-talk-empty')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-empty')).toBeNull();
  });

  it('read-only: the Notes tab shows only the notes, as plain text, with no editors', () => {
    // Sabotage target: render the notes with dangerouslySetInnerHTML, or show the talk track on the Notes tab.
    const talk = 'Then ask the question.';
    const notes = '<b>bold</b>\n\nSecond';
    renderNotesDrawer({ talkTrack: talk, speakerNotes: notes, slideKey: 's1' });
    openNotesTab();

    const notesBody = screen.getByTestId('drawer-notes');
    expect(notesBody.textContent).toBe(notes);
    expect(notesBody.querySelector('b')).toBeNull();
    expect(screen.queryByTestId('drawer-talk')).toBeNull();
    expect(screen.queryByText(/ask the question/)).toBeNull();
    expect(document.querySelector('textarea')).toBeNull();
    for (const id of ['drawer-talk-input', 'drawer-talk-save', 'drawer-notes-input', 'drawer-notes-save']) {
      expect(screen.queryByTestId(id)).toBeNull();
    }
    expect(screen.queryByTestId('drawer-notes-empty')).toBeNull();
  });

  it.each([
    ['empty', '', ''],
    ['whitespace-only', '  \n\t ', ' \n '],
    ['missing', undefined, undefined],
  ])('read-only: each tab shows its own empty line when both fields are %s', (_label, talkTrack, speakerNotes) => {
    // Sabotage target: drop the trim guard on either tab.
    renderNotesDrawer({ talkTrack, speakerNotes, slideKey: 's1' });

    openTalkTab();
    expect(screen.getByTestId('drawer-talk-empty')).toHaveTextContent('No talk track for this slide.');
    expect(screen.queryByTestId('drawer-talk')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-empty')).toBeNull();

    openNotesTab();
    expect(screen.getByTestId('drawer-notes-empty')).toHaveTextContent('No speaker notes for this slide.');
    expect(screen.queryByTestId('drawer-notes')).toBeNull();
    expect(screen.queryByTestId('drawer-talk-empty')).toBeNull();
    expect(document.querySelector('textarea')).toBeNull();
  });

  it('read-only: a talk track with empty notes fills the Talk track tab and leaves Notes empty', () => {
    // Sabotage target: base the Notes tab's empty line on both fields (talk OR notes).
    renderNotesDrawer({ talkTrack: 'Lead with the result.', speakerNotes: '', slideKey: 's1' });
    openTalkTab();
    expect(screen.getByTestId('drawer-talk')).toHaveTextContent('Lead with the result.');
    expect(screen.queryByTestId('drawer-talk-empty')).toBeNull();

    openNotesTab();
    expect(screen.getByTestId('drawer-notes-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('drawer-notes')).toBeNull();
    expect(screen.queryByTestId('drawer-talk')).toBeNull();
  });

  it('read-only: notes with an empty talk track fill the Notes tab and leave Talk track empty', () => {
    // Sabotage target: base the Talk track tab's empty line on both fields.
    renderNotesDrawer({ talkTrack: '', speakerNotes: 'Source: the 2025 survey.', slideKey: 's1' });
    openNotesTab();
    expect(screen.getByTestId('drawer-notes')).toHaveTextContent('Source: the 2025 survey.');
    expect(screen.queryByTestId('drawer-notes-empty')).toBeNull();

    openTalkTab();
    expect(screen.getByTestId('drawer-talk-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('drawer-talk')).toBeNull();
    expect(screen.queryByTestId('drawer-notes')).toBeNull();
  });

  // ── Editable: each tab holds only its own box ───────────────────────────────

  it('editable: the Talk track tab holds only the talk box, its Save, and the rebuild hint', () => {
    // Sabotage target: render the notes box on the Talk track tab too, swap the props, or drop the hint.
    renderNotesDrawer({
      talkTrack: 'Say the result first.',
      speakerNotes: 'Figure from the Q3 report.',
      slideKey: 's1',
      onSaveNotes: vi.fn<SaveFn>(async () => {}),
    });
    openTalkTab();

    const input = screen.getByTestId('drawer-talk-input') as HTMLTextAreaElement;
    expect(input.value).toBe('Say the result first.');
    expect(screen.getByRole('textbox', { name: /^Talk track/ })).toBe(input);
    expect(screen.getByText('What you say.')).toBeInTheDocument();
    expect(screen.getByTestId('drawer-talk-save')).toHaveTextContent(/^Save talk track$/);
    expect(screen.getByTestId('drawer-notes-hint').textContent).toBe(NOTES_HINT);
    expect(screen.getAllByRole('textbox')).toHaveLength(1);

    expect(screen.queryByTestId('drawer-notes-input')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-save')).toBeNull();
    expect(screen.queryByText('What you need to know.')).toBeNull();
    expect(screen.queryByTestId('drawer-talk')).toBeNull();
    expect(screen.queryByTestId('drawer-talk-empty')).toBeNull();
  });

  it('editable: the Notes tab holds only the notes box and its Save, with no hint', () => {
    // Sabotage target: render the talk box (or the hint) on the Notes tab too, or swap the props.
    renderNotesDrawer({
      talkTrack: 'Say the result first.',
      speakerNotes: 'Figure from the Q3 report.',
      slideKey: 's1',
      onSaveNotes: vi.fn<SaveFn>(async () => {}),
    });
    openNotesTab();

    const input = screen.getByTestId('drawer-notes-input') as HTMLTextAreaElement;
    expect(input.value).toBe('Figure from the Q3 report.');
    expect(screen.getByRole('textbox', { name: /^Notes/ })).toBe(input);
    expect(screen.getByText('What you need to know.')).toBeInTheDocument();
    expect(screen.getByTestId('drawer-notes-save')).toHaveTextContent(/^Save notes$/);
    expect(screen.getAllByRole('textbox')).toHaveLength(1);

    expect(screen.queryByTestId('drawer-talk-input')).toBeNull();
    expect(screen.queryByTestId('drawer-talk-save')).toBeNull();
    expect(screen.queryByText('What you say.')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-hint')).toBeNull();
    expect(screen.queryByTestId('drawer-notes')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-empty')).toBeNull();
  });

  it('editable: an empty slide shows an empty editor on each tab, not the read-only empty line', () => {
    // Sabotage target: test the field text before onSaveNotes, so an empty editable slide gets the empty line.
    renderNotesDrawer({ talkTrack: '', speakerNotes: '', slideKey: 's1', onSaveNotes: vi.fn<SaveFn>(async () => {}) });
    expect(talkInput().value).toBe('');
    expect(screen.queryByTestId('drawer-talk-empty')).toBeNull();
    expect(notesInput().value).toBe('');
    expect(screen.queryByTestId('drawer-notes-empty')).toBeNull();
  });

  // Sabotage target: drop maxLength from either textarea (the route refuses over 20,000 characters).
  it('both editors stop at the 20,000-character route limit', () => {
    renderNotesDrawer({ talkTrack: 'x', speakerNotes: 'y', slideKey: 's1', onSaveNotes: vi.fn<SaveFn>(async () => {}) });
    expect(talkInput().maxLength).toBe(20000);
    expect(notesInput().maxLength).toBe(20000);
  });

  // ── Editable: drafts survive a tab switch ───────────────────────────────────

  it('an unsaved draft on each tab survives switching tabs and back on the same slide', () => {
    // Sabotage target: keep the draft inside the box (it unmounts with its tab), or reset it on a tab change.
    renderNotesDrawer({ talkTrack: 'Saved talk.', speakerNotes: 'Saved notes.', slideKey: 's1', onSaveNotes: vi.fn<SaveFn>(async () => {}) });

    fireEvent.change(talkInput(), { target: { value: 'Talk draft.' } });
    fireEvent.change(notesInput(), { target: { value: 'Notes draft.' } });
    expect(screen.queryByTestId('drawer-talk-input')).toBeNull();

    // Away to AI feedback and back to each tab.
    openFeedbackTab();
    expect(screen.queryByTestId('drawer-talk-input')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-input')).toBeNull();

    expect(talkInput().value).toBe('Talk draft.');
    expect(talkSave()).toBeEnabled();
    expect(notesInput().value).toBe('Notes draft.');
    expect(notesSave()).toBeEnabled();
    expect(talkInput().value).toBe('Talk draft.');
  });

  // ── Editable: dirty state ───────────────────────────────────────────────────

  it('each Save is disabled until its own box is dirty', () => {
    // Sabotage target: one shared dirty check (talk OR notes changed) for both buttons.
    renderNotesDrawer({ talkTrack: 'T', speakerNotes: 'N', slideKey: 's1', onSaveNotes: vi.fn<SaveFn>(async () => {}) });
    expect(talkSave()).toBeDisabled();
    expect(notesSave()).toBeDisabled();

    fireEvent.change(talkInput(), { target: { value: 'T, edited' } });
    expect(talkSave()).toBeEnabled();
    expect(notesSave()).toBeDisabled();

    // Typing back the saved text makes the talk box clean again.
    fireEvent.change(talkInput(), { target: { value: 'T' } });
    expect(talkSave()).toBeDisabled();

    fireEvent.change(notesInput(), { target: { value: 'N, edited' } });
    expect(notesSave()).toBeEnabled();
    expect(talkSave()).toBeDisabled();
  });

  // ── Editable: what each Save sends ──────────────────────────────────────────

  it('saving the talk track sends only talk_track', async () => {
    // Sabotage target: send both keys from the talk Save (the stale notes draft would overwrite a rebuild).
    const onSaveNotes = vi.fn<SaveFn>(async () => {});
    renderNotesDrawer({ talkTrack: 'Old talk.', speakerNotes: 'Old notes.', slideKey: 's1', onSaveNotes });

    // Both boxes are dirty; only the talk box is saved.
    fireEvent.change(notesInput(), { target: { value: 'Unsaved notes draft.' } });
    fireEvent.change(talkInput(), { target: { value: 'New talk.' } });
    fireEvent.click(talkSave());

    await waitFor(() => expect(onSaveNotes).toHaveBeenCalledTimes(1));
    const fields = savedFields(onSaveNotes);
    expect(fields).toEqual({ talk_track: 'New talk.' });
    expect(Object.keys(fields)).toEqual(['talk_track']);
    expect('speaker_notes' in fields).toBe(false);
  });

  it('saving the notes sends only speaker_notes', async () => {
    // Sabotage target: send both keys from the notes Save.
    const onSaveNotes = vi.fn<SaveFn>(async () => {});
    renderNotesDrawer({ talkTrack: 'Old talk.', speakerNotes: 'Old notes.', slideKey: 's1', onSaveNotes });

    fireEvent.change(talkInput(), { target: { value: 'Unsaved talk draft.' } });
    const draft = 'Old notes.\nLikely question: why now?';
    fireEvent.change(notesInput(), { target: { value: draft } });
    fireEvent.click(notesSave());

    await waitFor(() => expect(onSaveNotes).toHaveBeenCalledTimes(1));
    const fields = savedFields(onSaveNotes);
    expect(fields).toEqual({ speaker_notes: draft });
    expect(Object.keys(fields)).toEqual(['speaker_notes']);
    expect('talk_track' in fields).toBe(false);
  });

  it('a save sends the typed draft, not the saved text', async () => {
    // Sabotage target: call onSaveNotes with the talkTrack / speakerNotes props instead of the drafts.
    const onSaveNotes = vi.fn<SaveFn>(async () => {});
    renderNotesDrawer({ talkTrack: 'A', speakerNotes: 'B', slideKey: 's1', onSaveNotes });

    fireEvent.change(talkInput(), { target: { value: 'A2' } });
    fireEvent.click(talkSave());
    await waitFor(() => expect(onSaveNotes).toHaveBeenCalledTimes(1));
    expect(savedFields(onSaveNotes, 0)).toEqual({ talk_track: 'A2' });

    fireEvent.change(notesInput(), { target: { value: 'B2' } });
    fireEvent.click(notesSave());
    await waitFor(() => expect(onSaveNotes).toHaveBeenCalledTimes(2));
    expect(savedFields(onSaveNotes, 1)).toEqual({ speaker_notes: 'B2' });
  });

  // ── Editable: saving state ──────────────────────────────────────────────────

  it('a talk-track save in flight disables only the talk Save, across a tab switch', async () => {
    // Sabotage target: share one `saving` flag across both boxes, or lose it when the tab unmounts.
    let resolveSave: () => void = () => undefined;
    const onSaveNotes = vi.fn<SaveFn>(
      () => new Promise<void>((resolve) => { resolveSave = resolve; }),
    );
    renderNotesDrawer({ talkTrack: 'A', speakerNotes: 'N', slideKey: 's1', onSaveNotes });

    fireEvent.change(talkInput(), { target: { value: 'A and B' } });
    fireEvent.click(talkSave());
    await waitFor(() => expect(talkSave()).toBeDisabled());

    // The notes box is independent: once dirty, it can save while the talk save runs.
    fireEvent.change(notesInput(), { target: { value: 'N, edited' } });
    expect(notesSave()).toBeEnabled();

    // Back on Talk track the save is still in flight; a second click sends nothing more.
    expect(talkSave()).toBeDisabled();
    fireEvent.click(talkSave());
    expect(onSaveNotes).toHaveBeenCalledTimes(1);

    await act(async () => { resolveSave(); });
  });

  it('a notes save in flight disables only the notes Save', async () => {
    // Sabotage target: share one `saving` flag across both boxes.
    let resolveSave: () => void = () => undefined;
    const onSaveNotes = vi.fn<SaveFn>(
      () => new Promise<void>((resolve) => { resolveSave = resolve; }),
    );
    renderNotesDrawer({ talkTrack: 'T', speakerNotes: 'A', slideKey: 's1', onSaveNotes });

    fireEvent.change(notesInput(), { target: { value: 'A and B' } });
    fireEvent.click(notesSave());
    await waitFor(() => expect(notesSave()).toBeDisabled());
    fireEvent.click(notesSave());
    expect(onSaveNotes).toHaveBeenCalledTimes(1);

    fireEvent.change(talkInput(), { target: { value: 'T, edited' } });
    expect(talkSave()).toBeEnabled();

    await act(async () => { resolveSave(); });
  });

  // ── Editable: a failed save ─────────────────────────────────────────────────

  it('a failed talk-track save shows only the talk error and leaves the notes draft untouched', async () => {
    // Sabotage target: one shared failed flag, or one error element, or reset both drafts on failure.
    const onSaveNotes = vi.fn<SaveFn>(async () => {
      throw new Error('boom');
    });
    renderNotesDrawer({ talkTrack: 'Before.', speakerNotes: 'Notes before.', slideKey: 's1', onSaveNotes });

    fireEvent.change(notesInput(), { target: { value: 'Notes draft, unsaved.' } });
    expect(screen.queryByTestId('drawer-notes-error')).toBeNull();
    fireEvent.change(talkInput(), { target: { value: 'Before. After.' } });
    expect(screen.queryByTestId('drawer-talk-error')).toBeNull();
    fireEvent.click(talkSave());

    expect(await screen.findByTestId('drawer-talk-error')).toHaveTextContent('Could not save the talk track.');
    expect(talkInput().value).toBe('Before. After.');
    await waitFor(() => expect(talkSave()).toBeEnabled());

    // The Notes tab shows no error, and its draft survived.
    expect(notesInput().value).toBe('Notes draft, unsaved.');
    expect(screen.queryByTestId('drawer-notes-error')).toBeNull();
    expect(screen.queryByTestId('drawer-talk-error')).toBeNull();
    expect(notesSave()).toBeEnabled();

    // The talk error is still there on the way back.
    openTalkTab();
    expect(screen.getByTestId('drawer-talk-error')).toBeInTheDocument();
  });

  it('a failed notes save shows only the notes error and leaves the talk draft untouched', async () => {
    // Sabotage target: render the talk error from the notes failure flag.
    const onSaveNotes = vi.fn<SaveFn>(async () => {
      throw new Error('boom');
    });
    renderNotesDrawer({ talkTrack: 'Talk before.', speakerNotes: 'Before.', slideKey: 's1', onSaveNotes });

    fireEvent.change(talkInput(), { target: { value: 'Talk draft, unsaved.' } });
    fireEvent.change(notesInput(), { target: { value: 'Before. After.' } });
    fireEvent.click(notesSave());

    expect(await screen.findByTestId('drawer-notes-error')).toHaveTextContent('Could not save the notes.');
    expect(notesInput().value).toBe('Before. After.');
    await waitFor(() => expect(notesSave()).toBeEnabled());

    expect(talkInput().value).toBe('Talk draft, unsaved.');
    expect(screen.queryByTestId('drawer-talk-error')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-error')).toBeNull();
  });

  // ── Editable: drafts reset with the slide ───────────────────────────────────

  it('a slide switch resets both drafts', () => {
    // Sabotage target: initialise the drafts once with no reset on slideKey, or reset only one box.
    const onSaveNotes = vi.fn<SaveFn>(async () => {});
    const { rerender } = renderNotesDrawer({
      talkTrack: 'Slide one talk.', speakerNotes: 'Slide one notes.', slideKey: 's1', onSaveNotes,
    });
    fireEvent.change(talkInput(), { target: { value: 'Unsaved talk on slide one.' } });
    fireEvent.change(notesInput(), { target: { value: 'Unsaved notes on slide one.' } });

    rerender(notesTree({ talkTrack: 'Slide two talk.', speakerNotes: 'Slide two notes.', slideKey: 's2', onSaveNotes }));
    expect(notesInput().value).toBe('Slide two notes.');
    expect(notesSave()).toBeDisabled();
    expect(talkInput().value).toBe('Slide two talk.');
    expect(talkSave()).toBeDisabled();
  });

  it('a slide switch resets both drafts even when both slides have the same text', () => {
    // Sabotage target: reset the drafts on the field values only, ignoring slideKey.
    const onSaveNotes = vi.fn<SaveFn>(async () => {});
    const { rerender } = renderNotesDrawer({ talkTrack: '', speakerNotes: '', slideKey: 's1', onSaveNotes });
    fireEvent.change(talkInput(), { target: { value: 'Typed talk on slide one.' } });
    fireEvent.change(notesInput(), { target: { value: 'Typed notes on slide one.' } });

    rerender(notesTree({ talkTrack: '', speakerNotes: '', slideKey: 's2', onSaveNotes }));
    expect(talkInput().value).toBe('');
    expect(notesInput().value).toBe('');
  });

  it('a slide switch clears a failed save\'s error', async () => {
    // Sabotage target: reset the draft on slideKey but leave the failed flag set.
    const onSaveNotes = vi.fn<SaveFn>(async () => {
      throw new Error('boom');
    });
    const { rerender } = renderNotesDrawer({ talkTrack: 'T1', speakerNotes: 'N1', slideKey: 's1', onSaveNotes });
    fireEvent.change(talkInput(), { target: { value: 'T1, edited' } });
    fireEvent.click(talkSave());
    expect(await screen.findByTestId('drawer-talk-error')).toBeInTheDocument();

    rerender(notesTree({ talkTrack: 'T2', speakerNotes: 'N2', slideKey: 's2', onSaveNotes }));
    expect(screen.queryByTestId('drawer-talk-error')).toBeNull();
  });

  it('each draft follows new text for the same slide (the refreshed deck after a save)', () => {
    // Sabotage target: reset the drafts on slideKey only, ignoring the field values.
    const onSaveNotes = vi.fn<SaveFn>(async () => {});
    const { rerender } = renderNotesDrawer({ talkTrack: 'Old talk.', speakerNotes: 'Old.', slideKey: 's1', onSaveNotes });
    openTalkTab();

    rerender(notesTree({ talkTrack: 'New talk from the server.', speakerNotes: 'Old.', slideKey: 's1', onSaveNotes }));
    expect(talkInput().value).toBe('New talk from the server.');

    rerender(notesTree({ talkTrack: 'New talk from the server.', speakerNotes: 'New from the server.', slideKey: 's1', onSaveNotes }));
    expect(notesInput().value).toBe('New from the server.');
  });

  it('new notes from the server for the same slide leave an unsaved talk draft alone', () => {
    // Sabotage target: one reset effect keyed on both fields (a notes refresh wipes the talk draft).
    const onSaveNotes = vi.fn<SaveFn>(async () => {});
    const { rerender } = renderNotesDrawer({ talkTrack: 'Talk.', speakerNotes: 'Old.', slideKey: 's1', onSaveNotes });
    fireEvent.change(talkInput(), { target: { value: 'Talk, being edited.' } });

    rerender(notesTree({ talkTrack: 'Talk.', speakerNotes: 'Refreshed notes.', slideKey: 's1', onSaveNotes }));
    expect(notesInput().value).toBe('Refreshed notes.');
    expect(talkInput().value).toBe('Talk, being edited.');
    expect(talkSave()).toBeEnabled();
  });

  it('a new talk track from the server for the same slide leaves an unsaved notes draft alone', () => {
    // Sabotage target: one reset effect keyed on both fields (a talk refresh wipes the notes draft).
    const onSaveNotes = vi.fn<SaveFn>(async () => {});
    const { rerender } = renderNotesDrawer({ talkTrack: 'Old talk.', speakerNotes: 'Notes.', slideKey: 's1', onSaveNotes });
    fireEvent.change(notesInput(), { target: { value: 'Notes, being edited.' } });

    rerender(notesTree({ talkTrack: 'Saved talk.', speakerNotes: 'Notes.', slideKey: 's1', onSaveNotes }));
    expect(talkInput().value).toBe('Saved talk.');
    expect(notesInput().value).toBe('Notes, being edited.');
    expect(notesSave()).toBeEnabled();
  });

  // ── Tabs and persistence ────────────────────────────────────────────────────

  it('switching back to AI feedback shows the findings again', () => {
    // Sabotage target: render the findings list regardless of activeTab.
    renderNotesDrawer({
      findings: [openFinding],
      talkTrack: 'Talk track.',
      speakerNotes: 'Notes.',
      slideKey: 's1',
      onSaveNotes: vi.fn<SaveFn>(async () => {}),
    });
    expectActiveTab('drawer-tab-feedback');
    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();

    for (const open of [openTalkTab, openNotesTab]) {
      open();
      expect(screen.queryByTestId('finding-f-open')).toBeNull();
      expect(screen.queryByTestId('drawer-empty')).toBeNull();
      for (const name of ['Apply', 'Dismiss', 'Discuss']) {
        expect(screen.queryByRole('button', { name })).toBeNull();
      }
    }
    expect(talkInput().value).toBe('Talk track.');
    expect(notesInput().value).toBe('Notes.');

    openFeedbackTab();
    expectActiveTab('drawer-tab-feedback');
    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();
    expect(screen.queryByTestId('drawer-talk-input')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-input')).toBeNull();
  });

  it('the unread dot stays on the AI feedback tab', () => {
    // Sabotage target: render the unseen dot inside (or move it to) the Talk track or Notes tab button.
    renderNotesDrawer({ findings: [openFinding], hasUnseen: true, talkTrack: 't', speakerNotes: 'x', slideKey: 's1' });
    openTalkTab();

    const dot = screen.getByTestId('drawer-tab-unseen');
    expect(screen.getByTestId('drawer-tab-feedback')).toContainElement(dot);
    expect(screen.getByTestId('drawer-tab-talk')).not.toContainElement(dot);
    expect(screen.getByTestId('drawer-tab-notes')).not.toContainElement(dot);
    expect(screen.getAllByTestId('drawer-tab-unseen')).toHaveLength(1);
  });

  it('choosing Talk track persists it', () => {
    // Sabotage target: map the Talk track click to setActiveTab('notes').
    renderNotesDrawer({ talkTrack: 't', speakerNotes: 'x', slideKey: 's1' });
    openTalkTab();
    expect(JSON.parse(localStorage.getItem(VIEW_STATE_KEY) ?? '{}').activeTab).toBe('talk');
  });

  it('reopens on Talk track when that tab was persisted', () => {
    // Sabotage target: readViewState rejects 'talk' (DRAWER_TABS missing it) or ignores the stored tab.
    localStorage.setItem(
      VIEW_STATE_KEY,
      JSON.stringify({ drawerOpen: true, drawerHeight: 180, activeTab: 'talk' }),
    );
    renderNotesDrawer({ findings: [openFinding], talkTrack: 'Persisted talk.', speakerNotes: 'Persisted.', slideKey: 's1' });

    expectActiveTab('drawer-tab-talk');
    expect(screen.getByTestId('drawer-talk')).toHaveTextContent('Persisted talk.');
    expect(screen.queryByTestId('drawer-notes')).toBeNull();
    expect(screen.queryByTestId('finding-apply-f-open')).toBeNull();
  });

  it('reopens on Notes when that tab was persisted (an older stored value)', () => {
    // Sabotage target: readViewState rejects 'notes' (DRAWER_TABS missing it) or ignores the stored tab.
    localStorage.setItem(
      VIEW_STATE_KEY,
      JSON.stringify({ drawerOpen: true, drawerHeight: 180, activeTab: 'notes' }),
    );
    renderNotesDrawer({ findings: [openFinding], talkTrack: 'Persisted talk.', speakerNotes: 'Persisted.', slideKey: 's1' });

    expectActiveTab('drawer-tab-notes');
    expect(screen.getByTestId('drawer-notes')).toHaveTextContent('Persisted.');
    expect(screen.queryByTestId('drawer-talk')).toBeNull();
    expect(screen.queryByTestId('finding-apply-f-open')).toBeNull();
  });

  it('falls back to AI feedback for an unknown persisted tab', () => {
    // Sabotage target: drop the DRAWER_TABS validation in readViewState.
    localStorage.setItem(
      VIEW_STATE_KEY,
      JSON.stringify({ drawerOpen: true, drawerHeight: 180, activeTab: 'bogus' }),
    );
    renderNotesDrawer({ findings: [openFinding], speakerNotes: 'x', slideKey: 's1' });

    expectActiveTab('drawer-tab-feedback');
    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();
  });
});
