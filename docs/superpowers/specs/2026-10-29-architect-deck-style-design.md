# Architect owns deck styling — design

Status: draft for owner review (2026-10-29).

## Why

Agent-mode (graph) decks look worse than legacy (monolith) decks built from the same kind of brief. A side-by-side of two production decks for the same technical topic ("Lakebase → Delta without CDF", 15 vs 22 slides, both on the Databricks design system) showed:

- **Legacy writes its own stylesheet; agent cannot.** In one call, seeing the whole deck, the monolith wrote ~60 rules of deck-specific CSS on top of the brand tokens: a syntax-highlighted `.code-block` (`.kw` / `.fn` / `.str` / `.cm`), a `.brand-table` (coral header, zebra rows), `.tag-measured` / `.tag-untested` badges, inline `code` chips, numbered step circles, a title accent bar and a logo + "n / N" footer, all reused on every slide. The builder is told "DO NOT emit a `<style>` element — deck CSS has a single writer" (`src/core/skills/builder.py`, enforced by `BuilderOutput._no_style_element` in `src/domain/skill_io.py`). The only deck CSS is the design system's tokens plus the template's own `<style>` block (232 rules written for the template's sample slides), which has no code block, badge, step or chip.
- **Parallel builders cannot agree.** Each builder sees one slide and none of its siblings, so each one improvises. The agent deck's three code blocks have three different inline styles (`#F3F3F3` / 13px / bordered, `#f5f5f5` / 12px / no border, …) and no syntax highlighting. It also has 174 inline `color:` / `background:` declarations despite the prompt's ban, and no shared chrome (plain "Databricks" text footer, no page numbers).
- **Slides are forced into template layouts.** With a design system and no pinned template, the graph fills in the design system's default template (`_with_default_template` in `src/services/graph/nodes.py`), and a bound builder must "fill that structure … and keep everything else". Content that doesn't match the section's shape leaves dead space (e.g. a code slide with its notes pinned to the bottom of the frame).

Both engines get the same design-system prose (`resolve_style_source`), so the gap is not the wording of the style guidance. It comes from who may write CSS and how much of the deck each model sees.

## Goals

- **A consistent agent deck.** The same kind of thing (code, table, badge, steps, callout, diagram box) looks the same on every slide.
- **The architect decides the look.** It writes a thin, deck-specific *deck style* (the "house style"), and for every slide it says what that slide looks like.
- **Builders only fill content** into the look they were given, using the deck style's pieces.
- **Strongly guided by the design system, not caged by it.** Template slides are used where they fit. Where the story needs a slide the template doesn't have, the architect designs one in the deck style, the way a person with a brand kit and a blank slide would.
- **Deck-wide style requests are cheap.** "Make the code blocks dark" changes the deck style once, and every slide follows without being rebuilt.
- **Parity on the reference deck.** Rebuilt in agent mode, the Lakebase deck is as consistent and polished as the legacy one, judged by the owner side by side.

## Non-goals

- Changing legacy (monolith) mode in any way.
- Changing what design systems or templates are, or how they are uploaded or compiled.
- Content fidelity (verbatim code and tables surviving the architect's `content_brief`). That gap is real but separate.
- Restyling existing agent decks automatically.

## Anti-goals (a failure even if it "works")

- **A heavy design system in disguise.** The deck style is thin. If it starts restating the brand (resets, type scale, colours, slide frame), it competes with the design system.
- **Every deck looking the same.** The deck style is written for each deck's content. It is not a fixed library shipped in code.
- **Noticeably slower first slides.** The architect does more work before any builder starts.
- **Breaking existing agent decks.** A deck built before this must still display, edit and export exactly as it does today.

## Decisions made with the owner

1. **The architect owns styling.** It sets what each slide looks like, to make the deck consistent. Parallel builders are the problem being solved.
2. **A thin layer on top of the design system**, not a replacement for it. It holds only the pieces this deck needs that the design system doesn't already provide. If the design system has a piece, the deck style uses that one.
3. **Not prescriptive.** Decks should not all look the same, and the architect may adjust the deck style as the deck evolves.
4. **The design system is a strong steer, not a cage.** Brand colours, fonts, logo and feel always apply. Template slides are a starting point. The architect may design layouts the template doesn't have.
5. **The overall shape** (deck style plus a per-slide look; builders fill content; deck-wide style requests change the deck style once), the anti-goals above, the edit behaviour in §5, the reviewer check in §6, and how success is judged (§8) were played back and accepted.

## Design

### 1. What the architect produces

Two new things, both optional so every existing spec stays valid.

**`DeckSpec.deck_style`** — the deck's house style:

- `css`: CSS text (not `<style>`-wrapped) defining the deck's pieces. Rules:
  - It adds classes and does not redefine design-system tokens (`:root` custom properties), `@font-face` or the template's own classes.
  - It takes colours and fonts from the design system's custom properties (`var(--db-navy)` and the like) rather than raw values, when a design system is active.
  - Without a design system there are no such properties, so the deck style opens with a small palette of its own prefixed custom properties, taken from the resolved slide-style text. Its pieces use those, and raw colour values appear only in that palette.
  - Its classes carry one shared prefix so they cannot collide with template classes.
  - No `@import` and no external `url()`.
  - It is thin: a target of roughly 4,000 characters and a schema hard cap of 10,000.
- `components`: a short catalogue, one entry per piece (at most ~12). Each entry has a name, its class(es), one line on when to use it, and a minimal example of its markup. This is how a builder knows how to use the CSS: for a code block, for example, which span classes mark keywords, strings and comments.

**`SlideSpec.look`** — one or two sentences saying what this slide looks like. It names the layout of the body and which deck-style pieces (or template pieces) it uses, e.g. "code block across the top, the three notes as cards in a row beneath". It is written in plain language.

The deck-level chrome every slide shares (the title treatment, the footer's look) is part of the deck style too. For bound slides it comes from the template; for unbound slides it comes from the deck style.

**Page numbers are out of scope.** A number baked into a slide goes stale when slides are inserted, deleted or moved: the legacy reference deck's cover still says "1 / 17" in a 22-slide deck. The deck style may style a footer, but it does not number slides.

`ArchitectOutput` gains nothing new at the top level: both fields travel inside `deck_spec`. The edit form gets `DeckChanges.deck_style` (§5).

### 2. How the architect decides

Architect prompt changes:

- **On a build**, write the deck style from what the content needs (look at the slides you planned: code? tables? measured / untested badges? steps? diagrams?) and the design system. Reuse any design-system or template piece that already exists, add only what's missing, and keep it thin.
- **On every slide**, write a `look`.
- **Template binding becomes "where it fits"**:
  - Bind a template section when its shape fits the slide (cover, divider, a standard content slide).
  - When the content needs a body the section doesn't have, you may still bind the section for its frame (ground, eyebrow, title, footer). The `look` then describes the body, which replaces the section's body. This generalises today's "the exhibit replaces that section's body while its eyebrow, title and footer stay".
  - When no section's frame fits, leave the slide unbound, and the `look` describes the whole slide in the deck style.
  - The existing rule against binding a merely similar section stays.
- **Without a design system** (plain slide style), the deck style does the whole job: its colours and fonts come from the resolved slide style text.

### 3. What builders and fixers do

`build_branch_payload` carries `deck_style` whole (CSS and catalogue) alongside the existing `section_css`. `look` arrives inside `slide_spec`.

Builder (and fixer) prompt changes:

- Build the slide to its `look`, using the deck style's pieces exactly as the catalogue shows them.
- For a bound section, keep its frame and lay out the body as the `look` says, replacing the section's body markup where the look requires it. This relaxes today's "keep everything else".
- **When a deck style is present**, inline styles are for layout only (flex, grid, gap, width, position). No inline colour, background, font family, font size or border colour, in both design-system and no-design-system decks. The no-DS permission for inline colour exists today only "because there is no deck CSS"; with a deck style there is.
- **When a deck style is absent** (an older deck), today's rules apply unchanged.
- The no-`<style>` rule stays: the architect is now the only model writer of deck CSS.

### 4. How the deck style reaches the page

The graph already has a single deck-CSS slot: `emitted_style_blocks`, merged by `aggregate_deck_css` (`src/services/deck_css_aggregator.py`) after the pre-fan-out write of `deterministic_css` (tokens + template block). Today it holds at most one block, the template's.

- **Merge order:** the deck style is appended after the template block (tokens, then template, then deck style), both in the pre-fan-out `deck.css` write and in the post-commit aggregate. Builders' slides therefore render with it from the first `slide_ready`.
- **The aggregator's contract changes** from "exactly one element" to "the template block, then the deck style". Its docstring and tests change with it.
- **A change to the deck style** must leave `deck.css` reflecting the new style, not the union of old and new: a piece removed from the deck style must not linger. Recomputing from `deterministic_css` + the current `deck_style` is the obvious way.
- **Security:**
  - The deck style is model-authored CSS that is influenced by user input. It renders under the same deck CSP as monolith-authored CSS (no new network allowance).
  - It is handed to builders, fixers and reviewers inside the untrusted-data section, as `section_css` is.
  - `@import` and non-`data:` `url()` are rejected or stripped at the point it enters the spec.

### 5. Edits

- **A slide edit** (update / replace / insert): the builder gets the current deck style, so the edited slide matches the rest.
- **A deck-wide style request** ("dark code blocks", "bigger tables"):
  - The architect returns `deck_changes.deck_style` with the revised style. `deck.css` is rewritten, and no slide is rebuilt when the change is to the pieces' appearance only.
  - If the request needs different markup on some slides (e.g. "put the notes in cards"), those slides also get `update` operations.
- **Dropping or renaming a piece that slides still use:**
  - The architect may do it, but every committed slide that uses that piece's class must get an `update` operation in the same edit. Otherwise those slides would silently lose their styling.
  - The node checks this deterministically: it scans the committed slides' class usage against the new deck style. If a used class would disappear without its slides being updated, the edit is refused with a problem, through the existing one-retry path. The problem names the slides and the class.
  - Changing how a piece looks while keeping its class needs no slide updates.
- **A slide that needs a piece the deck style doesn't have** (the first chart, say): the architect adds it in `deck_changes.deck_style` in the same turn, so later slides can reuse it.
- **A design-contract change** (a new design system or template), which already invalidates every slide: the architect writes a fresh deck style along with the rebuild.
- **An older deck with no deck style** keeps today's behaviour. The architect may introduce one when the user asks for a style change or a full rebuild, and otherwise leaves it absent. Slides built before it existed don't use its classes, which is acceptable.
- **`classify_spec_change`:** a deck-style-only change is not a narrative change. It does not fire the deck-level re-review / rebuild path. It is a CSS rewrite.

### 6. Reviewers

- **The build reviewer and the fix reviewer** receive the deck style.
- **One check is added**, through the criteria registry in `src/domain/finding.py` (which regenerates the reviewer checklist), either as a new criterion or as an extension of `rogue_colour` / `off_template_treatment`. It flags a slide that:
  - restyles what the deck style provides (inline colours or sizes, its own code block or badge);
  - uses a class the deck style doesn't define;
  - ignores its `look`.
- **The fixer** fixes toward the deck style.
- **The deck reviewer** is unchanged.

### 7. Prompts, schemas and shipping

The edit-operations work (`2026-10-28-architect-edit-operations-design.md` §10) is the precedent, and the same process applies:

- **Schema changes are canonical:**
  - `DeckSpec`, `SlideSpec` and `DeckChanges` gain optional fields.
  - The schema digests of every role whose output or payload changes are re-pinned, and the superseded values move into `_HISTORICAL_DIGESTS`.
  - `BuilderOutput` itself does not change.
- **Prompts** change for the architect, builder, fixer, build reviewer and fix reviewer. They are promoted into the frozen manifest with `evals.harness.promote` after measured runs (§8).
- **Frontend:** the new `DeckSpec` / `SlideSpec` fields are mirrored in the TypeScript types and in the pydantic-parity fixtures (`frontend/src/types/slide.ts`, `frontend/src/test/pydanticSource.ts`). The spec view does not need to show the CSS.
- **Existing installs** get the new prompts only when an admin publishes the release, and only new conversations pick them up. Node code (payload, CSS merge, edit handling) ships immediately and must behave exactly as today when `deck_style` is absent.
- **Devloop** forks inherit prod's published graph release, so testing the new prompts there needs a workbench publish on the devloop instance.
- **Docs:** `docs/technical/backend-overview.md` (graph CSS path) and `CONTEXT.md` (deck style, look).

### 8. How we know it worked

- **Owner judgement, the real bar:** on a devloop instance, rebuild the Lakebase deck plus two or three other decks of different kinds (a data/chart deck and a narrative deck) in agent mode. The owner compares them side by side with legacy.
  - **The Lakebase reference** lives outside the repo in `~/tellr-loop/deck-style/`:
    - the production prompt (`lakebase-brief.md`);
    - the prod agent-mode deck (`agent-mode-prod.html`);
    - the legacy comparator (`legacy-mode-prod.html`).

    It is kept out of git because the brief describes internal platform work. The legacy deck was edited after its first build, so it is a style comparator, not a content one.
  - **Setup:** use the Databricks design system on the devloop instance with its default template (what an unpinned graph deck gets). For the other decks, a legacy build of the same prompt on the same instance is the comparator.
  - **Shared state:** creating the devloop instance and doing the workbench publish there are shared-state actions. The builder confirms them with the owner before doing them.
- **Deterministic consistency checks** on those full-deck runs:
  - zero inline colour / background / font-size declarations on slides built with a deck style;
  - every code block (and every table, every badge) on the deck uses the same deck-style class;
  - every class a slide uses is defined by the design system, the template or the deck style;
  - the deck style respects its size cap and redefines no design-system token.
- **Offline evals** (`evals/packs/architect`, `builder`, `build_reviewer`):
  - Architect: new cases check that a deck style is present and thin, uses DS tokens, and that every slide's `look` names only pieces that exist.
  - Builder: cases with a deck style in the payload check use of the catalogue and the inline-style rule.
  - Every existing case passes at least as often as its recorded baseline.
- **Time to first slide** on the reference deck rises by no more than 30 seconds against today's agent mode.
- **Eval spend** for the change is capped at USD 40 across all offline eval runs and all roles, with up to three prompt candidates per role. If the cap binds, the architect and builder prompts take priority, and the reviewer and fixer prompts get one candidate each. Devloop full-deck runs are outside this cap.

## Left to the builder

- Field names beyond `deck_style` / `look`, the class prefix, and the exact shape of a catalogue entry.
- The exact prompt wording within §2, §3 and §6.
- Whether the reviewer check is a new criterion or an extension of existing ones.
- How `@import` / external `url()` are rejected (validator vs strip) and where.
- How `deck.css` is recomputed on a deck-style change, as long as nothing removed lingers.
- How the hard size cap is enforced and what happens on a breach (retry vs truncate).
- Which two or three extra reference decks to use, as long as they differ in kind from the Lakebase deck.

## Calls made without the owner (review these)

- **The terms:** "deck style" for the house style and `look` for the per-slide recipe.
- **The deck style lives in `DeckSpec`** (persisted with the spec, editable through `deck_changes`) rather than only in `deck.css`.
- **The catalogue.** The deck style carries a catalogue of pieces with example markup, not just CSS, so builders can use it without guessing.
- **Thin is enforced:** ~4,000-character target, 10,000 hard cap, ~12 pieces. Raw colours are not allowed when a design system is active.
- **The deck style may not override** design-system tokens, fonts or template classes. It adds pieces and does not restyle the brand.
- **Bound sections are a frame.** The `look` may replace a bound section's body, relaxing the builder's "keep everything else".
- **Inline styles are layout-only** whenever a deck style exists, for design-system and plain-style decks alike.
- **A deck-style-only edit rebuilds and re-reviews nothing.**
- **Older decks** get a deck style only when the user asks for a style change or rebuild.
- **The bars:** time to first slide ≤ +30 s, eval spend ≤ USD 40 (offline evals only).
- **Dropping a used piece** forces updates to the slides that use it, enforced by a node check and refusal (§5).
- **No page numbers.**
- **Plain-style decks** get a small palette of their own declared in the deck style.
- **The reference deck** stays outside git, in `~/tellr-loop/deck-style/`.
