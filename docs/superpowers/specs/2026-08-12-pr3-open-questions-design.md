# PR3 (LangGraph core) — resolutions to the spec's open questions

**Status:** Design, approved decisions pending user review
**Date:** 2026-08-12
**Parent:** `2026-08-06-agentification-core-design.md` (the authoritative spec)
**Parent PRD:** `2026-07-30-tellr-agentic-rebuild-prd-design.md` (workstreams 4 + 7)
**Branch:** `feat/langgraph-core`

This document records the decisions needed before
`docs/superpowers/plans/2026-08-09-pr3-langgraph-core.md` becomes executable. It is an
**addendum**: where it and the parent spec disagree, this document is newer and wins;
everything it does not mention stands as the parent spec states it.

Nine questions were resolved (A–I). Two of them (H, I) were unresolved *defects* found
while reading the spec against the code, not gaps the spec knew it had.

**§L was added on 2026-08-18** after main's Design System Library was merged into this
branch. It revises §E1 and §H1 and corrects §E2's mechanism — read it alongside them, not
as an appendix.

---

## 0. Environment: the probe evidence is now current

All runtime facts in the parent spec, the plan, and the `langgraph-verified-behaviours`
memory were measured against **langgraph 1.0.3**. PR2 changed the pins but never the
installed environment, so the shared pyenv was still on 1.0.3 as of this session.

**The shared pyenv was upgraded to PR2's pins** (langgraph 1.2.10, langgraph-checkpoint
4.1.1, langgraph-prebuilt 1.1.0, langgraph-sdk 0.4.2, langchain 1.3.14, langchain-core
1.5.3, langchain-community 0.4.2, langchain-text-splitters 1.1.2, mlflow 3.14.0) and every
load-bearing behaviour was re-probed by executing it.

**Nine of ten reproduce byte-identically:** the superstep barrier (an orchestrator sending
batches of 2 over 5 positions woke exactly 4 times, always on a completed batch); a
`Send`-reached node sees only its payload (`deck_spec` invisible); a static edge out of a
`Send`-reached node collapses 3 branches into **1** invocation; re-fanning with a
conditional edge gives 6 builders → 6 reviewers; `bool({0: None}) is True`; turn-2 state
accumulation survives both a fresh value and a fresh `checkpoint_ns`; `max_concurrency=15`
caps 40 sends at peak 15; OBO ContextVars survive fan-out; no non-serialisable
`configurable` value leaks into checkpoint metadata.

**One changed, and it inverts a planned "fix":**

> `recursion_limit` **defaults to 10007** on 1.2.10, not 25.
> `DEFAULT_RECURSION_LIMIT = int(getenv("LANGGRAPH_DEFAULT_RECURSION_LIMIT", "10007"))`
> (`langgraph/_internal/_config.py:32`). A 100-superstep loop ran to completion with no
> config; an explicit `{"recursion_limit": 5}` still raises `GraphRecursionError`, so only
> the default moved.

Consequence: the plan's `recursion_limit_for(slide_count)` helper returns ~50, which would
**lower** the limit and make the graph fail *earlier* than shipping no config at all.
Review finding F4 is now harmful as written. Either drop the helper or choose an explicit
runaway guard on its own merits — do not "raise" a default that is already 10007.

Also new since 1.0.3: **`Send` accepts a `timeout` keyword**
(`Send(node, arg, *, timeout: float | timedelta | TimeoutPolicy | None = None)`). A
per-branch runtime timeout now exists; §8's stall handling was designed assuming it did not.
It is an implementation option for stall detection (§I), not a design change.

### Test baseline (by cause, never by count)

Recorded before and after the upgrade, because a dependency change is exactly what mutates
a failure *cause* while preserving its count.

| | Pre-upgrade | Post-upgrade |
|---|---|---|
| Result | 20 failed / 2003 passed / 8 skipped | **17 failed / 2006 passed / 8 skipped** |

**The baseline for PR3 is 17 failures across 3 causes:**

| Cause | Files | Count |
|---|---|---|
| `ModuleNotFoundError: No module named 'svgpathtools'` | `test_html_to_pptx.py`, `test_google_slides_converter.py` | 14 |
| deploy-autoscaling assertion mismatch (`assert 'provisioned' == 'autoscaling'`) | `test_deploy_autoscaling.py` | 2 |
| `GenieToolError: Failed to query Genie space after 3 attempts` (live Databricks) | `tests/integration/test_genie_integration.py` | 1 |

The upgrade **resolved** the third pre-existing cause (3 mlflow `trace_location` failures,
caused by mlflow 3.6.0 running tests written for 3.14.0). No new cause appeared; the passed
count rose by exactly those 3.

Two corrections to the brief carried into this session: it described 19 failures in four
files. The real set is 17 in **three** files — `test_mlflow_tracing.py` is now green, and
`test_genie_integration.py` was missing from the list. The SVG family's cause is a missing
`svgpathtools` module, not Cairo.

**Any 18th failure, or any change to one of those three causes, is a regression PR3 caused.**

---

## A. The seven skill prompts

Zero of the seven exist; the substance of plan Phases 2–3 is `[To be filled in Phase 2]`.
This is the single largest gap and it is **content, not code**.

**Reusable material:** `src/core/prompt_modules.py` holds ~10KB across 11 named blocks.
`CHART_JS_RULES` (1470 chars), `EDITING_RULES` (3731), `SLIDE_GUIDELINES` (708),
`IMAGE_SUPPORT` (908) and `HTML_OUTPUT_FORMAT` (982) are directly reusable by the builder
and fixer. The architect and all four reviewers are net-new writing.

### A1. Authoring: draft-then-review, one skill at a time

Each skill is drafted, reviewed by the user, and corrected before the next begins.
Sequential rather than one batch pass, because these prompts *are* the product, and because
the skills share fragments — a correction to the builder's CSS-contract language must
propagate to the fixer, which only works if the builder is settled first.

**Consequence for execution: prompt authoring is not subagent work.** It is seven
human-in-the-loop checkpoints in a working session. The plan must schedule it as such and
must not dispatch it in parallel.

Suggested order (dependency, not preference): `architect` → `builder` → `fixer` →
`build_reviewer` → `fix_reviewer` → `deck_reviewer` → `data_analyst`. The architect first
because its deck-spec output is every downstream skill's input; reviewers after builders
because a reviewer's rubric is the builder's brief.

### A2. Reviewer criteria: start minimal and objective-heavy

Review criteria have no upstream source by design — §4.2 keeps them out of the deck spec so
the architect cannot author the standard it is judged against. They are invented here.

The initial criteria set is **few, sharply defined, and weighted toward auto-fixable
defects**: overflow, contrast failure, rogue colour outside the contract, stretched or
distorted image, a figure contradicting its cited source. Subjective criteria are admitted
sparingly.

Rationale: PRD §14 names **review fatigue** as a live risk — "users learn to ignore the
drawer, and the quality pillar dies as decoration." A small objective-heavy set makes most
findings auto-fixed and invisible, which is the behaviour PRD §3 wants. §4.2 already states
that extensibility comes from adding criteria to the skill, so starting small is cheap to
grow and expensive to reverse.

---

## B. Spec propagation (§4.4 / §4.5 / §4.6)

### B0. Correction to the parent spec's framing, and to this session's first reading

§4.5 claims provenance needs no stored flag because "origin is known from the code path."
My first reading called this broken for five of §4.4's seven triggers, on the grounds that
the graph will also reorder, duplicate, delete and restore slides through the same service
code a human uses (`chat_service.reorder_slides` at `:2520`, `update_slide` `:2605`,
`duplicate_slide` `:2684`, `delete_slide` `:2755`).

**That overstated it.** The rebuild cycle can only close if an *agent-caused HTML change*
fires the spec-update trigger. Of the seven triggers, only two touch slide HTML: the human
`PATCH /slides/{index}` route, and the graph's `SlideWriter` write. Those two are genuinely
structurally distinct, so **the cycle break holds as specified.**

Reorder, duplicate and delete change deck *structure*, not slide HTML. They trigger a
narrative-arc re-description, which is correct and terminating whoever caused it.

So the real defect is smaller and different in kind:

- **Cost, not correctness.** Agent-driven restructures fire a redundant arc review.
- **One genuine edge:** version restore replaces whole-deck HTML, so an agent-driven
  restore *would* be an agent-originated HTML change arriving on a human route. Resolved by
  B3 below.

### B1. The trigger call lives in the route handler, never in the service method

`spec_sync.mark_dirty(session_id)` is called from the **route handlers** in
`src/api/routes/slides.py` and `src/api/routes/tour.py`. The service methods in
`chat_service.py` do **not** call it. The graph calls those service methods directly and so
never fires the trigger.

This makes §4.5's claim true by construction rather than by convention: "arrived via the
route" *means* "a human did this", because the route is the only human entry point and the
graph does not use it. No stored flag, no `origin=` parameter to forget, no ContextVar to
leak. The failure mode requires actively wiring a new route call, not merely forgetting a
parameter.

Rejected: an `origin='human'|'agent'` parameter (a caller that forgets it silently rebuilds
a user's manual edit — the "actively hostile" outcome §4.5 names); a ContextVar (probed to
survive `Send` fan-out, but invisible coupling and a missed reset leaks origin into the next
request); a persisted origin column (§4.5 rejects it, and B0 shows it is not needed).

### B2. Debounce window: 180 seconds

Longer than the plan's 30s. The spec is advisory for existing content and reviewers are the
backstop (§4.3), so a briefly stale spec costs nothing, while a short window means a
WYSIWYG session pays for repeated LLM arc reviews. 180s is the concrete value; it is a
tunable constant, not a contract.

The dirty marker lives in the database, not in-process, so whichever uvicorn worker picks it
up sees it. Driven from the existing job queue rather than a new scheduler.

### B3. A version restore cancels any pending spec review

On restore, discard the dirty marker without running the review. Two reasons: the deck those
pending edits described no longer exists, and `SlideDeckVersion` carries its own
`deck_spec_json` snapshot (`session.py:356`), which PR1 already restores
(`session_manager.py:2221`). The restored spec is authoritative.

This also closes B0's remaining edge: a restore never triggers a spec update, so an
agent-driven restore cannot start hop two.

### B4. New scope: insert slide

Tellr has **no insert-slide capability**. `SlideDeck.insert_slide(slide, position)` exists
(`src/domain/slide_deck.py:251`) and is used at seven internal call sites, but there is no
service method and no route — the mutating routes are only reorder, patch, duplicate,
delete, verification and versions. A user can only obtain a new slide by asking the agent or
duplicating an existing one.

PR3 adds the **backend and spec halves**:

- `chat_service.insert_slide(session_id, position, ...)`, following `duplicate_slide`'s
  shape (clone/insert, `_reindex_slide_ids`, `save_slide_deck`, save point).
- `POST /slides` taking a position.
- A deck-spec slide entry for the new position (position, purpose, `assumes`, `hands off`).
- A §4.4 trigger on the route, per B1.
- Position-shift handling for every position above the insertion point.

**No UI in PR3.** The "add slide here" affordance belongs with the WYSIWYG workstream (ws8),
where slide-stage affordances live. The capability is fully usable via the API and via the
architect ("add a slide after slide 3").

---

## C. Frontend test runner

There is none: `frontend/package.json`'s only test script is `playwright test`, there is no
vitest or jest, no `@testing-library`, and zero `*.test.tsx` files. 31 Playwright E2E specs
exist.

**Add both:** `vitest` + `@testing-library/react` for isolated component tests, and
Playwright specs for flows. PR3's frontend surface (spec-view toggle, drawer wiring,
`slide_ready` handling, finding rendering) has both shapes of test in it — component
rendering is badly served by E2E, and cross-transport slide delivery is badly served by
component tests.

Requires: a `test:unit` script, vitest config, and CI wiring alongside the existing
Playwright job.

---

## D. Feature flag end state: no flag

`agent.py` is deleted and the flag is **removed entirely in the same PR**. The graph is
simply the engine; there is no `LANGGRAPH_ENABLED`, no legacy path, no "off" state to define.

This resolves the plan's sequencing hazard (Phase 11 adding a flag whose `false` default
selects a path Phase 9.2 already deleted) by deleting the question rather than ordering it.

**Consequence, named explicitly: there is no dogfooding period with both engines live.**
The graph must be correct at merge. Two things follow, and the plan must reflect them:

1. The **agentic test layer (§G) carries the weight** a flag would otherwise carry.
2. Validation is a **devloop deploy**, not a flag flip. The `deploy-tellr-dev` skill's
   loop is the pre-merge gate.

Consistent with PRD §10's "many small PRs, big-bang release" and §13's "deliberately not
offered: a toggle back to the old viewer or the old selection model."

---

## E. Customisation in the agentic design

The original question — how to migrate custom `system_prompt` values into in-repo skills —
was the wrong question. Editing those fields is highly unlikely in practice, and PR3 is a
clean rebuild. The right question is how customisation works *forwards*.

### E1. Three axes are the whole user-editable surface; skills stay closed

| Axis | Means | Status |
|---|---|---|
| Deck prompts (`SlideDeckPromptLibrary`) | *what* the deck says | exists, has UI |
| **Design system** (`design_system` + 4 tables), else slide style (`slide_style_library`) | *how* it looks | **design systems landed on main after this decision** — see §L |
| Tone / communication guideline | *how* it reads | **new** — PR3 ships the consumption hook + an in-repo default; authoring UI is a later PR (§10) |

**Corrected after merging main (§L).** The "how it looks" axis is no longer slide styles. A
**design system** — an org-shared brand bundle — supersedes them: the two are mutually
exclusive, enforced in three independent places, and a selected design system *clears* the
style. Template pinning is a further sub-choice inside a design system. The axis count is
unchanged at three; what the middle axis *is* changed.

The seven agent skills are **never user-editable**. If something a custom `system_prompt`
used to do cannot be expressed in one of the three axes, that is evidence a fourth axis is
missing — not evidence that skills should open up.

Rejected: per-skill append-only overrides. A user appending text to a reviewer skill could
soften the bar it enforces, and §5.1 requires review independence to be **structural**, not
nominal. Deferring an extension mechanism to a later workstream was also considered and
rejected as premature — nobody has asked for it.

### E2. Drop the retired columns in this PR

`ConfigPrompts.system_prompt` and `ConfigPrompts.slide_editing_instructions` are
`Column(Text, nullable=False)` (`src/database/models/prompts.py:39-40`) and are live. The
full consumer set, verified:

| Site | Role |
|---|---|
| `src/core/init_default_profile.py:408-412` | seeds both when the default profile is created |
| `src/services/profile_service.py:204-207` | **`ConfigPrompts` insert** — new profile, from `DEFAULT_CONFIG` |
| `src/services/profile_service.py:409-413` | **`ConfigPrompts` insert** — create-with-config path |
| `src/services/profile_service.py:490-494` | **`ConfigPrompts` insert** — clone profile, copies both values |
| `scripts/init_database.py:218-222` | **`ConfigPrompts` insert** — DB init script |
| `src/core/migrate_profiles_to_agent_config.py:15,44,51-52,76` | reads them at startup (`main.py:112`) |
| `src/services/agent_factory.py:155-168` | consumes at runtime; branches on `system_prompt is not None` |
| `src/core/config_loader.py:130` | config key |
| `src/services/agent.py:246,612,619` | dies with the monolith |
| `frontend/src/types/agentConfig.ts:47-48,98-99` | typed and defaulted |
| `frontend/src/contexts/AgentConfigContext.tsx:392-393` | read for a "has custom config" check |
| `PUT /agent-config`, `POST /profiles` | write paths |

All of these change together, and the physical columns are dropped via a `_migrate_*`
helper wired into `_run_migrations()` (this repo has no Alembic — see
`migrations-run-at-startup`).

**Ordering constraint — there are five insert sites, not one.** Every `ConfigPrompts(...)`
constructor that passes these columns must stop doing so *before* the drop migration runs,
or profile creation raises after the drop. The two paths that matter most are easy to miss:
`profile_service.clone_profile` (`:490`) copies both values from the source profile, and
`scripts/init_database.py` (`:218`) is a separate entry point from the app lifespan.

Migrations no longer run in the FastAPI lifespan. Since main's
`fix(startup): run migrations once pre-fork, never in the uvicorn workers`, the chain runs
**once before the server forks**, in
`packages/databricks-tellr-app/databricks_tellr_app/run.py::init_database`, and each step
`raise SystemExit(1)` on failure. The ordering hazard is unchanged in substance — that file
calls `init_db()` (schema + data migrations) **before** `seed_defaults()` — but a migration
that outruns its callers now kills the boot command rather than the lifespan. Sequence the
code change ahead of the migration in the same PR; this is a hard requirement, not a
tidiness preference.

Custom values are inventoried and logged before the drop so anything real is visible rather
than silently discarded.

---

## F. `finding.ts` ↔ reviewer-schema reconciliation (§7.1's named seam)

They currently disagree. `frontend/src/types/finding.ts` declares
`{id, slideIndex, category, message, seen}`; the plan's reviewer schema produces
`{category, severity, description, auto_fixable}`. `message` vs `description` is a rename;
`severity` and `auto_fixable` have no frontend home; `id` and `slideIndex` are never
populated. The drawer's callbacks are wired to `console.info` against a `testFindings`
fixture (`AppLayout.tsx:747, 965-967`), so nothing real consumes it yet.

### F1. The backend reviewer schema is canonical

The reviewer's Pydantic schema is the source of truth and is mirrored into `finding.ts`.
Backend owns it because the schema is versioned *with* the review skill (§5.1) and because
PRD §7.1 wants verdicts queryable as MLflow assessments — which needs the criteria list and
its schema versioned as one identifiable artifact. `finding.ts` is currently fixture-wired,
so changing it costs nothing.

A conformance test asserts a real reviewer payload deserialises into `SlideFinding` with no
loss. The reviewer emits a stable per-finding `id` (so drawer callbacks have something to
key on) and `slide_index`.

### F2. Auto-fixed findings surface, marked as already fixed

The drawer shows subjective findings as **actionable**, plus objective auto-fixed findings
as a **read-only "we fixed this"** list.

This reconciles two requirements that otherwise conflict: §7.4 says objective defects are
fixed before the user sees the slide, and PRD §3 requires that "what was fixed is visible."
Read-only presentation satisfies the second without asking the user to act on resolved
items, and keeps the actionable surface small enough to respect PRD §14's review-fatigue
risk.

### F3. Findings live in `verification_record`

PRD §12.1 left open whether drawer findings and reviewer verdicts share one record. They
share it. `session_slides.verification_record` is hash-keyed, **merged never overwritten**,
travels with its slide on reorder, and is re-materialised by `restore_version` — all built
and tested in PR1. A parallel store would re-solve reorder-safety, edit-then-revert recall
and save-point restore, each of which PR1 already got right once (and one of which shipped
as a defect during 0a before being caught).

Note the non-obvious property to preserve: **a record belongs to a slide, not a position.**

---

## G. Testing non-determinism — restructured

§9's three layers are replaced by **four, organised by what each layer needs in order to
run.** The spec conflated "excluded from CI" with "rarely run", but the real constraint is
environmental: CI has no LLM (`test.yml` uses `DATABRICKS_HOST: https://test.cloud.databricks.com`
and `DATABRICKS_TOKEN: test-token`, with `-m "not live"` throughout), while a local machine
*can* reach Databricks. The repo is currently personal; a move to a company org will change
this.

| Layer | Needs | In CI | Catches |
|---|---|---|---|
| 1. Orchestration | nothing (stub agents, real compiled graph) | ✅ | ascending dispatch, cap at 15, ordered release, exactly-one-fix-round, placeholder-counts-as-committed, barrier acknowledged |
| 2. Schema / contract | nothing (canned payloads) | ✅ | a prompt edit that breaks its own output schema; every node's return keys are a subset of `GraphState` |
| 3. **Agentic behaviour** | real LLM via local Databricks | ❌ today | whether the agents actually behave |
| 4. Concurrency / multi-worker | DB, no LLM | ✅ | parallel row writes, cross-worker buffer release |

### G1. Layer 3 lives in `tests/agentic/` with its own target

A dedicated directory plus a `make test-agentic` (or equivalent script) that runs the suite
against a real Databricks connection, retaining the `live` marker (already declared at
`pyproject.toml:104`). Discoverable and one command, rather than a marker nobody remembers.

**Built CI-ready now, enabled later.** When the repo moves to a company org, turning this on
must be a workflow change and nothing else — no test rewrites. Recorded as an explicit
follow-up so it is not rediscovered.

### G2. Layer 3 asserts structure *and* behavioural outcomes — never wording

§9's "structure, never wording" is necessary but insufficient: it can confirm a reviewer
returns valid JSON, not that it reviews well. So layer 3 also asserts checkable behaviour:

- the architect **asks** rather than picking a slide when a reference is ambiguous (RC10);
- a deliberately-broken slide **is** flagged by the build reviewer;
- the fixer's diff is **small** relative to the finding (not a re-author);
- the fix reviewer **keeps the original** when handed a worse "fix";
- the analyst returns exactly one of its three outcome shapes, and passes a single source
  through without re-summarising.

Phrasing is never asserted.

### G3. CI keeps a cheap schema smoke test

Every skill gets a CI-runnable test that its output schema is well-formed and that a canned
valid payload parses. This closes the gap where a prompt edit breaks a schema and ships
green — the "test that cannot fail" class that cost the most last session — without needing
a live model.

---

## H. Deck-level state has no writer (defect)

**Found by reading the spec against the code.** `knit()` (`src/domain/slide_deck.py:323`)
emits `<style>{self.css}</style>` from `SessionSlideDeck.css`. `SlideWriter` is per-row only
and never touches `css`, `title` or `deck_json` — verified. The parent spec calls the foreman
"the sole writer of deck-level CSS" (§5.2.8, §5.5), but the foreman is a set of pure
functions over graph state with **no database access at all**.

As drawn, **every graph-built deck would knit with an empty `<style>` block** — an unstyled
deck. Review finding F9, unresolved until now.

### H1. One deck-level write per turn, before the fan-out

When the architect commits the deck spec — before builders dispatch — the graph performs a
single deck-level write persisting CSS and title, via the existing
`session_manager.save_slide_deck` path.

Once per turn, so exactly one `version` bump and no contention. Before the fan-out, so the
CSS contract is persisted while builders run and an incrementally-released slide renders
styled. The design contract already lives in the spec, so this is persisting what the
architect decided — design is *decided* by the architect and *enforced* by the foreman, as
§5.2.8 says.

Note `save_slide_deck` bumps `version` and enforces the optimistic lock
(`session_manager.py:1294-1299`), which is precisely why it cannot be called per slide and
why `SlideWriter` deliberately does not use it.

Rejected: writing after all slides land (leaves incrementally-released slides unstyled
mid-turn); adding a deck-level method to `SlideWriter` (invites per-slide calls that would
409 each other — the contention row-per-slide exists to remove).

### H2. `deck_json` is deliberately left stale — no write-through

PRD §10.2 states that because `SlideWriter` does not update `deck_json`, the pre-cutover
rollback guarantee for slide content holds only while it has no production callers, and
workstream 4 must "either write through to `deck_json` or accept and document the loss."

**Neither branch of that obligation applies, because the scenario cannot occur.** The
release is forward-only and big-bang; nobody will redeploy a pre-PR1 build against a
Lakebase holding graph-written rows. Building write-through — and a parity test to guard it
— would be insurance against an impossible event. It is not built.

Two things verified so this is a decision and not an assumption:

- **The dual-read path is unaffected.** `get_slide_deck` reconstructs the deck from
  `session_slides` rows whenever *any* row exists, and only falls back to the blob
  otherwise (`session_manager.py:1446-1484`; the code comment reads "Any rows at all means
  the dual-write has run; use rows as truth"). A stale blob is **unreachable**, not wrong.
- **Save points are unaffected.** `create_version` snapshots the deck dict the row path
  produced, so it captures current state.

The only consequence is dead bytes in a column. **Recorded here explicitly because a future
reader will otherwise see a stale `deck_json` on a graph-written deck and "fix" a bug that
does not exist.**

---

## I. No-flapping vs. the stalled-buffer release (defect)

**Found by reading the spec against itself.** §7.4 guarantees that a slide "appears in the
viewer only once it is review-clean — it never appears and then silently changes under the
user (no flapping)." §8 specifies that if position *n* has not committed within a bound
after *n+1* is ready, later slides are released and *n* "slots in late or becomes a
placeholder."

A slide arriving at position 3 after 4–8 are already on screen **is** a visible reshuffle.
Both rules are individually sensible; they cannot both hold.

### Resolution: strict ascending release; a stalled position becomes a placeholder

Release stays strictly ascending and nothing ever slots in late. On timeout, the stalled
position commits as a **visibly-marked placeholder** the user can retry individually.

§7.4 wins on the guarantee; §8's actual intent — the buffer must never stall — is fully
preserved, because a placeholder already counts as committed for both the release query and
the all-positions-committed deck-review trigger (§5.5). The deck always completes, is always
honest about what failed, and never reshuffles under the reader.

PR1 already implements the placeholder: `SlideWriter.commit_placeholder` writes
`{content_hash: {"error": True, "message": ...}}` with a `slide-placeholder-error` class,
detected via `is_placeholder_record`. **Detect a failed position via that helper, never via
an HTML class.**

This also simplifies the foreman: no late-arrival path and no re-release logic.

**Implementation note, not a design question.** §8 justifies its wall-clock-in-the-foreman
design by arguing the barrier prevents a timeout from firing while a position is actually
stalled. `Send`'s new `timeout` kwarg (1.2.10) may express this directly at the runtime
level. To be probed during planning and used only if genuinely cleaner than the
state-recorded `dispatched_at` timestamp check; the design does not depend on it.

### §5.2.4's "implementation detail" is already decided

§5.2.4 leaves "the exact row representation of the placeholder (flag, sentinel, or other
marker)" open. It is not open — PR1 shipped it, in the hash-keyed form above. Recorded so
nobody redesigns it.

---

## J. Corrections to the parent documents

Recorded so the divergences are deliberate rather than drift.

| Document | Says | Correction |
|---|---|---|
| spec §5.2.8 / §5.5 | the foreman is "sole writer of deck-level CSS" | the foreman has no DB access; a once-per-turn graph write persists CSS + title (§H1) |
| spec §7.4 vs §8 | no flapping / stalled position slots in late | mutually exclusive; strict order wins, stall → placeholder (§I) |
| spec §5.2.4 | placeholder representation is an implementation detail | already shipped by PR1, hash-keyed (§I) |
| spec §9 | three test layers; live tests excluded from CI | four layers organised by runtime need; `tests/agentic/` is a first-class local suite (§G) |
| spec §4.5 | origin known from the code path | true for the HTML triggers; the trigger call must live in the route to keep it true (§B1) |
| PRD §10.2 | must write through to `deck_json` or document the loss | the rollback scenario cannot occur; no write-through (§H2) |
| plan (F4) | set `recursion_limit` explicitly; default is 25 | default is **10007** on 1.2.10; the plan's ~50 would lower it (§0) |
| kickoff brief | `SessionManager.get_deck_spec` / `write_deck_spec` are the only persistence path | **those methods do not exist.** They appear only in the PR1 *plan*. What landed is the `deck_spec_json` column on both tables, the migration, save-point snapshot/restore, and a per-slide `deck_spec_slide` parameter on `write_slide`. PR3 owns the deck-level accessor. |
| kickoff brief | 19 pre-existing failures in four files | 17 in three files, post-upgrade (§0) |
| spec §4.1 | design contract = "the CSS/style contract" | a design system compiles to a **prompt artifact**, not a stylesheet; the spec stores a reference (§L1, §L3) |
| spec §5.2.3 | builders receive "the style sheet (the CSS contract)" | they receive the resolved `compiled_style_content` **or** `style_content` — a branch, not a ladder — already carrying the frame rules (§L1, §L5) |
| spec §5.2.8 | the foreman is sole CSS writer | a second, **measured** deck-CSS write is now required post-commit (`ensure_deck_token_css`), or pinned-template decks ship washed out (§L2) |
| spec §4.6 | design-contract change = `slide_style_id` | three fields plus template pinning; setting a design system clears the style (§L4) |
| plan Phase 9.2 | delete or reduce `agent_factory` | it now owns design-system resolution, template blocks and `search_brand_assets` gating — move, do not delete (§L6) |
| this doc §E2 (pre-merge) | migrations run in the lifespan and re-raise | they run **once pre-fork** in `run.py::init_database` and `SystemExit(1)` (§L8) |
| `migrations-run-at-startup` memory | backfills go in the FastAPI lifespan | superseded — they go in `run.py::init_database` (§L8) |

---

---

## L. Design System Library — merged from main, 2026-08-18

Main landed a **Design System Library** after the decisions above were taken, and merged it
into `feat/langgraph-core` on 2026-08-18. It is the single largest change to PR3's
integration surface since the parent spec was written, because it **replaces the CSS
contract with a prompt artifact** and adds a deck-CSS write the graph path would bypass.

What it is: org-shared brand bundles (colour/type tokens, webfonts, brand imagery, named
slide templates) uploaded as a zip, compiled once into `compiled_style_content`, and
resolved onto a deck through six per-entry-path decision trees. Five tables, 15 routes,
admin-governed org default, per-user personal defaults. Reference:
`docs/technical/design-system-library.md`, `-bundle-format.md`, `-library-spec.md`.

### L1. The CSS contract is now a prompt artifact, resolved as a branch

`agent_factory` resolves the visual style as a **branch, not a ladder**:

```python
if config.design_system_id is not None:   # design-system branch
    ...
elif config.slide_style_id is not None:    # legacy slide-style branch
```

Consequences PR3 must respect:

- **The two are mutually exclusive**, enforced in three independent places — the model
  serializer, the column bind (`NormalizedAgentConfig`, now the type of
  `UserSession.agent_config`), and a database `BEFORE INSERT OR UPDATE` trigger. A caller
  cannot construct a deck carrying both.
- **An inactive `design_system_id` does not fall through to the style.** The branch is
  chosen on the id being *present*, so a soft-deleted design system logs a warning and
  leaves generation on the `DEFAULT_SLIDE_STYLE` constant. The `elif` is never evaluated.
- **`compiled_style_content` has a currency contract.** It is stamped with
  `COMPILER_VERSION` and currency is an **exact match, not a comparison**; a stale row is
  lazily recompiled on read via `ensure_compiled_style_content_current`. Any change to
  compiler output must bump the version or it never reaches existing rows.

### L2. §H1 revised — two deck-level writes per turn, and a second measured defect

§H found that nobody writes deck-level CSS on the graph path. The design system adds a
**second, independent instance of the same class**, and this one is measured rather than
inferred.

`chat_service._ensure_pinned_template_token_css` runs `ensure_deck_token_css` **right before
every deck save** (`chat_service.py:670`, `:1469`). Its docstring records why prompt prose
was insufficient: a pinned deck "referenced 57 `var(--…)` tokens while defining none,
washing out preview and both PPTX export paths. Prompt prose is not a guarantee; this is."

**Both call sites are in the flows PR3 deletes.** PR3's reviewers write *rows* via
`SlideWriter`, which is not a deck save, so on the graph path the backstop never fires and a
pinned-template deck ships washed out in preview and both exports.

**Resolution — two deck-level writes per turn:**

| When | Writes | Why there |
|---|---|---|
| Before the fan-out | CSS contract + title | so incrementally-released slides render styled (§6.2's payoff) |
| After all positions commit, before the deck-review trigger | `ensure_deck_token_css(deck.css, token_css)` | the backstop **compares emitted deck CSS** against the token stylesheet, so it cannot run before builders have emitted any |

Two `version` bumps per turn, both deck-level, neither per-slide — so the no-contention
property holds. `ensure_deck_token_css` is idempotent and prepends (deck CSS stays later in
the cascade, so anything the model authored still wins), and it never raises: a failed
guarantee must not block the save.

This revives the two-write sequencing dropped when §H2 was cancelled, for a different and
now-measured reason.

### L3. The deck spec's `design_contract` holds a reference, not content

§4.1 lists "design contract: the CSS/style contract" as a deck-level spec field. It stores
**which brand**, not the compiled text:

```
design_contract: { design_system_id, template_id, slide_style_id }
```

The compiled content is resolved at build time through `agent_factory`'s logic. Storing a
copy is wrong by construction: `compiled_style_content` currency is an exact version match,
so a snapshot in the spec is stale the moment `COMPILER_VERSION` moves, and the spec would
silently drive builds from a superseded artifact.

### L4. §4.6's design-contract trigger widens

The parent spec names `slide_style_id` as the design-contract field behind
confirm-then-rebuild-all. It is now three fields, and **pinning or unpinning a template is
also a design-contract change** because pinning is what supplies the template's own CSS
(unpinned decks get only a name/description catalog with no CSS). Setting
`design_system_id` additionally *clears* `slide_style_id`, so one user action mutates two
fields.

### L5. Reusable, already-measured prompt material for §A

Three blocks exist that the builder skill should consume rather than reinvent:

- **`_SLIDE_FRAME_CONSTRAINTS`** (`design_system_compiler.py:545`) — fixed 1280×720 frame,
  clip-not-scroll, left/right clearance **MUST** be ≥88px, vertical **TARGET** 72px and
  never below 56px, root carries no outer margin, decorative imagery never overlaps text.
  The source comments record the measurement that set each wording: across 6 unpinned runs /
  18 slides the horizontal 88px held on 313/314 ink boxes, while `padding-top` hit the
  brand's 72px on only 3 of 18 — so the horizontal became a MUST and the vertical an
  imperative floor. **Do not re-derive or reword these numbers.**
- **`DESIGN_SYSTEM_PRECEDENCE`** (`prompt_modules.py:191`) — asserts the design system is
  authoritative over generic styling guidance. Include only when a design system is active.
- **The `{{ds-asset:ID}}` contract** — a distinct namespace from `{{image:ID}}` (independent
  id sequences, so reusing `{{image:ID}}` resolves to an unrelated image). Brand images are
  **not** enumerated in the prompt; the model fetches them via `search_brand_assets`.

**The frame rules arrive with the style content on both paths** — the compiler emits them
for a design-system deck (which bypasses `DEFAULT_SLIDE_STYLE`), and `DEFAULT_SLIDE_STYLE`
carries its own for the legacy path. So the builder skill **must not hardcode them**, or a
design-system deck gets two conflicting copies.

### L6. What PR3 must preserve rather than delete

The plan's Phase 9.2 says `agent_factory` should be deleted or "reduced to graph config
assembly". That is no longer safe — it is now the only home for:

- the design-system resolution branch and `compiled_style_content` currency check;
- pinned-template block assembly (`build_selected_template_block`,
  `get_template_for_generation`);
- **`search_brand_assets` tool gating** — the tool is added *only* when
  `config.design_system_id is not None`. This is a live input to the architect's tool
  manifest (§5.2.1) and the analyst's tool grants.

`chat_service` likewise gained design-system responsibilities that must survive its
rewrite: `resolve_active_design_system_id`, `{{ds-asset:ID}}` substitution inside
`_substitute_images_for_response(..., session_id=)` (note the new keyword-only argument),
`_resolve_pinned_template_token_css` and `_ensure_pinned_template_token_css`.

### L7. The slide-root contract changed

`SlideDeck.from_html` no longer looks for `div.slide`. It calls
`find_slide_roots(soup)` (`src/utils/html_utils.py:46`): the outermost element carrying the
`slide` class token, **whatever its tag**, promoted outward through any semantic sectioning
wrapper whose sole element child is the slide root. A `<div>` is never promoted.

The reason is design-system templates: a pinned template makes the model emit the template's
own `<section>` wrapper around the `div.slide` body, and every `<style>` block is copied
verbatim into deck CSS — so dropping the wrapper keeps rules like
`section { background; color; font-family }` while deleting the only element they could
match.

Affects PR3 in three places: what the builder is told to emit, how canvas dedup locates
slides, and any reviewer check that assumes a slide root is a `div`.

**And it sharpens the build reviewer's overflow criterion (§A2).** Every preview surface now
clips at the true 1280×720 frame, so overflow is visible to the user while editing rather
than absorbed by a growing tile (§L8). That makes "content overflows its frame" a defect the
reviewer must catch *before* the slide is shown — it is on the objective-heavy initial
criteria list for exactly this reason, and the frame numbers it judges against come from
`_SLIDE_FRAME_CONSTRAINTS` (§L5), not from the reviewer's own invention.

### L8. Merge integration — the `main.py` trap

Main's `fix(startup): run migrations once pre-fork, never in the uvicorn workers` deleted the
lifespan block that PR1 had extended, because "4 workers racing the migration chain on boot
wedged startup." Five files conflicted; two were traps.

- **`src/api/main.py`** — resolved to main's side (no migration code in the lifespan), and
  PR1's `backfill_unmigrated_decks` **relocated into `run.py::init_database`** alongside
  `migrate_profiles` / `backfill_sessions`. Keeping our side would have put four workers
  back into the race main just fixed; taking main's side alone would have dropped the
  backfill entirely, so migrated decks would never acquire rows.
  **This supersedes the `migrations-run-at-startup` convention: new migrations and backfills
  go in `run.py::init_database`, pre-fork, not the lifespan.**
- **`src/core/database.py`** — both sides appended to the same migration list; kept both.
  `_migrate_row_per_slide_schema` must stay **after**
  `_migrate_rewrite_deck_image_placeholders`, and a comment now pins why:
  that rewrite targets `_DECK_PLACEHOLDER_COLUMNS` only (`session_slide_decks.deck_json`,
  `.html_content`, `slide_deck_versions.deck_json`) and **not** `session_slides.html`, which
  did not exist when it was written. Row data is backfilled later still, so rows are always
  built from `deck_json` that has already been rewritten to `{{image:<token>}}` form.
  Reordering these would backfill rows from int-id placeholders that nothing subsequently
  rewrites, silently breaking images on every migrated deck.
- **`SlidePanel.tsx`** resolved to our side (ws6 extracted export/verification into hooks),
  but main's *behaviour* was ported into those hooks rather than discarded: the louder
  partial-PPTX-export toast (persistent, naming the failed slide numbers and first error),
  the previously-absent auto-verification failure notice, and the inline "Save as HTML"
  document builder replaced by main's extracted `buildStandaloneDeckDocument`. That last one
  matters because three suites pin that helper (`slide-surface-fidelity.spec.ts`,
  `slide-host-frame.spec.ts`, `tests/unit/test_preview_box_model_parity.py`); leaving a
  duplicate inline would have left those specs guarding a function the real export never
  calls.
- **`SlideSelection.tsx`** stays deleted (checkbox selection is retired per PRD §3). Two
  tests referenced it as an exemplar and were repointed at surviving surfaces:
  `test_preview_box_model_parity.py` now pins **three** preview surfaces, and
  `test_export_csp.py`'s non-vacuity guard uses `PresentationMode.tsx`.
- **`SlideTile.tsx` — resolved to MAIN's side, reversing an initial mistake worth recording.**
  Taking `--ours` here resurrected code main had deliberately deleted, and the failing
  `test_the_preview_reset_has_exactly_two_consumers` was correctly reporting it.
  The history: SlideTile's postMessage height-reporter and grow-to-fit behaviour came from
  `d75eda88` (2026-02-18, "v0 polish" — "card height adapts to slide content … to avoid
  inner scrollbar"), and `48fe0fa1` (2026-07-06, design-system frame guardrails Phase 3)
  **removed it on purpose**: *"SlideTile now clips at the true 1280x720 frame like the
  presentation viewer / export … instead of growing to fit tall content, so overflow is
  visible while editing. Removes the now-unused height reporter + grow machinery."* That
  commit is on main and **not** on this branch, so our side merely predated the removal —
  it was never a ws6 feature and never a design disagreement.
  A growing tile actively hides the defect: `48fe0fa1` names the production symptom it fixed
  as the *"cut off" / "massive long slide"* problem, where a design-system deck bypassed
  `DEFAULT_SLIDE_STYLE` (the only place the frame limits lived) and export clipped the
  overflow. Resolution: main's `SlideTile`, with this branch's only genuine change to that
  file re-applied — removal of the selection affordance (`useSelection`, `isSelected`, the
  `ring-2 ring-blue-500` class, the `MessageSquare` "Add to chat context" button).
  **Lesson for the remaining merge work: when a conflict looks like "our refactor vs their
  change", check `git log -S` on the specific behaviour before choosing a side.** The shape
  of a conflict does not tell you which side is intentional.

### L9. Unaffected, verified

- **`{{image:ID}}` prompt contract is unchanged.** SDR-4437 made the id an opaque token
  rather than an enumerable int; the placeholder syntax the builder emits is the same.
- **No conflict on `deck_spec_json`.** Main does not touch `SessionSlideDeck`.
- **§I's placeholder mechanism is unaffected** — `commit_placeholder` and
  `is_placeholder_record` are PR1 code that main never saw.

## K. What this document does not decide

- The **content** of the seven prompts. A1 fixes the process; the prompts are written in the
  next session.
- The **specific initial reviewer criteria list**. A2 fixes the posture (minimal,
  objective-heavy); the list is drafted with `build_reviewer`.
- Anything the parent spec §10 excludes: WYSIWYG (ws8), gateway abstraction (ws2), the
  MLflow rebuild (ws3), per-agent model routing, the tone authoring UI, speaker notes.
- The ~34 bare steps and unapplied review findings in the plan. Those are plan-repair work,
  scheduled next via `writing-plans`, informed by these decisions.
- **How the architect converses about brand.** §L makes the design system a first-class deck
  property with an org default, personal defaults and template pinning. Whether the architect
  can *change* it conversationally ("use the Acme brand", "pin the section-divider
  template"), or whether it is read-only context the user sets in Agent Config, is not
  decided here. §L4 covers what happens *when* it changes, not who may change it.
- **Whether design-system templates inform the deck spec's slide briefs.** A pinned template
  supplies layout; a `SlideSpec` supplies purpose and content. Whether the architect should
  select a template *per slide* from the catalog is a genuine design question §L does not
  answer.
