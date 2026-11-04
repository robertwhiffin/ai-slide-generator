"""What a deck open downloads (prod profiling, 2026-11-04).

A deck open on prod took 19 s in a browser trace while the server answered each
request in ~0.65 s.  The rest was download: the same uncompressed 3.16 MB deck
JSON was fetched three times in series (``GET /api/sessions/{id}``, then
``GET /api/sessions/{id}/slides``, then ``GET /api/sessions/{id}`` again for the
chat), and 1.56 MB of each copy was ``html_content``, a knitted duplicate of the
deck that no screen renders.

Pinned here, through the full stack (savepoint e2e harness, in-memory SQLite):

- ``GET /api/sessions/{id}?include_deck=false`` returns the session without the
  deck and never loads it.  The default still includes it, for API callers.
- The REST deck reads do not send ``html_content``.
- JSON responses are gzip-encoded for a client that accepts it, and an SSE
  response through the same middleware stack is not.

SABOTAGE (each run against a throwaway change, then reverted):
- ignore ``include_deck`` in ``get_session``          -> the two include_deck REDs.
- drop only the key but still call get_slide_deck     -> "never loads" RED.
- remove the ``html_content`` pop from either route   -> that route's RED.
- remove the GZipMiddleware registration              -> gzip RED.
- empty starlette's DEFAULT_EXCLUDED_CONTENT_TYPES    -> SSE RED.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.responses import StreamingResponse

from src.api.services.session_manager import SessionManager
from src.database.models.session import SessionSlideDeck, UserSession
from tests.integration.test_savepoint_e2e import (  # noqa: F401 — pytest fixtures
    _create_session,
    _make_fake_get_db_session,
    _seed_deck,
    active_graph_release,
    client,
    mock_user,
    reset_singletons,
    test_db,
    test_db_engine,
    test_db_factory,
)

_SPEC_SYNC_DB = "src.services.spec_sync.get_db_session"
_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
_CHAT_SERVICE_USERNAME = "src.api.services.chat_service.get_current_username"


@pytest.fixture
def api(client, test_db_factory, monkeypatch, mock_user):
    """The savepoint TestClient plus the patches every deck read needs (as in
    ``test_slide_number_token_boundaries``): spec_sync and the deck-level writer
    on the test database, and SCIM display names neutralised (a real lookup runs
    on every ``get_slide_deck`` and retries)."""
    monkeypatch.setattr(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    )
    fake = _make_fake_get_db_session(test_db_factory)
    with patch(_SPEC_SYNC_DB, fake), patch(_WRITER_DB, fake):
        with patch(_CHAT_SERVICE_USERNAME, return_value="test-user"):
            yield client


@pytest.fixture
def deck_session(api, test_db_factory) -> str:
    """A session whose stored deck has slides AND a non-empty html_content."""
    session_id = _create_session(api)
    _seed_deck(session_id)
    db = test_db_factory()
    try:
        owner = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        stored = db.query(SessionSlideDeck).filter(SessionSlideDeck.session_id == owner.id).one()
        assert stored.html_content, "precondition: the stored deck has html_content"
    finally:
        db.close()
    return session_id


# -- include_deck --------------------------------------------------------------


def test_session_read_without_deck_omits_the_deck(api, deck_session):
    resp = api.get(f"/api/sessions/{deck_session}", params={"include_deck": "false"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "slide_deck" not in body
    # Everything a caller of the light read relies on is still there.
    assert body["has_slide_deck"] is True
    assert body["messages"] == []
    assert body["my_permission"] == "CAN_MANAGE"


def test_session_read_without_deck_never_loads_the_deck(api, deck_session):
    with patch.object(
        SessionManager, "get_slide_deck", autospec=True, side_effect=SessionManager.get_slide_deck
    ) as spy:
        resp = api.get(f"/api/sessions/{deck_session}", params={"include_deck": "false"})

    assert resp.status_code == 200, resp.text
    assert spy.call_count == 0


def test_session_read_includes_the_deck_by_default(api, deck_session):
    """Back-compat guard for API callers: no parameter, same deck as before."""
    resp = api.get(f"/api/sessions/{deck_session}")

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["slide_deck"]["slides"]) == 3


# -- html_content ----------------------------------------------------------------


def test_slides_read_does_not_send_html_content(api, deck_session):
    resp = api.get(f"/api/sessions/{deck_session}/slides")

    assert resp.status_code == 200, resp.text
    deck = resp.json()["slide_deck"]
    assert len(deck["slides"]) == 3
    assert "html_content" not in deck


def test_session_read_with_deck_does_not_send_html_content(api, deck_session):
    resp = api.get(f"/api/sessions/{deck_session}")

    assert resp.status_code == 200, resp.text
    deck = resp.json()["slide_deck"]
    assert len(deck["slides"]) == 3
    assert "html_content" not in deck


# -- compression -------------------------------------------------------------------


def test_deck_read_is_gzip_encoded_when_the_client_accepts_it(api, deck_session):
    resp = api.get(
        f"/api/sessions/{deck_session}/slides", headers={"Accept-Encoding": "gzip"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-encoding") == "gzip"
    # httpx decodes it: the client still reads the same deck.
    assert len(resp.json()["slide_deck"]["slides"]) == 3


@pytest.fixture
def sse_probe_path():
    """A throwaway SSE route on the REAL app, first in the route table so no
    catch-all shadows it.  The chat stream needs a whole turn to drive; this
    isolates the one property under test — the middleware stack leaves
    ``text/event-stream`` alone, so events are not held for compression."""
    from src.api.main import app

    path = "/api/__test_sse_probe"

    async def probe():
        async def events():
            for i in range(3):
                yield f"data: {'x' * 400} {i}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    app.add_api_route(path, probe, methods=["GET"])
    route = app.router.routes.pop()
    app.router.routes.insert(0, route)
    try:
        yield path
    finally:
        app.router.routes.remove(route)


def test_event_stream_is_not_gzip_encoded(api, sse_probe_path):
    resp = api.get(sse_probe_path, headers={"Accept-Encoding": "gzip"})

    assert resp.status_code == 200, resp.text
    assert "content-encoding" not in resp.headers
    assert resp.text.count("data: ") == 3
