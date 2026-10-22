"""`src.domain.deck_spec_slides` — the blank shell, the blank predicates, the spec splice.

#314 follow-up, Task 1 (plan `docs/superpowers/plans/2026-10-19-issue-314-manual-insert-slide.md`
D1/D3/D4, with PLAN-CORRECTIONS C2-C6 and the supervisor's revised C3 overriding it).

What these tests pin, and why
-----------------------------
**The shell is a structural copy of THIS deck's frame.**  A bare `<div class="slide"></div>`
paints only where the ground sits on `.slide` (Meridian).  On the shipped design system the
ground is on a `<section>` wrapper, and unpinned graph decks carry an inline `style` ground with
no deck CSS, so in both a bare div is a white box.  Every shell assertion compares the WHOLE
output string.

**Which slide's frame is copied (revised C3).**  The most common FULL candidate shell (chain
tags + class tokens + data-label + style) wins, not the tag/class signature alone: on an
inline-styled deck every slide has the same signature, so the style is what tells a content
ground from the cover.  A tie goes to the nearest slide holding a tied candidate (scan
`position-1 ... 0`, then `position ... n-1`; at position 0, `0 ... n-1`), never slide 0 (the
cover) while another slide holds a tied candidate.

**Safety.**  Only `class`, `data-label` and `style` survive, `style` verbatim (C2: the scanner
does not flag `url(javascript:...)` and the CSP enforces at render, so the shell keeps it).  A
shell that trips the scanner, or that has no `<div>` slide wrapper, is the bare div.

**One predicate, two languages (C4).**  `tests/fixtures/blank_slide_cases.json` is read here
and by Task 7's vitest.  Whitespace is HTML ASCII whitespace only (`str.strip()` and JS
`trim()` disagree with each other, and with HTML, on U+FEFF, U+0085, U+001C, U+00A0...); the
`slide` class token match is case-sensitive.

**The spec splice keeps today's raw-dict semantics** (D3): `{}` and a dict without a slides
list are left alone, `{"slides": []}` gains the entry, unknown keys and invalid shapes are
kept, and the blank entry is a deep copy (C5).
"""
from __future__ import annotations

import contextlib
import copy
import json
import logging
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup, Tag
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — register all ORM models
from src.api.routes.export import build_slide_html
from src.api.services import chat_service
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import SessionSlideDeck, UserSession
from src.domain import deck_spec_slides
from src.domain.deck_spec import SlideSpec
from src.domain.deck_spec_slides import (
    BLANK_DECK_SPEC_ENTRY,
    BLANK_SLIDE_HTML,
    blank_slide_shell,
    is_blank_slide_html,
    is_blank_slide_spec,
    renumber_spec_slides,
    splice_blank_entry,
    spec_json_with_blank_entry,
)
from src.domain.slide import Slide, has_slide_wrapper
from src.domain.slide_deck import SlideDeck
from src.utils.html_safety import scan_html_for_unsafe_patterns
from src.utils.html_utils import find_slide_roots
from src.utils.slide_hash import compute_slide_hash

_REPO = Path(__file__).resolve().parents[2]
_CASES_PATH = _REPO / "tests" / "fixtures" / "blank_slide_cases.json"
_WRAPPED_PATH = _REPO / "tests" / "fixtures" / "export_slide_root" / "wrapped_bare_slide.html"
_BANNER_PATH = _REPO / "tests" / "fixtures" / "export_inline_svg" / "slide_banner.html"
_MERIDIAN = _REPO / "evals" / "fixtures" / "meridian"

_BLANK_ENTRY = {
    "purpose": "",
    "content_brief": "",
    "assumes": "",
    "hands_off": "",
    "data_references": [],
}


def _body_fragments(path: Path) -> List[str]:
    """Each top-level element of the fixture's <body>, serialised as a slide's html."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    body = soup.body or soup
    return [str(child) for child in body.children if isinstance(child, Tag)]


def _fixture_css(path: Path) -> str:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    return "\n".join(tag.string for tag in soup.find_all("style") if tag.string)


def _inline(style: str, body: str = "<h2>Body</h2>") -> str:
    return f'<div class="slide" style="{style}">{body}</div>'


def _shell(style: str) -> str:
    return f'<div class="slide" style="{style}"></div>'


# ---------------------------------------------------------------------------
# Deck families
# ---------------------------------------------------------------------------

#: (a) The shipped design system: the ground is painted on a <section> wrapper.
_WRAPPED = _body_fragments(_WRAPPED_PATH)[0]
_WRAPPED_SHELL = '<section data-label="Acme Ground"><div class="slide"></div></section>'

#: (a2) slide-surface-fidelity's DS_WRAPPED shape.
_DS_WRAPPED = (
    '<section data-label="Ground"><div class="slide"><h1 class="headline">Acme Quarterly</h1>'
    '<p class="bodycopy">Body copy.</p></div></section>'
)

#: (b) Unpinned graph deck: inline grounds, no deck CSS (probe b1/b2).
_COVER = (
    "background:linear-gradient(135deg,#0b1f3a,#123b6d);color:#fff;padding:60px;"
    "display:flex;flex-direction:column;justify-content:center"
)
_WHITE = "background:#ffffff;color:#1b3139;padding:48px 64px"
_DARK = "background:#0b1f3a;color:#fff;padding:60px"
_B1 = [
    _inline(_COVER, '<h1 style="font-size:56px">Q3 Review</h1><p>Prepared for the board</p>'),
    _inline(
        _WHITE,
        '<h2>Revenue grew 18%</h2><div style="display:grid;grid-template-columns:1fr 1fr">'
        '<canvas id="c1"></canvas><ul><li>a</li></ul></div>',
    ),
    _inline(_WHITE, "<h2>Costs</h2><p>x</p>"),
    _inline(_DARK, "<h2>Ask</h2>"),
]

#: (b3) A real fixture with an inline ground.
_BANNER = _body_fragments(_BANNER_PATH)[0]
_BANNER_SHELL = (
    '<div class="slide" style="position:relative;width:1280px;height:720px;background:#ffffff;"></div>'
)

#: (c) Meridian: grounds `.slide`, and its slides are <section class="slide"> roots.
_MERIDIAN_GOLD = [
    (_MERIDIAN / "gold" / f"{i}.html").read_text(encoding="utf-8") for i in range(10)
]
_MERIDIAN_TEMPLATE = _body_fragments(_MERIDIAN / "bundle" / "templates" / "standard" / "index.html")


# ---------------------------------------------------------------------------
# The constants
# ---------------------------------------------------------------------------


def test_the_bare_blank_slide_is_the_wrapper_and_nothing_else():
    assert BLANK_SLIDE_HTML == '<div class="slide"></div>'


def test_the_blank_spec_entry_is_the_five_empty_fields():
    assert BLANK_DECK_SPEC_ENTRY == _BLANK_ENTRY


def test_chat_service_re_exports_the_domain_constants_and_the_renumber_core():
    """`test_insert_slide_service.py` imports BLANK_SLIDE_HTML from chat_service; the
    plan makes `_BLANK_DECK_SPEC_ENTRY` an alias, so there is one definition of each."""
    assert chat_service.BLANK_SLIDE_HTML is deck_spec_slides.BLANK_SLIDE_HTML
    assert chat_service._BLANK_DECK_SPEC_ENTRY is deck_spec_slides.BLANK_DECK_SPEC_ENTRY
    assert chat_service.renumber_spec_slides is deck_spec_slides.renumber_spec_slides


# ---------------------------------------------------------------------------
# blank_slide_shell — the three fixture families
# ---------------------------------------------------------------------------


def test_section_wrapper_deck_gets_its_wrapper_with_the_label_and_no_content():
    assert blank_slide_shell([_WRAPPED, _WRAPPED, _WRAPPED], 1) == _WRAPPED_SHELL


def test_section_wrapper_deck_appending_copies_the_wrapper():
    assert blank_slide_shell([_DS_WRAPPED] * 3, 3) == (
        '<section data-label="Ground"><div class="slide"></div></section>'
    )


def test_inline_styled_deck_keeps_the_ground_style_verbatim():
    deck = [_inline(_DARK, f"<h1>Slide {i}</h1>") for i in range(3)]
    assert blank_slide_shell(deck, 1) == _shell(_DARK)


def test_inline_styled_fixture_keeps_its_ground_style_verbatim():
    assert blank_slide_shell([_BANNER, _BANNER], 2) == _BANNER_SHELL


def test_meridian_gold_falls_back_to_the_bare_div():
    """Every candidate is `<section class="slide ...">`, which has_slide_wrapper (div only)
    rejects; Meridian's `.slide{background}` still paints the bare div."""
    assert blank_slide_shell(_MERIDIAN_GOLD, 4) == BLANK_SLIDE_HTML


def test_meridian_template_sections_fall_back_to_the_bare_div():
    assert len(_MERIDIAN_TEMPLATE) == 4
    assert blank_slide_shell(_MERIDIAN_TEMPLATE, 2) == BLANK_SLIDE_HTML


# ---------------------------------------------------------------------------
# blank_slide_shell — which slide's frame is copied (revised C3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("position", [0, 1, 2, 3, 4])
def test_the_most_common_ground_wins_over_the_cover_at_every_position(position):
    """Probe b1: gradient cover, two white content slides, a dark closer.  Every slide has
    the same tag/class signature, so only the full candidate (with its style) can tell the
    content ground (2 of 4) from the cover — inserting right after the cover included."""
    assert blank_slide_shell(_B1, position) == _shell(_WHITE)


def test_the_majority_beats_the_neighbour():
    m = "background:#f4f4f4;color:#111"
    n = "background:#000;color:#fff"
    deck = [_inline(m), _inline(m), _inline(m), _inline(n)]
    assert blank_slide_shell(deck, 4) == _shell(m)
    assert blank_slide_shell(deck, 3) == _shell(m)


def test_the_majority_beats_the_first_slide():
    m = "background:#f4f4f4;color:#111"
    n = "background:#000;color:#fff"
    assert blank_slide_shell([_inline(n), _inline(m), _inline(m)], 3) == _shell(m)


def test_the_data_label_is_part_of_the_candidate():
    title = '<section data-label="Title Ground"><div class="slide"><h1>Title</h1></div></section>'
    content = '<section data-label="Content Ground"><div class="slide"><h2>Body</h2></div></section>'
    assert blank_slide_shell([title, content, content], 1) == (
        '<section data-label="Content Ground"><div class="slide"></div></section>'
    )


def test_the_class_tokens_are_part_of_the_candidate():
    deck = [
        '<div class="slide dark"><h1>Cover</h1></div>',
        '<div class="slide light"><h2>One</h2></div>',
        '<div class="slide light"><h2>Two</h2></div>',
    ]
    assert blank_slide_shell(deck, 1) == '<div class="slide light"></div>'


_C0 = "background:#c0c0c0"
_SA = "background:#aa0000"
_SB = "background:#00bb00"
_SC = "background:#0000cc"
_ALL_DISTINCT = [_inline(_C0), _inline(_SA), _inline(_SB), _inline(_SC)]


@pytest.mark.parametrize(
    "position, expected_style",
    [
        (0, _SA),  # at 0 the scan is 0..n-1, and the cover is excluded
        (1, _SA),  # before: only the cover, excluded; then after: slide 1
        (2, _SA),  # before wins: slide 1
        (3, _SB),  # before wins: slide 2
        (4, _SC),  # append: slide 3
    ],
)
def test_an_all_distinct_deck_copies_the_nearest_non_cover_slide(position, expected_style):
    """Every slide's candidate is unique, so all four tie (the revised-C3 residual)."""
    assert blank_slide_shell(_ALL_DISTINCT, position) == _shell(expected_style)


_X = "background:#101010;color:#fafafa"
_Y = "background:#fafafa;color:#101010"
_Z = "background:#808080"
_XYYXZ = [_inline(_X), _inline(_Y), _inline(_Y), _inline(_X), _inline(_Z)]


@pytest.mark.parametrize(
    "position, expected_style",
    [
        (0, _Y),  # scan 0 (cover, excluded: slides 1-3 hold tied candidates), 1 -> Y
        (1, _Y),  # scan 0 (excluded), then 1 -> Y
        (3, _Y),  # scan 2 -> Y
        (4, _X),  # scan 3 -> X
        (5, _X),  # scan 4 (Z is not tied, skipped), 3 -> X
    ],
)
def test_a_tie_goes_to_the_nearest_slide_holding_a_tied_candidate(position, expected_style):
    """X is on slides 0 and 3, Y on 1 and 2 (both twice); Z once, so never a winner."""
    assert blank_slide_shell(_XYYXZ, position) == _shell(expected_style)


def test_a_one_slide_deck_copies_its_only_slide():
    """No tie, so nothing excludes the cover: the C3 residual on a one-slide deck."""
    assert blank_slide_shell([_inline(_COVER, "<h1>Q3</h1>")], 1) == _shell(_COVER)


def test_slides_without_a_slide_element_are_skipped():
    deck = ["<p>Speaker notes only</p>", "", _inline(_DARK), _inline(_DARK)]
    assert blank_slide_shell(deck, 0) == _shell(_DARK)


@pytest.mark.parametrize(
    "deck",
    [
        [],
        ['<div class="x"><h1>a</h1></div>', "<p>b</p>"],
        [""],
    ],
    ids=["empty deck", "no .slide anywhere", "one empty slide"],
)
def test_a_deck_with_no_slide_element_gets_the_bare_div(deck):
    assert blank_slide_shell(deck, 0) == BLANK_SLIDE_HTML


def test_the_slide_class_token_is_case_sensitive():
    """C4: `class="Slide"` is not a slide; has_slide_wrapper's regex is /i, so only the
    token match can refuse it, and a shell built from it would not be a blank row."""
    deck = ['<div class="Slide" style="background:#000"><h1>a</h1></div>'] * 2
    assert blank_slide_shell(deck, 1) == BLANK_SLIDE_HTML


# ---------------------------------------------------------------------------
# blank_slide_shell — what is kept, what is stripped
# ---------------------------------------------------------------------------


def test_id_event_handlers_and_other_data_attributes_are_dropped():
    hostile = (
        '<div class="slide dark" id="x" onclick="evil()" data-x="1" data-label="L" '
        'style="background:#000"><h1>t</h1></div>'
    )
    assert blank_slide_shell([hostile, hostile], 1) == (
        '<div class="slide dark" data-label="L" style="background:#000"></div>'
    )


def test_every_chain_element_is_stripped_and_off_chain_children_dropped():
    slide = (
        '<section id="s" class="ground" data-label="G" data-testid="t" aria-label="a" '
        'style="background:#123" onmouseover="x()"><header>H</header>'
        '<div class="slide hero" data-label="inner" style="padding:4px" hidden><h1>t</h1></div>'
        "<footer>f</footer></section>"
    )
    assert blank_slide_shell([slide, slide], 2) == (
        '<section class="ground" data-label="G" style="background:#123">'
        '<div class="slide hero" data-label="inner" style="padding:4px"></div></section>'
    )


def test_a_three_level_chain_is_rebuilt_whole():
    slide = (
        '<section data-label="G"><div class="frame" style="padding:8px">'
        '<div class="slide"><p>x</p></div><aside>note</aside></div></section>'
    )
    assert blank_slide_shell([slide], 1) == (
        '<section data-label="G"><div class="frame" style="padding:8px">'
        '<div class="slide"></div></div></section>'
    )


def test_comments_whitespace_and_sibling_scripts_are_not_part_of_the_chain():
    slide = (
        '\n<!-- generated -->\n<section data-label="G"><div class="slide">'
        '<canvas id="c9"></canvas></div></section>\n<script>new Chart(1)</script>\n'
    )
    assert blank_slide_shell([slide, slide], 0) == (
        '<section data-label="G"><div class="slide"></div></section>'
    )


@pytest.mark.parametrize(
    "style",
    [
        "background:url('{{image:3}}') center/cover;color:#fff",
        "background:url(https://cdn.example.com/ground.png)",
        "background:url(javascript:alert(1))",  # C2: the scanner does not flag it; kept
    ],
    ids=["image placeholder", "external url", "url(javascript:) (C2)"],
)
def test_a_url_style_is_kept_verbatim(style):
    assert blank_slide_shell([_inline(style), _inline(style)], 1) == _shell(style)


@pytest.mark.parametrize(
    "style",
    [
        "width:expression(eval(1))",  # eval
        "background:url(x);fetch(1)",  # fetch
        "javascript:alert(1)",  # javascript: URI
        "color:red; onload=1",  # inline event handler
    ],
    ids=["eval", "fetch", "javascript: URI", "inline event handler"],
)
def test_a_style_the_scanner_flags_gives_the_bare_div(style):
    """C2's fixtures: each really trips scan_html_for_unsafe_patterns."""
    assert scan_html_for_unsafe_patterns(_shell(style)) != []
    assert blank_slide_shell([_inline(style), _inline(style)], 1) == BLANK_SLIDE_HTML


def test_a_data_label_the_scanner_flags_gives_the_bare_div():
    slide = '<section data-label="x fetch(1)"><div class="slide"><h1>a</h1></div></section>'
    assert blank_slide_shell([slide, slide], 1) == BLANK_SLIDE_HTML


@pytest.mark.parametrize(
    "slide",
    [
        # has_slide_wrapper's regex is case-insensitive, so the ancestor's class="SLIDE"
        # satisfies it while the real .slide (the chain's end) is a <span>.
        '<div class="SLIDE" style="background:#000"><span class="slide"><h1>t</h1></span></div>',
        # html.parser and browsers both read `div"x` as the tag NAME, and `<div\b` still
        # matches it: copying that tag would give a slide whose .slide is not a <div>.
        '<div"x class="slide" style="background:#000"><h1>t</h1></div>',
    ],
    ids=["upper-case SLIDE ancestor, span.slide", "malformed div tag name"],
)
def test_a_winner_whose_slide_is_not_a_div_gives_the_bare_div(slide):
    """The check is "the winner is a blank row", not merely "has_slide_wrapper passes":
    every shell must be a blank row, or the architect would treat the blank as content."""
    assert has_slide_wrapper(slide)
    assert blank_slide_shell([slide, slide], 1) == BLANK_SLIDE_HTML


def test_the_scan_judges_the_winning_candidate_not_the_next_best():
    """The plan's order is choose, then check, then bare — not 'skip unsafe candidates'."""
    flagged = "width:expression(eval(1))"
    deck = [_inline(flagged), _inline(flagged), _inline(_WHITE)]
    assert blank_slide_shell(deck, 3) == BLANK_SLIDE_HTML


# ---------------------------------------------------------------------------
# Every shell is a safe blank row that survives the deck's round trips
# ---------------------------------------------------------------------------

_SHELL_DECKS = [
    ("wrapped fixture", [_WRAPPED] * 3, 1),
    ("DS_WRAPPED", [_DS_WRAPPED] * 3, 3),
    ("b1 after the cover", _B1, 1),
    ("b1 append", _B1, 4),
    ("banner fixture", [_BANNER] * 2, 2),
    ("all distinct", _ALL_DISTINCT, 2),
    ("meridian gold", _MERIDIAN_GOLD, 4),
    ("empty deck", [], 0),
    (
        "hostile attributes",
        [
            '<div class="slide dark" id="x" onclick="evil()" data-x="1" data-label="L" '
            'style="background:#000"><h1>t</h1></div>'
        ]
        * 2,
        1,
    ),
    ("url(javascript:) kept", [_inline("background:url(javascript:alert(1))")] * 2, 1),
    (
        "span.slide under an upper-case SLIDE div",
        ['<div class="SLIDE" style="background:#000"><span class="slide"><h1>t</h1></span></div>']
        * 2,
        1,
    ),
]


@pytest.mark.parametrize(
    "slides, position", [(s, p) for _, s, p in _SHELL_DECKS], ids=[n for n, _, _ in _SHELL_DECKS]
)
def test_every_shell_is_a_safe_blank_row_that_reparses_to_itself(slides, position):
    shell = blank_slide_shell(slides, position)
    assert has_slide_wrapper(shell)
    assert scan_html_for_unsafe_patterns(shell) == []
    assert is_blank_slide_html(shell) is True
    assert str(BeautifulSoup(shell, "html.parser")) == shell


_ROUND_TRIP_DECKS = [
    ("wrapped fixture", [_WRAPPED] * 3, 1, _WRAPPED_SHELL),
    ("b1 after the cover", _B1, 1, _shell(_WHITE)),
    ("banner fixture", [_BANNER] * 2, 2, _BANNER_SHELL),
]


@pytest.mark.parametrize(
    "slides, position, shell",
    [(s, p, sh) for _, s, p, sh in _ROUND_TRIP_DECKS],
    ids=[n for n, _, _, _ in _ROUND_TRIP_DECKS],
)
def test_the_shell_survives_knit_and_reparse_byte_identically(slides, position, shell):
    """`find_slide_roots` promotes the <section> to the root, so the knitted deck reads back
    the same slides, the shell among them, with the same content hash."""
    assert blank_slide_shell(slides, position) == shell
    htmls = slides[:position] + [shell] + slides[position:]
    deck = SlideDeck(
        title="t",
        css="",
        slides=[Slide(html=h, slide_id=f"s{i}") for i, h in enumerate(htmls)],
    )
    back = [s.html for s in SlideDeck.from_html_string(deck.knit()).slides]
    assert back == htmls
    assert compute_slide_hash(back[position]) == compute_slide_hash(shell)


@pytest.fixture()
def factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _fake_db(factory):
    @contextlib.contextmanager
    def _cm():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _cm


@pytest.mark.parametrize(
    "slides, position, shell",
    [(s, p, sh) for _, s, p, sh in _ROUND_TRIP_DECKS],
    ids=[n for n, _, _, _ in _ROUND_TRIP_DECKS],
)
def test_the_shell_row_round_trips_with_a_stable_content_hash(factory, slides, position, shell):
    """Task 3 compares `(slide_id, compute_slide_hash(cached html))` with the rows' hashes, so
    a shell that changed under save -> read would turn the next insert into a 409."""
    db = factory()
    owner = UserSession(session_id="shell-rt", created_by="a@b.c")
    db.add(owner)
    db.flush()
    db.add(SessionSlideDeck(session_id=owner.id, html_content="", slide_count=0, version=1))
    db.commit()
    db.close()

    htmls = slides[:position] + [blank_slide_shell(slides, position)] + slides[position:]
    deck = SlideDeck(
        title="t",
        css="",
        slides=[Slide(html=h, slide_id=f"s{i}") for i, h in enumerate(htmls)],
    )
    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)), patch(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    ):
        manager = SessionManager()
        manager.save_slide_deck(
            session_id="shell-rt",
            title="t",
            html_content=deck.knit(),
            scripts_content="",
            slide_count=len(htmls),
            deck_dict=deck.to_dict(),
        )
        got = manager.get_slide_deck("shell-rt")

    assert [(s["html"], s["content_hash"]) for s in got["slides"]] == [
        (h, compute_slide_hash(h)) for h in htmls
    ]
    assert got["slides"][position]["html"] == shell


def test_export_smoke_renders_a_deck_holding_the_wrapper_shell():
    """SMOKE ONLY (pre-brief): this shows the export keeps a childless wrapper as the slide
    root and carries the deck CSS. No product sabotage exists for it; it is not shell coverage."""
    css = _fixture_css(_WRAPPED_PATH)
    shell = blank_slide_shell([_WRAPPED, _WRAPPED], 1)
    deck = {
        "title": "Acme",
        "css": css,
        "scripts": "",
        "external_scripts": [],
        "slides": [
            {"slide_id": "a", "html": _WRAPPED},
            {"slide_id": "new", "html": shell},
            {"slide_id": "b", "html": _WRAPPED},
        ],
    }
    out = build_slide_html({"slide_id": "new", "html": shell}, deck)
    assert css in out
    roots = find_slide_roots(BeautifulSoup(out, "html.parser"))
    assert [str(r) for r in roots] == [_WRAPPED_SHELL]


# ---------------------------------------------------------------------------
# is_blank_slide_html / is_blank_slide_spec — the shared case table (C4)
# ---------------------------------------------------------------------------

_CASES = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
_HTML_CASES: List[Dict[str, Any]] = _CASES["html_cases"]
_SPEC_CASES: List[Dict[str, Any]] = _CASES["spec_cases"]


def test_the_case_table_is_well_formed_for_both_consumers():
    for rows, keys in (
        (_HTML_CASES, {"name", "html", "blank"}),
        (_SPEC_CASES, {"name", "purpose", "content_brief", "blank"}),
    ):
        names = [r["name"] for r in rows]
        assert len(names) == len(set(names))
        assert all(set(r) == keys for r in rows)
        assert all(isinstance(r["blank"], bool) for r in rows)
        assert {r["blank"] for r in rows} == {True, False}


def test_the_case_table_carries_the_plan_and_c4_rows():
    rows = {(r["html"], r["blank"]) for r in _HTML_CASES}
    required = {
        ('<div class="slide"></div>', True),
        ('<section data-label="Acme Ground"><div class="slide"></div></section>', True),
        ('<section><div class="w"><div class="slide"></div></div></section>', True),
        ('<div class="slide dark"></div>', True),
        ('<div class="slide" style="background:url(\'{{image:3}}\') center/cover"></div>', True),
        ('<div class="slide">\n  <!-- empty -->\n</div>', True),
        ('\n<!-- shell -->\n<div class="slide"></div>\n', True),
        ('<div class="slide">hi</div>', False),
        ('<div class="slide"><img src="data:image/png;base64,AAAA"></div>', False),
        ('<div class="slide"></div><script></script>', False),
        ('<div class="slide"></div><div></div>', False),
        ('<div class="slide"><div></div></div>', False),
        ('<div class="x"></div>', False),
        ('<section class="slide"></section>', False),
        ('<div class="slide">&nbsp;</div>', False),
        ('<div class="slide">﻿</div>', False),
        ('<div class="Slide"></div>', False),
        # The chain's .slide must itself be a <div>: has_slide_wrapper is a raw-string
        # regex, so a wrapper inside a comment or an attribute value satisfies it.
        (
            '<!-- <div class="slide"> --><img class="slide" src="data:image/png;base64,AAAA">',
            False,
        ),
        (
            '<img class="slide" alt=\'<div class="slide">\' src="data:image/png;base64,AAAA">',
            False,
        ),
    }
    assert required <= rows
    specs = {(r["purpose"], r["content_brief"], r["blank"]) for r in _SPEC_CASES}
    assert {("   ", "   ", True), (" ", "", False)} <= specs


@pytest.mark.parametrize("row", _HTML_CASES, ids=[r["name"] for r in _HTML_CASES])
def test_is_blank_slide_html_matches_the_case_table(row):
    assert is_blank_slide_html(row["html"]) is row["blank"]


@pytest.mark.parametrize("row", _SPEC_CASES, ids=[r["name"] for r in _SPEC_CASES])
def test_is_blank_slide_spec_matches_the_case_table(row):
    entry = {"purpose": row["purpose"], "content_brief": row["content_brief"]}
    assert is_blank_slide_spec(entry) is row["blank"]


@pytest.mark.parametrize("row", _SPEC_CASES, ids=[r["name"] for r in _SPEC_CASES])
def test_is_blank_slide_spec_matches_the_case_table_on_a_slide_spec(row):
    spec = SlideSpec(
        position=3,
        purpose=row["purpose"],
        content_brief=row["content_brief"],
        assumes="Assumes the prior slide",
        hands_off="Hands off to the next",
        data_references=["revenue_q3"],
    )
    assert is_blank_slide_spec(spec) is row["blank"]


def test_is_blank_slide_html_of_none_is_false():
    assert is_blank_slide_html(None) is False


def test_missing_spec_keys_count_as_empty():
    assert is_blank_slide_spec({}) is True
    assert is_blank_slide_spec({"position": 2}) is True
    assert is_blank_slide_spec({"content_brief": "x"}) is False
    assert is_blank_slide_spec({"purpose": "x"}) is False


def test_only_purpose_and_brief_decide_blankness():
    entry = {
        "position": 1,
        "purpose": "",
        "content_brief": " ",
        "assumes": "The audience saw slide 1",
        "hands_off": "Pricing",
        "data_references": ["r1"],
        "slide_type": "content",
    }
    assert is_blank_slide_spec(entry) is True


# ---------------------------------------------------------------------------
# renumber_spec_slides — the pure middle of _rewrite_deck_spec_slides, moved verbatim
# ---------------------------------------------------------------------------


def _gapped_spec() -> Dict[str, Any]:
    return {
        "title": "T",
        "extra": {"kept": [1, 2]},
        "slides": [
            {"position": 5, "purpose": "E", "content_brief": "e"},
            "junk",
            {"position": 0, "purpose": "A", "content_brief": "a"},
            {"purpose": "no position"},
            {"position": 2, "purpose": "C", "content_brief": "c", "unknown": 1},
            {"position": "3", "purpose": "string position"},
        ],
    }


def test_renumber_restamps_a_gapped_spec_and_carries_unpositioned_entries_last():
    assert renumber_spec_slides(_gapped_spec(), lambda entries: entries) == {
        "title": "T",
        "extra": {"kept": [1, 2]},
        "slides": [
            {"position": 0, "purpose": "A", "content_brief": "a"},
            {"position": 1, "purpose": "C", "content_brief": "c", "unknown": 1},
            {"position": 2, "purpose": "E", "content_brief": "e"},
            "junk",
            {"purpose": "no position"},
            {"position": "3", "purpose": "string position"},
        ],
    }


def test_renumber_hands_reorder_the_positioned_entries_in_position_order():
    seen: List[Any] = []

    def reorder(entries):
        seen.append(copy.deepcopy(entries))
        return entries

    renumber_spec_slides(_gapped_spec(), reorder)
    assert seen == [
        [
            {"position": 0, "purpose": "A", "content_brief": "a"},
            {"position": 2, "purpose": "C", "content_brief": "c", "unknown": 1},
            {"position": 5, "purpose": "E", "content_brief": "e"},
        ]
    ]


def test_renumber_stamps_positions_in_the_order_reorder_returns():
    out = renumber_spec_slides(_gapped_spec(), lambda entries: list(reversed(entries)))
    assert out["slides"] == [
        {"position": 0, "purpose": "E", "content_brief": "e"},
        {"position": 1, "purpose": "C", "content_brief": "c", "unknown": 1},
        {"position": 2, "purpose": "A", "content_brief": "a"},
        "junk",
        {"purpose": "no position"},
        {"position": "3", "purpose": "string position"},
    ]


def test_renumber_does_not_mutate_its_input():
    spec = _gapped_spec()
    before = copy.deepcopy(spec)
    out = renumber_spec_slides(spec, lambda entries: list(reversed(entries)))
    assert spec == before
    assert out is not spec


def test_an_entry_returned_twice_becomes_two_independent_entries():
    """Identity is never inferred from equality: a duplicate's two entries are two entries."""
    out = renumber_spec_slides(
        {"slides": [{"position": 0, "purpose": "A"}, {"position": 1, "purpose": "B"}]},
        lambda e: e[:1] + [e[0]] + e[1:],
    )
    assert out == {
        "slides": [
            {"position": 0, "purpose": "A"},
            {"position": 1, "purpose": "A"},
            {"position": 2, "purpose": "B"},
        ]
    }


def test_a_declined_reorder_returns_none_and_leaves_the_spec_alone():
    spec = _gapped_spec()
    before = copy.deepcopy(spec)
    assert renumber_spec_slides(spec, lambda entries: None) is None
    assert spec == before


def test_an_index_error_from_reorder_propagates():
    def reorder(entries):
        raise IndexError(9)

    with pytest.raises(IndexError):
        renumber_spec_slides(_gapped_spec(), reorder)


@pytest.mark.parametrize(
    "spec",
    [{}, {"title": "no slides key"}, {"slides": None}, {"slides": "x"}, {"slides": {"0": {}}}],
    ids=["empty", "no slides key", "slides null", "slides string", "slides dict"],
)
def test_renumber_returns_none_when_slides_is_not_a_list(spec):
    reorder = MagicMock(side_effect=AssertionError("reorder must not run"))
    before = copy.deepcopy(spec)
    assert renumber_spec_slides(spec, reorder) is None
    reorder.assert_not_called()
    assert spec == before


# ---------------------------------------------------------------------------
# splice_blank_entry
# ---------------------------------------------------------------------------

_A = {"position": 0, "purpose": "A", "content_brief": "a"}
_B = {"position": 1, "purpose": "B", "content_brief": "b"}


@pytest.mark.parametrize(
    "position, expected",
    [
        (0, [_BLANK_ENTRY, _A, _B]),
        (1, [_A, _BLANK_ENTRY, _B]),
        (2, [_A, _B, _BLANK_ENTRY]),
        (9, [_A, _B, _BLANK_ENTRY]),
    ],
    ids=["at 0", "mid", "end", "past the end"],
)
def test_splice_places_the_blank_entry_at_the_clamped_position(position, expected):
    entries = [dict(_A), dict(_B)]
    assert splice_blank_entry(entries, position) == expected
    assert entries == [_A, _B]


@pytest.mark.parametrize("position", [0, 3])
def test_splice_into_no_entries_gives_just_the_blank(position):
    assert splice_blank_entry([], position) == [_BLANK_ENTRY]


def test_the_spliced_blank_is_a_deep_copy_of_the_constant():
    """C5: `dict(BLANK_DECK_SPEC_ENTRY)` would share `data_references` with the constant."""
    pristine = copy.deepcopy(BLANK_DECK_SPEC_ENTRY)
    try:
        first = splice_blank_entry([], 0)[0]
        first["data_references"].append("leaked")
        first["purpose"] = "filled"
        assert BLANK_DECK_SPEC_ENTRY == _BLANK_ENTRY
        assert splice_blank_entry([], 0) == [_BLANK_ENTRY]
    finally:
        BLANK_DECK_SPEC_ENTRY.clear()
        BLANK_DECK_SPEC_ENTRY.update(pristine)


# ---------------------------------------------------------------------------
# spec_json_with_blank_entry — the raw column in, the raw column out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "not json",
        "[]",
        "{}",
        "null",
        '"a string"',
        "42",
        '{"title": "no slides key"}',
        '{"slides": "x"}',
        '{"slides": null}',
    ],
)
def test_specs_without_a_slides_list_are_left_untouched(raw):
    """None means 'leave the column alone' (D3/n3), so legacy decks still insert."""
    assert spec_json_with_blank_entry(raw, 1) is None


@pytest.mark.parametrize("position", [0, 4])
def test_an_empty_slides_list_gains_the_entry(position):
    out = spec_json_with_blank_entry('{"slides": []}', position)
    assert isinstance(out, str)
    assert json.loads(out) == {"slides": [{**_BLANK_ENTRY, "position": 0}]}


def test_the_blank_entry_lands_mid_spec_and_later_entries_shift():
    raw = json.dumps(
        {
            "title": "Deck",
            "unknown_top_level": {"x": [1]},
            "slides": [
                {"position": 0, "purpose": "A", "content_brief": "a", "custom": True},
                {"position": 1, "purpose": "B", "content_brief": "b"},
            ],
        }
    )
    assert json.loads(spec_json_with_blank_entry(raw, 1)) == {
        "title": "Deck",
        "unknown_top_level": {"x": [1]},
        "slides": [
            {"position": 0, "purpose": "A", "content_brief": "a", "custom": True},
            {**_BLANK_ENTRY, "position": 1},
            {"position": 2, "purpose": "B", "content_brief": "b"},
        ],
    }


def test_an_invalid_shape_is_renumbered_not_destroyed():
    raw = json.dumps(
        {
            "slides": [
                {"position": 2, "purpose": "C"},
                "not an entry",
                {"position": 0, "content_brief": "only a brief", "slide_type": 7},
                {"purpose": "unpositioned"},
            ]
        }
    )
    assert json.loads(spec_json_with_blank_entry(raw, 1)) == {
        "slides": [
            {"position": 0, "content_brief": "only a brief", "slide_type": 7},
            {**_BLANK_ENTRY, "position": 1},
            {"position": 2, "purpose": "C"},
            "not an entry",
            {"purpose": "unpositioned"},
        ]
    }


def test_a_drifted_short_spec_is_spliced_at_the_clamp():
    raw = json.dumps({"slides": [{"position": 0, "purpose": "A"}, {"position": 1, "purpose": "B"}]})
    assert json.loads(spec_json_with_blank_entry(raw, 5)) == {
        "slides": [
            {"position": 0, "purpose": "A"},
            {"position": 1, "purpose": "B"},
            {**_BLANK_ENTRY, "position": 2},
        ]
    }


def test_insert_at_zero_shifts_every_entry():
    raw = json.dumps({"slides": [{"position": 0, "purpose": "A"}, {"position": 1, "purpose": "B"}]})
    assert json.loads(spec_json_with_blank_entry(raw, 0)) == {
        "slides": [
            {**_BLANK_ENTRY, "position": 0},
            {"position": 1, "purpose": "A"},
            {"position": 2, "purpose": "B"},
        ]
    }


# ---------------------------------------------------------------------------
# ChatService._rewrite_deck_spec_slides keeps its guards around the pure call (C6)
# ---------------------------------------------------------------------------

_SID = "rewrite-sid"
_CS_LOGGER = "src.api.services.chat_service"


@contextlib.contextmanager
def _rewrite_env(spec: Any, *, read_error: Exception = None, write_error: Exception = None):
    read = MagicMock(return_value=spec, side_effect=read_error)
    write = MagicMock(return_value={"version": 7}, side_effect=write_error)
    with patch("src.api.services.deck_level_writer.read_deck_spec", read), patch(
        "src.api.services.deck_level_writer.write_deck_level_columns", write
    ), patch("src.api.services.chat_service.get_current_username", return_value="author@x.com"):
        yield write


def _warnings(caplog) -> List[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _CS_LOGGER and r.levelno == logging.WARNING]


def test_the_method_delegates_its_middle_to_renumber_spec_slides():
    """One primitive (D3): the method's write receives exactly what the pure core returned."""
    spec = {"slides": [{"position": 0, "purpose": "A"}]}
    produced = {"slides": [{"position": 0, "purpose": "FROM-THE-PURE-CORE"}]}
    core = MagicMock(return_value=produced)
    with _rewrite_env(spec) as write, patch(
        "src.api.services.chat_service.renumber_spec_slides", core
    ):
        result = ChatService()._rewrite_deck_spec_slides(_SID, lambda e: e, label="insert_slide")
    assert result == {"version": 7}
    assert core.call_count == 1
    assert core.call_args.args[0] == spec
    write.assert_called_once_with(_SID, deck_spec=produced, modified_by="author@x.com")


def test_the_method_writes_the_renumbered_spec_with_the_author():
    spec = {"title": "T", "slides": [{"position": 3, "purpose": "B"}, {"position": 1, "purpose": "A"}]}
    with _rewrite_env(spec) as write:
        ChatService()._rewrite_deck_spec_slides(
            _SID, lambda e: splice_blank_entry(e, 1), label="insert_slide"
        )
    write.assert_called_once_with(
        _SID,
        deck_spec={
            "title": "T",
            "slides": [
                {"position": 0, "purpose": "A"},
                {**_BLANK_ENTRY, "position": 1},
                {"position": 2, "purpose": "B"},
            ],
        },
        modified_by="author@x.com",
    )


def test_the_method_still_warns_when_the_spec_has_no_slides_list(caplog):
    with caplog.at_level(logging.WARNING, logger=_CS_LOGGER), _rewrite_env(
        {"slides": "x"}
    ) as write:
        result = ChatService()._rewrite_deck_spec_slides(_SID, lambda e: e, label="delete_slide")
    assert result is None
    write.assert_not_called()
    [record] = _warnings(caplog)
    assert record.getMessage() == "deck_spec_json has no slides list; leaving it untouched"
    assert (record.session_id, record.route) == (_SID, "delete_slide")


def test_the_method_still_warns_when_the_spec_cannot_answer_the_mutation(caplog):
    spec = {"slides": [{"position": 0}, {"position": 1}, "unpositioned"]}

    def reorder(entries):
        raise IndexError(5)

    with caplog.at_level(logging.WARNING, logger=_CS_LOGGER), _rewrite_env(spec) as write:
        result = ChatService()._rewrite_deck_spec_slides(_SID, reorder, label="delete_slide")
    assert result is None
    write.assert_not_called()
    [record] = _warnings(caplog)
    assert record.getMessage() == (
        "deck spec has 2 entries and cannot answer this mutation; leaving it untouched"
    )
    assert (record.session_id, record.route) == (_SID, "delete_slide")


@pytest.mark.parametrize("spec", [None, {}], ids=["no spec", "empty spec"])
def test_the_method_leaves_a_missing_spec_alone_silently(caplog, spec):
    with caplog.at_level(logging.WARNING, logger=_CS_LOGGER), _rewrite_env(spec) as write:
        result = ChatService()._rewrite_deck_spec_slides(_SID, lambda e: e, label="insert_slide")
    assert result is None
    write.assert_not_called()
    assert _warnings(caplog) == []


def test_the_method_swallows_a_declined_reorder_silently(caplog):
    with caplog.at_level(logging.WARNING, logger=_CS_LOGGER), _rewrite_env(
        {"slides": [{"position": 0}]}
    ) as write:
        result = ChatService()._rewrite_deck_spec_slides(_SID, lambda e: None, label="x")
    assert result is None
    write.assert_not_called()
    assert _warnings(caplog) == []


def test_the_method_swallows_read_and_write_failures_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=_CS_LOGGER):
        with _rewrite_env(None, read_error=RuntimeError("db down")) as write:
            assert ChatService()._rewrite_deck_spec_slides(_SID, lambda e: e, label="r") is None
        write.assert_not_called()
        with _rewrite_env({"slides": []}, write_error=RuntimeError("disk full")):
            assert ChatService()._rewrite_deck_spec_slides(_SID, lambda e: e, label="w") is None
    assert [r.getMessage() for r in _warnings(caplog)] == [
        "Failed to read deck spec (r): db down",
        "Failed to write deck spec (w): disk full",
    ]
