# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""The deck style reaches every model role that builds or judges a slide
(architect deck style, plan Task 5; PLAN-CORRECTIONS C13, C14, C15; Ruling R5).

* **Builder, build reviewer, fixer and fix reviewer.**  A committed spec's
  ``deck_style`` travels to each of them as the payload key ``deck_style``, a
  ``DeckStyle.model_dump()``.  Driven through the production chain: the architect
  commits the spec, ``build_branch_payload`` copies it out of state, and
  ``slide_pipeline_node`` runs builder -> build reviewer -> fixer -> fix reviewer
  with the build reviewer opening a fix.  A slide's ``look`` arrives inside
  ``slide_spec``.
* **The deck-level re-review (C15).**  ``rereview_committed_slides`` builds its
  own build-reviewer payload; it carries ``deck_style`` too.
* **Old decks are unchanged.**  For a spec with no deck style none of those five
  payloads has a ``deck_style`` key, and each key set is exactly the base
  commit's — literals copied from HEAD 2ce8640b here, never imports of a
  production or fixture set, so a widened payload fails instead of agreeing.
* **The architect is shown what it may reference.**  Its payload gains
  ``deck_style_context``: ``deck_style_context(token_css, style_block)`` of the
  brand it is shown, the defined empty form on an unpinned deck, and never the
  brand's font data.
* **The projection keeps them (C13).**  ``model_payload_for`` — what eval packs
  and workbench test runs hand the model — strips nothing from a payload that
  carries the new keys.

How this file asserts: on the payload each role's node actually handed the
runtime (``SkillStub`` records it), never on whether a helper was called.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from src.api.services.deck_level_writer import write_deck_level_columns
from src.domain.deck_spec import DeckSpec, DeckStyle, DeckStyleComponent
from src.domain.deck_style import deck_style_context
from src.services.agent_model_payload import model_payload_for
from src.services.graph.nodes import (
    architect_node,
    build_branch_payload,
    rereview_committed_slides,
    slide_pipeline_node,
)
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    builder_out,
    finding,
    fixer_out,
    graph_env,
    make_spec,
    review_out,
)

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

#: A clean style the sanitiser keeps byte-identical: one ``.dk-`` rule, one component.
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
LOOK = "Two columns: a dk-callout on the left, the chart on the right."

#: A brand whose CSS carries embedded font data, as a design system's does.
#: ``token_css`` is every CSS file of the bundle joined, so it may hold a class
#: rule too; ``template_classes`` come from the template's ``style_block`` only.
FONT_TOKEN_CSS = (
    "@font-face{font-family:'Brand Sans';"
    "src:url(data:font/woff2;base64,d09GMgABAAAAAAQ4AA0AAAAACMQAAAPh) format('woff2')}\n"
    ":root{--brand-primary:#0b2a4a;--brand-font:'Brand Sans',sans-serif;"
    "--brand-logo:url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB)}\n"
    ".brand-eyebrow{letter-spacing:.2em}"
)
FONT_STYLE_BLOCK = (
    "@font-face{font-family:'Brand Serif';"
    "src:url(data:font/woff2;base64,d09GMgABAAAAAAQ4) format('woff2')}\n"
    ":root{--brand-accent:#e4572e}\n"
    ".slide{font-family:var(--brand-font);color:var(--brand-primary)}\n"
    ".slide .title{font-size:44px}\n"
    "@media (max-width:800px){.slide .kpi{font-size:20px}}"
)

#: The re-review's brand, as ``_resolve_brand`` returns it (the keys it reads).
REREVIEW_BRAND = {
    "resolved_style": "STUB STYLE PROSE",
    "deterministic_css": ".slide { color: red; }",
    "design_system_active": False,
    "template_layout_html": "",
}

# ---------------------------------------------------------------------------
# The base commit's model payload key sets (HEAD 2ce8640b), as literals
# ---------------------------------------------------------------------------

OLD_BUILDER_KEYS = frozenset(
    {
        "position",
        "slide_spec",
        "assumes",
        "hands_off",
        "resolved_data",
        "section_html",
        "section_css",
        "resolved_style",
        "design_system_active",
    }
)
OLD_BUILD_REVIEWER_KEYS = frozenset(
    {
        "position",
        "slide_spec",
        "resolved_style",
        "section_css",
        "resolved_data",
        "section_html",
        "html",
        "scripts",
    }
)
OLD_FIXER_KEYS = frozenset(
    {
        "position",
        "finding",
        "html",
        "scripts",
        "slide_spec",
        "resolved_style",
        "section_css",
        "resolved_data",
    }
)
OLD_FIX_REVIEWER_KEYS = frozenset(
    {
        "position",
        "finding",
        "change_summary",
        "html",
        "scripts",
        "original_html",
        "original_scripts",
        "slide_spec",
        "resolved_style",
        "section_css",
    }
)
OLD_REREVIEW_KEYS = OLD_BUILD_REVIEWER_KEYS | {"deck_brief"}
OLD_ARCHITECT_KEYS = frozenset(
    {
        "conversation",
        "message",
        "current_deck_spec",
        "committed_slide_count",
        "slide_numbering",
        "slide_references",
        "previous_deck_review",
        "available_design_contract",
        "template_sections",
        "resolved_style",
        "design_system_library",
    }
)

SLIDE_ROLES = ("builder", "build_reviewer", "fixer", "fix_reviewer", "rereview")
OLD_KEYS = {
    "builder": OLD_BUILDER_KEYS,
    "build_reviewer": OLD_BUILD_REVIEWER_KEYS,
    "fixer": OLD_FIXER_KEYS,
    "fix_reviewer": OLD_FIX_REVIEWER_KEYS,
    "rereview": OLD_REREVIEW_KEYS,
}


# ---------------------------------------------------------------------------
# Driving the production chain
# ---------------------------------------------------------------------------


def _styled_spec() -> DeckSpec:
    spec = make_spec((0,))
    slide = spec.slides[0].model_copy(update={"look": LOOK})
    return spec.model_copy(update={"deck_style": CALLOUT_STYLE, "slides": [slide]})


def _only_call(env, role: str) -> Dict[str, Any]:
    calls = env.skills.calls_for(role)
    assert len(calls) == 1, f"expected one {role} call, got {len(calls)}"
    return calls[0]["payload"]


def _slide_role_payloads(env, spec: DeckSpec) -> Dict[str, Any]:
    """Every slide role's model payload for one turn that commits *spec*.

    The architect commits the spec; ``build_branch_payload`` copies it out of
    state; ``slide_pipeline_node`` builds slide 0, the build reviewer flags an
    objective finding, the fixer fixes it and the fix reviewer clears it.  Then
    the deck-level re-review scores the committed slide against the spec.

    Returns the payloads keyed by role, plus ``"committed"`` — the spec the
    architect committed into state, which is what every branch is briefed from.
    """
    env.skills.set("architect", architect_build(spec))
    env.skills.set("builder", builder_out)
    env.skills.set(
        "build_reviewer",
        lambda payload: review_out(
            payload["position"],
            [finding("overflow", slide_index=payload["position"])],
        ),
    )
    env.skills.set("fixer", fixer_out)
    env.skills.set("fix_reviewer", lambda payload: review_out(payload["position"]))

    state = env.state()
    state = {**state, **architect_node(state)}
    committed: DeckSpec = state["deck_spec"]
    slide_pipeline_node(build_branch_payload(state, 0))

    payloads = {
        "committed": committed,
        "builder": _only_call(env, "builder"),
        "build_reviewer": _only_call(env, "build_reviewer"),
        "fixer": _only_call(env, "fixer"),
        "fix_reviewer": _only_call(env, "fix_reviewer"),
    }

    # The deck-level re-review (C15), on its own: it reads committed rows, so the
    # one the fix reviewer just wrote is there to be scored.
    env.skills.calls.clear()
    env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))
    rereview_committed_slides(env.session_id, committed, REREVIEW_BRAND, 1)
    payloads["rereview"] = _only_call(env, "build_reviewer")
    return payloads


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------


def test_branch_payload_carries_deck_style(graph_env):
    payloads = _slide_role_payloads(graph_env, _styled_spec())
    committed = payloads["committed"]
    builder = payloads["builder"]

    # Guard: the committed spec still carries the style, so the builder had one
    # to be given (the sanitiser keeps a clean style as is).
    assert committed.deck_style is not None
    assert committed.deck_style.model_dump() == CALLOUT_STYLE.model_dump()

    assert "deck_style" in builder, "the builder was not shown the deck style"
    assert builder["deck_style"] == committed.deck_style.model_dump()
    assert builder["slide_spec"]["look"] == LOOK
    # Nothing else was widened: the base keys plus the one new key.
    assert set(builder) == OLD_BUILDER_KEYS | {"deck_style"}


# ---------------------------------------------------------------------------
# The judges and the fixer, and the deck-level re-review
# ---------------------------------------------------------------------------


def test_reviewer_fixer_and_fix_reviewer_payloads_carry_deck_style(graph_env):
    payloads = _slide_role_payloads(graph_env, _styled_spec())
    expected = payloads["committed"].deck_style.model_dump()

    missing = [
        role
        for role in ("build_reviewer", "fixer", "fix_reviewer", "rereview")
        if "deck_style" not in payloads[role]
    ]
    assert missing == [], f"these model payloads carry no deck_style: {missing}"
    for role in ("build_reviewer", "fixer", "fix_reviewer", "rereview"):
        assert payloads[role]["deck_style"] == expected, role
        assert set(payloads[role]) == OLD_KEYS[role] | {"deck_style"}, role


# ---------------------------------------------------------------------------
# Old decks: no key, exactly today's payloads
# ---------------------------------------------------------------------------


def test_payloads_without_deck_style_carry_no_key(graph_env):
    """The oracle: green at the base commit, and must stay green."""
    spec = make_spec((0,))
    assert spec.deck_style is None

    payloads = _slide_role_payloads(graph_env, spec)

    assert payloads["committed"].deck_style is None
    for role in SLIDE_ROLES:
        assert "deck_style" not in payloads[role], role
        assert set(payloads[role]) == OLD_KEYS[role], role


# ---------------------------------------------------------------------------
# The architect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("deck", ["pinned", "unpinned"])
def test_architect_payload_has_context_without_font_data(graph_env, deck):
    env = graph_env
    if deck == "pinned":
        # Pin ds 7 / template 3 on the persisted spec, so the brand the architect
        # is shown (the inbound one) resolves the font-bearing template bytes.
        env.template.token_css = FONT_TOKEN_CSS
        env.template.style_block = FONT_STYLE_BLOCK
        prior = make_spec((0,), design_system_id=7, template_id=3)
        write_deck_level_columns(env.session_id, deck_spec=prior.to_json())
        answer = make_spec((0,), design_system_id=7, template_id=3)
        expected = deck_style_context(FONT_TOKEN_CSS, FONT_STYLE_BLOCK)
        # Guard: the fixture is not vacuous, and the brand really carries font data.
        assert expected["design_tokens"] and expected["template_classes"]
        assert "@font-face" in FONT_TOKEN_CSS and "base64" in FONT_STYLE_BLOCK
    else:
        answer = make_spec((0,))
        expected = {"design_tokens": {}, "template_classes": []}
    env.skills.set("architect", architect_build(answer))

    architect_node(env.state())

    payload = _only_call(env, "architect")
    if deck == "pinned":
        assert env.template.calls[:1] == [(7, 3)], "the inbound brand was not pinned"
    assert "deck_style_context" in payload, "the architect was not shown the context"
    assert payload["deck_style_context"] == expected
    assert set(payload) == OLD_ARCHITECT_KEYS | {"deck_style_context"}
    rendered = json.dumps(payload)
    assert "@font-face" not in rendered
    assert "base64" not in rendered
    # The architect sees its own style through current_deck_spec, never as a key.
    assert "deck_style" not in payload


# ---------------------------------------------------------------------------
# The projection eval packs and workbench runs use (C13)
# ---------------------------------------------------------------------------

_STYLE_DUMP = CALLOUT_STYLE.model_dump()
_CONTEXT = {"design_tokens": {"--brand-primary": "#0b2a4a"}, "template_classes": ["slide"]}


def _filled(keys) -> Dict[str, Any]:
    return {key: f"value of {key}" for key in sorted(keys)}


@pytest.mark.parametrize(
    "role, payload",
    [
        ("builder", _filled(OLD_BUILDER_KEYS) | {"deck_style": _STYLE_DUMP}),
        (
            "builder",
            _filled(OLD_BUILDER_KEYS | {"corrective_instruction"})
            | {"deck_style": _STYLE_DUMP},
        ),
        ("build_reviewer", _filled(OLD_BUILD_REVIEWER_KEYS) | {"deck_style": _STYLE_DUMP}),
        ("build_reviewer", _filled(OLD_REREVIEW_KEYS) | {"deck_style": _STYLE_DUMP}),
        ("fixer", _filled(OLD_FIXER_KEYS) | {"deck_style": _STYLE_DUMP}),
        (
            "fixer",
            _filled(OLD_FIXER_KEYS | {"corrective_instruction"})
            | {"deck_style": _STYLE_DUMP},
        ),
        ("fix_reviewer", _filled(OLD_FIX_REVIEWER_KEYS) | {"deck_style": _STYLE_DUMP}),
        (
            "architect",
            _filled(OLD_ARCHITECT_KEYS - {"previous_deck_review"})
            | {"previous_deck_review": None, "deck_style_context": _CONTEXT},
        ),
    ],
    ids=[
        "builder",
        "builder_retry",
        "build_reviewer",
        "deck_level_rereview",
        "fixer",
        "fixer_retry",
        "fix_reviewer",
        "architect",
    ],
)
def test_model_payload_projection_keeps_deck_style(role, payload):
    projected = model_payload_for(role, payload)

    new_key = "deck_style_context" if role == "architect" else "deck_style"
    assert new_key in projected, f"model_payload_for({role!r}) strips {new_key}"
    assert projected[new_key] == payload[new_key]
    # A production payload loses nothing to the projection.
    assert projected == payload
