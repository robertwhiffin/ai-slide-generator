# Task 3 report: `AgentRuntime.run_candidate` and the deterministic fake adapter (#267)

**Status:** DONE_WITH_CONCERNS. The concerns are rulings for the controller to confirm; nothing fails.
- TASK_BASE: `dec69b3651a9b75bc68932e36d2d91b10ccd6c93`.
- Implementation commit: `fac5571f8`. This report is committed on its own.
- The driver and raw output are in `/tmp/t267-3/`: `red.txt`, `full.txt`, `mutate.py`, `mutations.json` and `table.md`.

## What changed

### `src/services/agent_runtime.py`

**`run_candidate`.** The signature is `run_candidate(agent_key, candidate_content, candidate_hash, payload, assembly_context) -> CandidateRunOutcome`. It runs four checks, in this order:
1. The role must be a known role. Otherwise it raises `UnknownAgentKeyError`, as `run` does (C14).
2. The content's role must match `agent_key`. Otherwise it raises `ValueError`.
3. The hash must match the content. Otherwise it raises `ValueError("candidate_hash does not match candidate_content")`.
4. The context must carry no session IDs. Otherwise it raises `ValueError` (see ruling R2).

After the checks, it builds a `ResolvedDefinition` with the `-1` sentinels and returns through `self._run_resolved(..., _raw_output_observer=observe)`. It never calls `run`, the loader, `bind_structured_output_model`, `saved_model_configuration` or `_write_locked_content` (C12, C31).

**Sentinels.** `CANDIDATE_RUN_GRAPH_VERSION`, `CANDIDATE_RUN_GRAPH_RELEASE_ID` and `CANDIDATE_RUN_REVISION_ID` are all `-1`. They are defined in `agent_runtime.py`. The plan put them in `persisted_graph_release.py`; C27 overrides that.

**`CandidateRunOutcome`.** Its fields are `status`, `result`, `raw_output`, `error` and `error_detail`. The caller checks above raise. Every failure after them is returned as an outcome, classified by `_classify_candidate_failure` (C15, C16, C33, C34):

| Failure | Status | `error_detail` |
|---|---|---|
| `PersistedConfigurationUnavailableError` | `assembly_error` | the error's code |
| `PinnedInvocationEndpointError` | `model_error` | `endpoint_unavailable:<endpoint>` |
| `NotImplementedError` | `model_error` | `structured_output_unsupported:<endpoint>` |
| `AgentOutputValidationError`, pydantic `ValidationError`, or langchain `OutputParserException` | `incomplete` | `invalid_output:<Class>` |
| Any other exception | `model_error` | `unexpected_error:<Class>` |

- An unexpected error is also logged server-side with its traceback, per C16.
- `error_detail` never contains exception text.

**Raw-output observer.** `_run_resolved` gains a private, keyword-only `_raw_output_observer`. It receives `_supplied_output_keys(...)` immediately before `validate_output` runs.
- `raw_output` is stored as `to_jsonable_python(..., fallback=str)`.
- `run` passes no observer. An AST comparison confirms that `run` and `get_agent_runtime` are source-identical to base.

**Adapter transport options.** `DatabricksModelAdapter` takes a keyword-only `transport_options=None` and forwards it to `bind_structured_output_model`.
- With the default `None`, the production model-factory kwargs are byte-identical. The pinned test at `test_agent_runtime.py:645-677` passes unedited.
- The helper's docstring now names both bounded callers.

**`get_agent_test_runtime()`.** It is `lru_cache`d and uses production's loader and logging sink. Its adapter is `DatabricksModelAdapter(transport_options={"timeout": 120.0, "max_retries": 0})`. The two values are the constants `TEST_RUN_TIMEOUT_SECONDS` and `TEST_RUN_MAX_RETRIES` (C33).

### `tests/fixtures/deterministic_model_adapter.py` (new, C26; never in `src/`)
- **`FAKE_OUTPUTS`:** moved verbatim from the `VALID_OUTPUT_VALUES` table in both suites. Both suites now import it.
- **`fake_output()`:** returns a fresh copy of a role's fake output.
- **`DeterministicFakeModelAdapter`:** records `FakeModelCall(agent_key, schema, prompt, configuration)`. That is a superset of C26's `(agent_key, schema, prompt)`. Its modes are:
  - `success`
  - `provider_unavailable`
  - `invalid_optional_field`
  - `provider_parse_error`
  - `structured_output_unsupported`
  - `pause`, which sets an `entered` event and waits on a `release` event (for C8).

### Tests
- `tests/unit/test_agent_runtime.py`: 62 new node IDs.
- `tests/unit/test_persisted_agent_runtime.py`: 4 new node IDs.
- `tests/unit/test_persisted_graph_release.py`: 1 new node ID. It shows that `run(-1, …)` still raises `GraphReleaseNotFoundError` against a bootstrapped database (C27).

## Rulings made here (for the controller)

**R1 — the identity sink.** A candidate run goes through the same sink that `_run_resolved` always calls.
- It carries the sentinel identity `(-1, -1, agent_key, -1, candidate_hash, "", "")`.
- The logging sink's record is exactly `SUCCESS_LOG_FIELDS` (success) or `PERMITTED_LOG_FIELDS` (error). No new field or message is added.
- No real release or revision ID is attached. In particular, the draft's base release is not used.
- `-1` cannot collide with a SERIAL ID, so a record can always be identified as a candidate run.
- This differs from #266's probe, which never reaches the runtime and so logs nothing. Not logging here would need a second sink parameter on `_run_resolved`, which is a larger divergence from `run`.
- Cost if wrong: anything that aggregates `persisted_agent_invocation` records by release sees a `-1` bucket.

**R2 — session IDs are refused, not stripped.** A test run belongs to no conversation. So `run_candidate` raises if the context carries `root_session_id` or `actor_session_id`. The prompt never contained them anyway: the assembler reads only `design_system_active`.

**R3 — payload projection is not done here.**
- C37 and the C40 table assign `src/services/agent_model_payload.py` and `tests/fixtures/model_payload_keys.py` to Task 4, so this task created neither.
- The runtime does not filter the payload (C10, C37: "the runtime must not filter"). Removing identifiers from what the model sees stays with Task 4's projection.
- A parity test shows that `run_candidate` and `run` produce the same prompt bytes, schema and configuration for the same content and payload. It covers 7 roles × both `design_system_active` values × v1 and v2 assembly (28 cases).

**R4 — what raises and what returns.** Caller-contract violations raise; every other failure is an outcome. Task 4 maps the raised `ValueError` to `assembly_error`, per C16.

## RED (before implementation)
One invocation over the three test files gave **62 failed, 174 passed**. Every failure was the feature being absent:
- 57 × `AttributeError: 'AgentRuntime' object has no attribute 'run_candidate'`.
- `TypeError: DatabricksModelAdapter.__init__() got an unexpected keyword argument 'transport_options'`.
- `ImportError: cannot import name 'CANDIDATE_RUN_GRAPH_RELEASE_ID'`.
- The AST delegation test: `type object 'AgentRuntime' has no attribute 'run_candidate'`.
- No `get_agent_test_runtime`.
- No `CANDIDATE_RUN_GRAPH_VERSION`.

Some new tests passed before the implementation, by design:
- **Regression pins:**
  - `test_production_run_passes_no_raw_output_observer`
  - `test_run_still_raises_the_validation_error_it_always_raised`
  - `test_the_production_runtime_adapter_still_hands_no_transport_options`
- **Guards that stay vacuous until a caller exists:** the call-site guards and the one-binding guard.

The mutations below show each of these can fail (M18, M20–M23).

## Clause-to-mutation table
`/tmp/t267-3/mutate.py` ran every row from inside the worktree, the same way for each:
- **Anchor:** the edited text occurs exactly once, asserted before the edit.
- **Marker:** `grep -c` returns 1, on the mutated line, which the tests execute.
- **Scope:** `tests/unit/test_agent_runtime.py`, `tests/unit/test_persisted_agent_runtime.py` and `tests/unit/test_persisted_graph_release.py`. The command is the brief's PYTHONPATH/pyenv pytest command with `-q -p no:randomly -rf` and `DATABASE_URL=sqlite:////tmp/t267-3-mut.sqlite`.
- **Restore:** `git checkout fac5571f8 -- <file>`, then the marker count is 0 and `git diff --quiet fac5571f8 -- <file>` is clean.

After all restores the scope is GREEN: **236 passed**, and `grep -rn T267_3_M src tests` finds nothing.

As instructed, I did not run the controller or reviewer sabotage that C33 assigns: building the test runtime with the default adapter, or giving `transport_options` a non-empty default. The kwargs tests those target are the ones M15 and M16 turn RED.

| Clause | File | Anchor | Marker | RED | Failing tests | Restore |
|---|---|---|---|---|---|---|
| M01 role check first (C12.1/C14) | `src/services/agent_runtime.py` | 1 | `T267_3_M01` = 1 | 3 failed, 233 passed | `test_run_candidate_rejects_an_unknown_or_deterministic_role_first` ×3 | marker after restore 0, clean=True |
| M02 content-role check (C12.2) | `src/services/agent_runtime.py` | 1 | `T267_3_M02` = 1 | 1 failed, 235 passed | `test_run_candidate_rejects_content_for_another_role_before_the_hash` | marker after restore 0, clean=True |
| M03 hash check (C12.3; plan Step 4) | `src/services/agent_runtime.py` | 1 | `T267_3_M03` = 1 | 1 failed, 235 passed | `test_run_candidate_rejects_a_hash_that_does_not_match_the_content` | marker after restore 0, clean=True |
| M04 check order: hash before content role (C12) | `src/services/agent_runtime.py` | 1 | `T267_3_M04` = 1 | 1 failed, 235 passed | `test_run_candidate_rejects_content_for_another_role_before_the_hash` | marker after restore 0, clean=True |
| M05 no session identity (user decision) | `src/services/agent_runtime.py` | 1 | `T267_3_M05` = 1 | 2 failed, 234 passed | `test_run_candidate_refuses_a_session_identity` ×2 | marker after restore 0, clean=True |
| M06 sentinel release id on identity (C27) | `src/services/agent_runtime.py` | 1 | `T267_3_M06` = 1 | 12 failed, 224 passed | `test_a_candidate_run_error_record_is_the_exact_error_set_with_sentinels` ×3; `test_a_candidate_run_success_record_is_the_exact_success_set_with_sentinels`; `test_a_provider_endpoint_error_names_the_sentinel_release_not_a_real_one`; `test_run_candidate_runs_every_role_through_the_fake_and_records_the_sentinel_identity` ×7 | marker after restore 0, clean=True |
| M07 sentinel value is -1, never a real id (C27) | `src/services/agent_runtime.py` | 1 | `T267_3_M07` = 1 | 14 failed, 222 passed | `test_a_candidate_run_error_record_is_the_exact_error_set_with_sentinels` ×3; `test_a_candidate_run_success_record_is_the_exact_success_set_with_sentinels`; `test_a_provider_endpoint_error_names_the_sentinel_release_not_a_real_one`; `test_candidate_run_sentinels_are_negative_runtime_identity_constants`; `test_run_candidate_runs_every_role_through_the_fake_and_records_the_sentinel_identity` ×7; `test_the_candidate_sentinel_release_id_never_resolves_through_run` | marker after restore 0, clean=True |
| M08 observer called (C15 sabotage) | `src/services/agent_runtime.py` | 1 | `T267_3_M08` = 1 | 9 failed, 227 passed | `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2; `test_run_candidate_runs_every_role_through_the_fake_and_records_the_sentinel_identity` ×7 | marker after restore 0, clean=True |
| M09 observer before validate_output (C15/C34) | `src/services/agent_runtime.py` | 1 | `T267_3_M09` = 1 | 2 failed, 234 passed | `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2 | marker after restore 0, clean=True |
| M10 never resolves a release (C12) | `src/services/agent_runtime.py` | 1 | `T267_3_M10` = 1 | 51 failed, 185 passed | `test_a_candidate_run_error_record_is_the_exact_error_set_with_sentinels` ×3; `test_a_candidate_run_success_record_is_the_exact_success_set_with_sentinels`; `test_a_failing_model_call_is_classified_and_does_not_escape` ×3; `test_a_provider_endpoint_error_names_the_sentinel_release_not_a_real_one`; `test_a_v1_candidate_with_an_overlay_is_an_assembly_error_before_the_model`; `test_a_v2_overlay_candidate_binds_the_composed_schema_now`; `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2; `test_an_output_parser_exception_is_incomplete`; `test_an_unavailable_protected_bundle_is_an_assembly_error_before_the_model`; `test_an_unexpected_failure_is_a_model_error_carrying_only_its_class_name`; `test_candidate_prompt_schema_and_configuration_equal_the_production_path` ×28; `test_run_candidate_delegates_to_run_resolved_and_never_to_run`; `test_run_candidate_runs_every_role_through_the_fake_and_records_the_sentinel_identity` ×7 | marker after restore 0, clean=True |
| M11 NotImplementedError classified (C33) | `src/services/agent_runtime.py` | 1 | `T267_3_M11` = 1 | 1 failed, 235 passed | `test_a_failing_model_call_is_classified_and_does_not_escape` ×1 | marker after restore 0, clean=True |
| M12 provider parse error is incomplete (C15) | `src/services/agent_runtime.py` | 1 | `T267_3_M12` = 1 | 2 failed, 234 passed | `test_a_failing_model_call_is_classified_and_does_not_escape` ×1; `test_an_output_parser_exception_is_incomplete` | marker after restore 0, clean=True |
| M13 failures do not escape (C15/C34) | `src/services/agent_runtime.py` | 1 | `T267_3_M13` = 1 | 8 failed, 228 passed | `test_a_candidate_run_error_record_is_the_exact_error_set_with_sentinels` ×2; `test_a_failing_model_call_is_classified_and_does_not_escape` ×2; `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2; `test_an_output_parser_exception_is_incomplete`; `test_an_unexpected_failure_is_a_model_error_carrying_only_its_class_name` | marker after restore 0, clean=True |
| M14 no exception text in detail (C16) | `src/services/agent_runtime.py` | 1 | `T267_3_M14` = 1 | 1 failed, 235 passed | `test_an_unexpected_failure_is_a_model_error_carrying_only_its_class_name` | marker after restore 0, clean=True |
| M15 adapter forwards transport_options (C33) | `src/services/agent_runtime.py` | 1 | `T267_3_M15` = 1 | 2 failed, 234 passed | `test_databricks_model_adapter_forwards_transport_options_to_the_one_binding`; `test_the_agent_test_runtime_bounds_its_model_call_to_120_seconds_and_no_retry` | marker after restore 0, clean=True |
| M16 test runtime timeout is 120 s (C33) | `src/services/agent_runtime.py` | 1 | `T267_3_M16` = 1 | 1 failed, 235 passed | `test_the_agent_test_runtime_bounds_its_model_call_to_120_seconds_and_no_retry` | marker after restore 0, clean=True |
| M17 prompt parity: candidate payload unchanged | `src/services/agent_runtime.py` | 1 | `T267_3_M17` = 1 | 28 failed, 208 passed | `test_candidate_prompt_schema_and_configuration_equal_the_production_path` ×28 | marker after restore 0, clean=True |
| M18 run passes no observer (C15) | `src/services/agent_runtime.py` | 1 | `T267_3_M18` = 1 | 1 failed, 235 passed | `test_production_run_passes_no_raw_output_observer` | marker after restore 0, clean=True |
| M19 v1 overlay guard kept (C13) | `src/services/agent_runtime.py` | 1 | `T267_3_M19` = 1 | 2 failed, 234 passed | `test_a_v1_candidate_with_an_overlay_is_an_assembly_error_before_the_model`; `test_a_v1_schema_contract_still_rejects_a_non_empty_overlay_before_the_model` | marker after restore 0, clean=True |
| M20 call-site guard: run_candidate from graph/ (C12) | `src/services/graph/nodes.py` | 1 | `T267_3_M20` = 1 | 1 failed, 235 passed | `test_run_candidate_is_reachable_only_from_the_agent_test_workbench` | marker after restore 0, clean=True |
| M21 call-site guard: test runtime from graph/ (C33) | `src/services/graph/nodes.py` | 1 | `T267_3_M21` = 1 | 1 failed, 235 passed | `test_the_bounded_test_runtime_is_reachable_only_from_the_workbench_and_its_route` | marker after restore 0, clean=True |
| M22 one binding: workbench binds itself (C31) | `src/services/agent_test_workbench.py` | 1 | `T267_3_M22` = 1 | 1 failed, 235 passed | `test_no_module_binds_a_structured_model_outside_the_one_helper` | marker after restore 0, clean=True |
| M23 workbench never names ChatDatabricks (C31) | `src/services/agent_test_workbench.py` | 1 | `T267_3_M23` = 1 | 1 failed, 235 passed | `test_no_module_binds_a_structured_model_outside_the_one_helper` | marker after restore 0, clean=True |

## Gates
- **Focused:** 1340 passed, 0 failed, 0 skipped, in one invocation. It covers:
  - the plan's Task 3 files;
  - the brief's list;
  - the ten files in §7;
  - #266's five shared files;
  - `test_persisted_graph_release.py` and `test_agent_test_workbench.py`.
- **Full unit suite:** `tests/unit -q -p no:randomly -rf` with `DATABASE_URL=sqlite:////tmp/t267-3-full.sqlite` gave 6 failed, 6376 passed, 110 skipped and 136 warnings in 381 s.
  - The six failures are exactly the baseline nodes, with the same causes:
    - `test_deploy_autoscaling` ×2: the `provisioned` and `called 0 times` assertions.
    - `test_style_exclusivity_chokepoint` ×3: `'_FakeSession' object has no attribute 'execute'`.
    - `test_style_exclusivity_persistence_boundary` ×1: `no active Graph Release`.
  - There is no new cause, and the warning count is unchanged at 136.
- **PostgreSQL:** each file ran in its own invocation with `-rs`, against `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`. There were zero skips:
  - `test_persisted_graph_runtime_failures_postgres.py`: 7 passed.
  - `test_agent_definition_workbench_postgres.py`: 21 passed.
  - `test_agent_schema_overlay_postgres.py`: 10 passed.
- **`ruff check`:** every touched file is clean, as it was at base.
- **Environment:** `test ! -e .venv` held before and after. Nothing was installed, and `ai_slide_generator` was not touched.

## Concerns
1. **R1 differs from #266.** #266 does not log its probe. Candidate runs do log `persisted_agent_invocation`, with the `-1` identity and the unchanged exact field set. The controller should confirm this ruling.
2. **Tracebacks in the server log.** `unexpected_error` is logged with `exc_info`, per C16. The traceback may carry provider text into the server log, though never into `error_detail`. If that is unwanted, drop `exc_info`.
3. **Fake adapter location and shape.** The fake also records `configuration`, a superset of C26. Its location, `tests/fixtures/deterministic_model_adapter.py`, needs recording for #269's Task 0-B probe.
4. **Allowed callers are fixed.** The M20 and M21 guards allow exactly these callers:
   - `run_candidate`: only `src/services/agent_test_workbench.py`.
   - `get_agent_test_runtime`: that module and `src/api/routes/agent_definitions.py`.

   Tasks 4 and 5 must call from those modules only.

## Fix round 1

**Base:** the controller ledger commit `05dd5a37c`, pinned.

**Commits:**
- `3f5e7a44f` — fix: keep candidate runs out of the production identity log (#267).
- `029aa3eb7` — test: renames the every-role candidate test to `…_bypasses_the_identity_sink`.

**I-1 (ruling R1 rejected).** A candidate run no longer writes to the production identity log.
- `_run_resolved` takes a second private keyword-only argument, `_identity_sink`.
- `run_candidate` always passes `_PASS_THROUGH_IDENTITY_SINK`. It runs the callback and records nothing, so the `lru_cache`d test runtime cannot grow.
- `run_candidate` then writes one record of its own, `agent_candidate_run`, with exactly `{agent_key, status, error_code, error_class}`.
  - `error_code` is the code part of `error_detail`.
  - The record has no ids, endpoint, payload, prompt, output or `exc_info`.
- **Replaced tests:** the two persisted-runtime sentinel-record tests became `test_a_candidate_run_writes_no_identity_record_and_one_exact_candidate_record`, covering 4 modes. Each mode asserts:
  - zero `persisted_agent_invocation` records;
  - one candidate record with the exact field set;
  - no payload, prompt, hash or endpoint in any record.
- **Updated tests:** the recording-sink assertions in `test_agent_runtime.py` now assert `sink.calls == []`.
- **Sentinel:** the `-1` is now observable only on `PinnedInvocationEndpointError`. M06 still turns that test RED.
- **Unchanged:** `get_agent_test_runtime` keeps the logging sink. Its baseline reruns go through `run` against a real release, so they belong in that log, and that test was not changed.

**I-2.** The traceback (`exc_info`) is removed; only the class name is logged.
- New test: `test_an_unexpected_candidate_failure_logs_its_class_name_and_no_provider_text`, captured at DEBUG on the root logger.
- It asserts every record has `exc_info` and `exc_text` of `None`.
- It asserts `secret-host-267` appears in no record's message, args, vars or formatted traceback.

**I-3.** New test: `test_neither_run_nor_run_candidate_logs_model_output_anywhere`, captured at DEBUG on the root logger. It asserts:
- the unique output string really was produced;
- the runtime and sink loggers wrote exactly one production record and one candidate record;
- the string appears in no record at all.

The reviewer's R1 mutation (the observer defaults to a raw-output logger) turns it RED.

**I-4.** New test: `test_classification_reads_the_exception_type_never_its_text`.
- `OutputParserException("x")` is classified `incomplete`.
- `RuntimeError("could not parse output: 1 validation error")` is classified `model_error`, with `unexpected_error:RuntimeError`.

The reviewer's R2 text-match mutation turns it RED.

**Invariants.**
- `run` and `get_agent_runtime` are AST-identical to base `dec69b365`.
- The production adapter's kwargs are unchanged. `:645-677` and `test_the_production_runtime_adapter_still_hands_no_transport_options` both pass.

**Mutations.** `/tmp/t267-3/mutate-fix1.py`, pinned at `3f5e7a44f`, over the three runtime test files:
- M01–M23 were re-run. M10 and M17 got new anchors for the reformatted call.
- S1–S6 are new, and include the reviewer's R1 and R2.

Every row had anchor 1 and marker 1, turned RED, and restored clean. After all restores, 239 passed and no `T267_3_` marker remains.

| Clause | File | Anchor | Marker | RED | Failing tests | Restore |
|---|---|---|---|---|---|---|
| M01 role check first (C12.1/C14) | `src/services/agent_runtime.py` | 1 | `T267_3_M01` = 1 | 3 failed, 236 passed | `test_run_candidate_rejects_an_unknown_or_deterministic_role_first` ×3 | marker after restore 0, clean=True |
| M02 content-role check (C12.2) | `src/services/agent_runtime.py` | 1 | `T267_3_M02` = 1 | 1 failed, 238 passed | `test_run_candidate_rejects_content_for_another_role_before_the_hash` | marker after restore 0, clean=True |
| M03 hash check (C12.3; plan Step 4) | `src/services/agent_runtime.py` | 1 | `T267_3_M03` = 1 | 1 failed, 238 passed | `test_run_candidate_rejects_a_hash_that_does_not_match_the_content` | marker after restore 0, clean=True |
| M04 check order: hash before content role (C12) | `src/services/agent_runtime.py` | 1 | `T267_3_M04` = 1 | 1 failed, 238 passed | `test_run_candidate_rejects_content_for_another_role_before_the_hash` | marker after restore 0, clean=True |
| M05 no session identity (user decision) | `src/services/agent_runtime.py` | 1 | `T267_3_M05` = 1 | 2 failed, 237 passed | `test_run_candidate_refuses_a_session_identity` ×2 | marker after restore 0, clean=True |
| M06 sentinel release id on identity (C27) | `src/services/agent_runtime.py` | 1 | `T267_3_M06` = 1 | 1 failed, 238 passed | `test_a_provider_endpoint_error_names_the_sentinel_release_not_a_real_one` | marker after restore 0, clean=True |
| M07 sentinel value is -1, never a real id (C27) | `src/services/agent_runtime.py` | 1 | `T267_3_M07` = 1 | 3 failed, 236 passed | `test_a_provider_endpoint_error_names_the_sentinel_release_not_a_real_one`; `test_candidate_run_sentinels_are_negative_runtime_identity_constants`; `test_the_candidate_sentinel_release_id_never_resolves_through_run` | marker after restore 0, clean=True |
| M08 observer called (C15 sabotage) | `src/services/agent_runtime.py` | 1 | `T267_3_M08` = 1 | 10 failed, 229 passed | `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2; `test_neither_run_nor_run_candidate_logs_model_output_anywhere`; `test_run_candidate_runs_every_role_through_the_fake_and_records_the_sentinel_identity` ×7 | marker after restore 0, clean=True |
| M09 observer before validate_output (C15/C34) | `src/services/agent_runtime.py` | 1 | `T267_3_M09` = 1 | 2 failed, 237 passed | `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2 | marker after restore 0, clean=True |
| M10 never resolves a release (C12) | `src/services/agent_runtime.py` | 1 | `T267_3_M10` = 1 | 54 failed, 185 passed | `test_a_candidate_run_writes_no_identity_record_and_one_exact_candidate_record` ×4; `test_a_failing_model_call_is_classified_and_does_not_escape` ×3; `test_a_provider_endpoint_error_names_the_sentinel_release_not_a_real_one`; `test_a_v1_candidate_with_an_overlay_is_an_assembly_error_before_the_model`; `test_a_v2_overlay_candidate_binds_the_composed_schema_now`; `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2; `test_an_output_parser_exception_is_incomplete`; `test_an_unavailable_protected_bundle_is_an_assembly_error_before_the_model`; `test_an_unexpected_candidate_failure_logs_its_class_name_and_no_provider_text`; `test_an_unexpected_failure_is_a_model_error_carrying_only_its_class_name`; `test_candidate_prompt_schema_and_configuration_equal_the_production_path` ×28; `test_classification_reads_the_exception_type_never_its_text`; `test_neither_run_nor_run_candidate_logs_model_output_anywhere`; `test_run_candidate_delegates_to_run_resolved_and_never_to_run`; `test_run_candidate_runs_every_role_through_the_fake_and_records_the_sentinel_identity` ×7 | marker after restore 0, clean=True |
| M11 NotImplementedError classified (C33) | `src/services/agent_runtime.py` | 1 | `T267_3_M11` = 1 | 2 failed, 237 passed | `test_a_candidate_run_writes_no_identity_record_and_one_exact_candidate_record` ×1; `test_a_failing_model_call_is_classified_and_does_not_escape` ×1 | marker after restore 0, clean=True |
| M12 provider parse error is incomplete (C15) | `src/services/agent_runtime.py` | 1 | `T267_3_M12` = 1 | 3 failed, 236 passed | `test_a_failing_model_call_is_classified_and_does_not_escape` ×1; `test_an_output_parser_exception_is_incomplete`; `test_classification_reads_the_exception_type_never_its_text` | marker after restore 0, clean=True |
| M13 failures do not escape (C15/C34) | `src/services/agent_runtime.py` | 1 | `T267_3_M13` = 1 | 10 failed, 229 passed | `test_a_candidate_run_writes_no_identity_record_and_one_exact_candidate_record` ×2; `test_a_failing_model_call_is_classified_and_does_not_escape` ×2; `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2; `test_an_output_parser_exception_is_incomplete`; `test_an_unexpected_candidate_failure_logs_its_class_name_and_no_provider_text`; `test_an_unexpected_failure_is_a_model_error_carrying_only_its_class_name`; `test_classification_reads_the_exception_type_never_its_text` | marker after restore 0, clean=True |
| M14 no exception text in detail (C16) | `src/services/agent_runtime.py` | 1 | `T267_3_M14` = 1 | 3 failed, 236 passed | `test_an_unexpected_candidate_failure_logs_its_class_name_and_no_provider_text`; `test_an_unexpected_failure_is_a_model_error_carrying_only_its_class_name`; `test_classification_reads_the_exception_type_never_its_text` | marker after restore 0, clean=True |
| M15 adapter forwards transport_options (C33) | `src/services/agent_runtime.py` | 1 | `T267_3_M15` = 1 | 2 failed, 237 passed | `test_databricks_model_adapter_forwards_transport_options_to_the_one_binding`; `test_the_agent_test_runtime_bounds_its_model_call_to_120_seconds_and_no_retry` | marker after restore 0, clean=True |
| M16 test runtime timeout is 120 s (C33) | `src/services/agent_runtime.py` | 1 | `T267_3_M16` = 1 | 1 failed, 238 passed | `test_the_agent_test_runtime_bounds_its_model_call_to_120_seconds_and_no_retry` | marker after restore 0, clean=True |
| M17 prompt parity: candidate payload unchanged | `src/services/agent_runtime.py` | 1 | `T267_3_M17` = 1 | 28 failed, 211 passed | `test_candidate_prompt_schema_and_configuration_equal_the_production_path` ×28 | marker after restore 0, clean=True |
| M18 run passes no observer (C15) | `src/services/agent_runtime.py` | 1 | `T267_3_M18` = 1 | 1 failed, 238 passed | `test_production_run_passes_no_raw_output_observer` | marker after restore 0, clean=True |
| M19 v1 overlay guard kept (C13) | `src/services/agent_runtime.py` | 1 | `T267_3_M19` = 1 | 2 failed, 237 passed | `test_a_v1_candidate_with_an_overlay_is_an_assembly_error_before_the_model`; `test_a_v1_schema_contract_still_rejects_a_non_empty_overlay_before_the_model` | marker after restore 0, clean=True |
| M20 call-site guard: run_candidate from graph/ (C12) | `src/services/graph/nodes.py` | 1 | `T267_3_M20` = 1 | 1 failed, 238 passed | `test_run_candidate_is_reachable_only_from_the_agent_test_workbench` | marker after restore 0, clean=True |
| M21 call-site guard: test runtime from graph/ (C33) | `src/services/graph/nodes.py` | 1 | `T267_3_M21` = 1 | 1 failed, 238 passed | `test_the_bounded_test_runtime_is_reachable_only_from_the_workbench_and_its_route` | marker after restore 0, clean=True |
| M22 one binding: workbench binds itself (C31) | `src/services/agent_test_workbench.py` | 1 | `T267_3_M22` = 1 | 1 failed, 238 passed | `test_no_module_binds_a_structured_model_outside_the_one_helper` | marker after restore 0, clean=True |
| M23 workbench never names ChatDatabricks (C31) | `src/services/agent_test_workbench.py` | 1 | `T267_3_M23` = 1 | 1 failed, 238 passed | `test_no_module_binds_a_structured_model_outside_the_one_helper` | marker after restore 0, clean=True |
| S1 candidate runs bypass the production identity sink (I-1) | `src/services/agent_runtime.py` | 1 | `T267_3_S1` = 1 | 18 failed, 221 passed | `test_a_candidate_run_writes_no_identity_record_and_one_exact_candidate_record` ×4; `test_a_failing_model_call_is_classified_and_does_not_escape` ×3; `test_a_v2_overlay_candidate_binds_the_composed_schema_now`; `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2; `test_neither_run_nor_run_candidate_logs_model_output_anywhere`; `test_run_candidate_runs_every_role_through_the_fake_and_records_the_sentinel_identity` ×7 | marker after restore 0, clean=True |
| S2 the override is honoured in _run_resolved (I-1) | `src/services/agent_runtime.py` | 1 | `T267_3_S2` = 1 | 18 failed, 221 passed | `test_a_candidate_run_writes_no_identity_record_and_one_exact_candidate_record` ×4; `test_a_failing_model_call_is_classified_and_does_not_escape` ×3; `test_a_v2_overlay_candidate_binds_the_composed_schema_now`; `test_an_invalid_output_keeps_its_raw_keys_and_is_incomplete` ×2; `test_neither_run_nor_run_candidate_logs_model_output_anywhere`; `test_run_candidate_runs_every_role_through_the_fake_and_records_the_sentinel_identity` ×7 | marker after restore 0, clean=True |
| S3 no traceback in the candidate log (I-2) | `src/services/agent_runtime.py` | 1 | `T267_3_S3` = 1 | 4 failed, 235 passed | `test_a_candidate_run_writes_no_identity_record_and_one_exact_candidate_record` ×3; `test_an_unexpected_candidate_failure_logs_its_class_name_and_no_provider_text` | marker after restore 0, clean=True |
| S4 exact candidate log field set (I-1) | `src/services/agent_runtime.py` | 1 | `T267_3_S4` = 1 | 4 failed, 235 passed | `test_a_candidate_run_writes_no_identity_record_and_one_exact_candidate_record` ×4 | marker after restore 0, clean=True |
| S5 reviewer R1: default observer logs raw output (I-3) | `src/services/agent_runtime.py` | 1 | `T267_3_S5` = 1 | 1 failed, 238 passed | `test_neither_run_nor_run_candidate_logs_model_output_anywhere` | marker after restore 0, clean=True |
| S6 reviewer R2: classify by exception text (I-4) | `src/services/agent_runtime.py` | 1 | `T267_3_S6` = 1 | 1 failed, 238 passed | `test_classification_reads_the_exception_type_never_its_text` | marker after restore 0, clean=True |

**Gates:**

| Gate | Result |
|---|---|
| Focused, same 18 files | 1343 passed, 0 skipped |
| Full `tests/unit`, `DATABASE_URL=sqlite:////tmp/t267-3.sqlite` | 6 failed, 6379 passed, 110 skipped, 136 warnings. The six failures are the baseline nodes and causes. |
| PG runtime failures | 7 passed, zero skips |
| `ruff check` | clean |
| `.venv` | absent |

Minors M-1–M-4 are deferred as instructed. M-1 must go into Task 4's brief.
