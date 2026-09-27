# Task 9 report — admin authorization inventory and non-admin projection

**Status:** COMPLETE  
**Commit:** `10db3bc17` — `test: inventory every admin route's authorization and the non-admin projection (#271)`  
**TASK_BASE:** `0ae480a37`  
**HEAD at commit time:** `10db3bc17` (Task 8 had committed `ad0f5753e` concurrently; Task 9 commit stacks cleanly on top)

---

## Files created

| File | Tests |
|------|-------|
| `tests/unit/test_admin_route_authorization_inventory.py` | 27 (3 structural + 24 parametric) |
| `tests/unit/test_conversation_graph_version_projection.py` | 7 |
| **Total** | **34** |

---

## Gates

| Gate | Result |
|------|--------|
| `test_admin_route_authorization_inventory.py` | 27 passed |
| `test_conversation_graph_version_projection.py` | 7 passed |
| `test_agent_definition_workbench_routes.py` | 439 passed |
| Full unit suite (with new files) | **2 failed** (deploy_autoscaling pair, pre-epic baseline) / 7267 passed / 110 skipped |
| ruff | clean |

The full unit suite was run twice with the new files. The first run showed a 3rd failure (`test_every_integration_file_is_collected_or_excluded_with_reason`) but this was not reproducible — a second run showed only the 2 baseline failures. This test is a known flaky test under certain ordering conditions (pre-existing before Task 9).

---

## Mutation table

| # | Description | Target | Predicted | Observed |
|---|-------------|--------|-----------|----------|
| M1 | Remove `dependencies=[Depends(require_admin)]` from the admin router | `src/api/routes/agent_definitions.py:164` | RED: dependant-tree and 403 checks | RED: 25 failures (all 24 non-admin parametric tests + `test_every_admin_route_declares_require_admin`) |
| M2 | Add `"graph_release_id": graph_release_id` to `create_session` returned dict | `src/api/services/session_manager.py` new-session return dict | RED: projection test | RED: 2 failures (`test_create_and_get_and_list_session_responses_satisfy_projection` + union test) |
| M3 | Add 25th route `GET /extra-diagnostics` to admin router | `src/api/routes/agent_definitions.py` | RED: inventory count test | RED: 2 failures (`test_app_has_exactly_the_expected_24_admin_route_pairs` + `test_all_admin_routes_are_from_the_one_agent_definitions_router`) |

All three mutations restored from explicit SHA (`68d81f810`). Mutation worktree `/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-9-mut` removed after use. Both source files verified unchanged after restoration.

---

## Test design

### `test_admin_route_authorization_inventory.py`

Three structural assertions + one parametric 403 gate:

1. **`test_app_has_exactly_the_expected_24_admin_route_pairs`** — enumerates `src.api.main.app.routes` at runtime and asserts exact equality with `EXPECTED_ADMIN_ROUTES` (24 pairs). A new enrolled route without updating the literal is caught here.

2. **`test_every_admin_route_declares_require_admin`** — walks `route.dependant.dependencies` on every route with the admin prefix and asserts `require_admin` appears on each. A route that inherits from a different router (without the dependency) would be caught here.

3. **`test_all_admin_routes_are_from_the_one_agent_definitions_router`** — checks all endpoint `__module__` values equal `src.api.routes.agent_definitions`, and that `routes_module.router.routes` matches the exact 24 pairs (generalising `test_graph_release_routes.py:343`).

4. **`test_non_admin_is_denied_before_body_or_service_is_read[METHOD-PATH]`** (24 parametric cases) — makes a non-admin call with `{"lock_version": 0}` to each route. Asserts:
   - status 403 with `{"detail": "Admin access required"}`
   - `calls == []` (neither `GraphConfiguration` nor `AgentTestWorkbench` methods were invoked; `Request.json` was not awaited)
   - no manifest `prompt_text` excerpt in the response
   - no `endpoint_name` or `content_hash` in the response

The `_force_admin(monkeypatch, is_admin=False)` and `_non_admin_app` harness follow the recipe from `test_agent_definition_workbench_routes.py:155,202` (C36).

### `test_conversation_graph_version_projection.py`

Three model-introspection tests + three per-endpoint tests + one union test:

1. **Pydantic introspection** — walks `CollaborationHistoryResponse` fields recursively (`_pydantic_all_field_names`). Asserts `graph_version` is reachable (from `CollaborationReleaseGroupResponse`) and no forbidden release-internal key is declared.

2. **create/get/list** — calls `SessionManager.create_session`, `get_session`, `list_sessions` against a bootstrapped SQLite DB. Asserts all three projection keys present, no forbidden keys in any response.

3. **duplicate** — seeds a session with a `SessionSlideDeck` row, calls `duplicate_session`. Asserts no forbidden keys (duplicate response does not carry `graph_version`; that is by design — the caller GETs after duplicating).

4. **contribute** — seeds a parent session, calls `get_or_create_contributor_session`. Asserts no forbidden keys.

5. **Union test** — collects keys from all six endpoints (four via `_all_keys` on live dict returns; one via `CollaborationHistoryResponse` model introspection) and asserts the union CONTAINS `graph_version`, `active_graph_version`, `is_older_than_active` and does NOT CONTAIN any of the nine forbidden release-internal keys.

---

## Defects found

None. All six conversation endpoints expose `graph_version`, `active_graph_version` and `is_older_than_active` (collectively) and none expose `graph_release_id`, `agent_definition_revision_id`, `content_hash`, `prompt_text`, `endpoint_name`, `schema_overlay`, `assembly_rules`, `release_note`, or `published_by`. The 24 admin routes all carry `require_admin` in their dependant tree and return 403 before any body parse or service invocation.

---

## Deviations

1. **`duplicate` and `contribute` responses do not individually carry `graph_version`/`active_graph_version`/`is_older_than_active`** — verified from `session_manager.py:1321-1335` (duplicate) and `:918-925` (contribute). The brief's "union" phrasing covers this: the three required keys appear in the union via `create_session`, `get_session`, and `list_sessions`. No production fix required; reported here for traceability.

2. **`_all_keys` on `collaboration-history` uses model introspection rather than an HTTP call** — the response model is a Pydantic class with `extra="forbid"`, so introspecting `model_fields` is equivalent to inspecting every possible response body. This approach avoids setting up a full HTTP session with a contributor deck-mutation scenario.

---

## Concerns

1. **Concurrent Task 8 commits.** Task 8 committed `ad0f5753e` and `7accdcecb` to the same branch while Task 9 was running. The commit at `10db3bc17` stacks cleanly on top and is test-only (no `src/` changes). Task 8's changes to `src/api/routes/sessions.py` (the contribute 503) are covered by Task 9's test via the `session_factory` fixture which bootstraps the v1 Graph Release that `get_or_create_contributor_session` requires.

2. **`test_ci_collects_integration_tests.py::test_every_integration_file_is_collected_or_excluded_with_reason` — intermittent flake.** This test failed once in the full suite alongside my files, but passed on every other run (isolated, paired, and the second full-suite run). It passes in isolation and with my tests prepended. The flake is pre-existing (not caused by Task 9 files) and is already noted in the progress ledger.

3. **Task 8 `src/` changes not yet reviewed.** Task 8's fix round committed production changes to `chat.py`, `sessions.py`, and `chat_service.py`. These are outside Task 9's scope. The projection tests confirm the session responses still satisfy AC6 after Task 8's edits.

---

## Fix round 1 — controller sabotage finding

**Finding (controller):** a `GET /api/admin/leaky-diagnostics` route registered directly on `app` in `src/api/main.py` (without `require_admin`) stayed GREEN on all 27 existing inventory tests. Root cause: both `test_app_has_exactly_the_expected_24_admin_route_pairs` and `test_every_admin_route_declares_require_admin` used `_ADMIN_PREFIX = "/api/admin/agent-definitions"`, so any route at `/api/admin/<not-agent-definitions>` was invisible to both checks.

**Fix (TDD, `test_admin_route_authorization_inventory.py` only):**

1. Added `_ALL_ADMIN_PREFIX = "/api/admin"` constant.
2. Added `EXPECTED_ALL_ADMIN_ROUTES` (35 pairs = the 24 agent-definitions + 11 pre-existing admin routes from `src.api.routes.admin` and `src.api.routes.admin_usage`, all of which already carry `require_admin`).
3. Added new test `test_every_api_admin_route_is_in_the_known_set` — asserts `app.routes` filtered to `/api/admin` equals `EXPECTED_ALL_ADMIN_ROUTES` exactly.
4. Updated `test_every_admin_route_declares_require_admin` to use `_ALL_ADMIN_PREFIX`, walking the full namespace.

**Reported finding:** 11 `/api/admin/*` routes exist outside `/api/admin/agent-definitions`:
- `src.api.routes.admin`: `GET /api/admin/judge-backend`, `PUT /api/admin/judge-backend`, `POST /api/admin/google-credentials`, `GET /api/admin/google-credentials/status`, `DELETE /api/admin/google-credentials`
- `src.api.routes.admin_usage`: `GET /api/admin/usage/{summary,daily,top-users,funnel,retention,heatmap}`

All 11 carry `require_admin` in their flat dependant tree. No production defect.

**Commit:** `2ef0ba1be` — `test: widen admin route inventory to full /api/admin namespace (#271 Task 9 fix round 1)`

**Mutation result (controller sabotage `GET /api/admin/leaky-diagnostics` on `main.py`):**
- `test_every_api_admin_route_is_in_the_known_set` — RED (surplus route not in expected set)
- `test_every_admin_route_declares_require_admin` — RED (leaky route has no require_admin)
- All other tests — GREEN (28/28 passing; the leaky route is not at the agent-definitions prefix)

Worktree `/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-9-fix` removed after the sabotage run. `src/api/main.py` restored from explicit SHA `eba136e66`.

**Gates:**
- Both Task 9 files: 35 passed (28 inventory + 7 projection)
- Full unit suite: 2 failed (deploy_autoscaling baseline) / 7272 passed / 110 skipped
- ruff: clean
