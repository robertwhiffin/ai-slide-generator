"""``SlideWriter.insert_pending_slides`` on real PostgreSQL (#314, Task 2).

The SQLite suite (``test_insert_pending_slides.py``) owns the behaviour.  This file
repeats the two cases whose correctness depends on the engine: the [1, 3] shift
(in-place UPDATEs under the ``(session_id, position)`` primary key, INSERTs that
must not collide on the globally UNIQUE ``id``, the evidence row's constraints and
naive-timestamp round-trips) and one refused shift rolling back on a real
transaction.

Each test gets a throwaway database built with ``create_all`` + ``_run_migrations``
(production ordering), dropped afterwards.  Pattern:
``tests/unit/test_spec_dirty_marker.py`` (the ``pg_engine_with_dirty_marker``
fixture).  CI provisions the server; locally the suite self-skips.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import src.api.services.slide_repository as slide_repository
import src.database.models  # noqa: F401 — register every ORM model
from src.core.database import Base, _run_migrations
from tests.unit.test_insert_pending_slides import (
    _assert_every_old_row_intact,
    _assert_pending,
    _db_state,
    _deck,
    _events,
    _expected_rows,
    _insert,
    _layout,
    _mangle_hash,
    _rows,
    _seed_six,
    _shift_six,
    _spec_json,
)

pytestmark = pytest.mark.postgres

_PG_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL",
    "postgresql+psycopg2://localhost:5432/postgres",
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_PG_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


_PG_REACHABLE = _postgres_available()


@pytest.fixture()
def factory():
    """A fresh PostgreSQL database with the full Tellr schema, dropped afterwards."""
    if not _PG_REACHABLE:
        pytest.skip(
            f"no PostgreSQL reachable at {_PG_URL}; set TELLR_TEST_POSTGRES_URL to run "
            "the insert-pending-slides Postgres suite",
        )
    db_name = f"tellr_insertpending_{uuid.uuid4().hex[:16]}"
    admin = create_engine(_PG_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    engine = create_engine(make_url(_PG_URL).set(database=db_name))
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    try:
        yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
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


def test_insert_at_1_and_3_on_postgres(factory):
    seed, before, ids, t0, t1, new_spec = _shift_six(factory)
    after = _rows(factory, seed["owner_pk"])

    assert _layout(after) == [
        "MK-ALPHA", "PENDING", "MK-FAILED", "PENDING",
        "MK-BRAVO", "MK-BACKFILL", "MK-CHARLIE", "MK-DELTA",
    ]
    assert [r["position"] for r in after] == list(range(8))
    _assert_every_old_row_intact(before, after)
    for position in (1, 3):
        _assert_pending(after[position], t0, t1)
    assert ids == [after[1]["slide_id"], after[3]["slide_id"]]
    assert len({r["id"] for r in after}) == 8, "two rows share the globally UNIQUE id"

    deck = _deck(factory, seed["owner_pk"])
    assert deck.deck_spec_json == new_spec
    assert deck.version == 6
    assert deck.slide_count == 6
    assert _events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"])
    ]


def test_a_changed_row_refuses_the_shift_on_postgres(factory):
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)

    with pytest.raises(slide_repository.SlideRowsChangedError):
        _insert(
            factory,
            [1, 3],
            deck_spec=_spec_json(8, title="Shifted"),
            expected_rows=_mangle_hash(before),
            release_id=seed["release_id"],
        )
    assert _db_state(factory) == state, "a refused shift wrote something"
    assert _expected_rows(_rows(factory, seed["owner_pk"])) == _expected_rows(before)
