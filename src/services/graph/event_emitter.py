"""Turn-scoped event emitter for the graph, carried in a ``ContextVar``.

Why a ``ContextVar`` and not a state key
---------------------------------------
Nodes cannot queue events through ``GraphState``: the runtime **silently drops
undeclared keys**, and a ``queue.Queue`` is not serialisable through the
checkpointer anyway.  ``ContextVar``s were measured to survive both the thread
boundary and the ``Send`` fan-out — a var set before ``graph.invoke()`` was read
by all six fanned nodes, and a node-local ``.set()`` leaked neither back to the
parent nor sideways to a sibling.  LangChain fans out through
``ContextThreadPoolExecutor``, whose ``submit`` wraps every task in
``copy_context().run(...)``, which is what makes this work — and also why the
CALLER must ``contextvars.copy_context()`` before spawning its thread (ws4d's
obligation): the copy happens at spawn, so anything set afterwards is invisible.

Lifecycle — owned by ``invoke_graph``
-------------------------------------
The queue is created by the caller and handed to
:func:`~src.services.graph.builder.invoke_graph` as ``emitter=``, which calls
:func:`set_event_emitter` **before** ``graph.invoke()`` so the var is live for
the whole turn.  The dependency is therefore visible in a signature rather than
ambient: a caller in another module setting a variable this module's nodes read
is not a contract, and nothing would test it.

``invoke_graph`` sets the var on **every** invocation, including with
``emitter=None`` — that is the "reset or validate when resuming a turn in a new
process" rule.  Without the unconditional set, a second turn on a different
worker would keep queueing into the first process's queue forever.

With no emitter (the sweeper path, and every layer-1 test that asserts state
rather than events) nodes see ``None`` and **skip emission; they must not
raise.**  Emission is an optional side channel, never a precondition for
building a deck — which is why :func:`emit_event` swallows a failing ``put``
as well as an absent queue.

**The ContextVar must never enter ``GraphState``.**  An undeclared key read back
from state is silently dropped, so its presence there is undetectable until the
next turn inherits it from the checkpointer.
"""

from __future__ import annotations

import logging
import queue
from contextvars import ContextVar
from typing import Optional

from src.api.schemas.streaming import StreamEvent

logger = logging.getLogger(__name__)

#: The queue type nodes push into.  ``queue.Queue[StreamEvent]`` is the shape the
#: shipped streaming path already uses (``chat_service.py``'s
#: ``event_queue: queue.Queue[StreamEvent]``), so ws4d hands in the same object it
#: already drains for SSE.
StreamEventQueue = "queue.Queue[StreamEvent]"

event_emitter_var: ContextVar[Optional[queue.Queue]] = ContextVar(
    "graph_event_emitter", default=None
)


def set_event_emitter(emitter: Optional[queue.Queue]) -> None:
    """Install *emitter* as this context's event queue.

    ``None`` clears it, which is how ``invoke_graph`` resets a var inherited
    from an earlier turn in the same process.
    """
    event_emitter_var.set(emitter)


def get_event_emitter() -> Optional[queue.Queue]:
    """Return this context's event queue, or ``None`` when nothing is emitting."""
    return event_emitter_var.get()


def emit_event(event: StreamEvent) -> bool:
    """Queue *event* if an emitter is installed; never raise.

    Returns ``True`` when the event was queued, ``False`` when there was no
    emitter or the ``put`` failed.  Nodes call this rather than
    ``get_event_emitter().put(...)`` because that expression raises
    ``AttributeError`` on the ``emitter=None`` path, which every layer-1 state
    test and the ws4d sweeper take.
    """
    emitter = get_event_emitter()
    if emitter is None:
        return False
    try:
        emitter.put(event)
        return True
    except Exception:  # pragma: no cover - a full/closed queue must not fail a turn
        logger.warning("Graph event emission failed; continuing", exc_info=True)
        return False
