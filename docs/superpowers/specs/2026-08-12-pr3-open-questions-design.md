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

Nine questions were resolved first (A–I); §L and §M were added later, so the document now
runs **A–M**. Two of the original nine (H, I) were unresolved *defects* found while reading
the spec against the code, not gaps the spec knew it had.

**§L and §M were added on 2026-08-18** after main's Design System Library was merged into
this branch. §L revises §E1 and §H1 and corrects §E2's mechanism — read it alongside them,
not as an appendix. §M then settles how the agentic core consumes brands and templates, and
adds two fields to the deck spec.

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

| | Pre-upgrade | Post-upgrade | After the local env was installed to spec |
|---|---|---|---|
| Result | 20 failed / 2003 passed / 8 skipped | 17 failed / 2006 passed / 8 skipped | **3 failed / 4177 passed / 8 skipped** (4188 collected, `pytest tests/ -n auto`, 2026-08-19) |

**The baseline for PR3 is 3 failures across 2 causes:**

| Cause | Files | Count |
|---|---|---|
| deploy-autoscaling assertion mismatch (`assert 'provisioned' == 'autoscaling'`) | `tests/unit/test_deploy_autoscaling.py` | 2 |
| `GenieToolError: Failed to query Genie space after 3 attempts` (live Databricks) | `tests/integration/test_genie_integration.py` | 1 |

**Corrected 2026-08-19 — the 14 `svgpathtools` failures were never a repo baseline.** They
were a **local environment not installed to spec**: `svgpathtools>=1.6.0` is a declared
*root runtime dependency* (`pyproject.toml:52`, and the app wheel declares it too at
`packages/databricks-tellr-app/pyproject.toml:53`), and every CI job installs it via
`pip install -e ".[dev]"`. It was simply absent from the pyenv the probe used. With it
installed, `tests/unit/test_html_to_pptx.py` and `tests/unit/test_google_slides_converter.py`
pass (71 passed, measured). Treating them as a baseline would have parked the two suites
covering the **PPTX and Google-Slides emitters** permanently red — the exact export surface
§L2 says a pinned-template deck washes out — and `tests/unit/test_app_wheel_dependencies.py`
documents this same package as a measured HIGH defect class. **Fix the environment before
recording a baseline.**

The upgrade also **resolved** a third pre-existing cause (3 mlflow `trace_location` failures,
caused by mlflow 3.6.0 running tests written for 3.14.0). No new cause appeared.

Two corrections to the brief carried into this session: it described 19 failures in four
files, and named Cairo as the SVG family's cause. Neither was right.

Note the earlier rows' "2003/2006 passed" reflect a narrower selection than `pytest tests/`
(4188 collected), which is precisely why this section's rule is **by cause, never by count**.

**Any 4th failure, or any change to one of those two causes, is a regression PR3 caused.**

---

## A. The seven skill prompts

Zero of the seven exist; the substance of plan Phases 2–3 is `[To be filled in Phase 2]`.
This is the single largest gap and it is **content, not code**.

**Reusable material:** `src/core/prompt_modules.py` holds **11,189 chars across 12 named
blocks** (measured 2026-08-19). `CHART_JS_RULES` (1470 chars), `EDITING_RULES` (3731),
`SLIDE_GUIDELINES` (708), `IMAGE_SUPPORT` (908) and `HTML_OUTPUT_FORMAT` (982) are directly
reusable by the builder and fixer. Two more are load-bearing rather than optional:
`DESIGN_SYSTEM_PRECEDENCE` (472) — the 12th block, added by main's design-system work and
the one §L5 depends on — and **`UNTRUSTED_DATA_NOTICE` (516)**, which every skill that
receives tool output or prior slide HTML needs (see §D on the two safety controls that die
with `agent.py`). The architect and all four reviewers are net-new writing.

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
code a human uses (`src/api/services/chat_service.py` — note the path: it is **not** under
`src/services/` — `reorder_slides` at `:2686`, `update_slide` `:2771`, `duplicate_slide`
`:2850`, `delete_slide` `:2921`; all §A–§I line numbers were re-verified against the
post-merge tree on 2026-08-19).

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
up sees it.

**Mechanism — corrected 2026-08-19. It cannot ride `enqueue_job`.**
`src/api/services/job_queue.py` is an in-process `asyncio.Queue` (`:21`) plus an in-memory
`jobs` dict (`:20`), drained FIFO by a per-worker `worker()` loop (`:214-239`). It has **no
delay/at-time primitive**, so a 180 s coalescing window has nothing to hang off. What is
reusable is the **sweeper pattern**, not the queue: `mark_timed_out_jobs_loop` (`:342-352`)
with `TIMEOUT_SWEEP_INTERVAL_SECONDS = 60` (`:33`) — a periodic loop that reads DB state and
acts on whatever is due. So: a periodic sweeper reads the dirty marker and runs the arc
review once the marker is older than the window.

**A claim step is required.** `run.py:128` defaults to `UVICORN_WORKERS=4`, and the sweeper
runs in every worker, so four loops would race one DB dirty marker with no lease — the same
multi-worker race class main just fixed for migrations (§L8). The sweeper must claim the
marker atomically (conditional `UPDATE … WHERE claimed_at IS NULL RETURNING`, or equivalent)
before running the review, or a WYSIWYG session pays for up to four identical LLM arc
reviews per window — the exact cost the debounce exists to avoid.

### B3. A version restore cancels any pending spec review

On restore, discard the dirty marker without running the review. Two reasons: the deck those
pending edits described no longer exists, and `SlideDeckVersion` carries its own
`deck_spec_json` snapshot (`src/database/models/session.py:358`), which PR1 already restores
(`session_manager.py:2222,2240`). The restored spec is authoritative.

This also closes B0's remaining edge: a restore never triggers a spec update, so an
agent-driven restore cannot start hop two.

### B4. New scope: insert slide

Tellr has **no insert-slide capability**. `SlideDeck.insert_slide(slide, position)` exists
(`src/domain/slide_deck.py:251`) and is used at **six** internal call sites (all in
`src/api/services/chat_service.py`), but there is no
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
vitest or jest, no `@testing-library`, and zero `*.test.tsx` files. **32** Playwright specs
live under `frontend/tests/e2e/` (49 `*.spec.ts` tracked in the repo overall, counting
`frontend/tests/` and `frontend/tests/user-guide/`) — measured 2026-08-19.

**Add both:** `vitest` + `@testing-library/react` for isolated component tests, and
Playwright specs for flows. PR3's frontend surface (spec-view toggle, drawer wiring,
`slide_ready` handling, finding rendering) has both shapes of test in it — component
rendering is badly served by E2E, and cross-transport slide delivery is badly served by
component tests.

Requires a `test:unit` script and a vitest config — and **more CI work than "wiring
alongside the existing Playwright job" implies.** The `e2e-tests` job is an **explicit
matrix allowlist of 23 spec names** (`.github/workflows/test.yml:479-501`) against **32**
specs on disk, so a spec runs in CI only after a matrix edit. **PR3's frontend surface has
zero CI coverage today:** `slide-viewer` — the only spec exercising the feedback drawer and
findings (`frontend/tests/e2e/slide-viewer.spec.ts:302-360`) — is absent from the matrix,
as are `slide-host-frame` and `template-viewer`; `frontend/tests/viewer-readonly.spec.ts`
sits outside `tests/e2e/` entirely and so is unreachable by that job's naming scheme.
Adding the existing specs to the matrix is PR3 work, not a follow-up: without it, every new
Playwright spec PR3 writes ships uncollected.

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

### D1. Deleting `agent.py` deletes two shipped security controls — re-home both

**Added 2026-08-19.** `src/services/agent.py` is not only the monolith; it is the only home
of two controls that landed as security work and have no equivalent on the graph path
(verified: no other module implements either):

| Control | Where | Pinned by |
|---|---|---|
| **Output safety gate** — `_run_output_safety_gate` + `SAFETY_RETRY_NOTICE` (`agent.py:96-118`, call sites `:1488`, `:1746`): scans model HTML for disallowed external network/resource access, regenerates once with a corrective instruction, raises if still unsafe (AISEC-248 PR1) | generation *and* streaming paths | `tests/unit/test_agent_safety_gate.py`, `tests/unit/test_safety_gate_http.py` |
| **Slide-context spotlight** — `spotlight("slide_context", html, session_id=…)` (`agent.py:894-916`): prior slide HTML is untrusted input, so it is framed as `<untrusted-data>`, delimiters neutralised, injection patterns scanned/logged at the prompt boundary (SDR-4437 F-TM-12) | edit/add operations that inject prior slides | `tests/unit/test_slide_context_injection.py` |

Neither is optional and neither is a monolith artifact: the graph's builder and fixer emit
HTML from a model, and its fixer/reviewers receive prior slide HTML as input, so both
threats survive the rewrite unchanged. `src/api/routes/export.py:159` runs the same scanner
at *export* time and `src/services/streaming_callback.py:90` suppresses unsafe streamed
text, but neither replaces the generate-time gate-and-retry.

**PR3 must therefore:**

1. Move the gate to the graph's HTML-emitting boundary (builder and fixer output), keeping
   the retry-once-then-fail shape and the generic user-facing notice.
2. Route every prior-slide-HTML injection through `spotlight` on the graph path, and use
   `UNTRUSTED_DATA_NOTICE` (§A) in the skills that receive it.
3. Repoint both test files (and the other 11 test files importing `src.services.agent` —
   13 in total) at the new homes rather than deleting them.

**Why this is called out here:** under §0's baseline rule a deleted test is invisible — the
failure count does not rise when a suite stops existing. These two are security controls, so
their tests must be re-pointed and seen to pass, not merely absent from the failure list.

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

**The tone axis needs a precedence rule against the BRAND MANUAL — added 2026-08-19.**
A design system's compiled artifact injects the full README + SKILL.md under the heading
*"BRAND MANUAL (the authoritative brand documentation for this design system — follow it)"*
(`design_system_compiler.py:489-492`), and the module header records that "The README
already documents the brand's assets/**voice**/rules" (`:22-23`). So a brand can already
speak to how a deck reads, unqualified and declared authoritative. `DESIGN_SYSTEM_PRECEDENCE`
does **not** settle the collision: it is scoped to *visual* styling — "AUTHORITATIVE for ALL
visual styling of this deck — colors, typography, layout, spacing, shadows, and imagery"
(`prompt_modules.py:191-200`) — and says nothing about voice. Tone is therefore undefined
between the two artifacts today, and the third axis must ship with an explicit rule (a
brand's documented voice outranks the generic tone default, or the reverse) plus the prompt
wording that states it. Without one, a branded deck's tone is decided by injection order.

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
| `src/core/migrate_profiles_to_agent_config.py:15,44,51-52,76` | reads them at startup — **pre-fork, in `run.py::init_database` (`packages/databricks-tellr-app/databricks_tellr_app/run.py:66`), not `main.py`'s lifespan** (see the closing paragraph below; the only `main.py:112` caller left is the stale `packages/databricks-tellr-app/build/lib/` copy) |
| `src/services/agent_factory.py:250-263` (also logged at `:504-505`) | consumes at runtime; branches on `system_prompt is not None` |
| `src/core/config_loader.py:130` | config key |
| `src/services/agent.py:250-252,617,624-625` | dies with the monolith |
| `frontend/src/types/agentConfig.ts:82-83,135-136` | typed and defaulted |
| `frontend/src/contexts/AgentConfigContext.tsx:124-125,1137-1138` | read for a "has custom config" check (**two** call sites, not one) |
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
fixture (`frontend/src/components/Layout/AppLayout.tsx:762, 988-990`), so nothing real
consumes it yet.

### F1. The backend reviewer schema is canonical

The reviewer's Pydantic schema is the source of truth and is mirrored into `finding.ts`.
Backend owns it because the schema is versioned *with* the review skill (§5.1) and because
PRD §7.1 wants verdicts queryable as MLflow assessments — which needs the criteria list and
its schema versioned as one identifiable artifact. `finding.ts` is currently fixture-wired, so changing it is
**cheap but not free** (corrected 2026-08-19): besides `FeedbackDrawer.tsx` and
`SlideViewer.tsx`, the type also governs `frontend/tests/fixtures/findings.ts` — where
`id`/`slideIndex` *are* populated — and about ten assertions in
`frontend/tests/e2e/slide-viewer.spec.ts:302-360` keyed on the ids `f1`/`f2`
(`finding-f1`, `finding-dismiss-f1`, `finding-apply-f2`, …). Renaming `message` to
`description` or re-keying the ids means editing the fixture and those assertions in the
same PR. Note that spec is not in the CI matrix (§C), so nothing would have caught it.

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

**Two hard constraints on the reviewer verdict schema — added 2026-08-19.**

1. **`error` is a reserved key.** `is_placeholder_record`
   (`src/api/services/slide_repository.py:41-61`) returns `True` when the record's top level
   **or any verdict value inside it** has `error is True`. §I makes that helper the *only*
   sanctioned way to detect a failed position, so a reviewer verdict that used
   `{"error": true}` for its own purposes would make a healthy slide read as a
   failed placeholder everywhere the helper is consulted — release query, all-committed
   deck-review trigger, and the UI error badge. The reviewer schema must either reserve
   `error` or nest its findings under a namespaced key inside the per-hash verdict.
2. **The record is aggregated flat into save points.** `get_verification_map`
   (`session_manager.py:1793-1811`) merges every row's `{content_hash: verdict}` into one
   flat dict that feeds `create_version`, so whatever the reviewer writes here is persisted
   into `slide_deck_versions.verification_map_json` permanently. `slide_repository.py:290-301`
   records the measured version of this defect (a flat `{"error": True, "message": …}` record
   was both invisible to the UI and baked into save points). Findings must stay inside the
   `{content_hash: verdict}` shape; a record keyed any other way is silently lost.

---

## G. Testing non-determinism — restructured

§9's three layers are replaced by **four, organised by what each layer needs in order to
run.** The spec conflated "excluded from CI" with "rarely run", but the real constraint is
environmental: CI has no LLM, while a local machine *can* reach Databricks. The repo is
currently personal; a move to a company org will change this.

**Correction 2026-08-19 — `-m "not live"` is NOT applied "throughout", and the largest job
has no fake credentials either.** The integration jobs do pass
`DATABRICKS_HOST: https://test.cloud.databricks.com` / `DATABRICKS_TOKEN: test-token` and
`-m "not live"` (`test.yml:154-158`, `:199-208`). The **`unit-tests` job does neither**: it
runs `pytest tests/unit -v --tb=short -n auto` with **no marker filter and no
`DATABRICKS_HOST`/`DATABRICKS_TOKEN` at all** (`test.yml:100-105`). The repo already
documents the consequence, in `tests/unit/test_dependencies_resolve.py:19-25`: *"Both tests
are marked @live. The unit CI job (test.yml:102) runs `pytest tests/unit …` with NO -m
filter, so these tests ARE collected in CI. They are currently saved only incidentally
because the Databricks proxy host is unreachable…"* — and `pyproject.toml:104`'s own marker
description ("excluded in CI with -m 'not live'") is the convention that job does not honour.
So under `tests/unit/`, **the `live` marker is not a CI gate**; the working convention is a
self-skip guard inside the test. This matters to G1 below, because it decides where layer 3
must live.

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

**`tests/agentic/` — a sibling of `tests/unit/`, not a subdirectory of it.** That placement
is what makes the marker sufficient: no CI job collects `tests/agentic/`, whereas the
`unit-tests` job collects everything under `tests/unit/` regardless of markers (§G intro).
A layer-3 suite parked under `tests/unit/` would be collected by CI on day one.

**Built CI-ready now, enabled later — and "enabled" means two mechanisms, not one.**
When the repo moves to a company org, turning this on must be a workflow change and nothing
else, no test rewrites. Concretely:

- **The workflow gate** is a *new job* that runs `pytest tests/agentic -m live` with real
  credentials. Adding `-m "not live"` to the `unit-tests` job would be a separate,
  independently useful change, but PR3 must not depend on it.
- **Every layer-3 test also carries a self-skip guard** (the convention
  `test_dependencies_resolve.py` documents), so a test that is somehow collected without a
  reachable endpoint skips rather than fails. Marker for *selection*, guard for *safety* —
  PR3 ships both, because the marker alone is not load-bearing in this repo.

Recorded as an explicit follow-up so it is not rediscovered.

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
single deck-level write.

Once per turn, so exactly one `version` bump and no contention. Before the fan-out, so the
CSS contract is persisted while builders run and an incrementally-released slide renders
styled. The design contract already lives in the spec, so this is persisting what the
architect decided — design is *decided* by the architect and *enforced* by the foreman, as
§5.2.8 says.

Rejected: writing after all slides land (leaves incrementally-released slides unstyled
mid-turn); adding a deck-level method to `SlideWriter` (invites per-slide calls that would
409 each other — the contention row-per-slide exists to remove).

#### H1a. PR3 must ADD a deck-level writer — `save_slide_deck` cannot do this job

**Corrected 2026-08-19.** An earlier draft of this section said the write goes "via the
existing `session_manager.save_slide_deck` path". It cannot. Read against the code, that
method has exactly two behaviours and neither is a deck-level-only write:

- **`deck_dict=None`** → `deck.css` is *never assigned*. Both assignments live inside
  `if deck_dict:` (`session_manager.py:1356`, assignment at `:1366`; the only other one is
  `restore_version`'s at `:2246`). Worse, the same call sets `deck.deck_json = None`
  (`:1303`, `:1320`). So this branch writes no CSS at all.
- **`deck_dict={…}`** → the block runs `_upsert_slide_row` for **every** slide in
  `deck_dict["slides"]` **and then** `_prune_slide_rows_beyond(db, deck_owner.id, len(slides))`
  (`:1403`), which hard-deletes every row at `position >= len(slides)` (`:425-457`). A
  *pre-fan-out* call necessarily carries a `slides` list shorter than the live row count, so
  it would **truncate the live deck mid-turn** — and the read path serves rows whenever any
  exist (§H2), so the viewer would show the truncated deck, or fall back to a
  just-emptied blob if the list were empty.

`save_slide_deck` also takes **`html_content` as a required positional** (`:1251-1255`), which
the graph has not knitted at fan-out time. And there is no deck-level-only alternative in
`SessionManager`: `update_session` (`:884-925`) touches only `session.title`,
`slide_deck.title` and `slide_deck.slide_count`, and does not bump `version`.

**So PR3 adds a new writer** — a deck-level-columns-only method that bumps `version`,
enforces the optimistic lock, and touches **no `session_slides` rows**. It reuses
`save_slide_deck`'s locking shape (`session_manager.py:1309-1314` for the lock,
`:1321` for the bump) — which is also why the *existing* method cannot be called per slide,
and why `SlideWriter` deliberately does not use it — but not its dual-write body.

#### H1b. The write must enumerate five deck-level columns, not two

**Added 2026-08-19.** The row-read path reconstructs the deck from deck-level columns, not
from `deck_json` (`session_manager.py:1538-1552`), so a column the graph never writes is a
column the deck never has. `save_slide_deck`'s own comment (`:1360-1365`) names the cost:
*"Missing css/external_scripts costs every export its stylesheet and the Chart.js CDN;
missing head_meta reverts a custom viewport to `SlideDeck.knit()`'s hardcoded default (F5)."*

| Column | If the graph never writes it | Self-heals? |
|---|---|---|
| `css` | unstyled deck — the §H defect | no |
| `title` | untitled deck and untitled session row | no |
| `external_scripts_json` | Chart.js CDN missing from every export | **yes** — `SlideDeck._ensure_default_external_scripts` (`src/domain/slide_deck.py:74`) re-adds the defaults in `__init__` and `knit` |
| `head_meta_json` | custom viewport and every other `<meta>` silently reverts | no |
| `scripts_content` | deck-level JS lost from the row-read path | no |
| `slide_count` | **the session list renders `0 slides`** for every graph-built deck (`src/api/routes/sessions.py:233`, `session_manager.py:836` — it is a *column*, not derived; only `get_slide_deck`'s own dict derives it from `len(slides_list)`) | no |
| `html_content` | raw-HTML debug view empty; `save_slide_deck` treats it as required | no |

`slide_count` and `html_content` are only knowable **after** the fan-out, so they belong to
§L2's second (post-commit) write, not the pre-fan-out one. `css`, `title`, `head_meta_json`
and `scripts_content` are decidable up front. The two writes together must cover all seven;
neither alone does.

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
  otherwise (`session_manager.py:1486-1497`, blob fallback at `:1572`; the code comment reads
  "Any rows at all means the dual-write has run; use rows as truth"). A stale blob is **unreachable**, not wrong.
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
| spec §5.2.1 | tool manifest comes from `AgentConfig.tools` | it must also carry the design-system library, or the architect cannot offer a brand it cannot see (§M1) |
| spec §4.1 slide level | `SlideSpec` fields are purpose / brief / assumes / hands-off / data refs | plus a **template section assignment** (§M3) |
| `design-system-library.md` §9 | a first-request template pin is stripped | fixed on the **graph path** only; the browser path is unchanged (§M2) |
| current pinned-template prompt block | injects the whole layout for the whole deck | per-slide **section extraction**; the layout never goes to a builder whole (§M3–§M5) |
| `migrations-run-at-startup` memory | backfills go in the FastAPI lifespan | superseded — they run **once pre-fork** in `run.py::init_database` and `SystemExit(1)` on failure (§L8). §E2 is corrected in place; the still-stale *source* docstrings are named in §L8 |
| PRD §14 (review-fatigue mitigation) | "Objective defects are fixed silently, **not reported**" (`2026-07-30-tellr-agentic-rebuild-prd-design.md:695`) | auto-fixed findings **are** reported, as a read-only "we fixed this" list in the drawer (§F2). Deliberate: PRD §3 (`:121-122`) requires "what was fixed is visible", and PRD §7.3 (`:379-380`) already says "the *list of what was auto-fixed* is shown in chat for transparency, along with the iteration count" — so the PRD contradicts itself and §F2 picks the visible branch. §F2 also moves that list from **chat** to the **drawer**, read-only; §14's fatigue concern is answered by read-only presentation rather than by silence |

---

---

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
Two items that stood here were later resolved by §M below, and are listed so the change of
status is visible rather than silently dropped:

- ~~How the architect converses about brand~~ → **resolved in §M1/§M2.**
- ~~Whether design-system templates inform the deck spec's slide briefs~~ → **resolved in
  §M3–§M5.**

Still open, and deliberately so:

- **The two probes §M7 names.** They size the extraction implementation; neither changes the
  design.
- **Which deterministic CSS the pre-fan-out write persists**, if any (§L2a). The candidate is
  the pinned template's `token_css` plus its own `<style>` block; this document does not yet
  take that decision.
- **How `merge_css` is extended to survive at-rules** (§L2a) — carry at-rules through, or
  dedupe by exact block text. Either is small; both need an at-rule survival test.
- **The tone-vs-BRAND-MANUAL precedence rule** (§E1). The collision is named; which artifact
  wins is not settled.

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

`chat_service._ensure_pinned_template_token_css` runs `ensure_deck_token_css` before the deck
save in `send_message` (`chat_service.py:670`, saving at `:686`) and `send_message_streaming`
(`:1469`, saving at `:1485`). Its docstring records why prompt prose was insufficient: a
pinned deck "referenced 57 `var(--…)` tokens while defining none, washing out preview and
both PPTX export paths. Prompt prose is not a guarantee; this is."

**Premise corrected 2026-08-19 — it is not "before every deck save".** It runs at exactly
**two of the seven** `save_slide_deck` call sites. `reorder_slides` (`:2742`), `update_slide`
(`:2822`), `duplicate_slide` (`:2888`), `delete_slide` (`:2952`) and `tour.py:82` all save
without it, and `restore_version` writes the deck-level columns directly
(`session_manager.py:2229-2246`) without it either. The backstop is a *generation-path*
guarantee, not a save-path invariant — which makes the conclusion below stronger, not weaker,
because the graph path replaces exactly the two flows that have it.

**Both call sites are in the flows PR3 deletes.** PR3's reviewers write *rows* via
`SlideWriter`, which is not a deck save, so on the graph path the backstop never fires and a
pinned-template deck ships washed out in preview and both exports.

**Resolution — two deck-level writes per turn:**

| When | Writes | Why there |
|---|---|---|
| Before the fan-out | title, `head_meta_json`, `scripts_content`, and whatever deterministic CSS exists up front (§L2a) | so incrementally-released slides render styled (§6.2's payoff) |
| After all positions commit, before the deck-review trigger | aggregated builder CSS (§L2a), `slide_count`, `html_content`, then `ensure_deck_token_css(deck.css, token_css)` | the backstop **compares emitted deck CSS** against the token stylesheet, so it cannot run before builders have emitted any; `slide_count`/`html_content` are only knowable after the fan-out (§H1b) |

Two `version` bumps per turn, both deck-level, neither per-slide — so the no-contention
property holds. `ensure_deck_token_css` is idempotent and prepends (deck CSS stays later in
the cascade, so anything the model authored still wins), and it never raises: a failed
guarantee must not block the save.

This revives the two-write sequencing dropped when §H2 was cancelled, for a different and
now-measured reason.

### L2a. Nobody aggregates the builders' CSS — the second half of §H's defect

**Added 2026-08-19.** §H1's write had an unexamined premise: that there is *something
CSS-shaped* to persist. On the design-system path there is not, and after the fan-out nobody
collects what the builders emit. Two facts:

- **`deck.css` is populated today by exactly one mechanism**, and it is a monolith
  mechanism: `SlideDeck.from_html` walks `soup.find_all('style')` and joins the blocks
  (`src/domain/slide_deck.py:193-198`). The graph never calls it — `SlideWriter` writes
  per-row `html` only.
- **The design contract is no longer a stylesheet** (§L1/§L3): it is a prompt artifact plus a
  `{design_system_id, template_id, slide_style_id}` reference. So "persist the CSS contract"
  has no referent on the design-system path.

What *is* deterministically available before the fan-out is the pinned template's
`token_css` and its own `<style>` block — the same two artifacts §M5 already hands to every
builder. That is a real candidate for the pre-fan-out write, and it is a decision this
document does not yet take.

**The unassigned owner is the post-commit aggregation.** Nothing in §H/§L/§M says who turns
the builders' emitted `<style>` blocks into deck-level CSS. Left unassigned, a graph deck
reaches `ensure_deck_token_css` with `deck.css` empty; that backstop restores only *custom
properties* and *`@font-face` families* (`design_system_templates.py:381-422`), so it returns
the token stylesheet alone and the deck knits with **no layout CSS** — the exact defect §H
was written to close, reached by a different route.

**The dedupe question, and why the obvious answer is not quite the answer.** §M5 hands every
builder the template's full `<style>` block (a deliberate trade-off — see §M5), so 15
builders emit up to 15 copies of the same stylesheet. `SlideDeck.update_css` →
`src/utils/css_utils.merge_css` looks like the ready-made merge, and for the dedupe half it
is: `parse_css_rules` maps `{selector: declarations}` and `dict.update` collapses identical
selectors, so N copies become one.

**But it silently drops every at-rule.** `parse_css_rules` keeps only
`rule.type == 'qualified-rule'` (`src/utils/css_utils.py:28-34`). Measured 2026-08-19 on a
stylesheet containing `:root`, `@font-face`, `section.slide`, `@media print` and
`@keyframes`, `merge_css(css, css)` returned **only** `:root` and `section.slide`.
`@font-face` happens to survive via `ensure_deck_token_css`'s re-emit, but a template's own
`@media` and `@keyframes` rules would be lost permanently — outside what the safety net
covers, which is precisely the failure mode §M5 rejects pruning to avoid.

**So the aggregation step is PR3 work with one open choice:** extend `merge_css` to carry
at-rules through, or dedupe by exact block text rather than by selector. Either is small and
testable; both need an at-rule survival test. Do **not** adopt `merge_css` as-is.

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

**§M3 adds a per-slide companion.** `SlideSpec` gains a section assignment — which of the
template's slide roots this position builds from. It is an **index or class reference, never
extracted markup**, for the same reason: the spec stores *which*, and deterministic code
resolves *what* at build time. A spec carrying layout bytes would go stale against its
template and would put brand markup on the LLM's rewrite path.

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

**Corrected 2026-08-19 — the frame rules do NOT arrive on both paths. There are three
cases, not two.** An earlier draft said the compiler emits them for a design-system deck and
`DEFAULT_SLIDE_STYLE` "carries its own" for the legacy path. Measured against the code:

| Resolved style | Carries the safe-area numbers? |
|---|---|
| design system (`compiled_style_content`) | **yes** — `_SLIDE_FRAME_CONSTRAINTS` is emitted by the compiler |
| no style at all → `DEFAULT_SLIDE_STYLE` | **no safe area at all.** `src/core/defaults.py:5-26` carries only body-level `1280x720px` / `margin:0; padding:0; overflow:hidden` (`:14-15`). There is no 88 px, no 72 px, no 56 px, and no clearance rule of any kind |
| a selected library slide style | **unknown, and usually no** — `agent_factory.py:216` does `slide_style = style.style_content`, which **replaces** `DEFAULT_SLIDE_STYLE` wholesale. Whatever the user's style content says is all the builder gets |

This is not cosmetic: §L7 puts "content overflows its frame" on the build reviewer's
objective criteria list and tells it to judge against these exact numbers. As drawn,
legacy-style decks would be judged against numbers their builder's prompt never received.

**So the rule needs a third case.** The builder skill still **must not hardcode** the
numbers — a design-system deck would then get two conflicting copies — but deterministic
prompt assembly **must inject `_SLIDE_FRAME_CONSTRAINTS` when the resolved style does not
already carry it**. "Already carries it" is a property of the resolved text, so the check
belongs where the style is resolved, next to the branch at `agent_factory.py:134-216`, not in
the skill. The reviewer and the builder must be handed the same numbers or §L7's criterion is
unfair by construction.

### L6. What PR3 must preserve rather than delete

The plan's Phase 9.2 says `agent_factory` should be deleted or "reduced to graph config
assembly". That is no longer safe — it is now the only home for:

- the design-system resolution branch and `compiled_style_content` currency check;
- pinned-template block assembly (`build_selected_template_block`,
  `get_template_for_generation`);
- **the late type-scale re-assertion** — `strip_type_scale_region_markers` (`:170`),
  `extract_type_scale_block` (`:292`), `build_type_scale_reassertion` (`:294-295`) and the
  `template_pinned` flag (`:134`, set at `:194`). This is not incidental plumbing: the
  compiled artifact delimits its type-scale region with control-character sentinels so the
  numbers restated **last** in the prompt can never drift from the ones injected earlier, and
  **a pinned template changes those numbers** (its own CSS title sizes outrank the design
  system's ramp). Dropping it re-opens a measured defect — the model fell back to its own
  heading sizes when the scale was stated only early;
- **`search_brand_assets` tool gating.** **Corrected 2026-08-19:** the gate is *not* "only
  when `config.design_system_id is not None`" — that is an outdated docstring
  (`agent_factory.py:357-358`) which an earlier draft of this section repeated. The code is
  `if config.design_system_id is not None and _design_system_is_active(config.design_system_id)`
  (`:404-406`), and the comment above it records the measured defect the second half fixes: a
  session keeps its pin after the design system is soft-deleted, and on the id alone
  generation "got a fully working brand tool for a TOMBSTONE (measured: 'Found 2 brand
  asset(s)' with embeddable handles) while the prompt branch, which does filter `is_active`,
  supplied no brand at all." `_design_system_is_active` (`:315-350`) fails **closed**, and its
  docstring warns it is a different question from `chat_service.resolve_active_design_system_id`
  (which deliberately still resolves a tombstone's bytes, for the D7 retention contract).
  §L1 already states the prompt-side inactive case correctly, which is what made this
  inconsistency easy to miss. Preserve **both halves** — this is a live input to the
  architect's tool manifest (§5.2.1) and the analyst's tool grants.

**Name the regression harness, because "move, don't delete" needs one.** Six unit suites pin
`_get_prompt_content` / `_build_tools` directly: `tests/unit/test_ds_generation_state_matrix.py`,
`test_design_system_compiler.py`, `test_prompt_precedence_fixes.py`,
`test_factory_tool_spotlighting.py`, `test_agent_factory.py` and `test_design_systems_routes.py`.
Whatever module the resolution logic moves into, those tests must be repointed at it and seen
to pass — not deleted. Under §0's baseline rule a deleted suite is invisible, so this is the
same trap §D1 names for the security controls.

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
  **Two source docstrings still describe the old placement** and will mislead a reader who
  trusts them: `src/core/backfill_session_slides_startup.py:4` ("from its FastAPI lifespan on
  every boot") and `:239` ("Called from the FastAPI lifespan alongside `migrate_profiles`").
  The code is correct; only the prose is stale. Worth fixing in PR3 while that file is open.
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

---

## M. Brand and templates in the agentic core

Resolved 2026-08-18, after §L, closing the two items §K left open. This section replaces
§K's "not decided here" entries for brand and templates.

### M1. Brand is conversationally changeable, always confirming before a rebuild

The architect may set both `design_system_id` and `template_id` through conversation ("use
the Acme brand", "pin the data-slide template"). This follows the system's own principle: in
a conversational agentic system, anything the user can configure they should be able to ask
for.

Because changing either restyles every slide, it routes through §4.6's
**confirm-then-rebuild-all** path — the architect states what it is about to do and waits.
That path already exists for exactly this case; nothing new is needed to gate it.

Two consequences:

- **The architect's tool manifest must include the design-system library** — system names and
  descriptions, plus each system's template catalog. §5.2.1 derives the manifest from
  `AgentConfig.tools`; it now also needs the brand inventory, or the architect cannot offer
  what it cannot see.
- **One conversational act mutates two fields.** Setting `design_system_id` *clears*
  `slide_style_id` at the column bind (§L1), so the confirmation must say the deck's slide
  style is being dropped, not silently drop it.

### M2. First-turn pinning is fixed on the graph path

Today a template pin submitted on the request that *creates* a session is **stripped**,
because a pin arriving at session-creation cannot be distinguished from another browser
surface's carry-over (`design-system-library.md` §9). The documented workaround is "send your
first message, then pin".

A conversational pin hits this immediately — "build me an Acme-branded deck" is a first turn.
**PR3 fixes it for the graph path only.** The ambiguity that motivated the strip is a
*browser-surface* ambiguity; a pin the architect derives from the user's message is
unambiguous architect intent, so the graph path can honour it without reintroducing the
carry-over problem for the pre-session browser path. The browser path's behaviour is
unchanged.

### M3. Grain-agnosticism: the architect assigns, deterministic code extracts

The bundle format permits a template to be **either** a single slide layout **or** a whole
deck skeleton whose sections the model trims or repeats, and it does not record which. The
agent core therefore must not assume either — it must work for both, including bundles that
mix them.

**The division of labour, and the line that must not be crossed:**

| Job | Who | Why |
|---|---|---|
| "Slide 3 plays the section-divider role → use that section" | **architect** (LLM) | intent and assignment; model-appropriate |
| Extract that section's HTML and CSS, byte-for-byte | **deterministic code** | brand bytes must NEVER pass through a model |

**The architect never rewrites layout HTML or CSS.** That is not a stylistic preference: it
is the failure `ensure_deck_token_css` was built to catch. A model dropped 57 `var(--…)`
definitions and washed out preview and both PPTX export paths (§L2). An architect retyping or
summarising layout chunks would reproduce that defect with more steps and no backstop.

**Grain is measured, not assumed.** Extraction requires parsing the layout, and the parse
reveals the grain: `find_slide_roots(BeautifulSoup(layout_html))` returns **1** root for a
per-slide template and **N** for a deck skeleton. Probed on both shapes:

```
deck skeleton  -> 3 slide root(s); tags=['section','section','section']
                  classes=[['slide','title'], ['slide','divider'], ['slide','data']]
single slide   -> 1 slide root(s); tags=['div']
section extracted verbatim: <section class="slide divider"><h2>Section</h2></section>
```

This reuses existing tested code — the same function `SlideDeck.from_html` calls, which main
hardened for precisely this case (a template emits `<section class="slide">` where generation
emits `<div class="slide">`; `src/services/design_system_templates.py:444`
`_detect_slide_root_tags` relies on the same convention).

**Extraction must read the layout through the normalizing accessor, not the raw column.**
`normalize_root_tag_selectors` (`src/services/design_system_templates.py:527`, applied at
`:703` on self-heal and `:773` on materialize) is what makes a template's *tag-keyed* CSS
(`section { … }`) also match the `div.slide` roots generation emits. Reading
`template.layout_html` directly bypasses that pass, so an extracted section would carry CSS
whose selectors match nothing in the built slide — a silent, whole-section styling loss.

**Note the promotion rule.** `SLIDE_WRAPPER_TAGS` is `{"section", "article"}` only — a
`<div>` is deliberately excluded, and so is `<main>`. A template that wraps its slides in a
non-promoting tag keeps that wrapper's styles *outside* the extracted section. This is the
first probe below.

**The resulting behaviour, per grain, with no grain detection in the graph:**

| Sections in layout | Architect assigns | Builder receives |
|---|---|---|
| N | section *i* per slide | one section |
| 1 | that section for every slide | the same section |
| fewer than the slide count | reuses sections, varying which | its assigned section |

The last row is already the shipped instruction — *"vary which slide sections you reuse
rather than repeating one"* — which was written for a monolith emitting a whole deck and
becomes a per-slide assignment here.

### M4. The architect assigns from a deterministic section inventory

To assign well the architect needs to know what the sections *are*, not just their template's
name. It is given a **section inventory** derived from the same parse:

per section — its index, tag, class list, a short text snippet (first heading or leading
text), and its structural affordances (does it contain a canvas, an image, a table).

The inventory is deterministic, a few hundred bytes per section, and sufficient for
assignment. It is **not** the raw layout: a real Claude-Design template measures **24–47 KB**
(`design_system_templates.py:59`), and the architect holds the only durable conversation in
the system (§5.3), so injecting the full layout into it every turn would be both expensive
and contrary to §7.2's compaction story. The inventory is per-turn context, never accumulated
into the transcript.

### M5. CSS travels whole with every section — never pruned

Each extracted section is paired with the template's **full `<style>` block and its
`token_css`**, unpruned.

Selector pruning was rejected. CSS is small next to markup, so pruning buys little; and
under-including is exactly the known defect — undefined `var(--…)` references washing out
preview and both export paths. `ensure_deck_token_css` backstops *custom properties and
`@font-face` families*, not arbitrary dropped rules, so a pruner's mistakes would land
outside what the safety net covers.

### M6. What this fixes about the earlier draft

An earlier version of this section handed **every builder the full template layout** and
proposed grouping builders by template so the identical prefix would be cacheable. That was
worse on two counts, and is recorded so it is not revisited:

- **Cost.** 15 builders × ~35 KB ≈ 130k tokens of duplicated layout per build turn, before
  any content — against PRD §14's named cost-per-deck risk. Per-section extraction reduces
  this to a fraction.
- **It leaned on an unverified assumption**, that the gateway supports prompt caching.
  Gateway abstraction is workstream 2 and deferred, so the mitigation was not available to
  depend on.

The chunking approach also restores consistency with the deck spec's own design: `SlideSpec`
already carries `content_brief`, `assumes`, `hands off` and `data_references` precisely so a
builder receives only its slice. Handing over the design contract wholesale was the one place
that pattern had been broken.

### M7. Probes required before building this

Both are empirical, not design questions:

1. **Does an extracted section render standalone?** A section may depend on an ancestor's
   styles — including a non-promoting `<main>` or `<div>` wrapper that `find_slide_roots`
   leaves behind (§M3). Render an extracted section against its template's full CSS and
   compare with the same section rendered in situ. If wrappers matter, extraction must carry
   the ancestor chain (or its computed contribution) rather than the bare root.
2. **Does the section inventory support good assignment?** Give the architect an inventory
   from a real multi-section bundle and check its assignments are sensible — that a title
   slide gets the title section rather than the data section. If names and snippets prove
   insufficient, the inventory grows (thumbnails already exist per template, though not per
   section).

Neither blocks the design; both size the implementation.
