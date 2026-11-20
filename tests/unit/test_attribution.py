"""The labels Tellr puts on its own requests: product, version, never content."""

import contextvars
import hashlib
import re
import socket
import sys
import threading
import types
from collections import UserString
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


def test_remembering_a_token_again_replaces_its_label_and_makes_it_the_newest():
    """A user's client is rebuilt every cache TTL: remembering the token again replaces
    its label without a second entry, and makes it the newest, so an active user is not
    the one dropped at the cap.  ``tok-active`` is remembered again below the cap, from
    the middle of the map: only that refresh moves it behind ``tok-idle``."""
    cap = attribution._MAX_TOKEN_PRODUCTS
    attribution.remember_user_product("tok-first", "tellr-app-111111111111")
    attribution.remember_user_product("tok-active", "tellr-app-ffffffffffff")
    attribution.remember_user_product("tok-idle", "tellr-app-bbbbbbbbbbbb")
    attribution.remember_user_product("tok-active", "tellr-app-aaaaaaaaaaaa")

    assert len(attribution._token_products) == 3
    assert attribution.user_product_kwargs("tok-active")["product"] == "tellr-app-aaaaaaaaaaaa"

    for n in range(cap - 1):  # two past the cap: the two oldest are dropped
        attribution.remember_user_product(f"tok-{n}", "tellr-app-dddddddddddd")

    assert len(attribution._token_products) == cap
    assert attribution.user_product_kwargs("tok-active")["product"] == "tellr-app-aaaaaaaaaaaa"
    assert attribution.user_product_kwargs("tok-first")["product"] == "tellr-app-unknown"
    assert attribution.user_product_kwargs("tok-idle")["product"] == "tellr-app-unknown"


def test_remembering_a_token_again_at_the_cap_drops_no_other_token():
    """At the cap, a token already remembered takes no new room: every other entry stays."""
    cap = attribution._MAX_TOKEN_PRODUCTS
    for n in range(cap):
        attribution.remember_user_product(f"tok-{n}", "tellr-app-dddddddddddd")
    attribution.remember_user_product("tok-5", "tellr-app-eeeeeeeeeeee")

    assert len(attribution._token_products) == cap
    assert attribution.user_product_kwargs("tok-5")["product"] == "tellr-app-eeeeeeeeeeee"
    dropped = [
        n
        for n in range(cap)
        if n != 5
        and attribution.user_product_kwargs(f"tok-{n}")["product"] != "tellr-app-dddddddddddd"
    ]
    assert dropped == []


def _while_the_lock_is_held(action, observe):
    """Run ``action`` in a thread while this thread holds the map's lock.

    Returns whether the thread was still waiting after 0.2 s, what ``observe()`` saw
    while the lock was held, and the thread, finished once the lock is released.  With
    the lock in place the thread cannot finish early, so this cannot fail falsely.
    """
    worker = threading.Thread(target=action)
    with attribution._token_products_lock:
        worker.start()
        worker.join(timeout=0.2)
        waiting = worker.is_alive()
        observed = observe()
    worker.join(timeout=5)
    return waiting, observed, worker


def test_remembering_a_token_waits_for_the_maps_lock():
    waiting, map_while_held, worker = _while_the_lock_is_held(
        lambda: attribution.remember_user_product("tok-L", "tellr-app-111111111111"),
        observe=lambda: dict(attribution._token_products),
    )

    assert waiting, "remember_user_product wrote the map without its lock"
    assert map_while_held == {}
    assert not worker.is_alive()
    assert attribution.user_product_kwargs("tok-L")["product"] == "tellr-app-111111111111"


def test_looking_a_token_up_waits_for_the_maps_lock():
    attribution.remember_user_product("tok-R", "tellr-app-222222222222")
    answered = {}

    waiting, answered_while_held, worker = _while_the_lock_is_held(
        lambda: answered.update(attribution.user_product_kwargs("tok-R")),
        observe=lambda: dict(answered),
    )

    assert waiting, "user_product_kwargs read the map without its lock"
    assert answered_while_held == {}
    assert not worker.is_alive()
    assert answered["product"] == "tellr-app-222222222222"


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


@pytest.mark.parametrize(
    "token",
    [object(), b"tok", UserString("tok"), "", "tok-\ud800"],
    ids=["object", "bytes", "str-like", "empty-str", "unencodable-str"],
)
def test_a_token_that_is_not_a_usable_string_is_no_token(monkeypatch, token):
    """Neither function raises on such a token: nothing is remembered for it, and its
    label falls back as for no token, to the request user and then ``tellr-app-unknown``.
    Only a ``str`` counts, even one whose stand-in (``UserString``) would encode."""
    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))

    attribution.remember_user_product(token, "tellr-app-ffffffffffff")

    assert attribution._token_products == {}
    assert attribution.user_product_kwargs(token) == {
        "product": "tellr-app-unknown",
        "product_version": "9.9.9",
    }
    with _request_user("john.doe@example.com"):
        assert attribution.user_product_kwargs(token)["product"] == "tellr-app-30f69670bba2"


def test_a_request_user_that_cannot_be_hashed_is_no_user():
    """The request user is hashed under the same protection it is read under."""
    with _request_user(object()):
        assert attribution.user_product_kwargs(None)["product"] == "tellr-app-unknown"
        assert attribution.user_product_kwargs("never-seen")["product"] == "tellr-app-unknown"


def test_mcp_user_agent_leads_with_tellr(monkeypatch):
    import httpx

    monkeypatch.setattr(attribution.metadata, "version", _installed("9.9.9"))
    assert attribution.mcp_user_agent() == f"tellr/9.9.9 python-httpx/{httpx.__version__}"


# ---------------------------------------------------------------------------
# The turn's entrypoint: how a chat turn reached Tellr (its UI, or its MCP server)
# ---------------------------------------------------------------------------

#: Spelled out: a test that read them from ``ENTRYPOINTS`` would follow a changed list.
ALL_ENTRYPOINTS = ("app", "mcp")


class _Impostor(str):
    """Free text posing as an allowed name: its hash and its equality are the name's.

    ``impostor in frozenset({name})`` is ``True``, yet ``json.dumps`` writes its own
    text, so a membership test alone would let that text into a label.
    """

    def __new__(cls, text: str, posing_as: str) -> "_Impostor":
        impostor = super().__new__(cls, text)
        impostor.posing_as = posing_as
        return impostor

    def __hash__(self) -> int:
        return hash(self.posing_as)

    def __eq__(self, other: object) -> bool:
        return other == self.posing_as

    def __ne__(self, other: object) -> bool:
        return other != self.posing_as


#: Values a turn's entrypoint must never be: each is ignored, and none raises.
OFF_LIST_ENTRYPOINTS = [
    pytest.param("cron", id="unknown-name"),
    pytest.param("App", id="wrong-case"),
    pytest.param("MCP", id="upper-case"),
    pytest.param(" app", id="leading-space"),
    pytest.param("mcp\n", id="trailing-newline"),
    pytest.param("", id="empty"),
    pytest.param("a prompt someone typed", id="free-text"),
    pytest.param("app,mcp", id="two-names"),
    pytest.param(None, id="none"),
    pytest.param(1, id="int"),
    pytest.param(True, id="bool"),
    pytest.param(b"app", id="bytes"),
    pytest.param(UserString("app"), id="str-like"),
    pytest.param(["app"], id="unhashable-list"),
    pytest.param({"entrypoint": "mcp"}, id="unhashable-dict"),
]


def test_the_entrypoints_are_exactly_app_and_mcp():
    assert attribution.ENTRYPOINTS == frozenset(ALL_ENTRYPOINTS)
    assert type(attribution.ENTRYPOINTS) is frozenset


def test_entrypoint_is_unset_by_default_and_ignores_values_off_the_list():
    """A value off the list changes nothing: it neither sets nor clears the turn's value."""
    seen = []

    def turn():
        seen.append(attribution.get_entrypoint())
        attribution.set_entrypoint("cron")
        seen.append(attribution.get_entrypoint())
        attribution.set_entrypoint("mcp")
        seen.append(attribution.get_entrypoint())
        attribution.set_entrypoint("cron")
        seen.append(attribution.get_entrypoint())
        attribution.set_entrypoint("app")
        seen.append(attribution.get_entrypoint())

    contextvars.copy_context().run(turn)

    assert seen == [None, None, "mcp", "mcp", "app"]
    assert attribution.get_entrypoint() is None


@pytest.mark.parametrize("value", OFF_LIST_ENTRYPOINTS)
def test_an_entrypoint_off_the_list_is_ignored_and_never_raises(value):
    """A label never fails a request: an unhashable value, or a ``str`` stand-in equal to
    ``"app"``, is ignored like any other value off the list (only a ``str`` counts)."""

    def turn():
        attribution.set_entrypoint(value)
        before = attribution.get_entrypoint()
        attribution.set_entrypoint("mcp")
        attribution.set_entrypoint(value)
        return before, attribution.get_entrypoint()

    assert contextvars.copy_context().run(turn) == (None, "mcp")


@pytest.mark.parametrize("posing_as", ALL_ENTRYPOINTS)
def test_free_text_posing_as_an_entrypoint_is_never_kept(posing_as):
    impostor = _Impostor("a prompt someone typed", posing_as)
    assert impostor in frozenset(ALL_ENTRYPOINTS)  # precondition: it fools a membership test

    def turn():
        attribution.set_entrypoint(impostor)
        return attribution.get_entrypoint()

    kept = contextvars.copy_context().run(turn)

    assert kept is None or (type(kept) is str and kept == posing_as), (
        f"the entrypoint kept {kept!r}, a {type(kept).__name__}"
    )


def test_a_turns_entrypoint_stays_in_its_own_context():
    """Each turn marks its entrypoint in its own context (a request's task, the job's copy
    of it): no other turn, not one started later, and not the code around it, sees it."""
    turn = contextvars.copy_context()
    sibling = contextvars.copy_context()

    turn.run(attribution.set_entrypoint, "mcp")
    later = contextvars.copy_context()

    assert turn.run(attribution.get_entrypoint) == "mcp"
    assert sibling.run(attribution.get_entrypoint) is None
    assert later.run(attribution.get_entrypoint) is None
    assert attribution.get_entrypoint() is None


def test_a_turns_entrypoint_reaches_a_thread_only_through_a_copied_context():
    """The chat service copies the job's context for its graph and title threads: such a
    thread sees the turn's entrypoint, and what it sets stays in its copy.  A bare thread
    starts with none, as for every ContextVar."""
    seen = {}

    def turn():
        attribution.set_entrypoint("app")

        def bare():
            seen["bare thread"] = attribution.get_entrypoint()

        def copied():
            seen["copied context"] = attribution.get_entrypoint()
            attribution.set_entrypoint("mcp")

        thread = threading.Thread(target=bare)
        thread.start()
        thread.join()
        context = contextvars.copy_context()
        thread = threading.Thread(target=lambda: context.run(copied))
        thread.start()
        thread.join()
        seen["spawner, after"] = attribution.get_entrypoint()

    contextvars.copy_context().run(turn)

    assert seen == {"bare thread": None, "copied context": "app", "spawner, after": "app"}
