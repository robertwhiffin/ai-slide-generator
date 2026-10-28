# ruff: noqa: F811 — the conftest_graph fixtures are imported, then requested by name.
"""One architect retry, the deferred message and the refusal note (architect edit
operations, plan Task 5; spec §5, §7; PLAN-CORRECTIONS C8, C11).

* **One retry.**  A retryable planning refusal (operations problems, binding
  errors, DeckSpec problems, today's alignment refusals) calls the architect ONCE
  more with the same payload plus ``rejected_edit = {"your_previous_answer": …,
  "problems": [{"code", "positions", "detail"}]}``.  The second answer is handled
  from the top and may be another intent.  Nothing the model cannot fix retries.
* **The deferred message.**  For ``build``/``edit`` the model's own message is
  said (emitted AND persisted) only once every check and the row layout have
  succeeded, before the deck-level re-review and its notice.  On any refusal only
  the refusal is said; a refused answer's message reaches neither surface.
* **The refusal row** carries ``metadata={"architect_refusal": {"code", "problems"}}``
  and ``_conversation`` replays it followed by a ``system`` note naming why.

How this file asserts, and why:

* The architect stub answers A on a first call and B when ``rejected_edit`` is in
  the payload, and snapshots every payload it is handed (deep copies, at call
  time).  Calls are counted exactly, and the second payload is compared with the
  first: identical but for ``rejected_edit``.  ``rejected_edit`` is compared after a
  JSON round trip (the payload is JSON-serialised for the model), so a tuple of
  positions and a list are the same, and anything not JSON-native fails.
* Both surfaces are read in full: every ``ASSISTANT`` event the turn emitted, and
  every transcript row it added (role, content, type, metadata), in order.  A
  refused answer's message is checked absent from EVERY event and EVERY row.
* "Nothing changed" is the whole-database snapshot of ``test_architect_insert_slide``.
"""

from __future__ import annotations

import copy
import inspect
import json
import queue
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Sequence

import pytest

from src.api.schemas.streaming import StreamEventType
from src.api.services.session_manager import SessionManager, get_session_manager
from src.api.services.slide_repository import SlideRowsChangedError, SlideWriter
from src.domain.deck_spec import DesignContractRef
from src.domain.skill_io import ArchitectOutput
from src.domain.slide_alignment import AlignmentRefused, align_slides
from src.domain.slide_operations import DeckChanges
from src.services.graph import nodes
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import architect_node
from src.services.graph.state import scoped
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    graph_env,
    make_spec,
    review_out,
)
from tests.unit.test_architect_edit_operations import (
    NEW_AUDIENCE,
    REJECTED_PREFIX,
    _assert_laid_out,
    _content,
    _delete,
    _insert,
    _mk,
    _ops_out,
    _replace,
    _seeded,
    _spec_from,
    _update,
)
from tests.unit.test_architect_insert_slide import (
    REFUSAL_TEXT,
    _canonical,
    _db_state,
    _edit_out,
    _new,
    _persist,
    _persisted_spec,
    _seed_rows,
    _spec_of,
)

#: The keys of ``your_previous_answer`` (spec §5), dumped as the brief says.
PREVIOUS_ANSWER_FIELDS = {"intent", "operations", "deck_changes", "target_positions"}

#: The system note's fixed opening (spec §7, plan Task 5).
NOTE_PREFIX = (
    "The edit above was NOT applied; nothing in the deck changed. "
    "It was rejected because: "
)

#: C11: the operations path's row-write refusals, edit-neutral.
OPS_ROWS_CHANGED = (
    "The deck changed while I was planning, so I have not made that edit. "
    "Nothing has been changed; please ask again."
)
OPS_ROWS_FAILED = (
    "I could not make that edit, so nothing has been changed. Please try asking again."
)

SPEC_POSITIONS_STALE = (
    "This deck has changed since I last described it — its slides no longer line "
    "up with the plan I hold — so I have not rebuilt anything. Tell me what this "
    "deck should say and I will describe it again from what is there now."
)
EDIT_WITHOUT_SPEC = (
    "I could not find a deck specification to edit for this session. Tell me what "
    "you would like to build and I will draft one."
)
EDIT_WITHOUT_REVISED_SPEC = (
    "I could not apply that edit: I did not produce an updated plan for the deck, "
    "so nothing has been changed. Please try asking again."
)
BINDING_PREFIX = (
    "I could not use that plan because a slide is bound to a template section "
    "that does not match: "
)
STYLE_DROPPED = (
    "Note: a design system and a slide style cannot both apply to one deck, so "
    "confirming this drops the slide style this deck currently uses (slide style "
    "5). Confirming also rebuilds every slide against the new design, because a "
    "restyle affects all of them."
)

#: Distinct, greppable model messages: a refused answer's must appear nowhere.
A_MSG = "FIRST-ANSWER: the edit is done."
B_MSG = "SECOND-ANSWER: the edit is done."

_POSITIONS_0_21 = ", ".join(str(p) for p in range(22))


def _unknown(position: int, label: str = "position") -> Dict[str, Any]:
    """Task 1's ``unknown_slide`` problem on the 22-slide deck, as a JSON dict."""
    return {
        "code": "unknown_slide",
        "positions": [position],
        "detail": (
            f"{label} {position} is not a slide of the deck (positions: {_POSITIONS_0_21})"
        ),
    }


def _half_bound_error(slide_number: int) -> str:
    """``invalid_slide_bindings``' error for a ``slide_type`` with no index."""
    return (
        f"slide {slide_number}: slide_type='title', template_section_index=None — "
        "slide_type and template_section_index must be set together or both left empty"
    )


# ---------------------------------------------------------------------------
# The architect stub, and running one turn
# ---------------------------------------------------------------------------


class _Answers:
    """A first answer, and a second for a payload carrying ``rejected_edit``.

    Every payload is deep-copied when it is handed over, so a later in-place
    mutation of the caller's dict cannot rewrite what the model was shown.
    """

    def __init__(self, first: Any, second: Any = None) -> None:
        self.first = first
        self.second = second
        self.seen: List[Dict[str, Any]] = []

    def __call__(self, payload: Dict[str, Any]) -> Any:
        self.seen.append(copy.deepcopy(payload))
        if "rejected_edit" in payload:
            assert self.second is not None, "this test expects no retry"
            return self.second
        return self.first


class _LoggingQueue(queue.Queue):
    """The turn's emitter, also recording each event into a shared order log."""

    def __init__(self, log: List[tuple]) -> None:
        super().__init__()
        self._log = log

    def put(self, item, block=True, timeout=None):  # noqa: D401 - queue API
        self._log.append(("event", item.type, item.content))
        super().put(item, block, timeout)


def _turn(env, answers: _Answers, *, log: Optional[List[tuple]] = None, **overrides):
    """Run ``architect_node`` once; return updates, every event and every new row."""
    env.skills.set("architect", answers)
    before = len(env.messages())
    state = env.state(**overrides)
    emitter: queue.Queue = _LoggingQueue(log) if log is not None else queue.Queue()
    set_event_emitter(emitter)
    try:
        updates = architect_node(state)
    finally:
        set_event_emitter(None)
    events = []
    while not emitter.empty():
        events.append(emitter.get_nowait())
    rows = env.messages()[before:]
    return SimpleNamespace(
        state=state,
        updates=updates,
        events=events,
        assistant=[e.content for e in events if e.type == StreamEventType.ASSISTANT],
        rows=rows,
        said=[(m["role"], m["content"], m["message_type"]) for m in rows],
    )


def _calls(env) -> int:
    return len(env.skills.calls_for("architect"))


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _previous(answer: ArchitectOutput) -> Dict[str, Any]:
    return answer.model_dump(include=PREVIOUS_ANSWER_FIELDS, mode="json")


def _assert_retried_with(answers: _Answers, env, first: ArchitectOutput) -> List[Dict]:
    """Exactly two calls; the second is the first payload plus ``rejected_edit``.

    Returns the second payload's problems (JSON round-tripped).
    """
    assert _calls(env) == 2, f"expected exactly one retry, got {_calls(env)} calls"
    assert len(answers.seen) == 2
    original, retry = answers.seen
    assert "rejected_edit" not in original, "the FIRST call was told of a rejection"
    # The runtime's own record of the first call (the dict object it was handed):
    # the retry payload is a NEW dict (`payload | {"rejected_edit": …}`), so the
    # first call's payload is not rewritten after the fact.
    assert "rejected_edit" not in env.skills.calls_for("architect")[0]["payload"], (
        "the retry mutated the first call's payload in place"
    )
    assert {k: v for k, v in retry.items() if k != "rejected_edit"} == original, (
        "the retry payload must be the same payload plus rejected_edit"
    )
    rejected = _json(retry["rejected_edit"])
    assert set(rejected) == {"your_previous_answer", "problems"}, rejected
    assert rejected["your_previous_answer"] == _previous(first)
    problems = rejected["problems"]
    assert isinstance(problems, list) and problems, problems
    for problem in problems:
        assert set(problem) == {"code", "positions", "detail"}, problem
        assert isinstance(problem["positions"], list), problem
        assert isinstance(problem["detail"], str) and problem["detail"], problem
    return problems


def _assert_nowhere(env, t: SimpleNamespace, *messages: str) -> None:
    """None of *messages* reached any event or any transcript row (the whole one)."""
    contents = [e.content or "" for e in t.events]
    transcript = [m.get("content") or "" for m in env.messages()]
    for message in messages:
        assert all(message not in c for c in contents), (
            f"a refused answer's message reached the SSE stream: {message!r}"
        )
        assert all(message not in c for c in transcript), (
            f"a refused answer's message reached the transcript: {message!r}"
        )


def _assert_only_refusal(env, t: SimpleNamespace, code: str, sentence: str) -> Dict:
    """A degrade whose refusal is the ONLY thing said, on both surfaces.

    Returns the refusal row's ``architect_refusal`` metadata.
    """
    updates = t.updates
    assert updates["architect_intent"] == "discuss"
    assert updates["error_state"]["node"] == "architect"
    assert updates["error_state"]["code"] == code
    assert updates["architect_message"] == sentence
    assert updates["target_positions"] is None
    assert "deck_spec" not in updates
    assert t.assistant == [sentence], (
        "on a refusal only the refusal is emitted; the model's own line must not "
        f"precede it: {t.assistant}"
    )
    assert t.said == [("assistant", sentence, "llm_response")], (
        f"on a refusal only the refusal is persisted: {t.said}"
    )
    metadata = t.rows[0]["metadata"]
    assert isinstance(metadata, dict) and set(metadata) == {"architect_refusal"}, metadata
    refusal = metadata["architect_refusal"]
    assert set(refusal) == {"code", "problems"}, refusal
    assert refusal["code"] == code
    assert isinstance(refusal["problems"], list)
    for problem in refusal["problems"]:
        assert set(problem) == {"code", "positions", "detail"}, problem
    return refusal


def _assert_plain_row(row: Dict[str, Any], content: str) -> None:
    """An ordinary assistant turn: no refusal metadata."""
    assert (row["role"], row["content"], row["message_type"]) == (
        "assistant",
        content,
        "llm_response",
    )
    assert "architect_refusal" not in (row["metadata"] or {}), row["metadata"]


def _user(env, content: str) -> None:
    get_session_manager().add_message(
        env.session_id, role="user", content=content, message_type="user_query"
    )


# ---------------------------------------------------------------------------
# 1. A bad operations list, then a good one: the second lands
# ---------------------------------------------------------------------------


def test_bad_operations_then_good_retry_applies(graph_env, monkeypatch):
    """A replaces position 29 of a 22-slide deck (``unknown_slide``).  The model is
    called once more with A's answer and the exact problem; B (replace the last
    slide with two) lands.  Only B's message is said, once, on each surface, and
    A's message is nowhere.

    Sabotage: no retry -> one call and a refusal; retry with the payload
    unchanged -> the stub answers A again; say A's message first -> it shows."""
    prior, before = _seeded(graph_env, range(22))
    first = _ops_out([_replace(29, _content("X"))], message=A_MSG)
    last_a, last_b = _content("LAST-A"), _content("LAST-B")
    second = _ops_out([_replace(21, last_a, last_b)], message=B_MSG)
    answers = _Answers(first, second)

    t = _turn(graph_env, answers)

    problems = _assert_retried_with(answers, graph_env, first)
    assert problems == [_unknown(29)]
    assert problems[0]["code"] == "unknown_slide"
    retry = answers.seen[1]["rejected_edit"]
    assert _json(retry["your_previous_answer"]["operations"]) == (
        first.model_dump(mode="json")["operations"]
    )

    old = list(prior.slides)
    composed = _canonical(prior, old[:21] + [_spec_from(last_a), _spec_from(last_b)])
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["architect_message"] == B_MSG
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == [21, 22]
    assert t.updates["deck_spec"] == composed
    assert _persisted_spec(graph_env) == composed
    _assert_laid_out(graph_env, before, [_mk(i) for i in range(22)] + ["PENDING"])

    assert t.assistant == [B_MSG]
    assert len(t.rows) == 1
    _assert_plain_row(t.rows[0], B_MSG)
    _assert_nowhere(graph_env, t, A_MSG)
    assert nodes._conversation(graph_env.session_id) == [
        {"role": "assistant", "content": B_MSG}
    ], "a turn that landed leaves no system note"


# ---------------------------------------------------------------------------
# 2. Two bad answers: refused with the SECOND answer's problems
# ---------------------------------------------------------------------------


def test_two_bad_answers_refuse_with_second_problems(graph_env):
    """A names position 29, B names position 25; both are refused by the planner.
    The turn degrades ``edit_operations_rejected`` with B's problem ("slide 26"), not
    A's ("slide 30"), and nothing is written.  Neither model message is said."""
    _seeded(graph_env, range(22))
    snapshot = _db_state(graph_env)
    first = _ops_out([_replace(29, _content("X"))], message=A_MSG)
    second = _ops_out([_delete(25)], message=B_MSG)
    answers = _Answers(first, second)

    t = _turn(graph_env, answers)

    assert _assert_retried_with(answers, graph_env, first) == [_unknown(29)]
    sentence = REJECTED_PREFIX + "there is no slide 26 — the deck has 22 slides."
    refusal = _assert_only_refusal(graph_env, t, "edit_operations_rejected", sentence)
    assert "slide 30" not in t.updates["architect_message"]
    assert t.updates["error_state"]["message"] == _unknown(25)["detail"]
    assert refusal["problems"] == [_unknown(25)]
    _assert_nowhere(graph_env, t, A_MSG, B_MSG)
    assert _db_state(graph_env) == snapshot


# ---------------------------------------------------------------------------
# 3. The retry may answer with another intent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["discuss", "confirm_design_contract"])
def test_retry_answer_can_be_discuss(graph_env, case):
    """B is handled from the top: a ``discuss`` question is said straight away and
    ends the turn, with nothing written and no error.  ``confirm_design_contract``:
    the §L4 augmentation runs on B too (the deck's slide style 5 would be dropped),
    on both surfaces.

    Sabotage: dispatch on A's intent after the retry -> an edit / a refusal; skip
    the augmentation on a second answer -> the bare question."""
    _seed_rows(graph_env, {p: _mk(p) for p in range(22)})
    prior = make_spec(tuple(range(22)), slide_style_id=5)
    _persist(graph_env, prior)
    snapshot = _db_state(graph_env)
    first = _ops_out([_replace(29, _content("X"))], message=A_MSG)
    if case == "discuss":
        question = "Which slide do you mean? The deck has 22 slides."
        second = ArchitectOutput(intent="discuss", message=question)
        said = question
    else:
        question = "Shall I switch this deck to the Acme design system?"
        second = ArchitectOutput(
            intent="confirm_design_contract",
            message=question,
            proposed_design_contract=DesignContractRef(
                design_system_id=7, template_id=3, slide_style_id=None
            ),
        )
        said = question + "\n\n" + STYLE_DROPPED
    answers = _Answers(first, second)

    t = _turn(graph_env, answers)

    assert _assert_retried_with(answers, graph_env, first) == [_unknown(29)]
    assert t.updates["architect_intent"] == case
    assert t.updates["architect_message"] == said
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] is None
    assert "deck_spec" not in t.updates
    assert t.assistant == [said]
    assert len(t.rows) == 1
    _assert_plain_row(t.rows[0], said)
    _assert_nowhere(graph_env, t, A_MSG)
    assert _db_state(graph_env) == snapshot


# ---------------------------------------------------------------------------
# 4. Today's alignment refusal retries too, and the operations answer lands
# ---------------------------------------------------------------------------


def test_alignment_refusal_on_old_path_retries(graph_env, monkeypatch):
    """The production shape (spec "Why"): "replace slide 5 of 16 with an overview and
    six stage slides" returned as a grown ``deck_spec``.  The alignment refuses it as
    ``ambiguous``; the retry is told so (``alignment_ambiguous``, no positions,
    the alignment's own detail) and answers with operations, which land.

    Sabotage: retry only operations problems -> one call and today's refusal."""
    prior, before = _seeded(graph_env, range(16))
    old = list(prior.slides)
    overview = old[4].model_copy(
        update={"purpose": "overview of the stages", "content_brief": "OVERVIEW brief"}
    )
    stages = [_new(f"STAGE-{i}") for i in range(6)]
    grown = _canonical(prior, old[:4] + [overview] + stages + old[5:])
    with pytest.raises(AlignmentRefused) as refused:
        align_slides(prior.slides, grown.slides)
    assert refused.value.code == "ambiguous", "precondition: the production refusal"
    first = _edit_out(grown, list(range(4, 11)), message=A_MSG)
    seven = [_content("OVERVIEW")] + [_content(f"STAGE-{i}") for i in range(6)]
    second = _ops_out([_replace(4, *seven)], message=B_MSG)
    answers = _Answers(first, second)

    t = _turn(graph_env, answers)

    problems = _assert_retried_with(answers, graph_env, first)
    assert problems == [
        {"code": "alignment_ambiguous", "positions": [], "detail": refused.value.detail}
    ]
    assert answers.seen[1]["rejected_edit"]["your_previous_answer"] == {
        "intent": "edit",
        "operations": None,
        "deck_changes": None,
        "target_positions": list(range(4, 11)),
    }

    composed = _canonical(prior, old[:4] + [_spec_from(c) for c in seven] + old[5:])
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assert t.updates["target_positions"] == list(range(4, 11))
    assert t.updates["deck_spec"] == composed
    assert _persisted_spec(graph_env) == composed
    _assert_laid_out(
        graph_env,
        before,
        [_mk(i) for i in range(5)] + ["PENDING"] * 6 + [_mk(i) for i in range(5, 16)],
    )
    assert t.assistant == [B_MSG]
    assert len(t.rows) == 1
    _assert_plain_row(t.rows[0], B_MSG)
    _assert_nowhere(graph_env, t, A_MSG)


# ---------------------------------------------------------------------------
# 5. What the model cannot fix is never retried
# ---------------------------------------------------------------------------


def _raise_from(error: Exception) -> Callable:
    def _raise(self, *args, **kwargs):
        raise error

    return _raise


@pytest.mark.parametrize(
    "case, code, sentence",
    [
        ("spec_positions_stale", "spec_positions_stale", SPEC_POSITIONS_STALE),
        ("ops-rows-changed", "insert_rows_changed", OPS_ROWS_CHANGED),
        ("ops-rows-failed", "insert_rows_failed", OPS_ROWS_FAILED),
        ("edit_without_spec", "edit_without_spec", EDIT_WITHOUT_SPEC),
        ("edit_without_revised_spec", "edit_without_revised_spec", EDIT_WITHOUT_REVISED_SPEC),
    ],
    ids=[
        "spec_positions_stale",
        "ops-rows-changed",
        "ops-rows-failed",
        "edit_without_spec",
        "edit_without_revised_spec",
    ],
)
def test_non_retryable_refusals_call_once(graph_env, monkeypatch, case, code, sentence):
    """``spec_positions_stale`` (the persisted spec no longer describes the rows),
    ``SlideRowsChangedError`` and any other error from the layout writer, and the two
    spec-less refusals: the model cannot fix any of them, so exactly ONE architect
    call, and only the refusal is said.  B would land if it were ever asked for.

    Sabotage: retry every degrade -> two calls and B's edit applied."""
    if case == "spec_positions_stale":
        _seed_rows(graph_env, {0: _mk(0), 1: _mk(1), 2: _mk(2)})
        _persist(graph_env, make_spec((0, 1, 2, 3)))
        first = _ops_out([_update(1, _content("U"))], message=A_MSG)
    elif case in ("ops-rows-changed", "ops-rows-failed"):
        _seeded(graph_env, (0, 1, 2, 3))
        error = (
            SlideRowsChangedError("the rows moved under the planner")
            if case == "ops-rows-changed"
            else RuntimeError("the database went away")
        )
        monkeypatch.setattr(SlideWriter, "apply_slide_layout", _raise_from(error))
        first = _ops_out([_delete(1)], message=A_MSG)
    elif case == "edit_without_spec":
        first = _ops_out([_update(0, _content("U"))], message=A_MSG)
    else:
        _seeded(graph_env, (0, 1, 2))
        first = _edit_out(None, [1], message=A_MSG)
    second = _ops_out([_update(1, _content("B"))], message=B_MSG)
    snapshot = _db_state(graph_env)
    answers = _Answers(first, second)

    t = _turn(graph_env, answers)

    assert _calls(graph_env) == 1, f"{code} must not be retried"
    assert len(answers.seen) == 1 and "rejected_edit" not in answers.seen[0]
    _assert_only_refusal(graph_env, t, code, sentence)
    _assert_nowhere(graph_env, t, A_MSG, B_MSG)
    assert _db_state(graph_env) == snapshot
    assert nodes.RETRYABLE_EDIT_CODES == frozenset(
        {
            "edit_operations_rejected",
            "invalid_slide_type_binding",
            "edit_insert_ambiguous",
            "edit_spec_moves_slides",
            "edit_spec_positions_changed",
        }
    )
    assert code not in nodes.RETRYABLE_EDIT_CODES


# ---------------------------------------------------------------------------
# 6. A build's message also waits for its checks
# ---------------------------------------------------------------------------


def test_build_message_said_only_after_checks(graph_env):
    """A build whose bindings fail on both answers (``slide_type`` with no index on
    an unpinned deck).  ``invalid_slide_type_binding`` is retryable, so the model is
    called twice; the only thing said is today's binding refusal, naming B's error
    (slide 2) and not A's (slide 1).  Neither "Building…" line is said.

    Sabotage: emit the build message before the binding check -> it shows."""
    snapshot = _db_state(graph_env)
    a_spec = make_spec((0, 1), slide_type="title")
    b_spec = a_spec.model_copy(
        update={
            "slides": [
                s.model_copy(update={"slide_type": None}) if s.position == 0 else s
                for s in a_spec.slides
            ]
        }
    )
    first = architect_build(a_spec, message=A_MSG)
    second = architect_build(b_spec, message=B_MSG)
    answers = _Answers(first, second)

    t = _turn(graph_env, answers)

    problems = _assert_retried_with(answers, graph_env, first)
    assert {p["code"] for p in problems} == {"invalid_slide_type_binding"}
    assert "; ".join(p["detail"] for p in problems) == "; ".join(
        [_half_bound_error(1), _half_bound_error(2)]
    )
    error = _half_bound_error(2)
    sentence = BINDING_PREFIX + error + ". Nothing has been changed."
    refusal = _assert_only_refusal(graph_env, t, "invalid_slide_type_binding", sentence)
    assert t.updates["error_state"]["message"] == error
    assert {p["code"] for p in refusal["problems"]} == {"invalid_slide_type_binding"}
    assert "; ".join(p["detail"] for p in refusal["problems"]) == error
    assert _half_bound_error(1) not in t.updates["architect_message"]
    _assert_nowhere(graph_env, t, A_MSG, B_MSG)
    assert _db_state(graph_env) == snapshot


# ---------------------------------------------------------------------------
# 7. The model's message lands after the rows and before the deck-level notice
# ---------------------------------------------------------------------------


def _log_writes(monkeypatch, log: List[tuple]) -> None:
    """Record the row writers and every transcript write into *log*, then run them."""
    for name in ("apply_slide_layout", "insert_pending_slides"):
        real = getattr(SlideWriter, name)

        def spy(self, *args, _real=real, _name=name, **kwargs):
            log.append(("rows", _name))
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(SlideWriter, name, spy)

    real_add = SessionManager.add_message
    signature = inspect.signature(real_add)

    def add_spy(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs).arguments
        log.append(("row", bound["role"], bound["content"]))
        return real_add(self, *args, **kwargs)

    monkeypatch.setattr(SessionManager, "add_message", add_spy)


def _first(log: Sequence[tuple], predicate) -> int:
    for index, entry in enumerate(log):
        if predicate(entry):
            return index
    raise AssertionError(f"not in the log: {log}")


@pytest.mark.parametrize("path", ["operations", "old-path-equal-length", "old-path-insert"])
def test_message_precedes_deck_level_notice(graph_env, monkeypatch, path):
    """A deck-level edit (a new audience).  The persisted assistant rows are exactly
    ``[model message, deck-level notice]``, in that order, and so are the emitted
    ``ASSISTANT`` events.  The model's message is said AFTER the rows are laid out
    (operations, or the old path's insert shift) and BEFORE the re-review calls the
    reviewer, so before ``classify_spec_change``.

    Sabotage: say the message after the re-review -> it follows the notice; say it
    before the layout (today) -> ``operations`` and ``old-path-insert`` go red."""
    prior, _ = _seeded(graph_env, (0, 1, 2))
    log: List[tuple] = []
    graph_env.skills.set(
        "build_reviewer",
        lambda payload: (log.append(("review", payload["position"])),
                         review_out(payload["position"]))[1],
    )
    message = "Retargeting the deck at the CFO."
    if path == "operations":
        out = _ops_out(
            [_delete(0), _insert(2, _content("CLOSE"))],
            DeckChanges(audience=NEW_AUDIENCE),
            message=message,
        )
        notice = (
            "The deck's brief changed, so I re-checked all 3 slide(s) against it. "
            "Rebuilding slide 3."
        )
        writes = True
    elif path == "old-path-equal-length":
        revised = prior.slides[1].model_copy(update={"content_brief": "REVISED brief"})
        spec = _spec_of(
            prior,
            [(0, prior.slides[0]), (1, revised), (2, prior.slides[2])],
            audience=NEW_AUDIENCE,
        )
        out = _edit_out(spec, [1], message=message)
        notice = (
            "The deck's brief changed, so I re-checked all 3 slide(s) against it. "
            "Rebuilding slide 2."
        )
        writes = False
    else:
        a, b, c = prior.slides
        spec = _spec_of(
            prior, [(0, a), (1, b), (2, c), (3, _new())], audience=NEW_AUDIENCE
        )
        out = _edit_out(spec, [3], message=message)
        notice = (
            "The deck's brief changed, so I re-checked all 4 slide(s) against it. "
            "Rebuilding slide 4."
        )
        writes = True
    _log_writes(monkeypatch, log)
    answers = _Answers(out)

    t = _turn(graph_env, answers, log=log)

    assert _calls(graph_env) == 1
    assert t.updates["architect_intent"] == "edit"
    assert t.updates["error_state"] is None
    assistant_rows = [m for m in t.rows if m["role"] == "assistant"]
    assert [(m["content"], m["message_type"]) for m in assistant_rows] == [
        (message, "llm_response"),
        (notice, "llm_response"),
    ]
    for row in assistant_rows:
        _assert_plain_row(row, row["content"])
    assert t.assistant == [message, notice]

    said_row = _first(log, lambda e: e[0] == "row" and e[2] == message)
    said_event = _first(
        log, lambda e: e[0] == "event" and e[1] == StreamEventType.ASSISTANT and e[2] == message
    )
    first_review = _first(log, lambda e: e[0] == "review")
    notice_row = _first(log, lambda e: e[0] == "row" and e[2] == notice)
    notice_event = _first(log, lambda e: e[0] == "event" and e[2] == notice)
    if writes:
        laid_out = _first(log, lambda e: e[0] == "rows")
        assert laid_out < said_row and laid_out < said_event, (
            f"the model's message was said before the rows were laid out: {log}"
        )
    assert max(said_row, said_event) < first_review, (
        f"the model's message must be said before the deck-level re-review: {log}"
    )
    assert first_review < min(notice_row, notice_event)


# ---------------------------------------------------------------------------
# 8. The refusal row carries why it was refused
# ---------------------------------------------------------------------------


def _ambiguous_three(prior):
    """``test_architect_insert_slide``'s ambiguous insert: a new slide next to a
    rewrite of its neighbour, on three slides."""
    a, b, c = prior.slides
    rewritten = b.model_copy(update={"content_brief": "REWRITTEN brief for b"})
    return _spec_of(prior, [(0, a), (1, rewritten), (2, _new()), (3, c)]), [1, 2]


def _swap_three(prior):
    a, b, c = prior.slides
    return _spec_of(prior, [(0, b), (1, a), (2, c)]), [0, 1]


@pytest.mark.parametrize(
    "case, code", [
        ("operations", "edit_operations_rejected"),
        ("ambiguous", "edit_insert_ambiguous"),
        ("moves", "edit_spec_moves_slides"),
        ("shrink", "edit_spec_positions_changed"),
    ],
)
def test_refusal_row_carries_metadata(graph_env, case, code):
    """The refusal is saved as an ``llm_response`` (the UI shows it as today) with
    ``metadata == {"architect_refusal": {"code": …, "problems": […]}}`` naming the
    SECOND answer's problems.  The non-operations refusals keep today's code and
    sentence; an alignment refusal's problem is ``alignment_<code>`` with the
    alignment's detail and no positions.  (The shrink refusal is today's
    position-set guard: retryable, but its problem shape is not pinned by the plan.)

    Sabotage: save the refusal without metadata -> red; key it otherwise -> red."""
    if case == "operations":
        _seeded(graph_env, range(22))
        first = _ops_out([_replace(29, _content("X"))], message=A_MSG)
        second = _ops_out([_delete(25)], message=B_MSG)
        sentence = REJECTED_PREFIX + "there is no slide 26 — the deck has 22 slides."
        expected: Optional[List[Dict]] = [_unknown(25)]
    else:
        prior, _ = _seeded(graph_env, (0, 1, 2))
        if case == "ambiguous":
            spec, targets = _ambiguous_three(prior)
        elif case == "moves":
            spec, targets = _swap_three(prior)
        else:
            spec, targets = make_spec((0, 1)), [1]
        first = _edit_out(spec, targets, message=A_MSG)
        second = _edit_out(spec, targets, message=B_MSG)
        sentence = REFUSAL_TEXT[code]
        expected = None
        if case in ("ambiguous", "moves"):
            with pytest.raises(AlignmentRefused) as refused:
                align_slides(prior.slides, spec.slides)
            expected = [
                {
                    "code": f"alignment_{refused.value.code}",
                    "positions": [],
                    "detail": refused.value.detail,
                }
            ]
    snapshot = _db_state(graph_env)
    answers = _Answers(first, second)

    t = _turn(graph_env, answers)

    # The refusal row first: what this test is about, whatever else is wrong.
    row = t.rows[-1]
    assert (row["role"], row["message_type"]) == ("assistant", "llm_response")
    assert isinstance(row["metadata"], dict) and "architect_refusal" in row["metadata"], (
        f"the refusal row carries no architect_refusal metadata: {row['metadata']!r}"
    )
    assert row["metadata"]["architect_refusal"]["code"] == code
    retried = _assert_retried_with(answers, graph_env, first)
    refusal = _assert_only_refusal(graph_env, t, code, sentence)
    if expected is not None:
        assert retried == (expected if case != "operations" else [_unknown(29)])
        assert row["metadata"] == {"architect_refusal": {"code": code, "problems": expected}}
        assert refusal["problems"] == expected
    _assert_nowhere(graph_env, t, A_MSG, B_MSG)
    assert _db_state(graph_env) == snapshot
    assert nodes.REFUSAL_METADATA_KEY == "architect_refusal"


# ---------------------------------------------------------------------------
# 9. The next turn reads the refusal as a refusal, and why
# ---------------------------------------------------------------------------


def test_conversation_replays_refusal_with_system_note(graph_env):
    """After a refused turn and a new user message, ``_conversation`` is exactly
    ``[user, assistant(refusal), system(note), user]``.  The note opens "The edit
    above was NOT applied; nothing in the deck changed. It was rejected because: "
    and names B's problems (their details, ``; ``-joined).  The next architect call
    is handed that same conversation.

    Both answers carry the same two bad deletes (only their messages differ), so
    the refusal's sentence does not depend on whether the retry happened.

    Sabotage: replay the refusal row as a plain assistant turn -> no note; append
    the note at the end -> it follows the new user message."""
    _seeded(graph_env, range(22))
    asked = "Delete slides 26 and 27."
    _user(graph_env, asked)
    bad = [_delete(25), _delete(26)]
    first = _ops_out(bad, message=A_MSG)
    second = _ops_out(bad, message=B_MSG)

    t = _turn(graph_env, _Answers(first, second), architect_message=asked)

    sentence = (
        REJECTED_PREFIX
        + "there is no slide 26 — the deck has 22 slides; "
        + "there is no slide 27 — the deck has 22 slides."
    )
    assert t.updates["architect_message"] == sentence
    again = "Try again, please."
    _user(graph_env, again)

    note = NOTE_PREFIX + _unknown(25)["detail"] + "; " + _unknown(26)["detail"] + "."
    expected = [
        {"role": "user", "content": asked},
        {"role": "assistant", "content": sentence},
        {"role": "system", "content": note},
        {"role": "user", "content": again},
    ]
    conversation = nodes._conversation(graph_env.session_id)
    assert [turn["role"] for turn in conversation] == [
        "user", "assistant", "system", "user"
    ], f"the refusal is not followed by a system note: {conversation}"
    assert conversation[2]["content"].startswith(NOTE_PREFIX)
    assert conversation == expected
    _assert_only_refusal(graph_env, t, "edit_operations_rejected", sentence)

    graph_env.skills.calls.clear()
    nxt = _Answers(ArchitectOutput(intent="discuss", message="Which slide did you mean?"))
    _turn(graph_env, nxt, architect_message=again)
    assert len(nxt.seen) == 1
    assert nxt.seen[0]["conversation"] == expected, (
        "the architect's next call does not see why its plan was rejected"
    )


# ---------------------------------------------------------------------------
# 10. Rows without the key replay exactly as today
# ---------------------------------------------------------------------------


def test_conversation_unchanged_for_plain_rows(graph_env):
    """Regression guard (green before Task 5): user and assistant rows of every
    replayable type, an assistant row carrying unrelated metadata, an ``info``
    advisory (skipped) and an empty row (skipped) replay exactly as today, with no
    system note anywhere."""
    manager = get_session_manager()
    sid = graph_env.session_id
    manager.add_message(sid, role="user", content="u1", message_type="user_query")
    manager.add_message(sid, role="assistant", content="a1", message_type="llm_response")
    manager.add_message(
        sid,
        role="assistant",
        content="a2",
        message_type="llm_response",
        metadata={"node": "architect", "intent": "discuss"},
    )
    manager.add_message(sid, role="assistant", content="advisory", message_type="info")
    manager.add_message(
        sid, role="assistant", content="which one?", message_type="clarification"
    )
    manager.add_message(sid, role="user", content="u2", message_type="chat")
    manager.add_message(sid, role="user", content="u3", message_type="user_input")
    manager.add_message(sid, role="assistant", content="", message_type="llm_response")

    assert nodes._conversation(sid) == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "assistant", "content": "a2"},
        {"role": "assistant", "content": "which one?"},
        {"role": "user", "content": "u2"},
        {"role": "user", "content": "u3"},
    ]


# ---------------------------------------------------------------------------
# 11. C11: the operations path's write refusals do not say "added the slide"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, error, code, sentence",
    [
        ("operations", SlideRowsChangedError("moved"), "insert_rows_changed", OPS_ROWS_CHANGED),
        ("operations", RuntimeError("gone"), "insert_rows_failed", OPS_ROWS_FAILED),
        (
            "old-insert",
            SlideRowsChangedError("moved"),
            "insert_rows_changed",
            REFUSAL_TEXT["insert_rows_changed"],
        ),
        (
            "old-insert",
            RuntimeError("gone"),
            "insert_rows_failed",
            REFUSAL_TEXT["insert_rows_failed"],
        ),
    ],
    ids=["ops-rows-changed", "ops-rows-failed", "old-rows-changed", "old-rows-failed"],
)
def test_ops_path_write_refusals_use_edit_neutral_wording(
    graph_env, monkeypatch, path, error, code, sentence
):
    """C11: on the operations path a delete or a move can fail to land, so its
    row-write refusals are edit-neutral ("I have not made that edit"); the codes stay.
    The old alignment/insert path keeps today's "…have not added the slide…" /
    "I could not add the slide…" sentences byte for byte.  Neither retries, and only
    the refusal is said.

    Sabotage: reuse the insert sentences on the operations path -> the ops rows;
    change the shared dicts -> the old-insert rows."""
    prior, _ = _seeded(graph_env, (0, 1, 2))
    if path == "operations":
        monkeypatch.setattr(SlideWriter, "apply_slide_layout", _raise_from(error))
        first = _ops_out([_delete(1)], message=A_MSG)
    else:
        monkeypatch.setattr(SlideWriter, "insert_pending_slides", _raise_from(error))
        a, b, c = prior.slides
        first = _edit_out(
            _spec_of(prior, [(0, a), (1, b), (2, _new()), (3, c)]), [2], message=A_MSG
        )
    snapshot = _db_state(graph_env)
    answers = _Answers(first)

    t = _turn(graph_env, answers)

    assert _calls(graph_env) == 1
    _assert_only_refusal(graph_env, t, code, sentence)
    if path == "operations":
        assert "added the slide" not in sentence and "add the slide" not in sentence
    else:
        assert "the slide" in sentence, "precondition: today's insert sentence"
    _assert_nowhere(graph_env, t, A_MSG)
    assert _db_state(graph_env) == snapshot


# ---------------------------------------------------------------------------
# 12. A retry call that raises is no new way to fail the turn (review C14)
# ---------------------------------------------------------------------------


class _RetryRaises(_Answers):
    """Answers the first call; the retry call raises *error* (after recording it)."""

    def __init__(self, first: Any, error: BaseException) -> None:
        super().__init__(first)
        self.error = error

    def __call__(self, payload: Dict[str, Any]) -> Any:
        self.seen.append(copy.deepcopy(payload))
        if "rejected_edit" in payload:
            raise self.error
        return self.first


@pytest.mark.parametrize(
    "error",
    [RuntimeError("the serving endpoint went away"), ValueError("no parseable answer")],
    ids=["provider-failure", "unparseable-answer"],
)
def test_a_failed_retry_refuses_with_the_first_answers_refusal(graph_env, caplog, error):
    """The retry is a second chance, not a new way to fail: when the retry call
    raises, the turn is refused with the FIRST answer's refusal — its code, its
    sentence ("slide 30") and its row metadata — exactly as if no retry had been
    asked for, with nothing written.  A WARNING names the retry's failure.

    Sabotage: let the retry's exception propagate -> the turn raises; degrade
    without the first answer's problems -> the metadata differs."""
    _seeded(graph_env, range(22))
    snapshot = _db_state(graph_env)
    first = _ops_out([_replace(29, _content("X"))], message=A_MSG)
    answers = _RetryRaises(first, error)

    with caplog.at_level("WARNING", logger="src.services.graph.nodes"):
        t = _turn(graph_env, answers)

    assert _assert_retried_with(answers, graph_env, first) == [_unknown(29)]
    sentence = REJECTED_PREFIX + "there is no slide 30 — the deck has 22 slides."
    refusal = _assert_only_refusal(graph_env, t, "edit_operations_rejected", sentence)
    assert t.updates["error_state"]["message"] == _unknown(29)["detail"]
    assert refusal == {"code": "edit_operations_rejected", "problems": [_unknown(29)]}
    _assert_nowhere(graph_env, t, A_MSG)
    assert _db_state(graph_env) == snapshot
    failures = [
        record
        for record in caplog.records
        if record.levelname == "WARNING"
        and record.exc_info
        and record.exc_info[1] is error
    ]
    assert len(failures) == 1, "the retry's failure must be logged once, as a WARNING"
    assert type(error).__name__ in failures[0].getMessage()


def test_a_persisted_runtime_failure_on_the_retry_still_fails_the_turn(graph_env):
    """The persisted-runtime family (the pinned release or its configuration is
    unavailable) fails the turn on the retry exactly as it does on any model call
    (``_raise_if_persisted_runtime_failure``): it is not something a refusal can
    stand in for.  Nothing is said or written.

    Sabotage: degrade on every exception from the retry -> no raise."""
    from src.services.persisted_graph_release import GraphReleaseNotFoundError

    _seeded(graph_env, range(22))
    snapshot = _db_state(graph_env)
    rows_before = len(graph_env.messages())
    first = _ops_out([_replace(29, _content("X"))], message=A_MSG)
    error = GraphReleaseNotFoundError("graph release 1 does not exist")
    graph_env.skills.set("architect", _RetryRaises(first, error))

    with pytest.raises(GraphReleaseNotFoundError):
        architect_node(graph_env.state())

    assert _calls(graph_env) == 2
    assert len(graph_env.messages()) == rows_before, "a failed turn says nothing"
    assert _db_state(graph_env) == snapshot


def test_a_failed_first_call_still_fails_the_turn(graph_env):
    """Only the RETRY degrades on a failure: a first call that raises fails the
    turn as it always has, since there is no refusal to fall back on.

    Sabotage: catch the first call's exception too -> no raise."""
    _seeded(graph_env, range(22))

    def _down(payload):
        raise RuntimeError("the serving endpoint went away")

    graph_env.skills.set("architect", _down)

    with pytest.raises(RuntimeError, match="serving endpoint"):
        architect_node(graph_env.state())

    assert _calls(graph_env) == 1


# ---------------------------------------------------------------------------
# 13. A describe-only turn never retries (review C15)
# ---------------------------------------------------------------------------


def test_a_describe_only_turn_never_retries(graph_env):
    """The arc-review sweeper's turn (``describe_only``) is addressed to nobody
    and builds nothing, so a refusal on it is not worth a second model call: a
    binding refusal (``slide_type`` with no index, retryable on a human's turn)
    makes exactly ONE architect call, and B — which would land — is never asked
    for.  The refusal stays out of the transcript as the turn's prose does.

    Sabotage: drop the describe-only condition from the retry rule -> two calls
    and B's re-description lands."""
    prior, _ = _seeded(graph_env, (0, 1, 2))
    snapshot = _db_state(graph_env)
    first = _edit_out(make_spec((0, 1, 2), slide_type="title"), [0], message=A_MSG)
    second = _edit_out(prior, [0], message=B_MSG)
    answers = _Answers(first, second)

    t = _turn(graph_env, answers, describe_only=scoped("turn-1", True))

    assert _calls(graph_env) == 1, "a describe-only turn must not be retried"
    assert len(answers.seen) == 1 and "rejected_edit" not in answers.seen[0]
    assert t.updates["architect_intent"] == "discuss"
    assert t.updates["error_state"]["code"] == "invalid_slide_type_binding"
    assert t.updates["target_positions"] is None
    assert "deck_spec" not in t.updates
    assert t.said == [], "a describe-only turn adds nothing to the transcript"
    _assert_nowhere(graph_env, t, A_MSG, B_MSG)
    assert _db_state(graph_env) == snapshot
