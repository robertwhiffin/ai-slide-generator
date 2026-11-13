"""Task 3a: a stopped turn's deck, deck-level and deck-review writes never land.

Once a turn's ``chat_requests`` row is terminal, every deck writer the graph uses
must refuse with ``TurnFencedError`` (the fence from Task 2), so the abandoned
graph thread that keeps running after a stop changes nothing.  The writers:

* ``SlideWriter.write_slide`` (and ``commit_placeholder``, which goes through it)
* ``SlideWriter.apply_slide_layout`` (and ``insert_pending_slides``, through it)
* ``SlideWriter.delete_slide``
* ``write_deck_level_columns``
* the deck-review save in ``deck_reviewer_node``

Each writer has a pair:

* ``..._refused_after_cancel`` -- the turn's request id is in the ``ContextVar``
  and its row is ``cancelled``: the writer raises ``TurnFencedError`` and EVERY row
  of EVERY table is byte-identical afterwards (whole-table snapshots, every column,
  not chosen keys).
* ``..._lands_while_live`` -- the row is ``running``: the write lands, AND the claim
  of the request row is the first write statement of the writer's OWN transaction
  (PLAN-CORRECTIONS P1).  A fence in a separate session, or after the first write,
  passes the refusal test and fails this one.

``test_writers_unfenced_outside_a_turn`` is the guard for every caller that is not
a turn (manual edits, the sweeper): no request id, no fence SQL, writes as today --
even when the session has a cancelled request lying around.

``TestAnAbandonedBranchStops`` pins the ``except TurnFencedError: raise`` audit
(PLAN-CORRECTIONS C8): writer call sites in ``nodes.py`` that sit inside a broad
``except Exception`` must let the refusal out, so an abandoned branch ends at its
first refused write instead of logging and starting more model calls.

``TestInvokeGraphCarriesTheRequestId`` pins C5: ``invoke_graph`` puts the request id
in ``config["configurable"]``, because LangGraph calls the checkpointer's
``put_writes`` for ``Send``-fanned tasks outside the task's context, where the
``ContextVar`` is None.  The checkpointer half is in ``test_checkpointer.py``.

Everything runs on a real SQLite schema (``conftest_graph``): only the model and the
brand resolvers are stubbed.
"""
from __future__ import annotations

import contextlib
import logging
import re
import uuid
from typing import Any, Dict, Iterator, List, Optional

import pytest
from sqlalchemy import event, inspect, select, update

from src.api.services.deck_level_writer import write_deck_level_columns
from src.api.services.slide_repository import SlideWriter, is_placeholder_record
from src.core.database import Base
from src.database.models.session import ChatRequest, UserSession
from src.domain.finding import DeckReviewOutput
from src.services.deck_review_store import compute_deck_digest
from src.services.generation_fence import TurnFencedError
from src.services.graph import builder as builder_module
from src.services.graph import nodes
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from src.services.graph.state import scoped
from src.services.shared_deck_attribution import DeckMutationContext, MutationActor
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest_graph import (  # noqa: F401 -- fixtures
    DEFAULT_STYLE,
    TEMPLATE_TOKEN_CSS,
    architect_build,
    builder_out,
    finding,
    fixer_out,
    graph_env,
    make_spec,
    review_out,
)

USER = "turn-author@example.com"
TURN = "turn-fence"

_THREE = [
    "<div class='slide'><h1>MK-ONE</h1></div>",
    "<div class='slide'><h1>MK-TWO</h1></div>",
    "<div class='slide'><h1>MK-THREE</h1></div>",
]

_WRITE_RE = re.compile(
    r"^\s*(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+[\"`]?(\w+)",
    re.IGNORECASE,
)
_CLAIM_RE = re.compile(
    r"^\s*UPDATE\s+chat_requests\s+SET\s+status\s*=\s*status\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    """Every test starts with no request id bound; the old value is put back after."""
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


@contextlib.contextmanager
def _in_turn(request_id: Optional[str]) -> Iterator[None]:
    """Run the block as the graph does: with *request_id* bound in the ContextVar."""
    token = chat_request_id_var.set(request_id)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)


def _owner(env) -> UserSession:
    db = env.factory()
    try:
        owner = (
            db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        )
        db.expunge(owner)
        return owner
    finally:
        db.close()


def _seed_request(env, status: str) -> str:
    rid = f"req-{uuid.uuid4().hex[:16]}"
    db = env.factory()
    try:
        db.add(ChatRequest(request_id=rid, session_id=_owner(env).id, status=status))
        db.commit()
    finally:
        db.close()
    return rid


def _set_status(env, rid: str, status: str) -> None:
    table = ChatRequest.__table__
    db = env.factory()
    try:
        db.execute(update(table).where(table.c.request_id == rid).values(status=status))
        db.commit()
    finally:
        db.close()


def _mutation(env, operation: str, object_type: str) -> DeckMutationContext:
    return DeckMutationContext(
        actor=MutationActor(env.session_id, _owner(env).graph_release_id),
        operation=operation,
        object_type=object_type,
    )


def _snapshot(engine) -> Dict[str, List[Dict[str, Any]]]:
    """Every row of every table, every column, in primary-key order.

    Read on a connection of its own, only ever while no session is open (the
    in-memory engine is ``SingletonThreadPool``).
    """
    present = set(inspect(engine).get_table_names())
    out: Dict[str, List[Dict[str, Any]]] = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in present:
                continue
            statement = select(table).order_by(*table.primary_key.columns)
            out[table.name] = [dict(row) for row in conn.execute(statement).mappings()]
    return out


def _assert_unchanged(before, after) -> None:
    changed = sorted(name for name in before if before[name] != after.get(name))
    assert not changed, (
        f"tables changed although the turn was cancelled: {changed}; "
        + "; ".join(
            f"{name}: {len(before[name])} -> {len(after.get(name, []))} rows"
            for name in changed
        )
    )


@contextlib.contextmanager
def _transactions(engine) -> Iterator[List[List[str]]]:
    """Every statement sent to *engine*, grouped by the transaction it ran in."""
    done: List[List[str]] = []
    open_: Dict[int, List[str]] = {}

    def on_begin(conn):
        open_[id(conn)] = []

    def on_statement(conn, cursor, statement, parameters, context, executemany):
        open_.setdefault(id(conn), []).append(statement)

    def on_end(conn):
        statements = open_.pop(id(conn), None)
        if statements is not None:
            done.append(statements)

    listeners = (
        ("begin", on_begin),
        ("before_cursor_execute", on_statement),
        ("commit", on_end),
        ("rollback", on_end),
    )
    for name, fn in listeners:
        event.listen(engine, name, fn)
    try:
        yield done
    finally:
        for name, fn in listeners:
            event.remove(engine, name, fn)


def _writes(statements: List[str]) -> List[str]:
    return [s for s in statements if _WRITE_RE.match(s)]


def _assert_claim_opens_the_write(transactions: List[List[str]], table: str) -> None:
    """The request-row claim is the FIRST write in each transaction writing *table*."""
    writing = [
        t for t in transactions
        if any(_WRITE_RE.match(s).group(1).lower() == table for s in _writes(t))
    ]
    assert writing, f"no transaction wrote {table}: the write did not land"
    for statements in writing:
        first = _writes(statements)[0]
        assert _CLAIM_RE.match(first), (
            f"the transaction writing {table} did not open with the request-row "
            f"claim; its first write was: {first.strip()[:120]!r}"
        )


def _expected_rows(env):
    return [(r.slide_id, compute_slide_hash(r.html or "")) for r in env.rows()]


def _branch_payload(env, position: int = 0) -> Dict[str, Any]:
    """A slide-pipeline payload of the shape ``build_branch_payload`` produces."""
    spec = make_spec((position,))
    slide_spec = spec.slide_at(position)
    return {
        "session_id": env.session_id,
        "graph_release_id": _owner(env).graph_release_id,
        "turn_id": TURN,
        "root_session_id": env.session_id,
        "actor_session_id": env.session_id,
        "initiated_by": USER,
        "position": position,
        "slide_spec": slide_spec.model_dump(),
        "assumes": slide_spec.assumes,
        "hands_off": slide_spec.hands_off,
        "design_contract": spec.design_contract.model_dump(),
        "resolved_data": spec.resolved_data.model_dump(),
        "section_html": "<section class='slide'></section>",
        "section_css": TEMPLATE_TOKEN_CSS,
        "resolved_style": DEFAULT_STYLE,
        "design_system_active": False,
    }


def _reviewer_state(env) -> Dict[str, Any]:
    return env.state(
        turn_id=TURN,
        graph_release_id=_owner(env).graph_release_id,
        initiated_by=USER,
        root_session_id=env.session_id,
        actor_session_id=env.session_id,
    )


# -- the writers, each called the way the graph calls it ----------------------


def _write_slide(env) -> None:
    SlideWriter().write_slide(
        env.session_id,
        0,
        "<div class='slide'><h1>MK-REWRITTEN</h1></div>",
        scripts="",
        modified_by=USER,
        mutation=_mutation(env, "write_slide", "slide"),
    )


def _commit_placeholder(env) -> None:
    SlideWriter().commit_placeholder(
        env.session_id, 1, error_message="Builder", mutation=_mutation(env, "write_slide", "slide")
    )


def _apply_slide_layout(env) -> None:
    SlideWriter().apply_slide_layout(
        env.session_id,
        [2, 0, 1],
        deck_spec=make_spec((0, 1, 2)).to_json(),
        expected_rows=_expected_rows(env),
        created_by=USER,
        mutation=_mutation(env, "reorder_slides", "deck"),
    )


def _insert_pending_slides(env) -> None:
    rows = _expected_rows(env)
    SlideWriter().insert_pending_slides(
        env.session_id,
        [1],
        deck_spec=make_spec(tuple(range(len(rows) + 1))).to_json(),
        expected_rows=rows,
        created_by=USER,
        mutation=_mutation(env, "insert_slide", "deck"),
    )


def _delete_slide(env) -> None:
    SlideWriter().delete_slide(
        env.session_id, 2, mutation=_mutation(env, "delete_slide", "slide")
    )


def _write_deck_level(env) -> None:
    write_deck_level_columns(
        env.session_id,
        title="MK-FENCED-TITLE",
        css=".mk-fenced { color: red; }",
        slide_count=7,
        modified_by=USER,
        mutation=_mutation(env, "write_deck_level", "deck"),
    )


#: (writer, the table its write lands in, a check that it landed)
_WRITERS = {
    "write_slide": (
        _write_slide,
        "session_slides",
        lambda env: env.rows()[0].html == "<div class='slide'><h1>MK-REWRITTEN</h1></div>",
    ),
    "commit_placeholder": (
        _commit_placeholder,
        "session_slides",
        lambda env: is_placeholder_record(
            SlideWriter().get_slide(env.session_id, 1)["verification_record"]
        ),
    ),
    "apply_slide_layout": (
        _apply_slide_layout,
        "session_slides",
        lambda env: [r.html for r in env.rows()] == [_THREE[2], _THREE[0], _THREE[1]],
    ),
    "insert_pending_slides": (
        _insert_pending_slides,
        "session_slides",
        lambda env: len(env.rows()) == 4 and _THREE[0] == env.rows()[0].html
        and _THREE[1] == env.rows()[2].html,
    ),
    "delete_slide": (
        _delete_slide,
        "session_slides",
        lambda env: [r.html for r in env.rows()] == _THREE[:2],
    ),
    "write_deck_level_columns": (
        _write_deck_level,
        "session_slide_decks",
        lambda env: (env.deck_row().title, env.deck_row().slide_count, env.deck_row().css)
        == ("MK-FENCED-TITLE", 7, ".mk-fenced { color: red; }"),
    ),
}


# ---------------------------------------------------------------------------
# The writers, one pair each
# ---------------------------------------------------------------------------


def _refused_after_cancel(env, writer: str) -> None:
    """ContextVar -> a ``cancelled`` request: TurnFencedError, every table unchanged."""
    env.seed_slides(list(_THREE))
    rid = _seed_request(env, "cancelled")
    write, _table, _landed = _WRITERS[writer]
    before = _snapshot(env.engine)

    with _in_turn(rid):
        with pytest.raises(TurnFencedError) as excinfo:
            write(env)

    assert excinfo.value.request_id == rid
    _assert_unchanged(before, _snapshot(env.engine))


def _lands_while_live(env, writer: str) -> None:
    """ContextVar -> a ``running`` request: the write lands, the claim opens its txn."""
    env.seed_slides(list(_THREE))
    rid = _seed_request(env, "running")
    write, table, landed = _WRITERS[writer]
    requests_before = _snapshot(env.engine)["chat_requests"]

    with _in_turn(rid), _transactions(env.engine) as transactions:
        write(env)

    assert landed(env), f"{writer} did not land while the turn was live"
    _assert_claim_opens_the_write(transactions, table)
    # The claim is a no-op UPDATE: the request row itself is untouched.
    assert _snapshot(env.engine)["chat_requests"] == requests_before


def test_write_slide_refused_after_cancel(graph_env):
    _refused_after_cancel(graph_env, "write_slide")


def test_write_slide_lands_while_live(graph_env):
    _lands_while_live(graph_env, "write_slide")


def test_commit_placeholder_refused_after_cancel(graph_env):
    _refused_after_cancel(graph_env, "commit_placeholder")


def test_commit_placeholder_lands_while_live(graph_env):
    _lands_while_live(graph_env, "commit_placeholder")


def test_apply_slide_layout_refused_after_cancel(graph_env):
    _refused_after_cancel(graph_env, "apply_slide_layout")


def test_apply_slide_layout_lands_while_live(graph_env):
    _lands_while_live(graph_env, "apply_slide_layout")


def test_insert_pending_slides_refused_after_cancel(graph_env):
    _refused_after_cancel(graph_env, "insert_pending_slides")


def test_insert_pending_slides_lands_while_live(graph_env):
    _lands_while_live(graph_env, "insert_pending_slides")


def test_delete_slide_refused_after_cancel(graph_env):
    _refused_after_cancel(graph_env, "delete_slide")


def test_delete_slide_lands_while_live(graph_env):
    _lands_while_live(graph_env, "delete_slide")


def test_write_deck_level_columns_refused_after_cancel(graph_env):
    _refused_after_cancel(graph_env, "write_deck_level_columns")


def test_write_deck_level_columns_lands_while_live(graph_env):
    _lands_while_live(graph_env, "write_deck_level_columns")


def test_deck_review_save_refused_after_cancel(graph_env):
    """Stop pressed during the deck review: its findings must not be persisted.

    The request is cancelled inside the ``deck_reviewer`` model call, so the
    deck-level write before it landed while live and the review save after it is
    the first write the stopped turn attempts.
    """
    env = graph_env
    env.seed_slides(list(_THREE))
    rid = _seed_request(env, "running")
    at_cancel: Dict[str, Any] = {}

    def reviewer(payload):
        _set_status(env, rid, "cancelled")
        at_cancel["tables"] = _snapshot(env.engine)
        return DeckReviewOutput(findings=[])

    env.skills.set("deck_reviewer", reviewer)

    with _in_turn(rid):
        with pytest.raises(TurnFencedError) as excinfo:
            nodes.deck_reviewer_node(_reviewer_state(env))

    assert "tables" in at_cancel, "the deck reviewer model was never called"
    assert excinfo.value.request_id == rid
    _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))


def test_deck_review_save_lands_while_live(graph_env):
    env = graph_env
    env.seed_slides(list(_THREE))
    rid = _seed_request(env, "running")
    env.skills.set("deck_reviewer", DeckReviewOutput(findings=[]))

    with _in_turn(rid), _transactions(env.engine) as transactions:
        nodes.deck_reviewer_node(_reviewer_state(env))

    reviews = _snapshot(env.engine)["deck_reviews"]
    assert [r["deck_digest"] for r in reviews] == [compute_deck_digest(list(_THREE))]
    _assert_claim_opens_the_write(transactions, "deck_reviews")


def test_writers_unfenced_outside_a_turn(graph_env):
    """No request id: every writer works as today and no fence SQL is issued.

    A cancelled request of this session is present, as after a stop, so a fence
    that keyed on "this session has a stopped turn" rather than on the turn's own
    id would refuse the manual edit that follows it.
    """
    env = graph_env
    env.seed_slides(list(_THREE))
    _seed_request(env, "cancelled")
    env.skills.set("deck_reviewer", DeckReviewOutput(findings=[]))

    with _transactions(env.engine) as transactions:
        _write_slide(env)
        assert env.rows()[0].html == "<div class='slide'><h1>MK-REWRITTEN</h1></div>"
        _commit_placeholder(env)
        assert is_placeholder_record(
            SlideWriter().get_slide(env.session_id, 1)["verification_record"]
        )
        _apply_slide_layout(env)
        assert len(env.rows()) == 3
        _insert_pending_slides(env)
        assert len(env.rows()) == 4
        SlideWriter().delete_slide(
            env.session_id, 3, mutation=_mutation(env, "delete_slide", "slide")
        )
        assert len(env.rows()) == 3
        _write_deck_level(env)
        assert env.deck_row().title == "MK-FENCED-TITLE"
        nodes.deck_reviewer_node(_reviewer_state(env))
        assert len(_snapshot(env.engine)["deck_reviews"]) == 1

    assert transactions, "no statement was captured: the capture itself is broken"
    claims = [
        s.strip()[:100]
        for t in transactions
        for s in _writes(t)
        if _WRITE_RE.match(s).group(1).lower() == "chat_requests"
    ]
    assert claims == [], f"a writer outside a turn issued fence SQL: {claims}"


# ---------------------------------------------------------------------------
# The except-TurnFencedError audit: an abandoned branch ends at its first refusal
# ---------------------------------------------------------------------------


class TestAnAbandonedBranchStops:
    def test_abandoned_pipeline_stops_at_first_refused_write(self, graph_env):
        """Stop pressed while slide 1 builds: no reviewer call may start after.

        ``_write_draft_row`` catches every exception and the pipeline goes on to
        ``build_reviewer_node``, a model call (``nodes.py:7126`` -> ``:7217``).  The
        refused draft write must instead end the branch.  The request is cancelled
        inside the builder's model call, so the draft is the first write after it.
        """
        env = graph_env
        rid = _seed_request(env, "running")
        at_cancel: Dict[str, Any] = {}

        def builder(payload):
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)
            return builder_out(payload)

        env.skills.set("builder", builder)
        env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

        raised: Optional[BaseException] = None
        with _in_turn(rid):
            try:
                nodes.slide_pipeline_node(_branch_payload(env, 0))
            except Exception as exc:  # noqa: BLE001 - asserted below
                raised = exc

        assert "tables" in at_cancel, "the builder model was never called"
        assert [c["name"] for c in env.skills.calls] == ["builder"], (
            "a model call started in the branch after its draft write was refused"
        )
        assert isinstance(raised, TurnFencedError), (
            f"the branch did not end at the refused write; it raised {raised!r}"
        )
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    def test_abandoned_branch_stops_at_a_refused_placeholder(self, graph_env):
        """A builder failing after the stop: the refused placeholder ends the branch.

        ``_placehold_failed_position`` catches every exception from
        ``commit_placeholder`` and returns False (``nodes.py:1983``), which leaves
        the position for the foreman and the turn carries on to deck review.
        """
        env = graph_env
        rid = _seed_request(env, "running")
        at_cancel: Dict[str, Any] = {}

        def builder(payload):
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)
            raise ValueError("the builder failed after the stop")

        env.skills.set("builder", builder)
        env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

        raised: Optional[BaseException] = None
        with _in_turn(rid):
            try:
                nodes.slide_pipeline_node(_branch_payload(env, 0))
            except Exception as exc:  # noqa: BLE001 - asserted below
                raised = exc

        assert "tables" in at_cancel, "the builder model was never called"
        assert isinstance(raised, TurnFencedError), (
            f"the refused placeholder did not end the branch; it raised {raised!r}"
        )
        assert [c["name"] for c in env.skills.calls] == ["builder"]
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    # -- Task 8 (D1): a stopped pipeline stops at its first check -----------
    #
    # Every write is fenced; the model calls that NO fenced write precedes are
    # preceded by ``raise_if_turn_ended``, and the broad catches around the
    # reviewed writes let the refusal out without an ERROR.  Each test cancels
    # the request inside one model call and pins the next call never starts.

    @staticmethod
    def _pipeline(env, rid: str, caplog) -> Optional[BaseException]:
        caplog.set_level(logging.INFO)
        caplog.clear()
        with _in_turn(rid):
            try:
                nodes.slide_pipeline_node(_branch_payload(env, 0))
            except Exception as exc:  # noqa: BLE001 - asserted by the caller
                return exc
        return None

    @staticmethod
    def _errors(caplog) -> List[str]:
        return [
            f"{r.name}: {r.getMessage()}" for r in caplog.records if r.levelno >= logging.ERROR
        ]

    @staticmethod
    def _cancelling(env, rid: str, at_cancel: Dict[str, Any], answer):
        def handler(payload):
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)
            return answer(payload)

        return handler

    @staticmethod
    def _flagged(payload):
        return review_out(
            payload["position"], [finding("overflow", slide_index=payload["position"])]
        )

    def test_abandoned_edit_stops_before_reviewing_a_slide_it_keeps(
        self, graph_env, caplog
    ):
        """Stop pressed while an edit rebuilds slide 1, which holds a real slide.

        No draft is written over a real slide, so no fenced write stood between
        the builder's answer and the build reviewer's model call
        (``_write_draft_row``'s early return): the abandoned edit paid for the
        review and then logged a false "Build review failed" ERROR.
        """
        env = graph_env
        env.seed_slides(list(_THREE))
        rid = _seed_request(env, "running")
        at_cancel: Dict[str, Any] = {}
        env.skills.set("builder", self._cancelling(env, rid, at_cancel, builder_out))
        env.skills.set("build_reviewer", lambda payload: review_out(payload["position"]))

        raised = self._pipeline(env, rid, caplog)

        assert "tables" in at_cancel, "the builder model was never called"
        assert [c["name"] for c in env.skills.calls] == ["builder"], (
            "a model call started after the stop, on a position that keeps its slide"
        )
        assert isinstance(raised, TurnFencedError), (
            f"the branch did not end at the check; it raised {raised!r}"
        )
        assert self._errors(caplog) == []
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    def test_refused_reviewed_write_ends_the_build_review_quietly(
        self, graph_env, caplog
    ):
        """Stop pressed during the build review: its refused row write ends the node.

        The write sits in ``build_reviewer_node``'s broad ``except``, which logged
        "Build review failed" at ERROR and tried to placehold the position before
        the placeholder's own refusal ended the branch.
        """
        env = graph_env
        rid = _seed_request(env, "running")
        at_cancel: Dict[str, Any] = {}
        env.skills.set("builder", builder_out)
        env.skills.set(
            "build_reviewer",
            self._cancelling(env, rid, at_cancel, lambda p: review_out(p["position"])),
        )

        raised = self._pipeline(env, rid, caplog)

        assert "tables" in at_cancel, "the build reviewer was never called"
        assert isinstance(raised, TurnFencedError), raised
        assert [c["name"] for c in env.skills.calls] == ["builder", "build_reviewer"]
        assert self._errors(caplog) == [], "a refused write was logged as a failed review"
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    def test_abandoned_pipeline_stops_before_the_fixer(self, graph_env, caplog):
        """Stop pressed during a review that opens a fix: the fixer never starts.

        A review that opens a fix writes no row, so nothing was fenced between it
        and the fixer's model call (and the wait for a fix slot can be long).
        """
        env = graph_env
        rid = _seed_request(env, "running")
        at_cancel: Dict[str, Any] = {}
        env.skills.set("builder", builder_out)
        env.skills.set("build_reviewer", self._cancelling(env, rid, at_cancel, self._flagged))
        env.skills.set("fixer", fixer_out)
        env.skills.set("fix_reviewer", lambda payload: review_out(payload["position"]))

        raised = self._pipeline(env, rid, caplog)

        assert "tables" in at_cancel, "the build reviewer was never called"
        assert [c["name"] for c in env.skills.calls] == ["builder", "build_reviewer"], (
            "a fix round's model call started after the stop"
        )
        assert isinstance(raised, TurnFencedError), raised
        assert self._errors(caplog) == []
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    def test_abandoned_pipeline_stops_before_the_fix_review(self, graph_env, caplog):
        """Stop pressed while the fixer runs: the fix reviewer never starts.

        The fixer writes no row either, so its answer went straight on to the fix
        reviewer's model call.
        """
        env = graph_env
        rid = _seed_request(env, "running")
        at_cancel: Dict[str, Any] = {}
        env.skills.set("builder", builder_out)
        env.skills.set("build_reviewer", self._flagged)
        env.skills.set("fixer", self._cancelling(env, rid, at_cancel, fixer_out))
        env.skills.set("fix_reviewer", lambda payload: review_out(payload["position"]))

        raised = self._pipeline(env, rid, caplog)

        assert "tables" in at_cancel, "the fixer was never called"
        assert [c["name"] for c in env.skills.calls] == [
            "builder", "build_reviewer", "fixer",
        ], "the fix reviewer's model call started after the stop"
        assert isinstance(raised, TurnFencedError), raised
        assert self._errors(caplog) == []
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    def test_refused_fix_review_write_ends_the_fix_quietly(self, graph_env, caplog):
        """Stop pressed during the fix review: its refused row write ends the node.

        The write sits in ``fix_reviewer_node``'s broad ``except``, which logged
        "Fix review could not deliver a row" at ERROR and tried to placehold.
        """
        env = graph_env
        rid = _seed_request(env, "running")
        at_cancel: Dict[str, Any] = {}
        env.skills.set("builder", builder_out)
        env.skills.set("build_reviewer", self._flagged)
        env.skills.set("fixer", fixer_out)
        env.skills.set(
            "fix_reviewer",
            self._cancelling(env, rid, at_cancel, lambda p: review_out(p["position"])),
        )

        raised = self._pipeline(env, rid, caplog)

        assert "tables" in at_cancel, "the fix reviewer was never called"
        assert isinstance(raised, TurnFencedError), raised
        assert [c["name"] for c in env.skills.calls] == [
            "builder", "build_reviewer", "fixer", "fix_reviewer",
        ]
        assert self._errors(caplog) == [], "a refused write was logged as a failed fix review"
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    def test_refused_stale_fix_landing_ends_the_fixer(self, graph_env, caplog):
        """The fixer's stale in-flight reconcile lets a refused landing out.

        ``_reconcile_stale_fixes`` wraps each ``_land_original`` write in a broad
        ``except`` that logged ERROR and carried on.  Unreachable from the slide
        pipeline today; pinned because it is a fenced write in a broad catch.
        """
        env = graph_env
        env.seed_slides(list(_THREE))
        rid = _seed_request(env, "cancelled")
        state = {
            "turn_id": TURN,
            "session_id": env.session_id,
            "graph_release_id": _owner(env).graph_release_id,
            "initiated_by": USER,
            "fix_map": scoped(
                TURN,
                {
                    0: {
                        "original_html": "<div class='slide'><h1>MK-ORIGINAL</h1></div>",
                        "original_scripts": "",
                        "findings": [],
                        "payload": _branch_payload(env, 0),
                        "in_flight": True,
                    }
                },
            ),
        }
        before = _snapshot(env.engine)
        caplog.set_level(logging.INFO)

        raised: Optional[BaseException] = None
        updates: Any = None
        with _in_turn(rid):
            try:
                updates = nodes.fixer_node(state)
            except Exception as exc:  # noqa: BLE001 - asserted below
                raised = exc

        assert isinstance(raised, TurnFencedError), (
            f"the refused landing did not end the fixer; it returned {updates!r}"
        )
        assert env.skills.calls == []
        assert self._errors(caplog) == []
        _assert_unchanged(before, _snapshot(env.engine))

    def test_abandoned_rereview_stops_before_its_next_model_call(self, graph_env):
        """Stop pressed during the deck-level re-review: no further slide is scored.

        The pass makes one serial model call per committed slide and writes
        nothing, so no fence stopped it between them.
        """
        env = graph_env
        env.seed_slides(list(_THREE))
        rid = _seed_request(env, "running")
        at_cancel: Dict[str, Any] = {}
        env.skills.set(
            "build_reviewer",
            self._cancelling(env, rid, at_cancel, lambda p: review_out(p["position"])),
        )
        brand = {
            "resolved_style": DEFAULT_STYLE,
            "deterministic_css": TEMPLATE_TOKEN_CSS,
            "design_system_active": False,
            "template_layout_html": "",
        }

        raised: Optional[BaseException] = None
        with _in_turn(rid):
            try:
                nodes.rereview_committed_slides(
                    env.session_id,
                    make_spec((0, 1, 2)),
                    brand,
                    _owner(env).graph_release_id,
                    env.session_id,
                    env.session_id,
                )
            except Exception as exc:  # noqa: BLE001 - asserted below
                raised = exc

        assert "tables" in at_cancel, "the re-review never called the model"
        assert len(env.skills.calls_for("build_reviewer")) == 1, (
            "the re-review scored another slide after the stop"
        )
        assert isinstance(raised, TurnFencedError), raised
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))

    def test_abandoned_deck_review_stops_at_its_refused_deck_level_write(
        self, graph_env
    ):
        """After a stop, the deck reviewer's model call must not start.

        Its deck-level write sits in a broad ``except`` (``nodes.py:7519``) that
        surfaces a notice and goes on to the ``deck_reviewer`` model call.
        """
        env = graph_env
        env.seed_slides(list(_THREE))
        rid = _seed_request(env, "cancelled")
        env.skills.set("deck_reviewer", DeckReviewOutput(findings=[]))
        before = _snapshot(env.engine)

        raised: Optional[BaseException] = None
        with _in_turn(rid):
            try:
                nodes.deck_reviewer_node(_reviewer_state(env))
            except Exception as exc:  # noqa: BLE001 - asserted below
                raised = exc

        assert env.skills.calls_for("deck_reviewer") == [], (
            "the deck reviewer's model call started after its deck-level write "
            "was refused"
        )
        assert isinstance(raised, TurnFencedError), (
            f"the refused deck-level write did not end the node; it raised {raised!r}"
        )
        _assert_unchanged(before, _snapshot(env.engine))

    def test_abandoned_architect_stops_at_its_refused_pre_fan_out_write(
        self, graph_env
    ):
        """Stop pressed while the architect plans: nothing is dispatched after.

        The pre-fan-out deck-level write sat in a broad ``except Exception`` that
        recorded ``deck_level_write_failed`` and returned the build intent, so the
        router sent the turn to the foreman and a batch of builders started.  The
        refused write must end the node instead; the only model call is the
        architect's own.
        """
        env = graph_env
        rid = _seed_request(env, "running")
        at_cancel: Dict[str, Any] = {}

        def architect(payload):
            _set_status(env, rid, "cancelled")
            at_cancel["tables"] = _snapshot(env.engine)
            return architect_build(make_spec((0, 1)))

        env.skills.set("architect", architect)
        env.skills.set("builder", lambda payload: builder_out(payload))

        raised: Optional[BaseException] = None
        updates: Any = None
        with _in_turn(rid):
            try:
                updates = nodes.architect_node(env.state())
            except Exception as exc:  # noqa: BLE001 - asserted below
                raised = exc

        assert "tables" in at_cancel, "the architect model was never called"
        assert isinstance(raised, TurnFencedError), (
            f"the refused pre-fan-out write did not end the node; it raised "
            f"{raised!r} and returned {updates!r}"
        )
        assert [c["name"] for c in env.skills.calls] == ["architect"]
        # EVERY table: the architect's own message (session_messages and the
        # session's last_activity) is refused as well, since Task 3b fenced
        # add_message.
        _assert_unchanged(at_cancel["tables"], _snapshot(env.engine))


# ---------------------------------------------------------------------------
# C5: the request id rides in the checkpointer's config
# ---------------------------------------------------------------------------


class _RecordingGraph:
    def __init__(self) -> None:
        self.configs: List[Dict[str, Any]] = []

    def invoke(self, state, config):
        self.configs.append(
            {**config, "configurable": dict(config.get("configurable") or {})}
        )
        return {}


class TestInvokeGraphCarriesTheRequestId:
    def test_invoke_graph_puts_the_request_id_in_configurable(self, monkeypatch):
        """``put_writes`` for a fanned task never sees the ContextVar; the config it
        is handed is the only carrier that reaches it (PLAN-CORRECTIONS C5)."""
        fake = _RecordingGraph()
        monkeypatch.setattr(builder_module, "_compiled_graph", fake)
        monkeypatch.setattr(builder_module, "get_session_local", lambda: object())

        def turn(request_id):
            builder_module.invoke_graph(
                "sess-c5",
                {"architect_message": "build"},
                request_id=request_id,
                principal=USER,
                pin_loader=lambda factory, session_id: 1,
                root_loader=lambda factory, session_id: session_id,
            )

        turn("req-c5-first")
        turn(None)

        first, second = (c["configurable"] for c in fake.configs)
        assert first.get("thread_id") == "sess-c5"
        assert first.get("chat_request_id") == "req-c5-first", (
            f"invoke_graph did not hand the request id to the checkpointer: {first}"
        )
        assert second.get("thread_id") == "sess-c5"
        assert second.get("chat_request_id") is None, (
            "a turn with no request carried an earlier turn's id"
        )
