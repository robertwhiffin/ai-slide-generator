"""`POST /api/slides`, end to end: the insert capability, and its trigger.

The structural half lives in `tests/unit/test_spec_sync_placement.py` (the route
exists and its handler names `mark_dirty`) and the service half in
`tests/unit/test_insert_slide_service.py`.  Neither can prove what this file does:
that driving the real HTTP route through the real service stack against a real
database inserts the slide AND lands a marker on the deck row — and that the same
mutation invoked as a service method, the way the graph invokes it, does not.

That pairing is the point.  "A graph insert does not set the marker" is an absence
assertion, equally true of a `mark_dirty` that never runs at all, so the test that
asserts the absence asserts the presence on the same deck in the same test.

Harness reused from tests/integration/test_savepoint_e2e.py, with the two patches
that harness does not know about: `mark_dirty` and `write_deck_level_columns` each
open their OWN `get_db_session`, so without them the marker write and the deck-spec
write reach whatever database the environment points at.
"""
from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession

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
_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
# Every slide-mutation method in chat_service calls get_current_username() to stamp
# modified_by / created_by on Slide objects.  On a laptop load_dotenv() supplies real
# Databricks credentials, so the call returns in milliseconds and was invisible.
# In CI, DATABRICKS_HOST is a non-empty but unreachable value
# ("https://test.cloud.databricks.com"); the SDK enters a retry loop that sleeps
# rather than raising, and the job hung for 604+ seconds before it was cancelled.
# The username is incidental plumbing for this suite (the test subject is the
# insert-slide route, not Databricks identity resolution), so we stub it here at
# the module boundary where chat_service binds the name.
_CHAT_SERVICE_USERNAME = "src.api.services.chat_service.get_current_username"

_NEW_HTML = '<div class="slide"><h2>Inserted by a human</h2></div>'

_SPEC = {
    "title": "Route insert deck",
    "audience": "test",
    "purpose": "test",
    "argument": "test",
    "call_to_action": "test",
    "narrative_arc": ["a", "b", "c"],
    "design_contract": {
        "design_system_id": None,
        "template_id": None,
        "slide_style_id": None,
    },
    "resolved_data": {"synthesis": "s", "figures": [], "gaps": []},
    "slides": [
        {
            "position": i,
            "purpose": f"PURPOSE-{i}",
            "content_brief": "",
            "assumes": "",
            "hands_off": "",
            "data_references": [],
        }
        for i in range(3)
    ],
}


@pytest.fixture
def api(client, test_db_factory):
    """The savepoint harness's TestClient, with spec_sync, deck_level_writer, and
    the Databricks username lookup all redirected away from the environment's host.

    `client` is built first, so its patches are already active; this only adds the
    targets it does not know about: the spec_sync and deck_level_writer db sessions,
    and chat_service's Databricks username lookup which would otherwise reach a
    non-resolving host and hang indefinitely under CI credentials.
    """
    fake = _make_fake_get_db_session(test_db_factory)
    with patch(_SPEC_SYNC_DB, fake), patch(_WRITER_DB, fake):
        with patch(_CHAT_SERVICE_USERNAME, return_value="test-user"):
            yield client


def _deck_row(test_db_factory, session_id: str) -> SessionSlideDeck:
    """Read the deck row back on a FRESH session.

    A fresh session each time, so an identity-mapped object from an earlier read
    cannot mask a write made through a different one.
    """
    db = test_db_factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == session_id).one()
        )
        return (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner.id)
            .one()
        )
    finally:
        db.close()


def _row_htmls(test_db_factory, session_id: str):
    db = test_db_factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == session_id).one()
        )
        return [
            r.html
            for r in db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner.id)
            .order_by(SessionSlide.position)
            .all()
        ]
    finally:
        db.close()


def _seeded_session(api, test_db_factory, with_spec: bool = False) -> str:
    session_id = _create_session(api)
    _seed_deck(session_id)
    if with_spec:
        db = test_db_factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .one()
            )
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner.id)
                .one()
            )
            deck.deck_spec_json = json.dumps(_SPEC)
            db.commit()
        finally:
            db.close()
    return session_id


# ---------------------------------------------------------------------------
# The capability
# ---------------------------------------------------------------------------


class TestTheRouteInsertsTheSlide:
    def test_the_slide_lands_at_the_requested_position(
        self, api, test_db_factory, mock_user
    ):
        session_id = _seeded_session(api, test_db_factory)
        before = _row_htmls(test_db_factory, session_id)
        assert len(before) == 3, "fixture precondition: a 3-slide deck"

        resp = api.post(
            "/api/slides",
            json={"session_id": session_id, "position": 1, "html": _NEW_HTML},
        )
        assert resp.status_code == 200, resp.text

        after = _row_htmls(test_db_factory, session_id)
        assert after == [before[0], _NEW_HTML, before[1], before[2]], (
            "the slide did not land at position 1 with every higher slide shifted "
            "up by one, identity intact"
        )

    def test_inserting_beyond_the_end_appends_rather_than_erroring(
        self, api, test_db_factory, mock_user
    ):
        session_id = _seeded_session(api, test_db_factory)
        before = _row_htmls(test_db_factory, session_id)

        resp = api.post(
            "/api/slides",
            json={"session_id": session_id, "position": 99, "html": _NEW_HTML},
        )
        assert resp.status_code == 200, resp.text
        assert _row_htmls(test_db_factory, session_id) == before + [_NEW_HTML]

    def test_a_negative_position_is_a_400_and_changes_nothing(
        self, api, test_db_factory, mock_user
    ):
        session_id = _seeded_session(api, test_db_factory)
        before = _row_htmls(test_db_factory, session_id)

        resp = api.post(
            "/api/slides",
            json={"session_id": session_id, "position": -1, "html": _NEW_HTML},
        )
        assert resp.status_code == 400, resp.text
        assert _row_htmls(test_db_factory, session_id) == before

    def test_the_deck_spec_gains_an_entry_and_higher_entries_shift(
        self, api, test_db_factory, mock_user
    ):
        session_id = _seeded_session(api, test_db_factory, with_spec=True)

        resp = api.post(
            "/api/slides",
            json={"session_id": session_id, "position": 1, "html": _NEW_HTML},
        )
        assert resp.status_code == 200, resp.text

        spec = json.loads(_deck_row(test_db_factory, session_id).deck_spec_json)
        by_position = {e["position"]: e["purpose"] for e in spec["slides"]}
        assert sorted(by_position) == [0, 1, 2, 3], (
            f"spec positions are not contiguous: {spec['slides']}"
        )
        assert by_position[1] == "", "the new position has no placeholder entry"
        assert by_position[2] == "PURPOSE-1", (
            f"the spec entry for the displaced slide did not shift: {by_position}"
        )


# ---------------------------------------------------------------------------
# The trigger — C-1's obligation, in behaviour rather than in structure
# ---------------------------------------------------------------------------


class TestTheInsertRouteFiresTheTrigger:
    def test_inserting_a_slide_marks_the_deck(self, api, test_db_factory, mock_user):
        session_id = _seeded_session(api, test_db_factory)
        assert _deck_row(test_db_factory, session_id).spec_dirty_at is None

        resp = api.post(
            "/api/slides",
            json={"session_id": session_id, "position": 1, "html": _NEW_HTML},
        )
        assert resp.status_code == 200, resp.text

        deck = _deck_row(test_db_factory, session_id)
        assert deck.spec_dirty_at is not None, (
            "a human inserted a slide and nothing recorded it: the committed spec "
            "now describes a deck with a slide it has never seen"
        )
        assert deck.spec_dirty_by == "test-user"

    def test_the_same_insert_via_the_service_does_not_mark_but_via_the_route_does(
        self, api, test_db_factory, mock_user
    ):
        """The placement rule, on one deck, in one test.

        `chat_service.insert_slide` is exactly what the handler calls and exactly
        what the architect will call.  Invoked directly it must leave no marker;
        reached through the route the marker appears.  Asserting both against the
        same session is what stops the absence from being an artefact of a path
        that never ran.
        """
        from src.api.services.chat_service import get_chat_service

        session_id = _seeded_session(api, test_db_factory)

        get_chat_service().insert_slide(
            session_id, 0, html='<div class="slide"><h2>By the graph</h2></div>'
        )
        assert _row_htmls(test_db_factory, session_id)[0] == (
            '<div class="slide"><h2>By the graph</h2></div>'
        ), "the service insert did not happen, so its absence of a marker proves nothing"
        assert _deck_row(test_db_factory, session_id).spec_dirty_at is None, (
            "an agent insert set the dirty marker: the sweeper will now re-describe "
            "the graph's own output on a loop"
        )

        resp = api.post(
            "/api/slides",
            json={"session_id": session_id, "position": 1, "html": _NEW_HTML},
        )
        assert resp.status_code == 200, resp.text
        assert _deck_row(test_db_factory, session_id).spec_dirty_at is not None

    def test_a_rejected_insert_does_not_mark_the_deck(
        self, api, test_db_factory, mock_user
    ):
        """The trigger sits AFTER the mutation, so a 400 marks nothing.

        Paired with a successful insert on the same deck, or "no marker" would be
        true of a route that never marks at all.
        """
        session_id = _seeded_session(api, test_db_factory)

        resp = api.post(
            "/api/slides",
            json={"session_id": session_id, "position": 1, "html": "<p>no wrapper</p>"},
        )
        assert resp.status_code == 400, resp.text
        assert _deck_row(test_db_factory, session_id).spec_dirty_at is None

        resp = api.post(
            "/api/slides",
            json={"session_id": session_id, "position": 1, "html": _NEW_HTML},
        )
        assert resp.status_code == 200, resp.text
        assert _deck_row(test_db_factory, session_id).spec_dirty_at is not None, (
            "the paired insert did not mark either — this test's earlier assertion "
            "was vacuous"
        )


# ---------------------------------------------------------------------------
# The single-direction trap: a contributor's request
# ---------------------------------------------------------------------------


class TestAContributorsInsertReachesTheOwnersDeck:
    def test_a_contributor_session_inserts_into_the_owners_deck(
        self, api, test_db_factory, mock_user
    ):
        """A contributor session has no deck of its own; the write must resolve.

        A standalone-session test cannot tell "resolved the deck owner" from
        "happened to be the deck owner", so it is asserted here through the real
        route as well as at the service level.
        """
        owner_sid = _seeded_session(api, test_db_factory)
        before = _row_htmls(test_db_factory, owner_sid)

        db = test_db_factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == owner_sid)
                .one()
            )
            db.add(
                UserSession(
                    session_id="route-contrib-sess",
                    created_by="test-user",
                    parent_session_id=owner.id,
                )
            )
            db.commit()
        finally:
            db.close()

        resp = api.post(
            "/api/slides",
            json={
                "session_id": "route-contrib-sess",
                "position": 1,
                "html": _NEW_HTML,
            },
        )
        assert resp.status_code == 200, resp.text

        assert _row_htmls(test_db_factory, owner_sid) == [
            before[0],
            _NEW_HTML,
            before[1],
            before[2],
        ], "the contributor's insert did not reach the owner's deck"

        # The marker belongs on the OWNER's deck row too — that is the row the
        # sweeper claims from.
        assert _deck_row(test_db_factory, owner_sid).spec_dirty_at is not None, (
            "the contributor's insert marked something other than the owner's deck"
        )
