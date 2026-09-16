/**
 * SpecView — component tests for E1's test-intent table.
 *
 * Sabotage targets, one per group, all in SpecView.tsx:
 *   - deck-level fields        : drop a <SpecField /> row
 *   - narrative arc order      : `[...spec.narrative_arc].reverse()` (or .sort())
 *   - per-slide contract       : drop the assumes/hands-off pair
 *   - read-only is structural  : add an <input /> or contentEditable node
 *   - Discuss offered          : remove the spec-discuss Button
 *   - Discuss is the write path: make onClick a no-op
 *   - empty state              : `spec = slideDeck!.deck_spec` (crash on null)
 *   - design contract ids      : stop rendering the ids
 *   - NO compiled style content: render {slideDeck.css}
 *
 * THE LAST ONE IS FINDING 18b's RESHAPED ASSERTION, and the reason it is shaped
 * this way is worth keeping.  The plan asked for "the design contract shows which
 * brand (ids), never compiled style content".  `DesignContractRef` holds THREE
 * INTEGERS — there is no compiled style content in the object, so an assertion
 * that the component does not leak it cannot fail whatever the component does.
 * Five assertions of that shape have already been paid for on this branch.
 *
 * What replaces it is falsifiable: the fixture deck carries REAL compiled style
 * content in `slideDeck.css` (the thing design_system_id 7 / template_id 3 resolve
 * to on the server), SpecView takes the whole deck so that content is in scope,
 * and the assertion is that no CSS-shaped text reaches the rendered output.
 * Widening the component to render the resolved style turns it red.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { SpecView } from './SpecView';
import type { DeckSpec, SlideDeck, SlideSpec } from '../../types/slide';

// ── fixtures ──────────────────────────────────────────────────────────────────

/**
 * Compiled style content — what design system #7 / template #3 resolve to.
 *
 * Carries all four CSS shapes the assertion looks for on purpose: a custom
 * property reference (`var(--`), a `{…}` rule body, an `@media` block and an
 * `@font-face` block.  A fixture missing any of them would make the
 * corresponding half of the no-CSS assertion unfalsifiable, so
 * `the fixture genuinely carries compiled style content` below pins it.
 */
const COMPILED_DECK_CSS = [
  ":root { --brand-primary: #FF3621; --brand-body: 'Brand Sans'; }",
  '@font-face { font-family: \'Brand Sans\'; src: url(/assets/brand.woff2); }',
  '.slide h1 { color: var(--brand-primary); font-family: var(--brand-body); }',
  '@media (min-width: 900px) { .slide { padding: 64px; } }',
].join('\n');

/**
 * Narrative arc beats chosen so that a reversal AND an alphabetical sort both
 * differ from the given order — an order assertion that a sort would satisfy is
 * not an order assertion.
 */
const ARC = [
  'Frame the problem: renewals are slipping and nobody can say which accounts.',
  'Argue the cause: the signal exists but arrives after the renewal date.',
  'Close on the ask: fund the early-warning pipeline this quarter.',
];

/**
 * Slide positions 0 and 2, NOT 0 and 1.  `position` is the slide's canonical
 * identity and diverges from list index after a delete, so a component keyed or
 * labelled by index would render "Slide 2" for position 2 and be caught here.
 */
function makeSpec(overrides: Partial<DeckSpec> = {}): DeckSpec {
  return {
    title: 'Renewal risk, Q3',
    audience: 'The regional sales leadership team, who own the renewal number.',
    purpose: 'Get the early-warning pipeline funded before the Q4 renewal wave.',
    argument: 'Churn is predictable a quarter ahead, and today nobody looks.',
    call_to_action: 'Approve two engineers for one quarter to build the pipeline.',
    narrative_arc: [...ARC],
    design_contract: { design_system_id: 7, template_id: 3, slide_style_id: null },
    resolved_data: {
      synthesis: 'Three quarters of churn history, aggregated by region.',
      figures: [{ key: 'churn_rate', value: '11.4%', source: 'warehouse.renewals' }],
      gaps: ['No data before FY23.'],
    },
    slides: [
      {
        position: 0,
        purpose: 'Open on the number nobody can explain.',
        content_brief: 'Title slide: the headline churn rate and the quarter it lands in.',
        assumes: 'Nothing. This is the first slide.',
        hands_off: 'The reader knows the number and wants to know why.',
        data_references: ['churn_rate'],
        template_section_index: 0,
      },
      {
        position: 2,
        purpose: 'Land the ask while the cause is still fresh.',
        content_brief: 'Closing slide: the two-engineer ask, scoped to one quarter.',
        assumes: 'The reader accepts that the signal arrives too late today.',
        hands_off: 'The deck ends on a decision the reader can make in the room.',
        data_references: [],
        template_section_index: 2,
      },
    ],
    ...overrides,
  };
}

/**
 * One brief at an arbitrary position, for the ordering test.
 *
 * Positions need not be contiguous or list-ordered: `position` is the slide's
 * canonical identity and diverges from list index after a delete or a partial
 * rebuild, which is why `DeckSpec.slide_at` looks up by the field and never by index.
 */
function makeSlide(position: number): SlideSpec {
  return {
    position,
    purpose: `Purpose of the brief at position ${position}.`,
    content_brief: `Content brief for position ${position}.`,
    assumes: `What position ${position} inherits.`,
    hands_off: `What position ${position} leaves the reader.`,
    data_references: [],
    template_section_index: null,
  };
}

function makeDeck(deckSpec: DeckSpec | null | undefined): SlideDeck {
  const deck: SlideDeck = {
    title: 'Renewal risk, Q3',
    slide_count: 2,
    css: COMPILED_DECK_CSS,
    external_scripts: [],
    scripts: '',
    slides: [],
  };
  if (deckSpec !== undefined) deck.deck_spec = deckSpec;
  return deck;
}

const noop = () => undefined;

function renderSpec(deckSpec: DeckSpec | null | undefined, onDiscuss = noop) {
  return render(<SpecView slideDeck={makeDeck(deckSpec)} onDiscuss={onDiscuss} />);
}

// ── deck-level fields ─────────────────────────────────────────────────────────

describe('SpecView — deck-level fields', () => {
  it('renders audience, purpose, argument and call to action', () => {
    const spec = makeSpec();
    renderSpec(spec);

    expect(screen.getByTestId('spec-audience')).toHaveTextContent(spec.audience);
    expect(screen.getByTestId('spec-purpose')).toHaveTextContent(spec.purpose);
    expect(screen.getByTestId('spec-argument')).toHaveTextContent(spec.argument);
    expect(screen.getByTestId('spec-call-to-action')).toHaveTextContent(spec.call_to_action);
  });
});

// ── narrative arc ─────────────────────────────────────────────────────────────

describe('SpecView — narrative arc', () => {
  it('renders the arc in the order the spec gives, not sorted or reversed', () => {
    renderSpec(makeSpec());

    // getAllByTestId returns document order, and toEqual on arrays is
    // order-sensitive — a set comparison here would accept any permutation,
    // which is the whole defect this asserts against.
    const rendered = screen
      .getAllByTestId(/^spec-arc-beat-/)
      .map((li) => li.textContent);

    expect(rendered).toEqual(ARC);
  });
});

// ── per-slide briefs ──────────────────────────────────────────────────────────

describe('SpecView — per-slide briefs', () => {
  it('renders every slide brief with its assumes / hands-off contract', () => {
    const spec = makeSpec();
    renderSpec(spec);

    for (const slide of spec.slides) {
      expect(screen.getByTestId(`spec-slide-purpose-${slide.position}`))
        .toHaveTextContent(slide.purpose);
      expect(screen.getByTestId(`spec-slide-brief-${slide.position}`))
        .toHaveTextContent(slide.content_brief);
      expect(screen.getByTestId(`spec-slide-assumes-${slide.position}`))
        .toHaveTextContent(slide.assumes);
      expect(screen.getByTestId(`spec-slide-hands-off-${slide.position}`))
        .toHaveTextContent(slide.hands_off);
    }
  });

  it('labels a brief by its position, not its list index', () => {
    // Positions are 0 and 2 (a delete happened), so the second brief is
    // "Slide 3".  A component labelling by list index would say "Slide 2".
    renderSpec(makeSpec());
    expect(screen.getByTestId('spec-slide-2')).toHaveTextContent('Slide 3');
  });

  it('renders the briefs in the order the spec gives, not reversed or re-sorted', () => {
    // ORDER IS MEANING HERE TOO — the same reason the narrative arc's order is
    // asserted. The briefs are that arc made concrete, and a reversed list renders
    // "Slide 6, Slide 3, Slide 1" to the reader.
    //
    // Every other per-slide assertion in this file is keyed by `position` and
    // reads a label of `position + 1`, so expected and actual move together and a
    // reversal is invisible to all of them. Measured: reversing the render order
    // left 42/42 vitest and 18/18 e2e green.
    //
    // THE INVOLUTION TRAP (§29). The fixture is deliberately NOT symmetric:
    // positions 0, 2, 5 with three entries, so a reversal is not its own inverse
    // and a rotation does not reproduce it either. Asserting the SEQUENCE as
    // rendered — not the set — is what makes that reachable.
    renderSpec(makeSpec({ slides: [makeSlide(0), makeSlide(2), makeSlide(5)] }));

    const rendered = screen
      .getAllByTestId(/^spec-slide-\d+$/)
      .map((li) => li.dataset.testid);

    expect(rendered).toEqual(['spec-slide-0', 'spec-slide-2', 'spec-slide-5']);
  });
});

// ── the rendered spec FOLLOWS the deck ────────────────────────────────────────
//
// This is the feature's central loop and it had no guard. The spec is read-only,
// so the ONLY way it ever changes is a chat turn replacing the deck: the user asks
// the architect to tighten the arc, the deck comes back, and the open spec pane
// must show the new plan. A component that renders the spec once and then never
// follows the deck fails at exactly that, silently — the pane keeps showing a plan
// the deck no longer has.
//
// Sabotage target: derive `spec` from anything other than the current props —
// `useState(slideDeck?.deck_spec ?? null)` (captured on mount), or a `useRef` that
// latches the first NON-null spec and ignores every later one. The second is the
// realistic staleness: the pane mounts before the deck arrives, so a mount-capture
// latches `null` and is caught by half the suite, while a first-non-null latch left
// 42/42 vitest and 18/18 e2e green. Both are caught here, because the sequence
// below starts at null and then changes TWICE.

describe('SpecView — the rendered spec follows the deck', () => {
  /** The spec after a later chat turn: the architect narrowed the audience. */
  const REVISED_AUDIENCE =
    'The board only — the regional leads were briefed separately on the second turn.';

  it('follows the deck through null, then a spec, then a revised spec', () => {
    const first = makeSpec();
    const { rerender } = render(<SpecView slideDeck={makeDeck(null)} onDiscuss={noop} />);
    // Phase 1 — the pane mounts before the deck arrives. Production order.
    expect(screen.getByTestId('spec-view-empty')).toBeInTheDocument();

    // Phase 2 — the first spec lands.
    rerender(<SpecView slideDeck={makeDeck(first)} onDiscuss={noop} />);
    expect(screen.getByTestId('spec-audience')).toHaveTextContent(first.audience);

    // Phase 3 — a later turn revises it. THIS is the change a first-non-null latch
    // swallows, and the one nothing asserted before.
    const revised = makeSpec({ audience: REVISED_AUDIENCE });
    rerender(<SpecView slideDeck={makeDeck(revised)} onDiscuss={noop} />);

    expect(screen.getByTestId('spec-audience')).toHaveTextContent(REVISED_AUDIENCE);
    // And the superseded value is GONE, not merely joined by the new one — a
    // component that appended rather than replaced would satisfy the line above.
    expect(screen.queryByText(first.audience)).not.toBeInTheDocument();
  });

  it('replaces the narrative arc and the slide briefs when the spec is revised', () => {
    // A DISTINCT SECTION from the test above, on purpose: a partial staleness that
    // froze only the list-rendered sections (arc, briefs) while the deck-level
    // fields still tracked would pass the audience test and fail here.
    const first = makeSpec();
    const { rerender } = render(<SpecView slideDeck={makeDeck(first)} onDiscuss={noop} />);
    expect(screen.getByTestId('spec-slide-2')).toBeInTheDocument();

    const revisedArc = ['One beat only, after the architect collapsed the middle.'];
    rerender(
      <SpecView
        slideDeck={makeDeck(makeSpec({ narrative_arc: revisedArc, slides: [makeSlide(0)] }))}
        onDiscuss={noop}
      />,
    );

    expect(
      screen.getAllByTestId(/^spec-arc-beat-/).map((li) => li.textContent),
    ).toEqual(revisedArc);
    // The brief the revised spec dropped is gone, so this is not passing because
    // the new content was appended alongside the old.
    expect(screen.queryByTestId('spec-slide-2')).not.toBeInTheDocument();
    expect(screen.getByTestId('spec-slide-0')).toBeInTheDocument();
  });
});

// ── read-only is a structural property, not a styling one ─────────────────────

describe('SpecView — read-only is structural', () => {
  it('renders no input, textarea or contenteditable anywhere in the spec view', () => {
    const { container } = renderSpec(makeSpec());

    // PRECONDITION, not a second subject: an absence assertion over an empty
    // subtree passes for the wrong reason.  If this fires the test is RED, so it
    // cannot manufacture a false pass — it only rules one out.
    expect(container.querySelectorAll('[data-testid^="spec-slide-"]').length)
      .toBeGreaterThan(0);

    const editable = container.querySelectorAll(
      'input, textarea, select, [contenteditable], [contentEditable]',
    );
    expect(Array.from(editable).map((el) => el.outerHTML)).toEqual([]);
  });
});

// ── Discuss — offered, and the only write path ────────────────────────────────

describe('SpecView — Discuss', () => {
  it('offers Discuss', () => {
    renderSpec(makeSpec());
    expect(screen.getByTestId('spec-discuss')).toBeInTheDocument();
  });

  it('hands off to the conversation when Discuss is clicked', () => {
    const onDiscuss = vi.fn();
    renderSpec(makeSpec(), onDiscuss);

    fireEvent.click(screen.getByTestId('spec-discuss'));

    expect(onDiscuss).toHaveBeenCalledTimes(1);
  });
});

// ── empty state ───────────────────────────────────────────────────────────────

describe('SpecView — specless decks', () => {
  it('renders the empty state when deck_spec is null (a specless deck)', () => {
    renderSpec(null);
    expect(screen.getByTestId('spec-view-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('spec-deck-fields')).not.toBeInTheDocument();
  });

  it('renders the empty state when deck_spec is absent (a client-side deck)', () => {
    renderSpec(undefined);
    expect(screen.getByTestId('spec-view-empty')).toBeInTheDocument();
  });

  it('renders the empty state when there is no deck at all', () => {
    render(<SpecView slideDeck={null} onDiscuss={noop} />);
    expect(screen.getByTestId('spec-view-empty')).toBeInTheDocument();
  });

  it('still offers Discuss on a specless deck', () => {
    // The whole point of Discuss being the only write path: with no spec, asking
    // for one is the action available, so the affordance must not vanish.
    renderSpec(null);
    expect(screen.getByTestId('spec-discuss')).toBeInTheDocument();
  });
});

// ── design contract: WHICH brand (ids) ────────────────────────────────────────

describe('SpecView — design contract shows which brand', () => {
  it('shows the design-system and template ids', () => {
    renderSpec(makeSpec());
    expect(screen.getByTestId('spec-design-system-id')).toHaveTextContent('7');
    expect(screen.getByTestId('spec-template-id')).toHaveTextContent('3');
  });

  it('says so plainly when no brand is pinned', () => {
    renderSpec(makeSpec({
      design_contract: { design_system_id: null, template_id: null, slide_style_id: null },
    }));
    expect(screen.getByTestId('spec-design-contract-none')).toBeInTheDocument();
  });
});

// ── finding 18b, reshaped: NO compiled style content ──────────────────────────

describe('SpecView — never compiled style content (finding 18b, reshaped)', () => {
  it('the fixture deck genuinely carries compiled style content', () => {
    // Fixture integrity, kept in its OWN test so it can never be the assertion
    // that carries the behavioural one below.  Each of the four shapes must be
    // present in the input, or the matching half of the next test is inert.
    expect(COMPILED_DECK_CSS).toContain('var(--');
    expect(COMPILED_DECK_CSS).toContain('@media');
    expect(COMPILED_DECK_CSS).toContain('@font-face');
    expect(COMPILED_DECK_CSS).toMatch(/\{[^{}]*:[^{}]*\}/);
  });

  it('renders no CSS-shaped text, though the compiled style is in scope', () => {
    const { container } = renderSpec(makeSpec());
    const text = container.textContent ?? '';

    // Precondition: the populated branch rendered (see the read-only test).
    expect(container.querySelectorAll('[data-testid^="spec-slide-"]').length)
      .toBeGreaterThan(0);

    expect(text).not.toContain('var(--');
    expect(text).not.toContain('@media');
    expect(text).not.toContain('@font-face');
    // A `{…}` block containing a colon — i.e. a declaration body.  Reported as a
    // match rather than a boolean so a failure names the leaked text.
    expect(text.match(/\{[^{}]*:[^{}]*\}/)).toBeNull();
  });
});
