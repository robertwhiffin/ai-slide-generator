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

This PRD reframes Tellr from *a slide-generating agent* into **an agentic
slide-authoring system you converse with** — a brainstorming and refinement partner
that produces, reviews, and repairs decks, is fully observable, and is governed by
the platform.

### 1.1 Primary driver

This is a **phased platform re-architecture**, not a single-axis improvement. The
PRD frames the end-state and sequences the work. Three outcomes matter together:

1. **Conversational UX** — an agent you brainstorm and iterate a deck with.
2. **Databricks showcase** — exemplary use of Unity AI Gateway and MLflow 3 GenAI.
3. **Quality & trust** — automated review agents plus real evaluation/observability.

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
- Review verdicts are queryable as MLflow assessments against traces.

**Platform / showcase**
- Every LLM call in the system is attributable to a user and session, with token and
  cost visibility in the admin dashboard.
- A full turn is inspectable end-to-end as one nested trace (supervisor → builder →
  reviewers → tools) with no gaps.
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
  observable as clean nested spans (feeding the MLflow pillar) and replaces the
  imperative control flow of the 1,863-line monolith.
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
- A lightweight **"@slide" affordance** remains: clicking a slide inserts a
  reference chip into the chat so pointing is easy when the user doesn't want to
  type an index. It *augments* natural language; it does not gate it.
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

Run as parallel graph nodes after any build. Each is implemented as an **MLflow 3
GenAI scorer** (`make_judge` / custom scorer), so its verdict is a first-class
assessment logged against the trace. **"Review" and "eval" are one codebase.**

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

### 7.5 MLflow 3 GenAI rebuild

- **Reliable, always-on tracing.** The LangGraph flow emits clean nested spans
  (supervisor → builder → each review agent → tools). A single traced entrypoint on
  LangGraph resolves the async/ContextVar breakage that forced autolog off today.
  **Delete** the direct-judge fallback and the span-auto-skip hacks.
- **Eval harness / regression suite.** A curated evaluation dataset plus the same
  scorers, runnable in CI, to catch quality regressions when prompts/models change.
  This is the "quality & trust" evidence.
- **Production monitoring & feedback.** Dashboards over live traces (quality
  scores, token cost, latency per agent). Structured human feedback (drawer
  Apply/Dismiss, thumbs, edits) logged back to MLflow to close the loop.

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

### 8.2 Unity Catalog requirement (cross-cutting tradeoff)

**Tellr is intentionally UC-agnostic today** — it requires no UC schema, which keeps
deployment simple. Traces to UC are currently *optional*: the app only binds a UC
trace location when `TELLR_MLFLOW_UC_*` is fully configured, and silently falls back
to a plain MLflow experiment when UC linking is unavailable.

**This rebuild makes MLflow tracing to Unity Catalog non-negotiable.**

- A **required UC catalog/schema** is added to app config and to the
  setup/provisioning flow (setup wizard, deploy tooling, `app.yaml`).
- **The existing optional/fallback behaviour is a workaround, not a feature.** It
  exists because of an egress restriction in FEVM workspaces. It is to be **retired**,
  not preserved as a supported lean-install mode.
- **Why non-negotiable:** the review agents *are* MLflow scorers (§7.1), so review,
  evaluation and observability are one system. Making tracing optional would mean
  either a second code path for verdicts or losing a headline feature on lean
  installs. We accept the provisioning friction to keep one code path.
- **What UC actually buys:** traces land in queryable Delta tables, which is what
  makes the eval harness (§7.5) and monitoring dashboards possible at all.
- **A SQL warehouse is *not* required to write traces.** It is an optional additional
  step needed only to *enable production monitoring* over UC-backed traces. Setup
  should treat it as optional and not gate installation on it.
- **Migration concern:** existing deployments will need a UC schema provisioned on
  upgrade. The UC-in-setup workstream (§10, stream 1) must handle this path, not only fresh
  installs.

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
| 1 | **UC-in-setup** — required UC catalog/schema in app config + provisioning; handles upgrade path for existing deployments | — | S | Unblocks MLflow; can land early |
| 2 | **Gateway endpoint abstraction** — de-hardcode the model, route via Gateway, usage tracking & rate limits | — | S | Independent |
| 3 | **MLflow rebuild** — always-on nested tracing + scorer framework; delete fallback/auto-skip hacks | 1 | M | |
| 4 | **LangGraph core** — supervisor + builder, deck-spec state, two front doors; replaces the monolith | 2 | L | The big one |
| 5 | **Review subsystem** — 3 agents as scorers + remediation loop | 3, 4 | L | Review = eval |
| 6 | ✅ **DONE** — **Flip-through viewer + feedback drawer** — new slide stage + AI feedback UI | — (stub) | M | Shipped on `feat/flip-through-viewer`; see §6.2 for what landed vs. deferred |
| 7 | **Conversational multi-target editing** — supervisor intent parsing, retire checkboxes | 4 | M | |
| 8 | **Inline WYSIWYG editor** — click-to-edit, move/resize, drag-reorder, raw-HTML escape hatch | 6 | L | Largest FE build |

### 10.1 Sequencing notes

- **0a and 0b** ✅ **are done.** They were not in the original decomposition — the
  workstream-4 design spec identified them as prerequisites that had to land and be
  verified against live data *before* the core rewrite, so a bad deck could be
  attributed to one change or the other rather than both at once.
- **1 and 2** are small, independent, and safe to land first.
- **3** depends on UC being available (1).
- **4** is the keystone; **5 and 7** build on it. Its data-model and dependency
  prerequisites are now satisfied.
- **6** ✅ **is done** — it was built against a stub deck and merged independently,
  as planned. **8** builds on **6** and is now unblocked.

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
- UC schema migration UX for existing production deployments.
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
- **Security surface of review agents.** Review agents read untrusted deck content
  and tool output, and their findings feed instructions back to the builder. The
  existing `<untrusted-data>` wrapping/injection scanning and the output safety gate
  must extend to cover reviewer input and remediation output — including re-gating
  auto-remediated HTML. Affects workstream 5.
- **OBO propagation.** The user's token must reach tool calls made from any agent in
  the graph, and deck/profile permission checks still apply. Affects workstream 4/5.
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
| **Install friction from mandatory UC** | Requiring UC removes Tellr's easy-install advantage and could slow FE adoption | Accepted deliberately (§8.2); setup must make provisioning as close to one step as possible, and must not additionally gate on a SQL warehouse |
| **Two large UI builds** (flip-through viewer, inline WYSIWYG) | The biggest schedule risk; WYSIWYG editors are notoriously deep | Viewer and editor are separate workstreams (§10 streams 6 and 8) so the viewer can land and be useful without the full editor |

---

## 15. Non-goals (this PRD)

- Per-agent model routing and Gateway guardrails (deferred; see §8.1).
- Rewriting export, permissions, or the data-tool internals.
- Detailed implementation specs — each workstream produces its own.
