"""At-rule survival across ``merge_css`` — ws4a task A1.

Shipped defect this file pins: ``merge_css`` merged over a
``{selector: declarations}`` dict, so every CSS at-rule (``@media``,
``@keyframes``, ``@supports``, ``@import``, ``@font-face``) was silently
dropped from a deck's stylesheet on the FIRST slide edit. The merged CSS is
persisted and re-fed as ``existing_css`` on the next edit, so the loss is
permanent: a branded deck loses its print rules, animations and web fonts.

Every test reuses one branded fixture so a failure names the block that was
lost. The first test drives the SHIPPED caller (``SlideDeck.update_css`` ->
``merge_css``); the rest pin the merge contract that ws4b's CSS aggregator
depends on.
"""

import tinycss2

from src.domain.slide_deck import SlideDeck
from src.services.design_system_templates import _TOKEN_CSS_REEMIT_MARKER
from src.utils.css_utils import CssBlock, merge_css, parse_css_blocks, parse_css_rules
from tests.fixtures.html import load_6_slide_deck

# One branded stylesheet carrying every block kind the assertions need:
#   @import, :root with two custom properties, THREE @font-face weights of one
#   family, a qualified rule referencing var(--...), TWO @media blocks with
#   DIFFERENT preludes (in the order tests/fixtures/css/databricks_theme.css
#   really has them: (max-width: 1200px) at :308, print at :329), @keyframes
#   and @supports.
BRANDED_SHEET = """@import url("brand.css");

:root {
  --brand: #ff3621;
  --ink: #1b3139;
}

@font-face {
  font-family: "Acme Sans";
  font-weight: 400;
  src: url("acme-400.woff2") format("woff2");
}

@font-face {
  font-family: "Acme Sans";
  font-weight: 700;
  src: url("acme-700.woff2") format("woff2");
}

@font-face {
  font-family: "Acme Sans";
  font-style: italic;
  font-weight: 400;
  src: url("acme-400i.woff2") format("woff2");
}

section.slide {
  color: var(--ink);
  background: var(--brand);
}

@media (max-width: 1200px) {
  section.slide {
    padding: 40px;
  }
}

@media print {
  section.slide {
    page-break-after: always;
  }
}

@keyframes acme-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

@supports (display: grid) {
  .grid {
    display: grid;
  }
}
"""

# A replacement that touches ONE qualified selector and nothing else. Every
# at-rule in BRANDED_SHEET must survive a merge with it.
SELECTOR_ONLY_REPLACEMENT = "section.slide {\n  color: #000000;\n}"


class TestShippedPathRegression:
    """THE regression test: the live caller chain, not a helper."""

    def test_update_css_preserves_at_rules_on_shipped_path(self):
        """SlideDeck.update_css on a branded sheet keeps every at-rule.

        Shipped caller chain: chat_service.py:2631 -> slide_deck.py:108 ->
        merge_css. Before the fix all five at-rules vanished here.
        """
        deck = SlideDeck.from_html_string(load_6_slide_deck(css=BRANDED_SHEET))
        assert "@media print" in deck.css, "fixture did not reach the deck"

        deck.update_css(SELECTOR_ONLY_REPLACEMENT)

        for marker in (
            "@font-face",
            "@media print",
            "@media (max-width: 1200px)",
            "@keyframes acme-fade",
            "@supports (display: grid)",
            '@import url("brand.css");',
        ):
            assert marker in deck.css, f"{marker} was dropped by update_css"

        # The edit itself still applied.
        assert "color: #000000" in deck.css

    def test_update_css_empty_guard_is_untouched(self):
        """update_css's own guard (slide_deck.py:106-107) still short-circuits."""
        deck = SlideDeck.from_html_string(load_6_slide_deck(css=BRANDED_SHEET))
        before = deck.css

        deck.update_css("")
        assert deck.css == before
        deck.update_css("   \n  ")
        assert deck.css == before


class TestExistingSemanticsPreserved:
    """Nothing the current suite pins may regress."""

    def test_replacement_still_overrides_matching_selector(self):
        result = merge_css(BRANDED_SHEET, SELECTOR_ONLY_REPLACEMENT)

        assert "color: #000000" in result
        # The overridden declarations are gone.
        assert "var(--ink)" not in result
        assert "background: var(--brand)" not in result
        # ...but the custom properties they referenced are still defined.
        assert "--ink: #1b3139" in result

    def test_overridden_rule_keeps_its_original_position(self):
        """dict.update semantics, not append -- @font-face still precedes consumers."""
        existing = ".a { color: red; }\n.b { color: green; }\n.c { color: blue; }"

        result = merge_css(existing, ".a { color: black; }")

        assert "color: black" in result
        assert result.index(".a") < result.index(".b") < result.index(".c")

    def test_qualified_rule_output_shape_is_byte_identical_to_today(self):
        """Formatting gate: tests/sample_htmls/final_html.html pins this shape.

        `f"{selector} {{\\n{declarations}\\n}}"`, blocks joined by "\\n\\n".
        If this changes, test_slide_replacement_flow's golden-file comparison
        breaks -- and the rewrite is wrong, not the golden file.
        """
        result = merge_css(".box { color: red; }", ".card { padding: 10px; }")

        assert result == ".box {\ncolor: red;\n}\n\n.card {\npadding: 10px;\n}"

    def test_parse_css_rules_contract_is_unchanged(self):
        """parse_css_rules still returns ONLY qualified rules, keyed by selector."""
        rules = parse_css_rules(BRANDED_SHEET)

        assert set(rules) == {":root", "section.slide"}
        assert rules["section.slide"] == "color: var(--ink);\n  background: var(--brand);"


class TestAtRuleDedupe:
    """The dedupe half: keyed on (at_keyword, discriminator)."""

    def test_self_merge_collapses_identical_at_rules_to_one_each(self):
        result = merge_css(BRANDED_SHEET, BRANDED_SHEET)

        assert result.count("@import") == 1
        assert result.count("@media (max-width: 1200px)") == 1
        assert result.count("@media print") == 1
        assert result.count("@keyframes acme-fade") == 1
        assert result.count("@supports (display: grid)") == 1
        # Three DIFFERENT @font-face blocks: each collapses to one occurrence.
        assert result.count("@font-face") == 3

    def test_two_different_media_blocks_both_survive(self):
        """The failure mode of a naive keyword-keyed fix."""
        result = merge_css(BRANDED_SHEET, SELECTOR_ONLY_REPLACEMENT)

        assert "@media (max-width: 1200px)" in result
        assert "@media print" in result
        assert "padding: 40px" in result
        assert "page-break-after: always" in result

    def test_three_font_face_weights_of_one_family_all_survive(self):
        """The empty-prelude fallback.

        Every @font-face serializes an EMPTY prelude, so prelude-only keying
        would collapse a three-weight brand font to one weight -- and
        ensure_deck_token_css's guard is per-FAMILY, so it would not notice.
        This assertion is the only thing standing between the fix and a silent
        font regression.
        """
        result = merge_css(BRANDED_SHEET, BRANDED_SHEET)

        assert result.count("@font-face") == 3
        for src in ("acme-400.woff2", "acme-700.woff2", "acme-400i.woff2"):
            assert result.count(src) == 1, f"{src} weight lost or duplicated"

    def test_edited_media_print_replaces_the_existing_one(self):
        """One copy out, not two -- deck.css must not grow monotonically.

        merge_css's output is persisted (session_manager.py:1366) and re-fed as
        existing_css on the next edit, so an append-only at-rule key would make
        deck.css grow on every edit and ship in every knit, preview and export.
        """
        edited = (
            "@media print {\n"
            "  section.slide {\n"
            "    page-break-after: avoid;\n"
            "  }\n"
            "}"
        )

        result = merge_css(BRANDED_SHEET, edited)

        assert result.count("@media print") == 1
        assert "page-break-after: avoid" in result
        assert "page-break-after: always" not in result

        # Re-feeding the merged sheet (the live persistence loop) is stable.
        again = merge_css(result, edited)
        assert again.count("@media print") == 1

    def test_at_rule_keyword_case_does_not_mint_a_second_key(self):
        """A case variant must not reintroduce the append-only failure.

        CSS at-rule keywords are ASCII case-insensitive per spec, so
        `@MEDIA print` IS `@media print`. Keying on the raw `at_keyword` would
        give them different keys, so an edit arriving in a different case would
        append a second block instead of replacing -- exactly the growth the
        prelude key exists to prevent, smuggled in through capitalisation.
        """
        edited = (
            "@MEDIA print {\n"
            "  section.slide {\n"
            "    page-break-after: avoid;\n"
            "  }\n"
            "}"
        )

        result = merge_css(BRANDED_SHEET, edited)

        # ONE @media print block survives, in the replacement's case.
        media_blocks = [
            b for b in parse_css_blocks(result)
            # .lower() here on PURPOSE: this must count real @media print
            # blocks however they are keyed, or a sabotage/regression that
            # splits them across two keys would look like a pass.
            if b.is_at_rule and b.key[0].lower() == "media" and b.key[1] == "print"
        ]
        assert len(media_blocks) == 1, f"expected 1 @media print block, got {len(media_blocks)}"

        assert result.count("page-break-after") == 1
        assert "page-break-after: avoid" in result
        assert "page-break-after: always" not in result
        # The other, differently-preluded @media is untouched.
        assert result.count("@media (max-width: 1200px)") == 1

        # The key is normalised, so parse order/case cannot matter either way.
        assert parse_css_blocks(edited)[0].key == ("media", "print")

    def test_at_rules_are_overridable_not_immortal(self):
        """A text-keyed at-rule could never be overridden -- @keyframes forever."""
        edited = "@keyframes acme-fade {\n  from { opacity: 0.5; }\n  to { opacity: 1; }\n}"

        result = merge_css(BRANDED_SHEET, edited)

        assert result.count("@keyframes acme-fade") == 1
        assert "opacity: 0.5" in result


class TestBlocklessAtRules:
    """@import and @charset have a prelude and NO block (content is None)."""

    def test_import_at_rule_has_no_content_block(self):
        """Pins the fact a naive fix trips over."""
        parsed = tinycss2.parse_stylesheet(BRANDED_SHEET, skip_whitespace=True)
        at_import = next(
            r for r in parsed if r.type == "at-rule" and r.at_keyword == "import"
        )

        assert at_import.content is None

    def test_import_survives_the_merge(self):
        blocks = parse_css_blocks(BRANDED_SHEET)
        import_blocks = [b for b in blocks if b.is_at_rule and b.key[0] == "import"]

        assert len(import_blocks) == 1
        assert isinstance(import_blocks[0], CssBlock)
        assert import_blocks[0].text == '@import url("brand.css");'

        result = merge_css(BRANDED_SHEET, SELECTOR_ONLY_REPLACEMENT)
        assert '@import url("brand.css");' in result


class TestOrdering:
    """CSS is order-sensitive; a merge that reshuffles at-rules changes rendering."""

    def test_font_face_still_precedes_media_print(self):
        result = merge_css(BRANDED_SHEET, SELECTOR_ONLY_REPLACEMENT)

        assert result.index("@font-face") < result.index("@media print")

    def test_new_import_is_hoisted_before_every_qualified_rule(self):
        """The hoist. dict.update puts a NEW key last, where a browser ignores it."""
        existing = "section.slide { color: red; }\n\n.card { padding: 10px; }"

        result = merge_css(existing, '@import url("late.css");\n.card { padding: 20px; }')

        assert '@import url("late.css");' in result
        assert result.startswith('@import url("late.css");')
        import_pos = result.index("@import")
        assert import_pos < result.index("section.slide")
        assert import_pos < result.index(".card")

    def test_charset_is_hoisted_ahead_of_import(self):
        existing = "section.slide { color: red; }"

        result = merge_css(
            existing, '@import url("late.css");\n@charset "utf-8";\n.card { color: blue; }'
        )

        assert result.index("@charset") < result.index("@import")
        assert result.index("@import") < result.index("section.slide")

    def test_hoist_preserves_relative_order_within_a_group(self):
        existing = ".a { color: red; }"

        result = merge_css(
            existing, '@import url("one.css");\n@import url("two.css");\n.b { color: blue; }'
        )

        assert result.index("one.css") < result.index("two.css")
        assert result.index("two.css") < result.index(".a")


class TestVerbatimDeclarationText:
    """CssBlock.text's formatting contract, enforceable."""

    def test_internal_whitespace_and_inline_comment_survive_verbatim(self):
        """Inner content is verbatim; leading/trailing padding is stripped at
        assembly so the qualified-rule byte shape (and the golden file) holds.
        """
        replacement = ".a { color : red ; /* keep me */ }"

        result = merge_css(".a { color: blue; }", replacement)

        assert "color : red ; /* keep me */" in result
        assert result == ".a {\ncolor : red ; /* keep me */\n}"

    def test_css_block_text_is_stored_unstripped(self):
        """The contract says 'no newline normalization' -- store it raw."""
        (block,) = parse_css_blocks(".a { color : red ; /* keep me */ }")

        assert block.is_at_rule is False
        assert block.key == ".a"
        assert block.text == " color : red ; /* keep me */ "


class TestNonRuleNodesDropped:
    """Only qualified-rule and at-rule become blocks -- today's behaviour, kept."""

    def test_top_level_comment_does_not_survive_the_merge(self):
        """Deliberately pins today's behaviour, so changing it is a decision.

        _TOKEN_CSS_REEMIT_MARKER (design_system_templates.py) is "what a
        reviewer greps for"; it does not survive an edit today and must not
        after the fix either.
        """
        replacement = f"{_TOKEN_CSS_REEMIT_MARKER}\n.a {{ color: red; }}"

        result = merge_css(".a { color: blue; }", replacement)

        assert _TOKEN_CSS_REEMIT_MARKER not in result
        assert "design-system token stylesheet" not in result
        assert "color: red" in result

    def test_comments_are_not_blocks(self):
        blocks = parse_css_blocks("/* hello */\n.a { color: red; }\n/* bye */")

        assert [b.key for b in blocks] == [".a"]


class TestEmptinessGuard:
    """Keep the early return, key it on parse_css_blocks."""

    def test_empty_replacement_returns_existing_unchanged(self):
        existing = ".a { color: red; }"

        assert merge_css(existing, "") == existing
        assert merge_css(existing, "   \n ") == existing
        assert merge_css(existing, "/* nothing but a comment */") == existing

    def test_at_rule_only_replacement_now_merges(self):
        """Deliberate behaviour change: a blocks-keyed guard no longer drops it.

        Measured before the fix: this returned `existing` untouched, because
        parse_css_rules yields {} for an at-rule-only sheet and the early
        return fired -- so half the bug would have survived a parse-only fix.
        """
        existing = ".a { color: red; }"

        result = merge_css(existing, "@media print { .a { color: green } }")

        assert result != existing
        assert "@media print" in result
        assert "color: green" in result
        assert "color: red" in result

    def test_parse_css_blocks_handles_none_and_empty(self):
        assert parse_css_blocks(None) == []
        assert parse_css_blocks("") == []
