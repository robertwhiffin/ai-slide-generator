"""Design-system template entities (v1 Phase 4).

Makes each design system's slide templates individually addressable and
consumable by generation:

- **Materialization**: ``design_system_template`` rows are a flattened
  projection (the ``design_system_token`` pattern) of the manifest
  ``templates[]`` entries — ``{name, description, folder, entryPath}`` in the
  Claude-Design export shape — joined to the retained ``design_system_file``
  entry HTML (``templates/<folder>/index.html``, kind ``template``). Populated
  at import; :func:`materialize_templates` also derives them lazily for systems
  imported after Phase 1 but before this table existed. Pre-Phase-1 systems
  retained no files and simply have no templates (owner accepted re-upload).

- **Asset-ref rewriting**: a template's entry HTML references bundle assets by
  relative path (``../assets/brand/x.svg`` from its folder, or bundle-root
  ``assets/…``) in both ``<img src>``/``href`` attributes AND CSS ``url()``.
  :func:`rewrite_template_asset_refs` maps those to the design system's stored
  assets and rewrites them to ``{{ds-asset:ID}}`` so the existing resolver
  (``src.utils.ds_asset_utils``) renders them. Unresolvable image refs become an
  inert ``data:,`` placeholder (logged, never a crash); preview-chrome
  ``<script>`` tags (``ds-base.js``/``deck-stage.js``) are stripped — they are
  picker chrome, never model input. Rewriting happens ONCE, at materialization,
  into the stored ``layout_html``/``token_css`` (deterministic; re-derivable by
  deleting the rows).

- **Consumption**: :func:`build_selected_template_block` renders ONE pinned
  template as a clearly-delimited SELECTED-TEMPLATE prompt block — the layout
  HTML as an archetype catalog plus the token stylesheet its ``var(--…)`` refs
  depend on. It is appended at PROMPT-ASSEMBLY time by
  ``agent_factory._get_prompt_content``; the persisted per-design-system
  ``compiled_style_content`` stays template-agnostic (no COMPILER_VERSION bump).
  The block is deliberately ONE function so its wording/shape can be swapped
  without touching the plumbing around it.

Everything here is brand-neutral engine code; no brand content is embedded.
"""
from __future__ import annotations

import logging
import posixpath
import re
from typing import Any, Optional
from urllib.parse import unquote

from src.database.models.design_system import DesignSystemTemplate

logger = logging.getLogger(__name__)

# Upper bound on the layout HTML injected into a prompt. Real Claude-Design
# template entries measure 24-47 KB; this is ~2.5x that headroom. A layout past
# the cap falls back to no-template (logged) rather than blowing up the prompt.
MAX_TEMPLATE_LAYOUT_CHARS = 120_000

# Inert placeholder for an unresolvable image/url ref: the minimal valid data
# URI. Renders as nothing, never fetches, and cannot be mistaken for a real
# ``{{ds-asset:ID}}`` handle.
_UNRESOLVED_PLACEHOLDER = "data:,"

# Refs that are not bundle-relative paths and must be left untouched: absolute
# URIs (http/https/data/mailto/blob/…), protocol-relative, fragments, and
# already-rewritten ``{{ds-asset:ID}}`` handles.
_ABSOLUTE_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)

# src/href/poster attribute refs in the entry HTML.
_ATTR_REF_RE = re.compile(
    r"(?P<prefix>\b(?P<name>src|href|poster)\s*=\s*(?P<q>[\"']))(?P<ref>[^\"']*)(?P=q)",
    re.IGNORECASE,
)

# CSS url() refs — both in <style> blocks and inline style="" attributes.
_CSS_URL_RE = re.compile(r"url\(\s*(?P<q>[\"']?)(?P<ref>[^\"')]+)(?P=q)\s*\)", re.IGNORECASE)


def _slug(value: str) -> str:
    """Slugify a template name for folder matching (same shape the compiler uses
    for CSS identifiers: lowercase, non-alphanumerics collapsed to ``-``)."""
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _normalize_bundle_path(base_dir: str, ref: str) -> Optional[str]:
    """Resolve *ref* against *base_dir* into a normalized bundle-relative path.

    Unlike the importer's zip-slip guard (which REJECTS ``..`` outright), this
    resolves ``..`` segments — template refs are legitimately parent-relative
    (``../assets/x.svg``) — and returns ``None`` only when the result escapes
    the bundle root or is absolute.
    """
    candidate = (ref or "").strip()
    if not candidate:
        return None
    joined = posixpath.join(base_dir, candidate) if base_dir else candidate
    normalized = posixpath.normpath(joined.replace("\\", "/"))
    if normalized.startswith(("/", "../")) or normalized in ("..", "."):
        return None
    return normalized


def _looks_rewritable(ref: str) -> bool:
    """True when *ref* is a candidate bundle-relative path (not an absolute URI,
    fragment, protocol-relative URL, or an existing ``{{ds-asset:ID}}`` handle)."""
    if not ref:
        return False
    if ref.startswith(("#", "//", "{{")):
        return False
    return not _ABSOLUTE_URI_RE.match(ref)


def _resolve_asset_id(
    ref: str, base_dir: str, asset_ids_by_path: dict[str, int]
) -> Optional[int]:
    """Map a raw ref to a stored asset id. Query strings/fragments are ignored.

    Templates are authored with several path conventions, so candidates are
    tried in order: (1) strict resolution against the template folder, (2) the
    ref taken as bundle-root-relative, (3) the ref with its leading ``..``
    segments stripped, re-anchored at the bundle root. (3) is what makes both
    ``../../assets/x.svg`` (strictly correct from ``templates/<folder>/``) and
    the commonly-authored ``../assets/x.svg`` land on the stored ``assets/…``
    path.
    """
    clean = unquote(ref.split("#", 1)[0].split("?", 1)[0].strip())
    if not clean:
        return None
    normalized = posixpath.normpath(clean.replace("\\", "/"))
    root_anchored = re.sub(r"^(\.\./)+", "", normalized)
    for candidate in (
        _normalize_bundle_path(base_dir, clean),
        _normalize_bundle_path("", clean),
        _normalize_bundle_path("", root_anchored),
    ):
        if candidate is not None and candidate in asset_ids_by_path:
            return asset_ids_by_path[candidate]
    return None


def rewrite_template_asset_refs(
    text: str, *, base_dir: str, asset_ids_by_path: dict[str, int]
) -> str:
    """Rewrite a template source's asset refs to ``{{ds-asset:ID}}`` handles.

    Covers ``src``/``href``/``poster`` attributes and CSS ``url()`` refs (the
    real export uses both). Refs that resolve to a stored asset become handles
    the existing resolver renders; unresolvable ``src``/``poster``/``url()``
    refs become the inert ``data:,`` placeholder (logged — never a crash), while
    an unresolvable ``href`` is left as-is (a dead link is already harmless).
    ``<script>`` tags are stripped first: template folders ship preview chrome
    (``ds-base.js``/``deck-stage.js``) that must never reach the model.
    """
    if not text:
        return text

    text = _SCRIPT_TAG_RE.sub("", text)

    def _replace_attr(match: "re.Match[str]") -> str:
        ref = match.group("ref")
        if not _looks_rewritable(ref):
            return match.group(0)
        asset_id = _resolve_asset_id(ref, base_dir, asset_ids_by_path)
        if asset_id is not None:
            return f"{match.group('prefix')}{{{{ds-asset:{asset_id}}}}}{match.group('q')}"
        if match.group("name").lower() == "href":
            logger.debug("Template href '%s' does not match a stored asset; left as-is", ref)
            return match.group(0)
        logger.warning(
            "Template asset ref '%s' does not match any stored design-system asset; "
            "replaced with an inert placeholder",
            ref,
        )
        return f"{match.group('prefix')}{_UNRESOLVED_PLACEHOLDER}{match.group('q')}"

    def _replace_url(match: "re.Match[str]") -> str:
        ref = match.group("ref").strip()
        if not _looks_rewritable(ref):
            return match.group(0)
        quote = match.group("q")
        asset_id = _resolve_asset_id(ref, base_dir, asset_ids_by_path)
        if asset_id is not None:
            return f"url({quote}{{{{ds-asset:{asset_id}}}}}{quote})"
        logger.warning(
            "Template CSS url ref '%s' does not match any stored design-system asset; "
            "replaced with an inert placeholder",
            ref,
        )
        return f"url({quote}{_UNRESOLVED_PLACEHOLDER}{quote})"

    text = _ATTR_REF_RE.sub(_replace_attr, text)
    return _CSS_URL_RE.sub(_replace_url, text)


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------


def _decode_file_text(ds_file: Any) -> Optional[str]:
    data = getattr(ds_file, "data", None)
    if data is None:
        return None
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="replace")
    return str(data)


def _entry_path_candidates(entry: dict) -> list[str]:
    """Ordered, normalized candidate entry paths for one manifest template entry.

    ``entryPath`` is authoritative (the Claude-Design export shape); ``folder``
    (with or without the ``templates/`` prefix) and a slug of the name are
    compatibility fallbacks for manifests that omit it.
    """
    candidates: list[str] = []

    entry_path = entry.get("entryPath")
    if isinstance(entry_path, str) and entry_path.strip():
        candidates.append(entry_path)

    folder = entry.get("folder")
    if isinstance(folder, str) and folder.strip():
        normalized = _normalize_bundle_path("", folder)
        if normalized:
            candidates.append(f"{normalized}/index.html")
            if not normalized.startswith("templates/"):
                candidates.append(f"templates/{normalized}/index.html")

    name = entry.get("name")
    if isinstance(name, str) and _slug(name):
        candidates.append(f"templates/{_slug(name)}/index.html")

    out: list[str] = []
    for candidate in candidates:
        normalized = _normalize_bundle_path("", candidate)
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def _find_thumbnail_asset_id(files: list[Any], template_dir: str) -> Optional[int]:
    """The template folder's ``preview*`` screenshot: the smallest-path image
    reference row under ``template_dir`` whose basename starts with ``preview``."""
    previews: list[tuple[str, int]] = []
    for ds_file in files:
        asset_id = getattr(ds_file, "asset_id", None)
        if asset_id is None:
            continue
        path = getattr(ds_file, "path", "") or ""
        if not path.startswith(f"{template_dir}/"):
            continue
        basename = path.rsplit("/", 1)[-1].lower()
        mime = (getattr(ds_file, "mime", "") or "").lower()
        if basename.startswith("preview") and mime.startswith("image/"):
            previews.append((path, asset_id))
    return min(previews)[1] if previews else None


def _build_token_css(files: list[Any], asset_ids_by_path: dict[str, int]) -> Optional[str]:
    """Join the retained CSS token sources (rewritten) in path order.

    Template CSS is not token-self-contained — its ``var(--…)`` references are
    defined in ``colors_and_type.css``/``globalCssPaths`` — so the ORIGINAL
    stylesheets ride along with every template (the compiled artifact renames
    tokens to ``--brand-*`` and cannot satisfy those references).
    """
    chunks: list[tuple[str, str]] = []
    for ds_file in files:
        if (getattr(ds_file, "kind", "") or "") != "css":
            continue
        text = _decode_file_text(ds_file)
        if not text:
            continue
        path = getattr(ds_file, "path", "") or ""
        base_dir = posixpath.dirname(path)
        chunks.append(
            (path, rewrite_template_asset_refs(
                text, base_dir=base_dir, asset_ids_by_path=asset_ids_by_path
            ))
        )
    if not chunks:
        return None
    return "\n\n".join(text for _, text in sorted(chunks))


def materialize_templates(design_system: Any) -> list[Any]:
    """Ensure a design system's ``design_system_template`` rows exist; return them.

    Idempotent: existing rows are returned untouched. Otherwise rows are derived
    from ``manifest_json['templates']`` joined to the retained entry-HTML file
    rows, with asset refs rewritten into the stored layout. None-safe throughout:
    a missing/malformed manifest, absent file rows (pre-Phase-1 imports), or a
    manifest entry with no matching file simply contribute no templates — never
    an error. New rows are APPENDED to ``design_system.templates``; flushing/
    committing them is the calling session's business (mirroring how the
    compiler's lazy recompute leaves persistence to ``get_db_session``).
    """
    existing = list(getattr(design_system, "templates", None) or [])
    if existing:
        return existing

    manifest = getattr(design_system, "manifest_json", None)
    entries = manifest.get("templates") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        return []

    files = list(getattr(design_system, "files", None) or [])
    entry_files = {
        getattr(f, "path", ""): f
        for f in files
        if (getattr(f, "kind", "") or "") == "template" and getattr(f, "data", None) is not None
    }
    if not entry_files:
        # Pre-Phase-1 import (no retained sources): no templates to address.
        return []

    asset_ids_by_path = {
        getattr(f, "path", ""): f.asset_id
        for f in files
        if getattr(f, "asset_id", None) is not None
    }
    token_css = _build_token_css(files, asset_ids_by_path)

    created: list[Any] = []
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name:
            continue
        entry_path = next(
            (c for c in _entry_path_candidates(entry) if c in entry_files), None
        )
        if entry_path is None:
            logger.info(
                "Design system %s: manifest template '%s' has no retained entry "
                "HTML; not materialized",
                getattr(design_system, "id", None),
                name,
            )
            continue
        if entry_path in seen_paths:
            logger.info(
                "Design system %s: manifest template '%s' duplicates entry path "
                "'%s'; skipped",
                getattr(design_system, "id", None),
                name,
                entry_path,
            )
            continue
        seen_paths.add(entry_path)

        template_dir = posixpath.dirname(entry_path)
        layout_html = rewrite_template_asset_refs(
            _decode_file_text(entry_files[entry_path]) or "",
            base_dir=template_dir,
            asset_ids_by_path=asset_ids_by_path,
        )
        raw_description = entry.get("description")
        description = (
            raw_description.strip()
            if isinstance(raw_description, str) and raw_description.strip()
            else None
        )
        template = DesignSystemTemplate(
            name=name,
            description=description,
            entry_path=entry_path,
            layout_html=layout_html,
            token_css=token_css,
            thumbnail_asset_id=_find_thumbnail_asset_id(files, template_dir),
        )
        design_system.templates.append(template)
        created.append(template)

    return created


# ---------------------------------------------------------------------------
# Generation-side lookup + the SELECTED-TEMPLATE prompt block
# ---------------------------------------------------------------------------


def get_template_for_generation(design_system: Any, template_id: int) -> Optional[Any]:
    """Resolve a pinned ``template_id`` against the selected design system.

    The template must exist AND belong to *design_system* (membership in its
    ``templates`` collection is the ownership check); anything else — deleted
    template, an id from a different design system, rows never materialized —
    returns ``None`` with a warning so generation falls back to the no-template
    path. Never raises for an invalid pin.
    """
    try:
        templates = materialize_templates(design_system)
    except Exception:
        logger.exception(
            "Failed to materialize templates for design system %s",
            getattr(design_system, "id", None),
        )
        templates = list(getattr(design_system, "templates", None) or [])

    for template in templates:
        if getattr(template, "id", None) == template_id:
            return template

    logger.warning(
        "Pinned template %s not found on design system %s; generating without a "
        "template",
        template_id,
        getattr(design_system, "id", None),
    )
    return None


def build_selected_template_block(template: Any) -> Optional[str]:
    """Render ONE pinned template as the SELECTED-TEMPLATE prompt block.

    Appended at prompt-assembly time (``agent_factory``) AFTER the design
    system's compiled artifact — never persisted into it. Returns ``None`` (=
    fall back to no-template behavior, logged) when the template has no usable
    layout or the layout exceeds :data:`MAX_TEMPLATE_LAYOUT_CHARS`.

    Deliberately a single function so a follow-up investigation can refine the
    wording/shape (archetype framing, trimming strategy, …) in one place.
    """
    layout_html = (getattr(template, "layout_html", None) or "").strip()
    name = (getattr(template, "name", None) or "").strip() or "Untitled template"
    if not layout_html:
        logger.warning(
            "Pinned template '%s' has no layout HTML; generating without a template", name
        )
        return None
    if len(layout_html) > MAX_TEMPLATE_LAYOUT_CHARS:
        logger.warning(
            "Pinned template '%s' layout is %d chars (cap %d); generating without a "
            "template",
            name,
            len(layout_html),
            MAX_TEMPLATE_LAYOUT_CHARS,
        )
        return None

    parts: list[str] = [f"SELECTED SLIDE TEMPLATE: {name}"]
    description = (getattr(template, "description", None) or "").strip()
    if description:
        parts.append(description)

    parts.append(
        "The user PINNED this template for this deck. It takes precedence over the "
        "SLIDE TEMPLATES list above — build every slide from THIS template's layout "
        "system."
    )
    token_css = (getattr(template, "token_css", None) or "").strip()

    instructions = [
        "HOW TO APPLY THE TEMPLATE:",
        "- The layout HTML below is an ARCHETYPE CATALOG (one sample slide per "
        "layout archetype), NOT a deck outline: for each slide you generate, pick "
        "the best-fitting archetype and slot the deck's ACTUAL content into its "
        "structure. Never copy the sample's text, slide order, or slide count.",
        "- Reproduce the template's structure, type scale, and component patterns: "
        "carry its <style> rules into every slide unchanged, put any additions in a "
        "separate <style> block after them, and never redefine the template's "
        "selectors.",
    ]
    if token_css:
        instructions.append(
            "- The template CSS reads design tokens via var(--...); include the TOKEN "
            "STYLESHEET definitions below in every slide so those references resolve."
        )
    instructions.extend(
        [
            "- Brand assets are referenced as {{ds-asset:ID}} handles — keep them "
            "exactly as written wherever you reuse them.",
            "- Vary archetypes across the deck to fit each slide's content; do not "
            "force every slide into the same archetype.",
        ]
    )
    parts.append("\n".join(instructions))

    if token_css:
        parts.append(
            "TOKEN STYLESHEET (the custom properties the template CSS depends on):\n"
            f"{token_css}"
        )

    parts.append(f"TEMPLATE LAYOUT HTML (archetype catalog):\n{layout_html}")
    parts.append("END OF SELECTED SLIDE TEMPLATE.")
    return "\n\n".join(parts)
