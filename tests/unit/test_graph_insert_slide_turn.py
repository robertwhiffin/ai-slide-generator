# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""Graph-level acceptance for #314: an insert keeps every existing slide intact
and builds only the new one (plan Task 6; D3, D4).

Every turn here runs through the COMPILED graph (``build_graph(checkpointer=
False)``) on a real file-backed SQLite database: architect, foreman, the per-slide
pipeline, the deck reviewer and every row writer are the shipped code.  Only the
models are stubbed (``SkillStub``), and every stub records its calls.

How this file asserts, and why (executing-plans-tellr §1 and §7: a shift is the
place where a slide's identity, attribution, verdicts and findings silently end
up on a different slide):

* **A slide is found by the marker in its own HTML** (the builder writes
  ``<h1>{purpose}</h1>``), never by position or count.  "Row 3 has a verdict"
  and "there are five rows" are both true of a mis-attributed deck.
* **An existing slide is compared WHOLE**: every column but ``position`` and
  ``id`` (slide_id, html, scripts, authorship, timestamps, verification record,
  spec fragment).  The two JSON columns are compared parsed and every seed has
  non-NULL scripts (PLAN-CORRECTIONS C6).  Authorship and timestamps are set
  distinct per row after the build, so a row that kept its POSITION's author
  instead of its slide's shows.
* **Findings and the judge verdict are read through ``get_slide_deck``**, the
  surface the drawer and the verify badge consume, and each finding is tied back
  to its slide through the content hash inside its own id.
* **Model calls are sliced per turn**, so "only the new slide is built" is an
  exact list of positions, with no fixer call.
* No assertion pins the slide number inside a notice text (#332 owns notices);
  the failure variant asserts only that a notice row exists.

Sabotage map (each run in the real tree, one at a time):

1. ``NO_ATTRIBUTION`` for moved rows in ``insert_pending_slides`` -> every
   by-marker whole-row equality after an insert;
2. snapshot only html/scripts/slide_id -> the same (a moved row keeps its
   position's authorship and timestamps);
3. targets by position on an insert -> ``[2, 3, 4]`` built (gapped: ``[1, 3]``);
4. remove Task 3's ``slideIndex`` override -> purpose-3's finding is shown on
   purpose-2's slide;
5. remove the spec write from the shift AND make the architect's pre-fan-out
   write raise on an insert turn (only the ``deck_spec=`` write, C13) -> turn 3
   is refused ``spec_positions_stale``, and rows != spec after a dead turn;
6. re-stamp by the model's position instead of the index -> the gapped insert
   whose model keeps the old numbers persists a gapped spec.  (Keying
   ``SlideAlignment.old_to_new_index`` by list index stays green here: no
   production code reads that field; ``test_slide_alignment.py`` pins it.)
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import (
    PENDING_SLIDE_TEXT,
    SlideWriter,
    is_placeholder_verdict,
)
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.domain.deck_spec import DeckSpec, SlideSpec
from src.domain.finding import VERDICT_KEY, DeckReviewOutput
from src.domain.skill_io import (
    AnalystOutput,
    ArchitectOutput,
    BuilderOutput,
    DataRequest,
)
from src.services.foreman_service import CAP
from src.services.graph.builder import build_graph
from src.services.persisted_graph_release import PinnedInvocationEndpointError
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env_threadsafe is a fixture
    architect_build,
    finding,
    fixer_out,
    graph_env_threadsafe,
    make_spec,
    review_out,
)

USER = "graph-user@example.com"  # GraphEnv.state()'s initiated_by
NEW = "purpose-NEW"
#: The slides the build reviewer gives a subjective finding (turn 1: positions 1, 3).
FLAGGED = frozenset({"purpose-1", "purpose-3"})
JUDGE = {"marker": "JUDGE-purpose-2", "score": 90}
REVISED_BRIEF = "brief-3 REVISED after the insert"

#: The pending placeholder (plan D4 step 3), written out literally so the oracle
#: does not depend on the code under test.
PENDING_MESSAGE = "Inserted slide not yet built"
PENDING_HTML = (
    f'<div class="slide-placeholder-error" data-error="{PENDING_MESSAGE}">'
    "<p>New slide — not built yet.</p>"
    "</div>"
)
#: The failed placeholder's copy (``commit_placeholder``).
FAILED_TEXT = "Slide generation failed."

_H1 = re.compile(r"<h1>(.*?)</h1>")
_SLIDE_COLUMNS = [c.name for c in SessionSlide.__table__.columns]
_JSON_COLUMNS = ("verification_record", "deck_spec_slide")


# ---------------------------------------------------------------------------
# Model stubs
# ---------------------------------------------------------------------------


def _slide_html(purpose: str, brief: str) -> str:
    return f'<div class="slide"><h1>{purpose}</h1><p>{brief}</p></div>'


def _builder(payload: dict) -> BuilderOutput:
    """Writes the slide's purpose (its marker) and brief, so a rebuild shows."""
    spec = payload["slide_spec"]
    return BuilderOutput(
        position=payload["position"],
        html=_slide_html(spec["purpose"], spec["content_brief"]),
        scripts=f"window.builtSlide = '{spec['purpose']}';",
    )


def _build_reviewer(payload: dict):
    """A subjective ``brief_not_delivered`` finding on the FLAGGED slides only.

    Keyed by the slide's purpose, not its position, so a finding belongs to a
    slide's content however it is numbered.  Subjective, so no fixer runs.
    """
    purpose = payload["slide_spec"]["purpose"]
    findings = (
        [
            finding(
                "brief_not_delivered",
                slide_index=payload["position"],
                message=f"{purpose} does not deliver its brief",
            )
        ]
        if purpose in FLAGGED
        else []
    )
    return review_out(payload["position"], findings)


def _wire(env) -> None:
    env.skills.set("builder", _builder)
    env.skills.set("build_reviewer", _build_reviewer)
    env.skills.set("fixer", fixer_out)
    env.skills.set("fix_reviewer", lambda payload: review_out(payload["position"]))
    env.skills.set("deck_reviewer", DeckReviewOutput(findings=[]))


def _edit(spec: DeckSpec, targets: Sequence[int], message: str = "Editing.") -> ArchitectOutput:
    return ArchitectOutput(
        intent="edit", message=message, target_positions=list(targets), deck_spec=spec
    )


def _new_slide() -> SlideSpec:
    return SlideSpec(
        position=0,
        purpose=NEW,
        content_brief="brief-NEW",
        assumes="assumes-NEW",
        hands_off="hands-off-NEW",
        data_references=[],
    )


def _with_slides(base: DeckSpec, placed: Sequence[Tuple[int, SlideSpec]]) -> DeckSpec:
    """*base*'s deck-level fields with exactly *placed* as its slides."""
    data = base.model_dump()
    data["slides"] = [{**s.model_dump(), "position": p} for p, s in placed]
    return DeckSpec.model_validate(data)


def _inserted(base: DeckSpec, at: int) -> DeckSpec:
    """*base* with the new slide inserted at index *at*, re-stamped ``0..n``."""
    slides = sorted(base.slides, key=lambda s: s.position)
    slides.insert(at, _new_slide())
    return _with_slides(base, list(enumerate(slides)))


def _revised_at(base: DeckSpec, position: int, brief: str) -> DeckSpec:
    return base.model_copy(
        update={
            "slides": [
                s.model_copy(update={"content_brief": brief})
                if s.position == position
                else s
                for s in base.slides
            ]
        }
    )


# ---------------------------------------------------------------------------
# Running a turn, and reading what it did
# ---------------------------------------------------------------------------


def _invoke(env, turn_id: str) -> Dict[str, Any]:
    graph = build_graph(checkpointer=False)
    return graph.invoke(env.state(turn_id=turn_id), {"max_concurrency": CAP})


def _positions(calls: List[dict], name: str) -> List[int]:
    return sorted(c["payload"]["position"] for c in calls if c["name"] == name)


def _decoded(row: SessionSlide) -> Dict[str, Any]:
    out = {name: getattr(row, name) for name in _SLIDE_COLUMNS}
    for name in _JSON_COLUMNS:
        out[name] = json.loads(out[name]) if out[name] is not None else None
    return out


def _rows(env) -> List[Dict[str, Any]]:
    """Every row of this session, whole, in position order."""
    return [_decoded(r) for r in env.rows()]


def _marker(html: Optional[str]) -> Optional[str]:
    found = _H1.findall(html or "")
    assert len(found) <= 1, f"a row's HTML carries more than one marker: {found}"
    return found[0] if found else None


def _by_marker(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        marker = _marker(row["html"])
        if marker is None:
            continue
        assert marker not in out, f"two rows carry {marker}: a slide was duplicated"
        out[marker] = row
    return out


def _identity(row: Dict[str, Any]) -> Dict[str, Any]:
    """The whole row minus the two columns a shift legitimately changes."""
    return {k: v for k, v in row.items() if k not in ("position", "id")}


def _layout(rows: List[Dict[str, Any]]) -> List[str]:
    out = []
    for row in rows:
        marker = _marker(row["html"])
        if marker is not None:
            out.append(marker)
        elif row["html"] == PENDING_HTML:
            out.append("PENDING")
        elif FAILED_TEXT in (row["html"] or ""):
            out.append("FAILED")
        else:
            out.append(f"OTHER:{row['html']}")
    return out


def _current_verdict(row: Dict[str, Any]) -> Any:
    return (row["verification_record"] or {}).get(compute_slide_hash(row["html"] or ""))


def _persisted_spec(env) -> DeckSpec:
    spec = DeckSpec.from_json(env.deck_row().deck_spec_json)
    assert spec is not None
    return spec


def _deck(env) -> Dict[str, Any]:
    deck = SessionManager().get_slide_deck(env.session_id)
    assert deck is not None
    return deck


def _info_notices(env) -> List[str]:
    return [m["content"] for m in env.messages() if m["message_type"] == "info"]


def _insert_events(env) -> int:
    db = env.factory()
    try:
        return (
            db.query(SharedDeckMutationEvent)
            .filter(SharedDeckMutationEvent.operation == "insert_slide")
            .count()
        )
    finally:
        db.close()


def _assert_old_rows_intact(rows, before: Dict[str, Dict[str, Any]]) -> None:
    after = _by_marker(rows)
    for marker, old in before.items():
        assert marker in after, f"{marker}'s slide is gone"
        assert _identity(after[marker]) == _identity(old), (
            f"{marker}'s row changed (identity, authorship, timestamps, verification "
            "record or spec fragment did not travel with its slide)"
        )


def _assert_rows_match_the_spec(env) -> None:
    """Rows are exactly the persisted spec's positions (D4's rollback guarantee)."""
    spec = _persisted_spec(env)
    assert [r.position for r in env.rows()] == sorted(s.position for s in spec.slides)


def _spy_on_the_shift(monkeypatch) -> List[List[str]]:
    """Record the new slide_ids every ``insert_pending_slides`` call returns."""
    real = SlideWriter.insert_pending_slides
    returned: List[List[str]] = []

    def spy(self, *args, **kwargs):
        ids = real(self, *args, **kwargs)
        returned.append(list(ids))
        return ids

    monkeypatch.setattr(SlideWriter, "insert_pending_slides", spy)
    return returned


def _stamp_authorship(env) -> None:
    """Distinct created_by/created_at/modified_by/modified_at per row, by marker."""
    db = env.factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        )
        rows = (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == owner.id)
            .order_by(SessionSlide.position)
            .all()
        )
        for day, row in enumerate(rows, start=1):
            marker = _marker(row.html)
            row.created_by = f"author-{marker}@example.com"
            row.created_at = datetime(2024, 1, day, 9, 0, 0)
            row.modified_by = f"editor-{marker}@example.com"
            row.modified_at = datetime(2024, 2, day, 17, 30, 0)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Turn 1: build a four-slide deck, then give every slide a history of its own
# ---------------------------------------------------------------------------


def _turn_1(env) -> Tuple[DeckSpec, Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Build ``make_spec((0, 1, 2, 3))``; return (spec, row snapshot, findings by id).

    After the build: a judge verdict is merged into slide 2's current-hash slot,
    and every row gets distinct authorship and timestamps.
    """
    _wire(env)
    spec = make_spec((0, 1, 2, 3))
    env.skills.set("architect", architect_build(spec))
    _invoke(env, "turn-1-build")

    rows = env.rows()
    assert [(r.position, _marker(r.html)) for r in rows] == [
        (p, f"purpose-{p}") for p in range(4)
    ], "precondition: turn 1 built the four slides"
    SessionManager().write_slide_verification(
        env.session_id, 2, {compute_slide_hash(rows[2].html): dict(JUDGE)}
    )
    _stamp_authorship(env)

    before = _by_marker(_rows(env))
    assert len({r["slide_id"] for r in before.values()}) == 4
    assert all(r["scripts"] for r in before.values())
    assert _current_verdict(before["purpose-2"])["marker"] == JUDGE["marker"]
    findings = {f["id"]: f for f in _deck(env)["findings"]}
    assert sorted(f["slideIndex"] for f in findings.values()) == [1, 3], (
        "precondition: turn 1 left a subjective finding on slides 1 and 3"
    )
    return spec, before, findings


def _turn_2_insert(env, spec: DeckSpec) -> Tuple[Dict[str, Any], List[dict]]:
    """The architect inserts ``purpose-NEW`` at 2 (re-stamped 0..4), targeting [2]."""
    env.skills.set("architect", _edit(_inserted(spec, 2), [2], "Adding a slide."))
    start = len(env.skills.calls)
    final = _invoke(env, "turn-2-insert")
    return final, env.skills.calls[start:]


def _turn_3_revise_slide_3(env, spec: DeckSpec) -> Tuple[Dict[str, Any], List[dict]]:
    """An ordinary edit of ``purpose-3``'s brief at its NEW position 4.

    The model's spec is the post-insert deck (*spec* is turn 1's), not read back
    from the database: whether the node accepts it is decided from the PERSISTED
    spec and the rows (``spec_positions_stale``), which is what is under test.
    """
    after_insert = _inserted(spec, 2)
    assert after_insert.slide_at(4).purpose == "purpose-3"
    env.skills.set(
        "architect", _edit(_revised_at(after_insert, 4, REVISED_BRIEF), [4], "Revising.")
    )
    start = len(env.skills.calls)
    final = _invoke(env, "turn-3-revise")
    return final, env.skills.calls[start:]


# ---------------------------------------------------------------------------
# The insert turn
# ---------------------------------------------------------------------------


class TestAnInsertTurn:
    def test_only_the_new_slide_is_built_and_every_existing_slide_is_intact(
        self, graph_env_threadsafe, monkeypatch
    ):
        env = graph_env_threadsafe
        spec, before, findings_before = _turn_1(env)
        pending_ids = _spy_on_the_shift(monkeypatch)

        final, calls = _turn_2_insert(env, spec)

        assert final["architect_intent"] == "edit"
        assert final["error_state"] is None
        assert final["target_positions"] == [2]

        # D3: the builder and the build reviewer ran for the new slide only.
        assert _positions(calls, "builder") == [2]
        assert _positions(calls, "build_reviewer") == [2]
        assert _positions(calls, "fixer") == []
        assert _positions(calls, "fix_reviewer") == []
        built = [c for c in calls if c["name"] == "builder"][0]
        assert built["payload"]["slide_spec"]["purpose"] == NEW

        # D4: every existing slide kept its whole row; the order is by marker.
        rows = _rows(env)
        assert [r["position"] for r in rows] == [0, 1, 2, 3, 4]
        assert _layout(rows) == ["purpose-0", "purpose-1", NEW, "purpose-2", "purpose-3"]
        _assert_old_rows_intact(rows, before)

        # The new slide is built (not a placeholder) in the pending row it was
        # given, so it kept the pending row's slide_id.
        assert len(pending_ids) == 1 and len(pending_ids[0]) == 1
        new_row = _by_marker(rows)[NEW]
        assert new_row["position"] == 2
        assert new_row["slide_id"] == pending_ids[0][0]
        assert new_row["slide_id"] not in {r["slide_id"] for r in before.values()}
        assert not is_placeholder_verdict(_current_verdict(new_row))
        assert VERDICT_KEY in _current_verdict(new_row), "the new slide was not reviewed"
        assert new_row["html"] != PENDING_HTML
        assert _insert_events(env) == 1

        # D7/D8 through the read surface: findings follow their slide, and the
        # judge verdict is on purpose-2's slide (now index 3).
        deck = _deck(env)
        slides = deck["slides"]
        assert [_marker(s["html"]) for s in slides] == _layout(rows)
        findings_after = {f["id"]: f for f in deck["findings"]}
        assert set(findings_after) == set(findings_before)
        for finding_id, f in findings_after.items():
            assert slides[f["slideIndex"]]["content_hash"] in finding_id, (
                f"finding {finding_id} is shown on slide {f['slideIndex']}, which is "
                "not the slide it was minted for"
            )
            assert {k: v for k, v in f.items() if k != "slideIndex"} == {
                k: v for k, v in findings_before[finding_id].items() if k != "slideIndex"
            }
        assert sorted(
            (_marker(slides[f["slideIndex"]]["html"]), f["slideIndex"])
            for f in findings_after.values()
        ) == [("purpose-1", 1), ("purpose-3", 4)]
        assert _marker(slides[3]["html"]) == "purpose-2"
        assert slides[3]["verification"]["marker"] == JUDGE["marker"]

        # The persisted spec is the canonical 0..4 spec, and every row's spec
        # fragment is the spec entry at that row's position.
        persisted = _persisted_spec(env)
        assert [s.position for s in persisted.slides] == [0, 1, 2, 3, 4]
        assert [s.purpose for s in persisted.slides] == [
            "purpose-0", "purpose-1", NEW, "purpose-2", "purpose-3"
        ]
        assert persisted == _inserted(spec, 2)
        for row in rows:
            entry = persisted.slide_at(row["position"])
            assert row["deck_spec_slide"]["purpose"] == entry.purpose == _marker(row["html"])


    def test_the_next_edit_targets_a_shifted_slide_at_its_new_position(
        self, graph_env_threadsafe
    ):
        """Turn 3 revises purpose-3 at 4: accepted (not ``spec_positions_stale``),
        rebuilt in place, and nothing else touched."""
        env = graph_env_threadsafe
        spec, _, _ = _turn_1(env)
        _turn_2_insert(env, spec)
        before = _by_marker(_rows(env))

        final, calls = _turn_3_revise_slide_3(env, spec)

        assert (final["architect_intent"], final["error_state"]) == ("edit", None), (
            final["error_state"]
        )
        assert final["target_positions"] == [4]
        assert _positions(calls, "builder") == [4]
        built = [c for c in calls if c["name"] == "builder"][0]
        assert built["payload"]["slide_spec"]["purpose"] == "purpose-3"
        assert built["payload"]["slide_spec"]["content_brief"] == REVISED_BRIEF

        rows = _rows(env)
        assert _layout(rows) == ["purpose-0", "purpose-1", NEW, "purpose-2", "purpose-3"]
        rebuilt = _by_marker(rows)["purpose-3"]
        old = before["purpose-3"]
        assert rebuilt["position"] == 4
        assert rebuilt["html"] == _slide_html("purpose-3", REVISED_BRIEF)
        assert rebuilt["slide_id"] == old["slide_id"]
        # created_at stays; created_by is NOT pinned: write_slide's partial update
        # overwrites it with the rebuilding user on every rebuild in place
        # (pre-existing, not #314).
        assert rebuilt["created_at"] == old["created_at"]
        assert rebuilt["deck_spec_slide"]["content_brief"] == REVISED_BRIEF
        _assert_old_rows_intact(
            rows, {m: r for m, r in before.items() if m != "purpose-3"}
        )


# ---------------------------------------------------------------------------
# The new slide's build fails, or the turn dies after the shift
# ---------------------------------------------------------------------------


class TestAnInsertTurnThatFails:
    def test_a_failed_build_leaves_a_failed_placeholder_and_the_deck_aligned(
        self, graph_env_threadsafe
    ):
        env = graph_env_threadsafe
        spec, before, _ = _turn_1(env)

        def _failing(payload):
            if payload["slide_spec"]["purpose"] == NEW:
                raise RuntimeError("the builder crashed")
            return _builder(payload)

        env.skills.set("builder", _failing)
        notices_before = len(_info_notices(env))

        final, calls = _turn_2_insert(env, spec)

        failed_turn_notices = _info_notices(env)[notices_before:]
        assert final["architect_intent"] == "edit"
        assert _positions(calls, "builder") == [2]
        rows = _rows(env)
        assert _layout(rows) == ["purpose-0", "purpose-1", "FAILED", "purpose-2", "purpose-3"]
        assert is_placeholder_verdict(_current_verdict(rows[2]))
        _assert_old_rows_intact(rows, before)
        _assert_rows_match_the_spec(env)

        env.skills.set("builder", _builder)
        notices_before = len(_info_notices(env))
        final, calls = _turn_3_revise_slide_3(env, spec)
        clean_turn_notices = _info_notices(env)[notices_before:]

        assert (final["architect_intent"], final["error_state"]) == ("edit", None), (
            final["error_state"]
        )
        assert _positions(calls, "builder") == [4]
        assert _by_marker(_rows(env))["purpose-3"]["html"] == _slide_html(
            "purpose-3", REVISED_BRIEF
        )
        # A failure notice row exists: the failed turn posted an info notice that
        # a clean turn (the deck reviewer's summary) does not.  Its text is not
        # pinned (#332 owns notices).
        assert set(failed_turn_notices) - set(clean_turn_notices), (
            f"no failure notice: the failed turn posted {failed_turn_notices}, a "
            f"clean turn posts {clean_turn_notices}"
        )

    def test_a_turn_that_dies_after_the_shift_leaves_a_pending_slide_the_next_edit_builds(
        self, graph_env_threadsafe, monkeypatch
    ):
        """Finding 15: a non-transient runtime failure kills the turn after the
        shift.  The pending placeholder stays, rows equal the spec, and the next
        edit that targets the new slide is accepted and builds it from its brief."""
        env = graph_env_threadsafe
        spec, before, _ = _turn_1(env)
        pending_ids = _spy_on_the_shift(monkeypatch)

        def _dies(payload):
            raise PinnedInvocationEndpointError(
                endpoint_name="x", graph_release_id=1, agent_definition_revision_id=1
            )

        env.skills.set("builder", _dies)

        with pytest.raises(PinnedInvocationEndpointError):
            _turn_2_insert(env, spec)

        rows = _rows(env)
        _assert_rows_match_the_spec(env)
        assert _layout(rows) == ["purpose-0", "purpose-1", "PENDING", "purpose-2", "purpose-3"]
        pending = rows[2]
        assert PENDING_SLIDE_TEXT in pending["html"]
        assert is_placeholder_verdict(_current_verdict(pending))
        assert [pending["slide_id"]] == pending_ids[0]
        _assert_old_rows_intact(rows, before)

        env.skills.set("builder", _builder)
        env.skills.set("architect", _edit(_inserted(spec, 2), [2], "Building it."))
        start = len(env.skills.calls)
        final = _invoke(env, "turn-3-build-the-pending-slide")
        calls = env.skills.calls[start:]

        assert (final["architect_intent"], final["error_state"]) == ("edit", None), (
            final["error_state"]
        )
        assert _positions(calls, "builder") == [2]
        rows = _rows(env)
        assert _layout(rows) == ["purpose-0", "purpose-1", NEW, "purpose-2", "purpose-3"]
        built = rows[2]
        assert built["html"] == _slide_html(NEW, "brief-NEW")
        assert built["slide_id"] == pending["slide_id"]
        assert not is_placeholder_verdict(_current_verdict(built))
        _assert_old_rows_intact(rows, before)


# ---------------------------------------------------------------------------
# A gapped deck (finding 1)
# ---------------------------------------------------------------------------


def _seed_gapped(env, spec: DeckSpec) -> None:
    """Rows at *spec*'s positions, each carrying its slide's marker and a rich row.

    ``seed_slides`` enumerates ``0..n-1``, so the gaps are seeded through the ORM.
    Each row's spec fragment is its own spec entry, so a fragment left on a
    position (rather than its slide) would describe another slide.
    """
    db = env.factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        )
        db.add(
            SessionSlideDeck(
                session_id=owner.id,
                html_content="",
                scripts_content=None,
                slide_count=len(spec.slides),
                version=1,
            )
        )
        for day, slide in enumerate(spec.slides, start=1):
            html = _slide_html(slide.purpose, slide.content_brief)
            history = compute_slide_hash(f"<p>an earlier draft of {slide.purpose}</p>")
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=slide.position,
                    id=str(uuid.uuid4()),
                    slide_id=f"sid-{slide.purpose}-{uuid.uuid4().hex[:8]}",
                    html=html,
                    scripts=f"window.seeded = '{slide.purpose}';",
                    created_by=f"author-{slide.purpose}@example.com",
                    created_at=datetime(2024, 1, day, 9, 0, 0),
                    modified_by=f"editor-{slide.purpose}@example.com",
                    modified_at=datetime(2024, 2, day, 17, 30, 0),
                    verification_record=json.dumps(
                        {
                            history: {"score": 41, "explanation": f"HISTORY-{slide.purpose}"},
                            compute_slide_hash(html): {
                                "score": 92,
                                "explanation": f"CURRENT-{slide.purpose}",
                            },
                        }
                    ),
                    deck_spec_slide=json.dumps(slide.model_dump()),
                )
            )
        db.commit()
    finally:
        db.close()

    from src.api.services.deck_level_writer import write_deck_level_columns

    write_deck_level_columns(env.session_id, deck_spec=spec.to_json())


class TestAGappedDeck:
    @pytest.mark.parametrize(
        "model_positions",
        [(0, 1, 2, 3), (0, 1, 2, 5)],
        ids=["model-restamps", "model-keeps-old-numbers"],
    )
    def test_an_insert_after_the_first_slide_makes_rows_and_spec_contiguous(
        self, graph_env_threadsafe, model_positions
    ):
        env = graph_env_threadsafe
        _wire(env)
        prior = make_spec((0, 2, 5))
        _seed_gapped(env, prior)
        before = _by_marker(_rows(env))
        assert sorted(r["position"] for r in before.values()) == [0, 2, 5]
        first, second, third = prior.slides
        model_spec = _with_slides(
            prior, list(zip(model_positions, [first, _new_slide(), second, third]))
        )
        env.skills.set("architect", _edit(model_spec, [1], "Adding a slide."))
        start = len(env.skills.calls)

        final = _invoke(env, "turn-gapped-insert")
        calls = env.skills.calls[start:]

        assert final["architect_intent"] == "edit"
        assert final["error_state"] is None, final["error_state"]
        assert _positions(calls, "builder") == [1]
        assert _positions(calls, "build_reviewer") == [1]
        rows = _rows(env)
        assert [r["position"] for r in rows] == [0, 1, 2, 3]
        assert _layout(rows) == ["purpose-0", NEW, "purpose-2", "purpose-5"]
        _assert_old_rows_intact(rows, before)
        persisted = _persisted_spec(env)
        assert [s.position for s in persisted.slides] == [0, 1, 2, 3]
        assert [s.purpose for s in persisted.slides] == [
            "purpose-0", NEW, "purpose-2", "purpose-5"
        ]
        for row in rows:
            assert row["deck_spec_slide"]["purpose"] == persisted.slide_at(
                row["position"]
            ).purpose


# ---------------------------------------------------------------------------
# The ask_data loop: the architect runs twice in one turn (finding 7)
# ---------------------------------------------------------------------------


class TestAnInsertAfterAskData:
    def test_the_rows_shift_once_and_only_the_new_slide_is_built(
        self, graph_env_threadsafe
    ):
        env = graph_env_threadsafe
        spec, before, _ = _turn_1(env)
        answers = iter(
            [
                ArchitectOutput(
                    intent="ask_data",
                    message="Let me fetch the figures first.",
                    data_request=DataRequest(metric="quarterly revenue"),
                ),
                _edit(_inserted(spec, 2), [2], "Adding a slide with the figures."),
            ]
        )
        env.skills.set("architect", lambda payload: next(answers))
        env.skills.set(
            "data_analyst",
            AnalystOutput(outcome="success", synthesis="Revenue grew 12%.", sources=["s"]),
        )
        start = len(env.skills.calls)

        final = _invoke(env, "turn-2-ask-data")
        calls = env.skills.calls[start:]

        assert [c["name"] for c in calls if c["name"] in ("architect", "data_analyst")] == [
            "architect",
            "data_analyst",
            "architect",
        ]
        assert final["architect_intent"] == "edit"
        assert _insert_events(env) == 1
        assert _positions(calls, "builder") == [2]
        rows = _rows(env)
        assert _layout(rows) == ["purpose-0", "purpose-1", NEW, "purpose-2", "purpose-3"]
        _assert_old_rows_intact(rows, before)
