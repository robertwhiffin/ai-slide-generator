"""Prompt contract: the architect writes the deck style and a look for every slide.

Plan Task 8 (architect deck style).  Spec:
docs/superpowers/specs/2026-10-29-architect-deck-style-design.md, sections 1, 2 and 5,
plus the Task 8 brief's prompt changes and its controller overrides (Rulings R19 and
R26, m4, the sanitiser rules) and PLAN-CORRECTIONS C25.  Task 8's "no page numbers"
rule is retired (Addendum A, Ruling RA4, PLAN-CORRECTIONS-A A19).

Addendum A (Task B5a; spec Addendum A section A5 and calls Q1 and Q3) adds FOOTER_RULES,
ICON_RULES and GROUND_RULES: the deck style always has a footer piece (a component whose
name or class names contain "footer", the eval scorer's definition, A17) holding the logo
handles chosen from ``deck_style_context.logos`` (one for light grounds, a light-on-dark
one for dark slides) and both page tokens ``{{slide:number}}`` and ``{{slide:count}}``;
every slide except the cover carries a footer (a bound slide fills its template's own
footer, an unbound one uses the footer piece, never two footers); a look states icon
intent but never names an icon handle, because builders search for icons themselves;
content slides share the deck's default light ground while dark sections stay dark.

The architect's ``deck_spec`` gains ``deck_style`` = ``{css, components: [{name,
class_names, use, example_html}]}`` and each SlideSpec a ``look``; an edit restyles
through ``deck_changes.deck_style``.  The payload carries ``deck_style_context`` =
``{design_tokens, template_classes}`` (src/domain/deck_style.py), and
``sanitise_deck_style`` strips what breaks its rules.  These tests pin the RULES the
prompt must state, not their wording or their place:

* the whole prompt is cut into clauses: blank-line paragraphs, indented or bulleted
  lines, lines ending in ``:``, and sentences (a full stop, ``!`` or ``?`` after a
  non-space character and before whitespace).  ``.dk-code .kw``, ``var(--x)``,
  ``url(data:...)`` and ``4,000`` do not end a sentence; ``e.g.``, ``i.e.``, ``etc.``,
  ``vs.`` and ``cf.`` are read as words first;
* each clause is lower-cased, whitespace-collapsed and stripped of backticks;
* a rule holds when every one of its needles matches inside one clause or, where the
  rule says so, two neighbouring clauses, in any order.  So a rule has to be stated
  locally, but it may be reworded freely and live in any block;
* a ban ("no @media", "never use @import", "image-set ... is stripped") must sit next
  to what it bans, in one sentence and not across a ";" (``_forbids``), so a sentence
  that permits the thing and negates something else does not count.

Three structural pins: SLIDESPEC FIELDS lists a ``look:`` line, DECKSPEC CONSTRUCTION
lists a ``deck_style:`` line AFTER ``slides:`` (C25: the seven existing field lines stay
directly under the heading), and the EDITING sentence that lists the deck_changes
fields names ``deck_style``.

Guards that are green today and must stay green (C25):

* the HEAD tuples of test_architect_edit_prompt.py that C25 says must survive
  (``DECKSPEC_HEADING``, ``HEAD_DECKSPEC_FIELD_LINES``, ``HEAD_SLIDESPEC_FIELD_LINES``,
  ``EDITING_RULE_PHRASES``, ``EDITING_GUARD_PHRASES``,
  ``DESIGN_SYSTEMS_CONTRACT_PHRASES``) are untouched (digest pin) and still hold on the
  prompt, the SlideSpec field lines as whole lines;
* the architect prose of test_skill_prose.py and the "never bind a merely similar
  section" rule are still stated.

Traps for the prompt author, pinned elsewhere: test_architect_edit_prompt.py's
``FORBIDDEN_BINDING_PATTERNS`` reject "every slide must have / should carry ..." and
"non-null" anywhere in the prompt (write "write a look for every slide" or "every slide
except the cover uses the footer piece" instead), its ``_slide_numbers_block`` needs
exactly one paragraph starting ``SLIDE NUMBERS`` (so do not head the footer rule that
way), and test_skills.py rejects ``88px``, ``72px``, ``56px`` and ``1280x720`` in any
skill (Meridian's footer sits at ``bottom: 56px``: never quote it).
"""

from __future__ import annotations

import hashlib
import re

import pytest

import src.core.database  # noqa: F401  (must be imported before other src.* modules)
from src.core.skills import load_skill
from tests.unit.test_architect_edit_prompt import (
    DECKSPEC_HEADING,
    DESIGN_SYSTEMS_CONTRACT_PHRASES,
    EDITING_GUARD_PHRASES,
    EDITING_RULE_PHRASES,
    HEAD_DECKSPEC_FIELD_LINES,
    HEAD_SLIDESPEC_FIELD_LINES,
)


def _instructions() -> str:
    return load_skill("architect").instructions


# ---------------------------------------------------------------------------
# Text helpers (pure: they take the prompt text, so they can be exercised on a
# candidate prompt without importing it)
# ---------------------------------------------------------------------------


def _plain(text: str) -> str:
    """Whitespace-collapsed, lower-cased text with markdown backticks removed."""
    return re.sub(r"\s+", " ", text.replace("`", "")).strip().lower()


#: Abbreviations whose full stop would otherwise end a sentence.
_ABBREVIATIONS = (("e.g.", "eg"), ("i.e.", "ie"), ("etc.", "etc"), ("vs.", "vs"), ("cf.", "cf"))

#: Paragraph breaks, a line break before an indented or bulleted line, and a line
#: break after a line that ends in ":" (a heading or a lead-in).
_LINE_BREAKS = re.compile(r"\n[ \t]*\n|\n(?=[ \t]+\S|[-•*][ \t])|(?<=:)[ \t]*\n")

#: A sentence end: ".", "!" or "?" after a non-space, non-"." character, before
#: whitespace or the end.  ".dk-code .kw" (a dot after a space or before a letter),
#: "var(--…)", "url(data:...)" and "10,000" are not sentence ends.
_SENTENCE_END = re.compile(r"(?<=[^\s.])[.!?](?=\s|$)")


def _clauses(text: str) -> list[str]:
    """The prompt's clauses: lines that stand alone, and sentences within them."""
    text = text.replace("`", "")
    for abbreviation, word in _ABBREVIATIONS:
        text = re.sub(re.escape(abbreviation), word, text, flags=re.IGNORECASE)
    clauses: list[str] = []
    for piece in _LINE_BREAKS.split(text):
        flat = re.sub(r"\s+", " ", piece).strip().lower()
        clauses.extend(s.strip() for s in _SENTENCE_END.split(flat) if s.strip())
    return clauses


def _windows(clauses: list[str], width: int):
    for size in range(1, width + 1):
        for i in range(len(clauses) - size + 1):
            yield " ".join(clauses[i : i + size])


def _holds(text: str, needles: tuple[str, ...], width: int) -> bool:
    """True when every needle matches inside one window of <= ``width`` clauses."""
    return any(all(re.search(n, w) for n in needles) for w in _windows(_clauses(text), width))


def _paragraphs_starting(text: str, prefix: str) -> list[str]:
    return [p for p in text.split("\n\n") if p.startswith(prefix)]


def _one_paragraph(text: str, prefix: str) -> str:
    paragraphs = _paragraphs_starting(text, prefix)
    assert len(paragraphs) == 1, f"expected exactly one {prefix!r} block, found {len(paragraphs)}"
    return paragraphs[0]


def _field_line_indexes(block: str, name: str) -> list[int]:
    return [i for i, line in enumerate(block.splitlines()) if re.match(rf"^\s*{name}:", line)]


# ---------------------------------------------------------------------------
# Needles
# ---------------------------------------------------------------------------

#: A negation that comes before what it forbids ("no", "never use", "do not write").
NEG_BEFORE = r"(\b(no|never|not|nor|without|avoid)\b|n't\b|\bdo not\b|\bmust not\b)"
#: A ban that comes after what it forbids ("... is dropped").
BANNED_AFTER = r"\b(is |are )?(dropped|stripped|removed|forbidden|not allowed|rejected)\b"


def _forbids(thing: str, gap: int) -> str:
    """``thing`` with a negation at most ``gap`` characters before it, or a ban after it,
    in the same sentence and not across a ";": "no @media", "never use @import",
    "image-set ... is stripped".  "No url() except data:; remote addresses are fine"
    does not forbid remote addresses.
    """
    return rf"({NEG_BEFORE}[^.;]{{0,{gap}}}{thing}|{thing}[^.;]{{0,40}}{BANNED_AFTER})"


#: ``deck_style`` / "deck style"; not ``deck_style_context`` (the "_" is a word character).
DECK_STYLE = r"\bdeck[_ ]style\b"
DECK_CHANGES_STYLE = r"\bdeck_changes\.deck_style\b"
LOOK = r"(?<![\w-])look(?![\w-])"
PIECE = r"\b(pieces?|components?)\b"
CATALOGUE_ENTRY = r"\b(pieces?|components?|entry|entries|catalogue|catalog)\b"
#: a dk- class (".dk-x" or "dk-x"), not the "--dk-" custom-property prefix.
DK_CLASS = r"(?<![\w-])\.?dk-"
DS_ABSENT = (
    r"(\bwithout (a |any )?design system\b|\bno design system\b|"
    r"\bdesign_system_active is false\b|\bwhen there is no design system\b|"
    r"\bplain slide style\b)"
)
DS_ACTIVE = (
    r"(\b(with|under|when|while) (a|the) design system\b|"
    r"\bdesign system is (active|in force|present|on|pinned)\b|"
    r"\bdesign_system_active is true\b)"
)
#: ":root" forbidden: "no :root", "never declare :root", ":root is dropped", ...
ROOT_FORBIDDEN = (
    r"(\b(no|never|not|don't|nor)\s+(\w+\s+){0,2}:root\b|"
    r":root\b[^.]{0,40}\b(is |are )?(dropped|stripped|removed|not allowed|forbidden|never)\b)"
)
DECK_WIDE = r"\b(across the deck|whole deck|every slide|all (the )?slides)\b"
#: a whole (not a "whole-deck") style: "the whole revised style", "the full css".
WHOLE_STYLE = r"\b(whole|full|entire|complete)\b(?![- ]deck)[^.]{0,30}\b(style|deck[_ ]style|css)\b"

#: A rule is (id, description, needles, width): every needle must match inside one
#: window of at most ``width`` consecutive clauses.  Width 1 keeps a rule inside one
#: sentence or bullet; width 2 lets a condition or a reason sit in the neighbouring
#: clause.  Needles written with ``[^.]`` gaps are themselves sentence-local.
Rule = tuple[str, str, tuple[str, ...], int]

BUILD_RULES: tuple[Rule, ...] = (
    (
        "build_writes_deck_style_once",
        "on a build, write deck_style once",
        (
            DECK_STYLE,
            r"\bbuild(s|ing)?\b",
            r"\b(write|writes|author|authors|set|sets)\b",
            r"\b(once|a single|one deck style)\b",
        ),
        1,
    ),
    (
        "deck_style_from_the_planned_slides_needs",
        "the deck style comes from what the planned slides need",
        (
            DECK_STYLE,
            r"\b(planned slides?|slides? (that )?you (have )?planned|slides? you plan)\b",
            r"\bneeds?\b",
        ),
        2,
    ),
    (
        "deck_style_from_deck_style_context",
        "the deck style is written from the payload's deck_style_context",
        (
            r"\bdeck_style_context\b",
            r"\b(from|use|uses|using|read|reads|base|based|take|takes|draw|draws|consult|check)\b",
        ),
        1,
    ),
    (
        "deck_style_context_names_tokens_and_template_classes",
        "deck_style_context carries design_tokens and template_classes",
        (r"\bdeck_style_context\b", r"\bdesign_tokens\b", r"\btemplate_classes\b"),
        2,
    ),
    (
        "reuse_an_existing_design_system_or_template_piece",
        "reuse a design-system or template piece when one exists",
        (
            r"\b(design[- ]system|template)\b",
            r"\b(pieces?|components?|class(es)?)\b",
            r"\b(reuse\w*|use (it|that|that one|them|the existing)|rather than|instead of)\b",
            r"\b(already|exists?|existing|provides?|has one|have one|offers?)\b",
        ),
        1,
    ),
    (
        "add_only_what_is_missing",
        "add only what is missing",
        (
            r"\b(add|adds|adding|define|write)\b[^.]{0,20}\bonly\b|\bonly (add|define|write)\b"
            r"|\badd nothing\b",
            r"\b(missing|lacks?|does not (have|provide)|doesn't (have|provide)|not already)\b",
        ),
        1,
    ),
    (
        "thin_about_4000_characters",
        "keep it thin, about 4,000 characters",
        (
            r"\b(thin|short|small|lean|light)\b",
            r"(\babout |\baround |\broughly |\bapproximately |~ ?)4,?000 characters\b",
        ),
        2,
    ),
    (
        "css_hard_cap_10000_characters",
        "the css stays under 10,000 characters",
        (r"\b10,?000\b", r"\b(characters|chars)\b"),
        2,
    ),
    (
        "at_most_12_pieces",
        "at most 12 pieces",
        (
            r"\b(at most|no more than|up to|never more than|a maximum of|maximum of|max) "
            r"(12|twelve)\b|\b(12|twelve)\b[^.]{0,20}\b(at most|maximum|max)\b",
            PIECE,
        ),
        1,
    ),
    (
        "every_class_starts_with_dk",
        "every class starts with dk-",
        (
            r"\b(every|each|all)\b",
            r"\bclass(es| names?)?\b",
            r"\b(starts?|starting|begins?|beginning|prefix(ed|es)?|carr(y|ies)|uses?)\b",
            DK_CLASS,
        ),
        1,
    ),
    (
        "colours_and_fonts_from_design_tokens",
        "colours and fonts come from the design tokens (var(--…))",
        (
            r"\bcolou?rs?\b",
            r"\bfonts?\b",
            r"\bvar\(",
            r"\b(design )?tokens?\b|\bcustom propert(y|ies)\b|\bdesign_tokens\b",
        ),
        2,
    ),
    (
        "without_a_design_system_a_dk_palette_in_root",
        "without a design system, a small --dk- palette in :root from resolved_style",
        (
            DS_ABSENT,
            r"--dk-",
            r":root\b",
            r"\b(palette|custom propert(y|ies)|variables?)\b",
            r"\bresolved_style\b",
        ),
        2,
    ),
    (
        "no_root_under_a_design_system",
        "no :root when a design system is active",
        (
            rf"({DS_ACTIVE}[^.]{{0,80}}{ROOT_FORBIDDEN}|{ROOT_FORBIDDEN}[^.]{{0,80}}{DS_ACTIVE}"
            rf"|:root\b[^.]{{0,60}}\bonly\b[^.]{{0,40}}{DS_ABSENT})",
        ),
        1,
    ),
    (
        "without_a_design_system_a_ground_piece",
        "R26: without a design system, a ground piece paints the background and base text colour",
        (
            DS_ABSENT,
            r"\bground\b",
            r"\bbackground\b",
            r"\b(text|base) colou?r\b|\bcolou?r of (the )?text\b",
        ),
        2,
    ),
    (
        "each_look_names_the_ground_piece",
        "R26: each slide's look names the ground piece",
        (
            DS_ABSENT,
            r"\bground\b",
            rf"({LOOK}[^.]{{0,60}}\b(names?|uses?|mentions?|includes?)\b[^.]{{0,40}}"
            r"\b(ground|it|that piece|this piece)\b"
            r"|\bnames?\b[^.]{0,40}\b(ground|it|that piece|this piece)\b[^.]{0,40}"
            rf"{LOOK})",
        ),
        2,
    ),
    (
        "each_component_has_name_classes_use_and_example",
        "each component gets a name, its classes, when to use it and example markup",
        (
            CATALOGUE_ENTRY,
            r"\bname\b",
            r"\bclass(es|_names)\b",
            r"\b(when to use|use)\b",
            r"\bexample(_html| markup)?\b",
        ),
        2,
    ),
    (
        "component_classes_are_defined_in_the_css",
        "every component's classes are defined in its css",
        (
            r"\b(component|piece|entry|catalogue)s?\b|\bclass_names\b",
            r"\bdefin(e|es|ed)\b",
            r"\bcss\b",
            r"\bclass(es|_names)?\b",
        ),
        1,
    ),
)

SANITISER_RULES: tuple[Rule, ...] = (
    (
        "each_selector_once",
        "R19: write each selector once",
        (
            r"(\b(each|every)\b[^.]{0,20}\bselector\b[^.]{0,40}\bonce\b"
            r"|\bno (repeated|duplicated?) selectors?\b"
            r"|\b(never|do not|don't|not)\b[^.]{0,20}\b(repeat|duplicate)\b[^.]{0,30}\bselectors?\b"
            r"|\b(never|do not|don't|not)\b[^.]{0,30}\bselectors?\b[^.]{0,20}"
            r"\b(more than once|twice|again)\b"
            r"|\bselectors? (only )?once\b)",
        ),
        1,
    ),
    (
        "every_selector_has_a_top_level_dk_class_then_descendant_or_child",
        "every selector has a top-level .dk- class, with only descendant or > combinators after it",
        (
            r"\bselectors?\b",
            DK_CLASS,
            r"\btop-level\b|\b(not|never) (inside|within)\b",
            r"\bdescendant\b",
            r"(>|\bchild\b)",
        ),
        2,
    ),
    (
        "classes_inside_a_piece_are_allowed",
        "classes inside a piece (token spans like .dk-code .kw) are allowed",
        (
            r"\b(inside|within)\b[^.]{0,20}\b(a |the |that |its )?(piece|component)\b",
            r"\b(token|spans?|kw)\b",
            r"\b(allowed|fine|may|can|need no|needn't|do not need|don't need|ok)\b",
        ),
        1,
    ),
    (
        "no_at_rules",
        "no at-rules (no @media)",
        (_forbids(r"\bat-rules?\b", 25), r"@media\b"),
        1,
    ),
    (
        "no_import_or_font_face",
        "no @import or @font-face",
        (_forbids(r"@import\b", 40), _forbids(r"@font-face\b", 50)),
        1,
    ),
    (
        "url_only_data",
        "no url() except data:",
        (r"\burl\(", r"\bdata:", r"\b(only|except|unless|other than)\b"),
        1,
    ),
    (
        "no_remote_addresses",
        "no remote addresses",
        (
            _forbids(
                r"(\b(remote|external)\b[^.]{0,30}"
                r"\b(address(es)?|urls?|resources?|links?|files?|images?|fonts?)\b|\bhttps?:)",
                40,
            ),
        ),
        1,
    ),
    (
        "no_image_functions",
        "no image functions (image-set, cross-fade ...)",
        (_forbids(r"\b(image functions?|image-set|cross-fade)\b", 30),),
        1,
    ),
    # "no_page_numbers" is retired (Ruling RA4, PLAN-CORRECTIONS-A A19): the owner reversed
    # the section 1 ruling, so the footer piece now carries the page tokens
    # (FOOTER_RULES "footer_piece_holds_both_page_tokens"), and
    # test_the_page_number_ban_is_retired pins that the ban is gone.
)

LOOK_RULES: tuple[Rule, ...] = (
    (
        "every_slide_gets_a_look",
        "write a look for every slide",
        (
            LOOK,
            r"\b(every|each|all)\b[^.]{0,15}\b(slides?|slidespecs?)\b|\bper slide\b",
            r"\b(write|writes|give|gives|get|gets|has|have|carr(y|ies)|needs?|set)\b",
        ),
        1,
    ),
    (
        "look_names_the_body_layout_and_the_pieces",
        "the look names the body's layout and the pieces it uses",
        (
            LOOK,
            r"\b(layout|lay out|laid out|arrangement)\b",
            r"\bbody\b",
            PIECE,
        ),
        1,
    ),
    (
        "look_is_one_or_two_sentences",
        "a look is one or two sentences",
        (LOOK, r"\b(one or two|1-2|1 or 2|one to two) sentences\b|\ba sentence or two\b"),
        1,
    ),
)

BINDING_RULES: tuple[Rule, ...] = (
    (
        "bind_a_section_when_its_shape_fits",
        "bind a section when its shape fits",
        (
            r"\bbind(s|ing)?\b",
            r"\b(sections?|entry|entries)\b",
            r"\b(shape|structure)\b",
            r"\bfits?\b",
        ),
        1,
    ),
    (
        "bind_for_the_frame_only_when_the_body_differs",
        "bind for the frame only when the body differs, and the look describes the body",
        (
            r"\bbind",
            r"(\bfor (its|the|their) frame\b|\bframe only\b|\bonly (for )?(its|the) frame\b"
            r"|\bjust (for )?(its|the) frame\b)",
            r"\b(differs?|different|does not (have|fit)|doesn't (have|fit)|needs a body"
            r"|other body|another body)\b",
            r"\bbody\b",
            LOOK,
        ),
        2,
    ),
    (
        "otherwise_unbound_and_the_look_describes_the_whole_slide",
        "otherwise leave the slide unbound, and the look describes the whole slide",
        (
            r"\bunbound\b|\bno section\b|\bnot bound\b",
            LOOK,
            r"\b(whole|entire|full|in full)\b|\ball of (it|the slide)\b",
        ),
        2,
    ),
)

EDIT_RULES: tuple[Rule, ...] = (
    # Width 1 for these two: at width 2 the shipped prompt's neighbouring bullets (the
    # missing-piece bullet's deck_changes.deck_style beside the contract bullet's "every
    # slide ... deck style", and the m4 bullet's deck_changes.deck_style) satisfied them, so a
    # deck-wide bullet rewritten to "a full deck_spec holding the whole revised style" stayed
    # green (Task 8 review, I1).
    (
        "deck_wide_style_request_is_deck_changes_deck_style",
        "a deck-wide style request is deck_changes.deck_style",
        (
            r"\b(deck-wide|whole-deck|style requests?|restyl\w* (the|a|an|this|your) deck"
            r"|restyl\w* of the (whole )?deck)\b"
            rf"|\bstyle\b[^.]{{0,40}}{DECK_WIDE}|{DECK_WIDE}[^.]{{0,40}}\bstyle\b",
            DECK_CHANGES_STYLE,
        ),
        1,
    ),
    (
        "restyle_carries_the_whole_revised_style",
        "deck_changes.deck_style carries the whole revised style",
        (DECK_CHANGES_STYLE, WHOLE_STYLE),
        1,
    ),
    (
        "no_operations_unless_markup_must_change",
        "no operations unless some slide's markup must change",
        (
            r"\boperations?\b",
            r"\bmarkup\b",
            r"\b(unless|only (if|when|where)|except (when|where|if))\b",
        ),
        2,
    ),
    (
        "restyling_always_goes_through_deck_changes_deck_style",
        "m4: restyling always goes through deck_changes.deck_style",
        (
            DECK_CHANGES_STYLE,
            r"\b(always|only)\b",
            r"\b(restyl\w*|style change|change (to )?the (deck )?style|changing the (deck )?style"
            r"|style request)\b",
        ),
        1,
    ),
    (
        "adding_a_style_to_an_older_deck_is_deck_changes_deck_style",
        "m4: adding a style to an older deck goes through deck_changes.deck_style",
        (
            r"\b(older deck|deck (that )?(has|with) no deck[_ ]style|without a deck[_ ]style"
            r"|has no deck[_ ]style|has none|no deck[_ ]style yet)\b",
            DECK_CHANGES_STYLE,
        ),
        2,
    ),
    (
        "a_full_deck_spec_cannot_change_the_deck_style",
        "m4: a same-contract full-spec answer cannot change the deck style",
        (
            r"\b(full deck_spec|deck_spec|re-descri\w*)\b",
            r"\b(cannot|can't|never|does not|doesn't|will not|won't|not)\b[^.]{0,30}"
            r"\b(change|changes|carry|set|restyle|alter|update)\b",
            DECK_STYLE,
        ),
        1,
    ),
    (
        "keep_class_names_when_only_appearance_changes",
        "keep class names stable when only appearance changes",
        (
            r"\b(keep|keeps|stable|unchanged|same)\b|\b(never|do not|don't) rename\b",
            r"\bclass(es| names?)?\b",
            r"\b(appearance|looks?|colou?rs?)\b",
            r"\bonly\b",
        ),
        1,
    ),
    (
        "dropping_or_renaming_a_used_class_needs_update_operations",
        "dropping or renaming a class a kept slide uses needs update operations for those slides",
        (
            r"\b(drop|drops|dropping|remov\w*|delet\w*)\b",
            r"\brenam\w*",
            r"\bclass(es)?\b",
            r"\bupdate\b",
            r"\b(slides?|it|them)\b[^.]{0,30}\b(uses?|using)\b|\b(uses?|using)\b[^.]{0,20}\bit\b",
            r"\b(same (edit|turn|answer)|refused|rejected)\b",
        ),
        2,
    ),
    (
        "add_a_missing_piece_in_the_same_turn",
        "a slide that needs a missing piece gets it added in the same turn",
        (
            rf"\badd(s|ed|ing)?\b[^.]{{0,40}}{PIECE}|{PIECE}[^.]{{0,60}}\badd(s|ed|ing)?\b",
            r"\b(missing|lacks?|does not have|doesn't have|not (yet )?(in|have)|needs?)\b",
            r"\bsame (turn|edit|answer)\b",
        ),
        1,
    ),
    (
        "a_confirmed_design_contract_change_brings_a_fresh_deck_style",
        "a confirmed design-contract change comes with a fresh deck style",
        (
            r"\bdesign[- ]contract\b|\bdesign system or template\b|\bnew design system\b",
            rf"\b(fresh|new|rewrit\w*|re-?written)\b[^.]{{0,20}}{DECK_STYLE}"
            rf"|{DECK_STYLE}[^.]{{0,20}}\b(afresh|from scratch|anew)\b",
        ),
        2,
    ),
    (
        "an_older_deck_keeps_no_deck_style_unless_asked",
        "an older deck with no deck style keeps none unless the user asks for a style change or a "
        "full rebuild (spec section 5)",
        (
            r"\b(older deck|deck (that )?(has|with) no deck[_ ]style|without a deck[_ ]style"
            r"|has no deck[_ ]style)\b",
            r"\b(keeps? none|keeps? no deck[_ ]style|stays? without"
            r"|leave (it )?(absent|without))\b",
            r"\b(unless|until|only (if|when))\b[^.]{0,40}\b(asks?|requests?)\b",
            r"\bstyle change\b|\brestyl\w*",
            r"\b(full )?rebuild\b",
        ),
        1,
    ),
)

RULES: tuple[Rule, ...] = BUILD_RULES + SANITISER_RULES + LOOK_RULES + BINDING_RULES + EDIT_RULES


# ---------------------------------------------------------------------------
# Addendum A (Task B5a): footer, page tokens, logos, icon intent, one ground
# ---------------------------------------------------------------------------

FOOTER = r"\bfooters?\b"
#: The footer piece: "footer piece", "the component ... footer", or a dk- footer class
#: (dk-footer, .dk-slide-footer).
FOOTER_PIECE = (
    r"(\bfooter (piece|component)s?\b|(?<![\w-])\.?dk-[\w-]*footer\b"
    r"|\b(piece|component)s?\b[^.]{0,30}\bfooter\b)"
)
#: The eval scorer's definition of a footer piece (PLAN-CORRECTIONS-A A17): a component
#: whose name or class names contain "footer".  A dk- footer class (every class starts
#: with dk-) or the definition said in words.
FOOTER_NAMED = (
    r"((?<![\w-])\.?dk-[\w-]*footer\b"
    r"|\b(name|names|class(es| names?|_names)?)\b[^.]{0,30}\b(contains?|includes?|with)\b"
    r"[^.]{0,15}\bfooter\b"
    r"|\b(named|called)\b[^.]{0,15}\bfooter\b)"
)
#: Where the logo handles come from: the payload's deck_style_context.logos.
LOGOS_SOURCE = (
    r"(\bdeck_style_context\.logos\b"
    r"|\b(from|in|among|of)\s+(the\s+)?(payload's\s+)?(deck_style_context's\s+)?logos\b)"
)
NUMBER_TOKEN = r"\{\{slide:number\}\}"
COUNT_TOKEN = r"\{\{slide:count\}\}"
PAGE_TOKEN = r"\{\{slide:(number|count)\}\}"
LIGHT_GROUND = r"\blight (grounds?|slides?|backgrounds?|sections?)\b"
DARK_SLIDES = r"\bdark (slides?|sections?|grounds?|backgrounds?)\b|\bdividers?\b"
#: The light-on-dark logo variant: "light-on-dark", "the reverse logo", "the light logo".
LIGHT_ON_DARK = (
    r"(\blight-on-dark\b|\bon-dark\b"
    r"|\b(reverse[ds]?|white|knock-?out|inverse|negative|light) (logo|mark|variant|version|one"
    r"|lockup)s?\b)"
)
#: "look" or "looks" (the plural reads "looks state icon intent").
LOOKS = r"(?<![\w-])looks?(?![\w-])"
ICON = r"\bicons?\b"
#: Naming an icon: "an icon handle", "the icon's handle", "handles for icons", "pick icons".
ICON_HANDLE = (
    r"(\bicons?('s|s')? (handles?|ids?)\b|\bhandles? (for|of) (an |the |any )?icons?\b"
    r"|\b(pick|picks|choose|chooses|select|selects)\b[^.;]{0,10}\bicons?\b)"
)

#: The retired Task 8 ban ("no page numbers"): its needle, kept to prove the ban is gone.
PAGE_NUMBERS = (
    r"(\bpage numb(ers?|ering)\b|\bnumber(s|ing)? (the )?(pages|slides)\b"
    r"|\b(page|slide) (counters?|numbers? (in|on) (the |a )?footer)\b|\bn / n\b)"
)
PAGE_NUMBER_BAN = _forbids(PAGE_NUMBERS, 30)

FOOTER_RULES: tuple[Rule, ...] = (
    (
        "deck_style_always_has_a_footer_piece",
        "the deck style always includes a footer piece",
        (DECK_STYLE, r"\balways\b|\bevery deck[_ ]style\b", FOOTER_PIECE),
        1,
    ),
    (
        "footer_piece_is_named_footer",
        'A17: the footer piece\'s name or class names contain "footer" (dk-footer)',
        (FOOTER_PIECE, FOOTER_NAMED),
        1,
    ),
    (
        "footer_piece_holds_both_page_tokens",
        "RA4: the footer piece holds both page tokens, {{slide:number}} and {{slide:count}} "
        "(replaces the retired no_page_numbers)",
        (
            FOOTER,
            NUMBER_TOKEN,
            COUNT_TOKEN,
            r"\b(hold|holds|holding|carr(y|ies|ying)|include|includes|including|contain"
            r"|contains|containing|has|have|with|show|shows|showing|put|puts)\b",
        ),
        2,
    ),
    (
        "footer_piece_holds_logo_handles_from_logos",
        "the footer piece holds the logo handle(s) chosen from deck_style_context.logos",
        (FOOTER, r"\blogos?\b", r"\bhandles?\b", LOGOS_SOURCE),
        2,
    ),
    # Width 1: at width 2 the one-ground sentence ("default light ground; dark sections
    # ... stay dark") beside the footer sentence ("logo", "two footers") satisfied it with
    # the light-ground logo clause deleted (B5a scratch sabotage).
    (
        "two_logos_one_for_light_grounds_one_for_dark",
        "Q3: two logo handles, one for light grounds and one for dark slides",
        (
            r"\blogos?\b",
            LIGHT_GROUND,
            DARK_SLIDES,
            r"\b(two|both|one|pair|second|other)\b",
        ),
        1,
    ),
    (
        "dark_slides_use_the_light_on_dark_logo",
        "Q3: dark slides (dividers, closing) use the light-on-dark logo",
        (
            DARK_SLIDES,
            LIGHT_ON_DARK,
            r"\b(use|uses|using|for|on|carr(y|ies)|gets?|takes?)\b",
        ),
        1,
    ),
    (
        "every_slide_except_the_cover_carries_a_footer",
        "every slide except the cover carries a footer",
        (
            r"\b(every|each|all)\b[^.]{0,20}\bslides?\b",
            r"(\b(except|but|other than|apart from|save|besides)\b[^.]{0,15}\bcover\b"
            r"|\bcover\b[^.]{0,40}\b(no|without|not)\b[^.]{0,20}\bfooter\b"
            r"|\bnot (on )?the cover\b)",
            FOOTER,
        ),
        1,
    ),
    (
        "a_bound_slide_fills_its_template_footer",
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
        "an_unbound_slide_uses_the_footer_piece",
        "Q1: an unbound slide uses the deck style's footer piece",
        (
            r"\bunbound\b|\bnot bound\b|\bno section\b|\bwithout a (bound )?section\b",
            FOOTER_PIECE,
            r"\b(use|uses|using|carr(y|ies)|gets?|takes?|cop(y|ies)|place|places)\b",
        ),
        1,
    ),
    (
        "never_two_footers",
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
)

ICON_RULES: tuple[Rule, ...] = (
    (
        "looks_state_icon_intent",
        'a look states icon intent ("an icon on each box")',
        (
            LOOKS,
            ICON,
            r"\b(intent|state|states|stating|say|says|ask|asks|asking|describe|describes|want"
            r"|wants|call for|calls for|request|requests)\b",
        ),
        1,
    ),
    (
        "looks_never_name_icon_handles",
        "a look never names an icon handle",
        (LOOKS, _forbids(ICON_HANDLE, 40)),
        2,
    ),
    (
        "builders_search_for_icons_themselves",
        "builders search the design system for icons themselves",
        (
            r"\bbuilders?\b",
            r"\b(search|searches|searching|find|finds|look up|looks up|fetch|fetches)\b",
            ICON,
        ),
        2,
    ),
)

GROUND_RULES: tuple[Rule, ...] = (
    (
        "content_slides_share_the_default_light_ground",
        "one ground: content slides share the deck's default light ground",
        (
            r"\bcontent slides?\b",
            r"\bground\b",
            r"\b(default|light)\b",
            r"\b(share|shares|same|one|single|all|every)\b|\bdeck's\b",
        ),
        1,
    ),
    (
        "dark_sections_stay_dark",
        "dark sections (cover, dividers) stay dark",
        (
            r"\b(cover|covers|dividers?|closing)\b",
            r"(\b(stay|stays|remain|remains|keep|keeps|kept|left)\b[^.]{0,20}\bdark\b"
            r"|\bdark\b[^.]{0,20}\b(stay|stays|remain|remains|unchanged)\b)",
        ),
        2,
    ),
)

ADDENDUM_A_RULES: tuple[Rule, ...] = FOOTER_RULES + ICON_RULES + GROUND_RULES


# ---------------------------------------------------------------------------
# The new rules (red until the deck-style prompt is promoted)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule_id", "description", "needles", "width"), RULES, ids=[r[0] for r in RULES]
)
def test_architect_prompt_states_deck_style_rule(rule_id, description, needles, width):
    assert _holds(_instructions(), needles, width), f"architect prompt lacks: {description}"


@pytest.mark.parametrize(
    ("rule_id", "description", "needles", "width"),
    ADDENDUM_A_RULES,
    ids=[r[0] for r in ADDENDUM_A_RULES],
)
def test_architect_prompt_states_addendum_a_rule(rule_id, description, needles, width):
    assert _holds(_instructions(), needles, width), f"architect prompt lacks: {description}"


def _page_number_bans(text: str) -> list[str]:
    """Clauses that forbid page numbers outright.

    Two kinds of clause are not the retired ban: one with a page token in the same clause
    ("never type a page number yourself; write {{slide:number}}"), and one that exempts the
    cover ("the cover carries no page number").  A token in a neighbouring clause does not
    excuse a ban: "Never add page numbers to a slide." beside the token sentence still
    contradicts it (B5a review mutation d2).
    """
    return [
        clause
        for clause in _clauses(text)
        if re.search(PAGE_NUMBER_BAN, clause)
        and not (re.search(PAGE_TOKEN, clause) or re.search(r"\bcover\b", clause))
    ]


@pytest.mark.parametrize(
    ("text", "banned"),
    [
        # A ban next to the token sentence is still a ban (review mutation d2).
        (
            "Its example_html holds {{slide:number}} / {{slide:count}}, so they stay right when "
            "slides move. Never add page numbers to a slide. When template_classes has a footer.",
            True,
        ),
        ("No page numbers on any slide.", True),
        ("Never type a page number yourself; write {{slide:number}} instead.", False),
        ("The cover carries no page number.", False),
        ("A footer piece gains one only when the user asks for page numbers.", False),
    ],
)
def test_page_number_ban_detector(text, banned):
    assert bool(_page_number_bans(text)) is banned


def test_the_page_number_ban_is_retired():
    # Ruling RA4 / A19: the owner reversed the section 1 ruling.  Task 8's sentence ("No page
    # numbers: ... a footer piece may style the footer but never numbers the slides") is
    # gone, and no other clause bans page numbers outright.
    plain = _plain(_instructions())
    assert "no page numbers:" not in plain, "the retired 'No page numbers:' rule is still stated"
    assert "never numbers the slides" not in plain, (
        "the prompt still says the footer piece never numbers the slides"
    )
    bans = _page_number_bans(_instructions())
    assert not bans, f"the prompt still bans page numbers: {bans}"


def test_slidespec_fields_list_look():
    block = _one_paragraph(_instructions(), "SLIDESPEC FIELDS")
    assert len(_field_line_indexes(block, "look")) == 1, (
        "SLIDESPEC FIELDS must list exactly one `look:` line"
    )


def test_deckspec_construction_lists_deck_style_after_slides():
    # C25: the seven existing field lines stay directly under the heading
    # (test_deckspec_heading_covers_build_and_edit), so `deck_style:` follows `slides:`.
    block = _one_paragraph(_instructions(), DECKSPEC_HEADING)
    deck_style = _field_line_indexes(block, "deck_style")
    slides = _field_line_indexes(block, "slides")
    assert len(deck_style) == 1, "DECKSPEC CONSTRUCTION must list exactly one `deck_style:` line"
    assert len(slides) == 1 and deck_style[0] > slides[0], (
        "the `deck_style:` line must come after `slides:`"
    )


def test_deck_changes_field_list_names_deck_style():
    # The EDITING sentence that lists the deck_changes fields must not read as an
    # exhaustive list without deck_style.
    lead = "put only the changed fields in deck_changes"
    clauses = [c for c in _clauses(_instructions()) if lead in c]
    assert len(clauses) == 1, (
        f"expected one clause listing the deck_changes fields, found {len(clauses)}"
    )
    assert re.search(r"\bdeck_style\b", clauses[0]), (
        f"the deck_changes field list does not name deck_style: {clauses[0]!r}"
    )


# ---------------------------------------------------------------------------
# Today's pinned architect prompt survives (green before and after the change)
# ---------------------------------------------------------------------------

#: sha256 of repr((DECKSPEC_HEADING, HEAD_DECKSPEC_FIELD_LINES, HEAD_SLIDESPEC_FIELD_LINES,
#: EDITING_RULE_PHRASES, EDITING_GUARD_PHRASES, DESIGN_SYSTEMS_CONTRACT_PHRASES)) of
#: tests/unit/test_architect_edit_prompt.py at HEAD 458187fd (the file last changed in
#: 3eeb5fe5).  C25: Task 8 must make the new prompt keep these, not edit them.
C25_SURVIVING_PINS_DIGEST = "b7d1b9150b3b5a66dc9879952e7c479c61d6e888a8d4e4e1943da11c70996a40"


def test_c25_surviving_pins_are_untouched():
    digest = hashlib.sha256(
        repr(
            (
                DECKSPEC_HEADING,
                HEAD_DECKSPEC_FIELD_LINES,
                HEAD_SLIDESPEC_FIELD_LINES,
                EDITING_RULE_PHRASES,
                EDITING_GUARD_PHRASES,
                DESIGN_SYSTEMS_CONTRACT_PHRASES,
            )
        ).encode()
    ).hexdigest()
    assert digest == C25_SURVIVING_PINS_DIGEST, (
        "tests/unit/test_architect_edit_prompt.py's C25 pins changed; the deck-style prompt "
        "must keep them as they are (PLAN-CORRECTIONS C25)"
    )


@pytest.mark.parametrize("line", HEAD_SLIDESPEC_FIELD_LINES)
def test_slidespec_field_line_survives_verbatim(line):
    block = _one_paragraph(_instructions(), "SLIDESPEC FIELDS")
    assert line in block.splitlines(), f"SLIDESPEC FIELDS line lost or reworded: {line!r}"


def test_deckspec_field_lines_stay_directly_under_the_heading():
    assert f"{DECKSPEC_HEADING}\n{HEAD_DECKSPEC_FIELD_LINES}" in _instructions()


@pytest.mark.parametrize("phrase", EDITING_RULE_PHRASES + EDITING_GUARD_PHRASES)
def test_editing_phrase_survives(phrase):
    assert phrase in _plain(_one_paragraph(_instructions(), "EDITING")), (
        f"EDITING block lacks {phrase!r}"
    )


@pytest.mark.parametrize("phrase", DESIGN_SYSTEMS_CONTRACT_PHRASES)
def test_design_systems_contract_phrase_survives(phrase):
    assert phrase in _plain(_one_paragraph(_instructions(), "DESIGN SYSTEMS")), (
        f"DESIGN SYSTEMS block lacks {phrase!r}"
    )


# Copied by hand from tests/unit/test_skill_prose.py TestArchitectProse (C25).
ARCHITECT_PROSE = (
    "14 to 20 slides",
    "reusable layouts, not a one-of-each menu",
    "its slide_type must equal the label of the template_sections entry",
)


@pytest.mark.parametrize("phrase", ARCHITECT_PROSE)
def test_architect_prose_survives(phrase):
    assert phrase in _instructions()


def test_never_bind_a_merely_similar_section_survives():
    # Spec section 2: "The existing rule against binding a merely similar section stays."
    block = _plain(_one_paragraph(_instructions(), "VISUAL / TEMPLATE BINDING"))
    assert "never bind a merely similar section" in block
