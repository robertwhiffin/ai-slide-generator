# Task 9 report: end-to-end rollback acceptance over admin HTTP

**Status:** DONE
**TASK_BASE:** `5b11f3da7` (docs: record #270 Task 7 complete). **Commit:** `7b2511b58`.

## Commits

| SHA | Summary |
|---|---|
| `7b2511b58` | test: end-to-end rollback acceptance over admin HTTP (#270) |
| (this report) | docs: record #270 Task 9 |

Files in `7b2511b58`:
- **Created:** `tests/integration/test_graph_release_rollback_acceptance_postgres.py`
- **Modified:** `.github/workflows/test.yml` — added new file to `integration-graph` block after `test_graph_release_rollback_ordering_postgres.py`
- **Modified:** `tests/unit/test_ci_collects_integration_tests.py` — added `test_graph_release_rollback_acceptance_is_collected_by_integration_graph` pin; fixed import ordering (ruff I001)

## Gates

- **New file:** 1 passed (zero skips).
- **PostgreSQL gate files (each in its own invocation, zero skips, all green):**
  - `test_graph_release_publication_postgres.py`: 21 passed
  - `test_graph_release_history_postgres.py`: 5 passed
  - `test_graph_release_rollback_postgres.py`: 12 passed (including injected-failure stages)
  - `test_graph_release_publication_acceptance_postgres.py`: 3 passed
- **CI collection test:** 22 passed (including the new pin).
- **Full unit suite:** 6 failed (all 6 baseline causes) / 7149 passed / 110 skipped. The 6 failures are the same baseline causes as Task 6:
  - `test_deploy_autoscaling.py` ×2: `'provisioned' == 'autoscaling'`
  - `test_style_exclusivity_chokepoint.py` ×3: `_FakeSession.execute`
  - `test_style_exclusivity_persistence_boundary.py` ×1: "no active Graph Release"
- **ruff:** clean (required three fixes: removed unused `select`, `text`, `GraphRelease`, `GraphReleaseAgent`, `UserSession` imports; removed unused `_node` import; split the inline long line; moved `from pathlib import Path` before third-party imports in `test_ci_collects_integration_tests.py`).

## Mutation table

Each mutation was applied to `src/services/graph_configuration_rollback.py`, tested, then restored with `git checkout HEAD -- src/services/graph_configuration_rollback.py`.  Marker `MUT270_9` was present count=1 while applied and 0 after restore.

| # | Mutation | Seam | First RED assertion |
|---|---|---|---|
| M01 (REVIEWER) | `_draft_effect`: remove the `elif restored_hashes[key] == node.published.content_hash: effect[key] = "unchanged"` branch; all clean roles get `"reset"` | `_draft_effect`, lines 541–542 | Step 6 `preview["draft_effect"] == expected_effect` — `builder`, `data_analyst`, `build_reviewer`, `fix_reviewer`, `deck_reviewer` all show `"reset"` instead of `"unchanged"` |
| M02 (CONTROLLER) | `preview_rollback` and `restore_release`: pass `source_release_id=release_row.id` (the active release, id=8) to `_historical_evidence` instead of `source.ref.release_id` (id=4) | `preview_rollback` line 285 and `restore_release` line 368 | Step 6 evidence assertion — preview shows v7's architect run (`run_id=7`) instead of v3's architect run (`run_id=2`) and builder run (`run_id=3`) |

### Mutation details

**M01 (REVIEWER — reset-all):** Under reset-all, every clean role gets `"reset"` regardless of whether the restored hash equals the active hash. The test immediately fails at step 6's `draft_effect` assertion: builder (whose restored hash == active hash) shows `"reset"` instead of `"unchanged"`. Per Correction 5, builder is the primary RED indicator (the original plan had builder as `"reset"`, C5 corrected it to `"unchanged"`). Fixer is unaffected by this mutation (it has a pending edit → `"kept"` in both cases). Step 11's builder-clean assertion would also trigger if step 6 were somehow patched around, since `_assign_locked_candidate` would then be called for builder too (though it sets builder to v3's content = v8's content, so builder would still appear clean — the RED is at the draft_effect assertion itself).

**M02 (CONTROLLER — wrong source_release_id):** Under this mutation, both `preview_rollback` and `restore_release` look up evidence links from the active release (v7, id=8) instead of the historical source (v3, id=4). The preview returns v7's only linked run (architect's most recent approval run at v7, run_id=7) instead of v3's two linked runs (architect's run_id=2, builder's run_id=3). The test fails at the step 6 evidence assertion with `[('architect', 7, 1)] != [('architect', 2, 1), ('builder', 3, 3)]`. This also confirms the controller's `source_release_id` path is the production seam, matching the plan's C16 sabotage rule.

## No defect found

The production code (`graph_configuration_rollback.py`) behaved exactly as specified. All 12 acceptance steps passed GREEN with no changes to production code, confirming:
- v3's architect and builder runs are correctly linked as `historical_restore` with `source_release_id = v3.id`
- The draft_effect correctly computes `builder: "unchanged"` (C5 verified)
- The stale 409 names v8 on the second rollback POST
- The history listing correctly shows v8 with `restored_from = v3` and v3 with `restored_by = [v8]`
- Conversation c7 remains pinned to v7 after rollback
- The workbench shows fixer as changed and blocking readiness after rollback
- POST /releases names only fixer's case in the publication_not_ready 409

## Deviations

1. **`_node` import dropped.** The `_node` helper was imported from the Task 8 acceptance test but is not used in the Task 9 flow (nodes are accessed by `for n in post_rb_wb["nodes"]`). Ruff flagged it unused and it was removed.
2. **Prompt text comparison via history detail.** Instead of computing cumulative expected prompt strings (initial + "\n\n+2" + ...), the comparison assertions read the actual v3 and v7 texts from `GET /releases/3` and `GET /releases/7`. This is more robust against v1 bootstrap seed changes.
3. **Module-level constants `_V3_ID = 4`, `_V7_ID = 8`, `_V8_ID = 9` and `_V1_TO_V7_PAIRS`.** These make the burned-id invariant explicit and give every assertion a name.

## Concerns

None. The test runs in 2 seconds on PostgreSQL, all mutations are in a single production file, and the restore is clean.
