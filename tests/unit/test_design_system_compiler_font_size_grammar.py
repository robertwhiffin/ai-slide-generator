"""The font-size VALUE grammar, audited once against the CSS font-size spec.

Hard rule B — a font size must NEVER be labelled spacing — has now reopened four
times, each time because the grammar recognised a slightly narrower set of values
than CSS actually permits for ``font-size``. Every miss costs the same thing: a
token the brand declared as a TYPE size is suppressed from the font-size heading
and printed under ``SPACING TOKENS:``, telling the model a cover size is a gap.

Round 9's find was the CSS-WIDE KEYWORDS. ``font-size: inherit`` is the single most
ordinary way a design system says "same size as the parent", and ``initial`` /
``unset`` / ``revert`` / ``revert-layer`` are valid on every CSS property that
exists. All five were rejected, so ``fs-inherit: inherit`` printed as spacing.

Rather than add the five keywords and wait for a sixth surface, this module pins
the WHOLE grammar against the spec, in both directions:

* ACCEPTED — the CSS-wide keywords; the absolute-size keywords (``xx-small`` ..
  ``xxx-large``); the relative keywords (``larger``, ``smaller``); ``<length>`` in
  every unit CSS defines; ``<percentage>``; the math functions (``calc``,
  ``clamp``, ``min``, ``max``); ``var()``; and unit-less ``0``.
* REJECTED — the properties that merely START with a type-ish word
  (``text-indent``, ``text-decoration-thickness``, ``text-gap``, ``text-align``)
  and the spacing properties that carry real lengths (``letter-spacing``,
  ``word-spacing``). Claiming one of these EVICTS a genuine spacing token from
  ``SPACING TOKENS:``, so the false-positive direction is a defect too.

The assertions are ARTIFACT-LEVEL: they compile a real design system and read the
emitted headings. A predicate-only test passes while the artifact still mislabels
the token, which is how a threshold defect escaped a previous sweep — ownership was
gated on the ramp reaching three distinct sizes, so a bundle with one or two font
sizes mislabelled them no matter what the predicate said. Every case therefore runs
at ramp lengths 0, 1, 2, 3 and many, spanning that ``_MIN_RAMP_SIZES`` boundary.

All fixtures SYNTHETIC (invented "Acme" brand, dummy values).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from src.services.design_system_compiler import compile_design_system
from tests.unit.test_design_system_compiler import _make_ds

#: The heading a font-size token MUST appear under.
_FONT_SIZE_HEADING = "BRAND FONT-SIZE TOKENS"

#: The heading a font-size token must NEVER appear under (hard rule B).
_SPACING_HEADING = "SPACING TOKENS:"

#: Extra px sizes used to pad the ramp to a given length. Deliberately distinct
#: values, since the px ramp keys on DISTINCT sizes.
_PAD_SIZES = ("12px", "24px", "36px", "48px", "64px", "80px")

#: Ramp lengths spanning the ``_MIN_RAMP_SIZES`` (3) threshold in both directions.
#: 0/1/2 are BELOW it (neutral bands apply), 3 is exactly AT it, 6 is well above.
_RAMP_LENGTHS = (0, 1, 2, 3, 6)

# Every value form CSS permits for ``font-size``, grouped by the spec clause it
# comes from. ``id`` strings keep the parametrised test names readable.
_CSS_WIDE_KEYWORDS = ("inherit", "initial", "unset", "revert", "revert-layer")

_ABSOLUTE_SIZE_KEYWORDS = (
    "xx-small",
    "x-small",
    "small",
    "medium",
    "large",
    "x-large",
    "xx-large",
    "xxx-large",
)

_RELATIVE_SIZE_KEYWORDS = ("larger", "smaller")

#: ``<length>`` in every unit named in the CSS spec, at a plausible size.
_LENGTH_VALUES = (
    "16px",
    "1em",
    "1rem",
    "2ex",
    "2ch",
    "2cap",
    "2ic",
    "1lh",
    "1rlh",
    "2vw",
    "2vh",
    "2vmin",
    "2vmax",
    "2vi",
    "2vb",
    "4q",
    "1cm",
    "10mm",
    "1in",
    "12pt",
    "1pc",
)

_PERCENTAGE_VALUES = ("125%", "100%", "62.5%")

_MATH_VALUES = (
    "calc(1rem + 2px)",
    "clamp(1rem, 2.5vw, 3rem)",
    "min(2rem, 5vw)",
    "max(1rem, 2vh)",
)

_VAR_VALUES = ("var(--brand-body)", "var(--fs-hero, 64px)")

#: The one length that is legal with NO unit at all.
_UNITLESS_ZERO_VALUES = ("0", "0.0")

_ACCEPTED_VALUES = (
    [pytest.param(v, id=f"css-wide-{v}") for v in _CSS_WIDE_KEYWORDS]
    + [pytest.param(v, id=f"absolute-{v}") for v in _ABSOLUTE_SIZE_KEYWORDS]
    + [pytest.param(v, id=f"relative-{v}") for v in _RELATIVE_SIZE_KEYWORDS]
    + [pytest.param(v, id=f"length-{v}") for v in _LENGTH_VALUES]
    + [pytest.param(v, id=f"percentage-{v}") for v in _PERCENTAGE_VALUES]
    + [pytest.param(v, id=f"math-{v.split('(')[0]}") for v in _MATH_VALUES]
    + [pytest.param(v, id="var") for v in _VAR_VALUES[:1]]
    + [pytest.param(_VAR_VALUES[1], id="var-with-fallback")]
    + [pytest.param(v, id=f"unitless-zero-{v}") for v in _UNITLESS_ZERO_VALUES]
)

#: Tokens whose NAME is a CSS property that is not a font size. Each carries a
#: real length, so only the name distinguishes it from a size — and each must keep
#: its place in ``SPACING TOKENS:``.
_NON_FONT_SIZE_TOKENS = (
    pytest.param("text-indent", "2em", id="text-indent"),
    pytest.param("text-decoration-thickness", "2px", id="text-decoration-thickness"),
    pytest.param("text-gap", "8px", id="text-gap"),
    pytest.param("text-align", "center", id="text-align"),
    pytest.param("letter-spacing", "0.05em", id="letter-spacing"),
    pytest.param("word-spacing", "0.2rem", id="word-spacing"),
)


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


def _ramp_tokens(length):
    """*length* distinct px font-size tokens, in the "spacing" group.

    The group is "spacing" on purpose: Claude Design manifests declare the type
    ramp as kind "spacing", which is the whole reason ownership is decided by
    name+value rather than by group membership.
    """
    return [
        {"group": "spacing", "name": f"fs-{px.removesuffix('px')}", "value": px}
        for px in _PAD_SIZES[:length]
    ]


def _section_of(compiled, heading):
    """The lines under *heading*, up to the next blank-line-separated block."""
    if heading not in compiled:
        return ""
    after = compiled.split(heading, 1)[1]
    return after.split("\n\n", 1)[0]


@pytest.mark.parametrize("ramp_length", _RAMP_LENGTHS)
@pytest.mark.parametrize("value", _ACCEPTED_VALUES)
def test_font_size_value_is_never_labelled_spacing(session, value, ramp_length):
    """A font-size token lands under the FONT-SIZE heading, never under spacing.

    Runs at every ramp length so a threshold on the ramp's size cannot make the
    label depend on how many OTHER sizes the bundle happens to ship.
    """
    ds = _make_ds(
        session,
        tokens=[
            {"group": "spacing", "name": "fs-probe", "value": value},
            *_ramp_tokens(ramp_length),
        ],
    )

    compiled = compile_design_system(ds)

    assert f"- fs-probe: {value}" in _section_of(compiled, _FONT_SIZE_HEADING), (
        f"font size {value!r} is missing from {_FONT_SIZE_HEADING}"
    )
    assert "fs-probe" not in _section_of(compiled, _SPACING_HEADING), (
        f"font size {value!r} was labelled SPACING — hard rule B violation"
    )


@pytest.mark.parametrize("ramp_length", _RAMP_LENGTHS)
@pytest.mark.parametrize(("name", "value"), _NON_FONT_SIZE_TOKENS)
def test_non_font_size_property_keeps_its_spacing_listing(
    session, name, value, ramp_length
):
    """A non-size property is NOT claimed as a font size.

    The other direction of the same rule: ownership SUPPRESSES a token from
    ``SPACING TOKENS:``, so a false positive silently evicts a real spacing token
    from the list the model reads for gaps.
    """
    ds = _make_ds(
        session,
        tokens=[
            {"group": "spacing", "name": name, "value": value},
            *_ramp_tokens(ramp_length),
        ],
    )

    compiled = compile_design_system(ds)

    assert f"- {name}: {value}" in _section_of(compiled, _SPACING_HEADING), (
        f"{name!r} was evicted from {_SPACING_HEADING}"
    )
    assert name not in _section_of(compiled, _FONT_SIZE_HEADING), (
        f"{name!r} was claimed as a font size"
    )
