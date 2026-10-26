# Corrected plan re-review — issue #264 at `7e9ef7553`

## Verdict

**CHANGES_REQUIRED**

Finding count: **0 Critical, 2 Important, 0 Minor**.

Round 2 fully fixes the previous immutable-base/package-range and final-head
reconciliation findings. It also adds the then-missing #261 persisted-runtime
PostgreSQL failure file. The matrix nevertheless remains incomplete for the
final #261 integration surface, and its claimed per-file PostgreSQL zero-skip
evidence is internally contradictory.

## Current local-state re-probe

- `feat/langgraph-core` is now `76a88f238e84f17cc60eba8a62e00dc80fc26115`,
  the local merge of #263. It contains reviewed #260 and
  `1d706e21b92aad68314da2e79bb4d1d5626663b7` (#263).
- The current #261 Task-6 head remains
  `785d9aaca35a3a9103cd4283afdc6bda3b679882` and is **not** an ancestor of
  the root. The #265 branch is still its reviewed plan head
  `ae3d09f3437eb9ce45a6ac52c992c03a3a00c6ca`, also not integrated.
- This is not a defect: the hard integration gate correctly prevents Task 2
  until a concrete reviewed local base contains the final predecessors
  ([plan:17](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:17),
  [plan:44](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:44)).
  No dynamic gate is satisfied merely because #263 has landed.

## Important

### I1. The claimed complete #261 verification matrix still omits current #261 caller/pin suites

The plan requires Task 0 to inventory **all** final #261 graph
caller/retry/failure suites and Task 3 to re-run those final-#261 contracts
([plan:44](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:44),
[plan:125](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:125)).
But both Task 3's executable matrix and the supposedly full Task 7 matrix
omit `tests/unit/test_graph_builder.py`, `tests/unit/test_graph_routers.py`,
and `tests/unit/test_graph_state.py`
([plan:126](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:126),
[plan:168](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:168)).
Those tests are not historical noise: the current #261 head added the hostile
pin overwrite assertion in `test_graph_builder.py:308`, release-id propagation
assertions in `test_graph_routers.py:181` and `:308`, and the state contract in
`test_graph_state.py:380`.

The same final matrix executes only
`test_persisted_graph_runtime_failures_postgres.py` for #261
([plan:191](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:191)).
Current #261 explicitly registers two further PostgreSQL suites in the graph
CI collection guard: `test_conversation_pin_migration_postgres.py`
(`tests/unit/test_ci_collects_integration_tests.py:185`) and
`test_conversation_pin_creation_postgres.py`
(`tests/unit/test_ci_collects_integration_tests.py:196`), alongside the
persisted-runtime suite (`:207`). The plan even runs that collection guard
([plan:182](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:182)),
so it can prove these files are required by CI while never executing them.

This leaves the final #261 pin/no-fallback/caller contract unproved after
Task 3 changes the runtime boundary. Add the three missing unit files to the
Task 3 and Task 7 exact commands, and add the two named #261 PostgreSQL files
to Task 7 (and Task 3 if that is the intended per-task regression gate). Keep
the current persisted-runtime failure invocation; it was correctly added and
must not be replaced.

### I2. The final PostgreSQL command does not deliver the stated per-file zero-skip proof

Task 7 says that every required PostgreSQL file runs as a **separate named
invocation** and that each file has zero skips
([plan:186](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:186),
[plan:196](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:196)).
The final command instead passes the workbench and overlay suites in one
pytest invocation
([plan:192](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:192)).
That contradicts the stated execution rule and does not produce unambiguous
per-file zero-skip evidence.

Split line 192 into one explicit URL-prefixed invocation for
`tests/integration/test_agent_definition_workbench_postgres.py` and one for
`tests/integration/test_agent_schema_overlay_postgres.py`. Add the two missing
#261 PostgreSQL invocations from I1 in the same form. Then require and record
zero skips for each individual command.

## Prior-finding and acceptance re-checks

| Check | Result and evidence |
|---|---|
| Previous I1: immutable bases and exact #264 range | **Resolved.** `TASK1_BASE` and `INTEGRATION_BASE` are separate immutable artifacts ([plan:17](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:17), [plan:34](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:34)); Task 0 records the rebase/range proof ([plan:44](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:44)); the final package is exactly `INTEGRATION_BASE..HEAD` and must contain only rebased Task 1 plus Tasks 2–6 ([plan:208](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:208)). |
| Previous I2: current #261 PostgreSQL failure coverage and runnable matrix | **Partially resolved, not complete.** The current persisted-runtime failure test is explicitly URL-prefixed and zero-skip in Task 3 ([plan:126](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:126)) and retained in Task 7 ([plan:191](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:191)); I1–I2 above identify the remaining omissions/contradiction. The frontend unit/typecheck/ESLint/Playwright commands are otherwise concrete ([plan:200](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:200), [plan:202](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:202), [plan:203](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:203)). |
| Previous I3: final predecessor/root ancestry gate | **Resolved.** The pre-merge gate re-probes final reviewed heads and root, checks both root and #264 ancestry, recomputes the reviewed range, and mandates rebase/refresh/re-review after advancement ([plan:209](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:209)). |
| Earlier C1: aggregate wire/error family | **Resolved.** The plan retains `candidate`, `invalid_draft`, ordered `{field, code, message}`, and the coherent seven-role stale snapshot ([plan:22](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:22), [plan:66](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:66), [plan:93](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:93)). |
| Earlier I1: Task-0 correction pass before Task 1 | **Resolved.** Task 0 precedes implementation and its overriding corrections file is attached to every Task-1 brief/review ([plan:15](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:15), [plan:42](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:42)). |
| Earlier I2: diagnostics and trace success boundary | **Resolved.** Validation/projection/freezing occurs within the existing callback before either sink records success; error and absent/null/empty semantics are explicit ([plan:64](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:64), [plan:125](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:125)). |
| Earlier I3: interpreter and browser roots | **Resolved.** The absolute shared-pyenv interpreter, `.venv` guard, and frontend-rooted Playwright command are binding ([plan:19](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:19), [plan:20](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:20)). |
| Earlier M1: unreachable catalog ruling | **Resolved.** The embedded catalog is expressly authoritative, with no untracked-ruling dependency ([plan:11](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:11), [plan:23](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:23), [plan:52](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:52)). |
| #264 acceptance | **Covered subject to I1–I2.** The plan keeps executable canonical contracts separate, composes only allowlisted extras, preserves them in diagnostics/traces, protects canonical properties at the UI/API, and requires allowed/forbidden/raw-extra tests ([plan:5](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:5), [plan:24](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:24), [plan:64](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:64), [plan:145](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:145), [plan:155](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:155)). |
| Required local order | **Resolved.** The plan and current #265 handoff agree on local-only `#265 -> #264 -> #266` after reviewed predecessors ([plan:18](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:18), [plan:210](docs/superpowers/plans/2026-09-22-safe-output-schema-overlays.md:210)). |

No implementation tests were run. This was a read-only plan/state review; the
only change is this review artifact.
