"""The polling route across an agent-path insert (#314, Task 7; plan D5).

An "add a slide" turn shifts the deck's rows at architect commit
(``SlideWriter.insert_pending_slides``): C and D move down one position and a
pending placeholder opens at the insert point.  A polling client learns of rows
through two queries only, and neither knows about shifts:

* ``slides_since_cursor`` releases positions at or above the client's cursor;
* ``slide_revisions_since`` re-sends positions BELOW the cursor whose
  ``modified_at`` is newer than the client's mark.

A shift deliberately keeps every moved row's ``modified_at`` (it is attribution,
not a write by this turn).  So when a client's first poll lands before the shift,
the next poll sends D again at the new last position and the pending row as the
only revision, and C (now one place down) is never re-sent.  The client shows
``[A, B, P, D, D]`` until ``complete``, whose refetched ``result.slides`` is the
shifted deck.  That is D5's known mid-turn limit.  This suite pins it at the
route, over real persistence, so that:

* a change that starts re-sending moved rows (e.g. stamping a fresh
  ``modified_at`` on them, which would also falsify their attribution) is seen;
* the end-of-turn correction the client relies on is the shifted deck.

Every slide is identified by the marker in its own HTML, never by position alone.
"""
from __future__ import annotations

import src.core.database  # noqa: F401 — imported FIRST (circular import via src.core)

import contextlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — registers every ORM model on Base
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import PENDING_SLIDE_TEXT, SlideWriter
from src.core.database import Base, _run_migrations
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.domain.deck_spec import DeckSpec
from src.services.shared_deck_attribution import DeckMutationContext, MutationActor
from src.utils.slide_hash import compute_slide_hash

SESSION_ID = "poll-across-insert"
OWNER = "owner@test.com"

OLD = ("MK-ALPHA", "MK-BRAVO", "MK-CHARLIE", "MK-DELTA")
NEW = "MK-NEW"
#: The insert point: the new slide goes after B, so C and D move down one.
INSERT_AT = 2
SHIFTED = ["MK-ALPHA", "MK-BRAVO", NEW, "MK-CHARLIE", "MK-DELTA"]
PENDING = "PENDING"

_MARKER_RE = re.compile(r"MK-[A-Z]+")


def _html(marker: str) -> str:
    return f'<div class="slide"><h1>{marker}</h1><p>its own body text</p></div>'


def _marker(html: str) -> str:
    """The slide a payload carries: its marker, or PENDING for the placeholder."""
    found = _MARKER_RE.findall(html or "")
    assert len(found) <= 1, f"one payload carries several slides: {found}"
    if found:
        return found[0]
    assert PENDING_SLIDE_TEXT in (html or ""), f"an unidentifiable slide: {html!r}"
    return PENDING


def _delivered(entries: List[Dict[str, Any]]) -> List[tuple]:
    """``[(position, marker)]`` of a poll's ``slides`` or ``slide_revisions``."""
    return [(entry["position"], _marker(entry["html"])) for entry in entries]


def _spec_json(markers: List[str]) -> str:
    """A valid DeckSpec whose slide ``purpose`` names the slide it specifies."""
    return DeckSpec(
        title="Poll deck",
        audience="aud",
        purpose="pur",
        argument="arg",
        call_to_action="cta",
        narrative_arc=["open", "close"],
        design_contract={},
        resolved_data={"synthesis": "syn", "figures": [], "gaps": []},
        slides=[
            {
                "position": position,
                "purpose": f"purpose-{marker}",
                "content_brief": f"brief-{marker}",
                "assumes": "",
                "hands_off": "",
                "data_references": [],
            }
            for position, marker in enumerate(markers)
        ],
    ).to_json()


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


@dataclass
class World:
    client: TestClient
    factory: Any
    request_id: str
    slide_ids: Dict[str, str]
    release_id: Optional[int]
    new_slide_id: Optional[str] = None
    #: What a replace-by-position client holds, position -> marker.
    view: Dict[int, str] = field(default_factory=dict)

    # -- the route ---------------------------------------------------------

    def poll(self, slide_cursor: Optional[int] = None, mark: Optional[float] = None):
        params: Dict[str, Any] = {}
        if slide_cursor is not None:
            params["slide_cursor"] = slide_cursor
        if mark is not None:
            params["revisions_after"] = mark
        response = self.client.get(f"/api/chat/poll/{self.request_id}", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        # The client's model: released slides land at their position, revisions
        # replace by position (frontend api.ts / ws4e).
        for entry in body["slides"] + body["slide_revisions"]:
            self.view[entry["position"]] = _marker(entry["html"])
        return body

    def client_view(self) -> List[str]:
        assert sorted(self.view) == list(range(len(self.view))), self.view
        return [self.view[p] for p in range(len(self.view))]

    # -- the turn ----------------------------------------------------------

    def shift(self) -> None:
        """The architect-commit shift, against the rows the client was sent."""
        expected_rows = [
            (self.slide_ids[marker], compute_slide_hash(_html(marker))) for marker in OLD
        ]
        (self.new_slide_id,) = SlideWriter().insert_pending_slides(
            SESSION_ID,
            [INSERT_AT],
            deck_spec=_spec_json(SHIFTED),
            expected_rows=expected_rows,
            created_by=OWNER,
            mutation=DeckMutationContext(
                actor=MutationActor(SESSION_ID, self.release_id),
                operation="insert_slide",
                object_type="deck",
            ),
        )

    def land_new_slide(self) -> None:
        SlideWriter().write_slide(
            SESSION_ID, INSERT_AT, html=_html(NEW), modified_by="build_reviewer"
        )

    def complete(self) -> None:
        """Exactly what job_queue stores from the graph's COMPLETE event."""
        manager = SessionManager()
        manager.update_chat_request_status(self.request_id, "completed")
        manager.set_chat_request_result(
            self.request_id, {"slides": ChatService().get_slides(SESSION_ID)}
        )

    def rows_by_marker(self) -> Dict[str, Dict[str, Any]]:
        db = self.factory()
        try:
            return {
                _marker(row.html): {"position": row.position, "modified_at": row.modified_at}
                for row in db.query(SessionSlide).order_by(SessionSlide.position).all()
            }
        finally:
            db.close()


#: Far outside ``SessionManager.REVISION_OVERLAP_S`` of any mark this test takes.
OLD_MODIFIED_AT = datetime(2024, 2, 1, 17, 30, 0)


@pytest.fixture
def world(monkeypatch, tmp_path) -> World:
    # File-backed: the route reads through asyncio.to_thread, and an in-memory
    # SQLite database is per-connection, so a worker thread would see no tables.
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
    # get_slide_deck resolves display names on every row read; the real SCIM
    # client retries and hangs (conftest_graph.py).
    monkeypatch.setattr(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    )
    monkeypatch.setattr(
        "src.api.routes.chat.get_session_manager", lambda: SessionManager()
    )
    monkeypatch.setattr("src.api.routes.chat._require_chat_request_owner", MagicMock())

    slide_ids = {marker: f"sid-{marker}-{uuid.uuid4().hex[:8]}" for marker in OLD}
    db = factory()
    try:
        release = GraphRelease(
            version_number=1,
            release_note="poll-across-insert fixture",
            published_by="test",
            published_at=datetime(2026, 9, 1, 9, 0, 0),
            effective_from=datetime(2026, 9, 1, 9, 0, 0),
            effective_to=None,
        )
        db.add(release)
        db.flush()
        owner = UserSession(
            session_id=SESSION_ID, created_by=OWNER, graph_release_id=release.id
        )
        db.add(owner)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=owner.id,
                title="Poll deck",
                html_content="",
                scripts_content="",
                slide_count=len(OLD),
                deck_spec_json=_spec_json(list(OLD)),
                version=3,
            )
        )
        for position, marker in enumerate(OLD):
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    slide_id=slide_ids[marker],
                    html=_html(marker),
                    scripts="",
                    created_by=OWNER,
                    created_at=datetime(2024, 1, 1, 9, 0, 0),
                    modified_by=OWNER,
                    modified_at=OLD_MODIFIED_AT,
                )
            )
        db.commit()
        # The mutation actor must carry the session's own persisted pin.
        release_id = owner.graph_release_id
    finally:
        db.close()

    from src.api.main import app

    w = World(
        client=TestClient(app, raise_server_exceptions=False),
        factory=factory,
        request_id=SessionManager().create_chat_request(SESSION_ID),
        slide_ids=slide_ids,
        release_id=release_id,
    )
    yield w
    engine.dispose()


def _first_poll_then_shift(world: World) -> Dict[str, Any]:
    """Poll 1 lands before the shift (the timing D5 is about); returns its body."""
    first = world.poll()
    assert _delivered(first["slides"]) == list(enumerate(OLD)), (
        f"entry: the first poll must release A–D at 0–3: {_delivered(first['slides'])}"
    )
    assert first["slide_cursor"] == len(OLD)
    assert first["slide_revisions"] == []
    assert first["status"] == "pending" and first["result"] is None
    world.shift()
    return first


def test_the_poll_after_the_shift_sends_D_again_and_only_the_pending_row(world):
    """The pinned mid-turn limit (D5): moved rows keep ``modified_at``, so C is
    never re-sent and the client shows [A, B, P, D, D] until ``complete``."""
    first = _first_poll_then_shift(world)
    # ENTRY: the shift really happened, and C and D really moved.
    rows = world.rows_by_marker()
    assert {m: r["position"] for m, r in rows.items()} == {
        "MK-ALPHA": 0, "MK-BRAVO": 1, PENDING: 2, "MK-CHARLIE": 3, "MK-DELTA": 4,
    }

    second = world.poll(slide_cursor=first["slide_cursor"], mark=first["revision_mark"])

    assert _delivered(second["slides"]) == [(4, "MK-DELTA")], (
        "slides_since_cursor(4) after the shift must release exactly the old last "
        f"slide again at its new position 4: {_delivered(second['slides'])}"
    )
    assert second["slides"][0]["html"] == _html("MK-DELTA")
    assert second["slide_cursor"] == 5
    assert _delivered(second["slide_revisions"]) == [(INSERT_AT, PENDING)], (
        "the only revision after the shift must be the pending row at the insert "
        "point; a moved row re-sent here means the shift stamped a fresh "
        f"modified_at on it: {_delivered(second['slide_revisions'])}"
    )
    assert PENDING_SLIDE_TEXT in second["slide_revisions"][0]["html"]
    assert "MK-CHARLIE" not in [m for _, m in _delivered(second["slide_revisions"])], (
        "C (now at 3) must NOT be re-sent mid-turn (D5)"
    )
    # Why: the moved rows' attribution, including modified_at, is untouched.
    assert rows["MK-CHARLIE"]["modified_at"] == OLD_MODIFIED_AT
    assert rows["MK-DELTA"]["modified_at"] == OLD_MODIFIED_AT

    assert world.client_view() == ["MK-ALPHA", "MK-BRAVO", PENDING, "MK-DELTA", "MK-DELTA"], (
        "D5's documented mid-turn polling view"
    )


def test_the_landed_slide_reaches_the_client_as_a_revision_at_the_insert_point(world):
    first = _first_poll_then_shift(world)
    second = world.poll(slide_cursor=first["slide_cursor"], mark=first["revision_mark"])
    world.land_new_slide()

    third = world.poll(slide_cursor=second["slide_cursor"], mark=second["revision_mark"])

    assert third["slides"] == [] and third["slide_cursor"] == 5, (
        "nothing is left above the cursor, and the cursor must not move"
    )
    assert _delivered(third["slide_revisions"]) == [(INSERT_AT, NEW)], (
        f"the built slide must replace the pending row: {_delivered(third['slide_revisions'])}"
    )
    assert third["slide_revisions"][0]["html"] == _html(NEW)
    # Still the mid-turn view: C is missing and D is shown twice until complete.
    assert world.client_view() == ["MK-ALPHA", "MK-BRAVO", NEW, "MK-DELTA", "MK-DELTA"]


def test_a_client_that_starts_polling_after_the_shift_gets_the_shifted_deck(world):
    _first_poll_then_shift(world)
    world.land_new_slide()
    world.view.clear()  # a fresh client: no cursor, no mark, nothing held

    fresh = world.poll()

    assert _delivered(fresh["slides"]) == list(enumerate(SHIFTED)), (
        f"a fresh client must receive all five in shifted order: {_delivered(fresh['slides'])}"
    )
    assert fresh["slide_cursor"] == 5
    assert fresh["slide_revisions"] == []
    assert world.client_view() == SHIFTED


def test_the_completed_result_is_the_shifted_deck_in_marker_order(world):
    """The end-of-turn refetch is the correction D5 relies on."""
    first = _first_poll_then_shift(world)
    second = world.poll(slide_cursor=first["slide_cursor"], mark=first["revision_mark"])
    world.land_new_slide()
    third = world.poll(slide_cursor=second["slide_cursor"], mark=second["revision_mark"])
    # ENTRY: before complete the route carries no result.
    assert third["status"] == "pending" and third["result"] is None

    world.complete()
    done = world.poll(slide_cursor=third["slide_cursor"], mark=third["revision_mark"])

    assert done["status"] == "completed"
    deck = done["result"]["slides"]
    slides = deck["slides"]
    assert [_marker(s["html"]) for s in slides] == SHIFTED, (
        f"result.slides must be the shifted deck: {[_marker(s['html']) for s in slides]}"
    )
    assert [s["index"] for s in slides] == [0, 1, 2, 3, 4]
    # Identity follows the slide, and the new slide is the one the shift opened.
    by_marker = {_marker(s["html"]): s for s in slides}
    for marker in OLD:
        assert by_marker[marker]["slide_id"] == world.slide_ids[marker], marker
    assert by_marker[NEW]["slide_id"] == world.new_slide_id
    spec_slides = deck["deck_spec"]["slides"]
    assert [s["position"] for s in spec_slides] == [0, 1, 2, 3, 4]
    assert [s["purpose"] for s in spec_slides] == [f"purpose-{m}" for m in SHIFTED]

    # The client replaces its whole view with the refetched deck on complete.
    world.view = {s["index"]: _marker(s["html"]) for s in slides}
    assert world.client_view() == SHIFTED
