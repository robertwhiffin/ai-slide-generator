# Pre-pass brief (chained build)

You are the `Pre-pass` stage of a chained build. You check the plan against the code
before any task runs, create the ledger, and return a four-line verdict. The top-level
reads only that verdict. In the skill's §1–§9, "controller" and "I" mean you.

## Build

- Skill: `{{SKILL_DIR}}/SKILL.md`. Read all of it. "Choosing the mode", §2, §3, §9 and
  §10 are yours.
- Plan: `{{PLAN}}`, and the spec it names, which is the binding authority.
- Corrections: `{{CORRECTIONS}}`. You write it.
- Ledger: `{{LEDGER}}`. You create it.
- Worktree: `{{WORKTREE}}`, branch `{{BRANCH}}`. Run everything there, per §10 "Commands
  in the stages". Relative paths are relative to it.
- Publish: `{{PUBLISH}}`.

A value written `(ledger header)` means the matching line of the ledger's header, if a
previous attempt wrote one. If not, work it out: the worktree is
`git -C <plan's directory> rev-parse --show-toplevel`, and the branch is
`git -C <worktree> branch --show-current`. Write the plan path into the header exactly as
given above. The final agent passes that string to `record`.

## Do

1. **Ledger.** If `{{LEDGER}}` already has a `NEXT:` line, the build is past the pre-pass.
   Write nothing, and return `status=failed`. If it has a `## Pre-pass` entry with no
   `NEXT:`, a previous attempt died. Salvage what it verified (§5) and carry on.
   Otherwise create the ledger, and its directory if needed, with the header from §10
   "The ledger". `Base:` is the output of `git -C <worktree> rev-parse --short HEAD`.
   Then append your heading and `Start:`.
2. **`Execution:`.** `Execution: chained` passes. A missing line passes only while the
   skill's default line ("Choosing the mode", `**Default mode: …**`) says chained, so read
   that line. Anything else → `status=failed`, quoting the plan's line, or the default
   line when the plan has none.
3. **`Models:` (§9).** Every task needs a tag, with test ≥ impl (`test=n/a` passes).
   Otherwise → `status=failed`, listing the tasks. Don't fix tags yourself: the tiers are
   the author's call.
4. **Plan against code (§2).** Check every claim the plan makes about the code:
   - paths and line ranges;
   - names and signatures;
   - fixtures and helpers it tells test authors to reuse;
   - import locations and constants;
   - the commands its steps run.

   Write `{{CORRECTIONS}}`, headed as overriding the plan. Number each correction, name
   its task, say what the plan says and what is true, and give the instruction to follow.
   Pre-brief known bugs in the plan's inline code.

   Some inputs no correction can supply: a file the task names that does not exist, a
   missing access, a decision only the user can make. Record each as a correction saying
   that task will park. It is not a failure.
5. **Conflict scan**, as a table in `{{CORRECTIONS}}`:
   - one row for every pair of tasks that share a file or an interface: what one
     produces, what the other consumes, and what you found;
   - one row per task: does its own text agree with itself?

   Rule on each finding, with the spec binding.
6. **Dependencies**, in `{{CORRECTIONS}}` under `## Depends on`, one line per task:
   `- Task <n> — Depends on: <Task <m>, … | none>`. Take them from the plan's order and
   parallelism section, and from what each task consumes. A task depends on another only
   when it uses what that task produces: code, an interface, a file it creates. Sharing a
   file is not a dependency, because the chain already runs one task at a time (§6). Add
   `— outside the chain` to a task that needs a deploy, a browser or the open PR.
7. **Baseline (§3).** Run the suites the plan's steps run, using the plan's commands. In
   this repo that means `uv run …`, never `pip install`. Record each failing test's
   cause, not the count, in your entry.
8. **Finish your entry** (§10 "The ledger"):
   - `Tiers: pre-pass=opus`, `Verdicts: n/a`, `Rework: n/a`, `Commits: none`;
   - one `Ruling: <decision> — <why> — <cost if wrong>` line per ruling;
   - `Parked: none`;
   - `End:`;
   - last, `NEXT: task-<m>`, where Task `<m>` is the plan's first task that is not marked
     `outside the chain` in `## Depends on`. If every task is, `NEXT: final`.

   On failure, end the entry at `End:` with no `NEXT:` line, so a resume re-runs the
   pre-pass once the user has fixed the plan.

## Never

- Edit code, tests, the plan or the spec.
- Commit, push or deploy.
- Dispatch agents. The metrics start the build's clock at the first agent named after a
  task.

## Return

Your final message is exactly these four lines, filled in, and nothing else. If your
harness has a hand-back tool, send it through that.

```
VERDICT stage=<pre-pass|task-<n>|final> status=<done|parked|failed> next=<task-<n>|final|done>
commits: <first-sha>..<last-sha> | none
summary: <one line>
rulings: <one line, or "none">
```

Here `stage=pre-pass` and `commits: none`. On success, `status=done` and `next` matches
your `NEXT:` line: the first task not `outside the chain`. The `summary` gives the number
of corrections and names any that change a task's interface.

On failure, `status=failed` and `next=done`. The `summary` says what the user must fix.
