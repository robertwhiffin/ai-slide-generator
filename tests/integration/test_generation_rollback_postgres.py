"""Task 4 on real PostgreSQL: the rollback against the constraints SQLite does not have.

``test_first_generation_rollback_deletes_deck_row_on_postgres`` -- a first-generation
rollback deletes the deck row the turn created, and the turn's mutation evidence
(``shared_deck_mutation_event``) points at that row.  On PostgreSQL the foreign key
is ``ON DELETE SET NULL`` and the table carries the append-only trigger
(``src/core/database.py``, the event guard), which admits exactly one kind of
UPDATE: a reference nulled because its target row is gone.  So the delete must
succeed, every event must survive with ``root_deck_id`` NULL and every other column
unchanged, and the turn's ``deck_reviews`` row must go with the deck through its
``ON DELETE CASCADE``.  SQLite enforces none of these foreign keys, so the unit
suite cannot show any of it.

``test_edit_rollback_is_exact_on_postgres`` -- the edit restore on PostgreSQL types
(timestamps, UUID identities, JSON agent config) and its triggers (deck
collaboration identity immutable, events append-only): every table back as it was
at Enter, the same assertion the unit suite makes on SQLite.

The scenarios, writers and assertions are the unit suite's
(``tests/unit/test_generation_rollback.py``), run here on a throwaway PostgreSQL
database.  Self-skips when no PostgreSQL is reachable (``postgres_engine``).
"""

from __future__ import annotations

from typing import Iterator

import pytest

from src.core.database import get_db_session
from src.services.deck_review_store import compute_deck_digest, save_deck_review
from src.services.generation_fence import fence_turn_write
from src.services.graph.event_emitter import chat_request_id_var, set_event_emitter
from tests.unit.test_generation_rollback import (
    OWNER,
    SLIDES_BEFORE,
    SLIDES_BUILT,
    RollbackEnv,
    _assert_rolled_back_to_enter,
    _one,
    _rb,
    build_env,
    edit_turn,
    first_generation_turn,
    in_turn,
    press_enter,
    roll_back,
    seed_earlier_turn,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


@pytest.fixture
def pg_env(postgres_engine, monkeypatch) -> RollbackEnv:
    return build_env(postgres_engine, monkeypatch)


@pytest.mark.parametrize(
    "terminal_status, error_message, refuse",
    [
        pytest.param("cancelled", None, True, id="stop"),
        pytest.param("error", "Model call failed: 403", False, id="failure"),
    ],
)
def test_first_generation_rollback_deletes_deck_row_on_postgres(
    pg_env, terminal_status, error_message, refuse
):
    env = pg_env
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    before = env.tables()

    rid = press_enter(env, sid)
    first_generation_turn(env, sid, rid)
    deck_id = env.deck_row(sid)["id"]
    # The deck reviewer's write, as deck_reviewer_node makes it (fenced, same txn).
    with in_turn(rid):
        with get_db_session() as db:
            fence_turn_write(db)
            save_deck_review(db, deck_id, compute_deck_digest(SLIDES_BUILT), [], OWNER)
    at_turn_end = env.tables()
    pointing = [
        e for e in at_turn_end["shared_deck_mutation_event"] if e["root_deck_id"] == deck_id
    ]
    assert pointing, "no mutation evidence points at the deck; the test proves nothing"
    assert [r for r in at_turn_end["deck_reviews"] if r["deck_id"] == deck_id]

    result = roll_back(rid, terminal_status, error_message, refuse)

    assert result == _rb().RollbackResult.ROLLED_BACK
    after = env.tables()
    assert env.deck_row(sid) is None
    # Every event kept, the deck reference nulled by the foreign key, nothing else
    # about it changed (the append-only trigger admitted exactly that UPDATE).
    expected_events = [
        dict(e, root_deck_id=None) if e["root_deck_id"] == deck_id else e
        for e in at_turn_end["shared_deck_mutation_event"]
    ]
    assert after["shared_deck_mutation_event"] == expected_events
    # Everything else back as it was at Enter -- including deck_reviews, emptied by
    # the cascade.
    _assert_rolled_back_to_enter(
        env,
        before,
        dict(at_turn_end, shared_deck_mutation_event=expected_events),
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status=terminal_status,
        error_message=error_message,
        deck_existed=False,
    )
    assert after["deck_reviews"] == before["deck_reviews"] == []


def test_edit_rollback_is_exact_on_postgres(pg_env):
    env = pg_env
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    before = env.tables()

    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    at_turn_end = env.tables()
    assert env.slide_htmls(sid) != SLIDES_BEFORE

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK

    after = env.tables()
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="cancelled",
        error_message=None,
        deck_existed=True,
    )
    assert after["session_slides"] == before["session_slides"]
    assert _one(after["chat_requests"], request_id=rid)["rollback_outcome"] == "rolled_back"
