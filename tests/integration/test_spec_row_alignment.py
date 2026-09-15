"""ws4d final review C1 — the persisted spec must still describe THESE rows.

Two representations of the same per-slide brief exist.  ``session_slides.
deck_spec_slide`` travels with its row on every mutation (Task 7), while
``session_slide_decks.deck_spec_json``'s ``slides[].position`` entries are
renumbered on **insert only**: delete, duplicate and reorder leave the deck-level
spec describing slides that have moved or gone.  The whole-branch review measured
all four routes.

This suite is about the CONSUMER, because that is where the fix went.
``architect_node`` falls back to the persisted spec whenever the architect emits
none — the real shape of an edit turn — and both the builder brief and §4.6's
re-review then resolve slides out of it **by position**.  So a stale spec is not
an inert inconsistency; it is a brief handed to a builder for the wrong slide.

Measured on the tree before the guard, by these tests:

* delete the third slide, then ask to edit "the third slide": a builder is
  dispatched for position 2, which has no row, and **the deck gains a slide
  nobody asked for** (rows went ``[0, 1]`` -> ``[0, 1, 2]``);
* delete the *middle* slide, then ask to edit position 1: the builder is briefed
  with ``brief-1`` — the brief of the slide that used to be there — and
  **overwrites the human's surviving slide** with a rebuild against it
  (row 1's HTML went ``Slide 2`` -> ``Slide 1``).

What the guard can and cannot see, stated so nobody reads more into it
---------------------------------------------------------------------
It compares POSITION SETS, so it catches the two mutations that change the row
set's cardinality (delete, duplicate).  A **reorder** leaves ``{0, 1, 2}`` on
both sides while every position describes a different slide, and no consumer-side
check can see that: the deck-level spec has no per-slide identity to compare a
row against.  Two stronger predicates were measured and rejected, both because
they fire on decks that are correctly aligned —

* comparing each row's own ``deck_spec_slide.position`` to its row position fires
  after an **insert**, which is the one route that renumbers the deck-level spec
  correctly (the row fragments travel with their slides and keep their original
  position field);
* comparing the row's fragment CONTENT to the deck-level entry fires after any
  §4.6 deck-level change, where the spec is deliberately newer than the slides
  that have not been rebuilt against it yet.

So a reorder is closed only by renumbering in the routes, which is the strictly
larger fix this branch did not take.

Why the premise test is here
----------------------------
:func:`test_a_delete_leaves_the_deck_level_spec_describing_slides_that_moved`
measures the misalignment through the **real** ``ChatService.delete_slide`` on
every run.  Without it the two damage tests could quietly become tests of nothing
— a future change that renumbers the deck spec in the routes would make their
setup produce an ALIGNED deck, the guard would stop firing, and "no builder was
dispatched" would be satisfied by a turn that had no reason to refuse.  That
change should redden the premise test first, and whoever makes it should then
relax these three rather than delete the guard.
"""

from __future__ import annotations

import contextlib

import pytest

from src.domain.deck_spec import DeckSpec
from tests.integration.conftest_stub_skills import builder_html

pytestmark = pytest.mark.integration


def _fake_db(factory):
    """``get_db_session`` against this test's engine.

    ``ChatService`` reaches the database through *function-local* imports of
    ``src.core.database.get_db_session``, which the ``graph_turn_env`` fixture's
    per-module patches do not cover, so the real route's service is redirected at
    the source module instead.
    """

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


def _service(env, monkeypatch):
    """The real ``ChatService`` the slide routes call, wired to this database."""
    from src.api.services.chat_service import ChatService

    monkeypatch.setattr("src.core.database.get_db_session", _fake_db(env.factory))
    return ChatService()


def _spec_positions(env) -> list[int]:
    return [
        slide.position
        for slide in DeckSpec.model_validate_json(env.deck_row().deck_spec_json).slides
    ]


def _build_three_slides(env) -> None:
    """Turn 1: a build turn that leaves rows and the deck-level spec aligned."""
    env.recorder.configure(slide_count=3)
    env.run()
    assert sorted(env.rows_by_position()) == [0, 1, 2], "turn 1 did not build"
    assert _spec_positions(env) == [0, 1, 2]


# ---------------------------------------------------------------------------
# The premise: a production mutation route really does leave the two disagreeing
# ---------------------------------------------------------------------------


def test_a_delete_leaves_the_deck_level_spec_describing_slides_that_moved(
    graph_turn_env, monkeypatch
):
    """``DELETE /slides/{i}``'s service renumbers rows and not the deck spec.

    Both halves are asserted, because only the pair states the defect: the rows
    close up (so position 1 now holds what was slide 2) while the spec still
    carries three entries whose briefs describe the original three slides.
    """
    env = graph_turn_env
    _build_three_slides(env)

    _service(env, monkeypatch).delete_slide(env.session_id, 1)

    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1]
    assert rows[1].html == builder_html(2), (
        "the surviving slide did not close up into position 1"
    )
    assert _spec_positions(env) == [0, 1, 2], (
        "the deck-level spec was renumbered after all — the guard's premise is "
        "gone and these tests need re-reading, not deleting"
    )


# ---------------------------------------------------------------------------
# The damage the guard exists to stop
# ---------------------------------------------------------------------------


def test_an_edit_turn_after_a_delete_does_not_gain_a_slide_from_the_stale_spec(
    graph_turn_env, monkeypatch
):
    """The destructive case, measured: the deck grew a slide nobody asked for.

    The stale spec still has an entry at position 2, so an edit turn aimed there
    resolves a brief, dispatches a builder and the builder's row write CREATES
    the row — a deleted slide comes back, silently, minutes after the user
    deleted it.

    The no-builder assertion is an absence, so it is paired with
    :func:`test_an_aligned_deck_still_edits_from_the_persisted_spec`, which
    proves this environment dispatches builders off a persisted spec, plus the
    intent and error_state assertions below, which prove the turn ran and
    refused for the stated reason rather than never starting.
    """
    env = graph_turn_env
    _build_three_slides(env)
    _service(env, monkeypatch).delete_slide(env.session_id, 2)

    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={2})
    final = env.run(initial={"architect_message": "polish the third slide"})

    # The turn HAPPENED: the architect ran and answered.
    assert env.recorder.counts("architect") == 1

    # The outcome first, in the finding's own terms.
    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1], "the deck gained a slide from the stale spec"
    assert rows[0].html == builder_html(0)
    assert rows[1].html == builder_html(1)

    # ...because the turn refused, for this reason, before dispatching anything.
    assert final["architect_intent"] == "discuss"
    assert final["error_state"]["code"] == "spec_positions_stale"
    assert final["error_state"]["node"] == "architect"
    assert final["target_positions"] is None
    assert env.wakes(final) == [], "the foreman woke on a refused turn"
    assert env.recorder.counts("builder") == 0
    assert env.recorder.counts("build_reviewer") == 0
    assert env.recorder.counts("deck_reviewer") == 0


def test_an_edit_turn_after_a_middle_delete_leaves_the_surviving_slide_alone(
    graph_turn_env, monkeypatch
):
    """The quieter case, and the worse one: no slide count changes at all.

    Deleting the middle slide moves slide 2's row down to position 1.  The stale
    spec's entry at position 1 still describes the DELETED slide, so an edit turn
    aimed at position 1 rebuilds the human's surviving slide against the wrong
    brief — measured before the guard as row 1's HTML changing from ``Slide 2``
    to ``Slide 1``.  A row-count assertion cannot see this, so the assertion is
    on the row's own HTML.
    """
    env = graph_turn_env
    _build_three_slides(env)
    _service(env, monkeypatch).delete_slide(env.session_id, 1)
    assert env.rows_by_position()[1].html == builder_html(2)  # ENTRY

    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={1})
    final = env.run(initial={"architect_message": "tighten up the second slide"})

    assert env.recorder.counts("architect") == 1

    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1]
    assert rows[1].html == builder_html(2), (
        "the surviving slide was rebuilt against the deleted slide's brief"
    )

    assert final["architect_intent"] == "discuss"
    assert final["error_state"]["code"] == "spec_positions_stale"
    assert env.recorder.positions("builder") == []


def test_an_edit_turn_after_a_duplicate_is_refused_too(graph_turn_env, monkeypatch):
    """The other direction of mismatch: more rows than the spec describes.

    ``POST /slides/{i}/duplicate`` adds a row and no spec entry, so the spec's
    ``{0, 1, 2}`` no longer describes the deck's ``{0, 1, 2, 3}`` — and every
    entry from the duplication point on describes a different slide.  One guard
    covers both directions because it compares the two sets, not their sizes.
    """
    env = graph_turn_env
    _build_three_slides(env)
    _service(env, monkeypatch).duplicate_slide(env.session_id, 0)
    assert sorted(env.rows_by_position()) == [0, 1, 2, 3]  # ENTRY
    assert _spec_positions(env) == [0, 1, 2]

    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={1})
    final = env.run(initial={"architect_message": "redo the second slide"})

    assert sorted(env.rows_by_position()) == [0, 1, 2, 3]
    assert env.rows_by_position()[1].html == builder_html(0), (
        "the duplicated slide was rebuilt against the spec entry for slide 1"
    )
    assert final["architect_intent"] == "discuss"
    assert final["error_state"]["code"] == "spec_positions_stale"
    assert env.recorder.counts("builder") == 0


# ---------------------------------------------------------------------------
# The paired direction: the fallback still works where it is sound
# ---------------------------------------------------------------------------


def test_an_aligned_deck_still_edits_from_the_persisted_spec(
    graph_turn_env, monkeypatch
):
    """Without this the guard could be "refuse every edit" and stay green.

    Same two turns, no mutation in between: the architect emits no ``deck_spec``,
    ``architect_node`` reads the persisted one back, and the turn edits exactly
    its target from the brief that spec carries.  ``monkeypatch`` is requested so
    the two tests differ in one line — the mutation — and nothing else.
    """
    env = graph_turn_env
    _build_three_slides(env)

    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={1})
    final = env.run(initial={"architect_message": "tighten up the second slide"})

    assert final["architect_intent"] == "edit"
    assert final["error_state"] is None
    assert final["target_positions"] == [1]
    assert env.recorder.positions("builder") == [1]
    assert [
        call["payload"]["slide_spec"]["content_brief"]
        for call in env.recorder.calls_for("builder")
    ] == ["brief-1"], "the builder was briefed from something other than the spec"
    assert sorted(env.rows_by_position()) == [0, 1, 2]
