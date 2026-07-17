# SDR-4437 PR-4 — OAuth & Error Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close HIGH-7, MEDIUM-2 and MEDIUM-3 of SDR-4437: MCP header-only forwarded identity no longer executes Databricks resources as the service principal; the Google OAuth flow gains a DB-backed single-use state nonce (login-CSRF fix), server-side PKCE, and explicit postMessage origins; and all 85 exception-interpolating `detail=` sites across `src/api/routes/` become generic client messages with server-side logging, enforced by an AST gate test.

**Architecture:** A serial gate commits the MEDIUM-2 AST interpolation-gate test **red** (it is the shared failing test for the whole sweep). Then three streams run: HIGH-7 as a focused single-agent task on `mcp_auth.py`/`mcp_server.py`; MEDIUM-3 as the deep single-agent task (new `oauth_states` Lakebase table, OAuth flow rewrite in `google_slides.py`, PKCE verifier moved server-side, postMessage origins on both ends); and a mechanical per-file MEDIUM-2 fan-out driven by one fixed replacement recipe (no per-site improvisation). Convergence turns the gate green, runs the full suite plus frontend lint/build, and deploys to a devloop instance for smoke checks.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`delete(...).returning(...)` — atomic single-use consume), Lakebase Postgres (SQLite in tests, RETURNING supported: repo sqlite3 is 3.51), google-auth-oauthlib `Flow` (PKCE S256), React/TS (`useGoogleOAuthPopup.ts`), pytest + `fastapi.testclient`, Python `ast` for the interpolation gate.

**Planning baseline: main@7c50339 + PR-2 plan (intended end-state). Execution baseline (REFRESHED 2026-07-17): all five SDR-4437 PRs (#223/#224/#228/#226/#227) are now MERGED to `main`; this track branches off `main`, not off `security/sdr4437-pr2-authz` (which no longer exists as an open branch). Re-verify handler line refs at execution time; treat all line numbers in this plan as approximate.**

> **BASELINE REFRESH NOTE (2026-07-17):** A fresh AST scan of current `main` found **88** `detail=` interpolation sites (not 85) + the 1 HTML reflection. The entire +3 delta is in `sessions.py` (**19**, was 16) — all three new sites are in the `duplicate_session` handler that landed via PR #213 (duplicate-deck feature) AFTER this plan was written. Every other file's count is unchanged. Task 6's site table has been updated with the three `duplicate_session` rows. This is exactly the drift Task 1 Step 3 was designed to reconcile.

All counts and line references below were re-verified by an AST scan of the **pre-PR-2** working tree (main@7c50339): 85 `detail=` interpolation sites in 13 router files + 1 HTML `{exc}` reflection — matches the spec's totals exactly (now 88 on the merged baseline; see refresh note above). The gate, however, executes on the **post-PR-2** head, which adds files under `src/api/routes/` that the gate also walks (notably `_authz.py`) — Task 1 Step 3's red-list run is therefore the authoritative re-verification of the 85/13 map on the actual branch head. `_authz.py` must contain **zero** interpolating sites (its permission gates raise static-detail `HTTPException`s); if the gate ever lists a site in `_authz.py` (or any other file this track's boundary forbids touching), that is an **escalation to the orchestrator/PR-2 track**, not a fix — see Task 1 Step 3. PR-2's Task 1 deletes helper blocks from `sessions.py` (~lines 50–147) and `slides.py` (~lines 33–110), so line refs in those two files shift down by roughly 97 and 77 respectively at execution time — always relocate sites by grep, never by line number.

**Branch:** `security/sdr4437-pr4-oauth-errors` off `main` (REFRESHED 2026-07-17 — all of Wave 1 is merged, so the PR-2 end-state this track depends on is now in `main`; the original "off security/sdr4437-pr2-authz head" instruction is superseded).

**Branch-naming note (verified):** the `sdr4437-*` form (no hyphen after `sdr`) is the implementation-branch scheme shared by all five SDR-4437 track plans, and `security/sdr4437-pr2-authz` is exactly the branch the PR-2 plan prescribes (`2026-07-15-sdr4437-pr2-authz.md`). That branch does not exist yet — PR-2's track creates it, which is why Task 1 Step 1's precondition checks halt this track on a missing baseline. Do **not** "correct" the name to the hyphenated `security/sdr-4437-*` form: the existing hyphenated branches (`security/sdr-4437-spec-review`, `security/sdr-4437-remediation`) are the spec/docs branches, not implementation branches. Any rename of the implementation scheme is an orchestrator-level decision spanning all five plans, not this track's.

**Spec:** `docs/superpowers/specs/2026-07-13-sdr-4437-remediation-design.md`, section "PR-4 — OAuth & error hardening (HIGH-7, MEDIUM-2, 3)" (plus the Delivery section for context).

## What PR-2 already did (do not undo or duplicate)

This branch contains PR-2's work. Specifically, PR-2 has already:

- Added permission gates as the **first statement(s)** of most handlers this track touches (`export.py`, `google_slides.py` export/poll, `slides.py` versions, `verification.py`, `chat.py` poll, `images.py`, `agent_config.py`, etc.). **Leave every gate exactly where it is.**
- Created `src/api/routes/_authz.py` and moved `sessions.py`/`slides.py` permission helpers into it.
- Removed the exception-swallowing identity fallbacks: `google_slides.py::_get_user_identity` and `images.py::_get_current_user` now **raise `UserClientRequiredError` in production** instead of returning `"local_dev"`/`"system"` (still early-return those values when `ENVIRONMENT` in `("development", "test")`).
- Made `get_user_client()` fail closed in production (`UserClientRequiredError`, mapped to a 401 handler in `main.py`).
- Added per-router `tests/unit/test_authz_*.py` files and `tests/unit/test_route_authz_coverage.py` (which allowlists `GET /api/export/google-slides/auth/callback` with the note that the nonce lands in this PR).

## Global Constraints

- Branch `security/sdr4437-pr4-oauth-errors` is created off the **actual head** of `security/sdr4437-pr2-authz`. Do not push/merge unless the orchestrator asks.
- **The MEDIUM-2 Replacement Recipe (below) is normative.** Every fan-out task applies it verbatim with its site table; implementers must not invent alternative wordings, change status codes, change exception types, reorder except clauses, or touch success paths.
- Do NOT touch permission gates, `src/api/routes/_authz.py`, or `tests/unit/test_route_authz_coverage.py`. If a gate looks wrong, **escalate to the sub-supervisor, don't fix**.
- Do NOT touch the middleware block or exception handlers in `main.py`.
- New client-facing error strings must never interpolate an exception object, exception message, path, env var, stdout/stderr, or stack data. Interpolating *request identifiers* the caller already sent (e.g. `f"Session not found: {session_id}"`) is allowed and existing such strings stay unchanged.
- **Cross-plan ownership note (escalated to the orchestrator — do not resolve in this track):** the PR-2 plan's handoff line (`2026-07-15-sdr4437-pr2-authz.md`, "Definition of done + PR-4 handoff") tells the orchestrator that "PR-4's MEDIUM-2 sweep owns every `detail=` string this track deliberately left leaky", explicitly naming the pre-existing `detail=f"Session not found: {session_id}"` family. That overstates this sweep's scope: per the constraint above (and the gate's deliberate scope, Task 17 Step 1), request-identifier interpolations are allowed and intentionally left unchanged — a caller-supplied `session_id` echoed back (e.g. `chat.py`'s `SessionNotFoundError` handler) is not an information leak, and the AST gate correctly does not flag such sites. This track owns only *exception-variable* interpolation sites. Implementers must not "fix" request-identifier sites to satisfy the PR-2 handoff wording; the PR-2 side of that wording is the orchestrator's to reconcile.
- Production detection (where needed): `os.getenv("ENVIRONMENT", "development") == "production"`; `tests/conftest.py` sets `ENVIRONMENT=test`.
- Tests: `python -m pytest tests/unit/...`; remove the `mlruns/` artifact after runs (`rm -rf mlruns`).
- **Implementers edit files and report; only the sub-supervisor commits.** Every task ends with a "report for commit" step carrying the intended commit message.
- Parallel tasks must each touch **only the files listed in their own Files block**. `src/api/routes/google_slides.py` has two owners in sequence (Task 3 then Task 4) — Task 4 must not start until Task 3 is committed.

## Boundary Contract

This track owns: `mcp_auth.py`, the new `oauth_states` model/table, OAuth flow changes in `google_slides.py`, `frontend/src/hooks/useGoogleOAuthPopup.ts` (verify exact path), and `detail=` strings across `src/api/routes/`. It must NOT: touch permission gates, `_authz.py`, or the coverage test (PR-2 owns those — if a gate looks wrong, escalate, don't fix); touch `main.py` middleware; change any handler's success-path behavior; or modify converter services or deploy tooling.

**Planning-verified additions to the ownership list** (required to implement the owned items; verified at planning time):

- `frontend/src/hooks/useGoogleOAuthPopup.ts` — path verified to exist; it is the only message listener for the popup flow (consumers `AppLayout.tsx` and `GoogleSlidesAuthForm.tsx` use the hook and need no change).
- `src/services/google_slides_auth.py::get_auth_url` — **must** change: today it *injects the PKCE `code_verifier` into the client-visible `state` parameter* (lines ~242–252). This matches the spec's corrected analysis (remediation-design.md, MEDIUM-3 PKCE bullet: the callback's `code_verifier` read "is therefore **live**"): leaving `get_auth_url` untouched while changing the callback would break token exchange (Google would enforce a `code_challenge` the callback can no longer answer). This plan implements exactly the spec's prescribed "PKCE proper" fix: verifier generated server-side, stored in the `oauth_states` row, never client-visible. No other function in that service changes.
- `src/api/mcp_server.py` — only the two `mcp_auth_scope(...)` call sites for resource-executing tools (`_create_deck_impl`, `_edit_deck_impl`) gain a keyword argument.
- `src/database/models/__init__.py` — one import + `__all__` entry to register `OAuthState` for `create_all`.
- Tests owned: `tests/unit/test_no_exception_interpolation.py` (new), `tests/unit/test_google_oauth_state.py` (new), `tests/unit/test_mcp_auth.py` (edit), `tests/unit/test_google_slides_routes.py` (edit callback tests), `tests/unit/config/test_google_oauth.py` (edit one signature test).

## Execution Model

Sub-supervisor with fan-out:

1. **Phase 1 — Serial gate (Task 1).** Cut the branch; commit the MEDIUM-2 AST gate test **red** (its failure list is exactly the 85-site/13-file map below — that is the TDD failing test for the whole sweep).
2. **Phase 2 — Fan-out (Tasks 2–16).**
   - Task 2 (HIGH-7) and Task 3 (MEDIUM-3) are **focused single-agent tasks** — dispatch each to one implementer. MEDIUM-3 is the deep one; give it the strongest implementer and expect the longest wall-clock.
   - Tasks 5–16 (MEDIUM-2 per-file sweeps) are mechanical and fully parallel with disjoint file ownership.
   - **Task 4 (google_slides.py MEDIUM-2) is the one ordering constraint: it runs only after Task 3 is committed** (same file). Everything else can run concurrently, including Task 2 alongside Task 3.
3. **Phase 3 — Convergence (Task 17) + Deploy & evaluation (Task 18).**

## Rebase / conflict note

If PR-2's branch moves after this branch is cut (review fixes), **this track rebases onto the new `security/sdr4437-pr2-authz` head** (`git rebase security/sdr4437-pr2-authz`). Conflict policy: for any conflicted hunk in a route file, take PR-2's side of the hunk first, then re-apply this plan's change to it. The MEDIUM-2 re-application is mechanical by construction: after the rebase, run `python -m pytest tests/unit/test_no_exception_interpolation.py -v`; any site the gate lists is re-fixed by applying the Replacement Recipe with the owning task's site table. The MEDIUM-3 and HIGH-7 changes live in regions PR-2 does not edit (OAuth section of `google_slides.py`; `mcp_auth.py` is outside PR-2's boundary), so conflicts there should be limited to import blocks.

## Verified site map (AST scan of the working tree — ground truth for the sweep)

| File | Sites | Line refs (approximate — relocate by grep) |
|---|---|---|
| `src/api/routes/slides.py` | 33 | 179, 205, 233, 235, 238, 241, 272, 301, 303, 306, 309, 341, 369, 371, 374, 377, 415, 443, 445, 448, 451, 547, 611, 614, 657, 660, 725, 760, 808, 869, 872, 875, 911 |
| `src/api/routes/sessions.py` | 19 (was 16; +3 from #213 `duplicate_session`) | current-main: 104, 152, 238, 359, 424, 481, 536, 541, 546, 586, 640, 696, 735, 758, 840, 873, 898, 917, 942 |
| `src/api/routes/google_slides.py` | 9 (+1 HTML) | 151, 260, 274, 387, 403, 421, 488, 530, 563; HTML `{exc}` reflection in the callback failure page (~193–207) |
| `src/api/routes/export.py` | 7 | 603, 614, 620, 751, 889, 981, 1224 |
| `src/api/routes/chat.py` | 4 | 108, 263, 274, 552 |
| `src/api/routes/verification.py` | 3 | 267, 385, 510 |
| `src/api/routes/images.py` | 3 | 129, 195, 248 |
| `src/api/routes/settings/identities.py` | 3 | 112, 152, 206 |
| `src/api/routes/setup.py` | 2 | 126, 157 |
| `src/api/routes/settings/contributors.py` | 2 | 239, 421 |
| `src/api/routes/feedback.py` | 1 | 30 |
| `src/api/routes/agent_config.py` | 1 | 153 |
| `src/api/routes/admin.py` | 1 | 96 |
| **Total** | **88** (was 85; +3 from #213 `duplicate_session` in sessions.py) | (spec says "remainder spread across ten routers"; verified count is nine remainder files — recorded discrepancy, totals match) |

## The MEDIUM-2 Replacement Recipe (normative — applied verbatim by Tasks 4–16)

Every site sits inside an `except <Type> as e:` (or `as exc`) block. For each site in your task's table:

1. **Relocate the site** by grepping for the current `detail=` text (line numbers are approximate).
2. **Replace the `detail=` value** according to the site's Form:
   - **Form A** — `detail=f"<Prefix>: {str(e)}"` (also `{e}`, `{exc}`): → `detail="<Prefix>"`. Keep the existing prefix text verbatim, drop the colon, space, and interpolation. Example: `detail=f"Failed to create session: {str(e)}"` → `detail="Failed to create session"`.
   - **Form B** — bare `detail=str(e)` / `detail=str(exc)`: → the exact literal given in the site table (derived from the table below).
3. **Form B literal table** (keyed by caught type / status — the per-task site tables spell these out per line; this is the derivation rule):

   | Caught type / status | Replacement literal |
   |---|---|
   | `PermissionError` / 423 | `"This deck is locked by another editing session. Try again shortly."` |
   | `VersionConflictError` / 409 | `"The deck was modified by another request. Refresh and try again."` |
   | `ValueError` / 400 (validation) | `"Invalid request."` (unless the site table gives a more specific fixed literal) |
   | `ValueError` / 404 (images) | `"Image not found"` |
   | `ValidationError` / 422 | `"Invalid agent tool configuration."` |
   | `GoogleSlidesAuthError` / 400 | `"Google authorization is missing, expired, or not configured. Connect your Google account and try again."` |
   | `EditableExportError` / 503 | `"Editable PPTX export is not available."` |
   | `HuashuExportError` / 500 or 503 | (site table gives the literal; keep the existing status code) |
   | `Exception` / 500 | `"<Action> failed"` — the exact action phrase is in the site table |
4. **Logging** — after the edit, the except block must contain **exactly one** server-side log of the original exception:
   - If the block already has a `logger.*` call: keep it. For 500-class sites, ensure it carries the traceback (`exc_info=True` or `logger.exception`) — add `exc_info=True` if missing.
   - If the block has no log: add one **above the raise** — 5xx: `logger.exception("<handler_name> failed")`; 4xx: `logger.warning("<handler_name> rejected: %s", e)` (use the block's actual variable name, `e` or `exc`).
   - If the file has no module logger, add `logger = logging.getLogger(__name__)` (and `import logging`) at the top.
5. **Never change:** status codes, caught exception types, except-clause ordering, `from e` / `from exc` chaining, success-path code, response models, or any non-interpolating `detail=` string (including the ones PR-2 just added).
6. **Self-check:** run `python -m pytest tests/unit/test_no_exception_interpolation.py -v` — your file must no longer appear in the failure listing (the test stays red overall until all fan-out tasks land; you verify **your file's entries** are gone). Then run the existing tests named in your task.

---

# Phase 1 — Serial Gate

### Task 1: Branch + red MEDIUM-2 interpolation gate

**Files:**
- Create: `tests/unit/test_no_exception_interpolation.py`

**Interfaces:**
- Produces: the CI tripwire all MEDIUM-2 tasks converge on. **Committed failing** — its failure list at this point must be exactly the 13 files / **88 sites** in the Verified site map (plus the one HTML reflection). Also the rebase tool: after any rebase, whatever this test lists is what gets re-fixed.

- [ ] **Step 1: Cut the branch**

REFRESHED 2026-07-17 — branch off `main` (Wave 1 is merged):

```bash
git checkout main && git pull --ff-only 2>/dev/null; git checkout -b security/sdr4437-pr4-oauth-errors
```

(If the branch already exists from the orchestrator's baseline refresh, skip the create.) Confirm the PR-2 end-state is present in `main` before proceeding (all three must succeed):

```bash
test -f src/api/routes/_authz.py
python -m pytest tests/unit/test_route_authz_coverage.py -q
grep -q "UserClientRequiredError" src/core/databricks_client.py
```

If any check fails, stop and report to the orchestrator — this track must not start from a pre-PR-2 baseline.

- [ ] **Step 2: Write the gate test**

Create `tests/unit/test_no_exception_interpolation.py`:

```python
"""MEDIUM-2 gate (SDR-4437 PR-4): no exception interpolation in client responses.

Walks every file under src/api/routes/ with the AST and flags:

1. any ``detail=`` argument (keyword, or HTTPException's 2nd positional)
   inside an ``except ... as <name>:`` block that references ``<name>`` —
   this catches the whole family (``str(e)``, ``{e}``, ``{exc}``,
   ``{str(e)}``, multi-line f-strings) regardless of variable name; and
2. any ``HTMLResponse(...)`` call inside such a block that references the
   exception variable (the OAuth-callback ``{exc}`` reflection class).

NOTE while PR-4 is in flight: this test is committed RED at the end of the
serial gate and turns green as the per-file MEDIUM-2 tasks land.
"""

import ast
from pathlib import Path

ROUTES_DIR = Path(__file__).resolve().parents[2] / "src" / "api" / "routes"


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return getattr(func, "attr", "")


def _references(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _scan():
    detail_sites = []
    html_sites = []
    for path in sorted(ROUTES_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler) or not handler.name:
                continue
            for call in (n for n in ast.walk(handler) if isinstance(n, ast.Call)):
                values = [kw.value for kw in call.keywords if kw.arg == "detail"]
                if _call_name(call) == "HTTPException" and len(call.args) > 1:
                    values.append(call.args[1])
                for value in values:
                    if _references(value, handler.name):
                        detail_sites.append(
                            f"{path.relative_to(ROUTES_DIR)}:{value.lineno}"
                        )
                if _call_name(call) == "HTMLResponse" and _references(
                    call, handler.name
                ):
                    html_sites.append(
                        f"{path.relative_to(ROUTES_DIR)}:{call.lineno}"
                    )
    return detail_sites, html_sites


def test_no_exception_interpolation_in_detail():
    detail_sites, _ = _scan()
    assert detail_sites == [], (
        "Exception objects interpolated into client-facing detail= strings "
        "(SDR-4437 MEDIUM-2 — apply the PR-4 replacement recipe; log the "
        "exception server-side and return a generic message):\n  "
        + "\n  ".join(detail_sites)
    )


def test_no_exception_reflection_into_html_responses():
    _, html_sites = _scan()
    assert html_sites == [], (
        "Exception objects reflected into HTMLResponse bodies "
        "(SDR-4437 MEDIUM-2):\n  " + "\n  ".join(html_sites)
    )
```

- [ ] **Step 3: Run it — record the red list**

Run: `python -m pytest tests/unit/test_no_exception_interpolation.py -v`
Expected: both tests FAIL. `test_no_exception_interpolation_in_detail` lists **88 sites** across exactly the 13 files in the Verified site map (REFRESHED 2026-07-17 — was 85; the +3 in sessions.py `duplicate_session` are already folded into Task 6's table); `test_no_exception_reflection_into_html_responses` lists one site in `google_slides.py`. If the counts differ AGAIN from 88 (later merges may move things), diff the listing against the site map, update the owning tasks' site tables accordingly, and record the delta in the task report — do NOT weaken the test. **If a flagged site lives in a route file with no owning task** (Tasks 4–16 cover only the 13 files with sites at planning time; `tools.py`, `profiles.py`, `deck_contributors.py`, `version.py`, `admin_usage.py`, `local_version.py`, `tour.py`, and the other `settings/*` modules were verified to have zero), it is still this track's to fix — the Boundary Contract owns `detail=` strings across all of `src/api/routes/`: the sub-supervisor adds a site table entry to the most closely related task or dispatches an additional one-file sweep task applying the Replacement Recipe. Never leave a flagged site unowned (the gate stays red at convergence) and never fix it inline in this serial-gate task. This run doubles as the authoritative post-PR-2 re-verification of the site map (the planning-time scan ran on the pre-PR-2 tree). **Boundary special case:** if any listed site lives in a file this track must not touch — `_authz.py` above all — do not add it to a site table, do not fix it, and do not allowlist it in the gate: **stop and escalate to the orchestrator** (it belongs to PR-2's track; the gate stays red on that entry until PR-2 fixes it).

- [ ] **Step 4: Report for commit**

Commit message: `test(errors): AST gate against exception interpolation in route responses — red until PR-4 sweep lands (SDR-4437 MEDIUM-2)`

---

# Phase 2 — Fan-out

### Task 2: HIGH-7 — MCP header-only identity must not execute resources as the SP

**Files:**
- Modify: `src/api/mcp_auth.py`
- Modify: `src/api/mcp_server.py` (two `with mcp_auth_scope(request)` call sites only)
- Test: `tests/unit/test_mcp_auth.py` (edit + extend)

**Interfaces:**
- Consumes: `MCPAuthError`, `mcp_auth_scope` (existing); `MCPToolError`, `_create_deck_impl` (~line 326), `_edit_deck_impl` (~732), `_get_deck_status_impl` (~526), `_get_deck_impl` (~863) in `mcp_server.py`.
- Produces: `mcp_auth_scope(request, *, require_user_token: bool = False)` — new keyword. When the resolved identity has no token (priority-3 header-only path): `require_user_token=True` → raises `MCPAuthError`; `require_user_token=False` → binds **no** Databricks client (`set_user_client(None)`), so any downstream `get_user_client()` call fails closed in production via PR-2's `UserClientRequiredError`. **Baseline caveat (verified):** that fail-closed behavior is PR-2's rewrite and does **not** exist on pre-PR-2 `main` — today's `get_user_client()` (`src/core/databricks_client.py:492–511`) logs a warning and falls back to `get_system_client()` when the ContextVar is empty, so binding `None` there would still silently run as the SP. Task 1 Step 1's `grep -q "UserClientRequiredError" src/core/databricks_client.py` precondition exists precisely to refuse that baseline. Read the fail-closed language as defense-in-depth only: the resource tools (`create_deck`/`edit_deck`) are closed by the `require_user_token=True` refusal, which raises before binding anything and is independent of `get_user_client` behavior; the read tools are protected by the read-path trace below (no `get_user_client()` reachable), not by fail-closing.
- Boundary: keep the module trust-model docstring (amend the priority-3 paragraph, don't delete it). Do not touch `extract_mcp_identity`'s resolution logic or the `TELLR_TRUST_FORWARDED_IDENTITY` gate.

**Rationale (spec, HIGH-7):** today `mcp_auth_scope` binds `get_system_client()` when `identity.token is None`, so a header-only (app-to-app) caller executes Genie/UC/model-serving tools **with tellr's SP credentials** — and `enqueue_job` (`src/api/services/job_queue.py:47`) copies that ContextVar into the agent worker, so the whole agent run inherits it. Fix: user OBO token required for resource-executing tools (`create_deck`, `edit_deck` — both enqueue agent runs); header-only identity remains valid for attribution/read ops (`get_deck_status`, `get_deck` — session-manager/DB reads gated by the permission facade, no Databricks SDK calls). This closes the finding by defense-in-depth regardless of whether the proxy strips caller-supplied headers.

**Read-path trace (verified at planning time — binding `set_user_client(None)` cannot break the read tools):** every callee of `_get_deck_status_impl`/`_get_deck_impl` was traced for `get_user_client()` reachability. The `permission_service` facade (`mcp_server.py`) uses only `get_permission_context()` + `get_db_session()` + `PermissionService`, and `src/services/permission_service.py` is pure SQLAlchemy (imports no Databricks client; group ids come from the pre-built context, not an SDK call at check time). `SessionManager` (`src/api/services/session_manager.py` — `get_session`, `get_slide_deck`, `get_chat_request`, `get_session_id_for_request`, `get_messages_for_request`) imports only stdlib + SQLAlchemy + models. `_render_deck_response` is pure object construction; `_public_app_url` reads the `DATABRICKS_APP_URL` env var; `get_job_status` reads the in-memory jobs dict. Group fetching is not on this path (`mcp_auth_scope` calls `build_permission_context(fetch_groups=False)`), and even the group-fetch path acquires its own SP client via `get_system_client()` directly (`src/services/identity_provider.py:99,112`), never the `get_user_client()` ContextVar. Re-verify on the PR-2 head before finalizing: `grep -rn "get_user_client\|get_system_client\|WorkspaceClient" src/services/permission_service.py src/api/services/session_manager.py` (expect no hits).

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_mcp_auth.py`: **delete** `test_scope_uses_system_client_for_forwarded_identity` (its asserted behavior is the vulnerability) and add, using the file's existing `_FakeRequest` / `fake_user_client` helpers:

```python
# ---- HIGH-7 (SDR-4437): priority-3 header-only identity ---------------------


def _forwarded_identity_request():
    return _FakeRequest(
        headers={
            "x-forwarded-email": "alice@example.com",
            "x-forwarded-user": "12345@99999",
        }
    )


def test_scope_binds_no_client_for_forwarded_identity(monkeypatch):
    """Header-only identity must NOT bind the SP client (HIGH-7)."""
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")

    with patch("src.api.mcp_auth.get_or_create_user_client") as user_client_factory, \
         patch("src.api.mcp_auth.set_current_user"), \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context"):

        with mcp_auth_scope(_forwarded_identity_request()) as identity:
            assert identity.source == "x-forwarded-identity"
            assert identity.token is None

        user_client_factory.assert_not_called()
        # Every set_user_client call (entry AND teardown) bound None.
        assert all(c.args[0] is None for c in set_client.call_args_list)
        assert set_client.call_count >= 1


def test_scope_require_user_token_refuses_forwarded_identity(monkeypatch):
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")

    with patch("src.api.mcp_auth.set_current_user") as set_user, \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context") as set_perm:

        with pytest.raises(MCPAuthError, match="user access token"):
            with mcp_auth_scope(
                _forwarded_identity_request(), require_user_token=True
            ):
                pass  # pragma: no cover — must not be reached

        # Refused before binding anything.
        set_user.assert_not_called()
        set_client.assert_not_called()
        set_perm.assert_not_called()


def test_scope_require_user_token_allows_token_callers(fake_user_client):
    req = _FakeRequest(headers={"x-forwarded-access-token": "tok"})

    with patch(
        "src.api.mcp_auth.get_or_create_user_client", return_value=fake_user_client
    ), patch("src.api.mcp_auth.set_current_user"), \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context"):

        with mcp_auth_scope(req, require_user_token=True) as identity:
            assert identity.token == "tok"

        bound = [c.args[0] for c in set_client.call_args_list if c.args[0] is not None]
        assert bound == [fake_user_client]


# ---- HIGH-7: tool-level enforcement (call sites in mcp_server.py) -----------


@pytest.mark.asyncio
async def test_create_deck_refuses_header_only_identity(monkeypatch):
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    from src.api.mcp_server import MCPToolError, _create_deck_impl

    with pytest.raises(MCPToolError, match="user access token"):
        await _create_deck_impl(_forwarded_identity_request(), prompt="make a deck")


@pytest.mark.asyncio
async def test_edit_deck_refuses_header_only_identity(monkeypatch):
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    from src.api.mcp_server import MCPToolError, _edit_deck_impl

    with pytest.raises(MCPToolError, match="user access token"):
        await _edit_deck_impl(
            _forwarded_identity_request(), session_id="s1", instruction="tweak it"
        )


@pytest.mark.asyncio
async def test_get_deck_status_allows_header_only_identity(monkeypatch):
    """Read/attribution tools keep working with header-only identity."""
    monkeypatch.setenv("TELLR_TRUST_FORWARDED_IDENTITY", "true")
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError, _get_deck_status_impl

    with patch.object(mcp_server, "permission_service") as perm:
        perm.can_view_deck.return_value = False
        with pytest.raises(MCPToolError, match="permission"):
            # request_id is a required positional (mcp_server.py:526-528);
            # it is never reached — the permission check fires first.
            await _get_deck_status_impl(
                _forwarded_identity_request(), session_id="s1", request_id="r1"
            )
    # Reaching the permission check proves auth did NOT refuse the caller.
```

Execution notes: verify the impl signatures before finalizing the tool-level tests (`grep -n "async def _create_deck_impl\|async def _edit_deck_impl\|async def _get_deck_status_impl" src/api/mcp_server.py`) and pass whatever minimal required arguments they take — the assertions (which exception, which match) are the contract, the argument lists are not. If `pytest.ini`/`pyproject` lacks `asyncio_mode`, decorate as the existing async tests in `tests/unit/test_mcp_server.py` do.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_mcp_auth.py -v`
Expected: the three new scope tests FAIL (`TypeError: mcp_auth_scope() got an unexpected keyword argument` / SP client still bound); the tool-level refusal tests FAIL (no `MCPToolError` raised at auth time).

- [ ] **Step 3: Implement `mcp_auth.py`**

Change the signature and the client-binding block of `mcp_auth_scope` (~line 149):

```python
@contextmanager
def mcp_auth_scope(
    request: Request, *, require_user_token: bool = False
) -> Iterator[MCPIdentity]:
    """Authenticate an MCP request and bind identity ContextVars for the block.

    On entry: resolves identity, binds ``current_user``, ``user_client``,
    and ``permission_context``.

    On exit: clears all three ContextVars, even if the wrapped block raised.

    HIGH-7 (SDR-4437): when the identity was resolved via priority 3 (header-
    only forwarded identity, no user token), **no Databricks client is bound**
    — the identity is used for attribution and permission checks only. Tools
    that execute Databricks resources (Genie/UC/model serving — anything that
    runs the agent) must pass ``require_user_token=True``, which refuses the
    priority-3 path outright with ``MCPAuthError``. Any stray downstream
    ``get_user_client()`` call on the header-only path fails closed in
    production (``UserClientRequiredError`` — see databricks_client.py) rather
    than silently running as the service principal. Attribution
    (``created_by``) is unaffected: it uses ``user_name`` from the forwarded
    identity headers, which the proxy attests.
    """
    identity = extract_mcp_identity(request)

    if identity.token is not None:
        user_client = get_or_create_user_client(identity.token)
    elif require_user_token:
        raise MCPAuthError(
            "This tool executes Databricks resources and requires a user "
            "access token (x-forwarded-access-token or Authorization: "
            "Bearer). Header-only forwarded identity (app-to-app) is "
            "accepted only for read/attribution operations."
        )
    else:
        # HIGH-7: priority-3 path binds NO client. Downstream services that
        # only need identity (session manager, permission service, MLflow
        # attribution) keep working; anything needing a Databricks client
        # fails closed instead of running as the SP.
        user_client = None
```

The rest of the function body (`build_permission_context` → `set_current_user` / `set_user_client` / `set_permission_context` → `try/yield/finally`) is unchanged — `set_user_client(user_client)` now receives `None` on the priority-3 path. Then:

- Remove `get_system_client` from the `src.core.databricks_client` import (it becomes unused — confirm with `grep -n get_system_client src/api/mcp_auth.py`).
- Amend the **module docstring**, priority-3 bullet: keep the proxy trust-model text through "…cannot be bypassed by external traffic.", then replace the final two sentences ("This path has no user token, so downstream Databricks API calls use tellr's own service principal credentials; attribution … remains the real user via ``user_name``.") with:

```
   This path has no user token, so it is valid for **attribution and
   read/permission operations only**: no Databricks client is bound, and
   tools that execute Databricks resources (Genie/UC/model serving)
   refuse header-only callers (SDR-4437 HIGH-7). Attribution
   (``created_by`` on decks, etc.) remains the real user via ``user_name``.
```

- [ ] **Step 4: Implement the `mcp_server.py` call sites**

- `_create_deck_impl` (~line 354): `with mcp_auth_scope(request) as identity:` → `with mcp_auth_scope(request, require_user_token=True) as identity:` with the comment line above it: `# SDR-4437 HIGH-7: deck generation runs the agent (Genie/UC/model tools) — user OBO token required.`
- `_edit_deck_impl` (~line 773): same change, comment: `# SDR-4437 HIGH-7: editing runs the agent — user OBO token required.`
- `_get_deck_status_impl` (~541) and `_get_deck_impl` (~872): **unchanged** (read/attribution ops; header-only identity allowed).

The existing `except MCPAuthError as e: raise MCPToolError(f"Authentication failed: {e}") from e` blocks in all four impls already surface the refusal as a clean tool error — do not touch them (they interpolate into MCP tool results, not HTTP `detail=`, and are out of MEDIUM-2's scope).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_mcp_auth.py tests/unit/test_mcp_server.py -v`
Expected: all PASS. If a pre-existing `test_mcp_server.py` test fails because it exercised create/edit through a header-only fixture, update **that fixture** to present a bearer token (matching the new contract); never relax the scope.

- [ ] **Step 6: Report for commit**

Commit message: `fix(mcp): header-only forwarded identity binds no client; resource-executing tools require user OBO token (SDR-4437 HIGH-7)`

---

### Task 3: MEDIUM-3 — OAuth state nonce, server-side PKCE, explicit postMessage origins

**Files:**
- Create: `src/database/models/oauth_state.py`
- Modify: `src/database/models/__init__.py` (register `OAuthState`)
- Modify: `src/services/google_slides_auth.py` (`get_auth_url` only)
- Modify: `src/api/routes/google_slides.py` (OAuth section: `_build_redirect_uri` refactor, `auth_url`, `auth_callback`, new helpers; **do not touch the export handlers or their PR-2 gates**)
- Modify: `frontend/src/hooks/useGoogleOAuthPopup.ts` (origin check)
- Create: `tests/unit/test_google_oauth_state.py`
- Modify: `tests/unit/test_google_slides_routes.py` (callback tests only)
- Modify: `tests/unit/config/test_google_oauth.py` (`test_get_auth_url_db_mode` — new return shape)

**Interfaces:**
- Consumes: `Base` (`src/core/database.py:344`; `create_all` at 411 and `src/core/lakebase.py:453` creates any model imported via `src.database.models`), `GoogleSlidesAuth.from_global(user_identity, db)`, `authorize(code, redirect_uri, code_verifier=None)` (unchanged), `_get_user_identity()` (PR-2's fail-closed version — returns `"local_dev"` under `ENVIRONMENT` dev/test, raises in production on OBO failure).
- Produces:
  - `OAuthState` model (`oauth_states` table: `nonce` PK, `user_identity`, `code_verifier`, `created_at`).
  - `google_slides._create_oauth_state(db, nonce: str, user_identity: str, code_verifier: str) -> None` (stores the row for a caller-generated nonce and sweeps expired rows; the caller mints the nonce first because `get_auth_url(state=nonce)` needs it and is what returns the verifier).
  - `google_slides._consume_oauth_state(db, nonce: str)` → `Row(user_identity, code_verifier, created_at) | None` — atomic `DELETE … RETURNING`, single-use under concurrency.
  - `google_slides._public_base_url(request) -> str` (also used by Task 18's smoke reasoning; `_build_redirect_uri` now composes it).
  - `GoogleSlidesAuth.get_auth_url(redirect_uri, state=None) -> tuple[str, str]` — `(auth_url, code_verifier)`; state passed through **untouched** (verifier no longer client-visible).

**Design decisions (recorded):**
- **DB-backed nonce, not in-memory:** the app runs 4 uvicorn workers; `/auth/url` and `/auth/callback` routinely land on different workers, so a per-worker dict fails most callbacks — the same failure mode that made `ExportJob` DB-backed. The `oauth_states` table follows that pattern; `Base` registration means `create_all` creates it with zero operator setup (pip-install constraint).
- **PKCE kept, moved server-side** (the spec's prescribed "PKCE proper" fix): per the spec's corrected analysis, the `code_verifier` read is **live** — `get_auth_url` currently injects the verifier into client-visible `state`, defeating PKCE's purpose. The verifier now lives only in the `oauth_states` row; `state` becomes a bare nonce; the callback fetches the verifier from the consumed row — exactly as the spec prescribes. (There is no "remove the dead read" option that doesn't also change `get_auth_url` — Google would enforce a `code_challenge` the callback could no longer answer.)
- **`state` is the raw nonce string** (no JSON, no `user` field): identity comes exclusively from the authenticated callback request (`_get_user_identity()`), which PR-2 made fail-closed. The spec's correction stands: there was never misattribution-via-state; the `user` field was dead weight and is dropped.
- **Callback failure pages stay HTTP 200 HTML** (popup UX contract — the opener learns the outcome via postMessage; this is the existing success-path shape and must not change).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_google_oauth_state.py`:

```python
"""SDR-4437 MEDIUM-3: OAuth state nonce + server-side PKCE + postMessage origin.

Spec acceptance list: valid nonce; double-consume; cross-user; expired;
unknown nonce; concurrent consume (exactly one winner).
"""

import json
import re
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base, get_db
from src.core.encryption import encrypt_data
from src.database.models import GoogleGlobalCredentials
from src.database.models.oauth_state import OAuthState

CALLBACK = "/api/export/google-slides/auth/callback"
AUTH_URL = "/api/export/google-slides/auth/url"

VALID_CREDENTIALS = json.dumps({
    "installed": {
        "client_id": "test-id.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
})


@pytest.fixture
def db_setup():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield engine, factory
    engine.dispose()


@pytest.fixture
def client(db_setup):
    _, factory = db_setup
    from src.api.main import app

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _seed_credentials(factory):
    db = factory()
    db.add(
        GoogleGlobalCredentials(
            credentials_encrypted=encrypt_data(VALID_CREDENTIALS),
            uploaded_by="admin@test.com",
        )
    )
    db.commit()
    db.close()


def _insert_state(factory, nonce="nonce-1", user="local_dev",
                  verifier="verif-1", created_at=None):
    db = factory()
    row = OAuthState(nonce=nonce, user_identity=user, code_verifier=verifier)
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.commit()
    db.close()


@pytest.fixture
def fake_auth():
    """Patch the auth object the callback builds, recording authorize()."""
    auth = MagicMock()
    with patch(
        "src.api.routes.google_slides.GoogleSlidesAuth"
    ) as cls:
        cls.from_global.return_value = auth
        yield auth


# --- /auth/url stores a server-side row -------------------------------------


def test_auth_url_creates_nonce_row_with_server_side_verifier(client, db_setup):
    _, factory = db_setup
    _seed_credentials(factory)

    resp = client.get(AUTH_URL)
    assert resp.status_code == 200

    state = parse_qs(urlparse(resp.json()["url"]).query)["state"][0]
    # State is the bare nonce — a URL-safe token, not a JSON payload (no
    # user field, no code_verifier). Assert the shape rather than substring
    # absence: substring checks on a random token are theoretically flaky.
    assert re.fullmatch(r"[A-Za-z0-9_-]+", state)

    db = factory()
    row = db.query(OAuthState).filter(OAuthState.nonce == state).one()
    assert row.user_identity == "local_dev"  # ENVIRONMENT=test identity
    assert row.code_verifier  # verifier stored server-side only
    db.close()


# --- callback: the six spec cases --------------------------------------------


def test_callback_valid_nonce_authorizes_and_consumes(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-ok", verifier="verif-xyz")

    resp = client.get(CALLBACK, params={"code": "code-1", "state": "nonce-ok"})
    assert resp.status_code == 200
    assert '"success": true' in resp.text  # json.dumps payload in the page
    fake_auth.authorize.assert_called_once()
    assert fake_auth.authorize.call_args.kwargs["code_verifier"] == "verif-xyz"

    db = factory()
    assert db.query(OAuthState).count() == 0  # consumed
    db.close()


def test_callback_double_consume_rejected(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-once")

    first = client.get(CALLBACK, params={"code": "c", "state": "nonce-once"})
    second = client.get(CALLBACK, params={"code": "c", "state": "nonce-once"})
    assert first.status_code == 200 and second.status_code == 200
    assert fake_auth.authorize.call_count == 1  # replay did not re-authorize
    assert "Authorization Failed" in second.text


def test_callback_cross_user_nonce_rejected(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-mallory", user="mallory@evil.test")

    resp = client.get(CALLBACK, params={"code": "c", "state": "nonce-mallory"})
    assert "Authorization Failed" in resp.text
    fake_auth.authorize.assert_not_called()


def test_callback_expired_nonce_rejected(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(
        factory,
        nonce="nonce-old",
        created_at=datetime.utcnow() - timedelta(minutes=30),
    )

    resp = client.get(CALLBACK, params={"code": "c", "state": "nonce-old"})
    assert "Authorization Failed" in resp.text
    fake_auth.authorize.assert_not_called()


def test_callback_unknown_or_missing_nonce_rejected(client, db_setup, fake_auth):
    resp = client.get(CALLBACK, params={"code": "c", "state": "never-issued"})
    assert "Authorization Failed" in resp.text
    resp = client.get(CALLBACK, params={"code": "c", "state": ""})
    assert "Authorization Failed" in resp.text
    fake_auth.authorize.assert_not_called()


def test_callback_consent_denied_no_code_returns_failure_page(
    client, db_setup, fake_auth
):
    """?error=...&state=... with NO code: popup-contract page, not a 422."""
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-denied")

    resp = client.get(
        CALLBACK, params={"error": "access_denied", "state": "nonce-denied"}
    )
    assert resp.status_code == 200
    assert "Authorization Failed" in resp.text
    fake_auth.authorize.assert_not_called()

    db = factory()
    assert db.query(OAuthState).count() == 0  # nonce retired anyway
    db.close()


def test_concurrent_consume_exactly_one_winner(tmp_path):
    """Atomic DELETE ... RETURNING: one winner under concurrent callbacks."""
    from src.api.routes.google_slides import _consume_oauth_state

    engine = create_engine(
        f"sqlite:///{tmp_path / 'nonce.db'}", connect_args={"timeout": 10}
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)

    db = factory()
    db.add(OAuthState(nonce="race", user_identity="u", code_verifier="v"))
    db.commit()
    db.close()

    results = []
    barrier = threading.Barrier(2)

    def consume():
        session = factory()
        try:
            barrier.wait()
            results.append(_consume_oauth_state(session, "race"))
        finally:
            session.close()

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(r is not None for r in results) == 1


# --- postMessage origin + no error reflection --------------------------------


def test_callback_html_uses_explicit_origin_not_wildcard(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-origin")

    ok = client.get(CALLBACK, params={"code": "c", "state": "nonce-origin"})
    bad = client.get(CALLBACK, params={"code": "c", "state": "never-issued"})
    for resp in (ok, bad):
        assert "postMessage" in resp.text
        # No wildcard targetOrigin anywhere in the page.
        assert "'*'" not in resp.text and '"*"' not in resp.text
        # TestClient base_url origin appears as the explicit target.
        assert "http://testserver" in resp.text


def test_callback_failure_html_never_reflects_exception(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-boom")
    fake_auth.authorize.side_effect = ValueError("SECRET-INTERNAL-DETAIL")

    resp = client.get(CALLBACK, params={"code": "c", "state": "nonce-boom"})
    assert resp.status_code == 200
    assert "Authorization Failed" in resp.text
    assert "SECRET-INTERNAL-DETAIL" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_google_oauth_state.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'src.database.models.oauth_state'`.

- [ ] **Step 3: Create the model and register it**

Create `src/database/models/oauth_state.py`:

```python
"""OAuth state nonce for the Google OAuth flow (SDR-4437 MEDIUM-3).

Single-use, short-TTL rows binding an OAuth callback to a consent flow the
authenticated user actually started (login-CSRF protection), and carrying
the PKCE ``code_verifier`` server-side so it is never client-visible.

DB-backed by construction: the app runs multiple uvicorn workers and
``/auth/url`` and ``/auth/callback`` routinely land on different workers,
so an in-memory per-worker store fails most callbacks — the same reason
``ExportJob`` lives in the DB. Registered on ``Base`` so ``create_all``
creates the table with zero operator setup on a fresh pip install.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from src.core.database import Base


class OAuthState(Base):
    """Single-use OAuth state nonce, consumed atomically on callback."""

    __tablename__ = "oauth_states"

    # secrets.token_urlsafe(32) -> 43 chars (256 bits of entropy).
    nonce = Column(String(64), primary_key=True)
    user_identity = Column(String(255), nullable=False, index=True)
    code_verifier = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:  # never include the verifier
        return f"<OAuthState(user='{self.user_identity}')>"
```

In `src/database/models/__init__.py`: add `from src.database.models.oauth_state import OAuthState` to the import block (alphabetical position) and `"OAuthState"` to `__all__`. (This is what makes `Base.metadata.create_all` — `src/core/database.py:411`, `src/core/lakebase.py:453` — create the table on boot.)

- [ ] **Step 4: Move PKCE server-side in `google_slides_auth.py`**

Replace `get_auth_url` (~line 229):

```python
    def get_auth_url(
        self, redirect_uri: str, state: str | None = None
    ) -> tuple[str, str]:
        """Generate the OAuth2 consent URL with PKCE.

        SDR-4437 MEDIUM-3: the PKCE ``code_verifier`` is returned to the
        caller for **server-side** storage (``oauth_states`` row) instead of
        being embedded in the client-visible ``state`` parameter. ``state``
        is passed through to Google untouched.

        Args:
            redirect_uri: The registered OAuth callback URI (no query params).
            state: Opaque state string (the server-issued nonce).

        Returns:
            (auth_url, code_verifier)
        """
        flow = self._build_flow(redirect_uri)
        verifier, challenge = self._generate_pkce()

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
            code_challenge=challenge,
            code_challenge_method="S256",
        )
        logger.info("Generated Google OAuth consent URL")
        return auth_url, verifier
```

`authorize()` is unchanged (it already accepts `code_verifier`). Update `tests/unit/config/test_google_oauth.py::test_get_auth_url_db_mode` to unpack the tuple:

```python
        url, verifier = auth.get_auth_url(
            redirect_uri="http://localhost/callback", state="nonce-abc"
        )
        assert "code_challenge=" in url
        assert "state=nonce-abc" in url
        assert verifier  # returned for server-side storage
        assert verifier not in url  # never client-visible
```

- [ ] **Step 5: Rewrite the OAuth section of `google_slides.py`**

Imports to add near the top: `import secrets`, `from datetime import datetime, timedelta`, `from sqlalchemy import delete`, `from src.database.models.oauth_state import OAuthState`. Module constant:

```python
# MEDIUM-3 (SDR-4437): OAuth state nonces are single-use and short-lived.
_OAUTH_STATE_TTL_SECONDS = 600
```

Refactor `_build_redirect_uri` (~91) into two functions — the base-URL logic moves verbatim into `_public_base_url`:

```python
def _public_base_url(request: Request) -> str:
    """Public origin of the app, reconstructed from x-forwarded-* headers.

    Behind a reverse proxy (Databricks Apps), ``request.base_url`` returns
    the internal address; the proxy's X-Forwarded-Host/Proto give the public
    one. Also used as the explicit postMessage targetOrigin in the OAuth
    popup pages (SDR-4437 MEDIUM-3).
    """
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto")

    if forwarded_host:
        scheme = forwarded_proto or "https"
        return f"{scheme}://{forwarded_host.split(',')[0].strip()}"

    base = str(request.base_url).rstrip("/")
    # Force http for localhost (Google rejects https://localhost)
    if "://localhost" in base or "://127.0.0.1" in base:
        base = base.replace("https://", "http://")
    return base


def _build_redirect_uri(request: Request) -> str:
    """Build the OAuth callback redirect URI (exact-match, no query params)."""
    return f"{_public_base_url(request)}/api/export/google-slides/auth/callback"
```

(Keep the original docstring content on whichever function it best describes; the existing `test_build_redirect_uri` assertions must still pass.)

Add the nonce helpers:

```python
def _create_oauth_state(
    db: Session, nonce: str, user_identity: str, code_verifier: str
) -> None:
    """Store a single-use state nonce bound to the authenticated user.

    The caller generates the nonce first: it must be handed to
    ``get_auth_url(state=nonce)``, which is also the call that returns the
    PKCE verifier — so this helper cannot mint the nonce itself (the row's
    PK must equal the ``state`` sent to Google). Expired rows are swept
    opportunistically on every insert.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=_OAUTH_STATE_TTL_SECONDS)
    db.query(OAuthState).filter(OAuthState.created_at < cutoff).delete()
    db.add(
        OAuthState(
            nonce=nonce, user_identity=user_identity, code_verifier=code_verifier
        )
    )
    db.commit()


def _consume_oauth_state(db: Session, nonce: str):
    """Atomically consume a state nonce (single-use, race-safe).

    ``DELETE ... WHERE nonce = :n RETURNING ...`` — under two concurrent
    callbacks exactly one wins; the loser sees no row. Returns the Row
    (user_identity, code_verifier, created_at) or None.
    """
    if not nonce:
        return None
    row = db.execute(
        delete(OAuthState)
        .where(OAuthState.nonce == nonce)
        .returning(
            OAuthState.user_identity,
            OAuthState.code_verifier,
            OAuthState.created_at,
        )
    ).first()
    db.commit()
    return row
```

Add the popup-page builders (fixed literals only — never exception-derived; explicit targetOrigin closes the `postMessage(..., '*')` wildcard):

```python
def _callback_page(
    app_origin: str, *, success: bool, heading: str, body_text: str, close_ms: int
) -> HTMLResponse:
    payload = json.dumps({"type": "google-slides-auth", "success": success})
    origin_js = json.dumps(app_origin)
    return HTMLResponse(
        content=f"""
        <html><body>
            <h2>{heading}</h2>
            <p>{body_text}</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({payload}, {origin_js});
                }}
                setTimeout(() => window.close(), {close_ms});
            </script>
        </body></html>
        """,
        status_code=200,
    )


def _oauth_success_html(app_origin: str) -> HTMLResponse:
    return _callback_page(
        app_origin,
        success=True,
        heading="Authorization Successful",
        body_text="You can close this window.",
        close_ms=1500,
    )


def _oauth_failure_html(app_origin: str) -> HTMLResponse:
    # MEDIUM-2: generic text only — the reason is logged server-side.
    return _callback_page(
        app_origin,
        success=False,
        heading="Authorization Failed",
        body_text=(
            "Authorization failed. Close this window and try connecting "
            "your Google account again."
        ),
        close_ms=3000,
    )
```

Replace the `auth_url` handler body (keep the decorator, response model, and the two except clauses exactly as they are — Task 4 sweeps their `detail=` strings, not this task):

```python
    try:
        user_identity = _get_user_identity()
        auth = GoogleSlidesAuth.from_global(user_identity, db)
        redirect_uri = _build_redirect_uri(request)

        # MEDIUM-3 (SDR-4437): state carries ONLY a server-issued single-use
        # nonce; the PKCE verifier and the user binding live in the
        # oauth_states row, never in anything client-visible. Nonce first,
        # then get_auth_url (which returns the verifier), then the row.
        nonce = secrets.token_urlsafe(32)  # 256-bit
        url, code_verifier = auth.get_auth_url(redirect_uri=redirect_uri, state=nonce)
        _create_oauth_state(db, nonce, user_identity, code_verifier)

        return AuthUrlResponse(url=url)
```

(Update the `auth_url` docstring: state carries a single-use nonce, not the user identity. Invariant: the nonce passed as `state` to `get_auth_url` must equal the `oauth_states` row's PK — `_create_oauth_state` takes the nonce as an argument for exactly this reason.)

Replace the `auth_callback` handler:

```python
@router.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback(
    request: Request,
    code: str = Query("", description="Authorization code (absent when the user denies consent)"),
    state: str = Query("", description="Server-issued single-use state nonce"),
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback from Google.

    MEDIUM-3 (SDR-4437): ``state`` is a single-use server-issued nonce
    (``oauth_states`` row) binding this callback to a consent flow that the
    authenticated request user started. Login-CSRF — an attacker completing
    their own consent and feeding the victim their code — fails the
    nonce/user checks. Token persistence keys off the authenticated request
    identity, never off anything client-supplied. All failures return the
    same generic popup page (HTTP 200 + postMessage, the popup contract);
    the specific reason is logged server-side only (MEDIUM-2).
    """
    app_origin = _public_base_url(request)

    try:
        user_identity = _get_user_identity()
    except Exception:
        # PR-2's fail-closed _get_user_identity() raises in production on OBO
        # failure — keep the popup contract: generic page, reason in the log
        # (an unhandled raise here would surface as a 500 JSON body instead).
        logger.error("OAuth callback failed to resolve user identity", exc_info=True)
        return _oauth_failure_html(app_origin)

    if not code:
        # Consent denied / error redirect: Google calls back with ?error=...
        # and NO code. `code` is optional (default "") precisely so this path
        # returns the popup-contract page instead of FastAPI's 422 JSON
        # validation error. Retire the nonce — the flow is over either way.
        _consume_oauth_state(db, state)
        logger.warning(
            "OAuth callback rejected: no authorization code "
            "(consent denied or error redirect)"
        )
        return _oauth_failure_html(app_origin)

    row = _consume_oauth_state(db, state)
    if row is None:
        logger.warning("OAuth callback rejected: unknown or already-used state nonce")
        return _oauth_failure_html(app_origin)
    if row.user_identity != user_identity:
        logger.warning("OAuth callback rejected: state nonce belongs to another user")
        return _oauth_failure_html(app_origin)
    if datetime.utcnow() - row.created_at > timedelta(
        seconds=_OAUTH_STATE_TTL_SECONDS
    ):
        logger.warning("OAuth callback rejected: state nonce expired")
        return _oauth_failure_html(app_origin)

    try:
        auth = GoogleSlidesAuth.from_global(user_identity, db)
        redirect_uri = _build_redirect_uri(request)
        auth.authorize(
            code=code, redirect_uri=redirect_uri, code_verifier=row.code_verifier
        )
        logger.info(
            "Google Slides OAuth callback successful", extra={"user": user_identity}
        )
    except Exception:
        # MEDIUM-2 (SDR-4437): never reflect the exception into the page.
        logger.error("OAuth callback failed", exc_info=True)
        return _oauth_failure_html(app_origin)

    return _oauth_success_html(app_origin)
```

This removes: the `json.loads(state)` parse, the `user` state field and its check, the client-visible `code_verifier` read, the `{exc}` HTML reflection, and both `postMessage(..., '*')` wildcards. It also fixes a pre-existing gap that would otherwise falsify the docstring's "all failures return the generic popup page" contract: `code` was a **required** query param, so a consent-denied redirect (`?error=...`, no `code`) returned a 422 JSON validation error — raw JSON in the popup, no `postMessage`, resolved only by the hook's popup-closed polling fallback. `code` is now optional and the no-code path returns `_oauth_failure_html`. Likewise, `_get_user_identity()` is wrapped so a production OBO failure (PR-2's fail-closed behavior) yields the generic failure page rather than an unhandled 500. `GoogleSlidesAuth` is already imported at module top (needed for the `from_global` patch seam in tests — verify, and keep `_get_auth` for the other routes that use it).

- [ ] **Step 6: Frontend origin check**

`frontend/src/hooks/useGoogleOAuthPopup.ts` — add the origin guard as the first line of `handleMessage`:

```ts
      const handleMessage = (event: MessageEvent) => {
        // SDR-4437 MEDIUM-3: the callback page posts with an explicit
        // targetOrigin; only trust messages from our own origin so a hostile
        // page cannot spoof a "connected" state.
        if (event.origin !== window.location.origin) return;
        if (event.data?.type === 'google-slides-auth') {
          cleanup();
          resolve(event.data.success === true);
        }
      };
```

(Local-dev note, record in the report: when the Vite dev server origin differs from the API origin, the message is dropped and the hook's existing popup-closed polling fallback — `checkGoogleSlidesAuth()` — still resolves the flow. No change needed.)

- [ ] **Step 7: Update existing callback tests**

In `tests/unit/test_google_slides_routes.py` (`TestAuthCallback` class, ~175–215): the old tests pass `state=json.dumps({"user": ...})` / assert "Missing user" semantics. Update them to the nonce model: an unknown/absent nonce now yields the generic failure page (`"Authorization Failed"` present, `postMessage` present, no `'*'` targetOrigin). Rename `test_callback_missing_user_in_state` → `test_callback_without_valid_nonce_rejected`. Keep `test_callback_no_credentials_returns_failure_html` / `test_callback_invalid_code_returns_failure_html` but note they now fail at the nonce check (still failure HTML — assertions on the page shape survive; drop any assertion on specific error text). Do not modify other test classes in the file.

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_google_oauth_state.py tests/unit/test_google_slides_routes.py tests/unit/config/test_google_oauth.py tests/unit/test_authz_google_slides.py -v && rm -rf mlruns`
Expected: all PASS (the last file proves PR-2's export/poll gates were untouched). Then confirm the HTML-reflection half of the gate is green: `python -m pytest tests/unit/test_no_exception_interpolation.py::test_no_exception_reflection_into_html_responses -v` → PASS.

Frontend check: `cd frontend && npm run lint` → no new errors.

- [ ] **Step 9: Report for commit**

Commit message: `fix(oauth): DB-backed single-use state nonce + server-side PKCE + explicit postMessage origins for Google OAuth (SDR-4437 MEDIUM-3)`

---

### Task 4: MEDIUM-2 sweep — `google_slides.py` (9 sites) — **runs after Task 3 is committed**

**Files:**
- Modify: `src/api/routes/google_slides.py` (`detail=` strings in except blocks only)

**Ordering:** same file as Task 3 — the sub-supervisor dispatches this only after Task 3's commit. Line refs below are pre-Task-3 and will have shifted; relocate by grep.

**Site table** (apply the Replacement Recipe with these exact literals):

| ~Line | Handler | Caught / status | Current | Replacement `detail=` |
|---|---|---|---|---|
| 151 | `auth_url` | `GoogleSlidesAuthError` / 400 | `str(exc)` | `"Google authorization is missing, expired, or not configured. Connect your Google account and try again."` |
| 260 | `start_google_slides_export` | `GoogleSlidesAuthError` / 400 | `str(exc)` | same literal as 151 |
| 274 | `start_google_slides_export` | `Exception` / 500 | `f"Failed to fetch slides: {exc}"` | `"Failed to fetch slides"` |
| 387 | `export_google_slides_from_records` | `GoogleSlidesAuthError` / 400 | `str(exc)` | same literal as 151 |
| 403 | `export_google_slides_from_records` | `EmitError` / 500 | `f"PPTX build failed: {exc}"` | `"PPTX build failed"` |
| 421 | `export_google_slides_from_records` | `Exception` / 502 | `f"Drive upload failed: {exc}"` | `"Drive upload failed"` |
| 488 | `export_google_slides_from_huashu` | `GoogleSlidesAuthError` / 400 | `str(exc)` | same literal as 151 |
| 530 | `export_google_slides_from_huashu` | `HuashuExportError` / 503 | `f"Huashu pipeline unavailable: {exc}"` | `"Huashu pipeline unavailable"` |
| 563 | `export_google_slides_from_huashu` | `Exception` / 502 | `f"Drive upload failed: {exc}"` | `"Drive upload failed"` |

Logging notes: sites 274/403/421/530/563 already log with `exc_info=True` — keep. The four `GoogleSlidesAuthError` 400 sites have no log — add `logger.warning("<handler_name> rejected: %s", exc)` above each raise (the service's own messages, e.g. `"Token refresh failed: {exc}"`, land in the log and no longer reach the client). Keep every `from exc` chain.

- [ ] **Step 1: Confirm red** — run `python -m pytest tests/unit/test_no_exception_interpolation.py::test_no_exception_interpolation_in_detail -v` and confirm `google_slides.py` entries appear in the failure list.
- [ ] **Step 2: Apply the recipe** per the table above.
- [ ] **Step 3: Verify** — rerun the gate test: `google_slides.py` entries gone. Then `python -m pytest tests/unit/test_google_slides_routes.py tests/unit/test_google_oauth_state.py tests/unit/test_authz_google_slides.py -v`. If an existing test asserted a specific leaked message, update its assertion to the new literal — never the code.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in google_slides routes; details to server log (SDR-4437 MEDIUM-2)`

---

### Task 5: MEDIUM-2 sweep — `slides.py` (33 sites)

**Files:**
- Modify: `src/api/routes/slides.py`

**Context:** PR-2 deleted this file's helper block (~lines 33–110), so every line ref below shifts down by ~77 — relocate by grep (`grep -n "detail=str(e)" src/api/routes/slides.py`). The 33 sites are five repeated except-ladders on the element-CRUD handlers plus per-handler tails. All 500-class blocks here already log with `exc_info=True` — keep those logs.

**Site table** (pre-shift lines; Form B throughout):

| Caught / status | Sites (~lines, handler) | Replacement `detail=` |
|---|---|---|
| `PermissionError` / 423 | 205, 235 (`reorder_slides`); 272, 303 (`update_slide`); 341, 371 (`duplicate_slide`); 415, 445 (`delete_slide`); 869 (`restore_version`) | `"This deck is locked by another editing session. Try again shortly."` |
| `VersionConflictError` / 409 | 233 (`reorder_slides`); 301 (`update_slide`); 369 (`duplicate_slide`); 443 (`delete_slide`) | `"The deck was modified by another request. Refresh and try again."` |
| `ValueError` / 400 | 238 (`reorder_slides`); 306 (`update_slide`); 374 (`duplicate_slide`); 448 (`delete_slide`); 611 (`create_version`); 657 (`update_version_verification`); 872 (`restore_version`) | `"Invalid request."` |
| `Exception` / 500 | 179 (`get_slides`) | `"Failed to get slides"` |
| `Exception` / 500 | 241 | `"Failed to reorder slides"` |
| `Exception` / 500 | 309 | `"Failed to update slide"` |
| `Exception` / 500 | 377 | `"Failed to duplicate slide"` |
| `Exception` / 500 | 451 | `"Failed to delete slide"` |
| `Exception` / 500 | 547 (`update_slide_verification`) | `"Failed to update slide verification"` |
| `Exception` / 500 | 614 (`create_version`) | `"Failed to create version"` |
| `Exception` / 500 | 660 (`update_version_verification`) | `"Failed to update version verification"` |
| `Exception` / 500 | 725 (`sync_latest_version_verification`) | `"Failed to sync version verification"` |
| `Exception` / 500 | 760 (`list_versions`) | `"Failed to list versions"` |
| `Exception` / 500 | 808 (`preview_version`) | `"Failed to preview version"` |
| `Exception` / 500 | 875 (`restore_version`) | `"Failed to restore version"` |
| `Exception` / 500 | 911 (`get_current_version`) | `"Failed to get current version"` |

Logging: the 423/409/400 blocks mostly have no log (400 in `reorder_slides` has a `logger.warning` — keep it) — add `logger.warning("<handler_name> rejected: %s", e)` where absent.

- [ ] **Step 1: Confirm red** — gate test lists 33 `slides.py` entries.
- [ ] **Step 2: Apply the recipe** per the table.
- [ ] **Step 3: Verify** — gate test: `slides.py` entries gone; then `python -m pytest tests/unit -k "slides or version" -v`. Fix only test assertions that pinned leaked messages.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in slides routes (SDR-4437 MEDIUM-2)`

---

### Task 6: MEDIUM-2 sweep — `sessions.py` (19 sites — REFRESHED 2026-07-17)

**Files:**
- Modify: `src/api/routes/sessions.py`

**Context:** PR-2 deleted this file's helper block and moved helpers into `_authz.py`; PR #213 later added the `duplicate_session` handler (3 new sites). Relocate every site by grep — line numbers are post-merge approximate. The 12 original Form-A sites and the 4 Form-B lock-endpoint sites are inside `except Exception` blocks that already log with `exc_info=True` — keep the logs. **Do NOT touch the `SessionNotFoundError` handlers' `detail=f"Session not found: {session_id}"` strings — those interpolate a caller-supplied request identifier, not an exception, and the gate deliberately does not flag them (Global Constraints).**

**Site table** (line numbers are current-main approximate; relocate by grep):

| ~Line | Handler | Form | Replacement `detail=` |
|---|---|---|---|
| 104 | `create_session` | A | `"Failed to create session"` |
| 152 | `list_sessions` | A | `"Failed to list sessions"` |
| 238 | shared-presentations list | A | `"Failed to list shared presentations"` |
| 359 | contributor-session create | A | `"Failed to create contributor session"` |
| 424 | `get_session` | A | `"Failed to get session"` |
| 481 | `update_session` | A | `"Failed to update session"` |
| **536** | **`duplicate_session`** | **B (`SessionAccessDeniedError` `e.message` / 403)** | **`"You don't have permission to duplicate this deck."`** |
| **541** | **`duplicate_session`** | **B (`ValueError` `str(e)` / 400 validation)** | **`"Invalid request."`** |
| **546** | **`duplicate_session`** | **A (`Exception` `f"Failed to duplicate session: {str(e)}"` / 500)** | **`"Failed to duplicate session"`** |
| 586 | `delete_session` | A | `"Failed to delete session"` |
| 640 | `get_session_messages` | A | `"Failed to get messages"` |
| 696 | `add_message` | A | `"Failed to add message"` |
| 735 | `get_session_slides` | A | `"Failed to get slides"` |
| 758 | `cleanup_expired_sessions` | A | `"Cleanup failed"` |
| 840 | `export_session` | A | `"Export failed"` |
| 873 | `acquire_editing_lock` | B (`str(e)` / 500) | `"Failed to acquire editing lock"` |
| 898 | `release_editing_lock` | B / 500 | `"Failed to release editing lock"` |
| 917 | `get_editing_lock_status` | B / 500 | `"Failed to get editing lock status"` |
| 942 | `heartbeat_editing_lock` | B / 500 | `"Failed to heartbeat editing lock"` |

(Form A: keep the existing prefix, drop `: {str(e)}` — the replacements above are exactly those prefixes.)

**`duplicate_session` logging notes:** the `ValueError` block (541) already has `logger.warning("Validation error in duplicate_session: %s", e)`-style logging — keep it; the `Exception` block (546) already logs with `exc_info=True` — keep it; the `SessionAccessDeniedError` block (536) has no log — add `logger.warning("duplicate_session denied: %s", e)` above the raise. Keep every `from e` chain and all status codes.

- [ ] **Step 1: Confirm red** — gate lists 19 `sessions.py` entries (16 original + 3 `duplicate_session`).
- [ ] **Step 2: Apply the recipe.**
- [ ] **Step 3: Verify** — gate entries gone; `python -m pytest tests/unit -k "session" -v`.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in sessions routes (SDR-4437 MEDIUM-2)`

---

### Task 7: MEDIUM-2 sweep — `export.py` (7 sites)

**Files:**
- Modify: `src/api/routes/export.py`

**Site table:**

| ~Line | Handler | Caught / status | Current | Replacement `detail=` |
|---|---|---|---|---|
| 603 | `export_pptx` | `Exception` / 500 | `f"PPTX conversion failed: {str(e)}"` | `"PPTX conversion failed"` |
| 614 | `export_pptx` | `Exception` / 500 | `f"Export failed: {str(e)}"` | `"Export failed"` |
| 620 | `export_pptx` (outer) | `Exception` / 500 | `f"Export failed: {str(e)}"` | `"Export failed"` |
| 751 | `start_pptx_export_async` | `Exception` / 500 | `str(e)` | `"Failed to start async export"` |
| 889 | `export_pptx_editable_from_records` | `Exception` / 500 | `str(e)` | `"Editable PPTX export failed"` |
| 981 | `export_pptx_editable` | `EditableExportError` / 503 | `str(e)` | `"Editable PPTX export is not available."` |
| 1224 | `export_pptx_huashu_from_html` | `HuashuExportError` / 500 | `str(e)` | `"Huashu export failed."` |

Logging: 614/620 already log with `exc_info=True`; 603's block logs only via the inner cleanup — ensure a `logger.error("PPTX conversion failed", exc_info=True)` (or equivalent existing line) is present; 751/889/981/1224 — add the recipe's log line if the block has none.

- [ ] **Step 1: Confirm red** — gate lists 7 `export.py` entries.
- [ ] **Step 2: Apply the recipe.**
- [ ] **Step 3: Verify** — gate entries gone; `python -m pytest tests/unit -k "export" -v` (includes PR-2's `test_authz_export.py` — proves gates untouched).
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in export routes (SDR-4437 MEDIUM-2)`

---

### Task 8: MEDIUM-2 sweep — `chat.py` (4 sites)

**Files:**
- Modify: `src/api/routes/chat.py`

**Site table:**

| ~Line | Handler | Caught / status | Replacement `detail=` |
|---|---|---|---|
| 108 | `_check_chat_permission` (helper) | `PermissionError` / 423 | `"This deck is locked by another editing session. Try again shortly."` |
| 263 | `send_message` | `PermissionError` / 423 | same lock literal |
| 274 | `send_message` | `Exception` / 500 (Form A `f"Failed to process message: {str(e)}"`) | `"Failed to process message"` |
| 552 | `submit_chat_async` | `Exception` / 500 (`str(e)`) | `"Failed to submit chat request"` |

Logging: 274 already logs with `exc_info=True`; 552 logs without traceback — add `exc_info=True`; 108/263 add `logger.warning(...)` per recipe. UX note (recorded, accepted): the 423 literal no longer names the lock holder; the editing-lock **status endpoint** still exposes `locked_by` to collaborators, so the frontend can render who holds the lock without the error string.

- [ ] **Step 1: Confirm red** — gate lists 4 `chat.py` entries.
- [ ] **Step 2: Apply the recipe.**
- [ ] **Step 3: Verify** — gate entries gone; `python -m pytest tests/unit -k "chat" -v`.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in chat routes (SDR-4437 MEDIUM-2)`

---

### Task 9: MEDIUM-2 sweep — `verification.py` (3 sites)

**Files:**
- Modify: `src/api/routes/verification.py`

**Site table** (all Form A, `except Exception` / 500, blocks already log with `exc_info=True`):

| ~Line | Handler | Replacement `detail=` |
|---|---|---|
| 267 | `verify_slide` | `"Verification failed"` |
| 385 | slide feedback | `"Failed to submit feedback"` |
| 510 | genie-link | `"Failed to get Genie link"` |

- [ ] **Step 1: Confirm red**; **Step 2: apply recipe**; **Step 3: verify** — gate entries gone; `python -m pytest tests/unit -k "verification" -v`.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in verification routes (SDR-4437 MEDIUM-2)`

---

### Task 10: MEDIUM-2 sweep — `images.py` (3 sites)

**Files:**
- Modify: `src/api/routes/images.py`

**Site table:**

| ~Line | Handler | Caught / status | Replacement `detail=` |
|---|---|---|---|
| 129 | `upload_image` | `ValueError` / 400 | `"Invalid image upload."` |
| 195 | `get_image_data` | `ValueError` / 404 | `"Image not found"` |
| 248 | `delete_image` | `ValueError` / 404 | `"Image not found"` |

Logging: none of the three `ValueError` blocks logs — add `logger.warning("<handler_name> rejected: %s", e)` to each. Do not touch PR-2's owner-check 403s or the `except HTTPException: raise` lines.

- [ ] **Step 1: Confirm red**; **Step 2: apply recipe**; **Step 3: verify** — gate entries gone; `python -m pytest tests/unit -k "image" -v` (includes PR-2's `test_authz_images.py`).
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in images routes (SDR-4437 MEDIUM-2)`

---

### Task 11: MEDIUM-2 sweep — `settings/identities.py` (3 sites)

**Files:**
- Modify: `src/api/routes/settings/identities.py`

**Site table** (all Form A `{e}`, `except Exception` / 500, blocks already log with `exc_info=True`):

| ~Line | Handler | Replacement `detail=` |
|---|---|---|
| 112 | list users | `"Failed to list users"` |
| 152 | list groups | `"Failed to list groups"` |
| 206 | search identities | `"Failed to search identities"` |

- [ ] **Step 1: Confirm red**; **Step 2: apply recipe**; **Step 3: verify** — gate entries gone; `python -m pytest tests/unit -k "identit" -v`.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in identities routes (SDR-4437 MEDIUM-2)`

---

### Task 12: MEDIUM-2 sweep — `settings/contributors.py` (2 sites)

**Files:**
- Modify: `src/api/routes/settings/contributors.py`

**Site table:**

| ~Line | Handler | Caught / status | Replacement `detail=` |
|---|---|---|---|
| 239 | `add_contributor` | `ValueError` / 400 (validator messages) | `"Invalid permission level or identity type."` |
| 421 | `update_contributor` | `ValueError` / 400 | `"Invalid permission level or identity type."` |

Logging: add `logger.warning("<handler_name> rejected: %s", e)` to each (no log today; ensure the file has a module logger).

- [ ] **Step 1: Confirm red**; **Step 2: apply recipe**; **Step 3: verify** — gate entries gone; `python -m pytest tests/unit -k "contributor" -v`.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in contributors routes (SDR-4437 MEDIUM-2)`

---

### Task 13: MEDIUM-2 sweep — `setup.py` (2 sites)

**Files:**
- Modify: `src/api/routes/setup.py`

**Site table** (both Form A, `except Exception`; blocks log without traceback — add `exc_info=True`):

| ~Line | Handler | Status | Replacement `detail=` |
|---|---|---|---|
| 126 | configure workspace | 500 | `"Failed to save configuration"` |
| 157 | `test_connection` | 400 | `"Connection failed"` |

(Recorded, accepted: the local-dev setup flow loses inline auth-error text; the reason is in the server log, which for this local-only flow is the same terminal.)

- [ ] **Step 1: Confirm red**; **Step 2: apply recipe**; **Step 3: verify** — gate entries gone; `python -m pytest tests/unit -k "setup" -v`.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client errors in setup routes (SDR-4437 MEDIUM-2)`

---

### Task 14: MEDIUM-2 sweep — `feedback.py` (1 site)

**Files:**
- Modify: `src/api/routes/feedback.py`

**Site:** ~line 30, `feedback_chat`, `ValueError` / 503 → `detail="Feedback service is unavailable."`. Add `logger.warning("feedback_chat rejected: %s", e)` (block has no log). Do not touch PR-2's `require_admin` dependencies on the read endpoints.

- [ ] **Step 1: Confirm red**; **Step 2: apply recipe**; **Step 3: verify** — gate entries gone; `python -m pytest tests/unit -k "feedback" -v`.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client error in feedback chat route (SDR-4437 MEDIUM-2)`

---

### Task 15: MEDIUM-2 sweep — `agent_config.py` (1 site)

**Files:**
- Modify: `src/api/routes/agent_config.py`

**Site:** ~line 153, `patch_tools`, pydantic `ValidationError` / 422 → `detail="Invalid agent tool configuration."`. Add `logger.warning("patch_tools rejected: %s", exc)`. Keep the 422 status and `ValidationError` type; do not touch PR-2's CAN_MANAGE gates.

- [ ] **Step 1: Confirm red**; **Step 2: apply recipe**; **Step 3: verify** — gate entries gone; `python -m pytest tests/unit -k "agent_config" -v`.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client error in agent-config tools patch (SDR-4437 MEDIUM-2)`

---

### Task 16: MEDIUM-2 sweep — `admin.py` (1 site)

**Files:**
- Modify: `src/api/routes/admin.py`

**Site:** ~line 96, google-credentials upload, `ValueError` / 400 from `validate_credentials_json` → `detail="Invalid Google credentials file. Upload the OAuth client JSON downloaded from Google Cloud Console."`. Add `logger.warning("google-credentials upload rejected: %s", exc)`. Keep `from exc`; do not touch PR-2's router-level `require_admin`.

- [ ] **Step 1: Confirm red**; **Step 2: apply recipe**; **Step 3: verify** — gate entries gone; `python -m pytest tests/unit -k "admin" -v`.
- [ ] **Step 4: Report for commit** — `fix(errors): generic client error in admin credentials upload (SDR-4437 MEDIUM-2)`

---

# Phase 3 — Convergence

### Task 17: Gate green + full suite + frontend build

**Files:** none expected (any `src/` fix routes back to the owning task's implementer).

- [ ] **Step 1: The gate is green**

Run: `python -m pytest tests/unit/test_no_exception_interpolation.py -v`
Expected: both tests PASS — **zero remaining exception-variable interpolation sites in `src/api/routes/`** (this is the final regex/AST gate the track promised — precisely: no `detail=` or `HTMLResponse` inside an `except ... as <name>:` block references the bound exception variable). The gate is deliberately no broader than that: request-identifier interpolations (e.g. `f"Session not found: {session_id}"`) remain allowed per Global Constraints, and an exception smuggled through an intermediate variable or helper would evade the AST check — accepted residual risk, covered only by the recipe's rule that implementers never introduce new interpolations. Belt-and-braces spot check:

```bash
grep -rnE 'detail=(f".*\{(str\()?(e|exc)\)?\}|str\((e|exc)\))' src/api/routes/ ; echo "exit=$? (want 1 = no matches)"
```

If any site remains, re-dispatch the owning file task — do not fix inline here.

- [ ] **Step 2: Track-specific suites**

Run: `python -m pytest tests/unit/test_mcp_auth.py tests/unit/test_mcp_server.py tests/unit/test_google_oauth_state.py tests/unit/test_google_slides_routes.py tests/unit/config/test_google_oauth.py -v`
Expected: all PASS.

- [ ] **Step 3: PR-2 invariants still hold**

Run: `python -m pytest tests/unit/test_route_authz_coverage.py tests/unit/test_user_client_fail_closed.py tests/unit/test_identity_helpers_fail_closed.py -v`
Expected: all PASS — proves this track didn't disturb PR-2's gates, coverage test, or fail-closed identity helpers.

- [ ] **Step 4: Full backend suite + frontend**

Run: `python -m pytest tests/unit tests/integration -q; rm -rf mlruns`
Expected: all PASS. Pre-existing tests that pinned a leaked error message get their assertion updated to the new literal by the owning task's implementer — never by weakening the change.

Run: `cd frontend && npm run lint && npm run build`
Expected: clean lint, successful production build (the hook change is inside the wheel's built frontend, so the build must pass before publish).

- [ ] **Step 5: Report for commit (only if convergence needed edits)**

Commit message: `test(pr4): convergence — interpolation gate green, full suite green (SDR-4437)`

---

### Task 18: Deploy & evaluation (devloop smoke)

**Own devloop instance built from this branch.** References: `.claude/skills/deploy-tellr-dev/`, `docs/technical/dev-deploy.md`.

**Scope note (expected, by design):** this branch includes PR-2's changes, so the deployed evaluation covers **PR-2 + PR-4 combined** — that is the wave-2 design, not contamination. Any authz-smoke anomaly is reported against PR-2's track, not fixed here.

- [ ] **Step 1: Publish flow (serialized — signal, don't run)**

Push the branch, then **signal the orchestrator** to run `gh workflow run publish-dev.yml` (the publish workflow is serialized across tracks; do not run it directly from this track). Note the published `.devN` version from the orchestrator's reply.

- [ ] **Step 2: Deploy to the devtest workspace**

Run: `./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi <version>`
Expected: deploy completes; app starts (watch for the startup-timeout issue documented in the devloop notes — retry once before escalating). Confirm in startup logs that `create_all` ran without errors (the `oauth_states` table now exists — verify with a Lakebase query if logs are ambiguous: `SELECT count(*) FROM oauth_states;` should succeed).

- [ ] **Step 3: Smoke checks (all must pass)**

1. **Full Google OAuth popup connect flow end-to-end (nonce path):** as a test user with Google credentials configured, click Connect → Google consent → popup shows "Authorization Successful" and closes → `GET /api/export/google-slides/auth/status` returns `authorized: true`. Confirm the consent URL's `state` parameter is an opaque nonce (no `user`, no `code_verifier` — check the popup URL). Then run a Google Slides export end-to-end to prove the stored token works (PKCE exchange succeeded).
2. **Replayed / forged state rejected:** capture the callback URL from step 1 (server log or browser history) and re-request it → "Authorization Failed" page, log line "unknown or already-used state nonce". Request the callback with a made-up `state=forged-nonce` → same rejection. Confirm both failure pages contain no exception text and no `'*'` postMessage target (view source).
3. **MCP header-only identity refuses resource execution:** with `TELLR_TRUST_FORWARDED_IDENTITY=true` on the instance, issue an app-to-app-style `create_deck` tool call carrying only `x-forwarded-email`/`x-forwarded-user` (no token) → tool error containing "requires a user access token". Then `get_deck_status`/`get_deck` with the same header-only identity → succeeds (or fails on *permission*, never on authentication). Finally `create_deck` with a real bearer token → works. Confirm app logs show no SP-credential Databricks calls attributed to the header-only attempt.
4. **Generic error + server-side detail:** force an error (e.g. `POST /api/export/google-slides` while not Google-authorized, or a chat send against a deck locked by another user) → the HTTP response `detail` is the fixed generic literal, while the app log (`databricks apps logs` / log stream) carries the full exception with traceback for the same request.

- [ ] **Step 4: Definition of done**

Done means: all tasks committed by the sub-supervisor on `security/sdr4437-pr4-oauth-errors`; interpolation gate green; MEDIUM-3 acceptance tests green; full pytest green; frontend lint+build green; smoke checks 1–4 pass; branch stable and **signalled to the orchestrator** with the head SHA. Include in the signal: (a) the HIGH-7 SDR process item reminder (engineer confirmation that the Apps proxy sets/strips `x-forwarded-*` still needs to accompany the code fix in the SDR response — the code closes it by defense-in-depth either way); (b) if PR-2's branch moved during this track, the rebase performed and the gate-test re-verification result.

---

## Self-review record (spec ↔ plan)

- **HIGH-7:** Task 2 — no SP binding on the priority-3 path (binds `None`, leaning on PR-2's fail-closed `get_user_client`), `require_user_token=True` on both agent-executing tools (`create_deck`, `edit_deck` — the Genie/UC/model execution paths, including the `enqueue_job` context-copy propagation, verified at `job_queue.py:47`), header-only identity kept for attribution/read tools (`get_deck_status`, `get_deck` — read-path `get_user_client()` reachability traced to zero, see Task 2's rationale), trust-model docstring kept and amended. Live smoke in Task 18.3.
- **MEDIUM-3:** Task 3 — DB-backed `oauth_states` (cross-worker rationale recorded, mirrors ExportJob), 256-bit nonce, single-use atomic `DELETE … RETURNING`, ~10-min TTL + opportunistic sweep on insert, user binding to the authenticated callback identity, `user` field dropped from state, PKCE implemented properly server-side per the spec's corrected prescription (the verifier is live in client-visible state today; it moves into the `oauth_states` row), explicit postMessage origin on both ends (callback HTML + `useGoogleOAuthPopup.ts` origin check, path verified). All six spec acceptance tests present in `test_google_oauth_state.py` (valid, double-consume, cross-user, expired, unknown, concurrent-race) plus origin/no-reflection tests. Spec's suggested filename `test_google_oauth_state.py` used.
- **MEDIUM-2:** 85 sites re-verified by AST scan matching the spec's per-file counts (slides 33, sessions 16, google_slides 9, export 7; remainder 20 across nine files — spec said "ten routers", verified nine; recorded). One task per file (Tasks 4–16), each with an exact site table; the normative Replacement Recipe forbids improvisation; the `{exc}` HTML reflection is fixed inside Task 3's callback rewrite (spec: "fix it in the same edit") and enforced by the gate's HTML check; the final gate (Task 1 test, confirmed green in Task 17 plus a literal-regex spot check) proves zero remaining **exception-variable** interpolation sites in `src/api/routes/` (request-identifier interpolation stays allowed by design; see Task 17 Step 1 for the gate's exact scope and accepted residual risk).
- **PR-2 non-interference:** boundary contract verbatim; every task's Files block avoids `_authz.py`, the coverage test, `main.py`, and gate lines; Task 17 Step 3 re-runs PR-2's coverage and fail-closed suites; google_slides same-file ownership serialized (Task 3 → Task 4).
- **Required sections:** Deploy & evaluation (Task 18, with combined PR-2+PR-4 note and the four specified smoke checks), Execution model (sub-supervisor; HIGH-7/MEDIUM-3 focused single agents; MEDIUM-2 fan-out), Rebase/conflict note (mechanical recipe re-application via the gate test) — all present above.
- **Type consistency check:** `mcp_auth_scope(request, *, require_user_token=False)` used identically in Task 2's code and tests; `_consume_oauth_state(db, nonce)` Row fields (`user_identity`, `code_verifier`, `created_at`) match between helper, callback, and tests; `_create_oauth_state(db, nonce, user_identity, code_verifier)` takes the caller-generated nonce (it cannot mint its own — `get_auth_url(state=nonce)` needs the nonce before the verifier exists) and matches its call site in `auth_url`; `get_auth_url(...) -> tuple[str, str]` matches route usage and the updated config test; `OAuthState` column set matches model, helpers, and test inserts.
