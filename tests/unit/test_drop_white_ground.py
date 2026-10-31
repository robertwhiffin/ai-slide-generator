"""One ground, the pure helper (deck style addendum A, Task B7, Ruling RA23/RA25).

``src.domain.deck_style.drop_white_ground(html: str) -> str`` removes the class
token ``white`` from every element whose class list holds the token ``slide``:
the template convention ``.slide.white`` (the deck CSS paints ``.slide``,
``.slide.dark``, ``.slide.white`` and ``.slide.event``).  Everything else comes
back byte for byte:

* only the whole token ``white``, and only on an element whose class tokens
  include ``slide`` (``whitespace``, ``bg-white``, ``white-card``, ``slide-white``
  and a ``white`` beside no ``slide`` are other classes);
* only a real class attribute of a real tag: never text, an attribute value that
  merely contains ``class="slide white"``, an attribute named ``data-class``, a
  ``<script>``/``<style>`` element or a comment;
* every other token, attribute, quote and byte of the tag.

HTML with nothing to drop comes back equal to its input.  The scan is linear: a
50k-character adversarial input finishes well under 0.1 s.

How "dropped" is compared: inside a CHANGED class attribute the token separators
may be re-spaced, so expected and actual are compared with every class value's
whitespace collapsed (``_same_after_drop``).  Everything outside class values,
and every class value of an untouched element, must be byte-identical.
"""

from __future__ import annotations

import re
import time

import pytest


def drop_white_ground(html: str) -> str:
    """The helper under test, imported per call so each case fails on its own."""
    from src.domain.deck_style import drop_white_ground as helper

    return helper(html)


#: A class attribute's value in the simple inputs below (never ``data-class``).
_CLASS_VALUE = re.compile(r"""(?<![-\w])(class\s*=\s*)(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)


def _collapsed(html: str) -> str:
    def _one(m: "re.Match[str]") -> str:
        quote = '"' if m.group(2) is not None else "'"
        value = m.group(2) if m.group(2) is not None else m.group(3)
        return f"{m.group(1)}{quote}{' '.join(value.split())}{quote}"

    return _CLASS_VALUE.sub(_one, html)


def _same_after_drop(actual: str, expected: str) -> bool:
    return _collapsed(actual) == _collapsed(expected)


# ---------------------------------------------------------------------------
# Dropped
# ---------------------------------------------------------------------------

DROPPED = [
    pytest.param('<div class="slide white">X</div>', '<div class="slide">X</div>', id="at_the_end"),
    pytest.param(
        '<div class="white slide">X</div>', '<div class="slide">X</div>', id="at_the_start"
    ),
    pytest.param(
        '<div class="brand white slide pad">X</div>',
        '<div class="brand slide pad">X</div>',
        id="in_the_middle",
    ),
    pytest.param(
        "<div class='slide white'>X</div>", "<div class='slide'>X</div>", id="single_quoted"
    ),
    pytest.param(
        '<div class="slide white"/>', '<div class="slide"/>', id="double_quoted_self_closing"
    ),
    pytest.param(
        '<section class="frame"><div class="slide white" id="s5"><p>Two-column</p></div></section>',
        '<section class="frame"><div class="slide" id="s5"><p>Two-column</p></div></section>',
        id="nested_in_a_section",
    ),
    pytest.param(
        '<section class="slide white"><h1>T</h1></section>',
        '<section class="slide"><h1>T</h1></section>',
        id="a_section_root",
    ),
    pytest.param(
        '<div class="slide white">A</div><div class="white slide">B</div>',
        '<div class="slide">A</div><div class="slide">B</div>',
        id="every_element",
    ),
    pytest.param(
        '<div class="white slide white">X</div>',
        '<div class="slide">X</div>',
        id="every_occurrence",
    ),
    pytest.param(
        '<div class="slide\n\twhite">X</div>',
        '<div class="slide">X</div>',
        id="any_html_whitespace",
    ),
    pytest.param(
        '<div class = "slide white">X</div>',
        '<div class = "slide">X</div>',
        id="spaces_around_the_equals",
    ),
    pytest.param(
        '<div CLASS="slide white">X</div>', '<div CLASS="slide">X</div>', id="attribute_name_case"
    ),
    pytest.param(
        '<div data-x="a>b" class="slide white">X</div>',
        '<div data-x="a>b" class="slide">X</div>',
        id="a_quoted_gt_earlier_in_the_tag",
    ),
    pytest.param(
        '<p>x < 10</p><div class="slide white">X</div>',
        '<p>x < 10</p><div class="slide">X</div>',
        id="a_text_lt_before_the_tag",
    ),
    pytest.param(
        '<div class="slide dark white">X</div>', '<div class="slide dark">X</div>', id="dark_stays"
    ),
    pytest.param(
        '<div id="s" class="slide white" style="display:flex" data-theme="white">X</div>',
        '<div id="s" class="slide" style="display:flex" data-theme="white">X</div>',
        id="only_the_class_attribute_changes",
    ),
]


@pytest.mark.parametrize("html, expected", DROPPED)
def test_white_is_dropped_from_a_slide_element(html, expected):
    out = drop_white_ground(html)

    assert _same_after_drop(out, expected), out
    assert out != html


def test_only_the_slide_elements_class_value_changes():
    """A non-slide element's class value keeps its exact bytes, double space included."""
    html = (
        '<div class="slide white"><div class="card  white">A</div>'
        "<span class='bg-white'>B</span></div>"
    )

    out = drop_white_ground(html)

    assert 'class="card  white"' in out
    assert "class='bg-white'" in out
    assert _same_after_drop(
        out,
        '<div class="slide"><div class="card  white">A</div>'
        "<span class='bg-white'>B</span></div>",
    )


def test_a_real_slide_is_dropped_while_its_script_and_comment_are_not():
    script = "<script>const tpl = '<div class=\"slide white\">';</script>"
    comment = '<!-- <div class="slide white"> -->'
    html = f'{comment}<div class="slide white">X</div>{script}'

    out = drop_white_ground(html)

    assert out.startswith(comment)
    assert out.endswith(script)
    assert _same_after_drop(out, f'{comment}<div class="slide">X</div>{script}')


# ---------------------------------------------------------------------------
# Untouched, byte for byte
# ---------------------------------------------------------------------------

UNTOUCHED = [
    pytest.param('<div class="slide whitespace">X</div>', id="whitespace"),
    pytest.param('<div class="slide bg-white">X</div>', id="bg_white"),
    pytest.param('<div class="slide white-card">X</div>', id="white_card"),
    pytest.param('<div class="slide-white white">X</div>', id="slide_white_is_not_slide"),
    pytest.param('<div class="slides white">X</div>', id="slides_is_not_slide"),
    pytest.param('<div class="card white">X</div>', id="no_slide_token"),
    pytest.param('<div class="white">X</div>', id="white_alone"),
    pytest.param(
        '<section class="white"><div class="slide">X</div></section>', id="white_on_a_wrapper"
    ),
    pytest.param('<div class="slide dark">X</div>', id="dark"),
    pytest.param('<div class="slide event">X</div>', id="event"),
    pytest.param('<div class="slide">X</div>', id="already_default"),
    pytest.param("<script>const s = '<div class=\"slide white\">';</script>", id="inside_a_script"),
    pytest.param(
        '<script type="text/template"><div class="slide white"></div></script>',
        id="a_script_template",
    ),
    pytest.param("<style>.slide.white{background:#fff}</style>", id="a_style_rule"),
    pytest.param('<style>/* <div class="slide white"> */</style>', id="inside_a_style"),
    pytest.param('<!-- <div class="slide white"> -->', id="inside_a_comment"),
    pytest.param('<p>class="slide white"</p>', id="text"),
    pytest.param(
        '<div title=\'class="slide white"\' class="card">X</div>', id="inside_another_attribute"
    ),
    pytest.param('<div data-class="slide white">X</div>', id="an_attribute_named_data_class"),
    pytest.param("<div class=slide>X</div>", id="unquoted_slide"),
    pytest.param("<div class=white>X</div>", id="unquoted_white"),
    pytest.param("plain text, no tags", id="no_tags"),
    pytest.param("", id="empty"),
    pytest.param(
        '<div class="slide"><h1 class="title">Q3</h1>'
        '<div class="dk-callout" style="display:flex">Revenue doubled.</div>'
        '<footer class="footer">{{slide:number}} / {{slide:count}}</footer></div>',
        id="a_whole_slide_with_nothing_to_drop",
    ),
]


@pytest.mark.parametrize("html", UNTOUCHED)
def test_nothing_else_is_touched(html):
    assert drop_white_ground(html) == html


# ---------------------------------------------------------------------------
# Linear on adversarial input
# ---------------------------------------------------------------------------

ADVERSARIAL = [
    pytest.param('<div class="' + "slide white " * 4200, id="an_unclosed_class_value"),
    pytest.param("<" * 50_000, id="lt_run"),
    pytest.param("<div " + "a=" * 25_000, id="equals_run"),
    pytest.param("<div class=" * 5_000, id="class_equals_run"),
    pytest.param("<div " + '"' * 50_000, id="quote_run"),
    pytest.param("<div" + " class" * 10_000, id="attribute_name_run"),
    pytest.param("<!--" * 12_500, id="comment_openers"),
    pytest.param("<script>" + "<div class='slide white'>" * 2_000, id="an_unclosed_script"),
    pytest.param('<div class="slide white">' * 2_000, id="many_real_matches"),
]


@pytest.mark.parametrize("html", ADVERSARIAL)
def test_a_50k_adversarial_input_is_linear(html):
    assert len(html) >= 50_000
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        drop_white_ground(html)
        timings.append(time.perf_counter() - start)
    assert min(timings) < 0.1, f"best of 3: {min(timings):.3f}s"


def test_the_many_matches_input_drops_every_one():
    html = '<div class="slide white">' * 2_000

    out = drop_white_ground(html)

    assert "white" not in out
    assert _collapsed(out).count('class="slide"') == 2_000
