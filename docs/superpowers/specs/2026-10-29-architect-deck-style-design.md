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
- **`classify_spec_change`:** a deck-style-only change is not a narrative change. It does not fire the per-slide re-review or a rebuild. It is a CSS rewrite; the deck (arc) review still runs (see "Changes during the build", R12).

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
- **A deck-style-only edit rebuilds nothing.** (It still gets the deck, or arc, review; see "Changes during the build", R12.)
- **Older decks** get a deck style only when the user asks for a style change or rebuild.
- **The bars:** time to first slide ≤ +30 s, eval spend ≤ USD 40 (offline evals only).
- **Dropping a used piece** forces updates to the slides that use it, enforced by a node check and refusal (§5).
- **No page numbers.**
- **Plain-style decks** get a small palette of their own declared in the deck style.
- **The reference deck** stays outside git, in `~/tellr-loop/deck-style/`.

## Changes during the build

Where the built code differs from this spec, or a call was made at plan time. R-numbers are rulings in the build ledger (not committed).

Plan-time calls:
- The sanitiser cleans a bad deck style rather than rejecting the answer. What it cannot keep is dropped with a note; a style with nothing left becomes absent.
- The reviewer check in section 6 is carried by the authored fix_reviewer prompt, not by a new criterion in `src/domain/finding.py`.

Sanitiser (`src/domain/deck_style.py`):
- Every at-rule is dropped, not only `@import`, `@font-face`, `@keyframes` and `@namespace` (R3). `merge_css` keys at-rules by (keyword, prelude), so a deck-style `@media` would replace the template's.
- `:root` is dropped under a design system (same keying problem); otherwise only its `--dk-` properties survive (R3).
- A selector is kept only if a compound has a top-level `.dk-` class and every combinator after it is descendant or `>`. `:not(.dk-a)`, `:has`, `~` and `+` are dropped (R14, R14a).
- Declarations with a remote address (URL-normalised first; `data:` exempt) or `expression()` are dropped. Image functions (`image-set`, `cross-fade`, `src`, `element`) and nested rules are dropped too (R14, R15).
- Repeated selectors are coalesced at the last occurrence, because `merge_css` would keep only the last. Accepted: a rare cascade inversion against an equal-specificity rule written between them (R18, R19).
- Empty rules are dropped, `<style` text never survives, a rebuilt sheet must re-sanitise with no notes, and notes are capped at 200 characters (R14, R15).
- On a build, a style the sanitiser empties is dropped and the deck builds without one. On an edit, a dropped `deck_changes.deck_style` refuses the edit, with the notes, through the one-retry path (R4).
- A style carried into a new contract is re-sanitised under the committed contract's flag (R17).
- Final review fixes: the cleaned CSS never leaves a construct open and always encodes as UTF-8; the committed style is re-sanitised once at the write under the final design-system flag; a pinned deck whose brand resolves empty keeps its stored `deck.css` (the post-commit merge applies the style); and a dropped `deck_changes.deck_style` beside operations or other `deck_changes` is ignored and logged, refusing only when it was the edit's only change (R31).

Edits:
- A dropped class used by a kept slide refuses the edit with a slide-numbered sentence (`deck_style_drops_used_class`, R6). The check runs only when both a prior and a new style exist and the contract is unchanged (R7). It excludes classes the template owns and `slide`, and counts every other class (R22).
- Full-spec edits carry the persisted style forward on the same contract, and so does a describe-only answer with intent `build` (R8, R20, R23). A null `deck_changes.deck_style` means unchanged, so an edit cannot remove a style (R13).
- A deck-style-only edit rebuilds nothing, but the arc (deck) review still runs, one call per restyle (R12). This replaces the "rebuilds and re-reviews nothing" wording in the Calls list and §5's "not a narrative change" bullet.
- The deck style is also in the payload of `rereview_committed_slides` (R5). `build_request` is unchanged (R9).

Reviewers and prompts:
- The build reviewer prompt is unchanged (R10). The promote step refuses a transition source, and editing the prompt would break the v1 to v2 upgrade on released installs. It receives `deck_style` but has no rule for it; only the fix_reviewer prompt carries the deck-style check. This is a follow-up needing a migration decision.
- Prompts changed: architect, builder, fixer, fix_reviewer. A deck with a style but no design system gets a ground piece (R26).

Eval and scoring:
- `deck_style_keeps` is scored on the sanitised style, so a class defined only inside `@media` fails (R27, R28).
- The architect judge prompt is unchanged; the deterministic scorers decide the new cases (R30).
- Page numbers stay out, as specced.

Owner decisions:
- The builder moved to Sonnet (`system.ai.claude-sonnet-5-5`). Measured against Haiku: train 1.00 vs 0.86, held-out 0.86 vs 0.71, deck-style code cases 5/5 vs 2/10, at about 1.6 to 1.8 times the latency per slide and 2.8 times the cost per slide (about USD 0.55 vs 0.21 per 15-slide deck). The production workspace must offer that endpoint with non-zero rate limits. See `evals/README.md`.

Bars missed and known gaps:
- Architect build output tokens rose by 3,147 to 3,574 against the +2,500 bar (baseline 5,702). The architect build call went from about 51 s to about 77 s, close to the +30 s time-to-first-slide bar. Mostly longer reasoning; closing it is an owner call (the README says the growth is mostly reasoning).
- No eval case has a deck style on a deck with no design system, for the architect or the builder, so the ground-piece rule is shown non-breaking, not working.
- The architect cases carry no labelled template sections.
- The build-reviewer gap is unmeasured: its new cases are caught today by `rogue_colour`, so no gap was shown.

Addendum A (R-numbers here are `RA` rulings in the addendum ledger):
- Page tokens are read-path substitution with marker spans, as specced (RA1). The readers covered are `GET /api/sessions/{id}/slides`, the MCP `_render_deck_response`, the version-restore response and the chat service's deck dict; the saves covered are `update_slide` and `insert_slide` with html. `/chat/poll` reads the stored spec once for the slide count, so the Q4 "no DB read" yields there. A reader path missed would show literal tokens.
- The tool loop carries tools on `AgentAssemblyContext` (excluded from eq and hash), passes them to the adapter only when non-empty, and parses the raw reply itself because the schema parser raises on a first call that names another tool. Token usage is summed across rounds. Search output is capped at 20 rows at the call site (`_brand_search_tools`) and spotlighted once in the runtime loop (`_tool_result`) (RA2, RA9). Code: `_invoke_with_tool_rounds`, `_brand_search_tools`.
- Logo ranking changed from the spec's "default-ground variant first, SVG before raster": brand `logo` ranks before `lockup`, then the two grounds alternate before the cap of 12. Without that, a real library of hundreds of product lockups left no mark for a dark ground (RA8). One `search_assets` read is filtered in Python.
- The page-number ruling in §1 and the `no_page_numbers` architect pin and prompt line are retired (RA4). `evals/fixtures/meridian/assets.json` holds the fake index of logos and icons (RA6). The `deck_style_icons` case requires at least one icon handle placed, not only a logo (RA10).
- Prompts: the architect, builder and fixer prompts changed and were promoted after measurement. The builder extends the DECK STYLE block's precedence over IMAGE RULES rather than editing that line; the fixer never drops `white` and keeps its outer-root pin, so the one-ground rule is the builder's (RA5). The binding block's "logos come from the selected section's markup" was reworded to agree with the footer piece (RA11).
- Q1 gap fix (RA15). The first rule, "a bound slide fills the template's footer", left a bound section with no footer without one, which was about half of a real Databricks deck. The rule is now: every non-cover slide has exactly one footer. A bound slide whose section has a footer fills it and never adds the piece. A bound slide whose section has none, and an unbound slide, use the piece. The cover gets no page tokens and no footer piece, and a footer its section ships stays as shipped. The whole DECK STYLE block is fenced to payloads that carry `deck_style`. The fixer's footer bullets apply only when the finding concerns a footer. This was a measured wording pass. The RA15 bar was met: deck-style cases pass, no existing case lost a row, and no page token leaked on a no-deck-style row. One held-out row (`stat_no_data`) failed; the README records it as judge variance, not the footer wording (RA16). Improvised footers on no-deck-style rows fell from 7/10 to 3/10 pooled, probably from the fence; this is unconfirmed.

Addendum A limits:
- An older release's architect can still author a deck style that survives the sanitiser, which binds the tool for an older builder prompt, and for an older fixer prompt too (the fixer's binding is decided on the same builder record). The model may not call it (tool choice is auto), or may. Behaviour of an older release's builder or fixer with the tool is not measured, and the spec's "byte for byte" claim for those decks does not hold in that case (RA3).
- A sanctioned deviation from "old decks and old releases are byte-identical in model payloads" (Correction A22): every architect call on a design-system deck, on every release, carries `deck_style_context.logos` (and every other architect call carries `"logos": []`). It is a nested key, passed through by `model_payload_for`; the guarantee holds for the top-level payload keys, the builder and fixer bindings, CSS writes and stored HTML.
- Final review fixes: the streaming boundaries resolve brand assets, which replaces the Q4 call's "ds-asset handles stay unresolved mid-build". `slide_ready` and `/chat/poll` render each `{{ds-asset:ID}}` as a base64 data URI scoped to the session's active design system, after the page tokens, with one asset read per release wake or poll. The restore response resolves images and brand assets as the version preview does. The page-token scan reads a `<` that starts no tag name as text.
- One ground is enforced in code on build turns (RA23, RA25). The prompt rule did not hold on a real deck: a template's `slide white` section kept `white` and rendered on #FFF. When the architect's intent is `build` and the spec carries a deck style, `build_branch_payload` sets a branch-only `one_ground` key, and `slide_pipeline_node` drops the `white` token from every `slide` element of each non-cover slide (cover = spec position 0), after the builder and after the fixer, before the first store, so stored, reviewed and streamed HTML agree. The key is not a model payload key. Edit turns, including their fixer runs, and decks with no deck style are untouched: there the rule stays prompt-governed, and a user can ask for a white slide.
- The fixer's tool path has no eval case. The fixer is checked for non-regression only (RA7).
- Eval spend passed the USD 25 cap. It was USD 24.17 at the upper bound before the RA15 pass, which RA15 funded with a USD 4 extension (about USD 2.53 spent), for about USD 26.7 at the upper bound in all (RA13, RA14, RA15). The architect's footer text was not re-measured after RA15; the builder rule is the operative one. Footer and one-ground behaviour is also checked on a devloop build.
- The +30 s time-to-first-slide bar is waived for search latency (Q5); latency numbers are in `evals/README.md`.

## Addendum A (2026-10-30): brand assets, page numbers, one ground

### Why

The owner compared a devloop agent deck with legacy, built from the same prompt. Three gaps remain:

- **No icons or logo.** Legacy places product icons (Lakebase, Delta, Unity Catalog) and a Databricks logo in every footer, using the `search_brand_assets` tool. Graph roles have no tool, and the compiled design-system style deliberately does not list brand images. So a graph builder only sees asset handles that happen to sit in the bound template section's sample markup. Its prompt also says "If no image ids are supplied, build the slide without images".
- **No page numbers.** The spec's §1 ruling ruled them out because baked-in numbers go stale; the owner wants them.
- **White slides.** The template's Two-column section ships `slide white`, and the builder keeps a section's ground as shipped, so some content slides are white and others oat.

### Decisions made with the owner

1. **Builders search the design system for relevant icons themselves.** The architect does not pick icons: knowing the whole library is unreasonable. Its look only states intent ("an icon on each box").
2. **The logo is resolved once and placed by the architect in the footer piece**, so it is identical on every slide. (Proposed; owner: "lgtm".)
3. **Page numbers** appear as `n / N` on every slide except the cover.
4. **Light template sections render on the deck's own ground.** Dark sections (cover, dividers) stay dark.

### Design

**A1. A tool loop for builders and fixers.**
- The agent runtime gains support for role tool grants. Today it binds only the output schema.
- `builder` and `fixer` are granted `search_brand_assets`, the existing tool in `src/services/tools/ds_asset_tool.py`, scoped to the deck's design system.
- The loop binds the search tool and the output schema. The model may search up to 3 times, then must return its output through the schema tool as today. A reply with no output still fails as today.
- Tool results are untrusted data, spotlighted like other tool output.
- **The tool is bound only when a design system is active and the payload carries a `deck_style`.** A deck built by an older release, or a deck without a style, keeps today's single-tool binding byte for byte, so prod behaviour before a publish is unchanged.
- The same runtime path serves production, workbench test runs and the eval harness.
- Grants stay code-owned. They are not in the frozen manifest, so no content hash or digest moves; the `skills/__init__` rule "data_analyst is the ONLY skill with non-empty tool_grants" is updated. The data analyst's grants stay unread.

**A2. Logo context.** `deck_style_context` gains `logos`: up to 12 rows of `{handle, filename}` from `search_assets(kind="logo")` for the active design system. The architect picks the variant that suits the ground and puts it in the deck style's footer piece. Builders copy the footer piece.

**A3. Page-number tokens.**
- The footer piece carries `{{slide:number}}` and `{{slide:count}}`.
- They are filled in wherever a deck's `{{ds-asset:ID}}` handles are resolved for a reader: UI reads, exports, Google Slides and thumbnails. Values come from the slide's index in the deck's current order, so they are always right after inserts, deletes and moves.
- Stored HTML keeps the tokens.
- Legacy decks never contain them, so substitution is a no-op there.

**A4. One ground.**
- Builder rule: a light section treatment (`white` or default) renders on the deck's default ground, so the `white` token is dropped on content slides.
- Dark and event treatments are never changed.
- The build reviewer is unchanged (R10). Its `off_template_treatment` judges light-for-dark flips only, which this rule never makes.

**A5. Prompts.**
- **Architect:**
  - the deck style always includes a footer piece holding the chosen logo handle and the page tokens;
  - every content slide's look uses it;
  - looks state icon intent but never name icon handles.
- **Builder and fixer:**
  - place the brand assets the deck style catalogue names;
  - when the look asks for icons, or the slide shows products or concepts, search the design system and place what it returns;
  - never invent a handle;
  - follow the one-ground rule.
- All three are re-measured and promoted.

**A6. Evals.**
- The harness gets a small fake asset index for the Meridian fixture: a few logos and product icons with handles. Searches during eval runs resolve against it.
- **New builder case:** a look that asks for icons. It passes when the builder searched and placed a handle from the index, never an invented one.
- **Architect build cases:** the footer piece holds a handle from `deck_style_context.logos` plus both page tokens.
- Scoring is deterministic.

**A7. Cost and safety.**
- A slide whose builder searches costs one extra model round trip.
- Searches are read-only and scoped to the deck's design system.
- A wrong handle is left unresolved: it shows as a broken image and never resolves to another system's bytes.

### Non-goals

- The build reviewer.
- Legacy mode.
- Missing assets in a design system's library (e.g. no Lakebase icon).
- Any change to how assets are stored.

### Left to the builder

- The loop's exact implementation and how the design-system id reaches the runtime.
- The logo cap's ordering heuristic.
- Final token spellings.
- Which response-boundary helper hosts the page-token substitution, as long as every reader path uses it.

### Calls made without the owner (Addendum A; review these)

- **One footer per slide** (Q1).
  - On a bound slide the builder fills the template's own footer: its label slot, its number slot with `{{slide:number}} / {{slide:count}}`, and the logo.
  - On an unbound slide it uses the deck style's footer piece, which the architect styles to match the template footer.
  - A slide never carries two footers.
- **Page numbers survive hand edits** (Q2).
  - Substitution renders each value as `<span data-tellr-slide="number">3</span>` (and `"count"` for the total).
  - Every slide save path (`update_slide` and the visual and HTML editors' saves) turns such spans back into tokens before storing.
  - If an editor strips the marker, the number stays baked into that one slide; that is accepted.
  - Today's baking of ds-asset data URIs is out of scope.
- **Dark slides** (Q3). Every slide except the cover is numbered. The architect picks two logo handles from `logos`, one for light grounds and one for dark. Dark slides (dividers, closing) use the light-on-dark logo in their footer.
- **Streaming** (Q4).
  - Mid-build `slide_ready` events and `/chat/poll` slides substitute page tokens only. The number is position + 1 and the count is the spec's slide count. There is no DB read.
  - ds-asset handles stay unresolved mid-build, as they are today, until the `complete` refetch.
- **Bars and budget** (Q5).
  - The +30 s time-to-first-slide bar is waived for search latency, because the owner chose builder search. Latency is measured and reported.
  - The addendum gets its own eval cap of USD 25: architect ≤ 12, builder + fixer ≤ 11, slack 2.
- **Workbench runs** (Q6). The tool is unbound in workbench test runs: they build their context without tools, even when a test case sets `design_system_active`. Publish approvals exercise the prompts only; the eval harness covers the tool path.
- **Build reviewer and the dropped `white`** (Q7). If measurement shows the frozen reviewer flagging `off_template_treatment` on light-to-default grounds, the fallback is architect-side: prefer default-ground sections, or leave a slide unbound. The reviewer is not changed.
- **Logo kinds.** `logos` draws on assets of kind `logo` and `lockup`, then ranks: default-ground variant first, SVG before raster.
