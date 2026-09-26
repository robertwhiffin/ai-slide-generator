# #266 whole-branch review: exact model endpoint discovery and validation

- Branch `plan/model-discovery-266`, HEAD **`39f32a4e2933fbd3961a5915aecaa37e5864bc0f`**. Range `50c8cbf35..HEAD`.
- The range has 49 commits, not the 48 in the brief. The 49th is the rebase-record docs commit `39f32a4e2` itself. It has 0 merges and is 0 behind `feat/langgraph-core`.
- Reviewer: whole-branch gate (Opus). No subagents, no installs. GitHub was read-only: `gh api user` returned `robertwhiffin`.
- Inputs read: issue #266; design §§6, 7.2, 10, 13.1, 14–17; the research note; the plan's global constraints; PLAN-CORRECTIONS c1–c23; `progress.md`; all task reports and reviews; the production diff of every file in the range.

## Verdict: MERGE WITH LISTED FIXES

| Severity | Count | Must-fix before local merge |
| --- | ---: | --- |
| Critical | 0 | — |
| Important | 1 | **I1: yes** |
| Minor | 9 | none. m1 and m2 are recommended for the same fix wave. |

**Critical / Important**
- **I1 (Important, MUST-FIX): the save PUT runs the remote endpoint check on the event loop, while it holds the exclusive draft lock.**
  - Where: `src/api/routes/agent_definitions.py:537` is `async def save_agent_definition_draft`. At `:587-589` it calls `GraphConfiguration(remote_endpoint_validator=...).save_editable_model_draft(db, ...)` synchronously. That call reaches `graph_configuration_draft.py:421` `_validate_remote_endpoint`, which calls the Databricks `serving_endpoints.get` inside `with session.begin()` FOR UPDATE.
  - Measured: a scratch test in the temp worktree (never committed, deleted) injected a validator that calls `asyncio.get_running_loop()` through `_app_for`. It recorded `[True]`, so the remote check ran with the loop running. The probe route's identical guard (`test_model_endpoint_probe_route_calls_the_model_off_the_event_loop`, `:4406`) records `[False]`, because `probe_agent_definition_model_endpoint` uses `run_in_threadpool` (`:767`).
  - Why it matters (multi-worker blast radius):
    - During each save, the worker's whole event loop is frozen for the remote round trip. Every SSE chat stream, health check and request on that worker stalls with it.
    - In an outage the freeze lasts up to the C8 bound: a 5 s retry window plus a 3 s in-flight request, plus one server-controlled `Retry-After` sleep and any OAuth refresh (m3).
    - A concurrent save routed to another worker blocks *its* event loop on the FOR UPDATE row wait for the same duration.
    - So one slow endpoint check can stall every uvicorn worker (4 by default), not just one draft.
    - Before #266 the PUT also did synchronous DB work on the loop, but its lock hold was milliseconds. #266 turns it into network-bounded seconds.
    - Task 5 identified exactly this hazard for the probe (task-5-report §5). No task review applied it to the Task 3 PUT wiring.
  - Fix:
    - Wrap the facade call in `await run_in_threadpool(...)`, exactly as the probe does. The `db` session is used sequentially from one thread, as it already is in the probe.
    - Add a PUT sibling of the `:4406` loop-observer test, with its sabotage (remove the threadpool wrap → RED).
    - Optional: add the PG lock-waiter case from a second worker thread.

**Minor (graded; none must-fix)**
- **m1 (should-fix, test-only): the "any served entity" discovery rule is unpinned.**
  - `model_endpoint_catalog.py:182-189` includes an endpoint when *any* served entity has `foundation_model`.
  - My survivor sabotage (below) restricted the scan to the first entity. All 295 catalog and route tests stayed GREEN, because every fixture's foundation entity comes first.
  - Add one fixture with `[external/None entity, foundation entity]`.
- **m2 (should-fix, wording): the probe's 400/404/422 → `unsupported_structured_output` message overclaims.**
  - `model_endpoint_probe.py:65-69,114-118`. Under the ruled table, a deleted endpoint (404), a legacy pre-#266 name that never passed remote validation, or a saved `max_tokens` above the model limit (400) is all shown as "This endpoint does not support structured output."
  - AC6 is still met at save time (`endpoint_unknown` is exact). But the probe copy should say that the endpoint *rejected the structured-output test request*, not that it lacks the capability.
  - Keep the code and status: this is the controller's ruling and it is not re-litigated.
- **m3 (accept, follow-up): residual unbounded windows under the lock (C8 parked).**
  - A server `Retry-After` sleep is not clamped to the deadline. The SDK `retried` loop sleeps `retry_after_secs`, then checks the deadline, so there is at most one extra sleep.
  - OAuth refresh inside the shared header factory, and `get_system_client()` first-call auth resolution or external-browser `authenticate()`, both run inside the save's lock.
  - Production Apps start with a warm system client. I1's threadpool fix removes the event-loop part. The lock part remains bounded by the platform's `Retry-After`.
  - Track it as a follow-up; it is not a blocker.
- **m4 (accept, follow-up): Task 6 m1, the unjoined probe failure contract.** See the queued rulings.
- **m5 (should-fix copy): Task 4 M-1.** A non-retryable `catalog_forbidden` alert still says "Use Refresh models to try again" (`DefinitionEditor.tsx:484`). Append the retry sentence only for `retryable`.
- **m6 (follow-up): `openai` is not declared in the app wheel.** See the queued rulings.
- **m7 (out of scope, file an issue): another C4-class path exists outside #266.**
  - `src/services/tools/model_endpoint_tool.py:75` calls `client.serving_endpoints.get(endpoint_name)` with the same unescaped SDK interpolation.
  - The name there is user-configured, and the call runs under the *user* (OBO) client (`:231`).
  - It is pre-existing, and not an endpoint-name path of the Agent Definition.
- **m8 (forward note for the publish ticket): no publication path exists yet.** `GraphRelease(` is constructed only in `graph_configuration_bootstrap.py:249`. When publication lands, it must run the C4 policy (and ideally remote validation) on each published endpoint, so that a pre-#266 draft row cannot be promoted unchecked.
- **m9 (verification gate before release, not before local merge): the readiness rule rests on an unverified remote fact.** `model_endpoint_catalog.py:262-270` rejects any `get` result whose `config_update != NOT_UPDATING`, including an absent value. Because *every* save revalidates the endpoint, even a prompt-only save, a pay-per-token system endpoint that omits `config_update` would make every save of the seeded role fail with `endpoint_not_ready`. I could not verify this (no workspace access; see "Declined to judge"). Probe `get databricks-claude-opus-4-6` once on the dev workspace (deploy-tellr-dev) before the epic ships, or treat an absent `config_update` as not-updating.

## 1. Ticket-level spec review

| # | Acceptance criterion / design clause | Verdict | Evidence |
| --- | --- | --- | --- |
| AC1 | First-party API/SDK contract identified, with permissions and failure behaviour | PASS | `docs/research/2026-09-22-databricks-model-endpoint-discovery.md:10-24` (decision), `:28-53` (list/get contract), `:55-65` (no `system.ai` API exists), `:67-92` (scopes, ACLs, failure modes). The code implements exactly that: `model_endpoint_catalog.py:163-211` (one `list()` call, `foundation_model` classification) and `:213-270` (`get(name)`, exact-name and state checks). I re-probed SDK 0.112.0 and the 0.120.0 wheel: `get` still interpolates `f"/api/2.0/serving-endpoints/{name}"`. |
| AC2 | Searchable, refreshable list of discovered system models | PASS | Catalog owned once per workbench (C16): `AgentDefinitionWorkbench.tsx:39-73`. Search and Refresh: `DefinitionEditor.tsx:464-478`. The `radiogroup` is at `:488`. The GET is at `routes/agent_definitions.py:503-534`. Tests: routes `:3574` (populated), `:3599` (empty), `:3616` (failure envelope). Playwright "model endpoint catalogue 503 … recovers through Refresh models", 69/69. |
| AC3 | A custom name is allowed, but never a URL | PASS | Server policy at `model_endpoint_catalog.py:81-103` (URL prefix, `/ \ ? # %`, controls, `.`/`..`). It runs before the stale check in both saves (`graph_configuration_draft.py:412,471`) and defensively before `get` (`:215`). Client mirror at `draftEditorState.ts:583` and `:601`. TS↔Python join: `tests/unit/test_endpoint_name_policy_client_join.py`. The "Custom endpoint name" field is at `DefinitionEditor.tsx:522`. |
| AC4 | Exact names stored, never floating family aliases | PASS | Selection copies `item.name` exactly (`DefinitionEditor.tsx:502`). Remote exact-name equality is at `model_endpoint_catalog.py:235-240` (`endpoint_name_mismatch`). The adapter delegates the unchanged name (`graph_configuration_draft.py:277-280`; test `:3716`). Nothing trims or rewrites it. |
| AC5 | The seeded Opus endpoint stays exact and does not auto-advance | PASS | No code path writes `endpoint_name` except an explicit edit and Save. Vitest "a newer discovered item never moves the seed until it is explicitly selected and saved". Task 6 controller sabotage `TASK6_CONTROLLER_AUTO_ADVANCE_SABOTAGE` RED 8/177. |
| AC6 | Permission errors, discovery failures, unknown endpoints and unsupported structured output are observable | PASS (m2, m5 wording) | Discovery 403/503 (`routes:137-148`, `_CATALOG_FAILURE_STATUS`). Save 422 codes from the catalog table (`catalog.py:218-270`). A system-client failure is typed (`graph_configuration.py:67-76`, `routes:115-120`). Probe 403/422/503 (`routes:147-151`, `model_endpoint_probe.py:110-185`). The UI alerts at `DefinitionEditor.tsx:482-486` and `ProbeResultView`. |
| AC7 | An injected production adapter; tests use deterministic fakes | PASS | FastAPI dependencies `get_remote_endpoint_draft_validator`, `get_model_endpoint_catalog` and `get_structured_output_probe` (`routes:89-141`). Fakes: `FakeModelEndpointCatalog` (`catalog.py:281`) and `FakeStructuredOutputProbe` (`probe.py:202`). `_app_for` defaults to the fakes. Production wiring is sabotage-proved (Task 3 S01/S02, Task 5 M20). |
| AC8 | Backend and frontend tests cover refresh, exact selection, manual validation, empty results and failure recovery | PASS | Backend: catalog 60, draft endpoint rows, routes (discovery, PUT, probe), the PG stale loser and probe lock-release. Frontend: Vitest 486/486 and Playwright 69/69. This includes empty discovery, 503 recovery, manual server-validation failure and the URL-rejection zero-PUT test. |
| §6 | The seed is the exact `databricks-claude-opus-4-6` and never floats | PASS | As AC5. The only release constructor is the bootstrap (`graph_configuration_bootstrap.py:249`). |
| §7.2 | ModelCatalog discovers and validates; ports are injected | PASS | `model_endpoint_catalog.py` is the only serving-SDK boundary. "`system.ai`" is product vocabulary with no verified API (research `:55-65`), so `foundation_model` classification is used. |
| §10 | Search/refresh list, advanced manual field, name not URL, local + server ranges | PASS | As AC2 and AC3. The "Advanced" label is at `DefinitionEditor.tsx:519`. "Tested before approval": the probe is the #266 part, and approval gating belongs to #267+. |
| §13.1 | Centre tabs are Prompt, Model, Output Schema, Assembly; closed status vocabulary | PASS | Discovery and probe live only in the Model tab. The probe never changes status ("This result does not change the draft or its status."; the reducer never touches status, Task 6 M7). |
| §14 | Distinct interfaces for discovery and manual validation | PASS (note) | Discovery is its own GET. Manual validation is exposed through the save PUT (ordered 422) and the saved-candidate probe, not a dry-run endpoint. The reviewed plan chose this and it satisfies the bullet. |
| §15 | Unknown endpoint gives a clear error; stale save gives 409 | PASS (m2) | The save gives `endpoint_unknown`. The probe's 404 wording is m2. The stale check precedes all remote I/O (draft `:3291`, PG stale loser). |
| §16 | Custom endpoints are names, not URLs; admin-only | PASS | C4 policy on both sides. The router's `require_admin` runs before the body or catalog is touched (routes tests `:3671` and `:4494`; Task 3 R1). |
| §17.4 | Frontend: discovery, refresh, manual entry, exact selection | PASS | As AC8. |
| tellr-code-review §1 | Multi-worker coherence | PASS | No new process-lifetime state. Catalog state is client-side and per-mount. Server factories are built per request, and the probe reads the DB every time. **I1 is the multi-worker defect in this range.** |
| tellr-code-review §2 | huashu chain | N/A | Untouched. |

## 2. Endpoint-name path table

| Path (input → Databricks/model call) | Where the C4 name policy runs | Remote validation (and lock held) | Pinning tests |
| --- | --- | --- | --- |
| **Save PUT** `PUT /draft/{key}` → `save_editable_model_draft` → `serving_endpoints.get(name)` | Client: `validateDraftForm` (`draftEditorState.ts:601`) gives zero PUT. Server: pre-stale local aggregate at `graph_configuration_draft.py:412`, and defensively in `catalog.py:215` before `get`. | Once, after the stale and post-stale checks, immediately before the write (`:421`). It runs **inside `with session.begin()` holding FOR UPDATE** on GraphRelease/GraphDraft parents and the selected row (`graph_configuration_workbench.py:201-206,374`). Client bound is 5 s retry / 3 s request (`catalog.py:110-147`). **On the event loop (I1).** | draft `:3257` (URL+stale → 422, zero remote), `:3291` (valid+stale → 409, zero remote), `:3410`, `:3547`, `:3584`, `:3617`; routes `:3950`, `:3972`; catalog `:288`, `:319`, `:358`, `:383`; PG `test_stale_endpoint_loser_waits_on_the_lock_and_never_reaches_remote_validation`; join file (25) |
| **Trusted save** `save_draft_content` | Pre-stale at `:471` | Only if a validator is injected (`:480`), with the same lock. No production caller (c5), and the default facade has `None`. | draft `[trusted]` parameters of `:3291`, `:3410`, plus `:3380` and `:3693` |
| **Discovery selection** `GET /model-endpoints` → `list()` → radio → `edit(endpoint_name, item.name)` → Save PUT | Not on `list()` output. The selected name then goes through the PUT's client and server policy. | `list()` runs with **no DB lock** (the route takes no `db`), in a sync `def` threadpool, with a 30 s retry / 30 s request bound (`catalog.py:117-156`). The selected name is then remote-validated by the PUT. | routes `:3574-3768`; catalog `:74`, `:95`, `:114`, `:235`, `:417`; Vitest selection and one-GET; Playwright discovery flow. **Unpinned: any-entity rule (m1).** |
| **Probe** `POST /draft/{key}/model-endpoint-probe` → `ChatDatabricks(model=name).with_structured_output(...).invoke` | Re-run on the **saved** name after the snapshot transaction ends (`graph_configuration_draft.py:637-639`) | No catalog `get`; the model call is the check. The FOR SHARE read is copied and released before the call (`:622-636`), so **no lock** is held. It runs in the threadpool (`routes:767`), with a 30 s httpx per-phase timeout and 0 retries (`probe.py:99-100`). | workbench `:158`, `:194`, `:209`; probe `:473`, `:518`, `:660`, `:673`; routes `:4353`, `:4406`; PG `test_model_endpoint_probe_holds_no_lock_while_the_model_call_is_in_flight` |
| **Runtime invocation of a published release** `_run_resolved` → `saved_model_configuration` → `bind_structured_output_model` → `ChatDatabricks(endpoint=name)` | **None, and none needed** (see the queued ruling). The name travels as the JSON body `model` field to `POST {host}/serving-endpoints/chat/completions` (`databricks_langchain/chat_models.py:332,348,370`; SDK `open_ai_client.py:96` `base_url = host + "/serving-endpoints"`, the same in 0.120.0). It is never path-interpolated. | None. There is no DB lock during invoke (pre-existing). The openai defaults (600 s, 2 retries) are pre-existing and unchanged. | `test_agent_runtime.py:435` (one `with_structured_output(`), `:680` (runtime and probe share one helper), `:783` (saved-configuration conversion) |
| Protected-assembly upgrade / schema-contract upgrade | **Never** (a legacy URL-shaped name must still upgrade) | **Never**, with no network | draft `test_endpoint_checks_are_composed_only_into_the_two_save_paths[protected_assembly,schema_contract]` (`:3650`); `test_overlay_validation_is_registered_in_the_pre_stale_tuple_only`; Task 2 M08; Task 3 R2; **my S1** |
| Bootstrap seed `bootstrap_v1` | None (packaged constant) | None | manifest/bootstrap PG suite (2) |
| Legacy prompt-source read | N/A (reads the endpoint, never sends it) | None | — |
| Other path found: `tools/model_endpoint_tool.py:75` `get(endpoint_name)` (user OBO client) | None | Pre-existing; not an Agent Definition path (m7) | — |

## 3. Writer-by-writer table (`_write_locked_content`, `graph_configuration_draft.py:911`)

Every entry point opens `with session.begin()`, then `_read_workbench_for_draft_write` (FOR UPDATE).

| Entry point | Order of phases relative to the stale check | Endpoint phases | Network I/O |
| --- | --- | --- | --- |
| `save_editable_model_draft` `:367` | command checks → lock `:382-383` → rebuild/validate → **local + C4 policy `:412`** → **stale `:413`** → post-stale `:420` → **remote `:421`** → write `:422` | C4 before stale; remote once after stale | yes: one `get` under the lock (I1: on the loop) |
| `save_draft_content` `:429` | common checks → lock `:447` → round-trip → immutable `:464` → **local + C4 `:471`** → **stale `:472`** → post-stale `:479` → **remote `:480`** → write `:481` | the same | only with an injected validator; no production caller |
| `upgrade_draft_protected_assembly` `:488` | lock `:498` → **stale first `:503`** → assembler upgrade → class local `:518` → post-stale `:519` → write `:520` | **none** | **none** |
| `upgrade_draft_schema_contract` `:527` | lock `:553` → class local on current `:559` → **stale `:560`** → already-current → upgrade → class local on target `:572` → post-stale `:573` → write `:574` | **none** | **none** |

Upgrades make no network I/O. The class tuples are unchanged (`local == (assembly, overlay)`, `post_stale == ()`), and `_validate_remote_endpoint` is called only at `:421` and `:480`. My sabotage S1 below proves the schema-contract service seam, which no earlier round targeted.

## 4. Lock and network table

| # | Network call | DB lock held? | Time bound |
| --- | --- | --- | --- |
| 1 | Save PUT: `serving_endpoints.get(name)` via `bounded_catalog_workspace_client` | **Yes**: FOR UPDATE on GraphRelease/GraphDraft parents and the selected draft row, for the whole call | Retry window 5 s plus a 3 s per-request http timeout, so about 8 s worst case. Plus one unclamped server `Retry-After` sleep and OAuth refresh (m3). **Runs on the event loop (I1).** |
| 2 | Save PUT: `get_system_client()` inside the validator factory (`graph_configuration.py:67`); first-call auth resolution, or external-browser `authenticate()` refresh | **Yes** (same transaction) | Unbounded (C8 parked); warm in production |
| 3 | Trusted save: the same `get` | Yes, if injected | Same as #1; no production caller |
| 4 | Discovery GET: `serving_endpoints.list()` via `bounded_discovery_workspace_client` | **No** (the route has no session) | 30 s retry window plus a 30 s request, about 60–90 s worst case; sync `def`, so threadpool |
| 5 | Probe: `get_system_client()`, then `ChatDatabricks.invoke` (`POST /serving-endpoints/chat/completions`) | **No**: the snapshot transaction ends first (C13, PG-proved) | 30 s httpx per phase, `max_retries=0`. The system client and OAuth refresh sit outside the bound (Task 5 M3). Threadpool. |
| 6 | Runtime invoke (refactored, not new) | No (pre-existing) | Pre-existing openai defaults; unchanged by #266 (Task 5 M13 pins "no transport options") |
| — | Both upgrades, the legacy-source read, the workbench read, bootstrap | — | **no network** |

## 5. Reviewer's own sabotage (temp worktree)

- Worktree: `git worktree add --detach /Users/robert.whiffin/Documents/slide-gen-branch-eval/wbr-266 39f32a4e2933fbd3961a5915aecaa37e5864bc0f`. The path contains neither "private" nor "payload". `.venv` was absent.
- Interpreter: `PYTHONPATH=$T:$T/packages/databricks-tellr /Users/robert.whiffin/.pyenv/shims/python -m pytest -q -p no:randomly -rf`.
- Ledger check: every earlier target was listed and avoided:
  - T1 task heuristic and exact name
  - T2 bypass, stale-order, http timeout, `%`, `RuntimeError`, M01–M16 (M08 = protected-assembly upgrade)
  - T3 empty-on-error, body-before-auth, route-level schema-upgrade wiring (R2), PG override, S01–S12
  - T4 S01–S31, F1–F8, M1–M3
  - T5 M1–M23, S1, C13
  - T6 M1–M24, R1–R5, auto-advance
- **No one targeted the service-level schema-contract upgrade composition.** Task 3 R2 wired the validator into the *route*. That is a behavioural no-op, because the service ignores the validator there (Task 3 M3).

**S1: the schema-contract upgrade acquires remote endpoint I/O (writer-table seam).**
- Mutation: in `src/services/graph_configuration_draft.py`, `upgrade_draft_schema_contract`, insert `self._validate_remote_endpoint(target)  # WBR266_SCHEMA_UPGRADE_REMOTE_SABOTAGE` after `self._run_candidate_validators(self.post_stale_validators, target)` and before `_write_locked_content`.
- Checks:
  - Anchor count **1**: a three-line anchor starting at the unique `target = upgrade_content_to_v2(current)`.
  - Marker count **1** (`grep -c`), at `:574`, on the executed path directly before the `return self._write_locked_content(`.
- Scope: `tests/unit/test_graph_configuration_draft.py tests/unit/test_agent_definition_workbench_routes.py tests/unit/test_graph_configuration_workbench.py`.
- **RED: 1 failed / 408 passed.** The failing test is `test_graph_configuration_draft.py::test_endpoint_checks_are_composed_only_into_the_two_save_paths[schema_contract]`, because the recording remote saw the legacy candidate.
- Restore: `git checkout 39f32a4e2933fbd3961a5915aecaa37e5864bc0f -- src/services/graph_configuration_draft.py`. The md5 equals the pre-mutation md5, the marker count is 0, and the triple check is 0/0/0.
- **GREEN: 409 passed.**

**S2 (survivor, which produced m1): discovery scans only the first served entity.**
- Mutation: `for entity in list(served_entities)[:1]  # WBR266_FIRST_ENTITY_ONLY_SABOTAGE` in `model_endpoint_catalog.py`.
- Checks: anchor count 1; marker count 1 at `:185`.
- Scope: `tests/unit/test_model_endpoint_catalog.py tests/unit/test_agent_definition_workbench_routes.py`.
- **Result: 295 passed, 0 failed. The mutation SURVIVED.** No fixture puts a non-foundation entity first.
- Restore: `git checkout 39f32a4e2… -- src/services/model_endpoint_catalog.py`. The md5 is the same and the marker count is 0.
- GREEN: 295.

**Demonstration for I1 (not a sabotage).** I added an untracked scratch test, `tests/unit/test_zz_wbr266_loop_probe.py`, which mirrors `:4406` for the PUT validator. It failed with `remote endpoint validation ran on the event loop: [True]`. The file was deleted, and the triple check was empty afterwards.

The temp worktree was removed with `git worktree remove`. The path is absent and `git worktree list` no longer lists it.

## 6. Gates re-run by this review at `39f32a4e2`

- **Full `tests/unit`:** 6 failed / 6170 passed / 110 skipped. The failures are exactly the baseline causes:
  - autoscaling ×2: `'provisioned' == 'autoscaling'`, and `Called 0 times`
  - `_FakeSession.execute` ×3 at `conversation_pins.py:79`
  - "no active Graph Release" ×1 at `:83`
  - Zero failures outside that set.
- **PostgreSQL**, one file per invocation, zero skips:

  | File | Passed |
  | --- | ---: |
  | bootstrap | 2 |
  | constraints | 7 |
  | runtime failures | 7 |
  | pin migration | 1 |
  | pin creation | 2 |
  | workbench | 17 |
  | overlay | 10 |
  | pin acceptance | 1 |
  | mixed-release collaboration | 26 |

- **SDK 0.120.0 shadow** (`PYTHONPATH=/tmp/sdk120/x:…`, which printed version 0.120.0): the catalog, draft, routes, probe, workbench, runtime and join files gave **578 passed**. This is wider than the controller's 60 + 39 and includes the real-`ChatDatabricks`-over-`httpx.MockTransport` probe tests.
- **Frontend** (ticket worktree, read-only; `lsof -i :3000` empty before and after):
  - Vitest 14 files, **486 passed**
  - `npm run typecheck` exit 0
  - Playwright workbench **69/69**
  - A strict standalone `tsc` of `tests/e2e/agent-definition-workbench.spec.ts` (`--strict --noUnusedLocals --noUnusedParameters`, vite types) exits 0
- The ticket worktree's triple check was empty throughout, and `.venv` was absent before and after.

## 7. Rulings on the queued items

| Item | Ruling |
| --- | --- |
| Task 2 minor 1 (system-client failure → 500) | **Closed.** Fixed in Task 3 `6332f427d` (`graph_configuration.py:67-76`, `routes:115-120`), with sabotage S11/S12 RED. |
| Task 2 minor 2 / C8 broad `RuntimeError` | **Accept.** C3-mandated. The `try` wraps only the SDK call, and `ModelEndpointCatalogFailure`/`EndpointValidationFailure` are raised outside it. |
| Task 2 minor 3 / C8 `Retry-After` and OAuth refresh | **Accept for merge, follow-up (m3).** Clamping `Retry-After` needs SDK internals. After I1 the residual is a bounded-by-platform lock hold, not an event-loop freeze. |
| Task 3 M1 (duplicated unavailable literals) | Accept. Tests pin both strings, so drift REDs. Optional consolidation. |
| Task 3 M2 (discovery composition in the route module) | Accept. Optional move beside `build_remote_endpoint_draft_validator`. |
| Task 3 M3 (route-level mis-wire is a dependency check only) | Accept. My S1 now pins the *service*-level seam behaviourally. |
| Task 3 deferred (draft-level factory test stubs the bound) | Accept. The route and catalog levels pin the literal bounds. |
| Task 4 M-1 (`retryable` unused; forbidden says "try again") | Should-fix copy (m5), not must-fix. |
| Task 4 M-2 (narrowed GET counts) | Closed. `allGets()` backstops were restored in the fix round. |
| Task 4 M-3 (vacuous no-secret check) | Accept. Sanitisation is server-owned: messages are code-owned table constants, and the probe logs the class name only. |
| Task 4 M-4 / docs not rendered | Accept. Re-run the forbidden-name sweep if `docs` is ever rendered. |
| Task 4: no AbortController on refresh | Accept. The freshness token drops stale responses, and the discovery bound is finite. |
| Task 4: control-char/dot rules pinned by text only | Accept. The join file pins them by text, and the server catalog tests cover them case by case (`[delete]`, `[dot-dot]`). |
| Task 5 M1 (422 dead with 0.9.0) | Superseded by the ruled openai table; 422 is now reachable. Wording issue → m2. |
| Task 5 M2 (`DraftProbeCandidate` above `_LEGACY_SOURCE_ROLES`) | Accept. The text-read is unaffected; ledger wording only. |
| Task 5 M3 (30 s is per phase, not wall-clock) | Accept, as ruled. |
| Task 5 M4 (`NotImplementedError` from the factory → unsupported) | Accept (negligible). |
| **Task 6 m1: `PROBE_FAILURE_CONTRACT` hand-copied in `agentDefinitions.ts:1023` and `mocks.ts`, with no Python join** | **Accept for merge; add the join in the fix wave (not must-fix).** Drift fails closed: a mismatched typed failure becomes a contained generic alert with no Retry. The UI renders the server's message, and nothing blocks a write. Unlike the C4 policy, a drifted copy cannot make valid data unsaveable. |
| Task 6 m2 (no Playwright probe tripwire) | Optional. |
| Task 6 m3 ("Draft lock N" reads as current) | Optional copy ("Tested at draft lock N"). |
| **C8's unbounded paths** (`Retry-After`, OAuth refresh, broad `RuntimeError`) | As above: accept, with I1 fixed. The only must-fix consequence of C8 is I1. |
| **Pre-#266 path-shaped rows / runtime guard (C4 park)** | **No runtime-side guard is required in #266.** `ChatDatabricks` does **not** interpolate the name into a path, unlike the SDK `get`. It sends `model=<name>` in the JSON body of `POST {host}/serving-endpoints/chat/completions` (`databricks_langchain/chat_models.py:259,332,348,370`; SDK `mixins/open_ai_client.py:96`, identical in 0.120.0). A path-shaped name therefore yields a provider 4xx, not a traversal. Also, today the only release writer is bootstrap (seed only), so no published release can hold a non-seed name. Every draft save re-runs C4 on the full candidate, and the probe re-checks the saved name. Carry m8 to the publish ticket. |
| **`openai` undeclared in the app wheel** | **Accept for merge; follow-up (m6).** It is pre-existing: `agent_runtime.py:27` already imports `openai` at base `50c8cbf35`. It is guaranteed by the exact pin `databricks-langchain==0.9.0`, whose metadata requires `openai>=1.99.9` unconditionally (probed). Every class the probe uses exists in openai 1.x. Declaring it explicitly in `packages/databricks-tellr-app/pyproject.toml` would harden the build, but it has to clear the Apps resolution budget on its own evidence, as the wheel test's allowlist notes. |
| **SDK 0.120.0 (wheel) vs 0.112.0 (env)** | **Sufficient for local merge.** I extended the controller's shadow run to the whole #266 matrix (578 passed). I also confirmed in the 0.120.0 source that `Config.copy` is still shallow and shares `_inner`, `get` still interpolates the name, `retried` has the same `Retry-After` semantics, and the openai `base_url` is the same. The bounded-client tests assert literal values and the transport `timeout=`, so a semantic change REDs. The residual is the live-workspace check m9, which is a release gate, not a merge gate. |
| Epic: `frontend/tests/` typecheck gap | **Does not hide a #266 defect.** A strict standalone `tsc` of the #266-extended e2e spec exits 0. `mocks.ts` is typechecked via imports (controller correction). No action for #266. |
| Epic: log-test substring needles matching `pathname` | **Does not touch #266.** The range adds no `caplog`/`LogRecord` assertion (grep over the test diff: 0). The probe's only log line (`model_endpoint_probe.py:194-198`) emits the code and exception class name. |

## 8. Declined to judge

- The live Databricks `get` shape for pay-per-token endpoints (whether `config_update` is always present), and whether the app service principal can `get` or `list` system endpoints. That needs a real workspace, which this review may not touch. It is raised as release gate m9.
- The real `Retry-After` values Databricks returns on 429/503. It is remote state and determines only m3's magnitude.
- Whether an openai 400 from a real serving endpoint reliably means "structured output unsupported" as opposed to a sampling-limit rejection. It is remote behaviour, and the classification is a recorded controller ruling. Only the wording is raised (m2).
- Playwright visual/UX quality of the Model tab layout. It is outside the correctness gate, and the accessibility names are pinned by tests.
- #267/#268 approval and publication gating from design §10/§11. It is out of #266 scope; m8 is the forward note.
- `model_endpoint_tool.py:75`'s C4-class exposure under the user client. It is pre-existing and outside the Agent Definition flow (m7).

## 9. Fix list for local merge

1. **I1 (must-fix):** run `save_editable_model_draft` for the PUT through `run_in_threadpool`, and add the PUT loop-observer test with its sabotage.
2. m1: add a mixed-entity discovery fixture (test-only).
3. m2 and m5: copy fixes (probe rejection wording; forbidden catalog alert without "try again").
4. m4: optional probe-contract text-read join.
