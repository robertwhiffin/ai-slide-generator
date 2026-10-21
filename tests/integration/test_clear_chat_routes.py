"""#323 — clear the chat on a deck, through the real routes, services and database.

``DELETE /api/sessions/{id}/context`` is driven through ``TestClient(app)``:
the real auth middleware, the real deck gate and creator gate, the real session
lock, the real ``ChatService.clear_context`` and ``SessionManager``, over a real
file-backed SQLite database with a real ``SqlAlchemyCheckpointSaver``.  Nothing
in the clear path is mocked.

What is stubbed, and why
------------------------
* ``get_db_session`` at every module that bound or lazily imports it, plus
  ``app.dependency_overrides[get_db]``, so every read and write lands in this
  test's own database (the pattern of ``test_savepoint_e2e.py``).
* ``src.core.checkpointer.get_checkpointer`` returns a real saver on that same
  database (``clear_context`` imports it lazily).
* ``resolve_display_names`` returns ``{}``: ``get_slide_deck``'s row read
  resolves SCIM display names, and identity resolution is not under test (the
  ``graph_turn_env`` precedent, ``tests/integration/conftest.py``).
* Identity: ``DEV_USER_ID`` is what the auth middleware signs every request in
  as, and ``src.api.routes._authz.get_permission_context`` is pointed at the
  same user (the ``test_savepoint_e2e.py`` precedent).  Permissions themselves
  are NOT stubbed: the deck owner gets CAN_MANAGE by the creator rule, and the
  second user gets CAN_EDIT from a real ``DeckContributor`` row.

The deck is seeded with the tour's own helpers (``_phase1_create_session``,
``_run_stage``): a pinned graph deck with a spec, three verified slides and two
chat rows (the ``chat_prompt`` and the plan reply).

What this file does NOT prove
-----------------------------
No architect and no model run here.  The post-clear turn in the first test is
the tour's SCRIPTED review and edit stages: it proves the backend reads, writes
and serves a cleared conversation correctly, and nothing about what a model is
given.  The architect evidence for "the next turn continues from the Spec and
the committed slides" is ``tests/integration/test_clear_context_graph_turn.py``.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.base import empty_checkpoint

from src.api.main import app
from src.api.routes.sessions import CONVERSATION_BUSY_DETAIL
from src.api.routes.tour import _load_fixture, _phase1_create_session, _run_stage
from src.api.services.session_manager import get_session_manager
from src.core.checkpointer import SqlAlchemyCheckpointSaver
from src.core.database import get_db
from src.core.permission_context import PermissionContext
from src.database.models.deck_contributor import DeckContributor
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import UserSession
from src.database.models.usage_event import UsageEvent
from src.services.conversation_pins import load_conversation_pin
from src.services.graph_configuration import bootstrap_graph_configuration
from tests.integration.conftest import _make_factory, _make_fake_db, _make_graph_engine

OWNER = "owner@example.com"
EDITOR = "editor@example.com"

# Read back by the stored string, the way admin analytics reads usage_events.
_CONTEXT_CLEARED = "context_cleared"

# Every module the seed, the routes and the clear reach ``get_db_session`` through.
_GET_DB_SESSION_TARGETS = (
    "src.core.database.get_db_session",  # lazy imports in chat_service (clear_context)
    "src.api.services.session_manager.get_db_session",
    "src.api.services.slide_repository.get_db_session",
    "src.api.services.deck_level_writer.get_db_session",
    "src.api.routes._authz.get_db_session",
    "src.api.routes.sessions.get_db_session",
)


def _sign_in(monkeypatch, user: str) -> None:
    """Every later request is made by ``user``: the middleware and the deck gate."""
    monkeypatch.setenv("DEV_USER_ID", user)
    monkeypatch.setattr(
        "src.api.routes._authz.get_permission_context",
        lambda: PermissionContext(user_name=user),
    )


def _thread_config(sid: str) -> dict:
    return {"configurable": {"thread_id": sid, "checkpoint_ns": ""}}


@pytest.fixture
def deck(monkeypatch, tmp_path):
    """A seeded, pinned graph deck owned by OWNER, with a graph thread, OWNER signed in."""
    import src.api.services.chat_service as cs_mod
    import src.api.services.session_manager as sm_mod

    engine = _make_graph_engine(str(tmp_path / "routes.db"))
    factory = _make_factory(engine)
    bootstrap_graph_configuration(factory)

    monkeypatch.setattr(cs_mod, "_chat_service_instance", None)
    monkeypatch.setattr(sm_mod, "_session_manager", None)

    fake_db = _make_fake_db(factory)
    for target in _GET_DB_SESSION_TARGETS:
        monkeypatch.setattr(target, fake_db)

    saver = SqlAlchemyCheckpointSaver(session_factory=factory)
    monkeypatch.setattr("src.core.checkpointer.get_checkpointer", lambda: saver)
    monkeypatch.setattr(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    )

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    _sign_in(monkeypatch, OWNER)

    sid = _phase1_create_session(OWNER)["session_id"]
    _run_stage(sid, "plan", OWNER)
    _run_stage(sid, "build", OWNER)

    # The conversation's graph thread, so "the thread is untouched" is checkable.
    saver.put(
        _thread_config(sid),
        empty_checkpoint(),
        {"source": "loop", "step": 0, "parents": {}},
        {},
    )

    try:
        yield SimpleNamespace(sid=sid, factory=factory, saver=saver)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# -- readers -----------------------------------------------------------------


def _ok(resp) -> dict:
    assert resp.status_code == 200, (resp.status_code, resp.text)
    return resp.json()


def _session(sid: str) -> dict:
    with TestClient(app) as client:
        return _ok(client.get(f"/api/sessions/{sid}"))


def _messages(sid: str) -> dict:
    with TestClient(app) as client:
        return _ok(client.get(f"/api/sessions/{sid}/messages"))


def _slide_deck(sid: str) -> dict:
    with TestClient(app) as client:
        return _ok(client.get(f"/api/sessions/{sid}/slides"))["slide_deck"]


def _clear(sid: str):
    with TestClient(app) as client:
        return client.delete(f"/api/sessions/{sid}/context")


def _session_pk(factory, sid: str) -> int:
    with factory() as db:
        return db.query(UserSession).filter(UserSession.session_id == sid).one().id


def _is_processing(factory, sid: str) -> bool:
    """The session lock, read back from the database."""
    with factory() as db:
        return bool(
            db.query(UserSession).filter(UserSession.session_id == sid).one().is_processing
        )


def _cleared_events(factory) -> list[tuple[str, int]]:
    with factory() as db:
        return [
            (e.username, e.session_id)
            for e in db.query(UsageEvent).filter(UsageEvent.event_type == _CONTEXT_CLEARED)
        ]


def _has_thread(saver, sid: str) -> bool:
    return saver.get_tuple(_thread_config(sid)) is not None


# -- tests -------------------------------------------------------------------


def test_a_cleared_chat_reads_back_empty_and_the_next_scripted_turn_shows_only_new_rows(deck):
    """A clear empties every transcript read and keeps the deck, Spec, pin and save point.

    Then the tour's review and edit stages run on the cleared conversation and
    exactly their rows come back.  That post-clear turn is SCRIPTED: no
    architect and no model run, so this proves only that the backend reads,
    writes and serves a cleared conversation correctly.  What a model is given
    after a clear is proven by ``tests/integration/test_clear_context_graph_turn.py``.
    """
    sid, factory = deck.sid, deck.factory
    fixture = _load_fixture()
    script = fixture["stages"]
    edit = script["edit"]
    pos = edit["position"]

    # 1. Before the clear.
    before = _session(sid)
    graph_version = before["graph_version"]
    assert fixture["chat_prompt"] in [m["content"] for m in before["messages"]]

    deck_before = _slide_deck(sid)
    html_before = [s["html"] for s in deck_before["slides"]]
    spec_before = copy.deepcopy(deck_before["deck_spec"])
    assert spec_before and len(html_before) == len(spec_before["slides"]) == 3

    with TestClient(app) as client:
        version_number = _ok(
            client.post(
                "/api/slides/versions/create",
                json={"session_id": sid, "description": "before clear"},
            )
        )["version_number"]
        preview_url = f"/api/slides/versions/{version_number}"
        history_before = _ok(client.get(preview_url, params={"session_id": sid}))[
            "chat_history"
        ]
    assert fixture["chat_prompt"] in [m["content"] for m in history_before]

    pin_before = load_conversation_pin(factory, sid)
    assert _has_thread(deck.saver, sid)

    # 2. Clear.
    _ok(_clear(sid))

    # 3. After the clear.
    after = _session(sid)
    assert after["messages"] == []
    assert after["graph_version"] == graph_version

    listed = _messages(sid)
    assert listed["messages"] == []
    assert listed["count"] == 0

    deck_after = _slide_deck(sid)
    assert [s["html"] for s in deck_after["slides"]] == html_before
    assert deck_after["deck_spec"] == spec_before

    with TestClient(app) as client:
        preview = _ok(client.get(preview_url, params={"session_id": sid}))
    assert preview["chat_history"] == history_before  # previews keep their chat (D9)

    assert load_conversation_pin(factory, sid) == pin_before
    assert not _has_thread(deck.saver, sid)
    assert _cleared_events(factory) == [(OWNER, _session_pk(factory, sid))]

    # 4. A SCRIPTED post-clear turn: the tour's own review and edit stages.
    with TestClient(app) as client:
        for stage in ("review", "edit"):
            result = _ok(client.post(f"/api/tour/demo-deck/{sid}/stages/{stage}"))
            assert result["applied"] is True, (stage, result)

    assert [m["content"] for m in _session(sid)["messages"]] == [
        script["review"]["advisory"],
        edit["user_prompt"],
        edit["architect_reply"],
    ]

    deck_edited = _slide_deck(sid)
    spec_after = deck_edited["deck_spec"]
    assert {k: v for k, v in spec_after.items() if k != "slides"} == {
        k: v for k, v in spec_before.items() if k != "slides"
    }
    assert len(spec_after["slides"]) == len(spec_before["slides"])
    for i, (old, new) in enumerate(zip(spec_before["slides"], spec_after["slides"])):
        if i == pos:
            assert new != old
            assert new == {**old, "content_brief": edit["content_brief"]}
        else:
            assert new == old, i
    # Only slide `pos`'s HTML is evidence: the fixture rewrites the others byte for byte.
    assert deck_edited["slides"][pos]["html"] != html_before[pos]


def test_another_editor_cannot_clear_the_owners_chat(deck, monkeypatch):
    """An editor of the deck who is not the conversation's creator gets 403 and changes nothing.

    The editor's CAN_EDIT is real (a ``DeckContributor`` row on the deck), and
    the positive control shows the deck gate grants it, so the 403 is the
    creator gate's, not the deck gate's.
    """
    sid, factory = deck.sid, deck.factory
    transcript = _messages(sid)["messages"]
    assert transcript
    pin_before = load_conversation_pin(factory, sid)

    with factory() as db:
        db.add(
            DeckContributor(
                user_session_id=_session_pk(factory, sid),
                identity_type="USER",
                identity_id=EDITOR,
                identity_name=EDITOR,
                permission_level=PermissionLevel.CAN_EDIT.value,
                created_by=OWNER,
            )
        )
        db.commit()

    _sign_in(monkeypatch, EDITOR)

    # Positive control: the deck gate resolves CAN_EDIT for this user.
    as_editor = _session(sid)
    assert as_editor["my_permission"] == PermissionLevel.CAN_EDIT.value
    assert as_editor["messages"] == []  # conversations are private

    refused = _clear(sid)
    assert refused.status_code == 403, refused.text
    assert "session creator" in refused.json()["detail"]
    assert not _is_processing(factory, sid)  # refused before the lock

    _sign_in(monkeypatch, OWNER)
    assert _messages(sid)["messages"] == transcript
    assert load_conversation_pin(factory, sid) == pin_before
    assert _has_thread(deck.saver, sid)
    assert _cleared_events(factory) == []


def test_a_clear_while_a_turn_holds_the_session_lock_is_a_409(deck):
    """A clear refused mid-turn changes nothing and leaves the holder's lock held."""
    sid, factory = deck.sid, deck.factory
    transcript = _messages(sid)["messages"]
    assert transcript

    sm = get_session_manager()
    assert sm.acquire_session_lock(sid) is True
    assert _is_processing(factory, sid)

    busy = _clear(sid)
    assert busy.status_code == 409, busy.text
    assert busy.json()["detail"] == CONVERSATION_BUSY_DETAIL

    assert _messages(sid)["messages"] == transcript
    assert _has_thread(deck.saver, sid)
    assert _cleared_events(factory) == []
    assert _is_processing(factory, sid)  # the 409 did not release someone else's lock

    sm.release_session_lock(sid)
    _ok(_clear(sid))
    assert _messages(sid)["messages"] == []
    assert _cleared_events(factory) == [(OWNER, _session_pk(factory, sid))]
    assert not _is_processing(factory, sid)  # the retry released the lock it took
