# Usage Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Load `executing-plans-tellr` alongside it (CLAUDE.md). Steps use checkbox (`- [ ]`) syntax for tracking.

Execution: single-session

**Goal:** Every request Tellr makes carries a Tellr product name, the real version and (on Gateway calls) the feature it was for, and an autoscaling install's Lakebase is attached to its app.

**Architecture:** A new leaf module, `src/core/attribution.py`, owns the version lookup, the product names and the per-token product label. Every SDK client construction asks it for `product=` / `product_version=`; the MCP HTTP client asks it for a User-Agent; `gateway_clients.py` adds two allow-listed keys to its existing request tag. The installer gains one step, `_ensure_app_postgres_resource`, run after the service principal's role exists.

**Tech Stack:** Python 3.11, databricks-sdk 0.157.0 (`WorkspaceClient`, `Config`, `AppResourcePostgres`), databricks-langchain / databricks-openai (Gateway clients), httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-consumption-attribution-design.md`

## Global Constraints

- **Identifiers only.** A label is a product name, a version or a value from a fixed allow-list. Never a prompt, deck content, user text or a customer name.
- Product names are unchanged: `tellr-app-system`, `tellr-app-<12-hex hash>`, `tellr-app-unknown`. The Gateway tag keeps `"source": "tellr"`.
- No new network call, no new permission, no change to which identity makes a call, no change to any request body.
- Nothing in this plan may raise into a request or a deploy: lookups fall back (`"unknown"`, `tellr-app-unknown`, no tag key), the installer step warns and continues.
- Tag allow-lists, exactly: component ∈ {`generation`, `title`, `export`, `image`}; entrypoint ∈ {`app`, `mcp`}.
- MCP HTTP User-Agent, exactly: `tellr/<version> python-httpx/<httpx.__version__>`. No request-tags header on MCP calls.
- The app resource is named `app_database` (the name provisioned installs already use) and is attached only **after** `_ensure_sp_autoscaling_role` has run. Never pass it to `apps.create`.
- Python env is the per-worktree uv `.venv` (`uv sync --extra dev`); run everything with `uv run`. No new dependencies.
- Baseline before Task 1: `uv run pytest tests/unit/test_gateway_clients.py tests/unit/test_client.py tests/unit/test_genie_agent_client.py tests/unit/test_genie_one_client.py tests/unit/test_model_endpoint_catalog.py tests/unit/test_deploy_app_scopes.py tests/unit/test_deploy_autoscaling.py tests/unit/test_session_naming.py tests/unit/test_agent_runtime.py -q`. Record the result; compare later failures by cause, not count.
- Commits end with `Co-authored-by: Isaac <no-reply@databricks.com>`.
- `origin/feat/mcp-agent-mode` is in flight and rewrites parts of `src/api/mcp_server.py`. Task 4 touches that file in one line only; rebase onto `origin/main` before the PR and re-run Task 4's tests if it has merged.

## Review Focus

1. **A client built in a worker thread loses the user label.** `run_with_timeout` and the Legacy MCP tool use a bare `ThreadPoolExecutor`, which does not copy ContextVars. Expect the per-user label there, not `tellr-app-unknown`. Pinned in Task 2 (`test_label_is_found_from_a_thread_with_no_request_context`).
2. **Two User-Agent headers on an MCP request** (the library default plus ours). Expect exactly one. Pinned in Task 2 (`test_mcp_http_client_sends_one_tellr_user_agent_and_no_tag_header`).
3. **A tag value that is not on the allow-list** (a typo at a call site, or a value from a payload). Expect the key to be omitted and `source` kept. Pinned in Tasks 3 and 4.
4. **An install that already has a database resource** (every provisioned install, and any app updated twice). Expect no second resource and no update call. Pinned in Task 5.
5. **The platform refusing the attach** (a workspace without the feature, a caller who may not update the app). Expect one warning line and the deploy to continue. Pinned in Task 5.

---

### Task 1: `src/core/attribution.py` and the real version

**Models:** `test=opus impl=opus`

**Files:**
- Create: `src/core/attribution.py`
- Modify: `src/core/databricks_client.py:46-99` (constants, `_get_package_version`, `_hash_username`)
- Modify: `src/services/gateway_clients.py:25-48` (`_tellr_version`)
- Test: `tests/unit/test_attribution.py` (create), `tests/unit/test_gateway_clients.py:34-70` (update)

**Interfaces:**
- Produces, in `src/core/attribution.py`:
  - `APP_PACKAGE: Final[str] = "databricks-tellr-app"`
  - `PRODUCT_NAME_SYSTEM: Final[str] = "tellr-app-system"`, `PRODUCT_NAME_USER_PREFIX: Final[str] = "tellr-app-"`, `PRODUCT_NAME_UNKNOWN: Final[str] = "tellr-app-unknown"`
  - `package_version() -> str` (cached; `package_version.cache_clear()` exists)
  - `hash_username(username: str) -> str`
  - `system_product_kwargs() -> dict[str, str]` → `{"product": "tellr-app-system", "product_version": <version>}`
- Keeps, in `src/core/databricks_client.py`: the names `PRODUCT_NAME_SYSTEM`, `PRODUCT_NAME_USER_PREFIX`, `_get_package_version()`, `_hash_username()` (tests patch `src.core.databricks_client._get_package_version`).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_attribution.py`:

```python
"""The labels Tellr puts on its own requests: product, version, never content."""

from importlib import metadata

import pytest

from src.core import attribution


@pytest.fixture(autouse=True)
def _fresh_version_cache():
    attribution.package_version.cache_clear()
    yield
    attribution.package_version.cache_clear()


def _installed(version):
    def _version(name):
        if name == "databricks-tellr-app":
            return version
        raise metadata.PackageNotFoundError(name)

    return _version


def _not_installed(name):
    raise metadata.PackageNotFoundError(name)


def test_version_is_the_installed_wheels(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    assert attribution.package_version() == "9.9.9"


def test_version_falls_back_to_the_source_tree_outside_a_wheel(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _not_installed)
    from src import __version__

    try:
        from src._version import version as expected
    except ImportError:
        expected = __version__
    assert attribution.package_version() == expected


def test_version_lookup_never_raises(monkeypatch):
    def _boom(name):
        raise RuntimeError("broken metadata")

    monkeypatch.setattr(attribution.metadata, "version", _boom)
    assert isinstance(attribution.package_version(), str)


def test_the_sdk_clients_report_the_same_version(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    from src.core.databricks_client import _get_package_version

    assert _get_package_version() == "9.9.9"


def test_hash_is_twelve_hex_of_the_email_local_part():
    assert attribution.hash_username("jane.doe@example.com") == attribution.hash_username(
        "jane.doe@other.org"
    )
    digest = attribution.hash_username("jane.doe@example.com")
    assert len(digest) == 12 and int(digest, 16) >= 0
    assert "jane" not in digest


def test_system_product_kwargs(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    assert attribution.system_product_kwargs() == {
        "product": "tellr-app-system",
        "product_version": "9.9.9",
    }


def test_databricks_client_keeps_its_names():
    from src.core import databricks_client

    assert databricks_client.PRODUCT_NAME_SYSTEM == "tellr-app-system"
    assert databricks_client.PRODUCT_NAME_USER_PREFIX == "tellr-app-"
    assert databricks_client._hash_username("a@b.c") == attribution.hash_username("a@b.c")
```

In `tests/unit/test_gateway_clients.py`: the autouse fixture clears `attribution.package_version` as well as `gateway_clients._tellr_version` (if that cache still exists), and the two version tests patch `attribution.metadata` instead of `gateway_clients.metadata`:

```python
from src.core import attribution

@pytest.fixture(autouse=True)
def _fresh_version_cache():
    attribution.package_version.cache_clear()
    yield
    attribution.package_version.cache_clear()

# in test_user_agent_reports_the_installed_wheel_version and
# test_user_agent_falls_back_to_the_source_version_outside_a_wheel:
monkeypatch.setattr(attribution.metadata, "version", _version)       # was gateway_clients.metadata
monkeypatch.setattr(attribution.metadata, "version", _not_installed) # was gateway_clients.metadata
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_attribution.py tests/unit/test_gateway_clients.py -q`
Expected: `test_attribution.py` errors on collection (`cannot import name 'attribution' from 'src.core'`).

- [ ] **Step 3: Implement**

`src/core/attribution.py`:

```python
"""The labels Tellr puts on its own requests.

A label is a product name, a version or one of a fixed list of feature names.
Nothing here ever carries a prompt, deck content, user text or a customer name.
Every function returns a fallback instead of raising: a label must never be the
reason a request or a deploy fails.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib import metadata
from typing import Final

#: The wheel a deployed app installs (``packages/databricks-tellr-app``).
APP_PACKAGE: Final[str] = "databricks-tellr-app"
PRODUCT_NAME_SYSTEM: Final[str] = "tellr-app-system"
PRODUCT_NAME_USER_PREFIX: Final[str] = "tellr-app-"
PRODUCT_NAME_UNKNOWN: Final[str] = "tellr-app-unknown"


@lru_cache(maxsize=1)
def package_version() -> str:
    """The deployed release: the installed wheel's metadata, else the source tree's.

    The wheel's copied ``src/`` has no generated ``_version.py``, so the source
    tree alone reports ``src/__init__``'s placeholder on a deployed app.
    """
    try:
        return metadata.version(APP_PACKAGE)
    except Exception:  # noqa: BLE001 - not installed, or unreadable metadata
        pass
    try:
        from src._version import version

        return version
    except ImportError:
        pass
    try:
        from src import __version__

        return __version__
    except ImportError:
        return "unknown"


def hash_username(username: str) -> str:
    """First 12 hex of SHA-256 of the email's local part (the whole name if no ``@``)."""
    local_part = username.split("@")[0] if "@" in username else username
    return hashlib.sha256(local_part.encode()).hexdigest()[:12]


def system_product_kwargs() -> dict[str, str]:
    """``product=`` / ``product_version=`` for a client that runs as the app."""
    return {"product": PRODUCT_NAME_SYSTEM, "product_version": package_version()}
```

`src/core/databricks_client.py`: replace the constants block and the bodies of `_get_package_version` and `_hash_username` (keep both functions and their docstrings' first line):

```python
from src.core.attribution import (
    PRODUCT_NAME_SYSTEM,
    PRODUCT_NAME_USER_PREFIX,
    hash_username,
    package_version,
)


def _get_package_version() -> str:
    """The version SDK clients report (see ``attribution.package_version``)."""
    return package_version()


def _hash_username(username: str) -> str:
    """Short hash of the username for the per-user product name."""
    return hash_username(username)
```

`src/services/gateway_clients.py`: delete `_APP_PACKAGE`, the `lru_cache` and `metadata` imports if now unused, and make `_tellr_version` a plain call:

```python
def _tellr_version() -> str:
    """The deployed release (``attribution.package_version``)."""
    from src.core.attribution import package_version

    return package_version()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_attribution.py tests/unit/test_gateway_clients.py tests/unit/test_client.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/attribution.py src/core/databricks_client.py src/services/gateway_clients.py tests/unit/test_attribution.py tests/unit/test_gateway_clients.py
git commit -m "feat(attribution): SDK clients report the installed version, from one module"
```

---

### Task 2: No unlabelled client

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `src/core/attribution.py` (add the per-token label)
- Modify: `src/core/databricks_client.py:421-511` (`_create_user_client`)
- Modify: `src/services/agent_tools/genie_agent.py:137-151` (`_genie`)
- Modify: `src/services/agent_tools/mcp_transport.py:99-148` (`build_user_mcp_client`)
- Modify: `src/services/tools/mcp_tool.py:68`, `:135`
- Test: `tests/unit/test_attribution.py`, `tests/unit/test_client_labels.py` (create)

**Interfaces:**
- Consumes: `package_version()`, `hash_username()`, the product-name constants (Task 1).
- Produces, in `src/core/attribution.py`:
  - `remember_user_product(token: str, product: str) -> None`
  - `user_product_kwargs(token: str | None = None) -> dict[str, str]` → `{"product": ..., "product_version": ...}`. Lookup order: the product remembered for `token`; else `tellr-app-<hash>` of `get_current_user()`; else `tellr-app-unknown`.
  - `mcp_user_agent() -> str` → `f"tellr/{package_version()} python-httpx/{httpx.__version__}"`

Why a token lookup and not only the ContextVar: `run_with_timeout` (`mcp_transport.py`) and the Legacy MCP tool build their clients inside a bare `ThreadPoolExecutor`, where the request's ContextVars are not visible. Every one of those sites holds the user's token, and `_create_user_client` already computes the label for that token.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_attribution.py`:

```python
import threading

from src.core import user_context


def test_label_for_a_remembered_token(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    attribution.remember_user_product("tok-A", "tellr-app-aaaaaaaaaaaa")
    assert attribution.user_product_kwargs("tok-A") == {
        "product": "tellr-app-aaaaaaaaaaaa",
        "product_version": "9.9.9",
    }


def test_label_is_found_from_a_thread_with_no_request_context():
    attribution.remember_user_product("tok-B", "tellr-app-bbbbbbbbbbbb")
    seen = {}

    def run():
        seen["kwargs"] = attribution.user_product_kwargs("tok-B")

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert seen["kwargs"]["product"] == "tellr-app-bbbbbbbbbbbb"


def test_label_falls_back_to_the_request_user_then_unknown():
    user_context.set_current_user("jane.doe@example.com")
    try:
        assert attribution.user_product_kwargs("never-seen")["product"] == (
            "tellr-app-" + attribution.hash_username("jane.doe@example.com")
        )
    finally:
        user_context.set_current_user(None)
    assert attribution.user_product_kwargs("never-seen")["product"] == "tellr-app-unknown"
    assert attribution.user_product_kwargs(None)["product"] == "tellr-app-unknown"


def test_the_token_itself_is_never_kept():
    attribution.remember_user_product("super-secret-token", "tellr-app-cccccccccccc")
    assert "super-secret-token" not in repr(attribution._token_products)


def test_remembered_tokens_are_bounded():
    for n in range(attribution._MAX_TOKEN_PRODUCTS + 50):
        attribution.remember_user_product(f"tok-{n}", "tellr-app-dddddddddddd")
    assert len(attribution._token_products) <= attribution._MAX_TOKEN_PRODUCTS


def test_mcp_user_agent_leads_with_tellr(monkeypatch):
    import httpx

    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    assert attribution.mcp_user_agent() == f"tellr/9.9.9 python-httpx/{httpx.__version__}"
```

`tests/unit/test_client_labels.py`:

```python
"""Every client Tellr builds says it is Tellr: no bare WorkspaceClient, no bare MCP client."""

import ast
import asyncio
from pathlib import Path

import httpx
import pytest

from src.core import attribution

SRC = Path(__file__).resolve().parents[2] / "src"


def _bare_workspace_clients(source: str) -> list[int]:
    """Lines that build a ``WorkspaceClient`` with neither ``product=`` nor ``config=``."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
        if name != "WorkspaceClient":
            continue
        kwargs = {kw.arg for kw in node.keywords}
        spreads = None in kwargs  # a ``**mapping`` argument
        if "product" not in kwargs and "config" not in kwargs and not spreads:
            lines.append(node.lineno)
    return lines


def test_guard_flags_a_bare_client_and_accepts_the_labelled_forms():
    source = (
        "a = WorkspaceClient(host=h, token=t)\n"
        "b = WorkspaceClient(host=h, token=t, product='tellr-app-system')\n"
        "c = WorkspaceClient(config=cfg)\n"
        "d = WorkspaceClient(host=h, **user_product_kwargs(t))\n"
        "# e = WorkspaceClient()\n"
    )
    assert _bare_workspace_clients(source) == [1]


def test_no_workspace_client_in_src_is_bare():
    bare = {
        path.relative_to(SRC).as_posix(): lines
        for path in SRC.rglob("*.py")
        if (lines := _bare_workspace_clients(path.read_text()))
    }
    assert bare == {}


def test_a_config_built_for_a_client_carries_the_label():
    """``Config(...)`` feeding ``WorkspaceClient(config=...)`` must be labelled itself."""
    source = (SRC / "services/agent_tools/genie_agent.py").read_text()
    configs = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Config"
    ]
    assert configs
    for node in configs:
        assert None in {kw.arg for kw in node.keywords}, f"Config at line {node.lineno}"


def test_agent_mode_genie_client_is_labelled_for_its_user(monkeypatch):
    from src.services.agent_tools import genie_agent

    attribution.remember_user_product("tok-genie", "tellr-app-eeeeeeeeeeee")
    built = {}

    class _Config:
        def __init__(self, **kwargs):
            built.update(kwargs)

    class _Client:
        def __init__(self, config):
            self.genie = object()

    monkeypatch.setattr(genie_agent, "Config", _Config)
    monkeypatch.setattr(genie_agent, "WorkspaceClient", _Client)
    client = genie_agent.GenieAgentClient(
        host="https://h", token="tok-genie", space_id="s", source="x"
    )
    client._genie()
    assert built["product"] == "tellr-app-eeeeeeeeeeee"
    assert built["product_version"] == attribution.package_version()


def test_first_stage_user_client_is_labelled(monkeypatch):
    from src.core import databricks_client

    calls = []

    class _Me:
        user_name = "jane.doe@example.com"

    class _Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.current_user = type("U", (), {"me": staticmethod(lambda: _Me())})()

    monkeypatch.setenv("DATABRICKS_HOST", "https://h")
    monkeypatch.setattr(databricks_client, "WorkspaceClient", _Client)
    databricks_client._create_user_client("tok-first")
    assert calls[0]["product"] == "tellr-app-system"
    expected = "tellr-app-" + attribution.hash_username("jane.doe@example.com")
    assert calls[1]["product"] == expected
    assert attribution.user_product_kwargs("tok-first")["product"] == expected


def test_mcp_http_client_sends_one_tellr_user_agent_and_no_tag_header(monkeypatch):
    from src.services.agent_tools import mcp_transport

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    headers = mcp_transport.mcp_http_headers()
    assert headers == {"User-Agent": attribution.mcp_user_agent()}

    async def go():
        async with httpx.AsyncClient(
            headers=headers, transport=httpx.MockTransport(handler)
        ) as client:
            await client.get("https://h/ai-gateway/mcp-services/x")

    asyncio.run(go())
    assert seen[0].headers.get_list("user-agent") == [attribution.mcp_user_agent()]
    assert "databricks-ai-gateway-request-tags" not in seen[0].headers


def test_mcp_transport_opens_its_http_client_with_those_headers():
    source = (SRC / "services/agent_tools/mcp_transport.py").read_text()
    clients = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "httpx.AsyncClient"
    ]
    assert clients
    for node in clients:
        kwargs = {kw.arg: ast.unparse(kw.value) for kw in node.keywords}
        assert kwargs.get("headers") == "mcp_http_headers()", f"line {node.lineno}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_attribution.py tests/unit/test_client_labels.py -q`
Expected: the new attribution tests fail with `AttributeError: module 'src.core.attribution' has no attribute 'remember_user_product'`; `test_no_workspace_client_in_src_is_bare` fails listing `core/databricks_client.py`, `services/agent_tools/mcp_transport.py` and `services/tools/mcp_tool.py`; the guard's own test passes.

- [ ] **Step 3: Implement**

Add to `src/core/attribution.py`:

```python
import threading

_MAX_TOKEN_PRODUCTS: Final[int] = 200
#: SHA-256 of a user token -> that user's product name.  Never the token itself.
_token_products: dict[str, str] = {}
_token_products_lock = threading.Lock()


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def remember_user_product(token: str, product: str) -> None:
    """Record the product name of the user who owns ``token`` (oldest entry dropped at the cap)."""
    with _token_products_lock:
        _token_products.pop(_token_key(token), None)
        while len(_token_products) >= _MAX_TOKEN_PRODUCTS:
            _token_products.pop(next(iter(_token_products)))
        _token_products[_token_key(token)] = product


def user_product_kwargs(token: str | None = None) -> dict[str, str]:
    """``product=`` / ``product_version=`` for a client that runs as a user.

    The product remembered for ``token`` (works in any thread), else the hash of
    the request's user, else ``tellr-app-unknown``.  Makes no network call.
    """
    product: str | None = None
    if token:
        with _token_products_lock:
            product = _token_products.get(_token_key(token))
    if product is None:
        try:
            from src.core.user_context import get_current_user

            username = get_current_user()
        except Exception:  # noqa: BLE001 - a label never fails a request
            username = None
        product = (
            f"{PRODUCT_NAME_USER_PREFIX}{hash_username(username)}"
            if username
            else PRODUCT_NAME_UNKNOWN
        )
    return {"product": product, "product_version": package_version()}


def mcp_user_agent() -> str:
    """User-Agent of Tellr's MCP HTTP client: product first, the library's own kept after it."""
    import httpx

    return f"tellr/{package_version()} python-httpx/{httpx.__version__}"
```

`src/core/databricks_client.py`, `_create_user_client`: label the first-stage client, and remember the label once it is known (both the success and the fallback branch):

```python
        initial_client = WorkspaceClient(
            host=host,
            token=token,
            auth_type="pat",
            **system_product_kwargs(),
        )
        ...
        # after product_name is set, in both branches:
        remember_user_product(token, product_name)
```

(import `remember_user_product` and `system_product_kwargs` from `src.core.attribution`.)

`src/services/agent_tools/genie_agent.py`, `_genie`:

```python
                    config = Config(
                        host=self._host,
                        token=self._token,
                        auth_type="pat",
                        http_timeout_seconds=_CALL_TIMEOUT_SECONDS,
                        retry_timeout_seconds=_CALL_TIMEOUT_SECONDS,
                        **user_product_kwargs(self._token),
                    )
```

`src/services/agent_tools/mcp_transport.py`: add a module-level helper, use it for the HTTP client, and label the workspace client:

```python
def mcp_http_headers() -> dict[str, str]:
    """Headers of Tellr's MCP HTTP client.

    The User-Agent only: the AI Gateway records the request-tags header on model
    routes, not on MCP routes.
    """
    from src.core.attribution import mcp_user_agent

    return {"User-Agent": mcp_user_agent()}

            async with httpx.AsyncClient(
                auth=UserBearerAuth(self.client),
                timeout=httpx.Timeout(30, read=300),
                follow_redirects=True,
                headers=mcp_http_headers(),
            ) as http_client:

    workspace_client = WorkspaceClient(
        host=host, token=token, auth_type="pat", **user_product_kwargs(token)
    )
```

`src/services/tools/mcp_tool.py`, both sites:

```python
        ws_client = WorkspaceClient(
            host=host, token=token, auth_type="pat", **user_product_kwargs(token)
        )
```

`src/services/model_endpoint_catalog.py:201` needs no change: `Config.copy()` keeps the system client's product (verified on SDK 0.157.0), and the guard accepts `config=`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_attribution.py tests/unit/test_client_labels.py tests/unit/test_client.py tests/unit/test_genie_agent_client.py tests/unit/test_genie_one_client.py tests/unit/test_model_endpoint_catalog.py -q`
Expected: all PASS.

Sabotage (revert after each): remove `**user_product_kwargs(token)` from one `mcp_tool.py` site → `test_no_workspace_client_in_src_is_bare` red; remove `headers=mcp_http_headers()` → `test_mcp_transport_opens_its_http_client_with_those_headers` red.

- [ ] **Step 5: Commit**

```bash
git add src/core/attribution.py src/core/databricks_client.py src/services/agent_tools/genie_agent.py src/services/agent_tools/mcp_transport.py src/services/tools/mcp_tool.py tests/unit/test_attribution.py tests/unit/test_client_labels.py
git commit -m "feat(attribution): label Agent-mode Genie, MCP and first-stage clients; guard against bare clients"
```

---

### Task 3: `component` on the Gateway tag

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `src/services/gateway_clients.py`
- Modify: `src/services/agent_runtime.py:560-566`, `src/api/services/session_naming.py:109-115`, `src/services/html_to_pptx.py:76`, `src/services/html_to_google_slides.py:359`, `src/services/image_generation.py:454`
- Test: `tests/unit/test_gateway_clients.py`, plus the exact-tag assertions in `tests/unit/test_agent_runtime.py`, `tests/unit/test_agent_runtime_tool_loop.py`, `tests/unit/test_session_naming.py`

**Interfaces:**
- Produces, in `src/services/gateway_clients.py`:
  - `COMPONENTS: Final[frozenset[str]] = frozenset({"generation", "title", "export", "image"})`
  - `gateway_request_headers(component: str | None = None) -> dict[str, str]`
  - `gateway_chat_model(*, component: str | None = None, **kwargs) -> Any`
  - `gateway_openai_client(workspace_client, *, component: str | None = None, **client_kwargs) -> Any`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_gateway_clients.py`:

```python
@pytest.mark.parametrize("component", ["generation", "title", "export", "image"])
def test_component_is_added_beside_source(component):
    tags = json.loads(gateway_request_headers(component)[REQUEST_TAGS_HEADER])
    assert tags == {"source": "tellr", "component": component}


@pytest.mark.parametrize("value", ["judge", "Generation", "", "a prompt someone typed", None])
def test_a_component_off_the_list_is_dropped(value):
    tags = json.loads(gateway_request_headers(value)[REQUEST_TAGS_HEADER])
    assert tags == {"source": "tellr"}


def test_chat_model_sends_its_component(monkeypatch):
    workspace = _text_workspace(monkeypatch)
    model = gateway_chat_model(
        component="title", model="system.ai.claude-opus-5-5", workspace_client=workspace
    )
    model.invoke([HumanMessage(content="hi")])
    sent = workspace.requests[0]
    assert json.loads(sent.headers["databricks-ai-gateway-request-tags"]) == {
        "source": "tellr",
        "component": "title",
    }
    body = json.loads(sent.content)
    assert "component" not in body and "extra_headers" not in body


def test_openai_client_sends_its_component(monkeypatch):
    workspace = _text_workspace(monkeypatch)
    client = gateway_openai_client(workspace, component="export")
    client.chat.completions.create(
        model="system.ai.claude-opus-5-5", messages=[{"role": "user", "content": "hi"}]
    )
    assert json.loads(workspace.requests[0].headers["databricks-ai-gateway-request-tags"]) == {
        "source": "tellr",
        "component": "export",
    }


def test_every_builder_call_site_names_its_component():
    src = Path(__file__).resolve().parents[2] / "src"
    expected = {
        "services/agent_runtime.py": "generation",
        "api/services/session_naming.py": "title",
        "services/html_to_pptx.py": "export",
        "services/html_to_google_slides.py": "export",
        "services/image_generation.py": "image",
    }
    found = {}
    for path in src.rglob("*.py"):
        if path.name == "gateway_clients.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in (
                "gateway_chat_model",
                "gateway_openai_client",
            ):
                kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                value = kwargs.get("component")
                found[path.relative_to(src).as_posix()] = (
                    value.value if isinstance(value, ast.Constant) else None
                )
    assert found == expected
```

(`_text_workspace(monkeypatch)` is the plain-text mock workspace already defined in this file; reuse it.)

Update the exact-header assertions that pin `'{"source": "tellr"}'` on graph, tool-loop and title requests in `tests/unit/test_agent_runtime.py`, `tests/unit/test_agent_runtime_tool_loop.py` and `tests/unit/test_session_naming.py` to compare parsed JSON: `{"source": "tellr", "component": "generation"}` for the adapter and every tool-loop round, `{"source": "tellr", "component": "title"}` for titles. In `test_session_naming.py`, the expected constructor kwargs become `"extra_params": {"extra_headers": gateway_request_headers("title")}`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_gateway_clients.py tests/unit/test_agent_runtime.py tests/unit/test_agent_runtime_tool_loop.py tests/unit/test_session_naming.py -q`
Expected: the new tests fail with `TypeError: gateway_request_headers() takes 0 positional arguments but 1 was given`; the updated assertions fail on the missing `component` key.

- [ ] **Step 3: Implement**

`src/services/gateway_clients.py`:

```python
#: The fixed feature names a tag may carry.  A value outside the set is dropped,
#: so a tag can never carry free text.
COMPONENTS: Final[frozenset[str]] = frozenset({"generation", "title", "export", "image"})


def _request_tags(component: str | None = None) -> str:
    tags: dict[str, str] = {"source": "tellr"}
    if component in COMPONENTS:
        tags["component"] = component
    return json.dumps(tags)


def gateway_request_headers(component: str | None = None) -> dict[str, str]:
    import openai

    return {
        REQUEST_TAGS_HEADER: _request_tags(component),
        "User-Agent": f"tellr/{_tellr_version()} DatabricksOpenAI/Python {openai.__version__}",
    }


def gateway_chat_model(*, component: str | None = None, **kwargs: Any) -> Any:
    from databricks_langchain import ChatDatabricks  # type: ignore[import-untyped]

    return ChatDatabricks(
        use_ai_gateway=True,
        extra_params={"extra_headers": gateway_request_headers(component)},
        **kwargs,
    )


def gateway_openai_client(
    workspace_client: Any, *, component: str | None = None, **client_kwargs: Any
) -> Any:
    from databricks_openai import DatabricksOpenAI

    return DatabricksOpenAI(
        workspace_client=workspace_client,
        use_ai_gateway=True,
        default_headers=gateway_request_headers(component),
        **client_kwargs,
    )
```

Remove the module-level `_REQUEST_TAGS` constant; keep each function's existing docstring and add one sentence naming `component`. Update the module docstring's first paragraph to say the tag also carries the feature name.

Call sites, one keyword each:

```python
# src/services/agent_runtime.py  (_default_model_factory)
return gateway_chat_model(component="generation", **kwargs)
# src/api/services/session_naming.py  (build_session_title_model)
return gateway_chat_model(component="title", model=SESSION_TITLE_MODEL, max_tokens=50, workspace_client=get_system_client())
# src/services/html_to_pptx.py:76 and src/services/html_to_google_slides.py:359
self.llm_client = gateway_openai_client(self.ws_client, component="export")
# src/services/image_generation.py:454
return gateway_openai_client(get_system_client(), component="image", max_retries=0)
```

The existing AST guard (`_is_headers_call`) matches a call to `gateway_request_headers` with any arguments, so it needs no change; confirm it still passes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_gateway_clients.py tests/unit/test_agent_runtime.py tests/unit/test_agent_runtime_tool_loop.py tests/unit/test_session_naming.py tests/unit/test_html_to_pptx.py tests/unit/test_google_slides_converter.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/services/gateway_clients.py src/services/agent_runtime.py src/api/services/session_naming.py src/services/html_to_pptx.py src/services/html_to_google_slides.py src/services/image_generation.py tests/unit
git commit -m "feat(gateway): tag each Gateway call with its component"
```

---

### Task 4: `entrypoint` on the Gateway tag

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `src/core/attribution.py` (the ContextVar)
- Modify: `src/services/gateway_clients.py` (`_request_tags`)
- Modify: `src/api/routes/chat.py:958` (before `enqueue_job`), `src/api/mcp_server.py:252` (before `enqueue_job`)
- Test: `tests/unit/test_gateway_clients.py`, `tests/unit/test_attribution.py`

**Interfaces:**
- Consumes: `_request_tags(component)` (Task 3).
- Produces, in `src/core/attribution.py`:
  - `ENTRYPOINTS: Final[frozenset[str]] = frozenset({"app", "mcp"})`
  - `set_entrypoint(value: str) -> None` (ignores a value off the list)
  - `get_entrypoint() -> str | None`

How it travels: `enqueue_job` (`src/api/services/job_queue.py:164`) already captures `contextvars.copy_context()` and the worker runs the job inside it, so a ContextVar set just before `enqueue_job` is visible to every model call of that turn. On `main` an MCP job runs the Legacy engine, whose deck calls do not go through the Gateway, so today the `mcp` value shows on that job's title call; it reaches the deck calls when MCP jobs run on the graph (`feat/mcp-agent-mode`), with no further change.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_attribution.py`:

```python
import contextvars


def test_entrypoint_is_unset_by_default_and_ignores_values_off_the_list():
    def run():
        assert attribution.get_entrypoint() is None
        attribution.set_entrypoint("cron")
        assert attribution.get_entrypoint() is None
        attribution.set_entrypoint("mcp")
        assert attribution.get_entrypoint() == "mcp"

    contextvars.copy_context().run(run)
    assert attribution.get_entrypoint() is None
```

`tests/unit/test_gateway_clients.py`:

```python
import contextvars

from src.core import attribution


@pytest.mark.parametrize("entrypoint", ["app", "mcp"])
def test_entrypoint_is_added_when_the_turn_set_it(entrypoint):
    def run():
        attribution.set_entrypoint(entrypoint)
        return json.loads(gateway_request_headers("generation")[REQUEST_TAGS_HEADER])

    assert contextvars.copy_context().run(run) == {
        "source": "tellr",
        "component": "generation",
        "entrypoint": entrypoint,
    }


def test_no_entrypoint_key_outside_a_turn():
    assert "entrypoint" not in json.loads(gateway_request_headers("title")[REQUEST_TAGS_HEADER])


def test_entrypoint_survives_the_job_queues_context_copy():
    """``enqueue_job`` copies the context; the worker's model call must still see it."""

    def enqueue():
        attribution.set_entrypoint("mcp")
        return contextvars.copy_context()

    captured = contextvars.copy_context().run(enqueue)
    tags = captured.run(lambda: json.loads(gateway_request_headers("generation")[REQUEST_TAGS_HEADER]))
    assert tags["entrypoint"] == "mcp"


def test_both_enqueue_sites_set_their_entrypoint_first():
    src = Path(__file__).resolve().parents[2] / "src"
    for rel, value in (("api/routes/chat.py", "app"), ("api/mcp_server.py", "mcp")):
        text = (src / rel).read_text()
        call = f'set_entrypoint("{value}")'
        assert call in text, rel
        assert text.index(call) < text.index("await enqueue_job("), rel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_attribution.py tests/unit/test_gateway_clients.py -q`
Expected: FAIL with `AttributeError: module 'src.core.attribution' has no attribute 'get_entrypoint'`.

- [ ] **Step 3: Implement**

`src/core/attribution.py`:

```python
from contextvars import ContextVar

#: How a chat turn reached Tellr: its own UI, or its MCP server.
ENTRYPOINTS: Final[frozenset[str]] = frozenset({"app", "mcp"})
_entrypoint_var: ContextVar[str | None] = ContextVar("tellr_entrypoint", default=None)


def set_entrypoint(value: str) -> None:
    """Mark the current turn's entrypoint; a value off the list is ignored."""
    if value in ENTRYPOINTS:
        _entrypoint_var.set(value)


def get_entrypoint() -> str | None:
    return _entrypoint_var.get()
```

`src/services/gateway_clients.py`, `_request_tags`:

```python
def _request_tags(component: str | None = None) -> str:
    from src.core.attribution import ENTRYPOINTS, get_entrypoint

    tags: dict[str, str] = {"source": "tellr"}
    if component in COMPONENTS:
        tags["component"] = component
    entrypoint = get_entrypoint()
    if entrypoint in ENTRYPOINTS:
        tags["entrypoint"] = entrypoint
    return json.dumps(tags)
```

`src/api/routes/chat.py`, immediately before `await enqueue_job(` at line 958:

```python
            set_entrypoint("app")
```

`src/api/mcp_server.py`, immediately before `await enqueue_job(` at line 252:

```python
        set_entrypoint("mcp")
```

(each file imports `set_entrypoint` from `src.core.attribution`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_attribution.py tests/unit/test_gateway_clients.py tests/unit/test_agent_runtime.py tests/unit/test_session_naming.py -q`
Expected: all PASS. (The Task 3 exact-tag assertions run outside a turn, so they still see no `entrypoint` key.)

- [ ] **Step 5: Commit**

```bash
git add src/core/attribution.py src/services/gateway_clients.py src/api/routes/chat.py src/api/mcp_server.py tests/unit/test_attribution.py tests/unit/test_gateway_clients.py
git commit -m "feat(gateway): tag Gateway calls with the turn's entrypoint (app or mcp)"
```

---

### Task 5: Installer attaches the Lakebase branch to the app

**Models:** `test=opus impl=opus`

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py` (imports; new `_ensure_app_postgres_resource`; `_create_databricks` step 3b; `_update_databricks` before the deploy; the comment at `_create_app:1681-1701`)
- Modify: `scripts/deploy_local.py:612`, `:760` (its two `_ensure_sp_autoscaling_role` calls; add the attach after each, with that call's branch)
- Test: `tests/unit/test_deploy_postgres_resource.py` (create)

**Interfaces:**
- Produces, in `databricks_tellr/deploy.py`:
  - `DATABASE_RESOURCE_NAME = "app_database"`
  - `_ensure_app_postgres_resource(ws, app_name: str, project_name: str, branch_name: str = "production") -> bool` — `True` if it attached the resource, `False` if nothing was needed or it failed. Never raises.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_deploy_postgres_resource.py`:

```python
"""The installer links an autoscaling install's Lakebase branch to its app."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from databricks.sdk.service.apps import (
    App,
    AppResource,
    AppResourceDatabase,
    AppResourcePostgres,
    AppResourceSecret,
)
from databricks_tellr import deploy

BRANCH = "projects/tellr-db/branches/production"
DATABASE = f"{BRANCH}/databases/databricks-postgres"


def _ws(app: App) -> MagicMock:
    ws = MagicMock()
    ws.apps.get.return_value = app
    return ws


def test_attaches_the_branch_and_carries_every_other_field():
    secret = AppResource(name="encryption_key", secret=AppResourceSecret(scope="s", key="k"))
    ws = _ws(
        App(
            name="tellr",
            description="Tellr",
            default_source_code_path="/ws/src",
            user_api_scopes=["sql"],
            resources=[secret],
        )
    )
    assert deploy._ensure_app_postgres_resource(ws, "tellr", "tellr-db") is True
    sent = ws.apps.update.call_args.kwargs["app"]
    assert ws.apps.update.call_args.kwargs["name"] == "tellr"
    assert [r.name for r in sent.resources] == ["encryption_key", "app_database"]
    added = sent.resources[-1].postgres
    assert added.branch == BRANCH
    assert added.database == DATABASE
    assert added.permission.value == "CAN_CONNECT_AND_CREATE"
    assert sent.description == "Tellr"
    assert sent.default_source_code_path == "/ws/src"
    assert sent.user_api_scopes == ["sql"]
    assert sent.compute_size is None


def test_names_the_forks_own_branch():
    ws = _ws(App(name="tellr"))
    deploy._ensure_app_postgres_resource(ws, "tellr", "tellr-db", branch_name="dev-x")
    added = ws.apps.update.call_args.kwargs["app"].resources[-1].postgres
    assert added.branch == "projects/tellr-db/branches/dev-x"
    assert added.database == "projects/tellr-db/branches/dev-x/databases/databricks-postgres"


@pytest.mark.parametrize(
    "existing",
    [
        AppResource(name="app_database", postgres=AppResourcePostgres(branch=BRANCH, database=DATABASE)),
        AppResource(
            name="app_database",
            database=AppResourceDatabase(instance_name="tellr-db", database_name="databricks_postgres"),
        ),
        AppResource(name="my_pg", postgres=AppResourcePostgres(branch=BRANCH, database=DATABASE)),
    ],
)
def test_an_app_that_already_has_a_database_resource_is_left_alone(existing):
    ws = _ws(App(name="tellr", resources=[existing]))
    assert deploy._ensure_app_postgres_resource(ws, "tellr", "tellr-db") is False
    ws.apps.update.assert_not_called()


def test_a_refusal_warns_and_continues(capsys):
    ws = _ws(App(name="tellr"))
    ws.apps.update.side_effect = RuntimeError("feature not enabled")
    assert deploy._ensure_app_postgres_resource(ws, "tellr", "tellr-db") is False
    out = capsys.readouterr().out
    assert "WARNING" in out and "feature not enabled" in out


def test_a_failed_lookup_warns_and_continues(capsys):
    ws = MagicMock()
    ws.apps.get.side_effect = RuntimeError("no such app")
    assert deploy._ensure_app_postgres_resource(ws, "tellr", "tellr-db") is False
    assert "WARNING" in capsys.readouterr().out


def test_create_app_never_carries_the_postgres_resource():
    """Passing it to apps.create makes the platform create the role itself, and the
    installer's own role setup then fails with 'role with that name already exists'."""
    ws = MagicMock()
    deploy._create_app(ws, "app", "desc", "/ws/src", "MEDIUM", "lb", lakebase_type="autoscaling")
    created = ws.apps.create_and_wait.call_args.args[0]
    assert [r for r in (created.resources or []) if r.postgres is not None] == []


def test_create_attaches_after_the_role_and_before_the_deploy(monkeypatch):
    order = []
    monkeypatch.setattr(deploy, "_ensure_sp_autoscaling_role", lambda *a, **k: order.append("role"))
    monkeypatch.setattr(
        deploy, "_ensure_app_postgres_resource", lambda *a, **k: order.append("attach") or True
    )
    monkeypatch.setattr(deploy, "_setup_database_schema", lambda *a, **k: order.append("schema"))
    monkeypatch.setattr(deploy, "_deploy_app", lambda *a, **k: order.append("deploy") or MagicMock(url="u"))
    monkeypatch.setattr(
        deploy,
        "_get_or_create_lakebase",
        lambda *a, **k: {"name": "lb", "type": "autoscaling", "status": "created", "host": "h",
                         "endpoint_name": "e", "project_id": "lb", "instance_name": None},
    )
    monkeypatch.setattr(deploy, "_upload_files", lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_create_app", lambda *a, **k: MagicMock(service_principal_client_id="cid"))
    monkeypatch.setattr(deploy, "_ensure_app_sp_can_manage", lambda *a, **k: True)
    deploy.create(
        lakebase_name="lb", schema_name="app_data", app_name="app",
        app_file_workspace_path="/ws/src", client=MagicMock(),
    )
    assert order == ["role", "attach", "schema", "deploy"]


def test_create_on_provisioned_lakebase_does_not_attach(monkeypatch):
    attach = MagicMock()
    monkeypatch.setattr(deploy, "_ensure_app_postgres_resource", attach)
    monkeypatch.setattr(
        deploy,
        "_get_or_create_lakebase",
        lambda *a, **k: {"name": "lb", "type": "provisioned", "status": "exists", "host": None,
                         "endpoint_name": None, "project_id": None, "instance_name": "lb"},
    )
    for name in ("_upload_files", "_setup_database_schema", "_ensure_app_sp_can_manage"):
        monkeypatch.setattr(deploy, name, lambda *a, **k: None)
    monkeypatch.setattr(deploy, "_create_app", lambda *a, **k: MagicMock(service_principal_client_id="cid"))
    monkeypatch.setattr(deploy, "_deploy_app", lambda *a, **k: MagicMock(url="u"))
    deploy.create(
        lakebase_name="lb", schema_name="app_data", app_name="app",
        app_file_workspace_path="/ws/src", client=MagicMock(),
    )
    attach.assert_not_called()
```

Also add one test for the update path next to the existing update tests in `tests/unit/test_deploy_app_scopes.py` (reuse that file's `_update_databricks` harness): with an autoscaling `lakebase_result`, `_ensure_app_postgres_resource` is called once with the app name and project name before `ws.apps.deploy_and_wait`; with a provisioned one it is not called.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_deploy_postgres_resource.py -q`
Expected: FAIL with `AttributeError: module 'databricks_tellr.deploy' has no attribute '_ensure_app_postgres_resource'`.

- [ ] **Step 3: Implement**

`packages/databricks-tellr/databricks_tellr/deploy.py`. Guard the import as the other newer-SDK imports are:

```python
HAS_POSTGRES_RESOURCE = False
try:
    from databricks.sdk.service.apps import (
        AppResourcePostgres,
        AppResourcePostgresPostgresPermission,
    )
    HAS_POSTGRES_RESOURCE = True
except ImportError:
    pass

#: The app resource that names the app's Lakebase database (provisioned installs
#: already use this name for their ``AppResourceDatabase``).
DATABASE_RESOURCE_NAME = "app_database"
```

```python
def _ensure_app_postgres_resource(
    ws: WorkspaceClient,
    app_name: str,
    project_name: str,
    branch_name: str = "production",
) -> bool:
    """Attach an autoscaling install's Lakebase branch to its app as a resource.

    The resource is what lets the platform attribute the database's usage to
    the app.  It changes nothing about how the app connects: the app keeps
    reading the ``LAKEBASE_*`` settings from ``app.yaml``.

    Call this only after ``_ensure_sp_autoscaling_role``.  Given the resource
    at ``apps.create`` instead, the platform creates the service principal's
    role itself (as ``dbrx-apps-<client id>``, with no membership) and the
    installer's own role setup then fails with "role with that name already
    exists" (verified live, Nov 2026).

    ``apps.update`` is a full replace on the fields it accepts, so every
    mutable field is carried and ``compute_size`` is omitted, as in
    ``_ensure_app_user_api_scopes``.  An app that already has a database
    resource of either kind is left alone.

    Never raises.  Returns True only when it attached the resource.
    """
    if not HAS_POSTGRES_RESOURCE:
        print("   Lakebase resource not attached: databricks-sdk is too old for it")
        return False
    try:
        cur = ws.apps.get(name=app_name)
        existing = list(cur.resources or [])
        if any(
            r.name == DATABASE_RESOURCE_NAME or r.postgres is not None or r.database is not None
            for r in existing
        ):
            return False
        branch = f"projects/{project_name}/branches/{branch_name}"
        resource = AppResource(
            name=DATABASE_RESOURCE_NAME,
            postgres=AppResourcePostgres(
                branch=branch,
                database=f"{branch}/databases/databricks-postgres",
                permission=AppResourcePostgresPostgresPermission.CAN_CONNECT_AND_CREATE,
            ),
        )
        ws.apps.update(
            name=app_name,
            app=App(
                name=app_name,
                description=cur.description,
                default_source_code_path=cur.default_source_code_path,
                user_api_scopes=cur.user_api_scopes,
                resources=existing + [resource],
                # compute_size deliberately omitted — passing it is rejected.
            ),
        )
    except Exception as exc:  # noqa: BLE001 — the deploy continues without it
        print(
            f"   WARNING: could not attach the Lakebase branch to {app_name} as an "
            f"app resource: {exc}"
        )
        print("   The app is unaffected; only usage attribution for its database is.")
        return False
    print("   Lakebase branch attached to the app as a resource")
    return True
```

`_create_databricks`, step 3b, after the role setup and inside the same `if lakebase_type == "autoscaling":` block:

```python
            if client_id:
                print("Configuring SP role on autoscaling project...")
                _ensure_sp_autoscaling_role(ws, lakebase_name, client_id)
                _ensure_app_postgres_resource(
                    ws, app_name, lakebase_name,
                    branch_name=lakebase_result.get("branch_id") or "production",
                )
```

`_update_databricks`, after `_ensure_app_sp_can_manage(ws, app_name)` and before `# Trigger new deployment`:

```python
        if lakebase_type == "autoscaling":
            _ensure_app_postgres_resource(
                ws, app_name, lakebase_name,
                branch_name=lakebase_result.get("branch_id") or "production",
            )
```

In `_create_app`, replace the docstring's last paragraph and the `else:` comment so they no longer say an autoscaling resource is unsupported:

```python
    For autoscaling, the database resource is NOT passed here: it is attached
    after the service principal's role exists (``_ensure_app_postgres_resource``).
```

Then `grep -n "_ensure_sp_autoscaling_role" scripts/deploy_local.py`: at each call, add `_ensure_app_postgres_resource(ws, app_name, project_name, branch_name=<the branch that call uses>)` on the next line, importing it beside the existing `databricks_tellr.deploy` imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_deploy_postgres_resource.py tests/unit/test_deploy_app_scopes.py tests/unit/test_deploy_autoscaling.py tests/unit/test_deploy_secret_encryption_key.py tests/unit/test_deploy_local_schema_setup_sp_only.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/deploy.py scripts/deploy_local.py tests/unit/test_deploy_postgres_resource.py tests/unit/test_deploy_app_scopes.py
git commit -m "feat(deploy): attach an autoscaling install's Lakebase branch to its app"
```

---

### Task 6: Docs, live check on the dev workspace, PR

**Models:** `test=— impl=opus` — run by the orchestrator, not dispatched: the check is the real platform.

Load `deploy-tellr-dev`, and `databricks-core` + `databricks-dbsql` for the queries. Never `devtest`.

- [ ] **Step 1: Docs.** In `docs/technical/databricks-app-deployment.md`, add a short section "How Tellr identifies its own requests": the three product names, the Gateway tag keys and their allowed values, the MCP User-Agent, the `app_database` resource, and the sentence "A label is a product name, a version or a fixed feature name; it never carries prompts, deck content, user text or customer names." Update the module docstring of `src/core/databricks_client.py` (lines 10-12) to say the version is the installed release.
- [ ] **Step 2: Full unit suite.** `uv run pytest tests/unit -q -n auto`. For each failure, check that it fails the same way on `origin/main`; any failure this branch introduced stops the task.
- [ ] **Step 3: Publish a dev wheel.** Push the branch; `gh workflow run publish-dev.yml --ref feat/consumption-attribution`; record the published `.devN` from the run log (`200 OK` + `View at:`).
- [ ] **Step 4: New install.** From this worktree, run `tellr.create` (the public installer, from `packages/databricks-tellr` at this commit) for a fresh app and a fresh autoscaling Lakebase project on the dev workspace, pinned to the dev version. Expect: `Lakebase branch attached to the app as a resource`; `/api/health` 200; the branch's roles are exactly the user's and `sp-<client id>` with `DATABRICKS_SUPERUSER`; the app's tables exist and are owned by the service principal.
- [ ] **Step 5: Update, twice.** `tellr.update` on that install: the resource is kept and no "attached" line is printed. Run it again: same. Then `tellr.update` on an install created by the released 0.5.7 installer (no resource): the resource is attached once, the app restarts healthy, and a second update is a no-op.
- [ ] **Step 6: Exercise every label.** In the dev install, in Agent mode with one Genie Agent and Genie One enabled: create a deck that asks both for data, let it get its title, export it to PPTX, generate one image. Then create one deck through the MCP server (`scripts/mcp_smoke/`).
- [ ] **Step 7: Read the labels back (≥ 1 h later).** In that workspace's system tables:

```sql
SELECT request_tags['source'] AS source, request_tags['component'] AS component,
       request_tags['entrypoint'] AS entrypoint, user_agent, count(*) AS requests
FROM system.ai_gateway.usage
WHERE event_time >= current_timestamp() - INTERVAL 6 HOURS
  AND request_tags['source'] = 'tellr'
GROUP BY ALL
```

Expected: rows for `generation`, `title`, `export` and `image`, `entrypoint` `app` on the UI deck and `mcp` on the MCP deck's title, `user_agent` starting `tellr/<the dev version>`. Then confirm from the workspace's request records that the Genie conversation requests carry `tellr-app-<hash>/<the dev version>`, that the Genie One requests carry `tellr/<the dev version> python-httpx/…`, and that no request from the app carries `unknown/0.0.0` or version `0.1.0`. No rows after 3 h, or any `/ai-gateway/` 4xx in the app log, is a stop.
- [ ] **Step 8: PR.** Rebase on `origin/main`. Body per `.github/pull_request_template.md`; `## What's new` is `None` (a Tellr user would not notice the change). Include the Step 7 result and the note that the installer change takes effect on the next `tellr.create` / `tellr.update`. End the body with `This pull request and its description were written by Isaac.`
- [ ] **Step 9: Clean up.** Delete the test apps and Lakebase projects created in Steps 4-5.
