---
name: executing-plans-tellr
description: Use when executing any written implementation plan in this repo via subagents, when resuming a chained build, or when reviewing work a subagent produced here. Runs a plan in chained mode (a thin top-level session dispatches a pre-pass, one Opus supervisor per task and a final agent that opens the PR, with the state in a ledger on disk) or single-session mode (one coordinating session); 'Choosing the mode' sets the default. Adds Tellr's hard-won practices to superpowers:subagent-driven-development — sabotage-verification of every test, a plan-vs-code corrections pre-pass, cause-based baselines, and re-probing subagent claims. Triggers on "execute this plan", "build PR from plan", "subagent-driven development", "run the plan", "continue the build in".
---

# Executing Plans in Tellr

Load this **with** `superpowers:subagent-driven-development`, not instead of it. These are
the practices that earned their cost across a 13-task, ~30-subagent build (agentification
PR1 + PR2, both merged 2026-08-12), and which that skill does not currently cover.

Kept as a project skill rather than edited into the plugin: the plugin lives in a
version-pinned cache that upgrades overwrite, and several of these practices reference
Tellr's specific layout (per-worktree uv venvs, app-wheel BUILD path, live-Postgres test
suites).

## Choosing the mode

**Default mode: chained.**

A plan overrides the default with a header line, `Execution: chained` or
`Execution: single-session`. A plan without the line gets the default.

- `single-session`: §1–§9 as written, with one coordinating session doing the controller's
  work for the whole build.
- `chained`: §10. §1–§9 still apply inside its stages. Where they say "controller",
  "orchestrator" or "I", read the stage running them: the pre-pass for §2, the task
  supervisor for its task, the final agent for §7.

**If you are the top-level of a chained build**, your whole job is §10's "The top-level"
and "Resume". You use three tools: Agent, Read of this file and its brief templates, and
two greps: the plan's `Execution:` line before the pre-pass (§10 "The top-level", step 0)
and the resume grep. Navigate this file with Read alone, not shell. **Never Read the
ledger, not even on a resume to orient yourself:** the resume grep is your only view of
it, and each stage reads the ledger itself.

Reverting:

- For one build, edit its plan's `Execution:` line.
- For every build, change the default line above to `single-session`.
- For the whole skill, `git revert -m 1 <this PR's merge commit>`. Or restore the skill's
  text from before chained mode with
  `git restore --source=executing-plans-tellr/single-session-v1 -- .claude/skills/executing-plans-tellr/SKILL.md`,
  delete the three brief files beside it, and drop the `Execution:` paragraph from
  `CLAUDE.md`.

Measuring: `uv run python -m scripts.build_metrics report` prints every chained build (each
final agent writes its record into its PR body) beside the single-session baseline. It
shows time and cost to handover and edits after it. The user reads it and decides which
mode stays. There is no threshold and no automatic switch.

## 1. Sabotage is the only proof a test works

The skill's reviewer prompt has no falsification step. Add one to every review dispatch:
**break the production line the test guards, confirm the test goes red, restore, confirm
green, paste the real output.**

This found defects nothing else did:

- a migration idempotency test that stayed green with the migration disabled (it called
  `create_all()`, which builds the new columns from the ORM, and never dropped them — so it
  tested `create_all`, not the migration)
- a dry-run test that could not detect a leaked write (`autoflush=False` hid unflushed rows
  from its `count()`)
- an equivalence test comparing hand-picked keys, so corrupting a per-slide field left all
  13 tests green

**Verify the sabotage took effect.** A sabotage that misses its target is indistinguishable
from a test that cannot fail. I once patched a line *inside* the `if` guard that was the
actual fix — nothing changed, and I nearly reported a working guard as fake. Grep for your
marker and confirm it sits on the executed path.

**Assign different sabotage targets to the controller and the reviewer.** Overlap wastes a
round; divergence finds more. Tell the reviewer explicitly which ones you already ran.

## 2. Run a plan-vs-code pre-pass before Task 1

Before dispatching anything, verify the plan's claims against the actual code and write a
corrections file (`PLAN-CORRECTIONS.md`) that **explicitly overrides the plan**. Point every
implementer and reviewer dispatch at it.

On a 2,000-line plan this produced 13 corrections, and roughly half the tasks would
otherwise have shipped a defect transcribed straight from the plan's own inline code:

- a model definition with both `index=True` and an explicit `Index(...)` of the same
  generated name — crashes `create_all()` for the whole repo
- an invented `save_slide_deck` signature; following it would have silently destroyed
  author-stamping and changed the return type
- two export functions that do not exist (`build_pptx`, `build_google_slides`)
- a `from src.core.database import engine` that is not a module symbol
- a dry-run path that still mutated the database

Also pre-brief the **known** bugs in a task's inline code. An implementer told "these five
things are wrong, fix them" fixes them; one told nothing transcribes them.

## 3. Baselines are cause-sets, not counts

Record the failing-test *causes*, not the number, and diff causes on every regression check.
A 13→13 count collision hid a genuinely new breakage for seven consecutive tasks and
propagated a wrong attribution into ~7 dispatch briefs. Re-derive the baseline after any
schema, ORM or dependency change — those are exactly what mutate a cause while preserving
the count. See [[verify-by-cause-not-count]].

## 4. Re-probe every external-state fact a subagent volunteers

Five fabrications across four agents in one session, all about state that is slow to check:
a nonexistent HTTP 403, a package version that did not exist, two "forced by a resolver
conflict" claims that resolved fine, and a dependency upper bound that is absent from the
wheel metadata. **I relayed one to the user before probing it** — don't.

Fabrications cluster on remote state (a package proxy, an API) where the agent assumes you
won't re-run the slow command. They are cheap to falsify; all five were caught within
minutes. A claim repeated by three agents is still not evidence.

## 5. A stalled agent's work is usually salvageable

Agents die (watchdogs, closed laptops). Before re-dispatching: `git status`, grep for
leftover sabotage markers, run the tests, read the diff. Twice the work was complete and
correct but uncommitted — I verified and committed it myself, noting the stall in the
message. Re-dispatching would have discarded good work and re-run the whole task.

## 6. Sequence by file, parallelise by worktree

Tasks touching the same file must run sequentially even when the plan calls them
independent (three tasks all edited `session_manager.py`). Genuinely independent PRs get
their own git worktree.

**Check the Python environment first.** Each worktree gets its own uv-managed `.venv`
(`uv sync --extra dev` in the worktree root — sub-second from the warm uv cache). Run
everything through `uv run` so it resolves to that worktree's venv. Never `pip install`
into a shared interpreter — parallel agents corrupt each other's test runs and dependency
verification. A dependency change goes in `pyproject.toml` + `uv lock`, not an ad-hoc install.

## 7. The whole-branch review is where cross-cutting defects live

Per-task reviews cannot see them. The final Opus review found the session's worst defect —
four hand-copied row-writers had diverged, so a reorder attached slide identity and
verification verdicts to the wrong slide and silently lost verdicts. It also reversed one of
my own earlier rulings (I had accepted an implementer's argument against a shared-helper
refactor; the review showed five findings were instances of exactly that divergence).

Dispatch it on the most capable model, hand it the ledger's deferred/parked list, and ask
explicitly for: a writer-by-writer comparison table, a rollback-guarantee ruling, and a
merge/no-merge verdict.

## 8. Ledger everything, and expect to be wrong in it

With ~30 agents and two mid-session deaths the ledger was the only reliable state. Record
rulings, parked findings, **and your own corrections** — including where the ledger itself
was wrong. Mine carried a wrong baseline attribution for seven tasks; the correction is now
the most useful entry in it.

## 9. Tier the model to the task

Capability goes where a mistake is silent or expensive; speed goes where the plan has
already removed the judgment. The reviewer-as-asset logic is unchanged — what moves down is
the implementer, and partly the per-task reviewer.

**Every task carries a `Models:` tag; an untagged task is not dispatched.** Fold the check
into the pre-pass (§2): a plan with any untagged task is a correction, not a run. The tag
sets two tiers; the rest derive.

```
Models: test=opus impl=haiku
```

- `test=` — writes the task's failing tests against its declared interface. **test ≥ impl,
  always:** never write the contract with a weaker model than the thing built against it.
  Lean Opus. A cheap test that hand-picks keys passes a broken implementation — the exact
  defect in §1, now moved upstream, so the test author must write BEHAVIOURAL assertions
  where gaming the test equals solving the problem.
- `impl=` — makes the tests green. Haiku for mechanical/transcription tasks where the plan
  gives the actual code; Sonnet where it sketches the approach but the code is real work;
  Opus for design judgment or a frozen/pinned artifact where a quiet mistake is costly.
- per-task reviewer = **impl + 1**, capped at Opus — a fast local gate, NOT the
  silent-defect net. That net is the whole-branch review (§7), which stays **Opus, always**;
  paying Opus on every per-task review buys little the final sweep won't catch.
- fixer = the per-task reviewer itself, for a `localised` verdict (it has the context and is
  already the right tier).

**Tests and implementation are authored by different agents, in that order.** The test
author writes the failing tests, confirms red, leaves them uncommitted. The orchestrator
then launches a cheap implementer with exactly this brief:

> "The failing tests are at `<path>`, red confirmed, uncommitted. Make them pass without
> weakening them. If you hit something you can't resolve, or you think a test is wrong, STOP
> and report — do not work around it and do not edit the test. A more capable model decides
> whether the test is actually wrong."

The cheap tier never authors a test, so it cannot write one that passes vacuously — the
clean fix for the Haiku-writes-its-own-trivial-test risk. The cost moves onto the test
author's behavioural-completeness job above.

**A stop escalates straight to Opus — not step-by-step — carrying the stopped agent's
context.** A stop means the cheap tier is out of road; a second cheap attempt is wasted
time. "The test is wrong" from a cheap tier is a DISTRUSTED claim (§4): it is not believed
until Opus has attempted the task and either passed it or confirmed the test wrong — the
cheap agent never rules a test broken. Before relaunching, read the stopped agent's partial
work (`git status`, the diff, its notes) and carry it forward; it is usually salvageable
(§5).

**The per-task reviewer emits one of three structured verdicts, never prose:**

- `approved` — no changes; move on.
- `localised` — a listed set of fixes; the reviewer applies them itself.
- `rewrite` — structurally wrong; a fresh Opus implementer rebuilds against the (good,
  already-written) tests. A `rewrite` also means the task's plan under-specified it —
  re-read it against §2 before the rebuild.

**The downgrade is a bet on plan quality (§2); ledger the rework rate per tier (§8).** A
cheap implementer that stops often makes you pay escalation + review every time and loses
the saving. Record rework rate by tier; if a tier's climbs, raise its default in the next
plan's tags. The rate is the only evidence the tiering is paying off.

Related: [[plan-review-lessons]], [[subagent-delegation-discipline]],
[[verify-by-cause-not-count]], [[model-tiering-for-plan-execution]]

## 10. Chained execution

A chained build is a chain of short-lived agents. Each stage starts from disk (the plan, the
corrections file and the ledger) and ends with a four-line verdict, so no context lives
long. The chain ends at the handover: a PR marked ready for review, or left as a draft if
anything is parked.

### Roles

| Stage | `description` (exact) | Model | Brief |
|---|---|---|---|
| Top-level: the user's session | — | any | — |
| Pre-pass | `Pre-pass` | Opus | `pre-pass-brief.md` |
| Task supervisor: one per task, in plan order | `Task <n> supervisor` | Opus | `task-supervisor-brief.md` |
| Final agent | `Final agent` | Opus | `final-agent-brief.md` |

The briefs sit beside this file. `scripts/build_metrics.py record --find <ledger>` costs
the sessions that name the ledger and dispatched a `Task <n> supervisor` or the
`Final agent`. It starts the build's clock at the first `Task <n> supervisor` dispatch
whose prompt names the ledger, and falls back to the first dispatch whose description names
a task. It ends the final review at the last agent whose description contains `final` or
`whole-branch`, not counting `Final agent`. So the pre-pass dispatches no agents, and the
final agent's §7 dispatch, `Final branch review`, is the only description in the chain that
contains either word.

### The top-level

After the user approves the plan, the top-level runs the chain and does nothing else:

0. Take the plan's `Execution:` line, from your context or with
   `grep -m1 '^Execution:' <plan>`. If it is `single-session`, or the plan has none and the
   default line in "Choosing the mode" says `single-session`, you are not a chained
   top-level: run the build per §1–§9. A resume skips this step; the pre-pass checks the
   line too.
1. Dispatch `Pre-pass`. After each verdict, dispatch the stage its `next` names:
   `task-<n>` → `Task <n> supervisor`, `final` → `Final agent`. When a verdict has
   `next=done` or `status=failed`, give the user that verdict and stop. `status=parked`
   is not a stop.
2. To dispatch a stage, Read its brief template (once: reuse it for later dispatches),
   replace every `{{…}}`, and send the result as the prompt, with the exact description and
   model `opus`. Use a fresh agent, never a fork: a fork inherits your context.
3. Dispatch exactly one stage at a time, and do nothing else until its verdict arrives: no
   other dispatch, no other tool call, no polling, no `sleep`, no reading its output file.
   If the user asks, say which stage is running. To wait:
   - By default, dispatch in the background and end your turn. The completion
     notification carries the stage's report, and its `VERDICT` lines are the verdict.
   - This works when the top-level is itself a subagent. Ending a turn does not end its
     run, and its child's notification wakes it. So a subagent top-level never gives its
     final answer, or calls its hand-back tool, while a stage is running.
   - If the harness runs the dispatch in the foreground instead, the call returns the
     stage's report.
   - If the harness offers neither, stop and tell your caller. Never dispatch the next
     stage without a verdict.
4. Read only verdicts. Never run tests, git or deploys, and never read diffs, transcripts,
   the plan or the ledger. The two exceptions are step 0's
   `grep -m1 '^Execution:' <plan>` and a resume's `grep '^NEXT:' <ledger> | tail -1`. Your
   only tools are Agent, Read of this file and the brief templates, and those two greps.
   Load no other skill: each stage loads `superpowers:subagent-driven-development` itself.
   If it is already loaded, leave its Setup, Task Loop and waiting rules to the stages.
5. A report with no `VERDICT` line means the stage stopped early. Dispatch a fresh agent
   for the same stage.

Fill paths absolute with `~` expanded, except `{{PLAN}}`:

| Placeholder | Value |
|---|---|
| `{{SKILL_DIR}}` | this file's directory |
| `{{PLAN}}` | the plan's path: relative to the worktree root when the plan is inside the worktree you are in, else absolute. The final agent passes the same string to `record` as `--plan`. |
| `{{LEDGER}}` | the ledger the user names, else `~/tellr-loop/<build>/LEDGER.md`, where `<build>` is the plan's file name without `.md`. Every stage brief carries it, so the final agent's `record --find <ledger>` finds the build's sessions and its first supervisor by it. |
| `{{CORRECTIONS}}` | `PLAN-CORRECTIONS.md` in the ledger's directory |
| `{{WORKTREE}}`, `{{BRANCH}}` | the git worktree that holds the plan, and its branch: your own directory and branch when the plan is inside it. Otherwise `(ledger header)`, and the pre-pass works them out from the plan's directory. Never give your own directory for a plan outside it. |
| `{{TASK}}` | the `<n>` of `next=task-<n>` |
| `{{PUBLISH}}` | `yes`. `no` for a smoke run: the final agent does §7 and its fixes, writes the handover to the ledger, and neither pushes nor opens a PR. |

Fill a value you do not know with `(ledger header)`, and the stage reads it there. On a
resume that is `{{PLAN}}`, `{{WORKTREE}}`, `{{BRANCH}}`, and `{{PUBLISH}}` unless the user
gave it. Never run a command or read a file to find a value.

### Resume

When the user says "continue the build in `<ledger>`", your first command is
`grep '^NEXT:' <ledger> | tail -1`. Don't Read the ledger before it or after it: the
stage you dispatch reads the ledger, and the values you lack are `(ledger header)`.
Dispatch the stage the grep names and carry on as above. If the shell refuses the pipe,
run `grep '^NEXT:' <ledger>` and take its last line.

Run nothing before the grep, not even an `ls`: the grep's own output covers every case.

- `NEXT: done`: the build is over. Say so.
- No `NEXT:` line: the pre-pass did not finish. Dispatch `Pre-pass`.
- `No such file`, in the grep's error: the build never started. Ask the user for the plan.

Resume only once the old top-level session has ended. Its running stage dies with it, and
two agents on one stage corrupt each other's work. A stage whose previous attempt died gets
a fresh agent of the same stage, which first does §5 salvage. The dead attempt left an
entry with a `Start:` line and no `NEXT:` line.

### The ledger

`{{LEDGER}}` is §8's ledger and the chain's only state. It lives outside git, so
`git clean` and removing the worktree leave it alone. The pre-pass creates it with this
header:

```
# Chained build ledger
Plan: <path>
Corrections: <path>
Worktree: <path>
Branch: <name>
Base: <HEAD when the pre-pass started>
Publish: <yes|no>
```

Each stage appends one entry. It writes the heading and `Start:` when it begins, and the
rest when it ends:

```
## <Pre-pass | Task <n> supervisor | Final agent>
Start: <UTC>
Tiers: <role=model for every agent dispatched, escalations included>
Verdicts: <review verdicts in order, or n/a>
Rework: stops <n>, fix rounds <n>, rewrites <n>
Ruling: <decision> — <why> — <cost if wrong>     (one line each, or "Rulings: none")
PARKED: Task <n> — <reason>                      (one line each, or "Parked: none")
Commits: <first-sha>..<last-sha> | none
End: <UTC>
NEXT: <task-<n>|final|done>
```

Other lines go between `Start:` and `End:`: baseline causes, sabotage output,
`Task <n>: minor (deferred): …` and `User check: …`. `NEXT:` is an entry's last line and
starts no other line. **The last `NEXT:` line in the ledger is the chain's state.** Never
edit an earlier entry. A correction is a new line in your own (§8). Times come from
`date -u +%Y-%m-%dT%H:%M:%SZ`.

### Commands in the stages

A stage runs every command in `{{WORKTREE}}`, but its shell may start somewhere else on
every call, and some sessions refuse commands with `$VAR`, `$(…)`, heredocs or pipes.

- Run plain commands. Give git `-C <worktree>`, and use absolute paths. Keep a value such
  as a SHA in your entry, not in a shell variable.
- The SDD scripts (`sdd-workspace`, `task-brief`, `review-package`) act on the repo of the
  current directory. If the shell does not start in the worktree, run
  `cd <worktree> && bash <script> …`. If that is refused, build the review package
  yourself: `git -C <worktree> log --oneline`, `diff --stat` and `diff -U10` over the
  range, redirected to one file in `<ws>`.
- Write the ledger and the corrections with the Write and Edit tools. Commit with
  `git -C <worktree> commit -m <subject> -m <trailer>`, not a heredoc.

### The stages

**Pre-pass.** §2, written to `{{CORRECTIONS}}`, plus these checks:

- The `Execution:` line. `chained` passes. A missing line passes only while the default
  line in "Choosing the mode" says chained, so the pre-pass reads that line. Anything else
  → `status=failed`.
- `Models:` (§9). An untagged task, or a tag with test below impl → `status=failed`,
  listing the tasks.
- A `Depends on:` line per task in `{{CORRECTIONS}}`, taken from the plan's order and
  parallelism section, so supervisors never infer dependencies. A task that needs a
  deploy, a browser or the open PR is marked `outside the chain`.
- The conflict scan, and the baseline failing-test causes (§3).

**Task supervisor.** It runs §9's pipeline on its one task:

- a test author at the `test=` tier, which leaves the tests red and uncommitted;
- the implementer at the `impl=` tier, given §9's brief verbatim;
- a reviewer at impl + 1, whose verdict is `approved`, `localised` (the reviewer applies
  its fixes) or `rewrite` (a fresh Opus implementer rebuilds);
- a stop escalates straight to Opus.

§1 sabotage uses the supervisor's own targets, run before the review. The reviewer is told
which ones were run and picks different ones. §3 and §4 apply as written. The supervisor
dispatches these agents itself, at depth 2–3. They land in the same session's `subagents/`
folder, where the metrics find them. It commits, makes and records the rulings a
coordinator would, and returns the verdict. §6 holds: the chain runs one task at a time, in
one worktree.

**Parking.** A supervisor that cannot proceed at all parks its task with the reason,
instead of guessing. Examples: missing access, an input the task names that does not
exist, a contradiction no ruling settles. Every supervisor then picks `next` from the tasks
after its own, in plan order. It skips a task that is `outside the chain` or whose
`Depends on:` names a parked task, and records each dependent it skips as parked in its
own entry. The first task it does not skip is `next`. If none is left, `next=final`.

**Final agent.** §7, dispatched as `Final branch review`, then one fix dispatch and one
scoped re-review. Then:

1. Rename a `worktree-<name>` branch to `feat/<name>`. Push as `robertwhiffin`, after
   checking `gh auth status`. Never use the EMU account.
2. `gh pr create --draft`. CI runs only on pull requests, so the PR must exist first.
3. Wait on `gh pr checks --watch`, and fix red CI inside the chain, for at most 3 fix
   rounds. A check still red after them is parked.
4. Once CI is green, or every red check is parked, run
   `uv run --directory <worktree> python -m scripts.build_metrics record --pr <n> --plan <plan> --find <ledger>`,
   and put the block it prints into the PR body. The body also carries the handover: every
   ruling, every parked item, the `Parked-task: <n>` commit trailer to use when finishing
   one, what waits on the user (browser check, devloop deploy, merge), and that the branch
   takes `main` by a merge, not a rebase, after handover.
5. `gh pr ready <n>`, unless anything is parked, in which case the PR stays a draft. This
   is the handover, which the metrics measure from.
6. Write `NEXT: done`.

With `{{PUBLISH}}=no`, steps 1–5 become writing the handover into the ledger. There is no
devloop deploy either way. Instances and the `.devN` counter are shared with other
sessions, and a fix after a deploy should count as a miss.

### The verdict

Every stage's final message is exactly these four lines, and nothing else. Where the
harness has a hand-back tool, the message goes through it.

```
VERDICT stage=<pre-pass|task-<n>|final> status=<done|parked|failed> next=<task-<n>|final|done>
commits: <first-sha>..<last-sha> | none
summary: <one line>
rulings: <one line, or "none">
```

- `status=done`: the stage did its job. `parked`: the supervisor's own task is parked or,
  for the final agent, the build has parked items and the PR stays a draft. `failed`: the
  chain stops for the user.
- A supervisor parks rather than fails. It fails only when it cannot leave the worktree
  committed and clean. The final agent fails only when it cannot push as `robertwhiffin`
  or open the PR.
- `next` equals the entry's `NEXT:` line. A failed supervisor or final agent names its own
  stage, so a resume re-runs it once the user has fixed the cause. A failed pre-pass
  returns `next=done` and writes no `NEXT:` line, so a resume re-runs the pre-pass.
- `commits`: the stage's own first and last commit as short SHAs, the same SHA twice for
  one commit.
