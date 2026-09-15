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
| **The deck-level spec is renumbered on INSERT ONLY.** After a delete or duplicate its positions no longer match the rows, and this branch's own code reads that representation — measured, a turn dispatched a builder for a position with no slide and **the deck gained one nobody asked for** | final review C1 |

---

## 4. WHAT YOU OWN THAT ws4d DELIBERATELY LEFT

**Read this before planning your tasks. Three of these are yours by assignment, not by default.**

- **THE POSTGRES HARNESS, and this is the one that will bite you.** Four items were parked as "ws4e, needs
  a real database". **Measured: the `integration-graph` job provisions Postgres 15 and exports
  `DATABASE_URL`, but NOT ONE of the seven ws4d integration files reads it** — they all run on the SQLite
  engine at `tests/integration/conftest.py:604`. So CI will report the suite green and close **none** of
  them. **Your layer-4 work must build the harness first**, or these four stay unfunded:
  1. **The sweeper's outer lease predicate is untested.** Measured: dropping only the outer
     `.where(unclaimed)` reddens **nothing**, because sqlite's single writer serialises the four claimers so
     the race window never opens. Your test must exercise **two genuinely overlapping transactions**.
  2. **The `mark_dirty`-versus-claim TOCTOU** — costs one skipped re-description, never a lost edit.
  3. **Postgres lock ordering between the two title writers.**
  4. **Sweeper throughput:** all four workers pick the same `LIMIT 1` candidate, so real throughput is 1–4
     decks/minute rather than 4. `with_for_update(skip_locked=True)` fixes that **and** hedges the
     EvalPlanQual reliance on the same line — but it is Postgres-behaviour reasoning with no Postgres to
     test against, which is exactly why it is yours.
  **And `sqlite_engine_file_backed` is `StaticPool`** — do not reach for it for anything that fans out. It
  corrupted the database 3 of 3 runs on ws4c. **The load-bearing part is the POOL CLASS, not the storage
  location.**
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
- **A reorder is invisible to the final review's C1 guard**, because it compares position **sets** and a
  reorder preserves the set. Both stronger predicates were measured and rejected for firing on correctly
  aligned decks. **Only per-route renumbering closes it** — the wide fix that was ruled against.
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
