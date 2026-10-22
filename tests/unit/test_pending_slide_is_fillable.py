# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""A pending slide is a hole the builder fills; a judged slide is not (#314, D9).

An insert opens a pending placeholder row at the new position before any
builder runs (Task 2).  Two call sites decide whether a row is "a placeholder":

* ``_write_draft_row`` only drafts into an EMPTY position.  A pending row is a
  row, so today the inserted slide gets no draft preview, and a transient review
  failure there fails the whole turn instead of keeping the draft.
* ``rereview_committed_slides`` auto-fails a placeholder with no model call.
  Today it asks ``is_placeholder_record`` of the WHOLE record, which is also true
  for a slide whose judge errored (the judge's own ``error: True``) and for a
  slide that was once pending and has since been built (hash-keyed history is
  merged, never dropped).

The fix judges the row's CURRENT verdict with the strict predicate
``is_placeholder_verdict`` (keys within ``{"error", "message"}``).  Each test
below fails under one of the plausible wrong versions:

* keep ``get_slide(...) is not None``         -> (a), (b) red;
* plain ``is_placeholder_record`` on the
  current verdict (a judge error counts)      -> (c) red;
* the whole-record check                      -> (c) and (d) red;
* the strict predicate on the whole record,
  or on the wrong key                         -> (a), (b), (e) red.

(a)/(b) and the draft side of (c)/(d) run the compiled graph exactly as
``test_slide_pipeline.py`` does (its BUILD architect stub suits them: every
position is built).  The re-review side calls ``rereview_committed_slides``
directly with a brand dict, as ``test_deck_level_spec_change.py`` does.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

import pytest

from src.api.services.session_manager import _merge_verdict_slots
from src.api.services.slide_repository import (
    PENDING_SLIDE_MESSAGE,
    PENDING_SLIDE_TEXT,
    placeholder_slide,
)
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.domain.finding import VERDICT_KEY, build_verification_record
from src.services.graph.nodes import rereview_committed_slides
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest_graph import (  # noqa: F401 — fixtures
    graph_env,
    graph_env_threadsafe,
    make_spec,
    review_out,
)
from tests.unit.test_slide_pipeline import _rows, _run, _transient, _wire

#: What ``builder_out`` drafts at position 1 / 0.
DRAFT_0 = "<div class='slide'>slide 0</div>"
DRAFT_1 = "<div class='slide'>slide 1</div>"
COMMITTED_0 = "<div class='slide'>committed 0</div>"
COMMITTED_1 = "<div class='slide'>committed 1</div>"

#: The pending row an insert opens (Task 2), and a failed position's placeholder
#: (``commit_placeholder``'s shape, built by the same helper).
PENDING = placeholder_slide(PENDING_SLIDE_MESSAGE, text=PENDING_SLIDE_TEXT)
FAILED = placeholder_slide("builder: model exploded")

#: The LLM judge's real error payload: ``verification.py``'s
#: ``verification_result`` dict, with the values ``llm_judge``'s except branch
#: returns.  It sets ``error: True`` — and carries a judgement's other keys.
JUDGE_ERROR_VERDICT = {
    "score": 0,
    "rating": "error",
    "explanation": "Evaluation failed: upstream timeout",
    "issues": [{"type": "error", "detail": "upstream timeout"}],
    "duration_ms": 1234,
    "trace_id": None,
    "genie_conversation_id": "conv-1",
    "error": True,
    "error_message": "upstream timeout",
}


def _reviewed(html: str) -> Dict[str, Any]:
    """The graph reviewer's clean record for *html* (``build_verification_record``)."""
    return build_verification_record(
        content_hash=compute_slide_hash(html), findings=[], verdict="clean"
    )


def _judge_errored(html: str, *, reviewed: bool) -> Dict[str, Any]:
    """*html*'s record after the judge errored on it.

    ``reviewed=True`` is a graph-reviewed slide the user then verified: the
    judge's keys are merged into the SAME per-hash slot as ``tellr_review``
    (``_merge_verdict_slots``, the merge ``write_slide_verification`` uses).
    ``reviewed=False`` is a slide only the judge has scored.
    """
    judged = {compute_slide_hash(html): dict(JUDGE_ERROR_VERDICT)}
    return _merge_verdict_slots(_reviewed(html), judged) if reviewed else judged


def _once_pending(html: str, *, reviewed: bool) -> Dict[str, Any]:
    """*html*'s record after it was built into a pending position.

    The pending verdict stays under the pending HTML's OLD hash (records are
    merged by hash, never pruned).  ``reviewed=True``: the built slide's review
    landed.  ``reviewed=False``: the draft was kept after a transient review
    failure, so the current hash has no verdict at all — exactly the row (b)
    leaves behind.
    """
    record = dict(PENDING[1])
    if reviewed:
        record.update(_reviewed(html))
    return record


def _seed(env, rows: List[Tuple[str, Optional[Dict[str, Any]]]]) -> None:
    """Commit ``(html, verification_record)`` rows at positions 0..n-1, plus the deck row.

    ``env.seed_slides`` writes no verification record, so this goes to the ORM.
    """
    db = env.factory()
    try:
        owner = (
            db.query(UserSession)
            .filter(UserSession.session_id == env.session_id)
            .one()
        )
        if (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner.id)
            .first()
            is None
        ):
            db.add(
                SessionSlideDeck(
                    session_id=owner.id,
                    html_content="",
                    scripts_content=None,
                    slide_count=len(rows),
                    version=1,
                )
            )
        for position, (html, record) in enumerate(rows):
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    slide_id=str(uuid.uuid4()),
                    html=html,
                    scripts="",
                    verification_record=(
                        json.dumps(record) if record is not None else None
                    ),
                )
            )
        db.commit()
    finally:
        db.close()


def _record_html_at_review(env) -> Dict[int, Any]:
    """Make the build reviewer note the committed row's HTML when it is called."""
    seen: Dict[int, Any] = {}

    def reviewer(payload):
        row = _rows(env).get(payload["position"])
        seen[payload["position"]] = row.html if row else None
        return review_out(payload["position"])

    env.skills.set("build_reviewer", reviewer)
    return seen


def _brand() -> Dict[str, Any]:
    return {
        "resolved_style": "STUB STYLE PROSE",
        "deterministic_css": ".slide { color: red; }",
        "design_system_active": False,
        "template_layout_html": "",
    }


def _rereview(env, positions=(0, 1)) -> Dict[str, Any]:
    env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))
    return rereview_committed_slides(env.session_id, make_spec(positions), _brand(), 1)


def _reviewed_positions(env) -> List[int]:
    return [c["payload"]["position"] for c in env.skills.calls_for("build_reviewer")]


_JUDGE_SHAPES = pytest.mark.parametrize(
    "reviewed", [True, False], ids=["reviewed_then_judge_errored", "judge_errored_only"]
)
_ONCE_PENDING_SHAPES = pytest.mark.parametrize(
    "reviewed", [True, False], ids=["built_and_reviewed", "kept_draft_no_verdict"]
)


# ---------------------------------------------------------------------------
# (a), (b): a placeholder position is empty, so the builder's draft fills it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("placeholder", [PENDING, FAILED], ids=["pending", "failed"])
def test_a_a_placeholder_position_gets_the_builder_s_draft_before_review(
    graph_env_threadsafe, placeholder
):
    """(a) The reviewer of the placeholder position reads the builder's draft.

    Position 0 holds a real slide and keeps it until its reviewed write; the
    placeholder at 1 holds no slide to protect, so the draft replaces it at once.
    """
    env = graph_env_threadsafe
    _wire(env, (0, 1))
    _seed(env, [(COMMITTED_0, None), placeholder])
    seen = _record_html_at_review(env)

    _run(env)

    assert seen == {0: COMMITTED_0, 1: DRAFT_1}, (
        "the placeholder at position 1 was treated as a committed slide: its "
        "reviewer saw the placeholder, not the draft"
    )
    rows = _rows(env)
    assert {p: rows[p].html for p in rows} == {0: DRAFT_0, 1: DRAFT_1}


def test_b_a_transient_review_failure_at_a_pending_position_keeps_the_draft(
    graph_env_threadsafe,
):
    """(b) The pending position was drafted, so a rate-limited review keeps the
    draft and the turn finishes, as on a fresh position."""
    env = graph_env_threadsafe
    _wire(env, (0, 1))
    _seed(env, [(COMMITTED_0, None), PENDING])
    clean = env.skills._handlers["build_reviewer"]
    env.skills.set(
        "build_reviewer",
        lambda p: _transient("opus")(p) if p["position"] == 1 else clean(p),
    )

    _run(env)  # a failed turn raises PinnedInvocationEndpointError here

    rows = _rows(env)
    assert rows[1].html == DRAFT_1
    record = json.loads(rows[1].verification_record)
    assert compute_slide_hash(DRAFT_1) not in record, (
        f"the kept draft must read as unreviewed, not clean: {record}"
    )
    assert len(env.skills.calls_for("deck_reviewer")) == 1
    info = [m for m in env.messages() if m["message_type"] == "info"]
    # #321 numbers the notice 1-based: position 1 is "Slide 2".
    assert any("Slide 2" in m["content"] for m in info), info


# ---------------------------------------------------------------------------
# (c): a judged slide whose judge errored is a real slide
# ---------------------------------------------------------------------------


@_JUDGE_SHAPES
def test_c_a_judge_errored_slide_gets_no_draft(graph_env_threadsafe, reviewed):
    """(c) The judge's ``error: True`` sits in the slide's CURRENT slot, but the
    slot is a judgement, not a placeholder: the committed slide stays visible
    until its reviewed write, so an edit's unreviewed draft never replaces it."""
    env = graph_env_threadsafe
    _wire(env, (0,))
    record = _judge_errored(COMMITTED_0, reviewed=reviewed)
    assert record[compute_slide_hash(COMMITTED_0)]["error"] is True  # the hazard
    assert (VERDICT_KEY in record[compute_slide_hash(COMMITTED_0)]) is reviewed
    _seed(env, [(COMMITTED_0, record)])
    seen = _record_html_at_review(env)

    _run(env)

    assert seen == {0: COMMITTED_0}, (
        "a judge-errored slide was treated as a placeholder: a draft replaced it "
        "before review"
    )


@_JUDGE_SHAPES
def test_c_a_judge_errored_slide_is_re_reviewed_by_the_model(graph_env, reviewed):
    """(c) ...and the re-review pass asks the model about it rather than
    auto-failing it as placeheld (which would rebuild it with no review)."""
    env = graph_env
    _seed(
        env,
        [
            (COMMITTED_0, _reviewed(COMMITTED_0)),
            (COMMITTED_1, _judge_errored(COMMITTED_1, reviewed=reviewed)),
        ],
    )

    verdicts = _rereview(env)

    assert verdicts["placeheld"] == set()
    assert verdicts["failing"] == set()
    assert verdicts["reviewed"] == {0, 1}
    assert _reviewed_positions(env) == [0, 1]
    assert env.skills.calls_for("build_reviewer")[1]["payload"]["html"] == COMMITTED_1


# ---------------------------------------------------------------------------
# (d): a slide built into a pending position keeps the OLD pending hash
# ---------------------------------------------------------------------------


@_ONCE_PENDING_SHAPES
def test_d_a_slide_that_was_once_pending_is_re_reviewed_by_the_model(
    graph_env, reviewed
):
    """(d) Only the old pending HTML's hash carries the placeholder verdict; the
    slide now there is real, so the model reviews it."""
    env = graph_env
    _seed(
        env,
        [
            (COMMITTED_0, _reviewed(COMMITTED_0)),
            (COMMITTED_1, _once_pending(COMMITTED_1, reviewed=reviewed)),
        ],
    )

    verdicts = _rereview(env)

    assert verdicts["placeheld"] == set(), (
        "a slide built over a pending row was auto-failed on its old pending hash"
    )
    assert verdicts["failing"] == set()
    assert verdicts["reviewed"] == {0, 1}
    assert _reviewed_positions(env) == [0, 1]


@_ONCE_PENDING_SHAPES
def test_d_a_slide_that_was_once_pending_gets_no_draft(graph_env_threadsafe, reviewed):
    """(d) ...and, being a real committed slide, it is not replaced by a draft."""
    env = graph_env_threadsafe
    _wire(env, (0,))
    _seed(env, [(COMMITTED_0, _once_pending(COMMITTED_0, reviewed=reviewed))])
    seen = _record_html_at_review(env)

    _run(env)

    assert seen == {0: COMMITTED_0}


# ---------------------------------------------------------------------------
# (e): a genuine placeholder still fails by definition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "placeholder",
    [
        PENDING,
        FAILED,
        # A real slide that a later rebuild placeheld: its old hash keeps a real
        # verdict, the current one is the placeholder's.
        (FAILED[0], {**_reviewed(COMMITTED_1), **FAILED[1]}),
    ],
    ids=["pending", "failed", "failed_over_a_reviewed_slide"],
)
def test_e_a_genuine_placeholder_still_fails_with_no_model_call(graph_env, placeholder):
    """(e) There is no slide to judge, so no model is paid to say so."""
    env = graph_env
    _seed(env, [(COMMITTED_0, _reviewed(COMMITTED_0)), placeholder])

    verdicts = _rereview(env)

    assert verdicts["placeheld"] == {1}
    assert verdicts["failing"] == {1}
    assert verdicts["reviewed"] == {0}
    assert _reviewed_positions(env) == [0]
