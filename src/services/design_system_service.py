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
  rows (bytes in-DB, following the ``image_assets`` pattern). ``preview*`` files
  under ``assets/`` are reference-only and skipped; a template folder's
  ``templates/<folder>/preview.*`` screenshot IS stored (kind ``template_shot``,
  v1 Phase 4) so the template picker can serve thumbnails.

v1 Phase 1 ("import foundation") extends the importer WITHOUT changing the
generation seam:

- Bundle SOURCE files (README.md / SKILL.md / CSS token sources / ``templates/*/
  index.html``) are RETAINED as ``design_system_file`` rows (bytes in-DB). Files
  already stored as ``design_system_asset`` (assets/fonts) get a path-only
  REFERENCE row (``asset_id`` set, ``data`` NULL) — their bytes are never
  double-stored. Every path is normalized and zip-slip (absolute / ``..``) is
  rejected.
- Tokens run through ONE canonical parser: the real manifest carries grouping in
  ``kind`` (color/font/spacing/shadow), names are stripped of leading ``--`` /
  ``brand-`` so manifest tokens dedup against the identical CSS ``:root`` vars,
  and shadow tokens are emitted. (Previously grouping was read from a ``group``
  key the real manifest lacks, so ~34 non-color tokens mis-bucketed as colors,
  tokens double-counted 72->144, and spacing came out empty.)
- The manifest ``fonts[]`` / ``brandFonts[]`` are normalized into a
  family -> variants + token-linkage mapping on ``DesignSystem.font_mapping_json``
  so typography is usable downstream without re-parsing the manifest.

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
from typing import Any, Optional

from sqlalchemy.orm import Session, defer

from src.database.models.design_system import (
    MAX_ASSET_SIZE_BYTES,
    MAX_BUNDLE_SIZE_BYTES,
    DesignSystem,
    DesignSystemAsset,
    DesignSystemFile,
    DesignSystemToken,
)
from src.services.design_system_compiler import recompute_compiled_style_content

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "_ds_manifest.json"
DEFAULT_CSS_TOKEN_SOURCE = "colors_and_type.css"

# Color sub-groups the compiler renders as :root vars. A token name whose first
# segment is one of these carries its group in the name (e.g. --brand-accents-lava).
_COLOR_SUBGROUPS = frozenset(("core", "accents", "ink", "tints"))

# Every token group the canonical parser may emit — also the set honored when a
# (legacy/backward-compatible) manifest token carries an explicit ``group`` key.
_TOKEN_GROUPS = frozenset(("core", "accents", "ink", "tints", "type", "spacing", "shadow"))

# Manifest token ``kind`` -> canonical token group. ``color`` resolves to a color
# sub-group via the name (default ``core``); the compiler renders ``type`` +
# ``spacing`` as rules and (for now) surfaces ``shadow`` with a warning.
_KIND_TO_GROUP = {
    "color": "core",
    "colour": "core",
    "font": "type",
    "spacing": "spacing",
    "shadow": "shadow",
}

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


# A template folder's preview screenshot (``templates/<folder>/preview.*`` with a
# raster-image extension) — stored as a ``template_shot`` asset so the Phase 4
# template picker can serve thumbnails. Checked BEFORE ``_should_skip`` (which
# excludes ``templates/**`` from generic asset storage).
_TEMPLATE_PREVIEW_RE = re.compile(
    r"^templates/[^/]+/preview[^/]*\.(png|jpe?g|gif|webp)$", re.IGNORECASE
)


def _is_template_preview(rel_path: str) -> bool:
    return bool(_TEMPLATE_PREVIEW_RE.match(rel_path.lower()))


def _should_skip(rel_path: str) -> bool:
    """Only ``assets/**`` and ``fonts/**`` files are stored; skip everything else.

    Directories, OS junk, dotfiles, template screenshots and ``preview*`` files
    (reference-only material) are excluded. Template-folder preview thumbnails
    are the exception — the caller checks :func:`_is_template_preview` first.
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


def _strip_token_ident(raw_name: str) -> str:
    """Normalize a token identifier: drop a leading ``--`` and a ``brand-`` namespace.

    So the manifest name ``--brand-core-primary`` and the CSS var ``primary`` (or
    ``--primary``) reduce to the same identifier and dedup to a single token.
    """
    ident = (raw_name or "").strip().lstrip("-")
    if ident.startswith("brand-"):
        ident = ident[len("brand-"):]
    return ident


def _canonicalize_token(
    raw_name: str,
    value: str,
    kind: Optional[str] = None,
    group: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """Resolve a token to a canonical ``(group, name)`` key, or ``None`` if unusable.

    The ONE canonical parser shared by the manifest-token and CSS ``:root`` paths,
    so the same underlying token dedups regardless of source. Group precedence:

    1. An explicit, recognized legacy ``group`` key (kept for backward-compatible
       bundles that carry one; the real Claude-Design manifest does not).
    2. A color sub-group encoded in the name (core/accents/ink/tints).
    3. The manifest ``kind`` (color -> core, font -> type, spacing -> spacing,
       shadow -> shadow).
    4. Inference from the value (CSS-only vars with no ``kind``): color-like ->
       core, otherwise type.

    The name is the stripped identifier, minus a leading color sub-group segment
    when that segment determined the group.
    """
    ident = _strip_token_ident(raw_name)
    if not ident:
        return None

    head, _, rest = ident.partition("-")

    # 1. Explicit, recognized legacy group.
    if group:
        normalized_group = group.strip().lower()
        if normalized_group in _TOKEN_GROUPS:
            name = (
                rest
                if (normalized_group in _COLOR_SUBGROUPS and head == normalized_group and rest)
                else ident
            )
            return normalized_group, name

    # 2. Color sub-group encoded in the name.
    if head in _COLOR_SUBGROUPS:
        return head, (rest or head)

    # 3. Manifest kind.
    if kind:
        mapped = _KIND_TO_GROUP.get(kind.strip().lower())
        if mapped:
            return mapped, ident

    # 4. Infer from the value.
    return ("core" if _looks_like_color(value) else "type"), ident


def _parse_css_root_vars(css_text: str) -> list[tuple[str, str]]:
    """Extract ``(--var-name-without-dashes, value)`` pairs from ``:root`` blocks."""
    pairs: list[tuple[str, str]] = []
    for block in _ROOT_BLOCK_RE.findall(css_text or ""):
        for match in _CSS_VAR_RE.finditer(block):
            pairs.append((match.group(1).strip(), match.group(2).strip()))
    return pairs


# Deliberate app-level decompressed-pixel ceiling (~8k x 8k) shared with the
# thumbnail endpoint's guard: header-declared dimensions past it are treated
# as unusable (a crafted small-bytes/huge-dimensions file must never buy a
# decode anywhere downstream that trusts these recorded dims).
_MAX_DECODE_PIXELS = 64_000_000


def _image_dimensions(data: bytes, mime: str) -> tuple[Optional[int], Optional[int]]:
    """Best-effort intrinsic (width, height); ``(None, None)`` for fonts/SVG/
    failure/absurd header-declared dimensions. Header read only — no decode."""
    if mime == "image/svg+xml" or mime.startswith("font/"):
        return (None, None)
    try:
        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(data)) as im:
            if im.width * im.height > _MAX_DECODE_PIXELS:
                logger.warning(
                    "Asset image declares %dx%d px (> %d ceiling); "
                    "recording no dimensions",
                    im.width,
                    im.height,
                    _MAX_DECODE_PIXELS,
                )
                return (None, None)
            return (im.width, im.height)
    except Exception:
        return (None, None)


class _SizeBudget:
    """Bounds cumulative uncompressed bytes read from a bundle (bomb guard).

    EVERY ``zf.read`` in the importer goes through :meth:`read`/:meth:`read_info`,
    which check the entry's DECLARED uncompressed size (from the zip header)
    against the per-entry (``MAX_ASSET_SIZE_BYTES``) and cumulative-bundle
    (``MAX_BUNDLE_SIZE_BYTES``) limits BEFORE the entry is materialised — so an
    attacker-declared multi-GB manifest/CSS/asset is rejected rather than OOMing
    the worker — then re-check the actual decoded length as a backstop. The
    single running total spans the manifest, CSS sources, and all assets.
    """

    def __init__(self) -> None:
        self.total = 0

    def read(self, zf: zipfile.ZipFile, name: str) -> bytes:
        """Size-checked read by entry name. Raises ``KeyError`` if absent."""
        return self.read_info(zf, zf.getinfo(name))

    def read_info(self, zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
        """Size-checked read for an already-resolved :class:`zipfile.ZipInfo`."""
        self._enforce(info.filename, info.file_size)
        data = zf.read(info)
        self.total += len(data)
        self._enforce(info.filename, 0)  # backstop: re-check actual cumulative
        if len(data) > MAX_ASSET_SIZE_BYTES:
            raise DesignSystemImportError(
                f"Bundle entry '{info.filename}' is too large: {len(data)} bytes "
                f"(max {MAX_ASSET_SIZE_BYTES} per entry)."
            )
        return data

    def _enforce(self, name: str, pending: int) -> None:
        if pending > MAX_ASSET_SIZE_BYTES:
            raise DesignSystemImportError(
                f"Bundle entry '{name}' is too large: {pending} bytes "
                f"(max {MAX_ASSET_SIZE_BYTES} per entry)."
            )
        if self.total + pending > MAX_BUNDLE_SIZE_BYTES:
            raise DesignSystemImportError(
                f"Bundle exceeds the maximum size of {MAX_BUNDLE_SIZE_BYTES} bytes."
            )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def import_bundle(
    db: Session,
    *,
    zip_bytes: bytes,
    user: Optional[str],
    name_override: Optional[str] = None,
    source_filename: Optional[str] = None,
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
        # Reject the WHOLE bundle up-front on ANY zip-slip path or symlink entry —
        # validated globally over every ZipInfo, before/independent of root-prefix
        # scoping, so a malicious entry outside the bundle root is refused (not
        # silently skipped) and symlinks are refused before any bytes are read.
        _assert_bundle_paths_safe(zf)

        # One cumulative memory budget spanning manifest + CSS + asset reads.
        budget = _SizeBudget()
        root_prefix = _locate_root_prefix(zf)
        manifest = _read_manifest(zf, root_prefix, budget)
        name = _resolve_name(
            name_override,
            manifest,
            root_prefix,
            readme_h1=_read_readme_h1(zf, root_prefix, budget),
            source_filename=source_filename,
        )

        # Fail fast on a name clash before doing any expensive work.
        existing = db.query(DesignSystem).filter(DesignSystem.name == name).first()
        if existing:
            raise DesignSystemNameConflictError(
                f"A design system named '{name}' already exists (id={existing.id}). "
                "Choose a different name to import a copy."
            )

        # Read the DECLARED CSS token sources ONCE (budgeted); the same bytes are
        # reused for both token parsing and source-file retention (no double-charge).
        css_sources = _read_css_sources(zf, root_prefix, manifest, budget)
        tokens = _collect_tokens(manifest, _decode_css_texts(css_sources))
        assets, files = _collect_assets_and_files(zf, root_prefix, budget, css_sources)

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
        font_mapping_json=build_font_mapping(manifest),
        version=1,
        published=False,
        is_default=False,
        is_active=True,
    )
    for token in tokens:
        design_system.tokens.append(token)
    for asset in assets:
        design_system.assets.append(asset)
    for ds_file in files:
        design_system.files.append(ds_file)

    db.add(design_system)
    # Flush assigns primary keys so {{ds-asset:ID}} placeholders point at real ids
    # and each asset-reference file row resolves its asset_id.
    db.flush()
    # Materialize addressable template entities (v1 Phase 4) AFTER the flush so
    # the rewritten layout's {{ds-asset:ID}} refs point at real asset ids. Local
    # import: design_system_templates imports this module for nothing, but the
    # deferred import keeps the module graph acyclic-by-construction.
    from src.services.design_system_templates import materialize_templates

    materialize_templates(design_system)
    recompute_compiled_style_content(design_system)
    db.commit()
    db.refresh(design_system)

    logger.info(
        "Imported design system '%s' (id=%s): %d token(s), %d asset(s), %d file(s), "
        "%d template(s)",
        design_system.name,
        design_system.id,
        len(tokens),
        len(assets),
        len(files),
        len(design_system.templates),
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
            # The manifest's OWN path must be safe before its directory is adopted
            # as the bundle root — otherwise '../_ds_manifest.json' or an absolute
            # path would set an escaping root prefix that every other entry is then
            # resolved against. Reject rather than treat as root.
            if _safe_relpath(name) is None:
                raise DesignSystemImportError(
                    f"Bundle manifest is at an unsafe path '{name}' (absolute path "
                    "or parent-directory traversal); refusing to import."
                )
            return name[: -len(MANIFEST_FILENAME)]
    raise DesignSystemImportError(
        f"Bundle is missing its manifest ({MANIFEST_FILENAME}). A design-system "
        "bundle must contain a _ds_manifest.json at its root."
    )


def _read_manifest(zf: zipfile.ZipFile, root_prefix: str, budget: "_SizeBudget") -> dict:
    try:
        raw = budget.read(zf, root_prefix + MANIFEST_FILENAME)
    except KeyError as exc:  # pragma: no cover - guarded by _locate_root_prefix
        raise DesignSystemImportError(f"Bundle is missing {MANIFEST_FILENAME}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise DesignSystemImportError(f"{MANIFEST_FILENAME} is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise DesignSystemImportError(f"{MANIFEST_FILENAME} must be a JSON object.")
    return manifest


_MARKDOWN_H1_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$")


def _read_readme_h1(
    zf: zipfile.ZipFile, root_prefix: str, budget: "_SizeBudget"
) -> Optional[str]:
    """First ATX ``# Heading`` of the bundle's root README.md, or None.

    Budgeted like every other bundle read. Any failure (no README, undecodable
    bytes, no heading) degrades to None — naming falls through to the next
    candidate.
    """
    readme_entry = next(
        (
            info.filename
            for info in zf.infolist()
            if info.filename.startswith(root_prefix)
            and info.filename[len(root_prefix):].lower() == "readme.md"
        ),
        None,
    )
    if not readme_entry:
        return None
    try:
        text = budget.read(zf, readme_entry).decode("utf-8", errors="replace")
    except Exception:
        return None
    for line in text.splitlines():
        match = _MARKDOWN_H1_RE.match(line.strip())
        if match and match.group(1).strip():
            return match.group(1).strip()
    return None


def _resolve_name(
    name_override: Optional[str],
    manifest: dict,
    root_prefix: str,
    *,
    readme_h1: Optional[str] = None,
    source_filename: Optional[str] = None,
) -> str:
    """Default name precedence: explicit override -> manifest ``name`` ->
    README H1 -> uploaded zip filename -> bundle root folder -> constant.
    Every candidate is clamped to the column length."""
    for candidate in (name_override, manifest.get("name"), readme_h1):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:255]
    if source_filename:
        stem = _basename(source_filename)
        if stem.lower().endswith(".zip"):
            stem = stem[:-4]
        if stem.strip():
            return stem.strip()[:255]
    stem = root_prefix.rstrip("/").rsplit("/", 1)[-1] if root_prefix else ""
    return stem[:255] or "Imported Design System"


def _collect_tokens(manifest: dict, css_texts: list[str]) -> list[DesignSystemToken]:
    """Tokens from ``manifest['tokens']`` plus the ``:root`` vars in ``css_texts``.

    Both sources run through :func:`_canonicalize_token`; dedup is SOURCE-AWARE so
    it collapses only genuine restatements, never distinct tokens:

    - Manifest vs manifest: dedup on EXACT ``(group, canonical-name)``. Two
      manifest tokens that share a canonical name and value but sit in DIFFERENT
      groups (legitimate semantic aliases, e.g. ``--brand-core-primary`` and
      ``--brand-accents-primary``) are BOTH kept.
    - CSS vs manifest: a CSS ``:root`` var that RESTATES a manifest token — same
      canonical name AND value — is dropped, so the manifest's authoritative
      ``kind``-derived group wins (this collapses the 72->144 duplication and the
      identical fs-12 spacing/type case). A CSS var that shares a name but has a
      DIFFERENT value is a distinct token and is kept.
    - CSS vs CSS: identical ``(name, value)`` repeats are collapsed.

    ``css_texts`` is pre-decoded by the caller so the CSS bytes are budgeted once
    and reused for retention (no double-charge).
    """
    tokens_out: list[tuple[str, str, str]] = []
    manifest_gn: set[tuple[str, str]] = set()  # (group, name) claimed by the manifest
    manifest_nv: set[tuple[str, str]] = set()  # (name, value) defined by the manifest
    css_nv: set[tuple[str, str]] = set()  # (name, value) already added from CSS

    for entry in manifest.get("tokens") or []:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("name")
        value = entry.get("value")
        if not raw_name or value is None or str(value).strip() == "":
            continue
        value_str = str(value).strip()
        resolved = _canonicalize_token(
            str(raw_name), value_str, entry.get("kind"), entry.get("group")
        )
        if resolved is None:
            continue
        group, name = resolved
        if (group, name) in manifest_gn:
            continue  # exact manifest duplicate
        manifest_gn.add((group, name))
        manifest_nv.add((name, value_str))
        tokens_out.append((group, name, value_str))

    for css_text in css_texts:
        for var_name, value in _parse_css_root_vars(css_text):
            resolved = _canonicalize_token(var_name, value)
            if resolved is None:
                continue
            group, name = resolved
            if (name, value) in manifest_nv:
                continue  # restates a manifest token — manifest's group wins
            if (name, value) in css_nv:
                continue  # identical CSS repeat
            css_nv.add((name, value))
            tokens_out.append((group, name, value))

    return [
        DesignSystemToken(group=group, name=name, value=value)
        for group, name, value in sorted(tokens_out)
    ]


def _declared_css_paths(manifest: dict) -> list[str]:
    """Ordered, de-duplicated, normalized rel-paths of the DECLARED CSS token
    sources: ``globalCssPaths`` plus the conventional ``colors_and_type.css``.

    Only these declared sources are treated as token sources / retained — not
    arbitrary ``.css`` files elsewhere in the bundle. Paths are normalized with
    :func:`_safe_relpath`; an unsafe declared path is dropped.
    """
    raw_paths = list(manifest.get("globalCssPaths") or [])
    raw_paths.append(DEFAULT_CSS_TOKEN_SOURCE)
    paths: list[str] = []
    seen: set[str] = set()
    for path in raw_paths:
        if not isinstance(path, str) or not path.strip():
            continue
        safe = _safe_relpath(path.strip())
        if safe is None or safe in seen:
            continue
        seen.add(safe)
        paths.append(safe)
    return paths


def _read_css_sources(
    zf: zipfile.ZipFile, root_prefix: str, manifest: dict, budget: "_SizeBudget"
) -> "dict[str, bytes]":
    """Read each DECLARED CSS token source ONCE, keyed by its rel path.

    Returns ``{rel_path: raw_bytes}`` for the declared sources actually present in
    the bundle. Reads go through ``budget`` (oversized entries are rejected before
    materialisation); a genuinely-missing path is skipped. The same bytes are
    reused for token parsing AND source-file retention, so a CSS source is charged
    against the size budget exactly once.
    """
    result: dict[str, bytes] = {}
    for path in _declared_css_paths(manifest):
        try:
            result[path] = budget.read(zf, root_prefix + path)
        except KeyError:
            continue  # optional source not present in this bundle
    return result


def _decode_css_texts(css_sources: "dict[str, bytes]") -> list[str]:
    """Decode the pre-read CSS source bytes to UTF-8 text (skip undecodable)."""
    texts: list[str] = []
    for path, raw in css_sources.items():
        try:
            texts.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            logger.warning("Skipping non-UTF-8 CSS token source: %s", path)
    return texts


def _safe_relpath(rel_path: str) -> Optional[str]:
    """Normalize a bundle-relative path; return ``None`` if it is unsafe (zip-slip).

    Rejects absolute paths (POSIX ``/`` or a Windows drive) and any path that
    escapes the bundle root via a ``..`` segment. Backslashes are normalized to
    ``/`` and ``.``/empty segments are collapsed. Assets are stored as DB bytes
    (never written to disk), so this is defence-in-depth — and it keeps the
    persisted ``design_system_file.path`` values safe for the later file browser.
    """
    if not rel_path:
        return None
    normalized = rel_path.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return None
    parts: list[str] = []
    for segment in normalized.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            return None
        parts.append(segment)
    return "/".join(parts) if parts else None


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """True if a zip entry is a symlink (Unix mode ``S_IFLNK`` in ``external_attr``).

    A symlink entry stores its link TARGET as content; if we stored it as an asset
    the bytes would be the target path/data, so such entries are refused outright.
    Windows-created zips have no Unix mode (``external_attr`` high bits 0), which
    correctly reads as "not a symlink".
    """
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _assert_bundle_paths_safe(zf: zipfile.ZipFile) -> None:
    """Reject the WHOLE bundle if ANY entry is a symlink or a zip-slip path.

    Validated GLOBALLY over every ``ZipInfo`` — independent of, and before, any
    root-prefix scoping — so a malicious entry that falls OUTSIDE the bundle root
    (e.g. ``../evil.png`` when the manifest sits under ``safe/``) is REJECTED, not
    silently skipped. EVERY entry is checked (no exemption for empty or ``.``-only
    names): absolute paths, ``..`` traversal, and empty/invalid names are refused,
    and symlink entries are refused before any bytes are read.
    """
    for info in zf.infolist():
        name = info.filename
        if _is_symlink(info):
            raise DesignSystemImportError(
                f"Bundle entry '{name}' is a symlink; refusing to import."
            )
        # No ``if name`` guard: an empty (or ``.``-only) name also fails
        # ``_safe_relpath`` and must be rejected, not skipped.
        if _safe_relpath(name) is None:
            raise DesignSystemImportError(
                f"Bundle contains an unsafe path '{name}' (empty, absolute, or "
                "parent-directory traversal); refusing to import."
            )


def _iter_safe_entries(zf: zipfile.ZipFile, root_prefix: str):
    """Yield ``(ZipInfo, safe_rel_path)`` for every in-scope bundle FILE entry.

    Skips directories, OS junk (``__MACOSX``, ``.DS_Store``) and dotfiles. Raises
    :class:`DesignSystemImportError` on a zip-slip path (absolute or ``..``) so a
    malicious bundle is rejected rather than silently stored.
    """
    for info in zf.infolist():
        name = info.filename
        if not name.startswith(root_prefix):
            continue
        rel_raw = name[len(root_prefix):]
        if not rel_raw or rel_raw.endswith("/"):
            continue  # directory entry
        low = rel_raw.lower()
        if low.startswith("__macosx/") or "/__macosx/" in low:
            continue
        base = _basename(low)
        if base == ".ds_store" or base.startswith("."):
            continue
        safe = _safe_relpath(rel_raw)
        if safe is None:
            raise DesignSystemImportError(
                f"Bundle contains an unsafe path '{rel_raw}' (absolute path or "
                "parent-directory traversal); refusing to import."
            )
        yield info, safe


def _classify_source_file(rel: str) -> Optional[str]:
    """Return the ``design_system_file.kind`` for a retained SOURCE file, else None.

    Retains the human/authoring layer: README.md, SKILL.md, and template layout
    HTML (``templates/*/index.html``). CSS token sources are handled separately by
    the caller (only the DECLARED sources are retained, using bytes already read),
    so ``.css`` is intentionally NOT matched here — arbitrary ``.css`` files
    elsewhere in the bundle are not retained. Callers reach here only for entries
    that are NOT stored as binary assets, so there is no overlap with the
    asset/font reference rows (no double-store).
    """
    low = rel.lower()
    base = _basename(low)
    if base == "readme.md":
        return "readme"
    if base == "skill.md":
        return "skill"
    if low.startswith("templates/") and base == "index.html":
        return "template"
    return None


def build_font_mapping(manifest: dict) -> Optional[dict]:
    """Normalize manifest ``fonts[]`` / ``brandFonts[]`` into a family-keyed mapping.

    Joins the flat ``fonts[]`` variant rows (family + weight/style + files) with the
    ``brandFonts[]`` token linkage (family -> tokens) into one structure so
    downstream typography use never re-parses the manifest::

        {"families": [
            {"family": "Acme Sans",
             "variants": [{"weight": "400", "style": "normal",
                           "files": ["fonts/acme-sans-regular.woff2"]}, ...],
             "tokens": ["font-sans"]},   # canonical token names (--/brand- stripped)
            ...
        ]}

    Families are de-duplicated and everything is sorted for deterministic output.
    Token names are canonicalized with :func:`_strip_token_ident` so they line up
    with ``design_system_token.name``. Returns ``None`` when the manifest declares
    no fonts.
    """
    if not isinstance(manifest, dict):
        return None

    families: dict[str, dict] = {}

    def _family(family_name: str) -> dict:
        return families.setdefault(family_name, {"variants": [], "tokens": set()})

    for entry in manifest.get("fonts") or []:
        if not isinstance(entry, dict):
            continue
        family = (entry.get("family") or "").strip()
        if not family:
            continue
        weight = "" if entry.get("weight") is None else str(entry.get("weight")).strip()
        style = (entry.get("style") or "").strip()
        raw_files = entry.get("files")
        if isinstance(raw_files, str):
            raw_files = [raw_files]
        raw_files = list(raw_files or [])
        # Some manifests carry a single ``path`` instead of a ``files`` list.
        single_path = entry.get("path")
        if isinstance(single_path, str) and single_path.strip():
            raw_files.append(single_path)
        # Normalize + zip-slip-validate every font path so an unsafe declared path
        # (e.g. "../font.woff2") is never persisted; normalized paths line up with
        # the retained design_system_file.path values.
        files = sorted(
            {
                norm
                for item in raw_files
                if isinstance(item, str)
                and item.strip()
                and (norm := _safe_relpath(item.strip())) is not None
            }
        )
        variant = {"weight": weight, "style": style, "files": files}
        variants = _family(family)["variants"]
        if variant not in variants:
            variants.append(variant)

    for entry in manifest.get("brandFonts") or []:
        if not isinstance(entry, dict):
            continue
        family = (entry.get("family") or "").strip()
        if not family:
            continue
        for token in entry.get("tokens") or []:
            if isinstance(token, str) and token.strip():
                _family(family)["tokens"].add(_strip_token_ident(token))

    if not families:
        return None

    return {
        "families": [
            {
                "family": family,
                "variants": sorted(
                    data["variants"], key=lambda v: (v["weight"], v["style"])
                ),
                "tokens": sorted(data["tokens"]),
            }
            for family, data in sorted(families.items())
        ]
    }


def _collect_assets_and_files(
    zf: zipfile.ZipFile,
    root_prefix: str,
    budget: "_SizeBudget",
    css_sources: "dict[str, bytes]",
) -> tuple[list[DesignSystemAsset], list[DesignSystemFile]]:
    """Read a bundle into asset rows + file rows in one safety-checked pass.

    - a DECLARED CSS token source (``css_sources``) -> a ``DesignSystemFile``
      SOURCE row using the bytes ALREADY read for parsing (never re-read/re-charged
      against the budget), so CSS is not double-counted; only declared sources are
      retained (not arbitrary ``.css`` files).
    - ``assets/**`` / ``fonts/**`` -> a ``DesignSystemAsset`` (bytes) AND a
      ``DesignSystemFile`` REFERENCE row (``data`` NULL, linked via ``asset``) so
      the file listing is complete without double-storing the bytes.
    - README / SKILL / template HTML -> a ``DesignSystemFile`` SOURCE row (bytes).
    - everything else (previews, template screenshots, slides, ui_kits, uploads,
      bundle scripts) is skipped.

    One shared ``budget`` spans every read, so each stored byte counts once and the
    per-bundle cap holds.
    """
    assets: list[DesignSystemAsset] = []
    files: list[DesignSystemFile] = []
    seen_paths: set[str] = set()

    for info, rel in _iter_safe_entries(zf, root_prefix):
        if rel in seen_paths:
            continue  # de-dup pathological duplicate arcnames
        seen_paths.add(rel)

        # Declared CSS token source: retain from the already-read (and budgeted)
        # bytes — no second read, no double-charge, and only declared sources.
        if rel in css_sources:
            data = css_sources[rel]
            files.append(
                DesignSystemFile(
                    path=rel,
                    kind="css",
                    mime=_guess_mime(rel),
                    data=data,
                    size_bytes=len(data),
                )
            )
            continue

        if not _should_skip(rel) or _is_template_preview(rel):
            # Storable binary asset: assets/**, fonts/**, or a template folder's
            # preview screenshot (kind ``template_shot`` — thumbnail material for
            # the Phase 4 template picker, excluded from brand-asset search).
            # Size-checked read: the declared size is validated BEFORE
            # materialisation (bomb guard).
            data = budget.read_info(zf, info)
            mime = _guess_mime(rel)
            kind = "template_shot" if _is_template_preview(rel) else _infer_asset_kind(rel)
            width, height = _image_dimensions(data, mime)
            asset = DesignSystemAsset(
                kind=kind,
                filename=_basename(rel),
                mime=mime,
                data=data,
                width=width,
                height=height,
                size_bytes=len(data),
            )
            assets.append(asset)
            # Path-only reference — the bytes are NOT re-stored (no double-store).
            files.append(
                DesignSystemFile(
                    path=rel,
                    kind="font" if kind == "font" else "asset",
                    mime=mime,
                    data=None,
                    size_bytes=len(data),
                    asset=asset,
                )
            )
            continue

        source_kind = _classify_source_file(rel)
        if source_kind:
            data = budget.read_info(zf, info)
            files.append(
                DesignSystemFile(
                    path=rel,
                    kind=source_kind,
                    mime=_guess_mime(rel),
                    data=data,
                    size_bytes=len(data),
                )
            )

    return assets, files


# ---------------------------------------------------------------------------
# Asset retrieval (used by the {{ds-asset:ID}} resolver + serve endpoint)
# ---------------------------------------------------------------------------


def get_asset_base64(
    db: Session, asset_id: int, *, design_system_id: Optional[int]
) -> tuple[str, str]:
    """Return ``(base64_data, mime)`` for a stored design-system asset, scoped to
    its owning design system.

    Mirrors ``image_service.get_image_base64`` so the ``{{ds-asset:ID}}`` resolver
    embeds bytes exactly the way ``{{image:ID}}`` does — but the fetch is filtered
    on ``(id AND design_system_id)``, never on a bare global id. This is the
    confused-deputy guard: a ``{{ds-asset:<foreign_id>}}`` handle (e.g. a crafted
    bundle's template referencing another system's asset id) must not resolve to
    that other system's bytes. ``design_system_id`` is mandatory and keyword-only
    so every caller makes the scope explicit.

    ``design_system_id=None`` is FAIL-CLOSED: the column is ``NOT NULL``, so the
    ``IS NULL`` filter matches no row and the asset is reported not-found. A deck
    with no active design system therefore resolves NO brand asset by bare id.
    """
    asset = (
        db.query(DesignSystemAsset)
        .filter(
            DesignSystemAsset.id == asset_id,
            DesignSystemAsset.design_system_id == design_system_id,
        )
        .first()
    )
    if not asset:
        raise ValueError(
            f"Design system asset {asset_id} not found in design system {design_system_id}"
        )
    return base64.b64encode(asset.data).decode("utf-8"), asset.mime


# ---------------------------------------------------------------------------
# Brand-asset search (backs the ``search_brand_assets`` generation tool)
# ---------------------------------------------------------------------------

# Brand-image importance order for the tool's no-filter fallback (spec §4 Core
# Asset Protocol: logo first, then lockups, icons, illustrations, backgrounds).
# Unknown/other image kinds sort AFTER these but are still returned — this is a
# denylist (below), not an allowlist, so a novel brand-image kind still surfaces.
# Results are ranked by this order in EVERY case, so the output is deterministic.
_ASSET_IMPORTANCE_ORDER = ("logo", "lockup", "icon", "illustration", "background")

# Kinds the tool NEVER surfaces: fonts are wired inline via @font-face in the
# compiled prompt (not fetched on demand), and ``template_shot`` is reference-only
# preview material tied to templates, never embeddable slide content.
_TOOL_EXCLUDED_ASSET_KINDS = frozenset(("font", "template_shot"))


def _asset_search_sort_key(asset: Any) -> tuple[int, str, int]:
    """Rank by brand importance, then filename + id for a stable total order.

    ``asset`` is a ``DesignSystemAsset``; it is typed ``Any`` (as the compiler does
    for ORM records) so attribute reads aren't flagged against the SQLAlchemy
    ``Column`` descriptors — this repo runs mypy without the SQLAlchemy plugin.
    """
    kind = (asset.kind or "").lower()
    try:
        rank = _ASSET_IMPORTANCE_ORDER.index(kind)
    except ValueError:
        rank = len(_ASSET_IMPORTANCE_ORDER)
    return (rank, asset.filename or "", asset.id or 0)


def search_assets(
    db: Session,
    design_system_id: int,
    query: Optional[str] = None,
    kind: Optional[str] = None,
) -> list[DesignSystemAsset]:
    """Return a design system's brand IMAGE assets, optionally filtered + ranked.

    Backs the ``search_brand_assets`` generation tool. Rows are scoped to
    ``design_system_id`` and never include fonts (delivered inline via @font-face)
    or ``template_shot`` (reference-only preview material). Optional filters:

    - ``kind``: case-insensitive exact match on the asset kind.
    - ``query``: case-insensitive substring match on the filename.

    When NEITHER filter is given, the full brand-image inventory is returned as a
    sensible RANKED default set (importance order: logo, lockup, icon,
    illustration, background; unknown image kinds last) so a loose call still
    yields useful assets. Results are ranked by that same order (then filename,
    id) in every case, so the output is deterministic. The binary ``data`` column
    is deferred — a metadata search never loads asset bytes.
    """
    rows = (
        db.query(DesignSystemAsset)
        .filter(DesignSystemAsset.design_system_id == design_system_id)
        # Defer the bytea column: a metadata search never needs the asset bytes.
        # ``# type: ignore`` covers the SQLAlchemy Column-vs-attribute stubs gap
        # (this repo runs mypy without the SQLAlchemy plugin).
        .options(defer(DesignSystemAsset.data))  # type: ignore[arg-type]
        .all()
    )
    result = [a for a in rows if (a.kind or "").lower() not in _TOOL_EXCLUDED_ASSET_KINDS]
    if kind:
        kind_l = kind.strip().lower()
        result = [a for a in result if (a.kind or "").lower() == kind_l]
    if query:
        query_l = query.strip().lower()
        result = [a for a in result if query_l in (a.filename or "").lower()]
    result.sort(key=_asset_search_sort_key)
    return result
