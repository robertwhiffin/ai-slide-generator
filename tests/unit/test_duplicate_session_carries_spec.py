"""Tests: duplicate_session carries deck_spec_json from the correct source.

Cover three executable behaviours introduced by A2's fix.

The fourth brief bullet — "the copy does not fire a mark_dirty trigger" — is a
code comment only, not an executable test: mark_dirty does not yet exist in this
repo (ws4d adds it).  The duplicate_session path is deliberately absent from
ws4d's trigger list because a duplicated spec is already correct for the HTML it
carries.  When ws4d lands it must not add mark_dirty to this route.
"""

import pytest

import src.database.models  # noqa: F401 — register all models with Base
from src.database.models.session import (
    SlideDeckVersion,
    UserSession,
)

# Reuse the fixtures and helpers from the existing suite rather than hand-rolling
# a second set — the version-branch assertion is only meaningful if the setup
# matches the production path already exercised by test_session_duplicate.py.
from tests.unit.test_session_duplicate import (  # noqa: F401 — pytest fixture re-export
    _add_deck,
    _make_root_session,
    db,
    session_manager,
)


class TestDuplicateSessionCarriesSpec:
    def test_live_deck_spec_is_copied(self, db, session_manager):
        """Duplicating a deck with a spec yields a copy whose spec equals the source."""
        owner = _make_root_session(
            db, session_id="src-spec", created_by="owner@test.com", title="Spec Test"
        )
        spec = '{"slides":[{"title":"Slide 1"}]}'
        _add_deck(db, owner, deck_spec_json=spec)

        result = session_manager.duplicate_session("src-spec", created_by="copier@test.com")

        copy = (
            db.query(UserSession)
            .filter(UserSession.session_id == result["session_id"])
            .one()
        )
        assert copy.slide_deck.deck_spec_json == spec

    def test_version_spec_snapshot_is_copied_not_live(self, db, session_manager):
        """Duplicating from a version carries that version's spec, not the live deck's spec.

        live_spec and version_spec are set to distinct values so the test can distinguish
        "copied the version snapshot" from "copied the live deck" — without different values
        the assertion is vacuous (either source would pass).
        """
        owner = _make_root_session(
            db,
            session_id="src-ver-spec",
            created_by="owner@test.com",
            title="Version Spec Test",
        )
        live_spec = '{"slides":[{"title":"Live Slide"}]}'
        version_spec = '{"slides":[{"title":"Old Slide from version 3"}]}'

        # Live deck carries live_spec; the version snapshot carries version_spec.
        _add_deck(db, owner, deck_spec_json=live_spec)
        db.add(
            SlideDeckVersion(
                session_id=owner.id,
                version_number=3,
                description="Older snapshot",
                deck_json='{"slides":[{"html":"<div>old</div>"}],"slide_count":1}',
                deck_spec_json=version_spec,
            )
        )
        db.commit()

        result = session_manager.duplicate_session(
            "src-ver-spec",
            created_by="copier@test.com",
            version_number=3,
        )

        copy = (
            db.query(UserSession)
            .filter(UserSession.session_id == result["session_id"])
            .one()
        )
        # Must carry the VERSION's snapshot, not the live deck's spec.
        assert copy.slide_deck.deck_spec_json == version_spec
        assert copy.slide_deck.deck_spec_json != live_spec

    def test_specless_deck_duplicate_does_not_raise(self, db, session_manager):
        """Duplicating a deck with no spec (NULL) must not raise, and the copy is also NULL."""
        owner = _make_root_session(
            db,
            session_id="src-nospec",
            created_by="owner@test.com",
            title="No Spec Test",
        )
        _add_deck(db, owner)  # deck_spec_json defaults to None

        result = session_manager.duplicate_session(
            "src-nospec", created_by="copier@test.com"
        )

        copy = (
            db.query(UserSession)
            .filter(UserSession.session_id == result["session_id"])
            .one()
        )
        assert copy.slide_deck.deck_spec_json is None
