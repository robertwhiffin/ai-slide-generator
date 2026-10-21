"""#317 — delete one message of a conversation, through the real routes, services and database.

``DELETE /api/sessions/{id}/messages/{message_id}`` is driven through
``TestClient(app)``: the real auth middleware, the real deck gate and creator
gate, the real session lock, the real ``ChatService.delete_message`` and
``SessionManager``, over a real file-backed SQLite database with a real
``SqlAlchemyCheckpointSaver``.  Nothing in the delete path is mocked.

The harness is #323's ``deck`` fixture (``tests/integration/test_clear_chat_routes.py``),
imported as is: its module docstring lists what it stubs and why (the database
seams, the checkpointer seam, SCIM display names, the signed-in user).
Permissions are NOT stubbed: the owner gets CAN_MANAGE by the creator rule and
the second user gets CAN_EDIT from a real ``DeckContributor`` row.

Seeding: the fixture ran the tour's ``plan`` and ``build`` stages.  Every test
then runs ``review`` and ``edit`` through ``POST /api/tour/demo-deck/{sid}/stages/{stage}``,
so the transcript is two turns:

* turn 1: ``chat_prompt`` (user), the plan reply (assistant), the review
  advisory (assistant, ``info``);
* turn 2: the edit ``user_prompt`` (user), the edit reply (assistant).

What this file does NOT prove
-----------------------------
No architect and no model run here.  What an agent and the checkpoint hold
after a delete is ``tests/integration/test_delete_message_graph_turn.py``.
"""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes.sessions import CONVERSATION_BUSY_DETAIL, MESSAGE_NOT_FOUND_DETAIL
from src.api.routes.tour import _load_fixture, _phase1_create_session
from src.api.services.chat_service import resolve_engine_mode
from src.api.services.session_manager import get_session_manager
from src.database.models.deck_contributor import DeckContributor
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import SessionMessage
from src.database.models.usage_event import UsageEvent
from src.services.conversation_pins import load_conversation_pin
from tests.integration.test_clear_chat_routes import (  # noqa: F401 (deck: a fixture)
    EDITOR,
    OWNER,
    _has_thread,
    _is_processing,
    _messages,
    _ok,
    _session,
    _session_pk,
    _sign_in,
    _slide_deck,
    deck,
)

# Read back by the stored strings, the way admin analytics and the transcript
# readers see them, so a renamed constant cannot make these tests agree with it.
_MESSAGE_DELETED = "message_deleted"
_ENGINE_MODE_MARKER = "engine_mode_marker"


# -- helpers -----------------------------------------------------------------


def _delete(sid: str, message_id: int):
    with TestClient(app) as client:
        return client.delete(f"/api/sessions/{sid}/messages/{message_id}")


def _deleted_events(factory) -> list[tuple[str, int]]:
    with factory() as db:
        return [
            (e.username, e.session_id)
            for e in db.query(UsageEvent).filter(UsageEvent.event_type == _MESSAGE_DELETED)
        ]


def _seed_two_turns(sid: str) -> list[dict]:
    """Run the tour's review and edit stages; return the five rows of ``GET …/messages``."""
    with TestClient(app) as client:
        for stage in ("review", "edit"):
            result = _ok(client.post(f"/api/tour/demo-deck/{sid}/stages/{stage}"))
            assert result["applied"] is True, (stage, result)

    fixture = _load_fixture()
    script = fixture["stages"]
    rows = _messages(sid)["messages"]
    assert [(m["role"], m["content"]) for m in rows] == [
        ("user", fixture["chat_prompt"]),
        ("assistant", script["plan"]["architect_reply"]),
        ("assistant", script["review"]["advisory"]),
        ("user", script["edit"]["user_prompt"]),
        ("assistant", script["edit"]["architect_reply"]),
    ]
    assert all(isinstance(m["id"], int) for m in rows)
    return rows


def _save_point_history(sid: str, description: str) -> tuple[int, list[dict]]:
    """Take a save point through the route; return its number and its preview chat."""
    with TestClient(app) as client:
        number = _ok(
            client.post(
                "/api/slides/versions/create",
                json={"session_id": sid, "description": description},
            )
        )["version_number"]
    return number, _preview_history(sid, number)


def _preview_history(sid: str, number: int) -> list[dict]:
    with TestClient(app) as client:
        return _ok(
            client.get(f"/api/slides/versions/{number}", params={"session_id": sid})
        )["chat_history"]


def _row_type(factory, message_id: int):
    """The stored row's ``message_type``, or ``None`` when no row has this id."""
    with factory() as db:
        row = db.query(SessionMessage).filter(SessionMessage.id == message_id).first()
        return None if row is None else row.message_type


# -- tests -------------------------------------------------------------------


def test_deleting_a_turn_through_the_routes_keeps_the_deck_spec_and_save_points(
    deck,  # noqa: F811 (the imported fixture)
):
    """A delete removes one turn from every transcript read and rolls nothing back.

    The deck (slides, Spec, the edit's brief at ``stages.edit.position``), the
    Conversation Pin and a save point taken before the delete are unchanged;
    the graph thread is gone; one ``message_deleted`` row names the caller.
    """
    sid, factory = deck.sid, deck.factory
    edit = _load_fixture()["stages"]["edit"]
    pos = edit["position"]
    rows = _seed_two_turns(sid)
    first_turn, edit_prompt_id = rows[:3], rows[3]["id"]

    # 1. Before the delete.
    version_number, history_before = _save_point_history(sid, "before delete")
    assert edit["user_prompt"] in [m["content"] for m in history_before]

    deck_before = copy.deepcopy(_slide_deck(sid))
    assert len(deck_before["slides"]) == 3
    # The edit turn's Spec change is there, so "kept" below is not vacuous.
    assert deck_before["deck_spec"]["slides"][pos]["content_brief"] == edit["content_brief"]

    session_before = _session(sid)
    pin_before = load_conversation_pin(factory, sid)
    assert _has_thread(deck.saver, sid)
    assert _deleted_events(factory) == []

    # 2. Delete the edit turn.
    result = _ok(_delete(sid, edit_prompt_id))
    assert result["status"] == "deleted"
    assert result["message_id"] == edit_prompt_id
    assert result["deleted_messages"] == 2
    assert result["hidden_message_id"] is None

    # 3. After the delete.
    session_after = _session(sid)
    assert [m["content"] for m in session_after["messages"]] == [
        m["content"] for m in first_turn
    ]
    assert session_after["message_count"] == 3
    assert session_after["graph_version"] == session_before["graph_version"]

    listed = _messages(sid)
    assert listed["messages"] == first_turn
    assert listed["count"] == 3

    deck_after = _slide_deck(sid)
    assert deck_after == deck_before  # slide rows, HTML, verification, Spec: nothing undone
    assert deck_after["deck_spec"]["slides"][pos]["content_brief"] == edit["content_brief"]

    # The save point keeps the chat it captured, deleted turn included (D10).
    assert _preview_history(sid, version_number) == history_before

    assert load_conversation_pin(factory, sid) == pin_before
    assert not _has_thread(deck.saver, sid)
    assert _deleted_events(factory) == [(OWNER, _session_pk(factory, sid))]

    # A save point taken after the delete captures the conversation without it.
    _, history_after = _save_point_history(sid, "after delete")
    assert [m["id"] for m in history_after] == [m["id"] for m in first_turn]

    # 4. The turn is gone, and a turn is never addressed through a reply.
    again = _delete(sid, edit_prompt_id)
    assert again.status_code == 404, again.text
    assert again.json()["detail"] == MESSAGE_NOT_FOUND_DETAIL

    via_reply = _delete(sid, first_turn[1]["id"])  # the plan reply (assistant)
    assert via_reply.status_code == 404, via_reply.text
    assert via_reply.json()["detail"] == MESSAGE_NOT_FOUND_DETAIL

    assert _messages(sid)["messages"] == first_turn
    assert _deleted_events(factory) == [(OWNER, _session_pk(factory, sid))]


def test_deleting_the_first_turn_hides_it_and_keeps_the_engine_and_pin(
    deck,  # noqa: F811 (the imported fixture)
):
    """The session's earliest user row is re-typed, never deleted; the rest of its turn goes."""
    sid, factory = deck.sid, deck.factory
    rows = _seed_two_turns(sid)
    prompt_id, edit_turn = rows[0]["id"], rows[3:]

    pin_before = load_conversation_pin(factory, sid)
    assert resolve_engine_mode(sid) == "graph"
    assert _row_type(factory, prompt_id) == "chat"

    result = _ok(_delete(sid, prompt_id))
    assert result["hidden_message_id"] == prompt_id
    assert result["deleted_messages"] == 2  # the plan reply and the advisory

    listed = _messages(sid)["messages"]
    assert listed == edit_turn
    assert [m["content"] for m in _session(sid)["messages"]] == [
        m["content"] for m in edit_turn
    ]

    # The row is kept, hidden: engine mode, the pin and the title still see a first message.
    assert _row_type(factory, prompt_id) == _ENGINE_MODE_MARKER
    assert resolve_engine_mode(sid) == "graph"
    assert load_conversation_pin(factory, sid) == pin_before
    assert _session(sid)["message_count"] == len(listed) + 1

    assert not _has_thread(deck.saver, sid)
    assert _deleted_events(factory) == [(OWNER, _session_pk(factory, sid))]

    # A save point taken now excludes the hidden row (D10).
    _, history = _save_point_history(sid, "after first-turn delete")
    assert [m["id"] for m in history] == [m["id"] for m in edit_turn]

    again = _delete(sid, prompt_id)
    assert again.status_code == 404, again.text
    assert again.json()["detail"] == MESSAGE_NOT_FOUND_DETAIL
    assert _row_type(factory, prompt_id) == _ENGINE_MODE_MARKER
    assert _deleted_events(factory) == [(OWNER, _session_pk(factory, sid))]


def test_another_editor_cannot_delete_from_the_owners_conversation(
    deck, monkeypatch,  # noqa: F811 (the imported fixture)
):
    """An editor of the deck who did not create the conversation gets 403 and changes nothing.

    The editor's CAN_EDIT is real (a ``DeckContributor`` row on the deck), and
    the positive control shows the deck gate grants it, so the 403 is the
    creator gate's, not the deck gate's.
    """
    sid, factory = deck.sid, deck.factory
    rows = _seed_two_turns(sid)
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

    refused = _delete(sid, rows[3]["id"])
    assert refused.status_code == 403, refused.text
    assert "session creator" in refused.json()["detail"]
    assert not _is_processing(factory, sid)  # refused before the lock

    _sign_in(monkeypatch, OWNER)
    assert _messages(sid)["messages"] == rows
    assert load_conversation_pin(factory, sid) == pin_before
    assert _has_thread(deck.saver, sid)
    assert _deleted_events(factory) == []


def test_a_delete_while_a_turn_holds_the_session_lock_is_a_409(
    deck,  # noqa: F811 (the imported fixture)
):
    """A delete refused mid-turn changes nothing and leaves the holder's lock held."""
    sid, factory = deck.sid, deck.factory
    rows = _seed_two_turns(sid)
    edit_prompt_id = rows[3]["id"]

    sm = get_session_manager()
    assert sm.acquire_session_lock(sid) is True
    assert _is_processing(factory, sid)

    busy = _delete(sid, edit_prompt_id)
    assert busy.status_code == 409, busy.text
    assert busy.json()["detail"] == CONVERSATION_BUSY_DETAIL

    assert _messages(sid)["messages"] == rows
    assert _has_thread(deck.saver, sid)
    assert _deleted_events(factory) == []
    assert _is_processing(factory, sid)  # the 409 did not release someone else's lock

    sm.release_session_lock(sid)
    result = _ok(_delete(sid, edit_prompt_id))
    assert result["deleted_messages"] == 2
    assert _messages(sid)["messages"] == rows[:3]
    assert _deleted_events(factory) == [(OWNER, _session_pk(factory, sid))]
    assert not _is_processing(factory, sid)  # the retry released the lock it took


def test_a_message_id_from_another_session_is_a_404_and_neither_conversation_changes(
    deck,  # noqa: F811 (the imported fixture)
):
    """Rows are read within the addressed session: another session's id is not found there."""
    sid, factory = deck.sid, deck.factory
    rows = _seed_two_turns(sid)

    other = _phase1_create_session(OWNER)["session_id"]
    other_rows = _messages(other)["messages"]
    assert [(m["role"], m["content"]) for m in other_rows] == [
        ("user", _load_fixture()["chat_prompt"])
    ]
    other_id = other_rows[0]["id"]
    assert other_id not in {m["id"] for m in rows}

    missing = _delete(sid, other_id)
    assert missing.status_code == 404, missing.text
    assert missing.json()["detail"] == MESSAGE_NOT_FOUND_DETAIL

    assert _messages(sid)["messages"] == rows
    assert _messages(other)["messages"] == other_rows
    assert _row_type(factory, other_id) == "chat"
    assert _has_thread(deck.saver, sid)
    assert _deleted_events(factory) == []
