import type { SlideFinding } from '../../src/types/finding';

export const mockFindings: SlideFinding[] = [
  { id: 'f1', slideIndex: 1, category: 'design',    message: 'This layout is busy; consider splitting it.', seen: false },
  { id: 'f2', slideIndex: 1, category: 'content',   message: 'The 35% figure is not supported by the source data.', seen: false },
  { id: 'f3', slideIndex: 3, category: 'narrative', message: 'This slide breaks the argument arc.', seen: false },
];
