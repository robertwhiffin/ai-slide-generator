"""Reconciling ``{{image:TOKEN}}`` references against known tokens (gateway-mcp Task 5).

Review Focus 4: a model that mistypes an image token's tail, or invents one,
must not break a slide.

- A known reference is kept.
- An unknown reference of at least 12 characters (T5.3) is corrected when
  exactly ONE known token shares its first 12 characters.
- Otherwise it is removed (in HTML with its ``<img>`` element, or inside
  ``url('...')`` with its whole ``background-image`` declaration) and reported.

``reconcile_model_strings`` walks an architect output dict and reports each
removal as ``(json_path, ref)``; ``removed_slide_numbers`` turns those paths
into 1-based slide numbers (T5.4).  The token regex is the shared
``IMAGE_PLACEHOLDER_PATTERN`` (T5.6).

Tokens are real ``secrets.token_urlsafe(32)`` values (43 characters).  Expected
strings are built by concatenation, never with an f-string (PLAN-CORRECTIONS T4.2).
"""

from __future__ import annotations

import ast
import copy
import re
import secrets
from pathlib import Path
from typing import Any

import pytest

from src.domain.skill_io import ArchitectOutput
from src.utils.image_refs import (
    IMAGE_REF_RE,
    reconcile_html,
    reconcile_model_strings,
    reconcile_text,
    refs_in,
    removed_slide_numbers,
)
from src.utils.image_utils import IMAGE_PLACEHOLDER_PATTERN

REPO = Path(__file__).resolve().parents[2]


def _ref(token: str) -> str:
    return "{{image:" + token + "}}"


def _token() -> str:
    """A real image token whose first 12 characters cannot be confused with the
    fixed invented tokens below."""
    while True:
        token = secrets.token_urlsafe(32)
        if not token.startswith(("ZZZZ", "YYYY", "WWWW")):
            assert len(token) == 43
            return token


def _typo(token: str) -> str:
    """Same first 40 characters, a different 3-character tail."""
    for tail in ("xyz", "abc"):
        candidate = token[:40] + tail
        if candidate != token:
            return candidate
    raise AssertionError("unreachable")


#: Invented by the model: no known token shares their first 12 characters.
INVENTED = "Z" * 43
INVENTED_2 = "Y" * 43
INVENTED_3 = "W" * 43


def _declarations(style: str) -> list[str]:
    """A style attribute's declarations, stripped, empties dropped."""
    return [part.strip() for part in style.split(";") if part.strip()]


# ---------------------------------------------------------------------------
# The shared regex (T5.6)
# ---------------------------------------------------------------------------


def test_image_ref_re_is_the_shared_placeholder_pattern():
    assert IMAGE_REF_RE is IMAGE_PLACEHOLDER_PATTERN


# ---------------------------------------------------------------------------
# reconcile_text
# ---------------------------------------------------------------------------


def test_reconcile_keeps_known_fixes_tail_typo_removes_invented():
    token = _token()
    typo = _typo(token)
    assert typo != token and typo[:12] == token[:12]

    # Known: kept.
    kept = "Hero: " + _ref(token) + "."
    assert reconcile_text(kept, {token}) == (kept, [])

    # Tail typo: corrected to the one known token sharing its first 12 characters.
    assert reconcile_text("Chart: " + _ref(typo) + ".", {token}) == (
        "Chart: " + _ref(token) + ".",
        [],
    )

    # Invented: the placeholder is removed and reported.
    assert reconcile_text("Logo: " + _ref(INVENTED) + ".", {token}) == ("Logo: .", [INVENTED])

    # All three in one text.
    text = "Hero: " + _ref(token) + ". Chart: " + _ref(typo) + ". Logo: " + _ref(INVENTED) + "."
    fixed, removed = reconcile_text(text, {token})
    assert fixed == "Hero: " + _ref(token) + ". Chart: " + _ref(token) + ". Logo: ."
    assert removed == [INVENTED]
    assert IMAGE_PLACEHOLDER_PATTERN.findall(fixed) == [token, token]


def test_reconcile_text_without_refs_is_unchanged():
    text = "A slide about the lakehouse. {not a ref} {{image:}} done"

    assert reconcile_text(text, {_token()}) == (text, [])
    assert reconcile_text("", set()) == ("", [])


def test_reconcile_ambiguous_prefix_removes():
    """Two known tokens share the first 12 characters: an unknown ref with that
    prefix cannot be pinned to either, so it is removed.  The known ones stay."""
    first = _token()
    second = first[:12] + _token()[:31]
    assert len(second) == 43 and second != first
    unknown = first[:12] + "q" * 31
    assert unknown not in (first, second)

    assert reconcile_text("a " + _ref(unknown) + " b", [first, second]) == ("a  b", [unknown])

    both = _ref(first) + " " + _ref(second)
    assert reconcile_text(both, [first, second]) == (both, [])


@pytest.mark.parametrize("length", [1, 8, 11])
def test_a_short_unknown_ref_is_removed_not_prefix_matched(length):
    """T5.3: the 12-character prefix fix applies only to a ref of at least 12
    characters; a shorter one that happens to start a known token is removed."""
    token = _token()
    short = token[:length]

    assert reconcile_text("x" + _ref(short) + "y", {token}) == ("xy", [short])


@pytest.mark.parametrize("length", [12, 20, 42])
def test_an_unknown_ref_of_12_or_more_characters_is_prefix_matched(length):
    token = _token()
    partial = token[:length]

    assert reconcile_text("x" + _ref(partial) + "y", {token}) == ("x" + _ref(token) + "y", [])


@pytest.mark.parametrize("make_known", [list, tuple, set, frozenset])
def test_known_may_be_any_collection(make_known):
    token = _token()
    other = _token()
    text = _ref(token) + _ref(_typo(other)) + _ref(INVENTED)

    fixed, removed = reconcile_text(text, make_known([token, other]))

    assert fixed == _ref(token) + _ref(other)
    assert removed == [INVENTED]


def test_every_occurrence_is_reconciled():
    token = _token()
    typo = _typo(token)
    text = _ref(typo) + " and " + _ref(typo) + "; " + _ref(INVENTED) + " and " + _ref(INVENTED)

    fixed, removed = reconcile_text(text, {token})

    assert fixed == _ref(token) + " and " + _ref(token) + ";  and "
    assert set(removed) == {INVENTED}


# ---------------------------------------------------------------------------
# reconcile_html
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "img",
    [
        '<img src="REF" alt="Logo" />',
        '<img class="logo" alt="Logo" src="REF">',
        '<img\n  class="logo"\n  src="REF"\n  alt="Logo"\n/>',
    ],
    ids=["self-closing", "src-last", "multi-line"],
)
def test_reconcile_html_drops_the_whole_img_element(img):
    token = _token()
    html = "<p>a</p>" + img.replace("REF", _ref(INVENTED)) + "<p>b</p>"

    assert reconcile_html(html, {token}) == ("<p>a</p><p>b</p>", [INVENTED])


def test_reconcile_html_drops_img_element_and_background_decl():
    token = _token()
    html = (
        '<div class="slide">'
        '<img src="' + _ref(token) + '" alt="Architecture" />'
        '<img class="logo" alt="Logo" src="' + _ref(INVENTED) + '">'
        "<p>Revenue grew 12%</p>"
        '<div class="hero" style="background-image: url(\'' + _ref(INVENTED_2) + "'); color: red\">"
        "Hero</div>"
        "</div>"
    )

    fixed, removed = reconcile_html(html, {token})

    assert sorted(removed) == sorted([INVENTED, INVENTED_2])
    # The known image is untouched; the invented one went with its element.
    assert '<img src="' + _ref(token) + '" alt="Architecture" />' in fixed
    assert fixed.count("<img") == 1
    assert 'class="logo"' not in fixed and 'alt="Logo"' not in fixed
    # The background declaration went whole; the rest of the style stayed.
    assert "background-image" not in fixed
    assert "url(" not in fixed
    hero = re.search(r'<div class="hero" style="([^"]*)">Hero</div>', fixed)
    assert hero is not None, fixed
    assert _declarations(hero.group(1)) == ["color: red"]
    # Nothing else changed.
    assert INVENTED not in fixed and INVENTED_2 not in fixed
    assert fixed.startswith('<div class="slide">')
    assert fixed.endswith("Hero</div></div>")
    assert "<p>Revenue grew 12%</p>" in fixed
    assert IMAGE_PLACEHOLDER_PATTERN.findall(fixed) == [token]


def test_reconcile_html_background_decl_last_without_semicolon():
    html = (
        '<div style="color: red; background-image: url(\'' + _ref(INVENTED) + "')\">x</div>"
    )

    fixed, removed = reconcile_html(html, {_token()})

    assert removed == [INVENTED]
    assert "background-image" not in fixed and INVENTED not in fixed
    style = re.search(r'<div style="([^"]*)">x</div>', fixed)
    assert style is not None, fixed
    assert _declarations(style.group(1)) == ["color: red"]


def test_reconcile_html_keeps_known_and_fixes_typos_in_place():
    token = _token()
    typo = _typo(token)
    template = (
        '<img src="REF" alt="Diagram" />'
        "<div style=\"background-image: url('REF'); background-size: cover\">x</div>"
    )
    html = template.replace("REF", _ref(typo))

    assert reconcile_html(html, {token}) == (template.replace("REF", _ref(token)), [])
    known = template.replace("REF", _ref(token))
    assert reconcile_html(known, {token}) == (known, [])


def test_reconcile_html_ambiguous_prefix_in_an_img_removes_the_element():
    first = _token()
    second = first[:12] + _token()[:31]
    unknown = first[:12] + "q" * 31
    html = '<p>a</p><img src="' + _ref(unknown) + '" alt="x" /><p>b</p>'

    assert reconcile_html(html, [first, second]) == ("<p>a</p><p>b</p>", [unknown])


def test_reconcile_html_bare_ref_outside_img_or_url_is_removed():
    html = "<p>See " + _ref(INVENTED) + " here</p>"

    assert reconcile_html(html, {_token()}) == ("<p>See  here</p>", [INVENTED])


def test_reconcile_html_unknown_ref_in_another_css_context_never_survives():
    """Whatever the context, an unknown reference is never left in the HTML."""
    html = (
        "<div style=\"background: url('" + _ref(INVENTED) + "') center / cover\">x</div>"
        "<div style='background-image: url(\"" + _ref(INVENTED_2) + "\")'>y</div>"
    )

    fixed, removed = reconcile_html(html, {_token()})

    assert sorted(removed) == sorted([INVENTED, INVENTED_2])
    assert IMAGE_PLACEHOLDER_PATTERN.findall(fixed) == []
    assert ">x</div>" in fixed and ">y</div>" in fixed


# ---------------------------------------------------------------------------
# refs_in
# ---------------------------------------------------------------------------


def test_refs_in_finds_every_ref_in_nested_strings():
    a, b, c = _token(), _token(), _token()
    obj = {
        "message": "x " + _ref(a) + " y",
        "slides": [
            _ref(b) + _ref(c),
            {"content_brief": "again " + _ref(a)},
            7,
            None,
            True,
        ],
        "deck": {"title": "no refs here", "nested": [[{"deep": _ref(c)}]]},
    }

    assert refs_in(obj) == {a, b, c}
    assert refs_in(_ref(a) + " " + _ref(b)) == {a, b}
    assert refs_in({"none": None, "n": 3}) == set()
    assert refs_in(None) == set()


# ---------------------------------------------------------------------------
# reconcile_model_strings and removed_slide_numbers (T5.4)
# ---------------------------------------------------------------------------


def _slide(position: int, brief: str, *, purpose: str = "Explain") -> dict[str, Any]:
    return {
        "position": position,
        "purpose": purpose,
        "content_brief": brief,
        "assumes": "nothing",
        "hands_off": "next",
        "data_references": [],
    }


def _deck(slides: list[dict[str, Any]], *, title: str = "Lakehouse") -> dict[str, Any]:
    return {
        "title": title,
        "audience": "Execs",
        "purpose": "Inform",
        "argument": "It works",
        "call_to_action": "Adopt",
        "narrative_arc": ["setup", "payoff"],
        "design_contract": {},
        "resolved_data": {"synthesis": "", "figures": [], "gaps": []},
        "slides": slides,
    }


def _content(brief: str, *, purpose: str = "Explain") -> dict[str, Any]:
    slide = _slide(0, brief, purpose=purpose)
    del slide["position"]
    return slide


def test_reconcile_model_strings_walks_nested():
    """A build output: every string in it is reconciled, the input is not mutated,
    the result still validates, and each removal names its JSON path.  Slides are
    deliberately out of position order (positions 0, 3, 1)."""
    token = _token()
    typo = _typo(token)
    output = ArchitectOutput.model_validate(
        {
            "intent": "build",
            "message": "Built with " + _ref(token),
            "deck_spec": _deck(
                [
                    _slide(0, "Intro"),
                    _slide(3, "Diagram: " + _ref(typo)),
                    _slide(1, "Chart: " + _ref(INVENTED), purpose="Show " + _ref(INVENTED_2)),
                ]
            ),
        }
    ).model_dump()
    before = copy.deepcopy(output)

    fixed, removed = reconcile_model_strings(output, {token})

    assert output == before, "the input is not mutated"
    assert sorted(removed) == sorted(
        [
            ("deck_spec.slides[2].content_brief", INVENTED),
            ("deck_spec.slides[2].purpose", INVENTED_2),
        ]
    )
    expected = copy.deepcopy(before)
    expected["deck_spec"]["slides"][1]["content_brief"] = "Diagram: " + _ref(token)
    expected["deck_spec"]["slides"][2]["content_brief"] = "Chart: "
    expected["deck_spec"]["slides"][2]["purpose"] = "Show "
    assert fixed == expected
    assert ArchitectOutput.model_validate(fixed).deck_spec.slides[1].content_brief == (
        "Diagram: " + _ref(token)
    )

    numbers = removed_slide_numbers(fixed, removed)
    # slides[2] is the slide at position 1: slide 2, whatever its list index.
    assert numbers == [2, 2]


def test_reconcile_model_strings_paths_for_operations_and_deck_changes():
    token = _token()
    output = ArchitectOutput.model_validate(
        {
            "intent": "edit",
            "message": "Edited " + _ref(INVENTED_3),
            "operations": [
                {"op": "update", "position": 2, "slides": [_content("A " + _ref(token))]},
                {
                    "op": "insert",
                    "after_position": 4,
                    "slides": [_content("first"), _content("B " + _ref(INVENTED))],
                },
                {"op": "delete", "position": 7},
            ],
            "deck_changes": {"title": "T " + _ref(INVENTED_2)},
            "target_positions": [2],
        }
    ).model_dump()

    fixed, removed = reconcile_model_strings(output, [token])

    assert sorted(removed) == sorted(
        [
            ("message", INVENTED_3),
            ("operations[1].slides[1].content_brief", INVENTED),
            ("deck_changes.title", INVENTED_2),
        ]
    )
    assert fixed["operations"][0]["slides"][0]["content_brief"] == "A " + _ref(token)
    assert fixed["operations"][1]["slides"][1]["content_brief"] == "B "
    assert fixed["operations"][2] == output["operations"][2]
    assert fixed["deck_changes"]["title"] == "T "
    assert fixed["message"] == "Edited "
    assert fixed["target_positions"] == [2]
    ArchitectOutput.model_validate(fixed)

    expected_numbers = {
        "message": None,
        "operations[1].slides[1].content_brief": 4 + 2 + 1,
        "deck_changes.title": None,
    }
    assert removed_slide_numbers(fixed, removed) == [expected_numbers[p] for p, _ in removed]


def test_reconcile_model_strings_without_removals():
    token = _token()
    output = {"intent": "discuss", "message": "See " + _ref(token), "target_positions": []}

    assert reconcile_model_strings(output, {token}) == (output, [])


def test_removed_slide_numbers_use_positions_not_list_indexes():
    output = {
        "intent": "build",
        "message": "m",
        "deck_spec": _deck([_slide(0, "a"), _slide(3, "b"), _slide(1, "c")]),
    }
    removed = [
        ("deck_spec.slides[1].content_brief", "r1"),
        ("deck_spec.slides[2].purpose", "r2"),
        ("deck_spec.slides[0].content_brief", "r3"),
        ("message", "r4"),
        ("deck_spec.title", "r5"),
    ]

    assert removed_slide_numbers(output, removed) == [4, 2, 1, None, None]


def test_removed_slide_numbers_for_operations():
    """``operations[j]`` -> that op's ``position + 1``; an insert's k-th slide ->
    ``after_position + 2 + k`` (``after_position = -1`` is the start); anything
    else -> None."""
    output = {
        "intent": "edit",
        "message": "m",
        "operations": [
            {"op": "update", "position": 2, "after_position": None, "slides": [_content("a")]},
            {
                "op": "insert",
                "position": None,
                "after_position": 4,
                "slides": [_content("b0"), _content("b1")],
            },
            {"op": "insert", "position": None, "after_position": -1, "slides": [_content("c")]},
            {
                "op": "replace",
                "position": 5,
                "after_position": None,
                "slides": [_content("d0"), _content("d1")],
            },
        ],
        "deck_changes": {"title": "t"},
    }
    removed = [
        ("operations[0].slides[0].content_brief", "r0"),
        ("operations[1].slides[1].content_brief", "r1"),
        ("operations[1].slides[0].purpose", "r2"),
        ("operations[2].slides[0].content_brief", "r3"),
        ("operations[3].slides[1].content_brief", "r4"),
        ("deck_changes.title", "r5"),
        ("message", "r6"),
    ]

    assert removed_slide_numbers(output, removed) == [3, 7, 6, 1, 6, None, None]


def test_removed_slide_numbers_of_nothing_is_empty():
    assert removed_slide_numbers({"intent": "discuss", "message": "m"}, []) == []


# ---------------------------------------------------------------------------
# Module contract
# ---------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    package = ".".join(path.relative_to(REPO).parent.parts)
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - (node.level - 1)])
                module = base + ("." + node.module if node.module else "")
            else:
                module = node.module or ""
            modules.add(module)
            modules.update(module + "." + alias.name for alias in node.names)
    return modules


def test_the_image_refs_module_does_not_import_core_skills():
    """T5.5 (``test_lakebase_only_runtime_contract``)."""
    modules = _imported_modules(REPO / "src" / "utils" / "image_refs.py")

    assert not [m for m in modules if m == "src.core.skills" or m.startswith("src.core.skills.")]
