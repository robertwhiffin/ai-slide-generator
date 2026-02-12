"""Unit tests for {{image:ID}} placeholder substitution."""
import pytest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.api.services.chat_service import ChatService
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.utils.image_utils import substitute_image_placeholders

from tests.fixtures.html import load_3_slide_deck


# --- Fixtures ---

@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables_to_create = [
        t for t in Base.metadata.sorted_tables if t.name != "config_history"
    ]
    for table in tables_to_create:
        table.create(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS config_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                domain VARCHAR(50) NOT NULL,
                action VARCHAR(50) NOT NULL,
                changed_by VARCHAR(255) NOT NULL,
                changes TEXT NOT NULL,
                snapshot TEXT,
                timestamp DATETIME NOT NULL
            )
        """))
        conn.commit()
    yield engine
    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_history"))
        conn.commit()
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


# --- Tests ---

class TestSubstituteImagePlaceholders:
    """Tests for replacing {{image:ID}} with base64 data URIs."""

    def test_substitutes_single_placeholder(self, db_session):
        html = '<img src="{{image:42}}" alt="logo" />'
        with patch("src.utils.image_utils.image_service") as mock_svc:
            mock_svc.get_image_base64.return_value = ("BASE64DATA", "image/png")
            result = substitute_image_placeholders(html, db_session)

        assert result == '<img src="data:image/png;base64,BASE64DATA" alt="logo" />'

    def test_substitutes_multiple_placeholders(self, db_session):
        html = '<img src="{{image:1}}" /><img src="{{image:2}}" />'
        with patch("src.utils.image_utils.image_service") as mock_svc:
            def side_effect(db, image_id):
                if image_id == 1:
                    return ("DATA_1", "image/png")
                return ("DATA_2", "image/jpeg")
            mock_svc.get_image_base64.side_effect = side_effect
            result = substitute_image_placeholders(html, db_session)

        assert "data:image/png;base64,DATA_1" in result
        assert "data:image/jpeg;base64,DATA_2" in result

    def test_preserves_html_without_placeholders(self, db_session):
        html = '<h1>Hello World</h1><img src="data:image/png;base64,existing" />'
        result = substitute_image_placeholders(html, db_session)
        assert result == html

    def test_leaves_unresolved_placeholder_on_missing_image(self, db_session):
        html = '<img src="{{image:999}}" />'
        with patch("src.utils.image_utils.image_service") as mock_svc:
            mock_svc.get_image_base64.side_effect = ValueError("not found")
            result = substitute_image_placeholders(html, db_session)

        # Placeholder should remain (graceful degradation)
        assert "{{image:999}}" in result

    def test_works_in_css_url_context(self, db_session):
        css = "section::after { background-image: url('{{image:42}}'); }"
        with patch("src.utils.image_utils.image_service") as mock_svc:
            mock_svc.get_image_base64.return_value = ("BASE64", "image/png")
            result = substitute_image_placeholders(css, db_session)

        assert "url('data:image/png;base64,BASE64')" in result

    def test_handles_empty_string(self, db_session):
        assert substitute_image_placeholders("", db_session) == ""

    def test_mixed_resolved_and_unresolved(self, db_session):
        html = '<img src="{{image:1}}" /><img src="{{image:999}}" />'
        with patch("src.utils.image_utils.image_service") as mock_svc:
            def side_effect(db, image_id):
                if image_id == 1:
                    return ("OK_DATA", "image/png")
                raise ValueError("not found")
            mock_svc.get_image_base64.side_effect = side_effect
            result = substitute_image_placeholders(html, db_session)

        assert "data:image/png;base64,OK_DATA" in result
        assert "{{image:999}}" in result


class TestSlideContextBase64Stripping:
    """Regression: frontend sends base64 HTML in slide_context; agent must receive placeholders."""

    def _create_mock_service(self) -> ChatService:
        service = ChatService.__new__(ChatService)
        service.agent = MagicMock()
        service._deck_cache = {}
        service._cache_lock = MagicMock()
        service._cache_lock.__enter__ = MagicMock(return_value=None)
        service._cache_lock.__exit__ = MagicMock(return_value=None)
        return service

    def test_agent_receives_placeholders_not_base64(self):
        """slide_context passed to agent.generate_slides must use {{image:ID}} placeholders,
        even when the frontend sends base64-substituted HTML."""
        service = self._create_mock_service()
        session_id = "img-ctx-test"

        # Build a deck whose slide[0] uses an image placeholder (backend canonical form)
        placeholder_html = '<div class="slide"><img src="{{image:42}}" /></div>'
        deck = SlideDeck.from_html_string(load_3_slide_deck())
        deck.slides[0] = Slide(html=placeholder_html, slide_id="slide_0")
        service._deck_cache[session_id] = deck

        # Frontend would have received base64-substituted HTML for rendering
        base64_html = '<div class="slide"><img src="data:image/png;base64,AAAA..." /></div>'

        # Mock agent to capture what slide_context it receives
        captured = {}
        def fake_generate(*args, **kwargs):
            captured["slide_context"] = kwargs.get("slide_context")
            return {
                "html": '<div class="slide"><h1>Edited</h1></div>',
                "messages": [{"role": "assistant", "content": "Done"}],
                "metadata": {},
                "replacement_info": None,
                "parsed_output": {"html": '<div class="slide"><h1>Edited</h1></div>', "type": "full_deck"},
            }
        service.agent.generate_slides = MagicMock(side_effect=fake_generate)

        # Stub helpers used by send_message
        service._ensure_agent_session = MagicMock(return_value=None)
        service._detect_edit_intent = MagicMock(return_value=True)
        service._detect_generation_intent = MagicMock(return_value=False)
        service._detect_add_intent = MagicMock(return_value=False)
        service._parse_slide_references = MagicMock(return_value=([], None))
        service._detect_explicit_replace_intent = MagicMock(return_value=False)

        mock_session_manager = MagicMock()
        mock_session_manager.get_session.return_value = {
            "id": session_id, "profile_id": None, "profile_name": None,
            "genie_conversation_id": None,
        }
        mock_session_manager.get_slide_deck.return_value = None

        slide_context = {
            "indices": [0],
            "slide_htmls": [base64_html],  # frontend sends base64
        }

        with patch("src.api.services.chat_service.get_session_manager", return_value=mock_session_manager):
            with patch("src.core.settings_db.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(profile_id=None, profile_name=None)
                # The RC3 guard raises ValueError when replacement_info is None
                # with slide_context present — we only care about the captured context
                try:
                    service.send_message(session_id, "Edit this slide", slide_context=slide_context)
                except ValueError:
                    pass

        # The agent must have received the placeholder form, NOT base64
        agent_ctx = captured["slide_context"]
        assert agent_ctx is not None
        assert "{{image:42}}" in agent_ctx["slide_htmls"][0]
        assert "base64" not in agent_ctx["slide_htmls"][0]
