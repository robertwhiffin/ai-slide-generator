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

**Which interpreter — added 2026-08-20. Every number in this section is the shared pyenv's,
and the in-tree `.venv` is NOT it.**

| Interpreter | langgraph | mlflow | svgpathtools | `DEFAULT_RECURSION_LIMIT` | `Send(timeout=)` |
|---|---|---|---|---|---|
| `~/.pyenv/versions/3.11.0/bin/python` — **what this section measures** | 1.2.10 | 3.14.0 | 1.7.2 | **10007** | **present** |
| `<repo>/.venv` — **stale; do not use** | 1.0.3 | 3.6.0 | **absent** | 25 | absent |

`CLAUDE.md` states the environment fact this rests on: the Python env is a **shared pyenv
site-packages**, not a per-repo venv (and never `pip install` into it from an agent — it
corrupts parallel agents' runs). The repo nevertheless still contains a gitignored `.venv/`
(`.gitignore:20`) left over from earlier work, and it is exactly the
not-installed-to-spec environment this section was written to warn about. In it, both causes
below reproduce (measured 2026-08-20: 17 failed across `test_html_to_pptx.py`,
`test_google_slides_converter.py` and `test_mlflow_tracing.py` — 14 `svgpathtools` + 3
mlflow `trace_location`), the `recursion_limit` inversion above is **false** (the default is
25 there), and §I's `Send(timeout=)` option **does not exist**. Run the baseline, and every
probe in this document, with `~/.pyenv/versions/3.11.0/bin/python -m pytest …`. **Do not
delete or modify `.venv`** — just never reach for it; an executor or subagent that defaults
to `./.venv/bin/python` will "reproduce" a baseline this document has already retracted.

| | Pre-upgrade | Post-upgrade | After the local env was installed to spec |
|---|---|---|---|
| Result | 20 failed / 2003 passed / 8 skipped | 17 failed / 2006 passed / 8 skipped | **3 failed / 4177 passed / 8 skipped** (4188 collected, `pytest tests/ -n auto`, 2026-08-19) |

**The baseline for PR3 is 3 failures across 2 causes:**

| Cause | Files | Count | Reproduces anywhere? |
|---|---|---|---|
| deploy-autoscaling: `_get_or_create_lakebase` never returns the autoscaling result. **Two distinct assertion strings** — `:124` `AssertionError: assert 'provisioned' == 'autoscaling'` and `:152` `AssertionError: Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.` | `tests/unit/test_deploy_autoscaling.py` (`TestGetOrCreateLakebase::test_returns_autoscaling_when_available`, `::test_falls_back_when_autoscaling_creation_fails`) | 2 | **yes** — environment-free |
| `GenieToolError: Failed to query Genie space after 3 attempts` | `tests/integration/test_genie_integration.py::test_genie_conversation_continuation` | 1 | **no** — depends on local `.env` + a stale stored Genie space id; see below |

**Match on the cause, not on one quoted string — added 2026-08-20.** An earlier draft of this
table labelled the deploy-autoscaling cause with `assert 'provisioned' == 'autoscaling'`
alone. Re-measured: that is the failure at
`tests/unit/test_deploy_autoscaling.py:124`; the second failure in the same file, at `:152`,
raises a completely different message (`Expected '_get_or_create_lakebase_provisioned' to have
been called once. Called 0 times.`). An executor grepping the quoted string would count **1**
where the table says **2** and conclude a failure had been fixed. Both are the same underlying
cause — the orchestrator's autoscaling branch — which is exactly why the *cause* column has to
carry the mechanism and not a copied traceback line. Measured 2026-08-20:
`pytest tests/unit/test_deploy_autoscaling.py` → `2 failed, 37 passed`.

**The third failure is environment-dependent, but NOT in the way a first measurement
suggested — corrected 2026-08-20.** `tests/integration/test_genie_integration.py` is
`pytestmark = [pytest.mark.integration, pytest.mark.live]` (`:17`) behind two module-scoped
fixtures that `pytest.skip` when `DATABRICKS_HOST`/`DATABRICKS_TOKEN` are falsy or the Genie
space is unconfigured (`check_databricks_connection` `:20-43`; `check_genie_config` `:46-66`).

An earlier revision of this section reported "clear the credentials and it skips — so on any
other machine the baseline is 2 failures / 1 cause." **That conclusion is wrong**, and the way
it is wrong is worth recording because it is a trap for anyone re-deriving this baseline. Two
measurements, both reproducible, that disagree:

| Method | Result | Why |
|---|---|---|
| `DATABRICKS_HOST= DATABRICKS_TOKEN= pytest …` (assign empty) | `2 skipped` | the empty var **exists**, so `load_dotenv()` — `override=False` by default — declines to replace it; `os.getenv` is falsy; both fixtures skip |
| `env -u DATABRICKS_HOST -u DATABRICKS_TOKEN pytest …` (fully unset) | **`1 failed, 1 skipped`** | the var is **absent**, so `load_dotenv()` at `src/core/database.py:28` supplies it from the gitignored `.env`; the fixtures proceed and the real Genie call fails |

`load_dotenv()` runs unconditionally at import of `src/core/database.py`, so **clearing the
shell environment does not clear the credentials** on any machine that has a `.env` — which is
the ordinary dev setup here.

**And credentials are not the actual cause.** The failing call resolves its Genie space from
the **database**, not the environment: `check_genie_config` reads
`get_settings().genie.space_id` (`:52-59`), which on this machine is
`01effebcc2781b6bbb749077a55d31e3` — a space that no longer exists, hence
`Space with id … not found`. So the cause is **a stale Genie space id in local database
settings**, and it would persist even with perfectly valid credentials.

**What this means for the gate.** The 2-failure cause (deploy-autoscaling) is environment-free
and reproduces anywhere. The 3rd is local-state-dependent: an executor on a machine with no
`.env` *and* no stored Genie space sees **2 failures / 1 cause**; one with this machine's
`.env` and stale stored space sees **3 / 2**. Read the gate as **"no NEW cause, and no change
to the deploy-autoscaling cause"** rather than as an absolute count — which is what "by cause,
never by count" meant in the first place. Fixing or clearing the stored Genie space id would
remove the third failure legitimately, and that is not a regression.

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

**The gate, stated so it survives a change of machine:** with live credentials bound,
**any 4th failure, or any change to one of those two causes, is a regression PR3 caused**;
without them, the baseline is **2 failures / 1 cause** (deploy-autoscaling only) and any 3rd
is the regression. Record which of the two you measured alongside the number, or the count is
not comparable to anyone else's.

---

## A. The seven skill prompts

Zero of the seven exist. **Corrected 2026-08-20 — the marker an executor should grep for is
not `[To be filled in Phase 2]`.** That string occurs twice in
`docs/superpowers/plans/2026-08-09-pr3-langgraph-core.md` and neither occurrence is in Phases
2–3: `:417`, inside a **Phase 1** stub-file example, and `:3465`, in the plan's own
placeholder-scan note. Phases 2–3 (`:680-:1282`) are substantial; what is hollow inside them
is the prompt bodies, marked `"[full prompt from spec §5.2.1]"` (`:700`),
`"""...[full prompt]..."""` (`:763`) and `"[prompt from spec §5.2.2]"` (`:810`).

Those placeholders name spec §5.2.1/§5.2.2 as the source of "the full prompt", and **those
sections hold behavioural description, not prompt text** — §5.2.1 describes the architect's
job, its data awareness, its tone hook and its two output types; it contains no prompt. That
is exactly the trap §A1 exists to close: an executor who follows the placeholder to its cited
source finds a role description and invents the prompt. The gap is **content, not code**, and
it is the single largest one.

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
- **One genuine edge — restated 2026-08-20.** An earlier draft called it "an agent-caused
  HTML change arriving on a human route". Per B1 that cannot happen: the graph calls
  `session_manager.restore_version` directly and never routes, so an agent-driven restore
  fires no trigger at all. The real edge is a **stale-marker** edge and it does not depend on
  who restores: a restore replaces whole-deck HTML, so any dirty marker the pre-restore
  deck's edits left behind now describes a deck that no longer exists. Resolved by B3 below,
  which earns its place on that ground (and on the `deck_spec_json` snapshot) rather than on
  origin attribution.

### B1. The trigger call lives in the route handler, never in the service method

**This is a decision about code PR3 will write, not a description of code that exists —
corrected 2026-08-20.** An earlier draft stated it in the present tense. Verified: **neither
`spec_sync` nor `mark_dirty` exists anywhere in the repo** (the only `mark_dirty*` hits are
matplotlib's `mark_dirty_rectangle` in site-packages). PR3 builds both, and the placement
rule below is the design constraint on that build.

`spec_sync.mark_dirty(session_id)` **is to be called from the route handlers** in
`src/api/routes/slides.py` and `src/api/routes/tour.py` — never from the service methods in
`chat_service.py`. The graph calls those service methods directly, so it never fires the
trigger.

Placed that way, §4.5's claim becomes true by construction rather than by convention:
"arrived via the route" *means* "a human did this", because the route is the only human
entry point and the
graph does not use it. No stored flag, no `origin=` parameter to forget, no ContextVar to
leak. The failure mode requires actively wiring a new route call, not merely forgetting a
parameter.

**`tour.py` is named above but the justification does not reach it — added 2026-08-20, and
this is a sub-decision PR3 must take rather than a settled one.** The rule's whole warrant is
"a human authored this". `src/api/routes/tour.py` authors nothing: `_phase2_add_slides` loads
a **canned fixture** (`_load_fixture()`, reading `src/api/fixtures/tour_demo_deck.json`) and
saves it via `sm.save_slide_deck` at `:82`. It is deck *creation* from fixed bytes, not an
edit, and the bytes are identical on every tour. Firing `mark_dirty` there schedules an LLM
narrative-arc re-description of the same demo deck for every user who takes the tour, for no
user value and at §B2's per-window cost. **Resolved 2026-08-24: ship the arc description inside the fixture.**
`src/api/fixtures/tour_demo_deck.json` (4.7 KB, module-cached at `tour.py:34-39`) gains a
deck-spec field, so the tour deck arrives *with* its spec and `mark_dirty` is never called on
this route. Chosen over simply excluding the route because it costs one JSON field and is
strictly better: the tour then also demonstrates spec §7.1's spec view, which an
excluded-and-specless tour deck could not. The fixture is static, so its arc description is
authored once by hand — never at runtime, and never per user.

`tour.py` therefore does **not** appear in §B1's trigger list. The rule's warrant ("a human
authored this") is preserved without exception.

**And one deck-content route this section does not consider at all:
`POST /sessions/{session_id}/duplicate`.** See §B5.

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

**Two dependencies the sweeper needs and this document does not supply — added 2026-08-20.**
Both are PR3 work and neither is listed in §K, so both are named here.

1. **Storage.** "The dirty marker lives in the database" and the claim step wants
   `claimed_at`, but **no table or column is nominated anywhere.** §H1b's eight-column
   deck-level enumeration does not include it (correctly — it is not deck presentation state),
   and §E2's migration discussion is about *dropping* columns, not adding them. So PR3 owes a
   schema decision (a column pair on `session_slide_decks` — `spec_dirty_at` + `claimed_at` —
   or a small dedicated table if a marker should outlive the deck row), **plus a new
   `_migrate_*` step**. Under §L8 that step goes in the pre-fork chain reached from
   `run.py::init_database`, not the FastAPI lifespan, and it must be sequenced against the
   §E2 drop in the same `_run_migrations()` list. None of that is assigned today.
2. **Identity.** A sweeper tick has no request, and Tellr's identity primitives are
   request-scoped. `get_current_user()` returns `None` outside a request
   (`src/core/user_context.py:21-23`), and `get_user_client()` **fails closed in production** —
   `UserClientRequiredError` at `src/core/databricks_client.py:492`, raised at `:536`, with
   `:511-515` recording that SDR-4437 HIGH-6 removed the SP fallback for everything except
   non-prod. The
   LLM call itself is fine (`agent_factory.py:56` uses `get_system_client()`, which is
   SP-scoped by design), but three things around it are not: **`modified_by` stamping** (the
   deck writer takes it as a parameter, `session_manager.py:1259`, and the arc review's write
   would have nothing to pass), **deck permission checks** (`_require_deck_permission` at
   `:733-748` resolves through the request-scoped permission context), and **usage/cost
   attribution**, which is the one thing PRD §8.1 requires be visible from day one. §B2 is
   silent on all three. PR3 must decide what identity a sweeper-driven write carries — the
   marker's own recorded author, an explicit system identity, or a captured OBO token — and
   whether an arc review may run at all without one.

### B3. A version restore cancels any pending spec review

On restore, discard the dirty marker without running the review. Two reasons: the deck those
pending edits described no longer exists, and `SlideDeckVersion` carries its own
`deck_spec_json` snapshot (`src/database/models/session.py:358`), which PR1 already restores
(`session_manager.py:2222,2240`). The restored spec is authoritative.

This also closes B0's remaining edge: the discarded marker cannot drive an arc review
against a deck that no longer exists, and — since a restore never triggers a spec update —
nothing can start hop two.

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

### B5. New scope: `duplicate_session` drops the deck spec

**Added 2026-08-20 — a gap in every other section, not a correction to one.** §H1b enumerates
`deck_spec_json`'s two touchers in `session_manager.py` (the `create_version` snapshot at
`:1939-1951` and the `restore_version` copy-back at `:2240`) and is right about both, but
there is a **third** place a `SessionSlideDeck` row is constructed and it is not one of them.
`duplicate_session` builds a fresh row at `src/api/services/session_manager.py:1014-1026`
passing `session_id`, `title`, `html_content`, `scripts_content`, `slide_count`, `deck_json`,
`verification_map`, `version=1`, `modified_by`, `locked_by`, `locked_at` — and **not
`deck_spec_json`**.

Why the other deck-level columns survive and this one does not: the duplicate creates **no
`session_slides` rows**, so the new deck reads through the `deck_json` blob fallback
(`session_manager.py:1572`), and `css`, `external_scripts`, `head_meta` and `scripts` all
live inside that blob. `deck_spec_json` does not — it is a sibling column, deliberately, and
§H1b's own row-read `deck_dict` (`:1538-1564`) confirms no deck spec is carried in the deck
dict either. So `POST /sessions/{session_id}/duplicate` (`src/api/routes/sessions.py:492`)
yields a deck whose spec is **gone, permanently, with no self-heal** — precisely the state
§H1b names the cost of ("turn *n+1*'s architect starts blind"), reached by the one lifecycle
point the document had not enumerated.

**PR3 must carry `deck_spec_json` across the duplicate.** It is a one-line addition to the
`SessionSlideDeck(...)` construction, plus the `version_number is not None` branch
(`:967-984`), which reads its deck bytes from a `SlideDeckVersion` and must therefore take
that version's `deck_spec_json` snapshot rather than the live deck's.

Note this is a **copy, not a trigger**: the duplicated deck's spec is already correct for the
HTML it carries, so §B1's `mark_dirty` must *not* fire here. That is also why the route is not
in §B1's list — but its absence there was silence, not a decision, which is what made the
column drop invisible.

---

## C. Frontend test runner

There is none: every test script in `frontend/package.json` is a Playwright variant — `test`,
`test:report`, `test:ui`, `test:headed`, `test:debug`, five in all, each invoking
`playwright test` — there is no vitest or jest, no `@testing-library`, and zero `*.test.tsx`
files. **32** Playwright specs
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
findings (`frontend/tests/e2e/slide-viewer.spec.ts:304-360`) — is absent from the matrix,
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
| **Slide-context spotlight** — `spotlight("slide_context", html, session_id=…)` (`agent.py:885-916`): prior slide HTML is untrusted input, so it is framed as `<untrusted-data>`, delimiters neutralised, injection patterns scanned/logged at the prompt boundary (SDR-4437 F-TM-12) | edit/add operations that inject prior slides | `tests/unit/test_slide_context_injection.py` |

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
3. Repoint **all three** named test files (`test_agent_safety_gate.py`,
   `test_safety_gate_http.py`, `test_slide_context_injection.py`) **and the other 10** test
   files referencing `src.services.agent` — **13 in total**, re-counted 2026-08-20 (an
   earlier draft said "both … and the other 11", which named three files and summed to 14) —
   at the new homes rather than deleting them.

**Why this is called out here:** under §0's baseline rule a deleted test is invisible — the
failure count does not rise when a suite stops existing. These two are security controls, so
their tests must be re-pointed and seen to pass, not merely absent from the failure list.

### D2. The MCP surface is a third caller this document had not accounted for

**Added 2026-08-20.** `src/api/mcp_server.py` exposes four tools — `create_deck` (`:410`),
`get_deck_status` (`:658`), `edit_deck` (`:894`), `get_deck` (`:1034`) — and parent spec §6.4
asserts their "`create_deck` / `edit_deck` contracts are unchanged, so the TAP builder, DAIS
agenda curator and KPMG pricing skills need no coordinated change". Three decisions above
land on that surface and none of them said so. None of the three reopens a decision; each
adds work its section must carry.

1. **§D's deletion breaks a documented MCP internal contract.** `_edit_deck_impl` (`:910`)
   bundles `slide_indices` into "the `slide_context` dict the agent's `_format_slide_context`
   helper expects (`{"indices": [...], "slide_htmls": [...]}`)" — and `_format_slide_context`
   is `src/services/agent.py:885`, in the file §D deletes. Spec §6.4's "contracts are
   unchanged" is true of the *tool signature* and false of the payload shape behind it. So
   PR3 must either accept that same `slide_context` shape at the graph's edit entry point, or
   repoint `_edit_deck_impl` in the same PR. Note this is also §D1's second control's
   territory: the slide HTMLs `_edit_deck_impl` pulls via `SessionManager.get_slide_deck` are
   exactly the prior-slide HTML that must go through `spotlight`.
2. **§I's placeholder is invisible to an MCP caller.** §I hands a failed position back as a
   `slide-placeholder-error` slide whose failure is legible **only** via
   `is_placeholder_record`, and no MCP response field exposes it. `get_deck_status`
   (`:815-842`) returns `status: "ready"` plus `replacement_info` and
   `metadata.clarification_needed`, so a deck containing placeholders reads as fully ready —
   recreating the measured defect that `clarification_needed` was added to fix ("hand-picked
   keys DROPPED the flag, so an automated caller reading `status` concluded the edit had
   landed when the deck was untouched", `:810-815`). PR3 must surface the failed positions
   (or a placeholder count) on `get_deck_status`, **additively**, keeping `status`'s existing
   meaning — the same pattern that field already established.
3. **§F's channel split has no MCP channel.** §F2/§F3 route findings to the drawer and to
   chat, both browser surfaces. Spec §6.4's one-shot turn "returns the deck plus a review
   summary", and nothing in §F says what that summary is or where it lands in an MCP
   response. It needs a field on `get_deck_status`/`get_deck`, decided together with the
   reviewer schema (§F1), or the one-shot caller pays for the review and receives none of its
   output.

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

**Two physical storages, not one — corrected 2026-08-20.** The same two field *names* live
in two different places, and one drop migration cannot retire both:

| Storage | Where | Shape |
|---|---|---|
| **`config_prompts` columns** | `ConfigPrompts.system_prompt` / `.slide_editing_instructions`, `Column(Text, nullable=False)` (`src/database/models/prompts.py:39-40`) | real columns — the only thing the `_migrate_*` drop below can target |
| **keys inside the `agent_config` JSON column** | `AgentConfig.system_prompt` / `.slide_editing_instructions` (`src/api/schemas/agent_config.py:97-98`, with a `field_validator` at `:100-104`), persisted through `Column(NormalizedAgentConfig, …)` on **both** `UserSession` (`src/database/models/session.py:135`) and `ConfigProfile` (`src/database/models/profile.py:31`) | JSON keys — no column to drop |

The JSON half needs its **own data migration** (strip the keys from stored blobs) plus
removal of the two fields from the `AgentConfig` pydantic model
(`src/api/schemas/agent_config.py:97-98` and the `field_validator` at `:100-104`).
**`agent_factory.py:250` branches on the JSON field, not the column** (`_get_prompt_content`
takes an `AgentConfig`, `:78-80`), and every frontend row below is the JSON shape.

**`NormalizedAgentConfig` needs NO change — corrected 2026-08-20 (a round-2 error).** A
previous round said the JSON half required "a change to `NormalizedAgentConfig` … Editing
that type is therefore not free: §L1's exclusivity guarantee depends on it." That is wrong on
both halves, and it points the executor at the one file whose documented invariant is *do not
generalise this*. The type only ever inspects `slide_style_id` and `design_system_id`
(`_normalize_mapping`, `src/database/types.py:139-156`); every other byte is passed through
untouched, and its own docstring says why (`:64-70`):

> *Deliberately SURGICAL. It would be tempting to route each blob through `AgentConfig` and
> store the result, but that round trip is LOSSY in both directions: the model ignores
> unknown keys, so a value a newer writer stored would be silently destroyed, and it fills in
> every default, so a lean `{"tools": []}` would inflate into the full field set. So only the
> one contradiction is repaired and every other byte is passed through[, on a COPY].*

A bind hook that stripped prompt keys would be exactly that generalisation. The prompt keys
therefore come out by a **one-off data migration over stored blobs**, and the column type is
left alone.

The full consumer set, verified:

| Site | Role |
|---|---|
| `src/core/init_default_profile.py:408-412` | seeds both when the default profile is created |
| `src/services/profile_service.py:204-207` | **`ConfigPrompts` insert** — new profile, from `DEFAULT_CONFIG` |
| `src/services/profile_service.py:409-413` | **`ConfigPrompts` insert** — create-with-config path |
| `src/services/profile_service.py:490-494` | **`ConfigPrompts` insert** — clone profile, copies both values |
| `scripts/init_database.py:218-222` | **`ConfigPrompts` insert** — DB init script |
| `scripts/run_e2e_local.sh:160-165` | **`ConfigPrompts` insert** — inline Python inside the local E2E bootstrap script |
| `.github/workflows/test.yml:589-594` | **`ConfigPrompts` insert** — the `e2e-tests` job's "Seed database with default data" step, inline Python in the workflow |
| `src/core/migrate_profiles_to_agent_config.py:15,17,44-45,51-52,54,76-77` | reads them at startup — **pre-fork, in `run.py::init_database` (`packages/databricks-tellr-app/databricks_tellr_app/run.py:66`), not `main.py`'s lifespan** (see the closing paragraph below; the only `main.py` callers left are the two stale build copies, both at `main.py:111` — `packages/databricks-tellr-app/build/lib/src/api/main.py:111` and `build/lib/src/api/main.py:111`. The live `src/api/main.py` no longer mentions `migrate_profiles` at all.) Line list corrected 2026-08-20: the earlier `:15,44,51-52,76` cited only the `system_prompt` line of each pair and dropped its `slide_editing_instructions` sibling (`:17`, `:45`, `:54`, `:77`) |
| `src/services/agent_factory.py:250-263` (also logged at `:504-505`) | consumes at runtime; branches on `system_prompt is not None` |
| `src/core/config_loader.py:130` | config key |
| `src/api/schemas/settings/responses.py:53-54` | `PromptsConfig` — `system_prompt: str` / `slide_editing_instructions: str`, required and non-`Optional`, `from_attributes=True` (`:47`). Unpopulatable once the ORM attributes go, but **dead code**: its only referrer is `ProfileDetail` (`:59`, field at `:74`), which no route declares as a `response_model`. Update or delete it; nothing breaks at runtime either way (see below) |
| `src/core/settings_db.py:386-387` | reads both ORM attributes into the `AppSettings` payload |
| `src/services/config_service.py:69-75` | **assigns both columns** — the concrete write behind `PUT /agent-config` |
| `src/api/schemas/settings/requests.py:35-36`, `:133-134` | request models (`PromptsCreateInline`, `PromptsConfigUpdate`), including a `field_validator` on `system_prompt` (`:136-141`) |
| `src/core/defaults.py:41`, `:150` | `DEFAULT_CONFIG["prompts"]` carries both default bodies |
| `src/services/validator.py:39` | `validate_prompts(system_prompt=…)` |
| `src/services/agent.py:250-252,617,624-625` | dies with the monolith |
| `frontend/src/types/agentConfig.ts:82-83,135-136` | typed and defaulted |
| `frontend/src/contexts/AgentConfigContext.tsx:124-125,1137-1138` | read for a "has custom config" check (**two** call sites, not one) |
| `PUT /agent-config`, `POST /profiles` | write paths |

All of these change together, and the physical columns are dropped via a `_migrate_*`
helper wired into `_run_migrations()` (this repo has no Alembic — see
`migrations-run-at-startup`).

**Ordering constraint — there are seven insert sites, not one. Corrected 2026-08-20; an
earlier draft said five and missed the two that are not application code.** Every
`ConfigPrompts(...)` constructor that passes these columns must stop doing so *before* the
drop migration runs, or profile creation raises after the drop. Measured — the full set in
the working tree (excluding `tests/`, `build/lib/` and worktrees) is
`init_default_profile.py:408`, `profile_service.py:204`, `:409`, `:490`,
`scripts/init_database.py:218`, `scripts/run_e2e_local.sh:160` and
`.github/workflows/test.yml:589`. Three are easy to miss and one of them is CI:

- `profile_service.clone_profile` (`:490`) copies both values from the source profile;
- `scripts/init_database.py` (`:218`) is a separate entry point from the app boot chain;
- **`scripts/run_e2e_local.sh:160` and `.github/workflows/test.yml:589` are inline Python,
  not importable modules**, so no grep of `src/` finds them and no type checker or import
  analysis will either. The `test.yml` one is the `e2e-tests` job's *"Seed database with
  default data"* step, which every matrix entry runs, so a drop that lands without editing it
  fails **all 23 matrix jobs at seeding**, before a single spec executes. §C already has PR3
  editing that same file for the matrix allowlist, so it is open anyway — edit both in the
  same pass.

Four `ConfigPrompts(...)` constructors also exist under `tests/`
(`tests/unit/config/test_models.py:87`, `:137`, `tests/unit/test_settings_db.py:69`,
`tests/unit/test_unset_agent_config_is_sql_null.py:126`). Those fail as *test* failures
rather than as a broken product, but under §0's cause-based baseline they must be repointed,
not left red.

**And two *read* sites that fail independently of insert ordering.**
`src/core/settings_db.py:386-387` reads both ORM attributes into the `AppSettings` payload
and `src/services/config_service.py:69-75` assigns both columns behind `PUT /agent-config`;
both must change in the same PR as the drop, not merely before the migration.

**`responses.py:53-54` is NOT one of them — corrected 2026-08-20 (a round-2 error).** A
previous round elevated it to a hard same-PR requirement on the grounds that "every `GET`
that serialises a `ConfigPrompts` row raises a `ValidationError`". No `GET` does.
`PromptsConfig` (`src/api/schemas/settings/responses.py:44`) is referenced only by
`ProfileDetail` (`:59`, field at `:74`), and `ProfileDetail` is **dead code**: no route in
`profiles.py` or `settings/*` declares it as a `response_model`, and the only other mentions
anywhere in `src/` are the two lines of the `schemas/settings/__init__.py` re-export
(measured: three hits total for `ProfileDetail` across `src/`). It still carries two
`str`-typed, non-`Optional`, `from_attributes=True` fields that become unpopulatable, so it
is on the change list — but as **dead schema to update or delete**, not as a live response
that breaks.

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
populated. The drawer's callbacks are wired to `console.info` against test-injected
findings (`frontend/src/components/Layout/AppLayout.tsx:762, 988-990` — `testFindings` is an
AppLayout state variable filled from `window.__TELLR_TEST_FINDINGS__`; production renders an
empty list), so nothing real consumes it yet.

### F1. The backend reviewer schema is canonical

The reviewer's Pydantic schema is the source of truth and is mirrored into `finding.ts`.
Backend owns it because the schema is versioned *with* the review skill (§5.1) and because
PRD §7.1 wants verdicts queryable as MLflow assessments — which needs the criteria list and
its schema versioned as one identifiable artifact. `finding.ts` is currently fixture-wired, so changing it is
**cheap but not free** (corrected 2026-08-19): besides `FeedbackDrawer.tsx` and
`SlideViewer.tsx`, the type also governs `frontend/tests/fixtures/findings.ts` — where
`id`/`slideIndex` *are* populated — and about ten assertions in
`frontend/tests/e2e/slide-viewer.spec.ts:314-359` keyed on the ids `f1`/`f2`
(`finding-f1`, `finding-dismiss-f1`, `finding-apply-f2`, …). Renaming `message` to
`description` or re-keying the ids means editing the fixture and those assertions in the
same PR. Note that spec is not in the CI matrix (§C), so nothing would have caught it.

A conformance test asserts a real reviewer payload deserialises into `SlideFinding` with no
loss. The reviewer emits a stable per-finding `id` (so drawer callbacks have something to
key on) and `slide_index`.

**Three fields the mapping must also settle.** Two were added on 2026-08-20; the third
field below, and the correction to the `seen` bullet, were added by the review round after it.

- **`seen: boolean` is `SlideFinding`'s fifth field**, commented *"initial value only;
  lifecycle owned client-side"* (`frontend/src/types/finding.ts`), with the lifecycle in
  `frontend/src/components/SlideViewer/seenState.ts`. The reviewer schema must supply an
  initial value (or the mapping must default it).

  **The hazard an earlier round named here does not exist, and the real constraint is a
  different one.** That round claimed *"a backend that re-sends `seen` on every poll would
  reset the user's read state. This is the one field where backend-is-canonical does not hold
  end-to-end."* Measured: **the payload's `seen` field is never read by the viewer.**
  `SlideViewer.tsx:95` and `:153` both initialise seen-state from `loadSeen(deckKey)`
  (localStorage), `:203` computes the unseen set as `!seen.has(f.id)` and `:525` computes
  `hasUnseen` the same way. The only place `seen:` is populated at all is
  `frontend/tests/fixtures/findings.ts`. A backend re-sending it would be ignored, so it
  cannot reset anything, and §F1's backend-is-canonical rule holds with no exception.

  **What the mapping actually has to settle is `id` stability**, because seen-state is
  persisted in `localStorage` keyed by `(deckKey, finding.id)`
  (`SEEN_STORAGE_KEY = 'tellr-viewer-seen-findings'`, store shape `deckKey -> finding ids`,
  `seenState.ts`). Two consequences pull against each other and the reviewer schema must
  choose: ids that are **not** stable across re-reviews make every carried-over finding
  re-highlight as unseen on every turn (the review-fatigue failure PRD §14 names), while ids
  that **are** stable make a finding legitimately re-raised after an edit read as
  already-seen. §F1 currently justifies the stable id only as something "drawer callbacks
  have … to key on" — that is the smaller of its two jobs. Recorded in §K as unsettled: a
  content-derived id, a `(criterion, slide content hash)` composite, or an explicit
  re-raise counter that changes the id are all admissible; picking one is a §F1 decision.
- **A findings state field — `SlideFinding` has no way to express §F2's "already fixed".**
  The type has exactly five fields (`id`, `slideIndex`, `category`, `message`, `seen`) and
  none distinguishes an *actionable* finding from a *resolved* one, while
  `frontend/src/components/SlideViewer/FeedbackDrawer.tsx:128-160` renders **Apply / Dismiss /
  Discuss on every finding unconditionally** — asserted as current behaviour at
  `frontend/tests/e2e/slide-viewer.spec.ts:353-360`. §F2 requires auto-fixed findings to
  render as a read-only "we fixed this" list, so §F2 is **unimplementable against §F1 as
  drawn**: an executor who mirrors the reviewer schema into `finding.ts` to the letter, then
  turns to §F2, has no field to branch on and no drawer branch to render.

  Two things must therefore land together with the schema: (a) a state field
  (`status: 'open' | 'fixed'`, or equivalent — note `auto_fixable` in the plan's schema is a
  **predicate**, "could a fixer handle this", not a **state**, "a fixer did", so it does not
  cover this); and (b) the drawer branch that suppresses the three action buttons for the
  fixed state. And it settles the `hasUnseen` interaction, which is a third question the two
  answers do not decide on their own: **a fixed finding must not count toward `hasUnseen`**
  (`SlideViewer.tsx:525`), or the unseen badge nags the user about work already done — the
  exact review-fatigue symptom §F2's read-only presentation exists to avoid.
- **`category` is a closed union**, `'content' | 'design' | 'narrative'`, consumed by an
  **exhaustive** `CATEGORY_LABEL: Record<SlideFinding['category'], string>`
  (`frontend/src/components/SlideViewer/FeedbackDrawer.tsx:13`). A `Record` keyed on the union
  fails to **compile** the moment a fourth value appears. So §A2's initial criteria —
  overflow, contrast failure, rogue colour outside the contract, stretched/distorted image,
  source-contradicting figure — must map into those three values, or the union and the
  `Record` widen in the same PR. That is a compile-time constraint on the reviewer schema, not
  a presentation preference.

Fixture detail for the re-key above: the export is **`mockFindings`**
(`frontend/tests/fixtures/findings.ts`) and it carries **three** findings — `f1`/`f2` on
`slideIndex: 1` and **`f3` on `slideIndex: 3`** — so a rename or re-key touches three ids,
not the two the e2e assertions name.

### F2. Auto-fixed findings surface, marked as already fixed

The drawer shows subjective findings as **actionable**, plus objective auto-fixed findings
as a **read-only "we fixed this"** list.

This reconciles two requirements that otherwise conflict: §7.4 says objective defects are
fixed before the user sees the slide, and PRD §3 requires that "what was fixed is visible."
Read-only presentation satisfies the second without asking the user to act on resolved
items, and keeps the actionable surface small enough to respect PRD §14's review-fatigue
risk.

**This section has two hard dependencies on §F1, and §F1 must carry them — added 2026-08-20.**
"Read-only" is not a presentation choice the frontend can make on its own: `SlideFinding` has
no field that distinguishes actionable from resolved, and `FeedbackDrawer.tsx:128-160` renders
Apply / Dismiss / Discuss on **every** finding unconditionally (current behaviour asserted at
`frontend/tests/e2e/slide-viewer.spec.ts:353-360`). So §F2 requires (a) a **state** field on
the reviewer schema and its `finding.ts` mirror, and (b) a drawer branch keyed on it, plus the
`hasUnseen` rule that a fixed finding does not count as unseen. All three are now listed
in §F1's "Three fields the mapping must also settle" — implement §F1 without them and §F2
becomes unbuildable.

### F3. Findings live in `verification_record`

PRD §12.1 left open whether drawer findings and reviewer verdicts share one record. They
share it. `session_slides.verification_record` is hash-keyed, **merged never overwritten**,
travels with its slide on reorder, and is re-materialised by `restore_version` — all built
and tested in PR1. A parallel store would re-solve reorder-safety, edit-then-revert recall
and save-point restore, each of which PR1 already got right once (and one of which shipped
as a defect during 0a before being caught).

Note the non-obvious property to preserve: **a record belongs to a slide, not a position.**

**§F3 answers the slide-level half only — added 2026-08-20.** PRD §3
(`2026-07-30-tellr-agentic-rebuild-prd-design.md:123-124`) routes findings by grain:
"Subjective findings surface in the right channel (**deck-level → chat**, slide-level →
drawer)." `deck_reviewer` is one of the seven skills, and spec §5.2.7 says its findings
"route to the main chat (deck-level) per PRD §6.3". `verification_record` cannot hold them:
it is a **per-row** column (`src/database/models/session.py:412`) keyed by slide content
hash, and a deck-level verdict has no slide content hash to key on — which is §F3's own
closing property read the other way. So PRD §12.1 is answered for slide-level findings, and the
deck-level half needs its own home. **Resolved 2026-08-24 — see §F4.**

### F4. Deck-level reviews get their own content-addressed table

**Decided 2026-08-24.** Deck-level verdicts live in a new **`deck_reviews`** table, joined on
**`(deck_id, deck_digest)`** — a content key, not a validity window and not a sequence number.

| Column | Meaning |
|---|---|
| `deck_id` | FK to `session_slide_decks.id` — the deck, not the session, so contributor sessions all resolve to one review history (they already share the deck-owner row) |
| `deck_digest` | hash over the **ordered** per-slide content hashes; the deck-level analogue of `verification_record`'s per-slide key |
| verdict payload | the deck reviewer's findings, same schema shape as §F1 |
| `created_at` | ordering only — not identity |

**Why content-addressed rather than SCD2.** An SCD2 pair (`valid_from`/`valid_to`) records
*when* a review was current. What every consumer actually needs is *which deck state it
judged* — and those come apart the moment a user edits and reverts. A content key answers the
real question, and gives deck reviews the same property `verification_record` already has for
slides: **edit-then-revert finds the earlier verdict again** (PRD §12.1's "finding
persistence"). Reuse `compute_slide_hash` (`src/utils/slide_hash.py:52`, already the
per-slide key) over the rows in position order; there is no deck-level hash helper yet, so
PR3 adds one.

**Three consequences, all of them simplifications:**

1. **Restore needs no handling at all.** There is no "current" row to go stale. A save-point
   restore returns the deck to a prior state, its digest reverts with it, and the join finds
   the review made against that state if one exists. Contrast `deck_spec_json`, which *did*
   need a snapshot-and-copy-back (`create_version` at `session_manager.py:1939-1951`,
   restored at `:2240`) precisely because it is keyed by deck rather than by content. **No new
   snapshot column and no restore step.**
2. **It cannot be broken by the save-point cap.** `VERSION_LIMIT = 40`
   (`session_manager.py:1859`) deletes the oldest version once exceeded. Anything FK'd to
   `slide_deck_versions` would either orphan on that prune or cascade and destroy the review
   history the table exists to keep. `deck_reviews` references only the deck, so pruning save
   points cannot touch it.
3. **Reorder correctly invalidates.** Reordering changes the ordered digest even though no
   slide's HTML changed — which is right, because a deck review judges the narrative arc and
   the arc is exactly what a reorder changes. Note this is the **opposite** of the per-slide
   rule, where a record deliberately travels with its slide across a reorder (§F3). Both are
   correct: a slide verdict is about a slide, a deck verdict is about an ordering.

**The digest is computed, not stored.** Deriving it on read from the `session_slides` rows
avoids a denormalised column that could drift from the rows it summarises. The read path
already loads every row (`get_slide_deck`), so there is no extra query.

**This also dissolves the trade-off the two earlier candidates forced.** Riding the chat
transcript would have left the verdict with no queryable identity (against PRD §7.1's
MLflow-assessment goal); a column on the deck would have been queryable but needed
save-point handling. A content-addressed table is queryable **and** needs no restore
handling, and it is orthogonal to *surfacing*: the verdict is stored here and still surfaces
in chat per spec §5.2.7 and PRD §3's grain routing. Storage and channel were never the same
question.

**PR3 owes:** the table, a `_migrate_*` step for it — **pre-fork, in the chain reached from
`run.py::init_database`** per §L8, and sequenced in the same `_run_migrations()` list as
§E2's drop and §B2's dirty marker (three schema changes that should be planned together
rather than as three separate migrations) — the deck-digest helper, and the read-side join.

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

As drawn, **every graph-built deck would knit with no `<style>` element at all** — an
unstyled deck. Review finding F9, unresolved until now. (Wording corrected 2026-08-20: an
earlier draft said "an empty `<style>` block". `knit()` guards the block with `if self.css:`
(`src/domain/slide_deck.py:370`), so an empty `css` emits *nothing*, not an empty element.
Substance unaffected.)

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

#### H1b. The write must enumerate eight deck-level columns, not two

**Added 2026-08-19.** The row-read path reconstructs the deck from deck-level columns, not
from `deck_json` (the `deck_dict` literal is `session_manager.py:1538-1564`), so a column
the graph never writes is a column the deck never has. `save_slide_deck`'s own comment (`:1360-1365`) names the cost:
*"Missing css/external_scripts costs every export its stylesheet and the Chart.js CDN;
missing head_meta reverts a custom viewport to `SlideDeck.knit()`'s hardcoded default (F5)."*

| Column | If the graph never writes it | Self-heals? |
|---|---|---|
| `css` | unstyled deck — the §H defect | no |
| `title` | untitled deck and untitled session row | no |
| `external_scripts_json` | Chart.js CDN missing from every export | **no** — see the correction below |
| `head_meta_json` | custom viewport and every other `<meta>` silently reverts | no |
| `scripts_content` | deck-level JS lost from the row-read path | no |
| `slide_count` | **the session list renders `0 slides`** for every graph-built deck (`src/api/routes/sessions.py:233`, `session_manager.py:836` — it is a *column*, not derived; only `get_slide_deck`'s own dict derives it from `len(slides_list)`) | no |
| `html_content` | raw-HTML debug view empty; `save_slide_deck` treats it as required | no |
| `deck_spec_json` | **the deck spec is never persisted** — spec §7.1's "view spec" toggle has no data, and turn *n+1*'s architect starts blind | no |

`slide_count` and `html_content` are only knowable **after** the fan-out, so they belong to
§L2's second (post-commit) write, not the pre-fan-out one. `css`, `title`,
`external_scripts_json`, `head_meta_json`, `scripts_content` and `deck_spec_json` are
decidable up front. The two writes together must cover **all eight**; neither alone does —
**6 decidable up front, 2 post-fan-out, and nothing self-heals.**

**`external_scripts_json` does NOT self-heal — corrected 2026-08-20, and this was the one
entry an executor could have skipped in good faith.** An earlier draft of this table marked
it "self-healing" on the strength of `SlideDeck._ensure_default_external_scripts`
(`src/domain/slide_deck.py:74`). That helper runs only inside `SlideDeck.__init__`, `knit()`
(`:329`) and `render_slide()` (`:416`) — i.e. only when somebody builds a **domain object**.
Nothing on the export or preview path does. `chat_service.get_slide_deck_dict`
(`chat_service.py:2661`) returns the raw dict, `src/api/routes/export.py:84` reads
`slide_deck.get("external_scripts", [])` off that dict and `:148` builds the `<script src>`
tags straight from it; the five frontend consumers
(`PresentationMode.tsx:140`, `ThumbnailRibbon.tsx:185`, `SlideViewer.tsx:520`,
`VisualEditorPanel.tsx:42`, `SlideTile.tsx:144`) likewise read `slideDeck.external_scripts`.
The row-read path emits `json.loads(deck.external_scripts_json or "[]")`
(`session_manager.py:1541`), so an unwritten column is `[]` at every one of those sites. The
model's own comment states the consequence (`src/database/models/session.py:283-287`):
*"If the row path returns [] instead, EVERY export silently loses Chart.js and all charts
render blank — the PRD §3 no-regression gate, failing invisibly."*
So the graph must write this column like the other seven, and the failure if it does not is
**silent**: no exception, no empty-`<style>` symptom, just blank charts.

**`deck_spec_json` added 2026-08-20 — it is the column PR3 exists to write, and it was
missing from this enumeration.** It is also the only deck-level column with a *reader* gap
as well as a writer gap. Today it has exactly two touchers in `session_manager.py`: the
`create_version` snapshot (`:1939-1951`) and the `restore_version` copy-back (`:2240`).
**Nothing serves it to a caller** — the row-read `deck_dict` (`:1538-1564`) emits title,
slide_count, css, external_scripts, head_meta, scripts, slides, authorship, version and
html_content, and no deck spec. So the deck-level accessor §J assigns to PR3 is a **read and
a write**, not just a write; without the read, spec §7.1's "view spec" toggle has no data
path at all. It belongs to the **pre-fan-out** write, because §H1's trigger *is* "the
architect commits the deck spec".

**There is a third toucher this enumeration also missed, and it is a *dropper*, not a
writer: `duplicate_session`.** See §B5 — a duplicated deck loses its spec permanently,
because the column is a sibling of `deck_json` rather than a key inside it.

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
| kickoff brief | 19 pre-existing failures in four files | **3 failures / 2 causes / 2 files** — §0's current baseline. (Row corrected 2026-08-20: it previously said "17 in three files, post-upgrade", which was both stale and miscounted. The intermediate post-upgrade figure was 17 across **four** files — 14 `svgpathtools` in `test_html_to_pptx.py` + `test_google_slides_converter.py`, 2 deploy-autoscaling, 1 genie — and §0 has since retracted the `svgpathtools` and mlflow causes as a local-environment defect, not a repo baseline.) |
| spec §4.1 | design contract = "the CSS/style contract **+ image guidelines**" | a design system compiles to a **prompt artifact**, not a stylesheet; the spec stores a reference (§L1, §L3). The image-guidelines half is reached through the *same* reference — it is a `slide_style_library` column, resolved only on the legacy branch (§L3) |
| spec §5.2.3 | builders receive "the style sheet (the CSS contract)" | they receive the resolved `compiled_style_content` **or** `style_content` — a branch, not a ladder — already carrying the frame rules (§L1, §L5) |
| spec §5.2.8 | the foreman is sole CSS writer | a second, **measured** deck-CSS write is now required post-commit (`ensure_deck_token_css`), or pinned-template decks ship washed out (§L2) |
| spec §4.6 | design-contract change = `slide_style_id` | three fields plus template pinning; setting a design system clears the style (§L4) |
| plan Phase 9.2 | delete or reduce `agent_factory` | it now owns design-system resolution, template blocks and `search_brand_assets` gating — move, do not delete (§L6) |
| spec §6.4 | "`create_deck` / `edit_deck` contracts are unchanged, so the TAP builder, DAIS agenda curator and KPMG pricing skills need no coordinated change" | true of the tool *signatures*, not of what is behind them: `_edit_deck_impl` targets `agent.py`'s `_format_slide_context` shape (deleted by §D), `get_deck_status` has no field that exposes §I's placeholders, and §F routes findings only to browser surfaces (§D2) |
| spec §5.2.1 | tool manifest comes from `AgentConfig.tools` | it must also carry the design-system library, or the architect cannot offer a brand it cannot see (§M1) |
| spec §4.1 slide level | `SlideSpec` fields are **position** / purpose / brief / assumes / hands-off / data refs | plus a **template section assignment** (§M3) |
| `design-system-library.md` §9 | a first-request template pin is stripped | **no change** — the strip is correct and stays. An earlier revision of this document promised a graph-path fix; withdrawn, because the strip runs before any agent exists and §M1 covers the user story a turn later (§M2) |
| current pinned-template prompt block | injects the whole layout for the whole deck | per-slide **section extraction**; the layout never goes to a builder whole (§M3–§M5) |
| `migrations-run-at-startup` memory | backfills go in the FastAPI lifespan | superseded — they run **once pre-fork** in `run.py::init_database` and `SystemExit(1)` on failure (§L8). §E2 is corrected in place; the still-stale *source* docstrings are named in §L8 |
| PRD §12.1 | leaves open "whether drawer findings and reviewer verdicts share one record" | slide-level: yes, `verification_record` (§F3). Deck-level: **a separate content-addressed `deck_reviews` table** keyed `(deck_id, deck_digest)` — a per-row hash-keyed column cannot hold a verdict about an *ordering* (§F4) |
| PRD §14 (big-bang-release mitigation) | "Workstreams merge continuously **behind flags**; **dogfood the integration branch** internally well before release" (`2026-07-30-tellr-agentic-rebuild-prd-design.md:693`) | **both named mitigations are dropped** (§D). The flag is removed entirely and there is no dogfooding period with both engines live. Deliberate: a `false`-default flag would select a path plan Phase 9.2 deletes, so the flag cannot exist in the form PRD §14 assumes. Substituted mitigations: the four-layer test suite with a real-LLM agentic layer (§G) and a `deploy-tellr-dev` devloop deploy as the pre-merge gate (§D). The residual risk — no both-engines-live comparison, and the graph must be correct at merge — is **accepted**; recorded here because §J documents every other divergence |
| PRD §14 (review-fatigue mitigation) | "Objective defects are fixed silently, **not reported**" (`2026-07-30-tellr-agentic-rebuild-prd-design.md:695`) | auto-fixed findings **are** reported, as a read-only "we fixed this" list in the drawer (§F2). Deliberate: PRD §3 (`:120-122`) requires "what was fixed is visible", and PRD §7.3 (`:379-380`) already says "the *list of what was auto-fixed* is shown in chat for transparency, along with the iteration count" — so the PRD contradicts itself and §F2 picks the visible branch. §F2 also moves that list from **chat** to the **drawer**, read-only; §14's fatigue concern is answered by read-only presentation rather than by silence |

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

Resolved on 2026-08-24 and moved out of this list: where deck-level reviewer findings live
(now §F4 — a content-addressed `deck_reviews` table) and whether `tour.py` fires the §4.4
trigger (it does not; the arc ships inside the fixture — §B1).

Two items that stood here were later resolved by §M below, and are listed so the change of
status is visible rather than silently dropped:

- ~~How the architect converses about brand~~ → **resolved in §M1.** (§M2's first-turn-pinning
  half was withdrawn as a non-issue — see §M2.)
- ~~Whether design-system templates inform the deck spec's slide briefs~~ → **resolved in
  §M3–§M5.**

Still open, and deliberately so:

- **The three probes §M7 names.** They size the extraction implementation; none changes the
  design.
- **Which deterministic CSS the pre-fan-out write persists**, if any (§L2a). The candidate is
  the pinned template's `token_css` plus its own `<style>` block; this document does not yet
  take that decision.
- **How `merge_css` is extended to survive at-rules** (§L2a) — carry at-rules through, or
  dedupe by exact block text. Either is small; both need an at-rule survival test.
- **The tone-vs-BRAND-MANUAL precedence rule** (§E1). The collision is named; which artifact
  wins is not settled.
- **The dirty marker's storage** (§B2). §B2 says it "lives in the database" and wants a
  `claimed_at` lease, but no table, column or `_migrate_*` step is nominated, and none of
  §H1b's or §E2's schema work covers it.
- **What identity a sweeper-driven arc review runs as** (§B2). `get_current_user()` is `None`
  outside a request and `get_user_client()` fails closed in production, so `modified_by`,
  deck permission checks and usage attribution have no source. Not decided.
- **How reviewer finding `id`s behave across re-reviews** (§F1). Seen-state is persisted in
  `localStorage` keyed by `(deckKey, finding.id)`, so stability across turns and
  re-raise-after-edit pull in opposite directions. The schema must pick; §F1 only requires the
  id be stable *enough to key callbacks on*.

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

- **The two are mutually exclusive at every PERSISTENCE boundary**, enforced in three
  independent places — the `AgentConfig` model *serializer*
  (`_one_style_authority`, `src/api/schemas/agent_config.py:128-129`), the column bind
  (`NormalizedAgentConfig`, now the type of `UserSession.agent_config`), and a database
  `BEFORE INSERT OR UPDATE` trigger. **No stored row can carry both.**

  **But an in-memory `AgentConfig` deliberately CAN — corrected 2026-08-20.** An earlier
  draft said "a caller cannot construct a deck carrying both", which reads as an
  object-construction guarantee and is the opposite of what the code documents. All three
  enforcement points above are *persistence* boundaries; the first is a `@model_serializer`,
  not a validator, and its docstring says why (`:157-165`):

  > *Normalization stays at SERIALIZATION rather than moving to a model validator,
  > **deliberately**. `put_agent_config` must validate DB references BEFORE making the
  > sources exclusive, because a DANGLING design system can only be detected with a lookup;
  > if the object could not hold both transiently, a user holding a dead pin AND a real slide
  > style would be left with NEITHER.*

  This matters for the next bullet, not just for accuracy: `_get_prompt_content(config:
  AgentConfig)` (`agent_factory.py:78-80`) branches on the **in-memory object**
  (`if config.design_system_id is not None:` at `:139`), so the both-set state is reachable at
  exactly the site the branch is read. The outcome is unchanged — the design system wins
  either way — but "both can be set here" is the reason the `elif` deserves a sentence at all.
- **An inactive `design_system_id` does not fall through to the style.** The branch is
  chosen on the id being *present*, so a soft-deleted design system logs a warning and
  leaves generation on the `DEFAULT_SLIDE_STYLE` constant. The `elif` (`:204`) is never
  evaluated once `design_system_id` is set — which is a real statement precisely because a
  transiently both-set config can reach it.
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
(`session_manager.py:2229-2253` — `css` at `:2246`, `scripts_content` at `:2250`,
`head_meta_json` at `:2253`; the range was cited as `2229-2246` and cut the last two off)
without it either. The backstop is a *generation-path*
guarantee, not a save-path invariant — which makes the conclusion below stronger, not weaker,
because the graph path replaces exactly the two flows that have it.

**Both call sites are in the flows PR3 deletes.** PR3's reviewers write *rows* via
`SlideWriter`, which is not a deck save, so on the graph path the backstop never fires and a
pinned-template deck ships washed out in preview and both exports.

**Resolution — two deck-level writes per turn:**

| When | Writes | Why there |
|---|---|---|
| Before the fan-out | title, `external_scripts_json`, `head_meta_json`, `scripts_content`, `deck_spec_json`, and whatever deterministic CSS exists up front (§L2a) | so incrementally-released slides render styled (§6.2's payoff); the spec is exactly what the architect just committed (§H1b). `external_scripts_json` added 2026-08-20 — §H1b previously marked it self-healing, which it is not, so it needs an explicit write and belongs here (the Chart.js default is known before any builder runs) |
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

- **`deck.css` is populated today by exactly two mechanisms, both monolith-path** —
  premise corrected 2026-08-20. (1) **`SlideDeck.from_html_string`**
  (`src/domain/slide_deck.py:162`) walks `soup.find_all('style')` and joins the blocks
  (`:193-198`); `from_html` (`:142`) reaches it only by delegating at `:159`, so the walk is
  not in `from_html` itself. (2) **`SlideDeck.update_css`**
  (`src/domain/slide_deck.py:97`) does `self.css = merge_css(self.css, replacement_css)`
  (`:108`), called live from `src/api/services/chat_service.py:2631` on the
  slide-replacement edit path — its only caller in `src/`. The graph calls neither:
  `SlideWriter` writes per-row `html` only.
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

**This is a shipped defect on the edit path today, not only a hazard for a new step — added
2026-08-20.** Because `update_css` is already a live `deck.css` populator (above), every
slide-replacement edit already runs the whole deck stylesheet through `merge_css` and
already drops its `@media` and `@keyframes` blocks (and `@font-face`, until
`ensure_deck_token_css` re-emits it). The at-rule loss is therefore reachable on the current
monolith edit path, not confined to PR3's hypothetical aggregation step. Two consequences:

- **Priority.** Fixing `merge_css` is a bug fix with a user-visible symptom — a branded deck
  loses its print rules and animations after one slide edit — not speculative hardening for
  code PR3 has not written yet. It stands on its own even if PR3's aggregation choice moves.
- **Regression test.** The at-rule survival test must cover the **existing** path
  (`SlideDeck.update_css` on a sheet carrying `@font-face`, `@media print` and
  `@keyframes`) as well as PR3's aggregation. A test written only against the new aggregator
  ships green over the live defect.

**So the aggregation step is PR3 work with one open choice:** extend `merge_css` to carry
at-rules through, or dedupe by exact block text rather than by selector. Either is small and
testable; both need an at-rule survival test. Do **not** adopt `merge_css` as-is.

### L3. The deck spec's `design_contract` holds a reference, not content

§4.1 lists "design contract: the CSS/style contract" as a deck-level spec field. It stores
**which brand**, not the compiled text:

```
design_contract: { design_system_id, template_id, slide_style_id }
```

**§4.1's second half — "+ image guidelines" — rides the same reference, added 2026-08-20.**
It is not a separate stored field and it is not dropped: `image_guidelines` is a column on
`slide_style_library` (`src/database/models/slide_style_library.py:35`), resolved **only on
the legacy slide-style branch** (`agent_factory.py:217`). The design-system branch leaves it
at the function's **untouched initializer** — `image_guidelines: Optional[str] = None` at
`agent_factory.py:123` — so a design-system deck has no image guidelines at all.
(Mechanism corrected 2026-08-20: an earlier draft cited `:310`. That line is
`"image_guidelines": None` inside the **pre-assembled return dict**, which nulls the key on
*both* branches because the resolved value has already been baked into the assembled prompt at
`:300`. It is not what makes the design-system branch empty.) `slide_style_id` *is* the
image-guidelines reference; nothing further needs storing in the spec.

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

**Inject the constant, never a retyped copy of the numbers — added 2026-08-20.**
`_SLIDE_FRAME_CONSTRAINTS` is module-private (`design_system_compiler.py:545`) and is emitted
into `compiled_style_content` at `:2535`, where `COMPILER_VERSION = 20` (`:281`) governs
currency by **exact match** (`:317`). Prompt assembly must **import that same constant** —
promoting it out of `_`-private, or exposing an accessor — so both sites read one set of bytes
at request time. Restating the numbers in assembly code instead would create exactly the
divergence class the currency contract exists to prevent. Importing does not: the injected
value is never persisted, so it cannot go stale against `COMPILER_VERSION` the way a compiled
artifact row can.

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
  (`agent_factory.py:359-360`, inside `_build_tools`' docstring) which an earlier draft of
  this section repeated. The code is
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

`SlideDeck` parsing no longer looks for `div.slide`. `from_html_string`
(`src/domain/slide_deck.py:162`) calls `find_slide_roots(soup)` at `:206`
(`src/utils/html_utils.py:46`): the outermost element carrying the
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
  visible while editing. Removes the now-unused height reporter + grow machinery."* At
  conflict-resolution time that commit was on main and **not yet** on this branch, so our side
  merely predated the removal — it was never a ws6 feature and never a design disagreement.
  (Tense corrected 2026-08-20: post-merge, `48fe0fa1` **is** an ancestor of `HEAD` as well as
  `origin/main`, via the merge at `b54c5cc4`. The resolution stands; only the sentence was
  stale.)
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

### M2. First-turn template pinning — withdrawn as a non-issue

**This section previously instructed PR3 to "fix first-turn pinning on the graph path".
Withdrawn 2026-08-24; it asked for work that has nowhere to happen and no longer needs
doing.** Kept as a record so the question is not re-opened from the parent doc's limitation
list.

**The limitation is real.** A template pin submitted on the request that *creates* a session
is dropped by `_without_template_pin` (`src/api/routes/chat.py:240`, applied at `:279` and
`:295`). Its docstring gives the reason: a pin arriving at session-creation "can only be
another surface's in-memory carryover (the new-session race)" — a `localStorage` pin from a
different deck riding along on the new session's request. `design-system-library.md` §9
documents the workaround as "send your first message, then pin".

**Why "fix it on the graph path" cannot be executed.** The strip runs *inside*
`_maybe_create_session`, which the route awaits at `chat.py:339` / `:443` / `:602` — strictly
**before** `chat_service.send_message_streaming` (`:480`) and before `enqueue_job` (`:641`).
So no agent or graph exists yet at the moment the pin is discarded. There is no
architect-derived pin to preserve at that point; the only thing present is a `template_id` in
the inbound `agent_config` blob, which is exactly the carry-over case the strip exists to
reject. A fix would therefore have to change the **browser** path — the one this section
promised to leave unchanged — and would reopen the race.

**And the user story is already served, by §M1.** "Build me an Acme-branded deck" resolves in
the ordinary sequence: the session is created (any stale pin correctly stripped), the
architect then runs, reads the brand intent, and sets `design_system_id`/`template_id` on an
**existing** session — the path that already works. The cost is one turn, and §M1 requires a
confirmation before restyling anyway, so that turn was always going to happen.

**The precedent §M2 wanted to establish already exists.** MCP `create_deck` resolves
`template_name` into `agent_config["template_id"]` **on the session-creating request** and it
is *not* stripped, because `_without_template_pin` is local to `chat.py`
(`src/api/mcp_server.py:480-483`; `design-system-library.md` §4.6, `:148-151`). A non-browser
caller pinning on first request is therefore established behaviour, not a new exception.

**Net effect on PR3: no work.** The pre-session browser behaviour is unchanged and deliberate;
first-turn brand intent is §M1's job. If a future change genuinely needs a first-request pin
honoured from the browser, it needs a way to distinguish "the user just chose this" from
carry-over — a marker on the request, not a graph-path condition — and that is a separate
design question outside PR3.

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

**Extraction must resolve the template through the materialize/self-heal path first — there
is no "normalizing accessor" to read through.** Corrected 2026-08-20: an earlier draft named
one. `normalize_root_tag_selectors` (`src/services/design_system_templates.py:527`) is a
**plain function**, and its two callers **persist** its output — `materialize_templates`
(`:682`) self-heals existing rows by assigning `template.layout_html = normalized` (`:703`),
and normalizes freshly derived rows on the way in (`:773`). It is what makes a template's
*tag-keyed* CSS (`section { … }`) also match the `div.slide` roots generation emits. So the
instruction is not "call an accessor"; it is **resolve the template via
`get_template_for_generation` (`:849`, which calls `materialize_templates` at `:859`) and only
then read `template.layout_html`** — by that point the bytes are already normalized.
Extracting from a row that has not been through that pass yields a section whose CSS
selectors match nothing in the built slide — a silent, whole-section styling loss. The pass is
idempotent, so routing through it costs nothing on an already-healed row.

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
(`design_system_templates.py:60`), and the architect holds the only durable conversation in
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

All three are empirical, not design questions:

1. **Does an extracted section render standalone?** A section may depend on an ancestor's
   styles — including a non-promoting `<main>` or `<div>` wrapper that `find_slide_roots`
   leaves behind (§M3). Render an extracted section against its template's full CSS and
   compare with the same section rendered in situ. If wrappers matter, extraction must carry
   the ancestor chain (or its computed contribution) rather than the bare root.
2. **Is CSS actually small next to markup?** §M5 rejects pruning partly on the grounds that
   "CSS is small next to markup, so pruning buys little", and §M6 credits per-section
   extraction with most of its saving on the same assumption. **Neither is measured** — there
   is no design-system bundle fixture in this repo to measure against. If a template's
   `<style>` block dominates its 24–47 KB, then handing every builder the full stylesheet
   (§M5) gives back most of what §M6 claims to save, and the cost argument needs restating.
   Measure `len(style_block)` against `len(layout_html)` on a real imported bundle. This does
   **not** reopen §M5's decision — under-including CSS is the known washout defect either way
   — it tests the *cost* claim the two sections lean on.
3. **Does the section inventory support good assignment?** Give the architect an inventory
   from a real multi-section bundle and check its assignments are sensible — that a title
   slide gets the title section rather than the data section. If names and snippets prove
   insufficient, the inventory grows (thumbnails already exist per template, though not per
   section).

None blocks the design; all three size the implementation.
