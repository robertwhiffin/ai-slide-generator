/**
 * #314 Task 8: the pure half of the new-slide indicator (plan D10, AC10; corrections C18, C20; review
 * m7, n5).
 *
 * `diffNewSlides(baseline, slides)` compares a deck's slide_ids with the last SERVER deck the viewer saw
 * (the baseline) and says which ids are new. Its rules, one table row each below:
 *   - no baseline (first mount, or a deckKey change reset it)  -> nothing new; the deck becomes the baseline.
 *   - any synthetic `build-N` id (a mid-turn view assembled from slide_ready events, on SSE and on
 *     polling alike)                                            -> nothing new; the baseline is KEPT, so
 *                                                                  the end-of-turn refetch is diffed
 *                                                                  against the pre-turn deck.
 *   - pure growth (every baseline id still there)              -> the ids not in the baseline, in DECK order.
 *   - growth plus a removed id                                 -> nothing new (a replace, not an add).
 *   - an empty baseline                                        -> nothing new (a first generation 0 -> N
 *                                                                  flags nothing).
 *   - null / empty ids                                         -> ignored on both sides.
 *   - unchanged (or only reordered)                            -> nothing new.
 *   - reordered and grown                                      -> the new ids only (growth compares sets).
 * Whenever the deck is not synthetic it becomes the next baseline.
 *
 * `syntheticSlideId(p)` is the one place a synthetic id is minted (AppLayout.handleSlideReady uses it), and
 * the helper must recognise its own ids. The AppLayout pin at the bottom reads AppLayout.tsx through the
 * TypeScript parser, not a regex over the text, so a comment holding the expected call cannot satisfy it.
 *
 * SABOTAGE (run against a throwaway implementation in /tmp/issue314-ui-t8, then reverted):
 *   - synthetic check dropped                             -> the build- rows RED.
 *   - synthetic check by `includes('build-')`             -> "x-build-1 is a real id" RED.
 *   - pure-growth check dropped                           -> "growth plus a removed id" RED.
 *   - fresh in baseline order / reversed                  -> "deck order" RED.
 *   - empty baseline treated as a real baseline           -> "empty baseline" RED.
 *   - baseline not replaced on a non-growth deck          -> "the next growth after a replace" RED.
 *   - null ids kept in the baseline / flagged             -> "null and empty ids" RED.
 *   - AppLayout keeps the `build-${position}` literal     -> the AppLayout pin RED.
 * Added after the whole-branch review (NIT-1), sabotaged on the REAL implementation:
 *   - any order change treated as not-growth              -> "reordered AND grown" RED.
 */
import ts from 'typescript';
import appLayoutSource from '../Layout/AppLayout.tsx?raw';
import {
  diffNewSlides,
  NEW_SLIDE_INDICATOR_MS,
  SYNTHETIC_SLIDE_ID_PREFIX,
  syntheticSlideId,
} from './newSlides';

type Id = string | null | undefined;

/** Slides carrying the given ids. `slide_id` is typed `string`; legacy rows can still carry none. */
const deck = (...ids: Id[]) => ids.map((id) => ({ slide_id: id as unknown as string }));
const set = (...ids: string[]): ReadonlySet<string> => new Set(ids);
const sorted = (s: ReadonlySet<string> | null) => (s === null ? null : [...s].sort());

// ── the rules, one row each ──────────────────────────────────────────────────

interface Row {
  rule: string;
  baseline: ReadonlySet<string> | null;
  slides: Id[];
  fresh: string[];
  /** The baseline after the call, as sorted ids (null = still no baseline). */
  next: string[] | null;
}

const ROWS: Row[] = [
  {
    rule: 'no baseline: nothing new, the deck becomes the baseline',
    baseline: null,
    slides: ['A', 'B', 'C'],
    fresh: [],
    next: ['A', 'B', 'C'],
  },
  {
    rule: 'a synthetic id replacing a slide (SSE mid-turn): nothing new, baseline kept',
    baseline: set('A', 'B', 'C'),
    slides: ['A', 'build-1', 'C'],
    fresh: [],
    next: ['A', 'B', 'C'],
  },
  {
    rule: 'every position synthetic (the first poll at cursor 0): nothing new, baseline kept',
    baseline: set('A', 'B', 'C'),
    slides: ['build-0', 'build-1', 'build-2'],
    fresh: [],
    next: ['A', 'B', 'C'],
  },
  {
    rule: 'a synthetic id appended to real ones (growth, but mid-turn): nothing new, baseline kept',
    baseline: set('A', 'B', 'C'),
    slides: ['A', 'B', 'C', 'build-3'],
    fresh: [],
    next: ['A', 'B', 'C'],
  },
  {
    rule: "a revised synthetic id ('build-1-rev') is synthetic too",
    baseline: set('A', 'B'),
    slides: ['A', 'build-1-rev', 'B'],
    fresh: [],
    next: ['A', 'B'],
  },
  {
    rule: "the prefix is a prefix: 'x-build-1' is a real id",
    baseline: set('A'),
    slides: ['A', 'x-build-1'],
    fresh: ['x-build-1'],
    next: ['A', 'x-build-1'],
  },
  {
    rule: 'pure growth: the new ids, in deck order',
    baseline: set('A', 'B', 'C'),
    slides: ['A', 'X', 'B', 'Y', 'C'],
    fresh: ['X', 'Y'],
    next: ['A', 'B', 'C', 'X', 'Y'],
  },
  {
    rule: 'pure growth: deck order, not baseline or alphabetical order',
    baseline: set('B', 'C'),
    slides: ['Z', 'B', 'C', 'M'],
    fresh: ['Z', 'M'],
    next: ['B', 'C', 'M', 'Z'],
  },
  {
    rule: 'growth plus a removed id: nothing new, the deck becomes the baseline',
    baseline: set('A', 'B', 'C'),
    slides: ['A', 'X', 'C', 'Y'],
    fresh: [],
    next: ['A', 'C', 'X', 'Y'],
  },
  {
    rule: 'a shrink: nothing new, the deck becomes the baseline',
    baseline: set('A', 'B', 'C'),
    slides: ['A', 'C'],
    fresh: [],
    next: ['A', 'C'],
  },
  {
    rule: 'an empty baseline: nothing new (a first generation 0 -> N flags nothing)',
    baseline: set(),
    slides: ['A', 'B', 'C'],
    fresh: [],
    next: ['A', 'B', 'C'],
  },
  {
    rule: 'null and empty ids: ignored when flagging and kept out of the baseline',
    baseline: set('A', 'B'),
    slides: ['A', null, 'B', '', undefined, 'C'],
    fresh: ['C'],
    next: ['A', 'B', 'C'],
  },
  {
    rule: 'a slide losing its id is not a removal, a slide with none is not growth',
    baseline: set('A', 'B'),
    slides: [null, 'A', 'B', ''],
    fresh: [],
    next: ['A', 'B'],
  },
  {
    rule: 'unchanged: nothing new',
    baseline: set('A', 'B', 'C'),
    slides: ['A', 'B', 'C'],
    fresh: [],
    next: ['A', 'B', 'C'],
  },
  {
    rule: 'reordered only: nothing new',
    baseline: set('A', 'B', 'C'),
    slides: ['C', 'A', 'B'],
    fresh: [],
    next: ['A', 'B', 'C'],
  },
  {
    // Growth is set-based: a refetch that also moved existing slides still flags the added one.
    rule: 'reordered AND grown: only the new id is flagged',
    baseline: set('A', 'B', 'C'),
    slides: ['C', 'A', 'NEW', 'B'],
    fresh: ['NEW'],
    next: ['A', 'B', 'C', 'NEW'],
  },
];

describe('diffNewSlides (D10)', () => {
  it.each(ROWS)('$rule', ({ baseline, slides, fresh, next }) => {
    const result = diffNewSlides(baseline, deck(...slides));
    expect(result.fresh).toEqual(fresh);
    expect(sorted(result.baseline)).toEqual(next);
  });

  it('does not mutate the baseline it is given', () => {
    const baseline = new Set(['A', 'B']);
    diffNewSlides(baseline, deck('A', 'B', 'C'));
    diffNewSlides(baseline, deck('A', 'build-1'));
    diffNewSlides(baseline, deck('A', 'X'));
    expect([...baseline].sort()).toEqual(['A', 'B']);
  });
});

// ── sequences: the baseline a viewer carries from deck to deck ──────────────

/** Feeds decks through the helper as the viewer does, returning each step's fresh ids. */
function run(start: ReadonlySet<string> | null, ...decks: Id[][]): string[][] {
  let baseline = start;
  return decks.map((ids) => {
    const result = diffNewSlides(baseline, deck(...ids));
    baseline = result.baseline;
    return result.fresh;
  });
}

describe('diffNewSlides across a turn', () => {
  it('SSE insert turn: [A,B,C] -> [A,build-1,C] -> [A,NEW,B,C] flags only NEW', () => {
    expect(run(null, ['A', 'B', 'C'], ['A', 'build-1', 'C'], ['A', 'NEW', 'B', 'C'])).toEqual([
      [],
      [],
      ['NEW'],
    ]);
  });

  it('polling insert turn (m7): every position replaced, then a revision replace, then the refetch', () => {
    expect(
      run(
        null,
        ['A', 'B', 'C'],
        ['build-0', 'build-1', 'build-2'], // the first poll, cursor 0
        ['build-0', 'build-1', 'build-2', 'build-3'], // a slide_revisions-style replace and the 4th position
        ['A', 'NEW', 'B', 'C'], // the end-of-turn refetch
      ),
    ).toEqual([[], [], [], ['NEW']]);
  });

  it('a first generation from an empty viewer flags nothing, and the next real growth does flag', () => {
    expect(
      run(null, ['build-0'], ['build-0', 'build-1'], ['A', 'B'], ['A', 'B', 'C']),
    ).toEqual([[], [], [], ['C']]);
  });

  it('the next growth after a replace is diffed against the replacing deck', () => {
    // [A,B,C] -> [A,X,C] is a replace (B gone): nothing. Its ids are the new baseline, so adding Y flags Y.
    expect(run(null, ['A', 'B', 'C'], ['A', 'X', 'C'], ['A', 'X', 'C', 'Y'])).toEqual([[], [], ['Y']]);
  });
});

// ── the synthetic id and the timing constant ─────────────────────────────────

describe('syntheticSlideId and the constants', () => {
  it.each([0, 1, 7, 12])("syntheticSlideId(%i) is 'build-' + position", (p) => {
    expect(SYNTHETIC_SLIDE_ID_PREFIX).toBe('build-');
    expect(syntheticSlideId(p)).toBe(`build-${p}`);
    expect(syntheticSlideId(p)).toBe(SYNTHETIC_SLIDE_ID_PREFIX + p);
  });

  it('the helper recognises the ids syntheticSlideId mints', () => {
    const result = diffNewSlides(set('A', 'B'), deck('A', 'B', syntheticSlideId(2)));
    expect(result.fresh).toEqual([]);
    expect(sorted(result.baseline)).toEqual(['A', 'B']);
    // Positive in the same test: the same growth with a real id is flagged.
    expect(diffNewSlides(set('A', 'B'), deck('A', 'B', 'C')).fresh).toEqual(['C']);
  });

  it('a chip lasts 5 seconds', () => {
    expect(NEW_SLIDE_INDICATOR_MS).toBe(5000);
  });
});

// ── AppLayout mints mid-turn ids through the helper (source pin) ─────────────
//
// handleSlideReady lives inside the AppLayout component; rendering AppLayout needs the whole app shell
// (see AppLayoutSpecToggle.test.ts). The TypeScript AST is used instead of a regex so comments do not count.

const appLayout = ts.createSourceFile(
  'AppLayout.tsx',
  appLayoutSource,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);

function findAll<T extends ts.Node>(root: ts.Node, test: (n: ts.Node) => n is T): T[] {
  const out: T[] = [];
  const visit = (n: ts.Node) => {
    if (test(n)) out.push(n);
    ts.forEachChild(n, visit);
  };
  visit(root);
  return out;
}

describe('AppLayout.handleSlideReady uses syntheticSlideId', () => {
  it('the slide it builds takes its slide_id from syntheticSlideId(position)', () => {
    const decls = findAll(appLayout, ts.isVariableDeclaration).filter(
      (d) => ts.isIdentifier(d.name) && d.name.text === 'handleSlideReady',
    );
    expect(decls, 'handleSlideReady not found in AppLayout.tsx').toHaveLength(1);

    const slideIdProps = findAll(decls[0], ts.isPropertyAssignment).filter(
      (p) => ts.isIdentifier(p.name) && p.name.text === 'slide_id',
    );
    expect(slideIdProps, 'handleSlideReady builds no object with a slide_id').toHaveLength(1);
    const init = slideIdProps[0].initializer;
    expect(ts.isCallExpression(init) ? init.expression.getText(appLayout) : init.getText(appLayout)).toBe(
      'syntheticSlideId',
    );
    expect((init as ts.CallExpression).arguments.map((a) => a.getText(appLayout))).toEqual(['position']);
  });

  it('syntheticSlideId is imported from the SlideViewer newSlides module', () => {
    const imports = findAll(appLayout, ts.isImportDeclaration).filter((d) => {
      const bindings = d.importClause?.namedBindings;
      return (
        !!bindings
        && ts.isNamedImports(bindings)
        && bindings.elements.some((e) => e.name.text === 'syntheticSlideId')
      );
    });
    expect(imports).toHaveLength(1);
    expect((imports[0].moduleSpecifier as ts.StringLiteral).text).toMatch(/(^|\/)SlideViewer\/newSlides$/);
  });

  it("no other code in AppLayout spells a 'build-' id by hand", () => {
    // String and template literals only (comments are not nodes). The helper owns the prefix.
    const literals = findAll(
      appLayout,
      (n): n is ts.Node =>
        ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n) || ts.isTemplateExpression(n),
    );
    const spelled = literals.filter((n) => {
      const text = ts.isTemplateExpression(n) ? n.head.text : (n as ts.StringLiteral).text;
      return text.startsWith('build-');
    });
    expect(spelled.map((n) => n.getText(appLayout))).toEqual([]);
    // Vacuity guard: the scan does see AppLayout's literals.
    expect(literals.length).toBeGreaterThan(10);
  });
});
