"""Server-side export documents pin the slide root to the 1280x720 frame origin.

dsv2 battery F3: model-authored deck CSS routinely styles the slide root like a
print-preview card (``.slide { margin: 32px auto }``). Every export document
force-wraps the slide at exactly 1280x720 with ``overflow: hidden``, so an
outer margin that survives into the document shifts the root inside the clip
rect and silently truncates the bottom edge of the export. Presentation mode
already neutralizes root margins; the huashu/from-html document (built here on
the server) must do the same so preview and export agree (WYSIWYG).

All fixtures synthetic.
"""

from src.api.routes.export import build_slide_html

_MARGINED_DECK = {
    "title": "Synthetic Deck",
    "css": ".slide { margin: 32px auto; width: 1280px; height: 720px; }",
    "scripts": "",
    "external_scripts": [],
}
_SLIDE = {"slide_id": "s1", "html": '<div class="slide">probe</div>'}


def test_slide_root_outer_margin_is_neutralized_after_deck_css():
    html = build_slide_html(_SLIDE, _MARGINED_DECK)

    # The neutralization rule exists, force-wins (!important), and is emitted
    # AFTER the deck CSS so it beats the deck's own root-margin rule.
    squished = html.replace(" ", "").replace("\n", "")
    rule_pos = squished.index("body>*{margin:0!important")
    deck_pos = squished.index(".slide{margin:32pxauto")
    assert deck_pos < rule_pos


def test_neutralization_present_for_margin_free_decks_too():
    """The rule is unconditional — a static part of the document skeleton."""
    deck = dict(_MARGINED_DECK, css="")
    html = build_slide_html(_SLIDE, deck)
    squished = html.replace(" ", "").replace("\n", "")
    assert "body>*{margin:0!important" in squished
