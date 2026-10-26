/**
 * The chat placeholder's copy for a graph turn (#319, plan D7), and the
 * validation and ordering rules the transports lean on (plan D3, D6).
 *
 * Pure functions only, and every label expectation is an exact string, so a
 * change of wording, of the ellipsis character or of the slide numbering turns a
 * test red.  Two byte-level facts are pinned on purpose:
 *  - the stage labels end with the single character U+2026 ("…"), never "...";
 *  - the no-snapshot text keeps its three ASCII dots, byte for byte, because
 *    tests/e2e/chat-ui.spec.ts pins /Generating slides/ and the legacy engine
 *    must look exactly as it does today.
 *
 * Positions on the wire are 0-based; the UI shows `position + 1`, matching the
 * ribbon's `Slide {index + 1}` (ThumbnailRibbon.tsx).
 */
import {
  DEFAULT_TURN_LABEL,
  describeTurnProgress,
  newerTurnProgress,
  parseTurnProgress,
} from './turnProgress';
import type { TurnPhase, TurnProgress } from '../types/turnProgress';

const ELLIPSIS = '…';

type StageLists = Partial<Record<'building' | 'reviewing' | 'fixing' | 'done', number[]>>;

/** A snapshot in the wire shape: every stage list present, positions 0-based. */
function snapshot(phase: TurnPhase, total = 0, lists: StageLists = {}, seq = 1): TurnProgress {
  return {
    seq,
    phase,
    slides: {
      total,
      building: lists.building ?? [],
      reviewing: lists.reviewing ?? [],
      fixing: lists.fixing ?? [],
      done: lists.done ?? [],
    },
  };
}

/** [from, to) */
const range = (from: number, to: number): number[] =>
  Array.from({ length: to - from }, (_, i) => from + i);

const label = (progress: TurnProgress | null): string => describeTurnProgress(progress);

// ---------------------------------------------------------------------------
// describeTurnProgress
// ---------------------------------------------------------------------------

describe('describeTurnProgress: the issue\'s own examples', () => {
  it('the five example labels from #319 are produced verbatim', () => {
    expect(label(snapshot('planning'))).toBe('Planning the deck…');
    expect(label(snapshot('building', 10, { building: range(0, 10) }))).toBe('Building 10 slides…');
    expect(label(snapshot('building', 1, { reviewing: [2] }))).toBe('Reviewing slide 3…');
    expect(label(snapshot('building', 2, { fixing: [0, 1] }))).toBe('Fixing 2 slides…');
    expect(label(snapshot('reviewing_deck', 10, { done: range(0, 10) }))).toBe('Reviewing the narrative…');
  });
});

describe('describeTurnProgress: the D7 copy table, one row each', () => {
  it('no snapshot yet (or the legacy engine) shows "Generating slides..." byte for byte, three ASCII dots', () => {
    expect(label(null)).toBe('Generating slides...');
    expect(DEFAULT_TURN_LABEL).toBe('Generating slides...');
    expect(DEFAULT_TURN_LABEL).toHaveLength(20);
    expect(DEFAULT_TURN_LABEL).not.toContain(ELLIPSIS);
  });

  it('planning reads "Planning the deck…"', () => {
    expect(label(snapshot('planning'))).toBe('Planning the deck…');
  });

  it('gathering_data reads "Gathering the data…"', () => {
    expect(label(snapshot('gathering_data'))).toBe('Gathering the data…');
  });

  it('checking_slides reads "Checking the slides against the new brief…"', () => {
    expect(label(snapshot('checking_slides'))).toBe('Checking the slides against the new brief…');
  });

  it('reviewing_deck reads "Reviewing the narrative…", whatever the slide lists say', () => {
    expect(label(snapshot('reviewing_deck', 10, { done: range(0, 10) }))).toBe('Reviewing the narrative…');
    expect(label(snapshot('reviewing_deck', 3, { done: [0, 2], reviewing: [1] }))).toBe('Reviewing the narrative…');
  });

  it('building with one active stage of several slides names the count, for each verb', () => {
    expect(label(snapshot('building', 10, { building: range(0, 10) }))).toBe('Building 10 slides…');
    expect(label(snapshot('building', 2, { reviewing: [0, 1] }))).toBe('Reviewing 2 slides…');
    expect(label(snapshot('building', 2, { fixing: [0, 1] }))).toBe('Fixing 2 slides…');
  });

  it('a single slide in a stage is named by its 1-based number, for each verb', () => {
    expect(label(snapshot('building', 1, { building: [0] }))).toBe('Building slide 1…');
    // D9: editing slide 2 (position 1) reads "Building slide 2…".
    expect(label(snapshot('building', 1, { building: [1] }))).toBe('Building slide 2…');
    expect(label(snapshot('building', 1, { reviewing: [2] }))).toBe('Reviewing slide 3…');
    expect(label(snapshot('building', 1, { fixing: [4] }))).toBe('Fixing slide 5…');
  });

  it('several active stages read as one sentence in pipeline order: building, reviewing, fixing', () => {
    expect(
      label(snapshot('building', 6, { building: [0, 1, 2], reviewing: [3, 4], fixing: [5] })),
    ).toBe('Building 3 slides, reviewing 2 slides, fixing slide 6…');
    // Pipeline order, not position order; only the first letter is capitalised.
    expect(
      label(snapshot('building', 6, { fixing: [0], reviewing: [1, 2], building: [5] })),
    ).toBe('Building slide 6, reviewing 2 slides, fixing slide 1…');
    expect(label(snapshot('building', 2, { reviewing: [0], fixing: [3] }))).toBe(
      'Reviewing slide 1, fixing slide 4…',
    );
  });

  it('the mixed three-clause sentence carries the done suffix after the ellipsis', () => {
    expect(
      label(
        snapshot('building', 10, {
          building: [0, 1, 2],
          reviewing: [3, 4],
          fixing: [5],
          done: [6, 7, 8, 9],
        }),
      ),
    ).toBe('Building 3 slides, reviewing 2 slides, fixing slide 6… (4 of 10 done)');
  });

  it('building with some slides done in a multi-slide turn appends " (D of T done)"', () => {
    expect(
      label(
        snapshot('building', 10, {
          reviewing: [0, 1],
          fixing: [4],
          done: [2, 3, 5, 6, 7, 8, 9],
        }),
      ),
    ).toBe('Reviewing 2 slides, fixing slide 5… (7 of 10 done)');
    // The smallest turn that qualifies: total 2, one done.
    expect(label(snapshot('building', 2, { building: [1], done: [0] }))).toBe(
      'Building slide 2… (1 of 2 done)',
    );
  });

  it('the done suffix appears only when total > 1 and done > 0', () => {
    // done == 0 in a multi-slide turn: no suffix.
    expect(
      label(snapshot('building', 10, { building: [2, 3, 5, 6, 7, 8, 9], reviewing: [0, 1], fixing: [4] })),
    ).toBe('Building 7 slides, reviewing 2 slides, fixing slide 5…');
    // A single-slide turn never reads "(… of 1 done)".
    expect(label(snapshot('building', 1, { reviewing: [0] }))).toBe('Reviewing slide 1…');
    expect(label(snapshot('building', 1, { done: [0] }))).toBe('Finishing the slides…');
  });

  it('nothing active with slides still to go reads "Building the slides…", plus the suffix when it applies', () => {
    expect(label(snapshot('building', 10, { done: range(0, 6) }))).toBe('Building the slides… (6 of 10 done)');
    expect(label(snapshot('building', 20))).toBe('Building the slides…');
  });

  it('nothing active and every slide done reads "Finishing the slides…", with no suffix', () => {
    expect(label(snapshot('building', 10, { done: range(0, 10) }))).toBe('Finishing the slides…');
    expect(label(snapshot('building', 1, { done: [0] }))).toBe('Finishing the slides…');
  });
});

describe('describeTurnProgress: edges of the table', () => {
  it('queued slides are not named; the done suffix carries the overall progress', () => {
    // A 20-slide deck dispatches at most 15 at once; the other 5 are covered but queued.
    expect(label(snapshot('building', 20, { building: range(0, 15) }))).toBe('Building 15 slides…');
    expect(label(snapshot('building', 20, { building: range(15, 20), done: range(0, 15) }))).toBe(
      'Building 5 slides… (15 of 20 done)',
    );
  });

  it('a building snapshot with no slides at all does not claim to be finishing', () => {
    expect(label(snapshot('building', 0))).toBe('Building the slides…');
  });

  it('the ellipsis is the single character U+2026, never three dots', () => {
    const labels = [
      label(snapshot('planning')),
      label(snapshot('gathering_data')),
      label(snapshot('checking_slides')),
      label(snapshot('reviewing_deck')),
      label(snapshot('building', 1, { building: [0] })),
      label(snapshot('building', 20)),
      label(snapshot('building', 10, { done: range(0, 10) })),
    ];
    for (const text of labels) {
      expect(text.endsWith(ELLIPSIS), text).toBe(true);
      expect(text, text).not.toContain('...');
    }
    expect(label(snapshot('building', 10, { reviewing: [0], done: range(1, 10) }))).toBe(
      `Reviewing slide 1${ELLIPSIS} (9 of 10 done)`,
    );
  });

  it('no label contains an emoji, an internal node name or a raw enum value', () => {
    const corpus: Array<TurnProgress | null> = [
      null,
      snapshot('planning'),
      snapshot('gathering_data'),
      snapshot('checking_slides'),
      snapshot('reviewing_deck', 10, { done: range(0, 10) }),
      snapshot('building', 10, { building: range(0, 10) }),
      snapshot('building', 1, { building: [0] }),
      snapshot('building', 1, { reviewing: [2] }),
      snapshot('building', 1, { fixing: [4] }),
      snapshot('building', 10, { building: [0, 1, 2], reviewing: [3, 4], fixing: [5], done: [6, 7, 8, 9] }),
      snapshot('building', 10, { done: range(0, 6) }),
      snapshot('building', 10, { done: range(0, 10) }),
    ];
    // Not vacuous: every phase is in the corpus.
    expect(new Set(corpus.map((p) => p?.phase ?? null))).toEqual(
      new Set([null, 'planning', 'gathering_data', 'checking_slides', 'reviewing_deck', 'building']),
    );
    for (const progress of corpus) {
      const text = label(progress);
      expect(text, JSON.stringify(progress)).toMatch(/\S/);
      expect(text, text).not.toMatch(/\p{Extended_Pictographic}/u);
      expect(text, text).not.toMatch(/architect|foreman|reviewer|pipeline|analyst|builder|fixer|placeholder|node/i);
      expect(text, text).not.toContain('_');
    }
  });
});

// ---------------------------------------------------------------------------
// newerTurnProgress
// ---------------------------------------------------------------------------

describe('newerTurnProgress: hold the highest seq seen this turn', () => {
  const held = snapshot('building', 10, { building: range(0, 10) }, 3);

  it('a higher seq replaces the held snapshot', () => {
    const incoming = snapshot('building', 10, { building: range(1, 10), reviewing: [0] }, 4);
    expect(newerTurnProgress(held, incoming)).toBe(incoming);
  });

  it('an equal seq keeps the held snapshot', () => {
    const sameSeq = snapshot('planning', 0, {}, 3);
    expect(newerTurnProgress(held, sameSeq)).toBe(held);
  });

  it('a lower seq keeps the held snapshot', () => {
    const older = snapshot('planning', 0, {}, 2);
    expect(newerTurnProgress(held, older)).toBe(held);
  });

  it('a null incoming keeps the held snapshot', () => {
    expect(newerTurnProgress(held, null)).toBe(held);
    expect(newerTurnProgress(null, null)).toBeNull();
  });

  it('a null held takes the incoming snapshot, even at seq 1', () => {
    const first = snapshot('planning', 0, {}, 1);
    expect(newerTurnProgress(null, first)).toBe(first);
  });
});

// ---------------------------------------------------------------------------
// parseTurnProgress
// ---------------------------------------------------------------------------

/** The plan's wire-contract example (Task 2): lists ascending and disjoint, 0-based. */
function wireSnapshot(): Record<string, unknown> {
  return {
    seq: 7,
    phase: 'building',
    slides: { total: 10, building: [0, 1, 2], reviewing: [3], fixing: [4, 5], done: [6, 7, 8, 9] },
  };
}

/** The wire example with one top-level key replaced (or removed, for `undefined`). */
function withTop(key: string, value: unknown): Record<string, unknown> {
  const v = wireSnapshot();
  if (value === undefined) delete v[key];
  else v[key] = value;
  return v;
}

/** The wire example with one `slides` key replaced (or removed, for `undefined`). */
function withSlides(key: string, value: unknown): Record<string, unknown> {
  const v = wireSnapshot();
  const slides = { ...(v.slides as Record<string, unknown>) };
  if (value === undefined) delete slides[key];
  else slides[key] = value;
  v.slides = slides;
  return v;
}

const STAGES = ['building', 'reviewing', 'fixing', 'done'] as const;

const REJECTED: Array<[string, unknown]> = [
  ['undefined', undefined],
  ['null', null],
  ['a string (even one holding a valid snapshot as JSON)', JSON.stringify(wireSnapshot())],
  ['a missing seq', withTop('seq', undefined)],
  ['a non-integer seq', withTop('seq', 1.5)],
  ['a string seq', withTop('seq', '7')],
  ['a zero seq', withTop('seq', 0)],
  ['an unknown phase', withTop('phase', 'deploying')],
  ['a null phase', withTop('phase', null)],
  ['missing slides', withTop('slides', undefined)],
  ['null slides', withTop('slides', null)],
  ['a non-integer total', withSlides('total', 1.5)],
  ['a negative total', withSlides('total', -1)],
  ...STAGES.flatMap((stage): Array<[string, unknown]> => [
    [`a missing ${stage} list`, withSlides(stage, undefined)],
    [`a ${stage} list that is not an array`, withSlides(stage, 3)],
    [`a ${stage} list containing -1`, withSlides(stage, [-1])],
    [`a ${stage} list containing 1.5`, withSlides(stage, [1.5])],
  ]),
  ['the legacy mock shape {message}', { message: 'Generating slides...' }],
  ['the legacy progress event mock', { type: 'progress', message: 'Generating slides...' }],
];

describe('parseTurnProgress: only a well-formed snapshot is ever rendered', () => {
  it('accepts the wire-contract snapshot and returns it unchanged', () => {
    expect(parseTurnProgress(wireSnapshot())).toEqual(wireSnapshot());
  });

  it.each(['planning', 'gathering_data', 'checking_slides', 'building', 'reviewing_deck'])(
    'accepts phase %s with no slides yet (total 0, every list empty)',
    (phase) => {
      const start = { seq: 1, phase, slides: { total: 0, building: [], reviewing: [], fixing: [], done: [] } };
      expect(parseTurnProgress(start)).toEqual(start);
    },
  );

  it.each(REJECTED)('rejects %s', (_name, value) => {
    expect(parseTurnProgress(value)).toBeNull();
  });
});
