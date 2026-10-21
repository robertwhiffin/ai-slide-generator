/**
 * The graph turn's stage summary (#319), mirrored from src/services/graph/progress.py.
 * Positions are 0-based; the UI shows position + 1.  Pinned against the Python
 * enums by src/utils/turnProgress.conformance.test.ts.
 * (Named SlideProgressStage, not SlideStage: SlideViewer/SlideStage.tsx is a component.)
 */
export const TURN_PHASES = ['planning', 'gathering_data', 'checking_slides', 'building', 'reviewing_deck'] as const;
export type TurnPhase = (typeof TURN_PHASES)[number];

export const SLIDE_PROGRESS_STAGES = ['building', 'reviewing', 'fixing', 'done'] as const;
export type SlideProgressStage = (typeof SLIDE_PROGRESS_STAGES)[number];

export type TurnProgressSlides = { total: number } & Record<SlideProgressStage, number[]>;

export interface TurnProgress {
  seq: number;
  phase: TurnPhase;
  slides: TurnProgressSlides;
}
