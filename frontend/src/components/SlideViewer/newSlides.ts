/**
 * The pure half of the viewer's new-slide indicator (#314, plan D10).
 *
 * `diffNewSlides` compares the deck's `slide_id`s with the last SERVER deck the viewer saw (the
 * "baseline") and says which ids are new. It is the only place that decides what counts as new:
 *
 *   - no baseline (first mount, or a deckKey change reset it)  -> nothing new; the deck becomes the baseline.
 *   - any synthetic `build-N` id (a mid-turn view assembled from slide_ready events, on SSE and on
 *     polling alike)                                            -> nothing new; the baseline is KEPT, so the
 *                                                                  end-of-turn refetch is diffed against the
 *                                                                  pre-turn deck.
 *   - an empty baseline                                        -> nothing new (a first generation 0 -> N).
 *   - every baseline id still present (pure growth)            -> the ids not in the baseline, in DECK order.
 *   - a baseline id gone (a replace or a shrink)               -> nothing new.
 *   - null / empty ids                                         -> ignored on both sides.
 * Whenever the deck is not synthetic it becomes the next baseline.
 */

/** Mid-turn slides (AppLayout.handleSlideReady) carry ids with this prefix; no stored slide_id does. */
export const SYNTHETIC_SLIDE_ID_PREFIX = 'build-';

/** The one place a synthetic mid-turn slide id is minted. */
export function syntheticSlideId(position: number): string {
  return `${SYNTHETIC_SLIDE_ID_PREFIX}${position}`;
}

/** How long the "New" chips, ring and status line stay up after slides were added. */
export const NEW_SLIDE_INDICATOR_MS = 5000;

export function diffNewSlides(
  baseline: ReadonlySet<string> | null,
  slides: ReadonlyArray<{ slide_id?: string | null }>,
): { baseline: ReadonlySet<string> | null; fresh: string[] } {
  const ids = new Set<string>();
  let synthetic = false;
  for (const { slide_id: id } of slides) {
    if (typeof id !== 'string' || id === '') continue;
    if (id.startsWith(SYNTHETIC_SLIDE_ID_PREFIX)) synthetic = true;
    ids.add(id);
  }

  // A mid-turn view: not a server deck, so it neither flags anything nor replaces the baseline.
  if (synthetic) return { baseline, fresh: [] };

  if (baseline === null || baseline.size === 0) return { baseline: ids, fresh: [] };
  // Pure growth only: a baseline id that is gone makes this a replace or a shrink.
  if (![...baseline].every((id) => ids.has(id))) return { baseline: ids, fresh: [] };
  // Set iteration is insertion order, which is deck order.
  return { baseline: ids, fresh: [...ids].filter((id) => !baseline.has(id)) };
}
