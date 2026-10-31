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

Addendum A (Task B5b; spec Addendum A sections A4/A5 and calls Q1/Q3; PLAN-CORRECTIONS-A
A20/A21; Ruling RA5).  The same DECK STYLE block also states, in the same clause-window
style:

* brand assets (both roles): place the brand assets the catalogue's pieces name (the
  footer piece's logo); search with ``search_brand_assets`` only when that tool is
  available (A20: decks without a design system, workbench runs and old releases have no
  tool), and place what it returns; never invent a handle.  The builder searches when the
  look asks for icons or the slide shows products or concepts; the fixer searches only
  when the finding requires an asset (MINIMAL CHANGE);
* one footer per slide (both roles; Q1, A21): a bound slide fills its template's own
  footer (a label, ``{{slide:number}} / {{slide:count}}`` in its number slot, the logo
  inside a slot and never a third flex child; the template's sample number is
  placeholder), an unbound slide uses the deck style's footer piece, never two footers;
  dark slides use the light-on-dark logo (Q3).  From the B5a review (the main two-footer
  risk: the measured footer pieces reuse the template's slide-footer class and their use
  line says "every slide except the cover"): a bound slide whose section has a footer
  never adds the footer piece, even when the piece's use line says every slide;
* one ground (builder only; A4): a light template section (``white`` or default) renders
  on the deck's default ground, so ``white`` is dropped on content slides; dark and event
  treatments never change.  The fixer never drops ``white`` (RA5): no fixer clause says
  to, and its outer-root class-token pin stays;
* precedence (builder only; RA5): the block's precedence sentence extends to IMAGE RULES,
  and the IMAGE RULES line "If no image ids are supplied, build the slide without images"
  stays as written.

Ruling RA15 (the B5b review's findings 1, 2, 3 and 5), in the same style:

* the whole-block fence (both roles): the block's lead (its heading, the lines before its
  first bullet, and that bullet) says the WHOLE block applies only to a payload that
  carries deck_style.  The B5b finalist F1 showed the closing "skip this block" alone does
  not stop the model applying the block's rules to decks without one.  The builder also
  keeps its page-token fence ("without deck_style, write no {{slide:number}} or
  {{slide:count}}");
* one footer on every slide except the cover (both roles): a bound slide whose section has
  no footer, like an unbound slide, uses the footer piece; the piece is only for slides
  without a footer of their own; and no clause bars every bound slide from the piece
  (that contradiction left the footer-less white sections of the Databricks template
  unnumbered);
* the cover (both roles): no page tokens and no footer piece, and a footer its section
  ships stays as shipped; no clause strips the cover's own footer;
* the fixer's footer rules (fixer only): every footer bullet carries "only when the
  finding concerns a footer", or sits nested under a bullet that does.

"Without a deck style" rules are unchanged: each prompt outside its DECK STYLE block is
byte-identical to HEAD (digest pin), so every new rule lives inside the block.  Traps for
the new text: no blank line or upper-case heading paragraph inside the block (it would end
the block there and move the outside digest); never quote Meridian's ``bottom: 56px``.
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
    (
        # Ruling R26 (Task 8): without a design system an unbound slide's ground is the
        # deck style's ground piece, since the block bans an inline background.
        "without a design system, an unbound slide's ground is the deck style's ground piece "
        "that the look names, its class on the slide's root element",
        (
            r"(no bound section|unbound|not bound|section_html is empty)",
            r"(design_system_active is false|without a design system|no design system)",
            r"\bground piece\b|\bground\b[^.]{0,60}\b(piece|class)\b",
            LOOK + r"[^.]{0,20}\bnames?\b|\bnames?\b[^.]{0,30}" + LOOK,
            r"\bclass\b[^.]{0,40}\broot\b|\broot\b[^.]{0,40}\bclass\b",
        ),
        1,
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


# ---------------------------------------------------------------------------
# Addendum A (Task B5b): brand assets, one footer, one ground (red until promoted)
# ---------------------------------------------------------------------------

#: The tool A1 binds for builders and fixers.
SEARCH_TOOL = r"search_brand_assets"
#: Searching: the tool by name, or the verb.
SEARCH = r"(search_brand_assets|\bsearch(es|ing)?\b)"
#: Putting an asset on the slide.  Not "in place of" (the catalogue rule's "this slide's
#: copy in place of the sample text").
PLACE = (
    r"((?<!in )\bplace[sd]?\b|\bplacing\b|\bput\b|\bkeep\b|\bcop(y|ies)\b|\binclude\b"
    r"|\bembed\b|\buse\b|\bcarr(y|ies)\b)"
)
#: The general term, not "logo" or "handle": the dark-slide logo rule ("use the
#: light-on-dark logo the footer piece's use line names") must not stand in for it.
BRAND_ASSET = r"(\bassets?\b|\{\{ds-asset)"
#: The deck style's catalogue (its pieces, their example_html).
CATALOGUE = r"(\bcatalog(ue)?('s)?\b|\bpieces?\b|\bcomponents?\b|example_html)"
NAMES = r"\b(name|names|named|hold|holds|carr(y|ies)|shows?|contains?|gives?|lists?)\b"


def _gap(n: int) -> str:
    """Up to ``n`` characters of one sentence with no negation in them."""
    return rf"(?:(?!\bnot\b|n't\b|\bnever\b|\bno\b)[^.;]){{0,{n}}}"


#: "Place the brand assets the catalogue's pieces name", in that order and un-negated, or
#: passive ("the assets the pieces hold are kept").  Not "search when the finding requires
#: an asset the catalogue does not name" (a B5b scratch sabotage).
PLACE_NAMED_ASSETS = (
    r"(\b(place|places|put|puts|keep|keeps|copy|copies|include|includes|embed|embeds|use|uses)\b"
    + _gap(30)
    + BRAND_ASSET
    + _gap(60)
    + CATALOGUE
    + _gap(30)
    + NAMES
    + r"|"
    + BRAND_ASSET
    + _gap(60)
    + CATALOGUE
    + _gap(30)
    + NAMES
    + _gap(40)
    + r"\b(placed|kept|copied|included|embedded|used)\b)"
)
#: "available" / "bound": the condition A20 puts on every search instruction.
TOOL_AVAILABLE = r"\b(available|bound|offered|granted|provided|present|listed)\b"
CONDITIONAL = r"\b(when|if|whenever|while|where|unless|only)\b"
ICON = r"\bicons?\b"
LOGO = r"\blogos?\b"
HANDLE = r"\bhandles?\b"
FOOTER = r"\bfooters?\b"
#: The deck style's footer piece: "footer piece", "the piece ... footer", a dk- footer
#: class (as in test_architect_deck_style_prompt.py).
FOOTER_PIECE = (
    r"(\bfooter (piece|component)s?\b|(?<![\w-])\.?dk-[\w-]*footer\b"
    r"|\b(piece|component)s?\b[^.]{0,30}\bfooter\b)"
)
#: A bound slide's own footer: "a bound slide", "its template's own footer".
BOUND = r"(\bbound\b|\btemplate('s)? (own )?footers?\b|\bown footers?\b|\bsection's footer\b)"
NUMBER_TOKEN = r"\{\{slide:number\}\}"
COUNT_TOKEN = r"\{\{slide:count\}\}"
PAGE_TOKEN = r"\{\{slide:(number|count)\}\}"
#: "n / N" (owner decision 3): both tokens, number first, a slash between.
PAGE_TOKENS_N_OF_N = NUMBER_TOKEN + r"\s*/\s*" + COUNT_TOKEN
DARK_SLIDES = r"(\bdark (slides?|sections?|grounds?|backgrounds?)\b|\bdividers?\b)"
#: The light-on-dark logo variant (as in test_architect_deck_style_prompt.py).
LIGHT_ON_DARK = (
    r"(\blight-on-dark\b|\bon-dark\b"
    r"|\b(reverse[ds]?|white|knock-?out|inverse|negative|light) (logo|mark|variant|version|one"
    r"|lockup)s?\b)"
)
#: The deck's default ground (A4): "the deck's default ground", "the deck's own ground".
DEFAULT_GROUND = r"(\bdefault\b[^.]{0,20}\bground\b|\bdeck's (own |one )?ground\b)"
LIGHT_SECTION = (
    r"(\blight\b[^.]{0,30}\b(sections?|treatments?)\b"
    r"|\b(sections?|treatments?)\b[^.]{0,30}\blight\b)"
)
#: Dropping the white token: "drop white", "white is removed".
DROP_WHITE = (
    r"(\b(drop|drops|dropping|remove|removes|removing|omit|omits|strip|strips|delete|deletes"
    r"|lose|loses|leave off|leaves off)\b[^.;]{0,40}\bwhite\b"
    r"|\bwhite\b[^.;]{0,40}\b(dropped|removed|omitted|stripped|deleted)\b)"
)
#: The logo inside a footer slot (A21): "the logo inside the label's span", "the label's
#: slot holds the logo", "never a third child".  The slot phrase follows the logo (or the
#: slot holds it), so "the label in the first slot, the logo beside it" does not count.
LOGO_IN_SLOT = (
    r"(\blogos?\b[^.;]{0,40}\b(inside|in|within|into) (a|the|its|that|one|their|this)"
    r" (first |label('s)? |existing |same )?(span|slot)s?\b"
    r"|\b(span|slot)s?\b[^.;]{0,15}\b(holds?|carr(y|ies)|gets?|takes?|contains?)\b[^.;]{0,15}"
    r"\blogos?\b"
    r"|\b(not|never|no)\b[^.;]{0,20}\bthird\b)"
)
#: A ban on adding the footer piece: "never adds the deck style's footer piece", "carries
#: no footer piece".
_ADD_VERB = (
    r"\b(add|adds|adding|use|uses|place|places|carr(y|ies)|cop(y|ies)|append|appends|include"
    r"|includes|gets?|takes?)\b"
)
NEVER_ADDS_FOOTER_PIECE = (
    r"(\b(never|not|no|don't|do not|must not)\b[^.;]{0,30}"
    + _ADD_VERB
    + r"[^.;]{0,40}"
    + FOOTER_PIECE
    + r"|"
    + _ADD_VERB
    + r"[^.;]{0,10}\bno\b[^.;]{0,30}"
    + FOOTER_PIECE
    + r")"
)
#: The one-ground rule said as a light section on the default ground.
ONE_GROUND = r"\blight\b[^.;]{0,80}" + DEFAULT_GROUND

# --- RA15 needles ------------------------------------------------------------------------

#: "footer" that is not the start of "footer piece" / "footer component".
_NOT_PIECE = r"(?!\s+(piece|component)s?\b)"
#: A reference to the whole block: "this whole block", "every rule in it", "these rules".
WHOLE_BLOCK = (
    r"(\b(this|the) (whole |entire )?block\b|\b(whole|entire) block\b"
    r"|\b(every|each|all|any) (of )?(its |these |the |this block's )?(rules?|bullets?|lines?)\b"
    r"|\b(these|its|the following) rules\b|\bnone of (it|this|these|them|its rules)\b)"
)
#: No deck style in the payload: "without deck_style", "deck_style is absent".
NO_DECK_STYLE = (
    r"(\b(without|absent|lacking|lacks?|missing|no)\b (a |the |any )?"
    + DECK_STYLE
    + r"|"
    + DECK_STYLE
    + r" (is )?(absent|missing|empty|not present|not set)\b)"
)
#: The block applies ONLY with deck_style, or is skipped without it (either order).
FENCED_TO_DECK_STYLE = (
    r"(\bonly\b[^.;]{0,60}"
    + DECK_STYLE
    + r"|"
    + DECK_STYLE
    + r"[^.;]{0,30}\bonly\b|"
    + NO_DECK_STYLE
    + r"[^.;]{0,80}\b(skip|ignore|disregard|does not apply|do not apply|doesn't apply"
    r"|don't apply|not apply|none of)\b"
    r"|\b(skip|ignore|disregard)\b[^.;]{0,60}\b(without|absent|unless|missing|lacking)\b"
    r"[^.;]{0,30}" + DECK_STYLE + r")"
)
#: L1: "without deck_style, write no {{slide:number}} or {{slide:count}}" (either order).
NO_PAGE_TOKENS_WITHOUT_DECK_STYLE = (
    NO_DECK_STYLE
    + r"[^.;]{0,60}"
    + NEG
    + r"[^.;]{0,30}"
    + PAGE_TOKEN
    + r"|"
    + NEG
    + r"[^.;]{0,30}"
    + PAGE_TOKEN
    + r"[^.;]{0,60}"
    + NO_DECK_STYLE
)
#: A section (or slide) with a footer of its own: "whose section has a footer".
HAS_OWN_FOOTER = (
    r"\b(has|have|ships?|carr(y|ies)|holds?|includes?|provides?|comes with|with)\s+"
    r"(a|an|its own|their own|its|one)\s+(own\s+)?footers?\b" + _NOT_PIECE
)
#: A section (or slide) without one: "whose section has no footer", "without a footer of
#: their own".  Not "without a footer piece".
NO_OWN_FOOTER = (
    r"(\b(without|lacking|lacks?|with no|has no|have no|having no|ships? no|carr(y|ies) no"
    r"|holds? no)\s+(a\s+|an\s+|any\s+|its\s+|their\s+)?(own\s+)?footers?\b"
    + _NOT_PIECE
    + r"|\bno (own )?footers? of (its|their) own\b)"
)
#: An un-negated verb that puts the piece on the slide ("uses", "takes"), not "never adds"
#: and not the noun in "the piece's use line".
POS_USE = (
    r"(?<!never )(?<!not )(?<!n't )(?<!\bno )"
    r"\b(use|uses|using|take|takes|get|gets|carry|carries|add|adds|copy|copies|place|places"
    r"|gain|gains|receive|receives)\b(?! line)"
)
#: Between the footer-less condition and its verb: no other subject ("unbound"), no "none"
#: and no negation, inside one ;-free segment.
_SAME_SUBJECT_GAP = r"(?:(?!\bunbound\b|\bnone\b|\bnot\b|n't\b|\bnever\b|\bno\b)[^.;]){0,60}"
#: RA15: "a bound slide whose section lacks a footer uses the deck style's footer piece",
#: in that order, so the bound slide is the one that takes the piece.  Not "… lacks a footer
#: carries no footer; an unbound slide uses the footer piece" (the fix-round-1 mutation e).
BOUND_WITHOUT_FOOTER_USES_PIECE = (
    r"\bbound\b[^.;]{0,60}" + NO_OWN_FOOTER + _SAME_SUBJECT_GAP + POS_USE + _gap(40) + FOOTER_PIECE
)
#: The footer piece is only for slides without a footer of their own (either order).
ONLY_FOR_FOOTERLESS = (
    r"("
    + FOOTER_PIECE
    + r"[^.;:]{0,30}\bonly\b[^.;]{0,30}"
    + NO_OWN_FOOTER
    + r"|\bonly\b[^.;]{0,40}"
    + NO_OWN_FOOTER
    + r"[^.;]{0,40}"
    + FOOTER_PIECE
    + r")"
)
EXCEPT_COVER = r"\b(except|but|other than|apart from|save|besides|bar)\b[^.;]{0,15}\bcover\b"
ONE_FOOTER = (
    r"\b(exactly one|one and only one|a single|just one|only one|one)\b[^.;]{0,15}\bfooters?\b"
    + _NOT_PIECE
)
#: "Every slide except the cover carries exactly one footer" (either order).
EVERY_NON_COVER_SLIDE_ONE_FOOTER = (
    r"((\b(every|each|all)\b[^.;]{0,20}\bslides?\b[^.;]{0,10}"
    + EXCEPT_COVER
    + r"|\b(every|each|all) non-cover slides?\b)[^.;]{0,40}"
    + ONE_FOOTER
    + r"|"
    + ONE_FOOTER
    + r"[^.;]{0,30}\b(every|each|all)\b[^.;]{0,20}\bslides?\b[^.;]{0,10}"
    + EXCEPT_COVER
    + r")"
)
#: Page numbering: the tokens, "page tokens", "page numbers", "numbered".  Not the bare
#: word "number" ("its number slot").
PAGE_NUM = r"(\bpage (tokens?|numbers?)\b|\bslide numbers?\b|\bnumber(ed|ing)\b|" + PAGE_TOKEN + ")"
#: The cover gets no page tokens: tied to the cover, so the L1 fence ("write no
#: {{slide:number}} …): every slide except the cover …") does not stand in for it.  The
#: negation sits right before the tokens (at most 15 characters, no comma), so "no footer
#: piece but carries page tokens" does not count.
COVER_NO_PAGE_NUMBERS = (
    r"(\bcover\b[^.;]{0,40}"
    + NEG
    + r"[^.;,]{0,15}"
    + PAGE_NUM
    + r"|"
    + NEG
    + r"[^.;,]{0,15}"
    + PAGE_NUM
    + r"[^.;]{0,30}\b(on|for|in|to) the cover\b|"
    + PAGE_NUM
    + r"[^.;:()]{0,40}\b(except|but|other than|apart from)\b[^.;]{0,15}\bcover\b)"
)
#: The cover gets no footer piece (the negation right before the piece, as above, so "no
#: page tokens but uses the footer piece" does not count).
COVER_NO_FOOTER_PIECE = (
    r"(\bcover\b[^.;]{0,40}"
    + NEG
    + r"[^.;,]{0,15}"
    + FOOTER_PIECE
    + r"|"
    + NEG
    + r"[^.;,]{0,15}"
    + FOOTER_PIECE
    + r"[^.;]{0,30}\b(on|to|for|in) the cover\b)"
)
_KEEP = r"(?<!never )(?<!not )(?<!n't )\b(keeps?|kept|leaves?|retains?|preserves?)\b"
_SHIPS = r"\b(ships?|shipped|comes with)\b"
_STAYS = r"\b(stays?|kept|remains?|unchanged|untouched|as (it )?ships|as shipped|in place)\b"
#: A footer the section ships stays as shipped: "keeps any footer its section ships",
#: "a footer its section ships stays as shipped", "keeps its shipped footer".
SHIPPED_FOOTER_KEPT = (
    r"("
    + _KEEP
    + _gap(30)
    + r"\bfooters?\b"
    + _NOT_PIECE
    + _gap(40)
    + _SHIPS
    + r"|"
    + _KEEP
    + _gap(20)
    + r"\bshipped footers?\b|\bfooters?\b"
    + _NOT_PIECE
    + _gap(40)
    + _SHIPS
    + _gap(40)
    + _STAYS
    + r")"
)
#: Stripping the cover's own footer: "the cover carries no footer", "no footer on the
#: cover", "remove the footer from the cover", "the cover …; a footer its section ships is
#: removed".  "No footer piece" is allowed, and so is "a second footer is removed".
COVER_DROPS_ITS_FOOTER = (
    r"(\bcover\b[^.;]{0,30}\b(carries|carry|has|have|gets?|takes?|shows?|bears?|keeps?)\s+no\s+"
    r"footers?\b" + _NOT_PIECE + r"|\bno\s+footers?\b" + _NOT_PIECE + r"[^.;]{0,20}\b(on|for) the "
    r"cover\b|\b(remove|removes|drop|drops|strip|strips|delete|deletes)\b[^.;]{0,30}\bfooters?\b"
    + _NOT_PIECE
    + r"[^.;]{0,30}\bcover\b|\bcover\b[^.]{0,80}(?<!second )\bfooters?\b"
    + _NOT_PIECE
    + r"[^.;]{0,40}\b(removed|dropped|stripped|deleted)\b)"
)
#: The fixer's footer condition: "only when the finding concerns a footer".
FINDING_CONCERNS = (
    r"\bfinding\b[^.;]{0,30}\b(concerns?|is about|names?|involves?|flags?|reports?|targets?"
    r"|touches?|asks? about|is on|mentions?)\b"
)
FOOTER_FINDING_CONDITION = (
    r"(\b(only|solely)\b[^.;]{0,20}\b(when|if|where|while)\b[^.;]{0,20}"
    + FINDING_CONCERNS
    + r"|\bunless\b[^.;]{0,20}"
    + FINDING_CONCERNS
    + r")"
)
#: What makes a fixer bullet a footer rule (beside naming a footer): the cover, two
#: footers, page tokens, the label, the light-on-dark logo, bound/unbound slides, the
#: number slot, the third child.  The brand-assets bullet ("the logo in the footer
#: piece") is not one.
FOOTER_RULE_MARK = (
    r"(\bcover\b|\btwo footers\b|\bsecond footer\b|\bpage tokens?\b|"
    + PAGE_TOKEN
    + r"|\blabel\b|light-on-dark|\bbound\b|\bunbound\b|\bnumber slot\b|\bthird child\b)"
)

COMMON_ADDENDUM_A_RULES: tuple[Rule, ...] = (
    (
        "place the brand assets the catalogue's pieces name (the footer piece's logo)",
        (PLACE_NAMED_ASSETS,),
        1,
    ),
    (
        "A20: search with search_brand_assets only when that tool is available",
        (SEARCH_TOOL, r"\btool\b", TOOL_AVAILABLE, CONDITIONAL),
        1,
    ),
    (
        "place what the search returns",
        (SEARCH, PLACE, r"\b(returns?|returned|results?|finds|found)\b"),
        2,
    ),
    (
        "never invent a handle (use only the catalogue's or a search's handles)",
        (
            HANDLE,
            r"(" + NEG + r"[^.]{0,20}\b(invent|fabricat|guess|make up|made[- ]up|coin)"
            r"|\bonly\b[^.]{0,30}\bhandles?\b[^.]{0,60}"
            r"\b(catalog|search|return|result|pieces?|components?|example_html))",
        ),
        1,
    ),
    (
        "Q1: a bound slide fills its template's own footer",
        (
            r"\bbound\b",
            r"(\b(template|section)('s|s')?\b[^.]{0,30}\bfooters?\b|\bown footers?\b"
            r"|\bits footer\b)",
            r"\b(fill|fills|filled|filling)\b",
        ),
        1,
    ),
    (
        "Q1: the bound slide's footer carries a label (its label slot)",
        (BOUND, FOOTER, r"\blabels?\b"),
        2,
    ),
    (
        "Q1: the bound slide's footer number slot holds {{slide:number}} / {{slide:count}}",
        (BOUND, FOOTER, PAGE_TOKENS_N_OF_N),
        2,
    ),
    (
        "Q1: the bound slide's footer carries the logo",
        (BOUND, FOOTER, LOGO),
        2,
    ),
    (
        "A21: the logo goes inside a footer slot (span), never as a third flex child",
        (FOOTER, LOGO, LOGO_IN_SLOT),
        2,
    ),
    (
        "A21: the template's sample page number is placeholder (the page tokens replace it)",
        (
            r"\b(sample|placeholder|stray|hard-?coded|typed)\b",
            r"(?<!:)\bnumbers?\b",
            r"(\b(replace|replaces|replaced|replacing|placeholder|instead)\b|in its place|"
            + PAGE_TOKEN
            + r")",
        ),
        2,
    ),
    (
        "Q1: an unbound slide uses the deck style's footer piece",
        (
            r"\bunbound\b|\bnot bound\b|\bno (bound )?section\b|\bwithout a (bound )?section\b",
            FOOTER_PIECE,
            r"\b(use|uses|using|carr(y|ies)|gets?|takes?|cop(y|ies)|place|places)\b",
        ),
        1,
    ),
    # B5a review: the architect's measured footer pieces reuse the template's slide-footer
    # class and their use line says "every slide except the cover", so a bound slide
    # that obeys the piece's use line adds a second footer (the main two-footer risk).
    # RA15: only a bound slide whose section HAS a footer; one without takes the piece.
    (
        "RA15: a bound slide whose section has a footer never adds the deck style's footer piece",
        (r"\bbound\b", HAS_OWN_FOOTER, NEVER_ADDS_FOOTER_PIECE),
        1,
    ),
    (
        "B5a review: even when the footer piece's use line says every slide",
        (
            r"\b(even (when|if|though)|whatever|regardless of|although|though)\b[^.;]{0,60}"
            r"\buse( line)?\b",
            r"\b(every|each|all) slides?\b",
        ),
        1,
    ),
    (
        "RA15: the footer piece is only for slides without a footer of their own",
        (ONLY_FOR_FOOTERLESS,),
        1,
    ),
    (
        "RA15: a bound slide whose section has no footer uses the deck style's footer piece",
        (BOUND_WITHOUT_FOOTER_USES_PIECE,),
        1,
    ),
    (
        "RA15: every slide except the cover carries exactly one footer",
        (EVERY_NON_COVER_SLIDE_ONE_FOOTER,),
        1,
    ),
    (
        "Q1: a slide never carries two footers",
        (
            r"(\b(never|not|no|nor)\b[^.;]{0,30}\b(two|a second|double|another|both)\b"
            r"[^.;]{0,10}\bfooters?\b"
            r"|\b(one|a single|only one|just one) footer\b[^.;]{0,20}\b(per|on (each|every|a|any))"
            r" slide\b"
            r"|\b(never|not|no)\b[^.;]{0,20}\bfooters? twice\b)",
        ),
        1,
    ),
    # RA15 replaces "no footer on the cover": the cover gets no page tokens and no footer
    # piece, and a footer its section ships (the Databricks cover's) stays as shipped.
    (
        "RA15: the cover gets no page tokens",
        (COVER_NO_PAGE_NUMBERS,),
        1,
    ),
    (
        "RA15: the cover gets no footer piece",
        (COVER_NO_FOOTER_PIECE,),
        1,
    ),
    (
        "RA15: a footer the cover's section ships stays as shipped",
        (r"\bcover\b", SHIPPED_FOOTER_KEPT),
        2,
    ),
    (
        "Q3: dark slides (dividers, closing) use the light-on-dark logo",
        (
            DARK_SLIDES,
            LIGHT_ON_DARK,
            r"\b(use|uses|using|for|on|carr(y|ies)|gets?|takes?)\b",
        ),
        1,
    ),
)

BUILDER_ADDENDUM_A_RULES: tuple[Rule, ...] = (
    (
        "RA5: the block takes precedence over BOUND TEMPLATE SECTION, NO BOUND SECTION and "
        "IMAGE RULES",
        (
            r"\b(precedence|override|overrides|priority|supersedes?|wins?|prevails?)\b",
            r"\bbound template section\b",
            r"\bno bound section\b",
            r"\bimage rules\b",
        ),
        1,
    ),
    (
        "search when the look asks for icons",
        (
            SEARCH,
            LOOK,
            ICON,
            r"\b(asks?|calls? for|wants?|says|names?|requests?|mentions?)\b",
        ),
        2,
    ),
    (
        "search when the slide shows products or concepts",
        (SEARCH, r"\bproducts?\b", r"\bconcepts?\b"),
        2,
    ),
    (
        "A4: a light template section (white or default) renders on the deck's default ground",
        (LIGHT_SECTION, r"\bwhite\b", DEFAULT_GROUND),
        1,
    ),
    (
        "A4: so white is dropped on content slides",
        (DROP_WHITE, r"\bcontent slides?\b"),
        2,
    ),
    (
        "L1: without deck_style, no {{slide:number}} or {{slide:count}} is written",
        (NO_PAGE_TOKENS_WITHOUT_DECK_STYLE,),
        1,
    ),
    (
        "A4: dark and event treatments are never changed",
        (
            r"\bdark\b",
            r"\bevent\b",
            r"(\b(never|not|no)\b[^.]{0,30}\b(change|changed|changes|touch|touched|alter|altered"
            r"|recolou?r|recolou?red|flip|flipped)\b"
            r"|\b(stay|stays|remain|remains|unchanged|kept|as shipped|as they ship)\b)",
        ),
        1,
    ),
)

FIXER_ADDENDUM_A_RULES: tuple[Rule, ...] = (
    (
        "A20: the fixer searches only when the finding requires an asset (MINIMAL CHANGE)",
        (
            SEARCH,
            r"\bfinding\b",
            r"\b(assets?|icons?|logos?|handles?)\b",
            r"\b(only|unless)\b",
        ),
        2,
    ),
)

ROLE_ADDENDUM_A_RULES = {
    "builder": COMMON_ADDENDUM_A_RULES + BUILDER_ADDENDUM_A_RULES,
    "fixer": COMMON_ADDENDUM_A_RULES + FIXER_ADDENDUM_A_RULES,
}

ROLE_ADDENDUM_A_CASES = [
    pytest.param(role, rid, needles, width, id=f"{role}: {rid}")
    for role, rules in ROLE_ADDENDUM_A_RULES.items()
    for rid, needles, width in rules
]


@pytest.mark.parametrize(("role", "rule", "needles", "width"), ROLE_ADDENDUM_A_CASES)
def test_deck_style_block_states_addendum_a_rule(role, rule, needles, width):
    block = _plain(_deck_style_block(_instructions(role)))
    assert _holds(block, needles, width), f"{role} DECK STYLE block lacks: {rule}"


# --- RA15 pins (red until the RA15 wording pass) ------------------------------------------


def _block_lead(block: str) -> str:
    """The block's heading, any lines before its first bullet, and that first bullet."""
    lines = block.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"[ \t]*- ", line):
            return "\n".join(lines[: i + 1])
    return block


def _bullets(block: str) -> list[tuple[int, str]]:
    """(indent, text) of each bullet item of the raw block; continuation lines joined."""
    items: list[tuple[int, str]] = []
    for line in block.splitlines():
        m = re.match(r"^([ \t]*)- (.*)$", line)
        if m:
            items.append((len(m.group(1)), m.group(2)))
        elif items and line.strip() and not _HEADING_RE.match(line):
            items[-1] = (items[-1][0], items[-1][1] + " " + line.strip())
    return items


@pytest.mark.parametrize("role", ROLES)
def test_deck_style_block_lead_fences_the_whole_block_to_deck_style(role):
    """RA15 (i): the block's lead says the WHOLE block applies only to a payload carrying
    deck_style.  F1 put page tokens in 10 of 10 no-deck-style rows with only the closing
    "skip this block", so the closing line alone does not count: the fence must sit in the
    heading, the lines before the first bullet, or the first bullet."""
    lead = _plain(_block_lead(_deck_style_block(_instructions(role))))
    assert _holds(lead, (WHOLE_BLOCK, FENCED_TO_DECK_STYLE), 1), (
        f"{role} DECK STYLE block's lead does not fence the whole block to deck_style: {lead!r}"
    )


@pytest.mark.parametrize("role", ROLES)
def test_no_clause_bars_every_bound_slide_from_the_footer_piece(role):
    """RA15 (ii): "a bound slide never adds the footer piece" with no condition contradicts
    "a bound slide whose section has no footer uses the piece".  Every clause that bars a
    bound slide from the piece names the section's own footer as the reason."""
    for clause in _clauses(_plain(_deck_style_block(_instructions(role)))):
        if re.search(r"\bbound\b", clause) and re.search(NEVER_ADDS_FOOTER_PIECE, clause):
            assert re.search(HAS_OWN_FOOTER, clause), (
                f"{role} bars a bound slide from the footer piece without the "
                f"'whose section has a footer' condition: {clause!r}"
            )


@pytest.mark.parametrize("role", ROLES)
def test_no_clause_strips_the_covers_own_footer(role):
    """RA15 (iii): the cover gets no page tokens and no footer piece, but a footer its
    section ships stays: no clause says the cover carries no footer or removes it."""
    for clause in _clauses(_plain(_deck_style_block(_instructions(role)))):
        m = re.search(COVER_DROPS_ITS_FOOTER, clause)
        assert not m, f"{role} strips the cover's own footer ({m.group(0)!r}): {clause!r}"


def test_fixer_footer_rules_all_sit_under_the_footer_finding_condition():
    """RA15 (iv): every fixer footer bullet applies only when the finding concerns a
    footer.  A footer bullet either carries that condition itself or is nested (indented
    deeper) under a bullet that does; a flat bullet after a conditioned one does not count
    (today's "Footers, when the finding concerns one:" gated only its own bullet)."""
    block = _deck_style_block(load_skill("fixer").instructions)
    items = _bullets(block)

    def conditioned(text: str) -> bool:
        plain = _plain(text)
        return bool(re.search(FOOTER, plain) and re.search(FOOTER_FINDING_CONDITION, plain))

    def fence(text: str) -> bool:
        plain = _plain(text)
        return bool(re.search(WHOLE_BLOCK, plain) and re.search(FENCED_TO_DECK_STYLE, plain))

    footer_rules = [
        i
        for i, (_, text) in enumerate(items)
        if re.search(FOOTER, _plain(text))
        and re.search(FOOTER_RULE_MARK, _plain(text))
        and not fence(text)
    ]
    assert footer_rules, "fixer DECK STYLE block states no footer rule"
    for i in footer_rules:
        indent, text = items[i]
        if conditioned(text):
            continue
        parent = next((j for j in range(i - 1, -1, -1) if items[j][0] < indent), None)
        assert parent is not None and conditioned(items[parent][1]), (
            f"fixer footer bullet is not under 'only when the finding concerns a footer': {text!r}"
        )


# --- Guards on the new text (green today; they must stay green) ----------------


@pytest.mark.parametrize("role", ROLES)
def test_every_search_brand_assets_instruction_is_conditioned_on_the_tool(role):
    """A20: a deck style without a design system, a workbench run and an old release bind
    no tool, so each clause naming search_brand_assets (or the clause before it) says it
    applies when the tool is available."""
    clauses = _clauses(_plain(_instructions(role)))
    for i, clause in enumerate(clauses):
        if re.search(SEARCH_TOOL, clause):
            near = " ".join(clauses[max(i - 1, 0) : i + 1])
            assert re.search(TOOL_AVAILABLE, near) and re.search(CONDITIONAL, near), (
                f"{role} names search_brand_assets without the tool-available condition: {clause!r}"
            )


def test_fixer_never_drops_white():
    """RA5: the one-ground rule is the builder's.  No fixer clause tells it to drop white
    or to put a light section on the deck's default ground, unless the clause negates it
    or names the builder as the one who does; the fixer keeps its outer root's class
    tokens."""
    instructions = load_skill("fixer").instructions
    for clause in _clauses(_plain(instructions)):
        for pattern in (DROP_WHITE, ONE_GROUND):
            for m in re.finditer(pattern, clause):
                before = clause[max(0, m.start() - 20) : m.end()]
                assert re.search(NEG, before) or re.search(r"\bbuilders?('s)?\b", clause), (
                    f"fixer prompt tells the fixer to drop white / change the ground: {clause!r}"
                )
    outside = _plain(_without_deck_style_block(instructions))
    assert re.search(r"keep the class tokens on that outer root", outside)


def test_fixer_does_not_search_on_the_builders_triggers():
    """A20: the fixer searches only when the finding requires an asset, not whenever the
    look asks for icons or the slide shows products (that would re-author the slide)."""
    block = _plain(_deck_style_block(load_skill("fixer").instructions))
    trigger = r"(\bproducts?\b|\bconcepts?\b|" + LOOK + r"[^.]{0,40}" + ICON + r")"
    for clause in _clauses(block):
        if re.search(SEARCH, clause) and re.search(trigger, clause):
            assert re.search(r"\bfinding\b", clause), (
                f"fixer searches on a builder trigger, not on the finding: {clause!r}"
            )


def test_image_rules_line_is_left_as_written():
    """RA5: the block's precedence covers IMAGE RULES; the IMAGE RULES line itself stays."""
    paragraphs = _paragraphs_starting(load_skill("builder").instructions, "IMAGE RULES")
    assert len(paragraphs) == 1
    assert "If no image ids are supplied, build the slide without images" in paragraphs[0]
    assert "NEVER guess or fabricate an image ID" in paragraphs[0]


#: sha256 of each prompt with its DECK STYLE block cut out (_without_deck_style_block),
#: at HEAD f59d0a04.  Task B5b puts every new rule inside the block, so "without a deck
#: style" the prompt is unchanged byte for byte (A20, RA5).
OUTSIDE_DECK_STYLE_DIGESTS = {
    "builder": "3995292fc11fa047462f4bc60b9d6ae11cb8c03a1df82f35e9a5f1b44f8497a3",
    "fixer": "dde8a5ceff9e78f7327ad8e8eb31d12b6f3b373c430c292c2459a9afe4c224f6",
}


@pytest.mark.parametrize("role", ROLES)
def test_prompt_outside_the_deck_style_block_is_unchanged(role):
    outside = _without_deck_style_block(_instructions(role))
    digest = hashlib.sha256(outside.encode()).hexdigest()
    assert digest == OUTSIDE_DECK_STYLE_DIGESTS[role], (
        f"{role} prompt changed outside its DECK STYLE block; without a deck style today's "
        "rules apply unchanged, so B5b's rules go inside the block (A20, RA5)"
    )
