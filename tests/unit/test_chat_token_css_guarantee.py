"""Deck saves re-emit the pinned template's token stylesheet (dsv2 WB-1).

The pinned-template prompt block instructs the model to carry the TOKEN
STYLESHEET into the emitted deck CSS; the live battery proved the model can
ignore it (57 var() references, zero definitions — washout in preview and both
PPTX export paths). Prompt prose is not a guarantee, so the chat save paths
apply a deterministic backstop right before persisting: when the session pins
a template and the deck CSS does not define the template's tokens, the token
stylesheet is re-emitted into the deck CSS. Fresh generations AND edits both
pass through it.

All fixtures synthetic. Mock machinery mirrors tests/unit/test_chat_persistence.py.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.api.services.chat_service import ChatService
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from tests.fixtures.html import load_3_slide_deck
from tests.unit.test_chat_persistence import MockSessionManager

SESSION_ID = "token-css-guarantee-session"

TOKEN_CSS = (
    ":root { --acme-navy: #123456; --acme-lava: #654321; }\n"
    "@font-face { font-family: 'Acme Sans'; src: url('{{ds-asset:9}}'); }"
)

# Deck CSS the "model" returns: brand vars referenced, never defined.
DROPPED_TOKENS_CSS = ".dark { background: var(--acme-navy); color: var(--acme-lava); }"


class PinnedSessionManager(MockSessionManager):
    """Session manager whose sessions pin design system 7 / template 3."""

    def get_session(self, session_id):
        return {
            "session_id": session_id,
            "genie_conversation_id": None,
            "agent_config": {"design_system_id": 7, "template_id": 3},
        }


def _create_mock_service() -> ChatService:
    service = ChatService.__new__(ChatService)
    service._deck_cache = {}
    service._cache_lock = MagicMock()
    service._cache_lock.__enter__ = MagicMock(return_value=None)
    service._cache_lock.__exit__ = MagicMock(return_value=None)
    service._mock_agent = MagicMock()
    service._mock_agent.sessions = {}
    service._build_agent_for_session = MagicMock(
        return_value=(
            service._mock_agent,
            {"session_id": SESSION_ID, "genie_conversation_id": None},
            None,
        )
    )
    service._persist_genie_conversation_ids = MagicMock()
    service._detect_edit_intent = MagicMock(return_value=False)
    service._detect_generation_intent = MagicMock(return_value=True)
    service._detect_add_intent = MagicMock(return_value=False)
    service._parse_slide_references = MagicMock(return_value=([], None))
    service._detect_explicit_replace_intent = MagicMock(return_value=False)
    return service


def _agent_returns(service: ChatService, html: str) -> None:
    service._mock_agent.generate_slides = MagicMock(
        return_value={
            "html": html,
            "messages": [{"role": "assistant", "content": "Here are your slides"}],
            "metadata": {},
            "replacement_info": None,
            "parsed_output": {"html": html, "type": "full_deck"},
        }
    )


def _send(service: ChatService, manager: MockSessionManager, message: str):
    with patch(
        "src.api.services.chat_service.get_session_manager", return_value=manager
    ):
        with patch("src.core.settings_db.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(profile_id=None, profile_name=None)
            return service.send_message(SESSION_ID, message)


def test_fresh_generation_with_dropped_tokens_saves_token_css():
    service = _create_mock_service()
    manager = PinnedSessionManager()
    _agent_returns(service, load_3_slide_deck(css=DROPPED_TOKENS_CSS))

    with patch.object(
        ChatService, "_resolve_pinned_template_token_css", return_value=TOKEN_CSS
    ):
        _send(service, manager, "Create a 3 slide presentation")

    saved = manager.get_last_save()
    assert saved is not None
    saved_css = saved["deck_dict"]["css"]
    assert "--acme-navy: #123456" in saved_css
    assert "@font-face" in saved_css
    # Model-authored CSS still present (backstop prepends, never replaces).
    assert "var(--acme-navy)" in saved_css
    # The knitted html_content representation carries the tokens too.
    assert "--acme-navy: #123456" in saved["html_content"]


def test_edit_path_with_dropped_tokens_saves_token_css():
    """A slide edit must re-assert the guarantee at save time — the persisted
    deck CSS may have lost the tokens on an earlier rewrite."""
    service = _create_mock_service()
    manager = PinnedSessionManager()
    # Existing deck in cache: its css already lost the tokens earlier.
    existing_deck = SlideDeck.from_html_string(load_3_slide_deck(css=DROPPED_TOKENS_CSS))
    service._deck_cache[SESSION_ID] = existing_deck

    replacement_html = '<div class="slide"><h1>Edited Slide</h1></div>'
    replacement_slide = Slide(html=replacement_html, slide_id="slide_0")
    replacement_info = {
        "start_index": 0,
        "original_count": 1,
        "replacement_slides": [replacement_slide],
        "replacement_count": 1,
        "is_add_operation": False,
    }
    service._mock_agent.generate_slides = MagicMock(
        return_value={
            "html": replacement_html,
            "messages": [{"role": "assistant", "content": "Updated slide"}],
            "metadata": {},
            "replacement_info": replacement_info,
            "parsed_output": dict(replacement_info),
        }
    )
    service._detect_generation_intent = MagicMock(return_value=False)
    service._detect_edit_intent = MagicMock(return_value=True)
    service._parse_slide_references = MagicMock(return_value=([0], None))
    service._detect_add_position = MagicMock(return_value=("after", None))
    slide_context = {"indices": [0], "slide_htmls": [existing_deck.slides[0].html]}

    with patch.object(
        ChatService, "_resolve_pinned_template_token_css", return_value=TOKEN_CSS
    ):
        with patch(
            "src.api.services.chat_service.get_session_manager", return_value=manager
        ):
            with patch("src.core.settings_db.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(profile_id=None, profile_name=None)
                service.send_message(
                    SESSION_ID, "Change the title of this slide", slide_context=slide_context
                )

    saved = manager.get_last_save()
    assert saved is not None
    assert "--acme-navy: #123456" in saved["deck_dict"]["css"]
    # The model-authored css (token-less) is still there underneath.
    assert "var(--acme-navy)" in saved["deck_dict"]["css"]


def test_unpinned_sessions_save_deck_css_unchanged():
    service = _create_mock_service()
    manager = MockSessionManager()  # no agent_config -> no pin
    _agent_returns(service, load_3_slide_deck(css=DROPPED_TOKENS_CSS))

    _send(service, manager, "Create a 3 slide presentation")

    saved = manager.get_last_save()
    assert saved is not None
    saved_css = saved["deck_dict"]["css"]
    assert "--acme-navy: #123456" not in saved_css
    assert "var(--acme-navy)" in saved_css


def test_resolution_reads_pin_from_agent_config_and_template_row():
    """_resolve_pinned_template_token_css mirrors agent_factory's lookup:
    session agent_config -> active DesignSystem row -> owned template row."""
    template = SimpleNamespace(
        id=3, name="Acme Corporate", layout_html="<html></html>", token_css=TOKEN_CSS
    )
    design_system = SimpleNamespace(id=7, templates=[template], manifest_json=None)

    db = MagicMock()
    query = MagicMock()
    query.filter_by.return_value.first.return_value = design_system
    db.query.return_value = query

    service = _create_mock_service()
    manager = PinnedSessionManager()
    with patch(
        "src.api.services.chat_service.get_session_manager", return_value=manager
    ):
        with patch("src.core.database.get_db_session") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(return_value=db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            resolved = service._resolve_pinned_template_token_css(SESSION_ID)

    assert resolved == TOKEN_CSS


def test_resolution_returns_none_without_pin():
    service = _create_mock_service()
    manager = MockSessionManager()
    with patch(
        "src.api.services.chat_service.get_session_manager", return_value=manager
    ):
        assert service._resolve_pinned_template_token_css(SESSION_ID) is None
