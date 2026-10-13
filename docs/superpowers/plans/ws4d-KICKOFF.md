# ws4d — kick-off instructions

**You are implementing ws4d, the fourth of five PRs in workstream 4.** Written 2026-09-14, on
completing and merging ws4c. Everything below is an instruction to you, not background reading.

Plan: `docs/superpowers/plans/2026-08-25-ws4d-wiring-and-propagation.md`
Scope: **ws4d ONLY.** Do not start ws4e. Do not implement anything the plan does not name.

---

## BRANCH

ws4c is already MERGED into `feat/langgraph-core` (merge commit `cf122243`). Branch off
`feat/langgraph-core`. **Do not commit to it directly, do not push, and do not open a PR without
asking.** The operator merges locally, as with ws4a, ws4b and ws4c.

## READ FIRST, IN THIS ORDER

1. The skills: `.claude/skills/executing-plans-tellr/` **AND**
   `superpowers:subagent-driven-development`. Both, per `CLAUDE.md`. Not optional.
2. `docs/superpowers/plans/ws4c-HANDOVER.md` — what your plan PREDATES. Read it before the plan.
   §4 is what you **own**; §5 is what will bite you; §6 is the one process finding worth more than
   the rest.
3. `docs/superpowers/plans/.ws4c-PLAN-CORRECTIONS.md` — 62 sections, 25 rulings. **Treat §48, §55,
   §57, §59 and §61 as contracts you consume.** Read §60 before you trust any of it: three of that
   file's own corrections were wrong in ways that shaped code.
4. `docs/superpowers/plans/.ws4c-MEASURED-INTERFACES.md` — every interface ws4c binds to, extracted
   from source **by script**. Regenerate with `scripts/gen_ws4c_measured_interfaces.sh` if you move
   any of them; it reports NOT FOUND rather than emitting stale numbers.
5. `ws4-START-HERE.md` and `2026-08-25-ws4-index.md` — and **`../reviews/ws4_r1_cde_findings.md`,
   because roughly THREE of ws4d's review findings were never applied.** You are the first PR where
   that file matters.
6. `git show cf122243 --no-patch` — ws4c's Definition-of-done record.
7. **The plan itself, end to end, before writing anything.** 523 lines, D0 through D6.

## BEFORE TASK 1 — the corrections pre-pass

Verify the plan against the code and write what you find to
`docs/superpowers/plans/.ws4d-PLAN-CORRECTIONS.md`, then point every task dispatch at it. On ws4a
this produced six corrections, on ws4b twenty-three, on ws4c **four blocking ones plus sixteen wrong
anchors**. Re-grep every `file:line` your tasks depend on: ws4c took `agent_factory.py` from 522
lines to 150, created `src/services/graph/` and `src/core/skills/`, and added `design_system_active`
to `GraphState`.

## THIS PR IS SHAPED DIFFERENTLY FROM ws4c, AND THAT CHANGES YOUR PLAN OF ATTACK

ws4c was **new code in new files** — its only existing-file edit was `agent_factory.py`. That is why
four of its nine tasks ran in parallel, and why ruling R2 was easy to hold.

**ws4d is the opposite.** It rewrites `chat_service`, touches both transports and the route handlers,
and adds a periodic loop. Those are existing, heavily-tested, multi-writer files. Expect:

- **far less parallelism** — most of your tasks converge on `chat_service` and the routes, so
  sequence by file and plan for a mostly serial loop;
- **regression risk instead of integration risk** — ws4c's danger was a graph that silently built
  nothing; yours is breaking a path that works today for every user;
- **the first user-visible behaviour in the workstream.** Both engines live in one deployment, which
  is the whole point of §D.

## THE TRAP MOST LIKELY TO COST YOU A DAY

**`build_agent_for_request`'s presence on `agent_factory` gates collection of the ENTIRE unit
suite**, via `tests/unit/conftest.py` → `session_manager` → `src/api/services/__init__.py` →
`chat_service`. **You rewrite `chat_service`.** Remove or reshape that import without following the
chain and the whole unit suite stops **collecting** rather than failing a test — which presents as a
catastrophe and is a four-hop import problem.

`agent_factory` is now a re-export shim exposing exactly `_build_tools`, `_design_system_is_active`
and `_get_prompt_content`, plus locally-defined `_create_model` and `build_agent_for_request`. The six
tool builders and `search_images` are **deliberately withheld**, so a stale patch target on
`src.services.agent_factory.build_mcp_tools` raises `AttributeError` instead of silently intercepting
nothing (ruling C-20). **Do not "restore" them.**

## WHAT YOU OWN THAT ws4c DELIBERATELY LEFT

- **The msgpack restructure (ws4c §55, Ruling C-25).** `DeckSpec` and `Finding` are declared in
  `GraphState` and langgraph will stop deserialising them — **silently degrading both to plain
  `dict`**, not raising, so the symptom is attribute access failing far downstream with nothing
  pointing at serialisation. A tripwire ships in `test_graph_orchestration.py` so an upgrade reddens
  CI. The recipe is in §55, and `DeckSpec.to_json` / `from_json` and `Finding.model_dump` all already
  exist. **You are the first PR where a real user drives turn 2 — absorb it if you touch those
  nodes.**
- **Finding 20, and it is a security fix:** `clear_context` gates on `CAN_VIEW`, so a **viewer can
  wipe a session's transcript and graph thread.** It must be `CAN_EDIT`.
- **`ask_data` has no round bound**, and `tool_grants` is dead metadata — no `bind_tools` call exists
  anywhere, so the analyst can fetch nothing and returns `no_tool` every time. That makes an
  architect/analyst ping-pong **more** likely, not less. Bounding it needs a new declared
  `GraphState` key.

## ENVIRONMENT — hard rules

- Use `~/.pyenv/versions/3.11.0/bin/python`. Never the in-tree `.venv`.
- **Never `pip install`.** Shared pyenv site-packages; an install corrupts parallel agents' runs.
- **ws4d adds no dependency.** If a task thinks it needs one, stop and escalate.
- `src/core/database.py` calls `load_dotenv()`, so the local `.env` leaks into test runs.
- **`.claude/worktrees/` now holds THIRTEEN stale repo copies**, not the nine ws4b documented. Scope
  every grep to `src/ tests/ frontend/src/ scripts/ .github/`.

## BASELINE — Section 2c, and compare CAUSES never counts

`docs/superpowers/baselines/pr3_ws4_collected.log` **Section 2c** is your baseline:
`3 failed, 4977 passed, 8 skipped, 4988 collected` — two causes, four assertion strings, each of
which must be checked **individually**. Two notes in that section were paid for:

- **A bare grep for `src.services.agent` under `tests/` now returns FIFTEEN files, not thirteen.**
  That is correct and additive: ws4c added two files that legitimately reference the module. Check
  per-file presence, never the count.
- **Delete probe files before measuring.** Twice on ws4c a probe registered as a phantom fourth
  failure via ws4a's collection guard, and a count comparison would have sent someone hunting it.

## TESTS — sabotage-verify every one, and then sabotage the guard

**Seven times on ws4c a guard could not reach the path it claimed to cover, and TWICE the blindness
was inside the guard written to catch the previous instance.** None was visible by reading the code.

> **"The check found something" is far weaker than "the check found what it should have found."**

So: break the production line a test guards, confirm it goes red **for the right reason**, confirm
the sabotage sits on the executed path, and **confirm the file still imports cleanly before believing
any red** — a `SyntaxError` reddens everything for the wrong reason and cost a cycle on ws4c.

**Then sabotage the guard you wrote to protect it.** The two most valuable findings on ws4c came from
an agent doubting its own fix.

**Assign every reviewer a sabotage target its implementer has not used, and require it to say plainly
when nothing goes red.**

## IF YOU DISPATCH SUBAGENTS

- **No git commands in ANY agent**, not even read-only ones. `git show HEAD` in a shared tree once
  destroyed a sibling's uncommitted work.
- **Only ONE agent may falsify in a tree at a time, whatever its role.** Several implementer briefs
  require sabotaging production code, so implementers are sabotaging agents too. Parallelism is for
  *writing*, not for *falsifying*.
- **Worktree isolation is BROKEN here** (ws4c §51). Both attempts were created from a base commit on
  an unrelated line of history; in one case **every file under review was absent**. If you use one,
  `diff -q` each reviewed file against the main tree before trusting the verdict.
- **INLINE the precedent rather than naming it.** Agents stall mid-exploration, never mid-writing.
- **Re-probe every external-state fact an agent volunteers** — and note the reverse paid off on ws4c
  too: agents caught the controller's own corrections wrong three times, each by implementing the
  instruction and checking whether the test it promised could actually fail.
- **To locate a construct, grep a distinctive TOKEN**, never a phrase or a `patch(`-style prefix —
  those wrap across newlines and the grep silently finds nothing. That misled three agents on ws4c,
  the controller included.
- **Write long commit messages to a FILE and use `git commit -F <file>`.** The repo's pre-commit
  guard scans the whole command string for flag-like sequences, and a prose mention of one inside a
  heredoc body is enough to block the commit. It blocked this very document twice.

## LAKEBASE, AND WHAT ws4c COULD NOT CHARACTERISE

`db-tellr` is a Lakebase **PROJECT**, not a provisioned instance — `databricks database
get-database-instance db-tellr` returning "Resource not found" is **not** an absence. Use
`databricks postgres list-projects` / `list-branches` / `list-endpoints`.

**Everything on ws4c ran on SQLite.** Two behaviours are uncharacterised on PostgreSQL, and **you run
on Lakebase**:

- concurrent failing builders write two chat messages in one superstep;
- **checkpoint growth** — measured 538 KB across 14 rows for 31 slides with brand bytes **EMPTY**, so
  ~8 MB per turn is realistic, `findings` is unbounded, and **nothing calls `delete_thread`.**

And **`sqlite_engine_file_backed` is `StaticPool` — do NOT use it for anything that fans out.** Under
a real 15-slide compiled turn it failed 3 of 3: two SIGSEGV and a 45-second deadlock. ws4b's guidance
says "file-backed"; **the pool class is the load-bearing part**, not the storage location.

## CI

**A job in `test-summary`'s `needs:` list gates NOTHING.** The gate is its `for result in …` failure
loop, and `test-summary` runs `if: always()`, so a job outside that loop lets a red suite exit 0.
ws4c shipped exactly that bug for most of its build.
`tests/unit/test_ci_test_summary_gates_every_job.py` now guards it — including a typo'd job name,
which also exits 0 because GitHub resolves an unknown `needs.X.result` to the empty string. **Put any
new job in all three places: the job list, the echo block, and the failure loop.**

CI has never run ws4a, ws4b or ws4c to completion. **If a DoD item needs a CI observation, say so
rather than declaring it met.**

## DONE

The plan's own **Definition of done** is the bar. Do not infer one, and do not report completion with
items outstanding — say what is left and why.

**Ask before deciding anything that belongs to the operator. Probe, don't infer: if a fact about the
code or the environment matters, measure it rather than reasoning about it.**
