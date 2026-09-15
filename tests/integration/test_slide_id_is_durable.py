"""`slide_id` is durable identity, and the whole stack already depends on it.

THE BUG THIS FILE WAS WRITTEN RED AGAINST
-----------------------------------------
`_attribute_slide_records` resolves "which slide does this verdict belong to?" by
`slide_id` first, documented as "durable per-slide identity".  But
`chat_service._reindex_slide_ids` used to rewrite EVERY slide_id to
`slide_<index>` after any list mutation, and `_upsert_slide_row` writes those onto
the rows.  So once a deck had been saved through chat_service once, both sides of
that comparison carried `slide_0..slide_N` and matching "by identity" WAS matching
by position: pass 3's "unclaimed" guard — the whole of the F1/F2 fix — never got a
chance to run, and a reorder handed slide A's verdict to slide B.

Measured against the pre-fix tree through this very route: a 3-slide deck reordered
`[1,0,2]` moved the HTML and left every verdict where it was.

WHY THE FIX IS AN ALIGNMENT, NOT A NEW CONTRACT
-----------------------------------------------
Nothing anywhere in `src/` or `frontend/src` parses an index out of a slide_id.  The
frontend was written to treat it as durable identity and says so:
`SlideViewer.tsx` keys its verification Map and its per-slide staleness Set on
slide_id "so deck mutations (delete, reorder) cannot shift the index → result
mapping"; `AppLayout.tsx` matches slides across deck versions with
`findIndex(s => s.slide_id === ...)`; `ThumbnailRibbon.tsx` uses it as the React key
AND as the dnd-kit sortable item id.  `_reindex_slide_ids`' own docstring gives its
purpose as preventing duplicate React keys — which needs UNIQUENESS.  Sequentiality
was incidental damage, and it is what destroyed durability.

So these tests pin the invariant that replaced it: **every slide has a unique id, and
an id a slide already has is never taken away from it.**
"""
from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from src.database.models.session import SessionSlide, UserSession

from tests.integration.test_savepoint_e2e import (  # noqa: F401 — pytest fixtures
    _create_session,
    _make_fake_get_db_session,
    _seed_deck,
    client,
    mock_user,
    reset_singletons,
    test_db,
    test_db_engine,
    test_db_factory,
)

_SPEC_SYNC_DB = "src.services.spec_sync.get_db_session"
_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"


@pytest.fixture
def api(client, test_db_factory):
    fake = _make_fake_get_db_session(test_db_factory)
    with patch(_SPEC_SYNC_DB, fake), patch(_WRITER_DB, fake):
        yield client


def _rows(test_db_factory, session_id: str):
    """Every slide row in position order, on a FRESH session."""
    db = test_db_factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == session_id).one()
        )
        return [
            {
                "position": r.position,
                "html": r.html,
                "slide_id": r.slide_id,
                "verification_record": r.verification_record,
                "deck_spec_slide": r.deck_spec_slide,
            }
            for r in db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner.id)
            .order_by(SessionSlide.position)
            .all()
        ]
    finally:
        db.close()


def _stamp_each_row_with_its_own_marker(test_db_factory, session_id: str):
    """Give every row a verdict and a fragment that name the slide they belong to.

    Returns `{html: marker}` so assertions can be written per SLIDE rather than per
    position — the distinction the whole defect lives in.
    """
    db = test_db_factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == session_id).one()
        )
        rows = (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner.id)
            .order_by(SessionSlide.position)
            .all()
        )
        owned = {}
        for row in rows:
            marker = f"OWNED-BY-{row.position}"
            owned[row.html] = marker
            row.verification_record = json.dumps({"h": {"marker": marker}})
            row.deck_spec_slide = json.dumps({"purpose": marker})
        db.commit()
        return owned
    finally:
        db.close()


def _seeded(api, test_db_factory):
    session_id = _create_session(api)
    _seed_deck(session_id)
    return session_id


def _verdict(row) -> str | None:
    record = json.loads(row["verification_record"]) if row["verification_record"] else {}
    for value in record.values():
        if isinstance(value, dict) and "marker" in value:
            return value["marker"]
    return None


def _fragment(row) -> str | None:
    frag = json.loads(row["deck_spec_slide"]) if row["deck_spec_slide"] else None
    return (frag or {}).get("purpose")


# ---------------------------------------------------------------------------
# The defect, end to end
# ---------------------------------------------------------------------------


class TestAReorderCarriesEachSlidesOwnStateWithIt:
    def test_every_verdict_follows_its_own_slide_across_a_reorder(
        self, api, test_db_factory, mock_user
    ):
        """THE red-first guard. Failed against the pre-fix tree, for this reason:
        the reorder moved the HTML and left every verdict on its old position.

        Keyed on HTML, never on position.  "some verdict exists at position 0" is
        true of a completely mis-attributed deck.
        """
        session_id = _seeded(api, test_db_factory)
        owned = _stamp_each_row_with_its_own_marker(test_db_factory, session_id)
        assert len(owned) == 3, "fixture precondition: three slides with distinct HTML"

        resp = api.put(
            "/api/slides/reorder", json={"session_id": session_id, "new_order": [1, 0, 2]}
        )
        assert resp.status_code == 200, resp.text

        rows = _rows(test_db_factory, session_id)
        assert [r["html"] for r in rows] == [
            list(owned)[1],
            list(owned)[0],
            list(owned)[2],
        ], "fixture precondition: the reorder actually moved the slides"

        mis = {
            r["position"]: (owned[r["html"]], _verdict(r))
            for r in rows
            if _verdict(r) != owned[r["html"]]
        }
        assert not mis, (
            "a verdict did not follow its slide across the reorder — "
            "{position: (whose verdict it should be, whose it is)}: " + repr(mis)
        )

    def test_every_spec_fragment_follows_its_own_slide_across_a_reorder(
        self, api, test_db_factory, mock_user
    ):
        """The same claim for the per-slide spec fragment, on the same path."""
        session_id = _seeded(api, test_db_factory)
        owned = _stamp_each_row_with_its_own_marker(test_db_factory, session_id)

        resp = api.put(
            "/api/slides/reorder", json={"session_id": session_id, "new_order": [2, 1, 0]}
        )
        assert resp.status_code == 200, resp.text

        rows = _rows(test_db_factory, session_id)
        mis = {
            r["position"]: (owned[r["html"]], _fragment(r))
            for r in rows
            if _fragment(r) != owned[r["html"]]
        }
        assert not mis, (
            "a spec fragment did not follow its slide across the reorder — "
            "{position: (whose fragment it should be, whose it is)}: " + repr(mis)
        )

    def test_state_survives_two_consecutive_reorders(
        self, api, test_db_factory, mock_user
    ):
        """The second mutation, which is what made this shipped rather than latent.

        The first mutation is what used to stamp positional ids onto the ROWS, so
        the defect was reachable even on a deck whose rows started out with durable
        ids — and a one-mutation test can miss that.

        The rotation is deliberately NOT an involution.  `[1,0,2]` applied twice
        returns the deck to its original order, and a purely positional
        mis-attribution ALSO returns every verdict to where it started, so that pair
        passes against the buggy tree for the wrong reason (measured: it did).
        `[1,2,0]` twice leaves the deck genuinely rotated, so nothing cancels out.
        """
        session_id = _seeded(api, test_db_factory)
        owned = _stamp_each_row_with_its_own_marker(test_db_factory, session_id)
        original = list(owned)

        for _ in range(2):
            resp = api.put(
                "/api/slides/reorder",
                json={"session_id": session_id, "new_order": [1, 2, 0]},
            )
            assert resp.status_code == 200, resp.text

        rows = _rows(test_db_factory, session_id)
        assert [r["html"] for r in rows] == [
            original[2],
            original[0],
            original[1],
        ], "fixture precondition: [1,2,0] applied twice leaves the deck rotated by two"
        mis = {
            r["position"]: (owned[r["html"]], _verdict(r))
            for r in rows
            if _verdict(r) != owned[r["html"]]
        }
        assert not mis, (
            "after two reorders a verdict is on the wrong slide — "
            "{position: (should be, is)}: " + repr(mis)
        )


# ---------------------------------------------------------------------------
# The invariant that replaced sequentiality
# ---------------------------------------------------------------------------


class TestSlideIdsAreDurableAndUnique:
    def test_a_reorder_does_not_take_a_slides_id_away_from_it(
        self, api, test_db_factory, mock_user
    ):
        """Durability, asserted directly rather than only through its consequences.

        The id a slide had before the reorder is the id it has after it.  This is
        the property `_attribute_slide_records` pass 1, `SlideViewer`'s verification
        Map and `AppLayout`'s cross-version matching all read.
        """
        session_id = _seeded(api, test_db_factory)
        before = {r["html"]: r["slide_id"] for r in _rows(test_db_factory, session_id)}
        assert all(before.values()), "fixture precondition: every row has an id"

        resp = api.put(
            "/api/slides/reorder", json={"session_id": session_id, "new_order": [2, 0, 1]}
        )
        assert resp.status_code == 200, resp.text

        after = {r["html"]: r["slide_id"] for r in _rows(test_db_factory, session_id)}
        assert after == before, (
            "a slide's id changed under a reorder, so nothing downstream can use it "
            f"as identity: before={before} after={after}"
        )

    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param(
                lambda api, sid: api.put(
                    "/api/slides/reorder",
                    json={"session_id": sid, "new_order": [1, 2, 0]},
                ),
                id="reorder",
            ),
            pytest.param(
                lambda api, sid: api.post(
                    "/api/slides/0/duplicate", json={"session_id": sid}
                ),
                id="duplicate",
            ),
            pytest.param(
                lambda api, sid: api.delete(
                    "/api/slides/1", params={"session_id": sid}
                ),
                id="delete",
            ),
            pytest.param(
                lambda api, sid: api.post(
                    "/api/slides",
                    json={
                        "session_id": sid,
                        "position": 1,
                        "html": '<div class="slide"><h2>New</h2></div>',
                    },
                ),
                id="insert",
            ),
            pytest.param(
                lambda api, sid: api.patch(
                    "/api/slides/1",
                    json={
                        "session_id": sid,
                        "html": '<div class="slide"><h2>Edited</h2></div>',
                    },
                ),
                id="patch",
            ),
        ],
    )
    def test_every_mutating_route_leaves_the_ids_unique(
        self, api, test_db_factory, mock_user, mutate
    ):
        """Uniqueness is the invariant `_reindex_slide_ids` actually owes.

        Its docstring's purpose — no duplicate React keys — needs unique ids, and
        `ThumbnailRibbon` additionally uses slide_id as the dnd-kit sortable item
        id, where a collision breaks drag-and-drop outright.  Asserted for every
        route that changes the slide list, because "unique" has to survive the
        duplicate and insert paths that MINT ids, not just the ones that move them.
        """
        session_id = _seeded(api, test_db_factory)

        resp = mutate(api, session_id)
        assert resp.status_code == 200, resp.text

        ids = [r["slide_id"] for r in _rows(test_db_factory, session_id)]
        assert all(ids), f"a slide row came out with no id at all: {ids}"
        assert len(ids) == len(set(ids)), (
            f"duplicate slide_id after the mutation: {ids}"
        )

    def test_a_duplicated_slide_does_not_share_its_sources_id(
        self, api, test_db_factory, mock_user
    ):
        """A clone is a NEW slide, so it must not inherit its source's identity.

        `Slide.clone()` copies slide_id, and `duplicate_slide` used to rely on the
        wholesale reindex to pull them apart again.  With ids preserved, the clone
        needs its own or the deck carries two slides with one identity — which
        `_attribute_slide_records` pass 1 skips as ambiguous (so BOTH lose their
        verdict) and dnd-kit cannot sort.
        """
        session_id = _seeded(api, test_db_factory)
        before = _rows(test_db_factory, session_id)
        source_id = before[0]["slide_id"]

        resp = api.post("/api/slides/0/duplicate", json={"session_id": session_id})
        assert resp.status_code == 200, resp.text

        rows = _rows(test_db_factory, session_id)
        assert len(rows) == 4
        assert rows[0]["slide_id"] == source_id, (
            "the SOURCE slide lost its id to its own clone"
        )
        assert rows[1]["slide_id"] != source_id, (
            "the clone kept its source's slide_id: two slides now share one "
            f"identity ({source_id})"
        )
        ids = [r["slide_id"] for r in rows]
        assert len(ids) == len(set(ids)), f"duplicate slide_id after clone: {ids}"
