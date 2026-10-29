"""Contract for ``src.domain.slide_operations`` (architect edit operations, plan
Task 1, spec §2-§3, PLAN-CORRECTIONS C6).

``apply_operations(current, operations)`` applies an ordered list of
insert / update / delete / replace / move operations to the persisted slide
specs. Every ``position`` / ``after_position`` is a ``SlideSpec.position`` of
the pre-message deck; ``after_position = -1`` means "at the start".

The composed deck is the slides placed at the start, then each current slide in
position order. A moved slide is skipped where it was and appears where it was
placed. Each slide's own content (unchanged, updated, its replacements, or
nothing if deleted) is followed by whatever was placed after it, in operation
order, recursively. "After *a*" follows *a* when *a* moves and fills *a*'s gap
when *a* is deleted. The result is re-stamped ``0..m-1``.

``OperationsResult``:
- ``layout[i]``: the persisted position whose row lands at new index ``i``, or
  ``None`` for a new slide (a replace's first slide keeps the old row);
- ``rebuild``: ascending new indices of inserted, updated and replaced slides;
- ``deleted`` / ``moved``: ascending persisted positions.

Bad input never raises: every problem is collected in one pass, in operation
order, as an ``OperationProblems``. ``apply_operations(current, [])`` is the
identity (C6); ``compose_edit_spec`` decides ``nothing_to_do``.

Deck notation used by the assertions:
- ``deck(n)`` is slides at positions ``0..n-1``; the slide at position ``p``
  has purpose ``s{p}`` and its own distinct value for every other field;
- any other token (``A``, ``X``, ``U4`` ...) is ``content(token)``, a new
  ``SlideContent`` whose purpose is the token;
- a composed deck is asserted as the full list of tokens, and every slide is
  compared field-for-field against the slide that token names, re-stamped to
  its new index.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from src.domain.deck_spec import (
    DeckSpec,
    DeckStyle,
    DeckStyleComponent,
    DesignContractRef,
    ResolvedData,
    ResolvedFigure,
    SlideSpec,
)
from src.domain.slide_operations import (
    PROBLEM_CODES,
    DeckChanges,
    OperationProblem,
    OperationProblems,
    OperationsResult,
    SlideContent,
    SlideOperation,
    apply_operations,
    compose_edit_spec,
    problem_sentence,
)

# ---------------------------------------------------------------------------
# Deck builders
# ---------------------------------------------------------------------------


def _old_fields(p: int) -> dict:
    """Distinct values for every non-position field of the persisted slide ``p``."""
    return {
        "purpose": f"s{p}",
        "content_brief": f"s{p} brief: the evidence for s{p}",
        "assumes": f"s{p} assumes: the audience saw the slide before",
        "hands_off": f"s{p} hands off: the question s{p} leaves open",
        "data_references": [f"s{p}_metrics", "shared_metrics"],
        "slide_type": f"type-s{p}",
        "template_section_index": 100 + p,
        "look": f"s{p} look: three dk-card notes under the title",
    }


def _new_fields(name: str) -> dict:
    """Distinct values for every field of the new slide content ``name``."""
    return {
        "purpose": name,
        "content_brief": f"{name} brief: what {name} must say",
        "assumes": f"{name} assumes: nothing new",
        "hands_off": f"{name} hands off: to the next slide",
        "data_references": [f"{name.lower()}_metrics"],
        "slide_type": f"type-{name}",
        "template_section_index": 7,
        "look": f"{name} look: one dk-stat across the body",
    }


def spec(p: int) -> SlideSpec:
    return SlideSpec(position=p, **_old_fields(p))


def deck(n: int) -> list[SlideSpec]:
    return [spec(p) for p in range(n)]


def content(name: str) -> SlideContent:
    return SlideContent(**_new_fields(name))


def insert(after: int, *names: str) -> SlideOperation:
    return SlideOperation(
        op="insert", after_position=after, slides=[content(n) for n in names]
    )


def update(position: int, name: str) -> SlideOperation:
    return SlideOperation(op="update", position=position, slides=[content(name)])


def replace(position: int, *names: str) -> SlideOperation:
    return SlideOperation(
        op="replace", position=position, slides=[content(n) for n in names]
    )


def delete(position: int) -> SlideOperation:
    return SlideOperation(op="delete", position=position)


def move(position: int, after: int) -> SlideOperation:
    return SlideOperation(op="move", position=position, after_position=after)


def prior_spec(slides) -> DeckSpec:
    return DeckSpec(
        title="Prior title",
        audience="Prior audience",
        purpose="Prior purpose",
        argument="Prior argument",
        call_to_action="Prior call to action",
        narrative_arc=["setup", "tension", "payoff"],
        design_contract=DesignContractRef(design_system_id=4, template_id=9),
        resolved_data=ResolvedData(
            synthesis="Prior synthesis",
            figures=[ResolvedFigure(key="arr", value="12m", source="finance")],
            gaps=["churn by region"],
        ),
        slides=list(slides),
    )


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

_OLD_TOKEN = re.compile(r"s(\d+)")


def _expected_slides(tokens: list[str]) -> tuple[SlideSpec, ...]:
    expected = []
    for index, token in enumerate(tokens):
        old = _OLD_TOKEN.fullmatch(token)
        fields = _old_fields(int(old.group(1))) if old else _new_fields(token)
        expected.append(SlideSpec(position=index, **fields))
    return tuple(expected)


def assert_composed(result, tokens, *, layout, rebuild, deleted=(), moved=()):
    """The whole result: order, re-stamping, every field, and the four tuples."""
    assert isinstance(result, OperationsResult), result
    assert [s.purpose for s in result.slides] == tokens
    assert [s.position for s in result.slides] == list(range(len(tokens)))
    assert result.slides == _expected_slides(tokens)
    assert result.layout == layout
    assert result.rebuild == rebuild
    assert result.deleted == deleted
    assert result.moved == moved


def problems_of(result) -> list[tuple[str, tuple[int, ...]]]:
    """``[(code, positions), ...]`` in reported order, after checking the shape."""
    assert isinstance(result, OperationProblems), result
    assert isinstance(result.problems, tuple)
    for problem in result.problems:
        assert isinstance(problem, OperationProblem)
        assert problem.code in PROBLEM_CODES
        assert isinstance(problem.positions, tuple)
        assert isinstance(problem.detail, str) and problem.detail.strip()
        # The detail is model-facing and speaks in positions.
        for position in problem.positions:
            if position != -1:
                assert re.search(
                    rf"(?<!\d){re.escape(str(position))}(?!\d)", problem.detail
                ), (position, problem.detail)
    return [(p.code, p.positions) for p in result.problems]


def only_problem(result) -> OperationProblem:
    assert isinstance(result, OperationProblems), result
    assert len(result.problems) == 1, result.problems
    return result.problems[0]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def test_update_rebuilds_in_place():
    assert_composed(
        apply_operations(deck(4), [update(2, "X")]),
        ["s0", "s1", "X", "s3"],
        layout=(0, 1, 2, 3),
        rebuild=(2,),
    )

    # The operation's content replaces the slide whole: a None binding in the
    # new content clears the old slide's binding rather than keeping it.
    bare = SlideContent(
        **{**_new_fields("X"), "slide_type": None, "template_section_index": None}
    )
    result = apply_operations(
        deck(4), [SlideOperation(op="update", position=2, slides=[bare])]
    )
    assert isinstance(result, OperationsResult)
    assert result.slides[2] == SlideSpec(
        position=2,
        **{**_new_fields("X"), "slide_type": None, "template_section_index": None},
    )
    assert result.slides[:2] == _expected_slides(["s0", "s1"])
    assert result.slides[3] == SlideSpec(position=3, **_old_fields(3))


def test_replace_is_update_plus_inserts():
    new = ["A", "B", "C", "D", "E", "F", "G"]
    assert_composed(
        apply_operations(deck(16), [replace(4, *new)]),
        ["s0", "s1", "s2", "s3", *new] + [f"s{p}" for p in range(5, 16)],
        layout=(0, 1, 2, 3, 4) + (None,) * 6 + tuple(range(5, 16)),
        rebuild=(4, 5, 6, 7, 8, 9, 10),
    )


def test_insert_at_start_and_after():
    assert_composed(
        apply_operations(deck(3), [insert(-1, "A"), insert(1, "B", "C")]),
        ["A", "s0", "s1", "B", "C", "s2"],
        layout=(None, 0, 1, None, None, 2),
        rebuild=(0, 3, 4),
    )

    # After the last slide appends.
    assert_composed(
        apply_operations(deck(3), [insert(2, "Z")]),
        ["s0", "s1", "s2", "Z"],
        layout=(0, 1, 2, None),
        rebuild=(3,),
    )


def test_delete_rebuilds_nothing():
    assert_composed(
        apply_operations(deck(4), [delete(1)]),
        ["s0", "s2", "s3"],
        layout=(0, 2, 3),
        rebuild=(),
        deleted=(1,),
    )

    # `deleted` is ascending whatever the operation order.
    assert_composed(
        apply_operations(deck(4), [delete(3), delete(0)]),
        ["s1", "s2"],
        layout=(1, 2),
        rebuild=(),
        deleted=(0, 3),
    )


def test_move_rebuilds_nothing():
    assert_composed(
        apply_operations(deck(4), [move(3, 0)]),
        ["s0", "s3", "s1", "s2"],
        layout=(0, 3, 1, 2),
        rebuild=(),
        moved=(3,),
    )

    # Moving the first slide to the start is a no-op order (it is still a move).
    assert_composed(
        apply_operations(deck(4), [move(0, -1)]),
        ["s0", "s1", "s2", "s3"],
        layout=(0, 1, 2, 3),
        rebuild=(),
        moved=(0,),
    )

    assert_composed(
        apply_operations(deck(4), [move(2, -1)]),
        ["s2", "s0", "s1", "s3"],
        layout=(2, 0, 1, 3),
        rebuild=(),
        moved=(2,),
    )

    assert_composed(
        apply_operations(deck(4), [move(0, 3)]),
        ["s1", "s2", "s3", "s0"],
        layout=(1, 2, 3, 0),
        rebuild=(),
        moved=(0,),
    )


def test_insert_after_deleted_slide_fills_its_gap():
    assert_composed(
        apply_operations(deck(4), [delete(2), insert(2, "N")]),
        ["s0", "s1", "N", "s3"],
        layout=(0, 1, None, 3),
        rebuild=(2,),
        deleted=(2,),
    )

    # The same whichever operation is listed first.
    assert_composed(
        apply_operations(deck(4), [insert(2, "N"), delete(2)]),
        ["s0", "s1", "N", "s3"],
        layout=(0, 1, None, 3),
        rebuild=(2,),
        deleted=(2,),
    )

    # A slide moved after a deleted slide fills its gap too.
    assert_composed(
        apply_operations(deck(4), [delete(2), move(0, 2)]),
        ["s1", "s0", "s3"],
        layout=(1, 0, 3),
        rebuild=(),
        deleted=(2,),
        moved=(0,),
    )


def test_anchor_follows_moved_slide():
    assert_composed(
        apply_operations(deck(4), [move(1, 3), insert(1, "N")]),
        ["s0", "s2", "s3", "s1", "N"],
        layout=(0, 2, 3, 1, None),
        rebuild=(4,),
        moved=(1,),
    )

    # The same whichever operation is listed first.
    assert_composed(
        apply_operations(deck(4), [insert(1, "N"), move(1, 3)]),
        ["s0", "s2", "s3", "s1", "N"],
        layout=(0, 2, 3, 1, None),
        rebuild=(4,),
        moved=(1,),
    )

    # A move anchored on a moved slide follows it; `moved` is ascending.
    assert_composed(
        apply_operations(deck(4), [move(3, 0), move(1, 3)]),
        ["s0", "s3", "s1", "s2"],
        layout=(0, 3, 1, 2),
        rebuild=(),
        moved=(1, 3),
    )


def test_followers_keep_list_order():
    assert_composed(
        apply_operations(deck(4), [insert(0, "A"), move(3, 0), insert(0, "B")]),
        ["s0", "A", "s3", "B", "s1", "s2"],
        layout=(0, None, 3, None, 1, 2),
        rebuild=(1, 3),
        moved=(3,),
    )

    # At the start too.
    assert_composed(
        apply_operations(deck(4), [insert(-1, "A"), move(2, -1)]),
        ["A", "s2", "s0", "s1", "s3"],
        layout=(None, 2, 0, 1, 3),
        rebuild=(0,),
        moved=(2,),
    )

    # A moved follower's own followers come straight after it, before the
    # next follower of the shared anchor.
    assert_composed(
        apply_operations(
            deck(4), [insert(0, "A"), move(3, 0), insert(3, "C"), insert(0, "B")]
        ),
        ["s0", "A", "s3", "C", "B", "s1", "s2"],
        layout=(0, None, 3, None, None, 1, 2),
        rebuild=(1, 3, 4),
        moved=(3,),
    )


def test_insert_after_replaced_goes_after_all_replacements():
    assert_composed(
        apply_operations(deck(3), [replace(1, "X", "Y"), insert(1, "N")]),
        ["s0", "X", "Y", "N", "s2"],
        layout=(0, 1, None, None, 2),
        rebuild=(1, 2, 3),
    )

    # The replacements are the slide's own content, so they come first even
    # when the insert is listed before the replace.
    assert_composed(
        apply_operations(deck(3), [insert(1, "N"), replace(1, "X", "Y")]),
        ["s0", "X", "Y", "N", "s2"],
        layout=(0, 1, None, None, 2),
        rebuild=(1, 2, 3),
    )

    # A slide moved after a replaced slide lands after all replacements too.
    assert_composed(
        apply_operations(deck(4), [replace(1, "X", "Y"), move(3, 1)]),
        ["s0", "X", "Y", "s3", "s2"],
        layout=(0, 1, None, 3, 2),
        rebuild=(1, 2),
        moved=(3,),
    )


def test_mixed_owner_example():
    assert_composed(
        apply_operations(
            deck(8),
            [delete(3), update(4, "U4"), replace(5, "A", "B", "C"), insert(4, "N")],
        ),
        ["s0", "s1", "s2", "U4", "N", "A", "B", "C", "s6", "s7"],
        layout=(0, 1, 2, 4, None, 5, None, None, 6, 7),
        rebuild=(3, 4, 5, 6, 7),
        deleted=(3,),
    )


def test_gapped_positions():
    gapped = (spec(0), spec(2), spec(5))

    assert_composed(
        apply_operations(gapped, [delete(2)]),
        ["s0", "s5"],
        layout=(0, 5),
        rebuild=(),
        deleted=(2,),
    )

    # `current` is read in position order, whatever order it arrives in.
    assert_composed(
        apply_operations([spec(5), spec(0), spec(2)], [delete(2)]),
        ["s0", "s5"],
        layout=(0, 5),
        rebuild=(),
        deleted=(2,),
    )

    # `rebuild` holds new indices, never persisted positions.
    assert_composed(
        apply_operations(gapped, [update(5, "X")]),
        ["s0", "s2", "X"],
        layout=(0, 2, 5),
        rebuild=(2,),
    )

    assert_composed(
        apply_operations(gapped, [insert(2, "N"), move(0, 5)]),
        ["s2", "N", "s5", "s0"],
        layout=(2, None, 5, 0),
        rebuild=(1,),
        moved=(0,),
    )


def test_empty_operations_is_identity():
    assert_composed(
        apply_operations(tuple(deck(4)), ()),
        ["s0", "s1", "s2", "s3"],
        layout=(0, 1, 2, 3),
        rebuild=(),
    )

    # Gapped and out of order: re-stamped, layout is the positions in order.
    assert_composed(
        apply_operations([spec(5), spec(0), spec(2)], []),
        ["s0", "s2", "s5"],
        layout=(0, 2, 5),
        rebuild=(),
    )


def test_slides_on_delete_or_move_are_ignored():
    for slides in ([content("Z")], []):
        ops = [
            SlideOperation(op="delete", position=1, slides=slides),
            SlideOperation(
                op="move", position=3, after_position=0, slides=[*slides, *slides]
            ),
        ]
        assert_composed(
            apply_operations(deck(4), ops),
            ["s0", "s3", "s2"],
            layout=(0, 3, 2),
            rebuild=(),
            deleted=(1,),
            moved=(3,),
        )


# ---------------------------------------------------------------------------
# Problems: one code each, exact positions, never raised
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current, operation, position",
    [
        pytest.param(deck(22), replace(29, "X"), 29, id="replace-29-of-22"),
        pytest.param(deck(22), update(29, "X"), 29, id="update-29-of-22"),
        pytest.param(deck(22), delete(29), 29, id="delete-29-of-22"),
        pytest.param(deck(22), move(29, 0), 29, id="move-29-of-22"),
        pytest.param(deck(22), delete(-1), -1, id="minus-one-is-not-a-slide"),
        pytest.param([spec(0), spec(2), spec(5)], delete(1), 1, id="gap-is-not-a-slide"),
    ],
)
def test_unknown_position_is_unknown_slide(current, operation, position):
    assert problems_of(apply_operations(current, [operation])) == [
        ("unknown_slide", (position,))
    ]


@pytest.mark.parametrize(
    "current, operation, position",
    [
        pytest.param(deck(4), insert(9, "N"), 9, id="insert-after-9"),
        pytest.param(deck(4), move(1, 9), 9, id="move-after-9"),
        pytest.param([spec(0), spec(2), spec(5)], insert(1, "N"), 1, id="after-a-gap"),
    ],
)
def test_unknown_after_position_is_unknown_slide(current, operation, position):
    assert problems_of(apply_operations(current, [operation])) == [
        ("unknown_slide", (position,))
    ]


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(insert(-2, "N"), id="insert"),
        pytest.param(move(1, -2), id="move"),
    ],
)
def test_after_position_below_minus_one_is_unknown_slide(operation):
    assert problems_of(apply_operations(deck(4), [operation])) == [
        ("unknown_slide", (-2,))
    ]


def test_slide_targeted_twice():
    assert problems_of(apply_operations(deck(4), [update(2, "X"), delete(2)])) == [
        ("slide_targeted_twice", (2,))
    ]
    assert problems_of(
        apply_operations(deck(4), [replace(2, "X", "Y"), move(2, 0)])
    ) == [("slide_targeted_twice", (2,))]


def test_insert_without_slides_is_missing_slides():
    for slides in (None, []):
        assert problems_of(
            apply_operations(
                deck(4), [SlideOperation(op="insert", after_position=1, slides=slides)]
            )
        ) == [("missing_slides", (1,))]
    assert problems_of(
        apply_operations(
            deck(4), [SlideOperation(op="insert", after_position=-1, slides=None)]
        )
    ) == [("missing_slides", (-1,))]


def test_replace_with_empty_slides_is_missing_slides():
    for slides in ([], None):
        assert problems_of(
            apply_operations(
                deck(4), [SlideOperation(op="replace", position=2, slides=slides)]
            )
        ) == [("missing_slides", (2,))]


def test_update_with_two_slides_needs_one_slide():
    for slides in ([content("X"), content("Y")], [], None):
        assert problems_of(
            apply_operations(
                deck(4), [SlideOperation(op="update", position=2, slides=slides)]
            )
        ) == [("update_needs_one_slide", (2,))]


def test_delete_without_position_is_missing_position():
    for operation in (
        SlideOperation(op="delete"),
        SlideOperation(op="update", slides=[content("X")]),
        SlideOperation(op="replace", slides=[content("A"), content("B")]),
        SlideOperation(op="move", after_position=0),
    ):
        assert problems_of(apply_operations(deck(4), [operation])) == [
            ("missing_position", ())
        ]


def test_move_without_after_position_is_missing_after_position():
    for operation in (
        SlideOperation(op="move", position=2),
        SlideOperation(op="insert", slides=[content("N")]),
    ):
        assert problems_of(apply_operations(deck(4), [operation])) == [
            ("missing_after_position", ())
        ]


def test_move_after_itself():
    assert problems_of(apply_operations(deck(4), [move(2, 2)])) == [
        ("move_after_itself", (2,))
    ]


def test_move_loop():
    assert problems_of(apply_operations(deck(4), [move(1, 2), move(2, 1)])) == [
        ("move_loop", (1, 2))
    ]

    # A three-slide circle, listed out of order, beside a valid operation:
    # one problem, positions ascending.
    assert problems_of(
        apply_operations(
            deck(5), [move(3, 1), move(1, 2), update(0, "X"), move(2, 3)]
        )
    ) == [("move_loop", (1, 2, 3))]


def test_deleting_every_slide_is_deck_emptied():
    assert problems_of(
        apply_operations(deck(3), [delete(0), delete(1), delete(2)])
    ) == [("deck_emptied", ())]

    # Decided on the composed deck: an insert into the emptied deck is fine.
    assert_composed(
        apply_operations(deck(3), [delete(0), delete(1), delete(2), insert(1, "N")]),
        ["N"],
        layout=(None,),
        rebuild=(0,),
        deleted=(0, 1, 2),
    )


def test_all_problems_collected_in_one_pass():
    ops = [
        update(1, "X"),
        replace(29, "Y"),
        delete(1),
        SlideOperation(op="insert", after_position=0, slides=None),
        update(3, "Z"),
        move(2, 2),
    ]
    assert problems_of(apply_operations(deck(4), ops)) == [
        ("unknown_slide", (29,)),
        ("slide_targeted_twice", (1,)),
        ("missing_slides", (0,)),
        ("move_after_itself", (2,)),
    ]


@pytest.mark.parametrize(
    "operations, expected",
    [
        pytest.param(
            [move(2, 99), delete(2)],
            [("unknown_slide", (99,)), ("slide_targeted_twice", (2,))],
            id="bad-anchor-still-claims-its-slide",
        ),
        pytest.param(
            [SlideOperation(op="move", position=2), delete(2)],
            [("missing_after_position", ()), ("slide_targeted_twice", (2,))],
            id="missing-anchor-still-claims-its-slide",
        ),
        pytest.param(
            [SlideOperation(op="move", position=99)],
            [("unknown_slide", (99,)), ("missing_after_position", ())],
            id="unknown-subject-and-missing-anchor",
        ),
        pytest.param(
            [SlideOperation(op="move", after_position=99)],
            [("missing_position", ()), ("unknown_slide", (99,))],
            id="missing-subject-and-unknown-anchor",
        ),
        pytest.param(
            [SlideOperation(op="update", position=99, slides=[content("X"), content("Y")])],
            [("unknown_slide", (99,)), ("update_needs_one_slide", (99,))],
            id="unknown-subject-and-two-slide-update",
        ),
        pytest.param(
            [SlideOperation(op="replace", position=99, slides=[])],
            [("unknown_slide", (99,)), ("missing_slides", (99,))],
            id="unknown-subject-and-empty-replace",
        ),
        pytest.param(
            [
                delete(2),
                SlideOperation(op="update", position=2, slides=[content("X"), content("Y")]),
            ],
            [("slide_targeted_twice", (2,)), ("update_needs_one_slide", (2,))],
            id="duplicate-subject-and-two-slide-update",
        ),
        pytest.param(
            [move(99, 99)],
            [("unknown_slide", (99,))],
            id="unknown-self-move-reported-once",
        ),
    ],
)
def test_every_fault_of_one_operation_is_reported(operations, expected):
    """One retry is all the model gets (spec §5), so an op with two independent
    faults reports both, and a faulty op on a known slide still claims it."""
    assert problems_of(apply_operations(deck(4), operations)) == expected


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


def test_never_mutates_inputs():
    current = [spec(3), spec(0), spec(2), spec(1)]  # out of order on purpose
    ops = [update(2, "X"), replace(1, "A", "B"), move(3, -1), insert(0, "N"), delete(0)]
    bad_ops = [replace(29, "X"), SlideOperation(op="insert", after_position=1, slides=None)]
    current_before = [s.model_dump() for s in current]
    ops_before = [o.model_dump() for o in ops]
    bad_ops_before = [o.model_dump() for o in bad_ops]

    result = apply_operations(current, ops)
    assert isinstance(result, OperationsResult)
    assert isinstance(apply_operations(current, bad_ops), OperationProblems)

    assert [s.model_dump() for s in current] == current_before
    assert [o.model_dump() for o in ops] == ops_before
    assert [o.model_dump() for o in bad_ops] == bad_ops_before

    prior = prior_spec(deck(4))
    changes = DeckChanges(title="New title", narrative_arc=["one", "two"])
    prior_before = prior.model_dump()
    changes_before = changes.model_dump()
    result_before = [s.model_dump() for s in result.slides]

    composed = compose_edit_spec(prior, result, changes)
    assert isinstance(composed, DeckSpec)

    assert prior.model_dump() == prior_before
    assert changes.model_dump() == changes_before
    assert [s.model_dump() for s in result.slides] == result_before


# ---------------------------------------------------------------------------
# compose_edit_spec
# ---------------------------------------------------------------------------


def test_compose_applies_only_set_deck_changes():
    prior = prior_spec(deck(3))
    result = apply_operations(prior.slides, [delete(1), insert(-1, "N")])
    assert isinstance(result, OperationsResult)

    # An explicit None (a model's `null`) is unchanged, like an unset field.
    changes = DeckChanges(
        title="New title", narrative_arc=["one", "two", "three"], audience=None
    )
    composed = compose_edit_spec(prior, result, changes)

    assert type(composed) is DeckSpec
    assert composed.title == "New title"
    assert composed.narrative_arc == ["one", "two", "three"]
    for field in DeckSpec.model_fields:
        if field not in {"title", "narrative_arc", "slides"}:
            assert getattr(composed, field) == getattr(prior, field), field
    assert composed.slides == list(result.slides)

    # No changes: only the slides change.
    assert compose_edit_spec(prior, result, None) == prior.model_copy(
        update={"slides": list(result.slides)}
    )

    # Every DeckChanges field, when set, lands on the composed spec.
    every = {
        "title": "Every title",
        "audience": "Board",
        "purpose": "Approve the budget",
        "argument": "Spend now to save later",
        "call_to_action": "Sign off today",
        "narrative_arc": ["problem", "plan"],
        "design_contract": DesignContractRef(slide_style_id=3),
        "resolved_data": ResolvedData(synthesis="New synthesis", figures=[], gaps=[]),
        "deck_style": DeckStyle(
            css=".dk-note { color: var(--brand-core-primary); }",
            components=[
                DeckStyleComponent(
                    name="Note",
                    class_names=["dk-note"],
                    use="A one-line aside under the exhibit.",
                    example_html='<p class="dk-note">Aside</p>',
                )
            ],
        ),
    }
    assert set(every) == set(DeckChanges.model_fields)
    identity = apply_operations(prior.slides, [])
    assert compose_edit_spec(prior, identity, DeckChanges(**every)) == DeckSpec(
        **every, slides=list(identity.slides)
    )


def test_compose_invalid_deck_changes():
    prior = prior_spec(deck(3))
    for result in (
        apply_operations(prior.slides, [update(0, "X")]),
        apply_operations(prior.slides, []),
    ):
        composed = compose_edit_spec(prior, result, DeckChanges(title="  "))
        assert problems_of(composed) == [("invalid_deck_changes", ())]
        assert "title must be non-empty and not whitespace-only" in (
            composed.problems[0].detail
        )


def test_compose_nothing_to_do():
    prior = prior_spec(deck(3))
    identity = apply_operations(prior.slides, [])
    for changes in (None, DeckChanges(), DeckChanges(title=None, narrative_arc=None)):
        assert problems_of(compose_edit_spec(prior, identity, changes)) == [
            ("nothing_to_do", ())
        ]

    # Decided on the result, not on the operations: a no-op move leaves the
    # layout the identity and rebuilds nothing.
    assert problems_of(
        compose_edit_spec(prior, apply_operations(prior.slides, [move(0, -1)]), None)
    ) == [("nothing_to_do", ())]

    # A deck-level change alone is an edit.
    assert compose_edit_spec(
        prior, identity, DeckChanges(audience="Board")
    ) == prior.model_copy(update={"audience": "Board"})

    # A delete-only result rebuilds nothing but changes the layout.
    deleted = apply_operations(prior.slides, [delete(1)])
    assert compose_edit_spec(prior, deleted, None) == prior.model_copy(
        update={"slides": list(deleted.slides)}
    )

    # An update-only result keeps the identity layout but rebuilds a slide.
    updated = apply_operations(prior.slides, [update(1, "X")])
    assert compose_edit_spec(prior, updated, None) == prior.model_copy(
        update={"slides": list(updated.slides)}
    )


# ---------------------------------------------------------------------------
# problem_sentence
# ---------------------------------------------------------------------------


def test_problem_sentences():
    assert PROBLEM_CODES == (
        "unknown_slide",
        "slide_targeted_twice",
        "missing_slides",
        "update_needs_one_slide",
        "missing_position",
        "missing_after_position",
        "move_after_itself",
        "move_loop",
        "deck_emptied",
        "nothing_to_do",
        "invalid_deck_changes",
    )

    current = deck(22)
    numbers = {p: p + 1 for p in range(22)}
    said: set[str] = set()

    def say(problem: OperationProblem) -> str:
        said.add(problem.code)
        return problem_sentence(problem, numbers, 22)

    def say_ops(ops) -> str:
        return say(only_problem(apply_operations(current, ops)))

    assert say_ops([replace(29, "X")]) == "there is no slide 30 — the deck has 22 slides"
    assert say_ops([update(2, "X"), delete(2)]) == (
        "slide 3 was changed in more than one way"
    )
    assert say_ops([SlideOperation(op="insert", after_position=4, slides=None)]) == (
        "the new slides for slide 5 had no content"
    )
    assert say_ops([SlideOperation(op="replace", position=6, slides=[])]) == (
        "the new slides for slide 7 had no content"
    )
    assert say_ops([SlideOperation(op="insert", after_position=-1, slides=None)]) == (
        "the new slides at the start of the deck had no content"
    )
    assert say_ops(
        [SlideOperation(op="update", position=2, slides=[content("X"), content("Y")])]
    ) == "the change to slide 3 described 2 slides instead of one"
    assert say_ops([SlideOperation(op="update", position=3, slides=[])]) == (
        "the change to slide 4 described 0 slides instead of one"
    )
    assert say_ops([SlideOperation(op="delete")]) == (
        "one change did not say which slide it was for"
    )
    assert say_ops([SlideOperation(op="insert", slides=[content("N")])]) == (
        "one change did not say where its slides go"
    )
    assert say_ops([move(2, 2)]) == "slide 3 cannot be moved after itself"
    assert say_ops([move(2, 1), move(1, 2)]) == (
        "the moves of slides 2, 3 go round in a circle"
    )
    assert say_ops([move(3, 1), move(1, 2), move(2, 3)]) == (
        "the moves of slides 2, 3, 4 go round in a circle"
    )
    assert say_ops([delete(p) for p in range(22)]) == (
        "it would have left the deck with no slides"
    )

    prior = prior_spec(current)
    identity = apply_operations(current, [])
    assert say(only_problem(compose_edit_spec(prior, identity, None))) == (
        "it did not list any change to make"
    )
    invalid = only_problem(compose_edit_spec(prior, identity, DeckChanges(title="  ")))
    assert say(invalid) == f"the deck-level changes were not valid ({invalid.detail})"
    assert say(
        OperationProblem("invalid_deck_changes", (), "title must be non-empty")
    ) == "the deck-level changes were not valid (title must be non-empty)"

    assert said == set(PROBLEM_CODES)

    # Slide numbers come from `slide_numbers`, not `position + 1`; a position
    # the mapping does not hold is numbered `position + 1`.
    gapped = [spec(0), spec(3), spec(7)]
    gapped_numbers = {0: 1, 3: 2, 7: 3}

    def say(problem: OperationProblem) -> str:
        return problem_sentence(problem, gapped_numbers, 3)

    assert say(only_problem(apply_operations(gapped, [update(7, "X"), delete(7)]))) == (
        "slide 3 was changed in more than one way"
    )
    assert say(
        only_problem(
            apply_operations(
                gapped, [SlideOperation(op="insert", after_position=3, slides=None)]
            )
        )
    ) == "the new slides for slide 2 had no content"
    assert say(
        only_problem(
            apply_operations(
                gapped,
                [SlideOperation(op="update", position=7, slides=[content("X"), content("Y")])],
            )
        )
    ) == "the change to slide 3 described 2 slides instead of one"
    assert say(only_problem(apply_operations(gapped, [move(3, 3)]))) == (
        "slide 2 cannot be moved after itself"
    )
    assert say(only_problem(apply_operations(gapped, [move(7, 3), move(3, 7)]))) == (
        "the moves of slides 2, 3 go round in a circle"
    )
    assert say(only_problem(apply_operations(gapped, [delete(4)]))) == (
        "there is no slide 5 — the deck has 3 slides"
    )

    # Built from code and positions alone, whatever the detail says.
    assert say(OperationProblem("move_loop", (7, 3), "detail")) == (
        "the moves of slides 2, 3 go round in a circle"
    )
    assert say(OperationProblem("slide_targeted_twice", (3,), "detail")) == (
        "slide 2 was changed in more than one way"
    )
    assert say(OperationProblem("unknown_slide", (9,), "detail")) == (
        "there is no slide 10 — the deck has 3 slides"
    )


# ---------------------------------------------------------------------------
# SlideContent
# ---------------------------------------------------------------------------


def test_slide_content_mirrors_slide_spec():
    spec_fields = {
        name: field for name, field in SlideSpec.model_fields.items() if name != "position"
    }
    assert set(SlideContent.model_fields) == set(spec_fields)
    for name, field in spec_fields.items():
        mirrored = SlideContent.model_fields[name]
        assert mirrored.annotation == field.annotation, name
        assert mirrored.default == field.default, name
        assert mirrored.is_required() == field.is_required(), name

    original = spec(5)
    as_content = SlideContent.from_slide_spec(original)
    assert type(as_content) is SlideContent
    assert as_content.model_dump() == original.model_dump(exclude={"position"})
    assert as_content.to_slide_spec(5) == original
    assert as_content.to_slide_spec(9) == SlideSpec(position=9, **_old_fields(5))
    assert content("X").to_slide_spec(0) == SlideSpec(position=0, **_new_fields("X"))


def test_slide_content_applies_slide_specs_slide_type_rule():
    """C9: whatever validates as SlideContent validates as the same SlideSpec,
    so apply_operations never raises building a slide from new content."""
    for slide_type, stored in ((None, None), ("hero", "hero"), ("  hero\t", "hero")):
        fields = {**_new_fields("X"), "slide_type": slide_type}
        built = SlideContent(**fields)
        assert built.slide_type == stored
        result = apply_operations(
            deck(4), [SlideOperation(op="update", position=2, slides=[built])]
        )
        assert isinstance(result, OperationsResult)
        assert result.slides[2] == SlideSpec(position=2, **fields)
        assert result.slides[2].slide_type == stored

    for blank in ("", "   ", "\n\t"):
        fields = {**_new_fields("X"), "slide_type": blank}
        with pytest.raises(ValidationError, match="slide_type must not be whitespace-only"):
            SlideSpec(position=2, **fields)
        with pytest.raises(ValidationError, match="slide_type must not be whitespace-only"):
            SlideContent(**fields)


def test_slide_content_applies_slide_specs_look_rule():
    """Deck style (Task 1, C5): ``look`` is stripped and a blank look becomes None
    (not an error, unlike a blank slide_type), on SlideSpec and SlideContent alike, so
    a slide built from new content stores the look a spec would."""
    for look, stored in (
        (None, None),
        ("one dk-stat across the body", "one dk-stat across the body"),
        ("  one dk-stat across the body\t\n", "one dk-stat across the body"),
        ("", None),
        ("   ", None),
        ("\n\t", None),
    ):
        fields = {**_new_fields("X"), "look": look}
        built = SlideContent(**fields)
        assert built.look == stored
        as_spec = SlideSpec(position=2, **fields)
        assert as_spec.look == stored
        assert built.to_slide_spec(2) == as_spec

        for operation in (
            SlideOperation(op="update", position=2, slides=[built]),
            SlideOperation(op="replace", position=2, slides=[built]),
            SlideOperation(op="insert", after_position=1, slides=[built]),
        ):
            result = apply_operations(deck(4), [operation])
            assert isinstance(result, OperationsResult)
            assert result.slides[2] == as_spec, operation.op
            assert result.slides[2].look == stored, operation.op
            # Every slide the operation did not rebuild keeps its own look.
            for index, persisted in enumerate(result.layout):
                if index not in result.rebuild:
                    assert result.slides[index].look == _old_fields(persisted)["look"]


def test_deck_helpers_give_every_slide_field_a_value():
    """The notation's promise: every field but position has its own value, so the
    field-for-field comparisons above also check that each field travels with its slide."""
    assert set(_old_fields(0)) == set(SlideSpec.model_fields) - {"position"}
    assert set(_new_fields("X")) == set(SlideContent.model_fields)


def test_problem_sentence_passes_other_problems_through():
    """C8: a code outside the table (later tasks add their own) returns its
    detail unchanged, and so does a table code missing what its sentence needs."""
    numbers = {p: p + 1 for p in range(8)}
    for problem in (
        OperationProblem(
            "invalid_slide_type_binding",
            (),
            "slide 3 binds slide_type 'hero' to a section the template does not have",
        ),
        OperationProblem("alignment_overlap", (4,), "slide 5 overlaps the slide after it"),
        OperationProblem(
            "update_needs_one_slide", (2,), "the update had the wrong number of slides"
        ),
    ):
        assert problem_sentence(problem, numbers, 8) == problem.detail
