# ws4 implementation — START HERE

Written 2026-09-10, at the end of the planning phase. Read this before the plans.

## 1. Five decisions are OPEN and they block ws4c/ws4d/ws4e

`ws4_seam_findings.md` § **OPEN — judgment calls for the human**, items **S1–S5**. They are
contract holes, not polish. Building ws4c past S1/S2 wastes work:

- **S1** `invoke_graph(session_id, initial)` has no slot for ws4d's event queue *or* the turn's
  principal — and ws4d runs the graph on a bare `threading.Thread`, which does not carry the
  identity ContextVar, so every graph row insert lands `modified_by` NULL.
- **S2** `resolved_style` has a consumer, a payload slot and a three-case test, and **no producer**.
- **S3** deck-level findings have a writer and no reader — no caller, no route, no event type.
- **S4** ws4c's layer-1 suite runs in **no CI job**.
- **S5** ws4e's "review in progress" flag has no data path.

**ws4a and ws4b are unblocked by all five.** Start there while these are settled.

## 2. Order, and why

**ws4a → ws4b → ws4c → ws4d → ws4e.** Not arbitrary:

- **ws4a first** because it *Blocks ws4b* — B3.3's `aggregate_deck_css` needs A1's at-rule-preserving
  `merge_css`, which exists on no other branch. ws4a also owns creating and committing
  `docs/superpowers/baselines/pr3_ws4_collected.log`; **nothing downstream can compare by cause until
  it lands**, and that directory does not exist yet.
- **ws4b second** because it freezes every contract the rest consume. This is what removes the
  escalation class of defect: ws4c cannot invent a schema field.

## 3. Required reading order, per plan

1. `.claude/skills/executing-plans-tellr/` **and** `superpowers:subagent-driven-development` — both,
   per the repo's `CLAUDE.md`. Not optional.
2. `2026-08-25-ws4-index.md` — the shared conventions every plan inherits. Never skip it; the plans
   deliberately do not repeat it.
3. This directory's `README.md` — two decisions were **reversed on evidence**; older text is wrong.
4. The plan itself, plus its unapplied residue: **~3 of ws4d's and ~7 of ws4e's round-1 findings**
   (in `ws4_r1_cde_findings.md`) are the only known-unfixed items in the set.

## 4. Do a corrections pre-pass before Task 1

Verify the plan against the code and write
`docs/superpowers/plans/.ws4<x>-PLAN-CORRECTIONS.md` before implementing anything, then point every
dispatch at it. On the last build roughly **half the tasks would have shipped a defect straight from
the plan's own text** without this. Re-grep every `file:line` anchor — the index lists the ones ws4a's
insertions shift, and warns that a broken anchor is a silent misfile.

## 5. Environment — two hard rules

- Use `~/.pyenv/versions/3.11.0/bin/python`. The in-tree `.venv` carries the **pre-PR2** stack; do not
  delete or modify it, just never reach for it.
- **Never `pip install` from an agent.** It is a shared pyenv site-packages and it corrupts parallel
  agents' runs.

## 6. Gate on the CAUSE of failures, never the count

A 13→13 count collision once hid a new breakage for seven tasks and poisoned seven dispatch briefs.
Compare failure *causes* against the baseline artifact: no new cause, no change to the
deploy-autoscaling cause, and no test that stopped existing.

## 7. Sabotage-verify every test a reviewer approves

Break the production line the test guards and confirm it goes red **for the right reason**, then
confirm your sabotage was on the executed path. A sabotage that misses its target is
indistinguishable from a test that cannot fail — and several tests in these plans exist precisely
because that happened.

## 8. If you dispatch subagents

- **No git commands in a fix agent, not even read-only ones.** `git show HEAD` in a shared tree cost
  this project ~15 applied findings.
- **Disjoint file sets per parallel agent**, stated explicitly, or separate worktrees.
- For evidence work landed, ask for a **quote of the new text plus its heading** and grep it yourself.
  Do not ask for line numbers — an agent once reported 24 fabricated ranges having written nothing.
