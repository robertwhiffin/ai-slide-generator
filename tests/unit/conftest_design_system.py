"""Shared synthetic fixtures for Design System Library tests (Phase 3).

Everything here is SYNTHETIC — a fake "Acme" brand, dummy hex, and placeholder
bytes — per the public-repo hygiene rule (no real brand content ever).
"""
import io
import json
import zipfile
from typing import Optional

from PIL import Image as PILImage

MANIFEST_FILENAME = "_ds_manifest.json"


def png_bytes(width: int = 8, height: int = 8, color=(18, 52, 86)) -> bytes:
    """A tiny valid PNG (so PIL can read intrinsic dimensions)."""
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color=color).save(buf, format="PNG")
    return buf.getvalue()


# A minimal, syntactically valid SVG logo — placeholder art, not a real brand.
SVG_LOGO = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40">'
    b'<rect width="120" height="40" fill="#123456"/></svg>'
)

# Synthetic :root vars — a color and a type token in the "colors_and_type.css"
# convention the importer treats as a token source.
COLORS_AND_TYPE_CSS = """
:root {
  --brand-core-primary: #123456;
  --brand-accents-lava: #EB4A34;
  --heading-font: 'Inter', sans-serif;
}
""".strip()


def default_manifest() -> dict:
    """A representative _ds_manifest.json for the synthetic Acme bundle."""
    return {
        "name": "Acme Design System",
        "description": "Synthetic fixture brand — not a real design system.",
        "version": "1.0.0",
        "tokens": [
            {"group": "core", "name": "primary", "value": "#123456"},
            {"group": "spacing", "name": "md", "value": "16px"},
        ],
        "templates": [
            {"name": "Title Slide", "description": "Centered hero with logo lockup."},
            {"name": "Two Column", "description": "Left text, right chart."},
        ],
        "cards": [{"name": "Stat Card", "description": "Big number + label."}],
        "globalCssPaths": ["colors_and_type.css"],
        "fonts": [{"family": "Acme Sans", "path": "fonts/acme-sans.woff2"}],
    }


def make_bundle_zip(
    *,
    manifest: Optional[dict] = "__default__",
    css: Optional[str] = COLORS_AND_TYPE_CSS,
    files: Optional[dict] = None,
    root_prefix: str = "",
    include_manifest: bool = True,
) -> bytes:
    """Build an in-memory ``_ds_manifest.json`` design-system bundle as zip bytes.

    Args:
        manifest: dict written as _ds_manifest.json (``"__default__"`` -> default),
            or a raw string to write invalid JSON, or None to write ``null``.
        css: contents of colors_and_type.css (None to omit the file).
        files: extra ``{arcname: bytes}`` entries (fonts/…, assets/…, etc.).
        root_prefix: optional top-level folder (e.g. ``"acme/"``) prepended to
            every arcname, to exercise bundles zipped with a wrapping directory.
        include_manifest: when False, omit the manifest entirely.
    """
    if manifest == "__default__":
        manifest = default_manifest()

    if files is None:
        files = {
            "fonts/acme-sans.woff2": b"OTTO synthetic-font-bytes",
            "assets/logo.svg": SVG_LOGO,
            "assets/backgrounds/hero-bg.png": png_bytes(16, 16),
            # These must be skipped by the importer:
            "templates/title-shot.png": png_bytes(4, 4),
            "assets/preview.png": png_bytes(4, 4),
        }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if include_manifest:
            if isinstance(manifest, str):
                manifest_body = manifest  # raw (possibly invalid) JSON
            else:
                manifest_body = json.dumps(manifest)
            zf.writestr(root_prefix + MANIFEST_FILENAME, manifest_body)
        if css is not None:
            zf.writestr(root_prefix + "colors_and_type.css", css)
        for arcname, data in files.items():
            zf.writestr(root_prefix + arcname, data)
    return buf.getvalue()
