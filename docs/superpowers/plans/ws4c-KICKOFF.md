# ws4c — kick-off instructions

**You are implementing ws4c, the third of five PRs in workstream 4.** Written 2026-09-13, on
completing and merging ws4b. Everything below is an instruction to you, not background reading.

Plan: `docs/superpowers/plans/2026-08-25-ws4c-graph-core.md`
Scope: **ws4c ONLY.** Do not start ws4d. Do not implement anything the plan does not name.

---

## BRANCH

ws4b is already MERGED into `feat/langgraph-core` (merge commit `70009b7e`). Branch off
`feat/langgraph-core`. **Do not commit to it directly, do not push, and do not open a PR without
asking.** When the work is done and reviewed the operator will merge it back locally, as with ws4a
and ws4b.

## READ FIRST, IN THIS ORDER

1. The skills: `.claude/skills/executing-plans-tellr/` **AND**
   `superpowers:subagent-driven-development`. Both, per the repo's `CLAUDE.md`. Not optional.
2. `docs/superpowers/plans/ws4b-HANDOVER.md` — carries what your plan PREDATES: the contracts you
   bind to, one whose signature DIFFERS from what your plan states, seven traps ws4b paid for, and
   the Lakebase facts that took three wrong turns to establish. **Read it before the plan.**
3. `docs/superpowers/plans/.ws4b-PLAN-CORRECTIONS.md` — 23 sections. **Treat §12, §15, §19, §20 and
   §23 as contracts you consume**, not as ws4b's private notes.
4. `ws4-START-HERE.md` and `2026-08-25-ws4-index.md` — what the workstream is for, and the
   conventions all five plans inherit and deliberately do not repeat.
5. `git show 70009b7e --no-patch` — ws4b's Definition-of-done obligations live in that merge commit
   rather than a PR description, including exactly what is frozen and what is not.
6. **The plan itself, end to end, before writing anything.** 946 lines, nine tasks C1–C9.

## BEFORE TASK 1 — the corrections pre-pass

Verify the plan against the code and write what you find to
`docs/superpowers/plans/.ws4c-PLAN-CORRECTIONS.md`, then point every task dispatch at that file
alongside the plan. Re-grep every `file:line` anchor your tasks depend on — ws4b moved
`session_manager.py` and `database.py` substantially, and the CI seed step's anchor has now been
wrong **three times**. On ws4a this pass produced six corrections; on ws4b it produced **twenty-
three**, two of which made the work smaller and several of which would otherwise have shipped a
defect transcribed straight from the plan. A stale anchor is a silent misfile, not an error.

## ENVIRONMENT — hard rules

- Use `~/.pyenv/versions/3.11.0/bin/python`. The in-tree `.venv` carries the pre-upgrade stack;
  never reach for it, never delete it.
- **Never `pip install`.** Shared pyenv site-packages; an install corrupts other agents' runs.
- **ws4c adds no dependency.** ws4b was the only one of the five that did. If a task thinks it needs
  one, stop and escalate.
- `src/core/database.py` calls `load_dotenv()`, so the operator's local `.env` leaks into test runs
  and an explicit env var overrides it. Measure anything touching a Databricks client with the CI env.
- `.claude/worktrees/` holds nine stale repo copies. An unfiltered repo-wide grep returns roughly
  **ten times** the real hit count. Scope to `src/ tests/ frontend/src/ scripts/ .github/`, or filter.

## BASELINE — re-derive it, and compare CAUSES never counts

`docs/superpowers/baselines/pr3_ws4_collected.log` **Section 2b** is your baseline:
`3 failed, 4578 passed, 8 skipped, 4589 collected` — two causes, exact assertion strings in the file.
C8 moves `agent_factory` and C7 re-homes two security controls, so you fall inside that file's own
re-derivation rule: **re-measure and add a Section 2c** rather than comparing to a stale figure.

Two traps it spells out: the deploy-autoscaling cause raises **two different assertion strings**, so
never grep for one; and "no test stopped existing" cannot be checked by a count, because N deletions
plus N additions preserve it — diff the test tree for removed `def test_` lines. Ruling **R1** means
irrelevant tests are DELETED, not migrated or left red, and every deletion must be **named in its
commit**.

## THE CONTRACTS ARE FROZEN — you escalate, you do not edit

`src/domain/finding.py`, `deck_spec.py`, `skill_io.py`, `frontend/src/types/finding.ts` and the
fixture surfaces in both conftests were frozen by ws4b. **If you need a field that does not exist,
that is an escalation to the operator — not a local edit.** Three of the review loop's blocking
findings came from exactly that going wrong. Two specifics:

- **`deck_review_store`'s signatures differ from what your plan says** (§19). It ships
  `save_deck_review(db, deck_id, digest, findings, author=None)` and
  `get_deck_review(db, deck_id, digest)`. The plan's `session_id`-taking forms do not exist. §19
  carries the call-site recipe.
- **`get_slide_deck` has THREE dict-returning read paths, not two** (§23). Your plan, like ws4b's,
  describes two.

## TESTS — sabotage-verify every one

Break the production line the test guards, confirm it goes red FOR THE RIGHT REASON, and confirm
your sabotage landed on the executed path. Verify the sabotage still imports cleanly before
believing any red — a `SyntaxError` reddens everything for the wrong reason.

**The commonest defect in ws4b was not broken code. It was a test, name or docstring asserting more
than it could observe.** Six instances: a guard test that re-implemented the guard it was meant to
prove; a coverage test that passed against an empty directory; an order assertion satisfied by
silent stubs; two tests whose kwarg was discarded by pydantic's `extra='ignore'` before it reached
anything; a class named for the migration when it tested the ORM declaration; and a fixture
docstring instructing a future author how to reconstruct removed behaviour.

**Assign every reviewer a sabotage target its implementer has not used, and require it to say
plainly when nothing goes red.** On ws4b, six of sixteen tasks had their defect found only by that
outside sabotage.

## RULINGS YOU ARE MOST LIKELY TO VIOLATE

- **R2** — the graph COPIES what it needs. `src/services/agent.py`, `src/core/prompt_modules.py` and
  `src/services/design_system_compiler.py` are **never modified**. Reading and importing is fine,
  private names included. Your one recorded exception is importing `UNTRUSTED_DATA_NOTICE`. Do not
  widen it.
- **`Send(timeout=)` is unusable.** The parameter EXISTS on `Send` in langgraph 1.2.10 — a scout
  "corrected" ws4b's plan on that basis and was wrong — but a compiled graph fanning into a **sync**
  node raises `ValueError: Node timeouts are only supported for async nodes because sync Python
  execution cannot be safely cancelled in-process.` Stall detection must use state-recorded
  timestamps. **This decides C2 and C4.**
- **A compiled-graph test fixture MUST be file-backed SQLite.** `StaticPool` with
  `sqlite:///:memory:` hands two Pregel worker threads the same connection and **segfaults the
  interpreter** — reproduced 3 of 3 runs. **This will bite C5.**
- **Undeclared keys are silently dropped.** Treat `GraphState` as the exhaustive contract it is;
  this caused three separate blocking findings in review.

## WHERE THE TIME WILL GO

Nine tasks. Three real risks:

- **C4** is the largest — nodes, routers, assembly, the emitter lifecycle, and where the deck-level
  write's values come from. It also tells you to **delete `reviewer_router`** (finding 14:
  specified, tested, never wired — its return values match no node name).
- **C5** runs layer-1 tests against the **COMPILED** graph. Read the index's verified runtime facts
  before writing them; the superstep barrier and `Send` payload semantics broke three plan drafts.
- **C8 moves `agent_factory`** rather than deleting it. Thirteen files reference `src.services.agent`
  and must still collect and pass where they are — **nothing moves** (finding 15's other half).

Your carry-forward findings are **10, 14, 15 (the repointing half), 17, 21, 24, 28**. Each is a
named item in your plan; check you have discharged every one.

## TWO ws4b FOLLOW-UPS THAT WILL TRIP YOU

- **`FindingLevel` is declared and never consumed.** Nothing checks that a deck-level finding carries
  `slide_index == -1`, and `SlideViewer.tsx` filters findings by index — so deck-level findings are
  currently invisible and `-1` lands in the unseen set. If your deck reviewer emits them, decide this
  deliberately rather than discovering it.
- The **legacy read path** returns five of the writer's eight columns and spells one key differently.
  Six further follow-ups are named in `git show 70009b7e --no-patch`.

## IF YOU DISPATCH SUBAGENTS

- **No git commands in an implementation or fix agent**, not even read-only ones. `git show HEAD` in
  a shared tree once destroyed a sibling agent's uncommitted work. **You** do the committing.
- Give parallel agents **disjoint file sets, stated explicitly**. Name the other agents' files in
  each brief so nobody has to guess.
- **INLINE the precedent rather than naming it.** Three ws4b agents stalled, every one mid-
  exploration and never mid-writing — each had been told to "follow the existing pattern" and left
  to go and find it. Read the pattern once yourself and paste it into the brief.
- **Re-probe every external-state fact an agent volunteers.** ws4b caught three fabrications stated
  as measured: a driver behaviour that did not hold, a method that would "raise at run time" and does
  not, and a plan claim about a parameter. One of the three the controller propagated into code
  without checking, because it arrived as a *concern* rather than a claim.
- **Check merges by CONTENT, never by commit identity.** `git merge-base --is-ancestor` reported work
  as unmerged when the code was fully present, squashed in. Use `git log -S` or a grep.
- **A stalled agent's work is usually salvageable.** Inspect the tree, run the tests, read the diff
  before re-dispatching. On ws4b that saved substantial work four times.

## LAKEBASE AND THE DEV LOOP — it works, and ws4b proved it

`db-tellr` is a Lakebase **PROJECT**, not a provisioned instance. `databricks database
get-database-instance db-tellr` returns "Resource not found" and that is **not** an absence. Use
`databricks postgres list-projects` / `list-branches` / `list-endpoints`.

If your DoD needs a live deploy: `gh auth switch --user robertwhiffin` first (the EMU token gets
HTTP 403 on workflow dispatch), then `gh workflow run publish-dev.yml --ref <branch>`, then
`./scripts/deploy_local.sh create --env devloop --instance <id> --profile tellr-dev --from-pypi
<version>`, confirm RUNNING, and `delete` to tear down. **Ask before pushing or publishing.** PyPI
is blocked from this laptop, so a local curl returning 503 is not a publish failure — and the
publish can partially succeed, so check both packages. **RUNNING is the plan's proof that migrations
applied — but query the schema directly rather than trusting the inference.**

## DONE

The plan's own **Definition of done** is the bar. Do not infer one, and do not report completion with
items outstanding — say what is left and why. CI has still never run ws4a or ws4b to completion, so
if a DoD item genuinely needs a CI observation, say so rather than declaring it met.

**Ask before deciding anything that belongs to the operator. Probe, don't infer: if a fact about the
code or the environment matters, measure it rather than reasoning about it.**
