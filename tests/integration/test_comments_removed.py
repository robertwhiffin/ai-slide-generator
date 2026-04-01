"""Verification test: comment endpoints should not exist.

This test was written BEFORE removing comment code (TDD red phase).
It should FAIL while comments exist and PASS after removal.

Run: pytest tests/integration/test_comments_removed.py -v
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class TestCommentEndpointsRemoved:
    """All comment/mention endpoints should return 404 after removal."""

    def test_list_comments_returns_404(self, client):
        resp = client.get("/api/comments", params={"session_id": "any"})
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_add_comment_returns_404(self, client):
        resp = client.post("/api/comments", json={
            "session_id": "any",
            "slide_id": "s1",
            "content": "test",
        })
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_mentionable_users_returns_404(self, client):
        resp = client.get("/api/comments/mentionable-users", params={"session_id": "any"})
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_mentions_returns_404(self, client):
        resp = client.get("/api/comments/mentions")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_resolve_comment_returns_404(self, client):
        resp = client.post("/api/comments/1/resolve")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_delete_comment_returns_404(self, client):
        resp = client.delete("/api/comments/1")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"
