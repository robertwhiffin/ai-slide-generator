"""Prompt contract: the fix reviewer judges fixes against the architect's deck style.

Plan Task 10 (architect deck style), as overridden by Ruling R10 (correction C27,
option c) and corrections C26/C28.  Spec:
docs/superpowers/specs/2026-10-29-architect-deck-style-design.md.

The fix reviewer's payload carries ``deck_style`` = ``{css, components}`` beside
``section_css`` when the deck has an architect-written style.  Its authored prompt
(``src/core/skills/fix_reviewer.py``) gains a ``DECK STYLE`` block.  These tests pin
the RULES in that block, not its wording:

* the text is whitespace-collapsed, lower-cased and stripped of backticks
  (``_plain``, shared with test_builder_deck_style_prompt.py);
* the block runs from its one ``DECK STYLE`` heading line (a ``5. `` number in front
  is allowed) to the next upper-case heading paragraph (``VERDICT RULES:``,
  ``IMPORTANT:``, ...), or to the end of the prompt;
* the block is cut into clauses: sentences and bullet items.  A rule's core needles
  must all match inside ONE clause, in any order.  Its consequence ("counts against
  the fix", "report it as rogue_colour") must sit in that same clause; only the
  cascade rule lets its "judge the cascade" sit in a neighbouring clause.  So a rule
  must be stated locally, but it may be reworded freely.

The rules (when the payload carries a ``deck_style``):

* the colours of the deck style's pieces are part of the contract;
* a fix that paints colours, backgrounds or font sizes inline counts against it;
* a fix that restyles a piece the deck style provides counts against it;
* the cascade is judged with the deck style's CSS applied after ``section_css``;
* the block applies only when the payload carries a ``deck_style``.

One negative pin: nothing in the block permits inline paint.

Guards that are green today and must stay green:

* the fix reviewer's existing rules still hold with the block cut out, and its
  VALID CRITERION NAMES list keeps today's names and names only registry criteria
  (the criteria registry does not change in Task 10);
* the promoted manifest's fix_reviewer prompt is the skill's ``INSTRUCTIONS``;
* Ruling R10: the BUILD reviewer is unchanged.  Its v1 composite and v2 authored
  target carry no deck-style text and are byte-identical to HEAD, its packaged
  definition hash is HEAD's, and ``src/services/prompt_assembler.py`` imports cleanly
  with HEAD's ``_V1_DIGEST`` / ``_V2_DIGEST`` (the v2 digest hashes both transition
  prompts, so an edited build-reviewer prompt raises at import).

Every hash literal below is a HEAD (851e9f39) value copied by hand; do not import them
from the code under test.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

import src.core.database  # noqa: F401  (must be imported before other src.* modules)
from src.core.skills import load_skill
from src.domain.finding import CRITERIA
from src.services.graph_definition_manifest import (
    definition_content_hash,
    load_graph_v1_manifest,
)
from tests.unit.test_builder_deck_style_prompt import (
    BACKGROUND,
    COLOUR,
    FONT_SIZE,
    NEG,
    _clauses,
    _deck_style_span,
    _plain,
    _without_deck_style_block,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Text helpers (pure: they take the prompt text, so a candidate prompt can be checked
# without importing it)
# ---------------------------------------------------------------------------


def _block(instructions: str) -> str:
    span = _deck_style_span(instructions)
    assert span is not None, "fix reviewer prompt has no DECK STYLE block"
    return instructions[span[0] : span[1]]


def _holds(
    plain_text: str,
    core: tuple[str, ...],
    consequence: tuple[str, ...] = (),
    width: int = 1,
) -> bool:
    """True when one clause matches every ``core`` needle and that clause matches every
    ``consequence`` needle; with ``width=2``, the clause joined with a neighbouring
    clause may match the consequence instead."""
    clauses = _clauses(plain_text)
    for i, clause in enumerate(clauses):
        if not all(re.search(n, clause) for n in core):
            continue
        windows = [clause]
        if width >= 2:
            windows += [
                " ".join(clauses[j : j + 2]) for j in (i - 1, i) if 0 <= j < len(clauses) - 1
            ]
        if any(all(re.search(n, w) for n in consequence) for w in windows):
            return True
    return False


# ---------------------------------------------------------------------------
# Needles
# ---------------------------------------------------------------------------

PIECE = r"(piece|component)"

#: The fix is held against the rule: "counts against the fix", "report it as
#: rogue_colour", "re-report", "not fixed", ...
AGAINST = (
    r"(counts? against|against (the|this|that) fix|rogue_colou?r|re-?report|\breport"
    r"|\bflag|new finding|not (fixed|clean|resolved|addressed)|surfaced|reject|violat)"
)

#: "is/are part of the contract", "do not report them as rogue_colour", "are allowed".
#: "not part of the contract" does not count, and adjacency (``\s+``) keeps "are not
#: allowed" from counting either.
IN_CONTRACT = (
    r"((?<!not )(?<!never )\b(part of|within|inside|belong\w* to|in)\s+(the\s+)?"
    r"(slide'?s\s+|deck'?s\s+|resolved\s+|colou?r\s+)?contract"
    r"|(do not|don't|never|not)\s+(\w+\s+)?(report|flag|count|treat)\w*.{0,80}"
    r"(rogue_colou?r|finding|violation)"
    r"|\b(is|are)\s+not\s+(a\s+|an\s+)?(rogue_colou?r|finding|violation)"
    r"|\b(is|are)\s+(allowed|permitted|legitimate|expected|approved|sanctioned))"
)

RESTYLE = r"(restyl|re-styl|recolou?r|repaint|overrid|alter|chang|modif|rework|edit)"

#: The deck style's CSS comes after section_css in the cascade, in either word order.
#: Clauses are cut at ". " only, so ``.`` gaps inside one clause stay in the sentence
#: (they let ``deck_style.css`` through).
DECK_CSS_AFTER_SECTION_CSS = (
    r"(deck[ _]style|deck_style).{0,60}\b(after|on top of|over|later than|following)\b"
    r".{0,30}section_css"
    r"|section_css.{0,60}\b(then|before|first|followed by|beneath|under|earlier than)\b"
    r".{0,60}(deck[ _]style|deck_style)"
    r"|(deck[ _]style|deck_style).{0,60}\b(overrides?|wins over|takes precedence over"
    r"|outranks)\b.{0,30}section_css"
)

CASCADE = r"(cascade|computed|render)"

#: A presence condition on deck_style: "when deck_style is present", "if the payload
#: carries deck_style", "only when ... deck_style".
PRESENT = (
    r"(when|if|with)[^:.]{0,40}(deck_style[^:.]{0,30}(present|provided|supplied|non-empty"
    r"|not empty|given|set|carried)|(carries|has|includes|contains)[^:.]{0,20}deck_style)"
)

#: (id, core needles, consequence needles, consequence width).  See ``_holds``.
Rule = tuple[str, tuple[str, ...], tuple[str, ...], int]

RULES: tuple[Rule, ...] = (
    (
        "the colours of the deck style's pieces are part of the contract",
        (r"(piece|component|deck[ _]style|deck_style)", COLOUR, IN_CONTRACT),
        (),
        1,
    ),
    (
        "a fix that paints colours, backgrounds or font sizes inline counts against it",
        (r"inline", COLOUR, BACKGROUND, FONT_SIZE),
        (AGAINST,),
        1,
    ),
    (
        "a fix that restyles a piece the deck style provides counts against it",
        (RESTYLE, PIECE, r"(deck[ _]style|deck_style|provid|ship|defin|catalog)"),
        (AGAINST,),
        1,
    ),
    (
        "judge the cascade with the deck style's CSS applied after section_css",
        (DECK_CSS_AFTER_SECTION_CSS,),
        (CASCADE,),
        2,
    ),
)

#: A permission for inline paint: "inline colour is fine", "you may use inline
#: background", "a fix may paint colours ... inline".  A match whose text (plus the 30
#: characters before it) holds a negation ("is not allowed", "never acceptable",
#: "cannot use") is a ban, not a permission.
_INLINE_PAINT_PERMISSION = re.compile(
    r"inline[^.;]{0,40}(colou?r|background|font)[^.;]{0,60}"
    r"\b(permitted|allowed|fine|ok|acceptable)\b"
    r"|\b(may|can)\b[^.;]{0,20}\b(use|add|set|keep|paint|apply)\b[^.;]{0,20}inline[^.;]{0,40}"
    r"(colou?r|background|font)"
    r"|\b(may|can)\b[^.;]{0,20}\b(use|add|set|keep|paint|apply)\b[^.;]{0,20}"
    r"(colou?r|background|font)[^.;]{0,40}\binline\b"
)
_PERMISSION_NEG = NEG + r"|cannot|can't"


def _fix_reviewer() -> str:
    return load_skill("fix_reviewer").instructions


def _rule_holds(
    instructions: str, core: tuple[str, ...], consequence: tuple[str, ...], width: int
) -> bool:
    return _holds(_plain(_block(instructions)), core, consequence, width)


def _is_conditioned_on_deck_style(instructions: str) -> bool:
    """The heading, or the block's first clause, scopes the block to a present deck_style."""
    block = _block(instructions)
    heading = _plain(block.splitlines()[0])
    body = _plain("\n".join(block.splitlines()[1:]))
    first_clause = (_clauses(body) or [""])[0]
    return bool(re.search(PRESENT, heading) or re.search(PRESENT, first_clause))


def _inline_paint_permissions(instructions: str) -> list[str]:
    block = _plain(_block(instructions))
    found = []
    for m in _INLINE_PAINT_PERMISSION.finditer(block):
        context = block[max(0, m.start() - 30) : m.end()]
        if not re.search(_PERMISSION_NEG, context):
            found.append(context)
    return found


# ---------------------------------------------------------------------------
# The DECK STYLE block exists, names deck_style, and is scoped to it (red at HEAD)
# ---------------------------------------------------------------------------


def test_fix_reviewer_has_one_deck_style_block_naming_deck_style():
    block = _block(_fix_reviewer())
    assert re.match(r"(\d+\.\s*)?deck style\b", _plain(block.splitlines()[0]))
    assert "deck_style" in _plain(block), "the DECK STYLE block never names deck_style"


def test_deck_style_block_applies_only_when_the_payload_carries_deck_style():
    assert _is_conditioned_on_deck_style(_fix_reviewer()), (
        "neither the DECK STYLE heading nor its first clause says the block applies "
        "when the payload carries deck_style"
    )


@pytest.mark.parametrize(("rule", "core", "consequence", "width"), RULES, ids=[r[0] for r in RULES])
def test_deck_style_block_states_rule(rule, core, consequence, width):
    assert _rule_holds(_fix_reviewer(), core, consequence, width), (
        f"fix reviewer DECK STYLE block lacks: {rule}"
    )


def test_deck_style_block_never_permits_inline_paint():
    found = _inline_paint_permissions(_fix_reviewer())
    assert found == [], f"fix reviewer DECK STYLE block permits inline paint: {found}"


# ---------------------------------------------------------------------------
# The fix reviewer's existing rules are untouched (green before and after)
# ---------------------------------------------------------------------------

#: Today's rules, as plain-text regexes over the prompt with the block cut out.
FIX_REVIEWER_TODAY_RULES = (
    (
        "check the reported finding was addressed; re-report it if it persists",
        r"check whether the specific finding was addressed\. if the corrected html still "
        r"exhibits the same issue, re-report it",
    ),
    (
        "a changed claim or content is brief_not_delivered",
        r"now makes a different claim or has different content than the original, this is "
        r"a brief_not_delivered violation",
    ),
    (
        "the fix changes only what the finding requires",
        r"the fix should change only what the finding requires",
    ),
    (
        "unrelated content, messaging or styling changes are a new finding",
        r"altered content, messaging or styling unrelated to the finding, report it as a "
        r"new finding",
    ),
    ("verdict clean", r"clean → no remaining findings"),
    (
        "verdict fixed",
        r"fixed → the original finding was resolved and no new findings are present",
    ),
    ("verdict surfaced", r"surfaced → new findings are present"),
    (
        "a fixed verdict has an empty findings list",
        r'when verdict is "fixed", your findings list must be empty',
    ),
)


@pytest.mark.parametrize(
    ("description", "pattern"),
    FIX_REVIEWER_TODAY_RULES,
    ids=[d for d, _ in FIX_REVIEWER_TODAY_RULES],
)
def test_todays_fix_reviewer_rules_hold_outside_the_deck_style_block(description, pattern):
    outside = _plain(_without_deck_style_block(_fix_reviewer()))
    assert re.search(pattern, outside), (
        f"fix reviewer prompt outside the DECK STYLE block lacks today's rule: {description}"
    )


#: The fix reviewer's VALID CRITERION NAMES at HEAD.
HEAD_FIX_REVIEWER_CRITERION_NAMES = (
    "overflow",
    "contrast_failure",
    "rogue_colour",
    "distorted_image",
    "source_contradiction",
    "brief_not_delivered",
    "arc_gap",
    "cross_slide_repetition",
    "missing_conclusion",
)


def _valid_criterion_names(instructions: str) -> list[str]:
    paragraphs = [p for p in instructions.split("\n\n") if p.startswith("VALID CRITERION NAMES")]
    assert len(paragraphs) == 1, f"expected one VALID CRITERION NAMES paragraph: {paragraphs}"
    return re.findall(r"^\s*-\s*([a-z_]+)\s*$", paragraphs[0], re.MULTILINE)


def test_valid_criterion_names_keep_todays_names_and_name_only_registry_criteria():
    names = _valid_criterion_names(_fix_reviewer())
    missing = [n for n in HEAD_FIX_REVIEWER_CRITERION_NAMES if n not in names]
    assert missing == [], f"VALID CRITERION NAMES dropped: {missing}"
    invented = [n for n in names if n not in CRITERIA]
    assert invented == [], f"VALID CRITERION NAMES lists non-registry criteria: {invented}"


def test_criteria_named_in_the_deck_style_block_are_valid_criterion_names():
    """Vacuous until the block exists; then it may report only listed criteria."""
    instructions = _fix_reviewer()
    span = _deck_style_span(instructions)
    block = instructions[span[0] : span[1]] if span else ""
    valid = set(_valid_criterion_names(instructions))
    unlisted = sorted(
        name for name in CRITERIA if re.search(rf"\b{name}\b", block) and name not in valid
    )
    assert unlisted == [], f"DECK STYLE block names criteria the prompt does not list: {unlisted}"
    # A name the block tells the model to report must be a listed criterion, even one
    # outside the registry (``Finding`` rejects an unknown criterion at runtime).
    reported = re.findall(r"\breport\s+(?:it|them)\s+as\s+([a-z_]+)", _plain(block))
    unknown = sorted({name for name in reported if name not in valid})
    assert unknown == [], f"DECK STYLE block reports unlisted criterion names: {unknown}"


def test_manifest_fix_reviewer_prompt_is_the_skill_instructions():
    """``promote`` writes the manifest; the skill body must match it."""
    from src.core.skills.fix_reviewer import INSTRUCTIONS

    manifest = load_graph_v1_manifest()
    fix_reviewer = next(d for d in manifest.definitions if d.agent_key == "fix_reviewer")
    assert fix_reviewer.prompt_text == INSTRUCTIONS == _fix_reviewer()


# ---------------------------------------------------------------------------
# Ruling R10: the build reviewer is NOT changed (green before and after)
# ---------------------------------------------------------------------------

HEAD_BUILD_REVIEWER_V1_PROMPT_SHA256 = (
    "31172924f92d36d4c4bd6ad2f93571750754dfe47da241846a7085a0f61d918e"
)
HEAD_BUILD_REVIEWER_AUTHORED_INSTRUCTIONS_SHA256 = (
    "357f4093b9fefd318a5dabf75ce3229b67496463d1cb1c8073db9f6b7c25e40d"
)
HEAD_BUILD_REVIEWER_CONTENT_HASH = (
    "0a8f6a7c6ef13c1acd89960f44a0eaa57ea2e7b1074a1ec191654229d268461f"
)
HEAD_V1_PROTECTED_DIGEST = "e4ff3d6197ea926de2a4b7445c57a1d8b7cb906453ad76345ffd0666a0976852"
HEAD_V2_PROTECTED_DIGEST = "cb940ea3b990e12483eb660aca60f624e45711f4bcde6679ea928ae3391d3854"
HEAD_HISTORICAL_V2_DIGESTS = (
    "fb651a0d28276a0daf7b0db09f2648eb6b50d9429a7100cfaf69e3fc2b08592a",
    "4e9e32ab3554202474ec4ebae486f6007b4c455a5cef78341d0f1e9ba200b41d",
)

_DECK_STYLE_TEXT = re.compile(r"deck[ _-]?style", re.IGNORECASE)


def _build_reviewer_prompts() -> dict[str, str]:
    from src.core.skills.build_reviewer import (
        BUILD_REVIEWER_AUTHORED_INSTRUCTIONS,
        DECK_BRIEF_REVIEW,
        build_instructions,
    )

    manifest = load_graph_v1_manifest()
    packaged = next(d for d in manifest.definitions if d.agent_key == "build_reviewer")
    return {
        "load_skill('build_reviewer').instructions": load_skill("build_reviewer").instructions,
        "BUILD_REVIEWER_AUTHORED_INSTRUCTIONS": BUILD_REVIEWER_AUTHORED_INSTRUCTIONS,
        "build_instructions()": build_instructions(),
        "DECK_BRIEF_REVIEW": DECK_BRIEF_REVIEW,
        "packaged build_reviewer prompt_text": packaged.prompt_text,
    }


BUILD_REVIEWER_PROMPT_NAMES = (
    "load_skill('build_reviewer').instructions",
    "BUILD_REVIEWER_AUTHORED_INSTRUCTIONS",
    "build_instructions()",
    "DECK_BRIEF_REVIEW",
    "packaged build_reviewer prompt_text",
)


@pytest.mark.parametrize("name", BUILD_REVIEWER_PROMPT_NAMES)
def test_build_reviewer_prompts_carry_no_deck_style_text(name):
    text = _build_reviewer_prompts()[name]
    assert not _DECK_STYLE_TEXT.search(text), (
        f"{name} mentions the deck style; Ruling R10 leaves the build reviewer unchanged"
    )


def test_build_reviewer_prompts_are_byte_identical_to_head():
    from src.core.skills.build_reviewer import BUILD_REVIEWER_AUTHORED_INSTRUCTIONS

    def sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    assert sha(load_skill("build_reviewer").instructions) == HEAD_BUILD_REVIEWER_V1_PROMPT_SHA256
    assert sha(BUILD_REVIEWER_AUTHORED_INSTRUCTIONS) == (
        HEAD_BUILD_REVIEWER_AUTHORED_INSTRUCTIONS_SHA256
    )


def test_packaged_build_reviewer_definition_is_unchanged():
    manifest = load_graph_v1_manifest()
    packaged = next(d for d in manifest.definitions if d.agent_key == "build_reviewer")
    assert definition_content_hash(packaged) == HEAD_BUILD_REVIEWER_CONTENT_HASH


def test_protected_assembly_digests_are_heads_and_v2_recomputes():
    from src.services import prompt_assembler

    assert prompt_assembler._V1_DIGEST == HEAD_V1_PROTECTED_DIGEST
    assert prompt_assembler._V2_DIGEST == HEAD_V2_PROTECTED_DIGEST
    assert prompt_assembler._HISTORICAL_V2_DIGESTS == HEAD_HISTORICAL_V2_DIGESTS
    assert prompt_assembler.protected_assembly_v2_digest() == HEAD_V2_PROTECTED_DIGEST


def test_prompt_assembler_imports_cleanly_in_a_fresh_interpreter():
    """The ``_V2_DIGEST`` check runs at import, once per process; a fresh interpreter
    re-runs it whatever this session already imported."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import src.services.prompt_assembler as m; print(m._V1_DIGEST, m._V2_DIGEST)",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.split() == [HEAD_V1_PROTECTED_DIGEST, HEAD_V2_PROTECTED_DIGEST]
