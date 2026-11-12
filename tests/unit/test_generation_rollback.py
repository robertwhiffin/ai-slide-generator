"""Task 4: the generation snapshot and the all-or-nothing rollback.

A stopped, failed, timed-out or interrupted Agent-deck generation must leave the
deck, the Spec, the chat and the session fields exactly as they were when Enter
was pressed, and must never roll back another person's intentional work.  The
module under test is ``src.services.generation_rollback``:

* ``take_generation_snapshot(db, *, request_id, session_id)`` -- in the caller's
  transaction, no commit.
* ``has_generation_snapshot(request_id)`` / ``has_pending_restore(session_id)`` /
  ``discard_generation_snapshot(db, request_id)``.
* ``seal_generation(request_id) -> bool`` -- the commit point of a turn.
* ``roll_back_generation(request_id, *, terminal_status, error_message,
  refuse_on_foreign_change) -> RollbackResult``.

Plus the deck-cache fix in ``ChatService._get_or_load_deck``: a CONFIRMED "no deck
row" drops another process's cached deck (a first-generation rollback deletes the
row), while a database error still serves the cache as today.

How the tests are built
-----------------------
* **Real writers only.**  Every row a turn changes is written by the code a real
  turn runs: ``add_user_message`` (submit: deck-mode lock and pin), ``add_message``,
  ``write_deck_level_columns``, ``SlideWriter.write_slide`` /
  ``apply_slide_layout``, the checkpointer's ``put`` / ``put_writes``,
  ``set_genie_one_conversation_id``, ``rename_session`` (the title thread) -- all
  under the turn's request id (``set_chat_request_id``, or the explicit
  ``request_id=`` / ``configurable`` key where the real caller passes one), with a
  live ``chat_requests`` row made by ``create_chat_request`` + ``start_chat_request``
  and a session lock taken by ``acquire_session_lock`` + ``bind_session_lock``, in
  the order ``submit_chat_async`` uses.  So the tests prove the rollback undoes
  what the real writers do, not what a fixture inserted.
* **"Exact" means the whole database.**  Every table is read in full (every row,
  every column) before Enter, at the end of the turn, and after the rollback.  A
  ``ROLLED_BACK`` result must put EVERY table back as it was at Enter, except
  (Global Constraints): ``session_slide_decks.version`` (old + bumps + 1) and
  ``updated_at``; ``user_sessions.last_activity``; the request's own
  ``chat_requests`` row (now terminal); and ``shared_deck_mutation_event``, which is
  append-only -- the turn's events stay, plus exactly one ``restore_version``/``deck``
  event when the deck existed before Enter, none on a first generation.
* The other results are checked the same way against the state just before the
  call: what may change is named, everything else must be byte-identical.
* File-backed SQLite (separate connections, like PostgreSQL): a restore-failure path
  that opened its second transaction while the first still held the database would
  hit ``database is locked`` here, as it would deadlock on the request row lock in
  PostgreSQL.

``src.services.generation_rollback`` is imported at CALL time (``_rb``), so the two
cache tests that do not need it (``test_db_error_keeps_cached_deck``,
``test_confirmed_missing_deck_row_drops_cached_deck``) run on their own behaviour
before the module exists.  The Postgres-gated cases (the deck-row delete with
mutation evidence pointing at it) are in
``tests/integration/test_generation_rollback_postgres.py``.
"""

from __future__ import annotations

import contextlib
import copy
import importlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Sequence

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import src.core.checkpointer as checkpointer_module
import src.database.models  # noqa: F401 -- registers every ORM model on Base
from src.api.routes.agent_config import _save_agent_config
from src.api.schemas.agent_config import (
    AgentConfig,
    GenieOneTool,
    GenieTool,
)
from src.api.services import chat_service as chat_service_module
from src.api.services.chat_service import ChatService
from src.api.services.deck_level_writer import write_deck_level_columns
from src.api.services.session_manager import get_session_manager
from src.api.services.slide_repository import SlideWriter
from src.core.checkpointer import get_checkpointer
from src.core.database import Base, _run_migrations, get_db_session
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    UserSession,
)
from src.services.generation_fence import (
    TurnFencedError,
    start_chat_request,
)
from src.services.graph.event_emitter import (
    chat_request_id_var,
    set_chat_request_id,
    set_event_emitter,
)
from src.utils.slide_hash import compute_slide_hash
from tests.unit.conftest_graph import make_spec

OWNER = "deck-owner@example.com"
CONTRIBUTOR = "contributor@example.com"
STRANGER = "someone-else@example.com"

#: Global Constraints copy, exact.
RESTORE_PENDING = (
    "This deck is still being restored after a failed generation. Try again in a minute."
)

#: The deck an earlier, completed turn left behind (the "edit" starting point).
SLIDES_BEFORE = [f"<div class='slide'><h1>MK-BEFORE-{c}</h1></div>" for c in "ABCD"]
#: What a first generation builds.
SLIDES_BUILT = [f"<div class='slide'><h1>MK-BUILT-{n}</h1></div>" for n in range(3)]
REWRITTEN = "<div class='slide'><h1>MK-REWRITTEN-BY-THE-TURN</h1></div>"
FOREIGN = "<div class='slide'><h1>MK-SOMEONE-ELSE-EDITED-THIS</h1></div>"

#: (terminal_status, error_message, refuse_on_foreign_change): a stop and a failure.
STOP_AND_FAILURE = [
    pytest.param("cancelled", None, True, id="stop"),
    pytest.param("error", "Model call failed: 403", False, id="failure"),
]

_SESSION_SLIDES_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+[\"`]?session_slides\b", re.I)


# ---------------------------------------------------------------------------
# The module under test, imported at call time
# ---------------------------------------------------------------------------


def _rb():
    """``src.services.generation_rollback``.

    Imported per call so the cache tests that do not depend on it still run (and
    fail on their own behaviour) while the module does not exist yet.
    """
    return importlib.import_module("src.services.generation_rollback")


# ---------------------------------------------------------------------------
# The environment: a real file-backed database behind every writer
# ---------------------------------------------------------------------------


class RollbackEnv:
    """A real database, every ``get_db_session`` and the checkpointer routed onto it."""

    def __init__(self, engine, factory, release_id: int, release_version: int):
        self.engine = engine
        self.factory = factory
        self.release_id = release_id
        self.release_version = release_version

    # -- sessions (not turn state, so created directly, as conftest_graph does) --

    def new_session(self, *, created_by: str, title: str, pinned: bool = False) -> str:
        session_id = f"rb-{uuid.uuid4().hex[:12]}"
        db = self.factory()
        try:
            db.add(
                UserSession(
                    session_id=session_id,
                    created_by=created_by,
                    title=title,
                    graph_release_id=self.release_id if pinned else None,
                )
            )
            db.commit()
        finally:
            db.close()
        return session_id

    def contributor(self, owner_sid: str, created_by: str = CONTRIBUTOR) -> str:
        """A contributor session on *owner_sid*'s deck, through the real path."""
        return get_session_manager().get_or_create_contributor_session(owner_sid, created_by)[
            "session_id"
        ]

    # -- reads --------------------------------------------------------------

    def tables(self) -> Dict[str, List[Dict[str, Any]]]:
        return _tables(self.engine)

    def pk(self, session_id: str) -> int:
        return _one(self.tables()["user_sessions"], session_id=session_id)["id"]

    def session_row(self, session_id: str) -> Dict[str, Any]:
        return _one(self.tables()["user_sessions"], session_id=session_id)

    def request_row(self, rid: str) -> Dict[str, Any]:
        return _one(self.tables()["chat_requests"], request_id=rid)

    def snapshot_rows(self, rid: str) -> List[Dict[str, Any]]:
        return [r for r in self.tables()["generation_snapshots"] if r["request_id"] == rid]

    def deck_row(self, owner_sid: str) -> Optional[Dict[str, Any]]:
        pk = self.pk(owner_sid)
        rows = [r for r in self.tables()["session_slide_decks"] if r["session_id"] == pk]
        return rows[0] if rows else None

    def slide_htmls(self, owner_sid: str) -> List[str]:
        pk = self.pk(owner_sid)
        rows = [r for r in self.tables()["session_slides"] if r["session_id"] == pk]
        return [r["html"] for r in sorted(rows, key=lambda r: r["position"])]


def _tables(engine) -> Dict[str, List[Dict[str, Any]]]:
    """Every row of every table, every column, in primary-key order."""
    present = set(inspect(engine).get_table_names())
    out: Dict[str, List[Dict[str, Any]]] = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in present:
                continue
            statement = select(table).order_by(*table.primary_key.columns)
            out[table.name] = [dict(row) for row in conn.execute(statement).mappings()]
    return out


def _one(rows: Sequence[Dict[str, Any]], **where: Any) -> Dict[str, Any]:
    matches = [r for r in rows if all(r.get(k) == v for k, v in where.items())]
    assert len(matches) == 1, f"expected exactly one row with {where}, found {len(matches)}"
    return matches[0]


def _without(row: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if k not in keys}


def build_env(engine, monkeypatch) -> RollbackEnv:
    """Route the app's session factory and the checkpointer onto *engine*.

    ``get_db_session`` resolves ``get_session_local`` at call time, so one patch
    covers every module that imported ``get_db_session`` by name (the writers, the
    fence, the module under test).  The checkpointer imported ``get_session_local``
    itself.  Shared with the Postgres-gated file.
    """
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr("src.core.database.get_session_local", lambda: factory)
    monkeypatch.setattr(checkpointer_module, "get_session_local", lambda: factory)
    monkeypatch.setattr(checkpointer_module, "_checkpointer", None)
    # This process's ChatService (the rollback invalidates its cache) starts fresh.
    monkeypatch.setattr(chat_service_module, "_chat_service_instance", None)
    # SCIM display-name resolution runs on every get_slide_deck read; a real
    # WorkspaceClient here retries and hangs (conftest_graph does the same).
    monkeypatch.setattr("src.services.identity_provider.resolve_display_names", lambda emails: {})

    db = factory()
    try:
        effective = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
        release = GraphRelease(
            version_number=3,
            release_note="rollback fixture release",
            published_by="test",
            published_at=effective,
            effective_from=effective,
            effective_to=None,
        )
        db.add(release)
        db.commit()
        release_id, release_version = release.id, release.version_number
    finally:
        db.close()
    return RollbackEnv(engine, factory, release_id, release_version)


@pytest.fixture
def env(monkeypatch, tmp_path) -> Iterator[RollbackEnv]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/rollback.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    yield build_env(engine, monkeypatch)
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_request_id_in_context() -> Iterator[None]:
    """Every test starts with no request id bound; the old value is put back after."""
    token = chat_request_id_var.set(None)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)
        set_event_emitter(None)


# ---------------------------------------------------------------------------
# Enter, and what a turn writes -- all through the real writers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def in_turn(rid: str) -> Iterator[None]:
    """Run the block as the graph does: with *rid* bound as the turn's request id."""
    token = chat_request_id_var.set(None)
    set_chat_request_id(rid)
    try:
        yield
    finally:
        chat_request_id_var.reset(token)


def _ctx(session_id: str, operation: str, object_type: str):
    """The mutation provenance a turn builds from the session row (its pin)."""
    return get_session_manager().deck_mutation_context(
        session_id, operation=operation, object_type=object_type
    )


def _verdict(html: str, score: int) -> Dict[str, Any]:
    return {compute_slide_hash(html): {"score": score, "rating": "good", "explanation": "MK"}}


def press_enter(
    env: RollbackEnv,
    session_id: str,
    message: str = "MK-USER make me a deck",
    *,
    requested_deck_mode: Optional[str] = None,
    start: bool = True,
) -> str:
    """``POST /chat/async`` as Task 5 wires it, then the job's pending -> running.

    Session lock, the request row, the lock bound to it, the snapshot (before the
    user message: ``add_user_message`` locks the deck mode on a first message),
    then the user message.
    """
    sm = get_session_manager()
    assert sm.acquire_session_lock(session_id), "the session lock was not free at Enter"
    rid = sm.create_chat_request(session_id)
    sm.bind_session_lock(session_id, rid)
    with get_db_session() as db:
        _rb().take_generation_snapshot(db, request_id=rid, session_id=session_id)
    sm.add_user_message(
        session_id,
        message,
        message_type="user_query",
        request_id=rid,
        requested_deck_mode=requested_deck_mode,
    )
    if start:
        with get_db_session() as db:
            assert start_chat_request(db, rid), "the job could not start the request"
    return rid


def put_checkpoints(thread_id: str, rid: str, n: int, *, tag: str) -> List[str]:
    """*n* chained checkpoints (each with pending writes) on *thread_id*, plus one in
    a ``slide_pipeline`` sub-namespace, written as ``invoke_graph`` configures the
    saver (``chat_request_id`` in ``configurable``)."""
    saver = get_checkpointer()
    ids: List[str] = []
    parent: Optional[str] = None
    for step in range(n):
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"marker": f"MK-{tag}-{step}"}
        configurable: Dict[str, Any] = {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            "chat_request_id": rid,
        }
        if parent is not None:
            configurable["checkpoint_id"] = parent
        saver.put(
            {"configurable": configurable},
            checkpoint,
            {"source": "loop", "step": step, "parents": {}},
            {},
        )
        saver.put_writes(
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint["id"],
                    "chat_request_id": rid,
                }
            },
            [("slides", {"marker": f"MK-{tag}-{step}"})],
            f"task-{tag}-{step}",
        )
        parent = checkpoint["id"]
        ids.append(checkpoint["id"])
    sub = empty_checkpoint()
    sub["channel_values"] = {"marker": f"MK-{tag}-sub"}
    saver.put(
        {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": f"slide_pipeline:{tag}",
                "chat_request_id": rid,
            }
        },
        sub,
        {"source": "loop", "step": 0, "parents": {}},
        {},
    )
    ids.append(sub["id"])
    return ids


def seed_earlier_turn(env: RollbackEnv, session_id: str) -> str:
    """An earlier, COMPLETED Agent turn: a 4-slide deck with a Spec, css, external
    scripts, head meta, per-slide scripts, spec fragments and verification records,
    the session titled, the deck mode locked and the owner pinned, a reply message
    and two checkpoints.  Written by the real writers under that turn's own request
    id while it was running; then the request completes as today.

    Returns that earlier request's id (its messages must survive a later rollback).
    """
    sm = get_session_manager()
    rid0 = sm.create_chat_request(session_id)
    sm.add_user_message(
        session_id, "MK-EARLIER first message", message_type="user_query", request_id=rid0
    )
    with get_db_session() as db:
        assert start_chat_request(db, rid0)
    spec = make_spec((0, 1, 2, 3), title="MK-EARLIER-SPEC")
    with in_turn(rid0):
        write_deck_level_columns(
            session_id,
            title="MK-EARLIER-DECK-TITLE",
            css=".mk-before { color: #010203; }",
            external_scripts=["https://cdn.example.com/chart.js"],
            head_meta={"viewport": "width=1280"},
            deck_spec=spec.to_json(),
            modified_by=OWNER,
            mutation=_ctx(session_id, "write_deck_level", "deck"),
        )
        for position, html in enumerate(SLIDES_BEFORE):
            SlideWriter().write_slide(
                session_id,
                position,
                html,
                scripts=f"console.log('MK-before-{position}');",
                verification_record=_verdict(html, 80 + position),
                deck_spec_slide=spec.slide_at(position).model_dump(),
                modified_by=OWNER,
                mutation=_ctx(session_id, "write_slide", "slide"),
            )
        write_deck_level_columns(
            session_id,
            slide_count=4,
            html_content="<html>MK-EARLIER-KNIT</html>",
            scripts_content="MK-EARLIER-SCRIPTS",
            modified_by=OWNER,
            mutation=_ctx(session_id, "write_deck_level", "deck"),
        )
        sm.add_message(
            session_id, "assistant", "MK-EARLIER reply", message_type="chat", request_id=rid0
        )
        put_checkpoints(session_id, rid0, 2, tag="earlier")
    sm.update_chat_request_status(rid0, "completed")
    sm.rename_session(session_id, "MK-EARLIER-SESSION-TITLE")
    return rid0


def first_generation_turn(env: RollbackEnv, actor_sid: str, rid: str) -> None:
    """What a first Agent generation writes after Enter: three assistant messages
    (four ``rid`` messages with the user's), the pre-fan-out deck-level write that
    creates the deck row (title, css, scripts, head meta, Spec), three builder
    slides, the post-commit deck-level write, checkpoints, and the title thread's
    rename."""
    sm = get_session_manager()
    spec = make_spec((0, 1, 2), title="MK-TURN-SPEC")
    with in_turn(rid):
        sm.add_message(
            actor_sid, "assistant", "MK-TURN planning", message_type="chat", request_id=rid
        )
        write_deck_level_columns(
            actor_sid,
            title="MK-TURN-DECK-TITLE",
            css=".mk-turn { color: #0a0b0c; }",
            external_scripts=["https://cdn.example.com/chart.js"],
            head_meta={"viewport": "width=1920"},
            deck_spec=spec.to_json(),
            modified_by=OWNER,
            mutation=_ctx(actor_sid, "write_deck_level", "deck"),
        )
        for position, html in enumerate(SLIDES_BUILT):
            SlideWriter().write_slide(
                actor_sid,
                position,
                html,
                scripts=f"console.log('MK-built-{position}');",
                verification_record=_verdict(html, 90),
                deck_spec_slide=spec.slide_at(position).model_dump(),
                modified_by=OWNER,
                mutation=_ctx(actor_sid, "write_slide", "slide"),
            )
        sm.add_message(
            actor_sid, "assistant", "MK-TURN slides built", message_type="chat", request_id=rid
        )
        write_deck_level_columns(
            actor_sid,
            slide_count=3,
            html_content="<html>MK-TURN-KNIT</html>",
            scripts_content="MK-TURN-SCRIPTS",
            modified_by=OWNER,
            mutation=_ctx(actor_sid, "write_deck_level", "deck"),
        )
        sm.add_message(actor_sid, "assistant", "MK-TURN done", message_type="chat", request_id=rid)
        put_checkpoints(actor_sid, rid, 2, tag=f"turn-{rid[:6]}")
    # The title thread: its own thread, request id passed explicitly.
    sm.rename_session(actor_sid, "MK-TURN-SESSION-TITLE", request_id=rid, allow_completed=True)


def edit_turn(env: RollbackEnv, actor_sid: str, owner_sid: str, rid: str) -> None:
    """An edit turn on the 4-slide deck: ``apply_slide_layout`` deletes slide C and
    moves D in front of B, ``write_slide`` rewrites B (now at position 2), and
    ``write_deck_level_columns`` changes the css and the Spec, then the post-commit
    columns; messages and checkpoints as a turn writes them."""
    sm = get_session_manager()
    rows = _owner_slide_rows(env, owner_sid)
    expected_rows = [(r["slide_id"], compute_slide_hash(r["html"])) for r in rows]
    layout_spec = make_spec((0, 1, 2), title="MK-LAYOUT-SPEC")
    with in_turn(rid):
        sm.add_message(
            actor_sid, "assistant", "MK-EDIT planning", message_type="chat", request_id=rid
        )
        SlideWriter().apply_slide_layout(
            actor_sid,
            [0, 3, 1],
            deck_spec=layout_spec.to_json(),
            expected_rows=expected_rows,
            created_by=OWNER,
            mutation=_ctx(actor_sid, "save_deck_slides", "deck"),
        )
        SlideWriter().write_slide(
            actor_sid,
            2,
            REWRITTEN,
            scripts="console.log('MK-rewritten');",
            modified_by=CONTRIBUTOR if actor_sid != owner_sid else OWNER,
            mutation=_ctx(actor_sid, "write_slide", "slide"),
        )
        write_deck_level_columns(
            actor_sid,
            css=".mk-edited { color: #ff0000; }",
            deck_spec=make_spec((0, 1, 2), title="MK-EDITED-SPEC").to_json(),
            modified_by=OWNER,
            mutation=_ctx(actor_sid, "write_deck_level", "deck"),
        )
        write_deck_level_columns(
            actor_sid,
            slide_count=3,
            html_content="<html>MK-EDIT-KNIT</html>",
            scripts_content="MK-EDIT-SCRIPTS",
            modified_by=OWNER,
            mutation=_ctx(actor_sid, "write_deck_level", "deck"),
        )
        sm.add_message(actor_sid, "assistant", "MK-EDIT done", message_type="chat", request_id=rid)
        put_checkpoints(actor_sid, rid, 2, tag=f"edit-{rid[:6]}")


def foreign_edit(env: RollbackEnv, other_sid: str) -> None:
    """Another person's edit on the shared deck, outside any turn (no request id)."""
    SlideWriter().write_slide(
        other_sid,
        0,
        FOREIGN,
        scripts="",
        modified_by=CONTRIBUTOR,
        mutation=_ctx(other_sid, "write_slide", "slide"),
    )


def _owner_slide_rows(env: RollbackEnv, owner_sid: str) -> List[Dict[str, Any]]:
    pk = env.pk(owner_sid)
    rows = [r for r in env.tables()["session_slides"] if r["session_id"] == pk]
    return sorted(rows, key=lambda r: r["position"])


def roll_back(rid: str, terminal_status: str, error_message: Optional[str], refuse: bool):
    rb = _rb()
    return rb.roll_back_generation(
        rid,
        terminal_status=terminal_status,
        error_message=error_message,
        refuse_on_foreign_change=refuse,
    )


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def _assert_tables_equal(before, after, *, exclude: Sequence[str] = ()) -> None:
    names = (set(before) | set(after)) - set(exclude)
    changed = sorted(n for n in names if before.get(n) != after.get(n))
    assert not changed, f"tables changed that must not have: {changed}; " + "; ".join(
        f"{n}: {len(before.get(n, []))} -> {len(after.get(n, []))} rows" for n in changed
    )


def _assert_sessions_equal(before, after, *, touched: Sequence[str]) -> None:
    """Every ``user_sessions`` row equal on every column; ``last_activity`` excluded
    on the *touched* sessions only (Global Constraints)."""

    def norm(rows):
        return [_without(r, ("last_activity",)) if r["session_id"] in touched else r for r in rows]

    assert norm(after["user_sessions"]) == norm(before["user_sessions"])


def _assert_decks_restored(
    before, after, *, restored_deck_id: Optional[int], version: Optional[int]
):
    """Every deck row equal on every column; on the restored deck ``version`` must
    be *version* and ``updated_at`` is excluded."""
    assert len(after["session_slide_decks"]) == len(before["session_slide_decks"]), (
        "a deck row appeared or disappeared"
    )
    for b, a in zip(before["session_slide_decks"], after["session_slide_decks"]):
        if a["id"] == restored_deck_id:
            assert _without(a, ("version", "updated_at")) == _without(b, ("version", "updated_at"))
            assert a["version"] == version, (
                f"the restored deck's version is {a['version']}, expected {version} "
                "(the turn's last version + 1, so open clients and other processes reload)"
            )
        else:
            assert a == b


def _expected_restore_event(tables, *, owner_sid: str, actor_sid: str) -> Dict[str, Any]:
    owner = _one(tables["user_sessions"], session_id=owner_sid)
    actor = _one(tables["user_sessions"], session_id=actor_sid)
    deck = _one(tables["session_slide_decks"], session_id=owner["id"])
    release = _one(tables["graph_release"], id=actor["graph_release_id"])
    return {
        "root_session_id": owner["id"],
        "root_deck_id": deck["id"],
        "actor_session_id": actor["id"],
        "root_session_identity": owner["collaboration_identity"],
        "root_deck_identity": deck["collaboration_identity"],
        "actor_session_identity": actor["collaboration_identity"],
        "graph_release_id": actor["graph_release_id"],
        "graph_version": release["version_number"],
        "operation": "restore_version",
        "object_type": "deck",
        "object_id": None,
    }


def _assert_events(at_turn_end, after, *, restore_event: Optional[Dict[str, Any]]) -> None:
    """Append-only: every event the turn wrote is kept unchanged; the rollback adds
    exactly *restore_event* (or nothing)."""
    kept = at_turn_end["shared_deck_mutation_event"]
    now = after["shared_deck_mutation_event"]
    assert now[: len(kept)] == kept, "the rollback changed or removed mutation evidence"
    added = now[len(kept) :]
    if restore_event is None:
        assert added == [], f"a first-generation rollback records no mutation: {added}"
    else:
        assert len(added) == 1, f"expected one restore_version event, got {len(added)}"
        assert _without(added[0], ("id", "occurred_at")) == restore_event


def _assert_request(
    row, base, *, status, error_message, rollback_outcome, completed: Optional[bool]
) -> None:
    """The request row equals *base* on every column but the ones a terminal
    write sets.  ``completed=None`` leaves ``completed_at`` unasserted."""
    expected = dict(
        base, status=status, error_message=error_message, rollback_outcome=rollback_outcome
    )
    skip = ("completed_at",)
    assert _without(row, skip) == _without(expected, skip)
    if completed is True:
        assert row["completed_at"] is not None, "a terminal request carries completed_at"


def _assert_lock(env, session_id: str, *, held_by: Optional[str]) -> None:
    row = env.session_row(session_id)
    if held_by is None:
        assert (
            row["is_processing"],
            row["processing_started_at"],
            row["processing_request_id"],
        ) == (False, None, None), "the session lock was not released"
    else:
        assert row["is_processing"] is True, "the session lock was released"
        assert row["processing_request_id"] == held_by


def _assert_rolled_back_to_enter(
    env: RollbackEnv,
    before,
    at_turn_end,
    after,
    *,
    rid: str,
    actor_sid: str,
    owner_sid: str,
    terminal_status: str,
    error_message: Optional[str],
    deck_existed: bool,
) -> None:
    """``ROLLED_BACK``: every table as it was at Enter (see the module docstring)."""
    _assert_tables_equal(
        before,
        after,
        exclude=(
            "chat_requests",
            "user_sessions",
            "session_slide_decks",
            "shared_deck_mutation_event",
        ),
    )
    _assert_sessions_equal(before, after, touched=(actor_sid, owner_sid))
    if deck_existed:
        deck = _one(at_turn_end["session_slide_decks"], session_id=env.pk(owner_sid))
        enter_deck = _one(before["session_slide_decks"], session_id=env.pk(owner_sid))
        assert deck["version"] > enter_deck["version"], (
            "the turn bumped no version; the test proves nothing"
        )
        _assert_decks_restored(
            before, after, restored_deck_id=deck["id"], version=deck["version"] + 1
        )
        restore_event = _expected_restore_event(after, owner_sid=owner_sid, actor_sid=actor_sid)
    else:
        _assert_decks_restored(before, after, restored_deck_id=None, version=None)
        restore_event = None
    _assert_events(at_turn_end, after, restore_event=restore_event)
    assert [r for r in after["chat_requests"] if r["request_id"] != rid] == before["chat_requests"]
    _assert_request(
        _one(after["chat_requests"], request_id=rid),
        _one(at_turn_end["chat_requests"], request_id=rid),
        status=terminal_status,
        error_message=error_message,
        rollback_outcome="rolled_back",
        completed=True,
    )


def _messages_tagged(tables, rid: str) -> List[Dict[str, Any]]:
    return [m for m in tables["session_messages"] if m["request_id"] == rid]


def _thread_checkpoints(tables, thread_id: str) -> List[Dict[str, Any]]:
    return [c for c in tables["graph_checkpoints"] if c["thread_id"] == thread_id]


@contextlib.contextmanager
def _slide_inserts_fail(engine) -> Iterator[List[str]]:
    """Make every ``INSERT INTO session_slides`` raise, at the driver boundary, so the
    restore fails part-way through whatever helper it uses to re-insert the rows."""
    seen: List[str] = []

    def boom(conn, cursor, statement, parameters, context, executemany):
        if _SESSION_SLIDES_INSERT.match(statement):
            seen.append(statement)
            raise RuntimeError("MK-injected: the slide insert failed")

    event.listen(engine, "before_cursor_execute", boom)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", boom)


# ---------------------------------------------------------------------------
# ROLLED_BACK: a first generation goes back to an empty deck
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal_status, error_message, refuse", STOP_AND_FAILURE)
def test_first_generation_rollback_returns_to_empty(env, terminal_status, error_message, refuse):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    sm = get_session_manager()
    # Messages of other requests on this very session (no deck, deck mode unset):
    # a delete keyed on the session or a timestamp would take them too.
    sm.add_message(
        sid, "assistant", "MK-OTHER-REQUEST note", message_type="info", request_id="req-other"
    )
    sm.add_message(sid, "system", "MK-UNTAGGED note", message_type="info")
    before = env.tables()
    assert _one(before["user_sessions"], session_id=sid)["deck_mode"] is None
    assert _one(before["user_sessions"], session_id=sid)["graph_release_id"] is None

    rid = press_enter(env, sid)
    first_generation_turn(env, sid, rid)
    at_turn_end = env.tables()
    # Entry assertions: the turn really wrote everything the rollback must undo.
    owner_at_end = _one(at_turn_end["user_sessions"], session_id=sid)
    assert owner_at_end["deck_mode"] == "agent"
    assert owner_at_end["graph_release_id"] == env.release_id
    assert owner_at_end["title"] == "MK-TURN-SESSION-TITLE"
    assert env.deck_row(sid) is not None and env.slide_htmls(sid) == SLIDES_BUILT
    assert len(_messages_tagged(at_turn_end, rid)) == 4
    assert _thread_checkpoints(at_turn_end, sid)

    result = roll_back(rid, terminal_status, error_message, refuse)

    assert result == _rb().RollbackResult.ROLLED_BACK
    after = env.tables()
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status=terminal_status,
        error_message=error_message,
        deck_existed=False,
    )
    # Spelled out (all implied by the whole-table comparison above):
    assert env.deck_row(sid) is None and env.slide_htmls(sid) == []
    assert _messages_tagged(after, rid) == []
    assert _thread_checkpoints(after, sid) == []
    assert after["graph_checkpoint_writes"] == before["graph_checkpoint_writes"]
    assert after["generation_snapshots"] == []
    _assert_lock(env, sid, held_by=None)
    assert _rb().has_generation_snapshot(rid) is False
    assert _rb().has_pending_restore(sid) is False


def test_pending_request_rollback_undoes_the_user_message_and_deck_mode_lock(env):
    """A stop on a request still queued (``pending``): nothing but the user message,
    the deck-mode lock and the pin were written, and all of them are undone."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    before = env.tables()
    rid = press_enter(env, sid, start=False)
    at_enter = env.tables()
    assert env.request_row(rid)["status"] == "pending"
    assert _one(at_enter["user_sessions"], session_id=sid)["deck_mode"] == "agent"

    result = roll_back(rid, "cancelled", None, True)

    assert result == _rb().RollbackResult.ROLLED_BACK
    _assert_rolled_back_to_enter(
        env,
        before,
        at_enter,
        env.tables(),
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status="cancelled",
        error_message=None,
        deck_existed=False,
    )


# ---------------------------------------------------------------------------
# ROLLED_BACK: an edit goes back to the previous deck, exactly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal_status, error_message, refuse", STOP_AND_FAILURE)
def test_edit_rollback_is_exact(env, terminal_status, error_message, refuse):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid0 = seed_earlier_turn(env, sid)
    before = env.tables()
    deck_before = env.deck_row(sid)
    assert deck_before["deck_spec_json"] and deck_before["css"]
    assert all(r["verification_record"] for r in _owner_slide_rows(env, sid))

    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    at_turn_end = env.tables()
    # Entry assertions: the layout deleted and moved, the write rewrote, the
    # deck-level write changed css and Spec.
    assert env.slide_htmls(sid) == [SLIDES_BEFORE[0], SLIDES_BEFORE[3], REWRITTEN]
    deck_at_end = env.deck_row(sid)
    assert deck_at_end["css"] != deck_before["css"]
    assert deck_at_end["deck_spec_json"] != deck_before["deck_spec_json"]

    result = roll_back(rid, terminal_status, error_message, refuse)

    assert result == _rb().RollbackResult.ROLLED_BACK
    after = env.tables()
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        after,
        rid=rid,
        actor_sid=sid,
        owner_sid=sid,
        terminal_status=terminal_status,
        error_message=error_message,
        deck_existed=True,
    )
    # Every session_slides row equals the snapshot on every column (implied above).
    assert after["session_slides"] == before["session_slides"]
    assert env.slide_htmls(sid) == SLIDES_BEFORE
    # The earlier request's messages are untouched; this request's are gone.
    assert _messages_tagged(after, rid0) == _messages_tagged(before, rid0) != []
    assert _messages_tagged(after, rid) == []
    _assert_lock(env, sid, held_by=None)


def test_checkpoints_before_snapshot_survive(env):
    """The planner state before Enter survives byte-for-byte, in every namespace and
    with its pending writes; everything the turn checkpointed (default namespace,
    sub-namespace, writes) is gone; another thread is untouched."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    other_sid = env.new_session(created_by=STRANGER, title="MK-OTHER-DECK", pinned=True)
    other_rid = get_session_manager().create_chat_request(other_sid)
    with get_db_session() as db:
        assert start_chat_request(db, other_rid)
    before = env.tables()
    earlier = _thread_checkpoints(before, sid)
    assert len(earlier) == 3, "the earlier turn left no checkpoints; the test proves nothing"

    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    # Another person's turn checkpoints its own thread meanwhile.
    put_checkpoints(other_sid, other_rid, 1, tag="other-thread")
    at_turn_end = env.tables()
    assert len(_thread_checkpoints(at_turn_end, sid)) == len(earlier) + 3
    other_thread = _thread_checkpoints(at_turn_end, other_sid)
    other_writes = [
        w for w in at_turn_end["graph_checkpoint_writes"] if w["thread_id"] == other_sid
    ]
    assert other_thread and other_writes

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK

    after = env.tables()
    assert _thread_checkpoints(after, sid) == earlier
    assert [w for w in after["graph_checkpoint_writes"] if w["thread_id"] == sid] == [
        w for w in before["graph_checkpoint_writes"] if w["thread_id"] == sid
    ]
    assert _thread_checkpoints(after, other_sid) == other_thread
    assert [
        w for w in after["graph_checkpoint_writes"] if w["thread_id"] == other_sid
    ] == other_writes
    with get_db_session() as db:
        assert get_checkpointer().latest_checkpoint_id(sid, session=db) == max(
            c["checkpoint_id"] for c in earlier
        )


@pytest.mark.parametrize("conversation_before", [None, "conv-before"])
def test_genie_one_conversation_id_restored_only_on_entry(env, conversation_before):
    """The actor's ``genie_one`` entry gets its pre-Enter ``conversation_id`` back;
    every other agent-config change made mid-turn (outside the turn, e.g. the
    agent-config route) survives."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    _save_agent_config(sid, AgentConfig(tools=[GenieOneTool(conversation_id=conversation_before)]))
    before = env.tables()

    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    with in_turn(rid):
        get_session_manager().set_genie_one_conversation_id(sid, "conv-written-by-the-turn")
    # Mid-turn, the user adds a Genie space and a deck prompt (the client PUTs the
    # whole config, carrying the conversation id it last read).
    _save_agent_config(
        sid,
        AgentConfig(
            tools=[
                GenieOneTool(conversation_id="conv-written-by-the-turn"),
                GenieTool(type="genie", space_id="space-mk", space_name="MK Space"),
            ],
            deck_prompt_id=7,
        ),
    )
    mid_turn = copy.deepcopy(env.session_row(sid)["agent_config"])

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK

    expected = copy.deepcopy(mid_turn)
    genie_one = [t for t in expected["tools"] if t.get("type") == "genie_one"]
    assert len(genie_one) == 1
    genie_one[0]["conversation_id"] = conversation_before
    assert env.session_row(sid)["agent_config"] == expected
    # Nothing else about the session is left over from the turn.
    restored = env.session_row(sid)
    entered = _one(before["user_sessions"], session_id=sid)
    assert _without(restored, ("last_activity", "agent_config")) == _without(
        entered, ("last_activity", "agent_config")
    )


def test_genie_one_entry_removed_mid_turn_is_not_recreated(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    _save_agent_config(sid, AgentConfig(tools=[GenieOneTool(conversation_id="conv-before")]))

    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    with in_turn(rid):
        get_session_manager().set_genie_one_conversation_id(sid, "conv-written-by-the-turn")
    # Mid-turn, the user removes Genie One.
    _save_agent_config(
        sid,
        AgentConfig(tools=[GenieTool(type="genie", space_id="space-mk", space_name="MK Space")]),
    )
    mid_turn = copy.deepcopy(env.session_row(sid)["agent_config"])

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK

    assert env.session_row(sid)["agent_config"] == mid_turn


# ---------------------------------------------------------------------------
# Contributors: the owner's fields and the actor's fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal_status, error_message, refuse", STOP_AND_FAILURE)
def test_contributor_first_generation_rollback_restores_owner_and_actor_fields(
    env, terminal_status, error_message, refuse
):
    """A contributor's first message on an unlocked, deck-less shared session:
    ``add_user_message`` locks and pins the OWNER; the turn creates the OWNER's
    deck and retitles the OWNER (deck-level title); the title thread retitles the
    CONTRIBUTOR; Genie One writes the CONTRIBUTOR's entry; checkpoints go on the
    CONTRIBUTOR's thread.  All of it comes back; the owner's own planner thread
    and messages are untouched."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    contrib = env.contributor(owner)
    _save_agent_config(contrib, AgentConfig(tools=[GenieOneTool(conversation_id=None)]))
    sm = get_session_manager()
    # The owner's own earlier planner state and notes (no deck yet).
    owner_rid = sm.create_chat_request(owner)
    with get_db_session() as db:
        assert start_chat_request(db, owner_rid)
    put_checkpoints(owner, owner_rid, 1, tag="owner-thread")
    sm.add_message(owner, "assistant", "MK-OWNER note", message_type="info", request_id=owner_rid)
    sm.update_chat_request_status(owner_rid, "completed")
    before = env.tables()
    assert _one(before["user_sessions"], session_id=owner)["graph_release_id"] is None
    assert _one(before["user_sessions"], session_id=contrib)["graph_release_id"] == env.release_id

    rid = press_enter(env, contrib)
    first_generation_turn(env, contrib, rid)
    with in_turn(rid):
        sm.set_genie_one_conversation_id(contrib, "conv-written-by-the-turn")
    at_turn_end = env.tables()
    owner_at_end = _one(at_turn_end["user_sessions"], session_id=owner)
    contrib_at_end = _one(at_turn_end["user_sessions"], session_id=contrib)
    assert (owner_at_end["deck_mode"], owner_at_end["graph_release_id"], owner_at_end["title"]) == (
        "agent",
        env.release_id,
        "MK-TURN-DECK-TITLE",
    )
    assert contrib_at_end["title"] == "MK-TURN-SESSION-TITLE"
    assert env.deck_row(owner) is not None
    assert (
        _thread_checkpoints(at_turn_end, contrib) and len(_messages_tagged(at_turn_end, rid)) == 4
    )

    result = roll_back(rid, terminal_status, error_message, refuse)

    assert result == _rb().RollbackResult.ROLLED_BACK
    after = env.tables()
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        after,
        rid=rid,
        actor_sid=contrib,
        owner_sid=owner,
        terminal_status=terminal_status,
        error_message=error_message,
        deck_existed=False,
    )
    assert _thread_checkpoints(after, contrib) == []
    assert _thread_checkpoints(after, owner) == _thread_checkpoints(before, owner) != []
    _assert_lock(env, contrib, held_by=None)


@pytest.mark.parametrize("terminal_status, error_message, refuse", STOP_AND_FAILURE)
def test_contributor_edit_rollback_records_the_restore_as_the_contributor(
    env, terminal_status, error_message, refuse
):
    """The owner's earlier events are ANOTHER actor's, but they precede the
    watermark, so they are no foreign change; the restore's ``restore_version``
    event is the contributor's (actor) on the owner's deck (root)."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    before = env.tables()
    assert before["shared_deck_mutation_event"], "no earlier evidence; the watermark is untested"

    rid = press_enter(env, contrib)
    edit_turn(env, contrib, owner, rid)
    with in_turn(rid):
        write_deck_level_columns(
            contrib,
            title="MK-CONTRIB-RETITLED-THE-DECK",
            mutation=_ctx(contrib, "write_deck_level", "deck"),
        )
    get_session_manager().rename_session(
        contrib, "MK-CONTRIB-SESSION-TITLE", request_id=rid, allow_completed=True
    )
    at_turn_end = env.tables()
    assert (
        _one(at_turn_end["user_sessions"], session_id=owner)["title"]
        == "MK-CONTRIB-RETITLED-THE-DECK"
    )

    result = roll_back(rid, terminal_status, error_message, refuse)

    assert result == _rb().RollbackResult.ROLLED_BACK
    _assert_rolled_back_to_enter(
        env,
        before,
        at_turn_end,
        env.tables(),
        rid=rid,
        actor_sid=contrib,
        owner_sid=owner,
        terminal_status=terminal_status,
        error_message=error_message,
        deck_existed=True,
    )


def test_rollback_drops_this_process_cache_for_actor_and_owner(env, monkeypatch):
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    this_process = ChatService()
    monkeypatch.setattr(chat_service_module, "_chat_service_instance", this_process)

    rid = press_enter(env, contrib)
    edit_turn(env, contrib, owner, rid)
    assert this_process._get_or_load_deck(contrib) is not None
    assert this_process._get_or_load_deck(owner) is not None
    assert {contrib, owner} <= set(this_process._deck_cache)

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK

    assert contrib not in this_process._deck_cache and owner not in this_process._deck_cache
    assert contrib not in this_process._deck_versions()
    assert owner not in this_process._deck_versions()


# ---------------------------------------------------------------------------
# The snapshot row and its small helpers
# ---------------------------------------------------------------------------


def test_snapshot_row_identifies_actor_owner_checkpoint_and_watermark(env):
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    sm = get_session_manager()
    # The contributor's own planner thread, and the owner's (newer), differ.
    contrib_rid = sm.create_chat_request(contrib)
    with get_db_session() as db:
        assert start_chat_request(db, contrib_rid)
    contrib_ids = put_checkpoints(contrib, contrib_rid, 1, tag="contrib-thread")
    sm.update_chat_request_status(contrib_rid, "completed")
    owner_rid = sm.create_chat_request(owner)
    with get_db_session() as db:
        assert start_chat_request(db, owner_rid)
    put_checkpoints(owner, owner_rid, 1, tag="owner-newer")
    sm.update_chat_request_status(owner_rid, "completed")
    owner_events = [
        e["id"]
        for e in env.tables()["shared_deck_mutation_event"]
        if e["root_session_id"] == env.pk(owner)
    ]
    # A later event on ANOTHER deck must not raise this deck's watermark.
    stranger = env.new_session(created_by=STRANGER, title="MK-STRANGER", pinned=True)
    seed_earlier_turn(env, stranger)
    assert max(e["id"] for e in env.tables()["shared_deck_mutation_event"]) > max(owner_events)

    rid = press_enter(env, contrib)

    rows = env.snapshot_rows(rid)
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_session_pk"] == env.pk(contrib)
    assert row["owner_session_pk"] == env.pk(owner)
    assert row["deck_present"] is True
    assert row["checkpoint_id"] == max(contrib_ids), "the checkpoint is the ACTOR's thread's newest"
    assert row["mutation_watermark"] == max(owner_events)
    assert row["state"] == "active"
    assert row["created_at"] is not None
    assert _rb().has_generation_snapshot(rid) is True
    assert _rb().has_pending_restore(contrib) is False


def test_first_generation_snapshot_has_no_deck_watermark_zero_and_no_checkpoint(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env, sid)
    row = env.snapshot_rows(rid)[0]
    assert (row["deck_present"], row["mutation_watermark"], row["checkpoint_id"], row["state"]) == (
        False,
        0,
        None,
        "active",
    )


def test_snapshot_and_discard_run_in_the_callers_transaction(env):
    rb = _rb()
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = get_session_manager().create_chat_request(sid)
    assert rb.has_generation_snapshot(rid) is False

    db = env.factory()
    try:
        rb.take_generation_snapshot(db, request_id=rid, session_id=sid)
        db.rollback()
    finally:
        db.close()
    assert rb.has_generation_snapshot(rid) is False, "take_generation_snapshot committed"

    with get_db_session() as db:
        rb.take_generation_snapshot(db, request_id=rid, session_id=sid)
    assert rb.has_generation_snapshot(rid) is True

    db = env.factory()
    try:
        rb.discard_generation_snapshot(db, rid)
        db.rollback()
    finally:
        db.close()
    assert rb.has_generation_snapshot(rid) is True, "discard_generation_snapshot committed"

    with get_db_session() as db:
        rb.discard_generation_snapshot(db, rid)
    assert rb.has_generation_snapshot(rid) is False
    assert env.snapshot_rows(rid) == []


# ---------------------------------------------------------------------------
# NOT_LIVE: nothing happens twice, or after the turn finished
# ---------------------------------------------------------------------------


def test_second_rollback_is_not_live(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK
    after_first = env.tables()

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.NOT_LIVE
    assert roll_back(rid, "error", "late failure", False) == _rb().RollbackResult.NOT_LIVE

    # No second restore: no second restore_version event, no version bump, the
    # request keeps its first outcome.
    _assert_tables_equal(after_first, env.tables())


@pytest.mark.parametrize("terminal_status, error_message, refuse", STOP_AND_FAILURE)
def test_rollback_on_completed_is_not_live(env, terminal_status, error_message, refuse):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    get_session_manager().update_chat_request_status(rid, "completed")
    before = env.tables()

    assert roll_back(rid, terminal_status, error_message, refuse) == _rb().RollbackResult.NOT_LIVE

    _assert_tables_equal(before, env.tables())


def test_rollback_of_unknown_request_is_not_live(env):
    before = env.tables()
    assert roll_back("req-does-not-exist", "cancelled", None, True) == _rb().RollbackResult.NOT_LIVE
    _assert_tables_equal(before, env.tables())


# ---------------------------------------------------------------------------
# Sealed: the turn has committed
# ---------------------------------------------------------------------------


def test_cancel_on_sealed_is_not_live_and_changes_nothing(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    assert _rb().seal_generation(rid) is True
    before = env.tables()

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.NOT_LIVE

    _assert_tables_equal(before, env.tables())
    assert env.request_row(rid)["status"] == "running"
    _assert_lock(env, sid, held_by=rid)


def test_failure_on_sealed_keeps_deck_and_ends_request(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    assert _rb().seal_generation(rid) is True
    before = env.tables()

    result = roll_back(rid, "error", "Generation interrupted", False)

    assert result == _rb().RollbackResult.SEALED_KEPT
    after = env.tables()
    # The finished deck, its messages and checkpoints stay; only the request row,
    # the snapshot and the lock change.
    _assert_tables_equal(
        before, after, exclude=("chat_requests", "generation_snapshots", "user_sessions")
    )
    _assert_request(
        env.request_row(rid),
        _one(before["chat_requests"], request_id=rid),
        status="error",
        error_message="Generation interrupted",
        rollback_outcome=None,
        completed=None,
    )
    assert after["generation_snapshots"] == [
        r for r in before["generation_snapshots"] if r["request_id"] != rid
    ]
    _assert_lock(env, sid, held_by=None)
    released = dict(
        _one(before["user_sessions"], session_id=sid),
        is_processing=False,
        processing_started_at=None,
        processing_request_id=None,
    )
    _assert_sessions_equal(
        dict(
            before,
            user_sessions=[
                released if r["session_id"] == sid else r for r in before["user_sessions"]
            ],
        ),
        after,
        touched=(sid,),
    )


def test_seal_generation_seals_an_active_snapshot(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env, sid)
    first_generation_turn(env, sid, rid)
    before = env.tables()

    assert _rb().seal_generation(rid) is True

    after = env.tables()
    _assert_tables_equal(before, after, exclude=("generation_snapshots",))
    assert env.snapshot_rows(rid) == [
        dict(_one(before["generation_snapshots"], request_id=rid), state="sealed")
    ]
    assert env.request_row(rid)["status"] == "running", "sealing does not complete the request"


def test_seal_generation_twice_is_false_and_changes_nothing(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env, sid)
    assert _rb().seal_generation(rid) is True
    before = env.tables()

    assert _rb().seal_generation(rid) is False

    _assert_tables_equal(before, env.tables())


def test_seal_fails_after_cancel(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env, sid)
    first_generation_turn(env, sid, rid)
    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK
    before = env.tables()

    assert _rb().seal_generation(rid) is False

    _assert_tables_equal(before, env.tables())


def test_seal_generation_without_snapshot_returns_true_and_warns(env, caplog):
    """Claim matched, no snapshot row (unreachable after Task 5's fail-closed submit):
    True, so a graph turn is never abandoned in ``running``, and a WARNING."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    sm = get_session_manager()
    rid = sm.create_chat_request(sid)
    with get_db_session() as db:
        assert start_chat_request(db, rid)
    before = env.tables()
    caplog.set_level(logging.WARNING)
    caplog.clear()

    assert _rb().seal_generation(rid) is True

    assert [r for r in caplog.records if r.levelno == logging.WARNING], (
        "sealing a live request with no snapshot must log a WARNING"
    )
    _assert_tables_equal(before, env.tables())


def test_seal_generation_of_unknown_request_is_false(env):
    before = env.tables()
    assert _rb().seal_generation("req-does-not-exist") is False
    _assert_tables_equal(before, env.tables())


# ---------------------------------------------------------------------------
# NO_SNAPSHOT: a monolith request
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal_status, error_message, refuse", STOP_AND_FAILURE)
def test_monolith_request_no_snapshot(env, terminal_status, error_message, refuse):
    """No snapshot (a Legacy/monolith request): the status is set and the lock
    released, and NOTHING is rolled back -- the monolith's message and deck-mode
    lock stay as today."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    sm = get_session_manager()
    assert sm.acquire_session_lock(sid)
    rid = sm.create_chat_request(sid)
    sm.bind_session_lock(sid, rid)
    sm.add_user_message(
        sid,
        "MK-LEGACY message",
        message_type="user_query",
        request_id=rid,
        requested_deck_mode="legacy",
    )
    with get_db_session() as db:
        assert start_chat_request(db, rid)
    sm.add_message(sid, "assistant", "MK-LEGACY reply", message_type="chat", request_id=rid)
    before = env.tables()

    result = roll_back(rid, terminal_status, error_message, refuse)

    assert result == _rb().RollbackResult.NO_SNAPSHOT
    after = env.tables()
    _assert_tables_equal(before, after, exclude=("chat_requests", "user_sessions"))
    row = env.request_row(rid)
    assert row["status"] == terminal_status
    assert row["rollback_outcome"] is None
    assert _without(row, ("status", "error_message", "completed_at")) == _without(
        _one(before["chat_requests"], request_id=rid), ("status", "error_message", "completed_at")
    )
    _assert_lock(env, sid, held_by=None)
    assert len(_messages_tagged(after, rid)) == 2
    assert env.session_row(sid)["deck_mode"] == "legacy"


# ---------------------------------------------------------------------------
# Someone else changed the deck: never roll back their work
# ---------------------------------------------------------------------------


def _shared_edit_in_flight(env):
    """The owner's edit generation is running; a contributor edits a slide."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    rid = press_enter(env, owner)
    edit_turn(env, owner, owner, rid)
    foreign_edit(env, contrib)
    assert env.slide_htmls(owner)[0] == FOREIGN
    return owner, contrib, rid


def test_cancel_refused_on_foreign_change(env):
    owner, contrib, rid = _shared_edit_in_flight(env)
    before = env.tables()

    result = roll_back(rid, "cancelled", None, True)

    assert result == _rb().RollbackResult.REFUSED_FOREIGN_CHANGE
    # The transaction rolled back: still running, deck unchanged (the other
    # person's edit survives), snapshot kept, lock still held.
    _assert_tables_equal(before, env.tables())
    assert env.request_row(rid)["status"] == "running"
    assert env.snapshot_rows(rid)[0]["state"] == "active"
    _assert_lock(env, owner, held_by=rid)


def test_failure_keeps_foreign_change(env, caplog):
    owner, contrib, rid = _shared_edit_in_flight(env)
    before = env.tables()
    caplog.set_level(logging.ERROR)
    caplog.clear()

    result = roll_back(rid, "error", "Model call failed: 403", False)

    assert result == _rb().RollbackResult.KEPT_FOREIGN_CHANGE
    after = env.tables()
    # Deck, slides, messages, checkpoints, evidence: as they stand, not restored.
    _assert_tables_equal(
        before, after, exclude=("chat_requests", "generation_snapshots", "user_sessions")
    )
    row = env.request_row(rid)
    assert (row["status"], row["rollback_outcome"]) == ("error", "kept_foreign_change")
    assert _without(
        row, ("status", "rollback_outcome", "error_message", "completed_at")
    ) == _without(
        _one(before["chat_requests"], request_id=rid),
        ("status", "rollback_outcome", "error_message", "completed_at"),
    )
    assert env.snapshot_rows(rid) == []
    _assert_lock(env, owner, held_by=None)
    assert env.slide_htmls(owner)[0] == FOREIGN
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], "logged at ERROR"


def test_first_generation_foreign_change_detected(env):
    """No deck at the snapshot (watermark 0): an event on the OWNER's session by
    another actor after Enter still refuses a stop -- matching on root_session_id
    rather than on a deck id that did not exist yet."""
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    contrib = env.contributor(owner)
    rid = press_enter(env, owner)
    assert env.snapshot_rows(rid)[0]["mutation_watermark"] == 0
    first_generation_turn(env, owner, rid)
    foreign_edit(env, contrib)
    before = env.tables()

    result = roll_back(rid, "cancelled", None, True)

    assert result == _rb().RollbackResult.REFUSED_FOREIGN_CHANGE
    _assert_tables_equal(before, env.tables())
    assert env.request_row(rid)["status"] == "running"


def test_events_on_other_decks_are_not_foreign_changes(env):
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    stranger = env.new_session(created_by=STRANGER, title="MK-STRANGER", pinned=True)
    seed_earlier_turn(env, stranger)
    rid = press_enter(env, owner)
    edit_turn(env, owner, owner, rid)
    # Meanwhile someone else edits THEIR OWN deck (a later event id, another root).
    foreign_edit(env, stranger)

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK
    assert env.slide_htmls(owner) == SLIDES_BEFORE
    assert env.slide_htmls(stranger)[0] == FOREIGN


# ---------------------------------------------------------------------------
# RESTORE_FAILED: a failed restore keeps the snapshot and the lock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal_status, error_message, refuse", STOP_AND_FAILURE)
def test_restore_failure_marks_restore_failed_and_keeps_lock(
    env, caplog, terminal_status, error_message, refuse
):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    before = env.tables()
    caplog.set_level(logging.ERROR)
    caplog.clear()

    with _slide_inserts_fail(env.engine) as attempted:
        result = roll_back(rid, terminal_status, error_message, refuse)

    assert attempted, "the restore never inserted a slide row; the injected failure proves nothing"
    assert result == _rb().RollbackResult.RESTORE_FAILED
    after = env.tables()
    # The restore's transaction rolled back whole: no half-restored deck, the
    # turn's messages and checkpoints still there, the lock untouched.
    _assert_tables_equal(before, after, exclude=("chat_requests", "generation_snapshots"))
    _assert_request(
        env.request_row(rid),
        _one(before["chat_requests"], request_id=rid),
        status=terminal_status,
        error_message=RESTORE_PENDING,
        rollback_outcome="restore_failed",
        completed=None,
    )
    assert env.snapshot_rows(rid) == [
        dict(_one(before["generation_snapshots"], request_id=rid), state="restore_failed")
    ]
    _assert_lock(env, sid, held_by=rid)
    assert _rb().has_pending_restore(sid) is True
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], "logged at ERROR"
    # The request is terminal now: a second call is NOT_LIVE and leaves the
    # restore_failed snapshot for the recovery sweep (Task 6).
    after_failure = env.tables()
    assert roll_back(rid, terminal_status, error_message, refuse) == _rb().RollbackResult.NOT_LIVE
    _assert_tables_equal(after_failure, env.tables())


def test_pending_restore_is_seen_from_contributor_and_owner(env):
    owner = env.new_session(created_by=OWNER, title="MK-OWNER-TITLE")
    seed_earlier_turn(env, owner)
    contrib = env.contributor(owner)
    stranger = env.new_session(created_by=STRANGER, title="MK-STRANGER", pinned=True)
    rid = press_enter(env, contrib)
    edit_turn(env, contrib, owner, rid)
    assert _rb().has_pending_restore(contrib) is False, (
        "an active snapshot is not a pending restore"
    )

    with _slide_inserts_fail(env.engine):
        assert roll_back(rid, "error", "boom", False) == _rb().RollbackResult.RESTORE_FAILED

    assert _rb().has_pending_restore(contrib) is True
    assert _rb().has_pending_restore(owner) is True
    assert _rb().has_pending_restore(stranger) is False
    _assert_lock(env, contrib, held_by=rid)


# ---------------------------------------------------------------------------
# A late write from the abandoned turn
# ---------------------------------------------------------------------------


def test_late_writer_after_rollback_is_refused(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK
    before = env.tables()

    with in_turn(rid):
        with pytest.raises(TurnFencedError):
            SlideWriter().write_slide(
                sid,
                1,
                "<div class='slide'><h1>MK-LATE-BUILDER</h1></div>",
                modified_by=OWNER,
                mutation=_ctx(sid, "write_slide", "slide"),
            )
        with pytest.raises(TurnFencedError):
            get_session_manager().add_message(
                sid, "assistant", "MK-LATE message", message_type="chat", request_id=rid
            )

    assert env.slide_htmls(sid) == SLIDES_BEFORE
    _assert_tables_equal(before, env.tables())


# ---------------------------------------------------------------------------
# The deck cache of another process (a second ChatService stands in for it)
# ---------------------------------------------------------------------------


def test_other_process_cache_drops_deck_after_first_generation_rollback(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    rid = press_enter(env, sid)
    first_generation_turn(env, sid, rid)
    other_process = ChatService()
    warmed = other_process._get_or_load_deck(sid)
    assert warmed is not None and [s.html for s in warmed.slides] == SLIDES_BUILT

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK

    assert other_process._get_or_load_deck(sid) is None, (
        "another process kept serving the rolled-back deck from its cache"
    )
    assert sid not in other_process._deck_cache


def test_other_process_cache_reloads_after_edit_rollback(env):
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    rid = press_enter(env, sid)
    edit_turn(env, sid, sid, rid)
    other_process = ChatService()
    warmed = other_process._get_or_load_deck(sid)
    assert [s.html for s in warmed.slides] == [SLIDES_BEFORE[0], SLIDES_BEFORE[3], REWRITTEN]

    assert roll_back(rid, "cancelled", None, True) == _rb().RollbackResult.ROLLED_BACK

    reloaded = other_process._get_or_load_deck(sid)
    assert reloaded is not warmed
    assert [s.html for s in reloaded.slides] == SLIDES_BEFORE


def test_confirmed_missing_deck_row_drops_cached_deck(env):
    """The cache fix on its own: another process deleted the deck row (as a
    first-generation rollback does), so a CONFIRMED "no row" drops this process's
    cached deck and returns None.  Today a missing row reads as version None and
    the stale cached deck is served."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    other_process = ChatService()
    assert other_process._get_or_load_deck(sid) is not None
    db = env.factory()
    try:
        owner_pk = db.query(UserSession.id).filter(UserSession.session_id == sid).scalar()
        db.query(SessionSlide).filter(SessionSlide.session_id == owner_pk).delete()
        db.query(SessionSlideDeck).filter(SessionSlideDeck.session_id == owner_pk).delete()
        db.commit()
    finally:
        db.close()

    assert other_process._get_or_load_deck(sid) is None
    assert sid not in other_process._deck_cache
    assert sid not in other_process._deck_versions()


def test_db_error_keeps_cached_deck(env, monkeypatch):
    """A database error while checking the version keeps today's behaviour: the
    cached deck is served.  Shared with Legacy, whose only observable change is
    that a deleted deck row is no longer served from a stale cache."""
    sid = env.new_session(created_by=OWNER, title="MK-NEW-SESSION")
    seed_earlier_turn(env, sid)
    other_process = ChatService()
    cached = other_process._get_or_load_deck(sid)
    assert cached is not None

    def unreachable():
        raise OperationalError("SELECT 1", {}, Exception("MK-injected: database unreachable"))

    monkeypatch.setattr("src.core.database.get_session_local", lambda: unreachable)

    assert other_process._get_or_load_deck(sid) is cached
    assert other_process._deck_cache.get(sid) is cached
