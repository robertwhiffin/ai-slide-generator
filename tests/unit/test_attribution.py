"""The labels Tellr puts on its own requests: product, version, never content."""

import hashlib
import re
import socket
import sys
import threading
import types
from contextlib import contextmanager
from importlib import metadata

import pytest

from src.core import attribution, user_context


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


def _broken(name):
    raise RuntimeError("broken metadata")


def _source_tree_version():
    """What the source tree says: its generated ``_version.py`` if built, else ``__init__``'s."""
    try:
        from src._version import version
    except ImportError:
        from src import __version__ as version
    return version


@contextmanager
def _request_user(username):
    """The auth middleware's binding of the request's user, undone on exit as it does."""
    user_context.set_current_user(username)
    try:
        yield
    finally:
        user_context.set_current_user(None)


def test_version_is_the_installed_wheels(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    assert attribution.package_version() == "9.9.9"


def test_version_falls_back_to_the_source_tree_outside_a_wheel(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _not_installed)
    assert attribution.package_version() == _source_tree_version()


@pytest.mark.parametrize("reported", [None, ""])
def test_a_wheel_that_reports_no_version_counts_as_not_installed(monkeypatch, reported):
    """A dist-info with no ``Version`` field makes ``metadata.version`` answer ``None`` on
    Python 3.11: a label must never read ``tellr/None``, nor a bare ``tellr/``."""
    monkeypatch.setattr(attribution.metadata, "version", _installed(reported))
    assert attribution.package_version() == _source_tree_version()


def test_without_a_generated_version_file_the_init_version_is_reported(monkeypatch):
    """A wheel's copied ``src/`` has no ``_version.py``: next is ``src.__version__``."""
    import src

    monkeypatch.setattr(attribution.metadata, "version", _not_installed)
    monkeypatch.setitem(sys.modules, "src._version", None)  # ``import src._version`` now raises

    assert attribution.package_version() == src.__version__


def test_an_unreadable_version_file_falls_back_to_the_init_version(monkeypatch):
    """A ``_version.py`` that fails with anything but ``ImportError`` must not raise into a
    request either: the chain carries on to ``src.__version__``."""
    import src

    def _unreadable(name):
        if name.startswith("__"):  # the import machinery's own probes (``__path__``)
            raise AttributeError(name)
        raise RuntimeError("unreadable _version.py")

    broken = types.ModuleType("src._version")
    broken.__getattr__ = _unreadable  # PEP 562: reading ``version`` now raises RuntimeError
    monkeypatch.setattr(attribution.metadata, "version", _not_installed)
    monkeypatch.setitem(sys.modules, "src._version", broken)

    assert attribution.package_version() == src.__version__


def test_version_lookup_never_raises(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _broken)

    version = attribution.package_version()

    assert isinstance(version, str)
    # Unreadable metadata is treated like a missing wheel: the chain carries on.
    assert version == _source_tree_version()


def test_with_every_source_broken_the_version_is_unknown(monkeypatch):
    import src

    monkeypatch.setattr(attribution.metadata, "version", _broken)
    monkeypatch.setitem(sys.modules, "src._version", None)
    monkeypatch.delattr(src, "__version__")

    assert attribution.package_version() == "unknown"


def test_the_version_is_looked_up_once_until_the_cache_is_cleared(monkeypatch):
    lookups = []

    def _counting(name):
        lookups.append(name)
        return _installed("9.9.9")(name)

    monkeypatch.setattr(attribution.metadata, "version", _counting)

    assert [attribution.package_version() for _ in range(3)] == ["9.9.9"] * 3
    assert lookups == ["databricks-tellr-app"]

    attribution.package_version.cache_clear()

    assert attribution.package_version() == "9.9.9"
    assert lookups == ["databricks-tellr-app"] * 2


def test_the_sdk_clients_report_the_same_version(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    from src.core.databricks_client import _get_package_version

    assert _get_package_version() == "9.9.9"


def test_the_sdk_clients_read_the_one_cached_lookup_not_a_copy(monkeypatch):
    """``attribution.metadata`` is ``importlib.metadata`` itself, so a copy of the lookup in
    ``databricks_client`` would pass the test above. Only attribution's own cache still
    answers 7.0.0 once the installed metadata says 8.0.0."""
    monkeypatch.setattr(attribution.metadata, "version", _installed("7.0.0"))
    assert attribution.package_version() == "7.0.0"
    monkeypatch.setattr(attribution.metadata, "version", _installed("8.0.0"))
    from src.core.databricks_client import _get_package_version

    assert _get_package_version() == "7.0.0"


def test_hash_is_twelve_hex_of_the_email_local_part():
    assert attribution.hash_username("jane.doe@example.com") == attribution.hash_username(
        "jane.doe@other.org"
    )
    digest = attribution.hash_username("jane.doe@example.com")
    assert len(digest) == 12 and int(digest, 16) >= 0
    assert re.fullmatch(r"[0-9a-f]{12}", digest)
    assert "jane" not in digest


def test_hash_is_the_sha256_prefix_already_in_use():
    """Deployed apps already label users ``tellr-app-<hash>``; another digest would split
    each user's history. ``test_client.py`` pins the same value for ``test.user``."""
    assert attribution.hash_username("test.user@company.com") == "07460583da32"
    assert attribution.hash_username("test.user") == "07460583da32"  # no ``@``: the whole name
    assert attribution.hash_username("john.doe@example.com") == "30f69670bba2"


def test_system_product_kwargs(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    assert attribution.system_product_kwargs() == {
        "product": "tellr-app-system",
        "product_version": "9.9.9",
    }


def test_the_label_names_are_fixed():
    assert attribution.APP_PACKAGE == "databricks-tellr-app"
    assert attribution.PRODUCT_NAME_SYSTEM == "tellr-app-system"
    assert attribution.PRODUCT_NAME_USER_PREFIX == "tellr-app-"
    assert attribution.PRODUCT_NAME_UNKNOWN == "tellr-app-unknown"


def test_databricks_client_keeps_its_names():
    from src.core import databricks_client

    assert databricks_client.PRODUCT_NAME_SYSTEM == "tellr-app-system"
    assert databricks_client.PRODUCT_NAME_USER_PREFIX == "tellr-app-"
    assert databricks_client._hash_username("a@b.c") == attribution.hash_username("a@b.c")


def test_label_for_a_remembered_token(monkeypatch):
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    attribution.remember_user_product("tok-A", "tellr-app-aaaaaaaaaaaa")
    assert attribution.user_product_kwargs("tok-A") == {
        "product": "tellr-app-aaaaaaaaaaaa",
        "product_version": "9.9.9",
    }


def test_label_is_found_from_a_thread_with_no_request_context(monkeypatch):
    """``run_with_timeout`` and the Legacy MCP tool build their clients in a bare thread,
    where the request's ContextVars are not visible: only the token can name the user,
    each token its own."""
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    attribution.remember_user_product("tok-B", "tellr-app-bbbbbbbbbbbb")
    attribution.remember_user_product("tok-C", "tellr-app-cccccccccccc")
    seen = {}

    def run():
        seen["request_user"] = user_context.get_current_user()
        seen["tok-B"] = attribution.user_product_kwargs("tok-B")
        seen["tok-C"] = attribution.user_product_kwargs("tok-C")
        seen["never-seen"] = attribution.user_product_kwargs("never-seen")

    with _request_user("john.doe@example.com"):
        thread = threading.Thread(target=run)
        thread.start()
        thread.join()

    assert seen["request_user"] is None, "the thread must see no request context"
    assert seen["tok-B"] == {"product": "tellr-app-bbbbbbbbbbbb", "product_version": "9.9.9"}
    assert seen["tok-C"] == {"product": "tellr-app-cccccccccccc", "product_version": "9.9.9"}
    assert seen["never-seen"]["product"] == "tellr-app-unknown"


def test_label_falls_back_to_the_request_user_then_unknown(monkeypatch):
    """``john.doe``'s golden hash is pinned by ``test_hash_is_the_sha256_prefix_already_in_use``."""
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    with _request_user("john.doe@example.com"):
        assert attribution.user_product_kwargs("never-seen") == {
            "product": "tellr-app-30f69670bba2",
            "product_version": "9.9.9",
        }
        assert attribution.user_product_kwargs(None)["product"] == "tellr-app-30f69670bba2"
        assert attribution.user_product_kwargs()["product"] == "tellr-app-30f69670bba2"
    assert attribution.user_product_kwargs("never-seen") == {
        "product": "tellr-app-unknown",
        "product_version": "9.9.9",
    }
    assert attribution.user_product_kwargs(None)["product"] == "tellr-app-unknown"
    assert attribution.user_product_kwargs("")["product"] == "tellr-app-unknown"


def test_a_remembered_token_wins_over_the_request_user():
    """The token is whose credentials the client carries, so it names the user first."""
    attribution.remember_user_product("tok-D", "tellr-app-dddddddddddd")
    with _request_user("john.doe@example.com"):
        assert attribution.user_product_kwargs("tok-D")["product"] == "tellr-app-dddddddddddd"


def test_the_token_itself_is_never_kept():
    """Only a SHA-256 of the token is kept: it is the map's key, and nothing else (a
    cache on the key function, a list, a log record) holds on to the token."""
    token = "".join(["dapi-", "super-secret-", "token-0123456789"])  # a fresh object
    references_before = sys.getrefcount(token)

    attribution.remember_user_product(token, "tellr-app-cccccccccccc")
    assert attribution.user_product_kwargs(token)["product"] == "tellr-app-cccccccccccc"

    assert sys.getrefcount(token) == references_before
    assert dict(attribution._token_products) == {
        hashlib.sha256(token.encode()).hexdigest(): "tellr-app-cccccccccccc"
    }
    assert token not in repr(attribution._token_products)


def test_remembered_tokens_are_bounded_and_the_oldest_goes_first():
    """At the cap the oldest token is dropped, one at a time: the newest are always kept.
    Every token the user-client cache can hold at once must fit."""
    from src.core import databricks_client

    cap = attribution._MAX_TOKEN_PRODUCTS
    assert cap >= databricks_client._USER_CLIENT_CACHE_MAX_SIZE
    for n in range(cap + 50):
        attribution.remember_user_product(f"tok-{n}", f"tellr-app-{n:012x}")

    assert len(attribution._token_products) == cap
    newest, oldest_kept = cap + 49, 50
    assert attribution.user_product_kwargs(f"tok-{newest}")["product"] == f"tellr-app-{newest:012x}"
    assert attribution.user_product_kwargs(f"tok-{oldest_kept}")["product"] == (
        f"tellr-app-{oldest_kept:012x}"
    )
    assert attribution.user_product_kwargs("tok-0")["product"] == "tellr-app-unknown"
    assert attribution.user_product_kwargs("tok-49")["product"] == "tellr-app-unknown"


def test_remembering_a_token_again_replaces_its_label_and_keeps_it():
    """A user's client is rebuilt every cache TTL: remembering the token again replaces
    its label without a second entry, and makes it the newest, so an active user is not
    the one dropped at the cap."""
    cap = attribution._MAX_TOKEN_PRODUCTS
    attribution.remember_user_product("tok-active", "tellr-app-ffffffffffff")
    attribution.remember_user_product("tok-active", "tellr-app-aaaaaaaaaaaa")
    assert len(attribution._token_products) == 1
    assert attribution.user_product_kwargs("tok-active")["product"] == "tellr-app-aaaaaaaaaaaa"

    for n in range(cap - 1):
        attribution.remember_user_product(f"tok-{n}", "tellr-app-dddddddddddd")
    attribution.remember_user_product("tok-active", "tellr-app-aaaaaaaaaaaa")
    attribution.remember_user_product("tok-one-past-the-cap", "tellr-app-eeeeeeeeeeee")

    assert len(attribution._token_products) == cap
    assert attribution.user_product_kwargs("tok-active")["product"] == "tellr-app-aaaaaaaaaaaa"
    assert attribution.user_product_kwargs("tok-0")["product"] == "tellr-app-unknown"


class _NetworkAttemptedError(Exception):
    """Not an ``OSError``: the SDK retries a connection error for minutes, this it does not."""


def test_user_product_kwargs_makes_no_network_call(monkeypatch):
    """No lookup of the user (``/Me``, a new client) is made to label a client. The
    attempts are recorded, not only refused: a broad ``except`` cannot hide one. A host
    and a token are set so that a client built to ask would really try to connect.
    Only this test's thread is watched: a thread another test left running keeps its
    network."""
    attempts = []
    this_thread = threading.current_thread()

    def _tripwire(real):
        def _no_network(*args, **kwargs):
            if threading.current_thread() is not this_thread:
                return real(*args, **kwargs)
            attempts.append(args)
            raise _NetworkAttemptedError("this test allows no network")

        return _no_network

    for owner, name in (
        (socket, "getaddrinfo"),
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
    ):
        monkeypatch.setattr(owner, name, _tripwire(getattr(owner, name)))
    monkeypatch.setenv("DATABRICKS_HOST", "https://unit.invalid")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-unit")
    attribution.remember_user_product("tok-E", "tellr-app-eeeeeeeeeeee")

    products = [
        attribution.user_product_kwargs(token)["product"] for token in ("tok-E", "never-seen", None)
    ]
    with _request_user("john.doe@example.com"):
        products.append(attribution.user_product_kwargs("never-seen")["product"])

    assert attempts == []
    assert products == [
        "tellr-app-eeeeeeeeeeee",
        "tellr-app-unknown",
        "tellr-app-unknown",
        "tellr-app-30f69670bba2",
    ]


class _UnreadableRequestUser:
    """Stands in for the request-user ContextVar: reading it raises."""

    def get(self, *args):
        raise RuntimeError("request context unreadable")

    def set(self, value):
        raise RuntimeError("request context unreadable")


def test_user_product_kwargs_never_raises(monkeypatch):
    """A label never fails a request: an unreadable request user is no user."""
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    attribution.remember_user_product("tok-F", "tellr-app-ffffffffffff")
    monkeypatch.setattr(user_context, "_current_user_var", _UnreadableRequestUser())

    assert attribution.user_product_kwargs("tok-F") == {
        "product": "tellr-app-ffffffffffff",
        "product_version": "9.9.9",
    }
    assert attribution.user_product_kwargs("never-seen") == {
        "product": "tellr-app-unknown",
        "product_version": "9.9.9",
    }
    assert attribution.user_product_kwargs(None)["product"] == "tellr-app-unknown"


def test_mcp_user_agent_leads_with_tellr(monkeypatch):
    import httpx

    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    assert attribution.mcp_user_agent() == f"tellr/9.9.9 python-httpx/{httpx.__version__}"
