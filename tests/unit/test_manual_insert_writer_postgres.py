"""``SessionManager.insert_slide`` on real PostgreSQL (#314 follow-up, Task 2).

The SQLite suite (``test_manual_insert_writer.py``) owns the behaviour.  This file
repeats the cases whose correctness depends on the engine:

* the insert at 1: in-place UPDATEs under the ``(session_id, position)`` primary key,
  the one INSERT that must not collide on the globally UNIQUE ``id``, the evidence
  row's constraints and naive-timestamp round trips;
* the live arc-review claim, read ``FOR UPDATE`` on the OWNER's deck row (a no-op on
  SQLite) and refused for a contributor session;
* the M2 refusal: a turn on the owner's session while a contributor inserts, with
  the naive-UTC cutoff compared on a ``TIMESTAMP WITHOUT TIME ZONE`` column;
* the row-less legacy deck (C7, supervisor's ruling), whose rows are materialised and
  then rewritten in the same transaction, and whose refusal must roll the
  materialisation back on a real transaction.

Each test gets a throwaway database built with ``create_all`` + ``_run_migrations``
(production ordering), dropped afterwards.  Pattern:
``tests/unit/test_insert_pending_slides_postgres.py``.  CI provisions the server;
locally the suite self-skips.
"""
from __future__ import annotations

import json
import os
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import src.api.services.session_manager as session_manager
import src.database.models  # noqa: F401 — register every ORM model
from src.api.services.chat_service import ArcReviewInFlightError
from src.core.database import Base, _run_migrations
from tests.unit.test_manual_insert_writer import (
    CONTRIB_SID,
    EVENT_TYPE,
    INSERTER,
    LAYOUT_AT_1,
    NEW_SID,
    OWNER_SID,
    _assert_every_old_row_intact,
    _assert_new_row,
    _assert_unchanged,
    _blank_entry,
    _by_marker,
    _cached_legacy_deck,
    _db_state,
    _deck,
    _expected_legacy_rows,
    _identity,
    _insert,
    _insert_legacy,
    _insert_six,
    _layout,
    _mutation_events,
    _rows,
    _seed_legacy,
    _seed_six,
    _set_claim,
    _set_processing,
    _usage_events,
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
            "the manual-insert writer Postgres suite",
        )
    db_name = f"tellr_manualinsert_{uuid.uuid4().hex[:16]}"
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


def test_insert_at_1_on_postgres(factory):
    seed, before, result = _insert_six(factory, 1)
    after = _rows(factory, seed["owner_pk"])

    assert _layout(after) == LAYOUT_AT_1
    assert [r["position"] for r in after] == list(range(7))
    _assert_every_old_row_intact(before, after)
    _assert_new_row(after[1])
    assert len({r["id"] for r in after}) == 7, "two rows share the globally UNIQUE id"
    assert result["position"] == 1 and result["slide_id"] == NEW_SID

    deck = _deck(factory, seed["owner_pk"])
    assert deck.version == 6 and deck.slide_count == 7
    spec = json.loads(deck.deck_spec_json)
    assert spec["slides"][1] == _blank_entry(1)
    assert [e["position"] for e in spec["slides"]] == list(range(7))
    assert _mutation_events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"], NEW_SID)
    ]
    assert _usage_events(factory) == [(EVENT_TYPE, INSERTER, seed["owner_pk"])]


def test_a_live_claim_on_the_owners_deck_refuses_a_contributor_on_postgres(factory):
    seed = _seed_six(factory, contributors=1)
    before = _rows(factory, seed["owner_pk"])
    _set_claim(factory, seed["owner_pk"], claim_age_seconds=10)
    state = _db_state(factory)

    with pytest.raises(ArcReviewInFlightError):
        _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=CONTRIB_SID)
    _assert_unchanged(factory, state)


def test_an_owner_turn_refuses_a_contributor_insert_on_postgres(factory):
    seed = _seed_six(factory, contributors=1)
    before = _rows(factory, seed["owner_pk"])
    _set_processing(factory, OWNER_SID, 10)
    state = _db_state(factory)

    with pytest.raises(session_manager.DeckBusyError):
        _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=CONTRIB_SID)
    _assert_unchanged(factory, state)

    # A stale lock (> 300 s) on the same deck proceeds.
    _set_processing(factory, OWNER_SID, 310)
    _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=CONTRIB_SID)
    assert _layout(_rows(factory, seed["owner_pk"])) == LAYOUT_AT_1


def test_a_row_less_legacy_deck_on_postgres(factory):
    seed = _seed_legacy(factory)
    cached = _cached_legacy_deck(factory)

    _insert_legacy(factory, 2, seed, cached)
    after = _rows(factory, seed["owner_pk"])

    assert _layout(after) == ["MK-LEGACYONE", "MK-LEGACYTWO", "NEW", "MK-LEGACYTHREE"]
    expected = _expected_legacy_rows(seed["owner_pk"])
    for marker, row in _by_marker(after).items():
        assert _identity(row) == expected[marker], marker
    _assert_new_row(after[2])
    assert len({r["id"] for r in after}) == 4


def test_a_refused_legacy_insert_leaves_no_rows_on_postgres(factory):
    seed = _seed_legacy(factory)
    cached = _cached_legacy_deck(factory)
    state = _db_state(factory)

    def _refuse(*args, **kwargs):
        raise RuntimeError("evidence write refused")

    with patch.object(session_manager, "record_shared_deck_mutation", _refuse):
        with pytest.raises(RuntimeError, match="evidence write refused"):
            _insert_legacy(factory, 2, seed, cached)
    assert _rows(factory, seed["owner_pk"]) == []
    _assert_unchanged(factory, state)

