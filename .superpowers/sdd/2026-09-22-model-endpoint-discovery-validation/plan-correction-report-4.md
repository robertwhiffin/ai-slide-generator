# Correction report 4 — Task 1 replay-sequence ledger (#266)

**Corrected plan:** `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`
**Fix-round finding addressed:** `plan-rereview-26ab712f1.md` Important finding

## Important — Task 1 review/report commits were outside the source ledger

**Correction:** Task 0 still freezes `ALLOWED_PREINTEGRATION_266_HISTORY` before
Task 1. After Task 1 closes, the corrections ledger now separately records
`ALLOWED_TASK1_266_HISTORY`: the complete exact ordered `%H %s` Task 1 sequence after
`TASK1_BASE`, with a one-for-one classification of every commit as implementation,
fix, report, review, or re-review. The pre-rebase gate requires both that this raw
Task 1 ledger exactly equals `TASK1_BASE..PRE_REBASE_266_HEAD` and that the complete
source interval exactly equals the frozen Task-0 history followed by this separate
Task 1 sequence. Prefix and superset comparisons are insufficient.

The replay remains `git rebase --onto "$INTEGRATION_BASE" "$PLAN_HISTORY_BASE"`.
It rejects #261/#263/#265/#264 predecessor heads and commits plus merge commits before
replay, rejects merge commits after replay, and requires `git range-diff` to map every
frozen planning/research/review entry and every classified Task 1 entry. The final
ledger still requires `IMPLEMENTATION_BASE == INTEGRATION_BASE`, reserves that base
for the whole-branch range, and preserves Task 2–6's independent `TASK_BASE..TASK_HEAD`
packages.

## Re-probed repository evidence

- #264 Task 1 interleaves implementation/fix work with committed re-review and final
  review artifacts, including `554031049` (re-review round 2), `2500b50f4`
  (re-review round 3), `1095ac202` (approve rereview 4), and `ac69f62b6` (complete
  review).
- #261 likewise records task evidence/reviews after implementation and fix commits:
  `a4c65e427` (task 9 evidence), `5bbdca80e` (task 9 review), `c39557deb`
  (task 9 fix re-review), and `876f2a91f` (complete task 9 review).

Those observed patterns require an auditable Task 1 report/review/re-review ledger;
they cannot fit into Task 0's already-frozen pre-integration snapshot.

## Preserved safeguards

- No production, test, dependency, environment, remote, PR, push, merge, or
  implementation action was taken.
- The reviewed-local predecessor ancestry gate, range-diff mapping, no-merge rule,
  and #265 → #264 → #266 local integration order are unchanged.
