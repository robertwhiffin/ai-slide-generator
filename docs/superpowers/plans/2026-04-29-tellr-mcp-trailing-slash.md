# Tellr MCP — accept `/mcp` and `/mcp/` interchangeably — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the `POST /mcp` (no trailing slash) failure mode by adding an ASGI middleware that rewrites the request scope's path to `/mcp/` before route resolution, so MCP clients that omit the slash succeed in a single round-trip instead of receiving 405 (production, with SPA catch-all) or 307 (tests, without SPA catch-all).

**Architecture:** One small `@app.middleware("http")` in `src/api/main.py`, registered immediately after the `FastAPI(...)` constructor. The middleware checks for an exact-equality match on `/mcp` with a non-`GET` method and rewrites `scope["path"]` and `scope["raw_path"]` to `/mcp/` before delegating to `call_next`. Then one new integration test asserts both URL forms produce identical 200 JSON-RPC responses, plus stale-comment cleanup and client-facing doc updates.

**Tech Stack:** FastAPI / Starlette ASGI middleware, FastMCP (`mcp.server.fastmcp`), pytest with FastAPI `TestClient`, Python 3.11.

**Spec:** `docs/superpowers/specs/2026-04-29-tellr-mcp-trailing-slash-design.md`

---

## File Map

| File | Change | Why |
|---|---|---|
| `src/api/main.py` | Modify (add middleware after `app = FastAPI(...)` block ~line 219) | Adds the ASGI path rewrite. |
| `tests/integration/test_mcp_endpoint.py` | Modify (add new test, fix stale module docstring & comment near `MCP_PATH`) | New regression guard; corrects two stale comments that asserted 307 behavior. |
| `docs/technical/mcp-server.md` | Modify (sections 1, 6, "Common gotchas", troubleshooting table) | Update protocol-level reference: both forms are accepted, no canonical-slash rule. |
| `docs/technical/mcp-integration-guide.md` | Modify ("Trailing slash on the URL" gotcha) | Update integrator-facing how-to: the slash is no longer required. |
| `scripts/mcp_smoke/mcp_smoke_httpx.py` | Modify (one comment near `MCP_PATH_SUFFIX`) | One-line note that the slash is optional post-fix; URL value unchanged. |
| `scripts/mcp_smoke/README.md` | Modify ("Notes" bullet about the trailing slash) | Same. |
| `mcp-test-client/app.py` | Modify (one comment near `mcp_url = f"{tellr_base_url}/mcp/"`) | Same. |

Each task below produces a self-contained commit. Order matters: Task 1 lands the failing test, Task 2 lands the middleware (turning the test green), then Tasks 3–5 are pure documentation/comment cleanup that depend on Tasks 1–2 having merged.

---

## Task 1: Add the failing regression test

**Files:**
- Modify: `tests/integration/test_mcp_endpoint.py` (add new test function at end of file)

- [ ] **Step 1: Open `tests/integration/test_mcp_endpoint.py` and append the new test at the bottom of the file.**

Add this function after the last existing test in the file (file currently ends at the last `def test_*` definition; place the new test below it, with two blank lines between definitions to match the existing PEP-8 spacing):

```python
def test_mcp_endpoint_accepts_both_slash_forms(client, mock_identity_client):
    """Regression guard: POST /mcp and POST /mcp/ behave identically.

    The SPA catch-all (``@app.get("/{full_path:path}")`` added by
    ``_mount_frontend`` in production) used to make ``POST /mcp`` return
    405 with ``allow: GET``, since Starlette's ``Mount`` cannot tell the
    outer router which methods FastMCP accepts. In tests
    ``IS_PRODUCTION`` is false so ``_mount_frontend`` doesn't run and
    Mount itself returns a 307 redirect for the bare path. The
    ``normalize_mcp_path`` middleware in ``main.py`` rewrites
    ``/mcp -> /mcp/`` in the ASGI scope so both forms reach the FastMCP
    sub-app's POST handler in a single round-trip.

    ``follow_redirects=False`` is critical: without it, ``TestClient``
    would silently follow a 307 from ``/mcp`` to ``/mcp/`` and the test
    would pass even if the middleware regressed.
    """
    # Run the standard MCP handshake against the canonical slashed path
    # first so any FastMCP-internal state (none today, since stateless)
    # mirrors what the existing tests do.
    _initialize_session(client)

    body = _jsonrpc("tools/list", rid=2)

    no_slash = client.post(
        "/mcp",
        headers=_mcp_headers(),
        json=body,
        follow_redirects=False,
    )
    with_slash = client.post(
        "/mcp/",
        headers=_mcp_headers(),
        json=body,
        follow_redirects=False,
    )

    assert no_slash.status_code == 200, (
        f"POST /mcp should return 200 after the middleware rewrite, "
        f"got {no_slash.status_code}: {no_slash.text!r}"
    )
    assert with_slash.status_code == 200, with_slash.text

    no_slash_body = _decode_mcp_response(no_slash)
    with_slash_body = _decode_mcp_response(with_slash)

    no_slash_tools = {
        t["name"] for t in no_slash_body["result"]["tools"]
    }
    with_slash_tools = {
        t["name"] for t in with_slash_body["result"]["tools"]
    }
    assert no_slash_tools == with_slash_tools, (
        f"tool sets differ between paths: "
        f"no_slash={no_slash_tools} with_slash={with_slash_tools}"
    )
    assert {
        "create_deck", "get_deck_status", "edit_deck", "get_deck",
    } <= no_slash_tools, f"unexpected tool set: {no_slash_tools}"
```

- [ ] **Step 2: Run the test to confirm it fails for the right reason**

Run: `pytest tests/integration/test_mcp_endpoint.py::test_mcp_endpoint_accepts_both_slash_forms -v`

Expected: **FAIL** with an assertion error like `POST /mcp should return 200 after the middleware rewrite, got 307: ''` (the test environment hits Mount's built-in slash redirect because `_mount_frontend` doesn't run there). If the failure is anything else — module import error, fixture not found, redirect actually followed — investigate before continuing; the test must fail at the `no_slash.status_code == 200` assertion specifically, otherwise the middleware in Task 2 won't be exercising the right path.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/integration/test_mcp_endpoint.py
git commit -m "$(cat <<'EOF'
test(mcp): assert /mcp and /mcp/ behave identically

Adds a failing regression guard for the trailing-slash equivalence the
next commit introduces. follow_redirects=False ensures TestClient
surfaces any 307/405 instead of silently following.

Co-authored-by: Isaac
EOF
)"
```

Verify: `git log -1 --stat` shows exactly one file changed (`tests/integration/test_mcp_endpoint.py`).

---

## Task 2: Add the path-rewrite middleware

**Files:**
- Modify: `src/api/main.py` (insert middleware between the `FastAPI(...)` constructor and the `_resolve_frontend_dist` helper)

- [ ] **Step 1: Insert the middleware**

Open `src/api/main.py`. Locate this block (around line 213-220):

```python
# Initialize FastAPI app
app = FastAPI(
    title="AI Slide Generator API",
    description="Generate presentation slides from natural language using AI",
    version="0.3.0 (Phase 3 - Databricks Apps)",
    lifespan=lifespan,
)
```

Insert the following **immediately after the closing `)` of the `FastAPI(...)` call**, before `def _resolve_frontend_dist():`. Leave one blank line before and after the new middleware:

```python


@app.middleware("http")
async def normalize_mcp_path(request: Request, call_next):
    """Make POST /mcp behave like POST /mcp/.

    The SPA catch-all (``@app.get("/{full_path:path}")`` added by
    ``_mount_frontend``) intercepts non-GET requests to ``/mcp`` and
    causes Starlette to return 405 instead of routing to the FastMCP
    Mount. Rewriting the ASGI scope path before route resolution
    sidesteps that interaction and avoids emitting a 307 the client
    has to follow (which can drop ``Authorization`` or method-downgrade
    in misbehaving HTTP clients — Claude Code v2.1.123 via stdio→HTTP
    proxy was the original report).

    GET is left alone so ``/mcp`` continues to render the SPA in a
    browser. The match is exact so ``/mcp/``, ``/mcp/anything``, and
    ``/mcp-something`` are all unaffected; query strings live in
    ``scope["query_string"]`` and are not touched.
    """
    if request.url.path == "/mcp" and request.method != "GET":
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"
    return await call_next(request)
```

`Request` is already imported at the top of the file (`from fastapi import FastAPI, HTTPException, Request`), so no new imports are needed. Verify by grepping:

```bash
grep -n "^from fastapi" src/api/main.py
```

Expected: a line containing `Request` in the `from fastapi import ...` list.

- [ ] **Step 2: Run the regression test to confirm it now passes**

Run: `pytest tests/integration/test_mcp_endpoint.py::test_mcp_endpoint_accepts_both_slash_forms -v`

Expected: **PASS**.

- [ ] **Step 3: Run the full MCP integration suite to confirm nothing else broke**

Run: `pytest tests/integration/test_mcp_endpoint.py -v`

Expected: all tests **PASS**. The existing tests use `MCP_PATH = "/mcp/"` (slashed form) which the middleware does not touch, so they should be unaffected.

- [ ] **Step 4: Commit the middleware**

```bash
git add src/api/main.py
git commit -m "$(cat <<'EOF'
fix(mcp): accept POST /mcp without trailing slash

Adds an ASGI path-rewrite middleware so /mcp and /mcp/ are accepted
interchangeably. Resolves the production 405 reported by Claude Code
v2.1.123 callers whose HTTP layer doesn't follow / can't follow the
implicit slash redirect. See
docs/superpowers/specs/2026-04-29-tellr-mcp-trailing-slash-design.md.

Co-authored-by: Isaac
EOF
)"
```

Verify: `git log -1 --stat` shows exactly one file changed (`src/api/main.py`).

---

## Task 3: Fix stale comments in the integration test file

**Files:**
- Modify: `tests/integration/test_mcp_endpoint.py` (module docstring lines 22-25; the `MCP_PATH` comment lines 40-44)

These two comments still claim "POST /mcp returns a 307 redirect" — true historically, true in tests today, but no longer the user-facing behavior thanks to the middleware. Replace them so a future reader doesn't get confused.

- [ ] **Step 1: Update the module docstring**

In `tests/integration/test_mcp_endpoint.py`, replace lines 22-25 (the second numbered gotcha):

Old:
```python
2. ``POST /mcp`` returns a 307 redirect to ``/mcp/``. Hitting the
   trailing-slash path directly avoids TestClient's redirect handling
   (which may or may not follow redirects automatically depending on
   the httpx version).
```

New:
```python
2. The ``normalize_mcp_path`` middleware in ``src/api/main.py`` rewrites
   ``POST /mcp`` to ``POST /mcp/`` in the ASGI scope so both forms reach
   the FastMCP sub-app. The test fixture here doesn't run
   ``_mount_frontend`` (production-only), so without the middleware
   ``POST /mcp`` would 307; with the middleware it returns 200 directly.
   Existing tests still use ``MCP_PATH = "/mcp/"`` for stability —
   ``test_mcp_endpoint_accepts_both_slash_forms`` is the dedicated
   regression guard for the no-slash case.
```

- [ ] **Step 2: Update the `MCP_PATH` constant comment**

In the same file, replace lines 40-44:

Old:
```python
# Trailing slash: the FastMCP streamable-HTTP transport internally
# mounts its route at "/", and main.py mounts that sub-app at "/mcp".
# External POST to "/mcp" returns a 307 to "/mcp/"; going straight to
# the slashed form bypasses that round trip.
MCP_PATH = "/mcp/"
```

New:
```python
# FastMCP's streamable-HTTP transport mounts its route at "/", and
# main.py mounts that sub-app at "/mcp". External clients can POST to
# either ``/mcp`` or ``/mcp/`` thanks to the ``normalize_mcp_path``
# middleware. Existing tests pin to the slashed form for stability;
# ``test_mcp_endpoint_accepts_both_slash_forms`` covers the no-slash
# case explicitly.
MCP_PATH = "/mcp/"
```

- [ ] **Step 3: Run the test suite to confirm nothing regressed**

Run: `pytest tests/integration/test_mcp_endpoint.py -v`

Expected: all tests **PASS** (this task changes only comments, no behavior).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_mcp_endpoint.py
git commit -m "$(cat <<'EOF'
docs(test): refresh stale 307 comments after slash-rewrite middleware

Co-authored-by: Isaac
EOF
)"
```

---

## Task 4: Update client-facing technical docs

**Files:**
- Modify: `docs/technical/mcp-server.md` (lines 41, 47, 525, 543, plus URL examples on lines 69, 102, 112, 126, 351, 370, 437)
- Modify: `docs/technical/mcp-integration-guide.md` (line 404 gotcha; URL examples on lines 123, 250, 261, 296, 308, 352, 356, 365, 386, 402, 428)

Both forms are now accepted. We pick **`/mcp` (no slash)** as the documented canonical URL going forward — it's the form most CLIs default to when copying URLs around. Existing client code using `/mcp/` keeps working; we are not breaking anyone, just retiring the "mandatory slash" claim.

- [ ] **Step 1: Update `docs/technical/mcp-server.md`**

In the URL row of the table around line 41:

Old:
```
| URL | `https://<your-tellr-app-url>/mcp/` |
```

New:
```
| URL | `https://<your-tellr-app-url>/mcp` (or `/mcp/` — both accepted) |
```

Replace the "Mandatory trailing slash" callout around line 47:

Old:
```
**Mandatory trailing slash.** `POST /mcp` returns `307 Temporary Redirect` to `/mcp/`. Always POST to `/mcp/` directly — the redirect will strip `POST` semantics with some clients.
```

New:
```
**Both `/mcp` and `/mcp/` are accepted.** A path-rewrite middleware in `src/api/main.py` makes the two forms behave identically — single round-trip, no redirect. Documented examples below use the no-slash form; existing clients hard-coded to `/mcp/` continue to work unchanged.
```

In the "Common gotchas" table around line 525:

Old row:
```
| Trailing slash | Always POST to `/mcp/`. `POST /mcp` returns `307 Temporary Redirect`, which some HTTP clients silently downgrade to `GET`. |
```

New row:
```
| Trailing slash | Either `/mcp` or `/mcp/` works. A middleware rewrites the bare path before routing. |
```

In the troubleshooting table around line 543:

Old row:
```
| Client receives HTML instead of JSON on the first POST | Target URL is `/mcp` (no trailing slash) and the client followed the 307 to a GET | Always POST to `/mcp/` directly |
```

New row:
```
| Client receives HTML instead of JSON on the first POST | Either the SPA catch-all is intercepting (deployed app missing the path-rewrite middleware) or the URL points at the wrong host. | Verify `MCP server mounted at /mcp` appears in the app logs, and curl `POST /mcp` directly with `Accept: application/json, text/event-stream` to confirm a JSON-RPC envelope returns. |
```

For the URL examples in this file (lines 69, 102, 112, 126, 351, 370, 437), drop the trailing slash to match the new canonical form:

```bash
# In docs/technical/mcp-server.md only:
sed -i '' 's|<your-tellr-app-url>/mcp/|<your-tellr-app-url>/mcp|g' docs/technical/mcp-server.md
sed -i '' 's|TELLR_URL}/mcp/|TELLR_URL}/mcp|g' docs/technical/mcp-server.md
```

After running, quickly read the diff (`git diff docs/technical/mcp-server.md`) and confirm only URL strings changed — no prose accidentally touched.

- [ ] **Step 2: Update `docs/technical/mcp-integration-guide.md`**

Replace the "Trailing slash on the URL" callout around line 404:

Old:
```
**Trailing slash on the URL.** Always POST to `/mcp/` (with slash). `/mcp` (no slash) returns a 307 redirect that some clients silently downgrade to GET and break on. The `claude mcp add` command sometimes strips the trailing slash — double-check with `claude mcp list`.
```

New:
```
**Trailing slash on the URL.** Both `/mcp` and `/mcp/` work; a path-rewrite middleware in tellr accepts either. The `claude mcp add` command sometimes strips the slash — that's now harmless. (Historical note: deployments before April 2026 returned 405 for `/mcp` with no slash; if you're integrating against a pinned-old build, append the slash.)
```

For the URL examples in this file (lines 123, 250, 261, 296, 308, 352, 356, 365, 386, 402, 428), drop the trailing slash:

```bash
# In docs/technical/mcp-integration-guide.md only:
sed -i '' 's|tellr-app-url>/mcp/|tellr-app-url>/mcp|g' docs/technical/mcp-integration-guide.md
sed -i '' 's|tellr_base}/mcp/|tellr_base}/mcp|g' docs/technical/mcp-integration-guide.md
sed -i '' "s|app's \`/mcp/\` endpoint|app's \`/mcp\` endpoint|g" docs/technical/mcp-integration-guide.md
sed -i '' "s|external \`/mcp/\` calls|external \`/mcp\` calls|g" docs/technical/mcp-integration-guide.md
sed -i '' "s|\`/mcp/\` still returns 403|\`/mcp\` still returns 403|g" docs/technical/mcp-integration-guide.md
```

Read the diff (`git diff docs/technical/mcp-integration-guide.md`) and verify only URL/path strings changed.

- [ ] **Step 3: Commit**

```bash
git add docs/technical/mcp-server.md docs/technical/mcp-integration-guide.md
git commit -m "$(cat <<'EOF'
docs(mcp): document /mcp and /mcp/ both being accepted

Refreshes the protocol reference and integration guide for the
path-rewrite middleware. Picks /mcp (no slash) as the canonical
documented form going forward; existing /mcp/ examples in client
code remain valid.

Co-authored-by: Isaac
EOF
)"
```

---

## Task 5: Refresh smoke-script and test-client comments

**Files:**
- Modify: `scripts/mcp_smoke/mcp_smoke_httpx.py` (lines 25-27 comment)
- Modify: `scripts/mcp_smoke/README.md` (the trailing-slash bullet under "Notes")
- Modify: `mcp-test-client/app.py` (line 140 comment / nearby docstring)

These three files keep using `/mcp/` for now. We don't change the URLs — just the comments — so the smoke script continues exercising the historically-broken path until we have post-deploy confidence in the middleware.

- [ ] **Step 1: `scripts/mcp_smoke/mcp_smoke_httpx.py`**

Replace lines 25-27:

Old:
```python
# The MCP endpoint path has a mandatory trailing slash; POST /mcp
# returns 307 -> /mcp/.
MCP_PATH_SUFFIX = "/mcp/"
```

New:
```python
# As of 2026-04-29 the tellr server accepts both ``/mcp`` and ``/mcp/``
# (path-rewrite middleware in ``src/api/main.py``). We keep the slashed
# form here so the smoke test continues to exercise the historical path
# real users have hard-coded.
MCP_PATH_SUFFIX = "/mcp/"
```

- [ ] **Step 2: `scripts/mcp_smoke/README.md`**

Replace the existing "trailing slash" bullet under "Notes":

Old:
```
- The MCP endpoint path has a mandatory trailing slash. The script
  uses `/mcp/` directly to avoid the 307 redirect that `POST /mcp`
  returns.
```

New:
```
- The tellr server accepts both `/mcp` and `/mcp/`. The script uses
  `/mcp/` so it continues to cover the historical client path; either
  form works against current deployments.
```

- [ ] **Step 3: `mcp-test-client/app.py`**

The relevant code is around line 140:

```python
mcp_url = f"{tellr_base_url}/mcp/"
```

Add a one-line comment immediately above that assignment:

```python
    # tellr accepts both ``/mcp`` and ``/mcp/``; we keep the slashed
    # form here to match the test-client's pre-2026-04-29 baseline.
    mcp_url = f"{tellr_base_url}/mcp/"
```

(Note: `mcp-test-client/app.py` lives in the sibling directory `mcp-test-client/`, not under `ai-slide-generator/`. Edit it from its own working directory: `/Users/robert.whiffin/Documents/slide-gen-branch-eval/mcp-test-client/app.py`. If that file has its own git repo, commit it there with its own commit message; if it shares the tellr repo, fold it into the same commit below.)

- [ ] **Step 4: Commit**

If `mcp-test-client/app.py` is part of the tellr repo, run:

```bash
git add scripts/mcp_smoke/mcp_smoke_httpx.py scripts/mcp_smoke/README.md ../mcp-test-client/app.py
git commit -m "$(cat <<'EOF'
docs(mcp): note both slash forms work in smoke + test-client

Comment-only update; URLs unchanged so historical paths still get
exercised by the smoke flow.

Co-authored-by: Isaac
EOF
)"
```

If `mcp-test-client/` is a separate repo, run two commits — one in each repo — with the same message body.

Verify: `git log --oneline -5` shows the five commits from Tasks 1–5 in order.

---

## Self-review

The plan covers every spec section:

- **Component 1 (middleware)** — Task 2.
- **Component 2 (regression test)** — Task 1 (failing) + Task 2 (passing) + Task 3 (stale comments).
- **Component 3 (documentation updates)** — Task 4 (`mcp-server.md`, `mcp-integration-guide.md`) + Task 5 (smoke + test-client comments).
- **Verification plan** — Steps 2–3 of Task 2 cover the pre-merge `pytest` run; the spec's post-deploy manual check is operational and lives in the spec itself, not in this implementation plan.

No placeholders. Method/property names match across tasks (`normalize_mcp_path` everywhere, `MCP_PATH` left as `/mcp/`, no name drift between test fixtures and code under test). Each task is independently committable. Every code change shows the actual code; every command shows the expected output.
