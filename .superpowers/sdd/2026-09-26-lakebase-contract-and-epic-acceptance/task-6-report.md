# Task 6 report: staged lifecycle journey over real PostgreSQL and admin HTTP (AC7, AC1 tripwire)

**Status:** DONE. No production defect was found. `src/` is unchanged.

## Commits
- TASK_BASE was `002d4c4ab`. HEAD moved to `9f5516b2a` during the task: the Task 3 review docs commit, made by another session in this worktree.
- `bdb49bdc3` `test: staged edit-to-rollback lifecycle acceptance over admin HTTP (#271)`. It touches these files:
  - `tests/integration/graph_lifecycle_journey.py` (new helper, not collected);
  - `tests/integration/test_graph_lifecycle_acceptance_postgres.py` (new);
  - `tests/unit/test_graph_lifecycle_stage_attribution.py` (new, 13 tests);
  - `tests/unit/test_ci_collects_integration_tests.py` (a new pin, `test_graph_lifecycle_acceptance_is_collected_by_integration_graph`);
  - `.github/workflows/test.yml` (the file is appended to `integration-graph` after `test_claim_exclusivity_postgres.py`, per C39).
- This report is committed separately and force-added.

## TDD
- **RED.** Both new test files failed at collection with `ModuleNotFoundError: No module named 'tests.integration.graph_lifecycle_journey'`.
  - The unit file was written and run RED before the helper existed.
  - The RED for the PostgreSQL file was re-shown with the helper moved aside, then restored. The helper and the PG file were written in the same step, which is a minor deviation.
- **GREEN.** Integrated code gave no stage failure, so nothing needed C22 controller triage. Two harness corrections were made while building:
  - S14 used `revision_id`; the real key on `ReleaseDefinitionResponse` is `agent_definition_revision_id`.
  - Run ids are now offset (see Deviations).

## Gates
The env for every run was `PYTHONPATH=tree:tree/packages/databricks-tellr`, `DATABASE_URL=sqlite:////tmp/t271-6.sqlite`, `TELLR_TEST_POSTGRES_URL=…/postgres`. Each file ran in its own invocation with `-rs`, and there were zero skips.

| Gate | Result |
|---|---|
| `tests/unit/test_graph_lifecycle_stage_attribution.py` | 13 passed |
| `tests/unit/test_ci_collects_integration_tests.py` | 23 passed |
| `test_graph_lifecycle_acceptance_postgres.py` | 1 passed (about 3 s) |
| `test_graph_release_publication_acceptance_postgres.py` (#269) | 3 passed |
| `test_graph_release_rollback_acceptance_postgres.py` (#270) | 1 passed |
| `test_graph_release_publication_postgres.py` | 21 passed |
| `test_graph_release_rollback_postgres.py` | 12 passed |
| Full unit suite (`-n 4`, `DATABASE_URL` unset) | 2 failed / 7217 passed / 110 skipped. The 2 failures are exactly the `test_deploy_autoscaling` pair (the baseline). |
| ruff check (4 files) | clean; the 3 new files are `ruff format`-clean |

- `.venv` was absent before and after.
- The `tellr_int_*` set is unchanged: the same 5 databases before and after.
- `ai_slide_generator` was never touched.

## The journey (what each stage asserts, exactly)
- **Principals.** `ADMIN = lifecycle-admin@example.com`, `OWNER = lifecycle-owner@example.com` and `CONTRIBUTOR = contributor@example.com` (non-admin, with a deck-level `CAN_VIEW` grant).
- **Ids diverge from versions.** The release ids are v1 = id 1, id 2 burned with `nextval` before the publish, v2 = id 3, v3 = id 4. Run ids start at 101 (via `setval`), so they are clear of case ids 1/3/5 and revision ids 1–10.

| Stage | Assertions |
|---|---|
| S01 | Exact (id, version) (1,1). Seven model nodes in `GRAPH_V1_AGENT_KEYS` order, with Foreman last as the exact tuple `(foreman, Foreman, False, False, None, None)`, 8 nodes in total. Draft base (1,1), L0 = 0, every draft hash equals the published hash, and the DB mappings equal the published revision ids. |
| S02 | `old-root` (graph_capable) returns an exact key set with `(graph_version, active, older) == (1, 1, False)`, has no forbidden key, and has a DB pin of 1. A C37 control session sent with the default body has pin null and `graph_version` None. old-root is then seeded (C2) with an agent-mode marker message and a deck, both through `SessionManager`. |
| S03 | Architect PUT (suffix plus temperature 0.4) gives L1. Builder PUT gives L2. The stale fixer PUT returns 409 `stale_draft` with (expected 0, current 2), the server lists all seven roles in order, and the fixer draft row is byte-equal before and after. The workbench `changed` map is exact. |
| S04 | The schema-contract upgrade returns `(2, 65f29cb9…6aad)`. The overlay PUT persists `{field_overrides:{}, additional_optional_fields:["diagnostic_notes"]}` in the response and in the DB row, and the candidate hash changed from S03. |
| S05 | The protected-assembly upgrade returns `(2, fb651a0d…592a)`. The C34 probe result is asserted exactly. The custom block PUT is persisted as the exact `custom_blocks` list in the response and in the DB. |
| S06 | Discovery lists exactly `[opus-4-6, sonnet-4-5]`. The fixer endpoint change is stored in the DB. |
| S07 | See the details below this table. |
| S08 | Reject builder, approve architect, approve fixer. Each verdict response exactly matches `(run_id, verdict, reviewer=ADMIN, notes)`. Then the builder is rerun, and the runs list is exactly `[(rerun, None), (first, rejected)]`. |
| S09 | Readiness before and after the rerun approval gives exact per-changed-role `(case, status, run_id, verdict)` rows, plus `all_ready` / `blocking_agents`, `draft_lock_version` equal to the current lock, and `base_release_id` of v1. The rerun approval POST is recorded under S09 (see Deviations). |
| S10 | See the details below this table. |
| S11 | See the details below this table. |
| S12 | new-root returns (2,2,False) with pin 3. Contributor: the contribute call (as CONTRIBUTOR) returns an exact tuple including `my_permission == "CAN_VIEW"`, and the pin is 3. Duplicate (as CONTRIBUTOR, carrying the marker) returns 201 with pin 3. `GET old-root` and `GET mid-root` return (1,2,True). The contributor view returns (2,False). The full pin map is exact. |
| S12b | See the details below this table. |
| S14 | See the details below this table. |
| S15 | See the details below this table. |
| S16 | `post-rollback-root` returns (3,3,False) with pin 4. `GET new-root` returns (2,3,True). old-root returns (1,True). The full pin map is exact. |
| S18 | DB (id, version, active) is `[(1,1,F),(3,2,F),(4,3,T)]`. `v1.to == v2.from` and `v2.to == v3.from`. `tripwire.reads == []`. |

**S07 in detail.**
- For each changed role, the stage does `GET /test-cases?agent_key=`, then the run returns 201.
- Each run matches exactly: `(candidate, completed, checks_passed, verdict None, candidate_is_current True)`. The candidate hash equals the draft's, and the compared release and revision are v1's.
- The adapter was called exactly for `[architect, builder, fixer]`.
- The architect prompt equals `assembled_prompt`, which contains both the custom block and the suffix. Architect temperature is 0.4 and the fixer endpoint is sonnet.
- C33/C48:
  - the Recording sink's `.calls` are unchanged;
  - there are zero `persisted_agent_invocation` records;
  - there are exactly three `agent_candidate_run` records with extra keys `{agent_key, status, error_code, error_class}` and status `completed`;
  - the lock is unmoved.

**S10 in detail.**
- Changed roles are exactly `[architect, builder, fixer]`, `next_version_number` is 2, `publishable` is true and there are no issues.
- The C34 exact field lists are in `_DIFF_FIELDS` order:
  - architect: `[prompt_text, model.temperature, assembly_rules, protected_assembly.version, protected_assembly.digest]`;
  - builder: `[prompt_text, schema_overlay, schema_contract.version, schema_contract.digest]`;
  - fixer: `[model.endpoint_name]`.
- Published revision ids and hashes equal v1's, and the architect `prompt_text` diff matches exactly.

**S11 in detail.**
- mid-root pins 1 before the publish.
- The stale lock returns 409 `stale_publication` with (L−1, L) and `active_release` naming v1.
- The successful publish returns 200 with release `(3, 2, prev 1, restored None, ADMIN, open)`.
- `changed_agents` equals the three roles.
- The four unchanged roles are `reused: true` and equal to v1's revision ids. The three changed roles are new revisions whose hashes equal the preview candidate hashes.
- The evidence set is exact: `{architect run, builder RERUN, fixer run}`, each an `approval` with `source_release_id` None.
- Mappings in the DB equal the response. Releases in the DB are `[(1,1,F),(3,2,T)]`. The pin map is exact, and nothing in the workbench shows as changed.

**S12b in detail (C9).**
- The v1 owner and the v2 contributor each call `save_slide_deck` on old-root's one deck.
- `GET collaboration-history` then gives exact key sets (C49). `mixed_release_warning` is true and `has_legacy_evidence` is false.
- The groups are `[(v2, 2), (v1, 4)]`: the S02 seed's two events plus two now. There are two distinct actor labels.

**S14 in detail.**
- History matches exactly: `[(3,2,active,prev v1,…), (1,1,…)]`, `changed_agents`, and `v1.effective_to == v2.effective_from`.
- `GET /releases/1`: seven definitions in order, revision ids and hashes equal v1's, and evidence `[]`.
- `GET /releases/2`: the evidence is the exact three approvals with `source: None` (C35), and there is no `source_release_id` key.
- The comparison matches exactly per role: `same_revision` is false only for the three changed roles, and the active and historical revision ids are exact.
- `GET /releases/99` returns 404 `{"detail":"Graph Version not found"}` (C35).

**S15 in detail.**
- Preview: `(source v1, active v2, next 3, restorable, blocked None)`, with issues, warnings and evidence all empty. `draft_effect` is `reset` for the three changed roles and `unchanged` for the rest, and the lock is the current lock.
- The stale rollback returns 409 `stale_rollback` naming v2.
- The successful rollback returns 200 with release `(4, 3, prev 3, restored_from 1)`. All seven mappings are `(reused True, v1 revision id)`. Evidence is `[]` (C19), and `draft_effect` equals the preview's.
- The rollback log (C35/C49) is exactly `[{outcome: stale, agent_keys: []}, {outcome: restored, agent_keys: [architect, builder, fixer]}]`, as extras.
- After the rollback, the workbench base is id 4 and nothing shows as changed.

**Recording.** The journey records 72 exchanges, each with a unique `"<stage>-<label>"` id, including the C1 UI reads:
- `GET /test-cases/{id}/runs` after every run;
- `GET /readiness` after every save, upgrade, run and verdict.

## Mutation table (all RED with the predicted label)
- Every `src/` mutation was restored with `git checkout 002d4c4ab -- <file>`, then `git diff --quiet 002d4c4ab -- <file>` was asserted.
- `git diff --stat 002d4c4ab HEAD -- src` is empty.
- The runner script is `/tmp/t271-6-mut/run.py`.

| # | Seam mutated | First RED line |
|---|---|---|
| M1 | **Plan REVIEWER sabotage**: `restore_release` passes `restored_from_release_id=None` (`graph_configuration_rollback.py:383`) | `[#270] S15 rollback via POST …/releases/{version_number}/rollback: AssertionError: {'release_id': 4, 'version_number': 3, 'previous_release_id': 3, 'restored_from_release_id': None, …` |
| M2 | Swallowed, function-level `load_graph_v1_manifest()` call in `AgentRuntime` candidate path | `[AC1/#271] S07 test via POST …/draft/{agent_key}/test-runs: code-owned definition read after Graph Version 1: src.services.graph_definition_manifest.load_graph_v1_manifest, …` |
| M2b | Module-level by-name `from …graph_definition_manifest import load_graph_v1_manifest` in `agent_runtime.py`, called in the candidate path (proves the `sys.modules` trap) | `[AC1/#271] S07 test …: … read after Graph Version 1: src.services.agent_definition_manifest_v1` |
| M9 | Module-level by-name `from src.core.skills import load_skill` in `agent_runtime.py`, called in the candidate path (proves the C6 `_SKILLS` trap) | `[AC1/#271] S07 test …: … read after Graph Version 1: src.core.skills._SKILLS` |
| M3 | Candidate run uses `self._identity_sink` instead of `_PASS_THROUGH_IDENTITY_SINK` (C48) | `[#267] S07 test …: AssertionError: a candidate run reached the identity sink` |
| M4 | `create_session` ignores `graph_capable` | `[#261] S02 old conversation via POST /api/sessions: AssertionError: {… 'graph_version': None …}` |
| M5 | Contributor inherits the parent's pin (root inference) | `[#262] S12 pinned conversations via POST /api/sessions/{session_id}/contribute: AssertionError` |
| M6 | `mixed_release_warning` threshold changed from `>= 2` to `>= 3` | `[#262] S12b collaboration history via GET …/collaboration-history: AssertionError` |
| M7 | Rollback comparison `same_revision=True` | `[#270] S14 history via GET /api/admin/agent-definitions/releases: AssertionError: [{'agent_key': 'architect', … 'same_revision': True …` |
| M8 | `_log_rollback` adds an extra key | `[#270] S15 rollback …: AssertionError: [{'outcome': 'stale', 'agent_keys': [], 'actor': 'x'}, …]` |
| M11 | Draft save skips its lock check (`graph_configuration_draft.py:445`) | `[#263] S03 edit prompts and model via PUT …/draft/{agent_key}: AssertionError: PUT …/draft/fixer …` |
| M12 | Verdict writer stores a different reviewer | `[#268] S08 approve via POST …/test-runs/{run_id}/verdict: AssertionError: {'run_id': 102, …` |
| M13 | Publication `reused=False` for every mapping | `[#269] S11 publish via POST …/releases: AssertionError: ('data_analyst', {'agent_definition_revision_id': 2, …` |
| CI | Remove the workflow line | the new pin plus `test_every_integration_file_is_collected_or_excluded_with_reason`: RED 2/23; restored |
| H1 | Harness: drop the C50 `src.core.database.get_db_session` patch | **stayed GREEN**. It is not load-bearing for the current stages (see Concerns). |

- **Not run:** the plan's CONTROLLER sabotage (drop `prompt_text` from `_DIFF_FIELDS`), because it is the controller's. Predicted RED: `[#269] S10 preview`.
- **Not used:** C6's Task 12 controller sabotage, a function-level `load_skill` call in `_load_complete_release`. It is left unspent for Task 12. M2, M2b and M9 are different anchors.

## Defects found
None in production code.

## C34 probe result
`POST /draft/architect/protected-assembly-upgrade` rewrites these draft columns: `assembly_rules` (v1 format → `{format_version: 2, custom_blocks: []}`), `candidate_hash`, `protected_assembly_version` and `protected_assembly_digest`. It does **not** rewrite `prompt_text`. This is asserted exactly in S05. So S10's architect `assembly_rules` diff would be present even without the custom block.

## Harness API consumed by Tasks 7 and 8
Everything is in `tests/integration/graph_lifecycle_journey.py`.

**Fixtures.** A consumer module must import both names so pytest sees them:

```python
from tests.integration.graph_lifecycle_journey import acceptance_stack, lifecycle_journey  # noqa: F401
```

- `acceptance_stack` is #270's fixture, re-exported unchanged.
- `lifecycle_journey` yields a fresh `LifecycleJourney` with the tripwire already armed.
- `open_journey(factory, client, adapter, monkeypatch, stack)` builds the same journey outside the fixture.

**Stages and attribution.**
- `STAGES: dict[str, Stage]`, in order: `S01 … S12, S12b, S14, S15, S16, S18`. Task 7 adds S13 and S17 in its own file.
- `Stage(code, name, ticket, seam)`.
- `StageFailure`.
- `stage(current)`: StageFailure passes through; a tripwire read wins over any failure and is also caught when swallowed.
- `require(upstream, condition, detail)`.

**Tripwire.**
- `CodeDefaultTripwire` has `reads` and `arm(monkeypatch)`. `CodeDefaultRead` is the error it raises.
- It traps:
  - `src.core.skills.load_skill` and `src.core.skills._SKILLS` (C6);
  - `graph_definition_manifest.load_graph_v1_manifest`, after `cache_clear`;
  - the `src.services.agent_definition_manifest_v1` module, in `sys.modules` and as the package attribute;
  - `CodeOwnedAgentDefinitionSource.resolve` and `CompatibilityResolvedDefinitionLoader.resolve`. These two are listed in `CodeDefaultTripwire.UNTIL_TASK_12`, so Task 12 removes them there.

**`LifecycleJourney`.**
- Fields: `factory`, `admin`, `user`, `adapter`, `tripwire`, `exchanges: list[RecordedExchange]`, `state: dict`, `workbench`, `completed: list[str]`.
- `admin` and `user` are the same `TestClient`, because the principal is set per request (C2).
- Methods:
  - `run_to(code)` is resumable: it runs only the stages not yet run.
  - `call(label, method, path, *, principal, expect, json=None)` records the exchange and asserts the status. Use it inside a `stage()` with `journey._current` set; `run_to` does this.
  - `admin_call`, `read_workbench`, `read_readiness`, `read_runs`, `pins()`, `pin_of()`, `draft_row()` and `releases()`.

**`RecordedExchange`.** Fields are `(id, method, path, request, status, body)`. The id is `"<stage code>-<label>"`.

**`state` keys after `run_to("S12")`, for Task 8:**
- `v1_id` = 1 and `v2_id` = 3;
- `v1_mappings`, `v2_mappings`, `v1_hashes` and `published`;
- `lock`, `lock0`;
- `cases` and `runs` (both per role), `builder_rerun` and `preview_hashes`;
- `contributor_id` and `duplicate_id`.

Conversations present at that point:

| Session | Pin |
|---|---|
| `old-root` | v1 (has a deck and the agent-mode marker) |
| `control-legacy` | null (default body) |
| `mid-root` | v1 |
| `new-root` | v2 |
| contributor | v2 |
| duplicate | v2 |

`v3_id` = 4 is added after S15.

**Constants:** `ADMIN`, `OWNER`, `CONTRIBUTOR`, `CHANGED_ROLES`, `UNCHANGED_ROLES`, `OPUS`, `SONNET` and the two digest literals.

## Deviations
1. **Identity sink.** The brief wanted `LoggingAgentInvocationIdentitySink`. Per C37/C50, the journey extends `acceptance_stack`, whose runtime has the Recording sink. C48's extra assertion is used instead: the Recording sink's `.calls` are unchanged, with M3 proving it live. The zero-`persisted_agent_invocation` check is kept as well.
2. **One client.** `admin` and `user` are the same `TestClient`, because the sessions router is added to the same app (C50) and the principal is set per request (C2.3).
3. **The v2 mutation on the shared deck (S12b).** C9 named `new-root` for this mutation. It is made by the v2-pinned **contributor** instead, because new-root is a separate root and cannot mutate old-root's deck. Both mutations go through `SessionManager.save_slide_deck`, as C9 permits.
4. **Rerun approval.** The approval POST for the builder rerun is recorded as `S09-approve-builder-rerun`, not as an S08 exchange. S09 needs readiness both before and after that approval. Both stages are #268, so attribution is unaffected.
5. **Id burning.** The release id is burned with `nextval(pg_get_serial_sequence('graph_release','id'))`, not #270's commit-failure trigger. Run ids are offset with `setval(…, 100)`, so no run id coincides with a case id. Without the offset, architect's run id and case id were both 1.
6. **No underscore imports from the workbench file.** Nothing is imported from `test_agent_definition_workbench_postgres.py`. `_mapping_rows`, `_pin_of` and `_release_ids` come from #269's acceptance file, as #270 already does.

## Concerns
- **Concurrent edits in this worktree.** Another session is working here: it committed `9f5516b2a` during my run, and it has uncommitted edits in `tests/unit/test_agent_runtime.py`, `test_graph_definition_manifest.py` and `test_prompt_assembler.py` (these look like the Task 3 fix round).
  - I did not commit or touch them. My commit stages only my five paths.
  - My full-unit run (2 baseline failures) included their in-progress edits.
  - My `src/` mutations were short-lived and restored from the base SHA. A unit run by that session during a mutation window would have seen them.
- **C50 patch not load-bearing (H1).** The `src.core.database.get_db_session` patch changes nothing today. `GET /api/sessions/old-root` runs `_substitute_deck_images` against the conftest SQLite without error, because the deck has no image placeholders. It is kept for Tasks 7 and 8 and for any stage that hits `/slides`.
- **Random session ids in exchange paths.** The contributor and duplicate session ids are random tokens (`secrets.token_urlsafe`), and they appear in exchange paths, e.g. `S12-get-contributor`. Task 10's contract should join on the exchange id rather than the literal path.
- **Long failure messages.** Some assertion messages print whole response bodies (M7's is very long). The label is always on the first line.
