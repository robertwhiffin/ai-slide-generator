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

import json
import logging
import re
import unicodedata
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
# v7: font-size ramp tokens are surfaced ONLY as BRAND TYPE SCALE — they are no
# longer reprinted under TYPOGRAPHY/SPACING TOKENS, killing the competing role
# cue that made a mislabeled ``fs-64: 64px`` read as a gap value (measured: 56px
# covers against a 64px spec, content titles at 32px against a 40px floor).
# v8: the BRAND TYPE SCALE heading carries the compiler-owned
# ``[ds-type-scale]`` marker so ``extract_type_scale_block`` anchors the late
# re-assertion to the COMPILER's section instead of the first prose occurrence
# of the phrase. Persisted v7 rows carry no marker, so the bump is what makes
# them recompile and regain an extractable block.
# v9: EVERY user-controlled string is sanitized at its interpolation point
# (``_safe`` / ``_safe_multiline``) and the type-scale region is delimited by
# control-character SENTINELS that sanitized text cannot contain — replacing the
# v8 "keep the marker unique" approach, which a ramp TOKEN NAME defeated by
# smuggling a marker and fake role lines into the scrub-exempt owning section.
# Persisted v8 rows may hold an artifact built from unsanitized values and carry
# no sentinels, so the bump is what makes them recompile.
# v10: NO token name is echoed inside the numeric BRAND TYPE SCALE region (it
# emits parsed px numbers only), so the v9 identifier allowlist + 40-char cap on
# ramp token names is DELETED and every token is kept: ramp names get their own
# correctly-labeled BRAND FONT-SIZE TOKENS section, and typography/spacing list
# everything else regardless of length or script. Sanitize-not-reject of line
# breaks/controls is now the ONLY transformation applied to a user string (the v9
# multi-space collapse renamed legitimate tokens). Line endings are normalized in
# ONE place, matching CRLF as a single unit — v9 turned a Windows-authored README
# into a double-spaced one. Persisted v9 rows hold dropped token names and
# doubled line breaks, so the bump is what makes them recompile.
# v11: NO token is dropped for the name of its GROUP. The group set was CLOSED
# (the seven canonical groups) and every token in any other group was omitted with
# only a log warning, so a bundle grouping its tokens as "color" / "palette" /
# "typography" / "elevation" — the vocabulary most token tooling uses — lost the
# ENTIRE group, invisibly. Obvious synonyms are now ALIASED onto the canonical
# seven (``_GROUP_ALIASES``) so they reach the emitter that labels them correctly,
# and any group still unknown is emitted verbatim under its own sanitized name
# (``ADDITIONAL BRAND TOKENS (group: <name>):``) rather than dropped. Group names
# are sanitized exactly like every other user string — sanitize-not-reject, no
# length cap, no script restriction. Persisted v10 rows are missing every token in
# a non-canonical group, so the bump is what makes them recompile and regain them.
# v12: the font-size exclusion is UNCONDITIONAL. It was gated on the ramp having
# 3+ distinct sizes, which COUPLED a labeling question ("is this token a font
# size?", true at any count) to a numeric-contract one ("is the ramp long enough to
# derive role bands from?"), so a design system shipping ONE or TWO font-size
# tokens still printed them under ``SPACING TOKENS:`` — the v7 small-titles
# mislabel, still live below the threshold. Both the exclusion and its BRAND
# FONT-SIZE TOKENS home now apply at any count; only the numeric block still
# consults ``_MIN_RAMP_SIZES``, falling back to the neutral bands. The generic
# section's heading is now CONSTANT (the group name is no longer interpolated into
# it) and the version marker moved to a FIXED, name-independent header position.
# Persisted v11 rows hold short-ramp font sizes labeled as spacing, so the bump is
# what makes them recompile.
# v13: font-token OWNERSHIP no longer comes from the numeric ramp map. v12 fixed the
# ramp-LENGTH coupling but ownership was still read back out of ``{px: name}``,
# which answers a narrower question than "is this token a font size?" — it keeps one
# name per DISTINCT px (so the second token at 16px was unowned) and cannot
# represent a non-px size at all (so ``1rem``/``2em``/``125%``/``clamp(...)`` were
# all unowned). Both classes of unowned font size printed under ``SPACING TOKENS:``:
# the v7 small-titles mislabel, third and fourth surfaces. Ownership is now a
# predicate over the token itself (``_is_font_size_token``: name shape + any CSS
# font-size value form), applied to EVERY token including duplicates; the px map
# survives as ``_font_size_px_ramp`` for BAND MATH only. Persisted v12 rows hold
# non-px and same-px font sizes labeled as spacing, so the bump is what makes them
# recompile.
# v14: the font-size NAME HEURISTIC itself, both directions, after five rounds of
# extending its pattern. The stem is now a WHOLE SEGMENT of the normalized name
# instead of a prefix, so a CSS property that merely starts with the same letters
# (``text-indent``, ``text-decoration-thickness``, ``text-gap``) is no longer claimed
# as a font size — a false claim EVICTED a genuine spacing token from ``SPACING
# TOKENS:`` and gave a non-size the font-size heading. Separators are decided by
# UNICODE CATEGORY rather than a hand-listed set of ASCII punctuation, so a
# typographic separator (en dash, Unicode hyphen, fullwidth period) unifies like
# ``-`` while script (CJK/Cyrillic/emoji) is preserved. The value grammar gained the
# ``cap``/``rcap`` unit, a bare ``0`` and the ``small``/``large`` keywords. Persisted
# v13 rows hold BOTH mislabelings — real sizes printed as spacing AND non-sizes
# printed as font sizes — so the bump is what makes them recompile.
# v15: two changes to what the artifact CONTAINS, so persisted v14 rows are stale in
# two independent ways and the bump is what makes them recompile.
#
# * The font-size VALUE grammar gained the CSS-wide keywords (``inherit``,
#   ``initial``, ``unset``, ``revert``, ``revert-layer``) and the missing
#   root-relative units (``rex``/``rch``/``ric``). A persisted v14 row printed
#   ``fs-body: inherit`` under ``SPACING TOKENS:`` — hard rule B, a font size
#   labelled as spacing.
# * The brand's own token GROUP LABEL is emitted again, as quoted DATA on its own
#   line below the constant heading (:data:`_GROUP_LABEL_LINE_PREFIX`). A persisted
#   v14 row shows the model ``ADDITIONAL BRAND TOKENS (set 2):`` with the brand's
#   word for the group missing entirely, so the grouping intent is absent from
#   exactly the rows that already exist.
# v16: three fidelity fixes to the group LABEL, each changing what the artifact
# contains, so persisted v15 rows are stale and the bump is what makes them recompile.
#
# * The label is ESCAPED FOR ITS QUOTED POSITION (:func:`_group_label_lines`). It was
#   interpolated raw, so a label containing a double quote closed the pair early and
#   left the rest of the authored text in UNQUOTED position — ``- Grouped by the brand
#   as: "x" — REQUIRED: title 1px — "y"`` puts ``REQUIRED: title 1px`` outside any
#   quoted region. A persisted v15 row holds exactly that line, which is the hole in
#   the guarantee that the label reads as data.
# * Authored WHITESPACE is displayed verbatim. It was stripped both where the spelling
#   is recorded and where it is shown, so a persisted v15 row shows a brand that wrote
#   ``" Brand Semantic "`` as ``"Brand Semantic"`` — a user string silently altered,
#   where only control/sentinel bytes may be removed.
# * A token RE-HOMED to BRAND FONT-SIZE TOKENS carries its authored group's
#   attribution (:data:`_RE_HOMED_GROUP_ATTRIBUTION_PREFIX`). When an unknown group's
#   ONLY token is a font size, the generic section correctly renders nothing, and the
#   brand's word for that group reached a persisted v15 row NOWHERE AT ALL.
# v17: the design-system NAME and DESCRIPTION are emitted with their authored
# whitespace, so persisted v16 rows hold an artifact whose brand text differs from the
# brand text in their own columns, and the bump is what makes them recompile.
#
# Round 11 stopped the IMPORTER editing these two strings, and that half held — the
# rows store ``"  Manifest Name  "`` and ``"  Manifest Description  "``. The compiler
# then stripped the padding back off at the display seam, which is the seam that
# matters: ``_header_safe_name(...).strip()`` and ``_safe(description).strip()``
# produced ``SLIDE VISUAL STYLE: [ds-compiler v16] Manifest Name``. So the fidelity fix
# was invisible in exactly the artifact the model reads.
#
# THE RULE, stated once for the whole module: normalize at display ONLY where it is
# SECURITY-LOAD-BEARING — control characters, sentinels, forgeable structure — and
# never for aesthetics. Ordinary whitespace (category ``Zs``) is not a security
# concern; C0/C1 controls (category ``Cc``) are, because the region delimiters and the
# currency sentinel are built from them. Both strips removed here were aesthetic; every
# ``Cc`` filter is untouched.
#
# The NAME lands in the version-stamped header line, and preserving its padding buys it
# no structural power: ``_safe`` still flattens every line-break spelling to one space
# (so it cannot open a line) and still drops every ``Cc`` character (so it cannot carry
# a sentinel), ``_MARKER_LIKE_RE`` still removes marker-shaped text from this slot, and
# currency is decided at OFFSET ZERO of the artifact — ahead of the header line
# entirely — by :data:`_CURRENCY_SENTINEL`.
# v18: the two remaining OUR-CODE gaps in what the artifact CONTAINS, so persisted v17
# rows lack both and the bump is what makes them recompile.
#
# * CONTRAST guidance existed NOWHERE in the artifact. A grep for
#   ``contrast|wcag|accessib`` over a full 31k-char compiled artifact returned ZERO
#   hits, and the cost was measured on the UNPINNED path (where the model writes its
#   own CSS): two sub-AA text/background pairs at 2.73:1 and 2.81:1 against AA's
#   4.5:1. The model picks a background from the palette, then picks an ink from the
#   SAME palette, and nothing asked it to check the pair. :func:`_contrast_section`
#   now COMPUTES WCAG relative luminance over the design system's own color tokens
#   and states which of them can carry text — generic prose would have restated the
#   requirement without telling the model which of ITS colors satisfy it.
# * The BRAND TYPE SCALE defined FOUR tiers (cover / section / body / floor) while a
#   real bundle authors FIVE text roles. The missing one is the eyebrow/kicker — the
#   small label above a title — so the model guessed its size on every slide and
#   those labels rendered inconsistently slide-to-slide. The band is derived from the
#   bundle's own ramp (:func:`_eyebrow_px`), never from a constant.
COMPILER_VERSION = 18
_COMPILER_VERSION_MARKER = f"[ds-compiler v{COMPILER_VERSION}]"

# The EXACT, name-independent header prefix every compiled artifact opens with.
# Currency is decided by comparing against this constant (see
# ``compiled_style_content_is_current``), which is safe precisely because nothing
# user-controlled can appear before or inside it — the design-system name follows
# it. Deriving currency from the END of the header instead was spoofable by a name
# that ended with the marker.
_HEADER_VERSION_PREFIX = f"{_STYLE_HEADER}: {_COMPILER_VERSION_MARKER}"

# THE PROOF OF CURRENCY. A version-stamped sentinel the compiler emits at a FIXED
# position — the very first characters of every artifact — built from the same
# UNIT SEPARATOR (U+001F) control character as the type-scale region delimiters.
#
# This is what makes currency unforgeable, and it replaces reading the header line.
# FIVE successive rules all inspected that line, and every one of them fell,
# because the line contains user-influenced text BY CONSTRUCTION (the design-system
# name is interpolated into it). The last of them — prefix + non-empty name segment
# + exactly one marker — was defeated by a PRE-VERSION artifact (no marker at all,
# which the lazy backfill explicitly supports) whose NAME simply STARTED with
# ``[ds-compiler v13]``: that reproduces the current prefix byte-for-byte, leaves a
# name segment, and contains exactly one marker, so a stale body read as current and
# NEVER recompiled.
#
# No amount of further tightening fixes that, because the header is a place where
# compiler text and user text are adjacent. The fix is to stop asking the question
# there. ``_safe`` / ``_safe_multiline`` strip category-``Cc`` characters from EVERY
# interpolated user string, so no uploaded name, description, token, template or
# README can contain U+001F. A sentinel built from it therefore cannot be forged by
# any user input — the same argument that already makes the region delimiters sound,
# reused for the version claim.
#
# It is VERSION-STAMPED so a v13 sentinel does not vouch for a v14 artifact, and it
# is stripped from the model-facing text alongside the region delimiters
# (:func:`strip_type_scale_region_markers`), so the model never sees it.
_CURRENCY_SENTINEL = f"\x1f<ds-compiler v{COMPILER_VERSION}>\x1f"

# Matches a currency sentinel of ANY version, so a stale-but-stamped artifact can be
# recognized as *a compiled artifact* while still failing the exact-version check.
_CURRENCY_SENTINEL_RE = re.compile(r"\x1f<ds-compiler v[0-9]+>\x1f")

# Marker-SHAPED text, at ANY version number. Removed from the design-system NAME
# where it is interpolated into the header (:func:`_header_safe_name`), which is
# what makes the fixed marker slot the compiler's alone.
#
# Position ALONE is not sufficient, and a bare prefix comparison hid one last
# spoof: a system named ``"[ds-compiler v12] Evil"`` compiled by the OLD v11
# compiler emits ``SLIDE VISUAL STYLE: [ds-compiler v12] Evil [ds-compiler v11]``,
# whose leading characters are byte-for-byte the CURRENT prefix — so the stale v11
# artifact reads current. The name must therefore not be able to contribute marker
# text at ANY position in that line.
#
# Scoped to the NAME deliberately. README / SKILL prose keeps its marker mentions
# untouched (an earlier round established that scrubbing an author's own
# documentation is destructive and buys nothing, since prose lives outside the
# header line): the name is a short identifier occupying a STRUCTURALLY RESERVED
# slot, which is a different thing from documentation.
_MARKER_LIKE_RE = re.compile(r"\[ds-compiler\s+v[0-9]+\]", re.IGNORECASE)

# Canonical color-group ordering -> deterministic, human-meaningful sections.
_COLOR_GROUPS = ("core", "accents", "ink", "tints")

# The CANONICAL token groups, each with a purpose-built emitter: colors +
# shadows as :root custom properties, type + spacing as rule lists.
_CANONICAL_GROUPS = frozenset(_COLOR_GROUPS + ("type", "spacing", "shadow"))

# Backwards-compatible alias retained for readers/greppers of the old name.
_RECOGNIZED_GROUPS = _CANONICAL_GROUPS

# Group-name SYNONYMS folded onto a canonical group (v11). The canonical set is
# this app's own vocabulary; real token tooling names the same concepts
# differently ("color"/"palette" for brand colors, "typography" for type,
# "elevation" for shadows), and every token in such a group used to be DROPPED
# with only a log line. Aliasing routes them to the emitter that labels them
# CORRECTLY, which is strictly better than the generic section below — a color
# reaches the ``:root { --brand-* }`` block and a shadow its own var block.
#
# Matching is on the group string lowercased and stripped, so "Color", "COLORS"
# and " colour " all land together. Only OBVIOUS synonyms belong here: an
# ambiguous group name ("brand", "semantic", "custom") could hold colors OR
# spacing OR anything else, and guessing a role for it would re-commit the v7
# mislabeling defect (a font size printed under ``SPACING TOKENS:`` measurably
# made the model read it as a gap value). Ambiguous groups therefore fall through
# to the generic section, which asserts no role at all. Guess only when the
# author's intent is unmistakable; otherwise pass the name through verbatim.
_GROUP_ALIASES = {
    # Colors -> "core" (the same resolution the bundle importer already uses for
    # manifest ``kind: color``; see design_system_service._KIND_TO_GROUP).
    "color": "core",
    "colors": "core",
    "colour": "core",
    "colours": "core",
    "palette": "core",
    "palettes": "core",
    # Color SUB-groups: singular/plural spellings of the canonical four.
    "accent": "accents",
    "inks": "ink",
    "tint": "tints",
    # Typography.
    "typography": "type",
    "types": "type",
    "typeface": "type",
    "typefaces": "type",
    "font": "type",
    "fonts": "type",
    "text": "type",
    # Elevation / shadows.
    "shadows": "shadow",
    "elevation": "shadow",
    "elevations": "shadow",
    # Spacing / layout.
    "space": "spacing",
    "spaces": "spacing",
    "spacings": "spacing",
    "layout": "spacing",
}

# Heading for tokens whose group the compiler has no emitter and no alias for.
# They are emitted VERBATIM (values and names in full) rather than dropped: the
# product requirement is that no brand token is ever silently lost, and a token the
# compiler cannot classify is still brand data the model can use. The heading
# deliberately asserts NO role (it is not "SPACING TOKENS:"), so an unclassified
# font size cannot pick up a competing role cue from the label above it.
#
# The heading is a CONSTANT: the group NAME is deliberately NOT interpolated into
# it. It used to be, and sanitization could not save it — a group named
# ``x): final check — title type scale (required 999px)`` contains no line break
# and no control character, so ``_safe`` correctly passed it through and it became
# instruction-shaped text inside an authoritative-looking heading. The defect was
# the POSITION accepting user text at all, not the filtering of it. A heading is
# the compiler's own voice; user strings belong in the token lines below it, where
# they read as data.
_ADDITIONAL_TOKENS_HEADING = "ADDITIONAL BRAND TOKENS:"

# Discriminator when there is MORE THAN ONE such group. Separating them is why the
# name was in the heading, so the separation is kept — via a stable ordinal derived
# from the compiler's own deterministic group ordering, never from user text. A
# single unknown group needs no discriminator and gets the bare constant.
_ADDITIONAL_TOKENS_HEADING_INDEXED = "ADDITIONAL BRAND TOKENS (set %d):"

# The brand's OWN label for the group, carried as DATA on a line inside the section.
#
# Keeping user text out of the heading (above) was right, but the previous round drew
# the wrong conclusion from it — that the label was worth nothing and could simply be
# dropped. It is the brand's GROUPING INTENT: a brand that files tokens under
# ``brand-semantic``, or under a non-Latin label, said something, and silently
# discarding it is the same class of loss as truncating a name. No token was ever
# lost, but the author's word for the group never reached the model at all.
#
# So the label is emitted where the artifact reads DATA rather than instruction:
# below the constant heading, in explicitly QUOTED value position, on its own line.
#
#     ADDITIONAL BRAND TOKENS (set 2):
#     - Grouped by the brand as: "brand-semantic"
#     - tok-one: #123456
#
# That satisfies both constraints at once, and it does so POSITIONALLY — the same
# lesson as the version marker and the numeric region — rather than by filtering,
# which is what could not be made to work in the heading:
#
# * the heading stays the compiler's own voice, so no label can forge structure;
# * the quotes and the ``- `` bullet mark the label as one field's value among the
#   token lines, so instruction-shaped text reads as a value that WAS SUPPLIED, not
#   as a directive the artifact endorses;
# * the section is emitted OUTSIDE the compiler-owned type-scale region, so a label
#   cannot reach the one numeric contract in the artifact (asserted, not assumed —
#   see ``tests/unit/test_design_system_compiler_group_labels.py``).
#
# The label goes through :func:`_safe` like every other user string: no length cap,
# no script restriction, line breaks flattened to spaces and C0/C1 controls (the
# range the region sentinels live in) dropped. Sanitize, never reject.
#
# It is then ESCAPED FOR ITS POSITION (:func:`_group_label_lines`), because the
# quoted-data argument above depends on the label being unable to LEAVE the quotes —
# and a label containing a double quote could. See that function for the defect.
_GROUP_LABEL_LINE_PREFIX = "- Grouped by the brand as: "

# The same attribution, carried into the section that RE-HOMED a token.
#
# A font size filed under an author-invented group is moved to BRAND FONT-SIZE TOKENS
# (hard rule B: a size must never sit under a SPACING heading). When such a group's
# ONLY token is a font size, the generic section is left with nothing to render and is
# correctly not emitted — and the brand's word for the group used to vanish with it.
# A runtime probe over one token grouped as ``brand-type`` found no label line and no
# occurrence of ``brand-type`` anywhere in the artifact.
#
# Zero TOKEN loss was never the same as zero DATA loss; that is the lesson the label
# line itself came from. So the attribution travels WITH the token, on its own line
# directly below the token it describes:
#
#     BRAND FONT-SIZE TOKENS (...):
#     - fs-hero: 64px
#       (grouped by the brand as: "brand-type")
#
# Indented and parenthesized so it reads as a note ON the line above rather than as
# another token; quoted by the same helper as the section label, so the value cannot
# leave its quotes. It is emitted ONLY for author-invented groups: a canonical group
# name ("type") is this app's own vocabulary, and attributing a token to it would
# invent a claim the brand never made.
_RE_HOMED_GROUP_ATTRIBUTION_PREFIX = "  (grouped by the brand as: "

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


# --- Interpolation-boundary sanitization -----------------------------------
#
# EVERY user-controlled string is passed through :func:`_safe` at the point it
# is interpolated into the artifact. Two earlier rounds tried instead to keep
# the type-scale anchor UNIQUE — first by searching for the bare heading phrase,
# then by scrubbing the reserved marker from every section except the one that
# owns it — and both fell, because the owning section itself interpolates raw
# ramp TOKEN NAMES and is precisely the section the scrub must spare. Uniqueness
# was the wrong invariant.
#
# What user text must never do is change the artifact's STRUCTURE. There are
# exactly two structural affordances, and this function removes both:
#
# 1. LINE BREAKS. ``build_type_scale_reassertion`` selects role lines with
#    ``str.splitlines()``, and sections are joined/split on blank lines — so a
#    value containing a break can forge a role line or truncate a region.
#    ``str.splitlines()`` breaks on EIGHT characters (LF CR VT FF FS GS RS NEL)
#    plus U+2028/U+2029, so handling only CR/LF would leave live doors; each of
#    those is covered by a test.
# 2. The region SENTINELS (:data:`_REGION_BEGIN` / :data:`_REGION_END`), which
#    delimit the compiler-owned type-scale region. They are drawn from the C0
#    control range that this function strips wholesale, so a sanitized value
#    cannot contain one — that is what makes the delimiters unforgeable rather
#    than merely improbable.
#
# Deliberately NOT removed: the reserved marker text itself. It is no longer
# load-bearing (the sentinels are), so deleting it from a README that
# legitimately mentions the string would silently mangle the author's own
# documentation for no security benefit. Neutralize structure, preserve prose.
#
# Nothing else is transformed. Sanitization is SANITIZE-NOT-REJECT and it is the
# ONLY thing applied to a user string: no allowlist, no length cap, no
# whitespace tidying. An earlier round also collapsed runs of 2+ spaces so a
# payload's "visual shape" would not survive as ragged whitespace — cosmetic
# only, never a security property, and it RENAMED a legitimate token that
# happened to contain two spaces. Renaming brand data to tidy it is exactly the
# class of loss this module no longer commits.
#
# THE ONE PLACE line endings are normalized. Both sanitizers share this pattern,
# so a break is recognized ONCE however it is spelled. CRLF is matched as a
# SINGLE unit and must stay first in the alternation: substituting \r and \n
# independently turned every CRLF into TWO replacements, which is what
# double-spaced every line of a Windows-authored brand manual (and, in ``_safe``,
# left a two-space gap mid-value).
_LINE_BREAK_RE = re.compile(
    "\r\n"  # CRLF — one break, matched before the single-character forms
    "|[\n"
    "\r"
    "\v"  # \x0b VT
    "\f"  # \x0c FF
    "\x1c"  # FS
    "\x1d"  # GS
    "\x1e"  # RS
    "\x85"  # NEL
    " "  # LINE SEPARATOR
    " "  # PARAGRAPH SEPARATOR
    "]"
)


def _safe(value: Any) -> str:
    """Render *value* as text that cannot alter the artifact's structure.

    Applied at EVERY interpolation point for user-controlled data (design-system
    name/description, token names and values, font family names and their token
    lists, template names/descriptions, asset filenames, README/SKILL text).
    Each line break becomes a single space and C0/C1 control characters — the
    range the region sentinels live in — are dropped. Everything else is
    preserved VERBATIM, at any length, in any script: the reserved marker text,
    slashes, dots, colons, brackets, repeated spaces, CJK/Cyrillic/emoji.
    """
    text = "" if value is None else str(value)
    text = _LINE_BREAK_RE.sub(" ", text)
    # Drop remaining C0/C1 controls (this is what makes the sentinels
    # unforgeable). Covers NUL and the rest of the C0 range.
    return "".join(ch for ch in text if not _is_control(ch))


def _is_control(ch: str) -> bool:
    """True for C0/C1 control characters (Unicode category ``Cc``)."""
    return unicodedata.category(ch) == "Cc"


def _header_safe_name(value: Any) -> str:
    """Sanitize the design-system name for the version-stamped HEADER line.

    :func:`_safe` plus removal of marker-SHAPED text (:data:`_MARKER_LIKE_RE`).
    The header line is the ONE place the artifact makes a machine-readable claim
    about itself — which compiler version produced it — so it is the one place a
    user string must not be able to contribute marker text. Everywhere else the
    name is emitted, and everywhere the README/SKILL prose is emitted, marker
    mentions survive untouched.

    Any version number is matched, not just the current one: the spoof that
    motivated this used the CURRENT marker in the name of a row compiled by an
    OLDER compiler, so matching only the current version would have left the
    mirror-image case (an older marker in the name of a current row) open.

    THE AUTHORED WHITESPACE IS PRESERVED. This used to end in ``.strip()``, which
    made the model-facing header disagree with the stored row: a system named
    ``"  Manifest Name  "`` was persisted verbatim (round 11) and then compiled to
    ``SLIDE VISUAL STYLE: [ds-compiler v16] Manifest Name``. That strip was
    AESTHETIC — ordinary whitespace is category ``Zs``, and nothing in this module's
    structure rests on it. What IS load-bearing stays exactly as it was: ``_safe``
    drops every ``Cc`` control (the class the region delimiters and the currency
    sentinel are built from) and flattens every line-break spelling to one space, and
    the marker strip above runs first. So a padded name cannot open a line, cannot
    contain a sentinel, and cannot contribute marker text — the three things the
    header line's integrity actually depends on. Currency itself is decided at offset
    zero of the artifact, ahead of this line entirely
    (:func:`compiled_style_content_is_current`).

    A name that consists entirely of marker text — or entirely of whitespace —
    collapses to something the caller reads as empty, and it falls back to the default
    label, so the header never loses its name segment. That EMPTINESS CHECK is the one
    place normalization still belongs, and it lives in the caller: this function
    returns the brand's text, and the caller decides whether there is any.
    """
    return _MARKER_LIKE_RE.sub("", _safe(value))


# NO token NAME is echoed inside the compiler-owned type-scale region. That
# region carries the NUMERIC contract only: compiler prose plus px numbers the
# compiler itself parsed from token values. With no user-controlled text there,
# the "a token name forges role lines / smuggles fake numbers into the contract"
# class is closed STRUCTURALLY — there is nothing left inside to police.
#
# This replaces an allowlist (``^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,39}$``) that
# echoed a name only when it looked like a plain identifier and DROPPED it
# otherwise. Tightening that regex was the wrong axis: because ramp-shaped
# tokens are deliberately suppressed from the typography/spacing lists (the
# scale is meant to be their one authoritative home), a rejected name was left
# with NO home at all, so a legitimate brand token called ``brand/heading-xl``,
# ``brand-サイズ-64``, ``font.size.display.xxl`` or anything over 40 characters
# disappeared from the compiled artifact entirely. Dropping brand data to
# protect a sentence is not a trade this compiler makes: the sentence no longer
# needs protecting, and EVERY token is listed in full below.
#
def _safe_multiline(value: Any) -> str:
    """Sanitize a user document whose LINE STRUCTURE is meaningful.

    README / SKILL.md are injected as prose, so collapsing their newlines would
    destroy the markdown the brand manual depends on. Their line breaks are
    NORMALIZED to ``\\n`` instead of removed (so no exotic breaker reaches the
    artifact), every other control character is dropped, and blank lines are
    preserved. They cannot forge the type-scale region regardless, because that
    region is delimited by sentinels this function strips — the manual is
    injected outside those sentinels entirely.

    Normalization happens ONCE, over the whole document, BEFORE any per-line
    processing (:data:`_LINE_BREAK_RE` matches CRLF as one unit). Replacing each
    breaker in sequence instead turned a Windows-authored ``\\r\\n`` into
    ``\\n\\n``, putting a blank line between EVERY line of the brand manual —
    which the model reads as paragraph structure that the author never wrote.
    """
    text = "" if value is None else str(value)
    text = _LINE_BREAK_RE.sub("\n", text)
    return "".join(ch for ch in text if ch == "\n" or not _is_control(ch))


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
#
# That mislabeling is also why the DECLARED kind cannot be preferred over the name.
# It is the obvious structural fix — "stop inferring role from the name where the
# bundle already tells us" — and it was evaluated and rejected on evidence:
#
#   1. ``kind`` is never persisted. ``design_system_token`` has exactly
#      ``(group, name, value)`` (``src/database/models/design_system.py``), and the
#      importer writes ``DesignSystemToken(group=, name=, value=)``
#      (``design_system_service.py``). By the time the compiler runs, the manifest's
#      per-token ``kind`` has already been mapped through ``_KIND_TO_GROUP`` and
#      collapsed into ``group``; there is no declared kind left to read.
#   2. Where it IS still visible, it is WRONG for precisely these tokens. A real
#      Claude Design manifest declares ``{"name": "--fs-12", "value": "12px",
#      "kind": "spacing"}``. Preferring the declared kind would therefore file the
#      type ramp as spacing BY CONTRACT — it would re-create the v7 small-titles
#      defect as designed behaviour rather than close it.
#
# So the name heuristic stays, and is instead made structurally sound on both axes:
# the stem must be a WHOLE SEGMENT (below) and separators are decided by Unicode
# category (see :data:`_NAME_SEPARATOR_RE`).
#
# THE STEM IS A WHOLE SEGMENT, NEVER A PREFIX. Round 7 matched
# ``^(?:fs|font-?size|text)[-_]?\d*($|[-_])``, where the ``text`` alternative
# matched the leading four characters of any name, so ``text-indent: 2em``,
# ``text-decoration-thickness: 2px`` and ``text-gap: 8px`` were all claimed as font
# sizes. Ownership SUPPRESSES a pair from the spacing list, so the cost was a
# genuine spacing token evicted from ``SPACING TOKENS:`` while a non-size took the
# font-size heading. Matching whole segments of the normalized name closes the
# entire "some CSS property happens to start with these letters" class, rather than
# denylisting the three properties that were found.
#
# Two stems from the obvious candidate list are deliberately ABSENT, both because
# they are AMBIGUOUS rather than merely awkward:
#
# * ``size`` — ``size-gap: 8px`` is a spacing token (and a pinned control). A bare
#   ``size`` segment does not say WHAT is being sized, so it cannot carry the stem.
# * ``text`` — the direct cause of the over-inclusive half. ``text`` is the shared
#   prefix of a large open set of CSS properties that are not font sizes
#   (``text-indent``, ``text-decoration-thickness``, ``text-align``, ``text-wrap``)
#   and of brand names that are not either (``text-gap``). Only the explicit
#   ``text-size`` spelling denotes a size. This is what retires ``text-percent``
#   and ``text-🎨-body`` from ownership: under a whole-segment rule they are
#   ``text`` + a word, exactly like ``text-indent``, so claiming them would mean
#   re-admitting the prefix match that evicts real spacing tokens.
_TYPE_SIZE_STEMS = ("fs", "font-size", "text-size", "type-scale")
_TYPE_SIZE_NAME_RE = re.compile(
    rf"^(?:{'|'.join(_TYPE_SIZE_STEMS)})(?:-?\d+)?(?:$|-)",
    re.IGNORECASE,
)
_PX_VALUE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*px\s*$", re.IGNORECASE)

# Separator conventions a brand may use between the parts of a token name. A design
# system is free to write its scale as ``fs-body``, ``fs.body``, ``fs_body``,
# ``font.size.body`` or ``fontSizeBody``, and the choice is a house style — it says
# nothing about whether the token is a font size. Ownership therefore compares a
# NORMALIZED name: every separator run becomes a single ``-``, and a camelCase hump
# becomes a separator too, so all of those spellings collapse onto ``fs-body`` /
# ``font-size-body`` before :data:`_TYPE_SIZE_NAME_RE` is applied.
#
# Round 6 matched the raw name against a pattern that only accepted ``-``/``_``
# after the stem, so ``fs.body``, ``font_size_body``, ``fontSizeBody`` and
# ``font.size.body`` were all read as NOT font sizes and printed under
# ``SPACING TOKENS:`` — the v7 small-titles mislabel on its fifth surface.
# Only PUNCTUATION/whitespace is a separator. Deliberately NOT ``[^0-9A-Za-z]``:
# that also consumed CJK, Cyrillic and emoji, so a legitimate brand token
# ``fs-サイズ-24`` normalized to ``fs-24`` and collided with a different rung of the
# same ramp. Normalization must unify SEPARATOR CONVENTIONS, never erase script.
#
# Round 7 spelled that class as a HAND-LISTED set of ASCII punctuation, which is the
# same losing move one level down: a brand using a typographic separator — an en
# dash ``fs–body`` (U+2013), a Unicode hyphen ``fs‐body`` (U+2010), a fullwidth
# period ``fs．body`` (U+FF0E) — normalized to a name the stem could not match, and
# the size printed as spacing again. Extending the list would leave the next
# separator (em dash, ideographic full stop, non-breaking hyphen, …) broken.
#
# So the question is asked of UNICODE, not of a list: a character is a separator
# when its general category is ``Pd`` (dash punctuation), ``Pc`` (connector, e.g.
# ``_``) or ``Po`` (other punctuation, e.g. ``.`` ``/`` ``:``), plus any whitespace.
# Categories are what make the exclusions principled rather than lucky: ``Lo``
# (CJK ``サ``, Cyrillic) and ``So`` (emoji ``🎨``) are LETTERS and SYMBOLS, never
# punctuation, so script is preserved and ``fs-サイズ-24`` still cannot collapse onto
# ``fs-24``. ``Sm`` (math symbols, e.g. ``|`` ``+``) is likewise not punctuation and
# so not a separator.
_SEPARATOR_UNICODE_CATEGORIES = frozenset(("Pd", "Pc", "Po"))


def _is_name_separator(char: str) -> bool:
    """True when *char* is a separator CONVENTION rather than part of the name."""
    return char.isspace() or unicodedata.category(char) in _SEPARATOR_UNICODE_CATEGORIES


_CAMEL_HUMP_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# A font size may legitimately be declared in any CSS length/relative unit, or by
# a function that computes one. OWNERSHIP (see ``_font_size_token_pairs``) accepts
# every form; only :data:`_PX_VALUE_RE` values can contribute to the numeric bands,
# because only they can be converted to a pixel number without knowing the
# document's root size or its containing block.
#
# This distinction is the whole of the round-6 BLOCKING 1 fix. Ownership used to be
# read off the px-keyed ramp map, which silently made "is this a font size?"
# answerable ONLY for a px value that was also the first token at its size — so
# ``fs-body: 1rem`` and the second token at ``16px`` were both filed under
# ``SPACING TOKENS:``, the v7 mislabel again.
# Two further corrections to the grammar, both round-7 B1:
#
# * NO LEADING SIGN. ``[+-]?`` accepted ``-8px``, but there is no such thing as a
#   negative font size. The cost was not cosmetic: ownership SUPPRESSES a token from
#   ``SPACING TOKENS:``, so a genuine spacing token of ``-8px`` was removed from the
#   spacing list and re-homed under a font-size heading. A leading ``+`` is dropped
#   with it — ``+16px`` is not a form any brand writes for a size.
# * A COMPUTED SIZE MUST CONTAIN A SIZE. The arm was ``(?:clamp|calc|min|max)\s*\(.*\)``,
#   where ``.*`` matched literally anything, so ``calc(not css at all)`` was claimed
#   as a font size. The contents must now hold at least one length/percentage or
#   custom-property reference, which is what distinguishes a real computed size from
#   a string that merely opens with ``calc(``.
#
# ``var()`` is accepted as a size in its own right: indirecting the scale through a
# custom property (``fs-body: var(--brand-body)``) is the most common way a design
# system references its own tokens, and rejecting it printed those sizes as spacing.
# Round 8 completes the grammar with the three forms codex found still printing as
# spacing. Each is ordinary CSS, so each was a live surface of the same mislabel:
#
# * ``cap`` (and ``rcap``) — the cap-height unit, missing from the font-relative
#   group. ``fs-body: 2cap`` is a font size stated in the most typographic unit CSS
#   has.
# * A BARE ``0`` — the one length that is valid with no unit at all. ``fs-body: 0``
#   is legal CSS, so rejecting it filed a declared size under spacing. Only zero
#   qualifies: ``16`` without a unit is not a length.
# * ``small`` / ``large`` — the base rungs of the CSS absolute-size keyword scale.
#   The arm covered ``x{1,3}-small``/``x{1,3}-large`` (and ``medium``) but not the
#   two unprefixed keywords those are derived from.
#
# Round 9 found the CSS-WIDE KEYWORDS missing, and this time the grammar was
# audited AS A WHOLE against the CSS font-size spec rather than extended by the
# one form that was reported. Four rounds of "add the value that was found" is
# itself the defect: each fix left the grammar a proper subset of legal CSS, so
# the next ordinary declaration reopened hard rule B. The clauses below are now
# the spec's own list — CSS-wide keywords, absolute-size keywords, relative-size
# keywords, ``<length>``, ``<percentage>``, math functions, ``var()``, unitless
# zero — and ``tests/unit/test_design_system_compiler_font_size_grammar.py`` pins
# every one of them at the ARTIFACT level, so a future narrowing fails a test
# instead of shipping a mislabel.
#
# The keywords are the most consequential of the misses: ``font-size: inherit`` is
# how a design system says "match the parent", and ``initial``/``unset``/``revert``/
# ``revert-layer`` are valid on EVERY CSS property, so all five are ordinary things
# to find in a brand's token file. They carry no computable pixel number, which is
# exactly why they belong here and not in :data:`_PX_VALUE_RE`: ownership asks "is
# this a font size?", while the px ramp asks "what number is it?" — the round-6
# separation of those two questions is what lets a keyword be correctly LABELLED
# without inventing a size for the band math.
_CSS_WIDE_KEYWORDS = r"inherit|initial|unset|revert-layer|revert"

# ``revert-layer`` precedes ``revert`` so the longer keyword is matched whole. The
# trailing ``\s*$`` anchor would force a backtrack anyway, but relying on that makes
# the alternation's correctness depend on the engine rather than on the order.
_LENGTH_UNITS = r"""(?:px|pt|pc|in|cm|mm|q         # absolute lengths
             |r?em|r?ex|r?ch|r?lh|r?ic|r?cap  # font-relative lengths (+ root variants)
             |v(?:w|h|i|b|min|max)        # viewport-relative lengths
             |[cdsl]v(?:w|h|i|b|min|max)  # small/large/dynamic/container viewport
             |cq(?:w|h|i|b|min|max)       # container-query lengths
             |%)                          # percentage of the inherited size"""

_FONT_SIZE_VALUE_RE = re.compile(
    rf"""^\s*(?:
        (?:\d+(?:\.\d+)?|\.\d+)           # a non-negative number (no sign)
        \s*{_LENGTH_UNITS}
        |0+(?:\.0+)?                      # a bare zero — the one unitless length
        |var\s*\(\s*--[^)]*\)             # a custom-property reference
        |(?:clamp|calc|min|max)\s*\(      # a computed size, which must CONTAIN a size
            (?=[^)]*(?:
                (?:\d+(?:\.\d+)?|\.\d+)\s*{_LENGTH_UNITS}
                |var\s*\(\s*--
            ))
            .*\)
        |x{{1,3}}-large|x{{1,3}}-small    # CSS absolute-size keywords
        |small|large|larger|smaller|medium
        |{_CSS_WIDE_KEYWORDS}             # CSS-wide keywords, legal on any property
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# A usable ramp needs at least this many distinct sizes; below it the tokens are
# NOT a scale, so they keep their original group listing (never dropped) and the
# neutral bands apply.
_MIN_RAMP_SIZES = 3

# Body band bounds for role mapping (which ramp entries read as body text).
# These bound the SELECTION out of the ramp — the emitted numbers themselves
# always come from the tokens.
_BODY_BAND_MIN_PX = 16.0
_BODY_BAND_MAX_PX = 22.0
_BODY_BAND_IDEAL_PX = 18.0

# Human-readable tag on the BRAND TYPE SCALE heading. Kept because it is
# greppable in logs and in a persisted artifact, but it is NO LONGER the
# extraction anchor — the sentinels below are. Two rounds of trying to keep this
# string unique failed (see ``_safe``); user text may now contain it freely.
# It TRAILS the heading line (like ``[ds-compiler vN]`` on the header line) so
# the heading's prose reads unbroken to the model.
_TYPE_SCALE_MARKER = "[ds-type-scale]"

# Structural delimiters for the compiler-owned type-scale region.
#
# ``extract_type_scale_block`` recovers the region BETWEEN them, so a stray
# occurrence of any user-visible string can neither extend the region nor
# truncate it — the two failure modes of an anchor-plus-blank-line scan (the
# reviewer truncated a marker-anchored region with an injected blank line).
#
# They are UNIT SEPARATOR (U+001F) pairs: category ``Cc``, which ``_safe`` and
# ``_safe_multiline`` strip from every interpolated user value. That is the whole
# security argument — the delimiters are unforgeable by CONSTRUCTION, not by
# being unlikely. They are stripped from the artifact before it is returned
# (``_extract_and_strip_region``), so the model never sees them.
_REGION_BEGIN = "\x1f<ds-type-scale>\x1f"
_REGION_END = "\x1f</ds-type-scale>\x1f"

_TYPE_SCALE_ANTI_SHRINK_LINE = (
    "- These sizes are REQUIRED, not suggestions: titles at or above their "
    "band, body inside its band. To make content fit, trim it or split it "
    "across more slides — NEVER shrink type below the brand type scale."
)

# The EYEBROW / KICKER band — the fifth text role.
#
# The scale defined four tiers (cover / section / body / floor) while a real bundle
# authors five: it also has a small label ABOVE the title (``.eyebrow`` /
# ``.action-kicker``). One title per slide with a small kicker over it is correct BY
# DESIGN; what was missing is a BAND for it, so the model guessed the size on every
# slide and the labels rendered inconsistently slide-to-slide.
#
# WHAT IS DERIVABLE, AND WHAT IS NOT — the two halves are treated differently on
# purpose:
#
# * THE SIZE IS DERIVED (:func:`_eyebrow_px`), from a rung the brand actually
#   shipped. Nothing is hardcoded, exactly as for the other four bands.
# * THE TREATMENT IS NOT DERIVABLE. A token is ``(group, name, value)``
#   (``src/database/models/design_system.py``) — there is no case, weight or
#   tracking token to read, and the compiler does not parse the bundle's CSS, which
#   is the only place those live. So this line states NO number for them and defers
#   to the BRAND MANUAL, which is injected above and is already the authority on
#   style. Prescribing a case or a weight here would invent a claim the brand never
#   made and could contradict the manual the artifact declares authoritative.
#
# What the line DOES require is CONSISTENCY, because that is the defect that was
# measured: whatever treatment is chosen must be the same on every slide.
_EYEBROW_TREATMENT_CLAUSE = (
    "Follow the brand manual for its case, weight and letter-spacing; if the "
    "manual is silent, choose one treatment and keep it identical on every slide."
)

# The neutral branch states the eyebrow RELATIONALLY and invents no number.
#
# There is nothing to derive a neutral size FROM: ``src/core/defaults.py``'s
# ``DEFAULT_SLIDE_STYLE`` — the documented source of every other neutral band —
# names H1 40-52px, H2 28-36px and body 16-18px, and NO small-label or caption
# size. Writing a number here would mean importing one from a specific brand's
# stylesheet, which is precisely the hardcoding the derived path exists to avoid.
# Positioning it against the body band above is the strongest statement the
# compiler can make honestly.
_EYEBROW_NEUTRAL_LINE = (
    "- Eyebrow/kicker labels (the small label above a title): smaller than the "
    "body band above, and the SAME size on every slide that carries one. "
    f"{_EYEBROW_TREATMENT_CLAUSE}"
)

# Neutral fallback bands = the app default style's anchors, restated. Kept in
# prose form (no CSS) like the rest of the compiled guidance.
_TYPE_SCALE_NEUTRAL_BLOCK = "\n".join(
    [
        "BRAND TYPE SCALE (REQUIRED — this design system ships no font-size "
        f"ramp, so use the app's neutral bands): {_TYPE_SCALE_MARKER}",
        "- Cover/hero and slide titles (H1): 40-52px, bold.",
        "- Section headers (H2): 28-36px.",
        "- Body text: 16-18px.",
        _EYEBROW_NEUTRAL_LINE,
        _TYPE_SCALE_ANTI_SHRINK_LINE,
    ]
)


def _delimit_region(block: str) -> str:
    """Wrap the compiler-owned type-scale *block* in its region sentinels."""
    return f"{_REGION_BEGIN}{block}{_REGION_END}"


def _fmt_px(px: float) -> str:
    return f"{int(px)}px" if px == int(px) else f"{px:g}px"


def _normalized_token_name(name: Any) -> str:
    """A token name reduced to one separator convention, for COMPARISON only.

    Sanitized first (so the string compared is the string EMITTED — see
    :func:`_is_font_size_token`), then camelCase humps are split and every run of
    non-alphanumerics collapses to a single ``-``. ``fs.body``, ``fs_body``,
    ``fontSizeBody`` and ``font.size.body`` all normalize onto a form
    :data:`_TYPE_SIZE_NAME_RE` recognizes.

    Never used for OUTPUT: every emitted name is the author's own, verbatim through
    :func:`_safe`. This exists so a house style cannot decide a token's role.

    Separators are identified by UNICODE CATEGORY (:func:`_is_name_separator`), not
    by a hand-listed set of ASCII punctuation, so a typographic separator (en dash,
    Unicode hyphen, fullwidth period) unifies exactly like ``-`` while CJK, Cyrillic
    and emoji — letters and symbols, not punctuation — are preserved.
    """
    sanitized = _CAMEL_HUMP_RE.sub("-", _safe(name).strip())
    collapsed = "".join(
        "-" if _is_name_separator(char) else char for char in sanitized
    )
    return re.sub(r"-+", "-", collapsed).strip("-")


def _is_font_size_token(name: Any, value: Any) -> bool:
    """True when this token IS a font size, for LABELING purposes.

    OWNERSHIP, and nothing else. Decided by the token's NAME SHAPE plus a value
    that is any recognizable CSS font size (:data:`_FONT_SIZE_VALUE_RE`) — px or
    not, first at its size or not. It is deliberately independent of
    :func:`_font_size_px_ramp`, which is a lossy px-keyed projection built for
    BAND MATH.

    That independence is the round-6 fix. Ownership was previously read back out
    of the ramp map's values, which coupled a labeling question to the map's
    construction and produced two live surfaces of the v7 mislabel:

    * ``{px: name}`` keeps only the FIRST name per distinct pixel value
      (``setdefault``), so a second token at ``16px`` was not "a font size" and
      landed under ``SPACING TOKENS:``.
    * A px-keyed map cannot represent ``1rem`` / ``2em`` / ``125%`` /
      ``clamp(...)`` at all, so NO non-px font size was ever recognized.

    A map keyed by the thing you can compute bands from can never be the register
    of what exists — the two answer different questions, so they are now two
    functions.

    Round 7 (B1) corrected both halves of the test itself:

    * The NAME is normalized (:func:`_normalized_token_name`) before matching, so a
      brand's separator convention — ``fs.body``, ``font_size_body``,
      ``fontSizeBody``, ``font.size.body`` — cannot change the answer.
    * The name is normalized from the SANITIZED string, so the token that decides
      ownership is the token the artifact actually EMITS. Classifying the raw name
      let ``fs\\x1f-body`` be filed under spacing while it printed as ``fs-body``.
    * The VALUE grammar accepts ``var()`` and rejects values that are not valid CSS
      lengths (a negative length, a ``calc()`` containing no size).
    """
    if not _TYPE_SIZE_NAME_RE.match(_normalized_token_name(name)):
        return False
    return bool(_FONT_SIZE_VALUE_RE.match(_safe(value).strip()))


def _font_size_px_ramp(grouped: dict[str, list[tuple[str, str]]]) -> dict[float, str]:
    """The NUMERIC ramp: ``{px: token_name}`` over font-size tokens with px values.

    Deliberately lossy, and used for BAND MATH ONLY (:func:`_type_scale_section`):
    one entry per DISTINCT pixel size is exactly right for deriving role bands,
    since two tokens at 16px describe one rung of the scale. Non-px sizes are
    absent because they cannot be resolved to a pixel number without the document
    context, and inventing one would fabricate a numeric contract the brand never
    stated.

    It must NOT be used to decide labeling or exclusion — that is
    :func:`_is_font_size_token` / :func:`_font_size_token_pairs`. The token NAMES
    here are retained only for the deterministic ordering they impose.
    """
    ramp: dict[float, str] = {}
    for group in sorted(grouped):
        for name, value in grouped[group]:
            if not _is_font_size_token(name, value):
                continue
            px_match = _PX_VALUE_RE.match(value or "")
            if not px_match:
                continue
            px = float(px_match.group(1))
            if px <= 0:
                continue
            ramp.setdefault(px, str(name).strip())
    return ramp


def _font_size_token_pairs(
    grouped: dict[str, list[tuple[str, str]]]
) -> frozenset[tuple[str, str]]:
    """The exact ``(name, value)`` token pairs BRAND FONT-SIZE TOKENS owns.

    Used to suppress those pairs from the type/spacing rule lists and the generic
    sections so each size carries exactly ONE role cue (see ``_scale_section``).

    Computed by asking :func:`_is_font_size_token` of EVERY token directly. Three
    rounds of this defect all came from deriving ownership from something narrower
    than the question:

    1. v12 gated it on the ramp reaching :data:`_MIN_RAMP_SIZES`, so a bundle with
       one or two font sizes printed them under ``SPACING TOKENS:``.
    2. Then it was derived from the px-keyed ramp map's VALUES, so the SECOND token
       sharing a pixel value was not recognized (``setdefault`` keeps the first).
    3. And that same map made non-px sizes (``1rem``, ``2em``, ``125%``,
       ``clamp(...)``) unrepresentable, so every one of them was labeled spacing.

    Each is the same v7 small-titles mislabel — brand TYPE sizes presented to the
    model as gap values. The class is closed by taking ownership away from the ramp
    map entirely: this function iterates tokens, applies the ownership predicate,
    and keeps ALL matches including duplicates. Only :func:`_type_scale_section`
    consults the px ramp, and only for band math.

    Nothing is dropped by the wider exclusion: :func:`_font_size_token_section`
    derives from these SAME pairs, so every excluded token is re-homed there under
    a heading that names its real role.
    """
    return frozenset(
        (name, value)
        for entries in grouped.values()
        for name, value in entries
        if _is_font_size_token(name, value)
    )


def _eyebrow_px(sizes: list[float], body_bottom: float) -> float:
    """The ramp rung an eyebrow/kicker label sits on.

    THE LARGEST RUNG STRICTLY BELOW THE BODY BAND, falling back to the body band's
    own bottom rung when the ramp has nothing below it. Always a size the brand
    shipped — the same property the other four bands have.

    The definition follows from what an eyebrow IS: a label that is read, so it is
    real text rather than fine print, but subordinate to the body it sits above. On
    a ramp that ships a rung between the floor and body, that rung is the brand's
    own answer; a ramp with no such rung has no dedicated label size, and the
    smallest body rung is then the honest one rather than a number invented to fill
    the gap.

    Measured against the real bundle shape (12, 14, 16, 18, 20, 24, 32, 40, 48, 64):
    body is 16-20, so this returns 14 — which is the size that bundle's own
    ``.eyebrow`` CSS uses, reached without the compiler knowing anything about it.
    """
    below_body = [px for px in sizes if px < body_bottom]
    return max(below_body) if below_body else body_bottom


def _type_scale_section(grouped: dict[str, list[tuple[str, str]]]) -> str:
    """Build the BRAND TYPE SCALE block (always emitted; see comment above).

    Role mapping over the sorted distinct ramp sizes: cover/hero = top,
    floor = bottom, body = the 16-22px band (closest-to-18 when the ramp
    skips that range), section headers = the upper-middle entry between the
    body band and the top, eyebrow = the largest rung below the body band
    (:func:`_eyebrow_px`). Fewer than 3 distinct sizes is not a usable ramp
    -> neutral default bands.
    """
    ramp = _font_size_px_ramp(grouped)
    sizes = sorted(ramp)
    if len(sizes) < _MIN_RAMP_SIZES:
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
    else:
        body_label = _fmt_px(body_top)

    # NUMBERS ONLY. Every value here is formatted from a float the compiler
    # parsed out of a px token value, so no user-controlled text is interpolated
    # into this region at all — which is what closes the name-injection class
    # structurally instead of by pattern-matching names. The token NAMES behind
    # these sizes are listed in the typography/spacing sections, in full.
    return "\n".join(
        [
            "BRAND TYPE SCALE (REQUIRED — derived from this design system's "
            f"own tokens): {_TYPE_SCALE_MARKER}",
            f"- Cover/hero titles: {_fmt_px(hero_px)} — the top of the brand ramp.",
            f"- Section/slide titles: {_fmt_px(section_px)} or larger.",
            f"- Body text: {body_label}.",
            # The bands read in descending size order, so the eyebrow follows body
            # and precedes the floor. Like every other number in this region it is
            # formatted from a float the compiler parsed out of a px token value, so
            # the region stays numbers-only and no user text enters it.
            f"- Eyebrow/kicker labels (the small label above a title): "
            f"{_fmt_px(_eyebrow_px(sizes, body_sizes[0]))}, the SAME size on every "
            f"slide that carries one. {_EYEBROW_TREATMENT_CLAUSE}",
            f"- Floor: never render ANY text below {_fmt_px(floor_px)}, the "
            "bottom of the brand ramp.",
            _TYPE_SCALE_ANTI_SHRINK_LINE,
        ]
    )


# --- Late numeric re-assertion (salience) ----------------------------------
#
# The compiled artifact is prompt block #2: ``build_generation_system_prompt``
# appends ``slide_style`` BEFORE ``BASE_PROMPT`` and every generic styling block.
# So a type scale stated only inside the compiled blob is always read EARLY,
# buried in a ~10k-char brand manual, and competes with the generic instructions
# that follow it. The measured consequence was the model falling back to trained
# priors (56px covers against a 64px spec; content titles at 32px against a 40px
# floor). This block restates the SAME derived numbers as the LAST thing in the
# assembled prompt — last instruction wins — plus a pre-emit self-check. It is
# appended at PROMPT-ASSEMBLY time (``agent_factory``) like the SELECTED-TEMPLATE
# block, so the persisted artifact is unchanged and the no-DS golden prompts stay
# byte-identical.
TYPE_SCALE_REASSERTION_HEADING = "FINAL CHECK — TITLE TYPE SCALE (do this last):"

# Role lines carry the derived numbers; the anti-shrink line is prose already
# restated below, so it is not echoed twice.
_REASSERTION_ROLE_PREFIXES = (
    "- Cover/hero",
    "- Section/slide",
    "- Floor:",
)

_TYPE_SCALE_SELF_CHECK_LINE = (
    "- Before emitting, re-read every slide you have written and verify each "
    "title's font-size meets the required scale above. Fix any that fall short "
    "BEFORE you output the deck."
)

# When a template is PINNED its own CSS sizes are authoritative — re-asserting
# ramp numbers here could contradict them (e.g. a template shipping a 56px
# ``.action-title`` against a 64px ramp top). A pinned deck was observed
# inline-shrinking that 56px title to 26px, so the pinned variant forbids
# shrinking below the template's sizes instead of restating numbers.
_TYPE_SCALE_PINNED_BLOCK = "\n".join(
    [
        TYPE_SCALE_REASSERTION_HEADING,
        "- The pinned template's own heading/title font sizes are AUTHORITATIVE: "
        "use them exactly as the template's CSS ships them, on every slide type "
        "including the cover and closing slide.",
        "- Never shrink a title below the template's size — not with an inline "
        "style, not with an overriding rule, not on a 'denser' slide. To make "
        "content fit, trim it or split it across more slides.",
        "- Before emitting, re-read every slide you have written and verify no "
        "title renders smaller than the template's own size for that slide type. "
        "Fix any that do BEFORE you output the deck.",
    ]
)


def build_type_scale_reassertion(
    type_scale_block: str, *, template_pinned: bool = False
) -> str:
    """Build the LAST-position restatement of the title type-scale contract.

    *type_scale_block* is the BRAND TYPE SCALE section this design system already
    compiled; its role lines are echoed VERBATIM so the re-asserted numbers are
    by construction the bundle's own (nothing is recomputed or hardcoded here).
    When *template_pinned* is True the pinned template's CSS sizes win instead —
    see :data:`_TYPE_SCALE_PINNED_BLOCK`.
    """
    if template_pinned:
        return _TYPE_SCALE_PINNED_BLOCK

    role_lines = [
        line
        for line in (type_scale_block or "").splitlines()
        if line.startswith(_REASSERTION_ROLE_PREFIXES)
    ]
    if not role_lines:
        # No parseable role lines (e.g. the neutral block's differently-worded
        # bands): echo the whole block's bullets rather than losing the contract.
        role_lines = [
            line
            for line in (type_scale_block or "").splitlines()
            if line.startswith("- ") and "NEVER shrink" not in line
        ]

    return "\n".join(
        [
            TYPE_SCALE_REASSERTION_HEADING,
            *role_lines,
            "- These are REQUIRED minimums for titles, not suggestions. Do NOT "
            "substitute your own default heading sizes.",
            _TYPE_SCALE_SELF_CHECK_LINE,
        ]
    )


def _trim_blank_lines(text: str) -> str:
    """Drop WHOLLY BLANK lines from each end of *text*, leaving every line's own
    indentation and inner blank lines untouched.

    The blank-line half of what a bare ``.strip()`` used to do here, without the
    aesthetic half. A leading run of empty lines would open a gap under the BRAND
    MANUAL heading, so removing it is structural; the SPACES INSIDE the first
    surviving line are markdown the brand authored, so they stay.
    """
    lines = text.split("\n")
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end])


def _brand_manual_section(skill_md: Optional[str], readme_md: Optional[str]) -> Optional[str]:
    """Assemble the BRAND MANUAL block: the FULL README then the FULL SKILL.md.

    UNFILTERED and UNTRUNCATED — both documents are injected verbatim (the huashu
    / Claude-Design "brand operating manual" model). README is the primary
    operating manual, so it comes first; SKILL.md follows. Returns ``None`` when
    neither source contributes text, so a design system without a SKILL/README
    simply omits the block (backward compatible).
    """
    # README / SKILL are prose documents whose LINE structure carries meaning
    # (markdown), so they are normalized rather than flattened — see
    # ``_safe_multiline``. They are injected OUTSIDE the type-scale region, so
    # they cannot reach the numeric contract regardless.
    #
    # BLANK LINES are trimmed from each end, INDENTATION is not (v17). This used to be
    # a bare ``.strip()``, which is a WHITESPACE strip: it also removed the authored
    # indentation of the document's FIRST line and the trailing spaces of its LAST. In
    # markdown that indentation is content — four spaces is a code block, two is a
    # nested list item — so a manual opening with an indented code sample was handed to
    # the model as prose. Only the blank lines around the document are the compiler's
    # to normalize, because those are what would otherwise open a gap under the
    # heading.
    readme = _trim_blank_lines(_safe_multiline(readme_md))
    skill = _trim_blank_lines(_safe_multiline(skill_md))
    body_parts = [part for part in (readme, skill) if part.strip()]
    if not body_parts:
        return None
    return "\n\n".join([_BRAND_MANUAL_HEADING, *body_parts])


def _resolve_group(raw_group: Any) -> str:
    """Map a stored token group onto a canonical group, or pass it through.

    Canonical groups and their synonyms (:data:`_GROUP_ALIASES`) resolve to the
    canonical spelling so they reach the purpose-built emitter. ANY other group is
    returned as its own key — lowercased and stripped so casing/padding variants
    of the same author-invented group collapse into ONE generic section instead of
    several — and is emitted under the generic heading. Nothing resolves to
    "dropped": this function has no failure mode that loses a token.
    """
    key = str(raw_group or "").strip().lower()
    if key in _CANONICAL_GROUPS:
        return key
    return _GROUP_ALIASES.get(key, key)


def _grouped_tokens(design_system: Any) -> dict[str, list[tuple[str, str]]]:
    """Return ``group -> [(name, value), ...]`` with each list sorted by name.

    Sorting here is what makes the output order-independent of however the ORM
    relationship happened to load the rows.

    Group names are resolved through :func:`_resolve_group` HERE, at the one place
    raw group strings enter the compiler, so every downstream consumer — the
    emitters, the ramp detector, the generic-section builder — agrees on which
    group a token belongs to without repeating the aliasing.
    """
    grouped: dict[str, list[tuple[str, str]]] = {}
    for token in getattr(design_system, "tokens", None) or []:
        grouped.setdefault(_resolve_group(token.group), []).append((token.name, token.value))
    for group in grouped:
        grouped[group].sort(key=lambda name_value: (name_value[0], name_value[1]))
    return grouped


def _authored_group_labels(design_system: Any) -> dict[str, str]:
    """``resolved_group -> the label the BRAND actually wrote``.

    :func:`_resolve_group` lowercases and strips its key on purpose, so that
    ``Brand-Semantic``, ``brand-semantic`` and ``  brand-semantic  `` collapse into
    ONE generic section rather than three. That is right for GROUPING, and wrong for
    DISPLAY: the artifact must show the brand its own spelling, not a normalized
    one, because casing is part of the text the brand authored and hard rule A does
    not permit altering it.

    So the two concerns are two mappings: the grouping key stays normalized, and the
    authored spelling is recovered here for the label line alone.

    THE SPELLING IS RECORDED VERBATIM, whitespace included. It used to be stripped
    here (and again at the point of display), so a brand that authored
    ``" Brand Semantic "`` was shown ``"Brand Semantic"``. Only control and sentinel
    bytes may be removed from a user string — the rule that keeps a 300-character
    label uncapped, and that already forced the revert of an earlier round's
    multi-space collapse for RENAMING a legitimate token. A space is neither, so
    normalising it away is the same class of silent loss.

    Emptiness is decided on the STRIPPED text, because a group whose name is nothing
    but whitespace has no spelling for the artifact to show; the display decision
    lives in :func:`_group_label_lines`, which handles that case explicitly.

    Ties are resolved deterministically. When several spellings share one key the
    FIRST in sorted order wins — an arbitrary but stable choice, since the artifact
    can only show one and any preference between equal claims would be invented.
    Sorting compares the verbatim spellings, so the choice stays a pure function of
    what the brand wrote.
    """
    labels: dict[str, str] = {}
    for token in getattr(design_system, "tokens", None) or []:
        raw = str(token.group or "")
        if not raw.strip():
            continue
        key = _resolve_group(token.group)
        existing = labels.get(key)
        if existing is None or raw < existing:
            labels[key] = raw
    return labels


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
        spec_lines.append(f"- {_safe(group)}:")
        for name, value in entries:
            spec_lines.append(f"  - {_safe(name)}: {_safe(value)}")
            slug = _slug(name)
            if (group, slug) in seen_vars:
                continue
            seen_vars.add((group, slug))
            css_vars.append(f"  --brand-{_safe(group)}-{slug}: {_safe(value)};")

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


# --- Text contrast (WCAG AA), computed from the brand's OWN colors -----------
#
# The artifact used to carry NO contrast guidance at all, and the model was left to
# pick a background from the palette and then an ink from the same palette with
# nothing checking the pair. Two shipped pairs measured 2.73:1 and 2.81:1.
#
# Generic prose ("meet 4.5:1") was the cheaper fix and it is strictly worse: it
# restates the requirement without telling the model which of THIS system's colors
# satisfy it, which is the only question it actually has to answer. So the compiler
# computes the answer.
#
# IT EMITS PARSED COLORS ONLY — never a token NAME. This is the same structural
# argument the numbers-only type-scale region rests on, and here it is even
# stronger: a string reaching this section has matched a fully-anchored color
# grammar, so it cannot carry marker text, instruction-shaped prose, a line break
# or a region sentinel — not because it was sanitized, but because a valid CSS
# color cannot contain any of them. The value is re-serialized from the three
# integers the compiler parsed, so what is emitted is the compiler's own text.
#
# That also keeps the section clear of the one live hazard here: a color token
# NAMED ``brand [ds-type-scale]`` is a fixture in this repo's own suite. Naming
# colors would have put user text next to a compiler contract for the sixth time
# in this module's history. ``BRAND COLOR TOKENS:`` sits directly above and maps
# every value back to its authored name, so nothing is lost by naming nothing —
# and the model writes CSS with the value anyway.
_CONTRAST_AA_NORMAL = 4.5
_CONTRAST_AA_LARGE = 3.0

# The requirement itself, shared by both branches so the numbers are stated once.
_CONTRAST_AA_REQUIREMENT_LINE = (
    "- Every text/background pair must meet WCAG AA: at least "
    f"{_CONTRAST_AA_NORMAL:g}:1 for normal text, and at least "
    f"{_CONTRAST_AA_LARGE:g}:1 for large text (24px and above, or bold from 19px). "
    "Choose the background first, then the text color, then check that pair."
)

_CONTRAST_DERIVED_HEADING = (
    "BRAND TEXT CONTRAST (REQUIRED — computed from this design system's own "
    "color tokens):"
)

# Closes the derived block. The pair rule is what covers everything the two
# extremes do not: the measured failures were mid-tone ON mid-tone, which is
# exactly the pair a palette makes easy to reach for and a luminance table cannot
# enumerate without listing every combination.
_CONTRAST_PAIR_RULE_LINE = (
    "- For any other pair of these colors, work out the ratio before you use it: "
    f"two mid-tone brand colors together almost never reach {_CONTRAST_AA_NORMAL:g}:1. "
    "If a pair falls short, change the background or the text color — never lower "
    "the requirement."
)

# Fallback when fewer than two colors can be resolved (a token-less system, or one
# whose colors are all in forms with no computable value). The requirement is still
# stated — the vacuum this whole block exists to close must not be able to reopen
# for a bundle the compiler happens not to be able to read — but nothing is claimed
# to be "computed from" colors that were not.
_CONTRAST_GENERIC_BLOCK = "\n".join(
    [
        "BRAND TEXT CONTRAST (REQUIRED):",
        _CONTRAST_AA_REQUIREMENT_LINE,
        "- Work out the ratio for every pair you use: two mid-tone colors together "
        f"almost never reach {_CONTRAST_AA_NORMAL:g}:1. If a pair falls short, change "
        "the background or the text color — never lower the requirement.",
    ]
)

# ``#rgb`` / ``#rgba`` / ``#rrggbb`` / ``#rrggbbaa``. Lengths 5 and 7 are not valid
# CSS hex colors and are rejected by the length check in :func:`_rgb_from_hex`.
_HEX_COLOR_RE = re.compile(r"^#([0-9a-f]{3,8})$", re.IGNORECASE)

# ``rgb()`` / ``rgba()`` in both the legacy comma form and the modern space form
# (``rgb(0 0 0 / 50%)``). Anchored at both ends: a value that merely CONTAINS a
# color (a shadow, a gradient) must not be read as one, because the color that
# ends up behind the text in those cases is not this value.
_RGB_FUNC_RE = re.compile(
    r"""^rgba?\(\s*
        ([0-9.]+%?)\s*(?:,\s*|\s+)
        ([0-9.]+%?)\s*(?:,\s*|\s+)
        ([0-9.]+%?)
        (?:\s*[,/]\s*([0-9.]+%?))?
        \s*\)$""",
    re.IGNORECASE | re.VERBOSE,
)


def _rgb_from_hex(digits: str) -> Optional[tuple[int, int, int]]:
    """Parse the digits of a hex color, rejecting anything not fully opaque."""
    if len(digits) in (3, 4):
        channels = [int(digit * 2, 16) for digit in digits]
    elif len(digits) in (6, 8):
        channels = [int(digits[at : at + 2], 16) for at in range(0, len(digits), 2)]
    else:
        return None
    if len(channels) == 4 and channels[3] != 255:
        return None
    return (channels[0], channels[1], channels[2])


def _color_channel(raw: str) -> int:
    """One ``rgb()`` channel as 0-255, accepting the number or percentage form."""
    number = float(raw[:-1]) * 255.0 / 100.0 if raw.endswith("%") else float(raw)
    return max(0, min(255, int(round(number))))


def _parse_opaque_color(value: Any) -> Optional[tuple[int, int, int]]:
    """The ``(r, g, b)`` of *value*, or ``None`` when it is not an opaque color.

    ``None`` covers three DIFFERENT situations, and all three must be excluded
    rather than guessed at:

    * NOT A COLOR — a spacing length, a font stack, a shadow. The grammars are
      anchored at both ends, so ``0 1px 2px rgba(0,0,0,0.1)`` does not read as
      ``rgba(0,0,0,0.1)``: the color behind text on a shadowed element is not the
      shadow's color, and treating it as one would put a value in the table that
      no text ever sits on.
    * A COLOR THIS FUNCTION CANNOT RESOLVE — ``hsl()``, ``lab()``, ``color-mix()``,
      a named color, ``currentColor``, ``var(--x)``. Omitting them understates the
      palette, which is the safe direction: the pair rule still covers them, while
      inventing a luminance would state a ratio the brand never authored.
    * TRANSLUCENT — any alpha below 1. A translucent color's effective luminance
      depends on what is composited BEHIND it, which the compiler does not know, so
      its contrast is genuinely not computable. Assuming white (the usual shortcut)
      would report a ratio that is wrong on every dark surface.
    """
    text = _safe(value).strip()
    hex_match = _HEX_COLOR_RE.match(text)
    if hex_match:
        return _rgb_from_hex(hex_match.group(1))
    func_match = _RGB_FUNC_RE.match(text)
    if not func_match:
        return None
    try:
        alpha = func_match.group(4)
        if alpha is not None and (
            float(alpha[:-1]) / 100.0 if alpha.endswith("%") else float(alpha)
        ) < 1.0:
            return None
        return (
            _color_channel(func_match.group(1)),
            _color_channel(func_match.group(2)),
            _color_channel(func_match.group(3)),
        )
    except ValueError:
        # The character class admits malformed numbers ("1.2.3"); a value that is
        # not a number is not a color.
        return None


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x relative luminance of an opaque sRGB color."""

    def _linear(channel: int) -> float:
        ratio = channel / 255.0
        return ratio / 12.92 if ratio <= 0.03928 else ((ratio + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * _linear(rgb[0]) + 0.7152 * _linear(rgb[1]) + 0.0722 * _linear(rgb[2])
    )


def _contrast_ratio(one: float, other: float) -> float:
    """WCAG contrast ratio between two relative luminances."""
    lighter, darker = max(one, other), min(one, other)
    return (lighter + 0.05) / (darker + 0.05)


def _fmt_hex(rgb: tuple[int, int, int]) -> str:
    """Canonical ``#RRGGBB`` — the compiler's own rendering of a parsed color."""
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _palette_luminances(
    grouped: dict[str, list[tuple[str, str]]]
) -> list[tuple[float, str]]:
    """``[(luminance, "#RRGGBB"), ...]`` for every resolvable color, ascending.

    Read from EVERY token group by VALUE, not from the color groups by membership —
    the same reasoning that makes ramp detection a name+value question. Group
    aliasing already routes ``color``/``palette`` to a color group, but a color
    filed under an author-invented group (``brand-semantic``) reaches no color
    emitter at all, and it is still a color the model may put text on.

    De-duplicated by canonical value: two tokens naming one color are one color
    here. Sorted by ``(luminance, value)`` so the output is a pure function of the
    palette and not of load order.
    """
    by_value: dict[str, float] = {}
    for entries in grouped.values():
        for _name, value in entries:
            rgb = _parse_opaque_color(value)
            if rgb is None:
                continue
            by_value.setdefault(_fmt_hex(rgb), _relative_luminance(rgb))
    return sorted((luminance, value) for value, luminance in by_value.items())


def _contrast_section(grouped: dict[str, list[tuple[str, str]]]) -> str:
    """Build the BRAND TEXT CONTRAST block (always emitted).

    The palette's own extremes are the two inks the block can speak about
    RIGOROUSLY: for any single ink, "which of these colors reach AA behind it" is
    answerable in one pass, whereas the full pairing is quadratic in the palette
    and a real bundle ships hundreds of tokens. So the block states what it has
    actually computed — the AA-safe backgrounds for the lightest ink, for the
    darkest ink, and the colors that reach AA with NEITHER — and hands the model a
    rule for every other pair.

    That third list is the one that addresses the measured defect. A mid-tone that
    fails against both extremes fails against everything between them too, so
    naming it as "never put normal text here" is a complete answer for that color,
    not a heuristic.
    """
    colors = _palette_luminances(grouped)
    if len(colors) < 2:
        return _CONTRAST_GENERIC_BLOCK

    darkest_luminance, darkest = colors[0]
    lightest_luminance, lightest = colors[-1]

    def _reaching_aa(ink_luminance: float) -> list[str]:
        return [
            value
            for luminance, value in colors
            if _contrast_ratio(luminance, ink_luminance) >= _CONTRAST_AA_NORMAL
        ]

    on_lightest = _reaching_aa(lightest_luminance)
    on_darkest = _reaching_aa(darkest_luminance)
    unusable = [
        value
        for luminance, value in colors
        if _contrast_ratio(luminance, lightest_luminance) < _CONTRAST_AA_NORMAL
        and _contrast_ratio(luminance, darkest_luminance) < _CONTRAST_AA_NORMAL
    ]

    lines = [
        _CONTRAST_DERIVED_HEADING,
        _CONTRAST_AA_REQUIREMENT_LINE,
        f"- The two safest text colors in this system are its extremes: {lightest} "
        f"(the lightest) and {darkest} (the darkest).",
    ]
    if on_lightest:
        lines.append(
            f"- Use {lightest} as the text color on these backgrounds: "
            f"{', '.join(on_lightest)}"
        )
    if on_darkest:
        lines.append(
            f"- Use {darkest} as the text color on these backgrounds: "
            f"{', '.join(on_darkest)}"
        )
    if unusable:
        lines.append(
            "- Never set normal text on these colors — they reach "
            f"{_CONTRAST_AA_NORMAL:g}:1 with NEITHER extreme, so use them for "
            f"fills, rules, icons and imagery only: {', '.join(unusable)}"
        )
    lines.append(_CONTRAST_PAIR_RULE_LINE)
    return "\n".join(lines)


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
        spec_lines.append(f"- {_safe(name)}: {_safe(value)}")
        slug = _slug(name)
        if slug in seen:
            continue
        seen.add(slug)
        css_vars.append(f"  --brand-shadow-{slug}: {_safe(value)};")
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
    grouped: dict[str, list[tuple[str, str]]],
    group: str,
    heading: str,
    *,
    exclude: frozenset[tuple[str, str]] = frozenset(),
) -> Optional[str]:
    """Render a non-color token group (type/spacing) as a simple rule list.

    ``exclude`` holds ``(name, value)`` pairs already surfaced authoritatively
    elsewhere — the font-size ramp, which BRAND TYPE SCALE owns. Reprinting a
    ramp entry here would restate a font size under a heading that names a
    DIFFERENT role (``SPACING TOKENS:`` for a Claude-Design-mislabeled ramp),
    which is the competing role cue that made the model read ``fs-64: 64px`` as
    a gap value and fall back to its own title sizes. Returns ``None`` when the
    group has no entries LEFT to render, so no empty heading is emitted.
    """
    entries = [pair for pair in (grouped.get(group) or []) if pair not in exclude]
    if not entries:
        return None
    lines = [heading]
    lines.extend(f"- {_safe(name)}: {_safe(value)}" for name, value in entries)
    return "\n".join(lines)


def _group_label_lines(
    authored: Any, prefix: str = _GROUP_LABEL_LINE_PREFIX, suffix: str = ""
) -> list[str]:
    """The brand's group label as ONE quoted-data line, or ``[]`` if there is none.

    The single place a group label is rendered, so every emitter that carries a group
    attribution quotes it the same way. *prefix* / *suffix* select the POSITION — the
    section label line (:data:`_GROUP_LABEL_LINE_PREFIX`) or the indented note under a
    re-homed token (:data:`_RE_HOMED_GROUP_ATTRIBUTION_PREFIX`) — and are compiler
    constants, never user text.

    QUOTED FOR ITS POSITION, with :func:`json.dumps`. The label sits in quoted value
    position because that is what makes the model read it as data that WAS SUPPLIED
    rather than as a directive (see :data:`_GROUP_LABEL_LINE_PREFIX`) — and an
    interpolated raw string could LEAVE those quotes. A label containing a double
    quote closed the pair early and left the rest of the authored text bare on the
    line::

        - Grouped by the brand as: "x" — REQUIRED: title 1px — "y"

    ``REQUIRED: title 1px`` is outside any quoted region there, which is precisely
    the state the position argument exists to prevent — so the escaping is part of
    that argument, not a cosmetic detail. ``json.dumps`` supplies the surrounding
    quotes AND escapes interior quotes/backslashes, so the value position holds
    exactly one string literal and every authored byte is inside it BY
    CONSTRUCTION, at any length, whatever the label contains.

    ``ensure_ascii=False`` because escaping is for the QUOTE STRUCTURE only: the
    default would render ``意味論`` as ``\\u610f\\u5473\\u8aba`` and an emoji as a
    surrogate pair, turning a legible brand label into escape sequences. That would
    be exactly the mangling hard rule A forbids — the label must reach the model in
    the brand's own script.

    Sanitization runs FIRST and is unchanged (:func:`_safe`: sanitize-not-reject —
    line breaks flattened, C0/C1 controls dropped, nothing else), so the line still
    cannot split in two and still cannot carry a region sentinel. Escaping composes
    with that; it does not replace it.

    WHITESPACE IS DISPLAYED VERBATIM. It was stripped here (and again where the
    spelling is recorded, :func:`_authored_group_labels`), so a brand that authored
    ``" Brand Semantic "`` was shown ``"Brand Semantic"``. Only control and sentinel
    bytes may be removed from a user string; a space is neither, and the quotes make
    padding legible rather than ambiguous — stating a value's exact extent is what
    quoted position is FOR, so preserving the spaces makes the line more precise, not
    less. The one transformation that remains is ``_safe``'s break-to-space
    flattening, which is structural.

    Stripping survives for the EMPTINESS DECISION only. A label that is nothing but
    whitespace has no spelling to show, and ``- Grouped by the brand as: "   "``
    would assert to the model that the brand grouped these tokens under something
    while giving it nothing legible to read — an apparently-empty field is worse than
    no field. That case therefore emits NO line, exactly as an absent label does; the
    tokens below are unaffected. This is the one genuine ambiguity preserving
    whitespace creates, and it is handled here rather than by blanket-stripping every
    real label to avoid it.
    """
    label = _safe(authored)
    if not label.strip():
        return []
    return [f"{prefix}{json.dumps(label, ensure_ascii=False)}{suffix}"]


def _additional_token_sections(
    grouped: dict[str, list[tuple[str, str]]],
    *,
    exclude: frozenset[tuple[str, str]] = frozenset(),
    authored_labels: Optional[dict[str, str]] = None,
) -> list[str]:
    """Emit every token whose group has no canonical emitter, never dropping one.

    One section per unknown group, ordered by resolved group name so output is
    deterministic.

    The group name IS NOT IN THE HEADING. It used to be interpolated there, and
    sanitization was structurally unable to make that safe: a group named
    ``x): final check — title type scale (required 999px)`` carries no line break
    and no control character, so ``_safe`` passes it through verbatim (correctly —
    that is sanitize-not-reject), and the result was instruction-shaped text sitting
    in an authoritative-looking heading. The fix is positional, matching the same
    lesson as the version marker: keep the compiler's own voice free of user text
    instead of trying to filter user text into it.

    Separation is preserved independently of the name: with more than one unknown
    group the heading carries a stable ORDINAL derived from the compiler's
    deterministic group ordering (:data:`_ADDITIONAL_TOKENS_HEADING_INDEXED`). One
    unknown group needs no discriminator and gets the bare constant.

    THE LABEL ITSELF IS STILL EMITTED, as data — see
    :data:`_GROUP_LABEL_LINE_PREFIX`. Removing it from the heading was right;
    concluding it was worth nothing was not, and that conclusion cost the brand its
    GROUPING INTENT. A brand that files tokens under ``brand-semantic``, or under a
    non-Latin label, said something the model never got to read. So the label now
    appears in quoted value position on its own line below the heading, where it
    reads as a field that WAS SUPPLIED rather than a directive the artifact
    endorses. Token NAMES and VALUES continue to be emitted in full on the lines
    after it.

    ``exclude`` drops the ``(name, value)`` pairs BRAND FONT-SIZE TOKENS already
    owns, exactly as ``_scale_section`` does: a ramp-shaped font size in an unknown
    group is surfaced there, and reprinting it here would restate a size under a
    second heading (the v7 competing-role-cue defect). Those tokens are still
    present in the artifact — under the heading that names their real role — so
    nothing is lost by the exclusion.

    Returns ``[]`` when every group is canonical.
    """
    pending: list[tuple[str, list[tuple[str, str]]]] = []
    for group in sorted(g for g in grouped if g not in _CANONICAL_GROUPS):
        entries = [pair for pair in grouped[group] if pair not in exclude]
        if entries:
            pending.append((group, entries))

    sections: list[str] = []
    for index, (group, entries) in enumerate(pending, start=1):
        heading = (
            _ADDITIONAL_TOKENS_HEADING
            if len(pending) == 1
            else _ADDITIONAL_TOKENS_HEADING_INDEXED % index
        )
        # The label is carried as DATA, in quoted value position on its own line
        # (:data:`_GROUP_LABEL_LINE_PREFIX`) — never in the heading. ``_safe``
        # flattens line breaks and strips the control range, so the line cannot
        # split into two and cannot carry a region sentinel; everything else
        # survives at any length in any script.
        #
        # The AUTHORED spelling is preferred over the resolved key, which
        # ``_resolve_group`` lowercased for grouping purposes (see
        # :func:`_authored_group_labels`). Falls back to the key when no authored
        # spelling was recorded, so the line is never lost.
        authored = (authored_labels or {}).get(group, group)
        label_lines = _group_label_lines(authored)
        sections.append(
            "\n".join(
                [
                    heading,
                    *label_lines,
                    *(f"- {_safe(name)}: {_safe(value)}" for name, value in entries),
                ]
            )
        )
    return sections


def _font_size_token_section(
    grouped: dict[str, list[tuple[str, str]]],
    *,
    authored_labels: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """List the ramp's font-size tokens by NAME under a FONT-SIZE heading.

    Ramp-shaped tokens are suppressed from the TYPOGRAPHY/SPACING rule lists on
    purpose (v7: a font size printed under ``SPACING TOKENS:`` is a competing
    role cue that measurably made the model read a brand cover size as a gap
    value). Their names used to be echoed inside the BRAND TYPE SCALE region
    instead — which is where the name-injection problem lived, and where an
    allowlist then silently DROPPED any name that did not look like a plain
    identifier.

    So the names get their own correctly-labeled home, OUTSIDE the compiler-owned
    numeric region: every ramp token is listed here, in full, whatever its length
    or script, while the region next to it stays numbers-only. Nothing is
    dropped and nothing is mislabeled.

    Ordered by px value ascending (the ramp's own order) then name, with non-px
    sizes following the numeric run in name order — they carry no comparable pixel
    number. Output stays deterministic. Returns ``None`` only when the design system
    ships no font-size token at all, so there is nothing to re-home.

    Derives from :func:`_font_size_token_pairs`, the SAME set the exclusion uses, so
    the two cannot drift: this section is the HOME of every excluded font size, and
    it exists exactly when the exclusion does. That pairing is what keeps the
    widened ownership loss-free — every token taken out of the type/spacing lists is
    listed here instead, whatever its value form and however many tokens share its
    size.

    The heading deliberately does NOT contain the words "BRAND TYPE SCALE": that
    phrase is how callers (and tests) locate the compiler-owned numeric region by
    index, so reusing it here would shadow the real region. It is also a CONSTANT:
    the attribution below carries the brand's group name, so the heading itself never
    has to, and stays the compiler's own voice.

    ``authored_labels`` supplies the brand's spelling per resolved group so a token
    RE-HOMED out of an author-invented group keeps that group's attribution
    (:data:`_RE_HOMED_GROUP_ATTRIBUTION_PREFIX`). Without it the label of a group
    whose only token is a font size reached the artifact nowhere at all.
    """
    font_size_pairs = _font_size_token_pairs(grouped)
    if not font_size_pairs:
        return None

    def _px_of(value: str) -> float:
        match = _PX_VALUE_RE.match(value or "")
        return float(match.group(1)) if match else 0.0

    # px sizes ascending first (the ramp's own order), then the non-px ones —
    # which have no comparable pixel number, so they sort by name after the
    # numeric run rather than all colliding at 0.0 ahead of it.
    entries = sorted(
        font_size_pairs,
        key=lambda pair: (
            0 if _PX_VALUE_RE.match(pair[1] or "") else 1,
            _px_of(pair[1]),
            pair[0],
        ),
    )
    attributions = _re_homed_group_attributions(grouped, authored_labels)
    lines = [
        # The heading names the tokens' ROLE without promising that the block below
        # derives its bands from them: with fewer than ``_MIN_RAMP_SIZES`` distinct
        # sizes the numeric contract falls back to the neutral bands, so wording that
        # asserted "the required sizes for each role are stated below" would have been
        # false for exactly the short-ramp case this decoupling introduced.
        "BRAND FONT-SIZE TOKENS (this design system's font-size tokens; they "
        "are TYPE sizes, never spacing or gap values):"
    ]
    for name, value in entries:
        lines.append(f"- {_safe(name)}: {_safe(value)}")
        # The attribution follows the token it describes, so the brand's grouping
        # intent is readable at the token that carries it.
        lines.extend(attributions.get((name, value), ()))
    return "\n".join(lines)


def _re_homed_group_attributions(
    grouped: dict[str, list[tuple[str, str]]],
    authored_labels: Optional[dict[str, str]],
) -> dict[tuple[str, str], list[str]]:
    """``(name, value) -> attribution line(s)`` for tokens re-homed out of a group.

    Emitted ONLY for groups with no canonical emitter — the author-invented ones. A
    canonical group name (``type``, ``spacing``) is this app's OWN vocabulary, not
    something the brand said, so attributing a token to it would invent a claim the
    brand never made and add a line to artifacts that have nothing to disclose.

    A token appearing under SEVERAL author-invented groups gets one line per distinct
    label, in sorted order: the pairs are de-duplicated before they reach the
    font-size section, so a single listed token can legitimately carry more than one
    grouping claim, and picking one of them would silently drop the others. Sorting
    keeps the output deterministic.
    """
    labels = authored_labels or {}
    attributions: dict[tuple[str, str], list[str]] = {}
    for group in sorted(g for g in grouped if g not in _CANONICAL_GROUPS):
        for pair in grouped[group]:
            if not _is_font_size_token(*pair):
                continue
            lines = _group_label_lines(
                labels.get(group, group),
                prefix=_RE_HOMED_GROUP_ATTRIBUTION_PREFIX,
                suffix=")",
            )
            for line in lines:
                if line not in attributions.setdefault(pair, []):
                    attributions[pair].append(line)
    for pair in attributions:
        attributions[pair].sort()
    return attributions


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
        detail = f"- {_safe(name)}"
        if variant_labels:
            detail += f": weights {', '.join(_safe(label) for label in variant_labels)}"
        if tokens:
            detail += f" (tokens: {', '.join(_safe(token) for token in tokens)})"
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
        lines.append(
            f"- {_safe(name)}: {_safe(description)}"
            if description
            else f"- {_safe(name)}"
        )

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
        lines.append(f"- {_safe(filename)} -> {DS_ASSET_PLACEHOLDER % asset.id}")
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
    color tokens -> BRAND TEXT CONTRAST (always present: WCAG AA pairings
    computed from those colors, or the requirement alone when fewer than two
    resolve) -> the remaining tokens (type, spacing, shadow, then any group
    with no canonical emitter under ADDITIONAL BRAND TOKENS; all uncapped) ->
    BRAND TYPE SCALE (always present: ramp-derived role anchors including the
    eyebrow band, or the neutral default bands when no ramp is recognizable) ->
    fonts (@font-face refs + family listing; uncapped) -> templates (closed by
    the soft-pick enabler) -> SLIDE FRAME CONSTRAINTS (frame guardrails, always
    present) -> the brand IMAGE ASSET CONTRACT (fetch via
    ``search_brand_assets``). Brand images are NOT enumerated.
    """
    parts: list[str] = []

    # ``_header_safe_name`` also strips marker-shaped text: this name lands in the
    # version-stamped header slot, so it must not be able to contribute a marker at
    # any position on that line (see ``_MARKER_LIKE_RE``).
    #
    # The authored WHITESPACE survives (v17) — the name reaches the model as the brand
    # wrote it. Only EMPTINESS is decided on the stripped form, so a name that is
    # nothing but whitespace (or nothing but marker text) still yields the default
    # label instead of a header with no name segment. Deciding on ``.strip()`` while
    # emitting the original is the same split the importer applies on ingress.
    safe_name = _header_safe_name(getattr(design_system, "name", None) or "Design System")
    name = safe_name if safe_name.strip() else "Design System"
    # The version marker rides on the header line (no schema change) so persisted
    # artifacts self-describe which compiler produced them — see
    # ``compiled_style_content_is_current``.
    #
    # POSITION IS THE SECURITY PROPERTY (v12). The marker sits in a FIXED slot
    # immediately after the constant ``SLIDE VISUAL STYLE:`` label, BEFORE the
    # name, so the compared region is a compiler-owned constant that no user text
    # can precede or extend. Emitting it after the name instead made currency a
    # function of what the header ENDED WITH — and the header ends with
    # user-controlled text by construction, because the name is interpolated into
    # it. A design system named ``Evil Brand [ds-compiler v12]`` therefore made a
    # STALE pre-version body read as current, so it never recompiled.
    #
    # The name still follows in full (nothing is hidden from the model); it simply
    # cannot reach the region the version check reads. The name is sanitized as
    # well, so it cannot inject additional header lines.
    #
    # The human-readable marker STAYS on the header line — it is greppable in logs
    # and in a persisted row, and it tells a reader which compiler produced the
    # artifact. It is no longer what the currency CHECK reads: that is
    # ``_CURRENCY_SENTINEL``, prepended below in a position no user text can occupy.
    parts.append(f"{_HEADER_VERSION_PREFIX} {name}")

    # A short frontmatter-style description/identity caption comes FIRST (huashu /
    # Claude Code skill convention: blurb -> manual); the full brand manual below
    # is the first FULL/substantive block. It is a one-line caption, so it is
    # flattened like every other single-line user string.
    #
    # Emitted with its authored whitespace (v17): the caption is free prose the brand
    # wrote, and a ``.strip()`` here was purely cosmetic — it made the model-facing
    # caption differ from the stored column for no structural gain. ``_safe`` still
    # removes what matters (controls, line breaks), so the caption cannot become two
    # blocks or carry a sentinel. Emptiness is still decided on the stripped form, so a
    # whitespace-only description contributes no blank caption block.
    description = _safe(getattr(design_system, "description", None))
    if description.strip():
        parts.append(description)

    brand_manual = _brand_manual_section(skill_md, readme_md)
    if brand_manual:
        parts.append(brand_manual)

    # Scope firewall — ALWAYS present, reading as a coda to the manual (or in
    # its slot when no manual was retained): everything above and below is style
    # authority, never content. See the constant's comment for provenance.
    parts.append(DESIGN_SYSTEM_SCOPE_FIREWALL)

    grouped = _grouped_tokens(design_system)

    # Groups with no canonical emitter are EMITTED under the generic heading (see
    # ``_additional_token_sections``), never dropped. The log line is now
    # informational — it records which groups took the generic path so an author
    # can add an alias if the name is a common synonym — and is deliberately INFO,
    # not WARNING: nothing is lost, so there is nothing to warn about.
    uncanonical = sorted(group for group in grouped if group not in _CANONICAL_GROUPS)
    if uncanonical:
        logger.info(
            "Design system '%s' has token group(s) %s with no canonical emitter; "
            "those tokens are emitted verbatim under 'ADDITIONAL BRAND TOKENS'. "
            "Canonical groups: %s.",
            name,
            ", ".join(uncanonical),
            ", ".join(sorted(_CANONICAL_GROUPS)),
        )

    # Tokens: color, type, spacing, shadow — all uncapped. FONT-SIZE tokens are
    # EXCLUDED from the type/spacing rule lists: BRAND FONT-SIZE TOKENS is their
    # authoritative home, and listing a size a second time under a heading naming
    # another role (Claude Design mislabels the ramp as "spacing") is the competing
    # role cue that produced under-sized titles.
    #
    # Ownership comes from the token itself, NOT from the px-keyed band-math ramp:
    # any font-size value form, any count, all duplicates. Reading it off that map
    # is what left non-px sizes and same-px siblings labeled as spacing.
    font_size_pairs = _font_size_token_pairs(grouped)
    parts.extend(_color_sections(grouped))

    # Text contrast — ALWAYS present, immediately after the colors it reasons about
    # so the model reads the pairing rules next to the palette they apply to. The
    # block emits PARSED colors only (never a token name), so it carries no
    # user-controlled text; it is therefore emitted outside the compiler-owned
    # type-scale region purely because it is a different contract, not because it
    # would be unsafe inside one.
    parts.append(_contrast_section(grouped))

    typography = _scale_section(
        grouped, "type", "TYPOGRAPHY TOKENS:", exclude=font_size_pairs
    )
    if typography:
        parts.append(typography)
    spacing = _scale_section(
        grouped, "spacing", "SPACING TOKENS:", exclude=font_size_pairs
    )
    if spacing:
        parts.append(spacing)
    parts.extend(_shadow_sections(grouped))

    # Tokens in groups with no canonical emitter — emitted in full, under a constant
    # heading, with the brand's own group label carried as quoted DATA on its own
    # line rather than dropped (the zero-token-loss rule, now covering the label as
    # well as the tokens). Placed after the canonical token sections and BEFORE the
    # type-scale region, so the artifact's token block stays contiguous AND no label
    # can reach the compiler-owned numeric contract. The font-size exclusion is
    # passed through for the same reason the type/spacing lists get it.
    authored_labels = _authored_group_labels(design_system)
    parts.extend(
        _additional_token_sections(
            grouped,
            exclude=font_size_pairs,
            authored_labels=authored_labels,
        )
    )

    # The ramp's own token NAMES, under a heading that names their real role.
    # They are excluded from the type/spacing lists above (v7) and are no longer
    # echoed inside the numeric region below, so this is their home — which is
    # what makes "every token is listed" true without putting user text back
    # inside the compiler-owned contract.
    #
    # The authored labels come along so a token RE-HOMED out of an author-invented
    # group keeps that group's attribution. Without it, a group whose ONLY token is a
    # font size lost its label entirely: the generic section above correctly renders
    # nothing, and the brand's word for the group then appeared nowhere.
    font_size_tokens = _font_size_token_section(grouped, authored_labels=authored_labels)
    if font_size_tokens:
        parts.append(font_size_tokens)

    # Type-size role anchors — ALWAYS present (ramp-derived or neutral), so a
    # DS deck never generates in the size vacuum left by bypassing
    # DEFAULT_SLIDE_STYLE. Emitted right after the token sections it reads.
    #
    # Wrapped in its region SENTINELS: the late re-assertion recovers exactly
    # what lies between them, so nothing outside can extend or truncate the
    # contract. Every user value reaching the artifact has been through ``_safe``
    # / ``_safe_multiline``, which strip the C0 controls the sentinels are built
    # from — so no uploaded text can forge a delimiter. This replaces the v8
    # position-based marker scrub, which had to EXEMPT this section (it owns the
    # marker) and so could not protect the token names interpolated inside it.
    parts.append(_delimit_region(_type_scale_section(grouped)))

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

    # The currency sentinel leads the artifact. Prepended here — outside the
    # ``\n\n``-joined body — so it occupies the first bytes of the string, a
    # position no user text can reach: every interpolated user value goes through
    # ``_safe``/``_safe_multiline``, which strip the control character it is built
    # from. This, and not the header line, is what
    # ``compiled_style_content_is_current`` reads. Stripped before the text is
    # injected (``strip_type_scale_region_markers``), so the model never sees it.
    return _CURRENCY_SENTINEL + "\n\n".join(parts)


def extract_type_scale_block(compiled: Optional[str]) -> Optional[str]:
    """Recover the compiler's BRAND TYPE SCALE section from a compiled artifact.

    The prompt-assembly seam re-asserts the scale's numbers LAST
    (:func:`build_type_scale_reassertion`) and reads them back out of the text it
    is about to inject — which may be a PERSISTED artifact rather than a fresh
    compile — so the re-assertion can never drift from what the model was shown.

    Delimited by :data:`_REGION_BEGIN` / :data:`_REGION_END` and read as exactly
    what lies BETWEEN them. Both earlier designs scanned for a single anchor and
    guessed the region's extent from surrounding text — first the bare heading
    phrase, then the reserved marker plus "up to the next blank line" — and both
    were defeated, the second by a token name that injected its own marker AND a
    blank line inside the very section the marker scrub had to exempt. A start/end
    pair removes the guess: a stray occurrence of any user-visible string can
    neither extend the region nor cut it short.

    The sentinels are C0 control sequences, and every user value is put through
    ``_safe``/``_safe_multiline``, which strip that whole category — so uploaded
    text cannot forge a delimiter. The FIRST begin and the FIRST end after it win,
    which keeps behaviour defined even for a hand-edited artifact.

    Returns ``None`` when the text carries no delimited region — a legacy
    hand-pasted style blob, or a pre-v9 artifact — in which case no re-assertion
    is appended. Stale persisted rows are recompiled before they reach here
    (``ensure_compiled_style_content_current``), so they regain the block.
    """
    if not compiled:
        return None
    begin = compiled.find(_REGION_BEGIN)
    if begin < 0:
        return None
    body_at = begin + len(_REGION_BEGIN)
    end = compiled.find(_REGION_END, body_at)
    if end < 0:
        # An artifact carrying a begin but no end is malformed (hand-edited or
        # truncated in storage): treat it as having no recoverable contract
        # rather than reading to the end of the text, which would swallow every
        # later section.
        logger.warning("Compiled artifact has an unterminated type-scale region")
        return None
    return compiled[body_at:end]


def strip_type_scale_region_markers(compiled: Optional[str]) -> str:
    """Remove the compiler's control sentinels, yielding MODEL-FACING text.

    Two kinds, both structural bookkeeping that must never reach the model:

    * the type-scale region delimiters, read by :func:`extract_type_scale_block`;
    * the leading :data:`_CURRENCY_SENTINEL`, read by
      :func:`compiled_style_content_is_current`. Stripped at ANY version
      (:data:`_CURRENCY_SENTINEL_RE`) so an artifact persisted by an older compiler
      is cleaned too, rather than leaking a stray control sequence into a prompt if
      it reaches this seam before being recompiled.

    The prompt-assembly seam (``agent_factory._get_prompt_content``) extracts the
    type-scale block and then calls this, so the persisted artifact keeps its
    sentinels — that is what makes the currency check work on a stored row — while
    the injected prompt does not.

    Leading blank space left where the currency sentinel was removed is trimmed, so
    the model-facing text still OPENS with the ``SLIDE VISUAL STYLE:`` header
    exactly as before this sentinel existed.
    """
    if not compiled:
        return ""
    text = _CURRENCY_SENTINEL_RE.sub("", compiled)
    return text.replace(_REGION_BEGIN, "").replace(_REGION_END, "").lstrip("\n")


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

    Currency is proven by :data:`_CURRENCY_SENTINEL` — a version-stamped
    UNIT-SEPARATOR sentinel the compiler emits at the FRONT of every artifact — and
    NOT by inspecting the header line.

    FIVE successive rules read that header line, and every one was defeated,
    because the line puts compiler text and user text side by side: the
    design-system NAME is interpolated into it by construction.

      1. ``marker in artifact``      — any README mentioning the string passed.
      2. ``marker in header line``   — a system NAMED like the marker passed.
      3. ``header.endswith(marker)`` — a system named EXACTLY the marker passed.
      4. ``prefix + non-empty name + endswith(marker)`` — a system named
         ``Evil Brand [ds-compiler vN]`` satisfied every clause at once.
      5. ``prefix + non-empty name + exactly one marker`` — defeated by a
         PRE-VERSION artifact (no marker at all, which the lazy backfill explicitly
         supports) whose NAME merely STARTS with ``[ds-compiler vN]``: that
         reproduces the current prefix byte-for-byte, leaves a name segment, and
         contains exactly one marker. A stale body read as current and NEVER
         recompiled.

    Rules 1-5 each tightened WHAT was compared while leaving WHERE it was compared
    user-influenced; rule 5 shows there is no end to that sequence. The fix is to
    ask the question somewhere a user string cannot reach.

    The sentinel is built from U+001F, category ``Cc``, which ``_safe`` and
    ``_safe_multiline`` strip from EVERY interpolated user value — name,
    description, token names/values, template names, filenames, README/SKILL prose.
    So no uploaded text can contain one, let alone place one at offset zero. This is
    the same construction argument that already makes the type-scale region
    delimiters sound, reused for the version claim; it is a property of the
    character class, not of the string being unlikely.

    A PRE-VERSION artifact carries no sentinel and therefore always reads STALE,
    which is the correct answer — it must be recompiled to regain the current
    compiler's blocks. A README legitimately discussing ``[ds-compiler vN]`` keeps
    its prose and confers nothing.

    Trailing whitespace is tolerated implicitly (the sentinel leads, so anything
    appended by a storage round-trip is irrelevant). The design-system name buys
    nothing in EITHER direction: a system named exactly like the marker still reads
    current from its own compile, and reads stale when its body is stale.
    """
    if not compiled:
        return False
    # Exact version, at the FRONT. Not ``in``: a sentinel's position is part of what
    # makes it unforgeable, and ``in`` would also accept one embedded in a body.
    return compiled.startswith(_CURRENCY_SENTINEL)


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
