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
| Slide styles (`slide_style_library` + `image_guidelines`) | *how* it looks | exists, has UI |
| Tone / communication guideline | *how* it reads | **new** — PR3 ships the consumption hook + an in-repo default; authoring UI is a later PR (§10) |

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

Because migrations run inside the FastAPI lifespan and **re-raise** on failure
(`main.py:105-125`), a migration that outruns its callers aborts startup entirely. Sequence
the code change ahead of the migration in the same PR; this is a hard requirement, not a
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

---

## K. What this document does not decide

- The **content** of the seven prompts. A1 fixes the process; the prompts are written in the
  next session.
- The **specific initial reviewer criteria list**. A2 fixes the posture (minimal,
  objective-heavy); the list is drafted with `build_reviewer`.
- Anything the parent spec §10 excludes: WYSIWYG (ws8), gateway abstraction (ws2), the
  MLflow rebuild (ws3), per-agent model routing, the tone authoring UI, speaker notes.
- The ~34 bare steps and unapplied review findings in the plan. Those are plan-repair work,
  scheduled next via `writing-plans`, informed by these decisions.
