# Task 6 report: admin HTTP for release history, comparison, rollback preview and rollback

**Status:** DONE_WITH_CONCERNS (minor; see the end).
**TASK_BASE:** `01213fca5`. **Mutation pin:** `0794afa25`.

## Commits
| SHA | Summary |
|---|---|
| `0794afa25` | feat: admin HTTP for graph release history and rollback (#270) |
| (this report) | docs: record #270 Task 6 |

Files in `0794afa25` (C38 is atomic: the Python and TS halves land together):
- **Created:**
  - `src/api/schemas/graph_release_history.py`
  - `tests/unit/test_graph_release_history_routes.py` (69 tests)
  - `tests/unit/test_graph_release_history_client_join.py` (20 tests, C46)
- **Modified:**
  - `src/api/routes/agent_definitions.py`:
    - five handlers after #269's, on the one `router` (C37);
    - the publish route now passes `source_release_id` (C38);
    - `_parse_publish_request` delegates to a new generic `_parse_release_body(request, model, invalid)`, which the rollback reuses (it is not a copy);
    - `_published_response` delegates to `_published_fields`, which the rollback reuses without going through the approval-only publish model.

    No existing handler was edited, and #269's tests are green.
  - `src/api/schemas/graph_releases.py` (C38):
    - `ReleaseEvidenceResponse` gains `evidence_kind: Literal["approval", "historical_restore"]` and `source_release_id: _RowId | None`, placed after `evidence_kind`;
    - a pairing validator: the source is non-null iff the kind is `historical_restore`;
    - `PublishReleaseSuccessResponse` gains an approval-only validator.
  - `frontend/src/api/agentDefinitions.ts`, the evidence parser only:
    - the `ReleaseEvidence` type is widened;
    - `RELEASE_EVIDENCE_KEYS` gains `'source_release_id'`;
    - `isReleaseEvidence` checks the kind/source pairing;
    - `parsePublishReleaseSuccessResponse` requires every item to be `approval`.
  - `frontend/tests/fixtures/mocks.ts`: `syntheticPublishSuccess` evidence gains `source_release_id: null`.
  - `frontend/src/components/Admin/GraphRelease/releaseClient.test.ts`, whose rows had to change:
    - the old :184 is now "a well-formed restore evidence item", with a kind and a source, which pins approval-only;
    - added "a restore evidence kind without a source";
    - the old :185 is relabelled "an approval with a source", which pins pairing;
    - added a true "an extra evidence key" row (`note`).

    `reviewAndPublishState.test.ts` and `ReviewAndPublishPage.test.tsx` needed no edit: they use `syntheticPublishSuccess()` from mocks.
  - `tests/unit/test_graph_release_client_join.py`: the one-element unpack at `:131–134` is now a two-literal check, which requires both `evidence_kind === '<kind>'` spellings in the TS source.
  - `tests/unit/test_graph_release_routes.py`: the exact publish 200 body adds `"source_release_id": None`.
  - `tests/unit/test_agent_definition_workbench_routes.py`: the exhaustive registry pin (it went RED as designed) now has `/releases` `{"GET","POST"}` plus the four `{version_number}` paths.
- **Not changed:** `src/api/main.py`. `git diff --exit-code c7ea1d943 -- src/api/main.py` exits 0.

## HTTP contract (Task 7's TS parsers must match these exactly)
**Prefix and rules**
- Every path is under `/api/admin/agent-definitions`, on the router-level `require_admin`.
- `{version_number}` is a version, never an id.
- Every model is `extra="forbid"`. Keys are listed in wire order.
- `Ref` is the reused `ReleaseIdentityResponse`: `{release_id: int≥1, version_number: int≥1}`.
- Timestamps are ISO strings, labelled UTC in the history models. On SQLite they end in `Z`; see concern 3.

**`GET /releases`** returns 200 `ReleaseHistoryListResponse`.
- Body: `{active_release: Ref, releases: Entry[] (min 1, newest first)}`.
- `Entry` (`ReleaseHistoryEntryResponse`) fields:
  - `release_id`
  - `version_number`
  - `is_active: bool`
  - `release_note`
  - `published_by`
  - `published_at`
  - `effective_from`
  - `effective_to: str|null`
  - `previous: Ref|null`
  - `restored_from: Ref|null`
  - `restored_by: Ref[]`, ascending
  - `changed_agents: AgentKey[]`, min 1, in Graph order; v1 lists all seven

**`GET /releases/{version_number}`** returns 200 `ReleaseDetailResponse`.
- Body: `{release: Entry, definitions: {AgentKey: Definition} (exactly 7, in Graph order), evidence: Evidence[]}`.
- `Definition` (`ReleaseDefinitionResponse`): `{agent_definition_revision_id, content_hash: sha256, content: <canonical_payload()>}`.
- `Evidence` (`ReleaseHistoryEvidenceResponse`) fields:
  - `agent_test_run_id`
  - `agent_key`
  - `test_case_id`
  - `test_case_version: int≥1`
  - `evidence_kind: "approval"|"historical_restore"`
  - `source: Ref|null`, non-null iff `historical_restore` (validator)
  - `verdict: "approved"|"rejected"|null`
  - `verdict_reviewer: str|null`
  - `verdict_at: str|null`
  - `execution_status: "completed"|"model_error"|"assembly_error"|"incomplete"`
  - `deterministic_checks_passed: bool`
  - `run_at`
- Evidence order: Graph role index, then test case id, then run id.

**`GET /releases/{version_number}/comparison`** returns 200 `ReleaseComparisonResponse`.
- Body: `{active_release: Ref, release: Ref, agents: AgentComparison[] (exactly 7, in Graph order)}`.
- `AgentComparison` (`AgentComparisonResponse`): `{agent_key, active_revision_id, historical_revision_id, same_revision: bool, field_diffs: FieldDiff[]}`.
- `FieldDiff` (`ReleaseFieldDiffResponse`, C46): `{field: DiffFieldName, active: JSON, historical: JSON}`.
  - Only differing fields appear, in `DiffFieldName` order.
  - `field_diffs` is empty iff the contents are equal.

**`GET /releases/{version_number}/rollback-preview`** returns 200 `RollbackPreviewResponse`.
- It is the only new route that resolves `get_remote_endpoint_draft_validator` (C34).
- Keys, in order:
  - `source: Ref`
  - `active_release: Ref`
  - `next_version_number: int≥2`
  - `lock_version: int≥0`
  - `default_release_note: str` ("Roll back to Graph Version N.")
  - `restorable: bool`, exactly `blocked === null` (validator)
  - `blocked: null|"source_is_active"|"matches_active"|"incompatible"`
  - `issues: {field, code, message}[]`
  - `warnings: {field, code, message}[]`: advisory, never blocking, `definitions.<key>.candidate.model.endpoint_name`
  - `agents: AgentComparison[]` (×7, in Graph order)
  - `evidence: {agent_test_run_id, agent_key, test_case_id}[]` (`RollbackPreviewEvidenceResponse`)
  - `draft_effect: {AgentKey: "reset"|"kept"|"unchanged"}` (×7, in Graph order)

**`POST /releases/{version_number}/rollback`**
- **Request:** `RollbackRequest` is `{lock_version: int, release_note: str}`, `extra="forbid", strict=True`, with no `ge` and no `max_length` (see deviation 1).
- **200** `RollbackSuccessResponse`. Keys, in order:
  - `release: ActiveReleaseResponse`
  - `restored_from: Ref`
  - `previous_release_id: int`
  - `changed_agents: AgentKey[]` (min 1)
  - `mappings: {AgentKey: {agent_definition_revision_id, content_hash, reused}}`: exactly 7, in Graph order, every `reused` true (validator)
  - `evidence: {agent_test_run_id, agent_key, test_case_id, evidence_kind, source_release_id}[]`: every item `historical_restore` (validator)
  - `draft: DraftMetadataResponse`
  - `draft_effect: {…×7}`
- **Errors:**

  | Status | Body |
  |---|---|
  | 403 | `{"detail": "Admin access required"}` (router) |
  | 403 | `{"detail": "Authenticated principal required"}` (blank principal, or a service `actor` issue) |
  | 404 | `{"detail": "Graph Version not found"}`, which also covers a `version_number` outside `1..2**31-1` |
  | 422 | `RollbackValidationErrorResponse {code: "invalid_rollback", errors: [{field, code, message}] (min 1)}`; malformed JSON gives `$ / invalid_json / "Request body must be valid JSON."` |
  | 422 | `RollbackIncompatibleResponse {code: "rollback_incompatible", source: Ref, errors: [...] (min 1)}` |
  | 409 | `StaleRollbackResponse {code: "stale_rollback", expected_lock_version, current_lock_version, active_release: Ref, draft}` |
  | 409 | `RollbackSourceActiveResponse {code: "rollback_source_active", active_release: Ref}` |
  | 409 | `RollbackMatchesActiveResponse {code: "rollback_matches_active", active_release: Ref, source: Ref}` |
  | 500 | `{"detail": "Graph configuration is incomplete"}` |

  A SQLAlchemy `IntegrityError` is never caught (a plain 500), and an unknown outcome raises an `AssertionError` (500).

**Widened publish evidence item (C38)**
- `ReleaseEvidenceResponse` is `{agent_test_run_id, agent_key, test_case_id, evidence_kind: "approval"|"historical_restore", source_release_id: int|null}`, with the pairing validator.
- The publish 200 accepts only `approval` with `null`.

**Order of checks in the POST**
1. The router's `require_admin`.
2. `require_draft_write_principal`.
3. The body parse (so an invalid body on an unknown version is a 422).
4. The version range check (404).
5. `run_in_threadpool(restore_release)`.
6. Outcome mapping: an unknown version with a stale lock is a 404, not a 409 (Task 3a concern 3).

**Log contract**
- Each handler call emits exactly one `graph_release_rollback` record, with `extra` keys exactly `{outcome, agent_keys}`.
- Outcomes:
  - `restored`: sorted changed keys
  - `stale`
  - `not_found`
  - `source_active`
  - `matches_active`
  - `incompatible`: sorted distinct offending roles
  - `rejected`: body 422, service 422, or service actor 403
- `integrity_error` is logged at ERROR with `error_class` and no `exc_info` (C13/C37), and the rollback never calls `_graph_integrity_failure`.
- A 403 from a dependency emits nothing, because the handler never runs.

## Gates
- **New route tests:** 69 passed. **C46 join file:** 20 passed.
- **Named set:** 800 passed. It covers:
  - both new files
  - #269's `test_graph_release_routes.py`, `test_graph_release_preview.py`, `test_graph_release_publication.py`
  - `test_agent_definition_workbench_routes.py`
  - `test_graph_release_rollback.py`, `test_graph_release_history.py`
  - all 6 `tests/unit/test_*client_join*.py`
- **RED evidence:**
  - Before the handlers existed: 63 failed and 6 passed. The failures were 404s for every new path, missing `routes.list_release_history`, and the narrow evidence wire. The 6 passes were schema-only tests.
  - After the Python-only widening, exactly 4 #269 tests went RED, as C38 predicted: the publish exact body, the join key list, the join literal, and the registry pin. They went GREEN with the edits above.
- **Full unit:** 7 failed / 7122 passed / 110 skipped.
  - Six are the baseline nodes with the baseline causes:
    - deploy_autoscaling ×2: `'provisioned' == 'autoscaling'`
    - chokepoint ×3: `_FakeSession.execute`
    - persistence_boundary: "no active Graph Release"
  - The seventh, `test_persisted_agent_runtime.py::test_runtime_logging_sink_success_record_…`, is an artefact of where the suite ran. I ran it from a throwaway worktree under `/tmp`, which macOS resolves to `/private/tmp`, so `record.pathname` contains the forbidden word "private". The same node passes in the real worktree at the same SHA (114/114 in its file). The throwaway worktree is removed.
- **PostgreSQL** (one invocation each, zero skips, all green): publication 21, evidence 18, rollback 12, history 5, publication_acceptance 3, rollback_ordering 12. `tellr_int_*` still holds the 5 older DBs; I created or dropped none.
- **Vitest:** GraphRelease 152 passed; `src/components/Admin` 780 passed (baseline 778, plus the 2 new rows). `npm run typecheck` (`tsc -b`) is clean. No `npm install` and no Playwright.
- **ruff:** clean on every new or changed file. `test_agent_definition_workbench_routes.py` has 2 pre-existing findings, identical to base.
- **`main.py`:** `git diff --exit-code c7ea1d943 -- src/api/main.py` exits 0.

## Mutation sweep
- Each mutation: anchor count 1, marker `MUT270_6` count 1 while applied.
- Each was restored with `git checkout 0794afa25 -- <file>`. After each: `git diff --quiet 0794afa25 -- src tests frontend` was clean and the marker count was 0.

| # | Mutation | Result (first RED) |
|---|---|---|
| M01 (**plan REVIEWER sabotage**) | rollback handler gains `validator: Depends(get_remote_endpoint_draft_validator)` | RED `test_history_and_rollback_routes_do_no_model_or_remote_work` |
| M02 (**C38 sabotage**) | drop the `ReleaseEvidenceResponse` pairing validator | RED `test_release_evidence_pairs_the_kind_with_the_source` |
| M03 | drop publish approval-only validator | RED `test_the_publish_success_wire_stays_approval_only` |
| M04 | drop rollback all-reused check | RED `test_the_rollback_success_wire_is_restore_only_reused_and_exactly_seven` |
| M05 | drop rollback restore-only evidence check | RED same |
| M06 | service actor issue → 422 not 403 | RED `test_an_actor_rejection_is_the_principal_403_not_a_client_422` |
| M07 | rollback integrity via `_graph_integrity_failure` (`logger.exception`) | RED `test_a_rollback_integrity_failure_is_the_500_with_one_class_only_record` |
| M08 | restore called on the event loop | RED `test_rollback_runs_the_service_off_the_event_loop` |
| M09 | POST skips the version range check | RED `test_an_unknown_rollback_version_is_the_exact_404[0]`, `[-1]` (a service 422) |
| M10 | detail GET skips the version range check | **survives, equivalent**: the read model resolves versions in Python, so 0, -1 and 2**31 raise `GraphVersionNotFound` anyway. Kept as the existing idiom (defence-in-depth). |
| M11 | preview builds the facade without the dependency's validator | RED `test_the_preview_serves_endpoint_warnings_that_never_block` |
| M12 | comparison active/historical swapped | RED `test_the_comparison_is_the_exact_body` |
| M13 | log extra gains a `note` key | RED `test_a_rollback_restores_the_exact_200_body` |
| M14 | restored log carries the version number | RED same |
| M15 | incompatible → 409 | RED `test_an_incompatible_release_is_the_exact_422` |
| M16 | POST not-found → 409 | RED `test_an_unknown_version_with_a_stale_lock_is_404_not_409` |
| M17 | stale expected/current swapped | RED `test_a_stale_lock_is_the_exact_stale_409` |
| M18 | `RollbackRequest` `extra="ignore"` | RED `…invalid_rollback_422[extra_key]` |
| M19 | `RollbackRequest` not strict | RED `…[string_lock]`, `[bool_lock]` |
| M20 | `RollbackRequest.lock_version` `ge=0` | RED `…[negative_lock]` |
| M21 | drop the preview `restorable == (blocked is None)` validator | RED `test_the_preview_wire_derives_restorable_from_blocked` |
| M22 | history timestamps not labelled UTC | RED `test_the_history_list_is_the_exact_body_newest_first` |
| M23 | detail content `model_dump(mode="json")` not `canonical_payload()` | RED `test_the_detail_is_the_exact_body_with_canonical_content` |
| M24 | detail evidence source dropped | RED `test_a_restored_release_detail_names_its_source` |
| M25 | publish/rollback evidence built without `source_release_id` | RED 2/2: #269 `test_an_approved_change_publishes_the_exact_200_body` and `test_a_rollback_restores_the_exact_200_body` |
| M26 | no log on a body-parse 422 | RED 6/9 `…invalid_rollback_422[malformed_json…]` |
| M27 | incompatible log carries `[]` | RED `test_an_incompatible_release_is_the_exact_422` |
| M28 | drop rollback seven-mappings check | RED wire test |
| M29 | drop history-evidence pairing validator | RED `test_history_evidence_pairs_the_kind_with_the_source` |
| M30 | history list oldest first | RED list body test |
| M31 | preview `draft_effect` constant | RED `test_the_rollback_preview_is_the_exact_body` |
| M32 | `restored_from` id = the version number (ids ≠ versions) | RED success body test |
| M33 | list `active_release` = the last entry | RED list body test |
| T1 (TS) | `isReleaseEvidence` approval branch returns `true` | RED Vitest "rejects a 200 with an approval with a source" |
| T2 (TS) | the publish parser drops the approval-only rule | RED Vitest "rejects a 200 with a well-formed restore evidence item" |

I did **not** run the plan's CONTROLLER sabotage (remove `Depends(require_draft_write_principal)` and pass `actor=""`). Its target is `test_rollback_requires_a_nonblank_principal_before_the_body[None|''|' \t ']`.

## Deviations
1. **`RollbackRequest` has no `ge=0`.** The brief says `ge=0`.
   - I followed #269 Task 5 deviation 2 (accepted) and C31: the service's `_lock_version_issues` is the one lock authority.
   - A negative lock returns the service triple `lock_version/out_of_range/"Lock version must be greater than or equal to 0."`, the same as publish. M20 pins this.
2. **The route fixture is #269's `publication_tests.factory` plus Task 2's `build_v2_v3_v4`.**
   - That means C1's strictly increasing clock, which covers the rollback's own timestamp, and `offset_release_ids`, so every id is the version plus 10.
   - The brief asked for the workbench fixture plus v1 backdating. C1 supersedes the backdating, and the offset makes every id/version confusion RED (M32, and `test_a_version_equal_to_another_release_id_is_resolved_by_version`).
3. **Log levels.** The plan says INFO throughout; integrity is ERROR with no traceback, per C13/C37.
   - `agent_keys` is `sorted()`, as the plan says "sorted".
   - `rejected` is logged for body 422s, service 422s, and the service-actor 403.
   - An out-of-range path logs `not_found`.
4. **The body is parsed before the path range check** (the verdict route's idiom). An invalid body on an unknown version is therefore a 422 `invalid_rollback`, not a 404. The service's own order is the same: the request shape comes before not-found.
5. **Two #269 helpers now delegate to shared cores:**
   - `_parse_publish_request` → `_parse_release_body`
   - `_published_response` → `_published_fields`

   Both are behaviour-identical: all 45+ #269 route tests are green. This is the brief's "reuse, do not copy". No #269 handler changed.
6. **`Ref` reuses #269's `ReleaseIdentityResponse`** instead of a new model.
7. **The preview's evidence items carry three keys,** per the plan table. The kind is implicitly `historical_restore` from `source`.
8. **Two added TS test rows** in `releaseClient.test.ts`: a well-formed restore item, and a true extra key. They keep #269's intent pinned on both rules once the key became legal.
9. **The history detail's evidence includes `verdict_reviewer`**, because the Task 1 dataclass carries it. The route is admin-only.

## Concerns
1. **M10 is equivalent.** The range guard on the four GETs cannot be observed on SQLite or PostgreSQL, because no SQL binds the version. It is kept deliberately.
2. **Alphabetical and Graph order coincide in the fixture.** `sorted()` is used for the log's `agent_keys`, but the fixture's changed roles (`architect`, `builder`) are in the same order both ways, so a sorted→Graph-order mutation would survive. That is fine if either order is acceptable; say so if Graph order is wanted.
3. **Timestamp spellings differ across endpoints on SQLite.** The history wire labels stored instants UTC (`…Z`), per the Task 1 ruling, but `/workbench` still returns SQLite's naive value (no `Z`). On PostgreSQL both are aware. Task 7 should compare instants, not strings.
4. **Pydantic messages leak into `invalid_rollback`,** for example "Input should be a valid dictionary or instance of RollbackRequest". This is #269 Task 5 concern 1 again, from the shared renderer. Clients must key on `code`.
5. **Full-suite runs should not start from `/tmp` on macOS.** A path under `/private/tmp` trips `test_persisted_agent_runtime`'s "private" secret check. This is harness knowledge, not a defect.
6. **The C46 join file cannot yet pin TS parsers,** because Task 7 writes them. It pins the widened evidence item against the existing TS parser, and every new server model's exact key list and literals as the contract. Task 7 extends it with the TS-side lists.
