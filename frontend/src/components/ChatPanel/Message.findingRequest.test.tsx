/**
 * Message — the "Reviewer's details" collapse in chat bubbles (#316, plan Task 7,
 * decision D14; corrections C5 and probe (c)).
 *
 * Exactly two shapes collapse, strictly matched and role-bound:
 *   - a USER Apply/Discuss request (frontend/src/utils/findingText.ts writers);
 *   - an ASSISTANT deck-review advisory (src/services/graph/nodes.py
 *     `_advisory_text`, copied verbatim from tests/unit/test_graph_nodes.py::
 *     TestDeckAdvisoryIsPlain's transport test).
 * The plain lead shows; the reviewer's text sits in a closed native <details>
 * (data-testid="message-reviewer-details", summary "Reviewer's details").
 * Everything else renders verbatim.
 *
 * Every content string is a LITERAL; nothing is rebuilt from the module's
 * exports, so a drifted constant goes red here too.
 *
 * How "hidden" and "verbatim" are asserted (C5):
 *   - the closed <details> body stays in the DOM, so hidden is
 *     `expect(body).not.toBeVisible()`, never a `queryByText(...) === null`;
 *   - "verbatim" is the regular branch's content element (the first
 *     `.whitespace-pre-wrap`) having `textContent === content`, byte for byte
 *     (Testing Library's getByText normaliser would hide a mangled newline),
 *     plus no `message-reviewer-details` at all.
 *
 * Sabotage notes (each turns the named tests red):
 *   - Render `message.content` instead of `split.lead` -> the three
 *     "leads with the plain text" tests.
 *   - Render the details always open (or as a plain <div>) -> "closed until
 *     the summary is clicked".
 *   - Parse regardless of role (or swap the two parsers) -> the opposite-role
 *     tests.
 *   - Parse before the HTML / tool branches -> "the HTML, tool and tool-call
 *     branches are untouched".
 *   - Use `text-primary-foreground/80`, an `opacity-*` class, or the muted tone
 *     on the user bubble -> the user-bubble contrast test.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { Message } from './Message';
import type { Message as MessageType, MessageRole } from '../../types/message';

/** The technical message quoted in #316, verbatim. */
const TECH =
  'The "NOTE" label in the bottom callout is Coral #FF5F46 at 13px/700 over the ' +
  'box fill (rgba(255,95,70,0.12) composited on navy #1B3139 ≈ #2D3A3C), ' +
  'giving roughly 3.9:1 — below the 4.5:1 AA floor for text this size. The ' +
  "template's own dark-background eyebrow colour (#FFC9BF) clears AA; use that " +
  'instead of raw coral.';

const SEP = "\n\nReviewer's details:\n";

/** applyFindingRequest / discussFindingRequest for an open contrast_failure on slide 3. */
const APPLY_LEAD = 'Please fix this on slide 3: Some text is hard to read against its background.';
const DISCUSS_LEAD =
  "I'd like to discuss this on slide 3: Some text is hard to read against its background.";
const APPLY = `${APPLY_LEAD}${SEP}${TECH}`;
const DISCUSS = `${DISCUSS_LEAD}${SEP}${TECH}`;

/** nodes._advisory_text for [arc_gap M1, missing_conclusion M2], byte for byte. */
const M1 = 'Slide 4 presents pilot results before slide 2 introduces the pilot.';
const M2 = 'The final slide restates the agenda instead of a recommendation.';
const ADVISORY_LEAD =
  'Deck review found 2 things to look at in how the deck reads as a whole:\n' +
  '- The story has a gap or an unexplained jump between slides.\n' +
  '- The deck has no clear conclusion or call to action.\n' +
  "None of these were changed automatically. Reply here if you'd like any of them addressed.";
const ADVISORY_DETAILS = `- ${M1}\n- ${M2}`;
const ADVISORY = `${ADVISORY_LEAD}${SEP}${ADVISORY_DETAILS}`;

/** Rows stored before #316 keep these shapes (D6); they are never parsed. */
const LEGACY_APPLY = `Please apply this review suggestion for slide 2: ${TECH}`;
const LEGACY_DISCUSS = `I'd like to discuss this review finding for slide 2: ${TECH}`;
const LEGACY_ADVISORY =
  'Deck review found 2 narrative issues:\n' +
  `- arc_gap: ${M1}\n` +
  `- missing_conclusion: ${M2}`;
/** Byte-identical to before #316 (D5); the tour and integration suites pin it. */
const NO_FINDINGS = 'Deck review complete: no narrative issues found across the deck.';
const LEGACY_FAILURE_ADVISORY =
  'The deck is complete, but the deck-level review could not be completed this turn.';
/** #321's deck_review_failed and deck_not_updated(review_skipped=True) notices (user_notices.py). */
const REVIEW_FAILED_NOTICE =
  "The deck is ready, but the review of the deck as a whole couldn't run this time. " +
  'It will run again the next time I build or edit slides.';
const REVIEW_SKIPPED_NOTICE =
  "Your slides were saved, but the deck couldn't be fully updated, so its slide count and " +
  'exports may be out of date, and the review of the deck as a whole was skipped. ' +
  'Both will run again the next time I build or edit slides.';

function renderMessage(role: MessageRole, content: string, extra: Partial<MessageType> = {}) {
  return render(<Message message={{ role, content, timestamp: '', ...extra }} />);
}

/** The regular branch's content element: the first whitespace-preserving block (C5). */
function contentElement(container: HTMLElement): HTMLElement {
  const el = container.querySelector<HTMLElement>('.whitespace-pre-wrap');
  expect(el, 'the regular-branch content element').not.toBeNull();
  return el!;
}

/** The one disclosure, its summary and its body (the child that is not the summary). */
function disclosure() {
  const all = screen.getAllByTestId('message-reviewer-details');
  expect(all).toHaveLength(1);
  const details = all[0] as HTMLDetailsElement;
  expect(details.tagName).toBe('DETAILS');
  const summary = details.querySelector('summary');
  expect(summary, '<summary> inside the disclosure').not.toBeNull();
  const bodies = Array.from(details.children).filter(el => el.tagName !== 'SUMMARY');
  expect(bodies, 'one details body beside the summary').toHaveLength(1);
  return { details, summary: summary as HTMLElement, body: bodies[0] as HTMLElement };
}

function expectVerbatim(container: HTMLElement, content: string) {
  expect(contentElement(container).textContent).toBe(content);
  expect(screen.queryByTestId('message-reviewer-details')).toBeNull();
}

/** Class tokens on an element and all its descendants. */
function classTokens(root: Element): string[] {
  return [root, ...Array.from(root.querySelectorAll('*'))].flatMap(el =>
    (el.getAttribute('class') ?? '').split(/\s+/).filter(Boolean),
  );
}

describe.each<{ name: string; role: MessageRole; content: string; lead: string; details: string }>([
  { name: 'user Apply request', role: 'user', content: APPLY, lead: APPLY_LEAD, details: TECH },
  { name: 'user Discuss request', role: 'user', content: DISCUSS, lead: DISCUSS_LEAD, details: TECH },
  {
    name: 'assistant deck-review advisory',
    role: 'assistant',
    content: ADVISORY,
    lead: ADVISORY_LEAD,
    details: ADVISORY_DETAILS,
  },
])('Message — a $name collapses the reviewer\'s details', ({ role, content, lead, details: tech }) => {
  it('leads with the plain text only', () => {
    const { container } = renderMessage(role, content);
    const leadEl = contentElement(container);
    expect(leadEl.textContent).toBe(lead);
    expect(leadEl).toBeVisible();
  });

  it('keeps the reviewer\'s text in a closed <details> until the summary is clicked', () => {
    renderMessage(role, content);
    const { details, summary, body } = disclosure();

    expect(details.open).toBe(false);
    expect(summary).toBeVisible();
    expect(body).not.toBeVisible();

    fireEvent.click(summary);

    expect(details.open).toBe(true);
    expect(body).toBeVisible();
    expect(body.textContent).toBe(tech);
  });

  it('renders the reviewer\'s text exactly once, inside the details body', () => {
    const { container } = renderMessage(role, content);
    const { body } = disclosure();
    expect(container.textContent?.split(tech).length).toBe(2);
    expect(body.textContent).toBe(tech);
  });

  it('labels the summary "Reviewer\'s details"', () => {
    renderMessage(role, content);
    expect(disclosure().summary.textContent?.trim()).toBe("Reviewer's details");
  });
});

describe('Message — the details tone keeps AA contrast (D14)', () => {
  it.each([
    ['Apply', APPLY],
    ['Discuss', DISCUSS],
  ])('user %s bubble: full-opacity text-primary-foreground, never /80, opacity or muted', (_label, content) => {
    renderMessage('user', content);
    const { details } = disclosure();
    const ownTokens = details.className.split(/\s+/);
    expect(ownTokens).toContain('text-primary-foreground');

    const tokens = classTokens(details);
    // White on primary is 5.2:1; /80 is 3.91:1, below AA at text-xs.
    expect(tokens.filter(t => /^text-primary-foreground\//.test(t))).toEqual([]);
    expect(tokens.filter(t => /(^|:)opacity-/.test(t))).toEqual([]);
    expect(tokens.filter(t => /^text-muted-foreground/.test(t))).toEqual([]);
  });

  it('assistant advisory bubble: text-muted-foreground, never the primary foreground', () => {
    renderMessage('assistant', ADVISORY);
    const { details } = disclosure();
    expect(details.className.split(/\s+/)).toContain('text-muted-foreground');
    expect(classTokens(details).filter(t => /^text-primary-foreground/.test(t))).toEqual([]);
  });
});

describe('Message — the role is part of the match: opposite roles render verbatim', () => {
  it.each<[string, MessageRole, string]>([
    ['the Apply shape from the assistant', 'assistant', APPLY],
    ['the Discuss shape from the assistant', 'assistant', DISCUSS],
    ['the deck-advisory shape from the user', 'user', ADVISORY],
  ])('%s', (_label, role, content) => {
    const { container } = renderMessage(role, content);
    expectVerbatim(container, content);
  });
});

describe('Message — everything else renders verbatim, never parsed (D6, D14, C5)', () => {
  it.each<[string, MessageRole, string]>([
    [
      'an ordinary user message with the exact separator and a non-matching lead',
      'user',
      "Hello there\n\nReviewer's details:\nnot a finding",
    ],
    [
      'an ordinary assistant message with the exact separator',
      'assistant',
      "Here is the plan.\n\nReviewer's details:\nnone",
    ],
    ['a user Apply lead whose details are blank', 'user', `${APPLY_LEAD}${SEP}   `],
    ['a user Apply lead with no details (blank reviewer message)', 'user', APPLY_LEAD],
    ['the legacy Apply request', 'user', LEGACY_APPLY],
    ['the legacy Discuss request', 'user', LEGACY_DISCUSS],
    ['the legacy slug advisory', 'assistant', LEGACY_ADVISORY],
    ['the no-findings advisory', 'assistant', NO_FINDINGS],
    ['the legacy deck-review failure advisory', 'assistant', LEGACY_FAILURE_ADVISORY],
    ['the deck-review-failed notice', 'assistant', REVIEW_FAILED_NOTICE],
    ['the deck-review-skipped notice', 'assistant', REVIEW_SKIPPED_NOTICE],
    ['an ordinary multi-line user message', 'user', 'Line one\n\n  Line two, indented\nLine three'],
  ])('%s', (_label, role, content) => {
    const { container } = renderMessage(role, content);
    expectVerbatim(container, content);
  });
});

describe('Message — the HTML, tool and tool-call branches are untouched (D14)', () => {
  it('an assistant HTML message still renders through the collapsible HTML branch', () => {
    renderMessage('assistant', '<!DOCTYPE html><html><body><div class="slide">Hi</div></body></html>');
    expect(screen.getByText('AI Assistant (HTML)')).toBeInTheDocument();
    expect(screen.queryByTestId('message-reviewer-details')).toBeNull();
  });

  it('HTML wins over the advisory shape: the HTML branch runs first', () => {
    renderMessage('assistant', `${ADVISORY_LEAD}${SEP}- <!DOCTYPE html> ${M1}`);
    expect(screen.getByText('AI Assistant (HTML)')).toBeInTheDocument();
    expect(screen.queryByTestId('message-reviewer-details')).toBeNull();
  });

  it('a tool message carrying a request shape is still a tool result', () => {
    renderMessage('tool', APPLY);
    expect(screen.getByText('Tool Result')).toBeInTheDocument();
    expect(screen.queryByTestId('message-reviewer-details')).toBeNull();
  });

  it('an assistant tool call carrying the advisory shape is still a tool call', () => {
    renderMessage('assistant', ADVISORY, {
      tool_call: { name: 'query_genie_space', arguments: { query: 'revenue by region' } },
    });
    expect(screen.getByText('Tool call: query_genie_space')).toBeInTheDocument();
    expect(screen.queryByTestId('message-reviewer-details')).toBeNull();
  });
});
