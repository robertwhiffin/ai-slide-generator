# SDD ledger — plan: docs/superpowers/plans/2026-09-26-lakebase-contract-and-epic-acceptance.md

This plan was drafted on 2026-09-26 by a planning agent on `plan/lakebase-contract-acceptance-271`, at base `a08389ec3` (Merge #267). It has Tasks 0–14.

- **Not yet plan-reviewed.** It is executable beyond Phase A (Task 0 phase A, Tasks 1 and 5) only after reviewed #268, #269 and #270 are merged locally and Task 0 phase B has run.
- **Phase A** is Task 0 phase A plus Tasks 1 and 5. These touch no file that #268, #269 or #270 own.
- **Phase B** is Tasks 2–4 and 6–14.
- **AC10 ordering:** Task 12 (the deletion) refuses to start until the Tasks 6–11 suites are green at its base SHA.

## Probes recorded while planning (read-only)

- **P1.** A typecheck of `frontend/tests/**` with a throwaway tsconfig (in `/tmp/probe271-ts`, using the main worktree's node_modules through a symlink) gives 12 errors:
  - 9 × TS2307 on `'/src/…'` browser imports;
  - 2 × TS2339 on `ImportMeta.env`;
  - 1 × TS2740 at `findings-drawer.spec.ts:87`.
- **P2.** Six unit failures at `a08389ec3`:
  - The deploy_autoscaling ×2 also fail on `main` `f6b1506c5`, so they are not caused by the epic.
  - The style_exclusivity ×4 pass on `main`, so they are caused by the epic: `create_session` requires an active Graph Release.

## Rulings made in the plan (for plan review)

- **In scope:**
  - the `frontend/tests` typecheck (Task 4);
  - log needles matching `pathname` (Task 2);
  - the dev-DB default in conftest (Task 1);
  - the style_exclusivity ×4 (Task 1);
  - declaring `openai` (Task 5).
- **Out of scope** (for the user to file as GitHub issues):
  - deploy_autoscaling ×2, which fails on `main`;
  - #266 m7, `tools/model_endpoint_tool.py:75`, which is the legacy tool path.
- **Conditional release gate:** #266 m9, pay-per-token `config_update` (Task 13). It needs the user's authorisation to read the dev workspace.

## Open questions

Q1–Q4 are listed at the end of the plan.

## Controller rulings — 2026-09-26
Controller check of the planner's "file changed on disk before commit" note: working tree clean; committed plan is 1005 lines and is the file on disk; no other agent works in this worktree. Nothing to reconcile.
Ruling: OQ1 — the conftest REFUSES to run a unit suite whose `DATABASE_URL` names `ai_slide_generator` (fail fast), and defaults to a throwaway SQLite URL when unset. Cost if wrong: a developer who deliberately points unit tests at the dev DB must override explicitly.
Ruling: OQ2 — deleting the now-unread authored prompt text in `src/core/skills` is OUT of #271's scope (a follow-up); protected constants stay. Cost if wrong: dead text remains for a while.
Ruling: OQ3 — a documented developer command to re-record the Playwright contract is acceptable (no new make target). Cost if wrong: none.
Ruling: OQ4 — the local merge of #271 may proceed with #266 m9 unverified; the epic is NOT reported shippable until the user authorises and the dev-workspace check passes. Surfaced to the user. Cost if wrong: none locally.
Ruling: the planner's follow-up split is accepted — style-exclusivity ×4 in scope (Task 1); deploy-autoscaling ×2 out (pre-epic, needs an issue); #266 m7 out (needs an issue); `openai` declared (Task 5); typecheck gap and log needles in scope.
Next: independent plan review before execution. Phase A (Tasks 0-A, 1, 5) is runnable at `a08389ec3`.

## Plan review 1 — 2026-09-26

**Verdict:** APPROVE WITH CORRECTIONS. **Counts:** 2 Critical, 9 Important, 12 Minor. Total: 23 corrections.

**Corrections file:** `.superpowers/sdd/2026-09-26-lakebase-contract-and-epic-acceptance/PLAN-CORRECTIONS.md`

**Correction numbers:**
- C1 (Correction 1): Tasks 10/11 replay design
- C2 (Correction 2): Task 6 S12 contributor/duplicate prerequisites
- I1 (Correction 3): Task 4 tsconfig verbatimModuleSyntax and tsc invocation
- I2 (Correction 4): Task 1 xdist worker isolation
- I3 (Correction 5): Task 5 openai specifier and requirements.txt
- I4 (Correction 6): AC1 tripwire (_SKILLS) and guard 2/4 widening
- I5 (Correction 7): **REAL PRODUCTION DEFECT** — `resolve_engine_mode_or` fallback at `chat.py:490-491` and `:697-698` silently routes a pinned graph conversation to the legacy monolith on any DB error; violates spec §15; must be fixed in #271
- I6 (Correction 8): Task 7 AC5 no-tools uses recording DatabricksModelAdapter
- I7 (Correction 9): Task 11 mixed-release warning requires real deck mutations in Task 6
- I8 (Correction 10): Task 3 reviewer sabotage changes one byte, not swaps the role
- I9 (Correction 11): Playwright port-3000 lane; node_modules symlink; tsc --noEmit
- M1 (Correction 12): Task 2 regex widened to `vars\(record`
- M2 (Correction 13): Task 12 Step 2 RED count is guards 1–4, not 1 and 4
- M3 (Correction 14): R7 extended; RecordingAgentInvocationIdentitySink kept as re-export
- M4 (Correction 15): Three stale citations corrected
- M5 (Correction 16): Sweep helper extracted to shared fixture; missing Files block entry
- M6 (Correction 17): Style-fixture assertions confirmed by value, not text
- M7 (Correction 18): Task 8 names existing cases; three setup details for new cases
- M8 (Correction 19): S15 evidence asserted `== []`
- M9 (Correction 20): OQ2 follow-up must keep two skills imports
- M10 (Correction 21): model_validate_json for strict models in Task 10 join
- M11 (Correction 22): Controller triage before routing any failure to predecessor
- M12 (Correction 23): Scoped re-review of Task 0-B corrections before Task 2 dispatches

**Blocking Phase A (before Task 1):**
- Correction 4 (I2): xdist worker isolation

**Blocking Phase A (before Task 5):**
- Correction 5 (I3): openai no-cap specifier

**Blocking Phase A (worktree setup):**
- Correction 11 (I9): frontend/node_modules symlink

**Blocking Phase B (before Task 2):**
- Correction 23 (M12): scoped re-review after Task 0-B

**Blocking Phase B (before Task 3):**
- Correction 10 (I8): reviewer sabotage one-byte change

**Blocking Phase B (before Task 4):**
- Correction 3 (I1): drop verbatimModuleSyntax; re-measure; tsc --noEmit

**Blocking Phase B (before Task 6):**
- Correction 1 (C1): replay design
- Correction 2 (C2): S12 prerequisites
- Correction 6 (I4): tripwire _SKILLS and guard 2/4

**Blocking Phase B (before Task 7):**
- Correction 8 (I6): DatabricksModelAdapter for AC5
- Correction 9 (I7): deck mutations and collab-history exchange

**Blocking Phase B (before Task 8):**
- Correction 7 (I5): production fallback fix (chat.py)

**Blocking Phase B (before Task 10):**
- Correction 11 (I9): lsof gate; tsc --noEmit

**Blocking Phase B (before Task 12):**
- Correction 6 (I4): (also) Task 12 sabotage re-aimed

**I5 noted as real production defect:** `resolve_engine_mode_or` at `src/api/routes/chat.py:490-491` and `:697-698` silently falls through to the legacy monolith on any DB error when the session has a pinned graph release. Found at plan review. Added to the removal inventory and to Task 8 scope in PLAN-CORRECTIONS.md.

## Task 0 phase A — 2026-09-26 (implementer, worktree `.worktrees/issue-271-plan`)

### Implementation facts
- **TASK1_BASE** = `0500629354d504315c0e4e6acf44102f8372b8d4` (written to `TASK1_BASE`). `a08389ec3` is an ancestor. `git diff --stat a08389ec3 HEAD -- src tests frontend packages` is empty.
- **Interpreter:** `/Users/robert.whiffin/.pyenv/shims/python` → 3.11.0. pytest 8.4.2, pytest-xdist 3.8.0 (installed), pytest-randomly **not** installed (`-p no:randomly` is a no-op), ruff 0.12.11. `.venv` absent before and after every gate.
- **Dev-DB source is `.env`, not only the code default.** `src/core/database.py:28` calls `load_dotenv()`, which searches upward from `src/core/` and finds the MAIN checkout's `.env` (`DATABASE_URL=postgresql://localhost:5432/ai_slide_generator`). Measured: with `DATABASE_URL` unset, `_get_database_url()` in this worktree returns `postgresql://localhost:5432/ai_slide_generator` (not the code default `postgresql://localhost/ai_slide_generator`). `load_dotenv` does not override a set variable, so a conftest that always sets `DATABASE_URL` closes both routes.
- **Correction 4's literal conftest code does not isolate xdist workers.** Workers inherit the controller's `os.environ`, so `if "DATABASE_URL" not in os.environ` is false in every worker and all workers keep the controller's `main` path. Measured by mutation M9 in `task-1-report.md` (both gw0 and gw1 report the same file). The implementation re-derives in a worker whenever `TELLR_TESTS_DATABASE_URL_DEFAULTED=1` is inherited. It also uses `mkdtemp(prefix=f"tellr-tests-{worker}-")` rather than a fixed `/tmp/tellr-tests-{worker}.sqlite`, so concurrent runs in other worktrees and stale files from earlier runs cannot collide.
- **Pre-existing, epic-caused (#267) xdist defect, OUT of Task 1 scope:** `pytest tests/unit -n 2` (and CI's `-n auto`, `test.yml:137`) errors at collection with "Different tests were collected between gw1 and gw0". The cause is `tests/unit/test_agent_definition_workbench_routes.py:4797` and `:4829`: `parametrize(..., ids=lambda v: str(v))` over lambdas and functions, which renders `<function <lambda> at 0x…>` and differs per process. Introduced by `6358cf392` (#267). Measured at TASK1_BASE, before any Task 1 change. Every `-n` run here therefore uses `--ignore=tests/unit/test_agent_definition_workbench_routes.py` plus a separate single-process run of that file. **For the controller: route to a fix (a stable `ids=` is test-only) before CI's unit job can pass.**
- **Other `DATABASE_URL` setters in tests (grep):** `test_database_autoscaling.py:81,85` and every `patch.dict(os.environ, …, clear=True)` restore on exit. `tests/integration/test_graph_live_real_model.py:149` uses `monkeypatch.setenv` (live-only). `test_layer4_multi_worker.py:597,626,774` pass an explicit URL to child processes. `test_ws4b_fixture_contracts.py:68`'s child `setdefault` now inherits the SQLite file URL; the file still passes (16 passed, measured after). No test legitimately relies on an unset `DATABASE_URL`, and the only other writer is `scripts/run_e2e_local.sh` (`e2e_test_db`, not a pytest run).

### Cause baseline (at TASK1_BASE)
- `DATABASE_URL=sqlite:////tmp/t271-0.sqlite … pytest tests/unit -q -p no:randomly -rf`: **6 failed, 6625 passed, 110 skipped** (477 s). Failures by cause, exactly as P2:
  - `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_returns_autoscaling_when_available`: `assert 'provisioned' == 'autoscaling'`
  - `test_deploy_autoscaling.py::TestGetOrCreateLakebase::test_falls_back_when_autoscaling_creation_fails`: `Expected '_get_or_create_lakebase_provisioned' to have been called once. Called 0 times.`
  - `test_style_exclusivity_chokepoint.py::TestModelDumpIsNotTheChokepoint::{test_create_session_normalizes_a_raw_both_set_dict, test_create_session_still_stores_a_single_authority_config_unchanged, test_create_session_still_accepts_no_agent_config}`: `AttributeError: '_FakeSession' object has no attribute 'execute'`
  - `test_style_exclusivity_persistence_boundary.py::TestEveryWriterIsNormalized::test_session_manager_create_session`: `ConversationGraphReleaseIntegrityError: no active Graph Release`
- Skips (110), by cause: 105 huashu PPTX-export tests needing node + `services/pptx-emit-huashu/node_modules` + Chrome; 3 `test_rc_graph_ci.py` documented non-applicable RCs (RC3, RC6, RC14); 1 `test_otel_logging.py` (no `opentelemetry.exporter`); 1 `test_converter_jail.py` (RLIMIT_AS on macOS). No PostgreSQL skip: the six unit PostgreSQL modules ran against the default `localhost:5432`.
- **Unreachable `DATABASE_URL` probe (before):** `DATABASE_URL=postgresql://t271probe@127.0.0.1:1/unreachable_probe`, `-n 4 --ignore=<routes file>` gives 6 failed / 6233 passed / 110 skipped, and the routes file alone gives 392 passed. The same 6 nodes and causes. So no unit test depends on a reachable dev database. The writes come only from best-effort request/usage logging.
- **PostgreSQL, one invocation per file** (`TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres -q -rs -m "not live"`), all 25 `integration-graph` files (`test.yml:448-472`), **zero skips each**: graph_orchestration 19, graph_mode_turn 39, graph_configuration_bootstrap_postgres 3, graph_configuration_constraints_postgres 66, conversation_pin_migration_postgres 1, shared_deck_mutation_migration_postgres 3, shared_deck_mutation_lifecycle_postgres 4, collaboration_history_api_postgres 30, mixed_release_collaboration_acceptance_postgres 26, shared_deck_mutation_attribution 60, conversation_pin_creation_postgres 2, mixed_release_creation_postgres 14, conversation_creator_exclusions_postgres 4, persisted_graph_runtime_failures_postgres 7, conversation_pin_acceptance_postgres 1, agent_definition_workbench_postgres 25, agent_schema_overlay_postgres 10, spec_dirty_marker_routes 11, sweeper_describe_only 18, architect_reply_is_persisted 9, insert_slide_route 8, slide_id_is_durable 14, deck_spec_change_turn 9, spec_row_alignment 10, claim_exclusivity_postgres 3 (+1 xfailed, the file's own documented xfail).

### Deploy baseline ruling (Step A5)
- `test_deploy_autoscaling.py::TestGetOrCreateLakebase::{test_returns_autoscaling_when_available,test_falls_back_when_autoscaling_creation_fails}` are an **accepted, not-epic** baseline (P2: they also fail on `main` `f6b1506c5`). #271 does not edit `deploy.py`.
- **For the user:** file a GitHub issue for the deploy_autoscaling ×2 failures (`packages/databricks-tellr/deploy.py`).

### Removal inventory re-count (not acted on)
- R1 `AgentRuntime.compatibility(`: **13 sites in 4 files**, all tests (test_agent_runtime ×9, test_deck_level_spec_change ×2, test_graph_configuration_bootstrap ×1, test_agent_resolution_prompt ×1). No production caller. Matches.
- R2 `CompatibilityResolvedDefinitionLoader|TEST_COMPATIBILITY_GRAPH`: test_persisted_agent_runtime ×3, test_prompt_assembler ×7 (3 + 4 constant refs), agent_runtime.py ×7. Matches.
- R3 `CodeOwnedAgentDefinitionSource`: script ×2, test_agent_runtime ×4, bootstrap ×2, prompt_assembler ×3, manifest ×2, persisted ×2 (+ agent_runtime.py ×4). Matches.
- R4 `StaticDefinitionSource`: test_agent_runtime.py:112, :349, :369. Matches (the plan says `:350`/`:370`, which is one-line drift).
- R5: test_agent_runtime imports at `:34-35`, and the digest tests now sit at `:254`, `:272` and `:306` (function defs; the call lines are `:301` and `:324`). test_agent_schema_registry `:1322-1324`. Matches. The `V1_/V2_SCHEMA_CONTRACT_DIGESTS` hits in test_graph_definition_manifest are local frozen literals, not R5 callers.
- R6 generator tests: test_graph_definition_manifest `:694`, `:701`, `:716` + parity `:266`. Matches.
- No new caller. No correction row is needed for Task 3.

## Task 1 — controller record, 2026-09-26
Task 1: implementer DONE at `1580b40d6` (TASK1_BASE `050062935`): `d92eae76d` conftest isolates unit runs (refuses any `DATABASE_URL` containing `ai_slide_generator` with `pytest.UsageError`; per-worker `mkdtemp` SQLite default; re-derives in workers that inherit the defaulted flag) + four style-exclusivity tests pinned to a real Graph Version 1 bootstrap; no `src/` change. Baseline before: 6 failed / 6625 / 110; after: 2 failed (deploy_autoscaling pair, pre-epic) / 6634 / 110. All 25 integration-graph PG files zero skips, counts identical before/after. 10 mutations RED incl. both plan targets.
Ruling: deviation from Correction 4 RATIFIED — the correction's `not in os.environ` check is false in every xdist worker (inherited env), measured by M9 (gw0 and gw1 shared one file); the implementer's flag-driven re-derivation plus `mkdtemp` isolates workers and avoids collisions with other worktrees' agents. Cost if wrong: none observed.
Ruling: deviation from Correction 17 RATIFIED — reading rows back cannot distinguish a broken `create_session` (the column bind hook normalises anyway; M1 stayed GREEN under read-back); the tests record `agent_config` as handed to the session on a real bootstrapped SQLite session. Cost if wrong: none observed.
Finding (pre-existing, from #267 `6358cf392`): `ids=lambda v: str(v)` at `tests/unit/test_agent_definition_workbench_routes.py:4797`/`:4829` embeds memory addresses, so every parallel (xdist) pytest run, including CI's auto-worker unit job, errors at collection. Ruled: fixed on its own branch `fix/stable-test-ids` from `a08389ec3` and merged ahead of #271, since CI is broken now.
Finding: the main checkout's `.env` sets `DATABASE_URL=postgresql://localhost:5432/ai_slide_generator`, which `load_dotenv()` picks up from worktrees; the conftest now always sets `DATABASE_URL`, closing that route.
Task 1: review (Sonnet): spec PASS, quality HIGH — 0 Critical, 0 Important, 1 Minor (`before_attach` vs `after_attach` capture timing not structurally pinned; values identical today). Reviewer sabotage: refusal → warning RED 2/5; silence the `isinstance(instance, UserSession)` capture guard RED 3/37. Both ratified deviations independently confirmed (M9 shared worker file; M4 read-back vacuity). Full unit (DATABASE_URL unset): 2 failed (deploy pair) / 6634 / 110; `-n 2` (routes file ignored pending the xdist fix, now merged at `82309f48d`): 2 failed / 6242 / 110.
Task 1: complete (commits `050062935..1580b40d6`, review clean).
Ruling: #271 is merged whole, not piecemeal; Task 1's conftest waits for #271's whole-branch review even though it is independent — the original boundary is "merge only when a ticket is fully implemented and reviewed". Cost if wrong: other lanes keep setting `DATABASE_URL` explicitly until then (they already do).

## Task 5 — 2026-09-26
Task 5: implementer DONE at `e5a43eba3` (TASK_BASE `04abb2d25`): `3767ef831` declares `openai>=1.99.9` (uncapped, I3) in `packages/databricks-tellr-app/pyproject.toml`, root `pyproject.toml`, `requirements.txt`; `test_the_manifests_declare_openai_within_the_transitive_bounds` via `packaging.requirements`. Implementer gates: 5/5 file; full unit 2 failed (deploy_autoscaling pair, baseline) / 6635 / 110; sabotages: drop the app line (RED), add `<2.0.0` cap (RED).
Controller re-probe (external-state fact): installed `databricks-langchain` 0.9.0 requires `openai>=1.99.9` — CONFIRMED via importlib.metadata. `langchain-openai` 0.3.32 caps `<2.0.0`; the declaration stays uncapped per I3.
Task 5: controller sabotage (own seam) — `requirements.txt` bound `>=1.99.9` → `>=1.0` (`CTRL271_5`, anchor 1). Scope `tests/unit/test_app_wheel_dependencies.py`: RED 1/5 (`test_the_manifests_declare_openai_within_the_transitive_bounds`). Restored from pinned HEAD, porcelain/diff/cached clean, GREEN 5/5.
Task 5: review (Sonnet): spec PASS, quality PASS — 0 Critical, 0 Important, 3 Minor. M1 root comment claimed `databricks-langchain>=0.1.0` (unverified range); M2 "transitively" wrong (openai is a direct requirement of databricks-langchain 0.9.0); M3 `Requirement(f"openai{...}")` built name `openaiopenai`. Apps BUILD: `langchain-openai` is only under `extra == 'openai'`, so its `<2.0.0` cap never enters the closure — no conflict. Reviewer sabotage: root bound `>=1.0` → RED 1/5, restored clean.
Task 5: fix round 1/5 (controller, 3 addressed, 0 open; `52972f731`): comments corrected in all three manifests; test parses the declared string directly. GREEN 5/5; root-bound sabotage re-run RED 1/5, restored; ruff clean.
Ruling: no scoped re-review — comment edits plus a two-line test simplification, re-sabotaged by the controller. Cost if wrong: none.
Task 5: complete (commits `04abb2d25..52972f731`). Phase A (Tasks 0-A, 1, 5) complete; Phase B waits for #268, #269, #270 merges.

## Phase B start — 2026-09-27
#268 merged `16aa02b76`, #269 merged `c7ea1d943`, #270 merged `12a521dc7` (all locally, all whole-branch reviewed). #271 rebased cleanly onto `12a521dc7` (12 commits, no conflicts). INTEGRATION_BASE = `12a521dc7`.
Carries into #271 Phase B: (1) C7/Task 8 — `resolve_engine_mode_or(..., fallback="monolith")` at `src/api/routes/chat.py:~490, ~697` silently falls back to the monolith on a DB failure; (2) the id-equals-version carry from #270 is CLOSED (whole-branch review found none across #268/#269/#270); (3) epic-level review must cover: the Q7 rollback caveat (accepted), the C32 endpoint-policy on rollback, `test_usage_service` midnight flake, `test_shared_deck_mutation_attribution` intermittent hang, `test_dependencies_resolve_on_proxy` network dependency; (4) all L0 locks via `_lock_current_parents` (AST scanner); (5) the forbidden-action count is 8; (6) CI has no ESLint job (found by #270's review — N2).
