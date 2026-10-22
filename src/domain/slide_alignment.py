"""Pure alignment of a revised deck's slides to the persisted ones (issue #314, D1).

An edit whose revised ``deck_spec`` has more slides than the persisted one is
an insertion. ``align_slides(old, new)`` reads both lists in position order and
pairs every persisted slide with one returned slide, keeping the order. The
remaining ``len(new) - len(old)`` returned slides are the inserted ones.

The pairing minimises, lexicographically, the sum of two per-pair costs:

1. 1 if the pair's ``(purpose, content_brief)`` differ (the slide is rewritten);
2. 1 if the pair differs in any field but ``position`` (``slide_key``).

An untouched slide aligns at (0, 0), a neighbour whose only change is
``assumes`` / ``hands_off`` at (0, 1), and a rewritten slide at (1, 1).

The alignment never guesses:

- more than one optimal pairing -> ``ambiguous``;
- fewer returned slides than persisted ones -> ``removes_slides``;
- an edit that moves a slide's spec -> ``moves_slides``. Two forms are caught:
  (a) a revised pair whose returned slide equals a DIFFERENT persisted slide;
  (b) an inserted slide equal to a persisted slide whose own pair is revised
  (a moved slide read as "insert a copy, rewrite the original").

Two numberings are reported (D1): the returned spec's own ``SlideSpec.position``
values (``inserted`` / ``revised``) and indices in position order, the
canonical numbering once the caller re-stamps (``inserted_indices`` /
``revised_indices``). ``old_to_new_index`` maps each persisted position to its
index in the returned spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from src.domain.deck_spec import SlideSpec

AlignmentRefusalCode = Literal["removes_slides", "ambiguous", "moves_slides"]

_Cost = tuple[int, int]


class AlignmentRefused(ValueError):  # noqa: N818 - stable public domain name
    """The revised slides cannot be matched to the current ones without guessing."""

    def __init__(self, code: AlignmentRefusalCode, detail: str) -> None:
        super().__init__(detail)
        self.code: AlignmentRefusalCode = code
        self.detail = detail


@dataclass(frozen=True)
class SlideAlignment:
    """Where each persisted slide went and which returned slides are new or revised."""

    # Index (position order) -> the returned SlideSpec.position.
    new_positions: tuple[int, ...]
    # Persisted SlideSpec.position -> index in the returned spec (position order).
    old_to_new_index: Mapping[int, int]
    # Returned slides with no persisted slide, ascending.
    inserted_indices: tuple[int, ...]
    # Returned slides whose persisted slide differs, ascending.
    revised_indices: tuple[int, ...]

    @property
    def inserted(self) -> tuple[int, ...]:
        """The inserted slides as returned-spec ``SlideSpec.position`` values."""
        return tuple(self.new_positions[i] for i in self.inserted_indices)

    @property
    def revised(self) -> tuple[int, ...]:
        """The revised slides as returned-spec ``SlideSpec.position`` values.

        Equals today's positional ``changed`` set when the lengths are equal.
        """
        return tuple(self.new_positions[i] for i in self.revised_indices)


def slide_key(slide: SlideSpec) -> str:
    """Canonical JSON of the slide without ``position`` (sorted keys).

    The full model is dumped, so an absent optional field and an explicit
    ``None`` give the same key.
    """
    return json.dumps(slide.model_dump(exclude={"position"}), sort_keys=True)


def _by_position(slides: Sequence[SlideSpec]) -> list[SlideSpec]:
    return sorted(slides, key=lambda slide: slide.position)


def align_slides(old: Sequence[SlideSpec], new: Sequence[SlideSpec]) -> SlideAlignment:
    """Align the persisted slides ``old`` to the returned slides ``new`` (D1).

    Both lists are read in position order and neither is mutated. Raises
    ``AlignmentRefused`` rather than guess.
    """
    old_sorted = _by_position(old)
    new_sorted = _by_position(new)
    n_old, n_new = len(old_sorted), len(new_sorted)

    if n_new < n_old:
        raise AlignmentRefused(
            "removes_slides",
            f"the revised deck has {n_new} slides but the current deck has {n_old}; "
            "removing slides is not supported",
        )

    extra = n_new - n_old
    old_keys = [slide_key(slide) for slide in old_sorted]
    new_keys = [slide_key(slide) for slide in new_sorted]
    old_identity = [(s.purpose, s.content_brief) for s in old_sorted]
    new_identity = [(s.purpose, s.content_brief) for s in new_sorted]

    def pair_cost(i: int, j: int) -> _Cost:
        return (
            0 if old_identity[i] == new_identity[j] else 1,
            0 if old_keys[i] == new_keys[j] else 1,
        )

    # best[(i, j)] = (minimum cost, number of optimal paths capped at 2) with i
    # old and j new slides consumed. Only states with 0 <= j - i <= extra exist.
    best: dict[tuple[int, int], tuple[_Cost, int]] = {(0, 0): ((0, 0), 1)}
    for i in range(n_old + 1):
        for j in range(i, i + extra + 1):
            if (i, j) == (0, 0):
                continue
            candidates: list[tuple[_Cost, int]] = []
            if i > 0 and j > 0:
                prev_cost, prev_count = best[(i - 1, j - 1)]
                step = pair_cost(i - 1, j - 1)
                candidates.append(
                    ((prev_cost[0] + step[0], prev_cost[1] + step[1]), prev_count)
                )
            if j > i:
                candidates.append(best[(i, j - 1)])
            cheapest = min(cost for cost, _ in candidates)
            count = sum(c for cost, c in candidates if cost == cheapest)
            best[(i, j)] = (cheapest, min(count, 2))

    if best[(n_old, n_new)][1] > 1:
        raise AlignmentRefused(
            "ambiguous",
            "the revised deck can be matched to the current deck in more than one "
            "way, so it is unclear which slides are new and which were changed",
        )

    # Backtrack the unique optimal path.
    old_to_new: dict[int, int] = {}  # old sorted index -> new sorted index
    paired_new: dict[int, int] = {}  # new sorted index -> old sorted index
    i, j = n_old, n_new
    while (i, j) != (0, 0):
        cost = best[(i, j)][0]
        if i > 0 and j > 0:
            prev_cost = best[(i - 1, j - 1)][0]
            step = pair_cost(i - 1, j - 1)
            if (prev_cost[0] + step[0], prev_cost[1] + step[1]) == cost:
                old_to_new[i - 1] = j - 1
                paired_new[j - 1] = i - 1
                i, j = i - 1, j - 1
                continue
        j -= 1  # an inserted slide

    revised_indices = tuple(
        sorted(nj for nj, oi in paired_new.items() if old_keys[oi] != new_keys[nj])
    )
    inserted_indices = tuple(nj for nj in range(n_new) if nj not in paired_new)

    revised_old = {paired_new[nj] for nj in revised_indices}
    for nj in revised_indices:
        oi = paired_new[nj]
        for other, key in enumerate(old_keys):
            if other != oi and key == new_keys[nj]:
                raise AlignmentRefused(
                    "moves_slides",
                    f"revised slide {new_sorted[nj].position} is a copy of the current "
                    f"slide {old_sorted[other].position}; an edit cannot move a slide",
                )
    for nj in inserted_indices:
        for other in revised_old:
            if old_keys[other] == new_keys[nj]:
                raise AlignmentRefused(
                    "moves_slides",
                    f"new slide {new_sorted[nj].position} is a copy of the current slide "
                    f"{old_sorted[other].position}, which was also rewritten; an edit "
                    "cannot move a slide",
                )

    return SlideAlignment(
        new_positions=tuple(slide.position for slide in new_sorted),
        old_to_new_index={
            old_sorted[oi].position: nj for oi, nj in sorted(old_to_new.items())
        },
        inserted_indices=inserted_indices,
        revised_indices=revised_indices,
    )
