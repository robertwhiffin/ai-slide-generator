export type FindingCategory = 'content' | 'design' | 'narrative';
export type FindingStatus = 'open' | 'fixed';

export interface SlideFinding {
  id: string;
  slideIndex: number;   // 0-based, matches Slide.index; -1 for deck-level findings
  category: FindingCategory;
  criterion: string;    // key into Python CRITERIA registry
  message: string;
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
