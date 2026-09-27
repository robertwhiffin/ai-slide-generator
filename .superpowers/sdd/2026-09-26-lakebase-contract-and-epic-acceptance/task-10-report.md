# Task 10 report: contract-recorded fixtures and the administrator Playwright journey (AC9)

**Status:** DONE. No production defect was found. `src/` and `frontend/src` are unchanged (`git diff --stat eba136e66 HEAD -- src frontend/src` is empty).

## Commits
- TASK_BASE was `eba136e66`. Task 9 committed `a4dc51dc2` and `010b3c1f5` in this worktree during the task.
- `7d06b258a` `test: administrator Playwright journey over the recorded HTTP contract (#271)`. Committed by explicit path. It touches:
  - `tests/integration/graph_lifecycle_journey.py`: additive only. It adds `CONTRACT_VERSION`, `CONTRACT_PATH`, `CONTRACT_EXCHANGE_KEYS`, `exchange_models`, `build_contract`, `contract_shape`, `write_contract` and a `__main__` entry point. `run_to`, the stages and `call` are untouched.
  - `tests/integration/test_graph_lifecycle_acceptance_postgres.py`: a new second test, `test_a_fresh_recording_has_the_checked_in_contracts_shape`.
  - `tests/unit/test_graph_lifecycle_playwright_contract.py` (new, 145 tests).
  - `frontend/tests/fixtures/graphLifecycleContract.json`: recorded, 70 exchanges, 1.4 MB, `recorded_at_commit` `eba136e66…`.
  - `frontend/tests/fixtures/graphLifecycleContract.ts` (new).
  - `frontend/tests/fixtures/forbiddenActionHelpers.ts` (new, C16/C40).
  - `frontend/tests/e2e/agent-definition-workbench.spec.ts`: the sweep closure now calls the shared helper. `const AFFECTED_ROLES` is byte-identical.
  - `frontend/tests/e2e/graph-release-admin-journey.spec.ts` (new).
  - `.github/workflows/test.yml`: `graph-release-admin-journey` goes before `graph-release-history`, its nearest sorted neighbour (C39). The `unit-tests` job checkout also gets `fetch-depth: 0` (see Deviations).
- This report is force-added in a separate commit.

## TDD
- **RED, Python join.** Before the harness entry points existed, `test_graph_lifecycle_playwright_contract.py` failed at collection with an ImportError on `CONTRACT_PATH`. The contract file was also missing.
- **Recording.** I ran `TELLR_TEST_POSTGRES_URL=… PYTHONPATH=… python -m tests.integration.graph_lifecycle_journey --write-contract frontend/tests/fixtures/graphLifecycleContract.json`, which printed `1 passed … wrote 70 exchanges`, and committed its output unedited.
  - `write_contract` runs Task 6's journey test through `pytest.main` with a small plugin. The plugin keeps `journey.exchanges` only when the test passed and every stage completed.
  - The exchange list is written in recording order, which is stage order. The unit test asserts that order.
- **GREEN, Python.** One harness fix was needed: the model resolver now takes the request into account, so an exchange that sent no body resolves to `request_model = null`.
- **RED, Playwright.** The spec was iterated against the running app. The failures along the way:
  - the status text is `Clean`, not `Published`;
  - the verdict controls sit under the `Compare` view as region `Candidate run verdict`;
  - after a rejection, the status is `Test failed`;
  - the lookahead and carried lists (below).
- After those fixes the spec was GREEN three runs in a row (8/8 each time).

## The contract
- **Format.** `{contract_version: 1, recorded_at_commit, exchanges: [{id, method, path, request, status, body, response_model, request_model}]}`.
- **Model resolution.** `exchange_models` resolves the dotted paths from the SHIPPED routers, matching each route with `APIRoute.matches`.
  - Response models:
    - the success status uses the route's `response_model`;
    - an error status uses the model declared in `responses=`, with a union narrowed by its `code` literal;
    - one undeclared status is tabled: `save_agent_definition_draft` returns 409 `DraftSaveConflictResponse` through a hand-built `JSONResponse`;
    - a FastAPI `{"detail"}` error has no model (`null`).
  - Request models: seven routes read their body by hand, so their models are tabled (`_MANUAL_REQUEST_MODELS`). The others use FastAPI's `body_field`, so `POST /api/sessions` resolves to `CreateSessionRequest`.
- **What the unit join asserts.**
  - The top-level key set and `contract_version == 1`. Each exchange's key tuple is exact.
  - The 70 ids equal a literal list, in stage order. The list covers the admin journey plus the `/api/sessions` exchanges Task 11 consumes.
  - The recorded model names equal a fresh resolution against today's routes.
  - Every body round-trips its response model: `model_validate_json(json.dumps(body)).model_dump(mode="json") == body`. This gives exact recursive keys, and it also covers `CollaborationHistoryResponse`, whose `model_config` is `{}` (C49).
  - Every request round-trips its request model through `model_validate_json` (C21), compared with `model_dump(exclude_unset=True)`.
  - Model-less exchanges are restricted to `/api/sessions` (their shape only, C21) or a 404 `{detail}` body.
  - The three bodies the UI must reproduce are checked for structure.
  - `recorded_at_commit` is an ancestor of `HEAD`.
- **Shape test (PostgreSQL).** A fresh recording's shape equals the checked-in file's.
  - Shape is each exchange's id, method, status and model names, plus the recursive key structure of its request and body, with JSON type names for scalars.
  - Ids, tokens and timestamps are therefore ignored. Session paths with random ids are not compared.

## The replay (`graphLifecycleContract.ts`, per C1)
- **Exports.** `loadContract()` (a `readFileSync` of a URL relative to the module), `exchange()`, `adminExchangeIds()` and `installContract(target: Page | BrowserContext, ids)`.
- **Mutations.** PUT and POST requests are a queue, consumed strictly in recorded order. Each is matched on method and path, never on body ids (Task 6 concern 4). A request out of order is answered 500 and listed in `unmatched`.
- **GETs.** A GET is served the last recording for its method and path that precedes the next unconsumed mutation. Query parameters must match exactly, except the UI-only `limit`.
- **Pinned approximations.** Two lists name every read the recording cannot answer from the page's own point in the journey:
  - `lookahead`: a GET made before the journey first recorded it is served the first later recording;
  - `carried`: a GET whose latest recording comes before a mutation already sent.

  The spec pins both lists exactly.
- **App shell (C1.3).** Six named, fixed responses:
  - `setup-status` and `current-user`;
  - `profiles`, `design-systems` and `slide-styles` (setupMocks' bodies);
  - `admin-sibling-panel`: a 500 for the hidden sibling admin tabs, as `admin-route-gate.spec.ts` stubs them. It excludes `/api/admin/agent-definitions/**`.
- **Scope.** One `BrowserContext` holds one cursor. A second page in it is the other admin whose fixer save goes stale.

## The spec (`graph-release-admin-journey.spec.ts`)
It is one `test.describe.serial` over a context created in `beforeAll`. Every named `getByRole` passes `exact: true`: 52 calls. The one nameless call is the nav button list.

| Step | What it drives and asserts |
|---|---|
| 1 | Open `/admin`, then the `Agent Definitions` tab. The nav shows the 8 nodes in order, lock 0, and changed roles `Clean`. Foreman is `Deterministic`, has no test cases and no `Save Draft`. The shared sweep runs on the Foreman view and on all 4 Architect tabs, plus a `/\btools?\b/i` check (AC5). `ALLOWED_ACTION_NAMES` has length 8. The other admin's page opens at lock 0. |
| 2 | Architect prompt plus temperature 0.4 (C1.5), then `Save Draft` → lock 1. The PUT deep-equals `S03-put-architect.request`, and the status is `Needs test`. Builder save → lock 2, deep-equal. The other admin's fixer save sends lock 0 and deep-equals `S03-put-fixer-stale.request`. The 409 region shows `Expected lock 0; Current lock 2` with `Reload server` / `Keep local`. `Reload server` → lock 2. |
| 3 | `Schema Upgrade` → lock 3, then `Select diagnostic_notes` and save → lock 4. `Upgrade protected assembly` → lock 5, then `Add custom block After authored prompt` with the recorded text and save → lock 6. Every body deep-equals its recording; the custom block is compared with its UUID-shaped `block_id` swapped for the recorded one. |
| 4 | `Refresh models`, then the `databricks-claude-sonnet-4-5` radio, then save → lock 7, deep-equal. |
| 5 | For each changed role: `Needs test`, then `Run test case`, then `Awaiting review`; the body deep-equals the recording. Then builder `Reject run` with the recorded notes → `Test failed`. Architect and fixer `Approve run` → `Approved`. Builder reruns → `Awaiting review`, then `Approve run` → `Approved`. Every body deep-equals its recording. |
| 6 | The `Review & Publish` link lands on `/admin/agent-definitions/review`. `Next Graph Version: 2` is shown, and the diff tab lists the architect `prompt_text`. The note is typed. `Publish Graph Version 2` → `release-stale-alert`, then `Reload preview`, then publish → `release-success-panel`. The POST deep-equals `S11-post-release.request`. |
| 7 | `Release History`: `release-history-row-1`, then `Inspect this version` (detail and comparison), then `Roll back to this version`. The lineage reads `Graph Version 3 will restore Graph Version 1`, and the default note equals the recorded note. `Confirm rollback` → `rollback-stale-alert`, then `Reload rollback preview`, then `Confirm rollback` → `Graph Version 3 restores Graph Version 1`. The POST deep-equals `S15-post-rollback-1.request`. |
| 8 | `unmatched == []`. The mutation ids equal the contract's admin mutation ids, in order (C1.4): 20 of them. The `lookahead` and `carried` lists are exact. |

Of the 20 admin mutations, 18 request bodies are deep-equal. The two stale POSTs are not (see Concerns).

## Gates
- **Environment.** `PYTHONPATH=tree:tree/packages/databricks-tellr`, `DATABASE_URL=sqlite:////tmp/t271-10.sqlite` and `TELLR_TEST_POSTGRES_URL=…/postgres`, one file per invocation.
- **Housekeeping.**
  - Port 3000 was free before and after every Playwright run.
  - `.venv` is absent.
  - The `tellr_int_*` set is the same 5 databases before and after.
  - `ai_slide_generator` was never touched.

| Gate | Result |
|---|---|
| `graph-release-admin-journey` (chromium, 1 worker) | 8 passed, three consecutive runs |
| That spec plus `graph-release-review`, `graph-release-history`, `admin-route-gate` and `agent-definition-workbench`, in one run | 110 passed |
| Full Vitest | 21 files, 1099 passed |
| `tsc --noEmit -p` for `tsconfig.app.json`, `tsconfig.node.json` and `tsconfig.e2e.json` | exit 0 each. `--listFilesOnly` confirms the three new TS files are in the e2e program (C25). |
| `tsc -b` | exit 0. It was run with `node_modules/.tmp/*.tsbuildinfo` backed up and restored byte-for-byte (mtimes preserved), so the shared node_modules were not changed (C25/C26). |
| ESLint on the 3 new TS files plus `agent-definition-workbench.spec.ts` | clean |
| `tests/unit/test_graph_lifecycle_playwright_contract.py` | 145 passed |
| `tests/integration/test_graph_lifecycle_acceptance_postgres.py` | 2 passed, zero skips (`-rs`) |
| `tests/unit/test_e2e_matrix_covers_specs.py` | 4 passed |
| `tests/unit/test_prompt_assembler.py` (C40 re-run) | 78 passed |
| `test_frontend_tests_are_typechecked.py` | 3 passed |
| `test_ci_collects_integration_tests.py` | 25 passed |
| `test_graph_lifecycle_stage_attribution.py` | 17 passed |
| Full unit suite (`-n 4`, 20:23:13Z–20:27:00Z UTC) | 2 failed / 7417 passed / 110 skipped. The 2 failures are exactly the `test_deploy_autoscaling` pair (the baseline cause). |
| `ruff check` and `ruff format --check` (3 Python files) | clean |

## Mutation table
- **Where.** Every mutation ran in `/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-10-mut`, a detached worktree at `7d06b258a` with the node_modules symlink.
- **Restore.** Each mutation was restored with `git checkout 7d06b258a -- <file>`, followed by `git diff --quiet 7d06b258a`.
- **Cleanup.** The worktree was then removed. A grep for the markers in the shared tree is empty.

| # | Mutation | Predicted | Result (first RED line) |
|---|---|---|---|
| M1 | A recorded body drifts from its model: in the JSON, `S11-post-release.body.changed_agents` becomes `changedAgents` | Python join | RED: `test_every_recorded_body_round_trips_its_response_model[S11-post-release]` (1 failed / 144 passed) |
| M1-PW | Same JSON drift, run through the Playwright spec (front-end parser) | Playwright step 6 | RED: `waiting for getByTestId('release-success-panel')` at step 6. The page's strict parser rejects the drifted body. |
| M2 | The backend model drifts from the recording: `PublishReleaseSuccessResponse` gains `sabotage_m2: int = 0` | unit join and PG shape | RED in both. Unit: `…round_trips_its_response_model[S11-post-release]`. PG: `test_a_fresh_recording_has_the_checked_in_contracts_shape`, `AssertionError: S11-post-release` (the journey test itself stayed green: 1 failed, 1 passed). |
| M3 | **Plan REVIEWER sabotage**: a frontend control is renamed, the publish button `Publish Graph Version ${next}` → `Publish` (`ReviewAndPublishPage.tsx:335`) | exact-name locator | RED: `waiting for getByRole('button', { name: 'Publish Graph Version 2', exact: true })` at step 6 |
| M4 | The page sends a wrong request body: publish `release_note: state.note.toUpperCase()` (`useReviewAndPublish.ts:83`) | step 6 deep-equal | RED: `+ "release_note": "LIFECYCLE GRAPH VERSION 2."` at `expect(served.requestBody('S11-post-release')).toEqual(publish)` |
| M5 | The page sends a wrong save body: `max_tokens` − 1 in `validateDraftForm` (`draftEditorState.ts:783`) | step 2 deep-equal | RED: `- 60000 / + 59999` at `requestBody('S03-put-architect')` |
| M6 | CI: remove `graph-release-admin-journey` from the e2e matrix | matrix test | RED: `test_every_spec_is_in_matrix_or_excluded_with_reason`, `assert not {'graph-release-admin-journey'}` |

- **Not run:** the plan's CONTROLLER sabotage (`lock_version` → `lockVersion` in one recorded request), because it is the controller's. Predicted RED: `test_every_recorded_request_round_trips_its_request_model[<id>]`, since `extra="forbid"` rejects the extra key and the renamed key leaves `lock_version` missing.

## Deviations
1. **Route.** The brief's `/admin/agent-definitions` does not exist (`App.tsx:54-55`). The workbench is `/admin` plus the `Agent Definitions` tab, as every existing workbench spec opens it. `/admin/agent-definitions/review` is used as specified.
2. **`installContract` takes `Page | BrowserContext`.** It is installed on the context, so two pages share one cursor. The S03 stale save is then real: the other admin's page really holds lock 0, the body deep-equals the recording, and the reducer's coherence checks (current 2 > expected 0) accept the 409.
3. **Step 5 order.** Step 5 follows the recorded mutation order: reject builder, approve architect, approve fixer, rerun builder, approve the rerun. After the rejection the real recorded readiness renders `Test failed`, so the sequence is `Needs test` → `Awaiting review` → `Test failed` → … → `Approved`.
4. **Two tests in the PostgreSQL file.** The shape comparison is a second test, and the journey runs twice (about 5 s total). This lets `write_contract` run only the unchanged journey test: a shape check inside that test would refuse the first recording.
5. **`write_contract` is `pytest.main` plus a plugin.** The Task 6 fixtures (`postgres_engine`, `acceptance_stack`, `monkeypatch`) are pytest fixtures. Driving the real test means a recording exists only for a fully passing journey.
6. **`fetch-depth: 0` on the `unit-tests` checkout.** The ancestry assertion cannot run on a shallow clone, because the recorded commit is absent. This file was not in the Files block.
7. **The full unit suite ran with `DATABASE_URL` unset**, as Task 6 did. The conftest then gives each xdist worker its own SQLite file, and a single shared `/tmp/t271-10.sqlite` across 4 workers would invite lock contention. Every per-file run used the prescribed `DATABASE_URL`.
8. **`tsc -b` backup and restore.** C25 says never run `tsc -b` from an agent, while the gate list asks for it. I ran it with the tsbuildinfo backup and restore described above, so the shared node_modules are unchanged.
9. **Exchange count.** The recording has 70 exchanges. Task 6's report said 72, so this is a count correction. The literal list in the unit test is authoritative.

## Concerns
1. **Recording gaps.** The replay serves reads the journey never recorded; they are pinned but approximate. **`lookahead` (8 reads):**
   - each page's boot readiness, 2× each under StrictMode. It is served lock 1's body, which the reducer drops as another lock's;
   - the first catalog read when the Model tab opens, served S06's body;
   - each role's stored-run list, read when its case is selected before the run, served the list recorded after the run.

   **`carried` (6 reads):**
   - the other admin's readiness after its 409;
   - the preview after the stale publish and after the publish;
   - the rollback preview after the stale rollback;
   - the history and the preview after the rollback.

   The spec asserts only the POST-response panels at those points. **Fix:** closing these needs Task 6 to record the missing UI reads: `GET /readiness` at S01, `GET /test-cases/{id}/runs` before each run, `GET /release-preview` after S11, and `GET /releases` plus `GET /release-preview` after S15. That changes stage recording and the Task 6 and Task 11 id sets, so it is a controller decision. I did not change stage behaviour.
2. **The stale 409s are served against a current lock.** The UI's stale publish and stale rollback send the current lock (L), while the recorded stale requests carry L−1. Those two bodies are therefore not deep-equaled. The UIs render their stale alerts from the recorded 409 bodies.
3. **Two hand-maintained tables.** `_MANUAL_REQUEST_MODELS` (7 routes) and `_UNDECLARED_RESPONSE_MODELS` (1 entry) exist because those routes parse bodies, or build 409s, by hand. A route that switched to an undeclared model would be caught by the body round-trip, not by the model-name check.
4. **Contract size.** The contract is 1.4 MB of indented JSON, mostly the full prompt texts repeated in each workbench and draft body. Re-record it whenever the backend wire changes; the PostgreSQL shape test names the first drifting exchange id.
5. **`recorded_at_commit` is `eba136e66`, the TASK_BASE.** The recording ran from the uncommitted harness change, which became `7d06b258a`. The ancestry assertion holds.
6. **Concurrent session.** The Task 9 agent committed in this worktree during my task. My commit staged only my 9 paths.
