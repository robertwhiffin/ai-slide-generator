"""Shared synthetic fixtures for Design System Library tests (Phase 3).

Everything here is SYNTHETIC — a fake "Acme" brand, dummy hex, and placeholder
bytes — per the public-repo hygiene rule (no real brand content ever).
"""
import io
import json
import struct
import zipfile
import zlib
from typing import Optional

from PIL import Image as PILImage

MANIFEST_FILENAME = "_ds_manifest.json"


def png_bytes(width: int = 8, height: int = 8, color=(18, 52, 86)) -> bytes:
    """A tiny valid PNG (so PIL can read intrinsic dimensions)."""
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color=color).save(buf, format="PNG")
    return buf.getvalue()


def webp_bytes(width: int = 8, height: int = 8, color=(18, 52, 86)) -> bytes:
    """A tiny valid WebP — the format a real export's ``.thumbnail`` files carry.

    Those files ship with NO extension, so their type is only knowable from the
    ``RIFF....WEBP`` magic bytes these carry.
    """
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color=color).save(buf, format="WEBP")
    return buf.getvalue()


def gif_bytes(width: int = 8, height: int = 8, color=(18, 52, 86)) -> bytes:
    """A tiny valid GIF (``GIF89a`` magic)."""
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color=color).save(buf, format="GIF")
    return buf.getvalue()


def jpeg_bytes(width: int = 8, height: int = 8, color=(18, 52, 86)) -> bytes:
    """A tiny valid JPEG (``\\xff\\xd8\\xff`` magic)."""
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color=color).save(buf, format="JPEG")
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
    """A representative _ds_manifest.json for the synthetic Acme bundle.

    Uses the legacy ``group``-keyed token shape (exercises the parser's
    backward-compatible ``group`` precedence). See :func:`realistic_manifest` for
    the ``kind``-keyed shape a real Claude-Design export ships.
    """
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


# Synthetic bundle source files (README/SKILL/template layout HTML). All fake —
# no real brand content. Retained as ``design_system_file`` rows (v1 Phase 1).
SYNTHETIC_README = b"# Acme Design System\n\nSynthetic readme for tests. Not a real brand.\n"
SYNTHETIC_SKILL = b"---\nname: acme-design\n---\n\nSynthetic SKILL doc for tests.\n"
SYNTHETIC_TEMPLATE_HTML = (
    b"<!doctype html><html><body><section>Acme synthetic layout</section></body></html>"
)


# A kind-based manifest mirroring a real Claude-Design export (still SYNTHETIC).
REALISTIC_CSS = """
:root {
  --acme-navy: #0B1F3A;
  --acme-ink-deep: #11141A;
  --font-sans: 'Acme Sans', sans-serif;
  --font-mono: 'Acme Mono', monospace;
  --fs-12: 12px;
  --fs-16: 16px;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.1);
}
""".strip()


def realistic_manifest() -> dict:
    """A ``kind``-keyed manifest mirroring a real Claude-Design export (synthetic).

    Tokens carry grouping in ``kind`` (color/font/spacing/shadow), names keep the
    ``--`` prefix, and the SAME tokens also appear in ``REALISTIC_CSS`` — exactly
    the shape that used to mis-bucket the 34 non-color tokens as colors,
    double-count tokens, and leave spacing empty. Fonts use the real
    ``fonts[]`` (family/weight/style/files) + ``brandFonts[]`` (family->tokens)
    shapes so the font mapping is exercised end-to-end.
    """
    return {
        "name": "Acme Realistic DS",
        "description": "Synthetic kind-based fixture — not a real brand.",
        "version": "2.0.0",
        "namespace": "acme",
        "tokens": [
            {"name": "--acme-navy", "value": "#0B1F3A", "kind": "color",
             "definedIn": "colors_and_type.css"},
            {"name": "--acme-ink-deep", "value": "#11141A", "kind": "color",
             "definedIn": "colors_and_type.css"},
            {"name": "--font-sans", "value": "'Acme Sans', sans-serif", "kind": "font",
             "definedIn": "colors_and_type.css"},
            {"name": "--font-mono", "value": "'Acme Mono', monospace", "kind": "font",
             "definedIn": "colors_and_type.css"},
            {"name": "--fs-12", "value": "12px", "kind": "spacing",
             "definedIn": "colors_and_type.css"},
            {"name": "--fs-16", "value": "16px", "kind": "spacing",
             "definedIn": "colors_and_type.css"},
            {"name": "--shadow-sm", "value": "0 1px 2px rgba(0,0,0,0.1)", "kind": "shadow",
             "definedIn": "colors_and_type.css"},
        ],
        "templates": [{"name": "Title", "description": "Hero."}],
        "globalCssPaths": ["colors_and_type.css"],
        "fonts": [
            {"family": "Acme Sans", "weight": "400", "style": "normal",
             "cssPath": "colors_and_type.css", "files": ["fonts/acme-sans-regular.woff2"]},
            {"family": "Acme Sans", "weight": "700", "style": "normal",
             "cssPath": "colors_and_type.css", "files": ["fonts/acme-sans-bold.woff2"]},
            {"family": "Acme Mono", "weight": "400", "style": "normal",
             "cssPath": "colors_and_type.css", "files": ["fonts/acme-mono.woff2"]},
        ],
        "brandFonts": [
            {"family": "Acme Sans", "status": "ok", "tokens": ["--font-sans"],
             "path": "colors_and_type.css"},
            {"family": "Acme Mono", "status": "ok", "tokens": ["--font-mono"],
             "path": "colors_and_type.css"},
        ],
    }


# A synthetic template entry file (archetype-catalog shape): one inline <style>
# using var(--…) tokens + a CSS url() background, brand-asset <img> refs in both
# parent-relative and bundle-root-relative form, one unresolvable ref, and
# preview-chrome <script> tags. All fake — no real brand content.
TEMPLATED_TEMPLATE_HTML = b"""<!doctype html>
<html><head>
<script src="./ds-base.js"></script>
<style>
.slide { width: 1280px; height: 720px; padding: 72px 88px; color: var(--acme-navy); }
.hero { background-image: url("../assets/backgrounds/hero-bg.png"); }
</style>
</head><body>
<section class="slide cover">
  <img src="../assets/logo.svg" alt="Acme logo" />
  <h1>Sample cover title</h1>
</section>
<section class="slide content">
  <img src="assets/logo.svg" alt="Acme logo root-relative" />
  <img src="../assets/missing-art.png" alt="Ghost asset" />
</section>
<script>window.__acmePreviewChrome = true;</script>
</body></html>
"""


def template_preview_png() -> bytes:
    """Tiny synthetic preview screenshot for the template fixture."""
    return png_bytes(6, 4, color=(18, 52, 86))


def templated_manifest() -> dict:
    """The default manifest plus addressable templates (folder + entryPath),
    mirroring the Claude-Design export shape ``templates[]{name, description,
    folder, entryPath}``. Still fully SYNTHETIC."""
    manifest = default_manifest()
    manifest["templates"] = [
        {
            "name": "Acme Corporate",
            "description": "Cover + agenda, content, closing.",
            "folder": "templates/corporate",
            "entryPath": "templates/corporate/index.html",
        },
    ]
    return manifest


def templated_bundle_files() -> dict:
    """Bundle files for a template-bearing synthetic bundle: the default file set
    with the corporate template's entry HTML replaced by the ref-rich fixture and
    a preview screenshot added."""
    return {
        "fonts/acme-sans.woff2": b"OTTO synthetic-font-bytes",
        "assets/logo.svg": SVG_LOGO,
        "assets/backgrounds/hero-bg.png": png_bytes(16, 16),
        "README.md": SYNTHETIC_README,
        "SKILL.md": SYNTHETIC_SKILL,
        "templates/corporate/index.html": TEMPLATED_TEMPLATE_HTML,
        "templates/corporate/preview.png": template_preview_png(),
        "templates/corporate/ds-base.js": b"// synthetic - not retained",
    }


# ---------------------------------------------------------------------------
# Real-export shape: one DOT-PREFIXED, EXTENSION-LESS `.thumbnail` per template
# ---------------------------------------------------------------------------

#: The template folders a real Claude-Design export ships, each carrying a
#: ``templates/<slug>/.thumbnail`` screenshot: dot-prefixed, named ``thumbnail``
#: (not ``preview``), and with NO file extension. Names are generic layout
#: archetypes, not brand content.
DOT_THUMBNAIL_SLUGS = (
    "corporate",
    "executive-events",
    "reference-architecture",
    "strategy-consulting",
)


def dot_thumbnail_manifest() -> dict:
    """A manifest declaring one template per :data:`DOT_THUMBNAIL_SLUGS` folder."""
    manifest = default_manifest()
    manifest["name"] = "Acme Dot Thumbnail DS"
    manifest["templates"] = [
        {
            "name": f"Acme {slug}",
            "description": f"Synthetic {slug} layout.",
            "folder": f"templates/{slug}",
            "entryPath": f"templates/{slug}/index.html",
        }
        for slug in DOT_THUMBNAIL_SLUGS
    ]
    return manifest


def dot_thumbnail_bundle_files() -> dict:
    """Bundle files matching the real export: every template folder carries an
    ``index.html`` plus an extension-less, dot-prefixed WebP ``.thumbnail``.

    Each thumbnail gets distinct dimensions so a test can prove the rows are not
    all the same asset.
    """
    files = {
        "fonts/acme-sans.woff2": b"OTTO synthetic-font-bytes",
        "assets/logo.svg": SVG_LOGO,
        "assets/backgrounds/hero-bg.png": png_bytes(16, 16),
        "README.md": SYNTHETIC_README,
        "SKILL.md": SYNTHETIC_SKILL,
    }
    for index, slug in enumerate(DOT_THUMBNAIL_SLUGS):
        files[f"templates/{slug}/index.html"] = TEMPLATED_TEMPLATE_HTML
        files[f"templates/{slug}/.thumbnail"] = webp_bytes(10 + index, 6 + index)
        files[f"templates/{slug}/ds-base.js"] = b"// synthetic - not retained"
    return files


def make_declared_size_bundle_zip(
    entries: dict,
    *,
    manifest: Optional[dict] = "__default__",
    css: Optional[str] = COLORS_AND_TYPE_CSS,
    root_prefix: str = "",
) -> bytes:
    """Build a bundle whose ``entries`` DECLARE a large uncompressed size cheaply.

    ``entries`` maps ``{arcname: declared_uncompressed_bytes}``. Each entry is
    written as highly-compressible NUL bytes streamed a megabyte at a time, so the
    zip header advertises the full size (what the importer's pre-materialisation
    size guard reads) while the zip on disk stays kilobytes — a faithful
    decompression bomb that never allocates the declared size in the test process.

    Use this instead of ``b"x" * (CAP + 1)`` so a guard test does not allocate
    hundreds of megabytes just because the caps were raised.
    """
    if manifest == "__default__":
        manifest = default_manifest()

    buf = io.BytesIO()
    chunk = b"\0" * (1024 * 1024)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if manifest is not None:
            body = manifest if isinstance(manifest, str) else json.dumps(manifest)
            zf.writestr(root_prefix + MANIFEST_FILENAME, body)
        if css is not None:
            zf.writestr(root_prefix + "colors_and_type.css", css)
        for arcname, declared in entries.items():
            with zf.open(root_prefix + arcname, "w") as handle:
                remaining = declared
                while remaining > 0:
                    handle.write(chunk[: min(remaining, len(chunk))])
                    remaining -= min(remaining, len(chunk))
    return buf.getvalue()


#: The legacy 32-bit "relative offset of local header" value that means "the real
#: offset is 64 bits wide, in the ZIP64 extra field". CPython honours the pair.
_ZIP64_OFFSET_SENTINEL = 0xFFFFFFFF
#: ZIP64 Extended Information Extra Field.
_ZIP64_EXTRA_TAG = 0x0001


def make_zip64_header_offset_archive(offset: bytes = b"\xff" * 8) -> bytes:
    """A tiny, CPython-readable .zip whose entry's LOCAL HEADER OFFSET is hostile.

    Built by hand rather than through ``zipfile``, because the point is a central
    directory record no writer would ever emit: the legacy 32-bit offset field holds
    the ZIP64 sentinel ``0xffffffff`` and the ZIP64 extra field supplies a 64-bit
    replacement of the caller's choosing. ``ZipInfo._decodeExtra`` substitutes it
    verbatim, so the default of eight ``0xff`` bytes yields
    ``header_offset == 2**64 - 1`` — an offset no seek can accept, on an archive
    CPython opens and lists without complaint.

    Only ``_ds_manifest.json`` is present, and its content is not valid bundle JSON.
    That is deliberate and sufficient: the whole-bundle path scan runs BEFORE the
    manifest is read, so this archive exercises the offset and nothing else.

    Every length and offset is computed here, so the archive stays internally
    consistent — in particular the end-of-central-directory record's size and
    location leave CPython's prepended-data adjustment (``concat``) at zero, which
    keeps ``header_offset`` exactly the crafted value rather than a shifted one.
    """
    name = MANIFEST_FILENAME.encode()
    data = b"{}"
    crc = zlib.crc32(data)
    # Stored, not deflated: the sizes below are then the same number twice, and the
    # local header's variable part is just the name.
    local_header = (
        b"PK\x03\x04"
        + struct.pack("<HHHHH", 20, 0, 0, 0, 0x21)  # version, flags, method, time, date
        + struct.pack("<LLL", crc, len(data), len(data))
        + struct.pack("<HH", len(name), 0)  # name length, extra length
        + name
    )
    extra = struct.pack("<HH", _ZIP64_EXTRA_TAG, len(offset)) + offset
    central = (
        b"PK\x01\x02"
        + struct.pack("<HHHHHH", 20, 20, 0, 0, 0, 0x21)
        + struct.pack("<LLL", crc, len(data), len(data))
        + struct.pack("<HHH", len(name), len(extra), 0)
        + struct.pack("<HHL", 0, 0, 0)  # disk, internal attrs, external attrs
        + struct.pack("<L", _ZIP64_OFFSET_SENTINEL)
        + name
        + extra
    )
    body = local_header + data
    end_record = (
        b"PK\x05\x06"
        + struct.pack("<HHHH", 0, 0, 1, 1)
        + struct.pack("<LL", len(central), len(body))
        + struct.pack("<H", 0)
    )
    return body + central + end_record


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
            # Source files retained as design_system_file rows (v1 Phase 1):
            "README.md": SYNTHETIC_README,
            "SKILL.md": SYNTHETIC_SKILL,
            "templates/corporate/index.html": SYNTHETIC_TEMPLATE_HTML,
            # These must be skipped entirely (neither asset nor retained source):
            "templates/corporate/ds-base.js": b"// synthetic - not retained",
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
