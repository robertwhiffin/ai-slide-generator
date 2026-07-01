"""Unit tests for SessionManager.duplicate_session and agent config sanitization."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — register all models with Base
from src.api.schemas.agent_config import sanitize_agent_config_for_persist
from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.core.database import Base
from src.database.models.deck_contributor import DeckContributor
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import (
    SessionMessage,
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)


@pytest.fixture
def db():
    """In-memory SQLite session for unit tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def session_manager(monkeypatch, db):
    """SessionManager with get_db_session patched to the test database."""

    @contextmanager
    def _fake_db_session():
        yield db

    monkeypatch.setattr(
        "src.api.services.session_manager.get_db_session",
        _fake_db_session,
    )
    return SessionManager()


def _add_deck(
    db,
    session: UserSession,
    *,
    slide_count: int = 2,
    html: str = "<div>deck</div>",
    deck_json: str = '{"slides":[{"html":"<div>1</div>"},{"html":"<div>2</div>"}]}',
) -> SessionSlideDeck:
    deck = SessionSlideDeck(
        session_id=session.id,
        title=session.title,
        html_content=html,
        scripts_content="// chart",
        slide_count=slide_count,
        deck_json=deck_json,
        verification_map='{"abc": {"score": 90}}',
        version=5,
        modified_by=session.created_by,
    )
    db.add(deck)
    db.commit()
    db.refresh(session)
    return deck


def _make_root_session(db, *, session_id: str, created_by: str, title: str = "Q4 Review", **kwargs):
    session = UserSession(
        session_id=session_id,
        created_by=created_by,
        title=title,
        **kwargs,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


class TestSanitizeAgentConfigForPersist:
    def test_strips_genie_conversation_id(self):
        raw = {
            "tools": [
                {
                    "type": "genie",
                    "space_id": "space-1",
                    "space_name": "Sales",
                    "conversation_id": "conv-old",
                }
            ],
            "slide_style_id": 3,
        }
        result = sanitize_agent_config_for_persist(raw)
        assert result["tools"][0]["conversation_id"] is None
        assert result["slide_style_id"] == 3

    def test_none_config_returns_none(self):
        assert sanitize_agent_config_for_persist(None) is None


class TestDuplicateSessionValidScenarios:
    def test_duplicate_root_session_creates_owned_copy(self, db, session_manager):
        owner = _make_root_session(
            db,
            session_id="src-root",
            created_by="owner@test.com",
            title="Board Deck",
            agent_config={
                "tools": [
                    {
                        "type": "genie",
                        "space_id": "s1",
                        "space_name": "Genie",
                        "conversation_id": "keep-out",
                    }
                ]
            },
            global_permission=PermissionLevel.CAN_VIEW.value,
            genie_conversation_id="genie-123",
            experiment_id="exp-1",
            google_slides_presentation_id="pres-1",
            google_slides_url="https://slides.example/1",
        )
        _add_deck(db, owner)
        db.add(
            DeckContributor(
                user_session_id=owner.id,
                identity_type="USER",
                identity_id="viewer-uid",
                identity_name="viewer@test.com",
                permission_level=PermissionLevel.CAN_VIEW.value,
                created_by="owner@test.com",
            )
        )
        db.add(
            SessionMessage(
                session_id=owner.id,
                role="user",
                content="secret chat",
            )
        )
        db.add(
            SlideDeckVersion(
                session_id=owner.id,
                version_number=1,
                description="v1",
                deck_json='{"slides":[]}',
            )
        )
        db.commit()

        result = session_manager.duplicate_session(
            "src-root",
            created_by="copier@test.com",
            title="My Fork",
        )

        assert result["title"] == "My Fork"
        assert result["slide_count"] == 2
        assert result["source_session_id"] == "src-root"
        assert result["created_by"] == "copier@test.com"

        copy = db.query(UserSession).filter(UserSession.session_id == result["session_id"]).one()
        assert copy.created_by == "copier@test.com"
        assert copy.parent_session_id is None
        assert copy.global_permission is None
        assert copy.genie_conversation_id is None
        assert copy.experiment_id is None
        assert copy.google_slides_presentation_id is None
        assert copy.google_slides_url is None
        assert copy.agent_config["tools"][0]["conversation_id"] is None

        copy_deck = copy.slide_deck
        assert copy_deck.slide_count == 2
        assert copy_deck.html_content == "<div>deck</div>"
        assert copy_deck.deck_json == '{"slides":[{"html":"<div>1</div>"},{"html":"<div>2</div>"}]}'
        assert copy_deck.verification_map == '{"abc": {"score": 90}}'
        assert copy_deck.version == 1

        # Source unchanged; related rows not duplicated onto copy
        assert db.query(UserSession).filter(UserSession.session_id == "src-root").count() == 1
        assert db.query(SessionMessage).filter(SessionMessage.session_id == copy.id).count() == 0
        assert db.query(DeckContributor).filter(DeckContributor.user_session_id == copy.id).count() == 0
        assert db.query(SlideDeckVersion).filter(SlideDeckVersion.session_id == copy.id).count() == 0

    def test_duplicate_from_contributor_session_uses_parent_deck(self, db, session_manager):
        owner = _make_root_session(db, session_id="parent-1", created_by="owner@test.com", title="Shared")
        _add_deck(db, owner, deck_json='{"slides":[{"html":"<div>parent</div>"}]}', slide_count=1)

        contributor = UserSession(
            session_id="contrib-1",
            created_by="contrib@test.com",
            title="Shared",
            parent_session_id=owner.id,
        )
        db.add(contributor)
        db.commit()

        result = session_manager.duplicate_session(
            "contrib-1",
            created_by="contrib@test.com",
        )

        assert result["source_session_id"] == "parent-1"
        assert result["title"] == "Copy of Shared"

        copy = db.query(UserSession).filter(UserSession.session_id == result["session_id"]).one()
        assert copy.parent_session_id is None
        assert copy.slide_deck.deck_json == '{"slides":[{"html":"<div>parent</div>"}]}'

    def test_default_title_when_not_provided(self, db, session_manager):
        owner = _make_root_session(db, session_id="src-2", created_by="owner@test.com", title="Annual")
        _add_deck(db, owner)

        result = session_manager.duplicate_session("src-2", created_by="owner@test.com")

        assert result["title"] == "Copy of Annual"


class TestDuplicateSessionErrorHandling:
    def test_missing_session_raises_not_found(self, db, session_manager):
        with pytest.raises(SessionNotFoundError):
            session_manager.duplicate_session("missing", created_by="user@test.com")

    def test_session_without_deck_raises_value_error(self, db, session_manager):
        _make_root_session(db, session_id="empty", created_by="owner@test.com")
        with pytest.raises(ValueError, match="no slide deck"):
            session_manager.duplicate_session("empty", created_by="owner@test.com")


class TestListSessionsIncludesDuplicatedDeck:
    def test_deck_only_session_appears_in_list(self, db, session_manager):
        owner = _make_root_session(db, session_id="src-list", created_by="owner@test.com", title="Original")
        _add_deck(db, owner)

        result = session_manager.duplicate_session("src-list", created_by="owner@test.com")

        listed = session_manager.list_sessions(created_by="owner@test.com")
        session_ids = {s["session_id"] for s in listed}

        assert result["session_id"] in session_ids
        copy_row = next(s for s in listed if s["session_id"] == result["session_id"])
        assert copy_row["has_slide_deck"] is True
        assert copy_row["slide_count"] == 2
        assert copy_row["message_count"] == 0
