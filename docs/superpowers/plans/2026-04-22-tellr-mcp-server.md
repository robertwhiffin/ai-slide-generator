# Tellr MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose tellr as an MCP (Model Context Protocol) server at `/mcp` on the existing Databricks App so external Databricks Apps and MCP-compatible agent tools can programmatically generate and edit slide decks, using tellr's existing agent pipeline.

**Architecture:** Mount a FastMCP (Python `mcp` SDK) router at `/mcp` inside the existing FastAPI app, registered before the SPA catch-all. Four tools (`create_deck`, `get_deck_status`, `edit_deck`, `get_deck`) are thin wrappers over existing services (`ChatService`, `SessionManager`, `SlideDeck`, `permission_service`). Authentication accepts `x-forwarded-access-token` (proxy-injected) and `Authorization: Bearer` (external) in that priority order, reusing the existing `get_or_create_user_client` identity resolution. A lifespan-managed sweeper marks jobs stuck beyond 10 minutes as failed. No new infrastructure, no new queue, no new worker — MCP submissions ride the existing chat job queue.

**Tech Stack:** Python 3.10+, FastAPI, `mcp` Python SDK (FastMCP), SQLAlchemy, Pydantic v2, pytest + pytest-asyncio. Frontend is unchanged.

**Spec:** `docs/superpowers/specs/2026-04-22-tellr-mcp-server-design.md`

**Branch:** `ty/feature/tellr-mcp-server` (user will create this branch at a later stage; for now commits land on the current working branch)

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/api/mcp_server.py` | FastMCP instance + 4 tool handlers; thin wrappers over existing services |
| `src/api/mcp_auth.py` | Dual-token extraction + `ContextVar` scope helper for MCP tool handlers |
| `tests/unit/test_mcp_auth.py` | Unit tests for the auth helper |
| `tests/unit/test_mcp_server.py` | Unit tests for each tool handler (with mocked services) |
| `tests/unit/test_slide_deck_to_html_document.py` | Unit tests for the new serializer |
| `tests/unit/test_job_queue_timeout_sweeper.py` | Unit tests for `mark_timed_out_jobs_loop` |
| `tests/integration/test_mcp_endpoint.py` | End-to-end MCP protocol tests (TestClient + mocked LLM) |
| `scripts/mcp_smoke/mcp_smoke_httpx.py` | Post-deploy smoke test against a real tellr URL |
| `scripts/mcp_smoke/README.md` | How to run the smoke script |
| `docs/technical/mcp-server.md` | Caller-facing integration reference (follows `docs/technical/technical-doc-template.md`) |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | Add `mcp>=1.0.0` to `dependencies`; bump `[project]` version to `0.3.0` |
| `src/api/main.py` | Register MCP router before `_mount_frontend`; start `mark_timed_out_jobs_loop` in lifespan |
| `src/api/services/job_queue.py` | Add `JOB_HARD_TIMEOUT_SECONDS` constant + `mark_timed_out_jobs_loop` coroutine |
| `src/domain/slide_deck.py` | Add `to_html_document(chart_js_cdn: str = CHART_JS_URL) -> str` method |
| `README.md` | Add one-paragraph breadcrumb to the MCP tech doc |

### Decomposition rationale

`mcp_server.py` holds the tool surface (4 tool handlers, each ~30-60 lines). `mcp_auth.py` is a focused dependency-like helper. Tests are one file per logical surface. This keeps each file under ~400 lines, each with one clear responsibility, and each independently testable.

---

## Phase 1: Foundation

### Task 1: Add `mcp` SDK dependency and bump version

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read the current dependencies block**

Read `pyproject.toml` and confirm the `[project] dependencies = [...]` block and the current version line.

- [ ] **Step 2: Add `mcp>=1.0.0` to dependencies**

Edit the `[project] dependencies` array — add one line:

```toml
"mcp>=1.0.0",
```

Place it alphabetically relative to existing `databricks-mcp>=0.1.0` line (so `mcp` comes after `litellm` and before `mlflow` or similar — preserve the file's existing ordering pattern).

- [ ] **Step 3: Bump `dynamic = ["version"]` handling**

`pyproject.toml` currently uses `dynamic = ["version"]` with `setuptools_scm`. The runtime version comes from git tags. Do NOT add an explicit `version = "0.3.0"` line. Instead, the `0.3.0` version will be set at release time by tagging `v0.3.0`. This task only adds the dependency; the version bump happens at release.

- [ ] **Step 4: Install the new dependency**

Run:

```bash
cd "/path/to/ai-slide-generator"
uv sync
```

Expected: uv installs `mcp>=1.0.0` and its transitive deps. No errors.

- [ ] **Step 5: Verify the SDK imports**

Run:

```bash
python -c "from mcp.server.fastmcp import FastMCP; print('OK')"
```

Expected output: `OK`

If import fails, check installed version: `pip show mcp`. The required module path may differ slightly in very new SDK versions — verify with `python -c "import mcp; print(mcp.__version__)"` and adjust the import to `from mcp.server import FastMCP` if the former path doesn't exist in the installed version.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
feat(mcp): add mcp SDK dependency for MCP server implementation

Adds mcp>=1.0.0 Python SDK dependency. Version bump to 0.3.0 will
happen at release tagging time via setuptools_scm.

Co-authored-by: Isaac
EOF
)"
```

---

### Task 2: Add `SlideDeck.to_html_document()` method

**Files:**
- Modify: `src/domain/slide_deck.py`
- Create: `tests/unit/test_slide_deck_to_html_document.py`

- [ ] **Step 1: Read `src/domain/slide_deck.py` in full** to identify existing methods that produce HTML output (e.g., `knit()` or `to_html()`). If a method already produces a full standalone HTML document, evaluate whether to reuse it with a thin wrapper. If not, add a new method.

Record findings before proceeding.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_slide_deck_to_html_document.py`:

```python
"""Tests for SlideDeck.to_html_document() serializer."""

import pytest

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck


@pytest.fixture
def minimal_deck():
    return SlideDeck(
        title="Test Deck",
        css=".slide { background: white; }",
        external_scripts=["https://cdn.jsdelivr.net/npm/chart.js"],
        slides=[
            Slide(html='<div class="slide"><h1>Slide 1</h1></div>', scripts=""),
            Slide(
                html='<div class="slide"><canvas id="c1"></canvas></div>',
                scripts='new Chart(document.getElementById("c1"), {});',
            ),
        ],
    )


def test_to_html_document_is_valid_html5(minimal_deck):
    out = minimal_deck.to_html_document()
    assert out.startswith("<!doctype html>") or out.startswith("<!DOCTYPE html>")
    assert "<html" in out
    assert "<head>" in out
    assert "<body>" in out
    assert "</html>" in out


def test_to_html_document_includes_title(minimal_deck):
    out = minimal_deck.to_html_document()
    assert "<title>Test Deck</title>" in out


def test_to_html_document_includes_deck_css(minimal_deck):
    out = minimal_deck.to_html_document()
    assert ".slide { background: white; }" in out


def test_to_html_document_includes_chart_js_cdn(minimal_deck):
    out = minimal_deck.to_html_document()
    assert "chart.js" in out


def test_to_html_document_includes_all_slide_html(minimal_deck):
    out = minimal_deck.to_html_document()
    assert "<h1>Slide 1</h1>" in out
    assert '<canvas id="c1"></canvas>' in out


def test_to_html_document_includes_slide_scripts(minimal_deck):
    out = minimal_deck.to_html_document()
    assert 'new Chart(document.getElementById("c1")' in out


def test_to_html_document_overrides_chart_js_cdn(minimal_deck):
    out = minimal_deck.to_html_document(chart_js_cdn="https://internal.cdn/chart.js")
    assert "https://internal.cdn/chart.js" in out
    assert "cdn.jsdelivr.net" not in out or out.count("cdn.jsdelivr.net") == 0


def test_to_html_document_empty_deck():
    deck = SlideDeck(title="Empty")
    out = deck.to_html_document()
    assert "<!doctype html>" in out.lower()
    assert "<title>Empty</title>" in out


def test_to_html_document_is_deterministic(minimal_deck):
    a = minimal_deck.to_html_document()
    b = minimal_deck.to_html_document()
    assert a == b
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/unit/test_slide_deck_to_html_document.py -v
```

Expected: 9 failures / errors due to `to_html_document` not being defined (or producing wrong output if a similar method exists).

- [ ] **Step 4: Implement `to_html_document` in `src/domain/slide_deck.py`**

Add the method inside the `SlideDeck` class (place it near other serialization methods like `to_dict` if present, or near `knit` if that exists). If an existing method already produces similar output, implement `to_html_document` as a thin wrapper; otherwise, implement from scratch:

```python
    def to_html_document(self, chart_js_cdn: str = None) -> str:
        """Serialize the deck as a standalone renderable HTML document.

        Produces a complete <!doctype html> page with the deck's CSS, external
        scripts (with the Chart.js CDN URL overridable for air-gapped
        environments), all slide HTML in order, and per-slide scripts
        aggregated at the bottom.

        Args:
            chart_js_cdn: Override for the Chart.js CDN URL. If provided,
                replaces the default Chart.js entry in external_scripts for
                this serialization only (does NOT mutate the deck).

        Returns:
            A complete HTML document string, renderable in any modern browser.
        """
        title = self.title or "Slide Deck"

        scripts_list = list(self.external_scripts)
        if chart_js_cdn is not None:
            scripts_list = [
                chart_js_cdn if s == self.CHART_JS_URL else s
                for s in scripts_list
            ]
            if self.CHART_JS_URL not in self.external_scripts and chart_js_cdn not in scripts_list:
                scripts_list.append(chart_js_cdn)

        external_script_tags = "\n".join(
            f'  <script src="{src}"></script>' for src in scripts_list
        )

        slide_html = "\n".join(slide.html for slide in self.slides)
        aggregated_scripts = self.scripts  # IIFE-wrapped per existing property

        return (
            "<!doctype html>\n"
            "<html>\n"
            "<head>\n"
            '  <meta charset="utf-8">\n'
            f"  <title>{title}</title>\n"
            f"  <style>\n{self.css}\n  </style>\n"
            f"{external_script_tags}\n"
            "</head>\n"
            "<body>\n"
            f"{slide_html}\n"
            f"<script>\n{aggregated_scripts}\n</script>\n"
            "</body>\n"
            "</html>\n"
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_slide_deck_to_html_document.py -v
```

Expected: 9 passed.

If `test_to_html_document_overrides_chart_js_cdn` fails because the default CDN still appears (e.g., `_ensure_default_external_scripts` re-adds it), adjust the override logic so `chart_js_cdn` fully replaces the default rather than appending alongside.

- [ ] **Step 6: Commit**

```bash
git add src/domain/slide_deck.py tests/unit/test_slide_deck_to_html_document.py
git commit -m "$(cat <<'EOF'
feat(domain): add SlideDeck.to_html_document() serializer

Adds a standalone-document HTML serializer so deck content can be
returned as a self-contained renderable page to MCP callers (Stride,
Vibe, and other external agents) without requiring them to assemble
head/body/scripts themselves. Default Chart.js CDN is overridable for
air-gapped environments.

Co-authored-by: Isaac
EOF
)"
```

---

### Task 3: Add 10-minute hard-timeout sweeper to the job queue

**Files:**
- Modify: `src/api/services/job_queue.py`
- Create: `tests/unit/test_job_queue_timeout_sweeper.py`

- [ ] **Step 1: Read `src/api/services/job_queue.py` in full** to identify:
  - The existing data model for in-memory `jobs` dict and any DB-backed `chat_requests` table.
  - The signature of `recover_stuck_requests` (referenced in `main.py` lifespan).
  - The pattern used for other background loops (e.g., the `request_log_cleanup_loop` in `src/api/middleware/request_logging.py`).

Record findings.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_job_queue_timeout_sweeper.py`:

```python
"""Tests for the 10-minute hard-timeout sweeper on chat jobs."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.api.services import job_queue


@pytest.fixture(autouse=True)
def _clean_jobs():
    """Ensure an empty in-memory jobs dict between tests."""
    job_queue.jobs.clear()
    yield
    job_queue.jobs.clear()


def test_timeout_constant_is_600_seconds():
    assert job_queue.JOB_HARD_TIMEOUT_SECONDS == 600


@pytest.mark.asyncio
async def test_sweep_marks_old_running_job_as_failed():
    now = datetime.utcnow()
    job_queue.jobs["req-old"] = {
        "status": "running",
        "session_id": "s1",
        "started_at": now - timedelta(seconds=700),  # older than timeout
    }

    await job_queue.mark_timed_out_jobs_once()

    entry = job_queue.jobs["req-old"]
    assert entry["status"] == "failed"
    assert "10 minutes" in entry.get("error", "") or "600" in entry.get("error", "")


@pytest.mark.asyncio
async def test_sweep_leaves_young_running_job_alone():
    now = datetime.utcnow()
    job_queue.jobs["req-young"] = {
        "status": "running",
        "session_id": "s2",
        "started_at": now - timedelta(seconds=60),  # fresh
    }

    await job_queue.mark_timed_out_jobs_once()

    assert job_queue.jobs["req-young"]["status"] == "running"


@pytest.mark.asyncio
async def test_sweep_leaves_pending_job_alone():
    now = datetime.utcnow()
    job_queue.jobs["req-pending"] = {
        "status": "pending",
        "session_id": "s3",
        "queued_at": now - timedelta(seconds=1200),
    }

    await job_queue.mark_timed_out_jobs_once()

    assert job_queue.jobs["req-pending"]["status"] == "pending"


@pytest.mark.asyncio
async def test_sweep_idempotent_on_already_failed():
    now = datetime.utcnow()
    job_queue.jobs["req-already-failed"] = {
        "status": "failed",
        "session_id": "s4",
        "started_at": now - timedelta(hours=1),
        "error": "Existing error",
    }

    await job_queue.mark_timed_out_jobs_once()

    # status unchanged; existing error preserved
    entry = job_queue.jobs["req-already-failed"]
    assert entry["status"] == "failed"
    assert entry["error"] == "Existing error"


@pytest.mark.asyncio
async def test_sweep_handles_missing_started_at():
    """Sweeper should not crash if a running job has no started_at timestamp."""
    job_queue.jobs["req-no-ts"] = {
        "status": "running",
        "session_id": "s5",
    }

    # Should not raise; the job is left alone (we can't determine age)
    await job_queue.mark_timed_out_jobs_once()

    assert job_queue.jobs["req-no-ts"]["status"] == "running"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/unit/test_job_queue_timeout_sweeper.py -v
```

Expected: all fail (constant not defined, function not defined, etc.).

- [ ] **Step 4: Implement the sweeper**

Add to `src/api/services/job_queue.py` (at module top, near existing constants):

```python
# Maximum duration (seconds) a chat request can stay in "running" before the
# hard-timeout sweeper marks it failed. Belt-and-suspenders on top of the
# startup recover_stuck_requests() pass: the sweeper runs continuously while
# the app is up, whereas recovery only runs at process boot.
JOB_HARD_TIMEOUT_SECONDS = 600
```

Then add two functions:

```python
async def mark_timed_out_jobs_once() -> int:
    """Single sweep: mark running jobs older than JOB_HARD_TIMEOUT_SECONDS as failed.

    Examines the in-memory jobs dict. For any job whose status is "running"
    and whose started_at is older than the timeout, flips status to "failed"
    and records an explanatory error. Jobs with no started_at are left
    untouched (we cannot determine age).

    Returns:
        Number of jobs marked failed in this sweep.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=JOB_HARD_TIMEOUT_SECONDS)
    marked = 0

    for request_id, entry in list(jobs.items()):
        if entry.get("status") != "running":
            continue
        started_at = entry.get("started_at")
        if started_at is None:
            continue
        if started_at > cutoff:
            continue

        entry["status"] = "failed"
        entry["error"] = (
            f"Generation exceeded maximum duration "
            f"({JOB_HARD_TIMEOUT_SECONDS // 60} minutes)"
        )
        entry["ended_at"] = now
        marked += 1
        logger.warning(
            "Marked job as timed-out",
            extra={
                "request_id": request_id,
                "session_id": entry.get("session_id"),
                "age_seconds": (now - started_at).total_seconds(),
            },
        )

    return marked


async def mark_timed_out_jobs_loop() -> None:
    """Background loop: runs mark_timed_out_jobs_once() every 60 seconds.

    Started in the FastAPI lifespan alongside the existing workers. Survives
    its own exceptions so a single DB or logging hiccup does not take down
    the loop for the lifetime of the process.
    """
    while True:
        try:
            await asyncio.sleep(60)
            marked = await mark_timed_out_jobs_once()
            if marked:
                logger.info(
                    "Timeout sweep marked %d jobs as failed", marked
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Timeout sweep iteration failed: %s", e, exc_info=True)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_job_queue_timeout_sweeper.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/api/services/job_queue.py tests/unit/test_job_queue_timeout_sweeper.py
git commit -m "$(cat <<'EOF'
feat(job-queue): add 10-minute hard-timeout sweeper for stuck jobs

Adds JOB_HARD_TIMEOUT_SECONDS (600) constant, a single-sweep helper
mark_timed_out_jobs_once(), and a long-running mark_timed_out_jobs_loop()
coroutine started in the lifespan. Belt-and-suspenders on top of
startup recover_stuck_requests(): guarantees a predictable upper bound
on polling duration for MCP callers regardless of deploy cadence.

Co-authored-by: Isaac
EOF
)"
```

The lifespan wiring (actually starting the loop) is deferred to Task 10 (`main.py` changes), so this commit only adds the building block.

---

## Phase 2: MCP Authentication Helper

### Task 4: Create `src/api/mcp_auth.py` with dual-token extraction

**Files:**
- Create: `src/api/mcp_auth.py`
- Create: `tests/unit/test_mcp_auth.py`

- [ ] **Step 1: Read `src/api/main.py` lines 240-329** — the existing `user_auth_middleware`. Note specifically:
  - How `x-forwarded-access-token` is extracted
  - How `get_or_create_user_client(token)` is called from `src/core/databricks_client`
  - How `set_current_user`, `set_user_client`, `set_permission_context` are used
  - How the `finally` block clears context

The MCP auth helper mirrors this exactly, just with a different token source priority.

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_mcp_auth.py`:

```python
"""Tests for the dual-token MCP auth helper."""

from unittest.mock import MagicMock, patch

import pytest

from src.api.mcp_auth import (
    MCPAuthError,
    extract_mcp_identity,
    mcp_auth_scope,
)


class _FakeRequest:
    """Minimal Request stand-in with a headers dict."""

    def __init__(self, headers: dict):
        self.headers = headers


@pytest.fixture
def fake_user_client():
    client = MagicMock()
    me = MagicMock()
    me.id = "user-abc"
    me.user_name = "alice@example.com"
    client.current_user.me.return_value = me
    return client


# ---- extract_mcp_identity -------------------------------------------------


def test_extracts_from_x_forwarded_access_token_when_present(fake_user_client):
    req = _FakeRequest(headers={"x-forwarded-access-token": "tok-xfa"})
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=fake_user_client,
    ):
        identity = extract_mcp_identity(req)

    assert identity.user_id == "user-abc"
    assert identity.user_name == "alice@example.com"
    assert identity.token == "tok-xfa"
    assert identity.source == "x-forwarded-access-token"


def test_falls_back_to_authorization_bearer(fake_user_client):
    req = _FakeRequest(headers={"authorization": "Bearer tok-bearer"})
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=fake_user_client,
    ):
        identity = extract_mcp_identity(req)

    assert identity.token == "tok-bearer"
    assert identity.source == "authorization-bearer"


def test_x_forwarded_wins_over_authorization_when_both_present(fake_user_client):
    req = _FakeRequest(
        headers={
            "x-forwarded-access-token": "tok-xfa",
            "authorization": "Bearer tok-bearer",
        }
    )
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=fake_user_client,
    ):
        identity = extract_mcp_identity(req)

    assert identity.token == "tok-xfa"
    assert identity.source == "x-forwarded-access-token"


def test_raises_on_missing_credentials():
    req = _FakeRequest(headers={})
    with pytest.raises(MCPAuthError) as exc:
        extract_mcp_identity(req)
    assert "authentication" in str(exc.value).lower() or "credentials" in str(exc.value).lower()


def test_raises_on_malformed_authorization_header():
    req = _FakeRequest(headers={"authorization": "Basic abcd"})
    with pytest.raises(MCPAuthError):
        extract_mcp_identity(req)


def test_raises_when_identity_resolution_fails():
    req = _FakeRequest(headers={"authorization": "Bearer tok-bad"})
    bad_client = MagicMock()
    bad_client.current_user.me.side_effect = Exception("token invalid")
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=bad_client,
    ):
        with pytest.raises(MCPAuthError):
            extract_mcp_identity(req)


def test_bearer_extraction_trims_whitespace(fake_user_client):
    req = _FakeRequest(headers={"authorization": "Bearer    tok-spaced   "})
    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=fake_user_client,
    ):
        identity = extract_mcp_identity(req)

    assert identity.token == "tok-spaced"


# ---- mcp_auth_scope context manager --------------------------------------


def test_scope_sets_and_clears_context_vars(fake_user_client):
    req = _FakeRequest(headers={"x-forwarded-access-token": "tok"})

    with patch("src.api.mcp_auth.get_or_create_user_client", return_value=fake_user_client), \
         patch("src.api.mcp_auth.set_current_user") as set_user, \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context") as set_perm:

        with mcp_auth_scope(req) as identity:
            assert identity.user_name == "alice@example.com"

        # After exit: all three setters were called with None for teardown
        assert set_user.call_args_list[-1].args[0] is None
        assert set_client.call_args_list[-1].args[0] is None
        assert set_perm.call_args_list[-1].args[0] is None


def test_scope_clears_context_even_on_exception(fake_user_client):
    req = _FakeRequest(headers={"x-forwarded-access-token": "tok"})

    with patch("src.api.mcp_auth.get_or_create_user_client", return_value=fake_user_client), \
         patch("src.api.mcp_auth.set_current_user") as set_user, \
         patch("src.api.mcp_auth.set_user_client") as set_client, \
         patch("src.api.mcp_auth.set_permission_context") as set_perm:

        with pytest.raises(RuntimeError):
            with mcp_auth_scope(req):
                raise RuntimeError("boom")

        # Context was still cleared
        assert set_user.call_args_list[-1].args[0] is None
        assert set_client.call_args_list[-1].args[0] is None
        assert set_perm.call_args_list[-1].args[0] is None
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/unit/test_mcp_auth.py -v
```

Expected: all 9 fail with import errors (module doesn't exist yet).

- [ ] **Step 4: Implement the auth helper**

Create `src/api/mcp_auth.py`:

```python
"""Dual-token authentication for the MCP endpoint.

Accepts two token sources in priority order:

1. ``x-forwarded-access-token`` — injected by the Databricks Apps proxy.
   Highest trust; cannot be spoofed from outside the proxy.
2. ``Authorization: Bearer <token>`` — fallback for external callers
   (laptop MCP clients, agent tools) that are not behind the proxy.

The resolved identity is bound into the same request-scoped ContextVars
the browser flow uses (``set_current_user``, ``set_user_client``,
``set_permission_context``), so downstream services (session manager,
permission service, MLflow, Google OAuth) see the caller's identity
without any MCP-specific plumbing.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

from fastapi import Request

from src.core.databricks_client import (
    get_or_create_user_client,
    set_user_client,
)
from src.core.permission_context import (
    build_permission_context,
    set_permission_context,
)
from src.core.user_context import set_current_user

logger = logging.getLogger(__name__)


class MCPAuthError(Exception):
    """Raised when a request to /mcp lacks valid authentication."""


@dataclass
class MCPIdentity:
    user_id: Optional[str]
    user_name: str
    token: str
    source: str  # "x-forwarded-access-token" or "authorization-bearer"


def extract_mcp_identity(request: Request) -> MCPIdentity:
    """Resolve the caller's identity from request headers.

    Raises ``MCPAuthError`` if no valid token is found or if the token
    cannot be resolved to an identity.
    """
    # Priority 1: proxy-injected token
    token = request.headers.get("x-forwarded-access-token")
    source = "x-forwarded-access-token"

    if not token:
        # Priority 2: Authorization: Bearer fallback
        authz = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if authz.lower().startswith("bearer "):
            token = authz[len("Bearer "):].strip()
            source = "authorization-bearer"
        elif authz:
            raise MCPAuthError(
                "Unsupported Authorization scheme; expected 'Bearer <token>'"
            )

    if not token:
        raise MCPAuthError("Authentication required: no credentials presented")

    try:
        user_client = get_or_create_user_client(token)
        me = user_client.current_user.me()
    except Exception as e:
        logger.warning("MCP auth: identity resolution failed: %s", e)
        raise MCPAuthError("Invalid or expired credentials") from e

    return MCPIdentity(
        user_id=getattr(me, "id", None),
        user_name=getattr(me, "user_name", "") or "",
        token=token,
        source=source,
    )


@contextmanager
def mcp_auth_scope(request: Request) -> Iterator[MCPIdentity]:
    """Context manager that authenticates an MCP request and binds identity
    ContextVars for the duration of the block.

    On entry: resolves identity, binds ``current_user``, ``user_client``,
    and ``permission_context``.

    On exit: clears all three ContextVars, even if the wrapped block raised.
    """
    identity = extract_mcp_identity(request)

    user_client = get_or_create_user_client(identity.token)
    permission_ctx = build_permission_context(
        user_id=identity.user_id,
        user_name=identity.user_name,
        fetch_groups=False,
    )

    set_current_user(identity.user_name)
    set_user_client(user_client)
    set_permission_context(permission_ctx)

    logger.debug(
        "MCP auth scope entered",
        extra={
            "user_name": identity.user_name,
            "token_source": identity.source,
        },
    )

    try:
        yield identity
    finally:
        set_current_user(None)
        set_user_client(None)
        set_permission_context(None)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_mcp_auth.py -v
```

Expected: 9 passed.

If any test around `set_current_user` / `set_user_client` patches fails because of import paths (e.g., the `ContextVar` setter lives in a different module than my import), adjust the import path in `mcp_auth.py` to match the real setter location in the codebase. The unit tests patch `src.api.mcp_auth.set_*` so the functions must be imported *by name into `mcp_auth.py`*, not called via module attribute.

- [ ] **Step 6: Commit**

```bash
git add src/api/mcp_auth.py tests/unit/test_mcp_auth.py
git commit -m "$(cat <<'EOF'
feat(mcp): add dual-token auth helper for MCP endpoint

Introduces extract_mcp_identity() and mcp_auth_scope() context manager.
Accepts x-forwarded-access-token (proxy-injected, highest trust) with
Authorization: Bearer fallback for external callers (laptop agent
tools, Claude Code, etc). Binds the same ContextVars as the browser
flow so downstream services see identity transparently.

Co-authored-by: Isaac
EOF
)"
```

---

## Phase 3: MCP Tools

### Task 5: Create `src/api/mcp_server.py` skeleton with FastMCP instance

**Files:**
- Create: `src/api/mcp_server.py`

- [ ] **Step 1: Create the skeleton file**

Create `src/api/mcp_server.py`:

```python
"""MCP (Model Context Protocol) server for tellr.

Exposes tellr's deck-generation capabilities as a set of MCP tools so
external Databricks Apps and MCP-compatible agent tools (e.g., Claude
Code) can programmatically create, edit, and retrieve slide decks.

The tools are thin wrappers over existing services (ChatService,
SessionManager, SlideDeck, permission_service) — no re-implementation
of the agent pipeline.

See docs/superpowers/specs/2026-04-22-tellr-mcp-server-design.md for
the design rationale and docs/technical/mcp-server.md for the
caller-facing integration guide.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import Request
from mcp.server.fastmcp import FastMCP

from src.api.mcp_auth import MCPAuthError, mcp_auth_scope

logger = logging.getLogger(__name__)

# FastMCP instance — one per process. Tools are registered via decorators below.
mcp = FastMCP("tellr")


def _public_app_url() -> str:
    """Return the base URL for constructing deck_url / deck_view_url.

    Reads TELLR_APP_URL from the environment; this is set at deploy time
    by the Databricks App platform or by local dev config.
    """
    return os.getenv("TELLR_APP_URL", "").rstrip("/")


# Tool implementations are added in subsequent tasks.
```

- [ ] **Step 2: Smoke-test the module imports**

```bash
python -c "from src.api.mcp_server import mcp; print(type(mcp).__name__)"
```

Expected output: `FastMCP`

- [ ] **Step 3: Commit**

```bash
git add src/api/mcp_server.py
git commit -m "$(cat <<'EOF'
feat(mcp): add mcp_server.py skeleton with FastMCP instance

Creates the module that will host tellr's four MCP tools (create_deck,
get_deck_status, edit_deck, get_deck). Tools are added in subsequent
commits, each wrapping existing services without duplication.

Co-authored-by: Isaac
EOF
)"
```

---

### Task 6: Implement `create_deck` tool

**Files:**
- Modify: `src/api/mcp_server.py`
- Create: `tests/unit/test_mcp_server.py`

- [ ] **Step 1: Read `src/api/routes/chat.py`** for the `/api/chat/async` route implementation. Identify:
  - How a new session is created (`SessionManager.create_session` signature)
  - How the async submission works (likely `ChatService.submit_chat_async(...)` or direct `job_queue.enqueue_job(...)`)
  - The agent_config structure used for prompt-only generation

Record the exact function signatures and module paths.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_mcp_server.py`:

```python
"""Unit tests for MCP tool handlers.

Each handler is tested in isolation with mocked services. Integration
behavior (full JSON-RPC round trip, FastMCP routing) lives in
tests/integration/test_mcp_endpoint.py.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.api.mcp_auth import MCPIdentity


@pytest.fixture
def identity():
    return MCPIdentity(
        user_id="user-abc",
        user_name="alice@example.com",
        token="tok",
        source="x-forwarded-access-token",
    )


@pytest.fixture
def fake_request():
    req = MagicMock()
    req.headers = {"x-forwarded-access-token": "tok"}
    return req


# ---- create_deck --------------------------------------------------------


@pytest.mark.asyncio
async def test_create_deck_creates_session_and_submits_job(fake_request, identity):
    from src.api import mcp_server

    mock_session = {"session_id": "sess-123"}

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.get_session_manager") as get_sm, \
         patch("src.api.mcp_server.enqueue_create_job") as enqueue:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        sm = MagicMock()
        sm.create_session.return_value = mock_session
        get_sm.return_value = sm

        enqueue.return_value = "req-777"

        result = await mcp_server._create_deck_impl(
            request=fake_request,
            prompt="make a deck about Q3",
            num_slides=7,
            slide_style_id=4,
            deck_prompt_id=2,
            correlation_id="vibe-xyz",
        )

        sm.create_session.assert_called_once()
        create_kwargs = sm.create_session.call_args.kwargs
        assert create_kwargs["created_by"] == "alice@example.com"
        agent_config = create_kwargs["agent_config"]
        assert agent_config["tools"] == []
        assert agent_config["slide_style_id"] == 4
        assert agent_config["deck_prompt_id"] == 2

        enqueue.assert_called_once()
        assert enqueue.call_args.kwargs["session_id"] == "sess-123"
        assert enqueue.call_args.kwargs["prompt"] == "make a deck about Q3"
        assert enqueue.call_args.kwargs["mode"] == "generate"
        assert enqueue.call_args.kwargs["correlation_id"] == "vibe-xyz"

        assert result == {
            "session_id": "sess-123",
            "request_id": "req-777",
            "status": "pending",
        }


@pytest.mark.asyncio
async def test_create_deck_rejects_empty_prompt(fake_request, identity):
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope:
        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        with pytest.raises(MCPToolError) as exc:
            await mcp_server._create_deck_impl(
                request=fake_request,
                prompt="",
            )
        assert "prompt" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_create_deck_rejects_num_slides_out_of_range(fake_request, identity):
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope:
        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        with pytest.raises(MCPToolError):
            await mcp_server._create_deck_impl(
                request=fake_request,
                prompt="foo",
                num_slides=0,
            )
        with pytest.raises(MCPToolError):
            await mcp_server._create_deck_impl(
                request=fake_request,
                prompt="foo",
                num_slides=51,
            )


@pytest.mark.asyncio
async def test_create_deck_surfaces_auth_error_as_tool_error(fake_request):
    from src.api import mcp_server
    from src.api.mcp_auth import MCPAuthError
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope:
        auth_scope.return_value.__enter__.side_effect = MCPAuthError("no creds")

        with pytest.raises(MCPToolError) as exc:
            await mcp_server._create_deck_impl(
                request=fake_request,
                prompt="foo",
            )
        assert "auth" in str(exc.value).lower() or "credentials" in str(exc.value).lower()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/unit/test_mcp_server.py -v
```

Expected: all fail with import errors (`MCPToolError` not defined, `_create_deck_impl` not defined, etc.).

- [ ] **Step 4: Implement `create_deck`**

Add to `src/api/mcp_server.py` (below the skeleton):

```python
# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

class MCPToolError(Exception):
    """Raised when an MCP tool cannot complete its operation.

    FastMCP renders these as tool results with ``isError: true`` rather
    than as JSON-RPC protocol errors, per MCP convention.
    """


# ---------------------------------------------------------------------------
# create_deck
# ---------------------------------------------------------------------------

from src.api.services.session_manager import get_session_manager
from src.api.services.chat_service import get_chat_service


async def enqueue_create_job(
    session_id: str,
    prompt: str,
    mode: str = "generate",
    slide_context: Optional[dict] = None,
    correlation_id: Optional[str] = None,
) -> str:
    """Submit a generate or edit job using tellr's existing chat async path.

    Thin wrapper so tests can patch at one call site. Delegates to
    ChatService.submit_chat_async if present, or to the job_queue
    directly — executor should verify which signature is in use.
    """
    chat_service = get_chat_service()
    # Use the same entry point /api/chat/async uses.
    # Executor: verify the exact signature of submit_chat_async against
    # src/api/services/chat_service.py and adjust kwargs below if needed.
    request_id = await chat_service.submit_chat_async(
        session_id=session_id,
        message=prompt,
        mode=mode,
        slide_context=slide_context,
        correlation_id=correlation_id,
    )
    return request_id


@mcp.tool(
    name="create_deck",
    description=(
        "Generate a new slide deck from a natural-language prompt. Returns a "
        "session_id and a request_id; the caller polls get_deck_status for "
        "completion. The resulting deck is attributed to the calling user and "
        "appears in their tellr UI. v1 runs prompt-only: the agent does not "
        "invoke Genie, Vector Search, or other tools. Callers that want data-"
        "backed decks should gather the data themselves and include it in the "
        "prompt."
    ),
)
async def create_deck(
    request: Request,
    prompt: str,
    num_slides: Optional[int] = None,
    slide_style_id: Optional[int] = None,
    deck_prompt_id: Optional[int] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    return await _create_deck_impl(
        request=request,
        prompt=prompt,
        num_slides=num_slides,
        slide_style_id=slide_style_id,
        deck_prompt_id=deck_prompt_id,
        correlation_id=correlation_id,
    )


async def _create_deck_impl(
    request: Request,
    prompt: str,
    num_slides: Optional[int] = None,
    slide_style_id: Optional[int] = None,
    deck_prompt_id: Optional[int] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    """Implementation, separated from the decorated tool for testability."""
    if not prompt or not prompt.strip():
        raise MCPToolError("prompt must be a non-empty string")
    if num_slides is not None and not (1 <= num_slides <= 50):
        raise MCPToolError("num_slides must be between 1 and 50")

    try:
        with mcp_auth_scope(request) as identity:
            agent_config: dict[str, Any] = {"tools": []}
            if slide_style_id is not None:
                agent_config["slide_style_id"] = slide_style_id
            if deck_prompt_id is not None:
                agent_config["deck_prompt_id"] = deck_prompt_id
            if num_slides is not None:
                agent_config["num_slides"] = num_slides

            sm = get_session_manager()
            session = sm.create_session(
                created_by=identity.user_name,
                agent_config=agent_config,
            )
            session_id = session["session_id"]

            request_id = await enqueue_create_job(
                session_id=session_id,
                prompt=prompt,
                mode="generate",
                slide_context=None,
                correlation_id=correlation_id,
            )

            logger.info(
                "MCP create_deck submitted",
                extra={
                    "event": "mcp_tool_invoked",
                    "tool_name": "create_deck",
                    "session_id": session_id,
                    "request_id": request_id,
                    "user_name": identity.user_name,
                    "token_source": identity.source,
                    "correlation_id": correlation_id,
                },
            )

            return {
                "session_id": session_id,
                "request_id": request_id,
                "status": "pending",
            }
    except MCPToolError:
        raise
    except MCPAuthError as e:
        raise MCPToolError(f"Authentication failed: {e}") from e
    except Exception as e:
        logger.exception("MCP create_deck failed")
        raise MCPToolError(f"Internal error (correlation_id={correlation_id}): {e}") from e
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_mcp_server.py -v
```

Expected: 4 passed (only the create_deck tests so far).

If the test `test_create_deck_creates_session_and_submits_job` fails because `sm.create_session` expects different kwargs than `(created_by=..., agent_config=...)` (e.g., the real signature uses `user_name` instead of `created_by`, or returns a model object rather than a dict), update `_create_deck_impl` to match the real signature found in `src/api/services/session_manager.py`, and update the test accordingly.

- [ ] **Step 6: Commit**

```bash
git add src/api/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "$(cat <<'EOF'
feat(mcp): implement create_deck tool

Adds the create_deck MCP tool. Creates a new tellr session attributed
to the authenticated caller with an empty agent_config.tools list
(prompt-only generation), then submits a generate-mode async job via
tellr's existing chat queue. Returns {session_id, request_id, status:
pending}; caller polls get_deck_status for completion.

Co-authored-by: Isaac
EOF
)"
```

---

### Task 7: Implement `get_deck_status` tool

**Files:**
- Modify: `src/api/mcp_server.py`
- Modify: `tests/unit/test_mcp_server.py`

- [ ] **Step 1: Read `src/api/routes/chat.py`** for the `poll_chat` / polling implementation to identify how job status + session state are merged for the caller. Key bits to reuse:
  - How to tell "running" from "ready" from "failed"
  - How the deck_json is loaded into a SlideDeck instance on ready
  - How messages are extracted for the current turn
  - How replacement_info propagates back

- [ ] **Step 2: Write the failing tests**

Append to `tests/unit/test_mcp_server.py`:

```python
# ---- get_deck_status ----------------------------------------------------


@pytest.mark.asyncio
async def test_get_deck_status_returns_pending_shape(fake_request, identity):
    from src.api import mcp_server

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.get_job_status") as get_status, \
         patch("src.api.mcp_server.permission_service") as perm_svc:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        perm_svc.can_view_deck.return_value = True
        get_status.return_value = {"status": "pending", "session_id": "sess-1"}

        result = await mcp_server._get_deck_status_impl(
            request=fake_request,
            session_id="sess-1",
            request_id="req-1",
        )

        assert result == {
            "session_id": "sess-1",
            "request_id": "req-1",
            "status": "pending",
            "progress": None,
        }


@pytest.mark.asyncio
async def test_get_deck_status_returns_ready_with_full_deck(fake_request, identity):
    from src.api import mcp_server

    fake_session = {
        "session_id": "sess-1",
        "title": "Q3 Pitch",
        "deck_json": {
            "title": "Q3 Pitch",
            "slides": [{"html": "<div class='slide'>A</div>", "scripts": ""}],
            "css": "",
            "external_scripts": ["https://cdn.jsdelivr.net/npm/chart.js"],
            "head_meta": {},
        },
    }

    fake_turn_messages = [
        {"role": "user", "content": "make Q3 deck"},
        {"role": "assistant", "content": "I created 1 slide..."},
    ]

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.get_job_status") as get_status, \
         patch("src.api.mcp_server.permission_service") as perm_svc, \
         patch("src.api.mcp_server.get_session_manager") as get_sm, \
         patch("src.api.mcp_server._public_app_url", return_value="https://t.example"):

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        perm_svc.can_view_deck.return_value = True
        get_status.return_value = {
            "status": "ready",
            "session_id": "sess-1",
            "messages": fake_turn_messages,
            "replacement_info": None,
            "started_at": None,
            "ended_at": None,
            "mode": "generate",
            "latency_ms": 10000,
            "tool_calls": 0,
            "correlation_id": None,
        }

        sm = MagicMock()
        sm.get_session.return_value = fake_session
        get_sm.return_value = sm

        result = await mcp_server._get_deck_status_impl(
            request=fake_request,
            session_id="sess-1",
            request_id="req-1",
        )

        assert result["status"] == "ready"
        assert result["session_id"] == "sess-1"
        assert result["slide_count"] == 1
        assert result["title"] == "Q3 Pitch"
        assert "deck" in result and "slides" in result["deck"]
        assert result["html_document"].startswith(("<!doctype", "<!DOCTYPE"))
        assert result["deck_url"] == "https://t.example/sessions/sess-1/edit"
        assert result["deck_view_url"] == "https://t.example/sessions/sess-1/view"
        assert result["messages"] == fake_turn_messages
        assert result["replacement_info"] is None


@pytest.mark.asyncio
async def test_get_deck_status_returns_failed_with_error(fake_request, identity):
    from src.api import mcp_server

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.get_job_status") as get_status, \
         patch("src.api.mcp_server.permission_service") as perm_svc:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        perm_svc.can_view_deck.return_value = True
        get_status.return_value = {
            "status": "failed",
            "session_id": "sess-1",
            "error": "Generation exceeded maximum duration (10 minutes)",
        }

        result = await mcp_server._get_deck_status_impl(
            request=fake_request,
            session_id="sess-1",
            request_id="req-1",
        )

        assert result["status"] == "failed"
        assert "10 minutes" in result["error"]


@pytest.mark.asyncio
async def test_get_deck_status_denies_when_not_permitted(fake_request, identity):
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.permission_service") as perm_svc:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False

        perm_svc.can_view_deck.return_value = False

        with pytest.raises(MCPToolError) as exc:
            await mcp_server._get_deck_status_impl(
                request=fake_request,
                session_id="sess-other",
                request_id="req-1",
            )
        assert "permission" in str(exc.value).lower() or "not found" in str(exc.value).lower()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/unit/test_mcp_server.py -v
```

Expected: the four new tests fail; previous `create_deck` tests still pass.

- [ ] **Step 4: Implement `get_deck_status`**

Append to `src/api/mcp_server.py`:

```python
# ---------------------------------------------------------------------------
# get_deck_status
# ---------------------------------------------------------------------------

from src.api.services.job_queue import get_job_status
from src.services import permission_service
from src.domain.slide_deck import SlideDeck


def _render_deck_response(session: dict, base_url: str) -> dict:
    """Serialize a session's deck for inclusion in a ready response."""
    deck_json = session.get("deck_json") or {}
    deck = SlideDeck.from_dict(deck_json) if deck_json else SlideDeck(title=session.get("title"))
    session_id = session["session_id"]
    return {
        "slide_count": len(deck.slides),
        "title": session.get("title") or deck.title,
        "deck": deck.to_dict(),
        "html_document": deck.to_html_document(),
        "deck_url": f"{base_url}/sessions/{session_id}/edit" if base_url else f"/sessions/{session_id}/edit",
        "deck_view_url": f"{base_url}/sessions/{session_id}/view" if base_url else f"/sessions/{session_id}/view",
    }


@mcp.tool(
    name="get_deck_status",
    description=(
        "Poll the status of a deck generation or edit job. Returns "
        "lightweight status while pending/running; when ready, returns the "
        "complete deck as structured slide data, a standalone HTML "
        "document, and URLs into tellr's full editor and view-only surfaces."
    ),
)
async def get_deck_status(
    request: Request,
    session_id: str,
    request_id: str,
) -> dict:
    return await _get_deck_status_impl(
        request=request, session_id=session_id, request_id=request_id
    )


async def _get_deck_status_impl(
    request: Request, session_id: str, request_id: str
) -> dict:
    try:
        with mcp_auth_scope(request):
            if not permission_service.can_view_deck(session_id):
                raise MCPToolError(
                    "Deck not found or you do not have permission to view it"
                )

            status = get_job_status(request_id)
            if status is None:
                raise MCPToolError(f"Unknown request_id: {request_id}")

            job_status = status.get("status", "pending")

            if job_status in ("pending", "running"):
                return {
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": job_status,
                    "progress": status.get("progress"),
                }

            if job_status == "failed":
                return {
                    "session_id": session_id,
                    "request_id": request_id,
                    "status": "failed",
                    "error": status.get("error", "Generation failed"),
                }

            # status == "ready"
            sm = get_session_manager()
            session = sm.get_session(session_id)
            base = _public_app_url()
            deck_fields = _render_deck_response(session, base)

            return {
                "session_id": session_id,
                "request_id": request_id,
                "status": "ready",
                **deck_fields,
                "replacement_info": status.get("replacement_info"),
                "messages": status.get("messages") or [],
                "metadata": {
                    "mode": status.get("mode"),
                    "tool_calls": status.get("tool_calls"),
                    "latency_ms": status.get("latency_ms"),
                    "correlation_id": status.get("correlation_id"),
                },
            }
    except MCPToolError:
        raise
    except MCPAuthError as e:
        raise MCPToolError(f"Authentication failed: {e}") from e
    except Exception as e:
        logger.exception("MCP get_deck_status failed")
        raise MCPToolError(f"Internal error: {e}") from e
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_mcp_server.py -v
```

Expected: 8 passed (4 create_deck + 4 get_deck_status).

If `SlideDeck.from_dict` / `to_dict` are not the exact method names in `src/domain/slide_deck.py`, adjust `_render_deck_response` to use the actual serialization API. Common alternatives: `SlideDeck.from_html_string(...)` + `SlideDeck.knit()`.

- [ ] **Step 6: Commit**

```bash
git add src/api/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "$(cat <<'EOF'
feat(mcp): implement get_deck_status tool

Adds the get_deck_status MCP tool. Returns lightweight pending/running
status during generation and a full response on ready — structured
deck, standalone html_document, deck_url / deck_view_url into tellr's
UI, current-turn messages, replacement_info, and metadata. Permission-
checks via permission_service.can_view_deck.

Co-authored-by: Isaac
EOF
)"
```

---

### Task 8: Implement `edit_deck` tool

**Files:**
- Modify: `src/api/mcp_server.py`
- Modify: `tests/unit/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_mcp_server.py`:

```python
# ---- edit_deck ----------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_deck_submits_with_slide_context(fake_request, identity):
    from src.api import mcp_server

    fake_session = {
        "session_id": "sess-1",
        "deck_json": {
            "title": "x",
            "slides": [
                {"html": "<div class='slide'>0</div>", "scripts": ""},
                {"html": "<div class='slide'>1</div>", "scripts": ""},
                {"html": "<div class='slide'>2</div>", "scripts": ""},
            ],
            "css": "",
            "external_scripts": [],
            "head_meta": {},
        },
    }

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.permission_service") as perm_svc, \
         patch("src.api.mcp_server.get_session_manager") as get_sm, \
         patch("src.api.mcp_server.enqueue_create_job") as enqueue:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False
        perm_svc.can_edit_deck.return_value = True

        sm = MagicMock()
        sm.get_session.return_value = fake_session
        get_sm.return_value = sm

        enqueue.return_value = "req-edit-1"

        result = await mcp_server._edit_deck_impl(
            request=fake_request,
            session_id="sess-1",
            instruction="make slide 2 more exciting",
            slide_indices=[1],
        )

        enqueue.assert_called_once()
        kwargs = enqueue.call_args.kwargs
        assert kwargs["session_id"] == "sess-1"
        assert kwargs["prompt"] == "make slide 2 more exciting"
        assert kwargs["mode"] == "edit"
        assert kwargs["slide_context"]["indices"] == [1]
        assert kwargs["slide_context"]["slide_htmls"] == ["<div class='slide'>1</div>"]

        assert result == {
            "session_id": "sess-1",
            "request_id": "req-edit-1",
            "status": "pending",
        }


@pytest.mark.asyncio
async def test_edit_deck_submits_without_slide_context_when_indices_omitted(
    fake_request, identity
):
    from src.api import mcp_server

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.permission_service") as perm_svc, \
         patch("src.api.mcp_server.get_session_manager") as get_sm, \
         patch("src.api.mcp_server.enqueue_create_job") as enqueue:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False
        perm_svc.can_edit_deck.return_value = True

        sm = MagicMock()
        sm.get_session.return_value = {"session_id": "sess-1", "deck_json": {}}
        get_sm.return_value = sm

        enqueue.return_value = "req-edit-2"

        await mcp_server._edit_deck_impl(
            request=fake_request,
            session_id="sess-1",
            instruction="make it more exciting",
        )

        kwargs = enqueue.call_args.kwargs
        assert kwargs["mode"] == "edit"
        assert kwargs["slide_context"] is None


@pytest.mark.asyncio
async def test_edit_deck_rejects_non_contiguous_indices(fake_request, identity):
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.permission_service") as perm_svc:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False
        perm_svc.can_edit_deck.return_value = True

        with pytest.raises(MCPToolError) as exc:
            await mcp_server._edit_deck_impl(
                request=fake_request,
                session_id="sess-1",
                instruction="edit",
                slide_indices=[0, 2],  # not contiguous
            )
        assert "contiguous" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_edit_deck_denies_without_edit_permission(fake_request, identity):
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.permission_service") as perm_svc:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False
        perm_svc.can_edit_deck.return_value = False

        with pytest.raises(MCPToolError):
            await mcp_server._edit_deck_impl(
                request=fake_request,
                session_id="sess-other",
                instruction="edit",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_mcp_server.py -v
```

Expected: 4 new tests fail.

- [ ] **Step 3: Implement `edit_deck`**

Append to `src/api/mcp_server.py`:

```python
# ---------------------------------------------------------------------------
# edit_deck
# ---------------------------------------------------------------------------


def _check_contiguous(indices: list[int]) -> None:
    if not indices:
        return
    sorted_idx = sorted(indices)
    for a, b in zip(sorted_idx, sorted_idx[1:]):
        if b - a != 1:
            raise MCPToolError(
                "slide_indices must be contiguous (e.g. [2, 3, 4], not [2, 4])"
            )


@mcp.tool(
    name="edit_deck",
    description=(
        "Refine an existing deck through a natural-language instruction. "
        "Optionally target specific contiguous slides via slide_indices. "
        "The edit is applied in-place; the session_id and deck_url stay "
        "stable across edits. Returns a request_id; the caller polls "
        "get_deck_status for completion and receives the updated deck "
        "plus replacement_info summarizing what changed."
    ),
)
async def edit_deck(
    request: Request,
    session_id: str,
    instruction: str,
    slide_indices: Optional[list[int]] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    return await _edit_deck_impl(
        request=request,
        session_id=session_id,
        instruction=instruction,
        slide_indices=slide_indices,
        correlation_id=correlation_id,
    )


async def _edit_deck_impl(
    request: Request,
    session_id: str,
    instruction: str,
    slide_indices: Optional[list[int]] = None,
    correlation_id: Optional[str] = None,
) -> dict:
    if not instruction or not instruction.strip():
        raise MCPToolError("instruction must be a non-empty string")
    if slide_indices is not None:
        _check_contiguous(slide_indices)

    try:
        with mcp_auth_scope(request) as identity:
            if not permission_service.can_edit_deck(session_id):
                raise MCPToolError(
                    "Deck not found or you do not have permission to edit it"
                )

            slide_context = None
            if slide_indices:
                sm = get_session_manager()
                session = sm.get_session(session_id)
                deck_json = session.get("deck_json") or {}
                all_slides = deck_json.get("slides") or []
                try:
                    slide_htmls = [all_slides[i]["html"] for i in slide_indices]
                except IndexError as e:
                    raise MCPToolError(
                        f"slide_indices contains out-of-range index: {e}"
                    ) from e
                slide_context = {"indices": slide_indices, "slide_htmls": slide_htmls}

            request_id = await enqueue_create_job(
                session_id=session_id,
                prompt=instruction,
                mode="edit",
                slide_context=slide_context,
                correlation_id=correlation_id,
            )

            logger.info(
                "MCP edit_deck submitted",
                extra={
                    "event": "mcp_tool_invoked",
                    "tool_name": "edit_deck",
                    "session_id": session_id,
                    "request_id": request_id,
                    "user_name": identity.user_name,
                    "slide_indices": slide_indices,
                    "correlation_id": correlation_id,
                },
            )

            return {
                "session_id": session_id,
                "request_id": request_id,
                "status": "pending",
            }
    except MCPToolError:
        raise
    except MCPAuthError as e:
        raise MCPToolError(f"Authentication failed: {e}") from e
    except Exception as e:
        logger.exception("MCP edit_deck failed")
        raise MCPToolError(f"Internal error: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_mcp_server.py -v
```

Expected: 12 passed (4 create_deck + 4 get_deck_status + 4 edit_deck).

- [ ] **Step 5: Commit**

```bash
git add src/api/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "$(cat <<'EOF'
feat(mcp): implement edit_deck tool

Adds the edit_deck MCP tool. Validates CAN_EDIT via permission_service,
builds a slide_context from the caller's slide_indices (requiring
contiguous indices, matching tellr's existing SlideContext invariant),
and submits an edit-mode job through the same async pipeline as
create_deck. The edit reuses tellr's existing _parse_slide_replacements
and _apply_slide_replacements logic without change.

Co-authored-by: Isaac
EOF
)"
```

---

### Task 9: Implement `get_deck` tool

**Files:**
- Modify: `src/api/mcp_server.py`
- Modify: `tests/unit/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_mcp_server.py`:

```python
# ---- get_deck -----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_deck_returns_deck_without_job(fake_request, identity):
    from src.api import mcp_server

    fake_session = {
        "session_id": "sess-1",
        "title": "Existing Deck",
        "deck_json": {
            "title": "Existing Deck",
            "slides": [{"html": "<div class='slide'>1</div>", "scripts": ""}],
            "css": "",
            "external_scripts": ["https://cdn.jsdelivr.net/npm/chart.js"],
            "head_meta": {},
        },
    }

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.permission_service") as perm_svc, \
         patch("src.api.mcp_server.get_session_manager") as get_sm, \
         patch("src.api.mcp_server._public_app_url", return_value="https://t.example"):

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False
        perm_svc.can_view_deck.return_value = True

        sm = MagicMock()
        sm.get_session.return_value = fake_session
        get_sm.return_value = sm

        result = await mcp_server._get_deck_impl(
            request=fake_request,
            session_id="sess-1",
        )

        assert result["session_id"] == "sess-1"
        assert result["slide_count"] == 1
        assert result["title"] == "Existing Deck"
        assert "deck" in result
        assert result["html_document"].lower().startswith("<!doctype")
        assert result["deck_url"] == "https://t.example/sessions/sess-1/edit"
        assert result["deck_view_url"] == "https://t.example/sessions/sess-1/view"
        # Fields tied to a job/turn are absent
        for absent_key in ("status", "request_id", "messages", "replacement_info", "metadata"):
            assert absent_key not in result


@pytest.mark.asyncio
async def test_get_deck_denies_without_view_permission(fake_request, identity):
    from src.api import mcp_server
    from src.api.mcp_server import MCPToolError

    with patch("src.api.mcp_server.mcp_auth_scope") as auth_scope, \
         patch("src.api.mcp_server.permission_service") as perm_svc:

        auth_scope.return_value.__enter__.return_value = identity
        auth_scope.return_value.__exit__.return_value = False
        perm_svc.can_view_deck.return_value = False

        with pytest.raises(MCPToolError):
            await mcp_server._get_deck_impl(
                request=fake_request,
                session_id="sess-other",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_mcp_server.py -v
```

Expected: 2 new tests fail.

- [ ] **Step 3: Implement `get_deck`**

Append to `src/api/mcp_server.py`:

```python
# ---------------------------------------------------------------------------
# get_deck
# ---------------------------------------------------------------------------


@mcp.tool(
    name="get_deck",
    description=(
        "Retrieve the current state of a deck without submitting new work. "
        "Returns structured slide data, a standalone HTML document, and "
        "URLs into tellr's editor — same payload as a ready get_deck_status "
        "response, without status/request_id/messages. Idempotent; no job "
        "queue interaction. Use when you have a session_id from earlier and "
        "want to re-render without polling."
    ),
)
async def get_deck(request: Request, session_id: str) -> dict:
    return await _get_deck_impl(request=request, session_id=session_id)


async def _get_deck_impl(request: Request, session_id: str) -> dict:
    try:
        with mcp_auth_scope(request):
            if not permission_service.can_view_deck(session_id):
                raise MCPToolError(
                    "Deck not found or you do not have permission to view it"
                )

            sm = get_session_manager()
            session = sm.get_session(session_id)
            base = _public_app_url()
            deck_fields = _render_deck_response(session, base)

            return {
                "session_id": session_id,
                **deck_fields,
            }
    except MCPToolError:
        raise
    except MCPAuthError as e:
        raise MCPToolError(f"Authentication failed: {e}") from e
    except Exception as e:
        logger.exception("MCP get_deck failed")
        raise MCPToolError(f"Internal error: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_mcp_server.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api/mcp_server.py tests/unit/test_mcp_server.py
git commit -m "$(cat <<'EOF'
feat(mcp): implement get_deck tool

Adds the get_deck MCP tool — an idempotent read that returns a session's
current deck as structured data, standalone HTML, and tellr URLs,
without submitting any job. Used by callers re-rendering a deck they
already have a session_id for.

Co-authored-by: Isaac
EOF
)"
```

---

## Phase 4: Wire the MCP Router into FastAPI

### Task 10: Register MCP router in `main.py` and start the timeout sweeper

**Files:**
- Modify: `src/api/main.py`

- [ ] **Step 1: Read `src/api/main.py` in full** — confirm the current:
  - Router registration order (where `app.include_router(...)` calls live)
  - Lifespan function structure and where background tasks are created
  - The exact location where `_mount_frontend` is called in production

Record findings.

- [ ] **Step 2: Integrate the MCP router mount**

Locate the block near line 337–355 of `src/api/main.py` where existing `app.include_router(...)` calls happen. **Before** the `@app.get("/api/health")` definition and **before** the `_mount_frontend(app, frontend_dist)` call inside `lifespan`, add:

```python
# MCP server — mount before any catch-all SPA route so /mcp is handled.
from src.api.mcp_server import mcp as tellr_mcp  # noqa: E402
app.include_router(
    tellr_mcp.streamable_http_app().router,
    prefix="/mcp",
    tags=["mcp"],
)
logger.info("MCP server mounted at /mcp")
```

Placement intent: top-level module-load registration, alongside the other `app.include_router` calls. Do NOT place it inside the lifespan.

**Executor note:** The exact API for mounting FastMCP into FastAPI differs slightly between `mcp` SDK versions. Verify against the installed version with:

```bash
python -c "from mcp.server.fastmcp import FastMCP; m = FastMCP('t'); print(dir(m))"
```

Common patterns:
- `mcp.streamable_http_app()` returns an ASGI app you can `app.mount("/mcp", ...)` — preferred.
- If the SDK exposes `mcp.fastapi_router()`, use that with `app.include_router(..., prefix="/mcp")`.
- If neither exists in the installed version, use `mcp.http_server()` + `app.mount("/mcp", ...)`.

Pick whichever the installed version supports. Run a quick smoke request afterward (Step 4 below) to confirm mounting succeeded.

- [ ] **Step 3: Start the timeout sweeper in lifespan**

In the `lifespan` function (around line 105), after `start_export_worker` and before `recover_stuck_requests`, add:

```python
# Start the MCP job timeout sweeper
from src.api.services.job_queue import mark_timed_out_jobs_loop
_timeout_task = asyncio.create_task(mark_timed_out_jobs_loop())
logger.info("MCP job timeout sweeper started")
```

Declare `_timeout_task` in the globals section near the other worker task refs (near line 53):

```python
_timeout_task = None
```

Add shutdown handling in the cleanup section (near line 154):

```python
if _timeout_task:
    _timeout_task.cancel()
    try:
        await _timeout_task
    except asyncio.CancelledError:
        pass
    logger.info("MCP job timeout sweeper stopped")
```

- [ ] **Step 4: Smoke-test by starting the app locally**

Activate the Python environment and run:

```bash
cd "/path/to/ai-slide-generator"
ENVIRONMENT=development uvicorn src.api.main:app --port 8000 --reload &
sleep 3
curl -i -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer fake-token-for-local-dev" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0.0.0"}}}'
```

Expected: an HTTP 200 response with a JSON-RPC envelope containing capabilities and an `mcp-session-id` header. If auth fails with a test token (because current_user.me() can't resolve it), mock the identity temporarily with `DEV_USER_ID=dev@local.dev` in env and a stub user client, or ensure `get_or_create_user_client` has a dev-mode bypass in local dev. If the server returns HTML (from the SPA catch-all) instead of JSON-RPC, the router is registered too late — move its registration earlier in the file.

Kill the local server:

```bash
kill %1
```

- [ ] **Step 5: Run all unit tests to confirm no regressions**

```bash
pytest tests/unit/ -v
```

Expected: all pass (including the new MCP tests from Tasks 2, 3, 4, 6, 7, 8, 9).

- [ ] **Step 6: Commit**

```bash
git add src/api/main.py
git commit -m "$(cat <<'EOF'
feat(mcp): mount MCP router at /mcp and start timeout sweeper

Registers the FastMCP router at /mcp before the SPA catch-all so MCP
JSON-RPC POSTs reach the tool handlers. Starts mark_timed_out_jobs_loop
in the lifespan and cancels it cleanly on shutdown alongside the
existing chat and export workers.

Co-authored-by: Isaac
EOF
)"
```

---

## Phase 5: Integration Tests

### Task 11: End-to-end MCP protocol tests

**Files:**
- Create: `tests/integration/test_mcp_endpoint.py`

- [ ] **Step 1: Write the integration tests**

Create `tests/integration/test_mcp_endpoint.py`:

```python
"""End-to-end integration tests for the /mcp endpoint.

Uses FastAPI TestClient against the full app. LLM generation and
Databricks identity client are mocked; DB layer uses the in-memory
SQLite test harness configured in tests/conftest.py.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


MCP_PATH = "/mcp"


def _jsonrpc(method: str, params: dict | None = None, rid: int = 1) -> dict:
    body: dict = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _init_payload() -> dict:
    return _jsonrpc(
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "0.0.0"},
        },
    )


@pytest.fixture
def mock_identity_client():
    """Patch get_or_create_user_client to return a fake user client."""
    client = MagicMock()
    me = MagicMock()
    me.id = "user-alice"
    me.user_name = "alice@example.com"
    client.current_user.me.return_value = me

    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=client,
    ):
        yield client


@pytest.fixture
def client():
    return TestClient(app)


def test_initialize_returns_session_id(client, mock_identity_client):
    resp = client.post(
        MCP_PATH,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer fake-tok",
        },
        json=_init_payload(),
    )
    assert resp.status_code == 200
    assert resp.headers.get("mcp-session-id")
    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert "result" in body


def test_tools_list_returns_four_tools(client, mock_identity_client):
    # initialize first to get session id
    init = client.post(
        MCP_PATH,
        headers={"Authorization": "Bearer fake-tok", "Content-Type": "application/json"},
        json=_init_payload(),
    )
    session_id = init.headers["mcp-session-id"]

    resp = client.post(
        MCP_PATH,
        headers={
            "Authorization": "Bearer fake-tok",
            "Content-Type": "application/json",
            "mcp-session-id": session_id,
        },
        json=_jsonrpc("tools/list"),
    )
    body = resp.json()
    tool_names = {t["name"] for t in body["result"]["tools"]}
    assert tool_names == {"create_deck", "get_deck_status", "edit_deck", "get_deck"}


def test_create_deck_returns_pending(client, mock_identity_client):
    init = client.post(
        MCP_PATH,
        headers={"Authorization": "Bearer fake-tok", "Content-Type": "application/json"},
        json=_init_payload(),
    )
    session_id = init.headers["mcp-session-id"]

    with patch("src.api.mcp_server.get_session_manager") as get_sm, \
         patch("src.api.mcp_server.enqueue_create_job", return_value="req-int-1"):
        sm = MagicMock()
        sm.create_session.return_value = {"session_id": "sess-int-1"}
        get_sm.return_value = sm

        resp = client.post(
            MCP_PATH,
            headers={
                "Authorization": "Bearer fake-tok",
                "Content-Type": "application/json",
                "mcp-session-id": session_id,
            },
            json=_jsonrpc(
                "tools/call",
                {
                    "name": "create_deck",
                    "arguments": {"prompt": "integration test deck"},
                },
            ),
        )

    body = resp.json()
    content = body["result"]["content"]
    # FastMCP serializes tool return dicts as text content by default
    text = content[0]["text"] if isinstance(content, list) else content
    parsed = json.loads(text) if isinstance(text, str) else text
    assert parsed["session_id"] == "sess-int-1"
    assert parsed["request_id"] == "req-int-1"
    assert parsed["status"] == "pending"


def test_rejects_request_without_auth(client):
    resp = client.post(
        MCP_PATH,
        headers={"Content-Type": "application/json"},
        json=_init_payload(),
    )
    # Depending on FastMCP's error-envelope behavior, this is either an HTTP 401 or
    # a 200 with a JSON-RPC error. Both are acceptable v1 outcomes; assert one of them.
    if resp.status_code == 401:
        return
    body = resp.json()
    assert "error" in body or (
        "result" in body and body["result"].get("isError")
    )


def test_permission_denied_on_other_users_deck(client, mock_identity_client):
    init = client.post(
        MCP_PATH,
        headers={"Authorization": "Bearer fake-tok", "Content-Type": "application/json"},
        json=_init_payload(),
    )
    session_id = init.headers["mcp-session-id"]

    with patch("src.api.mcp_server.permission_service.can_view_deck", return_value=False):
        resp = client.post(
            MCP_PATH,
            headers={
                "Authorization": "Bearer fake-tok",
                "Content-Type": "application/json",
                "mcp-session-id": session_id,
            },
            json=_jsonrpc(
                "tools/call",
                {
                    "name": "get_deck",
                    "arguments": {"session_id": "someone-elses-deck"},
                },
            ),
        )

    body = resp.json()
    # Tool-level error is returned with isError: true
    result = body.get("result") or {}
    is_error = result.get("isError") is True
    content = result.get("content") or []
    text = content[0]["text"] if content else ""
    assert is_error or "permission" in text.lower()


def test_create_deck_forwards_correlation_id(client, mock_identity_client):
    init = client.post(
        MCP_PATH,
        headers={"Authorization": "Bearer fake-tok", "Content-Type": "application/json"},
        json=_init_payload(),
    )
    session_id = init.headers["mcp-session-id"]

    with patch("src.api.mcp_server.get_session_manager") as get_sm, \
         patch("src.api.mcp_server.enqueue_create_job", return_value="req-corr") as enqueue:
        sm = MagicMock()
        sm.create_session.return_value = {"session_id": "sess-corr"}
        get_sm.return_value = sm

        client.post(
            MCP_PATH,
            headers={
                "Authorization": "Bearer fake-tok",
                "Content-Type": "application/json",
                "mcp-session-id": session_id,
            },
            json=_jsonrpc(
                "tools/call",
                {
                    "name": "create_deck",
                    "arguments": {
                        "prompt": "x",
                        "correlation_id": "caller-42",
                    },
                },
            ),
        )

    kwargs = enqueue.call_args.kwargs
    assert kwargs["correlation_id"] == "caller-42"
```

- [ ] **Step 2: Run integration tests**

```bash
pytest tests/integration/test_mcp_endpoint.py -v
```

Expected: all 6 tests pass.

If any test fails because FastMCP's content serialization format differs from the expected `content[0]["text"]` JSON-of-dict pattern, adjust the test's parsing — FastMCP newer versions may return structured content blocks directly.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

```bash
pytest tests/ -v --ignore=tests/integration/test_client_integration.py
```

(Exclude the `test_client_integration.py` file if it requires a live Databricks connection — it's marked with `@pytest.mark.live` and is excluded in CI.)

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_mcp_endpoint.py
git commit -m "$(cat <<'EOF'
test(mcp): add end-to-end integration tests for the /mcp endpoint

Covers: initialize handshake, tools/list returns expected four tools,
create_deck end-to-end with mocked services, auth rejection,
permission denial on other-user decks, and correlation_id propagation.
LLM and Databricks identity client are mocked; DB uses the existing
test harness.

Co-authored-by: Isaac
EOF
)"
```

---

## Phase 6: Smoke Tests, Documentation, README Breadcrumb

### Task 12: Create post-deploy smoke test script

**Files:**
- Create: `scripts/mcp_smoke/mcp_smoke_httpx.py`
- Create: `scripts/mcp_smoke/README.md`

- [ ] **Step 1: Create the smoke script**

Create `scripts/mcp_smoke/mcp_smoke_httpx.py`:

```python
"""Post-deploy smoke test for the tellr MCP endpoint.

Runs a full create_deck -> poll -> ready flow against a deployed tellr
Databricks App using a real user token. Prints each step's outcome.

Usage:
    export TELLR_URL=https://<your-tellr-app-url>
    export DATABRICKS_TOKEN=<your-databricks-token>
    python scripts/mcp_smoke/mcp_smoke_httpx.py

Exits 0 on success, non-zero with an error message on failure.
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx


def main() -> int:
    tellr_url = os.environ.get("TELLR_URL", "").rstrip("/")
    token = os.environ.get("DATABRICKS_TOKEN", "")

    if not tellr_url:
        print("ERROR: TELLR_URL is required", file=sys.stderr)
        return 2
    if not token:
        print("ERROR: DATABRICKS_TOKEN is required", file=sys.stderr)
        return 2

    mcp_url = f"{tellr_url}/mcp"
    headers_base = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print(f"Smoke-testing {mcp_url}")

    # Step 1: initialize
    print("Step 1: initialize")
    init_body = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "tellr-smoke", "version": "0.0.1"},
        },
    }
    resp = httpx.post(mcp_url, headers=headers_base, json=init_body, timeout=30)
    resp.raise_for_status()
    session_id = resp.headers.get("mcp-session-id")
    if not session_id:
        print(f"ERROR: no mcp-session-id in response headers: {dict(resp.headers)}")
        return 1
    print(f"  mcp-session-id: {session_id}")

    mcp_headers = {**headers_base, "mcp-session-id": session_id}

    # Step 2: tools/list
    print("Step 2: tools/list")
    resp = httpx.post(
        mcp_url,
        headers=mcp_headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        timeout=30,
    )
    resp.raise_for_status()
    tool_names = [t["name"] for t in resp.json()["result"]["tools"]]
    print(f"  tools: {tool_names}")
    expected = {"create_deck", "get_deck_status", "edit_deck", "get_deck"}
    missing = expected - set(tool_names)
    if missing:
        print(f"ERROR: missing tools {missing}")
        return 1

    # Step 3: create_deck
    print("Step 3: create_deck")
    resp = httpx.post(
        mcp_url,
        headers=mcp_headers,
        json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {
                "name": "create_deck",
                "arguments": {"prompt": "a three-slide smoke-test deck about the weather"},
            },
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["result"]["content"]
    payload = json.loads(content[0]["text"]) if content else {}
    session_id_deck = payload["session_id"]
    request_id = payload["request_id"]
    print(f"  session_id={session_id_deck}, request_id={request_id}, status={payload['status']}")

    # Step 4: poll get_deck_status
    print("Step 4: poll get_deck_status (up to 10 minutes)")
    start = time.time()
    last_status = None
    while time.time() - start < 600:
        resp = httpx.post(
            mcp_url,
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {
                    "name": "get_deck_status",
                    "arguments": {"session_id": session_id_deck, "request_id": request_id},
                },
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["result"]["content"]
        payload = json.loads(content[0]["text"]) if content else {}
        status = payload.get("status")
        if status != last_status:
            print(f"  status={status}  (elapsed={int(time.time()-start)}s)")
            last_status = status

        if status == "ready":
            print(f"  slide_count={payload.get('slide_count')}")
            print(f"  deck_url={payload.get('deck_url')}")
            assert "html_document" in payload and payload["html_document"].lower().startswith("<!doctype")
            print("SUCCESS")
            return 0
        if status == "failed":
            print(f"FAILED: {payload.get('error')}")
            return 1

        time.sleep(2)

    print("TIMEOUT: generation did not complete within 10 minutes")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Create the smoke README**

Create `scripts/mcp_smoke/README.md`:

```markdown
# MCP Smoke Tests

Manual verification scripts for the tellr MCP endpoint after deploy.
These are NOT run in CI — they require a live deployed tellr app and a
real Databricks user token.

## `mcp_smoke_httpx.py`

Runs the full `initialize → tools/list → create_deck → poll → ready`
flow using raw `httpx`. Prints each step's outcome and exits 0 on
success.

### Running

```bash
export TELLR_URL=https://<your-tellr-app-url>
export DATABRICKS_TOKEN=<a-databricks-user-token>
python scripts/mcp_smoke/mcp_smoke_httpx.py
```

Expected output ends with:

```
Step 4: poll get_deck_status (up to 10 minutes)
  status=running  (elapsed=2s)
  status=ready  (elapsed=47s)
  slide_count=3
  deck_url=https://<your-tellr-app-url>/sessions/<id>/edit
SUCCESS
```

### Notes

- The script polls every 2 seconds with a 10-minute hard timeout
  that matches the server-side `JOB_HARD_TIMEOUT_SECONDS`.
- If `initialize` returns no `mcp-session-id` header, the app
  deployment did not pick up the MCP router — redeploy and check
  `/api/health` is healthy.
- If auth fails with the token, try generating a fresh PAT or using
  `databricks auth login` output.
```

- [ ] **Step 3: Run the script against local dev (optional but recommended)**

Start the local app (from Task 10), then:

```bash
export TELLR_URL=http://localhost:8000
export DATABRICKS_TOKEN=<local-dev-token-or-mock>
python scripts/mcp_smoke/mcp_smoke_httpx.py
```

If this requires real Databricks auth that local dev can't provide, skip and rely on unit+integration tests — the script's true purpose is post-deploy.

- [ ] **Step 4: Commit**

```bash
git add scripts/mcp_smoke/
git commit -m "$(cat <<'EOF'
test(mcp): add post-deploy smoke script

Adds scripts/mcp_smoke/mcp_smoke_httpx.py for manual verification
against a deployed tellr app. Runs the full create → poll → ready
flow and exits non-zero on any failure. Not part of CI.

Co-authored-by: Isaac
EOF
)"
```

---

### Task 13: Write the caller-facing technical documentation

**Files:**
- Create: `docs/technical/mcp-server.md`

- [ ] **Step 1: Read `docs/technical/technical-doc-template.md` in full** to match the project's doc-template structure exactly. Do not deviate from the template's top-level headings or ordering.

- [ ] **Step 2: Read 2-3 existing tech docs for tone/length reference**, e.g. `docs/technical/google-slides-integration.md` and `docs/technical/real-time-streaming.md`. Match the depth (schemas, code examples, troubleshooting) without copying their structure.

- [ ] **Step 3: Write the tech doc**

Create `docs/technical/mcp-server.md`. Follow the template from Step 1. Content scope:

- **Overview** — what the MCP server is, when to use it, how it relates to the tellr browser UI.
- **Prerequisites** — deployed tellr app URL, Databricks user token, MCP-compatible client (or raw HTTP).
- **Endpoint & protocol** — `https://<your-tellr-app-url>/mcp`, Streamable HTTP MCP rev 2025-03-26, JSON-RPC 2.0. Include the "how to find your tellr app URL" guidance (Databricks Apps UI or CLI: `databricks apps get <app-name> --output json`).
- **Authentication** — the dual-token model in plain prose, with three caller recipes:
  1. **In-workspace Databricks App** — pseudocode showing how the caller's backend extracts its own `x-forwarded-access-token` and forwards it as `Authorization: Bearer` on the outbound call to tellr. Include the "deliberately unsupported: using your SP token to call tellr" warning.
  2. **External MCP client (Claude Code, Claude Desktop, Cursor, etc.)** — `mcp_servers.json` snippet with `Authorization: Bearer ${DATABRICKS_TOKEN}` header.
  3. **Direct HTTP** — `httpx` example mirroring the smoke script.
- **Tool catalog** — one subsection per tool (`create_deck`, `get_deck_status`, `edit_deck`, `get_deck`):
  - Description
  - Input schema (table with field / type / required / description)
  - Output schema (JSON example)
  - Example request payload
  - Example response payload
  - Common error cases and what they mean
- **Client recipes** — full, copy-pasteable:
  - Python `httpx` — complete `create → poll → ready` script (same as `mcp_smoke_httpx.py` but standalone)
  - Claude Code / Vibe `mcp_servers.json` snippet
  - Databricks App backend pseudocode for OBO forwarding
- **Rendering recipes**:
  - Minimal: `<iframe srcdoc="{html_document}">` with an HTML-escaping note
  - Custom: iterate `deck.slides` with a short React/TypeScript example rendering each slide
  - Air-gapped: overriding the default Chart.js CDN (mention `to_html_document(chart_js_cdn=…)` isn't exposed over MCP in v1; if needed, serve the `html_document` through a CDN-rewriting proxy on the caller side)
- **Integration best practices** (section inside the same doc):
  - Polling cadence: 1–2s with backoff; do not poll faster than 500ms.
  - Error retry: respect `retry_after_seconds` on rate-limit responses.
  - Always forward the end-user's OBO token; never call with an SP token if the deck should surface to a user.
  - Use `correlation_id` on every call for cross-system trace correlation.
  - Render `html_document` for single-pane preview; iterate `deck.slides` for custom grids.
  - Hand-off-to-tellr vs. render-in-app: use `deck_url` when users need full editor features (presentation mode, Google Slides export, Monaco HTML editing, save points); render HTML locally for passive display or custom editing UIs.
- **Troubleshooting**:
  - 401 with a valid token → check proxy header forwarding
  - `status: running` forever → check server logs; verify 10-minute timeout sweeper is active
  - Deck doesn't appear in my tellr UI → check that the OBO token forwarded actually resolves to the user who's browsing tellr
  - `isError: true` with "permission" → caller identity differs from deck's `created_by`
  - Chart.js fails to load in an air-gapped environment → serve the `html_document` through a proxy that rewrites the Chart.js CDN URL
- **Versioning & changelog** — current version (match tellr's `0.3.0`), note that v1.1 will add exports / structural edit tools / tool configurability; include a link back to the spec for deferred items.
- **Links** — back to the design spec at `docs/superpowers/specs/2026-04-22-tellr-mcp-server-design.md`.

Use `<your-tellr-app-url>` as the placeholder throughout. Do NOT bake any specific workspace or deployment URL into this file.

- [ ] **Step 4: Verify the doc renders cleanly**

```bash
# Ensure no broken internal links and markdown renders OK.
# If the project has a markdown linter (e.g., markdownlint), run it:
markdownlint docs/technical/mcp-server.md || true
```

- [ ] **Step 5: Commit**

```bash
git add docs/technical/mcp-server.md
git commit -m "$(cat <<'EOF'
docs(mcp): add caller-facing technical reference for MCP endpoint

Adds the integration guide for external teams building Databricks Apps
or agent tools that want to call tellr via MCP. Covers auth setup,
tool catalog with schemas, Python and Claude Code client recipes,
rendering recipes (iframe srcdoc, custom slide grid), integration
best practices, and troubleshooting. Uses <your-tellr-app-url>
placeholder throughout.

Co-authored-by: Isaac
EOF
)"
```

---

### Task 14: Add README breadcrumb

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read current `README.md`** to find the appropriate place for the breadcrumb (likely near the "Documentation" section that already links to other `docs/technical/` pages).

- [ ] **Step 2: Add the breadcrumb**

In `README.md`'s "Technical Docs" table (around lines 123-129), add one row:

```markdown
| [MCP Server](docs/technical/mcp-server.md) | Call tellr programmatically from other Databricks Apps or MCP agent tools |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: add README breadcrumb to MCP server tech doc

Lists the new MCP integration guide in the Technical Docs table so
developers landing on the repo's README can find the caller-facing
reference without searching.

Co-authored-by: Isaac
EOF
)"
```

---

### Task 15: Final verification pass

**Files:** (no changes)

- [ ] **Step 1: Run the full unit test suite**

```bash
pytest tests/unit/ -v
```

Expected: all pass.

- [ ] **Step 2: Run the integration test suite (excluding live tests)**

```bash
pytest tests/integration/ -v -m "not live"
```

Expected: all pass.

- [ ] **Step 3: Verify git log shows all task commits cleanly**

```bash
git log --oneline -20
```

Expected: commits for tasks 1–14 all present, in order, with conventional-commit prefixes (`feat(mcp):`, `test(mcp):`, `docs(mcp):`, etc.).

- [ ] **Step 4: Deploy to dev workspace (user action)**

User step: deploy via `tellr.update(...)` from a Databricks notebook or the Apps UI. Smoke-test with `scripts/mcp_smoke/mcp_smoke_httpx.py`.

- [ ] **Step 5: Resolve the three open verification items from the spec**

From the spec's "Open Verification Items" section, run real smoke tests (or manual curl) against the dev deployment to confirm:

1. Databricks Apps proxy forwards `Authorization: Bearer` headers unmodified (or adjust auth helper if it strips them)
2. App-to-app calls: identify whose identity lands in `x-forwarded-access-token` for in-workspace app-to-app traffic
3. `current_user.me()` latency under realistic load

Record findings in a follow-up entry at the bottom of the spec, or as an issue to close before GA.

- [ ] **Step 6: Deploy to production (user action)**

User step: `tellr.update(...)` against the production workspace. Smoke-test again.

No commit for this task — it's verification only.

---

## Summary of task structure

| # | Task | Files | Test coverage |
|---|---|---|---|
| 1 | Add `mcp` SDK dependency | `pyproject.toml` | Import verification |
| 2 | `SlideDeck.to_html_document()` | `slide_deck.py` + unit tests | 9 tests |
| 3 | 10-min timeout sweeper | `job_queue.py` + unit tests | 6 tests |
| 4 | Dual-token auth helper | `mcp_auth.py` + unit tests | 9 tests |
| 5 | `mcp_server.py` skeleton | `mcp_server.py` | Import smoke |
| 6 | `create_deck` tool | `mcp_server.py` + unit tests | 4 tests |
| 7 | `get_deck_status` tool | `mcp_server.py` + unit tests | 4 tests |
| 8 | `edit_deck` tool | `mcp_server.py` + unit tests | 4 tests |
| 9 | `get_deck` tool | `mcp_server.py` + unit tests | 2 tests |
| 10 | Wire MCP into `main.py` | `main.py` | Local smoke test |
| 11 | Integration tests | `tests/integration/test_mcp_endpoint.py` | 6 tests |
| 12 | Post-deploy smoke script | `scripts/mcp_smoke/` | Manual verification |
| 13 | Technical documentation | `docs/technical/mcp-server.md` | N/A |
| 14 | README breadcrumb | `README.md` | N/A |
| 15 | Final verification | — | All tests + deploy smoke |

Total: ~44 new unit tests, 6 integration tests, 1 smoke script, 1 technical doc, 1 README update, ~4 existing files modified, ~6 new files created.

Each task ships independently via its own commit. Tasks 1–9 can be executed in order without any deploy. Task 10 enables local testing. Tasks 11–15 harden and document.
