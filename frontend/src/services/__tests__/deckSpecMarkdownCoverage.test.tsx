/**
 * deckSpecMarkdownCoverage -- a deck-spec field cannot be added and silently left out of the
 * Markdown export (#318, plan Task 4; Decisions D2 and D3).
 *
 * Guard (a), field classification + mutation. src/domain/deck_spec.py is read as TEXT with the
 * shared Pydantic-source reader (the one deckSpecConformance.test.ts uses, so both guards parse the
 * models identically). COVERAGE must classify every model and every field as 'rendered' or
 * { excluded: reason }. Then, for every leaf field and EVERY instance of its model in the golden
 * spec, a deep clone is mutated -- the mutation is chosen from the PYTHON annotation, not from the
 * TS type -- and rendered:
 *   - a 'rendered' field must change the output, and a string mutation must reach the parsed text;
 *   - an excluded field must leave the output byte-identical.
 * So a new Python field is red until it is classified, a field marked 'rendered' that the renderer
 * ignores is red, and starting to render an excluded field is red. An annotation with no mutation
 * rule -- including one the source reader garbles (a default containing `=`, a trailing comment, a
 * multi-line annotation) -- throws "extend this guard": the guard fails closed, never guesses.
 *
 * Guard (b), Spec-view parity. <SpecView> and the renderer get the SAME spec. Every piece of text
 * the view shows outside its header (spec-view-header holds controls, not spec content) must appear,
 * letter/number-bounded, in a heading or paragraph of the PARSED Markdown. Nothing is picked by
 * data-testid, so anything added to the view -- a value, a label, an empty-state sentence -- is red
 * until the export carries it.
 *
 * Sabotage targets (each run and seen red):
 *   (a) stop emitting the `Data references` line         -> SlideSpec.data_references
 *       start emitting template_section_index            -> SlideSpec.template_section_index (excluded)
 *       emit `Slide type` only for slides[0]             -> SlideSpec.slide_type, instance 1
 *       add `notes: str` to SlideSpec in deck_spec.py    -> SlideSpec: COVERAGE lists exactly the Python fields
 *   (b) rename the renderer's `## Narrative arc`         -> every fixture
 *       reword `No design system or slide style pinned`  -> EMPTY
 *       render slide.template_section_index in SpecView  -> GOLDEN (via `12`)
 * Showing slide_type or resolved_data.synthesis in SpecView stays GREEN: the export carries both,
 * which is what shows that (b) compares content, not structure.
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import deckSpecPy from '../../../../src/domain/deck_spec.py?raw';
import goldenSpecJson from '../../../tests/fixtures/deck-spec-markdown/full.deck-spec.json?raw';
import { SpecView } from '../../components/SpecView/SpecView';
import { blockTexts, normaliseText, parseMarkdown, plainText } from '../../test/markdownStructure';
import {
  pythonModelClasses,
  pythonModelFieldAnnotations,
  pythonModelFields,
} from '../../test/pydanticSource';
import type { DeckSpec, SlideDeck } from '../../types/slide';
import { renderDeckSpecMarkdown } from '../deckSpecMarkdown';

// -- fixtures ------------------------------------------------------------------------------------

const GOLDEN: DeckSpec = JSON.parse(goldenSpecJson);
const GOLDEN_JSON = JSON.stringify(GOLDEN);
/** A fresh deep copy of the golden input. Tests mutate copies, never GOLDEN. */
const golden = (): DeckSpec => structuredClone(GOLDEN);
const BASELINE = renderDeckSpecMarkdown(GOLDEN);

// -- (a) the classification ----------------------------------------------------------------------

type Coverage = 'rendered' | { excluded: string };

/** Every model, every field: rendered, or excluded with the reason (D2). */
const COVERAGE: Record<string, Record<string, Coverage>> = {
  DeckSpec: {
    title: 'rendered',
    audience: 'rendered',
    purpose: 'rendered',
    argument: 'rendered',
    call_to_action: 'rendered',
    narrative_arc: 'rendered',
    design_contract: 'rendered',
    resolved_data: 'rendered',
    slides: 'rendered',
  },
  SlideSpec: {
    position: 'rendered',
    purpose: 'rendered',
    content_brief: 'rendered',
    assumes: 'rendered',
    hands_off: 'rendered',
    data_references: 'rendered',
    slide_type: 'rendered',
    template_section_index: {
      excluded: 'Machine binding index into the pinned template; slide_type names the same binding '
        + 'by its data-label and the pair is validated together (invalid_slide_bindings). A 0-based index next to a 1-based '
        + '"Slide N" heading misleads a reader.',
    },
  },
  DesignContractRef: { design_system_id: 'rendered', template_id: 'rendered', slide_style_id: 'rendered' },
  ResolvedData: { synthesis: 'rendered', figures: 'rendered', gaps: 'rendered' },
  ResolvedFigure: { key: 'rendered', value: 'rendered', source: 'rendered' },
};

/** Where each model's instances live in a spec. Every instance is mutated, one at a time. */
const INSTANCES: Record<string, (s: DeckSpec) => object[]> = {
  DeckSpec: (s) => [s],
  SlideSpec: (s) => s.slides,
  DesignContractRef: (s) => [s.design_contract],
  ResolvedData: (s) => [s.resolved_data],
  ResolvedFigure: (s) => s.resolved_data.figures,
};

const ROOT_MODEL = 'DeckSpec';
const SENTINEL = 'ZQXMUTSENTINEL';
const MUTATED_INT = 900000;

type Kind = 'str' | 'int' | 'list[str]' | 'list[model]' | 'model';
type LeafKind = Exclude<Kind, 'model'>;
type Instance = Record<string, unknown>;

/** The mutation rule for a Python annotation. Anything without a rule throws: the guard fails closed. */
function kindOf(annotation: string, models: readonly string[]): Kind {
  const inner = annotation.replace(/^Optional\[(.*)\]$/, '$1');
  if (inner === 'str') return 'str';
  if (inner === 'int') return 'int';
  if (inner === 'list[str]') return 'list[str]';
  const listOf = /^list\[(\w+)\]$/.exec(inner);
  if (listOf && models.includes(listOf[1])) return 'list[model]';
  if (models.includes(inner)) return 'model';
  throw new Error(`deck_spec.py annotation "${annotation}" has no mutation rule -- extend this guard`);
}

/** The model named by a 'model' or 'list[model]' annotation. */
function modelOf(annotation: string): string {
  return annotation.replace(/^Optional\[(.*)\]$/, '$1').replace(/^list\[(\w+)\]$/, '$1');
}

const MODELS = pythonModelClasses(deckSpecPy);
const ANNOTATIONS: Record<string, Map<string, string>> = Object.fromEntries(
  MODELS.map((model) => [model, pythonModelFieldAnnotations(deckSpecPy, model)]),
);

/** kindOf, but never throwing at collection time: an unknown annotation must fail a TEST, not hide one. */
function kindOrUnknown(annotation: string): Kind | 'unknown' {
  try {
    return kindOf(annotation, MODELS);
  } catch {
    return 'unknown';
  }
}

const FIELDS = MODELS.flatMap((model) =>
  [...ANNOTATIONS[model]].map(([field, annotation]) => ({ model, field, annotation })));
/** Every field that is not a bare model -- including an unknown annotation, whose test then throws. */
const LEAVES: Array<[string, string]> = FIELDS
  .filter((f) => kindOrUnknown(f.annotation) !== 'model')
  .map((f) => [f.model, f.field]);
const BARE_MODEL_FIELDS: Array<[string, string, string]> = FIELDS
  .filter((f) => kindOrUnknown(f.annotation) === 'model')
  .map((f) => [f.model, f.field, modelOf(f.annotation)]);

function mutate(target: Instance, field: string, kind: LeafKind): void {
  if (kind === 'str') target[field] = SENTINEL;
  else if (kind === 'int') target[field] = MUTATED_INT;
  else if (kind === 'list[str]') target[field] = [...(target[field] as string[]), SENTINEL];
  else target[field] = [];
}

/** Every model instance in a spec, found by walking the Python annotations from the root. */
function instancesByWalking(spec: DeckSpec): Record<string, object[]> {
  const found: Record<string, object[]> = Object.fromEntries(MODELS.map((model) => [model, [] as object[]]));
  const visit = (model: string, obj: Instance): void => {
    found[model].push(obj);
    for (const [field, annotation] of ANNOTATIONS[model]) {
      const kind = kindOf(annotation, MODELS);
      if (kind === 'model') visit(modelOf(annotation), obj[field] as Instance);
      else if (kind === 'list[model]') for (const item of obj[field] as Instance[]) visit(modelOf(annotation), item);
    }
  };
  visit(ROOT_MODEL, spec as unknown as Instance);
  return found;
}

const isExcluded = (c: Coverage | undefined): c is { excluded: string } =>
  typeof c === 'object' && c !== null && typeof c.excluded === 'string';

describe('guard (a): every deck_spec.py field is classified and behaves as classified', () => {
  it('precondition: the Python models were read at all', () => {
    expect(MODELS.length).toBeGreaterThan(0);
    expect(MODELS).toContain(ROOT_MODEL);
    // A class that is not a direct BaseModel subclass is invisible to pythonModelClasses, and so to
    // both guards. Refuse it rather than let a model escape classification.
    const everyClass = [...deckSpecPy.replace(/"""[\s\S]*?"""/g, '').matchAll(/^class (\w+)/gm)].map((m) => m[1]);
    expect(
      everyClass.filter((name) => !MODELS.includes(name)),
      'pythonModelClasses (src/test/pydanticSource.ts) reads only `class X(BaseModel):`, so these deck_spec.py classes '
        + 'escape both guards. Make each a direct BaseModel subclass, move a non-model helper (an Enum, a mixin) out of '
        + 'deck_spec.py, or teach pythonModelClasses and kindOf about it',
    ).toEqual([]);
  });

  it('precondition: the sentinel is absent from the golden rendering', () => {
    expect(BASELINE).not.toContain(SENTINEL);
    expect(GOLDEN_JSON).not.toContain(SENTINEL);
  });

  it('every model is classified and has an instance accessor', () => {
    const sorted = [...MODELS].sort();
    expect(Object.keys(COVERAGE).sort()).toEqual(sorted);
    expect(Object.keys(INSTANCES).sort()).toEqual(sorted);
  });

  it.each(MODELS)('%s: COVERAGE lists exactly the Python fields', (model) => {
    const python = pythonModelFields(deckSpecPy, model);
    expect(
      [...ANNOTATIONS[model].keys()],
      'the annotation reader and the field reader disagree (src/test/pydanticSource.ts)',
    ).toEqual(python);
    const classified = Object.keys(COVERAGE[model] ?? {});
    expect(
      {
        unclassified: python.filter((field) => !classified.includes(field)),
        stale: classified.filter((field) => !python.includes(field)),
      },
      `${model}: classify each unclassified field as 'rendered' or { excluded: reason }, and delete each stale one`,
    ).toEqual({ unclassified: [], stale: [] });
  });

  it('every excluded field states a reason', () => {
    const bad = Object.entries(COVERAGE).flatMap(([model, fields]) =>
      Object.entries(fields)
        .filter(([, c]) => c !== 'rendered' && !(isExcluded(c) && c.excluded.trim().length >= 20))
        .map(([field]) => `${model}.${field}`));
    expect(bad, "each must be 'rendered' or { excluded: '<a reason of 20+ characters>' }").toEqual([]);
  });

  it('every deck_spec.py annotation has a mutation rule', () => {
    const refused = FIELDS
      .filter((f) => kindOrUnknown(f.annotation) === 'unknown')
      .map((f) => `${f.model}.${f.field}: ${f.annotation}`);
    expect(refused, 'extend kindOf and mutate for these annotations').toEqual([]);
  });

  it.each(MODELS)('%s: every fixture instance carries every field as an own key', (model) => {
    const accessor = INSTANCES[model];
    expect(accessor, `${model} has no INSTANCES accessor`).toBeDefined();
    const instances = accessor(GOLDEN);
    expect(instances.length, `the golden fixture has no ${model} instance to mutate`).toBeGreaterThan(0);
    const missing = instances.flatMap((instance, i) =>
      [...ANNOTATIONS[model].keys()]
        .filter((field) => !Object.prototype.hasOwnProperty.call(instance, field))
        .map((field) => `instance ${i}: ${field}`));
    expect(missing, 'spell every field out in full.deck-spec.json (optional ones as null)').toEqual([]);
  });

  it('INSTANCES reaches exactly the objects the spec holds, model by model', () => {
    const spec = golden();
    const walked = instancesByWalking(spec);
    for (const model of MODELS) {
      const listed = INSTANCES[model]?.(spec) ?? [];
      expect(listed.length, `${model}: INSTANCES lists a different number of instances than the spec holds`)
        .toBe(walked[model].length);
      listed.forEach((obj, i) => {
        expect(obj === walked[model][i], `${model}[${i}] is not the object the spec holds`).toBe(true);
      });
    }
  });

  it.each(LEAVES)('%s.%s behaves as classified', (model, field) => {
    const kind = kindOf(ANNOTATIONS[model].get(field) ?? '', MODELS);
    expect(kind).not.toBe('model');
    const coverage = COVERAGE[model]?.[field];
    expect(coverage, `${model}.${field} is not in COVERAGE`).toBeDefined();
    const count = INSTANCES[model](GOLDEN).length;
    expect(count, `the golden fixture has no ${model} instance`).toBeGreaterThan(0);

    const failures: string[] = [];
    for (let i = 0; i < count; i += 1) {
      const spec = golden();
      mutate(INSTANCES[model](spec)[i] as Instance, field, kind as LeafKind);
      if (JSON.stringify(spec) === GOLDEN_JSON) {
        failures.push(`instance ${i}: the ${kind} mutation was a no-op`);
        continue;
      }
      const out = renderDeckSpecMarkdown(spec);
      if (coverage === 'rendered') {
        if (out === BASELINE) {
          failures.push(`instance ${i}: classified 'rendered', but mutating it left the output unchanged`);
        } else if ((kind === 'str' || kind === 'list[str]') && !plainText(parseMarkdown(out)).includes(SENTINEL)) {
          failures.push(`instance ${i}: the output changed, but the parsed text does not contain the mutated value`);
        }
      } else if (out !== BASELINE) {
        failures.push(`instance ${i}: classified excluded, but mutating it changed the output`);
      }
    }
    expect(failures).toEqual([]);
  });

  it('precondition: the bare-model fields were found', () => {
    expect(BARE_MODEL_FIELDS.map(([model, field]) => `${model}.${field}`))
      .toEqual(expect.arrayContaining(['DeckSpec.design_contract', 'DeckSpec.resolved_data']));
  });

  it.each(BARE_MODEL_FIELDS)('%s.%s is rendered iff its model %s renders something', (model, field, child) => {
    expect(COVERAGE[child], `${child} is not in COVERAGE`).toBeDefined();
    const childRenders = Object.values(COVERAGE[child]).some((c) => c === 'rendered');
    expect(COVERAGE[model]?.[field] === 'rendered').toBe(childRenders);
  });

  describe('an annotation the guard cannot mutate faithfully throws (fails closed)', () => {
    /**
     * Lines pythonModelFieldAnnotations either garbles (its `[^=]+?` stops at the first `=`, keeps a
     * trailing comment, and sees one line of a multi-line annotation) or reads faithfully but which
     * have no mutation rule. For each: the true annotation, and its kind (null = no rule).
     */
    const PROBE_SOURCE = [
      'class Probe(BaseModel):',
      '    annotated: Annotated[str, Field(description="x")]',
      '    annotated_int: Annotated[int, Field(ge=0)]',
      '    literal: Literal["a=b"]',
      '    commented: str  # a trailing comment',
      '    commented_after_default: Optional[str] = None  # a trailing comment',
      '    wrapped: Optional[',
      '        str',
      '    ] = None',
      '    forward_ref: "SlideSpec"',
      '    union: int | None = None',
      '    typing_list: List[str]',
      '    mapping: dict[str, int]',
      '    real: float',
      '    defaulted: Optional[str] = Field(default="a=b")',
      '    optional_list: Optional[list[str]] = None',
      '',
    ].join('\n');
    const PROBES: Array<[string, string, Kind | null]> = [
      ['annotated', 'Annotated[str, Field(description="x")]', null],
      ['annotated_int', 'Annotated[int, Field(ge=0)]', null],
      ['literal', 'Literal["a=b"]', null],
      ['commented', 'str', 'str'],
      ['commented_after_default', 'Optional[str]', 'str'],
      ['wrapped', 'Optional[str]', 'str'],
      ['forward_ref', '"SlideSpec"', null],
      ['union', 'int | None', null],
      ['typing_list', 'List[str]', null],
      ['mapping', 'dict[str, int]', null],
      ['real', 'float', null],
      ['defaulted', 'Optional[str]', 'str'],
      ['optional_list', 'Optional[list[str]]', 'list[str]'],
    ];
    const read = pythonModelFieldAnnotations(PROBE_SOURCE, 'Probe');

    it('precondition: the reader saw every probe line', () => {
      expect([...read.keys()]).toEqual(PROBES.map(([field]) => field));
    });

    it.each(PROBES)('%s: classified correctly, or refused', (field, actual, kind) => {
      const annotation = read.get(field) ?? '';
      if (annotation === actual && kind !== null) {
        expect(kindOf(annotation, MODELS)).toBe(kind);
      } else {
        expect(() => kindOf(annotation, MODELS)).toThrow(/has no mutation rule -- extend this guard/);
      }
    });
  });
});

// -- (b) Spec-view parity ------------------------------------------------------------------------

/** All ids null; narrative arc, slides, figures and gaps empty; every scalar non-empty. */
const EMPTY: DeckSpec = {
  title: 'A plan with nothing in it yet',
  audience: 'Whoever opens an empty plan.',
  purpose: 'Show that every empty section still says something.',
  argument: 'An empty list is a statement too.',
  call_to_action: 'Fill the plan in.',
  narrative_arc: [],
  design_contract: { design_system_id: null, template_id: null, slide_style_id: null },
  resolved_data: { synthesis: 'Nothing has been resolved yet.', figures: [], gaps: [] },
  slides: [],
};
const SLIDE_STYLE: DeckSpec = {
  ...golden(),
  design_contract: { design_system_id: null, template_id: null, slide_style_id: 5 },
};
const FIXTURES: Array<[string, DeckSpec]> = [['GOLDEN', GOLDEN], ['EMPTY', EMPTY], ['SLIDE_STYLE', SLIDE_STYLE]];

/** Texts the collector must see, per fixture, so a broken collector cannot pass vacuously. */
const MUST_SEE: Record<string, string[]> = {
  GOLDEN: [normaliseText(GOLDEN.audience), 'Slide 4', 'Design system #7', 'Narrative arc', 'Assumes:', 'Hands off:'],
  EMPTY: [EMPTY.audience, 'Narrative arc', 'No design system or slide style pinned'],
  SLIDE_STYLE: ['Slide style #5', 'Slide 4'],
};

const deckOf = (spec: DeckSpec): SlideDeck => ({
  title: 'Deck title differs from the spec title',
  slide_count: 0,
  css: '',
  external_scripts: [],
  scripts: '',
  slides: [],
  deck_spec: spec,
});

/**
 * Every piece of text the Spec view shows, outside its header: each element with no element
 * children gives its textContent, and each element with element children gives its direct text
 * nodes. Normalised with the test-side normaliseText (D4's sets, restated independently).
 */
function specViewTexts(container: HTMLElement): string[] {
  const view = container.querySelector('[data-testid="spec-view"]');
  const header = view?.querySelector('[data-testid="spec-view-header"]');
  if (!view || !header) throw new Error('SpecView no longer renders spec-view / spec-view-header -- fix this collector');
  const out: string[] = [];
  for (const el of [view, ...Array.from(view.querySelectorAll('*'))]) {
    if (header.contains(el)) continue;
    if (el.children.length === 0) {
      out.push(normaliseText(el.textContent ?? ''));
    } else {
      for (const n of Array.from(el.childNodes)) {
        if (n.nodeType === Node.TEXT_NODE) out.push(normaliseText(n.textContent ?? ''));
      }
    }
  }
  return out.filter((t) => t !== '');
}

function specViewTextsOf(spec: DeckSpec): string[] {
  const { container, unmount } = render(<SpecView slideDeck={deckOf(spec)} onDiscuss={() => undefined} />);
  const texts = specViewTexts(container);
  unmount();
  return texts;
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const appearsIn = (needle: string, hay: string[]) =>
  hay.some((h) => new RegExp(`(?<![\\p{L}\\p{N}])${escapeRe(needle)}(?![\\p{L}\\p{N}])`, 'u').test(h));

describe('guard (b): every piece of text the Spec view shows is in the Markdown', () => {
  // Today every SpecView text outside the header sits in a leaf element ("Assumes: " is its own
  // <span>), so no fixture exercises the mixed-content branch and MUST_SEE cannot pin it. A later
  // `<p>Assumes: <span>{x}</span></p>` would rely on that branch, so pin it on a synthetic DOM.
  it('precondition: the collector reads leaves and mixed-content text, and skips the header', () => {
    const { container, unmount } = render(
      <section data-testid="spec-view">
        <header data-testid="spec-view-header"><h2>Header heading</h2>Header text</header>
        <p>Mixed label: <span>leaf value</span> trailing words</p>
        <div><span>first</span><span>second</span></div>
      </section>,
    );
    const texts = specViewTexts(container);
    unmount();
    expect(texts).toEqual(['Mixed label:', 'trailing words', 'leaf value', 'first', 'second']);
  });

  it.each(FIXTURES)('precondition: the collector sees the populated %s spec', (name, spec) => {
    const texts = specViewTextsOf(spec);
    expect(texts).toEqual(expect.arrayContaining(MUST_SEE[name]));
  });

  it.each(FIXTURES)('%s: every piece of text the Spec view shows appears in the Markdown', (_name, spec) => {
    const texts = specViewTextsOf(spec);
    const markdown = blockTexts(parseMarkdown(renderDeckSpecMarkdown(spec)));
    expect(texts.filter((t) => !appearsIn(t, markdown)), 'shown in the Spec view but missing from the export').toEqual([]);
  });
});
