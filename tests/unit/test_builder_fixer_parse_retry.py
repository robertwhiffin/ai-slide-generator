# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""One retry on a builder or fixer parse failure (deck style addendum A, Task B7; RA24 m7).

Before: an ``OutputParserException`` (or a pydantic ``ValidationError``, or the tool
loop's own no-answer failure, which raises ``OutputParserException``) in ``builder_node``
or ``fixer_node`` became a placeholder slide (builder) or the original slide (fixer) at
once.  Now each gets ONE more attempt, in the pattern ``build_reviewer_node`` already
uses (``is_provider_parse_error``): the SAME model payload, and a FRESH brand-search
toolset (a toolset counts its calls, so the retry must not inherit a spent budget).

* a parse failure then a valid answer lands the slide (builder) or the fix (fixer);
* two parse failures fall back exactly as today: the builder placeholds, the fixer
  lands the original;
* any other exception is not retried;
* token usage: neither node records any today (production ``run`` records none; only
  an observed workbench/eval run does), so there is nothing to pin per attempt.

The deck here has a deck style and an active design system whose contract names it,
so every run binds the search and the toolset freshness is observable.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.api.services.slide_repository import is_placeholder_record
from src.domain.deck_spec import DeckStyle, DeckStyleComponent
from src.services.graph import nodes
from src.services.graph.nodes import build_branch_payload, builder_node, fixer_node
from src.services.graph.state import scoped
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    DEFAULT_STYLE,
    builder_out,
    finding,
    fixer_out,
    graph_env,
    make_spec,
)

TURN = "turn-1"
DESIGN_SYSTEM_ID = 7

CALLOUT_STYLE = DeckStyle(
    css=".dk-callout{border-left:4px solid #0b2a4a;padding:12px}",
    components=[
        DeckStyleComponent(
            name="callout",
            class_names=["dk-callout"],
            use="a single takeaway the slide should land",
            example_html="<div class='dk-callout'>Revenue doubled.</div>",
        )
    ],
)

ORIGINAL = "<div class='slide'>original</div>"


def _parse_failure(kind: str) -> Exception:
    from langchain_core.exceptions import OutputParserException

    if kind == "parser":
        return OutputParserException("malformed tool call")
    if kind == "loop_no_answer":
        # The tool loop's own failure (agent_runtime.py: the round limit).
        return OutputParserException(
            "the model did not call the structured-output tool within the round limit"
        )
    from pydantic import ValidationError

    from src.domain.skill_io import BuilderOutput

    try:  # BuilderOutput refuses a <style> element: the schema's ValidationError
        BuilderOutput(position=0, html="<style>p{}</style><p>x</p>", scripts="")
    except ValidationError as exc:
        return exc
    raise AssertionError("a <style> element must not validate")


PARSE_FAILURES = ["parser", "validation", "loop_no_answer"]


class _Runtime:
    """Stands in for ``AgentRuntime``; records each call with its context whole.

    ``answers[agent_key]`` is a list consumed one per call: an exception is raised, any
    other value is returned as the output.  Each call also records how many searches its
    toolset had spent when the call began, then spends the whole budget, so a retry
    handed the same toolset would be seen starting exhausted.
    """

    def __init__(self, answers: Dict[str, List[Any]]) -> None:
        self.answers = {k: list(v) for k, v in answers.items()}
        self.calls: List[SimpleNamespace] = []

    def run(self, agent_key, graph_release_id, payload, assembly_context):
        toolset = assembly_context.toolset
        self.calls.append(
            SimpleNamespace(
                agent_key=agent_key,
                payload=payload,
                context=assembly_context,
                spent_at_start=None if toolset is None else toolset.calls_made,
            )
        )
        if toolset is not None:
            toolset.calls_made = toolset.max_calls
        answer = self.answers[agent_key].pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            answer = answer(payload)
        return SimpleNamespace(output=answer)


def _runtime(monkeypatch, **answers) -> _Runtime:
    runtime = _Runtime(answers)
    monkeypatch.setattr(nodes, "get_agent_runtime", lambda: runtime)
    return runtime


def _branch_payload(env) -> Dict[str, Any]:
    spec = make_spec((0,), design_system_id=DESIGN_SYSTEM_ID)
    state = env.state(
        deck_spec=spec.model_copy(update={"deck_style": CALLOUT_STYLE}),
        design_system_active=True,
        root_session_id=env.session_id,
        actor_session_id=env.session_id,
        resolved_style=DEFAULT_STYLE,
    )
    return build_branch_payload(state, 0)


def _fix_state(env, branch_payload) -> Dict[str, Any]:
    entry = {
        "original_html": ORIGINAL,
        "original_scripts": "",
        "finding": finding("overflow", slide_index=0).model_dump(),
        "findings": [finding("overflow", slide_index=0).model_dump()],
        "payload": {**branch_payload, "html": ORIGINAL, "scripts": ""},
    }
    return env.state(
        turn_id=TURN,
        deck_spec=make_spec((0,)),
        fix_map=scoped(TURN, {0: entry}),
        design_system_active=True,
        root_session_id=env.session_id,
        actor_session_id=env.session_id,
    )


def _assert_a_same_payload_retry_on_a_fresh_toolset(runtime: _Runtime, agent_key: str):
    first, retry = runtime.calls
    assert first.agent_key == retry.agent_key == agent_key
    assert retry.payload == first.payload, "the retry was not handed the same payload"
    assert "corrective_instruction" not in retry.payload
    assert first.context.toolset is not None and retry.context.toolset is not None
    assert retry.context.toolset is not first.context.toolset
    assert [first.spent_at_start, retry.spent_at_start] == [0, 0], (
        "the retry inherited a spent budget"
    )


# ---------------------------------------------------------------------------
# builder_node
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", PARSE_FAILURES)
def test_a_builder_parse_failure_is_retried_once_and_the_slide_lands(graph_env, monkeypatch, kind):
    runtime = _runtime(
        monkeypatch,
        builder=[
            _parse_failure(kind),
            lambda p: builder_out(p, html="<div class='slide'>second</div>"),
        ],
    )

    updates = builder_node(_branch_payload(graph_env))

    _assert_a_same_payload_retry_on_a_fresh_toolset(runtime, "builder")
    assert "placeheld_positions" not in updates
    assert updates["slides"]["vals"][0]["html"] == "<div class='slide'>second</div>"
    assert graph_env.rows() == [], "a retried build wrote a placeholder"


def test_a_builder_that_fails_to_parse_twice_is_placeheld_as_today(graph_env, monkeypatch):
    runtime = _runtime(monkeypatch, builder=[_parse_failure("parser"), _parse_failure("parser")])

    updates = builder_node(_branch_payload(graph_env))

    assert len(runtime.calls) == 2
    assert updates == {"placeheld_positions": scoped(TURN, {0})}
    (row,) = graph_env.rows()
    assert is_placeholder_record(json.loads(row.verification_record))


@pytest.mark.parametrize(
    "error", [RuntimeError("builder exploded"), ValueError("bad value")], ids=["runtime", "value"]
)
def test_any_other_builder_failure_is_not_retried(graph_env, monkeypatch, error):
    runtime = _runtime(monkeypatch, builder=[error, builder_out])

    updates = builder_node(_branch_payload(graph_env))

    assert len(runtime.calls) == 1
    assert updates == {"placeheld_positions": scoped(TURN, {0})}


# ---------------------------------------------------------------------------
# fixer_node
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", PARSE_FAILURES)
def test_a_fixer_parse_failure_is_retried_once_and_the_fix_goes_on(graph_env, monkeypatch, kind):
    runtime = _runtime(
        monkeypatch,
        fixer=[_parse_failure(kind), lambda p: fixer_out(p, html="<div class='slide'>fixed</div>")],
    )

    updates = fixer_node(_fix_state(graph_env, _branch_payload(graph_env)))

    _assert_a_same_payload_retry_on_a_fresh_toolset(runtime, "fixer")
    assert updates["fix_target"] == 0
    assert updates["fixed"]["vals"][0]["html"] == "<div class='slide'>fixed</div>"
    assert "landed_positions" not in updates
    assert graph_env.rows() == [], "a retried fix landed the original"


def test_a_fixer_that_fails_to_parse_twice_lands_the_original_as_today(graph_env, monkeypatch):
    runtime = _runtime(monkeypatch, fixer=[_parse_failure("parser"), _parse_failure("parser")])

    updates = fixer_node(_fix_state(graph_env, _branch_payload(graph_env)))

    assert len(runtime.calls) == 2
    assert updates["fix_target"] is None
    assert updates["fix_map"] == scoped(TURN, {0: None})
    assert updates["landed_positions"] == scoped(TURN, {0})
    assert [row.html for row in graph_env.rows()] == [ORIGINAL]


@pytest.mark.parametrize(
    "error", [RuntimeError("fixer exploded"), ValueError("bad value")], ids=["runtime", "value"]
)
def test_any_other_fixer_failure_is_not_retried(graph_env, monkeypatch, error):
    runtime = _runtime(monkeypatch, fixer=[error, fixer_out])

    updates = fixer_node(_fix_state(graph_env, _branch_payload(graph_env)))

    assert len(runtime.calls) == 1
    assert updates["landed_positions"] == scoped(TURN, {0})
    assert [row.html for row in graph_env.rows()] == [ORIGINAL]
