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

from src.api.schemas.streaming import StreamEvent, StreamEventType

logger = logging.getLogger(__name__)

#: The queue type nodes push into.  ``queue.Queue[StreamEvent]`` is the shape the
#: shipped streaming path already uses (``chat_service.py``'s
#: ``event_queue: queue.Queue[StreamEvent]``), so ws4d hands in the same object it
#: already drains for SSE.
StreamEventQueue = "queue.Queue[StreamEvent]"

event_emitter_var: ContextVar[Optional[queue.Queue]] = ContextVar(
    "graph_event_emitter", default=None
)

#: The SSE transport's slide cursor: the lowest position NOT yet released to this
#: turn's queue.  Held in a **one-element mutable list**, and that is load-bearing
#: (see :func:`advance_slide_cursor`).  Turn-scoped and in-process, exactly like
#: the queue it feeds — the polling transport's cursor is the client's instead,
#: which is why the release *rule* lives in a query over committed rows
#: (``SessionManager.slides_since_cursor``) and not in either cursor.
slide_cursor_var: ContextVar[Optional[list]] = ContextVar(
    "graph_slide_cursor", default=None
)


def set_event_emitter(emitter: Optional[queue.Queue]) -> None:
    """Install *emitter* as this context's event queue, and reset the slide cursor.

    ``None`` clears the queue, which is how ``invoke_graph`` resets a var
    inherited from an earlier turn in the same process.

    The slide cursor is reset **here** because this function is called on every
    ``invoke_graph`` invocation and nowhere else, so it is the one point that
    coincides exactly with a turn boundary.  Leaving a previous turn's cursor in
    place would mean turn 2 released nothing at all: its cursor already sits past
    every position turn 1 delivered.
    """
    event_emitter_var.set(emitter)
    slide_cursor_var.set([0])


def get_event_emitter() -> Optional[queue.Queue]:
    """Return this context's event queue, or ``None`` when nothing is emitting."""
    return event_emitter_var.get()


def get_slide_cursor() -> int:
    """Return the lowest slide position not yet released on this turn's queue.

    ``0`` when no turn has been started in this context, so a caller that never
    went through ``invoke_graph`` releases from the top of the deck rather than
    silently releasing nothing.
    """
    holder = slide_cursor_var.get()
    if not holder:
        return 0
    return int(holder[0])


def advance_slide_cursor(next_cursor: int) -> None:
    """Move the cursor forward to *next_cursor*; never backwards.

    **Mutates the holder in place and MUST keep doing so.**  LangChain fans nodes
    out through ``ContextThreadPoolExecutor``, whose ``submit`` wraps every task
    in ``copy_context().run(...)``, and LangGraph runs ordinary nodes through the
    same executor.  A ``ContextVar.set()`` inside a node therefore dies with that
    node's context copy — so ``slide_cursor_var.set([next_cursor])`` here would
    leave every wake reading ``0`` and re-emitting every slide released so far,
    once per foreman wake.  A copy shares the *object*, so ``holder[0] = ...``
    is visible to the parent context and to every sibling.
    """
    holder = slide_cursor_var.get()
    if holder is None:
        slide_cursor_var.set([int(next_cursor)])
        return
    holder[0] = max(int(holder[0]), int(next_cursor))


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


def emit_slide_ready(
    position: int, html: str, scripts: str = "", agent: Optional[str] = None
) -> bool:
    """Queue one ``slide_ready`` event for a committed slide; never raise.

    The whole point of ws4d D3: a fifteen-slide deck used to appear all at once
    because ``slides`` rides only on the terminal ``COMPLETE`` event.  This is the
    per-slide event that travels on the queue ``invoke_graph`` was handed.

    **Takes no queue.**  No graph node holds one and none can be given one — a
    ``queue.Queue`` is not serialisable through the checkpointer and ``GraphState``
    silently discards undeclared keys — so the queue reaches nodes through
    :data:`event_emitter_var` and by no other route.

    ``slide_cursor`` is stamped as ``position + 1``: the next position the client
    has NOT been sent.  That is the same number ``GET /chat/poll`` returns in its
    own ``slide_cursor`` field, so a client that starts on SSE and falls back to
    polling hands the value straight back without re-deriving it.

    ``metadata["node"]`` is stamped ``"release"`` because every other event the
    graph queues names the node that produced it, and ``tests/unit/
    test_graph_builder.py::test_every_fanned_node_queues_into_the_one_emitter``
    groups the whole turn's events by that key — an event without it made the
    turn's event stream un-attributable.  ``"release"`` names the reorder-buffer
    release rather than a node, which stays true whichever node calls this.

    Returns what :func:`emit_event` returns — ``True`` when the event was queued,
    ``False`` when there was no emitter.  Callers ignore it; emission is an
    optional side channel, never a precondition for building a deck.
    """
    return emit_event(
        StreamEvent(
            type=StreamEventType.SLIDE_READY,
            position=position,
            html=html,
            scripts=scripts,
            agent=agent,
            slide_cursor=position + 1,
            metadata={"node": "release"},
        )
    )
