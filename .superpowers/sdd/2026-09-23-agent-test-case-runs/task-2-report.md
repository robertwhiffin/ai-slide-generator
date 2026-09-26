# #267 Task 2 report: Agent Test Case CRUD service and admin routes

**Status:** DONE_WITH_CONCERNS (the concerns are advisory; no gate is red)
**TASK_BASE:** `9c75074b20b8a5670b8c99e047d3a933173ed104`
**Commits:**
- `6358cf392` feat: test case CRUD service and admin routes (#267)
- `805c250f9` fix: let the unique constraint refuse a reused test case name (#267). The mutation sweep showed the create path's duplicate-name pre-check was redundant, so a mutation of it left every test GREEN. The pre-check was removed, the mapped unique-constraint loss is now the only guard, and a PostgreSQL proof was added.
- The report commit follows these.

## What was built
- `src/services/agent_test_workbench.py` (new) provides these types:
  - `TestCaseVersion` (a frozen row snapshot);
  - `TestCaseIssue`;
  - `TestCaseRejected(ValueError)`, which sorts its issues by C9's field order;
  - `TestCaseNotFound`;
  - `TestCaseStale`;
  - `AgentTestWorkbench`, with `list_test_cases`, `create_test_case`, `update_test_case` (a supersede) and `deactivate_test_case`.
- Routes were added to the existing router in `src/api/routes/agent_definitions.py`, under `/api/admin/agent-definitions` (C23). There is no second router, and `main.py` is untouched.
  - `GET /test-cases?agent_key=&include_inactive=` returns 200 `{"items": [...]}` in role order, then by name, then by version.
  - `POST /test-cases` returns 201.
  - `PUT /test-cases/{id}` returns 200 with the new version.
  - `DELETE /test-cases/{id}` returns 200 with the retired snapshot. Retiring an already inactive version is idempotent and writes nothing.
  - The error statuses are:
    - 404 `{"detail": "Test case not found"}`;
    - 409 `{"code": "stale_test_case", "test_case_id", "message"}`;
    - 422 `{"code": "invalid_test_case", "issues": [{field, code, message}]}`.
- `src/api/schemas/agent_definitions.py` gains strict sibling DTOs. None of them extends a draft type.
  - Request DTOs, all on `_StrictDraftRequest` (`extra="forbid"`, strict): `TestCaseAssemblyContextRequest`, `CreateTestCaseRequest` and `UpdateTestCaseRequest`.
  - Response DTOs: `TestCaseResponse`, with `is_synthetic_data_warning: Literal[True] = True`, plus `TestCaseListResponse`, `TestCaseValidationErrorResponse` and `TestCaseConflictResponse`.
- **Envelope ruling:** I used C9's named case envelope, `invalid_test_case` with `issues`, not the draft's `invalid_draft`/`errors`. C9 names that body explicitly, and corrections override the plan. Its item type reuses `DraftFieldErrorResponse`. Pydantic body errors go through the existing `_request_validation_errors` renderer, so the same codes appear (`extra_forbidden`, `strict_type`, and `invalid_json` at `$`). No new renderer was written.

## Corrections satisfied
- **C9:**
  - Each write takes `SELECT … FROM agent_test_case WHERE agent_key = :k ORDER BY id FOR UPDATE`, with no `is_active` filter, using `populate_existing`. It then re-reads the role (a fresh READ COMMITTED snapshot) and decides from those rows.
  - It takes no L0 lock and makes no remote call.
  - Three writes are refused with an exact ordered 422 before any row changes: deactivating a role's last active required case (`is_active`/`last_required_case`), updating it with `is_required=False` (`is_required`/`last_required_case`), and any supersede with the same effect.
  - Issues are ordered `name, synthetic_payload, assembly_context, is_required, is_active`. `actor` and `agent_key` come before them.
  - A two-session PostgreSQL test covers the race: `test_two_sessions_retiring_a_roles_last_two_required_cases_serialize_and_one_is_refused[seed|second]`.
- **C22:**
  - A supersede retires the old row, flushes, then inserts `version + 1` with the same name, in one transaction.
  - The old row changes only in `is_active`, `updated_by` and `updated_at`. Exact tuple comparisons pin this in unit and PostgreSQL tests, and the row is unchanged by later supersedes.
  - A rename is 422 `name_immutable`. An echoed unchanged name is accepted.
  - A new case reusing a role's name is 422 `duplicate_name`, even when the old lineage is retired. The unique constraint carries this, recognised by constraint name on PostgreSQL and by message on SQLite.
  - Updating an inactive version, or losing the unique constraint, is 409 `stale_test_case`.
  - There is no sentinel. The payload is a JSON object of at most 65536 bytes, serialized compactly with `allow_nan=False`. `assembly_context` is exactly `{design_system_active: bool}`, and `name` is trimmed, non-blank and at most 200 characters.
- **C23 / C36:**
  - Bodies are parsed only after `require_admin` (on the router) and `require_draft_write_principal` succeed. Tests cover 403-before-parse and 403-before-service for all four routes, plus the missing or blank principal for the three writes.
  - **C36 ruling:** the case routes call no model, so C36's mandatory rule does not bind them. However, the writer can wait on another session's L2 row lock, and a lock wait on the event loop stalls every request, which is the same failure class. So it runs off the loop:
    - POST and PUT are `async` (they must `await request.json()`) and use `run_in_threadpool`;
    - GET and DELETE have no body and are plain `def`, which FastAPI runs in its threadpool.
  - Loop-observer tests cover all four routes. Cost if wrong: none; it is conservative.
- **P2/P3/P5/P7:**
  - `name` is immutable.
  - `test_replacing_the_only_required_case_is_add_then_retire` pins the add-then-retire order.
  - Only active versions are listed by default, and superseded versions are 409 on write. P5 applies to running a case, which is Task 4.
  - The synthetic-data rule is a display flag only.
- **Unchanged:** bootstrap, seed, `graph_configuration*.py`, `main.py` and the frontend. `git diff --name-only` against TASK_BASE is exactly the six planned files.

## RED before implementation
- `tests/unit/test_agent_test_workbench.py`: collection error, `ModuleNotFoundError: No module named 'src.services.agent_test_workbench'`.
- Route tests: 38 failed. 32 got 404, because the routes were missing: `assert 404 == 403/422/200/201`.
- `test_main_app_registers_the_dedicated_workbench_route`: `assert 0 == 2` for the new test-cases path. I extended it for the four new routes, and it now counts one route object per method.
- The PostgreSQL tests were written after implementation. Their RED proof is the mutation table: the C9 FOR UPDATE drop gives `outcomes={'second': 'committed', 'seed': 'committed'}; bootstrap afterwards=GraphConfigurationIntegrityError('active required Agent Test Cases do not cover every graph role')`. That is exactly C9's predicted sabotage RED.

## Clause-to-mutation table (driver `/tmp/t267-2/mutate.py`, GREEN pinned at `805c250f9`)
- **Unit scope:** `tests/unit/test_agent_test_workbench.py` plus `tests/unit/test_agent_definition_workbench_routes.py`.
- **PostgreSQL scope:** `tests/integration/test_agent_definition_workbench_postgres.py -k "case_versions or last_two_required"`, only for rows that touch C9 locking or C22 versioning.
- **Procedure for each row:**
  - The anchor count is asserted to be exactly 1 before the mutation.
  - The mutation inserts a marker, whose `grep -c` must be 1, so every mutation is proven to execute.
  - After the run, the file is restored from the pinned SHA and must `git diff --exit-code` clean.
  - The final GREEN was 325 unit and 3 PostgreSQL passed, with an empty `git status --porcelain`.
- **Truncated names:** test IDs with spaces in their parameters are cut off at the space by the driver's regex, for example `test_create_rejects_a_blank_name[` for the `"   "` case.

| ID | Clause | File | Anchor | Marker `grep -c` | Unit RED | PG RED | Restore | GREEN |
|---|---|---|---|---|---|---|---|---|
| C9-FOR-UPDATE | C9 L2 lock is FOR UPDATE | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C9-FOR-UPDATE` = 1 | 1 failed: `test_the_role_lock_statement_is_for_update_over_every_row_of_the_role` | 2 failed: `test_two_sessions_retiring_a_roles_last_two_required_cases_serialize_and_one_is_refused[second]`<br>`test_two_sessions_retiring_a_roles_last_two_required_cases_serialize_and_one_is_refused[seed]` | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C9-NO-ACTIVE-FILTER | C9 L2 lock has no is_active filter | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C9-NO-ACTIVE-FILTER` = 1 | 1 failed: `test_the_role_lock_statement_is_for_update_over_every_row_of_the_role` | 3 passed (GREEN; see note) | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C9-GUARD-RETIRE | C9 refuse retiring last active required | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C9-GUARD-RETIRE` = 1 | 10 failed: `test_delete_test_case_of_the_last_required_case_is_the_exact_422`<br>`test_deactivating_a_roles_last_active_required_case_is_refused[architect]`<br>`test_deactivating_a_roles_last_active_required_case_is_refused[build_reviewer]`<br>`test_deactivating_a_roles_last_active_required_case_is_refused[builder]`<br>`test_deactivating_a_roles_last_active_required_case_is_refused[data_analyst]`<br>`test_deactivating_a_roles_last_active_required_case_is_refused[deck_reviewer]`<br>`test_deactivating_a_roles_last_active_required_case_is_refused[fix_reviewer]`<br>`test_deactivating_a_roles_last_active_required_case_is_refused[fixer]`<br>`test_optional_and_inactive_rows_do_not_count_as_required_coverage`<br>`test_replacing_the_only_required_case_is_add_then_retire` | 2 failed: `test_two_sessions_retiring_a_roles_last_two_required_cases_serialize_and_one_is_refused[second]`<br>`test_two_sessions_retiring_a_roles_last_two_required_cases_serialize_and_one_is_refused[seed]` | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C9-GUARD-UNREQUIRE | C9 refuse un-require/supersede of last required | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C9-GUARD-UNREQUIRE` = 1 | 4 failed: `test_put_test_case_rename_and_last_required_are_one_ordered_422`<br>`test_put_test_case_unrequiring_the_last_required_case_is_the_exact_422`<br>`test_a_refused_supersede_reports_every_issue_in_field_order`<br>`test_unrequiring_the_last_active_required_case_is_refused` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C9-ORDER | C9 issues ordered by field | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C9-ORDER` = 1 | 1 failed: `test_a_refused_supersede_reports_every_issue_in_field_order` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-RETIRE-OLD | C22 supersede retires the old row | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C22-RETIRE-OLD` = 1 | 5 failed: `test_put_test_case_returns_the_new_version_and_retires_the_old`<br>`test_a_historical_row_is_never_modified_after_its_own_retirement`<br>`test_list_filters_by_role_and_can_include_inactive_versions`<br>`test_list_returns_active_versions_in_role_order_by_default`<br>`test_update_supersedes_the_old_row_and_inserts_the_next_version` | 1 failed: `test_postgres_case_versions_are_new_rows_and_every_write_records_its_actor` | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-VERSION-PLUS-1 | C22 successor is version + 1 | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C22-VERSION-PLUS-1` = 1 | 5 failed: `test_put_test_case_returns_the_new_version_and_retires_the_old`<br>`test_a_historical_row_is_never_modified_after_its_own_retirement`<br>`test_list_filters_by_role_and_can_include_inactive_versions`<br>`test_list_returns_active_versions_in_role_order_by_default`<br>`test_update_supersedes_the_old_row_and_inserts_the_next_version` | 1 failed: `test_postgres_case_versions_are_new_rows_and_every_write_records_its_actor` | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-NAME-IMMUTABLE | C22 rename is 422 name_immutable | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C22-NAME-IMMUTABLE` = 1 | 3 failed: `test_put_test_case_rename_and_last_required_are_one_ordered_422`<br>`test_a_refused_supersede_reports_every_issue_in_field_order`<br>`test_update_accepts_the_unchanged_name_and_rejects_a_rename` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-STALE | C22 update of inactive version is 409 stale | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C22-STALE` = 1 | 1 failed: `test_update_of_a_superseded_or_retired_version_is_stale` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-UNIQUE-409 | C22 unique-constraint loss maps to stale | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C22-UNIQUE-409` = 1 | 1 failed: `test_a_unique_constraint_loss_is_reported_as_stale` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-CONTEXT-EXACT | C22 assembly_context exactly {design_system_active} | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C22-CONTEXT-EXACT` = 1 | 1 failed: `test_create_requires_the_assembly_context_to_be_exactly_design_system_active[context3]` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-PAYLOAD-64KIB | C22 payload <= 64 KiB | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C22-PAYLOAD-64KIB` = 1 | 1 failed: `test_create_bounds_the_serialized_synthetic_payload_at_64_kib` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-NAME-200 | C22 name <= 200 chars | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C22-NAME-200` = 1 | 1 failed: `test_create_rejects_a_name_longer_than_200_characters_after_trimming` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| PLAN-BLANK-NAME | plan: blank name is ValueError | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-PLAN-BLANK-NAME` = 1 | 5 failed: `test_post_test_case_projects_the_ordered_domain_rejection`<br>`test_create_orders_every_issue_by_field`<br>`test_create_rejects_a_blank_name[`<br>`test_create_rejects_a_blank_name[\t\n]`<br>`test_create_rejects_a_blank_name[]` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| PLAN-IDEMPOTENT | plan: second deactivation idempotent | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-PLAN-IDEMPOTENT` = 1 | 1 failed: `test_deactivate_retires_without_deleting_and_is_idempotent` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| PLAN-ACTOR | plan: nonblank trusted principal | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-PLAN-ACTOR` = 1 | 3 failed: `test_every_write_requires_a_nonblank_trusted_actor[`<br>`test_every_write_requires_a_nonblank_trusted_actor[None]`<br>`test_every_write_requires_a_nonblank_trusted_actor[]` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-DUPLICATE-NAME | C22 a new case needs a new name | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-C22-DUPLICATE-NAME` = 1 | 1 failed: `test_create_rejects_a_name_already_used_by_the_role_even_when_retired` | 1 failed: `test_postgres_case_versions_are_new_rows_and_every_write_records_its_actor` | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| LIST-ACTIVE-DEFAULT | list shows active versions by default | `src/services/agent_test_workbench.py` | 1 | `MUT267-2-LIST-ACTIVE-DEFAULT` = 1 | 1 failed: `test_list_returns_active_versions_in_role_order_by_default` | not run | `git checkout 805c250f9 -- src/services/agent_test_workbench.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C23-PRINCIPAL | C23 actor from require_draft_write_principal | `src/api/routes/agent_definitions.py` | 1 | `MUT267-2-C23-PRINCIPAL` = 1 | 4 failed: `test_delete_test_case_deactivates_and_returns_the_snapshot`<br>`test_post_test_case_returns_201_with_the_exact_snapshot`<br>`test_test_case_writes_require_a_trusted_principal_before_body_or_service[`<br>`test_test_case_writes_require_a_trusted_principal_before_body_or_service[None-POST-<function` | not run | `git checkout 805c250f9 -- src/api/routes/agent_definitions.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C36-THREADPOOL | writer off the event loop | `src/api/routes/agent_definitions.py` | 1 | `MUT267-2-C36-THREADPOOL` = 1 | 1 failed: `test_test_case_routes_run_the_locking_writer_off_the_event_loop[POST]` | not run | `git checkout 805c250f9 -- src/api/routes/agent_definitions.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| PLAN-WARNING-FIELD | is_synthetic_data_warning Literal[True] | `src/api/schemas/agent_definitions.py` | 1 | `MUT267-2-PLAN-WARNING-FIELD` = 1 | 4 failed: `test_delete_test_case_deactivates_and_returns_the_snapshot`<br>`test_get_test_cases_lists_active_versions_with_the_exact_item_shape`<br>`test_post_test_case_returns_201_with_the_exact_snapshot`<br>`test_put_test_case_returns_the_new_version_and_retires_the_old` | not run | `git checkout 805c250f9 -- src/api/schemas/agent_definitions.py`, `git diff --exit-code` clean | 325 unit, 3 PG |
| C22-DTO-CONTEXT-STRICT | wire assembly_context extra=forbid | `src/api/schemas/agent_definitions.py` | 1 | `MUT267-2-C22-DTO-CONTEXT-STRICT` = 1 | 1 failed: `test_post_test_case_accepts_only_the_strict_create_body[context-extra]` | not run | `git checkout 805c250f9 -- src/api/schemas/agent_definitions.py`, `git diff --exit-code` clean | 325 unit, 3 PG |

- **Not ran:** the plan's own Step-6 sabotage (removing the `GRAPH_V1_AGENT_KEYS` guard), because the brief assigns it to the controller or reviewer. C9's "drop FOR UPDATE" sabotage is included above, because I ran it while developing the two-session test.
- **Note on `C9-NO-ACTIVE-FILTER`:** the PostgreSQL two-session test stays GREEN under this mutation. With the filter, PostgreSQL's re-check drops the row the first session retired, but the session still locks B and the re-read still counts only B, so the refusal still happens. The unit compile test `test_the_role_lock_statement_is_for_update_over_every_row_of_the_role` is the pin (RED 1). The filter does become harmful in the shape C9 describes, where both sessions' locks would miss an already-retired row. The pin is a textual check of the statement, not a behavioural one.
- **Unpinned by design:** `populate_existing` and the post-lock re-read. They are defensive:
  - no entity is loaded before the lock (`_lock_role_of` reads only the `agent_key` column);
  - without the re-read, the effect is over-refusal, never under-refusal;
  - a concurrent insert that the lock's snapshot missed is also caught by the unique constraint.

## Gates (at `805c250f9`)
- **Focused:** 379 passed. The files are `test_agent_test_workbench` (53), `test_agent_definition_workbench_routes` (272), `test_graph_configuration_bootstrap` and `test_graph_configuration_models`. `test_ci_collects_integration_tests` was also green (393 with it, at `6358cf392`).
- **Full `tests/unit -q -p no:randomly -rf`** (`DATABASE_URL=sqlite:////tmp/t267-2-full.sqlite`): **6 failed, 6292 passed, 110 skipped, 136 warnings.**
  - The failures are exactly the baseline six node IDs and causes: autoscaling `'provisioned' == 'autoscaling'` and "called 0 times", chokepoint `_FakeSession.execute` ×3, and persistence-boundary "no active Graph Release".
  - Passed went from 6202 to 6292, which is +90 (53 service tests plus 37 new route tests). The skip and warning counts are unchanged.
- **PostgreSQL** (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, one invocation each, zero skips):
  - two-session last-required: 2 passed;
  - constraints: 66 passed;
  - bootstrap: 3 passed;
  - workbench: 20 passed (was 17, +3).
- **New PostgreSQL file:** none. The tests went into the planned `test_agent_definition_workbench_postgres.py`, so `test_ci_collects_integration_tests.py` and `test.yml` needed no enrolment.
- **Ruff:** 0 new findings. The only two findings (I001 and F401 in `test_agent_definition_workbench_routes.py`) are byte-identical at TASK_BASE.
- **Environment:** `test ! -e .venv` held before and after. Nothing was installed. `ai_slide_generator` was untouched: every run set `DATABASE_URL` to `/tmp`, and the PostgreSQL fixtures use throwaway databases.

## #269 assumptions (from its ledger and PLAN-CORRECTIONS, read-only)
- **Q8, SATISFIED:** a new version is a new row with a new `id`, the same `(agent_key, name)` and `version + 1`. The old row is retired in the same transaction. #269's gate keys on `(test_case_id, test_case_version)`, so an approval of v1 can never satisfy v2, and v1 is inactive so the gate never selects it.
- **Q9, SATISFIED (L2 only, as #267's C9 and the ledger ruled):**
  - Case writers take L2 `FOR UPDATE` on the role's rows by `id`, with no L0.
  - The new row's insert has no FK to `graph_release` or `graph_draft`, so it takes no implicit L0 `KEY SHARE`.
  - This is a prefix-respecting subsequence of #269's global order, and the writer never waits on L0 while holding L2. Both lockers take ascending `id`, so the gate's L2 `FOR SHARE` (L0 then L2) and the case writer cannot deadlock.
- **#269 plan line 206 / C20 (M6), STRONGER THAN ASSUMED:**
  - C20 narrowed the L2 claim because it believed re-versioning is an insert that a row lock cannot block.
  - Under C22, a supersede *updates* the old row (`is_active = False`) before inserting. So the gate's L2 `FOR SHARE` on the active required row now blocks re-versioning as well as deactivation.
  - `test_case_version_bump_after_approval_is_not_ready` should assert this supersede mechanism: the old row is retired and the new row has a new id.
  - What L2 does NOT block is a brand-new case, a new `name`, created in a changed role between readiness and link. It is an insert, and the gate's statement snapshot will not see it. This is the one residual window. Flag it for #269 Task 4. It is benign for boot safety.
- **#269 C1 / Task 4 `test_changed_role_without_active_required_case_is_not_ready` and C21 SQLite route test, BRANCH DECIDED:** "Deactivate architect's only required case, using #267's case writer if the Task 0-B probe shows it allows this; otherwise use an ORM update". The writer **refuses** this (C9), so #269 must take the ORM-update branch in both tests.
- **#269 C1 carry-forward (writer must refuse the last required case), SATISFIED:** see C9 above.

## Concerns (advisory)
1. Every update supersedes, even one identical to the current version. That bumps the version and orphans approvals of the old id. I did not add an "unchanged" short-circuit because nothing specifies one. This needs a Task 4, #268 or #269 decision if the UI resubmits unchanged forms.
2. `duplicate_name` is a new issue code that C22 implies ("a new case with a new `name` starts at version 1") but does not name. A retired lineage's name can never be reused.
3. The 404 uses FastAPI's standard `{"detail": ...}` rather than a typed envelope, to avoid inventing one.
4. Query-parameter type errors on GET, such as `include_inactive=maybe`, get FastAPI's default 422 envelope, not `invalid_test_case`. A non-integer `{test_case_id}` path segment behaves the same way. Authorization still comes first.
5. Existing async routes in this file (the upgrade routes and legacy-source) still run their locking facade on the event loop. This is pre-existing, and Task 2 did not touch it. It may be worth a whole-branch note given my C36 ruling.

## Fix round 1 (review `task-2-review.md`: I1–I3; base pinned `78badbcd1`)
**Commits:**
- `fd4e9cb59` fix: make identical test case saves a no-op and pin the atomic supersede (#267)
- `191ff54d6` test: pin that a failed retirement leaves no committed successor (#267). This is an extra I2 pin. The sweep showed the insert-then-retire split, with a driver-level commit, stayed GREEN under the commit counter.

### I1: an identical save is a no-op
- **Where the check sits:** inside the lock, after the 422 issues (name included) and the inactive-row 409.
- **Rule:** if `is_required` matches and the payload and context are canonically identical, the current version is returned. There is no retire, no new row, and no approval is orphaned.
- **Comparison:** `_canonical_json` uses `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, never `==`.
- **Pins:**
  - identical content with a different key order gives the same id and version, and the rows are unchanged;
  - five type-only changes are real new versions: `1→True`, `1→1.0`, `True→1`, `0→False`, `1.0→1`;
  - a change to any single field is a new version;
  - PostgreSQL `test_postgres_identical_save_is_a_no_op_but_a_type_change_is_a_new_version` checks the JSONB round-trip.
- **RED before the fix:** with the service file at base, `test_an_identical_update_is_a_no_op_returning_the_current_version` failed (1 failed, 64 passed).

### I2: the supersede is atomic
Three pins cover it:
- `test_an_update_commits_exactly_once` counts the session's `after_commit` events.
- `test_a_failed_successor_insert_leaves_the_old_version_active` injects a failure into the successor `INSERT`. It then checks that the rows are unchanged, the old row is still active and required, and bootstrap passes.
- `test_a_failed_retirement_leaves_no_successor_behind` injects a failure into the retiring `UPDATE`. It then checks that no successor exists and v1 is the only active version.

### I3: optional rows present
- The two-session PostgreSQL test now includes an active optional architect case, and asserts that case is untouched afterwards.
- A new unit test covers the update path: `test_an_active_optional_case_does_not_stop_the_unrequire_refusal`.

### Sabotage (driver `/tmp/t267-2/fix1-mutate.py`, GREEN pinned `191ff54d6`)
- Each row had anchor count 1 and marker `grep -c` of 1, and was restored by `git checkout` with a clean diff.
- The final GREEN was 338 unit and 21 PostgreSQL passed, with an empty status.

| ID | Mutation | Unit RED | PG RED |
|---|---|---|---|
| I1-EQ | no-op payload comparison uses `==` | 5: `test_a_type_only_payload_change_is_a_real_new_version[int-to-bool, int-to-float, bool-to-int, zero-to-false, float-to-int]` | 1: `test_postgres_identical_save_is_a_no_op_but_a_type_change_is_a_new_version` |
| I2-RETIRE-COMMIT-THEN-INSERT | retire flushed, then a DBAPI commit, then the insert | 1: `test_a_failed_successor_insert_leaves_the_old_version_active` | 0 (unit is the pin) |
| I2-INSERT-COMMIT-THEN-RETIRE | insert flushed, then a DBAPI commit, then the retire | 1: `test_a_failed_retirement_leaves_no_successor_behind` | 0 (unit is the pin) |
| I3-COUNT-IGNORES-REQUIRED | `_active_required_count` counts `is_active` only | 2: `test_an_active_optional_case_does_not_stop_the_unrequire_refusal`, `test_optional_and_inactive_rows_do_not_count_as_required_coverage` | 2: `test_two_sessions_retiring_…_one_is_refused[seed]`, `[second]` |

- **Commit-counter note:** `test_an_update_commits_exactly_once` catches a split made with a *session-level* commit. An earlier variant called `session.commit()` inside the `with session.begin()` block, and the counter test was among the failures. That run was noisy, though: other tests failed for an unrelated reason (`InvalidRequestError: Can't operate on closed transaction inside context manager`). So the clean proofs for splits are the two injected-failure tests. A raw driver-level commit is invisible to any SQLAlchemy commit event.

### Gates
- **Focused** (`test_agent_test_workbench`, `test_agent_definition_workbench_routes`, `test_graph_configuration_bootstrap`): 365 passed.
- **Full `tests/unit`** (`DATABASE_URL=sqlite:////tmp/t267-2.sqlite`): 6 failed, 6305 passed, 110 skipped, 136 warnings. The failures are exactly the baseline six nodes and causes. Passed rose by 13: 12 unit tests from `fd4e9cb59` and 1 from `191ff54d6`.
- **PostgreSQL workbench:** 21 passed, zero skips.
- **Ruff:** clean on the changed files.
- **Environment:** `test ! -e .venv` held before and after.

## Fix round 2 (scoped re-review; base pinned `1675d6b0a`)
**Commit:** `f350a2e42` test: pin that an identical save to a superseded case is still stale (#267). It changes tests only.

- **The gap:** moving the no-op check above the inactive-row 409 stayed GREEN. Every stale test submitted content that differed from the stored row.
- **The new pins:** each submits content byte-identical to the inactive row's stored name, payload, context and `is_required`. Each asserts 409 `stale_test_case` with no row change.
  - `test_agent_test_workbench.py::test_an_identical_save_to_an_inactive_version_is_still_stale[superseded|retired]`
  - `test_agent_definition_workbench_routes.py::test_put_identical_content_to_a_superseded_version_is_409_stale`. This one also checks the exact 409 body through the route.
- **Sabotage `MUT267-2F2-NOOP-FIRST`:** the no-op block was moved above `if not old.is_active: raise TestCaseStale`.
  - Each of the three anchors (the stale block, the no-op start and the no-op end) had count 1, and the marker `grep -c` was 1.
  - RED: 3 failed, 338 passed. The failures were exactly the three new tests.
  - Restored with `git checkout f350a2e42 -- src/services/agent_test_workbench.py`, and `git diff --exit-code` was clean.
  - GREEN afterwards: 341 passed.
- **Gates:**
  - The two unit files: 341 passed.
  - Full `tests/unit` (`DATABASE_URL=sqlite:////tmp/t267-2.sqlite`): 6 failed, 6308 passed, 110 skipped, 136 warnings. The failures are exactly the baseline six nodes and causes. Passed rose by 3, the new tests.
  - Ruff was clean, and `test ! -e .venv` held before and after.
  - No temp worktree was used. Every run was from inside `.worktrees/issue-267-plan`, so `src` resolved to this worktree.
