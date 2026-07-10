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
  ``assets/…``) in ``src``/``href``/``poster``/``srcset`` attributes AND CSS
  ``url()``. :func:`rewrite_template_asset_refs` maps those to the design
  system's stored assets and rewrites them to ``{{ds-asset:ID}}`` so the
  existing resolver (``src.utils.ds_asset_utils``) renders them. Unresolvable
  RELATIVE refs become an inert ``data:,`` placeholder (logged, never a crash;
  an unresolvable ``srcset`` entry drops the whole attribute); absolute
  URLs/anchors are left untouched. Hardening on the same pass: preview-chrome
  ``<script>``/``<object>``/``<embed>``/``<iframe>`` elements and inline
  ``on*=`` handlers are stripped and ``javascript:`` URLs neutralized — picker
  chrome and active content never reach the model. Rewriting happens ONCE, at
  materialization, into the stored ``layout_html``/``token_css`` (deterministic;
  re-derivable by deleting the rows).

- **Consumption**: :func:`build_selected_template_block` renders ONE pinned
  template as a clearly-delimited SELECTED-TEMPLATE prompt block — the layout
  HTML as an edit-in-place STARTING FILE plus the token stylesheet its
  ``var(--…)`` refs depend on. The framing mirrors the live Claude Design
  probe: their platform seeds the template files into the project and directs
  the model to EDIT THE COPY IN PLACE (which measurably produced literal
  structural reuse); our one-shot injection plays the role of that file-seeding
  (there is no project FS here), so the directive flips accordingly. It is
  appended at PROMPT-ASSEMBLY time by ``agent_factory._get_prompt_content``;
  the persisted per-design-system ``compiled_style_content`` stays
  template-agnostic. The block is deliberately ONE function so its
  wording/shape can be swapped without touching the plumbing around it.

Everything here is brand-neutral engine code; no brand content is embedded.
"""
from __future__ import annotations

import logging
import posixpath
import re
from typing import Any, Optional
from urllib.parse import unquote

from src.database.models.design_system import DesignSystemTemplate
from src.services.design_system_compiler import DESIGN_SYSTEM_SCOPE_FIREWALL

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

# Active embedded content stripped like <script> (hardening on the org-trusted
# surface — belt-and-braces, not a full sanitizer): paired object/iframe first,
# then any stragglers (void <embed>, unclosed tags, orphan closers).
_EMBEDDED_CONTENT_TAG_RE = re.compile(
    r"<(object|iframe)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
_LONE_EMBEDDED_TAG_RE = re.compile(r"</?(?:object|embed|iframe)\b[^>]*>", re.IGNORECASE)

# Inline event-handler attributes (onclick=/onerror=/…), quoted or bare.
_EVENT_HANDLER_ATTR_RE = re.compile(
    r"\son[a-z0-9]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE
)

# script-scheme URLs (javascript:/vbscript:), matched after stripping the
# whitespace/control characters attackers use to split the scheme.
_SCRIPT_SCHEME_RE = re.compile(r"^(?:javascript|vbscript):", re.IGNORECASE)

# src/href/poster attribute refs in the entry HTML.
_ATTR_REF_RE = re.compile(
    r"(?P<prefix>\b(?P<name>src|href|poster)\s*=\s*(?P<q>[\"']))(?P<ref>[^\"']*)(?P=q)",
    re.IGNORECASE,
)

# Unquoted src/href/poster values (``href=javascript:...``) bypass
# _ATTR_REF_RE. This narrower companion exists only to NEUTRALIZE
# script-scheme values — benign unquoted refs are left untouched (rewriting
# them to handles is not worth the regex ambiguity on this trusted surface).
_UNQUOTED_ATTR_REF_RE = re.compile(
    r"\b(?P<name>src|href|poster)\s*=\s*(?P<ref>[^\s\"'>][^\s>]*)",
    re.IGNORECASE,
)

# srcset carries a comma-separated list of "url [descriptor]" entries — handled
# by a dedicated pass because the generic attr pattern rewrites single refs.
_SRCSET_ATTR_RE = re.compile(
    r"\ssrcset\s*=\s*(?P<q>[\"'])(?P<val>[^\"']*)(?P=q)", re.IGNORECASE
)

# CSS url() refs — both in <style> blocks and inline style="" attributes.
_CSS_URL_RE = re.compile(r"url\(\s*(?P<q>[\"']?)(?P<ref>[^\"')]+)(?P=q)\s*\)", re.IGNORECASE)

# QUOTED CSS url() refs whose value may contain ``)`` — invisible to
# _CSS_URL_RE (its ref class excludes the paren), which let
# ``url("javascript:alert(1)")`` bypass neutralization. Used by a
# defang-only pre-pass: script-scheme matches are neutralized, everything
# else keeps whatever treatment _CSS_URL_RE gives it (no rewriting here —
# widening the main pattern would change behavior for benign parenthesized
# refs, which is beyond this trusted surface's needs).
_QUOTED_CSS_URL_RE = re.compile(
    r"url\(\s*(?P<q>[\"'])(?P<ref>[^\"']*)(?P=q)\s*\)", re.IGNORECASE
)


def _is_script_scheme_url(ref: str) -> bool:
    """True for javascript:/vbscript: URLs, including whitespace-split forms."""
    return bool(_SCRIPT_SCHEME_RE.match(re.sub(r"[\s\x00-\x1f]+", "", ref or "")))


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

    Covers ``src``/``href``/``poster``/``srcset`` attributes and CSS ``url()``
    refs (the real export uses both). Refs that resolve to a stored asset
    become handles the existing resolver renders; an unresolvable RELATIVE ref
    becomes the inert ``data:,`` placeholder (logged — never a crash) — href
    included, since a relative href is an asset ref this rewrite claims to
    cover. Absolute URLs, ``mailto:``, and ``#`` anchors are not asset refs and
    are left untouched. An unresolvable relative ``srcset`` entry drops the
    whole attribute instead (a ``data:,`` srcset is useless).

    Hardening (org-trusted surface, belt-and-braces — no sanitizer dependency):
    ``<script>``/``<object>``/``<embed>``/``<iframe>`` elements and inline
    ``on*=`` event-handler attributes are stripped (template folders ship
    preview chrome that must never reach the model), and ``javascript:`` URLs
    are neutralized to the placeholder in the covered attributes (quoted or
    unquoted) and in CSS ``url()`` refs.
    """
    if not text:
        return text

    text = _SCRIPT_TAG_RE.sub("", text)
    text = _EMBEDDED_CONTENT_TAG_RE.sub("", text)
    text = _LONE_EMBEDDED_TAG_RE.sub("", text)
    text = _EVENT_HANDLER_ATTR_RE.sub("", text)

    def _replace_unquoted_attr(match: "re.Match[str]") -> str:
        if not _is_script_scheme_url(match.group("ref")):
            return match.group(0)
        logger.warning(
            "Template %s ref uses an unquoted script-scheme URL; replaced with "
            "an inert placeholder",
            match.group("name").lower(),
        )
        return f'{match.group("name")}="{_UNRESOLVED_PLACEHOLDER}"'

    text = _UNQUOTED_ATTR_REF_RE.sub(_replace_unquoted_attr, text)

    def _replace_srcset(match: "re.Match[str]") -> str:
        entries = [e.strip() for e in match.group("val").split(",") if e.strip()]
        if not entries:
            return match.group(0)
        rewritten: list[str] = []
        for entry in entries:
            pieces = entry.split(None, 1)
            url = pieces[0]
            descriptor = f" {pieces[1].strip()}" if len(pieces) > 1 else ""
            if _is_script_scheme_url(url):
                logger.warning(
                    "Template srcset entry '%s' uses a script-scheme URL; dropping "
                    "the srcset attribute",
                    url,
                )
                return ""
            if not _looks_rewritable(url):
                rewritten.append(f"{url}{descriptor}")
                continue
            asset_id = _resolve_asset_id(url, base_dir, asset_ids_by_path)
            if asset_id is None:
                logger.warning(
                    "Template srcset entry '%s' does not match any stored "
                    "design-system asset; dropping the srcset attribute",
                    url,
                )
                return ""
            rewritten.append(f"{{{{ds-asset:{asset_id}}}}}{descriptor}")
        quote = match.group("q")
        return f" srcset={quote}{', '.join(rewritten)}{quote}"

    def _replace_attr(match: "re.Match[str]") -> str:
        ref = match.group("ref")
        if _is_script_scheme_url(ref):
            logger.warning(
                "Template %s ref uses a javascript:-style URL; replaced with an "
                "inert placeholder",
                match.group("name").lower(),
            )
            return f"{match.group('prefix')}{_UNRESOLVED_PLACEHOLDER}{match.group('q')}"
        if not _looks_rewritable(ref):
            return match.group(0)
        asset_id = _resolve_asset_id(ref, base_dir, asset_ids_by_path)
        if asset_id is not None:
            return f"{match.group('prefix')}{{{{ds-asset:{asset_id}}}}}{match.group('q')}"
        logger.warning(
            "Template asset ref '%s' does not match any stored design-system asset; "
            "replaced with an inert placeholder",
            ref,
        )
        return f"{match.group('prefix')}{_UNRESOLVED_PLACEHOLDER}{match.group('q')}"

    def _defang_quoted_css_url(match: "re.Match[str]") -> str:
        if not _is_script_scheme_url(match.group("ref").strip()):
            return match.group(0)
        logger.warning(
            "Template CSS url() ref uses a script-scheme URL; replaced "
            "with an inert placeholder"
        )
        quote = match.group("q")
        return f"url({quote}{_UNRESOLVED_PLACEHOLDER}{quote})"

    def _replace_url(match: "re.Match[str]") -> str:
        ref = match.group("ref").strip()
        quote = match.group("q")
        if _is_script_scheme_url(ref):
            logger.warning(
                "Template CSS url() ref uses a script-scheme URL; replaced "
                "with an inert placeholder"
            )
            return f"url({quote}{_UNRESOLVED_PLACEHOLDER}{quote})"
        if not _looks_rewritable(ref):
            return match.group(0)
        asset_id = _resolve_asset_id(ref, base_dir, asset_ids_by_path)
        if asset_id is not None:
            return f"url({quote}{{{{ds-asset:{asset_id}}}}}{quote})"
        logger.warning(
            "Template CSS url ref '%s' does not match any stored design-system asset; "
            "replaced with an inert placeholder",
            ref,
        )
        return f"url({quote}{_UNRESOLVED_PLACEHOLDER}{quote})"

    text = _SRCSET_ATTR_RE.sub(_replace_srcset, text)
    text = _ATTR_REF_RE.sub(_replace_attr, text)
    text = _QUOTED_CSS_URL_RE.sub(_defang_quoted_css_url, text)
    return _CSS_URL_RE.sub(_replace_url, text)


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------


# <style> blocks inside a template's layout HTML (the ONE inline stylesheet
# Claude-Design exports ship, but any count is handled).
_STYLE_BLOCK_RE = re.compile(
    r"(?P<open><style\b[^>]*>)(?P<css>.*?)(?P<close></style\s*>)",
    re.IGNORECASE | re.DOTALL,
)

# Opening tags that carry a class attribute — used to find which TAGS the
# template uses as slide roots (elements classed ``slide``).
_CLASSED_TAG_RE = re.compile(
    r"<(?P<tag>[a-zA-Z][a-zA-Z0-9-]*)\b[^>]*\bclass\s*=\s*([\"'])(?P<classes>[^\"']*)\2",
    re.IGNORECASE,
)

# Everything between the previous block boundary and an opening ``{`` — the
# candidate rule prelude (selector list or at-rule head).
_CSS_PRELUDE_RE = re.compile(r"(?P<prelude>[^{}]+)\{")


def _detect_slide_root_tags(layout_html: str) -> frozenset:
    """Tags the template itself uses as slide roots (elements classed ``slide``)."""
    tags = set()
    for match in _CLASSED_TAG_RE.finditer(layout_html):
        if "slide" in match.group("classes").split():
            tags.add(match.group("tag").lower())
    return frozenset(tags)


def _augment_selector_list(selector_list: str, root_tags: frozenset) -> str:
    """Append a ``.slide``-keyed parallel for each selector keyed on a root tag.

    ``section .title`` gains ``.slide .title``; ``section.dark`` gains
    ``.slide.dark``. Tag tokens are matched with identifier boundaries so
    class/id names that merely CONTAIN the tag (``.section-title``) are left
    alone. Idempotent: a parallel already present is not appended again.
    """
    parts = [part.strip() for part in selector_list.split(",") if part.strip()]
    augmented = list(parts)
    for part in parts:
        for tag in sorted(root_tags):
            tag_token = re.compile(rf"(?<![\w.#-]){re.escape(tag)}(?![\w-])")
            if not tag_token.search(part):
                continue
            parallel = tag_token.sub(".slide", part)
            if parallel not in augmented:
                augmented.append(parallel)
    return ", ".join(augmented)


def normalize_root_tag_selectors(layout_html: str) -> str:
    """Make tag-keyed template CSS also match class-keyed generated roots.

    dsv2 battery F7: templates key typography on their root TAG
    (``section { font-family: var(--font-sans) }``, roots being
    ``<section class="slide">``), but generation emits ``<div class="slide">``
    roots — the selector never matches and pinned decks render in the UA
    serif. Every rule keyed on a tag the template uses as a slide root gains a
    ``.slide``-keyed parallel selector, inside every ``<style>`` block
    (at-rule preludes are skipped; rules nested in ``@media`` are reached
    because their preludes parse like top-level ones). Plain-CSS selector
    lists only — functional pseudo-class argument lists (``:is(a, b)``) are
    beyond this trusted surface's needs. Idempotent, so it doubles as the
    lazy self-heal pass for rows materialized before it existed.
    """
    root_tags = _detect_slide_root_tags(layout_html)
    if not root_tags:
        return layout_html

    def _rewrite_css(css_text: str) -> str:
        def _rewrite_prelude(match: "re.Match[str]") -> str:
            prelude = match.group("prelude")
            # Only the text after the previous block close is the selector.
            head, brace, selector = prelude.rpartition("}")
            stripped = selector.strip()
            if not stripped or stripped.startswith("@"):
                return match.group(0)
            leading = selector[: len(selector) - len(selector.lstrip())]
            trailing = selector[len(selector.rstrip()):]
            rebuilt = _augment_selector_list(stripped, root_tags)
            return f"{head}{brace}{leading}{rebuilt}{trailing}{{"

        return _CSS_PRELUDE_RE.sub(_rewrite_prelude, css_text)

    def _rewrite_style_block(match: "re.Match[str]") -> str:
        return f"{match.group('open')}{_rewrite_css(match.group('css'))}{match.group('close')}"

    return _STYLE_BLOCK_RE.sub(_rewrite_style_block, layout_html)


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
        # Lazy self-heal (the compiler's recompute-on-read discipline): rows
        # materialized before root-tag selector normalization existed carry
        # tag-keyed CSS that never matches generated <div class="slide">
        # roots. The pass is idempotent, so healed rows read as no-ops and
        # only stale ones are rewritten (persisted by the calling session).
        for template in existing:
            layout_html = getattr(template, "layout_html", None) or ""
            normalized = normalize_root_tag_selectors(layout_html)
            if normalized != layout_html:
                template.layout_html = normalized
                logger.info(
                    "Design system %s: normalized root-tag selectors in stored "
                    "template '%s'",
                    getattr(design_system, "id", None),
                    getattr(template, "name", None),
                )
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
        layout_html = normalize_root_tag_selectors(
            rewrite_template_asset_refs(
                _decode_file_text(entry_files[entry_path]) or "",
                base_dir=template_dir,
                asset_ids_by_path=asset_ids_by_path,
            )
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

    Framing (Round 2, reconciled with the live Claude Design probe): the layout
    is an edit-in-place STARTING FILE. Their platform seeds the template files
    into the project and directs the model to EDIT THE COPY IN PLACE — a frame
    that measurably produced literal structural reuse (byte-identical style
    block, class-subset, sample content treated as placeholder). Our one-shot
    injection stands in for that file-seeding (no project FS here), so the
    primary directive says exactly that; the Round-1 guards survive, restated
    in this frame. The content/style scope firewall
    (``DESIGN_SYSTEM_SCOPE_FIREWALL``) rides here AND once in the compiled
    artifact.

    Deliberately a single function so a follow-up investigation can refine the
    wording/shape (framing, trimming strategy, …) in one place.
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

    parts.append(
        f"The user chose the {name} template. The HTML below is your STARTING FILE "
        "— produce the deck by editing it: replace its placeholder content with "
        "the requested content, keep its classes, CSS, and structure intact, and "
        "trim or repeat its slide sections to fit the requested slide count."
    )

    token_css = (getattr(template, "token_css", None) or "").strip()

    instructions = [
        "HOW TO EDIT THE STARTING FILE:",
        "- Everything the template ships as content — sample text, numbers, names, "
        "data — is PLACEHOLDER, never fact: replace it with the requested content.",
        "- Omit sample sections you have no content for rather than inventing "
        "filler.",
        "- Keep the template's <style> rules intact; put any additional CSS in a "
        "separate <style> block below it and never redefine the template's "
        "selectors.",
        "- Keep the template's own heading/title sizes; never shrink type below "
        "them to fit more content — trim or split across slides instead.",
    ]
    if token_css:
        instructions.append(
            "- Carry the TOKEN STYLESHEET definitions below into the emitted deck's "
            "CSS on every slide so every var(--...) reference resolves."
        )
    instructions.extend(
        [
            "- Brand assets are referenced as {{ds-asset:ID}} handles — keep them "
            "exactly as written wherever you reuse them.",
            "- When the deck has more slides than the template has sections, vary "
            "which slide sections you reuse rather than repeating one.",
            f"- {DESIGN_SYSTEM_SCOPE_FIREWALL}",
        ]
    )
    parts.append("\n".join(instructions))

    if token_css:
        parts.append(
            "TOKEN STYLESHEET (the custom properties the template CSS depends on):\n"
            f"{token_css}"
        )

    parts.append(f"TEMPLATE STARTING FILE (edit this HTML in place):\n{layout_html}")
    parts.append("END OF SELECTED SLIDE TEMPLATE.")
    return "\n\n".join(parts)
