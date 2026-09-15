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
import uuid

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


def _give_the_rows_durable_ids(test_db_factory, session_id):
    """Replace the parse-time `slide_<idx>` ids with ids that are NOT positional.

    A freshly parsed deck's ids happen to equal their positions, which makes a
    positional stamp a silent no-op — the blindness that let `update_slide`'s stamp
    survive a route-level uniqueness test with a `patch` case in it.  Tests about
    identity being PRESERVED need ids that cannot be reproduced by accident.
    """
    db = test_db_factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == session_id).one()
        )
        for row in (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner.id)
            .order_by(SessionSlide.position)
            .all()
        ):
            row.slide_id = f"durable-{uuid.uuid4().hex[:8]}"
        db.commit()
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
                # FOUR indices: every case below runs after the composing insert, so
                # the deck is four slides deep by the time the mutation arrives.
                lambda api, sid: api.put(
                    "/api/slides/reorder",
                    json={"session_id": sid, "new_order": [1, 2, 3, 0]},
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

        EVERY CASE IS COMPOSED, and that is the repair of this test's own blindness.
        It previously ran ONE mutation against a freshly seeded deck and passed while
        `update_slide` was stamping `slide_<index>` on every edit — because on a
        freshly parsed deck the row at index 1 already carries `slide_1`, so the
        stamp is a no-op and a single PATCH cannot expose it.  The defect is a
        COMPOSITION: an insert first shifts the slides, so the stamp then writes an
        id that belongs to a DIFFERENT slide further down the deck.  So each case
        now runs after an insert.
        """
        session_id = _seeded(api, test_db_factory)

        # The composition: shift the deck before mutating it, so a positional stamp
        # lands on an id that belongs to another slide.
        pre = api.post(
            "/api/slides",
            json={
                "session_id": session_id,
                "position": 1,
                "html": '<div class="slide"><h2>Shifter</h2></div>',
            },
        )
        assert pre.status_code == 200, pre.text

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


# ---------------------------------------------------------------------------
# An EDIT must preserve identity, and a positional stamp must never impersonate
# ---------------------------------------------------------------------------


class TestAnEditPreservesTheEditedSlidesIdentity:
    """`update_slide` stamped `slide_<index>` on every WYSIWYG edit.

    That is the one mutation that most obviously must NOT change identity: the
    slide is the same slide, with new HTML.  `SlideViewer.tsx:117` tracks per-slide
    staleness in a Set of slide_ids across exactly this operation, so an edit that
    renames its own slide loses the "edited since last verified" flag as well as the
    verdict.

    `update_slide` is also the only one of the ten `_reindex_slide_ids` call sites
    that has NO reindex after it, so its stamp went straight to the database with
    nothing to resolve the collision it could create.
    """

    def test_a_patch_does_not_change_the_edited_slides_id(
        self, api, test_db_factory, mock_user
    ):
        session_id = _seeded(api, test_db_factory)
        _give_the_rows_durable_ids(test_db_factory, session_id)
        before = _rows(test_db_factory, session_id)

        resp = api.patch(
            "/api/slides/1",
            json={
                "session_id": session_id,
                "html": '<div class="slide"><h2>Edited by a human</h2></div>',
            },
        )
        assert resp.status_code == 200, resp.text

        after = _rows(test_db_factory, session_id)
        assert after[1]["slide_id"] == before[1]["slide_id"], (
            "the edited slide was given a new id, so every downstream consumer that "
            "keyed on the old one — its verdict, its staleness flag — is now orphaned:"
            f" {before[1]['slide_id']!r} -> {after[1]['slide_id']!r}"
        )
        # PAIRED: the slides nobody touched kept theirs too, so the assertion above
        # is not satisfied by a route that rewrote every id to the same thing.
        assert [r["slide_id"] for r in after] == [r["slide_id"] for r in before]

    def test_the_patch_response_reports_the_slides_real_id(
        self, api, test_db_factory, mock_user
    ):
        """The response used to return `f"slide_{index}"` regardless.

        A caller told a positional id will store it and hand it back later, which
        reintroduces the impersonation from outside the backend entirely.
        """
        session_id = _seeded(api, test_db_factory)
        _give_the_rows_durable_ids(test_db_factory, session_id)
        expected = _rows(test_db_factory, session_id)[1]["slide_id"]

        resp = api.patch(
            "/api/slides/1",
            json={
                "session_id": session_id,
                "html": '<div class="slide"><h2>Edited</h2></div>',
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["slide_id"] == expected, (
            "the PATCH response reported an id the slide does not have: "
            f"{resp.json()['slide_id']!r} vs {expected!r}"
        )

    def test_insert_then_edit_leaves_no_duplicate_id_and_loses_no_verdict(
        self, api, test_db_factory, mock_user
    ):
        """THE composition, on the deck shape that makes it bite: monolith ids.

        A freshly parsed deck carries `slide_0..slide_N` (`from_html_string`).  Insert
        a slide at 1 and the slide holding `slide_1` moves to index 2.  Editing index
        2 then stamped it `slide_2` — an id that belongs to the LAST slide — so two
        rows carried `slide_2`, the edited slide was handed the last slide's verdict
        and spec fragment by attribution tier 1, and the last slide lost both.

        Measured against the pre-fix tree, which is why the assertions below name
        both halves: the duplicate AND the theft.
        """
        session_id = _seeded(api, test_db_factory)
        owned = _stamp_each_row_with_its_own_marker(test_db_factory, session_id)
        last_html = list(owned)[2]

        resp = api.post(
            "/api/slides",
            json={
                "session_id": session_id,
                "position": 1,
                "html": '<div class="slide">TAG-INSERTED</div>',
            },
        )
        assert resp.status_code == 200, resp.text

        resp = api.patch(
            "/api/slides/2",
            json={"session_id": session_id, "html": '<div class="slide">TAG-EDITED</div>'},
        )
        assert resp.status_code == 200, resp.text

        rows = _rows(test_db_factory, session_id)
        ids = [r["slide_id"] for r in rows]
        assert len(ids) == len(set(ids)), (
            "two slides share an id after insert-then-edit: duplicate React keys and "
            f"duplicate dnd-kit sortable ids, and tier 1 cannot resolve either: {ids}"
        )

        # The untouched last slide must still hold its OWN verdict and fragment.
        last = [r for r in rows if r["html"] == last_html]
        assert len(last) == 1, "fixture precondition: the last slide is still present"
        assert _verdict(last[0]) == owned[last_html], (
            "the untouched last slide lost its verdict to the slide that was edited "
            f"two positions above it: expected {owned[last_html]}, got {_verdict(last[0])}"
        )
        assert _fragment(last[0]) == owned[last_html], (
            "the untouched last slide lost its spec fragment the same way: expected "
            f"{owned[last_html]}, got {_fragment(last[0])}"
        )

        # And the edited slide did not inherit someone else's verdict.
        edited = [r for r in rows if "TAG-EDITED" in (r["html"] or "")]
        assert len(edited) == 1
        assert _verdict(edited[0]) != owned[last_html], (
            "the edited slide is carrying the last slide's verdict"
        )


class TestNoPathStampsAPositionalId:
    """A structural guard over the layer that merges slides into an EXISTING deck.

    Seven sites in `chat_service.py` assigned `f"slide_{...}"` to a slide_id.  While
    `_reindex_slide_ids` renumbered everything, those stamps were merely vestigial.
    Once identity became durable they turned ACTIVELY HARMFUL: a stamped positional
    id can collide with a real slide's id, and the uniqueness pass resolves a
    collision in favour of the FIRST holder — so a newcomer stamped `slide_1` and
    inserted above the real `slide_1` keeps that identity, is handed its verdict and
    spec fragment by tier 1, and the real slide is re-minted with neither.  Measured.

    This is scoped to `chat_service.py` deliberately and carries no allowlist.
    `SlideDeck.from_html_string`/`from_dict` legitimately assign `slide_<idx>` when
    PARSING, where every slide is new and there is nothing to impersonate — and every
    chat_service path that merges parsed slides into an existing deck now overrides
    those ids, which is the property this guard keeps true.
    """

    def test_chat_service_never_assigns_a_positional_slide_id(self):
        import re
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "api"
            / "services"
            / "chat_service.py"
        )
        text = source.read_text()
        assert "def _reindex_slide_ids" in text, (
            "anchor drifted: this is no longer the module that owns slide ids"
        )

        offenders = [
            (n, line.strip())
            for n, line in enumerate(text.splitlines(), 1)
            if re.search(r'slide_id\s*=\s*f?["\']slide_\{', line)
        ]
        assert not offenders, (
            "chat_service.py assigns a POSITIONAL slide_id. A positional id can "
            "impersonate an existing slide and steal its verdict and spec fragment; "
            "new slides must be left without an id so _reindex_slide_ids mints one, "
            "and edits must preserve the id they already have.\n  "
            + "\n  ".join(f"line {n}: {line}" for n, line in offenders)
        )
