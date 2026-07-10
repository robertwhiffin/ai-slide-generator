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
- A short description caption comes first; the FULL README then the FULL
  SKILL.md follow as the first SUBSTANTIVE block — a BRAND MANUAL, UNFILTERED
  and UNTRUNCATED (no rule-only keyword filter, no char budget). The README
  already documents the brand's assets/voice/rules, so there is no separate
  computed "map". ``recompute_compiled_style_content`` reads that text from the
  retained ``design_system_file`` rows and passes it IN, keeping
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
- SLIDE FRAME CONSTRAINTS (Phase 3) are always appended (just before the asset
  contract): a DS deck bypasses ``DEFAULT_SLIDE_STYLE``, so the compiled content
  must itself carry the fixed 1280x720 frame rules + soft safe-area guidance to
  keep the model frame-aware. Compiler-emitted (not ``prompt_modules``) so the
  no-DS / legacy prompts stay byte-identical. The block is PROSE ONLY — it states
  outcomes, never CSS rule prescriptions or a wrapper-class assumption (the model
  writes freehand HTML).
- The header line is stamped with a compiler-version marker so consumers of the
  PERSISTED artifact can detect rows compiled by an OLDER compiler (e.g. rows
  compiled before the frame guardrails existed) via
  ``compiled_style_content_is_current`` and lazily recompute them on read
  (``agent_factory._get_prompt_content``). Deliberately NO batch backfill.
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

# Version of the compiled-artifact format, stamped into the header line of every
# compiled output. Consumers of the PERSISTED ``compiled_style_content``
# (``agent_factory._get_prompt_content``) treat a row whose text lacks the
# CURRENT marker as stale — which covers rows compiled before versioning existed
# (implicitly v1: the pre-frame-guardrail Phase 2/3 artifacts carry no marker) —
# and lazily recompute it from the row's persisted tokens/files/assets via
# ``recompute_compiled_style_content``. Bump the version whenever the compiled
# output changes in a way persisted rows must pick up (new/changed blocks).
# v3: content/style scope firewall + the templates section's soft-pick enabler
# (Round 2 — reconciled with the live Claude Design probe).
# v4: BRAND TYPE SCALE block (ramp derived from the DS's own font-size tokens,
# neutral default bands when no ramp is recognizable) + the frame block's
# overflow line no longer suggests scaling content down.
# v5: BRAND MANUAL is built from ROOT-level README/SKILL only — nested
# component docs (e.g. a ui-kit folder's README) no longer pollute it.
# v6: frame block adds two hard rules (dsv2 battery F3): the slide root
# carries NO outer margin (print-preview roots shifted content past the 720px
# clip on every surface), and decorative imagery never overlaps text content
# (cover-art bled over titles/subtitles/list items).
COMPILER_VERSION = 6
_COMPILER_VERSION_MARKER = f"[ds-compiler v{COMPILER_VERSION}]"

# Canonical color-group ordering -> deterministic, human-meaningful sections.
_COLOR_GROUPS = ("core", "accents", "ink", "tints")

# Every token group the compiler emits: colors + shadows as :root custom
# properties, type + spacing as rules. Tokens in any other group are dropped from
# the prompt and a warning names them so authors notice rather than losing them
# silently.
_RECOGNIZED_GROUPS = frozenset(_COLOR_GROUPS + ("type", "spacing", "shadow"))

# Heading that frames the injected README + SKILL as the authoritative brand
# operating manual (the huashu / Claude-Design model). Injected in FULL as the
# first substantive block (right after the short description caption).
# NOTE: cross-cutting precedence over generic styling is stated ONCE — and
# unconditionally, so token-only design systems get it too — in
# ``prompt_modules.DESIGN_SYSTEM_PRECEDENCE`` (not here), to avoid a duplicate.
_BRAND_MANUAL_HEADING = (
    "BRAND MANUAL (the authoritative brand documentation for this design system — "
    "follow it):"
)

# Content/style scope firewall, adopted from the live Claude Design probe: their
# pinned-template mechanism ships this guard so seeded brand prose/templates are
# never mistaken for facts about the user's request. Emitted UNCONDITIONALLY
# (right after the brand manual's slot) so token-only systems get it too, and
# PUBLIC because the pinned-template block (``design_system_templates``)
# restates the same sentence next to the injected starting file.
DESIGN_SYSTEM_SCOPE_FIREWALL = (
    "Never treat anything in the design system — its README, its templates, or "
    "their sample content — as a fact about the user or the topic; it governs "
    "STYLE only."
)

# Closes the SLIDE TEMPLATES section, matching Claude Design's none-path: with
# no pinned template the model soft-picks a listed template when one fits.
_TEMPLATE_SOFT_PICK_LINE = (
    "Start from the best-matching template above if one fits the request."
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

# Frame guardrails (Phase 3). A design-system deck injects this compiled content
# and BYPASSES ``DEFAULT_SLIDE_STYLE`` (``src/core/defaults.py``) — the only place
# the slide frame + content limits used to live — so without this block the model
# generates blind to the 1280x720 ceiling and the export clips it (the "cut off" /
# "massive long slide" symptom). Emitting it here (in ``compiled_style_content``,
# NOT ``prompt_modules``) keeps the legacy custom-system-prompt path and the no-DS
# golden prompts BYTE-IDENTICAL. Always present when a design system compiles (like
# the asset contract). The WHOLE block is PROSE ONLY: the model writes freehand
# HTML, so the block states outcomes (exact frame size, clipped overflow) without
# prescribing CSS rules or assuming any wrapper class such as ``.slide`` — and the
# safe area stays SOFT prose with no injected padding CSS, which would break
# full-bleed backgrounds (structural safe-area is Phase 4 template CSS).
# "no in-slide scrolling" is deliberately per-slide so it does not contradict
# ``prompt_modules.HTML_OUTPUT_FORMAT``'s vertically-stacked-slides deck page.
_SLIDE_FRAME_CONSTRAINTS = (
    "SLIDE FRAME CONSTRAINTS:\n"
    "- Every slide renders into a FIXED 1280x720px frame (16:9). The frame never "
    "grows to fit content.\n"
    "- Size each slide's root element to exactly 1280 by 720 pixels and make it "
    "clip its own overflow — do not rely on any particular class name or wrapper "
    "structure; whatever the slide's outermost element is, anything past its frame "
    "must be CLIPPED on export, never scrolled.\n"
    "- One slide per frame: fit ALL of that slide's content inside its single "
    "1280x720 frame, with no in-slide scrolling. If content would overflow, trim "
    "it or split it across additional slides until it fits — NEVER shrink type "
    "below the BRAND TYPE SCALE to make room.\n"
    "- Safe area (soft guidance): keep primary content (titles, body text, charts, "
    "tables) roughly 72px clear of the top and bottom edges and 88px clear of the "
    "left and right edges; let only full-bleed backgrounds or images reach the "
    "slide edges.\n"
    "- The slide's root element carries NO outer margin: it starts at the very "
    "top-left corner of its frame. Styling the root like a floating print-preview "
    "card shifts everything past the frame edge, and the bottom of the slide gets "
    "clipped on every surface and in every export.\n"
    "- Decorative imagery (cover art, corner motifs, background illustrations) "
    "must never overlap text content: keep titles, subtitles, list items, and "
    "footers fully clear of any artwork layer."
)


def _slug(value: str) -> str:
    """Slugify a token name for use in a CSS custom-property identifier."""
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "token"


# BRAND TYPE SCALE (the "small titles" fix). A DS deck bypasses
# ``DEFAULT_SLIDE_STYLE`` — the only place H1/H2/body size anchors used to
# live — so a compiled artifact without its own anchors leaves the model in a
# size vacuum and titles drift small. The block is ALWAYS emitted: derived
# from the design system's own font-size ramp when one is recognizable,
# otherwise falling back to the app default style's neutral bands
# (``src/core/defaults.py``: H1 40-52px / H2 28-36px / body 16-18px) so the
# vacuum can never recur. Nothing brand-specific is hardcoded — every
# ramp-path number comes from the uploaded bundle's tokens.
#
# Ramp detection is BY NAME+VALUE PATTERN across ALL token groups, not by
# group membership: Claude Design manifests mislabel the type ramp (fs-12 …
# fs-64) as kind "spacing", so the sizes never reach the "type" group.
_TYPE_SIZE_NAME_RE = re.compile(r"^(?:fs|font-?size|text)[-_]?\d*($|[-_])", re.IGNORECASE)
_PX_VALUE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*px\s*$", re.IGNORECASE)

# Body band bounds for role mapping (which ramp entries read as body text).
# These bound the SELECTION out of the ramp — the emitted numbers themselves
# always come from the tokens.
_BODY_BAND_MIN_PX = 16.0
_BODY_BAND_MAX_PX = 22.0
_BODY_BAND_IDEAL_PX = 18.0

_TYPE_SCALE_ANTI_SHRINK_LINE = (
    "- These sizes are REQUIRED, not suggestions: titles at or above their "
    "band, body inside its band. To make content fit, trim it or split it "
    "across more slides — NEVER shrink type below the brand type scale."
)

# Neutral fallback bands = the app default style's anchors, restated. Kept in
# prose form (no CSS) like the rest of the compiled guidance.
_TYPE_SCALE_NEUTRAL_BLOCK = "\n".join(
    [
        "BRAND TYPE SCALE (REQUIRED — this design system ships no font-size "
        "ramp, so use the app's neutral bands):",
        "- Cover/hero and slide titles (H1): 40-52px, bold.",
        "- Section headers (H2): 28-36px.",
        "- Body text: 16-18px.",
        _TYPE_SCALE_ANTI_SHRINK_LINE,
    ]
)


def _fmt_px(px: float) -> str:
    return f"{int(px)}px" if px == int(px) else f"{px:g}px"


def _font_size_ramp(grouped: dict[str, list[tuple[str, str]]]) -> dict[float, str]:
    """Collect ramp-shaped tokens (font-size-ish name + px value) from EVERY
    group and return ``{px: token_name}`` (first name per size wins, in
    deterministic group/name order)."""
    ramp: dict[float, str] = {}
    for group in sorted(grouped):
        for name, value in grouped[group]:
            if not _TYPE_SIZE_NAME_RE.match((name or "").strip()):
                continue
            px_match = _PX_VALUE_RE.match(value or "")
            if not px_match:
                continue
            px = float(px_match.group(1))
            if px <= 0:
                continue
            ramp.setdefault(px, name.strip())
    return ramp


def _type_scale_section(grouped: dict[str, list[tuple[str, str]]]) -> str:
    """Build the BRAND TYPE SCALE block (always emitted; see comment above).

    Role mapping over the sorted distinct ramp sizes: cover/hero = top,
    floor = bottom, body = the 16-22px band (closest-to-18 when the ramp
    skips that range), section headers = the upper-middle entry between the
    body band and the top. Fewer than 3 distinct sizes is not a usable ramp
    -> neutral default bands.
    """
    ramp = _font_size_ramp(grouped)
    sizes = sorted(ramp)
    if len(sizes) < 3:
        return _TYPE_SCALE_NEUTRAL_BLOCK

    floor_px = sizes[0]
    hero_px = sizes[-1]
    body_sizes = [px for px in sizes if _BODY_BAND_MIN_PX <= px <= _BODY_BAND_MAX_PX]
    if not body_sizes:
        # Ramp skips the band entirely — anchor body on the entry closest to
        # the ideal (larger wins a tie, for legibility).
        body_sizes = [min(sizes, key=lambda px: (abs(px - _BODY_BAND_IDEAL_PX), -px))]
    body_top = body_sizes[-1]
    mids = [px for px in sizes if body_top < px < hero_px]
    section_px = mids[len(mids) // 2] if mids else hero_px

    if len(body_sizes) > 1:
        body_label = f"{_fmt_px(body_sizes[0])}-{_fmt_px(body_top)}"
        body_tokens = ", ".join(ramp[px] for px in body_sizes)
    else:
        body_label = _fmt_px(body_top)
        body_tokens = ramp[body_top]

    return "\n".join(
        [
            "BRAND TYPE SCALE (REQUIRED — derived from this design system's "
            "own tokens):",
            f"- Cover/hero titles: {_fmt_px(hero_px)} (token {ramp[hero_px]}) — "
            "the top of the brand ramp.",
            f"- Section/slide titles: {_fmt_px(section_px)} (token "
            f"{ramp[section_px]}) or larger.",
            f"- Body text: {body_label} (tokens: {body_tokens}).",
            f"- Floor: never render ANY text below {_fmt_px(floor_px)} (token "
            f"{ramp[floor_px]}), the bottom of the brand ramp.",
            _TYPE_SCALE_ANTI_SHRINK_LINE,
        ]
    )


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
    The section closes with the soft-pick enabler line — the no-template default.
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
    # The soft-pick enabler names the no-template default (Claude Design's
    # none-path): the model may start from a listed template that fits. A PINNED
    # template overrides this via the SELECTED-TEMPLATE block's precedence line.
    return "\n".join(
        [
            "SLIDE TEMPLATES (use these named layouts as structural guidance):",
            *lines,
            _TEMPLATE_SOFT_PICK_LINE,
        ]
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

    Emitted order: header (stamped with the compiler-version marker) ->
    description -> BRAND MANUAL (README + SKILL, full) -> scope firewall
    (always present: the design system governs STYLE only, never content) ->
    tokens (color, type, spacing, shadow; all uncapped) -> BRAND TYPE SCALE
    (always present: ramp-derived role anchors, or the neutral default bands
    when no ramp is recognizable) -> fonts (@font-face refs + family listing;
    uncapped) -> templates (closed by the soft-pick enabler) -> SLIDE FRAME
    CONSTRAINTS (frame guardrails, always present) -> the brand IMAGE ASSET
    CONTRACT (fetch via ``search_brand_assets``). Brand images are NOT
    enumerated.
    """
    parts: list[str] = []

    name = getattr(design_system, "name", None) or "Design System"
    # The version marker rides on the header line (no schema change) so persisted
    # artifacts self-describe which compiler produced them — see
    # ``compiled_style_content_is_current``.
    parts.append(f"{_STYLE_HEADER}: {name} {_COMPILER_VERSION_MARKER}")

    # A short frontmatter-style description/identity caption comes FIRST (huashu /
    # Claude Code skill convention: blurb -> manual); the full brand manual below
    # is the first FULL/substantive block.
    description = getattr(design_system, "description", None)
    if description and description.strip():
        parts.append(description.strip())

    brand_manual = _brand_manual_section(skill_md, readme_md)
    if brand_manual:
        parts.append(brand_manual)

    # Scope firewall — ALWAYS present, reading as a coda to the manual (or in
    # its slot when no manual was retained): everything above and below is style
    # authority, never content. See the constant's comment for provenance.
    parts.append(DESIGN_SYSTEM_SCOPE_FIREWALL)

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

    # Type-size role anchors — ALWAYS present (ramp-derived or neutral), so a
    # DS deck never generates in the size vacuum left by bypassing
    # DEFAULT_SLIDE_STYLE. Emitted right after the token sections it reads.
    parts.append(_type_scale_section(grouped))

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

    # Frame guardrails: re-assert the fixed 1280x720 frame awareness a DS deck
    # loses by bypassing DEFAULT_SLIDE_STYLE. Always present; emitted before the
    # asset contract so the contract stays the last block.
    parts.append(_SLIDE_FRAME_CONSTRAINTS)

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
        # ROOT-level docs are the brand operating manual. Real Claude Design
        # exports also ship nested component READMEs (e.g.
        # ``ui_kits/website/README.md``) which the importer retains for the
        # source browser — those are component docs, never brand authority,
        # and must not pollute the manual. Only when a bundle has no
        # root-level doc at all does the previous all-rows join apply.
        root_rows = [row for row in rows if "/" not in row[0]]
        chosen = root_rows or rows
        return "\n\n".join(text for _, text in sorted(chosen, key=lambda row: row[0]))

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


def compiled_style_content_is_current(compiled: Optional[str]) -> bool:
    """True when a persisted ``compiled_style_content`` was produced by the
    CURRENT compiler version (its header carries the version marker).

    ``False`` means the artifact is missing, empty, or predates the current
    compiler — e.g. rows compiled before the frame guardrails / before version
    markers existed — and must be recomputed from the row's persisted data via
    ``recompute_compiled_style_content`` before being injected into a prompt.

    The marker is matched on the HEADER LINE ONLY: the artifact body embeds
    arbitrary README/SKILL prose, and body text that quotes (or collides with)
    ``[ds-compiler vN]`` must not pin a stale artifact as current.
    """
    if not compiled:
        return False
    return _COMPILER_VERSION_MARKER in compiled.split("\n", 1)[0]


def ensure_compiled_style_content_current(design_system: Any) -> str:
    """Return the record's ``compiled_style_content``, recomputing it first when
    it is stale or missing (lazy backfill-on-read for prompt consumers).

    The persisted artifact is stale when it predates the current compiler
    (``compiled_style_content_is_current``) — covering rows compiled before the
    frame guardrails / version markers existed and rows never compiled at all.
    The recompute rebuilds from the record's persisted tokens/files/assets and
    degrades gracefully (e.g. no BRAND MANUAL block) when no source files were
    retained (pre-Phase-1 imports). It refreshes the record IN PLACE; persisting
    that refresh is the caller's session's business — inside ``get_db_session``
    it commits on exit, making this a lazy per-row backfill with deliberately NO
    batch machinery.
    """
    compiled = getattr(design_system, "compiled_style_content", None)
    if compiled is not None and compiled_style_content_is_current(compiled):
        return compiled
    logger.info(
        "Design system compiled content stale or missing; recompiling",
        extra={"design_system_id": getattr(design_system, "id", None)},
    )
    return recompute_compiled_style_content(design_system)
