/**
 * Conformance: the TypeScript DeckSpec mirror vs src/domain/deck_spec.py.
 *
 * There is no runtime bridge between the Pydantic models and these interfaces —
 * the deck spec crosses as parsed JSON and TypeScript types are erased — which is
 * exactly why `Finding` and `SlideFinding` had already drifted when ws4b arrived
 * (the backend produced {category, severity, description, auto_fixable} while the
 * frontend declared {id, slideIndex, category, message, seen}).  ws4b's
 * `Finding` mirror came with `tests/unit/test_finding_conformance.py` for that
 * reason; this is the same guard for `DeckSpec`, on the frontend side.
 *
 * Why the Python source is read as TEXT: a vitest test cannot import a Pydantic
 * model, and the alternative — hand-writing the expected field list here — would
 * only pin this file against itself.  Reading the model means adding a field in
 * Python turns this red without anyone remembering to update a list.
 *
 * Why the comparison is THREE-WAY (Python source, the TypeScript interface read as
 * text, and a `Record<keyof T, true>` literal): the literal alone is not enough.
 * The compiler does enforce that it is exhaustive — a field added to an interface
 * but not to the literal fails `npm run typecheck`, and vice versa — but
 * `npm run test:unit` does not typecheck, so with only the literal a TypeScript
 * RENAME (`call_to_action` -> `callToAction`, updating both interface and literal)
 * left every assertion here green.  Measured, by sabotage.  Reading the interface
 * text as well means the vitest run catches a rename on either side by itself, and
 * the literal keeps the compile-time net underneath it.
 */
import deckSpecPy from '../../../../src/domain/deck_spec.py?raw';
import sessionManagerPy from '../../../../src/api/services/session_manager.py?raw';
import slideTs from '../../types/slide.ts?raw';
import type {
  DeckSpec,
  DesignContractRef,
  ResolvedData,
  ResolvedFigure,
  SlideSpec,
} from '../../types/slide';

// ---------------------------------------------------------------------------
// The TypeScript side — exhaustive by construction (see the header note)
// ---------------------------------------------------------------------------

const deckSpecKeys: Record<keyof DeckSpec, true> = {
  title: true,
  audience: true,
  purpose: true,
  argument: true,
  call_to_action: true,
  narrative_arc: true,
  design_contract: true,
  resolved_data: true,
  slides: true,
};

const slideSpecKeys: Record<keyof SlideSpec, true> = {
  position: true,
  purpose: true,
  content_brief: true,
  assumes: true,
  hands_off: true,
  data_references: true,
  template_section_index: true,
};

const designContractRefKeys: Record<keyof DesignContractRef, true> = {
  design_system_id: true,
  template_id: true,
  slide_style_id: true,
};

const resolvedDataKeys: Record<keyof ResolvedData, true> = {
  synthesis: true,
  figures: true,
  gaps: true,
};

const resolvedFigureKeys: Record<keyof ResolvedFigure, true> = {
  key: true,
  value: true,
  source: true,
};

/** Interface name in slide.ts -> the exhaustive key literal above. */
const MIRRORS: Record<string, Record<string, true>> = {
  DeckSpec: deckSpecKeys,
  SlideSpec: slideSpecKeys,
  DesignContractRef: designContractRefKeys,
  ResolvedData: resolvedDataKeys,
  ResolvedFigure: resolvedFigureKeys,
};

// ---------------------------------------------------------------------------
// Reading the Python models
// ---------------------------------------------------------------------------

/**
 * Field names declared on a Pydantic model, in declaration order.
 *
 * Docstrings are stripped first rather than skipped line by line: this codebase's
 * docstrings are long prose and several of their lines would otherwise parse as
 * annotated assignments.
 */
function pythonClassBody(source: string, className: string): string {
  const stripped = source.replace(/"""[\s\S]*?"""/g, '');
  const header = new RegExp(`^class ${className}\\(BaseModel\\):$`, 'm').exec(stripped);
  if (!header) {
    throw new Error(
      `class ${className}(BaseModel) not found in the Python source. Either it was `
      + 'renamed (update this mirror and slide.ts) or the base class changed.',
    );
  }
  const afterHeader = stripped.slice(header.index + header[0].length);
  const nextClass = afterHeader.search(/^class \w+/m);
  return nextClass === -1 ? afterHeader : afterHeader.slice(0, nextClass);
}

function pythonModelFields(source: string, className: string): string[] {
  const body = pythonClassBody(source, className);

  const fields: string[] = [];
  for (const line of body.split('\n')) {
    // Exactly four spaces of indent: model fields sit at class-body level, while
    // method bodies sit at eight and decorators start with '@'.
    const match = /^ {4}([a-z_][A-Za-z0-9_]*)\s*:\s*\S/.exec(line);
    if (match) fields.push(match[1]);
  }
  return fields;
}

/** Field name -> type annotation, for one `export interface` in slide.ts. */
function tsInterfaceFields(source: string, interfaceName: string): Map<string, string> {
  const header = new RegExp(`export interface ${interfaceName}\\s*\\{`).exec(source);
  if (!header) throw new Error(`export interface ${interfaceName} not found in slide.ts`);

  let depth = 1;
  let i = header.index + header[0].length;
  const start = i;
  while (i < source.length && depth > 0) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') depth -= 1;
    i += 1;
  }
  const body = source.slice(start, i - 1);

  const fields = new Map<string, string>();
  for (const raw of body.split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('//') || line.startsWith('*') || line.startsWith('/*')) continue;
    const match = /^([A-Za-z_][A-Za-z0-9_]*)\??\s*:\s*(.+?);?\s*$/.exec(line);
    if (match) fields.set(match[1], match[2].replace(/;$/, '').trim());
  }
  return fields;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DeckSpec conformance — field names', () => {
  it('the Python source was read and parsed at all', () => {
    // A conformance check that discovers no fields is vacuously true, and would
    // report success over an empty universe.  Kept as its own test so it can
    // never be the assertion that carries one of the comparisons below.
    for (const className of Object.keys(MIRRORS)) {
      expect(
        pythonModelFields(deckSpecPy, className),
        `no fields parsed out of class ${className}`,
      ).not.toEqual([]);
    }
  });

  it.each(Object.keys(MIRRORS))(
    '%s declares exactly the fields the Pydantic model declares',
    (className) => {
      const py = pythonModelFields(deckSpecPy, className).sort();
      const declared = [...tsInterfaceFields(slideTs, className).keys()].sort();

      expect(declared, [
        `${className}: the TypeScript interface and src/domain/deck_spec.py disagree.`,
        `  missing from TypeScript: ${py.filter((f) => !declared.includes(f)).join(', ') || '(none)'}`,
        `  not in Python:           ${declared.filter((f) => !py.includes(f)).join(', ') || '(none)'}`,
      ].join('\n')).toEqual(py);
    },
  );

  it.each(Object.keys(MIRRORS))(
    '%s: the exhaustive key literal matches the interface it is built from',
    (className) => {
      // The literal is `Record<keyof T, true>`, so this pair is normally kept in
      // step by the compiler. It is compared at runtime as well because
      // `npm run test:unit` does not typecheck: without this, the literal could go
      // stale against the interface and the Python comparison above would be
      // reading a name the frontend no longer declares.
      const declared = [...tsInterfaceFields(slideTs, className).keys()].sort();
      const literal = Object.keys(MIRRORS[className]).sort();
      expect(literal, `${className}: key literal is stale against the interface`)
        .toEqual(declared);
    },
  );
});

describe('DeckSpec conformance — nested models', () => {
  it('every composite field points at the mirror of the same Python model', () => {
    // A name-only comparison passes even when `design_contract` is typed
    // `string` on the TypeScript side, which would let the design contract be
    // read as text and the ids lost.  So the annotations are compared too, for
    // exactly the fields whose Python annotation names another mirrored model.
    const mirrored = Object.keys(MIRRORS);
    const checked: string[] = [];

    for (const className of mirrored) {
      const tsFields = tsInterfaceFields(slideTs, className);
      const pyBody = pythonClassBody(deckSpecPy, className);

      for (const [field] of tsFields) {
        const pyLine = new RegExp(`^ {4}${field}\\s*:\\s*(.+)$`, 'm').exec(pyBody);
        if (!pyLine) continue;
        const referenced = mirrored.filter((m) => new RegExp(`\\b${m}\\b`).test(pyLine[1]));
        for (const model of referenced) {
          checked.push(`${className}.${field}`);
          expect(
            tsFields.get(field),
            `${className}.${field} is \`${pyLine[1].trim()}\` in Python, so its `
            + `TypeScript annotation must name ${model}`,
          ).toContain(model);
        }
      }
    }

    // The loop above silently skips any field whose Python annotation names no
    // mirrored model, so with a broken extractor it would check NOTHING and pass.
    // These three composite fields are the ones that must always be reached.
    expect(checked.sort()).toEqual([
      'DeckSpec.design_contract',
      'DeckSpec.resolved_data',
      'DeckSpec.slides',
      'ResolvedData.figures',
    ]);
  });
});

describe('DeckSpec conformance — the read-path key', () => {
  it('SlideDeck declares exactly one DeckSpec field, and the server emits that key', () => {
    const slideDeckFields = tsInterfaceFields(slideTs, 'SlideDeck');
    const specFields = [...slideDeckFields.entries()]
      .filter(([, annotation]) => /\bDeckSpec\b/.test(annotation))
      .map(([field]) => field);

    expect(specFields, 'SlideDeck must declare exactly one DeckSpec-typed field').toHaveLength(1);

    const [field] = specFields;
    // The key the server actually puts in the deck dict, in either of the two
    // forms the read paths use (a literal in the dict, or an assignment onto it).
    // A rename on either side breaks this — which is the drift being guarded.
    const emitted = new RegExp(
      `(?:"${field}":\\s*_read_deck_spec\\()|(?:\\["${field}"\\]\\s*=\\s*_read_deck_spec\\()`,
    );
    expect(
      emitted.test(sessionManagerPy),
      `SlideDeck.${field} is the declared field name, but no read path in `
      + `session_manager.py emits a "${field}" key from _read_deck_spec(). One side `
      + 'has been renamed; the frontend would read undefined.',
    ).toBe(true);
  });
});
