# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""``architect_node`` applies an edit's operations (architect edit operations, plan
Task 4; spec §4, §6; PLAN-CORRECTIONS C3, C6, C7, C8; C19 in section 6b).

An ``edit`` answer that carries ``operations`` and/or ``deck_changes`` takes the
"operations path": the node composes the next spec deterministically
(``apply_operations`` + ``compose_edit_spec`` + the binding helpers), lays the rows
out in ONE transaction with ``SlideWriter.apply_slide_layout`` (only when the
layout is not the identity), and targets exactly the inserted, updated and
replaced slides (``rebuild``) in the composed numbering.  An edit without either
field takes today's alignment path unchanged; build, discuss and describe-only
turns ignore both fields with an INFO ``operations_ignored``.

How this file asserts, and why (the oracle of ``test_architect_insert_slide``):

* **Rows are read whole and found by the marker in their own HTML** (a blank row,
  which has no text, by its ``slide_id``), never by position, count or picked
  keys.  An untouched, moved or replaced-in-place row must equal its old self in
  every column but ``position`` and ``id``; an inserted index holds the pending
  placeholder, written out literally; a deleted row is absent.
* **The persisted ``deck_spec`` is read back from the database** and compared
  whole against the composed spec built by hand here: every slide's content in
  order, re-stamped ``0..m-1``.
* **The writes are counted**: the deck ``version`` delta, the mutation events the
  turn recorded (operation and object type, in order), and the arguments
  ``apply_slide_layout`` was called with (row INDICES, not persisted positions —
  C7; the gapped rows are what separate the two).
* **"Nothing changed" is a whole-database snapshot** (every slide column, every
  deck column and the mutation-event count).
* A degrade asserts the exact user sentence, the ``error_state`` code and
  message, ``target_positions is None`` and that the refusal is said on both
  surfaces.  Whether the model's own line is said before it is Task 5's change
  (spec §7), so both orders are accepted here.
* A named log is found by its name in the record's message or an ``extra`` field.
"""

from __future__ import annotations

import contextlib
import copy
import inspect
import json
import logging
import queue
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import pytest

from src.api.schemas.streaming import StreamEventType
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import SlideRowsChangedError, SlideWriter
from src.database.models.session import (
    SessionSlide,
    SharedDeckMutationEvent,
    UserSession,
)
from src.domain.deck_spec import DeckSpec, DesignContractRef, SlideSpec
from src.domain.deck_spec_slides import BLANK_DECK_SPEC_ENTRY
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_operations import DeckChanges, SlideContent, SlideOperation
from src.services.graph import nodes
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import architect_node, build_branch_payload
from src.services.graph.routers import architect_router, foreman_router
from src.services.graph.state import scoped
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    TEMPLATE_TOKEN_CSS,
    _build_env,
    finding,
    graph_env,
    make_spec,
    review_out,
)
from tests.unit.test_architect_insert_slide import (
    NODES_LOGGER,
    PENDING_HASH,
    PENDING_HTML,
    PENDING_VERDICT,
    TURN,
    USER,
    _assert_shifted,
    _by_marker,
    _canonical,
    _db_state,
    _edit_out,
    _marker,
    _named,
    _new,
    _persist,
    _persisted_spec,
    _rows,
    _seed_rows,
    _spec_of,
    _spy_on_the_shift,
)

#: The degrade sentence's fixed opening (plan Task 4, "Problems").
REJECTED_PREFIX = "I couldn't apply that edit, so nothing in the deck has changed: "

#: A deck-derived blank frame (as in test_architect_blank_slides).
SHELL = '<section data-label="G"><div class="slide"></div></section>'

NEW_AUDIENCE = "the CFO, not engineers"
RESTYLED = DesignContractRef(design_system_id=7, template_id=3, slide_style_id=None)

_WORDS = (
    "ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF", "HOTEL",
    "INDIA", "JULIET", "KILO", "LIMA", "MIKE", "NOVEMBER", "OSCAR", "PAPA",
    "QUEBEC", "ROMEO", "SIERRA", "TANGO", "UNIFORM", "VICTOR",
)


def _mk(i: int) -> str:
    """The marker of the i-th seeded row (letters only: the marker regex is MK-[A-Z]+)."""
    return f"MK-{_WORDS[i]}"


# ---------------------------------------------------------------------------
# Operations and answers
# ---------------------------------------------------------------------------


def _content(tag: str) -> SlideContent:
    return SlideContent(
        purpose=f"purpose {tag}",
        content_brief=f"brief {tag}",
        assumes=f"assumes {tag}",
        hands_off=f"hands-off {tag}",
        data_references=[f"ref-{tag}"],
    )


def _spec_from(content: SlideContent) -> SlideSpec:
    """The SlideSpec a SlideContent describes (re-stamped later by ``_canonical``)."""
    return SlideSpec(position=0, **content.model_dump())


def _insert(after: int, *slides: SlideContent) -> SlideOperation:
    return SlideOperation(op="insert", after_position=after, slides=list(slides))


def _update(position: int, slide: SlideContent) -> SlideOperation:
    return SlideOperation(op="update", position=position, slides=[slide])


def _replace(position: int, *slides: SlideContent) -> SlideOperation:
    return SlideOperation(op="replace", position=position, slides=list(slides))


def _delete(position: int) -> SlideOperation:
    return SlideOperation(op="delete", position=position)


def _move(position: int, after: int) -> SlideOperation:
    return SlideOperation(op="move", position=position, after_position=after)


def _ops_out(
    operations: Optional[List[SlideOperation]] = None,
    deck_changes: Optional[DeckChanges] = None,
    *,
    targets: Sequence[int] = (),
    message: str = "Editing the deck.",
    deck_spec: Optional[DeckSpec] = None,
) -> ArchitectOutput:
    return ArchitectOutput(
        intent="edit",
        message=message,
        target_positions=list(targets),
        operations=operations,
        deck_changes=deck_changes,
        deck_spec=deck_spec,
    )


# ---------------------------------------------------------------------------
# Decks
# ---------------------------------------------------------------------------


def _seeded(env, positions: Sequence[int]) -> Tuple[DeckSpec, Dict[str, Dict[str, Any]]]:
    """Rich rows at *positions* (marker ``_mk(i)`` for the i-th) and a persisted
    ``make_spec(positions)``; returns the spec and the rows by marker, whole."""
    _seed_rows(env, {p: _mk(i) for i, p in enumerate(positions)})
    prior = make_spec(tuple(positions))
    _persist(env, prior)
    return prior, _by_marker(_rows(env))


def _blank_entry() -> SlideSpec:
    return SlideSpec(position=0, **copy.deepcopy(BLANK_DECK_SPEC_ENTRY))


def _seed_blank_row(env, position: int, label: str = "BLANK") -> None:
    """One committed blank row (no marker: found by its ``slide_id``), fully populated."""
    db = env.factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        )
        db.add(
            SessionSlide(
                session_id=owner.id,
                position=position,
                id=str(uuid.uuid4()),
                slide_id=f"sid-{label}-{uuid.uuid4().hex[:8]}",
                html=SHELL,
                scripts=f"console.log('{label}');",
                created_by=f"{label.lower()}-author@example.com",
                created_at=datetime(2024, 3, 1, 9, 0, 0),
                modified_by=f"{label.lower()}-editor@example.com",
                modified_at=datetime(2024, 4, 1, 17, 30, 0),
                verification_record=json.dumps(
                    {compute_slide_hash(SHELL): {"score": 90, "rating": "good",
                                                 "explanation": f"CURRENT-{label}"}}
                ),
                deck_spec_slide=json.dumps({"position": position, **BLANK_DECK_SPEC_ENTRY}),
            )
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Running a turn, and what it wrote
# ---------------------------------------------------------------------------


def _turn(env, out: ArchitectOutput, **state_overrides) -> SimpleNamespace:
    """Run ``architect_node`` once; return its state, updates, events and new rows."""
    env.skills.set("architect", out)
    before = len(env.messages())
    state = env.state(**state_overrides)
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    try:
        updates = architect_node(state)
    finally:
        set_event_emitter(None)
    events = []
    while not emitter.empty():
        events.append(emitter.get_nowait())
    added = env.messages()[before:]
    return SimpleNamespace(
        state=state,
        updates=updates,
        merged={**state, **updates},
        events=events,
        architect_lines=[
            e.content for e in events if (e.metadata or {}).get("node") == "architect"
        ],
        rows=added,
        said=[m.get("content") for m in added if m.get("message_type") == "llm_response"],
        notices=[m.get("content") for m in added if m.get("message_type") == "info"],
    )


def _events(env) -> List[Tuple[str, str]]:
    """Every mutation event of the database, oldest first: ``(operation, object_type)``."""
    db = env.factory()
    try:
        return [
            (e.operation, e.object_type)
            for e in db.query(SharedDeckMutationEvent)
            .order_by(SharedDeckMutationEvent.id)
            .all()
        ]
    finally:
        db.close()


def _version(env) -> int:
    return env.deck_row().version


def _planned(rows: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    return [(r["slide_id"], compute_slide_hash(r["html"])) for r in rows]


def _spy_on_the_layout(monkeypatch) -> List[Dict[str, Any]]:
    """Record every ``apply_slide_layout`` call (bound arguments), then run it."""
    real = SlideWriter.apply_slide_layout
    signature = inspect.signature(real)
    calls: List[Dict[str, Any]] = []

    def spy(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        calls.append({k: v for k, v in bound.arguments.items() if k != "self"})
        return real(self, *args, **kwargs)

    monkeypatch.setattr(SlideWriter, "apply_slide_layout", spy)
    return calls


def _assert_one_layout_call(env, calls, *, layout, planned, spec, operation):
    """The node's half of the contract with the writer (spec §6, C7)."""
    assert len(calls) == 1, f"expected one apply_slide_layout call, got {len(calls)}"
    call = calls[0]
    assert call["session_id"] == env.session_id
    assert list(call["layout"]) == list(layout), (
        "apply_slide_layout takes ROW INDICES; Task 1's layout holds persisted "
        "positions and must be mapped through the committed rows' order (C7)"
    )
    assert [tuple(r) for r in call["expected_rows"]] == planned
    assert DeckSpec.from_json(call["deck_spec"]) == spec
    assert call["created_by"] == USER
    mutation = call["mutation"]
    assert (mutation.operation, mutation.object_type) == (operation, "deck")
    assert mutation.actor.actor_session_id == env.session_id
    assert mutation.actor.graph_release_id == 1


def _assert_laid_out(
    env,
    before: Mapping[str, Dict[str, Any]],
    expected: Sequence[str],
) -> None:
    """The rows are ``0..len(expected)-1`` holding *expected* (labels or PENDING).

    *before* maps a label (a marker, or ``BLANK`` for a blank row) to the old row,
    whole.  Every labelled row equals its old self but for ``position`` and ``id``;
    a label of *before* missing from *expected* must be gone; every PENDING row is
    the pending placeholder, authored by the turn's user, with a fresh slide_id.
    """
    rows = _rows(env)
    assert [r["position"] for r in rows] == list(range(len(expected)))
    by_sid = {old["slide_id"]: label for label, old in before.items()}
    labels: List[str] = []
    for row in rows:
        marker = _marker(row["html"])
        if marker is not None:
            labels.append(marker)
        elif row["html"] == PENDING_HTML:
            labels.append("PENDING")
        else:
            labels.append(by_sid.get(row["slide_id"], f"OTHER:{row['html']}"))
    assert labels == list(expected)
    for row, label in zip(rows, labels):
        if label == "PENDING":
            continue
        old = before[label]
        assert {k: v for k, v in row.items() if k not in ("position", "id")} == {
            k: v for k, v in old.items() if k not in ("position", "id")
        }, (
            f"{label}'s row changed (slide_id, HTML, scripts, authorship, "
            "timestamps, verification record or spec fragment did not travel with it)"
        )
    pending = [r for r in rows if r["html"] == PENDING_HTML]
    old_ids = {old["slide_id"] for old in before.values()}
    for row in pending:
        assert row["verification_record"] == {PENDING_HASH: PENDING_VERDICT}
        assert row["scripts"] == ""
        assert row["created_by"] == USER
        assert row["modified_by"] == USER
        assert row["slide_id"] and row["slide_id"] not in old_ids
    assert len({r["slide_id"] for r in pending}) == len(pending)


def _assert_persisted(env, expected: DeckSpec) -> None:
    persisted = _persisted_spec(env)
    assert persisted is not None, "the deck_spec column does not hold a valid spec"
    assert [s.position for s in persisted.slides] == list(range(len(expected.slides)))
    assert [s.purpose for s in persisted.slides] == [s.purpose for s in expected.slides]
    assert persisted == expected


def _assert_refused(t: SimpleNamespace, code: str, user: str, message: Optional[str]):
    """A degrade: discuss, the code, the sentence, no targets, said on both surfaces."""
    updates = t.updates
    assert updates["architect_intent"] == "discuss"
    assert updates["error_state"]["node"] == "architect"
    assert updates["error_state"]["code"] == code
    if message is not None:
        assert updates["error_state"]["message"] == message
    assert updates["architect_message"] == user
    assert updates["target_positions"] is None
    assert "deck_spec" not in updates
    assert t.architect_lines[-1] == user and t.architect_lines.count(user) == 1, (
        "the SSE client was not told the edit could not be applied"
    )
    assert t.events[-1].metadata.get("intent") == "discuss"
    assert t.said[-1] == user and t.said.count(user) == 1, (
        "the transcript (polling client, next turn) does not say the edit could "
        "not be applied"
    )
    # Only the refusal is said (spec §7): a refused answer's own line waits for a
    # plan that never lands, so it reaches neither surface.
    assert t.said == [user], t.said
    assert t.architect_lines == [user], t.architect_lines


@contextlib.contextmanager
def _second_env(monkeypatch) -> Iterator[Any]:
    """A second, independent graph environment (its patches replace the first's)."""
    env = _build_env(monkeypatch, "sqlite:///:memory:")
    try:
        yield env
    finally:
        env.engine.dispose()


# ---------------------------------------------------------------------------
# 1. The production shape: replace slide 5 of 16 with seven slides
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_deck_spec", [False, True], ids=["operations-only", "also-sends-a-deck-spec"]
)
def test_production_replace_five_with_seven_applies_in_one_turn(
    graph_env, monkeypatch, caplog, model_deck_spec
):
    """The production refusal (spec "Why"): "replace slide 5 with an overview and six
    stage slides" on a 16-slide deck.  ``replace`` 4 with seven slides lands in one
    turn: the first takes over row 4 (same slide_id, untouched until its builder
    runs), six pending rows open at 5..10, old 5..15 move to 11..21 whole, and
    exactly 4..10 are built.

    ``also-sends-a-deck-spec``: an answer that carries operations takes the
    operations path whatever ``deck_spec`` says (spec §4: the composed spec is the
    persisted spec + ``deck_changes`` + the composed slides); here the model echoes
    the persisted spec unchanged, which today's path would read as "no change".
    """
    prior, before = _seeded(graph_env, range(16))
    rows_before = _rows(graph_env)
    version_before = _version(graph_env)
    events_before = _events(graph_env)
    seven = [_content(f"STAGE-{_WORDS[i]}") for i in range(7)]
    calls = _spy_on_the_layout(monkeypatch)
    model_message = "Slide 5 becomes an overview and six stage slides."

    with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
        t = _turn(
            graph_env,
            _ops_out(
                [_replace(4, *seven)],
                message=model_message,
                deck_spec=prior if model_deck_spec else None,
            ),
        )

    old = list(prior.slides)
    composed = _canonical(prior, old[:4] + [_spec_from(c) for c in seven] + old[5:])
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [4, 5, 6, 7, 8, 9, 10]
    assert t.updates["deck_spec"] == composed
    _assert_persisted(graph_env, composed)
    assert len(composed.slides) == 22
    assert [s.purpose for s in composed.slides[4:11]] == [c.purpose for c in seven]

    expected_rows = (
        [_mk(i) for i in range(5)] + ["PENDING"] * 6 + [_mk(i) for i in range(5, 16)]
    )
    _assert_laid_out(graph_env, before, expected_rows)
    assert _rows(graph_env)[4]["slide_id"] == before[_mk(4)]["slide_id"]

    _assert_one_layout_call(
        graph_env,
        calls,
        layout=[0, 1, 2, 3, 4] + [None] * 6 + list(range(5, 16)),
        planned=_planned(rows_before),
        spec=composed,
        operation="insert_slide",
    )
    assert _version(graph_env) == version_before + 2, (
        "one bump for the layout and one for the pre-fan-out deck-level write"
    )
    assert _events(graph_env)[len(events_before):] == [
        ("insert_slide", "deck"),
        ("write_deck_level", "deck"),
    ]

    # The builders are briefed from the composed spec, at the composed indices.
    for index, content in zip(range(4, 11), seven):
        payload = build_branch_payload(t.merged, index)["slide_spec"]
        assert payload["content_brief"] == content.content_brief
    assert build_branch_payload(t.merged, 11)["slide_spec"]["content_brief"] == "brief-5"

    assert t.said == [model_message]
    assert t.notices == []
    assert _named(caplog, "operations_ignored", logging.INFO) == []


# ---------------------------------------------------------------------------
# 2. Delete-only and move-only: nothing is built, the deck is reviewed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "positions, deleted, kept",
    [((0, 1, 2, 3), 1, (0, 2, 3)), ((0, 2, 5, 6), 2, (0, 5, 6))],
    ids=["contiguous", "gapped"],
)
def test_delete_only_edit_builds_nothing_and_reviews_deck(
    graph_env, monkeypatch, positions, deleted, kept
):
    """Delete slide 2: its row and spec entry go, the others stay whole and are
    re-stamped ``0..2``, nothing is targeted, and the foreman goes straight to deck
    review (``target_positions == []``; ``None`` would cover every spec position).

    ``gapped``: rows and spec at ``(0, 2, 5, 6)``.  Task 1's layout ``(0, 5, 6)`` is in
    persisted positions; the writer is handed row indices ``[0, 2, 3]`` (C7).
    """
    prior, before = _seeded(graph_env, positions)
    rows_before = _rows(graph_env)
    version_before = _version(graph_env)
    events_before = _events(graph_env)
    calls = _spy_on_the_layout(monkeypatch)

    t = _turn(graph_env, _ops_out([_delete(deleted)], message="Deleting slide 2."))

    composed = _canonical(prior, [prior.slide_at(p) for p in kept])
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == []
    assert t.updates["deck_spec"] == composed
    _assert_persisted(graph_env, composed)
    _assert_laid_out(graph_env, before, [_mk(0), _mk(2), _mk(3)])
    _assert_one_layout_call(
        graph_env,
        calls,
        layout=[0, 2, 3],
        planned=_planned(rows_before),
        spec=composed,
        operation="delete_slide",
    )
    assert _version(graph_env) == version_before + 2
    assert _events(graph_env)[len(events_before):] == [
        ("delete_slide", "deck"),
        ("write_deck_level", "deck"),
    ]
    assert t.said == ["Deleting slide 2."]

    assert architect_router(t.merged) == "foreman"
    assert foreman_router(t.merged) == "deck_reviewer"


@pytest.mark.parametrize(
    "positions, moved, after, order",
    [((0, 1, 2, 3), 3, 0, (0, 3, 1, 2)), ((0, 2, 5, 6), 6, 0, (0, 6, 2, 5))],
    ids=["contiguous", "gapped"],
)
def test_move_only_edit_builds_nothing_and_reviews_deck(
    graph_env, monkeypatch, positions, moved, after, order
):
    """Move slide 4 after slide 1: a pure database change.  The moved row's HTML
    and everything else about it is byte-identical at its new index, its spec entry
    moves with it, nothing is targeted, and the foreman goes to deck review.

    ``gapped``: Task 1's layout ``(0, 6, 2, 5)`` is handed over as row indices
    ``[0, 3, 1, 2]`` (C7).
    """
    prior, before = _seeded(graph_env, positions)
    rows_before = _rows(graph_env)
    version_before = _version(graph_env)
    events_before = _events(graph_env)
    calls = _spy_on_the_layout(monkeypatch)

    t = _turn(graph_env, _ops_out([_move(moved, after)], message="Moving slide 4."))

    composed = _canonical(prior, [prior.slide_at(p) for p in order])
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == []
    assert t.updates["deck_spec"] == composed
    _assert_persisted(graph_env, composed)
    _assert_laid_out(graph_env, before, [_mk(0), _mk(3), _mk(1), _mk(2)])
    assert _rows(graph_env)[1]["html"] == before[_mk(3)]["html"]
    _assert_one_layout_call(
        graph_env,
        calls,
        layout=[0, 3, 1, 2],
        planned=_planned(rows_before),
        spec=composed,
        operation="reorder_slides",
    )
    assert _version(graph_env) == version_before + 2
    assert _events(graph_env)[len(events_before):] == [
        ("reorder_slides", "deck"),
        ("write_deck_level", "deck"),
    ]
    assert t.said == ["Moving slide 4."]

    assert architect_router(t.merged) == "foreman"
    assert foreman_router(t.merged) == "deck_reviewer"


# ---------------------------------------------------------------------------
# 3. Update-only: the identity layout writes no rows
# ---------------------------------------------------------------------------


def test_update_only_edit_writes_no_layout(graph_env, monkeypatch):
    """Update slide 3 in place: no layout write (the identity changes nothing, spec
    §6), so every row is untouched, position and id included; the one version bump
    is the pre-fan-out deck-level write's; only 2 is targeted."""
    prior, _ = _seeded(graph_env, (0, 1, 2, 3))
    rows_before = _rows(graph_env)
    version_before = _version(graph_env)
    events_before = _events(graph_env)
    calls = _spy_on_the_layout(monkeypatch)
    updated = _content("UPDATED-THREE")

    t = _turn(graph_env, _ops_out([_update(2, updated)], message="Updating slide 3."))

    old = list(prior.slides)
    composed = _canonical(prior, [old[0], old[1], _spec_from(updated), old[3]])
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [2]
    assert t.updates["deck_spec"] == composed
    _assert_persisted(graph_env, composed)
    assert calls == [], "an identity layout must not reach apply_slide_layout"
    assert _rows(graph_env) == rows_before
    assert _version(graph_env) == version_before + 1
    assert _events(graph_env)[len(events_before):] == [("write_deck_level", "deck")]
    assert build_branch_payload(t.merged, 2)["slide_spec"]["content_brief"] == (
        updated.content_brief
    )
    assert t.said == ["Updating slide 3."]


def test_gapped_update_only_keeps_persisted_positions(graph_env, monkeypatch):
    """Coordinator ruling (gapped decks): an IDENTITY layout over the persisted
    positions is not re-stamped.  Rows and spec at ``(0, 2, 5)``; update position 2.
    The composed spec keeps ``(0, 2, 5)`` with the update at 2, the target is the
    PERSISTED position 2, and no row writer runs, so rows and spec still agree.

    Sabotage: re-stamp to ``0..2`` -> spec ``[0, 1, 2]`` over rows at ``0, 2, 5``
    (the next turn is ``spec_positions_stale``) and the target ``[1]`` has no row."""
    prior, before = _seeded(graph_env, (0, 2, 5))
    rows_before = _rows(graph_env)
    version_before = _version(graph_env)
    events_before = _events(graph_env)
    calls = _spy_on_the_layout(monkeypatch)
    updated = _content("UPDATED-TWO")

    t = _turn(graph_env, _ops_out([_update(2, updated)], message="Updating slide 2."))

    composed = _spec_of(
        prior,
        [(0, prior.slide_at(0)), (2, _spec_from(updated)), (5, prior.slide_at(5))],
    )
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [2]
    assert t.updates["deck_spec"] == composed
    persisted = _persisted_spec(graph_env)
    assert [s.position for s in persisted.slides] == [0, 2, 5]
    assert persisted.slide_at(2).purpose == updated.purpose
    assert persisted == composed
    assert calls == [], "an identity layout must not reach apply_slide_layout"
    assert _rows(graph_env) == rows_before
    assert _by_marker(_rows(graph_env)) == before
    assert _version(graph_env) == version_before + 1
    assert _events(graph_env)[len(events_before):] == [("write_deck_level", "deck")]
    assert build_branch_payload(t.merged, 2)["slide_spec"]["content_brief"] == (
        updated.content_brief
    )
    assert t.said == ["Updating slide 2."]


def test_gapped_deck_changes_only_keeps_persisted_positions(graph_env, monkeypatch):
    """Coordinator ruling: ``deck_changes(audience)`` only, on rows and spec at
    ``(0, 2, 5)``.  The spec keeps ``(0, 2, 5)``, so the deck-level re-review sees
    each slide at its PERSISTED position with its own HTML and brief, and the
    failing slide (5) is targeted by its persisted position.  No row writer runs.

    Sabotage: re-stamp to ``0..2`` -> the re-review covers only the rows at 0 and 2,
    and judges the row at 2 against the brief of the slide at 5; the row at 5 is
    never reviewed."""
    prior, _ = _seeded(graph_env, (0, 2, 5))
    rows_before = _rows(graph_env)
    version_before = _version(graph_env)
    calls = _spy_on_the_layout(monkeypatch)

    def reviewer(payload):
        position = payload["position"]
        if position == 5:
            return review_out(
                position, [finding("brief_not_delivered", slide_index=position)]
            )
        return review_out(position)

    graph_env.skills.set("build_reviewer", reviewer)

    t = _turn(
        graph_env,
        _ops_out(deck_changes=DeckChanges(audience=NEW_AUDIENCE), message="For the CFO."),
    )

    composed = prior.model_copy(update={"audience": NEW_AUDIENCE})
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["deck_spec"] == composed
    persisted = _persisted_spec(graph_env)
    assert [s.position for s in persisted.slides] == [0, 2, 5]
    assert persisted == composed
    reviewed = [c["payload"] for c in graph_env.skills.calls_for("build_reviewer")]
    assert [p["position"] for p in reviewed] == [0, 2, 5]
    for payload, row in zip(reviewed, rows_before):
        assert payload["html"] == row["html"]
        assert payload["slide_spec"]["position"] == row["position"]
        assert payload["slide_spec"]["content_brief"] == f"brief-{row['position']}"
        assert payload["deck_brief"]["audience"] == NEW_AUDIENCE
    assert t.updates["target_positions"] == [5]
    assert calls == []
    assert _rows(graph_env) == rows_before
    assert _version(graph_env) == version_before + 1


# ---------------------------------------------------------------------------
# 4. The Task 1 mixed example on a seeded deck
# ---------------------------------------------------------------------------


def test_mixed_owner_example(graph_env, monkeypatch):
    """On 8 slides: delete 3, update 4, replace 5 with [A, B, C], insert N after 4.
    Composed ``[s0, s1, s2, U4, N, A, B, C, s6, s7]``; rebuild ``(3, 4, 5, 6, 7)``.
    Row 4 (updated) and row 5 (replaced, its first slide) keep their rows; row 3
    is deleted; 4 + 6 + 7 hold pending rows.  A mixed layout records
    ``save_deck_slides``."""
    prior, before = _seeded(graph_env, range(8))
    rows_before = _rows(graph_env)
    version_before = _version(graph_env)
    events_before = _events(graph_env)
    calls = _spy_on_the_layout(monkeypatch)
    u4, n, a, b, c = (_content(tag) for tag in ("UFOUR", "NEW", "A", "B", "C"))
    ops = [_delete(3), _update(4, u4), _replace(5, a, b, c), _insert(4, n)]

    t = _turn(graph_env, _ops_out(ops, message="Reworking the middle of the deck."))

    old = list(prior.slides)
    composed = _canonical(
        prior,
        old[:3] + [_spec_from(x) for x in (u4, n, a, b, c)] + old[6:],
    )
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [3, 4, 5, 6, 7]
    assert t.updates["deck_spec"] == composed
    _assert_persisted(graph_env, composed)
    _assert_laid_out(
        graph_env,
        before,
        [_mk(0), _mk(1), _mk(2), _mk(4), "PENDING", _mk(5), "PENDING", "PENDING",
         _mk(6), _mk(7)],
    )
    _assert_one_layout_call(
        graph_env,
        calls,
        layout=[0, 1, 2, 4, None, 5, None, None, 6, 7],
        planned=_planned(rows_before),
        spec=composed,
        operation="save_deck_slides",
    )
    assert _version(graph_env) == version_before + 2
    assert _events(graph_env)[len(events_before):] == [
        ("save_deck_slides", "deck"),
        ("write_deck_level", "deck"),
    ]
    for index, content in zip((3, 4, 5, 6, 7), (u4, n, a, b, c)):
        assert build_branch_payload(t.merged, index)["slide_spec"]["content_brief"] == (
            content.content_brief
        )


# ---------------------------------------------------------------------------
# 5. deck_changes only: today's deck-level re-review, on the composed spec
# ---------------------------------------------------------------------------


def test_deck_changes_only_reruns_deck_level_review(graph_env, monkeypatch):
    """``deck_changes(audience=…)`` with ``operations=None`` (C6: the identity
    operations result).  No row moves; ``classify_spec_change`` sees a deck-level
    change, so every committed slide is re-reviewed serially against the NEW brief
    and only the failing one is rebuilt; the deck-level notice is said."""
    prior, _ = _seeded(graph_env, (0, 1, 2))
    rows_before = _rows(graph_env)
    version_before = _version(graph_env)
    calls = _spy_on_the_layout(monkeypatch)

    def reviewer(payload):
        position = payload["position"]
        if position == 1:
            return review_out(
                position, [finding("brief_not_delivered", slide_index=position)]
            )
        return review_out(position)

    graph_env.skills.set("build_reviewer", reviewer)
    model_message = "Retargeting the deck at the CFO."

    t = _turn(
        graph_env,
        _ops_out(deck_changes=DeckChanges(audience=NEW_AUDIENCE), message=model_message),
    )

    composed = prior.model_copy(update={"audience": NEW_AUDIENCE})
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["deck_spec"] == composed
    _assert_persisted(graph_env, composed)
    reviewed = [c["payload"] for c in graph_env.skills.calls_for("build_reviewer")]
    assert [p["position"] for p in reviewed] == [0, 1, 2]
    for payload, row in zip(reviewed, rows_before):
        assert payload["html"] == row["html"]
        assert payload["slide_spec"]["content_brief"] == f"brief-{payload['position']}"
        assert payload["deck_brief"]["audience"] == NEW_AUDIENCE
    assert t.updates["target_positions"] == [1]
    notice = (
        "The deck's brief changed, so I re-checked all 3 slide(s) against it. "
        "Rebuilding slide 2."
    )
    assert t.said == [model_message, notice]
    deck_level = [
        e.metadata for e in t.events if (e.metadata or {}).get("spec_change") == "deck_level"
    ]
    assert len(deck_level) == 1 and deck_level[0]["rebuilding"] == [1]
    assert calls == []
    assert _rows(graph_env) == rows_before
    assert _version(graph_env) == version_before + 1


def test_deck_level_change_with_operations_reviews_the_laid_out_rows(
    graph_env, monkeypatch
):
    """The rows are laid out BEFORE ``classify_spec_change`` (spec §4 step 4), so the
    deck-level re-review reads each slide's own HTML against its own composed spec
    entry: delete slide 1 and insert N at the end, with a new audience.  BRAVO (now
    at 0) is judged against BRAVO's brief, the pending row at 2 fails by definition
    with no model call, and only it is rebuilt.

    Sabotage: lay out after the re-review -> ALPHA's HTML is reviewed against
    BRAVO's brief, and 2 has no row."""
    prior, before = _seeded(graph_env, (0, 1, 2))
    graph_env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))
    model_message = "Dropping the opener, adding a close, for the CFO."
    n = _content("CLOSE")

    t = _turn(
        graph_env,
        _ops_out(
            [_delete(0), _insert(2, n)],
            DeckChanges(audience=NEW_AUDIENCE),
            message=model_message,
        ),
    )

    composed = _canonical(
        prior, [prior.slides[1], prior.slides[2], _spec_from(n)], audience=NEW_AUDIENCE
    )
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["deck_spec"] == composed
    _assert_persisted(graph_env, composed)
    _assert_laid_out(graph_env, before, [_mk(1), _mk(2), "PENDING"])
    reviewed = [c["payload"] for c in graph_env.skills.calls_for("build_reviewer")]
    assert [(p["position"], _marker(p["html"])) for p in reviewed] == [
        (0, _mk(1)),
        (1, _mk(2)),
    ], "every laid-out committed slide, and only those, is re-reviewed"
    assert [p["slide_spec"]["content_brief"] for p in reviewed] == ["brief-1", "brief-2"]
    assert all(p["deck_brief"]["audience"] == NEW_AUDIENCE for p in reviewed)
    assert t.updates["target_positions"] == [2]
    assert t.said == [
        model_message,
        "The deck's brief changed, so I re-checked all 3 slide(s) against it. "
        "Rebuilding slide 3.",
    ]


# ---------------------------------------------------------------------------
# 6. A design-contract change rebuilds all but the untouched blanks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("named", [False, True], ids=["unnamed", "named"])
def test_design_contract_change_rebuilds_all_but_untouched_blanks(
    graph_env, monkeypatch, caplog, named
):
    """Rows ``[ALPHA, BLANK, CHARLIE, DELTA]``, entry 1 blank.  The edit restyles
    (``deck_changes.design_contract``), inserts N at the start, updates slide 4 and
    inserts a BLANK entry after it.  Composed: ``[N, ALPHA, BLANK, CHARLIE, D', NEWBLANK]``,
    rebuild ``(0, 4, 5)``.  The restyle rebuilds every composed index except the
    untouched blank, which moved to 2: ``[0, 1, 3, 4, 5]``.  The inserted blank
    entry was produced by an op, so it is built (#337).  The brand is re-resolved
    for the new contract.

    ``named``: the user's message names slide 2 (persisted position 1, the blank).
    References count the pre-message deck, so it is mapped through the layout to
    composed index 2 and the "still blank" notice and WARNING fire once.
    """
    _seed_rows(graph_env, {0: "MK-ALPHA", 2: "MK-CHARLIE", 3: "MK-DELTA"})
    _seed_blank_row(graph_env, 1)
    prior = _canonical(make_spec((0,)), [
        _spec_from(_content("ALPHA")), _blank_entry(),
        _spec_from(_content("CHARLIE")), _spec_from(_content("DELTA")),
    ])
    _persist(graph_env, prior)
    rows = _rows(graph_env)
    before = {**_by_marker(rows), "BLANK": rows[1]}
    calls = _spy_on_the_layout(monkeypatch)
    n, d2 = _content("NEW"), _content("DELTA-REVISED")
    new_blank = SlideContent(**copy.deepcopy(BLANK_DECK_SPEC_ENTRY))
    out = _ops_out(
        [_insert(-1, n), _update(3, d2), _insert(3, new_blank)],
        DeckChanges(design_contract=RESTYLED),
        message="Restyling, with a new opener.",
    )
    overrides = (
        {"architect_message": "Use the Acme brand and fill slide 2 with pricing"}
        if named
        else {}
    )

    with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
        t = _turn(graph_env, out, **overrides)

    old = list(prior.slides)
    composed = _canonical(
        prior,
        [_spec_from(n), old[0], old[1], old[2], _spec_from(d2), _spec_from(new_blank)],
        design_contract=RESTYLED.model_dump(),
    )
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [0, 1, 3, 4, 5]
    assert t.updates["deck_spec"] == composed
    _assert_persisted(graph_env, composed)
    _assert_laid_out(
        graph_env, before, ["PENDING", "MK-ALPHA", "BLANK", "MK-CHARLIE", "MK-DELTA", "PENDING"]
    )
    assert len(calls) == 1 and list(calls[0]["layout"]) == [None, 0, 1, 2, 3, None]
    # The brand of the committed contract, not the inbound unpinned one (C7).
    assert (7, 3) in graph_env.template.calls
    assert t.updates["token_css"] == TEMPLATE_TOKEN_CSS

    named_warnings = _named(caplog, "blank_named_but_not_described")
    if named:
        references = graph_env.skills.calls_for("architect")[0]["payload"]["slide_references"]
        assert [r["positions"] for r in references] == [[1]], "precondition"
        assert len(named_warnings) == 1
        assert len(t.notices) == 1, t.notices
    else:
        assert named_warnings == []
        assert t.notices == []


def test_gapped_identity_restyle_skips_the_untouched_blank(graph_env, monkeypatch):
    """C10 meets #314 N1: on an IDENTITY layout the untouched blanks are decided in
    PERSISTED positions, the numbering of the spec and of ``rebuild`` there.  Rows
    and spec at ``(0, 2, 5)``, entry 2 blank; restyle and update 5.  Nothing moves,
    and the rebuild-all is every persisted position but the blank: ``[0, 5]``.

    Sabotage: compare composed indices with the spec's positions -> persisted 5 is
    composed index 2, so the blank at 2 reads as touched and is rebuilt."""
    _seed_rows(graph_env, {0: "MK-ALPHA", 5: "MK-CHARLIE"})
    _seed_blank_row(graph_env, 2)
    alpha, charlie = _spec_from(_content("ALPHA")), _spec_from(_content("CHARLIE"))
    prior = _spec_of(make_spec((0,)), [(0, alpha), (2, _blank_entry()), (5, charlie)])
    _persist(graph_env, prior)
    rows_before = _rows(graph_env)
    calls = _spy_on_the_layout(monkeypatch)
    revised = _content("CHARLIE-REVISED")

    t = _turn(
        graph_env,
        _ops_out([_update(5, revised)], DeckChanges(design_contract=RESTYLED)),
    )

    composed = _spec_of(
        prior,
        [(0, alpha), (2, _blank_entry()), (5, _spec_from(revised))],
        design_contract=RESTYLED.model_dump(),
    )
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [0, 5]
    assert t.updates["deck_spec"] == composed
    assert _persisted_spec(graph_env) == composed
    assert calls == [], "an identity layout must not reach apply_slide_layout"
    assert _rows(graph_env) == rows_before
    assert (7, 3) in graph_env.template.calls
    assert t.notices == []


def test_session_selection_unlike_the_spec_resolves_the_spec_brand(graph_env, monkeypatch):
    """The re-resolve rule is today's: the brand is the COMMITTED contract's, not
    the session selection's.  The spec is pinned to ``(7, 3)``, the session has
    selected ``(8, 4)``, and the edit leaves ``design_contract`` alone.  The turn
    starts with the selection's brand, then resolves the spec's, exactly as the
    full-spec path does; no restyle is classified, so only the update is built.

    Sabotage: compare the composed contract with the persisted one instead of the
    one the inbound brand was resolved for -> equal, so the selection's brand
    (template ``(8, 4)``) briefs the builders of a deck pinned to ``(7, 3)``."""
    _seed_rows(graph_env, {0: "MK-ALPHA", 1: "MK-BRAVO"})
    prior = make_spec((0, 1), design_system_id=7, template_id=3)
    _persist(graph_env, prior)
    monkeypatch.setattr(
        "src.services.graph.nodes._session_contract",
        lambda session_id: DesignContractRef(
            design_system_id=8, template_id=4, slide_style_id=None
        ),
    )
    calls = _spy_on_the_layout(monkeypatch)

    t = _turn(graph_env, _ops_out([_update(1, _content("BRAVO-REVISED"))]))

    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert graph_env.template.calls == [(8, 4), (7, 3)]
    assert t.updates["target_positions"] == [1]
    assert t.updates["deck_spec"].design_contract == prior.design_contract
    assert calls == []


# ---------------------------------------------------------------------------
# 6b. A design contract carried only in deck_spec is adopted (C19)
# ---------------------------------------------------------------------------

#: A contract other than RESTYLED, for the answer whose deck_changes names one.
OTHER_CONTRACT = DesignContractRef(design_system_id=9, template_id=5, slide_style_id=None)

#: The named INFO log of the C19 adoption.
CONTRACT_FROM_SPEC = "operations_contract_from_deck_spec"


def _blank_middle_deck(env) -> DeckSpec:
    """Rows ``[ALPHA, BLANK, CHARLIE]`` at 0..2 and their persisted, unpinned spec."""
    _seed_rows(env, {0: "MK-ALPHA", 2: "MK-CHARLIE"})
    _seed_blank_row(env, 1)
    prior = _canonical(make_spec((0,)), [
        _spec_from(_content("ALPHA")), _blank_entry(), _spec_from(_content("CHARLIE")),
    ])
    _persist(env, prior)
    return prior


def _model_spec(prior: DeckSpec, contract: DesignContractRef) -> DeckSpec:
    """The ``deck_spec`` an operations answer also sends: *contract*, and an
    audience and a first slide the operations do NOT say — so a composed spec
    that read anything but the contract out of it shows."""
    old = list(prior.slides)
    return _canonical(
        prior,
        [_spec_from(_content("FROM-THE-DECK-SPEC")), old[1], old[2]],
        design_contract=contract.model_dump(),
        audience="the audience only deck_spec names",
    )


@pytest.mark.parametrize(
    "case", ["update", "restyle-only", "deck-changes-without-contract"]
)
def test_contract_only_in_deck_spec_is_adopted(graph_env, monkeypatch, caplog, case):
    """C19: the prompt commits a confirmed contract inside ``deck_spec`` on a build
    and in ``deck_changes.design_contract`` on an edit (its DESIGN SYSTEMS block said
    "inside deck_spec" only until the ``edit-ops-b`` follow-up).  The node still
    tolerates an operations answer that puts it in ``deck_spec`` — ``deck_changes``
    naming no contract, ``deck_spec`` a new one — and commits that contract: the
    composed spec carries it, the brand is re-resolved for it, and the restyle
    rebuilds every position but the untouched blank (``[0, 2]``).  Nothing ELSE is read out of
    ``deck_spec``: not its audience, not its slides.  INFO
    ``operations_contract_from_deck_spec`` says so, once.

    ``restyle-only``: ``operations=[]`` with the contract in ``deck_spec`` alone is
    a restyle, not ``nothing_to_do``.  ``deck-changes-without-contract``: a
    ``deck_changes`` that sets other fields keeps them, and still takes the
    contract from ``deck_spec``.

    Sabotage: drop the adoption -> the contract is lost (the spec stays unpinned,
    only the update is built; ``restyle-only`` refuses as ``nothing_to_do``)."""
    prior = _blank_middle_deck(graph_env)
    rows_before = _rows(graph_env)
    calls = _spy_on_the_layout(monkeypatch)
    revised = _content("CHARLIE-REVISED")
    ops = [] if case == "restyle-only" else [_update(2, revised)]
    deck_changes = (
        DeckChanges(audience=NEW_AUDIENCE)
        if case == "deck-changes-without-contract"
        else None
    )
    out = _ops_out(ops, deck_changes, deck_spec=_model_spec(prior, RESTYLED))

    with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
        t = _turn(graph_env, out)

    old = list(prior.slides)
    third = old[2] if case == "restyle-only" else _spec_from(revised)
    deck = {"design_contract": RESTYLED.model_dump()}
    if case == "deck-changes-without-contract":
        deck["audience"] = NEW_AUDIENCE
    composed = _canonical(prior, [old[0], old[1], third], **deck)
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["deck_spec"] == composed
    assert _persisted_spec(graph_env) == composed
    # The design-contract rebuild-all, minus the untouched blank at 1.
    assert t.updates["target_positions"] == [0, 2]
    assert calls == [], "an identity layout must not reach apply_slide_layout"
    assert _rows(graph_env) == rows_before
    # The brand of the adopted contract briefs the builders.
    assert (7, 3) in graph_env.template.calls
    assert t.updates["token_css"] == TEMPLATE_TOKEN_CSS
    adopted = _named(caplog, CONTRACT_FROM_SPEC, logging.INFO)
    assert len(adopted) == 1, [r.getMessage() for r in caplog.records]
    assert _named(caplog, "operations_ignored", logging.INFO) == []


def test_contract_in_deck_changes_wins_over_deck_spec(graph_env, monkeypatch, caplog):
    """C19 applies only when ``deck_changes`` names no contract: one that does is
    the edit's contract whatever ``deck_spec`` says, and nothing is adopted.

    Sabotage: adopt whenever ``deck_spec``'s contract is new -> the committed
    contract is RESTYLED, not OTHER_CONTRACT, and the log fires."""
    prior = _blank_middle_deck(graph_env)
    revised = _content("CHARLIE-REVISED")
    out = _ops_out(
        [_update(2, revised)],
        DeckChanges(design_contract=OTHER_CONTRACT),
        deck_spec=_model_spec(prior, RESTYLED),
    )

    with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
        t = _turn(graph_env, out)

    old = list(prior.slides)
    composed = _canonical(
        prior,
        [old[0], old[1], _spec_from(revised)],
        design_contract=OTHER_CONTRACT.model_dump(),
    )
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["deck_spec"] == composed
    assert _persisted_spec(graph_env) == composed
    assert t.updates["target_positions"] == [0, 2]
    assert (9, 5) in graph_env.template.calls
    assert (7, 3) not in graph_env.template.calls
    assert _named(caplog, CONTRACT_FROM_SPEC, logging.INFO) == []


@pytest.mark.parametrize("case", ["update", "no-operations"])
def test_same_contract_in_deck_spec_changes_nothing(graph_env, monkeypatch, caplog, case):
    """A ``deck_spec`` whose contract is the persisted one carries no contract
    change, so nothing is adopted: an update builds only itself, with the
    persisted contract and brand, and an answer with no operation and no
    ``deck_changes`` is still ``nothing_to_do`` — echoing the spec back is not a
    deck-level change.  Neither logs the adoption.

    Sabotage: adopt whenever ``deck_changes`` names no contract -> the log fires,
    and ``no-operations`` lands as a no-op edit instead of refusing."""
    prior = _blank_middle_deck(graph_env)
    snapshot = _db_state(graph_env)
    revised = _content("CHARLIE-REVISED")
    ops = [] if case == "no-operations" else [_update(2, revised)]
    out = _ops_out(ops, deck_spec=_model_spec(prior, prior.design_contract))

    with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
        t = _turn(graph_env, out)

    assert _named(caplog, CONTRACT_FROM_SPEC, logging.INFO) == []
    assert graph_env.template.calls == []
    if case == "no-operations":
        _assert_refused(
            t,
            "edit_operations_rejected",
            REJECTED_PREFIX + "it did not list any change to make.",
            "the edit listed no operation that changes the deck and no deck-level change",
        )
        assert _db_state(graph_env) == snapshot
        return
    old = list(prior.slides)
    composed = _canonical(prior, [old[0], old[1], _spec_from(revised)])
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["deck_spec"] == composed
    assert t.updates["target_positions"] == [2]


#: The #314 N1 notice for the blank at position 1, numbered as the user saw it.
STILL_BLANK_2 = "Slide 2 is still blank, so I left it as it is. Tell me what to put on it."


def _blank_second_slide(env) -> DeckSpec:
    """Rows ``[ALPHA, BLANK, CHARLIE]`` at ``0..2``; the persisted entry 1 is blank."""
    _seed_rows(env, {0: "MK-ALPHA", 2: "MK-CHARLIE"})
    _seed_blank_row(env, 1)
    prior = _canonical(make_spec((0,)), [
        _spec_from(_content("ALPHA")), _blank_entry(), _spec_from(_content("CHARLIE")),
    ])
    _persist(env, prior)
    return prior


def _named_turn(env, caplog, out: ArchitectOutput, user_message: str) -> SimpleNamespace:
    with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
        t = _turn(env, out, architect_message=user_message)
    references = env.skills.calls_for("architect")[0]["payload"]["slide_references"]
    assert [r["positions"] for r in references] == [[1]], "precondition: slide 2 is named"
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    return t


def _log_what_is_said(monkeypatch) -> List[tuple]:
    """Record every ASSISTANT event and every transcript row, in one order log."""
    log: List[tuple] = []
    real_emit = nodes._emit

    def emit_spy(event_type, **kwargs):
        if event_type == StreamEventType.ASSISTANT:
            log.append(("event", kwargs.get("content")))
        return real_emit(event_type, **kwargs)

    monkeypatch.setattr(nodes, "_emit", emit_spy)
    real_add = SessionManager.add_message
    signature = inspect.signature(real_add)

    def add_spy(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        arguments = bound.arguments
        log.append(("row", arguments["message_type"], arguments["content"]))
        return real_add(self, *args, **kwargs)

    monkeypatch.setattr(SessionManager, "add_message", add_spy)
    return log


def test_named_blank_no_operation_touches_is_said(graph_env, caplog, monkeypatch):
    """C12 (the reviewer's probe): "fill slide 2 with pricing" over a blank slide 2,
    answered by operations that only update slide 3.  The full-spec path says
    "Slide 2 is still blank…"; so must this one, once, in the user's own number,
    although no list this turn builds ever held the blank (targets are ``rebuild``,
    and nothing restyles or re-reviews).

    The notice qualifies the architect's message, so it is said AFTER it (spec §7;
    final review M1): the persisted assistant rows are exactly ``[message
    (llm_response), notice (info)]`` in that order, the message is the turn's only
    ``ASSISTANT`` event (a notice is a row, never an event), and both the message's
    event and its row are written before the notice's row.

    Sabotage: notice only when a list drops the blank (the first cut) -> silent;
    say the message after the notice -> the order is reversed."""
    _blank_second_slide(graph_env)
    log = _log_what_is_said(monkeypatch)
    message = "Adding pricing to slide 3."

    t = _named_turn(
        graph_env,
        caplog,
        _ops_out([_update(2, _content("CHARLIE-PRICING"))], targets=[1], message=message),
        "fill slide 2 with pricing",
    )

    assert t.updates["target_positions"] == [2]
    assert t.notices == [STILL_BLANK_2]
    assert len(_named(caplog, "blank_named_but_not_described")) == 1
    assert [
        (m["content"], m["message_type"]) for m in t.rows if m["role"] == "assistant"
    ] == [(message, "llm_response"), (STILL_BLANK_2, "info")], (
        "the still-blank notice must follow the architect's message"
    )
    assert [e.content for e in t.events if e.type == StreamEventType.ASSISTANT] == [message]
    said_event = log.index(("event", message))
    said_row = log.index(("row", "llm_response", message))
    notice_row = log.index(("row", "info", STILL_BLANK_2))
    assert max(said_event, said_row) < notice_row, (
        f"the architect's message was said after the still-blank notice: {log}"
    )


@pytest.mark.parametrize("restyle", [False, True], ids=["plain", "with-restyle"])
def test_named_blank_as_an_insert_anchor_is_not_said(graph_env, caplog, restyle):
    """C12: "add a pricing slide after slide 2" names the blank as a PLACE (an
    insert's ``after_position``), not a request to fill it, so nothing is said —
    also when a restyle rebuilds every slide but the untouched blank, which is the
    list that drops it (the blank moved nowhere: composed index 1).

    Sabotage: say a named blank whatever names it, or let the rebuild-all's drop
    say it -> one notice."""
    _blank_second_slide(graph_env)
    out = _ops_out(
        [_insert(1, _content("PRICING"))],
        DeckChanges(design_contract=RESTYLED) if restyle else None,
    )

    t = _named_turn(graph_env, caplog, out, "add a pricing slide after slide 2")

    # Composed [ALPHA, BLANK, PRICING, CHARLIE]; the restyle skips the blank at 1.
    assert t.updates["target_positions"] == ([0, 2, 3] if restyle else [2])
    assert t.notices == []
    assert _named(caplog, "blank_named_but_not_described") == []


@pytest.mark.parametrize(
    "ops, deck_changes, user_message, targets",
    [
        ([_update(1, _content("PRICING"))], None, "fill slide 2 with pricing", [1]),
        (
            [_move(1, 2)],
            DeckChanges(design_contract=RESTYLED),
            "move slide 2 to the end",
            [0, 1],
        ),
    ],
    ids=["updated", "moved-with-restyle"],
)
def test_named_blank_an_operation_acts_on_is_not_said(
    graph_env, caplog, ops, deck_changes, user_message, targets
):
    """C12: a named blank that is the subject of an operation is not "left alone".
    ``updated``: it is filled, and built.  ``moved-with-restyle``: the user named it
    to move it; the restyle's rebuild-all still skips it (now at composed index 2,
    composed ``[ALPHA, CHARLIE, BLANK]``) and says nothing.

    Sabotage: map the reference through the layout and let the rebuild-all's drop
    say it -> one notice on ``moved-with-restyle``."""
    _blank_second_slide(graph_env)

    t = _named_turn(graph_env, caplog, _ops_out(ops, deck_changes), user_message)

    assert t.updates["target_positions"] == targets
    assert t.notices == []
    assert _named(caplog, "blank_named_but_not_described") == []


# ---------------------------------------------------------------------------
# 7. Problems degrade with a sentence that names them; nothing is written
# ---------------------------------------------------------------------------


_POSITIONS_0_21 = ", ".join(str(p) for p in range(22))


@pytest.mark.parametrize(
    "positions, ops, details, sentences",
    [
        (
            tuple(range(22)),
            [_replace(29, _content("X"))],
            [f"position 29 is not a slide of the deck (positions: {_POSITIONS_0_21})"],
            ["there is no slide 30 — the deck has 22 slides"],
        ),
        (
            tuple(range(22)),
            [_replace(29, _content("X")), _delete(3), _update(3, _content("U"))],
            [
                f"position 29 is not a slide of the deck (positions: {_POSITIONS_0_21})",
                "the slide at position 3 is the subject of more than one operation",
            ],
            [
                "there is no slide 30 — the deck has 22 slides",
                "slide 4 was changed in more than one way",
            ],
        ),
        (
            (0, 2, 5),
            [_delete(5), _move(5, 0)],
            ["the slide at position 5 is the subject of more than one operation"],
            # The user's numbering (slide_numbering), not position + 1 ("slide 6").
            ["slide 3 was changed in more than one way"],
        ),
    ],
    ids=["one-problem", "two-problems", "gapped-numbering"],
)
def test_operations_problems_degrade_with_named_sentence(
    graph_env, monkeypatch, positions, ops, details, sentences
):
    """Replace position 29 on a 22-slide deck: ``edit_operations_rejected``, the
    sentence built from ``problem_sentence`` (slide numbers, not positions), the
    joined details on ``error_state``, and a whole-database snapshot unchanged."""
    _seeded(graph_env, positions)
    calls = _spy_on_the_layout(monkeypatch)
    snapshot = _db_state(graph_env)

    t = _turn(graph_env, _ops_out(ops, message="Replacing slide 30."))

    user = REJECTED_PREFIX + "; ".join(sentences) + "."
    for sentence in sentences:
        assert sentence in t.updates["architect_message"]
    _assert_refused(t, "edit_operations_rejected", user, "; ".join(details))
    assert calls == []
    assert _db_state(graph_env) == snapshot


def test_binding_error_in_operations_degrades(graph_env, monkeypatch):
    """An inserted slide bound half-way (``slide_type`` without an index) on an
    unpinned deck.  The bindings are checked on the COMPOSED spec, so the error
    names the new slide's composed number (slide 3), and it degrades like any other
    operations problem: ``invalid_slide_type_binding`` falls back to its detail in
    ``problem_sentence`` (C8)."""
    _seeded(graph_env, (0, 1, 2))
    calls = _spy_on_the_layout(monkeypatch)
    snapshot = _db_state(graph_env)
    half_bound = _content("TITLE").model_copy(update={"slide_type": "title"})

    t = _turn(graph_env, _ops_out([_insert(1, half_bound)], message="Adding a title."))

    error = (
        "slide 3: slide_type='title', template_section_index=None — slide_type and "
        "template_section_index must be set together or both left empty"
    )
    _assert_refused(t, "edit_operations_rejected", REJECTED_PREFIX + error + ".", error)
    assert calls == []
    assert _db_state(graph_env) == snapshot


def test_index_only_binding_in_operations_is_completed(graph_env, monkeypatch):
    """The other binding helper (C3): an inserted slide that binds only
    ``template_section_index`` on a labelled template gets its ``slide_type``
    completed from the template, on the composed spec, and is applied."""
    graph_env.template.layout = (
        "<main class='deck'>"
        "<section class='slide' data-label='title'><h1>Title</h1></section>"
        "<section class='slide' data-label='content'><h1>Body</h1></section>"
        "</main>"
    )
    _seed_rows(graph_env, {0: "MK-ALPHA", 1: "MK-BRAVO"})
    prior = make_spec(
        (0, 1), design_system_id=7, template_id=3, slide_type="content",
        template_section_index=1,
    )
    _persist(graph_env, prior)
    before = _by_marker(_rows(graph_env))
    index_only = _content("NEW").model_copy(update={"template_section_index": 1})

    t = _turn(graph_env, _ops_out([_insert(0, index_only)], message="Adding a slide."))

    completed = _spec_from(index_only).model_copy(update={"slide_type": "content"})
    composed = _canonical(prior, [prior.slides[0], completed, prior.slides[1]])
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [1]
    assert t.updates["deck_spec"] == composed
    _assert_persisted(graph_env, composed)
    _assert_laid_out(graph_env, before, ["MK-ALPHA", "PENDING", "MK-BRAVO"])


# ---------------------------------------------------------------------------
# 8. The rows changed while planning: refused, nothing written, no retry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error, code",
    [
        (SlideRowsChangedError("the rows moved under the planner"), "insert_rows_changed"),
        (RuntimeError("the database went away"), "insert_rows_failed"),
    ],
    ids=["rows-changed", "any-other-error"],
)
def test_rows_changed_mid_plan_refuses_without_retry(graph_env, monkeypatch, error, code):
    """The layout write refuses: today's two degrade codes, with C11's edit-neutral
    sentences (a delete was never "adding the slide"), nothing written, and no
    second architect call (the model cannot fix a deck that changed under it).
    Only the refusal is said: the model's own line waits for the plan to land
    (Task 5).  ``SlideRowsChangedError`` is a ``RuntimeError``, so catching
    ``Exception`` first would report it as a failure."""
    _seeded(graph_env, (0, 1, 2, 3))

    def _raise(self, *args, **kwargs):
        raise error

    monkeypatch.setattr(SlideWriter, "apply_slide_layout", _raise)
    snapshot = _db_state(graph_env)

    t = _turn(graph_env, _ops_out([_delete(1)], message="Deleting slide 2."))

    user = {
        "insert_rows_changed": (
            "The deck changed while I was planning, so I have not made that edit. "
            "Nothing has been changed; please ask again."
        ),
        "insert_rows_failed": (
            "I could not make that edit, so nothing has been changed. "
            "Please try asking again."
        ),
    }[code]
    _assert_refused(t, code, user, None)
    assert "Deleting slide 2." not in t.architect_lines
    assert "Deleting slide 2." not in t.said
    assert _db_state(graph_env) == snapshot
    assert len(graph_env.skills.calls_for("architect")) == 1


# ---------------------------------------------------------------------------
# 9. Operations are ignored on every other turn
# ---------------------------------------------------------------------------


def _ignored_case(case: str, prior: DeckSpec):
    """(answer with operations, the same answer without, state overrides)."""
    ops = [_delete(0)]
    changes = DeckChanges(title="IGNORED title", audience="IGNORED audience")
    if case == "build":
        spec = prior.model_copy(
            update={
                "slides": [
                    s.model_copy(update={"content_brief": "REBUILT brief"})
                    if s.position == 1
                    else s
                    for s in prior.slides
                ]
            }
        )
        base = dict(intent="build", message="Rebuilding the deck.", deck_spec=spec)
        return (
            ArchitectOutput(**base, operations=ops, deck_changes=changes),
            ArchitectOutput(**base),
            {},
        )
    if case == "describe-only":
        spec = prior.model_copy(
            update={
                "slides": [
                    s.model_copy(update={"purpose": "RE-DESCRIBED purpose"})
                    if s.position == 2
                    else s
                    for s in prior.slides
                ]
            }
        )
        base = dict(intent="edit", message="Re-described.", deck_spec=spec,
                    target_positions=[2])
        return (
            ArchitectOutput(**base, operations=ops, deck_changes=changes),
            ArchitectOutput(**base),
            {"describe_only": scoped(TURN, True)},
        )
    base = dict(intent="discuss", message="Which slide do you mean?")
    return (
        ArchitectOutput(**base, operations=ops, deck_changes=changes),
        ArchitectOutput(**base),
        {},
    )


@pytest.mark.parametrize("case", ["build", "describe-only", "discuss"])
def test_operations_ignored_on_build_and_describe_only(graph_env, monkeypatch, caplog, case):
    """Only an ``edit`` that is not describe-only takes the operations path (spec
    §4).  A build builds from its ``deck_spec``, a describe-only turn re-describes
    through ``deck_spec`` and shifts no row, and a discussion ends the turn, each
    EXACTLY as the same answer without ``operations``/``deck_changes`` does (the
    oracle is a second, identical environment).  The ignored fields are logged at
    INFO, ``operations_ignored``, once."""
    prior, _ = _seeded(graph_env, (0, 1, 2))
    with_ops, without_ops, overrides = _ignored_case(case, prior)
    calls = _spy_on_the_layout(monkeypatch)
    rows_before = _rows(graph_env)
    version_before = _version(graph_env)

    with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
        t = _turn(graph_env, with_ops, **overrides)
    ignored = _named(caplog, "operations_ignored", logging.INFO)
    persisted = _persisted_spec(graph_env)
    rows_after = _rows(graph_env)
    version_after = _version(graph_env)
    caplog.clear()

    with _second_env(monkeypatch) as oracle:
        oracle_prior, _ = _seeded(oracle, (0, 1, 2))
        assert oracle_prior == prior
        oracle_version_before = _version(oracle)
        with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
            o = _turn(oracle, without_ops, **overrides)
        oracle_ignored = _named(caplog, "operations_ignored", logging.INFO)
        oracle_persisted = _persisted_spec(oracle)
        oracle_version_delta = _version(oracle) - oracle_version_before

    assert t.updates == o.updates
    assert persisted == oracle_persisted
    assert version_after - version_before == oracle_version_delta
    assert rows_after == rows_before, "an ignored operation moved or deleted a row"
    assert calls == []
    assert t.said == o.said
    if case == "build":
        assert t.updates["target_positions"] is None
        assert persisted == with_ops.deck_spec
    elif case == "describe-only":
        assert persisted == with_ops.deck_spec
        assert version_after == version_before, "a describe-only turn bumps no version"
    else:
        assert persisted == prior
    assert len(ignored) == 1, [r.getMessage() for r in caplog.records]
    assert oracle_ignored == []


# ---------------------------------------------------------------------------
# 10. No operations: today's path, unchanged
# ---------------------------------------------------------------------------


def test_old_path_unchanged_without_operations(graph_env, monkeypatch, caplog):
    """Regression guard (green before Task 4): an edit that returns a grown
    ``deck_spec`` and no operations is aligned and shifted exactly as today
    (``test_architect_insert_slide``'s headline case: insert at 2 of 3, the model
    targets ``[3]``)."""
    prior, before = _seeded(graph_env, (0, 1, 2))
    a, b, c = prior.slides
    version_before = _version(graph_env)
    events_before = _events(graph_env)
    shifts = _spy_on_the_shift(monkeypatch)
    model_spec = _spec_of(prior, [(0, a), (1, b), (2, _new()), (3, c)])

    with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
        t = _turn(graph_env, _edit_out(model_spec, [3], message="Adding a slide."))

    canonical = _canonical(prior, [a, b, _new(), c])
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["architect_message"] == "Adding a slide."
    assert t.updates["error_state"] is None
    assert t.updates["fix_target"] is None
    assert t.updates["target_positions"] == [2]
    assert t.updates["deck_spec"] == canonical
    _assert_persisted(graph_env, canonical)
    _assert_shifted(graph_env, before, [_mk(0), _mk(1), "PENDING", _mk(2)])
    assert len(shifts) == 1 and list(shifts[0]["insert_at"]) == [2]
    assert _version(graph_env) == version_before + 2
    assert _events(graph_env)[len(events_before):] == [
        ("insert_slide", "deck"),
        ("write_deck_level", "deck"),
    ]
    assert len(_named(caplog, "insert_targets_disagree")) == 1
    assert _named(caplog, "operations_targets_disagree") == []
    assert _named(caplog, "operations_ignored", logging.INFO) == []
    assert t.said == ["Adding a slide."]


# ---------------------------------------------------------------------------
# 11. The model's own targets are ignored on the operations path, and compared
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_targets, warns", [([3], True), ([1, 2], False)], ids=["disagree", "agree"]
)
def test_model_targets_disagree_logged(graph_env, caplog, model_targets, warns):
    """Replace slide 2 of 3 with two slides: ``rebuild`` is ``[1, 2]``.  A model
    that targets ``[3]`` (CHARLIE's composed index) is not honoured, and not
    merged in either; the difference is logged as WARNING
    ``operations_targets_disagree``.  Agreeing targets log nothing."""
    prior, before = _seeded(graph_env, (0, 1, 2))
    x, y = _content("X"), _content("Y")

    with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
        t = _turn(graph_env, _ops_out([_replace(1, x, y)], targets=model_targets))

    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [1, 2]
    _assert_laid_out(graph_env, before, [_mk(0), _mk(1), "PENDING", _mk(2)])
    disagree = _named(caplog, "operations_targets_disagree")
    assert len(disagree) == (1 if warns else 0), [r.getMessage() for r in disagree]
