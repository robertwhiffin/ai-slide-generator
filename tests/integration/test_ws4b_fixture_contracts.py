"""B1.7 contract tests for the four integration-scoped fixtures.

Exercises every declared surface of:
  sqlite_engine_file_backed  — cross-process shared database
  stub_writer                — SlideWriter call-order recorder
  partial_deck               — land / placehold / session_id
  released_deck              — session_id with committed ascending prefix
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401
from src.api.services.slide_repository import SlideWriter
from src.core.database import Base, _run_migrations
from src.database.models.session import SessionSlide, UserSession

_REPO_ROOT = str(Path(__file__).parents[2])


# ---------------------------------------------------------------------------
# sqlite_engine_file_backed
# ---------------------------------------------------------------------------


class TestSqliteEngineFileBacked:
    def test_engine_has_deck_tables(self, sqlite_engine_file_backed):
        tables = set(sa_inspect(sqlite_engine_file_backed).get_table_names())
        assert "session_slide_decks" in tables
        assert "session_slides" in tables
        assert "user_sessions" in tables

    def test_engine_is_file_backed_not_memory(self, sqlite_engine_file_backed):
        url = str(sqlite_engine_file_backed.url)
        assert ":memory:" not in url, "Engine must be file-backed, not :memory:"

    def test_file_path_is_accessible(self, sqlite_engine_file_backed):
        """engine.url.database gives the on-disk path — contract for cross-process use."""
        db_path = sqlite_engine_file_backed.url.database
        assert db_path and db_path != ":memory:"
        assert os.path.exists(db_path), f"DB file does not exist: {db_path}"

    def test_two_processes_share_the_database(self, sqlite_engine_file_backed):
        """A row written by a child subprocess is visible in the parent.

        This is the ONLY property that distinguishes sqlite_engine_file_backed
        from sqlite:///:memory:.  An in-memory engine silently passes every
        other test here, so this cross-process assertion is the load-bearing one.
        """
        db_path = sqlite_engine_file_backed.url.database
        sid = f"xproc-{uuid.uuid4().hex[:10]}"

        # Script run in a genuinely separate OS process.
        # Import order: src.core before src.database.models avoids the circular
        # import that occurs in a fresh interpreter (settings_db imports from
        # database.models while database.models is still initialising).
        child_script = f"""
import sys, os
sys.path.insert(0, {_REPO_ROOT!r})
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('DATABRICKS_HOST', 'https://fake.azuredatabricks.net')
os.environ.setdefault('DATABRICKS_TOKEN', 'fake-token')
os.environ.setdefault('ENVIRONMENT', 'test')
import src.core          # must come first to avoid circular import
import src.database.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.models.session import UserSession
engine = create_engine(
    'sqlite:///{db_path}',
    connect_args={{'check_same_thread': False}},
)
factory = sessionmaker(bind=engine)
db = factory()
db.add(UserSession(session_id={sid!r}, created_by='child-proc@example.com'))
db.commit()
db.close()
engine.dispose()
print('CHILD_OK')
"""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c", child_script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Child process failed (exit {result.returncode}):\n{result.stderr[-600:]}"
        )
        assert "CHILD_OK" in result.stdout, (
            f"Expected CHILD_OK in child output; got: {result.stdout!r}"
        )

        # Read back in the parent — confirms the row crossed the process boundary.
        factory = sessionmaker(bind=sqlite_engine_file_backed, expire_on_commit=False)
        db = factory()
        try:
            row = (
                db.query(UserSession)
                .filter(UserSession.session_id == sid)
                .one_or_none()
            )
            assert row is not None, (
                f"Row written by child process not found in parent; "
                f"session_id={sid!r}"
            )
            assert row.created_by == "child-proc@example.com"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# stub_writer
# ---------------------------------------------------------------------------


class TestStubWriter:
    def test_written_positions_exists(self, stub_writer):
        assert hasattr(stub_writer, "written_positions")
        assert isinstance(stub_writer.written_positions, list)

    def test_written_exists(self, stub_writer):
        assert hasattr(stub_writer, "written")
        assert isinstance(stub_writer.written, list)

    def test_placeheld_exists(self, stub_writer):
        assert hasattr(stub_writer, "placeheld")
        assert isinstance(stub_writer.placeheld, list)

    def test_write_slide_records_position_and_html_in_call_order(self, stub_writer):
        """Order is the whole point: the reorder buffer releases in position order."""
        sw = SlideWriter()
        # Simulate builders finishing out of order (2, 0, 1)
        for pos in [2, 0, 1]:
            sw.write_slide(
                session_id="stub-test-session",
                position=pos,
                html=f"<div class='slide'>Slide {pos}</div>",
            )
        assert stub_writer.written_positions == [2, 0, 1], (
            "written_positions must reflect call order, not sorted order"
        )
        assert len(stub_writer.written) == 3
        for i, (pos, html) in enumerate(stub_writer.written):
            assert pos == [2, 0, 1][i]
            assert f"Slide {pos}" in html

    def test_commit_placeholder_records_position(self, stub_writer):
        sw = SlideWriter()
        sw.commit_placeholder(session_id="stub-test-session", position=5)
        assert stub_writer.placeheld == [5]

    def test_written_is_tuples_of_position_html(self, stub_writer):
        sw = SlideWriter()
        sw.write_slide(
            session_id="stub-test-session",
            position=3,
            html="<div class='slide'>X</div>",
        )
        assert len(stub_writer.written) == 1
        pos, html = stub_writer.written[0]
        assert pos == 3
        assert "X" in html


# ---------------------------------------------------------------------------
# partial_deck
# ---------------------------------------------------------------------------


class TestPartialDeck:
    def test_session_id_is_string(self, partial_deck):
        assert isinstance(partial_deck.session_id, str)
        assert partial_deck.session_id

    def test_land_writes_slides(self, partial_deck):
        partial_deck.land(positions=[0, 1])
        # Verify rows exist in the DB via the engine
        factory = sessionmaker(
            bind=partial_deck._engine, expire_on_commit=False
        )
        db = factory()
        try:
            owner_id = (
                db.query(UserSession)
                .filter(UserSession.session_id == partial_deck.session_id)
                .one()
                .id
            )
            rows = (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == owner_id)
                .order_by(SessionSlide.position)
                .all()
            )
            positions = [r.position for r in rows]
            assert 0 in positions
            assert 1 in positions
        finally:
            db.close()

    def test_placehold_writes_placeholder(self, partial_deck):
        from src.api.services.slide_repository import is_placeholder_record
        import json
        partial_deck.placehold(position=2)
        factory = sessionmaker(
            bind=partial_deck._engine, expire_on_commit=False
        )
        db = factory()
        try:
            owner_id = (
                db.query(UserSession)
                .filter(UserSession.session_id == partial_deck.session_id)
                .one()
                .id
            )
            row = (
                db.query(SessionSlide)
                .filter(
                    SessionSlide.session_id == owner_id,
                    SessionSlide.position == 2,
                )
                .one_or_none()
            )
            assert row is not None, "Placeholder row not found at position 2"
            record = json.loads(row.verification_record) if row.verification_record else {}
            assert is_placeholder_record(record), (
                "Row written by placehold() should be a placeholder record"
            )
        finally:
            db.close()

    def test_land_and_placehold_combined(self, partial_deck):
        partial_deck.land(positions=[0, 1])
        partial_deck.placehold(position=2)
        # Three rows total
        factory = sessionmaker(bind=partial_deck._engine, expire_on_commit=False)
        db = factory()
        try:
            owner_id = (
                db.query(UserSession)
                .filter(UserSession.session_id == partial_deck.session_id)
                .one()
                .id
            )
            count = (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == owner_id)
                .count()
            )
            assert count == 3
        finally:
            db.close()


# ---------------------------------------------------------------------------
# released_deck
# ---------------------------------------------------------------------------


class TestReleasedDeck:
    def test_session_id_is_string(self, released_deck):
        assert isinstance(released_deck, str) and released_deck

    def test_has_committed_ascending_slides(self, released_deck, sqlite_engine_file_backed):
        """The three slides are real (non-placeholder) rows at positions 0, 1, 2."""
        from src.api.services.slide_repository import is_placeholder_record
        import json

        factory = sessionmaker(bind=sqlite_engine_file_backed, expire_on_commit=False)
        db = factory()
        try:
            owner_id = (
                db.query(UserSession)
                .filter(UserSession.session_id == released_deck)
                .one()
                .id
            )
            rows = (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == owner_id)
                .order_by(SessionSlide.position)
                .all()
            )
            assert len(rows) == 3, f"Expected 3 slides, got {len(rows)}"
            assert [r.position for r in rows] == [0, 1, 2]
            for row in rows:
                record = json.loads(row.verification_record) if row.verification_record else None
                assert not is_placeholder_record(record), (
                    f"Position {row.position} is a placeholder; released_deck should have real slides"
                )
        finally:
            db.close()
