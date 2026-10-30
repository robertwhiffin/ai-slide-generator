"""Task 2: the pure deck-style module, ``src/domain/deck_style.py``.

The module under test is imported lazily (``_ds()``). Each test then fails on
its own with ``ModuleNotFoundError`` while the module is missing, and the R13
model guard at the bottom runs today.

How the sanitiser's output is compared
--------------------------------------
When the sanitiser removes something, it re-serialises the CSS, and the plan
does not fix that format. So every "cleaned CSS" assertion goes through
``_canon``: it parses the output with tinycss2 and writes it out again, one
rule per line, as ``selector{name:value;name:value}``.

- Whitespace runs collapse to one space. A descendant space is kept, so
  ``.dk-code .kw`` still differs from ``.dk-code.kw``.
- Selector lists are joined with ", ", and combinators are spaced (" > ").
- Comments are skipped, and strings come out in tinycss2's double quotes.
- Rule order, declaration order, every selector and every declaration are
  kept exactly.
- Anything that does not parse as a rule or a declaration raises, so stray
  ``<style>`` text or garbage cannot slip through.

The expected strings are written in that canonical form by hand, so each one
pins the exact set and order of the kept rules and declarations.

When NOTHING is removed, the format is pinned byte for byte instead (C24): the
input object itself comes back.
"""

from __future__ import annotations

import importlib
import json
import re

import pytest
import tinycss2

from src.domain.deck_spec import DeckStyle, DeckStyleComponent


def _ds():
    return importlib.import_module("src.domain.deck_style")


def _sanitise(style, *, active):
    return _ds().sanitise_deck_style(style, design_system_active=active)


def _comp(name, *class_names, html=None):
    snippet = html if html is not None else f'<div class="{" ".join(class_names)}">x</div>'
    return DeckStyleComponent(
        name=name, class_names=list(class_names), use=f"use {name}", example_html=snippet
    )


def _style(css, *components):
    return DeckStyle(css=css, components=list(components))


_WS = re.compile(r"\s+")
_COMBINATOR = re.compile(r"\s*([,>+~])\s*")


def _squash(text):
    return _WS.sub(" ", text).strip()


def _selector(prelude):
    sel = _squash(tinycss2.serialize(prelude))
    return _COMBINATOR.sub(lambda m: ", " if m.group(1) == "," else f" {m.group(1)} ", sel)


def _canon(css):
    """Canonical text of a stylesheet (see the module docstring)."""
    lines = []
    for node in tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True):
        if node.type == "qualified-rule":
            decls = []
            for d in tinycss2.parse_declaration_list(
                node.content, skip_whitespace=True, skip_comments=True
            ):
                if d.type != "declaration":
                    raise AssertionError(
                        f"non-declaration inside {_selector(node.prelude)!r}: {d!r}"
                    )
                important = "!important" if d.important else ""
                decls.append(f"{d.name}:{_squash(tinycss2.serialize(d.value))}{important}")
            lines.append(f"{_selector(node.prelude)}{{{';'.join(decls)}}}")
        elif node.type == "at-rule":
            lines.append(_squash(tinycss2.serialize([node])))
        else:
            raise AssertionError(f"output does not parse as CSS: {node!r}")
    return "\n".join(lines)


def _assert_notes(notes, *needles, count=None):
    """Notes are a non-empty tuple of strings. Each needle is named by some note
    (case-insensitive). ``count`` pins "one note per thing removed"."""
    assert isinstance(notes, tuple) and notes, f"expected notes, got {notes!r}"
    assert all(isinstance(n, str) and n.strip() for n in notes), notes
    for needle in needles:
        assert any(needle.lower() in n.lower() for n in notes), (
            f"no note names {needle!r}: {notes!r}"
        )
    if count is not None:
        assert len(notes) == count, f"expected {count} note(s): {notes!r}"


@pytest.fixture(params=[True, False], ids=["design-system", "no-design-system"])
def active(request):
    """Cases whose outcome does not depend on the design system run in both modes."""
    return request.param


def test_canonical_form_is_strict_enough_to_pin_output():
    # Guard on the helper itself. If _canon were lossy, the exact-CSS
    # assertions below would pass against a broken sanitiser.
    assert _canon(".a .b{x:1}") != _canon(".a.b{x:1}")
    assert _canon(".a{x:1;y:2}") != _canon(".a{y:2;x:1}")
    assert _canon(".a{}") == ".a{}"
    assert _canon(" .a ,.b>c { x : 1 ; } /* c */") == ".a, .b > c{x:1}"
    assert _canon("@media print{.a{x:1}}") == "@media print{.a{x:1}}"
    with pytest.raises(AssertionError):
        _canon("<style>.a{x:1}</style>")
    with pytest.raises(AssertionError):
        _canon(".a{x:1; garbage}")
    with pytest.raises(AssertionError):
        _canon(".a{x:1; .b{y:2}}")
    with pytest.raises(AssertionError):
        _canon(".a{x:1; @media print{y:2}}")


# --- constants and signature -------------------------------------------------


def test_constants():
    ds = _ds()
    assert ds.DECK_STYLE_CLASS_PREFIX == "dk-"
    assert ds.DECK_STYLE_VAR_PREFIX == "--dk-"
    assert ds.DECK_STYLE_TARGET_CHARS == 4000
    assert ds.DECK_STYLE_MAX_CHARS == 10000
    assert ds.DECK_STYLE_MAX_COMPONENTS == 12


def test_design_system_active_is_keyword_only_and_required():
    # It has no default: a caller that forgot it would keep a :root that
    # overwrites the template's :root (R3 / C11).
    ds = _ds()
    style = _style(".dk-a{color:red}", _comp("A", "dk-a"))
    with pytest.raises(TypeError):
        ds.sanitise_deck_style(style, True)
    with pytest.raises(TypeError):
        ds.sanitise_deck_style(style)


# --- sanitiser: at-rules (R3: every at-rule is dropped) ---------------------

_AT_RULES = [
    pytest.param("@import url(https://x/y.css);", "@import", id="import"),
    pytest.param("@import 'https://x/y.css';", "@import", id="import-string"),
    pytest.param(
        "@font-face{font-family:'Brand';src:url(data:font/woff2;base64,AAAA)}",
        "@font-face",
        id="font-face",
    ),
    pytest.param('@charset "utf-8";', "@charset", id="charset"),
    pytest.param(
        "@namespace svg url(http://www.w3.org/2000/svg);", "@namespace", id="namespace"
    ),
    # Replaces the brief's "@media keeps only .dk-a" case (R3): the whole block goes.
    pytest.param("@media (max-width:1px){.dk-a{color:red} p{color:blue}}", "@media", id="media"),
    pytest.param("@MEDIA print{.dk-a{color:red}}", "@media", id="media-upper-case"),
    pytest.param(
        "@keyframes dk-pulse{from{opacity:0}to{opacity:1}}", "@keyframes", id="keyframes"
    ),
    pytest.param("@supports (display:grid){.dk-a{display:grid}}", "@supports", id="supports"),
    pytest.param("@layer dk{.dk-a{color:red}}", "@layer", id="layer-block"),
    pytest.param("@layer base;", "@layer", id="layer-statement"),
    pytest.param("@container (min-width:400px){.dk-a{color:red}}", "@container", id="container"),
    pytest.param("@page{margin:0}", "@page", id="page"),
]


@pytest.mark.parametrize("block, keyword", _AT_RULES)
def test_every_at_rule_is_dropped_with_a_note(block, keyword, active):
    keep = _comp("Keep", "dk-keep")
    out, notes = _sanitise(_style(f"{block}\n.dk-keep{{color:red}}", keep), active=active)
    assert _canon(out.css) == ".dk-keep{color:red}"
    assert out.components == [keep]
    _assert_notes(notes, keyword, count=1)


# --- sanitiser: declarations -------------------------------------------------


def test_non_data_url_declaration_is_dropped_and_data_url_survives(active):
    css = (
        ".dk-a{background:url(https://x/p.png);color:red}\n"
        ".dk-b{background:url(data:image/png;base64,AAAA)}"
    )
    comps = [_comp("A", "dk-a"), _comp("B", "dk-b")]
    out, notes = _sanitise(_style(css, *comps), active=active)
    assert _canon(out.css) == (
        ".dk-a{color:red}\n.dk-b{background:url(data:image/png;base64,AAAA)}"
    )
    assert out.components == comps
    _assert_notes(notes, "url(", count=1)


_FOREIGN_URL_VALUES = [
    pytest.param('url("https://x/p.png")', id="double-quoted"),
    pytest.param("url('https://x/p.png')", id="single-quoted"),
    pytest.param("URL(https://x/p.png)", id="upper-case-unquoted"),
    pytest.param("URL('https://x/p.png')", id="upper-case-quoted"),
    pytest.param("url(   https://x/p.png   )", id="padded"),
    # A CSS escape in the name: the tokenizer still makes it a url token, and so
    # does a browser.
    pytest.param("u\\72 l(https://x/p.png)", id="css-escaped-name"),
    pytest.param("url(//x/p.png)", id="protocol-relative"),
    pytest.param("url(p.png)", id="relative"),
    pytest.param("image-set(url(https://x/p.png) 1x)", id="nested-in-function"),
    pytest.param(
        "url(data:image/png;base64,AAAA), url(https://x/p.png)", id="after-a-data-url"
    ),
]


@pytest.mark.parametrize("value", _FOREIGN_URL_VALUES)
def test_every_spelling_of_a_non_data_url_is_dropped(value, active):
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(f".dk-a{{background:{value};color:red}}", comp), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    assert out.components == [comp]
    _assert_notes(notes, count=1)


# Amended ruling 4: the content of a url(data:…) is exempt from the
# http:/https:/"//" scan. An SVG xmlns and a base64 "//" both survive.
_DATA_URL_VALUES = [
    pytest.param("url(data:image/png;base64,AAAA)", id="unquoted"),
    pytest.param("url(\"data:image/svg+xml;utf8,<svg width='8' height='8'/>\")", id="svg"),
    pytest.param(
        "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'/>\")",
        id="svg-with-xmlns",
    ),
    pytest.param("url(data:image/png;base64,iVBORw0K//8AAAA=)", id="base64-with-double-slash"),
    pytest.param("url('data:image/gif;base64,R0lGODlhAQABAAAAACw=')", id="single-quoted"),
]


def test_svg_data_url_with_xmlns_survives_unchanged(active):
    # The amended ruling 4 case, verbatim.
    css = ".dk-i{background:url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'/>\")}"
    style = _style(css, _comp("Icon", "dk-i"))
    out, notes = _sanitise(style, active=active)
    assert notes == ()
    assert out is style
    assert out.css == css


@pytest.mark.parametrize("value", _DATA_URL_VALUES)
def test_data_urls_survive_untouched(value, active):
    style = _style(f".dk-a{{background-image:{value};color:red}}", _comp("A", "dk-a"))
    out, notes = _sanitise(style, active=active)
    assert notes == ()
    assert out is style


@pytest.mark.parametrize("value", ["expression(alert(1))", "EXPRESSION(alert(1))"])
def test_expression_declaration_is_dropped(value, active):
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(f".dk-a{{width:{value};color:red}}", comp), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    _assert_notes(notes, "expression(", count=1)


# Ruling 4: besides non-data url(), any declaration whose value mentions
# http:, https: or a protocol-relative // is dropped, strings included.
_REMOTE_TEXT_DECLS = [
    pytest.param('background-image:image-set("https://x/a.png" 1x)', id="image-set-string"),
    # The scheme is case-insensitive, and the URL parser accepts a special
    # scheme with no "//" (https:x/a.png is https://x/a.png), so only a
    # case-insensitive "https:" check catches this one.
    pytest.param('background-image:image-set("HTTPS:x/a.png" 1x)', id="upper-case-scheme"),
    pytest.param('content:"//evil"', id="protocol-relative-string"),
    pytest.param('content:"http://x"', id="http-string"),
    # A CSS escape inside a string: its value is still "https://x/a.png".
    pytest.param('content:"\\68ttps://x/a.png"', id="css-escaped-string"),
    # The exemption covers only the data url itself. A remote string after it
    # in the same value is still caught.
    pytest.param(
        'background-image:url(data:image/png;base64,AAAA), image-set("https://x/a.png" 1x)',
        id="remote-string-after-data-url",
    ),
    pytest.param(
        'content:url(data:image/png;base64,AAAA) "https://x/a.png"',
        id="top-level-remote-string-after-data-url",
    ),
]


@pytest.mark.parametrize("decl", _REMOTE_TEXT_DECLS)
def test_declaration_naming_a_remote_address_is_dropped(decl, active):
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(f".dk-a{{{decl};color:red}}", comp), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    assert out.components == [comp]
    _assert_notes(notes, count=1)


def test_root_custom_property_naming_a_remote_address_is_dropped():
    # Inside image-set(var(--dk-img) 1x), a string token loads like a URL.
    comp = _comp("A", "dk-a")
    css = ':root{--dk-img:"https://x/a.png";--dk-accent:#f00}\n.dk-a{color:var(--dk-accent)}'
    out, notes = _sanitise(_style(css, comp), active=False)
    assert _canon(out.css) == ":root{--dk-accent:#f00}\n.dk-a{color:var(--dk-accent)}"
    _assert_notes(notes, count=1)


# --- sanitiser: nested rules (ruling 5) --------------------------------------

_NESTED = [
    pytest.param(".dk-a{color:red; .x{color:blue}}", ".x", id="nested-class"),
    pytest.param(".dk-a{color:red; &:hover{color:blue}}", "&:hover", id="ampersand-pseudo"),
    pytest.param(".dk-a{color:red; & .x{color:blue}}", ".x", id="ampersand-descendant"),
    pytest.param(".dk-a{color:red; .dk-b{color:blue}}", ".dk-b", id="nested-dk-class"),
    pytest.param(".dk-a{color:red; @media print{color:blue}}", "@media", id="nested-at-rule"),
    # The nested rule comes first. The parent's declaration after it must
    # survive: parse_declaration_list would swallow it, but a browser applies it.
    pytest.param(".dk-a{.x{color:blue} color:red}", ".x", id="nested-before-declaration"),
]


@pytest.mark.parametrize("css, needle", _NESTED)
def test_nested_rule_is_dropped_and_parent_declarations_survive(css, needle, active):
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(css, comp), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    assert "blue" not in out.css
    assert needle not in out.css
    assert out.components == [comp]
    _assert_notes(notes, needle, count=1)


# --- sanitiser: selectors ----------------------------------------------------

_UNSCOPED_SELECTORS = [
    pytest.param("body", "body", id="body"),
    pytest.param("html", "html", id="html"),
    pytest.param("*", "*", id="universal"),
    pytest.param("article", "article", id="element"),
    pytest.param("a:hover", "a:hover", id="pseudo"),
    pytest.param(".card", ".card", id="unprefixed-class"),
    pytest.param(".xdk-a", "xdk-a", id="prefix-not-at-start"),
    pytest.param(".dkx-a", "dkx-a", id="prefix-without-hyphen"),
    pytest.param("#dk-a", "#dk-a", id="id-not-class"),
    pytest.param('p[title=".dk-a"]', "title", id="dk-text-in-attribute-string"),
]


@pytest.mark.parametrize("selector, needle", _UNSCOPED_SELECTORS)
def test_rule_without_a_dk_class_is_dropped(selector, needle, active):
    keep = _comp("Keep", "dk-keep")
    css = f"{selector}{{color:blue}}\n.dk-keep{{color:red}}"
    out, notes = _sanitise(_style(css, keep), active=active)
    assert _canon(out.css) == ".dk-keep{color:red}"
    assert out.components == [keep]
    _assert_notes(notes, needle, count=1)


def test_descendant_token_span_rule_is_kept_through_a_rebuild(active):
    # body forces the CSS to be re-serialised; the descendant space must survive it.
    comp = _comp("Code", "dk-code")
    css = "body{color:red}\n.dk-code{padding:8px}\n.dk-code .kw{color:var(--db-coral)}"
    out, notes = _sanitise(_style(css, comp), active=active)
    assert _canon(out.css) == ".dk-code{padding:8px}\n.dk-code .kw{color:var(--db-coral)}"
    assert out.components == [comp]
    _assert_notes(notes, "body", count=1)


def test_selector_list_keeps_only_its_dk_selectors(active):
    comp = _comp("Card", "dk-card")
    out, notes = _sanitise(_style(".card, .dk-card{padding:8px}", comp), active=active)
    assert _canon(out.css) == ".dk-card{padding:8px}"
    _assert_notes(notes, ".card", count=1)


def test_selector_list_keeps_compound_and_child_dk_selectors(active):
    comp = _comp("A", "dk-a")
    css = ".dk-a, body, div.dk-b > .dk-c{color:red}"
    out, notes = _sanitise(_style(css, comp), active=active)
    assert _canon(out.css) == ".dk-a, div.dk-b > .dk-c{color:red}"
    _assert_notes(notes, "body", count=1)


# Ruling 3 sets the scoping rule. A selector is kept only if:
#   (a) some compound has a .dk- class at top level (a class inside :not(),
#       :has(), :is() or :where() does not count), and
#   (b) every combinator to the right of the first such compound is a
#       descendant (whitespace) or a child (>).
_SCOPED = [
    pytest.param(".dk-code .kw", id="descendant"),
    pytest.param(".dk-steps > li", id="child"),
    pytest.param("div.dk-b > .dk-c", id="compound-child"),
    pytest.param(".dk-a:hover", id="pseudo-class"),
    pytest.param(".dk-a::before", id="pseudo-element"),
    pytest.param(".dk-card .dk-card__title", id="dk-descendant"),
    pytest.param(".dk-a:not(.x)", id="top-level-dk-with-not"),
    pytest.param("p ~ .dk-a .x", id="sibling-left-of-dk"),
]


@pytest.mark.parametrize("selector", _SCOPED)
def test_scoped_selector_is_kept_unchanged(selector, active):
    style = _style(f".dk-keep{{color:red}}\n{selector}{{color:blue}}", _comp("Keep", "dk-keep"))
    out, notes = _sanitise(style, active=active)
    assert notes == ()
    assert out is style


_SCOPE_ESCAPES = [
    pytest.param(":not(.dk-a)", id="not"),
    pytest.param("body:has(.dk-a)", id="has"),
    pytest.param("*:is(.dk-a)", id="is"),
    pytest.param(":where(.dk-a) p", id="where"),
    pytest.param(".dk-a ~ *", id="general-sibling"),
    pytest.param(".dk-a + p", id="next-sibling"),
    pytest.param(".dk-a > p + span", id="sibling-after-child"),
    # Confirmed under ruling 3(b): the first dk compound is followed by "~".
    pytest.param(".dk-a ~ .dk-b", id="sibling-of-dk-to-dk"),
]


@pytest.mark.parametrize("selector", _SCOPE_ESCAPES)
def test_selector_that_escapes_the_dk_scope_is_dropped(selector, active):
    keep = _comp("Keep", "dk-keep")
    css = f"{selector}{{color:blue}}\n.dk-keep{{color:red}}"
    out, notes = _sanitise(_style(css, keep), active=active)
    assert _canon(out.css) == ".dk-keep{color:red}"
    assert out.components == [keep]
    _assert_notes(notes, selector, count=1)


def test_selector_list_keeps_only_its_scoped_selectors(active):
    comp = _comp("A", "dk-a")
    css = ".dk-a, .dk-a ~ *, :not(.dk-b), .dk-a > .x{color:red}"
    out, notes = _sanitise(_style(css, comp), active=active)
    assert _canon(out.css) == ".dk-a, .dk-a > .x{color:red}"
    _assert_notes(notes, ".dk-a ~ *", ":not(.dk-b)", count=2)


# --- sanitiser: :root (R3) ---------------------------------------------------

_MIXED_ROOT = ":root{--dk-accent:#f00;--db-navy:#000}\n.dk-a{color:var(--dk-accent)}"


def test_root_keeps_only_dk_custom_properties_without_a_design_system():
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(_MIXED_ROOT, comp), active=False)
    assert _canon(out.css) == ":root{--dk-accent:#f00}\n.dk-a{color:var(--dk-accent)}"
    _assert_notes(notes, "--db-navy", count=1)


def test_root_is_dropped_whole_with_a_design_system():
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(_MIXED_ROOT, comp), active=True)
    assert _canon(out.css) == ".dk-a{color:var(--dk-accent)}"
    _assert_notes(notes, ":root", count=1)


def test_dk_only_root_is_dropped_with_a_design_system():
    comp = _comp("A", "dk-a")
    style = _style(":root{--dk-accent:#f00}\n.dk-a{color:var(--dk-accent)}", comp)
    out, notes = _sanitise(style, active=True)
    assert _canon(out.css) == ".dk-a{color:var(--dk-accent)}"
    _assert_notes(notes, ":root", count=1)


def test_dk_only_root_is_kept_unchanged_without_a_design_system():
    style = _style(":root{--dk-accent:#f00}\n.dk-a{color:var(--dk-accent)}", _comp("A", "dk-a"))
    out, notes = _sanitise(style, active=False)
    assert notes == ()
    assert out is style


def test_root_left_empty_is_dropped_without_a_design_system():
    comp = _comp("A", "dk-a")
    css = ":root{--db-navy:#000}\n.dk-a{color:red}"
    out, notes = _sanitise(_style(css, comp), active=False)
    assert _canon(out.css) == ".dk-a{color:red}"
    _assert_notes(notes, "--db-navy")


# --- sanitiser: rules left empty, <style> text -------------------------------


def test_rule_emptied_by_the_sanitiser_is_dropped_with_its_component(active):
    # dk-hero is defined only by a rule that loses its one declaration, so its
    # component goes too: components are checked against the CLEANED css.
    hero, body = _comp("Hero band", "dk-hero"), _comp("Body text", "dk-body")
    css = ".dk-hero{background:url(https://x/p.png)}\n.dk-body{color:red}"
    out, notes = _sanitise(_style(css, hero, body), active=active)
    assert _canon(out.css) == ".dk-body{color:red}"
    assert out.components == [body]
    _assert_notes(notes, "url(", "Hero band")


@pytest.mark.parametrize(
    "empty",
    [
        pytest.param(".dk-e{}", id="braces"),
        pytest.param(".dk-e {  /* nothing yet */  }", id="comment-only"),
    ],
)
def test_rule_that_starts_empty_is_dropped(empty, active):
    # Ruling 1: an empty rule is dropped, whether it started empty or was emptied.
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(f"{empty}\n.dk-a{{color:red}}", comp), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    _assert_notes(notes, ".dk-e", count=1)


def test_style_wrapper_around_an_empty_rule_leaves_nothing(active):
    out, notes = _sanitise(_style("<style>.dk-a{}</style>", _comp("A", "dk-a")), active=active)
    assert out is None
    _assert_notes(notes, "<style")


_WRAPPED = [
    pytest.param("<style>.dk-a{color:red}</style>", id="bare"),
    pytest.param('\n  <style type="text/css">\n.dk-a{color:red}\n</style>\n', id="attributes"),
    pytest.param("<STYLE>.dk-a{color:red}</STYLE >", id="upper-case"),
]


@pytest.mark.parametrize("css", _WRAPPED)
def test_style_wrapper_is_removed(css, active):
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(css, comp), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    assert out.components == [comp]
    _assert_notes(notes, "<style")


_SMUGGLED = [
    pytest.param(
        '.dk-a{color:red;content:"</style><script>alert(1)</script>"}', id="in-a-string"
    ),
    pytest.param(".dk-a{color:red} /* </style><script>alert(1)</script> */", id="in-a-comment"),
    pytest.param(".dk-a{color:red}\n/* </STYLE ><img src=x onerror=alert(1)> */", id="upper-case"),
]


@pytest.mark.parametrize("css", _SMUGGLED)
def test_style_tag_text_never_survives(css, active):
    # deck.css is inlined in a <style> element, so "</style" anywhere, comments
    # included, would end it early. The constraint is "no <style> / </style>
    # text", which is stricter than "strip a wrapper".
    out, notes = _sanitise(_style(css, _comp("A", "dk-a")), active=active)
    assert out is not None
    assert "</style" not in out.css.lower()
    assert "<style" not in out.css.lower()
    assert _canon(out.css).startswith(".dk-a{color:red")
    _assert_notes(notes)


# --- sanitiser: components ---------------------------------------------------


def test_component_with_unprefixed_class_is_dropped(active):
    legacy, card = _comp("Legacy card", "card"), _comp("Card", "dk-card")
    out, notes = _sanitise(_style(".dk-card{padding:8px}", legacy, card), active=active)
    assert _canon(out.css) == ".dk-card{padding:8px}"
    assert out.components == [card]
    _assert_notes(notes, "Legacy card", count=1)


def test_component_listing_any_unprefixed_class_is_dropped_even_if_css_defines_it(active):
    # "kw" is defined (".dk-code .kw") but has no dk- prefix: class_names must
    # all be prefixed AND all be defined.
    spans, code = _comp("Code with spans", "dk-code", "kw"), _comp("Code", "dk-code")
    css = ".dk-code{padding:8px}\n.dk-code .kw{color:red}"
    out, notes = _sanitise(_style(css, spans, code), active=active)
    assert out.components == [code]
    _assert_notes(notes, "Code with spans", count=1)


def test_components_with_undefined_or_no_classes_are_dropped_but_css_is_kept(active):
    comps = [
        _comp("Phantom", "dk-x"),
        _comp("Half defined", "dk-a", "dk-x"),
        _comp("No classes"),
    ]
    out, notes = _sanitise(_style(".dk-a{color:red}", *comps), active=active)
    assert out is not None
    assert _canon(out.css) == ".dk-a{color:red}"
    assert out.components == []
    _assert_notes(notes, "Phantom", "Half defined", "No classes", count=3)


def test_component_whose_class_only_lived_in_a_dropped_at_rule_is_dropped(active):
    keep, printed = _comp("Keep", "dk-a"), _comp("Print only", "dk-print")
    css = ".dk-a{color:red}\n@media print{.dk-print{display:none}}"
    out, notes = _sanitise(_style(css, keep, printed), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    assert out.components == [keep]
    _assert_notes(notes, "@media", "Print only", count=2)


_THIRTEEN_CSS = "\n".join(f".dk-c{i:02d}{{color:red}}" for i in range(1, 14))
_THIRTEEN = [_comp(f"Component {i:02d}", f"dk-c{i:02d}") for i in range(1, 14)]


def test_thirteen_components_are_trimmed_to_the_first_twelve(active):
    out, notes = _sanitise(_style(_THIRTEEN_CSS, *_THIRTEEN), active=active)
    assert out.components == _THIRTEEN[:12]
    assert _canon(out.css) == _canon(_THIRTEEN_CSS)
    _assert_notes(notes, "Component 13", count=1)


def test_invalid_components_are_dropped_before_the_cap(active):
    ghost = _comp("Ghost", "dk-missing")
    out, notes = _sanitise(_style(_THIRTEEN_CSS, ghost, *_THIRTEEN[:12]), active=active)
    assert out.components == _THIRTEEN[:12]
    _assert_notes(notes, "Ghost", count=1)


# --- sanitiser: a realistic dirty answer --------------------------------------

_KITCHEN_CSS = (
    "<style>\n"
    "@import url(https://fonts.example.com/inter.css);\n"
    ":root { --dk-accent: #FF3621; --db-navy: #000; }\n"
    "body { margin: 0 }\n"
    ".card, .dk-card { padding: 16px; background: url(https://cdn.example.com/bg.png);"
    " border-radius: 8px }\n"
    "@keyframes dk-fade { from { opacity: 0 } to { opacity: 1 } }\n"
    ".dk-card .dk-card__title { font-weight: 700 }\n"
    ".dk-pill { animation: dk-fade 1s; color: var(--dk-accent) }\n"
    "</style>\n"
)
_KITCHEN_KEPT = (
    ".dk-card{padding:16px;border-radius:8px}\n"
    ".dk-card .dk-card__title{font-weight:700}\n"
    ".dk-pill{animation:dk-fade 1s;color:var(--dk-accent)}"
)


@pytest.mark.parametrize(
    "is_active, expected, root_needle",
    [
        pytest.param(True, _KITCHEN_KEPT, ":root", id="design-system"),
        pytest.param(
            False, ":root{--dk-accent:#FF3621}\n" + _KITCHEN_KEPT, "--db-navy", id="no-design-system"
        ),
    ],
)
def test_realistic_dirty_answer_is_cleaned_in_source_order(is_active, expected, root_needle):
    card = _comp("Card", "dk-card", "dk-card__title")
    pill = _comp("Pill", "dk-pill")
    legacy = _comp("Legacy", "card")
    out, notes = _sanitise(_style(_KITCHEN_CSS, card, legacy, pill), active=is_active)
    assert _canon(out.css) == expected
    assert out.components == [card, pill]
    _assert_notes(
        notes, "<style", "@import", root_needle, "body", ".card", "url(", "@keyframes", "Legacy"
    )


def test_input_style_is_not_mutated_when_something_is_dropped(active):
    style = _style(_KITCHEN_CSS, _comp("Card", "dk-card"), _comp("Legacy", "card"))
    before = style.model_dump()
    out, notes = _sanitise(style, active=active)
    assert notes
    assert out is not style
    assert style.model_dump() == before


# --- sanitiser: blank, None and size ------------------------------------------


def test_none_is_returned_as_none_without_notes(active):
    assert _sanitise(None, active=active) == (None, ())


@pytest.mark.parametrize(
    "css, needle",
    [
        pytest.param("body{color:red}", "body", id="only-unscoped"),
        pytest.param("@import url(https://x/y.css);", "@import", id="only-at-rule"),
        pytest.param(".dk-a{background:url(https://x/p.png)}", "url(", id="only-foreign-url"),
    ],
)
def test_style_whose_css_cleans_to_blank_is_dropped(css, needle, active):
    out, notes = _sanitise(_style(css, _comp("A", "dk-a")), active=active)
    assert out is None
    _assert_notes(notes, needle)


def test_style_with_blank_css_is_dropped_with_a_note(active):
    # The note matters: Ruling R4 refuses an edit with "deck_style was dropped: <notes>".
    out, notes = _sanitise(_style("  \n\t ", _comp("A", "dk-a")), active=active)
    assert out is None
    _assert_notes(notes)


_RULE = ".dk-a{color:red}"  # 16 characters


def _distinct_rules(count: int) -> str:
    """``count`` 20-character rules, each with its OWN selector (``.dk-a0000`` …).

    The padding must not repeat a selector: a repeated one is coalesced (R18),
    which would shrink the CSS and add a note.
    """
    return "".join(f".dk-a{i:04d}{{color:red}}" for i in range(count))


_AT_LIMIT = _distinct_rules(500)  # 10,000 characters
_OVER_LIMIT = _distinct_rules(499) + ".dk-a00499{color:red}"  # 10,001 characters


def _assert_size_note(notes):
    _assert_notes(notes)
    assert any("10000" in n or "10,000" in n for n in notes), (
        f"no note names the {10000} character limit: {notes!r}"
    )


def test_oversized_style_is_dropped(active):
    assert len(_OVER_LIMIT) == 10001
    out, notes = _sanitise(_style(_OVER_LIMIT, _comp("A", "dk-a0000")), active=active)
    assert out is None
    _assert_size_note(notes)


def test_style_exactly_at_the_size_limit_is_kept_unchanged(active):
    assert len(_AT_LIMIT) == 10000
    style = _style(_AT_LIMIT, _comp("A", "dk-a0000"))
    out, notes = _sanitise(style, active=active)
    assert notes == ()
    assert out is style


def test_dirty_style_still_oversized_after_cleaning_is_dropped(active):
    css = _distinct_rules(520) + "body{color:red}"
    out, notes = _sanitise(_style(css, _comp("A", "dk-a")), active=active)
    assert out is None
    _assert_size_note(notes)


def test_size_limit_applies_to_the_cleaned_css(active):
    # An embedded font pushes the raw CSS far past the limit. The cleaned CSS
    # is tiny, so the style survives without the font.
    font = "@font-face{font-family:X;src:url(data:font/woff2;base64," + "A" * 12000 + ")}"
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(font + "\n" + _RULE, comp), active=active)
    assert out is not None
    assert _canon(out.css) == ".dk-a{color:red}"
    assert out.components == [comp]
    _assert_notes(notes, "@font-face", count=1)


# --- sanitiser: repeated selectors are coalesced (R18) ------------------------
# merge_css keys a rule by its selector and keeps only the LAST of a repeated
# one, so the post-commit deck.css would lose the earlier rules' declarations.
# The sanitiser merges them first: declarations in source order, at the last
# occurrence.  Keyed on the exact selector text, so a selector LIST is its own
# key and never coalesces with one of its members.


def test_repeated_selector_is_coalesced_at_its_last_occurrence(active):
    comp = _comp("Code", "dk-code")
    style = _style(
        ".dk-code{background:#fff}\n.dk-x{color:red}\n.dk-code{font-family:monospace}", comp
    )
    out, notes = _sanitise(style, active=active)
    assert out is not None
    assert out.css == ".dk-x{color:red}\n.dk-code{background:#fff;font-family:monospace}"
    assert out.components == [comp]
    _assert_notes(notes, ".dk-code", count=1)
    assert "repeated" in notes[0], notes
    # A fixed point: the coalesced CSS sanitises again with nothing removed.
    again, again_notes = _sanitise(out, active=active)
    assert again is out and again_notes == ()


def test_every_repeat_of_a_selector_joins_one_rule_in_source_order(active):
    css = ".dk-a{color:red}\n.dk-b{margin:0}\n.dk-a{color:blue}\n.dk-a{padding:1px}"
    out, notes = _sanitise(_style(css, _comp("A", "dk-a")), active=active)
    assert out.css == ".dk-b{margin:0}\n.dk-a{color:red;color:blue;padding:1px}"
    _assert_notes(notes, ".dk-a", count=2)


def test_a_selector_list_does_not_coalesce_with_one_of_its_members(active):
    style = _style(".dk-a, .dk-b{color:red}\n.dk-a{font-weight:bold}", _comp("A", "dk-a"))
    out, notes = _sanitise(style, active=active)
    assert out is style and notes == ()


def test_repeated_root_palette_is_coalesced_without_a_design_system():
    style = _style(":root{--dk-a:#000}\n.dk-a{color:var(--dk-a)}\n:root{--dk-b:#fff}")
    out, notes = _sanitise(style, active=False)
    assert out.css == ".dk-a{color:var(--dk-a)}\n:root{--dk-a:#000;--dk-b:#fff}"
    _assert_notes(notes, ":root", count=1)


# --- sanitiser: byte identity (C24, R1) ---------------------------------------

# Live-looking clean style: comments, tabs, blank lines, irregular spacing,
# single quotes, a CSS escape, an SVG data URL, and .dk-code token spans.
# tinycss2 would rewrite '\203A' to "›" and single quotes to double quotes, so
# any re-serialisation shows up as a byte difference.
_CLEAN_CSS = (
    "/* Deck style: technical deck. Colours come from the brand tokens. */\n"
    ".dk-code {\n"
    "\tfont-family: 'JetBrains Mono', ui-monospace, monospace;\n"
    "  background: var(--db-navy);   color: var(--db-oat-light);\n"
    "  padding: 16px 20px;\n"
    "}\n"
    ".dk-code .kw { color: var(--db-coral); }\n"
    ".dk-code .fn{color:var(--db-teal)}\n"
    ".dk-code .str { color: var(--db-yellow) }\n"
    ".dk-code .cm { color: var(--db-grey); font-style: italic; }\n"
    "\n"
    "\n"
    ".dk-table { width: 100%; /* full bleed */ border-collapse: collapse }\n"
    ".dk-table th,\n"
    ".dk-table td { padding: 8px 12px; border-bottom: 1px solid var(--db-grey-light); }\n"
    ".dk-badge {\n"
    "  display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 14px;\n"
    "}\n"
    ".dk-badge--measured { background: var(--db-green); color: var(--db-white) }\n"
    ".dk-badge--untested { background: var(--db-oat); color: var(--db-navy); }\n"
    ".dk-badge--measured::before {\n"
    "  content: url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'"
    " width='8' height='8'/>\");\n"
    "}\n"
    ".dk-note::before { content: '\\203A'; margin-right: 8px; }   \n"
    ".dk-note { font-size: .875rem; color: var(--db-grey) }\n"
)


def _clean_components():
    return [
        DeckStyleComponent(
            name="Code block",
            class_names=["dk-code"],
            use="Any SQL or Python listing; wrap tokens in kw/fn/str/cm spans.",
            example_html=(
                "\n  <pre class='dk-code'><span class=\"kw\">SELECT</span> "
                "<span class=\"fn\">count</span>(*) <span class=\"cm\">-- rows</span></pre>\n"
            ),
        ),
        DeckStyleComponent(
            name="Comparison table",
            class_names=["dk-table"],
            use="Side-by-side comparison of two or three options.",
            example_html='<table class="dk-table"><tr><th>Mode</th><td>CDC</td></tr></table>',
        ),
        DeckStyleComponent(
            name="Evidence badge",
            class_names=["dk-badge", "dk-badge--measured", "dk-badge--untested"],
            use="Mark a claim as measured or untested.",
            example_html=(
                '<span class="dk-badge dk-badge--measured">measured</span> '
                '<span class="dk-badge  dk-badge--untested">untested</span>'
            ),
        ),
        DeckStyleComponent(
            name="Footnote",
            class_names=["dk-note"],
            use="Source lines under a chart.",
            example_html="<p class='dk-note'>Source: pg_stat_replication, 2026-10</p>  ",
        ),
    ]


def test_clean_style_is_returned_unchanged(active):
    style = DeckStyle(css=_CLEAN_CSS, components=_clean_components())
    before = style.model_dump()
    out, notes = _sanitise(style, active=active)
    assert notes == ()
    assert out is style
    # Equality with the literal also catches an in-place rewrite of style.css.
    assert out.css == _CLEAN_CSS
    assert out.model_dump() == before


def test_padded_css_is_clean_and_returned_unchanged(active):
    css = "\n  .dk-a{color:red}\n  "
    style = _style(css, _comp("A", "dk-a", html='\n <p class="dk-a">x</p> \n'))
    out, notes = _sanitise(style, active=active)
    assert notes == ()
    assert out is style
    assert out.css == css


# --- css_class_names ----------------------------------------------------------


def test_css_class_names_reads_compound_descendant_and_pseudo_selectors_only():
    css = (
        ".dk-a:hover{color:red}\n"
        "div.dk-b > .dk-c{color:red}\n"
        '.dk-d.dk-e::before{content:".not-a-class"}\n'
        ".dk-f{background:url(data:image/png;base64,x.y)}\n"
        ".dk-g{font-size:.875rem;width:1.5em}\n"
        ".dk-h:not(.dk-i){color:red}\n"
        'p[title=".fake-attr"]{color:red}\n'
        ".dk-j,.dk-k , .dk-l{color:red}\n"
        "/* .dk-commented{color:red} */\n"
    )
    names = _ds().css_class_names(css)
    assert isinstance(names, frozenset)
    assert names == frozenset(
        {"dk-a", "dk-b", "dk-c", "dk-d", "dk-e", "dk-f", "dk-g", "dk-h", "dk-i", "dk-j", "dk-k", "dk-l"}
    )


def test_css_class_names_reads_inside_media_and_supports():
    css = (
        "@media (max-width:900px){.dk-m{color:red} .dk-m .dk-n{color:blue}}\n"
        "@supports (display:grid){.dk-s{display:grid}}\n"
        ".dk-top{color:red}\n"
    )
    assert _ds().css_class_names(css) == frozenset({"dk-m", "dk-n", "dk-s", "dk-top"})


def test_css_class_names_ignores_at_rule_preludes_and_descriptor_values():
    css = (
        "@import url(https://x/a.b.css);\n"
        "@font-face{font-family:'X';src:url(x.woff2) format('woff2')}\n"
        "@keyframes dk-spin{from{opacity:0}50.5%{opacity:.5}to{opacity:1}}\n"
        ".dk-real{color:red}\n"
    )
    assert _ds().css_class_names(css) == frozenset({"dk-real"})


def test_css_class_names_of_empty_css_is_empty():
    assert _ds().css_class_names("") == frozenset()


# --- html_class_names ---------------------------------------------------------


def test_html_class_names_splits_every_class_attribute_on_any_whitespace():
    html = (
        '<div class="dk-a  dk-b\n\tdk-c">x</div>'
        "<span class='dk-q'>y</span>"
        '<p class="  dk-a ">again</p>'
        '<hr class="">'
        "<p>no class</p>"
    )
    names = _ds().html_class_names(html)
    assert isinstance(names, frozenset)
    assert names == frozenset({"dk-a", "dk-b", "dk-c", "dk-q"})


def test_html_class_names_reads_only_the_class_attribute():
    html = '<em data-class="dk-fake" class="dk-real" title="class=dk-title">z</em>'
    assert _ds().html_class_names(html) == frozenset({"dk-real"})


def test_html_class_names_follows_html_attribute_syntax():
    # Attribute names are case-insensitive. Spaces around "=" and unquoted
    # values are valid HTML too.
    html = '<p CLASS="dk-u">a</p><i class = "dk-sp">b</i><b class=dk-unq>c</b>'
    assert _ds().html_class_names(html) == frozenset({"dk-u", "dk-sp", "dk-unq"})


def test_html_class_names_of_empty_html_is_empty():
    assert _ds().html_class_names("") == frozenset()


# --- dropped_classes_in_use ---------------------------------------------------

_PRIOR = _style(".dk-code{color:red}\n.dk-note{color:blue}", _comp("Code", "dk-code"))
_NEW = _style(".dk-code{color:green}", _comp("Code", "dk-code"))


def test_dropped_classes_in_use():
    rows = {2: '<pre class="dk-note">', 5: '<div class="dk-note x">', 7: "<p>"}
    assert _ds().dropped_classes_in_use(_PRIOR, _NEW, rows) == {"dk-note": (2, 5)}


def test_dropped_class_positions_are_sorted_and_matched_by_whole_token():
    rows = {
        9: '<p class="dk-note">',
        3: '<p class="lead dk-note">',
        6: '<p class="dk-note-wide">',
        4: '<p data-x="dk-note">',
    }
    assert _ds().dropped_classes_in_use(_PRIOR, _NEW, rows) == {"dk-note": (3, 9)}


def test_dropped_class_nobody_uses_is_not_reported():
    prior = _style(".dk-code{color:red}\n.dk-note{color:blue}\n.dk-old{color:grey}")
    rows = {1: '<p class="dk-note">'}
    assert _ds().dropped_classes_in_use(prior, _NEW, rows) == {"dk-note": (1,)}


def test_every_prior_class_counts_as_dropped_when_the_new_style_is_none():
    rows = {1: '<pre class="dk-code">', 4: '<p class="dk-note">', 8: "<p>"}
    assert _ds().dropped_classes_in_use(_PRIOR, None, rows) == {
        "dk-code": (1,),
        "dk-note": (4,),
    }


def test_nothing_is_dropped_without_a_prior_style():
    assert _ds().dropped_classes_in_use(None, _NEW, {1: '<p class="dk-note">'}) == {}


def test_class_still_defined_by_another_selector_is_not_dropped():
    prior = _style(".dk-note{color:blue}")
    new = _style(".dk-card .dk-note{color:blue}")
    assert _ds().dropped_classes_in_use(prior, new, {1: '<p class="dk-note">'}) == {}


def test_unprefixed_class_from_the_prior_css_counts_too():
    # The brief says "every class in the prior style's CSS". A dropped
    # ".dk-code .kw" rule strands the kw spans of kept slides.
    prior = _style(".dk-code{color:red}\n.dk-code .kw{color:blue}")
    new = _style(".dk-code{color:red}")
    rows = {3: '<pre class="dk-code"><span class="kw">SELECT</span></pre>'}
    assert _ds().dropped_classes_in_use(prior, new, rows) == {"kw": (3,)}


# --- deck_style_context --------------------------------------------------------

_FONT_TOKEN_CSS = (
    "@font-face{font-family:'Brand Sans';"
    "src:url(data:font/woff2;base64,d09GMgABAAAAAA) format('woff2');font-weight:400}\n"
    ":root{--db-navy: #1B3139;--big:url(data:image/png;base64,AAAA)}\n"
)


def _assert_no_font_content(ctx):
    blob = json.dumps(ctx)
    for needle in ("font-face", "base64", "woff", "Brand Sans", "Other Face", "data:"):
        assert needle not in blob, f"{needle!r} leaked into {blob}"


def test_context_extracts_tokens_and_classes_without_fonts():
    style_block = (
        ".slide .title{font-size:40px}\n"
        ".card,.card .meta{color:var(--db-navy)}\n"
        ".card{padding:8px}\n"
    )
    ctx = _ds().deck_style_context(_FONT_TOKEN_CSS, style_block)
    assert set(ctx) == {"design_tokens", "template_classes"}
    assert ctx["design_tokens"] == {"--db-navy": "#1B3139"}
    assert ctx["template_classes"] == ["card", "meta", "slide", "title"]
    _assert_no_font_content(ctx)


def test_context_reads_root_of_both_inputs_with_the_120_character_cutoff():
    token_css = (
        ":root{--edge:" + "a" * 120 + ";--long:" + "b" * 121
        + ";--shadow:0 1px 2px rgba(0,0,0,.2)}\n"
        ".tok-only{--not-root:1px}\n"
    )
    style_block = (
        ":root{--t-gap: 24px}\n"
        "@media (max-width:900px){.grid{display:block}}\n"
        "@font-face{font-family:'Other Face';src:url(data:font/woff;base64,QUJD)}\n"
        ".grid .cell{gap:var(--t-gap)}\n"
    )
    ctx = _ds().deck_style_context(token_css, style_block)
    assert ctx["design_tokens"] == {
        "--edge": "a" * 120,
        "--shadow": "0 1px 2px rgba(0,0,0,.2)",
        "--t-gap": "24px",
    }
    # Classes come from the style block only; token_css's .tok-only is not a
    # template class.
    assert ctx["template_classes"] == ["cell", "grid"]
    _assert_no_font_content(ctx)


def test_context_template_classes_are_sorted_then_capped_at_300():
    # The source order is descending. "Cap then sort" would keep c050..c349;
    # "sort then cap" keeps c000..c299.
    style_block = "\n".join(f".c{i:03d}{{color:red}}" for i in range(349, -1, -1))
    style_block += "\n.c000 .c001{color:blue}\n"
    ctx = _ds().deck_style_context("", style_block)
    assert ctx["template_classes"] == [f"c{i:03d}" for i in range(300)]


def test_context_of_empty_inputs_is_empty():
    assert _ds().deck_style_context("", "") == {"design_tokens": {}, "template_classes": []}


# --- review fixes: escaped declaration names ---------------------------------
# tinycss2 hands back a declaration name unescaped. Written out raw on a
# rebuild, "\3c\2fstyle\3e" becomes a live "</style>" (deck.css is inlined in a
# <style> element) and "\7d" a live "}" that opens a body rule. Each case also
# holds "body{…}", so the CSS is rebuilt.


def _selectors_of(css):
    """Top-level selectors of ``css``; raises unless every node is a rule of declarations."""
    selectors = []
    for node in tinycss2.parse_stylesheet(css, skip_whitespace=True, skip_comments=True):
        assert node.type == "qualified-rule", f"not a rule: {node!r}"
        for item in tinycss2.parse_blocks_contents(
            node.content, skip_whitespace=True, skip_comments=True
        ):
            assert item.type == "declaration", f"non-declaration in {node!r}: {item!r}"
        selectors.append(_squash(tinycss2.serialize(node.prelude)))
    return selectors


_ESCAPED_NAMES = [
    pytest.param(
        r".dk-a{color:red;\3c\2fstyle\3e\3cscript\3e alert\28 1\29\3c\2fscript\3e:1}"
        "\nbody{color:red}",
        id="name-decodes-to-end-style-tag",
    ),
    pytest.param(
        r".dk-a{color:red;x\7d body\7b background\3a red\3b x:1}" "\nbody{color:red}",
        id="name-decodes-to-a-body-rule",
    ),
]


@pytest.mark.parametrize("css", _ESCAPED_NAMES)
def test_escaped_declaration_name_stays_escaped_through_a_rebuild(css, active):
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(css, comp), active=active)
    assert out is not None, notes
    assert out.components == [comp]
    # Only "</style" ends the <style> element; an escaped "\<script" inside it is inert.
    assert "</style" not in out.css.lower()
    assert _selectors_of(out.css) == [".dk-a"]
    _assert_notes(notes, "body", count=1)


def test_escaped_root_custom_property_name_stays_escaped_through_a_rebuild():
    comp = _comp("A", "dk-a")
    css = (
        r":root{--dk-\7d body\7b background\3a red\3b --dk-x:1}"
        "\n.dk-a{color:red}\nbody{color:red}"
    )
    out, notes = _sanitise(_style(css, comp), active=False)
    assert out is not None, notes
    assert out.components == [comp]
    assert _selectors_of(out.css) == [":root", ".dk-a"]
    _assert_notes(notes, "body", count=1)


# --- review fixes: the rebuild post-condition (R15) -----------------------------
# Rebuilt CSS must be a fixed point: sanitising it again removes nothing, and it
# holds no <style text. A serialiser bug must drop the style, not ship it.

_BAD_SERIALISER_OUTPUT = [
    pytest.param("color:red}body{color:blue", "body", id="emits-a-body-rule"),
    pytest.param('content:"</style><script>x()</script>"', "<style", id="emits-end-style-tag"),
]


@pytest.mark.parametrize("emitted, needle", _BAD_SERIALISER_OUTPUT)
def test_rebuilt_css_failing_the_post_condition_drops_the_style(
    emitted, needle, active, monkeypatch
):
    ds = _ds()
    monkeypatch.setattr(ds, "_serialise_declaration", lambda decl: emitted)
    out, notes = _sanitise(
        _style(".dk-a{color:red}\nbody{color:red}", _comp("A", "dk-a")), active=active
    )
    assert out is None
    _assert_notes(notes, "post-condition", needle)


@pytest.mark.parametrize("is_active", [True, False], ids=["design-system", "no-design-system"])
def test_rebuilt_css_is_a_fixed_point(is_active):
    style = _style(_KITCHEN_CSS, _comp("Card", "dk-card", "dk-card__title"), _comp("Pill", "dk-pill"))
    out, notes = _sanitise(style, active=is_active)
    assert notes and out is not None
    again, notes_again = _sanitise(out, active=is_active)
    assert notes_again == ()
    assert again is out


# --- review fixes: the remote scan reads text as a URL parser does ------------
# A URL parser removes tab, LF and CR, and reads "\" as "/" in http(s) URLs, so
# "\\host", "/\host" and "/<TAB>/host" all mean "//host". None of these values
# uses an image function, so only the normalised scan catches them.

_NORMALISED_REMOTE_DECLS = [
    pytest.param(r'content:"\\\\evil.example/a.png"', id="double-backslash"),
    pytest.param(r'content:"/\\evil.example/a.png"', id="slash-backslash"),
    pytest.param(r'content:"/\9/evil.example/a.png"', id="tab-inside-double-slash"),
    pytest.param(r'content:"/\a /evil.example/a.png"', id="lf-inside-double-slash"),
    pytest.param(r'content:"/\d /evil.example/a.png"', id="cr-inside-double-slash"),
    pytest.param(r'content:"\5c\5c evil.example/a.png"', id="escaped-backslashes"),
    # Kept from the image-set case, which an image function now drops first.
    pytest.param('content:"HTTPS:evil.example/a.png"', id="upper-case-scheme-without-slashes"),
]


@pytest.mark.parametrize("decl", _NORMALISED_REMOTE_DECLS)
def test_address_spelt_for_the_url_parser_is_dropped(decl, active):
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(f".dk-a{{{decl};color:red}}", comp), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    assert out.components == [comp]
    _assert_notes(notes, "remote address", count=1)


def test_root_custom_property_with_a_backslash_address_is_dropped():
    comp = _comp("A", "dk-a")
    css = (
        r':root{--dk-img:"\\\\evil.example/a.png";--dk-accent:#f00}'
        "\n.dk-a{color:var(--dk-accent)}"
    )
    out, notes = _sanitise(_style(css, comp), active=False)
    assert _canon(out.css) == ":root{--dk-accent:#f00}\n.dk-a{color:var(--dk-accent)}"
    _assert_notes(notes, "remote address", count=1)


# The five bypasses found in review, verbatim. Both the normalised scan and the
# image-function rule now drop them.
_REVIEW_BYPASS_DECLS = [
    pytest.param(r'background-image:image-set("\\\\evil.example/a.png" 1x)', id="backslashes"),
    pytest.param(r'background-image:image-set("/\\evil.example/a.png" 1x)', id="slash-backslash"),
    pytest.param(r'background-image:image-set("/\9/evil.example/a.png" 1x)', id="tab"),
    pytest.param(
        r'background-image:-webkit-image-set("\5c\5c evil.example/a.png" 1x)',
        id="webkit-escaped-backslashes",
    ),
]


@pytest.mark.parametrize("decl", _REVIEW_BYPASS_DECLS)
def test_review_bypass_is_dropped(decl, active):
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(_style(f".dk-a{{{decl};color:red}}", comp), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    _assert_notes(notes, count=1)


def test_review_bypass_through_a_root_variable_is_dropped():
    comp = _comp("A", "dk-a")
    css = (
        r':root{--dk-i:"\\\\evil.example/a.png";--dk-accent:#f00}'
        "\n.dk-a{background-image:image-set(var(--dk-i) 1x);color:red}"
    )
    out, notes = _sanitise(_style(css, comp), active=False)
    assert _canon(out.css) == ":root{--dk-accent:#f00}\n.dk-a{color:red}"
    _assert_notes(notes, "--dk-i", "image-set(", count=2)


# --- review fixes: image functions are dropped (R15) ---------------------------
# A string inside image-set() is a URL, so a relative or slash-less one gets
# past any address scan. These functions are dropped whatever their arguments,
# data: URLs included.

_IMAGE_FUNCTION_VALUES = [
    pytest.param('image-set("/api/sessions" 1x)', "image-set(", id="image-set-relative-path"),
    pytest.param('image-set("file:/etc/hosts" 1x)', "image-set(", id="image-set-file-scheme"),
    pytest.param(
        "image-set(url(data:image/png;base64,AAAA) 1x)", "image-set(", id="image-set-of-a-data-url"
    ),
    pytest.param('IMAGE-SET("a.png" 1x)', "image-set(", id="image-set-upper-case"),
    pytest.param(r'im\61ge-set("a.png" 1x)', "image-set(", id="image-set-css-escaped"),
    pytest.param('-webkit-image-set("a.png" 1x)', "-webkit-image-set(", id="webkit-image-set"),
    pytest.param(
        "cross-fade(url(data:image/png;base64,AAAA), url(data:image/png;base64,BBBB), 50%)",
        "cross-fade(",
        id="cross-fade",
    ),
    pytest.param(
        "-webkit-cross-fade(url(data:image/png;base64,AAAA), url(data:image/png;base64,BBBB), 50%)",
        "-webkit-cross-fade(",
        id="webkit-cross-fade",
    ),
    pytest.param('src("a.png")', "src(", id="src"),
    pytest.param('SRC("a.png")', "src(", id="src-upper-case"),
    pytest.param("element(#dk-a)", "element(", id="element"),
    pytest.param("-moz-element(#dk-a)", "-moz-element(", id="moz-element"),
    pytest.param('var(--dk-bg, image-set("a.png" 1x))', "image-set(", id="inside-a-var-fallback"),
]


@pytest.mark.parametrize("value, needle", _IMAGE_FUNCTION_VALUES)
def test_image_function_declaration_is_dropped(value, needle, active):
    comp = _comp("A", "dk-a")
    out, notes = _sanitise(
        _style(f".dk-a{{background-image:{value};color:red}}", comp), active=active
    )
    assert _canon(out.css) == ".dk-a{color:red}"
    assert out.components == [comp]
    _assert_notes(notes, needle, count=1)


def test_root_custom_property_holding_an_image_function_is_dropped():
    comp = _comp("A", "dk-a")
    css = ':root{--dk-bg:image-set("a.png" 1x);--dk-accent:#f00}\n.dk-a{color:var(--dk-accent)}'
    out, notes = _sanitise(_style(css, comp), active=False)
    assert _canon(out.css) == ":root{--dk-accent:#f00}\n.dk-a{color:var(--dk-accent)}"
    _assert_notes(notes, "image-set(", count=1)


# --- review fixes: comment-only CSS, note length, one note per <style item -----


@pytest.mark.parametrize(
    "css",
    [
        pytest.param("/* nothing yet */", id="one-comment"),
        pytest.param("/* a */\n\n  /* b */  ", id="two-comments"),
    ],
)
def test_style_with_only_comments_is_dropped(css, active):
    out, notes = _sanitise(_style(css), active=active)
    assert out is None
    _assert_notes(notes)


def test_style_with_only_comments_and_a_component_is_dropped(active):
    out, notes = _sanitise(_style("/* nothing yet */", _comp("A", "dk-a")), active=active)
    assert out is None
    _assert_notes(notes)


def _long_dirty_style():
    css = (
        ".x" + "y" * 500 + "{color:red}\n"
        "@" + "k" * 300 + " foo;\n"
        ".dk-a{color:red;" + "p" * 300 + ":url(https://x/p.png)}"
    )
    return _style(css, _comp("Z" * 500, "dk-missing"), _comp("A", "dk-a"))


def test_every_note_is_at_most_200_characters_and_keeps_its_reason(active):
    # Notes quote model-written CSS into the retry prompt (R4), so they are cut.
    # The quoted part is shortened first, so the reason after it survives.
    out, notes = _sanitise(_long_dirty_style(), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    assert len(notes) == 4, notes
    assert all(len(n) <= 200 for n in notes), [len(n) for n in notes]
    _assert_notes(notes, ".xyyy", "@kkk", "url(", "ZZZ")


def test_note_cap_holds_even_when_quoted_text_is_not_shortened(active, monkeypatch):
    monkeypatch.setattr(_ds(), "_MAX_QUOTED_CHARS", 10_000)
    out, notes = _sanitise(_long_dirty_style(), active=active)
    assert len(notes) == 4, notes
    assert all(len(n) <= 200 for n in notes), [len(n) for n in notes]


@pytest.mark.parametrize(
    "css",
    [
        pytest.param('.dk-a{color:red;content:"</style>"}', id="in-a-declaration"),
        pytest.param(".dk-a{color:red}\n</style> .dk-b{color:red}", id="in-a-selector"),
        pytest.param(".dk-a{color:red}\n/* </style> */", id="in-a-comment"),
    ],
)
def test_style_text_gets_exactly_one_note(css, active):
    out, notes = _sanitise(_style(css, _comp("A", "dk-a")), active=active)
    assert _canon(out.css) == ".dk-a{color:red}"
    assert "</style" not in out.css.lower()
    _assert_notes(notes, "<style", count=1)


# --- review fixes: classes inside @scope and @starting-style -------------------


def test_css_class_names_reads_inside_scope_and_starting_style():
    css = (
        "@scope (.dk-card) to (.dk-card__body){.dk-title{color:red}}\n"
        "@starting-style{.dk-pop{opacity:0}}\n"
    )
    assert _ds().css_class_names(css) == frozenset(
        {"dk-card", "dk-card__body", "dk-title", "dk-pop"}
    )


# --- R13 model guard (passes today; red if a strip validator is added) --------


def test_deck_style_strings_survive_a_dump_validate_round_trip_byte_exact():
    css = "\n  .dk-a{color:red}\n  "
    html = '\n <p class="dk-a">x</p> \n'
    style = DeckStyle(
        css=css,
        components=[DeckStyleComponent(name="n", class_names=["dk-a"], use="u", example_html=html)],
    )
    for again in (
        DeckStyle.model_validate(style.model_dump()),
        DeckStyle.model_validate_json(style.model_dump_json()),
    ):
        assert again.css == css
        assert again.components[0].example_html == html
