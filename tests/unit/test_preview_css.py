"""Preview CSS helpers: drop embedded fonts, Google Fonts imports, conservative trim.

The MCP deck preview must stay small and must never carry embedded font data, so
``src/utils/preview_css.py`` provides three pure functions:

* ``strip_embedded_font_faces(css)`` removes every ``@font-face`` whose ``src``
  holds a ``data:`` URI or a ``{{ds-asset:N}}`` handle and reports the removed
  families as ``{family: {(ital, weight)}}``; everything else comes back
  byte-for-byte (it does not minify);
* ``google_fonts_imports(faces)`` turns that report into one Google Fonts
  ``@import`` line per family;
* ``trim_css(css, used_text)`` removes comments, minifies, and drops a rule only
  when one of its selectors is CERTAINLY dead: it holds a ``.name``/``#name``
  token (outside ``[...]``) that is not a whole word of ``used_text``, and it
  holds neither ``\\`` nor ``(``. Anything it cannot classify is kept.

What this file pins (plan Task 1 + PLAN-CORRECTIONS C3-C7):

* the inside of quoted strings and of ``url(...)`` (quoted or not) is opaque to
  comment stripping, statement-end detection, brace matching and minification
  (C3);
* any at-rule whose prelude reaches ``;`` before ``{`` is a statement, and the
  rule after it is processed as its own rule (C4);
* tokens inside ``[...]`` are ignored (C5);
* ``@font-face`` defaults and keywords, and that stripping changes nothing else
  (C6);
* minification is observed through ``trim_css`` with a ``used_text`` that keeps
  the rule (C7).

Every oracle is a literal written here. Where the brief's rules do not fix the
exact bytes (how a kept at-rule block is re-emitted, spacing after a comma or a
colon), the tests assert what is kept, what is gone, and that braces balance.
"""

from __future__ import annotations

import re

from src.utils.preview_css import (
    FontFaces,
    google_fonts_imports,
    strip_embedded_font_faces,
    trim_css,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _balanced(css: str) -> bool:
    """True when ``{``/``}`` outside quoted strings never go negative and end at 0."""
    depth = 0
    quote = ""
    i = 0
    while i < len(css):
        ch = css[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0 and not quote


def _assert_minified(out: str) -> None:
    """Minify invariants that hold for any output with no strings and no rule starting with ':'."""
    assert "\n" not in out and "\t" not in out, out
    assert "  " not in out, out
    for ch in "{};":
        assert f" {ch}" not in out, (ch, out)
        assert f"{ch} " not in out, (ch, out)
    assert ";}" not in out, out


# ---------------------------------------------------------------------------
# strip_embedded_font_faces
# ---------------------------------------------------------------------------

_INTER_FACE = (
    "@font-face {\n"
    "  font-family: Inter;\n"
    "  font-weight: 400;\n"
    "  src: url(https://example.com/inter.woff2) format('woff2');\n"
    "}"
)


def test_strip_removes_data_uri_font_faces_and_reports_them():
    css = (
        "@font-face {\n"
        "  font-family: 'DM Sans';\n"
        "  font-style: normal;\n"
        "  font-weight: 400;\n"
        "  src: url(data:font/ttf;base64,AAAA) format('truetype');\n"
        "}\n"
        "@font-face {\n"
        '  font-family: "DM Sans";\n'
        "  font-style: italic;\n"
        "  font-weight: 700;\n"
        "  src: url('{{ds-asset:7}}') format('woff2');\n"
        "}\n" + _INTER_FACE + "\n"
        ".a{color:red}\n"
    )

    out, faces = strip_embedded_font_faces(css)

    assert "data:" not in out
    assert "ds-asset" not in out
    assert "DM Sans" not in out
    assert "base64" not in out
    # the https face stays whole and is not reported
    assert _INTER_FACE in out
    assert out.count("@font-face") == 1
    assert "inter.woff2" in out
    assert ".a{color:red}" in out
    assert faces == {"DM Sans": {(0, 400), (1, 700)}}


def test_strip_parses_weight_keywords_and_ranges():
    css = (
        "@font-face{font-family:'Alpha';font-weight:normal;"
        "src:url(data:font/woff2;base64,AA)}"
        "@font-face{font-family: Alpha ;font-weight:bold;"
        "src:url(data:font/woff2;base64,BB)}"
        '@font-face{font-family:"Beta";font-weight:100 900;'
        "src:url({{ds-asset:2}}) format('woff2')}"
        "@font-face{font-family:Gamma;font-style:oblique;font-weight:300;"
        'src:url("data:font/woff2;base64,CC")}'
        "@font-face{font-family:Open Sans;font-weight:500;"
        "src:url(data:font/woff2;base64,DD)}"
        "p{margin:0}"
    )

    out, faces = strip_embedded_font_faces(css)

    expected: FontFaces = {
        # quoted and unquoted (with surrounding whitespace) name -> one key
        "Alpha": {(0, 400), (0, 700)},
        # a two-number range reports both endpoints, nothing between
        "Beta": {(0, 100), (0, 900)},
        # oblique -> ital 1
        "Gamma": {(1, 300)},
        # an unquoted multi-word name keeps its inner space
        "Open Sans": {(0, 500)},
    }
    assert faces == expected
    assert out == "p{margin:0}"


def test_strip_font_face_defaults_and_leaves_the_rest_byte_identical():
    """C6: no weight -> 400, no style -> 0, italic / oblique <angle> -> 1; no minify."""
    pre = "/* brand fonts */\n.k  {\n  color : red ;\n}"
    faces_css = (
        "@font-face{font-family:P;src:url(data:font/woff2;base64,AA)}"
        "@font-face{font-family:Q;font-style:italic;src:url(data:font/woff2;base64,BB)}"
        "@font-face{font-family:R;font-style:oblique 10deg;font-weight:600;"
        "src:url({{ds-asset:9}})}"
    )
    post = ".m  >  .n { b : 2 }\n\n@media print {\n  .k { color : black ; }\n}\n"

    out, faces = strip_embedded_font_faces(pre + faces_css + post)

    assert faces == {"P": {(0, 400)}, "Q": {(1, 400)}, "R": {(1, 600)}}
    # removing the faces is the only change: comments, whitespace and the
    # trailing semicolons outside the faces come back exactly as given
    assert out == pre + post


def test_strip_treats_unquoted_url_with_braces_as_opaque():
    """C3: an unquoted ``url({{ds-asset:N}})`` holds braces; the face still ends at its own '}'."""
    css = (
        "@font-face{font-family:X;src:url({{ds-asset:1}})}"
        "@font-face{font-family:Y;src:url(https://e.com/y.woff2)}"
        ".k{a:1}"
    )

    out, faces = strip_embedded_font_faces(css)

    assert faces == {"X": {(0, 400)}}
    assert out == "@font-face{font-family:Y;src:url(https://e.com/y.woff2)}.k{a:1}"


def test_strip_without_embedded_faces_returns_input_unchanged():
    css = _INTER_FACE + "\n.a {\n  color: red;\n}\n/* end */\n"

    out, faces = strip_embedded_font_faces(css)

    assert out == css
    assert faces == {}


def test_strip_removes_embedded_faces_nested_in_grouping_at_rules():
    """Spec rule 4 says EVERY embedded face: one inside @media / @layer goes too (Tailwind
    puts faces in ``@layer base``); an https face inside @supports stays; nothing else changes."""
    css = (
        "@media screen{@font-face{font-family:Z;src:url(data:font/woff2;base64,AAAA)}.k{a:1}}"
        "@layer base{@font-face{font-family:'Y Y';font-weight:700;src:url('{{ds-asset:5}}')}}"
        "@supports (display:grid){@font-face{font-family:W;src:url(https://e.com/w.woff2)}}"
        ".b{x:1}"
    )

    out, faces = strip_embedded_font_faces(css)

    assert faces == {"Z": {(0, 400)}, "Y Y": {(0, 700)}}
    assert out == (
        "@media screen{.k{a:1}}"
        "@layer base{}"
        "@supports (display:grid){@font-face{font-family:W;src:url(https://e.com/w.woff2)}}"
        ".b{x:1}"
    )


# ---------------------------------------------------------------------------
# google_fonts_imports
# ---------------------------------------------------------------------------


def test_google_fonts_imports_url_encodes_family_names():
    """A quote or '&' in a family name must not end the url string or the query early."""
    out = google_fonts_imports({"Bob's Font": {(0, 400)}, "A&B": {(1, 700)}})

    assert out == (
        "@import url('https://fonts.googleapis.com/css2?family=A%26B:ital,wght@1,700"
        "&display=swap');\n"
        "@import url('https://fonts.googleapis.com/css2?family=Bob%27s+Font:ital,wght@0,400"
        "&display=swap');"
    )


def test_google_fonts_imports_one_line_per_family():
    faces = {"DM Sans": {(0, 400), (1, 400), (0, 700)}, "DM Mono": {(0, 500)}}

    assert google_fonts_imports(faces) == (
        "@import url('https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,500"
        "&display=swap');\n"
        "@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,700;1,400"
        "&display=swap');"
    )
    assert google_fonts_imports({}) == ""
    # every space in a name becomes '+', not only the first
    assert google_fonts_imports({"Noto Sans JP": {(1, 300)}}) == (
        "@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:ital,wght@1,300"
        "&display=swap');"
    )


# ---------------------------------------------------------------------------
# trim_css: pruning
# ---------------------------------------------------------------------------


def test_trim_drops_only_rules_whose_names_are_absent():
    css = ".used{a:1} .unused{b:2} #gone{c:3} .used .unused{d:4} .used, .unused{e:5}"

    out = trim_css(css, used_text='<div class="used">')

    # the comma list loses only its dead selector
    assert out == ".used{a:1}.used{e:5}"


def test_trim_keeps_root_vars_element_rules_and_at_rules():
    css = "\n".join(
        [
            "@import url('https://x');",
            ":root{--x:1}",
            "body{margin:0}",
            "@keyframes spin{from{a:1}to{a:2}}",
            "@page{size:a4}",
            ".dead{z:9}",
        ]
    )

    out = trim_css(css, used_text="")

    assert "@import url('https://x');" in out
    assert ":root{--x:1}" in out
    assert "body{margin:0}" in out
    assert "@keyframes spin{from{a:1}to{a:2}}" in out
    assert "@page{size:a4}" in out
    # ...while a classifiable dead rule in the same sheet is still dropped
    assert "dead" not in out
    assert "z:9" not in out
    assert _balanced(out)


def test_trim_recurses_into_media_and_drops_empty_media():
    css = "@media (min-width:1px){.used{a:1}.unused{b:2}}\n@media print{.unused{b:2}}"

    out = trim_css(css, used_text='class="used"')

    assert out.startswith("@media")
    assert "(min-width:1px)" in out
    assert ".used{a:1}" in out
    assert out.index("@media") < out.index(".used{a:1}")
    assert "unused" not in out
    assert "b:2" not in out
    # the media block left with no rules disappears entirely
    assert "print" not in out
    assert out.count("@media") == 1
    assert _balanced(out)
    _assert_minified(out)


def test_trim_keeps_an_emptied_named_layer_for_cascade_order():
    """A named @layer's first block fixes its place in the layer order even when empty:
    dropping it would put ``base`` after ``theme`` and flip which colour wins."""
    css = "@layer base{.dead{x:1}}@layer theme{.b{color:red}}@layer base{.b{color:blue}}"

    out = trim_css(css, used_text='class="b"')

    assert out == "@layer base{}@layer theme{.b{color:red}}@layer base{.b{color:blue}}"


def test_trim_keeps_the_rule_after_a_stray_top_level_statement():
    """Browsers fold a stray top-level ';' or '}' into the NEXT rule's prelude and drop that
    rule. Dropping the dead rule after one would make the stray kill the live rule behind
    it, so the rule straight after a stray is kept as written; later dead rules still go."""
    css = ".a{x:1};\n.dead{z:1}\n.c{w:1}\n.gone{k:1}\n.a{y:1}}\n.dead2{q:1}\n.c{v:1}"

    out = trim_css(css, used_text='class="a c"')

    assert out == ".a{x:1};.dead{z:1}.c{w:1}.a{y:1}}.dead2{q:1}.c{v:1}"


def test_trim_recurses_into_supports_container_and_layer_blocks():
    css = "\n".join(
        [
            "@supports (display:grid){.used{a:1}.unused{b:2}}",
            "@container card (min-width:400px){.unused{c:3}.used{g:7}}",
            "@layer base{.used{d:4}.unused{e:5}}",
            # not a trimmed at-rule: kept verbatim even though .nope/.inner are absent
            "@scope (.nope){.inner{f:6}}",
        ]
    )

    out = trim_css(css, used_text='class="used"')

    assert "(display:grid)" in out
    assert ".used{a:1}" in out
    assert "(min-width:400px)" in out
    assert ".used{g:7}" in out
    assert "@layer base" in out
    assert ".used{d:4}" in out
    assert "unused" not in out
    for gone in ("b:2", "c:3", "e:5"):
        assert gone not in out
    assert "@scope (.nope){.inner{f:6}}" in out
    assert out.count("@supports") == 1
    assert out.count("@container") == 1
    assert out.count("@layer") == 1
    assert _balanced(out)
    _assert_minified(out)


def test_trim_survives_comment_before_import():
    css = (
        "/* header */\n@import url('https://f');\n/* c */ :root{--bg:#123}\n"
        ".slide.dark{background:var(--bg)}"
    )

    out = trim_css(css, used_text='class="slide dark"')

    assert "@import url('https://f')" in out
    assert ":root{--bg:#123}" in out
    assert ".slide.dark{background:var(--bg)}" in out
    # comments are removed
    assert "/*" not in out
    assert "*/" not in out
    assert "header" not in out
    assert _balanced(out)


def test_trim_keeps_unclassifiable_selectors():
    css = "\n".join(
        [
            ".md\\:flex{a:1}",
            ":is(.a, .b) p{c:1}",
            "[data-x] .zz{b:1}",
            ".x:not(.y){e:1}",
            ".qq{d:1}",
        ]
    )

    out = trim_css(css, used_text='class="a"')

    # contains '\' -> unclassifiable -> kept
    assert ".md\\:flex{a:1}" in out
    # contains '(' -> kept; the comma inside :is(...) does not split the selector
    assert ":is(.a," in out
    assert ".b) p{c:1}" in out
    assert ".x:not(.y){e:1}" in out
    # classifiable and dead -> dropped
    assert "zz" not in out
    assert "data-x" not in out
    assert "b:1" not in out
    assert "qq" not in out
    assert "d:1" not in out
    assert _balanced(out)


def test_trim_counts_names_in_scripts_text():
    css = ".chart-tip{a:1}.gone{b:2}"

    out = trim_css(css, used_text="<div class=\"slide\"></div>\nel.classList.add('chart-tip')")

    assert out == ".chart-tip{a:1}"


def test_trim_matches_whole_words_not_substrings():
    """A name counts only as a whole word of used_text (word = [A-Za-z0-9_-]+)."""
    css = ".chart{a:1}.chart-tip{b:2}.tip{c:3}#main{d:4}#mai{e:5}.chart, .tip{f:6}"

    out = trim_css(
        css,
        used_text="<div id=\"main\"></div><script>el.classList.add('chart-tip')</script>",
    )

    # 'chart' and 'tip' occur only inside the word 'chart-tip'; 'mai' only inside 'main';
    # a selector list whose every selector is dead goes as a whole
    assert out == ".chart-tip{b:2}#main{d:4}"


def test_trim_ignores_tokens_inside_attribute_selectors():
    """C5: '.pdf' and '#top' inside [...] are not class/id tokens; a ']' in a quoted value
    does not end the brackets early."""
    css = (
        'a[href$=".pdf"]{c:1}'
        "[data-x] .zz{b:1}"
        'a[href^="#top"]{d:1}'
        "input[type=text].dead{e:1}"
        'a[title="x] .y"]{g:1}'
    )

    out = trim_css(css, used_text="")

    assert out == 'a[href$=".pdf"]{c:1}a[href^="#top"]{d:1}a[title="x] .y"]{g:1}'


def test_trim_treats_any_semicolon_terminated_at_rule_as_a_statement():
    """C4: '@layer a, b;' is a statement; the next rule is trimmed on its own."""
    css = "@layer a, b;.unused{x:1}.used{y:2}"

    out = trim_css(css, used_text='class="used"')

    assert re.fullmatch(r"@layer a, ?b;\.used\{y:2\}", out), out


def test_trim_unquoted_url_semicolons_do_not_end_a_statement():
    """C3: the ';' inside an unquoted @import url(...) is not the statement's end."""
    imp = "@import url(https://fonts.googleapis.com/css2?family=A:wght@0,400;0,700&display=swap);"
    css = imp + "\n.unused{x:1}\n.used{y:2}"

    out = trim_css(css, used_text='class="used"')

    assert out == imp + ".used{y:2}"


def test_trim_leaves_strings_and_urls_untouched():
    """C3: braces, ';', '/*' and whitespace inside strings and url(...) survive verbatim."""
    keep_a = '.a{content:"x  ;  { } /* no */";quotes:";}"}'
    keep_c = ".c{content:'}'}"
    keep_hero = ".hero{background:url({{ds-asset:3}})}"
    keep_cdn = ".cdn{background:url(https://cdn.example/a/*b*/c.png)}"
    css = (
        keep_a + "\n/* don't drop the next rule */\n" + keep_c + keep_hero + keep_cdn + ".gone{x:1}"
    )

    out = trim_css(css, used_text='class="a c hero cdn"')

    # the real comment (with an apostrophe in it) goes, the dead rule goes,
    # every byte inside a string or url(...) stays
    assert out == keep_a + keep_c + keep_hero + keep_cdn


# ---------------------------------------------------------------------------
# trim_css: minification (observable only through trim_css -- C7)
# ---------------------------------------------------------------------------


def test_minify_keeps_descendant_pseudo_space():
    # never strip whitespace before ':' (descendant + pseudo is not '.a:hover')
    assert trim_css(".a :hover{x:1}", used_text='class="a"') == ".a :hover{x:1}"

    # whitespace runs collapse to one space; spaces next to '{', '}', ';' go,
    # and so does the last ';' before '}'
    assert (
        trim_css(".a   \n\t .b {\n  x:1 ;\n  y:2 ;\n}\n\n", used_text='class="a b"')
        == ".a .b{x:1;y:2}"
    )
    assert trim_css(".a{margin:0  \n auto}", used_text='class="a"') == ".a{margin:0 auto}"

    # never strip whitespace around '>', '+', '~' (calc() needs the spaces)
    assert (
        trim_css(".a  >  .b{x:1}\n.a + .b{y:2}\n.a ~ .b{z:3}", used_text='class="a b"')
        == ".a > .b{x:1}.a + .b{y:2}.a ~ .b{z:3}"
    )
    assert (
        trim_css(".a{width:calc(1px + 2px)}", used_text='class="a"') == ".a{width:calc(1px + 2px)}"
    )
