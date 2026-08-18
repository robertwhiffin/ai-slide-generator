"""The chat write path must persist exactly ONE style authority (BLOCKING 3).

Exclusivity between ``slide_style_id`` and ``design_system_id`` was enforced on
the agent-config PUT, but ``chat.py`` validates the client's ``agent_config`` and
then persists the dumped dict DIRECTLY — bypassing that rule. An API or MCP caller
who sent both ids got a stored row carrying both, while generation silently applied
design-system precedence: a row that disagrees with the deck it produces.

The fix routes this write through the SAME chokepoint
(``normalize_style_source_exclusivity``) rather than restating the rule, because a
second copy of the rule is how this class keeps reopening. Semantics are the
established ones: normalize to DESIGN-SYSTEM-WINS, never a 422 — a 422 would wedge
legacy both-set rows on every save.

All fixtures SYNTHETIC (invented ids).
"""

from unittest.mock import MagicMock, patch

from src.api.schemas.requests import ChatRequest

_STYLE_ID = 101
_DS_ID = 202


def _persisted_on_create(agent_config, session_id=None):
    """Drive ``_maybe_create_session`` and return the agent_config it persisted."""
    from src.api.routes.chat import _maybe_create_session

    captured: dict = {}
    manager = MagicMock()

    def _create_session(**kwargs):
        captured.update(kwargs)
        return {"session_id": "new-session-abc"}

    manager.create_session.side_effect = _create_session
    request = ChatRequest(message="hi", session_id=session_id, agent_config=agent_config)
    with patch("src.api.routes.chat.get_current_user", return_value="u1"):
        _maybe_create_session(request, manager)
    return captured.get("agent_config", {})


def _authorities(config: dict) -> list[str]:
    return [
        key
        for key in ("slide_style_id", "design_system_id")
        if config.get(key) is not None
    ]


class TestChatCreatePersistsOneAuthority:
    def test_api_shaped_create_with_both_ids_persists_exactly_one(self):
        """The reviewer's repro: a create supplying BOTH ids."""
        persisted = _persisted_on_create(
            {"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID}
        )

        assert _authorities(persisted) == ["design_system_id"], (
            "chat create persisted both style authorities: "
            f"slide_style_id={persisted.get('slide_style_id')!r} "
            f"design_system_id={persisted.get('design_system_id')!r}"
        )
        # DS-wins (the established contract), not a 422 and not DS dropped.
        assert persisted["design_system_id"] == _DS_ID
        assert persisted["slide_style_id"] is None

    def test_style_only_and_ds_only_creates_are_untouched(self):
        style_only = _persisted_on_create({"slide_style_id": _STYLE_ID})
        assert style_only["slide_style_id"] == _STYLE_ID
        assert style_only.get("design_system_id") is None

        ds_only = _persisted_on_create({"design_system_id": _DS_ID})
        assert ds_only["design_system_id"] == _DS_ID
        assert ds_only.get("slide_style_id") is None

    def test_client_generated_session_id_path_also_normalizes(self):
        """The OTHER create branch: a client-generated session_id that was never
        persisted falls through to create_session with the same config."""
        from src.api.routes.chat import _maybe_create_session
        from src.api.services.session_manager import SessionNotFoundError

        captured: dict = {}
        manager = MagicMock()
        manager.get_session.side_effect = SessionNotFoundError("nope")

        def _create_session(**kwargs):
            captured.update(kwargs)
            return {"session_id": "client-abc"}

        manager.create_session.side_effect = _create_session
        request = ChatRequest(
            message="hi",
            session_id="client-abc",
            agent_config={"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID},
        )
        with patch("src.api.routes.chat.get_current_user", return_value="u1"):
            _maybe_create_session(request, manager)

        assert _authorities(captured.get("agent_config", {})) == ["design_system_id"]


class TestChatSyncPersistsOneAuthority:
    def test_existing_session_sync_with_both_ids_persists_exactly_one(self):
        """The sync branch writes ``session.agent_config`` directly on an EXISTING
        session — the same bypass, a different line."""
        from src.api.routes.chat import _maybe_create_session

        stored = MagicMock()
        stored.agent_config = None
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = stored

        manager = MagicMock()
        manager.get_session.return_value = {"session_id": "existing-1"}

        request = ChatRequest(
            message="hi",
            session_id="existing-1",
            agent_config={"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID},
        )

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=db)
        ctx.__exit__ = MagicMock(return_value=False)
        with patch("src.core.database.get_db_session", return_value=ctx):
            with patch("src.api.routes.chat.get_current_user", return_value="u1"):
                _maybe_create_session(request, manager)

        assert isinstance(stored.agent_config, dict), "sync never persisted a config"
        assert _authorities(stored.agent_config) == ["design_system_id"], (
            f"sync persisted both authorities: {stored.agent_config}"
        )


class TestExclusivityRuleIsNotDuplicated:
    def test_chat_uses_the_shared_chokepoint(self):
        """A SECOND copy of the rule is how this class keeps reopening, so the fix
        must call the shared helper — pinned by patching it and observing the call.
        """
        with patch(
            "src.api.routes.chat.normalize_style_source_exclusivity"
        ) as mock_norm:
            mock_norm.return_value = False
            _persisted_on_create(
                {"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID}
            )
        assert mock_norm.called, (
            "chat.py did not route its write through "
            "normalize_style_source_exclusivity — is the rule duplicated?"
        )
