"""Unit tests for CSS parsing and merging utilities."""
import pytest

from src.utils.css_utils import parse_css_rules, merge_css


class TestParseCssRules:
    """Tests for parse_css_rules function."""

    def test_parse_single_rule(self):
        """Parse a single CSS rule."""
        css = ".box { color: red; padding: 10px; }"
        result = parse_css_rules(css)
        
        assert ".box" in result
        assert "color: red" in result[".box"]

    def test_parse_multiple_rules(self):
        """Parse multiple CSS rules."""
        css = ".box { color: red; } .card { padding: 10px; }"
        result = parse_css_rules(css)
        
        assert len(result) == 2
        assert ".box" in result
        assert ".card" in result

    def test_parse_empty_css(self):
        """Empty CSS returns empty dict."""
        assert parse_css_rules("") == {}
        assert parse_css_rules(None) == {}

    def test_parse_invalid_css(self):
        """Invalid CSS returns empty dict without crashing."""
        result = parse_css_rules("not valid css {{{{")
        assert isinstance(result, dict)


class TestMergeCss:
    """Tests for merge_css function."""

    def test_override_existing_selector(self):
        """Replacement CSS overrides matching selectors."""
        existing = ".stat-box { background: red; }"
        replacement = ".stat-box { background: blue; }"
        
        result = merge_css(existing, replacement)
        
        assert "blue" in result
        assert "red" not in result

    def test_preserve_unmatched_selectors(self):
        """Selectors not in replacement are preserved."""
        existing = ".stat-box { background: red; } .card { padding: 10px; }"
        replacement = ".stat-box { background: blue; }"
        
        result = merge_css(existing, replacement)
        
        assert ".card" in result
        assert "padding" in result

    def test_add_new_selectors(self):
        """New selectors in replacement are added."""
        existing = ".box { color: red; }"
        replacement = ".new-class { margin: 5px; }"
        
        result = merge_css(existing, replacement)
        
        assert ".box" in result
        assert ".new-class" in result

    def test_empty_replacement_preserves_original(self):
        """Empty replacement returns original unchanged."""
        existing = ".box { color: red; }"
        
        result = merge_css(existing, "")
        
        assert result == existing


class TestCssMergeIntegration:
    """Integration tests for CSS merge in slide editing context."""

    def test_gradient_color_change(self):
        """Verify gradient backgrounds are correctly replaced."""
        existing = """.stat-box {
            background: linear-gradient(135deg, #EB4A34 0%, #d43d2a 100%);
            color: white;
        }"""
        replacement = """.stat-box {
            background: linear-gradient(135deg, #3C71AF 0%, #2d5a8f 100%);
            color: white;
        }"""
        
        result = merge_css(existing, replacement)
        
        assert "#3C71AF" in result
        assert "#EB4A34" not in result

