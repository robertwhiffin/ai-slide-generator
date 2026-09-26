# PLAN-CORRECTIONS.md — this file overrides docs/superpowers/plans/2026-09-26-lakebase-contract-and-epic-acceptance.md wherever they differ.

- **Source:** `plan-review-1.md` (APPROVE WITH CORRECTIONS; 2 Critical, 9 Important, 12 Minor), controller rulings OQ1–OQ4 in `progress.md`, and the binding corrections in this file's commissioning prompt.
- **Plan at:** `0a5598e50` on `feat/test-evidence-readiness-268`. **Code base:** `a08389ec3`. `git diff --stat a08389ec3 HEAD -- src tests frontend packages` is empty (Phase A base).
- **Authority:** the plan file stays unchanged. Where they differ, this file wins. Attach it to every implementer and reviewer brief, as plan line 15 requires. The plan's Task 0 Step A1 prescribes the first line for this file; the first line above supersedes it.
- **Numbering:** Correction 1 = C1, Correction 2 = C2, Corrections 3–11 = I1–I9, Corrections 12–23 = M1–M12. Each states the plan line(s) overridden, the evidence (re-verified against code where noted), the replacement instruction, any replacement sabotage target, the phase it binds, and its cost if wrong.
- **Phases:** **Phase A** = in force before Task 1 or Task 5 dispatches. **Phase B** = in force after reviewed #268, #269 and #270 are merged locally, before the named task dispatches.

---

## Critical

### Correction 1 (C1) — Tasks 10/11: the recorded-contract replay cannot serve the UI's real request sequence

**Overrides:** plan lines :756-758 (`installContract` spec: "serves exactly the named exchanges by method and path, fails the test on any unmatched `/api/**` request"), :771 (step 8 sequence-equality), :774 (step 2 PUT body must deep-equal `S03-put-architect.request`), :780 (step 8 comparison), :799 (Task 11 reuses chat mocks), :806 (step 5 `Start latest` mutation assertion).

**Evidence:** Every page boot calls `/api/user/current` (verified: `frontend/tests/e2e/admin-route-gate.spec.ts:18-29`) and other app-shell endpoints that Task 6 never records. `GET /workbench` and `GET /readiness` each appear with multiple state-dependent bodies — method + path is not a unique key. Selecting a role loads `GET /test-cases/{id}/runs` (client `listTestCaseRuns`, `frontend/src/api/agentDefinitions.ts:1623`); that endpoint never appears in the journey. Task 10 step 2 edits only the architect prompt, but S03's PUT also sets `temperature 0.4` (plan :632), so the body cannot deep-equal the S03 exchange. Verified: `src/api/routes/chat.py:490-491` and `:697-698` call `resolve_engine_mode_or` not `resolve_engine_mode`; the review also notes `GET /readiness` is re-read after each save or verdict per #268 C24.

**Replacement instruction:**
1. **Replay key is `(method, path, stage_cursor)`.** Only PUT and POST requests advance the cursor. A GET is served the most recent recorded body for `(method, path)` at or before the current cursor.
2. **Record every UI-driven GET.** Task 6 adds explicit "UI read" sub-steps inside each stage body — `GET /test-cases/{id}/runs` after each test run, and `GET /readiness` after each save or verdict — so each is a real exchange in the contract.
3. **App-shell boot endpoints** (`/api/user/current` and whatever `setupMocks` covers) are served from a named, fixed recorded response in `graphLifecycleContract.ts`'s allowlist. Any `/api/**` request outside the allowlist and the contract fails the test.
4. **Step 8's sequence-equality check** is scoped to mutating requests (PUT and POST) only, in order. GETs are not order-checked.
5. **Task 10 step 2** must perform exactly S03's edits: add the prompt suffix **and** set `temperature 0.4`. Only then does the recorded PUT body deep-equal `S03-put-architect.request`.

**Replacement sabotage:** The plan has no sabotage that breaks the sequence check; none is added. The controller's step 5 sabotage (rename `lock_version` → `lockVersion` in one recorded request) still targets the Python join and is unchanged.

**Binds:** Phase B, blocking before Task 10 dispatch.

**Cost if wrong:** The Playwright journeys cannot reach GREEN because every boot call hits the "unmatched `/api/**`" fail path; or the sequence check is vacuous because it only checks GETs; or the PUT body mismatch makes the contract body check permanently RED.

---

### Correction 2 (C2) — Task 6 S12: the contributor and duplicate calls contradict shipped #262 semantics; the failure would be misrouted to #262

**Overrides:** plan lines :641 (S12 `POST /api/sessions/old-root/contribute` and `POST /api/sessions/old-root/duplicate`), :648 (step 3: "record as a predecessor defect labelled `#262`"), :601 (single `user: TestClient`).

**Evidence (re-verified):**
- Owner cannot contribute to their own session: `src/api/routes/sessions.py:353-357` returns 400 "You are the owner of this session". A second user also needs deck-level `CAN_VIEW` (`:360`).
- `session_manager.duplicate_session` raises `ValueError("Source session has no slide deck to duplicate")` (`session_manager.py:1193-1194`), routed to 400 by `sessions.py:668-670`. `old-root` has no deck.
- Duplicate only pins a release when the source session's earliest user message carries the agent-mode marker (`session_manager.py:1232-1245`); without it `graph_release_id = None`.
- `real_route_stack` at `test_agent_definition_workbench_postgres.py:1284-1311` sets `_admin_acl_probe = lambda _user: True` (`:1304`), making every principal an admin. Both clients in the current plan share one `ContextVar` principal (`src/core/user_context.py:11-23`), so contributor is also an admin.

**Replacement instruction:**
1. Before S12, seed `old-root` with a slide deck **and** one user message carrying the agent-mode marker (the `"USE AGENT MODE …"` phrase). Either drive one Task-7-style graph turn, or seed through `SessionManager` directly.
2. Add a second non-admin principal (`contributor@example.com`) with a `CAN_VIEW` grant on `old-root`'s deck. The `_admin_acl_probe` must return `True` only for the admin principal's identity.
3. Set the current user per-request (not per-client), switching between principals for the owner-session create/read calls and the contributor calls.
4. **Step 3:** a stage failure is triaged by the controller against the shipped contract **before** it is routed to a predecessor. A failure on correct code is attributed to `#271`'s setup until the controller rules otherwise.

**Replacement sabotage:** No S12 sabotage was planned; none is added. The controller triage step supersedes the existing "record as #262 defect" instruction.

**Binds:** Phase B, blocking before Task 6 dispatch.

**Cost if wrong:** S12 fails on correct code and the fix is filed against #262 as a false predecessor defect; or `old-root` can never have a contributor because the deck is absent.

---

## Important

### Correction 3 (I1) — Task 4: the plan's tsconfig gives 42 errors, not 12; `verbatimModuleSyntax` must be dropped; `tsc -b` writes build info into shared node_modules

**Overrides:** plan lines :118-121 (P1 probe: "exactly 12 errors"), :503 (Step 1 guard: "12 errors"), :512-531 (the `tsconfig.e2e.json` template, which includes `"verbatimModuleSyntax": true`), :536 (Step 3: "`npm run typecheck` exits 0" with the plan's config).

**Evidence (reviewer-measured):** With the plan's config as written (including `verbatimModuleSyntax: true`): **42 errors** — 32 × TS1484 ("type import must use `import type`") across 28 spec files plus `tests/user-guide/shared.ts`, 9 × TS2307 and 1 × TS2740. Dropping `verbatimModuleSyntax` leaves **1 error** (TS2740 at `findings-drawer.spec.ts:87`). The plan's probe (`P1`) produced 12 errors from a config that did not include `verbatimModuleSyntax`; the plan's own template then re-added it. `tsc -b` (which `npm run typecheck` calls via the project references) writes `tsconfig.e2e.tsbuildinfo` into `node_modules/.tmp`, a path shared across parallel agents.

**Replacement instruction:**
1. **Drop `"verbatimModuleSyntax": true`** from `tsconfig.e2e.json`. The e2e config only has to typecheck, not enforce strict ESM import style.
2. **At Task 0-B Step 5,** re-measure with the corrected config and record the exact error list. The Files block must list **every** file whose error the implementer is expected to fix (not just three from P1).
3. **Use `tsc --noEmit -p frontend/tsconfig.e2e.json`** in all task steps and the Python guard, not `tsc -b`. This prevents any build info being written into `node_modules/.tmp`.
4. Add `"tsBuildInfoFile": null` (or omit the key entirely) from `tsconfig.e2e.json` — the `noEmit` flag makes it irrelevant, and leaving a path there risks a future caller without `--noEmit`.
5. The Python guard in `test_frontend_tests_are_typechecked.py` stays; assert `tsconfig.json` references `tsconfig.e2e.json` and that the e2e config contains `"include": ["tests/**/*.ts"]` and **not** `"verbatimModuleSyntax"`.

**Replacement sabotage (Task 4 controller):** re-introduce `"verbatimModuleSyntax": true` in `tsconfig.e2e.json`. Predicted RED: `npm run typecheck` reports 42 errors (TS1484 wave), not 1.

**Binds:** Phase B, blocking before Task 4 dispatch.

**Cost if wrong:** the implementer writes or reverts 29 files of type-import rewrites; or the build-info file is written into the shared node_modules, silently corrupting other agents' incremental type-check state.

---

### Correction 4 (I2) — Task 1: the conftest default is shared across all xdist workers; the `DATABASE_URL` guard must be scoped to `ai_slide_generator` only

**Overrides:** plan lines :327-337 (conftest template, comment "One directory per process, so xdist workers never share a file"), :344-349 (Step 4 green run, which does not include `-n auto`).

**Evidence (reviewer-probed):** A conftest with `if "DATABASE_URL" not in os.environ: os.environ["DATABASE_URL"] = tempfile.mkdtemp()` run under `pytest -n 4` gives all four workers (gw0–gw3) the **same** URL, because `conftest.py` is loaded in the controller process before workers fork; they inherit `os.environ`. `tests/integration/test_ws4b_fixture_contracts.py:68` calls `setdefault('DATABASE_URL', 'sqlite:///:memory:')` and would silently change to the shared file URL after Task 1. CI runs `pytest tests/unit -n auto` (`.github/workflows/test.yml:137`). The PostgreSQL fixtures read `TELLR_TEST_POSTGRES_URL` only (`tests/integration/conftest.py:209`); they are unaffected.

**Replacement instruction:**
1. **The guard** refuses only when `DATABASE_URL` already names `ai_slide_generator`. Any other value passes. This preserves every existing test that explicitly sets `DATABASE_URL`.
2. **The default** (when `DATABASE_URL` is unset) gives each xdist worker its own SQLite file:
   ```python
   if "DATABASE_URL" not in os.environ:
       _worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
       _db_path = f"/tmp/tellr-tests-{_worker}.sqlite"
       os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
       os.environ["TELLR_TESTS_DATABASE_URL_DEFAULTED"] = "1"
   elif "ai_slide_generator" in os.environ["DATABASE_URL"]:
       raise SystemExit("refusing to run tests against the ai_slide_generator dev database")
   ```
3. **Pin the worker isolation** with a dedicated `-n 2` probe in `test_unit_suite_database_isolation.py`: run two workers and assert that `_get_database_url()` returns **different** file paths in each. This replaces the "one directory per process" comment as the verification.
4. **Step 4** adds a run with `-n auto` (not just `-n 0`). The cause set must be identical to the single-worker run.
5. **CI decision** (`test.yml:102-104`) is respected: CI leaves `DATABASE_URL` unset intentionally; the conftest supplies the per-worker default. Do not add `DATABASE_URL` to CI workflows.

**Replacement sabotage (Task 1 controller):** unchanged (delete the `os.environ["DATABASE_URL"] = …` line). Predicted RED: `test_a_unit_run_never_resolves_the_operator_dev_database` fails.

**Binds:** Phase A, blocking before Task 1 dispatch.

**Cost if wrong:** `pytest -n auto` gives all workers the same SQLite file, causing random `OperationalError: database is locked` failures that look like test isolation bugs; or the guard fires on a valid `DATABASE_URL` that happens to contain a different substring.

---

### Correction 5 (I3) — Task 5: the `<2.0.0` upper cap is unproven; the RED test compares the wrong value; `requirements.txt` is omitted

**Overrides:** plan lines :114 ("the range `>=1.99.9,<2.0.0`, which is exactly the intersection of both transitive constraints"), :151 ("declared range `>=1.99.9,<2.0.0`"), :549-559 (RED test template: `assert app_deps["openai"] == ">=1.99.9,<2.0.0"`).

**Evidence (re-verified):** `langchain-openai`'s `<2.0.0` is not in the wheel's required closure: `databricks-langchain==0.9.0` requires only `openai>=1.99.9`, and the `langchain-openai` package appears only behind optional extras. `_declared()` in `test_app_wheel_dependencies.py:69-95` returns the **full spec string** from the manifest line (e.g. `"openai>=1.99.9,<2.0.0"`), not a parsed version object — so `app_deps["openai"] == ">=1.99.9,<2.0.0"` would compare strings and pass if the text matches, but the claim that the cap "adds no distribution" is unproven because the sandbox blocked network access during review. `requirements.txt` is not updated in the plan's Files block or Step 2 instruction.

**Replacement instruction:**
1. **Declare `openai>=1.99.9` with no upper cap** in `packages/databricks-tellr-app/pyproject.toml`, `pyproject.toml`, and `requirements.txt`. The range matches the one verified transitive constraint (`databricks-langchain>=1.99.9`) and is safe by evidence. A future cap requires a devloop-deploy proof that the wheel resolves correctly with the cap.
2. **The RED test** asserts `"openai"` in `app_deps` and the value is a string that **starts with** `"openai"` when interpreted as a full spec. Fix it to parse the specifier with `packaging.requirements.Requirement` and assert the parsed specifier string equals `">=1.99.9"` — never compare raw spec strings, which are fragile to whitespace and ordering:
   ```python
   from packaging.requirements import Requirement
   def test_the_app_wheel_declares_openai_within_the_transitive_bounds(app_deps, root_deps):
       """agent_runtime.py and model_endpoint_probe.py import openai at module level."""
       assert Requirement(f"openai{app_deps['openai']}").specifier == Requirement("openai>=1.99.9").specifier
       assert Requirement(f"openai{root_deps['openai']}").specifier == Requirement("openai>=1.99.9").specifier
   ```
3. **Record** in the task report: the local env has `openai 1.105.0` via `databricks-langchain`; the wheel's resolution at build time is a separate closure and may differ. The test proves only that the declared constraint matches the verified transitive bound, not that the wheel resolves to 1.105.0.
4. Add `requirements.txt` to the Task 5 Files block.

**Replacement sabotage (Task 5 controller):** unchanged (remove the app-manifest line). Predicted RED: `KeyError: 'openai'`.

**Binds:** Phase A, blocking before Task 5 dispatch.

**Cost if wrong:** the wheel ships with an unproven `<2.0.0` cap that could downgrade or block `openai` in the Databricks Apps build phase; or the RED test compares raw strings and passes vacuously with the wrong specifier.

---

### Correction 6 (I4) — AC1 tripwire and Task 12 guards miss by-name bindings and code-owned model defaults

**Overrides:** plan lines :609-614 (tripwire patches `src.core.skills.load_skill`), :889-891 (guard 2 checks only `load_skill` in `src.core.skills`; guard 4 scans only `agent_runtime.py`), :925 (Task 12 controller sabotage: adds `from src.core.skills import load_skill` to `persisted_graph_release.py`; predicts tripwire RED).

**Evidence (re-verified):** `src/core/skills/__init__.py:138` shows `load_skill` indexes `_SKILLS` directly. `agent_runtime.py:46` has `from src.services.persisted_graph_release import PersistedGraphReleaseLoader` — this is not a `load_skill` example, but the same pattern applies: a module-level `from src.core.skills import load_skill` (as at `prompt_assembler.py:15`) binds the name before the tripwire patches `src.core.skills.load_skill`, so the patch is never seen. `DEFAULT_CONFIG["llm"]` is at `agent_runtime.py:372`; guard 4's `agent_runtime.py` text scan does cover this line, but a fallback added to `persisted_graph_release.py` or `prompt_assembler.py` would pass guard 4 undetected. The Task 12 controller sabotage adds a module-level import to `persisted_graph_release.py`; module-level imports execute before `arm()` patches the function, so the tripwire can never fire for this path.

**Replacement instruction:**
1. **Tripwire: trap `src.core.skills._SKILLS`** instead of (or in addition to) `load_skill`. Replace `_SKILLS` with a raising mapping after `load_graph_v1_manifest.cache_clear()`. Since `load_skill` at `:138` always indexes `_SKILLS`, every binding — whether imported at module level or re-bound later — is caught. Keep the manifest trap (`sys.modules` swap plus `cache_clear`) unchanged; it is already binding-proof.
2. **Guard 4:** widen to scan every module on the Agent Definition resolution path — `src/services/agent_runtime.py`, `src/services/persisted_graph_release.py`, `src/services/prompt_assembler.py`, `src/services/agent_schema_registry.py`, and every file under `src/services/graph/` — for `DEFAULT_CONFIG["llm"]` or `DEFAULT_CONFIG.get("llm"`.
3. **Guard 2:** replace the "`src.core.skills` + `load_skill`" check with a full `src.core.skills.*` import allowlist. Any import of a `src.core.skills` name from a `src/` module is forbidden **except** the two protected-bundle material imports (`build_reviewer` and `data_analyst` `INSTRUCTIONS`) and the protected constants (`DECK_BRIEF_REVIEW`, etc.). The AST walk must catch both `from src.core.skills import X` and `from src.core.skills.X import Y`.
4. **Task 12 controller sabotage (:925):** re-aim to add a **function-level** `import src.core.skills; return src.core.skills.load_skill(agent_key)` call inside `PersistedGraphReleaseLoader._load_complete_release`. A function-level call runs after `arm()` patches `_SKILLS`, so the tripwire fires. Predicted RED: `[AC1/#271]` in the Task 6/7 log, **and** guard 2 in `test_lakebase_only_runtime_contract.py`.

**Replacement sabotage (Task 12 controller):** add a function-level `src.core.skills.load_skill(agent_key)` call inside `PersistedGraphReleaseLoader._load_complete_release`. Predicted RED: tripwire raises `[AC1/#271]`, and guard 2 text-scan fails.

**Binds:** Phase B, blocking before Task 6 dispatch (tripwire seam) and before Task 12 dispatch (guard seam).

**Cost if wrong:** the AC1 tripwire silently passes for module-level `load_skill` bindings; or a `DEFAULT_CONFIG["llm"]` fallback added outside `agent_runtime.py` passes guard 4; or the Task 12 sabotage goes RED on the wrong assertion (guard not tripwire).

---

### Correction 7 (I5) — Real production defect: pinned graph conversation silently runs on the legacy monolith when engine-mode resolution fails

**Overrides:** plan lines :127-141 (removal inventory, which does not list this fallback), Task 8 :708 ("Lakebase unavailable: the loader session factory raises `OperationalError`").

**Evidence (verified):** `src/api/routes/chat.py:490-491` and `:697-698` both call `resolve_engine_mode_or(request.session_id)` with the default `fallback="monolith"`. The function at `src/api/services/chat_service.py:239-270` catches **any** exception and returns the fallback. A transient `OperationalError` during mode resolution silently runs a pinned graph conversation on the legacy monolith, using `DEFAULT_CONFIG["llm"]` and code-owned prompts — the exact path spec §15 forbids: "Lakebase unavailable | Fail explicitly; no code defaults or latest-release substitution." Existing Task 8 tests patch the loader's session factory; this fallback is upstream of the loader and is never reached by those tests.

**Replacement instruction:**
1. **Add to the removal inventory** (plan lines :127-141) a new row: `resolve_engine_mode_or fallback | `src/api/services/chat_service.py:239-270`; `src/api/routes/chat.py:490-491`, `:697-698` | In scope: the call sites that route a pinned graph conversation must fail explicitly on a resolution error`.
2. **Fix in #271:** replace both call sites in `src/api/routes/chat.py` (`:490-491` and `:697-698`). When the session has a non-null graph pin and `resolve_engine_mode` raises, raise `PersistedConfigurationUnavailableError(code="lakebase_unavailable")` instead of returning `"monolith"`. The existing HTTP handler at the route level maps `PersistedConfigurationUnavailableError` to 503. If the session has no pin or no graph marker, the monolith fallback is permitted (this is a legacy session).
3. **Task 8 additions:** add two test cases that reach each call site with a pinned session and assert (a) the monolith is never invoked (the model adapter is never called), and (b) the response is 503 `lakebase_unavailable`.
4. **Sabotage (Task 8 reviewer):** restore the original `resolve_engine_mode_or` call at one of the two sites. Predicted RED: the new Task 8 test sees a successful (monolith) response instead of 503.

**Replacement sabotage (Task 8 reviewer):** restore `resolve_engine_mode_or(..., fallback="monolith")` at `chat.py:490-491`. Predicted RED: Task 8's new test asserts 503 but gets 200 with a monolith response body.

**Binds:** Phase B, blocking before Task 8 dispatch. The production fix also touches `src/api/routes/chat.py` and `src/api/services/chat_service.py` (Phase B).

**Cost if wrong:** a production Lakebase error during chat silently falls through to the legacy monolith, violating spec §15 and AC3; the bug ships undetected.

---

### Correction 8 (I6) — Task 7: the AC5 "no tools" assertion is vacuous with a recording `AgentModelAdapter`

**Overrides:** plan line :682 ("(no tools, AC5) the recording adapter asserts that `bind_tools` is never reached (use the `ChatModel` double pattern from `test_agent_runtime.py:379-430` inside the adapter)").

**Evidence:** The `AgentModelAdapter` protocol (`DeterministicFakeModelAdapter`) receives `(agent_key, configuration, schema, prompt)` and produces a response without going through a real LangChain `ChatModel`. There is no `bind_tools` call path in a recording adapter; it can never be asked to bind. `test_agent_runtime.py:379-430` places the raising double inside a real `DatabricksModelAdapter` (verified: `:403` shows `DatabricksModelAdapter(model_factory=…)`), which does call `bind_tools` during tool-use setup.

**Replacement instruction:**
1. **Drive the `bind_tools` AC5 assertion with the real `DatabricksModelAdapter`.** Construct it with `model_factory=lambda **_: recording_chat_model` where `recording_chat_model` is a `ChatModel` double that records all method calls and raises on `bind_tools([…])` (any non-empty tool list).
2. The rest of the Task 7 graph turns use `DeterministicFakeModelAdapter` for speed and determinism; this one assertion uses `DatabricksModelAdapter` with the raising double for exactly one turn per role.
3. The sabotage: make `bind_structured_output_model` also call `bind_tools([])`. Predicted RED: the `bind_tools` raising double fires.

**Replacement sabotage (Task 7 reviewer):** make `bind_structured_output_model` call `bind_tools([])`. Predicted RED: the raising `ChatModel` double fires before any structured output can be bound.

**Binds:** Phase B, blocking before Task 7 dispatch.

**Cost if wrong:** AC5 ("no tools") is asserted vacuously; a regression that adds tool binding to the graph runtime goes undetected by Task 7.

---

### Correction 9 (I7) — Task 11 step 3: the mixed-release warning cannot come from Task 6's recording; real deck mutations are required

**Overrides:** plan lines :805 (step 3: "open the shared `old-root` deck with the v2 contributor; `mixed-release-warning` is visible and names both versions"), :799 (Task 11 "consumes … exchanges `S02-*`, `S11-mid-root`, `S12-*` and `S16-*`").

**Evidence:** `mixed_release_warning` is set to `True` only when two or more persisted non-null Graph Versions appear in the session's mutation evidence (`src/api/routes/sessions.py:392-397`). Task 6's journey has no deck mutation via a chat turn on either `old-root` (v1) or any v2-pinned session. A real recording would show `mixed_release_warning: false` in `GET /api/sessions/old-root/collaboration-history`. Without a v1 mutation and a v2 mutation on the same deck, the warning never fires.

**Replacement instruction:**
1. **Add a Task 6 sub-stage** (between S12 and S14): the `old-root` (v1-pinned) session makes one deck mutation — drive one graph turn or write a deck row directly through `SessionManager` — and one of the v2-pinned sessions (`new-root`) makes one deck mutation on the same deck. Then record `GET /api/sessions/old-root/collaboration-history`. The response must have `mixed_release_warning: true` and list both versions.
2. Include this exchange in the contract file under the stage code `S12b-collab-history` (or similar); Task 11 step 3 consumes it.
3. The Task 6 helper's `LifecycleJourney.exchanges` list must include this exchange; `write_contract` exports it.

**Replacement sabotage:** none was planned for Task 11 step 3; the fix is to the journey setup, not a sabotage.

**Binds:** Phase B, blocking before Task 11 dispatch.

**Cost if wrong:** Task 11 step 3 is unverifiable — `mixed-release-warning` is never visible in the recorded contract, so the Playwright step cannot go GREEN against the contract.

---

### Correction 10 (I8) — Task 3: neither sabotage exercises the byte-for-byte parity comparison; reviewer sabotage triggers on role-key mismatch before any content diff

**Overrides:** plan lines :477 (parity test: "produce a prompt, configuration and schema byte-identical to `AgentRuntime.compatibility(...).run(...)`"), :493-495 (reviewer sabotage: "make it return `builder`'s content for `architect`"; predicted RED: "parity and hash tests").

**Evidence:** Returning `builder`'s content for `architect` means `content.agent_key == "builder" != "architect" == definition.agent_key` at `src/services/agent_runtime.py:1012-1013`. That raises `ValueError`, then `PersistedConfigurationUnavailableError("invalid_persisted_definition")` before any prompt is assembled (`:1050`). The parity assertion is never reached. The hash test fails for a different reason (the hash of builder's content does not match architect's stored hash). Nothing proves that a one-byte prompt difference causes the parity assertion to fail.

**Replacement instruction:**
1. **Reviewer sabotage:** in `PackagedGraphV1Loader.resolve`, for `agent_key == "architect"`, return `model_copy(update={"prompt_text": content.prompt_text + "x"})` — keeping `agent_key`, `schema_contract`, `definition_version` and all other fields unchanged. This changes exactly one byte of content while keeping the identity intact.
2. **Predicted RED:** the parity assertion fails on the architect prompt comparison (the one-byte `"x"` suffix); the hash test also fails because `definition_content_hash` is prompt-sensitive.
3. **Controller sabotage** (ignore `graph_release_id`) is unchanged; it REDs on `GraphReleaseNotFoundError`.

**Replacement sabotage (Task 3 reviewer):** return `model_copy(update={"prompt_text": content.prompt_text + "x"})` for architect in `PackagedGraphV1Loader.resolve`. Predicted RED: parity assertion fails on architect's prompt text; hash test also fails.

**Binds:** Phase B, blocking before Task 3 dispatch.

**Cost if wrong:** the parity test never actually exercises the byte comparison; a one-byte drift in the packaged manifest content goes undetected.

---

### Correction 11 (I9) — No port-3000 lane; no node_modules symlink; `tsc -b` writes into shared node_modules

**Overrides:** plan lines :53-59 (frontend command set, which does not mention an `lsof` check or node_modules setup), :536 (Task 4 Step 3: "`npm run typecheck`", which internally runs `tsc -b`), :785 (Task 10 Step 4: Playwright run with no port check), :808 (Task 11 Step 2: Playwright run with no port check), :970 (Task 14 Step 3: frontend matrix with no port check).

**Evidence:** `frontend/playwright.config.ts:16` has `baseURL: 'http://localhost:3000'` and `:38` has `reuseExistingServer: true`. A Vite server from another worktree at port 3000 would be tested silently. The worktree has no `frontend/node_modules` (verified: absent). `npm run typecheck` calls `tsc -b`, which writes `tsbuildinfo` into `node_modules/.tmp`; that would be the main checkout's shared `node_modules`.

**Replacement instruction:**
1. **Global constraint (prepend to plan line :53):** before and after every Playwright run, `lsof -i :3000` must show zero listeners. If port 3000 is occupied, abort and report the owning process. Playwright runs are serialized one at a time.
2. **Worktree setup (Task 0-A Step A1 or a named prerequisite):** create the symlink `frontend/node_modules → .worktrees/issue-260-bootstrap/frontend/node_modules`. Verify the symlink before any frontend command. Do not run `npm install`.
3. **Typecheck invocation:** replace every `npm run typecheck` with `(cd frontend && tsc --noEmit -p tsconfig.json)` so no build info is written. Add a note: `tsconfig.json`'s project references invoke `tsc --noEmit` on each referenced config including `tsconfig.e2e.json`.
4. Add the port check and symlink check to Task 14's Step 3 frontend matrix as the first two steps.

**Replacement sabotage:** none was planned for this finding; no sabotage is added.

**Binds:** Phase A (symlink step, before any frontend command), Phase B (port-check and typecheck invocation, blocking before Task 4 and every Playwright task).

**Cost if wrong:** a stale Vite server from another worktree is tested instead of this worktree's code; the result is GREEN against the wrong build, and the bug ships; or `tsbuildinfo` written into the shared `node_modules/.tmp` causes incremental type-check failures in other parallel agents.

---

## Minor

### Correction 12 (M1) — Task 2 site list and regex miss `test_persisted_agent_runtime.py` lines

**Overrides:** plan line :368 (site list: `test_persisted_agent_runtime.py:948`, `:1032`, `:1937`; regex `vars\(record\)|record\.__dict__`).

**Evidence (re-verified):** `rg -n "vars.record" tests/unit/test_persisted_agent_runtime.py` shows additional hits at `:1459` and `:1628-1629` (`str(vars(records[0]))`). The pattern `vars\(record\)` misses `vars\(records\[0\]\)`.

**Ruling:** Widen the regex to `vars\(record` (no closing parenthesis). Add `test_persisted_agent_runtime.py:1459` and `:1628-1629` to the Task 2 site list. The migrated files stay in the Task 2 Files block.

**Sabotage:** n/a.

**Binds:** Phase B, Task 2 (apply before the site grep command). Non-blocking.

**Cost if wrong:** two log-rendering sites stay as `str(vars(…))` and continue to match file paths, defeating the needle fix.

---

### Correction 13 (M2) — Step 2's "RED: the first and fourth guards fail" undercounts; guard 5 already passes

**Overrides:** plan line :910 ("RED: the first and fourth guards fail").

**Evidence:** Guards 1–4 all fail on the present compatibility code: guard 1 (`compatibility` attribute exists), guard 2 (`agent_runtime.py:46` imports `load_skill` — though this is a different import, the guard's text scan catches `src.core.skills` imports), guard 3 (`agent_runtime.py:71` and `:375` read `DEFAULT_CONFIG`), and guard 4 (`DEFAULT_CONFIG` in `agent_runtime.py` text). Guard 5 (`PersistedGraphReleaseLoader` in the factory) already passes today and is a regression pin, not a RED test.

**Ruling:** Change plan line :910 to: "RED: guards 1, 2, 3 and 4 all fail on the present code. Guard 5 already passes; it is a regression pin. The four failing guards collectively assert that the compatibility path is gone." Record that guard 5 must stay GREEN through the deletion.

**Sabotage:** n/a.

**Binds:** Phase B, Task 12. Non-blocking.

**Cost if wrong:** the implementer expects only guards 1 and 4 to fail and is surprised when 2 and 3 also need their fix; or guard 5's GREEN status is interpreted as "no test to write" when it is in fact a regression pin.

---

### Correction 14 (M3) — R7 is incomplete: `RecordingAgentInvocationIdentitySink` is used by tests and must be re-exported; three other unused names remain

**Overrides:** plan lines :137 (R7: "unused imports `load_skill`, `DEFAULT_CONFIG`, `inspect`, `textwrap` and the module docstring's 'temporary adapter' text"), :828-829 (`AgentRuntime` keeps various named exports; R7 items are deleted).

**Evidence (re-verified):** `src/services/agent_runtime.py:52` and `:826` use `RecordingAgentInvocationIdentitySink`; it is imported by `tests/unit/test_graph_configuration_draft.py:2920` and `tests/unit/test_persisted_agent_runtime.py:35`. Additionally, `agent_runtime.py` has `OUTPUT_SCHEMAS`, `hashlib`, `json`, `AssemblyRules`, and `cast` that are unused after R1–R5 deletion. `load_graph_v1_manifest` is used by guard 3 as evidence of its deletion; it must be removed too. `RecordingAgentInvocationIdentitySink` is used by `packaged_v1_runtime` at `:826` as a default sink.

**Ruling:**
1. **R7 extends to:** `load_skill`, `DEFAULT_CONFIG`, `inspect`, `textwrap`, `OUTPUT_SCHEMAS`, `hashlib` (used only by R5), `json` (used only by R5), `AssemblyRules` (used only by R5), `cast` (used only by R5), and `load_graph_v1_manifest` (guard 3 requires its removal from `src/`; it stays in `graph_definition_manifest.py` and `graph_configuration_bootstrap.py` only).
2. **`RecordingAgentInvocationIdentitySink`** is **kept** as a named re-export from `agent_runtime.py` (or relocated to `agent_runtime_identity.py`). Before Task 3, record which test files import it from `agent_runtime` and update their imports if the location changes. It is also the default sink in `packaged_v1_runtime`.
3. Add these items to Task 12's Step 3 deletion checklist.

**Sabotage:** n/a.

**Binds:** Phase B, Task 12. Non-blocking before earlier tasks.

**Cost if wrong:** `test_graph_configuration_draft.py` and `test_persisted_agent_runtime.py` fail with `ImportError` after deletion; or unused `hashlib`/`json` remain and guard 3's text scan sees them.

---

### Correction 15 (M4) — Three stale citations must be corrected before the tasks that use them

**Overrides:** plan line :95 ("production wiring is `agent_runtime.py:1149-1177`"), plan line :104 ("model discovery is `agent_definitions.py:529`"), plan line :789 ("Publish Graph Version" as the control's accessible name).

**Evidence (re-verified):**
- Production wiring: `get_agent_runtime` is at `agent_runtime.py:1140-1177` (the function begins at `:1140`, not `:1149`). Lines :1149-1177 are the function body.
- Model discovery: `get_remote_endpoint_draft_validator` is at `agent_definitions.py:115`, `get_model_endpoint_catalog` at `:156`, model discovery discovery logic at `:537` (not `:529`). The cite at `:104` says `:529`; it should say `:537`.
- #269's publish control: the exact accessible name per #269 plan `:875` is `Publish Graph Version {next}`, so at step 6 the name is `Publish Graph Version 2`, not `Publish Graph Version`.

**Ruling:**
1. Update `:95` to read "production wiring is `agent_runtime.py:1140-1177` (`get_agent_runtime` and `get_agent_test_runtime`)".
2. Update `:104` to read "model discovery is `agent_definitions.py:537`".
3. Update `:789` (Task 10 step 5 sabotage) to: "the page's publish control accessible name from `Publish Graph Version 2` (the exact name per Task 0-B, which may differ if #269 C-something changed the label) to `Publish`". Task 0-B records the exact name.

**Sabotage:** n/a (citation fix).

**Binds:** Phase B (citations used in Tasks 9, 10). Non-blocking before earlier tasks.

**Cost if wrong:** the Task 0-A2 re-verification grep lands on a wrong line and records a false correction; or the Task 10 reviewer sabotage changes the wrong label name and never goes RED.

---

### Correction 16 (M5) — Task 10 Files block omits `graph_lifecycle_acceptance_postgres.py`; sweeping `agent-definition-workbench.spec.ts` imports a non-exported helper from another spec

**Overrides:** plan lines :749-750 (Task 10 Files block omits `tests/integration/test_graph_lifecycle_acceptance_postgres.py`), :771 ("extend Task 6's PostgreSQL test"), :773 ("Reuse the sweep helper from `agent-definition-workbench.spec.ts`").

**Evidence:** Task 10 Step 2 extends `test_graph_lifecycle_acceptance_postgres.py` (the shape-equality assertion), but this file is not in the Task 10 Files block. Importing a helper from one Playwright spec inside another is invalid — each spec file is isolated and helpers must live in `tests/fixtures/`. `agent-definition-workbench.spec.ts` is not in the Task 10 Files block either, so the sweep helper is assumed to be in a shared fixture already, but it is not.

**Ruling:**
1. Add `tests/integration/test_graph_lifecycle_acceptance_postgres.py` to the Task 10 Files block as "Modify (add shape-equality assertion)".
2. Extract the forbidden-action sweep helper to `frontend/tests/fixtures/forbiddenActionHelpers.ts` (or the file Task 0-B records as the extraction target). Add that file to the Task 10 Files block as "Create" and add `frontend/tests/e2e/agent-definition-workbench.spec.ts` as "Modify (import from the shared fixture)".
3. Do not import between spec files.

**Sabotage:** n/a.

**Binds:** Phase B, Task 10. Non-blocking before earlier tasks.

**Cost if wrong:** Task 10 GREEN step misses the shape-equality assertion (it is not in the file being reviewed); or the spec import causes a Playwright import error at runtime.

---

### Correction 17 (M6) — "Assertions stay byte-identical" cannot hold for the style-exclusivity tests using a real session; `_FakeSession` causes must be confirmed

**Overrides:** plan line :343 ("The assertions about normalisation stay byte-identical").

**Evidence:** `_FakeSession` at `tests/unit/test_style_exclusivity_chokepoint.py:62-83` implements `add` and `flush` but not `execute`. When replaced by a real SQLite session, `_conversation_state` (or equivalent) must read rows back via `session.execute(…)` or ORM queries — the `captured` dict used in assertions is populated differently. The P2 causes for the style tests are confirmed: `_FakeSession has no attribute 'execute'` (×3) and `ConversationGraphReleaseIntegrityError: no active Graph Release` (×1), consistent with the plan's `:122-124`.

**Ruling:** "Assertions stay byte-identical" is replaced with: "All existing normalisation assertions are preserved **by value**. Where `_FakeSession.add/flush` populated `captured`, the real session replacement must re-derive the same values by reading back the committed rows with `session.refresh(obj)` or `session.get(Model, id)`. Each assertion is verified to fail RED with the original `_FakeSession` and GREEN with the real session before committing." Record the cause mapping (which assertion maps to which `_FakeSession` attribute error) in the task report.

**Sabotage:** n/a.

**Binds:** Phase A, Task 1. Blocking for the style-fixture fix.

**Cost if wrong:** assertion values diverge between the fake and real session (e.g., a lazy-loaded attribute is `None` until refreshed), and the GREEN step passes vacuously on `None == None`.

---

### Correction 18 (M7) — Task 8 repeats existing cases; three new cases need un-named setup; creation-refusal is already landed

**Overrides:** plan lines :705-711 (Task 8 case list, which does not name existing cases; "missing active release at creation" parametrized over four creators).

**Evidence (re-verified):** `test_persisted_graph_runtime_failures_postgres.py` already has cases at `:297`, `:337`, `:369`, `:398`. `src/api/routes/sessions.py:113-118` and `:375-379` already return 503 "No active Graph Release available" — the creation-refusal is a landed feature, not something Task 8 defers. The "duplicate refuses without active release" case needs a marker-carrying source session with a deck (see C2). The "removed endpoint" case needs `FAKE_OUTPUTS` to yield an objective finding so fixer's endpoint actually fires. `PersistedGraphReleaseLoader._cache` (`persisted_graph_release.py:96-138`) serves an already-loaded release without opening a new session, so the `OperationalError` case needs a **fresh loader** (not the cached one).

**Ruling:**
1. **Name existing cases** at Task 8 Step 1 as "already in `test_persisted_graph_runtime_failures_postgres.py`" and note that Task 8 adds only the delta cases.
2. **"Duplicate refuses without active release":** seed a marker-carrying source session with a deck before bootstrapping zero active releases. (See also C2 for the deck and marker requirement.)
3. **"Removed endpoint":** configure `FAKE_OUTPUTS` to include at least one objective finding for the fixer role so the fixer node actually runs.
4. **"`OperationalError` case":** construct a **new** `PersistedGraphReleaseLoader` instance (not the cached one from `get_agent_test_runtime()`) and patch its `session_factory` to raise `OperationalError`.
5. **Creation-refusal case:** note that it is already landed (`sessions.py:113-118`). Task 8 adds only a regression pin, not a new implementation.

**Sabotage:** n/a (these are setup corrections).

**Binds:** Phase B, Task 8. Non-blocking before earlier tasks.

**Cost if wrong:** three Task 8 tests fail at setup with missing fixtures that are not obvious from the plan; or the `OperationalError` case passes vacuously because the cached release is served from memory without a DB call.

---

### Correction 19 (M8) — S15's "evidence kinds all `historical_restore`" is vacuous for v1; assert `evidence == []` exactly

**Overrides:** plan line :643 ("evidence kinds all `historical_restore`, with `source_release_id == v1`").

**Evidence:** v1 is the bootstrap release. It was created before any test runs were recorded. `_historical_evidence` copies only runs already linked to the source release. A bootstrap release has no linked runs, so the rollback copies no evidence rows. `evidence kinds all historical_restore` is vacuously true for an empty list.

**Ruling:** Replace "evidence kinds all `historical_restore`, with `source_release_id == v1`" with "evidence `== []` exactly (v1 is the bootstrap release with no linked test runs; the rollback copies nothing)". If Task 6 adds test runs on v2 and the rollback target is v1, this assertion is accurate and non-vacuous.

**Sabotage:** n/a.

**Binds:** Phase B, Task 6 (S15). Non-blocking before earlier tasks.

**Cost if wrong:** the assertion passes vacuously on an empty list regardless of the actual `source_release_id`; a rollback that silently drops evidence would pass.

---

### Correction 20 (M9) — OQ2 premise is false: `prompt_assembler.py` imports two `src/core/skills` identifiers as v1 protected-bundle material; those two must be kept

**Overrides:** plan lines :1003 ("Q2: Should `src/core/skills` authored `instructions` be deleted … The plan retains the module"), :139 ("Reviewed and retained: `src/core/skills/*` … `prompt_assembler.py:15-26` imports protected constants").

**Evidence:** `prompt_assembler.py:20-28` imports `build_reviewer`'s and `data_analyst`'s `INSTRUCTIONS` as the v1 protected-bundle material (the v2 transition records). These are **production reads** of authored prompt text from `src/core/skills`. The OQ2 ruling ("deleting the now-unread authored prompt text is out of scope") is correct for the other roles' authored text, but these two specific imports — `build_reviewer.INSTRUCTIONS` and `data_analyst.INSTRUCTIONS` — are still read by production code.

**Ruling:** The OQ2 ruling stands (out of scope for #271). However, the follow-up issue that deletes authored prompt text from `src/core/skills` must **keep** `src/core/skills/build_reviewer.INSTRUCTIONS` and `src/core/skills/data_analyst.INSTRUCTIONS` — they are production-read bundle material, not inert prose. Add this note to the OQ2 entry in the plan's open-questions section and to the follow-up issue description.

**Sabotage:** n/a.

**Binds:** Phase B, Task 12 (guard 2 allowlist must include these two imports). Non-blocking before earlier tasks.

**Cost if wrong:** the follow-up issue deletes `build_reviewer.INSTRUCTIONS` and `data_analyst.INSTRUCTIONS`, breaking `prompt_assembler.py` at runtime.

---

### Correction 21 (M10) — Task 10: `model_validate` on strict request models requires `model_validate_json(json.dumps(…))`; sessions routes have no response models

**Overrides:** plan lines :761-762 (Step 1 Python join: "each exchange's `body` passes `model_validate` for its `response_model` … each `request` passes its `request_model`").

**Evidence:** `src/api/schemas/agent_definitions.py:328-329` shows `_StrictDraftRequest` uses `strict=True` in model config. `model_validate(dict)` on a strict Pydantic model accepts plain Python dicts, which may coerce types that the strict JSON decoder would reject (e.g., a Python `int` passes where strict JSON requires it to be an `int` too, but a `float`-typed integer coerces). The correct validator for wire-fidelity is `model_validate_json(json.dumps(body))`. The sessions router (`src/api/routes/sessions.py`) has no Pydantic response models; its responses are plain `JSONResponse` or `dict`. Task 11's conversation exchanges have no `response_model` to validate.

**Ruling:**
1. In `test_graph_lifecycle_playwright_contract.py` Step 1, use `model_validate_json(json.dumps(exchange["body"]))` for request model validation on all strict models, and note that sessions-route responses have no `response_model` — assert only their status code and the recursive key structure for those exchanges.
2. Add a comment: "Sessions routes return plain dicts; shape check only."

**Sabotage:** n/a.

**Binds:** Phase B, Task 10. Non-blocking before earlier tasks.

**Cost if wrong:** the strict-model validator accepts a type-coerced value that the actual HTTP wire would reject; drift in the contract is not caught.

---

### Correction 22 (M11) — A harness bug in `graph_lifecycle_journey.py` must also be triaged by the controller before routing to a predecessor

**Overrides:** plan line :648 (step 3: "if any stage fails on integrated code, that is a **predecessor defect**: record it in corrections, labelled with its ticket, and route the fix to that ticket's owner").

**Evidence:** A failure can arise from a harness bug in `graph_lifecycle_journey.py` (wrong assertion, wrong fixture, wrong HTTP body), not from production code. Such a failure would be mislabelled as a predecessor defect when the fix belongs in Task 6 itself.

**Ruling:** Plan line :648 is replaced with: "If any stage fails on integrated code, the controller triages it before routing. The controller checks whether the failure is in the harness (wrong assertion, wrong fixture) or in the production seam named by the stage. Only after triage is a production failure recorded as a predecessor defect and routed to that ticket's owner. A harness bug stays in #271. This applies equally to failures in Steps 3 and 5 and to Task 7's step 3."

**Sabotage:** n/a.

**Binds:** Phase B, Task 6 and Task 7. Non-blocking for implementation.

**Cost if wrong:** a Task 6 harness bug (wrong expected value in `stage()`) is filed as a #262 or #269 production defect; the fix lands in the wrong ticket and is never tested in #271.

---

### Correction 23 (M12) — Task 0-B may rewrite every consumed-interface row; a scoped re-review of phase-B corrections is required before Task 2 dispatches

**Overrides:** plan lines :263-270 (Task 0-B Step B2: "a contradiction with this plan becomes a correction row that overrides the task that consumes it"; no re-review step follows).

**Evidence:** Tasks 6, 9, 10 and 11 all consume exact Pydantic class names, field lists, status codes and `data-testid`s from the C268-*/C269-*/C270-* table. Task 0-B may record shapes that differ from the plan's assumptions, adding many new correction rows in one pass. No plan re-review covers this set of corrections before Phase B tasks are dispatched.

**Ruling:** After Task 0-B completes (all Steps B1–B6 done), a scoped re-review of the accumulated Phase B corrections is run before Task 2 is dispatched. The re-review covers: every consumed-interface correction row added at Task 0-B; the corrected sabotage targets for Tasks 6–11; and the `ALLOWED_ACTION_NAMES` final count. It does not re-review Phase A work. The controller approves before Task 2 dispatches.

**Sabotage:** n/a.

**Binds:** Phase B, blocking before Task 2 dispatch.

**Cost if wrong:** Task 6 is dispatched against stale interface shapes recorded at plan-write time, causing the journey to fail on correct code because the actual HTTP contract has different field names.

---

## Blocking summary

- **Phase A (before Task 1 dispatch):**
  - Correction 4 (I2): xdist worker isolation in the conftest and the guard scope.

- **Phase A (before Task 5 dispatch):**
  - Correction 5 (I3): `openai>=1.99.9` with no cap, `requirements.txt`, and the `packaging`-based RED test.

- **Phase A (worktree setup, before any frontend command):**
  - Correction 11 (I9): `frontend/node_modules` symlink.

- **Phase B (before Task 2 dispatch):**
  - Correction 23 (M12): scoped re-review of Task 0-B interface corrections.

- **Phase B (before Task 3 dispatch):**
  - Correction 10 (I8): byte-for-byte parity sabotage (reviewer: change one byte, not swap the role).

- **Phase B (before Task 4 dispatch):**
  - Correction 3 (I1): drop `verbatimModuleSyntax`; re-measure at Task 0-B Step B5; use `tsc --noEmit`.

- **Phase B (before Task 6 dispatch):**
  - Correction 1 (C1): stage-cursor replay design; record all UI reads; scope sequence check to writes.
  - Correction 2 (C2): S12 contributor/duplicate prerequisites (deck, marker, non-admin principal, per-request user).
  - Correction 6 (I4): tripwire traps `_SKILLS`; guards 2 and 4 widened; Task 12 sabotage re-aimed.

- **Phase B (before Task 7 dispatch):**
  - Correction 8 (I6): AC5 no-tools uses `DatabricksModelAdapter` with raising `ChatModel` double.
  - Correction 9 (I7): deck mutations on two releases and collaboration-history exchange recorded in Task 6.

- **Phase B (before Task 8 dispatch):**
  - Correction 7 (I5): production fallback fix at `chat.py:490-491` and `:697-698`; Task 8 tests for both call sites.

- **Phase B (before Task 10 dispatch):**
  - Correction 11 (I9): `lsof -i :3000` gate before every Playwright run; `tsc --noEmit`.

- **Phase B (before Task 12 dispatch):**
  - Correction 6 (I4): (also blocking here) Task 12 controller sabotage re-aimed to function-level call.

- **Non-blocking (apply in named task):**
  - Correction 12 (M1): widen Task 2 regex to `vars\(record` (Task 2).
  - Correction 13 (M2): correct guard RED count at Task 12 Step 2 (Task 12).
  - Correction 14 (M3): `RecordingAgentInvocationIdentitySink` kept as re-export; R7 extended (Tasks 3, 12).
  - Correction 15 (M4): stale line citations corrected (Tasks 9, 10).
  - Correction 16 (M5): sweep helper extracted to shared fixture; `test_graph_lifecycle_acceptance_postgres.py` in Files block (Task 10).
  - Correction 17 (M6): style-fixture assertion parity confirmed by value, not text (Task 1).
  - Correction 18 (M7): Task 8 names existing cases; three setup details for new cases (Task 8).
  - Correction 19 (M8): S15 evidence asserted `== []` (Task 6 S15).
  - Correction 20 (M9): OQ2 follow-up must keep two imports; record in Task 12 guard 2 allowlist (Task 12).
  - Correction 21 (M10): `model_validate_json(json.dumps(…))` for strict models; sessions routes shape-only (Task 10).
  - Correction 22 (M11): controller triage before routing any failure (Task 6, Task 7).
