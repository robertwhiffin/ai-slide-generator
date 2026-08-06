export type FindingCategory = 'content' | 'design' | 'narrative';

export interface SlideFinding {
  id: string;
  slideIndex: number;   // 0-based, matches Slide.index
  category: FindingCategory;
  message: string;
  seen: boolean;        // initial value only; lifecycle owned client-side
}

export interface DrawerCallbacks {
  onApplyFinding: (findingId: string) => void;
  onDismissFinding: (findingId: string) => void;
  onDiscussFinding: (findingId: string) => void;
}
