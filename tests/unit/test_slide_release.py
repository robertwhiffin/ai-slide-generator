"""ws4d D3 — incremental slide delivery on BOTH transports.

`slides` used to ride only on the terminal `COMPLETE` event, so a fifteen-slide
deck appeared all at once at the end.  This suite pins the per-slide event and
the reorder buffer that orders it, on both the SSE transport (`emit_slide_ready`
out of `foreman_node`) and the polling transport
(`SessionManager.slides_since_cursor` out of `GET /chat/poll`).

Two hazards this suite exists to catch, both of which have bitten this
workstream:

* **A guard that passes when the production call is deleted.**  Every ordering
  and no-repeat assertion here is paired with an *entry* assertion — a non-empty
  first result, or a spy's recorded call list — so "nothing was emitted out of
  order" cannot be satisfied by nothing being emitted at all.
* **Two prefix rules that can disagree.**  `releasable_positions` (graph state,
  SSE) and `slides_since_cursor` (committed rows, polling) implement the same
  release rule over different truths.  `TestTheTwoPrefixRulesAgree` drives the
  same position set through both.

Imports are at module scope throughout, deliberately: a previous draft in this
workstream imported `SessionManager` function-locally in one test and used it in
the next.
"""

from __future__ import annotations

import contextvars
import json
import queue
import re
from pathlib import Path
from typing import get_type_hints
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.session_manager import get_session_manager
from src.api.services.slide_repository import SlideWriter, is_placeholder_record
from src.database.models.profile_contributor import PermissionLevel
from src.services.foreman_service import releasable_positions
from src.services.graph import nodes
from src.services.graph.event_emitter import (
    advance_slide_cursor,
    emit_event,
    emit_slide_ready,
    get_slide_cursor,
    set_event_emitter,
)
from src.services.graph.nodes import _release_slides, foreman_node
from src.services.graph.state import scoped
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    graph_env,
    make_spec,
)

TURN = "turn-release"

#: Anchored from this file, never cwd-relative (the CI-collection guard's rule).
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_API_TS = REPO_ROOT / "frontend" / "src" / "services" / "api.ts"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _drain(emitter: queue.Queue) -> list:
    events = []
    while not emitter.empty():
        events.append(emitter.get_nowait())
    return events


def _slide_ready(events) -> list:
    return [e for e in events if e.type is StreamEventType.SLIDE_READY]


def _commit(env, *positions, scripts: str = "") -> None:
    """Write a real committed row at each position, through the shipped writer."""
    writer = SlideWriter()
    for position in positions:
        writer.write_slide(
            session_id=env.session_id,
            position=position,
            html=f"<div class='slide'>slide {position}</div>",
            scripts=scripts,
            modified_by="build_reviewer",
        )


def _release_state(env, *, covered, landed=(), placeheld=()):
    """A turn state whose covered set and committed set are stated explicitly."""
    return env.state(
        turn_id=TURN,
        deck_spec=make_spec(tuple(covered)),
        landed_positions=scoped(TURN, set(landed)),
        placeheld_positions=scoped(TURN, set(placeheld)),
        dispatched_at=scoped(TURN, {p: None for p in covered}),
        foreman_wakes=scoped(TURN, [list(covered)]),
    )


# ===========================================================================
# The event: the streaming transport's payload
# ===========================================================================


class TestTheSlideReadyEvent:
    def test_slide_ready_is_on_the_enum_beside_the_seven_shipped_types(self):
        """`to_sse()` reads `self.type.value`, so a type off the enum cannot be
        constructed at all — and dropping one of the seven would break the
        frontend union that now names eight."""
        assert StreamEventType.SLIDE_READY.value == "slide_ready"
        assert {member.value for member in StreamEventType} == {
            "assistant",
            "tool_call",
            "tool_result",
            "error",
            "complete",
            "session_title",
            "session_created",
            "slide_ready",
        }

    def test_the_event_carries_position_html_scripts_through_to_sse(self):
        """Asserted on PARSED JSON, never a formatted substring: `to_sse()` uses
        `model_dump_json()`, which emits compact JSON with no space after the
        colon."""
        event = StreamEvent(
            type=StreamEventType.SLIDE_READY,
            position=4,
            html="<div class='slide'>four</div>",
            scripts="new Chart(ctx);",
            agent="build_reviewer",
            slide_cursor=5,
        )
        sse = event.to_sse()
        assert sse.startswith("event: slide_ready\ndata: ")
        payload = json.loads(sse.split("data: ", 1)[1].strip())
        assert payload["type"] == "slide_ready"
        assert payload["position"] == 4
        assert payload["html"] == "<div class='slide'>four</div>"
        assert payload["scripts"] == "new Chart(ctx);"
        assert payload["agent"] == "build_reviewer"
        assert payload["slide_cursor"] == 5

    def test_scripts_is_exactly_str_and_defaults_to_empty(self):
        """`Optional[str] = None` would give "no per-slide JavaScript" a second
        spelling; every other link in the slide chain uses `""`.

        The annotation is compared to `str` itself — never to a string literal
        or `type(None)`, either of which would pass a broken field."""
        assert get_type_hints(StreamEvent)["scripts"] is str
        assert StreamEvent(type=StreamEventType.COMPLETE).scripts == ""

    def test_the_seven_existing_event_shapes_are_unbroken(self):
        """The new fields are additive: every shipped construction still works
        and still serialises the keys its consumer reads."""
        shipped = [
            StreamEvent(type=StreamEventType.ASSISTANT, content="hello"),
            StreamEvent(
                type=StreamEventType.TOOL_CALL, tool_name="t", tool_input={"a": 1}
            ),
            StreamEvent(type=StreamEventType.TOOL_RESULT, tool_output="out"),
            StreamEvent(type=StreamEventType.ERROR, error="boom"),
            StreamEvent(type=StreamEventType.COMPLETE, slides={"slides": []}),
            StreamEvent(type=StreamEventType.SESSION_TITLE, session_title="T"),
            StreamEvent(type=StreamEventType.SESSION_CREATED, session_id="s-1"),
        ]
        for event in shipped:
            payload = json.loads(event.to_sse().split("data: ", 1)[1].strip())
            assert payload["type"] == event.type.value
            # A pre-existing consumer must not start seeing slide data.
            assert payload["position"] is None
            assert payload["html"] is None
            assert payload["agent"] is None
            assert payload["slide_cursor"] is None
        assert [e.content for e in shipped[:1]] == ["hello"]


class TestTheFrontendUnionMatchesTheEnum:
    """The one guard the TypeScript change itself cannot provide.

    Measured while sabotage-verifying this task: deleting `'slide_ready'` from
    `frontend/src/services/api.ts`'s `StreamEventType` union produces **no red at
    all** — `npm run typecheck` exits 0, because nothing consumes the member yet
    (`handleStreamEvent` already has seven cases and rendering is ws4e's).  So the
    union can silently go stale against the backend enum, and the symptom would be
    a ws4e `case 'slide_ready'` that does not compile, or a live event the client
    types as impossible.

    Read as text on purpose: TypeScript types are erased at runtime, so there is
    nothing to import.
    """

    def test_every_backend_event_type_is_in_the_typescript_union(self):
        source = FRONTEND_API_TS.read_text()
        match = re.search(
            r"export type StreamEventType\s*=\s*([^;]+);", source
        )
        assert match, (
            f"could not find the StreamEventType union in {FRONTEND_API_TS}; if it "
            "moved, this guard needs its new home rather than deleting"
        )
        union = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        backend = {member.value for member in StreamEventType}
        assert union == backend, (
            f"the frontend union and the backend enum disagree: only in TS "
            f"{sorted(union - backend)}, only in Python {sorted(backend - union)}"
        )

    def test_the_slide_ready_payload_fields_are_declared_on_the_ts_interface(self):
        source = FRONTEND_API_TS.read_text()
        interface = source.split("export interface StreamEvent {", 1)[1].split("}", 1)[0]
        for declaration in (
            "position?: number;",
            "html?: string;",
            "scripts?: string;",
            "agent?: string;",
            "slide_cursor?: number;",
        ):
            assert declaration in interface, (
                f"{declaration!r} is missing from the StreamEvent interface; a "
                "ws4e consumer reading it would not compile"
            )


# ===========================================================================
# emit_slide_ready — the emitter itself, not merely "an object reached a queue"
# ===========================================================================


class TestEmitSlideReady:
    def test_it_queues_a_stream_event_object_stamped_with_the_next_cursor(self):
        """Two things at once, and the second is what makes this a guard on
        `emit_slide_ready` rather than on `queue.Queue`.

        The OBJECT: `chat.py` calls `.to_sse()` on what it dequeues, so queueing
        a pre-serialised string double-encodes and raises on the first slide.

        The CURSOR: `emit_slide_ready` stamps `slide_cursor = position + 1`.
        Bypassing it — building an "equivalent" `slide_ready` event by hand and
        handing it to `emit_event` — leaves that field `None`, so this reddens.
        """
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            assert emit_slide_ready(2, "<p>two</p>", "js", "fix_reviewer") is True
        finally:
            set_event_emitter(None)

        (event,) = _drain(emitter)
        assert isinstance(event, StreamEvent), (
            f"queued a {type(event).__name__}, not a StreamEvent — chat.py calls "
            "to_sse() on what it dequeues"
        )
        assert event.type is StreamEventType.SLIDE_READY
        assert (event.position, event.html, event.scripts) == (2, "<p>two</p>", "js")
        assert event.agent == "fix_reviewer"
        assert event.slide_cursor == 3, (
            "slide_cursor was not stamped as position + 1 — either "
            "emit_slide_ready was bypassed, or it no longer tells the client "
            "which position it has not yet been sent"
        )
        assert event.to_sse().startswith("event: slide_ready\n")
        # Every event the graph queues names its origin; a turn's whole event
        # stream is grouped by this key in test_graph_builder.py.
        assert event.metadata == {"node": "release"}

    def test_a_hand_rolled_equivalent_event_is_distinguishable(self):
        """The bypass this suite must be able to see: `emit_event` with an
        event carrying the same position/html/scripts leaves `slide_cursor`
        unset.  If this ever stops being true, the guard above degrades into a
        test of the queue."""
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            emit_event(
                StreamEvent(
                    type=StreamEventType.SLIDE_READY,
                    position=2,
                    html="<p>two</p>",
                    scripts="js",
                )
            )
        finally:
            set_event_emitter(None)
        (event,) = _drain(emitter)
        assert event.slide_cursor is None

    def test_it_returns_false_without_an_emitter_and_does_not_raise(self):
        """The sweeper tick and every layer-1 state test install no emitter."""
        set_event_emitter(None)
        event_emitter_cleared = emit_slide_ready(0, "<p>x</p>")
        assert event_emitter_cleared is False

    def test_the_cursor_resets_on_every_turn_boundary(self):
        """`set_event_emitter` is called once per `invoke_graph` and nowhere
        else, so it is the one point that coincides with a turn boundary.
        Without the reset, turn 2's cursor already sits past every position turn
        1 delivered and turn 2 releases nothing at all."""
        set_event_emitter(queue.Queue())
        advance_slide_cursor(9)
        assert get_slide_cursor() == 9
        set_event_emitter(queue.Queue())
        assert get_slide_cursor() == 0
        set_event_emitter(None)

    def test_the_cursor_never_moves_backwards(self):
        set_event_emitter(queue.Queue())
        advance_slide_cursor(5)
        advance_slide_cursor(2)
        assert get_slide_cursor() == 5
        set_event_emitter(None)


# ===========================================================================
# slides_since_cursor — the polling transport's release query
# ===========================================================================


class TestSlidesSinceCursor:
    def test_the_cursor_returns_new_positions_and_nothing_on_a_re_poll(
        self, graph_env
    ):
        _commit(graph_env, 0, 1, 2)
        manager = get_session_manager()

        first = manager.slides_since_cursor(graph_env.session_id, 0)

        # ENTRY assertion: the query ran and returned the deck.  Without this,
        # the re-poll assertion below is equally true of a method that returns
        # [] unconditionally.
        assert [row["position"] for row in first] == [0, 1, 2]
        assert first[1]["html"] == "<div class='slide'>slide 1</div>"
        assert first[1]["agent"] == "build_reviewer"

        cursor = first[-1]["position"] + 1
        assert manager.slides_since_cursor(graph_env.session_id, cursor) == []

    def test_a_partial_cursor_returns_only_the_tail(self, graph_env):
        _commit(graph_env, 0, 1, 2, 3)
        manager = get_session_manager()
        assert [
            row["position"]
            for row in manager.slides_since_cursor(graph_env.session_id, 2)
        ] == [2, 3]

    def test_a_later_position_landing_first_releases_nothing_above_the_gap(
        self, graph_env
    ):
        """Position 2 committed before position 1 must NOT be released.

        The second assertion is the one that catches the real defect: a cursor
        of 2 makes position 2 the FIRST row a `position >= cursor` query would
        see, so an implementation that filters before scanning reads it as the
        start of the deck and releases it over the gap."""
        _commit(graph_env, 0, 2)
        manager = get_session_manager()

        # ENTRY assertion: position 0 IS released, so "2 was not released" is
        # not just "nothing was released".
        assert [
            row["position"]
            for row in manager.slides_since_cursor(graph_env.session_id, 0)
        ] == [0]
        assert manager.slides_since_cursor(graph_env.session_id, 2) == []

        # Once the gap closes, the whole prefix is releasable.
        _commit(graph_env, 1)
        assert [
            row["position"]
            for row in manager.slides_since_cursor(graph_env.session_id, 1)
        ] == [1, 2]

    def test_a_missing_position_zero_releases_nothing(self, graph_env):
        _commit(graph_env, 1, 2)
        assert get_session_manager().slides_since_cursor(graph_env.session_id, 0) == []

    def test_a_placeholder_releases_like_any_other_position(self, graph_env):
        """`commit_placeholder` writes a real row, so the release query needs no
        special case — but it must be able to release POSITIONS ABOVE it, which
        is the whole reason a failed builder does not freeze the deck."""
        _commit(graph_env, 0)
        SlideWriter().commit_placeholder(
            graph_env.session_id, 1, error_message="builder exploded"
        )
        _commit(graph_env, 2)

        released = get_session_manager().slides_since_cursor(graph_env.session_id, 0)
        assert [row["position"] for row in released] == [0, 1, 2]

        placeholder_row = SlideWriter().get_slide(graph_env.session_id, 1)
        assert is_placeholder_record(placeholder_row["verification_record"])
        assert released[1]["html"] == placeholder_row["html"]

    def test_a_negative_cursor_is_read_as_zero(self, graph_env):
        """Positions are 0-based, so a client that mirrors `after_message_id`'s
        exclusive-after convention would start at -1.  Both -1 and 0 must
        deliver position 0."""
        _commit(graph_env, 0, 1)
        manager = get_session_manager()
        assert [
            row["position"]
            for row in manager.slides_since_cursor(graph_env.session_id, -1)
        ] == [0, 1]

    def test_scripts_and_agent_are_json_native_scalars(self, graph_env):
        _commit(graph_env, 0, scripts="new Chart(ctx);")
        (row,) = get_session_manager().slides_since_cursor(graph_env.session_id, 0)
        assert set(row) == {"position", "html", "scripts", "agent"}
        json.dumps(row)  # must be serialisable onto a poll response as-is
        assert row["scripts"] == "new Chart(ctx);"


# ===========================================================================
# The two prefix rules must agree
# ===========================================================================


class TestTheTwoPrefixRulesAgree:
    """`releasable_positions` reads GRAPH STATE; `slides_since_cursor` reads
    COMMITTED ROWS.  The polling path has no graph state and a poll may be served
    by a different uvicorn worker, so the rule genuinely has two
    implementations — and two prefix rules that can disagree are worse than one,
    because the divergence is otherwise invisible."""

    @pytest.mark.parametrize(
        "covered,committed",
        [
            ((0, 1, 2), ()),
            ((0, 1, 2), (0,)),
            ((0, 1, 2), (0, 1)),
            ((0, 1, 2), (0, 1, 2)),
            ((0, 1, 2), (0, 2)),
            ((0, 1, 2), (1, 2)),
            ((0, 1, 2, 3), (0, 1, 3)),
            ((0, 1, 2, 3, 4), (0, 1, 2, 4)),
        ],
    )
    def test_the_same_position_set_gives_the_same_prefix(
        self, graph_env, covered, committed
    ):
        _commit(graph_env, *committed)
        by_state = releasable_positions(
            _release_state(graph_env, covered=covered, landed=committed)
        )
        by_rows = [
            row["position"]
            for row in get_session_manager().slides_since_cursor(
                graph_env.session_id, 0
            )
        ]
        assert by_rows == by_state, (
            f"the row-derived prefix {by_rows} and the state-derived prefix "
            f"{by_state} disagree for committed={sorted(committed)}"
        )

    def test_they_agree_when_the_committed_position_is_a_placeholder(self, graph_env):
        """A placeholder is inside `releasable_positions`' committed set
        (`placeheld_positions`) and is an ordinary row for the row query."""
        _commit(graph_env, 0)
        SlideWriter().commit_placeholder(graph_env.session_id, 1, error_message="x")
        by_state = releasable_positions(
            _release_state(
                graph_env, covered=(0, 1, 2), landed=(0,), placeheld=(1,)
            )
        )
        by_rows = [
            row["position"]
            for row in get_session_manager().slides_since_cursor(
                graph_env.session_id, 0
            )
        ]
        assert by_state == [0, 1]
        assert by_rows == by_state


# ===========================================================================
# The SSE transport: the foreman wake releases the committed prefix
# ===========================================================================


class TestTheForemanWakeReleasesSlides:
    def test_a_wake_emits_the_committed_prefix_in_ascending_order(self, graph_env):
        """The whole feature: slides reach the client as they land, in index
        order, out of the node that runs ALONE after the superstep barrier."""
        _commit(graph_env, 0, 1, 2)
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            foreman_node(
                _release_state(graph_env, covered=(0, 1, 2), landed=(0, 1, 2))
            )
            # Read INSIDE the turn: `set_event_emitter(None)` is a turn boundary
            # and resets the cursor, which is the behaviour the reset test pins.
            cursor_after_the_wake = get_slide_cursor()
        finally:
            set_event_emitter(None)

        events = _slide_ready(_drain(emitter))
        assert [e.position for e in events] == [0, 1, 2]
        assert [e.slide_cursor for e in events] == [1, 2, 3]
        assert events[1].html == "<div class='slide'>slide 1</div>"
        assert events[1].agent == "build_reviewer"
        assert cursor_after_the_wake == 3

    def test_the_release_goes_through_emit_slide_ready(self, graph_env, monkeypatch):
        """An ENTRY assertion on the emitter, not on the queue.  Rewriting
        `_release_slides` to call `emit_event` with a hand-built event would
        leave every ordering assertion above green and this spy empty."""
        _commit(graph_env, 0, 1)
        calls = []

        def spy(**kwargs):
            calls.append(kwargs)
            return True

        monkeypatch.setattr(nodes, "emit_slide_ready", spy)
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            foreman_node(_release_state(graph_env, covered=(0, 1), landed=(0, 1)))
        finally:
            set_event_emitter(None)

        assert [call["position"] for call in calls] == [0, 1]
        assert calls[0]["html"] == "<div class='slide'>slide 0</div>"
        assert calls[0]["scripts"] == ""
        assert calls[0]["agent"] == "build_reviewer"

    def test_a_later_position_landing_first_is_not_emitted_over_the_gap(
        self, graph_env
    ):
        """Builders complete out of order; the client must not see slide 2
        before slide 1.  Position 0 IS emitted, so this is not vacuous."""
        _commit(graph_env, 0, 2)
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            foreman_node(_release_state(graph_env, covered=(0, 1, 2), landed=(0, 2)))
        finally:
            set_event_emitter(None)

        assert [e.position for e in _slide_ready(_drain(emitter))] == [0]

    def test_a_second_wake_does_not_re_emit_an_already_released_slide(
        self, graph_env
    ):
        """The cursor is what stops a fifteen-slide deck re-sending every slide
        it has already sent on every one of its foreman wakes."""
        _commit(graph_env, 0)
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            foreman_node(_release_state(graph_env, covered=(0, 1, 2), landed=(0,)))
            first = [e.position for e in _slide_ready(_drain(emitter))]

            _commit(graph_env, 1, 2)
            foreman_node(
                _release_state(graph_env, covered=(0, 1, 2), landed=(0, 1, 2))
            )
            second = [e.position for e in _slide_ready(_drain(emitter))]
        finally:
            set_event_emitter(None)

        assert first == [0]  # ENTRY: the first wake did emit
        assert second == [1, 2]

    def test_the_cursor_survives_the_context_copy_langgraph_makes(self, graph_env):
        """LangGraph runs nodes through `ContextThreadPoolExecutor`, whose
        `submit` wraps every task in `copy_context().run(...)`.  A
        `ContextVar.set()` inside a node dies with that copy, so the cursor MUST
        be advanced by mutating its holder in place — otherwise every wake reads
        0 and re-emits the whole released prefix."""
        _commit(graph_env, 0)
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            state_one = _release_state(graph_env, covered=(0, 1, 2), landed=(0,))
            contextvars.copy_context().run(foreman_node, state_one)
            first = [e.position for e in _slide_ready(_drain(emitter))]

            _commit(graph_env, 1, 2)
            state_two = _release_state(
                graph_env, covered=(0, 1, 2), landed=(0, 1, 2)
            )
            contextvars.copy_context().run(foreman_node, state_two)
            second = [e.position for e in _slide_ready(_drain(emitter))]
        finally:
            set_event_emitter(None)

        assert first == [0]
        assert second == [1, 2], (
            f"the second wake emitted {second}; a cursor advanced with "
            "ContextVar.set() inside a copied context is lost, so position 0 "
            "is re-emitted on every wake"
        )

    def test_a_placeheld_position_is_released_on_the_wake_like_any_other(
        self, graph_env
    ):
        """One terminal builder failure must not freeze the release prefix
        forever — the positions above the placeholder have to reach the client."""
        _commit(graph_env, 0)
        SlideWriter().commit_placeholder(
            graph_env.session_id, 1, error_message="builder exploded"
        )
        _commit(graph_env, 2)
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            foreman_node(
                _release_state(
                    graph_env, covered=(0, 1, 2), landed=(0, 2), placeheld=(1,)
                )
            )
        finally:
            set_event_emitter(None)

        events = _slide_ready(_drain(emitter))
        assert [e.position for e in events] == [0, 1, 2]
        assert "slide-placeholder-error" in events[1].html

    def test_nothing_is_released_and_nothing_raises_without_an_emitter(
        self, graph_env
    ):
        """The sweeper tick and every layer-1 state test pass no emitter."""
        _commit(graph_env, 0, 1)
        set_event_emitter(None)
        assert _release_slides(_release_state(graph_env, covered=(0, 1), landed=(0, 1))) == []

    def test_a_releasable_position_with_no_readable_row_holds_the_release(
        self, graph_env
    ):
        """State says committed, no row exists: STOP rather than skip, or the
        next position is delivered ahead of this one."""
        _commit(graph_env, 0, 2)
        emitter: queue.Queue = queue.Queue()
        set_event_emitter(emitter)
        try:
            released = _release_slides(
                _release_state(graph_env, covered=(0, 1, 2), landed=(0, 1, 2))
            )
        finally:
            set_event_emitter(None)
        assert released == [0]
        assert [e.position for e in _slide_ready(_drain(emitter))] == [0]


# ===========================================================================
# The polling transport: GET /chat/poll
# ===========================================================================


@pytest.fixture
def poll_client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def poll_manager(monkeypatch):
    manager = MagicMock()
    manager.get_session_id_for_request.return_value = "sess-poll"
    manager.get_chat_request.return_value = {
        "status": "processing",
        "result": None,
        "error_message": None,
    }
    manager.get_messages_for_request.return_value = []
    monkeypatch.setattr("src.api.routes.chat.get_session_manager", lambda: manager)
    monkeypatch.setattr(
        "src.api.routes.chat._check_deck_permission_for_session", MagicMock()
    )
    return manager


def _row(position: int) -> dict:
    return {
        "position": position,
        "html": f"<div class='slide'>slide {position}</div>",
        "scripts": "",
        "agent": "build_reviewer",
    }


class TestThePollingRoute:
    def test_it_returns_released_slides_and_the_next_cursor(
        self, poll_client, poll_manager
    ):
        poll_manager.slides_since_cursor.return_value = [_row(0), _row(1)]

        response = poll_client.get("/api/chat/poll/req-1")

        assert response.status_code == 200
        body = response.json()
        assert [slide["position"] for slide in body["slides"]] == [0, 1]
        assert body["slides"][0] == _row(0)
        assert body["slide_cursor"] == 2
        # The five pre-existing keys are untouched.
        assert set(body) == {
            "status",
            "events",
            "last_message_id",
            "result",
            "error",
            "slides",
            "slide_cursor",
        }

    def test_it_passes_the_client_cursor_through_to_the_release_query(
        self, poll_client, poll_manager
    ):
        poll_manager.slides_since_cursor.return_value = [_row(2)]

        response = poll_client.get("/api/chat/poll/req-1?slide_cursor=2")

        assert response.status_code == 200
        # ENTRY assertion: the route reached the query, with the client's cursor
        # and the session the permission gate resolved — not a hardcoded 0.
        assert poll_manager.slides_since_cursor.call_args.args == ("sess-poll", 2)
        assert response.json()["slide_cursor"] == 3

    def test_nothing_released_returns_the_incoming_cursor_unchanged(
        self, poll_client, poll_manager
    ):
        poll_manager.slides_since_cursor.return_value = []

        body = poll_client.get("/api/chat/poll/req-1?slide_cursor=7").json()

        assert body["slides"] == []
        assert body["slide_cursor"] == 7, (
            "a poll that released nothing must hand the client its own cursor "
            "back, or the client rewinds and re-receives every slide"
        )

    def test_the_default_cursor_is_zero_so_a_first_poll_gets_position_zero(
        self, poll_client, poll_manager
    ):
        poll_manager.slides_since_cursor.return_value = [_row(0)]

        poll_client.get("/api/chat/poll/req-1")

        assert poll_manager.slides_since_cursor.call_args.args == ("sess-poll", 0)

    def test_the_slides_read_happens_after_the_permission_gate(
        self, poll_client, monkeypatch
    ):
        """SDR-4437's gate must still come first: a leaked request_id must not
        reach slide HTML."""
        manager = MagicMock()
        manager.get_session_id_for_request.return_value = "sess-poll"
        monkeypatch.setattr(
            "src.api.routes.chat.get_session_manager", lambda: manager
        )

        def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="denied")

        monkeypatch.setattr(
            "src.api.routes.chat._check_deck_permission_for_session", gate
        )

        assert poll_client.get("/api/chat/poll/req-leaked").status_code == 403
        manager.slides_since_cursor.assert_not_called()
