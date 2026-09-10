# ws4 implementation — START HERE

Written 2026-09-10, at the end of the planning phase. Read this before the plans.

## 1. Nothing is open. Start at ws4a.

The five seam-review judgment calls (S1–S5) were **all closed on 2026-09-10**, each with a probe rather
than an argument. `ws4_seam_findings.md` § RESOLVED carries the decisions and the evidence; the commits are
`a63124e9`, `830b4590`, `a24aa2b2`, `6678c997`, `ee2bc8e9`.

The five you should know before reading any plan, because each changed a contract:

- **`invoke_graph(session_id, initial, *, emitter=None, principal=None)`.** ws4d must
  `contextvars.copy_context()` before spawning its thread, or every graph-written row loses its author.
- **`resolve_slide_style` delegates** to `_get_prompt_content(config)["slide_style"]`. Never reimplement
  that branch; there is a test asserting the graph and the monolith return identical bytes.
- **Deck-review verdicts have two readers:** `architect_node` via `get_deck_review`, and the human via a
  persisted `message_type="info"` chat message. No new event type, route or UI.
- **ws4c adds an `integration-graph` CI job**, and **ws4a Task A5** guards integration-test collection —
  10 of 17 integration files currently run in no job, including PR1's row-per-slide foundation.
- **The §7.4 flag is derived** from `releasedPositions.size === deckSpec.slides.length && !turnComplete`,
  not read from the sweeper's marker.

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
