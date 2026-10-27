"""Unit tests for SessionManager.duplicate_session and agent config sanitization."""

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — register all models with Base
from src.api.schemas.agent_config import sanitize_agent_config_for_persist
from src.api.services.session_manager import (
    DeckModeLockedError,
    SessionAccessDeniedError,
    SessionManager,
    SessionNotFoundError,
)
from src.core.database import Base
from src.database.models.graph_configuration import GraphRelease
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
    now = datetime.now(timezone.utc)
    session.add(
        GraphRelease(
            id=200,
            version_number=2,
            release_note="active duplicate fixture release",
            published_by="duplicate-fixture@example.com",
            published_at=now,
            effective_from=now,
        )
    )
    session.commit()
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
    deck_spec_json: Optional[str] = None,
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
        deck_spec_json=deck_spec_json,
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

    def test_default_title_truncated_when_source_title_too_long(self, db, session_manager):
        long_title = "A" * 255
        owner = _make_root_session(
            db, session_id="src-long", created_by="owner@test.com", title=long_title
        )
        _add_deck(db, owner)

        result = session_manager.duplicate_session("src-long", created_by="owner@test.com")

        assert result["title"].startswith("Copy of ")
        assert len(result["title"]) == 255
        copy = db.query(UserSession).filter(UserSession.session_id == result["session_id"]).one()
        assert copy.title == result["title"]
        assert copy.slide_deck.title == result["title"]


    def test_duplicate_from_save_point_uses_version_snapshot(self, db, session_manager):
        owner = _make_root_session(
            db, session_id="src-ver", created_by="owner@test.com", title="Versioned"
        )
        _add_deck(
            db,
            owner,
            slide_count=3,
            deck_json='{"slides":[{"html":"<div>live</div>"},{"html":"<div>2</div>"},{"html":"<div>3</div>"}]}',
        )
        db.add(
            SlideDeckVersion(
                session_id=owner.id,
                version_number=2,
                description="Older two-slide version",
                deck_json='{"slides":[{"html":"<div>old-1</div>"},{"html":"<div>old-2</div>"}],"slide_count":2}',
                verification_map_json='{"old": {"score": 1}}',
            )
        )
        db.commit()

        result = session_manager.duplicate_session(
            "src-ver",
            created_by="copier@test.com",
            version_number=2,
        )

        assert result["slide_count"] == 2
        assert result["source_version_number"] == 2

        copy = db.query(UserSession).filter(UserSession.session_id == result["session_id"]).one()
        assert "old-1" in copy.slide_deck.deck_json
        assert "live" not in copy.slide_deck.deck_json

    def test_duplicate_from_save_point_knits_html_with_head_meta(self, db, session_manager):
        owner = _make_root_session(
            db, session_id="src-head", created_by="owner@test.com", title="Head Meta"
        )
        _add_deck(db, owner, slide_count=1)
        version_deck_json = json.dumps(
            {
                "slides": [{"html": "<div>slide</div>", "slide_id": "slide_0"}],
                "slide_count": 1,
                "css": "body { color: red; }",
                "external_scripts": ["https://cdn.example.com/lib.js"],
                "head_meta": {"charset": "utf-8", "viewport": "width=device-width"},
            }
        )
        db.add(
            SlideDeckVersion(
                session_id=owner.id,
                version_number=1,
                description="With head meta",
                deck_json=version_deck_json,
            )
        )
        db.commit()

        result = session_manager.duplicate_session(
            "src-head",
            created_by="copier@test.com",
            version_number=1,
        )

        copy = db.query(UserSession).filter(UserSession.session_id == result["session_id"]).one()
        assert '<meta charset="utf-8">' in copy.slide_deck.html_content
        assert 'name="viewport"' in copy.slide_deck.html_content
        assert copy.slide_deck.deck_json == version_deck_json


# ---------------------------------------------------------------------------
# Deck Mode (spec rev 2 §5.3): a duplicate copies the deck OWNER's deck_mode.
#
# The copy is locked to that mode from creation and is pinned unless the mode
# is legacy; an unlocked (NULL) source gives an unlocked copy, pinned like any
# new deck.  In every mode the copy carries no chat history (the old hidden
# first-row carry is gone), so its first message really is its first:
# message_count 0, which is what gives it an auto-title.
#
# Every source has a chat history, and every pinned source is pinned to a
# SUPERSEDED release, so a copy must take a fresh pin from the active row,
# never the source's.  The old opt-out phrase is a literal here (Task 6 deletes
# the constant) and is ordinary text: no row's content decides a copy's mode.
# ---------------------------------------------------------------------------

_OLD_LEGACY_PHRASE = "USE LEGACY MODE"
_ACTIVE_RELEASE_ID = 200  # the ``db`` fixture's release
_SUPERSEDED_RELEASE_ID = 199

_FIRST_MESSAGES = {
    "plain": "Build me a deck about puffins",
    "old-phrase": f"{_OLD_LEGACY_PHRASE} and build me a deck about puffins",
}


def _seed_superseded_release(db) -> None:
    published = datetime.now(timezone.utc) - timedelta(days=3)
    db.add(
        GraphRelease(
            id=_SUPERSEDED_RELEASE_ID,
            version_number=1,
            release_note="superseded duplicate fixture release",
            published_by="duplicate-fixture@example.com",
            published_at=published,
            effective_from=published,
            effective_to=published + timedelta(days=1),
        )
    )
    db.commit()


def _seed_history(db, session: UserSession, first_message: Optional[str]) -> None:
    """A three-row transcript opening with *first_message*; None seeds no rows."""
    if first_message is None:
        return
    start = datetime.utcnow() - timedelta(hours=1)
    for offset, role, content, message_type in [
        (0, "user", first_message, "user_input"),
        (5, "assistant", "Here is your deck.", "llm_response"),
        (10, "user", "make slide 2 blue", "user_input"),
    ]:
        db.add(
            SessionMessage(
                session_id=session.id,
                role=role,
                content=content,
                message_type=message_type,
                created_at=start + timedelta(seconds=offset),
            )
        )
    db.commit()


def _moded_source(db, *, session_id: str, deck_mode, first_message) -> UserSession:
    """A deck-owning root stored as *deck_mode*, with a chat history.

    Pinned to the superseded release unless legacy (a legacy deck holds no pin).
    """
    _seed_superseded_release(db)
    owner = _make_root_session(
        db,
        session_id=session_id,
        created_by="owner@test.com",
        title="Moded Deck",
        deck_mode=deck_mode,
        graph_release_id=None if deck_mode == "legacy" else _SUPERSEDED_RELEASE_ID,
    )
    _add_deck(db, owner)
    _seed_history(db, owner, first_message)
    return owner


def _copy_state(db, session_manager, copy_id: str) -> dict:
    """What a reader sees of the copy: stored and API mode, pin, chat history."""
    row = db.query(UserSession).filter(UserSession.session_id == copy_id).one()
    db.refresh(row)
    api = session_manager.get_session(copy_id)
    return {
        "deck_mode": row.deck_mode,
        "api_deck_mode": api["deck_mode"],
        "pin": row.graph_release_id,
        "message_rows": db.query(SessionMessage)
        .filter(SessionMessage.session_id == row.id)
        .count(),
        "message_count": api["message_count"],
    }


class TestDuplicateCopiesTheOwnersMode:
    @pytest.mark.parametrize("first_message", list(_FIRST_MESSAGES))
    def test_duplicate_of_an_agent_deck_is_agent_and_pinned(
        self, db, session_manager, first_message
    ):
        """The copy is an agent deck, locked from creation, with a fresh pin.

        The ``old-phrase`` case is an agent deck whose first message happens to
        contain the old opt-out text: the column decides, not the text.
        """
        _moded_source(
            db,
            session_id="src-agent",
            deck_mode="agent",
            first_message=_FIRST_MESSAGES[first_message],
        )

        copy_id = session_manager.duplicate_session(
            "src-agent", created_by="copier@test.com"
        )["session_id"]

        assert _copy_state(db, session_manager, copy_id) == {
            "deck_mode": "agent",
            "api_deck_mode": "agent",
            "pin": _ACTIVE_RELEASE_ID,
            "message_rows": 0,
            "message_count": 0,
        }
        # Locked from creation: the copy's first message cannot choose legacy.
        with pytest.raises(DeckModeLockedError) as locked:
            session_manager.add_user_message(
                copy_id,
                "make it legacy",
                message_type="user_input",
                requested_deck_mode="legacy",
            )
        assert locked.value.deck_mode == "agent"
        # The source keeps its own mode and its own (older) pin.
        source = db.query(UserSession).filter(UserSession.session_id == "src-agent").one()
        assert (source.deck_mode, source.graph_release_id) == (
            "agent",
            _SUPERSEDED_RELEASE_ID,
        )

    @pytest.mark.parametrize("first_message", list(_FIRST_MESSAGES))
    def test_duplicate_of_a_legacy_deck_is_legacy_unpinned_and_carries_no_message(
        self, db, session_manager, first_message
    ):
        """The column carries the mode now, so no hidden row is copied.

        ``plain`` is a deck made legacy by the Mode selector; ``old-phrase`` is a
        legacy deck from before it (its first row still holds the opt-out).
        Either way the copy has no message, so its first message is its first
        and it gets an auto-title.  A legacy copy never takes the release lock.
        """
        _moded_source(
            db,
            session_id="src-legacy",
            deck_mode="legacy",
            first_message=_FIRST_MESSAGES[first_message],
        )

        with patch(
            "src.api.services.session_manager.lock_active_graph_release",
            side_effect=AssertionError("a legacy duplicate must not lock a release"),
        ):
            copy_id = session_manager.duplicate_session(
                "src-legacy", created_by="copier@test.com"
            )["session_id"]

        assert _copy_state(db, session_manager, copy_id) == {
            "deck_mode": "legacy",
            "api_deck_mode": "legacy",
            "pin": None,
            "message_rows": 0,
            "message_count": 0,
        }
        # Locked from creation: the copy's first message cannot choose agent.
        with pytest.raises(DeckModeLockedError) as locked:
            session_manager.add_user_message(
                copy_id,
                "make it agent",
                message_type="user_input",
                requested_deck_mode="agent",
            )
        assert locked.value.deck_mode == "legacy"

    @pytest.mark.parametrize(
        "first_message",
        [None, *_FIRST_MESSAGES],
        ids=["no-history", *_FIRST_MESSAGES],
    )
    def test_duplicate_of_an_unlocked_deck_is_unlocked_and_pinned(
        self, db, session_manager, first_message
    ):
        """An unlocked source gives an unlocked copy, pinned like any new deck.

        Its own first message still chooses its mode.  The ``old-phrase`` case
        is the one the old carry got wrong: the opt-out text in the source's
        first row no longer makes the copy legacy.
        """
        _moded_source(
            db,
            session_id="src-unlocked",
            deck_mode=None,
            first_message=_FIRST_MESSAGES.get(first_message),
        )

        copy_id = session_manager.duplicate_session(
            "src-unlocked", created_by="copier@test.com"
        )["session_id"]

        assert _copy_state(db, session_manager, copy_id) == {
            "deck_mode": None,
            "api_deck_mode": None,
            "pin": _ACTIVE_RELEASE_ID,
            "message_rows": 0,
            "message_count": 0,
        }
        # Still unlocked: its first message may choose legacy.
        first = session_manager.add_user_message(
            copy_id,
            "first ask on the copy",
            message_type="user_input",
            requested_deck_mode="legacy",
        )
        assert (first["deck_mode"], first["locked_now"]) == ("legacy", True)

    @pytest.mark.parametrize("owner_mode", ["agent", "legacy"])
    def test_duplicate_of_a_contributor_view_copies_the_owners_mode(
        self, db, session_manager, owner_mode
    ):
        """From a contributor's session, the copy takes the deck OWNER's mode.

        The contributor's own row holds no mode (the lock writes the owner's).
        """
        owner = _moded_source(
            db,
            session_id="parent-moded",
            deck_mode=owner_mode,
            first_message=_FIRST_MESSAGES["plain"],
        )
        contributor = UserSession(
            session_id="contrib-moded",
            created_by="contrib@test.com",
            title="Moded Deck",
            parent_session_id=owner.id,
            graph_release_id=None if owner_mode == "legacy" else _SUPERSEDED_RELEASE_ID,
        )
        db.add(contributor)
        db.commit()
        _seed_history(db, contributor, "contributor's own ask")
        assert contributor.deck_mode is None, "precondition: only the owner holds a mode"

        result = session_manager.duplicate_session(
            "contrib-moded", created_by="contrib@test.com"
        )

        assert result["source_session_id"] == "parent-moded"
        assert _copy_state(db, session_manager, result["session_id"]) == {
            "deck_mode": owner_mode,
            "api_deck_mode": owner_mode,
            "pin": None if owner_mode == "legacy" else _ACTIVE_RELEASE_ID,
            "message_rows": 0,
            "message_count": 0,
        }

    def test_the_duplicate_log_records_the_deck_mode(self, db, session_manager, caplog):
        """The log's ``carried_engine_mode_marker`` key becomes ``deck_mode``."""
        _moded_source(
            db,
            session_id="src-logged",
            deck_mode="legacy",
            first_message=_FIRST_MESSAGES["plain"],
        )

        with caplog.at_level(logging.INFO, logger="src.api.services.session_manager"):
            session_manager.duplicate_session("src-logged", created_by="copier@test.com")

        [record] = [r for r in caplog.records if r.getMessage() == "Duplicated session"]
        assert record.deck_mode == "legacy"
        assert not hasattr(record, "carried_engine_mode_marker")


class TestDuplicateSessionErrorHandling:
    def test_missing_session_raises_not_found(self, db, session_manager):
        with pytest.raises(SessionNotFoundError):
            session_manager.duplicate_session("missing", created_by="user@test.com")

    def test_session_without_deck_raises_value_error(self, db, session_manager):
        _make_root_session(db, session_id="empty", created_by="owner@test.com")
        with pytest.raises(ValueError, match="no slide deck"):
            session_manager.duplicate_session("empty", created_by="owner@test.com")

    def test_missing_version_raises_value_error(self, db, session_manager):
        owner = _make_root_session(db, session_id="src-missing-ver", created_by="owner@test.com")
        _add_deck(db, owner)
        with pytest.raises(ValueError, match="Version 99 not found"):
            session_manager.duplicate_session(
                "src-missing-ver",
                created_by="owner@test.com",
                version_number=99,
            )


class TestDuplicateSessionPermission:
    def test_requires_deck_permission_when_requested(self, db, session_manager):
        owner = _make_root_session(
            db, session_id="src-private", created_by="owner@test.com", title="Private"
        )
        _add_deck(db, owner)

        with pytest.raises(SessionAccessDeniedError):
            session_manager.duplicate_session(
                "src-private",
                created_by="stranger@test.com",
                min_permission=PermissionLevel.CAN_VIEW,
            )

    def test_can_view_contributor_may_duplicate(self, db, session_manager):
        owner = _make_root_session(
            db, session_id="src-shared", created_by="owner@test.com", title="Shared"
        )
        _add_deck(db, owner)
        db.add(
            DeckContributor(
                user_session_id=owner.id,
                identity_type="USER",
                identity_id="viewer-uid",
                identity_name="viewer@test.com",
                permission_level=PermissionLevel.CAN_VIEW.value,
            )
        )
        db.commit()

        from src.core.permission_context import PermissionContext

        ctx = PermissionContext(user_id="viewer-uid", user_name="viewer@test.com")
        with patch("src.core.permission_context.get_permission_context", return_value=ctx):
            result = session_manager.duplicate_session(
                "src-shared",
                created_by="viewer@test.com",
                min_permission=PermissionLevel.CAN_VIEW,
            )

        assert result["created_by"] == "viewer@test.com"

    def test_workspace_global_can_view_may_duplicate(self, db, session_manager):
        owner = _make_root_session(
            db,
            session_id="src-workspace",
            created_by="owner@test.com",
            title="Workspace Shared",
            global_permission=PermissionLevel.CAN_VIEW.value,
        )
        _add_deck(db, owner)

        from src.core.permission_context import PermissionContext

        ctx = PermissionContext(user_id="stranger-uid", user_name="stranger@test.com")
        with patch("src.core.permission_context.get_permission_context", return_value=ctx):
            result = session_manager.duplicate_session(
                "src-workspace",
                created_by="stranger@test.com",
                min_permission=PermissionLevel.CAN_VIEW,
            )

        assert result["created_by"] == "stranger@test.com"

    def test_workspace_global_revoked_denies_duplicate(self, db, session_manager):
        owner = _make_root_session(
            db,
            session_id="src-revoked",
            created_by="owner@test.com",
            title="Was Shared",
            global_permission=PermissionLevel.CAN_VIEW.value,
        )
        _add_deck(db, owner)
        owner.global_permission = None
        db.commit()

        from src.core.permission_context import PermissionContext

        ctx = PermissionContext(user_id="stranger-uid", user_name="stranger@test.com")
        with patch("src.core.permission_context.get_permission_context", return_value=ctx):
            with pytest.raises(SessionAccessDeniedError):
                session_manager.duplicate_session(
                    "src-revoked",
                    created_by="stranger@test.com",
                    min_permission=PermissionLevel.CAN_VIEW,
                )

    def test_contributor_session_id_with_min_permission(self, db, session_manager):
        owner = _make_root_session(
            db,
            session_id="parent-perm",
            created_by="owner@test.com",
            title="Shared Deck",
            global_permission=PermissionLevel.CAN_VIEW.value,
        )
        _add_deck(db, owner)
        contributor = UserSession(
            session_id="contrib-perm",
            created_by="viewer@test.com",
            title="Shared Deck",
            parent_session_id=owner.id,
        )
        db.add(contributor)
        db.commit()

        from src.core.permission_context import PermissionContext

        ctx = PermissionContext(user_id="viewer-uid", user_name="viewer@test.com")
        with patch("src.core.permission_context.get_permission_context", return_value=ctx):
            result = session_manager.duplicate_session(
                "contrib-perm",
                created_by="viewer@test.com",
                min_permission=PermissionLevel.CAN_VIEW,
            )

        assert result["source_session_id"] == "parent-perm"
        assert result["created_by"] == "viewer@test.com"


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


class TestListDeckOnlySessions:
    def test_deck_only_returns_recent_decks_not_chat_sessions(self, db, session_manager):
        deck_old = _make_root_session(
            db, session_id="deck-old", created_by="owner@test.com", title="Old Deck"
        )
        _add_deck(db, deck_old)

        chat_new = _make_root_session(
            db, session_id="chat-new", created_by="owner@test.com", title="Recent Chat"
        )
        db.add(
            SessionMessage(
                session_id=chat_new.id,
                role="user",
                content="hello",
            )
        )

        deck_new = _make_root_session(
            db, session_id="deck-new", created_by="owner@test.com", title="New Deck"
        )
        _add_deck(db, deck_new)

        # Explicit last_activity ordering: deck-new > chat-new > deck-old
        now = datetime.utcnow()
        chat_new.last_activity = now
        deck_new.last_activity = now + timedelta(minutes=2)
        deck_old.last_activity = now - timedelta(minutes=2)
        db.commit()

        listed = session_manager.list_sessions(
            created_by="owner@test.com",
            limit=10,
            deck_only=True,
        )

        assert [s["session_id"] for s in listed] == ["deck-new", "deck-old"]
        assert all(s["has_slide_deck"] for s in listed)
