"""An unindexable design-system NAME must be a clear 4xx on EVERY write path.

``design_system.name`` is unbounded ``TEXT`` (brand text is never capped or
truncated) carrying a UNIQUE constraint, so it is backed by a btree index whose
per-entry tuple cannot exceed 2704 bytes. A name that overflows it raises
``ProgramLimitExceeded`` from inside the INSERT/UPDATE — the right direction (it
fails loudly and never truncates), but it landed in each route's generic
``except Exception`` and surfaced as **HTTP 500**, which tells a user nothing
they can act on. A 500 on a legitimate upload is a bug.

The previous attempt PREDICTED the outcome: it ran ``zlib.compress`` as a stand-in
for Postgres's pglz and rejected a name whose compressed size still exceeded the
limit. Prediction is the wrong shape, and measurably wrong. The compressed size of
the NAME is not the size of the INDEX TUPLE — Postgres does not pglz-compress a
btree key into the index at all — so the guard let through everything it thought
compressed well enough:

    nbytes   zlib     guard   postgres
      2700   2048      pass   REJECTED: index row size 2712 exceeds btree ... 2704
      3000   2274      pass   REJECTED: index row size 3016 exceeds btree ... 2704
      3500   2652      pass   REJECTED: index row size 3512 exceeds btree ... 2704

so a 2700-byte name still produced the 500 the guard existed to prevent. It was
also never CALLED on create or rename — only on import.

So the database is the authority and the code REACTS: the real error is caught at
the DB boundary and translated into a 4xx naming the field and the practical limit.
Nothing is predicted, nothing is truncated, and a long-but-compressible name (which
Postgres genuinely stores, because a repetitive value is compressed in the HEAP and
the index key is the same bytes either way) still succeeds.

GATING: requires a reachable PostgreSQL, because this behaviour cannot be observed
on SQLite — it has no btree index-row limit, so every one of these names stores
happily there. That is exactly how the 500 survived a green suite.

All fixtures SYNTHETIC (invented brand names).
"""

import os
import random
import string
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 - register every model with Base.metadata
from src.api.main import app
from src.core.database import Base, get_db
from tests.unit.conftest_design_system import make_bundle_zip

pytestmark = pytest.mark.postgres

_ADMIN_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL",
    "postgresql+psycopg2://localhost:5432/postgres",
)

BASE = "/api/settings/design-systems"

#: Largest INCOMPRESSIBLE name a live PostgreSQL 14 accepted into the unique index,
#: found by binary search against the real database: 2704 - 12 bytes of index-tuple
#: overhead. Used only to pick test fixtures either side of the boundary; the
#: PRODUCTION code deliberately predicts nothing.
_LARGEST_INDEXABLE_INCOMPRESSIBLE = 2692


def _postgres_available() -> bool:
    try:
        engine = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


if not _postgres_available():  # pragma: no cover - environment-dependent
    pytest.skip(
        f"no PostgreSQL reachable at {_ADMIN_URL}; set TELLR_TEST_POSTGRES_URL to run "
        "the design-system name index-limit suite",
        allow_module_level=True,
    )


def _incompressible(nbytes: int, *, seed: int = 7) -> str:
    """A name pglz genuinely cannot shrink, seeded so the case is deterministic.

    A PATTERNED string will not do: an arithmetic sequence over the alphabet
    compresses to a few hundred bytes, so the HEAP stores it happily and only the
    INDEX complains — a different assertion than the one intended.
    """
    rng = random.Random(seed)
    alphabet = string.ascii_letters + string.digits
    return "".join(rng.choice(alphabet) for _ in range(nbytes))


#: Over the limit and genuinely incompressible: Postgres cannot index it.
_UNINDEXABLE = _incompressible(4000)
#: The same length, but a single repeated character. The name the zlib predictor and
#: the database AGREE is storable, so it must still succeed — never turned away.
_COMPRESSIBLE_LONG = "A" * 4000
#: Just over the boundary. The zlib predictor PASSED this one and Postgres rejected
#: it, which is the specific 500 this fix exists to remove.
_JUST_OVER = _incompressible(2700, seed=11)


@pytest.fixture()
def pg_engine():
    """A fresh PostgreSQL database with the real schema, dropped afterwards."""
    db_name = f"tellr_dsname_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    engine = create_engine(make_url(_ADMIN_URL).set(database=db_name))
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin.dispose()


@pytest.fixture()
def client(pg_engine):
    """A TestClient whose ``get_db`` yields a session on the REAL PostgreSQL, so
    routes meet the actual index and the actual error."""
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _assert_actionable_4xx(resp, *, path):
    """A 4xx whose message names the FIELD and gives a usable bound."""
    assert 400 <= resp.status_code < 500, (
        f"{path}: an unindexable name must be a client error, got "
        f"{resp.status_code}: {resp.text[:400]}"
    )
    detail = str(resp.json().get("detail", "")).lower()
    assert "name" in detail, f"{path}: the message must name the field: {detail!r}"
    assert any(token in detail for token in ("too long", "2692", "2704", "shorter")), (
        f"{path}: the message must give the user a bound to get under: {detail!r}"
    )
    # It must not leak the raw driver error as the user-facing message.
    assert "psycopg2" not in detail and "traceback" not in detail, (
        f"{path}: raw driver internals leaked to the caller: {detail!r}"
    )


def _stored_names(pg_engine):
    with pg_engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT name FROM design_system"))]


def _assert_nothing_truncated(pg_engine, *, expected):
    """Whatever is stored must be stored WHOLE. Truncation is never the answer."""
    for name in _stored_names(pg_engine):
        assert name in expected, (
            f"a stored name is not one that was submitted whole (len={len(name)}) — "
            "it was truncated"
        )


# ---------------------------------------------------------------------------
# Path 1 — import
# ---------------------------------------------------------------------------


class TestImportPath:
    def _import(self, client, *, name):
        return client.post(
            f"{BASE}/import",
            files={"file": ("synthetic.zip", make_bundle_zip(), "application/zip")},
            data={"name": name},
        )

    def test_unindexable_name_is_4xx_not_500(self, client, pg_engine):
        _assert_actionable_4xx(self._import(client, name=_UNINDEXABLE), path="import")
        _assert_nothing_truncated(pg_engine, expected={_UNINDEXABLE})

    def test_name_just_over_the_boundary_is_4xx_not_500(self, client, pg_engine):
        """The exact case the zlib predictor waved through into a 500."""
        _assert_actionable_4xx(self._import(client, name=_JUST_OVER), path="import")

    def test_compressible_long_name_still_succeeds(self, client, pg_engine):
        resp = self._import(client, name=_COMPRESSIBLE_LONG)
        assert resp.status_code == 201, (
            f"a long-but-storable name must not be turned away: {resp.text[:300]}"
        )
        assert resp.json()["name"] == _COMPRESSIBLE_LONG, "the name must not be altered"
        assert _stored_names(pg_engine) == [_COMPRESSIBLE_LONG]


# ---------------------------------------------------------------------------
# Path 2 — create
# ---------------------------------------------------------------------------


class TestCreatePath:
    def _create(self, client, *, name):
        return client.post(BASE, json={"name": name, "description": "synthetic"})

    def test_unindexable_name_is_4xx_not_500(self, client, pg_engine):
        """The guard was never even called here — create went straight to a 500."""
        _assert_actionable_4xx(self._create(client, name=_UNINDEXABLE), path="create")
        _assert_nothing_truncated(pg_engine, expected={_UNINDEXABLE})

    def test_name_just_over_the_boundary_is_4xx_not_500(self, client):
        _assert_actionable_4xx(self._create(client, name=_JUST_OVER), path="create")

    def test_compressible_long_name_still_succeeds(self, client, pg_engine):
        resp = self._create(client, name=_COMPRESSIBLE_LONG)
        assert resp.status_code == 201, (
            f"a long-but-storable name must not be turned away: {resp.text[:300]}"
        )
        assert resp.json()["name"] == _COMPRESSIBLE_LONG
        assert _stored_names(pg_engine) == [_COMPRESSIBLE_LONG]


# ---------------------------------------------------------------------------
# Path 3 — rename
# ---------------------------------------------------------------------------


class TestRenamePath:
    def _seed(self, client):
        resp = client.post(BASE, json={"name": "Synthetic Brand", "description": "seed"})
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def _rename(self, client, ds_id, *, name):
        return client.put(f"{BASE}/{ds_id}", json={"name": name})

    def test_unindexable_name_is_4xx_not_500(self, client, pg_engine):
        """Rename never called the guard either, and here the row already EXISTS —
        so the failing UPDATE must leave the original name intact."""
        ds_id = self._seed(client)

        _assert_actionable_4xx(self._rename(client, ds_id, name=_UNINDEXABLE), path="rename")

        assert _stored_names(pg_engine) == ["Synthetic Brand"], (
            "a rejected rename must leave the stored name untouched"
        )

    def test_name_just_over_the_boundary_is_4xx_not_500(self, client):
        ds_id = self._seed(client)
        _assert_actionable_4xx(self._rename(client, ds_id, name=_JUST_OVER), path="rename")

    def test_compressible_long_name_still_succeeds(self, client, pg_engine):
        ds_id = self._seed(client)
        resp = self._rename(client, ds_id, name=_COMPRESSIBLE_LONG)
        assert resp.status_code == 200, (
            f"a long-but-storable rename must not be turned away: {resp.text[:300]}"
        )
        assert resp.json()["name"] == _COMPRESSIBLE_LONG
        assert _stored_names(pg_engine) == [_COMPRESSIBLE_LONG]


# ---------------------------------------------------------------------------
# The predictor itself must be gone
# ---------------------------------------------------------------------------


class TestPredictionIsGone:
    def test_the_service_no_longer_predicts_the_compressor(self):
        """A guess about what pglz will do cannot be right, so none is made.

        Asserted on the module's own AST rather than on its text: the docstrings
        DISCUSS zlib (explaining why prediction was removed, so the next round does
        not reintroduce it), and a substring search cannot tell a warning apart from
        a call. What must be absent is the IMPORT and the CALL.
        """
        import ast
        import inspect as inspect_module

        from src.services import design_system_service

        tree = ast.parse(inspect_module.getsource(design_system_service))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "zlib" not in imported, (
            "design_system_service imports zlib again — it is predicting Postgres's "
            "compressor instead of reacting to the database's own error"
        )

        attribute_calls = {
            f"{node.func.value.id}.{node.func.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        }
        assert not {call for call in attribute_calls if call.startswith("zlib.")}, (
            f"a zlib call is back in design_system_service: {attribute_calls}"
        )

    def test_the_real_boundary_is_measured_not_assumed(self, pg_engine):
        """Pin the fixtures to what the LIVE database does, so this suite cannot
        drift into testing a guess of its own."""
        with pg_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO design_system (name, version, published, is_default, "
                     "is_active, created_at, updated_at) VALUES (:n, 1, FALSE, FALSE, "
                     "TRUE, NOW(), NOW())"),
                {"n": _COMPRESSIBLE_LONG},
            )
        assert _stored_names(pg_engine) == [_COMPRESSIBLE_LONG], (
            "the compressible name must store EXACTLY — if this fails the fixture, "
            "not the product, is wrong"
        )

        for label, name in (("unindexable", _UNINDEXABLE), ("just over", _JUST_OVER)):
            with pytest.raises(Exception) as excinfo:
                with pg_engine.begin() as conn:
                    conn.execute(
                        text("INSERT INTO design_system (name, version, published, "
                             "is_default, is_active, created_at, updated_at) VALUES "
                             "(:n, 1, FALSE, FALSE, TRUE, NOW(), NOW())"),
                        {"n": name},
                    )
            assert "index row size" in str(excinfo.value), (
                f"the {label} fixture must be one Postgres genuinely cannot index, "
                f"got: {excinfo.value}"
            )

        assert len(_UNINDEXABLE) > _LARGEST_INDEXABLE_INCOMPRESSIBLE
        assert len(_JUST_OVER) > _LARGEST_INDEXABLE_INCOMPRESSIBLE
