"""An omitted ``findings[].objective`` is filled from ``CRITERIA`` before parsing.

Measured on Opus 5 (2026-10-12, 3 of 6 local 10-slide decks): the build
reviewer omitted ``objective`` on one finding, ``Finding`` requires it, the whole
review failed validation and a built, reviewed slide was placeheld.  Driven
through the real ``bind_structured_output_model`` and its ``PydanticToolsParser``
with a stand-in provider, so the assertion is on what production parses.
"""

from __future__ import annotations

import pytest

from src.domain.finding import CRITERIA, SlideReviewOutput
from src.services.agent_runtime import AgentModelConfiguration, bind_structured_output_model
from src.services.agent_schema_registry import AgentSchemaRegistry
from tests.fixtures.tool_call_doubles import replying, tool_call_reply

_CONFIG = AgentModelConfiguration(
    endpoint_name="stand-in", temperature=0.0, max_tokens=100, top_p=1.0
)


def _finding(criterion: str, **extra) -> dict:
    return {
        "id": "unstamped",
        "slide_index": 0,
        "category": CRITERIA[criterion].category,
        "criterion": criterion,
        "message": "stub",
        **extra,
    }


def _parse(args: dict):
    class _Provider:
        def bind_tools(self, tools, **kwargs):
            (schema,) = tools
            return replying(lambda prompt: tool_call_reply(schema, args))

    bound = bind_structured_output_model(
        model_factory=lambda **kwargs: _Provider(),
        workspace_client=object(),
        configuration=_CONFIG,
        schema=SlideReviewOutput,
    )
    return bound.invoke("prompt")


def _objective_and_subjective():
    objective = next(name for name, c in CRITERIA.items() if c.objective)
    subjective = next(name for name, c in CRITERIA.items() if not c.objective)
    return objective, subjective


def test_an_omitted_objective_takes_the_registry_value():
    objective, subjective = _objective_and_subjective()
    out = _parse(
        {
            "slide_index": 0,
            "verdict": "surfaced",
            "findings": [_finding(objective), _finding(subjective)],
        }
    )
    assert [f.objective for f in out.findings] == [True, False]


def test_a_supplied_objective_is_left_for_the_node_to_correct():
    """Only an ABSENT key is filled; ``_stamp_findings`` owns overriding a wrong one."""
    objective, _ = _objective_and_subjective()
    out = _parse(
        {
            "slide_index": 0,
            "verdict": "surfaced",
            "findings": [_finding(objective, objective=False)],
        }
    )
    assert out.findings[0].objective is False


def test_an_unknown_criterion_still_fails_validation():
    with pytest.raises(Exception):
        _parse(
            {
                "slide_index": 0,
                "verdict": "surfaced",
                "findings": [
                    {"id": "x", "slide_index": 0, "category": "layout",
                     "criterion": "not_a_criterion", "message": "m"}
                ],
            }
        )


def test_the_frozen_schema_contracts_are_unchanged():
    """The default lives before parsing precisely so this still constructs."""
    AgentSchemaRegistry()
