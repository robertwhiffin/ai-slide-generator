"""F-CR-27: the assistant/slide ``{{image:ID}}`` resolution path must enforce
the same ephemeral-image privacy guard as ``GET /api/images/{token}``.

Chat-pasted ("ephemeral") images are private to their uploader; library images
stay open-read. A token for another user's ephemeral image must not resolve via
``get_image_base64`` / ``substitute_image_placeholders`` / the chat response
boundary.
"""
import base64
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.services.chat_service import ChatService
from src.core.database import Base
from src.core.user_context import set_current_user
from src.database.models.image import ImageAsset
from src.services import image_service
from src.utils.image_utils import (
    substitute_deck_dict_images,
    substitute_image_placeholders,
)

ALICE = "alice@test.com"
BOB = "bob@test.com"


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _make_image(db_session, **overrides) -> ImageAsset:
    defaults = dict(
        filename="f.png",
        original_filename="o.png",
        mime_type="image/png",
        size_bytes=5,
        image_data=b"bytes",
        thumbnail_base64=None,
        tags=[],
        description="",
        category="content",
        uploaded_by=ALICE,
        is_active=True,
        created_by=ALICE,
        updated_by=ALICE,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    img = ImageAsset(**defaults)
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img


def _data_uri(img: ImageAsset) -> str:
    return f"data:{img.mime_type};base64,{base64.b64encode(img.image_data).decode()}"


class TestGetImageBase64Privacy:
    def test_cross_user_ephemeral_denied(self, db_session):
        img = _make_image(db_session, category="ephemeral", uploaded_by=ALICE)
        with pytest.raises(ValueError, match="not found"):
            image_service.get_image_base64(db_session, img.token, requesting_user=BOB)

    def test_ephemeral_without_identity_fails_closed(self, db_session):
        img = _make_image(db_session, category="ephemeral", uploaded_by=ALICE)
        with pytest.raises(ValueError, match="not found"):
            image_service.get_image_base64(db_session, img.token, requesting_user=None)

    def test_owner_ephemeral_resolves(self, db_session):
        img = _make_image(db_session, category="ephemeral", uploaded_by=ALICE)
        b64, mime = image_service.get_image_base64(
            db_session, img.token, requesting_user=ALICE
        )
        assert base64.b64decode(b64) == b"bytes"
        assert mime == "image/png"

    @pytest.mark.parametrize("requesting_user", [BOB, None])
    def test_library_image_resolves_for_anyone(self, db_session, requesting_user):
        img = _make_image(db_session, category="content", uploaded_by=ALICE)
        b64, _ = image_service.get_image_base64(
            db_session, img.token, requesting_user=requesting_user
        )
        assert base64.b64decode(b64) == b"bytes"


class TestPlaceholderResolutionPrivacy:
    def test_cross_user_ephemeral_placeholder_left_unresolved(self, db_session):
        img = _make_image(db_session, category="ephemeral", uploaded_by=ALICE)
        html = f'<img src="{{{{image:{img.token}}}}}" />'
        out = substitute_image_placeholders(html, db_session, requesting_user=BOB)
        assert out == html
        assert "base64" not in out

    def test_owner_ephemeral_placeholder_resolves(self, db_session):
        img = _make_image(db_session, category="ephemeral", uploaded_by=ALICE)
        html = f'<img src="{{{{image:{img.token}}}}}" />'
        out = substitute_image_placeholders(html, db_session, requesting_user=ALICE)
        assert out == f'<img src="{_data_uri(img)}" />'

    def test_library_placeholder_resolves_cross_user(self, db_session):
        img = _make_image(db_session, category="content", uploaded_by=ALICE)
        html = f'<img src="{{{{image:{img.token}}}}}" />'
        out = substitute_image_placeholders(html, db_session, requesting_user=BOB)
        assert out == f'<img src="{_data_uri(img)}" />'

    def test_deck_dict_scopes_every_field(self, db_session):
        mine = _make_image(db_session, category="ephemeral", uploaded_by=BOB)
        theirs = _make_image(db_session, category="ephemeral", uploaded_by=ALICE)
        shared = _make_image(db_session, category="background", uploaded_by=ALICE)
        deck = {
            "slides": [{"html": f"<img src='{{{{image:{theirs.token}}}}}'>"}],
            "html_content": f"<img src='{{{{image:{mine.token}}}}}'>",
            "css": f"body{{background:url('{{{{image:{shared.token}}}}}')}}",
        }
        out = substitute_deck_dict_images(deck, db_session, requesting_user=BOB)
        assert f"{{{{image:{theirs.token}}}}}" in out["slides"][0]["html"]
        assert _data_uri(mine) in out["html_content"]
        assert _data_uri(shared) in out["css"]


class TestRequestContextIdentity:
    """Without an explicit ``requesting_user`` the resolver uses the acting
    request's identity (production path: middleware / MCP auth ContextVar)."""

    @pytest.fixture
    def prod_env(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        yield
        set_current_user(None)

    def test_resolve_requesting_user_reads_request_context(self, prod_env):
        set_current_user(BOB)
        assert image_service.resolve_requesting_user() == BOB
        set_current_user(None)
        assert image_service.resolve_requesting_user() is None

    def test_resolve_requesting_user_dev_fallback_matches_upload(self, monkeypatch):
        # routes.images._get_current_user stamps "system" in dev/test uploads.
        monkeypatch.setenv("ENVIRONMENT", "test")
        assert image_service.resolve_requesting_user() == "system"

    def test_chat_response_boundary_denies_cross_user_ephemeral(
        self, db_session, prod_env
    ):
        theirs = _make_image(db_session, category="ephemeral", uploaded_by=ALICE)
        mine = _make_image(db_session, category="ephemeral", uploaded_by=BOB)
        deck = {
            "slides": [
                {"html": f"<img src='{{{{image:{theirs.token}}}}}'>"},
                {"html": f"<img src='{{{{image:{mine.token}}}}}'>"},
            ]
        }
        raw_html = f"<img src='{{{{image:{theirs.token}}}}}'>"

        @contextmanager
        def _fake_db():
            yield db_session

        set_current_user(BOB)
        with patch("src.core.database.get_db_session", _fake_db):
            out_deck, out_html = ChatService()._substitute_images_for_response(
                deck, raw_html, session_id="sess-1"
            )

        assert f"{{{{image:{theirs.token}}}}}" in out_deck["slides"][0]["html"]
        assert _data_uri(mine) in out_deck["slides"][1]["html"]
        assert out_html == raw_html
