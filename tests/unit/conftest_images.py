"""Shared fixtures for image feature tests."""
import io
from datetime import datetime

import pytest
from PIL import Image as PILImage

from src.database.models.image import ImageAsset


# --- Test Image Generators ---

@pytest.fixture
def png_1x1() -> bytes:
    """Minimal valid 1x1 red PNG image (< 1KB)."""
    buf = io.BytesIO()
    img = PILImage.new("RGB", (1, 1), color=(255, 0, 0))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def png_100x100() -> bytes:
    """100x100 PNG for thumbnail tests (large enough to resize)."""
    buf = io.BytesIO()
    img = PILImage.new("RGB", (100, 100), color=(0, 128, 255))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def png_rgba_100x100() -> bytes:
    """100x100 PNG with transparency (RGBA mode)."""
    buf = io.BytesIO()
    img = PILImage.new("RGBA", (100, 100), color=(0, 128, 255, 128))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def jpeg_100x100() -> bytes:
    """100x100 JPEG image."""
    buf = io.BytesIO()
    img = PILImage.new("RGB", (100, 100), color=(0, 255, 0))
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def gif_animated() -> bytes:
    """Animated GIF with 3 frames."""
    frames = []
    for color in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]:
        frames.append(PILImage.new("RGB", (50, 50), color=color))
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


@pytest.fixture
def svg_content() -> bytes:
    """Minimal SVG content."""
    return b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect fill="red" width="100" height="100"/></svg>'


@pytest.fixture
def oversized_content() -> bytes:
    """Content exceeding 5MB limit."""
    return b"x" * (5 * 1024 * 1024 + 1)


# --- Database Helpers ---

def create_test_image(db_session, **overrides) -> ImageAsset:
    """Helper to create an ImageAsset in the test DB with sensible defaults."""
    defaults = dict(
        filename="test-uuid.png",
        original_filename="test.png",
        mime_type="image/png",
        size_bytes=1234,
        image_data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,  # Minimal PNG-like bytes
        thumbnail_base64="data:image/jpeg;base64,/9j/4AAQ",
        tags=["test"],
        description="Test image",
        category="content",
        uploaded_by="system",
        is_active=True,
        created_by="system",
        updated_by="system",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    image = ImageAsset(**defaults)
    db_session.add(image)
    db_session.commit()
    db_session.refresh(image)
    return image
