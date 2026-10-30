"""Prompt contract: builders and fixers build to the architect's deck style.

Plan Task 9 (architect deck style).  Spec:
docs/superpowers/specs/2026-10-29-architect-deck-style-design.md, section 3 ("What
builders and fixers do"), plus Rulings R18 and R19 and PLAN-CORRECTIONS C26.

The payload carries ``deck_style`` = ``{css, components: [{name, class_names, use,
example_html}]}`` and ``slide_spec.look``.  Both the builder and the fixer prompt gain a
``DECK STYLE (when deck_style is present)`` block.  These tests pin the RULES in that
block, not its wording:

* the text is whitespace-collapsed, lower-cased and stripped of backticks
  (``_plain``, as in test_builder_prompt.py);
* the block runs from its ``DECK STYLE`` heading line to the next upper-case heading
  paragraph (``HTML RULES:``, ``4. UNSUPPORTED OPERATIONS``, ...) that is not itself a
  deck-style sub-heading, or to the end of the prompt;
* the block is cut into clauses: sentences and bullet items.  A rule holds when every
  one of its needles matches inside one clause (or, where a rule says so, two
  neighbouring clauses), in any order.  So a rule has to be stated locally, but it may
  be reworded freely;
* one negative pin: nothing in the block permits inline paint (the no-design-system
  permission "because there is no deck CSS" stops applying once a deck style exists).

Guards that are green today and must stay green:

* the ``NON_EMPTY_RULES`` / ``EMPTY_RULES`` regex windows of test_builder_prompt.py
  are untouched (digest pin), and they still match with the deck-style block cut out,
  so today's rules live outside it ("Without a deck style, today's rules apply");
* the fixer's existing rules still hold with the block cut out;
* each prompt has exactly one paragraph that starts with ``INPUT`` (C26: the new block
  must not start with ``INPUT``) and keeps the no-``<style>`` rule.

``_SAFE_AREA_LITERALS`` (no ``88px`` / ``72px`` / ``56px`` / ``1280x720``) is already
pinned for every skill by test_skills.py; the promoted manifest must equal
``INSTRUCTIONS`` (test_builder_prompt.py, test_skill_prose.py).
"""

from __future__ import annotations

import hashlib
import re

import pytest

import src.core.database  # noqa: F401  (must be imported before other src.* modules)
from src.core.skills import load_skill
from tests.unit.test_builder_prompt import (
    EMPTY_CONDITION,
    EMPTY_RULES,
    NON_EMPTY_CONDITION,
    NON_EMPTY_RULES,
)

ROLES = ("builder", "fixer")


# ---------------------------------------------------------------------------
# Text helpers (pure: they take the prompt text, so they can be exercised on a
# candidate prompt without importing it)
# ---------------------------------------------------------------------------


def _plain(text: str) -> str:
    """Whitespace-collapsed, lower-cased text with markdown backticks removed."""
    return re.sub(r"\s+", " ", text.replace("`", "")).strip().lower()


#: The deck-style block's heading line: "DECK STYLE ...", optionally numbered ("5. ").
_HEADING_RE = re.compile(r"^[ \t]*(?:\d+\.[ \t]*)?DECK STYLE\b.*$", re.MULTILINE)

#: The start of any later upper-case heading paragraph, e.g. "HTML RULES:",
#: "CHART RULES (only when ...):", "4. UNSUPPORTED OPERATIONS — ...".
_NEXT_HEADING_RE = re.compile(
    r"\n[ \t]*\n[ \t]*((?:\d+\.[ \t]*)?[A-Z][A-Z0-9 ,/&'\-]{2,}(?:[ \t]*\([^)\n]*\))?[ \t]*[:—])"
)


def _deck_style_span(instructions: str) -> tuple[int, int] | None:
    """(start, end) of the DECK STYLE block, or None when the prompt has none."""
    headings = list(_HEADING_RE.finditer(instructions))
    if not headings:
        return None
    assert len(headings) == 1, (
        f"expected exactly one DECK STYLE heading, found {len(headings)}: "
        f"{[h.group(0) for h in headings]}"
    )
    start = headings[0].start()
    end = len(instructions)
    for m in _NEXT_HEADING_RE.finditer(instructions, headings[0].end()):
        # An upper-case sub-heading that is itself about the deck style
        # ("WITHOUT A DECK STYLE:") stays inside the block.
        if "DECK STYLE" not in m.group(1).upper():
            end = m.start()
            break
    return start, end


def _deck_style_block(instructions: str) -> str:
    span = _deck_style_span(instructions)
    assert span is not None, "prompt has no 'DECK STYLE (when deck_style is present)' block"
    return instructions[span[0] : span[1]]


def _without_deck_style_block(instructions: str) -> str:
    span = _deck_style_span(instructions)
    if span is None:
        return instructions
    return instructions[: span[0]] + instructions[span[1] :]


def _heading(instructions: str) -> str:
    return _plain(_deck_style_block(instructions).splitlines()[0])


def _clauses(plain_text: str) -> list[str]:
    """Sentences and bullet items of plain text.

    Splits after a full stop followed by whitespace, and at " - " / " • " bullet
    markers.  ``slide_spec.look``, ``dk-code`` and ``font-size`` survive (no
    whitespace around the dot or hyphen).
    """
    parts = re.split(r"(?<=\.)\s+|\s+[-•*]\s+", plain_text)
    return [p.strip() for p in parts if p.strip()]


def _windows(plain_text: str, width: int):
    clauses = _clauses(plain_text)
    for size in range(1, width + 1):
        for i in range(len(clauses) - size + 1):
            yield " ".join(clauses[i : i + size])


def _holds(plain_text: str, needles: tuple[str, ...], width: int) -> bool:
    """True when every needle matches inside one window of <= ``width`` clauses."""
    return any(all(re.search(n, w) for n in needles) for w in _windows(plain_text, width))


def _paragraphs_starting(instructions: str, prefix: str) -> list[str]:
    return [p for p in instructions.split("\n\n") if p.startswith(prefix)]


# ---------------------------------------------------------------------------
# Needles
# ---------------------------------------------------------------------------

NEG = r"(\bno\b|\bnever\b|\bnot\b|don't|do not|must not|avoid|forbidden)"
LOOK = r"(?<![\w-])look(?![\w-])"
DECK_STYLE = r"(deck_style|deck style)"
COLOUR = r"(?<!border )(?<!border-)colou?r"
BACKGROUND = r"background"
FONT_FAMILY = r"font[- ]famil"
FONT_SIZE = r"font[- ]size"
BORDER_COLOUR = r"border[- ]colou?r"
LAYOUT_PROPERTIES = (
    "display",
    "flex",
    "grid",
    "gap",
    "width",
    "height",
    "position",
    "margin",
    "padding",
    "align",
)

#: A rule is (id, needles, width): every needle must match inside one window of at
#: most ``width`` consecutive clauses.  Width 1 keeps a rule inside one sentence or
#: bullet; width 2 lets a condition ("For a bound section:") or a qualifier ("This
#: holds in every deck.") sit in the neighbouring clause.  Needles written with
#: ``[^.]`` gaps are themselves sentence-local.
Rule = tuple[str, tuple[str, ...], int]

COMMON_RULES: tuple[Rule, ...] = (
    (
        "use the catalogue's pieces exactly as their example_html shows",
        (
            r"example_html",
            r"(piece|component|catalogue|catalog)",
            r"(exactly|verbatim|as[^.]{0,30}\bshows?\b|as shown|same markup|unchanged)",
        ),
        1,
    ),
    (
        "inline styles are for layout only",
        (
            r"inline[^.]{0,40}\blayout\b[^.]{0,10}\bonly\b"
            r"|inline[^.]{0,60}\b(only|just|solely)\b[^.]{0,20}\blayout"
            r"|\blayout[- ]only\b[^.]{0,30}inline|inline[^.]{0,30}\blayout[- ]only\b",
        ),
        1,
    ),
    (
        "no inline colour, background, font family, font size or border colour",
        (NEG, r"inline", COLOUR, BACKGROUND, FONT_FAMILY, FONT_SIZE, BORDER_COLOUR),
        1,
    ),
    (
        "the inline ban holds in any deck (design system or not)",
        (
            NEG,
            r"inline",
            COLOUR,
            r"(\b(any|every|all|both|each)\b[^.]{0,40}\bdecks?\b|design_system_active is false"
            r"|whatever design_system_active|design_system_active (is )?(true or false|either way)"
            r"|with or without[^.]{0,30}design[ _]system|whether or not[^.]{0,40}design[ _]system"
            r"|even (when|without|if|in)[^.]{0,60}(design[ _]system|no deck css))",
        ),
        2,
    ),
    (
        "never use a dk- class the payload's deck_style does not define",
        (
            r"(\bnever\b|\bnot\b|don't|do not|\bno\b|\bonly\b|must be|must come)",
            r"(?<![\w-])dk-",
            r"\bclass",
            DECK_STYLE,
            r"(defin|declar|\blist|catalog)",
        ),
        1,
    ),
    (
        "token-span classes are used only inside their piece",
        (
            r"(token[- ]?spans?|span classes|token classes|sub-?classes|spans? (that|which) marks?)"
            r"[^.]{0,120}(inside|within|outside|only in)[^.]{0,40}(piece|component)",
        ),
        1,
    ),
    (
        "no class that the deck style, the bound section or the design system doesn't define",
        (
            r"(\bnever\b|\bnot\b|don't|do not|\bno\b|\bonly\b)",
            r"\bclass",
            DECK_STYLE,
            r"(bound section|section_html|section_css|template)",
            r"design[ _]system",
            r"(defin|declar|ship|provide|\blist)",
        ),
        1,
    ),
    (
        "without a deck style, today's rules apply",
        (
            r"(without (a |the )?deck[ _]style|no deck[ _]style"
            r"|deck_style is (absent|missing|empty|null|not (present|provided|supplied|set|given))"
            r"|(absent|missing|empty) deck_style"
            r"|when there is no deck[ _]style)"
            r"[^.]{0,120}(today'?s|existing|current|usual|unchanged|as before|still apply"
            r"|as written|rules (above|below)|other rules|apply as"
            r"|ignore (this|the) (block|section)|(this|the) block does not apply"
            r"|skip (this|the) block)",
        ),
        1,
    ),
)

#: The body is laid out as the look says (sentence-local, either word order).
BODY_AS_LOOK = (
    r"\bbody\b[^.]{0,40}\b(as|to|per|following)\b[^.]{0,30}"
    + LOOK
    + r"|(lay[^.]{0,15}\bout\b|arrange|compose|\bbuild\b)[^.]{0,40}\bbody\b[^.]{0,60}"
    + LOOK
    + r"|"
    + LOOK
    + r"[^.]{0,60}(lay[^.]{0,15}\bout\b|arrange|describ|says)[^.]{0,30}\bbody\b"
)

BUILDER_RULES: tuple[Rule, ...] = (
    (
        "build the slide to its look",
        (r"\bbuild\b[^.]{0,60}" + LOOK + r"|\b(follow|match)\b[^.]{0,25}" + LOOK,),
        1,
    ),
    (
        "a bound section keeps its frame: root tag and classes, ground, eyebrow, title, footer",
        (
            r"(bound|section_html)",
            r"(keep|retain|preserve)[^.]{0,40}\bframe\b|\bframe\b[^.]{0,40}(keep|retain|preserve)",
            r"\broot\b",
            r"\bclass",
            r"(ground|background)",
            r"eyebrow",
            r"\btitle",
            r"footer",
        ),
        2,
    ),
    (
        "a bound section's body is laid out as the look says",
        (r"(bound|section)", BODY_AS_LOOK),
        2,
    ),
    (
        "replace the bound section's body markup where the look needs it",
        (r"(bound|section)", r"replac[^.]{0,60}\bbody\b|\bbody\b[^.]{0,60}replac"),
        2,
    ),
)

FIXER_RULES: tuple[Rule, ...] = (
    (
        "fix toward the deck style",
        (
            r"(\bfix|correct|repair)[^.]{0,60}(toward|towards|to match|in line with|back to|conform"
            r"|closer to|consistent with)[^.]{0,40}" + DECK_STYLE,
        ),
        1,
    ),
    (
        "fix toward (or keep) the slide's look",
        (r"(\bfix|correct|keep|respect|follow|match|preserve|toward)[^.]{0,80}" + LOOK,),
        1,
    ),
)

ROLE_RULES = {"builder": COMMON_RULES + BUILDER_RULES, "fixer": COMMON_RULES + FIXER_RULES}

ROLE_RULE_CASES = [
    pytest.param(role, rid, needles, width, id=f"{role}: {rid}")
    for role, rules in ROLE_RULES.items()
    for rid, needles, width in rules
]


def _instructions(role: str) -> str:
    return load_skill(role).instructions


# ---------------------------------------------------------------------------
# The block exists, is titled, and names its inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
def test_prompt_has_one_deck_style_block_conditioned_on_deck_style(role):
    heading = _heading(_instructions(role))
    assert re.match(r"(\d+\.\s*)?deck style\b", heading), heading
    assert "deck_style" in heading, f"{role} DECK STYLE heading lacks deck_style: {heading!r}"
    assert re.search(
        r"(when|if|with)[^:]{0,40}(deck_style[^:]{0,30}(present|provided|supplied|non-empty"
        r"|not empty|given|set|carried)|(carries|has|includes|contains)[^:]{0,20}deck_style)",
        heading,
    ), f"{role} DECK STYLE heading does not say it applies when deck_style is present: {heading!r}"


@pytest.mark.parametrize("role", ROLES)
def test_deck_style_inputs_name_slide_spec_look(role):
    instructions = _instructions(role)
    block = _plain(_deck_style_block(instructions))
    inputs = " ".join(_plain(p) for p in _paragraphs_starting(instructions, "INPUT"))
    assert "deck_style" in block
    assert "slide_spec.look" in block or "slide_spec.look" in inputs, (
        f"{role} names neither slide_spec.look in the DECK STYLE block nor in INPUT"
    )


@pytest.mark.parametrize(("role", "rule", "needles", "width"), ROLE_RULE_CASES)
def test_deck_style_block_states_rule(role, rule, needles, width):
    block = _plain(_deck_style_block(_instructions(role)))
    assert _holds(block, needles, width), f"{role} DECK STYLE block lacks: {rule}"


@pytest.mark.parametrize("role", ROLES)
def test_layout_only_rule_names_layout_properties(role):
    """'Layout only' is concrete: at least three of the brief's layout properties."""
    block = _plain(_deck_style_block(_instructions(role)))
    best = max(
        (
            sum(1 for p in LAYOUT_PROPERTIES if re.search(rf"\b{p}", w))
            for w in _windows(block, 2)
            if re.search(r"inline", w) and re.search(r"layout", w)
        ),
        default=0,
    )
    assert best >= 3, (
        f"{role} layout-only rule names {best} of {LAYOUT_PROPERTIES}; expected at least 3"
    )


#: A permission for inline paint: "inline colour is permitted", "you may use inline
#: background".  Negated forms ("no inline colour", "is not allowed", "no longer
#: permitted") are excluded by the NEG check over the match plus 30 chars before it.
_INLINE_PAINT_PERMISSION = re.compile(
    r"inline[^.;]{0,40}(colou?r|background|font)[^.;]{0,60}\b(permitted|allowed|fine|ok)\b"
    r"|\b(may|can)\b[^.;]{0,20}\b(use|add|set|keep)\b[^.;]{0,20}inline[^.;]{0,40}"
    r"(colou?r|background|font)"
)


@pytest.mark.parametrize("role", ROLES)
def test_deck_style_block_never_permits_inline_paint(role):
    """With a deck style there is deck CSS, so the no-DS inline-colour permission ends:
    the block may not grant it back for any deck."""
    block = _plain(_deck_style_block(_instructions(role)))
    for m in _INLINE_PAINT_PERMISSION.finditer(block):
        context = block[max(0, m.start() - 30) : m.end()]
        assert re.search(NEG, context), f"{role} DECK STYLE block permits inline paint: {context!r}"


# ---------------------------------------------------------------------------
# Today's rules are untouched (green before and after the change)
# ---------------------------------------------------------------------------

#: sha256 of repr((NON_EMPTY_CONDITION, NON_EMPTY_RULES, EMPTY_CONDITION, EMPTY_RULES))
#: at HEAD b78b5d5d (the file last changed in 5653f3ec).  Task 9 must make the new prompt
#: pass these windows, not edit them.
BUILDER_PROMPT_RULES_DIGEST = "d8c69aaad796442956748e823e48734dde3b749442f57db2395bafe553487f0b"


def test_builder_prompt_rule_windows_are_untouched():
    digest = hashlib.sha256(
        repr((NON_EMPTY_CONDITION, NON_EMPTY_RULES, EMPTY_CONDITION, EMPTY_RULES)).encode()
    ).hexdigest()
    assert digest == BUILDER_PROMPT_RULES_DIGEST, (
        "tests/unit/test_builder_prompt.py NON_EMPTY_RULES / EMPTY_RULES changed; "
        "today's rules must still match unchanged (Ruling R18, C26)"
    )


@pytest.mark.parametrize(
    ("description", "pattern"),
    NON_EMPTY_RULES + EMPTY_RULES,
    ids=[d for d, _ in NON_EMPTY_RULES + EMPTY_RULES],
)
def test_todays_builder_rules_hold_outside_the_deck_style_block(description, pattern):
    """Without a deck style today's rules apply: they live outside the new block."""
    outside = _plain(_without_deck_style_block(load_skill("builder").instructions))
    assert re.search(pattern, outside), (
        f"builder prompt outside the DECK STYLE block lacks today's rule: {description}"
    )


FIXER_TODAY_RULES = (
    (
        "minimal-change disposition",
        r"minimal change[^.]{0,40}\. correct only what the finding requires",
    ),
    (
        "keep the outer root tag of the input html",
        r"keep the outer root tag of the input html exactly",
    ),
    ("keep the class tokens on the outer root", r"keep the class tokens on that outer root"),
)


@pytest.mark.parametrize(
    ("description", "pattern"), FIXER_TODAY_RULES, ids=[d for d, _ in FIXER_TODAY_RULES]
)
def test_todays_fixer_rules_hold_outside_the_deck_style_block(description, pattern):
    outside = _plain(_without_deck_style_block(load_skill("fixer").instructions))
    assert re.search(pattern, outside), (
        f"fixer prompt outside the DECK STYLE block lacks today's rule: {description}"
    )


@pytest.mark.parametrize("role", ROLES)
def test_prompt_keeps_exactly_one_input_paragraph(role):
    """C26: test_builder_prompt._block('INPUT') needs exactly one; the new block must
    not start with INPUT."""
    paragraphs = _paragraphs_starting(_instructions(role), "INPUT")
    assert len(paragraphs) == 1, f"{role}: expected one INPUT paragraph, found {len(paragraphs)}"


@pytest.mark.parametrize("role", ROLES)
def test_prompt_still_forbids_style_elements(role):
    assert re.search(
        r"(do not|don't|never)[^.]{0,20}emit a <style> element", _plain(_instructions(role))
    ), f"{role} prompt dropped the no-<style> rule"
