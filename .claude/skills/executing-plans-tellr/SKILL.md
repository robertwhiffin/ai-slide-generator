---
name: executing-plans-tellr
description: Use when executing any written implementation plan in this repo via subagents, or when reviewing work a subagent produced here. Adds Tellr's hard-won practices to superpowers:subagent-driven-development — sabotage-verification of every test, a plan-vs-code corrections pre-pass, cause-based baselines, and re-probing subagent claims. Triggers on "execute this plan", "build PR from plan", "subagent-driven development", "run the plan".
---

# Executing Plans in Tellr

Load this **with** `superpowers:subagent-driven-development`, not instead of it. These are
the practices that earned their cost across a 13-task, ~30-subagent build (agentification
PR1 + PR2, both merged 2026-08-12), and which that skill does not currently cover.

Kept as a project skill rather than edited into the plugin: the plugin lives in a
version-pinned cache that upgrades overwrite, and several of these practices reference
Tellr's specific layout (shared pyenv env, app-wheel BUILD path, live-Postgres test
suites).

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

**Check the Python environment first.** If it is a shared interpreter rather than a
per-repo venv, bar every agent from `pip install` — otherwise parallel agents corrupt each
other's test runs and each other's dependency verification.

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

Related: [[plan-review-lessons]], [[subagent-delegation-discipline]],
[[verify-by-cause-not-count]]
