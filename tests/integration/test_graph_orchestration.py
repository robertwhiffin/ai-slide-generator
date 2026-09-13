"""ws4c C5 — layer-1 orchestration, against the REAL COMPILED GRAPH.

**This is the suite the five-PR split exists to protect.**  Spec §8's point is that
a scheduler test passes in isolation while the shipped topology silently degrades
to "dispatch 15, wait for all 15, dispatch the next 15" — or to dispatching
nothing at all.  ``tests/unit/test_graph_nodes.py`` and
``tests/unit/test_graph_routers.py`` pin the *policy* and stay green either way.
Everything below runs a real turn through ``build_graph()``'s compiled graph,
over a real database, with a real ``SqlAlchemyCheckpointSaver``, and only
``call_skill`` stubbed.

How the harness is registered
-----------------------------
``tests/integration/conftest_stub_skills.py`` is HELPERS-ONLY and is consumed by
plain import — no ``pytest_plugins`` line, because the only fixture
(``graph_turn_env``) lives in ``tests/integration/conftest.py`` where pytest
auto-collects it.  See that module's docstring for the full reasoning.

Parametrisation lives on the recorder
-------------------------------------
``slide_count``, ``fail_positions``, ``slow_positions`` and
``objective_findings_at`` are attributes of ``env.recorder``.  They are NOT
passed through ``invoke()``: the runtime silently drops undeclared state keys,
which is how an earlier draft built three slides in every test — six failing and
two passing *vacuously*.  Nothing here adds a key to ``GraphState``.

What this suite does not cover
------------------------------
Emission of slide releases (``slides_since_cursor``, ``emit_slide_ready``) is
ws4d's; the committed-prefix test asserts the PREFIX, never its emission.
``next_dispatch_batch``'s rule 3 (in-flight subtraction from the cap) has no
reachable layer-1 scenario — see
``test_peak_concurrent_builders_never_exceeds_the_cap_over_40_positions``.
"""

from __future__ import annotations

import pytest

from src.api.services.slide_repository import SlideWriter
from src.services.foreman_service import CAP, releasable_positions
from src.services.graph.state import scoped_vals
from tests.integration.conftest_stub_skills import (
    OBJECTIVE_CRITERION,
    builder_html,
    fixed_html,
)

AUTHOR = "graph-user@example.com"


class _ProcessDied(BaseException):
    """A worker going away mid-turn, modelled as what a node would actually see.

    Deliberately NOT an ``Exception``: every node's failure handler catches
    ``Exception``, which is the point of the non-fatal discipline, so an
    ``Exception`` can no longer leave a turn half-finished.  A SIGTERM'd worker,
    an OOM kill or a redeploy is a ``BaseException`` from inside a node, and that
    is the only thing that still crosses a superstep boundary uncaught.
    """


def _prefix_sequence(snapshots):
    """The committed prefix after each superstep, in order."""
    return [releasable_positions(snapshot) for snapshot in snapshots]


# ---------------------------------------------------------------------------
# 1 — baseline: a three-slide deck builds every position
# ---------------------------------------------------------------------------


def test_a_three_slide_deck_builds_every_position(graph_turn_env):
    """Every covered position is built, reviewed, and committed as a real row.

    The baseline every other assertion here rests on: if this fails, a green
    scheduler unit suite means nothing.  Read off ROWS, not off the recorder, so
    "built" means a row exists with that builder's HTML and a non-NULL author.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=3)

    final = env.run()

    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1, 2]
    assert [rows[p].html for p in (0, 1, 2)] == [builder_html(p) for p in (0, 1, 2)]
    assert {rows[p].modified_by for p in rows} == {AUTHOR}
    assert not any(env.is_placeholder(p) for p in rows)

    assert scoped_vals(final, "landed_positions") == {0, 1, 2}
    assert env.deck_row().slide_count == 3
    assert final["knitted_html"]
    assert env.recorder.counts("builder") == 3
    assert env.recorder.counts("deck_reviewer") == 1


# ---------------------------------------------------------------------------
# 2 — one reviewer invocation per SLIDE, not per batch
# ---------------------------------------------------------------------------


def test_one_build_reviewer_invocation_per_slide_not_per_batch(graph_turn_env):
    """Six builders in ONE batch produce SIX reviewer invocations.

    ``builder -> build_reviewer`` must be a conditional edge that re-fans.  A
    static edge collapses N branches into ONE invocation receiving plain state
    with no payload (measured: 3 builders -> 1 reviewer, ``payload["position"]``
    raising ``KeyError``), which would give one review per *batch*: the
    one-reviewer-writes-one-row invariant and the n-not-3n cost model both break,
    and the per-slide fix path never fires.

    The single-batch assertion is what makes "per slide, not per batch"
    observable: six positions are dispatched in ONE wake, so six reviewer calls
    cannot be explained by six batches.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=6)

    final = env.run()

    assert env.wakes(final)[0] == [0, 1, 2, 3, 4, 5]
    assert env.recorder.counts("build_reviewer") == 6
    assert env.recorder.positions("build_reviewer") == [0, 1, 2, 3, 4, 5]

    # Each reviewer received ITS OWN branch's payload, not a shared state view.
    for call in env.recorder.calls_for("build_reviewer"):
        position = call["payload"]["position"]
        assert call["payload"]["html"] == builder_html(position)


# ---------------------------------------------------------------------------
# 3 — the cap
# ---------------------------------------------------------------------------


def test_peak_concurrent_builders_never_exceeds_the_cap_over_40_positions(
    graph_turn_env,
):
    """40 positions dispatch in batches of at most ``CAP``, and never more run at once.

    **This test does NOT cover ``next_dispatch_batch``'s rule 3** (subtracting
    in-flight positions from the cap).  The superstep barrier plus
    ``foreman_node``'s early returns mean the foreman never wakes with a
    partially-completed batch, so in-flight subtraction has no reachable layer-1
    scenario at all; it is pinned by C2's unit tests and sabotaged there.  Do not
    read this test as that coverage.

    Two complementary assertions, because each alone is weak:

    * the DISPATCH BATCH sizes, read out of ``foreman_wakes`` — exact, ordered,
      and the thing the scheduler's cap actually decides.  Remove the cap and the
      first batch becomes all 40.
    * the runtime-observed ``peak_concurrent``, measured from inside the stub.
      This is additionally bounded by the fan-out executor's width, which is
      ``max_concurrency`` when given and otherwise ``min(32, cpu+4)`` — measured
      at 12 on the dev machine, i.e. BELOW the cap, which would make a
      peak-only assertion unfalsifiable.  So the config passes
      ``max_concurrency=40``, deliberately WIDER than ``CAP``, leaving the
      scheduler's cap as the only bound; the builders sleep so the overlap is
      real rather than a coincidence of timing.
    """
    env = graph_turn_env
    env.recorder.configure(
        slide_count=40, slow_positions=range(40), slow_seconds=0.3
    )

    final = env.run(max_concurrency=40)

    batches = [batch for batch in env.wakes(final) if batch]
    assert batches == [list(range(0, 15)), list(range(15, 30)), list(range(30, 40))]
    assert max(len(batch) for batch in batches) == CAP == 15

    assert env.recorder.peak_concurrent == CAP
    assert sorted(env.recorder.builder_started_at) == list(range(40))


# ---------------------------------------------------------------------------
# 4 — ordering
# ---------------------------------------------------------------------------


def test_the_first_dispatch_batch_of_31_is_positions_0_to_14_ascending(graph_turn_env):
    """The first batch is exactly ``[0..14]`` — ascending, from the bottom.

    Ascending order is load-bearing, not tidiness: ``releasable_positions``
    releases nothing until every lower covered position is committed, so
    dispatching from the top would leave position 0 unstarted while the buffer
    filled and the user saw nothing.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=31)

    final = env.run()

    assert env.wakes(final)[0] == list(range(15))


def test_no_position_outside_the_in_flight_batch_starts_until_that_batch_completes(
    graph_turn_env,
):
    """With position 1 slow, positions 15..30 stay unstarted until batch 1 completes.

    Worded as the plan words it, and the wording matters: positions 2..14 ARE
    dispatched alongside position 1 — they are in the same batch — so
    "no higher position dispatches while position 1 runs" would be FALSE for
    batch 1 and vacuous for every later one.  The claim is about positions
    OUTSIDE the in-flight batch.

    The second assertion is the non-vacuity guard: if the batch did not really
    overlap the slow position, "nothing outside it started" would be trivially
    true of a serial run.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=31, slow_positions={1}, slow_seconds=0.3)

    final = env.run(max_concurrency=31)

    batch_one = env.wakes(final)[0]
    assert batch_one == list(range(15))

    batch_one_completed = max(env.recorder.builder_ended_at[p] for p in batch_one)
    outside = [p for p in range(31) if p not in batch_one]
    assert outside == list(range(15, 31))
    late_starters = {
        p: env.recorder.builder_started_at[p] for p in outside
    }
    assert all(start > batch_one_completed for start in late_starters.values()), (
        "a position outside the in-flight batch started before that batch "
        f"completed: {late_starters} vs batch-1 completion {batch_one_completed}"
    )

    # Non-vacuity: the rest of batch 1 really did run alongside the slow one.
    assert env.recorder.builder_started_at[14] < env.recorder.builder_ended_at[1]


# ---------------------------------------------------------------------------
# 5 — the committed prefix never regresses
# ---------------------------------------------------------------------------


def test_the_committed_prefix_never_regresses_across_foreman_wakes(graph_turn_env):
    """§7.4's no-flapping guarantee, asserted where the prefix is owned.

    ``releasable_positions`` is evaluated on the state after every superstep
    (``stream_mode="values"``), with position 1 slow so the turn spans three
    batches.  Two properties:

    * lengths never decrease, and each value is a prefix of the next — the
      no-flapping guarantee itself, and what this test exists for;
    * three distinct partial prefixes are observed (15, 30, 31), so the sequence
      is not one empty-then-complete jump that would satisfy the above vacuously.

    **Honest limit, measured.**  The contiguity check below is a shape check that
    THIS scenario cannot falsify: every builder succeeds, the barrier lands each
    batch's reviewers in one superstep, so the committed set is never
    discontiguous and a ``releasable_positions`` that returned the committed SET
    instead of the PREFIX keeps this test green (verified by sabotage).  The
    prefix-not-the-set property is pinned by
    ``test_a_position_left_uncommitted_by_a_completed_batch_is_placeheld_by_the_stall_path``,
    where position 1 is outstanding while position 2 is committed.

    The EMISSION of releases is ws4d's (``slides_since_cursor``,
    ``emit_slide_ready``) and is deliberately not asserted here.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=31, slow_positions={1}, slow_seconds=0.1)

    prefixes = _prefix_sequence(env.stream(max_concurrency=31))

    for prefix in prefixes:
        assert prefix == list(range(len(prefix))), (
            f"releasable_positions returned a non-contiguous value: {prefix}"
        )
    for earlier, later in zip(prefixes, prefixes[1:]):
        assert len(earlier) <= len(later), f"the prefix regressed: {prefixes}"
        assert later[: len(earlier)] == earlier

    assert {15, 30, 31} <= {len(prefix) for prefix in prefixes}, (
        f"expected the prefix to grow batch by batch; saw {[len(p) for p in prefixes]}"
    )
    assert prefixes[-1] == list(range(31))


# ---------------------------------------------------------------------------
# 6 — one wake per completed batch
# ---------------------------------------------------------------------------


def test_the_orchestrator_wakes_once_per_completed_batch(graph_turn_env):
    """31 positions -> exactly four wakes: three batches and one final empty one.

    This acknowledges the superstep barrier: there is no "a slot freed, dispatch
    the next" event, so the foreman wakes once per COMPLETED batch.  A future
    change that assumed per-completion wakeups would fail here.

    Every wake carries a falsifiable statement — the batches are exact, disjoint,
    ascending, within the cap, and together cover every position exactly once;
    the single trailing empty wake is the all-committed wake that routes to deck
    review.  ``len(wake) % 1 == 0`` is true of every int and would prove nothing.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=31)

    final = env.run()

    wakes = env.wakes(final)
    assert wakes == [
        list(range(0, 15)),
        list(range(15, 30)),
        [30],
        [],
    ]

    dispatched = [position for wake in wakes for position in wake]
    assert dispatched == sorted(dispatched) == list(range(31))
    assert all(len(wake) <= CAP for wake in wakes)
    assert env.recorder.counts("builder") == 31
    assert env.recorder.counts("deck_reviewer") == 1


# ---------------------------------------------------------------------------
# 7 — the headline invariant: one fix round per position, one deck review
# ---------------------------------------------------------------------------


def test_exactly_one_fixer_invocation_per_position_needing_a_fix(graph_turn_env):
    """Two objective findings -> two fixer calls, two fix reviews, one deck review.

    The headline invariant.  A position is handed to the fixer once and once
    only, and the deck-level review fires exactly once for the turn.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=6, objective_findings_at={0, 1})

    env.run()

    assert env.recorder.positions("fixer") == [0, 1]
    assert env.recorder.counts("fixer") == 2
    assert env.recorder.counts("fix_reviewer") == 2
    assert env.recorder.counts("deck_reviewer") == 1

    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1, 2, 3, 4, 5]
    assert rows[0].html == fixed_html(0)
    assert rows[1].html == fixed_html(1)
    assert rows[2].html == builder_html(2)
    assert env.verdict_for(0)["verdict"] == "fixed"
    assert [f["status"] for f in env.verdict_for(0)["findings"]] == ["fixed"]


def test_deck_review_fires_once_on_a_turn_where_two_builders_fail(graph_turn_env):
    """One deck review on a turn where TWO builders fail — corrections §48.

    A builder branch with nothing to review falls through to ``placeholder``, not
    to ``foreman``.  A router fall-through runs concurrently with its siblings'
    ``Send``s, so a fall-through to the foreman wakes it MID-BATCH: measured on
    this scenario, two paths then reach deck review and the deck reviewer runs
    TWICE — two deck-level writes and two ``deck_reviews`` rows for one turn.  A
    clean turn cannot see it, which is why this is asserted on a failing turn —
    and with **two** failures, so two fall-through branches must still collapse
    to one foreman wake, however the branches split.

    The advisory assertion matches **the deck reviewer's own text**, composed by
    the production ``_advisory_text``.  Counting all ``info`` messages instead
    would be a proxy for deck review rather than deck review itself: it moves
    when any other node surfaces a notice (both failing builders do, below) and —
    measured by review — it did **not** move on a turn where deck review really
    did fire twice.  The recorder count is the real observation; this one pins
    the user-visible surface.
    """
    from src.services.graph.nodes import _advisory_text

    env = graph_turn_env
    env.recorder.configure(slide_count=6, fail_positions={1, 4})

    env.run()

    assert env.recorder.counts("deck_reviewer") == 1
    assert env.recorder.counts("build_reviewer") == 4  # 1 and 4 never built
    assert env.is_placeholder(1) and env.is_placeholder(4)
    assert not any(env.is_placeholder(p) for p in (0, 2, 3, 5))

    messages = env.messages()
    deck_advisories = [
        m for m in messages if m.get("content") == _advisory_text([])
    ]
    assert len(deck_advisories) == 1, (
        "expected exactly one deck-review advisory; got "
        f"{[m.get('content') for m in deck_advisories]}"
    )
    assert all(m.get("message_type") == "info" for m in deck_advisories)

    # The two failed builders' own notices are separate, durable, and outside
    # the count above — the failure paths are symmetric with the reviewer's.
    builder_notices = [
        m for m in messages if "(builder:" in (m.get("content") or "")
    ]
    assert len(builder_notices) == 2


# ---------------------------------------------------------------------------
# 8 — a surviving defect is surfaced, not retried
# ---------------------------------------------------------------------------


def test_a_surviving_defect_becomes_a_surfaced_finding_not_a_retry(graph_turn_env):
    """When the fix does not hold, the ORIGINAL is written back and surfaced.

    The fix reviewer reports the same objective criterion again, so the fixed
    candidate loses: the original HTML is written with verdict ``surfaced`` and
    the finding still ``open``.  There is no second fixer invocation — nothing in
    this graph retries, and ``retry_count`` does not exist.
    """
    env = graph_turn_env
    env.recorder.configure(
        slide_count=3, objective_findings_at={0}, surviving_defect_at={0}
    )

    final = env.run()

    assert env.recorder.counts("fixer") == 1
    assert env.recorder.counts("fix_reviewer") == 1
    assert env.recorder.counts("deck_reviewer") == 1

    rows = env.rows_by_position()
    assert rows[0].html == builder_html(0), "the surviving defect must not ship"
    verdict = env.verdict_for(0)
    assert verdict["verdict"] == "surfaced"
    assert [f["criterion"] for f in verdict["findings"]] == [OBJECTIVE_CRITERION]
    assert [f["status"] for f in verdict["findings"]] == ["open"]

    surfaced = [f for f in final["findings"] if f.criterion == OBJECTIVE_CRITERION]
    assert surfaced and all(f.status == "open" for f in surfaced)


# ---------------------------------------------------------------------------
# 9 — a terminal failure is placeheld and release proceeds past it
# ---------------------------------------------------------------------------


def test_a_terminal_failure_is_placeheld_and_release_proceeds_past_it(graph_turn_env):
    """§I — a placeholder counts as committed, so the deck still reaches review.

    ``len(landed) == len(spec.slides)`` would be the wrong predicate: one
    terminal failure would freeze the prefix, deck review would never fire and
    the turn would never end.

    One failure mid-deck, so the placeholder sits INSIDE the prefix and the
    release has to proceed through it — distinct from the two-failure §48
    scenario above, which is about how many times the deck reviewer runs.  The
    last assertion pins the durable surface: a stream event is not enough,
    because the emitter is ``None`` on the sweeper path and in this test.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=3, fail_positions={1})

    final = env.run()

    assert scoped_vals(final, "placeheld_positions") == {1}
    assert scoped_vals(final, "landed_positions") == {0, 2}
    assert env.is_placeholder(1)

    # Release proceeds PAST the placeholder — the prefix is complete.
    assert releasable_positions(final) == [0, 1, 2]
    assert env.recorder.counts("deck_reviewer") == 1

    deck = env.deck_row()
    assert deck.slide_count == 3
    assert deck.html_content, "the post-commit deck-level write did not happen"

    notices = [
        m
        for m in env.messages()
        if "Slide 1" in (m.get("content") or "") and "(builder:" in m["content"]
    ]
    assert len(notices) == 1, (
        "a terminal builder failure must leave a durable notice, not only a "
        f"stream event; info messages were {[m.get('content') for m in env.messages()]}"
    )


# ---------------------------------------------------------------------------
# 10 — turn 2 BUILDS
# ---------------------------------------------------------------------------


def test_turn_2_dispatches_builders_rather_than_going_straight_to_deck_review(
    graph_turn_env,
):
    """Turn 2 dispatched three builders — stated as DISPATCH, never as a landed set.

    Turn-scoped state is what makes this true: the checkpointer carries all of
    turn 1's values forward, and ``scoped_vals`` discards them because the turn
    discriminator changed.  Without it turn 2 reads turn 1's
    ``landed_positions``, ``next_dispatch_batch`` returns ``[]``,
    ``all_positions_committed`` is true and the turn goes straight to deck review
    having built NOTHING.

    "Turn 2's landed set equals {0,1,2}" would pass BECAUSE of that bug — turn
    1's set is exactly what it would be reading.  So the assertions are about
    what turn 2 DISPATCHED and INVOKED.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=3)

    env.run()
    turn_one = env.last_turn_id
    assert env.recorder.counts("builder") == 3

    # The state turn 2 must discard was really carried forward: the checkpointer
    # holds turn 1's complete turn, under turn 1's id.  Without this the test
    # would be green against a graph compiled with no saver at all — i.e. it
    # would prove nothing about turn scoping, only that a fresh state builds.
    carried = env.graph.get_state(
        {"configurable": {"thread_id": env.session_id}}
    ).values
    assert carried["turn_id"] == turn_one
    assert scoped_vals(carried, "landed_positions") == {0, 1, 2}

    env.recorder.reset_observations()
    second = env.run()

    assert second["turn_id"] != turn_one

    assert env.recorder.counts("builder") == 3, (
        "turn 2 dispatched no builders — it went straight to deck review on "
        "turn 1's inherited state"
    )
    assert env.recorder.positions("builder") == [0, 1, 2]
    assert env.wakes(second)[0] == [0, 1, 2]
    assert env.recorder.counts("build_reviewer") == 3
    assert env.recorder.counts("deck_reviewer") == 1


# ---------------------------------------------------------------------------
# 11 — the two paths C4 asked C5 to close
# ---------------------------------------------------------------------------


def test_a_position_left_uncommitted_by_a_completed_batch_is_placeheld_by_the_stall_path(
    graph_turn_env, monkeypatch
):
    """``stalled_positions`` limb 1, driven through the compiled graph.

    Reaching limb 1 needs a position that a COMPLETED batch left uncommitted.
    The shape that produces it in production is the one ``builder_node``'s own
    handler documents: the builder fails AND its ``commit_placeholder`` also
    fails ("the foreman will reconcile it"), so the branch returns ``{}`` and the
    position is dispatched-but-neither-landed-nor-placeheld.  The stub therefore
    fails only the builder's own placeholder attempt, which the two call sites'
    distinct ``error_message`` values make possible — a transient failure, not a
    permanent one, because a permanently failing writer would loop the
    placeholder path to the recursion limit.

    (Measured, and worth recording: a ``build_reviewer`` that RAISES does not
    produce this shape — the exception propagates and the whole turn dies with
    ``RuntimeError``.  So the reviewer-failure route C4 suggested is not
    reachable as a stall; this is.)

    The wake sequence is what proves limb 1 did the work rather than the re-fan
    fall-through: the placeholder lands only after an EMPTY wake was recorded,
    which is the state ``stalled_positions``' limb-1 exclusion set is erased in.
    The prefix observation is the second half — while position 1 is outstanding
    the prefix is ``[0]`` even though position 2 is committed, which is a prefix
    and not the committed set.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=3, fail_positions={1})

    real_commit_placeholder = SlideWriter.commit_placeholder

    def only_the_foreman_may_placehold(self, session_id, position, error_message=""):
        # placeholder_node passes this message; builder_node passes the
        # exception's type name.
        if error_message != "Slide generation did not complete":
            raise RuntimeError("transient DB failure on the builder's placeholder")
        return real_commit_placeholder(
            self, session_id, position, error_message=error_message
        )

    monkeypatch.setattr(
        SlideWriter, "commit_placeholder", only_the_foreman_may_placehold
    )

    snapshots = env.stream()
    final = snapshots[-1]

    assert env.wakes(final) == [[0, 1, 2], [], []], (
        "the placeholder must be reached from an EMPTY wake (limb 1), not from "
        "the re-fan fall-through in the reviewers' superstep"
    )
    assert scoped_vals(final, "placeheld_positions") == {1}
    assert env.is_placeholder(1)
    assert final.get("error_state") is None, (
        "the turn ended with unreconciled work instead of placeholding it"
    )
    assert releasable_positions(final) == [0, 1, 2]
    assert env.recorder.counts("deck_reviewer") == 1

    prefixes = _prefix_sequence(snapshots)
    assert [0] in prefixes, (
        "expected the prefix to sit at [0] while position 1 was outstanding and "
        f"position 2 committed; saw {prefixes}"
    )
    assert prefixes[-1] == [0, 1, 2]


def test_an_edit_turn_dispatches_only_its_target_positions(graph_turn_env):
    """An EDIT turn covers ``target_positions``, not the whole ``deck_spec``.

    Recorded by review as the suite's one coverage hole: **no compiled-graph test
    exercised an edit turn at all**, and 15 of 15 passed with
    ``_covered_positions``' precedence INVERTED (``deck_spec`` winning over
    ``target_positions``).  Every function in ``foreman_service`` derives its
    coverage from that one helper, so under the inversion an edit of one slide
    re-dispatches the whole deck — N model calls and N overwritten rows for a
    one-slide edit — and nothing in this suite noticed.

    The unit suite could not reach it either: its ``_state`` fixture sets
    ``target_positions`` and ``deck_spec`` in an ``elif``, so the two keys can
    never both be set, and the multi-target case is exactly the case where they
    both are.  Here they both are for real — the architect stub returns
    ``intent="edit"`` with no ``deck_spec``, so ``architect_node`` reads turn 1's
    persisted spec back and commits it to state alongside ``target_positions``.

    Stated as DISPATCH and INVOKED, never as a landed set: turn 1 landed
    ``{0, 1, 2}`` and an inverted turn 2 would land the same three, so a
    landed-set assertion would pass under the very bug this test exists for.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=3)

    env.run()
    assert env.recorder.counts("builder") == 3
    turn_one_htmls = {p: row.html for p, row in env.rows_by_position().items()}

    env.recorder.reset_observations()
    env.recorder.configure(slide_count=3, edit_target_positions={1})

    final = env.run()

    # The turn really is an edit over a spec it did not author: both keys are set.
    assert final["architect_intent"] == "edit"
    assert final["target_positions"] == [1]
    assert final["deck_spec"] is not None
    assert [s.position for s in final["deck_spec"].slides] == [0, 1, 2]

    assert env.wakes(final)[0] == [1], (
        "the edit turn dispatched a batch other than its target positions"
    )
    assert env.recorder.positions("builder") == [1]
    assert env.recorder.counts("builder") == 1, (
        "the edit turn re-built slides it was not asked to touch"
    )
    assert env.recorder.counts("build_reviewer") == 1
    assert scoped_vals(final, "landed_positions") == {1}
    assert env.recorder.counts("deck_reviewer") == 1

    # The untouched slides are still the deck, and the deck still knows it has
    # three of them: coverage narrows the TURN, never the deck.
    rows = env.rows_by_position()
    assert sorted(rows) == [0, 1, 2]
    assert rows[0].html == turn_one_htmls[0]
    assert rows[2].html == turn_one_htmls[2]
    assert env.deck_row().slide_count == 3


def test_the_checkpointer_serde_round_trips_deck_spec_and_finding_as_themselves():
    """Ruling C-25 / corrections §55 — the tripwire for the two unregistered types.

    ``GraphState`` declares two pydantic types that cross the checkpointer:
    ``deck_spec: Optional[DeckSpec]`` and ``findings: Annotated[list[Finding],
    operator.add]``.  langgraph's ``JsonPlusSerializer`` carries both today, and
    logs ``Deserializing unregistered type … This will be blocked in a future
    version`` once per type per process while it does.

    **The failure that is coming is not an exception.**  Measured with
    ``LANGGRAPH_STRICT_MSGPACK=true``: the refusal is only LOGGED and the value
    comes back as a plain ``dict``.  So nothing raises at the seam — instead
    ``_covered_positions``' ``spec.slides`` and every other attribute access on a
    spec or a finding breaks somewhere downstream, with nothing pointing at
    serialisation.  This assertion is the early warning: under strict mode both
    types come back as ``dict`` and it goes red at the seam itself.

    No graph run, no database, no fixture — the serde is the whole subject, which
    is why the tripwire can be this cheap.  Constructing the saver deliberately
    builds no engine (that is its documented contract), so this touches nothing.

    Restructuring the two channels into JSON-native shapes is ws4d's work
    (corrections §55); until then, this is what fails first.
    """
    from src.core.checkpointer import SqlAlchemyCheckpointSaver
    from src.domain.deck_spec import DeckSpec
    from src.domain.finding import Finding
    from tests.integration.conftest_stub_skills import (
        make_deck_spec,
        objective_finding,
    )

    serde = SqlAlchemyCheckpointSaver().serde
    channel_values = {
        "deck_spec": make_deck_spec(2),
        "findings": [objective_finding(0)],
    }

    restored = serde.loads_typed(serde.dumps_typed(channel_values))

    spec = restored["deck_spec"]
    assert type(spec) is DeckSpec, (
        f"deck_spec came back as {type(spec).__name__}, not DeckSpec — the "
        "checkpoint serialisation of an unregistered type has changed.  Every "
        "attribute access on the spec (spec.slides in _covered_positions, "
        "spec.slide_at in build_branch_payload) now breaks downstream instead of "
        "here.  See corrections §55 / Ruling C-25."
    )
    assert [slide.position for slide in spec.slides] == [0, 1]

    finding = restored["findings"][0]
    assert type(finding) is Finding, (
        f"findings came back as [{type(finding).__name__}], not [Finding] — same "
        "cause as above; every f.criterion / f.objective read breaks downstream."
    )
    assert finding.criterion == OBJECTIVE_CRITERION


def test_a_resumed_turn_reconciles_an_in_flight_fix_instead_of_re_fixing_it(
    graph_turn_env, monkeypatch
):
    """The ``in_flight`` marker, driven through a REAL crash and a real resume.

    ``in_flight`` is what makes "exactly one fix round per position" true rather
    than aspirational, and within one turn nothing can reproduce it: the clean
    wiring serialises ``fixer -> fix_reviewer -> foreman``, and the fix reviewer
    tombstones its entry on every path including its own exception.  So this
    drives the case the marker actually exists for.

    Turn 1 dies mid-fix — the process goes away in the fix reviewer, after the
    fixer has already marked the entry ``in_flight`` and the superstep was
    checkpointed.  The same turn is then re-entered on the same thread, so
    ``scoped_vals`` reads that entry back (a FRESH turn id would discard it by
    design, which is why ``invoke_graph``'s per-turn id makes this reachable only
    for a caller resuming the same turn).  ``_reconcile_stale_fixes`` must then
    land the ORIGINAL slide, tombstone the entry and let the turn finish —
    costing NO model call, which is what keeps "one fix round" true.

    **Why a ``BaseException`` and not a ``RuntimeError``.**  This used to fail the
    fix reviewer's row write with a ``RuntimeError``, which killed the turn — the
    F1a defect: rows committed, ``slide_count = 0``, nothing in chat.  That is now
    guarded, so an ordinary write failure placeholds the position and the turn
    finishes, and it can no longer leave a fix ``in_flight``.  What still can is
    the process going away between the fixer's superstep landing and the fix
    reviewer finishing — a SIGTERM'd worker, an OOM kill, a redeploy — and from
    inside a node that looks like a ``BaseException``, which no ``except
    Exception`` handler catches.  So the scenario is unchanged and the mechanism
    is now the one that actually produces it in production.

    Without ``in_flight`` the resumed fixer sees a fresh candidate and re-fixes
    the position: ``counts("fixer") == 0`` is the assertion that catches it.
    """
    env = graph_turn_env
    env.recorder.configure(slide_count=3, objective_findings_at={0})

    real_write_slide = SlideWriter.write_slide

    def die_on_the_fixed_row(self, session_id, position, html, **kwargs):
        if html == fixed_html(position):
            raise _ProcessDied("the worker died mid-fix")
        return real_write_slide(
            self, session_id, position, html=html, **kwargs
        )

    monkeypatch.setattr(SlideWriter, "write_slide", die_on_the_fixed_row)

    turn_id = "turn-that-dies-mid-fix"
    with pytest.raises(_ProcessDied, match="died mid-fix"):
        env.run(turn_id=turn_id)

    # The checkpoint really holds an in-flight fix for this turn.
    checkpointed = env.graph.get_state(
        {"configurable": {"thread_id": env.session_id}}
    ).values
    assert checkpointed["turn_id"] == turn_id
    stalled_entry = scoped_vals(checkpointed, "fix_map")[0]
    assert stalled_entry["in_flight"] is True
    assert scoped_vals(checkpointed, "landed_positions") == {1, 2}

    # Resume the SAME turn with a working writer.
    monkeypatch.setattr(SlideWriter, "write_slide", real_write_slide)
    env.recorder.reset_observations()

    final = env.run(turn_id=turn_id)

    assert env.recorder.counts("fixer") == 0, (
        "the resumed turn re-dispatched the fix: the in_flight marker was not "
        "honoured, so 'exactly one fix round per position' is false"
    )
    assert env.recorder.counts("fix_reviewer") == 0
    assert scoped_vals(final, "fix_map")[0] is None, "the entry was not tombstoned"
    assert scoped_vals(final, "landed_positions") == {0, 1, 2}
    assert env.rows_by_position()[0].html == builder_html(0)
    assert env.verdict_for(0)["verdict"] == "surfaced"
    assert env.recorder.counts("deck_reviewer") == 1
