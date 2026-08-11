"""Unit tests for SessionSlide schema and new columns on SessionSlideDeck/SlideDeckVersion.

Task 1 of PR1 (row-per-slide rebuild). Tests are written first (TDD); they fail
until the model is added to session.py.
"""
import pytest
from src.database.models.session import SessionSlide


def test_session_slide_model_exists():
    """SessionSlide model is importable."""
    assert SessionSlide is not None
    assert hasattr(SessionSlide, "__tablename__")
    assert SessionSlide.__tablename__ == "session_slides"


def test_session_slide_has_required_columns():
    """SessionSlide has all columns from the Handoff spec."""
    columns = {c.name for c in SessionSlide.__table__.columns}
    required = {
        "id", "session_id", "position", "html", "slide_id", "scripts",
        "created_by", "created_at", "modified_by", "modified_at",
        "verification_record", "deck_spec_slide"
    }
    assert required.issubset(columns), f"Missing: {required - columns}"


def test_session_slide_composite_pk():
    """(session_id, position) is the composite primary key."""
    pk = SessionSlide.__table__.primary_key
    pk_cols = {c.name for c in pk.columns}
    assert pk_cols == {"session_id", "position"}


def test_session_slide_deck_has_new_columns():
    """SessionSlideDeck has deck_spec_json, css, and external_scripts_json columns."""
    from src.database.models.session import SessionSlideDeck
    columns = {c.name for c in SessionSlideDeck.__table__.columns}
    assert "deck_spec_json" in columns
    assert "css" in columns
    assert "external_scripts_json" in columns
    # Old columns still present during dual-write period
    assert "deck_json" in columns
    assert "verification_map" in columns


def test_slide_deck_version_has_deck_spec_json():
    """SlideDeckVersion.deck_spec_json column exists."""
    from src.database.models.session import SlideDeckVersion
    columns = {c.name for c in SlideDeckVersion.__table__.columns}
    assert "deck_spec_json" in columns
