# Handover into ws4e — the final PR of workstream 4

**Written 2026-09-15, on merging ws4d into `feat/langgraph-core`.** For whoever implements
**ws4e** (`2026-08-25-ws4e-surfaces-and-gates.md`), the fifth and last of the five workstreams.

This note is different in kind from `ws4a-HANDOVER.md` through `ws4d-HANDOVER.md`. Each of those
carries one workstream's delta and hands it to the next. **ws4e has no successor**, so every item
still open across ws4a, ws4b, ws4c and ws4d either gets closed here, gets a ticket with an owner, or
gets accepted in writing. Section 4 is the consolidated list, with a disposition against each.

Read it *with* the four per-workstream handovers, not instead of them: this one consolidates and
disposes, they carry the measurements and the reasoning.

---

## 1. Where things stand

- **ws4a, ws4b, ws4c and ws4d are all merged into `feat/langgraph-core`**, each as a `--no-ff` merge
  commit carrying its own Definition-of-Done obligations, because these workstreams land locally
  rather than through five pull requests. ws4d is `f8aafa6b`.
- **Suite at the merge point: `7 failed, 5484 passed, 10 skipped, 1 xfailed`, 5501 collected.** The
  seven are two environmental causes — the standing deploy-autoscaling pair, and five expired-token
  failures in `test_client_integration.py`. Section 4 of `ws4d-HANDOVER.md` §5 enumerates all four
  causes the baseline can present, including two that move between the failed and skipped columns.
- **The graph is reachable from chat and builds decks.** `USE AGENT MODE` in a session's earliest
  user message selects it per deck. The architect converses, the foreman fans builders out in
  parallel, one reviewer runs per slide, and the deck reviewer assesses the arc.
- **The monolith is untouched** and serves every request that does not opt in.
- **What a user cannot yet see is the point of ws4e.** Slides are delivered on both backend
  transports and rendered by neither incrementally; findings reach the database and not the drawer.

---

## 2. Read these first, in this order

1. **`.claude/skills/executing-plans-tellr/`** *and* **`superpowers:subagent-driven-development`** —
   both, per `CLAUDE.md`.
2. **`ws4-START-HERE.md`**, then **`2026-08-25-ws4-index.md`**.
3. **This note**, then **`ws4d-HANDOVER.md`** — especially its §4 (what you own), §4a (route
   renumbering), §5 (the baseline's four causes) and §6 (traps).
4. **`ws4c-HANDOVER.md` §4**, which assigns work to ws4d and ws4e jointly, and its §7 for the
   SQLite-only measurements.
5. **`.ws4d-PLAN-CORRECTIONS.md` — 1069 lines, 32 sections.** Several are contracts you consume:
   **§25** (a `Send` target does **not** appear in the compiled graph's edge list — measured), **§27**
   (two async testing traps you will meet in layer 4), **§31** and **§32** (the two largest fake-guard
   classes found on this branch). **§30 records the controller's own sizing errors** — read it before
   quoting any count from a handover, including this one.
6. **Your plan**, end to end, before writing anything.
7. **Do the corrections pre-pass into `.ws4e-PLAN-CORRECTIONS.md` before Task 1.** ws4a found six
   corrections, ws4b twenty-three, ws4c four blocking plus sixteen anchors, ws4d five blocking plus
   twenty-seven anchors. It has been the highest-yield hour of every build so far, and your plan's own
   DoD requires one of its outputs (the fifteen RC rule meanings).

---

## 3. What ws4e owns

### 3a. Its own six sections

`E1` the spec-view toggle; `E2` wiring the drawer to real findings; `E2b` the "agentic deck review in
progress" flag (§7.4); `E3` `tests/agentic/` as an honest, skipped layer 3; `E4` layer 4, concurrency
and multi-worker; `E5` the retired-regex regression checklist, fifteen RC rules; `E6` the release
gate, seven checks on a devloop deployment.

### 3b. Four things earlier workstreams deliberately left it

- **Frontend rendering of the incremental slide event.** ws4d delivers both backend transports and
  the TypeScript union member; ws4e realises the user-visible feature. Two facts that will bite:
  `handleStreamEvent` already has **seven** case branches, not the two an earlier review claimed, so
  a duplicate `case` is a compile error; and the TypeScript union member is guarded by a test that
  reads `api.ts` as **text**, because types are erased and deleting the member left `npm run
  typecheck` at exit 0.
- **Findings in the drawer.** `findings_from_record` exists, and deck-level findings live in
  `deck_reviews` and reach the user as an `info` chat message. No finding with `slide_index == -1`
  reaches `SlideViewer`.
- **The spec view after `clear_context`.** ws4d built the behaviour; the assertion is ws4e's, and the
  plan's DoD states its exact shape: the spec view still renders data while the transcript is cleared
  **down to the single earliest `role='user'` message**. Asserting an empty transcript is red by
  construction — that row is the sticky engine-mode marker and is preserved deliberately.
- **A measured real-model run gating the selective rebuild** (§4.6). See item 4.3 below; this is the
  one inherited item that can destroy a user's work if it is skipped.

---

## 4. The consolidated open ledger

Every item still open at the end of ws4d, with a disposition. **"Ticket" means it leaves this
programme with an owner and does not block the merge. "Accept" means it is recorded as intended
behaviour and nobody is expected to act.** Items marked **ws4e** are yours.

### 4.1 The one item that spans all four workstreams

**Continuous integration has never executed this branch, and has never completed a run on ws4a, ws4b
or ws4c either.** Every workstream reported this as NOT met. Consequences worth stating plainly:

- **No Definition-of-Done item resting on a CI observation has ever been claimed** by any of the four
  workstreams, and none should be claimed by ws4e either until a run completes.
- The longer the first real run is deferred, the harder attribution gets: it will cover four
  workstreams at once.
- Two known fragilities are waiting there. `test_dependencies_resolve_on_proxy` is `live`-marked and
  performs a **real dependency resolve** against the Databricks proxy, while the `unit-tests` job
  applies **no marker filter** — contrary to what the marker's own documentation promises. It has
  flaked once locally. And `pyproject.toml` declares the `live` marker as "excluded in CI with a
  not-live filter" but sets no `addopts`, so a local full run executes live network tests CI never
  does.
- `integration-graph` has never executed on a runner at all.

**Disposition: ws4e, and it should be the first thing done rather than the last.** A first CI run
before Task 1 turns four workstreams' worth of unclaimed DoD items into either claimed or actionable,
and it is the only item here that gets more expensive with every day it waits.

### 4.2 Correctness and durability

| Item | Detail | Disposition |
|---|---|---|
| **An architect-EMITTED spec is unchecked** | A model echoing back `current_deck_spec` can re-materialise a deleted slide on a build turn. The consumer-side guard covers only the persisted-spec fallback, and route renumbering (§4a of `ws4d-HANDOVER.md`) covers only routes. The exposure predates ws4d — committing a model-emitted spec is ws4c's — but ws4d's selective re-review reads it | **ws4e or ticket.** The cheapest shape is the same set comparison already written, applied to the emitted spec on a build turn where rows exist |
| **No optimistic locking on either deck-level write** | `expected_version` exists on the writer and **neither call site uses it**. Two writers can interleave on the deck-level columns | **ws4e.** Your E4 is concurrency; this is in its path |
| **Postgres lock ordering between the two title writers** | Uncharacterised. Assigned to ws4e by ws4d, and now cheap: the `postgres_engine` fixture exists | **ws4e** |
| **Sweeper throughput** | All four workers pick the same `LIMIT 1` candidate, so real throughput is 1–4 decks per minute rather than 4. `with_for_update(skip_locked=True)` fixes it **and** hedges the EvalPlanQual reliance on the same line | **ws4e.** There is now a Postgres to test it against |
| **The `mark_dirty`-versus-claim race** | Reproduced and banked as `xfail(strict=True)`: `spec_dirty_at` ends behind `spec_dirty_claimed_at` while `spec_dirty_by` carries the second author, so an edit coalesces into an already-claimed window and the finishing review discards an edit it never covered. **Because the xfail is strict, landing the fix makes CI report a failure and forces the record's own deletion** | **ws4e or ticket.** The fix is a row lock on a human's request path, which is a production design question |
| **The confirmation gate for a design-contract rebuild-all is structural, not enforced** | Nothing prevents the architect returning `build` with a changed contract having never asked. It is user-present, a save point exists per turn and restore works, so it is visible and recoverable | **Accept, or ticket.** Closing it needs a durable assent channel no plan specifies |
| **`resolved_data` is not a re-review trigger** | New figures never start the selective pass even though `source_contradiction` is spec-reachable and already counts as failing. One line in the field tuple | **ws4e.** One line |
| **`architect_message` inherits across turns**, like `findings` | ws4c measurement | **ws4e or ticket** — decide which, in writing |
| **A monolith CSS defect the graph aggregator fixes only for the graph path** | The token backstop prepends in front of a hoisted `@import`, which a browser then ignores. Recorded in `deck_css_aggregator.py`'s docstring. Fixing it means editing a module ruling R2 forbids touching | **Ticket.** Do not widen R2 to fix it |

### 4.3 The one that can destroy a user's work

**A real-model run gating the selective rebuild (§4.6).** `_REREVIEW_FAILING_CRITERIA` is a **single
subjective criterion**, so the entire selective-rebuild decision rests on how liberally a real model
emits `brief_not_delivered`. Liberal, and a deck-level edit rebuilds everything and destroys manual
edits — **the exact outcome §4.6 exists to prevent.** The mechanism is verified under stubs; its
economics are unmeasured.

**Disposition: ws4e, blocking.** One measured real-model run before this path touches a deck anyone
cares about. ws4c's `test_graph_live_real_model.py` is the harness shape to copy: opt-in through an
environment variable, `live`-marked, and in ws4a's `DELIBERATE_EXCLUSIONS` so it can never run in CI.
**Run its stage 1 first** — one call, answering whether a real model returns a `DeckSpec` that
survives its validators, which is the question that decides whether stage 2 is worth paying for.

### 4.4 Performance and cost, measured

| Item | Measurement | Disposition |
|---|---|---|
| **Selective re-review latency is serial by ruling** | One review call per committed slide inside the architect turn. Machinery cost is free — `non_model_elapsed=5.2ms` for 31 slides — so the whole cost is model latency, and it is **linear**: roughly **5 minutes for a 31-slide deck before any builder starts, with nothing streaming during it** | **ws4e.** Parallelising is a local change inside `rereview_committed_slides` that no caller can observe; picking a concurrency bound is the only decision, and the existing builder `CAP` is 15 |
| **Checkpoint growth** | **538 KB across 14 rows for 31 slides with brand bytes EMPTY**, so ~8 MB per turn is realistic. `findings` is unbounded and **nothing calls `delete_thread`** | **ws4e or ticket.** Unbounded growth per session in production Postgres |
| **Two behaviours uncharacterised on Postgres** | Concurrent failing builders writing two chat messages in one superstep; and the above | **ws4e.** Use `postgres_engine` |

### 4.5 Observability

**Production INFO logging is dead code.** `setup_logging()` has no caller, and `_otel_bootstrap.py`
states in its own docstring that it is "loaded first from `main.py`" while **nothing imports it**. So
`mark_dirty`'s audit line — the only record of which human dirtied a deck — goes nowhere. Four
reserved-`LogRecord`-key collisions were fixed during ws4d so that switching it on no longer *raises*;
whether it is meant to be on is undecided.

**Disposition: ws4e must decide, in writing, and the decision is cheap either way.** If logging is
meant to be on, the audit trail for human edits currently does not exist. Note also the three
per-row INFO lines in `src/core/backfill_session_slides_startup.py` (`:82`, `:86`, `:165`) which log
the uninteresting case once per row over a production-sized deck set; startup timeouts have blocked
devloop deploys before.

### 4.6 Test-suite honesty

| Item | Detail | Disposition |
|---|---|---|
| **One test is the SOLE guard** between the streaming and polling release rules drifting on an edit turn | Measured: remove its `covered=(5,6)` case and widen the streaming rule and **nothing reddens**. Do not "tidy" it | **Accept, and leave it alone** |
| **The baseline log records skips as a COUNT and never enumerates them** | So a test silently becoming skipped is invisible to a by-cause comparison — a gap in the doctrine's own artefact | **ws4e.** A future baseline should enumerate skipped ids; you are the last workstream that can set that precedent |
| **Seven quarantined e2e specs** | Greppable `FOLLOW-UP` marker in `tests/unit/test_e2e_matrix_covers_specs.py`; they predate the app-shell redesign and need re-authoring against `AppLayout`. **`slide-viewer` is NOT among them** — it is collected and green, which matters because it is the only spec covering the findings drawer your E2 surfaces | **ws4e for `slide-viewer`'s continued health; ticket for the seven** |
| **`test_route_authz_coverage.py` cannot detect a wrong permission LEVEL** | Measured: it passed 7 green with a real `CAN_VIEW`-instead-of-`CAN_EDIT` defect present. Every route pins its own level | **Accept.** Know it when you add a route |
| **The huashu export preflight flake** | `test_export_canvas_preflight_hostile_realm.py::…[hostile_canvas_selector_throw]`, measured **~29% flaky in isolation** (4 failures in 14 runs of that file), no workstream-4 code in the process. It compares sha256 manifests of two independently emitted PPTX files; the unmeasured hypothesis is a timestamp-bearing zip entry | **Ticket.** It is not this programme's defect and it will confuse every future by-cause comparison until someone owns it |
| **Deferred minors** | 17 in ws4b's ledger, 5 in ws4c's, 14 parked findings in ws4d's, plus 4 residuals from ws4c's fix wave and 4 from ws4d's | **ws4e triages once, in the ledger.** None blocks merge, and one of ws4c's was struck as **false** — a reviewer sabotaged the serialiser and the test reddened correctly, so a batched fix pass would have churned a correct test |

### 4.7 Pre-existing findings, reported and deliberately not fixed

Four from ws4b, under rulings R-K, R-P, R-S and R-U: fifteen lockfile entries resolving from
`registry.npmmirror.com`; a circular import that makes `import src.database.models` fail as the first
import in a fresh interpreter; two config predicates that disagree about `design_system_id`; and the
`live`-marker gap described in 4.1. Plus: **no job except `integration-general` sets
`timeout-minutes`**, a repo-wide gap deliberately outside ws4a's scope.

**Disposition: ticket, all of them.** They predate workstream 4 and none is in ws4e's path. The
`live`-marker gap is the exception — it is inside 4.1 and ws4e should close it there.

### 4.8 Closed since the last handover, recorded so nobody re-opens them

- **The reorder case of the deck-spec misalignment — CLOSED.** Every mutation route now renumbers
  `deck_spec_json`, through one primitive with four callers. See `ws4d-HANDOVER.md` §4a for the fix,
  the two rulings inside it, and the five sabotages. **The consumer-side guard stays and is not
  redundant**, because the spec write is deliberately allowed to fail without failing the user's
  mutation.
- **The Postgres test harness — CLOSED.** `TELLR_TEST_POSTGRES_URL` is set in every job that
  provisions Postgres, `unit-tests` provisions one too (nine jobs), and a shared `postgres_engine`
  fixture gives each thread its own connection. **Use it; do not build another.** Six modules under
  `tests/unit/` need a Postgres, and note `test_style_exclusivity_bypass_shapes_postgres.py` is gated
  by a module-level `pytest.skip` rather than a marker, so a marker-only inventory misses it.
- **The sweeper's outer lease predicate — CLOSED**, with a test that can fail. The proof is one
  sabotage measured two ways: remove the outer predicate at `src/services/spec_sync.py` and the
  Postgres tests fail 2 while the old SQLite four-claimer test passes 18, completely blind. Before
  this, dropping that predicate left **all 87** spec_sync tests green.
- **ws4c's real-model run — DONE and MET** (2026-09-14). 12 calls, 116s, three reviewers for three
  builders, which is the re-fan holding against real output where a static edge would give one.

---

## 5. What must be true before PR3 merges

**Two behaviour changes owe the release notes a line each.** Neither is a defect and both are
operator-authorised, but a user will notice:

1. **Slide identity for every existing user is now a durable random identifier.** All thirteen removed
   source lines were positional stamps. This fixed a shipped bug in which every reorder
   mis-attributed verification verdicts.
2. **The `ConfigPrompts` prompt columns are dropped**, so a stored custom `system_prompt` stops taking
   effect. Deliberate, per ws4a §E1/§E2.

**Ruling R2 still binds, and ws4e is the last chance to break it by accident.**
`src/services/agent.py`, `src/core/prompt_modules.py` and `src/services/design_system_compiler.py`
are **never modified** — read and import freely, private names included. Two exceptions were recorded
across all five plans: ws4a's `merge_css` fix, and ws4c importing `UNTRUSTED_DATA_NOTICE`. **Do not
widen either.** Relatedly, `agent.py`'s legacy prompt-concatenation branch is dead in production but
still reachable via `create_agent()`, which three test files call; it was left deliberately and goes
as a unit when the monolith goes.

**The skills ship placeholder-grade prompts by design.** They are substantive, functional instruction
text — not empty stubs — but they have not been prompt-engineered, and both ws4c's handover and
`src/core/skills/__init__.py`'s own docstring call them placeholders. Your DoD makes this binding:
**no layer-3 assertion may be weakened to accommodate a placeholder prompt.** If one is tempting,
skip the test and record why. Judge deck *quality* against this, not against the monolith's output.

---

## 6. Traps this programme paid for — do not re-learn these

The per-workstream handovers carry the full lists (`ws4a` §5, `ws4b` §5, `ws4c` §5, `ws4d` §6). These
are the ones that cost the most, and every one of them was measured rather than reasoned:

- **Anchors drift DURING a build, not only between workstreams.** Inside ws4d alone: `poll_chat`
  moved `:669` → `:691`; `restore_version` from `:2222` to `:2493`; `duplicate_slide` from `:2850` to
  `:3353`; `require_editing_lock` twice more. The workstream index explicitly promised two ranges were
  stable and **both had moved.** **Re-derive every anchor into a file an earlier task touched; never
  copy one forward. A reviewer's correction of an anchor is not evidence** — `get_system_client()` is
  at `agent_factory.py:67`, the plan says `:56`, a review "corrected" it to `:57`, and **both are
  docstring prose.**
- **Locate constructs by a distinctive bare TOKEN, never a paren-anchored prefix.** This codebase
  passes functions by reference — `asyncio.to_thread(mark_dirty, …)` — so a `mark_dirty(` grep finds
  **nothing**. Three agents made that mistake, the controller included.
- **`chat_service.py:32` gates COLLECTION of the entire unit suite** via `tests/unit/conftest.py` →
  `session_manager` → `src/api/services/__init__.py`. Reshape it and the suite stops collecting rather
  than failing.
- **A `Send` target does not appear in the compiled graph's edge list.** Guarding a node against
  unwanted entry needs **two** tests: an edge-list set-equality assertion and a `Send`-literal scan.
- **`VERSION_LIMIT = 40` EVICTS the oldest version.** A save point created per node rather than per
  turn destroys history rather than merely bloating it.
- **Restoring a file to its committed state to undo a sabotage also wipes uncommitted work in it.**
  That produced a false self-report, and the same implementer reproduced the mechanism a second time.
  **Commit before sabotaging; re-read every claim from the committed blob; revert by targeted edit.**
- **The repo's hook guard scans the whole shell command string** and refuses any command mentioning
  both a dash-prefixed short flag and the version-control tool's name — **even a heredoc writing a
  markdown file with no commit involved.** Write prose with a file-writing tool and concatenate.
- **`sqlite_engine_file_backed` is `StaticPool`** — never reach for it for anything that fans out. It
  corrupted the database 3 of 3 runs on ws4c. **The pool class is the load-bearing part, not the
  storage location.**

---

## 7. The process finding worth more than the rest

**Across ws4c and ws4d, twenty-seven guards could not reach the path they claimed to cover, and three
times the blindness sat inside a guard written to catch the previous instance.** The corrections file
names **six distinct shapes**, and every one was found by sabotage, never by reading:

| § | Shape | The test passes when… |
|---|---|---|
| 18 | absence-assertion | the code never ran at all |
| 22 | tautological-default | the code ran but carried nothing |
| 24 | mixed shape/behaviour | a *different* assertion in the same test fired |
| 26 | inert pair | the paired direction is satisfied by something else |
| 29 | involution | the transformation applied twice is the identity, so the defect cancels out |
| 31 | unreachable stub | the stubbed outcome is one production can never produce |

> **"The check found something" is far weaker than "the check found what it should have found."**

Three corollaries, each of which cost real time:

1. **§26: adding a paired assertion and verifying the pair can fail are SEPARATE STEPS.** Five paired
   assertions were added in good faith and found inert only by sabotage. The sequence is three steps —
   add the guard, pair it, **then sabotage the pair and read which assertion fired.**
2. **Assign every reviewer a sabotage target its implementer has not used, and require it to say
   plainly when nothing goes red.** On six of ws4b's tasks, an outside sabotage was the only thing
   that found the defect.
3. **When the defect already ships, write the test RED FIRST and confirm it fails before fixing
   anything.** ws4d's Task 7, its final fix wave and the route-renumbering follow-on all did this. It
   is the only way to know a guard would ever have caught the bug — and the selective re-review had
   **fourteen green tests over it** precisely because nobody had.

**Read sabotage results by which tests fired, never by how many.** A count comparison hid a genuinely
new breakage for seven consecutive tasks on an earlier build and propagated a wrong attribution into
roughly seven dispatch briefs.

---

## 8. Where the decisions are recorded

- **ws4d:** forty rulings and fourteen parked findings in
  `.superpowers/sdd/2026-08-25-ws4d-wiring-and-propagation/progress.md`, each with what it costs if
  wrong; fifteen pre-flight rulings in §17 of `.ws4d-PLAN-CORRECTIONS.md`.
- **ws4c, ws4b, ws4a:** their own ledgers under `.superpowers/sdd/`, and their handover notes.
- **These workspaces are deliberately NOT deleted**, because until the whole of PR3 merges the ledgers
  are the only record of decisions taken on the operator's behalf.
