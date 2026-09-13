"""Unit tests for src.services.template_sections.

Coverage:
  section_inventory   — deck skeleton, single-slide, affordances, no-markup
                        (all values in every dict), size guard, zero-roots named
                        outcome
  extract_section     — verbatim (byte-for-byte), out-of-range, re-parenting
                        (<main>, sibling stripping, verbatim inside wrapper,
                        promoting ancestors not re-added)
  resolve_template_bytes — inactive DS (active-gate mock), unknown DS, valid
                           template, unwrapped CSS text (§17/§31), session
                           boundary (normalisation persisted), normalisation
                           applied (Fix 5)

All mocks patch ``src.core.database.get_db_session`` — the import happens
inside each function (lazy pattern from agent_factory) so patching the source
is required.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures and helpers
# ──────────────────────────────────────────────────────────────────────────────

# Deck skeleton: 3 slides, uses single-quoted attributes so BS4 serialization
# (which normalises to double quotes) is distinguishable from the verbatim slice.
DECK_HTML = (
    "<section class='slide cover'>"
    "<h1>Cover Title</h1>"
    "<img src='logo.svg'/>"
    "</section>"
    "<section class='slide content'>"
    "<p>Body text</p>"
    "<ul><li>Item</li></ul>"
    "</section>"
    "<section class='slide closing'>"
    "<canvas id='chart1'></canvas>"
    "<table><tr><td>data</td></tr></table>"
    "</section>"
)

# Single-slide template
SINGLE_SLIDE_HTML = (
    "<div class='slide'>"
    "<h1>Title</h1>"
    "<img src='hero.png'/>"
    "</div>"
)

# Layout with NO slide-classed roots (brand template without the 'slide' token)
NO_SLIDE_CLASS_HTML = (
    "<section class='cover'><h1>Title</h1></section>"
    "<section class='content'><p>Text</p></section>"
)

# Layout whose sole slide is wrapped in <main> (non-promoting tag)
MAIN_WRAPPED_HTML = (
    "<main>"
    "<div class='slide'><h1>Wrapped</h1></div>"
    "</main>"
)

# Multiple slides inside <main> (for sibling-stripping test)
MAIN_MULTI_HTML = (
    "<main>"
    "<div class='slide'>S1</div>"
    "<div class='slide'>S2</div>"
    "</main>"
)

# Layout where <section> wraps a sole <div class='slide'> → promotion fires
PROMOTED_WRAPPER_HTML = (
    "<section>"
    "<div class='slide'><h1>Promoted</h1></div>"
    "</section>"
)

# Verbatim preservation test: single-quoted attributes inside a non-promoting wrapper
MAIN_SINGLE_QUOTE_HTML = (
    "<main>"
    "<section class='slide cover'><h1>Title</h1></section>"
    "</main>"
)

# Layout with a <style> block for the resolve_template_bytes tests
LAYOUT_WITH_STYLE = (
    "<style>"
    ".slide { color: var(--brand-primary); font-family: var(--font-sans); }"
    "</style>"
    "<section class='slide cover'><h1>Title</h1></section>"
    "<section class='slide content'><p>Body</p></section>"
)

# Layout with no <style> block
LAYOUT_NO_STYLE = (
    "<section class='slide cover'><h1>Title</h1></section>"
)

# Un-normalised layout: tag-keyed CSS for a section.slide root.
# normalize_root_tag_selectors adds ".slide" to the "section" selector.
UNNORMALISED_LAYOUT = (
    '<style>section { color: red; font-family: Georgia, serif; }</style>'
    '<section class="slide"><h1>T</h1></section>'
)


def _make_db_cm(design_system=None):
    """Return a context-manager mock that yields a mock DB returning design_system."""
    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.first.return_value = (
        design_system
    )

    @contextmanager
    def _cm():
        yield mock_db

    return _cm


def _make_active_gate_db_cm(*, active_ds: Any, inactive_ds_result: Any = None):
    """Return a CM whose filter_by only yields active_ds WITHOUT is_active=True.

    When ``is_active=True`` is in the kwargs (production code), ``first()``
    returns ``inactive_ds_result`` (default: None, simulating an inactive row).
    When ``is_active`` is absent (sabotaged code that dropped the filter),
    ``first()`` returns ``active_ds``.

    This lets the inactive-DS test distinguish between:
    - production code:  filter_by(id=99, is_active=True) → None → no-template
    - sabotaged code:   filter_by(id=99)                 → DS   → proceeds
    """
    def _filter_by(**kwargs):
        inner = MagicMock()
        if kwargs.get("is_active") is True:
            inner.first.return_value = inactive_ds_result
        else:
            inner.first.return_value = active_ds
        return inner

    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.side_effect = _filter_by

    @contextmanager
    def _cm():
        yield mock_db

    return _cm


def _make_template_mock(*, layout_html: str, token_css: str | None) -> MagicMock:
    """Build a mock DesignSystemTemplate with the given attributes."""
    t = MagicMock()
    t.layout_html = layout_html
    t.token_css = token_css
    return t


def _make_real_db_session(engine):
    """Return a get_db_session-compatible CM backed by the given SQLAlchemy engine."""
    from sqlalchemy.orm import Session

    @contextmanager
    def _cm():
        with Session(engine) as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise

    return _cm


# ──────────────────────────────────────────────────────────────────────────────
# section_inventory
# ──────────────────────────────────────────────────────────────────────────────


class TestSectionInventory:
    def test_deck_skeleton_inventories_all_sections(self):
        from src.services.template_sections import section_inventory

        inv = section_inventory(DECK_HTML)
        assert len(inv) == 3

    def test_single_slide_template_inventories_exactly_one(self):
        from src.services.template_sections import section_inventory

        inv = section_inventory(SINGLE_SLIDE_HTML)
        assert len(inv) == 1

    def test_inventory_fields_present(self):
        from src.services.template_sections import section_inventory

        inv = section_inventory(SINGLE_SLIDE_HTML)
        entry = inv[0]
        assert "index" in entry
        assert "tag" in entry
        assert "classes" in entry
        assert "text_snippet" in entry
        assert "affordances" in entry

    def test_index_is_zero_based(self):
        from src.services.template_sections import section_inventory

        inv = section_inventory(DECK_HTML)
        assert [e["index"] for e in inv] == [0, 1, 2]

    def test_tag_and_classes_populated(self):
        from src.services.template_sections import section_inventory

        inv = section_inventory(DECK_HTML)
        assert inv[0]["tag"] == "section"
        assert "slide" in inv[0]["classes"]
        assert "cover" in inv[0]["classes"]

    def test_affordances_detected(self):
        from src.services.template_sections import section_inventory

        inv = section_inventory(DECK_HTML)
        # section 0 (cover): has img
        assert "image" in inv[0]["affordances"]
        # section 1 (content): has list
        assert "list" in inv[1]["affordances"]
        # section 2 (closing): has canvas and table
        assert "canvas" in inv[2]["affordances"]
        assert "table" in inv[2]["affordances"]

    def test_affordances_absent_when_not_present(self):
        from src.services.template_sections import section_inventory

        inv = section_inventory(DECK_HTML)
        # section 0: no canvas, no table, no list
        assert "canvas" not in inv[0]["affordances"]
        assert "table" not in inv[0]["affordances"]
        assert "list" not in inv[0]["affordances"]

    def test_inventory_contains_no_markup(self):
        """Every value in every dict must be free of HTML tags.

        Checks ALL values across ALL keys (using isinstance recursion) so a new
        field cannot smuggle markup past this test undetected.
        """
        import json
        from src.services.template_sections import section_inventory

        inv = section_inventory(DECK_HTML)

        def _no_markup(value, path):
            if isinstance(value, str):
                assert "<" not in value, (
                    f"Markup found in inventory at {path}: {value!r}"
                )
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    _no_markup(item, f"{path}[{i}]")
            elif isinstance(value, dict):
                for k, v in value.items():
                    _no_markup(v, f"{path}.{k}")

        for i, entry in enumerate(inv):
            _no_markup(entry, f"inv[{i}]")

    def test_inventory_smaller_than_layout(self):
        """The inventory (serialised) should be smaller than the layout bytes.

        A real template measures 24–47 KB; the inventory is a few hundred bytes.
        This test uses a layout padded to ~2 KB (well below the real lower bound,
        but large enough to prove the compaction property against a synthetic
        fixture without reaching for disk fixtures).
        """
        import json
        from src.services.template_sections import section_inventory

        # A realistically padded layout: three slides with lorem-ipsum content,
        # inline styles, and class attributes — totals > 1500 bytes.
        padding = "x" * 400
        big_layout = (
            f"<section class='slide cover'>"
            f"<style>.slide{{color:var(--brand);font-family:var(--sans);}}</style>"
            f"<h1>Cover Title</h1><p>{padding}</p>"
            f"</section>"
            f"<section class='slide content'>"
            f"<h2>Section Two</h2><p>{padding}</p><ul><li>Item one</li><li>Item two</li></ul>"
            f"</section>"
            f"<section class='slide closing'>"
            f"<canvas id='chart1'></canvas><p>{padding}</p>"
            f"</section>"
        )
        inv = section_inventory(big_layout)
        inv_bytes = len(json.dumps(inv).encode())
        layout_bytes = len(big_layout.encode())
        assert inv_bytes < layout_bytes, (
            f"Inventory ({inv_bytes} B) is not smaller than layout ({layout_bytes} B)"
        )

    def test_zero_roots_returns_empty_list(self):
        """A layout with no class='slide' roots returns [] — named fallback."""
        from src.services.template_sections import section_inventory

        inv = section_inventory(NO_SLIDE_CLASS_HTML)
        assert inv == []

    def test_zero_roots_logs_warning(self, caplog):
        """Zero-roots must emit a WARNING so the caller activates the fallback."""
        from src.services.template_sections import section_inventory

        with caplog.at_level(logging.WARNING, logger="src.services.template_sections"):
            section_inventory(NO_SLIDE_CLASS_HTML)

        assert any("no-template fallback" in m or "no elements with class='slide'" in m
                   for m in caplog.messages), (
            "Expected a warning about zero slide roots"
        )

    def test_text_snippet_truncated_at_80_chars(self):
        long_text = "A" * 200
        layout = f"<section class='slide'><p>{long_text}</p></section>"
        from src.services.template_sections import section_inventory

        inv = section_inventory(layout)
        assert len(inv[0]["text_snippet"]) <= 81  # 80 chars + ellipsis char


# ──────────────────────────────────────────────────────────────────────────────
# extract_section
# ──────────────────────────────────────────────────────────────────────────────


class TestExtractSection:
    def test_extraction_is_byte_for_byte_verbatim(self):
        """Extracted text must match the original bytes exactly.

        Fixture uses single-quoted attributes, which BS4's serializer normalises
        to double quotes.  This test goes red if the implementation returns
        str(root) or str(BeautifulSoup(str(root), ...)).
        """
        from src.services.template_sections import extract_section

        # First section verbatim from DECK_HTML
        expected = (
            "<section class='slide cover'>"
            "<h1>Cover Title</h1>"
            "<img src='logo.svg'/>"
            "</section>"
        )
        result = extract_section(DECK_HTML, 0)
        assert result == expected, (
            f"Expected verbatim slice:\n{expected!r}\n\nGot:\n{result!r}"
        )

    def test_verbatim_second_section(self):
        from src.services.template_sections import extract_section

        expected = (
            "<section class='slide content'>"
            "<p>Body text</p>"
            "<ul><li>Item</li></ul>"
            "</section>"
        )
        result = extract_section(DECK_HTML, 1)
        assert result == expected

    def test_out_of_range_raises_index_error(self):
        from src.services.template_sections import extract_section

        with pytest.raises(IndexError):
            extract_section(DECK_HTML, 99)

    def test_negative_index_raises_index_error(self):
        from src.services.template_sections import extract_section

        with pytest.raises(IndexError):
            extract_section(DECK_HTML, -1)

    def test_zero_roots_raises_index_error(self):
        """A layout with no slide roots must raise for ANY index."""
        from src.services.template_sections import extract_section

        with pytest.raises(IndexError):
            extract_section(NO_SLIDE_CLASS_HTML, 0)

    # ── Re-parenting tests (Playwright probe confirmed divergence) ────────────

    def test_main_wrapper_included_in_extracted_section(self):
        """A <main> wrapper (non-promoting) is included in the returned markup.

        Probe measured: color, font-family, and custom-property-backed padding and
        background-color are all lost when the section is extracted without its
        <main> ancestor.  Re-parenting restores the inheritance context.
        """
        from src.services.template_sections import extract_section

        result = extract_section(MAIN_WRAPPED_HTML, 0)
        # The <main> wrapper must be present
        assert result.startswith("<main"), (
            f"Expected <main> wrapper in result, got: {result[:80]!r}"
        )
        # The section itself must be inside
        assert "class='slide'" in result
        assert "<h1>Wrapped</h1>" in result

    def test_main_wrapper_reparented_equals_full_layout(self):
        """Single slide in <main>: re-parented result equals the full layout."""
        from src.services.template_sections import extract_section

        result = extract_section(MAIN_WRAPPED_HTML, 0)
        assert result == MAIN_WRAPPED_HTML

    def test_sibling_slides_stripped_from_wrapper(self):
        """When multiple slides share a non-promoting wrapper, siblings are stripped."""
        from src.services.template_sections import extract_section

        r0 = extract_section(MAIN_MULTI_HTML, 0)
        r1 = extract_section(MAIN_MULTI_HTML, 1)

        # Slide 0 must not contain Slide 1's content
        assert "S2" not in r0, "Slide 0 should not include sibling S2"
        # Slide 1 must not contain Slide 0's content
        assert "S1" not in r1, "Slide 1 should not include sibling S1"
        # Both must include the <main> wrapper
        assert r0.startswith("<main")
        assert r1.startswith("<main")

    def test_section_markup_verbatim_inside_reparented_wrapper(self):
        """The section element itself is byte-for-byte verbatim inside the wrapper.

        Fixture uses single-quoted attributes in the slide element; BS4 would
        normalise these to double quotes.  The wrapper (reconstructed) may use
        double quotes, but the slide content must be the original bytes.
        """
        from src.services.template_sections import extract_section

        result = extract_section(MAIN_SINGLE_QUOTE_HTML, 0)

        # The result must contain the verbatim section with single-quoted attributes
        assert "class='slide cover'" in result, (
            f"Expected verbatim single-quoted attrs in result: {result!r}"
        )
        # The wrapper must be present
        assert "<main" in result

    def test_promoting_ancestors_not_rewrapped(self):
        """A section whose ancestors are all promoting tags is returned unwrapped.

        <section> wrapping a sole <div class='slide'> is promoted by
        find_slide_roots.  The promoted <section> has no non-promoting ancestors,
        so no additional wrapper is added.
        """
        from src.services.template_sections import extract_section

        result = extract_section(PROMOTED_WRAPPER_HTML, 0)
        # Must be the promoted <section>, verbatim
        assert result == PROMOTED_WRAPPER_HTML, (
            f"Expected promoted wrapper verbatim, got: {result!r}"
        )
        # Must NOT have a second <section> wrapping the first
        assert result.count("<section") == 1

    def test_promoted_wrapper_extracted_verbatim(self):
        """A <section> that wraps a sole <div class='slide'> is promoted.

        The verbatim text of the promoted <section> (NOT the inner div) is
        returned.
        """
        from src.services.template_sections import extract_section

        result = extract_section(PROMOTED_WRAPPER_HTML, 0)
        # Promoted root is the outer <section>
        assert result.startswith("<section"), (
            f"Expected promoted <section>, got: {result[:50]!r}"
        )
        # And it must contain the inner slide
        assert "class='slide'" in result

    def test_single_slide_extraction(self):
        from src.services.template_sections import extract_section

        result = extract_section(SINGLE_SLIDE_HTML, 0)
        assert result == SINGLE_SLIDE_HTML

    def test_all_sections_extracted_correctly(self):
        """Deck skeleton: extracting each index yields each section verbatim."""
        from src.services.template_sections import extract_section

        sections = [extract_section(DECK_HTML, i) for i in range(3)]
        # All three should be non-empty and distinct
        assert len(set(sections)) == 3
        # Concatenated, they reconstruct the full layout
        assert "".join(sections) == DECK_HTML


# ──────────────────────────────────────────────────────────────────────────────
# resolve_template_bytes
# ──────────────────────────────────────────────────────────────────────────────


class TestResolveTemplateBytes:
    def test_inactive_design_system_returns_empty_triple(self):
        """An inactive (or unknown) design system resolves to the no-template path.

        Sabotage target 1: remove the is_active=True filter from the query.
        Without the filter, the DB returns the (inactive) DS object.
        With the filter (production code), the DB returns None.

        The mock distinguishes the two call patterns via _make_active_gate_db_cm:
        - filter_by(id=99, is_active=True) → None    (simulates inactive row)
        - filter_by(id=99)                 → mock_ds (simulates unchecked access)

        After finding the DS in the sabotaged path, get_template_for_generation
        returns a valid template so the function proceeds to a non-empty result,
        making the assertion fail.
        """
        from src.services.template_sections import resolve_template_bytes

        mock_ds = MagicMock()
        template = _make_template_mock(
            layout_html=LAYOUT_NO_STYLE, token_css="--tok: val;"
        )

        db_cm = _make_active_gate_db_cm(
            active_ds=mock_ds, inactive_ds_result=None
        )

        with patch("src.core.database.get_db_session", db_cm):
            with patch(
                "src.services.design_system_templates.get_template_for_generation",
                return_value=template,
            ):
                result = resolve_template_bytes(design_system_id=99, template_id=1)

        assert result == ("", "", ""), (
            f"Expected ('', '', '') for inactive DS, got {result!r}"
        )

    def test_unknown_design_system_returns_empty_triple(self):
        """A design system id not in the DB resolves to the no-template path."""
        from src.services.template_sections import resolve_template_bytes

        with patch("src.core.database.get_db_session", _make_db_cm(design_system=None)):
            result = resolve_template_bytes(design_system_id=9999, template_id=1)

        assert result == ("", "", "")

    def test_valid_template_returns_all_three_parts(self):
        """Happy path: active DS + valid template_id returns (html, css, token)."""
        from src.services.template_sections import resolve_template_bytes

        mock_ds = MagicMock()
        template = _make_template_mock(
            layout_html=LAYOUT_NO_STYLE,
            token_css="--brand-primary: #0c3456;",
        )

        with patch("src.core.database.get_db_session", _make_db_cm(design_system=mock_ds)):
            with patch(
                "src.services.design_system_templates.get_template_for_generation",
                return_value=template,
            ):
                result = resolve_template_bytes(design_system_id=1, template_id=42)

        layout_html, style_css, token_css = result
        assert layout_html == LAYOUT_NO_STYLE
        assert token_css == "--brand-primary: #0c3456;"

    def test_style_block_css_is_unwrapped_text(self):
        """Second return value must be CSS text, NOT ``<style>``-wrapped markup.

        §17/§31: aggregate_deck_css expects CSS text; a <style>-wrapped block
        silently parses to tinycss2 error nodes and is dropped.

        Sabotage target 2: return the <style>-wrapped block → this test goes red.
        """
        from src.services.template_sections import resolve_template_bytes

        mock_ds = MagicMock()
        template = _make_template_mock(
            layout_html=LAYOUT_WITH_STYLE,
            token_css=None,
        )

        with patch("src.core.database.get_db_session", _make_db_cm(design_system=mock_ds)):
            with patch(
                "src.services.design_system_templates.get_template_for_generation",
                return_value=template,
            ):
                _, style_css, _ = resolve_template_bytes(design_system_id=1, template_id=1)

        # Must be CSS text, not wrapped
        assert not style_css.strip().startswith("<style"), (
            f"style_block_css must be unwrapped CSS text, got: {style_css[:80]!r}"
        )
        # Must contain the CSS content
        assert "color: var(--brand-primary)" in style_css
        assert "font-family: var(--font-sans)" in style_css

    def test_no_style_block_returns_empty_string(self):
        """Layout without <style> returns '' for style_block_css_text."""
        from src.services.template_sections import resolve_template_bytes

        mock_ds = MagicMock()
        template = _make_template_mock(
            layout_html=LAYOUT_NO_STYLE,
            token_css=None,
        )

        with patch("src.core.database.get_db_session", _make_db_cm(design_system=mock_ds)):
            with patch(
                "src.services.design_system_templates.get_template_for_generation",
                return_value=template,
            ):
                _, style_css, _ = resolve_template_bytes(design_system_id=1, template_id=1)

        assert style_css == ""

    def test_none_token_css_returns_empty_string(self):
        """token_css=None on the row → third return value is ""."""
        from src.services.template_sections import resolve_template_bytes

        mock_ds = MagicMock()
        template = _make_template_mock(layout_html=LAYOUT_NO_STYLE, token_css=None)

        with patch("src.core.database.get_db_session", _make_db_cm(design_system=mock_ds)):
            with patch(
                "src.services.design_system_templates.get_template_for_generation",
                return_value=template,
            ):
                _, _, token_css = resolve_template_bytes(design_system_id=1, template_id=1)

        assert token_css == ""

    def test_unknown_template_id_returns_empty_triple(self):
        """get_template_for_generation returning None → no-template path."""
        from src.services.template_sections import resolve_template_bytes

        mock_ds = MagicMock()

        with patch("src.core.database.get_db_session", _make_db_cm(design_system=mock_ds)):
            with patch(
                "src.services.design_system_templates.get_template_for_generation",
                return_value=None,
            ):
                result = resolve_template_bytes(design_system_id=1, template_id=999)

        assert result == ("", "", "")

    def test_exception_in_db_returns_empty_triple(self):
        """Any unexpected error resolves to the no-template path (fails closed)."""
        from src.services.template_sections import resolve_template_bytes

        @contextmanager
        def _boom():
            raise RuntimeError("db exploded")
            yield  # noqa: unreachable

        with patch("src.core.database.get_db_session", _boom):
            result = resolve_template_bytes(design_system_id=1, template_id=1)

        assert result == ("", "", "")

    def test_all_return_values_are_strings_not_none(self):
        """Return values must never be None — downstream callers unpack directly."""
        from src.services.template_sections import resolve_template_bytes

        with patch("src.core.database.get_db_session", _make_db_cm(design_system=None)):
            a, b, c = resolve_template_bytes(design_system_id=99, template_id=1)

        assert a is not None
        assert b is not None
        assert c is not None
        assert isinstance(a, str)
        assert isinstance(b, str)
        assert isinstance(c, str)

    def test_normalisation_is_applied_and_persisted(self):
        """get_template_for_generation must be called INSIDE get_db_session.

        materialize_templates self-heals by assigning ``template.layout_html``
        with normalised root-tag selectors; SQLAlchemy commits that write when
        the session context exits.  If the call is moved outside the ``with``
        block, the design-system object is detached, the assignment is made on
        a dead object, and nothing is committed.

        Two guarantees tested:
        1. The returned layout_html IS normalised (not the raw row value).
        2. The normalised value IS persisted — survives a fresh-session re-read.

        Sabotage for (1): return the template's layout_html DIRECTLY (bypass
        get_template_for_generation) so normalisation never runs → the returned
        value is the un-normalised raw form → assertion fails.

        Sabotage for (2): move get_template_for_generation OUTSIDE the session
        → detached row → normalisation is either not applied (DetachedInstanceError)
        or not committed → re-read shows un-normalised → assertion fails.
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool

        import src.database.models  # noqa: F401 — register all ORM models
        from src.core.database import Base

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)

        from src.database.models import DesignSystem
        from src.database.models.design_system import DesignSystemTemplate

        # Seed: DS with an EXISTING template row that has un-normalised layout_html.
        # normalize_root_tag_selectors turns "section { color: red; }" into
        # "section, .slide { color: red; }" for a template with <section class="slide">.
        with Session(engine) as s:
            ds = DesignSystem(name="boundary-test-ds", is_active=True)
            tmpl = DesignSystemTemplate(
                name="test-tmpl",
                entry_path="templates/test/index.html",
                layout_html=UNNORMALISED_LAYOUT,
                token_css=None,
            )
            ds.templates.append(tmpl)
            s.add(ds)
            s.commit()
            ds_id, tmpl_id = ds.id, tmpl.id

        # Verify the seeded layout is actually un-normalised (guard against bad fixture)
        with Session(engine) as s:
            row = s.get(DesignSystemTemplate, tmpl_id)
            assert ".slide" not in row.layout_html, (
                "Fixture defect: seeded layout is already normalised"
            )

        from src.services.template_sections import resolve_template_bytes

        with patch("src.core.database.get_db_session", _make_real_db_session(engine)):
            layout_html, _, _ = resolve_template_bytes(ds_id, tmpl_id)

        # (1) The returned value must be normalised.
        assert ".slide" in layout_html, (
            "Returned layout was not normalised — get_template_for_generation "
            "must route through materialize_templates"
        )

        # (2) The normalised value must be persisted to the DB.
        with Session(engine) as s2:
            reloaded = s2.get(DesignSystemTemplate, tmpl_id)
            assert reloaded is not None
            assert ".slide" in reloaded.layout_html, (
                "Normalisation was not persisted: get_template_for_generation "
                "must be called INSIDE the get_db_session context so the "
                "session commits the self-heal write"
            )

        engine.dispose()


# ──────────────────────────────────────────────────────────────────────────────
# _extract_style_blocks_css (internal, but the contract matters for §17/§31)
# ──────────────────────────────────────────────────────────────────────────────


class TestExtractStyleBlocksCss:
    """Spot-check the internal helper that §17/§31 depend on."""

    def test_returns_css_text_not_tags(self):
        from src.services.template_sections import _extract_style_blocks_css

        html = "<style>.slide { color: red; }</style><section class='slide'></section>"
        result = _extract_style_blocks_css(html)
        assert "<style>" not in result
        assert "</style>" not in result
        assert "color: red" in result

    def test_multiple_blocks_concatenated(self):
        from src.services.template_sections import _extract_style_blocks_css

        html = (
            "<style>body { margin: 0; }</style>"
            "<style>.slide { padding: 1em; }</style>"
        )
        result = _extract_style_blocks_css(html)
        assert "margin: 0" in result
        assert "padding: 1em" in result

    def test_no_style_block_returns_empty(self):
        from src.services.template_sections import _extract_style_blocks_css

        result = _extract_style_blocks_css("<section class='slide'><h1>hi</h1></section>")
        assert result == ""
