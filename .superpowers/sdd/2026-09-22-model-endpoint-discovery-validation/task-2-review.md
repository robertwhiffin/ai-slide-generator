# Task 2 review — two-phase endpoint validation (#266)

Reviewer: independent task reviewer. Range `2a579cfdc..3980a35b6` (TASK_HEAD). Mutations ran only in the temporary worktree `/tmp/rev-266-2` (detached at `3980a35b6`). That worktree was removed afterwards (`git worktree remove` followed by `prune`; the path is absent). `.venv` was absent before and after. There were no installs and no commits, and the dev database was not touched.

## Spec Compliance: ✅

The brief is met, and so are C3, C4, C6, C7 and C8 plus the controller's `http_timeout_seconds` ruling.

⚠️ One accepted ruling has no test guarding it. `http_timeout_seconds=3` is not pinned by any test (see Important 1).

### Re-verification of C3/C4/C6/C7 by measurement

**Entry points onto `_write_locked_content`.** There are exactly four call sites in `src/`: `graph_configuration_draft.py:407, :466, :505, :559`. There is no fifth writer.

| Entry point | Endpoint policy (local) | Remote | Relative to stale |
| --- | --- | --- | --- |
| `save_editable_model_draft` | `:397`, via `_save_local_validators()` | `:406` | policy before stale `:398`; remote after `post_stale` `:405`, directly before writer `:407` |
| `save_draft_content` | `:456` | `:465` | policy before stale `:457`; remote directly before writer `:466` |
| `upgrade_draft_protected_assembly` | none (class tuple only, `:503`) | none | n/a |
| `upgrade_draft_schema_contract` | none (class tuple only, `:544`, `:557`) | none | n/a |

The upgrades contain no `_validate_remote_endpoint`, so they make no network I/O. The tests prove this: `test_endpoint_checks_are_composed_only_into_the_two_save_paths[×2]` runs a URL-shaped legacy endpoint through both upgrades with `remote.contents == []`.

**Validator order.** `_save_local_validators()` returns `local_candidate_validators + (policy,)`, so the order is assembly, then overlay, then endpoint. The class tuples are unchanged. #264's `:2107` guard is GREEN and unmodified.

**C4 policy.**
- The seed name `databricks-claude-opus-4-6` passes, as do the Task 1 names with spaces, `model.v1`, `...` and non-ASCII.
- Databricks serving-endpoint names are alphanumeric, `-` and `_`. The regex `[/\\?#%\x00-\x1f\x7f]` and the `.`/`..` check cannot reject a legitimate name.
- The repo has exactly one `serving_endpoints.get` (`model_endpoint_catalog.py:187`). The defensive policy call at `:185` runs before it, so no path reaches the SDK `get` without the policy.

**C8 client.**
- Measured on SDK 0.112.0: `retry_timeout_seconds` and `http_timeout_seconds` are both `ConfigAttribute`s stored in `_inner`, and `Config.copy()` is `copy.copy` plus a deepcopy of `_user_agent_other_info` only. The re-dict of `_inner` is therefore required, and it is sufficient.
- `WorkspaceClient.__init__` does not call `init_auth`.
- The client is built lazily, inside `validate`.
- No new credential source is added, because the shared `_header_factory` and host are reused.
- The controller's 0.120.0 re-probe is recorded in `progress.md`. I did not repeat it.
- `_BaseClient` defaults confirmed: `retry_timeout_seconds or 300`, `http_timeout_seconds or 60`.

**C7 injection.**
- `__init__` is keyword-only and defaults to `None`.
- No mixin in the MRO (`_GraphConfigurationWorkbench`, `_GraphConfigurationBootstrap`) defines `__init__`, so `super().__init__()` reaches `object`.
- All no-argument `GraphConfiguration()` importers still work: the five route sites, the bootstrap tests, and the `ObservedGraphConfiguration`/`HoldingGraphConfiguration` subclasses in the PostgreSQL suites.
- Route tests: 164 passed, and the route file is unchanged.

## Strengths

- The save-only composition is minimal and exact. The class tuples are untouched, and the sibling guard pins the composition.
- Ordering is tested in both directions:
  - URL plus stale gives 422 with zero remote calls, in 4 cases.
  - Valid plus stale gives the seven-role 409 with zero remote calls.
  - "Remote once, immediately before the writer" is checked with an ordered log.
- The remote-failure table runs the real `DatabricksModelEndpointCatalog` over a fake SDK surface. It also includes a transport `TimeoutError`. It asserts no mutation of content, hash, audit, draft, revision, release or interval.
- The PostgreSQL race proves two PIDs, a lock waiter, that the winner writes, and that the loser makes no remote call.
- The implementer ran a thorough 18-row sabotage table, and its restores were done correctly (explicit SHA).

## Issues

### Critical
None.

### Important

**1. `src/services/model_endpoint_catalog.py:125`: `config.http_timeout_seconds = CATALOG_HTTP_TIMEOUT_SECONDS` is unguarded.**
- **What is wrong.** Deleting the line (mutation R2) leaves all 220 tests in `test_model_endpoint_catalog.py` and `test_graph_configuration_draft.py` GREEN.
- **Why it matters.** The controller accepted this line specifically because it is load-bearing for the C8 ≤15 s bound. Without it, the SDK default per-request timeout is 60 s (`_BaseClient`: `http_timeout_seconds or 60`). A single hung socket under the exclusive draft lock would then last at least 60 s. A future refactor could drop the line silently.
- **Why the existing tests miss it.** `test_bounded_endpoint_catalog_client_reuses_system_credentials_and_leaves_it_unchanged` (`tests/unit/test_model_endpoint_catalog.py:357`) asserts only `retry_timeout_seconds`. The outage test raises `ConnectionError` immediately, so the per-request timeout is never exercised.
- **Fix.**
  - Assert `bounded.config.http_timeout_seconds == CATALOG_HTTP_TIMEOUT_SECONDS` and `system_client.config.http_timeout_seconds is None`.
  - Add a bound assertion, such as `CATALOG_RETRY_TIMEOUT_SECONDS + 2 * CATALOG_HTTP_TIMEOUT_SECONDS + <max backoff> <= 15`, or record the `timeout=` kwarg passed to the stubbed `requests.Session.request` in the outage test and assert that it is 3.
  - Sabotage-verify by deleting `:125`.

### Minor

**1. `src/services/graph_configuration_draft.py:262` and `src/services/graph_configuration.py:67`: the catalog factory runs outside any failure mapping.**
- **What is wrong.** `get_system_client()` can raise `DatabricksClientError`. On first use, when there is no cached singleton, it also builds a `WorkspaceClient` with unbounded auth resolution. Either would surface as a 500 inside the locked transaction, not as `endpoint_unavailable`.
- **Why it matters.** It is unlikely in production, where the singleton is warm after startup, but it is outside the C3 "every SDK/transport failure is typed" intent.
- **Fix.** In Task 3's wiring, or here, map factory construction failures to `EndpointValidationFailure("endpoint_unavailable", …, True)` without reading the exception text. At minimum, ledger this for Task 3.

**2. `src/services/model_endpoint_catalog.py:69`: `RuntimeError` in `_TRANSPORT_FAILURES` is broad.**
- **What is wrong.** It also classifies `NotImplementedError`/`RecursionError` from SDK code as a retryable "unavailable".
- **Why it is only Minor.** C3 mandates it. The `try` wraps only the single SDK call, so our own post-processing bugs are not masked. No fix is required; note it for the whole-branch review.

**3. The residual unbounded windows are parked (implementer concern 2).** A server `Retry-After` sleep and the OAuth refresh inside the shared header factory are not bounded by `retry_timeout_seconds`. Carry this to the whole-branch review with C8.

## Sabotage evidence

The controller target (`TASK2_VALIDATOR_BYPASS_SABOTAGE`) was not repeated.

Every mutation used the same method:
- **Worktree and SHA.** Temporary worktree `/tmp/rev-266-2` at `3980a35b6`.
- **Environment.** `PYTHONPATH=/tmp/rev-266-2:/tmp/rev-266-2/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly -rf`.
- **Restore.** `git checkout 3980a35b68af4c5832618d148b06e33ec20b2ab9 -- <file>`, then marker `rg` count 0 and `git status --porcelain` empty.

The pre-mutation GREEN baseline was:
- the draft, catalog and routes files together: 384 passed;
- the PostgreSQL workbench file: 16 passed, 0 skipped.

**S1 — `TASK2_REVIEWER_STALE_REMOTE_SABOTAGE` (the plan's reviewer target).**
- **Mutation.** The `_validate_remote_endpoint(...)` call was moved from after `post_stale_validators` to directly after `_save_local_validators()`, in both saves.
- **Anchors.** The anchor count was 1 for each of the two local-validator lines and 1 for each of the two remote calls.
- **Marker.** `rg -n` showed the marker at `:398` and `:457`, which is after the local validators and before the `if expected_lock_version != …` stale check, so it sits on the executed path. `rg -c "_validate_remote_endpoint\("` returned 3 (the def plus two calls).
- **Unit result.** `tests/unit/test_graph_configuration_draft.py` went **RED 4/160**:
  - `test_locally_valid_endpoint_plus_stale_lock_is_seven_role_409_with_zero_remote_calls[editable]` and `[trusted]`. The failure was `assert [DefinitionContent(... prompt_text='valid but stale' ...)] == []`, so the stale loser called the fake remote.
  - `test_current_endpoint_candidate_is_remotely_validated_once_immediately_before_the_writer[editable]` and `[trusted]`.
- **PostgreSQL result.** `tests/integration/test_agent_definition_workbench_postgres.py`, run with `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, went **RED 1/16** with 0 skipped: `test_stale_endpoint_loser_waits_on_the_lock_and_never_reaches_remote_validation`. The failure was "Left contains one more item: ('endpoint-loser', 'loser endpoint name')".
- **Invalid-plus-stale under the same sabotage.** `-k url_plus_stale` gave 4 passed, so the URL case stays 422 with zero remote calls.
- **After restore.** Unit 160 passed; PostgreSQL 16 passed, 0 skipped.

**R1 — C4: `%` dropped from `_PATH_METACHARACTERS` (`model_endpoint_catalog.py:88`), marker `REV266_2_R1_PERCENT`.**
- Anchor count 1; marker `rg` count 1, on line 88.
- Scope: the catalog and draft files together (220 tests).
- **RED 2/220:** `test_validate_endpoint_name_policy_rejects_request_path_metacharacters[percent-escape]` and `test_validate_custom_endpoint_remote_refuses_a_path_shaped_name_before_any_get[percent-escape]`.
- Restored, marker 0, then GREEN 220.

**R2 — C8: `config.http_timeout_seconds = …` replaced by `pass` (`:125`), marker `REV266_2_R2_HTTP_TIMEOUT`.**
- Anchor count 1; marker count 1, on line 125.
- Scope: the same 220 tests.
- **Survived: 0/220 RED (220 passed).** This is Important 1.
- Restored, marker 0, then GREEN 220.

**R3 — C3: `RuntimeError` removed from `_TRANSPORT_FAILURES` (`:69`), marker `REV266_2_R3_RUNTIME`.**
- Anchor count 1; marker count 1, on line 69.
- Scope: the same 220 tests.
- **RED 2/220:** `test_list_system_models_maps_transport_exhaustion_to_catalog_unavailable[sdk-max-attempts]` and `test_validate_custom_endpoint_remote_maps_transport_exhaustion_to_endpoint_unavailable[sdk-max-attempts]`.
- Restored, marker 0, then GREEN 220.

### Regression gates in the temporary worktree

- **Full unit suite (`tests/unit`).** 7 failed, 5979 passed, 110 skipped, 136 warnings.
  - Six failures are the baseline causes: autoscaling ×2, `TestModelDumpIsNotTheChokepoint` ×3, and `test_session_manager_create_session`.
  - The seventh is `test_persisted_agent_runtime.py::test_runtime_logging_sink_success_record_is_identity_outcome_and_optional_projection_only`. It is the documented `/private/tmp` environmental case: `'private'` matched `pathname '/private/tmp/rev-266-2/…'`.
  - Passed is 5979 against the implementer's 5980 because of that one environmental failure.
- **PostgreSQL overlay file.** 10 passed, 0 skipped.

## Task quality: Needs fixes

The only item that must be fixed is Important 1: add a test that pins `http_timeout_seconds`, then sabotage-verify it by deleting `:125`. The Minor items can be ledgered.
