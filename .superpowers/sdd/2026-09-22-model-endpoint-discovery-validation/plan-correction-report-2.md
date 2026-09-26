# Correction report 2 — model endpoint discovery plan (#266)

**Corrected plan:** `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`
**Review addressed:** `plan-rereview-85bcc167.md`

## Important 1 — pre-rebase `IMPLEMENTATION_BASE` polluted the final review range

**Correction:** Task 0 now records only a distinct `TASK1_BASE` in
`PLAN-CORRECTIONS.md`; it explicitly does not create final `IMPLEMENTATION_BASE`.
Task 1 is reviewed from `TASK1_BASE..TASK1_HEAD`.

At the mandatory Task-2 local integration gate, after reviewed #260/#261/#263/#265/#264
ancestry is proven, the plan replays the complete ledgered #266 source interval: the
reviewed plan/research/review history needed to retain the plan plus the separately
recorded, exact ordered Task 1 implementation/fix/report/review/re-review sequence.
It records an auditable `git range-diff`, rejects predecessor-ticket and merge
commits, sets final `IMPLEMENTATION_BASE` to the exact proven `INTEGRATION_BASE`, and
proves its ancestry to `HEAD`.

The source gate requires exact ordering, not a prefix check: its pre-rebase source
history must equal frozen `ALLOWED_PREINTEGRATION_266_HISTORY` followed by the separate
Task 1 ledger, whose raw history exactly matches `TASK1_BASE..PRE_REBASE_266_HEAD`.

Before final review, the executor must prove `IMPLEMENTATION_BASE` still equals the
recorded integration base and use its exact `..HEAD` log/range-diff to show the allowed
rebased #266 plan/research/review history, exact separately ledgered Task 1 sequence,
Tasks 2–6, and review-approved #266 fixes. Any #261/#263/#265/#264 predecessor commit
or merge commit in that range fails the gate. The range proof accompanies the
whole-branch review package.

Task 1's package remains `TASK1_BASE..TASK1_HEAD`; after replay every Task 2–6 review
uses its own fresh `TASK_BASE..TASK_HEAD`.  Final `IMPLEMENTATION_BASE` is reserved
solely for the proven whole-branch package.

## Preserved safeguards

- Task 0 remains mandatory and non-mutating before Task 1.
- The stricter Task-2 re-probe, reviewed-local ancestry proof, local-only integration,
  and #265 → #264 → #266 order remain unchanged.
- No production, test, dependency, environment, remote, PR, or push action was taken.
