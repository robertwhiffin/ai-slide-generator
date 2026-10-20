import { PLAIN_MESSAGE_FALLBACK, type SlideFinding } from '../types/finding';

/** Splits a chat message's plain lead from the reviewer's technical text. Mirrors
 *  REVIEWER_DETAILS_SEPARATOR in src/domain/finding_copy.py (pinned equal). */
export const REVIEWER_DETAILS_SEPARATOR = "\n\nReviewer's details:\n";
export const APPLY_REQUEST_LEAD = "Please fix this on slide";
export const DISCUSS_REQUEST_LEAD = "I'd like to discuss this on slide";

/** Mirrors src/domain/finding_copy.py (pinned equal by tests/unit/test_finding_conformance.py).
 *  nodes._advisory_text writes the deck-review advisory from these three strings. */
export const DECK_ADVISORY_HEADER_PREFIX = "Deck review found ";
export const DECK_ADVISORY_HEADER_SUFFIX = " to look at in how the deck reads as a whole:";
export const DECK_ADVISORY_CLOSING =
  "None of these were changed automatically. Reply here if you'd like any of them addressed.";

/** The drawer's plain-language line for a finding; never the technical message. */
export function findingPlainText(f: Pick<SlideFinding, 'plainMessage'>): string {
  const text = typeof f.plainMessage === 'string' ? f.plainMessage.trim() : '';
  return text || PLAIN_MESSAGE_FALLBACK;
}

/** The issue sentence alone, for request leads. */
export function findingPlainIssue(f: Pick<SlideFinding, 'plainIssue'>): string {
  const text = typeof f.plainIssue === 'string' ? f.plainIssue.trim() : '';
  return text || PLAIN_MESSAGE_FALLBACK;
}

function withReviewerDetails(lead: string, f: SlideFinding): string {
  return f.message.trim() ? `${lead}${REVIEWER_DETAILS_SEPARATOR}${f.message}` : lead;
}

/** Chat text for Apply: a plain lead for the user, the reviewer's text (verbatim) for the agents. */
export function applyFindingRequest(f: SlideFinding): string {
  return withReviewerDetails(`${APPLY_REQUEST_LEAD} ${f.slideIndex + 1}: ${findingPlainIssue(f)}`, f);
}

/** Chat text for Discuss, same shape. */
export function discussFindingRequest(f: SlideFinding): string {
  return withReviewerDetails(`${DISCUSS_REQUEST_LEAD} ${f.slideIndex + 1}: ${findingPlainIssue(f)}`, f);
}

/** A chat message split into its plain lead and the reviewer's technical details. */
export interface SplitMessage {
  lead: string;
  details: string;
}

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const FINDING_REQUEST_LEAD = new RegExp(
  `^(?:${escapeRegExp(APPLY_REQUEST_LEAD)}|${escapeRegExp(DISCUSS_REQUEST_LEAD)}) [1-9]\\d*: [^\\n]+$`,
);
const DECK_ADVISORY_LEAD = new RegExp(
  `^${escapeRegExp(DECK_ADVISORY_HEADER_PREFIX)}[1-9]\\d* things?${escapeRegExp(DECK_ADVISORY_HEADER_SUFFIX)}` +
    `\\n(?:- [^\\n]+\\n)+${escapeRegExp(DECK_ADVISORY_CLOSING)}$`,
);

function splitAt(content: string, lead: RegExp): SplitMessage | null {
  const at = content.indexOf(REVIEWER_DETAILS_SEPARATOR);
  if (at < 0) return null;
  const head = content.slice(0, at);
  const details = content.slice(at + REVIEWER_DETAILS_SEPARATOR.length);
  return lead.test(head) && details.trim() !== '' ? { lead: head, details } : null;
}

/** A user message written by applyFindingRequest/discussFindingRequest, else null. */
export const splitFindingRequest = (content: string): SplitMessage | null =>
  splitAt(content, FINDING_REQUEST_LEAD);

/** An assistant deck-review advisory written by nodes._advisory_text, else null. */
export const splitDeckAdvisory = (content: string): SplitMessage | null =>
  splitAt(content, DECK_ADVISORY_LEAD);
