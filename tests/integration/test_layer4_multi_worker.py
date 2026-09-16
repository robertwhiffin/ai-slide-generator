"""Layer 4: concurrency and multi-worker safety on PostgreSQL.

Proves the new design is free of the bug class the rebuild exists to remove:
with four uvicorn workers, whichever worker answered a request saw a different
truth because deck state was held in process memory.

Layer 4 needs a database and no model, so unlike layer 3 it runs in CI
(the ``layer4`` job, enabled by default, named below in the CI comment).

The six plan assertions
-----------------------
1. 15 writes to distinct ``(session_id, position)`` PK slots all persist.
   Completeness assertion: every position lands in the database.  Concurrent
   writes stress the PK on Postgres; the test does NOT prove they ran in
   parallel (serialised writes would also pass).  The name reflects this.

2. The deck-level ``version`` counter rejects a stale write with HTTP 409.
   This assertion is route-level: ``save_slide_deck`` is the writer that
   accepts ``expected_version``.  The test drives it through a TestClient —
   a database-only test of the same property would bypass the HTTP layer that
   a frontend caller actually sees.  Said plainly in the docstring as
   instructed.

3. Two deck-level writes in one turn do not conflict.  ``architect_node``
   (``nodes.py``) and ``deck_reviewer_node`` (``nodes.py``) are sequential,
   both calling ``write_deck_level_columns``.  The assertion is the double
   ``version`` bump within one turn (v_initial → v_initial + 2).

4. The release query is correct from a DIFFERENT PROCESS than the builder.
   ``slides_since_cursor`` reads rows only, zero caches.  Sabotaged by having
   the parent buffer instead of persisting — child confirms no positions —
   then persisted, and child confirms it reads them back.

5. The ``SqlAlchemyCheckpointSaver`` resumes a turn in a second process.
   Checkpoint stored in parent; child process re-opens the same DB and reads
   back the stored blob via ``thread_id`` == ``session_id``.

6. Four concurrent sweepers run at most one arc review.  The ``unclaimed``
   predicate in the conditional UPDATE is the exclusive lock; without it
   (or with ``skip_locked``) all four would win.  The Postgres-only version
   is the load-bearing one; SQLite serialises via its single-writer lock and
   cannot see the race.

Plus: the human-versus-graph 409
---------------------------------
The graph bumps ``deck.version`` twice per turn (``architect_node`` writes,
then ``deck_reviewer_node`` writes again).  Meanwhile the browser holds the
version token it read before the turn started.  After the turn the frontend's
token is stale by 2, and its next save produces a 409.  This case is different
from assertion 2: assertion 2 proves the lock works; this proves the graph's
two sequential writes together cause the mismatch a user actually experiences.

Fixture note
-----------
Every class here uses ``postgres_engine`` (``conftest.py``).  NOT
``sqlite_engine_file_backed`` — that fixture is ``StaticPool``, which hands
every thread one connection and corrupted the database 3 of 3 runs on ws4c.
``graph_turn_env`` monkeypatches and monkeypatches do not cross a process
boundary; the cross-process tests set up their own connections.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sa_text
from sqlalchemy.engine import make_url

from src.api.main import app
from src.api.services.session_manager import SessionManager, VersionConflictError
from src.api.services.slide_repository import SlideWriter
from src.core.database import Base, get_db, _run_migrations
from src.core.permission_context import PermissionContext
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from tests.integration.conftest import _make_factory
from tests.integration.postgres_concurrency_helpers import (
    _ClaimGate,
    _WAIT_SECONDS,
    _await_lock_waiters,
    _seed_owner_deck,
    _thread_aware_db,
)

# ---------------------------------------------------------------------------
# CI job: the layer4 job names this file in its run block.
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.postgres

_REPO_ROOT = Path(__file__).resolve().parents[2]

# All the get_db_session patch targets the production code uses.
_SM_DB = "src.api.services.session_manager.get_db_session"
_REPO_DB = "src.api.services.slide_repository.get_db_session"
_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
_SPEC_SYNC_DB = "src.services.spec_sync.get_db_session"
_AUTHZ_DB = "src.api.routes._authz.get_db_session"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _patched_db(factory):
    """Patch all get_db_session callers to use *factory*."""
    fake = _make_fake_db(factory)
    with (
        patch(_SM_DB, fake),
        patch(_REPO_DB, fake),
        patch(_WRITER_DB, fake),
        patch(_SPEC_SYNC_DB, fake),
    ):
        yield fake


def _make_fake_db(factory):
    """Contextmanager get_db_session replacement that uses *factory*."""

    @contextlib.contextmanager
    def fake_get_db_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return fake_get_db_session


def _seed_owner(factory, session_id: Optional[str] = None) -> str:
    """Create a UserSession row and return its string session_id."""
    sid = session_id or f"l4-{uuid.uuid4().hex[:12]}"
    db = factory()
    try:
        owner = UserSession(session_id=sid, created_by="layer4@example.com")
        db.add(owner)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return sid


def _seed_deck(factory, session_id: str, version: int = 1) -> int:
    """Create a minimal SessionSlideDeck for *session_id*; return deck.id."""
    db = factory()
    try:
        owner = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        deck = SessionSlideDeck(
            session_id=owner.id,
            title="Layer-4 test deck",
            html_content="",
            scripts_content="",
            slide_count=0,
            version=version,
        )
        db.add(deck)
        db.commit()
        db.refresh(deck)
        return deck.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _deck_version(factory, session_id: str) -> int:
    """Read the current deck.version from a fresh session."""
    db = factory()
    try:
        owner = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        deck = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner.id)
            .one()
        )
        return deck.version
    finally:
        db.close()


def _assert_postgres(engine) -> None:
    """Fail loudly if the engine is not a PostgreSQL database.

    A test that runs against SQLite may look green while proving nothing about
    Postgres's row-level locking.  A test that self-skips due to a missing DB
    looks identical to a pass.  This assertion catches both.
    """
    dialect = engine.dialect.name
    assert dialect == "postgresql", (
        f"Layer-4 tests must run against PostgreSQL — got {dialect!r}. "
        "Either the postgres_engine fixture self-skipped and something else "
        "supplied the engine, or the wrong fixture is being used."
    )


# ---------------------------------------------------------------------------
# Assertion 1: 15 parallel slide-row writes do not collide
# ---------------------------------------------------------------------------


class TestFifteenParallelSlideWrites:
    """Fifteen threads each claim a distinct (session_id, position) pair.

    ``write_slide`` opens its own session (``slide_repository.py``), so
    fifteen simultaneous calls are fifteen genuinely concurrent transactions.
    On SQLite's single-writer lock they serialise and the test trivially passes;
    on Postgres they race on the composite PK and the test proves the design
    survives that.

    Sabotage: if ``write_slide`` shared a single session-level lock on the
    deck row (not the slide row) the fifteen calls would serialise, the PK
    contention would disappear, and this test would still pass — but for the
    wrong reason.  The mechanism asserted here is PK-level row conflict, not
    a higher-level lock.  Removing the composite PK from ``SessionSlide``
    (``session.py``) would let two threads INSERT (session_id, 3) twice, and
    the ON CONFLICT upsert would silently keep one — which is wrong.  This
    test goes red on that change.
    """

    def test_fifteen_distinct_positions_persist(self, postgres_engine):
        _assert_postgres(postgres_engine)

        factory = _make_factory(postgres_engine)
        session_id = _seed_owner(factory)
        # Deck must exist so write_slide can find the owner.
        _seed_deck(factory, session_id)

        errors: List[Exception] = []
        lock = threading.Lock()
        barrier = threading.Barrier(15, timeout=30.0)

        def write(position: int) -> None:
            try:
                barrier.wait()  # all threads start together → real concurrency
                with _patched_db(factory):
                    writer = SlideWriter()
                    writer.write_slide(
                        session_id,
                        position,
                        f"<div>Slide {position}</div>",
                        modified_by="builder@example.com",
                    )
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60.0)

        assert not errors, (
            f"{len(errors)} of 15 concurrent write_slide calls raised:\n"
            + "\n".join(f"  {e!r}" for e in errors[:5])
        )

        db = factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .one()
            )
            rows = (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == owner.id)
                .all()
            )
        finally:
            db.close()

        positions = sorted(r.position for r in rows)
        assert positions == list(range(15)), (
            f"expected positions 0–14, found {positions}. "
            "At least one position was lost — the PK collision the row-per-slide "
            "design exists to prevent happened."
        )


# ---------------------------------------------------------------------------
# Assertion 2: version counter rejects a stale write with 409
# ---------------------------------------------------------------------------


class TestVersionCounterRejectsStaleWrite:
    """The deck-level optimistic lock surfaces as HTTP 409 through the route.

    This test is ROUTE-LEVEL.  ``save_slide_deck`` (``session_manager.py``) is
    the writer tested here — not ``write_deck_level_columns``, which is the
    graph's writer.  The distinction matters: the four production call sites of
    the deck-level writer (``tour.py``, ``chat_service.py``, ``nodes.py`` ×2)
    pass NO ``expected_version``, so they cannot trigger a 409 through that
    path.  ``save_slide_deck`` IS the path the frontend hits via the slide
    routes (reorder, insert, update, duplicate, delete), each of which forwards
    ``expected_version`` from the request body.

    Because the 409 is route-level, this test uses a FastAPI TestClient backed
    by the Postgres engine.  The suite's own framing ("a database, no model")
    is correct for every other test; this one is the exception, stated plainly
    here rather than hidden.
    """

    def test_stale_expected_version_returns_409(self, postgres_engine):
        _assert_postgres(postgres_engine)

        factory = _make_factory(postgres_engine)
        session_id = _seed_owner(factory)
        _seed_deck(factory, session_id, version=1)

        fake_db = _make_fake_db(factory)

        # Seed a slide row so reorder has something to work with.
        db = factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .one()
            )
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=0,
                    html="<div>Slide 0</div>",
                    slide_id=str(uuid.uuid4()),
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        # Override the FastAPI DI dependency to yield sessions from our engine.
        def override_get_db():
            d = factory()
            try:
                yield d
            finally:
                d.close()

        app.dependency_overrides[get_db] = override_get_db

        perm_ctx = PermissionContext(user_name="layer4@example.com")
        try:
            with (
                patch(_SM_DB, fake_db),
                patch(_AUTHZ_DB, fake_db),
                patch(_WRITER_DB, fake_db),
                patch(_SPEC_SYNC_DB, fake_db),
                patch("src.api.routes.slides.get_current_user", return_value="layer4@example.com"),
                patch("src.api.routes._authz.get_permission_context", return_value=perm_ctx),
                TestClient(app) as client,
            ):
                # Reorder with correct expected_version=1 → succeeds (version → 2).
                r1 = client.put(
                    "/api/slides/reorder",
                    json={
                        "session_id": session_id,
                        "new_order": [0],
                        "expected_version": 1,
                    },
                )
                assert r1.status_code == 200, (
                    f"first reorder should succeed but got {r1.status_code}: {r1.text}"
                )

                # Reorder again with the stale version (1 instead of 2) → 409.
                r2 = client.put(
                    "/api/slides/reorder",
                    json={
                        "session_id": session_id,
                        "new_order": [0],
                        "expected_version": 1,
                    },
                )
                assert r2.status_code == 409, (
                    f"stale expected_version=1 should be rejected with 409 but got "
                    f"{r2.status_code}: {r2.text}"
                )
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Assertion 3: two deck-level writes in one turn do not conflict
# ---------------------------------------------------------------------------


class TestTwoDeckLevelWritesInOneTurn:
    """``architect_node`` and ``deck_reviewer_node`` both call
    ``write_deck_level_columns`` in a single turn, and neither passes
    ``expected_version``.  They are sequential (not concurrent), so the design
    question is not whether they race but whether both bumps land: the turn
    starts with version N, the architect writes (N → N+1) and the reviewer
    writes again (N+1 → N+2).  A client holding version N after the turn sees
    the deck at N+2 and gets a 409 on its next save — which is precisely the
    human-versus-graph case below.

    Assertion here: version is N+2 after two sequential ``write_deck_level_columns``
    calls, with no conflict exception raised.
    """

    def test_two_sequential_deck_writes_double_bump(self, postgres_engine):
        _assert_postgres(postgres_engine)

        factory = _make_factory(postgres_engine)
        session_id = _seed_owner(factory)
        _seed_deck(factory, session_id, version=1)

        from src.api.services.deck_level_writer import write_deck_level_columns

        with _patched_db(factory):
            # First write: mimics architect_node (user_visible=True, no expected_version).
            result1 = write_deck_level_columns(
                session_id,
                title="Architect write",
                modified_by="architect@example.com",
                user_visible=True,
            )
            v_after_first = result1["version"]

            # Second write: mimics deck_reviewer_node (user_visible=True, no expected_version).
            result2 = write_deck_level_columns(
                session_id,
                title="Reviewer write",
                modified_by="reviewer@example.com",
                user_visible=True,
            )
            v_after_second = result2["version"]

        assert v_after_first == 2, (
            f"expected version 2 after first write, got {v_after_first}"
        )
        assert v_after_second == 3, (
            f"expected version 3 after second write, got {v_after_second}"
        )

        # Confirm via a fresh DB read.
        assert _deck_version(factory, session_id) == 3, (
            "DB does not reflect the double bump; at least one write was lost"
        )


# ---------------------------------------------------------------------------
# Assertion 4: release query is correct from a DIFFERENT PROCESS
# ---------------------------------------------------------------------------


class TestCrossProcessReleaseQuery:
    """``slides_since_cursor`` reads from rows, not from in-process buffers.

    Sabotage proof (buffer-instead-of-persist)
    ------------------------------------------
    1. Parent creates a session and does NOT write any slides (simulating
       "the builder buffered in process memory").
    2. A child subprocess — a genuinely different OS process with a different
       PID — connects to the same Postgres database and calls
       ``slides_since_cursor``.  It should find NO positions.  If the method
       read from an in-process cache the parent had built up, this would not
       be a valid test — but there is no such cache, and this explicitly
       proves it by construction.
    3. Parent WRITES slides to the database.
    4. Child subprocess is run again.  It should NOW find the positions.

    The PID check is a secondary discriminator: step 2/4 run in a distinct
    process (``os.getpid()`` in child differs from parent's PID), confirming
    the test cannot pass because the child read from the parent's heap.
    """

    def test_child_sees_nothing_before_write_and_everything_after(
        self, postgres_engine
    ):
        _assert_postgres(postgres_engine)

        factory = _make_factory(postgres_engine)
        session_id = _seed_owner(factory)
        _seed_deck(factory, session_id)

        # Extract the DB URL so the child process can connect to the same DB.
        # Use the engine's URL (already pointing at the throw-away test database).
        #
        # render_as_string(hide_password=False), NOT str(url): SQLAlchemy 2.0's
        # URL.__str__ is render_as_string(hide_password=True), which replaces the
        # password with '***'.  The child builds its own engine from this string,
        # so with str() it authenticates as the literal '***'.  That is invisible
        # on a laptop whose fixture URL is credential-free (trust auth: nothing to
        # mask) and fatal in CI, where TELLR_TEST_POSTGRES_URL is
        # postgresql+psycopg2://test:test@localhost:5432/test_db against
        # postgres:15 with scram auth.
        db_url = postgres_engine.url.render_as_string(hide_password=False)
        parent_pid = os.getpid()

        # -----------------------------------------------------------------------
        # Phase 1: parent has buffered, not persisted — child sees nothing.
        # -----------------------------------------------------------------------
        child_result_before = _run_slides_since_cursor_in_subprocess(
            db_url, session_id
        )
        assert child_result_before["ok"], (
            f"subprocess errored before writes: {child_result_before.get('error')}"
        )
        child_pid = child_result_before["pid"]
        assert child_pid != parent_pid, (
            f"subprocess PID {child_pid} equals parent PID {parent_pid}; "
            "the cross-process read is not actually cross-process"
        )
        assert child_result_before["positions"] == [], (
            f"child saw positions {child_result_before['positions']} before any "
            "slides were written — if this is non-empty, something is in the DB "
            "that should not be there, or slides_since_cursor is reading a cache"
        )

        # -----------------------------------------------------------------------
        # Phase 2: parent writes slides to the DB.
        # -----------------------------------------------------------------------
        with _patched_db(factory):
            writer = SlideWriter()
            for position in range(3):
                writer.write_slide(
                    session_id,
                    position,
                    f"<div>Slide {position}</div>",
                    modified_by="builder@example.com",
                )

        # -----------------------------------------------------------------------
        # Phase 3: child reads back the written slides from the DB.
        # -----------------------------------------------------------------------
        child_result_after = _run_slides_since_cursor_in_subprocess(
            db_url, session_id
        )
        assert child_result_after["ok"], (
            f"subprocess errored after writes: {child_result_after.get('error')}"
        )
        assert child_result_after["positions"] == [0, 1, 2], (
            f"child saw positions {child_result_after['positions']} after three "
            "writes; expected [0, 1, 2].  slides_since_cursor is either reading a "
            "stale or wrong database, or the write did not commit."
        )


def _run_slides_since_cursor_in_subprocess(
    db_url: str, session_id: str
) -> Dict:
    """Run ``slides_since_cursor`` in a fresh subprocess.  Returns a dict with:
    - ``ok``: True on success
    - ``positions``: sorted list of position integers the child found
    - ``pid``: the child's ``os.getpid()``
    - ``error``: error string if ``ok`` is False
    """
    import subprocess

    # The script runs in a fresh Python interpreter — no inherited module state,
    # no monkeypatches from the parent.  DATABASE_URL is the only thing that
    # connects it to the right database.
    script = (
        "import sys, os, json\n"
        f"sys.path.insert(0, {repr(str(_REPO_ROOT))})\n"
        "os.environ['DATABASE_URL'] = os.environ.get('_TELLR_TEST_DB_URL', '')\n"
        "os.environ['ENVIRONMENT'] = 'test'\n"
        "os.environ['DATABRICKS_HOST'] = ''\n"
        "os.environ['DATABRICKS_TOKEN'] = ''\n"
        "# Reset global singletons — the subprocess starts fresh anyway,\n"
        "# but be explicit so a future fork-mode runner cannot mask the test.\n"
        "import src.core.database as db_mod\n"
        "db_mod._engine = None\n"
        "db_mod._session_local = None\n"
        "import src.api.services.session_manager as sm_mod\n"
        "sm_mod._session_manager = None\n"
        "from src.api.services.session_manager import SessionManager\n"
        "sm = SessionManager()\n"
        "try:\n"
        "    result = sm.slides_since_cursor(os.environ['_TELLR_TEST_SID'])\n"
        "    print(json.dumps({'ok': True, 'positions': [r['position'] for r in result], 'pid': os.getpid()}))\n"
        "except Exception as e:\n"
        "    print(json.dumps({'ok': False, 'error': str(e), 'pid': os.getpid()}))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "_TELLR_TEST_DB_URL": db_url,
            "_TELLR_TEST_SID": session_id,
            "DATABASE_URL": db_url,
            "ENVIRONMENT": "test",
            "DATABRICKS_HOST": "",
            "DATABRICKS_TOKEN": "",
        },
    )

    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"subprocess produced no output (returncode={result.returncode}):\n"
            f"stderr: {result.stderr[:2000]}"
        )
    return json.loads(stdout)


# ---------------------------------------------------------------------------
# Assertion 5: checkpointer resumes in a second process
# ---------------------------------------------------------------------------


class TestCheckpointerResumesInSecondProcess:
    """``SqlAlchemyCheckpointSaver`` reads and writes through the shared engine.

    The checkpointer holds no connections of its own (``checkpointer.py``) —
    it opens one per call through the session factory, which is why a second
    worker can resume a turn the first worker started.

    ``thread_id`` is the ``session_id`` (``builder.py``).  A checkpoint
    stored in one process under ``thread_id=<session_id>`` must be readable by
    a second process that supplies the same ``thread_id``.  If it were not,
    a user's graph turn started by worker A and polled by worker B would
    produce no checkpoint to resume from — the conversation would be lost.
    """

    def test_checkpoint_written_in_parent_is_readable_in_child(
        self, postgres_engine
    ):
        _assert_postgres(postgres_engine)

        from src.core.checkpointer import SqlAlchemyCheckpointSaver
        from langgraph.checkpoint.base import Checkpoint

        factory = _make_factory(postgres_engine)

        # Build a saver that uses the test database.
        saver = SqlAlchemyCheckpointSaver(session_factory=factory)

        # Minimal checkpoint payload — we only need to prove it survives a
        # round-trip through the database and comes back to a fresh process.
        thread_id = f"l4-ckpt-{uuid.uuid4().hex[:12]}"
        payload_data = {"hello": "cross-process", "turn": 1}

        # Store the checkpoint in the parent process.
        checkpoint_id = _store_test_checkpoint(saver, thread_id, payload_data)

        # Extract the DB URL for the child.  render_as_string(hide_password=False),
        # not str(url) — see the note in TestCrossProcessReleaseQuery: str() masks
        # the password to '***' and the child cannot authenticate under CI's
        # password-authenticated URL.
        db_url = postgres_engine.url.render_as_string(hide_password=False)

        # Read back in a child subprocess.
        child_result = _read_checkpoint_in_subprocess(db_url, thread_id, checkpoint_id)

        assert child_result["ok"], (
            f"child failed to read checkpoint: {child_result.get('error')}"
        )
        assert child_result["pid"] != os.getpid(), (
            "the read-back ran in the same process as the write — "
            "the cross-process property is not proved"
        )
        assert child_result["data"] == payload_data, (
            f"checkpoint data mismatch:\n"
            f"  parent stored:  {payload_data!r}\n"
            f"  child read back: {child_result['data']!r}"
        )


def _store_test_checkpoint(
    saver: "SqlAlchemyCheckpointSaver",
    thread_id: str,
    data: dict,
) -> str:
    """Store a checkpoint and return its checkpoint_id."""
    from langgraph.checkpoint.base import create_checkpoint, empty_checkpoint
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    # Build a minimal checkpoint dict
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = create_checkpoint(empty_checkpoint(), {}, 1)
    # Embed our test data in the channel_values so we can verify it
    checkpoint = {**checkpoint, "channel_values": data}
    metadata = {"source": "layer4-test", "step": 1}

    result_config = saver.put(config, checkpoint, metadata, {})
    return result_config["configurable"]["checkpoint_id"]


def _read_checkpoint_in_subprocess(
    db_url: str, thread_id: str, checkpoint_id: str
) -> Dict:
    """Read a stored checkpoint from a fresh subprocess."""
    import subprocess

    script = (
        "import sys, os, json\n"
        f"sys.path.insert(0, {repr(str(_REPO_ROOT))})\n"
        "os.environ['DATABASE_URL'] = os.environ.get('_TELLR_TEST_DB_URL', '')\n"
        "os.environ['ENVIRONMENT'] = 'test'\n"
        "os.environ['DATABRICKS_HOST'] = ''\n"
        "os.environ['DATABRICKS_TOKEN'] = ''\n"
        "import src.core.database as db_mod\n"
        "db_mod._engine = None\n"
        "db_mod._session_local = None\n"
        "from sqlalchemy import create_engine\n"
        "from sqlalchemy.orm import sessionmaker\n"
        "from src.core.checkpointer import SqlAlchemyCheckpointSaver\n"
        "engine = create_engine(os.environ['_TELLR_TEST_DB_URL'], pool_pre_ping=True)\n"
        "factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)\n"
        "saver = SqlAlchemyCheckpointSaver(session_factory=factory)\n"
        "thread_id = os.environ['_TELLR_THREAD_ID']\n"
        "ckpt_id = os.environ['_TELLR_CKPT_ID']\n"
        "config = {'configurable': {'thread_id': thread_id, 'checkpoint_ns': '', 'checkpoint_id': ckpt_id}}\n"
        "try:\n"
        "    got = saver.get(config)\n"
        "    if got is None:\n"
        "        print(json.dumps({'ok': False, 'error': 'checkpoint not found', 'pid': os.getpid()}))\n"
        "    else:\n"
        "        # saver.get() returns the Checkpoint dict directly (not a tuple)\n"
        "        data = got.get('channel_values', {})\n"
        "        print(json.dumps({'ok': True, 'data': data, 'pid': os.getpid()}))\n"
        "except Exception as e:\n"
        "    print(json.dumps({'ok': False, 'error': str(e), 'pid': os.getpid()}))\n"
        "finally:\n"
        "    engine.dispose()\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "_TELLR_TEST_DB_URL": db_url,
            "_TELLR_THREAD_ID": thread_id,
            "_TELLR_CKPT_ID": checkpoint_id,
            "DATABASE_URL": db_url,
            "ENVIRONMENT": "test",
            "DATABRICKS_HOST": "",
            "DATABRICKS_TOKEN": "",
        },
    )

    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"checkpoint-read subprocess produced no output "
            f"(returncode={result.returncode}):\n"
            f"stderr: {result.stderr[:2000]}"
        )
    return json.loads(stdout)


# ---------------------------------------------------------------------------
# Assertion 6: four concurrent sweepers run at most one arc review
# ---------------------------------------------------------------------------


class TestFourConcurrentSweepersOneWins:
    """Four sweeper loops race one due marker; at most one claims it.

    This is the load-bearing version of the claim-exclusivity proof.  The
    SQLite version in ``tests/unit/test_spec_sync_sweeper.py`` cannot see the
    race — SQLite serialises all writes, so the outer ``.where(unclaimed)``
    predicate is never exercised.  On Postgres, four transactions truly overlap
    and the predicate is the only thing stopping four arc reviews of one deck.

    The mechanism:
    1. Claimer A holds the marker row's lock via an open transaction.
    2. B, C, D each run their candidate subquery (reads unclaimed → finds the
       row), then block waiting for A's row lock.
    3. Test asserts all three are SEEN waiting (not assumed).
    4. A commits.  PostgreSQL re-checks each blocked UPDATE's WHERE against
       A's committed tuple — the outer ``.where(unclaimed)`` fails for B/C/D
       because ``spec_dirty_claimed_at`` is now non-NULL.
    5. B, C, D each claim 0 rows.  Exactly one winner.

    Delete the outer ``.where(unclaimed)`` from ``claim_due_marker`` to see
    this test red with four winners.
    """

    def test_exactly_one_of_four_concurrent_sweepers_claims_the_marker(
        self, postgres_engine
    ):
        _assert_postgres(postgres_engine)

        # _ClaimGate, _await_lock_waiters, _thread_aware_db, _seed_owner_deck
        # and _WAIT_SECONDS come from postgres_concurrency_helpers (module-level
        # import at the top of this file).
        from src.services.spec_sync import DEBOUNCE_SECONDS, claim_due_marker
        from datetime import datetime, timedelta
        import contextlib

        factory = _make_factory(postgres_engine)
        deck = _seed_owner_deck(factory)
        now = datetime.utcnow()
        deck.set_marker(age_seconds=DEBOUNCE_SECONDS + 60, base=now)

        gate = _ClaimGate()
        gates = {"l4-claimer-A": gate}
        results: Dict = {}
        errors: List[Exception] = []
        tlock = threading.Lock()

        @contextlib.contextmanager
        def patched_for_thread(factory, gates):
            fake = _thread_aware_db(factory, gates)
            with (
                patch("src.services.spec_sync.get_db_session", fake),
                patch("src.api.services.session_manager.get_db_session", fake),
            ):
                yield

        def claimer():
            name = threading.current_thread().name
            try:
                with patched_for_thread(factory, gates):
                    outcome = claim_due_marker(now)
                with tlock:
                    results[name] = outcome
            except BaseException as exc:
                with tlock:
                    errors.append(exc)

        first = threading.Thread(target=claimer, name="l4-claimer-A")
        first.start()

        assert gate.executed.wait(timeout=_WAIT_SECONDS), (
            "claimer A never reached its commit gate; the lock was not taken, "
            "so no winner count here is evidence about exclusivity"
        )

        rest = [
            threading.Thread(target=claimer, name=f"l4-claimer-{n}")
            for n in ("B", "C", "D")
        ]
        for t in rest:
            t.start()

        peak_waiters = _await_lock_waiters(postgres_engine, 3)
        try:
            assert peak_waiters >= 3, (
                f"only {peak_waiters} of 3 later claimers were seen waiting on "
                "the lock; the transactions did not overlap claimer A's, so a "
                "single-winner result would be an artefact of serialisation"
            )
        finally:
            gate.release.set()

        first.join(timeout=_WAIT_SECONDS * 2)
        for t in rest:
            t.join(timeout=_WAIT_SECONDS * 2)

        assert not errors, (
            f"a claimer raised, so the winner count is not evidence: {errors!r}"
        )
        assert len(results) == 4, (
            f"only {sorted(results)} of 4 claimers finished"
        )

        winners = {name: out for name, out in results.items() if out is not None}
        assert len(winners) == 1, (
            f"{len(winners)} of 4 sweepers claimed the same marker "
            f"({sorted(winners)}); each would trigger an identical arc review, "
            "paying for it N times instead of once."
        )


# ---------------------------------------------------------------------------
# Human-versus-graph 409
# ---------------------------------------------------------------------------


class TestHumanVsGraph409:
    """The graph bumps ``deck.version`` twice per turn; the user's token goes stale.

    A WYSIWYG edit mid-turn:
    1. User fetches the deck and records its version (e.g. 1).
    2. The graph runs: ``architect_node`` writes (version 1→2), then
       ``deck_reviewer_node`` writes again (version 2→3).
    3. User submits their edit with ``expected_version=1``.
    4. The route rejects with 409: ``save_slide_deck`` sees version=3, expected=1.

    This is structurally different from assertion 2: that proves the lock
    works in isolation; this proves the graph's two sequential writes together
    produce the version gap a user actually experiences.

    This test is ROUTE-LEVEL (uses TestClient) — the same caveat as
    assertion 2, for the same reason.
    """

    def test_two_graph_writes_then_stale_human_save_returns_409(
        self, postgres_engine
    ):
        _assert_postgres(postgres_engine)

        factory = _make_factory(postgres_engine)
        session_id = _seed_owner(factory)
        _seed_deck(factory, session_id, version=1)

        fake_db = _make_fake_db(factory)

        # Seed one slide row so reorder has something to work with.
        db = factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .one()
            )
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=0,
                    html="<div>Slide 0</div>",
                    slide_id=str(uuid.uuid4()),
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        from src.api.services.deck_level_writer import write_deck_level_columns

        # --- Step 1: user reads version=1 ---
        user_version_before_turn = 1

        # --- Step 2: graph runs two deck-level writes ---
        with _patched_db(factory):
            # architect_node write
            write_deck_level_columns(
                session_id,
                title="Architect output",
                modified_by="architect@example.com",
                user_visible=True,
            )
            # deck_reviewer_node write
            write_deck_level_columns(
                session_id,
                title="Reviewer output",
                modified_by="reviewer@example.com",
                user_visible=True,
            )

        version_after_turn = _deck_version(factory, session_id)
        assert version_after_turn == 3, (
            f"expected version 3 after two graph writes, got {version_after_turn}"
        )

        def override_get_db():
            d = factory()
            try:
                yield d
            finally:
                d.close()

        app.dependency_overrides[get_db] = override_get_db
        perm_ctx = PermissionContext(user_name="layer4@example.com")

        try:
            with (
                patch(_SM_DB, fake_db),
                patch(_AUTHZ_DB, fake_db),
                patch(_WRITER_DB, fake_db),
                patch(_SPEC_SYNC_DB, fake_db),
                patch("src.api.routes.slides.get_current_user", return_value="layer4@example.com"),
                patch("src.api.routes._authz.get_permission_context", return_value=perm_ctx),
                TestClient(app) as client,
            ):
                # --- Step 3: user submits with stale version ---
                response = client.put(
                    "/api/slides/reorder",
                    json={
                        "session_id": session_id,
                        "new_order": [0],
                        "expected_version": user_version_before_turn,
                    },
                )

                assert response.status_code == 409, (
                    f"expected HTTP 409 when user submits with stale "
                    f"expected_version={user_version_before_turn} (deck is at "
                    f"version {version_after_turn} after two graph writes) but "
                    f"got {response.status_code}: {response.text}"
                )
        finally:
            app.dependency_overrides.clear()
