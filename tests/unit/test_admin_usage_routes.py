"""Unit tests for /api/admin/usage routes."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app)


@pytest.fixture
def mock_service():
    with patch("src.api.routes.admin_usage.UsageService") as cls:
        yield cls.return_value


class TestSummaryEndpoint:
    def test_returns_summary(self, client, mock_service):
        mock_service.get_summary.return_value = {
            "total_users_ever": 10,
            "total_decks_ever": 25,
            "window": {
                "days": 7,
                "active_users": 4,
                "decks_created": 6,
                "avg_decks_per_active_user": 1.5,
                "logins": 12,
            },
        }
        resp = client.get("/api/admin/usage/summary")
        assert resp.status_code == 200
        assert resp.json()["total_users_ever"] == 10
        mock_service.get_summary.assert_called_once()
        assert mock_service.get_summary.call_args.kwargs.get("days") == 7 or (
            mock_service.get_summary.call_args[0]
            and 7 in mock_service.get_summary.call_args[0]
        )

    def test_invalid_days_rejected(self, client, mock_service):
        assert client.get("/api/admin/usage/summary?days=10").status_code == 422
        assert client.get("/api/admin/usage/summary?days=99").status_code == 422

    def test_valid_windows_accepted(self, client, mock_service):
        mock_service.get_summary.return_value = {}
        for days in (7, 14, 21, 28):
            assert (
                client.get(f"/api/admin/usage/summary?days={days}").status_code == 200
            )


class TestOtherEndpoints:
    def test_daily(self, client, mock_service):
        mock_service.get_daily.return_value = {"history_boundary": None, "days": []}
        resp = client.get("/api/admin/usage/daily?days=14")
        assert resp.status_code == 200
        assert resp.json()["days"] == []

    def test_top_users(self, client, mock_service):
        mock_service.get_top_users.return_value = [
            {"username": "a@x.com", "logins": 3, "sessions_created": 1, "decks_created": 1}
        ]
        resp = client.get("/api/admin/usage/top-users")
        assert resp.status_code == 200
        assert resp.json()[0]["username"] == "a@x.com"

    def test_funnel(self, client, mock_service):
        mock_service.get_funnel.return_value = {
            "logins": 5,
            "users_who_logged_in": 3,
            "users_who_created_deck": 2,
            "decks_created": 2,
            "proxy": False,
        }
        assert client.get("/api/admin/usage/funnel").status_code == 200

    def test_retention(self, client, mock_service):
        mock_service.get_retention.return_value = []
        assert client.get("/api/admin/usage/retention").status_code == 200

    def test_heatmap(self, client, mock_service):
        mock_service.get_heatmap.return_value = {
            "matrix": [[0] * 24 for _ in range(7)],
            "max": 0,
        }
        assert client.get("/api/admin/usage/heatmap").status_code == 200

    def test_service_error_returns_500(self, client, mock_service):
        mock_service.get_summary.side_effect = RuntimeError("boom")
        assert client.get("/api/admin/usage/summary").status_code == 500
