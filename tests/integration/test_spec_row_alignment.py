"""ws4d final review C1 — the persisted spec must still describe THESE rows.

Two representations of the same per-slide brief exist.  ``session_slides.
deck_spec_slide`` travels with its row on every mutation (Task 7), and
``session_slide_decks.deck_spec_json``'s ``slides[].position`` entries are now
renumbered by **every** mutation route.  When this suite was written only insert
renumbered, so delete, duplicate and reorder each left the deck-level spec
describing slides that had moved or gone; the whole-branch review measured all
four routes and the operator then asked for the wide fix.

**This file has been through that change, and the change is the reason it looks
the way it does.**  The three damage tests below used to reach staleness by
calling a real mutation route.  They cannot any more — the routes renumber — so
they inject the mismatch directly, and the premise tests now assert the OPPOSITE
of what they originally asserted: that each route takes the spec with it.  Nothing
was deleted, because the consumer-side guard is not redundant (below).

Why the guard still earns its place now the routes renumber
-----------------------------------------------------------
Renumbering closes the routes; it does not make a stale spec unreachable, and the
guard is the only thing standing between a stale one and a destroyed slide:

* **the spec write is deliberately allowed to fail.**
  ``_rewrite_deck_spec_slides`` logs and returns ``None`` rather than failing the
  mutation the user asked for — the slide change is already committed by then. So
  a spec-write failure leaves exactly the misalignment this guard catches, and
  that path is live in production.
* **an architect-EMITTED spec is not covered by any renumbering.** A model echoing
  back ``current_deck_spec`` can re-materialise a deleted slide, and no route is
  involved.
* **``deck_spec_json`` is a column a human or a migration can edit.**

So: the routes keep the two representations aligned, and the guard is what happens
when something else pulls them apart.  Both halves are tested here.

This suite is about the CONSUMER, because that is where the first fix went.
``architect_node`` falls back to the persisted spec whenever the architect emits
none — the real shape of an edit turn — and both the builder brief and §4.6's
re-review then resolve slides out of it **by position**.  So a stale spec is not
an inert inconsistency; it is a brief handed to a builder for the wrong slide.

Measured on the tree before the guard, by these tests when they still drove real
mutations:

* delete the third slide, then ask to edit "the third slide": a builder is
  dispatched for position 2, which has no row, and **the deck gains a slide
  nobody asked for** (rows went ``[0, 1]`` -> ``[0, 1, 2]``);
* delete the *middle* slide, then ask to edit position 1: the builder is briefed
  with ``brief-1`` — the brief of the slide that used to be there — and
  **overwrites the human's surviving slide** with a rebuild against it
  (row 1's HTML went ``Slide 2`` -> ``Slide 1``).

What the guard can and cannot see, stated so nobody reads more into it
---------------------------------------------------------------------
It compares POSITION SETS, so it catches only mismatches that change the row
set's cardinality.  A **reorder** leaves ``{0, 1, 2}`` on both sides while every
position describes a different slide, and no consumer-side check can see that: the
deck-level spec has no per-slide identity to compare a row against.  Two stronger
predicates were measured and rejected, both because they fire on decks that are
correctly aligned —

* comparing each row's own ``deck_spec_slide.position`` to its row position fires
  after an **insert**, where the row fragments travel with their slides and keep
  their original position field;
* comparing the row's fragment CONTENT to the deck-level entry fires after any
  §4.6 deck-level change, where the spec is deliberately newer than the slides
  that have not been rebuilt against it yet.

**That is why the reorder route had to renumber**: for a reorder, route
renumbering is not the belt-and-braces half, it is the only half there is.
``test_a_reorder_now_permutes_the_deck_level_spec`` and
``test_an_edit_turn_after_a_reorder_briefs_the_slide_that_is_actually_there``
are therefore load-bearing in a way the delete and duplicate cases are not.

Why the premise tests are here
------------------------------
They measure, through the **real** ``ChatService`` on every run, that each route
still renumbers.  Without them the damage tests could quietly become tests of
nothing: their injected mismatch is hand-written, so it would keep working even if
every route regressed to leaving the spec stale, and "the guard refused" would
stay green while production had gone back to producing staleness by itself.  The
premise tests are the half that watches the routes; the damage tests are the half
that watches the guard.
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
    """The real ``ChatService`` the slide routes call, wired to this database.

    ``get_current_username`` is patched here for the same reason ``graph_turn_env``
    already patches ``resolve_display_names``: in CI the Databricks host is a
    non-empty but unreachable value, and the SDK enters a retry loop that sleeps
    rather than raising.  ``delete_slide``, ``duplicate_slide`` and
    ``reorder_slides`` all call ``get_current_username()`` internally to stamp
    authorship; the username is incidental to what this suite tests (spec-position
    alignment), so we stub it at the module boundary rather than reaching the SDK.
    """
    from src.api.services.chat_service import ChatService

    monkeypatch.setattr("src.core.database.get_db_session", _fake_db(env.factory))
    monkeypatch.setattr(
        "src.api.services.chat_service.get_current_username",
        lambda: "test-user",
    )
    return ChatService()


def _spec_positions(env) -> list[int]:
    return [
        slide.position
        for slide in DeckSpec.model_validate_json(env.deck_row().deck_spec_json).slides
    ]


def _spec_briefs(env) -> dict[int, str]:
    """``{position: that entry's own content_brief}``.

    Positions alone cannot express a reorder defect — a reorder preserves the set —
    so every ordering assertion in this file reads the briefs.
    """
    return {
        slide.position: slide.content_brief
        for slide in DeckSpec.model_validate_json(env.deck_row().deck_spec_json).slides
    }


def _make_spec_stale(env, *, entries: int) -> None:
    """Force ``deck_spec_json`` to describe *entries* positions, whatever the rows say.

    The damage tests used to obtain staleness by calling a real mutation route.  The
    routes renumber now, so the mismatch is written directly — which is also the
    honest shape for what remains reachable in production: a swallowed spec-write
    failure, an architect-emitted spec, or a hand-edited column, none of which go
    through a route's renumbering.

    Entries are appended or dropped at the END, so the surviving entries keep the
    briefs they had and an assertion can still tell which slide an entry describes.
    """
    import json

    from src.database.models.session import SessionSlideDeck, UserSession

    db = env.factory()
    try:
        owner = (
            db.query(UserSession)
            .filter(UserSession.session_id == env.session_id)
            .one()
        )
        row = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner.id)
            .one()
        )
        spec = json.loads(row.deck_spec_json)
        slides = spec["slides"]
        while len(slides) > entries:
            slides.pop()
        while len(slides) < entries:
            slides.append(
                {
                    "position": len(slides),
                    "purpose": f"purpose-{len(slides)}",
                    "content_brief": f"brief-{len(slides)}",
                    "assumes": "",
                    "hands_off": "",
                    "data_references": [],
                }
            )
        row.deck_spec_json = json.dumps(spec)
        db.commit()
    finally:
        db.close()


def _build_three_slides(env) -> None:
    """Turn 1: a build turn that leaves rows and the deck-level spec aligned."""
    env.recorder.configure(slide_count=3)
    env.run()
    assert sorted(env.rows_by_position()) == [0, 1, 2], "turn 1 did not build"
    assert _spec_positions(env) == [0, 1, 2]


# ---------------------------------------------------------------------------
# The premise: every mutation route takes the deck-level spec with it
# ---------------------------------------------------------------------------


def test_a_delete_now_renumbers_the_deck_level_spec(graph_turn_env, monkeypatch):
    """``DELETE /slides/{i}``'s service renumbers the rows AND the deck spec.

    This test asserted the opposite when it was written — that the spec was left
    behind — which was C1.  Both halves are still asserted, because only the pair
    states the property: the rows close up (so position 1 now holds what was
    slide 2) and position 1's brief is slide 2's brief, not the deleted slide's.
    """
    env = graph_turn_env
    _build_three_slides(env)

    _service(env, monkeypatch).delete_slide(env.session_id, 1)

    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1]
    assert rows[1].html == builder_html(2), (
        "the surviving slide did not close up into position 1"
    )
    assert _spec_positions(env) == [0, 1], (
        "the deck-level spec was left describing a slide that is gone"
    )
    assert _spec_briefs(env) == {0: "brief-0", 1: "brief-2"}, (
        "position 1 still carries the deleted slide's brief"
    )


def test_a_duplicate_now_gives_the_clone_an_entry_of_its_own(
    graph_turn_env, monkeypatch
):
    """The other direction: a row appears, and an entry appears beside it.

    The clone's entry is a COPY of its source's, not a blank: a duplicate is a copy
    of a slide we already have a brief for.
    """
    env = graph_turn_env
    _build_three_slides(env)

    _service(env, monkeypatch).duplicate_slide(env.session_id, 0)

    assert sorted(env.rows_by_position()) == [0, 1, 2, 3]
    assert _spec_positions(env) == [0, 1, 2, 3]
    assert _spec_briefs(env) == {
        0: "brief-0",
        1: "brief-0",
        2: "brief-1",
        3: "brief-2",
    }, "the briefs did not shift with the slides the duplicate pushed up"


def test_a_reorder_now_permutes_the_deck_level_spec(graph_turn_env, monkeypatch):
    """The case the consumer-side guard structurally cannot cover.

    A reorder preserves the position SET, so ``_persisted_spec_describes_these_rows``
    reads a reordered deck as aligned whatever the entries say — route renumbering is
    not the belt-and-braces half here, it is the only half there is.  The assertion
    is therefore on the briefs; positions alone cannot express the defect at all.
    """
    env = graph_turn_env
    _build_three_slides(env)

    _service(env, monkeypatch).reorder_slides(env.session_id, [1, 2, 0])

    rows = env.rows_by_position()
    assert [rows[p].html for p in sorted(rows)] == [
        builder_html(1),
        builder_html(2),
        builder_html(0),
    ], "the rows themselves did not reorder"
    assert _spec_positions(env) == [0, 1, 2]
    assert _spec_briefs(env) == {0: "brief-1", 1: "brief-2", 2: "brief-0"}, (
        "the briefs stayed put while their slides moved"
    )


def test_a_reorder_that_changes_nothing_leaves_every_brief_alone(
    graph_turn_env, monkeypatch
):
    """The permutation's fixed point (§29, involution).

    A renumber is a permutation and the identity is one of them, so without a
    no-op control a passing reorder assertion cannot distinguish a correct remap
    from a remap that ran twice, or from one that never ran.
    """
    env = graph_turn_env
    _build_three_slides(env)

    _service(env, monkeypatch).reorder_slides(env.session_id, [0, 1, 2])

    assert _spec_briefs(env) == {0: "brief-0", 1: "brief-1", 2: "brief-2"}


# ---------------------------------------------------------------------------
# What renumbering buys: the edit turn the guard used to have to refuse
# ---------------------------------------------------------------------------


def test_an_edit_turn_after_a_delete_now_proceeds(graph_turn_env, monkeypatch):
    """Before route renumbering this turn was REFUSED, and refusing was correct.

    The spec was stale, so the only safe thing was to stop — at the cost of the
    user's edit. Now the spec describes the rows, so the turn runs and edits the
    slide the user meant.
    """
    env = graph_turn_env
    _build_three_slides(env)
    _service(env, monkeypatch).delete_slide(env.session_id, 2)

    env.recorder.reset_observations()
    env.recorder.configure(slide_count=2, edit_target_positions={1})
    final = env.run(initial={"architect_message": "polish the second slide"})

    assert final["architect_intent"] == "edit"
    assert final["error_state"] is None, (
        "the turn was refused on a deck that is now aligned"
    )
    assert sorted(env.rows_by_position()) == [0, 1], (
        "the deck changed size on an edit turn"
    )
    assert env.recorder.positions("builder") == [1]


def test_an_edit_turn_after_a_reorder_briefs_the_slide_that_is_actually_there(
    graph_turn_env, monkeypatch
):
    """The reorder case end to end, and the only test that can see it.

    After ``[1, 2, 0]`` the slide sitting at position 0 is the one that was built
    from ``brief-1``.  An edit turn aimed at position 0 must brief its builder with
    ``brief-1``.  Before route renumbering it was briefed with ``brief-0`` — the
    wrong slide — and the guard could not refuse, because the position sets matched.
    """
    env = graph_turn_env
    _build_three_slides(env)
    _service(env, monkeypatch).reorder_slides(env.session_id, [1, 2, 0])

    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={0})
    final = env.run(initial={"architect_message": "tighten up the first slide"})

    assert final["architect_intent"] == "edit"
    assert final["error_state"] is None
    assert env.recorder.positions("builder") == [0]
    assert [
        call["payload"]["slide_spec"]["content_brief"]
        for call in env.recorder.calls_for("builder")
    ] == ["brief-1"], (
        "the builder was briefed with the brief of the slide that USED to sit here"
    )


# ---------------------------------------------------------------------------
# The damage the guard exists to stop, on a spec made stale by something else
# ---------------------------------------------------------------------------


def test_an_edit_turn_on_an_overlong_spec_does_not_gain_a_slide(
    graph_turn_env, monkeypatch
):
    """The destructive case, measured: the deck grew a slide nobody asked for.

    A spec with an entry at position 2 that the rows do not have resolves a brief,
    dispatches a builder, and the builder's row write CREATES the row — a slide
    appears from nothing.  This used to be reached by deleting a slide; the routes
    renumber now, so the mismatch is injected, which is the shape a swallowed
    spec-write failure leaves behind in production.

    The no-builder assertion is an absence, so it is paired with
    :func:`test_an_aligned_deck_still_edits_from_the_persisted_spec`, which proves
    this environment dispatches builders off a persisted spec, plus the intent and
    error_state assertions below, which prove the turn ran and refused for the
    stated reason rather than never starting.
    """
    env = graph_turn_env
    _build_three_slides(env)
    _service(env, monkeypatch).delete_slide(env.session_id, 2)
    _make_spec_stale(env, entries=3)
    assert sorted(env.rows_by_position()) == [0, 1]  # ENTRY
    assert _spec_positions(env) == [0, 1, 2]  # ENTRY

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


def test_an_edit_turn_on_a_short_spec_is_refused_too(graph_turn_env, monkeypatch):
    """The other direction of mismatch: more rows than the spec describes.

    One guard covers both directions because it compares the two sets, not their
    sizes.  Injected here for the same reason as above: ``duplicate_slide`` no
    longer produces it.
    """
    env = graph_turn_env
    _build_three_slides(env)
    _service(env, monkeypatch).duplicate_slide(env.session_id, 0)
    _make_spec_stale(env, entries=3)
    assert sorted(env.rows_by_position()) == [0, 1, 2, 3]  # ENTRY
    assert _spec_positions(env) == [0, 1, 2]  # ENTRY

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


def test_a_stale_spec_leaves_the_surviving_slide_alone(graph_turn_env, monkeypatch):
    """The quieter case, and the worse one: no slide count changes at all.

    A spec whose entry at position 1 describes a slide that is no longer there means
    an edit turn aimed at position 1 would rebuild the human's surviving slide
    against the wrong brief — measured before the guard as row 1's HTML changing
    from ``Slide 2`` to ``Slide 1``.  A row-count assertion cannot see this, so the
    assertion is on the row's own HTML.
    """
    env = graph_turn_env
    _build_three_slides(env)
    _service(env, monkeypatch).delete_slide(env.session_id, 1)
    _make_spec_stale(env, entries=3)
    assert env.rows_by_position()[1].html == builder_html(2)  # ENTRY

    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={1})
    final = env.run(initial={"architect_message": "tighten up the second slide"})

    assert env.recorder.counts("architect") == 1

    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1]
    assert rows[1].html == builder_html(2), (
        "the surviving slide was rebuilt against the wrong brief"
    )

    assert final["architect_intent"] == "discuss"
    assert final["error_state"]["code"] == "spec_positions_stale"
    assert env.recorder.positions("builder") == []


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
