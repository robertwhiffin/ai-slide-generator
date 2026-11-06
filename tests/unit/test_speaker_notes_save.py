"""The notes-only save (speaker notes plan, Task 7A, D8 and D10).

``ChatService.update_slide_notes(session_id, index, speaker_notes, *, slide_id=None,
expected_version=None)`` and its route ``PATCH /api/slides/{index}/notes``.

What is pinned:

* a notes save changes ONLY the notes (and their source): the HTML, the slide's
  identity and authorship, its verification record and its spec fragment stay
  byte-identical on every row, so the content hash and the hash-keyed verdict
  stay too (Review focus 6);
* no save point is taken, the deck version bumps once and is returned;
* whitespace-only notes clear, a wrong ``slide_id`` or a bad index refuses, and a
  stale ``expected_version`` refuses AND leaves the worker's cached deck holding
  the old notes (the cache-restore requirement: an un-restored cache would serve,
  and a later write would persist, the rejected notes);
* the saved notes are user notes (D10): source ``"user"``, ``None`` after an empty
  save, and neither a later HTML save without an aside nor a later model write
  replaces them;
* the route makes the HTML save's checks (CAN_EDIT, the editing lock, the session
  lock), never marks the spec dirty, caps the notes at 20,000 characters and maps
  the service's errors the way ``PATCH /{index}`` does.

Service tests run against the real SQLite fixture (``deck_with_verdicts``, plus a
spec fragment written onto every row so "unchanged" compares non-empty values).
Route tests follow the stub pattern of ``tests/unit/test_manual_insert_route.py``.
"""
from __future__ import annotations

import contextlib
import copy
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager, VersionConflictError
from src.api.services.slide_repository import SlideWriter
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import SessionSlide, UserSession
from tests.unit.conftest import _make_fake_db

EDITOR = "notes-editor@example.com"

#: An HTML save of slide 1 with no aside: Task 4 keeps the slide's notes.
_PLAIN_HTML = "<div class='slide'><h1>Slide Two, edited</h1><p>Content B2</p></div>"


# ---------------------------------------------------------------------------
# Service harness
# ---------------------------------------------------------------------------


def _worker() -> ChatService:
    """A ChatService with its own deck cache, built as ``make_worker()`` does
    (``tests/unit/test_multiworker_cache_coherence.py``)."""
    worker = ChatService.__new__(ChatService)
    worker.agent = MagicMock()
    worker._deck_cache = {}
    worker._cache_lock = threading.Lock()
    return worker


def _write_spec_fragments(fixture) -> None:
    """Give every row a non-empty ``deck_spec_slide`` (the verdicts fixture has none)."""
    db = fixture._factory()
    try:
        owner_id = (
            db.query(UserSession)
            .filter(UserSession.session_id == fixture.session_id)
            .one()
            .id
        )
        for row in db.query(SessionSlide).filter(SessionSlide.session_id == owner_id):
            row.deck_spec_slide = json.dumps(
                {"title": f"Fragment {row.position}", "key_message": f"K{row.position}"}
            )
        db.commit()
    finally:
        db.close()


@pytest.fixture
def env(deck_with_verdicts):
    """The verdicts deck, a spec fragment on every row, one worker, real persistence.

    ``get_current_username`` answers ``EDITOR`` (not the rows' author), so a save
    that stamped ``modified_by`` would show in the row snapshot.
    """
    fixture = deck_with_verdicts
    _write_spec_fragments(fixture)
    sm = SessionManager()
    with contextlib.ExitStack() as stack:
        stack.enter_context(fixture._patched())
        stack.enter_context(
            patch("src.api.services.chat_service.get_session_manager", return_value=sm)
        )
        stack.enter_context(
            patch("src.api.services.chat_service.get_current_username", return_value=EDITOR)
        )
        stack.enter_context(
            patch(
                "src.api.services.slide_repository.get_db_session",
                # SlideWriter imports get_db_session by name, so it needs its own patch.
                _make_fake_db(fixture._factory),
            )
        )
        yield SimpleNamespace(
            fixture=fixture, sid=fixture.session_id, service=_worker(), sm=sm
        )


def _row(env, pos: int) -> dict:
    return env.fixture.row_snapshot()[pos]


def _without_notes(row: dict) -> dict:
    out = dict(row)
    out.pop("speaker_notes")
    out.pop("speaker_notes_source")
    return out


# ---------------------------------------------------------------------------
# Service: only the notes change
# ---------------------------------------------------------------------------


def test_a_notes_save_changes_only_the_notes(env):
    # Sabotage: stamp_modified on the slide, or rebuild its HTML through retokenise_slide_numbers / a new Slide(...).
    before = env.fixture.row_snapshot()
    assert before[1]["verification_record"] and before[1]["deck_spec_slide"], (
        "the harness must compare non-empty verdicts and fragments"
    )

    env.service.update_slide_notes(env.sid, 1, "Pause here.")

    after = env.fixture.row_snapshot()
    assert len(after) == len(before) == 3
    for pos in (0, 2):
        assert after[pos] == before[pos], f"row {pos} changed on a notes save of slide 1"
    assert _without_notes(after[1]) == _without_notes(before[1])
    assert after[1]["speaker_notes"] == "Pause here."
    assert after[1]["speaker_notes_source"] == "user"


def test_a_notes_save_keeps_the_content_hash_and_verification(env):
    # Sabotage: change the slide's HTML (e.g. retokenise or re-knit it), so the hash-keyed verdict no longer resolves.
    before = env.fixture.get_slide_deck()["slides"]
    assert all(s["verification"] for s in before), "every slide should carry a verdict"

    env.service.update_slide_notes(env.sid, 1, "Pause here.")

    after = env.fixture.get_slide_deck()["slides"]
    assert [s["content_hash"] for s in after] == [s["content_hash"] for s in before]
    assert [s["verification"] for s in after] == [s["verification"] for s in before]
    assert [s["html"] for s in after] == [s["html"] for s in before]
    assert after[1]["speaker_notes"] == "Pause here."
    assert after[1]["speaker_notes_source"] == "user"


def test_a_notes_save_creates_no_save_point(env):
    # Sabotage: call self.create_save_point(...) (or session_manager.create_version) after the save.
    versions_before = env.fixture.version_count()
    with patch.object(
        ChatService,
        "create_save_point",
        autospec=True,
        side_effect=ChatService.create_save_point,
    ) as spy:
        env.service.update_slide_notes(env.sid, 1, "Pause here.")

    spy.assert_not_called()
    assert env.fixture.version_count() == versions_before
    assert _row(env, 1)["speaker_notes"] == "Pause here.", "the save itself must land"


def test_a_notes_save_bumps_the_version_and_returns_it(env):
    # Sabotage: return the pre-save version, or skip save_slide_deck (no bump), or omit _record_deck_version.
    before = env.fixture.version()
    slide_id = _row(env, 1)["slide_id"]

    result = env.service.update_slide_notes(env.sid, 1, "Pause here.")

    assert result == {
        "index": 1,
        "slide_id": slide_id,
        "speaker_notes": "Pause here.",
        "version": before + 1,
    }
    assert env.fixture.version() == before + 1
    # _record_deck_version: the worker's cache now matches the database version, so
    # an expected_version of the returned value is accepted on the next save.
    again = env.service.update_slide_notes(
        env.sid, 1, "Then breathe.", expected_version=result["version"]
    )
    assert again["version"] == before + 2
    assert _row(env, 1)["speaker_notes"] == "Then breathe."


def test_a_matching_slide_id_is_accepted(env):
    # Sabotage: compare slide_id against the wrong slide (e.g. index + 1) or refuse whenever slide_id is given.
    slide_id = _row(env, 1)["slide_id"]
    result = env.service.update_slide_notes(env.sid, 1, "Pause here.", slide_id=slide_id)
    assert result["slide_id"] == slide_id
    assert _row(env, 1)["speaker_notes"] == "Pause here."


def test_whitespace_only_notes_clear(env):
    # Sabotage: store the whitespace as is (no strip), or keep source "user" on an empty save.
    env.service.update_slide_notes(env.sid, 1, "Pause here.")
    assert _row(env, 1)["speaker_notes_source"] == "user"

    result = env.service.update_slide_notes(env.sid, 1, "   \n ")

    row = _row(env, 1)
    assert row["speaker_notes"] is None
    assert row["speaker_notes_source"] is None
    assert result["speaker_notes"] == ""
    read = env.fixture.get_slide_deck()["slides"][1]
    assert read["speaker_notes"] == ""
    assert read["speaker_notes_source"] is None


def test_a_wrong_slide_id_refuses(env):
    # Sabotage: ignore slide_id (write the notes onto whatever slide sits at index).
    before_rows = env.fixture.row_snapshot()
    before_version = env.fixture.version()

    with pytest.raises(ValueError):
        env.service.update_slide_notes(env.sid, 1, "Pause here.", slide_id="not-this-one")

    assert env.fixture.row_snapshot() == before_rows
    assert env.fixture.version() == before_version


@pytest.mark.parametrize("index", [-1, 3])
def test_a_bad_index_refuses(env, index):
    # Sabotage: drop the bounds check (Python reads -1 as the last slide; 3 raises IndexError, not ValueError).
    before_rows = env.fixture.row_snapshot()
    before_version = env.fixture.version()

    with pytest.raises(ValueError):
        env.service.update_slide_notes(env.sid, index, "Pause here.")

    assert env.fixture.row_snapshot() == before_rows
    assert env.fixture.version() == before_version


def test_a_stale_expected_version_refuses(env):
    # Sabotage: drop the except-restore of the old (notes, source) pair on the cached slide.
    first = env.service.update_slide_notes(env.sid, 1, "Old notes.")
    stale = first["version"] - 1

    with pytest.raises(VersionConflictError):
        env.service.update_slide_notes(env.sid, 1, "Rejected notes.", expected_version=stale)

    assert _row(env, 1)["speaker_notes"] == "Old notes."
    assert env.fixture.version() == first["version"]
    slides = env.service.get_slides(env.sid)["slides"]
    assert slides[1]["speaker_notes"] == "Old notes."
    # The worker's own cache: its version still equals the database's, so it is
    # served as is.  It must not hold the rejected notes.
    cached = env.service._get_or_load_deck(env.sid).slides[1]
    assert cached.speaker_notes == "Old notes."
    assert cached.speaker_notes_source == "user"
    # A later, legitimate save through the same worker rewrites every row from that
    # cache: the rejected notes must not ride along onto slide 1.
    env.service.update_slide_notes(env.sid, 0, "Slide one notes.")
    assert _row(env, 1)["speaker_notes"] == "Old notes."
    assert _row(env, 1)["speaker_notes_source"] == "user"
    assert _row(env, 0)["speaker_notes"] == "Slide one notes."


# ---------------------------------------------------------------------------
# Service: the saved notes are user notes (D10)
# ---------------------------------------------------------------------------


def test_notes_survive_a_later_html_save(env):
    # Sabotage: have update_slide drop the original notes when the new HTML has no aside.
    env.service.update_slide_notes(env.sid, 1, "Pause here.")

    env.service.update_slide(env.sid, 1, _PLAIN_HTML)

    row = _row(env, 1)
    assert "Slide Two, edited" in row["html"], "the HTML save must land"
    assert row["speaker_notes"] == "Pause here."
    assert row["speaker_notes_source"] == "user"


def test_a_user_note_survives_a_later_model_write(env):
    # Sabotage: tag the notes-only save "model" (or leave its source None), so the partial-write user guard lets "M" in.
    env.service.update_slide_notes(env.sid, 1, "Pause here.")
    assert _row(env, 1)["speaker_notes_source"] == "user"

    SlideWriter(env.sm).write_slide(
        env.sid, 1, "<div class='slide'><h1>Rebuilt</h1></div>", speaker_notes="M"
    )

    row = _row(env, 1)
    assert "Rebuilt" in row["html"], "the model write must land"
    assert row["speaker_notes"] == "Pause here."
    assert row["speaker_notes_source"] == "user"


# ---------------------------------------------------------------------------
# Route harness (pattern of tests/unit/test_manual_insert_route.py:94-160)
# ---------------------------------------------------------------------------

SID = "s1"

_STUB_NOTES_RESULT = {
    "index": 1,
    "slide_id": "sid-b",
    "speaker_notes": "Pause here.",
    "version": 8,
}

_STUB_HTML_RESULT = {
    "index": 1,
    "slide_id": "sid-b",
    "html": "<div class='slide'><h1>B</h1></div>",
}


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
    """The slides router's permission gate; records the level demanded.

    ``refuse`` set: raises 403 after recording, as the real gate does for a viewer.
    """
    state = SimpleNamespace(calls=[], refuse=False)

    def gate(session_id, db, min_permission=PermissionLevel.CAN_VIEW):
        state.calls.append((session_id, min_permission))
        events.append(("gate", session_id))
        if state.refuse:
            raise HTTPException(status_code=403, detail="no permission")
        return min_permission

    monkeypatch.setattr("src.api.routes.slides._require_slide_permission", gate)
    return state


@pytest.fixture
def locks(monkeypatch, events):
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

    monkeypatch.setattr("src.api.routes.slides.get_session_manager", lambda: _Manager())
    return state


@pytest.fixture
def stub_service(monkeypatch, events):
    """Replaces ChatService for the route; records ``update_slide_notes`` calls.

    ``update_slide`` is stubbed too, so a test can pair the notes route's absence of
    ``mark_dirty`` with the HTML route's presence on the same harness.
    """
    stub = SimpleNamespace(calls=[], html_calls=[], raises=None)

    class _Stub:
        def update_slide_notes(
            self, session_id, index, speaker_notes, *, slide_id=None, expected_version=None
        ):
            stub.calls.append(
                {
                    "session_id": session_id,
                    "index": index,
                    "speaker_notes": speaker_notes,
                    "slide_id": slide_id,
                    "expected_version": expected_version,
                }
            )
            events.append(("service", session_id))
            if stub.raises is not None:
                raise stub.raises
            return copy.deepcopy(_STUB_NOTES_RESULT)

        def update_slide(self, session_id, index, html, *, expected_version=None):
            stub.html_calls.append((session_id, index, html, expected_version))
            events.append(("html_service", session_id))
            return copy.deepcopy(_STUB_HTML_RESULT)

    monkeypatch.setattr("src.api.routes.slides.get_chat_service", lambda: _Stub())
    return stub


@pytest.fixture
def marks(monkeypatch, events):
    calls = []

    def fake_mark_dirty(session_id, author):
        calls.append((session_id, author))
        events.append(("mark_dirty", session_id))
        return True

    monkeypatch.setattr("src.api.routes.slides.mark_dirty", fake_mark_dirty)
    return calls


@pytest.fixture
def route(client, slide_gate, locks, stub_service, marks, monkeypatch, events):
    monkeypatch.setenv("DEV_USER_ID", EDITOR)
    return SimpleNamespace(
        client=client,
        gate=slide_gate,
        locks=locks,
        service=stub_service,
        marks=marks,
        events=events,
    )


def _patch_notes(route, index=1, **body):
    payload = {"session_id": SID, "speaker_notes": "Pause here."}
    payload.update(body)
    return route.client.patch(f"/api/slides/{index}/notes", json=payload)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def test_the_notes_route_requires_can_edit(route):
    # Sabotage: call _require_slide_permission with PermissionLevel.CAN_VIEW (or not at all).
    route.gate.refuse = True

    resp = _patch_notes(route)

    assert resp.status_code == 403, resp.text
    assert route.gate.calls == [(SID, PermissionLevel.CAN_EDIT)]
    assert route.service.calls == []
    assert route.locks.acquired == []


def test_the_notes_route_honours_the_editing_lock(route):
    # Sabotage: drop the require_editing_lock check (or call it after the service).
    route.locks.editing_refusal = "Another editor is editing this deck."

    resp = _patch_notes(route)

    assert resp.status_code == 423, resp.text
    assert route.locks.editing == [SID]
    assert route.service.calls == []
    assert route.locks.acquired == [], "the session lock was taken after a 423"
    assert route.locks.released == []


def test_the_notes_route_refuses_when_the_session_is_busy(route):
    # Sabotage: ignore acquire_session_lock's False (call the service anyway).
    route.locks.grant = False

    resp = _patch_notes(route)

    assert resp.status_code == 409, resp.text
    assert route.service.calls == []
    assert route.locks.released == [], "a lock this request never took was released"


def test_the_notes_route_never_marks_the_spec_dirty(route):
    # Sabotage: add the mark_dirty call to the notes handler (also reddens test_spec_sync_placement.py).
    resp = _patch_notes(route, slide_id="sid-b", expected_version=7)

    assert resp.status_code == 200, resp.text
    assert resp.json() == _STUB_NOTES_RESULT
    assert route.gate.calls == [(SID, PermissionLevel.CAN_EDIT)]
    assert route.service.calls == [
        {
            "session_id": SID,
            "index": 1,
            "speaker_notes": "Pause here.",
            "slide_id": "sid-b",
            "expected_version": 7,
        }
    ]
    assert route.marks == [], "a notes save scheduled a spec review"
    assert route.events == [
        ("gate", SID),
        ("editing_lock", SID),
        ("acquire", SID),
        ("service", SID),
        ("release", SID),
    ]
    assert route.locks.released == [SID]

    # Paired presence: the HTML save on the same harness does mark, so the stub is
    # on the executed path.
    resp = route.client.patch(
        "/api/slides/1", json={"session_id": SID, "html": "<div class='slide'></div>"}
    )
    assert resp.status_code == 200, resp.text
    assert route.marks == [(SID, EDITOR)], "the mark_dirty stub is not on the executed path"


def test_the_notes_route_passes_optional_fields_as_none(route):
    # Sabotage: default slide_id/expected_version to something other than None, or drop them from the call.
    resp = _patch_notes(route, index=0)

    assert resp.status_code == 200, resp.text
    assert route.service.calls == [
        {
            "session_id": SID,
            "index": 0,
            "speaker_notes": "Pause here.",
            "slide_id": None,
            "expected_version": None,
        }
    ]


def test_the_notes_route_rejects_over_long_notes(route):
    # Sabotage: drop Field(max_length=20000) (or raise it).
    resp = _patch_notes(route, speaker_notes="x" * 20001)

    assert resp.status_code == 422, resp.text
    assert route.service.calls == []

    resp = _patch_notes(route, speaker_notes="x" * 20000)
    assert resp.status_code == 200, resp.text
    assert len(route.service.calls) == 1


@pytest.mark.parametrize(
    "error, status",
    [
        (ValueError("Invalid slide index: 9"), 400),
        (VersionConflictError(current_version=5, expected_version=4), 409),
        (PermissionError("locked"), 423),
        (RuntimeError("boom"), 500),
    ],
)
def test_the_notes_route_maps_service_errors_and_releases_the_lock(route, error, status):
    # Sabotage: drop an except clause (it falls to 500) or the finally release.
    route.service.raises = error

    resp = _patch_notes(route)

    assert resp.status_code == status, resp.text
    if status == 500:
        assert resp.json()["detail"] == "Internal server error"
    assert route.locks.released == [SID]
    assert route.marks == []
