"""Live page-number tokens at every reader boundary and every save path (Task B1).

Stored slide HTML keeps ``{{slide:number}}`` / ``{{slide:count}}``.  What a reader
receives carries ``<span data-tellr-slide="number">N</span>`` /
``<span data-tellr-slide="count">M</span>``, where N is the slide's position in
the deck's CURRENT order plus one and M is the deck's slide count.  A save turns
the marker spans back into tokens, so a slide whose rendered HTML was edited and
saved still renumbers after a move.

The boundaries (PLAN-CORRECTIONS-A A1, A2, A6; ruling RA1), each driven through
its real entry point:

======================================================  ===========================
boundary                                                 how it is driven here
======================================================  ===========================
``GET /api/sessions/{id}/slides`` (the UI's read)        HTTP, full stack
``GET /api/sessions/{id}``                               HTTP, full stack
``GET /api/slides`` -> ``ChatService.get_slides``        HTTP, full stack
``ChatService.get_slides`` (every server export, the     the service, full stack
graph COMPLETE event)
version preview ``GET /api/slides/versions/{n}``         HTTP, full stack
version restore ``POST /api/slides/versions/{n}/restore``  HTTP, full stack (A2)
MCP ``_render_deck_response``                            the shared serialiser
SSE ``slide_ready`` (``_release_slides``)                the foreman's release
``/chat/poll`` ``slides`` and ``slide_revisions``        HTTP over real rows (A6)
======================================================  ===========================

Save paths (A5): ``PATCH /api/slides/{i}`` -> ``update_slide`` and ``POST
/api/slides`` with ``html`` -> ``insert_slide``.

Also pinned (A3): the substitution is on the OUTGOING copy only.  The rows, the
deck the cache and every mutation round-trip (``get_slide_deck``,
``_get_or_load_deck``), the version snapshots and the ``content_hash`` a reader is
sent all stay on the stored, tokenised HTML.

And the old-deck guard: a deck with no token is byte-identical on every reader,
and a save of HTML with no marker stores it verbatim.  Those pass today and must
stay green.

Harness: ``tests/integration/test_savepoint_e2e.py``'s TestClient over in-memory
SQLite, with the extra patches ``test_slide_id_is_durable.py`` adds; the poll
fixture follows ``test_poll_route_across_an_insert.py``; the SSE half follows
``test_slide_release.py``; the MCP half follows ``test_mcp_server.py``.

Every oracle is a literal built here with ``str.replace``, never a value computed
by the code under test.  Slides are identified by the marker in their own HTML,
never by position alone.
"""
from __future__ import annotations

import contextlib
import base64
import queue
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — registers every ORM model on Base
from src.api.schemas.streaming import StreamEventType
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import SlideWriter
from src.core.database import Base, _run_migrations
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import _release_slides
from src.services.graph.state import scoped
from src.utils.slide_hash import compute_slide_hash
from tests.integration.test_savepoint_e2e import (  # noqa: F401 — pytest fixtures
    _create_session,
    _make_fake_get_db_session,
    client,
    mock_user,
    reset_singletons,
    test_db,
    test_db_engine,
    test_db_factory,
)
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    graph_env,
    make_spec,
)

NUMBER = "{{slide:number}}"
COUNT = "{{slide:count}}"
PAGE_TOKENS = NUMBER + " / " + COUNT
MARKER_ATTR = "data-tellr-slide"


def _numbered(number: int, count: int) -> str:
    return (
        f'<span data-tellr-slide="number">{number}</span> / '
        f'<span data-tellr-slide="count">{count}</span>'
    )


def _slide(marker: str, page: str = PAGE_TOKENS) -> str:
    """A graph slide whose footer carries *page* (the tokens, or what a reader
    renders for them).  No ``{{image:`` or ``{{ds-asset:`` on purpose: the
    ds-asset substitution is gated on those (A4), and a token-only deck must
    still be numbered."""
    return (
        '<div class="slide"><h1>' + marker + "</h1><p>body of " + marker + "</p>"
        '<div class="slide-footer"><span>Acme</span><span>' + page + "</span></div></div>"
    )


def _legacy_slide(marker: str) -> str:
    """A pre-addendum slide: a baked footer, no token, no marker."""
    return (
        "<div class='slide'><h1>" + marker + "</h1>"
        '<div class="footer"><span>Databricks</span><span>2026</span></div></div>'
    )


MARKERS = ["MK-ALPHA", "MK-BRAVO", "MK-CHARLIE"]
_MARKER_RE = re.compile(r"MK-[A-Z]+(?:-EDITED)?")


def _which(html: str) -> str:
    found = set(_MARKER_RE.findall(html or ""))
    assert len(found) == 1, f"a payload that is not exactly one slide: {html!r}"
    return found.pop()


# ---------------------------------------------------------------------------
# Full-stack harness (savepoint e2e + the durable-id suite's extra patches)
# ---------------------------------------------------------------------------

_SPEC_SYNC_DB = "src.services.spec_sync.get_db_session"
_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
_CHAT_SERVICE_USERNAME = "src.api.services.chat_service.get_current_username"


@pytest.fixture
def api(client, test_db_factory, monkeypatch):
    """The savepoint harness's TestClient with spec_sync, deck_level_writer and the
    username lookup redirected, and SCIM display names neutralised (they run on
    every ``get_slide_deck`` and a real client retries and hangs)."""
    from src.services.graph_configuration import bootstrap_graph_configuration

    monkeypatch.setattr(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    )
    bootstrap_graph_configuration(test_db_factory)
    fake = _make_fake_get_db_session(test_db_factory)
    with patch(_SPEC_SYNC_DB, fake), patch(_WRITER_DB, fake):
        with patch(_CHAT_SERVICE_USERNAME, return_value="test-user"):
            yield client


def _seed(session_id: str, htmls: List[str]) -> None:
    """Seed the cache and the database with exactly these slides, verbatim.

    ``_seed_deck`` parses a whole HTML document; this builds the deck from the
    slides themselves so the stored HTML is byte-for-byte what the test wrote.
    """
    from src.api.services.chat_service import get_chat_service
    from src.api.services.session_manager import get_session_manager

    deck = SlideDeck(
        title="Token deck",
        slides=[
            Slide(html=h, slide_id=f"sid-{i}-{uuid.uuid4().hex[:6]}")
            for i, h in enumerate(htmls)
        ],
    )
    service = get_chat_service()
    with service._cache_lock:
        service._deck_cache[session_id] = deck
    get_session_manager().save_slide_deck(
        session_id=session_id,
        title=deck.title,
        html_content=deck.knit(),
        slide_count=len(deck.slides),
        deck_dict=deck.to_dict(),
    )


def _row_htmls(test_db_factory, session_id: str) -> List[str]:
    """Every stored slide's HTML in position order, on a FRESH session."""
    db = test_db_factory()
    try:
        owner = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        return [
            r.html
            for r in db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner.id)
            .order_by(SessionSlide.position)
            .all()
        ]
    finally:
        db.close()


def _version_snapshots(test_db_factory, session_id: str) -> List[str]:
    """The raw ``deck_json`` of every save point, as stored."""
    db = test_db_factory()
    try:
        owner = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        return [
            v.deck_json
            for v in db.query(SlideDeckVersion)
            .filter(SlideDeckVersion.session_id == owner.id)
            .order_by(SlideDeckVersion.version_number)
            .all()
        ]
    finally:
        db.close()


def _seeded(api, test_db_factory, htmls: List[str]) -> str:
    session_id = _create_session(api)
    _seed(session_id, htmls)
    assert _row_htmls(test_db_factory, session_id) == htmls, (
        "precondition: the rows hold exactly the seeded HTML"
    )
    return session_id


def _htmls(slides: List[Dict[str, Any]]) -> List[str]:
    return [s["html"] for s in slides]


# -- the readers -------------------------------------------------------------


def _read_session_slides(api, session_id: str) -> List[str]:
    resp = api.get(f"/api/sessions/{session_id}/slides")
    assert resp.status_code == 200, resp.text
    return _htmls(resp.json()["slide_deck"]["slides"])


def _read_session(api, session_id: str) -> List[str]:
    resp = api.get(f"/api/sessions/{session_id}")
    assert resp.status_code == 200, resp.text
    return _htmls(resp.json()["slide_deck"]["slides"])


def _read_api_slides(api, session_id: str) -> List[str]:
    resp = api.get("/api/slides", params={"session_id": session_id})
    assert resp.status_code == 200, resp.text
    return _htmls(resp.json()["slides"])


def _read_chat_service_get_slides(api, session_id: str) -> List[str]:
    """The read every server export makes first (export.py, export_job_queue,
    google_slides) and the graph COMPLETE event's ``slides`` (A1)."""
    from src.api.services.chat_service import get_chat_service

    return _htmls(get_chat_service().get_slides(session_id)["slides"])


def _create_savepoint(api, session_id: str) -> int:
    resp = api.post(
        "/api/slides/versions/create",
        json={"session_id": session_id, "description": "token save point"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["version_number"]


def _read_version_preview(api, session_id: str) -> List[str]:
    version = _create_savepoint(api, session_id)
    resp = api.get(f"/api/slides/versions/{version}", params={"session_id": session_id})
    assert resp.status_code == 200, resp.text
    return _htmls(resp.json()["deck"]["slides"])


def _read_version_restore(api, session_id: str) -> List[str]:
    """The restore RESPONSE is a reader: the client renders ``result.deck``
    directly (AppLayout.tsx), with no refetch (A2)."""
    version = _create_savepoint(api, session_id)
    resp = api.post(
        f"/api/slides/versions/{version}/restore", json={"session_id": session_id}
    )
    assert resp.status_code == 200, resp.text
    return _htmls(resp.json()["deck"]["slides"])


READERS = [
    pytest.param(_read_session_slides, id="GET-sessions-id-slides"),
    pytest.param(_read_session, id="GET-sessions-id"),
    pytest.param(_read_api_slides, id="GET-api-slides"),
    pytest.param(_read_chat_service_get_slides, id="ChatService.get_slides-exports"),
    pytest.param(_read_version_preview, id="version-preview"),
    pytest.param(_read_version_restore, id="version-restore"),
]


# ===========================================================================
# Every HTTP / service reader substitutes, on its outgoing copy only
# ===========================================================================


class TestEveryReaderNumbersTheSlides:
    @pytest.mark.parametrize("read", READERS)
    def test_the_reader_renders_the_tokens_at_each_slides_position(
        self, api, test_db_factory, mock_user, read
    ):
        stored = [_slide(m) for m in MARKERS]
        session_id = _seeded(api, test_db_factory, stored)

        received = read(api, session_id)

        assert received == [
            _slide("MK-ALPHA", _numbered(1, 3)),
            _slide("MK-BRAVO", _numbered(2, 3)),
            _slide("MK-CHARLIE", _numbered(3, 3)),
        ]
        assert not any(NUMBER in h or COUNT in h for h in received), (
            "a reader shipped a literal page token"
        )

    @pytest.mark.parametrize("read", READERS)
    def test_the_rows_and_the_save_points_keep_the_tokens(
        self, api, test_db_factory, mock_user, read
    ):
        """A3: a reader that substituted in place on a dict that is later
        persisted (the restore's row rewrite, a snapshot, the cache) would bake
        today's numbers into storage and they would go stale on the next move."""
        stored = [_slide(m) for m in MARKERS]
        session_id = _seeded(api, test_db_factory, stored)

        received = read(api, session_id)

        # ENTRY: the reader really substituted, so "storage still holds tokens"
        # is not true merely because nothing ran.
        assert received[0] == _slide("MK-ALPHA", _numbered(1, 3))
        assert _row_htmls(test_db_factory, session_id) == stored
        for snapshot in _version_snapshots(test_db_factory, session_id):
            assert MARKER_ATTR not in snapshot, (
                "a save point stored rendered numbers instead of the tokens"
            )

    @pytest.mark.parametrize("read", READERS)
    def test_a_legacy_deck_is_byte_identical(self, api, test_db_factory, mock_user, read):
        stored = [_legacy_slide(m) for m in MARKERS]
        session_id = _seeded(api, test_db_factory, stored)

        assert read(api, session_id) == stored


class TestTheSubstitutionIsOnTheOutgoingCopyOnly:
    def test_the_internal_deck_read_and_the_cache_keep_the_tokens(
        self, api, test_db_factory, mock_user
    ):
        """``get_slide_deck`` feeds ``_get_or_load_deck``, every mutation's
        ``save_slide_deck`` and the verification route; numbers put there reach
        the database on the next mutation (A3)."""
        from src.api.services.chat_service import get_chat_service
        from src.api.services.session_manager import get_session_manager

        stored = [_slide(m) for m in MARKERS]
        session_id = _seeded(api, test_db_factory, stored)
        # ENTRY: a reader really did substitute in this process first.
        assert _read_session_slides(api, session_id)[0] == _slide(
            "MK-ALPHA", _numbered(1, 3)
        )
        _read_api_slides(api, session_id)

        assert _htmls(get_session_manager().get_slide_deck(session_id)["slides"]) == stored
        service = get_chat_service()
        service._invalidate_deck_cache(session_id)
        assert [s.html for s in service._get_or_load_deck(session_id).slides] == stored

    def test_the_content_hash_a_reader_sends_is_the_stored_htmls(
        self, api, test_db_factory, mock_user
    ):
        """The frontend's auto-verify and the verdict lookup key on
        ``content_hash``; it must be the hash of what is stored, computed before
        any substitution (A3)."""
        stored = [_slide(m) for m in MARKERS]
        session_id = _seeded(api, test_db_factory, stored)

        resp = api.get(f"/api/sessions/{session_id}/slides")
        assert resp.status_code == 200, resp.text
        slides = resp.json()["slide_deck"]["slides"]
        assert _htmls(slides)[1] == _slide("MK-BRAVO", _numbered(2, 3)), "ENTRY"
        assert [s["content_hash"] for s in slides] == [
            compute_slide_hash(h) for h in stored
        ]

        version = _create_savepoint(api, session_id)
        preview = api.get(
            f"/api/slides/versions/{version}", params={"session_id": session_id}
        ).json()
        assert _htmls(preview["deck"]["slides"])[2] == _slide(
            "MK-CHARLIE", _numbered(3, 3)
        ), "ENTRY"
        assert [s["content_hash"] for s in preview["deck"]["slides"]] == [
            compute_slide_hash(h) for h in stored
        ]


# ===========================================================================
# The save paths turn marker spans back into tokens
# ===========================================================================


class TestTheSavePathsStoreTokens:
    def test_update_slide_stores_tokens_not_numbers(
        self, api, test_db_factory, mock_user
    ):
        """PATCH /api/slides/{i}: the HTML and visual editors both save through it
        (A5 (a)), handing back the RENDERED html they were given, edited."""
        session_id = _seeded(api, test_db_factory, [_slide(m) for m in MARKERS])
        rendered = _read_session_slides(api, session_id)[1]
        assert rendered == _slide("MK-BRAVO", _numbered(2, 3)), "ENTRY"
        edited = rendered.replace("MK-BRAVO", "MK-BRAVO-EDITED")

        resp = api.patch(
            "/api/slides/1", json={"session_id": session_id, "html": edited}
        )
        assert resp.status_code == 200, resp.text

        assert _row_htmls(test_db_factory, session_id)[1] == _slide("MK-BRAVO-EDITED")
        assert resp.json()["html"] == _slide("MK-BRAVO-EDITED"), (
            "update_slide returns the html it stored, so it returns the tokens (A5)"
        )
        snapshots = _version_snapshots(test_db_factory, session_id)
        assert snapshots, "ENTRY: update_slide creates a save point"
        assert MARKER_ATTR not in snapshots[-1]
        assert "MK-BRAVO-EDITED" in snapshots[-1] and NUMBER in snapshots[-1]

    def test_update_slide_retokenises_what_the_visual_editor_reserialised(
        self, api, test_db_factory, mock_user
    ):
        """DOMParser/innerHTML may switch the quote style, and a human may add an
        attribute to the span; the marker is still recognised (A7)."""
        session_id = _seeded(api, test_db_factory, [_slide(m) for m in MARKERS])
        reserialised = _slide(
            "MK-BRAVO-EDITED",
            "<span data-tellr-slide='number'>2</span> / "
            '<span style="opacity:.6" data-tellr-slide="count">3</span>',
        )

        resp = api.patch(
            "/api/slides/1", json={"session_id": session_id, "html": reserialised}
        )
        assert resp.status_code == 200, resp.text

        assert _row_htmls(test_db_factory, session_id)[1] == _slide("MK-BRAVO-EDITED")

    def test_insert_slide_with_html_stores_tokens_not_numbers(
        self, api, test_db_factory, mock_user
    ):
        """POST /api/slides with ``html`` (A5 (b)): HTML copied from a rendered
        slide carries that slide's numbers; stored, it must carry the tokens, and
        read back it is numbered where it landed."""
        session_id = _seeded(api, test_db_factory, [_slide(m) for m in MARKERS])
        copied = _slide("MK-DELTA", _numbered(3, 3))

        resp = api.post(
            "/api/slides",
            json={"session_id": session_id, "position": 1, "html": copied},
        )
        assert resp.status_code == 200, resp.text

        assert _row_htmls(test_db_factory, session_id) == [
            _slide("MK-ALPHA"),
            _slide("MK-DELTA"),
            _slide("MK-BRAVO"),
            _slide("MK-CHARLIE"),
        ]
        assert _read_session_slides(api, session_id) == [
            _slide("MK-ALPHA", _numbered(1, 4)),
            _slide("MK-DELTA", _numbered(2, 4)),
            _slide("MK-BRAVO", _numbered(3, 4)),
            _slide("MK-CHARLIE", _numbered(4, 4)),
        ]

    def test_a_value_the_user_rewrote_as_plain_text_is_stored_plain(
        self, api, test_db_factory, mock_user
    ):
        """The editor stripped the number's marker (the user typed their own);
        that one value stays baked, by design (spec Q2).  The count's marker
        survived and goes live again."""
        session_id = _seeded(api, test_db_factory, [_slide(m) for m in MARKERS])
        edited = _slide(
            "MK-BRAVO-EDITED", 'Two / <span data-tellr-slide="count">3</span>'
        )

        resp = api.patch(
            "/api/slides/1", json={"session_id": session_id, "html": edited}
        )
        assert resp.status_code == 200, resp.text

        assert _row_htmls(test_db_factory, session_id)[1] == _slide(
            "MK-BRAVO-EDITED", "Two / " + COUNT
        )

    @pytest.mark.parametrize("path", ["update", "insert"])
    def test_saving_html_without_markers_stores_it_verbatim(
        self, api, test_db_factory, mock_user, path
    ):
        """Old decks are byte-identical in stored HTML (global constraints)."""
        session_id = _seeded(api, test_db_factory, [_legacy_slide(m) for m in MARKERS])
        html = (
            "<div class='slide'  data-x = \"1\"><h1>MK-DELTA</h1>"
            '<div class="footer"><span>Databricks</span><span>2</span></div></div>'
        )
        if path == "update":
            resp = api.patch(
                "/api/slides/1", json={"session_id": session_id, "html": html}
            )
        else:
            resp = api.post(
                "/api/slides",
                json={"session_id": session_id, "position": 1, "html": html},
            )
        assert resp.status_code == 200, resp.text

        assert _row_htmls(test_db_factory, session_id)[1] == html


# ===========================================================================
# The review-focus scenario: a hand-edited slide, then a move
# ===========================================================================


def test_hand_edited_slide_keeps_live_numbers_after_a_move(
    api, test_db_factory, mock_user
):
    """The real UI sequence (A1): the viewer reads through
    ``GET /api/sessions/{id}/slides``, the editor saves the rendered HTML it was
    given through ``PATCH /api/slides/{i}``, the ribbon moves the slide through
    ``PUT /api/slides/reorder``, and the viewer refetches.

    Without re-tokenising on save, the edited slide would carry "2 / 3" baked in
    and still say 2 at position 1.
    """
    session_id = _seeded(api, test_db_factory, [_slide(m) for m in MARKERS])

    # 1. The viewer's read.
    before = _read_session_slides(api, session_id)
    assert before[1] == _slide("MK-BRAVO", _numbered(2, 3))

    # 2. A hand edit of slide 2, saved with the rendered numbers in it.
    edited = before[1].replace("MK-BRAVO", "MK-BRAVO-EDITED")
    resp = api.patch("/api/slides/1", json={"session_id": session_id, "html": edited})
    assert resp.status_code == 200, resp.text

    # 3. Move it to the front.
    resp = api.put(
        "/api/slides/reorder", json={"session_id": session_id, "new_order": [1, 0, 2]}
    )
    assert resp.status_code == 200, resp.text

    # 4. The refetch: the number followed the slide to its new position.
    after = _read_session_slides(api, session_id)
    assert [_which(h) for h in after] == ["MK-BRAVO-EDITED", "MK-ALPHA", "MK-CHARLIE"], (
        "precondition: the reorder moved the edited slide to the front"
    )
    assert after == [
        _slide("MK-BRAVO-EDITED", _numbered(1, 3)),
        _slide("MK-ALPHA", _numbered(2, 3)),
        _slide("MK-CHARLIE", _numbered(3, 3)),
    ]


# ===========================================================================
# MCP: get_deck / get_deck_status share _render_deck_response
# ===========================================================================


@pytest.fixture
def mcp_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _render_mcp(db, deck_dict: dict) -> dict:
    """``_render_deck_response`` as ``get_deck`` calls it, with no design system."""
    from src.api.mcp_server import _render_deck_response

    @contextlib.contextmanager
    def fake_db_session():
        yield db

    manager = MagicMock()
    manager.get_session.return_value = {"agent_config": {}}
    with patch("src.api.mcp_server.get_db_session", fake_db_session), patch(
        "src.api.services.session_manager.get_session_manager", return_value=manager
    ):
        return _render_deck_response(
            deck_dict, {"session_id": "mcp-token-session", "title": "MCP deck"}, ""
        )


def _deck_dict(htmls: List[str]) -> dict:
    return SlideDeck(
        title="MCP deck",
        slides=[Slide(html=h, slide_id=f"sid-{i}") for i, h in enumerate(htmls)],
    ).to_dict()


class TestMcpDeckRender:
    def test_the_deck_and_the_html_document_are_numbered(self, mcp_db):
        result = _render_mcp(mcp_db, _deck_dict([_slide(m) for m in MARKERS]))

        assert _htmls(result["deck"]["slides"]) == [
            _slide("MK-ALPHA", _numbered(1, 3)),
            _slide("MK-BRAVO", _numbered(2, 3)),
            _slide("MK-CHARLIE", _numbered(3, 3)),
        ]
        document = result["html_document"]
        assert _slide("MK-BRAVO", _numbered(2, 3)) in document
        assert "{{slide:" not in document, (
            "the standalone document an MCP client renders carries a literal token"
        )

    def test_a_legacy_deck_is_byte_identical(self, mcp_db):
        stored = [_legacy_slide(m) for m in MARKERS]
        result = _render_mcp(mcp_db, _deck_dict(stored))

        assert _htmls(result["deck"]["slides"]) == stored
        for html in stored:
            assert html in result["html_document"]


# ===========================================================================
# SSE: slide_ready out of the foreman's release
# ===========================================================================

TURN = "turn-page-tokens"


def _commit(env, htmls: Dict[int, str]) -> None:
    writer = SlideWriter()
    for position, html in htmls.items():
        writer.write_slide(
            session_id=env.session_id,
            position=position,
            html=html,
            scripts="",
            modified_by="build_reviewer",
        )


def _release_state(env, *, covered, landed):
    return env.state(
        turn_id=TURN,
        deck_spec=make_spec(tuple(covered)),
        landed_positions=scoped(TURN, set(landed)),
        placeheld_positions=scoped(TURN, set()),
        dispatched_at=scoped(TURN, {p: None for p in covered}),
        foreman_wakes=scoped(TURN, [list(covered)]),
    )


def _drain_slide_ready(emitter: queue.Queue) -> list:
    events = []
    while not emitter.empty():
        event = emitter.get_nowait()
        if event.type is StreamEventType.SLIDE_READY:
            events.append(event)
    return events


def _release(env, state) -> list:
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    try:
        _release_slides(state)
    finally:
        set_event_emitter(None)
    return _drain_slide_ready(emitter)


def test_slide_ready_substitutes_page_tokens(graph_env):
    """Mid-build, three of the spec's five slides have landed.  Each released
    slide is numbered position + 1 of the SPEC's count (5): not the rows'
    count (3), which is what a deck mid-build has (spec Q4, A6)."""
    stored = {p: _slide(MARKERS[p]) for p in range(3)}
    _commit(graph_env, stored)

    events = _release(graph_env, _release_state(graph_env, covered=range(5), landed=range(3)))

    assert [e.position for e in events] == [0, 1, 2], "ENTRY: three slides released"
    assert [e.html for e in events] == [
        _slide("MK-ALPHA", _numbered(1, 5)),
        _slide("MK-BRAVO", _numbered(2, 5)),
        _slide("MK-CHARLIE", _numbered(3, 5)),
    ]
    for released in events:
        assert "{{slide:" not in released.to_sse(), "a literal token reached the client"
    assert [r.html for r in graph_env.rows()] == [stored[p] for p in range(3)], (
        "the release wrote rendered numbers back into the rows"
    )


def test_slide_ready_of_a_legacy_slide_is_byte_identical(graph_env):
    stored = {p: _legacy_slide(MARKERS[p]) for p in range(3)}
    _commit(graph_env, stored)

    events = _release(graph_env, _release_state(graph_env, covered=range(3), landed=range(3)))

    assert [e.html for e in events] == [stored[p] for p in range(3)]


# ===========================================================================
# /chat/poll: slides and slide_revisions, over real rows and the persisted spec
# ===========================================================================

POLL_SID = "page-token-poll"
OWNER = "owner@test.com"
#: Far outside REVISION_OVERLAP_S of any mark these tests take.
OLD_MODIFIED_AT = datetime(2024, 2, 1, 17, 30, 0)
#: The spec's slide count.  Mid-build only three rows exist, and the deck row's
#: slide_count is a stale value from a previous turn: three different numbers, so
#: a count read from the wrong source is visible.
SPEC_SLIDES = 5
STALE_SLIDE_COUNT = 2


def _spec_json(n: int) -> str:
    return make_spec(tuple(range(n))).to_json()


def _fake_db(factory):
    @contextlib.contextmanager
    def _cm():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _cm


class PollWorld:
    def __init__(self, client, factory, engine, request_id):
        self.client = client
        self.factory = factory
        self.engine = engine
        self.request_id = request_id

    def poll(self, slide_cursor: Optional[int] = None, mark: Optional[float] = None):
        params: Dict[str, Any] = {}
        if slide_cursor is not None:
            params["slide_cursor"] = slide_cursor
        if mark is not None:
            params["revisions_after"] = mark
        response = self.client.get(f"/api/chat/poll/{self.request_id}", params=params)
        assert response.status_code == 200, response.text
        return response

    def rows(self) -> List[str]:
        db = self.factory()
        try:
            return [r.html for r in db.query(SessionSlide).order_by(SessionSlide.position).all()]
        finally:
            db.close()


def _poll_world(monkeypatch, tmp_path, htmls: List[str], spec_json: Optional[str]):
    # File-backed: the route reads through asyncio.to_thread, and an in-memory
    # SQLite database is per-connection (test_poll_route_across_an_insert.py).
    engine = create_engine(
        f"sqlite:///{tmp_path}/poll.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    factory = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )
    fake = _fake_db(factory)
    for target in (
        "src.api.services.session_manager.get_db_session",
        "src.api.services.slide_repository.get_db_session",
        "src.api.services.deck_level_writer.get_db_session",
    ):
        monkeypatch.setattr(target, fake)
    monkeypatch.setattr(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    )
    monkeypatch.setattr("src.api.routes.chat.get_session_manager", lambda: SessionManager())
    monkeypatch.setattr("src.api.routes.chat._require_chat_request_owner", MagicMock())

    db = factory()
    try:
        release = GraphRelease(
            version_number=1,
            release_note="page-token poll fixture",
            published_by="test",
            published_at=datetime(2026, 9, 1, 9, 0, 0),
            effective_from=datetime(2026, 9, 1, 9, 0, 0),
            effective_to=None,
        )
        db.add(release)
        db.flush()
        owner = UserSession(
            session_id=POLL_SID, created_by=OWNER, graph_release_id=release.id
        )
        db.add(owner)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=owner.id,
                title="Poll deck",
                html_content="",
                scripts_content="",
                slide_count=STALE_SLIDE_COUNT,
                deck_spec_json=spec_json,
                version=3,
            )
        )
        for position, html in enumerate(htmls):
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    slide_id=f"sid-{position}-{uuid.uuid4().hex[:6]}",
                    html=html,
                    scripts="",
                    created_by=OWNER,
                    created_at=datetime(2024, 1, 1, 9, 0, 0),
                    modified_by=OWNER,
                    modified_at=OLD_MODIFIED_AT,
                )
            )
        db.commit()
    finally:
        db.close()

    from src.api.main import app

    return PollWorld(
        client=TestClient(app, raise_server_exceptions=False),
        factory=factory,
        engine=engine,
        request_id=SessionManager().create_chat_request(POLL_SID),
    )


@contextlib.contextmanager
def _recorded_sql(engine):
    statements: list = []

    def _record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


@pytest.fixture
def token_poll(monkeypatch, tmp_path):
    world = _poll_world(
        monkeypatch, tmp_path, [_slide(m) for m in MARKERS], _spec_json(SPEC_SLIDES)
    )
    yield world
    world.engine.dispose()


class TestThePollNumbersTheSlides:
    def test_poll_slides_substitute_page_tokens(self, token_poll):
        response = token_poll.poll()
        body = response.json()

        assert [s["position"] for s in body["slides"]] == [0, 1, 2], "ENTRY"
        assert _htmls(body["slides"]) == [
            _slide("MK-ALPHA", _numbered(1, SPEC_SLIDES)),
            _slide("MK-BRAVO", _numbered(2, SPEC_SLIDES)),
            _slide("MK-CHARLIE", _numbered(3, SPEC_SLIDES)),
        ]
        assert "{{slide:" not in response.text
        assert token_poll.rows() == [_slide(m) for m in MARKERS], (
            "the poll wrote rendered numbers back into the rows"
        )

    def test_poll_slide_revisions_substitute_page_tokens(self, token_poll):
        """A delivered draft rewritten by its reviewer comes back as a revision;
        it is numbered like a released slide."""
        first = token_poll.poll().json()
        assert first["slide_cursor"] == 3 and first["slide_revisions"] == [], "ENTRY"

        SlideWriter().write_slide(
            session_id=POLL_SID,
            position=1,
            html=_slide("MK-BRAVO-EDITED"),
            scripts="",
            modified_by="fix_reviewer",
        )
        response = token_poll.poll(
            slide_cursor=first["slide_cursor"], mark=first["revision_mark"]
        )
        body = response.json()

        assert [r["position"] for r in body["slide_revisions"]] == [1], "ENTRY"
        assert body["slide_revisions"][0]["html"] == _slide(
            "MK-BRAVO-EDITED", _numbered(2, SPEC_SLIDES)
        )
        assert "{{slide:" not in response.text

    def test_without_a_readable_spec_no_literal_token_ships(self, monkeypatch, tmp_path):
        """The fallback (A6): no persisted spec, so the count is the highest
        released position + 1."""
        world = _poll_world(monkeypatch, tmp_path, [_slide(m) for m in MARKERS], None)
        try:
            response = world.poll()
        finally:
            world.engine.dispose()

        assert "{{slide:" not in response.text
        assert _htmls(response.json()["slides"]) == [
            _slide("MK-ALPHA", _numbered(1, 3)),
            _slide("MK-BRAVO", _numbered(2, 3)),
            _slide("MK-CHARLIE", _numbered(3, 3)),
        ]

    def test_a_legacy_poll_is_byte_identical_and_reads_no_spec(
        self, monkeypatch, tmp_path
    ):
        """The 3-second poll stays free for legacy decks: the spec is read only
        when some released or revised HTML carries a token (A6)."""
        stored = [_legacy_slide(m) for m in MARKERS]
        world = _poll_world(monkeypatch, tmp_path, stored, _spec_json(SPEC_SLIDES))
        try:
            with _recorded_sql(world.engine) as statements:
                response = world.poll()
        finally:
            world.engine.dispose()

        assert _htmls(response.json()["slides"]) == stored
        assert statements, "ENTRY: the poll queried the database"
        assert not [s for s in statements if "deck_spec_json" in s], (
            "a poll of a deck with no token read the deck spec"
        )


# ===========================================================================
# Brand assets on the streaming boundaries (final review I1)
# ===========================================================================
#
# Addendum A puts a {{ds-asset:ID}} logo in every non-cover footer, and searched
# icons are handles too.  slide_ready and /chat/poll resolve them as the REST
# readers do (page tokens first, then the session's active design system's
# assets, a foreign handle left in place), with ONE asset read per release wake
# or poll rather than one per handle, and no read at all for a slide without a
# handle (an old deck, a deck with no design system).

LOGO_SVG = b"<svg>meridian logo</svg>"
FOREIGN_SVG = b"<svg>another brand</svg>"


def _data_uri(data: bytes) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode()


def _seed_brand(factory, session_id: str, *, scoped: bool = True) -> tuple:
    """The session's design system (via agent_config) with one logo, plus a second
    system's asset.  Returns ``(logo_handle, foreign_handle)``.  With
    ``scoped=False`` the session names no design system at all."""
    from src.database.models.design_system import DesignSystem, DesignSystemAsset

    db = factory()
    try:
        ours = DesignSystem(name=f"ours-{uuid.uuid4().hex[:8]}")
        ours.assets.append(
            DesignSystemAsset(
                kind="logo", filename="logos/logo.svg", mime="image/svg+xml",
                data=LOGO_SVG, size_bytes=len(LOGO_SVG),
            )
        )
        theirs = DesignSystem(name=f"theirs-{uuid.uuid4().hex[:8]}")
        theirs.assets.append(
            DesignSystemAsset(
                kind="logo", filename="logos/other.svg", mime="image/svg+xml",
                data=FOREIGN_SVG, size_bytes=len(FOREIGN_SVG),
            )
        )
        db.add_all([ours, theirs])
        db.flush()
        if scoped:
            session = (
                db.query(UserSession).filter(UserSession.session_id == session_id).one()
            )
            session.agent_config = {"design_system_id": ours.id}
        handles = (
            "{{ds-asset:%d}}" % ours.assets[0].id,
            "{{ds-asset:%d}}" % theirs.assets[0].id,
        )
        db.commit()
        return handles
    finally:
        db.close()


def _branded_slide(
    marker: str, logo: str, page: str = PAGE_TOKENS, foreign: Optional[str] = None
) -> str:
    """A graph slide as Addendum A builds it: a logo handle and the page tokens in
    the footer (and, optionally, a handle of another design system in the body)."""
    body = f'<img src="{foreign}" alt="foreign"/>' if foreign else ""
    return (
        '<div class="slide"><h1>' + marker + "</h1>" + body
        + '<div class="slide-footer"><span><img src="' + logo + '" alt="Logo"/>Acme</span>'
        "<span>" + page + "</span></div></div>"
    )


def _asset_reads(statements: list) -> list:
    return [s for s in statements if "FROM design_system_asset" in s]


def test_slide_ready_resolves_brand_assets_with_one_read(graph_env):
    logo, foreign = _seed_brand(graph_env.factory, graph_env.session_id)
    stored = {
        p: _branded_slide(MARKERS[p], logo, foreign=foreign if p == 1 else None)
        for p in range(3)
    }
    _commit(graph_env, stored)

    with _recorded_sql(graph_env.engine) as statements:
        events = _release(
            graph_env, _release_state(graph_env, covered=range(5), landed=range(3))
        )

    assert [e.position for e in events] == [0, 1, 2], "ENTRY: three slides released"
    assert [e.html for e in events] == [
        _branded_slide("MK-ALPHA", _data_uri(LOGO_SVG), _numbered(1, 5)),
        # A handle of another design system is left in place, never resolved.
        _branded_slide("MK-BRAVO", _data_uri(LOGO_SVG), _numbered(2, 5), foreign=foreign),
        _branded_slide("MK-CHARLIE", _data_uri(LOGO_SVG), _numbered(3, 5)),
    ]
    assert len(_asset_reads(statements)) == 1, "one asset read per wake, not one per handle"
    assert [r.html for r in graph_env.rows()] == [stored[p] for p in range(3)], (
        "the release wrote resolved assets back into the rows"
    )


def test_slide_ready_leaves_handles_when_the_session_names_no_design_system(graph_env):
    """Fail-closed, as the REST readers are: with no active design system no
    handle resolves to any system's bytes."""
    logo, _ = _seed_brand(graph_env.factory, graph_env.session_id, scoped=False)
    stored = {p: _branded_slide(MARKERS[p], logo) for p in range(2)}
    _commit(graph_env, stored)

    events = _release(graph_env, _release_state(graph_env, covered=range(2), landed=range(2)))

    assert [e.html for e in events] == [
        _branded_slide("MK-ALPHA", logo, _numbered(1, 2)),
        _branded_slide("MK-BRAVO", logo, _numbered(2, 2)),
    ]


def _forbid_design_system_lookup(monkeypatch) -> None:
    def _lookup(session_id):
        raise AssertionError("a slide with no handle looked up the session's design system")

    monkeypatch.setattr(
        "src.api.services.chat_service.resolve_active_design_system_id", _lookup
    )


def test_slide_ready_without_a_handle_is_byte_identical_and_reads_nothing(
    graph_env, monkeypatch
):
    stored = {p: _legacy_slide(MARKERS[p]) for p in range(3)}
    _commit(graph_env, stored)
    _forbid_design_system_lookup(monkeypatch)

    with _recorded_sql(graph_env.engine) as statements:
        events = _release(
            graph_env, _release_state(graph_env, covered=range(3), landed=range(3))
        )

    assert [e.html for e in events] == [stored[p] for p in range(3)]
    assert _asset_reads(statements) == []


def _rewrite_rows(world: "PollWorld", htmls: List[str]) -> None:
    db = world.factory()
    try:
        for row in db.query(SessionSlide).order_by(SessionSlide.position).all():
            row.html = htmls[row.position]
        db.commit()
    finally:
        db.close()


def test_poll_resolves_brand_assets_in_slides_and_revisions(monkeypatch, tmp_path):
    world = _poll_world(
        monkeypatch, tmp_path, [_slide(m) for m in MARKERS], _spec_json(SPEC_SLIDES)
    )
    try:
        logo, foreign = _seed_brand(world.factory, POLL_SID)
        stored = [
            _branded_slide(m, logo, foreign=foreign if i == 2 else None)
            for i, m in enumerate(MARKERS)
        ]
        _rewrite_rows(world, stored)

        with _recorded_sql(world.engine) as statements:
            first = world.poll()
        body = first.json()

        assert [s["position"] for s in body["slides"]] == [0, 1, 2], "ENTRY"
        assert _htmls(body["slides"]) == [
            _branded_slide("MK-ALPHA", _data_uri(LOGO_SVG), _numbered(1, SPEC_SLIDES)),
            _branded_slide("MK-BRAVO", _data_uri(LOGO_SVG), _numbered(2, SPEC_SLIDES)),
            _branded_slide(
                "MK-CHARLIE", _data_uri(LOGO_SVG), _numbered(3, SPEC_SLIDES), foreign=foreign
            ),
        ]
        assert len(_asset_reads(statements)) == 1, "one asset read per poll"
        assert world.rows() == stored, "the poll wrote resolved assets back into the rows"

        # A delivered draft rewritten by its reviewer comes back as a revision.
        SlideWriter().write_slide(
            session_id=POLL_SID,
            position=1,
            html=_branded_slide("MK-BRAVO-EDITED", logo),
            scripts="",
            modified_by="fix_reviewer",
        )
        second = world.poll(
            slide_cursor=body["slide_cursor"], mark=body["revision_mark"]
        ).json()

        assert second["slides"] == [], "ENTRY: nothing new released"
        assert [r["position"] for r in second["slide_revisions"]] == [1], "ENTRY"
        assert second["slide_revisions"][0]["html"] == _branded_slide(
            "MK-BRAVO-EDITED", _data_uri(LOGO_SVG), _numbered(2, SPEC_SLIDES)
        )
    finally:
        world.engine.dispose()


def test_a_poll_without_a_handle_is_byte_identical_and_reads_nothing(
    monkeypatch, tmp_path
):
    stored = [_legacy_slide(m) for m in MARKERS]
    world = _poll_world(monkeypatch, tmp_path, stored, _spec_json(SPEC_SLIDES))
    _forbid_design_system_lookup(monkeypatch)
    try:
        with _recorded_sql(world.engine) as statements:
            response = world.poll()
    finally:
        world.engine.dispose()

    assert response.status_code == 200, response.text
    assert _htmls(response.json()["slides"]) == stored
    assert _asset_reads(statements) == []


# ===========================================================================
# The restore response renders like the version preview (final review I2)
# ===========================================================================
#
# The client renders the restore response directly (AppLayout.tsx), with no
# refetch, so it must resolve images and brand assets as the preview of the same
# save point does, on an outgoing copy only.

PNG_BYTES = b"\x89PNG user image"


def _seed_library_image(factory) -> str:
    """A library (open-read) user image; returns its ``{{image:TOKEN}}`` handle."""
    from src.database.models.image import ImageAsset

    db = factory()
    try:
        image = ImageAsset(
            token=f"tok{uuid.uuid4().hex[:16]}",
            filename="u.png",
            original_filename="u.png",
            mime_type="image/png",
            size_bytes=len(PNG_BYTES),
            image_data=PNG_BYTES,
            category="branding",
        )
        db.add(image)
        db.commit()
        return "{{image:%s}}" % image.token
    finally:
        db.close()


def _with_image(html: str, src: str) -> str:
    return html.replace("</h1>", f'</h1><img src="{src}" alt="user image"/>', 1)


def test_the_restore_response_resolves_images_and_brand_assets_like_the_preview(
    api, test_db_factory, mock_user
):
    session_id = _create_session(api)
    logo, foreign = _seed_brand(test_db_factory, session_id)
    image = _seed_library_image(test_db_factory)
    stored = [
        _with_image(_branded_slide("MK-ALPHA", logo), image),
        _branded_slide("MK-BRAVO", logo, foreign=foreign),
    ]
    _seed(session_id, stored)
    version = _create_savepoint(api, session_id)

    preview = api.get(f"/api/slides/versions/{version}", params={"session_id": session_id})
    assert preview.status_code == 200, preview.text
    restored = api.post(
        f"/api/slides/versions/{version}/restore", json={"session_id": session_id}
    )
    assert restored.status_code == 200, restored.text

    png_uri = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()
    expected = [
        _with_image(_branded_slide("MK-ALPHA", _data_uri(LOGO_SVG), _numbered(1, 2)), png_uri),
        # A handle of another design system stays in place, as on every reader.
        _branded_slide("MK-BRAVO", _data_uri(LOGO_SVG), _numbered(2, 2), foreign=foreign),
    ]
    assert _htmls(preview.json()["deck"]["slides"]) == expected, "ENTRY: the preview resolves"
    assert _htmls(restored.json()["deck"]["slides"]) == expected
    # Outgoing copy only: the rows and every save point keep handles and tokens.
    assert _row_htmls(test_db_factory, session_id) == stored
    for snapshot in _version_snapshots(test_db_factory, session_id):
        assert "data:image/" not in snapshot and MARKER_ATTR not in snapshot
