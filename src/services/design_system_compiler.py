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
  a ``:root { --brand-* }`` CSS custom-property block (spec §8); shadow tokens
  render the same way as ``--brand-shadow-*`` vars + a spec list.
- SKILL.md (in full) + the README's RULE/GUIDANCE sections compile into a
  BRAND RULES / USAGE block near the top, hard-capped (``MAX_BRAND_RULES_CHARS``)
  with an explicit truncation marker so the prompt never carries the whole README.
  ``recompute_compiled_style_content`` reads that text from the retained
  ``design_system_file`` rows and passes it IN, keeping ``compile_design_system``
  a pure function of its arguments.
- Typography is enriched from ``font_mapping_json`` (family -> weight/style
  variants + the tokens that reference the family), richer than the raw ``type``
  tokens alone.
- Brand assets are RANKED (spec §4 Core Asset Protocol: Logo > product shot > UI
  > …) and CAPPED per category so a bundle carrying hundreds of assets can't bloat
  the prompt; any omission is disclosed rather than silent. Every count-bearing
  Phase-2 section is bounded the same way — assets, shadow tokens, and font
  families / per-family variants / per-family linked tokens — so no single such
  section can blow up the prompt (the brand-rules block is separately hard-capped
  in full). Assets are
  referenced with the ``{{ds-asset:ID}}`` placeholder. This mirrors the existing
  ``{{image:ID}}`` convention (``src/utils/image_utils.py``) but is a DISTINCT
  namespace: ``design_system_asset`` IDs and ``image_assets`` IDs are independent
  sequences, so reusing ``{{image:ID}}`` would resolve to an unrelated image.
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

# Asset kinds that are embeddable raster/vector images (referenced via <img> /
# CSS url()). ``font`` is handled separately (@font-face); ``template_shot`` is
# preview/reference material tied to templates and is never embedded as content.
_IMAGE_ASSET_KINDS = ("logo", "icon", "lockup", "illustration", "background")
_EXCLUDED_ASSET_KINDS = ("template_shot",)

# --- Phase 2 (v1): brand-rules budget + asset curation --------------------

# Hard cap on the injected BRAND RULES text (SKILL.md + README rule-sections).
# SKILL is emitted first (prioritized); the overflow — typically the README tail —
# is truncated with an explicit marker so the prompt never carries an unbounded
# multi-KB documentation dump. Read at call time so it stays tunable/testable.
MAX_BRAND_RULES_CHARS = 6000
_BRAND_RULES_TRUNCATION_MARKER = "\n…[truncated]"
# Stable heading for the block. The cap counts this against the budget, so the
# text stays concise to leave room for the actual rules.
_BRAND_RULES_HEADING = (
    "BRAND RULES / USAGE (follow these brand rules; they take precedence over "
    "generic styling):"
)

# Max references emitted per token/asset-driven section. Real bundles ship
# hundreds of assets, and a pathological manifest could declare arbitrarily many
# tokens/families, so every such section is ranked/sorted and capped — with the
# omission disclosed — so no single section can bloat the prompt with a flat dump.
MAX_IMAGE_ASSET_REFERENCES = 12
MAX_FONT_ASSET_REFERENCES = 8
MAX_SHADOW_TOKENS = 24
MAX_FONT_FAMILIES = 12
MAX_FONT_VARIANTS_PER_FAMILY = 12
MAX_FONT_TOKENS_PER_FAMILY = 12

# Brand-asset kind ranking — spec §4 "Core Asset Protocol": Logo > product shot >
# UI > icons > … . Lower rank = higher priority; unknown kinds sort after all
# known ones. The v1 importer (``design_system_service._infer_asset_kind``) only
# ever produces {logo, lockup, icon, illustration, background, font}, so those are
# the kinds actually ranked today; the product/ui/screenshot/wordmark aliases are
# forward-compat for structured/imported systems that carry the spec's own
# vocabulary (``design_system_asset.kind`` is a free string), each mapped to its
# spec tier so a cap keeps a product shot over an icon.
_ASSET_KIND_RANK = {
    # Logo tier
    "logo": 0,
    "wordmark": 0,
    "lockup": 1,
    # Product-shot / brand-imagery tier
    "product": 2,
    "product_shot": 2,
    "product-shot": 2,
    "photo": 2,
    "illustration": 3,
    "background": 4,
    # UI tier (screenshots, then icons)
    "ui": 5,
    "ui_screenshot": 5,
    "screenshot": 5,
    "icon": 6,
}
_UNKNOWN_ASSET_RANK = max(_ASSET_KIND_RANK.values()) + 1

# README headings whose section is a brand RULE / GUIDANCE (do's & don'ts,
# voice/tone, data-viz, usage/accessibility). Matched case-insensitively as a
# substring of the heading text; only these sections are injected — never the
# whole multi-KB README prose.
_README_RULE_KEYWORDS = (
    "rule",
    "guideline",
    "guidance",
    "do'",
    "don'",
    "dont",
    "do not",
    "dos and",
    "voice",
    "tone",
    "usage",
    "best practice",
    "avoid",
    "data viz",
    "data-viz",
    "dataviz",
    "data visual",
    "visualization",
    "visualisation",
    "chart",
    "accessib",
)


def _slug(value: str) -> str:
    """Slugify a token name for use in a CSS custom-property identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "token"


_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _is_rule_heading(title: str) -> bool:
    """True if a README heading names a brand RULE/GUIDANCE section."""
    low = title.lower()
    return any(keyword in low for keyword in _README_RULE_KEYWORDS)


def _extract_readme_rule_sections(readme_md: str) -> str:
    """Return only the RULE/GUIDANCE sections of a README, in document order.

    Each ATX heading (``#``..``######``) is evaluated independently: a heading is
    kept when its OWN text matches a rule keyword (:data:`_README_RULE_KEYWORDS`),
    and only its DIRECT content (the lines up to the NEXT heading of ANY level) is
    included. So a non-rule subsection nested under a rule heading (e.g.
    ``### History`` under ``## Usage``) is dropped, while a nested RULE subsection
    is still kept via its own heading. Overview/history/background prose is
    excluded — only concise brand rules reach the prompt. Pure and deterministic.
    """
    lines = (readme_md or "").splitlines()
    sections: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        match = _ATX_HEADING_RE.match(lines[i])
        if not match:
            i += 1
            continue
        keep = _is_rule_heading(match.group(2).strip())
        block = [lines[i]] if keep else []
        j = i + 1
        while j < n and not _ATX_HEADING_RE.match(lines[j]):
            if keep:
                block.append(lines[j])
            j += 1
        if keep:
            sections.append("\n".join(block).rstrip())
        i = j
    return "\n\n".join(sections).strip()


def _brand_rules_section(skill_md: Optional[str], readme_md: Optional[str]) -> Optional[str]:
    """Assemble the BRAND RULES / USAGE block: SKILL.md in full, then the README
    rule-sections, hard-capped so the FULL emitted block (heading + body +
    truncation marker) is <= :data:`MAX_BRAND_RULES_CHARS`.

    SKILL.md is the concise, authoritative rules doc, so it is emitted first and
    prioritized; when the block exceeds the budget the README tail is truncated
    with an explicit marker (never an unbounded dump). Returns ``None`` when
    neither source contributes text, so a design system without a SKILL/README
    simply omits the block (backward compatible).
    """
    skill = (skill_md or "").strip()
    readme_rules = _extract_readme_rule_sections(readme_md or "")

    body_parts: list[str] = []
    if skill:
        body_parts.append(skill)
    if readme_rules:
        body_parts.append(readme_rules)
    if not body_parts:
        return None
    body = "\n\n".join(body_parts)

    cap = MAX_BRAND_RULES_CHARS  # read at call time (tunable/testable)
    if cap <= 0:
        return None  # no budget -> omit the block entirely

    prefix = _BRAND_RULES_HEADING + "\n"
    marker = _BRAND_RULES_TRUNCATION_MARKER
    full = prefix + body

    # Genuine HARD cap on the FULL block: the returned block is <= cap for EVERY
    # non-negative cap. Emitted whole when it fits; otherwise reserve the marker
    # and truncate the body (SKILL is first, so the README tail drops, trimming
    # into the heading only for very small caps). When the cap is smaller than the
    # marker itself, the marker is truncated so the total still never exceeds cap.
    if len(full) <= cap:
        return full
    keep = cap - len(marker)
    if keep <= 0:
        return marker[:cap]
    return full[:keep].rstrip() + marker


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
    plus CSS custom properties. Entries are pre-sorted (see ``_grouped_tokens``);
    the per-slug de-dup mirrors the color path so two names that slugify to the
    same identifier don't emit duplicate/ambiguous custom properties.
    """
    entries = grouped.get("shadow")
    if not entries:
        return []
    omitted = max(0, len(entries) - MAX_SHADOW_TOKENS)
    spec_lines = ["BRAND SHADOWS:"]
    css_vars: list[str] = []
    seen: set[str] = set()
    for name, value in entries[:MAX_SHADOW_TOKENS]:
        spec_lines.append(f"- {name}: {value}")
        slug = _slug(name)
        if slug in seen:
            continue
        seen.add(slug)
        css_vars.append(f"  --brand-shadow-{slug}: {value};")
    if omitted:
        spec_lines.append(
            f"(+{omitted} more shadow token(s) omitted to keep the prompt focused.)"
        )
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
    output independent of mapping order, and every count is capped with disclosed
    omission — family count (``MAX_FONT_FAMILIES``), per-family variant count
    (``MAX_FONT_VARIANTS_PER_FAMILY``), and per-family linked-token count
    (``MAX_FONT_TOKENS_PER_FAMILY``) — so a pathological manifest can't blow up the
    section. Reads the scalar ``font_mapping_json`` column (no lazy relationship).
    Returns ``None`` when the design system carries no font mapping (backward
    compatible).
    """
    mapping = getattr(design_system, "font_mapping_json", None)
    families = mapping.get("families") if isinstance(mapping, dict) else None
    if not isinstance(families, list):
        return None

    ordered = sorted(
        (f for f in families if isinstance(f, dict) and f.get("family")),
        key=lambda f: str(f.get("family")),
    )
    family_omitted = max(0, len(ordered) - MAX_FONT_FAMILIES)

    lines: list[str] = []
    for family in ordered[:MAX_FONT_FAMILIES]:
        name = str(family.get("family"))
        variants = sorted(
            (v for v in (family.get("variants") or []) if isinstance(v, dict)),
            key=lambda v: (str(v.get("weight", "")), str(v.get("style", ""))),
        )
        variant_omitted = max(0, len(variants) - MAX_FONT_VARIANTS_PER_FAMILY)
        variant_labels: list[str] = []
        for variant in variants[:MAX_FONT_VARIANTS_PER_FAMILY]:
            weight = str(variant.get("weight", "")).strip()
            style = (variant.get("style") or "").strip()
            variant_labels.append(" ".join(p for p in (weight, style) if p) or "regular")
        tokens_all = sorted(
            str(t) for t in (family.get("tokens") or []) if isinstance(t, str) and t.strip()
        )
        token_omitted = max(0, len(tokens_all) - MAX_FONT_TOKENS_PER_FAMILY)
        tokens = tokens_all[:MAX_FONT_TOKENS_PER_FAMILY]
        detail = f"- {name}"
        if variant_labels:
            shown = ", ".join(variant_labels)
            if variant_omitted:
                shown += f", +{variant_omitted} more"
            detail += f": weights {shown}"
        if tokens:
            shown_tokens = ", ".join(tokens)
            if token_omitted:
                shown_tokens += f", +{token_omitted} more"
            detail += f" (tokens: {shown_tokens})"
        lines.append(detail)

    if not lines:
        return None
    section = [
        "BRAND FONT FAMILIES (load these families; apply them to the matching tokens):",
        *lines,
    ]
    if family_omitted:
        section.append(
            f"(+{family_omitted} more font families omitted to keep the prompt focused.)"
        )
    return "\n".join(section)


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


def _asset_rank_key(asset: Any) -> tuple[int, str, int]:
    """Rank images by kind priority (spec §4: Logo > product shot > UI > …), then
    filename + id for a stable total order (so curation/capping is deterministic)."""
    kind = getattr(asset, "kind", "") or ""
    return (
        _ASSET_KIND_RANK.get(kind, _UNKNOWN_ASSET_RANK),
        getattr(asset, "filename", "") or "",
        getattr(asset, "id", 0) or 0,
    )


def _font_sort_key(asset: Any) -> tuple[str, int]:
    return (getattr(asset, "filename", "") or "", getattr(asset, "id", 0) or 0)


def _asset_sections(design_system: Any) -> list[str]:
    """Render curated brand-asset references as ``{{ds-asset:ID}}`` instructions.

    Images are RANKED by kind priority (spec §4 Core Asset Protocol:
    Logo > product shot > UI icons > …) and CAPPED at
    ``MAX_IMAGE_ASSET_REFERENCES``; fonts are capped at
    ``MAX_FONT_ASSET_REFERENCES``. This keeps a bundle that ships hundreds of
    assets from bloating the prompt with a flat dump. Assets without a persisted
    ``id`` or of an excluded kind (``template_shot``) are skipped. Order + capping
    are deterministic (``_asset_rank_key`` / ``_font_sort_key``); any omission is
    disclosed rather than silent.
    """
    images: list[Any] = []
    fonts: list[Any] = []
    for asset in getattr(design_system, "assets", None) or []:
        if getattr(asset, "id", None) is None:
            continue
        kind = getattr(asset, "kind", "") or "asset"
        if kind in _EXCLUDED_ASSET_KINDS:
            continue
        (fonts if kind == "font" else images).append(asset)

    images.sort(key=_asset_rank_key)
    fonts.sort(key=_font_sort_key)
    image_omitted = max(0, len(images) - MAX_IMAGE_ASSET_REFERENCES)
    font_omitted = max(0, len(fonts) - MAX_FONT_ASSET_REFERENCES)

    def _ref(asset: Any) -> str:
        kind = getattr(asset, "kind", "") or "asset"
        filename = getattr(asset, "filename", "") or ""
        return f"- [{kind}] {filename} -> {DS_ASSET_PLACEHOLDER % asset.id}"

    sections: list[str] = []
    if images:
        lines = [
            "BRAND ASSETS:",
            "Embed these brand assets as real images using the "
            "{{ds-asset:ID}} placeholder (the system replaces it with the "
            'actual asset), e.g. <img src="{{ds-asset:1}}" alt="logo" /> or '
            "background-image: url('{{ds-asset:1}}'). Use ONLY the asset "
            "IDs listed here; never invent IDs:",
        ]
        lines.extend(_ref(asset) for asset in images[:MAX_IMAGE_ASSET_REFERENCES])
        if image_omitted:
            lines.append(
                f"(+{image_omitted} more brand asset(s) omitted to keep the prompt "
                "focused; the most important assets are listed above.)"
            )
        sections.append("\n".join(lines))
    if fonts:
        lines = [
            "BRAND FONTS:",
            "Load these font assets via @font-face using the "
            "{{ds-asset:ID}} placeholder as the src url, e.g. "
            "@font-face { font-family: 'Brand'; "
            "src: url('{{ds-asset:1}}'); }:",
        ]
        lines.extend(_ref(asset) for asset in fonts[:MAX_FONT_ASSET_REFERENCES])
        if font_omitted:
            lines.append(
                f"(+{font_omitted} more font(s) omitted to keep the prompt focused.)"
            )
        sections.append("\n".join(lines))
    return sections


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
    (Phase 1 ``design_system_file`` rows). When provided they compile into a
    BRAND RULES / USAGE block near the top; both default ``None`` so a design
    system without them — or the legacy positional call — simply omits the block.
    """
    parts: list[str] = []

    name = getattr(design_system, "name", None) or "Design System"
    parts.append(f"{_STYLE_HEADER}: {name}")

    description = getattr(design_system, "description", None)
    if description and description.strip():
        parts.append(description.strip())

    # Brand rules sit near the top so they frame everything that follows.
    brand_rules = _brand_rules_section(skill_md, readme_md)
    if brand_rules:
        parts.append(brand_rules)

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
    font_families = _font_families_section(design_system)
    if font_families:
        parts.append(font_families)
    spacing = _scale_section(grouped, "spacing", "SPACING TOKENS:")
    if spacing:
        parts.append(spacing)

    parts.extend(_shadow_sections(grouped))

    template_section = _template_section(design_system)
    if template_section:
        parts.append(template_section)

    parts.extend(_asset_sections(design_system))

    return "\n\n".join(parts)


def _brand_rules_text_from_files(
    design_system: Any,
) -> tuple[Optional[str], Optional[str]]:
    """Extract SKILL.md / README.md text from the retained ``design_system_file``
    rows (Phase 1) so the compiler can receive it as plain text.

    Reads the record's ``files`` collection — exactly how the compiler reads
    ``tokens``/``assets`` — decodes the in-DB bytes, and joins same-kind rows in
    path order (deterministic). Reference rows (asset/font; ``data`` is NULL) are
    ignored. Returns ``(skill, readme)``, each ``None`` when absent, so a legacy
    design system with no source files yields no BRAND RULES block.
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
    artifact carries the BRAND RULES / USAGE block. Sets
    ``design_system.compiled_style_content`` and returns the compiled string. The
    signature is unchanged, so every existing call site keeps working; a design
    system with no source files simply compiles without the block.
    """
    skill_md, readme_md = _brand_rules_text_from_files(design_system)
    compiled = compile_design_system(design_system, skill_md=skill_md, readme_md=readme_md)
    design_system.compiled_style_content = compiled
    return compiled
