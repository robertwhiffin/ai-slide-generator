# AgentRuntime Prefactor — Execution Corrections

These corrections override the execution mechanics in
`2026-09-21-agent-runtime-prefactor.md`. They do not change issue #259's product
scope or acceptance criteria.

1. **Review the working tree, not only `HEAD`.** The fixed point is `a266d91a6`,
   and the implementation is intentionally uncommitted until review completes.
   `git diff a266d91a6...HEAD` is therefore empty for the implementation. Review
   tracked changes with `git diff a266d91a6 -- <issue-paths>` and read the new
   runtime, runtime tests, plan, and this corrections file directly.
2. **Treat the full-suite baseline as a cause-set.** Before this work, the non-live
   suite had exactly two failures, both in
   `tests/unit/test_deploy_autoscaling.py`. A final run is acceptable only if those
   same two causes remain and no new cause appears; a matching failure count alone
   is not evidence.
3. **Do not turn inherited lint/type debt into issue #259 scope.** Repository-wide
   Ruff and mypy commands already report unrelated failures in legacy skill and
   fixture files. The new runtime and its tests must be clean under focused checks,
   and changed production code must introduce no new diagnostics relative to the
   recorded baseline.
4. **The shared Python environment is immutable for this task.** Do not install or
   upgrade packages while reviewing or verifying the change.
5. **Review all ten runtime call sites, not only seven role names.** Builder and
   Fixer each have retry calls, and Build Reviewer has both normal and deck-level
   re-review paths. Every call must cross `AgentRuntime`; Foreman must not.
