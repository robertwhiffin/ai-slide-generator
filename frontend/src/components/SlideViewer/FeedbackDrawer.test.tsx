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

// ── Speaker notes (plan Task 9, D6, D10): an editable Notes tab ─────────────

const NOTES_HINT =
  'Notes you save here are kept when the slide is rebuilt. Chat does not edit notes yet.';
const VIEW_STATE_KEY = 'tellr-viewer-view-state';

interface NotesDrawerProps {
  findings?: SlideFinding[];
  hasUnseen?: boolean;
  speakerNotes?: string;
  slideKey?: string;
  onSaveNotes?: (notes: string) => Promise<void>;
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

const openNotesTab = () => fireEvent.click(screen.getByTestId('drawer-tab-notes'));
const notesInput = () => screen.getByTestId('drawer-notes-input') as HTMLTextAreaElement;
const saveButton = () => screen.getByTestId('drawer-notes-save');

describe('FeedbackDrawer: Notes tab', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    localStorage.clear();
  });

  it('read-only: shows the slide\'s notes as plain text', () => {
    // Sabotage target: render the notes with dangerouslySetInnerHTML.
    const notes = '<b>bold</b>\n\nSecond';
    renderNotesDrawer({ speakerNotes: notes, slideKey: 's1' });
    openNotesTab();

    const body = screen.getByTestId('drawer-notes');
    expect(body.textContent).toBe(notes);
    expect(body.querySelector('b')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-input')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-save')).toBeNull();
  });

  it.each([
    ['empty', ''],
    ['whitespace-only', '  \n\t '],
    ['missing', undefined],
  ])('read-only: shows the empty state when the notes are %s', (_label, speakerNotes) => {
    // Sabotage target: drop the `speakerNotes.trim() !== ''` guard on the read-only branch.
    renderNotesDrawer({ speakerNotes, slideKey: 's1' });
    openNotesTab();

    expect(screen.getByTestId('drawer-notes-empty')).toHaveTextContent('No speaker notes for this slide.');
    expect(screen.queryByTestId('drawer-notes')).toBeNull();
    expect(screen.queryByTestId('drawer-notes-input')).toBeNull();
  });

  it('editable: the editor holds the notes and saves the draft', async () => {
    // Sabotage target: call onSaveNotes(speakerNotes) instead of onSaveNotes(draft).
    const onSaveNotes = vi.fn(async (_notes: string) => {});
    renderNotesDrawer({ speakerNotes: 'Open with the result.', slideKey: 's1', onSaveNotes });
    openNotesTab();

    expect(notesInput().value).toBe('Open with the result.');
    expect(notesInput()).toHaveAccessibleName('Speaker notes');
    expect(notesInput()).toHaveAttribute('placeholder', 'Add speaker notes for this slide.');
    expect(screen.queryByTestId('drawer-notes')).toBeNull();
    // Unchanged draft: nothing to save.
    expect(saveButton()).toBeDisabled();

    const draft = 'Open with the result.\nThen show the chart.';
    fireEvent.change(notesInput(), { target: { value: draft } });
    expect(saveButton()).toBeEnabled();
    expect(saveButton()).toHaveTextContent('Save notes');

    fireEvent.click(saveButton());
    await waitFor(() => expect(onSaveNotes).toHaveBeenCalledTimes(1));
    expect(onSaveNotes).toHaveBeenCalledWith(draft);
  });

  it('editable: Save is disabled while a save is in flight', async () => {
    // Sabotage target: drop the saving flag from the Save button's disabled condition.
    let resolveSave: () => void = () => undefined;
    const onSaveNotes = vi.fn(
      (_notes: string) => new Promise<void>((resolve) => { resolveSave = resolve; }),
    );
    renderNotesDrawer({ speakerNotes: 'A', slideKey: 's1', onSaveNotes });
    openNotesTab();

    fireEvent.change(notesInput(), { target: { value: 'A and B' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(saveButton()).toBeDisabled());
    fireEvent.click(saveButton());
    expect(onSaveNotes).toHaveBeenCalledTimes(1);

    await act(async () => { resolveSave(); });
  });

  it('editable: the hint says saved notes survive a rebuild and chat does not edit notes', () => {
    // Sabotage target: drop the hint, or keep the superseded "Notes are plain text." copy (D10 delta).
    renderNotesDrawer({ speakerNotes: '', slideKey: 's1', onSaveNotes: vi.fn(async () => {}) });
    openNotesTab();

    expect(screen.getByTestId('drawer-notes-hint').textContent).toBe(NOTES_HINT);
    // An editable, empty slide shows the editor, not the read-only empty state.
    expect(notesInput().value).toBe('');
    expect(screen.queryByTestId('drawer-notes-empty')).toBeNull();
  });

  it('editable: a failed save keeps the draft and shows the error', async () => {
    // Sabotage target: reset the draft (or skip the error state) when onSaveNotes rejects.
    const onSaveNotes = vi.fn(async (_notes: string) => {
      throw new Error('boom');
    });
    renderNotesDrawer({ speakerNotes: 'Before.', slideKey: 's1', onSaveNotes });
    openNotesTab();
    expect(screen.queryByTestId('drawer-notes-error')).toBeNull();

    fireEvent.change(notesInput(), { target: { value: 'Before. After.' } });
    fireEvent.click(saveButton());

    expect(await screen.findByTestId('drawer-notes-error')).toHaveTextContent('Could not save the notes.');
    expect(notesInput().value).toBe('Before. After.');
    // The user can retry: the draft still differs and nothing is in flight.
    await waitFor(() => expect(saveButton()).toBeEnabled());
  });

  it('editable: the draft resets when the slide changes', () => {
    // Sabotage target: initialise the draft once (useState(speakerNotes)) with no reset on slideKey/speakerNotes.
    const onSaveNotes = vi.fn(async () => {});
    const { rerender } = renderNotesDrawer({ speakerNotes: 'Slide one notes.', slideKey: 's1', onSaveNotes });
    openNotesTab();
    fireEvent.change(notesInput(), { target: { value: 'Unsaved draft on slide one.' } });

    rerender(notesTree({ speakerNotes: 'Slide two notes.', slideKey: 's2', onSaveNotes }));
    expect(notesInput().value).toBe('Slide two notes.');
    expect(saveButton()).toBeDisabled();
  });

  it('editable: the draft resets on a slide change even when both slides have the same notes', () => {
    // Sabotage target: reset the draft on speakerNotes only, ignoring slideKey.
    const onSaveNotes = vi.fn(async () => {});
    const { rerender } = renderNotesDrawer({ speakerNotes: '', slideKey: 's1', onSaveNotes });
    openNotesTab();
    fireEvent.change(notesInput(), { target: { value: 'Typed on slide one.' } });

    rerender(notesTree({ speakerNotes: '', slideKey: 's2', onSaveNotes }));
    expect(notesInput().value).toBe('');
  });

  it('editable: the draft follows new notes for the same slide (the refreshed deck after a save)', () => {
    // Sabotage target: reset the draft on slideKey only, ignoring speakerNotes.
    const onSaveNotes = vi.fn(async () => {});
    const { rerender } = renderNotesDrawer({ speakerNotes: 'Old.', slideKey: 's1', onSaveNotes });
    openNotesTab();
    expect(notesInput().value).toBe('Old.');

    rerender(notesTree({ speakerNotes: 'New from the server.', slideKey: 's1', onSaveNotes }));
    expect(notesInput().value).toBe('New from the server.');
  });

  it('switching back to AI feedback shows the findings again', () => {
    // Sabotage target: render the findings list regardless of activeTab.
    renderNotesDrawer({
      findings: [openFinding],
      speakerNotes: 'Talk track.',
      slideKey: 's1',
      onSaveNotes: vi.fn(async () => {}),
    });
    expect(screen.getByTestId('drawer-tab-notes')).toHaveTextContent('Notes');
    expect(screen.getByTestId('drawer-tab-notes')).toHaveAttribute('data-active', 'false');
    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();

    openNotesTab();
    expect(screen.getByTestId('drawer-tab-notes')).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId('drawer-tab-feedback')).toHaveAttribute('data-active', 'false');
    expect(screen.queryByTestId('finding-f-open')).toBeNull();
    expect(screen.queryByTestId('drawer-empty')).toBeNull();
    for (const name of ['Apply', 'Dismiss', 'Discuss']) {
      expect(screen.queryByRole('button', { name })).toBeNull();
    }
    expect(notesInput().value).toBe('Talk track.');

    fireEvent.click(screen.getByTestId('drawer-tab-feedback'));
    expect(screen.getByTestId('drawer-tab-feedback')).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();
    expect(screen.queryByTestId('drawer-notes-input')).toBeNull();
  });

  // Sabotage target: drop maxLength from the notes textarea (the route refuses over 20,000 characters).
  it('the notes editor stops at the 20,000-character route limit', () => {
    renderNotesDrawer({ speakerNotes: 'x', slideKey: 's1', onSaveNotes: vi.fn(async () => {}) });
    openNotesTab();
    expect(notesInput().maxLength).toBe(20000);
  });

  it('the unread dot stays on the AI feedback tab', () => {
    // Sabotage target: render the unseen dot inside (or move it to) the Notes tab button.
    renderNotesDrawer({ findings: [openFinding], hasUnseen: true, speakerNotes: 'x', slideKey: 's1' });
    openNotesTab();

    const dot = screen.getByTestId('drawer-tab-unseen');
    expect(screen.getByTestId('drawer-tab-feedback')).toContainElement(dot);
    expect(screen.getByTestId('drawer-tab-notes')).not.toContainElement(dot);
    expect(screen.getAllByTestId('drawer-tab-unseen')).toHaveLength(1);
  });

  it('reopens on Notes when that tab was persisted', () => {
    // Sabotage target: readViewState rejects 'notes' (DRAWER_TABS missing it) or ignores the stored tab.
    localStorage.setItem(
      VIEW_STATE_KEY,
      JSON.stringify({ drawerOpen: true, drawerHeight: 180, activeTab: 'notes' }),
    );
    renderNotesDrawer({ findings: [openFinding], speakerNotes: 'Persisted.', slideKey: 's1' });

    expect(screen.getByTestId('drawer-tab-notes')).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId('drawer-notes')).toHaveTextContent('Persisted.');
    expect(screen.queryByTestId('finding-apply-f-open')).toBeNull();
  });

  it('falls back to AI feedback for an unknown persisted tab', () => {
    // Sabotage target: drop the DRAWER_TABS validation in readViewState.
    localStorage.setItem(
      VIEW_STATE_KEY,
      JSON.stringify({ drawerOpen: true, drawerHeight: 180, activeTab: 'bogus' }),
    );
    renderNotesDrawer({ findings: [openFinding], speakerNotes: 'x', slideKey: 's1' });

    expect(screen.getByTestId('drawer-tab-feedback')).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId('drawer-tab-notes')).toHaveAttribute('data-active', 'false');
    expect(screen.getByTestId('finding-apply-f-open')).toBeInTheDocument();
  });
});
