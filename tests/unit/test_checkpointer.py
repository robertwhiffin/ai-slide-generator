"""The SQLAlchemy checkpoint saver, against REAL databases — never a mock.

Mocking the database is precisely what would hide the failure this saver exists
to avoid: a saver that holds its own raw connection never traverses the engine's
``do_connect`` listener, so on Lakebase its writes start failing about an hour
into a deployment, in production only. So the SQLite half below runs against a
real SQLite engine, and the ``live``/``postgres`` half against a real PostgreSQL
with a ``do_connect`` listener attached, asserting the write actually went
through it.

The two tables are built by ``_migrate_graph_checkpoints`` ALONE — deliberately
not by ``Base.metadata.create_all()``. create_all would build them from the ORM
models, and then disabling the migration's body would leave every test here
green: the measured PR1 defect where an idempotency test stayed green with its
migration turned off.

All fixture data is synthetic.
"""

import os
import uuid
from typing import Annotated, Any, TypedDict

import pytest
from langgraph.checkpoint.base import CheckpointTuple, empty_checkpoint
from langgraph.graph import END, START, StateGraph
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

import src.core.checkpointer as checkpointer_module
from src.core.checkpointer import SqlAlchemyCheckpointSaver, get_checkpointer
from src.core.database import Base, _migrate_graph_checkpoints, _run_migrations

_TABLES = ("graph_checkpoints", "graph_checkpoint_writes")


def _build_checkpoint_tables(engine) -> None:
    """Create the two tables through the MIGRATION only, then fail loudly if absent."""
    with engine.begin() as conn:
        # schema=None, as _run_migrations passes on an unqualified deployment.
        _migrate_graph_checkpoints(conn, None)

    tables = set(inspect(engine).get_table_names())
    missing = [name for name in _TABLES if name not in tables]
    assert not missing, (
        f"_migrate_graph_checkpoints did not create {missing}; found {sorted(tables)}"
    )


def _config(thread_id: str, checkpoint_id: str | None = None, ns: str = "") -> dict:
    configurable: dict[str, Any] = {"thread_id": thread_id, "checkpoint_ns": ns}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


def _checkpoint(channel_values: dict | None = None) -> dict:
    """A fresh checkpoint. ``empty_checkpoint`` mints a monotonic UUID6 id."""
    checkpoint = empty_checkpoint()
    if channel_values is not None:
        checkpoint["channel_values"] = channel_values
    return checkpoint


def _metadata(step: int = 0, **extra: Any) -> dict:
    return {"source": "loop", "step": step, "parents": {}, **extra}


def _count(engine, table_name: str, thread_id: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM {table_name} WHERE thread_id = :t"),
            {"t": thread_id},
        ).scalar_one()


@pytest.fixture()
def saver_engine(tmp_path):
    """FILE-BACKED SQLite carrying ONLY the migration-built checkpoint tables.

    MEASURED TRAP — copy this form, not the usual one. The house pattern for a
    SQLite test engine in this repo is ``sqlite:///:memory:`` with a
    ``StaticPool``, and it CANNOT be used for a compiled-graph test. A graph's
    sync Pregel loop calls the saver from more than one thread at a time — one
    running ``put`` via ``_checkpointer_put_after_previous`` while another runs
    ``put_writes`` — and ``StaticPool`` hands both threads the SAME sqlite3
    connection. That is not merely an error: it took down the interpreter with
    ``Fatal Python error: Segmentation fault``, reproducibly, when this file was
    first written.

    A file-backed database with ordinary pooling gives each thread its own
    connection onto one database, which is what makes the graph tests below
    safe. ``check_same_thread=False`` permits the cross-thread handoff and
    ``timeout=30`` absorbs SQLite's writer lock instead of failing the test.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'checkpoints.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    _build_checkpoint_tables(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def saver(saver_engine):
    """A saver over an explicitly injected factory (fast path for behaviour tests)."""
    return SqlAlchemyCheckpointSaver(
        session_factory=sessionmaker(bind=saver_engine, expire_on_commit=False)
    )


class TestTheMigrationBuildsTheSchema:
    def test_migration_creates_both_tables_with_their_keys(self, saver_engine):
        inspector = inspect(saver_engine)

        checkpoints_pk = inspector.get_pk_constraint("graph_checkpoints")
        assert list(checkpoints_pk["constrained_columns"]) == [
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
        ]
        writes_pk = inspector.get_pk_constraint("graph_checkpoint_writes")
        assert list(writes_pk["constrained_columns"]) == [
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "idx",
        ]

        # parent_checkpoint_id is what parent_config is built from — assert the
        # column exists rather than discovering its absence via a linking test.
        columns = {c["name"] for c in inspector.get_columns("graph_checkpoints")}
        assert "parent_checkpoint_id" in columns

        # No secondary index on either table, by design: every lookup the saver
        # makes is a leading-column prefix of the primary key, which the PK btree
        # already serves. An index over a strict PK prefix could never be
        # preferred over it, so adding one back would be dead weight.
        assert inspector.get_indexes("graph_checkpoints") == []
        assert inspector.get_indexes("graph_checkpoint_writes") == []

    def test_migration_is_idempotent(self, saver_engine):
        _build_checkpoint_tables(saver_engine)  # a second run must not raise
        _build_checkpoint_tables(saver_engine)

    def test_run_migrations_rebuilds_the_tables_after_they_are_dropped(self):
        """Proves the step is WIRED INTO the chain, not merely importable.

        create_all first (production ordering, so config_profiles exists and
        _run_migrations does not bail early), then drop the two tables so that
        only _migrate_graph_checkpoints can put them back.
        """
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            import src.database.models  # noqa: F401 - register every model

            Base.metadata.create_all(bind=engine)
            with engine.begin() as conn:
                for name in _TABLES:
                    conn.execute(text(f"DROP TABLE {name}"))
            assert not set(inspect(engine).get_table_names()) & set(_TABLES)

            _run_migrations(engine)

            tables = set(inspect(engine).get_table_names())
            assert set(_TABLES) <= tables, sorted(tables)
        finally:
            engine.dispose()


class TestRoundTrip:
    def test_put_then_get_tuple_survives_sets_int_keyed_dicts_and_none(self, saver):
        """The shapes GraphState actually stores, which json.dumps would reject."""
        values = {
            "a_set": {"architect", "reviewer"},
            "int_keys": {1: "slide-one", 2: "slide-two"},
            "nothing": None,
        }
        checkpoint = _checkpoint(values)
        saver.put(_config("thread-shapes"), checkpoint, _metadata(), {})

        tup = saver.get_tuple(_config("thread-shapes"))
        assert isinstance(tup, CheckpointTuple)
        recovered = tup.checkpoint["channel_values"]

        assert isinstance(recovered["a_set"], set)
        assert recovered["a_set"] == {"architect", "reviewer"}

        assert [type(k) for k in recovered["int_keys"]] == [int, int]
        assert recovered["int_keys"] == {1: "slide-one", 2: "slide-two"}

        assert "nothing" in recovered
        assert recovered["nothing"] is None

    def test_metadata_round_trips(self, saver):
        saver.put(
            _config("thread-meta"), _checkpoint(), _metadata(step=7, writes=None), {}
        )
        tup = saver.get_tuple(_config("thread-meta"))
        assert tup.metadata["step"] == 7
        assert tup.metadata["source"] == "loop"
        assert tup.metadata["writes"] is None

    def test_get_tuple_returns_none_for_an_unknown_thread(self, saver):
        assert saver.get_tuple(_config("thread-that-never-was")) is None

    def test_put_is_an_upsert_on_the_same_checkpoint_id(self, saver):
        checkpoint = _checkpoint({"stage": "first"})
        saver.put(_config("thread-upsert"), checkpoint, _metadata(), {})
        checkpoint["channel_values"] = {"stage": "second"}
        saver.put(_config("thread-upsert"), checkpoint, _metadata(step=1), {})

        assert len(list(saver.list(_config("thread-upsert")))) == 1
        tup = saver.get_tuple(_config("thread-upsert"))
        assert tup.checkpoint["channel_values"] == {"stage": "second"}


class TestCheckpointSelectionAndChaining:
    @pytest.fixture()
    def chain(self, saver):
        """Three chained checkpoints on one thread, oldest first."""
        thread_id = "thread-chain"
        first = _checkpoint({"n": 1})
        saver.put(_config(thread_id), first, _metadata(step=0), {})
        second = _checkpoint({"n": 2})
        saver.put(_config(thread_id, first["id"]), second, _metadata(step=1), {})
        third = _checkpoint({"n": 3})
        saver.put(_config(thread_id, second["id"]), third, _metadata(step=2), {})
        return thread_id, [first, second, third]

    def test_get_tuple_without_a_checkpoint_id_returns_the_latest(self, saver, chain):
        thread_id, checkpoints = chain
        tup = saver.get_tuple(_config(thread_id))
        assert tup.checkpoint["id"] == checkpoints[-1]["id"]
        assert tup.checkpoint["channel_values"] == {"n": 3}

    def test_get_tuple_with_a_checkpoint_id_returns_that_one(self, saver, chain):
        thread_id, checkpoints = chain
        tup = saver.get_tuple(_config(thread_id, checkpoints[0]["id"]))
        assert tup.checkpoint["id"] == checkpoints[0]["id"]
        assert tup.checkpoint["channel_values"] == {"n": 1}

    def test_parent_config_links_successive_checkpoints(self, saver, chain):
        thread_id, checkpoints = chain
        first, second, third = checkpoints

        latest = saver.get_tuple(_config(thread_id))
        assert latest.parent_config["configurable"]["checkpoint_id"] == second["id"]

        middle = saver.get_tuple(_config(thread_id, second["id"]))
        assert middle.parent_config["configurable"]["checkpoint_id"] == first["id"]

        root = saver.get_tuple(_config(thread_id, first["id"]))
        assert root.parent_config is None

    def test_list_is_newest_first(self, saver, chain):
        thread_id, checkpoints = chain
        listed = [t.checkpoint["id"] for t in saver.list(_config(thread_id))]
        assert listed == [c["id"] for c in reversed(checkpoints)]

    def test_list_honours_limit(self, saver, chain):
        thread_id, checkpoints = chain
        listed = [t.checkpoint["id"] for t in saver.list(_config(thread_id), limit=2)]
        assert listed == [checkpoints[2]["id"], checkpoints[1]["id"]]

    def test_list_honours_before(self, saver, chain):
        thread_id, checkpoints = chain
        listed = [
            t.checkpoint["id"]
            for t in saver.list(
                _config(thread_id), before=_config(thread_id, checkpoints[1]["id"])
            )
        ]
        assert listed == [checkpoints[0]["id"]]

    def test_list_honours_a_metadata_filter_with_a_limit(self, saver, chain):
        thread_id, _ = chain
        listed = list(saver.list(_config(thread_id), filter={"step": 1}, limit=5))
        assert [t.metadata["step"] for t in listed] == [1]


class TestPendingWrites:
    def test_put_writes_replays_as_pending_writes(self, saver):
        thread_id = "thread-writes"
        checkpoint = _checkpoint({"n": 1})
        saver.put(_config(thread_id), checkpoint, _metadata(), {})
        config = _config(thread_id, checkpoint["id"])

        saver.put_writes(
            config,
            [("slides", {3, 4}), ("notes", None)],
            "task-alpha",
            task_path="~__pregel_pull:architect",
        )

        pending = saver.get_tuple(config).pending_writes
        assert pending == [
            ("task-alpha", "slides", {3, 4}),
            ("task-alpha", "notes", None),
        ]

    def test_a_positive_index_write_is_kept_not_overwritten(self, saver):
        """Matches InMemorySaver: the first writer for a (task_id, idx) wins."""
        thread_id = "thread-keep"
        checkpoint = _checkpoint()
        saver.put(_config(thread_id), checkpoint, _metadata(), {})
        config = _config(thread_id, checkpoint["id"])

        saver.put_writes(config, [("slides", "first")], "task-alpha")
        saver.put_writes(config, [("slides", "second")], "task-alpha")

        assert saver.get_tuple(config).pending_writes == [
            ("task-alpha", "slides", "first")
        ]

    def test_a_control_channel_write_is_replaced(self, saver):
        """__interrupt__ maps to idx -3 in WRITES_IDX_MAP and must overwrite."""
        thread_id = "thread-replace"
        checkpoint = _checkpoint()
        saver.put(_config(thread_id), checkpoint, _metadata(), {})
        config = _config(thread_id, checkpoint["id"])

        saver.put_writes(config, [("__interrupt__", "first")], "task-alpha")
        saver.put_writes(config, [("__interrupt__", "second")], "task-alpha")

        assert saver.get_tuple(config).pending_writes == [
            ("task-alpha", "__interrupt__", "second")
        ]


class TestThreadIsolationAndDeletion:
    @pytest.fixture()
    def two_threads(self, saver):
        ids = {}
        for thread_id, value in (("thread-a", "alpha"), ("thread-b", "beta")):
            checkpoint = _checkpoint({"who": value})
            saver.put(_config(thread_id), checkpoint, _metadata(), {})
            saver.put_writes(
                _config(thread_id, checkpoint["id"]),
                [("slides", value)],
                f"task-{value}",
            )
            ids[thread_id] = checkpoint["id"]
        return ids

    def test_threads_are_isolated(self, saver, two_threads):
        assert saver.get_tuple(_config("thread-a")).checkpoint["channel_values"] == {
            "who": "alpha"
        }
        assert saver.get_tuple(_config("thread-b")).checkpoint["channel_values"] == {
            "who": "beta"
        }
        assert len(list(saver.list(_config("thread-a")))) == 1
        assert saver.get_tuple(
            _config("thread-a", two_threads["thread-a"])
        ).pending_writes == [("task-alpha", "slides", "alpha")]
        # Asking thread-a for thread-b's checkpoint id finds nothing.
        assert saver.get_tuple(_config("thread-a", two_threads["thread-b"])) is None

    def test_delete_thread_clears_both_tables_and_only_that_thread(
        self, saver, saver_engine, two_threads
    ):
        assert _count(saver_engine, "graph_checkpoints", "thread-a") == 1
        assert _count(saver_engine, "graph_checkpoint_writes", "thread-a") == 1

        saver.delete_thread("thread-a")

        assert _count(saver_engine, "graph_checkpoints", "thread-a") == 0
        assert _count(saver_engine, "graph_checkpoint_writes", "thread-a") == 0
        assert saver.get_tuple(_config("thread-a")) is None

        assert _count(saver_engine, "graph_checkpoints", "thread-b") == 1
        assert _count(saver_engine, "graph_checkpoint_writes", "thread-b") == 1
        assert saver.get_tuple(_config("thread-b")) is not None


class TestTheRealSessionHelperPath:
    """No injected factory — so the double call on get_session_local is exercised.

    ``get_session_local()`` returns a ``sessionmaker``, NOT a ``Session``, so the
    saver has to call it twice. A fixture that injects a factory hides that, which
    is how the bug survived review once; the patch below stands in for the real
    function by returning a factory, exactly as it does.
    """

    def test_the_saver_resolves_its_factory_from_get_session_local(
        self, saver_engine, monkeypatch
    ):
        factory = sessionmaker(bind=saver_engine, expire_on_commit=False)
        calls: list[int] = []

        def fake_get_session_local():
            calls.append(1)
            return factory  # a FACTORY, like the real function

        monkeypatch.setattr(
            checkpointer_module, "get_session_local", fake_get_session_local
        )

        saver = SqlAlchemyCheckpointSaver()  # nothing injected
        checkpoint = _checkpoint({"n": 1})
        saver.put(_config("thread-real-helper"), checkpoint, _metadata(), {})
        tup = saver.get_tuple(_config("thread-real-helper"))

        assert tup is not None
        assert tup.checkpoint["channel_values"] == {"n": 1}
        assert calls, "the saver never went through get_session_local"


class TestGetCheckpointer:
    def test_get_checkpointer_is_process_wide(self, monkeypatch):
        monkeypatch.setattr(checkpointer_module, "_checkpointer", None)
        first = get_checkpointer()
        second = get_checkpointer()
        assert first is second
        assert isinstance(first, SqlAlchemyCheckpointSaver)

    def test_constructing_the_saver_does_not_build_an_engine(self, monkeypatch):
        """A per-session saver against a pool_size=80 engine would exhaust the pool.

        The process-wide instance is only safe if creating it is inert, so assert
        the constructor never resolves a session factory.
        """
        def explode():  # pragma: no cover - must never be called
            raise AssertionError("get_session_local() called during construction")

        monkeypatch.setattr(checkpointer_module, "get_session_local", explode)
        monkeypatch.setattr(checkpointer_module, "_checkpointer", None)
        assert get_checkpointer() is not None


class _GraphState(TypedDict):
    log: Annotated[list, lambda a, b: a + b]


def _two_node_graph():
    builder = StateGraph(_GraphState)
    builder.add_node("architect", lambda state: {"log": ["architect"]})
    builder.add_node("reviewer", lambda state: {"log": ["reviewer"]})
    builder.add_edge(START, "architect")
    builder.add_edge("architect", "reviewer")
    builder.add_edge("reviewer", END)
    return builder


class TestACompiledGraph:
    def test_invoking_without_a_thread_id_raises_value_error(self, saver):
        graph = _two_node_graph().compile(checkpointer=saver)
        with pytest.raises(ValueError, match="thread_id"):
            graph.invoke({"log": []})

    def test_the_graph_resumes_from_this_saver_across_two_invokes(self, saver):
        graph = _two_node_graph().compile(
            checkpointer=saver, interrupt_before=["reviewer"]
        )
        config = _config("thread-graph")

        first = graph.invoke({"log": []}, config)
        assert first["log"] == ["architect"]

        # A separate invoke, with no input: everything it needs to carry on comes
        # back out of the checkpointer.
        second = graph.invoke(None, config)
        assert second["log"] == ["architect", "reviewer"]

        assert graph.get_state(config).next == ()

    def test_delete_thread_clears_a_graphs_history(self, saver):
        graph = _two_node_graph().compile(checkpointer=saver)
        config = _config("thread-graph-delete")
        graph.invoke({"log": []}, config)
        assert list(saver.list(config))

        saver.delete_thread("thread-graph-delete")

        assert list(saver.list(config)) == []
        assert saver.get_tuple(config) is None


# ---------------------------------------------------------------------------
# Live half: a real PostgreSQL, with a do_connect listener attached.
#
# This is the only test that can observe the property the saver exists for —
# that a write is carried by a connection the ENGINE issued, and therefore one
# that passed through the do_connect listener that injects Lakebase's OAuth
# token. It self-skips when no PostgreSQL is reachable (the pattern in
# tests/unit/test_design_system_partial_name_index_postgres.py), per-test rather
# than module-level so the SQLite half above still runs.
#
# It is NOT proof against Lakebase itself: local PostgreSQL has no OAuth token
# and no 50-minute refresh. The real proof is an app that stays up past a token
# refresh with graph traffic on it.
# ---------------------------------------------------------------------------

_ADMIN_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL",
    "postgresql+psycopg2://localhost:5432/postgres",
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.mark.live
@pytest.mark.postgres
class TestAgainstRealPostgres:
    @pytest.fixture()
    def pg(self):
        """A throwaway PostgreSQL database, plus the connections its engine issued.

        NullPool so every session checks out a genuinely new DBAPI connection and
        the do_connect listener is observably traversed each time, rather than a
        pooled connection being handed back without firing it.
        """
        if not _postgres_available():  # pragma: no cover - environment-dependent
            pytest.skip(
                f"no PostgreSQL reachable at {_ADMIN_URL}; set "
                "TELLR_TEST_POSTGRES_URL to run the checkpointer's live suite"
            )

        db_name = f"tellr_ckpt_{uuid.uuid4().hex[:16]}"
        admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        engine = create_engine(
            make_url(_ADMIN_URL).set(database=db_name), poolclass=NullPool
        )
        issued: list[dict] = []

        from sqlalchemy import event

        @event.listens_for(engine, "do_connect")
        def record_connect(dialect, conn_rec, cargs, cparams):
            # Stands in for src.core.database.provide_token, which is where
            # Lakebase's OAuth token is injected. Returning None lets the normal
            # connect proceed.
            issued.append(cparams)
            return None

        _build_checkpoint_tables(engine)
        issued.clear()
        try:
            yield engine, issued
        finally:
            engine.dispose()
            with admin.connect() as conn:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :db AND pid <> pg_backend_pid()"
                    ),
                    {"db": db_name},
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            admin.dispose()

    def test_a_write_lands_on_an_engine_issued_connection(self, pg, monkeypatch):
        engine, issued = pg
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        monkeypatch.setattr(
            checkpointer_module, "get_session_local", lambda: factory
        )

        saver = SqlAlchemyCheckpointSaver()  # real helper path, no injection
        checkpoint = _checkpoint(
            {"a_set": {"architect"}, "int_keys": {1: "one"}, "nothing": None}
        )
        saver.put(_config("thread-live"), checkpoint, _metadata(), {})

        assert issued, (
            "no connection was issued by the engine — the write bypassed the "
            "do_connect listener, which on Lakebase is the only path the OAuth "
            "token travels"
        )

        # And it round-trips off a real BYTEA column. (psycopg2 returns bytea as a
        # memoryview; loads_typed accepts that as-is, so this is a round-trip
        # assertion, not a driver-coercion one.)
        tup = saver.get_tuple(_config("thread-live"))
        assert tup is not None
        assert tup.checkpoint["channel_values"]["a_set"] == {"architect"}
        assert tup.checkpoint["channel_values"]["int_keys"] == {1: "one"}
        assert tup.checkpoint["channel_values"]["nothing"] is None

        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT COUNT(*) FROM graph_checkpoints WHERE thread_id = :t"),
                {"t": "thread-live"},
            ).scalar_one() == 1

    def test_writes_and_deletion_work_against_postgres(self, pg, monkeypatch):
        engine, _ = pg
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        monkeypatch.setattr(
            checkpointer_module, "get_session_local", lambda: factory
        )

        saver = SqlAlchemyCheckpointSaver()
        checkpoint = _checkpoint({"n": 1})
        saver.put(_config("thread-live-writes"), checkpoint, _metadata(), {})
        config = _config("thread-live-writes", checkpoint["id"])
        saver.put_writes(config, [("slides", {5}), ("__interrupt__", "halt")], "task-1")

        pending = dict(
            (channel, value) for _task, channel, value in saver.get_tuple(config).pending_writes
        )
        assert pending == {"slides": {5}, "__interrupt__": "halt"}

        saver.delete_thread("thread-live-writes")
        assert _count(engine, "graph_checkpoints", "thread-live-writes") == 0
        assert _count(engine, "graph_checkpoint_writes", "thread-live-writes") == 0
