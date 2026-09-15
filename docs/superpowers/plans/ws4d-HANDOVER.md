# ws4d → ws4e handover

**Written 2026-09-15, on completing ws4d.** For whoever picks up **ws4e**
(`2026-08-25-ws4e-surfaces-and-gates.md`). Read this *after* the documents in §2, not instead of them —
it carries only what ws4d changed, decided, or measured.

---

## 1. Where things stand

- **ws4d is complete: 51 commits, all eight tasks built, reviewed and fixed**, on `feat/ws4d-wiring`,
  cut from `feat/langgraph-core` at `7f938a1b`. **NOT yet merged** — the operator merges locally, as with
  ws4a, ws4b and ws4c.
- Suite: **`7 failed, 5427 passed, 10 skipped`, 5443 collected** — from 4988 at the branch cut, so
  **+455 cases**. **Section 2c of `docs/superpowers/baselines/pr3_ws4_collected.log` is now superseded for
  you: see §5, because the number of environmental failure causes has gone from two to FOUR.**
- **The graph is reachable from chat.** `USE AGENT MODE` in a session's earliest user message selects it
  per deck; slides stream on SSE and poll on HTTP; a human hand-edit marks the spec dirty and a
  four-worker-safe sweeper re-describes the narrative; restore cancels a pending review; slides can be
  inserted; and a deck-level spec change re-reviews every slide and rebuilds only failures.
- **The monolith is untouched.** `test_agent.py`, `test_llm_edit_responses.py` and
  `test_slide_replacement_flow.py` pass with a **zero diff over all three paths** across the whole branch.

---

## 2. Read these first, in this order

1. **`.claude/skills/executing-plans-tellr/`** *and* **`superpowers:subagent-driven-development`** — both,
   per `CLAUDE.md`.
2. **`ws4-START-HERE.md`**, then **`2026-08-25-ws4-index.md`**.
3. **`docs/superpowers/plans/.ws4d-PLAN-CORRECTIONS.md` — 1069 lines, 32 sections.** Several are contracts
   you consume rather than ws4d's private notes: **§25** (a `Send` target does **not** appear in the
   compiled graph's edge list — measured), **§27** (two async testing traps you will meet in layer-4),
   **§31** and **§32** (the two largest fake-guard classes found here). **§30 is the controller's own two
   sizing errors** — read it before quoting any count.
4. **Your plan**, end to end, before writing anything.
5. **Do the corrections pre-pass into `.ws4e-PLAN-CORRECTIONS.md` before Task 1.** ws4a found six
   corrections, ws4b twenty-three, ws4c four blocking plus sixteen anchors, **ws4d five blocking plus
   twenty-seven anchors.** It is the highest-yield hour of the build.

---

## 3. THE FOUR THINGS ws4d FOUND THAT WOULD HAVE SHIPPED

Each was measured, not reasoned, and each would have been silent.

| | |
|---|---|
| **The async engine-mode path runs through the JOB QUEUE, which the plan never mentions.** `POST /chat/async` does not call `send_message_streaming` — it enqueues, and **MCP shares the same `enqueue_job`, worker and `process_chat_request`.** Resolving mode "at the top of the streaming path" puts MCP on the graph, which is the blocking review finding the plan was written to fix. Six edit points across two files. And the payload key had to be `engine_mode`, because `mode` was already taken by MCP | §2 |
| **`_reindex_slide_ids` rewrote every `slide_id` to its position** at ten call sites, so the matcher's tier-1 "durable per-slide identity" silently degraded to matching by position. **On a monolith deck every reorder mis-attributed verification verdicts; a slide could display another slide's verdict.** The frontend was already written to the contract the backend broke — `SlideViewer.tsx` keys verification by `slide_id` "not array index" precisely so mutations survive | §29 / Task 7 |
| **§4.6's re-review pass was INERT, and fourteen tests were green over it.** The brief never reached the reviewer's payload, and the only criterion able to express "no longer serves the brief" is `objective=False` while the failing rule counted objective findings only. The tests passed because every failing stub returned `overflow` — a *rendering* criterion no spec edit can cause | §31 |
| **The deck-level spec was renumbered on INSERT ONLY.** After a delete or duplicate its positions no longer matched the rows, and this branch's own code reads that representation — measured, a turn dispatched a builder for a position with no slide and **the deck gained one nobody asked for**. Fixed twice: a consumer-side guard during the build, then **route renumbering after it, at the operator's request** — see §4a, which is the half that closes reorder | final review C1 |

---

## 4. WHAT YOU OWN THAT ws4d DELIBERATELY LEFT

**Read this before planning your tasks. Three of these are yours by assignment, not by default.**

- **THE POSTGRES HARNESS NOW EXISTS. Use it — do not build one.** This was fixed after the ws4d build, at
  the operator's request, and it changes what you inherit.
  **What was wrong:** eight jobs provisioned `postgres:15` and exported only `DATABASE_URL`, while the
  repo's established self-skip pattern reads **`TELLR_TEST_POSTGRES_URL`** — which **no workflow set**. So
  every Postgres-marked test self-skipped in CI while passing on a developer's laptop: **CI was strictly
  weaker than a laptop, silently.** And no Postgres engine fixture existed for integration tests, which is
  why all seven ws4d integration files used the SQLite engine at `tests/integration/conftest.py:604`.
  **What you now have:** `TELLR_TEST_POSTGRES_URL` set in every job that provisions Postgres, `unit-tests`
  provisioning one too (**nine** jobs), and a shared **`postgres_engine`** fixture in
  `tests/integration/conftest.py` that gives **each thread its own connection**. `DATABASE_URL` is
  deliberately NOT set in `unit-tests`, because that is what production code connects to, whereas
  `TELLR_TEST_POSTGRES_URL` has zero readers under `src/` — which is what makes it safe.
  **To run these locally:** start a Postgres on 5432, or export `TELLR_TEST_POSTGRES_URL`. **Six** modules
  under `tests/unit/` need one (note `test_style_exclusivity_bypass_shapes_postgres.py` is gated by a
  module-level `pytest.skip` rather than a marker, so a marker-only inventory misses it).
  **Of the four items parked as "needs a real database", two are CLOSED and one is BANKED:**
  1. **The sweeper's outer lease predicate — CLOSED.** It now has a test that can fail, in
     `tests/integration/test_claim_exclusivity_postgres.py`, driving two genuinely overlapping
     transactions. **The proof, measured both ways under one sabotage** — remove the outer
     `.where(unclaimed)` at `src/services/spec_sync.py:479`, leaving the inner select's copy: **the Postgres
     tests fail 2, the old SQLite four-claimer test passes 18, completely blind.** Before this, dropping
     that predicate left **all 87** spec_sync tests green.
  2. **The `mark_dirty`-versus-claim TOCTOU — REPRODUCED and BANKED as `xfail(strict=True)`, not fixed.**
     Measured: `spec_dirty_at` ends BEHIND `spec_dirty_claimed_at` while `spec_dirty_by` carries the second
     author, so the edit coalesces into an already-claimed window, `clear_marker`'s re-dirty rule never
     fires, and the finishing review discards an edit it never covered. **Because the xfail is strict, the
     moment someone lands the fix the test XPASSes and CI reports a failure — the record forces its own
     deletion.** The fix is a row lock on a human's request path, which is a production design question.
  3. **Postgres lock ordering between the two title writers — still yours**, and now cheap: use
     `postgres_engine`.
  4. **Sweeper throughput — still yours.** All four workers pick the same `LIMIT 1` candidate, so real
     throughput is 1–4 decks/minute rather than 4. `with_for_update(skip_locked=True)` fixes that **and**
     hedges the EvalPlanQual reliance on the same line. You now have a Postgres to test it against.
  **Still true and still load-bearing: `sqlite_engine_file_backed` is `StaticPool`** — never reach for it
  for anything that fans out. It corrupted the database 3 of 3 runs on ws4c. **The pool class is the
  load-bearing part, not the storage location**, which is why the new fixture is guarded by a test asserting
  four simultaneous checkouts are four distinct backends.
  **Weakness to know about:** both new concurrency tests deliberately **gate** claimer A, because an ungated
  barrier fan-out cannot guarantee overlap and would be flaky. So the genuinely-random four-worker arrival
  shape is still only covered weakly, on SQLite. And `_await_lock_waiters` reads
  `pg_stat_activity.wait_event_type` (PG 9.6+) — fine on 14.20 and 15, but version-dependent.
- **A REAL-MODEL RUN, GATING §4.6.** `_REREVIEW_FAILING_CRITERIA` is a **single subjective criterion**, so
  the entire selective-rebuild decision rests on how liberally a real model emits `brief_not_delivered`.
  **Liberal, and a deck-level edit rebuilds everything and destroys manual edits — the exact outcome §4.6
  exists to prevent.** The mechanism is verified under stubs; its economics are unmeasured. **One measured
  real-model run before this path touches a deck anyone cares about.**
- **Frontend rendering of `slide_ready`.** ws4d delivers both backend transports and the TypeScript types;
  ws4e realises the user-visible feature. Note `handleStreamEvent` already has **seven** case branches, not
  the two an earlier review claimed — adding a duplicate `case` is a compile error. And the TS union member
  is guarded by a test that reads `api.ts` as **text**, because types are erased and deleting the member
  left `npm run typecheck` at **exit 0**.
- **Findings in the drawer.** `findings_from_record` exists and deck-level findings still live in
  `deck_reviews` reaching the user as an `info` message; no `slide_index == -1` reaches `SlideViewer`.
- **The spec view after `clear_context`** — the assertion ws4e owns: the spec view still has data while the
  transcript is empty.

---

## 4a. ROUTE RENUMBERING — done after the build, at the operator's request

**This section supersedes what §3's C1 row and §8's first bullet used to say.** During the build the fix for
C1 was a **consumer-side guard**; the operator then asked why the real fix was not simply taken, and it was.
Both halves are now in the tree and both are tested, because they cover different things.

**What changed.** `session_slide_decks.deck_spec_json` is renumbered by **every** mutation route, not only
insert. One primitive, `ChatService._rewrite_deck_spec_slides`, with four thin callers
(`_insert_deck_spec_slide`, `_delete_deck_spec_slide`, `_duplicate_deck_spec_slide`,
`_reorder_deck_spec_slides`). The routes supply only *which entries end up in which order*; the position
stamping, the raw-dict handling, the author stamp and the failure policy live in the primitive once — because
four hand-copied writers diverging is the defect class that produced C1 in the first place.

**Why the guard stays and is NOT redundant.** Renumbering closes the routes; it does not make a stale spec
unreachable:
- **the spec write is deliberately allowed to fail** — `_rewrite_deck_spec_slides` logs and returns `None`
  rather than failing the mutation the user asked for, since the slide change is already committed by then.
  That path leaves exactly the misalignment the guard catches, and it is live in production.
- **an architect-EMITTED spec goes through no route at all** (still open — §8).
- **`deck_spec_json` is a column a human or a migration can edit.**

**Two rulings, both the controller's, both overridable:**
1. **A duplicated slide inherits its SOURCE's brief, not a blank one.** A duplicate is a copy of a slide we
   already have a description for, so that description is known to be right, where an inserted slide has
   none. The sweeper re-describes both either way, so this decides which starting point is true, not who
   writes the final prose.
2. **A spec that cannot answer the mutation is left untouched, not renumbered.** If the entry count and the
   deck disagree the two have already drifted; leaving a drifted spec alone is recoverable, renumbering it
   against the wrong slides is not.

**What the evidence is.** `tests/unit/test_mutations_renumber_the_deck_spec.py` (26 cases) written RED
first — 18 failed, and the 8 that passed were exactly the controls (insert, the no-spec degradation, the
save-point count). Plus `tests/integration/test_spec_row_alignment.py`, rewritten. Five sabotages, each
read by which tests fired rather than by a count:

| Sabotage | Result |
|---|---|
| delete call site → `None` | 9 fail |
| reorder call site → `None` | 8 fail |
| duplicate call site → `None` | 6 fail |
| `_permute` returns `entries` unchanged | 8 fail — the reorder tests, **and the identity control stayed GREEN** |
| the `position` re-stamp removed | 22 fail, insert's own case among them |

**That fourth row is the point.** §29's involution trap: a renumber is a permutation and the identity is one
of them, so a reorder test that only ever permutes cannot tell a correct remap from one that ran twice or
never ran. The suite pins the fixed point (`[0, 1, 2]`) *and* a reversal (`[2, 1, 0]`, which is its own
inverse), so the sabotage has somewhere to land and somewhere it must not.

**Suite after:** `7 failed, 5484 passed, 10 skipped, 1 xfailed`, **5501 collected** — from 5470, exactly the
31 added. Failure causes unchanged: 2 deploy-autoscaling, 5 expired PAT. No new cause.

**One thing to know if you touch `test_spec_row_alignment.py`.** It anticipated this change in its own
docstring and left instructions — *"that change should redden the premise test first, and whoever makes it
should then relax these three rather than delete the guard."* That is exactly what happened, so the premise
tests now assert the **opposite** of what they originally asserted, and the three damage tests inject the
mismatch directly rather than obtaining it from a route that no longer produces one. The injection is not a
weakening: it is the honest shape of what remains reachable, per the three bullets above.

---

## 5. THE BASELINE CHANGED SHAPE: FOUR ENVIRONMENTAL CAUSES, NOT TWO

**Compare causes, never counts — and after ws4d a naive count comparison is actively misleading.** At one
gate the failure count went 3 → 7 and would have read as catastrophic; every one was environmental.

| Cause | Tests | Behaviour |
|---|---|---|
| **deploy-autoscaling** | 2 | The standing baseline cause. **Its two strings must stay at exactly 1 and 2 occurrences — that is the comparison that matters.** |
| **Dead Genie space** | 1 | Moves between the *failed* and *skipped* columns run to run, so its string count varies **and the skip count reads 9 or 10.** |
| **Expired Databricks PAT** | 5 | `test_client_integration.py`, `PermissionDenied: Invalid access token`, `auth_type=pat`. `src/core/database.py` calls `load_dotenv()`, so the operator's `.env` leaks in and these hit a **real** workspace locally. **Refresh the token and they go green.** |
| **huashu export preflight** | 1 | `test_export_canvas_preflight_hostile_realm.py::…[hostile_canvas_selector_throw]` — measured **~29% flaky on its own** (4 failures in 14 isolated runs of that file), no ws4d code in the process. It compares sha256 manifests of two independently emitted PPTX files; hypothesis (unmeasured) is a timestamp-bearing zip entry. **Deserves its own ticket.** |

Also: **`pyproject.toml` declares the `live` marker "excluded in CI with a not-live filter" but sets no
`addopts`**, so a local full run executes live network tests CI never does. And **the baseline log records
skips as a COUNT only and never enumerates them**, so a test silently becoming skipped is invisible to a
by-cause comparison — a gap in the doctrine's own artefact. A future baseline should enumerate skipped ids.

---

## 6. TRAPS ws4d PAID FOR — do not re-learn these

- **Anchors drift DURING a build, not only between PRs.** `poll_chat` moved `:669` → `:691` inside this PR;
  `restore_version` from the plan's `:2222` to `:2493`; `duplicate_slide` from `:2850` to `:3353`;
  `require_editing_lock` twice more, to `:2710`. **Re-derive every anchor into a file an earlier task
  touched; never copy one forward.** The workstream index explicitly promised `:194-239` and `:709` were
  stable and **both had moved.**
- **`get_system_client()` is at `agent_factory.py:67`.** The plan says `:56`, a review "corrected" it to
  `:57`, and **both are docstring prose.** A reviewer's correction of an anchor is not evidence.
- **Locate constructs by a distinctive bare TOKEN, never a paren-anchored prefix.** This codebase passes
  functions by reference — `asyncio.to_thread(mark_dirty, …)` — so a `mark_dirty(` grep finds **nothing**.
  Three agents made that mistake, the controller included.
- **The repo's hook guard scans the whole shell command string** and refuses any mentioning both a
  dash-prefixed short flag and the version-control tool's name — **even a heredoc writing a markdown file
  with no commit involved.** Write prose with a file-writing tool and concatenate.
- **`chat_service.py:32` gates COLLECTION of the entire unit suite** via
  `tests/unit/conftest.py` → `session_manager` → `src/api/services/__init__.py`. Reshape it and the suite
  stops collecting rather than failing.
- **Restoring a file to its committed state to undo a sabotage also wipes uncommitted work in it.** That
  produced a false self-report here, and the same implementer reproduced the mechanism a second time.
  **Commit before sabotaging; re-read every claim from the committed blob; revert by targeted edit.**
- **`tests/unit/test_route_authz_coverage.py` cannot detect a wrong permission LEVEL** — measured, it passed
  7 green with a real `CAN_VIEW`-instead-of-`CAN_EDIT` defect present. Every route pins its own level.
- **A `Send` target does not appear in the compiled graph's edge list** (§25). Guarding a node against
  unwanted entry needs **two** tests: an edge-list **set-equality** assertion and a `Send`-literal scan.
- **`VERSION_LIMIT = 40` EVICTS the oldest version.** A save point created per node rather than per turn
  destroys history rather than merely bloating it.

---

## 7. THE ONE PROCESS FINDING WORTH MORE THAN THE REST

**Twenty guards on this branch could not reach the path they claimed to cover, and three times the
blindness sat inside a guard written to catch the previous instance.** ws4c found seven. The corrections
file now names **six distinct shapes**, and every one was found by sabotage, never by reading:

| § | Shape | The test passes when… |
|---|---|---|
| 18 | absence-assertion | the code never ran at all |
| 22 | tautological-default | the code ran but carried nothing |
| 24 | mixed shape/behaviour | a *different* assertion in the same test fired |
| 26 | inert pair | the paired direction is satisfied by something else |
| 29 | involution | the transformation applied twice is the identity, so the defect cancels out |
| 31 | unreachable stub | the stubbed outcome is one production can never produce |

> **"The check found something" is far weaker than "the check found what it should have found."**

**And §26's corollary, which cost the most: adding a paired assertion and verifying the pair can fail are
SEPARATE STEPS.** Five paired assertions here were added in good faith and found inert only by sabotage.
The sequence is three steps — add the guard, pair it, **then sabotage the pair and read which assertion
fired.**

**The single highest-value practice available to you: when the defect already ships, write the test RED
FIRST and confirm it fails before you fix anything.** Task 7 and the final fix wave both did it, and it is
the only way to know a guard would ever have caught the bug. Two of ws4d's worst defects were found that
way and one — §4.6's inert re-review — had fourteen green tests over it precisely because nobody could.

---

## 8. What ws4d leaves open

- **CI has never executed this branch. Reported as NOT met**, and CI has never completed a run on ws4a,
  ws4b or ws4c either. **Any DoD item resting on a CI observation cannot be claimed.** Worse, per §4, the
  Postgres it provisions is unused.
- ~~A reorder is invisible to the final review's C1 guard.~~ **CLOSED after the build — see §4a.** The
  reasoning that parked it still holds and is worth keeping: the guard compares position **sets**, a reorder
  preserves the set, both stronger consumer-side predicates were measured and rejected for firing on
  correctly aligned decks, and **only per-route renumbering closes it**. That is the fix that was ruled
  against during the build and taken afterwards.
- **An architect-EMITTED spec is unchecked.** A model echoing back `current_deck_spec` can re-materialise a
  deleted slide on a build turn. The C1 guard covers only the persisted-spec fallback.
- **The confirmation gate for a design-contract rebuild-all is structural, not enforced.** Nothing prevents
  the architect returning `build` with a changed contract having never asked. It is user-present, a save
  point exists per turn and restore works, so it is visible and recoverable — but closing it needs a durable
  assent channel no plan specifies.
- **Slide identity for every existing user is now a durable `uuid4`.** All thirteen removed `src/` lines are
  the positional stamps. Correct, operator-authorised, and it fixed a shipped bug — **but it belongs in the
  release notes.**
- **Production INFO logging is dead code.** `setup_logging()` has no caller and `_otel_bootstrap.py` states
  in its own docstring that it is "loaded first from `main.py`" while **nothing imports it**. So `mark_dirty`'s
  audit line — the only record of which human dirtied a deck — goes nowhere. Four reserved-`LogRecord`-key
  collisions were fixed so that switching it on no longer *raises*; whether it is meant to be on is undecided.
- **`resolved_data` is not a re-review trigger**, so new figures never start the pass even though
  `source_contradiction` is spec-reachable and already counts as failing. One line in the field tuple.
- **§4.6's latency is serial by ruling:** one review call per committed slide inside the architect turn.
  Measured machinery cost is free (`non_model_elapsed=5.2ms` for 31 slides); the whole cost is model
  latency and it is **linear** — roughly 5 minutes for a 31-slide deck before any builder starts, with
  nothing streaming during it. Parallelising is a local change inside `rereview_committed_slides` that no
  caller can observe; picking a concurrency bound is the decision, and the existing builder `CAP` is 15.
- **One test in the two-prefix-rule agreement suite is the SOLE guard** between the SSE and polling release
  rules drifting on an edit turn — measured: remove its `covered=(5,6)` case and widen the SSE rule and
  **nothing reddens.** Do not "tidy" it.
- **Forty rulings and fourteen parked findings** are recorded in the SDD ledger at
  `.superpowers/sdd/2026-08-25-ws4d-wiring-and-propagation/progress.md`, each with what it costs if wrong.
  Fifteen pre-flight rulings are in §17 of the corrections file. **The workspace is deliberately NOT deleted
  until the operator merges**, because until then the ledger is the only record of decisions taken on their
  behalf.
