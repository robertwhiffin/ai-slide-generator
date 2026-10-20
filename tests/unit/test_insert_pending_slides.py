"""The graph's slide shift: ``SlideWriter.insert_pending_slides`` (#314, Task 2).

An "add a slide" turn on the agent path inserts NEW positions into a deck that
already has rows.  At architect commit the rows shift, atomically with the spec, and
a pending placeholder opens at each inserted index (plan D4).  The shift is the place
where a slide's identity, authorship, timestamps, verification record and spec
fragment can silently end up on a different slide, which is what four hand-copied
row writers once did (executing-plans-tellr §7).  So:

* Every assertion about an existing slide reads the WHOLE row (every column except
  ``position`` and ``id``) and finds the row by the marker in its own HTML.  Never by
  position, never by count, never by hand-picked keys.  "There are eight rows" and
  "row 2 has a verdict" are both true of a mis-attributed deck.
* The seed includes the two row shapes a careless rewrite flattens: a failed
  placeholder with a NULL author (``commit_placeholder``'s shape) and a backfilled
  row with NULL timestamps.  Both must stay NULL (finding 9).
* Seeds use non-NULL ``scripts`` and default ``json.dumps`` encoding, and the two
  JSON columns are compared parsed (PLAN-CORRECTIONS C6).  That is canonical-writer
  behaviour, not a defect.

Also here: the one per-slide rewrite ``_rewrite_slide_rows`` (``save_slide_deck`` and
``restore_version`` keep ``now_dt``, C3), ``placeholder_slide`` (byte-identical to
``commit_placeholder``), and the strict ``is_placeholder_verdict`` (C4).

New symbols are read off the module at use (``slide_repository.X``), so before the
implementation each test is red on its own missing symbol rather than the whole
module failing to import.
"""
from __future__ import annotations

import contextlib
import inspect
import json
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.api.services.session_manager as session_manager
import src.api.services.slide_repository as slide_repository
import src.database.models  # noqa: F401 — register every ORM model
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.api.services.slide_repository import SlideWriter
from src.core.database import Base
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.domain.deck_spec import DeckSpec
from src.domain.finding import VERDICT_KEY, Finding, make_finding_id
from src.services.shared_deck_attribution import DeckMutationContext, MutationActor
from src.utils.slide_hash import compute_slide_hash

OWNER_SID = "insert-pending-owner"
CONTRIB_SID = "insert-pending-contributor"
#: The ``created_by`` argument: the user whose turn opened the pending rows.
REQUESTER = "turn-author@test.com"

#: The literal pending placeholder (plan Task 2 interface: placeholder_slide(
#: PENDING_SLIDE_MESSAGE, text=PENDING_SLIDE_TEXT)).  Written out, not computed, so
#: the oracle does not depend on the code under test.
PENDING_MESSAGE = "Inserted slide not yet built"
PENDING_HTML = (
    f'<div class="slide-placeholder-error" data-error="{PENDING_MESSAGE}">'
    "<p>New slide — not built yet.</p>"
    "</div>"
)
PENDING_HASH = compute_slide_hash(PENDING_HTML)
PENDING_VERDICT = {"error": True, "message": PENDING_MESSAGE}

_MARKER_RE = re.compile(r"MK-[A-Z]+")

#: The seeded deck, in position order, for the main [1, 3] shift.  Every shape the
#: shift must carry intact: real slides, a failed placeholder with NULL authorship
#: (``commit_placeholder`` writes no author), and a backfilled id-less row with NULL
#: timestamps.  Inserting at new indices 1 and 3 moves every row except ALPHA.
SIX = ("MK-ALPHA", "MK-FAILED", "MK-BRAVO", "MK-BACKFILL", "MK-CHARLIE", "MK-DELTA")


# ---------------------------------------------------------------------------
# Fixtures (self-contained, in the style of test_insert_shifts_records_and_specs)
# ---------------------------------------------------------------------------


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    # autoflush=False, as production (src/core/database.py): the shift must not
    # rely on an implicit flush.
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _fake_db(factory, calls: Optional[List[int]] = None):
    @contextlib.contextmanager
    def _cm():
        if calls is not None:
            calls.append(1)
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _cm


# ---------------------------------------------------------------------------
# Seed rows
# ---------------------------------------------------------------------------


def _real_html(marker: str) -> str:
    return f'<div class="slide"><h1>{marker}</h1><p>its own body text</p></div>'


def _failed_html(marker: str) -> str:
    """commit_placeholder's HTML, byte for byte, with the marker in data-error."""
    return (
        f'<div class="slide-placeholder-error" data-error="{marker} build crashed">'
        "<p>Slide generation failed.</p>"
        "</div>"
    )


def _fragment(marker: str, position: int) -> str:
    return json.dumps(
        {
            "position": position,
            "purpose": f"FRAGMENT-{marker}",
            "content_brief": f"brief for {marker}",
            "assumes": "",
            "hands_off": "",
            "data_references": [],
        }
    )


def _two_hash_record(marker: str, html: str, position: int) -> str:
    """History + current verdicts, the current one shared with a tellr_review finding."""
    current = compute_slide_hash(html)
    history = compute_slide_hash(f"<p>an earlier draft of {marker}</p>")
    finding = Finding(
        id=make_finding_id("overflow", current, 0),
        slide_index=position,
        category="design",
        criterion="overflow",
        message=f"FINDING-{marker}",
        objective=True,
    )
    return json.dumps(
        {
            history: {"score": 41, "rating": "poor", "explanation": f"HISTORY-{marker}"},
            current: {
                "score": 92,
                "rating": "good",
                "explanation": f"CURRENT-{marker}",
                VERDICT_KEY: {"verdict": "surfaced", "findings": [finding.model_dump()]},
            },
        }
    )


def _real_row(marker: str, position: int, day: int) -> Dict[str, Any]:
    html = _real_html(marker)
    return {
        "html": html,
        "slide_id": f"sid-{marker}-{uuid.uuid4().hex[:8]}",
        "scripts": f"console.log('{marker}');",
        "created_by": f"{marker.lower()}-author@test.com",
        "created_at": datetime(2024, 1, day, 9, 0, 0),
        "modified_by": f"{marker.lower()}-editor@test.com",
        "modified_at": datetime(2024, 2, day, 17, 30, 0),
        "verification_record": _two_hash_record(marker, html, position),
        "deck_spec_slide": _fragment(marker, position),
    }


def _failed_placeholder_row(marker: str, position: int) -> Dict[str, Any]:
    """commit_placeholder's shape: NULL author, empty scripts, an error verdict."""
    html = _failed_html(marker)
    history = compute_slide_hash(f"<p>an earlier draft of {marker}</p>")
    return {
        "html": html,
        "slide_id": str(uuid.uuid4()),
        "scripts": "",
        "created_by": None,
        "created_at": datetime(2024, 3, 1, 8, 0, 0),
        "modified_by": None,
        "modified_at": datetime(2024, 3, 1, 8, 0, 0),
        "verification_record": json.dumps(
            {
                history: {"score": 30, "rating": "poor", "explanation": f"HISTORY-{marker}"},
                compute_slide_hash(html): {"error": True, "message": f"{marker} build crashed"},
            }
        ),
        "deck_spec_slide": _fragment(marker, position),
    }


def _backfilled_row(marker: str, position: int) -> Dict[str, Any]:
    """The startup backfill's shape: no slide_id and NULL timestamps."""
    html = _real_html(marker)
    return {
        "html": html,
        "slide_id": None,
        "scripts": f"/* legacy {marker} */",
        "created_by": "legacy-author@test.com",
        "created_at": None,
        "modified_by": "legacy-author@test.com",
        "modified_at": None,
        "verification_record": _two_hash_record(marker, html, position),
        "deck_spec_slide": _fragment(marker, position),
    }


def _row_for(marker: str, position: int) -> Dict[str, Any]:
    if marker == "MK-FAILED":
        return _failed_placeholder_row(marker, position)
    if marker == "MK-BACKFILL":
        return _backfilled_row(marker, position)
    return _real_row(marker, position, day=position + 1)


def _spec_json(n: int, *, title: str) -> str:
    """A valid DeckSpec with ``n`` slides at positions 0..n-1."""
    return DeckSpec(
        title=title,
        audience="aud",
        purpose="pur",
        argument="arg",
        call_to_action="cta",
        narrative_arc=["open", "close"],
        design_contract={},
        resolved_data={"synthesis": "syn", "figures": [], "gaps": []},
        slides=[
            {
                "position": p,
                "purpose": f"{title}-purpose-{p}",
                "content_brief": f"{title}-brief-{p}",
                "assumes": "",
                "hands_off": "",
                "data_references": [],
            }
            for p in range(n)
        ],
    ).to_json()


def _seed(
    factory,
    rows: Dict[int, Dict[str, Any]],
    *,
    with_deck: bool = True,
    prior_spec_slides: Optional[int] = None,
    version: int = 5,
    with_contributor: bool = False,
) -> Dict[str, Any]:
    """Owner session (pinned to a real GraphRelease) + deck + the given rows.

    ``rows`` maps position -> column values, so gapped positions can be seeded.
    Returns the pks and the pin the mutation context must carry.
    """
    db = factory()
    try:
        release = GraphRelease(
            version_number=1,
            release_note="insert-pending fixture",
            published_by="test",
            published_at=datetime(2026, 9, 1, 9, 0, 0),
            effective_from=datetime(2026, 9, 1, 9, 0, 0),
            effective_to=None,
        )
        db.add(release)
        db.flush()
        owner = UserSession(
            session_id=OWNER_SID,
            created_by="owner@test.com",
            graph_release_id=release.id,
        )
        db.add(owner)
        db.flush()
        contrib_pk = None
        if with_contributor:
            contrib = UserSession(
                session_id=CONTRIB_SID,
                created_by="contributor@test.com",
                parent_session_id=owner.id,
                graph_release_id=release.id,
            )
            db.add(contrib)
            db.flush()
            contrib_pk = contrib.id
        if with_deck:
            n = len(rows) if prior_spec_slides is None else prior_spec_slides
            db.add(
                SessionSlideDeck(
                    session_id=owner.id,
                    title="Seeded deck",
                    html_content="<html>knitted</html>",
                    scripts_content="",
                    slide_count=len(rows),
                    deck_spec_json=_spec_json(n, title="Prior"),
                    version=version,
                )
            )
            db.flush()
        for position, values in rows.items():
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    **values,
                )
            )
        db.commit()
        return {"owner_pk": owner.id, "contrib_pk": contrib_pk, "release_id": release.id}
    finally:
        db.close()


def _seed_six(factory, **kw) -> Dict[str, Any]:
    return _seed(factory, {p: _row_for(m, p) for p, m in enumerate(SIX)}, **kw)


# ---------------------------------------------------------------------------
# Reading the database back
# ---------------------------------------------------------------------------

_SLIDE_COLUMNS = [c.name for c in SessionSlide.__table__.columns]
_JSON_COLUMNS = ("verification_record", "deck_spec_slide")


def _decoded(row: SessionSlide) -> Dict[str, Any]:
    """EVERY column of the row; the two JSON columns parsed (C6)."""
    out = {name: getattr(row, name) for name in _SLIDE_COLUMNS}
    for name in _JSON_COLUMNS:
        out[name] = json.loads(out[name]) if out[name] is not None else None
    return out


def _rows(factory, owner_pk: int) -> List[Dict[str, Any]]:
    db = factory()
    try:
        return [
            _decoded(r)
            for r in db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner_pk)
            .order_by(SessionSlide.position)
            .all()
        ]
    finally:
        db.close()


def _marker(html: str) -> Optional[str]:
    found = _MARKER_RE.findall(html or "")
    assert len(found) <= 1, f"a row's HTML carries more than one marker: {found}"
    return found[0] if found else None


def _by_marker(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        marker = _marker(row["html"])
        if marker is None:
            continue
        assert marker not in out, f"two rows carry {marker}: the shift duplicated a slide"
        out[marker] = row
    return out


def _identity(row: Dict[str, Any]) -> Dict[str, Any]:
    """The whole row minus the two columns a shift legitimately changes."""
    return {k: v for k, v in row.items() if k not in ("position", "id")}


def _layout(rows: List[Dict[str, Any]]) -> List[str]:
    """Position-ordered markers; a row without one shows as PENDING."""
    return [_marker(r["html"]) or "PENDING" for r in rows]


def _db_state(factory) -> Dict[str, Any]:
    """Byte-level snapshot of everything a refused shift must leave alone."""
    db = factory()
    try:
        slides = [
            {name: getattr(r, name) for name in _SLIDE_COLUMNS}
            for r in db.query(SessionSlide)
            .order_by(SessionSlide.session_id, SessionSlide.position)
            .all()
        ]
        decks = [
            {c.name: getattr(d, c.name) for c in SessionSlideDeck.__table__.columns}
            for d in db.query(SessionSlideDeck).order_by(SessionSlideDeck.id).all()
        ]
        events = db.query(SharedDeckMutationEvent).count()
        return {"slides": slides, "decks": decks, "events": events}
    finally:
        db.close()


def _deck(factory, owner_pk: int) -> Optional[SessionSlideDeck]:
    db = factory()
    try:
        deck = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner_pk)
            .one_or_none()
        )
        if deck is not None:
            db.expunge(deck)
        return deck
    finally:
        db.close()


def _events(factory) -> List[Tuple[Any, ...]]:
    db = factory()
    try:
        return [
            (e.operation, e.object_type, e.actor_session_id, e.root_session_id, e.graph_release_id)
            for e in db.query(SharedDeckMutationEvent).order_by(SharedDeckMutationEvent.id).all()
        ]
    finally:
        db.close()


def _expected_rows(rows: List[Dict[str, Any]]) -> List[Tuple[Optional[str], str]]:
    return [(r["slide_id"], compute_slide_hash(r["html"])) for r in rows]


# ---------------------------------------------------------------------------
# Calling the shift
# ---------------------------------------------------------------------------


def _mutation(session_id: str, release_id: Optional[int]) -> DeckMutationContext:
    return DeckMutationContext(
        actor=MutationActor(session_id, release_id),
        operation="insert_slide",
        object_type="deck",
    )


def _insert(
    factory,
    insert_at: Sequence[int],
    *,
    deck_spec: str,
    expected_rows: Sequence[Tuple[Optional[str], str]],
    release_id: Optional[int],
    session_id: str = OWNER_SID,
    created_by: Optional[str] = REQUESTER,
    mutation: Optional[DeckMutationContext] = None,
    calls: Optional[List[int]] = None,
) -> List[str]:
    """Run the shift with ONLY slide_repository's get_db_session patched.

    session_manager's is left alone on purpose: the shift is one transaction in
    one ``get_db_session()``, so it has no business opening another.
    """
    with patch(
        "src.api.services.slide_repository.get_db_session", _fake_db(factory, calls)
    ):
        return SlideWriter(SessionManager()).insert_pending_slides(
            session_id,
            insert_at,
            deck_spec=deck_spec,
            expected_rows=expected_rows,
            created_by=created_by,
            mutation=mutation or _mutation(session_id, release_id),
        )


def _shift_six(factory, insert_at=(1, 3), **kw):
    """Seed SIX, snapshot, shift; return (seed, before, ids, t0, t1, new_spec)."""
    seed = _seed_six(factory, **kw)
    before = _rows(factory, seed["owner_pk"])
    new_spec = _spec_json(len(before) + len(insert_at), title="Shifted")
    t0 = datetime.utcnow()
    ids = _insert(
        factory,
        list(insert_at),
        deck_spec=new_spec,
        expected_rows=_expected_rows(before),
        release_id=seed["release_id"],
    )
    t1 = datetime.utcnow()
    return seed, before, ids, t0, t1, new_spec


def _assert_every_old_row_intact(before, after) -> None:
    old, new = _by_marker(before), _by_marker(after)
    assert set(new) == set(old), (
        f"a slide was lost or invented by the shift: before {sorted(old)}, after {sorted(new)}"
    )
    for marker, snapshot in old.items():
        assert _identity(new[marker]) == _identity(snapshot), (
            f"{marker} changed across the shift (every column but position/id must "
            f"follow the slide):\n before {_identity(snapshot)}\n after  {_identity(new[marker])}"
        )


def _assert_pending(row: Dict[str, Any], t0: datetime, t1: datetime) -> None:
    assert row["html"] == PENDING_HTML, f"not the pending placeholder: {row['html']!r}"
    assert row["verification_record"] == {PENDING_HASH: PENDING_VERDICT}, (
        f"a pending row must carry exactly its own pending verdict: {row['verification_record']}"
    )
    assert slide_repository.is_placeholder_verdict(
        row["verification_record"][compute_slide_hash(row["html"])]
    )
    assert row["deck_spec_slide"] is None, (
        f"a pending row inherited a spec fragment: {row['deck_spec_slide']}"
    )
    assert row["scripts"] == ""
    assert row["slide_id"], "a pending row has no slide_id"
    assert row["created_by"] == REQUESTER and row["modified_by"] == REQUESTER, (
        "pending authorship must be the turn's author: "
        f"{row['created_by']!r}/{row['modified_by']!r}"
    )
    for col in ("created_at", "modified_at"):
        assert row[col] is not None and t0 <= row[col] <= t1, (
            f"pending {col} must be stamped explicitly at the shift: {row[col]!r}"
        )


# ---------------------------------------------------------------------------
# placeholder_slide and the copy it carries
# ---------------------------------------------------------------------------

FAILED_LITERAL = (
    '<div class="slide-placeholder-error" data-error="">'
    "<p>Slide generation failed.</p>"
    "</div>"
)


def test_placeholder_copy_is_the_planned_text():
    assert slide_repository.FAILED_SLIDE_TEXT == "Slide generation failed."
    assert slide_repository.PENDING_SLIDE_TEXT == "New slide — not built yet."
    assert slide_repository.PENDING_SLIDE_MESSAGE == PENDING_MESSAGE


def test_placeholder_slide_defaults_are_commit_placeholders_html():
    html, record = slide_repository.placeholder_slide()
    assert html == FAILED_LITERAL
    assert record == {compute_slide_hash(FAILED_LITERAL): {"error": True, "message": ""}}

    html, record = slide_repository.placeholder_slide("timeout")
    literal = FAILED_LITERAL.replace('data-error=""', 'data-error="timeout"')
    assert html == literal
    assert record == {compute_slide_hash(literal): {"error": True, "message": "timeout"}}


def test_placeholder_slide_pending_is_the_pending_literal():
    html, record = slide_repository.placeholder_slide(
        slide_repository.PENDING_SLIDE_MESSAGE, text=slide_repository.PENDING_SLIDE_TEXT
    )
    assert html == PENDING_HTML
    assert record == {PENDING_HASH: PENDING_VERDICT}


def test_commit_placeholder_still_writes_the_same_bytes(factory):
    """Green before and after: commit_placeholder moves onto placeholder_slide()
    without changing one byte of what it writes."""
    seed = _seed(factory, {})
    with patch("src.api.services.slide_repository.get_db_session", _fake_db(factory)):
        SlideWriter(SessionManager()).commit_placeholder(OWNER_SID, 0, "timeout")
    (row,) = _rows(factory, seed["owner_pk"])
    literal = FAILED_LITERAL.replace('data-error=""', 'data-error="timeout"')
    assert row["html"] == literal
    assert row["scripts"] == ""
    assert row["verification_record"] == {
        compute_slide_hash(literal): {"error": True, "message": "timeout"}
    }


# ---------------------------------------------------------------------------
# is_placeholder_verdict: the strict, current-verdict predicate (D9, C4)
# ---------------------------------------------------------------------------

#: The judge's real error payload (src/api/routes/verification.py, the
#: verification_result dict; values from llm_judge's except branch).
JUDGE_ERROR_VERDICT = {
    "score": 0,
    "rating": "error",
    "explanation": "Evaluation failed: upstream timeout",
    "issues": [{"type": "error", "detail": "upstream timeout"}],
    "duration_ms": 1234,
    "trace_id": None,
    "genie_conversation_id": "conv-1",
    "error": True,
    "error_message": "upstream timeout",
}


@pytest.mark.parametrize(
    "verdict, expected",
    [
        pytest.param(PENDING_VERDICT, True, id="pending-verdict"),
        pytest.param({"error": True, "message": "build crashed"}, True, id="failed-verdict"),
        pytest.param({"error": True, "message": ""}, True, id="failed-verdict-no-message"),
        pytest.param({"error": True}, True, id="bare-error-flag"),
        pytest.param(JUDGE_ERROR_VERDICT, False, id="judge-error-verdict"),
        pytest.param(
            {"error": True, "message": "x", VERDICT_KEY: {"verdict": "clean", "findings": []}},
            False,
            id="slot-also-holding-tellr_review",
        ),
        pytest.param(None, False, id="none"),
        pytest.param({"message": "no flag"}, False, id="message-without-flag"),
        pytest.param({"error": False, "message": ""}, False, id="error-false"),
        pytest.param({"error": "true", "message": ""}, False, id="error-not-literally-true"),
        pytest.param(
            {PENDING_HASH: PENDING_VERDICT}, False, id="a-whole-record-is-not-a-verdict"
        ),
        pytest.param("error", False, id="not-a-dict"),
    ],
)
def test_is_placeholder_verdict(verdict, expected):
    assert slide_repository.is_placeholder_verdict(verdict) is expected


# ---------------------------------------------------------------------------
# The [1, 3] shift
# ---------------------------------------------------------------------------


def test_insert_at_1_and_3_keeps_every_old_row_by_marker(factory):
    seed, before, _ids, _t0, _t1, _spec = _shift_six(factory)
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
    ], f"the rows did not shift to the planned layout: {_layout(after)}"
    assert [r["position"] for r in after] == list(range(8))
    _assert_every_old_row_intact(before, after)


def test_null_author_and_null_timestamps_stay_null(factory):
    """finding 9: no moved row gets a fabricated author or a fresh timestamp."""
    seed, _before, _ids, _t0, _t1, _spec = _shift_six(factory)
    after = _by_marker(_rows(factory, seed["owner_pk"]))

    failed = after["MK-FAILED"]
    assert (failed["created_by"], failed["modified_by"]) == (None, None), (
        "the failed placeholder gained an author it never had: "
        f"{failed['created_by']!r}/{failed['modified_by']!r}"
    )
    backfilled = after["MK-BACKFILL"]
    assert (backfilled["created_at"], backfilled["modified_at"]) == (None, None), (
        "the backfilled row gained timestamps it never had: "
        f"{backfilled['created_at']!r}/{backfilled['modified_at']!r}"
    )
    assert backfilled["slide_id"] is None


def test_insert_at_1_and_3_opens_pending_rows(factory):
    seed, before, ids, t0, t1, _spec = _shift_six(factory)
    after = _rows(factory, seed["owner_pk"])

    for position in (1, 3):
        _assert_pending(after[position], t0, t1)
    assert ids == [after[1]["slide_id"], after[3]["slide_id"]], (
        f"the returned slide_ids are not the new rows' ids in insert_at order: {ids}"
    )
    assert len(set(ids)) == 2, f"the two pending rows share a slide_id: {ids}"
    old_ids = {r["slide_id"] for r in before}
    assert not (set(ids) & old_ids), f"a pending row reused an existing slide's id: {ids}"


def test_insert_at_1_and_3_writes_spec_bumps_version_and_records_one_event(factory):
    seed, _before, _ids, _t0, _t1, new_spec = _shift_six(factory)
    deck = _deck(factory, seed["owner_pk"])

    assert deck.deck_spec_json == new_spec, "the canonical spec was not written with the shift"
    assert deck.version == 6, f"the shift did not bump the deck version once: {deck.version}"
    assert deck.slide_count == 6, (
        "slide_count has one writer, the post-commit write; the shift must not touch it "
        f"(got {deck.slide_count})"
    )
    assert _events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"])
    ], f"expected exactly one insert_slide/deck event: {_events(factory)}"


def test_the_shift_is_one_db_session(factory):
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    calls: List[int] = []
    _insert(
        factory,
        [1, 3],
        deck_spec=_spec_json(8, title="Shifted"),
        expected_rows=_expected_rows(before),
        release_id=seed["release_id"],
        calls=calls,
    )
    assert len(calls) == 1, f"the shift opened {len(calls)} db sessions, not one transaction"


def test_the_shift_goes_through_the_canonical_writer_with_the_exact_map(factory):
    """THE per-slide rewrite, called once, with the exact old-row map and no
    heuristic: now_dt=None, author_fallback=None, attribution={new: old row's},
    incoming={pending index: its pending record}."""
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    raw = _raw_json_columns(factory, seed["owner_pk"])

    real_rewrite = session_manager._rewrite_slide_rows
    real_attribute = session_manager._attribute_slide_records
    rewrites: List[Dict[str, Any]] = []
    heuristic_calls: List[int] = []

    def spy_rewrite(*args, **kwargs):
        bound = inspect.signature(real_rewrite).bind(*args, **kwargs)
        rewrites.append(dict(bound.arguments))
        return real_rewrite(*args, **kwargs)

    def spy_attribute(*args, **kwargs):
        heuristic_calls.append(1)
        return real_attribute(*args, **kwargs)

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch.object(session_manager, "_rewrite_slide_rows", spy_rewrite)
        )
        if hasattr(slide_repository, "_rewrite_slide_rows"):
            stack.enter_context(
                patch.object(slide_repository, "_rewrite_slide_rows", spy_rewrite)
            )
        stack.enter_context(
            patch.object(session_manager, "_attribute_slide_records", spy_attribute)
        )
        _insert(
            factory,
            [1, 3],
            deck_spec=_spec_json(8, title="Shifted"),
            expected_rows=_expected_rows(before),
            release_id=seed["release_id"],
        )

    assert len(rewrites) == 1, f"_rewrite_slide_rows called {len(rewrites)} times"
    call = rewrites[0]
    assert call["owner_id"] == seed["owner_pk"]
    assert call["now_dt"] is None
    assert call["author_fallback"] is None
    assert heuristic_calls == [], "the shift fell back to the attribution heuristic"

    # new index -> the raw columns of the old row that moves there
    new_index_of_old = {0: 0, 1: 2, 2: 4, 3: 5, 4: 6, 5: 7}
    expected_map = {
        new_index_of_old[old]: (raw[old]["verification_record"], raw[old]["deck_spec_slide"])
        for old in range(6)
    }
    got_map = {k: tuple(v) for k, v in (call["attribution"] or {}).items()}
    assert got_map == expected_map, f"not the exact old-row map: {got_map}"
    assert call["incoming"] == {
        1: {PENDING_HASH: PENDING_VERDICT},
        3: {PENDING_HASH: PENDING_VERDICT},
    }
    assert [s.get("html") for s in call["slides"]] == [
        before[0]["html"],
        PENDING_HTML,
        before[1]["html"],
        PENDING_HTML,
        before[2]["html"],
        before[3]["html"],
        before[4]["html"],
        before[5]["html"],
    ]


def _raw_json_columns(factory, owner_pk: int) -> List[Dict[str, Optional[str]]]:
    """The raw column strings, position order: what SlideAttribution carries."""
    db = factory()
    try:
        return [
            {name: getattr(r, name) for name in _JSON_COLUMNS}
            for r in db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner_pk)
            .order_by(SessionSlide.position)
            .all()
        ]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Append, and a gapped deck
# ---------------------------------------------------------------------------


def test_append_keeps_every_row_and_opens_the_pending_row_at_n(factory):
    """C7: the old rows ARE rewritten (every position goes through the canonical
    writer), with identical values.  What is pinned is that equality."""
    seed, before, ids, t0, t1, _spec = _shift_six(factory, insert_at=(6,))
    after = _rows(factory, seed["owner_pk"])

    assert _layout(after) == list(SIX) + ["PENDING"]
    _assert_every_old_row_intact(before, after)
    _assert_pending(after[6], t0, t1)
    assert ids == [after[6]["slide_id"]]


def test_gapped_rows_become_contiguous(factory):
    rows = {
        0: _real_row("MK-XRAY", 0, day=1),
        2: _real_row("MK-YANKEE", 2, day=2),
        5: _failed_placeholder_row("MK-FAILED", 5),
    }
    seed = _seed(factory, rows)
    before = _rows(factory, seed["owner_pk"])
    assert [r["position"] for r in before] == [0, 2, 5]

    t0 = datetime.utcnow()
    _insert(
        factory,
        [1],
        deck_spec=_spec_json(4, title="Shifted"),
        expected_rows=_expected_rows(before),
        release_id=seed["release_id"],
    )
    t1 = datetime.utcnow()
    after = _rows(factory, seed["owner_pk"])

    assert [r["position"] for r in after] == [0, 1, 2, 3], (
        f"rows are not contiguous after the shift (a row left at 5?): "
        f"{[r['position'] for r in after]}"
    )
    assert _layout(after) == ["MK-XRAY", "PENDING", "MK-YANKEE", "MK-FAILED"]
    _assert_every_old_row_intact(before, after)
    _assert_pending(after[1], t0, t1)


# ---------------------------------------------------------------------------
# Preconditions: nothing is written on any raise
# ---------------------------------------------------------------------------


def _mangle_hash(rows):
    out = _expected_rows(rows)
    out[2] = (out[2][0], compute_slide_hash("<p>someone edited this slide</p>"))
    return out


def _mangle_id(rows):
    out = _expected_rows(rows)
    out[4] = ("sid-someone-else", out[4][1])
    return out


def _drop_last(rows):
    return _expected_rows(rows)[:-1]


def _add_one(rows):
    return _expected_rows(rows) + [("sid-extra", compute_slide_hash("<p>x</p>"))]


def _swap(rows):
    out = _expected_rows(rows)
    out[0], out[2] = out[2], out[0]
    return out


@pytest.mark.parametrize(
    "expected_rows_of",
    [
        pytest.param(_mangle_hash, id="one-content-hash-differs"),
        pytest.param(_mangle_id, id="one-slide-id-differs"),
        pytest.param(_drop_last, id="a-row-was-added-since-planning"),
        pytest.param(_add_one, id="a-row-was-deleted-since-planning"),
        pytest.param(_swap, id="rows-were-reordered-since-planning"),
        pytest.param(lambda rows: [], id="expected-empty-while-rows-exist"),
    ],
)
def test_rows_that_are_not_the_planned_rows_refuse_the_shift(factory, expected_rows_of):
    seed = _seed_six(factory)
    before_rows = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)

    with pytest.raises(slide_repository.SlideRowsChangedError):
        _insert(
            factory,
            [1, 3],
            deck_spec=_spec_json(8, title="Shifted"),
            expected_rows=expected_rows_of(before_rows),
            release_id=seed["release_id"],
        )
    assert _db_state(factory) == state, "a refused shift wrote something"


def test_rows_that_vanished_since_planning_refuse_the_shift(factory):
    seed = _seed(factory, {})
    state = _db_state(factory)
    with pytest.raises(slide_repository.SlideRowsChangedError):
        _insert(
            factory,
            [1],
            deck_spec=_spec_json(3, title="Shifted"),
            expected_rows=[("sid-a", compute_slide_hash("<p>a</p>")),
                           ("sid-b", compute_slide_hash("<p>b</p>"))],
            release_id=seed["release_id"],
        )
    assert _db_state(factory) == state


@pytest.mark.parametrize(
    "insert_at, spec_slides",
    [
        pytest.param([3, 1], 8, id="not-ascending"),
        pytest.param([1, 1], 8, id="not-distinct"),
        pytest.param([-1], 7, id="negative"),
        pytest.param([7], 7, id="beyond-the-shifted-deck"),
        pytest.param([1, 8], 8, id="second-index-beyond-the-shifted-deck"),
        pytest.param([1, 3], 7, id="spec-has-fewer-slides-than-rows-plus-inserts"),
        pytest.param([1, 3], 9, id="spec-has-more-slides-than-rows-plus-inserts"),
    ],
)
def test_an_invalid_insert_refuses_the_shift(factory, insert_at, spec_slides):
    seed = _seed_six(factory)
    before_rows = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)

    with pytest.raises(ValueError):
        _insert(
            factory,
            insert_at,
            deck_spec=_spec_json(spec_slides, title="Shifted"),
            expected_rows=_expected_rows(before_rows),
            release_id=seed["release_id"],
        )
    assert _db_state(factory) == state, "a refused shift wrote something"


def test_a_session_with_no_deck_row_refuses_the_shift(factory):
    """C2: prior_spec came from the deck row, so no deck row means the deck
    changed under the architect.  Nothing, including a new deck row, is written."""
    seed = _seed(factory, {}, with_deck=False)
    state = _db_state(factory)
    with pytest.raises(slide_repository.SlideRowsChangedError):
        _insert(
            factory,
            [3],
            deck_spec=_spec_json(4, title="Shifted"),
            expected_rows=[],
            release_id=seed["release_id"],
        )
    assert _db_state(factory) == state
    assert _deck(factory, seed["owner_pk"]) is None


def test_an_unknown_session_raises_session_not_found(factory):
    seed = _seed(factory, {})
    state = _db_state(factory)
    with pytest.raises(SessionNotFoundError):
        _insert(
            factory,
            [0],
            deck_spec=_spec_json(1, title="Shifted"),
            expected_rows=[],
            release_id=seed["release_id"],
            session_id="no-such-session",
        )
    assert _db_state(factory) == state


def test_a_refused_evidence_write_rolls_back_the_whole_shift(factory):
    """One transaction: when the evidence row is refused (here, an actor pin that is
    not the session's persisted pin), the rows, spec and version roll back with it."""
    seed = _seed_six(factory)
    before_rows = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)
    with pytest.raises(ValueError, match="persisted pin"):
        _insert(
            factory,
            [1, 3],
            deck_spec=_spec_json(8, title="Shifted"),
            expected_rows=_expected_rows(before_rows),
            release_id=seed["release_id"],
            mutation=_mutation(OWNER_SID, seed["release_id"] + 1000),
        )
    assert _db_state(factory) == state, "part of a failed shift was committed"


# ---------------------------------------------------------------------------
# A row-less (spec-only) deck
# ---------------------------------------------------------------------------


def test_a_row_less_deck_writes_the_spec_and_version_only(factory):
    """C2: a 3-slide spec-only deck gaining a slide at 3.  The index is checked
    against the spec, not against zero rows (that range would be [0, 1))."""
    seed = _seed(factory, {}, prior_spec_slides=3, version=3)
    new_spec = _spec_json(4, title="Shifted")

    ids = _insert(
        factory,
        [3],
        deck_spec=new_spec,
        expected_rows=[],
        release_id=seed["release_id"],
    )

    assert ids == []
    assert _rows(factory, seed["owner_pk"]) == [], "a row-less deck gained rows"
    deck = _deck(factory, seed["owner_pk"])
    assert deck.deck_spec_json == new_spec
    assert deck.version == 4
    assert _events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"])
    ], f"a spec-only shift still records exactly one insert_slide event: {_events(factory)}"


def test_a_row_less_deck_rejects_an_index_beyond_its_spec(factory):
    seed = _seed(factory, {}, prior_spec_slides=3, version=3)
    state = _db_state(factory)
    with pytest.raises(ValueError):
        _insert(
            factory,
            [4],
            deck_spec=_spec_json(4, title="Shifted"),
            expected_rows=[],
            release_id=seed["release_id"],
        )
    assert _db_state(factory) == state


# ---------------------------------------------------------------------------
# Exact attribution, never the heuristic (C5)
# ---------------------------------------------------------------------------


def test_a_leftover_pending_row_keeps_its_own_record(factory):
    """An id-less pending placeholder left by an earlier turn sits AFTER the insert
    point, byte-identical to the row the shift opens.  The heuristic's pass 2 (by
    content hash) would hand the leftover's record to the NEW pending row and leave
    the leftover with nothing.  The exact map cannot."""
    leftover_record = {
        PENDING_HASH: PENDING_VERDICT,
        compute_slide_hash("<p>leftover's earlier draft</p>"): {"marker": "LEFTOVER-HISTORY"},
    }
    rows = {
        0: _real_row("MK-ALPHA", 0, day=1),
        1: _real_row("MK-BRAVO", 1, day=2),
        2: {
            "html": PENDING_HTML,
            "slide_id": None,
            "scripts": "",
            "created_by": "earlier-turn@test.com",
            "created_at": datetime(2024, 5, 1, 12, 0, 0),
            "modified_by": "earlier-turn@test.com",
            "modified_at": datetime(2024, 5, 1, 12, 0, 0),
            "verification_record": json.dumps(leftover_record),
            "deck_spec_slide": None,
        },
    }
    seed = _seed(factory, rows)
    before = _rows(factory, seed["owner_pk"])
    leftover_before = before[2]

    t0 = datetime.utcnow()
    (new_id,) = _insert(
        factory,
        [1],
        deck_spec=_spec_json(4, title="Shifted"),
        expected_rows=_expected_rows(before),
        release_id=seed["release_id"],
    )
    t1 = datetime.utcnow()
    after = _rows(factory, seed["owner_pk"])

    assert _layout(after) == ["MK-ALPHA", "PENDING", "MK-BRAVO", "PENDING"]
    new_rows = [r for r in after if r["slide_id"] == new_id]
    leftovers = [r for r in after if r["html"] == PENDING_HTML and r["slide_id"] is None]
    assert len(new_rows) == 1 and new_rows[0]["position"] == 1
    assert len(leftovers) == 1 and leftovers[0]["position"] == 3

    assert new_rows[0]["verification_record"] == {PENDING_HASH: PENDING_VERDICT}, (
        "the new pending row took the leftover's record (heuristic attribution): "
        f"{new_rows[0]['verification_record']}"
    )
    _assert_pending(new_rows[0], t0, t1)
    assert leftovers[0]["verification_record"] == leftover_record
    assert _identity(leftovers[0]) == _identity(leftover_before), (
        f"the leftover placeholder changed across the shift: {leftovers[0]}"
    )
    _assert_every_old_row_intact(before, after)


# ---------------------------------------------------------------------------
# Contributor session
# ---------------------------------------------------------------------------


def test_a_contributor_session_shifts_the_owners_deck(factory):
    seed = _seed_six(factory, with_contributor=True)
    before = _rows(factory, seed["owner_pk"])
    new_spec = _spec_json(8, title="Shifted")

    _insert(
        factory,
        [1, 3],
        deck_spec=new_spec,
        expected_rows=_expected_rows(before),
        release_id=seed["release_id"],
        session_id=CONTRIB_SID,
    )

    after = _rows(factory, seed["owner_pk"])
    assert _layout(after) == [
        "MK-ALPHA", "PENDING", "MK-FAILED", "PENDING",
        "MK-BRAVO", "MK-BACKFILL", "MK-CHARLIE", "MK-DELTA",
    ]
    _assert_every_old_row_intact(before, after)
    assert _rows(factory, seed["contrib_pk"]) == [], "rows landed on the contributor session"
    assert _deck(factory, seed["contrib_pk"]) is None
    deck = _deck(factory, seed["owner_pk"])
    assert deck.deck_spec_json == new_spec and deck.version == 6
    assert _events(factory) == [
        ("insert_slide", "deck", seed["contrib_pk"], seed["owner_pk"], seed["release_id"])
    ], "the evidence must name the contributor as actor and the owner as root"


def _last_activity(factory) -> Dict[str, datetime]:
    db = factory()
    try:
        return {s.session_id: s.last_activity for s in db.query(UserSession).all()}
    finally:
        db.close()


def test_the_shift_touches_last_activity_on_both_sessions(factory):
    """D4 step 5: the requesting session and the deck owner both show activity.
    ``last_activity`` orders the session list."""
    seed = _seed_six(factory, with_contributor=True)
    before = _rows(factory, seed["owner_pk"])
    db = factory()
    try:
        db.query(UserSession).update(
            {UserSession.last_activity: datetime(2024, 1, 1, 0, 0, 0)},
            synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()

    t0 = datetime.utcnow()
    _insert(
        factory,
        [1, 3],
        deck_spec=_spec_json(8, title="Shifted"),
        expected_rows=_expected_rows(before),
        release_id=seed["release_id"],
        session_id=CONTRIB_SID,
    )
    t1 = datetime.utcnow()

    activity = _last_activity(factory)
    for sid in (OWNER_SID, CONTRIB_SID):
        assert t0 <= activity[sid] <= t1, (
            f"the shift did not touch {sid}'s last_activity: {activity[sid]!r}"
        )


# ---------------------------------------------------------------------------
# Multi-worker coherence (tellr-code-review §1)
# ---------------------------------------------------------------------------


def _worker() -> ChatService:
    """One simulated uvicorn worker (pattern: test_multiworker_cache_coherence)."""
    worker = ChatService.__new__(ChatService)
    worker.agent = MagicMock()
    worker._deck_cache = {}
    worker._cache_lock = threading.Lock()
    return worker


def test_a_worker_that_cached_the_deck_sees_the_shift(factory):
    """The shift bumps deck.version in its transaction, so another worker's
    _deck_cache is revalidated and reloads the shifted deck."""
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    fake = _fake_db(factory)

    with patch("src.api.services.session_manager.get_db_session", fake), patch(
        "src.api.services.slide_repository.get_db_session", fake
    ), patch(
        "src.api.services.chat_service.get_session_manager",
        return_value=SessionManager(),
    ), patch(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    ):
        worker = _worker()
        cached = worker._get_or_load_deck(OWNER_SID)
        assert [_marker(s.html) for s in cached.slides] == list(SIX)

        SlideWriter(SessionManager()).insert_pending_slides(
            OWNER_SID,
            [1, 3],
            deck_spec=_spec_json(8, title="Shifted"),
            expected_rows=_expected_rows(before),
            created_by=REQUESTER,
            mutation=_mutation(OWNER_SID, seed["release_id"]),
        )

        reloaded = worker._get_or_load_deck(OWNER_SID)

    assert [(_marker(s.html) or "PENDING") for s in reloaded.slides] == [
        "MK-ALPHA", "PENDING", "MK-FAILED", "PENDING",
        "MK-BRAVO", "MK-BACKFILL", "MK-CHARLIE", "MK-DELTA",
    ], "a worker that cached the deck before the shift still serves the old deck"


# ---------------------------------------------------------------------------
# The other two whole-deck rewrites keep their arguments (C3)
# ---------------------------------------------------------------------------


def _bare_slide(html: str, **extra) -> Dict[str, Any]:
    return {"html": html, "scripts": "", **extra}


def _deck_dict(slides: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"title": "T", "css": "", "external_scripts": [], "scripts": "", "slides": slides}


def _save(factory, deck_dict: Dict[str, Any], *, modified_by: Optional[str]) -> None:
    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
        SessionManager().save_slide_deck(
            session_id=OWNER_SID,
            title="T",
            html_content="",
            slide_count=len(deck_dict["slides"]),
            deck_dict=deck_dict,
            modified_by=modified_by,
        )


def test_save_slide_deck_keeps_now_and_its_author_fallback(factory):
    """Green before and after.  A slide with an author but no editor and no
    timestamps: save_slide_deck stamps now (now_dt) and the saver (author_fallback)."""
    seed = _seed(factory, {}, with_deck=False)
    t0 = datetime.utcnow()
    _save(
        factory,
        _deck_dict([_bare_slide("<p>MK-SAVED</p>", slide_id="s1", created_by="orig@test.com")]),
        modified_by="saver@test.com",
    )
    t1 = datetime.utcnow()
    (row,) = _rows(factory, seed["owner_pk"])
    assert row["created_by"] == "orig@test.com"
    assert row["modified_by"] == "saver@test.com"
    for col in ("created_at", "modified_at"):
        assert row[col] is not None and t0 <= row[col] <= t1, f"{col}={row[col]!r}"


def test_restore_version_keeps_now_and_no_author_fallback(factory):
    """Green before and after (C3).  A restored slide with no timestamps gets the
    restore's now; with no authors it stays author-less (restore has no writer)."""
    seed = _seed(factory, {}, with_deck=False)
    snapshot = _deck_dict([_bare_slide("<p>MK-RESTORED</p>", slide_id="r1")])
    _save(factory, snapshot, modified_by=None)
    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
        SessionManager().create_version(OWNER_SID, "v1", json.loads(json.dumps(snapshot)))
    _save(factory, _deck_dict([_bare_slide("<p>MK-LATER</p>", slide_id="l1")]), modified_by=None)

    t0 = datetime.utcnow()
    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)), patch(
        "src.services.spec_sync.discard_marker", lambda session_id: None
    ):
        SessionManager().restore_version(OWNER_SID, 1)
    t1 = datetime.utcnow()

    (row,) = _rows(factory, seed["owner_pk"])
    assert _marker(row["html"]) == "MK-RESTORED"
    assert (row["created_by"], row["modified_by"]) == (None, None)
    for col in ("created_at", "modified_at"):
        assert row[col] is not None and t0 <= row[col] <= t1, (
            f"restore lost its now_dt: {col}={row[col]!r}"
        )


def test_restore_merges_each_save_point_verdict_onto_its_own_slide(factory):
    """restore_version's ``incoming`` is keyed by the restored slide's position.
    Neither slide is in the current rows, so the save point is the only source of
    their verdicts: each must land on its own slide's row (found by marker), keyed
    by that slide's hash, and nowhere else."""
    seed = _seed(factory, {}, with_deck=False)
    one, two = "<p>MK-RONE</p>", "<p>MK-RTWO</p>"
    verdicts = {
        compute_slide_hash(one): {"score": 11, "explanation": "SAVE-POINT-RONE"},
        compute_slide_hash(two): {"score": 22, "explanation": "SAVE-POINT-RTWO"},
    }
    snapshot = _deck_dict(
        [_bare_slide(one, slide_id="r1"), _bare_slide(two, slide_id="r2")]
    )
    _save(factory, snapshot, modified_by=None)
    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
        SessionManager().create_version(
            OWNER_SID, "v1", json.loads(json.dumps(snapshot)), verification_map=verdicts
        )
    _save(factory, _deck_dict([_bare_slide("<p>MK-LATER</p>", slide_id="l1")]), modified_by=None)

    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)), patch(
        "src.services.spec_sync.discard_marker", lambda session_id: None
    ):
        SessionManager().restore_version(OWNER_SID, 1)

    after = _by_marker(_rows(factory, seed["owner_pk"]))
    assert set(after) == {"MK-RONE", "MK-RTWO"}
    for marker, html in (("MK-RONE", one), ("MK-RTWO", two)):
        content_hash = compute_slide_hash(html)
        assert after[marker]["verification_record"] == {content_hash: verdicts[content_hash]}, (
            f"{marker}'s save-point verdict did not land on its own row: "
            f"{after[marker]['verification_record']}"
        )


def test_save_and_restore_each_rewrite_through_rewrite_slide_rows(factory):
    """One copy of the per-slide rewrite: both callers reach _rewrite_slide_rows
    once, with their own now_dt and author_fallback."""
    seed = _seed(factory, {}, with_deck=False)
    real = session_manager._rewrite_slide_rows
    calls: List[Dict[str, Any]] = []

    def spy(*args, **kwargs):
        calls.append(dict(inspect.signature(real).bind(*args, **kwargs).arguments))
        return real(*args, **kwargs)

    snapshot = _deck_dict([_bare_slide("<p>MK-ONE</p>", slide_id="o1")])
    with patch.object(session_manager, "_rewrite_slide_rows", spy):
        _save(factory, snapshot, modified_by="saver@test.com")
        assert len(calls) == 1
        assert calls[0]["owner_id"] == seed["owner_pk"]
        assert isinstance(calls[0]["now_dt"], datetime)
        assert calls[0]["author_fallback"] == "saver@test.com"

        with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)), patch(
            "src.services.spec_sync.discard_marker", lambda session_id: None
        ):
            SessionManager().create_version(OWNER_SID, "v1", json.loads(json.dumps(snapshot)))
            calls.clear()
            SessionManager().restore_version(OWNER_SID, 1)
        assert len(calls) == 1
        assert isinstance(calls[0]["now_dt"], datetime), "restore must keep now_dt (C3)"
        assert calls[0]["author_fallback"] is None
