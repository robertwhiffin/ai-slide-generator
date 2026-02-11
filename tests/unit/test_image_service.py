"""Unit tests for image upload, thumbnail, search, and delete service."""
import base64

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.database.models.image import ImageAsset
from src.services import image_service
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


# Import image fixtures from shared conftest
pytest_plugins = ["tests.unit.conftest_images"]


# ===== Upload Validation =====

class TestUploadValidation:
    """Tests for upload_image input validation (fail-fast, no side effects)."""

    def test_rejects_invalid_mime_type(self, db_session, png_1x1):
        with pytest.raises(ValueError, match="File type not allowed"):
            image_service.upload_image(
                db=db_session, file_content=png_1x1,
                original_filename="test.bmp", mime_type="image/bmp",
                user="test",
            )
        assert db_session.query(ImageAsset).count() == 0

    def test_rejects_oversized_file(self, db_session, oversized_content):
        with pytest.raises(ValueError, match="File too large"):
            image_service.upload_image(
                db=db_session, file_content=oversized_content,
                original_filename="big.png", mime_type="image/png",
                user="test",
            )
        assert db_session.query(ImageAsset).count() == 0

    def test_accepts_png(self, db_session, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="testuser",
        )
        assert result.id is not None
        assert result.mime_type == "image/png"
        assert result.original_filename == "logo.png"
        assert result.size_bytes == len(png_1x1)
        assert result.uploaded_by == "testuser"
        assert result.is_active is True

    def test_accepts_jpeg(self, db_session, jpeg_100x100):
        result = image_service.upload_image(
            db=db_session, file_content=jpeg_100x100,
            original_filename="photo.jpg", mime_type="image/jpeg",
            user="test",
        )
        assert result.mime_type == "image/jpeg"

    def test_accepts_gif(self, db_session, gif_animated):
        result = image_service.upload_image(
            db=db_session, file_content=gif_animated,
            original_filename="anim.gif", mime_type="image/gif",
            user="test",
        )
        assert result.mime_type == "image/gif"

    def test_accepts_svg(self, db_session, svg_content):
        result = image_service.upload_image(
            db=db_session, file_content=svg_content,
            original_filename="icon.svg", mime_type="image/svg+xml",
            user="test",
        )
        assert result.mime_type == "image/svg+xml"
        assert result.thumbnail_base64 is None  # SVGs have no thumbnail


# ===== Upload Database Storage =====

class TestUploadDatabaseStorage:
    """Tests that upload correctly stores image data and metadata in DB."""

    def test_stores_image_bytes_in_db(self, db_session, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="testuser",
        )
        assert result.image_data == png_1x1

    def test_saves_tags_and_description(self, db_session, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="test", tags=["branding", "logo"], description="Company logo",
        )
        assert result.tags == ["branding", "logo"]
        assert result.description == "Company logo"

    def test_saves_category(self, db_session, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="test", category="branding",
        )
        assert result.category == "branding"

    def test_default_category_is_content(self, db_session, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="test",
        )
        assert result.category == "content"

    def test_sets_created_by_and_updated_by(self, db_session, png_1x1):
        result = image_service.upload_image(
            db=db_session, file_content=png_1x1,
            original_filename="logo.png", mime_type="image/png",
            user="alice",
        )
        assert result.created_by == "alice"
        assert result.updated_by == "alice"


# ===== Thumbnail Generation =====

class TestThumbnailGeneration:
    """Tests for _generate_thumbnail internal function."""

    def test_generates_for_png(self, png_100x100):
        thumb = image_service._generate_thumbnail(png_100x100, "image/png")
        assert thumb is not None
        assert thumb.startswith("data:image/")
        assert ";base64," in thumb

    def test_generates_for_jpeg(self, jpeg_100x100):
        thumb = image_service._generate_thumbnail(jpeg_100x100, "image/jpeg")
        assert thumb is not None
        assert thumb.startswith("data:image/jpeg;base64,")

    def test_generates_for_rgba_png(self, png_rgba_100x100):
        thumb = image_service._generate_thumbnail(png_rgba_100x100, "image/png")
        assert thumb is not None
        # RGBA images should produce PNG thumbnails (to preserve transparency)
        assert thumb.startswith("data:image/png;base64,")

    def test_extracts_first_frame_from_animated_gif(self, gif_animated):
        thumb = image_service._generate_thumbnail(gif_animated, "image/gif")
        assert thumb is not None
        assert thumb.startswith("data:image/")

    def test_returns_none_for_svg(self, svg_content):
        thumb = image_service._generate_thumbnail(svg_content, "image/svg+xml")
        assert thumb is None

    def test_thumbnail_is_reasonable_size(self, png_100x100):
        thumb = image_service._generate_thumbnail(png_100x100, "image/png")
        assert len(thumb) < 50_000

    def test_upload_stores_thumbnail_in_db(self, db_session, png_100x100):
        result = image_service.upload_image(
            db=db_session, file_content=png_100x100,
            original_filename="test.png", mime_type="image/png",
            user="test",
        )
        assert result.thumbnail_base64 is not None
        assert result.thumbnail_base64.startswith("data:image/")


# ===== get_image_base64 =====

class TestGetImageBase64:
    """Tests for retrieving full image as base64."""

    def test_encodes_image_data_to_base64(self, db_session, png_1x1):
        image = create_test_image(db_session, image_data=png_1x1)
        b64, mime = image_service.get_image_base64(db_session, image.id)
        assert b64 == base64.b64encode(png_1x1).decode("utf-8")
        assert mime == "image/png"

    def test_raises_for_nonexistent_image(self, db_session):
        with pytest.raises(ValueError, match="not found"):
            image_service.get_image_base64(db_session, 99999)

    def test_raises_for_inactive_image(self, db_session):
        image = create_test_image(db_session, is_active=False)
        with pytest.raises(ValueError, match="not found"):
            image_service.get_image_base64(db_session, image.id)


# ===== Search =====

class TestSearchImages:
    """Tests for image search/filtering."""

    def test_returns_all_active_images(self, db_session):
        create_test_image(db_session, original_filename="a.png")
        create_test_image(db_session, original_filename="b.png")
        create_test_image(db_session, original_filename="c.png", is_active=False)

        results = image_service.search_images(db_session)
        assert len(results) == 2

    def test_filter_by_category(self, db_session):
        create_test_image(db_session, category="branding", original_filename="logo.png")
        create_test_image(db_session, category="content", original_filename="chart.png")

        results = image_service.search_images(db_session, category="branding")
        assert len(results) == 1
        assert results[0].category == "branding"

    def test_excludes_ephemeral_by_default(self, db_session):
        create_test_image(db_session, category="content", original_filename="kept.png")
        create_test_image(db_session, category="ephemeral", original_filename="pasted.png")

        results = image_service.search_images(db_session)
        assert len(results) == 1
        assert results[0].original_filename == "kept.png"

    def test_includes_ephemeral_when_explicitly_filtered(self, db_session):
        create_test_image(db_session, category="ephemeral", original_filename="pasted.png")

        results = image_service.search_images(db_session, category="ephemeral")
        assert len(results) == 1

    def test_filter_by_query_text_filename(self, db_session):
        create_test_image(db_session, original_filename="acme-logo.png")
        create_test_image(db_session, original_filename="chart-q4.png")

        results = image_service.search_images(db_session, query="acme")
        assert len(results) == 1
        assert "acme" in results[0].original_filename

    def test_filter_by_query_text_description(self, db_session):
        create_test_image(db_session, description="ACME Corp logo", original_filename="a.png")
        create_test_image(db_session, description="Revenue chart", original_filename="b.png")

        results = image_service.search_images(db_session, query="ACME")
        assert len(results) == 1

    def test_excludes_inactive(self, db_session):
        create_test_image(db_session, is_active=True, original_filename="visible.png")
        create_test_image(db_session, is_active=False, original_filename="hidden.png")

        results = image_service.search_images(db_session)
        assert all(r.is_active for r in results)

    def test_ordered_by_newest_first(self, db_session):
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        create_test_image(db_session, original_filename="old.png", created_at=now - timedelta(days=1))
        create_test_image(db_session, original_filename="new.png", created_at=now)

        results = image_service.search_images(db_session)
        assert results[0].original_filename == "new.png"


# ===== Soft Delete =====

class TestDeleteImage:
    """Tests for soft-delete."""

    def test_sets_inactive(self, db_session):
        image = create_test_image(db_session)
        image_service.delete_image(db_session, image.id, "admin")

        refreshed = db_session.get(ImageAsset, image.id)
        assert refreshed.is_active is False

    def test_sets_updated_by(self, db_session):
        image = create_test_image(db_session)
        image_service.delete_image(db_session, image.id, "admin@example.com")

        refreshed = db_session.get(ImageAsset, image.id)
        assert refreshed.updated_by == "admin@example.com"

    def test_raises_for_nonexistent(self, db_session):
        with pytest.raises(ValueError, match="not found"):
            image_service.delete_image(db_session, 99999, "admin")

    def test_image_data_preserved_after_soft_delete(self, db_session, png_1x1):
        image = create_test_image(db_session, image_data=png_1x1)
        image_service.delete_image(db_session, image.id, "admin")

        refreshed = db_session.get(ImageAsset, image.id)
        assert refreshed.image_data == png_1x1
