# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""Edits keep the deck style coherent (architect deck style, plan Task 6;
spec §5; PLAN-CORRECTIONS C16, C17, C18; Rulings R6, R7, R8, R22, R23).

* **An operations edit may not strand a slide (R7, C17).**  When the edit's
  ``deck_changes.deck_style`` drops a class that the persisted style defined and
  a KEPT, non-rebuilt slide still uses, the edit is refused with the problem
  ``deck_style_drops_used_class``, naming the PERSISTED positions of those slides
  and the class, and the one retry is handed it under the already-retryable
  ``edit_operations_rejected`` degrade (R6: ``RETRYABLE_EDIT_CODES`` is untouched).
  A moved slide is kept.  An updated, replaced or deleted slide is not.  A class
  no kept slide uses may go.  A design-contract change rebuilds every slide, so
  its fresh style is never refused.  Every class counts, a piece's unprefixed
  token spans (``.dk-code .kw``) too, except those something else styles: the
  template's own and the frame's ``slide`` (R22).
* **The user is told in slide numbers (R6, C16).**  A doubly-refused drop says
  "slides 3 and 4 still use the dk-note style the change removes" on a gapped
  deck whose persisted positions are 5 and 7.
* **A full-spec edit cannot lose (or change) the deck style (R8, C18).**  On the
  describe-only re-description (answered as an ``edit`` or, R23, a ``build``) and
  on an aligned edit, the committed spec keeps
  the persisted ``deck_style`` whatever the answer's ``deck_spec`` carries, and
  ``deck.css`` keeps the style's rules on a pinned deck (Task 4 review M4).  On a
  contract change the answer's (sanitised) style is kept instead.
* **A deck-style change is not a narrative change.**  ``classify_spec_change`` is
  ``"none"`` when only ``deck_style`` and a slide's ``look`` differ, and a
  deck-style-only edit fires no deck-level re-review.

How this file asserts: on what was persisted (the deck row's ``deck_spec_json``
and ``css``, the slide rows), the node's returned state, the payload the
architect's retry call was handed (``rejected_edit.problems``), what was said on
both surfaces, and the foreman's own dispatch (``foreman_node`` then
``foreman_router``).  Never on whether a helper was called.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import pytest

from src.api.services.deck_level_writer import write_deck_level_columns
from src.database.models.session import SessionSlide, UserSession
from src.domain.deck_spec import DeckSpec, DeckStyle, DeckStyleComponent
from src.domain.deck_style import sanitise_deck_style
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_operations import DeckChanges
from src.services.graph import nodes
from src.services.graph.nodes import classify_spec_change
from src.services.graph.state import scoped
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    TEMPLATE_STYLE_BLOCK,
    TEMPLATE_TOKEN_CSS,
    graph_env,
    make_spec,
)
from tests.unit.test_architect_edit_operations import (
    REJECTED_PREFIX,
    RESTYLED,
    _assert_laid_out,
    _content,
    _delete,
    _mk,
    _move,
    _ops_out,
    _replace,
    _seeded,
    _spec_from,
    _turn,
    _update,
)
from tests.unit.test_architect_edit_retry import (
    A_MSG,
    B_MSG,
    _Answers,
    _assert_nowhere,
    _assert_only_refusal,
    _assert_retried_with,
    _calls,
)
from tests.unit.test_architect_edit_retry import _turn as _retry_turn
from tests.unit.test_architect_insert_slide import (
    TURN,
    _by_marker,
    _canonical,
    _db_state,
    _edit_out,
    _marker,
    _persist,
    _persisted_spec,
    _revised,
    _rows,
)
from tests.unit.test_deck_style_css_path import (
    C11_TEMPLATE_BLOCK,
    C11_TEMPLATE_ROOT_AFTER_MERGE,
    _architect_writes,
    _dispatch,
    _pin,
    _post_commit,
    _sent_positions,
    _spy_on_deck_writes,
)

CODE = "deck_style_drops_used_class"

# ---------------------------------------------------------------------------
# Deck styles (each is clean: the sanitiser returns it as it is, under either flag)
# ---------------------------------------------------------------------------

NOTE_CSS = ".dk-note{border-left:4px solid #0a7;padding:8px}"
CODE_CSS = ".dk-code{background:#fff;font-family:monospace}"

#: The persisted style: a note and a code block.
STYLE = DeckStyle(
    css=NOTE_CSS + "\n" + CODE_CSS,
    components=[
        DeckStyleComponent(
            name="side note",
            class_names=["dk-note"],
            use="an aside beside the main point",
            example_html="<p class='dk-note'>An aside.</p>",
        ),
        DeckStyleComponent(
            name="code block",
            class_names=["dk-code"],
            use="any slide that shows code",
            example_html="<pre class='dk-code'>x = 1</pre>",
        ),
    ],
)

#: Drops ``dk-note``; keeps (and darkens) ``dk-code``.
WITHOUT_NOTE = DeckStyle(
    css=".dk-code{background:#000;font-family:monospace}",
    components=[
        DeckStyleComponent(
            name="code block",
            class_names=["dk-code"],
            use="any slide that shows code",
            example_html="<pre class='dk-code'>x = 1</pre>",
        )
    ],
)

#: Drops ``dk-code`` (which no slide uses); keeps ``dk-note`` with a new look.
WITHOUT_CODE = DeckStyle(
    css=".dk-note{border-left:4px solid #333;padding:12px}",
    components=[
        DeckStyleComponent(
            name="side note",
            class_names=["dk-note"],
            use="an aside beside the main point",
            example_html="<p class='dk-note'>An aside.</p>",
        )
    ],
)

#: A design-contract change's fresh style: none of the old classes.
FRESH = DeckStyle(css=".dk-panel{padding:16px;border-radius:8px}", components=[])

#: A fresh style with an at-rule and an unscoped rule around one the sanitiser keeps.
HOSTILE_FRESH = DeckStyle(
    css="@import url(https://evil/x.css);\nbody{color:red}\n.dk-panel{padding:8px}",
    components=[],
)

UNPINNED_CONTRACT = make_spec((0,)).design_contract
PINNED_CONTRACT = make_spec((0,), design_system_id=7, template_id=3).design_contract


# ---------------------------------------------------------------------------
# A styled deck whose rows use the style's classes
# ---------------------------------------------------------------------------


def _note_html(marker: str, cls: str) -> str:
    """A slide that uses *cls* (its marker kept, so ``_by_marker`` still finds it)."""
    return f'<div class="slide"><h1>{marker}</h1><p class="{cls}">an aside</p></div>'


def _use_class(env, positions: Sequence[int], cls: str = "dk-note") -> None:
    """Rewrite the committed rows at *positions* to use *cls*."""
    _rewrite_rows(env, positions, lambda marker: _note_html(marker, cls))


def _rewrite_rows(env, positions: Sequence[int], make_html: Callable[[str], str]) -> None:
    """Rewrite the committed rows at *positions* as ``make_html(marker)``."""
    if not positions:
        return
    db = env.factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        )
        rows = (
            db.query(SessionSlide)
            .filter(
                SessionSlide.session_id == owner.id,
                SessionSlide.position.in_(list(positions)),
            )
            .all()
        )
        assert sorted(r.position for r in rows) == sorted(positions), "fixture"
        for row in rows:
            row.html = make_html(_marker(row.html))
        db.commit()
    finally:
        db.close()


def _styled_deck(
    env,
    positions: Sequence[int],
    *,
    note_on: Sequence[int],
    style: Optional[DeckStyle] = STYLE,
    contract=None,
) -> Tuple[DeckSpec, Dict[str, Dict[str, Any]]]:
    """Rows at *positions* (marker ``_mk(i)``), those at *note_on* using ``dk-note``,
    and a persisted spec carrying *style*.  Returns the spec and the rows by marker."""
    plain, _ = _seeded(env, positions)
    update: Dict[str, Any] = {"deck_style": style}
    if contract is not None:
        update["design_contract"] = contract
    prior = plain.model_copy(update=update)
    _persist(env, prior)
    _use_class(env, note_on)
    return prior, _by_marker(_rows(env))


def _with_style(spec: DeckSpec, style: Optional[DeckStyle]) -> DeckSpec:
    return spec.model_copy(update={"deck_style": style})


def _assert_landed(t, *, targets, spec: DeckSpec, message: str) -> None:
    """The edit landed: committed and persisted as *spec*, only *message* said."""
    assert t.updates["error_state"] is None, t.updates["error_state"]
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["architect_message"] == message
    assert t.updates["target_positions"] == list(targets)
    assert t.updates["deck_spec"] == spec
    assert t.assistant == [message]


# ---------------------------------------------------------------------------
# 1. A dropped class a kept slide still uses: refused, retried, and the retry lands
# ---------------------------------------------------------------------------


def test_dropping_used_class_is_refused_and_retried(graph_env):
    """Rows 1 and 4 of six use ``dk-note``.  A updates slide 1 and drops ``dk-note``
    from the deck style: row 4 is kept and not rebuilt, so A is refused and the
    retry is handed exactly one ``deck_style_drops_used_class`` problem at
    persisted position 4 (not 1, which A rebuilds), whose detail names the class
    and says to add ``update`` operations.  B also updates slide 4 and lands: both
    are built, the committed spec carries B's style, and ``deck.css`` is B's style.
    Only B's message is said; A's is nowhere.

    Sabotage: skip the check -> one call and A lands without slide 4's styling;
    count the rebuilt row 1 as kept -> positions [1, 4]; check against the
    persisted style instead of the new one -> nothing is ever dropped."""
    prior, before = _styled_deck(graph_env, range(6), note_on=(1, 4))
    rows_before = _rows(graph_env)
    u1, u4 = _content("ONE-REVISED"), _content("FOUR-REVISED")
    first = _ops_out(
        [_update(1, u1)], DeckChanges(deck_style=WITHOUT_NOTE), message=A_MSG
    )
    second = _ops_out(
        [_update(1, u1), _update(4, u4)],
        DeckChanges(deck_style=WITHOUT_NOTE),
        message=B_MSG,
    )
    answers = _Answers(first, second)

    t = _retry_turn(graph_env, answers)

    problems = _assert_retried_with(answers, graph_env, first)
    assert [(p["code"], p["positions"]) for p in problems] == [(CODE, [4])], problems
    detail = problems[0]["detail"]
    assert "dk-note" in detail, f"the problem does not name the class: {detail!r}"
    assert "update" in detail, (
        f"the problem does not tell the model to update those slides: {detail!r}"
    )

    old = list(prior.slides)
    composed = _canonical(
        _with_style(prior, WITHOUT_NOTE),
        [old[0], _spec_from(u1), old[2], old[3], _spec_from(u4), old[5]],
    )
    _assert_landed(t, targets=[1, 4], spec=composed, message=B_MSG)
    assert _persisted_spec(graph_env) == composed
    assert graph_env.deck_row().css == WITHOUT_NOTE.css
    assert _rows(graph_env) == rows_before, "an identity layout moves no row"
    _assert_laid_out(graph_env, before, [_mk(i) for i in range(6)])
    assert _sent_positions(_dispatch({**t.state, **t.updates})) == [1, 4]
    _assert_nowhere(graph_env, t, A_MSG)


def test_moved_slide_using_the_class_counts_as_kept(graph_env):
    """Row 4 uses ``dk-note``.  A moves slide 5 to the front and drops ``dk-note``:
    the moved slide is kept (its row travels whole, nothing rebuilds it), so A is
    refused, at the slide's PERSISTED position 4 — not its new index 0.  B only
    moves it and lands with the persisted style.

    Sabotage: treat a moved row as not kept -> A lands; report composed indices
    -> positions [0]."""
    prior, before = _styled_deck(graph_env, range(6), note_on=(4,))
    first = _ops_out([_move(4, -1)], DeckChanges(deck_style=WITHOUT_NOTE), message=A_MSG)
    second = _ops_out([_move(4, -1)], message=B_MSG)
    answers = _Answers(first, second)

    t = _retry_turn(graph_env, answers)

    problems = _assert_retried_with(answers, graph_env, first)
    assert [(p["code"], p["positions"]) for p in problems] == [(CODE, [4])], problems
    assert "dk-note" in problems[0]["detail"]

    old = list(prior.slides)
    composed = _canonical(prior, [old[4], old[0], old[1], old[2], old[3], old[5]])
    _assert_landed(t, targets=[], spec=composed, message=B_MSG)
    assert _persisted_spec(graph_env).deck_style == STYLE
    _assert_laid_out(
        graph_env, before, [_mk(4), _mk(0), _mk(1), _mk(2), _mk(3), _mk(5)]
    )
    _assert_nowhere(graph_env, t, A_MSG)


def test_dropped_class_refused_twice_is_said_in_slide_numbers(graph_env):
    """A gapped deck: rows and spec at persisted positions ``(0, 2, 5, 7)`` — the
    user's slides 1-4 — with rows 5 and 7 using ``dk-note``.  Both answers drop it
    and update nothing.  The turn degrades ``edit_operations_rejected``; the user
    is told "slides 3 and 4 still use the dk-note style the change removes", the
    problem (on the retry payload and the refusal row) names PERSISTED positions
    ``[5, 7]``, ``error_state.message`` is its model-facing detail, and nothing is
    written.

    Sabotage: number the sentence ``position + 1`` -> "slides 6 and 8"; report row
    indices -> positions [2, 3]; no ``problem_sentence`` branch -> the user is
    shown the model-facing detail."""
    _styled_deck(graph_env, (0, 2, 5, 7), note_on=(5, 7))
    snapshot = _db_state(graph_env)
    first = _ops_out([], DeckChanges(deck_style=WITHOUT_NOTE), message=A_MSG)
    second = _ops_out([], DeckChanges(deck_style=WITHOUT_NOTE), message=B_MSG)
    answers = _Answers(first, second)

    t = _retry_turn(graph_env, answers)

    problems = _assert_retried_with(answers, graph_env, first)
    assert [(p["code"], p["positions"]) for p in problems] == [(CODE, [5, 7])], problems
    sentence = (
        REJECTED_PREFIX + "slides 3 and 4 still use the dk-note style the change removes."
    )
    refusal = _assert_only_refusal(graph_env, t, "edit_operations_rejected", sentence)
    (problem,) = refusal["problems"]
    assert (problem["code"], problem["positions"]) == (CODE, [5, 7])
    assert "dk-note" in problem["detail"]
    assert t.updates["error_state"]["message"] == problem["detail"]
    _assert_nowhere(graph_env, t, A_MSG, B_MSG)
    assert _db_state(graph_env) == snapshot


# ---------------------------------------------------------------------------
# 2. What may go: an unused class, and a class on a slide the edit rebuilds
# ---------------------------------------------------------------------------


def test_dropping_unused_class_applies(graph_env):
    """Row 4 uses ``dk-note``; no row uses ``dk-code``.  A style that drops
    ``dk-code`` and only restyles ``dk-note`` (same class, new look) lands on the
    first call: no slide is rebuilt, the committed spec and ``deck.css`` carry the
    new style, and no row is touched.

    Sabotage: refuse any dropped class -> a retry; refuse a restyled class -> a
    retry."""
    prior, _ = _styled_deck(graph_env, range(6), note_on=(4,))
    rows_before = _rows(graph_env)
    out = _ops_out([], DeckChanges(deck_style=WITHOUT_CODE), message=A_MSG)
    answers = _Answers(out)

    t = _retry_turn(graph_env, answers)

    assert _calls(graph_env) == 1, "an unused class may be dropped without a retry"
    _assert_landed(t, targets=[], spec=_with_style(prior, WITHOUT_CODE), message=A_MSG)
    assert _persisted_spec(graph_env) == _with_style(prior, WITHOUT_CODE)
    assert graph_env.deck_row().css == WITHOUT_CODE.css
    assert _rows(graph_env) == rows_before
    assert _dispatch({**t.state, **t.updates}) == "deck_reviewer"


@pytest.mark.parametrize("op", ["update", "replace", "delete"])
def test_dropping_class_on_rebuilt_slide_applies(graph_env, op):
    """Row 4 is the only one using ``dk-note``.  An edit that drops ``dk-note`` and
    updates, replaces or deletes slide 5 (position 4) leaves no kept slide using
    it, so it lands on the first call with the new style; the updated or replaced
    slide is built, a delete builds nothing.

    Sabotage: count the rebuilt (or deleted) row as kept -> a retry."""
    prior, before = _styled_deck(graph_env, range(6), note_on=(4,))
    new = _content("FOUR-NEW")
    operation = {"update": _update(4, new), "replace": _replace(4, new), "delete": _delete(4)}[op]
    out = _ops_out([operation], DeckChanges(deck_style=WITHOUT_NOTE), message=A_MSG)
    answers = _Answers(out)

    t = _retry_turn(graph_env, answers)

    assert _calls(graph_env) == 1, f"a {op} of the only slide using the class needs no retry"
    old = list(prior.slides)
    slides = old[:4] + ([] if op == "delete" else [_spec_from(new)]) + old[5:]
    composed = _canonical(_with_style(prior, WITHOUT_NOTE), slides)
    targets = [] if op == "delete" else [4]
    _assert_landed(t, targets=targets, spec=composed, message=A_MSG)
    assert _persisted_spec(graph_env) == composed
    assert graph_env.deck_row().css == WITHOUT_NOTE.css
    route = _dispatch({**t.state, **t.updates})
    if op == "delete":
        assert route == "deck_reviewer"
        _assert_laid_out(graph_env, before, [_mk(i) for i in (0, 1, 2, 3, 5)])
    else:
        assert _sent_positions(route) == [4]


#: Scopes its note under the template's ``slide`` class, a class the style names
#: but does not own (every seeded row carries ``class="slide"``).
SCOPED_NOTE = DeckStyle(css=".slide .dk-note{border-left:4px solid #0a7}", components=[])
#: The same piece, no longer scoped: ``dk-note`` stays, ``slide`` is not named.
UNSCOPED_NOTE = DeckStyle(css=".dk-note{border-left:4px solid #333}", components=[])


def test_dropping_a_class_the_deck_style_does_not_own_applies(graph_env):
    """Every row uses the frame's ``slide`` class and row 1 ``dk-note``.  The
    persisted style scopes its note as ``.slide .dk-note``; the restyle drops the
    qualifier and keeps ``dk-note``.  ``slide`` is the frame's class, never a deck
    style's (Ruling R22), and no slide loses a piece, so the edit lands on the
    first call with no slide rebuilt.  Unpinned: no template block owns ``slide``
    here, so the frame exclusion alone lets it through.

    Sabotage: count every class the new style stops naming -> refused for
    ``slide`` at every position, twice, and the turn degrades."""
    assert sanitise_deck_style(SCOPED_NOTE, design_system_active=False) == (
        SCOPED_NOTE,
        (),
    ), "fixture: the scoped style must be clean"
    prior, _ = _styled_deck(graph_env, range(3), note_on=(1,), style=SCOPED_NOTE)
    rows_before = _rows(graph_env)
    out = _ops_out([], DeckChanges(deck_style=UNSCOPED_NOTE), message=A_MSG)
    answers = _Answers(out)

    t = _retry_turn(graph_env, answers)

    assert _calls(graph_env) == 1, "the frame's slide class was refused"
    spec = _with_style(prior, UNSCOPED_NOTE)
    _assert_landed(t, targets=[], spec=spec, message=A_MSG)
    assert _persisted_spec(graph_env) == spec
    assert graph_env.deck_row().css == UNSCOPED_NOTE.css
    assert _rows(graph_env) == rows_before


#: A code block whose token spans are unprefixed classes inside the piece (the
#: shape of the plan's Task 7 fixture, ``.dk-code .kw/.fn/.str/.cm``).
TOKENS = DeckStyle(
    css=".dk-code{font-family:monospace}\n.dk-code .kw{color:#c00}\n.dk-code .str{color:#070}",
    components=[],
)
#: The same piece with its token spans renamed into the ``dk-`` vocabulary.
TOKENS_RENAMED = DeckStyle(
    css=".dk-code{font-family:monospace}\n.dk-code .dk-kw{color:#c00}\n"
    ".dk-code .dk-str{color:#070}",
    components=[],
)


def _code_html(marker: str) -> str:
    return (
        f'<div class="slide"><h1>{marker}</h1><pre class="dk-code">'
        '<span class="kw">def</span> <span class="str">"x"</span></pre></div>'
    )


def test_renaming_token_span_classes_is_refused(graph_env):
    """Ruling R22: a gapped deck at persisted positions ``(0, 2, 5, 7)``, rows 5 and
    7 colouring their code with the ``kw`` and ``str`` token spans.  A restyle
    renames them ``dk-kw`` / ``dk-str`` and updates nothing: every kept slide
    would lose its keyword and string colours, so A is refused with one problem
    per class, each at the PERSISTED positions ``[5, 7]`` and naming its class.
    The retry discusses instead; nothing is written.

    Sabotage: count only ``dk-`` classes (the filter R22 replaced) -> A lands and
    slides 3 and 4 lose their colours unchecked."""
    for style in (TOKENS, TOKENS_RENAMED):
        assert sanitise_deck_style(style, design_system_active=False) == (style, ()), (
            "fixture: the token styles must be clean"
        )
    _styled_deck(graph_env, (0, 2, 5, 7), note_on=(), style=TOKENS)
    _rewrite_rows(graph_env, (5, 7), _code_html)
    snapshot = _db_state(graph_env)
    first = _ops_out([], DeckChanges(deck_style=TOKENS_RENAMED), message=A_MSG)
    question = "Shall I update slides 3 and 4 so their code keeps its colours?"
    answers = _Answers(first, ArchitectOutput(intent="discuss", message=question))

    t = _retry_turn(graph_env, answers)

    problems = _assert_retried_with(answers, graph_env, first)
    assert [(p["code"], p["positions"]) for p in problems] == [
        (CODE, [5, 7]),
        (CODE, [5, 7]),
    ], problems
    assert "the class kw," in problems[0]["detail"], problems[0]["detail"]
    assert "the class str," in problems[1]["detail"], problems[1]["detail"]
    assert t.updates["architect_intent"] == "discuss"
    assert t.assistant == [question]
    _assert_nowhere(graph_env, t, A_MSG)
    assert _db_state(graph_env) == snapshot


#: The pinned template's own block: the frame and a ``title`` class it styles.
TITLED_TEMPLATE_BLOCK = ".slide { color: #123456; }\n.title { font-size: 40px; }"
#: A card that also tweaks the template's ``title`` inside it.
CARD_OVER_TITLE = DeckStyle(
    css=".dk-card{padding:8px}\n.dk-card .title{font-weight:700}", components=[]
)
#: The card without the tweak: ``title`` is no longer named.
CARD_ONLY = DeckStyle(css=".dk-card{padding:12px}", components=[])


@pytest.mark.parametrize("session", ["no-selection", "selection-unpinned"])
def test_dropping_a_template_class_qualifier_applies(graph_env, monkeypatch, session):
    """Ruling R22's other exclusion: on a pinned deck whose template styles
    ``title``, the persisted style tweaks ``.dk-card .title`` and the restyle drops
    that rule.  Row 1 still uses ``dk-card`` and ``title``, but the template keeps
    styling ``title``, so no piece is stripped: the edit lands on the first call
    with no slide rebuilt.

    ``selection-unpinned``: the session's own selection is unpinned, so the
    INBOUND brand has no template block; the classes left out are the composed
    contract's, resolved before the check.

    Sabotage: leave the template's classes out of the exclusion -> refused for
    ``title`` at position 1, twice, and the turn degrades; read them off the
    inbound brand (the check before the re-resolve) -> the unpinned-selection
    case is refused."""
    if session == "selection-unpinned":
        monkeypatch.setattr(nodes, "_session_contract", lambda _sid: UNPINNED_CONTRACT)
    graph_env.template.style_block = TITLED_TEMPLATE_BLOCK
    prior, _ = _styled_deck(
        graph_env,
        range(3),
        note_on=(),
        style=CARD_OVER_TITLE,
        contract=PINNED_CONTRACT,
    )
    _rewrite_rows(
        graph_env,
        (1,),
        lambda marker: (
            f'<div class="slide"><h1>{marker}</h1>'
            '<div class="dk-card"><h2 class="title">A card</h2></div></div>'
        ),
    )
    rows_before = _rows(graph_env)
    out = _ops_out([], DeckChanges(deck_style=CARD_ONLY), message=A_MSG)
    answers = _Answers(out)

    t = _retry_turn(graph_env, answers)

    assert _calls(graph_env) == 1, "a class the template styles was refused"
    spec = _with_style(prior, CARD_ONLY)
    _assert_landed(t, targets=[], spec=spec, message=A_MSG)
    assert _persisted_spec(graph_env) == spec
    assert _rows(graph_env) == rows_before


# ---------------------------------------------------------------------------
# 3. A design-contract change rebuilds every slide: its fresh style is not refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["in-deck_changes", "adopted-from-deck_spec"])
def test_design_contract_change_with_fresh_style_is_not_refused(graph_env, where):
    """C17's bug: a confirmed restyle commonly arrives as
    ``deck_changes(design_contract=…, deck_style=<fresh>)`` with no operations, so
    ``rebuild`` is empty and every slide would read as kept.  Rows 1 and 4 use
    ``dk-note``, which the fresh style does not define.  The contract changes, so
    every slide is rebuilt and the check is skipped: one call, every position
    built, the fresh style committed under the new contract.

    ``adopted-from-deck_spec``: the new contract is given in ``deck_spec`` only
    (C19); the composed spec's contract is what decides, not ``deck_changes``'.

    Sabotage: run the check on a contract change -> refused twice, the turn
    degrades; skip it only when the ANSWER's ``deck_changes.design_contract`` is
    set -> the adopted case is refused."""
    prior, _ = _styled_deck(graph_env, range(6), note_on=(1, 4))
    if where == "in-deck_changes":
        out = _ops_out(
            [], DeckChanges(design_contract=RESTYLED, deck_style=FRESH), message=A_MSG
        )
    else:
        echoed = prior.model_copy(update={"design_contract": RESTYLED})
        out = _ops_out([], DeckChanges(deck_style=FRESH), deck_spec=echoed, message=A_MSG)
    answers = _Answers(out)

    t = _retry_turn(graph_env, answers)

    assert _calls(graph_env) == 1, "a restyle with a fresh deck style must not be retried"
    composed = prior.model_copy(update={"design_contract": RESTYLED, "deck_style": FRESH})
    _assert_landed(t, targets=list(range(6)), spec=composed, message=A_MSG)
    assert _persisted_spec(graph_env) == composed
    assert _sent_positions(_dispatch({**t.state, **t.updates})) == list(range(6))


def test_echoed_contract_still_checks_the_dropped_class(graph_env):
    """A ``deck_changes`` that echoes the persisted contract is no contract change,
    so nothing is rebuilt wholesale and the check still runs: dropping ``dk-note``,
    which row 4 uses, is refused at position 4.  The retry discusses instead.

    Sabotage: skip the check whenever ``deck_changes.design_contract`` is set
    (rather than when the composed ids differ) -> the drop lands."""
    prior, _ = _styled_deck(graph_env, range(6), note_on=(4,))
    snapshot = _db_state(graph_env)
    first = _ops_out(
        [],
        DeckChanges(design_contract=prior.design_contract, deck_style=WITHOUT_NOTE),
        message=A_MSG,
    )
    question = "Shall I update slide 5 so it no longer needs the side note?"
    answers = _Answers(first, ArchitectOutput(intent="discuss", message=question))

    t = _retry_turn(graph_env, answers)

    problems = _assert_retried_with(answers, graph_env, first)
    assert [(p["code"], p["positions"]) for p in problems] == [(CODE, [4])], problems
    assert t.updates["architect_intent"] == "discuss"
    assert t.updates["error_state"] is None
    assert t.assistant == [question]
    _assert_nowhere(graph_env, t, A_MSG)
    assert _db_state(graph_env) == snapshot


# ---------------------------------------------------------------------------
# 4. The full-spec edit path carries the persisted deck style (R8, C18)
# ---------------------------------------------------------------------------

_DESCRIBE_ONLY = {"describe_only": scoped(TURN, True)}


#: The full-spec answers R8 carries the style over: the sweeper's describe-only
#: re-description under either intent it may answer with (R23: intent is model
#: output, and a describe-only build builds nothing), and an aligned edit.
_FULL_SPEC_KINDS = ["describe-only-edit", "describe-only-build", "alignment"]


def _full_spec_turn(env, prior: DeckSpec, kind: str, answer_style: Optional[DeckStyle]):
    """A full-spec answer for *prior* revising slide 2's brief, its spec carrying
    *answer_style*: the arc-review sweeper's describe-only re-description (as an
    ``edit`` or a ``build``), or an ordinary aligned edit targeting slide 2."""
    revised = _with_style(_revised(prior, {1: "brief RE-DESCRIBED"}), answer_style)
    overrides = _DESCRIBE_ONLY if kind.startswith("describe-only") else {}
    out = ArchitectOutput(
        intent="build" if kind == "describe-only-build" else "edit",
        message="Re-described.",
        target_positions=[1],
        deck_spec=revised,
    )
    return _turn(env, out, **overrides), revised


@pytest.mark.parametrize("kind", _FULL_SPEC_KINDS)
def test_full_spec_edit_keeps_persisted_deck_style(graph_env, kind):
    """A full-spec answer whose ``deck_spec`` has ``deck_style=None`` (the sweeper
    re-describes the narrative and does not echo the style) commits the persisted
    deck style: the spec in state and the persisted spec are the answer's, with
    the persisted style.  Unpinned deck.

    Sabotage: commit the answer's spec as given -> ``deck_style is None`` and the
    deck loses its style; carry on an ``edit`` only (R23) -> the describe-only
    build loses it."""
    prior, _ = _styled_deck(graph_env, (0, 1, 2), note_on=(1,))

    t, revised = _full_spec_turn(graph_env, prior, kind, None)

    expected = _with_style(revised, STYLE)
    assert t.updates["error_state"] is None, t.updates["error_state"]
    assert t.updates["architect_intent"] == (
        "build" if kind == "describe-only-build" else "edit"
    )
    assert t.updates["deck_spec"] == expected
    assert _persisted_spec(graph_env) == expected
    assert graph_env.deck_row().css == STYLE.css


@pytest.mark.parametrize("kind", _FULL_SPEC_KINDS)
def test_full_spec_edit_keeps_the_deck_style_in_deck_css(graph_env, monkeypatch, kind):
    """Task 4 review M4: on a PINNED deck the pre-fan-out write always passes
    ``css`` (the template's CSS), so a full-spec answer without a deck style
    rewrote ``deck.css`` without the style's rules.  With the style carried, the
    turn's own write — and so ``deck.css`` — is the token CSS, the template block,
    then the style.

    Sabotage: carry the style into state but write ``deck.css`` from the answer
    -> the ``.dk-`` rules are gone."""
    _pin(graph_env)
    prior, _ = _styled_deck(
        graph_env, (0, 1, 2), note_on=(1,), contract=PINNED_CONTRACT
    )
    expected_css = "\n\n".join((TEMPLATE_TOKEN_CSS, TEMPLATE_STYLE_BLOCK, STYLE.css))
    write_deck_level_columns(graph_env.session_id, css=expected_css)
    calls = _spy_on_deck_writes(monkeypatch)

    t, _ = _full_spec_turn(graph_env, prior, kind, None)

    assert t.updates["error_state"] is None, t.updates["error_state"]
    (write,) = _architect_writes(calls)
    assert write["css"] == expected_css, "the turn rewrote deck.css without the style"
    assert graph_env.deck_row().css == expected_css
    assert t.updates["deck_spec"].deck_style == STYLE
    assert _persisted_spec(graph_env).deck_style == STYLE


@pytest.mark.parametrize("kind", _FULL_SPEC_KINDS)
def test_full_spec_edit_on_the_same_contract_does_not_restyle(graph_env, kind):
    """R8 carries the persisted style whatever the answer's ``deck_spec`` says
    while the contract is unchanged: a full-spec answer bringing ANOTHER style
    (one that drops ``dk-note``, which row 1 uses) commits the persisted style.
    A restyle goes through ``deck_changes.deck_style``, where the dropped-class
    check runs; the full-spec path has no such check.

    Sabotage: carry only when the answer has no style -> ``WITHOUT_NOTE`` is
    committed and row 1 loses its styling unchecked."""
    prior, _ = _styled_deck(graph_env, (0, 1, 2), note_on=(1,))

    t, revised = _full_spec_turn(graph_env, prior, kind, WITHOUT_NOTE)

    expected = _with_style(revised, STYLE)
    assert t.updates["error_state"] is None, t.updates["error_state"]
    assert t.updates["deck_spec"] == expected
    assert _persisted_spec(graph_env) == expected


def test_full_spec_edit_changing_the_contract_keeps_the_answers_sanitised_style(graph_env):
    """R8's other half (a regression guard, green before Task 6): a full-spec edit
    that moves the deck onto a new contract keeps the ANSWER's style, sanitised,
    not the persisted one — a restyle rebuilds every slide.  The ``@import`` and
    ``body`` rules are gone from the committed spec and ``deck.css``.

    Sabotage: carry the persisted style on a contract change too -> ``STYLE`` is
    committed."""
    prior, _ = _styled_deck(graph_env, (0, 1, 2), note_on=(1,))
    clean, notes = sanitise_deck_style(HOSTILE_FRESH, design_system_active=False)
    assert notes and clean == sanitise_deck_style(
        HOSTILE_FRESH, design_system_active=True
    )[0], "fixture: the sanitised style must not depend on the flag"
    answer = prior.model_copy(
        update={"design_contract": PINNED_CONTRACT, "deck_style": HOSTILE_FRESH}
    )

    t = _turn(graph_env, _edit_out(answer, [0, 1, 2], message="Restyling."))

    assert t.updates["error_state"] is None, t.updates["error_state"]
    assert t.updates["architect_intent"] == "edit"
    committed = t.updates["deck_spec"]
    assert committed.design_contract == PINNED_CONTRACT
    assert committed.deck_style == clean
    assert _persisted_spec(graph_env).deck_style == clean
    css = graph_env.deck_row().css or ""
    assert clean.css in css and "@import" not in css and "body" not in css, css
    assert t.updates["target_positions"] == [0, 1, 2]


#: A palette plus a piece: clean on a deck with no design system, and not on one.
PALETTE_STYLE = DeckStyle(
    css=":root{--dk-ink:#000}\n" + NOTE_CSS, components=[STYLE.components[0]]
)


@pytest.mark.parametrize("kind", _FULL_SPEC_KINDS)
def test_same_contract_carry_is_resanitised_when_the_design_system_flag_flips(
    graph_env, kind
):
    """Final review SF1.  The persisted style was committed while the deck's
    design system resolved as inactive (deactivated, or the style source
    swallowed an error and said so), so it kept its ``:root{--dk-…}`` palette.
    This turn the SAME contract resolves as a design system.  R8/R23 carry the
    persisted style on a same-contract full-spec answer without sanitising it
    again, so the write site re-sanitises it under the committed brand's final
    flag: the palette is gone from the committed spec, ``deck.css`` and
    ``emitted_style_blocks``, and the template's ``:root`` survives the
    post-commit merge.

    Sabotage: write the carried style as it is -> ``--dk-ink`` reaches
    ``deck.css`` and replaces the template's ``:root`` after the merge."""
    clean, notes = sanitise_deck_style(PALETTE_STYLE, design_system_active=False)
    assert clean is PALETTE_STYLE and notes == (), "fixture: clean without a design system"
    expected, _ = sanitise_deck_style(PALETTE_STYLE, design_system_active=True)
    assert expected is not None and ":root" not in expected.css
    _pin(graph_env)
    graph_env.template.style_block = C11_TEMPLATE_BLOCK
    prior, _ = _styled_deck(
        graph_env, (0, 1, 2), note_on=(1,), style=PALETTE_STYLE, contract=PINNED_CONTRACT
    )
    write_deck_level_columns(graph_env.session_id, css=PALETTE_STYLE.css)

    t, _ = _full_spec_turn(graph_env, prior, kind, None)

    assert t.updates["error_state"] is None, t.updates["error_state"]
    assert t.updates["design_system_active"] is True
    assert t.updates["deck_spec"].deck_style == expected
    assert _persisted_spec(graph_env).deck_style == expected
    css = graph_env.deck_row().css
    assert C11_TEMPLATE_BLOCK in css and "--dk-ink" not in css, css
    for block in t.updates["emitted_style_blocks"]["vals"]:
        assert "--dk-ink" not in block, block

    _post_commit(graph_env, t.merged)
    post = graph_env.deck_row().css
    assert C11_TEMPLATE_ROOT_AFTER_MERGE in post, post
    assert "--dk-ink" not in post and ".dk-note" in post, post


# ---------------------------------------------------------------------------
# 5. A deck-style change is not a deck-level (narrative) change
# ---------------------------------------------------------------------------


def test_deck_style_change_is_not_deck_level(graph_env):
    """``classify_spec_change`` is ``"none"`` when only ``deck_style`` and a slide's
    ``look`` differ (spec §5), and ``deck_style`` is not one of the deck-level
    fields.  Behaviourally: a deck-style-only edit re-reviews no slide against the
    brief, says no deck-level notice, and builds nothing.

    Green before Task 6 by design; mutation-checked by adding ``"deck_style"`` to
    ``_DECK_LEVEL_FIELDS`` (-> ``"deck_level"``, a serial re-review and its
    notice)."""
    prior = _with_style(make_spec((0, 1, 2)), STYLE)
    looked = prior.model_copy(
        update={
            "deck_style": WITHOUT_CODE,
            "slides": [
                s.model_copy(update={"look": "a quiet aside on the right"})
                if s.position == 1
                else s
                for s in prior.slides
            ],
        }
    )
    assert looked != prior, "fixture"
    assert classify_spec_change(looked, prior) == "none"
    assert classify_spec_change(_with_style(prior, None), prior) == "none"
    assert classify_spec_change(prior, _with_style(prior, None)) == "none"
    assert "deck_style" not in nodes._DECK_LEVEL_FIELDS

    styled, _ = _styled_deck(graph_env, (0, 1, 2), note_on=(1,))
    t = _turn(graph_env, _ops_out([], DeckChanges(deck_style=WITHOUT_CODE), message=A_MSG))

    assert t.updates["error_state"] is None, t.updates["error_state"]
    assert t.updates["deck_spec"] == _with_style(styled, WITHOUT_CODE)
    assert t.updates["target_positions"] == []
    assert graph_env.skills.calls_for("build_reviewer") == [], (
        "a deck-style-only edit re-reviewed slides against the brief"
    )
    assert [e for e in t.events if (e.metadata or {}).get("spec_change")] == [], (
        "a deck-style-only edit was announced as a spec change"
    )
    assert t.said == [A_MSG]
    assert _dispatch(t.merged) == "deck_reviewer"
