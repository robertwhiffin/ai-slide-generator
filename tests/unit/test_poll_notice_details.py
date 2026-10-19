"""#321: the polling projection forwards a failure notice's details, and nothing else.

``SessionManager.msg_to_stream_event`` turns a ``get_messages_for_request`` row
into a ``GET /chat/poll`` event.  It gains exactly one key, ``metadata``, which is
``{"details": ...}`` when the row carries a non-empty dict of details and ``None``
otherwise.  It never forwards a row's whole metadata: a tool row's metadata carries
the tool's input, and a tour row's carries tour bookkeeping.

Every other key of the event is pinned by full-dict equality against today's
literal projection, so neither a dropped nor an extra key can slip through.

The constructor has no side effects, so the projection is called directly on
dicts shaped like ``get_messages_for_request`` output.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.services.session_manager import SessionManager

DETAILS = {"stage": "builder", "error": "RuntimeError", "request_id": "req-321"}


def _row(msg_id, *, role, message_type, content, metadata):
    """A row in exactly the shape ``get_messages_for_request`` returns."""
    return {
        "id": msg_id,
        "role": role,
        "content": content,
        "message_type": message_type,
        "created_at": "2026-10-19T00:00:00",
        "metadata": metadata,
    }


def _project(row):
    return SessionManager().msg_to_stream_event(row)


def test_an_info_row_with_details_forwards_them():
    row = _row(
        7,
        role="assistant",
        message_type="info",
        content="Slide 3 couldn't be built.",
        metadata={"details": dict(DETAILS)},
    )

    event = _project(row)

    assert event == {
        "type": "assistant",
        "content": "Slide 3 couldn't be built.",
        "tool_name": None,
        "tool_input": None,
        "tool_output": None,
        "message_id": 7,
        "metadata": {"details": DETAILS},
    }


def test_an_old_info_row_without_metadata_projects_none():
    """Every row persisted before notices had details."""
    row = _row(
        8,
        role="assistant",
        message_type="info",
        content="Slide 2 could not be built (stage: Error).",
        metadata=None,
    )

    event = _project(row)

    assert event == {
        "type": "assistant",
        "content": "Slide 2 could not be built (stage: Error).",
        "tool_name": None,
        "tool_input": None,
        "tool_output": None,
        "message_id": 8,
        "metadata": None,
    }


def test_a_tool_call_row_never_leaks_its_input_into_metadata():
    row = _row(
        9,
        role="assistant",
        message_type="tool_call",
        content="Calling q",
        metadata={"tool_name": "q", "tool_input": {"query": "secret"}},
    )

    event = _project(row)

    assert event["metadata"] is None
    # The tool mapping itself is unchanged.
    assert event == {
        "type": "tool_call",
        "content": "Calling q",
        "tool_name": "q",
        "tool_input": {"query": "secret"},
        "tool_output": None,
        "message_id": 9,
        "metadata": None,
    }


def test_a_tool_result_row_projects_as_today_with_no_metadata():
    row = _row(
        10,
        role="tool",
        message_type="tool_result",
        content="rows: 3",
        metadata={"tool_name": "q", "full_length": 7},
    )

    event = _project(row)

    assert event == {
        "type": "tool_result",
        "content": "rows: 3",
        "tool_name": "q",
        "tool_input": None,
        "tool_output": "rows: 3",
        "message_id": 10,
        "metadata": None,
    }


def test_a_tour_row_projects_as_today_with_no_metadata():
    row = _row(
        11,
        role="assistant",
        message_type="llm_response",
        content="Here is the plan.",
        metadata={"tour_stage": "prompt", "node": "architect"},
    )

    event = _project(row)

    assert event == {
        "type": "assistant",
        "content": "Here is the plan.",
        "tool_name": None,
        "tool_input": None,
        "tool_output": None,
        "message_id": 11,
        "metadata": None,
    }


def test_only_the_details_key_is_forwarded_from_a_notice_row():
    """A notice row that also carries other metadata forwards details alone."""
    row = _row(
        12,
        role="assistant",
        message_type="info",
        content="Slide 1 couldn't be built.",
        metadata={"details": dict(DETAILS), "tour_stage": "build", "node": "builder"},
    )

    event = _project(row)

    assert event["metadata"] == {"details": DETAILS}


@pytest.mark.parametrize(
    "details",
    ["not-a-dict", {}, None, ["builder", "RuntimeError"]],
    ids=["string", "empty-dict", "none", "list"],
)
def test_details_that_are_not_a_non_empty_dict_project_none(details):
    row = _row(
        13,
        role="assistant",
        message_type="info",
        content="x",
        metadata={"details": details},
    )

    event = _project(row)

    assert event["metadata"] is None
    assert event["type"] == "assistant"
    assert event["content"] == "x"
    assert event["message_id"] == 13


def test_the_poll_route_carries_the_details_on_the_wire(monkeypatch):
    """The route returns the projection as-is: no response model strips the key."""
    from src.api.main import app

    mgr = MagicMock()
    monkeypatch.setattr("src.api.routes.chat.get_session_manager", lambda: mgr)
    monkeypatch.setattr("src.api.routes.chat.get_current_user", lambda: "owner@x.com")
    mgr.get_session_id_for_request.return_value = "sess-1"
    mgr.get_session.return_value = {"created_by": "owner@x.com"}
    mgr.get_chat_request.return_value = {
        "status": "processing",
        "result": None,
        "error_message": None,
    }
    mgr.get_messages_for_request.return_value = [
        _row(
            21,
            role="assistant",
            message_type="tool_call",
            content="Calling q",
            metadata={"tool_name": "q", "tool_input": {"query": "secret"}},
        ),
        _row(
            22,
            role="assistant",
            message_type="info",
            content="Slide 3 couldn't be built.",
            metadata={"details": dict(DETAILS)},
        ),
    ]
    mgr.slides_since_cursor.return_value = []
    mgr.slide_revisions_since.return_value = []
    # The real conversion, so the wire carries what production would send.
    mgr.msg_to_stream_event.side_effect = SessionManager.msg_to_stream_event.__get__(
        mgr, SessionManager
    )

    resp = TestClient(app, raise_server_exceptions=False).get("/api/chat/poll/req-321")

    assert resp.status_code == 200, resp.text
    events = {e["message_id"]: e for e in resp.json()["events"]}
    assert events[22]["metadata"] == {"details": DETAILS}
    assert events[21]["metadata"] is None
    assert events[21]["tool_input"] == {"query": "secret"}
