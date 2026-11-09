# ruff: noqa: F811 — the graph_env fixture is imported, then requested by name.
"""Chat image generation: the budget and numbering rulings the controller pins (R9, R11).

* **R9.**  The Gateway's tools do not count their own calls: the toolset does.  On a
  merged toolset (Gateway tools plus ``generate_image``) the toolset's cap is the
  Gateway's 12 plus the image tool's 2, so without a guard the model could make a 13th
  and a 14th Gateway call.  Every Gateway tool on a merged toolset shares one counter
  that refuses a call once the Gateway's own calls are used up: no 13th MCP call is
  made, the pass records 12 Gateway calls, and the image tool still works.
* **R11.**  Options are numbered per turn: the tool's ``first_option`` is 1 plus the
  images this turn already generated (earlier passes' ``image_tool_usage``, then the
  earlier attempts of the same pass), so one reply never shows two "Option 1"s.

The seams and fakes are ``test_graph_image_tool``'s (``nodes.ImageGenerationAgentTool``
replaced by a fake honouring the real ``ImageToolContext``).
"""

from __future__ import annotations

import pytest

from src.domain.skill_io import ArchitectOutput
from src.services.graph import nodes
from src.services.graph.state import scoped
from src.services.image_generation import ENV_FLAG
from tests.fixtures.graph_tool_runtime import (
    FakeRuntime,
    install_runtime,
    ref,
    turn_state,
    with_slides,
)
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    graph_env,
    make_spec,
)
from tests.unit.test_graph_gateway_mcp import CREATE, _lakedraw_deck, _usage_vals
from tests.unit.test_graph_image_tool import (  # noqa: F401 — images_on, image_tools are fixtures
    IMAGE_TOOL,
    TURN,
    _discuss,
    _generate,
    _image_vals,
    _llm_rows,
    _meta,
    _run,
    _seed_reply,
    _three_committed_slides,
    image_tools,
    images_on,
)

pytestmark = pytest.mark.image_tool


def _architect_gateway_calls(updates) -> int:
    return sum(entry["calls"] for entry in _usage_vals(updates) if entry["agent"] == "architect")


def test_a_merged_toolset_keeps_the_gateways_own_call_cap(
    graph_env, monkeypatch, images_on, image_tools
):
    """R9: 13 LakeDraw calls on a merged toolset (cap 12 + 2): the 13th is refused
    with a budget text and never reaches the service; the image tool, which keeps its
    own budget, still generates after it."""
    lakedraw = _lakedraw_deck(graph_env, monkeypatch)
    seen = {}

    def answer(call):
        texts = [call.use(CREATE, {"diagram_data": {"n": n}}) for n in range(13)]
        seen["gateway"] = texts
        seen["image"] = _generate(call, count=1)
        return architect_build(make_spec((0, 1)))

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _run(graph_env, turn_state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert call.at_start[0] == 12 + 2
    assert len(lakedraw.calls) == 12
    thirteenth = seen["gateway"][12]
    assert "budget" in thirteenth.lower(), thirteenth
    assert f"{CREATE} done" not in thirteenth
    assert all(f"{CREATE} done" in text for text in seen["gateway"][:12])
    assert _architect_gateway_calls(t.updates) == 12
    assert "Generated 1 of 1" in seen["image"], seen["image"]
    (image_entry,) = _image_vals(t.updates, "image_tool_usage")
    assert (image_entry["calls"], image_entry["images"]) == (1, 1)
    assert t.updates["error_state"] is None


def test_a_later_merged_toolset_lets_only_the_gateways_last_call_through(
    graph_env, monkeypatch, images_on, image_tools
):
    """R9, a later pass: 11 Gateway calls already made this turn, so the Gateway has 1
    left; a merged toolset (cap 1 + 2) lets exactly one more LakeDraw call through."""
    lakedraw = _lakedraw_deck(graph_env, monkeypatch)
    prior = scoped(TURN, [{"agent": "architect", "calls": 11, "seconds": 10.0, "notified": []}])
    seen = {}

    def answer(call):
        seen["gateway"] = [call.use(CREATE, {"diagram_data": {"n": n}}) for n in range(3)]
        return architect_build(make_spec((0, 1)))

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _run(graph_env, turn_state(graph_env, gateway_usage=prior))

    (call,) = runtime.calls_for("architect")
    assert IMAGE_TOOL in call.tool_names and CREATE in call.tool_names
    assert call.at_start[0] == 1 + 2
    assert len(lakedraw.calls) == 1
    assert f"{CREATE} done" in seen["gateway"][0]
    for text in seen["gateway"][1:]:
        assert f"{CREATE} done" not in text
        assert "budget" in text.lower(), text
    assert t.updates["error_state"] is None


@pytest.mark.parametrize(
    ("prior", "first_option"),
    [
        ([], 1),
        ([{"calls": 1, "images": 3, "seconds": 20.0}], 4),
        ([{"calls": 1, "images": 2, "seconds": 20.0}], 3),
    ],
    ids=["first-pass", "after-3", "after-2"],
)
def test_options_are_numbered_from_what_this_turn_already_generated(
    graph_env, monkeypatch, images_on, image_tools, prior, first_option
):
    """R11: a later pass in the turn numbers its options after the earlier passes'."""
    install_runtime(monkeypatch, FakeRuntime(architect=_discuss()))

    _run(graph_env, turn_state(graph_env, image_tool_usage=scoped(TURN, prior)))

    (context,) = image_tools.contexts
    assert context.first_option == first_option


def test_options_from_an_earlier_turn_do_not_shift_the_numbering(
    graph_env, monkeypatch, images_on, image_tools
):
    install_runtime(monkeypatch, FakeRuntime(architect=_discuss()))
    stale = scoped("turn-0", [{"calls": 1, "images": 3, "seconds": 20.0}])

    _run(graph_env, turn_state(graph_env, image_tool_usage=stale))

    (context,) = image_tools.contexts
    assert context.first_option == 1


def test_the_retry_numbers_its_options_after_the_first_attempts(
    graph_env, monkeypatch, images_on, image_tools
):
    """R11 within one pass: attempt 1 generates 3 and is refused with a retryable code;
    the retry's fresh tool numbers from 4."""
    refused = architect_build(make_spec((0, 1), slide_type="title"))
    good = architect_build(make_spec((0, 1)))

    def first(call):
        _generate(call, count=3)
        return refused

    install_runtime(monkeypatch, FakeRuntime(architect=[first, good]))

    _run(graph_env, turn_state(graph_env))

    first_tool, second_tool = image_tools.built
    assert first_tool.context.first_option == 1
    assert second_tool.context.first_option == 4


def test_slide_numbers_follow_positions_not_the_order_the_model_listed_them(
    graph_env, monkeypatch, images_on, image_tools
):
    """The model may list a spec's slides in any order (positions are unique, not
    sorted).  An image placed on position 1 is "on slide 2" however the list runs."""
    prior = _three_committed_slides(graph_env)

    def answer(call):
        _generate(call, count=1, kind="icon", for_slide=2)
        (token,) = image_tools.made
        spec = with_slides(prior, content_brief={1: "Shield icon " + ref(token) + ", top right."})
        shuffled = spec.model_copy(update={"slides": list(reversed(spec.slides))})
        return ArchitectOutput(
            intent="edit", message="Adding it to slide 2.",
            deck_spec=shuffled, target_positions=[1],
        )

    install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _run(graph_env, turn_state(graph_env))

    (token,) = image_tools.made
    assert t.updates["error_state"] is None
    (row,) = _llm_rows(t)
    assert _meta(row["metadata"]["generated_images"]) == [(token, "icon", 1, 2, [2])]


# ---------------------------------------------------------------------------
# R16: with no image tool, a conversation that showed images says so
# ---------------------------------------------------------------------------
# Found live: with the admin switch off, a session whose earlier replies showed
# generated options got "I made three picture options ... shown below this reply"
# with no tool bound and nothing generated.  The model copied the conversation.

_OPTIONS = {
    "generated_images": [
        {"token": "tokA_1", "kind": "illustration", "option": 1, "for_slide": 2, "slides": []},
        {"token": "tokB_2", "kind": "illustration", "option": 2, "for_slide": 2, "slides": []},
    ]
}


def _off_notes(conversation):
    return [
        turn for turn in conversation
        if turn["role"] == "system" and turn["content"] == nodes._IMAGE_TOOL_OFF_NOTE
    ]


@pytest.mark.parametrize("switch", ["env-off", "gate-false"])
def test_without_the_tool_a_conversation_that_showed_images_is_told_it_cannot_make_more(
    graph_env, monkeypatch, images_on, image_tools, switch
):
    """The note is the conversation's LAST turn (after the replayed options note), and
    it says new images cannot be made this turn."""
    if switch == "env-off":
        monkeypatch.setenv(ENV_FLAG, "0")
    else:
        monkeypatch.setattr(nodes, "_image_generation_available", lambda: False)
    _seed_reply(graph_env, _OPTIONS)
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=_discuss("Sure.")))

    _run(graph_env, turn_state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    conversation = call.payload["conversation"]
    assert conversation[-1]["role"] == "system"
    assert conversation[-1]["content"] == nodes._IMAGE_TOOL_OFF_NOTE
    assert len(_off_notes(conversation)) == 1
    note = nodes._IMAGE_TOOL_OFF_NOTE.lower()
    assert "not available" in note
    assert "image library" in note


def test_with_the_tool_bound_no_off_note_is_added(graph_env, monkeypatch, images_on, image_tools):
    _seed_reply(graph_env, _OPTIONS)
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=_discuss("Sure.")))

    _run(graph_env, turn_state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert call.tool_names == [IMAGE_TOOL]
    assert _off_notes(call.payload["conversation"]) == []


def test_without_image_history_the_conversation_is_unchanged(
    graph_env, monkeypatch, images_on, image_tools
):
    """A session that never showed generated images: no note, exactly today's payload."""
    monkeypatch.setenv(ENV_FLAG, "0")
    _seed_reply(graph_env, None)
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=_discuss("Sure.")))

    _run(graph_env, turn_state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert [turn["role"] for turn in call.payload["conversation"]] == ["user", "assistant"]

