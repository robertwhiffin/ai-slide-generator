# Scoped plan rereview — exact model endpoint discovery and validation (#266)

**Reviewed fix range:** `750c03af1617c9a7e0b106300674cdac091beecd..26ab712f14e3daf9deacdc9aea683b9c9bca9f5a`

**Prior finding:** `.superpowers/sdd/2026-09-22-model-endpoint-discovery-validation/plan-rereview-86b292f7.md` Important 1

**Original-finding verdict:** **ADDRESSED**

**Overall verdict:** **CHANGES_REQUIRED** — the fix introduces one new Important replay-ledger gap.

Finding count in the scoped fix diff: **0 Critical, 1 Important**.

## Original finding — ADDRESSED

The plan no longer claims that the post-rebase range contains Task 1 alone. It now:

- records separate `PLAN_HISTORY_BASE` and `TASK1_BASE`, plus the ordered pre-integration #266 history (`docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:15`, `:51`);
- verifies the complete source interval, then names the exact replay command `git rebase --onto "$INTEGRATION_BASE" "$PLAN_HISTORY_BASE"` (`plan:67`);
- records a two-range `git range-diff`, rejects added/dropped/materially changed commits and merge commits, and keeps predecessor-ticket commits below the final base (`plan:67`);
- sets `IMPLEMENTATION_BASE` only after the replay, exactly equal to `INTEGRATION_BASE`, while preserving `TASK1_BASE..TASK1_HEAD` and fresh `TASK_BASE..TASK_HEAD` ranges for Tasks 2–6 (`plan:27`, `:51`, `:67`);
- repeats the exact-base/range-ledger checks before the final whole-branch package (`plan:497`, `:501`).

The correction reports now describe the same complete-source replay instead of the impossible Task-1-only post-rebase range (`plan-correction-report-2.md:8-27`; `plan-correction-report-3.md:6-16`).

## New Important finding — Task 1 review/report commits are excluded from the mandatory source ledger

The replacement source gate permits the Task-0 snapshot followed **only** by “recorded Task 1 implementation/fix commits” (`docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md:67`). But the same plan requires Task 1 to be reviewed and attaches `PLAN-CORRECTIONS.md` to its reviewer brief (`plan:27`, `:61`). In this repository's SDD workflow, task-review and re-review artifacts are committed as their own `docs:` commits after the implementation/fix commits.

That is not hypothetical. The adjacent #264 Task 1 history contains, after implementation/fix commits:

```text
554031049 docs: re-review schema overlay task 1 round 2
2500b50f4 docs: re-review schema overlay task 1 round 3
1095ac202 docs: approve schema overlay task 1 rereview 4
ac69f62b6 docs: complete schema overlay task 1 review
```

#261 likewise carries committed task-review/evidence artifacts between task and fix commits. The current assignment itself also requires its review artifact to be committed.

`ALLOWED_PREINTEGRATION_266_HISTORY` is frozen during Task 0, before Task 1 (`plan:51`), so future Task 1 review/report commits cannot be members of that snapshot. They are also not implementation/fix commits. A normal reviewed Task 1 therefore makes the exact equality check at `plan:67` fail before the otherwise-correct rebase can run. Dropping or leaving those review artifacts out of history would defeat the auditable SDD workflow this ledger is meant to protect.

Required correction: admit and separately record the complete Task 1 implementation, fix, **report, review, and re-review** commit sequence after the frozen pre-integration history. Keep the exact ordered comparison, predecessor-head rejection, merge rejection, and `range-diff` mapping. Update both correction reports to match the binding plan text.

## Independent history verification

Against the actual repository state:

| Check | Evidence | Ruling |
|---|---|---|
| Fix range | One commit, `26ab712f1`, changing only the plan and correction reports 2/3 | Scoped correctly |
| Current `PLAN_HISTORY_BASE` | `git merge-base HEAD feat/langgraph-core` = `a94c907d2db75e53743289651443fe9583bfa8f7` | Exact, stable source boundary |
| Current source ledger | Nine linear #266 research/plan/review commits, `ef726d7e5` through `26ab712f1` | All expected and classifiable |
| Merge rejection | `git rev-list --merges a94c907d2..HEAD` is empty | Pass |
| Predecessor rejection | #261, #263, and #264 heads are not ancestors of current #266 `HEAD`; `447791d7a` is also not an ancestor | Pass for current pre-integration source |
| #260 starting point | Reviewed #260 head `29e034114` is an ancestor of `a94c907d2` | Pass |
| Exact replay | `git rebase --onto "$INTEGRATION_BASE" "$PLAN_HISTORY_BASE"` replays the complete linear source interval, including Task 1, onto the later reviewed integration base | Correct command |
| Range proof | `git range-diff "$PLAN_HISTORY_BASE".."$PRE_REBASE_266_HEAD" "$INTEGRATION_BASE".."$TASK1_REBASED_HEAD"` is the correct old/new comparison; the plan requires one-to-one mapping or a ruling/review | Correct proof |
| Final base | The plan sets and later rechecks `IMPLEMENTATION_BASE == INTEGRATION_BASE` and ancestry to `HEAD` | Pass |
| Per-task review ranges | Task 1 retains `TASK1_BASE..TASK1_HEAD`; Tasks 2–6 each record fresh `TASK_BASE..TASK_HEAD`; none uses `IMPLEMENTATION_BASE` | Pass |

The present `feat/langgraph-core` does not yet contain every required predecessor head; the plan explicitly waits for reviewed local #265/#264 integration and re-probes ancestry before replay. That is a future gate, not a defect in this fix.

No implementation, dependency, environment, remote, PR, push, merge, or plan edit was performed.
