# ruff: noqa: F811 — the conftest_graph fixture is imported, then requested by name.
"""Chat image generation, Unit H (plan Tasks 3 and 4): the architect's ``generate_image``.

What is pinned (plan Tasks 3-4, CORRECTIONS "Unit H interface", R3 and R5):

* **Binding.**  With the feature on (``_image_generation_available()``, read on EVERY
  turn, never cached: R5) and not on a describe-only turn, every architect attempt is
  handed a toolset holding a fresh ``generate_image`` tool, sized from what is left of
  the TURN's image budget (2 calls, 6 images, 240 s, summed over this turn's
  ``image_tool_usage``, clipped to the 700 s turn deadline).  Beside Gateway tools it
  rides the same toolset, whose call cap is the Gateway cap plus the image calls left,
  and the Gateway budget is not charged for the image tool's seconds.
* **Fallback.**  A call that carried the image tool and raised is made once more with no
  toolset, and from then on the pass binds the tool no more.  With Gateway tools too,
  BOTH passes are told (a non-short-circuiting ``|``).
* **Progress.**  One ``tool_call`` row (``tool_name="image_generation"``,
  ``tool_input={"kind", "count"}``) and one ``TOOL_CALL`` event with TOP-LEVEL
  ``tool_name`` / ``tool_input`` per tool call.
* **State.**  ``generated_images`` (the tool's R3 refs) and ``image_tool_usage``
  (``{"calls", "images", "seconds"}`` per pass), turn-scoped, on every return path.
* **What the turn reports.**  The architect's reply row and its ASSISTANT event carry
  ``generated_images`` metadata (the shared shape, ``slides`` from the committed
  canonical spec); a generated ``{{image:…}}`` in the reply text is said as "option N";
  the builder allow-list and the architect's reconciliation run whenever this turn
  generated images, with "A generated image couldn't be placed on slide N."; a turn
  with the tool bound but unused behaves exactly as today; the next turn's conversation
  replays a system note listing the options; a refused edit keeps its images.

The seam: **the tool class nodes builds** (``nodes.ImageGenerationAgentTool``) is
replaced by :class:`_FakeImageTool`, which takes the ``ImageToolContext`` the node
builds, honours its ``calls_left`` / ``images_left``, calls its ``on_call(kind, n)``
first, and "generates" ``n`` images with fresh tokens (recording the R3 refs on
``generated``, and ``calls`` / ``images`` / ``seconds``, exactly as Unit G's interface
reads).  So these tests pin the NODE against the interface, never the tool's internals.
``ImageGenerator.generate`` is also replaced by a tripwire, so a node that built the real
tool some other way fails loudly instead of reaching the image model.  The availability
gate is the REAL ``_image_generation_available`` (the ``image_tool`` marker turns off
the conftest patch): the env flag is set to "1" and the admin toggle has no row (on).

The model is ``tests.fixtures.graph_tool_runtime.FakeRuntime``: a call that carries a
toolset plays its tool calls through ``DatabricksModelAdapter._answer_tool_call``.

Sabotage map (each line names what goes red):

* bind on a describe-only turn -> ``test_a_describe_only_turn_binds_no_image_tool``;
* ignore either switch, or cache availability -> the switched-off and R5 tests;
* not summing this turn's ``image_tool_usage`` -> ``test_a_later_pass_...``;
* no deadline -> the two deadline tests;
* charge image seconds to the Gateway -> ``test_image_seconds_are_not_charged_...``;
* drop ``images.without_tools`` -> the image-only fallback tests;
* a short-circuiting ``or`` (either order) -> ``test_a_failed_call_carrying_both_...``;
* ``_emit`` without top-level fields, or a row per image -> the progress test;
* metadata ``slides`` before the re-stamp / composition -> the canonical-numbering rows;
* builder gate left at ``gateway_usage`` -> the edit test (allow-list and notice);
* reconcile on every turn -> ``test_a_bound_but_unused_tool_changes_nothing``;
* skip the reply clean-up -> the discuss test; drop the note -> the replay test;
* drop the images on a refusal -> ``test_a_refused_edit_after_generating_...``.
"""

from __future__ import annotations

import contextlib
import json
import queue
import re
import secrets
import time
from typing import Any, Callable, ClassVar, Dict, List, Literal, Optional, Sequence, get_type_hints

import pytest
from pydantic import BaseModel, Field

from src.api.schemas.streaming import StreamEventType
from src.api.services.session_manager import get_session_manager
from src.domain.deck_spec import SlideSpec
from src.domain.skill_io import ArchitectOutput, DataRequest
from src.domain.slide_operations import SlideContent, SlideOperation
from src.services import image_service
from src.services.agent_runtime import AgentAssemblyContext
from src.services.graph import nodes
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import REFUSAL_METADATA_KEY, build_branch_payload, builder_node
from src.services.graph.state import (
    _EMPTY_FOR,
    GraphState,
    scoped,
    scoped_vals,
    turn_scoped_concat,
)
from src.services.image_generation import ENV_FLAG, ImageGenerator
from src.services.workspace_settings import set_image_generation_enabled
from src.utils.image_utils import IMAGE_PLACEHOLDER_PATTERN
from tests.fixtures.graph_tool_runtime import (
    FakeRuntime,
    fold,
    install_runtime,
    ref,
    run_architect,
    turn_state,
    with_slides,
)
from tests.fixtures.model_payload_keys import ARCHITECT_MODEL_KEYS
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    builder_out,
    graph_env,
    make_spec,
)
from tests.unit.test_architect_insert_slide import (
    GAPPED,
    THREE,
    _new,
    _persist,
    _persisted_spec,
    _seed_rows,
    _spec_of,
)
from tests.unit.test_graph_gateway_mcp import (
    CREATE,
    EXPORT,
    _lakedraw_deck,
    _loop_gave_up,
    _pinned_error,
    _tools_failed,
    _usage_vals,
)

pytestmark = pytest.mark.image_tool

TURN = "turn-1"
REQUEST_ID = "req-image-tool"
#: ``graph_env.state()``'s ``initiated_by``: the turn's user, who owns its images.
USER = "graph-user@example.com"

IMAGE_TOOL = "generate_image"
#: The ``tool_name`` a progress row and event carry (the frontend's activity label).
PROGRESS_TOOL = "image_generation"
#: CORRECTIONS, Unit H interface: ``_IMAGE_NOT_PLACED_GENERATED``.
GENERATED_NOT_PLACED = "A generated image couldn't be placed on slide {n}."
GATEWAY_NOT_PLACED_PREFIX = "An image from a connected tool couldn't be placed"
#: The shared metadata shape's keys (CORRECTIONS, "Shared metadata shape").
METADATA_KEYS = {"token", "kind", "option", "prompt", "for_slide", "slides"}
USAGE_KEYS = {"calls", "images", "seconds"}

#: An invented reference: 43 characters, sharing no 12-character prefix with a real one.
INVENTED = "Z" * 43

PROMPT = "A calm blue isometric data pipeline, flat style, no text"
#: Longer than the metadata's 300-character prompt cap.
LONG_PROMPT = ("A calm blue isometric data pipeline with glowing nodes, " * 8).strip()


# ---------------------------------------------------------------------------
# The fake tool: the class nodes builds, replaced (the seam)
# ---------------------------------------------------------------------------


class _RealImageModelReached(BaseException):
    """The real ``ImageGenerator`` was called: the node did not build its tool through
    ``nodes.ImageGenerationAgentTool``.  A ``BaseException``, so no ``except Exception``
    in the code under test can turn it into a pass."""


def _never_generate(self, *args, **kwargs):
    raise _RealImageModelReached(
        "ImageGenerator.generate was called: build the tool through "
        "nodes.ImageGenerationAgentTool, the seam these tests replace"
    )


class _ImageArgs(BaseModel):
    """The tool's arguments, as Unit G's ``ImageGenerationArgs`` declares them."""

    prompt: str = Field(min_length=1, max_length=2000)
    kind: Literal["illustration", "background", "icon", "vector_icon"]
    count: int = Field(1, ge=1, le=3)
    for_slide: Optional[int] = Field(None, ge=1)


class _ImageTools:
    """What the fake tools did this test: every tool the node built, every token made."""

    def __init__(self) -> None:
        self.built: List["_FakeImageTool"] = []
        self.made: List[str] = []
        #: Seconds each run takes (a real sleep: the toolset's clock is real).
        self.delay = 0.0
        #: Called after ``on_call`` and before the images are "generated".
        self.on_generate: Optional[Callable[[], None]] = None

    def next_token(self) -> str:
        token = secrets.token_urlsafe(32)  # shaped like a real image token: 43 chars
        self.made.append(token)
        return token

    @property
    def contexts(self) -> List[Any]:
        return [tool.context for tool in self.built]


class _FakeImageTool:
    """Stands in for ``ImageGenerationAgentTool`` (Unit G's interface, not its code)."""

    name = IMAGE_TOOL
    description = "Generate 1-3 images (test double)."
    args_schema = _ImageArgs
    tools: ClassVar[_ImageTools]

    def __init__(self, context: Any) -> None:
        self.context = context
        self.generated: List[Dict[str, Any]] = []
        self.calls = 0
        self.images = 0
        self.seconds = 0.0
        self.tools.built.append(self)

    def run(self, args: _ImageArgs, *, remaining_seconds: float) -> str:
        started = time.monotonic()
        images_left = self.context.images_left - self.images
        if self.calls >= self.context.calls_left or images_left <= 0:
            return "Image generation refused: this turn's image budget is spent."
        n = min(args.count, 3, images_left)
        try:
            self.context.on_call(args.kind, n)
        except Exception:  # noqa: BLE001 - the interface swallows on_call errors
            pass
        self.calls += 1
        if self.tools.on_generate is not None:
            self.tools.on_generate()
        if self.tools.delay:
            time.sleep(self.tools.delay)
        lines = [
            f"Generated {n} of {args.count} {args.kind} images, saved to the user's "
            "Image Library:"
        ]
        for option in range(1, n + 1):
            token = self.tools.next_token()
            self.generated.append(
                {
                    "token": token,
                    "kind": args.kind,
                    "option": option,
                    "prompt": args.prompt,
                    "for_slide": args.for_slide,
                }
            )
            lines.append(f"Option {option}: " + ref(token) + " (image/png, 1024x1024)")
        lines.append("Nothing is on a slide yet. The user sees these images under your reply.")
        self.images += n
        self.seconds += time.monotonic() - started
        return "\n".join(lines)

    def saved_tokens(self) -> List[str]:
        return [entry["token"] for entry in self.generated]


def _install_image_tools(monkeypatch) -> _ImageTools:
    tools = _ImageTools()
    fake = type("FakeImageGenerationAgentTool", (_FakeImageTool,), {"tools": tools})
    monkeypatch.setattr(nodes, "ImageGenerationAgentTool", fake, raising=False)
    monkeypatch.setattr(ImageGenerator, "generate", _never_generate)
    return tools


@pytest.fixture
def images_on(monkeypatch):
    """Both switches on, as a deployment that never touched them: the env flag (set
    explicitly, so a developer's environment cannot turn it off) and no admin row."""
    monkeypatch.setenv(ENV_FLAG, "1")


@pytest.fixture
def image_tools(monkeypatch) -> _ImageTools:
    return _install_image_tools(monkeypatch)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _run(env, state: Dict[str, Any]):
    return run_architect(env, state, request_id=REQUEST_ID)


def _generate(call, *, count: int = 3, kind: str = "illustration", prompt: str = PROMPT,
              for_slide: Optional[int] = None) -> str:
    args: Dict[str, Any] = {"prompt": prompt, "kind": kind, "count": count}
    if for_slide is not None:
        args["for_slide"] = for_slide
    return call.use(IMAGE_TOOL, args)


def _discuss(message: str = "Here are some options.") -> ArchitectOutput:
    return ArchitectOutput(intent="discuss", message=message)


def _llm_rows(t) -> List[Dict[str, Any]]:
    return [r for r in t.rows if r["message_type"] == "llm_response"]


def _architect_events(t, event_type=StreamEventType.ASSISTANT) -> List[Any]:
    return [
        e for e in t.events
        if e.type == event_type and (e.metadata or {}).get("node") == "architect"
    ]


def _meta(entries: Sequence[Dict[str, Any]]) -> List[tuple]:
    """``(token, kind, option, for_slide, slides)`` of each metadata entry."""
    return [
        (e["token"], e["kind"], e["option"], e["for_slide"], e["slides"]) for e in entries
    ]


def _image_vals(updates: Dict[str, Any], key: str) -> List[Any]:
    wrapper = updates[key]
    assert isinstance(wrapper, dict) and wrapper.get("turn") == TURN, wrapper
    return list(wrapper["vals"])


def _three_committed_slides(env):
    """Rows and the persisted spec at positions ``0..2`` (a built 3-slide deck)."""
    _seed_rows(env, THREE)
    prior = make_spec((0, 1, 2))
    _persist(env, prior)
    return prior


def _builder_run(env, monkeypatch, payload: Dict[str, Any], html: str):
    runtime = install_runtime(
        monkeypatch, FakeRuntime(builder=lambda call: builder_out(call.payload, html=html))
    )
    before = len(env.messages())
    updates = builder_node(payload)
    rows = env.messages()[before:]
    (call,) = runtime.calls_for("builder")
    return (
        updates["slides"]["vals"][payload["position"]]["html"],
        [r["content"] for r in rows if r["message_type"] == "info"],
        call,
    )


@contextlib.contextmanager
def _unreachable_db():
    raise RuntimeError("the database is unreachable (test)")
    yield  # pragma: no cover


# ===========================================================================
# The seam, the state keys and _emit
# ===========================================================================


def test_nodes_builds_the_tool_modules_own_class():
    """The seam this file replaces is the real one: nodes builds its tool from
    ``image_generation_tool.ImageGenerationAgentTool``, imported under that name."""
    from src.services.agent_tools import image_generation_tool

    assert nodes.ImageGenerationAgentTool is image_generation_tool.ImageGenerationAgentTool
    assert image_generation_tool.IMAGE_TOOL_NAME == IMAGE_TOOL


def test_image_state_keys_are_turn_scoped_lists():
    """``generated_images`` and ``image_tool_usage`` accumulate across the turn's passes
    (``turn_scoped_concat``, empty ``[]``) and a new turn starts them empty."""
    hints = get_type_hints(GraphState, include_extras=True)
    for key in ("generated_images", "image_tool_usage"):
        assert hints[key].__metadata__[0] is turn_scoped_concat, key
        assert _EMPTY_FOR[key] == [] and isinstance(_EMPTY_FOR[key], list), key
        assert scoped_vals({"turn_id": TURN}, key) == []
        assert scoped_vals({"turn_id": "turn-2", key: scoped(TURN, ["x"])}, key) == []
        assert scoped_vals({"turn_id": TURN, key: scoped(TURN, ["x"])}, key) == ["x"]


def test_emit_sets_the_events_top_level_tool_fields():
    """``_emit`` gains ``tool_name`` / ``tool_input`` (additive): the frontend's SSE
    ``tool_call`` case reads ``event.tool_name``, not the metadata's."""
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    try:
        nodes._emit(
            StreamEventType.TOOL_CALL,
            content="Generating 3 illustrations",
            metadata={"node": "architect"},
            tool_name=PROGRESS_TOOL,
            tool_input={"kind": "illustration", "count": 3},
        )
        nodes._emit(StreamEventType.ASSISTANT, content="plain", metadata={"node": "architect"})
    finally:
        set_event_emitter(None)
    tool_event, plain = emitter.get_nowait(), emitter.get_nowait()
    assert (tool_event.tool_name, tool_event.tool_input) == (
        PROGRESS_TOOL,
        {"kind": "illustration", "count": 3},
    )
    assert tool_event.metadata == {"node": "architect"}
    assert (plain.tool_name, plain.tool_input) == (None, None)


# ===========================================================================
# Binding: the gate, describe-only, the turn's budget, the deadline, the owner
# ===========================================================================


def test_feature_on_binds_exactly_the_image_tool(graph_env, monkeypatch, images_on, image_tools):
    """No Gateway entry, the feature on: the ONE architect call carries a toolset of
    exactly ``generate_image`` (the tool the node built), with a 2-call budget and at
    most 240 s; the tool's context holds the turn's whole image budget, the deadline,
    the owner and the session; the payload is today's; the deck is built."""
    spec = make_spec((0, 1))
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=architect_build(spec)))
    state = turn_state(graph_env)

    t = _run(graph_env, state)

    (call,) = runtime.calls_for("architect")
    assert call.tool_names == [IMAGE_TOOL]
    (tool,) = call.toolset.tools
    assert tool is image_tools.built[-1]
    max_calls, budget_seconds, made = call.at_start
    assert (max_calls, made) == (2, 0)
    assert 200.0 < budget_seconds <= 240.0
    assert call.context == AgentAssemblyContext(False, graph_env.session_id, graph_env.session_id)
    assert set(call.payload) == ARCHITECT_MODEL_KEYS
    context = tool.context
    assert (context.calls_left, context.images_left) == (2, 6)
    assert 200.0 < context.seconds_left <= 240.0
    assert context.deadline_at == pytest.approx(state["turn_started_at"] + 700.0, abs=1.0)
    assert (context.owner, context.session_id) == (USER, graph_env.session_id)
    assert callable(context.on_call)
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None


@pytest.mark.parametrize("switch", ["env-off", "admin-off", "gate-error", "gate-false"])
def test_switched_off_binds_nothing_and_writes_no_image_keys(
    graph_env, monkeypatch, images_on, image_tools, switch
):
    """The env flag off, the admin toggle off, a gate that cannot be read (False on any
    error), or the gate itself False: today's call (no toolset), no tool built, and no
    ``generated_images`` / ``image_tool_usage`` key; the deck is still built."""
    if switch == "env-off":
        monkeypatch.setenv(ENV_FLAG, "0")
    elif switch == "admin-off":
        db = graph_env.factory()
        try:
            set_image_generation_enabled(db, enabled=False, user="admin@example.com")
        finally:
            db.close()
    elif switch == "gate-error":
        monkeypatch.setattr(nodes, "get_db_session", _unreachable_db)
    else:
        monkeypatch.setattr(nodes, "_image_generation_available", lambda: False)
    spec = make_spec((0, 1))
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=architect_build(spec)))

    t = _run(graph_env, turn_state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    assert image_tools.built == []
    assert "generated_images" not in t.updates
    assert "image_tool_usage" not in t.updates
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None


def test_availability_is_read_on_every_turn(graph_env, monkeypatch, images_on, image_tools):
    """R5, never cached: the admin turns the feature off between two turns and on again
    before a third; each turn binds exactly what its own read says."""
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=_discuss()))

    def toggle(enabled: bool) -> None:
        db = graph_env.factory()
        try:
            set_image_generation_enabled(db, enabled=enabled, user="admin@example.com")
        finally:
            db.close()

    _run(graph_env, turn_state(graph_env))
    toggle(False)
    _run(graph_env, turn_state(graph_env, turn_id="turn-2"))
    toggle(True)
    _run(graph_env, turn_state(graph_env, turn_id="turn-3"))

    assert [call.tool_names for call in runtime.calls_for("architect")] == [
        [IMAGE_TOOL],
        [],
        [IMAGE_TOOL],
    ]


def test_a_describe_only_turn_binds_no_image_tool(graph_env, monkeypatch, images_on, image_tools):
    """The arc-review sweeper (describe-only): nobody is there to see an image, so the
    call is today's and nothing image-related is written."""
    spec = make_spec((0, 1))
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=architect_build(spec)))

    t = _run(graph_env, turn_state(graph_env, describe_only=scoped(TURN, True)))

    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    assert image_tools.built == []
    assert "generated_images" not in t.updates
    assert "image_tool_usage" not in t.updates


@pytest.mark.parametrize(
    ("prior", "expected"),
    [
        ([{"calls": 2, "images": 2, "seconds": 30.0}], None),
        (
            [
                {"calls": 1, "images": 3, "seconds": 10.0},
                {"calls": 1, "images": 1, "seconds": 10.0},
            ],
            None,
        ),
        ([{"calls": 1, "images": 1, "seconds": 240.0}], None),
        ([{"calls": 1, "images": 3, "seconds": 20.0}], (1, 3, 220.0)),
        ([{"calls": 0, "images": 0, "seconds": 100.0}], (2, 6, 140.0)),
    ],
    ids=["2-calls-used", "two-passes-of-1", "240s-used", "1-call-3-images-20s", "100s-used"],
)
def test_a_later_pass_in_the_turn_sizes_the_tool_from_earlier_usage(
    graph_env, monkeypatch, images_on, image_tools, prior, expected
):
    """This turn's ``image_tool_usage`` entries, summed, are what the pass may still
    spend: with no call or no second left the call carries no image tool; otherwise the
    tool's context and the toolset hold exactly what is left."""
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=_discuss()))

    _run(graph_env, turn_state(graph_env, image_tool_usage=scoped(TURN, prior)))

    (call,) = runtime.calls_for("architect")
    if expected is None:
        assert call.context.toolset is None
        assert image_tools.built == []
        return
    calls_left, images_left, seconds_left = expected
    assert call.tool_names == [IMAGE_TOOL]
    assert call.at_start[0] == calls_left
    assert call.at_start[1] == pytest.approx(seconds_left, abs=1.0)
    (context,) = image_tools.contexts
    assert (context.calls_left, context.images_left) == (calls_left, images_left)
    assert context.seconds_left == pytest.approx(seconds_left, abs=1.0)
    assert context.seconds_left <= seconds_left


def test_a_previous_turns_image_usage_does_not_count(
    graph_env, monkeypatch, images_on, image_tools
):
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=_discuss()))
    stale = scoped("turn-0", [{"calls": 2, "images": 6, "seconds": 240.0}])

    _run(graph_env, turn_state(graph_env, image_tool_usage=stale))

    (call,) = runtime.calls_for("architect")
    assert call.tool_names == [IMAGE_TOOL]
    assert call.at_start[0] == 2
    (context,) = image_tools.contexts
    assert (context.calls_left, context.images_left) == (2, 6)


def test_past_the_turn_deadline_no_image_tool_is_bound(
    graph_env, monkeypatch, images_on, image_tools
):
    """701 s into the turn: today's call, no tool built, and the deck is built."""
    spec = make_spec((0, 1))
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=architect_build(spec)))

    t = _run(graph_env, turn_state(graph_env, turn_started_at=time.time() - 701))

    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    assert image_tools.built == []
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None


def test_the_deadline_clips_the_image_budget(graph_env, monkeypatch, images_on, image_tools):
    """650 s in, 50 s of the turn are left: the tool gets that, not 240 s, and the
    deadline it refuses past is the turn's (``turn_started_at`` + 700, epoch seconds)."""
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=_discuss()))
    state = turn_state(graph_env, turn_started_at=time.time() - 650)

    _run(graph_env, state)

    (call,) = runtime.calls_for("architect")
    assert call.at_start[0] == 2
    assert 40.0 < call.at_start[1] <= 50.0
    (context,) = image_tools.contexts
    assert 40.0 < context.seconds_left <= 50.0
    assert context.deadline_at == pytest.approx(state["turn_started_at"] + 700.0, abs=1.0)


@pytest.mark.parametrize("initiated_by", [USER, None], ids=["initiated_by", "fallback"])
def test_the_images_belong_to_the_turns_initiator(
    graph_env, monkeypatch, images_on, image_tools, initiated_by
):
    """The owner is ``state["initiated_by"]``; only without one is it
    ``image_service.resolve_requesting_user()`` (as for the Gateway's images)."""
    monkeypatch.setattr(
        image_service, "resolve_requesting_user", lambda: "fallback-user@example.com"
    )
    install_runtime(monkeypatch, FakeRuntime(architect=_discuss()))

    _run(graph_env, turn_state(graph_env, initiated_by=initiated_by))

    (context,) = image_tools.contexts
    assert context.owner == (USER if initiated_by else "fallback-user@example.com")


def test_the_retry_gets_a_fresh_tool_holding_what_is_left(
    graph_env, monkeypatch, images_on, image_tools
):
    """Attempt 1 generates 3 images (1 call) and is refused with a retryable code; the
    retry is handed a NEW tool holding the rest of the turn's budget (1 call, 3
    images), and the pass records both attempts' spending once."""
    refused = architect_build(make_spec((0, 1), slide_type="title"))
    good = architect_build(make_spec((0, 1)))

    def first(call):
        _generate(call, count=3)
        return refused

    def second(call):
        assert "rejected_edit" in call.payload
        return good

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=[first, second]))

    t = _run(graph_env, turn_state(graph_env))

    attempt1, attempt2 = runtime.calls_for("architect")
    assert attempt1.at_start[0] == 2
    assert attempt2.tool_names == [IMAGE_TOOL]
    assert attempt2.at_start[0] == 1
    first_tool, second_tool = image_tools.built
    assert second_tool is not first_tool
    assert (second_tool.context.calls_left, second_tool.context.images_left) == (1, 3)
    (entry,) = _image_vals(t.updates, "image_tool_usage")
    assert (entry["calls"], entry["images"]) == (1, 3)
    assert t.updates["architect_intent"] == "build"
    assert t.updates["error_state"] is None


# ===========================================================================
# Beside the Gateway's tools
# ===========================================================================


def test_gateway_and_image_tools_ride_one_toolset(graph_env, monkeypatch, images_on, image_tools):
    """A LakeDraw deck with the feature on: one toolset of LakeDraw's tools plus
    ``generate_image``, whose call cap is the Gateway's 12 plus the image tool's 2; the
    turn records both kinds of usage."""
    _lakedraw_deck(graph_env, monkeypatch)
    runtime = install_runtime(
        monkeypatch, FakeRuntime(architect=architect_build(make_spec((0, 1))))
    )

    t = _run(graph_env, turn_state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert call.tool_names == sorted([CREATE, EXPORT, IMAGE_TOOL])
    assert call.at_start[0] == 12 + 2
    assert image_tools.built[-1] in call.toolset.tools
    (gateway_entry,) = _usage_vals(t.updates)
    assert gateway_entry["calls"] == 0
    (image_entry,) = _image_vals(t.updates, "image_tool_usage")
    assert (image_entry["calls"], image_entry["images"]) == (0, 0)
    assert t.updates["error_state"] is None


def test_image_seconds_are_not_charged_to_the_gateway_budget(
    graph_env, monkeypatch, images_on, image_tools
):
    """One LakeDraw call and one 0.6 s image call on the same toolset: the Gateway's
    ``seconds`` is what ITS tools spent (about nothing), the image tool's is the 0.6 s."""
    _lakedraw_deck(graph_env, monkeypatch)
    image_tools.delay = 0.6

    def answer(call):
        call.use(CREATE, {"diagram_data": {"n": 1}})
        _generate(call, count=1)
        return architect_build(make_spec((0, 1)))

    install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _run(graph_env, turn_state(graph_env))

    (gateway_entry,) = _usage_vals(t.updates)
    assert gateway_entry["calls"] == 1
    assert gateway_entry["seconds"] < 0.3, gateway_entry
    (image_entry,) = _image_vals(t.updates, "image_tool_usage")
    assert image_entry["calls"] == 1
    assert image_entry["seconds"] >= 0.6, image_entry


# ===========================================================================
# Fallback: a call that carried the image tool and raised
# ===========================================================================


@pytest.mark.parametrize(
    "make_error", [_pinned_error, _loop_gave_up], ids=["provider-refuses", "loop-gives-up"]
)
def test_a_failed_image_bound_call_is_made_again_without_tools(
    graph_env, monkeypatch, images_on, image_tools, make_error
):
    """The call that carried only ``generate_image`` raises (the provider refused it, or
    the tool loop gave up): it is made ONCE more with no toolset and the same payload,
    and the turn commits that answer."""
    spec = make_spec((0, 1))

    def bound(call):
        raise make_error()

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=[bound, architect_build(spec)]))

    t = _run(graph_env, turn_state(graph_env))

    first, second = runtime.calls_for("architect")
    assert first.tool_names == [IMAGE_TOOL]
    assert second.context.toolset is None
    assert second.payload == first.payload
    assert t.updates["architect_intent"] == "build"
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None


def test_after_a_failed_image_bound_call_the_pass_binds_the_tool_no_more(
    graph_env, monkeypatch, images_on, image_tools
):
    """Once a call with the tool has failed, the pass's later attempts are today's
    calls: the fallback's answer is refused (retryable) and the retry carries no
    toolset."""

    def bound(call):
        raise _pinned_error()

    refused = architect_build(make_spec((0, 1), slide_type="title"))
    good = architect_build(make_spec((0, 1)))
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=[bound, refused, good]))

    t = _run(graph_env, turn_state(graph_env))

    calls = runtime.calls_for("architect")
    assert [call.tool_names for call in calls] == [[IMAGE_TOOL], [], []]
    assert "rejected_edit" in calls[2].payload
    assert t.updates["architect_intent"] == "build"
    assert t.updates["error_state"] is None


def test_a_call_without_the_image_tool_still_fails_the_turn(
    graph_env, monkeypatch, images_on, image_tools
):
    """The image budget is spent, so the call carries no tool: a failure is not the
    image pass's to handle, and it fails the turn exactly as today (one call)."""
    spent = scoped(TURN, [{"calls": 2, "images": 6, "seconds": 100.0}])

    def fails(call):
        raise _pinned_error()

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=fails))

    with pytest.raises(type(_pinned_error())):
        _run(graph_env, turn_state(graph_env, image_tool_usage=spent))

    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None


def test_a_failed_call_carrying_both_kinds_of_tools_is_handed_to_both(
    graph_env, monkeypatch, images_on, image_tools
):
    """The call carried LakeDraw's tools AND ``generate_image`` and raised.  BOTH passes
    must be told (``gw.without_tools(...) | images.without_tools(...)``): the user hears
    once that LakeDraw is unavailable (the Gateway pass ran), and the retry after the
    fallback's refused answer carries neither kind of tool (the image pass ran too).  A
    short-circuiting ``or``, in either order, leaves one of the two undone."""
    _lakedraw_deck(graph_env, monkeypatch)

    def bound(call):
        raise _pinned_error()

    refused = architect_build(make_spec((0, 1), slide_type="title"))
    good = architect_build(make_spec((0, 1)))
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=[bound, refused, good]))

    t = _run(graph_env, turn_state(graph_env))

    calls = runtime.calls_for("architect")
    assert [call.tool_names for call in calls] == [sorted([CREATE, EXPORT, IMAGE_TOOL]), [], []]
    assert t.info.count(_tools_failed("LakeDraw")) == 1
    assert t.updates["architect_intent"] == "build"
    assert t.updates["error_state"] is None


# ===========================================================================
# Progress: one row and one top-level event per call
# ===========================================================================


def test_one_progress_row_and_one_top_level_event_per_image_call(
    graph_env, monkeypatch, images_on, image_tools
):
    """One call for 3 illustrations: exactly one ``tool_call`` row, written before the
    images are generated, with ``tool_name="image_generation"`` and
    ``tool_input={"kind", "count"}`` (never the model's prompt); exactly one ``TOOL_CALL``
    event naming the same tool and input at the TOP level (what the frontend reads);
    and the polling transport's event carries them too."""
    sm = get_session_manager()
    rows_at_generate: List[int] = []
    image_tools.on_generate = lambda: rows_at_generate.append(
        len([m for m in sm.get_messages(graph_env.session_id) if m["message_type"] == "tool_call"])
    )
    secret = "PROMPT-SENTINEL-4c1e"

    def answer(call):
        _generate(call, count=3, kind="illustration", prompt="An image of " + secret)
        return _discuss("Here are three options.")

    install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _run(graph_env, turn_state(graph_env))

    tool_input = {"kind": "illustration", "count": 3}
    (row,) = [r for r in t.rows if r["message_type"] == "tool_call"]
    assert row["role"] == "assistant"
    assert row["metadata"] == {"tool_name": PROGRESS_TOOL, "tool_input": tool_input}
    assert re.search(r"\b3\b", row["content"]) and "illustration" in row["content"], row
    assert rows_at_generate == [1]
    (event,) = [e for e in t.events if e.type == StreamEventType.TOOL_CALL]
    assert (event.tool_name, event.tool_input) == (PROGRESS_TOOL, tool_input)
    assert (event.metadata or {}).get("node") == "architect"
    for text in (row["content"], json.dumps(row["metadata"]), event.model_dump_json()):
        assert secret not in text
    polled = [
        sm.msg_to_stream_event(m)
        for m in sm.get_messages_for_request(REQUEST_ID)
        if m["message_type"] == "tool_call"
    ]
    assert [(p["type"], p["tool_name"], p["tool_input"]) for p in polled] == [
        ("tool_call", PROGRESS_TOOL, tool_input)
    ]


# ===========================================================================
# State: what the turn records
# ===========================================================================


def test_the_turn_records_its_refs_and_usage_turn_scoped(
    graph_env, monkeypatch, images_on, image_tools
):
    """``generated_images`` is exactly the tool's R3 refs (``{token, kind, option,
    prompt, for_slide}``, no ``slides``: the node adds those only to the metadata) and
    ``image_tool_usage`` one ``{calls, images, seconds}`` entry for the pass, both
    wrapped for THIS turn; folded into state, the next pass reads them back."""

    def answer(call):
        _generate(call, count=3, for_slide=2)
        return _discuss()

    install_runtime(monkeypatch, FakeRuntime(architect=answer))
    state = turn_state(graph_env)

    t = _run(graph_env, state)

    (tool,) = image_tools.built
    assert t.updates["generated_images"] == scoped(TURN, tool.generated)
    assert [ref_["option"] for ref_ in tool.generated] == [1, 2, 3]
    (entry,) = _image_vals(t.updates, "image_tool_usage")
    assert set(entry) == USAGE_KEYS
    assert (entry["calls"], entry["images"]) == (1, 3)
    assert isinstance(entry["seconds"], (int, float)) and 0 <= entry["seconds"] < 30
    json.dumps(t.updates["generated_images"])
    json.dumps(t.updates["image_tool_usage"])
    folded = fold(state, t.updates)
    assert scoped_vals(folded, "generated_images") == tool.generated
    assert scoped_vals(folded, "image_tool_usage") == [entry]


@pytest.mark.parametrize("path", ["ask_data", "refused", "build"])
def test_the_image_keys_are_written_on_every_return_path(
    graph_env, monkeypatch, images_on, image_tools, path
):
    """The ask_data return, the refusal (``_degrade_edit``) return and the committed
    build all carry what the pass generated and spent."""
    refused = architect_build(make_spec((0, 1), slide_type="title"))
    outputs = {
        "ask_data": ArchitectOutput(
            intent="ask_data", message="I need the figures first.",
            data_request=DataRequest(metric="throughput"),
        ),
        "refused": refused,
        "build": architect_build(make_spec((0, 1))),
    }

    def first(call):
        _generate(call, count=2)
        return outputs[path]

    install_runtime(monkeypatch, FakeRuntime(architect=[first, outputs[path]]))

    t = _run(graph_env, turn_state(graph_env))

    if path == "refused":
        assert t.updates["error_state"] is not None
    generated = [ref_ for tool in image_tools.built for ref_ in tool.generated]
    assert len(generated) == 2
    assert _image_vals(t.updates, "generated_images") == generated
    usage = _image_vals(t.updates, "image_tool_usage")
    assert len(usage) == 1
    assert (usage[0]["calls"], usage[0]["images"]) == (1, 2)


# ===========================================================================
# What the turn reports: discuss with options
# ===========================================================================


def test_a_discuss_turn_with_three_options_carries_them_on_its_reply(
    graph_env, monkeypatch, images_on, image_tools
):
    """"Make me a picture": 3 options, then a discussion.  The reply's row AND its
    ASSISTANT event carry ``generated_images``: 3 entries in the shared shape, options
    1-3, none on a slide, the prompt capped at 300 characters.  The model wrote one
    option's reference in its message; the user is shown "option 2", never a token."""
    get_session_manager().add_message(
        graph_env.session_id, role="user",
        content="Make me a picture to get slide 2's message across.", message_type="user_query",
    )

    def answer(call):
        _generate(call, count=3, kind="illustration", prompt=LONG_PROMPT)
        second = image_tools.made[1]
        return _discuss(
            "Here are three takes on it. I would pick " + ref(second) + " for slide 2."
        )

    install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _run(graph_env, turn_state(graph_env))

    a, b, c = image_tools.made
    (row,) = _llm_rows(t)
    entries = row["metadata"]["generated_images"]
    assert _meta(entries) == [
        (a, "illustration", 1, None, []),
        (b, "illustration", 2, None, []),
        (c, "illustration", 3, None, []),
    ]
    for entry in entries:
        assert set(entry) == METADATA_KEYS
        assert 0 < len(entry["prompt"]) <= 300
        assert entry["prompt"][:200] == LONG_PROMPT[:200]
    (event,) = _architect_events(t)
    assert event.metadata["generated_images"] == entries
    assert event.metadata["intent"] == "discuss"
    for said in (row["content"], event.content):
        assert "{{image:" not in said
        assert all(token not in said for token in (a, b, c))
        assert "option 2" in said.lower()
    assert len(IMAGE_PLACEHOLDER_PATTERN.findall(row["content"])) == 0


# ===========================================================================
# What the turn reports: an edit that places an option
# ===========================================================================


def test_an_edit_placing_option_1_on_slide_2(graph_env, monkeypatch, images_on, image_tools):
    """3 icon options for slide 2; the edit places option 1 in slide 2's brief.  The
    reply's metadata says option 1 is on slide 2 and the others are on none; with NO
    Gateway, slide 2's builder payload carries the allow-list holding the turn's
    generated tokens, and an invented reference in the built HTML is removed with the
    generated-image notice (once, for slide 2), the placed one kept."""
    prior = _three_committed_slides(graph_env)
    brief = {}

    def answer(call):
        _generate(call, count=3, kind="icon", for_slide=2)
        a = image_tools.made[0]
        brief[1] = "Shield icon " + ref(a) + ", top right, 120px."
        return ArchitectOutput(
            intent="edit", message="Adding option 1 to slide 2.",
            deck_spec=with_slides(prior, content_brief=brief), target_positions=[1],
        )

    install_runtime(monkeypatch, FakeRuntime(architect=answer))
    state = turn_state(graph_env)

    t = _run(graph_env, state)

    a, b, c = image_tools.made
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [1]
    assert t.updates["deck_spec"].slide_at(1).content_brief == brief[1]
    (row,) = _llm_rows(t)
    assert _meta(row["metadata"]["generated_images"]) == [
        (a, "icon", 1, 2, [2]),
        (b, "icon", 2, 2, []),
        (c, "icon", 3, 2, []),
    ]
    (event,) = _architect_events(t)
    assert event.metadata["generated_images"] == row["metadata"]["generated_images"]
    assert t.info == []

    payload = build_branch_payload(fold(state, t.updates), 1)
    known = payload["gateway_known_images"]
    json.dumps(known)  # JSON-native: a list, never a set
    assert {a, b, c} <= set(known)
    assert INVENTED not in known

    kept = '<img src="' + ref(a) + '" alt="shield" />'
    html = '<div class="slide"><h2>Plan</h2>' + kept + '<img src="' + ref(INVENTED) + '"/></div>'
    built, notices, builder_call = _builder_run(graph_env, monkeypatch, payload, html)

    assert kept in built and INVENTED not in built
    assert nodes._IMAGE_NOT_PLACED_GENERATED == GENERATED_NOT_PLACED
    assert notices == [GENERATED_NOT_PLACED.format(n=2)]
    assert "gateway_known_images" not in builder_call.payload


# ===========================================================================
# Canonical numbering: slides come from the committed, canonical spec
# ===========================================================================


def _seed_insert_case(env, case: str):
    """The deck an insert case starts from: built ``0..2``, or gapped ``[0, 2, 5]``."""
    if case.startswith("operations"):
        return _three_committed_slides(env)
    _seed_rows(env, GAPPED)
    prior = make_spec((0, 2, 5))
    _persist(env, prior)
    return prior


def _insert_answer(case: str, prior, token_brief: str) -> ArchitectOutput:
    """An edit adding one slide whose brief places the token: the operations form, or
    a full spec over the gapped deck whose model numbering is not the canonical one."""
    if case.startswith("operations"):
        content = SlideContent(
            purpose="purpose NEW", content_brief=token_brief, assumes="assumes NEW",
            hands_off="hands-off NEW", data_references=[],
        )
        return ArchitectOutput(
            intent="edit", message="Adding a slide after slide 1.",
            operations=[SlideOperation(op="insert", after_position=0, slides=[content])],
        )
    a, b, c = prior.slides
    new: SlideSpec = _new().model_copy(update={"content_brief": token_brief})
    if case == "full-spec-insert-after-slide-1-listed-last":
        placed = [(0, a), (2, b), (5, c), (1, new)]
    else:  # full-spec-insert-after-slide-2-old-numbers
        placed = [(0, a), (2, b), (3, new), (5, c)]
    return ArchitectOutput(
        intent="edit", message="Adding a slide.",
        deck_spec=_spec_of(prior, placed), target_positions=[1],
    )


@pytest.mark.parametrize(
    ("case", "slide"),
    [
        ("operations-insert-after-slide-1", 2),
        ("full-spec-insert-after-slide-1-listed-last", 2),
        ("full-spec-insert-after-slide-2-old-numbers", 3),
    ],
)
def test_an_insert_carrying_a_generated_image_reports_its_canonical_slide(
    graph_env, monkeypatch, images_on, image_tools, case, slide
):
    """``slides`` is the 1-based index in the COMMITTED spec: after the operations are
    composed and the insert re-stamped.  Over the gapped deck ``[0, 2, 5]`` the model's
    own numbering (list order, or ``position + 1``) gives another number."""
    prior = _seed_insert_case(graph_env, case)

    def answer(call):
        _generate(call, count=1, for_slide=slide)
        (token,) = image_tools.made
        return _insert_answer(case, prior, "New slide with " + ref(token) + ".")

    install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _run(graph_env, turn_state(graph_env))

    (token,) = image_tools.made
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert ref(token) in t.updates["deck_spec"].slide_at(slide - 1).content_brief
    (row,) = _llm_rows(t)
    (entry,) = row["metadata"]["generated_images"]
    assert (entry["token"], entry["slides"]) == (token, [slide])


# ===========================================================================
# Reconciliation on a generated-images turn with no Gateway
# ===========================================================================


def test_a_mistyped_generated_token_is_repaired_without_a_gateway(
    graph_env, monkeypatch, images_on, image_tools
):
    """The model copies the generated token with a mistyped tail into slide 1's brief:
    the committed (and reported) spec has the real token, and the metadata places it on
    slide 1."""

    def answer(call):
        _generate(call, count=1, for_slide=1)
        (token,) = image_tools.made
        spec = with_slides(
            make_spec((0, 1, 2)), content_brief={0: "Hero: " + ref(token[:40] + "xyz")}
        )
        return architect_build(spec)

    install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _run(graph_env, turn_state(graph_env))

    (token,) = image_tools.made
    assert t.updates["deck_spec"].slide_at(0).content_brief == "Hero: " + ref(token)
    (row,) = _llm_rows(t)
    (entry,) = row["metadata"]["generated_images"]
    assert (entry["token"], entry["slides"]) == (token, [1])


def test_an_invented_ref_on_a_generated_turn_is_removed_and_said_as_generated(
    graph_env, monkeypatch, images_on, image_tools
):
    """The same turn invents a reference on slide 3: it is removed from the committed
    spec, and the user is told once, in the generated-image wording (no Gateway ran)."""

    def answer(call):
        _generate(call, count=1, for_slide=1)
        (token,) = image_tools.made
        spec = with_slides(
            make_spec((0, 1, 2)),
            content_brief={0: "Hero: " + ref(token), 2: "Logo: " + ref(INVENTED) + "."},
        )
        return architect_build(spec)

    install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _run(graph_env, turn_state(graph_env))

    (token,) = image_tools.made
    committed = t.updates["deck_spec"]
    assert committed.slide_at(0).content_brief == "Hero: " + ref(token)
    assert committed.slide_at(2).content_brief == "Logo: ."
    assert t.info == [GENERATED_NOT_PLACED.format(n=3)]
    assert not any(text.startswith(GATEWAY_NOT_PLACED_PREFIX) for text in t.info)


def test_a_bound_but_unused_tool_changes_nothing(graph_env, monkeypatch, images_on, image_tools):
    """The tool is bound and never called: exactly today's turn.  An invented reference
    in a brief is kept (no reconciliation), nobody is told anything, the reply carries no
    images, and the builder payload has NO allow-list, so the builder's HTML is left as
    the model wrote it."""
    brief = "Logo: " + ref(INVENTED) + "."
    spec = with_slides(make_spec((0, 1)), content_brief={0: brief})
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=architect_build(spec)))
    state = turn_state(graph_env)

    t = _run(graph_env, state)

    (call,) = runtime.calls_for("architect")
    assert call.tool_names == [IMAGE_TOOL]
    assert t.updates["deck_spec"].slide_at(0).content_brief == brief
    assert t.info == []
    assert t.updates["generated_images"] == scoped(TURN, [])
    (row,) = _llm_rows(t)
    assert not (row.get("metadata") or {}).get("generated_images")
    payload = build_branch_payload(fold(state, t.updates), 0)
    assert "gateway_known_images" not in payload
    html = '<div class="slide"><img src="' + ref(INVENTED) + '"/><p>a</p></div>'
    built, notices, _ = _builder_run(graph_env, monkeypatch, payload, html)
    assert built == html
    assert notices == []


# ===========================================================================
# The next turn: the options are replayed as a system note
# ===========================================================================


def test_the_next_turn_replays_the_options_as_a_system_note(
    graph_env, monkeypatch, images_on, image_tools
):
    """Turn 1 shows 3 options; turn 2's architect reads, right after that reply, a
    ``system`` turn listing all three by option number and exact reference, so "use the
    second one" can be answered."""
    get_session_manager().add_message(
        graph_env.session_id, role="user", content="Make me a picture.", message_type="user_query",
    )

    def first_turn(call):
        _generate(call, count=3)
        return _discuss("Here are three options.")

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=[first_turn, _discuss("Sure.")]))

    _run(graph_env, turn_state(graph_env))
    _run(graph_env, turn_state(graph_env, turn_id="turn-2"))

    a, b, c = image_tools.made
    conversation = runtime.calls_for("architect")[1].payload["conversation"]
    (index,) = [
        i for i, turn in enumerate(conversation)
        if turn["role"] == "assistant" and turn["content"] == "Here are three options."
    ]
    note = conversation[index + 1]
    assert note["role"] == "system"
    for option, token in enumerate((a, b, c), start=1):
        assert ref(token) in note["content"]
        assert f"option {option}" in note["content"].lower()
    assert [turn["role"] for turn in conversation] == ["user", "assistant", "system"]


def _seed_reply(env, metadata: Any) -> None:
    sm = get_session_manager()
    sm.add_message(env.session_id, role="user", content="A picture, please.",
                   message_type="user_query")
    sm.add_message(env.session_id, role="assistant", content="Here you go.",
                   message_type="llm_response", metadata=metadata)


@pytest.mark.parametrize(
    "value",
    [
        "a string",
        {"token": "abc_DEF-1", "kind": "illustration", "option": 1, "slides": []},
        [1, "x", None, []],
        [{"token": "not a token!", "kind": "illustration", "option": 1, "slides": []}],
        [{"token": "abc_DEF-1", "kind": "painting", "option": 1, "slides": []}],
        [{"token": "abc_DEF-1", "kind": "illustration", "option": 0, "slides": []}],
        [{"kind": "illustration", "option": 1}],
    ],
    ids=["string", "dict", "junk-list", "bad-token", "bad-kind", "bad-option", "no-token"],
)
def test_malformed_generated_images_metadata_gives_no_note(graph_env, value):
    """A stored row's ``generated_images`` that is not a list of valid entries replays
    as the assistant turn alone: no note, and no exception."""
    _seed_reply(graph_env, {"generated_images": value})

    turns = nodes._conversation(graph_env.session_id)

    assert [turn["role"] for turn in turns] == ["user", "assistant"]


def test_a_partly_malformed_list_replays_only_its_valid_entries(graph_env):
    """Junk entries are dropped (the shared sanitiser's rules); the valid one is noted."""
    good = "abc_DEF-1234567890"
    _seed_reply(
        graph_env,
        {
            "generated_images": [
                {"token": "not a token!", "kind": "illustration", "option": 1, "slides": []},
                {"token": good, "kind": "icon", "option": 2, "prompt": "a shield",
                 "for_slide": 3, "slides": [3]},
                "junk",
            ]
        },
    )

    turns = nodes._conversation(graph_env.session_id)

    assert [turn["role"] for turn in turns] == ["user", "assistant", "system"]
    note = turns[2]["content"]
    assert ref(good) in note
    assert "not a token!" not in note


# ===========================================================================
# A refused edit keeps its images
# ===========================================================================


def test_a_refused_edit_after_generating_keeps_its_images_on_the_refusal_row(
    graph_env, monkeypatch, images_on, image_tools
):
    """The edit generates 3 options and is refused twice (it would drop a slide): the
    only reply is the refusal, and its row records both why (``architect_refusal``) and
    the images the user can still see and use (none on a slide)."""
    prior = _three_committed_slides(graph_env)
    shrink = ArchitectOutput(
        intent="edit", message="Editing.",
        deck_spec=with_slides(make_spec((0, 1)), content_brief={1: "revised brief-1"}),
        target_positions=[1],
    )

    def first(call):
        _generate(call, count=3, for_slide=2)
        return shrink

    install_runtime(monkeypatch, FakeRuntime(architect=[first, shrink]))

    t = _run(graph_env, turn_state(graph_env))

    assert t.updates["error_state"] is not None
    assert t.updates["architect_intent"] == "discuss"
    assert _persisted_spec(graph_env) == prior  # nothing in the deck changed
    a, b, c = image_tools.made
    (row,) = _llm_rows(t)
    assert isinstance(row["metadata"][REFUSAL_METADATA_KEY], dict)
    assert _meta(row["metadata"]["generated_images"]) == [
        (a, "illustration", 1, 2, []),
        (b, "illustration", 2, 2, []),
        (c, "illustration", 3, 2, []),
    ]
