"""Deck CSS aggregation for the graph write path — ws4b task B3.3.

The defect this file guards: the LangGraph path calls neither monolith
mechanism that populates ``deck.css``, so without :func:`aggregate_deck_css` a
graph-built deck reaches ``ensure_deck_token_css`` with an EMPTY stylesheet.
That backstop restores only custom properties and ``@font-face`` families, so
it would return the token stylesheet alone and the deck would knit with no
layout CSS at all.

Two structural facts shape every test here:

* ``merge_css`` returns ``existing_css`` unchanged when the REPLACEMENT parses
  to no blocks. So aggregation cannot concatenate the blocks and merge the
  concatenation with ``""`` — that call returns early and the emitted CSS never
  reaches the merge. The fold must be pairwise, and the assertions below are
  written to fail if it is not.
* The blocks are not builder output (``BuilderOutput`` forbids a builder
  emitting ``<style>``); one writer emits them once per turn in ws4c, so the
  list holds exactly ONE element or is empty. "N identical copies collapse to
  one" is therefore untestable here — every test uses one block or none, and
  asserts that block's properties instead.
"""

import logging
import re
from collections import Counter

import pytest

from src.services import deck_css_aggregator
from src.services.deck_css_aggregator import aggregate_deck_css
from src.services.design_system_templates import _TOKEN_CSS_REEMIT_MARKER
from src.utils.css_utils import merge_css, parse_css_blocks

# ---------------------------------------------------------------------------
# Fixtures
#
# FIXTURE TRAP (round-3 findings 6 and 7): a "compliant" deck must define EVERY
# custom property TOKEN_CSS declares, or the backstop legitimately prepends and
# the untouched-deck test fails for the wrong reason. And a name that is both
# defined and var()-referenced appears TWICE in the text, so occurrence counting
# must count DEFINITIONS (name followed by a colon), never bare occurrences.
# ---------------------------------------------------------------------------

# Exactly two custom properties and one @font-face family. Both halves matter:
# ensure_deck_token_css checks custom properties AND per-family @font-face
# survival.
TOKEN_CSS = """:root {
  --tellr-brand: #ff3621;
  --tellr-ink: #1b3139;
}

@font-face {
  font-family: "Acme Sans";
  font-weight: 400;
  src: url("acme-400.woff2") format("woff2");
}
"""

# A deck that defines NONE of the token properties and no @font-face: the
# backstop must fire for it.
DECK_CSS_WITHOUT_TOKENS = """section.slide {
  padding: 40px;
  color: #111111;
}

.card {
  padding: 10px;
}

@media print {
  section.slide {
    page-break-after: always;
  }
}
"""

# A deck that satisfies the backstop: every TOKEN_CSS property defined and the
# "Acme Sans" family still declared. (Guarded by
# test_the_compliant_fixture_really_is_compliant below.)
COMPLIANT_DECK_CSS = """:root {
  --tellr-brand: #ff3621;
  --tellr-ink: #1b3139;
}

@font-face {
  font-family: "Acme Sans";
  font-weight: 400;
  src: url("acme-400.woff2") format("woff2");
}

section.slide {
  padding: 40px;
  color: var(--tellr-ink);
}

.card {
  padding: 10px;
}

@media print {
  section.slide {
    page-break-after: always;
  }
}
"""

# THE one emitted block. It deliberately OVERLAPS the deck's ``section.slide``
# and ``@media print`` — so a concatenating implementation leaves two of each —
# and carries one of every at-rule kind the merge has to preserve.
EMITTED_STYLE_BLOCK = """section.slide {
  padding: 64px;
  color: var(--tellr-ink);
}

@media print {
  section.slide {
    page-break-after: avoid;
  }
}

@media (max-width: 1200px) {
  section.slide {
    padding: 24px;
  }
}

@keyframes tellr-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

@supports (display: grid) {
  .grid { display: grid; }
}

@import url("brand.css");
"""

# Every at-rule that must still be in the sheet after aggregation.
AT_RULE_MARKERS = (
    '@import url("brand.css");',
    "@media print",
    "@media (max-width: 1200px)",
    "@keyframes tellr-fade",
    "@supports (display: grid)",
)

# Custom-property DEFINITIONS only: inside ``var(--x)`` the name is followed by
# ``)``, so a var() reference never matches.
_PROP_DEF_RE = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")


def _prop_def_counts(css: str) -> Counter:
    """How many times each custom property is DEFINED in *css*."""
    return Counter(_PROP_DEF_RE.findall(css))


def _block_keys(css: str) -> list:
    """Top-level block keys, in order — the merge's own view of a stylesheet."""
    return [block.key for block in parse_css_blocks(css)]


class TestFixtureSelfChecks:
    """A wrong fixture makes the backstop tests lie. Check the fixtures first."""

    def test_the_compliant_fixture_really_is_compliant(self):
        """Every TOKEN_CSS property defined, and the token font family declared.

        Without this guard, a later fixture edit that drops one property turns
        test_a_compliant_deck_is_left_untouched into a test of the prepend
        path, passing for the wrong reason or failing for one.
        """
        token_props = set(_prop_def_counts(TOKEN_CSS))
        deck_props = set(_prop_def_counts(COMPLIANT_DECK_CSS))

        assert token_props == {"--tellr-brand", "--tellr-ink"}
        assert token_props <= deck_props, f"undefined in the deck: {token_props - deck_props}"
        assert 'font-family: "Acme Sans"' in COMPLIANT_DECK_CSS

    def test_the_non_compliant_fixture_defines_no_token_properties(self):
        assert not set(_prop_def_counts(TOKEN_CSS)) & set(
            _prop_def_counts(DECK_CSS_WITHOUT_TOKENS)
        )
        assert "@font-face" not in DECK_CSS_WITHOUT_TOKENS

    def test_a_var_reference_is_not_counted_as_a_definition(self):
        """The counting trap, pinned: defined once and referenced once is ONE."""
        css = ":root { --x: red; }\n.a { color: var(--x); }"

        assert css.count("--x") == 2
        assert _prop_def_counts(css)["--x"] == 1


class TestTheEmittedBlockIsMerged:
    """The one emitted block is merged into the deck CSS, without duplication."""

    def test_the_one_emitted_block_is_merged_without_duplication(self):
        result = aggregate_deck_css(DECK_CSS_WITHOUT_TOKENS, [EMITTED_STYLE_BLOCK], None)

        keys = _block_keys(result)
        # One block per key: the emitted rule OVERRODE the deck's, it did not
        # land beside it. A concatenating implementation gives two of each.
        assert keys.count("section.slide") == 1, f"section.slide duplicated: {keys}"
        assert keys.count(("media", "print")) == 1, f"@media print duplicated: {keys}"

        # The emitted values won and the overridden text is gone.
        assert "padding: 64px" in result
        assert "padding: 40px" not in result
        assert "page-break-after: avoid" in result
        assert "page-break-after: always" not in result

        # Blocks only the deck had are preserved — nothing is deleted by omission.
        assert keys.count(".card") == 1
        assert "padding: 10px" in result

    def test_the_emitted_block_went_through_merge_css_not_concatenation(self):
        """The direct assertion against the concatenate-and-merge-with-"" form.

        ``merge_css`` re-assembles a qualified rule as
        ``f"{selector} {{\\n{declarations}\\n}}"`` and hoists ``@import`` to the
        front. Concatenated source text keeps the fixture's own indentation and
        leaves the ``@import`` where it was written, so both assertions below
        fail if the block never reached the merge.
        """
        result = aggregate_deck_css(DECK_CSS_WITHOUT_TOKENS, [EMITTED_STYLE_BLOCK], None)

        assert "section.slide {\npadding: 64px;" in result
        assert result.startswith('@import url("brand.css");')
        assert "  padding: 64px;" not in result

    def test_at_rules_survive_aggregation(self):
        """What the dependency on the at-rule-preserving merge_css is FOR.

        Before ws4a's rewrite, merging over a {selector: declarations} dict
        dropped every at-rule: a branded deck lost its print rules, animations
        and web fonts on the first edit, permanently, because the merged CSS is
        persisted and re-fed as existing_css.
        """
        result = aggregate_deck_css(DECK_CSS_WITHOUT_TOKENS, [EMITTED_STYLE_BLOCK], None)

        for marker in AT_RULE_MARKERS:
            assert marker in result, f"{marker} was dropped by the aggregator"

        # The two DIFFERENTLY-preluded @media blocks both survive; only the
        # same-prelude one was replaced.
        assert "padding: 24px" in result

    @pytest.mark.parametrize("block", ["", "   \n  ", "/* just a comment */"])
    def test_a_blank_or_comment_only_block_is_a_no_op(self, block):
        """Relies on merge_css's empty-replacement guard, deliberately.

        There is no separate skip in the aggregator, so this pins the behaviour
        that makes one unnecessary.
        """
        assert aggregate_deck_css(DECK_CSS_WITHOUT_TOKENS, [block], None) == (
            DECK_CSS_WITHOUT_TOKENS
        )

    def test_no_emitted_blocks_leaves_the_existing_css_alone(self):
        """The legacy/unpinned deck: an empty list, and no token stylesheet."""
        assert aggregate_deck_css(DECK_CSS_WITHOUT_TOKENS, [], None) == DECK_CSS_WITHOUT_TOKENS
        assert aggregate_deck_css(None, [], None) == ""
        assert aggregate_deck_css(None, None, None) == ""


class TestTokenBackstop:
    """ensure_deck_token_css, run at the post-commit write on EMITTED CSS."""

    def test_the_backstop_prepends_when_a_token_is_undefined(self):
        """PREPENDS, so deck CSS stays later in the cascade and still wins."""
        result = aggregate_deck_css(DECK_CSS_WITHOUT_TOKENS, [EMITTED_STYLE_BLOCK], TOKEN_CSS)

        assert _TOKEN_CSS_REEMIT_MARKER in result
        assert "--tellr-brand: #ff3621" in result
        assert "--tellr-ink: #1b3139" in result

        # Prepended, not appended: the token definitions come BEFORE the deck's
        # own rules, so anything the model authored overrides them.
        assert result.index("--tellr-brand") < result.index("padding: 64px")

        # ...and the model's own CSS is still all there.
        assert "padding: 64px" in result
        for marker in AT_RULE_MARKERS:
            assert marker in result

    def test_a_compliant_deck_is_left_untouched(self):
        """Untouched means byte-identical to the merge alone."""
        result = aggregate_deck_css(COMPLIANT_DECK_CSS, [EMITTED_STYLE_BLOCK], TOKEN_CSS)

        assert result == merge_css(COMPLIANT_DECK_CSS, EMITTED_STYLE_BLOCK)
        assert _TOKEN_CSS_REEMIT_MARKER not in result
        # One definition each, from the deck's own :root — not a second copy
        # prepended alongside it.
        counts = _prop_def_counts(result)
        assert counts["--tellr-brand"] == 1
        assert counts["--tellr-ink"] == 1

    def test_an_empty_deck_still_gets_the_token_backstop(self):
        """Why this task exists: with nothing emitted there is nothing BUT tokens."""
        result = aggregate_deck_css("", [], TOKEN_CSS)

        assert _TOKEN_CSS_REEMIT_MARKER in result
        assert "--tellr-brand: #ff3621" in result

    @pytest.mark.parametrize("token_css", [None, "", "   \n  "])
    def test_no_token_css_means_no_backstop_and_no_crash(self, token_css):
        result = aggregate_deck_css(DECK_CSS_WITHOUT_TOKENS, [EMITTED_STYLE_BLOCK], token_css)

        assert result == merge_css(DECK_CSS_WITHOUT_TOKENS, EMITTED_STYLE_BLOCK)
        assert _TOKEN_CSS_REEMIT_MARKER not in result
        assert "--tellr-brand" not in result

    def test_a_failing_backstop_never_blocks_the_save(self, monkeypatch, caplog):
        """A stylesheet safety net must not be able to lose the user's work."""

        def _boom(deck_css, token_css):
            raise RuntimeError("backstop exploded")

        monkeypatch.setattr(deck_css_aggregator, "ensure_deck_token_css", _boom)
        caplog.set_level(logging.ERROR, logger=deck_css_aggregator.__name__)

        result = aggregate_deck_css(
            DECK_CSS_WITHOUT_TOKENS, [EMITTED_STYLE_BLOCK], TOKEN_CSS
        )

        # The merged CSS is returned, so the save proceeds with the emitted CSS.
        assert result == merge_css(DECK_CSS_WITHOUT_TOKENS, EMITTED_STYLE_BLOCK)
        assert "padding: 64px" in result
        # Swallowed, but not silent.
        assert "token backstop failed" in caplog.text


class TestTopOfSheetRehoist:
    """The backstop's prepend must not push ``@import`` out of position.

    Measured defect (coordinator's probe, reproduced by the first test below):
    with a backstop-triggering ``token_css`` and an ``@import`` in the emitted
    block, the token stylesheet was prepended at 0 and the ``@import`` ended up
    at 129 — and per the CSS spec ``@import`` must precede every rule except
    ``@charset``, so a browser silently ignores it and the deck loses that
    stylesheet. Same class of silent CSS loss the module exists to prevent.
    """

    IMPORT_BLOCK = (
        '@import url("brand.css");\n'
        "section.slide { padding: 64px; color: var(--brand-fg); }"
    )
    SINGLE_TOKEN_CSS = ":root { --brand-fg: #111; }"

    def test_a_hoisted_import_stays_ahead_of_a_prepended_token_stylesheet(self):
        result = aggregate_deck_css("", [self.IMPORT_BLOCK], self.SINGLE_TOKEN_CSS)

        # The backstop really did fire — otherwise this proves nothing.
        assert _TOKEN_CSS_REEMIT_MARKER in result
        assert "--brand-fg: #111" in result

        import_pos = result.index("@import")
        assert import_pos == 0, f"@import is not first:\n{result}"
        assert import_pos < result.index(_TOKEN_CSS_REEMIT_MARKER)
        assert import_pos < result.index(":root")
        # The emitted rule survived the re-hoist intact.
        assert "padding: 64px" in result

    def test_charset_still_precedes_import_after_the_rehoist(self):
        block = (
            '@import url("brand.css");\n'
            '@charset "utf-8";\n'
            "section.slide { color: var(--brand-fg); }"
        )

        result = aggregate_deck_css("", [block], self.SINGLE_TOKEN_CSS)

        assert (
            result.index("@charset")
            < result.index("@import")
            < result.index(_TOKEN_CSS_REEMIT_MARKER)
        )

    def test_a_sheet_already_in_order_is_returned_byte_identical(self):
        """The re-hoist is a no-op unless the backstop moved something.

        (The compliant-deck test asserts the same thing end-to-end; this one
        names the reason, so a re-hoist that reformatted every save would fail
        here with a clear cause.)
        """
        already_ordered = merge_css(DECK_CSS_WITHOUT_TOKENS, EMITTED_STYLE_BLOCK)

        assert already_ordered.startswith('@import url("brand.css");')
        assert aggregate_deck_css(DECK_CSS_WITHOUT_TOKENS, [EMITTED_STYLE_BLOCK], None) == (
            already_ordered
        )


class TestSemanticIdempotence:
    """Re-running the pipeline on its own output is stable — SEMANTICALLY.

    Not byte-identically: the backstop prepends a CSS COMMENT marker and
    merge_css drops top-level comments on the next pass, so byte equality would
    fail for a reason that is not a defect. The invariant is what matters —
    every token defined exactly once, every at-rule still present.
    """

    def test_the_pipeline_is_semantically_idempotent(self):
        first = aggregate_deck_css(DECK_CSS_WITHOUT_TOKENS, [EMITTED_STYLE_BLOCK], TOKEN_CSS)
        second = aggregate_deck_css(first, [EMITTED_STYLE_BLOCK], TOKEN_CSS)

        for label, css in (("first", first), ("second", second)):
            counts = _prop_def_counts(css)
            assert counts["--tellr-brand"] == 1, f"{label} pass: {counts}"
            assert counts["--tellr-ink"] == 1, f"{label} pass: {counts}"
            for marker in AT_RULE_MARKERS:
                assert marker in css, f"{marker} lost on the {label} pass"
            assert "padding: 64px" in css
            assert _block_keys(css).count("section.slide") == 1

        # Documented, not asserted-away: the ONE difference between the passes
        # is the comment marker, which is why this test asserts the invariant
        # instead of `second == first`.
        assert _TOKEN_CSS_REEMIT_MARKER in first
        assert _TOKEN_CSS_REEMIT_MARKER not in second
