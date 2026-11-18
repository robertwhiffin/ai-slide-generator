# Chained plan execution — design

Date: 2026-11-13. Status: draft for review.

Decisions are marked **(decided)** when the user made them, and **(my call)** when the
designer made them and the user has not yet confirmed them. Unmarked text describes how
things work today.

## Intent

The user starts a piece of work interactively (conversation, design, plan with `Models:`
tags, approval) and then leaves the agent to build it unattended. What they want to come
back to is **a finished, open PR** **(decided)**, not a long session to scroll through.

Today the whole build runs inside one long coordinating session. That session is the
single biggest cost, and it is expensive because of its length, not its model mix:

- Since 16 Oct 2026 (the start of transcripts on this laptop), estimated spend at list
  prices was about $3,200. The coordinating sessions the user talks to were 32% of it;
  supervisors, plan-vs-code pre-passes and planners another 14%. Per-task reviews were
  19%, Opus test writing 18%, implementation only 9%, final branch reviews 5%.
- Every turn re-reads the whole context. The median coordinator turn re-read 282k tokens
  (p90 671k), and 73% of coordinator input came from turns past 300k. Cost grows roughly
  with the square of session length; the 10 longest sessions were 67% of coordinator
  spend, the longest 1,127 turns.
- What fills the coordinator's context, weighted by how often it is re-read: its own
  reasoning and writing 41%, commands it runs itself (tests, git, deploys, logs) 25%,
  fixed start-up context 10%, the user's messages 8%, skills 4%, file reads 4%, and
  dispatching subagents plus their reports only 3%.

So delegation is cheap for the coordinator; long life and hands-on work are what cost.
The fix is to run the build as **a chain of short-lived contexts** whose state lives on
disk, ending at an open PR. **(decided)**

The user is happy with today's quality, in particular with the decisions the agent makes
on its own. The change must be measurable and reversible in case that slips. **(decided)**

## Goals

1. Lower **cost to an open PR**.
2. Same or shorter **time to an open PR**.
3. No rise in **edits after the PR is opened**: the open PR is the build's end state, so
   anything that happens to the branch afterwards counts as a fix or a miss. This is the
   objective quality test. **(decided)** (Precisely: after the handover, defined under
   Measuring.)
4. **Reversible** per plan with one line, and globally with one line or a git revert.
   **(decided)**
5. **Measured** by a script that lives in the repo, so the numbers survive a laptop move
   (the previous version of this working practice lost its notes that way). **(decided)**

## Non-goals

- **Time to merge.** Builds finish overnight and wait days for the user; it measures the
  user, not the build. **(decided)**
- **Changing the model tiers of §9.** The Opus test author stays: tests are the
  guardrails, and they must be legitimate behavioural tests, not everything mocked.
  **(decided)** The per-task reviewer also stays at impl + 1 for now, so that this change
  is measured on its own; dropping it to the implementer's tier is a later, separate
  experiment. **(my call)**
- **Splitting the hotspot files** (`src/services/graph/nodes.py` 7.6k lines,
  `src/api/services/session_manager.py` 4.5k, `src/api/services/chat_service.py` 4.3k,
  `frontend/src/services/api.ts` 2.7k — each touched by 8–15 of 58 PRs since October).
  That is about speed and merge conflicts, a separate project. **(my call)**
- **Conversational sessions** (the deck-comparison loop, prod investigations) where the
  user is in the loop anyway. **(my call)**
- **Running tasks in parallel.** v1 keeps today's task order. Parallel tracks in
  separate worktrees are a follow-up once the chain is measured. **(my call)**

## Anti-goals

- The agent's decisions get worse and the user starts overriding them.
- Tests get weaker (the cheap tier still never edits a test; §9 is unchanged).
- Build state is lost when an agent dies, because a fresh context had nothing to pick up.

## Design

### Two named modes

The skill describes both ways of running a build:

- `chained` — the new way, described below.
- `single-session` — today's way, kept word for word.

The skill states the **default mode in one line**. A plan may override it with a header
line `Execution: chained` or `Execution: single-session`. Reverting for one build is
editing that plan line; reverting for all builds is flipping the default line. The
commit before the change is tagged so the whole skill can be restored. **(decided in
principle; tag name my call)**

### The chain

1. **Top-level session** (the one the user talked to). After plan approval it stays thin:
   it dispatches each stage below as a fresh agent, waits for a short verdict, and
   dispatches the next. It does not run tests or commands, read diffs, or re-read the
   ledger. It holds only the verdict lines. **(my call)**
2. **Pre-pass agent.** Runs §2 (plan-vs-code corrections, `Models:` tag check, and now the
   `Execution:` check) and writes `PLAN-CORRECTIONS.md`. Today the coordinator does this
   inline. **(my call)**
3. **One task supervisor per task, sequential.** A fresh agent that reads its task's
   section of the plan, the corrections file and the ledger, then runs today's per-task
   pipeline unchanged: test author → red confirmed → implementer → reviewer (structured
   verdict) → escalation on a stop → sabotage of its own targets → commit. It makes the
   rulings the coordinator makes today, records them in the ledger, and returns a verdict
   of a few lines. It runs on Opus, because it carries today's coordinator judgment; it is
   short-lived, so its context stays small. **(my call)**
4. **Final agent.** Runs the whole-branch Opus review (§7) and its fixes, pushes the
   branch as the personal GitHub account, and opens the PR **as a draft**. CI
   (`.github/workflows/test.yml`) runs only on pull requests to `main`, so the PR has to
   exist before CI can run. The final agent fixes any red CI inside the chain, then marks
   the PR **ready for review** and writes the PR body with the handover: rulings made,
   parked items, and what is waiting on the user (browser check, devloop deploy, merge).
   **Marking the PR ready is the handover, and the point every metric is measured
   from.** **(decided: end state is an open PR; draft-until-green and the rest my call)**

Pushing the branch and opening the PR are authorised as part of the chain **(decided)**.
Deploying to a devloop instance is **not** part of the chain: devloop instances and the
`.devN` counter are shared with other sessions, and anything fixed after a deploy counts
as a miss, which is what the metric should see. **(my call)**

### When a task gets stuck

A task supervisor decides what today's coordinator would decide, and records the ruling.
If it cannot proceed at all (missing access, a contradiction in the plan), it **parks** the
task with the reason, later tasks that depend on it park too, and independent tasks carry
on. Dependencies come from the plan's existing order-and-parallelism section; the pre-pass
writes them out explicitly in `PLAN-CORRECTIONS.md`, so supervisors never infer them. No
new plan tag. A build with parked tasks still gets its final agent, but the PR **stays a
draft** listing the parked items. The handover is when the final agent finishes, and
later work on parked items counts as edits after handover, reported separately as
"parked" so it can be told apart from misses. **(my call)**

### The ledger is the state

Every stage starts from disk: the plan, `PLAN-CORRECTIONS.md`, and the ledger. Each task
supervisor writes, at minimum: task, tiers used, verdicts, rework (stops, fix rounds,
rewrites), rulings, parked items, commit range, and when it started and ended. The ledger
also records the chain's **next action**, so the chain can be resumed **from disk alone**:
if the top-level session dies (laptop closed, session ended), the user opens a new
session and says "continue the build in `<ledger>`". A dead agent's task is resumed by a
new supervisor from its entry plus `git status` (§5). Exact format: builder's choice.
**(my call)**

## Measuring

Three numbers per build. **(decided)**

| Measure | From | To |
|---|---|---|
| Time to handover | first task dispatched | handover |
| Cost to handover | first task dispatched | handover (all sessions and subagents, by model, at list prices) |
| Edits after handover | handover | merged: non-merge commits, lines changed, and their share of the PR's lines; parked-item work reported separately |

**Handover** means the same thing for old and new builds, so the comparison is fair
**(my call)**:

- **Chained builds:** the PR is marked ready for review (or, for a parked build, the
  final agent finishes). Final-review fixes and CI fixes fall before it.
- **Baseline builds:** the later of PR opened and the final branch review agent
  *returning* (from its transcript), so final-review fixes fall before it too. Fixes for
  red CI after the PR opened fall after it, a small bias against the baseline.

For chained builds the script also reports edits after the final review returned, so the
two endpoints can be compared directly.

**Overrides** stay the user's judgement rather than a number: there is no baseline count
to compare with, and an override that changes code already shows up as an edit after
handover. The PR handover lists every ruling the chain made, so the user can see what
was decided; "this feels worse" is a revert trigger on its own. **(my call)**

The script reads the Claude Code session transcripts (`~/.claude/projects/…`, where each
subagent has a `.meta.json` with its description and model) and GitHub (PR open time,
commits). Its results must be stored somewhere that survives a laptop move. Internals,
location and output format: builder's choice. The throwaway scripts used for this design
are in `~/tellr-loop/chained-plan-execution/model-audit/` and can be read for the parsing
details (`attrib.py`: cost by what entered the context; `builds.py`: per-build time and
cost; `baseline.py`: edits after the final review).

### Baseline

Measured on eight recent single-session builds. Today the PR is opened at inconsistent
points (sometimes before the final branch review, sometimes 16 h after). These
first-pass figures use the **dispatch** of the final branch review as the end point,
which overstates the misses slightly because it includes the final review's own fixes.
The script recomputes them to the handover definition above.

| PR | Edits after final review |
|---|---|
| #359 admin permissions | 0 commits, 0% of lines |
| #384 agent-mode MCP | 1 commit, 2% |
| #356 deck style | 5 commits, 3% |
| #385 interrupt generation | 2 commits, 4% |
| #360 Gateway MCP | 2 commits, 5% |
| #351 edit operations | 3 commits, 12% |
| #347 engine toggle | 4 commits, 12% |
| #354 Genie One | 9 commits, 26% |

Median about 2–3 commits and 4–5% of lines. Build time (first task to final review)
median about 8 h wall-clock, range 3.5–28 h. Build cost median about $50, range $24–126.

### When to revert

**The user decides, by hand.** **(decided)** There is no automatic switch and no
threshold in the skill or the script. The report puts each chained build next to the
baseline builds; the user reads it and flips the default line (or a plan's
`Execution:` line) when they judge it right.

## Constraints

- Nested agents work in this harness: transcripts show subagents at spawn depth 2 and 3
  (the overnight batch's per-issue supervisors dispatched their own agents). The chain
  relies on this.
- Repo conventions still apply: per-worktree uv `.venv` via `uv sync --extra dev`, never
  `pip install`; every plan task carries a `Models:` tag; the personal GitHub account,
  never EMU; worktree rules in `CLAUDE.local.md`.
- `CLAUDE.md` points at the skill and describes the `Models:` tag; it must also mention
  the `Execution:` line.

## Left to the builder

- The skill's wording and structure, including how `single-session` text is preserved.
- The verdict format between stages, and the ledger format beyond the minimum above.
- The measuring script's internals, location and output.
- Whether to pressure-test the changed skill per `superpowers:writing-skills`.
