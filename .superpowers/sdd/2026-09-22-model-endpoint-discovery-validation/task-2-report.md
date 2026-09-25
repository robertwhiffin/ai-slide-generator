# Task 2 report — two-phase endpoint validation in the one draft-save pipeline (#266)

**Status:** DONE, with concerns (see the end).

- `TASK_BASE=2a579cfdcadfa64684e31fba8148ed38f47f2273`
- `e46674ef9d609531e6b9b4903fcedb916bcbbdfa` fix: map SDK transport exhaustion to typed catalog unavailability (#266). This is C3 alone.
- `18b0f8cd3b10fb7849b1cac653f835bf05b05d46` feat: validate draft endpoint names (#266). This is the plan's Task 2 plus C4, C6, C7 and the C8 ruling.
- `TASK_HEAD` is the commit that adds this report.

## Files (base..18b0f8cd)

| File | Change |
| --- | --- |
| `src/services/model_endpoint_catalog.py` | C3 transport mapping for both methods. C4 path policy, plus a defensive policy call at the top of `validate_custom_endpoint_remote`. C8 `bounded_catalog_workspace_client` and its constants. |
| `src/services/graph_configuration_draft.py` | `_endpoint_name_policy_validator`, `RemoteEndpointDraftValidator` (Protocol) and `CatalogRemoteEndpointDraftValidator` (adapter). Keyword-only `__init__(remote_endpoint_validator=None)`. `_save_local_validators()` and `_validate_remote_endpoint()` are composed into the two saves only. All additions sit below `_LEGACY_SOURCE_ROLES`, which is not reflowed. |
| `src/services/graph_configuration.py` | Production factory `build_remote_endpoint_draft_validator()` and the new exports. |
| `tests/unit/test_model_endpoint_catalog.py` | 19 → 60 tests. |
| `tests/unit/test_graph_configuration_draft.py` | 121 → 160 tests. The #264 guard at `:2107` is unmodified. |
| `tests/integration/test_agent_definition_workbench_postgres.py` | 15 → 16 tests (the stale-loser race). `pytestmark` was already present. |

No CI guard or workflow edit was needed. `.github/workflows/test.yml:463` already names the PostgreSQL module (C20). There are no route edits (C7), no ORM column, and no second writer, lock read, mapper, hash, audit or transaction.

## Design as built

**Local phase.** In both `save_editable_model_draft` and `save_draft_content`, `self._run_candidate_validators(self._save_local_validators(), …)` runs after #263's command, round-trip and immutable checks and before the stale comparison. `_save_local_validators()` returns `self.local_candidate_validators + (_endpoint_name_policy_validator,)`, so the endpoint issue follows the assembly and overlay issues in the single ordered 422. The class tuples are unchanged, so both upgrades run no endpoint check (C6).

**Remote phase.** The remote check runs in both saves after `post_stale_validators`, and `_write_locked_content` follows immediately. `_validate_remote_endpoint` makes exactly one call to `self._remote_endpoint_validator.validate(content)`, and that call is the plan's sabotage anchor (count 1). It translates `EndpointValidationFailure` into `DraftValidationIssue("candidate.model.endpoint_name", code, message)`, and the endpoint text is never echoed. A `None` validator skips the phase.

**Injection (C7).** `GraphConfiguration(*, remote_endpoint_validator=None)`. The production factory `build_remote_endpoint_draft_validator()` builds nothing when it is called. On each `validate` it constructs `DatabricksModelEndpointCatalog(bounded_catalog_workspace_client(get_system_client()))` and passes the exact, unchanged `content.model.endpoint_name` to `validate_custom_endpoint_remote`. The PUT wiring is Task 3's job.

**C4 policy.** The policy rejects `/ \ ? # %`, ASCII controls `\x00-\x1f` and `\x7f`, and names exactly equal to `.` or `..`. All of these are reported under the existing `endpoint_url_not_allowed` code and message. Spaces, `...`, ` ..`, `model.v1` and non-ASCII names are still accepted verbatim.

**C8 ruling (bounded window).** The client is `config = get_system_client().config.copy()`. The copy gets its own `_inner` mapping, then `retry_timeout_seconds=5` and `http_timeout_seconds=3`, and becomes `WorkspaceClient(config=config)`. No credential source is added, because the copy shares the system client's resolved `_header_factory` and host.

Measurement found that `Config.copy()` in SDK 0.112.0 is shallow **and shares `_inner`** (`cpy._inner is base.config._inner` → `True`). Without the re-dict, setting the timeouts would silently rewrite the system client's own configuration. A test pins this behaviour.

The wall-clock driver `/tmp/t266-2/measure_bounded.py` ran on a real `_BaseClient` with `requests.Session.request` stubbed and no network:

| Forced failure | Result | Wall clock | Attempts | Per-request timeout |
| --- | --- | ---: | ---: | ---: |
| `ConnectionError` | `endpoint_unavailable` (cause `TimeoutError`) | 6.53 s | 3 | 3.0 s |
| `ReadTimeout` | `endpoint_unavailable` (cause `TimeoutError`) | 7.18 s | 3 | 3.0 s |

The system client's own `retry_timeout_seconds` and `http_timeout_seconds` were still `None` after the run. My arithmetic worst case for a hung socket is about 13 s: attempts start before 5 s, each lasts at most 3+3 s, and each sleep is at most `attempt+1` s. That is within 15 s. The one exception is an HTTP `Retry-After` header (see concerns). NEEDS_CONTEXT was not required.

## RED evidence (before implementation)

- **C3** (`/tmp/t266-2/red-c3.txt`): 8 failed, 19 passed. Each of the four parametrized errors escaped raw from both methods, for example `E TimeoutError: Timed out after 0:05:00` and `E RuntimeError: Exceeded max retry attempts (3)`.
- **C4** (`/tmp/t266-2/red-c4.txt`): 24 failed, 36 passed. Every one of the 24 failed with `Failed: DID NOT RAISE EndpointValidationFailure`: 12 on the policy and 12 on the remote pre-`get` guard. The bounded-client tests were first RED as a collection `ImportError` (the symbol was absent), and are sabotage-proved below.
- **Draft unit, `-k endpoint`, with no extension at all** (`/tmp/t266-2/red-draft.txt`): 38 failed, 1 passed. Every failure was the missing extension: `TypeError: GraphConfiguration() takes no arguments`, a failed import of `CatalogRemoteEndpointDraftValidator`, and the absent `build_remote_endpoint_draft_validator`. This matches the plan's expected RED.
- **Draft unit, with injection only and neither phase** (`/tmp/t266-2/red-draft-2.txt`): 30 failed, 9 passed. The failures were for the right reason:
  - 22 × `DID NOT RAISE DraftContentRejected`: URL plus stale gave a 409, and remote rejections wrote.
  - The aggregate lacked the endpoint row.
  - The log was `['post-1','write']` rather than `['post-1','remote:…','write']`.
  - `get_calls == []`.
  - The nine that passed are guards that stay GREEN until sabotaged: valid-stale ×2, command precedence, immutable precedence, upgrade isolation ×2, default/keyword-only, adapter and factory.
- **PostgreSQL, `-k endpoint`** (`/tmp/t266-2/red-pg.txt`): 1 failed, 0 skipped, `E TypeError: ObservedGraphConfiguration() takes no arguments`. It connected to a real server. I ran this retroactively by writing the three src files from `e46674ef` over the working tree, then restoring my copies byte-exact. The md5s before and after were `63b1a869…`, `4b31941c…` and `d2cfde06…`, all identical.

## Clause-to-mutation table

Driver: `/tmp/t266-2/sab.py`, with specs in `/tmp/t266-2/*.json` and output in `/tmp/t266-2/*.out`.

Each row followed the same procedure:
1. Assert the anchor occurs exactly once.
2. Apply the mutation carrying its marker, and confirm `rg -c <marker>` returns 1.
3. Run `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr python -m pytest -q -p no:randomly -rf <scope>`.
4. Restore with `git checkout <explicit SHA> -- <file>` and confirm `git diff <SHA> -- <file>` is 0 lines.
5. Confirm `rg -c <marker>` returns 0.
6. Re-run for GREEN.

Restore SHAs: rows C3a and C3b used `e46674ef9d609531e6b9b4903fcedb916bcbbdfa`, and rows M01–M16 used `18b0f8cd3b10fb7849b1cac653f835bf05b05d46`. These are explicit commit SHAs, not `TASK_BASE`. Restoring to `TASK_BASE` would have erased the implementation under test.

Scopes: TC is `tests/unit/test_model_endpoint_catalog.py` (60 tests) and TD is `tests/unit/test_graph_configuration_draft.py` (160 tests). The anchor count was 1 in every row, and the marker count was 1 after mutation and 0 after restore in every row.

| # | Clause | Mutation (marker) | Scope | RED: count and failing tests | GREEN |
| --- | --- | --- | --- | --- | --- |
| C3a | C3: `list` maps transport exhaustion | `except DatabricksError` only (`T266_2_C3_LIST_SABOTAGE`) | TC(27) | 4: `test_list_system_models_maps_transport_exhaustion_to_catalog_unavailable[sdk-retry-timeout, sdk-max-attempts, requests-transport, os-transport]` | 27 |
| C3b | C3: `get` maps transport exhaustion | same, in `validate_custom_endpoint_remote` (`T266_2_C3_GET_SABOTAGE`) | TC(27) | 4: `test_validate_custom_endpoint_remote_maps_transport_exhaustion_to_endpoint_unavailable[×4]` | 27 |
| M01 | C6: policy is in the pre-stale aggregate | `_save_local_validators` returns only the class tuple, dropping the policy (`T266_2_M01`) | TD | 6: `test_endpoint_url_plus_stale_lock_is_ordered_422_with_zero_remote_calls[×4]`, `test_endpoint_policy_issue_follows_the_overlay_issue_in_one_ordered_422[editable, trusted]` | 160 |
| M02 | C6: policy is not class-wide | policy appended to `local_candidate_validators` (`T266_2_M02`) | TD | 9: `test_overlay_validation_is_registered_in_the_pre_stale_tuple_only`, URL-stale ×4, aggregate ×2, `test_endpoint_checks_are_composed_only_into_the_two_save_paths[protected_assembly, schema_contract]` | 160 |
| M03 | Remote failure translated with exact code/message | issue code forced to `endpoint_invalid` (`T266_2_M03`) | TD | 24: URL-stale ×4, aggregate ×2, `test_every_remote_endpoint_failure_is_one_ordered_issue_with_no_mutation[×18]` | 160 |
| M04 | Remote validated exactly once | validate called twice (`T266_2_M04`) | TD | 6: `test_current_endpoint_candidate_is_remotely_validated_once_immediately_before_the_writer[×2]`, `test_valid_same_content_endpoint_save_validates_and_advances_audit_unchanged[×2]`, `test_flush_failure_after_endpoint_validation_rolls_back_from_a_fresh_session[×2]` | 160 |
| M05 | Remote runs immediately **before** the writer | editable path writes, then validates (`T266_2_M05`) | TD | 11: `…validated_once_immediately_before_the_writer[editable]`, remote-table `[*-editable]` ×9, flush-rollback `[editable]` | 160 |
| M06 | Adapter delegates the exact unchanged name | `.strip()` added in the adapter (`T266_2_M06`) | TD | 1: `test_catalog_remote_endpoint_validator_delegates_the_exact_unchanged_name` | 160 |
| M07 | C7: injection is keyword-only | `*` removed (`T266_2_M07`) | TD | 1: `test_default_facade_has_no_remote_endpoint_validator_and_injection_is_keyword_only` | 160 |
| M08 | C6: upgrades do no endpoint work | protected-assembly upgrade runs `_save_local_validators()` and remote (`T266_2_M08`) | TD | 1: `test_endpoint_checks_are_composed_only_into_the_two_save_paths[protected_assembly]` | 160 |
| M09 | C8: factory uses the bounded client | factory passes `get_system_client()` directly (`T266_2_M09`) | TD | 1: `test_production_remote_endpoint_validator_uses_a_bounded_system_client` | 160 |
| M10 | Factory is lazy (no I/O at construction) | catalog built eagerly in the factory (`T266_2_M10`) | TD | 1: `test_production_remote_endpoint_validator_uses_a_bounded_system_client` | 160 |
| M11 | C8: system config never mutated | `config._inner = dict(...)` removed (`T266_2_M11`) | TC | 1: `test_bounded_endpoint_catalog_client_reuses_system_credentials_and_leaves_it_unchanged` | 60 |
| M12 | C8: retry window bounded to 15 s or less | `retry_timeout_seconds` not set (`T266_2_M12`) | TC | 2: `…reuses_system_credentials_and_leaves_it_unchanged`, `test_bounded_endpoint_catalog_client_turns_a_transport_outage_into_endpoint_unavailable` | 60 |
| M13 | C4: path metacharacters rejected | `_PATH_METACHARACTERS.search` removed (`T266_2_M13`) | TC | 20: `test_validate_endpoint_name_policy_rejects_request_path_metacharacters[×10 non-dot]`, `test_validate_custom_endpoint_remote_refuses_a_path_shaped_name_before_any_get[×10]` | 60 |
| M14 | C4: `.`/`..` rejected | `_DOT_SEGMENTS` check removed (`T266_2_M14`) | TC | 4: policy `[dot, dot-dot]`, remote `[dot, dot-dot]` | 60 |
| M15 | C4: remote refuses before any `get` | defensive policy call removed (`T266_2_M15`) | TC | 12: `test_validate_custom_endpoint_remote_refuses_a_path_shaped_name_before_any_get[×12]` | 60 |
| M16 | C4: every ASCII control, including `\x7f` | `\x7f` dropped from the class (`T266_2_M16`) | TC | 2: policy `[delete]`, remote `[delete]` | 60 |

The plan's controller target (`TASK2_VALIDATOR_BYPASS_SABOTAGE`) and reviewer target (`TASK2_REVIEWER_STALE_REMOTE_SABOTAGE`) were not exercised, as instructed. The guards they will hit are these:
- For the bypass: `test_every_remote_endpoint_failure_is_one_ordered_issue_with_no_mutation[forbidden-*]` and the other remote-table cases. Under the bypass the save writes and does not raise.
- For stale-remote: `test_locally_valid_endpoint_plus_stale_lock_is_seven_role_409_with_zero_remote_calls[editable, trusted]` asserts `remote.contents == []`. The PostgreSQL `test_stale_endpoint_loser_waits_on_the_lock_and_never_reaches_remote_validation` asserts `remote_calls == [("endpoint-winner", …)]`.
- The invalid-plus-stale 422 with zero remote calls is `test_endpoint_url_plus_stale_lock_is_ordered_422_with_zero_remote_calls[×4]`.

The zero-count evidence is as follows. Within TD at `18b0f8cd`, no existing test other than the #264 guard reacted to any endpoint mutation, so M02's RED set outside the new tests is exactly `test_overlay_validation_is_registered_in_the_pre_stale_tuple_only` and nothing else. The M05 editable-only mutation left every trusted-path test GREEN, so the trusted path is free within TD for that mutation.

## Gates

`test ! -e .venv` passed before and after every run. Every command used `PYTHONPATH=<wt>:<wt>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest`.

- **Focused**:
  - `-q -p no:randomly -rf` over TD, TC and `test_agent_definition_workbench_routes.py`, plus `test_app_wheel_dependencies`, `test_prompt_assembler`, `test_agent_schema_registry`, `test_ci_collects_integration_tests`, `test_agent_runtime` and `test_persisted_agent_runtime`: **704 passed, 0 failed, 0 skipped**.
  - TD is 160 (121 + 39), TC is 60 (19 + 41) and routes is 164 (unchanged).
  - The text-read `_LEGACY_SOURCE_ROLES` join (`test_prompt_assembler`) and the wheel/registry scans are GREEN.
- **Full unit**: `tests/unit -q -p no:randomly -rf`, started 15:23 UTC, gave **6 failed, 5980 passed, 110 skipped, 136 warnings**.
  - The six are exactly the baseline set by node ID and cause:
    - `test_deploy_autoscaling` ×2: `assert 'provisioned' == 'autoscaling'` and `…provisioned to have been called once. Called 0 times.`
    - `TestModelDumpIsNotTheChokepoint` ×3: `'_FakeSession' object has no attribute 'execute'`.
    - `test_session_manager_create_session`: `no active Graph Release`.
  - The passed count is 5900 + 80 new tests. Skips are the same count (110).
  - No warning location is in a changed file, and the warning count matches the baseline (136).
  - There were no other failures. This was not a midnight run, so the `test_usage_service` flake did not apply.
- **PostgreSQL**: `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, one invocation per file, `-rfs`:
  - `test_agent_definition_workbench_postgres.py`: **16 passed, 0 skipped** (15 baseline + 1 new).
  - `test_agent_schema_overlay_postgres.py`: **10 passed, 0 skipped**.
  - The new race proves two distinct `pg_backend_pid()` values, a `pg_stat_activity` Lock waiter, that the winner writes, and that the loser returns a seven-role 409. The loser's `client_candidate is loser_candidate`, it made no remote call and it did not write.
  - The dev database `ai_slide_generator` was not touched; the fixtures own throwaway databases.
- **ruff check** on all six changed files, at HEAD and at base (base via `git show 2a579cf:<f> | ruff check --stdin-filename <f> -`): **All checks passed** on both sides. `ruff format` was not run and is not claimed.
- **Triple check**: `git status --porcelain`, `git diff HEAD` and `git diff --cached` were all empty after the sabotage runs and after the gates.

## Concerns

1. **The C8 bounded client relies on SDK internals.** It re-dicts `Config._inner` after `Config.copy()`, and the test asserts shared `_header_factory` identity. It was measured on the installed 0.112.0. However, `packages/databricks-tellr-app/pyproject.toml` pins **`databricks-sdk==0.120.0`**, which I did not probe; I installed nothing. If 0.120's `copy()` semantics differ, `test_bounded_endpoint_catalog_client_reuses_system_credentials_and_leaves_it_unchanged` is the guard that REDs. A re-probe on 0.120.0 is recommended before merge.
2. **The residual window is not bounded by `retry_timeout_seconds`.** The SDK sleeps a server-supplied `Retry-After` (429/503) before its deadline check, and the OAuth token refresh inside the shared header factory has its own timeouts. Neither is bounded by the 15 s ruling. Both are outside what configuration alone can bound without new credential handling.
3. **Setting `http_timeout_seconds=3` goes beyond the literal ruling**, which named only a short `retry_timeout_seconds`. I added it because a single hung request would otherwise last up to the SDK default of 60 s and break the 15 s bound. It uses the same configuration and adds no credential source. The controller may veto it.
4. **`requests` is imported directly** for the C3 mapping. It is transitive via `databricks-sdk` and not declared in the app wheel, but `src/services/agent_runtime.py` already does the same, and `test_app_wheel_dependencies` passes.
5. **The production factory builds a `WorkspaceClient` on every validation**, from a config copy with no auth re-init and no network. It is not cached, so a `get_system_client(force_new=True)` refresh is always honoured. The cost is about a few milliseconds per save.
6. **Carried forward, not Task 2 work.** Between Task 2 and Task 3 the production PUT does not validate remotely (C7). Legacy rows with path-shaped names remain a runtime exposure, parked by C4.
