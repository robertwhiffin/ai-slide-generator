"""Slide-style image guidelines reach the graph engine.

The monolith appends a slide style's ``image_guidelines`` to its prompt; the graph engine's
``_resolve_brand`` dropped them, so an image an author put in a style's guidelines never reached
the architect or the builders and decks were built without it (reproduced live: 0 images on a
2-slide deck). The guidelines now ride inside ``resolved_style``, the one style string every
graph agent already receives, with directions that make their ids count as supplied.
"""

from __future__ import annotations

import pytest

from src.services import agent_resolution
from src.services.agent_resolution import ResolvedStyle
from src.services.graph import nodes
from src.utils.image_refs import refs_in

STYLE = "Use navy titles on a white ground. Keep slides calm."
TOKEN = "Abc_123-tok"
GUIDELINES = f"Use this rocket icon on the title slide:\n{{{{image:{TOKEN}}}}}  /* rocket.png */"


def _brand_for(monkeypatch, image_guidelines):
    def fake_resolve(_config):
        return ResolvedStyle(
            slide_style=STYLE,
            design_system_active=False,
            design_system_compiled=None,
            template_pinned=False,
            image_guidelines=image_guidelines,
        )

    monkeypatch.setattr(agent_resolution, "resolve_style_source", fake_resolve)
    return nodes._resolve_brand(None)


def test_guidelines_ride_in_resolved_style_after_the_style_text(monkeypatch):
    resolved = _brand_for(monkeypatch, GUIDELINES)["resolved_style"]

    assert resolved.startswith(STYLE), "the style text itself must come first, unchanged"
    assert GUIDELINES in resolved, "the author's guidelines are carried verbatim"
    assert resolved.index(STYLE) < resolved.index(GUIDELINES)


def test_the_block_tells_the_agents_the_ids_are_supplied(monkeypatch):
    resolved = _brand_for(monkeypatch, GUIDELINES)["resolved_style"]
    block = resolved[len(STYLE):]

    assert "IMAGE GUIDELINES" in block
    lowered = block.lower()
    # the builder's IMAGE RULES only embed ids "the brief supplies": the block must say these
    # ids count as supplied, and tell the architect to put them in the slide briefs
    assert "supplied" in lowered
    assert "content_brief" in block
    assert '<img src="{{image:ID}}"' in block
    assert "never invent" in lowered or "never guess" in lowered


def test_the_image_token_survives_exactly_so_allow_lists_accept_it(monkeypatch):
    resolved = _brand_for(monkeypatch, GUIDELINES)["resolved_style"]

    # gateway_known_images is built from refs_in(resolved_style): the token must be found as-is
    assert TOKEN in refs_in(resolved)


@pytest.mark.parametrize("empty", [None, "", "   \n  "])
def test_a_style_without_guidelines_is_unchanged(monkeypatch, empty):
    assert _brand_for(monkeypatch, empty)["resolved_style"] == STYLE
