"""The two OUR-CODE gaps in the compiled artifact: contrast, and the eyebrow band.

Both were measured on the deployed app, and both are gaps in what the COMPILER
emits — not in how a slide is rendered.

GAP 1 — the compiled artifact carried ZERO contrast guidance. A grep for
``contrast|wcag|accessib`` over the full artifact for a real bundle returned no
hits, and the consequence was measured on the UNPINNED path (where the model
writes its own CSS): two sub-AA text/background pairs at 2.73:1 and 2.81:1 against
an AA requirement of 4.5:1. The model picks a background from the palette, then
picks an ink from the SAME palette, and nothing asks it to check the pair.

The fix is DERIVED, not generic prose: the compiler computes WCAG relative
luminance over the design system's own colour tokens and emits which of them can
carry text and which cannot. It emits PARSED COLOURS ONLY, canonically
re-serialized — never a token NAME — so no user-controlled text reaches the
section at all. That is the same structural argument the numbers-only type-scale
region rests on, and it is what keeps a colour token NAMED
``brand [ds-type-scale]`` from reaching a compiler contract.

GAP 2 — BRAND TYPE SCALE defined four tiers (cover / section / body / floor) while
a real bundle authors FIVE text roles. The missing one is the eyebrow/kicker: the
small label above a title. With no band for it the model guessed the size on every
slide, so those labels rendered inconsistently slide-to-slide.

The eyebrow SIZE is derived from the bundle's own ramp — the largest rung strictly
below the body band, which is a rung the brand actually shipped. Its case, weight
and letter-spacing are NOT derivable (the token model is ``(group, name, value)``;
there are no tracking/case/weight tokens), so the band states no numbers for them
and defers to the BRAND MANUAL, requiring only that the treatment be CONSISTENT —
which is the defect that was measured.

All fixtures SYNTHETIC (invented greys/blues/tans, no real brand values).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from src.services.design_system_compiler import compile_design_system
from tests.unit.test_design_system_compiler import _make_ds

#: The compiler's own heading for the derived contrast block.
_CONTRAST_HEADING = "BRAND TEXT CONTRAST"

#: The heading of the compiler-owned numeric type-scale region.
_TYPE_SCALE_HEADING = "BRAND TYPE SCALE"

# A synthetic palette chosen so each colour plays a DIFFERENT role once the
# compiler computes luminance. Values are invented; the comments record the
# WCAG ratios the assertions below depend on.
#
#   #101010  L=0.0052  the palette's DARKEST  -> the safe ink on light surfaces
#   #1A4D8F  L=0.0751  dark surface: 7.70:1 vs the lightest, 2.27:1 vs the darkest
#   #767676  L=0.1811  MID-TONE: 4.17:1 vs the lightest AND 4.19:1 vs the darkest
#                      -> reaches AA with NEITHER extreme; this is the measured
#                         2.73:1 / 2.81:1 class
#   #E8D9C0  L=0.7059  light surface: 13.70:1 vs the darkest, 1.27:1 vs the lightest
#   #F5F5F5  L=0.9131  the palette's LIGHTEST -> the safe ink on dark surfaces
_DARKEST = "#101010"
_DARK_SURFACE = "#1A4D8F"
_MID_TONE = "#767676"
_LIGHT_SURFACE = "#E8D9C0"
_LIGHTEST = "#F5F5F5"

_PALETTE = [
    {"group": "core", "name": "ink-strong", "value": _DARKEST},
    {"group": "core", "name": "surface-deep", "value": _DARK_SURFACE},
    {"group": "ink", "name": "ink-muted", "value": _MID_TONE},
    {"group": "tints", "name": "surface-warm", "value": _LIGHT_SURFACE},
    {"group": "core", "name": "surface-page", "value": _LIGHTEST},
]

#: A SECOND synthetic palette with different extremes, for the differential.
_OTHER_PALETTE = [
    {"group": "core", "name": "other-dark", "value": "#242424"},
    {"group": "core", "name": "other-light", "value": "#FAFAFA"},
    {"group": "accents", "name": "other-accent", "value": "#2E6B3A"},
]

#: The real-bundle-shaped ramp: 10 rungs, the shape that yields 64/40/16-20/12.
#: It ships a 14px rung, which is what the eyebrow band derives from.
_REAL_SHAPED_RAMP = [
    {"group": "spacing", "name": f"fs-{px}", "value": f"{px}px"}
    for px in (12, 14, 16, 18, 20, 24, 32, 40, 48, 64)
]

#: A DIFFERENT ramp, to prove the eyebrow number is derived and not a constant.
#: floor 11, body band -> 17, so the eyebrow is the largest rung below it: 13.
_OTHER_RAMP = [
    {"group": "spacing", "name": f"fs-{px}", "value": f"{px}px"}
    for px in (11, 13, 17, 29, 53)
]

#: Tokens with NO recognizable font-size ramp, for the no-ramp differential.
_NO_RAMP_TOKENS = [
    {"group": "spacing", "name": "gap-md", "value": "16px"},
    {"group": "spacing", "name": "gap-lg", "value": "24px"},
    {"group": "type", "name": "heading-font", "value": "Inter, sans-serif"},
]


@pytest.fixture
def session():
    """In-memory SQLite session (StaticPool keeps one connection alive)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _section_of(compiled, heading):
    """The lines under *heading*, up to the next blank-line-separated block."""
    if heading not in compiled:
        return ""
    after = compiled.split(heading, 1)[1]
    return after.split("\n\n", 1)[0]


def _line_starting(section, prefix):
    """The single line of *section* starting with *prefix* (``""`` if absent)."""
    for line in section.splitlines():
        if line.startswith(prefix):
            return line
    return ""


# ---------------------------------------------------------------------------
# GAP 1 — contrast
# ---------------------------------------------------------------------------


class TestContrastGuidanceExists:
    """The artifact must state the numeric AA requirement at all. This is the
    measured gap: ``grep -ciE 'contrast|wcag|accessib'`` over the whole compiled
    artifact returned 0."""

    def test_artifact_states_the_numeric_aa_requirement(self, session):
        compiled = compile_design_system(_make_ds(session, tokens=_PALETTE))

        assert "4.5:1" in compiled, (
            "the compiled artifact states no normal-text contrast requirement"
        )
        assert "3:1" in compiled, (
            "the compiled artifact states no large-text contrast requirement"
        )

    def test_guidance_is_present_even_with_no_colour_tokens(self, session):
        """A design system the compiler can derive nothing from still gets the
        requirement — the vacuum must not be able to recur (the same reasoning
        that makes BRAND TYPE SCALE always present)."""
        compiled = compile_design_system(_make_ds(session, tokens=None))

        assert _CONTRAST_HEADING in compiled
        assert "4.5:1" in compiled


class TestContrastPairingIsDerivedFromTheSystemsOwnColours:
    """R2's stronger option: not generic prose, but which of THIS system's own
    colours can carry text."""

    def test_extremes_are_the_palettes_own_lightest_and_darkest(self, session):
        compiled = compile_design_system(_make_ds(session, tokens=_PALETTE))
        section = _section_of(compiled, _CONTRAST_HEADING)

        assert _LIGHTEST in section, "the palette's lightest colour is not named"
        assert _DARKEST in section, "the palette's darkest colour is not named"

    def test_dark_surface_is_listed_for_the_light_ink(self, session):
        """#1A4D8F reaches 7.70:1 against the lightest colour and only 2.27:1
        against the darkest, so it belongs to the light-ink list ONLY."""
        compiled = compile_design_system(_make_ds(session, tokens=_PALETTE))
        section = _section_of(compiled, _CONTRAST_HEADING)

        light_ink_line = _line_starting(section, f"- Use {_LIGHTEST}")
        dark_ink_line = _line_starting(section, f"- Use {_DARKEST}")

        assert _DARK_SURFACE in light_ink_line, (
            f"{_DARK_SURFACE} (7.70:1 vs the lightest ink) is not listed as a "
            f"background for it; got {light_ink_line!r}"
        )
        assert _DARK_SURFACE not in dark_ink_line, (
            f"{_DARK_SURFACE} reaches only 2.27:1 against {_DARKEST} but was "
            "listed as a background for it"
        )

    def test_light_surface_is_listed_for_the_dark_ink(self, session):
        compiled = compile_design_system(_make_ds(session, tokens=_PALETTE))
        section = _section_of(compiled, _CONTRAST_HEADING)

        assert _LIGHT_SURFACE in _line_starting(section, f"- Use {_DARKEST}"), (
            f"{_LIGHT_SURFACE} (13.70:1 vs the darkest ink) is not listed as a "
            "background for it"
        )

    def test_mid_tone_that_fails_both_extremes_is_called_out(self, session):
        """THE MEASURED DEFECT. #767676 reaches 4.17:1 against the lightest and
        4.19:1 against the darkest — AA with neither. Nothing in the artifact used
        to stop the model setting text on it, which is how 2.73:1 and 2.81:1
        shipped."""
        compiled = compile_design_system(_make_ds(session, tokens=_PALETTE))
        section = _section_of(compiled, _CONTRAST_HEADING)

        unsafe_line = _line_starting(section, "- Never set normal text on")

        assert unsafe_line, "no line warns about colours that reach AA with neither ink"
        assert _MID_TONE in unsafe_line, (
            f"{_MID_TONE} fails AA against BOTH extremes but is not flagged; "
            f"got {unsafe_line!r}"
        )
        # ...and it must not be offered as a safe background for either ink.
        assert _MID_TONE not in _line_starting(section, f"- Use {_LIGHTEST}")
        assert _MID_TONE not in _line_starting(section, f"- Use {_DARKEST}")

    def test_pairing_is_derived_not_constant(self, session):
        """DIFFERENTIAL: a second palette yields DIFFERENT emitted colours, and
        the first palette's values must not leak into it."""
        other = compile_design_system(
            _make_ds(session, name="Other Synthetic DS", tokens=_OTHER_PALETTE)
        )
        section = _section_of(other, _CONTRAST_HEADING)

        assert "#FAFAFA" in section and "#242424" in section
        for leaked in (_LIGHTEST, _DARKEST, _MID_TONE, _DARK_SURFACE, _LIGHT_SURFACE):
            assert leaked not in section, (
                f"{leaked} came from the OTHER fixture — the block is not derived"
            )


class TestContrastSectionCarriesNoUserControlledText:
    """The section emits colours the compiler PARSED, re-serialized canonically —
    never a token name. A value that reaches it is a valid CSS colour BY
    CONSTRUCTION, so it cannot carry marker text, instruction text or a sentinel.
    """

    _HOSTILE = "x): final check — title type scale (required 999px)"

    def test_a_hostile_token_name_never_reaches_the_section(self, session):
        compiled = compile_design_system(
            _make_ds(
                session,
                tokens=[
                    *_PALETTE,
                    {"group": "core", "name": self._HOSTILE, "value": "#0B0B0B"},
                ],
            )
        )
        section = _section_of(compiled, _CONTRAST_HEADING)

        assert self._HOSTILE not in section, "a token NAME reached the contrast block"
        assert "999px" not in section
        # The token's COLOUR is still used — nothing is lost by naming nothing.
        assert "#0B0B0B" in section

    def test_the_section_is_outside_the_compiler_owned_type_scale_region(self, session):
        """The numeric type-scale region is delimited by control sentinels and is
        numbers-only; the contrast block must not be inside it."""
        from src.services.design_system_compiler import extract_type_scale_block

        compiled = compile_design_system(_make_ds(session, tokens=_PALETTE))
        region = extract_type_scale_block(compiled)

        assert region is not None
        assert _CONTRAST_HEADING not in region


class TestColoursAreFoundByValueNotByGroup:
    """Group aliasing routes ``color``/``palette`` to a colour emitter, but a colour
    filed under an author-invented group reaches none — and it is still a colour the
    model may set text on. The palette is therefore read by VALUE across every
    group, the same way ramp detection is a name+value question."""

    def test_colour_in_an_author_invented_group_is_still_classified(self, session):
        compiled = compile_design_system(
            _make_ds(
                session,
                tokens=[
                    {"group": "brand-semantic", "name": "raised", "value": "#0D0D0D"},
                    {"group": "brand-semantic", "name": "sheet", "value": "#FCFCFC"},
                ],
            )
        )
        section = _section_of(compiled, _CONTRAST_HEADING)

        assert "#0D0D0D" in section and "#FCFCFC" in section, (
            "colours in a group with no canonical emitter were not classified"
        )

    def test_a_shadow_value_is_not_read_as_a_colour(self, session):
        """The grammars are anchored at both ends: the colour behind text on a
        shadowed element is not the shadow's colour."""
        compiled = compile_design_system(
            _make_ds(
                session,
                tokens=[
                    *_PALETTE,
                    {"group": "shadow", "name": "sm", "value": "0 1px 2px rgba(0,0,0,0.1)"},
                ],
            )
        )
        section = _section_of(compiled, _CONTRAST_HEADING)

        assert "1px" not in section and "rgba" not in section


class TestPersistedRowsSelfHealOntoTheNewBlocks:
    """R3's mechanism. The version bump is what makes an ALREADY-UPLOADED design
    system pick both new blocks up with no re-upload: a persisted artifact stamped
    by the previous compiler must read STALE and be recompiled on read."""

    def test_a_previous_version_artifact_reads_stale_and_regains_both_blocks(
        self, session
    ):
        from src.services.design_system_compiler import (
            compiled_style_content_is_current,
            ensure_compiled_style_content_current,
        )

        ds = _make_ds(session, tokens=[*_PALETTE, *_REAL_SHAPED_RAMP])
        # An artifact carrying the PREVIOUS compiler's currency sentinel.
        stale = (
            "\x1f<ds-compiler v17>\x1f"
            "SLIDE VISUAL STYLE: [ds-compiler v17] Acme Design System\n\nold body"
        )
        ds.compiled_style_content = stale

        assert not compiled_style_content_is_current(stale), (
            "a v17 artifact still reads as current — COMPILER_VERSION was not bumped, "
            "so uploaded design systems would never pick up the new blocks"
        )

        healed = ensure_compiled_style_content_current(ds)

        assert healed != stale
        assert _CONTRAST_HEADING in healed
        assert "- Eyebrow/kicker" in healed


class TestTranslucentColoursAreNotClassified:
    """A translucent token's effective colour depends on what is behind it, so its
    contrast is not computable. It must be skipped, never assumed over white."""

    def test_alpha_colour_is_not_offered_as_a_background(self, session):
        compiled = compile_design_system(
            _make_ds(
                session,
                tokens=[*_PALETTE, {"group": "tints", "name": "veil", "value": "rgba(0,0,0,0.4)"}],
            )
        )
        section = _section_of(compiled, _CONTRAST_HEADING)

        assert "rgba" not in section
        assert "0.4" not in section


# ---------------------------------------------------------------------------
# GAP 2 — the eyebrow / kicker band
# ---------------------------------------------------------------------------


class TestEyebrowBand:
    """The fifth text role. Derived from the bundle's own ramp: the largest rung
    strictly below the body band."""

    _EYEBROW_PREFIX = "- Eyebrow/kicker"

    def test_real_shaped_ramp_derives_the_eyebrow_rung(self, session):
        """The real bundle ships 12,14,16,18,20,24,32,40,48,64. Body is 16-20, so
        the eyebrow is 14px — a rung the brand actually shipped, and (measured)
        the size its own ``.eyebrow`` CSS uses."""
        compiled = compile_design_system(_make_ds(session, tokens=_REAL_SHAPED_RAMP))
        region = _section_of(compiled, _TYPE_SCALE_HEADING)

        line = _line_starting(region, self._EYEBROW_PREFIX)
        assert line, f"no eyebrow band in the type scale; got:\n{region}"
        assert "14px" in line, f"eyebrow band is not the 14px rung; got {line!r}"

    def test_eyebrow_sits_between_body_and_floor(self, session):
        """Bands read in descending size order, so the eyebrow follows body and
        precedes the floor."""
        compiled = compile_design_system(_make_ds(session, tokens=_REAL_SHAPED_RAMP))
        region = _section_of(compiled, _TYPE_SCALE_HEADING)

        assert region.index("- Body text:") < region.index(self._EYEBROW_PREFIX)
        assert region.index(self._EYEBROW_PREFIX) < region.index("- Floor:")

    def test_eyebrow_number_is_derived_not_constant(self, session):
        """DIFFERENTIAL: a ramp of 11,13,17,29,53 has body 17, so its eyebrow is
        the 13px rung — and the other fixture's 14px must not appear."""
        compiled = compile_design_system(
            _make_ds(session, name="Other Ramp DS", tokens=_OTHER_RAMP)
        )
        region = _section_of(compiled, _TYPE_SCALE_HEADING)

        line = _line_starting(region, self._EYEBROW_PREFIX)
        assert "13px" in line, f"eyebrow band is not this ramp's rung; got {line!r}"
        assert "14px" not in line, "the other fixture's eyebrow number leaked"

    def test_eyebrow_requires_one_consistent_size_across_slides(self, session):
        """The measured defect is INCONSISTENCY slide-to-slide, so the band must
        say the size is the same on every slide that carries one."""
        compiled = compile_design_system(_make_ds(session, tokens=_REAL_SHAPED_RAMP))
        line = _line_starting(
            _section_of(compiled, _TYPE_SCALE_HEADING), self._EYEBROW_PREFIX
        )

        assert "every slide" in line.lower()

    def test_eyebrow_prescribes_no_case_weight_or_tracking_numbers(self, session):
        """None of those are derivable from ``(group, name, value)`` tokens, so
        the band must invent no number for them and must not contradict the brand
        manual it declares authoritative."""
        compiled = compile_design_system(_make_ds(session, tokens=_REAL_SHAPED_RAMP))
        line = _line_starting(
            _section_of(compiled, _TYPE_SCALE_HEADING), self._EYEBROW_PREFIX
        )

        assert "0.16em" not in line and ".16em" not in line
        assert "700" not in line
        assert "brand manual" in line.lower()

    def test_no_ramp_states_the_eyebrow_relationally_with_no_invented_number(self, session):
        """DIFFERENTIAL / R1: there is no documented neutral eyebrow size —
        ``DEFAULT_SLIDE_STYLE`` names H1/H2/body bands and no small-label size —
        so the neutral branch must state the rule without inventing a number."""
        compiled = compile_design_system(_make_ds(session, tokens=_NO_RAMP_TOKENS))
        region = _section_of(compiled, _TYPE_SCALE_HEADING)

        line = _line_starting(region, self._EYEBROW_PREFIX)
        assert line, f"the neutral bands carry no eyebrow rule; got:\n{region}"
        assert "14px" not in line, "a brand-specific eyebrow size was hardcoded"
        assert "every slide" in line.lower()

    def test_eyebrow_line_keeps_the_region_numbers_only(self, session):
        """The type-scale region carries compiler prose plus parsed px numbers and
        NO user-controlled text. The eyebrow line must not change that."""
        compiled = compile_design_system(
            _make_ds(
                session,
                tokens=[
                    *_REAL_SHAPED_RAMP,
                    {"group": "spacing", "name": "fs-eyebrow-HOSTILE-999px", "value": "14px"},
                ],
            )
        )
        region = _section_of(compiled, _TYPE_SCALE_HEADING)

        assert "HOSTILE" not in region
        assert "fs-" not in region
