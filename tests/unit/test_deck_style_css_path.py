# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""``architect_node`` sanitises the architect's deck style and writes it into
``deck.css`` (architect deck style, plan Task 4; PLAN-CORRECTIONS C11, C12, C32;
Rulings R3, R4).

* **Sanitised before anything is committed.**  Every architect answer — the first
  and the retry — has ``deck_spec.deck_style`` and ``deck_changes.deck_style``
  cleaned by ``sanitise_deck_style`` before it is planned.  An at-rule, an
  unscoped selector or an oversized style never reaches the committed spec or
  ``deck.css``.  On a BUILD a style the sanitiser drops commits as
  ``deck_style=None`` and the deck still builds; on an EDIT a dropped
  ``deck_changes.deck_style`` refuses the answer with an ``invalid_deck_changes``
  problem naming the notes, which the one retry is handed (R4, C12).
* **Written after the template block.**  The pre-fan-out ``deck.css`` is the
  token stylesheet, the template block, then the committed deck style, and
  ``emitted_style_blocks`` carries the template block then the deck style, so the
  post-commit aggregate in ``deck_reviewer_node`` keeps both.
* **Old decks are unchanged.**  A spec with no deck style writes exactly what the
  base commit wrote: the pre-fan-out ``deck_write`` kwargs, ``emitted_style_blocks``
  and the post-commit ``deck.css`` are pinned as literals captured at the base
  commit (HEAD f8de8373), for a pinned and an unpinned deck.
* **The template's ``:root`` and ``@media`` survive (C11).**  ``merge_css`` keys
  ``:root`` by selector and an at-rule by its prelude, so a deck-style ``:root``
  or same-prelude ``@media`` would silently replace the template's.  The sanitiser
  drops both on a design-system deck (R3); the end-to-end guarantee is pinned
  here on the post-commit ``deck.css``.
* **A deck-style-only edit builds nothing (C32).**  No builder ``Send``; the deck
  reviewer (the arc review) still runs.

How this file asserts: on what was persisted (the deck row's ``css`` and
``deck_spec_json``), on the kwargs ``write_deck_level_columns`` was actually
handed (a pass-through spy), on the node's returned state, on the foreman's own
dispatch decision (``foreman_node`` then ``foreman_router``), and on the payload
the architect's retry call was handed.  Never on whether a helper was called.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import pytest
from langgraph.types import Send

from src.domain.deck_spec import DeckSpec, DeckStyle, DeckStyleComponent
from src.domain.deck_style import DECK_STYLE_MAX_CHARS, sanitise_deck_style
from src.domain.finding import DeckReviewOutput
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_operations import DeckChanges
from src.services.graph import nodes
from src.services.graph.nodes import architect_node, deck_reviewer_node, foreman_node
from src.services.graph.routers import foreman_router
from src.services.graph.state import scoped
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    TEMPLATE_STYLE_BLOCK,
    TEMPLATE_TOKEN_CSS,
    architect_build,
    graph_env,
    make_spec,
)
from tests.unit.test_architect_edit_operations import (
    _content,
    _ops_out,
    _replace,
    _seeded,
    _turn,
    _update,
)
from tests.unit.test_architect_edit_retry import _Answers
from tests.unit.test_architect_edit_retry import _turn as _retry_turn
from tests.unit.test_architect_insert_slide import (
    TURN,
    _edit_out,
    _persist,
    _persisted_spec,
    _revised,
    _rows,
)
from tests.unit.test_deck_style_module import _follower_parses_after

# ---------------------------------------------------------------------------
# Deck styles
# ---------------------------------------------------------------------------

#: A clean style: one ``.dk-`` rule, one component.  The sanitiser returns it as is.
CODE_CSS = ".dk-code{background:#fff;font-family:monospace}"
CODE_STYLE = DeckStyle(
    css=CODE_CSS,
    components=[
        DeckStyleComponent(
            name="code block",
            class_names=["dk-code"],
            use="any slide that shows code",
            example_html="<pre class='dk-code'>x = 1</pre>",
        )
    ],
)

#: Remote fetch and an unscoped selector, around a rule the sanitiser keeps.
HOSTILE_CSS = (
    "@import url(https://evil/x.css);\n"
    "body{}\n"
    "body{background:red}\n"
    ".dk-code{background:#fff;font-family:monospace}"
)
HOSTILE_STYLE = DeckStyle(css=HOSTILE_CSS, components=[])

#: Valid ``.dk-`` rules, over ``DECK_STYLE_MAX_CHARS`` in total.
OVERSIZED_CSS = "\n".join(
    f".dk-c{i}{{color:#{i % 10}{i % 10}{i % 10}}}" for i in range(700)
)
OVERSIZED_STYLE = DeckStyle(css=OVERSIZED_CSS, components=[])

#: Nothing a deck style may keep: the sanitiser drops the whole style.
UNSCOPED_STYLE = DeckStyle(css="body{color:red}", components=[])

#: The deck-style-only edit (plan Task 4): white code blocks become black.
OLD_STYLE = DeckStyle(css=".dk-code{background:#fff}", components=[])
NEW_STYLE = DeckStyle(css=".dk-code{background:#000}", components=[])

#: What a deck style must never put in ``deck.css`` or the committed spec.
HOSTILE_TEXT = ("@import", "evil", "https:", "body")

DROPPED_PREFIX = "deck_changes.deck_style was dropped:"

# ---------------------------------------------------------------------------
# The base commit's writes for a deck with no deck style (captured at HEAD
# f8de8373, before Task 4; make_spec((0, 1)), graph_env.state(), the default
# TemplateStub).  Pinned literally so any drift on an old deck is red.
# ---------------------------------------------------------------------------

_HEAD_META = '{"charset": "UTF-8", "viewport": "width=device-width, initial-scale=1.0"}'
_CHART_JS = ["https://cdn.jsdelivr.net/npm/chart.js"]


def _base_spec_json(design_contract: str) -> str:
    return (
        '{"title":"Stub Deck","audience":"Stub audience","purpose":"Stub purpose",'
        '"argument":"Stub argument","call_to_action":"Stub CTA",'
        '"narrative_arc":["open","middle","close"],'
        '"design_contract":' + design_contract + ","
        '"resolved_data":{"synthesis":"Stub synthesis","figures":[],"gaps":[]},'
        '"slides":[{"position":0,"purpose":"purpose-0","content_brief":"brief-0",'
        '"assumes":"assumes-0","hands_off":"hands-off-0","data_references":[],'
        '"slide_type":null,"template_section_index":null,"look":null},'
        '{"position":1,"purpose":"purpose-1","content_brief":"brief-1",'
        '"assumes":"assumes-1","hands_off":"hands-off-1","data_references":[],'
        '"slide_type":null,"template_section_index":null,"look":null}],'
        '"deck_style":null}'
    )


BASE_PINNED_DECK_WRITE = {
    "title": "Stub Deck",
    "external_scripts": _CHART_JS,
    "head_meta": _HEAD_META,
    "deck_spec": _base_spec_json(
        '{"design_system_id":7,"template_id":3,"slide_style_id":null}'
    ),
    "modified_by": "graph-user@example.com",
    "user_visible": True,
    "css": ":root { --brand: #123456; }\n\n.slide { color: #123456; }",
}
BASE_UNPINNED_DECK_WRITE = {
    "title": "Stub Deck",
    "external_scripts": _CHART_JS,
    "head_meta": _HEAD_META,
    "deck_spec": _base_spec_json(
        '{"design_system_id":null,"template_id":null,"slide_style_id":null}'
    ),
    "modified_by": "graph-user@example.com",
    "user_visible": True,
    # No "css" key at all: an unpinned deck resolves no deterministic CSS, and
    # passing "" would erase the stored stylesheet.
}
BASE_PINNED_STYLE_BLOCKS = {"turn": "turn-1", "vals": [".slide { color: #123456; }"]}
BASE_UNPINNED_STYLE_BLOCKS = {"turn": "turn-1", "vals": []}
BASE_PINNED_POST_COMMIT_CSS = ":root {\n--brand: #123456;\n}\n\n.slide {\ncolor: #123456;\n}"
BASE_UNPINNED_POST_COMMIT_CSS = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spy_on_deck_writes(monkeypatch) -> List[Dict[str, Any]]:
    """Every ``write_deck_level_columns`` call the graph nodes make, kwargs whole.

    A pass-through: the real writer runs, so the deck row is what it would be.
    """
    real = nodes.write_deck_level_columns
    calls: List[Dict[str, Any]] = []

    def spy(session_id, **kwargs):
        calls.append({"session_id": session_id, **kwargs})
        return real(session_id, **kwargs)

    monkeypatch.setattr(nodes, "write_deck_level_columns", spy)
    return calls


def _pin(env) -> None:
    """A design-system deck: the brand resolves as design-system-active."""
    env.style.design_system_active = True


def _pinned_spec(positions=(0, 1), **kw) -> DeckSpec:
    return make_spec(positions, design_system_id=7, template_id=3, **kw)


def _with_style(spec: DeckSpec, style: Optional[DeckStyle]) -> DeckSpec:
    return spec.model_copy(update={"deck_style": style})


def _land_rows(env, count: int) -> None:
    """The rows the builders would have committed (none exist on a fresh build)."""
    if not env.rows():
        env.seed_slides([f"<div class='slide'>slide {p}</div>" for p in range(count)])


def _post_commit(env, merged: Dict[str, Any]) -> Dict[str, Any]:
    """Run the deck reviewer (the post-commit aggregate, then the arc review)."""
    env.skills.set("deck_reviewer", DeckReviewOutput(findings=[]))
    return deck_reviewer_node(merged)


def _dispatch(merged: Dict[str, Any]):
    """The foreman's first wake, then its router: the Sends, or where it goes."""
    wake = foreman_node(merged)
    return foreman_router({**merged, **wake})


def _sent_positions(route) -> List[int]:
    assert isinstance(route, list) and all(isinstance(s, Send) for s in route), (
        f"expected builder Sends, got {route!r}"
    )
    assert all(s.node == "slide_pipeline" for s in route)
    return sorted(s.arg["position"] for s in route)


def _assert_no_hostile_text(text: Optional[str], where: str) -> None:
    for bad in HOSTILE_TEXT:
        assert bad not in (text or ""), f"{bad!r} reached {where}: {text!r}"


def _architect_writes(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The pre-fan-out write(s): the architect's, the only ones carrying a deck_spec."""
    return [c for c in calls if "deck_spec" in c]


def _one_retry_problems(answers: _Answers, env) -> List[Dict[str, Any]]:
    """Exactly two architect calls, the second the first payload plus ``rejected_edit``.

    Returns the second payload's problems, JSON round-tripped.  ``your_previous_answer``
    is checked for its shape only: whether it echoes the answer as given or as
    sanitised is the implementation's choice.
    """
    assert len(env.skills.calls_for("architect")) == 2, "expected exactly one retry"
    original, retry = answers.seen
    assert "rejected_edit" not in original
    assert {k: v for k, v in retry.items() if k != "rejected_edit"} == original
    rejected = json.loads(json.dumps(retry["rejected_edit"]))
    assert set(rejected) == {"your_previous_answer", "problems"}, rejected
    assert rejected["your_previous_answer"]["intent"] == "edit"
    problems = rejected["problems"]
    for problem in problems:
        assert set(problem) == {"code", "positions", "detail"}, problem
    return problems


# ---------------------------------------------------------------------------
# 1. The deck style is written after the template block, and survives the aggregate
# ---------------------------------------------------------------------------


def test_build_writes_deck_style_after_template_css(graph_env, monkeypatch):
    """A pinned build with a clean deck style: the pre-fan-out ``deck.css`` is the
    token stylesheet, the template block, then the deck style's ``.dk-code`` rule,
    in that order; the style travels in ``emitted_style_blocks`` after the template
    block; and the post-commit aggregate keeps the template rule and the deck
    style's, still in that order.

    Sabotage: write the deck style first, or not at all, or leave it out of
    ``emitted_style_blocks`` and rewrite the column at post-commit -> red."""
    _pin(graph_env)
    calls = _spy_on_deck_writes(monkeypatch)
    spec = _with_style(_pinned_spec(), CODE_STYLE)
    graph_env.skills.set("architect", architect_build(spec))

    state = graph_env.state()
    updates = architect_node(state)

    assert updates["error_state"] is None
    assert updates["deck_spec"].deck_style == CODE_STYLE
    assert _persisted_spec(graph_env).deck_style == CODE_STYLE

    css = graph_env.deck_row().css
    assert css is not None and CODE_CSS in css, css
    assert TEMPLATE_TOKEN_CSS in css and TEMPLATE_STYLE_BLOCK in css, css
    assert css.index(TEMPLATE_TOKEN_CSS) < css.index(TEMPLATE_STYLE_BLOCK) < css.index(
        ".dk-code"
    ), f"the deck style must follow the template block: {css!r}"
    (write,) = _architect_writes(calls)
    assert write["css"] == css

    assert updates["emitted_style_blocks"] == scoped(
        TURN, [TEMPLATE_STYLE_BLOCK, CODE_CSS]
    )

    merged = {**state, **updates}
    _land_rows(graph_env, 2)
    review = _post_commit(graph_env, merged)

    assert review.get("error_state") is None
    post = graph_env.deck_row().css
    assert ".slide" in post and "#123456" in post, post
    assert ".dk-code" in post and "#fff" in post and "monospace" in post, post
    assert "--brand" in post, post
    assert post.index(".slide") < post.index(".dk-code"), post


# ---------------------------------------------------------------------------
# 2. Old decks: byte-identical writes (the oracle — passes at the base commit)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pinned, deck_write, style_blocks, post_commit_css",
    [
        (True, BASE_PINNED_DECK_WRITE, BASE_PINNED_STYLE_BLOCKS, BASE_PINNED_POST_COMMIT_CSS),
        (
            False,
            BASE_UNPINNED_DECK_WRITE,
            BASE_UNPINNED_STYLE_BLOCKS,
            BASE_UNPINNED_POST_COMMIT_CSS,
        ),
    ],
    ids=["pinned", "unpinned"],
)
def test_deck_without_style_writes_css_as_today(
    graph_env, monkeypatch, pinned, deck_write, style_blocks, post_commit_css
):
    """A build whose spec has no deck style writes exactly what the base commit
    wrote: the pre-fan-out ``deck_write`` kwargs, ``emitted_style_blocks`` and the
    post-commit ``deck.css``, all literals captured at HEAD f8de8373.

    This is the old-deck oracle, so it passes before Task 4 is implemented."""
    if pinned:
        _pin(graph_env)
    calls = _spy_on_deck_writes(monkeypatch)
    spec = _pinned_spec() if pinned else make_spec((0, 1))
    graph_env.skills.set("architect", architect_build(spec))

    state = graph_env.state()
    updates = architect_node(state)

    assert updates["error_state"] is None
    (write,) = _architect_writes(calls)
    mutation = write.pop("mutation")
    assert write.pop("session_id") == graph_env.session_id
    assert write == deck_write
    assert (
        mutation.operation,
        mutation.object_type,
        mutation.object_id,
        mutation.suppress_nested_events,
        mutation.actor.actor_session_id,
        mutation.actor.graph_release_id,
    ) == ("write_deck_level", "deck", None, False, graph_env.session_id, 1)
    assert updates["emitted_style_blocks"] == style_blocks
    assert graph_env.deck_row().css == deck_write.get("css")

    _land_rows(graph_env, 2)
    _post_commit(graph_env, {**state, **updates})
    assert graph_env.deck_row().css == post_commit_css


# ---------------------------------------------------------------------------
# 3. A hostile deck style is sanitised before anything is committed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pinned", [False, True], ids=["unpinned", "pinned"])
def test_build_with_hostile_deck_style_is_sanitised(graph_env, monkeypatch, pinned):
    """``@import url(https://evil/x.css)`` and ``body{}`` reach neither ``deck.css``
    (pre-fan-out or post-commit) nor the committed spec; the ``.dk-code`` rule
    beside them is kept and written.  ``deck.css`` is exactly the deterministic CSS
    followed by the COMMITTED (cleaned) deck style.

    Sabotage: commit the answer's style unsanitised, or sanitise the spec but write
    the raw CSS -> red."""
    if pinned:
        _pin(graph_env)
    calls = _spy_on_deck_writes(monkeypatch)
    base = _pinned_spec() if pinned else make_spec((0, 1))
    graph_env.skills.set("architect", architect_build(_with_style(base, HOSTILE_STYLE)))

    state = graph_env.state()
    updates = architect_node(state)

    assert updates["error_state"] is None
    assert updates["architect_intent"] == "build"
    committed = updates["deck_spec"].deck_style
    assert committed is not None, "the .dk-code rule should have survived"
    _assert_no_hostile_text(committed.css, "the committed spec (state)")
    assert ".dk-code" in committed.css
    persisted = _persisted_spec(graph_env)
    assert persisted.deck_style == committed
    _assert_no_hostile_text(graph_env.deck_row().deck_spec_json, "the persisted deck_spec")

    css = graph_env.deck_row().css
    _assert_no_hostile_text(css, "deck.css (pre-fan-out)")
    expected = "\n\n".join(
        part
        for part in (
            (TEMPLATE_TOKEN_CSS, TEMPLATE_STYLE_BLOCK) if pinned else ()
        )
        + (committed.css,)
    )
    assert css == expected
    (write,) = _architect_writes(calls)
    _assert_no_hostile_text(write["css"], "the pre-fan-out css kwarg")
    for block in updates["emitted_style_blocks"]["vals"]:
        _assert_no_hostile_text(block, "emitted_style_blocks")

    _land_rows(graph_env, 2)
    _post_commit(graph_env, {**state, **updates})
    post = graph_env.deck_row().css
    _assert_no_hostile_text(post, "deck.css (post-commit)")
    assert ".dk-code" in post


def test_full_spec_edit_with_hostile_deck_style_is_sanitised(graph_env):
    """An edit given as a revised ``deck_spec`` (no operations) on an unchanged
    contract commits the PERSISTED deck style, whatever its ``deck_spec`` carries
    (Rulings R8, R20; C18).  So a hostile ``deck_spec.deck_style`` reaches neither
    the committed spec nor ``deck.css``: not its ``@import`` or ``body`` rules,
    and not the ``.dk-code`` rule the sanitiser would keep of it either.  (On a
    contract change the answer's style is kept, sanitised:
    ``test_deck_style_edits.py::test_full_spec_edit_changing_the_contract_keeps_the_answers_sanitised_style``.)

    Sabotage: commit the answer's style, sanitised or not -> red."""
    seeded, _ = _seeded(graph_env, (0, 1, 2))
    prior = _with_style(seeded, OLD_STYLE)
    _persist(graph_env, prior)
    revised = _with_style(_revised(prior, {1: "brief REVISED"}), HOSTILE_STYLE)

    t = _turn(graph_env, _edit_out(revised, [1]))

    assert t.updates["error_state"] is None
    assert t.updates["architect_intent"] == "edit"
    committed = t.updates["deck_spec"].deck_style
    assert committed == OLD_STYLE, "the persisted deck style was not carried"
    _assert_no_hostile_text(committed.css, "the committed spec (state)")
    assert _persisted_spec(graph_env).deck_style == OLD_STYLE
    _assert_no_hostile_text(graph_env.deck_row().deck_spec_json, "the persisted deck_spec")
    css = graph_env.deck_row().css
    assert css == OLD_STYLE.css
    _assert_no_hostile_text(css, "deck.css")


# ---------------------------------------------------------------------------
# 4. An oversized deck style: the build goes ahead without it
# ---------------------------------------------------------------------------


def test_build_with_oversized_deck_style_builds_without_it(graph_env, monkeypatch):
    """A style over ``DECK_STYLE_MAX_CHARS`` is dropped on a build: the committed
    spec has ``deck_style is None``, every slide is dispatched, the turn succeeds,
    and the deck-level writes are byte-identical to an old deck's.

    Sabotage: commit the oversized style, or refuse the build -> red."""
    assert len(OVERSIZED_CSS) > DECK_STYLE_MAX_CHARS
    calls = _spy_on_deck_writes(monkeypatch)
    graph_env.skills.set(
        "architect", architect_build(_with_style(make_spec((0, 1)), OVERSIZED_STYLE))
    )

    state = graph_env.state()
    updates = architect_node(state)

    assert updates["architect_intent"] == "build"
    assert updates["error_state"] is None
    assert updates["target_positions"] is None
    assert updates["deck_spec"].deck_style is None
    assert _persisted_spec(graph_env).deck_style is None
    assert ".dk-c1" not in (graph_env.deck_row().deck_spec_json or "")

    merged = {**state, **updates}
    assert _sent_positions(_dispatch(merged)) == [0, 1]

    (write,) = _architect_writes(calls)
    write.pop("mutation")
    write.pop("session_id")
    assert write == BASE_UNPINNED_DECK_WRITE
    assert updates["emitted_style_blocks"] == BASE_UNPINNED_STYLE_BLOCKS
    assert graph_env.deck_row().css is None

    _land_rows(graph_env, 2)
    review = _post_commit(graph_env, merged)
    assert review.get("error_state") is None
    assert graph_env.deck_row().css == BASE_UNPINNED_POST_COMMIT_CSS


# ---------------------------------------------------------------------------
# 5. A deck-style-only edit rewrites deck.css and builds nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pinned", [False, True], ids=["unpinned", "pinned"])
def test_deck_style_only_edit_rewrites_css_and_builds_nothing(graph_env, pinned):
    """``operations=[]`` with ``deck_changes.deck_style`` taking ``.dk-code`` from
    ``#fff`` to ``#000`` on a deck whose stored ``deck.css`` already carries the old
    style (as the turn that wrote it left it).  No builder ``Send``, no row
    touched; ``deck.css`` holds ``#000`` and not ``#fff``, before and after the
    post-commit aggregate; the committed spec's deck style is the new one.  The
    deck reviewer (the arc review) still runs (C32).

    Sabotage: leave deck.css alone on an edit, or merge the new style into the old
    column instead of rewriting it -> red."""
    from src.api.services.deck_level_writer import write_deck_level_columns

    if pinned:
        _pin(graph_env)
    prior_plain, _ = _seeded(graph_env, (0, 1, 2))
    prior = _with_style(
        prior_plain.model_copy(
            update={"design_contract": _pinned_spec().design_contract}
        )
        if pinned
        else prior_plain,
        OLD_STYLE,
    )
    _persist(graph_env, prior)
    deterministic = (
        TEMPLATE_TOKEN_CSS + "\n\n" + TEMPLATE_STYLE_BLOCK + "\n\n" if pinned else ""
    )
    write_deck_level_columns(graph_env.session_id, css=deterministic + OLD_STYLE.css)
    rows_before = _rows(graph_env)

    t = _turn(
        graph_env,
        _ops_out([], DeckChanges(deck_style=NEW_STYLE), message="Darkening the code."),
    )

    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == []
    assert t.updates["deck_spec"].deck_style == NEW_STYLE
    assert _persisted_spec(graph_env).deck_style == NEW_STYLE

    route = _dispatch(t.merged)
    assert route == "deck_reviewer", f"a deck-style-only edit dispatched {route!r}"
    assert _rows(graph_env) == rows_before, "a deck-style-only edit touched a row"

    css = graph_env.deck_row().css
    assert "#000" in css and "#fff" not in css, css
    if pinned:
        assert css.index(TEMPLATE_STYLE_BLOCK) < css.index(".dk-code"), css

    reviews_before = len(graph_env.skills.calls_for("deck_reviewer"))
    _post_commit(graph_env, t.merged)
    post = graph_env.deck_row().css
    assert ".dk-code" in post and "#000" in post and "#fff" not in post, post
    assert len(graph_env.skills.calls_for("deck_reviewer")) == reviews_before + 1, (
        "C32: the arc review still runs on a deck-style-only edit"
    )
    assert graph_env.skills.calls_for("builder") == []


# ---------------------------------------------------------------------------
# 6. C11: a deck style cannot displace the template's :root or @media rules
# ---------------------------------------------------------------------------

#: A template block with a ``:root`` rule and an ``@media`` block (C11).
C11_TEMPLATE_BLOCK = (
    ":root{--t:1}\n@media (max-width:900px){.slide{x:1}}\n.slide{color:#123456}"
)
#: A deck style that tries a same-key ``:root`` and a same-prelude ``@media``.
C11_STYLE = DeckStyle(
    css=(
        ":root{--dk-a:#000}\n"
        "@media (max-width:900px){.dk-a{color:red}}\n"
        ".dk-a{color:#000}"
    ),
    components=[],
)
#: How the post-commit aggregate renders the template's rules at the base commit
#: (captured at HEAD f8de8373 with C11_TEMPLATE_BLOCK and no deck style).
C11_TEMPLATE_ROOT_AFTER_MERGE = ":root {\n--t:1\n}"
C11_TEMPLATE_MEDIA_AFTER_MERGE = "@media (max-width:900px){.slide{x:1}}"


def _flag_follows_the_contract(env, monkeypatch) -> None:
    """The style resolver reports a design system exactly when the contract names one.

    The default ``StyleStub`` answers one fixed flag for every contract, which cannot
    tell the inbound brand's flag from the committed contract's.
    """
    stub = env.style

    def resolve(config):
        stub.design_system_active = config.design_system_id is not None
        return stub(config)

    monkeypatch.setattr("src.services.agent_resolution.resolve_style_source", resolve)


@pytest.mark.parametrize(
    "pinned_this_turn", [False, True], ids=["design-system-deck", "pinned-this-turn"]
)
def test_deck_style_cannot_displace_template_root_or_media_rules(
    graph_env, monkeypatch, pinned_this_turn
):
    """``merge_css`` keys ``:root`` by selector and ``@media`` by its prelude, so a
    deck-style ``:root{--dk-a:#000}`` or ``@media (max-width:900px){.dk-a{…}}``
    merged after the template block would replace the template's own.  On a
    design-system deck the sanitiser removes both (R3) and the post-commit
    ``deck.css`` still holds the template's ``:root`` and ``@media`` rules exactly
    as the base commit renders them, while the deck style's plain ``.dk-a`` rule is
    written after them.

    ``pinned-this-turn``: the session starts unpinned (the inbound brand is not a
    design system) and the build's spec pins one.  The sanitiser must use the
    RE-resolved brand's flag (controller override), or ``:root{--dk-a:#000}``
    survives and replaces the template's ``:root``.

    Sabotage: skip the :root/at-rule drop, sanitise with the inbound brand's flag,
    or re-merge the raw answer CSS at post-commit -> red."""
    if pinned_this_turn:
        _flag_follows_the_contract(graph_env, monkeypatch)
    else:
        _pin(graph_env)
    graph_env.template.style_block = C11_TEMPLATE_BLOCK
    graph_env.skills.set(
        "architect", architect_build(_with_style(_pinned_spec(), C11_STYLE))
    )

    state = graph_env.state()
    updates = architect_node(state)

    assert updates["error_state"] is None
    assert updates["design_system_active"] is True
    if pinned_this_turn:
        architect_call = graph_env.skills.calls_for("architect")[0]
        assert architect_call["design_system_active"] is False, (
            "fixture: the inbound brand must not be a design system"
        )
    committed = updates["deck_spec"].deck_style
    assert committed is not None and ".dk-a" in committed.css
    assert ":root" not in committed.css and "@media" not in committed.css, committed.css
    assert "--dk-a" not in committed.css

    pre = graph_env.deck_row().css
    assert C11_TEMPLATE_BLOCK in pre, pre
    assert pre.index(C11_TEMPLATE_BLOCK) < pre.rindex(".dk-a"), pre

    _land_rows(graph_env, 2)
    _post_commit(graph_env, {**state, **updates})
    post = graph_env.deck_row().css

    assert C11_TEMPLATE_ROOT_AFTER_MERGE in post, (
        f"the template's :root rule was replaced or rewritten: {post!r}"
    )
    assert C11_TEMPLATE_MEDIA_AFTER_MERGE in post, (
        f"the template's @media block was replaced or rewritten: {post!r}"
    )
    assert post.count("@media") == 1, post
    assert "--dk-a" not in post and "color:red" not in post, post
    assert ".dk-a" in post and post.index(C11_TEMPLATE_MEDIA_AFTER_MERGE) < post.index(
        ".dk-a"
    ), f"the deck style's .dk-a rule must be written after the template's: {post!r}"


#: A fresh palette plus a rule, and an @media the sanitiser drops under any flag.
PALETTE_STYLE = DeckStyle(
    css=(
        ":root{--dk-a:#000}\n"
        "@media (max-width:900px){.dk-a{color:red}}\n"
        ".dk-a{color:var(--dk-a)}"
    ),
    components=[],
)
UNPINNED_CONTRACT = make_spec((0,)).design_contract
PINNED_CONTRACT = make_spec((0,), design_system_id=7, template_id=3).design_contract


@pytest.mark.parametrize(
    "prior_contract, new_contract, root_kept",
    [(UNPINNED_CONTRACT, PINNED_CONTRACT, False), (PINNED_CONTRACT, UNPINNED_CONTRACT, True)],
    ids=["pins-a-design-system", "unpins-the-design-system"],
)
def test_edit_changing_the_contract_sanitises_under_the_new_contracts_flag(
    graph_env, monkeypatch, prior_contract, new_contract, root_kept
):
    """An operations edit whose ``deck_changes`` changes the design contract AND
    brings a fresh deck style.  The style is sanitised under the NEW contract's
    flag (the re-resolved brand), never the inbound one:

    * ``pins-a-design-system``: unpinned deck -> 7/3.  The new brand is a design
      system, so ``:root{--dk-a:#000}`` is dropped (R3) and the template's ``:root``
      survives the post-commit aggregate.
    * ``unpins-the-design-system``: 7/3 -> unpinned.  No design system, so the
      ``--dk-`` palette is kept and written.

    The ``@media`` is dropped either way, so a raw (unsanitised) commit is red too.

    Sabotage: sanitise with the inbound brand's flag -> both cases red."""
    _flag_follows_the_contract(graph_env, monkeypatch)
    graph_env.template.style_block = C11_TEMPLATE_BLOCK
    prior_plain, _ = _seeded(graph_env, (0, 1, 2))
    prior = prior_plain.model_copy(update={"design_contract": prior_contract})
    _persist(graph_env, prior)

    t = _turn(
        graph_env,
        _ops_out(
            [],
            DeckChanges(design_contract=new_contract, deck_style=PALETTE_STYLE),
            message="Restyling.",
        ),
    )

    inbound_flag = graph_env.skills.calls_for("architect")[0]["design_system_active"]
    assert inbound_flag is root_kept, "fixture: the inbound brand is the OLD contract's"
    assert t.updates["error_state"] is None
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["design_system_active"] is (not root_kept)
    assert t.updates["deck_spec"].design_contract == new_contract
    committed = t.updates["deck_spec"].deck_style
    assert committed is not None and ".dk-a" in committed.css
    assert "@media" not in committed.css, committed.css
    assert _persisted_spec(graph_env).deck_style == committed

    css = graph_env.deck_row().css
    assert css is not None and ".dk-a" in css, css
    if root_kept:
        assert ":root{--dk-a:#000}" in committed.css, committed.css
        assert css == committed.css, css
    else:
        assert ":root" not in committed.css and "--dk-a:#000" not in committed.css
        assert css.index(C11_TEMPLATE_BLOCK) < css.rindex(".dk-a"), css
        _land_rows(graph_env, 3)
        _post_commit(graph_env, t.merged)
        post = graph_env.deck_row().css
        assert C11_TEMPLATE_ROOT_AFTER_MERGE in post, post
        assert C11_TEMPLATE_MEDIA_AFTER_MERGE in post, post
        assert "--dk-a:#000" not in post, post


# ---------------------------------------------------------------------------
# 6b. Every sanitiser note is logged with the session id
# ---------------------------------------------------------------------------


def _logged_with_session(caplog, text: str, session_id: str) -> List[logging.LogRecord]:
    """Records whose message holds *text* and which carry *session_id* (extra or text)."""
    return [
        r
        for r in caplog.records
        if text in r.getMessage()
        and (getattr(r, "session_id", None) == session_id or session_id in r.getMessage())
    ]


@pytest.mark.parametrize("where", ["build-deck_spec", "edit-deck_changes"])
def test_each_sanitiser_note_is_logged_with_the_session_id(graph_env, caplog, where):
    """Each note ``sanitise_deck_style`` returns for the answer's deck style is
    logged, with the turn's ``session_id`` (as an ``extra`` field or in the text).
    Level and logger are left to the implementation.

    Sabotage: sanitise silently, or log without the session id -> red."""
    _, notes = sanitise_deck_style(HOSTILE_STYLE, design_system_active=False)
    assert len(notes) >= 2, notes
    if where == "build-deck_spec":
        out = architect_build(_with_style(make_spec((0, 1)), HOSTILE_STYLE))
    else:
        _seeded(graph_env, (0, 1, 2))
        out = _ops_out([], DeckChanges(deck_style=HOSTILE_STYLE), message="Styling.")

    with caplog.at_level(logging.DEBUG):
        t = _turn(graph_env, out)

    assert t.updates["error_state"] is None
    for note in notes:
        assert _logged_with_session(caplog, note, graph_env.session_id), (
            f"note not logged with the session id: {note!r}"
        )


# ---------------------------------------------------------------------------
# 7. R4: an edit whose deck style the sanitiser drops is refused, with its notes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dropped", [UNSCOPED_STYLE, OVERSIZED_STYLE], ids=["unscoped-only", "oversized"]
)
def test_edit_with_dropped_deck_style_is_refused_with_its_notes(graph_env, dropped):
    """An edit whose ONLY change is a ``deck_changes.deck_style`` the sanitiser
    drops entirely is refused, and the one retry is told why: a single
    ``invalid_deck_changes`` problem, no positions, whose detail starts
    ``deck_changes.deck_style was dropped:`` and carries the sanitiser's notes —
    never C12's unexplained ``nothing_to_do``.  The retry (a clean deck-style
    edit) lands; nothing of the dropped style is committed or written.  (Beside
    other changes the style is ignored instead, Ruling R31: the next test.)

    Sabotage: let the style drop silently (nothing_to_do), or refuse without the
    notes -> red."""
    prior, _ = _seeded(graph_env, (0, 1, 2))
    rows_before = _rows(graph_env)
    _, notes = sanitise_deck_style(dropped, design_system_active=False)
    assert notes, "the fixture style must be one the sanitiser drops with notes"
    first = _ops_out([], DeckChanges(deck_style=dropped), message="FIRST")
    second = _ops_out([], DeckChanges(deck_style=NEW_STYLE), message="SECOND")
    answers = _Answers(first, second)

    t = _retry_turn(graph_env, answers)

    problems = _one_retry_problems(answers, graph_env)
    assert [p["code"] for p in problems] == ["invalid_deck_changes"], problems
    (problem,) = problems
    assert problem["positions"] == []
    assert problem["detail"].startswith(DROPPED_PREFIX), problem["detail"]
    for note in notes:
        assert note in problem["detail"], (note, problem["detail"])

    # The retry's clean style lands; the dropped one is nowhere.
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == []
    assert t.updates["deck_spec"].deck_style == NEW_STYLE
    persisted = _persisted_spec(graph_env)
    assert persisted.deck_style == NEW_STYLE
    assert [s.content_brief for s in persisted.slides] == [
        s.content_brief for s in prior.slides
    ], "the refused answer's update landed"
    assert _rows(graph_env) == rows_before
    assert graph_env.deck_row().css == NEW_STYLE.css


def test_dropped_deck_style_refusal_degrades_with_its_notes_when_the_retry_is_refused_too(
    graph_env,
):
    """Both answers carry a deck style the sanitiser drops: the turn degrades
    ``edit_operations_rejected`` with the second answer's ``invalid_deck_changes``
    problem (and its notes) on the refusal row, and nothing is written."""
    _seeded(graph_env, (0, 1, 2))
    css_before = graph_env.deck_row().css
    spec_before = graph_env.deck_row().deck_spec_json
    _, notes = sanitise_deck_style(UNSCOPED_STYLE, design_system_active=False)
    first = _ops_out([], DeckChanges(deck_style=UNSCOPED_STYLE), message="FIRST")
    second = _ops_out([], DeckChanges(deck_style=UNSCOPED_STYLE), message="SECOND")
    answers = _Answers(first, second)

    t = _retry_turn(graph_env, answers)

    assert len(graph_env.skills.calls_for("architect")) == 2
    assert t.updates["architect_intent"] == "discuss"
    assert t.updates["error_state"]["code"] == "edit_operations_rejected"
    assert t.updates["error_state"]["message"].startswith(DROPPED_PREFIX)
    refusal = t.rows[-1]["metadata"]["architect_refusal"]
    assert [p["code"] for p in refusal["problems"]] == ["invalid_deck_changes"]
    for note in notes:
        assert note in refusal["problems"][0]["detail"]
    assert graph_env.deck_row().css == css_before
    assert graph_env.deck_row().deck_spec_json == spec_before


@pytest.mark.parametrize("beside", ["beside-an-update", "beside-a-title-change"])
def test_dropped_deck_style_beside_other_changes_is_ignored_and_the_rest_applies(
    graph_env, caplog, beside
):
    """Ruling R31 (final review risk 1): an edit whose ``deck_changes.deck_style``
    the sanitiser drops whole, but which ALSO carries operations or another
    ``deck_changes`` field, is not refused.  The style is ignored, its notes are
    logged with the session id, and the rest lands in one call: the update (or
    the new title) is committed and the persisted deck style is kept.  An old
    prompt that fills ``deck_style`` with unprefixed classes no longer costs the
    user their slide edits.

    Sabotage: refuse as R4 does for a style-only edit (a retry, and the update
    never lands without one), or skip the log -> red."""
    prior_plain, _ = _seeded(graph_env, (0, 1, 2))
    prior = _with_style(prior_plain, OLD_STYLE)
    _persist(graph_env, prior)
    _, notes = sanitise_deck_style(UNSCOPED_STYLE, design_system_active=False)
    assert notes, "the fixture style must be one the sanitiser drops with notes"
    if beside == "beside-an-update":
        out = _ops_out(
            [_update(1, _content("UPDATED"))],
            DeckChanges(deck_style=UNSCOPED_STYLE),
            message="Updating slide 2.",
        )
    else:
        out = _ops_out(
            [],
            DeckChanges(title="A NEW TITLE", deck_style=UNSCOPED_STYLE),
            message="Retitling.",
        )

    with caplog.at_level(logging.DEBUG):
        t = _turn(graph_env, out)

    assert len(graph_env.skills.calls_for("architect")) == 1, "R31: the edit is not retried"
    assert t.updates["error_state"] is None, t.updates["error_state"]
    assert t.updates["architect_intent"] == "edit"
    persisted = _persisted_spec(graph_env)
    assert t.updates["deck_spec"].deck_style == OLD_STYLE
    assert persisted.deck_style == OLD_STYLE, "the persisted deck style must be kept"
    if beside == "beside-an-update":
        assert t.updates["target_positions"] == [1]
        assert persisted.slides[1].content_brief == "brief UPDATED"
    else:
        assert t.updates["target_positions"] == []
        assert persisted.title == "A NEW TITLE"
    assert "body" not in (graph_env.deck_row().css or "")

    ignored = _logged_with_session(caplog, "deck_style_ignored", graph_env.session_id)
    assert ignored, "the ignored style must be logged with the session id"
    for note in notes:
        assert any(note in r.getMessage() for r in ignored), (note, ignored)


# ---------------------------------------------------------------------------
# 8. The retry answer is sanitised too
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("retry_intent", ["edit", "build"])
def test_retry_answer_deck_style_is_sanitised(graph_env, retry_intent):
    """The first answer is refused for a reason that has nothing to do with style
    (it replaces a slide the deck does not have); the retry carries the hostile
    style — in ``deck_changes`` (an edit) or in ``deck_spec`` (a build).  The retry
    lands with the ``@import`` and ``body`` rules gone from the committed spec and
    from ``deck.css``, and the ``.dk-code`` rule kept.

    Sabotage: sanitise only the first answer -> red."""
    prior, _ = _seeded(graph_env, (0, 1, 2))
    first = _ops_out([_replace(29, _content("X"))], message="FIRST")
    if retry_intent == "edit":
        second = _ops_out([], DeckChanges(deck_style=HOSTILE_STYLE), message="SECOND")
    else:
        second = ArchitectOutput(
            intent="build",
            message="SECOND",
            deck_spec=_with_style(prior, HOSTILE_STYLE),
        )
    answers = _Answers(first, second)

    t = _retry_turn(graph_env, answers)

    problems = _one_retry_problems(answers, graph_env)
    assert [p["code"] for p in problems] == ["unknown_slide"], problems
    assert t.updates["error_state"] is None
    assert t.updates["architect_intent"] == retry_intent
    committed = t.updates["deck_spec"].deck_style
    assert committed is not None and ".dk-code" in committed.css
    _assert_no_hostile_text(committed.css, "the committed spec (state)")
    persisted = _persisted_spec(graph_env)
    assert persisted.deck_style == committed
    _assert_no_hostile_text(graph_env.deck_row().deck_spec_json, "the persisted deck_spec")
    css = graph_env.deck_row().css
    assert css == committed.css
    _assert_no_hostile_text(css, "deck.css")


# ---------------------------------------------------------------------------
# 9. R18 (I1): a style carried onto a design system is sanitised again
# ---------------------------------------------------------------------------

#: A palette plus a rule: what the sanitiser keeps on a deck with no design system.
CARRIED_STYLE = DeckStyle(css=":root{--dk-a:#000}\n.dk-a{color:var(--dk-a)}", components=[])


@pytest.mark.parametrize(
    "session_contract",
    [None, PINNED_CONTRACT],
    ids=["pins-a-design-system-without-a-fresh-style", "session-already-on-the-design-system"],
)
def test_edit_changing_the_contract_resanitises_the_carried_deck_style(
    graph_env, monkeypatch, session_contract
):
    """An unpinned deck's persisted style keeps its ``:root`` palette.  An operations
    edit pins 7/3 through ``deck_changes.design_contract`` and brings NO deck style,
    so the persisted one is carried.  It is sanitised again under the committed
    contract's flag: the ``:root`` goes (R3), so the template's ``:root`` and
    ``@media`` survive the post-commit aggregate (C11).

    ``session-already-on-the-design-system``: the session's contract is already
    7/3, so the inbound brand is a design system too and the flag does not change
    between the inbound brand and the plan's.  The carried style was still
    committed under no design system, so it must be cleaned all the same.

    Sabotage: carry the persisted style through unsanitised -> red."""
    from src.api.services.deck_level_writer import write_deck_level_columns

    _flag_follows_the_contract(graph_env, monkeypatch)
    if session_contract is not None:
        monkeypatch.setattr(nodes, "_session_contract", lambda _sid: session_contract)
    graph_env.template.style_block = C11_TEMPLATE_BLOCK
    clean, _ = sanitise_deck_style(CARRIED_STYLE, design_system_active=False)
    assert clean is CARRIED_STYLE, "fixture: the carried style is clean without a design system"
    prior_plain, _ = _seeded(graph_env, (0, 1, 2))
    _persist(
        graph_env,
        _with_style(
            prior_plain.model_copy(update={"design_contract": UNPINNED_CONTRACT}), CARRIED_STYLE
        ),
    )
    write_deck_level_columns(graph_env.session_id, css=CARRIED_STYLE.css)

    t = _turn(
        graph_env,
        _ops_out([], DeckChanges(design_contract=PINNED_CONTRACT), message="Pinning."),
    )

    assert t.updates["error_state"] is None
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["design_system_active"] is True
    assert t.updates["deck_spec"].design_contract == PINNED_CONTRACT
    committed = t.updates["deck_spec"].deck_style
    assert committed is not None and ".dk-a" in committed.css
    assert ":root" not in committed.css and "--dk-a:#000" not in committed.css, committed.css
    assert _persisted_spec(graph_env).deck_style == committed

    pre = graph_env.deck_row().css
    assert C11_TEMPLATE_BLOCK in pre, pre
    assert pre.index(C11_TEMPLATE_BLOCK) < pre.rindex(".dk-a"), pre
    assert "--dk-a:#000" not in pre, pre

    _land_rows(graph_env, 3)
    _post_commit(graph_env, t.merged)
    post = graph_env.deck_row().css
    assert C11_TEMPLATE_ROOT_AFTER_MERGE in post, post
    assert C11_TEMPLATE_MEDIA_AFTER_MERGE in post, post
    assert "--dk-a:#000" not in post, post


def test_carried_deck_style_that_cleans_to_nothing_commits_none_and_the_edit_lands(
    graph_env, monkeypatch
):
    """A carried style that is only a ``:root`` palette has nothing left on a design
    system.  The edit asked for a contract change, not a restyle, so it is NOT
    refused (R18): it commits with ``deck_style=None``."""
    _flag_follows_the_contract(graph_env, monkeypatch)
    palette_only = DeckStyle(css=":root{--dk-a:#000}", components=[])
    prior_plain, _ = _seeded(graph_env, (0, 1, 2))
    _persist(
        graph_env,
        _with_style(
            prior_plain.model_copy(update={"design_contract": UNPINNED_CONTRACT}), palette_only
        ),
    )

    t = _turn(
        graph_env,
        _ops_out([], DeckChanges(design_contract=PINNED_CONTRACT), message="Pinning."),
    )

    assert len(graph_env.skills.calls_for("architect")) == 1, "the edit must not be retried"
    assert t.updates["error_state"] is None
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["deck_spec"].design_contract == PINNED_CONTRACT
    assert t.updates["deck_spec"].deck_style is None
    assert _persisted_spec(graph_env).deck_style is None
    assert "--dk-a" not in (graph_env.deck_row().css or "")


# ---------------------------------------------------------------------------
# 10. R18 (I2): a repeated selector keeps every declaration in deck.css
# ---------------------------------------------------------------------------

#: ``.dk-code`` twice, with a different rule between.
REPEATED_STYLE = DeckStyle(
    css=".dk-code{background:#fff}\n.dk-x{color:red}\n.dk-code{font-family:monospace}",
    components=[],
)


@pytest.mark.parametrize("pinned", [False, True], ids=["unpinned", "pinned"])
def test_repeated_selector_keeps_every_declaration_in_post_commit_css(graph_env, pinned):
    """``merge_css`` keys a rule by its selector and keeps only the last of a
    repeated one.  The sanitiser coalesces the repeat first, so the post-commit
    ``deck.css`` still has both of ``.dk-code``'s declarations, in order.

    Sabotage: stop coalescing -> the post-commit CSS loses ``background:#fff``."""
    if pinned:
        _pin(graph_env)
    base = _pinned_spec() if pinned else make_spec((0, 1))
    graph_env.skills.set("architect", architect_build(_with_style(base, REPEATED_STYLE)))

    state = graph_env.state()
    updates = architect_node(state)

    assert updates["error_state"] is None
    committed = updates["deck_spec"].deck_style
    assert committed.css == ".dk-x{color:red}\n.dk-code{background:#fff;font-family:monospace}"

    _land_rows(graph_env, 2)
    _post_commit(graph_env, {**state, **updates})
    post = graph_env.deck_row().css
    assert post.count(".dk-code") == 1, post
    code_rule = post[post.index(".dk-code") :]
    assert "background:#fff" in code_rule and "font-family:monospace" in code_rule, post
    assert code_rule.index("background:#fff") < code_rule.index("font-family:monospace"), post


# ---------------------------------------------------------------------------
# 11. M1: the pre-fan-out write fails; the post-commit aggregate still lands the style
# ---------------------------------------------------------------------------


def test_failed_pre_fan_out_write_still_lands_the_deck_style_post_commit(
    graph_env, monkeypatch
):
    """The architect's deck-level write raises.  The turn records
    ``deck_level_write_failed`` and still routes on its intent, so the builders and
    the post-commit aggregate run, and that aggregate is the only write of
    ``deck.css`` this turn: the deck style reaches it only through
    ``emitted_style_blocks``, after the template block.

    Sabotage: leave the deck style out of ``emitted_style_blocks`` -> red."""
    _pin(graph_env)
    real = nodes.write_deck_level_columns

    def failing_architect_write(session_id, **kwargs):
        if "deck_spec" in kwargs:
            raise RuntimeError("pre-fan-out write exploded")
        return real(session_id, **kwargs)

    monkeypatch.setattr(nodes, "write_deck_level_columns", failing_architect_write)
    graph_env.skills.set("architect", architect_build(_with_style(_pinned_spec(), CODE_STYLE)))

    state = graph_env.state()
    updates = architect_node(state)

    assert updates["error_state"]["code"] == "deck_level_write_failed"
    assert updates["architect_intent"] == "build"
    row = graph_env.deck_row()
    assert CODE_CSS not in ((row.css if row is not None else None) or "")

    _land_rows(graph_env, 2)
    review = _post_commit(graph_env, {**state, **updates})

    assert review.get("error_state") is None
    post = graph_env.deck_row().css
    assert ".slide" in post and ".dk-code" in post and "#fff" in post, post
    assert post.index(".slide") < post.index(".dk-code"), post


# ---------------------------------------------------------------------------
# 12. MF1: a pinned deck whose brand resolves empty keeps its stored CSS
# ---------------------------------------------------------------------------

#: A styled pinned deck's column, as the turn that wrote it left it.
STORED_PINNED_CSS = "\n\n".join((TEMPLATE_TOKEN_CSS, TEMPLATE_STYLE_BLOCK, OLD_STYLE.css))


def _brand_resolves_empty(env) -> None:
    """``resolve_template_bytes`` failing closed: a transient DB error, a
    deactivated design system or a deleted template all return ``("", "", "")``."""
    env.template.layout = ""
    env.template.style_block = ""
    env.template.token_css = ""


@pytest.mark.parametrize("restyle", [False, True], ids=["keeps-its-style", "restyles"])
def test_styled_pinned_deck_keeps_its_brand_css_when_the_brand_resolves_empty(
    graph_env, monkeypatch, restyle
):
    """The final review's MF1 probe.  A deck pinned to 7/3 with a deck style, whose
    brand resolves empty this turn, takes one ``update`` edit (and, in
    ``restyles``, a new deck style).  The pre-fan-out write leaves ``deck.css``
    alone, as main does when the deterministic CSS is empty, so the token and
    template CSS survive; the post-commit merge then applies the committed deck
    style over them.

    Sabotage: write ``css`` whenever the deck style is non-empty -> the column
    becomes the deck style alone and every slide renders unbranded."""
    from src.api.services.deck_level_writer import write_deck_level_columns

    _pin(graph_env)
    prior_plain, _ = _seeded(graph_env, (0, 1, 2))
    _persist(
        graph_env,
        _with_style(
            prior_plain.model_copy(update={"design_contract": PINNED_CONTRACT}), OLD_STYLE
        ),
    )
    write_deck_level_columns(graph_env.session_id, css=STORED_PINNED_CSS)
    _brand_resolves_empty(graph_env)
    calls = _spy_on_deck_writes(monkeypatch)

    t = _turn(
        graph_env,
        _ops_out(
            [_update(1, _content("UPDATED"))],
            DeckChanges(deck_style=NEW_STYLE) if restyle else None,
        ),
    )

    assert t.updates["error_state"] is None, t.updates["error_state"]
    assert (7, 3) in graph_env.template.calls, "fixture: the pinned template was resolved"
    assert t.updates["deterministic_css"] == ""
    committed = NEW_STYLE if restyle else OLD_STYLE
    assert t.updates["deck_spec"].deck_style == committed
    assert t.updates["emitted_style_blocks"] == scoped(TURN, [committed.css])
    (write,) = _architect_writes(calls)
    assert "css" not in write, f"the column was overwritten: {write.get('css')!r}"
    assert graph_env.deck_row().css == STORED_PINNED_CSS

    _post_commit(graph_env, t.merged)
    post = graph_env.deck_row().css
    assert "--brand" in post and ".slide" in post and "#123456" in post, post
    assert ".dk-code" in post, post
    if restyle:
        assert "#000" in post and "#fff" not in post, post
    else:
        assert "#fff" in post, post


def test_design_system_without_a_template_still_replaces_the_column_with_the_style(
    graph_env,
):
    """MF1's guard does not reach a design system with no template (and no
    default one): no template bytes were asked for, so an empty deterministic CSS
    is no failure, and the committed deck style replaces the column whole, as on
    an unpinned deck.

    Sabotage: omit ``css`` whenever the contract names a design system -> the old
    style's ``#fff`` stays in the column."""
    from src.api.services.deck_level_writer import write_deck_level_columns

    _pin(graph_env)
    ds_only = make_spec((0,), design_system_id=7).design_contract
    prior_plain, _ = _seeded(graph_env, (0, 1, 2))
    _persist(
        graph_env,
        _with_style(prior_plain.model_copy(update={"design_contract": ds_only}), OLD_STYLE),
    )
    write_deck_level_columns(graph_env.session_id, css=OLD_STYLE.css)

    t = _turn(graph_env, _ops_out([], DeckChanges(deck_style=NEW_STYLE)))

    assert t.updates["error_state"] is None, t.updates["error_state"]
    assert graph_env.template.calls == [], "fixture: no template is pinned or defaulted"
    assert graph_env.deck_row().css == NEW_STYLE.css


# ---------------------------------------------------------------------------
# 13. MF2: the deck style written into deck.css closes, and always serialises
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "open_css",
    [
        ".dk-a{color:red}\n/*",
        ".dk-b{color:blue",
        '.dk-a{color:red;content:"abc',
        ".dk-a{width:calc(1px",
        ".dk-a{color:red;background:url(data:image/png;base64,AAAA",
    ],
    ids=["comment", "block", "string", "calc", "unquoted-url"],
)
def test_build_with_an_open_deck_style_writes_css_that_closes(graph_env, open_css):
    """A rule the frontend writes after ``deck.css`` in the same ``<style>`` (the
    frame contract, the preview reset) must still parse as its own rule: in the
    pre-fan-out column, in ``emitted_style_blocks`` and after the post-commit
    merge, which does not close an unquoted ``url(``.

    Sabotage: return an open style unchanged -> the follower is swallowed."""
    _pin(graph_env)
    graph_env.skills.set(
        "architect",
        architect_build(_with_style(_pinned_spec(), DeckStyle(css=open_css, components=[]))),
    )

    state = graph_env.state()
    updates = architect_node(state)

    assert updates["error_state"] is None, updates["error_state"]
    assert updates["deck_spec"].deck_style is not None
    pre = graph_env.deck_row().css
    assert TEMPLATE_STYLE_BLOCK in pre and _follower_parses_after(pre), pre
    for block in updates["emitted_style_blocks"]["vals"]:
        assert _follower_parses_after(block), block

    _land_rows(graph_env, 2)
    _post_commit(graph_env, {**state, **updates})
    post = graph_env.deck_row().css
    assert ".slide" in post and ".dk-" in post, post
    assert _follower_parses_after(post), post


def test_build_with_a_surrogate_escape_in_its_deck_style_does_not_crash_the_turn(graph_env):
    """``\\D800`` decodes to a lone surrogate on a rebuild (here forced by the
    ``html`` rule).  Written back raw, ``spec.to_json()`` raised outside the write's
    try and killed the build turn.  The sanitiser maps it to U+FFFD, so the turn
    commits, the spec persists and ``deck.css`` encodes as UTF-8.

    Sabotage: emit the decoded surrogate -> ``PydanticSerializationError``."""
    _pin(graph_env)
    style = DeckStyle(css='.dk-a{content:"\\D800"}\nhtml{color:red}', components=[])
    graph_env.skills.set("architect", architect_build(_with_style(_pinned_spec(), style)))

    state = graph_env.state()
    updates = architect_node(state)

    assert updates["error_state"] is None, updates["error_state"]
    committed = updates["deck_spec"].deck_style
    assert committed is not None and committed.css == '.dk-a{content:"\ufffd"}'
    assert _persisted_spec(graph_env).deck_style == committed
    css = graph_env.deck_row().css
    css.encode("utf-8")
    assert committed.css in css and "html" not in css, css

    _land_rows(graph_env, 2)
    review = _post_commit(graph_env, {**state, **updates})
    assert review.get("error_state") is None
    graph_env.deck_row().css.encode("utf-8")


def test_a_spec_that_cannot_serialise_fails_the_deck_write_not_the_turn(graph_env, monkeypatch):
    """Defence in depth for MF2: whatever the sanitiser returns, ``spec.to_json()``
    for the pre-fan-out write runs inside the write's ``try``.  With the sanitiser
    stubbed to pass a lone surrogate through, the turn records
    ``deck_level_write_failed`` instead of raising.

    Sabotage: serialise the spec before the ``try`` -> the node raises."""
    monkeypatch.setattr(
        nodes, "sanitise_deck_style", lambda style, *, design_system_active: (style, ())
    )
    style = DeckStyle(css='.dk-a{content:"\ud800"}', components=[])
    graph_env.skills.set("architect", architect_build(_with_style(make_spec((0, 1)), style)))

    updates = architect_node(graph_env.state())

    assert updates["architect_intent"] == "build"
    assert updates["error_state"]["code"] == "deck_level_write_failed", updates["error_state"]
