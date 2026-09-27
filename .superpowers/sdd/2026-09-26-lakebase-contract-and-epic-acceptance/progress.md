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

## Task 0 phase B — 2026-09-27 (at HEAD `9a63ab1b7`, INTEGRATION_BASE `12a521dc7`)

- **Bases.**
  - `12a521dc7` is an ancestor of HEAD.
  - Code-wise, `12a521dc7..HEAD` is exactly the rebased Phase A commits `92c1fa49a`, `761e76703` and `119e673ce`. Each is patch-id-identical to its pre-rebase original. Everything else in the range is docs.
  - Every predecessor merge and reviewed head is recorded in `predecessor-heads.md`, with ancestry proven: #264, #266, #267, the xdist fix, #268, #269 and #270.
  - `TASK1_BASE` (`050062935`) is intentionally no longer an ancestor (C45).
- **Corrections 24–46** are appended to `PLAN-CORRECTIONS.md`, together with a per-task self-consistency table, a producer/consumer table and a Phase B blocking summary. Corrections 1–23 are not edited. Errata: C25 overrides C11.3, C26 overrides C3.4, C24 overrides C7's 503-handler claim, C35 overrides C21's sessions claim, and C31 overrides C20's count.
- **Cause baseline** (`reports/preflight-phase-b.md`):
  - **Unit:** 2 failed / 7169 passed / 110 skipped. The 2 are exactly the `test_deploy_autoscaling` pair. The skip causes are unchanged.
  - **PostgreSQL:** all 33 `integration-graph` files, one per invocation, 549 passed, 0 skips, 1 documented xfail. The attribution file ran in 17 s under `timeout 120`, with no hang. The `tellr_int_*` databases were unchanged (5).
  - **Frontend:** Vitest 21 files / 1099 passed. The app and node typechecks (`tsc --noEmit -p`) are clean.
  - **`frontend/tests` typecheck:** 1 error with the C3 config and the d.ts.
  - **ESLint on `frontend/tests`:** 25 pre-existing errors in 12 files.
- **Ruling (controller to confirm):**
  - Task 2 is **GO** once the C23 scoped re-review of C24–C46 has passed. None of C24–C46 blocks Task 2 itself.
  - Task 8 is **NO-GO** until the user rules on C24, which reverses the ws4d fail-open contract.
  - Task 13 is **NO-GO** until the user authorises the dev-workspace read (C43).
- **For the user:**
  1. C24: approve fail-closed engine-mode resolution at all three sites. This inverts four ws4d tests.
  2. Task 13 / #266 m9: authorise the read-only dev-workspace probe, or accept "m9 open: release gate unverified".
  3. The deploy_autoscaling issue (still open).
  4. #266 m7 (still open).
  5. A CI ESLint job as a follow-up issue (carry 6).
Ruling (C24): ADOPT fail-closed engine-mode resolution at all three sites (`chat.py:~490, ~697`, `chat_service.py:1141`) — #271 AC3 requires explicit failures that preserve conversation state, and "fail only when pinned" is unimplementable (the pin needs the same failed read). The stream route releases the session lock before raising; a typed 503 mapping is added; the four ws4d fail-open tests in `test_engine_mode_wiring.py` are inverted deliberately. — this reverses the ratified ws4d fail-open contract; SURFACED to the user for override. — cost if wrong: Task 8 rework; during a DB outage graph-mode turns 503 instead of silently running the monolith.
Ruling (Task 13 / #266 m9): NOT run — the dev-workspace probe is the user's to authorise (their workspace, their profile). Per C43, Task 13 writes no code; the ledger records "m9 open: release gate unverified"; the epic is not called shippable until the user runs it. Local merge proceeds.
Ruling (Task 12): the compatibility runtime has no production caller — deletion proceeds.
Ruling (C46): Task 8 runs before Task 7.
Next: the C23 scoped re-review of C24–C46, then Task 2.
C23 scoped re-review (Opus): GO for Task 2. C24/C33/C35/C37/C38 PARTIAL → errata C47–C51 written (controller). Task 8 proceeds on the controller's C24 ruling with C47's expanded scope (user may override).

## Task 2 — 2026-09-27
Task 2: implementer (Sonnet) DONE at `41ca3f134` (TASK_BASE `491cdf179`): `bfc8be5fe` `tests/fixtures/log_records.py` (`rendered_record`, `STANDARD_LOG_RECORD_ATTRS` = makeLogRecord attrs ∪ {message, asctime, taskName}) + `tests/unit/test_log_record_rendering.py`; 6 sites migrated in `test_persisted_agent_runtime.py`, 1 in `test_agent_test_workbench.py` (C28). Gates: 2 new, 361 touched-file, full unit 2 (baseline deploy_autoscaling pair) / 7171 / 110; ruff clean. Mutations: drop `pathname` RED; drop `exc_text` RED. Real-leak proof: old `str(vars(record))` false-fails on a `/private/tmp/…payload.py` pathname; the helper does not.
Task 2: controller sabotage (fresh) — extras not rendered (`CTRL271_2_EXTRAS`): RED 1/361 (`test_extras_message_args_and_exception_text_do_reach_it`). Restored clean.
Task 2: review (Sonnet): spec PASS, quality HIGH — 0/0/1 Minor (M1: pre-existing local `_STANDARD_LOG_RECORD_ATTRS` duplicate at `test_persisted_agent_runtime.py:918` — park, follow-up). All C28 sites migrated; no naive path-matching rendering remains; helper emits message/args/extras/exception; taskName covered. Reviewer sabotage: production identity sink logs `root_session_id` as an extra → RED at the migrated site (fired at the `emitted_fields` assert first; the `rendered_record` layer's catch is inferred, not observed — CONTROLLER NOTE: the reviewer's "both layers live" claim is half-proved; the controller's CTRL271_2_EXTRAS covers the helper layer). Temp worktree removed.
Task 2: complete (commit `bfc8be5fe`, review clean, no fix round).

## Task 4 — 2026-09-27
Task 4: implementer (Sonnet) DONE at `16585de17`: `37cd74730` `frontend/tsconfig.e2e.json` (no verbatimModuleSyntax, tsBuildInfo under node_modules/.tmp), reference in `tsconfig.json` (CI `tsc -b` picks it up), `frontend/tests/types/browser-modules.d.ts` (`declare module '/src/*'`), the TS2740 site, Python guard `tests/unit/test_frontend_tests_are_typechecked.py` (3). Gates: each tsconfig exit 0; `tsc -b` clean, no un-ignored tsbuildinfo; Vitest 1099; guard 3/3; ESLint 25 (baseline); full unit 2 (baseline) / 7174 / 110. Mutations: drop the reference → guard RED; re-introduce the type error → tsc RED.
Task 4: CONTROLLER REVIEW FINDING (fixed, `d58f32339`): the TS2740 "fix" changed `__TELLR_TEST_FINDINGS__ = [f]` to `= f`, altering what the negative "window global is gone" test injects (an object instead of the array) — a behaviour change that could make the test vacuous. Restored `[f]`, annotated `Array<typeof f>`; tsc e2e exit 0; findings-drawer Playwright 3/3.
Task 4: controller sabotage (C3 controller target) — `verbatimModuleSyntax: true` in the e2e config: tsc e2e 34 errors (C27 predicted 35 on the C3 config; 34 here), guard RED 1/3. Restored clean.
Ruling: the controller acted as reviewer for this 5-file build-config task (read the full diff; found and fixed the one defect); no reviewer subagent. Cost if wrong: small.
Task 4: complete (commits `011ddfa86..d58f32339`).

## Task 3 — 2026-09-27
Task 3: implementer (Sonnet) DONE at `d6c97aea0` (TASK_BASE `011ddfa86`; controller commits `d58f32339`, `7d6fbd231` interleaved): `tests/fixtures/packaged_release_loader.py` (`PackagedGraphV1Loader`, `packaged_v1_runtime`) + 30 loader tests (incl. 14 parity tests vs `AgentRuntime.compatibility`, deleted in Task 12); all 13 R1 callers + the `CompatibilityResolvedDefinitionLoader` / `CodeOwnedAgentDefinitionSource` callers migrated across 8 test files. After: only the loader file and its parity tests name the compatibility API. Full unit 2 (baseline) / 7204 / 110. Mutations: the controller's (ignore graph_release_id) — run by the implementer, SPENT; reviewer's (architect content +"x") RED 4.
CONCERN (controller): several tests were REWRITTEN rather than moved (`test_code_owned_contract_identities_are_stable_literals`, `test_graph_definition_manifest.py`, `test_agent_schema_registry.py`, 2 tests → `content_overrides`, `ValueError` → `GraphReleaseNotFoundError`), against the brief's "assertions byte-identical — a move, not a rewrite". The review must check each rewrite for weakening. `task-3-report.md` was written but not force-added — added by the controller.

Ruling (order): Task 8 consumes Task 6's `run_to("S12")` and Task 7's turn driver, so the order is 6 → 7 → 8 (C46 option 2: re-run Task 7's tests after Task 8 edits `chat_service.py`). Then 9, 10, 11, 12, 14.
Task 3: review (Opus): spec PASS (every flagged rewrite is mandated by the brief's own Step 3; the byte-identical rule covers the mechanical swaps, which are), quality APPROVE with 1 Important + 3 Minor. I: `test_prompt_assembler.py:455-473` now compares the manifest to itself (vacuous — sabotage 1 left it GREEN; the pre-commit version went RED). Minors: `:426` tautology; two misleading test names; dropped explicit version checks. Rewritten identity tests narrow from runtime constants to the manifest — justified (Task 12 deletes the constants; the 14 parity tests guard them until then — sabotage 2 RED 16). Grep clean; loader test-only; Task 2 intact. Temp worktree removed.
Controller correction: my concern that the rewrites violated the brief was WRONG — Step 3 mandates them.
Task 3: fix round 1/5 dispatched (resume implementer): the Important (replace with a test-side oracle, e.g. `load_skill(k).instructions` via the historical replay, or delete) + the 3 Minors.

## Task 6 — 2026-09-27
Task 6: implementer (Opus) DONE at `9e7f2baf8`: `bdb49bdc3` test-only — `tests/integration/graph_lifecycle_journey.py` (staged harness, `run_to`), `tests/integration/test_graph_lifecycle_acceptance_postgres.py`, `tests/unit/test_graph_lifecycle_stage_attribution.py` (13), integration-graph enrolment + CI pin. `src/` unchanged; no defect. Gates: attribution 13, CI collection 23, lifecycle 1, #269 acceptance 3, #270 acceptance 1, publication 21, rollback 12 — zero skips; full unit 2 (baseline) / 7217 / 110; ruff clean. 13 mutations RED with the right ticket label (M1–M13, incl. the plan reviewer sabotage) + CI-pin mutation.
Concern 1 (valid): the implementer's in-place `src/` mutation windows overlapped the concurrent Task 3 fix round's unit runs — Task 3's gate results must be RE-RUN by the controller after its fix round (queued). Concern 2: the C50 `src.core.database.get_db_session` patch is currently unexercised (no image placeholders) — kept for Tasks 7/8. Concern 4 → Task 10 matches exchange ids, not literal paths.
Task 6: controller sabotage (plan controller target, C34) — drop `("prompt_text",)` from `_DIFF_FIELDS`, in a temp worktree: RED `[#269] S10 preview via GET …/release-preview` (architect's `prompt_text` diff missing) — exactly as C34 predicts. Temp worktree removed.
Task 3: fix round 1/5 (all addressed; `966727567`): the tautological byte-parity test DELETED (assembly covered by `test_v1_assembly_matches_independent_historical_replay`; release-id check by the loader test); `:426` now `content.prompt_text == load_skill(agent_key).instructions`; two tests renamed to manifest-based names; explicit version checks added. Mutation: architect prompt drift → replay test RED. Full unit 2 (baseline) / 7217 / 110; ruff clean.
Controller re-verification (Task 6's concurrent in-place `src/` mutation windows): tree clean, `src` diff empty; the 9 Task 3 files re-run → 604 passed.
Task 3: complete (commits `011ddfa86..966727567`, review clean after 1 fix round).
Task 6: review (Opus): spec PASS, quality APPROVED WITH FIXES — 0 Critical, 1 Important, 5 Minor. I1: the attribution unit file pins the ticket of only 4/17 stages — reviewer sabotage B (S15 relabelled #270 → #269) SURVIVED 14/14. m1 bare asserts (no message) in S04–S06/S12/S15; m2 S14 compares v1's `published_by` with itself; m3 readiness stale-hash invisible to the journey (owner tests catch it — coverage note); m4 harness needs a public `journey.in_stage(Stage)` (Task 7 would otherwise poke private `_current`), and S12b/S16 exact counts break if Task 7's stages create sessions/mutations; m5 noted. Reviewer sabotage A (silent re-pin on rollback) RED [#270] S16; C (wrong evidence source) RED [#270] S15. All deviations legitimate; isolation clean. Temp worktree removed.
Ruling: fix now I1 (assert the whole STAGES table as literal (code, name, ticket) tuples), m1, m2, m4 (`in_stage` context manager, additive). m3 → optional, park (owner tests cover it). Task 7 notified of m4.
Task 6: fix round 1/5 dispatched (resume implementer).
Task 6: fix round 1/5 (4 addressed, m3 parked; `afac6cf3c`, additive): full 17-row STAGES literal pin; assert messages; S14 bootstrap actor literal `system:bootstrap`; public `journey.in_stage(stage)` + 3 tests. Gates: attribution 17, CI 24, lifecycle PG 1 zero skips; ruff clean. Mutations in the implementer's own temp worktree: F1 S15 relabel RED 1/17 (was GREEN before); F2 bootstrap actor changed RED [#270] S14. Task 7 constraint recorded (no sessions/deck mutations before S12b/S16 assertions).
Ruling: no scoped re-review — test-only, both findings independently mutated RED. Task 6: complete (commits `002d4c4ab..afac6cf3c`).

## Task 7 — 2026-09-27
Task 7: implementer (Opus) DONE_WITH_CONCERNS at `7097df312` (TASK_BASE `693df109e`): `b03f76eb5` `tests/integration/test_graph_lifecycle_runtime_postgres.py` (2) + integration-graph + CI pin; `fb5d40caa` S17 labels + any ERROR event fails a turn; `dadffe0b1` stage bodies via `journey.in_stage`. `src/` unchanged. Gates: new 2 zero skips; lifecycle 1; pin acceptance 1; persisted runtime failures 7; graph-mode turn 39; CI 24; full unit 2 (baseline) / 7222 / 110; ruff clean. 14 mutations in a temp worktree: 12 RED with the right `[#261] S13` / `[#265] S17` labels (incl. plan reviewer sabotage + C8 `bind_tools([])`), 2 not decisive and replaced by targeted ones; CI-line mutation RED.
PRODUCTION DEFECT (concern 1) — controller-REPRODUCED: frozen+slots exception dataclasses become `TypeError` inside a `@contextmanager` → correction C52, routed to Task 8.
Deviation (C8): the real `DatabricksModelAdapter` with a `bind_tools`-raising ChatModel double drives all 30 calls of three turns — accepted (one ordered queue, deterministic).
Task 7: controller sabotage (plan controller target, in a temp worktree) — `builder.py:345` pin replaced by the active release id: RED `[#261] S13 turns on pinned releases …` (right stage/ticket; observed cause `GraphRecursionError`, not the predicted v3-vs-v1 identity mismatch — the wrong pin first breaks the placeholder commit; still a named RED at the predicted stage). Temp worktree removed.
