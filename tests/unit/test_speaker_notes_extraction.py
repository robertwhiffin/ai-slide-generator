"""Tests for the speaker-notes extraction helpers (plan D3).

An owned aside is ``<aside class="speaker-notes">`` that sits inside a
``.slide`` element, or that is a direct child of a ``section``/``article``
whose only other element child is the ``.slide``. Owned asides are removed
from the slide HTML and their text becomes the slide's notes.
"""

import pytest
from bs4 import BeautifulSoup

from src.utils.html_utils import (
    SPEAKER_NOTES_CLASS,
    extract_speaker_notes,
    find_slide_roots,
    notes_for_root,
    pop_speaker_notes,
)

SIBLING_SECTION = (
    '<section class="dark"><div class="slide"><p>x</p></div>'
    '<aside class="speaker-notes">Say it.</aside></section>'
)


def test_the_class_name_constant():
    # Sabotage: a renamed token (e.g. "notes") silently stops every extraction.
    assert SPEAKER_NOTES_CLASS == "speaker-notes"


@pytest.mark.parametrize(
    "html",
    [
        "<DIV class='slide'><br><p hidden>&nbsp;x</p></DIV>",
        '<div class="slide"><p>See the speaker-notes field.</p></div>',
        "",
    ],
)
def test_no_aside_returns_the_input_unchanged(html):
    # Sabotage: always return str(soup) (reserialises quotes, case, entities).
    out, notes = extract_speaker_notes(html)
    assert out == html
    assert out is html
    assert notes is None


def test_an_aside_inside_the_slide_becomes_paragraph_notes():
    # Sabotage: join paragraphs with "\n" or skip whitespace collapse.
    html = (
        '<div class="slide"><h1>T</h1><aside class="speaker-notes">'
        "<p>One.</p><p>Two\n   lines.</p></aside></div>"
    )
    out, notes = extract_speaker_notes(html)
    assert out == '<div class="slide"><h1>T</h1></div>'
    assert notes == "One.\n\nTwo lines."


def test_a_hidden_aside_from_the_design_system_readme_is_owned():
    # Sabotage: treat a `hidden` aside as not-notes, or keep it in the HTML.
    html = (
        '<div class="slide"><h1>T</h1>'
        '<aside class="speaker-notes" hidden><p>Step one.</p><p>Step two.</p></aside>'
        "</div>"
    )
    out, notes = extract_speaker_notes(html)
    assert out == '<div class="slide"><h1>T</h1></div>'
    assert notes == "Step one.\n\nStep two."


def test_an_aside_deep_inside_the_slide_is_owned():
    # Sabotage: require the aside to be a direct child of the .slide element.
    html = (
        '<div class="slide"><div class="body"><p>x</p>'
        '<aside class="speaker-notes">Deep.</aside></div></div>'
    )
    out, notes = extract_speaker_notes(html)
    assert out == '<div class="slide"><div class="body"><p>x</p></div></div>'
    assert notes == "Deep."


def test_list_items_are_paragraphs_too():
    # Sabotage: only collect <p> descendants, ignoring <li>.
    html = (
        '<div class="slide"><h1>T</h1><aside class="speaker-notes">'
        "<ul><li>First   point</li><li></li><li>Second\npoint</li></ul></aside></div>"
    )
    out, notes = extract_speaker_notes(html)
    assert out == '<div class="slide"><h1>T</h1></div>'
    assert notes == "First point\n\nSecond point"


def test_a_paragraph_inside_a_list_item_is_not_counted_twice():
    # Sabotage: emit both the <li> and its nested <p> as separate paragraphs.
    html = (
        '<div class="slide"><aside class="speaker-notes">'
        "<ul><li><p>A</p></li><li><p>B</p></li></ul></aside></div>"
    )
    out, notes = extract_speaker_notes(html)
    assert out == '<div class="slide"></div>'
    assert notes == "A\n\nB"


def test_an_aside_without_paragraphs_uses_its_text():
    # Sabotage: return "" when the aside has no <p>/<li>, or skip collapse/strip.
    html = (
        '<div class="slide"><p>x</p><aside class="speaker-notes">\n'
        "  Pause here,\n   then <b>click</b>.  \n</aside></div>"
    )
    out, notes = extract_speaker_notes(html)
    assert out == '<div class="slide"><p>x</p></div>'
    assert notes == "Pause here, then click."


@pytest.mark.parametrize(
    "html, expected_out",
    [
        (
            SIBLING_SECTION,
            '<section class="dark"><div class="slide"><p>x</p></div></section>',
        ),
        (
            '<article><aside class="speaker-notes">Say it.</aside>'
            '<div class="slide"><p>x</p></div></article>',
            '<article><div class="slide"><p>x</p></div></article>',
        ),
    ],
)
def test_a_sibling_aside_inside_a_wrapping_section_is_owned(html, expected_out):
    # Sabotage: only own asides that have a .slide ancestor (rule (a) alone).
    out, notes = extract_speaker_notes(html)
    assert out == expected_out
    assert notes == "Say it."


@pytest.mark.parametrize(
    "html",
    [
        # Top-level aside next to a slide, no wrapper.
        "<div class='slide'><p hidden>x</p></div>"
        "<aside class='speaker-notes'>Not mine.</aside>",
        # Aside beside the slide inside a <div> wrapper (div is never a slide wrapper).
        "<div class='wrap'><div class='slide'><p hidden>x</p></div>"
        "<aside class='speaker-notes'>Not mine.</aside></div>",
        # Aside in a <section> that holds two slides.
        "<section><div class='slide'><p hidden>a</p></div>"
        "<div class='slide'><p>b</p></div>"
        "<aside class='speaker-notes'>Not mine.</aside></section>",
    ],
)
def test_unowned_asides_are_left_alone(html):
    # Sabotage: own every speaker-notes aside, or reserialise when none is owned.
    out, notes = extract_speaker_notes(html)
    assert out == html
    assert out is html
    assert notes is None


def test_other_asides_are_untouched():
    # Sabotage: remove every <aside> in the slide, not only speaker-notes ones.
    html = (
        '<div class="slide"><aside>note</aside><aside class="callout">c</aside>'
        '<aside class="speaker-notes">S</aside></div>'
    )
    out, notes = extract_speaker_notes(html)
    assert out == '<div class="slide"><aside>note</aside><aside class="callout">c</aside></div>'
    assert notes == "S"


def test_the_class_token_must_match_exactly():
    # Sabotage: substring match on the class attribute instead of a token match.
    owned = "<div class='slide'><p>x</p><aside class='speaker-notes muted'>S</aside></div>"
    out, notes = extract_speaker_notes(owned)
    assert out == '<div class="slide"><p>x</p></div>'
    assert notes == "S"

    for not_owned in (
        "<div class='slide'><p>x</p><aside class='speaker-notes-x'>S</aside></div>",
        "<div class='slide'><p>x</p><aside class='my-speaker-notes'>S</aside></div>",
    ):
        out, notes = extract_speaker_notes(not_owned)
        assert out is not_owned
        assert notes is None


@pytest.mark.parametrize(
    "aside",
    [
        '<aside class="speaker-notes"></aside>',
        '<aside class="speaker-notes">  \n  </aside>',
        '<aside class="speaker-notes"><p> </p><p></p></aside>',
    ],
)
def test_an_empty_aside_clears_notes(aside):
    # Sabotage: return None for an empty owned aside (would keep stale notes).
    out, notes = extract_speaker_notes(f'<div class="slide"><p>x</p>{aside}</div>')
    assert out == '<div class="slide"><p>x</p></div>'
    assert notes == ""


def test_two_asides_join_in_document_order():
    # Sabotage: keep only the first (or last) owned aside, or reverse order.
    html = (
        '<div class="slide"><aside class="speaker-notes">First</aside><p>x</p>'
        '<aside class="speaker-notes"><p>Second</p></aside></div>'
    )
    out, notes = extract_speaker_notes(html)
    assert out == '<div class="slide"><p>x</p></div>'
    assert notes == "First\n\nSecond"


@pytest.mark.parametrize(
    "aside",
    [
        '<aside class="speaker-notes"><p>Run fetch( now</p>'
        "<script>x()</script><style>p{}</style></aside>",
        '<aside class="speaker-notes">Run fetch( now'
        "<script>x()</script><style>p{}</style><template>t</template></aside>",
        '<aside class="speaker-notes"><p>Run fetch(<script>x()</script> now</p></aside>',
    ],
)
def test_script_and_style_text_is_not_notes(aside):
    # Sabotage: collect every string (including script/style/template content).
    out, notes = extract_speaker_notes(f'<div class="slide"><p>x</p>{aside}</div>')
    assert out == '<div class="slide"><p>x</p></div>'
    assert notes == "Run fetch( now"


def test_pop_speaker_notes_lets_the_wrapper_promote():
    # Sabotage: pop after find_slide_roots, or leave the aside in the soup.
    before = find_slide_roots(BeautifulSoup(SIBLING_SECTION, "html.parser"))
    assert [root.name for root in before] == ["div"]

    soup = BeautifulSoup(SIBLING_SECTION, "html.parser")
    popped = pop_speaker_notes(soup)
    assert [text for _, text in popped] == ["Say it."]
    assert soup.find("aside") is None

    roots = find_slide_roots(soup)
    assert [root.name for root in roots] == ["section"]
    assert notes_for_root(roots[0], popped) == "Say it."


def test_pop_speaker_notes_leaves_unowned_asides_in_place():
    # Sabotage: pop every speaker-notes aside regardless of ownership.
    html = (
        '<div class="slide"><p>x</p></div>'
        '<aside class="speaker-notes">Not mine.</aside>'
    )
    soup = BeautifulSoup(html, "html.parser")
    assert pop_speaker_notes(soup) == []
    assert str(soup) == html


def test_notes_map_to_their_own_root():
    # Sabotage: key by list index, or match owners by equality instead of identity.
    html = (
        '<div class="slide"><p>x</p></div>'
        '<div class="slide"><p>x</p><aside class="speaker-notes">B</aside></div>'
    )
    soup = BeautifulSoup(html, "html.parser")
    popped = pop_speaker_notes(soup)
    roots = find_slide_roots(soup)
    assert len(roots) == 2
    assert [notes_for_root(root, popped) for root in roots] == [None, "B"]


def test_notes_for_root_joins_and_keeps_empty_as_empty():
    # Sabotage: return None when every matching text is empty (must clear, not keep).
    html = (
        '<div class="slide"><aside class="speaker-notes"></aside><p>x</p></div>'
        '<div class="slide"><aside class="speaker-notes">One</aside><p>y</p>'
        '<aside class="speaker-notes">Two</aside></div>'
    )
    soup = BeautifulSoup(html, "html.parser")
    popped = pop_speaker_notes(soup)
    roots = find_slide_roots(soup)
    assert [notes_for_root(root, popped) for root in roots] == ["", "One\n\nTwo"]


def test_an_empty_aside_beside_a_filled_one_adds_no_blank_paragraph():
    # Sabotage target: extract_speaker_notes / notes_for_root joining empty texts too.
    html = (
        '<div class="slide"><p>x</p>'
        '<aside class="speaker-notes"></aside>'
        '<aside class="speaker-notes"><p>One.</p></aside></div>'
    )
    out, notes = extract_speaker_notes(html)
    assert out == '<div class="slide"><p>x</p></div>'
    assert notes == "One."
    soup = BeautifulSoup(html, "html.parser")
    popped = pop_speaker_notes(soup)
    (root,) = find_slide_roots(soup)
    assert notes_for_root(root, popped) == "One."


# ---------------------------------------------------------------------------
# Talk track beside the notes (presenter plan, Task 1): the back-compatible
# helpers pop BOTH asides, so a talk-track aside never leaks into slide HTML.
# The builder marks asides with data-presenter="talk-track|speaker-notes"; the
# class forms stay accepted.
# ---------------------------------------------------------------------------


def test_pop_speaker_notes_also_removes_talk_track_asides():
    # Sabotage target: pop_speaker_notes popping only speaker-notes asides (the
    # talk-track aside would stay in every parsed slide's HTML).
    html = (
        '<div class="slide"><p>x</p><aside data-presenter="talk-track" hidden><p>Say it.</p></aside>'
        '<aside data-presenter="speaker-notes" hidden>Check Q2.</aside></div>'
    )
    soup = BeautifulSoup(html, "html.parser")
    popped = pop_speaker_notes(soup)
    assert [text for _, text in popped] == ["Check Q2."]
    assert soup.find("aside") is None
    assert str(soup) == '<div class="slide"><p>x</p></div>'


def test_a_sibling_talk_track_lets_the_wrapper_promote():
    # The talk track uses the same ownership rule: a section holding only the
    # slide and the aside is promoted once the aside is popped.
    from src.utils.html_utils import pop_presenter_asides, text_for_root

    html = (
        '<section class="dark"><div class="slide"><p>x</p></div>'
        '<aside class="talk-track">Say it.</aside></section>'
    )
    soup = BeautifulSoup(html, "html.parser")
    popped = pop_presenter_asides(soup)
    assert soup.find("aside") is None
    (root,) = find_slide_roots(soup)
    assert root.name == "section"
    assert text_for_root(root, popped["talk_track"]) == "Say it."
    assert text_for_root(root, popped["speaker_notes"]) is None


@pytest.mark.parametrize(
    "talk_attr,notes_attr",
    [
        ('data-presenter="talk-track" hidden', 'data-presenter="speaker-notes" hidden'),
        ('class="talk-track"', 'class="speaker-notes"'),
        ('data-presenter="talk-track" hidden', 'class="speaker-notes"'),
    ],
    ids=["data-presenter", "class", "mixed"],
)
def test_both_sibling_asides_in_a_wrapping_section_are_owned(talk_attr, notes_attr):
    # Sabotage target: a per-marker ownership check whose "only other element child
    # is the .slide" rule counts the OTHER presenter aside, so a section holding the
    # slide plus both asides owns neither and both leak into the slide HTML.
    from src.utils.html_utils import extract_presenter_text, pop_presenter_asides, text_for_root

    html = (
        '<section class="dark"><div class="slide"><p>x</p></div>'
        f'<aside {talk_attr}>Say it.</aside>'
        f'<aside {notes_attr}>Check Q2.</aside></section>'
    )
    out, notes, talk = extract_presenter_text(html)
    assert out == '<section class="dark"><div class="slide"><p>x</p></div></section>'
    assert (notes, talk) == ("Check Q2.", "Say it.")

    soup = BeautifulSoup(html, "html.parser")
    popped = pop_presenter_asides(soup)
    (root,) = find_slide_roots(soup)
    assert root.name == "section"
    assert text_for_root(root, popped["talk_track"]) == "Say it."
    assert text_for_root(root, popped["speaker_notes"]) == "Check Q2."


def test_other_asides_beside_presenter_asides_are_untouched():
    html = (
        '<div class="slide"><aside class="callout">c</aside><aside data-presenter="other">o</aside>'
        '<aside data-presenter="talk-track">T</aside><aside class="speaker-notes">S</aside></div>'
    )
    out, notes = extract_speaker_notes(html)
    assert out == (
        '<div class="slide"><aside class="callout">c</aside><aside data-presenter="other">o</aside></div>'
    )
    assert notes == "S"
