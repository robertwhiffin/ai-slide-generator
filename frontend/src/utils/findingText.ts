import { PLAIN_MESSAGE_FALLBACK, type SlideFinding } from '../types/finding';

/** Splits a chat message's plain lead from the reviewer's technical text. Mirrors
 *  REVIEWER_DETAILS_SEPARATOR in src/domain/finding_copy.py (pinned equal). */
export const REVIEWER_DETAILS_SEPARATOR = "\n\nReviewer's details:\n";
export const APPLY_REQUEST_LEAD = "Please fix this on slide";
export const DISCUSS_REQUEST_LEAD = "I'd like to discuss this on slide";

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
