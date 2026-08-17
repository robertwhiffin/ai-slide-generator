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
  under ``assets/`` are reference-only and skipped; a template folder's screenshot
  IS stored (kind ``template_shot``, v1 Phase 4) so the template picker can serve
  thumbnails. Both shipped shapes count: ``templates/<folder>/preview.<ext>`` and
  the DOT-PREFIXED, EXTENSION-LESS ``templates/<folder>/.thumbnail`` a real export
  writes — the latter is allowlisted past the general dotfile skip and has its
  media type SNIFFED from its magic bytes (unknown content is refused, never
  stored under a guessed type).

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
import struct
import unicodedata
import zipfile
from typing import Any, NamedTuple, Optional

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


class BundleImportWarning(NamedTuple):
    """A bundle entry the import DROPPED without failing the upload.

    Some entries are individually unusable without making the bundle unusable — an
    unsniffable template screenshot, a CSS token source that is not UTF-8. Dropping
    just that entry is right (one junk file must not cost the whole upload), but the
    caller was then told the import succeeded with nothing to say a file had been
    ignored, so the only record was a server-side log the user cannot see. These ride
    back on the import response instead.
    """

    path: str
    reason: str


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
    ``name (unique)``) over LIVE rows only — a name held solely by a soft-deleted
    tombstone is free, which is what makes delete-then-re-import work. The caller
    may supply a different name to import a copy of a system that is still live.
    """


#: Maximum size of a btree index tuple in PostgreSQL (version 4 btrees). A UNIQUE
#: index over ``design_system.name`` cannot hold an entry larger than this.
_BTREE_MAX_INDEX_ROW_BYTES = 2704

#: Bytes of that maximum the index tuple's own header consumes, so the largest NAME
#: that fits is this much smaller. Measured against a live PostgreSQL 14 by binary
#: search, and quoted to the user only as ADVICE — the database, not this number,
#: decides (see :func:`translate_name_index_limit_error`).
_INDEX_TUPLE_OVERHEAD_BYTES = 12

#: Practical ceiling on a design-system name, for the user-facing message.
MAX_INDEXABLE_NAME_BYTES = _BTREE_MAX_INDEX_ROW_BYTES - _INDEX_TUPLE_OVERHEAD_BYTES

#: PostgreSQL class 54 — "program limit exceeded"; 54000 is what an oversized btree
#: index tuple raises. Matched on the SQLSTATE rather than the message where the
#: driver exposes it, since the message is localizable and version-dependent.
_PROGRAM_LIMIT_EXCEEDED_SQLSTATE = "54000"

#: Fragments identifying the same condition when no SQLSTATE is available (a
#: non-psycopg driver, or an error already flattened to a string).
_INDEX_ROW_SIZE_MARKERS = (
    "index row size",
    "index row requires",
    "btree version",
    "values larger than 1/3 of a buffer page",
)


class DesignSystemNameTooLongError(ValueError):
    """The name overflowed the UNIQUE index on ``design_system.name``.

    Routes map this to HTTP 400. It is raised in REACTION to the database refusing
    the write, never in anticipation of it.
    """


def _is_name_index_limit_error(exc: BaseException) -> bool:
    """True when *exc* is Postgres refusing to index an oversized name.

    Checks the SQLSTATE on the driver exception (and on any ``orig`` SQLAlchemy
    wrapped), falling back to message markers for drivers that expose no code.
    """
    seen: set[int] = set()
    candidate: Optional[BaseException] = exc
    while candidate is not None and id(candidate) not in seen:
        seen.add(id(candidate))
        code = getattr(candidate, "pgcode", None) or getattr(candidate, "sqlstate", None)
        if code == _PROGRAM_LIMIT_EXCEEDED_SQLSTATE:
            return True
        candidate = getattr(candidate, "orig", None) or candidate.__cause__

    message = str(exc).lower()
    return any(marker in message for marker in _INDEX_ROW_SIZE_MARKERS)


def translate_name_index_limit_error(exc: BaseException, *, name: Optional[str]) -> None:
    """Re-raise *exc* as :class:`DesignSystemNameTooLongError` if that is what it is.

    THE DATABASE IS THE AUTHORITY. ``design_system.name`` is unbounded ``TEXT``
    (brand text is never capped or truncated) covered by a unique index, so it is
    backed by a btree whose per-entry tuple cannot exceed
    :data:`_BTREE_MAX_INDEX_ROW_BYTES`. Whether a given name fits is Postgres's
    determination, made when the row is written; this function's only job is to
    notice that determination and say something actionable about it. A caller wraps
    its write and calls this from the ``except``.

    This REPLACES a predictor. The previous version ran ``zlib.compress`` as a
    stand-in for pglz and refused a name whose compressed size still exceeded the
    limit — reasoning that both are LZ77-family, so what zlib cannot shrink pglz
    cannot either. The premise does not hold: a btree key is NOT pglz-compressed into
    the index, so the compressed size of the name has no bearing on the size of the
    index tuple. Measured against a live PostgreSQL, the guard passed 2700-, 3000- and
    3500-byte names that Postgres then rejected — producing exactly the HTTP 500 it
    existed to prevent — and it was never called on the create or rename paths at all.
    Reaction has no equivalent failure mode: whatever the server's page size, btree
    version or collation, the error it actually raises is the error translated here.

    The name is never TRUNCATED to make it fit. Storing a brand under a name it did
    not choose is worse than refusing the write, and the caller can retry with a
    shorter one.
    """
    if not _is_name_index_limit_error(exc):
        return
    measured = f" (it is {len(name.encode('utf-8'))} bytes)" if name else ""
    raise DesignSystemNameTooLongError(
        f"The design system name is too long to index uniquely{measured}. The "
        f"database limits a unique name to roughly {MAX_INDEXABLE_NAME_BYTES} bytes; "
        "use a shorter name (the brand's own text is stored uncapped everywhere "
        "else, and is never truncated)."
    ) from exc


#: The partial unique index that actually decides name uniqueness over LIVE rows
#: (see the ``DesignSystem`` model). Matched by NAME so this translation stays
#: specific to it: any OTHER integrity violation must keep its own identity.
_ACTIVE_NAME_INDEX = "uq_design_system_name_active"

#: PostgreSQL ``unique_violation``. Matched on the SQLSTATE rather than the message
#: where the driver exposes it, since the message is localizable.
_UNIQUE_VIOLATION_SQLSTATE = "23505"

#: How SQLite reports the SAME rule. It names the COLUMN rather than the index, and
#: this is the only unique index over ``design_system.name``, so the two are
#: equivalent — which is what lets the unit suite (SQLite) cover this at all.
_SQLITE_ACTIVE_NAME_MARKER = "unique constraint failed: design_system.name"


def _is_active_name_conflict_error(exc: BaseException) -> bool:
    """True when *exc* is the active-name index refusing a duplicate name.

    Walks the exception chain the same way :func:`_is_name_index_limit_error` does.
    A unique violation that names a DIFFERENT constraint returns False immediately
    rather than falling through to the message check — a positive identification of
    someone else's constraint is not a maybe.
    """
    seen: set[int] = set()
    candidate: Optional[BaseException] = exc
    while candidate is not None and id(candidate) not in seen:
        seen.add(id(candidate))
        code = getattr(candidate, "pgcode", None) or getattr(candidate, "sqlstate", None)
        if code == _UNIQUE_VIOLATION_SQLSTATE:
            constraint = getattr(getattr(candidate, "diag", None), "constraint_name", None)
            if constraint:
                return constraint == _ACTIVE_NAME_INDEX
        candidate = getattr(candidate, "orig", None) or candidate.__cause__

    message = str(exc).lower()
    return _ACTIVE_NAME_INDEX in message or _SQLITE_ACTIVE_NAME_MARKER in message


def translate_name_conflict_error(exc: BaseException, *, name: Optional[str]) -> None:
    """Re-raise *exc* as :class:`DesignSystemNameConflictError` if that is what it is.

    THE DATABASE IS THE AUTHORITY — the same doctrine as
    :func:`translate_name_index_limit_error`, applied to the other thing this index
    decides. The fail-fast SELECT in :func:`import_bundle` is a pre-check, not a
    lock: two importers of one name both pass it, and the loser meets
    ``uq_design_system_name_active`` only at its write. Untranslated, that
    ``UniqueViolation`` reaches the route's generic handler as an opaque 500, where
    the sequential path returns a precise 409 — a wrong status code and an
    unactionable message on a race a user hits by double-clicking Import.

    Scoped to THIS index by name. A unique violation on any other constraint, and
    every other class of integrity error, passes straight through so the caller's
    own ``raise`` still surfaces it — mislabelling those as a name conflict would
    send the caller off to rename something that is not the problem.

    Unlike the pre-check's message this one cannot name the winner's id: the
    transaction is already aborted, so there is nothing left to query.
    """
    if not _is_active_name_conflict_error(exc):
        return
    labelled = f" named '{name}'" if name else ""
    raise DesignSystemNameConflictError(
        f"A design system{labelled} already exists. Choose a different name to "
        "import a copy."
    ) from exc


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
#
# Anchored with ``\Z``, NOT ``$``: in Python ``$`` matches at the end of the string
# OR immediately before a single trailing newline, so a ``$``-anchored allowlist on
# a PATH accepts ``<allowed shape>\n`` — ``templates/x/preview.png\n`` was matched,
# stored, and served. ``\Z`` is the true end of string. Applies to every allowlist
# regex in this module that judges a path or a filename.
_TEMPLATE_PREVIEW_RE = re.compile(
    r"^templates/[^/]+/preview[^/]*\.(png|jpe?g|gif|webp)\Z", re.IGNORECASE
)

# The SAME screenshot as it actually ships in a real export: DOT-PREFIXED, named
# ``thumbnail`` rather than ``preview``, and carrying NO file extension —
# ``templates/<folder>/.thumbnail``. Every one of those was discarded, so a real
# bundle imported with no thumbnail at all and a NULL ``thumbnail_url``.
#
# Deliberately the NARROWEST path shape that describes them: exactly one folder
# segment under ``templates/``, an optional single leading dot, one of the two
# known basenames, and NOTHING else — no extension, no suffix. It is this
# tightness that makes it safe for :func:`_iter_safe_entries` to exempt a match
# from the general dotfile skip; a dotfile anywhere else stays skipped. Because
# a match carries no extension, its media type is NOT guessable from the name and
# is sniffed from the content instead (:func:`_sniff_raster_mime`).
# ``\Z`` for the same reason as _TEMPLATE_PREVIEW_RE: with ``$`` this accepted
# ``templates/x/.thumbnail\n``, which was then stored AND linked as a template's
# thumbnail_url.
_TEMPLATE_THUMBNAIL_RE = re.compile(
    r"^templates/[^/]+/\.?(thumbnail|preview)\Z", re.IGNORECASE
)

# Magic-byte signatures for the raster formats a template thumbnail may be. An
# extension-less file is stored ONLY if its bytes match one of these; unknown
# content is refused rather than persisted under a guessed content type. SVG is
# absent on purpose (it can carry inline script and has no magic number).
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF_MAGICS = (b"GIF87a", b"GIF89a")


def _sniff_raster_mime(data: bytes) -> Optional[str]:
    """MIME type from an image's MAGIC BYTES, or ``None`` if not a known raster.

    Content-based detection for files whose name carries no extension. WebP is a
    RIFF container, so ``RIFF`` alone is not enough — the form type at bytes 8:12
    must spell ``WEBP``, otherwise a RIFF/WAVE file would be stored as an image.
    """
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if data.startswith(_GIF_MAGICS):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _is_template_thumbnail(rel_path: str) -> bool:
    """True for an EXTENSION-LESS template screenshot (``templates/x/.thumbnail``).

    Distinguished from :func:`_is_template_preview` because the absence of an
    extension is what forces content sniffing.
    """
    return bool(_TEMPLATE_THUMBNAIL_RE.match(rel_path.lower()))


def _is_template_preview(rel_path: str) -> bool:
    """True for a template folder's screenshot in EITHER shipped shape."""
    low = rel_path.lower()
    return bool(_TEMPLATE_PREVIEW_RE.match(low)) or bool(
        _TEMPLATE_THUMBNAIL_RE.match(low)
    )


def _should_skip(rel_path: str) -> bool:
    """Only ``assets/**`` and ``fonts/**`` files are stored; skip everything else.

    Directories, OS junk, dotfiles, template screenshots and ``preview*`` files
    (reference-only material) are excluded. Template-folder screenshots are the
    exception — the caller checks :func:`_is_template_preview` first.

    NOTE: this is not the FIRST gate an entry passes. ``_iter_safe_entries`` runs
    upstream and applies its own dotfile skip, so a dot-prefixed screenshot has to
    be allowlisted THERE as well or it never reaches this function at all.
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
    """Resolve a token to a ``(group, name)`` key, or ``None`` if unusable.

    The ONE canonical parser shared by the manifest-token and CSS ``:root`` paths,
    so the same underlying token dedups regardless of source. Group precedence:

    1. An explicit ``group`` the author supplied. A RECOGNIZED one is normalized to
       its canonical spelling; ANY OTHER is preserved VERBATIM — casing AND
       whitespace (see below).
    2. A color sub-group encoded in the name (core/accents/ink/tints).
    3. The manifest ``kind`` (color -> core, font -> type, spacing -> spacing,
       shadow -> shadow).
    4. Inference from the value (CSS-only vars with no ``kind``): color-like ->
       core, otherwise type.

    An UNRECOGNIZED explicit group used to fall through to rules 2-4, which
    REPLACED the author's group with an inferred one — so a token could not be
    persisted with its group intact, and a design system that files its tokens under
    its own vocabulary had that vocabulary silently rewritten at import. Rules 2-4
    exist to INFER a group when none was given; running them over a group that WAS
    given is not inference, it is overwriting brand data.

    So an explicit group is now always honored. The compiler already handles any
    group name — it aliases known synonyms onto canonical groups and emits the rest
    under a role-less generic heading, dropping nothing — so preserving the author's
    string costs nothing downstream and is what makes "every token persists with its
    group" true.

    Stripping is used for the LOOKUP KEY and the EMPTINESS CHECK ONLY, never for the
    value returned. That split is the same one the compiler applies internally
    (``design_system_compiler._resolve_group`` normalizes its grouping key while
    ``_authored_group_labels`` records the spelling verbatim), and it has to hold at
    BOTH boundaries: returning ``group.strip()`` here destroyed the authored padding
    before any row was written, so the compiler was faithfully preserving whitespace
    that no longer existed by the time it ran — the fix was real and unobservable
    through the actual upload path. A group that is nothing BUT whitespace still
    falls through to inference, because it names nothing to preserve.

    The name is the stripped identifier, minus a leading color sub-group segment
    when that segment determined the group.
    """
    ident = _strip_token_ident(raw_name)
    if not ident:
        return None

    head, _, rest = ident.partition("-")

    # 1. Explicit group supplied by the author.
    if group and group.strip():
        normalized_group = group.strip().lower()
        if normalized_group in _TOKEN_GROUPS:
            name = (
                rest
                if (normalized_group in _COLOR_SUBGROUPS and head == normalized_group and rest)
                else ident
            )
            return normalized_group, name
        # Unrecognized: PRESERVE it verbatim — casing AND whitespace. It is the
        # author's own label, and the compiler normalizes for grouping itself.
        # Falling through here is what discarded it entirely; returning
        # ``group.strip()`` then discarded the authored PADDING, which made the
        # compiler's whitespace fidelity unobservable in production because this
        # boundary had already destroyed the spacing upstream of it.
        return group, ident

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
    warnings: Optional[list[BundleImportWarning]] = None,
) -> DesignSystem:
    """Import a ``.zip`` design-system bundle into Lakebase and compile it.

    Returns the persisted :class:`DesignSystem` (committed, with tokens + assets +
    ``compiled_style_content``).

    Args:
        warnings: optional collector. Pass a list to receive an
            :class:`BundleImportWarning` for every entry the import DROPPED without
            failing — the caller can then tell the user which files were ignored and
            why. Omitting it keeps the previous signature working for the many
            callers that only want the design system.

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

        # Whether the UNIQUE index can hold this name is Postgres's call, made at the
        # commit below; predicting it here was measurably wrong (see
        # translate_name_index_limit_error).
        #
        # Fail fast on a name clash before doing any expensive work.
        #
        # Scoped to LIVE rows to MATCH the partial unique index
        # ``uq_design_system_name_active`` (see the DesignSystem model). Unscoped, this
        # pre-check saw the tombstone a soft DELETE leaves behind — a row the list
        # endpoint hides — and refused every re-import of a name the user had just
        # deleted, permanently. The filter and the index are one change: filtering here
        # WITHOUT the partial index turns this clean 409 into an IntegrityError 500 at
        # the commit below, and the index without this filter would raise that 500
        # instead of a 409 for a genuine live clash.
        existing = (
            db.query(DesignSystem)
            .filter(DesignSystem.name == name, DesignSystem.is_active == True)  # noqa: E712
            .first()
        )
        if existing:
            raise DesignSystemNameConflictError(
                f"A design system named '{name}' already exists (id={existing.id}). "
                "Choose a different name to import a copy."
            )

        # Read the DECLARED CSS token sources ONCE (budgeted); the same bytes are
        # reused for both token parsing and source-file retention (no double-charge).
        css_sources = _read_css_sources(zf, root_prefix, manifest, budget)
        tokens = _collect_tokens(manifest, _decode_css_texts(css_sources, warnings))
        assets, files = _collect_assets_and_files(
            zf, root_prefix, budget, css_sources, warnings
        )

    # Stored VERBATIM; the strip decides only whether the brand wrote a description
    # at all (a whitespace-only one describes nothing, so it stays NULL). Same split
    # as the token group and the name above — normalize the check, never the value.
    raw_description = manifest.get("description")
    description = (
        raw_description
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
    # and each asset-reference file row resolves its asset_id. It is also where the
    # UNIQUE index on ``name`` first has to hold the value, so an unindexable name
    # surfaces HERE — as the database's own error, translated into the 4xx the route
    # already maps rather than escaping as an opaque 500.
    try:
        db.flush()
    except Exception as exc:
        translate_name_index_limit_error(exc, name=name)
        # The pre-check above is not a lock: a CONCURRENT importer of the same name
        # can have committed between that SELECT and this write, and then the partial
        # unique index is what refuses us. Translated to the same 409 the sequential
        # path returns, instead of escaping as an opaque 500.
        translate_name_conflict_error(exc, name=name)
        raise
    # Materialize addressable template entities (v1 Phase 4) AFTER the flush so
    # the rewritten layout's {{ds-asset:ID}} refs point at real asset ids. Local
    # import: design_system_templates imports this module for nothing, but the
    # deferred import keeps the module graph acyclic-by-construction.
    from src.services.design_system_templates import materialize_templates

    materialize_templates(design_system)
    recompute_compiled_style_content(design_system)
    # The flush above normally raises first, but the index is only DEFINITELY
    # exercised at the commit (a deferrable constraint, a different flush order), so
    # the same translation guards both rather than assuming which one fires.
    try:
        db.commit()
    except Exception as exc:
        translate_name_index_limit_error(exc, name=name)
        translate_name_conflict_error(exc, name=name)
        raise
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
                    f"Bundle manifest is at an unsafe path {name!r}: it is absolute "
                    f"or escapes the bundle with a '..' segment. {_REARCHIVE_ADVICE}"
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


#: An ATX H1 line, split into MARKDOWN SYNTAX and authored CONTENT.
#:
#: SYNTAX — consumed, because it is markup the brand did not author as text: any
#: indentation before the ``#``, the ``#`` itself, the ONE whitespace character that
#: makes the line a heading rather than a ``#hashtag``, and an optional closing ``#``
#: run at the end of the line.
#:
#: CONTENT — everything else, captured VERBATIM. The group is bounded by ``$`` with no
#: ``\s*`` adjacent to it, so a heading's own leading/trailing padding is CONTENT and
#: reaches the caller intact, in any Unicode whitespace class.
#:
#: The previous pattern (``^#\s+(.+?)\s*#*\s*$``, matched against a ``.strip()``-ed
#: line, with a third ``.strip()`` on the captured group) destroyed that padding: the
#: ``\s+`` delimiter was GREEDY, so it swallowed every space the author put before the
#: title, and the lazy ``.+?`` surrendered every space after it to ``\s*``. The loss is
#: PERMANENT rather than cosmetic, because this candidate is stored as
#: ``design_system.name``.
#:
#: WHAT LINES MATCH IS UNCHANGED — deliberately, so no bundle's naming falls through
#: differently than before. The delimiter is still ``\s`` (Python's Unicode class, so
#: an EM SPACE after the ``#`` still opens a heading, as it did), still requires at
#: least one character, and the ``#`` run is still a single ``#`` (H1 only, per this
#: module's contract). Only the CONTENT BOUNDARY moved: exactly one delimiter
#: character is syntax, and the rest belongs to the brand.
#:
#: The closing ``#`` run must be preceded by whitespace to count as a delimiter, which
#: is what CommonMark requires — so ``# Title #`` drops it, while ``# Title#`` keeps
#: the ``#`` as the authored content it is.
_MARKDOWN_H1_RE = re.compile(r"^\s*#\s(.*?)(?:[ \t]+#+[ \t]*)?$")


def _read_readme_h1(
    zf: zipfile.ZipFile, root_prefix: str, budget: "_SizeBudget"
) -> Optional[str]:
    """First ATX ``# Heading`` of the bundle's root README.md, VERBATIM, or None.

    Budgeted like every other bundle read. Any failure (no README, undecodable
    bytes, no heading) degrades to None — naming falls through to the next
    candidate.

    THE HEADING CONTENT IS AUTHORED BRAND TEXT and is returned exactly as written,
    including leading/trailing whitespace of ANY Unicode class (EM SPACE, NBSP,
    IDEOGRAPHIC SPACE). This candidate becomes ``design_system.name``, so editing it
    here destroys the brand's own title in storage — the same silent edit
    :func:`_resolve_name` stopped committing for the manifest name and the upload
    override, arriving by a different route.

    Normalization is confined to the two places it decides something rather than
    changes something: the line's own trailing LINE TERMINATOR (a file-format
    artifact, not authored padding, removed so a heading is recognizable at all) and
    the EMPTINESS CHECK below, where a heading that is nothing but whitespace states
    no title and must fall through to the next candidate.
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
    # ``splitlines`` already removes the line TERMINATOR however it is spelled
    # (CRLF included), so no ``.strip()`` is needed to recognize a heading — and a
    # ``.strip()`` here would silently take the authored padding with it.
    for line in text.splitlines():
        match = _MARKDOWN_H1_RE.match(line)
        if not match:
            continue
        heading = match.group(1)
        # STRIPPED ONLY TO DECIDE, never to store: a heading that is nothing but
        # whitespace names nothing, so keep looking. What is RETURNED is the
        # brand's own text.
        if heading.strip():
            return heading
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

    NEVER TRUNCATES. Every candidate used to be clamped to ``[:255]`` to match the
    old column width, which stored the brand under a name it never chose and gave no
    signal that it had happened — strictly worse than rejecting the import, because
    the loss was invisible. ``design_system.name`` is now unbounded ``Text``, so the
    clamp had no purpose left; it is removed rather than raised, since any number
    would reintroduce the same silent edit for a longer name.

    NEVER EDITS THE AUTHORED TEXT EITHER. Whitespace used to be stripped from the
    winning candidate on the grounds that it "normalizes a candidate" — but the
    candidate IS the stored value, so that was the same silent edit as the truncation
    above, in miniature: a brand that titled its system ``"  Acme  "`` was stored
    under a title it did not write, and the rename endpoint (which assigns
    ``request.name`` unstripped) preserved the very same text the importer edited.
    Stripping decides only WHETHER a candidate has content; what gets returned is
    what the brand wrote.

    The PATH-derived candidates (zip filename, bundle root folder) are the exception
    and stay normalized — a filesystem name is not authored prose, and its padding is
    an artifact of the filesystem rather than a brand's choice.

    The constant fallback still applies when no candidate yields anything.
    """
    for candidate in (name_override, manifest.get("name"), readme_h1):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    if source_filename:
        stem = _basename(source_filename)
        if stem.lower().endswith(".zip"):
            stem = stem[:-4]
        if stem.strip():
            return stem.strip()
    stem = root_prefix.rstrip("/").rsplit("/", 1)[-1] if root_prefix else ""
    return stem or "Imported Design System"


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


def _decode_css_texts(
    css_sources: "dict[str, bytes]",
    warnings: "Optional[list[BundleImportWarning]]" = None,
) -> list[str]:
    """Decode the pre-read CSS source bytes to UTF-8 text (skip undecodable)."""
    texts: list[str] = []
    for path, raw in css_sources.items():
        try:
            texts.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            logger.warning("Skipping non-UTF-8 CSS token source: %s", path)
            if warnings is not None:
                warnings.append(
                    BundleImportWarning(
                        path,
                        "not valid UTF-8; its design tokens were not read.",
                    )
                )
    return texts


# The verdict reached for one zip entry.
_ENTRY_REFUSE = "refuse"  # unsafe — reject the whole bundle
_ENTRY_SKIP = "skip"      # legitimate but never stored (directory, OS junk, dotfile)
_ENTRY_FILE = "file"      # store it, under the canonical path returned alongside


class _EntryVerdict(NamedTuple):
    """What to do with one bundle entry — and, if refused, what to tell the user.

    ``path`` and ``reason`` are empty rather than ``None`` when they do not apply:
    an ``_ENTRY_FILE`` verdict always carries a non-empty canonical path and an
    ``_ENTRY_REFUSE`` verdict always carries a reason, so no caller has to narrow an
    Optional that cannot in fact be ``None``.
    """

    kind: str
    path: str = ""    # canonical stored path; non-empty only for _ENTRY_FILE
    reason: str = ""  # the defect, in the user's terms; non-empty only for REFUSE


# Why a path is refused, phrased for someone who has never seen this code. A
# refusal that says only "non-canonical" names a category the user cannot map to
# anything they can change.
_REASON_EMPTY = "it has an empty name"
_REASON_CONTROL = (
    "it contains a control character (a newline, tab or NUL byte, for instance)"
)
_REASON_BIDI = (
    "it contains a bidirectional text control, which can make the name RENDER as a "
    "different one than it is (a '.svg' that displays as '.png', for instance)"
)
_REASON_SURROGATE = "it contains an unpaired surrogate character, which is not text"
_REASON_BACKSLASH = (
    "it uses '\\' as a path separator. Only '/' is a separator in a .zip, so this "
    "name is ambiguous: it would have to be rewritten to be interpreted, and this "
    "importer validates names rather than rewriting them"
)
_REASON_NAME_MISMATCH = (
    "the archive declares a name for this entry that does not match the name the zip "
    "reader resolves for it, so the entry has TWO identities and there is no single "
    "name that can be both validated and stored. A NUL byte in the name does this "
    "(readers truncate at it, so 'thumbnail\\x00.exe' is read as 'thumbnail'), and so "
    "does an Info-ZIP Unicode Path extra field that disagrees with the central "
    "directory"
)
_REASON_CORRUPT_EXTRA = (
    "its Info-ZIP Unicode Path extra field (0x7075) is malformed, so the name the "
    "archive means to declare for this entry cannot be read at all"
)
_REASON_LOCAL_HEADER = (
    "its local file header — the second place a .zip records an entry's name — cannot "
    "be read, so whether the archive states one name for this entry or two cannot be "
    "established"
)
# Distinct from :data:`_REASON_EMPTY`, which is about a name that IS empty everywhere.
# This one is about a name the ARCHIVE leaves empty while the reader resolves a usable
# one from an extra field — so the message has to name both halves, or it reads as a
# complaint about a name the user can see is not empty.
_REASON_EMPTY_RECORDED_NAME = (
    "the archive records NO name for this entry at all. An empty central-directory "
    "name is not a legitimate archive member, and it is not harmless either: an "
    "Info-ZIP Unicode Path extra field can supply a replacement (its checksum matches "
    "an empty name trivially), so the entry ends up with a name that was never "
    "recorded for it"
)
_REASON_ABSOLUTE = (
    "it is an absolute path, so it names a location outside the bundle rather than "
    "a file inside it"
)
_REASON_DRIVE = (
    "it starts with a Windows drive letter, so it names a location outside the "
    "bundle rather than a file inside it"
)
# NOT "would place the file outside the bundle": 'assets/../logo.svg' resolves back
# INSIDE it. The defect is that the name is not the plain relative path of the file
# it names, so it can only be judged by resolving it — and resolving is the
# rewriting this importer refuses to do. Some '..' paths do escape; the reason has
# to be true of ALL of them.
_REASON_TRAVERSAL = (
    "it contains a parent-directory ('..') segment, so which file it names can only "
    "be worked out by resolving the path rather than read from it — and a '..' can "
    "also lead outside the bundle entirely"
)

# The non-canonical SPELLINGS. Each names the spelling itself, not the category, so
# the user can find it in their archive: "non-canonical" is not something anyone can
# act on.
_REASON_EMPTY_SEGMENT = (
    "it contains an empty segment (a doubled '//'), so it is not the plain relative "
    "path of the file it names"
)
_REASON_DOT_PREFIX = (
    "it is spelled with a leading './' instead of as a plain relative path"
)
_REASON_DOT_SEGMENT = (
    "it contains a '.' (current-directory) segment, so it is not the plain relative "
    "path of the file it names — and a trailing '.' names a DIRECTORY, not a file"
)

# What to DO about it. Every path refusal ends with this, so the message closes on
# an action rather than on a classification. The tar-family case is called out by
# name because it is the one that produces a whole archive of './'-prefixed entries
# from a bundle that was fine before it was re-archived.
_REARCHIVE_ADVICE = (
    "Upload the .zip exactly as the design-system export produced it — its entries "
    "are already plain relative paths. If you must re-create the archive, do it from "
    "inside the bundle folder with 'cd <bundle-folder> && zip -r bundle.zip .': a "
    "tar-family re-archive such as 'bsdtar -a -cf bundle.zip -C <bundle-folder> .' "
    "prefixes EVERY entry with './', which is refused, as are '..' segments, "
    "absolute paths, drive letters, '\\' separators and control characters in a name."
)

# A dotfile is SKIPPED rather than refused, and the user is TOLD. See
# :func:`_classify_bundle_entry` for why this one class of junk is not fatal.
_REASON_DOTFILE_SKIPPED = (
    "it is a dot-prefixed file, which this importer does not store (the one "
    "exception is a template folder's '.thumbnail' screenshot); it was ignored and "
    "the rest of the bundle imported normally"
)


def _path_refusal_message(name: str, reason: str) -> str:
    """A refusal a user can act on: WHICH entry, WHAT is wrong, WHAT to do.

    The name goes through ``!r`` so a control character shows up as an escape
    instead of being acted on by whatever renders the message.
    """
    return f"Bundle entry {name!r} has an unsafe path: {reason}. {_REARCHIVE_ADVICE}"


def _collision_refusal_message(first: str, second: str, canonical: str) -> str:
    """A refusal for two entries that name ONE stored file.

    This is the nondeterminism, stated as such: nothing about either entry is
    unsafe on its own, but only one set of bytes can be stored at ``canonical`` and
    nothing decides which except the order the archive lists them in.

    The two names are reported in sorted order rather than in the order they were
    encountered, so the refusal itself does not depend on archive order either —
    reversing the members yields the same message, not a mirrored one.
    """
    earlier, later = sorted((first, second))
    return (
        f"Bundle entries {earlier!r} and {later!r} both name the same file "
        f"{canonical!r}, so which of the two would be stored depends only on the "
        "order the archive happens to list them in. Remove the duplicate and "
        "re-create the archive with one entry per file."
    )


# Bidi classes carried by EXACTLY the nine explicit bidirectional formatting
# characters — the embeddings, the overrides and the isolates. Verified over the whole
# code space against Unicode 16.0.0: no other assigned character has any of these
# classes, so this is a definitive derivation rather than a hand-kept list, and a
# future Unicode release that adds another embedding-style control is covered without
# a code change.
_BIDI_FORMATTING_CLASSES = frozenset(
    {"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"}
)

# The three IMPLICIT bidi marks have to be listed, because they are deliberately
# indistinguishable by bidi class from ordinary text: LRM is class "L" like "A", RLM
# is "R" like a Hebrew letter, and ALM is "AL" like an Arabic letter. They are the
# remainder of Unicode's Bidi_Control property (PropList.txt), and
# ``test_the_refused_set_is_exactly_unicodes_bidi_control_property`` asserts the union
# below is precisely those twelve characters, so an omission fails a test rather than
# shipping. U+061C ALM was the omission that did ship.
_BIDI_MARKS = frozenset("\u200e\u200f\u061c")


def _is_bidi_control(ch: str) -> bool:
    """True for a Unicode Bidi_Control character.

    Nine of the twelve are derived from their bidi class; the three implicit marks are
    named explicitly because no Unicode property available through
    :mod:`unicodedata` separates them from ordinary letters.
    """
    return (
        ch in _BIDI_MARKS
        or unicodedata.bidirectional(ch) in _BIDI_FORMATTING_CLASSES
    )


def _forbidden_character_reason(name: str) -> Optional[str]:
    """The reason ``name`` contains an unusable character, or ``None`` if it is clean.

    Rejected:

      * category ``Cc`` — the C0 range, DEL, **and the C1 range (0x80-0x9F)**. Testing
        ``ord(ch) < 0x20 or ord(ch) == 0x7F`` missed C1 entirely, so ``U+0085`` (NEL,
        which several parsers treat as a line break) passed and could be stored.
      * category ``Cs`` — an unpaired surrogate is not text at all; nothing
        downstream that encodes or renders a path can handle one meaningfully.
      * :func:`_is_bidi_control` — a name that renders as a different name than it is.

    NOT rejected: the rest of category ``Cf``, and unassigned/private-use code
    points. ZWNJ (``U+200C``), ZWJ (``U+200D``) and SOFT HYPHEN (``U+00AD``) are Cf
    and appear in legitimate filenames in Persian, Arabic and Indic scripts, so
    refusing all of Cf would turn away a real bundle to close nothing — the display
    spoof is specific to the bidi subset above. Unassigned code points are excluded
    for the same reason: today's ``Cn`` is tomorrow's ordinary letter, and refusing
    them dates the check rather than hardening it.
    """
    for ch in name:
        category = unicodedata.category(ch)
        if category == "Cc":
            return _REASON_CONTROL
        if category == "Cs":
            return _REASON_SURROGATE
        if _is_bidi_control(ch):
            return _REASON_BIDI
    return None


def _segment_refusal(path: str) -> Optional[_EntryVerdict]:
    """Refuse ``path`` if any SEGMENT of it is ``..``, empty, or ``.``, else ``None``.

    Checked in that order so the most consequential defect is the one reported: a
    path with both a traversal and a stray ``.`` is a traversal.
    """
    segments = path.split("/")
    if ".." in segments:
        return _EntryVerdict(_ENTRY_REFUSE, reason=_REASON_TRAVERSAL)
    if "" in segments:
        return _EntryVerdict(_ENTRY_REFUSE, reason=_REASON_EMPTY_SEGMENT)
    if "." in segments:
        return _EntryVerdict(
            _ENTRY_REFUSE,
            reason=_REASON_DOT_PREFIX if segments[0] == "." else _REASON_DOT_SEGMENT,
        )
    return None


def _entry_path_verdict(rel_path: str) -> _EntryVerdict:
    """VALIDATE a raw entry name — never rewrite it — and say why if refused.

    A bundle entry is already spelled as the plain relative path of the file it
    names, or the bundle is refused. Nothing is normalized into an acceptable form,
    for two reasons that were both observed:

      * Rewriting changes the very string the rules downstream are about to judge.
        ``assets/innocent/.`` normalized to ``assets/innocent``, losing the ``.``
        basename that made it a directory reference, and the entry was stored under
        a name that was not its own.
      * Rewriting collapses DISTINCT entries onto ONE identity — ``assets/./x``,
        ``assets//x`` and ``assets/x`` all become ``assets/x`` — leaving which bytes
        get stored to zip member ordering.

    Refused: an empty name, an unusable character (see
    :func:`_forbidden_character_reason`), an absolute path (POSIX ``/`` or a Windows
    drive), a ``\\`` separator, and any ``..``, EMPTY or ``.`` segment.

    There is now NO rewrite left here at all — a non-``None`` result is the argument,
    unchanged. The ``\\`` -> ``/`` fold that used to be the one tolerance is gone,
    because it was not free:

      * :func:`_locate_root_prefix` and the ``startswith(root_prefix)`` scoping in
        :func:`_iter_safe_entries` match RAW names, before any fold. So in a bundle
        wrapped in ``safe/``, ``safe\\templates\\x\\.thumbnail`` folded to the same
        logical path as ``safe/templates/x/.thumbnail`` — but failed the raw
        root-prefix match and was SILENTLY SKIPPED instead of colliding with it. The
        import succeeded, one entry vanished, and :func:`_claim_canonical_path` was
        never reached. Two path identities in one importer is the whole bug class.
      * measured, it buys nothing: across the real exports on hand (777, 777, 868 and
        872 entries) not ONE entry contains a backslash.

    So refusing it removes the last rewrite and leaves exactly one path identity for
    validation, root discovery and storage to agree on.

    A trailing ``/`` marks a DIRECTORY entry, which is never stored — but the path it
    NAMES is still validated, so ``../evil/`` is refused rather than skipped. A
    trailing ``.`` is NOT treated as a directory marker: it is refused, because
    accepting it means deciding what ``assets/innocent/.`` names, and every answer to
    that question stores or judges a string that is not the entry's own name.

    The consequence taken deliberately: ``bsdtar -a -cf bundle.zip -C <dir> .``
    prefixes every member with ``./`` and is refused wholesale. That shape belongs to
    a re-archive of an unpacked bundle, not to the product's export — measured over
    the real exports on hand (777, 777, 868 and 872 entries), every single entry is
    already canonical, so the refusal turns away no bundle the product produces — and
    :data:`_REARCHIVE_ADVICE` names the re-archive as the likely cause.
    """
    if not rel_path:
        return _EntryVerdict(_ENTRY_REFUSE, reason=_REASON_EMPTY)
    # Characters first: every rule below, and every consumer downstream, is written
    # for a path that has none of these.
    character_reason = _forbidden_character_reason(rel_path)
    if character_reason is not None:
        return _EntryVerdict(_ENTRY_REFUSE, reason=character_reason)
    # Absolute and drive-letter before the backslash rule, so 'C:\\Windows\\x' is
    # reported as the absolute Windows path it is rather than as a separator problem.
    if rel_path.startswith("/"):
        return _EntryVerdict(_ENTRY_REFUSE, reason=_REASON_ABSOLUTE)
    if re.match(r"^[A-Za-z]:", rel_path):
        return _EntryVerdict(_ENTRY_REFUSE, reason=_REASON_DRIVE)
    if "\\" in rel_path:
        return _EntryVerdict(_ENTRY_REFUSE, reason=_REASON_BACKSLASH)
    if rel_path.endswith("/"):
        named = rel_path[:-1]
        if not named:  # a bare "/" is already refused above as absolute
            return _EntryVerdict(_ENTRY_REFUSE, reason=_REASON_EMPTY)
        return _segment_refusal(named) or _EntryVerdict(_ENTRY_SKIP)
    return _segment_refusal(rel_path) or _EntryVerdict(_ENTRY_FILE, path=rel_path)


def _safe_relpath(rel_path: str) -> Optional[str]:
    """The bundle-relative FILE path as stored, or ``None`` to refuse it.

    VALIDATION, not laundering (see :func:`_entry_path_verdict`): a non-``None`` result
    is the argument, byte for byte. Nothing is rewritten, so this function and the raw
    ``startswith(root_prefix)``/slice bookkeeping elsewhere cannot disagree about what
    an entry's path is.

    Shape only — no junk/dotfile judgement — because its callers
    (:func:`_locate_root_prefix`, :func:`_declared_css_paths`,
    :func:`build_font_mapping`) ask exactly "is this a usable relative path". Entry
    classification goes through :func:`_classify_bundle_entry` instead.

    ``None`` covers both "refused" and "names a directory rather than a file"; no
    caller has anything to do with a directory.

    This is the contract the file browser relies on: stored
    ``design_system_file.path`` values are canonical by construction, so
    ``_validated_file_path`` can reject a non-canonical REQUEST instead of
    normalizing it into an accepted one.
    """
    return _entry_path_verdict(rel_path).path or None


def _classify_bundle_entry(rel_path: str) -> _EntryVerdict:
    """THE decision for one bundle entry: refuse it, skip it, or store it.

    ONE place that validates the path and then applies EVERY remaining rule to the
    SAME string, so no rule is ever handed a laundered one. Both gates that judge
    bundle paths call this — the up-front whole-bundle scan
    (:func:`_assert_bundle_paths_safe`) and the per-entry iterator
    (:func:`_iter_safe_entries`) — so a new rule cannot be added to one and forgotten
    in the other. They used to decide separately and DID disagree: the scan refused
    ``assets/innocent/.`` on its raw basename while the iterator accepted the same
    entry on its normalized one, and the permissive gate was the one that reached
    storage.

    Sharing one classifier is what makes that class of divergence impossible by
    construction; the tests can only pin that the two gates AGREE across a broad
    corpus of shapes, which is the property the regression violated.
    """
    verdict = _entry_path_verdict(rel_path)
    if verdict.kind != _ENTRY_FILE:
        return verdict
    canonical = verdict.path
    low = canonical.lower()
    if low.startswith("__macosx/") or "/__macosx/" in low:
        return _EntryVerdict(_ENTRY_SKIP)
    base = _basename(low)
    # The ONE dot-prefixed shape the importer stores is a template folder's
    # screenshot; every other dotfile is SKIPPED — and the user is told, via a
    # non-fatal warning carried on the verdict's ``reason``.
    #
    # A DELIBERATE, DOCUMENTED DEVIATION from the acceptance battery's B8 wording,
    # which lists dotfiles among the shapes to REFUSE. Refusal is wrong here on the
    # evidence: the real export contains ZERO non-``.thumbnail`` dotfiles (4 dotfiles,
    # all ``.thumbnail``), so refusal is untested against any real bundle — while
    # ``.DS_Store`` is created invisibly and ubiquitously by macOS Finder. Refusing
    # wholesale would fail a user's upload over a file they cannot see they have and
    # cannot easily remove. Skipping is safe (a dotfile is never stored, so nothing
    # unsafe reaches the database either way); the gap it leaves is that the user is
    # not TOLD, and a warning closes exactly that gap without the false negative.
    if (base == ".ds_store" or base.startswith(".")) and not _is_template_preview(
        canonical
    ):
        return _EntryVerdict(_ENTRY_SKIP, reason=_REASON_DOTFILE_SKIPPED)
    return _EntryVerdict(_ENTRY_FILE, path=canonical)


def _raw_entry_name(info: zipfile.ZipInfo) -> str:
    """The name the ARCHIVE records for an entry, not the one Python hands back.

    ``ZipInfo.__init__`` truncates ``filename`` at the first NUL byte and keeps the
    real central-directory name in ``orig_filename``. Every gate here reads the name
    through this function so validation judges what the archive actually says.

    ABSENT and EMPTY are different answers, and only an explicit ``None`` test tells
    them apart. ``or`` did not: it fell back to ``filename`` for an ``orig_filename``
    of ``""`` as readily as for a missing attribute — which is this module's own
    laundering, performed at the one function whose entire job is to report the raw
    name. An empty central name is attacker-controlled data with meaning, and CPython
    will happily REPLACE it: a ``0x7075`` record needs its checksum to match the
    central name, and the CRC-32 of ``b""`` is 0, so the record is honoured and
    ``filename`` becomes whatever it declares. The fallback then handed every gate
    that name, so ``orig_filename != filename`` compared the replacement against
    itself and the local-header comparison compared against it too. Measured: an entry
    with an empty central name, a local name of ``slides/benign.bin`` and a record
    declaring the same passed both and was yielded for storage.

    The empty name is now REPORTED rather than replaced; refusing it is
    :func:`_entry_identity_refusal`'s call, on :data:`_REASON_EMPTY_RECORDED_NAME`.
    The ``getattr`` default stays for a ``ZipInfo`` that genuinely lacks the attribute.
    """
    raw = getattr(info, "orig_filename", None)
    return info.filename if raw is None else raw


# Info-ZIP Unicode Path Extra Field. Its whole purpose is to declare a name for an
# entry OTHER than the one in the central directory, which makes it a name-rewriting
# record and therefore this module's business.
_UNICODE_PATH_EXTRA_TAG = 0x7075

# Bytes of the 0x7075 payload before the name itself: a 1-byte version and a 4-byte
# CRC-32 of the central-directory name.
_UNICODE_PATH_HEADER_LEN = 5

# Every extra-field record is a 2-byte tag followed by a 2-byte body size. Anything
# shorter than that cannot be a record at all.
_EXTRA_RECORD_HEADER_LEN = 4


def _extra_field_name_refusal(extra: bytes, central: str) -> Optional[str]:
    """Refuse an entry whose EXTRA FIELD declares a different name, else ``None``.

    Takes the extra-field BYTES rather than a ``ZipInfo`` because an entry has TWO
    extra fields — one in the central directory, one in its local file header — and
    both are walked, by :func:`_entry_identity_refusal`. ``ZipInfo.extra`` is only the
    central copy.

    Parsed from raw bytes on purpose. No stdlib-processed attribute
    can be trusted as an entry's identity, and this record is the proof: in CPython's
    ``ZipInfo._decodeExtra`` a ``0x7075`` record assigns
    ``self.filename = _sanitize_filename(declared_name)`` and never touches
    ``orig_filename``. So an entry whose central name is already the clean
    ``templates/x/.thumbnail`` and whose extra field declares
    ``templates/x/.thumbnail\\x00.exe`` comes back with ``orig_filename`` EQUAL to
    ``filename`` — the sanitizer removed the NUL — and the
    "recorded name == read name" invariant sees nothing wrong. Measured: that entry
    reached the thumbnail allowlist and was stored as a live template thumbnail.

    ANY disagreement is refused, without consulting the record's version byte or name
    CRC. Two reasons: replicating the stdlib's acceptance test would make this guard
    depend on the very internals it exists to distrust, and an entry that declares two
    different names is ambiguous whether or not this particular reader honours the
    second one. The cost is that a legacy Info-ZIP archive which uses this field for
    its intended purpose — carrying a UTF-8 name alongside a mangled CP437 one — is
    refused rather than accepted on the UTF-8 name. That is the consistent choice for
    this importer (refuse ambiguity, never resolve it), it is what the user can fix by
    re-zipping, and it costs nothing measured: across the real exports, ZERO entries
    carry a 0x7075 record. Modern tools set the UTF-8 flag and put the name straight in
    the central directory, needing no extra field at all.

    ``0x7075`` is the ONLY record that can rewrite a name: in the same stdlib function
    the only other tag handled is ``0x0001`` (Zip64), which adjusts sizes and offsets
    and never the filename. The Unicode COMMENT field (``0x6375``) carries a comment,
    not a path. Unknown tags are skipped by both the stdlib and the loop below.
    """
    offset = 0
    while offset < len(extra):
        # A LEFTOVER too short to be a record header is malformed, not padding. The
        # extra field is a sequence of records that tile it exactly; the format
        # defines no filler between or after them. Stopping quietly on a trailing
        # fragment skipped the shortest possible spelling of the very record this
        # function exists to read: an extra of exactly b"\x75\x70" is the 0x7075 tag
        # with its size field and body cut off, and CPython — whose own walk has the
        # same four-byte floor — opens such an archive without complaint. Whatever
        # name that record meant to declare cannot be read, which is the condition
        # the overrun and short-body branches below already refuse.
        if len(extra) - offset < _EXTRA_RECORD_HEADER_LEN:
            return _REASON_CORRUPT_EXTRA
        tag, size = struct.unpack_from("<HH", extra, offset)
        body_start = offset + _EXTRA_RECORD_HEADER_LEN
        body_end = body_start + size
        if body_end > len(extra):
            return _REASON_CORRUPT_EXTRA
        if tag == _UNICODE_PATH_EXTRA_TAG:
            body = extra[body_start:body_end]
            if len(body) < _UNICODE_PATH_HEADER_LEN:
                return _REASON_CORRUPT_EXTRA
            try:
                declared = body[_UNICODE_PATH_HEADER_LEN:].decode("utf-8")
            except UnicodeDecodeError:
                return _REASON_CORRUPT_EXTRA
            if declared != central:
                return _REASON_NAME_MISMATCH
        offset = body_end
    return None


# Local file header layout (APPNOTE 4.3.7), the fixed part of which is 30 bytes:
# signature, version needed, general-purpose bit flag, ... then the two lengths that
# say how much variable-length data follows, then the name and the extra field.
_LOCAL_HEADER_SIGNATURE = b"PK\x03\x04"
_LOCAL_HEADER_LEN = 30
_LOCAL_HEADER_FLAGS_OFFSET = 6
_LOCAL_HEADER_LENGTHS_OFFSET = 26  # file name length u16, then extra field length u16
# General-purpose bit 11: the name and comment are UTF-8 rather than the historical
# CP437. Read from the LOCAL header's own flags, because that is the byte a reader
# consulting this header would use to decode the name beside it.
_UTF8_NAME_FLAG = 0x800


def _local_header_identity(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo
) -> "Optional[tuple[str, bytes]]":
    """The ``(name, extra)`` the entry's LOCAL FILE HEADER records, or ``None``.

    A .zip states every entry's identity TWICE — once in the local file header that
    precedes its bytes, once in the central directory at the end — and NOTHING in the
    format makes the two agree. CPython builds ``ZipInfo`` purely from the central
    copy: ``ZipInfo.extra`` is the central extra and the local one is never parsed at
    all. So a guard that reads ``info.extra`` alone inspects one of the two names an
    archive can present, and an attacker simply puts the rewrite in the other:
    measured, an entry with a clean central name, an EMPTY central extra and a local
    ``0x7075`` record declaring ``templates/x/.thumbnail\\x00.exe`` (version 1,
    matching CRC — the form CPython would honour had it looked) was accepted and
    stored as a live template thumbnail, which is precisely the outcome the central
    check exists to prevent.

    Read straight from the archive rather than through any ``ZipInfo`` attribute, for
    the same reason the extra field is: the point is what the bytes say. The header is
    located by ``info.header_offset`` — an absolute file offset, adjusted by CPython
    for any prepended data — and parsed at the documented offsets rather than guessed
    at.

    THE OFFSET IS THE ARCHIVE'S, NOT THE READER'S. ``header_offset`` looks like a value
    the zip reader vouched for and is nothing of the kind: a central directory record
    may carry the legacy sentinel ``0xffffffff`` in its 32-bit offset field plus a ZIP64
    extra field holding a 64-bit replacement, and ``ZipInfo._decodeExtra`` substitutes
    that verbatim without ever comparing it to the size of the file. A 146-byte archive
    can therefore claim its entry's local header begins at ``2**64 - 1``. So the offset
    is bound-checked against the archive's real size BEFORE the seek, and an offset that
    cannot hold a header is unreadable like any other — which also makes "past the end
    of the file" and "too large to seek to at all" one case instead of two.

    PRECONDITION on sharing ``zf.fp``, stated rather than assumed. This seeks a file
    pointer it does not own, and it does so WITHOUT taking ``ZipFile._lock``, so it is
    not safe in general — a truly concurrent read, or a file object shared with anything
    outside this ``ZipFile``, could be moved out from under mid-read. It is safe for
    THIS importer's usage, and only because of four properties that hold together:
    :func:`import_bundle` wraps the upload in a private :class:`io.BytesIO` that nothing
    else holds a reference to; the whole-bundle scan runs to completion before any entry
    is read; ``ZipFile.open``'s reader re-seeks to its own position before every read, so
    a moved pointer cannot corrupt an open stream; and the asset reads are synchronous
    ``zf.read`` calls with no interleaving. The position is restored afterwards anyway —
    it costs one seek and removes the need for a reader of this function to know any of
    the above.

    ``None`` means the header could not be read as a local file header at all, which
    callers treat as a refusal (:data:`_REASON_LOCAL_HEADER`) rather than as
    permission: an entry whose second name is unknown is not an entry with one name.
    """
    fp = getattr(zf, "fp", None)
    if fp is None:
        return None
    try:
        resume_at = fp.tell()
        try:
            fp.seek(0, io.SEEK_END)
            archive_size = fp.tell()
            offset = info.header_offset
            # Negative is nonsense and at/after EOF means the header is not there. Both
            # are checked BEFORE the seek, because a large enough offset does not fail
            # the seek gracefully — it cannot be converted to a C ssize_t and raises
            # OverflowError, which is not an OSError and is not a ValueError.
            if offset < 0 or offset + _LOCAL_HEADER_LEN > archive_size:
                return None
            fp.seek(offset)
            header = fp.read(_LOCAL_HEADER_LEN)
            if (
                len(header) != _LOCAL_HEADER_LEN
                or header[:4] != _LOCAL_HEADER_SIGNATURE
            ):
                return None
            name_len, extra_len = struct.unpack_from(
                "<HH", header, _LOCAL_HEADER_LENGTHS_OFFSET
            )
            name_bytes = fp.read(name_len)
            extra = fp.read(extra_len)
        finally:
            fp.seek(resume_at)
    except (OSError, ValueError, OverflowError):
        # A seek on a detached/closed stream raises, and the bound check above cannot
        # cover an arithmetic surprise nobody has thought of yet — OverflowError is
        # here as the backstop for the next one, since the whole point of this helper
        # is that its input is hostile. Unreadable, like any other unparseable header.
        #
        # NOT bare ``Exception``: a genuine bug in the parsing this guards must still
        # crash loudly rather than be laundered into a path refusal.
        return None
    if len(name_bytes) != name_len or len(extra) != extra_len:
        return None
    (flags,) = struct.unpack_from("<H", header, _LOCAL_HEADER_FLAGS_OFFSET)
    encoding = "utf-8" if flags & _UTF8_NAME_FLAG else "cp437"
    try:
        return name_bytes.decode(encoding), extra
    except UnicodeDecodeError:
        return None


def _entry_identity_refusal(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo
) -> Optional[str]:
    """Refuse an entry that the archive gives more than ONE name, else ``None``.

    THE place every name-rewriting route is collected, so closing one cannot leave
    another open. There are four, and each is invisible to the others:

      1. ``orig_filename != filename`` — the reader rewrote the central name. A NUL
         byte does this: ``templates/x/.thumbnail\\x00.exe`` is truncated to
         ``templates/x/.thumbnail``, which matches the thumbnail allowlist.
      2. A ``0x7075`` record in the CENTRAL extra declaring another name. This defeats
         route 1 entirely, because the stdlib sanitizes the declared name before
         assigning it, leaving the two attributes equal.
      3. The LOCAL file header's name disagreeing with the central directory's.
         CPython does compare these, but only inside ``ZipFile.open`` — i.e. only for
         entries whose bytes are actually read, and only as a ``BadZipFile`` rather
         than as something the user can act on. Refusing here covers every entry and
         says what is wrong.
      4. A ``0x7075`` record in the LOCAL extra. This defeats routes 1-3 together: the
         central directory is entirely clean, so nothing CPython parses is out of
         place, while a reader that trusts local headers sees the other name.

    Checked in that order, so the reported reason names the shallowest defect the
    entry has rather than the deepest.

    All four presuppose that the archive records a name at all, which is why the EMPTY
    recorded name is refused ahead of them: an entry with no central-directory name has
    no identity for this function to establish, and every comparison below would be
    against ``""``. It is reported as the empty name it is rather than as a mismatch
    with whatever CPython resolved, because that is the fact the user can act on.
    """
    central = _raw_entry_name(info)
    if not central:
        return _REASON_EMPTY_RECORDED_NAME
    if central != info.filename:
        return _REASON_NAME_MISMATCH
    reason = _extra_field_name_refusal(info.extra or b"", central)
    if reason is not None:
        return reason
    local = _local_header_identity(zf, info)
    if local is None:
        return _REASON_LOCAL_HEADER
    local_name, local_extra = local
    if local_name != central:
        return _REASON_NAME_MISMATCH
    return _extra_field_name_refusal(local_extra, central)


def _entry_verdict_for_info(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo
) -> _EntryVerdict:
    """The verdict for one ZipInfo, judged on the name the archive really records.

    The whole-bundle scan's composition of the two shared steps, over the FULL recorded
    name. :func:`_iter_safe_entries` applies the very same two steps in the very same
    order but cannot call this, because it has to interleave its root-prefix scoping
    between them: identity is judged for every member, scoping then decides which
    entries this import stores, and only those are classified — on the STRIPPED path,
    because the template-thumbnail allowlist is anchored at ``templates/``. Identity is
    judged on the full recorded name in both gates, that being the string a rewrite
    would have altered.

    IDENTITY FIRST, then the path rules. :func:`_entry_identity_refusal` establishes
    that the entry has exactly ONE name — across both of the archive's copies of it —
    and only then is that name classified. The order is the point: validating a path
    that the archive states twice validates whichever copy this reader happened to
    resolve, while ``zf.read``/``namelist`` and the rest of the importer key off
    ``filename``. Refusing any divergence keeps one name per entry everywhere, which
    is the same property the backslash refusal buys (see
    :func:`_entry_path_verdict`).

    ``zf`` is needed because half of what an archive says about an entry lives in the
    local file header, which no ``ZipInfo`` attribute exposes.
    """
    identity_reason = _entry_identity_refusal(zf, info)
    if identity_reason is not None:
        return _EntryVerdict(_ENTRY_REFUSE, reason=identity_reason)
    return _classify_bundle_entry(_raw_entry_name(info))


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """True if a zip entry is a symlink (Unix mode ``S_IFLNK`` in ``external_attr``).

    A symlink entry stores its link TARGET as content; if we stored it as an asset
    the bytes would be the target path/data, so such entries are refused outright.
    Windows-created zips have no Unix mode (``external_attr`` high bits 0), which
    correctly reads as "not a symlink".
    """
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _claim_canonical_path(claimed: "dict[str, str]", name: str, canonical: str) -> None:
    """Record that ``name`` stores ``canonical``, refusing a second claim on it.

    Two DISTINCT entries whose stored paths are equal can only put one set of bytes
    at that path, and nothing decides which except the order the archive happens to
    list them in — so the bundle is refused rather than imported with order-dependent
    content.

    Strict path validation does NOT subsume this, which is why it remains a separate
    check even now that no rewrite is left to collapse two spellings together: a zip
    may legally carry the SAME arcname twice, where both names are identical and
    perfectly canonical and no path rule can see anything wrong at all. Only member
    order would decide which bytes a reader gets.

    Shared by both gates, so a collision cannot be caught by one and missed by the
    other.
    """
    previous = claimed.get(canonical)
    if previous is not None:
        raise DesignSystemImportError(
            _collision_refusal_message(previous, name, canonical)
        )
    claimed[canonical] = name


def _assert_bundle_paths_safe(zf: zipfile.ZipFile) -> None:
    """Reject the WHOLE bundle if ANY entry is a symlink, a zip-slip path, or a
    duplicate claim on one stored path.

    Validated GLOBALLY over every ``ZipInfo`` — independent of, and before, any
    root-prefix scoping — so a malicious entry that falls OUTSIDE the bundle root
    (e.g. ``../evil.png`` when the manifest sits under ``safe/``) is REJECTED, not
    silently skipped. EVERY entry is checked (no exemption for an empty name):
    absolute paths, ``..`` traversal, ``\\`` separators, unusable characters and empty
    names are refused, and symlink entries are refused before any bytes are read.

    Collisions are checked globally too, on the same paths. That is deliberately
    broader than the import scope — two colliding entries outside the bundle root
    refuse the bundle even though neither would be stored — and matches how this gate
    already treats an unsafe path outside the root.

    THIS GATE ESTABLISHES THE INVARIANT THE REST OF THE IMPORTER RELIES ON. It runs
    before root discovery and before any read (see :func:`import_bundle`), and it
    refuses any entry the archive gives more than one name — whether the divergence is
    between ``orig_filename`` and ``filename``, between the two headers that record
    the entry, or in a name-rewriting extra field in either of them
    (:func:`_entry_identity_refusal`) — as well as any name containing a ``\\``.
    Everything downstream — :func:`_locate_root_prefix`, the
    ``startswith(root_prefix)`` scoping and slicing in :func:`_iter_safe_entries`, and
    ``zf.read``-by-name — therefore works on names that are exactly what validation
    judged. Weakening any of those refusals reintroduces two path identities in one
    importer.

    The verdict comes from :func:`_entry_verdict_for_info`, which composes the SAME two
    shared steps :func:`_iter_safe_entries` applies —
    :func:`_entry_identity_refusal` then :func:`_classify_bundle_entry` — so the two
    gates cannot disagree about an entry. The iterator runs them either side of its own
    root-prefix scoping, which is why it composes them itself rather than calling this
    gate's helper; the classifiers are shared, so there is still exactly one of each.
    """
    claimed: dict[str, str] = {}
    for info in zf.infolist():
        # The name the ARCHIVE records — not ``info.filename``, which the stdlib may
        # have truncated. Reported with ``!r`` for the same reason the path refusals
        # use it: a control character must not render raw into the message.
        name = _raw_entry_name(info)
        if _is_symlink(info):
            raise DesignSystemImportError(
                f"Bundle entry {name!r} is a symlink; refusing to import."
            )
        # No ``if name`` guard: an empty name is refused, not skipped.
        verdict = _entry_verdict_for_info(zf, info)
        if verdict.kind == _ENTRY_REFUSE:
            raise DesignSystemImportError(_path_refusal_message(name, verdict.reason))
        if verdict.kind == _ENTRY_FILE:
            _claim_canonical_path(claimed, name, verdict.path)


def _iter_safe_entries(
    zf: zipfile.ZipFile,
    root_prefix: str,
    warnings: "Optional[list[BundleImportWarning]]" = None,
):
    """Yield ``(ZipInfo, safe_rel_path)`` for every in-scope bundle FILE entry.

    Skips directories, OS junk (``__MACOSX``, ``.DS_Store``) and dotfiles. Raises
    :class:`DesignSystemImportError` on an in-scope zip-slip path (absolute or ``..``),
    and on ANY entry the archive gives more than one name wherever it sits, so a
    malicious bundle is rejected rather than silently stored.

    This is the ACTUAL first gate every entry passes, so the ONE dot-prefixed shape
    the importer stores — a template folder's ``.thumbnail`` screenshot
    (:func:`_is_template_preview`) — is allowlisted HERE too. Without that a fix to
    the recognizer alone reads as working in a unit test and still drops every real
    thumbnail, because the entry never reaches the recognizer.

    Judged in TWO STEPS, in the same order :func:`_entry_verdict_for_info` applies them
    for the up-front scan, with the scoping filter interleaved between the two:
    :func:`_entry_identity_refusal` for every member, then
    :func:`_classify_bundle_entry` for the ones this import is scoped to. Both halves
    are the SHARED helpers, so neither gate can be patched into disagreeing with the
    other. Interleaving is what keeps the two halves' different natures straight: an
    entry outside the root is legitimately none of this import's business, while an
    entry the archive names twice is hostile wherever it sits — see the comments at the
    two steps.

    Stripping ``root_prefix`` is the only work done here, and it is bookkeeping rather
    than a path rule: it is a raw slice, which is sound precisely because no validated
    name is ever a rewritten one (no ``\\`` fold, no stdlib truncation).

    Two in-scope entries claiming ONE path are refused here as well as by the up-front
    scan, so every path this yields is DISTINCT and callers do not need a first-wins
    de-duplication that would have let zip order pick the bytes.

    Args:
        warnings: optional collector. A SKIPPED entry that the user should know about
            — a non-allowlisted dotfile — is reported here rather than vanishing
            silently. Skips with no ``reason`` (directory markers, ``__MACOSX``
            mirrors) stay silent on purpose: they are per-directory bookkeeping and
            would flood the list with one entry per real file while telling the user
            nothing about their own content.
    """
    claimed: dict[str, str] = {}
    for info in zf.infolist():
        name = _raw_entry_name(info)
        # IDENTITY BEFORE SCOPE, for EVERY member. Whether the archive gives this entry
        # ONE name is a fact about the entry, true wherever it sits, so it is settled
        # before the scoping below decides whether this import has any interest in it.
        # Ordering these the other way round left the iterator judging only what the
        # scope filter let through, and an entry it dropped was never judged at all: an
        # EMPTY recorded name is "in scope" of every prefix and strips to nothing, so
        # ``not rel_raw`` SKIPPED it — the one shape that is hostile precisely because
        # the archive records no name for it.
        #
        # Nothing was exploitable: :func:`_assert_bundle_paths_safe` runs first on every
        # production path and refuses such an entry before root discovery or any read.
        # What was lost is that this gate no longer refused INDEPENDENTLY, which is the
        # entire value of having two.
        identity_reason = _entry_identity_refusal(zf, info)
        if identity_reason is not None:
            raise DesignSystemImportError(
                _path_refusal_message(name, identity_reason)
            )
        # SCOPE, unchanged and still SILENT. An entry outside the discovered root is
        # not one of the entries this import stores, so it is passed over rather than
        # refused — including one whose PATH is unsafe, which the whole-bundle scan
        # already refuses GLOBALLY (see :func:`_assert_bundle_paths_safe`). Raising here
        # on an out-of-scope path would widen this generator from "the entries this
        # import stores" to "every entry in the archive", which is a different contract
        # from the one its caller has. Identity is not that: it is judged above because
        # no root prefix makes a second name acceptable.
        if not name.startswith(root_prefix):
            continue
        rel_raw = name[len(root_prefix):]
        if not rel_raw:
            continue  # the root-prefix directory entry itself
        # The STRIPPED path is what gets classified — the reason this is
        # :func:`_classify_bundle_entry` directly rather than
        # :func:`_entry_verdict_for_info`, whose identity half has already run above.
        # The template-thumbnail allowlist is anchored at ``templates/``, so a wrapped
        # bundle's ``safe/templates/x/.thumbnail`` only matches once ``safe/`` is off;
        # the identity check above deliberately used the FULL recorded name instead,
        # which is the string a rewrite would have altered.
        verdict = _classify_bundle_entry(rel_raw)
        if verdict.kind == _ENTRY_REFUSE:
            raise DesignSystemImportError(
                _path_refusal_message(rel_raw, verdict.reason)
            )
        if verdict.kind == _ENTRY_SKIP:
            if verdict.reason and warnings is not None:
                warnings.append(BundleImportWarning(rel_raw, verdict.reason))
            continue
        _claim_canonical_path(claimed, rel_raw, verdict.path)
        yield info, verdict.path


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
    warnings: "Optional[list[BundleImportWarning]]" = None,
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

    # No de-duplication here: ``_iter_safe_entries`` refuses a bundle in which two
    # entries claim one canonical path, so every ``rel`` it yields is distinct. The
    # first-wins skip this replaced was the thing that let zip order decide which of
    # two colliding entries' bytes were stored.
    for info, rel in _iter_safe_entries(zf, root_prefix, warnings):
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
            kind = "template_shot" if _is_template_preview(rel) else _infer_asset_kind(rel)
            if _is_template_thumbnail(rel):
                # No extension to guess from, so the type comes from the CONTENT.
                # Unrecognized bytes are REFUSED rather than stored as
                # application/octet-stream: a thumbnail is served back to the
                # browser, so its declared type has to be one we actually verified.
                # Only THIS entry is dropped — a bundle import is one request, and
                # one junk screenshot must not cost the whole upload.
                sniffed = _sniff_raster_mime(data)
                if sniffed is None:
                    logger.warning(
                        "Bundle entry '%s' is not a PNG/JPEG/GIF/WebP image "
                        "(%d bytes); not stored as a template thumbnail",
                        rel,
                        len(data),
                    )
                    # A server-side log alone left the user believing the import was
                    # complete; the same fact rides back on the response.
                    if warnings is not None:
                        warnings.append(
                            BundleImportWarning(
                                rel,
                                "not a PNG, JPEG, GIF or WebP image "
                                f"({len(data)} bytes); this template's thumbnail "
                                "was not stored.",
                            )
                        )
                    continue
                mime = sniffed
            else:
                mime = _guess_mime(rel)
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
