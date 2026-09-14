"""A sweeper turn re-describes the deck; it never rebuilds it.

`run_arc_review` runs the **full** graph, and `_INTENT_ROUTES` maps both `"build"`
and `"edit"` to `"foreman"`.  So an architect returning either on a sweeper tick
dispatches builders whose reviewers overwrite the slide rows a human just
hand-edited — with no emitter, so no SSE stream and nobody watching it happen.
A post-hoc check cannot help: `invoke_graph` is synchronous and the rows land
before it returns.

`describe_only` is the fix, and this file is where it is proved against the real
compiled graph, the real checkpointer and real row writes rather than at the
router's own edge (that is `tests/unit/test_graph_routers.py`).

The trap this file exists for
----------------------------
Turn-2 state **accumulates** — a measured runtime fact, and the entire reason
ws4c built the `turn_scoped_*` reducer family.  A plain single-writer bool set on
a sweeper turn would still read `True` on the user's *next* turn on that thread,
**silently barring every subsequent build for that deck.**  A flag added to close
one destructive path would have opened a worse and quieter one.  So
`test_the_sweeper_turn_does_not_bar_the_users_NEXT_turn_on_the_same_thread` runs
three turns on ONE `thread_id` through ONE checkpointer, and the third must
dispatch builders.  A test that used a fresh thread per turn would pass with an
unscoped flag and prove nothing — the single-direction trap again.

Harness
-------
`graph_turn_env` (tests/integration/conftest.py) — the compiled graph over a real
database and a real `SqlAlchemyCheckpointSaver`, with only `call_skill` stubbed.
Two additions it does not know about:

* `src.services.graph.builder._compiled_graph` is pointed at the env's graph, so
  `invoke_graph` and therefore `run_arc_review` run for real and only the graph
  they fetch is the env's.  Precedent: tests/integration/test_graph_mode_turn.py.
* `src.services.spec_sync.get_db_session` is patched.  The env patches four
  `get_db_session` references and this is not one of them, so `mark_dirty` and
  `clear_marker` would otherwise reach whatever database the environment points
  at (the harness gap Task 4 recorded).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.database.models.session import SessionSlide, UserSession
from src.services.graph.builder import invoke_graph
from src.services.spec_sync import claim_due_marker, mark_dirty, run_arc_review
from tests.integration.conftest import _make_fake_db

_AUTHOR = "hand-editor@example.com"
_HAND_EDITED = "<div class='slide'><h1>A HUMAN WROTE THIS BY HAND</h1></div>"


@pytest.fixture
def sweeper_env(graph_turn_env, monkeypatch):
    """`graph_turn_env`, with `invoke_graph` and `spec_sync` pointed at it."""
    monkeypatch.setattr(
        "src.services.graph.builder._compiled_graph", graph_turn_env.graph
    )
    fake = _make_fake_db(graph_turn_env.factory)
    monkeypatch.setattr("src.services.spec_sync.get_db_session", fake)
    return graph_turn_env


def _builder_calls(recorder) -> list:
    """Every builder invocation so far. `recorder.calls` entries are dicts."""
    return recorder.calls_for("builder")


def _hand_edit_slide_zero(env) -> None:
    """What the WYSIWYG route's row write leaves behind, without the route."""
    db = env.factory()
    try:
        owner = (
            db.query(UserSession)
            .filter(UserSession.session_id == env.session_id)
            .one()
        )
        db.execute(
            text(
                "UPDATE session_slides SET html = :html, modified_by = :by "
                "WHERE session_id = :sid AND position = 0"
            ),
            {"html": _HAND_EDITED, "by": _AUTHOR, "sid": owner.id},
        )
        db.commit()
    finally:
        db.close()


def _slide_html(env, position: int) -> str:
    db = env.factory()
    try:
        owner = (
            db.query(UserSession)
            .filter(UserSession.session_id == env.session_id)
            .one()
        )
        return (
            db.query(SessionSlide)
            .filter(
                SessionSlide.session_id == owner.id,
                SessionSlide.position == position,
            )
            .one()
            .html
        )
    finally:
        db.close()


def _age_the_marker(env, seconds: int = 400) -> None:
    """Push spec_dirty_at back so the claim's debounce window has passed."""
    db = env.factory()
    try:
        db.execute(
            text(
                "UPDATE session_slide_decks "
                "SET spec_dirty_at = datetime('now', :delta)"
            ),
            {"delta": f"-{seconds} seconds"},
        )
        db.commit()
    finally:
        db.close()


class TestASweeperTurnDoesNotRebuildTheDeck:
    def test_the_hand_edit_survives_the_arc_review(self, sweeper_env):
        """The property, stated as the user would state it.

        Turn 1 builds a three-slide deck.  A human then hand-edits slide 0, which
        is what sets the marker.  The sweeper's arc review runs the FULL graph
        with an architect returning `intent="build"` — the destructive case — and
        the human's HTML must still be there afterwards.
        """
        env = sweeper_env
        env.recorder.slide_count = 3

        env.run()  # turn 1: a normal user build
        assert len(_builder_calls(env.recorder)) == 3, (
            "turn 1 built nothing, so nothing below is testing an overwrite"
        )
        assert mark_dirty(env.session_id, _AUTHOR) is True
        _hand_edit_slide_zero(env)
        assert _slide_html(env, 0) == _HAND_EDITED

        builders_before = len(_builder_calls(env.recorder))
        assert run_arc_review(env.session_id, _AUTHOR) is True

        assert _slide_html(env, 0) == _HAND_EDITED, (
            "the arc review REBUILT the slide the human hand-edited; their work "
            "is gone and nobody was watching it happen"
        )
        assert len(_builder_calls(env.recorder)) == builders_before, (
            "the sweeper turn dispatched builders; every slide row on this deck "
            "is now whatever the model produced"
        )

    def test_the_architect_still_ran_and_re_persisted_the_spec(self, sweeper_env):
        """The entry assertion for every absence above.

        "No builders ran" is also true of a turn that did nothing at all, which
        would make the sweeper pointless rather than safe.  The turn must reach
        the architect and persist its re-described spec — that IS the arc review.
        """
        env = sweeper_env
        env.recorder.slide_count = 2
        env.run()
        mark_dirty(env.session_id, _AUTHOR)

        architect_before = env.recorder.counts("architect")
        assert run_arc_review(env.session_id, _AUTHOR) is True

        architect_after = env.recorder.counts("architect")
        assert architect_after == architect_before + 1, (
            "the sweeper turn never reached the architect, so no arc was "
            "re-described and the flag is over-blocking"
        )

        deck = env.deck_row()
        assert deck.deck_spec_json, "the re-described spec was not persisted"
        assert deck.modified_by == _AUTHOR, (
            f"the deck-level write recorded {deck.modified_by!r}; the sweeper's "
            "principal did not reach modified_by"
        )

    def test_an_EDIT_intent_is_blocked_too_and_the_same_config_builds_normally(
        self, sweeper_env
    ):
        """`_INTENT_ROUTES` sends "edit" to the foreman as well as "build".

        Paired: the SAME recorder configuration is then run as a normal turn and
        must dispatch builders, so this cannot pass on a recorder that never
        edits anything.
        """
        env = sweeper_env
        env.recorder.slide_count = 3
        env.run()
        mark_dirty(env.session_id, _AUTHOR)
        _hand_edit_slide_zero(env)

        env.recorder.edit_target_positions = {0}
        builders_before = len(_builder_calls(env.recorder))
        assert run_arc_review(env.session_id, _AUTHOR) is True

        assert len(_builder_calls(env.recorder)) == builders_before, (
            "an edit intent reached the foreman on a describe-only turn"
        )
        assert _slide_html(env, 0) == _HAND_EDITED

        # The paired half: the same edit configuration on a normal user turn.
        invoke_graph(env.session_id, {"architect_message": "edit slide 0 please"})
        assert len(_builder_calls(env.recorder)) > builders_before, (
            "the same edit configuration builds nothing on a NORMAL turn either, "
            "so the assertion above says nothing about the flag"
        )


class TestTheFlagDoesNotOutliveItsTurn:
    """THE tests. Three turns, one thread_id, one checkpointer.

    Turn state accumulates across a thread — turn 2 passing a fresh empty value
    still saw turn 1's, measured — so the flag the sweeper turn wrote is
    physically still in the channel when the user's next turn resumes.  If it
    were not turn-scoped, that turn would route to END and this deck would
    silently stop building, for ever, with nothing to explain it.  A version of
    these tests using a fresh thread per turn would prove nothing.

    TWO turn-3 variants, and the split is load-bearing rather than tidy.
    `invoke_graph` writes the flag on EVERY invocation, `False` included, so on
    that path a stale unscoped value would be overwritten anyway and the
    turn-scoping never tested — measured by sabotage, which is how this gap was
    found.  The scoping is what saves a turn that writes NO `describe_only` key
    at all, and there are two of those in the tree today: any caller that
    invokes the compiled graph directly rather than through `invoke_graph` (every
    test in test_graph_orchestration.py, and `env.run()` here), and a turn
    resumed from a checkpoint with no fresh input.  So variant 1 is the one that
    reddens when the flag is made a plain unscoped bool.
    """

    def _two_turns_then(self, env):
        """Turn 1 (user build) then turn 2 (the sweeper), on the same thread."""
        env.recorder.slide_count = 2
        env.run()
        assert len(_builder_calls(env.recorder)) == 2, "turn 1 built nothing"

        mark_dirty(env.session_id, _AUTHOR)
        after_turn_1 = len(_builder_calls(env.recorder))
        assert run_arc_review(env.session_id, _AUTHOR) is True
        assert len(_builder_calls(env.recorder)) == after_turn_1, (
            "the sweeper turn built, so turn 3's count cannot be attributed"
        )
        env.recorder.slide_count = 2
        return after_turn_1

    def test_a_turn_3_that_writes_NO_FLAG_still_dispatches_builders(
        self, sweeper_env
    ):
        """The variant that tests the turn-scoping itself.

        `env.run()` seeds no `describe_only` key, exactly like every direct
        `graph.invoke` caller in the tree, so the ONLY thing standing between the
        sweeper's `True` and a permanently unbuildable deck is `scoped_vals`
        discarding a wrapper from another turn.
        """
        env = sweeper_env
        after_turn_1 = self._two_turns_then(env)

        env.run()

        assert len(_builder_calls(env.recorder)) > after_turn_1, (
            "a turn after the sweeper's dispatched NO builders — the "
            "describe-only flag outlived its turn and this deck has silently "
            "stopped building, with nothing to explain it"
        )

    def test_a_turn_3_through_invoke_graph_also_dispatches_builders(
        self, sweeper_env
    ):
        """The user's real path, belt and braces.

        Here the flag is also overwritten by `invoke_graph`'s own `False` write,
        so this passes for two independent reasons.  It is the path a user
        actually takes, so it is worth pinning — but the sibling above is the one
        that fails when the scoping is removed.
        """
        env = sweeper_env
        after_turn_1 = self._two_turns_then(env)

        final = invoke_graph(
            env.session_id, {"architect_message": "now add the closing slide"}
        )

        assert len(_builder_calls(env.recorder)) > after_turn_1, (
            "the user's turn after a sweeper turn dispatched no builders"
        )
        # Kept in its own test below rather than here: a shape assertion that
        # raises would mask the behavioural one above.
        assert final["turn_id"]

    def test_the_flag_in_the_channel_after_a_user_turn_is_that_turns_own(
        self, sweeper_env
    ):
        """The structural half, deliberately separated.

        When this lived at the end of the behavioural test it was the assertion
        that caught an unscoped-flag sabotage, by raising TypeError — masking the
        fact that the behavioural assertion above it had passed. A shape check
        and a behaviour check must not share a test.
        """
        env = sweeper_env
        self._two_turns_then(env)

        final = invoke_graph(env.session_id, {"architect_message": "one more"})

        assert isinstance(final["describe_only"], dict), (
            f"describe_only is {type(final['describe_only']).__name__}, not a "
            "scoped wrapper; it cannot be discarded on a later turn"
        )
        assert final["describe_only"]["turn"] == final["turn_id"]
        assert final["describe_only"]["vals"] is False


class TestTheMarkerIsStillDequeued:
    def test_a_describe_only_review_clears_the_marker(self, sweeper_env):
        """Blocking the foreman must not block the queue: if the marker survived
        a successful review, this deck would be re-reviewed every window."""
        env = sweeper_env
        env.recorder.slide_count = 2
        env.run()
        mark_dirty(env.session_id, _AUTHOR)
        _age_the_marker(env)

        claimed = claim_due_marker(__import__("datetime").datetime.utcnow())
        assert claimed == (env.session_id, _AUTHOR), (
            f"the claim returned {claimed!r}; the rest of this test is untested"
        )

        assert run_arc_review(*claimed) is True

        deck = env.deck_row()
        assert deck.spec_dirty_at is None
        assert deck.spec_dirty_by is None
        assert deck.spec_dirty_claimed_at is None
