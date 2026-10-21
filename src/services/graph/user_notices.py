"""Plain-language failure notices for agent-mode chat (#321).

When a slide or the deck cannot be finished, the graph writes an ``info`` row into
the chat.  This module is the one place that decides what that row says: it maps a
failure's stage (and, for the safety gate, a flag) to a kind, and the kind to a
short headline and a one- or two-sentence text that names the slide, says what
happened in plain words, states the slide's state and offers one concrete action.

Pure and stdlib-only
--------------------
Nothing here imports the graph, the database, the runtime or any other ``src``
module (``__future__``, ``dataclasses`` and ``typing`` only; a test pins that).
It is pure and stdlib-only so #316 can reuse :func:`slide_number`,
:func:`slides_phrase` and the ``details`` payload for its own finding notices.
The one class-dependent decision, whether an error was a safety-gate block, is
made by the caller and passed in as ``unsafe=``.

Numbering
---------
1-based numbers in text, 0-based everywhere else.  Callers pass the 0-based
position they already hold; every number a user reads is ``position + 1``, via
:func:`slide_number` / :func:`slides_phrase`.  ``FailureNotice.positions`` stays
0-based for logs, and no ``details`` value is ever a slide number.

Technical detail
----------------
Each notice also carries the technical side for a collapsed disclosure and a log
line: ``stage``, ``error`` and, when known, ``request_id``.  ``details`` never
carries exception text (``str(exc)`` can echo model output) and never carries a
``PersistedRuntimeError`` subclass name (#271).  ``error`` is therefore either an
ordinary exception class name the caller has already vetted, or a fixed code.  A
transient fault always carries :data:`MODEL_TEMPORARILY_UNAVAILABLE`, and
:func:`unreviewed_slide_notice` has no ``error`` parameter at all, so a caller
cannot hand it the caught exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Final, Iterable, Literal, Mapping, Optional, Tuple

NoticeKind = Literal[
    "build_failed",
    "blocked_unsafe",
    "check_failed",
    "save_failed",
    "stalled",
    "slide_failed",
    "kept_unreviewed",
    "kept_unfixed",
    "slides_unfinished",
    "deck_not_updated",
    "deck_not_updated_review_skipped",
    "deck_review_failed",
]

#: The error code every transient notice carries, never the caught exception's class,
#: which for a transient fault is always a PersistedRuntimeError subclass (#271).
MODEL_TEMPORARILY_UNAVAILABLE: Final = "model_temporarily_unavailable"

#: Stage -> kind for a placeholder.  Any stage not listed maps to "slide_failed".
PLACEHOLDER_STAGE_KINDS: Mapping[str, NoticeKind] = {
    "builder": "build_failed",
    "build_reviewer": "check_failed",
    "fix_reviewer": "save_failed",
    "placeholder": "stalled",
}

_REVIEW_STAGE: Final = "build_reviewer"
_FIX_STAGE: Final = "fix_round"
_FOREMAN_STAGE: Final = "foreman"
_DECK_REVIEWER_STAGE: Final = "deck_reviewer"
_END_WITH_OUTSTANDING_POSITIONS: Final = "end_with_outstanding_positions"

# kind -> (headline, text).  ``{n}`` is the 1-based slide number; ``{Slides}`` is the
# capitalised slides phrase.  The headline makes no claim about the slide's state: it
# rides the pre-commit event, before any placeholder exists.
_CATALOGUE: Mapping[NoticeKind, Tuple[str, str]] = {
    "build_failed": (
        "Slide {n} couldn't be built.",
        "Slide {n} couldn't be built, so it's shown as a placeholder — "
        "ask me to regenerate slide {n}.",
    ),
    "blocked_unsafe": (
        "Slide {n} was blocked by a safety check.",
        "Slide {n} was blocked by a safety check because it included something a deck "
        "can't contain, such as content loaded from the web. It's shown as a placeholder "
        "— ask me to regenerate slide {n} without it, for example without images or "
        "videos from other websites.",
    ),
    "check_failed": (
        "Slide {n} was built but couldn't be checked.",
        "Slide {n} was built but couldn't be checked, so it's shown as a placeholder "
        "— ask me to regenerate slide {n}.",
    ),
    "save_failed": (
        "Slide {n} couldn't be saved after its automatic fix.",
        "Slide {n} couldn't be saved after its automatic fix, so it's shown as a "
        "placeholder — ask me to regenerate slide {n}.",
    ),
    "stalled": (
        "Slide {n} didn't finish building.",
        "Slide {n} didn't finish building, so it's shown as a placeholder — "
        "ask me to regenerate slide {n}.",
    ),
    "slide_failed": (
        "Slide {n} couldn't be generated.",
        "Slide {n} couldn't be generated, so it's shown as a placeholder — "
        "ask me to regenerate slide {n}.",
    ),
    "kept_unreviewed": (
        "Slide {n} hasn't been checked.",
        "Slide {n} is shown as first built: the AI service was briefly unavailable, "
        "so it hasn't been checked. If it doesn't look right, ask me to regenerate "
        "slide {n}.",
    ),
    "kept_unfixed": (
        "Slide {n} is shown without its automatic fix.",
        "Slide {n} is shown without its automatic fix because the AI service was "
        "briefly unavailable. The issues found are in the slide's AI feedback — "
        "choose Apply there to try the fix again, or ask me to regenerate slide {n}.",
    ),
    "slides_unfinished": (
        "{Slides} couldn't be finished.",
        "{Slides} couldn't be finished this time and may be missing or out of date. "
        "Please send your request again.",
    ),
    "deck_not_updated": (
        "The deck couldn't be fully updated.",
        "Your slides were saved, but the deck couldn't be fully updated, so its slide "
        "count and exports may be out of date. They'll refresh the next time I build "
        "or edit slides.",
    ),
    "deck_not_updated_review_skipped": (
        "The deck couldn't be fully updated, and its review was skipped.",
        "Your slides were saved, but the deck couldn't be fully updated, so its slide "
        "count and exports may be out of date, and the review of the deck as a whole "
        "was skipped. Both will run again the next time I build or edit slides.",
    ),
    "deck_review_failed": (
        "The review of the deck as a whole couldn't run.",
        "The deck is ready, but the review of the deck as a whole couldn't run this "
        "time. It will run again the next time I build or edit slides.",
    ),
}


@dataclass(frozen=True)
class FailureNotice:
    """One failure, in the words a user reads and the fields a log or disclosure needs."""

    kind: NoticeKind
    headline: str  # short; no claim about the slide's state (pre-commit events)
    text: str  # the full message the chat row carries
    stage: str  # technical: graph node / pipeline stage
    error: Optional[str]  # technical: exception class name or a fixed code
    positions: Tuple[int, ...]  # technical, 0-based, for logs only
    details: Dict[str, str]  # what the chat disclosure shows


def slide_number(position: int) -> int:
    """The 1-based number a user sees for the 0-based *position*."""
    return position + 1


def slides_phrase(positions: Iterable[int]) -> str:
    """Lowercase phrase for 0-based *positions*, sorted and de-duplicated.

    ``[3]`` gives ``"slide 4"``; ``[3, 1]`` gives ``"slides 2 and 4"``; ``[4, 1, 3, 3]``
    gives ``"slides 2, 4 and 5"``.  Any iterable is accepted and read once.  Raises
    ``ValueError`` when there are no positions.
    """
    numbers = [slide_number(position) for position in sorted(set(positions))]
    if not numbers:
        raise ValueError("slides_phrase needs at least one position")
    if len(numbers) == 1:
        return f"slide {numbers[0]}"
    return f"slides {', '.join(str(n) for n in numbers[:-1])} and {numbers[-1]}"


def _capitalised(phrase: str) -> str:
    return phrase[:1].upper() + phrase[1:]


def _details(stage: str, error: Optional[str], request_id: Optional[str]) -> Dict[str, str]:
    """The disclosure payload: stage, error and request id, with ``None`` values omitted."""
    candidates = {"stage": stage, "error": error, "request_id": request_id}
    return {key: value for key, value in candidates.items() if value is not None}


def _notice(
    kind: NoticeKind,
    *,
    stage: str,
    error: Optional[str],
    positions: Tuple[int, ...],
    request_id: Optional[str],
    slides: str = "",
) -> FailureNotice:
    """Render *kind* from the catalogue for *positions* and attach the technical side."""
    headline, text = _CATALOGUE[kind]
    values = {
        "n": slide_number(positions[0]) if len(positions) == 1 else "",
        "Slides": _capitalised(slides),
    }
    return FailureNotice(
        kind=kind,
        headline=headline.format(**values),
        text=text.format(**values),
        stage=stage,
        error=error,
        positions=positions,
        details=_details(stage, error, request_id),
    )


def placeholder_notice(
    position: int,
    *,
    stage: str,
    error: Optional[str],
    unsafe: bool = False,
    request_id: Optional[str] = None,
) -> FailureNotice:
    """Notice for a slide shown as a placeholder after *stage* failed.

    *unsafe* (the caller's ``isinstance(error, UnsafeContentError)``) wins over the
    stage; it is never inferred from the error name.  An unknown stage is passed
    through unchanged as ``stage`` and reads as the generic ``slide_failed``.
    """
    kind: NoticeKind = (
        "blocked_unsafe" if unsafe else PLACEHOLDER_STAGE_KINDS.get(stage, "slide_failed")
    )
    return _notice(kind, stage=stage, error=error, positions=(position,), request_id=request_id)


def unreviewed_slide_notice(
    position: int,
    *,
    during: Literal["review", "fix"],
    request_id: Optional[str] = None,
) -> FailureNotice:
    """Notice for a slide kept as built because the model was briefly unavailable.

    ``during="review"`` is a slide that was not checked; ``"fix"`` is one whose
    automatic fix was skipped.  There is no ``error`` parameter: the error is always
    :data:`MODEL_TEMPORARILY_UNAVAILABLE`, never the caught exception.
    """
    if during == "review":
        kind: NoticeKind = "kept_unreviewed"
        stage = _REVIEW_STAGE
    elif during == "fix":
        kind = "kept_unfixed"
        stage = _FIX_STAGE
    else:
        raise ValueError(f"during must be 'review' or 'fix', got {during!r}")
    return _notice(
        kind,
        stage=stage,
        error=MODEL_TEMPORARILY_UNAVAILABLE,
        positions=(position,),
        request_id=request_id,
    )


def unfinished_slides_notice(
    positions: Iterable[int], *, request_id: Optional[str] = None
) -> FailureNotice:
    """Notice for slides still outstanding when the turn ended.

    *positions* may be any iterable; it is read once, then sorted and de-duplicated.
    Raises ``ValueError`` when empty.
    """
    outstanding = tuple(sorted(set(positions)))
    return _notice(
        "slides_unfinished",
        stage=_FOREMAN_STAGE,
        error=_END_WITH_OUTSTANDING_POSITIONS,
        positions=outstanding,
        request_id=request_id,
        slides=slides_phrase(outstanding),
    )


def deck_not_updated_notice(
    *,
    review_skipped: bool,
    error: Optional[str],
    request_id: Optional[str] = None,
) -> FailureNotice:
    """Notice for slides saved while the deck-level update failed.

    *review_skipped* adds that the review of the deck as a whole did not run.
    """
    kind: NoticeKind = "deck_not_updated_review_skipped" if review_skipped else "deck_not_updated"
    return _notice(
        kind, stage=_DECK_REVIEWER_STAGE, error=error, positions=(), request_id=request_id
    )


def deck_review_failed_notice(
    *, error: Optional[str], request_id: Optional[str] = None
) -> FailureNotice:
    """Notice for a deck whose whole-deck review could not run."""
    return _notice(
        "deck_review_failed",
        stage=_DECK_REVIEWER_STAGE,
        error=error,
        positions=(),
        request_id=request_id,
    )
