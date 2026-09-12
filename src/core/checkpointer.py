"""SQLAlchemy-backed LangGraph checkpoint saver, and its process-wide accessor.

WHY THIS IS CUSTOM RATHER THAN ``langgraph-checkpoint-postgres`` — this is a
CORRECTNESS requirement, not a preference. ``PostgresSaver(conn, …)`` holds a
LIVE psycopg connection of its own. On Lakebase the OAuth token reaches a
connection ONLY through ``provide_token``, the SQLAlchemy ``do_connect``
listener registered on the ENGINE in :func:`src.core.database._create_engine`
(``src/core/database.py:305``), refreshed on a 50-minute timer against a
one-hour token expiry. A saver holding its own raw connection never traverses
that listener, so its writes begin failing roughly an hour into every
deployment — **in production only, and invisibly to any test that mocks the
database.** This saver therefore takes every connection from the application's
own session factory, :func:`src.core.database.get_session_local`, so each
connection passes through the ``do_connect`` listener and carries a fresh
token. That is the entire reason this module exists.

Because the failure mode is "a mocked database cannot see it", the unit suite
for this module runs against a REAL SQLite engine and the live half against a
real PostgreSQL — never a mock.

SYNC ONLY. ``BaseCheckpointSaver``'s ``a*`` methods raise
``NotImplementedError`` and Tellr's generation path is sync end to end, so the
graph is driven with ``invoke``/``stream`` and never ``ainvoke``/``astream``.
One consequence is recorded here because it decides a later PR's stall design:
**``Send(timeout=)`` is unusable.** The ``timeout`` parameter DOES exist on
``Send`` in langgraph 1.2.10 — this is not a missing-parameter problem — but a
compiled graph fanning out into a SYNC node REJECTS it at run time, on
``invoke``::

    ValueError: Node timeouts are only supported for async nodes because sync
    Python execution cannot be safely cancelled in-process. Node 'worker' is
    sync.

So a per-worker deadline has to come from somewhere other than ``Send``.

THE RAW SQL BELOW IS DELIBERATELY SCHEMA-UNQUALIFIED, following the explicit
NOTE in ``src/core/encryption.py`` (lines 46-54): this module must also run
against SQLite (unit tests — no schemas) and schema-less local Postgres. On
Lakebase the bare names resolve to ``<LAKEBASE_SCHEMA>.graph_checkpoints`` and
``<LAKEBASE_SCHEMA>.graph_checkpoint_writes`` ONLY because
``_get_database_url`` appends ``options=-csearch_path%3D<schema>`` to the
connection URL (``src/core/database.py:239,259``) and the ``do_connect``
listener injects just the password, preserving those options. There is no
``LAKEBASE_SCHEMA`` symbol to import — ``database.py`` reads the env var
locally. If that search_path mechanism ever changes these statements would
silently target ``public.graph_checkpoints`` — keep this coupling in mind.
The migration helper ``_migrate_graph_checkpoints`` in ``database.py`` follows
the OPPOSITE rule and qualifies with the ``_qual()`` callable that
``_run_migrations`` threads in, like every one of its siblings. The two rules
differ because the migration is handed a schema and the saver is not.

IMPLEMENTED SURFACE — exactly the five methods a compiled graph calls, all of
which raise ``NotImplementedError`` on the base class: ``get_tuple``, ``list``,
``put``, ``put_writes``, ``delete_thread``.

``get_next_version`` is NOT overridden, and not because it raises: probed on
langgraph-checkpoint 4.1.1 the base class ships a WORKING integer increment
(``None -> 1``, ``3 -> 4``) and raises only when ``current`` is a ``str``. It
is omitted because nothing calls it. ``prune``, ``copy_thread``,
``delete_for_runs``, ``get_delta_channel_history``, ``with_allowlist`` and
every ``a*`` method are left on the base class for the same reason: nothing
calls them. ``get_delta_channel_history`` additionally COULD NOT be
implemented as this saver stores state today — see ``put`` for why, and for
what starts failing if a ``DeltaChannel`` ever enters the graph state.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    PendingWrite,
    RunnableConfig,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from sqlalchemy import text

from src.core.database import get_session_local

logger = logging.getLogger(__name__)

# --- Raw SQL -----------------------------------------------------------------
# Deliberately schema-UNQUALIFIED; see the module docstring and the NOTE in
# src/core/encryption.py that this follows.

_CHECKPOINT_COLUMNS = (
    "checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint_type, "
    "checkpoint_blob, metadata_type, metadata_blob"
)

_UPSERT_CHECKPOINT = text(
    "INSERT INTO graph_checkpoints (thread_id, checkpoint_ns, checkpoint_id, "
    "parent_checkpoint_id, checkpoint_type, checkpoint_blob, metadata_type, "
    "metadata_blob, created_at) VALUES (:thread_id, :checkpoint_ns, "
    ":checkpoint_id, :parent_checkpoint_id, :checkpoint_type, :checkpoint_blob, "
    ":metadata_type, :metadata_blob, CURRENT_TIMESTAMP) "
    "ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET "
    "parent_checkpoint_id = excluded.parent_checkpoint_id, "
    "checkpoint_type = excluded.checkpoint_type, "
    "checkpoint_blob = excluded.checkpoint_blob, "
    "metadata_type = excluded.metadata_type, "
    "metadata_blob = excluded.metadata_blob"
)

_SELECT_CHECKPOINT_BY_ID = text(
    f"SELECT {_CHECKPOINT_COLUMNS} FROM graph_checkpoints "
    "WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns "
    "AND checkpoint_id = :checkpoint_id"
)

_SELECT_LATEST_CHECKPOINT = text(
    f"SELECT {_CHECKPOINT_COLUMNS} FROM graph_checkpoints "
    "WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns "
    # checkpoint ids are UUID6 — lexicographically ordered by creation time,
    # which is the same ordering langgraph's own savers rely on.
    "ORDER BY checkpoint_id DESC LIMIT 1"
)

_SELECT_WRITES = text(
    "SELECT task_id, channel, value_type, value_blob FROM graph_checkpoint_writes "
    "WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns "
    "AND checkpoint_id = :checkpoint_id ORDER BY task_id, idx"
)

_INSERT_WRITE_COLUMNS = (
    "INSERT INTO graph_checkpoint_writes (thread_id, checkpoint_ns, "
    "checkpoint_id, task_id, idx, channel, value_type, value_blob, task_path, "
    "created_at) VALUES (:thread_id, :checkpoint_ns, :checkpoint_id, :task_id, "
    ":idx, :channel, :value_type, :value_blob, :task_path, CURRENT_TIMESTAMP) "
)

_WRITE_CONFLICT = (
    "ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) "
)

# A positive idx is a real channel write: the first writer for that
# (task_id, idx) wins, matching InMemorySaver, which skips a duplicate.
_INSERT_WRITE_KEEP = text(_INSERT_WRITE_COLUMNS + _WRITE_CONFLICT + "DO NOTHING")

# A negative idx is one of langgraph's control channels (WRITES_IDX_MAP:
# __error__ -1, __scheduled__ -2, __interrupt__ -3, __resume__ -4). Those are
# overwritten rather than kept, again matching InMemorySaver.
_INSERT_WRITE_REPLACE = text(
    _INSERT_WRITE_COLUMNS + _WRITE_CONFLICT + "DO UPDATE SET "
    "channel = excluded.channel, value_type = excluded.value_type, "
    "value_blob = excluded.value_blob, task_path = excluded.task_path"
)

_DELETE_THREAD_CHECKPOINTS = text(
    "DELETE FROM graph_checkpoints WHERE thread_id = :thread_id"
)
_DELETE_THREAD_WRITES = text(
    "DELETE FROM graph_checkpoint_writes WHERE thread_id = :thread_id"
)


def _as_bytes(value: Any) -> bytes:
    """Normalise a blob column to ``bytes``.

    The two drivers differ here: psycopg2 hands ``bytea`` back as a
    ``memoryview``, while sqlite3 returns ``bytes``.
    ``JsonPlusSerializer.loads_typed`` accepts EITHER — measured against real
    PostgreSQL 14.20, where a ``memoryview`` straight out of psycopg2
    deserialised correctly — so this coercion is **not load-bearing today** and
    fixes no observed failure. It is belt-and-braces normalisation, kept so the
    rest of the module can rely on one concrete type regardless of driver, and
    so a future serialiser that is less tolerant than the current one cannot
    turn a driver detail into a production-only bug. Do not cite it as a fix
    for a real defect.
    """
    return value if isinstance(value, bytes) else bytes(value)


class SqlAlchemyCheckpointSaver(BaseCheckpointSaver[str]):
    """Persist LangGraph checkpoints through the app's own session factory.

    Args:
        session_factory: a ``sessionmaker`` to open sessions from. Defaults to
            the application factory resolved lazily per call, which is the
            production path — see the module docstring on why the ENGINE, not a
            held connection, has to be the source of connections. Passing one
            explicitly is for tests that need a throwaway engine.
        serde: serializer override; defaults to the base class's
            ``JsonPlusSerializer``, which survives sets, int-keyed dicts and
            other shapes ``json.dumps`` would reject.
    """

    def __init__(self, *, session_factory: Any | None = None, serde: Any | None = None):
        super().__init__(serde=serde)
        # Deliberately NOT resolved here: constructing the saver must not build
        # an engine, so get_checkpointer() stays inert until first use.
        self._session_factory = session_factory

    # -- session plumbing ---------------------------------------------------

    @contextmanager
    def _session(self) -> Iterator[Any]:
        """Yield a ``Session``, committing on success and rolling back on error.

        TRAP: ``get_session_local()`` returns a ``sessionmaker`` — a FACTORY,
        not a ``Session``. ``with get_session_local() as s:`` raises
        ``TypeError: 'sessionmaker' object does not support the context manager
        protocol``. It has to be called TWICE, which is why ``factory`` is
        resolved and then invoked below. Mirrors
        ``src.core.database.get_db_session``.
        """
        factory = self._session_factory or get_session_local()
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _config_key(config: RunnableConfig) -> tuple[str, str]:
        configurable = config["configurable"]
        return configurable["thread_id"], configurable.get("checkpoint_ns", "")

    @staticmethod
    def _config_for(thread_id: str, checkpoint_ns: str, checkpoint_id: str) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def _pending_writes(
        self, session: Any, thread_id: str, checkpoint_ns: str, checkpoint_id: str
    ) -> list[PendingWrite]:
        rows = session.execute(
            _SELECT_WRITES,
            {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            },
        ).fetchall()
        return [
            (
                row.task_id,
                row.channel,
                self.serde.loads_typed((row.value_type, _as_bytes(row.value_blob))),
            )
            for row in rows
        ]

    def _tuple_from_row(
        self, session: Any, thread_id: str, row: Any
    ) -> CheckpointTuple:
        checkpoint: Checkpoint = self.serde.loads_typed(
            (row.checkpoint_type, _as_bytes(row.checkpoint_blob))
        )
        metadata: CheckpointMetadata = self.serde.loads_typed(
            (row.metadata_type, _as_bytes(row.metadata_blob))
        )
        return CheckpointTuple(
            config=self._config_for(thread_id, row.checkpoint_ns, row.checkpoint_id),
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=(
                self._config_for(thread_id, row.checkpoint_ns, row.parent_checkpoint_id)
                if row.parent_checkpoint_id
                else None
            ),
            pending_writes=self._pending_writes(
                session, thread_id, row.checkpoint_ns, row.checkpoint_id
            ),
        )

    # -- BaseCheckpointSaver ------------------------------------------------

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Fetch one checkpoint: the one named by ``checkpoint_id``, else the latest."""
        thread_id, checkpoint_ns = self._config_key(config)
        checkpoint_id = get_checkpoint_id(config)
        params = {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}
        with self._session() as session:
            if checkpoint_id:
                row = session.execute(
                    _SELECT_CHECKPOINT_BY_ID, {**params, "checkpoint_id": checkpoint_id}
                ).fetchone()
            else:
                row = session.execute(_SELECT_LATEST_CHECKPOINT, params).fetchone()
            if row is None:
                return None
            return self._tuple_from_row(session, thread_id, row)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002 - base class signature
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """Yield checkpoints NEWEST FIRST, honouring ``filter``/``before``/``limit``.

        ``filter`` matches metadata keys, which live inside a serialised blob, so
        it is applied in Python after loading. The SQL ``LIMIT`` is therefore
        only pushed down when no ``filter`` is given; the Python-side countdown
        enforces ``limit`` in both cases.
        """
        sql = f"SELECT thread_id, {_CHECKPOINT_COLUMNS} FROM graph_checkpoints"
        clauses: list[str] = []
        params: dict[str, Any] = {}

        if config is not None:
            thread_id, checkpoint_ns = self._config_key(config)
            clauses.append("thread_id = :thread_id")
            params["thread_id"] = thread_id
            if config["configurable"].get("checkpoint_ns") is not None:
                clauses.append("checkpoint_ns = :checkpoint_ns")
                params["checkpoint_ns"] = checkpoint_ns
            if config_checkpoint_id := get_checkpoint_id(config):
                clauses.append("checkpoint_id = :config_checkpoint_id")
                params["config_checkpoint_id"] = config_checkpoint_id

        if before is not None and (before_id := get_checkpoint_id(before)):
            clauses.append("checkpoint_id < :before_id")
            params["before_id"] = before_id

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY checkpoint_id DESC"
        if limit is not None and not filter:
            sql += " LIMIT :limit"
            params["limit"] = limit

        remaining = limit
        with self._session() as session:
            rows = session.execute(text(sql), params).fetchall()
            for row in rows:
                if remaining is not None and remaining <= 0:
                    return
                metadata = self.serde.loads_typed(
                    (row.metadata_type, _as_bytes(row.metadata_blob))
                )
                if filter and not all(
                    metadata.get(key) == value for key, value in filter.items()
                ):
                    continue
                if remaining is not None:
                    remaining -= 1
                yield self._tuple_from_row(session, row.thread_id, row)

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store one checkpoint and return the config that identifies it.

        The whole checkpoint — ``channel_values`` included — is stored as a
        single ``dumps_typed`` blob. ``new_versions`` is part of the base
        signature and is intentionally unused: it exists for savers that split
        channel values into a separate per-version blob table, an optimisation
        this saver does not make, so there is nothing here for it to key.

        KNOWN CONSEQUENCE OF THAT CHOICE, accepted deliberately: because there
        is no per-channel, per-version blob table, this saver cannot reconstruct
        a channel's ancestor history, so ``get_delta_channel_history`` is left
        raising ``NotImplementedError`` on the base class. Nothing calls it
        today. **If a later change puts a ``DeltaChannel`` into the graph
        state, Pregel WILL start calling it and the graph will raise at run
        time.** The fix then is to add the per-version blob table (see
        ``InMemorySaver.blobs`` and its ``_load_blobs`` for the shape) and
        override the method — not to work around it at the call site.

        The incoming ``config``'s ``checkpoint_id`` is the PARENT of the
        checkpoint being written — that is what ``parent_config`` is later built
        from, and what chains a thread's checkpoints together.
        """
        thread_id, checkpoint_ns = self._config_key(config)
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_blob = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata)
        )
        with self._session() as session:
            session.execute(
                _UPSERT_CHECKPOINT,
                {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint["id"],
                    "parent_checkpoint_id": config["configurable"].get("checkpoint_id"),
                    "checkpoint_type": checkpoint_type,
                    "checkpoint_blob": checkpoint_blob,
                    "metadata_type": metadata_type,
                    "metadata_blob": metadata_blob,
                },
            )
        return self._config_for(thread_id, checkpoint_ns, checkpoint["id"])

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store the intermediate writes of one task against a checkpoint."""
        thread_id, checkpoint_ns = self._config_key(config)
        checkpoint_id = config["configurable"]["checkpoint_id"]
        with self._session() as session:
            for offset, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, offset)
                value_type, value_blob = self.serde.dumps_typed(value)
                statement = _INSERT_WRITE_KEEP if idx >= 0 else _INSERT_WRITE_REPLACE
                session.execute(
                    statement,
                    {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "task_id": task_id,
                        "idx": idx,
                        "channel": channel,
                        "value_type": value_type,
                        "value_blob": value_blob,
                        "task_path": task_path,
                    },
                )

    def delete_thread(self, thread_id: str) -> None:
        """Delete every checkpoint AND every pending write for one thread."""
        with self._session() as session:
            session.execute(_DELETE_THREAD_WRITES, {"thread_id": thread_id})
            session.execute(_DELETE_THREAD_CHECKPOINTS, {"thread_id": thread_id})
        logger.info("Cleared graph checkpoints for thread %s", thread_id)


# One saver per PROCESS. A per-request or per-session saver would open a
# connection of its own for every session against an engine already configured
# with pool_size=80 (src/core/database.py), so the pool would be the thing that
# ran out. The saver is stateless apart from its serializer, so sharing it is
# safe; every call opens and closes its own session.
_checkpointer: SqlAlchemyCheckpointSaver | None = None


def get_checkpointer() -> SqlAlchemyCheckpointSaver:
    """Return the process-wide checkpoint saver, creating it on first use."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = SqlAlchemyCheckpointSaver()
    return _checkpointer
