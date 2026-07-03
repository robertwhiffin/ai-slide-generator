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

Design decisions (Phase 2 RESET — README/SKILL-central, agentic, UNCAPPED, to
match the huashu / Claude-Design "brand operating manual" model):
- Output opens with ``SLIDE VISUAL STYLE:`` to match the ``DEFAULT_SLIDE_STYLE``
  convention (``src/core/defaults.py``) so it slots into the prompt identically.
- The FULL README then the FULL SKILL.md are injected FIRST as a BRAND MANUAL
  block — UNFILTERED and UNTRUNCATED (no rule-only keyword filter, no char
  budget). The README already documents the brand's assets/voice/rules, so there
  is no separate computed "map". ``recompute_compiled_style_content`` reads that
  text from the retained ``design_system_file`` rows and passes it IN, keeping
  ``compile_design_system`` a pure function of its arguments.
- ALL tokens are emitted UNCAPPED: color tokens as a human/LLM-readable spec
  grouped by group AND a ``:root { --brand-* }`` block (spec §8); type + spacing
  as rule lists; shadow tokens as ``--brand-shadow-*`` vars + a spec list.
- Fonts are emitted UNCAPPED: a @font-face reference list (font files -> their
  ``{{ds-asset:ID}}`` handles) plus a family listing enriched from
  ``font_mapping_json`` (family -> weight/style variants + linked tokens). Fonts
  are the ONE asset kind wired inline, because @font-face must resolve at
  generation time; there are few of them, so no cap is needed.
- Brand IMAGE assets are NOT enumerated. Instead the compiled content carries a
  short CONTRACT instructing the model to fetch them on demand via the
  ``search_brand_assets`` tool, which returns ``{{ds-asset:ID}}`` handles. This
  avoids dumping a large brand inventory (hundreds of assets) into every prompt.
- ``{{ds-asset:ID}}`` mirrors the existing ``{{image:ID}}`` convention
  (``src/utils/image_utils.py``) but is a DISTINCT namespace:
  ``design_system_asset`` IDs and ``image_assets`` IDs are independent sequences,
  so reusing ``{{image:ID}}`` would resolve to an unrelated image.
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

# Every token group the compiler emits: colors + shadows as :root custom
# properties, type + spacing as rules. Tokens in any other group are dropped from
# the prompt and a warning names them so authors notice rather than losing them
# silently.
_RECOGNIZED_GROUPS = frozenset(_COLOR_GROUPS + ("type", "spacing", "shadow"))

# Heading that frames the injected README + SKILL as the authoritative brand
# operating manual (the huashu / Claude-Design model). Injected FIRST, in FULL.
# NOTE: cross-cutting precedence over generic styling is stated ONCE — and
# unconditionally, so token-only design systems get it too — in
# ``prompt_modules.DESIGN_SYSTEM_PRECEDENCE`` (not here), to avoid a duplicate.
_BRAND_MANUAL_HEADING = (
    "BRAND MANUAL (the authoritative brand documentation for this design system — "
    "follow it):"
)

# Contract for brand IMAGE assets. They are NOT enumerated in the prompt (a real
# bundle ships hundreds); the model fetches them on demand via the
# ``search_brand_assets`` tool, which returns ``{{ds-asset:ID}}`` handles. This
# literal text is injected verbatim; the ``{{ds-asset:ID}}`` token round-trips
# through the system-prompt brace-escape (``agent.py``) exactly like
# ``{{image:ID}}``. Fonts are the ONE exception — wired inline via @font-face
# (see ``_font_assets_section``).
_ASSET_CONTRACT = (
    "BRAND IMAGE ASSETS:\n"
    "To place any brand image (logo, product icon, lockup, illustration, or "
    "background) from this design system, you MUST call the `search_brand_assets` "
    "tool to get its {{ds-asset:ID}} handle, then embed that handle — e.g. "
    '<img src="{{ds-asset:ID}}" alt="..." /> or '
    "background-image: url('{{ds-asset:ID}}'). Never invent an ID; only use "
    "handles the tool returned. Use assets in importance order "
    "(logo > product/lockup > icon > illustration > background) and never redraw "
    "them."
)


def _slug(value: str) -> str:
    """Slugify a token name for use in a CSS custom-property identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "token"


def _brand_manual_section(skill_md: Optional[str], readme_md: Optional[str]) -> Optional[str]:
    """Assemble the BRAND MANUAL block: the FULL README then the FULL SKILL.md.

    UNFILTERED and UNTRUNCATED — both documents are injected verbatim (the huashu
    / Claude-Design "brand operating manual" model). README is the primary
    operating manual, so it comes first; SKILL.md follows. Returns ``None`` when
    neither source contributes text, so a design system without a SKILL/README
    simply omits the block (backward compatible).
    """
    readme = (readme_md or "").strip()
    skill = (skill_md or "").strip()
    body_parts = [part for part in (readme, skill) if part]
    if not body_parts:
        return None
    return "\n\n".join([_BRAND_MANUAL_HEADING, *body_parts])


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


def _shadow_sections(grouped: dict[str, list[tuple[str, str]]]) -> list[str]:
    """Render shadow tokens as a spec list + a ``:root { --brand-shadow-* }`` block.

    Consistent with how color tokens render (spec §8): a human/LLM-readable list
    plus CSS custom properties, emitted UNCAPPED. Entries are pre-sorted (see
    ``_grouped_tokens``); the per-slug de-dup mirrors the color path so two names
    that slugify to the same identifier don't emit duplicate/ambiguous properties.
    """
    entries = grouped.get("shadow")
    if not entries:
        return []
    spec_lines = ["BRAND SHADOWS:"]
    css_vars: list[str] = []
    seen: set[str] = set()
    for name, value in entries:
        spec_lines.append(f"- {name}: {value}")
        slug = _slug(name)
        if slug in seen:
            continue
        seen.add(slug)
        css_vars.append(f"  --brand-shadow-{slug}: {value};")
    spec = "\n".join(spec_lines)
    css = "\n".join(
        [
            "Define these brand shadows as CSS custom properties on :root and "
            "reference them with var(--brand-shadow-*):",
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


def _font_families_section(design_system: Any) -> Optional[str]:
    """Render ``font_mapping_json`` families as a typography family listing.

    Richer than the raw ``type`` tokens: each family lists its weight/style
    variants and the tokens that reference it, so generated CSS can wire
    @font-face + font-family correctly. Families/variants/tokens are sorted for
    output independent of mapping order and emitted UNCAPPED. Reads the scalar
    ``font_mapping_json`` column (no lazy relationship). Returns ``None`` when the
    design system carries no font mapping (backward compatible).
    """
    mapping = getattr(design_system, "font_mapping_json", None)
    families = mapping.get("families") if isinstance(mapping, dict) else None
    if not isinstance(families, list):
        return None

    ordered = sorted(
        (f for f in families if isinstance(f, dict) and f.get("family")),
        key=lambda f: str(f.get("family")),
    )

    lines: list[str] = []
    for family in ordered:
        name = str(family.get("family"))
        variants = sorted(
            (v for v in (family.get("variants") or []) if isinstance(v, dict)),
            key=lambda v: (str(v.get("weight", "")), str(v.get("style", ""))),
        )
        variant_labels: list[str] = []
        for variant in variants:
            weight = str(variant.get("weight", "")).strip()
            style = (variant.get("style") or "").strip()
            variant_labels.append(" ".join(p for p in (weight, style) if p) or "regular")
        tokens = sorted(
            str(t) for t in (family.get("tokens") or []) if isinstance(t, str) and t.strip()
        )
        detail = f"- {name}"
        if variant_labels:
            detail += f": weights {', '.join(variant_labels)}"
        if tokens:
            detail += f" (tokens: {', '.join(tokens)})"
        lines.append(detail)

    if not lines:
        return None
    return "\n".join(
        ["BRAND FONT FAMILIES (load these families; apply them to the matching tokens):", *lines]
    )


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


def _font_assets_section(design_system: Any) -> Optional[str]:
    """Render font-kind assets as @font-face src references (``{{ds-asset:ID}}``).

    Fonts are the ONE asset kind wired inline (not fetched via the
    ``search_brand_assets`` tool): @font-face must resolve at generation time, and
    there are few of them, so the list is UNCAPPED. Each font file is mapped to its
    ``{{ds-asset:ID}}`` handle; assets without a persisted id are skipped. Sorted
    by (filename, id) for deterministic output. Returns ``None`` when the design
    system has no font assets.
    """
    fonts = [
        asset
        for asset in (getattr(design_system, "assets", None) or [])
        if getattr(asset, "id", None) is not None
        and (getattr(asset, "kind", "") or "") == "font"
    ]
    if not fonts:
        return None
    fonts.sort(key=lambda a: (getattr(a, "filename", "") or "", a.id))
    lines = [
        "BRAND FONTS:",
        "Load these font files via @font-face using the {{ds-asset:ID}} placeholder "
        "as the src url, e.g. @font-face { font-family: 'Brand'; "
        "src: url('{{ds-asset:1}}'); }:",
    ]
    for asset in fonts:
        filename = getattr(asset, "filename", "") or ""
        lines.append(f"- {filename} -> {DS_ASSET_PLACEHOLDER % asset.id}")
    return "\n".join(lines)


def compile_design_system(
    design_system: Any,
    *,
    skill_md: Optional[str] = None,
    readme_md: Optional[str] = None,
) -> str:
    """Serialize a structured design system into ``compiled_style_content``.

    Pure and deterministic. ``design_system`` is any object exposing ``name``,
    ``description``, ``manifest_json``, ``font_mapping_json``, and
    ``tokens``/``assets`` collections (i.e. a
    :class:`~src.database.models.design_system.DesignSystem`).

    ``skill_md`` / ``readme_md`` are the retained SKILL.md / README.md text
    (Phase 1 ``design_system_file`` rows). When provided they compile into the
    BRAND MANUAL block (FULL, first); both default ``None`` so a design system
    without them — or the legacy positional call — simply omits the block.

    Emitted order: header -> BRAND MANUAL (README + SKILL, full) -> description ->
    tokens (color, type, spacing, shadow; all uncapped) -> fonts (@font-face refs
    + family listing; uncapped) -> templates -> the brand IMAGE ASSET CONTRACT
    (fetch via ``search_brand_assets``). Brand images are NOT enumerated.
    """
    parts: list[str] = []

    name = getattr(design_system, "name", None) or "Design System"
    parts.append(f"{_STYLE_HEADER}: {name}")

    # The brand manual (FULL README + SKILL) is the FIRST authoritative content
    # block after the header — README first, before the description and tokens.
    brand_manual = _brand_manual_section(skill_md, readme_md)
    if brand_manual:
        parts.append(brand_manual)

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

    # Tokens: color, type, spacing, shadow — all uncapped.
    parts.extend(_color_sections(grouped))
    typography = _scale_section(grouped, "type", "TYPOGRAPHY TOKENS:")
    if typography:
        parts.append(typography)
    spacing = _scale_section(grouped, "spacing", "SPACING TOKENS:")
    if spacing:
        parts.append(spacing)
    parts.extend(_shadow_sections(grouped))

    # Fonts: inline @font-face references + family listing (both uncapped).
    font_assets = _font_assets_section(design_system)
    if font_assets:
        parts.append(font_assets)
    font_families = _font_families_section(design_system)
    if font_families:
        parts.append(font_families)

    template_section = _template_section(design_system)
    if template_section:
        parts.append(template_section)

    # Brand IMAGE assets are fetched on demand via search_brand_assets, not
    # enumerated. The contract is always present when a design system compiles.
    parts.append(_ASSET_CONTRACT)

    return "\n\n".join(parts)


def _brand_manual_text_from_files(
    design_system: Any,
) -> tuple[Optional[str], Optional[str]]:
    """Extract SKILL.md / README.md text from the retained ``design_system_file``
    rows (Phase 1) so the compiler can receive it as plain text.

    Reads the record's ``files`` collection — exactly how the compiler reads
    ``tokens``/``assets`` — decodes the in-DB bytes, and joins same-kind rows in
    path order (deterministic). Reference rows (asset/font; ``data`` is NULL) are
    ignored. Returns ``(skill, readme)``, each ``None`` when absent, so a legacy
    design system with no source files yields no BRAND MANUAL block.
    """
    skills: list[tuple[str, str]] = []
    readmes: list[tuple[str, str]] = []
    for ds_file in getattr(design_system, "files", None) or []:
        data = getattr(ds_file, "data", None)
        if data is None:
            continue
        kind = getattr(ds_file, "kind", "") or ""
        if kind not in ("skill", "readme"):
            continue
        if isinstance(data, (bytes, bytearray)):
            text = bytes(data).decode("utf-8", errors="replace")
        else:
            text = str(data)
        path = getattr(ds_file, "path", "") or ""
        (skills if kind == "skill" else readmes).append((path, text))

    def _join(rows: list[tuple[str, str]]) -> Optional[str]:
        if not rows:
            return None
        return "\n\n".join(text for _, text in sorted(rows, key=lambda row: row[0]))

    return _join(skills), _join(readmes)


def recompute_compiled_style_content(design_system: Any) -> str:
    """(Re)compute the compiled prompt text and store it on the record.

    Pulls the retained SKILL.md/README.md text from the design system's
    ``design_system_file`` rows and passes it to the pure compiler so the compiled
    artifact carries the BRAND MANUAL block. Sets
    ``design_system.compiled_style_content`` and returns the compiled string. The
    signature is unchanged, so every existing call site keeps working; a design
    system with no source files simply compiles without the block.
    """
    skill_md, readme_md = _brand_manual_text_from_files(design_system)
    compiled = compile_design_system(design_system, skill_md=skill_md, readme_md=readme_md)
    design_system.compiled_style_content = compiled
    return compiled
