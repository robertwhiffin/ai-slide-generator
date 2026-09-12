"""LangGraph checkpoint tables — graph state persisted between supersteps.

Two tables, shaped by exactly what ``BaseCheckpointSaver`` has to round-trip:

* ``graph_checkpoints`` — one row per checkpoint, keyed
  ``(thread_id, checkpoint_ns, checkpoint_id)``. Holds the serialised checkpoint
  and its metadata as opaque blobs, each alongside the serde *type tag* it was
  written with: ``JsonPlusSerializer.dumps_typed`` returns ``(type, bytes)`` and
  ``loads_typed`` needs both halves back. ``parent_checkpoint_id`` is the link
  that lets ``CheckpointTuple.parent_config`` chain successive checkpoints, and
  therefore what makes time-travel and resume work at all.
* ``graph_checkpoint_writes`` — one row per pending write, keyed
  ``(thread_id, checkpoint_ns, checkpoint_id, task_id, idx)``. These replay as
  ``CheckpointTuple.pending_writes``. ``idx`` is SIGNED: langgraph's
  ``WRITES_IDX_MAP`` assigns -1..-4 to the ``__error__``, ``__scheduled__``,
  ``__interrupt__`` and ``__resume__`` channels, so an unsigned column would
  silently drop interrupt/resume state.

The saver that reads and writes them is :mod:`src.core.checkpointer`; the
migration that guarantees they exist is
``src.core.database._migrate_graph_checkpoints``.

``created_at`` carries no Python-side default on purpose, mirroring
:class:`src.database.models.encryption_key.EncryptionKey`: every insert path is
raw SQL that supplies ``CURRENT_TIMESTAMP`` explicitly, so a default would be
dead code — and the codebase-conventional ``datetime.utcnow`` is deprecated on
Python 3.12+.
"""

from sqlalchemy import Column, DateTime, Index, Integer, LargeBinary, String, Text

from src.core.database import Base

#: Lookup index names. ``_migrate_graph_checkpoints`` re-derives its raw
#: ``CREATE INDEX IF NOT EXISTS`` statements from the ``Index`` objects declared
#: below, so these names are declared once, here, and the migration cannot drift
#: from the ORM.
GRAPH_CHECKPOINTS_THREAD_INDEX = "ix_graph_checkpoints_thread_ns"
GRAPH_CHECKPOINT_WRITES_CHECKPOINT_INDEX = "ix_graph_checkpoint_writes_checkpoint"


class GraphCheckpoint(Base):
    """One LangGraph checkpoint: a graph's state at the end of a superstep."""

    __tablename__ = "graph_checkpoints"

    # Composite primary key: (thread_id, checkpoint_ns, checkpoint_id).
    thread_id = Column(String(255), primary_key=True, nullable=False)
    # Uncapped: a checkpoint namespace is a "|"-joined path of subgraph node
    # names and task ids, so nested fan-out can make it long. "" for the root
    # graph, which is why it is empty-string-defaulted rather than nullable —
    # a NULL primary-key component is not storable.
    checkpoint_ns = Column(Text, primary_key=True, nullable=False, default="")
    checkpoint_id = Column(String(255), primary_key=True, nullable=False)

    # The chain link CheckpointTuple.parent_config is built from. NULL on the
    # first checkpoint of a thread.
    parent_checkpoint_id = Column(String(255), nullable=True)

    # dumps_typed() halves: the type tag, then the payload.
    checkpoint_type = Column(String(50), nullable=False)
    checkpoint_blob = Column(LargeBinary, nullable=False)
    metadata_type = Column(String(50), nullable=False)
    # NOT named `metadata`: that attribute is reserved on a declarative class.
    metadata_blob = Column(LargeBinary, nullable=False)

    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index(GRAPH_CHECKPOINTS_THREAD_INDEX, "thread_id", "checkpoint_ns"),
    )

    def __repr__(self) -> str:  # blobs are opaque; never print them
        return (
            f"<GraphCheckpoint(thread_id='{self.thread_id}', "
            f"checkpoint_ns='{self.checkpoint_ns}', "
            f"checkpoint_id='{self.checkpoint_id}')>"
        )


class GraphCheckpointWrite(Base):
    """One pending write against a checkpoint, replayed as ``pending_writes``."""

    __tablename__ = "graph_checkpoint_writes"

    # Composite primary key:
    # (thread_id, checkpoint_ns, checkpoint_id, task_id, idx).
    thread_id = Column(String(255), primary_key=True, nullable=False)
    checkpoint_ns = Column(Text, primary_key=True, nullable=False, default="")
    checkpoint_id = Column(String(255), primary_key=True, nullable=False)
    task_id = Column(String(255), primary_key=True, nullable=False)
    # Signed: WRITES_IDX_MAP maps __error__/__scheduled__/__interrupt__/
    # __resume__ to -1..-4.
    idx = Column(Integer, primary_key=True, nullable=False)

    channel = Column(String(255), nullable=False)
    value_type = Column(String(50), nullable=False)
    value_blob = Column(LargeBinary, nullable=False)
    # Uncapped for the same reason as checkpoint_ns: it is a task path.
    task_path = Column(Text, nullable=False, default="")

    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index(
            GRAPH_CHECKPOINT_WRITES_CHECKPOINT_INDEX,
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
        ),
    )

    def __repr__(self) -> str:  # blobs are opaque; never print them
        return (
            f"<GraphCheckpointWrite(thread_id='{self.thread_id}', "
            f"checkpoint_id='{self.checkpoint_id}', task_id='{self.task_id}', "
            f"idx={self.idx}, channel='{self.channel}')>"
        )
