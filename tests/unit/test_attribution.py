"""The labels Tellr puts on its own requests: product, version, never content."""

import re
import sys
import types
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


def _broken(name):
    raise RuntimeError("broken metadata")


def _source_tree_version():
    """What the source tree says: its generated ``_version.py`` if built, else ``__init__``'s."""
    try:
        from src._version import version
    except ImportError:
        from src import __version__ as version
    return version


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
