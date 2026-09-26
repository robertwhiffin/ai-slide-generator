# Plan rereview — exact model endpoint discovery and validation (#266)

**Reviewed commit:** `86b292f7dec433551e4b863373cab0992705a2fa`
**Plan:** `docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md`
**Verdict:** **CHANGES_REQUIRED**

Finding count: **0 Critical, 1 Important, 0 Minor.**

## Finding

### Important 1 — the corrected post-rebase “Task 1 only” proof is impossible on the actual plan branch as written

**Plan:** [lines 51, 65–69, 497–501](../../../docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md#mandatory-local-integration-and-stricter-corrections-re-probe-after-task-1-before-task-2)

The correction now gives Task 1 its own `TASK1_BASE`, delays
`IMPLEMENTATION_BASE` until the reviewed local integration is proven, and sets that
final base equal to `INTEGRATION_BASE`. Those are the right identities. The newly
required range assertion is nevertheless inconsistent with the branch it will run on.

Task 0 records `TASK1_BASE=$(git rev-parse HEAD)` after this approved plan/review
history. At the reviewed commit, the real branch contains seven #266-only planning,
research, correction, and review commits after its merge base with
`feat/langgraph-core`:

```text
ef726d7e5 docs: revalidate model endpoint discovery (#266)
2c618a8c7 docs: plan exact model endpoint discovery (#266)
c26389743 docs: remove circular model discovery dependency
9929fd4d9 docs: review model endpoint discovery plan
85bcc1672 docs: correct model endpoint discovery plan (#266)
6622ea023 docs: rereview model endpoint discovery plan
86b292f7d docs: correct model endpoint review base
```

After Task 1, a normal rebase of “the #266 branch” onto the later integration commit
replays those commits as well as Task 1. Therefore
`IMPLEMENTATION_BASE..TASK1_REBASED_HEAD` cannot “contain Task 1 only,” as line 67
requires. Rebasing only `TASK1_BASE..TASK1_HEAD` avoids that log pollution but drops
the branch's approved plan/research history—and the plan file needed for Tasks 2–6—
because the future integration base does not contain it. The plan names neither an
exact rebase range nor another retained source of the plan.

This makes the mandatory gate before Task 2 fail in the normal execution history, or
invites an ad hoc history rewrite that the range proof cannot audit. Correct it by
specifying the exact rebase range and admitting the known rebased #266 plan/research/
review commits to the Task-1 and final range ledgers, while continuing to reject every
#261/#263/#265/#264 predecessor commit. Equivalently, define another explicit reviewed
mechanism that keeps the plan available while replaying Task 1 alone. Update
`plan-correction-report-2.md` as well: it currently repeats the unsatisfiable claim that
the post-rebase subrange contains only Task 1.

## Prior finding verification

The direct defect from `plan-rereview-85bcc167.md` is **conceptually corrected but not
yet executable**:

- Task 0 records a distinct `TASK1_BASE` and does not set `IMPLEMENTATION_BASE`
  ([plan:15, 51–57](../../../docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md#global-constraints)).
- The integration gate sets final `IMPLEMENTATION_BASE` to the exact proven
  `INTEGRATION_BASE`, checks ancestry, and preserves per-task `TASK_BASE..TASK_HEAD`
  packages for Tasks 2–6 ([plan:16, 27, 67](../../../docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md#global-constraints)).
- Final review rechecks base equality and excludes predecessor-ticket commits
  ([plan:497–501](../../../docs/superpowers/plans/2026-09-22-model-endpoint-discovery-validation.md#final-whole-branch-review-handoff)).

The remaining contradiction above prevents those otherwise-correct assertions from
being satisfied on this branch.

## Preserved safeguards independently rechecked

- Mandatory non-mutating Task 0 still precedes Task 1 and records the absolute pyenv
  interpreter, SDK/fake/CI seams, and cause-based baselines.
- Local URL/name policy still runs before stale comparison; remote exact-name/state
  validation runs only after the locked request is current. Invalid-plus-stale and
  valid-plus-stale retain their distinct zero-SDK/zero-remote-call proofs.
- Every backend command uses `/Users/robert.whiffin/.pyenv/shims/python`; the seven
  PostgreSQL modules remain separate, explicit, and zero-skip gates.
- Component and Playwright requirements still include manual non-URL success, typed
  server failure, retained unsaved form, correction/retry without remount, exact five-
  leaf PUT shape, and separate URL zero-PUT/probe proof.
- #263 remains the sole writer/save route and the single reducer/request-ID gate;
  exact endpoint retention, no secret/URL/host/token leakage, lock-version-only probe,
  no-write behavior, runtime-identity `ChatDatabricks.with_structured_output` binding,
  and #267-downstream dependency ordering remain explicit.
- Installed SDK re-probe still reports `databricks-sdk 0.112.0`, argument-free
  `ServingEndpointsAPI.list`, `get(name)`, `ServedEntityOutput.foundation_model`, and
  no `query(response_format=...)` parameter. The plan red-flag scan remains empty.

No implementation, dependency, environment, remote, PR, push, or merge action was
performed.
