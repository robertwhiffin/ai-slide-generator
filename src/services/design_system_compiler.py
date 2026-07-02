"""Compile a structured Design System into prompt text (Phase 2 linchpin).

See ``docs/technical/design-system-library-spec.md`` §8. Generation keys off the
existing ``slide_style_id`` seam: ``agent_factory._get_prompt_content`` fetches a
style's text and ``prompt_modules.build_generation_system_prompt`` appends it
verbatim. A structured design system has no such text, so this module serializes
its tokens/templates/assets into ``compiled_style_content`` — the drop-in
equivalent of ``slide_style_library.style_content``. Nothing downstream changes;
it just receives compiled text the same way it receives a hand-pasted blob today.

The serializer is **pure and deterministic**: it reads only the passed record's
attributes (no DB, no I/O, no clock/randomness) and imposes a fixed ordering, so
the same design system always compiles to byte-identical output.

Design decisions:
- Output opens with ``SLIDE VISUAL STYLE:`` to match the ``DEFAULT_SLIDE_STYLE``
  convention (``src/core/defaults.py``) so it slots into the prompt identically.
- Color tokens render both as a human/LLM-readable spec grouped by group AND as
  a ``:root { --brand-* }`` CSS custom-property block (spec §8).
- Brand assets are referenced with the ``{{ds-asset:ID}}`` placeholder. This
  mirrors the existing ``{{image:ID}}`` convention (``src/utils/image_utils.py``)
  but is a DISTINCT namespace: ``design_system_asset`` IDs and ``image_assets``
  IDs are independent sequences, so reusing ``{{image:ID}}`` would resolve to an
  unrelated image. Phase 3 wires the resolver/serving endpoint for this token.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Placeholder namespace for design-system brand assets (see module docstring).
# Phase 3 adds the substitution that swaps this for real asset bytes.
DS_ASSET_PLACEHOLDER = "{{ds-asset:%d}}"

# Opening marker — matches src/core/defaults.py::DEFAULT_SLIDE_STYLE so the
# compiled text is indistinguishable from a legacy style block in the prompt.
_STYLE_HEADER = "SLIDE VISUAL STYLE"

# Canonical color-group ordering -> deterministic, human-meaningful sections.
_COLOR_GROUPS = ("core", "accents", "ink", "tints")

# Every token group the compiler knows how to emit (colors as :root vars, type +
# spacing as rules). Tokens in any other group are dropped from the prompt; Phase 3
# adds a warning so authors notice rather than losing them silently.
_RECOGNIZED_GROUPS = frozenset(_COLOR_GROUPS + ("type", "spacing"))

# Asset kinds that are embeddable raster/vector images (referenced via <img> /
# CSS url()). ``font`` is handled separately (@font-face); ``template_shot`` is
# preview/reference material tied to templates and is never embedded as content.
_IMAGE_ASSET_KINDS = ("logo", "icon", "lockup", "illustration", "background")
_EXCLUDED_ASSET_KINDS = ("template_shot",)


def _slug(value: str) -> str:
    """Slugify a token name for use in a CSS custom-property identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "token"


def _grouped_tokens(design_system: Any) -> dict[str, list[tuple[str, str]]]:
    """Return ``group -> [(name, value), ...]`` with each list sorted by name.

    Sorting here is what makes the output order-independent of however the ORM
    relationship happened to load the rows.
    """
    grouped: dict[str, list[tuple[str, str]]] = {}
    for token in getattr(design_system, "tokens", None) or []:
        grouped.setdefault(token.group, []).append((token.name, token.value))
    for group in grouped:
        grouped[group].sort(key=lambda name_value: (name_value[0], name_value[1]))
    return grouped


def _color_sections(grouped: dict[str, list[tuple[str, str]]]) -> list[str]:
    """Build the textual color spec and the ``:root { --brand-* }`` var block."""
    spec_lines: list[str] = []
    css_vars: list[str] = []
    # Distinct token names can slugify to the same identifier (e.g. "Primary" and
    # "primary"); emitting both would produce duplicate/ambiguous CSS custom
    # properties, so a var is written once per (group, slug). The textual spec
    # still lists every original name. Entries are pre-sorted, so the first
    # occurrence wins deterministically.
    seen_vars: set[tuple[str, str]] = set()
    for group in _COLOR_GROUPS:
        entries = grouped.get(group)
        if not entries:
            continue
        spec_lines.append(f"- {group}:")
        for name, value in entries:
            spec_lines.append(f"  - {name}: {value}")
            slug = _slug(name)
            if (group, slug) in seen_vars:
                continue
            seen_vars.add((group, slug))
            css_vars.append(f"  --brand-{group}-{slug}: {value};")

    if not spec_lines:
        return []

    spec = "\n".join(["BRAND COLOR TOKENS:", *spec_lines])
    css = "\n".join(
        [
            "Define these brand colors as CSS custom properties on :root and "
            "reference them with var(--brand-*):",
            ":root {",
            *css_vars,
            "}",
        ]
    )
    return [spec, css]


def _scale_section(
    grouped: dict[str, list[tuple[str, str]]], group: str, heading: str
) -> Optional[str]:
    """Render a non-color token group (type/spacing) as a simple rule list."""
    entries = grouped.get(group)
    if not entries:
        return None
    lines = [heading]
    lines.extend(f"- {name}: {value}" for name, value in entries)
    return "\n".join(lines)


def _template_section(design_system: Any) -> Optional[str]:
    """Render named slide templates (from the manifest) as layout guidance.

    Template metadata lives in ``manifest_json['templates']`` as a list of
    ``{"name": ..., "description": ...}`` entries; malformed/nameless entries are
    skipped. Manifest list order is preserved (it is authored and deterministic).
    """
    manifest = getattr(design_system, "manifest_json", None)
    templates = manifest.get("templates") if isinstance(manifest, dict) else None
    if not isinstance(templates, list):
        return None

    lines: list[str] = []
    for entry in templates:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        description = entry.get("description")
        lines.append(f"- {name}: {description}" if description else f"- {name}")

    if not lines:
        return None
    return "\n".join(
        ["SLIDE TEMPLATES (use these named layouts as structural guidance):", *lines]
    )


def _asset_sort_key(asset: Any) -> tuple[str, str, int]:
    return (
        getattr(asset, "kind", "") or "",
        getattr(asset, "filename", "") or "",
        getattr(asset, "id", 0) or 0,
    )


def _asset_sections(design_system: Any) -> list[str]:
    """Render brand assets as ``{{ds-asset:ID}}`` reference instructions.

    Two sub-sections: embeddable images (<img>/CSS url) and fonts (@font-face).
    Assets without a persisted ``id`` can't be referenced and are skipped, as are
    ``template_shot`` previews. Deterministic order via ``_asset_sort_key``.
    """
    images: list[str] = []
    fonts: list[str] = []
    for asset in sorted(getattr(design_system, "assets", None) or [], key=_asset_sort_key):
        asset_id = getattr(asset, "id", None)
        if asset_id is None:
            continue
        kind = getattr(asset, "kind", "") or "asset"
        if kind in _EXCLUDED_ASSET_KINDS:
            continue
        filename = getattr(asset, "filename", "") or ""
        placeholder = DS_ASSET_PLACEHOLDER % asset_id
        if kind == "font":
            fonts.append(f"- [{kind}] {filename} -> {placeholder}")
        else:
            images.append(f"- [{kind}] {filename} -> {placeholder}")

    sections: list[str] = []
    if images:
        sections.append(
            "\n".join(
                [
                    "BRAND ASSETS:",
                    "Embed these brand assets as real images using the "
                    "{{ds-asset:ID}} placeholder (the system replaces it with the "
                    'actual asset), e.g. <img src="{{ds-asset:1}}" alt="logo" /> or '
                    "background-image: url('{{ds-asset:1}}'). Use ONLY the asset "
                    "IDs listed here; never invent IDs:",
                    *images,
                ]
            )
        )
    if fonts:
        sections.append(
            "\n".join(
                [
                    "BRAND FONTS:",
                    "Load these font assets via @font-face using the "
                    "{{ds-asset:ID}} placeholder as the src url, e.g. "
                    "@font-face { font-family: 'Brand'; "
                    "src: url('{{ds-asset:1}}'); }:",
                    *fonts,
                ]
            )
        )
    return sections


def compile_design_system(design_system: Any) -> str:
    """Serialize a structured design system into ``compiled_style_content``.

    Pure and deterministic. ``design_system`` is any object exposing ``name``,
    ``description``, ``manifest_json``, and ``tokens``/``assets`` collections
    (i.e. a :class:`~src.database.models.design_system.DesignSystem`).
    """
    parts: list[str] = []

    name = getattr(design_system, "name", None) or "Design System"
    parts.append(f"{_STYLE_HEADER}: {name}")

    description = getattr(design_system, "description", None)
    if description and description.strip():
        parts.append(description.strip())

    grouped = _grouped_tokens(design_system)

    # Surface (don't silently drop) tokens in groups the compiler can't emit.
    unrecognized = sorted(group for group in grouped if group not in _RECOGNIZED_GROUPS)
    if unrecognized:
        logger.warning(
            "Design system '%s' has token group(s) %s that the compiler does not "
            "emit; those tokens are omitted from the compiled style. Recognized "
            "groups: %s.",
            name,
            ", ".join(unrecognized),
            ", ".join(sorted(_RECOGNIZED_GROUPS)),
        )

    parts.extend(_color_sections(grouped))

    typography = _scale_section(grouped, "type", "TYPOGRAPHY TOKENS:")
    if typography:
        parts.append(typography)
    spacing = _scale_section(grouped, "spacing", "SPACING TOKENS:")
    if spacing:
        parts.append(spacing)

    template_section = _template_section(design_system)
    if template_section:
        parts.append(template_section)

    parts.extend(_asset_sections(design_system))

    return "\n\n".join(parts)


def recompute_compiled_style_content(design_system: Any) -> str:
    """(Re)compute the compiled prompt text and store it on the record.

    Sets ``design_system.compiled_style_content`` and returns the compiled string.
    This is the recompute primitive; the Phase 3 CRUD layer will call it on create
    and on every structural edit so the prompt artifact stays in sync.
    """
    compiled = compile_design_system(design_system)
    design_system.compiled_style_content = compiled
    return compiled
