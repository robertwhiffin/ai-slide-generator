"""Self-tests for the fixtures declared in tests/unit/conftest.py.

Every fixture is exercised here so we know its declared surface exists and
behaves.  Without consumers, a fixture is unverifiable.

DO NOT put integration fixtures here — stub_writer, partial_deck, released_deck
live in tests/integration/conftest.py.  They are tested in
tests/integration/test_ws4b_fixture_contracts.py, which is named in the
integration-general CI job so the coverage guard passes.
"""
from __future__ import annotations

import json
import queue
from unittest.mock import patch

import pytest

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.core.database import Base

# Use a real StreamEventType value (CONTENT does not exist; ASSISTANT does)
_EVENT_TYPE = StreamEventType.ASSISTANT
from src.core.user_context import get_current_user


# ---------------------------------------------------------------------------
# sqlite_engine_with_decks
# ---------------------------------------------------------------------------


class TestSqliteEngineWithDecks:
    def test_engine_has_deck_tables(self, sqlite_engine_with_decks):
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(sqlite_engine_with_decks)
        tables = set(inspector.get_table_names())
        assert "session_slide_decks" in tables
        assert "session_slides" in tables
        assert "user_sessions" in tables

    def test_engine_is_not_none(self, sqlite_engine_with_decks):
        assert sqlite_engine_with_decks is not None


# ---------------------------------------------------------------------------
# sqlite_engine_with_prompts
# ---------------------------------------------------------------------------


class TestSqliteEngineWithPrompts:
    def test_engine_has_prompts_table(self, sqlite_engine_with_prompts):
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(sqlite_engine_with_prompts)
        tables = set(inspector.get_table_names())
        assert "config_prompts" in tables
        assert "session_slide_decks" in tables


# ---------------------------------------------------------------------------
# deck_fixture
# ---------------------------------------------------------------------------


class TestDeckFixture:
    def test_session_id_is_string(self, deck_fixture):
        assert isinstance(deck_fixture.session_id, str)
        assert deck_fixture.session_id

    def test_deck_row_returns_deck(self, deck_fixture):
        deck = deck_fixture.deck_row()
        assert deck is not None
        assert deck.title == "Test Deck"

    def test_prune_all_versions_is_callable(self, deck_fixture):
        # No versions exist yet — calling it should be a no-op
        deck_fixture.prune_all_versions()


# ---------------------------------------------------------------------------
# deck_with_three_rows — the workhorse
# ---------------------------------------------------------------------------


class TestDeckWithThreeRows:
    def test_rows_returns_three_rows(self, deck_with_three_rows):
        rows = deck_with_three_rows.rows()
        assert len(rows) == 3

    def test_rows_are_ordered_by_position(self, deck_with_three_rows):
        rows = deck_with_three_rows.rows()
        positions = [r.position for r in rows]
        assert positions == sorted(positions)

    def test_row_snapshot_captures_enough_to_detect_changes(self, deck_with_three_rows):
        snap = deck_with_three_rows.row_snapshot()
        assert len(snap) == 3
        # Must capture both identity columns
        for entry in snap:
            assert "slide_id" in entry  # String(255) stable frontend UUID
            assert "id" in entry        # String(64) internal row identity
            assert "html" in entry
            assert "position" in entry
            assert "modified_by" in entry
            assert "verification_record" in entry

    def test_deck_row_is_accessible(self, deck_with_three_rows):
        deck = deck_with_three_rows.deck_row()
        assert deck.slide_count == 3

    def test_version_returns_int(self, deck_with_three_rows):
        v = deck_with_three_rows.version()
        assert isinstance(v, int)

    def test_session_row_is_accessible(self, deck_with_three_rows):
        sess = deck_with_three_rows.session_row()
        assert sess.session_id == deck_with_three_rows.session_id

    def test_deck_row_for_returns_same_deck(self, deck_with_three_rows):
        deck = deck_with_three_rows.deck_row_for(deck_with_three_rows.session_id)
        assert deck is not None

    def test_set_raw_deck_spec_json_persists(self, deck_with_three_rows):
        deck_with_three_rows.set_raw_deck_spec_json('{"title":"overwritten"}')
        deck = deck_with_three_rows.deck_row()
        assert deck.deck_spec_json == '{"title":"overwritten"}'

    def test_get_slide_deck_returns_dict(self, deck_with_three_rows):
        result = deck_with_three_rows.get_slide_deck()
        # May be None if no slides returned, or a dict
        assert result is None or isinstance(result, dict)

    def test_version_count_starts_at_zero(self, deck_with_three_rows):
        assert deck_with_three_rows.version_count() == 0

    def test_create_version_increments_count(self, deck_with_three_rows):
        deck_with_three_rows.create_version()
        assert deck_with_three_rows.version_count() == 1

    def test_duplicate_returns_new_session_id(self, deck_with_three_rows):
        result = deck_with_three_rows.duplicate()
        assert isinstance(result, dict)
        assert "session_id" in result
        assert result["session_id"] != deck_with_three_rows.session_id

    def test_deck_json_returns_dict_or_none(self, deck_with_three_rows):
        dj = deck_with_three_rows.deck_json()
        assert dj is None or isinstance(dj, dict)


# ---------------------------------------------------------------------------
# deck_with_spec
# ---------------------------------------------------------------------------


class TestDeckWithSpec:
    def test_has_three_rows(self, deck_with_spec):
        assert len(deck_with_spec.rows()) == 3

    def test_deck_spec_json_is_set(self, deck_with_spec):
        deck = deck_with_spec.deck_row()
        assert deck.deck_spec_json is not None
        parsed = json.loads(deck.deck_spec_json)
        assert parsed["title"] == "Test Deck"

    def test_set_spec_audience_updates_spec(self, deck_with_spec):
        deck_with_spec.set_spec_audience("C-suite executives")
        deck = deck_with_spec.deck_row()
        spec = json.loads(deck.deck_spec_json)
        assert spec["audience"] == "C-suite executives"


# ---------------------------------------------------------------------------
# deck_with_spec_but_no_rows
# ---------------------------------------------------------------------------


class TestDeckWithSpecButNoRows:
    def test_session_id_is_string(self, deck_with_spec_but_no_rows):
        assert deck_with_spec_but_no_rows.session_id

    def test_get_slide_deck_returns_something(self, deck_with_spec_but_no_rows):
        # Should trigger blob fallback; returns None or a dict
        result = deck_with_spec_but_no_rows.get_slide_deck()
        assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# deck_with_verdicts
# ---------------------------------------------------------------------------


class TestDeckWithVerdicts:
    def test_verdict_for_html_at_returns_dict(self, deck_with_verdicts):
        for pos in range(3):
            verdict = deck_with_verdicts.verdict_for_html_at(pos)
            assert verdict is not None, f"No verdict at position {pos}"
            assert isinstance(verdict, dict)
            assert "score" in verdict

    def test_verdict_keyed_by_hash_not_position(self, deck_with_verdicts):
        # Each position has a distinct verdict (score differs)
        scores = {
            deck_with_verdicts.verdict_for_html_at(pos)["score"]
            for pos in range(3)
        }
        assert len(scores) == 3


# ---------------------------------------------------------------------------
# deck_with_marker
# ---------------------------------------------------------------------------


class TestDeckWithMarker:
    def test_session_id_is_string(self, deck_with_marker):
        assert deck_with_marker.session_id

    def test_deck_row_is_accessible(self, deck_with_marker):
        deck = deck_with_marker.deck_row()
        assert deck is not None

    def test_restore_latest_version_succeeds(self, deck_with_marker):
        # There is one version from fixture setup; restore should return a deck
        result = deck_with_marker.restore_latest_version()
        assert isinstance(result, dict)

    def test_restore_version_by_number_succeeds(self, deck_with_marker):
        # Version 1 was created during fixture setup
        result = deck_with_marker.restore_version(1)
        assert isinstance(result, dict)

    @pytest.mark.xfail(
        strict=True,
        reason="set_marker requires migration B2.3 (spec_dirty_at column not yet added); "
               "strict=True so the suite goes RED when B2.3 lands, forcing conversion to "
               "a passing test"
    )
    def test_set_marker_sets_dirty_columns(self, deck_with_marker):
        """After B2.3: set_marker writes spec_dirty_at and spec_dirty_by.

        The assertions below will pass once the columns exist.  Until then
        set_marker() raises OperationalError (column not found), the xfail
        catches it, and strict=True means an unexpected pass turns red.
        """
        from src.database.models.session import SessionSlideDeck

        deck_with_marker.set_marker(age_seconds=30.0, author="dirty@example.com")

        db = deck_with_marker._factory()
        try:
            owner_id = deck_with_marker._owner_pk(deck_with_marker.session_id)
            row = db.execute(
                __import__('sqlalchemy').text(
                    "SELECT spec_dirty_by, spec_dirty_at FROM session_slide_decks "
                    "WHERE session_id = :sid"
                ),
                {"sid": owner_id},
            ).one()
            assert row.spec_dirty_by == "dirty@example.com"
            assert row.spec_dirty_at is not None
            # age_seconds=30.0: the dirty timestamp must be at most ~35s in the past
            from datetime import datetime
            age = (datetime.utcnow() - row.spec_dirty_at).total_seconds()
            assert 0 <= age < 35, f"spec_dirty_at age {age:.1f}s outside expected range"
        finally:
            db.close()

    @pytest.mark.xfail(
        strict=True,
        reason="set_claim requires migration B2.3 (spec_dirty_claimed_at column not yet added); "
               "strict=True so the suite goes RED when B2.3 lands, forcing conversion"
    )
    def test_set_claim_sets_claimed_column(self, deck_with_marker):
        """After B2.3: set_claim writes spec_dirty_claimed_at.

        The assertion below passes once the column exists.  Until then strict
        xfail catches the OperationalError.
        """
        deck_with_marker.set_claim(age_seconds=10.0)

        db = deck_with_marker._factory()
        try:
            owner_id = deck_with_marker._owner_pk(deck_with_marker.session_id)
            row = db.execute(
                __import__('sqlalchemy').text(
                    "SELECT spec_dirty_claimed_at FROM session_slide_decks "
                    "WHERE session_id = :sid"
                ),
                {"sid": owner_id},
            ).one()
            assert row.spec_dirty_claimed_at is not None
            from datetime import datetime
            age = (datetime.utcnow() - row.spec_dirty_claimed_at).total_seconds()
            assert 0 <= age < 15, f"spec_dirty_claimed_at age {age:.1f}s outside expected range"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# contributor_session
# ---------------------------------------------------------------------------


class TestContributorSession:
    def test_contributor_session_id_is_string(self, contributor_session):
        assert contributor_session.contributor_session_id
        assert isinstance(contributor_session.contributor_session_id, str)

    def test_owner_deck_row_is_accessible(self, contributor_session):
        deck = contributor_session.owner_deck_row()
        assert deck is not None

    def test_contributor_and_owner_ids_differ(self, contributor_session):
        assert contributor_session.contributor_session_id != getattr(
            contributor_session, "_owner_session_id", None
        )


# ---------------------------------------------------------------------------
# contributor_session_with_spec
# ---------------------------------------------------------------------------


class TestContributorSessionWithSpec:
    def test_contributor_session_id_is_string(self, contributor_session_with_spec):
        assert contributor_session_with_spec.contributor_session_id

    def test_get_slide_deck_as_contributor_returns_result(self, contributor_session_with_spec):
        result = contributor_session_with_spec.get_slide_deck_as_contributor()
        # Returns None or a dict
        assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# session_with_messages + session_messages
# ---------------------------------------------------------------------------


class TestSessionWithMessages:
    def test_returns_session_id(self, session_with_messages):
        sid = session_with_messages(["Hello"])
        assert isinstance(sid, str) and sid

    def test_messages_are_readable(self, session_with_messages, session_messages):
        sid = session_with_messages(["First", "Second"])
        msgs = session_messages(sid)
        assert len(msgs) == 2
        assert all(m.role == "user" for m in msgs)

    def test_earliest_user_row_is_first_message(self, session_with_messages, session_messages):
        sid = session_with_messages(["first", "second"])
        msgs = session_messages(sid)
        assert msgs[0].content == "first"

    def test_assistant_messages_are_included(self, session_with_messages, session_messages):
        sid = session_with_messages(["question"], assistant_messages=["answer"])
        msgs = session_messages(sid)
        roles = {m.role for m in msgs}
        assert "user" in roles
        assert "assistant" in roles

    def test_multiple_sessions_are_independent(self, session_with_messages, session_messages):
        sid1 = session_with_messages(["msg-A"])
        sid2 = session_with_messages(["msg-B"])
        assert session_messages(sid1)[0].content == "msg-A"
        assert session_messages(sid2)[0].content == "msg-B"


# ---------------------------------------------------------------------------
# empty_session
# ---------------------------------------------------------------------------


class TestEmptySession:
    def test_returns_session_id(self, empty_session):
        assert isinstance(empty_session, str) and empty_session

    def test_no_messages(self, empty_session, session_messages):
        # empty_session and session_messages share _session_unit_engine
        msgs = session_messages(empty_session)
        assert msgs == []


# ---------------------------------------------------------------------------
# mcp_created_session
# ---------------------------------------------------------------------------


class TestMcpCreatedSession:
    def test_returns_session_id(self, mcp_created_session):
        assert isinstance(mcp_created_session, str) and mcp_created_session

    def test_different_from_empty_session(self, empty_session, mcp_created_session):
        assert empty_session != mcp_created_session


# ---------------------------------------------------------------------------
# session_with_spec_and_messages
# ---------------------------------------------------------------------------


class TestSessionWithSpecAndMessages:
    def test_returns_session_id(self, session_with_spec_and_messages):
        assert isinstance(session_with_spec_and_messages, str)


# ---------------------------------------------------------------------------
# session_and_profile_with_legacy_blobs
# ---------------------------------------------------------------------------


class TestSessionAndProfileWithLegacyBlobs:
    def test_session_local_is_callable(self, session_and_profile_with_legacy_blobs):
        assert callable(session_and_profile_with_legacy_blobs.session_local)

    def test_reload_blobs_returns_dict(self, session_and_profile_with_legacy_blobs):
        blobs = session_and_profile_with_legacy_blobs.reload_blobs()
        assert isinstance(blobs, dict)
        assert "session" in blobs
        assert "profile" in blobs

    def test_legacy_keys_are_present_before_migration(self, session_and_profile_with_legacy_blobs):
        blobs = session_and_profile_with_legacy_blobs.reload_blobs()
        session_cfg = blobs["session"]
        profile_cfg = blobs["profile"]
        # Before B2.5's migration runs, the legacy keys must be present
        assert "system_prompt" in session_cfg
        assert "slide_editing_instructions" in session_cfg
        assert "system_prompt" in profile_cfg


# ---------------------------------------------------------------------------
# session_with_garbage_blob
# ---------------------------------------------------------------------------


class TestSessionWithGarbageBlob:
    def test_session_local_is_callable(self, session_with_garbage_blob):
        assert callable(session_with_garbage_blob.session_local)

    def test_session_id_is_string(self, session_with_garbage_blob):
        assert isinstance(session_with_garbage_blob.session_id, str)

    def test_blob_survives_decode_as_list(self, session_with_garbage_blob):
        """The ORM-written garbage list reads back as a list, not a dict.

        This is the REACHABLE case in the two-halves ruling (R-G(i)):
          - A JSON list written via ORM reads back without raising.
          - Caller code doing .get("model") gets AttributeError.

        The NOT-GUARDABLE case (raw-SQL invalid JSON raises inside the result
        processor before any caller code) is documented in the fixture but
        cannot be tested here without raw SQL insertion.
        """
        db = session_with_garbage_blob.session_local()
        try:
            from src.database.models.session import UserSession
            us = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_with_garbage_blob.session_id)
                .one()
            )
            cfg = us.agent_config
            assert isinstance(cfg, list), f"Expected list, got {type(cfg)}: {cfg!r}"
            # Consumer calling .get() on a list would get AttributeError
            assert not hasattr(cfg, "get") or (
                True  # dict has .get but list does not
            )
        finally:
            db.close()

    def test_blob_fails_downstream_on_get(self, session_with_garbage_blob):
        """Consumer code calling .get() on the list raises AttributeError."""
        db = session_with_garbage_blob.session_local()
        try:
            from src.database.models.session import UserSession
            us = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_with_garbage_blob.session_id)
                .one()
            )
            cfg = us.agent_config
            with pytest.raises((AttributeError, TypeError)):
                _ = cfg.get("model")  # list has no .get()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# as_user
# ---------------------------------------------------------------------------


class TestAsUser:
    def test_stamps_the_identity(self, as_user):
        with as_user("alice@example.com"):
            assert get_current_user() == "alice@example.com"

    def test_restores_previous_value_on_exit(self, as_user):
        """CRITICAL: as_user must restore the previous value, not just clear it."""
        with as_user("outer@example.com"):
            with as_user("inner@example.com"):
                assert get_current_user() == "inner@example.com"
            assert get_current_user() == "outer@example.com"

    def test_restores_none_when_no_previous_user(self, as_user):
        prev = get_current_user()  # should be None in a fresh test
        with as_user("temp@example.com"):
            assert get_current_user() == "temp@example.com"
        assert get_current_user() == prev

    def test_restores_on_exception(self, as_user):
        """Restore happens even when the body raises."""
        try:
            with as_user("x@example.com"):
                raise RuntimeError("bang")
        except RuntimeError:
            pass
        assert get_current_user() != "x@example.com"


# ---------------------------------------------------------------------------
# other_user
# ---------------------------------------------------------------------------


class TestOtherUser:
    def test_stamps_fixed_identity(self, other_user):
        with other_user():
            assert get_current_user() == "other-user@example.com"

    def test_restores_on_exit(self, other_user):
        orig = get_current_user()
        with other_user():
            pass
        assert get_current_user() == orig


# ---------------------------------------------------------------------------
# fake_queue
# ---------------------------------------------------------------------------


class TestFakeQueue:
    def test_items_list_captures_objects(self, fake_queue):
        event = StreamEvent(
            type=_EVENT_TYPE,
            content="hello",
        )
        fake_queue.put(event)
        assert len(fake_queue.items) == 1
        assert isinstance(fake_queue.items[0], StreamEvent)

    def test_not_a_string_is_queued(self, fake_queue):
        event = StreamEvent(type=_EVENT_TYPE, content="world")
        fake_queue.put(event)
        assert not isinstance(fake_queue.items[0], str)

    def test_get_removes_from_queue(self, fake_queue):
        event = StreamEvent(type=_EVENT_TYPE)
        fake_queue.put(event)
        retrieved = fake_queue.get(block=False)
        assert isinstance(retrieved, StreamEvent)
        assert fake_queue.empty()

    def test_items_accumulates_across_puts(self, fake_queue):
        for i in range(3):
            fake_queue.put(StreamEvent(type=_EVENT_TYPE, content=str(i)))
        assert len(fake_queue.items) == 3


# ---------------------------------------------------------------------------
# Engine guard — calls the real _make_in_memory_engine with create_all patched
# ---------------------------------------------------------------------------


class TestEngineGuard:
    """Calls the REAL _make_in_memory_engine with create_all patched to a no-op.

    This test exercises production code, not a reimplementation.  If someone
    deletes the guard assertion from _make_in_memory_engine in conftest.py,
    this test goes RED.  That is verified by the sabotage output in the
    B1.7 report.
    """

    def test_guard_fires_when_create_all_is_noop(self):
        """_make_in_memory_engine raises AssertionError when create_all is a no-op.

        With Base.metadata.create_all patched out, the engine has no tables.
        The guard inside _make_in_memory_engine must detect this and raise
        before the function returns a broken engine.
        """
        from tests.unit.conftest import _make_in_memory_engine

        with patch.object(Base.metadata, "create_all") as mock_create:
            mock_create.return_value = None  # no-op: no tables are created
            with pytest.raises(AssertionError, match="zero tables"):
                _make_in_memory_engine()
