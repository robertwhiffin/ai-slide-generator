"""The deck-spec Markdown golden pair is a valid DeckSpec and a well-formed contract.

frontend/src/services/deckSpecMarkdown.ts renders full.deck-spec.json to full.md byte for
byte (vitest + e2e). It is also the contract any later backend/MCP renderer must reproduce
(docs/technical/export-features.md), so it must be a spec the backend would accept, it must
spell out every field explicitly, and the .md must survive any checkout unchanged.
"""
import json
from pathlib import Path

from src.domain.deck_spec import (
    DeckSpec,
    DeckStyle,
    DeckStyleComponent,
    DesignContractRef,
    ResolvedData,
    ResolvedFigure,
    SlideSpec,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "fixtures" / "deck-spec-markdown"


def _raw() -> dict:
    return json.loads((FIXTURE_DIR / "full.deck-spec.json").read_text(encoding="utf-8"))


def test_fixture_is_a_valid_deck_spec():
    DeckSpec.model_validate(_raw())


def test_fixture_round_trips_through_the_model_unchanged():
    # A value a validator would rewrite (e.g. a padded slide_type) would make the contract
    # describe input the backend never stores.
    raw = _raw()
    assert DeckSpec.model_validate(raw).model_dump() == raw


def test_fixture_spells_out_every_field_of_every_model():
    raw = _raw()
    assert set(raw) == set(DeckSpec.model_fields)
    assert set(raw["design_contract"]) == set(DesignContractRef.model_fields)
    assert set(raw["resolved_data"]) == set(ResolvedData.model_fields)
    assert raw["resolved_data"]["figures"] and raw["slides"]
    for figure in raw["resolved_data"]["figures"]:
        assert set(figure) == set(ResolvedFigure.model_fields)
    for slide in raw["slides"]:
        assert set(slide) == set(SlideSpec.model_fields)
        # Deck style (C1): every slide spells out a look, so the renderer has one to show.
        assert isinstance(slide["look"], str) and slide["look"].strip(), slide["position"]
    # A null deck_style would spell out none of its fields (C1, C8).
    assert isinstance(raw["deck_style"], dict)
    assert set(raw["deck_style"]) == set(DeckStyle.model_fields)
    assert raw["deck_style"]["components"]
    for component in raw["deck_style"]["components"]:
        assert set(component) == set(DeckStyleComponent.model_fields)


def test_golden_markdown_is_lf_utf8_with_one_trailing_newline():
    data = (FIXTURE_DIR / "full.md").read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in data
    assert data.endswith(b"\n") and not data.endswith(b"\n\n")
    data.decode("utf-8")
