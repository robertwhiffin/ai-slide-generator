"""The route wiring, end to end: a human edit through the API marks the deck.

The structural guarantee lives in tests/unit/test_spec_sync_placement.py (only
slides.py may reference `mark_dirty`) and the marker semantics in
tests/unit/test_spec_sync_marker.py.  This file proves the remaining claim, which
neither of those can: that driving the real HTTP route through the real service
stack against a real database actually lands a marker on the deck row — and that
the SAME mutation invoked as a service method, the way the graph invokes it, does
not.

That pairing is the point.  "A graph write does not set the marker" is an absence
assertion, true as well of a `mark_dirty` that never runs at all; so every test
below that asserts a marker is ABSENT also asserts, on the same deck and in the
same test, that the route path DOES set one.

Harness reused from tests/integration/test_savepoint_e2e.py (full stack, in-memory
SQLite, mocked user) rather than re-rolled, with one addition: `mark_dirty` opens
its own `get_db_session`, so `src.services.spec_sync.get_db_session` must be
patched to the same throwaway engine or the marker write would go to whatever
database the environment points at.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from src.database.models.session import SessionSlideDeck, UserSession

# Reuse the full-stack harness rather than duplicating 60 lines of it.  The
# repo's established pattern (see tests/unit/test_duplicate_session_carries_spec).
from tests.integration.test_savepoint_e2e import (  # noqa: F401 — pytest fixtures
    _create_session,
    _make_fake_get_db_session,
    _seed_deck,
    client,
    mock_user,
    reset_singletons,
    test_db,
    test_db_engine,
    test_db_factory,
)

_SPEC_SYNC_DB = "src.services.spec_sync.get_db_session"
# The graph's deck-level write path also opens its own session; a test that drives
# it must point it at the same engine or it reaches the environment's database.
_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
# Every slide-mutation method in chat_service calls get_current_username() to stamp
# modified_by on the Slide object.  On a laptop load_dotenv() supplies real
# Databricks credentials, so the call returns in milliseconds and was invisible.
# In CI, DATABRICKS_HOST is a non-empty but unreachable value
# ("https://test.cloud.databricks.com"); the SDK enters a retry loop that sleeps
# rather than raising, and the job hung for 22+ minutes before it was cancelled.
# The username is incidental plumbing for this suite (the test subject is the
# dirty-marker route, not Databricks identity resolution), so we stub it here at
# the module boundary where chat_service binds the name.
_CHAT_SERVICE_USERNAME = "src.api.services.chat_service.get_current_username"

_EDITED_HTML = '<div class="slide"><h2>Edited by a human</h2></div>'


@pytest.fixture
def api(client, test_db_factory):
    """The savepoint harness's TestClient, with spec_sync pointed at its engine.

    `client` is built first, so its patches are already active; this only adds the
    targets it does not know about: the spec_sync and deck_level_writer db sessions,
    and chat_service's Databricks username lookup which would otherwise reach a
    non-resolving host and hang indefinitely under CI credentials.
    """
    fake = _make_fake_get_db_session(test_db_factory)
    with patch(_SPEC_SYNC_DB, fake), patch(_WRITER_DB, fake):
        with patch(_CHAT_SERVICE_USERNAME, return_value="test-user"):
            yield client


def _marker(test_db_factory, session_id: str) -> SessionSlideDeck:
    """Read the deck row for *session_id* back on a FRESH session.

    A fresh session each time, so an identity-mapped object from an earlier read
    cannot mask a write made through a different session.
    """
    db = test_db_factory()
    try:
        owner = (
            db.query(UserSession)
            .filter(UserSession.session_id == session_id)
            .one()
        )
        return (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner.id)
            .one()
        )
    finally:
        db.close()


def _seeded_session(api) -> str:
    """A session with a real 3-slide deck, ready to mutate."""
    session_id = _create_session(api)
    _seed_deck(session_id)
    return session_id


# ---------------------------------------------------------------------------
# Every human mutation route sets the marker
# ---------------------------------------------------------------------------


class TestTheFourHumanRoutesTrigger:
    def test_patch_a_slide_marks_the_deck(self, api, test_db_factory, mock_user):
        session_id = _seeded_session(api)
        assert _marker(test_db_factory, session_id).spec_dirty_at is None

        resp = api.patch(
            "/api/slides/1",
            json={"session_id": session_id, "html": _EDITED_HTML},
        )
        assert resp.status_code == 200, resp.text

        deck = _marker(test_db_factory, session_id)
        assert deck.spec_dirty_at is not None, (
            "a human edited a slide by hand and nothing recorded it: the committed "
            "spec is now silently stale"
        )
        assert deck.spec_dirty_by == "test-user"

    def test_reorder_marks_the_deck_despite_no_html_change(
        self, api, test_db_factory, mock_user
    ):
        """The route a content-hash trigger would miss entirely.

        Reordering mutates the narrative arc — the very thing the spec describes —
        while every slide's HTML stays byte-identical.
        """
        session_id = _seeded_session(api)
        before = {
            s["html"]
            for s in api.get(
                "/api/slides", params={"session_id": session_id}
            ).json()["slides"]
        }

        resp = api.put(
            "/api/slides/reorder",
            json={"session_id": session_id, "new_order": [2, 0, 1]},
        )
        assert resp.status_code == 200, resp.text

        after = {
            s["html"]
            for s in api.get(
                "/api/slides", params={"session_id": session_id}
            ).json()["slides"]
        }
        assert before == after, (
            "fixture precondition: a reorder changes no slide's HTML"
        )
        assert _marker(test_db_factory, session_id).spec_dirty_at is not None

    def test_duplicate_a_slide_marks_the_deck(self, api, test_db_factory, mock_user):
        session_id = _seeded_session(api)

        resp = api.post("/api/slides/0/duplicate", json={"session_id": session_id})
        assert resp.status_code == 200, resp.text

        assert _marker(test_db_factory, session_id).spec_dirty_at is not None

    def test_delete_a_slide_marks_the_deck(self, api, test_db_factory, mock_user):
        """This handler takes session_id from the QUERY STRING, not a body."""
        session_id = _seeded_session(api)

        resp = api.delete("/api/slides/2", params={"session_id": session_id})
        assert resp.status_code == 200, resp.text

        deck = _marker(test_db_factory, session_id)
        assert deck.spec_dirty_at is not None
        assert deck.spec_dirty_by == "test-user"


# ---------------------------------------------------------------------------
# The design's central claim: the route is the human, the service is the graph
# ---------------------------------------------------------------------------


class TestOnlyTheRouteMarksItDirty:
    def test_the_same_edit_via_the_service_does_not_mark_but_via_the_route_does(
        self, api, test_db_factory, mock_user
    ):
        """The whole placement rule, in one test, on one deck.

        `chat_service.update_slide` is exactly what the PATCH handler calls and
        exactly what the graph calls.  Invoked directly it must leave no marker;
        invoked through the route the marker appears.  The absence and the presence
        are asserted against the same session, so neither can be an artefact of a
        path that never ran.
        """
        from src.api.services.chat_service import get_chat_service

        session_id = _seeded_session(api)

        # 1. The graph's way in: the service method, no HTTP request.
        get_chat_service().update_slide(
            session_id, 0, '<div class="slide"><h2>Written by the graph</h2></div>'
        )
        assert _marker(test_db_factory, session_id).spec_dirty_at is None, (
            "an agent write set the dirty marker: the sweeper will now re-describe "
            "the graph's own output on a loop"
        )

        # 2. The human's way in: the same service method, reached via the route.
        resp = api.patch(
            "/api/slides/0",
            json={"session_id": session_id, "html": _EDITED_HTML},
        )
        assert resp.status_code == 200, resp.text
        assert _marker(test_db_factory, session_id).spec_dirty_at is not None

    def test_the_graphs_deck_level_writer_does_not_mark(
        self, api, test_db_factory, mock_user
    ):
        """ws4b's two-pass deck writer is the graph's deck-level write path."""
        from src.api.services.deck_level_writer import write_deck_level_columns

        session_id = _seeded_session(api)

        write_deck_level_columns(
            session_id,
            deck_spec={"title": "Committed by the architect", "narrative_arc": ["a"]},
            modified_by="agent",
        )
        deck = _marker(test_db_factory, session_id)
        assert deck.deck_spec_json is not None, (
            "the graph write did not happen at all, so its absence of a marker "
            "proves nothing"
        )
        assert deck.spec_dirty_at is None

        # PAIRED: the route still marks this same deck.
        resp = api.patch(
            "/api/slides/0",
            json={"session_id": session_id, "html": _EDITED_HTML},
        )
        assert resp.status_code == 200, resp.text
        assert _marker(test_db_factory, session_id).spec_dirty_at is not None


# ---------------------------------------------------------------------------
# The out-of-scope routes, ruled out behaviourally as well as structurally
# ---------------------------------------------------------------------------


class TestTheOutOfScopeRoutesDoNotTrigger:
    def test_a_verification_verdict_does_not_mark_the_deck(
        self, api, test_db_factory, mock_user
    ):
        """A verdict COMPLETES a task a prior change triggered; it is not a change.

        Paired with a real edit on the same deck below.
        """
        session_id = _seeded_session(api)

        resp = api.patch(
            "/api/slides/0/verification",
            json={
                "session_id": session_id,
                "verification": {"score": 91, "rating": "excellent"},
            },
        )
        assert resp.status_code == 200, resp.text
        assert _marker(test_db_factory, session_id).spec_dirty_at is None

        resp = api.patch(
            "/api/slides/0",
            json={"session_id": session_id, "html": _EDITED_HTML},
        )
        assert resp.status_code == 200, resp.text
        assert _marker(test_db_factory, session_id).spec_dirty_at is not None, (
            "the paired edit did not mark either — this test's earlier assertion "
            "was vacuous"
        )

    def test_creating_a_version_does_not_mark_the_deck(
        self, api, test_db_factory, mock_user
    ):
        """A save point leaves the live deck unchanged, so the spec stays true."""
        session_id = _seeded_session(api)

        resp = api.post(
            "/api/slides/versions/create",
            json={"session_id": session_id, "description": "manual save point"},
        )
        assert resp.status_code == 200, resp.text
        assert _marker(test_db_factory, session_id).spec_dirty_at is None

        resp = api.patch(
            "/api/slides/0",
            json={"session_id": session_id, "html": _EDITED_HTML},
        )
        assert resp.status_code == 200, resp.text
        assert _marker(test_db_factory, session_id).spec_dirty_at is not None


# ---------------------------------------------------------------------------
# Coalescing, measured across real requests
# ---------------------------------------------------------------------------


class TestABurstOfEditsCoalesces:
    def test_three_edits_keep_the_first_windows_timestamp(
        self, api, test_db_factory, mock_user
    ):
        """The debounce window must not recede while a human keeps typing."""
        session_id = _seeded_session(api)

        api.patch(
            "/api/slides/0",
            json={"session_id": session_id, "html": _EDITED_HTML + "<!--1-->"},
        )
        first = _marker(test_db_factory, session_id).spec_dirty_at
        assert first is not None

        for n in (2, 3):
            resp = api.patch(
                "/api/slides/0",
                json={
                    "session_id": session_id,
                    "html": f"{_EDITED_HTML}<!--{n}-->",
                },
            )
            assert resp.status_code == 200, resp.text

        assert _marker(test_db_factory, session_id).spec_dirty_at == first

    def test_a_failed_edit_does_not_mark_the_deck(
        self, api, test_db_factory, mock_user
    ):
        """The trigger sits AFTER the mutation, so a rejected edit marks nothing.

        A 400 means the deck is unchanged and its spec still describes it.
        """
        session_id = _seeded_session(api)

        resp = api.patch(
            "/api/slides/99",
            json={"session_id": session_id, "html": _EDITED_HTML},
        )
        assert resp.status_code == 400, resp.text
        assert _marker(test_db_factory, session_id).spec_dirty_at is None

        resp = api.patch(
            "/api/slides/0",
            json={"session_id": session_id, "html": _EDITED_HTML},
        )
        assert resp.status_code == 200, resp.text
        assert _marker(test_db_factory, session_id).spec_dirty_at is not None


class TestTheMarkerDoesNotDisturbTheEditingClient:
    def test_two_consecutive_version_checked_edits_both_succeed(
        self, api, test_db_factory, mock_user
    ):
        """A marker write that bumped `version` would 409 the client's next save.

        The client reads the deck's version, edits with it, then edits again with
        the version its own edit produced.  If `mark_dirty` bumped the counter in
        between, the second request would be rejected as stale.
        """
        session_id = _seeded_session(api)

        version = _marker(test_db_factory, session_id).version
        resp = api.patch(
            "/api/slides/0",
            json={
                "session_id": session_id,
                "html": _EDITED_HTML + "<!--a-->",
                "expected_version": version,
            },
        )
        assert resp.status_code == 200, resp.text
        assert _marker(test_db_factory, session_id).spec_dirty_at is not None

        version = _marker(test_db_factory, session_id).version
        resp = api.patch(
            "/api/slides/0",
            json={
                "session_id": session_id,
                "html": _EDITED_HTML + "<!--b-->",
                "expected_version": version,
            },
        )
        assert resp.status_code == 200, (
            "the second optimistic-lock edit was rejected: something bumped the "
            f"deck version behind the client's back ({resp.status_code})"
        )
