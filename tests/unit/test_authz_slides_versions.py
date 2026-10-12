"""Authorization gating tests for slides.py version endpoints (SDR-4437 PR-2)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.database.models.profile_contributor import PermissionLevel


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def deck_gate(monkeypatch):
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.slides._check_deck_permission_for_session", gate
    )
    return calls


@pytest.mark.parametrize(
    "method,path,body,expected_level",
    [
        ("PATCH", "/api/slides/0/verification",
         {"session_id": "s1", "verification": None}, PermissionLevel.CAN_EDIT),
        ("POST", "/api/slides/versions/create",
         {"session_id": "s1", "description": "cp"}, PermissionLevel.CAN_EDIT),
        ("PATCH", "/api/slides/versions/3/verification",
         {"session_id": "s1", "verification_map": {}}, PermissionLevel.CAN_EDIT),
        ("POST", "/api/slides/versions/sync-verification",
         {"session_id": "s1"}, PermissionLevel.CAN_EDIT),
        ("POST", "/api/slides/versions/3/restore",
         {"session_id": "s1"}, PermissionLevel.CAN_MANAGE),
    ],
)
def test_version_writes_gated(client, deck_gate, method, path, body, expected_level):
    resp = client.request(method, path, json=body)
    assert resp.status_code == 403
    assert deck_gate == [("s1", expected_level)]


@pytest.mark.parametrize(
    "path",
    [
        "/api/slides/versions",
        "/api/slides/versions/3",
        "/api/slides/versions/current",
    ],
)
def test_version_reads_gated_can_view(client, deck_gate, path):
    resp = client.get(path, params={"session_id": "s1"})
    assert resp.status_code == 403
    assert deck_gate == [("s1", PermissionLevel.CAN_VIEW)]


@pytest.mark.parametrize(
    "path,manager_method,expected",
    [
        ("/api/slides/versions", "list_versions", {"versions": [], "current_version": None}),
        ("/api/slides/versions/current", "get_current_version_number", {"current_version": None}),
    ],
)
def test_version_reads_tolerate_session_vanishing_after_the_gate(
    client, monkeypatch, path, manager_method, expected
):
    """A session deleted between the permission gate and the read (a tab still
    polling while the session is removed) must answer "no versions", not 500.

    The ``except SessionNotFoundError`` handlers had lost their import, so this
    path raised NameError and returned 500 instead.
    """
    from src.api.services.session_manager import SessionNotFoundError

    monkeypatch.setattr(
        "src.api.routes.slides._check_deck_permission_for_session",
        lambda session_id, min_permission=PermissionLevel.CAN_VIEW: None,
    )

    def _raise(*_args, **_kwargs):
        raise SessionNotFoundError("gone")

    class _Manager:
        pass

    manager = _Manager()
    setattr(manager, manager_method, _raise)
    monkeypatch.setattr("src.api.routes.slides.get_session_manager", lambda: manager)

    resp = client.get(path, params={"session_id": "s1"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == expected
