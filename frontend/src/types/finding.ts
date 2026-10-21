export type FindingCategory = 'content' | 'design' | 'narrative';
export type FindingStatus = 'open' | 'fixed';

export interface SlideFinding {
  id: string;
  slideIndex: number;   // 0-based, matches Slide.index; -1 for deck-level findings
  category: FindingCategory;
  criterion: string;    // key into Python CRITERIA registry
  message: string;
  plainMessage: string; // issue + status, derived at read time (src/domain/finding_copy.py via _finding_to_camel); NOT a Python Finding field
  plainIssue: string;   // the issue sentence alone (tense by status); same derivation; leads Apply/Discuss requests
  objective: boolean;   // predicate: could an automated fixer handle this?
  status: FindingStatus;  // open = unaddressed; fixed = handled by auto-fixer
  seen: boolean;        // initial value only; lifecycle owned client-side
}

export interface DrawerCallbacks {
  onApplyFinding: (findingId: string) => void;
  onDismissFinding: (findingId: string) => void;
  onDiscussFinding: (findingId: string) => void;
}

// CATEGORY_LABEL moved here from FeedbackDrawer.tsx so the Python conformance
// test can assert key-exhaustiveness from a types file rather than parsing a
// component.  The Record<FindingCategory, string> annotation enforces compile-
// time completeness: adding a fourth FindingCategory without adding its label
// here becomes a TS error at the Record literal.
export const CATEGORY_LABEL: Record<FindingCategory, string> = {
  content: 'Content',
  design: 'Design',
  narrative: 'Narrative',
};

/** Shown if a finding arrives without plainMessage/plainIssue (an untyped mock or a stale API cache). Equals
 *  GENERIC_ISSUE.present in src/domain/finding_copy.py — pinned by test_finding_conformance.py. */
export const PLAIN_MESSAGE_FALLBACK = "Something here may need a closer look.";

/**
 * Criteria whose findings are routed to CHAT, not the slide drawer (grain-routing rule).
 *
 * Mirrors the `level: "deck"` entries in the Python CRITERIA registry at
 * `src/domain/finding.py`.  Kept in sync by a CONFORMANCE TEST, not by this comment:
 * `tests/unit/test_finding_conformance.py::TestFindingConformance::
 * test_deck_level_criteria_mirror_equals_the_registrys_deck_level_set` asserts this
 * Set equals the registry's level="deck" names in both directions.  Add a
 * deck-level criterion server-side without mirroring it here and that test goes
 * red (review finding I2).
 *
 * Guard: a finding with a deck-level criterion must never render in the FeedbackDrawer
 * even if it somehow carries a real slideIndex (§E2 defence-in-depth filter).
 */
export const DECK_LEVEL_CRITERIA: ReadonlySet<string> = new Set([
  'arc_gap',
  'cross_slide_repetition',
  'missing_conclusion',
]);
