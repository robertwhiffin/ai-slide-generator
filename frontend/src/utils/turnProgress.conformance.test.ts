/**
 * Conformance: the TypeScript turn-progress literals vs src/services/graph/progress.py (#319, plan D6).
 *
 * The backend's turn-progress contract is data: a `phase` drawn from `TurnPhase`
 * and per-stage position lists keyed by `SlideProgressStage`.  The copy lives in
 * the UI, keyed by those same strings.  Nothing bridges the two at runtime — the
 * snapshot crosses as parsed JSON and TypeScript types are erased — so a value
 * renamed on one side would make `parseTurnProgress` reject every snapshot (the
 * user would see "Generating slides..." forever) or leave a stage list unread.
 *
 * As in services/__tests__/deckSpecConformance.test.ts, the Python source is read
 * as TEXT: hand-writing the expected values here would only pin this file against
 * itself.  progress.py keeps each enum's class body to `NAME = "value"` lines
 * only (no docstring, no blank line inside the class) so the extraction below can
 * stay a single regular expression.
 */
import progressPy from '../../../src/services/graph/progress.py?raw';
import { SLIDE_PROGRESS_STAGES, TURN_PHASES } from '../types/turnProgress';
import { DEFAULT_TURN_LABEL, describeTurnProgress, parseTurnProgress } from './turnProgress';

/**
 * The plan's extraction (Task 6): the class header, then one or more `NAME = "value"`
 * lines at four spaces of indent (written ` {4}` for eslint's no-regex-spaces).
 */
const ENUM_BODIES: Record<string, RegExp> = {
  TurnPhase: /class TurnPhase\(str, Enum\):\n((?: {4}\w+ = "[a-z_]+"\n)+)/,
  SlideProgressStage: /class SlideProgressStage\(str, Enum\):\n((?: {4}\w+ = "[a-z_]+"\n)+)/,
};

function enumMatch(className: string): RegExpExecArray | null {
  return ENUM_BODIES[className].exec(progressPy);
}

/** The enum's values, in declaration order. */
function pythonEnumValues(className: string): string[] {
  const match = enumMatch(className);
  if (!match) {
    throw new Error(
      `class ${className}(str, Enum) with a NAME = "value" body was not found in `
      + 'src/services/graph/progress.py. Either it was renamed (update this mirror and '
      + 'types/turnProgress.ts) or its body no longer has the shape this test reads.',
    );
  }
  return [...match[1].matchAll(/^ {4}\w+ = "([a-z_]+)"$/gm)].map((m) => m[1]);
}

describe('turn progress conformance: the Python enums were read at all', () => {
  // A conformance check that extracts nothing is vacuously true.  Kept as its own
  // test so it is never the assertion that carries one of the comparisons below.
  it.each(Object.keys(ENUM_BODIES))('class %s(str, Enum) is found and its whole body is read', (className) => {
    const match = enumMatch(className);
    expect(match, `the ${className} regex did not match src/services/graph/progress.py`).not.toBeNull();
    expect(pythonEnumValues(className), `no values parsed out of class ${className}`).not.toEqual([]);

    // The capture must end where the class body ends.  A member whose line no
    // longer fits `NAME = "value"` (say a value with a digit or a capital) would
    // otherwise silently cut the capture short at that line.
    const rest = progressPy.slice(match!.index + match![0].length);
    expect(
      rest,
      `class ${className} continues past the parsed members; its next line is: `
      + JSON.stringify(rest.split('\n')[0]),
    ).not.toMatch(/^[ \t]+\S/);
  });
});

describe('turn progress conformance: the TypeScript literals mirror the Python enums', () => {
  it('TURN_PHASES lists exactly the TurnPhase values, in declaration order', () => {
    expect([...TURN_PHASES]).toEqual(pythonEnumValues('TurnPhase'));
  });

  it('SLIDE_PROGRESS_STAGES lists exactly the SlideProgressStage values, in declaration order', () => {
    expect([...SLIDE_PROGRESS_STAGES]).toEqual(pythonEnumValues('SlideProgressStage'));
  });

  it('every phase the backend can report has a label of its own', () => {
    // `npm run test:unit` does not typecheck, so the `Record<…, string>` of phase
    // labels is not enough on its own: a phase added on both sides but given no
    // copy would render `undefined`.
    for (const phase of pythonEnumValues('TurnPhase')) {
      const text = describeTurnProgress({
        seq: 1,
        phase: phase as (typeof TURN_PHASES)[number],
        slides: { total: 1, building: [0], reviewing: [], fixing: [], done: [] },
      });
      expect(typeof text, phase).toBe('string');
      expect(text, phase).not.toBe(DEFAULT_TURN_LABEL);
      expect(text.endsWith('…'), `${phase}: ${text}`).toBe(true);
    }
  });
});

describe('turn progress conformance: the snapshot keys the backend writes are the ones the UI parses', () => {
  // The enum values above are only half of the wire contract; the other half is
  // the dict keys `TurnProgress._snapshot_locked` writes.  A coordinated rename
  // of that method and its own Python test would otherwise pass every suite and
  // leave `parseTurnProgress` rejecting every snapshot ("Generating slides..."
  // forever).  The keys are read from the Python source and fed to the real
  // parser, so the check is backend-text against frontend-code, not a list
  // pinned against itself.
  const SNAPSHOT_BODY = /def _snapshot_locked\(self\)[^\n]*\n((?:(?: {8}.*)?\n)+?)\n/;

  function snapshotBody(): string {
    const match = SNAPSHOT_BODY.exec(progressPy);
    if (!match) {
      throw new Error('TurnProgress._snapshot_locked was not found in src/services/graph/progress.py');
    }
    return match[1];
  }

  it('reads the top-level keys and the slides total key out of _snapshot_locked', () => {
    const body = snapshotBody();
    const topLevel = [...body.matchAll(/^ {12}"(\w+)":/gm)].map((m) => m[1]);
    const slidesInit = /slides: Dict\[str, Any\] = \{"(\w+)":/.exec(body);

    expect(topLevel, 'no top-level snapshot keys parsed').not.toEqual([]);
    expect(slidesInit, 'the slides dict initialiser was not found').not.toBeNull();
    expect(body, 'stage lists are no longer keyed by SlideProgressStage values').toMatch(
      /slides\[stage\.value\]/,
    );

    const [seqKey, phaseKey, slidesKey] = topLevel;
    const totalKey = slidesInit![1];
    const stages = pythonEnumValues('SlideProgressStage');
    const slides: Record<string, unknown> = { [totalKey]: 2 };
    for (const stage of stages) slides[stage] = [];
    slides[stages[0]] = [0, 1];

    const wire = {
      [seqKey]: 1,
      [phaseKey]: pythonEnumValues('TurnPhase')[0],
      [slidesKey]: slides,
    };
    expect(topLevel).toHaveLength(3);
    expect(
      parseTurnProgress(wire),
      `the UI rejects a snapshot shaped the way progress.py writes it: ${JSON.stringify(wire)}`,
    ).not.toBeNull();
  });
});
