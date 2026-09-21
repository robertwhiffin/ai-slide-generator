"""Layer 3: the analyst returns exactly one of its three outcome shapes.

THE PLAN ASKS FOR ONE CALL PER OUTCOME.  ONE OF THE THREE IS REACHABLE.
----------------------------------------------------------------------
Re-measured on this branch before writing a line of it:

* ``grep -rn "bind_tools" src/`` returns **one** hit, and it is prose — a docstring
  in ``src/services/graph/nodes.py`` stating *"There is no manifest. ``TOOL_GRANTS``
  is ``[]``, ``bind_tools`` appears nowhere under ``src/``, and ``AgentRuntime``
  invokes the architect with structured output and no tools bound at all"*.
* ``DatabricksModelAdapter`` ends at ``model.with_structured_output(schema)``.
  There is no ``.bind_tools(...)`` on that path, or on any other.
* ``data_analyst``'s ``TOOL_GRANTS`` is ``["genie", "vector_index"]`` and is read by
  **nothing**: the only occurrences under ``src/`` are its own definition and the
  registry that copies it into the frozen ``Skill``.

So on the graph path the analyst holds no tool it can call.  It cannot retrieve
anything, and by its own prose the correct answer to every request is therefore
``no_tool``.  That has consequences for three of the four tests below, and they are
**skipped individually with the cause recorded** rather than rewritten into
something a tool-less analyst can satisfy:

``success``
    Unreachable.  ``AnalystOutput`` requires both ``synthesis`` and ``sources`` for
    ``success``, and a model with no tool has no source to name.  Anything it
    returned would be invented.

``missing_data``
    Unreachable.  Its meaning is *a tool ran and returned nothing* ("No source
    returned data"); with no tool, nothing ran.  A test that accepted
    ``missing_data`` here would be scoring the model's word choice between two
    labels for the same non-event.

verbatim single-source pass-through
    Unreachable, and the interesting one.  The behaviour is real and load-bearing —
    ``AnalystOutput``'s validator says in as many words that *"single source → pass
    through, do not re-summarise"* is **uncheckable** without ``synthesis``.  But the
    canned tool output the assertion needs has nowhere to enter from: there is no
    tool to stub and no payload key that carries source text (``analyst_payload``
    mirrors the node's three keys — ``session_id``, ``data_request``,
    ``deck_purpose``).  Inventing a payload key would test a prompt shape production
    never sends, i.e. measure the fixture.

**None of these three is a placeholder-prompt problem, and authoring the prompts
will not make them pass.**  They need either a bound tool or a declared channel,
both of which are scope additions recorded in ws4c's own gap list (``ResolvedData.
figures`` is empty on the graph path for the same root cause, which is why
``source_contradiction`` is unreachable too).  They are written out in full so that
the day a tool is bound, the work is deleting a skip.
"""

from __future__ import annotations

import pytest

from tests.agentic.gates import LAYER3_MARKS, invoke_agent
from tests.agentic.payloads import analyst_payload

pytestmark = LAYER3_MARKS

#: Shared by the three tests the graph path cannot reach.  Stated as a cause, so a
#: reader of ``pytest -rs`` learns what to change rather than that something is
#: "not supported".
_NO_TOOL_IS_BOUND = (
    "the analyst can reach no tool on the graph path: bind_tools appears nowhere "
    "under src/ (the single hit is a docstring saying so), DatabricksModelAdapter "
    "ends at with_structured_output with no tools bound, and data_analyst's "
    "TOOL_GRANTS is read by nothing. This outcome is therefore unreachable — NOT "
    "because the prompts are placeholders. Authoring them will not make it pass; "
    "binding a tool, or declaring a channel that carries source text, will."
)


def test_the_analyst_reports_no_tool_and_says_why():
    """The one outcome the graph path can actually produce.

    Also the structural half of "exactly one of three shapes": the outcome is one of
    the three literals, and the field that outcome requires is populated.  For
    ``no_tool`` the skill's own prose requires ``reason``; the schema does not
    enforce it (only ``success`` is validated), which is precisely why it is worth
    asserting here.
    """
    out = invoke_agent(
        "data_analyst",
        analyst_payload(
            "How many weekly active teams were there in each region last quarter?",
            deck_purpose="decide where to spend next quarter's onboarding effort",
        ),
        False,
    )

    assert out.outcome in {"success", "missing_data", "no_tool"}, (
        f"outcome {out.outcome!r} is outside AnalystOutput's closed union"
    )
    assert out.outcome == "no_tool", (
        f"the analyst returned {out.outcome!r} for a metric request while holding no "
        "callable tool. Its own procedure reserves `no_tool` for 'no applicable "
        f"tool'; anything else claims a retrieval that cannot have happened. "
        f"synthesis={out.synthesis!r} sources={out.sources!r} gap={out.gap!r}"
    )
    assert out.reason, (
        "outcome is `no_tool` with an empty `reason`. The node renders that reason "
        "into the sentence the user reads ('No tool is available for this kind of "
        "data request (…)'), so an empty one shows the user an empty parenthesis."
    )
    assert not out.synthesis, (
        f"the analyst returned a synthesis ({out.synthesis!r}) alongside `no_tool`. "
        "Prose with no retrieval behind it is the fabrication this outcome exists to "
        "prevent — the node would show it to the user as an answer."
    )


@pytest.mark.skip(reason=_NO_TOOL_IS_BOUND)
def test_the_analyst_reports_success_with_synthesis_and_sources():
    """Unreachable today — see the module docstring and ``_NO_TOOL_IS_BOUND``."""
    out = invoke_agent(
        "data_analyst",
        analyst_payload(
            "How many weekly active teams were there in each region last quarter?",
            deck_purpose="decide where to spend next quarter's onboarding effort",
        ),
        False,
    )

    assert out.outcome == "success", f"outcome was {out.outcome!r}"
    # AnalystOutput's validator already requires both for `success`; asserted again
    # because the node reads them directly to build the message the user sees.
    assert out.synthesis, "success with no synthesis"
    assert out.sources, "success with no sources"


@pytest.mark.skip(reason=_NO_TOOL_IS_BOUND)
def test_the_analyst_reports_missing_data_and_names_the_gap():
    """Unreachable today — ``missing_data`` means a tool ran and found nothing."""
    out = invoke_agent(
        "data_analyst",
        analyst_payload(
            "What was the churn rate for the Antarctic region in 1804?",
            deck_purpose="decide where to spend next quarter's onboarding effort",
        ),
        False,
    )

    assert out.outcome == "missing_data", f"outcome was {out.outcome!r}"
    assert out.gap, (
        "missing_data with no gap: the node renders the gap into 'The requested "
        "data could not be found: …', so an empty one tells the user nothing"
    )


@pytest.mark.skip(reason=_NO_TOOL_IS_BOUND)
def test_a_single_source_passes_through_without_being_re_summarised():
    """Unreachable today — there is no tool to stub and no channel for source text.

    Written against the behaviour as specified: with ONE source returned, the
    analyst passes it through verbatim rather than paraphrasing it.  The assertion
    is containment of the source's own sentence in the synthesis, which is a
    pass-through check on text the *fixture* supplied — not a comparison against
    wording this test expects the model to produce.
    """
    source_sentence = (
        "Weekly active teams rose from 40 in week one to 81 in week thirteen."
    )
    out = invoke_agent(
        "data_analyst",
        analyst_payload(
            "Weekly active teams by week for last quarter.",
            deck_purpose="decide where to spend next quarter's onboarding effort",
        ),
        False,
    )

    assert out.outcome == "success", f"outcome was {out.outcome!r}"
    assert len(out.sources or []) == 1, (
        f"this behaviour is about the single-source case; sources were {out.sources}"
    )
    assert source_sentence in (out.synthesis or ""), (
        "the analyst re-summarised a single source instead of passing it through. "
        f"The source read {source_sentence!r}; the synthesis was {out.synthesis!r}"
    )
