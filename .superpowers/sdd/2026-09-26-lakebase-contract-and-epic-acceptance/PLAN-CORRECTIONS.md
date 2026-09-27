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

---

# Task 0 phase B corrections (24–46) — 2026-09-27

- **Probed at:** HEAD `9a63ab1b7` on `plan/lakebase-contract-acceptance-271`; INTEGRATION_BASE `12a521dc7` (Merge #270). All file:line citations below are at that HEAD. Corrections 1–23 are not edited; where one is wrong, an **erratum** correction below overrides it.
- **Evidence logs:** `reports/preflight-phase-b.md` and `reports/logs/`.
- **Scoped re-review (C23):** every correction in this section is in scope for the scoped re-review that C23 requires before Task 2 dispatches.
- Format per correction: **Overrides** (plan line or earlier correction) · **Evidence** (file:line) · **Proposed ruling** · **Binds** · **Cost if wrong**.

---

### Correction 24 — Phase B carry (1), refines C7: the monolith fallback has THREE call sites; "only when pinned" is unimplementable; there is no 503 handler; the lock must be released; the fail-open contract is pinned by ws4d tests

**Overrides:** C7 replacement instruction 2 and 3; plan Task 8 Files block (:697-699, "tests only"); plan :712 ("implement (tests only)").

**Evidence:**
- Call sites: `src/api/routes/chat.py:490-492` (`/chat/stream`, after the session lock at `:475`, **outside** any `try`), `:697-699` (`/chat/async`, inside the `try` opened at `:668`, whose `except Exception` at `~:732-738` releases the lock and returns 500), and a third one C7 missed: `src/api/services/chat_service.py:1141` (`engine_mode = resolve_engine_mode_or(session_id, engine_mode)`, the SSE turn-1 re-resolve). On turn 1 of an SSE graph deck the route necessarily resolved `monolith` (no user row yet), so a DB error at `:1141` keeps `monolith` and runs the legacy path — the same defect.
- `resolve_engine_mode_or` (`chat_service.py:239-270`) catches every `Exception`. `resolve_engine_mode` (`:158-237`) decides graph vs monolith from the owner deck's earliest `role='user'` message, not from the pin; knowing whether the session is pinned needs the same database read that just failed. C7's "if the session has no pin … the monolith fallback is permitted" cannot be evaluated on the failure path.
- **C7 erratum:** "the existing HTTP handler at the route level maps `PersistedConfigurationUnavailableError` to 503" is false. `src/api/main.py` has one `exception_handler` (`:469`, `UserClientRequiredError`). The stream route maps `PersistedRuntimeError` inside the SSE generator (`chat.py:563-566`), after the 200 has started.
- The fail-open is a pinned ws4d contract: `tests/unit/test_engine_mode_wiring.py:550-625` (`test_a_raising_resolver_returns_the_callers_value`, `test_the_fallback_defaults_to_monolith`, `test_the_streaming_route_still_serves_the_turn`, `test_the_async_route_still_enqueues_the_job`) assert that a raising resolver still serves the turn as monolith.

**Proposed ruling:**
1. Fail closed at all three sites on any resolution exception, whatever the pin. `/chat/stream` and `/chat/async` release the session lock and then raise `HTTPException(503, detail={"code": "lakebase_unavailable", …})` before any response starts. The service site (`chat_service.py:1141`) raises `PersistedConfigurationUnavailableError(code="lakebase_unavailable")`, which the existing SSE mapping turns into the safe error event. Keep `resolve_engine_mode`'s three "no answer → monolith" cases unchanged: those are answers, not failures.
2. Invert the four ws4d tests listed above, rather than deleting them: a raising resolver now yields 503 or the safe event, with the lock released and the monolith never built.
3. Task 8 Files block adds: Modify `src/api/routes/chat.py`, `src/api/services/chat_service.py`, and `tests/unit/test_engine_mode_wiring.py`. Task 8 is then a production change, not tests only.
4. C7's reviewer sabotage stays: restore `resolve_engine_mode_or` at `chat.py:490`. Add a controller sabotage on the third site: restore the fallback at `chat_service.py:1141`. Predicted RED: the SSE turn-1 case runs the monolith.
5. **This reverses a ratified ws4d contract. The user must confirm it (see the user-decision list).**

**Binds:** Phase B, blocking before Task 8 dispatch.

**Cost if wrong:** Fixing only the two route sites leaves turn 1 of every SSE graph deck on the silent monolith fallback. Raising without releasing the lock leaves the session "processing" until the lock expires. A pin-conditional design adds a second DB read that fails the same way.

---

### Correction 25 — Erratum to C11 step 3: `tsc --noEmit -p tsconfig.json` typechecks nothing

**Overrides:** C11 replacement instruction 3; C3 instruction 3 (`tsc --noEmit -p frontend/tsconfig.e2e.json` is correct only for the e2e config).

**Evidence:**
- `frontend/tsconfig.json` is a solution config (`"files": []` plus references).
- `tsc` without `-b` does not follow references. Measured: `./node_modules/.bin/tsc --noEmit -p tsconfig.json --listFilesOnly | wc -l` gives **0**.

**Proposed ruling:** The typecheck gate for agents is three commands, run from `frontend/`:
- `./node_modules/.bin/tsc --noEmit -p tsconfig.app.json`
- `./node_modules/.bin/tsc --noEmit -p tsconfig.node.json`
- after Task 4, `./node_modules/.bin/tsc --noEmit -p tsconfig.e2e.json`

Each must exit 0. None of these writes a tsbuildinfo (measured: the `node_modules/.tmp/*.tsbuildinfo` mtimes are unchanged after the runs). Never use `npm run typecheck` or `tsc -b` from an agent.

**Binds:** Phase B, blocking before Task 4 (and every task that runs the typecheck gate: 10, 11, 14).

**Cost if wrong:** The typecheck gate is vacuously green for every task.

---

### Correction 26 — Erratum to C3 instruction 4: removing `tsBuildInfoFile` makes `tsc -b` write an un-ignored file into the worktree

**Overrides:** C3 replacement instruction 4.

**Evidence:**
- `npm run typecheck` and `npm run build` are `tsc -b` (`frontend/package.json:8-9`). CI's frontend-build also runs `npx tsc -b` (`.github/workflows/test.yml:616`).
- In build mode the siblings write buildinfo to `./node_modules/.tmp/` (`tsconfig.app.json:3`, `tsconfig.node.json:3`).
- With no `tsBuildInfoFile`, the e2e project's buildinfo defaults to `frontend/tsconfig.e2e.tsbuildinfo`. `git check-ignore frontend/tsconfig.e2e.tsbuildinfo` says **not ignored**.

**Proposed ruling:** Keep `"tsBuildInfoFile": "./node_modules/.tmp/tsconfig.e2e.tsbuildinfo"`, consistent with the siblings. The shared-`node_modules` risk is handled by C25: agents never run `tsc -b`.

**Binds:** Phase B, Task 4.

**Cost if wrong:** Every developer and CI `tsc -b` leaves an untracked `tsconfig.e2e.tsbuildinfo`, and the next `git add -A` commits it.

---

### Correction 27 — Task 4 (B5 re-measure): the exact error list, the Files block, and the ESLint baseline

**Overrides:**
- plan :503 (Files block: "`slide-viewer.spec.ts:14,33,46` and `slide-surface-fidelity.spec.ts:1022,1070` (plus 4 more lines…)");
- plan :536 ("`npx eslint tests` shows the same warning causes as preflight-B");
- C3 instruction 2.

**Evidence:** P1's recipe was run against the integrated tree (copied to `/tmp/t271-0b-ts`, `node_modules` symlinked, TypeScript 5.9.3). The C3 config has no `verbatimModuleSyntax` and has `types: ["node","vite/client"]`.
- **Without the `.d.ts`: 10 errors.**
  - 1 × TS2740 at `tests/e2e/findings-drawer.spec.ts(87,7)`.
  - 9 × TS2307 at `slide-surface-fidelity.spec.ts` :838, :880, :927, :1019, :1022, :1070 and `slide-viewer.spec.ts` :14, :33, :46.
- **With `tests/types/browser-modules.d.ts` (`declare module '/src/*';`): 1 error**, the TS2740.
- **With `verbatimModuleSyntax: true` re-added: 35 errors**, of which 34 are TS1484 across 29 files. #269 and #270 added TS1484 sites, so C3's prediction of "42" for its sabotage is stale.
- **ESLint on `frontend/tests`: 25 errors, 0 warnings, in 12 files:**
  - 18 `no-unused-vars`, 5 `no-explicit-any`, 1 `rules-of-hooks`, 1 `prefer-const`;
  - the files are 02-creating-profiles, 04-retrieving-feedback, 07-exporting-to-google-slides, deck-prompts-integration, export-csp, genie-detail-panel, history-integration, incremental-slide-delivery, navigation, save-points-versioning, slide-styles-integration, and `tests/fixtures/base-test.ts`;
  - none are in the #268–#270 specs, and #270's N2 is fixed.
- CI has no ESLint job (`grep -n eslint .github/workflows/test.yml` is empty; carry 6).

**Proposed ruling:**
1. **Task 4 Files block:**
   - Modify only `tests/e2e/findings-drawer.spec.ts:87`, at its cause.
   - Create `tests/types/browser-modules.d.ts`.
   - `slide-viewer.spec.ts` and `slide-surface-fidelity.spec.ts` are **not** edited; the `.d.ts` covers them.
2. **Task 4 Step 3's ESLint clause** becomes: "ESLint on `tests/` has exactly the 25-error cause set above (same rule × file pairs). Task 4 adds none."
3. **Controller sabotage (C3):** the predicted RED is "35 errors, 34 TS1484", or at minimum "TS1484 appears".
4. **Tasks 10 and 11:** ESLint on each new file must exit 0. There is no CI lint to catch it later.

**Binds:** Phase B, blocking before Task 4.

**Cost if wrong:** The implementer edits two specs that need no edit. Or Task 4 "fails" its ESLint gate on 25 pre-existing errors. Or a sabotage prediction mismatch is misread as a broken guard.

---

### Correction 28 — Task 2 (log-record rendering): the integrated site list

**Overrides:** plan :368 (the site list), and C12's list.

**Evidence** (`rg -n "vars\(record|record\.__dict__" tests`):
- `tests/unit/test_persisted_agent_runtime.py`:
  - `:924` is a field-**name** set; keep it as is;
  - rendering sites: `:948`, `:1032`, `:1459`, `:1628`, `:1629`, `:1937`.
- `tests/unit/test_agent_test_workbench.py:2010` (the plan said `:2003`; #268 drift).
- `tests/unit/test_graph_release_history_routes.py:168-174` (#270's `_extra`):
  - it already excludes every standard attribute, including `taskName`;
  - it is not a path-matching site.
- `tests/unit/test_logging_extra_reserved_keys.py:65` is a name set, out of scope.
- `tests/unit/test_conversation_graph_version_responses.py:141` renders a dataclass, not a LogRecord.
- No other #268–#270 site exists.

**Proposed ruling:**
- Migrate exactly `test_persisted_agent_runtime.py:948, :1032, :1459, :1628-1629, :1937` and `test_agent_test_workbench.py:2010`.
- #270's `_extra` may import `STANDARD_LOG_RECORD_ATTRS`, but this is optional and not required.
- The helper should union `{"taskName"}` explicitly, so that a 3.11 run and a 3.12 run render identically. (`makeLogRecord` on 3.11 has no `taskName`; #270's tests add it by hand.)

**Binds:** Phase B, Task 2. Non-blocking.

**Cost if wrong:** One rendering site is left matching `/private/tmp`, and one `taskName` extra leaks into the rendering on 3.12.

---

### Correction 29 — Task 3 (B3 re-inventory): no new compatibility caller after #268–#270; two citation drifts

**Overrides:** C14 (`test_graph_configuration_draft.py:2920`) and plan :474 (`PACKAGED_V1_CONTENT_HASHES` at `:745-751`).

**Evidence:**
- The AST import scan plus `rg` over `src scripts tests packages` finds the same callers as the Phase A re-count:
  - R1: 13 sites in 4 files, byte-identical lines;
  - R2 and R3 importers: `test_agent_runtime.py:24`, `test_graph_configuration_bootstrap.py:27`, `test_graph_definition_manifest.py:27`, `test_persisted_agent_runtime.py:23`, `test_prompt_assembler.py:30`, and `scripts/generate_graph_definition_manifest_v1.py:19`;
  - `_SchemaContractRegistry`: `test_agent_schema_registry.py:1322`;
  - `_canonical_digest` and `_schema_contract_material`: `test_agent_runtime.py:24`.
- `RecordingAgentInvocationIdentitySink` is imported from `agent_runtime` at `test_graph_configuration_draft.py:2917` and `test_persisted_agent_runtime.py:23`.
- There are no string monkeypatch targets on `src.services.agent_runtime.*`.
- There is no `docs/technical` mention of any retired name.
- `src/services/agent_runtime.py` is byte-unchanged since `a08389ec3`, so every agent_runtime line cited in the plan still holds.
- `PACKAGED_V1_CONTENT_HASHES` is at `test_graph_definition_manifest.py:744` and `V1_SCHEMA_CONTRACT_DIGESTS` is at `:754`.

**Proposed ruling:** The Task 3 Files block is unchanged. Use `:744` for the literal table copy (still copied, not imported).

**Binds:** Phase B, Task 3. Non-blocking. It sits alongside C10, which is blocking.

**Cost if wrong:** None beyond a citation.

---

### Correction 30 — Task 12 guard 3: the expected reader set names a file that never matches

**Overrides:** plan :882-886 (`test_the_bootstrap_manifest_is_read_only_by_bootstrap`'s expected set), and plan :98 (bootstrap reader at `graph_configuration_bootstrap.py:71-73`).

**Evidence:**
- `grep -c "agent_definition_manifest_v1\|load_graph_v1_manifest" src/services/agent_definition_manifest_v1.py` gives 0. Its only text is the docstring plus `GRAPH_VERSION_1_MANIFEST_JSON`.
- `rg -l` over `src` gives exactly `graph_definition_manifest.py`, `graph_configuration_bootstrap.py` and `agent_runtime.py`.
- Bootstrap reads the manifest at `graph_configuration_bootstrap.py:75-78`, lazily, and only when no release exists (`:67-70`).

**Proposed ruling:**
- After the deletion, the exact expected set is `{"services/graph_definition_manifest.py", "services/graph_configuration_bootstrap.py"}`.
- Before the deletion, guard 3 is RED only on `services/agent_runtime.py`. Record this in C13's RED list.

**Binds:** Phase B, Task 12.

**Cost if wrong:** Guard 3 stays permanently RED after a correct deletion. The implementer then "fixes" it by adding the string to the frozen v1 file, which plan :825 forbids.

---

### Correction 31 — Task 12 guards 2 and 4: the exact allowlist and the scope limits (makes C6/C20 concrete)

**Overrides:** C6 instructions 2 and 3, and C20's "keep two imports" (the actual count is six names in two modules).

**Evidence:**
- `prompt_assembler.py:14-27` imports:
  - from `src.core.skills.build_reviewer`: `BUILD_REVIEWER_AUTHORED_INSTRUCTIONS`, `BUILD_REVIEWER_CRITERIA_STAGE`, `DECK_BRIEF_REVIEW` and `INSTRUCTIONS` (as `BUILD_REVIEWER_V1_PROMPT`);
  - from `src.core.skills.data_analyst`: `ANALYST_AUTHORED_INSTRUCTIONS` and `INSTRUCTIONS` (as `ANALYST_V1_PROMPT`).
- The only other `src.core.skills` importer outside the package is `agent_runtime.py:46` (`load_skill`, which R7 deletes).
- `load_skill` indexes `_SKILLS` at `src/core/skills/__init__.py:138`. `list_skills` (`:145`) has no `src` caller.
- In C6's widened guard-4 scope, `DEFAULT_CONFIG` appears only at `agent_runtime.py:45` and `:372`.
- `src/services/graph/nodes.py:722` contains the text `tool_grants` in a docstring.

**Proposed ruling:**
- **Guard 2** is an AST allowlist keyed by `(importing file, module, name)`, and it contains exactly the six pairs above. It exempts files under `src/core/skills/` themselves. Any other `src.core.skills*` import in `src/` fails.
- **Guard 4:**
  - the `DEFAULT_CONFIG["llm"]` / `DEFAULT_CONFIG.get("llm"` scan uses C6's widened module set;
  - the `tool_grants` text check stays scoped to `agent_runtime.py`;
  - otherwise the `nodes.py:722` docstring is a false positive.
- **C20 follow-up issue text:** keep all six names, not "two".

**Binds:** Phase B, Task 12.

**Cost if wrong:** Guard 2 is either RED on correct code (a protected constant not allowlisted) or blind to a new import. Or guard 4 is RED on a docstring.

---

### Correction 32 — Tasks 7, 8 and 12: the real bundle-resolution and bundle-removal seams

**Overrides:**
- plan :685 (S17 "`AgentSchemaRegistry()`'s resolution of `(agent_key, schema_contract)`");
- plan :908 (the ledger "`AgentSchemaRegistry()`'s resolution");
- plan :710 ("`PromptAssembler._bundles` is patched");
- plan :913 (the `_SCHEMA_CONTRACT_VERSION` replacement name).

**Evidence:**
- **The schema registry has no public "resolve" method.** `AgentSchemaRegistry` (`agent_schema_registry.py:360`) has public `identity_for(agent_key, version)` (`:378`), `validate_overlay` and `compose` (`:451`), and private `_resolve(agent_key, identity)` (`:381-387`). `_resolve` reads the module global `SCHEMA_CONTRACT_BUNDLES` (`:304-314`, a `MappingProxyType`).
- **`_bundles` is per instance.** `PromptAssembler._bundles` is an instance attribute built in `__init__` from `_default_bundles()` (`prompt_assembler.py:387`, `:410`). Every `AgentRuntime` builds its own `PromptAssembler()` in `__init__` (`agent_runtime.py:806`), so patching the class attribute does nothing.
- **The replacement identity exists.** `V1_SCHEMA_IDENTITIES` is at `agent_schema_registry.py:298`. The v1-only overlay rule is still at `agent_runtime.py:1018` (`schema_identity.version == _SCHEMA_CONTRACT_VERSION`).
- **Existing PostgreSQL recipes.** `test_persisted_graph_runtime_failures_postgres.py:337` builds a closed release with an unknown protected contract, rather than patching bundles.

**Proposed ruling:**
- **Resolving a schema identity (S17 and the ledger):** assert `AgentSchemaRegistry().identity_for(role, v) == SchemaContractIdentity(role, v, <literal digest>)`, and `AgentSchemaRegistry().compose(...)` succeeds for the persisted overlay.
- **Resolving a protected identity:** `PromptAssembler().resolve_bundle(ContentIdentity(v, digest))`.
- **Task 8's dropped-bundle cases:**
  - Protected: `monkeypatch.setattr("src.services.prompt_assembler._default_bundles", lambda: {k: b for k, b in real().items() if k != (2, V2_DIGEST)})` **before** the runtime is constructed. Alternatively, pop the key from the constructed runtime's `_prompt_assembler._bundles`.
  - Schema v2: `monkeypatch.setattr(agent_schema_registry, "SCHEMA_CONTRACT_BUNDLES", MappingProxyType({k: v for k, v in … if k != ("builder", 2)}))`.
- **Replacement at `agent_runtime.py:1018`:** `schema_identity.version == V1_SCHEMA_IDENTITIES[definition.agent_key].version`. This is behaviour-identical. Do not tighten it to full identity equality in a deletion task.

**Binds:** Phase B. Task 7 (S17), Task 8 (bundle cases) and Task 12 (ledger and replacement). Non-blocking.

**Cost if wrong:** The S17 or ledger test fails at `AttributeError`. Or Task 8's bundle-drop is a no-op, so the case passes vacuously on the retained bundle.

---

### Correction 33 — Task 6 S07: the "no `graph_release_id == -1`" assertion is vacuous

**Overrides:** plan :636 ("no `persisted_agent_invocation` record carries `graph_release_id == -1`").

**Evidence:**
- Candidate runs use `_PassThroughIdentitySink` (`agent_runtime.py:756-768`), which records nothing.
- A candidate run emits exactly one `agent_candidate_run` record, with extras `{agent_key, status, error_code, error_class}` (`:771-792`).
- `CANDIDATE_RUN_GRAPH_VERSION`, `CANDIDATE_RUN_GRAPH_RELEASE_ID` and `CANDIDATE_RUN_REVISION_ID` are all `-1` (`:641-643`), but they never reach a log record.

**Proposed ruling:** S07 asserts both of these:
- **zero** `persisted_agent_invocation` records during S07;
- exactly one `agent_candidate_run` record per run, whose extra-key set (via `STANDARD_LOG_RECORD_ATTRS`, Task 2) is exactly `{agent_key, status, error_code, error_class}`, with `status == "completed"`.

**Binds:** Phase B, Task 6.

**Cost if wrong:** A regression that routes candidate runs through the production sink, with a fabricated `-1` id, passes S07.

---

### Correction 34 — Task 6 S10 and the Task 6 controller sabotage: exact diff field names and the sabotage anchor

**Overrides:** plan :639 ("`protected_assembly` … fields (names per Task 0-B)"), and plan :658 (the controller sabotage "`definition_field_diffs`, or the name Task 0-B recorded").

**Evidence:**
- **Field names.** `DiffFieldName` (`src/api/schemas/graph_releases.py:30-43`) lists 12 fields in order:
  - `definition_version`, `prompt_text`;
  - `model.endpoint_name`, `model.temperature`, `model.max_tokens`, `model.top_p`;
  - `schema_overlay`, `assembly_rules`;
  - `protected_assembly.version`, `protected_assembly.digest`;
  - `schema_contract.version`, `schema_contract.digest`.
- **Where the diff is built.** `definition_field_diffs` (`graph_configuration_publication.py:239-258`) iterates the module's `_DIFF_FIELDS`. It is also used by the rollback comparison (`graph_configuration_rollback.py:212`).
- **Preview shape.** `ReleasePreviewResponse` is `{draft, active_release, next_version_number, changed[{agent_key, published_revision_id, published_content_hash, candidate_hash, field_diffs[{field, published, candidate}]}], readiness, validation_issues, publishable}`.

**Proposed ruling:**
- **S10's architect diff field set** is exactly `{prompt_text, model.temperature, assembly_rules, protected_assembly.version, protected_assembly.digest}`. It is exact, not "includes". S05's upgrade changes protected assembly v1→v2, and S05 adds a custom block.
- **Builder's field set** is `{prompt_text, schema_overlay, schema_contract.version, schema_contract.digest}`.
- **Fixer's field set** is `{model.endpoint_name}`.
- Before writing the literals, Task 6 confirms by probe whether a protected-assembly upgrade also rewrites `assembly_rules` or `prompt_text`, and records the result.
- **Controller sabotage anchor:** remove the `prompt_text` entry from `_DIFF_FIELDS` in `graph_configuration_publication.py`. Grep the marker to prove it sits on the executed path. The predicted first RED is `[#269] S10 preview`, because S10 runs before S14's comparison.

**Binds:** Phase B, blocking before Task 6.

**Cost if wrong:** The literal `protected_assembly` never matches a wire field name, so S10 is RED on correct code and gets misrouted to #269.

---

### Correction 35 — The consumed-interface record (Step B2): the rows C268-1 … C270-4 as built, and five contradictions

**Overrides:** plan :159-177 (the consumed-interface table), C21's "sessions routes have no response models", and plan :171 (C270-4 "consumed by Task 7").

**Evidence:** A probe of `app.routes` plus `model_config` over `src.api.schemas.{agent_definitions,graph_releases,graph_release_history}`. Every response model listed below is `extra="forbid"`. Every request model listed is `extra="forbid"` and `strict=True`.

**C268-1 (verdict)**
- `POST /test-runs/{run_id}/verdict` (`agent_definitions.py:1352`), request `VerdictRequest{verdict, notes}`.
- 200 `TestRunEvidenceResponse`: 30 keys, including `verdict`, `verdict_reviewer`, `verdict_at`, `verdict_notes`, `candidate_is_current` and `base_release_is_current`.
- 422 `IneligibleForApprovalResponse{code, reason, message}`, with reasons `not_completed`, `checks_failed` and `linked_to_release` (the last from #269 C48).

**C268-2 (readiness)**
- `GET /readiness` (`:1410`) returns `DraftReadinessResponse{draft_lock_version, base_release_id, all_ready, blocking_agents, agents}`.

**C268-3 (cleanup)**
- It is a **method**: `AgentTestWorkbench.cleanup_unpublished_test_runs(self, session, *, per_case_limit=20)` (`agent_test_workbench.py:1647`), not a free function.
- `rg` finds no production caller (confirmed).

**C268-4 (frontend verdict controls)**
- `ALLOWED_ACTION_NAMES` has length 8 (`frontend/tests/fixtures/forbiddenActionNames.ts`). The length is pinned at `AgentDefinitionWorkbench.test.tsx:378` and `agent-definition-workbench.spec.ts:1518`.

**C269-1 (preview and publish)**
- `GET /release-preview` (`:1613`) returns `ReleasePreviewResponse` (C34).
- `POST /releases` (`:1632`), request `PublishReleaseRequest{lock_version, release_note}`, returns **200** (there is no `status_code=`) with `PublishReleaseSuccessResponse{release, previous_release_id, changed_agents, mappings, evidence, draft}`.
  - mappings are `PublishedMappingResponse{agent_definition_revision_id, content_hash, reused}`;
  - evidence is `ReleaseEvidenceResponse{agent_test_run_id, agent_key, test_case_id, evidence_kind, source_release_id}`.
- 409 responses: `StalePublicationResponse{code, expected_lock_version, current_lock_version, active_release, draft}`, `NothingToPublishResponse` and `PublicationNotReadyResponse{code, gaps[{agent_key, test_case_id, code}], readiness}`.
- 422: `PublicationValidationErrorResponse{code: invalid_publication, errors}`.

**C269-2 (publication service)**
- `publish_draft(self, session, *, expected_lock_version, release_note, actor, evidence_gate)` (`graph_configuration_publication.py:283-290`).
- `ApprovalEvidenceGate(*, readiness)` (`graph_release_evidence.py:152-160`).

**C269-3 (review page)**
- Page `/admin/agent-definitions/review` sits inside `RequireAdmin` (`App.tsx:55`).
- Test ids in `ReviewAndPublishPage.tsx`: `release-review-page`, `release-success-panel`, `release-stale-alert`, `release-not-ready-panel`, `release-nothing-panel`, `release-next-version`, `release-note-input` and `release-publish-button`.
- Tabs are `release-changes-tab` "Changes & Approvals", `release-diff-tab` "Definition Diff" and `release-history-tab` "Release History" (`:26-28`).
- The publish control's name is `Publish Graph Version ${next}` (`:335`).
- **`Review & Publish` is an `<a href>` link** (`AgentDefinitionWorkbench.tsx:138-141`), so Task 10 uses `getByRole('link', { name: 'Review & Publish', exact: true })`.

**C270-1 (history and rollback routes)**
- `GET /releases` (`:1856`) returns `ReleaseHistoryListResponse{active_release, releases[ReleaseHistoryEntryResponse{release_id, version_number, is_active, release_note, published_by, published_at, effective_from, effective_to, previous, restored_from, restored_by, changed_agents}]}`.
- `GET /releases/{v}` (`:1877`) returns `ReleaseDetailResponse{release, definitions, evidence}`. History evidence carries **`source`** (a `ReleaseIdentityResponse`), not `source_release_id`.
- `GET /releases/{v}/comparison` (`:1901`) returns `ReleaseComparisonResponse{active_release, release, agents[{agent_key, active_revision_id, historical_revision_id, same_revision, field_diffs[{field, active, historical}]}]}`.
- `GET /releases/{v}/rollback-preview` (`:1930`) returns `RollbackPreviewResponse{source, active_release, next_version_number, lock_version, default_release_note, restorable, blocked, issues, warnings, agents, evidence, draft_effect: dict[AgentKey, reset|kept|unchanged]}`.
- `POST /releases/{v}/rollback` (`:1963`), request `RollbackRequest{lock_version, release_note}`, returns 200 `RollbackSuccessResponse{release, restored_from, previous_release_id, changed_agents, mappings, evidence, draft, draft_effect}`.
- 409 codes: `stale_rollback`, `rollback_source_active` and `rollback_matches_active`. 422 codes: `rollback_incompatible` and `invalid_rollback`.
- **Plus a 404 `"Graph Version not found"`** on every `{version_number}` route (`agent_definitions.py:1706-1710`). The plan omits it.

**C270-3 (history tab)**
- Names `Inspect this version` and `Roll back to this version` (`ReleaseHistoryTab.tsx:27-28`), `Confirm rollback` and `Cancel rollback`.
- Test ids: `release-history-row-<v>`, `release-history-detail`, `release-comparison`, `rollback-preview`, `rollback-lineage`, `rollback-warnings`, `rollback-blocked-panel`, `rollback-note-input`, `rollback-confirm-button`, `rollback-cancel-button`, `rollback-stale-alert` and `rollback-success-panel`.

**C270-4 (rollback log)**
- `graph_release_rollback` is emitted by the **route** (`agent_definitions.py:1702-1708`), once per rollback call, with outcome and role key names only.

**Other request models** (all `extra="forbid"`, `strict=True`):
- `DraftSaveRequest{lock_version, candidate: {prompt_text, model{endpoint_name, temperature, max_tokens, top_p}, assembly_rules, schema_overlay}}`;
- `DraftLockRequest{lock_version}`, for the two upgrade routes;
- `CandidateTestRunRequest{test_case_id, lock_version}` and `BaselineTestRunRequest{test_case_id}`. Both run POSTs return **201**.

**Sessions**
- `/{id}/collaboration-history` **has** a response model: `CollaborationHistoryResponse{mixed_release_warning, has_legacy_evidence, groups[{actor_label, graph_version, mutation_count, last_mutation_at}]}` (`sessions.py:389-416`). This is the **C21 erratum**.
- The other sessions routes return plain dicts, whose graph projection keys are `graph_version`, `active_graph_version` and `is_older_than_active` (`session_manager.py:752-754`, `:788-789`, `:847-848`, `:1059-1060`).

**Task 11 components**
- `graph-version-status` is rendered by `frontend/src/components/Conversation/GraphVersionStatus.tsx:20-46`. Its text is ``Pinned Graph Version {graphVersion}{isOlder ? `; latest is ${activeGraphVersion}` : ''}``, so Task 11's sabotage edits `:32`.
- `mixed-release-warning` is in `MixedReleaseWarning.tsx:79`/`:185`.
- The app-shell mock is `setupMocks` (`frontend/tests/helpers/setup-mocks.ts:22`). Boot also reads `/api/setup/status` and `/api/user/current`.

**Proposed ruling:**
- These shapes replace the plan's table.
- Task 10's contract `response_model` / `request_model` dotted paths use the class names above.
- `collaboration-history` exchanges are validated against `CollaborationHistoryResponse`, not shape-only.
- The rollback-log assertion moves from Task 7 to Task 6 S15. Using `rendered_record`, the record's extra-key set is exactly the route's `{outcome, agent_keys}` set; Task 6 confirms the key names at `agent_definitions.py:1977+`.
- Tasks 6 and 10 add a 404 exchange (for example `GET /releases/99`) to the contract.

**Binds:** Phase B, blocking before Tasks 6, 9, 10 and 11.

**Cost if wrong:** The Python join points at non-existent classes. Or Task 7 waits for a log record its turns never emit. Or Task 10 uses `getByRole('button')` for a link, and it never matches.

---

### Correction 36 — Task 9: the `EXPECTED_ADMIN_ROUTES` literal (24 pairs) and its fixtures

**Overrides:** plan :727 ("Task 0-B fills from the integrated app"), and plan :726 (the non-admin fixtures at `:398-440`).

**Evidence:** `app.routes` gives exactly 24 `(method, path)` pairs under `/api/admin/agent-definitions`, all with `endpoint.__module__ == "src.api.routes.agent_definitions"`:

**Workbench and draft**
- GET `/workbench`
- GET `/model-endpoints`
- PUT `/draft/{agent_key}`
- POST `/draft/{agent_key}/protected-assembly-upgrade`
- POST `/draft/{agent_key}/schema-contract-upgrade`
- POST `/draft/{agent_key}/legacy-prompt-source`
- POST `/draft/{agent_key}/model-endpoint-probe`

**Test cases and runs**
- GET `/test-cases`, POST `/test-cases`
- PUT `/test-cases/{test_case_id}`, DELETE `/test-cases/{test_case_id}`
- POST `/draft/{agent_key}/test-runs`
- POST `/published/{agent_key}/test-runs`
- GET `/test-runs/{run_id}`
- GET `/test-cases/{test_case_id}/runs`
- POST `/test-runs/{run_id}/verdict`
- GET `/readiness`

**Releases**
- GET `/release-preview`
- POST `/releases`, GET `/releases`
- GET `/releases/{version_number}`
- GET `/releases/{version_number}/comparison`
- GET `/releases/{version_number}/rollback-preview`
- POST `/releases/{version_number}/rollback`

**Router and fixtures**
- The one router is `agent_definitions.py:161-165` (`prefix`, `dependencies=[Depends(require_admin)]`). `require_admin` is at `_authz.py:326` and `require_draft_write_principal` at `agent_definitions.py:168`.
- The non-admin helpers are `_force_admin(monkeypatch, is_admin=False)` and `_app_for(session_factory, …)` (`test_agent_definition_workbench_routes.py:155`, used at `:398-412`).
- Six handlers read their body through `await request.json()` (`:487`, `:638`, `:933`, `:1102`, `:1335`, `:1471`), so the `Request.json` patch is meaningful.
- An existing owner test already pins one router for the release routes: `test_graph_release_routes.py:343` (`test_release_routes_are_on_the_one_admin_router`).

**Proposed ruling:**
- `EXPECTED_ADMIN_ROUTES` is exactly the 24 pairs above.
- Task 9's one-router test generalises `test_graph_release_routes.py:343` to all 24 routes; it does not duplicate that test.

**Binds:** Phase B, Task 9.

**Cost if wrong:** The inventory is either RED on correct code (a miscounted route) or blind to a new route.

---

### Correction 37 — Task 6 harness: extend #270's acceptance seam; every graph-capable `POST /api/sessions` must send `graph_capable: true`

**Overrides:** plan :575 and :623 (the "`real_route_stack` recipe"), and plan :631, :640, :641 and :644 (the sessions calls).

**Evidence:**
- **The seam to extend.** It is #270's `acceptance_stack` (`test_graph_release_rollback_acceptance_postgres.py:106-137`), which is `real_route_stack` plus the `get_agent_test_workbench` override (C53) over `_fake_adapter_workbench` (`:96-103`). #270's `_session_manager_on` (`:140-163`) patches `src.api.services.session_manager.get_db_session`. #269's publication acceptance uses the same seam (`test_graph_release_publication_acceptance_postgres.py:101-141`).
- **`graph_capable` defaults to `false`.** `POST /api/sessions` (`sessions.py:79-127`) calls the global `get_session_manager().create_session(..., graph_capable=request.graph_capable)`, and `CreateSessionRequest.graph_capable` defaults to **`False`** (`src/api/schemas/requests.py:137-140`), so it persists a **null** pin.
- **The sessions routes also read other sources.** They use `Depends(get_db)` (`sessions.py:33`) and module-level `get_db_session` (`:69-74`).
- **Every principal is an admin in the seam.** `acceptance_stack` also sets `_admin_acl_probe = lambda _user: True` (`:129`), so C2 applies to it as well.

**Proposed ruling:**
- The Task 6 helper builds on `acceptance_stack` and `_session_manager_on`. It does not copy them: import them, or move them to a shared helper that both files import.
- It includes `src.api.routes.sessions.router` in the same app, with the `get_db` override plus the `session_manager.get_db_session` patch.
- S02 (`old-root`), S11 (`mid-root`), S12 (`new-root`) and S16 (`post-rollback-root`) send `{"graph_capable": true}`.
- One control conversation created with the default body must persist a null pin. It is recorded for Task 8's legacy case.

**Binds:** Phase B, blocking before Task 6.

**Cost if wrong:** Every S02/S11/S12/S16 pin is null, so S02 is RED on correct code and misrouted to #261. Or the sessions router writes to the conftest SQLite file instead of PostgreSQL.

---

### Correction 38 — Task 8 "every creator needs a pin": there are seven creators, not four

**Overrides:** plan :706 (parametrised over "root / chat auto-created / contributor / duplicate"), and C18 instruction 5.

**Evidence:**
- **The seven creators.** `CREATORS` (`tests/integration/test_mixed_release_creation_postgres.py:27-35`) is `explicit-root`, `chat-generated-id`, `chat-supplied-id`, `chat-service-sync`, `chat-service-streaming`, `contributor` and `duplicate`. It is driven by `_create(factory, creator)` (`:129`) and `_creator_patches(factory)` (`:175`), and #269's `test_graph_release_session_ordering_postgres.py:53-57` imports all three.
- **Seeding for the copy creators.** Contributor and duplicate seeding follows `_seed` (`session_ordering:85-110`).
- **Where 503 is raised.** "No active Graph Release available" is raised at `sessions.py:116-119`, `:377` and `:664`, and at `chat.py:360`, `:470` and `:654`.
- **Existing coverage.**
  - Unit (SQLite): `tests/unit/test_conversation_pin_creation.py:207` and `:291`.
  - PostgreSQL cases already in `test_persisted_graph_runtime_failures_postgres.py`: `:297`, `:337`, `:369`, `:398`, and also `:458`, `test_persisted_corruption_escapes_later_node_recovery`, which C18 did not list.
- **The removed-endpoint case.** A1's first turn reaches fixer (`test_conversation_pin_acceptance_postgres.py:60-71`, `_first_turn_outputs` `:209`), so the removed-endpoint case reuses A1. No new `FAKE_OUTPUTS` are needed for C18 step 3.

**Proposed ruling:**
- Parametrise the missing-active refusal over the imported `CREATORS` (7).
- For each creator, assert all of these:
  - the explicit error: HTTP 503, or `ActiveGraphReleaseUnavailableError` for the service creators;
  - no new `user_sessions` row;
  - the tripwire is unread.
- Name the five existing PostgreSQL cases as already landed.

**Binds:** Phase B, Task 8.

**Cost if wrong:** Three chat creators and the sync service creator are unguarded by the acceptance matrix, which is exactly the "every creator" claim of AC2.

---

### Correction 39 — CI facts the plan cites are stale: the `integration-graph` span, `DELIBERATE_EXCLUSIONS`, and the lint and typecheck jobs

**Overrides:**
- plan :51 ("`DELIBERATE_EXCLUSIONS` stays empty");
- plan :250, :965 and every "`test.yml:448-472`";
- plan :113 (the unit job lines).

**Evidence:**
- **`integration-graph`** is 33 files at `.github/workflows/test.yml:448-480`.
- **`DELIBERATE_EXCLUSIONS` is not empty.** In `tests/unit/test_ci_collects_integration_tests.py:37` it holds `test_graph_live_real_model.py`, and `tests/unit/test_e2e_matrix_covers_specs.py:51` has its own dict.
- **e2e matrix:** `test.yml:711-757`.
- **frontend-build:** `npx tsc -b` at `:616`.
- **ESLint:** there is no ESLint job.

**Proposed ruling:**
- "`DELIBERATE_EXCLUSIONS` is **unchanged**; #271 adds no exclusion."
- New PostgreSQL files are appended after `:480`.
- New specs are appended to the matrix in alphabetical position.

**Binds:** Phase B. Tasks 6, 7, 8, 10 and 11. Non-blocking.

**Cost if wrong:** An implementer "fixes" the exclusions dict to empty, which enrols the live real-model test in CI with real spend.

---

### Correction 40 — The text-read frontend files, re-derived (plan :64)

**Overrides:** plan :64 (the list), and C16 instruction 2.

**Evidence:** `rg -l "frontend/" tests/unit` plus the path constants in the join tests. Beyond the plan's list, these files are also read:
- `frontend/src/components/Admin/GraphRelease/reviewAndPublishState.ts` (`test_graph_release_client_join.py:46`, `test_graph_release_history_client_join.py:143`, which parse `ROLE_LABELS` line by line);
- `frontend/tests/e2e/agent-definition-workbench.spec.ts` (`test_prompt_assembler.py:1310`, `:1400`, which parse `const AFFECTED_ROLES`).

The forbidden-action sweep that C16 extracts is an inline closure at `agent-definition-workbench.spec.ts:1571-1580`.

**Proposed ruling:**
- Add both files to the text-read list.
- C16's extraction moves only the `sweep` closure body into `frontend/tests/fixtures/forbiddenActionHelpers.ts`, parameterised by a `Locator`. It must leave `const AFFECTED_ROLES` and its line format byte-identical.
- Re-run `tests/unit/test_prompt_assembler.py` in Task 10's GREEN.

**Binds:** Phase B, Task 10.

**Cost if wrong:** A reformat by the extraction silently turns a Python join test RED.

---

### Correction 41 — The epic invariant owner tests (Step B4)

**Overrides:** plan :272 ("A missing owner test becomes a Task 12 addition").

**Evidence:**

| Invariant | Owner test |
|---|---|
| One model binding | `tests/unit/test_agent_runtime.py:769` `test_structured_output_binding_has_one_call_site_and_the_probe_has_none`. `rg -c "with_structured_output\(" src` = 1. |
| One draft-content writer | `tests/unit/test_graph_release_rollback.py:1586` `test_candidate_hash_writers_are_the_allowlisted_attribute_and_builder_sites`, and `:1611` `…writer_scan_detects_each_write_form`. |
| One both-parent locker | `tests/unit/test_graph_parent_lock_is_single_sourced.py:62`. |
| One publication core | `tests/unit/test_graph_release_rollback.py:1072` `test_restore_writes_through_the_one_publication_core`. |
| One admin router | `tests/unit/test_graph_release_routes.py:343`, release routes only. |
| One gate, one counter (frontend) | `draftEditorState.test.ts:1115`, `:2654`; `reviewAndPublishState.test.ts:477`, `:508`, `:516`; `TestRunPanel.test.tsx:303`; `AgentDefinitionWorkbench.test.tsx:3319`. |
| One reducer per page | No structural pin. It is covered behaviourally only. |

**Proposed ruling:**
- The table above is the Task 14 Step 6 re-run list.
- The "one reducer per page" gap is **not** a Task 12 addition. Task 12 is the deletion task, and a structural `useReducer` count is brittle. Task 14's epic review rules on it as covered-with-ruling.
- The one-admin-router owner test is generalised in Task 9 (C36).

**Binds:** Phase B, Task 14.

**Cost if wrong:** Task 12 grows a frontend change outside its scope. Or the epic review has no owner list to re-run.

---

### Correction 42 — The Phase B carries, each bound to a task

**Overrides:** nothing in the plan. It adds the `progress.md` "Phase B start" carries to the task steps.

**Evidence:** The `progress.md` "Phase B start" carries, re-probed:
1. The monolith fallback. See C24.
2. id ≠ version is **closed**. #270's whole-branch review §5 found no version resolved by id.
3. The epic-review items:
   - the Q7 rollback caveat (#270 review O1);
   - the C32 endpoint policy on rollback;
   - the `test_usage_service` midnight flake;
   - the `test_shared_deck_mutation_attribution` hang. It did not reproduce here: 60 passed in 17.3 s under `timeout 120`.
   - `test_dependencies_resolve_on_proxy`. It is `@live` + `@slow` (`tests/unit/test_dependencies_resolve.py:149-151`), and **it is not deselected in local runs**, because there is no `addopts` `-m "not live"`. It needs the network, and it passed in this baseline run.
4. L0 is taken only through `_lock_current_parents`. The AST scanner is `test_graph_parent_lock_is_single_sourced.py:62`.
5. The forbidden-action list has 8 names (C35).
6. There is no ESLint job (C39).

**Proposed ruling:**

| Carry | Bound to | Instruction |
|---|---|---|
| 1 | Task 8 | C24 |
| 2 | Task 14 Step 6 | Record "closed by #270 review §5". No test is needed. |
| 3 | Task 14 Step 6 and every full-unit gate | Each full-unit gate records its UTC start and end, and a `test_usage_service` failure inside ±5 min of 00:00 UTC is the flake cause. A `test_dependencies_resolve_on_proxy` failure with a network error is the network cause, not a regression. `test_shared_deck_mutation_attribution.py` always runs under `timeout 120`, and exit 124 is the hang cause. The epic review rules on Q7 and on C32-on-rollback as covered-with-ruling or open. |
| 4 | Task 14 Step 5 | The writer table cites the scanner as GREEN, and confirms #271 adds no locker. |
| 5 | Tasks 10, 11, 14 | Assert `ALLOWED_ACTION_NAMES` length is still 8. #271 adds no exemption. |
| 6 | Tasks 4, 10, 11, 14 | ESLint runs locally on every touched frontend file (C27). Task 14 lists "add a CI lint job" as a follow-up issue for the user. |

**Binds:** Phase B, the named tasks.

**Cost if wrong:** A known flake is misread as a regression, or a real regression is dismissed as the flake.

---

### Correction 43 — Task 13 without the dev-workspace check (#266 m9)

**Overrides:** plan :933-935 (the Files block "Task 0 records the name").

**Evidence:**
- The readiness check is at `src/services/model_endpoint_catalog.py:242-271`:
  - `config_update = getattr(state, "config_update", None)`;
  - `IN_PROGRESS`, `UPDATE_FAILED` and `UPDATE_CANCELED` each have their own code;
  - `ready != READY` **or** `config_update != NOT_UPDATING` gives `endpoint_not_ready`. So `None` (absent) is refused.
- The unit test file is `tests/unit/test_model_endpoint_catalog.py`. The draft-side use is in `tests/unit/test_graph_configuration_draft.py`.
- The user's authorisation is outstanding.

**Proposed ruling:**
- Task 13 does **not** dispatch without the user's explicit authorisation. No speculative "absent" code is written.
- Record "m9 open: release gate unverified" in `progress.md` and in the Task 14 final report. The local merge may proceed (OQ4), but the epic is not declared shippable.
- If authorised, run only Step 1's read-only `databricks serving-endpoints get … --profile tellr-dev -o json`, then 2a or 2b as planned. The files are the two named above.

**Binds:** Phase B, Task 13.

**Cost if wrong:** Speculative code relaxes a readiness check that may be correct. Or the epic is reported shippable with its highest-impact external assumption unverified.

---

### Correction 44 — Task 12's retained-bundle ledger literals, as re-read

**Overrides:** plan :905-906 ("write the full 64-hex literals, as re-read at Task 0-B").

**Evidence:**
- Protected assembly: `prompt_assembler.py:43` and `:377`.
- Schema contracts: `agent_schema_registry.py:49-71`.

**Proposed ruling:** Use these literals.
- **Protected assembly:**
  - v1 `e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852`;
  - v2 `fb651a0d28276a0daf7b0db09f2648eb6b50d9429a7100cfaf69e3fc2b08592a`.
- **Schema v1:**
  - architect `a03440e5a8578cf3ced4fd1e83219466ccb0abb5f3d7b04f7836fefd4423fafd`
  - data_analyst `610545fe1d094f2544a5c602c2ebb45f542b813bf47e347e96ba7e22a6bfc281`
  - builder `fc4bd6a9020b228a79cc0d933066478225947605916e05bd6f44ba7eccc82387`
  - build_reviewer `50963d37738f8c97b12caa7688d282d3174a1e0c5e3606c8ec7a73c5ae50c70d`
  - fixer `7a4e984c602d16ea73c2f5f3f26ac385c440527001fa14b1cfb5c1245de12297`
  - fix_reviewer `31ff0a6d02cefb7db4cd2c499b4e7905fdadcda789c658e1c7605cdde01020df`
  - deck_reviewer `56c7ce141e07a70fc2c57f614e915ebb9e3914d24b3c11057401c4cc1c637467`
- **Schema v2:**
  - architect `a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122`
  - data_analyst `0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5`
  - builder `65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad`
  - build_reviewer `20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1`
  - fixer `a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143`
  - fix_reviewer `bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99`
  - deck_reviewer `c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3`
- They match the plan's prefixes and `V1_SCHEMA_CONTRACT_DIGESTS` (`test_graph_definition_manifest.py:754`).
- Assert resolution per C32.

**Binds:** Phase B, Task 12.

**Cost if wrong:** A transcription error makes the ledger RED on correct code.

---

### Correction 45 — "Task 1's baseline" after the rebase; `TASK1_BASE` is no longer an ancestor

**Overrides:** plan :491, :920 and :947 ("cause set must equal Task 1's"), and plan :38 (read with the rebase).

**Evidence:**
- The `TASK1_BASE` file holds `0500629354d5…`, the pre-rebase base. `git merge-base --is-ancestor 0500629… HEAD` is false after the rebase. This is expected: `a08389ec3` is an ancestor of `INTEGRATION_BASE`, and the Phase A patches are patch-id-identical (`predecessor-heads.md`).
- The full unit run at HEAD `9a63ab1b7` (`reports/preflight-phase-b.md`) gave **2 failed / 7169 passed / 110 skipped**. The two failures are exactly the deploy_autoscaling pair.

**Proposed ruling:**
- "Task 1's baseline" means the Phase B cause set recorded in `preflight-phase-b.md`:
  - exactly the two `test_deploy_autoscaling.py::TestGetOrCreateLakebase` nodes, with their two causes;
  - 110 skips in the four listed cause groups.
- Do not rewrite `TASK1_BASE`. It stays an immutable Phase A record.

**Binds:** Phase B, every task's GREEN step.

**Cost if wrong:** A reviewer compares against the pre-rebase six-failure set and misses a new cause hidden by a count difference.

---

### Correction 46 — Task 7 seams confirmed, and one sequencing rule with Task 8

**Overrides:** nothing. It confirms plan :669-692 with citations, and adds one ordering rule.

**Evidence:**
- **`graph_chat_env`:** `tests/integration/test_graph_mode_turn.py:342`.
- **In `test_conversation_pin_acceptance_postgres.py`:**
  - `A1_ROLES` at `:60-71`;
  - `_OrderedAdapter` at `:83`;
  - `_first_turn_outputs` at `:209`;
  - `Send` recording at `:426-432`.
- **The pin load:**
  - It happens at `src/services/graph/builder.py:345`.
  - `state.update` runs after `dict(initial)` (`:352-357`), so a seeded `graph_release_id` is overwritten. That is exactly the plan's step 3 premise.
- **The logging allow-list:** `_LOGGED_IDENTITY_FIELDS` is at `agent_runtime_identity.py:123-129`.
- **The model adapter:** `DatabricksModelAdapter(*, model_factory, client_factory, transport_options)` is at `agent_runtime.py:506-515`.
- **Unchanged since `a08389ec3`:** `conversation_pins.py`, `graph/`, `session_manager.py`, `sessions.py`, `chat.py`, `chat_service.py`, `agent_runtime*.py`, `persisted_graph_release.py`, `prompt_assembler.py` and `agent_schema_registry.py` are byte-unchanged since `a08389ec3`. #268–#270 touched none of them.

**Proposed ruling:**
- Task 7 drives `send_message_streaming`. Task 8 (C24) edits `chat_service.py`.
- So if Task 8 lands after Task 7, re-run Task 7's file in Task 8's GREEN step.
- Otherwise, dispatch Task 8 before Task 7. Both are "sequence by file".

**Binds:** Phase B, Tasks 7 and 8.

**Cost if wrong:** C24's change to the SSE path breaks Task 7's turn driver unnoticed.

---

## Per-task self-consistency (Phase B)

For each task: does the Files block cover every file the steps (plus the corrections) touch? Does every consumed name exist at HEAD? Is each sabotage anchor on the executed path?

| Task | Files block complete? | Consumed names exist? | Sabotage anchors valid? | Blocking corrections | Verdict |
|---|---|---|---|---|---|
| 2 | Yes, with the C28 site list | `logging.makeLogRecord` ✓ | ✓ (`pathname` exclusion; `exc_text` branch) | C23 | Consistent after C28 |
| 3 | Yes (C29: unchanged) | `load_graph_v1_manifest`, `definition_content_hash`, `ResolvedDefinition`, `GraphReleaseNotFoundError` (`persisted_graph_release.py:31`), `AgentRuntime(...)` ✓ | Controller ✓; reviewer per C10 | C10 | Consistent |
| 4 | **No.** C27: only `findings-drawer.spec.ts` + the new `.d.ts` | `tsconfig.*` ✓ | Controller per C27 (35/TS1484); reviewer ✓ | C3, C25, C26, C27 | Consistent after C25–C27 |
| 6 | **No.** It needs the shared seam from `test_graph_release_rollback_acceptance_postgres.py` (import or move, C37), plus the sessions router | `acceptance_stack`, `_session_manager_on`, `definition_field_diffs`/`_DIFF_FIELDS`, `restore_release` ✓ | Controller per C34; reviewer ✓ (`rollback.py:383`) | C1, C2, C6, C9 (Task 6 stage), C33, C34, C35, C37 | Consistent after corrections |
| 7 | Yes | All of C46 ✓; `AgentSchemaRegistry` resolution per C32 | Controller ✓ (`builder.py:345`); reviewer per C8 | C8, C9, C32 | Consistent; sequence with Task 8 (C46) |
| 8 | **No.** It needs `chat.py`, `chat_service.py` and `test_engine_mode_wiring.py` (C24) | `CREATORS`, `_create`, `_creator_patches` ✓; bundle seams per C32 | Controller ✓ (`conversation_pins.py:151-160`); reviewer per C7; extra controller per C24 | C7, C18, C24, C38 | Consistent after C24 (**needs a user decision**) |
| 9 | Yes | `require_admin`, `require_draft_write_principal`, `_force_admin`, `_app_for` ✓ | Controller ✓ (`agent_definitions.py:164`); reviewer ✓ (`session_manager.py:752`) | C36 | Consistent |
| 10 | **No.** C16 and C40 add `forbiddenActionHelpers.ts`, `agent-definition-workbench.spec.ts` and the acceptance PG file | Class paths per C35; `setupMocks` ✓ | Controller ✓; reviewer name `Publish Graph Version 2` (C15) ✓ | C1, C11, C16, C21, C25, C35, C40 | Consistent after corrections |
| 11 | Yes | `GraphVersionStatus.tsx:32`, `MixedReleaseWarning.tsx` ✓ | Controller ✓ (`GraphVersionStatus.tsx:32`); reviewer ✓ | C9, C11, C25, C35 | Consistent; depends on Task 6's S12b exchange (C9) |
| 12 | Yes, plus the C14/C29 import updates (`test_graph_configuration_draft.py:2917`, `test_persisted_agent_runtime.py:23`) if `RecordingAgentInvocationIdentitySink` moves | `V1_SCHEMA_IDENTITIES` ✓; guard 5 attribute `_persisted_release_loader` (`agent_runtime.py:803`) ✓ | Controller per C6; reviewer ✓ (`_default_bundles`) | C6, C13, C14, C30, C31, C44 | Consistent after C30/C31 (guard 3 would otherwise be permanently RED) |
| 13 | Yes (C43 names the files) | `model_endpoint_catalog.py:242-271` ✓ | ✓ | C43 (user authorisation) | **Does not dispatch without the user** |
| 14 | Yes | Owner list per C41; every gate per C25/C42/C45 | Final sabotage anchor ✓ (`persisted_graph_release.py:96`, `_cache: dict[int, …]`) | C41, C42, C45 | Consistent |

## Producer/consumer table (Phase B)

| Producer (task) | Output | Consumers | Shape source |
|---|---|---|---|
| Task 2 | `tests/fixtures/log_records.py`: `rendered_record`, `STANDARD_LOG_RECORD_ATTRS` (+`taskName`, C28) | Tasks 6 (S07 C33, S15 rollback log C35), 7 (log contract), 8 | plan :371 + C28 |
| Task 3 | `tests/fixtures/packaged_release_loader.py`: `PackagedGraphV1Loader`, `packaged_v1_runtime`, `PACKAGED_RELEASE_ID`/`VERSION` | Task 12 (drops the parity half), migrated unit files | plan :447-470 + C10, C14 |
| Task 4 | `frontend/tsconfig.e2e.json` + `tests/types/browser-modules.d.ts` + the Python guard | Tasks 10, 11, 14 (typecheck gate per C25) | C3, C25–C27 |
| Task 6 | `tests/integration/graph_lifecycle_journey.py`: `Stage`, `stage()`, `require()`, `CodeDefaultTripwire` (traps `_SKILLS` + the manifest, C6), `LifecycleJourney.run_to()`, `RecordedExchange`; stages S01–S12, S12b (C9), S14–S16, S18 | Task 7 (`run_to("S16")`), Task 8 (`run_to("S12")`), Task 10 (`write_contract`, shape test), Task 11 (exchanges S02, S11-mid-root, S12, S12b, S16), Task 12 (drops two tripwire targets) | plan :578-647 + C1, C2, C9, C33, C34, C35, C37 |
| Task 7 | S13, S17 stages; the turn driver | Task 8 (the turn driver), Task 12 gate, Task 14 final sabotage | plan :669-692 + C8, C32, C46 |
| Task 8 | `_conversation_state`; production fix at the 3 fallback sites (C24) | Task 12 gate, Task 14 Step 5(4) | plan :703 + C7, C18, C24, C38 |
| Task 9 | `EXPECTED_ADMIN_ROUTES` (24, C36), projection test | Task 12 gate, Task 14 | C36 |
| Task 10 | `graphLifecycleContract.json`/`.ts` (`loadContract`, `installContract` with C1 cursor replay), `forbiddenActionHelpers.ts` (C16/C40), the admin journey spec | Task 11 | plan :753-758 + C1, C16, C21, C35, C40 |
| Task 11 | The conversation journey spec | Task 12 gate | plan :798-812 + C9 |
| Task 12 | Deletion + `test_lakebase_only_runtime_contract.py` + `test_retained_bundle_ledger.py` | Task 14 | plan :827-927 + C6, C13, C14, C30, C31, C44 |
| #268/#269/#270 (upstream) | Routes, models and test ids per C35; `acceptance_stack`/`_session_manager_on` (C37); `CREATORS` (C38) | Tasks 6–11 | C35, C37, C38 |

## Blocking summary for Phase B (supersedes the Phase B part of the earlier summary where they differ)

- **Before Task 2:** C23 (the scoped re-review, now covering C24–C46).
- **Before Task 3:** C10.
- **Before Task 4:** C3, C25, C26, C27.
- **Before Task 6:** C1, C2, C6, C9, C33, C34, C35, C37.
- **Before Task 7:** C8, C9, C32 (S17 seam); sequence with Task 8 (C46).
- **Before Task 8:** C7 + **C24 (and a user decision)**, C38.
- **Before Task 9:** C36.
- **Before Task 10:** C1, C11, C16, C25, C35, C40.
- **Before Task 11:** C9, C11, C35.
- **Before Task 12:** C6, C30, C31, C44; the AC10 gate.
- **Before Task 13:** C43 (**user authorisation**).
- **Non-blocking:** C28, C29, C32 (Task 8/12 parts), C39, C41, C42, C45.

---

## Corrections 47–51 — errata from the C23 scoped re-review (2026-09-27)

Source: the C23 scoped re-review of C24–C46 at `78728e188` (controller dispatch; verdict GO for Task 2). C25–C32, C34, C36, C39, C41–C46 CONFIRMED; C28 confirmed. Notes: C31 guard 2 must also catch `ast.Import` (`import src.core.skills`); C32's `_default_bundles` lambda must capture the original before patching; C39 matrix is not strictly sorted (use nearest sorted neighbour); C40's text-read list is NOT exhaustive (`AssemblyEditor.tsx`, `template-viewer.spec.ts`, `slideDocument.ts`, `services/api.ts`, …) — any Task touching those files must re-grep the text-read tests.

### Correction 47 — erratum to C24 (BLOCKING Task 8)
(a) `/chat/async`: an `HTTPException(503)` raised at `chat.py:697` is inside the `try` opened at `:668`; `except Exception` at `:732` turns it into 500. Add an `except HTTPException:` (release the session lock; re-raise) BEFORE `except Exception`, or a typed exception with its own handler. (b) There is NO existing SSE mapping: the safe event (`pinned_graph_configuration_unavailable`) is emitted only inside `_send_message_streaming_graph.run_graph` (`chat_service.py:1913-1950`). At `:1141` the service must yield the typed pinned-config error event before raising (or `chat.py:563` gets an explicit `PersistedConfigurationUnavailableError` branch). (c) ~50 incidental fail-open dependents go RED when resolution is bare: 22 in `tests/unit/test_chat_session_creation.py`; `test_chat_service_no_singleton.py::…test_streaming_calls_build_agent`; `test_session_naming.py::TestSessionNamingInStreaming` ×2; 24 in `tests/integration/test_streaming.py`; `test_api_routes.py::test_chat_async_submit`. Task 8's Files block adds them, plus a fixture patching `src.api.services.chat_service.resolve_engine_mode` for tests that are not about resolution. (d) The `:1141` sabotage needs a resolver that returns `monolith` on the first call and raises on the second (an always-raising resolver fails at the route first, so the `:1141` restore stays GREEN). (e) Accepted and documented: on async and SSE turn 1 the user message (and the async `chat_requests` row) is already persisted before resolution and remains after the 503/error. Lock release: `/chat/stream` releases explicitly before raising at `:490` (the generator's `finally` at `:583` never runs); `/chat/async` in the new `except HTTPException` clause; `:1141` needs nothing extra (the generator's `finally` releases).

### Correction 48 — erratum to C33 (BLOCKING Task 6)
The C37 harness wires `RecordingAgentInvocationIdentitySink` (`rollback_acceptance:96-103`), so the "zero `persisted_agent_invocation` log records" half of S07 can never go RED there. S07 must ALSO assert the workbench runtime's Recording sink `.calls` is unchanged across S07 (reach it via `workbench._runtime_override._identity_sink`), or parameterise the helper with a `LoggingAgentInvocationIdentitySink`.

### Correction 49 — erratum to C35 (BLOCKING Task 10)
`CollaborationHistoryResponse` (+ its group model) lives at `src/api/routes/sessions.py:389-416`, not in `src.api.schemas`, and its `model_config` is `{}` (NOT `extra="forbid"`). Task 10 asserts exact key-set equality and uses the dotted path `src.api.routes.sessions.CollaborationHistoryResponse`. `PATCH /{id}/global` has `DeckGlobalPermissionResponse` (`:268`). The rollback log is emitted by `_log_rollback` (`agent_definitions.py:1845-1848`): success extras `{outcome, agent_keys}`, error paths add `error_class` (`:2007-2013`, `:2061-2067`).

### Correction 50 — erratum to C37 (BLOCKING Task 6)
`sessions.py:69-74` lazily imports `src.core.database.get_db_session`; the `session_manager.get_db_session` patch does not cover it — any stage hitting `GET /api/sessions/{id}/slides` patches `src.core.database.get_db_session` too. `acceptance_stack` builds its own `FastAPI()` and yields `(factory, client, adapter)`: Task 6 uses `client.app.include_router(sessions_router)` (ruling: the smaller change; no shared-helper refactor of #270's file).

### Correction 51 — erratum to C38 (BLOCKING Task 8)
`_create` calls the manager and service directly, so all 7 creators raise `ActiveGraphReleaseUnavailableError`, never HTTP 503. Task 8 asserts `pytest.raises(ActiveGraphReleaseUnavailableError)` for all 7 through `_create`; the route-level 503 is a separate HTTP parametrisation over the 5 route creators (or cited as owned by `test_conversation_pin_creation.py:291`). The `chat-service-streaming` creator passes `request_id`, so it never reaches `chat_service.py:1141`.

### Correction 52 — production defect found by Task 7: pinned-runtime errors become `TypeError` inside any `@contextmanager` (BLOCKING Task 8)

**Evidence:** `PersistedConfigurationUnavailableError` and `PinnedInvocationEndpointError` (`src/services/persisted_graph_release.py:39-68`) are `@dataclass(frozen=True, slots=True)` subclasses of `RuntimeError`. Raised through a `@contextmanager` (LangGraph runs every node inside `set_config_context`), they surface as `TypeError: super(type, obj): obj must be an instance or subtype of type`. Controller-reproduced with no database (a plain `@contextmanager` + `raise`): both classes → `TypeError`. Consequence: a node-raised pinned-runtime failure (bundle unavailable, invalid definition, Lakebase down, removed endpoint) reaches `chat_service.py:~1914` as a `TypeError`; the safe `pinned_graph_configuration_unavailable` event and its log are never emitted, the ERROR event leaks internal text, and `:~2030` re-raises the `TypeError`. Green today only because the envelope tests fake `invoke_graph` or raise before any node runs.

**Ruling:** Task 8 owns the fix (it already owns the safe-error path, C24/C47). Make both exceptions safe to traverse context managers — drop `slots=True` (keep `frozen` only if `__traceback__` assignment still works; otherwise plain classes with read-only properties), preserving their fields, `__str__` and `__post_init__` validation. Add a RED-first regression test that raises each through a real LangGraph node (or `set_config_context`) and asserts the exact typed exception and the safe event, per the recipe in `task-7-report.md`.

**Cost if wrong:** during a pinned-configuration outage users get a leaked internal `TypeError` instead of the safe, typed error event.
