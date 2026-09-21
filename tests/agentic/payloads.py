"""Payload builders that mirror what the graph nodes actually send.

WHY THIS EXISTS
---------------
A layer-3 test calls ``AgentRuntime`` directly — one model call, no database, no
graph — because the question is "what did the agent do with this input", not "did
the topology hold" (layer 1 owns that, in CI, with stubs).  But a skill invoked
with a payload the production nodes never send is measuring the fixture, not the
agent: the model would be answering a question it is never asked.  So every
builder here reproduces the key set of the corresponding node's payload, and
``tests/unit/test_agentic_layer_is_placed_and_gated.py`` parses ``architect_node``
to prove the architect builder has not drifted from it.

The values are synthetic.  No real brand, customer or account material.
"""

from __future__ import annotations

from typing import Any

#: Exactly the keys ``architect_node`` puts in its ``AgentRuntime`` payload
#: (``src/services/graph/nodes.py``).  Guarded against drift — see the module
#: docstring.
ARCHITECT_PAYLOAD_KEYS: tuple[str, ...] = (
    "session_id",
    "conversation",
    "message",
    "current_deck_spec",
    "committed_slide_count",
    "previous_deck_review",
    "available_design_contract",
    "template_sections",
    "resolved_style",
    "design_system_library",
)


def architect_payload(message: str, **overrides: Any) -> dict[str, Any]:
    """The architect's payload, with every production key present.

    Absent keys are as significant as present ones: ``architect_node`` always
    sends all ten, so a builder that omitted ``template_sections`` would be
    testing a prompt shape the architect never sees.

    Args:
        message: the user's turn — the field the architect classifies.
        **overrides: any of :data:`ARCHITECT_PAYLOAD_KEYS`.

    Raises:
        KeyError: on an override that is not a production key.  A typo'd key
            would otherwise travel silently into the prompt as dead JSON.
    """
    payload: dict[str, Any] = {
        "session_id": "agentic-layer3",
        "conversation": [],
        "message": message,
        "current_deck_spec": None,
        "committed_slide_count": 0,
        "previous_deck_review": None,
        "available_design_contract": None,
        "template_sections": [],
        "resolved_style": None,
        "design_system_library": [],
    }
    unknown = sorted(set(overrides) - set(payload))
    if unknown:
        raise KeyError(
            f"{unknown} are not architect payload keys. The production keys are "
            f"{list(ARCHITECT_PAYLOAD_KEYS)}; adding one here without adding it to "
            "architect_node would test a prompt shape production never sends."
        )
    payload.update(overrides)
    return payload


def slide_spec(position: int, *, purpose: str, content_brief: str) -> dict[str, Any]:
    """One ``SlideSpec``, as a JSON-ready dict, via the real model."""
    from src.domain.deck_spec import SlideSpec

    return SlideSpec(
        position=position,
        purpose=purpose,
        content_brief=content_brief,
        assumes="the audience has seen the previous slide",
        hands_off="the single takeaway of this slide",
        data_references=[],
    ).model_dump(mode="json")


def deck_spec_dict(slides: list[dict[str, Any]], *, title: str) -> dict[str, Any]:
    """A committed deck spec, shaped exactly as ``read_deck_spec`` returns one.

    Built through :class:`~src.domain.deck_spec.DeckSpec` rather than hand-written,
    so a fixture that the architect could never have been handed (duplicate
    positions, empty title) fails here instead of producing a plausible-looking
    prompt.
    """
    from src.domain.deck_spec import (
        DeckSpec,
        DesignContractRef,
        ResolvedData,
        SlideSpec,
    )

    return DeckSpec(
        title=title,
        audience="the engineering leadership team",
        purpose="decide whether to keep investing in the current approach",
        argument="the current approach is working and should continue",
        call_to_action="approve the next quarter of work",
        narrative_arc=["where we started", "what we measured", "what to do next"],
        design_contract=DesignContractRef(),
        resolved_data=ResolvedData(synthesis="", figures=[], gaps=[]),
        slides=[SlideSpec(**s) for s in slides],
    ).model_dump(mode="json")


def build_reviewer_payload(
    *, position: int, html: str, spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The build reviewer's payload, mirroring ``build_reviewer_node``.

    ``resolved_style`` and ``section_css`` are ``None`` on the no-template path,
    which is also the path that makes ``design_system_active`` false — and that
    flag is what causes ``AgentRuntime`` to inject
    ``_SLIDE_FRAME_CONSTRAINTS``.  The reviewer must be shown the numbers it is
    told to judge against, or the test is unfair by construction.
    """
    return {
        "position": position,
        "slide_spec": spec,
        "resolved_style": None,
        "section_css": None,
        "resolved_data": None,
        "html": html,
        "scripts": "",
    }


def fixer_payload(
    *, position: int, html: str, finding: dict[str, Any], spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The fixer's payload, mirroring ``fixer_node``."""
    return {
        "position": position,
        "finding": finding,
        "html": html,
        "scripts": "",
        "slide_spec": spec,
        "resolved_style": None,
        "section_css": None,
    }


def fix_reviewer_payload(
    *,
    position: int,
    html: str,
    finding: dict[str, Any],
    change_summary: str,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The fix reviewer's payload, mirroring ``fix_reviewer_node``."""
    return {
        "position": position,
        "finding": finding,
        "change_summary": change_summary,
        "html": html,
        "scripts": "",
        "slide_spec": spec,
        "resolved_style": None,
        "section_css": None,
    }


def analyst_payload(request: str, *, deck_purpose: str | None = None) -> dict[str, Any]:
    """The analyst's payload, mirroring ``data_analyst_node``.

    ``data_request`` is a *string* on the graph path, not a ``DataRequest`` object:
    ``GraphState`` declares no analyst channel, so the request travels as prose on
    ``architect_message`` and the node copies it straight across.
    """
    return {
        "session_id": "agentic-layer3",
        "data_request": request,
        "deck_purpose": deck_purpose,
    }


def well_formed_slide_html(
    frame: dict[str, int],
    *,
    caption_colour: str = "#111111",
    title_colour: str = "#111111",
) -> str:
    """A slide that fits its frame, with the colours as parameters.

    Everything except the two colours is correct: the root declares the frame's own
    size, clips its overflow, and keeps content inside the safe area — all read from
    ``_SLIDE_FRAME_CONSTRAINTS``.  That isolation is the point.  A ``contrast_failure``
    on one caption has exactly one narrow correction available, so a fixer that
    rewrites anything else has re-authored rather than corrected, and the diff says
    so.

    ``#cccccc`` on white is a real contrast failure (~1.6:1 against WCAG AA's 4.5:1)
    and a real builder choice — a light grey caption is the commonest one there is.
    """
    return (
        f'<div class="slide" style="width:{frame["width"]}px;'
        f'height:{frame["height"]}px;overflow:hidden;background:#ffffff;'
        f'padding:{frame["vertical_floor"]}px {frame["horizontal_clearance"]}px">\n'
        f'  <h1 style="color:{title_colour};margin:0 0 16px">Adoption doubled after '
        "onboarding changed</h1>\n"
        '  <ul style="color:#111111;margin:0 0 16px">\n'
        "    <li>Weekly active teams rose from 40 to 81</li>\n"
        "    <li>The change landed in the second week of the quarter</li>\n"
        "    <li>No other release shipped in that window</li>\n"
        "  </ul>\n"
        f'  <p style="color:{caption_colour};font-size:14px;margin:0">Source: the '
        "internal adoption ledger, quarter to date</p>\n"
        "</div>"
    )


def overflowing_slide_html(frame: dict[str, int]) -> str:
    """A slide that genuinely does not fit, sized from the frame's own numbers.

    §31's diagnostic, applied to this fixture: *what real input would produce an
    ``overflow`` finding?*  This one — a root element that declares the frame's
    exact height, does not clip, and is handed a stack of rows whose combined
    height is roughly twice that.  A real builder produces this whenever it puts
    a long list on one slide, which is the commonest overflow in the product.

    Every number is derived from ``_SLIDE_FRAME_CONSTRAINTS`` (see
    :func:`tests.agentic.gates.frame_constraint_numbers`) — nothing here is a
    hard-coded safe-area value.
    """
    row_height = 48
    rows_that_fit = frame["height"] // row_height
    rows = "\n".join(
        f'    <li style="height:{row_height}px;line-height:{row_height}px">'
        f"Finding {i + 1}: a full sentence of body copy that occupies its own row"
        "</li>"
        for i in range(rows_that_fit * 2)
    )
    return (
        f'<div class="slide" style="width:{frame["width"]}px;'
        f'height:{frame["height"]}px;overflow:visible;'
        f'padding:{frame["vertical_floor"]}px {frame["horizontal_clearance"]}px">\n'
        "  <h1>Every finding from the last review, on one slide</h1>\n"
        f'  <ul style="margin:0;padding:0;list-style:none">\n{rows}\n  </ul>\n'
        "</div>"
    )
