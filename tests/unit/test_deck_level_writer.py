"""Tests for src/api/services/deck_level_writer.py (B3.1).

Real sqlite throughout — every assertion reads the database back.  No mock stands
in for a column write, because the defect class this module exists to prevent
(a deck-level write that destroys `session_slides` rows) is invisible to a mock.

Driving the writer: `write_deck_level_columns` opens its own DB session via
`get_db_session`, exactly as every `SessionManager` method does, so a throwaway
engine reaches it only by patching (.ws4b-PLAN-CORRECTIONS.md §14.1).  The patch
target is this module's own reference, `src.api.services.deck_level_writer.
get_db_session`; the writer passes `db` explicitly into the two reused
`SessionManager` helpers, so `session_manager.get_db_session` needs no patch.
`_make_fake_db` is reused from tests/unit/conftest.py rather than reinvented.
"""
from __future__ import annotations

import contextlib
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text as sa_text
from unittest.mock import patch

from src.api.services.deck_level_writer import (
    read_deck_spec,
    write_deck_level_columns,
)
from src.api.services.session_manager import (
    SessionNotFoundError,
    VersionConflictError,
)
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from tests.unit.conftest import _make_fake_db, _make_factory

_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"


@contextlib.contextmanager
def _patched(factory):
    """Point both get_db_session references at *factory*'s throwaway engine.

    The writer only ever uses its OWN reference, so the SessionManager patch is
    inert for a correct implementation.  It is here deliberately: if the writer
    ever delegates to a `SessionManager` method (the wrong implementation this
    module exists to rule out — `save_slide_deck(deck_dict={"slides": []})`),
    that delegation runs against THIS engine and the row-safety test fails on
    destroyed rows, which is the defect, instead of on a real-database
    connection error, which would hide it.
    """
    fake = _make_fake_db(factory)
    with patch(_WRITER_DB, fake), patch(_MANAGER_DB, fake):
        yield


# Representative deck-level payloads.
_CSS = ".slide { color: rebeccapurple; }"
_EXTERNAL_SCRIPTS = ["https://cdn.jsdelivr.net/npm/chart.js@4"]
_HEAD_META = {"viewport": "width=1280, initial-scale=1.0", "charset": "utf-8"}
_DECK_SPEC = {
    "title": "Written By The Architect",
    "audience": "Board",
    "slides": [{"position": 0, "purpose": "intro"}],
}


# ---------------------------------------------------------------------------
# The reason the module exists: no session_slides row is touched.
# ---------------------------------------------------------------------------


class TestTouchesNoSlideRows:
    def test_pre_fan_out_write_touches_no_session_slides_row(self, deck_with_three_rows):
        """A deck-level write leaves all three slide rows byte-identical.

        This is the test the mandatory sabotage targets: delegating to
        `save_slide_deck(deck_dict={"slides": []})` prunes every row at
        position >= 0, i.e. the whole live deck, mid-turn.
        """
        before = deck_with_three_rows.row_snapshot()
        assert len(before) == 3, "fixture precondition: three slide rows exist"

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                title="Pre-fan-out title",
                css=_CSS,
                external_scripts=_EXTERNAL_SCRIPTS,
                head_meta=_HEAD_META,
                deck_spec=_DECK_SPEC,
            )

        after = deck_with_three_rows.row_snapshot()
        assert len(after) == 3, f"row COUNT changed: 3 -> {len(after)}"
        assert after == before, "a session_slides row was modified"

    def test_post_commit_write_touches_no_session_slides_row(self, deck_with_three_rows):
        """The second write of the turn is equally row-safe."""
        before = deck_with_three_rows.row_snapshot()

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                css=_CSS,
                slide_count=3,
                html_content="<html>knitted</html>",
                scripts_content="(function(){})();",
            )

        assert deck_with_three_rows.row_snapshot() == before

    def test_write_does_not_null_deck_json(self, deck_with_three_rows):
        """deck_json survives, unchanged — save_slide_deck(deck_dict=None) nulls it."""
        before = deck_with_three_rows.deck_json()
        assert before is not None, "fixture precondition: deck_json is populated"

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                title="Still has a blob",
                css=_CSS,
            )

        after = deck_with_three_rows.deck_json()
        assert after is not None, "deck_json was nulled"
        assert after == before


# ---------------------------------------------------------------------------
# Optimistic locking — the shape reused from save_slide_deck.
# ---------------------------------------------------------------------------


class TestOptimisticLock:
    def test_version_bumps_exactly_once_per_call(self, deck_with_three_rows):
        start = deck_with_three_rows.version()

        with _patched(deck_with_three_rows._factory):
            first = write_deck_level_columns(
                deck_with_three_rows.session_id, css=_CSS
            )
        assert deck_with_three_rows.version() == start + 1
        assert first["version"] == start + 1

        with _patched(deck_with_three_rows._factory):
            second = write_deck_level_columns(
                deck_with_three_rows.session_id, slide_count=3
            )
        assert deck_with_three_rows.version() == start + 2
        assert second["version"] == start + 2

    def test_user_visible_false_writes_the_columns_but_leaves_the_token(
        self, deck_with_three_rows
    ):
        """ws4d: a write that changes nothing the client's token guards.

        `deck.version` is the optimistic-lock token a WYSIWYG client holds between
        saves, and the slide routes turn a mismatch into HTTP 409.  The arc-review
        sweeper is the first writer that runs outside a user turn, and it runs
        BECAUSE the human is editing — so a bump there rejects that human's very
        next save.
        """
        start = deck_with_three_rows.version()

        with _patched(deck_with_three_rows._factory):
            result = write_deck_level_columns(
                deck_with_three_rows.session_id, css=_CSS, user_visible=False
            )

        assert deck_with_three_rows.version() == start, (
            "the token moved on a write that guards nothing; the editing human's "
            "next save is a 409"
        )
        assert result["version"] == start
        # The write itself must still have happened: a "fix" that skipped the
        # write entirely would satisfy the assertion above.
        assert deck_with_three_rows.deck_row().css == _CSS

    def test_the_default_still_bumps_so_a_real_edit_invalidates_the_token(
        self, deck_with_three_rows
    ):
        """The paired direction, asserted on the DEFAULT rather than on True.

        A default flipped to False would break the optimistic lock for every
        user-driven write, and passing True explicitly here would not notice.
        """
        start = deck_with_three_rows.version()
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(deck_with_three_rows.session_id, css=_CSS)
        assert deck_with_three_rows.version() == start + 1


class TestTheClientVisibleModifiedTimestamp:
    """`user_visible=False` also leaves `updated_at` alone.

    ONE flag governs both signals, so a caller cannot produce the half-state:
    "modified just now" rendered beside an *unchanged* optimistic-lock token.

    The suppression is measured, not assumed: `Column(onupdate=)` applies to any
    column not already in the UPDATE's SET clause, and an ORM attribute with no
    net change never reaches that clause — so `deck.updated_at = deck.updated_at`
    suppresses nothing.  `flag_modified` puts it in the clause at its loaded
    value, which does.

    A timestamp planted an hour back rather than whatever the INSERT wrote, so
    neither direction is a microsecond-resolution race with the UPDATE under test.
    """

    @staticmethod
    def _backdate(fixture, seconds: float = 3600.0) -> datetime:
        stamp = datetime.utcnow() - timedelta(seconds=seconds)
        db = fixture._factory()
        try:
            db.execute(
                sa_text(
                    "UPDATE session_slide_decks SET updated_at = :at WHERE id = :id"
                ),
                {"at": stamp, "id": fixture.deck_row().id},
            )
            db.commit()
        finally:
            db.close()
        assert fixture.deck_row().updated_at == stamp, "the backdate did not take"
        return stamp

    def test_a_write_the_client_should_not_see_leaves_modified_at_alone(
        self, deck_with_three_rows
    ):
        planted = self._backdate(deck_with_three_rows)

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id, css=_CSS, user_visible=False
            )

        assert deck_with_three_rows.deck_row().updated_at == planted, (
            "the deck shows as modified just now beside an unchanged version "
            "token — the half-state this flag exists to prevent"
        )
        # The columns really were written, so this is not a no-op passing.
        assert deck_with_three_rows.deck_row().css == _CSS

    def test_the_DEFAULT_still_moves_modified_at(self, deck_with_three_rows):
        """The paired direction, on the default rather than an explicit True.

        Suppressing everywhere would satisfy the test above while making every
        real edit invisible in the session list.
        """
        planted = self._backdate(deck_with_three_rows)

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(deck_with_three_rows.session_id, css=_CSS)

        assert deck_with_three_rows.deck_row().updated_at > planted, (
            "a user-driven deck write no longer moves modified_at"
        )


class TestTheSessionListOrdering:
    """`user_visible=False` also leaves `UserSession.last_activity` alone.

    The THIRD client-visible signal, and the one that escaped an earlier version
    of this flag that governed only `version` and `updated_at`.  The session list
    is ORDERED by `last_activity.desc()` (`sessions.py:207`) and returns it
    (`:232`), so a sweeper write that moved it would silently re-sort the human's
    session list about three minutes after they stopped editing — on a deck whose
    other two signals both say nothing changed.

    Kept in its own class per the standing rule: it is a distinct property of the
    same write, and a shared test would report one failure for any of the three.
    """

    @staticmethod
    def _backdate_session(fixture, seconds: float = 3600.0) -> datetime:
        stamp = datetime.utcnow() - timedelta(seconds=seconds)
        db = fixture._factory()
        try:
            db.execute(
                sa_text(
                    "UPDATE user_sessions SET last_activity = :at "
                    "WHERE session_id = :sid"
                ),
                {"at": stamp, "sid": fixture.session_id},
            )
            db.commit()
        finally:
            db.close()
        assert TestTheSessionListOrdering._session_row(fixture).last_activity == stamp
        return stamp

    @staticmethod
    def _session_row(fixture) -> UserSession:
        db = fixture._factory()
        try:
            row = (
                db.query(UserSession)
                .filter(UserSession.session_id == fixture.session_id)
                .one()
            )
            db.expunge(row)
            return row
        finally:
            db.close()

    def test_a_write_the_client_should_not_see_leaves_last_activity_alone(
        self, deck_with_three_rows
    ):
        """The absence half — PAIRED, per the standing rule, with proof the write
        happened at all: "the timestamp did not move" is equally true of a call
        that did nothing."""
        planted = self._backdate_session(deck_with_three_rows)

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id, css=_CSS, user_visible=False
            )

        assert deck_with_three_rows.deck_row().css == _CSS, (
            "the write did not happen, so an unmoved timestamp proves nothing"
        )
        assert self._session_row(deck_with_three_rows).last_activity == planted, (
            "a sweeper write moved last_activity; the human's session list "
            "re-sorts minutes after they stopped editing, on a deck whose version "
            "and modified_at both say nothing changed"
        )

    def test_the_DEFAULT_still_moves_last_activity(self, deck_with_three_rows):
        """The paired direction, on the default rather than an explicit True.

        Suppressing everywhere would satisfy the test above while freezing the
        session list's ordering for every real edit.
        """
        planted = self._backdate_session(deck_with_three_rows)

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(deck_with_three_rows.session_id, css=_CSS)

        assert self._session_row(deck_with_three_rows).last_activity > planted, (
            "a user-driven deck write no longer moves last_activity; the session "
            "list will not re-order after a real edit"
        )

    def test_a_contributors_own_session_row_is_left_alone_too(
        self, contributor_session
    ):
        """The writer touches TWO rows on a contributor write — the owner's and
        the contributor's — so a suppression covering only the owner would leave
        the contributor's list re-sorting. The single-direction trap."""
        stamp = datetime.utcnow() - timedelta(seconds=3600)
        db = contributor_session._factory()
        try:
            db.execute(
                sa_text("UPDATE user_sessions SET last_activity = :at"),
                {"at": stamp},
            )
            db.commit()
        finally:
            db.close()

        with _patched(contributor_session._factory):
            write_deck_level_columns(
                contributor_session.contributor_session_id,
                css=_CSS,
                user_visible=False,
            )

        assert contributor_session.owner_deck_row().css == _CSS, (
            "the contributor's write did not land, so nothing below is tested"
        )
        db = contributor_session._factory()
        try:
            moved = [
                r.session_id
                for r in db.query(UserSession).all()
                if r.last_activity != stamp
            ]
        finally:
            db.close()
        assert not moved, (
            f"{moved} had last_activity moved by a write the client should not "
            "see; a contributor's session list re-sorts too"
        )

    def test_matching_expected_version_is_accepted(self, deck_with_three_rows):
        current = deck_with_three_rows.version()

        with _patched(deck_with_three_rows._factory):
            result = write_deck_level_columns(
                deck_with_three_rows.session_id,
                css=_CSS,
                expected_version=current,
            )

        assert result["version"] == current + 1
        assert deck_with_three_rows.deck_row().css == _CSS

    def test_stale_expected_version_raises(self, deck_with_three_rows):
        """Property one, on its own: a stale write is rejected loudly."""
        current = deck_with_three_rows.version()

        with _patched(deck_with_three_rows._factory):
            with pytest.raises(VersionConflictError) as exc:
                write_deck_level_columns(
                    deck_with_three_rows.session_id,
                    css="/* stale writer */",
                    expected_version=current - 1,
                )

        assert exc.value.current_version == current
        assert exc.value.expected_version == current - 1

    def test_a_stale_write_persists_nothing(self, deck_with_three_rows):
        """Property two, INDEPENDENTLY falsifiable.

        The state comparison runs OUTSIDE the exception handling, so it is
        evaluated whether or not the conflict fired.  That is the point: a writer
        that raises correctly and has *already* mutated the row is the more
        insidious failure — the caller sees a clean rejection and the data has
        moved anyway — and a `pytest.raises` block with the assertions inside it
        cannot see that case at all.
        """
        before_version = deck_with_three_rows.version()
        _columns = (
            "version",
            "title",
            "css",
            "external_scripts_json",
            "head_meta_json",
            "deck_spec_json",
            "slide_count",
            "html_content",
            "scripts_content",
            "modified_by",
            "deck_json",
        )
        before_deck = deck_with_three_rows.deck_row()
        before = {name: getattr(before_deck, name) for name in _columns}
        before_session_title = deck_with_three_rows.session_row().title
        before_rows = deck_with_three_rows.row_snapshot()

        with _patched(deck_with_three_rows._factory):
            try:
                write_deck_level_columns(
                    deck_with_three_rows.session_id,
                    title="Stale title",
                    css="/* stale writer */",
                    external_scripts=["https://example.invalid/stale.js"],
                    head_meta={"viewport": "stale"},
                    deck_spec={"title": "stale spec"},
                    slide_count=99,
                    html_content="<html>stale</html>",
                    scripts_content="/* stale scripts */",
                    modified_by="stale@example.com",
                    expected_version=before_version - 1,
                )
            except VersionConflictError:
                # Whether it raises is test_stale_expected_version_raises's
                # business.  Swallowed here so the state assertions below run in
                # BOTH worlds.
                pass

        after_deck = deck_with_three_rows.deck_row()
        after = {name: getattr(after_deck, name) for name in _columns}
        assert after == before, "a rejected write persisted deck-level state"
        assert (
            deck_with_three_rows.session_row().title == before_session_title
        ), "a rejected write persisted the session row's title"
        assert deck_with_three_rows.row_snapshot() == before_rows


# ---------------------------------------------------------------------------
# The sentinel: omitted != explicit None.
# ---------------------------------------------------------------------------


class TestSentinelSemantics:
    def test_omitted_columns_survive_the_second_write(self, deck_with_three_rows):
        """The crux: the post-commit write must not erase the pre-fan-out write.

        Call 1 persists the five pre-fan-out columns; call 2 supplies only the
        three post-commit ones.  Every value from call 1 must still be there.
        """
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                title="Architect's title",
                css=_CSS,
                external_scripts=_EXTERNAL_SCRIPTS,
                head_meta=_HEAD_META,
                deck_spec=_DECK_SPEC,
            )

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                slide_count=3,
                html_content="<html>knitted</html>",
                scripts_content="(function(){/*charts*/})();",
            )

        deck = deck_with_three_rows.deck_row()
        assert deck.title == "Architect's title", "title erased by the second write"
        assert deck.css == _CSS, "css erased by the second write"
        assert json.loads(deck.external_scripts_json) == _EXTERNAL_SCRIPTS, (
            "external_scripts_json erased — Chart.js would vanish from every export"
        )
        assert json.loads(deck.head_meta_json) == _HEAD_META, "head_meta_json erased"
        assert json.loads(deck.deck_spec_json) == _DECK_SPEC, "deck_spec_json erased"

    def test_all_eight_columns_written_across_the_two_calls(self, deck_with_three_rows):
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                title="Eight Columns",
                css=_CSS,
                external_scripts=_EXTERNAL_SCRIPTS,
                head_meta=_HEAD_META,
                deck_spec=_DECK_SPEC,
            )
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                css=_CSS + " /* aggregated */",
                slide_count=7,
                html_content="<html>knitted</html>",
                scripts_content="(function(){/*charts*/})();",
            )

        deck = deck_with_three_rows.deck_row()
        assert deck.title == "Eight Columns"
        assert deck.css == _CSS + " /* aggregated */"
        assert json.loads(deck.external_scripts_json) == _EXTERNAL_SCRIPTS
        assert json.loads(deck.head_meta_json) == _HEAD_META
        assert json.loads(deck.deck_spec_json) == _DECK_SPEC
        assert deck.slide_count == 7
        assert deck.html_content == "<html>knitted</html>"
        assert deck.scripts_content == "(function(){/*charts*/})();"

    def test_explicit_none_writes_null(self, deck_fixture):
        """`None` is a value, not an omission — it clears the column."""
        with _patched(deck_fixture._factory):
            write_deck_level_columns(deck_fixture.session_id, css=_CSS)
        assert deck_fixture.deck_row().css == _CSS

        with _patched(deck_fixture._factory):
            write_deck_level_columns(deck_fixture.session_id, css=None)
        assert deck_fixture.deck_row().css is None

    def test_html_content_is_optional(self, deck_fixture):
        """The pre-fan-out write has no knitted HTML; save_slide_deck demands it."""
        with _patched(deck_fixture._factory):
            write_deck_level_columns(
                deck_fixture.session_id,
                title="No HTML yet",
                css=_CSS,
                deck_spec=_DECK_SPEC,
            )

        deck = deck_fixture.deck_row()
        assert deck.title == "No HTML yet"
        assert deck.html_content == "", "html_content was altered by a write that omitted it"


# ---------------------------------------------------------------------------
# Session row, owner resolution, and the no-row case.
# ---------------------------------------------------------------------------


class TestSessionRowAndOwner:
    def test_title_also_updates_the_session_row(self, deck_with_three_rows):
        """The session list renders UserSession.title, not the deck's."""
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id, title="Renamed by the graph"
            )

        assert deck_with_three_rows.session_row().title == "Renamed by the graph"
        assert deck_with_three_rows.deck_row().title == "Renamed by the graph"

    def test_a_write_that_omits_title_leaves_the_session_row_alone(
        self, deck_with_three_rows
    ):
        """A title must be established first, or this test cannot fail.

        The fixture's UserSession.title starts NULL, so asserting
        "unchanged" against that start state passes even when an omitted
        title nulls the row.  Write a title, THEN omit it.
        """
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id, title="Established"
            )
        assert deck_with_three_rows.session_row().title == "Established"

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(deck_with_three_rows.session_id, css=_CSS)

        assert deck_with_three_rows.session_row().title == "Established", (
            "the session row's title was clobbered by a write that omitted title"
        )

    def test_contributor_session_writes_to_the_owner(self, contributor_session):
        with _patched(contributor_session._factory):
            result = write_deck_level_columns(
                contributor_session.contributor_session_id,
                title="Written by a contributor",
                css=_CSS,
                deck_spec=_DECK_SPEC,
            )

        owner_deck = contributor_session.owner_deck_row()
        assert owner_deck.title == "Written by a contributor"
        assert owner_deck.css == _CSS
        assert json.loads(owner_deck.deck_spec_json) == _DECK_SPEC
        assert result["created"] is False, "wrote a second deck instead of the owner's"

        # And no separate deck row was created for the contributor session.
        db = contributor_session._factory()
        try:
            assert db.query(SessionSlideDeck).count() == 1
        finally:
            db.close()

    def test_creates_the_deck_row_when_none_exists(
        self, empty_session, _session_unit_engine
    ):
        """The pre-fan-out write is the FIRST deck write of a brand-new session.

        Without a create branch every graph turn on a new session raises.
        `empty_session` is a UserSession with no SessionSlideDeck; it shares the
        function-scoped `_session_unit_engine` so the same engine is patched in.
        """
        factory = _make_factory(_session_unit_engine)

        db = factory()
        try:
            owner_pk = (
                db.query(UserSession)
                .filter(UserSession.session_id == empty_session)
                .one()
                .id
            )
            assert (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_pk)
                .count()
                == 0
            ), "fixture precondition: no deck row"
        finally:
            db.close()

        with _patched(factory):
            result = write_deck_level_columns(
                empty_session,
                title="Brand new deck",
                css=_CSS,
                external_scripts=_EXTERNAL_SCRIPTS,
                head_meta=_HEAD_META,
                deck_spec=_DECK_SPEC,
                modified_by="graph@example.com",
            )

        assert result["created"] is True
        assert result["version"] == 1

        db = factory()
        try:
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_pk)
                .one()
            )
            assert deck.title == "Brand new deck"
            assert deck.css == _CSS
            assert json.loads(deck.deck_spec_json) == _DECK_SPEC
            assert deck.version == 1
            assert deck.modified_by == "graph@example.com"
            assert deck.slide_count == 0, "slide_count NULL renders nothing in the list"
            assert deck.deck_json is None
            # Still no slide rows.
            assert (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == owner_pk)
                .count()
                == 0
            )
        finally:
            db.close()

    def test_unknown_session_raises(self, deck_fixture):
        with _patched(deck_fixture._factory):
            with pytest.raises(SessionNotFoundError):
                write_deck_level_columns("no-such-session", css=_CSS)


# ---------------------------------------------------------------------------
# read_deck_spec
# ---------------------------------------------------------------------------


class TestReadDeckSpec:
    def test_round_trips_a_written_spec(self, deck_with_three_rows):
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id, deck_spec=_DECK_SPEC
            )
            assert read_deck_spec(deck_with_three_rows.session_id) == _DECK_SPEC

    def test_returns_none_when_absent(self, deck_fixture):
        assert deck_fixture.deck_row().deck_spec_json is None
        with _patched(deck_fixture._factory):
            assert read_deck_spec(deck_fixture.session_id) is None

    def test_returns_none_for_an_unparseable_column(self, deck_with_three_rows):
        deck_with_three_rows.set_raw_deck_spec_json("{not json at all")
        with _patched(deck_with_three_rows._factory):
            assert read_deck_spec(deck_with_three_rows.session_id) is None

    def test_returns_none_for_a_non_object_column(self, deck_with_three_rows):
        """Parses fine, but the contract is `dict | None`."""
        deck_with_three_rows.set_raw_deck_spec_json(json.dumps([1, 2, 3]))
        with _patched(deck_with_three_rows._factory):
            assert read_deck_spec(deck_with_three_rows.session_id) is None

    def test_contributor_reads_the_owners_spec(self, contributor_session):
        with _patched(contributor_session._factory):
            write_deck_level_columns(
                contributor_session.contributor_session_id, deck_spec=_DECK_SPEC
            )
            assert (
                read_deck_spec(contributor_session.contributor_session_id) == _DECK_SPEC
            )
