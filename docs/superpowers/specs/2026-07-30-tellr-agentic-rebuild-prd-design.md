# Tellr Agentic Rebuild — Product Requirements (Umbrella PRD)

**Status:** Design / PRD (not an implementation plan)
**Date:** 2026-07-30
**Author:** Robert Whiffin (with Claude)
**Scope:** Re-architecture of the core slide-generation agent and its surrounding
experience. This is the north-star document. Each workstream in §10 gets its own
detailed spec + implementation plan when it is picked up.

---

## 1. Why

The slide-generation agent is one of the oldest parts of Tellr and has drifted out
of step with both the product's ambitions and the Databricks platform. Today it is,
in effect, **an HTML emitter with a chat log bolted in front of it**:

- A single LangChain-classic `AgentExecutor` whose base instruction is literally
  *"You respond only valid HTML. Never include markdown code fences or additional
  commentary."* Conversation is treated as a failure mode to retry away from.
- The model is **hardcoded** (`databricks-claude-opus-4-6`); there is no gateway,
  no usage governance, and no per-role model flexibility.
- Editing is **checkbox-driven and contiguous-only**: the user selects adjacent
  slides and one instruction is applied to all of them. Intent is inferred by ~40
  brittle regex rules (the "RC10–RC15" checks). There is no way to say "update
  slide 5 with this, slide 6 with that, slide 10 with something else."
- The slide viewer is a **scroll-through-all list**; the direct HTML editor is
  broken.
- MLflow is present but **fragile and bolted-on**: LangChain autolog is disabled
  (async/ContextVar breakage), there is a "direct-judge" fallback that bypasses
  MLflow entirely, spans are auto-skipped under some conditions, and UC-backed
  tracing silently degrades to a plain experiment when unavailable. Verification is
  a manual, post-hoc "click Verify on a slide" action, not an intrinsic step.
  **Resolution (§16): this is fixed by REMOVING MLflow from the product, not by
  rebuilding it.** Every hack listed here is deleted; the quality evidence becomes a CI
  gate, and the manual Verify action is retired with the judge behind it.

This PRD reframes Tellr from *a slide-generating agent* into **an agentic
slide-authoring system you converse with** — a brainstorming and refinement partner
that produces, reviews, and repairs decks, is fully observable, and is governed by
the platform.

### 1.1 Primary driver

This is a **phased platform re-architecture**, not a single-axis improvement. The
PRD frames the end-state and sequences the work. Three outcomes matter together:

1. **Conversational UX** — an agent you brainstorm and iterate a deck with.
2. **Databricks showcase** — exemplary use of Unity AI Gateway.
   ~~and MLflow 3 GenAI~~ ❌ **AMENDED 2026-09-18 (§16).** MLflow is not in the
   product, so a stated outcome claiming exemplary use of it would be false. This
   follows from §16's decision rather than being an independent choice.
3. **Quality & trust** — automated review agents plus real evaluation. (~~/observability~~
   — §16: no observability stack; the evidence is a CI gate, not a dashboard.)

---

## 2. Users & jobs to be done

Two distinct segments with materially different needs. The architecture serves both
through one engine with two front doors (§9), but their success looks different.

### Segment 1 — Interactive authors (Field Engineers, primary)

An FE preparing a customer deck. They arrive with a goal and partial material, not a
finished outline.

| Job | Today | Target | Enabled by |
|---|---|---|---|
| "Help me work out what this deck should say" | Not supported — the agent only emits HTML | Brainstorm with the supervisor before any slide exists | ws4 |
| "Build it from our data" | Supported (Genie/tools) | Unchanged, but reviewed on the way out | ws4, ws5 |
| "Change slides 5, 6 and 10 — differently" | Impossible: contiguous checkbox selection, one instruction | One conversational turn, three targeted edits | ws7 (needs per-slide addressing — ✅ ws0a) |
| "Is this deck any good?" | Manual per-slide "Verify" for numbers only | Automatic content/design/narrative review, defects pre-fixed | ws5 (needs per-slide verdicts — ✅ ws0a) |
| "Fix this text myself" | HTML editor is broken | Inline WYSIWYG on the stage | ws8 |
| "Don't lose my verified slides when I reorder or restore" | Verdicts live in one shared blob; reorder and restore lose or mis-attribute them | A verdict follows its slide through reorder, edit-and-revert, and save-point restore | ✅ ws0a |

**Status against these jobs: none of them are delivered yet.** Workstreams 0a and 0b
(§10) changed no user-visible behaviour by design — they are the data model and dependency
groundwork the remaining workstreams stand on. The one row above marked ✅ is the exception,
and it is a *fidelity* guarantee rather than a new capability: per-slide verdicts now
survive the operations that previously dropped them.

Two jobs were **blocked by the old data model**, not merely unbuilt, which is why the
prerequisites came first: addressing slides 5, 6 and 10 independently and holding a
verdict per slide both require a slide to be a row you can name and write in parallel. With
one `deck_json` blob behind an optimistic lock, concurrent per-slide work 409s itself and
per-slide verdicts share one field. That is now fixed.

### Segment 2 — Programmatic callers (skills & MCP)

The TAP builder, DAIS agenda curator, and KPMG pricing skills render a single
composed prompt into a finished deck and **never see the UI**. They need:

- one call, no dialogue, no interrupts;
- the existing `create_deck` / `edit_deck` contract unchanged;
- review + remediation applied *internally* before the deck is returned — these
  callers benefit most from automatic quality, since no human is in the loop to
  catch a bad slide.

**Unchanged by workstreams 0a/0b, deliberately.** The prerequisites preserved the
`get_slide_deck()` dict contract exactly, so the export chain and every `html_content`
consumer needed no edits — verified by a parity test that builds each slide's HTML through
the real export funnel on both the legacy and row paths and asserts they are identical. The
programmatic contract these callers depend on is therefore untouched, and that parity test
is the regression gate protecting it (§3's no-regression criterion).

**Design consequence:** conversation is a front door, not the engine. Anything that
only works in dialogue (clarifying questions, interrupts) must have a defined
non-interactive behaviour.

---

## 3. Success criteria

How we know the rebuild worked. These are product outcomes, not implementation
checkpoints; each workstream spec derives its own acceptance tests.

**Conversational UX**
- A user can hold a substantive deck-shaping conversation with zero slides
  generated, then have the agent build from that conversation.
- Multi-target editing in one turn works: "slide 5 X, slide 6 Y, slide 10 Z"
  produces three correct, independent edits.
- Checkbox selection is **retired**, not merely supplemented.
- No brainstorm/build toggle exists in the UI.

**Quality & trust**
- Objective defects (rogue colour/format, stretched image, overflow, source-
  contradicting figure) are auto-fixed before the user sees the deck, and what was
  fixed is visible.
- Subjective findings surface in the right channel (deck-level → chat, slide-level →
  drawer) and are actionable (Apply / Dismiss / Discuss).
- The eval harness runs in CI and can demonstrate quality has not regressed when
  prompts or models change.
- ~~Review verdicts are queryable as MLflow assessments against traces.~~
  ❌ **STRUCK 2026-09-18 (§16).** Verdicts live in Lakebase —
  `session_slides.verification_record` (per slide, content-hashed) and `deck_reviews`
  (deck-level, digest-addressed) — which carry product-specific invalidation semantics
  an MLflow assessment does not have.

**Platform / showcase**
- Every LLM call in the system is attributable to a user and session, with token and
  cost visibility in the admin dashboard.
  **Owned by workstream 2** via Gateway metering (§16). No token or cost capture exists
  anywhere in `src/` today, and `get_structured_model` discards `usage_metadata`, so
  this criterion has no foundation in the application until the Gateway supplies it.
- ~~A full turn is inspectable end-to-end as one nested trace (supervisor → builder →
  reviewers → tools) with no gaps.~~
  ❌ **STRUCK 2026-09-18 (§16).** The user-facing need it served — showing a user what
  the agent did — is met by an app-native activity view over Lakebase, subject to the
  app's existing deck permissions.
- No hardcoded model endpoint remains.

**No regression** (release gate)
- Existing decks and sessions open and remain editable after cutover.
- `create_deck` / `edit_deck` callers work unchanged — TAP, DAIS and KPMG skills
  produce decks of at least current quality.
- Export (PPTX + Google Slides), permissions, save points and sharing behave as
  before.

*Status after workstreams 0a/0b (2026-08-12):* the data-model half of this gate is
covered by automated tests and verified against a production-forked Lakebase branch —
existing decks open (dual-read falls back to `deck_json`, and the startup backfill
migrates them), the `get_slide_deck()` dict contract is byte-identical across the legacy
and row paths, and save-point restore round-trips slides, CSS, external scripts, the deck
spec and verdicts. **Not yet covered:** Google Slides export parity could not be tested
hermetically (`HtmlToGoogleSlidesConverter` requires live Databricks and Google
credentials), so it is asserted only via the shared `build_slide_html` funnel — a manual
export check belongs in the release gate. Permissions and sharing are unchanged by these
workstreams but remain to be re-verified for 4/5.

*Status after workstream 4 (2026-09-16):* **six of the seven release-gate checks passed on
a live devloop deployment**, so several items above are now closed by measurement rather
than by argument. Existing decks open and stay editable; a monolith-mode turn is unchanged
(3 slides, ascending, styled); a graph-mode turn builds a styled deck with a populated deck
spec; **the Google Slides export parity gap above is closed** — both PPTX and Google Slides
exports were run end to end, and the Chart.js canvas rasterises into the PPTX (verified by
inspecting the artefact, not the code path); a pinned-template deck is not washed out; and
the checkpointer survives the Lakebase OAuth refresh, observed across 80 requests to
t+134m and a graph turn that wrote checkpoints past a refresh. The seventh check —
"a placeholder is honest" — **cannot be performed:** it needs a fault-injection mechanism
that exists in no plan.

**Two gate items are NOT closed, and one of them can lose a user's work.**
Permissions and sharing are still to be re-verified for 5. And the selective-rebuild
economics were measured and **failed**: a real model emitted the single criterion that
drives the decision on **3 slides out of 3**, so a deck-level spec edit may rebuild the
whole deck and discard manual edits. **This is the one item that should gate offering the
graph path to real users, and it lands directly on workstream 7**, whose whole subject is
conversational editing.

---

## 4. Target architecture

Tellr becomes a **multi-agent system orchestrated with LangGraph**, running
in-process. The thing the user (or a programmatic caller) talks to is a
**supervisor**, not an HTML emitter.

```
                    ┌─────────────────────────────┐
   user turn  ─────▶│      SUPERVISOR agent       │◀──── one-shot entry
  (multi-turn)      │  brainstorm · refine · route │      (MCP / skills)
                    │  decides implicitly:         │
                    │  chat? build? review? ask?   │
                    └──────────────┬──────────────┘
                          delegates │  (graph edges)
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                     ▼
      ┌──────────────┐    ┌────────────────┐   ┌──────────────────┐
      │   BUILDER    │    │  REVIEW agents  │   │   data tools      │
      │  data tools  │    │  content        │   │  Genie/MCP/vector │
      │  + HTML gen  │    │  design         │   │  model endpoints  │
      │  per-slide   │    │  narrative      │   │  (shared by       │
      └──────────────┘    └────────────────┘   │   builder+review) │
              ▲                    │            └──────────────────┘
              │  generate→review→  │
              └── remediate loop◀──┘  (cyclic edge; objective fixes only)
```

### 4.1 Core principles

- **Implicit mode.** There is no brainstorm/build toggle. The supervisor holds a
  conversation, and only delegates to the builder when the intent is to produce or
  change slides. Brainstorming turns never touch the deck.
- **Structured shared state.** The graph state carries: the conversation, a **deck
  spec** (structured intent — outline, per-slide purpose/narrative role), the
  current deck HTML, and accumulated review findings. This replaces both the
  base64-HTML round-trip and the regex intent detection.
- **Two front doors, one graph.** A conversational (multi-turn, interruptible)
  entry for humans, and a headless one-shot entry (prompt → finished deck, no
  dialogue) for programmatic callers. Same graph; interrupts disabled on the
  one-shot path.
- **Review is a cycle, not an afterthought.** Objective defects auto-remediate
  (builder re-invoked, then re-reviewed); subjective findings are surfaced, never
  silently applied.
- **The review system and the eval system are the same system** (see §7).

### 4.2 Orchestration decision

**LangGraph, in-process** (chosen over a hand-rolled Python orchestrator and over a
fully endpoint-hosted Databricks Agent Framework deployment).

- *Why:* LangGraph is purpose-built for exactly this shape — multiple agents, a
  cyclic remediation loop, human-in-the-loop interrupts, streaming, and
  checkpointed state that maps cleanly onto Tellr sessions. It makes the flow
  observable as clean nested spans (useful for debugging, though no MLflow pillar now
  depends on it — §16) and replaces the imperative control flow of the 1,863-line
  monolith.
- *Rejected — Python orchestrator over LangChain-classic:* would hand-roll state,
  loops, interrupts, and streaming, growing exactly the kind of hard-to-trace
  imperative code that is the current staleness.
- *Rejected (for now) — Databricks Agent Framework endpoints:* heavyweight for an
  in-process app; per-hop endpoint latency hurts the tight UI streaming loop.
  **Future option:** individual specialist agents *may* later be promoted to
  governed serving endpoints for the showcase story — the in-process graph does not
  preclude this.

---

## 5. The conversational supervisor

The supervisor is the product's new center of gravity.

- **Behaves as a brainstorming/refinement partner.** It can discuss narrative,
  audience, structure, and data without producing slides. It asks clarifying
  questions when intent is ambiguous rather than guessing (retiring the regex
  clarification checks).
- **Delegates implicitly.** When a turn's intent is "produce or change slides," it
  invokes the builder with a targeted instruction derived from the conversation and
  the deck spec. When the intent is discussion, it simply replies.
- **Owns multi-target edit parsing.** "Update slide 5 with this, slide 6 with that,
  slide 10 with something else" is decomposed into N distinct per-slide edit
  intents, each dispatched and reviewed independently (see §6).
- **Routes review output** to the correct channel: deck-level findings to the main
  chat, slide-level findings to per-slide drawers (see §6).

### 5.1 What "good brainstorming partner" means

This is the headline value proposition, so it needs stating as behaviour rather than
aspiration. The supervisor should:

- **Engage with the deck's purpose**, not just its contents — audience, the argument
  being made, what the reader should do next.
- **Offer structure**, e.g. propose an outline or narrative arc and invite reaction,
  rather than waiting to be told slide by slide.
- **Push back usefully.** If a deck has no conclusion, or a section doesn't serve the
  stated audience, say so during the conversation — not only after generation via a
  review finding.
- **Remember the shaping.** Decisions reached in conversation (audience, tone, the
  arc) persist in the deck spec and constrain later builds, so agreed direction isn't
  re-litigated or silently dropped.
- **Ask when genuinely ambiguous, act otherwise.** A clarifying question is right
  when readings differ materially; asking about a routine judgement call is friction.

**Explicitly not wanted:** a chatbot that discusses slides but won't commit; an agent
that needs a fully-specified brief before it will produce anything; or one that
silently generates a deck when the user was still thinking aloud.

**Non-interactive behaviour (Segment 2).** On the one-shot path there is nobody to
ask. The supervisor must resolve ambiguity by choosing a sensible default, proceed to
a finished deck, and report assumptions in the returned review summary — never block
waiting for input.

---

## 6. Editing UX & the flip-through viewer

Two shifts: **conversational multi-target editing** (retire checkboxes) and a **new
slide viewer** (retire the scroll list), plus a redesigned direct editor.

### 6.1 Conversational multi-target editing

- Slides are addressed **by natural-language reference** ("slide 5", "the pricing
  slide"). The supervisor resolves references against the deck spec / graph state —
  **no selection state and no base64 `slide_context` round-trip.**
- ~~A lightweight **"@slide" affordance** remains: clicking a slide inserts a
  reference chip into the chat so pointing is easy when the user doesn't want to
  type an index. It *augments* natural language; it does not gate it.~~
  ❌ **DROPPED (2026-09-16, operator's decision).** Natural-language addressing proved
  sufficient in use, so the chip is not being built. It was only ever an ergonomic
  augmentation — the bullet above is the requirement, and it stands.
- The contiguous-only constraint is gone: any set of slides, adjacent or not, can be
  targeted in one message with distinct instructions each.

### 6.2 Flip-through viewer

> ✅ **DONE — shipped (workstream 6).** Branch `feat/flip-through-viewer`, built
> against fixture data and verified on a devloop deploy against a prod Lakebase
> branch. Spec: `docs/superpowers/specs/2026-08-03-flip-through-viewer-design.md`;
> plan: `docs/superpowers/plans/2026-08-03-flip-through-viewer.md`; technical doc:
> `docs/technical/slide-viewer.md`.
>
> **Landed:** single-slide stage (aspect-fit, arrow/keyboard/wheel paging, one slide
> per gesture); vertical thumbnail ribbon with real scaled previews, drag-reorder and
> unseen-feedback dots; tabbed feedback drawer (resizable, persisted) with
> Apply/Dismiss/Discuss; checkbox + contiguous selection retired (`SelectionContext`,
> `SelectionRibbon`, `SlideSelection`, `isContiguous` all deleted); per-slide CRUD
> (edit HTML, delete, verification badge, optimize layout) migrated onto the stage;
> export/present rewired so they no longer route through `SlidePanel`'s ref.
>
> **Consumed as a stub, as planned:** findings arrive as props typed by
> `SlideFinding`/`DrawerCallbacks` and are hard-wired to `[]` in production — the
> producing backend is **workstream 5**, so Apply and Discuss currently only log.
> The drawer's empty state is therefore expected, not a defect.
>
> **Deliberately deferred:** speaker notes (no domain field exists; the drawer is a
> one-tab shell so notes drop in without restructuring) and the `@slide` reference
> chip (§6.1, **workstream 7**).
>
> **Note for workstream 8:** the stage iframe sets `pointer-events: none` and
> `tabIndex={-1}`, because focus inside it never delivers keydown to the parent —
> inline editing must put its editable regions in the parent document or revisit the
> focus/keyboard model. `docs/technical/slide-viewer.md` has the detail.

- Replace the scroll-through-all `SlidePanel` with a **single-slide stage** paged
  through like PowerPoint/Google Slides (◀ ▶, thumbnail rail, keyboard).
- Below the current slide: a **collapsible AI feedback drawer** showing that
  slide's subjective review findings, each with actions: **Apply** (dispatch the fix
  to the builder), **Dismiss**, or **Discuss** (pull it into the main chat).
- A badge on each thumbnail/stage indicates slides with open feedback.

### 6.3 Two feedback channels

- **Whole-deck feedback** (narrative arc, "no conclusion," cross-deck design) →
  posted by the supervisor in the **main chat**.
- **Per-slide feedback** → lives in that slide's **drawer**.

### 6.4 Direct-editing redesign — inline WYSIWYG

The current HTML editor is broken and is folded into this rebuild. The redesigned
direct-editing experience is **inline WYSIWYG on the stage**:

- Click text on the slide to edit it in place.
- Select an element to tweak / move / resize.
- Drag to reorder slides (on the thumbnail rail).
- A **raw-HTML view is retained as a power-user escape hatch.**

This is the largest front-end build in the PRD and composes directly with the
flip-through stage and the feedback drawer.

---

## 7. Review, remediation & the unified observability layer

### 7.1 The three review agents

Run as parallel graph nodes after any build. **REVISED 2026-09-18 (§16):** each is a
graph *participant*, not an MLflow scorer. A scorer grades a recorded interaction as an
observer; these reviewers run inline and synchronously and their findings drive the
remediation loop, so the two cannot be one runtime object without making the graph
depend on an evaluation harness. What review and evaluation genuinely share is the
**prompt text and the criteria registry** (`src/domain/finding.py`) — a weaker claim
than "one codebase", and the only one that holds.

Verdicts are persisted in Lakebase, not logged as MLflow assessments.

| Agent | Checks | Objective (auto-fix) | Subjective (surface) |
|---|---|---|---|
| **Content fidelity** | Do slide claims reflect the chat + source data? (generalizes today's numbers-only judge to any content) | A number/claim contradicts the source | "This claim is unsupported by anything we discussed" |
| **Design** | Cross-deck consistency (uniform bullet markers, fonts, color usage); within-slide consistency; **render correctness** (stretched images, overflow, contrast) | Rogue color/marker/format, stretched image, overflow | "This layout is busy; consider splitting" |
| **Narrative** | Deck-level: flow, real story vs. bullet-lists, strong conclusion, audience fit | — (mostly subjective) | "Slide 7 breaks the arc"; "no real conclusion" |

### 7.2 Objective vs. subjective

- **Each review agent self-classifies each finding**, returning a structured
  verdict with an `auto_fixable`/severity flag. The agent that found the defect
  knows best whether it is mechanical. (No separate classifier.)
- **Objective** findings are "objectively incorrect" (a slide randomly switched
  colors or formats, a broken render) → auto-remediate.
- **Subjective** findings are judgments ("this slide doesn't fit the narrative") →
  surfaced to the user, never silently applied.

### 7.3 The remediation loop

1. Builder produces/edits slide(s).
2. Review agents run in parallel.
3. Findings are classified objective vs. subjective.
4. **Objective** → supervisor re-invokes the builder with targeted fix
   instructions → re-review. **Bounded to N iterations** to prevent loops.
5. **Subjective** → collected, not applied; routed to chat (deck-level) or drawers
   (slide-level).
6. Loop exits when no objective findings remain or the iteration cap is hit.

- **Remediation trust:** auto-fixes pass back through the *same* review agents
  before reaching the user, so a bad fix cannot slip through.
- **Always-on for objective defects**, but the *list of what was auto-fixed* is
  shown in chat for transparency, along with the iteration count.

### 7.4 Review must not make the product feel slower

Adding a supervisor hop, three reviewers and a remediation loop multiplies the LLM
calls per turn. Review is only worth having if it doesn't tax the author, so this is
a product requirement rather than a tuning concern:

- **Show the deck first.** Builder output renders as soon as it exists; reviewers run
  against the rendered deck and their findings arrive afterwards into the drawer and
  chat. The user is reading slide 1 while review completes — the cost is masked by
  the UX rather than paid in a progress spinner.
- **Reviewers run concurrently**, not in series.
- **Progressive disclosure.** Review state is visible per slide (reviewing → clean →
  findings) so the deck is never ambiguously "done."
- **Auto-remediation is bounded** and must not hold the deck hostage: if the loop is
  still working, the user sees the current deck plus the fact that fixes are in
  flight.
- **The user can proceed regardless** — reviewing must never block editing, export or
  presenting. A "good enough, go now" escape is always available.

The one-shot path (§9.2) inverts this trade deliberately: no human is waiting, so it
runs the full loop to completion before returning.

Two consequences worth noting for the specs: current `max_tokens` / `timeout` values
are artifacts of one-shot full-deck generation and are expected to change as
generation becomes incremental; and per-agent model choice (a cheaper model for
reviewers) is deferred in §8.1 but is the obvious lever if review cost becomes the
constraint.

### 7.5 Agent-quality CI gates

> **REPLACED IN FULL, 2026-09-18 — see §16.** This subsection was "MLflow 3 GenAI
> rebuild". MLflow is removed from the product and is not adopted in a development rig
> either; the reasoning is in §16. Its three original bullets are disposed of as follows:
> always-on tracing — **struck**; eval harness — **becomes the fixture gate below**;
> production monitoring and feedback — **struck**.

The quality-and-trust evidence is a **fixture-based CI gate over the review agents**, not
an observability stack. It asks one question with an objective answer: *does the reviewer
catch defects that are definitely there, and refrain from reporting defects that are
definitely not?*

- **Two halves, and the second matters more.** **Recall** fixtures are deliberately broken
  slides and decks that must be caught. **Precision** fixtures are deliberately clean ones
  that must yield no findings. Both reviewer defects recorded in workstream 4e's closing
  note are false positives, so a recall-only gate would score those reviewers as flawless.
- **The ruler is independent of the thing under test.** Fixtures carry known-correct
  answers, so the metric does not move when a prompt changes. Had the production reviewer
  also been the scorer, a reviewer prompt change would move the number for two
  indistinguishable reasons — the deck changed, or the ruler changed — which makes
  evaluating the reviewers incoherent.
- **It extends what already exists.** `tests/agentic` (layer 3) already calls `call_skill`
  against a real serving endpoint behind three deliberate gates: a `live` marker for
  selection, a reachability `skipif` for safety, and an unconditional skip for honesty
  while the prompts are placeholders. The additions are a few dozen fixtures across the
  nine criteria, assertions on the **content** of output fields rather than their validity,
  and a path-filtered trigger keyed to changes in prompts, skills, criteria or the graph.
- **Fixtures are hand-authored, and that carries a risk worth naming.** Without a rendering
  oracle a fixture's label is the author's belief, not a measurement. So recall fixtures
  must be *unambiguously* broken rather than marginally so, and any numeric threshold must
  be derived at runtime from `_SLIDE_FRAME_CONSTRAINTS` — as
  `tests/agentic/gates.py::frame_constraint_numbers` already does — so a fixture cannot go
  stale when the constraints change. A generated fixture factory was considered and
  rejected as unnecessary machinery at this stage.
- **Human feedback still closes the loop, one hop longer.** Drawer Apply/Dismiss remains in
  Lakebase (`feedback_conversations`, `survey_responses`) and is exported into fixture
  corpora on demand, rather than logged to MLflow on a live path.

**This cannot be validated yet, and that is the honest status.** See §16 for the three
blockers: the repository is in a personal account so CI cannot hold Databricks credentials;
the seven prompts are placeholders so no assertion can be calibrated; and `test.yml`
triggers only on `main` and `release/**`, so nothing based on `feat/langgraph-core` runs CI
at all.

---

## 8. Platform integration

### 8.1 Unity AI Gateway — scoped to usage tracking & rate limits

- **All** LLM calls (supervisor, builder, every review scorer) route through a
  Gateway-fronted endpoint instead of the hardcoded model.
- Delivers **per-user / per-session token & cost tracking** and **rate limiting**,
  surfaced in the admin usage dashboard.
- Side-effect: the endpoint stops being hardcoded and **moves into app config**.
- **Deferred (future):** per-agent model routing (e.g. a cheaper model for review,
  a stronger one for generation) and Gateway guardrails as a replacement for the
  custom regex safety gate. The endpoint abstraction makes both cheap to add later;
  they are explicitly out of scope for the first pass.

### 8.2 ~~Unity Catalog requirement (cross-cutting tradeoff)~~

> ❌ **STRUCK IN FULL, 2026-09-18 — see §16.** Tellr remains **UC-agnostic**. No Unity
> Catalog catalog or schema is required: not in app config, not in the setup or
> provisioning flow, not in `app.yaml`, and not on upgrade. The workstream this section
> created (§10, stream 1) is deleted.
>
> This section rested on three premises, each of which proved false or stale:
>
> 1. That the optional trace binding existed as a workaround for "an egress restriction in
>    FEVM workspaces". Current Databricks documentation for storing MLflow traces in Unity
>    Catalog carries no preview or beta gating and does not mention regional
>    artifact-storage egress. `_is_uc_trace_backend_unavailable_error` guards a condition
>    that has since become generally available — dead code, not a tradeoff.
> 2. That existing deployments "will need a UC schema provisioned on upgrade". No trace
>    data needs moving; there was no migration. The only real constraint is that an
>    experiment's trace location binds at creation and can never be reassigned, which a
>    newly created experiment satisfies trivially.
> 3. That UC was non-negotiable *because* "the review agents are MLflow scorers, so review,
>    evaluation and observability are one system". They are not scorers — see §7.1 as
>    revised — so the justification does not stand.
>
> Independently of all three, tracing user work in production would write data fetched under
> a user's own on-behalf-of token into a store governed by coarser grants, durably and
> irreversibly (UC trace tables do not support deleting individual traces). That alone rules
> it out. See §12.1's extended OBO constraint.

---

## 9. Data flow, the one-shot door & error handling

### 9.1 Conversational turn

User message → supervisor (graph, checkpointed state = session) → either a
chat-only reply or delegation to the builder → review loop → objective auto-fixes →
subjective findings routed to chat (deck-level) or drawers (slide-level) → all
streamed over the existing SSE channel.

### 9.2 One-shot turn (MCP / skills)

Single prompt → enter graph → run generate → review → remediate to completion →
return finished deck + a review summary. Interrupts disabled. **This preserves the
`create_deck` / `edit_deck` contract**, so the TAP builder, DAIS agenda curator, and
KPMG deck skills keep working with no changes on their side. One engine, two front
doors.

### 9.3 Error handling

- **Review-loop iteration cap** prevents infinite remediation.
- **Builder failures degrade gracefully:** return the best available deck plus the
  surfaced problem; never hang.
- **Gateway rate-limit responses** are surfaced as a clear "slow down / quota"
  message, not a 500.
- **Observability is non-fatal:** a tracing/logging failure must never break a user
  turn — it is swallowed, logged, and the turn proceeds.

---

## 10. Workstream decomposition

Migration posture: **many small PRs, big-bang release.** Work is decomposed into
independently-mergeable workstreams that land behind flags / on an integration
branch; **we do not release until the whole system is coherent.** Each workstream is
its own spec → plan → implementation cycle later; this PRD is the umbrella that
defines the end state and the seams.

| # | Workstream | Depends on | Size | Notes |
|---|---|---|---|---|
| 0a | ✅ **DONE** — **Row-per-slide schema** — `session_slides` (one row per slide), per-row verification, deck-spec column | — | M | Merged 2026-08-12 (PR #235). Prerequisite for 4; see §10.2 |
| 0b | ✅ **DONE** — **Dependency stack upgrade** — langgraph 1.2.10 pinned and proven on the Apps build proxy | — | S | Merged 2026-08-12 (PR #236). Prerequisite for 4; see §10.2 |
| 1 | ❌ **DELETED (2026-09-18, §16)** — ~~**UC-in-setup**~~ | — | — | Existed only to provision UC for MLflow tracing. §8.2 struck, so there is nothing to provision. Row kept so numbering and history stay legible |
| 2 | **Gateway endpoint abstraction** — de-hardcode the model, route via Gateway, usage tracking & rate limits | — | S | Independent |
| 3 | 🔄 **REDEFINED (2026-09-18, §16)** — **Agent-quality CI gates** — fixture-based recall/precision gate over the review agents, extending `tests/agentic`; plus deletion of all MLflow code from the product | — | S | Was "MLflow rebuild". No longer depends on 1. **Cannot be validated until the repo leaves a personal account and the prompts are authored** — see §16 |
| 4 | ✅ **DONE** — **LangGraph core** — supervisor + builder, deck-spec state, two front doors; runs *alongside* the monolith | 2 | L | The big one. Merged 2026-09-16 into `feat/langgraph-core` as five workstreams, ws4a–ws4e (merge `60789f72`). **Two deliberate exclusions:** the monolith is not deleted, and MCP stays on it — both belong to a later PR. See `docs/superpowers/plans/ws4e-HANDOVER.md` |
| 5 | **Review subsystem** — 3 agents + remediation loop | 4 | L | ~~3, 4~~ — no longer depends on 3 (§16). ~~as scorers~~ — reviewers are participants, not scorers (§7.1 as revised). Much of this shipped incidentally in workstream 4: the three reviewer nodes, the nine-criterion registry with its `objective` predicate, and the foreman→fixer→fix_reviewer loop all exist |
| 6 | ✅ **DONE** — **Flip-through viewer + feedback drawer** — new slide stage + AI feedback UI | — (stub) | M | Shipped on `feat/flip-through-viewer`; see §6.2 for what landed vs. deferred |
| 7 | 🟢 **BELIEVED DELIVERED by 4 and 6 without being worked on — needs a revisit, not a build** — **Conversational multi-target editing** — supervisor intent parsing, retire checkboxes | 4 | M | **Delivered incidentally:** checkboxes and `SelectionContext` are gone (6); the graph is invoked with `{"architect_message": message}` **and nothing else**, so §6.1's "no selection state and no `slide_context` round-trip" holds *structurally* rather than by discipline; and **the operator tested multi-target editing on 2026-09-16 and it behaved as expected.** §6.1's "@slide" chip is **dropped** — see §6.1. **What is genuinely open is whether this workstream is still needed at all**, and that cannot be settled yet: the seven agent prompts are **placeholders**, so today's behaviour is not the behaviour that ships. **Revisit once real prompts land** — with a bias toward closing it rather than planning it. **The one real gap either way: no automated test covers multi-target editing**, so it can regress in silence |
| 8 | **Inline WYSIWYG editor** — click-to-edit, move/resize, drag-reorder, raw-HTML escape hatch | 6 | L | Largest FE build |

### 10.1 Sequencing notes

- **0a and 0b** ✅ **are done.** They were not in the original decomposition — the
  workstream-4 design spec identified them as prerequisites that had to land and be
  verified against live data *before* the core rewrite, so a bad deck could be
  attributed to one change or the other rather than both at once.
- ~~**1 and 2** are small, independent, and safe to land first.~~ **2** is; **1 is deleted**
  (§16).
- ~~**3** depends on UC being available (1).~~ **3 depends on nothing**, and is now a CI
  gate rather than an MLflow build (§16). Its blockers are environmental, not sequential:
  a non-personal repository so CI can hold credentials, and authored prompts so its
  assertions can be calibrated. **It should be built together with prompt authoring** — a
  gate written before its prompt is a guess, and a prompt written without a gate is
  unmeasurable. See §12.1's closing note on that unassigned work.
- **4** ✅ **is done** (2026-09-16) — the keystone. **So 7 is unblocked, and 5 is blocked
  only by 3.** It landed as five stacked workstreams rather than one PR, because the
  single-PR plan was reviewed to a three-round limit without converging: severity never
  decayed and four of round 3's nine blocking findings were regressions the loop's own
  fixes had introduced.
- **6** ✅ **is done** — it was built against a stub deck and merged independently,
  as planned. **8** builds on **6** and is now unblocked.
- **7** 🟢 **appears to be delivered without having been worked on, and the next action is a
  revisit rather than a build.** 6 removed the selection state, 4 gave the graph a
  language-only entry point, and the operator has since driven multi-target editing and
  found it behaves as expected. The "@slide" chip is dropped as unnecessary.
  **Why it is not simply ticked:** the agent prompts are placeholders, so the behaviour
  observed is not the behaviour that ships, and **this workstream's necessity needs
  significant revisit once the real prompts land.** The likely outcome is that it closes
  with no build at all — but that is a judgement to make against real prompts, not against
  these. Note also that nothing automated covers multi-target editing, so whatever is
  concluded, the behaviour is currently unguarded against regression.
- **Two things 4 deliberately left, which the later PR that deletes the monolith owns:**
  removing `src/services/agent.py` and the `USE AGENT MODE` trigger phrase, and moving the
  MCP one-shot door (§9.2) onto the graph.

**Where the work physically is.** All of it sits on the integration branch
`feat/langgraph-core`, which is **586 commits ahead of `main` and 0 behind**. `main` is
still at the 0.4.1 bump. Unreleased there: workstreams 0a, 0b, 6 and 4, the Design System
Library, and six SDR-4437 security PRs. That is this section's "big-bang release" posture
working as intended, but it is worth stating plainly rather than inferring from the
absence of a note: **nothing in this table has reached `main`.**

### 10.2 What the prerequisites delivered (and what they oblige workstream 4 to do)

Both merged into `feat/langgraph-core` on 2026-08-12 and verified on a Lakebase branch
forked from production, not just locally.

**0a — row-per-slide schema (PR #235).** The deck's source of truth is now one row per
slide, keyed `(session_id, position)`:

- Parallel per-slide writes no longer contend on a single optimistic-locked row — the
  precondition for the fan-out in §4.
- Verification moved off the shared `verification_map` blob onto the row, keyed by
  content hash and **merged, never overwritten**, so a verdict still survives
  regeneration. This is the mechanism §12.1's "finding persistence" constraint asked for;
  drawer findings can now key off the same field.
- `SlideDeckVersion` deliberately stays a JSON blob — the right shape for an immutable
  save-point snapshot, and it keeps §13's restore promise cheap.
- `SlideWriter` (`src/api/services/slide_repository.py`) is the published write API for
  the graph. Constructible with no arguments, and deliberately **no optimistic lock on
  the slide row** — one reviewer owns one position, so there is nothing to contend with.
- A dual-write / dual-read period keeps `deck_json` current, so an older build still
  reads decks and pre-cutover rollback works.
- The data backfill runs **automatically at app startup**, not as a manual script.

**0b — dependency stack (PR #236).** langgraph 1.2.10 / langchain 1.3.14 /
langchain-core 1.5.3 / langgraph-checkpoint 4.1.1, with mlflow reconciled to 3.14.0 —
which closes §12.1's "dependency resolution risk" and the live mlflow pin conflict named
there. Resolution was proven against the Databricks Apps build proxy, and the pins were
applied to `packages/databricks-tellr-app/pyproject.toml` — the file the BUILD phase
actually resolves.

**Obligations this creates for workstream 4:**

- The checkpointer must be a **custom `BaseCheckpointSaver` over the existing SQLAlchemy
  engine**, not `langgraph-checkpoint-postgres`. That package takes a raw psycopg
  connection, which never traverses the `provide_token` listener that delivers Lakebase's
  OAuth token — its writes would begin failing about an hour into every deployment. This
  is the concrete resolution of §12.1's multi-worker/checkpointer correctness point.
- A failed slide position is marked by a **hash-keyed** `verification_record` carrying
  `error: true`; detect it via `is_placeholder_record`, **not** an HTML class.
- `SlideWriter` updates rows but not `deck_json`. The rollback guarantee for slide
  *content* therefore holds only while it has no production callers — workstream 4 is
  when that stops being true, so it must either write through to `deck_json` or accept
  and document the loss.
- Orphan rows above the slide count are pruned by every write path; the graph's
  "all positions committed" predicate can rely on that.

---

## 11. Reused infrastructure (explicitly *not* rebuilt)

The rebuild is of the **agent core and its experience**, not the whole app. These
subsystems are reused and must keep working:

- **Export** (PPTX via huashu, Google Slides).
- **Sessions & persistence** (Lakebase/Postgres, save points).
- **Permissions** (Unity Catalog OBO enforcement, dual-client SP/user auth).
- **Data tools** (Genie, MCP, vector search, model endpoints, agent bricks) — these
  become tools shared by the builder and review agents; their internals are largely
  preserved.
- **Image library, comments, feedback collection, read-only viewer, presentation
  mode.**

---

## 12. Open questions / to resolve in per-workstream specs

- Deck-spec schema: exact structure of the structured shared state (outline model,
  per-slide fields, how it maps to the rendered HTML).
- Review-loop iteration cap value and back-off behavior.
- How auto-fixed vs. surfaced findings are persisted across turns and save points.
- Gateway endpoint provisioning: is it FE-provided, per-workspace, or app-managed?
- ~~UC schema migration UX for existing production deployments.~~ ❌ **MOOT (§16)** — no UC
  requirement, so no migration.
- Whether/when to promote specialist agents to governed serving endpoints (the
  showcase-vs-latency tradeoff).

### 12.1 Known implementation constraints (for the workstream specs)

Not PRD decisions, but known facts that the relevant specs must address rather than
rediscover. Recorded here so they are not lost between documents.

- **Multi-worker state coherence.** Production runs multiple uvicorn worker
  *processes*, so any graph/session state shared across requests must be visible to
  all workers (i.e. database-backed) or able to detect its own staleness. This has
  been a repeated source of shipped bugs; see the `tellr-code-review` skill. Affects
  workstream 4 (LangGraph core) directly — the checkpointer choice is a correctness
  issue, not a preference.
  **Narrowed by workstream 0a/0b:** the row-per-slide schema removes the write-contention
  half of this (parallel writers now touch distinct rows, not one optimistic-locked row),
  and §10.2 fixes the checkpointer decision — a custom saver over the existing SQLAlchemy
  engine, because the official Postgres saver bypasses the OAuth token listener. What
  remains is genuinely in-process cached state, which is a web-app concern rather than a
  database one.
  ✅ **CLOSED by workstream 4 (2026-09-16), and closed by measurement.** The custom saver
  landed and goes through the shared engine by design, never holding its own connection —
  which is the only reason the OAuth-refresh gate above can be observed at all. A layer-4
  suite proves the multi-worker property against a real PostgreSQL rather than SQLite:
  fifteen parallel row writes land, the deck-level version counter still rejects a stale
  write, four concurrent sweepers claim a marker exactly once, **the release query is
  correct from a different process with a cold cache**, and **a checkpoint written in one
  process is readable in another**. The last two are the ones that would fail if anyone
  reintroduced in-process buffering, and their sabotage was chosen so that it
  discriminates: the first process buffers instead of persisting, and the child then sees
  nothing.
  **One residual, filed rather than fixed:** a race between marking a deck dirty and
  claiming it is reproduced and banked as a strict expected-failure, so whoever fixes it is
  forced to delete the record. And checkpoint growth is unbounded — one whole-state blob per
  checkpoint and an uncapped findings list, so growth is super-linear in turns, with no
  retention policy. `delete_thread` exists but only a user action calls it.
- ✅ **RESOLVED (workstream 0b, PR #236) — Dependency resolution risk.** The `mlflow`
  pin conflict between `requirements.txt` and `pyproject.toml` is reconciled (3.14.0),
  and the langgraph 1.2.10 stack is pinned and proven to resolve on the Apps build
  proxy. **One correction worth carrying:** the repo-root `requirements.txt` and
  `pyproject.toml` are **not** on the Apps BUILD path — `deploy_local.py` emits a
  requirements file containing only `databricks-tellr-app==<version>`, so the closure
  that actually gets resolved is the one in
  `packages/databricks-tellr-app/pyproject.toml`. A dependency change that misses that
  file passes every local test and ships the old stack. That file also deliberately
  leaves leaf transitives ranged so the Apps base image can satisfy them — do not
  "tidy" it into a fully-pinned closure.
  **Further reduction now available (§16.6, item 5):** with MLflow out of the product,
  the `mlflow[databricks]` extra — and possibly `databricks-agents` plus three cloud
  SDKs — may leave the closure entirely. Prove it on the build proxy, not locally.
- ⚠️ **The seven agent prompts are PLACEHOLDERS, and several judgements in this document
  are provisional until they are not.** Workstream 4 shipped substantive, functional
  instruction text for the architect, analyst, builder, reviewers and fixer, but none of it
  has been prompt-engineered — `src/core/skills/__init__.py` says so in its own docstring.
  Consequences worth holding in mind rather than rediscovering:
  - **Deck quality is not yet evidence of anything.** Judge the machinery, not the prose.
  - **Workstream 7's necessity cannot be settled** against these prompts; see §10.1.
  - **Workstream 5 inherits this directly** — review *is* eval, and a scorer built against
    placeholder reviewers measures the placeholder.
  - The layer-3 test suite exists, is discoverable by one command, and **ships skipped for
    exactly this reason**. Enabling it is a workflow change plus deleting one gate line.
    **Do not weaken a layer-3 assertion to make a placeholder satisfy it** — a skipped
    honest test beats a passing dishonest one.
  **Authoring the real prompts is unassigned work and is not in any workstream above.**

- **Security surface of review agents.** Review agents read untrusted deck content
  and tool output, and their findings feed instructions back to the builder. The
  existing `<untrusted-data>` wrapping/injection scanning and the output safety gate
  must extend to cover reviewer input and remediation output — including re-gating
  auto-remediated HTML. Affects workstream 5.
- **OBO propagation.** The user's token must reach tool calls made from any agent in
  the graph, and deck/profile permission checks still apply. Affects workstream 4/5.
  **EXTENDED 2026-09-18 (§16): OBO-derived data must not be written to any store whose
  access control differs from the data's own.** Tool output reaches the agents under the
  user's own token, so persisting it anywhere governed by coarser grants makes it
  readable by principals holding no grants on it. This binds all logging, observability
  and telemetry work, not only the agent graph, and it is what ruled out production
  tracing independently of every other argument in §16.
- **Behavioural regression checklist.** The regex intent rules being retired
  (RC10–RC15 and related) each encode a previously-shipped bug fix. They are a test
  checklist for the supervisor's intent handling, not merely dead code to delete.
  Affects workstream 7.
- ✅ **MECHANISM DELIVERED (workstream 0a, PR #235) — Finding persistence.** Verification
  now lives on `session_slides.verification_record`, keyed by content hash and merged
  rather than overwritten, so a verdict survives regeneration *and* an edit-then-revert
  finds the earlier verdict again. `restore_version` re-materialises rows and merges
  verdicts back, so the save-point lifecycle is defined. Drawer findings should reuse this
  field rather than inventing a parallel store. **Still open:** whether drawer findings and
  reviewer verdicts share one record or sit side by side, and how a finding is retired once
  fixed.
  *Non-obvious property to preserve:* a record belongs to a **slide, not a position** — on
  reorder the whole record travels with its slide. Writing per-position instead silently
  attaches one slide's verdict to another (this shipped as a defect during 0a and was
  caught only by a whole-branch review).
- **Testing non-determinism.** A multi-agent core needs a stated approach to testing
  non-deterministic flows, distinct from the eval harness (which measures quality,
  not correctness).

---

## 13. Continuity for existing users

The rebuild changes the core and the primary UI of a live app (v0.4.1) with real
dependents. What existing users are entitled to on the day of the big-bang release:

- **Existing decks and sessions open and remain editable.** Decks are HTML; the new
  engine must adopt a deck it did not author, including one with no deck spec —
  inferring or back-filling structure rather than refusing or silently rebuilding it.
- **Save points and version history survive** the cutover and remain restorable.
- **Sharing, contributors, comments and read-only viewer links keep working**,
  including links already circulated.
- **Programmatic callers are unaffected** — `create_deck` / `edit_deck` contracts
  hold (§9.2), so TAP, DAIS and KPMG skills need no coordinated change.
- **Export parity** on day one: PPTX and Google Slides output no worse than current.
- **The UI change is significant and needs telling.** Checkbox selection disappearing
  and the viewer becoming flip-through are visible, habit-breaking changes. In-app
  orientation on first use after upgrade, plus updated docs, are part of the release —
  not an afterthought.

**Deliberately not offered:** a toggle back to the old viewer or the old selection
model. Maintaining both defeats the rebuild's purpose; the old path is retired.

---

## 14. Risks

Product-level risks. (Technical execution risks belong in the workstream specs.)

| Risk | Why it matters | Response |
|---|---|---|
| **Big-bang release** — nothing ships until the whole system is coherent | Long period without user feedback; a wrong assumption compounds unseen | Workstreams merge continuously behind flags; dogfood the integration branch internally well before release |
| **Conversational agent underperforms the deterministic path** | A supervisor that "chats" but produces worse decks than today's direct HTML emitter is a net loss | Success criteria include no-regression on deck quality for one-shot callers; eval harness gives evidence rather than opinion |
| **Review fatigue** — too many subjective findings | Users learn to ignore the drawer, and the quality pillar dies as decoration | Objective defects are fixed silently, not reported; subjective findings must clear a usefulness bar; findings are dismissible and must not nag |
| **Latency perceived as regression** | Even masked, more LLM calls per turn risks feeling slower than today | §7.4 is a hard product requirement, not a nice-to-have; "go now" escape always available |
| **Cost per deck rises materially** | Review multiplies calls; Tellr is FE-wide, so unit cost matters | Gateway usage tracking (§8.1) makes cost visible from day one; per-agent cheaper models are the deferred lever (§8.1) |
| ~~**Install friction from mandatory UC**~~ ❌ **RETIRED (2026-09-18, §16)** | ~~Requiring UC removes Tellr's easy-install advantage and could slow FE adoption~~ | **Risk eliminated rather than mitigated.** §8.2 is struck and Tellr stays UC-agnostic, so the easy-install advantage is kept |
| **Two large UI builds** (flip-through viewer, inline WYSIWYG) | The biggest schedule risk; WYSIWYG editors are notoriously deep | Viewer and editor are separate workstreams (§10 streams 6 and 8) so the viewer can land and be useful without the full editor |

---

## 15. Non-goals (this PRD)

- Per-agent model routing and Gateway guardrails (deferred; see §8.1).
- **MLflow 3 GenAI adoption, in the product and in a development rig (see §16).**
- Rewriting export, permissions, or the data-tool internals.
- Detailed implementation specs — each workstream produces its own.

---

## 16. Amendment — 2026-09-18: MLflow is an evaluation concern, not a product feature

**Status:** Agreed. The replacement work (§7.5 as revised) is **parked**, blocked on the
three items in §16.5. This section supersedes §8.2 in full and revises §1.1, §3, §4.2,
§7.1, §7.5, §10, §10.1, §12, §12.1, §14 and §15.

### 16.1 The decision

MLflow is removed from Tellr's production path, and is not adopted in a separate
development rig either. What this PRD called the "MLflow rebuild" (§10, stream 3) becomes
**agent-quality CI gates**: fixture-based tests measuring whether the review agents catch
defects that are definitely present and refrain from reporting defects that are definitely
absent. **UC-in-setup (§10, stream 1) is deleted** — it existed solely to provision Unity
Catalog for MLflow tracing, and there is nothing left to provision.

### 16.2 Why the original position was wrong

The PRD asked how to implement MLflow in the product. The question it should have asked is
how we know Tellr's agents are good. MLflow is an evaluation tool, and evaluation belongs in
an evaluation context rather than in software a customer installs. Databricks does not
retain a customer's sensitive processing logs; Tellr should not retain traces of a field
engineer's work in order to observe itself.

Five findings support this, each weakening the original position independently.

**1. §8.2's factual premises were stale.** Detailed in §8.2's own strike note. In summary:
the fallback it wanted retired guards a condition that has since become generally available;
the "migration" it wanted handled does not exist, because no trace data needs moving; and
its justification rested on the scorer claim refuted in point 3.

**2. Production tracing launders Unity Catalog entitlements.** Tool results reach the agents
under the user's own on-behalf-of token, so a user sees only data they hold UC grants for.
Writing those results into a trace store governed by coarse table grants makes them readable
by principals holding no grants on the underlying data — durably, because UC trace tables do
not support deleting individual traces (removal is direct SQL against Delta). MLflow 3.14
does provide a masking hook (`mlflow.tracing.configure(span_processors=...)`, applied before
export), but the sensitive payload here is free-form — Genie synthesis text, and slide HTML
that may embed customer figures — so only an allowlist is defensible, and an allowlist
excludes precisely the content that made the trace worth keeping. **This consideration alone
rules out tracing user work in production**, independently of everything else here. It is
recorded as a standing constraint in §12.1.

**3. Review agents cannot be MLflow scorers.** §7.1 asserted that each review agent "is
implemented as an MLflow 3 GenAI scorer", and used that to make tracing non-negotiable. A
scorer grades a recorded interaction — offline across a dataset, or sampled from production
traces. It is an observer. The graph's reviewers are participants: they run inline and
synchronously, and their findings drive the remediation loop. The two cannot be one runtime
object without making the graph depend on an evaluation harness. See §7.1 as revised.

**4. A shared artefact would invalidate the measurement.** If the production reviewer were
also the evaluation scorer, changing a reviewer's prompt would move the metric for two
indistinguishable reasons: the deck changed, or the ruler changed. Evaluating the reviewers —
one of the harness's stated purposes — becomes incoherent. The resolution is a ruler
independent of the system under test: fixtures with known-correct answers, measuring
**recall** and **precision** separately. See §7.5 as revised.

**5. MLflow does not survive in a development rig either.** Skill-level evaluation requires
no instrumentation: a test imports `call_skill`, passes a fixture payload, and asserts on the
returned model. `tests/agentic` already works this way with no MLflow present. Retaining
MLflow for a rig would mean maintaining an instrumentation path existing only for
development, in exchange for a user interface over data a committed test baseline already
holds. The one activity where MLflow's tooling genuinely helps — comparing many prompt
variants across many cases — is a one-off exercise suited to a notebook, needing no permanent
place in the codebase.

### 16.3 How the decision was tested

Three independent assessments were commissioned — a skeptic's case, an advocate's case, and a
neutral recommendation — each given the same facts, and none given knowledge of the others or
of the conclusions reached in discussion. All three recommended deferring an MLflow
evaluation harness until real prompts exist, keeping review verdicts in Lakebase, and not
building production monitoring dashboards. **None endorsed mandatory Unity Catalog
provisioning in the install path.** The advocate, briefed to defend the proposal, conceded
that its case rested on fan-out debugging alone.

Two of the three made material factual errors, both traceable to
`docs/technical/mlflow-uc-tracing.md` describing constraints that no longer apply. That
document misled reviewers reading in good faith; it is listed for deletion in §16.6.

### 16.4 What can land, and what it is coupled to

**CORRECTED 2026-09-21.** An earlier draft of this subsection listed the MLflow deletions
and a CI-trigger change as independently landable. Both were wrong; see the two notes below
the list.

Genuinely independent and urgent:

- **Withhold `source_contradiction`** from the build reviewer's generated criteria block, so
  the fixer stops rewriting correct slides against a hallucinated finding (§16.6, item 1).
  A live defect that damages user work on every graph turn, and a small change. **This is
  the only item here that should not wait for anything.**
- **Author the fixtures.** They can be written before they can be run.

Coupled to a UI update, and therefore *not* independent:

- **Removing MLflow from production:** `src/core/mlflow_tracing.py`,
  `src/core/mlflow_agent_spans.py`, `ChatService._ensure_user_experiment` and its
  `mlflow.set_experiment` block, `src/services/evaluation/llm_judge.py`, the
  `mlflow.log_feedback` call in `src/api/routes/verification.py`, the admin judge-backend
  control with the `llm_judge_backend` column, the experiment link at `AppLayout.tsx:750`
  with its `experiment_url` plumbing and `session.experiment_id`, the four `TELLR_MLFLOW_*`
  variables in `app.yaml.template` with `deploy.py`'s substitution machinery, and
  `docs/technical/mlflow-uc-tracing.md`. The monolith's own MLflow calls ride the pull
  request that deletes `src/services/agent.py`.
  Several of these are **user-visible** — the experiment link, the admin judge-backend
  control — so the removal should coincide with a UI update rather than landing on its own.
- **The dependency-closure reduction** (§16.6, item 5) **follows the removal above**, not
  precedes it: the `mlflow[databricks]` extra cannot leave the closure while
  `src/services/evaluation/llm_judge.py` still imports `mlflow.genai`. So the prize is real
  but it queues behind the UI-coupled work.

**Not a blocker, and not a defect: `test.yml`'s trigger set.** Restricting continuous
integration to `main` and `release/**` is **deliberate**, to stop CI filling up. Workstream
4e's closing note (§2) records it as an unowned defect and proposes adding `feat/**`; that
filing rests on a false premise and should not be acted on. The real consequence is simply
that work on `feat/langgraph-core` must be verified **locally** and said to be so — against
failure *causes*, never counts.

### 16.5 What blocks the replacement work

Two blockers, with different scopes — finishing the prompts will *feel* like it unblocked
everything, and it will not. Prompts unblock authoring and local validation of the gate; the
repository move unblocks enforcing it.

1. **The repository is in a personal account.** CI cannot hold Databricks credentials, so the
   live-model gate cannot execute. Until the repository moves, the gate can be written but
   not validated — and *an artefact built and never executed in the environment it was built
   for* is the most expensive failure pattern recorded in workstream 4e's closing note.
2. **The seven agent prompts are placeholders.** No assertion can be calibrated against them.
   This is what layer 3's unconditional placeholder skip exists to make explicit, and it must
   not be weakened to make a placeholder pass.

**Consequently: prompt authoring and the CI gate should be one piece of work with one
owner.** A gate written before its prompt is a guess; a prompt written without a gate is
unmeasurable. Authoring the seven prompts remains unassigned to any workstream in §10 — as
§12.1 already records — and is the natural next workstream, with this gate as its definition
of done.

### 16.6 Defects and opportunities found while investigating

Discovered in the course of this decision and recorded here because they exist nowhere else.

**1. `source_contradiction` is unreachable, and misfiring is not harmless.** `resolved_data`
is a required field of `DeckSpec`, so it is emitted by the **architect**, not the data
analyst. The build reviewer already receives it (`nodes.py:2051`, sourced from
`spec.resolved_data.model_dump()` at lines 575 and 1252). But the architect's instructions
never mention `resolved_data`, `synthesis`, `figures` or `source`, so the field is emitted
schema-valid and empty. The criterion is defined as "only assertable against
`resolved_data`", so it can never be legitimately asserted — and because it is
`objective=True`, a hallucinated finding dispatches the fixer to rewrite a slide that was
correct. Workstream 4e measured three of twelve findings on a real deck as invented
`source_contradiction`.

**Three code comments misdiagnose the cause** — `nodes.py:1731`, the module docstring of
`src/core/skills/data_analyst.py`, and the criterion's own description in
`src/domain/finding.py` — attributing it to a missing field on `AnalystOutput` and an
escalation to workstream 4b. **No schema change is required.** The fix is authoring the
architect's prompt; prose in `resolved_data.synthesis` is very likely sufficient, since the
working per-slide judge compares slide text against raw Genie text and produces usable
ratings. Once `resolved_data` is populated, workstream 4e's ruling that adding it to the
re-review trigger would be "an inert guard" ceases to hold, and that record should be
deleted.

**2. No cross-slide design-consistency criterion exists.** §7.1 promises cross-deck
consistency of bullet markers, fonts and colour usage. The nine criteria contain no such
check: the four design criteria are slide-level, `build_reviewer` receives exactly one
slide's HTML, and `deck_reviewer` is narrative-only and explicitly instructed not to report
slide-level issues. Where a design system is active, consistency arises by construction
through `rogue_colour` judged against the compiled contract; with no design system, a deck
can drift unchecked. **This is the one review capability in this PRD with neither a criterion
nor an agent able to hold it.**

**3. The build reviewer is shown deck-level criteria.** Its criteria block is generated from
the whole registry, so a per-slide reviewer is told about `arc_gap`,
`cross_slide_repetition` and `missing_conclusion` with no instruction to disregard them —
while `deck_reviewer` does receive the converse instruction.

**4. Token usage is discarded at the one point every agent passes through.**
`get_structured_model` returns `model.with_structured_output(schema)`, so `.invoke()` yields
the parsed object and the `AIMessage` — carrying `usage_metadata` — is dropped. No token or
cost capture exists anywhere in `src/`. §3's cost-visibility criterion therefore has no
foundation in the application today. Whether this needs fixing depends on whether workstream
2's Gateway supplies per-user metering at the endpoint; if it does, no app-side capture is
needed at all.

**5. A dependency-closure opportunity.** The app pins `mlflow[databricks]==3.14.0`, whose
`databricks` extra requires `databricks-agents<2.0`, `boto3`, `botocore`,
`google-cloud-storage` and `azure-storage-file-datalake`. `databricks-langchain` requires
only `mlflow>=2.20.1`. Removing the extra may allow `databricks-agents` and three cloud SDKs
out of the closure, along with some of the defensive pins that exist to stop that resolution
graph backtracking during the Apps build. **Must be proven against
`packages/databricks-tellr-app/pyproject.toml` on the Apps build proxy**, since no other
dependency file is on that path.

**6. `docs/technical/mlflow-uc-tracing.md` is stale and actively misleading.** It documents
preview gating and a regional artifact-storage egress requirement that current Databricks
documentation does not carry, and it caused factual errors in two of three independent
reviews (§16.3). Delete it alongside the code it documents.
