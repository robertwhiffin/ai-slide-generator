"""Unit tests for {{image:ID}} placeholder substitution."""
import pytest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.utils.image_utils import substitute_image_placeholders


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
