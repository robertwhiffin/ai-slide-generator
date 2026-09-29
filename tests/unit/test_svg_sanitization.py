"""Unit tests for server-side SVG upload sanitization."""

from __future__ import annotations

import io

import pytest
from lxml import etree  # type: ignore[import-untyped]
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.database.models.design_system import DesignSystemAsset
from src.services import image_service
from src.services.design_system_service import import_bundle
from src.services.svg_sanitizer import sanitize_svg
from tests.unit.conftest_design_system import make_bundle_zip


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(18, 52, 86)).save(buffer, format="PNG")
    return buffer.getvalue()


def _element_names(content: bytes) -> set[str]:
    root = etree.fromstring(content)
    return {etree.QName(element).localname for element in root.iter()}


def _find(root: etree._Element, name: str) -> etree._Element:
    return root.find(f".//{{http://www.w3.org/2000/svg}}{name}")


def test_sanitizes_executable_svg_content():
    malicious_svg = b"""<svg
        xmlns="http://www.w3.org/2000/svg"
        xmlns:xlink="http://www.w3.org/1999/xlink"
        onload="alert('root')"
        onclick="alert('root-click')"
    >
        <script>alert('script')</script>
        <rect x="0" y="0" width="10" height="10" onclick="alert('rect')" />
        <foreignObject><body><script>alert('foreign')</script></body></foreignObject>
        <use href="https://evil.example/icon.svg#icon" />
        <use xlink:href="#local-icon" />
        <a href="javascript:alert('link')"><text>click</text></a>
        <animate attributeName="href" to="javascript:alert('animated')" />
    </svg>"""

    sanitized = sanitize_svg(malicious_svg)
    root = etree.fromstring(sanitized)

    assert _element_names(sanitized) == {"svg", "rect", "use", "a", "text"}
    assert dict(root.attrib) == {}
    assert all("on" not in name for element in root.iter() for name in element.attrib)
    assert b"javascript:" not in sanitized
    xlink_href = "{http://www.w3.org/1999/xlink}href"
    assert _find(root, "use").get(xlink_href) == "#local-icon"


def test_preserves_clean_svg_content():
    clean_svg = b"""<svg
        xmlns="http://www.w3.org/2000/svg"
        width="120"
        height="40"
        viewBox="0 0 120 40"
    >
        <defs>
            <linearGradient id="brand-gradient" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stop-color="#123456" />
                <stop offset="100%" stop-color="#abcdef" />
            </linearGradient>
        </defs>
        <path d="M0 0h120v40H0z" fill="url(#brand-gradient)" />
        <rect x="8" y="8" width="10" height="10" />
        <text x="24" y="24" font-family="Inter" font-size="12">Acme</text>
        <use href="#icon" />
        <style>.title { fill: #123456; }</style>
    </svg>"""

    sanitized = sanitize_svg(clean_svg)
    root = etree.fromstring(sanitized)
    expected = {
        "svg",
        "defs",
        "linearGradient",
        "stop",
        "path",
        "rect",
        "text",
        "use",
        "style",
    }

    assert _element_names(sanitized) == expected
    assert root.get("width") == "120"
    assert root.get("viewBox") == "0 0 120 40"
    assert _find(root, "path").get("d") == "M0 0h120v40H0z"
    assert _find(root, "text").text == "Acme"
    assert _find(root, "use").get("href") == "#icon"
    assert ".title" in (_find(root, "style").text or "")


def test_rejects_malformed_svg_and_doctype():
    with pytest.raises(ValueError, match="well-formed XML"):
        sanitize_svg(b"<svg><rect></svg>")

    with pytest.raises(ValueError, match="DOCTYPE"):
        sanitize_svg(
            b'<!DOCTYPE svg [<!ENTITY xxe "https://evil.example">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg">&xxe;</svg>'
        )


def test_image_upload_sanitizes_svg_and_leaves_raster_unchanged(db_session):
    malicious_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        b'<script>alert(2)</script><rect width="1" height="1"/></svg>'
    )
    malicious_result = image_service.upload_image(
        db=db_session,
        file_content=malicious_svg,
        original_filename="malicious.svg",
        mime_type="image/svg+xml",
        user="tester",
    )

    assert b"<script>" not in malicious_result.image_data
    assert b"onload" not in malicious_result.image_data
    assert _element_names(malicious_result.image_data) == {"svg", "rect"}

    clean_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12">'
        b'<defs><linearGradient id="g">'
        b'<stop offset="0" stop-color="#111"/></linearGradient></defs>'
        b'<path d="M0 0h12v12H0z" fill="url(#g)"/>'
        b'<text x="1" y="2">Brand</text></svg>'
    )
    clean_result = image_service.upload_image(
        db=db_session,
        file_content=clean_svg,
        original_filename="clean.svg",
        mime_type="image/svg+xml",
        user="tester",
    )
    clean_root = etree.fromstring(clean_result.image_data)

    assert _element_names(clean_result.image_data) == {
        "svg",
        "defs",
        "linearGradient",
        "stop",
        "path",
        "text",
    }
    assert _find(clean_root, "path").get("fill") == "url(#g)"
    assert _find(clean_root, "text").text == "Brand"

    png = _png_bytes()
    png_result = image_service.upload_image(
        db=db_session,
        file_content=png,
        original_filename="logo.png",
        mime_type="image/png",
        user="tester",
    )

    assert png_result.image_data == png
    assert png_result.size_bytes == len(png)
    assert png_result.thumbnail_base64 is not None


def test_design_system_import_sanitizes_svg_and_leaves_raster_unchanged(db_session):
    malicious_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        b'<script>alert(2)</script><rect width="1" height="1"/></svg>'
    )
    clean_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12">'
        b'<defs><radialGradient id="g">'
        b'<stop offset="0" stop-color="#111"/></radialGradient></defs>'
        b'<circle cx="6" cy="6" r="6" fill="url(#g)"/>'
        b'<text x="1" y="2">Acme</text></svg>'
    )
    png = _png_bytes()
    bundle = make_bundle_zip(
        files={
            "fonts/acme-sans.woff2": b"OTTO synthetic-font-bytes",
            "assets/malicious.svg": malicious_svg,
            "assets/clean.svg": clean_svg,
            "assets/backgrounds/hero-bg.png": png,
            "README.md": b"# Acme\n",
            "SKILL.md": b"---\nname: acme\n---\n",
        }
    )

    design_system = import_bundle(db_session, zip_bytes=bundle, user="tester")
    assets = {
        asset.filename: asset
        for asset in db_session.query(DesignSystemAsset).filter_by(
            design_system_id=design_system.id
        )
    }

    assert b"<script>" not in assets["malicious.svg"].data
    assert b"onload" not in assets["malicious.svg"].data
    assert _element_names(assets["malicious.svg"].data) == {"svg", "rect"}
    assert _element_names(assets["clean.svg"].data) == {
        "svg",
        "defs",
        "radialGradient",
        "stop",
        "circle",
        "text",
    }
    assert assets["hero-bg.png"].data == png
    assert assets["hero-bg.png"].size_bytes == len(png)
