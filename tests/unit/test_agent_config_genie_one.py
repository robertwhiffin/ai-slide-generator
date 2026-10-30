"""The ``genie_one`` tool type: schema, persist strip, PATCH /tools, legacy skip."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from src.api.main import app

    monkeypatch.setattr(
        "src.api.routes.agent_config._check_deck_permission_for_session",
        lambda *a, **k: None,
    )
    return TestClient(app)


def _mock_session_manager(agent_config=None):
    mgr = MagicMock()
    mgr.get_session.return_value = {"session_id": "sess-1", "agent_config": agent_config}
    return mgr


class TestSchema:
    def test_genie_one_round_trips_with_no_conversation_id(self):
        from src.api.schemas.agent_config import AgentConfig

        config = AgentConfig.model_validate({"tools": [{"type": "genie_one"}]})
        assert len(config.tools) == 1
        assert config.tools[0].type == "genie_one"
        assert config.tools[0].conversation_id is None
        again = AgentConfig.model_validate(config.model_dump())
        assert again.tools[0].type == "genie_one"
        assert again.tools[0].conversation_id is None

    def test_duplicate_genie_one_is_rejected(self):
        from src.api.schemas.agent_config import AgentConfig

        with pytest.raises(ValueError, match="Duplicate tool: genie_one"):
            AgentConfig.model_validate(
                {"tools": [{"type": "genie_one"}, {"type": "genie_one"}]}
            )

    def test_persist_strip_clears_conversation_id(self):
        from src.api.schemas.agent_config import sanitize_agent_config_for_persist

        out = sanitize_agent_config_for_persist(
            {"tools": [{"type": "genie_one", "conversation_id": "conv-123"}]}
        )
        assert out is not None
        assert out["tools"] == [{"type": "genie_one", "conversation_id": None}]


class TestPatchTools:
    @patch("src.api.routes.agent_config._save_agent_config")
    @patch("src.api.routes.agent_config.get_session_manager")
    def test_add_genie_one(self, mock_get_mgr, mock_save, client):
        mock_get_mgr.return_value = _mock_session_manager({"tools": []})
        mock_save.side_effect = lambda sid, cfg: cfg.model_dump()

        response = client.patch(
            "/api/sessions/sess-1/agent-config/tools",
            json={"action": "add", "tool": {"type": "genie_one"}},
        )
        assert response.status_code == 200, response.text
        assert [t["type"] for t in response.json()["tools"]] == ["genie_one"]

    @patch("src.api.routes.agent_config._save_agent_config")
    @patch("src.api.routes.agent_config.get_session_manager")
    def test_remove_genie_one_keeps_other_tools(self, mock_get_mgr, mock_save, client):
        existing = {
            "tools": [
                {"type": "genie_one"},
                {"type": "genie", "space_id": "g1", "space_name": "Sales"},
            ]
        }
        mock_get_mgr.return_value = _mock_session_manager(existing)
        mock_save.side_effect = lambda sid, cfg: cfg.model_dump()

        response = client.patch(
            "/api/sessions/sess-1/agent-config/tools",
            json={"action": "remove", "tool": {"type": "genie_one"}},
        )
        assert response.status_code == 200, response.text
        assert [t["type"] for t in response.json()["tools"]] == ["genie"]


class TestLegacySkip:
    def test_legacy_build_tools_skips_genie_one(self, caplog):
        from src.api.schemas.agent_config import AgentConfig
        from src.services import agent_resolution

        genie = {"type": "genie", "space_id": "g1", "space_name": "Sales"}

        def _fake_genie_tool(entry, session_data, idx):
            fake = MagicMock()
            fake.name = f"query_genie_space_{idx}"
            return fake

        with patch.object(agent_resolution, "build_genie_tool", side_effect=_fake_genie_tool):
            without = agent_resolution._build_tools(
                AgentConfig.model_validate({"tools": [genie]}), {"session_id": "s1"}
            )
            with caplog.at_level(logging.DEBUG, logger="src.services.agent_resolution"):
                with_genie_one = agent_resolution._build_tools(
                    AgentConfig.model_validate({"tools": [{"type": "genie_one"}, genie]}),
                    {"session_id": "s1"},
                )

        assert [t.name for t in with_genie_one] == [t.name for t in without]
        assert "query_genie_space_1" in [t.name for t in without]
        assert any(
            r.levelno == logging.DEBUG
            and r.getMessage() == "genie_one is agent-mode only; skipped for the legacy agent"
            for r in caplog.records
        ), [r.getMessage() for r in caplog.records]
