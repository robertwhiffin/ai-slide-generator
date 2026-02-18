"""Integration tests for image API endpoints using TestClient."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.database.models.image import ImageAsset
from tests.unit.conftest_images import create_test_image


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


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def png_bytes() -> bytes:
    """Minimal valid PNG for upload tests."""
    import io
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (10, 10), color=(255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


# --- Upload Endpoint Tests ---

class TestUploadEndpoint:
    """POST /api/images/upload"""

    def test_upload_returns_201(self, client, png_bytes):
        response = client.post(
            "/api/images/upload",
            files={"file": ("logo.png", png_bytes, "image/png")},
            data={"category": "branding", "tags": '["logo"]'},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["original_filename"] == "logo.png"
        assert data["mime_type"] == "image/png"
        assert data["category"] == "branding"
        assert data["tags"] == ["logo"]
        assert data["id"] is not None
        assert data["thumbnail_base64"] is not None

    def test_upload_rejects_invalid_type(self, client):
        response = client.post(
            "/api/images/upload",
            files={"file": ("test.txt", b"not an image", "text/plain")},
        )
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_upload_rejects_oversized(self, client):
        big = b"x" * (5 * 1024 * 1024 + 1)
        response = client.post(
            "/api/images/upload",
            files={"file": ("big.png", big, "image/png")},
        )
        assert response.status_code == 400
        assert "too large" in response.json()["detail"]

    def test_upload_without_file_returns_422(self, client):
        response = client.post("/api/images/upload")
        assert response.status_code == 422

    def test_upload_default_category_is_content(self, client, png_bytes):
        response = client.post(
            "/api/images/upload",
            files={"file": ("test.png", png_bytes, "image/png")},
        )
        assert response.status_code == 201
        assert response.json()["category"] == "content"


# --- List Endpoint Tests ---

class TestListEndpoint:
    """GET /api/images"""

    def test_list_empty(self, client):
        response = client.get("/api/images")
        assert response.status_code == 200
        data = response.json()
        assert data["images"] == []
        assert data["total"] == 0

    def test_list_returns_uploaded_images(self, client, db_session):
        create_test_image(db_session, original_filename="a.png")
        create_test_image(db_session, original_filename="b.png")

        response = client.get("/api/images")
        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_list_filter_by_category(self, client, db_session):
        create_test_image(db_session, category="branding", original_filename="logo.png")
        create_test_image(db_session, category="content", original_filename="chart.png")

        response = client.get("/api/images?category=branding")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["images"][0]["category"] == "branding"

    def test_list_filter_by_query(self, client, db_session):
        create_test_image(db_session, original_filename="acme-logo.png")
        create_test_image(db_session, original_filename="chart-q4.png")

        response = client.get("/api/images?query=acme")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    def test_list_filter_by_tags(self, client, db_session):
        create_test_image(db_session, original_filename="logo.png", tags=["branding", "logo"])
        create_test_image(db_session, original_filename="chart.png", tags=["data"])

        response = client.get("/api/images?tags=branding")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["images"][0]["original_filename"] == "logo.png"

    def test_list_filter_by_multiple_tags(self, client, db_session):
        create_test_image(db_session, original_filename="logo.png", tags=["branding", "logo"])
        create_test_image(db_session, original_filename="banner.png", tags=["branding"])

        response = client.get("/api/images?tags=branding,logo")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["images"][0]["original_filename"] == "logo.png"

    def test_list_excludes_inactive(self, client, db_session):
        create_test_image(db_session, is_active=True, original_filename="visible.png")
        create_test_image(db_session, is_active=False, original_filename="hidden.png")

        response = client.get("/api/images")
        assert response.json()["total"] == 1


# --- Get Single Image Tests ---

class TestGetImageEndpoint:
    """GET /api/images/{id}"""

    def test_returns_image_metadata(self, client, db_session):
        image = create_test_image(db_session, original_filename="logo.png")

        response = client.get(f"/api/images/{image.id}")
        assert response.status_code == 200
        assert response.json()["original_filename"] == "logo.png"

    def test_returns_404_for_nonexistent(self, client):
        response = client.get("/api/images/99999")
        assert response.status_code == 404

    def test_returns_404_for_inactive(self, client, db_session):
        image = create_test_image(db_session, is_active=False)
        response = client.get(f"/api/images/{image.id}")
        assert response.status_code == 404


# --- Get Image Data Tests ---

class TestGetImageDataEndpoint:
    """GET /api/images/{id}/data"""

    def test_returns_base64_data(self, client, db_session, png_bytes):
        image = create_test_image(db_session, image_data=png_bytes)

        response = client.get(f"/api/images/{image.id}/data")
        assert response.status_code == 200
        data = response.json()
        assert data["mime_type"] == "image/png"
        assert data["base64_data"] is not None
        assert data["data_uri"].startswith("data:image/png;base64,")

    def test_returns_404_for_nonexistent(self, client):
        response = client.get("/api/images/99999/data")
        assert response.status_code == 404


# --- Update Tests ---

class TestUpdateEndpoint:
    """PUT /api/images/{id}"""

    def test_update_tags(self, client, db_session):
        image = create_test_image(db_session, tags=["old"])

        response = client.put(
            f"/api/images/{image.id}",
            json={"tags": ["new", "tags"]},
        )
        assert response.status_code == 200
        assert response.json()["tags"] == ["new", "tags"]

    def test_update_description(self, client, db_session):
        image = create_test_image(db_session, description="old")

        response = client.put(
            f"/api/images/{image.id}",
            json={"description": "new description"},
        )
        assert response.status_code == 200
        assert response.json()["description"] == "new description"

    def test_update_returns_404_for_nonexistent(self, client):
        response = client.put("/api/images/99999", json={"tags": ["x"]})
        assert response.status_code == 404


# --- Delete Tests ---

class TestDeleteEndpoint:
    """DELETE /api/images/{id}"""

    def test_delete_returns_204(self, client, db_session):
        image = create_test_image(db_session)

        response = client.delete(f"/api/images/{image.id}")
        assert response.status_code == 204

    def test_deleted_image_no_longer_listed(self, client, db_session):
        image = create_test_image(db_session)
        client.delete(f"/api/images/{image.id}")

        response = client.get("/api/images")
        assert response.json()["total"] == 0

    def test_delete_returns_404_for_nonexistent(self, client):
        response = client.delete("/api/images/99999")
        assert response.status_code == 404
