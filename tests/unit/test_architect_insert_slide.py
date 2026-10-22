# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""``architect_node`` applies an insertion (#314, Task 5; plan D1, D3, D4).

An edit whose revised ``deck_spec`` has more slides than the persisted one is an
insertion.  The node aligns the two specs (``align_slides``), re-stamps the
returned spec to positions ``0..m-1``, shifts the committed rows through
``SlideWriter.insert_pending_slides`` BEFORE ``classify_spec_change``, and
targets exactly the inserted and revised slides in the canonical numbering.  It
never honours the model's own targets on an insert, and it never guesses: an
ambiguous alignment, a move, a shrink or a renumber is refused with nothing
written but the chat lines.

How this file asserts, and why:

* **Rows are read by the marker in their own HTML, over the WHOLE row** (every
  column but ``position`` and ``id``), never by position, count or hand-picked
  keys.  "Row 2 has a verdict" and "there are four rows" are both true of a
  deck whose slides were mis-attributed.  Seeds are rich (non-NULL scripts,
  authorship, timestamps, a two-hash verification record and a spec fragment)
  so a lost or swapped column shows; the two JSON columns are compared parsed
  (PLAN-CORRECTIONS C6).
* **"Nothing changed" is a whole-database snapshot**: every slide column, every
  deck column (``deck_spec_json`` and ``version`` included) and the mutation
  evidence count.
* The pending placeholder's HTML is written out literally, so the oracle does
  not depend on the code under test.
* A named log (``insert_targets_disagree``, ``build_looks_like_insert``) is
  found by its name in the record's message or in an ``extra`` field.

Sabotage map (each line names what goes red; verified against a reference
implementation before Task 5 was built):

* targets by position (today's positional ``changed``) -> insert at 2 of 3,
  insert + revision, two inserts, spec-only, gapped insert, deck-level, D5;
* targets from ``alignment.inserted``/``revised`` (positions) on an insert, or
  the shift at those positions -> gapped insert ``after-second-old-numbers``;
* ``revised_indices`` instead of ``revised`` on the equal-length path
  -> both gapped equal-length rows;
* shift only ``if committed_rows`` -> the failed top-of-node read test;
* shift after ``classify_spec_change`` -> the deck-level test;
* skip the shift when the contract also changes -> the design-contract test;
* align before ``complete_index_only_bindings`` -> the completed-bindings test;
* skip the re-stamp, or carry / pre-fan-out-write the model's spec -> the
  three gapped-insert rows whose model numbering is not ``0..3`` (and, for the
  re-stamp, the failed pre-fan-out write test);
* hand the shift the model's spec -> the failed pre-fan-out write test;
* honour the model's targets -> insert at 2 of 3;
* shift on a describe-only turn -> describe-only growth;
* catch ``Exception`` before ``SlideRowsChangedError`` -> ``rows-changed`` and
  the failed top-of-node read;
* ``_degrade_edit`` leaves ``target_positions`` set -> every shift failure;
* no ``PersistedRuntimeError`` re-raise -> its test;
* run the #313 D5 guard on an insert -> the D5 test;
* align only when the spec grows (no equal-length moves check) -> ``swap``;
* keep the old guard or its "added or removed" sentence -> the refusals;
* let ``AlignmentRefused`` escape ``build_looks_like_insert`` -> the shrink and
  reorder build rows (C10); warn whenever a build inserts
  -> insert-and-revise; warn without committed rows -> no-rows; no
  ``insert_targets_disagree`` -> insert at 2 of 3.
"""

from __future__ import annotations

import inspect
import json
import logging
import queue
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pytest

from src.api.services.slide_repository import SlideRowsChangedError, SlideWriter
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.domain.deck_spec import DeckSpec, SlideSpec
from src.domain.skill_io import ArchitectOutput
from src.services.graph import nodes
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import architect_node, build_branch_payload
from src.services.graph.state import scoped
from src.services.persisted_graph_release import PersistedRuntimeError
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    graph_env,
    make_spec,
    review_out,
)

TURN = "turn-1"
USER = "graph-user@example.com"  # graph_env.state()'s initiated_by
NODES_LOGGER = "src.services.graph.nodes"

#: The pending placeholder (plan D4 step 3), written out literally.
PENDING_MESSAGE = "Inserted slide not yet built"
PENDING_HTML = (
    f'<div class="slide-placeholder-error" data-error="{PENDING_MESSAGE}">'
    "<p>New slide — not built yet.</p>"
    "</div>"
)
PENDING_HASH = compute_slide_hash(PENDING_HTML)
PENDING_VERDICT = {"error": True, "message": PENDING_MESSAGE}

#: The refusal sentences, verbatim from the plan (Task 5 steps 2, 3 and 5).
REFUSAL_TEXT = {
    "edit_insert_ambiguous": (
        "I could not tell which of the existing slides I was changing and where "
        "the new slide goes, so nothing has been changed. Ask me to add the slide "
        "on its own first, then for the other change."
    ),
    "edit_spec_moves_slides": (
        "I could not apply that edit: it would have moved existing slides, and an "
        "edit only adds slides or changes the ones that are there. Nothing has "
        "been changed."
    ),
    "edit_spec_positions_changed": (
        "I could not apply that edit: it would have removed or renumbered slides, "
        "and an edit only adds slides or changes the ones that are there. Nothing "
        "has been changed."
    ),
    "insert_rows_changed": (
        "The deck changed while I was planning, so I have not added the slide. "
        "Nothing has been changed; please ask again."
    ),
    "insert_rows_failed": (
        "I could not add the slide, so nothing has been changed. Please try "
        "asking again."
    ),
}

#: The #313 D5 warning's own words (C11: assert on the text, not a count).
D5_TEXT = "may have read a slide number as a position"

NEW_BRIEF = "brief NEW-PRICING"
NEW_AUDIENCE = "the CFO, not engineers"

_MARKER_RE = re.compile(r"MK-[A-Z]+")
_SLIDE_COLUMNS = [c.name for c in SessionSlide.__table__.columns]
_DECK_COLUMNS = [c.name for c in SessionSlideDeck.__table__.columns]
_JSON_COLUMNS = ("verification_record", "deck_spec_slide")


# ---------------------------------------------------------------------------
# Helpers copied from test_graph_nodes.py (:134-170 module level; :618-626 and
# the both-surfaces capture are METHODS of TestAnEditCarriesItsRevisedSpec
# there, rewritten here as functions — PLAN-CORRECTIONS C12).
# ---------------------------------------------------------------------------


def _revised(spec, briefs):
    """*spec* with ``content_brief`` replaced at each position in *briefs*."""
    return spec.model_copy(
        update={
            "slides": [
                slide.model_copy(update={"content_brief": briefs[slide.position]})
                if slide.position in briefs
                else slide
                for slide in spec.slides
            ]
        }
    )


def _edit_out(spec, targets, message="Editing."):
    return ArchitectOutput(
        intent="edit",
        message=message,
        target_positions=list(targets),
        deck_spec=spec,
    )


def _persist(env, spec):
    from src.api.services.deck_level_writer import write_deck_level_columns

    write_deck_level_columns(env.session_id, deck_spec=spec.to_json())


def _run(env, state=None):
    state = state if state is not None else env.state()
    updates = architect_node(state)
    return {**state, **updates}, updates


def _run_and_capture(env, state=None):
    """Run the node; return its updates, the SSE events and the new transcript rows."""
    from src.api.services.session_manager import get_session_manager

    before = len(get_session_manager().get_messages(env.session_id))
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    try:
        updates = architect_node(state if state is not None else env.state())
    finally:
        set_event_emitter(None)
    events = []
    while not emitter.empty():
        events.append(emitter.get_nowait())
    said = [
        m.get("content")
        for m in get_session_manager().get_messages(env.session_id)[before:]
    ]
    return updates, events, said


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------


def _new(tag: str = "NEW-PRICING") -> SlideSpec:
    """A slide the persisted spec does not have (its position is set by _spec_of)."""
    return SlideSpec(
        position=0,
        purpose=f"purpose {tag}",
        content_brief=f"brief {tag}",
        assumes=f"assumes {tag}",
        hands_off=f"hands-off {tag}",
        data_references=[],
    )


def _spec_of(base: DeckSpec, placed: Sequence[Tuple[int, SlideSpec]], **deck) -> DeckSpec:
    """*base*'s deck-level fields with exactly *placed* as its slides, in LIST order.

    Each ``(position, slide)`` pair gives the slide that ``position``.  Validated,
    so a duplicate position is rejected here, as the runtime's parser would.
    """
    data = base.model_dump()
    data.update(deck)
    data["slides"] = [
        {**slide.model_dump(), "position": position} for position, slide in placed
    ]
    return DeckSpec.model_validate(data)


def _canonical(base: DeckSpec, slides: Sequence[SlideSpec], **deck) -> DeckSpec:
    """The re-stamped spec: *slides* in this order at positions ``0..m-1``."""
    return _spec_of(base, list(enumerate(slides)), **deck)


# ---------------------------------------------------------------------------
# Rows: rich seeds, read back whole, found by marker
# ---------------------------------------------------------------------------


def _html(marker: str) -> str:
    return f'<div class="slide"><h1>{marker}</h1><p>its own body text</p></div>'


def _seed_rows(env, layout: Mapping[int, str]) -> None:
    """Committed rows at the given positions (gaps allowed), each fully populated.

    ``graph_env.seed_slides`` enumerates ``0..n-1`` and leaves authorship,
    timestamps, the verification record and the spec fragment NULL, so a whole-row
    comparison over its rows could not see those columns lost.  Creates the deck
    row when there is none.
    """
    db = env.factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        )
        deck = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner.id)
            .first()
        )
        if deck is None:
            db.add(
                SessionSlideDeck(
                    session_id=owner.id,
                    html_content="",
                    scripts_content=None,
                    slide_count=len(layout),
                    version=1,
                )
            )
        for day, (position, marker) in enumerate(sorted(layout.items()), start=1):
            html = _html(marker)
            current = compute_slide_hash(html)
            history = compute_slide_hash(f"<p>an earlier draft of {marker}</p>")
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    slide_id=f"sid-{marker}-{uuid.uuid4().hex[:8]}",
                    html=html,
                    scripts=f"console.log('{marker}');",
                    created_by=f"{marker.lower()}-author@example.com",
                    created_at=datetime(2024, 1, day, 9, 0, 0),
                    modified_by=f"{marker.lower()}-editor@example.com",
                    modified_at=datetime(2024, 2, day, 17, 30, 0),
                    verification_record=json.dumps(
                        {
                            history: {
                                "score": 41,
                                "rating": "poor",
                                "explanation": f"HISTORY-{marker}",
                            },
                            current: {
                                "score": 92,
                                "rating": "good",
                                "explanation": f"CURRENT-{marker}",
                            },
                        }
                    ),
                    deck_spec_slide=json.dumps(
                        {
                            "position": position,
                            "purpose": f"FRAGMENT-{marker}",
                            "content_brief": f"fragment brief {marker}",
                            "assumes": "",
                            "hands_off": "",
                            "data_references": [],
                        }
                    ),
                )
            )
        db.commit()
    finally:
        db.close()


def _decoded(row: SessionSlide) -> Dict[str, Any]:
    out = {name: getattr(row, name) for name in _SLIDE_COLUMNS}
    for name in _JSON_COLUMNS:
        out[name] = json.loads(out[name]) if out[name] is not None else None
    return out


def _rows(env) -> List[Dict[str, Any]]:
    """Every row of this session, whole, in position order."""
    return [_decoded(r) for r in env.rows()]


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
        assert marker not in out, f"two rows carry {marker}: a slide was duplicated"
        out[marker] = row
    return out


def _identity(row: Dict[str, Any]) -> Dict[str, Any]:
    """The whole row minus the two columns a shift legitimately changes."""
    return {k: v for k, v in row.items() if k not in ("position", "id")}


def _layout(rows: List[Dict[str, Any]]) -> List[str]:
    """Position-ordered markers; the pending placeholder shows as PENDING."""
    out = []
    for row in rows:
        marker = _marker(row["html"])
        if marker is not None:
            out.append(marker)
        elif row["html"] == PENDING_HTML:
            out.append("PENDING")
        else:
            out.append(f"OTHER:{row['html']}")
    return out


def _db_state(env) -> Dict[str, Any]:
    """Byte-level snapshot of everything a refused or failed insert must leave alone."""
    db = env.factory()
    try:
        slides = [
            {name: getattr(r, name) for name in _SLIDE_COLUMNS}
            for r in db.query(SessionSlide)
            .order_by(SessionSlide.session_id, SessionSlide.position)
            .all()
        ]
        decks = [
            {name: getattr(d, name) for name in _DECK_COLUMNS}
            for d in db.query(SessionSlideDeck).order_by(SessionSlideDeck.id).all()
        ]
        events = db.query(SharedDeckMutationEvent).count()
        return {"slides": slides, "decks": decks, "events": events}
    finally:
        db.close()


def _insert_events(env) -> List[Tuple[str, str]]:
    db = env.factory()
    try:
        return [
            (e.operation, e.object_type)
            for e in db.query(SharedDeckMutationEvent)
            .order_by(SharedDeckMutationEvent.id)
            .all()
            if e.operation == "insert_slide"
        ]
    finally:
        db.close()


def _persisted_spec(env) -> Optional[DeckSpec]:
    return DeckSpec.from_json(env.deck_row().deck_spec_json)


def _assert_shifted(env, before: Dict[str, Dict[str, Any]], expected_layout: List[str]):
    """Rows are ``0..n+k-1`` in *expected_layout*; every old slide intact by marker;
    every pending row is the pending placeholder, authored by the turn's user."""
    rows = _rows(env)
    assert [r["position"] for r in rows] == list(range(len(expected_layout)))
    assert _layout(rows) == expected_layout
    after = _by_marker(rows)
    assert set(after) == set(before), "a slide was lost or invented by the shift"
    for marker, old in before.items():
        assert _identity(after[marker]) == _identity(old), (
            f"{marker}'s row changed in the shift (identity, authorship, timestamps, "
            "verification record or spec fragment did not travel with it)"
        )
    pending = [r for r in rows if r["html"] == PENDING_HTML]
    assert len(pending) == expected_layout.count("PENDING")
    old_ids = {old["slide_id"] for old in before.values()}
    for row in pending:
        assert row["verification_record"] == {PENDING_HASH: PENDING_VERDICT}
        assert row["created_by"] == USER
        assert row["modified_by"] == USER
        assert row["slide_id"] and row["slide_id"] not in old_ids
    assert len({r["slide_id"] for r in pending}) == len(pending)


def _named(caplog, name: str, level: int = logging.WARNING) -> List[logging.LogRecord]:
    """The nodes-logger records at *level* that carry *name* (message or extra)."""
    found = []
    for record in caplog.records:
        if record.name != NODES_LOGGER or record.levelno != level:
            continue
        extras = {v for v in vars(record).values() if isinstance(v, str)}
        if name in record.getMessage() or name in extras:
            found.append(record)
    return found


def _warnings(caplog) -> List[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == NODES_LOGGER and r.levelno >= logging.WARNING
    ]


def _spy_on_the_shift(monkeypatch) -> List[Dict[str, Any]]:
    """Record every ``insert_pending_slides`` call (bound arguments), then run it."""
    real = SlideWriter.insert_pending_slides
    signature = inspect.signature(real)
    calls: List[Dict[str, Any]] = []

    def spy(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        calls.append({k: v for k, v in bound.arguments.items() if k != "self"})
        return real(self, *args, **kwargs)

    monkeypatch.setattr(SlideWriter, "insert_pending_slides", spy)
    return calls


THREE = {0: "MK-ALPHA", 1: "MK-BRAVO", 2: "MK-CHARLIE"}
FOUR = {0: "MK-ALPHA", 1: "MK-BRAVO", 2: "MK-CHARLIE", 3: "MK-DELTA"}
GAPPED = {0: "MK-ALPHA", 2: "MK-BRAVO", 5: "MK-CHARLIE"}


def _three_slide_deck(env) -> Tuple[DeckSpec, Dict[str, Dict[str, Any]]]:
    _seed_rows(env, THREE)
    prior = make_spec((0, 1, 2))
    _persist(env, prior)
    return prior, _by_marker(_rows(env))


# ---------------------------------------------------------------------------
# Applied inserts
# ---------------------------------------------------------------------------


class TestAnInsertIsApplied:
    def test_insert_at_2_of_3_shifts_the_rows_and_targets_only_the_new_slide(
        self, graph_env, caplog
    ):
        """The headline case: a new slide between b and c.

        The model re-stamps its spec 0..3 but targets ``[3]`` (it counted the
        slide that moved).  The node targets the alignment's insert, ``[2]``,
        logs the disagreement, and never rebuilds c.

        Sabotage: positional ``changed`` -> ``[2, 3]``; honour the model's targets
        -> ``3`` is targeted.
        """
        prior, before = _three_slide_deck(graph_env)
        a, b, c = prior.slides
        model_spec = _spec_of(prior, [(0, a), (1, b), (2, _new()), (3, c)])
        graph_env.skills.set("architect", _edit_out(model_spec, [3]))

        with caplog.at_level(logging.INFO, logger=NODES_LOGGER):
            merged, updates = _run(graph_env)

        assert updates["architect_intent"] == "edit"
        assert updates["error_state"] is None
        assert updates["target_positions"] == [2]
        canonical = _canonical(prior, [a, b, _new(), c])
        assert updates["deck_spec"] == canonical
        assert _persisted_spec(graph_env) == canonical
        _assert_shifted(graph_env, before, ["MK-ALPHA", "MK-BRAVO", "PENDING", "MK-CHARLIE"])
        assert len(_named(caplog, "insert_targets_disagree")) == 1, (
            "the model's [3] target differs from the canonical [2] and must be logged"
        )
        assert build_branch_payload(merged, 2)["slide_spec"]["content_brief"] == NEW_BRIEF
        assert build_branch_payload(merged, 3)["slide_spec"]["content_brief"] == "brief-2"
        assert _insert_events(graph_env) == [("insert_slide", "deck")]

    def test_the_shift_is_called_once_with_the_canonical_arguments(
        self, graph_env, monkeypatch
    ):
        """The node's half of the contract with the shift (plan Task 5 step 5)."""
        prior, before = _three_slide_deck(graph_env)
        a, b, c = prior.slides
        planned = [
            (r["slide_id"], compute_slide_hash(r["html"])) for r in _rows(graph_env)
        ]
        graph_env.skills.set(
            "architect",
            _edit_out(_spec_of(prior, [(0, a), (1, b), (2, _new()), (3, c)]), [2]),
        )
        calls = _spy_on_the_shift(monkeypatch)

        _run(graph_env)

        assert len(calls) == 1
        call = calls[0]
        assert call["session_id"] == graph_env.session_id
        assert list(call["insert_at"]) == [2]
        assert DeckSpec.from_json(call["deck_spec"]) == _canonical(prior, [a, b, _new(), c])
        assert [tuple(r) for r in call["expected_rows"]] == planned
        assert call["created_by"] == USER
        mutation = call["mutation"]
        assert (mutation.operation, mutation.object_type) == ("insert_slide", "deck")
        assert mutation.actor.actor_session_id == graph_env.session_id
        assert mutation.actor.graph_release_id == 1

    @pytest.mark.parametrize(
        "where", ["revision-after-the-insert", "revision-before-the-insert"]
    )
    def test_an_insert_with_a_non_adjacent_revision_targets_both(self, graph_env, where):
        """The revision is rebuilt from its revised brief at its NEW index; the
        untouched slides that only moved are not rebuilt."""
        _seed_rows(graph_env, FOUR)
        prior = make_spec((0, 1, 2, 3))
        _persist(graph_env, prior)
        before = _by_marker(_rows(graph_env))
        a, b, c, d = prior.slides
        if where == "revision-after-the-insert":
            revised = d.model_copy(update={"content_brief": "REVISED brief for d"})
            order = [a, _new(), b, c, revised]
            layout = ["MK-ALPHA", "PENDING", "MK-BRAVO", "MK-CHARLIE", "MK-DELTA"]
            targets, revised_at, new_at = [1, 4], 4, 1
        else:
            revised = a.model_copy(update={"content_brief": "REVISED brief for a"})
            order = [revised, b, c, _new(), d]
            layout = ["MK-ALPHA", "MK-BRAVO", "MK-CHARLIE", "PENDING", "MK-DELTA"]
            targets, revised_at, new_at = [0, 3], 0, 3
        graph_env.skills.set(
            "architect", _edit_out(_spec_of(prior, list(enumerate(order))), [new_at])
        )

        merged, updates = _run(graph_env)

        assert updates["architect_intent"] == "edit"
        assert updates["error_state"] is None
        assert updates["target_positions"] == targets
        assert updates["deck_spec"] == _canonical(prior, order)
        _assert_shifted(graph_env, before, layout)
        assert (
            build_branch_payload(merged, revised_at)["slide_spec"]["content_brief"]
            == revised.content_brief
        )
        assert build_branch_payload(merged, new_at)["slide_spec"]["content_brief"] == (
            NEW_BRIEF
        )

    def test_an_append_moves_no_existing_row(self, graph_env):
        prior, before = _three_slide_deck(graph_env)
        a, b, c = prior.slides
        graph_env.skills.set(
            "architect",
            _edit_out(_spec_of(prior, [(0, a), (1, b), (2, c), (3, _new())]), [3]),
        )

        merged, updates = _run(graph_env)

        assert updates["architect_intent"] == "edit"
        assert updates["target_positions"] == [3]
        assert updates["deck_spec"] == _canonical(prior, [a, b, c, _new()])
        _assert_shifted(graph_env, before, ["MK-ALPHA", "MK-BRAVO", "MK-CHARLIE", "PENDING"])
        assert build_branch_payload(merged, 3)["slide_spec"]["content_brief"] == NEW_BRIEF

    def test_two_inserts_open_two_pending_rows_and_target_both(self, graph_env):
        prior, before = _three_slide_deck(graph_env)
        a, b, c = prior.slides
        x, y = _new("NEW-ONE"), _new("NEW-TWO")
        graph_env.skills.set(
            "architect",
            _edit_out(_spec_of(prior, [(0, a), (1, x), (2, b), (3, y), (4, c)]), [1, 3]),
        )

        merged, updates = _run(graph_env)

        assert updates["architect_intent"] == "edit"
        assert updates["target_positions"] == [1, 3]
        assert updates["deck_spec"] == _canonical(prior, [a, x, b, y, c])
        _assert_shifted(
            graph_env,
            before,
            ["MK-ALPHA", "PENDING", "MK-BRAVO", "PENDING", "MK-CHARLIE"],
        )
        assert build_branch_payload(merged, 1)["slide_spec"]["content_brief"] == "brief NEW-ONE"
        assert build_branch_payload(merged, 3)["slide_spec"]["content_brief"] == "brief NEW-TWO"

    def test_a_spec_only_deck_writes_the_spec_and_opens_no_pending_row(self, graph_env):
        """A deck described but not yet built: there is no row to shift, so the
        canonical spec is written and nothing else (D4 step 1, both empty)."""
        prior = make_spec((0, 1, 2))
        _persist(graph_env, prior)
        a, b, c = prior.slides
        graph_env.skills.set(
            "architect",
            _edit_out(_spec_of(prior, [(0, a), (1, _new()), (2, b), (3, c)]), [1]),
        )

        merged, updates = _run(graph_env)

        assert updates["architect_intent"] == "edit"
        assert updates["error_state"] is None
        assert updates["target_positions"] == [1]
        canonical = _canonical(prior, [a, _new(), b, c])
        assert updates["deck_spec"] == canonical
        assert _persisted_spec(graph_env) == canonical
        assert _rows(graph_env) == []
        assert build_branch_payload(merged, 1)["slide_spec"]["content_brief"] == NEW_BRIEF


# ---------------------------------------------------------------------------
# Gapped decks: positions on the equal-length path, indices on the insert path
# ---------------------------------------------------------------------------


class TestAGappedDeck:
    """Rows and spec at ``[0, 2, 5]`` (``seed_slides`` cannot seed gaps)."""

    def _gapped(self, env) -> Tuple[DeckSpec, Dict[str, Dict[str, Any]]]:
        _seed_rows(env, GAPPED)
        prior = make_spec((0, 2, 5))
        _persist(env, prior)
        return prior, _by_marker(_rows(env))

    @pytest.mark.parametrize("revised_position", [5, 2])
    def test_an_equal_length_edit_targets_the_revised_position(
        self, graph_env, monkeypatch, revised_position
    ):
        """The equal-length path keeps POSITIONS (``alignment.revised``), exactly as
        today's positional ``changed``, and shifts and re-stamps nothing.

        Green before Task 5 on purpose: it guards the regression.  Sabotage:
        ``revised_indices`` -> ``[2]``/``[1]``, and ``build_branch_payload`` raises
        at position 1 (no slide there).
        """
        prior, _ = self._gapped(graph_env)
        rows_before = _rows(graph_env)
        brief = f"REVISED brief at {revised_position}"
        graph_env.skills.set(
            "architect",
            _edit_out(_revised(prior, {revised_position: brief}), [revised_position]),
        )
        calls = _spy_on_the_shift(monkeypatch)

        merged, updates = _run(graph_env)

        assert updates["architect_intent"] == "edit"
        assert updates["error_state"] is None
        assert updates["target_positions"] == [revised_position]
        assert [s.position for s in updates["deck_spec"].slides] == [0, 2, 5]
        payload = build_branch_payload(merged, revised_position)
        assert payload["slide_spec"]["content_brief"] == brief
        assert calls == []
        assert _rows(graph_env) == rows_before

    @pytest.mark.parametrize(
        "model_positions, insert_index",
        [
            # (positions the model gives [ALPHA, NEW, BRAVO, CHARLIE] or
            # [ALPHA, BRAVO, NEW, CHARLIE]; list order given separately below)
            ({"ALPHA": 0, "NEW": 1, "BRAVO": 2, "CHARLIE": 3}, 1),
            ({"ALPHA": 0, "NEW": 1, "BRAVO": 2, "CHARLIE": 5}, 1),
            ({"ALPHA": 0, "BRAVO": 2, "NEW": 3, "CHARLIE": 5}, 2),
            ({"ALPHA": 0, "BRAVO": 2, "CHARLIE": 5, "NEW": 1}, 1),
        ],
        ids=[
            "after-first-restamped",
            "after-first-old-numbers",
            "after-second-old-numbers",
            "after-first-listed-last",
        ],
    )
    def test_a_gapped_insert_makes_rows_and_spec_contiguous(
        self, graph_env, model_positions, insert_index
    ):
        """Whatever numbering the model used, rows and spec become ``0..3``, every
        slide keeps its row and its spec entry, and the target is the new INDEX.

        ``after-second-old-numbers`` is the row where positions and indices part:
        the new slide is model position 3 but canonical index 2.  Sabotage: skip
        the re-stamp -> the builder for 2 is briefed with BRAVO's brief, and every
        ``*-old-numbers`` spec stays gapped; target by position -> ``[3]``.
        """
        prior, before = self._gapped(graph_env)
        source = {"ALPHA": prior.slides[0], "BRAVO": prior.slides[1],
                  "CHARLIE": prior.slides[2], "NEW": _new()}
        # List order is the dict's order; for "listed-last" it differs from
        # position order on purpose.
        model_spec = _spec_of(
            prior, [(position, source[name]) for name, position in model_positions.items()]
        )
        in_order = [source[n] for n in sorted(model_positions, key=model_positions.get)]
        graph_env.skills.set("architect", _edit_out(model_spec, [model_positions["NEW"]]))

        merged, updates = _run(graph_env)

        assert updates["architect_intent"] == "edit"
        assert updates["error_state"] is None
        assert updates["target_positions"] == [insert_index]
        canonical = _canonical(prior, in_order)
        assert updates["deck_spec"] == canonical
        assert _persisted_spec(graph_env) == canonical
        layout = ["MK-ALPHA", "MK-BRAVO", "MK-CHARLIE"]
        layout.insert(insert_index, "PENDING")
        _assert_shifted(graph_env, before, layout)
        assert build_branch_payload(merged, insert_index)["slide_spec"][
            "content_brief"
        ] == NEW_BRIEF
        # Every old slide's spec entry sits at its row's new index.
        for index, row in enumerate(_rows(graph_env)):
            marker = _marker(row["html"])
            if marker is None:
                continue
            name = marker.split("-", 1)[1]
            assert canonical.slide_at(index) == source[name].model_copy(
                update={"position": index}
            ), f"{marker}'s spec entry is not at its row's index {index}"

    def test_a_failed_pre_fan_out_write_still_leaves_rows_and_spec_aligned(
        self, graph_env, monkeypatch
    ):
        """D4's rollback guarantee: the shift writes the CANONICAL spec in its own
        transaction, so when the later pre-fan-out write fails the rows and the
        persisted spec still agree, and the turn records ``deck_level_write_failed``
        as today.  The model numbers the new slide 3 between 2 and 5, so its own
        spec differs from the canonical one.

        Sabotage: hand the shift the model's un-re-stamped spec -> the persisted
        spec stays gapped over contiguous rows.  Only the architect's write (the
        one carrying ``deck_spec=``) is failed (C13).
        """
        prior, before = self._gapped(graph_env)
        alpha, bravo, charlie = prior.slides
        model_spec = _spec_of(prior, [(0, alpha), (2, bravo), (3, _new()), (5, charlie)])
        graph_env.skills.set("architect", _edit_out(model_spec, [3]))
        real_write = nodes.write_deck_level_columns

        def _failing_write(session_id, **kwargs):
            if "deck_spec" in kwargs:
                raise RuntimeError("the pre-fan-out write failed")
            return real_write(session_id, **kwargs)

        monkeypatch.setattr(nodes, "write_deck_level_columns", _failing_write)

        _, updates = _run(graph_env)

        assert updates["error_state"]["code"] == "deck_level_write_failed"
        assert updates["target_positions"] == [2]
        assert _persisted_spec(graph_env) == _canonical(
            prior, [alpha, bravo, _new(), charlie]
        )
        _assert_shifted(graph_env, before, ["MK-ALPHA", "MK-BRAVO", "PENDING", "MK-CHARLIE"])


# ---------------------------------------------------------------------------
# Nothing changes: a failed read, refusals, a failed shift
# ---------------------------------------------------------------------------


class TestNothingChanges:
    def _insert_at_2(self, prior: DeckSpec, message: str = "Adding a slide.") -> ArchitectOutput:
        a, b, c = prior.slides
        return _edit_out(
            _spec_of(prior, [(0, a), (1, b), (2, _new()), (3, c)]), [2], message=message
        )

    def _assert_refused(self, updates, events, said, code, model_message):
        assert updates["architect_intent"] == "discuss"
        assert updates["error_state"]["code"] == code
        assert updates["error_state"]["node"] == "architect"
        assert updates["target_positions"] is None
        assert "deck_spec" not in updates
        refusal = updates["architect_message"]
        assert refusal == REFUSAL_TEXT[code]
        architect_lines = [
            e.content for e in events if (e.metadata or {}).get("node") == "architect"
        ]
        assert architect_lines == [model_message, refusal], (
            "the SSE client was not told the edit could not be applied"
        )
        assert events[-1].metadata.get("intent") == "discuss"
        assert said == [model_message, refusal], (
            "the transcript (polling client, next turn) does not say the edit "
            "could not be applied"
        )

    def test_a_failed_top_of_node_read_still_shifts_and_is_refused(
        self, graph_env, monkeypatch
    ):
        """The row read swallows every error and returns ``[]``.  The shift still
        runs (it re-reads in its own transaction), finds rows the node did not plan
        against, and refuses: nothing is written (finding 3).

        Sabotage: shift only ``if committed_rows`` -> the edit is accepted and
        briefs a builder over rows the node never saw.
        """
        prior, _ = _three_slide_deck(graph_env)
        monkeypatch.setattr(nodes, "_committed_slide_rows", lambda session_id: [])
        model_message = "Adding a slide."
        graph_env.skills.set("architect", self._insert_at_2(prior, model_message))
        snapshot = _db_state(graph_env)

        updates, events, said = _run_and_capture(graph_env)

        self._assert_refused(updates, events, said, "insert_rows_changed", model_message)
        assert _db_state(graph_env) == snapshot

    @pytest.mark.parametrize(
        "case, code",
        [
            ("ambiguous", "edit_insert_ambiguous"),
            ("insert-and-move", "edit_spec_moves_slides"),
            ("swap", "edit_spec_moves_slides"),
            ("shrink", "edit_spec_positions_changed"),
            ("renumber", "edit_spec_positions_changed"),
        ],
    )
    def test_a_refused_insert_changes_nothing_and_says_so(self, graph_env, case, code):
        """Refused, never guessed (D1), with rows, spec and version untouched (D4).

        * ambiguous: an insert next to a rewrite of its neighbour ties two ways;
        * insert-and-move: ``[a, b, c] -> [b, a, NEW, c]`` (C1, clause b);
        * swap: an equal-length ``[b, a, c]``;
        * shrink ``(0, 1)`` and renumber ``(0, 1, 3)``: the position-set guard,
          whose sentence no longer says "added".
        """
        prior, _ = _three_slide_deck(graph_env)
        a, b, c = prior.slides
        model_message = "Editing the deck."
        if case == "ambiguous":
            rewritten = b.model_copy(update={"content_brief": "REWRITTEN brief for b"})
            spec, targets = _spec_of(prior, [(0, a), (1, rewritten), (2, _new()), (3, c)]), [1, 2]
        elif case == "insert-and-move":
            spec, targets = _spec_of(prior, [(0, b), (1, a), (2, _new()), (3, c)]), [2]
        elif case == "swap":
            spec, targets = _spec_of(prior, [(0, b), (1, a), (2, c)]), [0, 1]
        elif case == "shrink":
            spec, targets = _revised(make_spec((0, 1)), {1: "revised brief-1"}), [1]
        else:
            spec, targets = _revised(make_spec((0, 1, 3)), {1: "revised brief-1"}), [1]
        graph_env.skills.set("architect", _edit_out(spec, targets, message=model_message))
        snapshot = _db_state(graph_env)

        updates, events, said = _run_and_capture(graph_env)

        self._assert_refused(updates, events, said, code, model_message)
        assert _db_state(graph_env) == snapshot

    @pytest.mark.parametrize(
        "error, code",
        [
            (SlideRowsChangedError("the rows moved under the planner"), "insert_rows_changed"),
            (RuntimeError("the database went away"), "insert_rows_failed"),
        ],
        ids=["rows-changed", "any-other-error"],
    )
    def test_a_failed_shift_degrades_with_nothing_changed(
        self, graph_env, monkeypatch, error, code
    ):
        """``SlideRowsChangedError`` is a ``RuntimeError``: catching ``Exception``
        first would report every changed deck as a failure."""
        prior, _ = _three_slide_deck(graph_env)

        def _raise(self, *args, **kwargs):
            raise error

        monkeypatch.setattr(SlideWriter, "insert_pending_slides", _raise)
        model_message = "Adding a slide."
        graph_env.skills.set("architect", self._insert_at_2(prior, model_message))
        snapshot = _db_state(graph_env)

        updates, events, said = _run_and_capture(graph_env)

        self._assert_refused(updates, events, said, code, model_message)
        assert _db_state(graph_env) == snapshot

    def test_a_persisted_runtime_failure_in_the_shift_is_re_raised(
        self, graph_env, monkeypatch
    ):
        """Step 5: ``_raise_if_persisted_runtime_failure`` runs before the degrade."""
        prior, _ = _three_slide_deck(graph_env)

        def _raise(self, *args, **kwargs):
            raise PersistedRuntimeError("the pinned runtime is unavailable")

        monkeypatch.setattr(SlideWriter, "insert_pending_slides", _raise)
        graph_env.skills.set("architect", self._insert_at_2(prior))

        with pytest.raises(PersistedRuntimeError):
            architect_node(graph_env.state())


# ---------------------------------------------------------------------------
# A deck-level change on an insert turn
# ---------------------------------------------------------------------------


class TestADeckLevelChangeOnAnInsertTurn:
    def test_each_shifted_slide_is_re_reviewed_with_its_own_html_and_spec(
        self, graph_env
    ):
        """The shift lands BEFORE ``classify_spec_change``, so the re-review reads
        the shifted rows against the re-stamped spec: CHARLIE (now at 3) is judged
        against CHARLIE's brief.  The pending row is a placeholder, so it fails by
        definition with no model call, and is the only slide rebuilt.

        Sabotage: shift after ``classify_spec_change`` -> CHARLIE's HTML is
        reviewed against the NEW slide's brief at 2, and 3 has no row.
        """
        prior, before = _three_slide_deck(graph_env)
        a, b, c = prior.slides
        model_spec = _spec_of(
            prior, [(0, a), (1, b), (2, _new()), (3, c)], audience=NEW_AUDIENCE
        )
        graph_env.skills.set("architect", _edit_out(model_spec, [2]))
        graph_env.skills.set(
            "build_reviewer", lambda payload: review_out(payload["position"])
        )

        _, updates = _run(graph_env)

        own_brief = {"MK-ALPHA": "brief-0", "MK-BRAVO": "brief-1", "MK-CHARLIE": "brief-2"}
        calls = [c["payload"] for c in graph_env.skills.calls_for("build_reviewer")]
        reviewed = {_marker(p["html"]): p for p in calls}
        assert sorted(reviewed, key=str) == sorted(own_brief), (
            "every committed slide, and only those, is re-reviewed (never the pending row)"
        )
        assert all(PENDING_HTML != p["html"] for p in calls)
        rows = _by_marker(_rows(graph_env))
        for marker, payload in reviewed.items():
            assert payload["html"] == rows[marker]["html"]
            assert payload["slide_spec"]["content_brief"] == own_brief[marker], (
                f"{marker} was reviewed against another slide's spec entry"
            )
            assert payload["slide_spec"]["position"] == payload["position"]
            assert payload["position"] == rows[marker]["position"]
            assert payload["deck_brief"]["audience"] == NEW_AUDIENCE
        assert updates["target_positions"] == [2]
        assert updates["deck_spec"] == _canonical(
            prior, [a, b, _new(), c], audience=NEW_AUDIENCE
        )
        _assert_shifted(graph_env, before, ["MK-ALPHA", "MK-BRAVO", "PENDING", "MK-CHARLIE"])


# ---------------------------------------------------------------------------
# A design-contract change on an insert turn (D3: rebuild all, still shift first)
# ---------------------------------------------------------------------------


class TestADesignContractChangeOnAnInsertTurn:
    def test_the_rows_are_shifted_once_and_then_every_position_is_rebuilt(
        self, graph_env, monkeypatch
    ):
        """A restyle rebuilds every position (§4.6), but the rows must still shift
        first: rebuilt in place over unshifted rows, CHARLIE's row (its slide_id,
        authorship and verification record) would become the new slide at 2, and
        CHARLIE would be rebuilt into a fresh row at 3 with none of its own.
        Exactly one shift, and the pre-fan-out write carries the same canonical
        spec rather than a second shift or the model's numbering.

        Sabotage (review s8): skip the shift when the contract changes -> rows
        unshifted, no shift call.
        """
        prior, before = _three_slide_deck(graph_env)
        a, b, c = prior.slides
        restyled = {"design_system_id": 7, "template_id": None, "slide_style_id": None}
        model_spec = _spec_of(
            prior, [(0, a), (1, b), (2, _new()), (3, c)], design_contract=restyled
        )
        graph_env.skills.set("architect", _edit_out(model_spec, [2]))
        calls = _spy_on_the_shift(monkeypatch)

        _, updates = _run(graph_env)

        assert updates["architect_intent"] == "edit"
        assert updates["error_state"] is None
        assert updates["target_positions"] == [0, 1, 2, 3]
        canonical = _canonical(prior, [a, b, _new(), c], design_contract=restyled)
        assert updates["deck_spec"] == canonical
        assert _persisted_spec(graph_env) == canonical
        assert len(calls) == 1 and list(calls[0]["insert_at"]) == [2]
        _assert_shifted(graph_env, before, ["MK-ALPHA", "MK-BRAVO", "PENDING", "MK-CHARLIE"])
        assert _insert_events(graph_env) == [("insert_slide", "deck")]


# ---------------------------------------------------------------------------
# The alignment reads the spec AFTER the bindings are completed
# ---------------------------------------------------------------------------


class TestTheAlignmentSeesTheCompletedBindings:
    #: The stub template's sections carry no ``data-label``, so with it
    #: ``complete_index_only_bindings`` does nothing; these two are labelled.
    LABELLED_LAYOUT = (
        "<main class='deck'>"
        "<section class='slide' data-label='title'><h1>Title</h1></section>"
        "<section class='slide' data-label='content'><h1>Body</h1></section>"
        "</main>"
    )

    def test_index_only_bindings_on_untouched_slides_are_not_revisions(
        self, graph_env
    ):
        """Lagging model output binds ``template_section_index`` without
        ``slide_type``; the node completes the pair from the template.  The
        persisted slides carry the completed pair, so the untouched slides only
        equal them AFTER completion: aligned before it, every untouched slide
        reads as revised and is rebuilt, which is exactly what "only the new slide
        is built" forbids.

        Sabotage (review s10): align before ``complete_index_only_bindings`` ->
        targets ``[0, 1, 2, 3]``.
        """
        graph_env.template.layout = self.LABELLED_LAYOUT
        _seed_rows(graph_env, THREE)
        prior = make_spec(
            (0, 1, 2),
            design_system_id=7,
            template_id=3,
            slide_type="content",
            template_section_index=1,
        )
        _persist(graph_env, prior)
        before = _by_marker(_rows(graph_env))
        a, b, c = (s.model_copy(update={"slide_type": None}) for s in prior.slides)
        new = _new().model_copy(update={"template_section_index": 1})
        graph_env.skills.set(
            "architect",
            _edit_out(_spec_of(prior, [(0, a), (1, b), (2, new), (3, c)]), [2]),
        )

        _, updates = _run(graph_env)

        assert updates["architect_intent"] == "edit"
        assert updates["error_state"] is None
        assert updates["target_positions"] == [2]
        completed = new.model_copy(update={"slide_type": "content"})
        bound_a, bound_b, bound_c = prior.slides
        canonical = _canonical(prior, [bound_a, bound_b, completed, bound_c])
        assert updates["deck_spec"] == canonical
        assert _persisted_spec(graph_env) == canonical
        _assert_shifted(graph_env, before, ["MK-ALPHA", "MK-BRAVO", "PENDING", "MK-CHARLIE"])


# ---------------------------------------------------------------------------
# Paths that do not shift: describe-only, and the #313 D5 guard
# ---------------------------------------------------------------------------


class TestPathsThatDoNotShift:
    def test_a_describe_only_growth_is_not_persisted_and_shifts_nothing(
        self, graph_env, monkeypatch
    ):
        """The arc-review sweeper dispatches no builder: no alignment, no shift,
        and (as on every describe-only turn) no version bump.  It sees no HTML
        either, so a re-description with another position set describes slides
        that are not there: the persisted spec is kept (#314 follow-up, N2(a),
        on every deck — PLAN-REVIEW m4).

        Sabotage: shift on describe-only -> rows gain a pending row and the
        version moves; N2(a) removed -> the grown spec is persisted.
        """
        prior, _ = _three_slide_deck(graph_env)
        a, b, c = prior.slides
        rows_before = _rows(graph_env)
        version_before = graph_env.deck_row().version
        grown = _spec_of(prior, [(0, a), (1, _new()), (2, b), (3, c)])
        graph_env.skills.set("architect", _edit_out(grown, [1]))
        calls = _spy_on_the_shift(monkeypatch)

        updates = architect_node(graph_env.state(describe_only=scoped(TURN, True)))

        assert updates["error_state"] is None
        assert updates["architect_intent"] == "edit"
        assert _persisted_spec(graph_env) == prior
        assert calls == []
        assert _rows(graph_env) == rows_before
        assert graph_env.deck_row().version == version_before

    def test_an_insert_after_a_named_slide_is_not_an_ignored_reference(
        self, graph_env, caplog
    ):
        """#313 D5 is skipped on an insert turn: "after slide 2" names the ANCHOR
        (position 1), never a target, so the new slide's target [2] missing it is
        not an off-by-one.  The model's targets equal the canonical ones, and the
        assertion is on D5's own text (C11).

        Sabotage: run the D5 guard on inserts -> its warning is logged.
        """
        prior, _ = _three_slide_deck(graph_env)
        a, b, c = prior.slides
        graph_env.skills.set(
            "architect",
            _edit_out(_spec_of(prior, [(0, a), (1, b), (2, _new()), (3, c)]), [2]),
        )

        with caplog.at_level(logging.WARNING, logger=NODES_LOGGER):
            _, updates = _run(
                graph_env,
                graph_env.state(architect_message="Add a slide on pricing after slide 2"),
            )

        # Precondition: the reference resolved, so D5 WOULD fire on these targets.
        references = graph_env.skills.calls_for("architect")[0]["payload"]["slide_references"]
        assert [r["positions"] for r in references] == [[1]]
        assert updates["architect_intent"] == "edit"
        assert updates["target_positions"] == [2]
        assert [r.getMessage() for r in caplog.records if D5_TEXT in r.getMessage()] == []


# ---------------------------------------------------------------------------
# build_looks_like_insert (D1, review finding 14; C10)
# ---------------------------------------------------------------------------


class TestABuildThatLooksLikeAnInsert:
    """A ``build`` answer to an add rebuilds every position in place (pre-existing
    build semantics), so the node WARNS when a build spec is the persisted spec
    plus new slides over existing rows.  It changes nothing else: no shift, no
    re-stamp, no targets.  The diagnostic must never fail a build (C10)."""

    @pytest.mark.parametrize(
        "case, warns",
        [
            ("pure-insert", True),
            ("insert-and-revise", False),
            ("unchanged", False),
            ("shrink", False),
            ("reorder", False),
            ("no-rows", False),
        ],
    )
    def test_the_warning_fires_only_for_a_pure_insertion(
        self, graph_env, caplog, monkeypatch, case, warns
    ):
        prior = make_spec((0, 1, 2))
        if case != "no-rows":
            _seed_rows(graph_env, THREE)
        _persist(graph_env, prior)
        rows_before = _rows(graph_env)
        a, b, c = prior.slides
        spec = {
            "pure-insert": [a, b, _new(), c],
            "no-rows": [a, b, _new(), c],
            # The revision is NOT adjacent to the insert: next to it, the build
            # spec would align ambiguously and this row would test C10 instead.
            "insert-and-revise": [
                a.model_copy(update={"content_brief": "REVISED brief for a"}), b, _new(), c
            ],
            "unchanged": [a, b, c],
            "shrink": [a, b],
            "reorder": [b, a, c],
        }[case]
        model_spec = _canonical(prior, spec)
        graph_env.skills.set("architect", architect_build(model_spec))
        calls = _spy_on_the_shift(monkeypatch)

        with caplog.at_level(logging.WARNING, logger=NODES_LOGGER):
            _, updates = _run(graph_env)

        assert updates["architect_intent"] == "build"
        assert updates["error_state"] is None
        assert updates["target_positions"] is None
        assert updates["deck_spec"] == model_spec
        assert calls == [], "a build turn never shifts rows"
        assert _rows(graph_env) == rows_before
        named = _named(caplog, "build_looks_like_insert")
        if warns:
            assert len(named) == 1
            assert [r.getMessage() for r in _warnings(caplog)] == [named[0].getMessage()]
        else:
            assert _warnings(caplog) == [], [r.getMessage() for r in _warnings(caplog)]
