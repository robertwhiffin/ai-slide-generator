"""The plain-language failure-notice catalogue (#321, plan Task 1).

``src/services/graph/user_notices.py`` turns a failure's stage and class into the
text a user reads in chat.  These tests pin:

1. every notice's ``text`` and ``headline`` are plain language and 1-based;
2. each kind carries its one concrete action, and no headline claims a placeholder;
3. the stage -> kind mapping, the unknown-stage fallback and the safety override;
4. all twelve kinds read differently;
5. ``details`` carries only stage / error / request id, never a slide number;
6. ``slide_number`` / ``slides_phrase``;
7. the module is stdlib-only (so #316 can reuse it);

plus the catalogue itself, transcribed from the plan, as an exact contract — a
copy edit to the wording must change this file on purpose.

Positions are 0-based in data; every number in user text is ``position + 1``.
The expected numbers here are written as ``position + 1`` literally, never via
the module's own ``slide_number``, so an off-by-one there cannot agree with itself.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import logging
import re
import typing
from pathlib import Path

import pytest

from src.services.graph import user_notices
from src.services.graph.user_notices import (
    MODEL_TEMPORARILY_UNAVAILABLE,
    PLACEHOLDER_STAGE_KINDS,
    FailureNotice,
    NoticeKind,
    deck_not_updated_notice,
    deck_review_failed_notice,
    placeholder_notice,
    slide_number,
    slides_phrase,
    unfinished_slides_notice,
    unreviewed_slide_notice,
)
from tests.fixtures.notice_assertions import (
    EXCEPTION_CLASS_NAMES,
    assert_numbered,
    assert_plain_language,
    failure_notice_records,
    plain_language_offences,
)

# ---------------------------------------------------------------------------
# Literals.  Deliberately NOT read from the module under test.
# ---------------------------------------------------------------------------

POSITIONS = (0, 1, 9)
PLACEHOLDER_STAGES = ("builder", "build_reviewer", "fix_reviewer", "placeholder")
UNKNOWN_STAGE = "some_future_stage"
STAGES = PLACEHOLDER_STAGES + (UNKNOWN_STAGE,)

# nodes.py's _STALL_REASON — the placeholder node's row marker, passed as `error`.
STALL_REASON = "Slide generation did not complete"
END_WITH_OUTSTANDING = "end_with_outstanding_positions"

# Every `error` value a placeholder or deck notice can be handed: a class name,
# the stall code, or nothing.
ERRORS = EXCEPTION_CLASS_NAMES + (STALL_REASON, None)

EXPECTED_STAGE_KINDS = {
    "builder": "build_failed",
    "build_reviewer": "check_failed",
    "fix_reviewer": "save_failed",
    "placeholder": "stalled",
}

PLACEHOLDER_KINDS = frozenset(
    {"build_failed", "blocked_unsafe", "check_failed", "save_failed", "stalled", "slide_failed"}
)
KEPT_KINDS = frozenset({"kept_unreviewed", "kept_unfixed"})
SLIDE_KINDS = PLACEHOLDER_KINDS | KEPT_KINDS
DECK_KINDS = frozenset(
    {"deck_not_updated", "deck_not_updated_review_skipped", "deck_review_failed"}
)
ALL_KINDS = SLIDE_KINDS | {"slides_unfinished"} | DECK_KINDS

DETAIL_KEYS = frozenset({"stage", "error", "request_id"})


def _one_of_each_kind(
    position: int, *, request_id: str | None = None
) -> list[tuple[str, FailureNotice]]:
    """(expected kind, notice) for all twelve kinds, each about 0-based *position*."""
    rid = {"request_id": request_id}
    return [
        (
            "build_failed",
            placeholder_notice(position, stage="builder", error="ValidationError", **rid),
        ),
        (
            "blocked_unsafe",
            placeholder_notice(
                position, stage="builder", error="UnsafeContentError", unsafe=True, **rid
            ),
        ),
        (
            "check_failed",
            placeholder_notice(position, stage="build_reviewer", error="ValidationError", **rid),
        ),
        (
            "save_failed",
            placeholder_notice(position, stage="fix_reviewer", error="RuntimeError", **rid),
        ),
        ("stalled", placeholder_notice(position, stage="placeholder", error=STALL_REASON, **rid)),
        (
            "slide_failed",
            placeholder_notice(position, stage=UNKNOWN_STAGE, error="KeyError", **rid),
        ),
        ("kept_unreviewed", unreviewed_slide_notice(position, during="review", **rid)),
        ("kept_unfixed", unreviewed_slide_notice(position, during="fix", **rid)),
        ("slides_unfinished", unfinished_slides_notice([position], **rid)),
        (
            "deck_not_updated",
            deck_not_updated_notice(review_skipped=False, error="RuntimeError", **rid),
        ),
        (
            "deck_not_updated_review_skipped",
            deck_not_updated_notice(review_skipped=True, error="RuntimeError", **rid),
        ),
        ("deck_review_failed", deck_review_failed_notice(error="RuntimeError", **rid)),
    ]


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[.!?](?=\s|$)", text))


def _assert_plain_notice(notice: FailureNotice) -> None:
    """Test-1 checks shared by every builder: plain, short, no technical echo."""
    for surface in (notice.text, notice.headline):
        assert_plain_language(surface)
        if notice.error is not None:
            assert notice.error not in surface, (
                f"the technical error {notice.error!r} leaked into a user surface: {surface!r}"
            )
    assert 1 <= _sentence_count(notice.text) <= 2, (
        f"text must be one or two sentences: {notice.text!r}"
    )
    assert _sentence_count(notice.headline) == 1, (
        f"headline must be one sentence: {notice.headline!r}"
    )


# ---------------------------------------------------------------------------
# 1. Plain language and 1-based numbering, over every builder.
# ---------------------------------------------------------------------------


class TestEveryNoticeIsPlainLanguage:
    @pytest.mark.parametrize("unsafe", [False, True], ids=["safe", "unsafe"])
    @pytest.mark.parametrize("error", ERRORS, ids=lambda e: f"error={e}")
    @pytest.mark.parametrize("stage", STAGES)
    @pytest.mark.parametrize("position", POSITIONS, ids=lambda p: f"pos{p}")
    def test_placeholder_notice(
        self, position: int, stage: str, error: str | None, unsafe: bool
    ) -> None:
        notice = placeholder_notice(
            position, stage=stage, error=error, unsafe=unsafe, request_id="req-321"
        )

        _assert_plain_notice(notice)
        assert_numbered(notice.text, position)
        assert_numbered(notice.headline, position)

    @pytest.mark.parametrize("during", ["review", "fix"])
    @pytest.mark.parametrize("position", POSITIONS, ids=lambda p: f"pos{p}")
    def test_unreviewed_slide_notice(self, position: int, during: str) -> None:
        notice = unreviewed_slide_notice(position, during=during, request_id="req-321")

        _assert_plain_notice(notice)
        assert MODEL_TEMPORARILY_UNAVAILABLE not in notice.text
        assert_numbered(notice.text, position)
        assert_numbered(notice.headline, position)

    @pytest.mark.parametrize(
        ("positions", "phrase"),
        [
            ([0], "Slide 1"),
            ([1], "Slide 2"),
            ([9], "Slide 10"),
            ([2, 2], "Slide 3"),
            ([1, 3], "Slides 2 and 4"),
            ([3, 1], "Slides 2 and 4"),
            ([9, 1], "Slides 2 and 10"),
            ([4, 1, 3, 3], "Slides 2, 4 and 5"),
        ],
    )
    def test_unfinished_slides_notice(self, positions: list[int], phrase: str) -> None:
        notice = unfinished_slides_notice(positions, request_id="req-321")

        _assert_plain_notice(notice)
        assert END_WITH_OUTSTANDING not in notice.text
        for surface in (notice.text, notice.headline):
            assert surface.startswith(f"{phrase} "), f"expected {surface!r} to open with {phrase!r}"
        if len(set(positions)) == 1:
            assert_numbered(notice.text, positions[0])
            assert_numbered(notice.headline, positions[0])

    @pytest.mark.parametrize("error", ERRORS, ids=lambda e: f"error={e}")
    @pytest.mark.parametrize(
        "build",
        [
            lambda error: deck_not_updated_notice(
                review_skipped=False, error=error, request_id="req-321"
            ),
            lambda error: deck_not_updated_notice(
                review_skipped=True, error=error, request_id="req-321"
            ),
            lambda error: deck_review_failed_notice(error=error, request_id="req-321"),
        ],
        ids=["deck_not_updated", "deck_not_updated_review_skipped", "deck_review_failed"],
    )
    def test_deck_notice(self, build, error: str | None) -> None:
        notice = build(error)

        _assert_plain_notice(notice)
        for surface in (notice.text, notice.headline):
            assert not re.search(r"\b[Ss]lides? \d", surface), (
                f"a deck-level notice names no slide number: {surface!r}"
            )


# ---------------------------------------------------------------------------
# 2. Each kind carries its one action; no headline claims a placeholder.
# ---------------------------------------------------------------------------


class TestEachKindSaysWhatTheUserCanDo:
    @pytest.mark.parametrize("position", POSITIONS, ids=lambda p: f"pos{p}")
    def test_action_phrases(self, position: int) -> None:
        number = position + 1
        for kind, notice in _one_of_each_kind(position):
            if kind in SLIDE_KINDS:
                assert f"regenerate slide {number}" in notice.text, (kind, notice.text)
            if kind == "kept_unfixed":
                assert re.search(r"\bApply\b", notice.text), (kind, notice.text)
            if kind == "slides_unfinished":
                assert "send your request again" in notice.text, (kind, notice.text)
            if kind in DECK_KINDS:
                assert "next time I build or edit" in notice.text, (kind, notice.text)

    @pytest.mark.parametrize("position", POSITIONS, ids=lambda p: f"pos{p}")
    def test_only_placeholder_texts_claim_a_placeholder_and_no_headline_does(
        self, position: int
    ) -> None:
        for kind, notice in _one_of_each_kind(position):
            # The headline goes on the pre-commit ERROR event, before the
            # placeholder exists, so it must make no claim about one (D2).
            assert "placeholder" not in notice.headline.lower(), (kind, notice.headline)
            # A kept_* slide is shown as built, and a deck notice is about no
            # one slide: only the placeholder kinds may say "placeholder".
            assert ("placeholder" in notice.text) == (kind in PLACEHOLDER_KINDS), (
                kind,
                notice.text,
            )


# ---------------------------------------------------------------------------
# 3. Kind mapping.
# ---------------------------------------------------------------------------


class TestKindMapping:
    def test_the_stage_table(self) -> None:
        assert dict(PLACEHOLDER_STAGE_KINDS) == EXPECTED_STAGE_KINDS

    @pytest.mark.parametrize("position", POSITIONS, ids=lambda p: f"pos{p}")
    @pytest.mark.parametrize("stage", PLACEHOLDER_STAGES)
    def test_each_known_stage_maps_to_its_kind(self, stage: str, position: int) -> None:
        notice = placeholder_notice(position, stage=stage, error="RuntimeError")

        assert notice.kind == EXPECTED_STAGE_KINDS[stage]
        assert notice.stage == stage

    @pytest.mark.parametrize("stage", [UNKNOWN_STAGE, "fixer", "deck_reviewer", "architect", ""])
    def test_an_unknown_stage_falls_back_to_slide_failed(self, stage: str) -> None:
        notice = placeholder_notice(4, stage=stage, error="RuntimeError")

        assert notice.kind == "slide_failed"
        assert notice.stage == stage

    @pytest.mark.parametrize("stage", STAGES)
    def test_unsafe_overrides_every_stage(self, stage: str) -> None:
        notice = placeholder_notice(4, stage=stage, error="UnsafeContentError", unsafe=True)

        assert notice.kind == "blocked_unsafe"
        assert notice.stage == stage

    @pytest.mark.parametrize("stage", STAGES)
    def test_unsafe_defaults_to_false(self, stage: str) -> None:
        notice = placeholder_notice(4, stage=stage, error="UnsafeContentError")

        assert notice.kind == EXPECTED_STAGE_KINDS.get(stage, "slide_failed")

    @pytest.mark.parametrize(
        ("during", "kind", "stage"),
        [("review", "kept_unreviewed", "build_reviewer"), ("fix", "kept_unfixed", "fix_round")],
    )
    def test_during_selects_the_kept_kind(self, during: str, kind: str, stage: str) -> None:
        notice = unreviewed_slide_notice(4, during=during)

        assert (notice.kind, notice.stage, notice.error) == (
            kind,
            stage,
            MODEL_TEMPORARILY_UNAVAILABLE,
        )

    @pytest.mark.parametrize("during", ["reviewing", "Fix", "", None])
    def test_an_unknown_during_is_refused_not_relabelled(self, during) -> None:
        # Anything but "review" / "fix" must fail loudly, never read as one of them.
        with pytest.raises(ValueError):
            unreviewed_slide_notice(4, during=during)  # type: ignore[arg-type]

    def test_review_skipped_selects_the_deck_kind(self) -> None:
        assert (
            deck_not_updated_notice(review_skipped=False, error="RuntimeError").kind
            == "deck_not_updated"
        )
        assert (
            deck_not_updated_notice(review_skipped=True, error="RuntimeError").kind
            == "deck_not_updated_review_skipped"
        )
        assert deck_review_failed_notice(error="RuntimeError").kind == "deck_review_failed"


# ---------------------------------------------------------------------------
# 4. All twelve kinds read differently.
# ---------------------------------------------------------------------------


class TestKindsAreDistinct:
    def test_notice_kind_is_exactly_the_twelve_kinds(self) -> None:
        assert set(typing.get_args(NoticeKind)) == ALL_KINDS
        assert len(typing.get_args(NoticeKind)) == 12

    @pytest.mark.parametrize("position", POSITIONS, ids=lambda p: f"pos{p}")
    def test_every_kind_has_its_own_text_and_headline(self, position: int) -> None:
        pairs = _one_of_each_kind(position)

        assert [notice.kind for _, notice in pairs] == [kind for kind, _ in pairs]
        texts = [notice.text for _, notice in pairs]
        headlines = [notice.headline for _, notice in pairs]
        assert len(set(texts)) == 12, texts
        assert len(set(headlines)) == 12, headlines
        assert not set(texts) & set(headlines), (
            "a headline must be shorter than, not equal to, a text"
        )


# ---------------------------------------------------------------------------
# 5. details.
# ---------------------------------------------------------------------------


class TestDetails:
    @pytest.mark.parametrize("request_id", [None, "req-321"], ids=["no-request-id", "request-id"])
    @pytest.mark.parametrize("position", POSITIONS, ids=lambda p: f"pos{p}")
    def test_details_carry_only_stage_error_and_request_id(
        self, position: int, request_id: str | None
    ) -> None:
        for kind, notice in _one_of_each_kind(position, request_id=request_id):
            details = notice.details

            assert set(details) <= DETAIL_KEYS, (kind, details)
            assert all(isinstance(value, str) for value in details.values()), (kind, details)
            # Exactly the three technical fields, with None values dropped.
            expected = {"stage": notice.stage, "error": notice.error, "request_id": request_id}
            assert details == {k: v for k, v in expected.items() if v is not None}, kind
            assert ("request_id" in details) == (request_id is not None), (kind, details)
            if kind in SLIDE_KINDS or kind == "slides_unfinished":
                # The headline numbers the slide; a number in the disclosure
                # (0-based or not) would bring the off-by-one back (D3).
                for value in details.values():
                    assert value not in {str(position), str(position + 1)}, (kind, details)
            if kind in KEPT_KINDS:
                assert details["error"] == MODEL_TEMPORARILY_UNAVAILABLE, (kind, details)

    def test_a_missing_error_is_omitted_not_null(self) -> None:
        assert placeholder_notice(0, stage="builder", error=None).details == {"stage": "builder"}
        assert deck_not_updated_notice(review_skipped=False, error=None).details == {
            "stage": "deck_reviewer"
        }
        assert deck_not_updated_notice(review_skipped=True, error=None).details == {
            "stage": "deck_reviewer"
        }
        assert deck_review_failed_notice(error=None).details == {"stage": "deck_reviewer"}
        assert placeholder_notice(0, stage="builder", error=None).error is None

    def test_the_transient_code_is_a_fixed_literal(self) -> None:
        assert MODEL_TEMPORARILY_UNAVAILABLE == "model_temporarily_unavailable"

    def test_a_transient_notice_cannot_be_handed_an_exception(self) -> None:
        # By construction (#271): the caught exception for a transient fault is
        # a PersistedRuntimeError subclass, whose name must never reach a client.
        assert "error" not in inspect.signature(unreviewed_slide_notice).parameters
        with pytest.raises(TypeError):
            unreviewed_slide_notice(0, during="review", error="PinnedInvocationEndpointError")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 6. slide_number and slides_phrase.
# ---------------------------------------------------------------------------


class TestNumbering:
    @pytest.mark.parametrize(("position", "number"), [(0, 1), (1, 2), (9, 10)])
    def test_slide_number_is_one_based(self, position: int, number: int) -> None:
        assert slide_number(position) == number

    @pytest.mark.parametrize(
        ("positions", "phrase"),
        [
            ([3], "slide 4"),
            ([3, 1], "slides 2 and 4"),
            ([4, 1, 3, 3], "slides 2, 4 and 5"),
            ([0], "slide 1"),
            ([2, 2], "slide 3"),
            ([9, 1], "slides 2 and 10"),
            ((5, 0, 7, 2), "slides 1, 3, 6 and 8"),
            ({1, 0}, "slides 1 and 2"),
        ],
    )
    def test_slides_phrase(self, positions, phrase: str) -> None:
        assert slides_phrase(positions) == phrase

    def test_slides_phrase_reads_a_one_shot_iterable_once(self) -> None:
        assert slides_phrase(p for p in (3, 1, 3)) == "slides 2 and 4"

    @pytest.mark.parametrize("empty", [[], (), iter(())], ids=["list", "tuple", "iterator"])
    def test_slides_phrase_of_nothing_raises(self, empty) -> None:
        with pytest.raises(ValueError):
            slides_phrase(empty)

    def test_unfinished_slides_notice_of_nothing_raises(self) -> None:
        # No outstanding slide means no notice, not "Slides  couldn't be finished."
        with pytest.raises(ValueError):
            unfinished_slides_notice([])


# ---------------------------------------------------------------------------
# 7. Purity: stdlib only.
# ---------------------------------------------------------------------------


class TestModuleIsPure:
    def test_imports_only_future_dataclasses_and_typing(self) -> None:
        source = Path(user_notices.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append("." * node.level + (node.module or ""))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
            ):
                imported.append("__import__(...)")

        assert sorted(set(imported) - {"__future__", "dataclasses", "typing"}) == []


# ---------------------------------------------------------------------------
# The catalogue as an exact contract (transcribed from the plan, n = 3).
# ---------------------------------------------------------------------------

# The em dash (U+2014) the plan's catalogue uses, escaped so it cannot be mistyped.
_DASH = "\u2014"

CATALOGUE_AT_POSITION_2 = {
    "build_failed": (
        "Slide 3 couldn't be built.",
        f"Slide 3 couldn't be built, so it's shown as a placeholder {_DASH} "
        "ask me to regenerate slide 3.",
    ),
    "blocked_unsafe": (
        "Slide 3 was blocked by a safety check.",
        "Slide 3 was blocked by a safety check because it included something a deck "
        "can't contain, such as content loaded from the web. It's shown as a placeholder "
        f"{_DASH} ask me to regenerate slide 3 without it, for example without images or "
        "videos from other websites.",
    ),
    "check_failed": (
        "Slide 3 was built but couldn't be checked.",
        f"Slide 3 was built but couldn't be checked, so it's shown as a placeholder {_DASH} "
        "ask me to regenerate slide 3.",
    ),
    "save_failed": (
        "Slide 3 couldn't be saved after its automatic fix.",
        "Slide 3 couldn't be saved after its automatic fix, so it's shown as a placeholder "
        f"{_DASH} ask me to regenerate slide 3.",
    ),
    "stalled": (
        "Slide 3 didn't finish building.",
        f"Slide 3 didn't finish building, so it's shown as a placeholder {_DASH} "
        "ask me to regenerate slide 3.",
    ),
    "slide_failed": (
        "Slide 3 couldn't be generated.",
        f"Slide 3 couldn't be generated, so it's shown as a placeholder {_DASH} "
        "ask me to regenerate slide 3.",
    ),
    "kept_unreviewed": (
        "Slide 3 hasn't been checked.",
        "Slide 3 is shown as first built: the AI service was briefly unavailable, so it "
        "hasn't been checked. If it doesn't look right, ask me to regenerate slide 3.",
    ),
    "kept_unfixed": (
        "Slide 3 is shown without its automatic fix.",
        "Slide 3 is shown without its automatic fix because the AI service was briefly "
        f"unavailable. The issues found are in the slide's AI feedback {_DASH} choose Apply "
        "there to try the fix again, or ask me to regenerate slide 3.",
    ),
    "slides_unfinished": (
        "Slide 3 couldn't be finished.",
        "Slide 3 couldn't be finished this time and may be missing or out of date. "
        "Please send your request again.",
    ),
    "deck_not_updated": (
        "The deck couldn't be fully updated.",
        "Your slides were saved, but the deck couldn't be fully updated, so its slide count "
        "and exports may be out of date. They'll refresh the next time I build or edit slides.",
    ),
    "deck_not_updated_review_skipped": (
        "The deck couldn't be fully updated, and its review was skipped.",
        "Your slides were saved, but the deck couldn't be fully updated, so its slide count "
        "and exports may be out of date, and the review of the deck as a whole was skipped. "
        "Both will run again the next time I build or edit slides.",
    ),
    "deck_review_failed": (
        "The review of the deck as a whole couldn't run.",
        "The deck is ready, but the review of the deck as a whole couldn't run this time. "
        "It will run again the next time I build or edit slides.",
    ),
}

# (kind, call, stage, error, positions) — each builder's full technical side at position 2.
_RID = "req-321"
_CATALOGUE_CASES = [
    (
        "build_failed",
        lambda: placeholder_notice(2, stage="builder", error="ValidationError", request_id=_RID),
        "builder",
        "ValidationError",
        (2,),
    ),
    (
        "blocked_unsafe",
        lambda: placeholder_notice(
            2, stage="builder", error="UnsafeContentError", unsafe=True, request_id=_RID
        ),
        "builder",
        "UnsafeContentError",
        (2,),
    ),
    (
        "check_failed",
        lambda: placeholder_notice(
            2, stage="build_reviewer", error="ValidationError", request_id=_RID
        ),
        "build_reviewer",
        "ValidationError",
        (2,),
    ),
    (
        "save_failed",
        lambda: placeholder_notice(2, stage="fix_reviewer", error="RuntimeError", request_id=_RID),
        "fix_reviewer",
        "RuntimeError",
        (2,),
    ),
    (
        "stalled",
        lambda: placeholder_notice(2, stage="placeholder", error=STALL_REASON, request_id=_RID),
        "placeholder",
        STALL_REASON,
        (2,),
    ),
    (
        "slide_failed",
        lambda: placeholder_notice(2, stage=UNKNOWN_STAGE, error="KeyError", request_id=_RID),
        UNKNOWN_STAGE,
        "KeyError",
        (2,),
    ),
    (
        "kept_unreviewed",
        lambda: unreviewed_slide_notice(2, during="review", request_id=_RID),
        "build_reviewer",
        "model_temporarily_unavailable",
        (2,),
    ),
    (
        "kept_unfixed",
        lambda: unreviewed_slide_notice(2, during="fix", request_id=_RID),
        "fix_round",
        "model_temporarily_unavailable",
        (2,),
    ),
    (
        "slides_unfinished",
        lambda: unfinished_slides_notice([2], request_id=_RID),
        "foreman",
        END_WITH_OUTSTANDING,
        (2,),
    ),
    (
        "deck_not_updated",
        lambda: deck_not_updated_notice(
            review_skipped=False, error="RuntimeError", request_id=_RID
        ),
        "deck_reviewer",
        "RuntimeError",
        (),
    ),
    (
        "deck_not_updated_review_skipped",
        lambda: deck_not_updated_notice(review_skipped=True, error="RuntimeError", request_id=_RID),
        "deck_reviewer",
        "RuntimeError",
        (),
    ),
    (
        "deck_review_failed",
        lambda: deck_review_failed_notice(error="RuntimeError", request_id=_RID),
        "deck_reviewer",
        "RuntimeError",
        (),
    ),
]


class TestCatalogueIsTheContract:
    def test_every_kind_is_pinned(self) -> None:
        assert set(CATALOGUE_AT_POSITION_2) == ALL_KINDS
        assert [case[0] for case in _CATALOGUE_CASES] == list(CATALOGUE_AT_POSITION_2)

    @pytest.mark.parametrize(
        ("kind", "build", "stage", "error", "positions"),
        _CATALOGUE_CASES,
        ids=[case[0] for case in _CATALOGUE_CASES],
    )
    def test_the_whole_notice(self, kind, build, stage, error, positions) -> None:
        headline, text = CATALOGUE_AT_POSITION_2[kind]

        assert dataclasses.asdict(build()) == {
            "kind": kind,
            "headline": headline,
            "text": text,
            "stage": stage,
            "error": error,
            "positions": positions,
            "details": {"stage": stage, "error": error, "request_id": _RID},
        }

    @pytest.mark.parametrize(
        ("outstanding", "phrase", "positions"),
        [
            ((p for p in (3, 1, 3)), "Slides 2 and 4", (1, 3)),
            ([4, 1, 3, 3], "Slides 2, 4 and 5", (1, 3, 4)),
            ([9, 0], "Slides 1 and 10", (0, 9)),
        ],
        ids=["generator-with-duplicate", "unsorted-with-duplicate", "two-digit"],
    )
    def test_unfinished_slides_sorts_and_deduplicates(
        self, outstanding, phrase: str, positions
    ) -> None:
        assert dataclasses.asdict(unfinished_slides_notice(outstanding)) == {
            "kind": "slides_unfinished",
            "headline": f"{phrase} couldn't be finished.",
            "text": f"{phrase} couldn't be finished this time and may be missing or out of date. "
            "Please send your request again.",
            "stage": "foreman",
            "error": END_WITH_OUTSTANDING,
            "positions": positions,
            "details": {"stage": "foreman", "error": END_WITH_OUTSTANDING},
        }


# ---------------------------------------------------------------------------
# The FailureNotice value and the builders' call shape (Task 3 relies on both).
# ---------------------------------------------------------------------------


class TestFailureNoticeShape:
    def test_fields_in_order(self) -> None:
        assert [field.name for field in dataclasses.fields(FailureNotice)] == [
            "kind",
            "headline",
            "text",
            "stage",
            "error",
            "positions",
            "details",
        ]

    @pytest.mark.parametrize(
        "field", ["kind", "headline", "text", "stage", "error", "positions", "details"]
    )
    def test_is_frozen(self, field: str) -> None:
        notice = placeholder_notice(0, stage="builder", error="RuntimeError")

        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(notice, field, "changed")

    @pytest.mark.parametrize(
        ("function", "expected"),
        [
            (slide_number, [("position", "positional", inspect.Parameter.empty)]),
            (slides_phrase, [("positions", "positional", inspect.Parameter.empty)]),
            (
                placeholder_notice,
                [
                    ("position", "positional", inspect.Parameter.empty),
                    ("stage", "keyword", inspect.Parameter.empty),
                    ("error", "keyword", inspect.Parameter.empty),
                    ("unsafe", "keyword", False),
                    ("request_id", "keyword", None),
                ],
            ),
            (
                unreviewed_slide_notice,
                [
                    ("position", "positional", inspect.Parameter.empty),
                    ("during", "keyword", inspect.Parameter.empty),
                    ("request_id", "keyword", None),
                ],
            ),
            (
                unfinished_slides_notice,
                [
                    ("positions", "positional", inspect.Parameter.empty),
                    ("request_id", "keyword", None),
                ],
            ),
            (
                deck_not_updated_notice,
                [
                    ("review_skipped", "keyword", inspect.Parameter.empty),
                    ("error", "keyword", inspect.Parameter.empty),
                    ("request_id", "keyword", None),
                ],
            ),
            (
                deck_review_failed_notice,
                [("error", "keyword", inspect.Parameter.empty), ("request_id", "keyword", None)],
            ),
        ],
        ids=lambda value: getattr(value, "__name__", None),
    )
    def test_signature(self, function, expected) -> None:
        kinds = {
            inspect.Parameter.POSITIONAL_OR_KEYWORD: "positional",
            inspect.Parameter.KEYWORD_ONLY: "keyword",
        }
        actual = [
            (name, kinds.get(param.kind, str(param.kind)), param.default)
            for name, param in inspect.signature(function).parameters.items()
        ]
        assert actual == expected


# ---------------------------------------------------------------------------
# The shared assertions themselves are not vacuous (Task 3 reuses them).
# ---------------------------------------------------------------------------


class TestNoticeAssertionHelpers:
    @pytest.mark.parametrize(
        ("text", "offending"),
        [
            (
                "Slide 1 could not be generated (build_reviewer: ValidationError).",
                ["(", "build_reviewer", "ValidationError"],
            ),
            (
                "Some slides could not be reconciled: positions [1, 3].",
                ["reconcile", "position", "["],
            ),
            ("The fix_reviewer stage stopped.", ["fix_reviewer"]),
            ("An OutputParserException happened.", ["OutputParserException"]),
            ("Exception while saving.", ["Exception"]),
            ("The builder gave up.", ["builder"]),
            ("Builder gave up.", ["Builder"]),
            ("The fixer gave up.", ["fixer"]),
            ("The foreman gave up.", ["foreman"]),
            ("The architect gave up.", ["architect"]),
            ("The deck_reviewer gave up.", ["deck_reviewer"]),
            ("Code end_with_outstanding_positions.", ["end_with_outstanding_positions"]),
            ("A RuntimeError.", ["RuntimeError"]),
            ("A KeyError.", ["KeyError"]),
        ],
    )
    def test_rejects_a_technical_leak_and_names_it(self, text: str, offending: list[str]) -> None:
        with pytest.raises(AssertionError) as raised:
            assert_plain_language(text)

        message = str(raised.value)
        for token in offending:
            assert token in message, f"the failure should name {token!r}: {message}"

    @pytest.mark.parametrize(
        ("text", "offence"),
        [
            # Today's stall notice: "placeholder" is not an identifier the check
            # bans, so the "(" check is the only thing that catches this suffix.
            (
                "Slide 2 could not be generated and has been left as a placeholder "
                "(placeholder: Slide generation did not complete).",
                "character '('",
            ),
            # Today's 0-based rebuild line: only the "[" check catches it.
            ("Rebuilding 1: [2].", "character '['"),
            ("Slide 3 is at position 2.", "internal word 'position'"),
            ("The deck could not be reconciled.", "internal word 'reconcile'"),
            ("Code fix_round.", "snake_case token 'fix_round'"),
            ("A TimeoutError happened.", "CamelCase token 'TimeoutError'"),
            # Acronym-led class names slip past the plain CamelCase pattern.
            ("A JSONDecodeError happened.", "CamelCase token 'JSONDecodeError'"),
            ("An OSError happened.", "CamelCase token 'OSError'"),
            ("Exception while saving.", "exception class name 'Exception'"),
            ("The foreman gave up.", "stage identifier 'foreman' (matches 'foreman')"),
        ],
    )
    def test_each_check_fires_on_its_own(self, text: str, offence: str) -> None:
        # The failure message echoes the whole text, so "the token is in the
        # message" cannot tell which check fired. Each text here trips exactly one
        # check, so disabling any one of them turns its case red.
        assert plain_language_offences(text) == [offence]

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_rejects_an_empty_notice(self, text) -> None:
        with pytest.raises(AssertionError):
            assert_plain_language(text)

    def test_whole_words_only(self) -> None:
        # "built", "building", "build", "fix", "fixed", "deck", "review", "Apply"
        # and "AI" are ordinary English — none may trip an identifier check.
        text = (
            "The slide was built while building the deck; the build was fixed by its fix, "
            f"its review ran, and AI feedback {_DASH} choose Apply."
        )
        assert plain_language_offences(text) == []
        assert_plain_language(text)

    def test_numbered_accepts_the_one_based_number(self) -> None:
        assert_numbered("Slide 3 couldn't be built. Regenerate slide 3.", 2)
        assert_numbered("Slide 10 couldn't be built.", 9)

    @pytest.mark.parametrize(
        ("text", "position"),
        [
            ("Slide 2 couldn't be built.", 2),  # 0-based
            ("Slide 3 couldn't be built; regenerate slide 2.", 2),  # 0-based in the action
            ("Slide 10 couldn't be built.", 0),  # "Slide 1" must be a whole number
            ("Slides 1 and 2 couldn't be built.", 0),  # plural is not "Slide 1"
            ("The deck couldn't be updated.", 0),
        ],
    )
    def test_numbered_rejects(self, text: str, position: int) -> None:
        with pytest.raises(AssertionError):
            assert_numbered(text, position)

    def test_failure_notice_records_selects_only_notice_lines(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        log = logging.getLogger("tests.notice_assertions_selftest")

        log.warning("graph_failure_notice kind=%s stage=%s", "build_failed", "builder")
        log.warning("graph_failure_noticekind=x")
        log.warning("note: graph_failure_notice kind=x")
        log.warning("something else")

        records = failure_notice_records(caplog)
        assert [record.getMessage() for record in records] == [
            "graph_failure_notice kind=build_failed stage=builder"
        ]
