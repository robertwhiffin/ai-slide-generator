"""#319 — the polling transport serves the running turn's stage, WHILE it runs.

Polling is the production transport (``isPollingMode()`` is true on every
Databricks App), and it cannot see a single graph event:
``job_queue.process_chat_request`` keeps only ``COMPLETE`` and ``SESSION_TITLE``
off the stream and ``GET /chat/poll`` reads only the database.  So the stage the
placeholder shows has exactly one route to a production user: the tracker's
write to the turn's ``chat_requests`` row, read back by ``poll_chat``.

A poll taken AFTER the turn proves nothing about that route — a finished request
serves ``turn_progress: null`` by design, and a stage that only appears once the
deck is done is the static placeholder with extra steps.  So these tests poll
from INSIDE the turn: every model call the graph makes for the architect, a
build reviewer, a fixer and the deck reviewer first calls the real ``poll_chat``
for this turn's request, on the graph's own thread, and records what a polling
client would have been shown at that instant.  The turn itself is the real async
job (``process_chat_request``) over the compiled graph, the real ``invoke_graph``
and the real nodes; only the model calls are stubbed (``async_turn_env``).

Each stage is asserted at the moment it is TRUE rather than as a sequence of
labels, because up to three slides run at once here and their stages interleave
freely: a slide's reviewer can only be running while that slide is in
``reviewing``, its fixer only while it is in ``fixing``, and the deck reviewer
only once every slide is ``done``.  Those hold under every interleaving.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

import pytest

from src.api.services.session_manager import get_session_manager
from src.services.graph.event_emitter import (
    get_chat_request_id,
    set_chat_request_id,
    set_event_emitter,
)
from src.services.graph.progress import turn_progress_var
from tests.integration.test_architect_reply_is_persisted import (  # noqa: F401
    async_turn_env,  # fixture
)

#: The model calls a poll is taken inside.  Each runs at a moment the turn's
#: stage is pinned by the topology (see the module docstring).
_SPIED = frozenset({"architect", "build_reviewer", "fixer", "deck_reviewer"})

#: Every ``message_type`` a turn may persist into the transcript.  A progress
#: snapshot stored as a message would arrive with some other type (or as one of
#: these carrying the snapshot's JSON, which the content check catches).
_TRANSCRIPT_TYPES = {"user_query", "llm_response", "info"}

BUILD_REPLY = "Three slides on puffins, starting with where they breed."


@pytest.fixture(autouse=True)
def _no_turn_state_leaks():
    """Clear every turn ContextVar this suite touches, before AND after each test."""
    turn_progress_var.set(None)
    set_event_emitter(None)
    set_chat_request_id(None)
    yield
    turn_progress_var.set(None)
    set_event_emitter(None)
    set_chat_request_id(None)


class _TurnSpy:
    """An ``AgentRuntime`` that polls the running turn before each spied model call.

    The poll runs on the graph's own thread (the architect's, or a slide
    pipeline's Pregel worker), against this turn's request id as the graph sees
    it, so what is recorded is exactly what a client polling at that instant
    would have been served.  A poll that raises is recorded and re-raised: the
    nodes catch model-call failures, so swallowing it here would let a broken
    poll pass as "no observation".
    """

    def __init__(self, env, inner) -> None:
        self._env = env
        self._inner = inner
        self._lock = threading.Lock()
        self.observations: List[Dict[str, Any]] = []
        self.errors: List[str] = []

    def run(self, name, graph_release_id, payload, assembly_context):
        if name in _SPIED:
            request_id = get_chat_request_id()
            try:
                body = self._env.poll(request_id)
            except BaseException as exc:  # recorded, then re-raised
                with self._lock:
                    self.errors.append(f"{name}: poll({request_id!r}) raised {exc!r}")
                raise
            with self._lock:
                self.observations.append(
                    {
                        "name": name,
                        "position": (
                            payload.get("position") if isinstance(payload, dict) else None
                        ),
                        "status": body["status"],
                        "turn_progress": body["turn_progress"],
                        "events": body["events"],
                    }
                )
        return self._inner.run(name, graph_release_id, payload, assembly_context)

    def seen(self, name: str, position: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                o
                for o in self.observations
                if o["name"] == name and (position is None or o["position"] == position)
            ]


def _spy_on_turn(env, monkeypatch) -> _TurnSpy:
    """Wrap the fixture's runtime so every spied call polls the turn first."""
    import src.services.graph.nodes as nodes

    inner = nodes.get_agent_runtime()
    spy = _TurnSpy(env, inner)
    monkeypatch.setattr("src.services.graph.nodes.get_agent_runtime", lambda: spy)
    return spy


def _one(observations: List[Dict[str, Any]], what: str) -> Dict[str, Any]:
    assert len(observations) == 1, (
        f"expected exactly one {what} call, got {len(observations)}: the scenario "
        "changed, so the stage observed during it is not evidence"
    )
    return observations[0]


def _served(observation: Dict[str, Any], what: str) -> Dict[str, Any]:
    """The stage a polling client was shown during *what*; fails if it was shown none."""
    assert observation["status"] == "running", (
        f"during {what} the request was {observation['status']!r}, not running: "
        "the poll was not taken inside the turn"
    )
    progress = observation["turn_progress"]
    assert progress is not None, (
        f"a client polling during {what} was served no stage: the running turn's "
        "progress never reached its chat request row"
    )
    return progress


def _build_with_one_fix(env, monkeypatch) -> tuple:
    """A three-slide build turn whose slide 1 is flagged and fixed; returns (rid, spy)."""
    spy = _spy_on_turn(env, monkeypatch)
    env.architect_builds(BUILD_REPLY)
    env.recorder.configure(slide_count=3, objective_findings_at={1})
    request_id = env.run()
    assert spy.errors == [], f"a mid-turn poll failed: {spy.errors!r}"
    return request_id, spy


def test_a_polling_client_sees_each_stage_while_the_turn_runs(
    async_turn_env, monkeypatch
):
    env = async_turn_env
    _request_id, spy = _build_with_one_fix(env, monkeypatch)

    # -- the architect: planning ----------------------------------------------
    architect = _served(_one(spy.seen("architect"), "architect"), "the architect call")
    assert architect["phase"] == "planning", (
        f"while the architect ran, the poll served phase {architect['phase']!r}"
    )

    # -- each slide's build review: that slide is being reviewed ----------------
    reviews = spy.seen("build_reviewer")
    assert sorted(o["position"] for o in reviews) == [0, 1, 2], (
        f"build reviewers ran for {sorted(o['position'] for o in reviews)}, not "
        "[0, 1, 2]: the scenario changed"
    )
    review_seqs = []
    for observation in reviews:
        position = observation["position"]
        progress = _served(observation, f"build_reviewer({position})")
        assert progress["phase"] == "building", (
            f"while slide {position} was being reviewed the poll served phase "
            f"{progress['phase']!r}"
        )
        assert position in progress["slides"]["reviewing"], (
            f"while slide {position} was being reviewed the poll did not list it "
            f"as reviewing: {progress['slides']!r}"
        )
        assert progress["slides"]["total"] == 3, (
            f"the poll's total was {progress['slides']['total']} on a 3-slide turn"
        )
        review_seqs.append(progress["seq"])

    # -- the flagged slide's fix: that slide is being fixed --------------------
    fix_observation = _one(spy.seen("fixer", 1), "fixer(1)")
    fix = _served(fix_observation, "fixer(1)")
    assert fix["phase"] == "building"
    assert 1 in fix["slides"]["fixing"], (
        f"while slide 1 was being fixed the poll did not list it as fixing: "
        f"{fix['slides']!r}"
    )
    assert spy.seen("fixer") == [fix_observation], (
        "a slide with no finding was fixed: the scenario changed"
    )

    # -- the deck review: every slide done --------------------------------------
    deck = _served(_one(spy.seen("deck_reviewer"), "deck_reviewer"), "the deck review")
    assert deck["phase"] == "reviewing_deck", (
        f"during the deck review the poll served phase {deck['phase']!r}"
    )
    assert deck["slides"]["done"] == [0, 1, 2], (
        f"during the deck review not every slide was done: {deck['slides']!r}"
    )

    # -- causality: what a client saw moved forward with the turn --------------
    mid_turn = review_seqs + [fix["seq"]]
    assert architect["seq"] < min(mid_turn), (
        f"the architect's stage (seq {architect['seq']}) is not older than every "
        f"slide stage (seqs {sorted(mid_turn)})"
    )
    assert max(mid_turn) < deck["seq"], (
        f"a slide stage (seqs {sorted(mid_turn)}) is not older than the deck "
        f"review's (seq {deck['seq']})"
    )


def test_a_finished_turn_serves_no_stage_but_kept_the_last_one(
    async_turn_env, monkeypatch
):
    env = async_turn_env
    request_id, _spy = _build_with_one_fix(env, monkeypatch)

    body = env.poll(request_id)
    stored = get_session_manager().get_chat_request(request_id)

    assert body["status"] == "completed"
    assert body["turn_progress"] is None, (
        "a finished turn still serves a stage, so the placeholder would show "
        f"stale work after the deck has landed: {body['turn_progress']!r}"
    )
    assert stored["turn_progress"] is not None, (
        "the row holds no stage at all, so the null above is a lost write, not "
        "the poll's projection"
    )
    assert stored["turn_progress"]["phase"] == "reviewing_deck", (
        f"the row's last stage is {stored['turn_progress']!r}, not the deck review"
    )


def test_stage_progress_never_enters_the_transcript(async_turn_env, monkeypatch):
    env = async_turn_env
    request_id, spy = _build_with_one_fix(env, monkeypatch)

    polls = [o["events"] for o in spy.observations] + [env.poll(request_id)["events"]]
    assert len(polls) >= 7, "the mid-turn polls were not taken; nothing is checked"
    for events in polls:
        assert all(event.get("type") != "turn_progress" for event in events), (
            f"a turn_progress event reached the poll's chat events: {events!r}"
        )
        assert not any('"seq"' in (event.get("content") or "") for event in events), (
            f"a progress snapshot reached the poll's chat events as text: {events!r}"
        )

    messages = env.messages()
    assert BUILD_REPLY in [m["content"] for m in messages], (
        "the architect's reply is not in the transcript, so an empty transcript "
        "would pass the checks below"
    )
    assert {m["message_type"] for m in messages} <= _TRANSCRIPT_TYPES, (
        "the turn persisted a message of an unexpected type: "
        f"{sorted({m['message_type'] for m in messages})!r}"
    )
    assert not any('"seq"' in (m["content"] or "") for m in messages), (
        "a progress snapshot was persisted into the transcript"
    )


def test_a_discuss_turn_only_ever_shows_planning(async_turn_env, monkeypatch):
    env = async_turn_env
    spy = _spy_on_turn(env, monkeypatch)

    request_id = env.run()

    assert spy.errors == [], f"a mid-turn poll failed: {spy.errors!r}"
    assert [o["name"] for o in spy.observations] == ["architect"], (
        f"a discuss turn reached {[o['name'] for o in spy.observations]!r}: the "
        "scenario changed"
    )
    architect = _served(spy.observations[0], "the architect call")
    assert architect["phase"] == "planning"

    stored = get_session_manager().get_chat_request(request_id)["turn_progress"]
    assert stored is not None, "a discuss turn stored no stage at all"
    assert stored["phase"] == "planning", (
        f"a discuss turn ended on phase {stored['phase']!r}"
    )
    assert stored["seq"] == 1, (
        f"a discuss turn recorded {stored['seq']} stage changes; planning is the "
        f"only one it has: {stored!r}"
    )
