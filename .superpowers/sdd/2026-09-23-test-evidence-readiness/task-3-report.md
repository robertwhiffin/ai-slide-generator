# #268 Task 3 report: verdict and readiness routes

**Status: DONE_WITH_CONCERNS**

- TASK_BASE: `26713a0049e5efd2d81e73d310d779e47963e9af`
- Implementation commit: `1887e7790` `feat: verdict and readiness routes (#268)`. This one commit holds both sides of C16.
- This report is committed on top of it with `git add -f`.

## What landed
- **Routes.** Both are on the existing admin router (C15).
  - `POST /api/admin/agent-definitions/test-runs/{run_id}/verdict`
    - It is `async`, because it reads the body. It hands `record_verdict` to `run_in_threadpool`, because the L3 `FOR UPDATE` wait must not block the event loop.
    - The reviewer comes from `require_draft_write_principal`. The body is parsed after both dependencies, into the strict `VerdictRequest` with exactly `{verdict, notes}`.
    - `verdict: str`. The service owns the choice, blank and length rules, so one ordered list reports them all.
    - `notes: str | None` is required and may be null.
  - `GET /api/admin/agent-definitions/readiness` is a plain `def`, so FastAPI runs it in the threadpool.
- **Responses:**

  | Case | Response |
  |---|---|
  | success | 200 `TestRunEvidenceResponse`; currency flags `null` |
  | unknown or unstorable id | 404 `{"detail":"Test run not found"}` (path guard `_is_storable_row_id`) |
  | not completed or checks failed | 422 `{"code":"ineligible_for_approval","reason":…,"message":…}` from the strict `IneligibleForApprovalResponse` |
  | bad body, invalid JSON, or `VerdictRejected` | 422 `{"code":"invalid_verdict","errors":[…]}` from the strict `VerdictValidationErrorResponse`, in the ordered issue shape |
  | blank-reviewer `actor` issue from the writer (Task 1 carry-forward) | 403 `Authenticated principal required` |
  | `IntegrityError` | not caught; propagates to a 500 |
  | readiness `GraphConfigurationIntegrityError` | 500 `Graph configuration is incomplete`, as `/workbench` does; this includes the un-retried parent-handoff diagnosis |

  - **Blank reviewer → 403, not 422:** the principal is at fault, not the client's body. The dependency makes this unreachable today; the mapping is the second line of defence.
  - **`IntegrityError` → 500, not 409 (C7):** a 409 would tell the client "reload and retry", which is wrong for #269's linked-verdict trigger. #269 owns any friendlier mapping.
  - **Invalid JSON uses `invalid_verdict`, not the draft helper's `invalid_draft`:** this follows the per-family precedent of the test-case routes (`invalid_test_case`), so Task 6's client has one 422 code per route.
- **Readiness wire (C17):** `DraftReadinessResponse`, `AgentReadinessResponse` and `TestCaseReadinessResponse`.
  - All three are strict, with snake_case field names and snake_case `status` codes. There are no labels and no aliases.
  - The fields mirror the dataclasses one to one, including `missing_required_case`.
- **Evidence wire (C16):** the four verdict fields are required keys with nullable values. They were added in one commit to:
  - `TestRunEvidence` (placed before the defaulted flags) and `_evidence_from_row`;
  - `TestRunEvidenceResponse`;
  - TS: `TestRunVerdict`, `TEST_RUN_VERDICTS`, `TEST_RUN_KEYS`, the interface, and `parseTestRunEvidence` with an `isVerdictRecord` pairing check (verdict ⇔ reviewer ⇔ time; notes only beside a verdict);
  - `mocks.ts`, in `syntheticTestRunEvidence`.
- **Assertions flipped:**
  - routes test (was ~5569): now "present and null";
  - `TestRunPanel.test.tsx:537`: now an unknown-key case, plus verdict key, type and pairing cases;
  - the join test's "no verdict key" assertion: now "the four keys";
  - a new join test pins `TEST_RUN_VERDICTS`.
- `("verdict", "approved")` stays in `_FORBIDDEN_CLIENT_RUN_FIELDS`.
- `test_main_app_registers_the_dedicated_workbench_route` pins the route inventory. It gained the two new paths.
- **Task 1 carry-forward:** `record_verdict`'s return value is now asserted to carry the verdict fields, in both the identical re-submit test and the re-stamp test.

## RED before implementation
- **Python** (`/tmp/t268-3/red-python-saved.txt`): 60 failed and 618 passed across the routes, workbench and join files. All failed for missing features:
  - the new routes returned 404;
  - `DraftReadinessResponse` did not exist, so its import failed;
  - the verdict keys were missing;
  - `TestRunEvidence` had no `verdict` attribute;
  - the join tests had no verdict keys or `TEST_RUN_VERDICTS`.
- **Vitest** (`/tmp/t268-3/red-vitest.txt`): 4 failed.
  - The 3 "accepts stored evidence carrying …" cases failed.
  - "missing verdict key" failed because the mock had no such key yet.
  - The pairing cases were already rejected by the exact-key check. They became meaningful after the change, which M22–M24 prove.

## Clause-to-mutation table
Driver: `/tmp/t268-3/mutate.py`; results in `/tmp/t268-3/mutations-all.json` and `mutations-M15_no_refresh.json`.

For every row, the following all held:
- anchor count was 1, and `grep -c MUT_Mn <file>` was 1 after applying the mutation;
- the scope was whole-file: the pytest routes, workbench and join files, plus Vitest `TestRunPanel.test.tsx` and `tsc -b` for frontend mutations;
- the restore was `git checkout 1887e7790 -- <file>`, and `git diff --quiet` was clean afterwards;
- the tree was GREEN after the sweep: 785 Python tests and 76 Vitest tests.

Every mutation went RED, so every mutated line executed.

| # | Clause | Mutation | RED (failing tests) |
|---|---|---|---|
| M1 **S3 (controller target)** | reviewer never from the body | `reviewer` added to `VerdictRequest` and passed through | `test_a_verdict_body_cannot_choose_any_server_owned_value[reviewer]` |
| M2 | reviewer = principal | constant reviewer | `test_a_verdict_returns_200_evidence_with_the_principal_as_reviewer[approve, reject-without-notes]`, `test_a_verdict_route_passes_exactly_the_body_and_the_principal`, `test_a_blank_reviewer_reaching_the_writer_is_the_principal_403` |
| M3 | admin gate | router `dependencies=[]` | 20 tests, including `test_verdict_and_readiness_routes_deny_non_admins_before_body_or_service[verdict, readiness]` |
| M4 | exact reason | reason fixed to `checks_failed` | `test_a_verdict_on_a_run_that_did_not_complete_is_the_exact_not_completed_422[approved, rejected]` |
| M5 | ineligible is 422 | 409 | the same 2 tests plus `test_an_approval_of_a_run_with_failed_checks_is_the_exact_ineligible_422` |
| M6 | ineligible is mapped | catch removed | the same 3 tests |
| M7 | C7, never translate | generic `except` → ineligible | `test_a_verdict_integrity_error_is_never_translated` |
| M8 | blank `actor` → 403 | mapping disabled | `test_a_blank_reviewer_reaching_the_writer_is_the_principal_403` |
| M9 | path guard | guard disabled | `test_a_verdict_on_an_unknown_or_unstorable_run_is_404[9223372036854775808]` |
| M10 | verdict runs off the loop | direct call | `test_the_verdict_route_waits_on_the_run_row_lock_off_the_event_loop` |
| M11 | readiness runs off the loop | `async def` | `test_readiness_reads_off_the_event_loop` |
| M12 | readiness 500 mapping | catch changed to `KeyError` | `test_readiness_of_an_incomplete_configuration_is_the_existing_500` |
| M13 | C16, Python model | `verdict_notes` dropped | 43 tests, including the join test `test_the_client_run_keys_are_exactly_the_server_evidence_fields` |
| M14 | `_evidence_from_row` | `verdict=None` | 7 tests: the verdict-200 tests, identical re-submit, re-stamp ×4 |
| M15 | returned evidence is fresh | `session.refresh(row)` dropped (verdict writer copy only) | 7 tests: the verdict-200 tests ×2, `test_an_approval_writes_the_four_verdict_columns_and_nothing_else`, re-stamp ×4 |
| M16 | strict body | `extra="ignore"` | 9: `test_a_verdict_body_cannot_choose_any_server_owned_value[*]` |
| M17 | `invalid_verdict` code | draft envelope | 16 tests |
| M18 | C17 codes | `status: str` | `test_readiness_status_codes_are_the_service_codes_not_labels` |
| M20 | principal gate before body or service | dependency replaced by `get_current_user() or "anonymous"` | `test_the_verdict_route_requires_a_trusted_principal_before_body_or_service[None, blank]`, the blank-reviewer 403 test |
| M26 | notes verbatim | notes stripped | `test_a_verdict_route_passes_exactly_the_body_and_the_principal`, `…ordered_invalid_verdict_422[both-ordered]` |
| M28 | 200, not 201 | `status_code=201` | the verdict-200 tests ×2, the passes-exactly test, the off-loop test |
| M30 | readiness exact shape | `run_id` excluded | the 3 readiness route tests |
| M21 **S3b (reviewer target)** | TS keys | the four keys dropped from `TEST_RUN_KEYS` | the Python join test `test_the_client_run_keys_are_exactly_the_server_evidence_fields`, plus 7 Vitest cases |
| M22 | TS pairing when null | null branch returns true | Vitest: reviewer, time or notes with no verdict (3) |
| M23 | TS reviewer type | typeof check dropped | Vitest: verdict with no reviewer, non-string reviewer |
| M24 | TS pairing wired in | `\|\| true` | 8 Vitest cases |
| M25 | TS verdict choices | `'withdrawn'` added | `test_the_client_verdict_choices_are_the_servers` |
| M27 | mocks | `verdict_notes` dropped from the mock | 4 Vitest cases plus `tsc` errors |

The plan's controller target is S3, which is M1. It REDs only `test_a_verdict_body_cannot_choose_any_server_owned_value[reviewer]`: the principal tests do not send a body reviewer. This is exactly the condition that §12 names. The reviewer target is S3b, which is M21. It REDs the join test plus 7 Vitest cases.

## Gates
- **Focused set:** routes, workbench, join and the three other client joins. 785 passed, 0 failed.
- **Full `tests/unit`:** 6 failed, 6760 passed, 110 skipped, 136 warnings. These are exactly the baseline six by node:
  - `test_deploy_autoscaling` ×2;
  - `test_style_exclusivity_chokepoint` ×3;
  - `test_style_exclusivity_persistence_boundary` ×1.

  The warning count matches the baseline.
- **PostgreSQL** (`tests/integration/test_agent_definition_workbench_postgres.py`, one invocation): 36 passed, 0 skipped.
- **Frontend:**
  - `npm run test:unit`: 609 passed. The baseline at dispatch was 597; this task adds 12.
  - `npm run typecheck`: clean.
  - ESLint on the 3 touched TS files: clean.
  - Playwright `agent-definition-workbench.spec.ts` (chromium, one worker): 76 passed. The baseline was 76.
- **`ruff check` against base:** the only findings are the test file's pre-existing I001 and F401, which base also has. A new I001 in the routes file and a new E501 in the test file were fixed.
- `.venv` was absent before and after. Port 3000 was free before and after.

## Concerns
1. **The C17 readiness client-join test is not written.** No TS readiness key lists exist yet: C22 puts `DraftReadiness` and its parser in Task 6, and this task adds no UI or client. What this task does instead:
   - a Python test pins the response models' `status` Literal to the service's `ReadinessStatus` codes;
   - the same test checks the models are strict (`extra="forbid"`) with snake_case field names.

   Task 6 must add the TS key lists and the join test. PLAN-CORRECTIONS §13 already anticipates this ("the new readiness join test once it exists").
2. **`VerdictRequest.verdict` is `str`, not a `Literal`.** This lets the service's `invalid_choice`, `blank` and `too_long` issues appear in one ordered list. The cost is that the OpenAPI schema does not enumerate the two choices. The evidence response does use the `Literal`.
3. **`notes` is required** (it may be null) to keep the body exact-key. Task 6's client must always send it.
4. **Validation order:** body validation runs before the path guard. So an unstorable id with a bad body returns 422, not 404. For a storable id, the order is pinned by `test_the_verdict_body_is_validated_before_the_run_is_looked_up`.
5. **An unknown `IneligibleForApprovalError` reason** raises a `KeyError` in the route, which becomes a 500 (pinned by a test). If #269 adds a reason, it must extend `_INELIGIBLE_MESSAGES` and the response Literal.
6. **`TestCaseReadinessResponse` carries `__test__ = False`** as a pydantic class attribute. It imports cleanly and the full unit suite shows no new collection warning.

## Triple check
- `git status --short` shows only untracked files, and those predate this task: the `.superpowers` SDD files, `.worktrees` and other directories.
- `test ! -e .venv`: yes.
- `lsof -i :3000`: empty.
