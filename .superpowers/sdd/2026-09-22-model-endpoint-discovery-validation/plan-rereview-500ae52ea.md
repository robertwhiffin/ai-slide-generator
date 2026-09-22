# Scoped plan re-review — Task 1 replay-sequence ledger (#266)

**Reviewed fix range:** `b853eef3c15b0bca0e3ab9f5706e21bde67b1b24..500ae52eab2cf38dc0a6a3ad4e513671218b5880`

**Prior finding:** `plan-rereview-26ab712f1.md` Important — Task 1
review/report commits were outside the source ledger.

**Original-finding verdict:** **ADDRESSED**

**Overall verdict:** **APPROVED**

Finding count in the scoped fix diff: **0 Critical, 0 Important**.

## Prior finding — ADDRESSED

The binding plan now admits the complete Task 1 history without weakening the
replay boundary.

- Task 0 still freezes `ALLOWED_PREINTEGRATION_266_HISTORY` at
  `PLAN_HISTORY_BASE..TASK1_BASE` (`plan:51`).  It cannot contain future Task
  1 evidence commits.
- After Task 1 closes, `ALLOWED_TASK1_266_HISTORY` records the complete ordered
  `%H %s` range after `TASK1_BASE`, with a reviewer-approved one-for-one
  classification of every line as `implementation`, `fix`, `report`, `review`,
  or `re-review` (`plan:67`).  No other class is permitted.  This admits every
  committed Task 1 implementation/fix/report/review/re-review artifact, including
  evidence commits interleaved with fixes.
- Before replay, the Task 1 ledger must equal exactly, in order,
  `git log --reverse --format='%H %s' "$TASK1_BASE".."$PRE_REBASE_266_HEAD"`.
  The complete source interval must then equal exactly the concatenation of the
  frozen pre-integration ledger followed by that Task 1 ledger.  The plan says
  explicitly that a prefix or superset is insufficient (`plan:67`, reiterated
  at `:501`).
- The source check rejects reviewed #261/#263/#265/#264 ancestry, any
  predecessor entry, and every merge commit before replay; the rebased range
  must also be merge-free.  The required `git range-diff` maps every frozen
  #266 planning/research/review commit and every separately ledgered Task 1
  commit.  Added, dropped, or materially changed commits require a ruling and
  review before Task 2.
- `IMPLEMENTATION_BASE` is assigned only after that replay and is exactly
  `INTEGRATION_BASE`; Task 1 retains `TASK1_BASE..TASK1_HEAD`, and Tasks 2–6
  retain their own fresh `TASK_BASE..TASK_HEAD` package ranges (`plan:27`,
  `:67`, `:497`).

Correction reports 2, 3, and new 4 describe the same exact-sequence rule, so
the binding plan and correction evidence no longer disagree.

## Independent history verification

| Check | Evidence | Ruling |
| --- | --- | --- |
| Scoped package | One commit, `500ae52ea`, changes only the plan and correction reports 2–4; `git diff --check` is clean. | Scoped correctly |
| Current source boundary | `git merge-base HEAD feat/langgraph-core` is `a94c907d2`. | Stable pre-integration boundary |
| Current #266 history | `a94c907d2..HEAD` has 11 linear #266 research/plan/review/rereview commits, ending at `500ae52ea`. | Classifiable frozen-history candidate |
| Current merge rejection | `git rev-list --merges a94c907d2..HEAD` returned no commits. | Pass |
| Current predecessor separation | Reviewed #260 is an ancestor of the boundary; #261, #263, #264, and the #266 research branch are not ancestors of current #266 `HEAD`. | Pass; final local-integration ancestry remains a future mandatory gate |
| Exact replay proof | The plan requires exact Task 1 equality, exact concatenated-source equality, a no-merge check on both ranges, and `git range-diff` mapping for every allowed commit. | Pass |
| Final/package bases | The plan reserves `IMPLEMENTATION_BASE == INTEGRATION_BASE` for the final whole-branch package and keeps Task 1 and Tasks 2–6 on their distinct per-task ranges. | Pass |

## New Critical/Important breakage in this fix

None found.  The fix does not alter implementation scope, predecessor order,
or package-base ownership; it closes the missing committed-evidence class while
retaining exact ordered equality, predecessor/merge rejection, and complete
range-diff mapping.

No implementation, dependency, environment, remote, PR, push, or merge action
was performed.
