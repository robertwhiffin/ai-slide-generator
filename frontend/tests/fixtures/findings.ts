import type { SlideFinding } from '../../src/types/finding';

// Keep ids f1/f2/f3 and f3's slideIndex:3 — ~10 assertions in slide-viewer.spec.ts key on
// them.  slideIndex:3 is deliberately unreachable in the 3-slide spec deck, which is what
// keeps drawer-empty visible on slide 2 at spec line :319.
//
// f3 carries criterion 'arc_gap' (deck-level) on a non-deck slideIndex.  That is fine for
// this drawer-layout fixture but contradicts the grain-routing rule; nothing may build a
// deck-level assertion on f3 here.  (ws4e E2 asserts grain routing on its own injected
// component-test finding, not on this fixture.)
export const mockFindings: SlideFinding[] = [
  {
    id: 'f1',
    slideIndex: 1,
    category: 'design',
    criterion: 'rogue_colour',
    message: 'This layout is busy; consider splitting it.',
    plainMessage: "A colour on this slide was outside the deck's colour scheme. This was fixed automatically.",
    plainIssue: "A colour on this slide was outside the deck's colour scheme.",
    objective: true,
    status: 'fixed',
    seen: false,
  },
  {
    id: 'f2',
    slideIndex: 1,
    category: 'content',
    criterion: 'source_contradiction',
    message: 'The 35% figure is not supported by the source data.',
    plainMessage: "A figure on this slide does not match the source data. This was not fixed automatically.",
    plainIssue: "A figure on this slide does not match the source data.",
    objective: true,
    status: 'open',
    seen: false,
  },
  {
    id: 'f3',
    slideIndex: 3,
    category: 'narrative',
    criterion: 'arc_gap',
    message: 'This slide breaks the argument arc.',
    plainMessage: "The story has a gap or an unexplained jump between slides. This is a judgement call, so it was left for you to decide.",
    plainIssue: "The story has a gap or an unexplained jump between slides.",
    objective: false,
    status: 'open',
    seen: false,
  },
];
