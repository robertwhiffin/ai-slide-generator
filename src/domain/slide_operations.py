"""Pure slide edit operations for the architect (architect edit operations, spec §2-§3).

An edit can be described as an ordered list of insert / update / delete / replace /
move operations instead of a rewritten deck. ``apply_operations`` composes them
with the persisted slide specs into the new slide list, and says which persisted
row lands where and which slides must be built. It reads no database and never
raises on bad input: every problem is collected in one pass, so one retry can
fix them all.

Every ``position`` and ``after_position`` is a ``SlideSpec.position`` of the deck
as it was before the message; ``after_position = -1`` means "at the start".

Placement rules (deterministic, nothing is guessed):

- A slide can be the subject (``position``) of at most one operation. A replace
  is one operation.
- Anything placed "after slide a" (inserted slides and moved slides) goes
  directly after a's own content, in the order the operations appear in the
  list. a's own content is a itself, or all of its replacement slides.
- "After slide a" follows a if a is moved, and fills a's gap if a is deleted.
- A slide cannot be moved after itself, and moves cannot form a loop.

The composed deck is: the slides placed at the start, then each current slide in
position order. A slide that is moved away is skipped where it was and appears
where it was placed. Each slide's own content (unchanged, updated, replaced, or
nothing if deleted) is followed by whatever was placed after it, recursively.
The result is re-stamped to positions ``0..m-1``.

``apply_operations(current, [])`` is the identity; ``compose_edit_spec`` is what
decides there is nothing to do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ValidationError, field_validator

from src.domain.deck_spec import (
    DeckSpec,
    DeckStyle,
    DesignContractRef,
    ResolvedData,
    SlideSpec,
    look_or_none,
)

PROBLEM_CODES = (
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

_START = -1  # the anchor "at the start of the deck"

# OperationProblem has no field for an update's slide count, so problem_sentence
# reads it back out of the detail. The format and the pattern live together so
# they cannot drift apart.
_UPDATE_COUNT_DETAIL = (
    "the update of position {position} described {count} slides instead of one"
)
_UPDATE_COUNT = re.compile(r"described (\d+) slides instead of one")


class SlideContent(BaseModel):
    """A ``SlideSpec`` without its position: what one slide must say and how it binds.

    Mirrors ``SlideSpec``'s fields (a test pins that they stay in step).
    """

    purpose: str
    content_brief: str
    assumes: str
    hands_off: str
    data_references: list[str]
    slide_type: Optional[str] = None
    template_section_index: Optional[int] = None
    look: Optional[str] = None

    # Same rule as SlideSpec._slide_type_stripped_and_non_blank (duplicated so
    # SlideSpec's validator stays untouched): whatever validates here must
    # validate as a SlideSpec, so building one from a SlideContent never raises.
    @field_validator("slide_type")
    @classmethod
    def _slide_type_stripped_and_non_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("slide_type must not be whitespace-only")
        return stripped

    # SlideSpec's own look rule (shared helper): stripped, blank becomes None.
    @field_validator("look")
    @classmethod
    def _look_stripped_blank_is_none(cls, v: Optional[str]) -> Optional[str]:
        return look_or_none(v)

    def to_slide_spec(self, position: int) -> SlideSpec:
        return SlideSpec(position=position, **self.model_dump())

    @classmethod
    def from_slide_spec(cls, slide: SlideSpec) -> "SlideContent":
        return cls(**slide.model_dump(exclude={"position"}))


OperationKind = Literal["insert", "update", "delete", "replace", "move"]


class SlideOperation(BaseModel):
    """One edit. Flat on purpose: the per-op rules live in ``apply_operations``.

    A pydantic error would fail the whole turn with no retry; a problem found
    by ``apply_operations`` is retryable.
    """

    op: OperationKind
    position: Optional[int] = None
    after_position: Optional[int] = None
    slides: Optional[list[SlideContent]] = None


class DeckChanges(BaseModel):
    """Deck-level fields this edit changes; an unset (or null) field is unchanged."""

    title: Optional[str] = None
    audience: Optional[str] = None
    purpose: Optional[str] = None
    argument: Optional[str] = None
    call_to_action: Optional[str] = None
    narrative_arc: Optional[list[str]] = None
    design_contract: Optional[DesignContractRef] = None
    resolved_data: Optional[ResolvedData] = None
    deck_style: Optional[DeckStyle] = None


@dataclass(frozen=True)
class OperationProblem:
    code: str  # one of PROBLEM_CODES (callers may add their own codes)
    positions: tuple[int, ...]  # persisted positions involved (may be empty)
    detail: str  # model-facing sentence, in positions


@dataclass(frozen=True)
class OperationProblems:
    problems: tuple[OperationProblem, ...]


@dataclass(frozen=True)
class OperationsResult:
    slides: tuple[SlideSpec, ...]  # composed, re-stamped 0..m-1
    layout: tuple[Optional[int], ...]  # per new index: persisted position landing here, or None
    rebuild: tuple[int, ...]  # ascending new indices: inserted, updated, replaced
    deleted: tuple[int, ...]  # ascending persisted positions
    moved: tuple[int, ...]  # ascending persisted positions


def _problem(code: str, positions: tuple[int, ...], detail: str) -> OperationProblem:
    return OperationProblem(code, positions, detail)


def apply_operations(
    current: Sequence[SlideSpec], operations: Sequence[SlideOperation]
) -> OperationsResult | OperationProblems:
    """Compose ``operations`` over ``current``; see the module docstring for the rules."""
    ordered = sorted(current, key=lambda s: s.position)
    known = {s.position for s in ordered}
    problems: list[OperationProblem] = []

    subjects: set[int] = set()
    deleted: set[int] = set()
    updated: dict[int, SlideContent] = {}
    replaced: dict[int, list[SlideContent]] = {}
    moves: dict[int, int] = {}  # moved position -> anchor
    # anchor (_START or a position) -> items placed after it, in operation order:
    # ("new", SlideContent) or ("move", position)
    followers: dict[int, list[tuple[str, object]]] = {}

    def check_position(position: int, label: str) -> bool:
        if position in known:
            return True
        problems.append(
            _problem(
                "unknown_slide",
                (position,),
                f"{label} {position} is not a slide of the deck (positions: "
                f"{', '.join(str(p) for p in sorted(known))})",
            )
        )
        return False

    def check_anchor(after: int) -> bool:
        if after == _START or after in known:
            return True
        return check_position(after, "after_position")

    for op in operations:
        if op.op == "insert":
            if op.after_position is None:
                problems.append(
                    _problem(
                        "missing_after_position",
                        (),
                        "an insert did not give after_position (use -1 for the start)",
                    )
                )
                continue
            ok = check_anchor(op.after_position)
            if not op.slides:
                problems.append(
                    _problem(
                        "missing_slides",
                        (op.after_position,),
                        f"the insert after position {op.after_position} gave no slides",
                    )
                )
                continue
            if ok:
                followers.setdefault(op.after_position, []).extend(
                    ("new", s) for s in op.slides
                )
            continue

        # update / delete / replace / move all act on a position. Each fault of
        # the op is checked independently, so a retry sees all of them at once.
        position = op.position
        after = op.after_position
        position_ok = False
        if position is None:
            problems.append(
                _problem(
                    "missing_position",
                    (),
                    f"a {op.op} did not give the position of the slide it acts on",
                )
            )
        else:
            position_ok = check_position(position, "position")

        anchor_ok = True
        if op.op == "move":
            if after is None:
                anchor_ok = False
                problems.append(
                    _problem(
                        "missing_after_position",
                        (),
                        "a move did not give after_position (use -1 for the start)",
                    )
                )
            elif after == position:
                anchor_ok = position_ok  # an unknown self-anchor is already reported
            else:
                anchor_ok = check_anchor(after)

        # A known slide is claimed even by an otherwise faulty op, so a second
        # op on the same slide is reported now rather than after the retry.
        claimed = False
        if position_ok:
            assert position is not None
            if position in subjects:
                if not any(
                    p.code == "slide_targeted_twice" and p.positions == (position,)
                    for p in problems
                ):
                    problems.append(
                        _problem(
                            "slide_targeted_twice",
                            (position,),
                            f"the slide at position {position} is the subject of "
                            "more than one operation",
                        )
                    )
            else:
                subjects.add(position)
                claimed = True

        content_ok = True
        if position is not None and op.op == "update":
            if op.slides is None or len(op.slides) != 1:
                content_ok = False
                count = 0 if op.slides is None else len(op.slides)
                problems.append(
                    _problem(
                        "update_needs_one_slide",
                        (position,),
                        _UPDATE_COUNT_DETAIL.format(position=position, count=count),
                    )
                )
        elif position is not None and op.op == "replace":
            if not op.slides:
                content_ok = False
                problems.append(
                    _problem(
                        "missing_slides",
                        (position,),
                        f"the replace of position {position} gave no slides",
                    )
                )
        elif position_ok and op.op == "move" and after == position:
            content_ok = False
            problems.append(
                _problem(
                    "move_after_itself",
                    (position,),
                    f"the slide at position {position} cannot be moved after itself",
                )
            )

        if not (claimed and anchor_ok and content_ok):
            continue
        assert position is not None
        if op.op == "delete":
            deleted.add(position)
        elif op.op == "update":
            assert op.slides is not None
            updated[position] = op.slides[0]
        elif op.op == "replace":
            assert op.slides is not None
            replaced[position] = list(op.slides)
        else:  # move
            assert after is not None
            moves[position] = after
            followers.setdefault(after, []).append(("move", position))

    loops = _find_loops(moves)
    for members in loops:
        problems.append(
            _problem(
                "move_loop",
                members,
                "the moves of the slides at positions "
                f"{', '.join(str(p) for p in members)} go round in a circle",
            )
        )

    if problems:
        return OperationProblems(tuple(problems))

    by_position = {s.position: s for s in ordered}
    slides: list[SlideContent | SlideSpec] = []
    layout: list[Optional[int]] = []
    rebuild_flags: list[bool] = []

    def emit_new(content: SlideContent, owner: Optional[int]) -> None:
        slides.append(content)
        layout.append(owner)
        rebuild_flags.append(True)

    def expand(anchor: int) -> None:
        for kind, item in followers.get(anchor, ()):
            if kind == "new":
                emit_new(item, None)  # type: ignore[arg-type]
            else:
                emit_slot(item)  # type: ignore[arg-type]

    def emit_slot(position: int) -> None:
        if position in deleted:
            pass
        elif position in updated:
            emit_new(updated[position], position)
        elif position in replaced:
            first, *rest = replaced[position]
            emit_new(first, position)
            for extra in rest:
                emit_new(extra, None)
        else:
            slides.append(by_position[position])
            layout.append(position)
            rebuild_flags.append(False)
        expand(position)

    expand(_START)
    for s in ordered:
        if s.position not in moves:
            emit_slot(s.position)

    if operations and not slides:
        return OperationProblems(
            (
                _problem(
                    "deck_emptied",
                    (),
                    "the operations would leave the deck with no slides",
                ),
            )
        )

    stamped = tuple(
        item.to_slide_spec(i)
        if isinstance(item, SlideContent)
        else item.model_copy(update={"position": i})
        for i, item in enumerate(slides)
    )
    return OperationsResult(
        slides=stamped,
        layout=tuple(layout),
        rebuild=tuple(i for i, flag in enumerate(rebuild_flags) if flag),
        deleted=tuple(sorted(deleted)),
        moved=tuple(sorted(moves)),
    )


def _find_loops(moves: Mapping[int, int]) -> list[tuple[int, ...]]:
    """Cycles in the move graph (moved slide -> the slide it goes after).

    Only members of a cycle are reported, ascending; a slide merely hanging off
    a cycle is a consequence, not a cause.
    """
    loops: list[tuple[int, ...]] = []
    seen_in_loop: set[int] = set()
    for start in sorted(moves):
        if start in seen_in_loop:
            continue
        path: list[int] = []
        node: Optional[int] = start
        while node is not None and node in moves and node not in path:
            path.append(node)
            node = moves[node]
        if node is not None and node in path:
            members = path[path.index(node) :]
            if not seen_in_loop.intersection(members):
                seen_in_loop.update(members)
                loops.append(tuple(sorted(members)))
    return loops


_VALUE_ERROR_PREFIX = "Value error, "


def compose_edit_spec(
    prior: DeckSpec, result: OperationsResult, changes: Optional[DeckChanges]
) -> DeckSpec | OperationProblems:
    """The edited deck spec: ``prior`` + the deck-level fields set in ``changes`` + the new slides.

    ``nothing_to_do`` when the result changes no slide (nothing rebuilt, layout
    is the identity) and ``changes`` sets nothing. The composed spec is
    re-validated so a bad deck-level change is a problem, not an exception.
    """
    updates = (
        {
            name: getattr(changes, name)
            for name in DeckChanges.model_fields
            if getattr(changes, name) is not None
        }
        if changes is not None
        else {}
    )

    identity = tuple(sorted(s.position for s in prior.slides))
    if not result.rebuild and result.layout == identity and not updates:
        return OperationProblems(
            (
                _problem(
                    "nothing_to_do",
                    (),
                    "the edit listed no operation that changes the deck and no deck-level change",
                ),
            )
        )

    candidate = prior.model_copy(update={**updates, "slides": list(result.slides)})
    try:
        return DeckSpec.model_validate(candidate.model_dump())
    except ValidationError as exc:
        message = str(exc.errors()[0].get("msg", "invalid"))
        if message.startswith(_VALUE_ERROR_PREFIX):
            message = message[len(_VALUE_ERROR_PREFIX) :]
        return OperationProblems((_problem("invalid_deck_changes", (), message),))


def problem_sentence(
    problem: OperationProblem, slide_numbers: Mapping[int, int], slide_count: int
) -> str:
    """User-facing sentence for ``problem``, numbered the way the user sees the deck.

    ``slide_numbers`` maps a persisted position to its 1-indexed slide number in
    the pre-message deck; a position it does not hold is numbered ``position + 1``.
    A code outside ``PROBLEM_CODES``, or a problem missing what its sentence
    needs, returns its ``detail`` unchanged.
    """

    def number(position: int) -> int:
        return slide_numbers.get(position, position + 1)

    code = problem.code
    positions = problem.positions
    first = positions[0] if positions else None

    if code == "unknown_slide" and first is not None:
        return f"there is no slide {number(first)} — the deck has {slide_count} slides"
    if code == "slide_targeted_twice" and first is not None:
        return f"slide {number(first)} was changed in more than one way"
    if code == "missing_slides" and first is not None:
        if first == _START:
            return "the new slides at the start of the deck had no content"
        return f"the new slides for slide {number(first)} had no content"
    if code == "update_needs_one_slide" and first is not None:
        found = _UPDATE_COUNT.search(problem.detail)
        if found:  # without the count, fall back to the detail rather than guess one
            return (
                f"the change to slide {number(first)} described {found.group(1)} "
                "slides instead of one"
            )
    if code == "missing_position":
        return "one change did not say which slide it was for"
    if code == "missing_after_position":
        return "one change did not say where its slides go"
    if code == "move_after_itself" and first is not None:
        return f"slide {number(first)} cannot be moved after itself"
    if code == "move_loop":
        numbers = ", ".join(str(n) for n in sorted(number(p) for p in positions))
        return f"the moves of slides {numbers} go round in a circle"
    if code == "deck_emptied":
        return "it would have left the deck with no slides"
    if code == "nothing_to_do":
        return "it did not list any change to make"
    if code == "invalid_deck_changes":
        return f"the deck-level changes were not valid ({problem.detail})"
    return problem.detail
