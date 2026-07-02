"""Design System bundle import + asset retrieval (Phase 3).

See ``docs/technical/design-system-library-spec.md`` §5 (bundle), §6 (data model),
§7 (API). The importer accepts a ``.zip`` design-system *project* and turns it into
Lakebase rows:

- ``_ds_manifest.json`` — the manifest (``tokens[]``, ``templates[]``, ``cards[]``,
  ``globalCssPaths``, ``fonts[]``). Parsed and stored verbatim on
  ``DesignSystem.manifest_json`` so the Phase-2 compiler can read ``templates``.
- ``colors_and_type.css`` (and any ``globalCssPaths``) — its ``:root { --x: y }``
  custom properties are parsed as an ADDITIONAL token source.
- ``fonts/**`` and ``assets/**`` — binary files stored as ``design_system_asset``
  rows (bytes in-DB, following the ``image_assets`` pattern). Template screenshots
  and ``preview*`` files are reference-only and skipped.

After the rows are flushed (so assets have real ids), the Phase-2
``recompute_compiled_style_content`` produces the prompt artifact — the same
``compiled_style_content`` the generation seam already consumes. Brand assets are
referenced with the ``{{ds-asset:ID}}`` placeholder, resolved to bytes by
``src.utils.ds_asset_utils`` in the render path.

Guardrails: per-asset and per-bundle size limits are enforced against each entry's
declared *uncompressed* size BEFORE it is read into memory, so a decompression
bomb is rejected rather than materialised.

Everything here is brand-neutral engine code; no brand content is embedded.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import mimetypes
import re
import zipfile
from typing import Optional

from sqlalchemy.orm import Session

from src.database.models.design_system import (
    MAX_ASSET_SIZE_BYTES,
    MAX_BUNDLE_SIZE_BYTES,
    DesignSystem,
    DesignSystemAsset,
    DesignSystemToken,
)
from src.services.design_system_compiler import recompute_compiled_style_content

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "_ds_manifest.json"
DEFAULT_CSS_TOKEN_SOURCE = "colors_and_type.css"

# Token groups the compiler understands (colors + type + spacing).
_KNOWN_GROUPS = frozenset(("core", "accents", "ink", "tints", "type", "spacing"))

# Font file extensions -> stored as kind="font".
_FONT_EXTS = frozenset(("woff2", "woff", "ttf", "otf"))

# Extension -> MIME overrides (fonts + svg aren't reliably guessed by mimetypes).
_MIME_OVERRIDES = {
    "svg": "image/svg+xml",
    "woff2": "font/woff2",
    "woff": "font/woff",
    "ttf": "font/ttf",
    "otf": "font/otf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

_ROOT_BLOCK_RE = re.compile(r":root\s*\{([^}]*)\}", re.IGNORECASE)
_CSS_VAR_RE = re.compile(r"--([A-Za-z0-9\-_]+)\s*:\s*([^;]+);")


class DesignSystemImportError(ValueError):
    """A bundle could not be imported (malformed, missing manifest, oversized).

    Routes map this to HTTP 400 so the caller gets a clear, actionable message.
    """


class DesignSystemNameConflictError(ValueError):
    """A design system with the requested name already exists.

    Routes map this to HTTP 409. Name uniqueness is enforced (spec §6:
    ``name (unique)``); the caller may supply a different name to import a copy.
    """


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _guess_mime(filename: str) -> str:
    ext = _ext(filename)
    if ext in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _looks_like_color(value: str) -> bool:
    v = value.strip().lower()
    return v.startswith("#") or v.startswith("rgb") or v.startswith("hsl")


def _infer_asset_kind(rel_path: str) -> str:
    """Map a bundle-relative path to a ``design_system_asset.kind``.

    ``font`` for anything under ``fonts/`` or with a font extension; otherwise a
    best-effort keyword match, defaulting to ``illustration`` (an embeddable image
    kind, so unknown brand art still surfaces in generated slides).
    """
    low = rel_path.lower()
    if low.startswith("fonts/") or _ext(low) in _FONT_EXTS:
        return "font"
    if "lockup" in low:
        return "lockup"
    if "logo" in low:
        return "logo"
    if "icon" in low:
        return "icon"
    if "illustration" in low:
        return "illustration"
    if "background" in low or "-bg." in low or "/bg" in low:
        return "background"
    return "illustration"


def _should_skip(rel_path: str) -> bool:
    """Only ``assets/**`` and ``fonts/**`` files are stored; skip everything else.

    Directories, OS junk, dotfiles, template screenshots and ``preview*`` files
    (reference-only material) are excluded.
    """
    low = rel_path.lower()
    base = _basename(low)
    if not rel_path or rel_path.endswith("/"):
        return True
    if low.startswith("__macosx/") or "/__macosx/" in low:
        return True
    if base == ".ds_store" or base.startswith("."):
        return True
    if not (low.startswith("assets/") or low.startswith("fonts/")):
        return True
    if base.startswith("preview"):
        return True
    if "template_shot" in low or "/templates/" in low:
        return True
    return False


def _classify_css_var(var_name: str, value: str) -> tuple[str, str]:
    """Map a CSS custom property to a ``(group, name)`` token key.

    Recognises the ``--brand-<group>-<name>`` / ``--<group>-<name>`` conventions;
    otherwise infers ``core`` for color-like values and ``type`` for the rest, so
    CSS-sourced tokens land in groups the compiler actually emits.
    """
    parts = var_name.split("-")
    if parts and parts[0] == "brand":
        parts = parts[1:]
    if parts and parts[0] in _KNOWN_GROUPS:
        group = parts[0]
        name = "-".join(parts[1:]) or group
        return group, name
    return ("core" if _looks_like_color(value) else "type"), var_name


def _parse_css_root_vars(css_text: str) -> list[tuple[str, str]]:
    """Extract ``(--var-name-without-dashes, value)`` pairs from ``:root`` blocks."""
    pairs: list[tuple[str, str]] = []
    for block in _ROOT_BLOCK_RE.findall(css_text or ""):
        for match in _CSS_VAR_RE.finditer(block):
            pairs.append((match.group(1).strip(), match.group(2).strip()))
    return pairs


def _image_dimensions(data: bytes, mime: str) -> tuple[Optional[int], Optional[int]]:
    """Best-effort intrinsic (width, height); ``(None, None)`` for fonts/SVG/failure."""
    if mime == "image/svg+xml" or mime.startswith("font/"):
        return (None, None)
    try:
        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(data)) as im:
            return (im.width, im.height)
    except Exception:
        return (None, None)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def import_bundle(
    db: Session,
    *,
    zip_bytes: bytes,
    user: Optional[str],
    name_override: Optional[str] = None,
) -> DesignSystem:
    """Import a ``.zip`` design-system bundle into Lakebase and compile it.

    Returns the persisted :class:`DesignSystem` (committed, with tokens + assets +
    ``compiled_style_content``).

    Raises:
        DesignSystemImportError: bundle is not a zip, missing/invalid manifest, or
            violates a size limit (HTTP 400).
        DesignSystemNameConflictError: the resolved name already exists (HTTP 409).
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise DesignSystemImportError(f"Upload is not a valid .zip bundle: {exc}") from exc

    with zf:
        root_prefix = _locate_root_prefix(zf)
        manifest = _read_manifest(zf, root_prefix)
        name = _resolve_name(name_override, manifest, root_prefix)

        # Fail fast on a name clash before doing any expensive work.
        existing = db.query(DesignSystem).filter(DesignSystem.name == name).first()
        if existing:
            raise DesignSystemNameConflictError(
                f"A design system named '{name}' already exists (id={existing.id}). "
                "Choose a different name to import a copy."
            )

        tokens = _collect_tokens(zf, root_prefix, manifest)
        assets = _collect_assets(zf, root_prefix)

    raw_description = manifest.get("description")
    description = (
        raw_description.strip()
        if isinstance(raw_description, str) and raw_description.strip()
        else None
    )
    design_system = DesignSystem(
        name=name,
        description=description,
        created_by=user,
        updated_by=user,
        manifest_json=manifest,
        version=1,
        published=False,
        is_default=False,
        is_active=True,
    )
    for token in tokens:
        design_system.tokens.append(token)
    for asset in assets:
        design_system.assets.append(asset)

    db.add(design_system)
    # Flush assigns primary keys so {{ds-asset:ID}} placeholders point at real ids.
    db.flush()
    recompute_compiled_style_content(design_system)
    db.commit()
    db.refresh(design_system)

    logger.info(
        "Imported design system '%s' (id=%s): %d token(s), %d asset(s)",
        design_system.name,
        design_system.id,
        len(tokens),
        len(assets),
    )
    return design_system


def _locate_root_prefix(zf: zipfile.ZipFile) -> str:
    """Return the directory prefix that contains ``_ds_manifest.json`` (``""`` at root).

    Bundles are sometimes zipped inside a wrapping folder; every other path is then
    interpreted relative to that prefix.
    """
    for name in zf.namelist():
        if name.lower().startswith("__macosx"):
            continue
        if _basename(name) == MANIFEST_FILENAME:
            return name[: -len(MANIFEST_FILENAME)]
    raise DesignSystemImportError(
        f"Bundle is missing its manifest ({MANIFEST_FILENAME}). A design-system "
        "bundle must contain a _ds_manifest.json at its root."
    )


def _read_manifest(zf: zipfile.ZipFile, root_prefix: str) -> dict:
    try:
        raw = zf.read(root_prefix + MANIFEST_FILENAME)
    except KeyError as exc:  # pragma: no cover - guarded by _locate_root_prefix
        raise DesignSystemImportError(f"Bundle is missing {MANIFEST_FILENAME}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise DesignSystemImportError(f"{MANIFEST_FILENAME} is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise DesignSystemImportError(f"{MANIFEST_FILENAME} must be a JSON object.")
    return manifest


def _resolve_name(name_override: Optional[str], manifest: dict, root_prefix: str) -> str:
    for candidate in (name_override, manifest.get("name")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    stem = root_prefix.rstrip("/").rsplit("/", 1)[-1] if root_prefix else ""
    return stem or "Imported Design System"


def _collect_tokens(
    zf: zipfile.ZipFile, root_prefix: str, manifest: dict
) -> list[DesignSystemToken]:
    """Tokens from ``manifest['tokens']`` plus any ``:root`` CSS vars.

    Manifest tokens take precedence; a ``(group, name)`` is written once.
    """
    by_key: dict[tuple[str, str], str] = {}

    for entry in manifest.get("tokens") or []:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        value = entry.get("value")
        if not name or value is None or str(value).strip() == "":
            continue
        group = (entry.get("group") or "core").strip() or "core"
        by_key.setdefault((group, name), str(value).strip())

    for css_text in _read_css_sources(zf, root_prefix, manifest):
        for var_name, value in _parse_css_root_vars(css_text):
            group, name = _classify_css_var(var_name, value)
            by_key.setdefault((group, name), value)

    return [
        DesignSystemToken(group=group, name=name, value=value)
        for (group, name), value in sorted(by_key.items())
    ]


def _read_css_sources(zf: zipfile.ZipFile, root_prefix: str, manifest: dict) -> list[str]:
    """Read the CSS token sources: ``globalCssPaths`` + the conventional file."""
    paths: list[str] = []
    for path in manifest.get("globalCssPaths") or []:
        if isinstance(path, str) and path.strip():
            paths.append(path.strip())
    if DEFAULT_CSS_TOKEN_SOURCE not in paths:
        paths.append(DEFAULT_CSS_TOKEN_SOURCE)

    texts: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        try:
            raw = zf.read(root_prefix + path)
        except KeyError:
            continue
        try:
            texts.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            logger.warning("Skipping non-UTF-8 CSS token source: %s", path)
    return texts


def _collect_assets(zf: zipfile.ZipFile, root_prefix: str) -> list[DesignSystemAsset]:
    """Read + validate ``assets/**`` and ``fonts/**`` files into asset rows."""
    assets: list[DesignSystemAsset] = []
    total = 0
    for info in zf.infolist():
        name = info.filename
        if not name.startswith(root_prefix):
            continue
        rel = name[len(root_prefix):]
        if _should_skip(rel):
            continue

        # Guard against decompression bombs: check the declared uncompressed size
        # from the zip header BEFORE reading the entry into memory.
        declared = info.file_size
        if declared > MAX_ASSET_SIZE_BYTES:
            raise DesignSystemImportError(
                f"Asset '{rel}' is too large: {declared} bytes "
                f"(max {MAX_ASSET_SIZE_BYTES} per asset)."
            )
        if total + declared > MAX_BUNDLE_SIZE_BYTES:
            raise DesignSystemImportError(
                f"Bundle exceeds the maximum size of {MAX_BUNDLE_SIZE_BYTES} bytes."
            )

        data = zf.read(info)
        size = len(data)
        if size > MAX_ASSET_SIZE_BYTES:
            raise DesignSystemImportError(
                f"Asset '{rel}' is too large: {size} bytes (max {MAX_ASSET_SIZE_BYTES})."
            )
        total += size
        if total > MAX_BUNDLE_SIZE_BYTES:
            raise DesignSystemImportError(
                f"Bundle exceeds the maximum size of {MAX_BUNDLE_SIZE_BYTES} bytes."
            )

        mime = _guess_mime(rel)
        kind = _infer_asset_kind(rel)
        width, height = _image_dimensions(data, mime)
        assets.append(
            DesignSystemAsset(
                kind=kind,
                filename=_basename(rel),
                mime=mime,
                data=data,
                width=width,
                height=height,
                size_bytes=size,
            )
        )
    return assets


# ---------------------------------------------------------------------------
# Asset retrieval (used by the {{ds-asset:ID}} resolver + serve endpoint)
# ---------------------------------------------------------------------------


def get_asset_base64(db: Session, asset_id: int) -> tuple[str, str]:
    """Return ``(base64_data, mime)`` for a stored design-system asset.

    Mirrors ``image_service.get_image_base64`` so the ``{{ds-asset:ID}}`` resolver
    embeds bytes exactly the way ``{{image:ID}}`` does.
    """
    asset = db.query(DesignSystemAsset).filter(DesignSystemAsset.id == asset_id).first()
    if not asset:
        raise ValueError(f"Design system asset {asset_id} not found")
    return base64.b64encode(asset.data).decode("utf-8"), asset.mime
