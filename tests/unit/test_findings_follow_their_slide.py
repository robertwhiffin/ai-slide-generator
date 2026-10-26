"""Findings and verification follow their slide (#314, Task 3; plan D7, D8).

A review finding is minted for a slide's CONTENT: its id is
``criterion:subject_hash:ordinal`` (``make_finding_id``, as ``_stamp_findings``
mints it), and it lives in that hash's slot of the row's verification record.  Its
``slideIndex`` is only the position the reviewer happened to see.  So:

* **D7.**  On the ROW path of ``get_slide_deck``, a finding read from a row's
  current-hash verdict must report THAT ROW's list index.  Otherwise any shift (an
  agent insert, a UI reorder) shows a slide's findings on whichever slide now sits
  at the old index.  A stored ``-1`` (deck-level) finding stays ``-1``.  The blob
  and no-rows paths still project verbatim (PLAN-CORRECTIONS C8).
* **D8.**  ``write_slide_verification`` is called with an index read BEFORE the
  judge ran.  If the deck shifted in between, the verdict must still land on the
  slide whose HTML it verified, not on whatever now sits at that index.

Every assertion is by CONTENT: a finding's subject hash against the content hash of
the slide it is shown on, and a verdict's marker against the row whose own HTML
marker it names.  Never by position alone, never by count, never by hand-picked
keys.  "slide 1 has three findings" is true of a deck that shows slide B's findings
on the pending slide.

``get_slide_deck`` runs outside ``graph_env``, so the SCIM display-name lookup is
patched to ``{}`` (a real WorkspaceClient retries and hangs).
"""
from __future__ import annotations

import contextlib
import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — register every ORM model
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import SlideWriter
from src.core.database import Base
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.domain.deck_spec import DeckSpec
from src.domain.finding import Finding, build_verification_record, make_finding_id
from src.domain.slide_deck import SlideDeck
from src.services.shared_deck_attribution import DeckMutationContext, MutationActor
from src.utils.slide_hash import compute_slide_hash

OWNER_SID = "findings-follow-owner"
ABC = ("MK-ALPHA", "MK-BRAVO", "MK-CHARLIE")
_MARKER_RE = re.compile(r"MK-[A-Z]+")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    # autoflush=False, as production (src/core/database.py).
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
def db(factory, monkeypatch):
    """Point every writer and reader at this test's engine; neutralise SCIM."""
    monkeypatch.setattr(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    )
    with patch(
        "src.api.services.session_manager.get_db_session", _fake_db(factory)
    ), patch("src.api.services.slide_repository.get_db_session", _fake_db(factory)):
        yield factory


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------


def _html(marker: str) -> str:
    return f'<div class="slide"><h1>{marker}</h1><p>its own body text</p></div>'


def _marker(html: str) -> Optional[str]:
    found = _MARKER_RE.findall(html or "")
    assert len(found) <= 1, f"a slide carries more than one marker: {found}"
    return found[0] if found else None


def _stamped_findings(marker: str, html: str, slide_index: int) -> List[Finding]:
    """What a reviewer stamps: ids minted from the content hash, the index it saw.

    Two findings of one criterion (ordinals 0 and 1) and one of another, so an
    override that only touched the first finding of a slot is visible.
    """
    subject = compute_slide_hash(html)
    return [
        Finding(
            id=make_finding_id("overflow", subject, 0),
            slide_index=slide_index,
            category="design",
            criterion="overflow",
            message=f"{marker} overflows (0)",
            objective=True,
        ),
        Finding(
            id=make_finding_id("overflow", subject, 1),
            slide_index=slide_index,
            category="design",
            criterion="overflow",
            message=f"{marker} overflows (1)",
            objective=True,
        ),
        Finding(
            id=make_finding_id("brief_not_delivered", subject, 0),
            slide_index=slide_index,
            category="content",
            criterion="brief_not_delivered",
            message=f"{marker} misses its brief",
            objective=False,
        ),
    ]


def _deck_level_finding(marker: str, html: str) -> Finding:
    """A stored ``-1`` finding, sitting in a slide row's current-hash verdict."""
    return Finding(
        id=make_finding_id("arc_gap", compute_slide_hash(html), 0),
        slide_index=-1,
        category="narrative",
        criterion="arc_gap",
        message=f"deck-level gap noted beside {marker}",
        objective=False,
    )


def _record(findings: List[Finding], html: str) -> Dict[str, Any]:
    """The reviewer's record for *html*, plus a history slot for an earlier draft."""
    record = build_verification_record(
        content_hash=compute_slide_hash(html), findings=findings, verdict="surfaced"
    )
    record[compute_slide_hash(f"<p>an earlier draft {uuid.uuid4().hex}</p>")] = {
        "score": 40,
        "rating": "poor",
        "explanation": "history",
    }
    return record


def _spec_json(n: int) -> str:
    return DeckSpec(
        title="Seeded",
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
                "purpose": f"purpose-{p}",
                "content_brief": f"brief-{p}",
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
    deck_json: Optional[Dict[str, Any]] = None,
    verification_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Owner session pinned to a real GraphRelease, its deck, and *rows* by position."""
    db = factory()
    try:
        release = GraphRelease(
            version_number=1,
            release_note="findings-follow fixture",
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
        db.add(
            SessionSlideDeck(
                session_id=owner.id,
                title="Seeded deck",
                html_content="",
                scripts_content="",
                slide_count=len(rows),
                deck_spec_json=_spec_json(max(len(rows), 1)),
                deck_json=json.dumps(deck_json) if deck_json is not None else None,
                verification_map=(
                    json.dumps(verification_map) if verification_map is not None else None
                ),
                version=3,
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
        return {"owner_pk": owner.id, "release_id": release.id}
    finally:
        db.close()


def _row(
    marker: str, record: Optional[Dict[str, Any]], *, html: Optional[str] = None
) -> Dict[str, Any]:
    html = html if html is not None else _html(marker)
    return {
        "html": html,
        "slide_id": f"sid-{marker}-{uuid.uuid4().hex[:8]}",
        "scripts": f"console.log('{marker}');",
        "created_by": "author@test.com",
        "created_at": datetime(2024, 1, 1, 9, 0, 0),
        "modified_by": "author@test.com",
        "modified_at": datetime(2024, 2, 1, 9, 0, 0),
        "verification_record": json.dumps(record) if record is not None else None,
    }


def _seed_reviewed(
    factory, positions: Sequence[int], *, deck_level_on: str = "MK-BRAVO"
) -> Tuple[Dict[str, Any], List[Finding]]:
    """Rows A, B, C at *positions*, each reviewed where it sat (findings stamped at
    its position); one row's verdict also holds a stored ``-1`` finding.

    Returns the seed and every finding seeded into a current-hash slot.
    """
    rows: Dict[int, Dict[str, Any]] = {}
    seeded: List[Finding] = []
    for position, marker in zip(positions, ABC):
        html = _html(marker)
        findings = _stamped_findings(marker, html, position)
        if marker == deck_level_on:
            findings.append(_deck_level_finding(marker, html))
        seeded.extend(findings)
        rows[position] = _row(marker, _record(findings, html))
    return _seed(factory, rows), seeded


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


def _raw_rows(factory, owner_pk: int) -> List[SessionSlide]:
    db = factory()
    try:
        rows = (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner_pk)
            .order_by(SessionSlide.position)
            .all()
        )
        for row in rows:
            db.expunge(row)
        return rows
    finally:
        db.close()


def _records_by_marker(factory, owner_pk: int) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in _raw_rows(factory, owner_pk):
        marker = _marker(row.html)
        if marker is None:
            continue
        assert marker not in out, f"two rows carry {marker}"
        out[marker] = json.loads(row.verification_record) if row.verification_record else {}
    return out


def _records_by_slide_id(factory, owner_pk: int) -> Dict[str, Dict[str, Any]]:
    return {
        row.slide_id: (json.loads(row.verification_record) if row.verification_record else {})
        for row in _raw_rows(factory, owner_pk)
    }


def _merged(record: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """The record a per-hash slot merge produces (the oracle, written out here)."""
    out = dict(record)
    for content_hash, verdict in incoming.items():
        out[content_hash] = {**out.get(content_hash, {}), **verdict}
    return out


def _assert_findings_follow_their_slides(deck: Dict[str, Any], seeded: List[Finding]) -> None:
    """Every finding is shown on the slide whose content minted it; ``-1`` stays ``-1``."""
    slides = deck["slides"]
    findings = deck["findings"]
    assert sorted(f["id"] for f in findings) == sorted(f.id for f in seeded), (
        "the deck read lost or invented findings: "
        f"got {sorted(f['id'] for f in findings)}"
    )
    deck_level = {f.id for f in seeded if f.slide_index == -1}
    marker_of_hash = {s["content_hash"]: _marker(s["html"]) for s in slides}
    for finding in findings:
        subject = finding["id"].split(":")[1]
        if finding["id"] in deck_level:
            assert finding["slideIndex"] == -1, (
                f"a stored deck-level finding was re-indexed to {finding['slideIndex']}: "
                f"{finding['id']}"
            )
            continue
        index = finding["slideIndex"]
        assert 0 <= index < len(slides), (
            f"finding {finding['message']!r} points past the deck: slideIndex {index}, "
            f"{len(slides)} slides"
        )
        assert slides[index]["content_hash"] == subject, (
            f"finding {finding['message']!r} (minted for "
            f"{marker_of_hash.get(subject)}) is shown on slide {index}, which is "
            f"{_marker(slides[index]['html']) or 'the pending slide'}"
        )


# ---------------------------------------------------------------------------
# Shifting the deck
# ---------------------------------------------------------------------------


def _graph_insert(factory, seed: Dict[str, Any], insert_at: Sequence[int]) -> None:
    """The graph's shift, exactly as architect_node calls it."""
    before = _raw_rows(factory, seed["owner_pk"])
    SlideWriter(SessionManager()).insert_pending_slides(
        OWNER_SID,
        list(insert_at),
        deck_spec=_spec_json(len(before) + len(insert_at)),
        expected_rows=[(r.slide_id, compute_slide_hash(r.html)) for r in before],
        created_by="turn-author@test.com",
        mutation=DeckMutationContext(
            actor=MutationActor(OWNER_SID, seed["release_id"]),
            operation="insert_slide",
            object_type="deck",
        ),
    )


def _ui_reorder(new_order: Sequence[int]) -> None:
    """ChatService.reorder_slides' row half: load, reorder, re-id, save_slide_deck."""
    sm = SessionManager()
    deck = SlideDeck.from_dict(sm.get_slide_deck(OWNER_SID))
    deck.slides = [deck.slides[i] for i in new_order]
    ChatService._reindex_slide_ids(deck)
    sm.save_slide_deck(
        session_id=OWNER_SID,
        title=deck.title,
        html_content=deck.knit(),
        scripts_content=deck.scripts,
        slide_count=len(deck.slides),
        deck_dict=deck.to_dict(),
    )


# ---------------------------------------------------------------------------
# D7: findings follow their slide on the row path
# ---------------------------------------------------------------------------


def test_the_seed_shows_every_finding_on_its_slide_before_any_shift(db):
    """Guard the guard: unshifted, stamped index and list index agree, so a red
    below is caused by the shift and not by the seed."""
    _, seeded = _seed_reviewed(db, (0, 1, 2))
    _assert_findings_follow_their_slides(SessionManager().get_slide_deck(OWNER_SID), seeded)


@pytest.mark.parametrize("insert_at", [[1], [0, 2]], ids=["insert-at-1", "insert-at-0-and-2"])
def test_findings_follow_their_slide_across_a_graph_insert(db, insert_at):
    seed, seeded = _seed_reviewed(db, (0, 1, 2))
    _graph_insert(db, seed, insert_at)

    deck = SessionManager().get_slide_deck(OWNER_SID)
    layout = [_marker(s["html"]) or "PENDING" for s in deck["slides"]]
    assert layout.count("PENDING") == len(insert_at), f"the shift did not happen: {layout}"
    _assert_findings_follow_their_slides(deck, seeded)


def test_findings_follow_their_slide_across_a_ui_reorder(db):
    _, seeded = _seed_reviewed(db, (0, 1, 2))
    _ui_reorder([2, 0, 1])

    deck = SessionManager().get_slide_deck(OWNER_SID)
    assert [_marker(s["html"]) for s in deck["slides"]] == ["MK-CHARLIE", "MK-ALPHA", "MK-BRAVO"], (
        "the reorder did not happen"
    )
    _assert_findings_follow_their_slides(deck, seeded)


def test_gapped_rows_report_the_list_index_not_the_row_position(db):
    """``slideIndex`` is the row's LIST index, the same dense index its slide dict
    carries, not ``row.position``: on gapped rows the two differ."""
    _, seeded = _seed_reviewed(db, (0, 2, 5))
    _assert_findings_follow_their_slides(SessionManager().get_slide_deck(OWNER_SID), seeded)


def test_a_stored_minus_one_finding_stays_minus_one_after_a_shift(db):
    seed, seeded = _seed_reviewed(db, (0, 1, 2), deck_level_on="MK-BRAVO")
    _graph_insert(db, seed, [0])

    deck_level = {f.id for f in seeded if f.slide_index == -1}
    assert deck_level, "the seed holds no -1 finding"
    findings = SessionManager().get_slide_deck(OWNER_SID)["findings"]
    shown = {f["id"]: f["slideIndex"] for f in findings}
    assert {fid: shown.get(fid) for fid in deck_level} == {fid: -1 for fid in deck_level}


def test_the_blob_path_still_projects_slide_index_verbatim(db):
    """No rows, a ``deck_json`` blob: findings keep the index they were stamped with
    (C8).  The stamped indices here are deliberately stale (a cyclic shift of the
    blob's order), so an override applied on this path too is visible."""
    htmls = [_html(m) for m in ABC]
    stale = {ABC[0]: 2, ABC[1]: 0, ABC[2]: 1}
    verification_map: Dict[str, Any] = {}
    stamped: Dict[str, int] = {}
    for marker, html in zip(ABC, htmls):
        findings = _stamped_findings(marker, html, stale[marker])
        verification_map.update(_record(findings, html))
        stamped.update({f.id: f.slide_index for f in findings})
    _seed(
        db,
        {},
        deck_json={
            "title": "Blob deck",
            "slides": [
                {"html": h, "slide_id": f"blob-{i}", "scripts": ""}
                for i, h in enumerate(htmls)
            ],
        },
        verification_map=verification_map,
    )

    findings = SessionManager().get_slide_deck(OWNER_SID)["findings"]
    assert {f["id"]: f["slideIndex"] for f in findings} == stamped


def test_the_no_rows_path_still_projects_slide_index_verbatim(db):
    """No rows and no ``deck_json``: findings keep the index they were stamped with."""
    verification_map: Dict[str, Any] = {}
    stamped: Dict[str, int] = {}
    for marker, index in zip(ABC, (2, 0, 1)):
        html = _html(marker)
        findings = _stamped_findings(marker, html, index)
        verification_map.update(_record(findings, html))
        stamped.update({f.id: f.slide_index for f in findings})
    _seed(db, {}, verification_map=verification_map)

    deck = SessionManager().get_slide_deck(OWNER_SID)
    assert "slides" not in deck, "this test must exercise the no-rows, no-blob path"
    assert {f["id"]: f["slideIndex"] for f in deck["findings"]} == stamped


# ---------------------------------------------------------------------------
# D8: a verification write follows the content it verified
# ---------------------------------------------------------------------------


def _judge_verdict(tag: str) -> Dict[str, Any]:
    return {"score": 88, "rating": "good", "explanation": f"VERDICT-{tag}", "issues": []}


def _plain_rows(factory, markers: Sequence[str]) -> Dict[str, Any]:
    """Rows for *markers* at 0..n-1, each with its own reviewed record."""
    rows = {}
    for position, marker in enumerate(markers):
        html = _html(marker)
        rows[position] = _row(marker, _record(_stamped_findings(marker, html, position), html))
    return _seed(factory, rows)


def test_a_verdict_written_at_a_stale_position_lands_on_the_slide_it_verified(db):
    """Rows A, B.  A verdict keyed by A's hash, written at position 1 (B's row),
    lands in A's row; B's record is unchanged."""
    seed = _plain_rows(db, ("MK-ALPHA", "MK-BRAVO"))
    before = _records_by_marker(db, seed["owner_pk"])
    incoming = {compute_slide_hash(_html("MK-ALPHA")): _judge_verdict("MK-ALPHA")}

    SessionManager().write_slide_verification(OWNER_SID, 1, incoming)

    after = _records_by_marker(db, seed["owner_pk"])
    assert after["MK-BRAVO"] == before["MK-BRAVO"], (
        "slide B's record took a verdict for slide A's content"
    )
    assert after["MK-ALPHA"] == _merged(before["MK-ALPHA"], incoming), (
        "slide A's verdict did not land on slide A"
    )


def test_a_verdict_computed_before_a_graph_insert_lands_on_its_slide(db):
    """The motivating race: the judge read slide B at index 1, the architect then
    opened a pending slide at 1, and the verdict is written at the stale index.  It
    must reach B (now at 2) and leave the pending row's record alone."""
    seed, _ = _seed_reviewed(db, (0, 1, 2))
    _graph_insert(db, seed, [1])
    pending_before = [
        json.loads(r.verification_record)
        for r in _raw_rows(db, seed["owner_pk"])
        if _marker(r.html) is None
    ]
    assert len(pending_before) == 1
    before = _records_by_marker(db, seed["owner_pk"])
    incoming = {compute_slide_hash(_html("MK-BRAVO")): _judge_verdict("MK-BRAVO")}

    SessionManager().write_slide_verification(OWNER_SID, 1, incoming)

    pending_after = [
        json.loads(r.verification_record)
        for r in _raw_rows(db, seed["owner_pk"])
        if _marker(r.html) is None
    ]
    assert pending_after == pending_before, "the pending slide took slide B's verdict"
    after = _records_by_marker(db, seed["owner_pk"])
    assert after["MK-BRAVO"] == _merged(before["MK-BRAVO"], incoming)
    assert after["MK-ALPHA"] == before["MK-ALPHA"]
    assert after["MK-CHARLIE"] == before["MK-CHARLIE"]


def _ui_delete(index: int) -> None:
    """ChatService.delete_slide's row half: load, remove, re-id, save_slide_deck."""
    sm = SessionManager()
    deck = SlideDeck.from_dict(sm.get_slide_deck(OWNER_SID))
    deck.remove_slide(index)
    ChatService._reindex_slide_ids(deck)
    sm.save_slide_deck(
        session_id=OWNER_SID,
        title=deck.title,
        html_content=deck.knit(),
        scripts_content=deck.scripts,
        slide_count=len(deck.slides),
        deck_dict=deck.to_dict(),
    )


def test_a_verdict_computed_before_a_ui_delete_lands_on_its_slide(db):
    """The judge read slide C at index 2, the user then deleted slide A, so index 2
    no longer exists.  The verdict still names C's content, so it reaches C (now at
    1) rather than being dropped with an out-of-range warning; B is untouched."""
    seed = _plain_rows(db, ("MK-ALPHA", "MK-BRAVO", "MK-CHARLIE"))
    _ui_delete(0)
    assert [_marker(r.html) for r in _raw_rows(db, seed["owner_pk"])] == [
        "MK-BRAVO",
        "MK-CHARLIE",
    ], "the delete did not happen"
    before = _records_by_marker(db, seed["owner_pk"])
    incoming = {compute_slide_hash(_html("MK-CHARLIE")): _judge_verdict("MK-CHARLIE")}

    SessionManager().write_slide_verification(OWNER_SID, 2, incoming)

    after = _records_by_marker(db, seed["owner_pk"])
    assert after["MK-BRAVO"] == before["MK-BRAVO"]
    assert after["MK-CHARLIE"] == _merged(before["MK-CHARLIE"], incoming), (
        "slide C's verdict was dropped because its old index is past the shrunk deck"
    )


def test_a_verdict_whose_hash_matches_no_row_is_written_at_position(db):
    """Today's behaviour, kept: no row's HTML hashes to the key."""
    seed = _plain_rows(db, ("MK-ALPHA", "MK-BRAVO"))
    before = _records_by_marker(db, seed["owner_pk"])
    incoming = {compute_slide_hash(_html("MK-ELSEWHERE")): _judge_verdict("MK-ELSEWHERE")}

    SessionManager().write_slide_verification(OWNER_SID, 1, incoming)

    after = _records_by_marker(db, seed["owner_pk"])
    assert after["MK-ALPHA"] == before["MK-ALPHA"]
    assert after["MK-BRAVO"] == _merged(before["MK-BRAVO"], incoming)


def test_two_identical_rows_and_a_non_matching_position_fall_back_to_position(db):
    """Two rows share the key's hash, so "the unique row" does not exist: the
    verdict goes to *position*, and neither twin is touched."""
    twin_html = _html("MK-TWIN")
    rows = {
        0: _row("MK-TWIN", {"h0": {"explanation": "TWIN-FIRST"}}, html=twin_html),
        1: _row("MK-TWIN", {"h1": {"explanation": "TWIN-SECOND"}}, html=twin_html),
        2: _row("MK-YANKEE", _record([], _html("MK-YANKEE"))),
    }
    seed = _seed(db, rows)
    before = _records_by_slide_id(db, seed["owner_pk"])
    yankee_id = rows[2]["slide_id"]
    incoming = {compute_slide_hash(twin_html): _judge_verdict("MK-TWIN")}

    SessionManager().write_slide_verification(OWNER_SID, 2, incoming)

    after = _records_by_slide_id(db, seed["owner_pk"])
    assert after[yankee_id] == _merged(before[yankee_id], incoming)
    for twin in (rows[0]["slide_id"], rows[1]["slide_id"]):
        assert after[twin] == before[twin], f"twin {twin} took the verdict"


def test_a_record_without_exactly_one_key_is_written_at_position(db):
    """The content lookup needs THE record's key.  A two-key record (one of which
    is A's hash) written at position 1 goes to position 1, as today."""
    seed = _plain_rows(db, ("MK-ALPHA", "MK-BRAVO"))
    before = _records_by_marker(db, seed["owner_pk"])
    incoming = {
        compute_slide_hash(_html("MK-ALPHA")): _judge_verdict("MK-ALPHA"),
        compute_slide_hash(_html("MK-OTHER")): _judge_verdict("MK-OTHER"),
    }

    SessionManager().write_slide_verification(OWNER_SID, 1, incoming)

    after = _records_by_marker(db, seed["owner_pk"])
    assert after["MK-ALPHA"] == before["MK-ALPHA"]
    assert after["MK-BRAVO"] == _merged(before["MK-BRAVO"], incoming)
