"""``ChatService.insert_slide`` on the one-transaction writer (#314 follow-up, Task 3).

The viewer's "New slide" posts no HTML.  The service then inserts the deck's own
blank shell (``blank_slide_shell`` of the cached deck at the landed position), and
hands the write to ``SessionManager.insert_slide``: rows, spec, deck columns and
evidence in ONE transaction, with the exact old-row map (plan D1, D2, D8, D12;
PLAN-CORRECTIONS C11, C12 and the Task 3 pre-brief).

What these tests are careful about
----------------------------------
**Existing slides are compared whole, by marker.**  The cached deck the service
plans against came through ``get_slide_deck``, which swaps raw emails for SCIM
display names; ``save_slide_deck`` wrote those names back into every row and
turned NULL timestamps into "now".  So the display-name lookup is patched to map
every email to a name, and every old row must come back with its raw columns.

**Oracles are written out.**  The expected shells, spec entries and event types are
literals here, never computed by the code under test.

**Failure paths read the database AND the cache.**  A refused insert must write
nothing, must not leave a "ghost" slide in this worker's cache, and must leave the
next load fresh from the database, so a stale-rows 409 heals on the next try (m11).

**Two workers, one database** (tellr-code-review §1): each ``ChatService`` is a
worker with its own cache.  A worker whose cache is stale can only produce a 409,
never a write-back of its stale deck.

New Task 2 symbols (``DeckBusyError``, ``SlideRowsChangedError``) are read off
``session_manager`` at use, so a missing symbol reddens only its own tests.
"""
from __future__ import annotations

import contextlib
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.api.services.chat_service as chat_service_module
import src.api.services.session_manager as session_manager
import src.database.models  # noqa: F401 — register every ORM model
import src.domain.deck_spec_slides as deck_spec_slides
from src.api.services.chat_service import ArcReviewInFlightError, ChatService
from src.api.services.session_manager import SessionManager, VersionConflictError
from src.core.database import Base
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SharedDeckMutationEvent,
    SlideDeckVersion,
    UserSession,
)
from src.database.models.usage_event import UsageEvent
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.utils.slide_hash import compute_slide_hash

OWNER_SID = "manual-insert-svc-owner"
CONTRIB_SID = "manual-insert-svc-contrib"

#: What ``chat_service.get_current_username`` answers: the new slide's author.
EDITOR = "owner@test.com"
#: The route's ``get_current_user()``, for the usage event.
INSERTED_BY = "editor@test.com"

#: Written out, not imported: the oracles must not depend on the code under test.
BARE_BLANK = '<div class="slide"></div>'
WRAPPER_SHELL = '<section data-label="Acme Ground"><div class="slide"></div></section>'
EVENT_TYPE = "slide_inserted"
DECK_VERSION = 5

#: The SCIM lookup the read path applies: EVERY seeded email has a display name,
#: so a write-back of the cached deck's authorship is visible on every row.
DISPLAY_NAMES = {
    "alice@test.com": "Alice Display",
    "bob@test.com": "Bob Display",
    "carol@test.com": "Carol Display",
    "owner@test.com": "Owner Display",
    "editor@test.com": "Editor Display",
}

_MARKER_RE = re.compile(r"MK-[A-Z]+")

#: The three seeded slides, raw, in position order.  CHARLIE is a backfilled
#: legacy row: no slide_id, no modifier, NULL timestamps.
SEED_ROWS: List[Dict[str, Any]] = [
    {
        "marker": "MK-ALPHA",
        "slide_id": "sid-alpha",
        "scripts": "/* alpha chart */",
        "created_by": "alice@test.com",
        "created_at": datetime(2026, 9, 1, 9, 0, 0),
        "modified_by": "bob@test.com",
        "modified_at": datetime(2026, 9, 2, 10, 30, 0),
    },
    {
        "marker": "MK-BRAVO",
        "slide_id": "sid-bravo",
        "scripts": "",
        "created_by": "bob@test.com",
        "created_at": datetime(2026, 9, 3, 9, 0, 0),
        "modified_by": "carol@test.com",
        "modified_at": datetime(2026, 9, 4, 11, 45, 0),
    },
    {
        "marker": "MK-CHARLIE",
        "slide_id": None,
        "scripts": "",
        "created_by": "carol@test.com",
        "created_at": None,
        "modified_by": None,
        "modified_at": None,
    },
]
MARKERS = [r["marker"] for r in SEED_ROWS]

#: Distinct inline grounds, one per slide (the unpinned graph deck's shape).
INLINE_STYLES = [
    "background:#0b1f3a;color:#ffffff;padding:60px",
    "background:#ffffff;color:#1b3139;padding:48px 64px",
    "background:#f4f4f4;color:#222222;padding:40px",
]


def _bare_html(marker: str, index: int) -> str:
    return f'<div class="slide"><h1>{marker}</h1><p>body of {marker}</p></div>'


def _wrapper_html(marker: str, index: int) -> str:
    return (
        '<section data-label="Acme Ground"><div class="slide">'
        f"<h1>{marker}</h1><p>body of {marker}</p></div></section>"
    )


def _inline_html(marker: str, index: int) -> str:
    return (
        f'<div class="slide" style="{INLINE_STYLES[index]}">'
        f"<h1>{marker}</h1><p>body of {marker}</p></div>"
    )


SHAPES: Dict[str, Callable[[str, int], str]] = {
    "bare": _bare_html,
    "wrapper": _wrapper_html,
    "inline": _inline_html,
}


def _spec(markers: List[str]) -> Dict[str, Any]:
    return {
        "title": "Manual insert service deck",
        "audience": "test",
        "purpose": "test",
        "argument": "test",
        "call_to_action": "test",
        "narrative_arc": ["a", "b", "c"],
        "design_contract": {
            "design_system_id": None,
            "template_id": None,
            "slide_style_id": None,
        },
        "resolved_data": {"synthesis": "s", "figures": [], "gaps": []},
        "slides": [
            {
                "position": i,
                "purpose": f"PURPOSE-{m}",
                "content_brief": f"BRIEF-{m}",
                "assumes": "",
                "hands_off": "",
                "data_references": [],
            }
            for i, m in enumerate(markers)
        ],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    # autoflush=False, as production: nothing here may rely on an implicit flush.
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _fake_db(factory):
    @contextlib.contextmanager
    def _cm():
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


@pytest.fixture()
def service(factory):
    """A ChatService (one "worker") whose every DB hop reaches this test's engine.

    The shape of ``test_insert_slide_service.py``'s fixture, plus the username
    (the new slide's author), slide_repository's DB hop and the SCIM display-name
    lookup (imported lazily by ``_resolve_deck_display_names``; the real one can
    reach a WorkspaceClient that retries and hangs).
    """
    fake = _fake_db(factory)
    with patch("src.api.services.session_manager.get_db_session", fake), patch(
        "src.api.services.deck_level_writer.get_db_session", fake
    ), patch("src.api.services.slide_repository.get_db_session", fake), patch(
        "src.api.services.chat_service.get_session_manager",
        return_value=SessionManager(),
    ), patch(
        "src.api.services.chat_service.get_current_username", return_value=EDITOR
    ), patch(
        "src.services.identity_provider.resolve_display_names",
        lambda emails: {e: DISPLAY_NAMES[e] for e in emails if e in DISPLAY_NAMES},
    ):
        yield ChatService()


def _seed(factory, shape: str = "bare", *, spec: bool = True) -> Dict[str, Any]:
    """Owner + contributor sessions, a 3-slide deck of *shape* with a spec."""
    html_of = SHAPES[shape]
    db = factory()
    try:
        owner = UserSession(session_id=OWNER_SID, created_by="owner@test.com")
        db.add(owner)
        db.flush()
        contrib = UserSession(
            session_id=CONTRIB_SID,
            created_by="contrib@test.com",
            parent_session_id=owner.id,
        )
        db.add(contrib)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=owner.id,
                title="Manual insert service deck",
                html_content="<html>KNIT-BEFORE</html>",
                scripts_content="",
                slide_count=len(SEED_ROWS),
                version=DECK_VERSION,
                deck_spec_json=json.dumps(_spec(MARKERS)) if spec else None,
            )
        )
        for position, seed in enumerate(SEED_ROWS):
            html = html_of(seed["marker"], position)
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=f"row-{position}",
                    html=html,
                    slide_id=seed["slide_id"],
                    scripts=seed["scripts"],
                    created_by=seed["created_by"],
                    created_at=seed["created_at"],
                    modified_by=seed["modified_by"],
                    modified_at=seed["modified_at"],
                    verification_record=json.dumps(
                        {compute_slide_hash(html): {"score": 90, "who": seed["marker"]}}
                    ),
                    deck_spec_slide=json.dumps({"purpose": f"FRAGMENT-{seed['marker']}"}),
                )
            )
        db.commit()
        return {"owner_pk": owner.id, "contrib_pk": contrib.id}
    finally:
        db.close()


@pytest.fixture()
def seeded(factory):
    return _seed(factory, "bare")


# ---------------------------------------------------------------------------
# Reading the database back
# ---------------------------------------------------------------------------

_SLIDE_COLUMNS = [c.name for c in SessionSlide.__table__.columns]
_DECK_COLUMNS = [c.name for c in SessionSlideDeck.__table__.columns]


def _marker(html: Optional[str]) -> Optional[str]:
    found = _MARKER_RE.search(html or "")
    return found.group(0) if found else None


def _rows(factory, owner_pk: int) -> List[Dict[str, Any]]:
    db = factory()
    try:
        return [
            {c: getattr(r, c) for c in _SLIDE_COLUMNS}
            for r in db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner_pk)
            .order_by(SessionSlide.position)
            .all()
        ]
    finally:
        db.close()


def _deck_row(factory, owner_pk: int) -> Dict[str, Any]:
    db = factory()
    try:
        deck = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner_pk)
            .one()
        )
        return {c: getattr(deck, c) for c in _DECK_COLUMNS}
    finally:
        db.close()


def _spec_entries(factory, owner_pk: int) -> List[Dict[str, Any]]:
    raw = _deck_row(factory, owner_pk)["deck_spec_json"]
    return sorted(json.loads(raw)["slides"], key=lambda e: e["position"])


def _save_points(factory, owner_pk: int) -> List[Dict[str, Any]]:
    db = factory()
    try:
        return [
            {"description": v.description, "deck": json.loads(v.deck_json)}
            for v in db.query(SlideDeckVersion)
            .filter(SlideDeckVersion.session_id == owner_pk)
            .order_by(SlideDeckVersion.version_number)
            .all()
        ]
    finally:
        db.close()


def _mutation_events(factory) -> List[tuple]:
    db = factory()
    try:
        return [
            (e.operation, e.object_type, e.object_id, e.actor_session_id)
            for e in db.query(SharedDeckMutationEvent)
            .order_by(SharedDeckMutationEvent.id)
            .all()
        ]
    finally:
        db.close()


def _usage_events(factory) -> List[tuple]:
    db = factory()
    try:
        return [
            (u.username, u.event_type, u.session_id)
            for u in db.query(UsageEvent).order_by(UsageEvent.id).all()
        ]
    finally:
        db.close()


def _db_state(factory) -> Dict[str, Any]:
    """Everything the insert could write: rows, deck rows, save points, evidence."""
    db = factory()
    try:
        state = {
            "rows": [
                {c: getattr(r, c) for c in _SLIDE_COLUMNS}
                for r in db.query(SessionSlide)
                .order_by(SessionSlide.session_id, SessionSlide.position)
                .all()
            ],
            "decks": [
                {c: getattr(d, c) for c in _DECK_COLUMNS}
                for d in db.query(SessionSlideDeck).order_by(SessionSlideDeck.id).all()
            ],
            "versions": [
                (v.session_id, v.version_number, v.description, v.deck_json)
                for v in db.query(SlideDeckVersion).order_by(SlideDeckVersion.id).all()
            ],
        }
    finally:
        db.close()
    state["mutations"] = _mutation_events(factory)
    state["usage"] = _usage_events(factory)
    return state


def _fresh_load(factory) -> Dict[str, Any]:
    """The deck as ANY worker would load it from the database right now."""
    return SlideDeck.from_dict(SessionManager().get_slide_deck(OWNER_SID)).to_dict()


def _project(slides: List[Dict[str, Any]]) -> List[tuple]:
    return [
        (
            s.get("slide_id"),
            s.get("html"),
            s.get("created_by"),
            s.get("modified_by"),
            s.get("created_at"),
            s.get("modified_at"),
        )
        for s in slides
    ]


def _cached_markers(service: ChatService) -> List[Optional[str]]:
    deck = service._get_or_load_deck(OWNER_SID)
    return [_marker(s.html) for s in deck.slides]


def _seed_rows_whole(shape: str = "bare") -> Dict[str, Dict[str, Any]]:
    """The seeded rows' columns (everything but position and the internal id), by marker."""
    html_of = SHAPES[shape]
    out = {}
    for position, seed in enumerate(SEED_ROWS):
        html = html_of(seed["marker"], position)
        out[seed["marker"]] = {
            "html": html,
            "slide_id": seed["slide_id"],
            "scripts": seed["scripts"],
            "created_by": seed["created_by"],
            "created_at": seed["created_at"],
            "modified_by": seed["modified_by"],
            "modified_at": seed["modified_at"],
            "verification_record": json.dumps(
                {compute_slide_hash(html): {"score": 90, "who": seed["marker"]}}
            ),
            "deck_spec_slide": json.dumps({"purpose": f"FRAGMENT-{seed['marker']}"}),
        }
    return out


def _whole(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("position", "id", "session_id")}


# ---------------------------------------------------------------------------
# The blank is the deck's own shell
# ---------------------------------------------------------------------------


def test_a_blank_insert_on_a_section_wrapper_deck_is_the_wrapper_shell(factory, service):
    """D1/B1: on the shipped design system the ground is on the ``<section>``.

    The bare ``<div class="slide"></div>`` would be a white box there, so the
    new row must be the wrapper with no content (and the response must show it).
    """
    pks = _seed(factory, "wrapper")

    result = service.insert_slide(OWNER_SID, 1)

    rows = _rows(factory, pks["owner_pk"])
    assert [_marker(r["html"]) for r in rows] == ["MK-ALPHA", None, "MK-BRAVO", "MK-CHARLIE"]
    assert rows[1]["html"] == WRAPPER_SHELL, (
        f"the blank is not the deck's wrapper shell: {rows[1]['html']!r}"
    )
    assert result["slides"][1]["html"] == WRAPPER_SHELL


def test_a_blank_insert_on_a_bare_div_deck_is_the_bare_blank(factory, service, seeded):
    service.insert_slide(OWNER_SID, 1)

    rows = _rows(factory, seeded["owner_pk"])
    assert [_marker(r["html"]) for r in rows] == ["MK-ALPHA", None, "MK-BRAVO", "MK-CHARLIE"]
    assert rows[1]["html"] == BARE_BLANK


@pytest.mark.parametrize(
    "position, expected_style",
    [
        # Every slide has its own ground: the nearest non-cover slide before the
        # insertion point is the source (C3 as revised by the supervisor).
        (2, INLINE_STYLES[1]),
        (3, INLINE_STYLES[2]),
    ],
)
def test_the_shell_is_taken_from_the_deck_at_the_insertion_point(
    factory, service, position, expected_style
):
    """The shell is ``blank_slide_shell(deck htmls, landed)``: which slide's ground
    it copies depends on WHERE the slide goes, so a service that passed a fixed
    position (0, or the deck length) copies the wrong neighbour's ground."""
    pks = _seed(factory, "inline")

    result = service.insert_slide(OWNER_SID, position)

    rows = _rows(factory, pks["owner_pk"])
    expected = f'<div class="slide" style="{expected_style}"></div>'
    assert rows[position]["html"] == expected, (
        f"insert at {position} copied the wrong ground: {rows[position]['html']!r}"
    )
    assert result["inserted_position"] == position


def test_the_shell_is_computed_from_the_cached_deck_at_the_landed_position(
    factory, service, seeded, monkeypatch
):
    """Requesting 99 on a 3-slide deck lands at 3, and 3 is what the shell is asked
    for, with the deck's slide HTML in order."""
    calls: List[tuple] = []
    real = deck_spec_slides.blank_slide_shell

    def spy(slide_htmls, position):
        calls.append((list(slide_htmls), position))
        return real(slide_htmls, position)

    monkeypatch.setattr(deck_spec_slides, "blank_slide_shell", spy)
    monkeypatch.setattr(chat_service_module, "blank_slide_shell", spy, raising=False)

    service.insert_slide(OWNER_SID, 99)

    deck_htmls = [_bare_html(m, i) for i, m in enumerate(MARKERS)]
    assert calls == [(deck_htmls, 3)], f"blank_slide_shell was called with {calls}"


def test_a_caller_supplied_html_is_stored_verbatim_even_on_a_wrapper_deck(factory, service):
    pks = _seed(factory, "wrapper")
    supplied = '<div class="slide"><h2>MK-HUMAN</h2></div>'

    service.insert_slide(OWNER_SID, 1, html=supplied)

    rows = _rows(factory, pks["owner_pk"])
    assert [_marker(r["html"]) for r in rows] == [
        "MK-ALPHA",
        "MK-HUMAN",
        "MK-BRAVO",
        "MK-CHARLIE",
    ]
    assert rows[1]["html"] == supplied


def test_html_without_a_slide_wrapper_is_refused_and_nothing_changes(
    factory, service, seeded
):
    before = _db_state(factory)

    with pytest.raises(ValueError, match="slide"):
        service.insert_slide(OWNER_SID, 1, html="<p>MK-NOWRAP no wrapper</p>")

    assert _db_state(factory) == before
    assert _cached_markers(service) == MARKERS


def test_a_negative_position_is_refused_before_the_shell_is_computed(
    factory, service, seeded, monkeypatch
):
    """C12: ``min(-1, n)`` is -1, so computing ``landed`` and the shell before the
    bound check feeds -1 to the shell.  The check comes first; nothing is written.

    The same spy then sees exactly one call on a valid insert, so its silence on
    the refused one is not a spy that is off the executed path.
    """
    calls: List[int] = []
    real = deck_spec_slides.blank_slide_shell

    def spy(slide_htmls, position):
        calls.append(position)
        return real(slide_htmls, position)

    monkeypatch.setattr(deck_spec_slides, "blank_slide_shell", spy)
    monkeypatch.setattr(chat_service_module, "blank_slide_shell", spy, raising=False)
    before = _db_state(factory)

    with pytest.raises(ValueError, match="Invalid slide position"):
        service.insert_slide(OWNER_SID, -1)

    assert calls == [], f"the shell was computed for a negative position: {calls}"
    assert _db_state(factory) == before

    service.insert_slide(OWNER_SID, 1)
    assert len(calls) == 1, f"the spy is not on the executed path: {calls}"


# ---------------------------------------------------------------------------
# Every existing slide keeps its raw row (no display-name write-back)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("session_id", [OWNER_SID, CONTRIB_SID])
def test_old_rows_keep_raw_emails_and_null_timestamps(factory, service, seeded, session_id):
    """AC4: the cached deck carries display names (the read path resolved them),
    and the insert must not write them back.  NULL authorship and NULL timestamps
    stay NULL; nothing gets a fresh ``modified_at``.

    The worker loads the deck first, exactly as the UI's GET /api/slides does.
    """
    cached = service._get_or_load_deck(session_id)
    assert cached.slides[0].created_by == "Alice Display", (
        "fixture precondition: the cached deck carries display names"
    )

    service.insert_slide(session_id, 1)

    rows = _rows(factory, seeded["owner_pk"])
    by_marker = {_marker(r["html"]): _whole(r) for r in rows if _marker(r["html"])}
    assert by_marker == _seed_rows_whole("bare"), (
        "an existing row changed: display names written back, a NULL filled in, "
        "or a record/fragment moved"
    )


def test_the_new_slide_is_attributed_to_the_editor_with_its_creation_time(
    factory, service, seeded
):
    before = datetime.utcnow() - timedelta(seconds=5)

    service.insert_slide(OWNER_SID, 1)

    new = _rows(factory, seeded["owner_pk"])[1]
    assert (new["created_by"], new["modified_by"]) == (EDITOR, EDITOR), (
        "the new slide's authorship must be the raw username, not a display name"
    )
    assert new["created_at"] is not None and new["created_at"] >= before
    assert new["modified_at"] is not None and new["modified_at"] >= before
    assert new["verification_record"] is None
    assert new["deck_spec_slide"] is None


def test_a_slide_inserted_with_no_resolvable_user_still_has_its_creation_time(
    factory, service, seeded
):
    """D8: ``created_at = modified_at = utcnow`` explicitly.  The exact-map writer
    fabricates nothing (``now_dt=None``), so without the explicit stamp a slide
    inserted while the username lookup fails would carry NULL timestamps."""
    before = datetime.utcnow() - timedelta(seconds=5)

    with patch(
        "src.api.services.chat_service.get_current_username",
        side_effect=RuntimeError("no user client"),
    ):
        service.insert_slide(OWNER_SID, 1)

    new = _rows(factory, seeded["owner_pk"])[1]
    assert new["created_by"] is None
    assert new["created_at"] is not None and new["created_at"] >= before
    assert new["modified_at"] is not None and new["modified_at"] >= before


# ---------------------------------------------------------------------------
# One save point, one version bump, one mutation event; the reloaded deck back
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("position, landed", [(1, 1), (0, 0), (99, 3)])
def test_one_save_point_named_for_where_the_slide_landed(
    factory, service, seeded, position, landed
):
    """Exactly one save point, "Inserted slide N" with N the LANDED 1-based number
    (an append requested at 99 is slide 4), snapshotting the deck as written."""
    before = _save_points(factory, seeded["owner_pk"])

    service.insert_slide(OWNER_SID, position)

    after = _save_points(factory, seeded["owner_pk"])
    assert len(after) == len(before) + 1, f"{len(after) - len(before)} save points"
    point = after[-1]
    assert point["description"] == f"Inserted slide {landed + 1}"
    row_ids = [r["slide_id"] for r in _rows(factory, seeded["owner_pk"])]
    assert [s.get("slide_id") for s in point["deck"]["slides"]] == row_ids, (
        "the save point does not snapshot the deck the insert wrote"
    )


def test_a_failed_save_point_does_not_fail_the_committed_insert(
    factory, service, seeded, monkeypatch
):
    """The save point comes after the commit; its failure is a warning, never an
    error for an insert that has already been written."""

    def broken(self, *args, **kwargs):
        raise RuntimeError("version table unreachable")

    monkeypatch.setattr(ChatService, "create_save_point", broken)

    result = service.insert_slide(OWNER_SID, 1)

    rows = _rows(factory, seeded["owner_pk"])
    assert [_marker(r["html"]) for r in rows] == ["MK-ALPHA", None, "MK-BRAVO", "MK-CHARLIE"]
    assert result["inserted_slide_id"] == rows[1]["slide_id"]


def test_a_stale_expected_version_refuses_and_the_current_one_proceeds(
    factory, service, seeded
):
    """``expected_version`` reaches the writer: a stale one is a
    VersionConflictError with nothing written (and no ghost), the current one
    inserts."""
    before = _db_state(factory)

    with pytest.raises(VersionConflictError):
        service.insert_slide(OWNER_SID, 1, expected_version=DECK_VERSION - 1)

    assert _db_state(factory) == before
    assert _cached_markers(service) == MARKERS

    service.insert_slide(OWNER_SID, 1, expected_version=DECK_VERSION)
    assert _deck_row(factory, seeded["owner_pk"])["version"] == DECK_VERSION + 1


def test_one_version_bump_for_rows_and_spec_together(factory, service, seeded):
    """Rows and spec are one transaction: one bump, not one per write (AC7)."""
    service.insert_slide(OWNER_SID, 1)

    assert _deck_row(factory, seeded["owner_pk"])["version"] == DECK_VERSION + 1


def test_the_spec_gains_a_blank_entry_at_the_landed_position(factory, service, seeded):
    service.insert_slide(OWNER_SID, 1)

    entries = _spec_entries(factory, seeded["owner_pk"])
    assert [(e["position"], e["purpose"], e["content_brief"]) for e in entries] == [
        (0, "PURPOSE-MK-ALPHA", "BRIEF-MK-ALPHA"),
        (1, "", ""),
        (2, "PURPOSE-MK-BRAVO", "BRIEF-MK-BRAVO"),
        (3, "PURPOSE-MK-CHARLIE", "BRIEF-MK-CHARLIE"),
    ]


@pytest.mark.parametrize("position, landed", [(1, 1), (99, 3)])
def test_the_result_is_the_reloaded_deck_plus_the_inserted_slide(
    factory, service, seeded, position, landed
):
    """The response is what any worker would now load: the new slide at the landed
    index, every slide_id equal to the rows' (the id-less legacy row stays
    id-less: no reindex), plus ``inserted_slide_id`` and ``inserted_position``,
    which the viewer uses to select the slide it just inserted (m6)."""
    result = service.insert_slide(OWNER_SID, position)

    rows = _rows(factory, seeded["owner_pk"])
    row_ids = [r["slide_id"] for r in rows]
    expected_markers = list(MARKERS)
    expected_markers.insert(landed, None)
    assert [_marker(r["html"]) for r in rows] == expected_markers
    charlie = next(r for r in rows if _marker(r["html"]) == "MK-CHARLIE")
    assert charlie["slide_id"] is None, "the id-less legacy row was given an id"

    assert [s["slide_id"] for s in result["slides"]] == row_ids
    assert result["inserted_slide_id"] == row_ids[landed]
    assert result["inserted_slide_id"], "the new slide has no id"
    assert result["inserted_position"] == landed
    assert result["slide_count"] == 4
    assert _project(result["slides"]) == _project(_fresh_load(factory)["slides"]), (
        "the response is not the deck as it now loads from the database"
    )


def test_the_new_slide_id_is_minted_by_this_modules_uuid4(
    factory, service, seeded, monkeypatch
):
    """D8: ``object_id`` is the new id, minted in chat_service by ``uuid.uuid4()``.

    ``chat_service.uuid`` IS the global module, so the row writer's internal row id
    consumes values too (C11): a sequence is patched, and the slide's id must be
    its FIRST value, the same on the row, in the response and on the one mutation
    event.  The deck is cached first, so nothing before the mint consumes one.
    """
    service._get_or_load_deck(OWNER_SID)
    sequence = [uuid.uuid4() for _ in range(256)]
    monkeypatch.setattr(chat_service_module.uuid, "uuid4", iter(sequence).__next__)
    events_before = _mutation_events(factory)

    result = service.insert_slide(OWNER_SID, 1)

    minted = str(sequence[0])
    assert result["inserted_slide_id"] == minted
    assert _rows(factory, seeded["owner_pk"])[1]["slide_id"] == minted
    new_events = _mutation_events(factory)[len(events_before):]
    assert new_events == [("insert_slide", "deck", minted, seeded["owner_pk"])], (
        f"expected exactly one insert_slide event naming the new slide: {new_events}"
    )


def test_inserted_by_reaches_the_usage_event_and_none_writes_none(factory, service, seeded):
    """The usage event carries the route's user and the REQUESTING session's pk
    (a contributor here); without ``inserted_by`` there is none, while the
    mutation event is still written."""
    service.insert_slide(OWNER_SID, 1)
    assert _usage_events(factory) == []
    assert [e[0] for e in _mutation_events(factory)] == ["insert_slide"]

    service.insert_slide(CONTRIB_SID, 2, inserted_by=INSERTED_BY)

    assert _usage_events(factory) == [(INSERTED_BY, EVENT_TYPE, seeded["contrib_pk"])]
    assert [e[0] for e in _mutation_events(factory)] == ["insert_slide", "insert_slide"]
    assert _mutation_events(factory)[1][3] == seeded["contrib_pk"]


def test_the_deck_blob_written_with_the_rows_names_the_same_slides(factory, service, seeded):
    """The writer stores the service's planned deck as ``deck_json`` and its knit as
    ``html_content`` beside the rows.  ``deck_json`` is what a duplicated session is
    built from (it copies the blob, not the rows) and what a row-less deck is
    materialised from, so it must name the same slides, in the same order, as the
    rows: the post-insert deck, with the id-less legacy row still id-less (no
    reindex of the plan) and the new slide under the id the row carries."""
    service.insert_slide(OWNER_SID, 1)

    rows = _rows(factory, seeded["owner_pk"])
    deck = _deck_row(factory, seeded["owner_pk"])
    blob = json.loads(deck["deck_json"])["slides"]
    assert [(s.get("slide_id"), s.get("html")) for s in blob] == [
        (r["slide_id"], r["html"]) for r in rows
    ], "deck_json disagrees with the rows it was written beside"
    assert deck["slide_count"] == 4
    assert list(dict.fromkeys(_MARKER_RE.findall(deck["html_content"]))) == MARKERS, (
        "html_content is not the knit of the post-insert deck"
    )
    assert deck["html_content"].count('<div class="slide"></div>') == 1


def test_a_reload_failure_after_the_commit_still_answers_the_insert(
    factory, service, seeded, monkeypatch
):
    """The insert is committed before the deck is reloaded.  If the reload fails,
    the request must not turn into a 500 (the viewer would retry and insert a
    second slide): it answers the deck it planned, which names exactly the rows
    now written, takes the one save point from it, and leaves this worker's cache
    empty so the next load is the database's deck."""
    real = service._get_or_load_deck
    calls: List[str] = []

    def flaky(session_id):
        calls.append(session_id)
        if len(calls) == 2:  # the reload after the commit
            raise RuntimeError("database hiccup on reload")
        return real(session_id)

    monkeypatch.setattr(service, "_get_or_load_deck", flaky)
    points_before = _save_points(factory, seeded["owner_pk"])

    result = service.insert_slide(OWNER_SID, 1)

    assert len(calls) == 2, f"the reload is not on the executed path: {calls}"
    rows = _rows(factory, seeded["owner_pk"])
    row_ids = [r["slide_id"] for r in rows]
    assert [_marker(r["html"]) for r in rows] == ["MK-ALPHA", None, "MK-BRAVO", "MK-CHARLIE"]
    assert [s.get("slide_id") for s in result["slides"]] == row_ids, (
        "the fallback answer names slides the rows do not"
    )
    assert [_marker(s["html"]) for s in result["slides"]] == [_marker(r["html"]) for r in rows]
    assert result["inserted_slide_id"] == row_ids[1]
    assert result["inserted_position"] == 1

    points = _save_points(factory, seeded["owner_pk"])
    assert len(points) == len(points_before) + 1
    assert points[-1]["description"] == "Inserted slide 2"
    assert [s.get("slide_id") for s in points[-1]["deck"]["slides"]] == row_ids

    monkeypatch.undo()
    assert _cached_markers(service) == ["MK-ALPHA", None, "MK-BRAVO", "MK-CHARLIE"]


# ---------------------------------------------------------------------------
# No ghost: a refused write leaves neither the database nor the cache changed
# ---------------------------------------------------------------------------

_WRITER_REFUSALS: Dict[str, Callable[[], Exception]] = {
    "version_conflict": lambda: VersionConflictError(
        current_version=DECK_VERSION + 1, expected_version=DECK_VERSION
    ),
    "rows_changed": lambda: session_manager.SlideRowsChangedError("rows moved"),
    "deck_busy": lambda: session_manager.DeckBusyError("a turn holds the deck"),
    "arc_review": lambda: ArcReviewInFlightError(OWNER_SID),
}


@pytest.mark.parametrize("refusal", sorted(_WRITER_REFUSALS))
def test_a_refused_write_leaves_no_ghost_in_the_cache(
    factory, service, seeded, monkeypatch, refusal
):
    """The writer refuses (each of its four refusals): the error reaches the
    caller as is (the route maps each type), nothing is written, the deck object
    another request in this worker already holds is untouched (D12: the insert is
    built on a copy), and the next load shows the original slides."""
    held = service._get_or_load_deck(OWNER_SID)
    held_before = [(s.slide_id, s.html) for s in held.slides]
    error = _WRITER_REFUSALS[refusal]()
    calls: List[str] = []

    def refuse(self, session_id, position, **kwargs):
        calls.append(session_id)
        raise error

    monkeypatch.setattr(SessionManager, "insert_slide", refuse)
    before = _db_state(factory)

    with pytest.raises(type(error)) as raised:
        service.insert_slide(OWNER_SID, 1)

    assert raised.value is error
    assert calls == [OWNER_SID], "the insert never reached the writer"
    assert _db_state(factory) == before
    assert [(s.slide_id, s.html) for s in held.slides] == held_before, (
        "the cached deck was mutated before the write"
    )
    assert _cached_markers(service) == MARKERS


@pytest.mark.parametrize("refusal", sorted(_WRITER_REFUSALS))
def test_after_a_refused_write_the_next_load_is_fresh_from_the_database(
    factory, service, seeded, monkeypatch, refusal
):
    """The cache is invalidated on EVERY exit.  The cached deck is corrupted in
    place first (as a failed update/duplicate, which still mutate the cache before
    writing, would leave it): after the refusal the next load is the database's
    deck, not the corrupted one."""
    held = service._get_or_load_deck(OWNER_SID)
    held.slides.append(Slide(html=_bare_html("MK-GHOST", 3), slide_id="sid-ghost"))
    error = _WRITER_REFUSALS[refusal]()

    def refuse(self, session_id, position, **kwargs):
        raise error

    monkeypatch.setattr(SessionManager, "insert_slide", refuse)

    with pytest.raises(type(error)):
        service.insert_slide(OWNER_SID, 1)

    assert _cached_markers(service) == MARKERS, (
        "the cache still serves the corrupted deck after the refused insert"
    )


@pytest.mark.parametrize("corruption", ["appended_ghost", "edited_in_place"])
def test_a_stale_rows_409_heals_on_the_immediate_retry(
    factory, service, seeded, corruption
):
    """m11: the cached deck no longer matches the rows (a failed update/duplicate
    mutated it), so the real writer refuses with SlideRowsChangedError and writes
    nothing.  The same request, retried at once, succeeds with the right rows and
    no trace of the corruption."""
    held = service._get_or_load_deck(OWNER_SID)
    if corruption == "appended_ghost":
        held.slides.append(Slide(html=_bare_html("MK-GHOST", 3), slide_id="sid-ghost"))
    else:
        held.slides[1].html = _bare_html("MK-GHOST", 1)
    before = _db_state(factory)

    with pytest.raises(session_manager.SlideRowsChangedError):
        service.insert_slide(OWNER_SID, 1)
    assert _db_state(factory) == before

    result = service.insert_slide(OWNER_SID, 1)

    rows = _rows(factory, seeded["owner_pk"])
    assert [_marker(r["html"]) for r in rows] == ["MK-ALPHA", None, "MK-BRAVO", "MK-CHARLIE"]
    assert rows[1]["html"] == BARE_BLANK
    assert [s["slide_id"] for s in result["slides"]] == [r["slide_id"] for r in rows]
    by_marker = {_marker(r["html"]): _whole(r) for r in rows if _marker(r["html"])}
    assert by_marker == _seed_rows_whole("bare")


# ---------------------------------------------------------------------------
# Multi-worker coherence: two ChatServices, one database
# ---------------------------------------------------------------------------


def test_a_worker_that_cached_the_deck_loads_another_workers_insert(
    factory, service, seeded
):
    worker_a = service
    worker_b = ChatService()
    assert _cached_markers(worker_a) == MARKERS

    result = worker_b.insert_slide(OWNER_SID, 1)

    deck = worker_a._get_or_load_deck(OWNER_SID)
    assert [_marker(s.html) for s in deck.slides] == ["MK-ALPHA", None, "MK-BRAVO", "MK-CHARLIE"]
    assert deck.slides[1].slide_id == result["inserted_slide_id"]


def test_a_stale_worker_gets_a_409_and_cannot_write_its_stale_deck_back(
    factory, service, seeded, monkeypatch
):
    """Worker A cached the 3-slide deck; worker B inserted.  A's version probe is
    made to report A's own (stale) version, so A plans against its stale cache.
    The writer re-reads the rows and refuses: SlideRowsChangedError, nothing
    written (B's insert survives whole), and A's next load is fresh even with the
    probe still lying, because the refused insert dropped A's cache."""
    worker_a = service
    worker_b = ChatService()
    worker_a._get_or_load_deck(OWNER_SID)
    stale_version = worker_a._deck_versions()[OWNER_SID]

    b_result = worker_b.insert_slide(OWNER_SID, 1)
    after_b = _db_state(factory)
    monkeypatch.setattr(worker_a, "_get_deck_version", lambda session_id: stale_version)

    with pytest.raises(session_manager.SlideRowsChangedError):
        worker_a.insert_slide(OWNER_SID, 0)

    assert _db_state(factory) == after_b, "the stale worker wrote to the database"
    deck = worker_a._get_or_load_deck(OWNER_SID)
    assert [s.slide_id for s in deck.slides] == [
        r["slide_id"] for r in _rows(factory, seeded["owner_pk"])
    ]
    assert deck.slides[1].slide_id == b_result["inserted_slide_id"]
