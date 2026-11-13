"""The stage policy separates a kind of element across the deck from one slide's content (I2).

Whole-branch review I2: the STAGE SLIDE block told the architect that an edit naming no slide
means the stage slide, while DECK STYLE says an unqualified style request about a kind of element
("make the code blocks dark", "bigger table text") is deck-wide (``deck_changes.deck_style``).
With a slide on stage on nearly every Agent turn, the two compete. The shipped policy must say
which wins:

* a request about a kind of element across the deck (code blocks, tables, fonts...) stays
  deck-wide even when a slide is on stage, and is not narrowed to the stage slide;
* an edit of one slide's own content that names no slide (its title, its bullets) is the edit
  that defaults to the stage slide.

Literal-text checks over the authored prompt and the packaged manifest prompt, inside the blocks
that name ``stage_slide``. They prove the policy SHIPS, not that a live model follows it; the
Stage Slide eval cases (``evals/packs/architect/stage_cases.py``) measure that.
"""
from __future__ import annotations

import re

import pytest

import src.core.database  # noqa: F401  (break import cycle before src.services.*)


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("`", "")).strip().lower()


def _stage_text(prompt: str) -> str:
    """Every ``\\n\\n`` block of *prompt* that names ``stage_slide``, joined, plain."""
    blocks = [block for block in prompt.split("\n\n") if "stage_slide" in block]
    assert blocks, "the architect instructions never mention stage_slide"
    return _plain(" ".join(blocks))


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;])\s+", text) if s]


def _authored() -> str:
    from src.core.skills.architect import INSTRUCTIONS

    return INSTRUCTIONS


def _packaged() -> str:
    from src.services.graph_definition_manifest import load_graph_v1_manifest

    manifest = load_graph_v1_manifest()
    return next(d for d in manifest.definitions if d.agent_key == "architect").prompt_text


SOURCES = {"authored": _authored, "packaged": _packaged}

_KIND = (
    r"\b(kinds? of (element|thing|piece|content)s?|type of element"
    r"|every [a-z ]{0,20}(block|listing|table|chart|font|heading|title)s?)\b"
)
_ELEMENT_EXAMPLE = r"\b(code (block|listing)s?|tables?|table text|fonts?)\b"
_DECK_WIDE = r"\b(deck-wide|deck_style|deck style|whole deck|every slide|across the deck)\b"
_NOT_NARROWED = (
    r"\b(not|never|no)\b[^.;]{0,60}\b(narrow\w*|limit\w*|only the stage|just the stage)\b"
)
_ONE_SLIDE = r"\b(one slide'?s|a single slide'?s|a slide'?s own|one slide's own)\b"
_CONTENT = r"\b(content|title|bullets|wording|text)\b"


def _a_sentence_matching(text: str, *patterns: str) -> str | None:
    for sentence in _sentences(text):
        if all(re.search(p, sentence) for p in patterns):
            return sentence
    return None


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_a_kind_of_element_across_the_deck_stays_deck_wide_with_a_stage(source):
    """One sentence of the stage policy: a request about a kind of element (with an example such as
    code blocks or tables) is deck-wide and is not narrowed to the stage slide."""
    text = _stage_text(SOURCES[source]())
    assert _a_sentence_matching(text, _KIND, _DECK_WIDE, _NOT_NARROWED, r"\bstage\b"), (
        f"{source}: no stage-policy sentence keeps a kind of element across the deck deck-wide "
        "and refuses to narrow it to the stage slide"
    )
    assert re.search(_ELEMENT_EXAMPLE, text), (
        f"{source}: the stage policy gives no example of such an element (code blocks, tables)"
    )


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_one_slide_s_own_content_edit_is_what_defaults_to_the_stage(source):
    """One sentence of the stage policy: an edit of one slide's own content that names no slide
    means the stage slide."""
    text = _stage_text(SOURCES[source]())
    assert _a_sentence_matching(
        text, _ONE_SLIDE, _CONTENT, r"\bstage slide\b",
        r"\b(names no slide|does not name|doesn't name|no slide named|without naming)\b",
    ), (
        f"{source}: no stage-policy sentence limits the stage default to an edit of one slide's "
        "own content that names no slide"
    )


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_the_deck_style_rule_still_calls_a_style_request_deck_wide(source):
    """The DECK STYLE rule the stage policy must agree with is still shipped (not deleted to
    remove the conflict)."""
    text = _plain(SOURCES[source]())
    assert "a deck-wide style request" in text
    assert "deck_changes.deck_style" in text


def test_the_packaged_prompt_is_the_authored_prompt():
    assert _packaged() == _authored()
