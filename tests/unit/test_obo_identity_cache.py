"""OBO identity resolution must not hammer or block on SCIM ``/Me``.

Logfood (2026-11-05): the shared workspace rate-limits ``/api/2.0/preview/scim/v2/Me``
(429). The auth middleware called ``current_user.me()`` on every request, on the
event loop, so one throttled lookup (SDK retries for up to 5 min) froze a whole
uvicorn worker. These tests pin the fix: one ``/Me`` per token per cache TTL,
made off the event loop, single-flight per token, never serialised across users.
"""

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.core import databricks_client as d


class _Me:
    def __init__(self, token):
        self.id = f"id-{token}"
        self.user_name = f"{token}@example.com"


@pytest.fixture
def fake_scim(monkeypatch):
    """Replace WorkspaceClient with a fake whose ``current_user.me()`` is scripted.

    ``state["me"]`` (token -> callable returning a _Me or raising) defaults to an
    instant success; every ``me()`` call is recorded in ``state["calls"]``.
    """
    state = {"calls": [], "me": {}, "on_loop": []}

    class _CurrentUser:
        def __init__(self, token):
            self._token = token

        def me(self):
            try:
                asyncio.get_running_loop()
                state["on_loop"].append(True)
            except RuntimeError:
                state["on_loop"].append(False)
            state["calls"].append(self._token)
            return state["me"].get(self._token, lambda: _Me(self._token))()

    class _FakeWorkspaceClient:
        def __init__(self, host=None, token=None, **kwargs):
            self.current_user = _CurrentUser(token)

    monkeypatch.setenv("DATABRICKS_HOST", "https://example.com")
    monkeypatch.setattr(d, "WorkspaceClient", _FakeWorkspaceClient)
    monkeypatch.setattr(d, "_user_client_cache", {})
    return state


@pytest.fixture
def resolved_users(monkeypatch):
    """Record the usernames the middleware binds per request (None = unresolved)."""
    from src.api import main as main_module

    seen = []
    real = main_module.set_current_user

    def _record(user_name):
        seen.append(user_name)
        real(user_name)

    monkeypatch.setattr(main_module, "set_current_user", _record)
    return seen


def _requests(n, token="tok"):
    from src.api import main as main_module

    client = TestClient(main_module.app, raise_server_exceptions=False)
    for _ in range(n):
        client.get("/api/__nonexistent__", headers={"x-forwarded-access-token": token})


def test_middleware_calls_me_once_per_token_across_requests(fake_scim, resolved_users):
    # Fails if the middleware goes back to calling current_user.me() per request.
    _requests(5)

    assert fake_scim["calls"] == ["tok"]
    assert [u for u in resolved_users if u] == ["tok@example.com"] * 5


def test_middleware_resolves_identity_off_the_event_loop(fake_scim, resolved_users):
    # Fails if /Me is called synchronously inside the async middleware again.
    _requests(1)

    assert fake_scim["on_loop"] == [False]
    assert [u for u in resolved_users if u] == ["tok@example.com"]


def test_failed_identity_lookup_is_retried_on_the_next_request(fake_scim, resolved_users):
    # Fails if a failed lookup is cached (user locked out for the TTL) or if each
    # request still makes more than one /Me call.
    outcomes = iter([RuntimeError("429 Too Many Requests"), None])

    def flaky():
        err = next(outcomes)
        if err:
            raise err
        return _Me("tok")

    fake_scim["me"]["tok"] = flaky
    _requests(2)

    assert fake_scim["calls"] == ["tok", "tok"]
    assert [u for u in resolved_users if u] == ["tok@example.com"]


def test_slow_lookup_for_one_user_does_not_block_another(fake_scim):
    # Fails if one global lock is held across the /Me network call again.
    release_a = threading.Event()
    fake_scim["me"]["a"] = lambda: (release_a.wait(10), _Me("a"))[1]
    done = {}

    def resolve(token):
        d.get_or_create_user_client(token)
        done[token] = time.monotonic()

    ta = threading.Thread(target=resolve, args=("a",))
    ta.start()
    time.sleep(0.2)  # a is now inside its slow /Me call
    tb = threading.Thread(target=resolve, args=("b",))
    tb.start()
    tb.join(2)
    try:
        assert "b" in done, "user b waited on user a's /Me lookup"
    finally:
        release_a.set()
        ta.join(10)


def test_concurrent_misses_for_one_token_share_one_lookup(fake_scim):
    # Fails if the per-token single-flight goes (a page load fires ~10 API calls
    # at once; each would otherwise make its own /Me call).
    fake_scim["me"]["tok"] = lambda: (time.sleep(0.3), _Me("tok"))[1]
    threads = [
        threading.Thread(target=d.get_or_create_user_client, args=("tok",)) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert fake_scim["calls"] == ["tok"]
