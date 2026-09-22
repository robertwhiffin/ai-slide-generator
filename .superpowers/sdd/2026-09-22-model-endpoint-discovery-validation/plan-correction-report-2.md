# Correction report 2 — model endpoint discovery plan (#266)

**Corrected plan:** `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`
**Review addressed:** `plan-rereview-85bcc167.md`

## Important 1 — pre-rebase `IMPLEMENTATION_BASE` polluted the final review range

**Correction:** Task 0 now records only a distinct `TASK1_BASE` in
`PLAN-CORRECTIONS.md`; it explicitly does not create final `IMPLEMENTATION_BASE`.
Task 1 is reviewed from `TASK1_BASE..TASK1_HEAD`.

At the mandatory Task-2 local integration gate, after reviewed #260/#261/#263/#265/#264
ancestry is proven and Task 1 is rebased, the plan records `TASK1_REBASED_HEAD`, sets
final `IMPLEMENTATION_BASE` to the exact proven `INTEGRATION_BASE`, and proves its
ancestry to `HEAD`.  It also proves the rebased Task-1 subrange contains Task 1 only.

Before final review, the executor must prove `IMPLEMENTATION_BASE` still equals the
recorded integration base and use its exact `..HEAD` log to show only rebased Task 1,
Tasks 2–6, and review-approved #266 fixes.  Any #261/#263/#265/#264 predecessor commit
in that range fails the gate.  The range proof accompanies the whole-branch review
package.

Task 1's package remains `TASK1_BASE..TASK1_HEAD`; after rebase every Task 2–6 review
uses its own fresh `TASK_BASE..TASK_HEAD`.  Final `IMPLEMENTATION_BASE` is reserved
solely for the proven whole-branch package.

## Preserved safeguards

- Task 0 remains mandatory and non-mutating before Task 1.
- The stricter Task-2 re-probe, reviewed-local ancestry proof, local-only integration,
  and #265 → #264 → #266 order remain unchanged.
- No production, test, dependency, environment, remote, PR, or push action was taken.
