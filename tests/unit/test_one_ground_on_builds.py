# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""One ground on builds, deterministic (deck style addendum A, Task B7; RA23, RA25).

The builder prompt's one-ground rule held most of the time, not always: on the dev10
Lakebase deck a bound "Two-column" section kept its ``<div class="slide white">`` and
rendered on #FFF beside content slides on the deck's default ground.  So on a build
turn the code drops it.

The contract these tests hold (Ruling RA25):

* **The branch key.**  ``build_branch_payload(state, position)`` adds exactly one key,
  ``one_ground: True``, when the turn's ``architect_intent`` builds or rebuilds the deck
  AND the committed spec carries a ``deck_style``.  The intent map, pinned below: only
  ``"build"`` counts — a build that rebuilds some positions (a deck-level re-review) or
  all of them included.  ``"edit"`` never counts, even when it rebuilds every position
  (a confirmed design-contract change on an edit), and nor do ``discuss``, ``ask_data``,
  ``confirm_design_contract`` or an absent intent.  Every other branch payload (an edit,
  an old deck with no deck style) has exactly the base commit's keys.
* **The seam.**  ``slide_pipeline_node`` drops ``white`` (``drop_white_ground``) when its
  payload carries the key and the slide is not the cover — spec position 0, the notion
  ``blank_slide_shell`` uses (``deck_spec_slides.py``: "never slide 0 (the cover)") — after
  the builder and BEFORE the draft write, and again on the fixer's output.  So no row
  write ever holds the dropped white, the build reviewer judges the HTML that is stored,
  and the streamed ``slide_ready`` html equals the stored html.
* **Never touched.**  The cover; an edit turn (its fixer too: "make slide 5 white" keeps
  white); a deck without a deck style (byte-identical to the builder's output).
* **The models never see the key.**  It is not in ``_BUILDER_MODEL_PAYLOAD_KEYS`` nor in
  the fixer's model payload: every slide role's model payload is byte-identical with and
  without it.

Observed on what a user receives: rows read back off the real database, every
``SlideWriter.write_slide`` call (the polling transport shows the draft), and the
``slide_ready`` events of a compiled-graph turn — never on whether a helper was called.
"""

from __future__ import annotations

import json
import queue
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from src.api.schemas.streaming import StreamEventType
from src.api.services.deck_level_writer import write_deck_level_columns
from src.api.services.slide_repository import SlideWriter
from src.domain.deck_spec import DeckSpec, DeckStyle, DeckStyleComponent
from src.domain.finding import DeckReviewOutput
from src.domain.skill_io import ArchitectOutput
from src.services.foreman_service import CAP
from src.services.graph.builder import build_graph
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import build_branch_payload, builder_node, slide_pipeline_node
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest_graph import (  # noqa: F401 — fixtures
    architect_build,
    builder_out,
    finding,
    fixer_out,
    graph_env,
    graph_env_threadsafe,
    make_spec,
    review_out,
)

#: A clean style the sanitiser keeps byte-identical (as test_deck_style_payloads).
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

#: ``build_branch_payload``'s keys at the base commit (e7df35e7), as a literal.
HEAD_BRANCH_KEYS = frozenset(
    {
        "session_id",
        "graph_release_id",
        "turn_id",
        "root_session_id",
        "actor_session_id",
        "initiated_by",
        "position",
        "slide_spec",
        "assumes",
        "hands_off",
        "design_contract",
        "resolved_data",
        "section_html",
        "section_css",
        "resolved_style",
        "design_system_active",
    }
)

# What the builder writes, per position, and what a user must receive on a build turn
# of a deck with a deck style.  Position 0 is the cover.
COVER = '<div class="slide white"><h1>Cover</h1></div>'
TWO_COLUMN = (
    '<section class="frame"><div class="slide white" data-look="two-column">'
    '<div class="card white">A</div><p class="whitespace bg-white white-card">B</p>'
    "</div></section>"
)
TWO_COLUMN_ONE_GROUND = (
    '<section class="frame"><div class="slide" data-look="two-column">'
    '<div class="card white">A</div><p class="whitespace bg-white white-card">B</p>'
    "</div></section>"
)
EVENT = "<div class='white slide event'><h2>Launch</h2></div>"
EVENT_ONE_GROUND = "<div class='slide event'><h2>Launch</h2></div>"
DIVIDER = '<div class="slide dark"><h2>Part two</h2></div>'

BUILT = {0: COVER, 1: TWO_COLUMN, 2: EVENT, 3: DIVIDER}
ONE_GROUND = {0: COVER, 1: TWO_COLUMN_ONE_GROUND, 2: EVENT_ONE_GROUND, 3: DIVIDER}

FIXED_WHITE = '<div class="slide white"><h2>Fixed</h2></div>'
FIXED_ONE_GROUND = '<div class="slide"><h2>Fixed</h2></div>'


def _styled(spec: DeckSpec, deck_style: Optional[DeckStyle] = CALLOUT_STYLE) -> DeckSpec:
    if deck_style is None:
        return spec
    return spec.model_copy(update={"deck_style": deck_style})


def _class_tokens_of_slides(html: str) -> list:
    """The class tokens of every ``slide`` element, for the error messages."""
    import re

    return [
        value.split()
        for value in re.findall(r"""class=["']([^"']*)["']""", html)
        if "slide" in value.split()
    ]


# ---------------------------------------------------------------------------
# A compiled-graph turn, observed on rows, writes and the stream
# ---------------------------------------------------------------------------


def _wire_slides(env, *, built: Dict[int, str], fixes: Optional[Dict[int, str]] = None):
    fixes = fixes or {}
    env.skills.set("builder", lambda p: builder_out(p, html=built[p["position"]]))
    env.skills.set(
        "build_reviewer",
        lambda p: review_out(
            p["position"],
            [finding("overflow", slide_index=p["position"])] if p["position"] in fixes else [],
        ),
    )
    env.skills.set("fixer", lambda p: fixer_out(p, html=fixes[p["position"]]))
    env.skills.set("fix_reviewer", lambda p: review_out(p["position"]))
    env.skills.set("deck_reviewer", DeckReviewOutput(findings=[]))


def _run_turn(env, monkeypatch, turn_id: str = "turn-one-ground") -> SimpleNamespace:
    """Run one turn through the compiled graph; return what a user receives."""
    written: Dict[int, list] = {}
    real_write = SlideWriter.write_slide

    def _recording_write(self, *args, **kwargs):
        written.setdefault(kwargs["position"], []).append(kwargs["html"])
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(SlideWriter, "write_slide", _recording_write)
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    try:
        final = build_graph(checkpointer=False).invoke(
            env.state(turn_id=turn_id), {"max_concurrency": CAP}
        )
    finally:
        set_event_emitter(None)
    streamed: Dict[int, str] = {}
    while not emitter.empty():
        event = emitter.get_nowait()
        if event.type is StreamEventType.SLIDE_READY:
            streamed[event.position] = event.html
    rows = {row.position: row for row in env.rows()}
    return SimpleNamespace(
        final=final,
        rows=rows,
        stored={p: row.html for p, row in rows.items()},
        streamed=streamed,
        written=written,
    )


def _build_turn(env, monkeypatch, *, deck_style=CALLOUT_STYLE, fixes=None):
    spec = _styled(make_spec(tuple(BUILT)), deck_style)
    env.skills.set("architect", architect_build(spec))
    _wire_slides(env, built=BUILT, fixes=fixes)
    turn = _run_turn(env, monkeypatch)
    assert turn.final.get("architect_intent") == "build"
    assert sorted(turn.stored) == sorted(BUILT), "the turn did not build every slide"
    return turn


def _edit_turn(env, monkeypatch, *, target: int, built_html: str, fixes=None):
    """An edit of slide *target* on a committed four-slide deck with a deck style."""
    spec = _styled(make_spec(tuple(BUILT)))
    env.seed_slides([f"<div class='slide'>old {p}</div>" for p in BUILT])
    write_deck_level_columns(env.session_id, deck_spec=spec.to_json())
    revised = spec.model_copy(
        update={
            "slides": [
                s.model_copy(update={"content_brief": "make this slide white"})
                if s.position == target
                else s
                for s in spec.slides
            ]
        }
    )
    env.skills.set(
        "architect",
        ArchitectOutput(
            intent="edit",
            message="Editing.",
            target_positions=[target],
            deck_spec=revised,
        ),
    )
    _wire_slides(env, built={target: built_html}, fixes=fixes)
    turn = _run_turn(env, monkeypatch, turn_id="turn-edit")
    assert turn.final.get("architect_intent") == "edit"
    assert turn.final.get("target_positions") == [target]
    assert len(turn.written.get(target) or []) >= 1, "the edit built nothing"
    return turn


def _assert_received(turn, position: int, html: str) -> None:
    assert turn.stored[position] == html, (
        f"stored slide {position}: {_class_tokens_of_slides(turn.stored[position])}"
    )
    assert turn.streamed.get(position) == html, (
        f"streamed slide {position}: {turn.streamed.get(position)!r}"
    )


# ---------------------------------------------------------------------------
# The seam, on a build turn of a deck with a deck style
# ---------------------------------------------------------------------------


def test_a_build_turn_stores_and_streams_content_slides_without_white(
    graph_env_threadsafe, monkeypatch
):
    """The dev10 shape: a bound white section renders on the default ground.  Only the
    slide element's ``white`` goes; ``card white``, ``whitespace``, ``bg-white``,
    ``white-card``, ``event`` and ``dark`` stay, and so does every other byte."""
    turn = _build_turn(graph_env_threadsafe, monkeypatch)

    for position in (1, 2, 3):
        _assert_received(turn, position, ONE_GROUND[position])


def test_the_cover_keeps_white_on_a_build_turn(graph_env_threadsafe, monkeypatch):
    turn = _build_turn(graph_env_threadsafe, monkeypatch)

    _assert_received(turn, 0, COVER)


def test_no_write_of_a_content_slide_ever_holds_white_on_a_build_turn(
    graph_env_threadsafe, monkeypatch
):
    """Dropped BEFORE the draft write: the polling transport shows the draft, so a
    white draft would flash the ground the reviewed row then removes."""
    turn = _build_turn(graph_env_threadsafe, monkeypatch)

    for position in (1, 2):
        writes = turn.written[position]
        assert len(writes) == 2, f"expected the draft and the reviewed write, got {writes}"
        assert writes == [ONE_GROUND[position]] * 2, position


def test_the_build_reviewer_judges_the_html_that_is_stored(graph_env_threadsafe, monkeypatch):
    """The verdict is keyed by the stored html's hash and was reached on that html."""
    env = graph_env_threadsafe
    turn = _build_turn(env, monkeypatch)

    reviewed = {
        c["payload"]["position"]: c["payload"]["html"]
        for c in env.skills.calls_for("build_reviewer")
    }
    assert reviewed[1] == TWO_COLUMN_ONE_GROUND
    row = turn.rows[1]
    assert row.html == TWO_COLUMN_ONE_GROUND
    # get_slide_deck reads the verdict back with .get(compute_slide_hash(row.html)).
    record = json.loads(row.verification_record)
    assert compute_slide_hash(row.html) in record, "the stored slide carries no verdict of its own"


def test_a_build_turns_fixer_output_is_stored_and_streamed_without_white(
    graph_env_threadsafe, monkeypatch
):
    """The fixer may reintroduce white; it goes through the same rule."""
    env = graph_env_threadsafe
    turn = _build_turn(env, monkeypatch, fixes={1: FIXED_WHITE})

    (fix,) = env.skills.calls_for("fixer")
    assert fix["payload"]["position"] == 1
    (fix_review,) = env.skills.calls_for("fix_reviewer")
    assert fix_review["payload"]["html"] == FIXED_ONE_GROUND, "the re-review judged a white slide"
    _assert_received(turn, 1, FIXED_ONE_GROUND)
    # The draft, then the fix reviewer's winner: neither ever held the slide's white.
    assert turn.written[1] == [TWO_COLUMN_ONE_GROUND, FIXED_ONE_GROUND], turn.written[1]


def test_the_covers_fixer_output_keeps_white(graph_env_threadsafe, monkeypatch):
    env = graph_env_threadsafe
    turn = _build_turn(env, monkeypatch, fixes={0: FIXED_WHITE})

    assert [c["payload"]["position"] for c in env.skills.calls_for("fixer")] == [0]
    _assert_received(turn, 0, FIXED_WHITE)


# ---------------------------------------------------------------------------
# Never touched
# ---------------------------------------------------------------------------


def test_an_edit_turn_keeps_white(graph_env_threadsafe, monkeypatch):
    """A user who asks "make slide 2 white" keeps white."""
    turn = _edit_turn(graph_env_threadsafe, monkeypatch, target=1, built_html=TWO_COLUMN)

    _assert_received(turn, 1, TWO_COLUMN)
    assert turn.written[1] == [TWO_COLUMN], turn.written[1]


def test_an_edit_turns_fixer_output_keeps_white(graph_env_threadsafe, monkeypatch):
    env = graph_env_threadsafe
    turn = _edit_turn(env, monkeypatch, target=1, built_html=TWO_COLUMN, fixes={1: FIXED_WHITE})

    assert [c["payload"]["position"] for c in env.skills.calls_for("fixer")] == [1]
    _assert_received(turn, 1, FIXED_WHITE)


def test_a_deck_without_a_deck_style_keeps_every_slide_byte_identical(
    graph_env_threadsafe, monkeypatch
):
    turn = _build_turn(graph_env_threadsafe, monkeypatch, deck_style=None)

    for position, html in BUILT.items():
        _assert_received(turn, position, html)
        assert set(turn.written[position]) == {html}, position


# ---------------------------------------------------------------------------
# The branch key: which intents count, and nothing else moves
# ---------------------------------------------------------------------------


def _branch_state(env, *, intent, deck_style, target_positions=None) -> Dict[str, Any]:
    state = env.state(
        deck_spec=_styled(make_spec((0, 1, 2)), deck_style),
        root_session_id=env.session_id,
        actor_session_id=env.session_id,
        resolved_style="STUB STYLE PROSE",
        design_system_active=False,
        target_positions=target_positions,
    )
    if intent is not None:
        state["architect_intent"] = intent
    return state


INTENTS = [
    # (architect_intent, target_positions, builds or rebuilds the deck?)
    pytest.param("build", None, True, id="build"),
    pytest.param("build", [1], True, id="build_rebuilding_some_positions"),
    pytest.param("build", [0, 1, 2], True, id="build_rebuilding_every_position"),
    pytest.param("edit", [1], False, id="edit"),
    pytest.param("edit", [0, 1, 2], False, id="edit_rebuilding_every_position"),
    pytest.param("discuss", None, False, id="discuss"),
    pytest.param("ask_data", None, False, id="ask_data"),
    pytest.param("confirm_design_contract", None, False, id="confirm_design_contract"),
    pytest.param(None, None, False, id="no_intent"),
]


@pytest.mark.parametrize("intent, target_positions, builds", INTENTS)
@pytest.mark.parametrize("styled", [True, False], ids=["deck_style", "no_deck_style"])
def test_the_branch_key_is_set_only_on_a_build_of_a_styled_deck(
    graph_env, intent, target_positions, builds, styled
):
    state = _branch_state(
        graph_env,
        intent=intent,
        deck_style=CALLOUT_STYLE if styled else None,
        target_positions=target_positions,
    )

    for position in (0, 1, 2):
        payload = build_branch_payload(state, position)
        base = HEAD_BRANCH_KEYS | ({"deck_style"} if styled else set())
        if builds and styled:
            assert payload.get("one_ground") is True, position
            assert set(payload) == base | {"one_ground"}, position
        else:
            assert "one_ground" not in payload, position
            assert set(payload) == base, position


def test_the_cover_still_carries_the_key_so_the_seam_decides_it(graph_env):
    """The key is the turn's and the deck's; the cover is the seam's call (position 0)."""
    state = _branch_state(graph_env, intent="build", deck_style=CALLOUT_STYLE)

    assert build_branch_payload(state, 0).get("one_ground") is True


# ---------------------------------------------------------------------------
# The models never see the key
# ---------------------------------------------------------------------------


def _model_payloads(env, payload: dict) -> Dict[str, str]:
    """Each slide role's model payload for one pipeline run, as JSON text."""
    env.skills.calls.clear()
    slide_pipeline_node(payload)
    return {
        role: json.dumps(env.skills.calls_for(role)[0]["payload"], default=str)
        for role in ("builder", "build_reviewer", "fixer", "fix_reviewer")
    }


def test_every_slide_roles_model_payload_is_byte_identical_with_and_without_the_key(
    graph_env,
):
    """White-free html, so the drop is a no-op and only the key differs."""
    env = graph_env
    clean = "<div class='slide'>content</div>"
    env.skills.set("builder", lambda p: builder_out(p, html=clean))
    env.skills.set(
        "build_reviewer",
        lambda p: review_out(p["position"], [finding("overflow", slide_index=p["position"])]),
    )
    env.skills.set("fixer", lambda p: fixer_out(p, html=clean))
    env.skills.set("fix_reviewer", lambda p: review_out(p["position"]))
    state = _branch_state(env, intent="build", deck_style=CALLOUT_STYLE)
    with_key = build_branch_payload(state, 1)
    assert with_key.get("one_ground") is True
    without_key = {k: v for k, v in with_key.items() if k != "one_ground"}

    keyed = _model_payloads(env, with_key)
    unkeyed = _model_payloads(env, without_key)

    assert keyed == unkeyed
    for role, text in keyed.items():
        assert "one_ground" not in text, role


def test_the_builders_model_payload_never_carries_the_key(graph_env):
    graph_env.skills.set("builder", builder_out)
    payload = build_branch_payload(
        _branch_state(graph_env, intent="build", deck_style=CALLOUT_STYLE), 1
    )
    assert payload.get("one_ground") is True

    builder_node(payload)

    (call,) = graph_env.skills.calls_for("builder")
    assert "one_ground" not in call["payload"]
