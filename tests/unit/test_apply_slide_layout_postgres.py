"""``SlideWriter.apply_slide_layout`` on real PostgreSQL (Task 3).

The SQLite suite (``tests/unit/test_apply_slide_layout.py``) owns the behaviour.
This file repeats the two cases whose correctness depends on the engine:

* the mixed layout (move, delete and insert in one transaction).  It does in-place
  UPDATEs under the ``(session_id, position)`` primary key, INSERTs that must not
  collide on the globally UNIQUE ``id``, a DELETE of the row beyond the new count,
  the evidence row's constraints, and naive-timestamp round-trips;
* one refused layout rolling back on a real transaction.

Each test gets a throwaway database built with ``create_all`` + ``_run_migrations``
(production ordering), dropped afterwards.  The pattern is
``tests/unit/test_insert_pending_slides_postgres.py``.  CI provisions the server;
locally the suite self-skips.
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
from tests.unit.test_apply_slide_layout import (
    FOUR,
    MIXED,
    _apply,
    _check_mixed_layout,
    _expected_rows,
    _mutation,
    _rows,
    _run,
    _seed_rows,
    _spec_json,
    _state,
    _with_hash_changed,
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
            "the apply-slide-layout Postgres suite",
        )
    db_name = f"tellr_applylayout_{uuid.uuid4().hex[:16]}"
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


def test_mixed_layout_on_postgres(factory):
    run = _run(factory, FOUR, MIXED, "save_deck_slides")
    _check_mixed_layout(factory, run)
    assert len({r["id"] for r in run["after"]}) == 5, "two rows share the globally UNIQUE id"


def test_expected_rows_mismatch_writes_nothing_on_postgres(factory):
    seed = _seed_rows(factory, FOUR)
    before = _rows(factory, seed["owner_pk"])
    state = _state(factory)

    with pytest.raises(slide_repository.SlideRowsChangedError):
        _apply(
            factory,
            MIXED,
            deck_spec=_spec_json(5, title="Laid out"),
            expected_rows=_with_hash_changed(before),
            mutation=_mutation("save_deck_slides", release_id=seed["release_id"]),
        )
    assert _state(factory) == state, "a refused layout wrote something"
    assert _expected_rows(_rows(factory, seed["owner_pk"])) == _expected_rows(before)
