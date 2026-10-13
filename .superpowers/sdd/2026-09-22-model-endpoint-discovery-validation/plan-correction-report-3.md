# Correction report 3 — executable #266 replay ledger

**Corrected plan:** `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`
**Fix-round finding addressed:** `plan-rereview-86b292f7.md` Important 1

The plan no longer requires an impossible post-rebase range containing Task 1 alone.
Task 0 records `PLAN_HISTORY_BASE`, `TASK1_BASE`, and the ordered allowed #266
plan/research/review history. After Task 1, the integration gate replays the complete
allowed source interval onto the proven local integration base with an explicit
`git rebase --onto "$INTEGRATION_BASE" "$PLAN_HISTORY_BASE"`.

The ledger captures the pre-rebase source list, a separately recorded exact ordered
Task 1 implementation/fix/report/review/re-review sequence, replayed head, and
`git range-diff`. It requires exact ordered source equality—frozen
`ALLOWED_PREINTEGRATION_266_HISTORY` followed by that Task 1 sequence—and rejects any
#261/#263/#265/#264 predecessor or merge commit while admitting the required #266
planning/research/review commits. Final `IMPLEMENTATION_BASE` remains exactly
`INTEGRATION_BASE`; per-task ranges remain separate, and final review packages the
proven whole #266 range only.
