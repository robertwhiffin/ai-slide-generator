"""The architect's reply has to survive the turn, or nobody hears it.

The defect this suite exists for
--------------------------------
``architect_node`` emitted its reply as a ``StreamEvent`` and persisted nothing.
Two consequences, both measured on a live deployment:

1. **The polling transport delivered silence.**
   ``job_queue.process_chat_request`` handles only ``COMPLETE`` and
   ``SESSION_TITLE`` and discards every other event, and ``poll_chat`` reads
   assistant text out of **persisted rows** (``get_messages_for_request``).  So a
   graph turn that completed cleanly, called the model and emitted its reply put
   nothing at all in the chat, and the poll cursor never moved.
2. **The architect could not remember its own turns.**
   ``_conversation`` builds the architect's history from persisted rows and
   admits an assistant turn only when ``message_type`` is in ``_AI_TYPES``.  With
   nothing persisted, the architect saw every user message and none of its own
   replies — it could ask a clarifying question and, next turn, have no idea it
   had asked.

Why the two guards are shaped the way they are
----------------------------------------------
The first drives the **whole async transport**: a ``submit_chat_async``-shaped
job through ``process_chat_request``, then ``poll_chat``.  Every other test in
the repo asserts on *yielded events* (which the polling path throws away) or on
the slide cursor, so this seam had no coverage — which is how the defect reached
a deployment.

The second is a pure function of persisted rows and is the half that matters
more: it fails if the reply is persisted with any ``message_type`` outside
``_AI_TYPES``.  ``info`` — the type the failure-notice helper uses — would leave
the architect deaf while still showing the user the text, so guard 1 alone
cannot tell the two choices apart.  This one can, and that is its job.

The turn is a ``discuss`` turn, and that is deliberate: ``_INTENT_ROUTES`` maps
``discuss`` to ``END``, so ``architect_node`` is the only node that runs and the
only node that can write an assistant row.  Nothing else can mask the
assertions, and the reply text is a distinctive sentence rather than anything a
default could produce — the stub architect's own default message is
``"Building N slide(s)."``, the *same string* ``foreman_node`` emits, which is
exactly the collision a real assertion must not be exposed to.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.api.services.chat_service import ChatService
from src.domain.skill_io import ArchitectOutput
from src.services.agent_runtime import AgentAssemblyContext
from src.services.graph.nodes import _advisory_text
from tests.integration.conftest_stub_skills import CallableAgentRuntime

#: The architect's reply.  A sentence no default, no stub and no other node
#: produces, so its presence in a transcript can only have come from the
#: architect's own reply being persisted.
REPLY = (
    "Before I build anything: is this deck for the board, or for the "
    "engineering team?"
)

#: The user's message.  Carries the phrase because the async route resolves the
#: engine from the deck's earliest user row.
USER_MESSAGE = "USE AGENT MODE draft me something about puffins"

#: What ``_advisory_text([])`` composes — the one line a completed build turn owes
#: the user.  Asserted as a CONSTANT read off the production helper rather than
#: retyped, so a reworded advisory fails here instead of silently passing.
CLEAN_ADVISORY = _advisory_text([])

AUTHOR = "reply-persist@example.com"


class _MonolithReached(AssertionError):
    """Raised if a graph-mode turn ever reaches the monolith's agent build."""


class _AsyncTurnEnv:
    """The async chat transport over the fixture's compiled graph.

    Surface:
      session_id          — the session, and the checkpointer's thread_id
      recorder            — the SkillRecorder, for reading skill payloads back
      submit(message)     — what ``POST /chat/async`` does: lock, request row,
                            persisted user row, and the job payload
      run(message)        — submit(), then ``process_chat_request``; returns the
                            request_id
      poll(request_id)    — ``poll_chat``, returned as its response dict
      assistant_rows()    — every persisted ``role='assistant'`` message
    """

    def __init__(self, env, knobs: Dict[str, Any]):
        self._env = env
        self._knobs = knobs

    @property
    def session_id(self) -> str:
        return self._env.session_id

    def architect_builds(self, reply: str) -> None:
        """Stop forcing ``discuss``: keep the recorder's build output, swap the prose.

        The recorder's own architect message is ``"Building N slide(s)."`` — the
        *same string* ``foreman_node`` emits — so a build-turn assertion made
        against it could not tell the architect's row from the foreman's event.
        Only ``message`` is replaced; ``intent``, ``deck_spec`` and every other
        field stay the recorder's, so the turn really builds.
        """
        self._knobs["discuss"] = False
        self._knobs["reply"] = reply

    @property
    def recorder(self):
        return self._env.recorder

    # -- driving ------------------------------------------------------------

    def submit(self, message: str = USER_MESSAGE) -> tuple:
        """Mirror ``submit_chat_async``: lock, request row, user row, payload.

        The user row carries the ``request_id``, exactly as the route persists
        it — that column is what ``get_messages_for_request`` filters on, so a
        harness that omitted it would make the poll blind for reasons that have
        nothing to do with the architect.
        """
        from src.api.services.session_manager import get_session_manager

        manager = get_session_manager()
        assert manager.acquire_session_lock(self.session_id) is True
        request_id = manager.create_chat_request(self.session_id, AUTHOR)
        is_first_message = (
            manager.get_session(self.session_id).get("message_count", 0) == 0
        )
        manager.add_message(
            session_id=self.session_id,
            role="user",
            content=message,
            message_type="user_query",
            request_id=request_id,
        )
        payload: Dict[str, Any] = {
            "session_id": self.session_id,
            "message": message,
            "slide_context": None,
            "is_first_message": is_first_message,
            "image_ids": None,
            "engine_mode": "graph",
        }
        return request_id, payload

    def run(self, message: str = USER_MESSAGE) -> str:
        """One whole async turn, through the real job function."""
        from src.api.services.job_queue import process_chat_request

        request_id, payload = self.submit(message)
        asyncio.run(process_chat_request(request_id, payload))
        return request_id

    def poll(self, request_id: str, after_message_id: int = 0) -> Dict[str, Any]:
        from src.api.routes.chat import poll_chat

        return asyncio.run(
            poll_chat(request_id, after_message_id=after_message_id, slide_cursor=0)
        )

    # -- reading ------------------------------------------------------------

    def messages(self) -> List[dict]:
        return self._env.messages()

    def assistant_rows(self) -> List[dict]:
        return [m for m in self.messages() if m.get("role") == "assistant"]

    def architect_payloads(self) -> List[dict]:
        return [call["payload"] for call in self.recorder.calls_for("architect")]

    def is_placeholder(self, position: int) -> bool:
        return self._env.is_placeholder(position)


@pytest.fixture
def async_turn_env(graph_turn_env, monkeypatch):
    """``graph_turn_env`` reachable through the async chat transport.

    Everything redirected here is redirected for the same reason
    ``test_graph_mode_turn``'s fixture redirects it — the compiled graph is the
    fixture's, the databases are the fixture's, and nothing reaches a workspace.
    The monolith's agent build is booby-trapped so a turn that took the wrong
    engine dies loudly instead of quietly passing.

    ``_check_deck_permission_for_session`` is neutralised because ``poll_chat``
    resolves a real deck permission and this suite is not about authz — that
    gate has its own tests.
    """
    env = graph_turn_env

    monkeypatch.setattr("src.services.graph.builder.get_graph", lambda: env.graph)

    @contextlib.contextmanager
    def fake_get_db_session():
        db = env.factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr("src.core.database.get_db_session", fake_get_db_session)
    monkeypatch.setattr(
        "src.core.settings_db.get_settings", lambda: MagicMock(profile_id=None)
    )
    monkeypatch.setattr(
        "src.api.services.chat_service.generate_session_title",
        lambda message, model: "Puffins",
    )
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: MagicMock()
    )
    monkeypatch.setattr("databricks_langchain.ChatDatabricks", MagicMock())
    monkeypatch.setattr(
        "src.api.routes.chat._check_deck_permission_for_session", MagicMock()
    )

    def explode(*args, **kwargs):
        raise _MonolithReached(
            "a graph-mode turn reached _build_agent_for_session: the graph "
            "branch is placed too late, or was not taken at all"
        )

    monkeypatch.setattr(ChatService, "_build_agent_for_session", explode)

    # By default the architect DISCUSSES: one node runs, one reply, no build, so
    # nothing but the architect can write an assistant row and no assertion can be
    # masked.  `architect_builds()` switches to the recorder's real build output
    # with only the prose replaced.  The recorder is called first either way, so
    # its payloads and its other skill handlers stay observable.
    recorder = env.recorder
    knobs: Dict[str, Any] = {"discuss": True, "reply": REPLY}

    def stub_architect(name: str, payload: dict, design_system_active: bool):
        out = recorder.run(
            name,
            payload,
            AgentAssemblyContext(design_system_active),
        ).output
        if name != "architect":
            return out
        if knobs["discuss"]:
            return ArchitectOutput(intent="discuss", message=knobs["reply"])
        return out.model_copy(update={"message": knobs["reply"]})

    runtime = CallableAgentRuntime(stub_architect)
    monkeypatch.setattr(
        "src.services.graph.nodes.get_agent_runtime",
        lambda: runtime,
    )

    from src.core.user_context import set_current_user

    set_current_user(AUTHOR)
    try:
        yield _AsyncTurnEnv(env, knobs)
    finally:
        set_current_user(None)


# ===========================================================================
# Guard 1 — a polling client receives the architect's reply
# ===========================================================================


def test_a_polling_client_receives_the_architects_reply(async_turn_env):
    """The seam nothing else covers: job -> persisted row -> poll response.

    ``process_chat_request`` discards the ``ASSISTANT`` stream event, so the
    persisted row is the reply's ONLY route to a polling client.  Asserting on
    the poll response's ``events`` — not on yielded events, and not on the row —
    is what makes this a test of the transport rather than of the writer.
    """
    env = async_turn_env
    request_id = env.run()

    body = env.poll(request_id)

    assert body["status"] == "completed"
    assistant_events = [
        event for event in body["events"] if event["type"] == "assistant"
    ]
    assert REPLY in [event["content"] for event in assistant_events], (
        "the architect's reply never reached the polling transport; the poll "
        f"delivered {[e['content'] for e in assistant_events]!r}"
    )


def test_the_poll_cursor_moves_past_the_reply(async_turn_env):
    """``last_message_id`` advances, so a client polling incrementally sees it.

    The live symptom was a cursor that never moved: a client handing back
    ``after_message_id`` got the same empty answer forever.  Asserting the reply
    arrives on a SECOND poll taken from the first poll's cursor is what pins
    that, because a row the first poll returned cannot satisfy it.
    """
    env = async_turn_env
    request_id = env.run()

    first = env.poll(request_id)
    user_row_id = min(m["id"] for m in env.messages())
    second = env.poll(request_id, after_message_id=user_row_id)

    assert first["last_message_id"] > user_row_id, (
        "the poll cursor never moved past the user's own message"
    )
    assert REPLY in [event["content"] for event in second["events"]]


# ===========================================================================
# Guard 2 — the architect remembers its own turn
# ===========================================================================


def test_the_reply_enters_the_replayable_conversation(async_turn_env):
    """``_conversation`` is the architect's memory, and it admits only ``_AI_TYPES``.

    A reply persisted as ``info`` would satisfy guard 1 and fail here, which is
    the whole point of having this guard as well: ``info`` is deliberately
    excluded from replay so the deck reviewer's advisory never reaches the
    architect as prose, and reusing it for the reply would leave the architect
    deaf to itself.
    """
    from src.services.graph.nodes import _conversation

    env = async_turn_env
    env.run()

    turns = _conversation(env.session_id)

    assert {"role": "assistant", "content": REPLY} in turns, (
        "the architect's own reply is not in its replayable conversation; it "
        f"sees {turns!r}"
    )


def test_turn_two_sees_the_reply_it_gave_on_turn_one(async_turn_env):
    """The consumer, not just the helper: the turn-2 architect PAYLOAD carries it.

    ``_conversation`` feeds ``payload["conversation"]``, so this is the
    assertion that the architect actually receives its own prior turn — the
    clarifying-question case, where forgetting means asking twice.
    """
    env = async_turn_env
    env.run()
    env.run("the board, please")

    payloads = env.architect_payloads()
    assert len(payloads) == 2, f"expected one architect call per turn, got {len(payloads)}"
    turn_two = payloads[1]["conversation"]

    assert {"role": "assistant", "content": REPLY} in turn_two, (
        "turn 2's architect payload does not carry turn 1's reply; it carries "
        f"{turn_two!r}"
    )


# ===========================================================================
# The sweeper — a machine turn with no human waiting
# ===========================================================================


def test_a_describe_only_sweeper_turn_writes_no_assistant_row(async_turn_env):
    """A describe-only tick must not put words in a human's transcript.

    ``spec_sync.run_arc_review`` invokes the graph with ``describe_only=True``,
    no emitter and nobody watching; its reply is addressed to nobody.  Persisting
    it would both pollute the transcript a human reads and — worse — enter
    ``_conversation``, so the architect's next human turn would find a reply it
    never gave to a question nobody asked.
    """
    from src.services.graph.builder import invoke_graph
    from src.services.spec_sync import ARC_REVIEW_MESSAGE

    env = async_turn_env

    invoke_graph(
        env.session_id,
        {"architect_message": ARC_REVIEW_MESSAGE},
        principal="the-human-who-edited@example.com",
        describe_only=True,
    )

    assert env.architect_payloads(), "the sweeper turn never reached the architect"
    assert env.assistant_rows() == [], (
        "a describe-only sweeper turn wrote into a human's transcript: "
        f"{env.assistant_rows()!r}"
    )


# ===========================================================================
# The rest of the graph's chat rows: written, but until now untagged
# ===========================================================================
#
# `GET /chat/poll` reads a turn's chat text through `get_messages_for_request`,
# which filters `SessionMessage.request_id == request_id`.  Every row the graph
# wrote carried NULL there, so the deck-review advisory and the placeholder
# notices were durable and invisible to the polling client — the same silence as
# the architect's reply, arriving by a different route.  These pin the tag.


BUILD_REPLY = "Right — three slides, opening with the colony census."


def test_a_build_turn_delivers_both_the_reply_and_the_deck_review_advisory(
    async_turn_env,
):
    """A completed build turn owes the user two lines; polling used to get neither.

    Also the only test here that runs the architect on its real ``build`` output,
    so it covers the reply persisting on the branch that fans builders out rather
    than only on the branch that ends the turn.
    """
    env = async_turn_env
    env.recorder.configure(slide_count=2)
    env.architect_builds(BUILD_REPLY)

    request_id = env.run()
    body = env.poll(request_id)
    delivered = [event["content"] for event in body["events"]]

    assert body["status"] == "completed"
    assert BUILD_REPLY in delivered, (
        f"the architect's reply is missing from a build turn's poll: {delivered!r}"
    )
    assert CLEAN_ADVISORY in delivered, (
        f"the deck-review advisory is missing from the poll: {delivered!r}"
    )


def test_a_placeholder_notice_from_a_fanned_node_reaches_the_polling_client(
    async_turn_env,
):
    """The request id has to survive the ``Send`` fan-out, not just the turn.

    ``_surface_notice`` is reached from ``builder_node``, which LangGraph runs on
    a Pregel worker thread through ``copy_context().run(...)``.  A tag read from a
    ``ContextVar`` set before ``invoke`` is only visible there because of that
    copy, so this asserts the mechanism rather than assuming it — and the notice
    is the only durable surface a silently-failed slide has.
    """
    env = async_turn_env
    env.recorder.configure(slide_count=2, fail_positions={1})
    env.architect_builds(BUILD_REPLY)

    request_id = env.run()
    delivered = [event["content"] for event in env.poll(request_id)["events"]]

    assert env.is_placeholder(1), "position 1 was not placeheld; the scenario changed"
    notices = [text for text in delivered if "left as a placeholder" in text]
    assert notices, (
        "the placeholder notice never reached the polling client: "
        f"{delivered!r}"
    )
    assert "Slide 1" in notices[0]


# ===========================================================================
# The analyst — audible to the user, deliberately deaf to the architect
# ===========================================================================


SYNTHESIS = "Puffin colonies on Skomer grew 12% year on year."
SECOND_REPLY = "Twelve percent growth it is; I'll open on that."


def test_the_analysts_answer_reaches_the_user_but_never_replays_as_the_architects(
    async_turn_env, monkeypatch
):
    """Both halves, because either alone is the wrong fix.

    The analyst emits user-facing prose, so an emit-only answer left the polling
    user staring at a gap where the SSE user saw the data — the same defect.  But
    it must be persisted as ``info``, not ``llm_response``: ``_conversation``
    carries only ``user`` and ``assistant`` roles, so a replayable analyst row
    comes back to the architect as the ARCHITECT's own words, and it arrives twice
    on this very turn — the analyst also hands the same text to the architect on
    ``architect_message``, which is the field the architect answers from.

    The paired assertion is not inert: ``info`` satisfies both, ``llm_response``
    satisfies only the first, and no persist satisfies only the second.
    """
    from src.domain.skill_io import AnalystOutput, DataRequest
    from src.services.graph.nodes import _conversation

    env = async_turn_env
    architect_passes = {"n": 0}

    def ask_then_discuss(name: str, payload: dict, design_system_active: bool):
        # The recorder is invoked ONLY for the architect: its own data_analyst
        # handler raises on purpose ("not part of any layer-1 scenario"), so
        # routing this skill through it would kill the turn.
        if name == "architect":
            env.recorder.run(
                name,
                payload,
                AgentAssemblyContext(design_system_active),
            )
            architect_passes["n"] += 1
            if architect_passes["n"] == 1:
                return ArchitectOutput(
                    intent="ask_data",
                    message=REPLY,
                    data_request=DataRequest(metric="puffin colony size"),
                )
            return ArchitectOutput(intent="discuss", message=SECOND_REPLY)
        if name == "data_analyst":
            return AnalystOutput(
                outcome="success", synthesis=SYNTHESIS, sources=["Skomer census"]
            )
        raise AssertionError(f"unexpected skill {name!r} on an ask_data turn")

    runtime = CallableAgentRuntime(ask_then_discuss)
    monkeypatch.setattr(
        "src.services.graph.nodes.get_agent_runtime",
        lambda: runtime,
    )

    request_id = env.run()
    delivered = [event["content"] for event in env.poll(request_id)["events"]]

    assert len(env.architect_payloads()) == 2, (
        "the analyst did not hand the turn back to the architect; the scenario "
        "never exercised the round trip"
    )
    assert any(SYNTHESIS in text for text in delivered), (
        f"the analyst's answer never reached the polling client: {delivered!r}"
    )
    replayed = [turn["content"] for turn in _conversation(env.session_id)]
    assert SECOND_REPLY in replayed, (
        "the architect's own reply is missing, so this test would pass on a tree "
        "that persists nothing at all"
    )
    assert not any(SYNTHESIS in text for text in replayed), (
        "the analyst's answer replays to the architect as its OWN words: "
        f"{replayed!r}"
    )
