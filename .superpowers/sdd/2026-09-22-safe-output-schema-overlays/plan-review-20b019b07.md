# Plan review — issue #264 at `20b019b07`

## Verdict

**CHANGES_REQUIRED**

Finding count: **0 Critical, 3 Important, 0 Minor**.

The prior review's C1, I1, I2, I3, and M1 are all corrected. The plan now preserves
the landed aggregate wire family, runs a pre-Task-1 correction pass, validates and
projects output inside the existing #261 sink callback, uses the absolute shared-pyenv
interpreter and frontend-rooted Playwright command, and embeds the optional-catalog
literals directly. Three independent execution-control defects remain.

I re-read live GitHub issues #258 and #264 and the binding design sections, and
re-probed the local refs at review time:

- `feat/langgraph-core` = `774703e4487877bf65e0eeff173892d3e00ceac5`, containing
  reviewed #260 `29e03411487476383b34101b7b34513dbb917f26`;
- `feat/conversation-pins-runtime-261` =
  `785d9aaca35a3a9103cd4283afdc6bda3b679882`;
- `feat/shared-graph-draft-editor-263` =
  `1d706e21b92aad68314da2e79bb4d1d5626663b7`;
- corrected #265 plan = `ae3d09f3437eb9ce45a6ac52c992c03a3a00c6ca`.

The root does not yet contain #261, #263, or implemented #265. That is not a finding:
the plan correctly blocks Task 2 until the final reviewed heads and reviewed #265 are
ancestors of one concrete local integration commit
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:17,42`).

## Important

### I1. The plan does not establish the post-rebase base used by the final review package

Task 0 defines only one base artifact, `IMPLEMENTATION_BASE`
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:32-37`). Step 1
initially records the reviewed #260 base there before Task 1
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:39`). Step 4 later
records a different `INTEGRATION_BASE` after #261/#263/#265 are integrated and rebases
Task 1 above it, but never says to replace `IMPLEMENTATION_BASE`, preserve both values
under distinct names, or declare which value is authoritative for whole-branch review
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:42`). Task 7 then
requests the package from "the exact recorded implementation base" without resolving
that ambiguity (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:165`).

Using the initial #260 value after the rebase packages all integrated #261/#263/#265
commits as if they were #264 work. Silently overwriting it leaves the earlier evidence
and terminology ambiguous. This undermines the required exact-range whole-branch review,
especially its writer and sink comparison.

Define two immutable recorded SHAs (for example `TASK1_BASE` and
`INTEGRATION_BASE`), update the final-package instruction to use exactly
`INTEGRATION_BASE..HEAD`, and prove the rebased Task 1 plus Tasks 2-6 are the complete
#264 diff in that range.

### I2. The verification matrix is neither exact nor complete for the current #261 head

Task 3 requires the final #261 typed-failure and no-fallback tests
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:123`), but its exact
command contains only unit files and omits the current PostgreSQL failure suite
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:124`). At the probed
#261 head, `tests/integration/test_persisted_graph_runtime_failures_postgres.py:41`
marks that suite PostgreSQL, and `.github/workflows/test.yml:448-464` explicitly enrolls
it in `integration-graph`.

Task 7 then replaces concrete filenames with prose and says to run "all three
PostgreSQL suites" (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:162`).
The integrated slice already has the #261 persisted-runtime failure suite, the #260
bootstrap suite, and the #263/#265 workbench suite; Task 4 adds the #264 overlay suite
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:131-137`). Thus the
declared count cannot cover the named current failure seam. The same final step says
"scoped lint" without a command (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:163`),
even though the checked-in frontend exposes only the general `lint: eslint .` script
(`feat/shared-graph-draft-editor-263:frontend/package.json:6-18`).

Task 0's later inventory is useful, but it should not have to decide whether an explicit
"three suites" requirement excludes a newly observed required suite. Replace Tasks 3
and 7 with runnable commands naming every final #261/#263/#265/#264 unit and PostgreSQL
file, apply `TELLR_TEST_POSTGRES_URL` to every PostgreSQL invocation, require zero skips
per named file, and spell out the lint command and paths. The correction pass may update
renamed files, but must preserve the current #261 PostgreSQL failure coverage.

### I3. The final local merge has no final-head or integration-base re-probe

The plan re-probes predecessor heads immediately before the pre-Task-2 integration gate
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:17,42`). After all
implementation and review work, however, Task 7 directly merges #264 into
`feat/langgraph-core` with no assertion that the root still contains the recorded
integration base or the then-final reviewed #261/#263/#265 heads
(`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:166`). A predecessor
can advance during Tasks 2-7; the resulting local merge would then be based on stale
shared interfaces despite the earlier gate.

The corrected #265 handoff already states the appropriate rule: re-probe each reviewed
head before its local merge
(`plan/prompt-assembly-265:docs/superpowers/plans/2026-09-22-declarative-prompt-assembly.md:666-669`).
Add a final #264 gate that re-resolves final reviewed predecessor heads, proves them and
the recorded `INTEGRATION_BASE` are ancestors of the current local root and #264 HEAD,
and refuses the merge if reconciliation would change the reviewed #264 diff. If any
shared dependency advanced, integrate/rebase it, refresh corrections and cause
baselines, and rerun the affected task/final review before merging.

## Prior finding verification

- **C1 resolved:** `candidate.schema_overlay...`, `invalid_draft`, `{field, code,
  message}`, ordered 422s, ordinary submitted `client_candidate`, upgrade
  `client_candidate: null`, and the coherent exact-seven snapshot are explicit
  (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:22,64-97,143-146`).
- **I1 resolved:** Task 0 now precedes Task 1, creates the correctly named overriding
  corrections file, records cause baselines, and refreshes it before Task 2
  (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:15,30-42`).
- **I2 resolved:** validation/projection and freezing happen inside the existing sink
  callback before success; both sinks cover error outcomes and exact absent/null/empty
  trace values (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:62,123-126`).
- **I3 resolved:** backend commands use the absolute pyenv interpreter and Playwright
  runs from `frontend`; installs and root-level `npx` are forbidden
  (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:19-20`).
- **M1 resolved:** the seven exact catalog literals and validation semantics are now
  authoritative plan text (`docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:11,23,50-60`).

## Areas otherwise ready

- Task 1 is collision-free and isolated from #261/#263/#265-owned files; Task 0 now
  precedes it and Task 2 remains hard-gated on reviewed local integration.
- The local-only dependency order is exactly #265 -> #264 -> #266, with no remote,
  PR, push, publish, or install dependency.
- The registry contract preserves v1 material, uses role-bound retained identities,
  separates canonical and optional validation, projects to the original canonical
  model, and preserves immutable absent/null/empty diagnostics.
- The #261 sink order now prevents a success trace before output validation and retains
  provider conversion inside the callback and persisted-config failure before the sink.
- The #263/#265 aggregate request, one locked writer, ordered validator tuple, common
  hash/audit/lock path, strict upgrade, one frontend state machine, exact-seven conflict
  recovery, and cross-operation pending/response ordering are preserved.
- TDD, distinct controller/reviewer sabotage, exact task ranges, cause-based baselines,
  PostgreSQL waiter/identity/no-write assertions, and the most-capable final review are
  all required.

No implementation tests were run. This was a read-only plan, issue, design, and
authoritative-interface review; only this report was created.
