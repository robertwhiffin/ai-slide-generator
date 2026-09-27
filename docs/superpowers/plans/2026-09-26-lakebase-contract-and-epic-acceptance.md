# Lakebase-Only Contract and Epic #258 Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: use `executing-plans-tellr` and `superpowers:subagent-driven-development` together. Steps use checkbox (`- [ ]`) syntax. The spec and issues are binding. This plan is a hypothesis until Task 0 records code-verified corrections in `PLAN-CORRECTIONS.md`. That file overrides this one wherever they differ.

**Goal:** Close epic #258. First, prove the complete edit-to-rollback lifecycle through the shipped seams: real PostgreSQL over admin HTTP, the shipped graph-mode chat entry point, and Playwright for both user journeys. Then, and only then, delete the compatibility runtime (`CompatibilityResolvedDefinitionLoader`, `CodeOwnedAgentDefinitionSource`, `AgentRuntime.compatibility()` and what hangs off them). That leaves one Lakebase-backed production path.

**Architecture:** This is the contract half of an expand–contract migration. Tasks 1–5 repair epic-wide test hygiene and move every test off the compatibility path onto a test-only loader over the packaged manifest. Production is unchanged. Tasks 6–11 add the acceptance suite:
- one staged lifecycle journey whose every failure is labelled with the ticket that owns the failing seam;
- a code-default **tripwire** that fails the run if any code-owned definition source or the bootstrap manifest is read after Graph Version 1 exists;
- the graph-mode runtime seam across three releases;
- the explicit-failure matrix;
- the admin authorization inventory;
- two Playwright journeys whose mocks are recordings of the real HTTP contract.

Task 12 deletes the compatibility code, and its gate refuses to start until Tasks 6–11 are green (AC10). The removal adds structural guards so the path cannot return.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL 15, LangGraph, React 19, TypeScript 5.9, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-21-agent-definition-workbench-design.md` (all of it; §§6, 7, 15, 17.5 and 18 most directly).

**Binding issues:**
- #271, all ten acceptance criteria;
- #258, user stories 1–60 and the Testing Decisions;
- #259–#270, for the seams the journey crosses.

**Consumes (read-only; not implemented when this plan was written):**
- #268, `.worktrees/issue-268-plan/.superpowers/sdd/2026-09-23-test-evidence-readiness/PLAN-CORRECTIONS.md`, over the user's untracked draft `docs/superpowers/plans/2026-09-23-test-evidence-readiness.md` in the main worktree;
- #269, `.worktrees/issue-269-plan/`, plan plus Corrections 1–31;
- #270, `.worktrees/issue-270-plan/`, plan plus Corrections 1–23.

## Global constraints and execution protocol

- **Two phases.**
  - **Phase A** runs on the current integration head (`a08389ec3`, local `feat/langgraph-core` with #259–#267). It is Task 0 phase A, Task 1 and Task 5. They touch no file that #268, #269 or #270 own or are expected to edit.
  - **Phase B** is everything else. It dispatches only after reviewed #268, #269 and #270 are merged **locally** into `feat/langgraph-core` and Task 0 phase B has refreshed the corrections file against that commit.
  - Never dispatch a Phase B task against `a08389ec3`.
- **Integration base.**
  - Record immutable `TASK1_BASE` before Task 1 and `INTEGRATION_BASE` at Task 0 phase B. Never overwrite either.
  - Before any Phase B task, rebase the Phase A commits above `INTEGRATION_BASE`.
  - Prove that `INTEGRATION_BASE..HEAD` contains exactly the rebased Phase A commits and the Phase B work.
  - Never fetch or depend on a remote integration ref.
- **Interpreter.**
  - Every Python command is `PYTHONPATH=<worktree>:<worktree>/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest …`, run **from inside the worktree**.
  - Run `test ! -e .venv` before and after every backend gate.
  - Never run `pip`, `uv`, `npm install`, `npx playwright install` or any installer. The site-packages are shared across parallel agents.
- **Unit runs set `DATABASE_URL=sqlite:////tmp/t271-<task>.sqlite`** explicitly until Task 1 lands, and keep doing so afterwards as belt-and-braces. Without it they write to the operator's dev database `ai_slide_generator`.
- **PostgreSQL.**
  - Every PostgreSQL test file starts with `pytestmark = pytest.mark.postgres`.
  - It is run as its own command: `TELLR_TEST_POSTGRES_URL=postgresql+psycopg2://localhost:5432/postgres <interpreter> -m pytest -q -rs <file>`.
  - It must report **zero skips**, recorded per file.
  - It is enrolled in `.github/workflows/test.yml`'s `integration-graph` job, and `tests/unit/test_ci_collects_integration_tests.py` stays green (its `DELIBERATE_EXCLUSIONS` stays empty).
  - Fixtures create and drop uuid-named throwaway databases; nothing may touch `ai_slide_generator`.
- **Frontend.**
  - Only from `frontend/`, with checked-in dependencies:
    - `(cd frontend && npm run test:unit -- <paths>)`;
    - `(cd frontend && npm run typecheck)`;
    - `(cd frontend && npx eslint <paths>)`;
    - `(cd frontend && npx playwright test tests/e2e/<spec>.spec.ts --project=chromium --workers=1)`.
  - Every new spec is added to the `e2e` matrix (`tests/unit/test_e2e_matrix_covers_specs.py` enforces this).
- **Playwright names.**
  - Every `getByRole(…, { name })` in a new spec passes `exact: true`. Playwright matches substrings by default; Testing Library matches whole names.
  - No new control name may be a case-insensitive substring or superstring of another on the same page.
  - The forbidden-action guard (`frontend/tests/fixtures/forbiddenActionNames.ts`) exempts exact whole names only. #271 adds **no** exemption and does not touch a stem.
- **Text-read files.** These are read as text by Python join tests and keep their exact format: `frontend/src/api/agentDefinitions.ts`, `frontend/src/components/Admin/AgentDefinitionWorkbench/draftEditorState.ts`, `frontend/tests/fixtures/mocks.ts`, `frontend/src/types/*.ts`. Task 0 phase B re-derives the list with `rg -l "frontend/" tests/unit`. #271 edits none of them except where a task's Files block names one.
- **Epic invariants.** Every task preserves these (Task 14 verifies each):
  - one locked draft-content writer;
  - one model binding (`with_structured_output(` occurs once under `src/`);
  - one frontend reducer, one request counter and one in-flight gate per page;
  - one admin `APIRouter` with prefix `/api/admin/agent-definitions` and router-level `require_admin`.
- **The user's decisions.**
  - No session, user, turn or release identifier reaches any model.
  - The log carries key **names** only.
  - No model prose goes in the log.
  - Nothing fabricates a release id in the production log.
- **Sabotage.**
  - Before each task, record `TASK_BASE=$(git rev-parse HEAD)`.
  - The controller and the reviewer each sabotage a **different** executed production (or harness) seam, named in the task.
  - For each sabotage: grep the marker with `rg` to prove it sits on the executed path; capture a real RED; restore exactly; prove the marker is gone and `git diff` is clean; capture GREEN.
  - Generate review packages from exactly `TASK_BASE..TASK_HEAD`, never `HEAD~N`.
- **Workspace.**
  - The SDD workspace is `.superpowers/sdd/2026-09-26-lakebase-contract-and-epic-acceptance/`: `progress.md`, `PLAN-CORRECTIONS.md`, `TASK1_BASE`, `INTEGRATION_BASE`, `predecessor-heads.md`, `reports/`, `packages/`.
  - Only `progress.md` is committed, force-added with `git add -f` because `.superpowers/` is git-ignored.
  - Every commit message ends with a blank line and then `Co-authored-by: Isaac <no-reply@databricks.com>`.
  - A local hook falsely blocks one shell command that contains `sed -n` or `grep -n` together with `git commit`. Always commit in its own command.
- **No push, no PR, no remote merge.** GitHub is read-only. #271 ends with a **local** merge into `feat/langgraph-core`.

## Verified code facts (file:line at `a08389ec3`; Task 0 re-verifies each)

| Fact | Location | Detail |
|---|---|---|
| compatibility loader | `src/services/agent_runtime.py:585-619` | `CompatibilityResolvedDefinitionLoader.resolve` fabricates `graph_release_id=1`, `graph_version=1` and `revision_id = definition_version` from `CodeOwnedAgentDefinitionSource` |
| compatibility factory | `src/services/agent_runtime.py:809-826` | `AgentRuntime.compatibility(model_adapter, definition_source, identity_sink)` is the loader's only production-module constructor |
| code-owned source | `src/services/agent_runtime.py:347-391` | reads `load_skill(agent_key)` (`src/core/skills`), `DEFAULT_CONFIG["llm"]`, and the packaged manifest's `assembly_rules` |
| duplicated schema identity | `src/services/agent_runtime.py:99-112`, `:224-344` | `_PROTECTED_PROMPT_*`, `_SCHEMA_CONTRACT_DIGESTS`, `_canonical_digest`, `_schema_contract_material` (+ config/validator material) and `_SchemaContractRegistry`, which duplicate `agent_schema_registry.py:49`, `:182`, `:251`, `:357-379` |
| production wiring | `src/services/agent_runtime.py:1149-1177` | `get_agent_runtime()` and `get_agent_test_runtime()` both use `PersistedGraphReleaseLoader`, with no fallback |
| v1-only overlay rule | `src/services/agent_runtime.py:1018-1023` | the one production use of `_SCHEMA_CONTRACT_VERSION` |
| manifest generator | `scripts/generate_graph_definition_manifest_v1.py:19-36` | builds the v1 manifest **from** `CodeOwnedAgentDefinitionSource` |
| manifest reader | `src/services/graph_definition_manifest.py:360-366`; `graph_configuration_bootstrap.py:71-73` | `load_graph_v1_manifest` has one production caller besides the code-owned source: bootstrap |
| protected bundles | `src/services/prompt_assembler.py:387-425` | `_default_bundles()` keyed `(version, digest)`: v1 `e4ff3d61…6852`, v2 `fb651a0d…592a`; `resolve_bundle(ContentIdentity)` raises `ProtectedAssemblyBundleUnavailable` |
| schema bundles | `src/services/agent_schema_registry.py:297-316`, `:378-389` | `SCHEMA_CONTRACT_BUNDLES[(role, version)]` for v1 and v2 of all seven roles, digest-checked at construction |
| legacy source route | `src/api/routes/agent_definitions.py:726-763`; `prompt_assembler.py:830-835` | admin-only, reads the **retained v2 bundle's** transition records. It is bundle retention, **not** a runtime fallback |
| one admin router | `src/api/routes/agent_definitions.py:97-101` | prefix `/api/admin/agent-definitions`, `dependencies=[Depends(require_admin)]` |
| test-run routes | `agent_definitions.py:1119-1210` | `POST /draft/{agent_key}/test-runs` `{test_case_id, lock_version}`; `POST /published/{agent_key}/test-runs` `{test_case_id}`; `GET /test-runs/{run_id}`; `GET /test-cases/{id}/runs`; workbench dependency `get_agent_test_workbench` (`:1016`) |
| model discovery | `agent_definitions.py:115`, `:156`, `:529`; `src/services/model_endpoint_catalog.py:281` | `get_remote_endpoint_draft_validator`, `get_model_endpoint_catalog`, `FakeModelEndpointCatalog` |
| production trace | `src/services/agent_runtime_identity.py:100-190` | `LoggingAgentInvocationIdentitySink` logs `persisted_agent_invocation` with exactly `graph_version, graph_release_id, agent_key, agent_definition_revision_id, content_hash, outcome, error_class` (+ `additional_field_names` on success) |
| pin loader | `src/services/conversation_pins.py:151-160`; `graph/builder.py:345` | `load_conversation_pin` returns exactly the persisted pin or raises `ConversationPinMissingError` |
| graph chat seam | `tests/integration/test_graph_mode_turn.py:342-420` | `graph_chat_env` recipe: the redirected `get_graph`, `src.core.database.get_db_session`, `get_settings`, title generation, `get_user_client`, `ChatDatabricks`, and the booby-trapped `_build_agent_for_session` |
| PG three-turn acceptance | `tests/integration/test_conversation_pin_acceptance_postgres.py:368-512` | real graph over `invoke_graph` (not the chat entry point); ORM-built v2 (`_publish_v2`), not #269 publication |
| PG admin route stack | `tests/integration/test_agent_definition_workbench_postgres.py:1284-1311` | `real_route_stack` |
| fake adapter | `tests/fixtures/deterministic_model_adapter.py` | `DeterministicFakeModelAdapter`, `FAKE_OUTPUTS` |
| model-payload key literals | `tests/fixtures/model_payload_keys.py` | per-call literal key sets; no identifier key |
| log helpers | `tests/unit/test_persisted_agent_runtime.py:924`, `:948`, `:1032`, `:1937`; `tests/unit/test_agent_test_workbench.py:2003` | `str(vars(record))` renders `pathname`/`filename`/`module`, so needles `"private"` and `"payload"` match `/private/tmp/…` and `agent_model_payload.py` |
| dev-DB default | `src/core/database.py:203-264` | with no `DATABASE_URL` and no Lakebase env, the URL is `postgresql://localhost/ai_slide_generator`; `tests/conftest.py:1-20` sets only `ENVIRONMENT=test`; CI's unit job deliberately sets no `DATABASE_URL` (`.github/workflows/test.yml:96-104`) |
| wheel manifest | `packages/databricks-tellr-app/pyproject.toml:11-60`; `tests/unit/test_app_wheel_dependencies.py:30-60` | `openai` is imported at module level by `agent_runtime.py:28` and `model_endpoint_probe.py`, and declared in neither manifest. The env has `openai 1.105.0`; `databricks-langchain` requires `openai>=1.99.9` and `langchain-openai` requires `openai<2.0.0,>=1.99.9` |
| frontend typecheck | `frontend/tsconfig.app.json` (`"include": ["src"]`), `tsconfig.node.json` | `frontend/tests/**` is never typechecked |

**Probes run for this plan (read-only):**
- **P1 (tests typecheck).** Copied `frontend/{src,tests,tsconfig*}` to `/tmp/probe271-ts`, symlinked the main worktree's `node_modules`, and ran `tsc -p` with an include of `tests/**/*.ts`. Result: exactly **12 errors**:
  - 9 × TS2307 on absolute browser-side imports `'/src/…'` inside `page.evaluate`: `slide-surface-fidelity.spec.ts` ×6, `slide-viewer.spec.ts` ×3;
  - 2 × TS2339 `ImportMeta.env` (`src/api/agentDefinitions.ts:1-2`, because the probe lacked `vite/client` types);
  - 1 × TS2740 at `findings-drawer.spec.ts:87`, where a `SlideFinding[]` is passed where a `SlideFinding` is expected.
- **P2 (baseline failures).** At `a08389ec3`, with `DATABASE_URL=sqlite`, `test_deploy_autoscaling.py` ×2, `test_style_exclusivity_chokepoint.py` ×3 and `test_style_exclusivity_persistence_boundary.py` ×1 fail.
  - On `git archive main` (`f6b1506c5`), the two deploy tests **also fail**. The four style tests **pass**.
  - So the style failures are epic-caused: `create_session` now requires an active Graph Release. The causes are `_FakeSession has no attribute 'execute'` and `ConversationGraphReleaseIntegrityError: no active Graph Release`.
  - The deploy failures are not epic-caused.

## Removal inventory (every compatibility path found at `a08389ec3`, with callers)

| # | Path | Callers (file:line) | Disposition |
|---|---|---|---|
| R1 | `AgentRuntime.compatibility()` (`agent_runtime.py:809`) | 13 call sites in 4 test files: `test_agent_runtime.py:166,209,231,332,347,367,480,495,594`; `test_graph_configuration_bootstrap.py:414`; `test_agent_resolution_prompt.py:76`; `test_deck_level_spec_change.py:1026,1085`. **No production caller.** | Task 3 migrates the callers; Task 12 deletes |
| R2 | `CompatibilityResolvedDefinitionLoader` (`:585`) and `TEST_COMPATIBILITY_GRAPH_RELEASE_ID/VERSION` (`:581-582`, a fabricated release id 1) | `agent_runtime.py:819` (R1); `test_persisted_agent_runtime.py:30,1040,1061`; `test_prompt_assembler.py:34,425,460` (+ 4 constant refs) | Task 3 migrates; Task 12 deletes |
| R3 | `CodeOwnedAgentDefinitionSource` (`:347`); reads `load_skill` + `DEFAULT_CONFIG["llm"]` | `agent_runtime.py:822`; `scripts/generate_graph_definition_manifest_v1.py:21,35`; `test_agent_runtime.py:29,255,341,360`; `test_graph_configuration_bootstrap.py:30,415`; `test_prompt_assembler.py:33,425,460`; `test_graph_definition_manifest.py:30,269`; `test_persisted_agent_runtime.py:29,1040` | Task 3 migrates; Task 12 deletes |
| R4 | `AgentDefinitionSource` Protocol (`:213`), `AgentDefinition` dataclass with `legacy_tool_grants` (`:170-180`) | R1/R3 only; test fake `StaticDefinitionSource` (`test_agent_runtime.py:112`, used at `:350`, `:370`) | Task 12 deletes (AC5: no tool-grant field reaches the runtime) |
| R5 | duplicated v1 identity machinery (`_SchemaContractRegistry`, `_canonical_digest`, `_schema_*_material`, `_SCHEMA_CONTRACT_DIGESTS`, `_PROTECTED_PROMPT_*`, `RuntimeContractIdentityError`) | R3; `test_agent_runtime.py:34-35` (imports `_canonical_digest`, `_schema_contract_material`; tests at `:254`, `:272`, `:306`); `test_agent_schema_registry.py:1322-1324` | Task 3 re-points the tests to `agent_schema_registry`; Task 12 deletes. `_SCHEMA_CONTRACT_VERSION` is replaced at `:1018` per Task 0 |
| R6 | manifest **generator** (`scripts/generate_graph_definition_manifest_v1.py`) | `test_graph_definition_manifest.py:694-735` (3 tests), plus the parity test `:266-283` | Task 12 deletes the script and those 4 tests. Frozen literals (`PACKAGED_V1_CONTENT_HASHES`, `:745`) remain the oracle. Reason: after #271 the generator can only produce a *different* "Graph Version 1" for fresh deployments than existing ones hold |
| R7 | `AgentRuntime` unused imports (`load_skill`, `DEFAULT_CONFIG`, `inspect`, `textwrap`) and the module docstring's "temporary adapter" text (`:1-11`) | — | Task 12 |
| — | **Reviewed and retained:** `POST /draft/{agent_key}/legacy-prompt-source` and `PromptAssembler.legacy_v1_prompt_source` | admin workbench | Retained. They read the retained v2 bundle's transition records (AC4 retention), never a runtime definition |
| — | **Reviewed and retained:** `src/core/skills/*` | `prompt_assembler.py:15-26` imports protected constants (`DECK_BRIEF_REVIEW`, analyst security text); tests read `load_skill` | Retained as code-owned **protected-bundle material** and inert legacy `tool_grants` metadata (spec §19). Task 12 guards that `load_skill` has **zero** `src/` callers |
| — | **Reviewed, out of scope:** `DEFAULT_CONFIG["llm"]` in chat title generation (`chat_service.py:1418`, `:1981`), `agent.py`, `agent_factory.py`, `llm_judge.py`, `config_validator.py` | legacy monolith, naming model, judge | Not an Agent Definition or Graph Node (spec §7.3: these "keep their existing configuration") |
| — | **Reviewed, not a fallback:** `state.get("graph_release_id")` in `graph/nodes.py:1820,2451,2615,2819,2965` | deck-mutation attribution (`MutationActor`) | Attribution only; no definition is resolved from it. Task 7 asserts every model-driven call resolved the pin |

## Rulings on the epic-wide follow-ups routed to #271

| Follow-up | Ruling | Reason | Where |
|---|---|---|---|
| `frontend/tests/` has no typecheck | **In scope** | Measured cost is 12 errors (P1). #271 adds the two largest specs of the epic, and a typecheck-free spec tree is how a wrong mock shape ships | Task 4 |
| Log-test needles matching `pathname` (`"private"`, `"payload"`) | **In scope** | The epic's no-prose/no-id log decisions are only as strong as these guards. `/private/tmp` (macOS) and `agent_model_payload.py` make them fire on the wrong field, which invites someone to delete the needle | Task 2 |
| Dev-database default URL in unit tests | **In scope** (conftest fix) | Unit runs without `DATABASE_URL` write to `ai_slide_generator`. It is a one-file fix with a guard test | Task 1 |
| Deploy/autoscaling (2) and style-exclusivity (4) baseline failures | **Split.** Style ×4 **in scope**; deploy ×2 **out of scope** | P2: the style failures are epic-caused (conversation pins need an active release) and an acceptance ticket cannot close red on its own epic. The deploy failures reproduce on `main` `f6b1506c5`, pre-date the epic, and live in `packages/databricks-tellr/deploy.py` | Task 1 (style). Deploy: listed for a new GitHub issue by the user; Task 0 records the causes as an accepted baseline |
| `openai` not declared in the app wheel | **In scope** | `agent_runtime.py` imports it at module level, so it is a runtime dependency of the Lakebase path this ticket makes the only path. It is already in the resolved closure (via `databricks-langchain`), so the declared range `>=1.99.9,<2.0.0`, which is exactly the intersection of both transitive constraints, adds no distribution | Task 5 |
| #266 m7, unescaped endpoint name at `src/services/tools/model_endpoint_tool.py:75` | **Out of scope** | It is the legacy per-session tool path under the user's OBO client. Spec §4.2/§19 and #258 "Out of Scope" exclude tool binding and legacy monolith calls. It is not reachable from any Agent Definition invocation | Listed for a new GitHub issue by the user |
| #266 m9, pay-per-token `config_update` readiness | **In scope as a release gate, conditional** | If a pay-per-token system endpoint omits `config_update`, every save of a seeded role fails with `endpoint_not_ready`, which would make the epic unusable. It needs a live dev-workspace probe (external state), so it runs only with explicit user authorisation. The code branch for "absent" is pre-written | Task 13 |

## Consumed interfaces from #268, #269 and #270

Every row is **assumed from that ticket's plan and corrections. Re-probe at Task 0 phase B.** Where a plan is silent, this plan does not invent a shape. The row says "Task 0-B records".

| Id | Interface | Source | Consumed by |
|---|---|---|---|
| C268-1 | `POST /api/admin/agent-definitions/test-runs/{run_id}/verdict`, strict body `{verdict: "approved"\|"rejected", notes: str\|null}`; 200 `TestRunEvidenceResponse` with required nullable `verdict, verdict_reviewer, verdict_at, verdict_notes`; 422 `ineligible_for_approval` `{reason: not_completed\|checks_failed}` | #268 C15, C16 (assumed from #268's plan, re-probe at Task 0 phase B) | Tasks 6, 10 |
| C268-2 | `GET /api/admin/agent-definitions/readiness` → `DraftReadinessResponse` (strict, snake_case; per-role `candidate_hash`, `missing_required_case`, cases with `status ∈ needs_test\|test_failed\|awaiting_review\|approved`; `draft_lock_version`). Exact field list: **Task 0-B records** | #268 C11, C14, C17 (assumed from #268's plan, re-probe at Task 0 phase B) | Tasks 6, 10 |
| C268-3 | `cleanup_unpublished_test_runs(session, *, per_case_limit=20) -> int`, with no production caller (C21) | #268 C18, C21 (assumed from #268's plan, re-probe at Task 0 phase B) | Task 14 (review only) |
| C268-4 | Frontend `getDraftReadiness`, `recordTestRunVerdict`; controls `Approve run` / `Reject run` (exact exemptions; `ALLOWED_ACTION_NAMES` length 7) | #268 C22, C23, C26 (assumed from #268's plan, re-probe at Task 0 phase B) | Task 10 |
| C269-1 | `GET /api/admin/agent-definitions/release-preview`; `POST /api/admin/agent-definitions/releases` `{lock_version, release_note}` → **200** body `{release, previous_release_id, changed_agents, mappings{7×{agent_definition_revision_id, content_hash, reused}}, evidence[…], draft}`; 409 `stale_publication` / `nothing_to_publish` / `publication_not_ready` (`gaps[{agent_key, test_case_id, code}]`, `readiness`); 422 `invalid_publication`. Response model class names: **Task 0-B records** | #269 plan :181-196; C1, C10 (Q6: 200), C31 (same router) (assumed from #269's plan, re-probe at Task 0 phase B) | Tasks 6, 10 |
| C269-2 | `GraphConfiguration().publish_draft(session, *, expected_lock_version, release_note, actor, evidence_gate)`; `ApprovalEvidenceGate` | #269 plan :160-170, Task 4 (assumed from #269's plan, re-probe at Task 0 phase B) | Task 7 (non-HTTP publication in the runtime test) |
| C269-3 | Page `/admin/agent-definitions/review`; `data-testid`s `release-review-page`, `release-next-version`, `release-changes-tab`, `release-diff-tab`, `release-note-input`, `release-publish-button`, `release-stale-alert`, `release-not-ready-panel`, `release-success-panel`; control `Review & Publish` | #269 plan :842, C7 (assumed from #269's plan, re-probe at Task 0 phase B) | Task 10 |
| C270-1 | `GET …/releases`, `GET …/releases/{version_number}`, `GET …/releases/{version_number}/comparison`, `GET …/releases/{version_number}/rollback-preview`, `POST …/releases/{version_number}/rollback` `{lock_version, release_note}` → 200 with `restored_from`, seven `reused: true` mappings, `historical_restore` evidence, `draft_effect`; 409 `stale_rollback` / `rollback_source_active` / `rollback_matches_active`; 422 `rollback_incompatible` / `invalid_rollback`. Module `src/api/schemas/graph_release_history.py`; model class names: **Task 0-B records** | #270 plan :256-269; C8 (assumed from #270's plan, re-probe at Task 0 phase B) | Tasks 6, 10 |
| C270-2 | Three-way draft rebase on rollback (`reset`/`kept`/`unchanged`) | #270 Q7 ruling (assumed from #270's plan, re-probe at Task 0 phase B) | Task 6 S15 |
| C270-3 | Release History tab on the review page; fixed names `Inspect this version`, `Roll back to this version` scoped by `release-history-row-<version>`; `Rollback note`, `Confirm rollback`, `Cancel rollback`; `data-testid`s `release-history-tab`, `release-history-row-<v>`, `release-history-detail`, `release-comparison`, `rollback-preview`, `rollback-note-input`, `rollback-confirm-button`, `rollback-cancel-button`, `rollback-blocked-panel`, `rollback-stale-alert`, `rollback-success-panel` | #270 Task 7; C3 (assumed from #270's plan, re-probe at Task 0 phase B) | Task 10 |
| C270-4 | `graph_release_rollback` log record with `outcome` and `agent_keys` only | #270 "Log contract" (assumed from #270's plan, re-probe at Task 0 phase B) | Task 7 |

Silent in those plans, so Task 0-B records rather than assumes:
- the exact Pydantic class names of the #268/#269/#270 response and request models;
- whether #269 exported `definition_field_diffs` under that name;
- the Review & Publish page's route-gate coverage;
- the final `ALLOWED_ACTION_NAMES` length after #268/#269/#270.

## Seam table against every earlier ticket

| Ticket | Seam #271 exercises | Where | Label in the journey |
|---|---|---|---|
| #259 | one `AgentRuntime` for seven roles; Foreman absent; stable bundle identities; no tools bound | Tasks 3, 7, 12 | `S13`, `S16` (`#259`) |
| #260 | bootstrap v1 exactly once; seven mappings; shared draft; admin topology read; Foreman read-only | Task 6 `S01` | `#260` |
| #261 | root pin at creation; pin → `GraphState` → every `Send`; exact-release resolution; traces; explicit failures | Tasks 7, 8 | `S02`, `S13` (`#261`) |
| #262 | chat-auto-created, contributor and duplicate pins; mixed-release attribution and warning | Tasks 6 `S12`, 8, 11 | `#262` |
| #263 | explicit per-role save, lock version, stale `409` | Task 6 `S03` | `#263` |
| #264 | schema-contract upgrade, `diagnostic_notes` overlay, trace names | Task 6 `S04`, Task 7 | `#264` |
| #265 | protected-assembly upgrade, custom block, trust boundary; retained v1/v2 bundles | Task 6 `S05`, Task 7 `S17` | `#265` |
| #266 | discovery via the injected fake catalog; exact endpoint selection | Task 6 `S06` | `#266` |
| #267 | required smoke cases, candidate runs through the shared private path, evidence | Task 6 `S07` | `#267` |
| #268 | verdicts, readiness gaps, current-hash eligibility | Task 6 `S08`, `S09` | `#268` |
| #269 | preview diffs, atomic publish, stale conflict, reuse, evidence links, new pins | Task 6 `S10`, `S11`, `S12` | `#269` |
| #270 | history, comparison, rollback preview, rollback as a new version, `historical_restore` | Task 6 `S14`, `S15` | `#270` |

## Acceptance-criterion traceability

| AC | Proven by |
|---|---|
| AC1 (no code-owned defaults after v1; manifest is bootstrap input only) | Task 6 tripwire across the whole journey; Task 7 tripwire across graph turns; Task 12 structural guards |
| AC2 (every graph-capable creation path pins; each node resolves that release) | Task 6 `S12` (root, contributor, duplicate via HTTP); Task 8 (chat auto-created; missing-active refusal on all four); Task 7 (per-node identities) |
| AC3 (explicit failures preserve conversation state) | Task 8 |
| AC4 (historical bundles by version and digest) | Task 7 `S17` (a non-active v2-bundle release still executes; every persisted identity resolves); Task 12 retained-bundle ledger |
| AC5 (tool grants inert; no tools) | Task 7 (the recording adapter proves no `bind_tools`); Task 10 (no tool control in the workbench); Task 12 (`AgentDefinition.legacy_tool_grants` deleted; guard) |
| AC6 (admin-only; non-admin sees Graph Version only) | Task 9 |
| AC7 (multi-role edit → … → rollback → new version) | Task 6 |
| AC8 (release identity through state, fan-out and traces) | Task 7 |
| AC9 (Playwright for both journeys over published contracts) | Tasks 10, 11 |
| AC10 (delete only after green; one path) | Task 12 gate and guards |

## Review Focus

1. **A conversation created between preview and publish.** The user expects it to pin the *old* release, and one created after to pin the new one. Test: Task 6 `S12` creates `mid-root` after preview but before publish, and asserts it pins v1.
2. **An older conversation used after rollback.** A v2-pinned conversation keeps executing v2's exact revisions after v3 (restoring v1) is active, and is offered "Start latest" to v3. Tests: Task 7 `S16`, Task 11.
3. **A historical release whose bundles differ from the active one's.** v2 carries protected assembly v2 and schema contract v2; after rollback v3 carries the v1 bundles. Both must execute with their own bundles. Test: Task 7 `S17`.
4. **A failed turn after a successful one.** State must be unchanged: messages, checkpoint, deck rows, pin. Test: Task 8 compares a full-state snapshot before and after.
5. **A second admin tab submitting a stale publish or rollback.** The result must be an exact `409` naming the current version, and no new release. Tests: Task 6 `S11`/`S15`, Task 10.

---

## Task 0: Correct the plan against code; record cause baselines (phase A and phase B)

**Files (execution evidence; only `progress.md` is committed):**
- `.superpowers/sdd/2026-09-26-lakebase-contract-and-epic-acceptance/PLAN-CORRECTIONS.md`
- `.superpowers/sdd/2026-09-26-lakebase-contract-and-epic-acceptance/{TASK1_BASE,INTEGRATION_BASE,predecessor-heads.md}`
- `.superpowers/sdd/2026-09-26-lakebase-contract-and-epic-acceptance/reports/{preflight-A.md,preflight-B.md}`
- `.superpowers/sdd/2026-09-26-lakebase-contract-and-epic-acceptance/progress.md`

### Phase A (before Task 1, at the current integration head)

- [ ] **Step A1: Create the corrections file.** Its first line is exactly: `# PLAN-CORRECTIONS.md — this file overrides docs/superpowers/plans/2026-09-26-lakebase-contract-and-epic-acceptance.md wherever they differ.` Record `TASK1_BASE=$(git rev-parse HEAD)` and prove that `a08389ec3` is its ancestor.
- [ ] **Step A2: Re-verify every "Verified code facts" row and every removal-inventory row** with `rg -n` and file reads. Re-count R1–R6 callers with:

  ```bash
  rg -n "AgentRuntime\.compatibility\(|CompatibilityResolvedDefinitionLoader|CodeOwnedAgentDefinitionSource|TEST_COMPATIBILITY_GRAPH|_SchemaContractRegistry|StaticDefinitionSource|from src\.services\.agent_runtime import" -g '*.py' src scripts tests
  ```

  Any caller not in the inventory is a correction row and is added to Task 3's Files block.
- [ ] **Step A3: Search for any other compatibility path.**

  ```bash
  rg -n "fallback|compat|code.owned|legacy|DEFAULT_CONFIG\[.llm.\]|load_skill|load_graph_v1_manifest|agent_definition_manifest_v1" -g '*.py' src
  ```

  Classify each hit as runtime-definition source / bootstrap input / retained bundle / out of scope, and add it to the inventory with a reason.
- [ ] **Step A4: Phase A cause baseline.**
  1. Run `test ! -e .venv`.
  2. Run `DATABASE_URL=sqlite:////tmp/t271-A.sqlite PYTHONPATH=… <interpreter> -m pytest tests/unit -q -p no:randomly -rf`. Record every failing node id with its first causal assertion, and every skip with its reason.
  3. Expected: exactly the six P2 nodes. Anything else is a new cause.
  4. Run each `integration-graph` PostgreSQL file (listed in `.github/workflows/test.yml:448-472`) as its own command. Record the per-file pass count and zero skips.
  5. Run `test ! -e .venv`.
  6. Write the results to `reports/preflight-A.md`.
- [ ] **Step A5: Rule on the deploy baseline.** Record `test_deploy_autoscaling.py::TestGetOrCreateLakebase::{test_returns_autoscaling_when_available,test_falls_back_when_autoscaling_creation_fails}` as an **accepted, not-epic** baseline, with the `main` evidence (P2). Add a "for the user: file a GitHub issue" line to `progress.md`. #271 does not edit `deploy.py`.

### Phase B (after reviewed #268, #269, #270 are merged locally; before Task 2)

- [ ] **Step B1: Integration proof.**
  1. Re-resolve the final reviewed #268/#269/#270 heads and the local `feat/langgraph-core` merge commit.
  2. Record `INTEGRATION_BASE`, and write the heads to `predecessor-heads.md`.
  3. Prove each head is an ancestor of `INTEGRATION_BASE`.
  4. Rebase the Phase A commits above it.
  5. Prove `INTEGRATION_BASE..HEAD` is exactly the rebased Phase A commits.
- [ ] **Step B2: Re-probe every "Consumed interfaces" row** (C268-1 … C270-4) against the integrated code. For each row, record the exact:
  - route path and method;
  - request model class and its `extra` policy;
  - response model class and its key list;
  - status codes and error codes;
  - frontend client function names and `data-testid`s.

  Where a plan was silent, record what was built. A contradiction with this plan becomes a correction row that overrides the task that consumes it.
- [ ] **Step B3: Re-inventory R1–R7 after integration.** #268–#270 may have added compatibility callers (for example, a new test that uses `AgentRuntime.compatibility`). Add every new caller to Task 3.
- [ ] **Step B4: Re-derive the epic invariant owners.** For each invariant under "Global constraints", record the landed test that pins it (file::name). Examples: the single-binding test `tests/unit/test_agent_runtime.py::test_structured_output_binding_has_one_call_site_and_the_probe_has_none`; #270's `_assign_locked_candidate` one-writer test; #269/#270's one-reducer/one-gate tests. A missing owner test becomes a Task 12 addition.
- [ ] **Step B5: Re-measure the frontend tests typecheck** with P1's recipe against the integrated tree (#269 and #270 add specs). Record the exact error list for Task 4.
- [ ] **Step B6: Phase B cause baseline.** Repeat A4 at `INTEGRATION_BASE`. Also run:
  - every #268/#269/#270 PostgreSQL file, each with zero skips;
  - Vitest `src/components/Admin`;
  - `npm run typecheck`;
  - the Playwright specs `agent-definition-workbench`, `graph-release-review`, `graph-release-history`, `admin-route-gate`, `admin-page`, `conversation-graph-version` and `mixed-release-collaboration`.

  Record causes, not counts, in `reports/preflight-B.md`. Do not dispatch Task 2 until B1–B6 are complete.

---

## Task 1 (Phase A): Unit-suite database isolation, and the epic-caused style-exclusivity baseline

**Files:**
- Modify: `tests/conftest.py` (top of module, before the first `src` import)
- Create: `tests/unit/test_unit_suite_database_isolation.py`
- Modify: `tests/unit/test_style_exclusivity_chokepoint.py` (the `_FakeSession` fixture at `:62-83`, used by `:368` and the two tests after it)
- Modify: `tests/unit/test_style_exclusivity_persistence_boundary.py` (`:183-210`)

**Interfaces:**
- Produces: the environment variable `TELLR_TESTS_DATABASE_URL_DEFAULTED=1`, set when conftest supplied the SQLite default. Nothing in `src/` reads it.
- Consumes: `GraphConfiguration().bootstrap_v1(session_factory)` (#260).

- [ ] **Step 1: Write the RED tests.** `tests/unit/test_unit_suite_database_isolation.py`:

  ```python
  import os
  from pathlib import Path

  from src.core.database import _get_database_url


  def test_a_unit_run_never_resolves_the_operator_dev_database():
      url = _get_database_url()
      assert "ai_slide_generator" not in url, url
      if os.environ.get("TELLR_TESTS_DATABASE_URL_DEFAULTED") == "1":
          assert url.startswith("sqlite:///"), url


  def test_the_default_is_installed_before_any_src_import():
      text = Path(__file__).resolve().parents[1].joinpath("conftest.py").read_text()
      default_at = text.index('os.environ["DATABASE_URL"]')
      first_src_import = text.index("from src.")
      assert default_at < first_src_import
  ```

  Run it with `DATABASE_URL` **unset** (`env -u DATABASE_URL PYTHONPATH=… <interpreter> -m pytest -q tests/unit/test_unit_suite_database_isolation.py`). Expect RED: `ai_slide_generator` is in the URL, and the index lookup raises `ValueError`.

  The style tests are already RED (P2). Record their exact causes.
- [ ] **Step 2: Implement the conftest default** (before `from src.core.databricks_client import …`):

  ```python
  import tempfile

  if "DATABASE_URL" not in os.environ:
      # Unit runs must never reach the operator's dev database: with no URL and no
      # Lakebase environment, src/core/database.py resolves
      # postgresql://localhost/ai_slide_generator.  One directory per process, so
      # xdist workers never share a file.
      _UNIT_DB_DIR = tempfile.mkdtemp(prefix="tellr-tests-")
      os.environ["DATABASE_URL"] = f"sqlite:///{_UNIT_DB_DIR}/tellr-tests.sqlite"
      os.environ["TELLR_TESTS_DATABASE_URL_DEFAULTED"] = "1"
  elif "ai_slide_generator" in os.environ["DATABASE_URL"]:
      raise SystemExit("refusing to run tests against the ai_slide_generator dev database")
  ```

  Any test that deliberately unsets `DATABASE_URL` (via `monkeypatch.delenv`) to test `_get_database_url` keeps working: `monkeypatch` restores the variable afterwards. List such tests in the report.
- [ ] **Step 3: Fix the style fixtures.**
  - In `test_style_exclusivity_chokepoint.py`, replace `_FakeSession` with a real SQLite session. Build it from `create_engine("sqlite://", poolclass=StaticPool)` plus `Base.metadata.create_all`, followed by `GraphConfiguration().bootstrap_v1(sessionmaker(bind=engine))`.
  - In `test_style_exclusivity_persistence_boundary.py::test_session_manager_create_session`, call `GraphConfiguration().bootstrap_v1(session_local)` before `create_session`.
  - The assertions about normalisation stay byte-identical.
- [ ] **Step 4: GREEN.**
  1. Run `test ! -e .venv`.
  2. Run the new file both with `DATABASE_URL` unset and with `DATABASE_URL=sqlite:////tmp/t271-1.sqlite`.
  3. Run the two style files.
  4. Run the full unit suite with `DATABASE_URL` **unset** and with `-p no:randomly -rf`. The cause set must equal preflight-A **minus** the four style nodes: exactly the two deploy nodes.
  5. Run `test ! -e .venv`.
- [ ] **Step 5: Sabotage.**
  - **Controller:** delete the `os.environ["DATABASE_URL"] = …` line. Predicted RED: `test_a_unit_run_never_resolves_the_operator_dev_database` fails with `ai_slide_generator` in the URL.
  - **Reviewer:** drop the `bootstrap_v1` call from the persistence-boundary test. Predicted RED: `ConversationGraphReleaseIntegrityError: no active Graph Release`.
  - Restore each.
- [ ] **Step 6: Commit** (in its own command):

  ```bash
  git add tests/conftest.py tests/unit/test_unit_suite_database_isolation.py tests/unit/test_style_exclusivity_chokepoint.py tests/unit/test_style_exclusivity_persistence_boundary.py
  ```
  ```bash
  git commit -m "test: isolate unit runs from the dev database and pin style fixtures to Graph Version 1 (#271)" -m "Co-authored-by: Isaac <no-reply@databricks.com>"
  ```

## Task 2 (Phase B): A log-record rendering helper that cannot match file paths

**Files:**
- Create: `tests/fixtures/log_records.py`
- Create: `tests/unit/test_log_record_rendering.py`
- Modify: every site Task 0-B lists; at `a08389ec3` these are `tests/unit/test_persisted_agent_runtime.py:948`, `:1032` and `:1937`, and `tests/unit/test_agent_test_workbench.py:2003`, plus any #268–#270 addition found by `rg -n "vars\(record\)|record\.__dict__" tests`

**Interfaces:**
- Produces: `rendered_record(record: logging.LogRecord) -> str`, `STANDARD_LOG_RECORD_ATTRS: frozenset[str]`. Tasks 6–8 use both.

- [ ] **Step 1: RED test** in `tests/unit/test_log_record_rendering.py`:

  ```python
  import logging

  from tests.fixtures.log_records import rendered_record


  def _record(**extra):
      record = logging.LogRecord(
          "n", logging.INFO, "/private/tmp/agent_model_payload.py", 1, "persisted_agent_invocation", (), None
      )
      for key, value in extra.items():
          setattr(record, key, value)
      return record


  def test_path_attributes_never_reach_the_rendering():
      text = rendered_record(_record())
      assert "private" not in text and "payload" not in text


  def test_extras_message_args_and_exception_text_do_reach_it():
      record = _record(agent_key="architect")
      record.exc_text = "Traceback: secret-prompt"
      text = rendered_record(record)
      assert "architect" in text and "persisted_agent_invocation" in text and "secret-prompt" in text
  ```

  RED: the module does not exist.
- [ ] **Step 2: Implement** `tests/fixtures/log_records.py`:

  ```python
  import logging

  STANDARD_LOG_RECORD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


  def rendered_record(record: logging.LogRecord) -> str:
      """Everything a handler could emit for *record* except its source location."""
      extras = {k: v for k, v in vars(record).items() if k not in STANDARD_LOG_RECORD_ATTRS}
      parts = [record.getMessage(), repr(record.args), repr(extras)]
      if record.exc_info:
          parts.append(logging.Formatter().formatException(record.exc_info))
      if record.exc_text:
          parts.append(record.exc_text)
      return "\n".join(parts)
  ```

  Replace each listed `str(vars(record))` or `vars(record).items()` rendering with `rendered_record(record)`. Keep every needle, and keep every exact field-set assertion (`emitted_fields(record) == PERMITTED_LOG_FIELDS`) as it is.
- [ ] **Step 3: GREEN.** Run the new file and every modified file, with `DATABASE_URL=sqlite:////tmp/t271-2.sqlite`. Then run the same files from a worktree path under `/private/tmp` (for example `cp -R` of the tree to `/private/tmp/t271-path` and run there). They must pass there too. That is the case that used to false-positive.
- [ ] **Step 4: Sabotage.**
  - **Controller:** remove `"pathname"` from the exclusion set (write `STANDARD_LOG_RECORD_ATTRS - {"pathname"}`). Predicted RED: `test_path_attributes_never_reach_the_rendering`.
  - **Reviewer:** drop the `exc_text` branch. Predicted RED: `test_extras_message_args_and_exception_text_do_reach_it`.
- [ ] **Step 5: Commit** the helper, its test and the migrated files with `test: render log records without their source path (#271)`.

## Task 3 (Phase B): A test-only packaged-v1 loader; move every compatibility caller off it

**Files:**
- Create: `tests/fixtures/packaged_release_loader.py`
- Create: `tests/unit/test_packaged_release_loader.py`
- Modify:
  - `tests/unit/test_agent_runtime.py` (R1 ×9, R3, R4 `StaticDefinitionSource`, R5 imports and the `:254` / `:272` / `:306` tests);
  - `tests/unit/test_graph_configuration_bootstrap.py:414-416`;
  - `tests/unit/test_agent_resolution_prompt.py:76`;
  - `tests/unit/test_deck_level_spec_change.py:1026`, `:1085`;
  - `tests/unit/test_persisted_agent_runtime.py:1039-1062`;
  - `tests/unit/test_prompt_assembler.py:419-475`;
  - `tests/unit/test_agent_schema_registry.py:1319-1333`;
  - `tests/unit/test_graph_definition_manifest.py:266-283`;
  - every caller Task 0-B added.
- **Production files: none.** The compatibility code stays until Task 12.

**Interfaces:**
- Produces, in `tests/fixtures/packaged_release_loader.py`:

  ```python
  PACKAGED_RELEASE_ID: int = 1
  PACKAGED_GRAPH_VERSION: int = 1

  class PackagedGraphV1Loader:
      """Serves the packaged bootstrap manifest as ONE synthetic release, for unit tests only."""
      def __init__(self, *, graph_release_id: int = PACKAGED_RELEASE_ID,
                   graph_version: int = PACKAGED_GRAPH_VERSION,
                   content_overrides: Mapping[str, DefinitionContent] | None = None) -> None: ...
      def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition: ...

  def packaged_v1_runtime(*, model_adapter: AgentModelAdapter,
                          identity_sink: AgentInvocationIdentitySink | None = None,
                          content_overrides: Mapping[str, DefinitionContent] | None = None) -> AgentRuntime: ...
  ```

  - `resolve` raises `GraphReleaseNotFoundError(graph_release_id)` for any other id.
  - For an unknown role it raises `KeyError`. The runtime's own `UnknownAgentKeyError` check fires first.
  - `agent_definition_revision_id` equals `content.definition_version` (2). That is byte-parity with the retired loader, so diagnostics assertions are unchanged.
  - `content_hash = definition_content_hash(content)`.
  - `content_overrides` replaces the migration of `StaticDefinitionSource`: a test builds `load_graph_v1_manifest()`'s content, then `model_copy(update=…)`s a broken identity into it.
- Consumes: `load_graph_v1_manifest`, `definition_content_hash`, `ResolvedDefinition`, `GraphReleaseNotFoundError`, `AgentRuntime(...)`.

- [ ] **Step 1: RED tests** in `tests/unit/test_packaged_release_loader.py`:
  - All seven roles resolve with exact `graph_version == 1`, `graph_release_id == 1` and `agent_definition_revision_id == 2`.
  - The content hashes equal the literal `PACKAGED_V1_CONTENT_HASHES`. Copy that table from `test_graph_definition_manifest.py:745-751`; do not import it (epic C-24).
  - `resolve(2, "architect")` raises `GraphReleaseNotFoundError`.
  - An override for `architect` changes only architect.
  - **Parity:** for every role, and for `design_system_active ∈ {False, True}`, `packaged_v1_runtime(...).run(...)` produces a prompt, configuration and schema byte-identical to `AgentRuntime.compatibility(...).run(...)`. This comparison is possible now, and only now, because the compatibility code still exists. Task 12 deletes it together with the parity half of this test.
- [ ] **Step 2: RED run.** `DATABASE_URL=sqlite:////tmp/t271-3.sqlite PYTHONPATH=… <interpreter> -m pytest -q tests/unit/test_packaged_release_loader.py`. The failure must be the missing module.
- [ ] **Step 3: Implement the fixture, then migrate every caller mechanically.**
  - `AgentRuntime.compatibility(model_adapter=m)` → `packaged_v1_runtime(model_adapter=m)`.
  - `CodeOwnedAgentDefinitionSource().resolve(k)` + `replace(...)` → an override built from the manifest content.
  - `CompatibilityResolvedDefinitionLoader(...).resolve(TEST_COMPATIBILITY_GRAPH_RELEASE_ID, k).content` → `PackagedGraphV1Loader().resolve(1, k).content`. The expected `ValueError` becomes `GraphReleaseNotFoundError`.
  - `test_agent_runtime.py`: `_canonical_digest` and `_schema_contract_material` are imported from `src.services.agent_schema_registry`. `test_code_owned_contract_identities_are_stable_literals` becomes the identical literal assertion over `load_graph_v1_manifest().definitions` (it keeps checking the protected digest, the seven schema digests and `AssemblyRulesV1`).
  - `test_agent_schema_registry.py::test_runtime_and_registry_agree_on_identity_class_equality_and_isinstance` becomes a check that the registry's v1 identities equal the manifest's stored identities (`schema_contract_identity(role, content.schema_contract)`).
  - `test_graph_definition_manifest.py::test_packaged_v1_manifest_matches_exact_compatibility_definitions` compares the manifest with the **literals** it already pins (`PACKAGED_V1_CONTENT_HASHES`, `V1_SCHEMA_CONTRACT_DIGESTS`, protected digest `e4ff3d61…`) and with `load_skill(k).instructions` as a *test-side historical record*. It no longer uses `CodeOwnedAgentDefinitionSource`.
  - `_expected_prompt` in `test_agent_runtime.py:147` keeps `load_skill(...)`. It is test-side, and it is exactly the independent oracle that proves the persisted v1 equals the shipped v1.
- [ ] **Step 4: GREEN.**
  1. `test ! -e .venv`.
  2. Run the new file plus every modified file in one invocation with `DATABASE_URL=sqlite:////tmp/t271-3.sqlite`.
  3. Then `rg -n "AgentRuntime\.compatibility\(|CompatibilityResolvedDefinitionLoader|CodeOwnedAgentDefinitionSource|TEST_COMPATIBILITY_GRAPH|_SchemaContractRegistry|StaticDefinitionSource" tests scripts src`. The only hits allowed are `src/services/agent_runtime.py`, `scripts/generate_graph_definition_manifest_v1.py`, `tests/unit/test_graph_definition_manifest.py`'s generator tests (`:694-735`) and the parity test in `test_packaged_release_loader.py`.
  4. The full unit cause set must equal Task 1's.
  5. `test ! -e .venv`.
- [ ] **Step 5: Sabotage.**
  - **Controller:** make `PackagedGraphV1Loader.resolve` ignore `graph_release_id`. Predicted RED: the `GraphReleaseNotFoundError` test.
  - **Reviewer:** make it return `builder`'s content for `architect`. Predicted RED: the parity and hash tests.
- [ ] **Step 6: Commit** with `test: run runtime unit tests from the packaged manifest, not the compatibility loader (#271)`.

## Task 4 (Phase B): Typecheck `frontend/tests/`

**Files:**
- Create: `frontend/tsconfig.e2e.json`
- Modify: `frontend/tsconfig.json` (add the reference)
- Modify: the files Task 0-B5 lists; at P1 these are `tests/e2e/findings-drawer.spec.ts:87`, `tests/e2e/slide-viewer.spec.ts:14,33,46` and `tests/e2e/slide-surface-fidelity.spec.ts:1022,1070` (plus 4 more lines in the same file per the probe)
- Create: `frontend/tests/types/browser-modules.d.ts`
- Create: `tests/unit/test_frontend_tests_are_typechecked.py`

**Interfaces:** Produces the gate that Tasks 10–11 run: `npm run typecheck` now covers `tests/**/*.ts`.

- [ ] **Step 1: RED guard** `tests/unit/test_frontend_tests_are_typechecked.py`. It text-reads `frontend/tsconfig.json`, asserts that `{"path": "./tsconfig.e2e.json"}` is among its references, and asserts that `tsconfig.e2e.json`'s `include` covers `tests/**/*.ts`. RED: the file is missing.
- [ ] **Step 2: Implement `frontend/tsconfig.e2e.json`:**

  ```json
  {
    "compilerOptions": {
      "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.e2e.tsbuildinfo",
      "target": "ES2022",
      "lib": ["ES2022", "DOM", "DOM.Iterable"],
      "module": "ESNext",
      "moduleResolution": "bundler",
      "allowImportingTsExtensions": true,
      "verbatimModuleSyntax": true,
      "noEmit": true,
      "skipLibCheck": true,
      "strict": true,
      "jsx": "react-jsx",
      "types": ["node", "vite/client"],
      "paths": { "@/*": ["./src/*"] }
    },
    "include": ["tests/**/*.ts"]
  }
  ```

  - `tests/types/browser-modules.d.ts` declares `declare module '/src/*';` for the browser-side dynamic imports inside `page.evaluate`. Those are resolved by the Vite dev server, not by Node.
  - Fix the `findings-drawer.spec.ts:87` type error at its cause: pass the element, not the array. Do not add a cast.
  - Add `{ "path": "./tsconfig.e2e.json" }` to `tsconfig.json` `references`.
- [ ] **Step 3: GREEN.** `(cd frontend && npm run typecheck)` exits 0. `(cd frontend && npx eslint tests)` shows the same warning causes as preflight-B. The Python guard passes. The three edited specs pass under Playwright with `--project=chromium --workers=1`.
- [ ] **Step 4: Sabotage.**
  - **Controller:** re-introduce the array argument at `findings-drawer.spec.ts:87`. Predicted RED: `npm run typecheck` reports TS2740.
  - **Reviewer:** delete the reference from `tsconfig.json`. Predicted RED: the Python guard, while `npm run typecheck` goes silently green. That is exactly why the guard exists.
- [ ] **Step 5: Commit** with `build: typecheck the frontend test tree (#271)`.

## Task 5 (Phase A): Declare `openai` in both manifests

**Files:**
- Modify: `packages/databricks-tellr-app/pyproject.toml` (the `dependencies` array)
- Modify: `pyproject.toml` (the root `[project] dependencies`)
- Modify: `tests/unit/test_app_wheel_dependencies.py`

- [ ] **Step 1: RED test** in `tests/unit/test_app_wheel_dependencies.py`:

  ```python
  def test_the_app_wheel_declares_openai_within_the_transitive_bounds(app_deps, root_deps):
      """agent_runtime.py and model_endpoint_probe.py import openai at module level."""
      assert app_deps["openai"] == ">=1.99.9,<2.0.0"
      assert root_deps["openai"] == ">=1.99.9,<2.0.0"
  ```

  Adapt it to the file's existing `app_deps`/`root_deps` fixture shape, which Task 0 records. RED: `KeyError: 'openai'`.
- [ ] **Step 2: Implement.** Add `"openai>=1.99.9,<2.0.0",` to both arrays. Place it beside `httpx==0.28.1`, with a comment: the range is the intersection of `databricks-langchain` (`>=1.99.9`) and `langchain-openai` (`<2.0.0,>=1.99.9`), so the resolved closure is unchanged (1.105.0 in the dev env). Do **not** run a resolver or installer.
- [ ] **Step 3: GREEN.** Run the whole `test_app_wheel_dependencies.py`, including `test_no_root_runtime_dependency_is_silently_absent_from_the_app_wheel`.
- [ ] **Step 4: Sabotage.**
  - **Controller:** remove the app-manifest line. Predicted RED: the new test.
  - **Reviewer:** add `openai` only to the app wheel. Predicted RED: the new test's root assertion.
- [ ] **Step 5: Commit** with `build: declare openai, which the runtime imports directly (#271)`.

## Task 6 (Phase B): Staged lifecycle journey over real PostgreSQL and admin HTTP (AC7, AC1 tripwire)

**Files:**
- Create: `tests/integration/graph_lifecycle_journey.py` (helper module; not collected: no `test_` prefix)
- Create: `tests/integration/test_graph_lifecycle_acceptance_postgres.py`
- Create: `tests/unit/test_graph_lifecycle_stage_attribution.py`
- Modify: `.github/workflows/test.yml` (append the PostgreSQL file to `integration-graph`)

**Interfaces:**
- Consumes: C268-1, C268-2, C269-1, C270-1 and C270-2 (exact shapes per Task 0-B); `real_route_stack` recipe (`test_agent_definition_workbench_postgres.py:1284-1311`); `DeterministicFakeModelAdapter`; `FakeModelEndpointCatalog`; the sessions router (`src/api/routes/sessions.py`, prefix `/api/sessions`); `rendered_record` (Task 2).
- Produces:

  ```python
  @dataclass(frozen=True)
  class Stage:
      code: str        # "S11"
      name: str        # "publish"
      ticket: str      # "#269"
      seam: str        # "POST /api/admin/agent-definitions/releases"

  class StageFailure(AssertionError): ...

  @contextmanager
  def stage(current: Stage) -> Iterator[None]: ...
  def require(upstream: Stage, condition: bool, detail: str) -> None: ...

  class CodeDefaultTripwire:
      """After arm(), any read of a code-owned definition source or the bootstrap manifest raises."""
      reads: list[str]
      def arm(self, monkeypatch) -> None: ...

  @dataclass
  class LifecycleJourney:
      factory: sessionmaker
      admin: TestClient          # admin router, authorized principal
      user: TestClient           # sessions router, non-admin principal
      adapter: DeterministicFakeModelAdapter
      tripwire: CodeDefaultTripwire
      exchanges: list[RecordedExchange]   # every request/response, for Task 10
      state: dict[str, Any]              # ids produced by each stage
  ```

  `stage()` re-raises any exception as `StageFailure(f"[{ticket}] {code} {name} via {seam}: {type(exc).__name__}: {exc}")`, chained. `require(upstream, …)` raises `StageFailure` labelled with the **upstream** stage. Each stage opens by `require`-ing the exact output of the stage it consumes. So a failure is attributed to the stage that produced a wrong value, not to the one that noticed it.
- `CodeDefaultTripwire.arm` monkeypatches each of these to raise `AssertionError("code-owned definition read after Graph Version 1: <name>")` and to record the name:
  - `src.core.skills.load_skill`;
  - `src.services.graph_definition_manifest.load_graph_v1_manifest` (after `load_graph_v1_manifest.cache_clear()`), together with the module object `src.services.agent_definition_manifest_v1` in `sys.modules`;
  - until Task 12, `src.services.agent_runtime.CodeOwnedAgentDefinitionSource.resolve` and `CompatibilityResolvedDefinitionLoader.resolve`.

  **Before Task 12, Task 0-B checks each target by `rg`, because Task 12 removes the last two.** A tripwire read is re-raised by `stage()` with the prefix `[AC1/#271]`.

- [ ] **Step 1: RED unit test for attribution** (`tests/unit/test_graph_lifecycle_stage_attribution.py`, SQLite-free, pure):
  - an exception inside `stage(S11)` becomes a `StageFailure` whose message starts `[#269] S11 publish via POST`;
  - `require(S09, False, "…")` inside `stage(S10)` is labelled `[#268] S09`;
  - a tripwire read inside any stage is labelled `[AC1/#271]`;
  - a `StageFailure` passes through a nested `stage()` unchanged, so the inner label wins.
- [ ] **Step 2: RED PostgreSQL journey** `test_edit_test_approve_preview_publish_pin_rollback_lifecycle`, with `pytestmark = pytest.mark.postgres`.
  - **Fixture setup:** bootstrap v1, then `tripwire.arm()`. From here on, any manifest or `load_skill` read fails.
  - The admin client authorizes `lifecycle-admin@example.com` with the `real_route_stack` overrides. It adds `get_model_endpoint_catalog → FakeModelEndpointCatalog` seeded with `databricks-claude-opus-4-6` and `databricks-claude-sonnet-4-5`, and `get_agent_test_workbench →` a workbench whose runtime is `AgentRuntime(persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory), model_adapter=adapter, identity_sink=LoggingAgentInvocationIdentitySink(logger=…))`.
  - The user client includes the sessions router as a non-admin user.
  - Every exchange is recorded.
  - The stages run in order. Each assertion is exact: an identity, a key set or a status, never a count alone.

  | Stage | Ticket | Action (HTTP unless noted) | Exact assertions |
  |---|---|---|---|
  | S01 bootstrap | #260 | `GET /workbench` | v1 active; seven editable nodes in `GRAPH_V1_AGENT_KEYS` order; Foreman present, deterministic, not editable; draft `base == v1`, `lock_version = L0`; no node changed |
  | S02 old conversation | #261 | `POST /api/sessions` graph-capable as user (`old-root`) | response `graph_version == 1`, `is_older_than_active is False`; the DB pin equals the v1 id; the response has no key from `{graph_release_id, prompt_text, endpoint_name, content_hash}` |
  | S03 edit prompts and model | #263 | `PUT /draft/architect` (prompt `+ " Lifecycle A."`, `temperature 0.4`); `PUT /draft/builder` (prompt suffix); then a stale `PUT /draft/fixer` with `L0` | two 200s, lock `L0+1`, `L0+2`; the stale PUT is 409 `stale_draft` with an exact-seven server snapshot; fixer is unchanged in the DB |
  | S04 overlay | #264 | `POST /draft/builder/schema-contract-upgrade`, then `PUT /draft/builder` selecting `diagnostic_notes` | builder `schema_contract.version == 2` with the literal digest `65f29cb9…6aad`; overlay persisted; `candidate_hash` changed |
  | S05 assembly | #265 | `POST /draft/architect/protected-assembly-upgrade`, then `PUT` adding one custom block `always` after the authored prompt | architect `protected_assembly == (2, fb651a0d…592a)`; the custom block is persisted in order |
  | S06 endpoint | #266 | `GET /model-endpoints`; `PUT /draft/fixer` with `endpoint_name = "databricks-claude-sonnet-4-5"` | discovery lists the two fake names exactly; fixer stored with that exact name |
  | S07 test | #267 | `GET /test-cases?agent_key=…` for architect, builder and fixer; `POST /draft/{k}/test-runs` for each required case | each run `execution_status == completed` and `deterministic_checks_passed`; the candidate hash equals the draft's; the adapter's recorded prompt for architect equals the `assembled_prompt` in the evidence; no `persisted_agent_invocation` record carries `graph_release_id == -1` |
  | S08 approve | #268 | reject builder's run; approve architect's and fixer's; rerun builder and approve the rerun | the reject returns `verdict == "rejected"`; the approvals are exact; the reviewer is the admin principal |
  | S09 readiness | #268 | `GET /readiness` before the builder rerun approval, then after | before: exactly builder's case `awaiting_review` and every other changed case `approved`; after: all changed roles `approved`, and `draft_lock_version` is the current lock |
  | S10 preview | #269 | `GET /release-preview` | changed roles exactly `["architect","builder","fixer"]`; `next_version_number == 2`; `publishable is True`; the architect diff includes `prompt_text`, `model.temperature`, `protected_assembly` and `assembly_rules` fields (names per Task 0-B) |
  | S11 publish | #269 | `POST /api/sessions` (`mid-root`, **before** publishing); `POST /releases` with a stale lock; then with the current lock | `mid-root` pins v1; stale → 409 `stale_publication` naming v1; success 200: `version_number == 2`; mappings for data_analyst, build_reviewer, fix_reviewer and deck_reviewer are `reused: true` and equal v1's revision ids; the three changed roles map to new revisions; evidence run ids == {architect run, builder **rerun**, fixer run} |
  | S12 pinned conversations | #262 | `POST /api/sessions` (`new-root`); `POST /api/sessions/old-root/contribute`; `POST /api/sessions/old-root/duplicate`; `GET /api/sessions/old-root` | `new-root`, the contributor and the duplicate pin v2; `old-root` and `mid-root` still pin v1 with `is_older_than_active is True`; no pin changed in the DB (full `{session_id: graph_release_id}` map compared) |
  | S14 history | #270 | `GET /releases`; `GET /releases/1`; `GET /releases/1/comparison` | versions `[2, 1]`; v2 `previous == v1`; v1 detail lists seven definitions; the comparison marks exactly the three changed roles `same_revision: false` |
  | S15 rollback | #270 | `GET /releases/1/rollback-preview`; `POST /releases/1/rollback` with a stale lock, then with the preview's lock | preview: `next_version_number == 3`, `restorable`, `draft_effect` is `reset` for the three roles (clean after publish) and `unchanged` for the rest; stale → 409 `stale_rollback`; success: `version_number == 3`, `restored_from == v1`, all seven mappings `reused: true` and equal to **v1's** revision ids; evidence kinds all `historical_restore`, with `source_release_id == v1` |
  | S16 post-rollback pins | #270 / #261 | `POST /api/sessions` (`post-rollback-root`); `GET /api/sessions/new-root` | `post-rollback-root` pins v3; `new-root` still pins v2 with `is_older_than_active is True`; `old-root` still v1 |
  | S18 closing checks | #271 | DB read | exactly one active release (v3); intervals contiguous `v1.to == v2.from`, `v2.to == v3.from`; version numbers `{1,2,3}`, never reused; `tripwire.reads == []` |

  S13 and S17 are the graph-turn stages. They live in Task 7's file, so this file's journey has no model-driven graph turn. The journey helper exposes `run_to(stage_code)` so Task 7 can reuse it without copying.
- [ ] **Step 3: Run RED.** Expect the attribution unit test to fail on a missing module. The PostgreSQL file should fail only on the missing helper. If any stage fails on integrated code, that is a **predecessor defect**: record it in corrections, labelled with its ticket, and route the fix to that ticket's owner. Never fix a predecessor's production code in #271 without a corrections row approved by the controller.
- [ ] **Step 4: Implement the helper** so it is exactly the interfaces above. Stage bodies call only HTTP, except S18 and pin reads, which use the DB. Record every exchange as `RecordedExchange(id: str, method: str, path: str, request: JsonValue | None, status: int, body: JsonValue)`, with the stage code in `id`.
- [ ] **Step 5: GREEN.**
  1. `test ! -e .venv`.
  2. Run the unit file.
  3. Run `TELLR_TEST_POSTGRES_URL=… -m pytest -q -rs tests/integration/test_graph_lifecycle_acceptance_postgres.py`: zero skips.
  4. Run every #269/#270 PostgreSQL acceptance file, one command each: zero skips.
  5. Run `tests/unit/test_ci_collects_integration_tests.py` after the workflow edit.
  6. `test ! -e .venv`.
- [ ] **Step 6: Sabotage.** Both must go RED **with the right label**; paste the first line.
  - **Controller:** in #269's preview diff (`definition_field_diffs`, or the name Task 0-B recorded), drop the `prompt_text` field. Predicted RED: `[#269] S10 preview`.
  - **Reviewer:** in #270's `restore_release`, pass `restored_from_release_id=None` to `_commit_locked_publication`. Predicted RED: `[#270] S15 rollback`.
- [ ] **Step 7: Commit** the helper, both test files and the workflow with `test: staged edit-to-rollback lifecycle acceptance over admin HTTP (#271)`.

## Task 7 (Phase B): Release identity through the shipped graph-mode seam, across three releases (AC8, AC4, AC5)

**Files:**
- Create: `tests/integration/test_graph_lifecycle_runtime_postgres.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:**
- Consumes: Task 6's `LifecycleJourney.run_to("S16")`. Also the `graph_chat_env` patch recipe (`tests/integration/test_graph_mode_turn.py:342-420`), adapted to the PostgreSQL factory. Also `ChatService.send_message_streaming(..., engine_mode="graph")`, `routers.Send` recording (`test_conversation_pin_acceptance_postgres.py:426-432`), `_first_turn_outputs` (`test_conversation_pin_acceptance_postgres.py`, importing the underscore names only), and `LoggingAgentInvocationIdentitySink`.
- Produces: stage codes `S13` (turns on v1 and v2 pins) and `S17` (historical bundles), both labelled via Task 6's `stage()`.

- [ ] **Step 1: RED test** `test_every_pinned_release_drives_its_own_revisions_through_state_fan_out_and_traces`.
  1. Run the journey to S16, so v1, v2 and v3 exist (v3 restores v1).
  2. With the tripwire still armed, patch `src.services.graph.nodes.get_agent_runtime` to an `AgentRuntime` over `PersistedGraphReleaseLoader(session_factory=factory)`, an ordered recording adapter (A1 roles, see `test_conversation_pin_acceptance_postgres.py:60-72`), and a `LoggingAgentInvocationIdentitySink` whose records `caplog` captures.
  3. Drive one first turn per conversation through `send_message_streaming` with `"USE AGENT MODE build a deck"`, for `old-root` (v1), `new-root` (v2) and `post-rollback-root` (v3). Before each turn, seed `graph_release_id` in the graph input to a **different** release; the builder must overwrite it.
  4. For each turn:
     - **(state)** the final checkpoint's `graph_release_id` equals the pin;
     - **(fan-out)** every recorded `Send` payload to `builder` and `build_reviewer` carries the pin;
     - **(resolution)** every production log record `persisted_agent_invocation` for the turn has `graph_release_id == pin`, `graph_version ∈ {1, 2, 3}` exactly per conversation, and `agent_definition_revision_id` and `content_hash` equal to the release mapping read from the DB for that `agent_key`. For v3, those are **v1's** revision ids with `graph_version == 3`;
     - **(log contract)** every record's extra-field set is exactly the allow-list (Task 2's `STANDARD_LOG_RECORD_ATTRS` is excluded); `additional_field_names` is a list of names (v2 builder: `["diagnostic_notes"]` when the fake supplies it); `rendered_record(record)` contains none of the fake outputs' prose strings and none of the session ids;
     - **(no identifiers to the model)** no adapter prompt contains any session id (`old-root`, `new-root`, `post-rollback-root`), the admin or user principal, the turn id read from the checkpoint, or any of the key names `graph_release_id`, `session_id`, `turn_id`, `initiated_by`, `root_session_id`, `actor_session_id`;
     - **(no tools, AC5)** the recording adapter asserts that `bind_tools` is never reached (use the `ChatModel` double pattern from `test_agent_runtime.py:379-430` inside the adapter);
     - **(no fabricated ids)** no record has `graph_release_id ∉ {v1, v2, v3}`.
- [ ] **Step 2: RED test `S17`**, `test_every_readable_release_executes_with_its_own_bundles_after_it_stops_being_active`.
  - Inside `stage(S17)`: for every `agent_definition_revision` row, `PromptAssembler().resolve_bundle(ContentIdentity(version, digest))` and `AgentSchemaRegistry()`'s resolution of `(agent_key, schema_contract)` both succeed.
  - v2 (now **non-active**) holds architect on protected v2 and builder on schema v2, and its turn from Step 1 bound builder's **composed** v2 schema (`diagnostic_notes ∈ schema.model_fields`).
  - v3's builder bound the v1 schema (no `diagnostic_notes`).
- [ ] **Step 3: Implement** the test file only; no production change is expected. A failing assertion is a predecessor defect: record it, label it, route it.
- [ ] **Step 4: GREEN.** Run this file with zero skips, and `test_conversation_pin_acceptance_postgres.py` and `test_persisted_graph_runtime_failures_postgres.py` unchanged. Run the CI guard.
- [ ] **Step 5: Sabotage.**
  - **Controller:** in `src/services/graph/builder.py:345`, replace the `pin_loader(...)` result with the active release id (a one-line override). Predicted RED: `[#261] S13` on `old-root`'s identities (v3 instead of v1).
  - **Reviewer:** remove `"graph_version"` from `_LOGGED_IDENTITY_FIELDS` (`agent_runtime_identity.py:124`). Predicted RED: the trace assertion.
- [ ] **Step 6: Commit** with `test: prove pinned release identity through graph state, fan-out and traces across three releases (#271)`.

## Task 8 (Phase B): Explicit failures that preserve conversation state; every creator needs a pin (AC3, AC2)

**Files:**
- Create: `tests/integration/test_lakebase_contract_failures_postgres.py`
- Modify: `.github/workflows/test.yml`

**Interfaces:**
- Consumes: Task 6's journey (`run_to("S12")`), Task 7's turn driver, and the `graph_chat_env` recipe.
- Produces: `_conversation_state(factory, session_id) -> dict`. It captures the message rows (id, role, content hash), the latest checkpoint id, deck and slide rows (ids, content hash), the pin, and `graph_draft.lock_version`.

- [ ] **Step 1: RED tests.** Each one, parametrized where noted:
  - **missing active release at creation** (`test_every_graph_capable_creator_refuses_without_an_active_release`), parametrized over root / chat auto-created / contributor / duplicate. It uses a fresh database where bootstrap never ran, except for a legacy source session for contributor and duplicate. Expected: an explicit error (the exact status and error family per Task 0-B's re-probe of #261/#262), **no** new `user_sessions` row, and the tripwire unread.
  - **missing pinned release at invocation:** the loader raises `GraphReleaseNotFoundError` (a patched loader). The pin is non-null by FK, so this simulates a lost release row. Expected: the safe graph error event, and `_conversation_state` equal before and after.
  - **Lakebase unavailable:** the loader session factory raises `OperationalError`. Expected: code `lakebase_unavailable`, no active-release query attempted (a statement spy), state unchanged.
  - **removed endpoint:** the adapter raises `ModelProviderUnavailableError` for fixer's exact endpoint. Expected: `PinnedInvocationEndpointError` with `endpoint_name == "databricks-claude-sonnet-4-5"` and the v2 release id, attempted exactly once, state unchanged.
  - **unavailable historical bundle:** `PromptAssembler._bundles` is patched to drop `(2, fb651a0d…)` for a `new-root` (v2) turn. Expected: code `protected_bundle_unavailable`, no substitution by v1 (the adapter is never called), state unchanged. The same for the schema v2 bundle: code `schema_contract_unavailable`.
  - **legacy null-pin conversation:** a no-graph session stays null and runs no graph turn (`ConversationPinMissingError` path). It is never pinned to the active release.
- [ ] **Step 2: RED run**, then implement (tests only).
- [ ] **Step 3: GREEN.** Zero skips; the CI guard.
- [ ] **Step 4: Sabotage.**
  - **Controller:** make `load_conversation_pin` (`conversation_pins.py:151-160`) return the active release when the pin is null. Predicted RED: the legacy null-pin test.
  - **Reviewer:** in `AgentRuntime.run`'s `SQLAlchemyError` branch, retry via `get_agent_runtime()`'s active release (any code that queries `graph_release WHERE effective_to IS NULL`). Predicted RED: the Lakebase-unavailable statement spy.
- [ ] **Step 5: Commit** with `test: explicit Lakebase-contract failures preserve conversation state (#271)`.

## Task 9 (Phase B): Admin authorization inventory; non-admin conversations expose Graph Version only (AC6)

**Files:**
- Create: `tests/unit/test_admin_route_authorization_inventory.py`
- Create: `tests/unit/test_conversation_graph_version_projection.py`

**Interfaces:**
- Consumes: `src.api.main.app` routes; `require_admin`, `require_draft_write_principal`; the non-admin fixtures of `tests/unit/test_agent_definition_workbench_routes.py:398-440`.
- Produces: `EXPECTED_ADMIN_ROUTES: frozenset[tuple[str, str]]`. It is a literal set that Task 0-B fills from the integrated app: #260–#267's routes as listed under "Verified code facts", plus C268-1/C268-2, C269-1 and C270-1.

- [ ] **Step 1: RED tests.**
  - Every `(method, path)` in `app.routes` whose path starts with `/api/admin/agent-definitions` equals `EXPECTED_ADMIN_ROUTES`, exactly. A new route must be enrolled.
  - Every such route declares `require_admin` in its dependant tree (walk `route.dependant.dependencies`).
  - Exactly one `APIRouter` object in `app.routes` owns that prefix. Group by `route.endpoint.__module__` and the router's identity, as Task 0-B records it after #269 C31.
  - For each route, a non-admin call with a body of `{"lock_version": 0}` (or none) returns 403. The response body contains none of the prompt texts from `load_graph_v1_manifest()` (loaded **before** the call), and none of the strings `endpoint_name` or `content_hash`. A spy on `GraphConfiguration` and `AgentTestWorkbench` records zero calls. `request.json` is never awaited (patch `Request.json` to raise).
  - `test_conversation_graph_version_projection.py`: for `POST /api/sessions`, `GET /api/sessions`, `GET /api/sessions/{id}`, `POST /{id}/duplicate`, `POST /{id}/contribute` and `GET /{id}/collaboration-history`, the union of all JSON keys (recursively) contains `graph_version`, `active_graph_version` and `is_older_than_active`, and none of `{graph_release_id, agent_definition_revision_id, content_hash, prompt_text, endpoint_name, schema_overlay, assembly_rules, release_note, published_by}`. The exact key names are per Task 0-B's re-probe of #262's history body.
- [ ] **Step 2: RED run** with `DATABASE_URL=sqlite:////tmp/t271-9.sqlite`, then implement (tests only).
- [ ] **Step 3: GREEN.**
- [ ] **Step 4: Sabotage.**
  - **Controller:** remove `dependencies=[Depends(require_admin)]` from the admin router. Predicted RED: the dependant-tree and 403 checks.
  - **Reviewer:** add `"graph_release_id": pin` to `session_manager.create_session`'s returned dict. Predicted RED: the projection test.
- [ ] **Step 5: Commit** with `test: inventory every admin route's authorization and the non-admin projection (#271)`.

## Task 10 (Phase B): Contract-recorded fixtures and the administrator Playwright journey (AC9)

**Files:**
- Create: `frontend/tests/fixtures/graphLifecycleContract.json` (recorded; see Step 2)
- Create: `frontend/tests/fixtures/graphLifecycleContract.ts` (a typed loader and a `page.route` installer)
- Create: `frontend/tests/e2e/graph-release-admin-journey.spec.ts`
- Create: `tests/unit/test_graph_lifecycle_playwright_contract.py`
- Modify: `tests/integration/graph_lifecycle_journey.py` (add the `write_contract(path)` entry point)
- Modify: `.github/workflows/test.yml` (add `graph-release-admin-journey` to the `e2e` matrix)

**Interfaces:**
- The contract file is `{"contract_version": 1, "recorded_at_commit": "<sha>", "exchanges": [{"id", "method", "path", "request", "status", "body", "response_model", "request_model"}]}`.
  - `response_model` and `request_model` are dotted class paths, for example `src.api.schemas.agent_definitions.GraphWorkbenchResponse`, or `null` for bodies with no model.
  - The class paths for #268–#270 are recorded at Task 0-B.
- `graphLifecycleContract.ts` exports:
  - `loadContract(): LifecycleContract`, which reads the JSON with `readFileSync` and `JSON.parse`, so no `resolveJsonModule` is needed;
  - `installContract(page, ids: readonly string[]): Promise<RecordedRequests>`, which serves exactly the named exchanges by method and path, fails the test on any unmatched `/api/**` request, and records request bodies.

- [ ] **Step 1: RED Python join** `test_graph_lifecycle_playwright_contract.py`:
  - each exchange's `body` passes `model_validate` for its `response_model` (strict; `extra="forbid"` models reject drift);
  - each `request` passes its `request_model`;
  - the `id` set equals a literal list: the admin-journey ids and the conversation ids used by Task 11;
  - `recorded_at_commit` is an ancestor of `HEAD` (`git merge-base --is-ancestor`).

  RED: the file is missing.
- [ ] **Step 2: Record the contract.**
  - `write_contract(path)` runs the Task 6 journey against a throwaway PostgreSQL database and writes the recorded exchanges, sorted by stage.
  - Command: `TELLR_TEST_POSTGRES_URL=… PYTHONPATH=… <interpreter> -m tests.integration.graph_lifecycle_journey --write-contract frontend/tests/fixtures/graphLifecycleContract.json`.
  - It is a developer command, never run by a test. Commit its output unedited.
  - Then extend Task 6's PostgreSQL test: it asserts that a fresh recording's **shape** equals the checked-in file's shape. Shape means the recursive key structure and the status codes, ignoring ids and timestamps. So backend wire drift REDs in Python, and front-end drift REDs in Playwright.
- [ ] **Step 3: RED Playwright** `graph-release-admin-journey.spec.ts`. One `test.describe.serial` journey, with admin identity mocked as in `admin-route-gate.spec.ts`. Every `getByRole` passes `exact: true`. The steps:
  1. Open `/admin/agent-definitions`. Seven roles and a read-only Foreman are visible. `forbidsActionName` holds for every workbench control (reuse the sweep helper from `agent-definition-workbench.spec.ts`). No control's accessible name matches `/\btools?\b/i` (AC5).
  2. Edit the architect prompt, then `Save Draft`. The recorded PUT body deep-equals exchange `S03-put-architect.request`. Then a stale save → the 409 recovery UI (`Reload server` / `Keep local`).
  3. Upgrade the builder schema and select `diagnostic_notes`. Upgrade the architect's protected assembly and add a custom block.
  4. Select the fixer endpoint from `Refresh models`.
  5. `Run test case` for each changed role. `Reject run` on builder's run, then `Run test case` again and `Approve run`. Status badges move Needs test → Awaiting review → Approved (per C268-4).
  6. `Review & Publish` opens `/admin/agent-definitions/review`: `release-next-version` shows 2, the diff tab shows `prompt_text`, the note is typed, and a stale publish shows `release-stale-alert`. The success path shows `release-success-panel`. The POST body deep-equals `S11-publish.request`.
  7. Open the `Release History` tab. Within `release-history-row-1`, `Inspect this version`, then `Roll back to this version`. `rollback-preview` shows the lineage. `Confirm rollback` sends a POST body equal to `S15-rollback.request`, and `rollback-success-panel` shows Graph Version 3 restoring 1.
  8. The recorded request sequence equals the contract's admin-journey id order: no extra and no missing `/api` call.
- [ ] **Step 4: GREEN.**
  1. Run the Python join with `DATABASE_URL=sqlite:////tmp/t271-10.sqlite`.
  2. `(cd frontend && npm run typecheck)`: the spec is typechecked now (Task 4).
  3. `(cd frontend && npx eslint tests/e2e/graph-release-admin-journey.spec.ts tests/fixtures/graphLifecycleContract.ts)`.
  4. Run the Playwright spec with `--project=chromium --workers=1`. Also run `agent-definition-workbench`, `graph-release-review`, `graph-release-history` and `admin-route-gate`, each unchanged.
  5. Run `tests/unit/test_e2e_matrix_covers_specs.py`.
- [ ] **Step 5: Sabotage.**
  - **Controller:** rename `lock_version` to `lockVersion` in one recorded request inside the JSON. Predicted RED: the Python join, because the request model forbids extras and requires `lock_version`.
  - **Reviewer:** change the page's publish control accessible name from `Publish Graph Version` (the exact name per Task 0-B) to `Publish`. Predicted RED: the exact-name locator.
- [ ] **Step 6: Commit** with `test: administrator Playwright journey over the recorded HTTP contract (#271)`.

## Task 11 (Phase B): The conversation-user Playwright journey (AC9)

**Files:**
- Create: `frontend/tests/e2e/graph-release-conversation-journey.spec.ts`
- Modify: `.github/workflows/test.yml` (`e2e` matrix)

**Interfaces:**
- Consumes: `graphLifecycleContract.ts` (Task 10), the exchanges `S02-*`, `S11-mid-root`, `S12-*` and `S16-*`, and the existing chat-turn mocks in `frontend/tests/fixtures/mocks.ts`. Their exact helper names are per Task 0-B; `mocks.ts` itself is not edited.
- Existing names reused: `data-testid` `graph-version-status`, `mixed-release-warning`, `mixed-release-warning-text`; button `Start latest`; button `New Deck`; `chat-input`.

- [ ] **Step 1: RED Playwright**, run as a non-admin user.
  1. Open `old-root` after S16. `graph-version-status` contains `Pinned Graph Version 1; latest is 3`. Click `Start latest` (`exact: true`). Exactly one `POST /api/sessions` fires, **no** PATCH or PUT to `old-root`, and the new conversation shows `Pinned Graph Version 3`.
  2. Open `new-root` (v2). It shows `Pinned Graph Version 2; latest is 3`, and it is not mutated.
  3. Open the shared `old-root` deck with the v2 contributor. `mixed-release-warning` is visible and names both versions.
  4. Navigate to `/admin/agent-definitions` as non-admin. The user is redirected with no admin content flash. The recorded requests contain **no** `/api/admin/` URL, and no response body in the conversation exchanges contains `prompt_text`, `endpoint_name` or `content_hash` (AC6, user side).
  5. Send `USE AGENT MODE …` in the v3 conversation. The request carries no release id (the body keys are asserted against the chat request shape).
- [ ] **Step 2: GREEN.** `npm run typecheck`; ESLint on the spec; this spec plus `conversation-graph-version` and `mixed-release-collaboration`, each `--project=chromium --workers=1`; the matrix guard.
- [ ] **Step 3: Sabotage.**
  - **Controller:** render `active_graph_version` in `graph-version-status` instead of `graph_version`. The component is whichever file renders that test id; Task 0-B records it. Predicted RED: step 1's text.
  - **Reviewer:** make `Start latest` PATCH the current session before creating. Predicted RED: the zero-mutation assertion.
- [ ] **Step 4: Commit** with `test: conversation-user Playwright journey across three Graph Versions (#271)`.

## Task 12 (Phase B): Delete the compatibility runtime; guard the Lakebase-only contract (AC1, AC5, AC10)

**Files:**
- Modify: `src/services/agent_runtime.py` (delete R1–R5 and R7; replace `_SCHEMA_CONTRACT_VERSION` at `:1018`)
- Delete: `scripts/generate_graph_definition_manifest_v1.py`
- Modify:
  - `tests/unit/test_graph_definition_manifest.py` (delete `:266-283`'s remaining compatibility references and the three generator tests `:694-735`, with their `build_manifest_json` / `render_manifest_module` imports);
  - `tests/unit/test_packaged_release_loader.py` (delete the parity half that used `AgentRuntime.compatibility`);
  - `tests/integration/graph_lifecycle_journey.py` (the tripwire drops the two deleted targets).
- Create: `tests/unit/test_lakebase_only_runtime_contract.py`
- Create: `tests/unit/test_retained_bundle_ledger.py`
- Do **not** edit `src/services/agent_definition_manifest_v1.py`. Its bytes are the frozen v1.

**Interfaces:**
- After this task, `src.services.agent_runtime` exports **none** of `CodeOwnedAgentDefinitionSource`, `CompatibilityResolvedDefinitionLoader`, `AgentDefinitionSource`, `AgentDefinition`, `TEST_COMPATIBILITY_GRAPH_RELEASE_ID`, `TEST_COMPATIBILITY_GRAPH_VERSION` or `RuntimeContractIdentityError`, and `AgentRuntime` has no `compatibility` attribute.
- It keeps `ProtectedPromptIdentity`, `IncompatibleSchemaContractError`, `AgentModelConfiguration`, `AgentAssemblyContext`, `AgentInvocationResult`, `AgentInvocationDiagnostics` and every #266/#267 name.

- [ ] **Step 1: AC10 gate. Refuse to start unless the lifecycle suite is green.**
  1. At `TASK_BASE`, run Tasks 6–11's files: each PostgreSQL file (zero skips), both Playwright journeys, and the Python join.
  2. Record the outputs and the SHA in `reports/task12-gate.md`.
  3. Any RED or skip stops the task.
- [ ] **Step 2: RED guards.** `tests/unit/test_lakebase_only_runtime_contract.py`:

  ```python
  import ast
  import pathlib

  import src.services.agent_runtime as runtime_module
  from src.services.agent_runtime import AgentRuntime

  _SRC = pathlib.Path(runtime_module.__file__).resolve().parents[1]
  _RETIRED = {
      "CodeOwnedAgentDefinitionSource", "CompatibilityResolvedDefinitionLoader",
      "AgentDefinitionSource", "AgentDefinition", "TEST_COMPATIBILITY_GRAPH_RELEASE_ID",
      "TEST_COMPATIBILITY_GRAPH_VERSION", "RuntimeContractIdentityError",
  }


  def _imports(path):
      tree = ast.parse(path.read_text(encoding="utf-8"))
      for node in ast.walk(tree):
          if isinstance(node, ast.ImportFrom) and node.module:
              yield node.module, {alias.name for alias in node.names}
          elif isinstance(node, ast.Import):
              for alias in node.names:
                  yield alias.name, set()


  def test_the_compatibility_runtime_is_gone():
      assert not hasattr(AgentRuntime, "compatibility")
      assert _RETIRED.isdisjoint(vars(runtime_module))


  def test_no_src_module_reads_code_owned_agent_definitions():
      offenders = []
      for path in _SRC.rglob("*.py"):
          for module, names in _imports(path):
              if module == "src.core.skills" and "load_skill" in names:
                  offenders.append(path.relative_to(_SRC).as_posix())
      assert offenders == []


  def test_the_bootstrap_manifest_is_read_only_by_bootstrap():
      readers = set()
      for path in _SRC.rglob("*.py"):
          text = path.read_text(encoding="utf-8")
          if "load_graph_v1_manifest" in text or "agent_definition_manifest_v1" in text:
              readers.add(path.relative_to(_SRC).as_posix())
      assert readers == {
          "services/graph_definition_manifest.py",
          "services/graph_configuration_bootstrap.py",
          "services/agent_definition_manifest_v1.py",
      }


  def test_the_runtime_module_reads_no_code_default_model_configuration():
      text = pathlib.Path(runtime_module.__file__).read_text(encoding="utf-8")
      assert "DEFAULT_CONFIG" not in text and "tool_grants" not in text


  def test_production_runtimes_resolve_only_persisted_releases():
      from src.services.agent_runtime import get_agent_runtime, get_agent_test_runtime
      from src.services.persisted_graph_release import PersistedGraphReleaseLoader

      for factory in (get_agent_runtime, get_agent_test_runtime):
          factory.cache_clear()
          assert type(factory()._persisted_release_loader) is PersistedGraphReleaseLoader
          factory.cache_clear()
  ```

  `tests/unit/test_retained_bundle_ledger.py` pins, as **literals**, the full retained identity ledger:
  - protected assembly `{(1, "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852"), (2, "fb651a0d28276a0daf7b0db09f2648eb6b50d9429a7100cfaf69e3fc2b08592a")}`;
  - schema contract v1 and v2 for all seven roles: v1 per `V1_SCHEMA_CONTRACT_DIGESTS` in `test_graph_definition_manifest.py:754`; v2 architect `a03aefb1…4122`, data_analyst `0543006d…b6c5`, builder `65f29cb9…6aad`, build_reviewer `20f69d5e…c6b1`, fixer `a77a9896…6143`, fix_reviewer `bbe6bf02…fd99`, deck_reviewer `c466043b…04d3`. Write the full 64-hex literals, as re-read at Task 0-B.

  It asserts that each identity resolves (`PromptAssembler().resolve_bundle`, and `AgentSchemaRegistry()`'s resolution), and that the resolvable set **is a superset of** the ledger. Removing a bundle REDs; adding one does not, but its identity must then be appended.

  RED: the first and fourth guards fail on the present compatibility code.
- [ ] **Step 3: Implement the deletion.**
  - Delete R1–R5 and R7 from `agent_runtime.py`.
  - Replace `_SCHEMA_CONTRACT_VERSION` at `:1018` with the registry's v1 identity check. Use the name Task 0 records (for example `schema_identity == V1_SCHEMA_IDENTITIES[definition.agent_key]`); if the registry has no such name, a local `_SCHEMA_CONTRACT_V1 = 1` with a comment.
  - Rewrite the module docstring: it resolves only persisted Graph Releases, and Foreman is absent.
  - Delete the generator script and its tests.
  - Drop the tripwire's two retired targets. The structural guards now make them unreachable.
  - Run `rg -n "CodeOwnedAgentDefinitionSource|CompatibilityResolvedDefinitionLoader|AgentRuntime\.compatibility|TEST_COMPATIBILITY_GRAPH|_SchemaContractRegistry|generate_graph_definition_manifest_v1" .`. It must be empty outside `docs/` and `.superpowers/`. Update `docs/technical/` only where a document names the retired path; Task 0-B lists them.
- [ ] **Step 4: GREEN (whole contract).**
  1. `test ! -e .venv`.
  2. The full unit suite (`DATABASE_URL` unset now that Task 1 is in): cause set equals the Task 1 baseline (two deploy nodes).
  3. Every PostgreSQL file in `integration-graph`, one command each, zero skips.
  4. Both Playwright journeys.
  5. `test ! -e .venv`.
- [ ] **Step 5: Sabotage.**
  - **Controller:** add `from src.core.skills import load_skill` and one call inside `PersistedGraphReleaseLoader._load_complete_release`. Predicted RED: `test_no_src_module_reads_code_owned_agent_definitions` **and** the Task 6/7 tripwire labelled `[AC1/#271]`.
  - **Reviewer:** delete the v1 entry from `_default_bundles()`. Predicted RED: `test_retained_bundle_ledger.py`, and Task 7's `S17` on `old-root`.
- [ ] **Step 6: Commit** with `refactor: delete the compatibility runtime; Lakebase releases are the only definition source (#271)`.

## Task 13 (conditional release gate): Pay-per-token endpoint readiness (#266 m9)

**Runs only with explicit user authorisation.** It reads an external workspace. Without authorisation, record "m9 open: release gate unverified" in `progress.md` and the final report. The local merge may proceed; the epic may not be declared shippable.

**Files (only if the "absent" branch is taken):**
- Modify: `src/services/model_endpoint_catalog.py:262-270`
- Modify: its unit test file (Task 0 records the name)

- [ ] **Step 1: Probe.** Using the `deploy-tellr-dev` skill's profile `tellr-dev`, read-only, run `databricks serving-endpoints get databricks-claude-opus-4-6 --profile tellr-dev -o json`. Record whether `config_update` is present and its value. No write, no deploy.
- [ ] **Step 2a (present and `NOT_UPDATING`):** record the evidence and close m9. No code change.
- [ ] **Step 2b (absent):**
  - RED unit test: a `get` result with no `config_update` key is `ready`.
  - Implement: treat an absent `config_update` as not-updating, and keep every present non-`NOT_UPDATING` value refused.
  - Sabotage (controller): restore the strict check → RED. Reviewer: treat `IN_PROGRESS` as ready → RED on the existing refusal test.
  - Commit `fix: accept pay-per-token endpoints that report no config update (#271, #266 m9)`.

## Task 14: Whole-branch verification matrix, whole-branch and epic-level review, local merge

- [ ] **Step 1: Backend unit matrix.** Run `test ! -e .venv`, then the full suite with `DATABASE_URL` unset. Compare by node id and cause against Task 1's baseline: only the two accepted deploy nodes may fail. Then run these focused files once more, explicitly:

  ```bash
  PYTHONPATH=$PWD:$PWD/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly \
    tests/unit/test_lakebase_only_runtime_contract.py tests/unit/test_retained_bundle_ledger.py \
    tests/unit/test_packaged_release_loader.py tests/unit/test_agent_runtime.py \
    tests/unit/test_persisted_agent_runtime.py tests/unit/test_prompt_assembler.py \
    tests/unit/test_agent_schema_registry.py tests/unit/test_graph_definition_manifest.py \
    tests/unit/test_graph_configuration_bootstrap.py tests/unit/test_agent_resolution_prompt.py \
    tests/unit/test_deck_level_spec_change.py tests/unit/test_admin_route_authorization_inventory.py \
    tests/unit/test_conversation_graph_version_projection.py tests/unit/test_graph_lifecycle_stage_attribution.py \
    tests/unit/test_graph_lifecycle_playwright_contract.py tests/unit/test_log_record_rendering.py \
    tests/unit/test_unit_suite_database_isolation.py tests/unit/test_frontend_tests_are_typechecked.py \
    tests/unit/test_app_wheel_dependencies.py tests/unit/test_ci_collects_integration_tests.py \
    tests/unit/test_e2e_matrix_covers_specs.py
  ```

  Add every #268/#269/#270 unit file recorded at Task 0-B.
- [ ] **Step 2: PostgreSQL matrix.** Run every file in `integration-graph` as its own `TELLR_TEST_POSTGRES_URL=…` command, with zero skips recorded per file. That includes #271's three files, #269's and #270's files, and the #260–#267 files listed at `.github/workflows/test.yml:448-472`.
- [ ] **Step 3: Frontend matrix.**
  - Vitest `src/components/Admin`;
  - `npm run typecheck` (now including `tests/`);
  - ESLint on every touched frontend file;
  - Playwright, each `--project=chromium --workers=1`: `graph-release-admin-journey`, `graph-release-conversation-journey`, `agent-definition-workbench`, `graph-release-review`, `graph-release-history`, `admin-route-gate`, `admin-page`, `conversation-graph-version`, `mixed-release-collaboration`.

  Compare warning causes, not counts.
- [ ] **Step 4: Controller final sabotage** on a seam no task used. In `PersistedGraphReleaseLoader._load_complete_release`, cache by `agent_key` instead of `graph_release_id`. Predicted RED: Task 7's v2 turn resolves v1 revisions. Restore it and prove the diff is clean.
- [ ] **Step 5: Whole-branch review**, from exactly `INTEGRATION_BASE..HEAD`, on the most capable reviewer. Attach proof that the range is exactly #271's commits.
  - **Hand it:** `PLAN-CORRECTIONS.md`, every report, every ledger ruling and deferred item, the Task 12 gate evidence, and all sabotage outputs.
  - **Require (1):** a removal table. For every R1–R7 row: gone, callers migrated, structural guard name.
  - **Require (2):** a writer-by-writer table for every writer the journey crosses: draft writer, publication core, rollback, verdict writer, test-run executor, session creators. For each: the locks in order and the rows written. It must confirm that #271 added no writer.
  - **Require (3):** a failure-attribution audit. Pick three stages and show that a sabotage in the owning ticket's code is labelled with that ticket.
  - **Require (4):** a rollback/no-write ruling for every failure-matrix case.
  - **Require (5):** a merge/no-merge verdict.
  - Allow one fix wave and one scoped re-review.
- [ ] **Step 6: Epic-level spec review against #258.** This is a separate pass by the same reviewer, or a second one. It walks:
  - #258 user stories 1–60 and Implementation Decisions, each mapped to a test or a ruling;
  - spec §18 acceptance criteria 1–12;
  - the "one of each" invariants (Task 0-B4's owner-test list, each re-run);
  - the user's decisions (no identifiers to any model, key-name-only log, no prose in the log, no fabricated release ids) against Task 7's assertions;
  - #268 Q1–Q7, #269 Q2/Q4/Q8/Q9 and #270 OQ items, listing which are still open for the user.

  Output: covered / covered-with-ruling / open, per item. Any "open" that blocks spec §18 is a no-merge.
- [ ] **Step 7: Pre-merge gate.**
  1. Re-resolve the local `feat/langgraph-core` root and the #268/#269/#270 heads.
  2. Prove `INTEGRATION_BASE` and each head are ancestors of both the root and `HEAD`.
  3. Recompute the reviewed diff as `INTEGRATION_BASE..HEAD`. Refuse the merge if reconciliation changes it.
  4. If any predecessor advanced, rebase, refresh the corrections and baselines, and re-run the affected reviews.
- [ ] **Step 8: Local merge only.**
  1. Merge into `feat/langgraph-core` locally with `git merge --no-ff`. The message is `Merge #271: Lakebase-only execution and epic #258 acceptance` followed by the Co-authored-by trailer, in its own command.
  2. Record the merge SHA in `progress.md`.
  3. List for the user: the deploy-autoscaling issue, the m7 tool-path issue, m9's status, and any open epic item. No push, no PR.

## Open questions for controller ruling

- **Q1.** Should Task 1's conftest *refuse* a `DATABASE_URL` naming `ai_slide_generator`, as planned, or only warn? The plan refuses, because a test run that writes to the dev database is never intended.
- **Q2.** Should `src/core/skills` authored `instructions` be deleted in a follow-up now that no `src/` module reads them? The protected constants must stay. This plan retains the module; deleting authored prose is a separate, prose-only change.
- **Q3.** The recorded Playwright contract (Task 10) must be re-recorded whenever a wire model changes, and Task 6's shape test forces that. Is a developer command acceptable as the regeneration path, or should it be a documented `make` target?
- **Q4.** m9 (Task 13) needs user authorisation to read the dev workspace. Until then the epic is merge-ready but not release-verified. Confirm that this split is acceptable.
