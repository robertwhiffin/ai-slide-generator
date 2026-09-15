/**
 * SpecView — the architect's plan for the deck, rendered read-only.
 *
 * Reads `slideDeck.deck_spec` (ws4b's read-path key) — there is no spec endpoint
 * and no spec fetch here.  The deck the viewer already holds carries the spec.
 *
 * THREE PROPERTIES THIS COMPONENT MUST KEEP
 * -----------------------------------------
 * 1. READ-ONLY IS STRUCTURAL, NOT STYLING.  There is no `input`, no `textarea`
 *    and no `contenteditable` anywhere in this subtree, and there must never be
 *    one.  Editing the spec stays conversational so the architect remains its
 *    sole author and there is exactly one write path; a second author racing the
 *    async rebuild loop could silently overwrite the user's edits.  `Discuss`
 *    hands the user to that one write path — the conversation.
 *
 * 2. IDS, NEVER COMPILED STYLE CONTENT (L3).  `design_contract` holds three
 *    integers.  This component takes the WHOLE deck, so `slideDeck.css` — the
 *    compiled content those ids resolve to — is in scope right here.  Rendering
 *    it would be the §L3 violation: the spec stores a reference precisely so a
 *    snapshot cannot go stale against COMPILER_VERSION.  Show *which* brand.
 *    `SpecView.test.tsx` asserts the rendered output contains no CSS-shaped text
 *    (`var(--`, a `{…}` rule body, `@media`, `@font-face`) off a fixture whose
 *    deck genuinely carries all four, so widening this component to render the
 *    resolved style goes red rather than unnoticed.
 *
 * 3. THE VIEW IS A HINT, NEVER A MODE.  Nothing about which panel is open
 *    reaches intent parsing.  This component takes no view state and emits none:
 *    "tighten the arc" edits the spec and "make slide 5 bolder" edits the slide
 *    whichever panel happens to be open.  `SelectionContext` was deleted in ws6
 *    to stop UI state gating intent; do not walk that back.
 */
import type { SlideDeck } from '../../types/slide';
import { Button } from '@/ui/button';

interface SpecViewProps {
  /** The deck whose `deck_spec` is rendered; null before a deck exists. */
  slideDeck: SlideDeck | null;
  /**
   * Hands the user to the conversation — the only write path for the spec.
   * Deliberately takes no argument: this component knows nothing about how the
   * conversation is reached, and sends nothing itself.
   */
  onDiscuss: () => void;
}

/** One deck-level field, as a definition-list row. */
function SpecField({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div className="mb-3">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd data-testid={testId} className="mt-0.5 text-sm text-foreground">
        {value}
      </dd>
    </div>
  );
}

export function SpecView({ slideDeck, onDiscuss }: SpecViewProps) {
  // `deck_spec` is absent on a client-side deck and null on a specless one (and
  // on one whose stored JSON would not parse).  Both render the empty state:
  // pre-cutover decks and MCP-built decks legitimately have no spec, so this is
  // an ordinary state, not an error.
  const spec = slideDeck?.deck_spec ?? null;
  const contract = spec?.design_contract;

  return (
    <section
      data-testid="spec-view"
      aria-label="Deck spec"
      // h-full, because the pane wrapper in AppLayout is a BLOCK (see the comment
      // there): the height comes from the wrapper, not from being a flex item.
      className="flex h-full min-h-0 w-full flex-col"
    >
      {/* ── Spec pane header ────────────────────────────────────────────────
          E2b's "agentic deck review in progress" badge belongs HERE, between
          the heading and the actions on the right.  It is exact, not a
          heuristic: it reads releasedPositions.size against
          slideDeck.deck_spec.slides.length (the DeckSpec mirror in
          types/slide.ts) and the turn-complete flag.  E1 deliberately does not
          build it — the slot is left empty and named so E2b has one obvious
          home and does not need to restructure this header. */}
      <header
        data-testid="spec-view-header"
        className="flex shrink-0 items-center gap-2 border-b border-border bg-card px-3 py-1.5"
      >
        <h2 className="text-sm font-medium text-foreground">Deck spec</h2>
        {/* E2b badge slot — intentionally empty in E1. */}
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden text-xs text-muted-foreground sm:inline">
            Read-only — edits go through the conversation
          </span>
          <Button
            data-testid="spec-discuss"
            size="sm"
            variant="outline"
            onClick={onDiscuss}
          >
            Discuss
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        {!spec ? (
          <div
            data-testid="spec-view-empty"
            className="flex h-full items-center justify-center text-center text-muted-foreground"
          >
            <div>
              <p className="text-lg font-medium">No deck spec yet</p>
              <p className="mt-2 text-sm">
                Decks built before the architect agent — and decks built over MCP —
                have no spec. Ask in the chat for a plan and one will be written.
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* ── Deck-level fields ─────────────────────────────────────── */}
            <dl data-testid="spec-deck-fields">
              <SpecField label="Audience" value={spec.audience} testId="spec-audience" />
              <SpecField label="Purpose" value={spec.purpose} testId="spec-purpose" />
              <SpecField label="Argument" value={spec.argument} testId="spec-argument" />
              <SpecField
                label="Call to action"
                value={spec.call_to_action}
                testId="spec-call-to-action"
              />
            </dl>

            {/* ── Narrative arc — ORDER IS MEANING ───────────────────────
                An unordered arc is a different deck, so render the array as
                given: no sort, no reverse, no reordering by any other field. */}
            <h3 className="mb-1 mt-4 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Narrative arc
            </h3>
            <ol data-testid="spec-narrative-arc" className="list-decimal space-y-1 pl-5">
              {spec.narrative_arc.map((beat, i) => (
                <li
                  // Index key on purpose: the beats are plain strings with no id,
                  // and this list is never reordered in place.
                  key={i}
                  data-testid={`spec-arc-beat-${i}`}
                  className="text-sm text-foreground"
                >
                  {beat}
                </li>
              ))}
            </ol>

            {/* ── Design contract — IDS ONLY (see note 2 at the top) ────── */}
            <h3 className="mb-1 mt-4 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Design contract
            </h3>
            <div data-testid="spec-design-contract" className="text-sm text-foreground">
              {contract?.design_system_id != null && (
                <span data-testid="spec-design-system-id" className="mr-3">
                  Design system #{contract.design_system_id}
                </span>
              )}
              {contract?.template_id != null && (
                <span data-testid="spec-template-id" className="mr-3">
                  Template #{contract.template_id}
                </span>
              )}
              {contract?.slide_style_id != null && (
                <span data-testid="spec-slide-style-id" className="mr-3">
                  Slide style #{contract.slide_style_id}
                </span>
              )}
              {contract?.design_system_id == null
                && contract?.template_id == null
                && contract?.slide_style_id == null && (
                <span data-testid="spec-design-contract-none" className="text-muted-foreground">
                  No design system or slide style pinned
                </span>
              )}
            </div>

            {/* ── Per-slide briefs ───────────────────────────────────────── */}
            <h3 className="mb-1 mt-4 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Slide briefs
            </h3>
            <ol data-testid="spec-slides" className="space-y-2">
              {spec.slides.map((slide) => (
                <li
                  // Keyed by `position`, the slide's canonical identity — NOT the
                  // list index, which diverges from position after a delete.
                  key={slide.position}
                  data-testid={`spec-slide-${slide.position}`}
                  className="rounded-md border border-border p-2"
                >
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    Slide {slide.position + 1}
                  </div>
                  <p
                    data-testid={`spec-slide-purpose-${slide.position}`}
                    className="mt-0.5 text-sm font-medium text-foreground"
                  >
                    {slide.purpose}
                  </p>
                  <p
                    data-testid={`spec-slide-brief-${slide.position}`}
                    className="mt-1 text-sm text-foreground"
                  >
                    {slide.content_brief}
                  </p>
                  {/* assumes / hands off are the pair that makes the arc legible:
                      what this slide inherits, and what it leaves the reader. */}
                  <p className="mt-1 text-xs text-muted-foreground">
                    <span className="font-medium">Assumes: </span>
                    <span data-testid={`spec-slide-assumes-${slide.position}`}>
                      {slide.assumes}
                    </span>
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    <span className="font-medium">Hands off: </span>
                    <span data-testid={`spec-slide-hands-off-${slide.position}`}>
                      {slide.hands_off}
                    </span>
                  </p>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </section>
  );
}
