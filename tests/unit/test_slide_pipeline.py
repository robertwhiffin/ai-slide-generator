"""The per-slide pipeline: no slide waits for a sibling, and fixes run in parallel.

Measured on a real 10-slide deck before this change (local, real Gateway models):
9 of 10 slides were flagged, their fixes ran ONE AT A TIME through
``foreman -> fixer -> fix_reviewer -> foreman`` and took 186s of a 308s turn, and
every slide waited for the slowest builder and then the slowest reviewer before
anything moved on.

Each test here is built so that it FAILS under either of those two behaviours,
not merely so that it passes under the new one:

* the concurrency tests hold every fixer (or slide 1's builder) on a barrier that
  can only be released by work a serialising or superstep-barriered topology
  cannot have started yet, so the old graph times the barrier out and the
  slide falls back to its unfixed (or placeheld) form;
* the counting tests pair every "exactly once" with an entry assertion, so a
  graph that never fixes anything cannot satisfy them.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict

import pytest

from src.api.services.slide_repository import is_placeholder_record
from src.domain.finding import VERDICT_KEY, DeckReviewOutput
from src.services.foreman_service import CAP
from src.services.graph import nodes
from src.services.graph.builder import build_graph
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest_graph import (  # noqa: F401 — fixtures
    architect_build,
    builder_out,
    finding,
    fixer_out,
    graph_env_threadsafe,
    make_spec,
    review_out,
)

#: Long enough that a concurrent topology never trips it, short enough that the
#: old serial topology fails the suite in seconds rather than minutes.
BARRIER_TIMEOUT_S = 5


def _wire(env, positions, *, flagged=()):
    env.skills.set("architect", architect_build(make_spec(positions)))
    env.skills.set("builder", builder_out)
    env.skills.set(
        "build_reviewer",
        lambda payload: review_out(
            payload["position"],
            [finding("overflow", slide_index=payload["position"])]
            if payload["position"] in flagged
            else [],
        ),
    )
    env.skills.set("fixer", fixer_out)
    env.skills.set("fix_reviewer", lambda payload: review_out(payload["position"]))
    env.skills.set("deck_reviewer", DeckReviewOutput(findings=[]))


def _run(env) -> Dict[str, Any]:
    graph = build_graph(checkpointer=False)
    return graph.invoke(env.state(turn_id="turn-pipeline"), {"max_concurrency": CAP})


def _rows(env) -> Dict[int, Any]:
    return {r.position: r for r in env.rows()}


class TestFixesRunInParallel:
    def test_fixes_for_different_slides_are_in_flight_at_the_same_time(
        self, graph_env_threadsafe
    ):
        """Three flagged slides; each fixer waits until all three have STARTED.

        Serialised fixes reach the barrier one at a time, it times out, the fixer
        raises, and ``fixer_node`` lands the ORIGINAL — so the rows below would
        read ``slide N`` instead of ``fixed N``.
        """
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2), flagged=(0, 1, 2))
        barrier = threading.Barrier(3, timeout=BARRIER_TIMEOUT_S)

        def fixer(payload):
            barrier.wait()
            return fixer_out(payload)

        env.skills.set("fixer", fixer)

        _run(env)

        rows = _rows(env)
        assert sorted(rows) == [0, 1, 2]
        assert {p: rows[p].html for p in rows} == {
            p: f"<div class='slide'>fixed {p}</div>" for p in (0, 1, 2)
        }, "a fixer timed out on the barrier: fixes did not run concurrently"

    def test_exactly_one_fix_round_per_flagged_slide_and_deck_review_once(
        self, graph_env_threadsafe
    ):
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2, 3), flagged=(0, 2, 3))

        _run(env)

        fixed = sorted(c["payload"]["position"] for c in env.skills.calls_for("fixer"))
        reviewed = sorted(
            c["payload"]["position"] for c in env.skills.calls_for("fix_reviewer")
        )
        assert fixed == [0, 2, 3]
        assert reviewed == [0, 2, 3]
        assert len(env.skills.calls_for("deck_reviewer")) == 1
        rows = _rows(env)
        assert rows[1].html == "<div class='slide'>slide 1</div>"
        assert rows[3].html == "<div class='slide'>fixed 3</div>"


class TestNoSlideWaitsForASibling:
    def test_slide_zero_is_fixed_and_landed_while_slide_one_is_still_building(
        self, graph_env_threadsafe
    ):
        """Slide 1's builder cannot return until slide 0's FIX REVIEW has run.

        Under any superstep-barriered topology slide 0's reviewer cannot start
        until every builder in the batch has returned, so slide 1's builder times
        out, raises and is placeheld.  Only a pipeline that carries slide 0 from
        build through fix review on its own satisfies it.
        """
        env = graph_env_threadsafe
        _wire(env, (0, 1), flagged=(0,))
        slide_zero_fix_reviewed = threading.Event()

        def builder(payload):
            if payload["position"] == 1:
                if not slide_zero_fix_reviewed.wait(BARRIER_TIMEOUT_S):
                    raise RuntimeError("slide 1 waited on slide 0's barrier")
            return builder_out(payload)

        def fix_reviewer(payload):
            slide_zero_fix_reviewed.set()
            return review_out(payload["position"])

        env.skills.set("builder", builder)
        env.skills.set("fix_reviewer", fix_reviewer)

        _run(env)

        rows = _rows(env)
        assert rows[0].html == "<div class='slide'>fixed 0</div>"
        assert not is_placeholder_record(json.loads(rows[1].verification_record)), (
            "slide 1 was placeheld: its builder waited on slide 0's superstep"
        )
        assert rows[1].html == "<div class='slide'>slide 1</div>"


class TestTheDeckReviewerStillRunsOnce:
    def test_a_failed_builder_beside_fixed_slides_reviews_the_deck_once(
        self, graph_env_threadsafe
    ):
        """The measured 'deck reviewer ran twice' shape: a branch with nothing to
        review finishing beside branches that are still reviewing and fixing."""
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2), flagged=(0, 2))

        def builder(payload):
            if payload["position"] == 1:
                raise RuntimeError("model exploded")
            return builder_out(payload)

        env.skills.set("builder", builder)

        _run(env)

        rows = _rows(env)
        assert sorted(rows) == [0, 1, 2]
        assert is_placeholder_record(json.loads(rows[1].verification_record))
        assert sorted(c["payload"]["position"] for c in env.skills.calls_for("fixer")) == [0, 2]
        assert len(env.skills.calls_for("deck_reviewer")) == 1
        assert env.deck_row().slide_count == 3


class TestFanInKeysUnderParallelFixes:
    def test_two_fix_reviews_failing_to_deliver_in_one_superstep_do_not_kill_the_turn(
        self, graph_env_threadsafe, monkeypatch
    ):
        """``fix_reviewer_node``'s delivery-failure path writes ``error_state``,
        which has no reducer.  Two of those in one superstep raise
        ``InvalidUpdateError`` and kill the turn unless the pipeline keeps the
        key branch-local."""
        env = graph_env_threadsafe
        _wire(env, (0, 1, 2), flagged=(0, 1))
        real_write = nodes._write_reviewed_row

        def write(**kwargs):
            if kwargs["html"].startswith("<div class='slide'>fixed"):
                raise RuntimeError("row write failed")
            return real_write(**kwargs)

        monkeypatch.setattr(nodes, "_write_reviewed_row", write)

        _run(env)

        rows = _rows(env)
        assert sorted(rows) == [0, 1, 2]
        assert is_placeholder_record(json.loads(rows[0].verification_record))
        assert is_placeholder_record(json.loads(rows[1].verification_record))
        assert len(env.skills.calls_for("fix_reviewer")) == 2
        assert len(env.skills.calls_for("deck_reviewer")) == 1


class TestTheDraftIsVisibleBeforeReview:
    def test_the_builder_s_html_is_committed_before_its_review_runs(
        self, graph_env_threadsafe
    ):
        """Product decision (2026-10-12): show the builder's draft, then replace it.

        The reviewer reads the committed row at the moment it is called; the
        draft must already be there.  The final row is still the reviewed one.
        """
        env = graph_env_threadsafe
        _wire(env, (0, 1), flagged=(1,))
        seen_at_review: Dict[int, str] = {}

        def reviewer(payload):
            rows = _rows(env)
            row = rows.get(payload["position"])
            seen_at_review[payload["position"]] = row.html if row else None
            flagged = payload["position"] == 1
            return review_out(
                payload["position"],
                [finding("overflow", slide_index=payload["position"])] if flagged else [],
            )

        env.skills.set("build_reviewer", reviewer)

        _run(env)

        assert seen_at_review == {
            0: "<div class='slide'>slide 0</div>",
            1: "<div class='slide'>slide 1</div>",
        }
        rows = _rows(env)
        assert rows[1].html == "<div class='slide'>fixed 1</div>"
        verdicts = {
            p: json.loads(rows[p].verification_record)[compute_slide_hash(rows[p].html)]
            for p in rows
        }
        assert verdicts[0][VERDICT_KEY]["verdict"] == "clean"
        assert verdicts[1][VERDICT_KEY]["verdict"] == "fixed"

    def test_a_draft_row_claims_no_verdict(self, graph_env_threadsafe):
        """A draft is unreviewed; its row must not read as clean to the UI or to
        ``get_verification_map``."""
        env = graph_env_threadsafe
        _wire(env, (0,))
        record_at_review: Dict[str, Any] = {}

        def reviewer(payload):
            row = _rows(env)[0]
            record_at_review["record"] = row.verification_record
            return review_out(0)

        env.skills.set("build_reviewer", reviewer)

        _run(env)

        assert "record" in record_at_review, "the reviewer never ran"
        assert record_at_review["record"] in (None, "", "{}", "null")

    def test_a_draft_never_overwrites_a_committed_slide(self, graph_env_threadsafe):
        """On an edit or rebuild the position already holds the user's slide.  A
        turn that then dies on a persisted runtime failure must leave that slide,
        not an unreviewed draft, so the draft only fills an empty position."""
        env = graph_env_threadsafe
        _wire(env, (0, 1))
        env.seed_slides(["<div class='slide'>existing 0</div>"])
        seen_at_review: Dict[int, Any] = {}

        def reviewer(payload):
            row = _rows(env).get(payload["position"])
            seen_at_review[payload["position"]] = row.html if row else None
            return review_out(payload["position"])

        env.skills.set("build_reviewer", reviewer)

        _run(env)

        assert seen_at_review == {
            0: "<div class='slide'>existing 0</div>",
            1: "<div class='slide'>slide 1</div>",
        }
        assert _rows(env)[0].html == "<div class='slide'>slide 0</div>"
