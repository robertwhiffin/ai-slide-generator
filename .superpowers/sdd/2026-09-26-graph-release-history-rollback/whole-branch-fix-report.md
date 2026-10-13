# #270 whole-branch fix wave: report

- **Branch:** `plan/release-history-rollback-270`. BASE `0074656cc`. Work HEAD `8fd1e046c`; this report is committed on top of it.
- **Status:** DONE. All 11 items are addressed. The parked items (5-Minor-3, N3, O1 label copy) were not touched.

## Commits (oldest first)

| SHA | Subject |
|---|---|
| `e37f5ff0f` | fix: share one candidate validation loop and widen the candidate_hash writer pin (#270). Covers items 1, 2 and 9. |
| `ee07eb5aa` | test: pin that restore_release writes through the one publication core (#270 N1) |
| `5c228cc00` | fix: log one ERROR record for an unhandled rollback failure and re-raise it (#270 6-m1) |
| `ac152bdbb` | test: pin literal release ids and the flushed-rollback scan counts (#270 Task 5 Minors 1-2) |
| `a6d396ae6` | test: assert R2's full link list in the rollback-vs-cleanup race (#270 Task 5 Minor 4) |
| `774895017` | test: assert changed for all seven roles after the acceptance rollback (#270 9-M01) |
| `8fd1e046c` | test: compute history fixture dates with Date.UTC and drop the v12 override (#270 Task 8, N2) |

## Per-item table

| # | Item | Status | What was done |
|---|---|---|---|
| 1 | 3a-m1: the AST writer pin overclaims | Addressed | Renamed to `test_candidate_hash_writers_are_the_allowlisted_attribute_and_builder_sites`. The scan now detects five write forms: attribute assignment anywhere, `GraphDraftAgent(candidate_hash=…)`, Core `.values(candidate_hash=…)`, a `.values({"candidate_hash": …})` mapping, and `setattr(…, "candidate_hash", …)`. It asserts the exact allowlist `[content.py:draft_from_definition:constructor, draft.py:_assign_locked_candidate:attribute]`. A new parametrized test `test_candidate_hash_writer_scan_detects_each_write_form` proves each form on a tmp file. The constructor check is scoped to `GraphDraftAgent(`, because `candidate_hash=` is a legitimate keyword on `AgentTestRun`, on schemas and on dataclasses. |
| 2 | 3a-m2: no restore-level endpoint refusal | Addressed | Added `test_restore_refuses_an_endpoint_url_before_any_write`. It uses Task 2's URL-shaped endpoint on v2's architect and expects `RollbackIncompatible(source=r[2], issues=(endpoint_url_not_allowed,))`. `rollback_artifacts` is byte-identical before and after. |
| 3 | Task 5 Minor 1: literal ids | Addressed | `_seed_v4` asserts the (id, version) pairs `[(1,1),(3,2),(4,3),(5,4)]` and `(v2_id, v4_id) == (3, 5)`. v5's id is asserted to be 6 in the rollback-first test and in the flushed-commit branch. |
| 4 | Task 5 Minor 2: `race.scans` in the flushed-rollback test | Addressed | The rollback branch asserts `[1]`: the aborted rollback never closed v4. The commit branch asserts `[1, 1]`: the first scan hits the closed v4 and the rescan locks v5. The test also asserts `len(race.rollback_statements) == 1`. Verified on PostgreSQL, 57/57. |
| 5 | Task 5 Minor 4: R2's full link list | Addressed | Both orders now assert R2's links `[(v2, R2, approval, None), (v5, R2, historical_restore, v2)]` and the whole link table (4 rows). This replaces the `_links(factory)[-1]` check. |
| 6 | 6-m1: no log record on an unhandled failure | Addressed | The service call and the outcome mapping moved into `_restore_graph_release`. The handler re-raises `HTTPException` untouched. On any other `Exception` it emits one `graph_release_rollback` ERROR record, `{"outcome": "error", "agent_keys": [], "error_class": <name>}`, with no `exc_info`, then does a bare `raise`. `IntegrityError` is never translated. The path-int 422 is unchanged. New test: `test_an_unhandled_rollback_failure_logs_one_error_record_and_re_raises_unchanged[integrity_error\|unknown_outcome]`. It checks that the same exception object propagates, that there is exactly one record on the routes logger, and that "SECRET" does not leak. |
| 7 | Task 8 fixture: invalid dates | Addressed | `mocks.ts` now has `historyInstant(offset) = Date.UTC(2026, 8, 20 + offset, 12)` as an ISO string with the `.000` stripped. The v1–v9 strings are byte-identical, so no existing assertion needed an update. v10's `effective_to` is now `2026-10-01T12:00:00Z`. `historyV12`'s January override is gone. New Vitest block in `releaseClient.test.ts`: v1, v9, v10, v11, v12, v20 and v45 all round-trip as valid instants; the exact v4, v9, v10 and v12 strings are pinned; and a v1–v12 history parses. |
| 8 | 9-M01: `changed` checked for only 3 roles | Addressed | Step 11 asserts the full seven-key mapping in Graph order. Only `fixer` is True. |
| 9 | 2-m-2: duplicated validation loop | Addressed | Added `_GraphConfigurationPublication._candidate_contents_issues(contents)`, the one loop in the mapping's order. It keeps the same local-then-post-stale `try` and the same `definitions.<key>.<field>` prefix. `_changed_candidate_issues` passes `{key: draft.content for key in changed}`. `_structural_issues` passes `{key: contents[key] for key in GRAPH_V1_AGENT_KEYS}` and returns a tuple. New test: `test_rollback_and_publication_share_one_candidate_validation_loop`. #269's publication, preview, routes, evidence and client-join suites all pass: 298 passed. |
| 10 | N1: nothing pins that restore writes through the core | Addressed | Added `test_restore_writes_through_the_one_publication_core`. It first asserts `GraphConfiguration._commit_locked_publication is _GraphConfigurationPublication._commit_locked_publication`, which catches an override copy. It then spies the core and requires exactly 1 call with `restored_from_release_id == r[3].release_id`, and checks that this id is not the version number. |
| 11 | N2: ESLint unused variable | Addressed | Deleted `rollbackPreviewCallCount`. ESLint is clean on the 3 files changed in this wave and on all 14 TS/TSX files the branch changes. |

## Gates

- **Full unit suite** (from inside the tree, `DATABASE_URL=sqlite:////tmp/t270-wbf.sqlite`): **6 failed / 7159 passed / 110 skipped** in 7:20. The 6 failures are the baseline nodes with the baseline causes:
  - `test_deploy_autoscaling` ×2: `'provisioned' == 'autoscaling'`, and the provisioned mock was not called;
  - `test_style_exclusivity_chokepoint` ×3: `'_FakeSession' object has no attribute 'execute'`;
  - `test_style_exclusivity_persistence_boundary` ×1: `no active Graph Release`.

  The passed count is 7149 + 10 new tests.
- **PostgreSQL** (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres`, one file per invocation, `-rs`, **0 skips**, all exit 0):

  | File | Passed |
  |---|---|
  | rollback | 12 |
  | history | 5 |
  | publication | 21 |
  | evidence | 18 |
  | session-ordering | 57 |
  | rollback-ordering | 12 |
  | rollback acceptance | 1 |
  | publication acceptance | 3 |

  The `tellr_int_*` list was identical before and after: the 5 older databases only. Nothing was dropped and nothing leaked. `ai_slide_generator` was not touched.
- **Frontend:**
  - Vitest: **21 files / 1099 passed** (1090 + 9 new).
  - `npm run typecheck`: clean.
  - ESLint: clean on the 3 files this wave changed and on the branch's 14 changed TS/TSX files.
- **Playwright:** `graph-release-history` plus `graph-release-review` gave **18 passed**. The server was Playwright-managed, and port 3000 was free before and after.
- **ruff:** clean on every changed `.py` file. `ruff check src` reports 1143 errors repo-wide, which are pre-existing and not in the changed files.

## Mutations

Each mutation carried a `WBF_*` marker. Each was restored with `git checkout <HEAD SHA> -- src|tests|frontend`, and afterwards the marker count was 0 and `git diff --quiet` was clean.

| ID | Item | Mutation | Result |
|---|---|---|---|
| M1a–e | 1 | Appended `_wbf_m1_rogue` to `graph_configuration_publication.py` five times, with each write form in turn: attribute, `GraphDraftAgent(candidate_hash=)`, `.values(candidate_hash=)`, `.values({"candidate_hash": …})`, and `setattr(row, "candidate_hash", h)` | RED 5/5. The allowlist test names `…:_wbf_m1_rogue:<kind>` each time. |
| M2 | 2 | In `restore_release`, filtered `endpoint_url_not_allowed` out of the issues before the `RollbackIncompatible` raise | RED 1/65: only the new test |
| M9a | 9 | Put the duplicate loop back into rollback's `_structural_issues` | RED 1/65: the share test |
| M9b | 9 | Put the duplicate loop back into publication's `_changed_candidate_issues` | RED 1/65: the share test |
| N1a | 10 | Routed around the core: `restore_release` calls a module-level `types.FunctionType` copy of `_commit_locked_publication`, captured at import | RED 1/65: `len(calls) == 0`. This is S2's shape, which previously passed 249/250. |
| N1b | 10 | Installed a function copy as an override `_GraphConfigurationRollback._commit_locked_publication` | RED 1/65: the `is core` identity assertion |
| M6a | 6 | Changed the new record from `logger.error` to `logger.debug` | RED 2/71 (both params) |
| M6b | 6 | Translated to `HTTPException(500)` instead of re-raising | RED 2/71 |
| M6c | 6 | Added `exc_info=True` to the record | RED 2/71 |
| M6d | 6 | Dropped `except HTTPException: raise` (catching `BaseException`) | RED 4/71: the existing 404 tests and the integrity-500 "one record" test go RED on the double log |
| M3a | 3 | Test seed: did not burn id 2 | PostgreSQL RED 21/21 selected: `[(1,1),(2,2),(3,3),(4,4)] != …` |
| M3b | 3 | Test seed: an extra `nextval` on the `graph_release` id sequence after the seed | PostgreSQL RED 14: 7 rollback-first and 7 flushed-commit, each `7 == 6`. The flushed-rollback branch correctly stays green. |
| M4a | 4 | `lock_active_graph_release` does an extra unconditional pre-scan | PostgreSQL RED 7/14 flushed tests (rollback branch, `[1, 1] == [1]`) |
| M4b | 4 | An extra scan when the first scan finds no active row | PostgreSQL RED 7/14 flushed tests (commit branch, `[1, 1, 1] == [1, 1]`) |
| M5 | 5 | In `link_release_evidence`, a restore link deletes the run's existing approval link, so the restore "moves" it | PostgreSQL RED 2/2 cleanup-race tests, at the new R2 assertion (:694). The old `[-1]` check would have passed. |
| M8 | 8 | `GET /workbench` reports `deck_reviewer.changed = True` | PostgreSQL acceptance RED: `{'deck_reviewer': True} != {'deck_reviewer': False}`. The old 3-role check would have passed. An earlier attempt at the service layer (`graph_configuration_workbench.py:335`) was discarded: it went RED at step 5, because publication reads `changed`, not at the new assertion. |
| M7 | 7 | Restored the old `2026-09-${20+v}` formula in `historyInstant`, with the override still dropped | Vitest RED 7 (the new block). Playwright `graph-release-history` RED 1/9 at `(g) two-digit versions`, because the strict parser rejects day 31 and later. |
| N2 | 11 | Re-added an assigned-but-unused counter to the spec | ESLint: 1 error, `@typescript-eslint/no-unused-vars` |

**RED-first:** before any production change, the new share test failed with `AttributeError: … no attribute '_candidate_contents_issues'`. The 6-m1 route tests failed 2/2 with no record. The fixture Vitest block failed 7/7, including v10, which confirms the bug starts at v=10. Items 1–5, 8 and 10 pin existing, correct behaviour; for those, each mutation above serves as the RED proof.

## Concerns

1. **6-m1 is broader than the brief's wording, by design.** The route catches every non-`HTTPException` `Exception`, not only `IntegrityError` and `AssertionError`, following the reviewer's "on any other exception" wording. That keeps the rule of one record per handled call. The only other logged path, `GraphConfigurationIntegrityError`, becomes an `HTTPException`, so M6d proves it is not double-logged.
2. **Item 1's constructor detection covers `GraphDraftAgent(` by name only.** It would not see a constructor aliased under another name, or `**{"candidate_hash": …}` splatted into the constructor. `.values(...)` is flagged for any table, which is conservative; there are no such sites today.
3. **Item 9 changes publication's evaluation order slightly.** `_changed_candidate_issues` now reads every changed role's `draft.content` before it validates any of them; before, it read and validated each role in turn. These are plain attribute reads on a snapshot, so the phases, the issue order and the prefixes are unchanged, and the #269 suites are green.
4. **Item 4 semantics.** The flushed-rollback branch is `[1]`, not `[1, 1]`. The aborted rollback leaves v4 active, so the creator's first scan succeeds. This is the same as #269's twin.
