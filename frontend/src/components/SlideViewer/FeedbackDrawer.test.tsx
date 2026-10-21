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
import { fireEvent, render, screen } from '@testing-library/react';
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
