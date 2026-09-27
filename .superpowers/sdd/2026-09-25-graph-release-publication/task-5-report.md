# Task 5 report: preview service, field diffs, admin preview/publish routes

**Status:** DONE_WITH_CONCERNS (minor; see the end).
**TASK_BASE:** `66d112a1c`. **Mutation pin:** `124185497`.

## Commits
| SHA | Summary |
|---|---|
| `bda5273af` | feat: preview and publish graph releases over admin HTTP (#269) |
| `124185497` | test: pin preview role order against a non-alphabetical pair (#269) |

Files:
- **Modified:**
  - `src/services/graph_configuration_publication.py` adds:
    - `DIFF_FIELD_NAMES` and `_DIFF_FIELDS`
    - `FieldDiff`, `ChangedDefinitionPreview`, `ReleasePreview`
    - `definition_field_diffs`
    - `release_is_publishable`, the one definition of publishable (C22)
    - `preview_release`
  - It also splits `_validate_changed_candidates` into `_changed_candidate_issues` (collects) and the raising wrapper. Publish behaviour is unchanged.
  - `src/services/graph_configuration.py` re-exports the new names.
  - `src/api/routes/agent_definitions.py`: the two handlers are on the EXISTING router (C31/C35). Other additions: `_readiness_callable`, `_parse_publish_request`, and the outcome mappers.
  - `tests/unit/test_agent_definition_workbench_routes.py`: the exhaustive `test_main_app_registers_the_dedicated_workbench_route` registry gains the two paths. This was an intended pin change: it went RED on the new routes.
- **Created:**
  - `src/api/schemas/graph_releases.py`
  - `tests/unit/test_graph_release_preview.py` (31 tests)
  - `tests/unit/test_graph_release_routes.py` (45 tests)
- **Not created or changed:** no `src/api/routes/graph_releases.py`, and no `main.py` change (C35).

## Route paths (exact)
- `GET  /api/admin/agent-definitions/release-preview` → 200 `ReleasePreviewResponse`. Plain `def`, so it runs in the threadpool.
- `POST /api/admin/agent-definitions/releases` → 200 `PublishReleaseSuccessResponse` (C10/Q6: **200, not 201**). Other outcomes: 409 stale / nothing / not-ready, 422 `invalid_publication`, 403, 500.

Auth order:
1. The router's `require_admin`.
2. `require_draft_write_principal` as a signature `Depends`, then `get_agent_test_workbench`.
3. The body is read only inside the handler.

The actor is always the principal. A body `actor` key is `extra_forbidden`.

## Wire models (Task 6's TS parsers must match these)
Every model below is `extra="forbid"`. The embedded existing models are `ActiveReleaseResponse`, `DraftMetadataResponse`, `DraftFieldErrorResponse` and `DraftReadinessResponse` (#268's, verbatim; there is no second readiness type).

**Preview (`GET /release-preview`)**
- `ReleasePreviewResponse`, keys in this order:
  - `draft`: DraftMetadataResponse
  - `active_release`: ActiveReleaseResponse
  - `next_version_number`: int ≥2
  - `changed`: ChangedDefinitionResponse[]
  - `readiness`: DraftReadinessResponse
  - `validation_issues`: {field, code, message}[]
  - `publishable`: bool
- `ChangedDefinitionResponse`:
  - `agent_key`: AgentKey
  - `published_revision_id`: int
  - `published_content_hash`: sha256
  - `candidate_hash`: sha256
  - `field_diffs`: FieldDiffResponse[] (min 1)
  - The array is in `GRAPH_V1_AGENT_KEYS` order.
- `FieldDiffResponse`:
  - `field`: one of `definition_version`, `prompt_text`, `model.endpoint_name`, `model.temperature`, `model.max_tokens`, `model.top_p`, `schema_overlay`, `assembly_rules`, `protected_assembly.version`, `protected_assembly.digest`, `schema_contract.version`, `schema_contract.digest`, in that order
  - `published`: JSON
  - `candidate`: JSON
  - Only differing fields are listed. `schema_overlay` and `assembly_rules` are whole JSON documents.

**Publish request**
- `PublishReleaseRequest`: `{lock_version: int, release_note: str}`, `extra="forbid", strict=True`, with no `ge` and no `max_length` (see deviation 2).

**Publish 200**
- `PublishReleaseSuccessResponse`, keys in this order:
  - `release`: ActiveReleaseResponse
  - `previous_release_id`: int
  - `changed_agents`: AgentKey[] (min 1)
  - `mappings`: {AgentKey: `{agent_definition_revision_id: int, content_hash: sha256, reused: bool}`}
  - `evidence`: `{agent_test_run_id, agent_key, test_case_id, evidence_kind: "approval"}`[]
  - `draft`: DraftMetadataResponse
- `mappings` must hold exactly the 7 keys in `GRAPH_V1_AGENT_KEYS` order (validator).

**Publish 409**
- `StalePublicationResponse`: `{code: "stale_publication", expected_lock_version, current_lock_version, active_release: {release_id, version_number}, draft}`.
- `NothingToPublishResponse`: `{code: "nothing_to_publish", active_release: {release_id, version_number}, draft}`.
- `PublicationNotReadyResponse`: `{code: "publication_not_ready", gaps: [{agent_key, test_case_id: int|null, code: "no_required_case"|"no_eligible_approval"}] (min 1), readiness: DraftReadinessResponse}`.
  - The gap validator requires `test_case_id` to be null exactly when `code` is `no_required_case`.
  - Gaps are in the gate's order.

**Publish 422**
- `PublicationValidationErrorResponse`: `{code: "invalid_publication", errors: [{field, code, message}]}`. The errors are:
  - malformed JSON: `$ / invalid_json / "Request body must be valid JSON."`
  - Pydantic structure and type errors, rendered by the module's existing `_request_validation_errors`:
    - `extra_forbidden`
    - `strict_type` with the Pydantic message: "Input should be a valid integer", "Input should be a valid string", "Field required", or, for a non-object body, `$` "Input should be a valid dictionary or instance of PublishReleaseRequest"
  - service triples, verbatim:
    - `release_note/blank`, `release_note/too_long` (2001 characters)
    - `lock_version/out_of_range`
    - `definitions.<key>.<field>` candidate issues

**500**
- `GraphConfigurationIntegrityError` → `{"detail":"Graph configuration is incomplete"}`, with `logger.exception`.
- A SQLAlchemy `IntegrityError` is not caught; it stays a plain 500 (#268 C7).
- An unknown outcome raises an `AssertionError`, which is a 500.
- A `PublicationRejected` naming `actor` → 403 "Authenticated principal required", the verdict route's rule. It is unreachable in practice, but it is pinned.

## Service design
- `preview_release(session, *, readiness)` runs inside one `with session.begin()`, in this order:
  1. `_lock_current_parents(exclusive=False)`
  2. `_snapshot_locked_workbench`
  3. changed roles
  4. `_changed_candidate_issues` (the local validators plus the endpoint policy plus post-stale; never `_validate_remote_endpoint`, C37)
  5. one plain SELECT of the changed roles' active required case keys
  6. `readiness(session)`, once, in the transaction, after L0 (C39)

  It writes nothing; the statement capture shows only SELECTs.
- `publishable = bool(changed) and not validation_issues and every changed role has an active required case and not (readiness.blocking_agents ∩ changed)`. This is `release_is_publishable`. The route serves it verbatim, and a test patches the function to prove the route does not recompute it.
- The production binding is `_readiness_callable(workbench) → workbench.readiness_under_parent_lock`, where `workbench` is the resolved `get_agent_test_workbench` dependency. The POST builds `ApprovalEvidenceGate(readiness=_readiness_callable(workbench))` and runs `await run_in_threadpool(GraphConfiguration().publish_draft, …)` (C46).

## Gates
- **New unit files:** preview 31, routes 45. All green.
- **Focused unit set:** 1116 passed. It covers:
  - both new files
  - `test_agent_definition_workbench_routes.py`
  - `test_graph_release_publication.py`, `test_graph_release_evidence.py`
  - `test_agent_test_workbench.py`, `test_graph_configuration_draft.py`
  - `test_graph_parent_lock_is_single_sourced.py`
  - `test_prompt_assembler.py`
  - all 4 `test_*client_join*.py`
- **Client joins:** all 4 green. No Python↔TS join went RED, and no TS was touched.
- **Full unit suite:** 6 failed, 6934 passed, 110 skipped, 01:52 to 02:00 UTC (it did not cross midnight). These are exactly the baseline six by node, and their causes were re-checked:
  - deploy_autoscaling ×2: provisioned/autoscaling asserts
  - chokepoint ×3: `_FakeSession.execute`
  - persistence_boundary: "no active Graph Release"
- **PostgreSQL**, one invocation each, zero skips:

  | File | Passed |
  |---|---|
  | publication | 21 |
  | evidence | 18 |
  | agent_definition_workbench | 49 |

  Only the 4 older `tellr_int_*` databases remain; none leaked.
- **ruff:** clean on every new or changed source file. `test_agent_definition_workbench_routes.py` has 2 pre-existing findings (F401, I001), identical at base.

**RED evidence:** both new files failed at collection on the missing imports before the implementation. The workbench registry pin went RED on the new routes, which was expected. Discriminating power rests on the sweep below.

## Mutation sweep
Each mutation was restored with `git checkout 124185497 -- <file>`. After every one, `git diff --quiet 124185497 -- src tests` returned 0 and the `MUT269_5` marker count was 0. All 32 went RED.

| # | Mutation | First RED |
|---|---|---|
| M01 (plan REVIEWER sabotage) | diffs from `model_dump(mode="python")` | `test_a_float_and_its_decimal_are_not_a_diff` |
| M02 | every field emitted | `test_identical_definitions_have_no_diffs` |
| M03 | publishable drops `bool(changed)` | `test_an_unchanged_draft_previews_nothing_and_is_not_publishable` |
| M04 | drops validation clause | `test_validation_issues_are_collected_prefixed_and_block` |
| M05 | drops required-case clause | `test_a_changed_role_without_an_active_required_case_is_not_publishable` |
| M06 | drops readiness clause | `test_a_changed_role_awaiting_approval_is_not_publishable` |
| M07 | readiness clause ignores `∩ changed` | `test_readiness_blocking_only_an_unchanged_role_does_not_block` |
| M08 | case query drops `is_required` | `test_an_optional_active_case_does_not_satisfy_the_required_case_clause` |
| M09 | case query drops `is_active` | `test_a_changed_role_without_an_active_required_case_is_not_publishable` |
| M10 | preview raises instead of collecting | `test_validation_issues_are_collected_prefixed_and_block` |
| M11 | preview takes exclusive L0 | `test_the_preview_takes_the_shared_parent_lock` |
| M12 | readiness read before L0 | `test_an_unchanged_draft_…` (readiness called twice) |
| M13 | preview calls `_validate_remote_endpoint` | `test_the_preview_never_calls_the_remote_endpoint_validator` |
| M14 | `next_version_number` = active | `test_an_unchanged_draft_…` |
| M15 | changed sorted alphabetically | `test_changed_roles_preview_in_role_order_with_exact_diffs` (added commit `124185497`: fixer/deck_reviewer) |
| M16 | publish on the event loop | `test_publish_runs_the_service_off_the_event_loop` |
| M17 | binding uses a fresh `AgentTestWorkbench()` | `test_the_production_readiness_binding_is_the_dependency_workbench` |
| M18 | gate bound to `workbench.draft_readiness` | `test_a_changed_role_without_approval_is_the_exact_not_ready_409` |
| M19 | actor rejection → 422 | `test_an_actor_rejection_is_the_principal_403_not_a_client_422` |
| M20 | POST integrity error not caught | `test_an_integrity_failure_is_the_existing_500` |
| M21 | any exception → friendly 409 | `test_a_database_integrity_error_is_never_translated` |
| M22 | stale expected/current swapped | `test_a_stale_lock_is_the_exact_stale_publication_409` |
| M23 | preview integrity error not caught | `test_the_preview_integrity_failure_is_the_existing_500` |
| M24 | route recomputes publishable | `test_the_preview_serves_the_services_publishable_verbatim` |
| M25 | request `extra="ignore"` | `test_the_actor_is_the_principal_never_the_body` |
| M26 | request not strict | `test_a_bad_body_…[string_lock]` |
| M27 | request `lock_version` `ge=0` | `test_a_negative_lock_is_the_service_lock_rule_422` |
| M28 | gap validator removed | `test_the_gap_wire_refuses_a_case_id_that_disagrees_with_its_code` |
| M29 | seven-mapping validator removed | `test_the_success_wire_requires_exactly_the_seven_mappings` |
| M30 | response models allow extra | `test_every_release_wire_model_forbids_extra_keys` |
| M31 | diff literal drifts | `test_the_diff_field_literal_is_the_service_vocabulary` |
| M32 | not-ready readiness not from the gate result | `test_a_changed_role_without_approval_is_the_exact_not_ready_409` |

I did **not** run the plan's CONTROLLER sabotage (remove `not note.strip()` in `_validate_publication_request`). Its route-level target is `test_a_blank_note_is_the_exact_service_422`.

## Deviations
1. **Status 200, not 201**, per C10/Q6, which overrides the brief.
2. **`PublishReleaseRequest` carries no `ge=0`.**
   - The brief said `ge=0`. I dropped it so the lock range comes from `_lock_version_issues` (C17/C36 single authority, and C10's precedent for the note cap).
   - A negative lock returns the service triple `lock_version/out_of_range/"Lock version must be greater than or equal to 0."`, not Pydantic's text. M27 pins this.
   - Existing routes such as `DraftLockRequest` still keep `ge=0`.
3. **`_readiness_callable(workbench)` takes the resolved dependency** instead of calling `get_agent_test_workbench()` directly. A direct call would bypass `app.dependency_overrides`, so Task 8's single override would not reach readiness. The C21 monkeypatch target, `routes._readiness_callable`, is unchanged.
4. **Success evidence came from real writers.** C21 suggests ORM-seeding. I used #267's executor on the fake adapter and #268's verdict route, over HTTP. `no_required_case` is produced by an ORM deactivation (C43).
5. **`ChangedDefinitionPreview` fields.** The plan did not specify them. They are `agent_key, published_revision_id, published_content_hash, candidate_hash, field_diffs`.
6. **The "≥1 active required case" clause** is a direct plain SELECT in the preview transaction. It does not use readiness's `missing_required_case`, so it holds even under a faked readiness.
7. **Evidence wire `evidence_kind` is `Literal["approval"]`**, with no `source_release_id`, per the plan's table. #270 must widen this if it reuses the model for restore.
8. **SQLite timestamp artefact in the success test.** The publish returns the aware transaction timestamp (`…Z`), while a later GET on SQLite reads the value back naive. The test compares with the `Z` stripped; PostgreSQL returns aware values both ways.

## Concerns
1. **Pydantic messages leak into `invalid_publication`.** Examples are "Input should be a valid dictionary or instance of PublishReleaseRequest" and "Input should be a valid integer". This is the module's existing renderer behaviour, but the text names a Python class. Task 6 should key on `code`, never on these messages.
2. **Gap codes have no message table.** They are client-labelled codes by design (C1 part 4). A new gap code needs the Literal in `PublicationGapCodeWire`, or it becomes a 500 (a Pydantic error at response build).
3. **C46's "another request is served while POST waits" was not built as a two-request concurrency test.** I used #268's off-loop pattern (the service observed with no running loop), as the brief allows. M16 is RED on it.
4. The preview route test uses architect and builder, whose alphabetical order equals their role order. Role ordering is pinned at service level (M15).
