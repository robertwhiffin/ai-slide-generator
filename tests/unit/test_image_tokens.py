"""Opaque-token identifier / enumeration-defense tests for images (SDR-4437 F-TM-7).

Image assets keep an internal autoincrement int PK, but the only externally
visible identifier is an unguessable ``token``. Enumerating sequential ints must
not resolve, and chat-pasted ("ephemeral") images are additionally owner-scoped.
"""
import base64
import io
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.database.models.image import ImageAsset
from src.services import image_service


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def png_bytes() -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (10, 10), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _make_image(db_session, **overrides) -> ImageAsset:
    defaults = dict(
        filename="f.png",
        original_filename="o.png",
        mime_type="image/png",
        size_bytes=3,
        image_data=b"png-bytes",
        thumbnail_base64=None,
        tags=[],
        description="",
        category="content",
        uploaded_by="alice@test.com",
        is_active=True,
        created_by="alice@test.com",
        updated_by="alice@test.com",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    img = ImageAsset(**defaults)
    db_session.add(img)
    db_session.commit()
    db_session.refresh(img)
    return img


class TestOpaqueToken:
    def test_model_assigns_unique_unguessable_token(self, db_session):
        a = _make_image(db_session, original_filename="a.png")
        b = _make_image(db_session, original_filename="b.png")
        assert isinstance(a.token, str) and len(a.token) >= 20
        assert a.token != b.token

    def test_upload_response_id_is_opaque_token(self, client, png_bytes):
        resp = client.post(
            "/api/images/upload",
            files={"file": ("logo.png", png_bytes, "image/png")},
        )
        assert resp.status_code == 201
        img_id = resp.json()["id"]
        assert isinstance(img_id, str)
        assert len(img_id) >= 20
        assert not img_id.isdigit()  # not an enumerable integer

    def test_sequential_integer_pk_is_not_enumerable(self, client, db_session):
        img = _make_image(db_session)
        # The internal int PK (typically 1) must not resolve via the API.
        assert client.get("/api/images/1").status_code == 404
        assert client.get("/api/images/1/data").status_code == 404
        # Only the unguessable token resolves.
        assert client.get(f"/api/images/{img.token}").status_code == 200
        assert client.get(f"/api/images/{img.token}/data").status_code == 200


class TestEphemeralOwnerScoping:
    def test_ephemeral_cross_user_read_is_404(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "src.api.routes.images._get_current_user", lambda: "alice@test.com"
        )
        img = _make_image(db_session, category="ephemeral", uploaded_by="bob@test.com")
        assert client.get(f"/api/images/{img.token}").status_code == 404
        assert client.get(f"/api/images/{img.token}/data").status_code == 404

    def test_ephemeral_owner_read_is_200(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "src.api.routes.images._get_current_user", lambda: "alice@test.com"
        )
        img = _make_image(db_session, category="ephemeral", uploaded_by="alice@test.com")
        assert client.get(f"/api/images/{img.token}").status_code == 200
        assert client.get(f"/api/images/{img.token}/data").status_code == 200

    def test_library_image_open_read_by_token(self, client, db_session, monkeypatch):
        # Non-ephemeral (library) images stay open-read to any caller who knows
        # the token — the collaborator editor flow depends on it (accepted risk).
        monkeypatch.setattr(
            "src.api.routes.images._get_current_user", lambda: "alice@test.com"
        )
        img = _make_image(db_session, category="content", uploaded_by="bob@test.com")
        assert client.get(f"/api/images/{img.token}/data").status_code == 200


class TestServiceLookupByToken:
    def test_get_image_base64_by_token(self, db_session):
        img = _make_image(db_session, image_data=b"hello", mime_type="image/png")
        b64, mime = image_service.get_image_base64(db_session, img.token)
        assert mime == "image/png"
        assert base64.b64decode(b64) == b"hello"

    def test_get_image_base64_unknown_token_raises(self, db_session):
        with pytest.raises(ValueError):
            image_service.get_image_base64(db_session, "not-a-real-token")

    def test_delete_image_by_token(self, db_session):
        img = _make_image(db_session)
        image_service.delete_image(db_session, img.token, "alice@test.com")
        db_session.refresh(img)
        assert img.is_active is False
