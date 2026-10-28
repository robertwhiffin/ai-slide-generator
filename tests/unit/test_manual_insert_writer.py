"""``SessionManager.insert_slide``: the manual insert's one transaction (#314 follow-up, Task 2).

An editor inserting a blank slide from the viewer shifts every later slide by one.
The shift is where a slide's identity, authorship, timestamps, verification record
and spec fragment can quietly end up on a different slide (executing-plans-tellr §7),
so this writer moves rows with the EXACT old-row map, never the attribution heuristic,
and writes rows, spec, deck columns and evidence in ONE ``get_db_session()``
(plan D2, D3, D7, D8, D13; PLAN-CORRECTIONS C7-C11, C22).

How the assertions are made:

* An existing slide is found by the marker in its own HTML and compared as a WHOLE
  row: every column except ``position`` and ``id``, NULL authorship and NULL
  timestamps included.  Never by position or count alone.
* Two id-less rows with identical HTML cannot carry a marker in their HTML, so they
  carry one in their verification record and spec fragment, and differ in authorship.
* Every refusal compares a byte-level snapshot of every table the writer could touch
  (rows, decks, sessions, both event tables) before and after.
* Oracles are written out, not computed by the code under test (the blank spec entry,
  the event type string).

The row-less legacy deck (D13) follows the supervisor's ruling on C7: it is
materialised the way the startup backfill materialises it (raw emails, NULL
timestamps kept, verdicts migrated from ``verification_map``, css/external_scripts/
head_meta lifted into their columns), then takes the rows path, except that its
fresh rows are compared with ``expected_rows`` by content hash, in order, only (the
whole-branch review's MINOR-2: a blob slide with no ``slide_id`` key).  Its refusals
must leave no rows behind either.

New symbols are read off their module at use (``session_manager.DeckBusyError``,
``usage_event.EVENT_SLIDE_INSERTED``), so before the implementation each test is red
on its own missing symbol instead of the whole module failing to import.

``get_slide_deck`` runs outside ``graph_env``, so the SCIM display-name lookup is
always patched (a real WorkspaceClient retries and hangs).
"""
from __future__ import annotations

import contextlib
import copy
import inspect
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import src.api.services.session_manager as session_manager
import src.api.services.slide_repository as slide_repository
import src.database.models  # noqa: F401 — register every ORM model
import src.database.models.usage_event as usage_event
from src.api.services.chat_service import ArcReviewInFlightError
from src.api.services.session_manager import (
    SessionManager,
    SessionNotFoundError,
    VersionConflictError,
)
from src.core.database import Base
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.database.models.usage_event import UsageEvent
from src.domain.deck_spec import DeckSpec
from src.domain.finding import VERDICT_KEY, Finding, make_finding_id
from src.services.shared_deck_attribution import DeckMutationContext, MutationActor
from src.services.spec_sync import CLAIM_TTL_SECONDS
from src.utils.slide_hash import compute_slide_hash

OWNER_SID = "manual-insert-owner"
CONTRIB_SID = "manual-insert-contributor"
SECOND_CONTRIB_SID = "manual-insert-second-contributor"
STRANGER_SID = "manual-insert-unrelated-deck"

#: The editor who inserts (the route's ``get_current_user()``).
INSERTER = "inserter@test.com"
#: The new slide's id (minted by ChatService with uuid4; any unique string here).
NEW_SID = "sid-NEW-manual-insert"
NEW_STAMP = "2026-10-21T09:15:30.123456Z"
NEW_STAMP_DT = datetime(2026, 10, 21, 9, 15, 30, 123456)

#: Written out, not imported: the oracle must not depend on the code under test.
BLANK_HTML = '<div class="slide"></div>'
EVENT_TYPE = "slide_inserted"


def _blank_entry(position: int) -> Dict[str, Any]:
    return {
        "position": position,
        "purpose": "",
        "content_brief": "",
        "assumes": "",
        "hands_off": "",
        "data_references": [],
    }


#: What the caller hands the writer for the deck-level columns AFTER the insert.
TITLE_AFTER = "Title after the insert"
KNIT_AFTER = "<html>KNIT-AFTER-INSERT</html>"
SCRIPTS_AFTER = "/* SCRIPTS-AFTER-INSERT */"

#: The deck's presentation columns.  The two JSON columns are seeded with
#: NON-canonical spacing, so a json.dumps rewrite shows even when the values agree.
COLUMN_CSS = ".slide { background: #0b1f3a; } /* COLUMN-CSS */"
COLUMN_EXT = '[ "https://cdn.jsdelivr.net/npm/chart.js" ]'
COLUMN_HEAD = '{ "viewport": "width=1280, initial-scale=1" }'
#: The cached deck's copies, deliberately different from the columns: on the rows
#: path the columns are the authority and the writer must not write these back.
CACHED_CSS = "/* CACHED-CSS: must not be written back on the rows path */"
CACHED_EXT = ["https://cdn.example/cached-only.js"]
CACHED_HEAD = {"viewport": "width=999"}

_MARKER_RE = re.compile(r"MK-[A-Z]+")

#: The main seed, in position order: four real slides, a failed placeholder with a
#: NULL author (commit_placeholder's shape) and a backfilled id-less row with NULL
#: timestamps.  Inserting at 1 moves every row except ALPHA.
SIX = ("MK-ALPHA", "MK-BRAVO", "MK-FAILED", "MK-CHARLIE", "MK-BACKFILL", "MK-DELTA")


# ---------------------------------------------------------------------------
# Fixtures (self-contained, in the style of test_insert_pending_slides.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    # autoflush=False, as production (src/core/database.py): nothing here may
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


@contextlib.contextmanager
def _patched(factory, *, calls: Optional[List[int]] = None, names=None):
    """Every get_db_session the writer could reach points at this test's engine.

    deck_level_writer is patched too, so a writer that sneaks the spec through its
    own transaction is counted (and is visible) rather than hitting another DB.
    """
    names = names if names is not None else {}
    fake = _fake_db(factory, calls)
    with patch("src.api.services.session_manager.get_db_session", fake), patch(
        "src.api.services.slide_repository.get_db_session", fake
    ), patch("src.api.services.deck_level_writer.get_db_session", fake), patch(
        "src.services.identity_provider.resolve_display_names",
        lambda emails: {e: names[e] for e in emails if e in names},
    ):
        yield


# ---------------------------------------------------------------------------
# Seed rows
# ---------------------------------------------------------------------------


def _real_html(marker: str) -> str:
    return f'<div class="slide"><h1>{marker}</h1><p>its own body text</p></div>'


def _failed_html(marker: str) -> str:
    """commit_placeholder's HTML, with the marker in data-error."""
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


def _finding_for(html: str, position: int, marker: str) -> Finding:
    return Finding(
        id=make_finding_id("overflow", compute_slide_hash(html), 0),
        slide_index=position,
        category="design",
        criterion="overflow",
        message=f"FINDING-{marker}",
        objective=True,
    )


def _two_hash_record(marker: str, html: str, position: int) -> str:
    """History + current verdicts; the current one carries a tellr_review finding."""
    current = compute_slide_hash(html)
    history = compute_slide_hash(f"<p>an earlier draft of {marker}</p>")
    return json.dumps(
        {
            history: {"score": 41, "rating": "poor", "explanation": f"HISTORY-{marker}"},
            current: {
                "score": 92,
                "rating": "good",
                "explanation": f"CURRENT-{marker}",
                VERDICT_KEY: {
                    "verdict": "surfaced",
                    "findings": [_finding_for(html, position, marker).model_dump()],
                },
            },
        }
    )


def _real_row(marker: str, position: int, day: int) -> Dict[str, Any]:
    html = _real_html(marker)
    return {
        "html": html,
        "slide_id": f"sid-{marker}",
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
    return {
        "html": html,
        "slide_id": "sid-failed-placeholder",
        "scripts": "",
        "created_by": None,
        "created_at": datetime(2024, 3, 1, 8, 0, 0),
        "modified_by": None,
        "modified_at": datetime(2024, 3, 1, 8, 0, 0),
        "verification_record": json.dumps(
            {compute_slide_hash(html): {"error": True, "message": f"{marker} build crashed"}}
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


def _spec_dict(markers: Sequence[str], positions: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """A valid DeckSpec, one entry per marker, each entry naming its slide."""
    positions = list(positions) if positions is not None else list(range(len(markers)))
    return {
        "title": "Prior",
        "audience": "aud",
        "purpose": "pur",
        "argument": "arg",
        "call_to_action": "cta",
        "narrative_arc": ["open", "close"],
        "design_contract": {},
        "resolved_data": {"synthesis": "syn", "figures": [], "gaps": []},
        "slides": [
            {
                "position": p,
                "purpose": f"SPEC-{m}",
                "content_brief": f"spec brief for {m}",
                "assumes": "",
                "hands_off": "",
                "data_references": [f"ref-{m}"],
            }
            for m, p in zip(markers, positions)
        ],
    }


def _spec_json(markers: Sequence[str], positions: Optional[Sequence[int]] = None) -> str:
    spec = _spec_dict(markers, positions)
    # Validated through DeckSpec so the seed is a spec the app could have written.
    assert DeckSpec.model_validate(spec) is not None
    return json.dumps(spec)


_DEFAULT = object()


def _seed(
    factory,
    rows: Dict[int, Dict[str, Any]],
    *,
    with_deck: bool = True,
    spec: Any = _DEFAULT,
    version: int = 5,
    contributors: int = 0,
    stranger: bool = False,
    deck_columns: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Owner session (pinned to a real GraphRelease), its deck and the given rows.

    ``rows`` maps position -> column values, so a gapped deck can be seeded.
    """
    db = factory()
    try:
        release = GraphRelease(
            version_number=1,
            release_note="manual-insert fixture",
            published_by="test",
            published_at=datetime(2026, 9, 1, 9, 0, 0),
            effective_from=datetime(2026, 9, 1, 9, 0, 0),
            effective_to=None,
        )
        db.add(release)
        db.flush()
        owner = UserSession(
            session_id=OWNER_SID, created_by="owner@test.com", graph_release_id=release.id
        )
        db.add(owner)
        db.flush()
        pks: Dict[str, Any] = {"owner_pk": owner.id, "release_id": release.id}
        for index, sid in enumerate((CONTRIB_SID, SECOND_CONTRIB_SID)[:contributors]):
            contrib = UserSession(
                session_id=sid,
                created_by=f"contributor-{index}@test.com",
                parent_session_id=owner.id,
                graph_release_id=release.id,
            )
            db.add(contrib)
            db.flush()
            pks["contrib_pk" if index == 0 else "second_contrib_pk"] = contrib.id
        if stranger:
            other = UserSession(
                session_id=STRANGER_SID,
                created_by="stranger@test.com",
                graph_release_id=release.id,
            )
            db.add(other)
            db.flush()
            pks["stranger_pk"] = other.id
        if with_deck:
            markers = [_marker(r["html"]) for _, r in sorted(rows.items())]
            columns: Dict[str, Any] = {
                "title": "Seeded deck",
                "html_content": "<html>KNIT-BEFORE</html>",
                "scripts_content": "/* SCRIPTS-BEFORE */",
                "slide_count": len(rows),
                # A STALE blob (one slide): when rows exist they are the truth, and
                # the rows path must not consult, backfill from or prune to it.
                "deck_json": json.dumps(
                    {"slides": [{"html": '<div class="slide"><p>STALE BLOB</p></div>'}]}
                ),
                "deck_spec_json": (
                    _spec_json([m or "UNMARKED" for m in markers]) if spec is _DEFAULT else spec
                ),
                "version": version,
                "modified_by": "previous-editor@test.com",
                "css": COLUMN_CSS,
                "external_scripts_json": COLUMN_EXT,
                "head_meta_json": COLUMN_HEAD,
            }
            columns.update(deck_columns or {})
            db.add(SessionSlideDeck(session_id=owner.id, **columns))
            db.flush()
        for position, values in rows.items():
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=f"row-{owner.id}-{position}",
                    **values,
                )
            )
        db.commit()
        return pks
    finally:
        db.close()


def _seed_six(factory, **kw) -> Dict[str, Any]:
    return _seed(factory, {p: _row_for(m, p) for p, m in enumerate(SIX)}, **kw)


def _set_processing(factory, session_id: str, started_seconds_ago: Optional[float]) -> None:
    """A turn holds *session_id*'s processing lock (``acquire_session_lock``'s write)."""
    db = factory()
    try:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        row.is_processing = True
        row.processing_started_at = (
            None
            if started_seconds_ago is None
            else datetime.utcnow() - timedelta(seconds=started_seconds_ago)
        )
        db.commit()
    finally:
        db.close()


def _set_claim(factory, owner_pk: int, claim_age_seconds: float) -> None:
    """An arc review's lease on the owner's deck (``claim_due_marker``'s write)."""
    now = datetime.utcnow()
    db = factory()
    try:
        deck = db.query(SessionSlideDeck).filter(SessionSlideDeck.session_id == owner_pk).one()
        deck.spec_dirty_at = now - timedelta(seconds=claim_age_seconds + 120)
        deck.spec_dirty_by = "earlier-editor@test.com"
        deck.spec_dirty_claimed_at = now - timedelta(seconds=claim_age_seconds)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Reading the database back
# ---------------------------------------------------------------------------

_SLIDE_COLUMNS = [c.name for c in SessionSlide.__table__.columns]
_JSON_COLUMNS = ("verification_record", "deck_spec_slide")


def _decoded(row: SessionSlide) -> Dict[str, Any]:
    """EVERY column of the row; the two JSON columns parsed."""
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


def _marker(html: Optional[str]) -> Optional[str]:
    found = _MARKER_RE.findall(html or "")
    assert len(found) <= 1, f"a row's HTML carries more than one marker: {found}"
    return found[0] if found else None


def _by_marker(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        marker = _marker(row["html"])
        if marker is None:
            continue
        assert marker not in out, f"two rows carry {marker}: the insert duplicated a slide"
        out[marker] = row
    return out


def _identity(row: Dict[str, Any]) -> Dict[str, Any]:
    """The whole row minus the two columns a shift legitimately changes."""
    return {k: v for k, v in row.items() if k not in ("position", "id")}


def _layout(rows: List[Dict[str, Any]], new_sid: str = NEW_SID) -> List[str]:
    """Position-ordered markers; the inserted row shows as NEW."""
    out = []
    for r in rows:
        marker = _marker(r["html"])
        out.append(marker or ("NEW" if r["slide_id"] == new_sid else "UNMARKED"))
    return out


def _all_columns(model, rows) -> List[Dict[str, Any]]:
    return [{c.name: getattr(r, c.name) for c in model.__table__.columns} for r in rows]


def _db_state(factory) -> Dict[str, Any]:
    """Byte-level snapshot of every table a refused insert must leave alone."""
    db = factory()
    try:
        return {
            "slides": _all_columns(
                SessionSlide,
                db.query(SessionSlide)
                .order_by(SessionSlide.session_id, SessionSlide.position)
                .all(),
            ),
            "decks": _all_columns(
                SessionSlideDeck, db.query(SessionSlideDeck).order_by(SessionSlideDeck.id).all()
            ),
            "sessions": _all_columns(
                UserSession, db.query(UserSession).order_by(UserSession.id).all()
            ),
            "mutation_events": _all_columns(
                SharedDeckMutationEvent,
                db.query(SharedDeckMutationEvent).order_by(SharedDeckMutationEvent.id).all(),
            ),
            "usage_events": _all_columns(
                UsageEvent, db.query(UsageEvent).order_by(UsageEvent.id).all()
            ),
        }
    finally:
        db.close()


def _assert_unchanged(factory, state: Dict[str, Any]) -> None:
    after = _db_state(factory)
    for table in state:
        assert after[table] == state[table], (
            f"a refused insert changed {table}:\n before {state[table]}\n after  {after[table]}"
        )


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


def _mutation_events(factory) -> List[Tuple[Any, ...]]:
    db = factory()
    try:
        return [
            (
                e.operation,
                e.object_type,
                e.actor_session_id,
                e.root_session_id,
                e.graph_release_id,
                e.object_id,
            )
            for e in db.query(SharedDeckMutationEvent).order_by(SharedDeckMutationEvent.id).all()
        ]
    finally:
        db.close()


def _usage_events(factory) -> List[Tuple[Any, ...]]:
    db = factory()
    try:
        return [
            (e.event_type, e.username, e.session_id)
            for e in db.query(UsageEvent).order_by(UsageEvent.id).all()
        ]
    finally:
        db.close()


def _last_activity(factory) -> Dict[str, datetime]:
    db = factory()
    try:
        return {s.session_id: s.last_activity for s in db.query(UserSession).all()}
    finally:
        db.close()


def _expected_rows(rows: List[Dict[str, Any]]) -> List[Tuple[Optional[str], str]]:
    return [(r["slide_id"], compute_slide_hash(r["html"])) for r in rows]


# ---------------------------------------------------------------------------
# Calling the writer
# ---------------------------------------------------------------------------


def _new_slide(
    *,
    html: str = BLANK_HTML,
    slide_id: str = NEW_SID,
    author: Optional[str] = INSERTER,
) -> Dict[str, Any]:
    """What ChatService hands the writer: the new Slide as a dict, stamped."""
    slide: Dict[str, Any] = {"html": html, "slide_id": slide_id, "scripts": ""}
    if author:
        slide.update(
            created_by=author,
            created_at=NEW_STAMP,
            modified_by=author,
            modified_at=NEW_STAMP,
        )
    else:
        slide.update(created_at=NEW_STAMP, modified_at=NEW_STAMP)
    return slide


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


def _deck_dict_for(
    before: List[Dict[str, Any]], position: int, slide: Dict[str, Any]
) -> Dict[str, Any]:
    """The cached deck after the in-memory insert (``working.to_dict()``'s shape)."""
    slides: List[Dict[str, Any]] = []
    for r in before:
        s: Dict[str, Any] = {"html": r["html"], "slide_id": r["slide_id"], "scripts": r["scripts"]}
        for key in ("created_by", "modified_by"):
            if r[key]:
                s[key] = r[key]
        for key in ("created_at", "modified_at"):
            if r[key]:
                s[key] = _iso(r[key])
        slides.append(s)
    slides.insert(max(0, min(position, len(slides))), copy.deepcopy(slide))
    for index, s in enumerate(slides):
        s["index"] = index
    return {
        "title": TITLE_AFTER,
        "slide_count": len(slides),
        "css": CACHED_CSS,
        "external_scripts": list(CACHED_EXT),
        "scripts": SCRIPTS_AFTER,
        "slides": slides,
        "head_meta": dict(CACHED_HEAD),
    }


def _mutation(
    session_id: str,
    release_id: Optional[int],
    *,
    operation: str = "insert_slide",
    object_type: str = "deck",
    object_id: str = NEW_SID,
) -> DeckMutationContext:
    """``SessionManager.deck_mutation_context``'s shape for the insert."""
    return DeckMutationContext(
        actor=MutationActor(session_id, release_id),
        operation=operation,
        object_type=object_type,
        object_id=object_id,
        suppress_nested_events=True,
    )


def _insert(
    factory,
    position: int,
    *,
    before: List[Dict[str, Any]],
    release_id: Optional[int],
    session_id: str = OWNER_SID,
    slide: Optional[Dict[str, Any]] = None,
    expected_rows: Optional[Sequence[Tuple[Optional[str], str]]] = None,
    deck_dict: Optional[Dict[str, Any]] = None,
    expected_version: Optional[int] = None,
    inserted_by: Optional[str] = INSERTER,
    mutation: Optional[DeckMutationContext] = None,
    calls: Optional[List[int]] = None,
    names: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    slide = slide if slide is not None else _new_slide()
    with _patched(factory, calls=calls, names=names):
        return SessionManager().insert_slide(
            session_id,
            position,
            slide=slide,
            expected_rows=_expected_rows(before) if expected_rows is None else expected_rows,
            deck_dict=(
                deck_dict if deck_dict is not None else _deck_dict_for(before, position, slide)
            ),
            title=TITLE_AFTER,
            html_content=KNIT_AFTER,
            scripts_content=SCRIPTS_AFTER,
            mutation=mutation or _mutation(session_id, release_id, object_id=slide["slide_id"]),
            expected_version=expected_version,
            inserted_by=inserted_by,
        )


def _insert_six(factory, position: int = 1, **kw):
    """Seed SIX, snapshot, insert; return (seed, before, result)."""
    seed_kw = {k: kw.pop(k) for k in list(kw) if k in ("contributors", "spec", "stranger")}
    seed = _seed_six(factory, **seed_kw)
    before = _rows(factory, seed["owner_pk"])
    result = _insert(factory, position, before=before, release_id=seed["release_id"], **kw)
    return seed, before, result


def _assert_every_old_row_intact(before, after) -> None:
    old, new = _by_marker(before), _by_marker(after)
    assert set(new) == set(old), (
        f"a slide was lost or invented by the insert: before {sorted(old)}, after {sorted(new)}"
    )
    for marker, snapshot in old.items():
        assert _identity(new[marker]) == _identity(snapshot), (
            f"{marker} changed across the insert (every column but position/id must "
            f"follow the slide):\n before {_identity(snapshot)}\n after  {_identity(new[marker])}"
        )


def _assert_new_row(row: Dict[str, Any], *, html: str = BLANK_HTML) -> None:
    assert _identity(row) == {
        "session_id": row["session_id"],
        "html": html,
        "slide_id": NEW_SID,
        "scripts": "",
        "created_by": INSERTER,
        "created_at": NEW_STAMP_DT,
        "modified_by": INSERTER,
        "modified_at": NEW_STAMP_DT,
        "verification_record": None,
        "deck_spec_slide": None,
    }, f"the inserted row is not exactly the given slide with no record or fragment: {row}"


# ---------------------------------------------------------------------------
# Insert at 1: rows, the new row, spec, deck columns, evidence, findings
# ---------------------------------------------------------------------------

LAYOUT_AT_1 = [
    "MK-ALPHA",
    "NEW",
    "MK-BRAVO",
    "MK-FAILED",
    "MK-CHARLIE",
    "MK-BACKFILL",
    "MK-DELTA",
]


def test_insert_at_1_keeps_every_old_row_whole_by_marker(factory):
    seed, before, _result = _insert_six(factory, 1)
    after = _rows(factory, seed["owner_pk"])

    assert _layout(after) == LAYOUT_AT_1, f"not the planned layout: {_layout(after)}"
    assert [r["position"] for r in after] == list(range(7))
    _assert_every_old_row_intact(before, after)


def test_null_authorship_and_null_timestamps_stay_null(factory):
    """No moved row gets a fabricated author or a fresh timestamp (D2, AC4)."""
    seed, _before, _result = _insert_six(factory, 1)
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


def test_the_new_row_is_exactly_the_given_slide_with_no_record_and_no_fragment(factory):
    seed, _before, _result = _insert_six(factory, 1)
    after = _rows(factory, seed["owner_pk"])

    new_rows = [r for r in after if r["slide_id"] == NEW_SID]
    assert len(new_rows) == 1 and new_rows[0]["position"] == 1, (
        f"expected one inserted row at 1: {[(r['position'], r['slide_id']) for r in after]}"
    )
    _assert_new_row(new_rows[0])


def test_the_spec_gains_a_blank_entry_and_every_later_entry_shifts_whole(factory):
    seed, _before, _result = _insert_six(factory, 1)
    prior = _spec_dict(SIX)
    spec = json.loads(_deck(factory, seed["owner_pk"]).deck_spec_json)

    assert {k: v for k, v in spec.items() if k != "slides"} == {
        k: v for k, v in prior.items() if k != "slides"
    }, "the insert changed a spec field other than slides"
    assert spec["slides"][1] == _blank_entry(1), f"entry 1 is not blank: {spec['slides'][1]}"
    expected = [dict(prior["slides"][0])]
    expected.append(_blank_entry(1))
    for old in prior["slides"][1:]:
        expected.append({**old, "position": old["position"] + 1})
    assert spec["slides"] == expected, (
        "later entries must be the same entries, position + 1 and nothing else"
    )
    assert DeckSpec.from_json(json.dumps(spec)) is not None, "the spliced spec no longer validates"


def test_the_deck_columns_are_the_arguments_and_the_presentation_columns_are_untouched(factory):
    seed, before, result = _insert_six(factory, 1)
    deck = _deck(factory, seed["owner_pk"])
    deck_dict = _deck_dict_for(before, 1, _new_slide())

    assert deck.title == TITLE_AFTER
    assert deck.html_content == KNIT_AFTER
    assert deck.scripts_content == SCRIPTS_AFTER
    assert deck.slide_count == 7
    assert json.loads(deck.deck_json) == deck_dict, "deck_json is not the deck_dict argument"
    assert deck.version == 6, f"one bump, from 5: {deck.version}"
    assert deck.modified_by == INSERTER
    # D2 step 6: on the rows path the presentation columns are NOT touched, byte for
    # byte, although deck_dict carries other values (m11).
    assert deck.css == COLUMN_CSS
    assert deck.external_scripts_json == COLUMN_EXT
    assert deck.head_meta_json == COLUMN_HEAD

    keys = ("session_id", "version", "position", "slide_id", "slide_count")
    assert {k: result.get(k) for k in keys} == {
        "session_id": OWNER_SID,
        "version": 6,
        "position": 1,
        "slide_id": NEW_SID,
        "slide_count": 7,
    }, f"unexpected return value: {result}"


def test_exactly_one_mutation_event_and_one_usage_event(factory):
    seed, _before, _result = _insert_six(factory, 1)

    assert _mutation_events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"], NEW_SID)
    ], f"expected one insert_slide/deck event naming the new slide: {_mutation_events(factory)}"
    assert _usage_events(factory) == [(EVENT_TYPE, INSERTER, seed["owner_pk"])], (
        f"expected exactly one slide_inserted usage event: {_usage_events(factory)}"
    )


def test_the_event_type_constant(factory):
    assert usage_event.EVENT_SLIDE_INSERTED == EVENT_TYPE


def test_findings_show_on_their_own_slide_after_the_insert(factory):
    """AC4 at the read path: every finding's slideIndex is the index of the slide
    whose content hash its id names.  Matched by finding id (``#334`` added
    plainMessage/plainIssue to the projection, so whole dicts are not compared)."""
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    with _patched(factory):
        ids_before = {f["id"] for f in SessionManager().get_slide_deck(OWNER_SID)["findings"]}
    assert len(ids_before) == 5, f"the seed should show five findings: {ids_before}"

    _insert(factory, 1, before=before, release_id=seed["release_id"])
    with _patched(factory):
        deck = SessionManager().get_slide_deck(OWNER_SID)

    findings = {f["id"]: f for f in deck["findings"]}
    assert set(findings) == ids_before, "a finding was lost or invented by the insert"
    hashes = [s["content_hash"] for s in deck["slides"]]
    for finding_id, finding in findings.items():
        subject_hash = finding_id.split(":")[1]
        assert hashes[finding["slideIndex"]] == subject_hash, (
            f"{finding_id} ({finding['message']}) shows on slide {finding['slideIndex']}, "
            f"whose content is not the slide it was minted for"
        )
    by_message = {f["message"]: f["slideIndex"] for f in findings.values()}
    assert by_message == {
        "FINDING-MK-ALPHA": 0,
        "FINDING-MK-BRAVO": 2,
        "FINDING-MK-CHARLIE": 4,
        "FINDING-MK-BACKFILL": 5,
        "FINDING-MK-DELTA": 6,
    }, by_message


def test_the_insert_is_one_db_session(factory):
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    calls: List[int] = []
    _insert(factory, 1, before=before, release_id=seed["release_id"], calls=calls)
    assert len(calls) == 1, f"the insert opened {len(calls)} db sessions, not one transaction"


# ---------------------------------------------------------------------------
# At 0 and past the end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "position, landed",
    [
        pytest.param(0, 0, id="at-0"),
        pytest.param(6, 6, id="at-the-end"),
        pytest.param(99, 6, id="past-the-end-appends"),
    ],
)
def test_insert_at_the_edges_lands_where_the_slide_really_is(factory, position, landed):
    seed, before, result = _insert_six(factory, position)
    after = _rows(factory, seed["owner_pk"])

    expected_layout = list(SIX)
    expected_layout.insert(landed, "NEW")
    assert _layout(after) == expected_layout
    assert [r["position"] for r in after] == list(range(7))
    _assert_every_old_row_intact(before, after)
    _assert_new_row(after[landed])
    assert result["position"] == landed, f"the returned position is not the landed index: {result}"

    spec = json.loads(_deck(factory, seed["owner_pk"]).deck_spec_json)
    assert [e["position"] for e in spec["slides"]] == list(range(7))
    assert spec["slides"][landed] == _blank_entry(landed)
    others = [e for i, e in enumerate(spec["slides"]) if i != landed]
    assert [e["purpose"] for e in others] == [f"SPEC-{m}" for m in SIX]


def test_a_drifted_spec_is_spliced_at_the_landed_index_not_the_requested_one(factory):
    """D3: the spec is spliced where the slide LANDED.  A spec longer than the deck
    (8 entries, 6 rows) shows the difference on an append past the end."""
    markers = list(SIX) + ["MK-EXTRAONE", "MK-EXTRATWO"]
    seed, _before, result = _insert_six(factory, 99, spec=_spec_json(markers))
    assert result["position"] == 6
    spec = json.loads(_deck(factory, seed["owner_pk"]).deck_spec_json)
    assert [e["purpose"] for e in spec["slides"]] == (
        [f"SPEC-{m}" for m in SIX] + ["", "SPEC-MK-EXTRAONE", "SPEC-MK-EXTRATWO"]
    )
    assert spec["slides"][6] == _blank_entry(6)


def test_both_writers_shift_through_the_one_splice(factory):
    """One shift primitive (§7): the manual insert (via ``_splice_slide_rows``) and
    the graph's ``insert_pending_slides`` (via ``apply_slide_layout``) both call
    ``_lay_out_slide_rows``, the manual insert with exactly
    ``{landed: (slide, {})}`` over the re-read rows."""
    real = session_manager._lay_out_slide_rows
    calls: List[Dict[str, Any]] = []

    def spy(*args, **kwargs):
        bound = dict(inspect.signature(real).bind(*args, **kwargs).arguments)
        # Read inside the transaction: the ORM rows are detached once it closes.
        bound["old_slide_ids"] = [r.slide_id for r in bound["old_rows"]]
        calls.append(bound)
        return real(*args, **kwargs)

    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(session_manager, "_lay_out_slide_rows", spy))
        if hasattr(slide_repository, "_lay_out_slide_rows"):
            stack.enter_context(patch.object(slide_repository, "_lay_out_slide_rows", spy))
        _insert(factory, 1, before=before, release_id=seed["release_id"])
        assert len(calls) == 1, f"the manual insert called _lay_out_slide_rows {len(calls)} times"
        (call,) = calls
        assert call["owner_id"] == seed["owner_pk"]
        assert call["old_slide_ids"] == [r["slide_id"] for r in before]
        assert set(call["new_slides"]) == {1}
        new_slide, record = call["new_slides"][1]
        assert new_slide["slide_id"] == NEW_SID and not record

        calls.clear()
        after = _rows(factory, seed["owner_pk"])
        with _patched(factory):
            slide_repository.SlideWriter(SessionManager()).insert_pending_slides(
                OWNER_SID,
                [0],
                deck_spec=json.dumps(_spec_dict(["MK-PENDING"] + LAYOUT_AT_1)),
                expected_rows=_expected_rows(after),
                created_by="turn-author@test.com",
                mutation=DeckMutationContext(
                    actor=MutationActor(OWNER_SID, seed["release_id"]),
                    operation="insert_slide",
                    object_type="deck",
                ),
            )
        assert len(calls) == 1, "insert_pending_slides does not shift through _lay_out_slide_rows"
        assert set(calls[0]["new_slides"]) == {0}


# ---------------------------------------------------------------------------
# Spec variants (D3; n3)
# ---------------------------------------------------------------------------

_INVALID_SHAPE = {
    "title": "half a spec",
    "x-unknown-key": {"kept": [1, 2]},
    "slides": [
        {"position": 0, "purpose": "P0", "x-extra": "kept"},
        {"position": 2, "purpose": "P2"},
        {"purpose": "no position"},
        "not-a-dict",
    ],
}


@pytest.mark.parametrize(
    "raw, expected",
    [
        pytest.param(None, None, id="null-stays-null"),
        pytest.param("", "", id="empty-string-untouched"),
        pytest.param("{not json", "{not json", id="unparseable-untouched"),
        pytest.param("[]", "[]", id="non-dict-untouched"),
        pytest.param("{}", "{}", id="empty-object-untouched"),
        pytest.param(
            '{"title": "no slides key"}',
            '{"title": "no slides key"}',
            id="no-slides-list-untouched",
        ),
        pytest.param(
            '{"slides": "not a list"}', '{"slides": "not a list"}', id="slides-not-a-list-untouched"
        ),
        pytest.param(
            '{"slides": []}',
            {"slides": [_blank_entry(0)]},
            id="empty-slides-gains-the-entry-at-the-clamp",
        ),
        pytest.param(
            json.dumps(_INVALID_SHAPE),
            {
                "title": "half a spec",
                "x-unknown-key": {"kept": [1, 2]},
                "slides": [
                    {"position": 0, "purpose": "P0", "x-extra": "kept"},
                    _blank_entry(1),
                    {"position": 2, "purpose": "P2"},
                    {"purpose": "no position"},
                    "not-a-dict",
                ],
            },
            id="invalid-shape-renumbered-unknown-keys-kept",
        ),
    ],
)
def test_spec_variants(factory, raw, expected):
    seed, before, _result = _insert_six(factory, 1, spec=raw)
    after = _rows(factory, seed["owner_pk"])
    assert _layout(after) == LAYOUT_AT_1, "a legacy or odd spec must not stop the insert"
    _assert_every_old_row_intact(before, after)

    got = _deck(factory, seed["owner_pk"]).deck_spec_json
    if isinstance(expected, dict):
        assert json.loads(got) == expected
    else:
        assert got == expected, f"the spec column must be left untouched: {got!r}"


# ---------------------------------------------------------------------------
# Atomicity (C9): rows, spec, version and both event tables, or nothing
# ---------------------------------------------------------------------------


def test_a_failing_evidence_write_rolls_back_everything(factory):
    """``session_manager.record_shared_deck_mutation`` raising rolls back the rows,
    the spec, the version, the deck columns and the usage event with it."""
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)

    def _refuse(*args, **kwargs):
        raise RuntimeError("evidence write refused")

    with patch.object(session_manager, "record_shared_deck_mutation", _refuse):
        with pytest.raises(RuntimeError, match="evidence write refused"):
            _insert(factory, 1, before=before, release_id=seed["release_id"])
    _assert_unchanged(factory, state)


def test_a_refused_actor_pin_rolls_back_everything(factory):
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)
    with pytest.raises(ValueError, match="persisted pin"):
        _insert(
            factory,
            1,
            before=before,
            release_id=seed["release_id"],
            mutation=_mutation(OWNER_SID, seed["release_id"] + 1000),
        )
    _assert_unchanged(factory, state)


# ---------------------------------------------------------------------------
# Refusals, each changing nothing (D7)
# ---------------------------------------------------------------------------


def test_a_stale_expected_version_refuses_and_the_current_one_proceeds(factory):
    seed = _seed_six(factory, version=5)
    before = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)

    with pytest.raises(VersionConflictError):
        _insert(factory, 1, before=before, release_id=seed["release_id"], expected_version=4)
    _assert_unchanged(factory, state)

    result = _insert(factory, 1, before=before, release_id=seed["release_id"], expected_version=5)
    assert result["version"] == 6
    assert _layout(_rows(factory, seed["owner_pk"])) == LAYOUT_AT_1


def _mangle_hash(rows):
    out = _expected_rows(rows)
    out[2] = (out[2][0], compute_slide_hash("<p>someone edited this slide</p>"))
    return out


def _mangle_id(rows):
    out = _expected_rows(rows)
    out[3] = ("sid-someone-else", out[3][1])
    return out


def _swap(rows):
    out = _expected_rows(rows)
    out[0], out[1] = out[1], out[0]
    return out


@pytest.mark.parametrize(
    "expected_rows_of",
    [
        pytest.param(_mangle_hash, id="one-content-hash-differs"),
        pytest.param(_mangle_id, id="one-slide-id-differs"),
        pytest.param(lambda rows: _expected_rows(rows)[:-1], id="a-row-was-added-since"),
        pytest.param(
            lambda rows: _expected_rows(rows) + [("sid-x", compute_slide_hash("<p>x</p>"))],
            id="a-row-was-deleted-since",
        ),
        pytest.param(_swap, id="rows-were-reordered-since"),
        pytest.param(lambda rows: [], id="expected-empty-while-rows-exist"),
    ],
)
def test_rows_that_are_not_the_expected_rows_refuse(factory, expected_rows_of):
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)
    with pytest.raises(session_manager.SlideRowsChangedError):
        _insert(
            factory,
            1,
            before=before,
            release_id=seed["release_id"],
            expected_rows=expected_rows_of(before),
        )
    _assert_unchanged(factory, state)


@pytest.mark.parametrize(
    "position, mutation_kw",
    [
        pytest.param(-1, {}, id="negative-position"),
        pytest.param(1, {"operation": "save_deck"}, id="wrong-operation"),
        pytest.param(
            1, {"operation": "write_slide", "object_type": "slide"}, id="wrong-object-type"
        ),
    ],
)
def test_an_invalid_request_refuses_with_value_error(factory, position, mutation_kw):
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)
    with pytest.raises(ValueError):
        _insert(
            factory,
            position,
            before=before,
            release_id=seed["release_id"],
            deck_dict=_deck_dict_for(before, 1, _new_slide()),
            mutation=_mutation(OWNER_SID, seed["release_id"], **mutation_kw),
        )
    _assert_unchanged(factory, state)


def test_a_session_without_a_deck_refuses(factory):
    seed = _seed(factory, {}, with_deck=False)
    state = _db_state(factory)
    with pytest.raises(ValueError, match="No slide deck"):
        _insert(factory, 0, before=[], release_id=seed["release_id"])
    _assert_unchanged(factory, state)


def test_an_unknown_session_refuses(factory):
    seed = _seed_six(factory)
    before = _rows(factory, seed["owner_pk"])
    state = _db_state(factory)
    with pytest.raises(SessionNotFoundError):
        _insert(
            factory, 1, before=before, release_id=seed["release_id"], session_id="no-such-session"
        )
    _assert_unchanged(factory, state)


# ---------------------------------------------------------------------------
# A live arc-review claim on the OWNER's deck (D7 (2))
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requester", [OWNER_SID, CONTRIB_SID], ids=["owner", "contributor"])
def test_a_live_arc_review_claim_on_the_owners_deck_refuses(factory, requester):
    """The claim lives on the OWNER's deck row.  A contributor session owns no deck,
    so a check made with the requesting session instead of the deck owner never
    sees it."""
    seed = _seed_six(factory, contributors=1)
    before = _rows(factory, seed["owner_pk"])
    _set_claim(factory, seed["owner_pk"], claim_age_seconds=10)
    state = _db_state(factory)

    with pytest.raises(ArcReviewInFlightError):
        _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=requester)
    _assert_unchanged(factory, state)


def test_the_owners_deck_row_is_locked_before_the_deck_or_its_rows_are_read(factory):
    """The arc-review check reads the OWNER's deck row ``FOR UPDATE``.  On PostgreSQL
    that lock is what serialises this insert against another insert and against a
    claim: everything the insert decides on (the deck's version, the busy sessions,
    the rows it compares with *expected_rows* and splices) must be read AFTER it, or
    a concurrent insert that commits while this one waits on the lock is spliced
    over stale rows, and a deck loaded earlier keeps its pre-lock version in the
    identity map (the ``FOR UPDATE`` SELECT does not refresh it).  SQLite renders no
    ``FOR UPDATE``, so the order is pinned instead: before the lock only the two
    sessions are read; the lock's own SELECT is the first read of the deck row."""
    import src.api.services.chat_service as chat_service

    seed = _seed_six(factory, contributors=1)
    before = _rows(factory, seed["owner_pk"])
    trace: List[Tuple[str, str]] = []
    real = chat_service._refuse_during_an_arc_review

    def spy(db, session):
        trace.append(("lock", session.session_id))
        return real(db, session)

    def on_execute(conn, cursor, statement, params, context, executemany):
        trace.append(("sql", " ".join(statement.split())))

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        with patch.object(chat_service, "_refuse_during_an_arc_review", spy):
            _insert(
                factory, 1, before=before, release_id=seed["release_id"], session_id=CONTRIB_SID
            )
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)

    assert ("lock", OWNER_SID) in trace, f"the lock was not taken on the OWNER's deck: {trace}"
    lock_at = trace.index(("lock", OWNER_SID))
    before_lock = [sql for kind, sql in trace[:lock_at] if kind == "sql"]
    after_lock = [sql for kind, sql in trace[lock_at + 1 :] if kind == "sql"]
    early = [
        sql
        for sql in before_lock
        if "session_slide" in sql
        or "processing_started_at >" in sql
        or not sql.startswith("SELECT")
    ]
    assert not early, f"read or written before the owner's deck row was locked: {early}"
    assert after_lock and after_lock[0].startswith("SELECT") and (
        "FROM session_slide_decks" in after_lock[0]
    ), f"the first statement after the lock is not the lock's deck SELECT: {after_lock[:1]}"
    assert any("FROM session_slides" in sql for sql in after_lock[1:]), (
        "the rows were not re-read after the lock"
    )
    assert _layout(_rows(factory, seed["owner_pk"])) == LAYOUT_AT_1


def test_an_expired_arc_review_claim_does_not_refuse(factory):
    seed = _seed_six(factory, contributors=1)
    before = _rows(factory, seed["owner_pk"])
    _set_claim(factory, seed["owner_pk"], claim_age_seconds=CLAIM_TTL_SECONDS + 60)

    _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=CONTRIB_SID)
    assert _layout(_rows(factory, seed["owner_pk"])) == LAYOUT_AT_1


# ---------------------------------------------------------------------------
# M2: a turn on ANY other session of the deck refuses (D7 (3); C8)
# ---------------------------------------------------------------------------


def test_the_session_lock_timeout_is_one_constant():
    assert session_manager.SESSION_LOCK_TIMEOUT_SECONDS == 300
    default = inspect.signature(SessionManager.acquire_session_lock).parameters[
        "timeout_seconds"
    ].default
    assert default == session_manager.SESSION_LOCK_TIMEOUT_SECONDS


def test_the_new_errors_are_runtime_errors_and_shared():
    """The route maps these before ``except Exception``; none overlaps ValueError (400)."""
    assert slide_repository.SlideRowsChangedError is session_manager.SlideRowsChangedError
    assert slide_repository._snapshot_row is session_manager._snapshot_row
    for error in (session_manager.DeckBusyError, session_manager.SlideRowsChangedError):
        assert issubclass(error, RuntimeError) and not issubclass(error, ValueError)


@pytest.mark.parametrize(
    "busy_sid, requester",
    [
        pytest.param(OWNER_SID, CONTRIB_SID, id="owner-turn-refuses-a-contributor-insert"),
        pytest.param(CONTRIB_SID, OWNER_SID, id="contributor-turn-refuses-an-owner-insert"),
        pytest.param(
            SECOND_CONTRIB_SID, CONTRIB_SID, id="another-contributors-turn-refuses"
        ),
    ],
)
@pytest.mark.parametrize("started_seconds_ago", [10, 290], ids=["10s", "290s"])
def test_a_turn_on_another_session_of_the_deck_refuses(
    factory, busy_sid, requester, started_seconds_ago
):
    seed = _seed_six(factory, contributors=2)
    before = _rows(factory, seed["owner_pk"])
    _set_processing(factory, busy_sid, started_seconds_ago)
    state = _db_state(factory)

    with pytest.raises(session_manager.DeckBusyError):
        _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=requester)
    _assert_unchanged(factory, state)


@pytest.fixture()
def local_zone(request):
    """Run with the process's LOCAL zone set far from UTC.  POSIX TZ strings, so no
    tzdata is needed: ``AHEAD-14`` is UTC+14, ``BEHIND+12`` is UTC-12.  The columns
    hold naive UTC (``acquire_session_lock`` writes ``utcnow()``), so the busy cutoff
    must be naive UTC too (C8), never local time: ahead of UTC a local cutoff misses a
    live turn, behind UTC it calls a stale lock busy."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    try:
        yield request.param
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


@pytest.mark.parametrize("local_zone", ["AHEAD-14", "BEHIND+12"], indirect=True)
def test_the_busy_cutoff_is_naive_utc_whatever_the_local_zone(factory, local_zone):
    seed = _seed_six(factory, contributors=1)
    before = _rows(factory, seed["owner_pk"])

    _set_processing(factory, OWNER_SID, 10)
    state = _db_state(factory)
    with pytest.raises(session_manager.DeckBusyError):
        _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=CONTRIB_SID)
    _assert_unchanged(factory, state)

    _set_processing(factory, OWNER_SID, 310)
    _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=CONTRIB_SID)
    assert _layout(_rows(factory, seed["owner_pk"])) == LAYOUT_AT_1


@pytest.mark.parametrize(
    "busy_sid, started_seconds_ago, requester",
    [
        pytest.param(OWNER_SID, 310, CONTRIB_SID, id="a-lock-older-than-300s-is-stale"),
        pytest.param(OWNER_SID, None, CONTRIB_SID, id="no-start-time-is-not-busy"),
        pytest.param(OWNER_SID, 10, OWNER_SID, id="the-owners-own-lock-does-not-self-refuse"),
        pytest.param(
            CONTRIB_SID, 10, CONTRIB_SID, id="a-contributors-own-lock-does-not-self-refuse"
        ),
        pytest.param(STRANGER_SID, 10, CONTRIB_SID, id="another-decks-turn-does-not-refuse"),
    ],
)
def test_a_lock_that_is_not_another_live_turn_on_this_deck_proceeds(
    factory, busy_sid, started_seconds_ago, requester
):
    seed = _seed_six(factory, contributors=2, stranger=True)
    before = _rows(factory, seed["owner_pk"])
    _set_processing(factory, busy_sid, started_seconds_ago)

    _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=requester)
    after = _rows(factory, seed["owner_pk"])
    assert _layout(after) == LAYOUT_AT_1
    _assert_every_old_row_intact(before, after)


# ---------------------------------------------------------------------------
# Contributor; usage-event attribution
# ---------------------------------------------------------------------------


def test_a_contributor_writes_the_owners_rows_and_owns_the_usage_event(factory):
    seed = _seed_six(factory, contributors=1)
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
    _insert(factory, 1, before=before, release_id=seed["release_id"], session_id=CONTRIB_SID)
    t1 = datetime.utcnow()

    after = _rows(factory, seed["owner_pk"])
    assert _layout(after) == LAYOUT_AT_1
    _assert_every_old_row_intact(before, after)
    assert _rows(factory, seed["contrib_pk"]) == [], "rows landed on the contributor session"
    assert _deck(factory, seed["contrib_pk"]) is None
    assert _deck(factory, seed["owner_pk"]).version == 6

    assert _mutation_events(factory) == [
        ("insert_slide", "deck", seed["contrib_pk"], seed["owner_pk"], seed["release_id"], NEW_SID)
    ], "the evidence names the contributor as actor and the owner as root"
    assert _usage_events(factory) == [(EVENT_TYPE, INSERTER, seed["contrib_pk"])], (
        "the usage event carries the REQUESTING session's pk"
    )
    activity = _last_activity(factory)
    for sid in (OWNER_SID, CONTRIB_SID):
        assert t0 <= activity[sid] <= t1, f"{sid}'s last_activity not touched: {activity[sid]!r}"


def test_no_inserted_by_writes_no_usage_event_but_still_the_mutation_event(factory):
    seed, _before, _result = _insert_six(factory, 1, inserted_by=None)
    assert _usage_events(factory) == []
    assert _mutation_events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"], NEW_SID)
    ]


def test_an_author_less_slide_stays_author_less_and_leaves_deck_modified_by(factory):
    """No user resolved: the writer invents no author (author_fallback=None) and
    deck.modified_by keeps its last real editor."""
    seed, _before, _result = _insert_six(factory, 1, slide=_new_slide(author=None))
    (new_row,) = [r for r in _rows(factory, seed["owner_pk"]) if r["slide_id"] == NEW_SID]
    assert (new_row["created_by"], new_row["modified_by"]) == (None, None)
    assert (new_row["created_at"], new_row["modified_at"]) == (NEW_STAMP_DT, NEW_STAMP_DT)
    assert _deck(factory, seed["owner_pk"]).modified_by == "previous-editor@test.com"


# ---------------------------------------------------------------------------
# The exact map, never the heuristic
# ---------------------------------------------------------------------------


def _twin_row(label: str, day: int) -> Dict[str, Any]:
    """An id-less blank row.  Its HTML cannot carry a marker, so its record and
    fragment do, and its authorship differs from its twin's."""
    return {
        "html": BLANK_HTML,
        "slide_id": None,
        "scripts": "",
        "created_by": f"twin-{label.lower()}@test.com",
        "created_at": datetime(2024, 6, day, 10, 0, 0),
        "modified_by": f"twin-{label.lower()}@test.com",
        "modified_at": datetime(2024, 6, day, 11, 0, 0),
        "verification_record": json.dumps(
            {compute_slide_hash(BLANK_HTML): {"explanation": f"TWIN-{label}-VERDICT"}}
        ),
        "deck_spec_slide": _fragment(f"TWIN-{label}", 0),
    }


def test_id_less_identical_twins_each_keep_their_own_record_and_fragment(factory):
    """The heuristic's pass 2 (by content hash) would hand the first twin's record
    and fragment to the new blank, and shift the second twin's onto the first."""
    rows = {
        0: _real_row("MK-ALPHA", 0, day=1),
        1: _real_row("MK-BRAVO", 1, day=2),
        2: _twin_row("ONE", 3),
        3: _twin_row("TWO", 4),
    }
    seed = _seed(factory, rows, spec=_spec_json(["MK-ALPHA", "MK-BRAVO", "TWIN-ONE", "TWIN-TWO"]))
    before = _rows(factory, seed["owner_pk"])
    twin_one, twin_two = before[2], before[3]

    _insert(factory, 1, before=before, release_id=seed["release_id"])
    after = _rows(factory, seed["owner_pk"])

    assert [r["position"] for r in after] == list(range(5))
    assert _layout(after) == ["MK-ALPHA", "NEW", "MK-BRAVO", "UNMARKED", "UNMARKED"]
    _assert_new_row(after[1])
    assert _identity(after[3]) == _identity(twin_one), (
        f"the first twin did not keep its own record/fragment/authorship: {after[3]}"
    )
    assert _identity(after[4]) == _identity(twin_two), (
        f"the second twin did not keep its own record/fragment/authorship: {after[4]}"
    )
    _assert_every_old_row_intact(before, after)


# ---------------------------------------------------------------------------
# C22: a gapped deck comes out contiguous
# ---------------------------------------------------------------------------


def test_a_gapped_deck_comes_out_contiguous_in_rows_and_spec(factory):
    rows = {
        0: _real_row("MK-XRAY", 0, day=1),
        1: _real_row("MK-YANKEE", 1, day=2),
        3: _real_row("MK-ZULU", 3, day=3),
    }
    seed = _seed(
        factory, rows, spec=_spec_json(["MK-XRAY", "MK-YANKEE", "MK-ZULU"], positions=[0, 1, 3])
    )
    before = _rows(factory, seed["owner_pk"])
    assert [r["position"] for r in before] == [0, 1, 3]

    result = _insert(factory, 1, before=before, release_id=seed["release_id"])
    after = _rows(factory, seed["owner_pk"])

    assert [r["position"] for r in after] == [0, 1, 2, 3], (
        f"rows are not contiguous after the insert: {[r['position'] for r in after]}"
    )
    assert _layout(after) == ["MK-XRAY", "NEW", "MK-YANKEE", "MK-ZULU"]
    _assert_every_old_row_intact(before, after)
    _assert_new_row(after[1])
    assert result["position"] == 1 and result["slide_count"] == 4

    spec = json.loads(_deck(factory, seed["owner_pk"]).deck_spec_json)
    assert [e["position"] for e in spec["slides"]] == [0, 1, 2, 3]
    assert [e["purpose"] for e in spec["slides"]] == [
        "SPEC-MK-XRAY",
        "",
        "SPEC-MK-YANKEE",
        "SPEC-MK-ZULU",
    ]
    assert spec["slides"][1] == _blank_entry(1)


@pytest.mark.parametrize(
    "position", [pytest.param(3, id="at-the-row-count"), pytest.param(99, id="past-the-end")]
)
def test_a_gapped_deck_appends_at_its_row_count_not_after_its_last_position(factory, position):
    """C22: the clamp is the number of ROWS (3), never the last row's position + 1
    (4), which on a gapped deck names a position the shifted deck does not have."""
    rows = {
        0: _real_row("MK-XRAY", 0, day=1),
        1: _real_row("MK-YANKEE", 1, day=2),
        3: _real_row("MK-ZULU", 3, day=3),
    }
    seed = _seed(
        factory, rows, spec=_spec_json(["MK-XRAY", "MK-YANKEE", "MK-ZULU"], positions=[0, 1, 3])
    )
    before = _rows(factory, seed["owner_pk"])

    result = _insert(factory, position, before=before, release_id=seed["release_id"])
    after = _rows(factory, seed["owner_pk"])

    assert [r["position"] for r in after] == [0, 1, 2, 3]
    assert _layout(after) == ["MK-XRAY", "MK-YANKEE", "MK-ZULU", "NEW"]
    _assert_every_old_row_intact(before, after)
    _assert_new_row(after[3])
    assert result["position"] == 3 and result["slide_count"] == 4

    spec = json.loads(_deck(factory, seed["owner_pk"]).deck_spec_json)
    assert [e["position"] for e in spec["slides"]] == [0, 1, 2, 3]
    assert [e["purpose"] for e in spec["slides"]] == [
        "SPEC-MK-XRAY",
        "SPEC-MK-YANKEE",
        "SPEC-MK-ZULU",
        "",
    ]
    assert spec["slides"][3] == _blank_entry(3)


# ---------------------------------------------------------------------------
# D13 (C7, supervisor's ruling): a row-less legacy deck is materialised as the
# backfill would materialise it, then takes the rows path
# ---------------------------------------------------------------------------

LEGACY_CSS = ".slide { background: #123456; } /* LEGACY-CSS-ONLY-IN-DECK-JSON */"
LEGACY_EXT = ["https://cdn.jsdelivr.net/npm/chart.js"]
LEGACY_HEAD = {"viewport": "width=1600, initial-scale=1"}
#: SCIM display names the cached deck carries.  The rows must never get them.
DISPLAY_NAMES = {
    "one-author@test.com": "One Author (display)",
    "one-editor@test.com": "One Editor (display)",
    "two-author@test.com": "Two Author (display)",
    "three-author@test.com": "Three Author (display)",
    "owner@test.com": "Owner (display)",
    INSERTER: "Inserter (display)",
}
LEGACY = ("MK-LEGACYONE", "MK-LEGACYTWO", "MK-LEGACYTHREE")


def _legacy_slides() -> List[Dict[str, Any]]:
    return [
        {
            "html": _real_html("MK-LEGACYONE"),
            "slide_id": "legacy-sid-1",
            "scripts": "/* legacy one */",
            "created_by": "one-author@test.com",
            "created_at": "2024-04-01T10:00:00Z",
            "modified_by": "one-editor@test.com",
            "modified_at": "2024-04-02T11:00:00Z",
        },
        {
            # id-less, NULL timestamps: the shape the startup backfill keeps NULL.
            "html": _real_html("MK-LEGACYTWO"),
            "slide_id": None,
            "scripts": "",
            "created_by": "two-author@test.com",
            "created_at": None,
            "modified_by": "two-author@test.com",
            "modified_at": None,
        },
        {
            "html": _real_html("MK-LEGACYTHREE"),
            "slide_id": "legacy-sid-3",
            "scripts": "",
            "created_by": "three-author@test.com",
            "created_at": "2024-04-03T12:00:00Z",
            "modified_by": None,
            "modified_at": None,
        },
    ]


def _legacy_verdict(marker: str, html: str, position: int) -> Dict[str, Any]:
    return {
        "score": 77,
        "rating": "good",
        "explanation": f"LEGACY-VERDICT-{marker}",
        VERDICT_KEY: {
            "verdict": "surfaced",
            "findings": [_finding_for(html, position, marker).model_dump()],
        },
    }


def _seed_legacy(factory, **kw) -> Dict[str, Any]:
    """A deck the backfill has not reached: deck_json only, presentation columns
    NULL, verdicts only in the deck-wide verification_map, no rows."""
    slides = _legacy_slides()
    blob = {
        "title": "Legacy deck",
        "css": LEGACY_CSS,
        "external_scripts": LEGACY_EXT,
        "head_meta": LEGACY_HEAD,
        "scripts": "",
        "slides": slides,
    }
    verification_map = {
        compute_slide_hash(slides[1]["html"]): _legacy_verdict(
            "MK-LEGACYTWO", slides[1]["html"], 1
        ),
        compute_slide_hash(slides[2]["html"]): _legacy_verdict(
            "MK-LEGACYTHREE", slides[2]["html"], 2
        ),
    }
    columns = {
        "deck_json": json.dumps(blob),
        "verification_map": json.dumps(verification_map),
        "slide_count": 3,
        "css": None,
        "external_scripts_json": None,
        "head_meta_json": None,
        "deck_spec_json": _spec_json(LEGACY),
    }
    columns.update(kw.pop("deck_columns", {}))
    return _seed(factory, {}, deck_columns=columns, **kw)


def _cached_legacy_deck(factory) -> Dict[str, Any]:
    """The deck as ChatService caches it: get_slide_deck's blob path, which carries
    SCIM display names."""
    with _patched(factory, names=DISPLAY_NAMES):
        cached = SessionManager().get_slide_deck(OWNER_SID)
    assert [_marker(s["html"]) for s in cached["slides"]] == list(LEGACY)
    assert cached["slides"][0]["created_by"] == "One Author (display)", (
        "fixture check: the cached deck must carry display names"
    )
    return cached


def _legacy_deck_dict(cached: Dict[str, Any], position: int) -> Dict[str, Any]:
    keys = ("html", "slide_id", "scripts", "created_by", "created_at", "modified_by", "modified_at")
    slides = [
        {k: s.get(k) for k in keys if s.get(k) is not None or k == "slide_id"}
        for s in cached["slides"]
    ]
    slides.insert(min(position, len(slides)), _new_slide())
    for index, s in enumerate(slides):
        s["index"] = index
    return {
        "title": TITLE_AFTER,
        "slide_count": len(slides),
        "css": cached["css"],
        "external_scripts": cached["external_scripts"],
        "scripts": SCRIPTS_AFTER,
        "slides": slides,
        "head_meta": cached["head_meta"],
    }


def _insert_legacy(factory, position: int, seed, cached, **kw) -> Dict[str, Any]:
    expected = kw.pop(
        "expected_rows",
        [(s["slide_id"], compute_slide_hash(s["html"])) for s in cached["slides"]],
    )
    return _insert(
        factory,
        position,
        before=[],
        release_id=seed["release_id"],
        expected_rows=expected,
        deck_dict=_legacy_deck_dict(cached, position),
        names=DISPLAY_NAMES,
        **kw,
    )


def _expected_legacy_rows(owner_pk: int) -> Dict[str, Dict[str, Any]]:
    """What the startup backfill writes for each legacy slide, written out."""
    slides = _legacy_slides()
    two, three = slides[1]["html"], slides[2]["html"]
    return {
        "MK-LEGACYONE": {
            "session_id": owner_pk,
            "html": slides[0]["html"],
            "slide_id": "legacy-sid-1",
            "scripts": "/* legacy one */",
            "created_by": "one-author@test.com",
            "created_at": datetime(2024, 4, 1, 10, 0, 0),
            "modified_by": "one-editor@test.com",
            "modified_at": datetime(2024, 4, 2, 11, 0, 0),
            "verification_record": None,
            "deck_spec_slide": None,
        },
        "MK-LEGACYTWO": {
            "session_id": owner_pk,
            "html": two,
            "slide_id": None,
            "scripts": "",
            "created_by": "two-author@test.com",
            "created_at": None,
            "modified_by": "two-author@test.com",
            "modified_at": None,
            "verification_record": {
                compute_slide_hash(two): _legacy_verdict("MK-LEGACYTWO", two, 1)
            },
            "deck_spec_slide": None,
        },
        "MK-LEGACYTHREE": {
            "session_id": owner_pk,
            "html": three,
            "slide_id": "legacy-sid-3",
            "scripts": "",
            "created_by": "three-author@test.com",
            "created_at": datetime(2024, 4, 3, 12, 0, 0),
            "modified_by": None,
            "modified_at": None,
            "verification_record": {
                compute_slide_hash(three): _legacy_verdict("MK-LEGACYTHREE", three, 2)
            },
            "deck_spec_slide": None,
        },
    }


def test_a_row_less_legacy_deck_is_materialised_raw_then_spliced(factory):
    """Raw emails (never the cached display names), NULL timestamps kept, verdicts
    migrated from verification_map: the backfill's rows, plus the new one."""
    seed = _seed_legacy(factory)
    cached = _cached_legacy_deck(factory)

    result = _insert_legacy(factory, 2, seed, cached)
    after = _rows(factory, seed["owner_pk"])

    assert _layout(after) == ["MK-LEGACYONE", "MK-LEGACYTWO", "NEW", "MK-LEGACYTHREE"]
    assert [r["position"] for r in after] == [0, 1, 2, 3]
    expected = _expected_legacy_rows(seed["owner_pk"])
    for marker, row in _by_marker(after).items():
        assert _identity(row) == expected[marker], (
            f"{marker} was not materialised as the backfill writes it:\n"
            f" expected {expected[marker]}\n got      {_identity(row)}"
        )
    _assert_new_row(after[2])
    assert result["position"] == 2 and result["slide_count"] == 4
    deck = _deck(factory, seed["owner_pk"])
    assert deck.version == 6 and deck.slide_count == 4
    assert _mutation_events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"], NEW_SID)
    ]
    assert _usage_events(factory) == [(EVENT_TYPE, INSERTER, seed["owner_pk"])]


def test_a_row_less_legacy_deck_keeps_its_stylesheet_scripts_and_head_meta(factory):
    """C7: css/external_scripts/head_meta lived only in deck_json.  The next read
    takes the row path, which reads the columns, so they must be lifted."""
    seed = _seed_legacy(factory)
    cached = _cached_legacy_deck(factory)
    _insert_legacy(factory, 2, seed, cached)

    deck = _deck(factory, seed["owner_pk"])
    assert deck.css == LEGACY_CSS
    assert json.loads(deck.external_scripts_json) == LEGACY_EXT
    assert json.loads(deck.head_meta_json) == LEGACY_HEAD
    with _patched(factory, names=DISPLAY_NAMES):
        read = SessionManager().get_slide_deck(OWNER_SID)
    assert [_marker(s["html"]) or "NEW" for s in read["slides"]] == [
        "MK-LEGACYONE", "MK-LEGACYTWO", "NEW", "MK-LEGACYTHREE",
    ], "the read after the insert is not the row path's four slides"
    assert read["css"] == LEGACY_CSS, f"the deck lost its stylesheet: {read['css']!r}"
    assert read["external_scripts"] == LEGACY_EXT, "the deck lost Chart.js"
    assert read["head_meta"] == LEGACY_HEAD


def test_a_row_less_legacy_deck_gets_its_spec_entry_at_the_position_not_0(factory):
    """C7's second bug: min(position, len(rows)) with no rows is 0."""
    seed = _seed_legacy(factory)
    cached = _cached_legacy_deck(factory)
    _insert_legacy(factory, 2, seed, cached)

    spec = json.loads(_deck(factory, seed["owner_pk"]).deck_spec_json)
    assert [e["position"] for e in spec["slides"]] == [0, 1, 2, 3]
    assert spec["slides"][2] == _blank_entry(2), f"the blank is not at 2: {spec['slides']}"
    assert [e["purpose"] for e in spec["slides"]] == [
        "SPEC-MK-LEGACYONE", "SPEC-MK-LEGACYTWO", "", "SPEC-MK-LEGACYTHREE",
    ]


def test_a_row_less_legacy_deck_shows_its_migrated_findings_on_their_slides(factory):
    seed = _seed_legacy(factory)
    cached = _cached_legacy_deck(factory)
    _insert_legacy(factory, 2, seed, cached)

    with _patched(factory, names=DISPLAY_NAMES):
        read = SessionManager().get_slide_deck(OWNER_SID)
    by_message = {f["message"]: f["slideIndex"] for f in read["findings"]}
    assert by_message == {"FINDING-MK-LEGACYTWO": 1, "FINDING-MK-LEGACYTHREE": 3}, by_message


def test_a_refused_legacy_insert_leaves_no_rows_behind(factory):
    """Nothing is written on any refusal (D7), the materialisation included: an
    evidence failure after it rolls the backfilled rows and lifted columns back too."""
    seed = _seed_legacy(factory)
    cached = _cached_legacy_deck(factory)
    state = _db_state(factory)

    def _refuse(*args, **kwargs):
        raise RuntimeError("evidence write refused")

    with patch.object(session_manager, "record_shared_deck_mutation", _refuse):
        with pytest.raises(RuntimeError, match="evidence write refused"):
            _insert_legacy(factory, 2, seed, cached)
    assert _rows(factory, seed["owner_pk"]) == [], "a refused insert left materialised rows"
    _assert_unchanged(factory, state)


def test_a_legacy_deck_that_is_not_the_expected_rows_refuses_and_leaves_no_rows(factory):
    seed = _seed_legacy(factory)
    cached = _cached_legacy_deck(factory)
    stale = [(s["slide_id"], compute_slide_hash(s["html"])) for s in cached["slides"]]
    stale[1] = (stale[1][0], compute_slide_hash("<p>an edit the cache never saw</p>"))
    state = _db_state(factory)

    with pytest.raises(session_manager.SlideRowsChangedError):
        _insert_legacy(factory, 2, seed, cached, expected_rows=stale)
    assert _rows(factory, seed["owner_pk"]) == []
    _assert_unchanged(factory, state)


# MINOR-2 (whole-branch review): a row-less deck is reachable at RUNTIME, because
# duplicate_session copies deck_json and no rows, so a duplicated deck stays row-less
# until its first write.  A blob slide that LACKS the ``slide_id`` key is minted
# ``slide_{i}`` by SlideDeck.from_dict (the cached deck the caller plans against, so
# expected_rows carries ``slide_i``) but written NULL by the backfill.  The rows were
# materialised from this very blob inside this transaction, so on that path the
# writer compares content hashes, in order, only.  The rows path keeps the full
# (slide_id, content_hash) comparison: test_rows_that_are_not_the_expected_rows_refuse
# [one-slide-id-differs].

#: The ids SlideDeck.from_dict mints for blob slides with no ``slide_id`` key
#: (written out, not computed by the code under test).
MINTED_IDS = ("slide_0", "slide_1", "slide_2")


def _id_less_legacy_slides() -> List[Dict[str, Any]]:
    """``_legacy_slides()`` with the ``slide_id`` KEY removed (absent, not None)."""
    slides = _legacy_slides()
    for s in slides:
        del s["slide_id"]
    return slides


def _seed_id_less_legacy(factory) -> Dict[str, Any]:
    blob = {
        "title": "Legacy deck",
        "css": LEGACY_CSS,
        "external_scripts": LEGACY_EXT,
        "head_meta": LEGACY_HEAD,
        "scripts": "",
        "slides": _id_less_legacy_slides(),
    }
    return _seed_legacy(factory, deck_columns={"deck_json": json.dumps(blob)})


def _minted_expected_rows() -> List[Tuple[Optional[str], str]]:
    """What ChatService reads off its cached (from_dict) deck: minted ids, real hashes."""
    return [
        (sid, compute_slide_hash(s["html"]))
        for sid, s in zip(MINTED_IDS, _id_less_legacy_slides())
    ]


def _insert_id_less_legacy(factory, position: int, seed, cached, **kw) -> Dict[str, Any]:
    deck_dict = _legacy_deck_dict(cached, position)
    # The planned deck is the cached (from_dict) deck plus the blank: it carries the minted ids.
    minted = iter(MINTED_IDS)
    for s in deck_dict["slides"]:
        if s["slide_id"] != NEW_SID:
            s["slide_id"] = next(minted)
    return _insert(
        factory,
        position,
        before=[],
        release_id=seed["release_id"],
        expected_rows=kw.pop("expected_rows", _minted_expected_rows()),
        deck_dict=deck_dict,
        names=DISPLAY_NAMES,
        **kw,
    )


def test_a_row_less_deck_whose_blob_slides_have_no_slide_id_inserts_by_content_hash(factory):
    seed = _seed_id_less_legacy(factory)
    blob = json.loads(_deck(factory, seed["owner_pk"]).deck_json)
    assert [s.get("slide_id", "<absent>") for s in blob["slides"]] == ["<absent>"] * 3, (
        "fixture check: the blob slides must lack the slide_id key"
    )
    cached = _cached_legacy_deck(factory)

    result = _insert_id_less_legacy(factory, 2, seed, cached)
    after = _rows(factory, seed["owner_pk"])

    # Materialised in blob order, the blank at 2.
    assert _layout(after) == ["MK-LEGACYONE", "MK-LEGACYTWO", "NEW", "MK-LEGACYTHREE"]
    assert [r["position"] for r in after] == [0, 1, 2, 3]
    # The backfill's rows, ids NULL as it writes them (never the minted ids).
    expected = _expected_legacy_rows(seed["owner_pk"])
    for marker in ("MK-LEGACYONE", "MK-LEGACYTHREE"):
        expected[marker]["slide_id"] = None
    for marker, row in _by_marker(after).items():
        assert _identity(row) == expected[marker], (
            f"{marker} was not materialised as the backfill writes it:\n"
            f" expected {expected[marker]}\n got      {_identity(row)}"
        )
    _assert_new_row(after[2])
    assert result["position"] == 2 and result["slide_count"] == 4

    # The spec spliced at the landed index.
    spec = json.loads(_deck(factory, seed["owner_pk"]).deck_spec_json)
    assert [e["position"] for e in spec["slides"]] == [0, 1, 2, 3]
    assert spec["slides"][2] == _blank_entry(2)
    assert [e["purpose"] for e in spec["slides"]] == [
        "SPEC-MK-LEGACYONE", "SPEC-MK-LEGACYTWO", "", "SPEC-MK-LEGACYTHREE",
    ]
    deck = _deck(factory, seed["owner_pk"])
    assert deck.version == 6 and deck.slide_count == 4
    assert _mutation_events(factory) == [
        ("insert_slide", "deck", seed["owner_pk"], seed["owner_pk"], seed["release_id"], NEW_SID)
    ]


def _stale_hash(rows):
    rows[1] = (rows[1][0], compute_slide_hash("<p>an edit the cache never saw</p>"))
    return rows


def _stale_order(rows):
    rows[0], rows[2] = rows[2], rows[0]
    return rows


@pytest.mark.parametrize(
    "stale_of",
    [
        pytest.param(_stale_hash, id="one-content-hash-differs"),
        pytest.param(_stale_order, id="slides-reordered"),
        pytest.param(lambda rows: rows[:-1], id="one-slide-fewer"),
    ],
)
def test_a_row_less_id_less_deck_whose_blob_changed_is_still_refused(factory, stale_of):
    seed = _seed_id_less_legacy(factory)
    cached = _cached_legacy_deck(factory)
    state = _db_state(factory)

    with pytest.raises(session_manager.SlideRowsChangedError):
        _insert_id_less_legacy(
            factory, 2, seed, cached, expected_rows=stale_of(_minted_expected_rows())
        )
    assert _rows(factory, seed["owner_pk"]) == [], "a refused insert left materialised rows"
    _assert_unchanged(factory, state)


def test_a_legacy_deck_with_slides_refuses_an_insert_that_expected_none(factory):
    """The caller saw an empty deck, the blob holds three slides: a stale cache.
    Splicing into "no rows" would leave a one-row deck that hides the blob."""
    seed = _seed_legacy(factory)
    state = _db_state(factory)
    with pytest.raises(session_manager.SlideRowsChangedError):
        _insert(
            factory,
            0,
            before=[],
            release_id=seed["release_id"],
            expected_rows=[],
            names=DISPLAY_NAMES,
        )
    _assert_unchanged(factory, state)


def test_an_empty_deck_gets_its_first_slide(factory):
    """No rows, no blob: the splice with no old rows; any position lands at 0."""
    seed = _seed(factory, {}, spec=None, deck_columns={"deck_json": None, "slide_count": 0})
    result = _insert(factory, 3, before=[], release_id=seed["release_id"], expected_rows=[])

    after = _rows(factory, seed["owner_pk"])
    assert len(after) == 1 and after[0]["position"] == 0
    _assert_new_row(after[0])
    assert result["position"] == 0 and result["slide_count"] == 1
    deck = _deck(factory, seed["owner_pk"])
    assert deck.slide_count == 1 and deck.version == 6
    assert deck.deck_spec_json is None


def test_an_empty_deck_refuses_an_insert_that_expected_rows(factory):
    seed = _seed(factory, {}, spec=None, deck_columns={"deck_json": None, "slide_count": 0})
    state = _db_state(factory)
    with pytest.raises(session_manager.SlideRowsChangedError):
        _insert(
            factory,
            0,
            before=[],
            release_id=seed["release_id"],
            expected_rows=[("sid-gone", compute_slide_hash("<p>gone</p>"))],
        )
    _assert_unchanged(factory, state)
