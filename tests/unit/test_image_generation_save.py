"""``save_generated_image`` over ``image_service.upload_image``.

In-memory SQLite, same fixture style as ``tests/unit/test_image_service.py``.
Contract: "Unit A interface" in
``docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md``.
"""

from __future__ import annotations

import base64
import io
import re

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.services.image_generation import (
    SVG_THUMBNAIL_MAX_BYTES,
    GeneratedImage,
    save_generated_image,
)

from src.core.database import Base
from src.database.models.image import ImageAsset
from src.services import image_service
from src.services.svg_sanitizer import sanitize_svg

OWNER = "alice@example.com"
OTHER = "bob@example.com"
MODEL = "gpt-image-2.5-flare"
_FILENAME = re.compile(r"ai-[a-z0-9_-]{1,40}-\d{8}T\d{6}Z-[0-9a-f]{8}\.(?P<ext>[a-z]+)")
_SVG_DATA_URI = "data:image/svg+xml;base64,"


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
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = session_factory()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _transparent_png(size: tuple[int, int] = (300, 200)) -> bytes:
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (w - w // 2, h), (220, 40, 40, 255)), (w // 2, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(size: tuple[int, int] = (320, 180)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 90, 200)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _image(
    data: bytes, mime: str, ext: str, preset_id: str | None = "icon_png", model: str = MODEL
) -> GeneratedImage:
    return GeneratedImage(
        data=data,
        mime=mime,
        ext=ext,
        model=model,
        preset_id=preset_id,
        revised_prompt="revised",
        latency_s=10.5,
        usage=None,
    )


def _png_image() -> GeneratedImage:
    return _image(_transparent_png(), "image/png", "png")


def _svg_image(svg: str) -> GeneratedImage:
    return _image(
        svg.encode(), "image/svg+xml", "svg", preset_id="icon_svg", model="gpt-image-2.6-flare"
    )


def _save(db, img: GeneratedImage, prompt: str = "A lighthouse at dusk", **kwargs) -> ImageAsset:
    kwargs.setdefault("owner", OWNER)
    kwargs.setdefault("category", "content")
    kwargs.setdefault("tags", ["ai_generated", img.model, img.preset_id or "edit"])
    return save_generated_image(db, img, prompt=prompt, **kwargs)


def _reloaded(db, asset: ImageAsset) -> ImageAsset:
    """The row as committed: anything not committed is rolled back first."""
    token = asset.token
    db.rollback()
    db.expire_all()
    return db.query(ImageAsset).filter(ImageAsset.token == token).one()


def _decode_thumbnail(uri: str) -> Image.Image:
    header, b64 = uri.split(",", 1)
    assert header == "data:image/png;base64", header
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    img.load()
    return img


_SVG_WITH_DISALLOWED = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<circle cx="32" cy="32" r="20" fill="#1b3139"/>'
    "<blink>flash</blink><metadata>x</metadata>"
    "</svg>"
)


def _big_svg(min_bytes: int) -> str:
    """An all-allowlisted SVG at least ``min_bytes`` long (sanitizing keeps it whole)."""
    rect = '<rect x="{0}" y="{0}" width="10" height="10" fill="#ff3621" stroke="#1b3139"/>'
    count = min_bytes // len(rect.format(1000)) + 1
    body = "".join(rect.format(i % 1000) for i in range(count))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">{body}</svg>'


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_saves_a_library_row_with_the_owner_tags_category_and_prompt(db_session):
    img = _png_image()
    tags = ["ai_generated", MODEL, "icon_png"]

    asset = _save(db_session, img, prompt="A lighthouse at dusk", tags=tags, category="content")

    row = _reloaded(db_session, asset)
    assert isinstance(asset, ImageAsset)
    assert (row.uploaded_by, row.created_by) == (OWNER, OWNER)
    assert row.tags == tags
    assert row.category == "content"
    assert row.description == "A lighthouse at dusk"
    assert row.mime_type == "image/png"
    assert row.image_data == img.data
    assert row.size_bytes == len(img.data)
    assert row.is_active is True
    match = _FILENAME.fullmatch(row.original_filename)
    assert match, row.original_filename
    assert match["ext"] == "png"
    assert row.original_filename.startswith("ai-a-lighthouse-at-dusk-")


def test_a_background_jpeg_is_stored_as_a_background(db_session):
    img = _image(_jpeg(), "image/jpeg", "jpg", preset_id="background")

    asset = _save(
        db_session,
        img,
        prompt="Calm gradient",
        category="background",
        tags=["ai_generated", MODEL, "background"],
    )

    row = _reloaded(db_session, asset)
    assert (row.category, row.mime_type) == ("background", "image/jpeg")
    assert row.original_filename.endswith(".jpg")
    assert [a.token for a in image_service.search_images(db_session, category="background")] == [
        asset.token
    ]


def test_the_description_is_the_prompt_cut_to_500_characters(db_session):
    prompt = "lighthouse " + "x" * 700
    row = _reloaded(db_session, _save(db_session, _png_image(), prompt=prompt))
    assert row.description == prompt[:500]


def test_an_explicit_description_wins_and_is_cut_to_500_characters(db_session):
    first = _save(db_session, _png_image(), prompt="A lighthouse", description="Edited: bluer sky")
    second = _save(db_session, _png_image(), prompt="A lighthouse", description="d" * 600)
    assert _reloaded(db_session, first).description == "Edited: bluer sky"
    assert _reloaded(db_session, second).description == "d" * 500


def test_two_saves_of_the_same_prompt_do_not_collide(db_session):
    first = _save(db_session, _png_image(), prompt="Same prompt")
    second = _save(db_session, _png_image(), prompt="Same prompt")

    assert first.token != second.token
    assert first.original_filename != second.original_filename
    assert db_session.query(ImageAsset).count() == 2


# ---------------------------------------------------------------------------
# Thumbnails
# ---------------------------------------------------------------------------


def test_a_transparent_png_gets_a_thumbnail_that_keeps_alpha(db_session):
    row = _reloaded(db_session, _save(db_session, _png_image()))

    thumb = _decode_thumbnail(row.thumbnail_base64)
    assert thumb.mode == "RGBA"
    assert max(thumb.size) <= 150
    assert thumb.getchannel("A").getextrema() == (0, 255)


def test_an_svg_is_stored_sanitized_with_a_data_uri_thumbnail_of_the_stored_bytes(db_session):
    img = _svg_image(_SVG_WITH_DISALLOWED)

    row = _reloaded(
        db_session, _save(db_session, img, tags=["ai_generated", "gpt-image-2.6-flare", "icon_svg"])
    )

    assert row.mime_type == "image/svg+xml"
    assert row.original_filename.endswith(".svg")
    assert row.image_data == sanitize_svg(img.data)
    assert b"blink" not in row.image_data and b"metadata" not in row.image_data
    assert row.thumbnail_base64.startswith(_SVG_DATA_URI)
    assert base64.b64decode(row.thumbnail_base64[len(_SVG_DATA_URI) :]) == row.image_data


def test_an_svg_over_the_thumbnail_cap_gets_no_thumbnail(db_session):
    img = _svg_image(_big_svg(SVG_THUMBNAIL_MAX_BYTES + 10_000))

    row = _reloaded(db_session, _save(db_session, img))

    assert len(row.image_data) > SVG_THUMBNAIL_MAX_BYTES
    assert row.thumbnail_base64 is None


def test_the_svg_thumbnail_cap_applies_to_the_stored_sanitized_bytes(db_session):
    """Over the cap as generated, under it once the disallowed bulk is stripped."""
    bulk = "<blink>" + "z" * (SVG_THUMBNAIL_MAX_BYTES + 10_000) + "</blink>"
    img = _svg_image(_SVG_WITH_DISALLOWED.replace("</svg>", bulk + "</svg>"))
    assert len(img.data) > SVG_THUMBNAIL_MAX_BYTES

    row = _reloaded(db_session, _save(db_session, img))

    assert len(row.image_data) <= SVG_THUMBNAIL_MAX_BYTES
    assert base64.b64decode(row.thumbnail_base64[len(_SVG_DATA_URI) :]) == row.image_data


# ---------------------------------------------------------------------------
# Library integration
# ---------------------------------------------------------------------------


def test_a_saved_image_is_findable_by_a_prompt_word_for_its_owner(db_session):
    mine = _save(db_session, _png_image(), prompt="A lighthouse at dusk")
    _save(db_session, _png_image(), prompt="Another lighthouse", owner=OTHER)
    _save(db_session, _png_image(), prompt="A red fox")

    found = image_service.search_images(db_session, query="lighthouse", uploaded_by=OWNER)

    assert [a.token for a in found] == [mine.token]


def test_a_saved_image_is_findable_by_its_tags(db_session):
    asset = _save(db_session, _png_image(), tags=["ai_generated", MODEL, "icon_png"])
    _save(db_session, _png_image(), tags=["ai_generated", MODEL, "icon_svg"])

    found = image_service.search_images(db_session, tags=["ai_generated", "icon_png"])

    assert [a.token for a in found] == [asset.token]


@pytest.mark.parametrize("kind", ["png", "jpeg"])
def test_get_image_base64_returns_the_generated_bytes(db_session, kind):
    img = (
        _png_image()
        if kind == "png"
        else _image(_jpeg(), "image/jpeg", "jpg", preset_id="illustration")
    )
    asset = _save(db_session, img)

    b64, mime = image_service.get_image_base64(db_session, asset.token, requesting_user=OWNER)

    assert base64.b64decode(b64) == img.data
    assert mime == img.mime
