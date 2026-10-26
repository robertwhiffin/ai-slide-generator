"""`POST /api/slides` pins its own permission LEVEL, because nothing else can.

`tests/unit/test_route_authz_coverage.py` checks that a sensitive route has *a*
permission check — it reads the handler source for a gating call. It cannot detect
a WRONG level: measured by sabotage on this workstream, it passed 7 green with a
real level defect present on another route. So a route that mutates a deck has to
assert the level it demands, here, or "gated" silently means "gated at CAN_VIEW"
and any viewer of a shared deck can insert slides into it.

Shape borrowed from `tests/unit/test_authz_verification.py`: replace the gating
helper with one that records its arguments and refuses, so the assertion is on the
level the handler ASKED FOR and cannot be satisfied by a deny that happened for
some other reason.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.database.models.profile_contributor import PermissionLevel


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def slide_gate(monkeypatch):
    """Record every (session_id, level) the slides router demands, then refuse."""
    calls = []

    def gate(session_id, db, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.slides._require_slide_permission", gate
    )
    return calls


def test_insert_slide_requires_can_edit(client, slide_gate):
    resp = client.post(
        "/api/slides", json={"session_id": "s1", "position": 1}
    )
    assert resp.status_code == 403
    assert slide_gate == [("s1", PermissionLevel.CAN_EDIT)], (
        "the insert route did not demand CAN_EDIT: a viewer on a shared deck can "
        f"insert slides into it ({slide_gate})"
    )


def test_the_gate_runs_before_any_mutation(client, monkeypatch):
    """PAIRED with the level above: a denied request must not reach the service.

    Asserting the level alone is compatible with a handler that checks the
    permission AFTER doing the work, so the service method is replaced with one
    that fails loudly if it is ever called.
    """
    calls = []

    def gate(session_id, db, min_permission=PermissionLevel.CAN_VIEW):
        raise HTTPException(status_code=403, detail="denied")

    def must_not_run(*args, **kwargs):  # pragma: no cover - the point is it isn't
        calls.append(args)
        raise AssertionError("insert_slide ran despite a 403 from the gate")

    monkeypatch.setattr("src.api.routes.slides._require_slide_permission", gate)
    monkeypatch.setattr(
        "src.api.services.chat_service.ChatService.insert_slide", must_not_run
    )

    resp = client.post("/api/slides", json={"session_id": "s1", "position": 1})
    assert resp.status_code == 403
    assert calls == []


def test_the_gate_helper_is_actually_reachable_on_this_route(client, slide_gate):
    """Guard the guard: if the monkeypatch target were wrong, both tests above
    would report a 403 that came from somewhere else entirely and prove nothing.

    A recorded call is the evidence that the patched helper is the one the handler
    uses.
    """
    client.post("/api/slides", json={"session_id": "s-probe", "position": 0})
    assert slide_gate and slide_gate[0][0] == "s-probe", (
        f"the patched gate was never called by the insert handler: {slide_gate}"
    )
