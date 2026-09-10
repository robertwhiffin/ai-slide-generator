# Workstream 4 review findings — round 1 (and ws4a round 2)

Verbatim reviewer output from the `doc-review-loop` run of 2026-09-10. Moved here from `/tmp`
so it survives; **untracked by design** until someone decides these belong in git.

> **The "State" column is a snapshot taken 11:27 and it is already stale.** A concurrently
> live session was still running fix agents against `ws4a` and `ws4c` at 11:48 — both have
> uncommitted working-tree changes. **Read `git diff` before trusting any row below.** The
> findings themselves are verbatim and do not go stale; only the state does.

| File | Document | Findings | State |
|---|---|---|---|
| `ws4_r1_index_findings.md` | `2026-08-25-ws4-index.md` | — | fixed (waves 1, 1b, 1c) |
| `ws4_r1_ws4a_findings.md` | `2026-08-25-ws4a-shipped-defects.md` | 14 | fixed (wave 2) |
| `ws4_r1_ws4b_findings.md` | `2026-08-25-ws4b-contracts-and-schema.md` | — | fixed (wave 2) |
| `ws4_r1_cde_findings.md` | ws4c / ws4d / ws4e | 20 / 21 / 29 | **ws4c ~15 UNFIXED**; ws4d 18/21; ws4e ~22/29 |
| `ws4_r2_ws4a_findings.md` | ws4a, second fresh review | 15 | ~10 addressed in an **uncommitted** working-tree diff, incl. the at-rule dedupe key that was flagged as needing a human ruling |

**Read before executing any ws4 plan.** ws4c's unfixed residue is blocking-class for the
graph PR.

## `2026-08-25-ws4c-graph-core.md.bak` is not a backup — do not delete it

It is a **divergent partial state** from the wave-2 collision (a fix agent ran
`git show HEAD` over sibling plans while their agents were editing them). Diffed against
`HEAD`, the `.bak` **carries two fixes the committed plan lost**:

- the `title` producer row in the `GraphState` table (round-1 ws4c finding 2, *"BLOCKING —
  the deck title has no source"*);
- the builder-foundation text naming extracted section HTML, section CSS and resolved style
  prose as what the builder authors on (the §M5/§M6 fairness constraint).

and **lacks one the committed plan has**: the `stalled_positions` / `retry_count` paragraph.

So neither file is a superset. Recovering ws4c means a three-way merge, not a copy.
