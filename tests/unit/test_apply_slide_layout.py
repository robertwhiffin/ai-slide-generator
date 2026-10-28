"""The general row-layout writer: ``SlideWriter.apply_slide_layout`` (Task 3).

An architect edit's operations (insert, update, delete, replace, move) become ONE
layout of the deck's rows.  ``layout[i]`` is the index, in position order, of the
current row that lands at new index ``i``, or ``None`` for a new pending
placeholder.  An index that does not appear is deleted.  The writer applies the
layout in one transaction.  It generalises ``insert_pending_slides``: an insert is
the layout with the old rows in order around the ``None`` entries.  So the oracle
is that suite's:

* An existing slide is found by the marker in its OWN HTML, and its whole row
  (every column except ``position`` and ``id``) must be what it was, the two JSON
  columns compared parsed.  Never by position, never by count.  A moved row keeps
  its ``modified_at``.
* A deleted slide is gone from the TABLE (queried by its slide_id), and nothing it
  owned (record, fragment, scripts, authorship) is stranded on another row.
* A refusal leaves the whole database as it was: every slide column, every deck
  column (``deck_spec_json`` and ``version`` included), every session's
  ``last_activity`` and the mutation events.

The seeds, the pending-placeholder literal and the readers are imported from
``test_insert_pending_slides``, so the two suites cannot drift apart.  New symbols
are read off the module when used (``slide_repository.X``,
``SlideWriter.apply_slide_layout``), so before the implementation each test is red
on its own missing symbol rather than the whole module failing to import.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import re
import typing
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.api.services.session_manager as session_manager
import src.api.services.slide_repository as slide_repository
import src.database.models  # noqa: F401 — register every ORM model
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import SlideWriter
from src.core.database import Base
from src.database.models.session import SessionSlide, UserSession
from src.services.shared_deck_attribution import (
    DeckMutationContext,
    MutationActor,
    MutationOperation,
)
from src.utils.slide_hash import compute_slide_hash
from tests.unit.test_insert_pending_slides import (
    _SLIDE_COLUMNS,
    CONTRIB_SID,
    OWNER_SID,
    PENDING_HASH,
    PENDING_HTML,
    PENDING_VERDICT,
    REQUESTER,
    _assert_every_old_row_intact,
    _assert_pending,
    _by_marker,
    _db_state,
    _deck,
    _events,
    _expected_rows,
    _fake_db,
    _fragment,
    _identity,
    _last_activity,
    _layout,
    _marker,
    _raw_json_columns,
    _real_row,
    _row_for,
    _rows,
    _seed,
    _seed_six,
    _spec_json,
)

#: Four rich rows: non-NULL scripts, authorship and timestamps (all distinct), a
#: two-hash verification record and a spec fragment, each carrying its marker.
FOUR = ("MK-ALPHA", "MK-BRAVO", "MK-CHARLIE", "MK-DELTA")

#: Four rows including the two shapes a careless rewrite flattens: a failed
#: placeholder with NULL authorship and a backfilled id-less row with NULL
#: timestamps (finding 9).  Both must stay NULL wherever they move.
SHAPES = ("MK-ALPHA", "MK-FAILED", "MK-BRAVO", "MK-BACKFILL")

#: Sixteen rich rows for the production shape (replace slide 5 with seven slides).
SIXTEEN = (
    "MK-ALPHA",
    "MK-BRAVO",
    "MK-CHARLIE",
    "MK-DELTA",
    "MK-ECHO",
    "MK-FOXTROT",
    "MK-GOLF",
    "MK-HOTEL",
    "MK-INDIA",
    "MK-JULIETT",
    "MK-KILO",
    "MK-LIMA",
    "MK-MIKE",
    "MK-NOVEMBER",
    "MK-OSCAR",
    "MK-PAPA",
)

MOVE = (0, 3, 1, 2)
DELETE = (0, 2, 3)
MIXED = (0, None, 3, None, 1)
#: Replace slide 5 (position 4) of 16 with seven slides: the first takes over row 4,
#: six new rows follow it, and old rows 5..15 land at 11..21.
REPLACE = (0, 1, 2, 3, 4) + (None,) * 6 + tuple(range(5, 16))

#: The raw columns ``_snapshot_row`` carries for a kept row (everything but the two
#: JSON columns, which travel as its SlideAttribution).
_SNAPSHOT_KEYS = (
    "html",
    "scripts",
    "slide_id",
    "created_by",
    "created_at",
    "modified_by",
    "modified_at",
)

_ALL_OPERATIONS: Tuple[str, ...] = typing.get_args(MutationOperation)


# ---------------------------------------------------------------------------
# Fixture (the same in-memory engine as test_insert_pending_slides)
# ---------------------------------------------------------------------------


@pytest.fixture()
def factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    # autoflush=False, as production (src/core/database.py): the layout must not
    # rely on an implicit flush.
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# Seeding, calling, reading
# ---------------------------------------------------------------------------


def _seed_rows(factory, markers: Sequence[str], **kw) -> Dict[str, Any]:
    return _seed(factory, {p: _row_for(m, p) for p, m in enumerate(markers)}, **kw)


def _mutation(
    operation: str,
    *,
    release_id: Optional[int],
    session_id: str = OWNER_SID,
    object_type: str = "deck",
) -> DeckMutationContext:
    return DeckMutationContext(
        actor=MutationActor(session_id, release_id),
        operation=operation,  # type: ignore[arg-type]
        object_type=object_type,  # type: ignore[arg-type]
    )


def _apply(
    factory,
    layout: Sequence[Optional[int]],
    *,
    deck_spec: str,
    expected_rows: Sequence[Tuple[Optional[str], str]],
    mutation: DeckMutationContext,
    session_id: str = OWNER_SID,
    created_by: Optional[str] = REQUESTER,
    calls: Optional[List[int]] = None,
) -> List[str]:
    """Run the writer with ONLY slide_repository's get_db_session patched.

    session_manager's is left alone on purpose: the layout is one transaction in
    one ``get_db_session()``, so it has no business opening another.
    """
    with patch("src.api.services.slide_repository.get_db_session", _fake_db(factory, calls)):
        return SlideWriter(SessionManager()).apply_slide_layout(
            session_id,
            layout,
            deck_spec=deck_spec,
            expected_rows=expected_rows,
            created_by=created_by,
            mutation=mutation,
        )


def _run(
    factory,
    markers: Sequence[str],
    layout: Sequence[Optional[int]],
    operation: str,
    *,
    session_id: str = OWNER_SID,
    calls: Optional[List[int]] = None,
    **seed_kw,
) -> Dict[str, Any]:
    """Seed ``markers``, snapshot, apply ``layout``; return everything a test reads."""
    seed = _seed_rows(factory, markers, **seed_kw)
    before = _rows(factory, seed["owner_pk"])
    spec = _spec_json(len(layout), title="Laid out")
    t0 = datetime.utcnow()
    ids = _apply(
        factory,
        tuple(layout),
        deck_spec=spec,
        expected_rows=_expected_rows(before),
        mutation=_mutation(operation, release_id=seed["release_id"], session_id=session_id),
        session_id=session_id,
        calls=calls,
    )
    t1 = datetime.utcnow()
    return {
        "seed": seed,
        "before": before,
        "spec": spec,
        "ids": ids,
        "t0": t0,
        "t1": t1,
        "after": _rows(factory, seed["owner_pk"]),
    }


def _state(factory) -> Dict[str, Any]:
    """The whole database a refused layout must leave alone.

    ``_db_state`` (every slide column, every deck column, the event count) plus
    the event rows themselves and every session's ``last_activity``.
    """
    state = _db_state(factory)
    state["event_rows"] = _events(factory)
    db = factory()
    try:
        state["sessions"] = sorted(
            (s.session_id, s.last_activity) for s in db.query(UserSession).all()
        )
    finally:
        db.close()
    return state


def _expected_layout(markers: Sequence[str], layout: Sequence[Optional[int]]) -> List[str]:
    return ["PENDING" if old is None else markers[old] for old in layout]


def _assert_kept_rows_whole(
    before: List[Dict[str, Any]], after: List[Dict[str, Any]], kept: Sequence[str]
) -> None:
    old, new = _by_marker(before), _by_marker(after)
    assert set(new) == set(kept), (
        f"the kept slides are not exactly {sorted(kept)}: after the layout {sorted(new)}"
    )
    for marker in kept:
        assert _identity(new[marker]) == _identity(old[marker]), (
            f"{marker} changed across the layout (every column but position/id must "
            f"follow the slide):\n before {_identity(old[marker])}\n after  "
            f"{_identity(new[marker])}"
        )


def _assert_gone(factory, deleted: Dict[str, Any]) -> None:
    """The deleted row is absent from the whole table, and nothing it owned is
    stranded on any other row (its marker appears in its HTML, slide_id, scripts,
    authorship, record and fragment)."""
    marker = _marker(deleted["html"])
    assert marker and deleted["slide_id"], "the deleted seed row must carry a marker and id"
    db = factory()
    try:
        by_id = db.query(SessionSlide).filter(SessionSlide.slide_id == deleted["slide_id"]).count()
        stranded = [
            (r.session_id, r.position, name)
            for r in db.query(SessionSlide).all()
            for name in _SLIDE_COLUMNS
            if marker.lower() in str(getattr(r, name) or "").lower()
        ]
    finally:
        db.close()
    assert by_id == 0, f"the deleted slide {deleted['slide_id']} is still in the table"
    assert stranded == [], f"{marker}'s data was stranded on other rows: {stranded}"


def _check_mixed_layout(factory, run: Dict[str, Any]) -> None:
    """MIXED on FOUR: [ALPHA, new, DELTA, new, BRAVO]; CHARLIE deleted.

    Shared with the Postgres twin, so it carries the deck-level checks too.
    """
    before, after, ids, seed = run["before"], run["after"], run["ids"], run["seed"]
    assert _layout(after) == ["MK-ALPHA", "PENDING", "MK-DELTA", "PENDING", "MK-BRAVO"], (
        f"the rows are not laid out as planned: {_layout(after)}"
    )
    assert [r["position"] for r in after] == list(range(5))

    _assert_kept_rows_whole(before, after, ["MK-ALPHA", "MK-DELTA", "MK-BRAVO"])
    _assert_gone(factory, before[2])

    for position in (1, 3):
        _assert_pending(after[position], run["t0"], run["t1"])
    assert ids == [after[1]["slide_id"], after[3]["slide_id"]], (
        f"the returned slide_ids are not the new rows' ids in new-index order: {ids}"
    )
    assert len(set(ids)) == 2, f"the two pending rows share a slide_id: {ids}"
    old_ids = {r["slide_id"] for r in before}
    assert not (set(ids) & old_ids), f"a pending row reused an existing slide's id: {ids}"

    deck = _deck(factory, seed["owner_pk"])
    assert deck.deck_spec_json == run["spec"]
    assert deck.version == 6
    assert _events(factory) == [
        ("save_deck_slides", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"])
    ], f"expected exactly one save_deck_slides/deck event: {_events(factory)}"


# ---------------------------------------------------------------------------
# Moves, deletes, the mixed layout and the production replace shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "markers",
    [
        pytest.param(FOUR, id="rich-rows"),
        pytest.param(SHAPES, id="null-author-and-null-timestamps"),
    ],
)
def test_moved_row_keeps_whole_row(factory, markers):
    run = _run(factory, markers, MOVE, "reorder_slides")
    before, after = run["before"], run["after"]

    assert _layout(after) == [markers[0], markers[3], markers[1], markers[2]], (
        f"the rows did not move to the planned layout: {_layout(after)}"
    )
    assert [r["position"] for r in after] == [0, 1, 2, 3]
    _assert_every_old_row_intact(before, after)

    old, new = _by_marker(before), _by_marker(after)
    for marker in markers:
        assert new[marker]["modified_at"] == old[marker]["modified_at"], (
            f"moving {marker} restamped modified_at: "
            f"{old[marker]['modified_at']!r} -> {new[marker]['modified_at']!r}"
        )
    if "MK-FAILED" in markers:
        assert (new["MK-FAILED"]["created_by"], new["MK-FAILED"]["modified_by"]) == (None, None)
        assert (new["MK-BACKFILL"]["created_at"], new["MK-BACKFILL"]["modified_at"]) == (None, None)
    assert run["ids"] == [], f"a pure move opened new slides: {run['ids']}"


def test_deleted_row_is_gone(factory):
    run = _run(factory, FOUR, DELETE, "delete_slide")
    before, after = run["before"], run["after"]

    assert _layout(after) == ["MK-ALPHA", "MK-CHARLIE", "MK-DELTA"]
    assert [r["position"] for r in after] == [0, 1, 2], (
        f"a row was left beyond the new count: {[r['position'] for r in after]}"
    )
    _assert_kept_rows_whole(before, after, ["MK-ALPHA", "MK-CHARLIE", "MK-DELTA"])
    _assert_gone(factory, before[1])
    db = factory()
    try:
        assert db.query(SessionSlide).count() == 3, "the table holds rows beyond the deck"
    finally:
        db.close()
    assert run["ids"] == []


def test_mixed_layout(factory):
    run = _run(factory, FOUR, MIXED, "save_deck_slides")
    _check_mixed_layout(factory, run)


def test_replace_shape(factory):
    """The production shape: replace slide 5 of a 16-slide deck with seven slides."""
    run = _run(factory, SIXTEEN, REPLACE, "insert_slide")
    before, after, ids = run["before"], run["after"], run["ids"]

    assert _layout(after) == list(SIXTEEN[:5]) + ["PENDING"] * 6 + list(SIXTEEN[5:]), (
        f"the rows are not laid out as the replace planned: {_layout(after)}"
    )
    assert [r["position"] for r in after] == list(range(22))
    _assert_every_old_row_intact(before, after)
    assert after[4]["slide_id"] == before[4]["slide_id"], (
        "the replaced slide's row must keep its identity until its builder rewrites it"
    )
    for position in range(5, 11):
        _assert_pending(after[position], run["t0"], run["t1"])
    assert ids == [after[p]["slide_id"] for p in range(5, 11)], (
        f"the returned ids are not the new rows' ids in new-index order: {ids}"
    )
    assert len(set(ids)) == 6
    assert not (set(ids) & {r["slide_id"] for r in before})
    assert _deck(factory, run["seed"]["owner_pk"]).deck_spec_json == run["spec"]


def test_identical_html_rows_keep_their_own_rows(factory):
    """Exact attribution, never the heuristic.  Two id-less rows with byte-identical
    HTML (found here by a tag in their scripts) are swapped.  The heuristic's
    content-hash pass would give each the other's record and fragment."""
    twin_html = '<div class="slide"><h1>Section break</h1></div>'
    twin_hash = compute_slide_hash(twin_html)

    def twin(tag: str, day: int) -> Dict[str, Any]:
        return {
            "html": twin_html,
            "slide_id": None,
            "scripts": f"/* {tag} */",
            "created_by": f"{tag.lower()}-author@test.com",
            "created_at": datetime(2024, 4, day, 9, 0, 0),
            "modified_by": f"{tag.lower()}-editor@test.com",
            "modified_at": datetime(2024, 4, day, 18, 0, 0),
            "verification_record": json.dumps(
                {
                    compute_slide_hash(f"<p>draft of {tag}</p>"): {"explanation": f"HISTORY-{tag}"},
                    twin_hash: {"score": 50 + day, "explanation": f"VERDICT-{tag}"},
                }
            ),
            "deck_spec_slide": _fragment(tag, day),
        }

    seed = _seed(
        factory,
        {0: twin("TWIN-ONE", 1), 1: twin("TWIN-TWO", 2), 2: _real_row("MK-ALPHA", 2, day=3)},
    )
    before = _rows(factory, seed["owner_pk"])
    ids = _apply(
        factory,
        (2, 1, 0),
        deck_spec=_spec_json(3, title="Laid out"),
        expected_rows=_expected_rows(before),
        mutation=_mutation("reorder_slides", release_id=seed["release_id"]),
    )
    after = _rows(factory, seed["owner_pk"])

    def tag(row: Dict[str, Any]) -> str:
        found = re.findall(r"TWIN-[A-Z]+", row["scripts"] or "")
        return found[0] if found else (_marker(row["html"]) or "?")

    assert [tag(r) for r in after] == ["MK-ALPHA", "TWIN-TWO", "TWIN-ONE"]
    old = {tag(r): r for r in before}
    for row in after:
        assert _identity(row) == _identity(old[tag(row)]), (
            f"{tag(row)} did not keep its own row (record/fragment mis-attributed):\n"
            f" before {_identity(old[tag(row)])}\n after  {_identity(row)}"
        )
    assert ids == []


@pytest.mark.parametrize(
    "layout, operation",
    [
        pytest.param(MIXED, "save_deck_slides", id="mixed"),
        pytest.param(DELETE, "delete_slide", id="delete"),
        pytest.param(MOVE, "reorder_slides", id="move"),
    ],
)
def test_the_layout_goes_through_the_canonical_writer_with_the_exact_map(
    factory, layout, operation
):
    """THE per-slide rewrite, called once, with the exact old-row map and no
    heuristic: now_dt=None, author_fallback=None, attribution={new: old row's},
    incoming={pending index: its pending record}, slides = the old rows' raw
    columns at their new indices."""
    seed = _seed_rows(factory, FOUR)
    before = _rows(factory, seed["owner_pk"])
    raw = _raw_json_columns(factory, seed["owner_pk"])

    real_rewrite = session_manager._rewrite_slide_rows
    real_attribute = session_manager._attribute_slide_records
    rewrites: List[Dict[str, Any]] = []
    heuristic_calls: List[int] = []

    def spy_rewrite(*args, **kwargs):
        rewrites.append(dict(inspect.signature(real_rewrite).bind(*args, **kwargs).arguments))
        return real_rewrite(*args, **kwargs)

    def spy_attribute(*args, **kwargs):
        heuristic_calls.append(1)
        return real_attribute(*args, **kwargs)

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(session_manager, "_rewrite_slide_rows", spy_rewrite))
        if hasattr(slide_repository, "_rewrite_slide_rows"):
            stack.enter_context(patch.object(slide_repository, "_rewrite_slide_rows", spy_rewrite))
        stack.enter_context(
            patch.object(session_manager, "_attribute_slide_records", spy_attribute)
        )
        _apply(
            factory,
            layout,
            deck_spec=_spec_json(len(layout), title="Laid out"),
            expected_rows=_expected_rows(before),
            mutation=_mutation(operation, release_id=seed["release_id"]),
        )

    assert len(rewrites) == 1, f"_rewrite_slide_rows called {len(rewrites)} times"
    call = rewrites[0]
    assert call["owner_id"] == seed["owner_pk"]
    assert call["now_dt"] is None
    assert call["author_fallback"] is None
    assert heuristic_calls == [], "the layout fell back to the attribution heuristic"

    expected_map = {
        new: (raw[old]["verification_record"], raw[old]["deck_spec_slide"])
        for new, old in enumerate(layout)
        if old is not None
    }
    got_map = {k: tuple(v) for k, v in (call["attribution"] or {}).items()}
    assert got_map == expected_map, f"not the exact old-row map: {got_map}"
    assert (call["incoming"] or {}) == {
        new: {PENDING_HASH: PENDING_VERDICT} for new, old in enumerate(layout) if old is None
    }
    slides = call["slides"]
    assert len(slides) == len(layout)
    for new, old in enumerate(layout):
        if old is None:
            assert slides[new]["html"] == PENDING_HTML
        else:
            assert {k: slides[new].get(k) for k in _SNAPSHOT_KEYS} == {
                k: before[old][k] for k in _SNAPSHOT_KEYS
            }, f"new index {new} does not carry old row {old}'s raw columns"


# ---------------------------------------------------------------------------
# Refusals: nothing is written on any raise
# ---------------------------------------------------------------------------


def _with_hash_changed(rows):
    out = _expected_rows(rows)
    out[2] = (out[2][0], compute_slide_hash("<p>someone edited this slide</p>"))
    return out


def _with_id_changed(rows):
    out = _expected_rows(rows)
    out[3] = ("sid-someone-else", out[3][1])
    return out


def _with_swap(rows):
    out = _expected_rows(rows)
    out[0], out[2] = out[2], out[0]
    return out


@pytest.mark.parametrize(
    "expected_rows_of, layout, operation",
    [
        # Each layout and operation are valid for the rows the caller planned
        # against (len(expected_rows)), so only the re-read can refuse them.
        pytest.param(_with_hash_changed, MIXED, "save_deck_slides", id="one-content-hash-differs"),
        pytest.param(_with_id_changed, MIXED, "save_deck_slides", id="one-slide-id-differs"),
        pytest.param(
            _with_swap, MIXED, "save_deck_slides", id="rows-were-reordered-since-planning"
        ),
        pytest.param(
            lambda rows: _expected_rows(rows)[:-1],
            (0, None, 2, None, 1),
            "save_deck_slides",
            id="a-row-was-added-since-planning",
        ),
        pytest.param(
            lambda rows: _expected_rows(rows) + [("sid-extra", compute_slide_hash("<p>x</p>"))],
            MIXED,
            "save_deck_slides",
            id="a-row-was-deleted-since-planning",
        ),
        pytest.param(
            lambda rows: [],
            (None, None),
            "insert_slide",
            id="expected-empty-while-rows-exist",
        ),
    ],
)
def test_expected_rows_mismatch_writes_nothing(factory, expected_rows_of, layout, operation):
    seed = _seed_rows(factory, FOUR)
    before = _rows(factory, seed["owner_pk"])
    state = _state(factory)

    with pytest.raises(slide_repository.SlideRowsChangedError):
        _apply(
            factory,
            layout,
            deck_spec=_spec_json(len(layout), title="Laid out"),
            expected_rows=expected_rows_of(before),
            mutation=_mutation(operation, release_id=seed["release_id"]),
        )
    assert _state(factory) == state, "a refused layout wrote something"


def test_a_session_with_no_deck_row_refuses_the_layout(factory):
    seed = _seed(factory, {}, with_deck=False)
    state = _state(factory)
    with pytest.raises(slide_repository.SlideRowsChangedError):
        _apply(
            factory,
            (None,),
            deck_spec=_spec_json(1, title="Laid out"),
            expected_rows=[],
            mutation=_mutation("insert_slide", release_id=seed["release_id"]),
        )
    assert _state(factory) == state
    assert _deck(factory, seed["owner_pk"]) is None


@pytest.mark.parametrize(
    "layout, operation, deck_spec",
    [
        # An int is a valid DeckSpec with that many slides; a str is passed as is.
        pytest.param(MIXED, "save_deck_slides", 4, id="fewer-spec-slides"),
        pytest.param(MIXED, "save_deck_slides", 6, id="more-spec-slides"),
        pytest.param(DELETE, "delete_slide", 4, id="delete-with-the-old-spec"),
        pytest.param(MOVE, "reorder_slides", 3, id="move-with-a-short-spec"),
        pytest.param((0, 1, 2, 3, None), "insert_slide", 4, id="insert-with-the-old-spec"),
        pytest.param(MIXED, "save_deck_slides", "{}", id="not-a-deck-spec"),
        pytest.param(MIXED, "save_deck_slides", "not json", id="not-json"),
    ],
)
def test_spec_count_mismatch_writes_nothing(factory, layout, operation, deck_spec):
    seed = _seed_rows(factory, FOUR)
    before = _rows(factory, seed["owner_pk"])
    state = _state(factory)

    with pytest.raises(ValueError):
        _apply(
            factory,
            layout,
            deck_spec=(
                _spec_json(deck_spec, title="Laid out") if isinstance(deck_spec, int) else deck_spec
            ),
            expected_rows=_expected_rows(before),
            mutation=_mutation(operation, release_id=seed["release_id"]),
        )
    assert _state(factory) == state, "a refused layout wrote something"


_LAYOUT_OPERATIONS = ("insert_slide", "delete_slide", "reorder_slides", "save_deck_slides")


@pytest.mark.parametrize("operation", _LAYOUT_OPERATIONS)
@pytest.mark.parametrize(
    "layout",
    [
        pytest.param((0, 1, 1, 2), id="duplicate-old-index"),
        pytest.param((0, None, 2, 2, 3), id="duplicate-old-index-beside-a-new-slide"),
        pytest.param((0, 1, 2, 4), id="index-past-the-last-row"),
        pytest.param((0, 1, 2, -1), id="negative-index"),
        pytest.param((0, 1, 2, 3), id="identity"),
    ],
)
def test_malformed_layouts(factory, layout, operation):
    """Refused under EVERY layout operation, so no operation name lets it through."""
    seed = _seed_rows(factory, FOUR)
    before = _rows(factory, seed["owner_pk"])
    state = _state(factory)

    with pytest.raises(ValueError):
        _apply(
            factory,
            layout,
            deck_spec=_spec_json(len(layout), title="Laid out"),
            expected_rows=_expected_rows(before),
            mutation=_mutation(operation, release_id=seed["release_id"]),
        )
    assert _state(factory) == state, "a malformed layout wrote something"


_CLASSIFIED = (
    ("insert", (0, None, 1, 2, 3), "insert_slide"),
    ("delete", DELETE, "delete_slide"),
    ("reorder", MOVE, "reorder_slides"),
    ("mixed", MIXED, "save_deck_slides"),
)


@pytest.mark.parametrize(
    "layout, operation, object_type",
    [
        pytest.param(layout, wrong, "deck", id=f"{name}-as-{wrong}")
        for name, layout, right in _CLASSIFIED
        for wrong in _ALL_OPERATIONS
        if wrong != right
    ]
    + [
        pytest.param(layout, right, "slide", id=f"{name}-on-object-type-slide")
        for name, layout, right in _CLASSIFIED
    ],
)
def test_wrong_mutation_operation_refused(factory, layout, operation, object_type):
    seed = _seed_rows(factory, FOUR)
    before = _rows(factory, seed["owner_pk"])
    state = _state(factory)

    with pytest.raises(ValueError):
        _apply(
            factory,
            layout,
            deck_spec=_spec_json(len(layout), title="Laid out"),
            expected_rows=_expected_rows(before),
            mutation=_mutation(operation, release_id=seed["release_id"], object_type=object_type),
        )
    assert _state(factory) == state, "a mis-labelled layout wrote something"


def test_a_refused_evidence_write_rolls_back_the_whole_layout(factory):
    """One transaction: when the evidence row is refused (an actor pin that is not
    the session's persisted pin), the moves, the delete, the new rows, the spec and
    the version all roll back with it."""
    seed = _seed_rows(factory, FOUR)
    before = _rows(factory, seed["owner_pk"])
    state = _state(factory)
    with pytest.raises(ValueError, match="persisted pin"):
        _apply(
            factory,
            MIXED,
            deck_spec=_spec_json(5, title="Laid out"),
            expected_rows=_expected_rows(before),
            mutation=_mutation("save_deck_slides", release_id=seed["release_id"] + 1000),
        )
    assert _state(factory) == state, "part of a failed layout was committed"


# ---------------------------------------------------------------------------
# Deck-level writes: one event, one version bump, the spec, one transaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "markers, layout, operation, session_id",
    [
        pytest.param(FOUR, (0, None, 1, 2, 3), "insert_slide", OWNER_SID, id="insert"),
        pytest.param(FOUR, DELETE, "delete_slide", OWNER_SID, id="delete"),
        pytest.param(FOUR, MOVE, "reorder_slides", OWNER_SID, id="reorder"),
        pytest.param(FOUR, MIXED, "save_deck_slides", OWNER_SID, id="mixed"),
        pytest.param(SIXTEEN, REPLACE, "insert_slide", OWNER_SID, id="replace"),
        pytest.param(FOUR, MIXED, "save_deck_slides", CONTRIB_SID, id="mixed-by-a-contributor"),
    ],
)
def test_one_mutation_event_and_version_bump(factory, markers, layout, operation, session_id):
    seed = _seed_rows(factory, markers, with_contributor=True)
    db = factory()
    try:
        db.query(UserSession).update(
            {UserSession.last_activity: datetime(2024, 1, 1, 0, 0, 0)},
            synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()
    before = _rows(factory, seed["owner_pk"])
    (deck_before,) = _db_state(factory)["decks"]
    spec = _spec_json(len(layout), title="Laid out")
    calls: List[int] = []

    t0 = datetime.utcnow()
    _apply(
        factory,
        layout,
        deck_spec=spec,
        expected_rows=_expected_rows(before),
        mutation=_mutation(operation, release_id=seed["release_id"], session_id=session_id),
        session_id=session_id,
        calls=calls,
    )
    t1 = datetime.utcnow()

    actor_pk = seed["owner_pk"] if session_id == OWNER_SID else seed["contrib_pk"]
    assert _events(factory) == [
        (operation, "deck", actor_pk, seed["owner_pk"], seed["release_id"])
    ], f"expected exactly one {operation}/deck event: {_events(factory)}"
    (deck_after,) = _db_state(factory)["decks"]
    assert deck_after["version"] == deck_before["version"] + 1, (
        f"version not bumped exactly once: {deck_before['version']} -> {deck_after['version']}"
    )
    assert deck_after["deck_spec_json"] == spec, "the passed spec was not written"
    untouched = ("deck_spec_json", "version", "updated_at")
    assert {k: v for k, v in deck_after.items() if k not in untouched} == {
        k: v for k, v in deck_before.items() if k not in untouched
    }, "the layout wrote deck columns other than deck_spec_json/version (slide_count has "
    "one writer, the post-commit deck-level write)"
    assert len(calls) == 1, f"the layout opened {len(calls)} db sessions, not one transaction"

    activity = _last_activity(factory)
    for sid in {OWNER_SID, session_id}:
        assert t0 <= activity[sid] <= t1, f"the layout did not touch {sid}'s last_activity"
    assert _rows(factory, seed["contrib_pk"]) == [], "rows landed on the contributor session"
    assert _deck(factory, seed["contrib_pk"]) is None


# ---------------------------------------------------------------------------
# A row-less (spec-only) deck
# ---------------------------------------------------------------------------


def test_a_row_less_deck_writes_the_spec_version_and_one_event_only(factory):
    seed = _seed(factory, {}, prior_spec_slides=3, version=3)
    spec = _spec_json(4, title="Laid out")
    ids = _apply(
        factory,
        (None, None, None, None),
        deck_spec=spec,
        expected_rows=[],
        mutation=_mutation("insert_slide", release_id=seed["release_id"]),
    )
    assert ids == []
    assert _rows(factory, seed["owner_pk"]) == [], "a row-less deck gained rows"
    deck = _deck(factory, seed["owner_pk"])
    assert deck.deck_spec_json == spec
    assert deck.version == 4
    assert _events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"])
    ]


@pytest.mark.parametrize("operation", _LAYOUT_OPERATIONS)
def test_a_row_less_deck_refuses_a_layout_naming_a_row(factory, operation):
    seed = _seed(factory, {}, prior_spec_slides=3, version=3)
    state = _state(factory)
    with pytest.raises(ValueError):
        _apply(
            factory,
            (0, None, None, None),
            deck_spec=_spec_json(4, title="Laid out"),
            expected_rows=[],
            mutation=_mutation(operation, release_id=seed["release_id"]),
        )
    assert _state(factory) == state


# ---------------------------------------------------------------------------
# insert_pending_slides is the in-order special case, through the same writer
# ---------------------------------------------------------------------------


def test_insert_pending_slides_unchanged(factory):
    """It delegates to apply_slide_layout with the in-order layout, passes its
    arguments and result through, and behaves exactly as before.
    (test_insert_pending_slides.py itself must stay green, untouched.)"""
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    spec = _spec_json(8, title="Shifted")
    mutation = _mutation("insert_slide", release_id=seed["release_id"])

    real = SlideWriter.apply_slide_layout
    calls: List[Dict[str, Any]] = []
    results: List[Any] = []

    def spy(self, *args, **kwargs):
        calls.append(dict(inspect.signature(real).bind(self, *args, **kwargs).arguments))
        result = real(self, *args, **kwargs)
        results.append(result)
        return result

    t0 = datetime.utcnow()
    with (
        patch.object(SlideWriter, "apply_slide_layout", spy),
        patch("src.api.services.slide_repository.get_db_session", _fake_db(factory)),
    ):
        ids = SlideWriter(SessionManager()).insert_pending_slides(
            OWNER_SID,
            [1, 3],
            deck_spec=spec,
            expected_rows=_expected_rows(before),
            created_by=REQUESTER,
            mutation=mutation,
        )
    t1 = datetime.utcnow()

    assert len(calls) == 1, f"insert_pending_slides called apply_slide_layout {len(calls)} times"
    call = calls[0]
    assert call["session_id"] == OWNER_SID
    assert list(call["layout"]) == [0, None, 1, None, 2, 3, 4, 5], (
        f"not the in-order layout for insert_at [1, 3] on six rows: {list(call['layout'])}"
    )
    assert call["deck_spec"] == spec
    assert [tuple(r) for r in call["expected_rows"]] == _expected_rows(before)
    assert call["created_by"] == REQUESTER
    assert call["mutation"] == mutation
    assert ids == results[0]

    after = _rows(factory, seed["owner_pk"])
    assert _layout(after) == [
        "MK-ALPHA",
        "PENDING",
        "MK-FAILED",
        "PENDING",
        "MK-BRAVO",
        "MK-BACKFILL",
        "MK-CHARLIE",
        "MK-DELTA",
    ]
    _assert_every_old_row_intact(before, after)
    for position in (1, 3):
        _assert_pending(after[position], t0, t1)
    assert ids == [after[1]["slide_id"], after[3]["slide_id"]]
    assert _deck(factory, seed["owner_pk"]).version == 6
    assert _events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"])
    ]


# ---------------------------------------------------------------------------
# layout_mutation_operation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "layout, old_count, expected",
    [
        # insert: every old index present, in order, and at least one None
        pytest.param((0, None, 1, 2), 3, "insert_slide", id="insert-in-the-middle"),
        pytest.param((None, 0, 1), 2, "insert_slide", id="insert-at-the-start"),
        pytest.param((0, 1, None), 2, "insert_slide", id="append"),
        pytest.param(REPLACE, 16, "insert_slide", id="the-production-replace-shape"),
        pytest.param((None, None, None), 0, "insert_slide", id="row-less-deck"),
        # delete: no None, kept indices ascending, some missing
        pytest.param(DELETE, 4, "delete_slide", id="delete-one"),
        pytest.param((1, 2, 3), 4, "delete_slide", id="delete-the-first"),
        pytest.param((0, 1, 2), 4, "delete_slide", id="delete-the-last"),
        pytest.param((3,), 4, "delete_slide", id="delete-three"),
        # reorder: no None, all present, not in order
        pytest.param(MOVE, 4, "reorder_slides", id="move-one"),
        pytest.param((1, 0), 2, "reorder_slides", id="swap"),
        pytest.param((3, 2, 1, 0), 4, "reorder_slides", id="reverse"),
        # anything else is a mixed layout
        pytest.param(MIXED, 4, "save_deck_slides", id="move-delete-insert"),
        pytest.param((None, 1), 2, "save_deck_slides", id="delete-and-insert"),
        pytest.param((1, 0, None), 2, "save_deck_slides", id="move-and-insert"),
        pytest.param((2, 0), 3, "save_deck_slides", id="delete-and-move"),
        # the identity has nothing to write
        pytest.param((0, 1, 2, 3), 4, ValueError, id="identity-of-four"),
        pytest.param((0,), 1, ValueError, id="identity-of-one"),
    ],
)
def test_layout_mutation_operation(layout, old_count, expected):
    classify = slide_repository.layout_mutation_operation
    for form in (tuple(layout), list(layout)):
        if expected is ValueError:
            with pytest.raises(ValueError):
                classify(form, old_count)
        else:
            assert classify(form, old_count) == expected, (
                f"{form!r} on {old_count} rows classified as {classify(form, old_count)!r}"
            )
