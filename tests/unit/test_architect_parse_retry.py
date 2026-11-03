# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""The architect's first answer that does not parse is asked for once more.

A turn's first architect call whose answer the structured-output parser rejects
(a pydantic ``ValidationError``, such as ``deck_style`` returned at the top level of
ArchitectOutput instead of inside ``deck_spec``, or an ``OutputParserException``)
failed the user's turn outright, while the builder, build reviewer and fixer each
retry an unparseable answer once.  Measured on the eval harness (2026-11-03): 1 of 13
architect builds was rejected this way.

* **One more call.**  The same call is made once more, with the same payload, and
  that answer is the turn's.
* **Bounded.**  A second unparseable answer fails the turn as before: two calls,
  never three.
* **Only parse errors.**  Any other failure (the endpoint, a timeout) fails the turn
  on the first call, as it always has.
* **Not a describe-only turn.**  The arc-review sweeper's turn is addressed to nobody
  and builds nothing, so it is never asked again (the same rule as the edit retry).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List

import pytest
from langchain_core.exceptions import OutputParserException
from pydantic import ConfigDict, ValidationError

from src.domain.skill_io import ArchitectOutput
from src.services.graph import nodes
from src.services.graph.nodes import architect_node
from src.services.graph.state import scoped
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    graph_env,
    make_spec,
)

TURN = "turn-1"


class _StrictArchitectOutput(ArchitectOutput):
    """ArchitectOutput as the runtime composes it: ``extra="forbid"`` (agent_schema_registry
    ``compose``), so an unknown top-level key is a ValidationError, as in production."""

    model_config = ConfigDict(**{**ArchitectOutput.model_config, "extra": "forbid"})


def _misplaced_deck_style() -> ValidationError:
    """The held-out failure: ``deck_style`` at the top level of ArchitectOutput."""
    try:
        _StrictArchitectOutput.model_validate(
            {
                "intent": "build",
                "message": "Here is a 7-slide starter.",
                "deck_spec": make_spec((0, 1)).model_dump(mode="json"),
                "deck_style": {"css": ".dk-footer { color: red; }", "components": []},
            }
        )
    except ValidationError as exc:
        assert [(e["type"], e["loc"]) for e in exc.errors()] == [
            ("extra_forbidden", ("deck_style",))
        ]
        return exc
    raise AssertionError("ArchitectOutput accepted a top-level deck_style")


def _unparseable_text() -> OutputParserException:
    return OutputParserException("the provider's text is not the output schema")


PARSE_ERRORS = pytest.mark.parametrize(
    "make_error",
    [_misplaced_deck_style, _unparseable_text],
    ids=["validation-error", "output-parser-exception"],
)


def _answers(env, answers: List[Any]) -> None:
    """The architect answers each item in turn; an exception item is raised."""
    queue = list(answers)

    def handler(payload: dict) -> Any:
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    env.skills.set("architect", handler)


@PARSE_ERRORS
def test_an_unparseable_first_answer_is_asked_for_once_more(
    graph_env, caplog, make_error: Callable[[], Exception]
):
    spec = make_spec((0, 1))
    _answers(graph_env, [make_error(), architect_build(spec)])

    with caplog.at_level(logging.WARNING, logger=nodes.__name__):
        updates = architect_node(graph_env.state())

    first, second = graph_env.skills.calls_for("architect")
    assert second["payload"] == first["payload"]
    assert "rejected_edit" not in second["payload"]
    assert updates["architect_intent"] == "build"
    assert updates["deck_spec"].title == spec.title
    assert updates["error_state"] is None
    warned = [
        r
        for r in caplog.records
        if r.name == nodes.__name__
        and r.levelno == logging.WARNING
        and "architect_parse_retry" in r.getMessage()
    ]
    assert len(warned) == 1
    assert type(make_error()).__name__ in warned[0].getMessage()


@PARSE_ERRORS
def test_a_second_unparseable_answer_fails_the_turn(
    graph_env, make_error: Callable[[], Exception]
):
    _answers(graph_env, [make_error(), make_error()])

    with pytest.raises(type(make_error())):
        architect_node(graph_env.state())

    assert len(graph_env.skills.calls_for("architect")) == 2


def test_any_other_failure_fails_the_turn_on_the_first_call(graph_env):
    _answers(
        graph_env,
        [RuntimeError("the model endpoint is down"), architect_build(make_spec((0,)))],
    )

    with pytest.raises(RuntimeError, match="the model endpoint is down"):
        architect_node(graph_env.state())

    assert len(graph_env.skills.calls_for("architect")) == 1


def test_a_describe_only_turn_is_not_asked_again(graph_env):
    _answers(graph_env, [_unparseable_text(), architect_build(make_spec((0,)))])

    with pytest.raises(OutputParserException):
        architect_node(graph_env.state(describe_only=scoped(TURN, True)))

    assert len(graph_env.skills.calls_for("architect")) == 1
