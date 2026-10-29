# Prompt Shipping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, together with the repo's `executing-plans-tellr` skill. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prompts promoted into the packaged Graph V1 manifest reach existing installs on deploy, when nobody has changed the live graph by hand. Otherwise an admin sees a badge and can adopt the shipped version.

**Architecture:** A new `_GraphConfigurationShipping` mixin joins the `GraphConfiguration` facade. It compares the packaged manifest with the active release and, when the install is untouched, publishes through the existing publication core (`_commit_locked_publication`) the way rollback does: no approval gate, and a three-way draft rebase. `run.py` calls it once at startup, after `bootstrap_graph_configuration`, and a failure there is never fatal. Two admin routes and a workbench badge expose the status and an Adopt action.

**Tech Stack:** Python 3, SQLAlchemy, FastAPI, pytest (SQLite unit suites under `tests/unit/`), React + TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-prompt-shipping-design.md`

## Global Constraints

- **Run everything via `uv run`** in this worktree's `.venv`. Never `pip install`.
- **Don't load the manifest from bootstrap.** `bootstrap_v1` must still not load the packaged manifest when a release exists (`tests/unit/test_graph_configuration_bootstrap.py::test_second_bootstrap_neither_loads_manifest_nor_rewrites_rows`, `::test_importing_service_directly_does_not_import_generated_snapshot`). Shipping is a separate step and the only one that loads it.
- **Locks and remote calls:** follow the global lock order in `src/services/graph_configuration_publication.py`'s module docstring. No model, runtime or remote-endpoint call while a lock is held. Shipping makes no remote call at all.
- **Actors and the release note:**
  - Code-shipped revisions are created by `system:code-ship`.
  - Code-shipped releases have `published_by="system:code-ship"` and `release_note=f"Shipped with Tellr {app_version}"`, where `app_version` is `src.__version__`.
- **"Untouched"** means every revision mapped by the active release either has `created_by` starting with `system:`, or has a `content_hash` equal to the packaged definition's hash for its role. **And** the active release's `restored_from_release_id` is null.
- **All or nothing at graph level.** If anything blocks shipping, no release is written.
- **Shipped content is always materialised as `system:code-ship`,** whether startup or an admin's adopt writes it, so that adopting makes the install untouched again.
- **A failure in the startup ship step never stops the app.** Bootstrap's own failures stay fatal, as today.

## Review Focus

1. **Two workers or instances start at once.** Exactly one release must result. Ship takes the bootstrap advisory lock and then L0 exclusive; a second call finds the release already matching and does nothing. Pinned in Task 1 (`test_second_ship_is_a_noop`) and by the lock-statement check (`test_ship_takes_the_bootstrap_lock_then_l0_exclusive`).
2. **An admin is mid-edit when a ship lands.** Their pending draft edit is kept, and their next save gets a normal stale-lock conflict, not lost data. Pinned in Task 1 (`test_pending_draft_edit_is_kept_across_a_ship`).
3. **The shipped manifest fails today's local validators,** for example the endpoint-name policy. Nothing is written, and the status says `invalid`. Pinned in Task 1 (`test_invalid_packaged_content_writes_nothing`).
4. **A rollback followed by a restart on the same code** must not re-ship the release that was rolled away from. Pinned in Task 1 (`test_rollback_blocks_reshipping`).
5. **Adopting from the admin page creates no admin-authored revisions,** so later ships auto-apply. Pinned in Task 1 (`test_adopt_makes_the_install_untouched_again`).

---

### Task 1: Shipping service

**Models:** test=opus impl=opus

This task writes release-integrity code, where a quiet mistake corrupts the active release.

**Files:**
- Create: `src/services/graph_configuration_shipping.py`
- Modify: `src/services/graph_configuration.py`: add the mixin to the `GraphConfiguration` MRO, **first**, before `_GraphConfigurationRollback`, so it can use rollback's `_draft_effect` and `_verify_rebased_draft` through `self`. Re-export the new public names, and add the startup wrapper `ship_packaged_graph_configuration`.
- Test: `tests/unit/test_graph_configuration_shipping.py`

**Interfaces:**
- Consumes:
  - `_lock_current_parents(session, *, exclusive)` and `_snapshot_locked_workbench` (workbench mixin).
  - `_lock_all_draft_agents(session, *, draft_id)`, `_candidate_contents_issues(contents)` and `_commit_locked_publication(...)` (publication mixin).
  - `_draft_effect(snapshot, hashes)`, `_verify_rebased_draft(...)` and `_assign_locked_candidate(row, content)` (rollback and draft mixins).
  - `_take_bootstrap_lock(session)` (bootstrap mixin).
  - `materialize_or_reuse_revision(session, content, *, actor, timestamp)` and `database_transaction_timestamp(session)` (`graph_configuration_content`).
  - `definition_content_hash`, `GraphV1Manifest`, `GRAPH_V1_AGENT_KEYS` and `load_graph_v1_manifest()` (`graph_definition_manifest`).
  - `definition_field_diffs(old, new)`.
- Produces (all exported from `src.services.graph_configuration`):
  ```python
  CODE_SHIP_ACTOR: Final = "system:code-ship"
  SYSTEM_ACTOR_PREFIX: Final = "system:"
  PackagedBlockReason = Literal["hand_edited", "rollback", "invalid"]

  @dataclass(frozen=True)
  class PackagedUpdateStatus:
      available: bool                                  # packaged != active (any role hash differs)
      differing_agents: tuple[AgentKey, ...]           # GRAPH_V1_AGENT_KEYS order
      blocked_reason: PackagedBlockReason | None       # None => would auto-ship (or nothing available)
      hand_edited_agents: tuple[AgentKey, ...]         # active revisions not created by system:* AND != packaged for the role
      validation_issues: tuple[DraftValidationIssue, ...]
      field_diffs: Mapping[AgentKey, tuple[FieldDiff, ...]]  # active -> packaged, differing roles only
      active_release: ActiveReleaseSnapshot
      lock_version: int                                # current shared-draft lock_version

  @dataclass(frozen=True)
  class ShipNothing:   release_id: int; version_number: int
  @dataclass(frozen=True)
  class ShipBlocked:   reason: Literal["hand_edited", "rollback"]; hand_edited_agents: tuple[AgentKey, ...]
  @dataclass(frozen=True)
  class ShipInvalid:   issues: tuple[DraftValidationIssue, ...]
  @dataclass(frozen=True)
  class Shipped:       published: PublishedRelease; draft_effect: Mapping[AgentKey, DraftEffect]

  ShipOutcome = ShipNothing | ShipBlocked | ShipInvalid | Shipped
  AdoptOutcome = PublicationConflict | ShipNothing | ShipInvalid | Shipped

  # _GraphConfigurationShipping methods
  def packaged_update_status(self, session: Session, *, manifest: GraphV1Manifest) -> PackagedUpdateStatus
  def ship_packaged_manifest(self, session_factory: sessionmaker, *, manifest: GraphV1Manifest, app_version: str) -> ShipOutcome
  def adopt_packaged_manifest(self, session: Session, *, manifest: GraphV1Manifest, app_version: str,
                              actor: str, expected_lock_version: int) -> AdoptOutcome

  # graph_configuration.py, the startup wrapper
  def ship_packaged_graph_configuration(session_factory: sessionmaker) -> ShipOutcome
      # loads load_graph_v1_manifest() and src.__version__, calls ship_packaged_manifest
  ```

**Behaviour that each test pins:**
- `ship_packaged_manifest`:
  - Runs in one `session_factory.begin()` transaction: `_take_bootstrap_lock`, then `_lock_current_parents(exclusive=True)`, then `_lock_all_draft_agents`, then the snapshot.
  - If all seven hashes match: `ShipNothing`, with no write.
  - Otherwise, if any active revision is hand-edited, or the release is a restore: materialise every differing packaged definition with `actor=CODE_SHIP_ACTOR`. Write nothing else (no release, no draft change), and return `ShipBlocked`.
  - Otherwise, if `_candidate_contents_issues(packaged contents)` reports issues: `ShipInvalid`, with **no** write.
  - Otherwise:
    1. Pre-materialise the seven packaged definitions with `CODE_SHIP_ACTOR`.
    2. Compute `_draft_effect`.
    3. Call `_commit_locked_publication(..., evidence=(), actor=CODE_SHIP_ACTOR, release_note=f"Shipped with Tellr {app_version}", restored_from_release_id=None)`.
    4. Apply `reset` effects with `_assign_locked_candidate`.
    5. Call `_verify_rebased_draft`.
    6. Return `Shipped`.
- `adopt_packaged_manifest`:
  - Runs in the same transaction shape (no advisory lock needed).
  - Checks `expected_lock_version` against the draft's lock version; a mismatch returns `PublicationConflict`, the same type rollback returns.
  - Then: `ShipNothing` if everything matches, or `ShipInvalid` if there are issues.
  - Otherwise, pre-materialise with `CODE_SHIP_ACTOR`, then publish with `actor=<admin>`. Hand edits and rollbacks do **not** block an adopt.
- `packaged_update_status`:
  - Takes a shared lock (`exclusive=False`) and writes nothing.
  - `blocked_reason` is the first that applies, in this order: `"invalid"` if `validation_issues`, else `"hand_edited"` if `hand_edited_agents`, else `"rollback"` if `restored_from_release_id` is set, else `None`. It is always `None` when `available` is false.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_graph_configuration_shipping.py`.

  Reuse the SQLite `factory` fixture, `_NoEvidenceGate`, `_save_prompt`, `_save_model` and `_publish` from `tests/unit/test_graph_release_publication.py`, and `install_release_clock` and `current_lock` from `tests/unit/test_graph_release_rollback.py`. Build test manifests with a helper that copies `load_graph_v1_manifest()` and changes one role's `prompt_text`. Use `model_copy(update=...)` on the frozen models and rebuild `GraphV1Manifest(manifest_version=1, definitions=...)`.

  The tests:
  - `test_untouched_install_ships_the_packaged_manifest_as_the_next_release`:
    - V2 is active.
    - `published_by == "system:code-ship"`.
    - `release_note == "Shipped with Tellr 9.9.9"` (pass `app_version="9.9.9"`).
    - The changed role's new revision has `created_by == "system:code-ship"`.
    - The six unchanged roles reuse their v1 revision ids.
    - The `Shipped.published.changed_agent_keys == ("architect",)`.
  - `test_matching_manifest_is_a_noop`: shipping the unmodified packaged manifest on a fresh bootstrap gives `ShipNothing`, and the `_artifacts(factory)` snapshot is identical before and after.
  - `test_second_ship_is_a_noop`: ship the modified manifest twice. The second call returns `ShipNothing`, and exactly one release exists beyond v1.
  - `test_hand_edited_prompt_blocks_ship_and_inserts_system_revisions`:
    - `_save_prompt` plus `_publish` of the builder as `publisher@example.com`, then ship a manifest that changes the architect.
    - Result: `ShipBlocked(reason="hand_edited", hand_edited_agents=("builder",))`.
    - No new release.
    - An `AgentDefinitionRevision` row with the packaged architect hash exists, with `created_by == "system:code-ship"`.
    - Draft `lock_version` is unchanged.
  - `test_model_only_edit_blocks_ship`: the same, but via `_save_model`, gives `ShipBlocked(reason="hand_edited")`.
  - `test_rollback_blocks_reshipping`:
    - Ship v2 from manifest M.
    - `restore_release` to version 1 as `admin@example.com`.
    - Ship M again. Result: `ShipBlocked(reason="rollback", hand_edited_agents=())`, and the active release is still the restore.
  - `test_pending_draft_edit_is_kept_across_a_ship`:
    - Save, but don't publish, a builder draft edit.
    - Ship a manifest changing the architect and the builder.
    - `draft_effect["builder"] == "kept"`, and the builder draft still holds the edit.
    - `draft_effect["architect"] == "reset"`, and the architect draft hash equals the packaged hash.
    - `draft_effect["fixer"] == "unchanged"`.
  - `test_invalid_packaged_content_writes_nothing`:
    - Monkeypatch `GraphConfiguration._candidate_contents_issues` to return one `DraftValidationIssue("definitions.architect.model.endpoint_name", "endpoint_policy", "x")`.
    - Result: `ShipInvalid` with that issue, and `_artifacts` is unchanged.
  - `test_ship_takes_the_bootstrap_lock_then_l0_exclusive`: capture statements as the rollback suite does (`event.listen(engine, "before_cursor_execute")`, then compile for postgresql). The first lock statement is the advisory lock (skipped on SQLite; assert `_take_bootstrap_lock` was called first, via a spy). The parent select is `FOR UPDATE`.
  - `test_adopt_publishes_shipped_content_under_the_admin_with_system_revisions`:
    - From the hand-edited state above, adopt as `admin@example.com` with the current lock.
    - The new release has `published_by == "admin@example.com"`.
    - Every mapped revision for a differing role has `created_by == "system:code-ship"`.
    - The architect's draft is reset to the packaged content.
  - `test_adopt_makes_the_install_untouched_again`:
    - After the adopt above, ship manifest M2, which changes the deck_reviewer.
    - Result: `Shipped`, published by `system:code-ship`.
    - Note: the builder edit was replaced by the adopt, because adopt publishes all seven packaged definitions.
  - `test_adopt_with_a_stale_lock_is_a_conflict_and_writes_nothing`.
  - `test_hand_applied_shipped_text_counts_as_untouched_while_it_matches`:
    - An admin publishes the architect with exactly M's architect prompt text before M ships.
    - Ship M gives `ShipNothing`, because the hashes match.
    - Ship M2, which changes only the deck_reviewer and keeps M's architect text, gives `Shipped`. The admin-created architect revision equals the packaged one, so it isn't hand-edited.
    - Ship M3, which changes the architect's text, gives `ShipBlocked("hand_edited", ("architect",))`. The live architect is still the admin-created revision.
    - Adopt M3, then ship M4 (another deck_reviewer change), gives `Shipped`.
  - `test_model_only_edit_blocks_ship` and `test_hand_edited_prompt_blocks_ship_and_inserts_system_revisions` must use manifests where the edited role's packaged content differs from the edit. Otherwise the content fallback would make them untouched.
  - `test_status_reports_reason_agents_and_diffs`: cover each reason in priority order. `field_diffs` keys are exactly `differing_agents`, and each diff equals `definition_field_diffs(active, packaged)`.

- [ ] **Step 2: Run the tests and confirm they fail**

  Run: `uv run pytest tests/unit/test_graph_configuration_shipping.py -q`
  Expected: collection error or failures, with `ImportError` for `ship_packaged_manifest` / `PackagedUpdateStatus`.

- [ ] **Step 3: Implement `src/services/graph_configuration_shipping.py`** with the interfaces above.

  Approach:
  - One private `_packaged_contents(manifest) -> dict[AgentKey, DefinitionContent]`.
  - One private `_hand_edited_agents(session, snapshot, packaged_hashes) -> tuple[AgentKey, ...]`, which reads `AgentDefinitionRevision.created_by` for the seven `published.revision_id`s. A role is hand-edited only if its creator is not `system:*` **and** its hash differs from the packaged hash for that role.
  - Shared by all three public methods.
  - Imports of rollback/publication types follow those modules' lazy-import comments (Correction 29) to avoid cycles.

- [ ] **Step 4: Run the new suite plus the neighbouring suites**

  Run: `uv run pytest tests/unit/test_graph_configuration_shipping.py tests/unit/test_graph_release_publication.py tests/unit/test_graph_release_rollback.py tests/unit/test_graph_configuration_bootstrap.py tests/unit/test_graph_configuration_workbench.py -q`
  Expected: all pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/services/graph_configuration_shipping.py src/services/graph_configuration.py tests/unit/test_graph_configuration_shipping.py
  git commit -m "feat(graph-config): ship packaged prompts to untouched installs"
  ```

### Task 2: Run shipping at startup, and document it

**Models:** test=sonnet impl=haiku

**Files:**
- Modify: `packages/databricks-tellr-app/databricks_tellr_app/run.py`: after the `Bootstrapping Graph Configuration...` block, before `Migrating profiles/sessions...`.
- Modify: `tests/unit/test_startup_migrations.py`
- Modify: `docs/technical/backend-overview.md`: the "**Rollout.**" paragraph near line 593 currently says an existing install keeps its persisted prompts. Rewrite it to describe prompt shipping, and add a short "Prompt shipping" subsection next to the workbench section near line 465.

**Interfaces:**
- Consumes: `ship_packaged_graph_configuration(session_factory) -> ShipOutcome` (Task 1).
- Produces: none.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_startup_migrations.py`:
  - Extend `test_init_database_runs_profile_and_session_migrations`: monkeypatch `src.services.graph_configuration.ship_packaged_graph_configuration` to record `("ship_packaged_graph_configuration", sf)` and return `SimpleNamespace()`. The expected `calls` list gains that tuple directly after `("bootstrap_graph_configuration", "SESSION_FACTORY")`.
  - New `test_init_database_ship_failure_is_logged_and_startup_continues`:
    - The ship stub raises `RuntimeError("ship failed")`.
    - `run.init_database()` returns without `SystemExit`.
    - Every later stage still appears in `calls`.
    - `caplog` has one ERROR record containing `"Failed to ship packaged Graph Configuration"`.
  - Every other test in the file that pins the call list must also stub the ship step, so the file keeps passing.

- [ ] **Step 2: Run the tests and confirm they fail**

  Run: `uv run pytest tests/unit/test_startup_migrations.py -q`
  Expected: FAIL. The ship stub is never called, and the order differs.

- [ ] **Step 3: Implement the startup step in `run.py`**

  ```python
  try:
      outcome = ship_packaged_graph_configuration(get_session_local())
      logger.info("Packaged Graph Configuration: %s", type(outcome).__name__)
  except Exception as e:
      logger.error(f"Failed to ship packaged Graph Configuration: {e}\n{traceback.format_exc()}")
  ```

  Log `Shipped` with its version number, and `ShipBlocked` / `ShipInvalid` with the reason or issue codes.

- [ ] **Step 4: Update `docs/technical/backend-overview.md`** as described under Files. Name the rule, the actor, the badge, Adopt, and the edge case.

- [ ] **Step 5: Run the tests**

  Run: `uv run pytest tests/unit/test_startup_migrations.py -q`
  Expected: PASS.

- [ ] **Step 6: Commit**

  ```bash
  git commit -am "feat(startup): ship packaged Graph Configuration after bootstrap"
  ```

### Task 3: Admin API (status and adopt)

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `src/api/routes/agent_definitions.py`. The router is already admin-only (`dependencies=[Depends(require_admin)]`).
- Modify: `src/api/schemas/agent_definitions.py`
- Test: `tests/unit/test_agent_definitions_packaged_update_routes.py`. Mirror the client and fixture setup of the existing rollback route tests: `grep -rln "rollback" tests/unit/test_agent_definition*`.

**Interfaces:**
- Consumes: `packaged_update_status`, `adopt_packaged_manifest` and the outcome types (Task 1); `load_graph_v1_manifest()`; `src.__version__`; `require_draft_write_principal` (the rollback route's actor dependency); `_issue_responses`; `_json`; `_parse_release_body`.
- Produces:
  - `GET /api/admin/agent-definitions/packaged-update` returns 200 `PackagedUpdateResponse`:
    ```
    { available: bool, differing_agents: [AgentKey], blocked_reason: "hand_edited"|"rollback"|"invalid"|null,
      hand_edited_agents: [AgentKey], validation_issues: [{field, code, message}],
      diffs: [{agent_key, field_diffs: [<existing FieldDiff response shape>]}],
      active_version_number: int, lock_version: int }
    ```
  - `POST /api/admin/agent-definitions/packaged-update/adopt` takes the body `{"lock_version": int}` (strict, extra fields forbidden). It returns:
    - 200 `PackagedAdoptSuccessResponse {release: ActiveReleaseResponse, changed_agent_keys: [AgentKey], draft_effect: {AgentKey: "reset"|"kept"|"unchanged"}}`;
    - 409 with the existing stale-lock response shape on `PublicationConflict`;
    - 409 `{"code": "nothing_to_adopt"}` on `ShipNothing`;
    - 422 `{"code": "packaged_invalid", "errors": [...]}` on `ShipInvalid`;
    - 403 when the principal is missing, the same as rollback.
  - The route runs the service via `run_in_threadpool`, as `_restore_graph_release` does.

- [ ] **Step 1: Write the failing route tests:**
  - status on a fresh install gives `available: false, blocked_reason: null`;
  - status with a monkeypatched `load_graph_v1_manifest` returning a modified manifest gives `available: true` and the `diffs` entries;
  - adopt success: a 200, then status gives `available: false`;
  - adopt with a stale lock gives a 409;
  - adopt with nothing to adopt gives a 409 with `nothing_to_adopt`;
  - adopt with invalid content gives a 422 with `packaged_invalid`;
  - adopt with an unknown body key gives a 422 validation error;
  - a non-admin gets a 403 on both routes.
- [ ] **Step 2: Run them and confirm they fail.**
  Run: `uv run pytest tests/unit/test_agent_definitions_packaged_update_routes.py -q`
  Expected: 404s, so FAIL.
- [ ] **Step 3: Implement the two routes and their response models.**
- [ ] **Step 4: Run the tests, plus the existing agent-definitions route tests, and confirm they pass.**
- [ ] **Step 5: Commit.** `git commit -m "feat(admin-api): packaged prompt update status and adopt"`

### Task 4: Workbench badge, review and Adopt

**Models:** test=sonnet impl=sonnet

**Files:**
- Modify: `frontend/src/api/agentDefinitions.ts`. Add `getPackagedUpdate(): Promise<PackagedUpdate>` and `adoptPackagedUpdate(lockVersion: number): Promise<PackagedAdoptResult>`, with strict `parse…` functions in the file's existing style. Typed errors go through `AgentDefinitionApiError`.
- Create: `frontend/src/components/Admin/AgentDefinitionWorkbench/PackagedUpdateBadge.tsx`
- Modify: `frontend/src/components/Admin/AgentDefinitionWorkbench/AgentDefinitionWorkbench.tsx`. Render the badge in `WorkbenchContent`'s `<header>`. After a successful adopt, reload the workbench through the same path the parent uses on first load.
- Test: `frontend/src/components/Admin/AgentDefinitionWorkbench/PackagedUpdateBadge.test.tsx`, and a parse test in the existing `agentDefinitions` API test file, if there is one.

**Interfaces:**
- Consumes: the Task 3 routes; `FieldDiffView` from `frontend/src/components/Admin/GraphRelease/`.
- Produces: `<PackagedUpdateBadge onAdopted={() => void} />`. It fetches its own status.

**Copy (exact):**
- Title: `A newer shipped version is available`
- `blocked_reason === "hand_edited"`: `Not applied automatically because these agents were edited here: {comma-separated display names}.`
- `"rollback"`: `Not applied automatically because the live release is a rollback.`
- `"invalid"`: `The shipped version failed validation and was not applied.` The Adopt button is disabled.
- `null`: `It will be applied automatically on the next restart.`
- Buttons: `Review changes`, which toggles the per-agent `FieldDiffView`s, and `Adopt shipped version`, which asks `Publish the shipped version as the next Graph Version? Pending draft edits are kept.` before posting.

- [ ] **Step 1: Write the failing vitest tests:**
  - no badge when `available: false`;
  - each reason renders its exact copy;
  - Review shows one diff per differing agent;
  - Adopt confirms, posts the current `lock_version`, and calls `onAdopted` on 200;
  - a 409 shows `The draft changed since you loaded it. Reload and try again.`;
  - Adopt is disabled when the reason is invalid.
- [ ] **Step 2: Run them and confirm they fail.**
  Run: `cd frontend && npx vitest run src/components/Admin/AgentDefinitionWorkbench/PackagedUpdateBadge.test.tsx`
- [ ] **Step 3: Implement the API functions, the badge and the wiring.**
- [ ] **Step 4: Run the tests, then `cd frontend && npx tsc --noEmit && npx vitest run src/components/Admin`. All should pass.**
- [ ] **Step 5: Commit.** `git commit -m "feat(admin-ui): shipped-version badge with review and adopt"`

### Task 5: Whole-branch review, PR, CI, devloop (controller)

**Models:** test=opus impl=opus

Done by the controller. The whole-branch reviewer is always Opus.

- [ ] **Step 1:** Run `uv run pytest tests/unit -q -x --ignore=tests/unit/<known-baseline-failures>`, using the cause-based baseline recorded before Task 1, plus `cd frontend && npx tsc --noEmit && npx vitest run`.
- [ ] **Step 2:** Whole-branch Opus review. Supply the ledger's parked list. Ask for:
  - a rollback-guarantee ruling (every refusal precedes every write);
  - a lock-order check;
  - merge/no-merge.
- [ ] **Step 3:** Push `feat/prompt-shipping` as the personal account and open a PR to `main`. Iterate until CI is green.
- [ ] **Step 4:** Publish a `.devN` (`gh workflow run publish-dev.yml --ref feat/prompt-shipping`), then deploy to devloop instance `prompt-ship` (`deploy-tellr-dev` skill).
- [ ] **Step 5:** Verify on the instance:
  - the startup log line `Packaged Graph Configuration: …`;
  - the workbench shows either a code-shipped Graph Version, or the badge with a reason.
