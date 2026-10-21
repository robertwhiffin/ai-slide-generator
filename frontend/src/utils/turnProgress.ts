import { SLIDE_PROGRESS_STAGES, TURN_PHASES } from '../types/turnProgress';
import type { TurnPhase, TurnProgress } from '../types/turnProgress';

const ELLIPSIS = '…';

/** Unchanged legacy text: shown before the first stage arrives and for the legacy engine. */
export const DEFAULT_TURN_LABEL = 'Generating slides...';

const PHASE_LABELS: Record<Exclude<TurnPhase, 'building'>, string> = {
  planning: `Planning the deck${ELLIPSIS}`,
  gathering_data: `Gathering the data${ELLIPSIS}`,
  checking_slides: `Checking the slides against the new brief${ELLIPSIS}`,
  reviewing_deck: `Reviewing the narrative${ELLIPSIS}`,
};

const isPositions = (v: unknown): v is number[] =>
  Array.isArray(v) && v.every((n) => Number.isInteger(n) && n >= 0);

/** A well-formed snapshot, or null (malformed or absent payloads are ignored, never rendered). */
export function parseTurnProgress(value: unknown): TurnProgress | null {
  if (!value || typeof value !== 'object') return null;
  const v = value as Record<string, unknown>;
  if (!Number.isInteger(v.seq) || (v.seq as number) < 1) return null;
  if (typeof v.phase !== 'string' || !(TURN_PHASES as readonly string[]).includes(v.phase)) return null;
  const s = v.slides as Record<string, unknown> | null | undefined;
  if (!s || typeof s !== 'object' || !Number.isInteger(s.total) || (s.total as number) < 0) return null;
  if (!SLIDE_PROGRESS_STAGES.every((stage) => isPositions(s[stage]))) return null;
  return value as TurnProgress;
}

/** The snapshot to hold: `incoming` only when it is newer than `held` (seq strictly greater). */
export function newerTurnProgress(held: TurnProgress | null, incoming: TurnProgress | null): TurnProgress | null {
  if (!incoming) return held;
  if (!held || incoming.seq > held.seq) return incoming;
  return held;
}

function clause(verb: string, positions: number[]): string {
  return positions.length === 1 ? `${verb} slide ${positions[0] + 1}` : `${verb} ${positions.length} slides`;
}

/** The placeholder text for a snapshot (see the plan's D7 table). */
export function describeTurnProgress(progress: TurnProgress | null): string {
  if (!progress) return DEFAULT_TURN_LABEL;
  if (progress.phase !== 'building') return PHASE_LABELS[progress.phase];
  const { total, building, reviewing, fixing, done } = progress.slides;
  const clauses = [
    building.length ? clause('building', building) : null,
    reviewing.length ? clause('reviewing', reviewing) : null,
    fixing.length ? clause('fixing', fixing) : null,
  ].filter((c): c is string => c !== null);
  if (clauses.length === 0 && total > 0 && done.length === total) return `Finishing the slides${ELLIPSIS}`;
  const head = clauses.length ? clauses.join(', ') : 'building the slides';
  const sentence = `${head.charAt(0).toUpperCase()}${head.slice(1)}${ELLIPSIS}`;
  return total > 1 && done.length > 0 ? `${sentence} (${done.length} of ${total} done)` : sentence;
}
