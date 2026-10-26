"""``POST /api/slides`` for the manual insert (#314 follow-up, Task 3): the route half.

The route pattern of ``tests/unit/test_delete_message.py``: the permission gate,
the editing lock, the session lock and ``mark_dirty`` are stubs that append to ONE
ordered ``events`` list, the service is a stub that records its arguments, and the
caller comes from the request (``DEV_USER_ID`` through the real middleware).

What is pinned (plan Task 3, D6, D7; PLAN-REVIEW m6, m8, m9):

* the editor reaches the service as ``inserted_by`` (the usage event's user);
* the response is the service's dict as is, ``inserted_slide_id`` and
  ``inserted_position`` included: the viewer selects the slide it inserted from
  them (``frontend/src/services/api.ts`` ``insertSlide``);
* a blank insert (no ``html``) schedules no arc review; an HTML insert still marks
  the spec dirty, once (m9).  Every absence of ``mark_dirty`` is paired with a
  presence in the same test, so a stub off the executed path cannot pass it;
* every busy answer is ``CONVERSATION_BUSY_DETAIL`` (m8 for the held lock; the arc
  review and another session's turn for the service's refusals); a deck whose rows
  moved is its own 409 sentence; the lock is released whenever this request took
  it, and never when it did not;
* ``ValueError`` -> 400, ``VersionConflictError`` -> 409, anything else a fixed 500.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import src.api.services.session_manager as session_manager
from src.api.services.chat_service import ArcReviewInFlightError
from src.api.services.session_manager import VersionConflictError
from src.database.models.profile_contributor import PermissionLevel

EDITOR = "editor@example.com"
SID = "s-insert"

#: Written out: the plan's DECK_CHANGED_DETAIL (D7 (4)).
DECK_CHANGED = "The deck changed while the slide was being added. Refresh and try again."

#: What the stub service answers: the real service's shape, fixed, so a route that
#: rebuilt or trimmed the result shows up.
_STUB_RESULT = {
    "title": "Stub deck",
    "slide_count": 4,
    "css": "",
    "external_scripts": [],
    "scripts": "",
    "head_meta": {},
    "slides": [
        {"index": i, "slide_id": sid, "html": html, "scripts": ""}
        for i, (sid, html) in enumerate(
            [
                ("sid-a", '<div class="slide"><h1>A</h1></div>'),
                ("sid-b", '<div class="slide"><h1>B</h1></div>'),
                ("sid-new", '<div class="slide"></div>'),
                ("sid-c", '<div class="slide"><h1>C</h1></div>'),
            ]
        )
    ],
    "inserted_slide_id": "sid-new",
    "inserted_position": 2,
}

_HTML = '<div class="slide"><h2>MK-HUMAN</h2></div>'


def _busy_detail() -> str:
    from src.api.routes.sessions import CONVERSATION_BUSY_DETAIL

    return CONVERSATION_BUSY_DETAIL


def _whole_insert(*, marked: bool) -> list:
    """The order of an insert that gets as far as the service."""
    steps = [
        ("gate", SID),
        ("editing_lock", SID),
        ("acquire", SID),
        ("service", SID),
    ]
    if marked:
        steps.append(("mark_dirty", SID))
    steps.append(("release", SID))
    return steps


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def events():
    """The one ordered log every stub below appends ``(step, session_id)`` to."""
    return []


@pytest.fixture
def slide_gate(monkeypatch, events):
    """The slides router's permission gate, passing; records the level it demanded."""
    calls = []

    def gate(session_id, db, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        events.append(("gate", session_id))
        return min_permission

    monkeypatch.setattr("src.api.routes.slides._require_slide_permission", gate)
    return calls


@pytest.fixture
def locks(monkeypatch, events):
    """The editing lock and the session lock, on the manager the route looks up.

    ``grant`` is what ``acquire_session_lock`` answers (False: a turn holds it);
    ``editing_refusal`` makes ``require_editing_lock`` raise PermissionError.
    """
    state = SimpleNamespace(
        grant=True, editing_refusal=None, editing=[], acquired=[], released=[]
    )

    class _Manager:
        def require_editing_lock(self, session_id):
            state.editing.append(session_id)
            events.append(("editing_lock", session_id))
            if state.editing_refusal is not None:
                raise PermissionError(state.editing_refusal)

        def acquire_session_lock(self, session_id, timeout_seconds=300):
            state.acquired.append(session_id)
            events.append(("acquire", session_id))
            return state.grant

        def release_session_lock(self, session_id):
            state.released.append(session_id)
            events.append(("release", session_id))

    manager = _Manager()
    monkeypatch.setattr("src.api.routes.slides.get_session_manager", lambda: manager)
    return state


@pytest.fixture
def stub_service(monkeypatch, events):
    """Replaces ChatService for the route; records every call's arguments.

    Set ``.raises`` to make ``insert_slide`` raise it (after recording the call).
    ``inserted_by`` defaults to None, so a route that does not pass it is a
    recorded None, not a TypeError.
    """
    stub = SimpleNamespace(calls=[], raises=None)

    class _Stub:
        def insert_slide(
            self, session_id, position, *, html=None, expected_version=None, inserted_by=None
        ):
            stub.calls.append(
                {
                    "session_id": session_id,
                    "position": position,
                    "html": html,
                    "expected_version": expected_version,
                    "inserted_by": inserted_by,
                }
            )
            events.append(("service", session_id))
            if stub.raises is not None:
                raise stub.raises
            return copy.deepcopy(_STUB_RESULT)

    monkeypatch.setattr("src.api.routes.slides.get_chat_service", lambda: _Stub())
    return stub


@pytest.fixture
def marks(monkeypatch, events):
    """``spec_sync.mark_dirty`` as the route module binds it: records (session_id, author)."""
    calls = []

    def fake_mark_dirty(session_id, author):
        calls.append((session_id, author))
        events.append(("mark_dirty", session_id))
        return True

    monkeypatch.setattr("src.api.routes.slides.mark_dirty", fake_mark_dirty)
    return calls


@pytest.fixture
def as_editor(monkeypatch):
    """Authenticate as ``EDITOR``: the real middleware reads ``DEV_USER_ID``."""
    monkeypatch.setenv("DEV_USER_ID", EDITOR)


@pytest.fixture
def route(client, slide_gate, locks, stub_service, marks, as_editor, events):
    return SimpleNamespace(
        client=client,
        gate=slide_gate,
        locks=locks,
        service=stub_service,
        marks=marks,
        events=events,
    )


def _post(route, **body):
    payload = {"session_id": SID, "position": 2}
    payload.update(body)
    return route.client.post("/api/slides", json=payload)


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


def test_a_blank_insert_passes_the_editor_and_schedules_no_arc_review(route):
    """m9: no ``html`` -> the spliced blank entry is already the exact description,
    so no review is scheduled.  Paired: an HTML insert on the same route marks."""
    resp = _post(route)

    assert resp.status_code == 200, resp.text
    assert resp.json() == _STUB_RESULT
    assert route.gate == [(SID, PermissionLevel.CAN_EDIT)]
    assert route.service.calls == [
        {
            "session_id": SID,
            "position": 2,
            "html": None,
            "expected_version": None,
            "inserted_by": EDITOR,
        }
    ]
    assert route.marks == [], "a blank insert scheduled an arc review"
    assert route.events == _whole_insert(marked=False)
    assert route.locks.released == [SID]

    resp = _post(route, html=_HTML)
    assert resp.status_code == 200, resp.text
    assert route.marks == [(SID, EDITOR)], "the mark_dirty stub is not on the executed path"


def test_an_html_insert_still_marks_the_spec_dirty_once(route):
    """D6: an insert that carries HTML still schedules the arc review, after the
    service and before the lock is given back."""
    resp = _post(route, html=_HTML, expected_version=7, position=0)

    assert resp.status_code == 200, resp.text
    assert resp.json() == _STUB_RESULT
    assert route.service.calls == [
        {
            "session_id": SID,
            "position": 0,
            "html": _HTML,
            "expected_version": 7,
            "inserted_by": EDITOR,
        }
    ]
    assert route.marks == [(SID, EDITOR)]
    assert route.events == _whole_insert(marked=True)


def test_the_response_carries_the_inserted_slide_and_its_position(route):
    """m6: the viewer reads exactly these two keys to select the new slide."""
    resp = _post(route)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["inserted_slide_id"] == "sid-new"
    assert body["inserted_position"] == 2


@pytest.mark.parametrize("caller", ["editor@example.com", "contributor@example.com"])
def test_the_route_passes_the_request_user_as_inserted_by(
    route, monkeypatch, caller
):
    """The identity comes from the request (the real middleware), read in the
    handler and passed explicitly into the worker thread."""
    monkeypatch.setenv("DEV_USER_ID", caller)

    resp = _post(route)

    assert resp.status_code == 200, resp.text
    assert [c["inserted_by"] for c in route.service.calls] == [caller]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make_error",
    [
        pytest.param(lambda: ArcReviewInFlightError(SID), id="arc_review"),
        pytest.param(
            lambda: session_manager.DeckBusyError(
                "session other-sess of this deck is running a turn"
            ),
            id="deck_busy",
        ),
    ],
)
def test_a_busy_deck_is_a_409_with_the_busy_sentence_and_the_lock_is_released(
    route, make_error
):
    """D7 (2), (3): the service's busy refusals answer the same sentence as a held
    lock (never a 500, never the exception's text).  This request took the lock,
    so it gives it back; nothing was inserted, so nothing is marked.  The request
    carries HTML, so a mark on this path would show."""
    route.service.raises = make_error()

    resp = _post(route, html=_HTML)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == _busy_detail()
    assert route.locks.released == [SID]
    assert route.marks == []
    assert route.events == _whole_insert(marked=False)


def test_rows_that_moved_under_the_insert_are_a_409_saying_so(route):
    """D7 (4): the deck changed while the slide was being added; the UI shows this
    sentence and refetches.  Lock released, nothing marked."""
    route.service.raises = session_manager.SlideRowsChangedError(
        "the committed rows of session s-insert are not the rows the insert planned against"
    )

    resp = _post(route, html=_HTML)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == DECK_CHANGED
    assert route.locks.released == [SID]
    assert route.marks == []
    assert route.events == _whole_insert(marked=False)

    from src.api.routes import slides as slides_route

    assert getattr(slides_route, "DECK_CHANGED_DETAIL", None) == DECK_CHANGED


def test_a_held_session_lock_is_a_409_with_the_busy_sentence_and_is_not_released(route):
    """m8: the lock-held 409 says the same thing as every other busy answer
    (it used to say "Session is currently processing another request").  The lock
    belongs to the request holding it: a 409 never releases it."""
    route.locks.grant = False

    resp = _post(route, html=_HTML)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == _busy_detail()
    assert route.service.calls == [], "a busy session must not be inserted into"
    assert route.locks.acquired == [SID]
    assert route.locks.released == [], "a 409 must not release a lock it did not take"
    assert route.marks == []
    assert route.events == [("gate", SID), ("editing_lock", SID), ("acquire", SID)]


def test_a_validation_error_is_a_400_and_the_lock_is_released(route):
    route.service.raises = ValueError("Invalid slide position: -1")

    resp = _post(route, position=-1, html=_HTML)

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "Invalid slide position: -1"
    assert route.locks.released == [SID]
    assert route.marks == []
    assert route.events == _whole_insert(marked=False)


def test_a_stale_expected_version_is_a_409_and_the_lock_is_released(route):
    error = VersionConflictError(current_version=9, expected_version=7)
    route.service.raises = error

    resp = _post(route, expected_version=7, html=_HTML)

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == str(error)
    assert route.locks.released == [SID]
    assert route.marks == []


def test_an_unexpected_failure_is_a_fixed_500_and_the_lock_is_released(route):
    route.service.raises = RuntimeError("internal: dsn=secret")

    resp = _post(route, html=_HTML)

    assert resp.status_code == 500, resp.text
    assert "secret" not in resp.text
    assert route.locks.released == [SID]
    assert route.marks == []


def test_another_editor_holding_the_editing_lock_is_a_423_before_the_session_lock(route):
    route.locks.editing_refusal = "Slide editing is locked by someone@example.com"

    resp = _post(route)

    assert resp.status_code == 423, resp.text
    assert route.service.calls == []
    assert route.locks.acquired == []
    assert route.locks.released == []
    assert route.events == [("gate", SID), ("editing_lock", SID)]
