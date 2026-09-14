# ws4c → ws4d handover

**Written 2026-09-14, on completing ws4c.** For the agent picking up **ws4d**
(`2026-08-25-ws4d-wiring-and-propagation.md`). Read this *after* the documents in §2, not instead of
them — it carries only what ws4c changed, decided, or measured, all of which your plan predates.

---

## 1. Where things stand

- **ws4c is complete: 28 commits, all nine tasks built, reviewed and fixed**, on
  `feat/ws4c-graph-core`. **NOT yet merged** — the operator merges locally, as with ws4a and ws4b.
- Suite: **3 failed, 4977 passed, 8 skipped, 4988 collected.** The three failures are the two
  pre-existing causes; **Section 2c** of `docs/superpowers/baselines/pr3_ws4_collected.log` is now
  your baseline and Section 2b is ws4c's.
- **A compiled graph builds a deck end to end** under stub agents: architect → analyst → foreman →
  parallel builders → one reviewer per slide → fixer → fix reviewer → deck reviewer. **Nothing is
  reachable from chat. That is your job.**
- The monolith is untouched. `agent.py`, `prompt_modules.py` and `design_system_compiler.py` are
  byte-identical to the merge base (ruling R2 held for all nine tasks).

---

## 2. Read these first, in this order

1. **`.claude/skills/executing-plans-tellr/`** *and* **`superpowers:subagent-driven-development`** —
   both, per `CLAUDE.md`.
2. **`ws4-START-HERE.md`**, then **`2026-08-25-ws4-index.md`**.
3. **`docs/superpowers/plans/.ws4c-PLAN-CORRECTIONS.md` — 62 sections, 40 rulings.** Several are
   contracts you consume, not ws4c's private notes: **§48** (the foreman must never be a router's
   fall-through target), **§55** (the msgpack restructure **you own**), **§57** (the fixture you must
   not reuse), **§59** (how a CI job actually gates), **§61**.
4. **`docs/superpowers/plans/.ws4c-MEASURED-INTERFACES.md`** — every interface ws4c binds to, quoted
   from source **by script**, not typed. Regenerate with
   `scripts/gen_ws4c_measured_interfaces.sh` if you move any of them; it reports NOT FOUND rather
   than emitting stale line numbers, which is how it caught C8's move.
5. **Your plan**, end to end, before writing anything.
6. **Do the corrections pre-pass** into `.ws4d-PLAN-CORRECTIONS.md` before Task 1. On ws4a it found
   six corrections, on ws4b twenty-three, on ws4c **four blocking ones plus sixteen wrong anchors**.

---

## 3. THE FOUR THINGS ws4c FOUND THAT WOULD HAVE SHIPPED

Each was in the plan, each was caught before Task 1 or by a sabotage, and each would have been silent.

| | |
|---|---|
| **A router sees the writes of the node it hangs off.** So a foreman that stamps `dispatched_at` and a router that recomputes the batch gives `[]` — every stamped position reads as in-flight, the turn falls through to `END`, **the graph builds nothing, and every unit test stays green** | §2 |
| **`stalled_positions` limb 1 and the foreman's decision order were mutually unsatisfiable** — the limb excluded exactly the case it existed for, so a dead builder left a gap with no placeholder and nothing in chat | §3 |
| **`_get_prompt_content` returns `"slide_style": None` for every config**, and a test pins that null. The plan's one-line `resolve_slide_style` would have resolved nothing, and its "irreplaceable" guard test compared `None` to `None` | §33 |
| **A router fall-through runs concurrently with its siblings' Sends.** So `builder`'s fall-through to `foreman` woke the foreman mid-batch and **the deck reviewer ran twice** | §48 |

---

## 4. WHAT ws4d OWNS THAT ws4c DELIBERATELY DID NOT CLOSE

**Read this section before you plan your tasks — two of these are yours by assignment, not by default.**

- **The msgpack restructure (§55, Ruling C-25) is YOURS.** `DeckSpec` and `Finding` are declared in
  `GraphState`, and langgraph warns it **will stop deserialising them**. Measured: under
  `LANGGRAPH_STRICT_MSGPACK=true` it does **not raise** — it **silently degrades both to plain
  `dict`**, so the symptom is attribute access failing far downstream with nothing pointing at
  serialisation. ws4c ships a **tripwire** (a serde round-trip assertion in
  `test_graph_orchestration.py`) so an upgrade reddens CI instead of production. The restructure recipe
  is in §55: `DeckSpec.to_json()`/`from_json()` and `Finding.model_dump()` both already exist.
  **You are the first PR where a real user drives turn 2, so absorb it if you touch those nodes.**
- **`tool_grants` is dead metadata.** No `bind_tools` call exists anywhere, so the data analyst can
  reach no tool. The grants are declared and correct; nothing consumes them.
- **Brand assets and user-uploaded images cannot reach a graph-built deck.** No `GraphState` key and no
  payload field carries an id, and `search_brand_assets` gating stayed in `agent_factory`. Closing
  either needs a **declared channel**, not a local edit.
- **`ResolvedData.figures` is always empty** — `AnalystOutput` declares no field that maps to it, which
  makes the `source_contradiction` criterion unreachable on the graph path.
- **`ask_data` has no round bound.** Bounding it needs a new declared `GraphState` key.
- **Deck-level findings never enter the flat findings list** (Ruling C-6), so no `slide_index == -1`
  reaches `SlideViewer`'s index filter. They live in `deck_reviews` and reach the user as an `info`
  chat message. Surfacing them in the drawer is ws4e's.

---

## 5. TRAPS ws4c PAID FOR — do not re-learn these

- **`sqlite_engine_file_backed` is `StaticPool` and MUST NOT be used for anything that fans out.**
  Measured under a real 15-slide compiled turn: **3 of 3 runs failed — two SIGSEGV and a 45-second
  deadlock.** ws4b's guidance says "file-backed"; **the load-bearing part is the POOL CLASS**, not the
  storage location. Give each thread its own connection. (§57)
- **A CI job in `test-summary`'s `needs:` gates NOTHING.** The gate is the `for result in …` failure
  loop, and `test-summary` runs `if: always()`, so a job outside the loop lets a red suite exit 0. ws4c
  shipped exactly that bug for most of the build. **You will clone the `integration-graph` job — put it
  in all three places**, and note `tests/unit/test_ci_test_summary_gates_every_job.py` now guards it
  (a typo'd job name also exits 0, because GitHub resolves an unknown `needs.X.result` to `""`). (§59)
- **A handler inside a FANNED node cannot write `error_state`.** It is single-writer with no reducer, so
  two branches raise `InvalidUpdateError` — which would kill the very turn the handler exists to save.
  C1's table attributes `error_state` to "exception handlers"; that is true only for edge-reached nodes.
  Fanned nodes surface failures through the `info` notice instead. (§61)
- **`build_agent_for_request`'s presence on `agent_factory` gates collection of the ENTIRE unit suite**,
  via `tests/unit/conftest.py` → `session_manager` → `src/api/services/__init__.py` → `chat_service`.
  **You rewrite `chat_service`.** Remove that import without the chain and the whole unit suite stops
  collecting rather than failing a test.
- **`agent_factory` is now a re-export shim** exposing exactly `_build_tools`,
  `_design_system_is_active` and `_get_prompt_content`, plus locally-defined `_create_model` and
  `build_agent_for_request`. The six tool builders and `search_images` are **deliberately withheld**, so
  a stale `patch("src.services.agent_factory.build_mcp_tools")` raises `AttributeError` instead of
  silently intercepting nothing (Ruling C-20). Do not "restore" them.
- **Worktree-isolated reviews are broken here.** Both attempts were created from a base commit on an
  unrelated line of history; in one case **every file under review was absent**. If you use one, `diff -q`
  each reviewed file against the main tree before trusting the verdict. (§51)
- **Only ONE agent may falsify in a tree at a time**, whatever its role. Several implementer briefs
  require sabotaging production code, so implementers are sabotaging agents too. Parallelism works for
  *writing* — four tasks ran concurrently and cleanly on disjoint files — and not for falsifying. (§52)
- **`load_dotenv()` still leaks the operator's `.env` into test runs.** Measure anything touching a
  Databricks client with the CI env.
- **`.claude/worktrees/` now holds THIRTEEN stale repo copies**, not the nine ws4b documents. Scope every
  grep to `src/ tests/ frontend/src/ scripts/ .github/`.
- **Delete probe files before measuring the suite.** Twice a probe file registered as a phantom fourth
  failure via ws4a's collection guard, and a count comparison would have sent someone hunting it.

---

## 6. THE ONE PROCESS FINDING WORTH MORE THAN THE REST

**Seven times in this PR, a guard could not reach the path it claimed to cover** — and twice the
blindness was inside the guard written to catch the previous instance:

1. a coupling guard exercising one branch limb of two (466/466 green with the other limb re-inlined);
2. a `break` guard inside a loop its fixture never entered;
3. "three style cases" that were two identical booleans;
4. an AST scan blind to `x: T = {...}` while handling `x = {...}`;
5. **the guard written to catch (4)** — it asserted "every node yields at least one key", and the
   blindness costs 3 keys of 34 and empties no node;
6. a CI job in `needs:` but not the failure loop;
7. **the guard written to catch (6)** — it derived its job universe from `needs:`, so a job absent from
   `needs:` gated nothing and all three assertions passed.

**None was visible by reading the code.** Every one needed someone to break the line and look.

> **"The check found something" is far weaker than "the check found what it should have found."**

So: **sabotage every guard, and then sabotage the guard you wrote to protect it.** The two instances that
found the most were the ones where an agent doubted its own fix.

The corollary, learned three times at the controller's expense: **a corrections file is not more reliable
than the plan it corrects — it is only newer.** Three of ws4c's own corrections were wrong in ways that
shaped code (§60), each caught only because an agent implemented the instruction and checked whether the
test it promised could actually fail. Treat every ruling as a claim.

---

## 7. What ws4c leaves open

- **No run against a real model.** The DoD asks for a multi-slide deck built end to end against a live
  model; ws4c ships stub-agent coverage of the compiled graph only. **Reported as NOT met.**
- **No CI observation.** CI has never completed a run on ws4a or ws4b either, so `integration-graph` has
  never executed on a runner. **Reported as NOT met.**
- **Everything ran on SQLite.** Two behaviours are uncharacterised on PostgreSQL: concurrent failing
  builders writing two chat messages in one superstep, and checkpoint growth — measured **538 KB across
  14 rows for 31 slides with brand bytes EMPTY**, so ~8 MB per turn is realistic, `findings` is
  unbounded, and **nothing calls `delete_thread`**.
- **Five deferred minors**, all one-line test-honesty repairs, each with the behaviour covered by a
  sibling test. Listed in ws4c's ledger. A sixth was struck as **false** — the reviewer sabotaged the
  serialiser and the test reddened correctly, so a batched fix pass would have churned a correct test.
- **Four residuals from the final fix wave**, each recorded with a reason: `deck_reviewer_node`'s limit
  if the row read itself fails (pinned by a test; closing it needs the §55 restructure);
  `_reconcile_stale_fixes` claiming `landed_positions` unconditionally (pre-existing); two non-blocking
  raise-site siblings; and `placeholder_node` deliberately not writing `error_state`.
- **No optimistic locking on either deck-level write** — `expected_version` exists on the writer and
  neither call site uses it.
- **`architect_message` inherits across turns**, like `findings`.
