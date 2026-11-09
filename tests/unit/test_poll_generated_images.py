"""Chat image generation, Task 5: the polling projection forwards ``generated_images``.

``SessionManager.msg_to_stream_event`` turns a ``get_messages_for_request`` row into a
``GET /chat/poll`` event. Today its ``metadata`` carries only ``details`` (#321) and
``sign_in_url`` (Gateway MCP). It now also carries ``generated_images``, filtered through
the shared sanitiser (``src.utils.generated_images.sanitize_generated_images``, ruling R2),
and only when what survives is non-empty. Nothing else changes: a tool row's input still
never reaches ``metadata``.

Contract: ``docs/superpowers/plans/2026-11-09-chat-image-generation-CORRECTIONS.md``,
"Shared metadata shape" and "Polling" under "Unit G interface". Mirrors
``tests/unit/test_poll_notice_details.py``: every event is pinned by full-dict equality.
"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.services.session_manager import SessionManager

DETAILS = {"stage": "builder", "error": "RuntimeError", "request_id": "req-321"}
SIGN_IN_URL = "https://h.example/mcp-service-login?name=cat.sch.lakedraw&o=1"
SIGN_IN = f"To use LakeDraw, sign in here: {SIGN_IN_URL} — then ask again."
REPLY = "Here are three options. Which one should go on slide 3?"

IMAGES = [
    {
        "token": "abc_DEF-1",
        "kind": "illustration",
        "option": 1,
        "prompt": "A calm harbour at dawn",
        "for_slide": 3,
        "slides": [],
    },
    {
        "token": "tok2",
        "kind": "illustration",
        "option": 2,
        "prompt": "A calm harbour at dawn",
        "for_slide": 3,
        "slides": [3],
    },
    {
        "token": "Tok-3",
        "kind": "vector_icon",
        "option": 3,
        "prompt": "A shield",
        "for_slide": None,
        "slides": [],
    },
]


def _row(msg_id, *, role, message_type, content, metadata):
    """A row in exactly the shape ``get_messages_for_request`` returns."""
    return {
        "id": msg_id,
        "role": role,
        "content": content,
        "message_type": message_type,
        "created_at": "2026-11-09T00:00:00",
        "metadata": metadata,
    }


def _reply_row(msg_id, metadata):
    return _row(
        msg_id, role="assistant", message_type="llm_response", content=REPLY, metadata=metadata
    )


def _project(row):
    return SessionManager().msg_to_stream_event(row)


def _images():
    return copy.deepcopy(IMAGES)


# ---------------------------------------------------------------------------
# Valid metadata is forwarded exactly
# ---------------------------------------------------------------------------


def test_an_architect_reply_with_generated_images_forwards_them_exactly():
    row = _reply_row(
        40, {"node": "architect", "intent": "discuss", "generated_images": _images()}
    )

    event = _project(row)

    assert event == {
        "type": "assistant",
        "content": REPLY,
        "tool_name": None,
        "tool_input": None,
        "tool_output": None,
        "message_id": 40,
        "agent": None,
        "metadata": {"generated_images": IMAGES},
    }


def test_the_row_is_not_modified_by_the_projection():
    metadata = {"node": "architect", "generated_images": _images() + ["junk"]}
    row = _reply_row(41, metadata)
    before = copy.deepcopy(row)

    _project(row)

    assert row == before


# ---------------------------------------------------------------------------
# Junk is dropped; the key is omitted when nothing survives
# ---------------------------------------------------------------------------


def test_junk_entries_and_unknown_keys_are_dropped():
    first = {**copy.deepcopy(IMAGES[0]), "tool_input": {"query": "secret"}, "html": "<b>x</b>"}
    value = [
        first,
        {"token": "bad token", "kind": "icon", "option": 1, "slides": []},
        {"token": "tok9", "kind": "icon_png", "option": 1, "slides": []},
        {"token": "tok8", "kind": "icon", "option": 0, "slides": []},
        "junk",
        None,
        copy.deepcopy(IMAGES[2]),
    ]
    row = _reply_row(42, {"node": "architect", "generated_images": value})

    event = _project(row)

    assert event["metadata"] == {"generated_images": [IMAGES[0], IMAGES[2]]}


@pytest.mark.parametrize(
    "value",
    [
        [],
        None,
        "generated_images",
        {"token": "abc", "kind": "icon", "option": 1},
        [None, 1, "x"],
        [{"token": "a b", "kind": "icon", "option": 1, "slides": []}],
        [{"token": "abc", "kind": "photo", "option": 1, "slides": []}],
    ],
    ids=["empty", "none", "string", "dict", "junk-list", "bad-token", "bad-kind"],
)
def test_nothing_valid_omits_the_key_and_projects_none(value):
    row = _reply_row(43, {"node": "architect", "intent": "discuss", "generated_images": value})

    event = _project(row)

    assert event == {
        "type": "assistant",
        "content": REPLY,
        "tool_name": None,
        "tool_input": None,
        "tool_output": None,
        "message_id": 43,
        "agent": None,
        "metadata": None,
    }


def test_nothing_valid_beside_details_forwards_details_alone():
    row = _row(
        44,
        role="assistant",
        message_type="info",
        content="Slide 3 couldn't be built.",
        metadata={"details": dict(DETAILS), "generated_images": [{"token": "a b"}]},
    )

    event = _project(row)

    assert event["metadata"] == {"details": DETAILS}
    assert "generated_images" not in event["metadata"]


# ---------------------------------------------------------------------------
# Tool rows still never leak their input
# ---------------------------------------------------------------------------


def test_the_image_tool_progress_row_never_leaks_its_input_into_metadata():
    row = _row(
        45,
        role="assistant",
        message_type="tool_call",
        content="Generating 3 illustrations",
        metadata={
            "tool_name": "image_generation",
            "tool_input": {"kind": "illustration", "count": 3},
        },
    )

    event = _project(row)

    assert event == {
        "type": "tool_call",
        "content": "Generating 3 illustrations",
        "tool_name": "image_generation",
        "tool_input": {"kind": "illustration", "count": 3},
        "tool_output": None,
        "message_id": 45,
        "agent": None,
        "metadata": None,
    }


def test_a_tool_call_row_carrying_images_still_never_forwards_its_input():
    """Whether images on a tool row are forwarded is left open; its input never is."""
    row = _row(
        46,
        role="assistant",
        message_type="tool_call",
        content="Calling q",
        metadata={
            "tool_name": "q",
            "tool_input": {"query": "secret"},
            "generated_images": _images(),
        },
    )

    event = _project(row)

    assert event["metadata"] in (None, {"generated_images": IMAGES})
    assert "secret" not in repr(event["metadata"])
    assert event["tool_name"] == "q"
    assert event["tool_input"] == {"query": "secret"}


# ---------------------------------------------------------------------------
# details and sign_in_url behave as before
# ---------------------------------------------------------------------------


def test_details_alone_are_forwarded_as_before():
    row = _row(
        47,
        role="assistant",
        message_type="info",
        content="Slide 3 couldn't be built.",
        metadata={"details": dict(DETAILS), "node": "builder"},
    )

    assert _project(row) == {
        "type": "assistant",
        "content": "Slide 3 couldn't be built.",
        "tool_name": None,
        "tool_input": None,
        "tool_output": None,
        "message_id": 47,
        "agent": None,
        "metadata": {"details": DETAILS},
    }


def test_a_sign_in_link_alone_is_forwarded_as_before():
    row = _row(
        48,
        role="assistant",
        message_type="info",
        content=SIGN_IN,
        metadata={"sign_in_url": SIGN_IN_URL},
    )

    assert _project(row)["metadata"] == {"sign_in_url": SIGN_IN_URL}


def test_details_sign_in_link_and_images_are_all_forwarded_and_nothing_else():
    row = _row(
        49,
        role="assistant",
        message_type="info",
        content=SIGN_IN,
        metadata={
            "details": dict(DETAILS),
            "sign_in_url": SIGN_IN_URL,
            "generated_images": _images(),
            "node": "architect",
            "intent": "discuss",
        },
    )

    assert _project(row)["metadata"] == {
        "details": DETAILS,
        "sign_in_url": SIGN_IN_URL,
        "generated_images": IMAGES,
    }


@pytest.mark.parametrize(
    "metadata",
    [
        {"details": {}},
        {"details": "not-a-dict"},
        {"sign_in_url": ""},
        {"sign_in_url": 5},
        {"node": "architect", "intent": "discuss"},
        None,
    ],
    ids=["empty-details", "string-details", "empty-link", "int-link", "other-keys", "none"],
)
def test_rows_without_anything_forwardable_still_project_none(metadata):
    row = _reply_row(50, metadata)

    assert _project(row)["metadata"] is None


# ---------------------------------------------------------------------------
# On the wire
# ---------------------------------------------------------------------------


def test_the_poll_route_carries_the_generated_images_on_the_wire(monkeypatch):
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
            61,
            role="assistant",
            message_type="tool_call",
            content="Generating 3 illustrations",
            metadata={
                "tool_name": "image_generation",
                "tool_input": {"kind": "illustration", "count": 3},
            },
        ),
        _reply_row(
            62,
            {"node": "architect", "intent": "discuss", "generated_images": _images() + ["junk"]},
        ),
    ]
    mgr.slides_since_cursor.return_value = []
    mgr.slide_revisions_since.return_value = []
    # The real conversion, so the wire carries what production would send.
    mgr.msg_to_stream_event.side_effect = SessionManager.msg_to_stream_event.__get__(
        mgr, SessionManager
    )

    resp = TestClient(app, raise_server_exceptions=False).get("/api/chat/poll/req-376")

    assert resp.status_code == 200, resp.text
    events = {e["message_id"]: e for e in resp.json()["events"]}
    assert events[62]["metadata"] == {"generated_images": IMAGES}
    assert events[61]["metadata"] is None
    assert events[61]["tool_name"] == "image_generation"
    assert events[61]["tool_input"] == {"kind": "illustration", "count": 3}
