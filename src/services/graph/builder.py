"""Graph assembly and the one entry point that runs a turn.

The topology, which IS the product
----------------------------------
::

    START           -------------> architect
    architect       --conditional-> {discuss: END, ask_data: data_analyst,
                                     build: foreman, edit: foreman,
                                     confirm_design_contract: END}
    data_analyst    --static------> architect
    foreman         --conditional-> [builder(Send), fixer, placeholder,
                                     deck_reviewer, END]
    builder         --conditional-> [build_reviewer(Send re-fan), placeholder]
    build_reviewer  --static------> foreman      # measured clean; NO router here
    fixer           --conditional-> [fix_reviewer, foreman]
    fix_reviewer    --static------> foreman
    placeholder     --static------> foreman
    deck_reviewer   --static------> END

Nine nodes.  ``START``/``END`` are the imported sentinels, never the strings.

Why ``build_reviewer -> foreman`` is STATIC — measured, both variants built and
run with 6 builders (positions 0 and 1 needing a fix):

===============================================  =================  =============
Approach                                         fixer invocations  foreman wakes
===============================================  =================  =============
wiring a ``reviewer_router`` ("fix"/"land")      **3**              **5**
static ``add_edge("build_reviewer", "foreman")``  **2**              **4**
===============================================  =================  =============

Cause: reviewers split their return between ``"fix"`` and ``"land"``, so
``fixer`` and ``foreman`` land in the **same superstep**; the foreman then
independently routes to the fixer on ``has_pending_fix``, creating an invocation
whose candidate set is already empty.  Re-measured while porting the decision:
because ``fix_target`` is single-writer with **no** reducer, the wired variant
puts ``fixer`` and ``fix_reviewer`` in one superstep and the runtime raises
``InvalidUpdateError: At key 'fix_target': Can receive only one value per step``
— **the turn dies rather than degrading.**  So the router is not defined at all;
a tested-but-unreachable router misleads about the topology.

**One deviation from the plan's edge list, measured here.**  The plan draws
``builder -> foreman`` for a branch with nothing to review; that wakes the foreman
in the same superstep as its siblings' reviewers, and the deck reviewer then runs
TWICE on any turn where one builder fails.  The destination is ``placeholder``
instead — the full trace is in ``build_reviewer_refan_router``'s docstring.

Two adjacent facts that wiring revealed, worth knowing before tuning anything:
with the clean wiring fix rounds **serialise** one position per superstep (15
objective findings = 15 sequential rounds), and ``has_pending_fix`` preempts
dispatch entirely, so a 31-slide deck stops dispatching new builders until every
fix completes.

Configuration
-------------
``thread_id`` is passed on every invoke — omitting it raises ``ValueError:
Checkpointer requires one or more of the following 'configurable' keys``.
``max_concurrency`` is ``CAP``, the belt to the scheduler's braces.  **No
``recursion_limit``**: the installed default is 10007, and the superseded plan's
~50 would have made the graph fail *earlier* than shipping no value.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from src.core.checkpointer import get_checkpointer
from src.core.user_context import get_current_user
from src.services.foreman_service import CAP
from src.services.graph.event_emitter import set_event_emitter
from src.services.graph.nodes import (
    architect_node,
    build_reviewer_node,
    builder_node,
    data_analyst_node,
    deck_reviewer_node,
    fix_reviewer_node,
    fixer_node,
    foreman_node,
    placeholder_node,
)
from src.services.graph.routers import (
    architect_router,
    build_reviewer_refan_router,
    fixer_router,
    foreman_router,
)
from src.services.graph.state import GraphState

logger = logging.getLogger(__name__)

_graph_lock = threading.Lock()
_compiled_graph = None


def build_graph(checkpointer: Any = None):
    """Assemble and compile the graph.

    Args:
        checkpointer: Override for the shared checkpointer.  Production passes
            nothing and gets ``get_checkpointer()``; a compiled-graph test suite
            passes a file-backed SQLite saver (an in-memory saver on a
            ``StaticPool`` hands two Pregel worker threads one connection and
            segfaults the interpreter).

    Returns:
        The compiled graph.
    """
    graph = StateGraph(GraphState)

    graph.add_node("architect", architect_node)
    graph.add_node("data_analyst", data_analyst_node)
    graph.add_node("foreman", foreman_node)
    graph.add_node("builder", builder_node)
    graph.add_node("build_reviewer", build_reviewer_node)
    graph.add_node("fixer", fixer_node)
    graph.add_node("fix_reviewer", fix_reviewer_node)
    graph.add_node("placeholder", placeholder_node)
    graph.add_node("deck_reviewer", deck_reviewer_node)

    graph.add_edge(START, "architect")

    # One conditional-edge set per node, and no static edge alongside it: a
    # static add_edge from the same source gives duplicate conflicting edges and
    # a GraphRecursionError.
    graph.add_conditional_edges(
        "architect",
        architect_router,
        {"data_analyst": "data_analyst", "foreman": "foreman", END: END},
    )
    graph.add_conditional_edges(
        "foreman",
        foreman_router,
        {
            "builder": "builder",
            "fixer": "fixer",
            "placeholder": "placeholder",
            "deck_reviewer": "deck_reviewer",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "builder",
        build_reviewer_refan_router,
        # "placeholder", not "foreman", for a branch with nothing to review — see
        # build_reviewer_refan_router's docstring for the measured trace. Routing
        # a placeheld branch to the foreman wakes it in the reviewers' superstep
        # and the deck reviewer then runs TWICE.
        {"build_reviewer": "build_reviewer", "placeholder": "placeholder"},
    )
    graph.add_conditional_edges(
        "fixer",
        fixer_router,
        {"fix_reviewer": "fix_reviewer", "foreman": "foreman"},
    )

    graph.add_edge("data_analyst", "architect")
    graph.add_edge("build_reviewer", "foreman")
    graph.add_edge("fix_reviewer", "foreman")
    graph.add_edge("placeholder", "foreman")
    graph.add_edge("deck_reviewer", END)

    return graph.compile(
        checkpointer=checkpointer if checkpointer is not None else get_checkpointer()
    )


def get_graph():
    """The process-wide compiled graph, built on first use."""
    global _compiled_graph
    if _compiled_graph is None:
        with _graph_lock:
            if _compiled_graph is None:
                _compiled_graph = build_graph()
    return _compiled_graph


def invoke_graph(
    session_id: str,
    initial: Optional[Dict[str, Any]] = None,
    *,
    emitter: Any = None,
    principal: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one turn of the graph for *session_id*.

    Args:
        session_id: The session whose deck this turn builds.  Also the
            checkpointer's ``thread_id``, so turn 2 resumes the same thread and
            the ``turn_id`` below is what resets turn-scoped state.
        initial: Extra state to seed the turn with — in practice the user's
            request on ``architect_message``.  Only keys ``GraphState`` declares
            survive; the runtime silently drops the rest.
        emitter: The caller's event queue, or ``None``.  Installed in a
            ``ContextVar`` **before** ``invoke`` so it is live for the whole turn,
            including inside every ``Send``-fanned branch.  With ``None`` nodes
            skip emission and must not raise: emission is an optional side
            channel, never a precondition for building a deck.
        principal: The acting user, for callers with no request context (ws4d's
            sweeper passes the marker's ``spec_dirty_by``).

    A fresh ``turn_id`` is minted per turn — it is the discriminator every
    turn-scoped reducer compares, so reusing one would let turn 2 inherit turn
    1's landed positions and go straight to deck review having built nothing.

    ``principal or get_current_user()`` is resolved **once**, here, into
    ``initiated_by``, and every node reads it from state.  A node calling
    ``get_current_user()`` itself works today and breaks the first time the graph
    is invoked from a bare thread — and ``write_slide`` with
    ``modified_by=None`` leaves the author NULL on an INSERT, silently.

    The emitter is set on every invocation, ``None`` included: that is the reset
    a turn resumed in a new process needs, or events queue into the first
    process's queue forever.
    """
    turn_id = uuid.uuid4().hex
    initiated_by = principal or get_current_user()

    set_event_emitter(emitter)

    state: Dict[str, Any] = dict(initial or {})
    state.update(
        {
            "session_id": session_id,
            "turn_id": turn_id,
            "initiated_by": initiated_by,
        }
    )

    config = {
        "configurable": {"thread_id": session_id},
        "max_concurrency": CAP,
    }

    logger.info(
        "Invoking deck graph",
        extra={
            "session_id": session_id,
            "turn_id": turn_id,
            "has_emitter": emitter is not None,
        },
    )
    return get_graph().invoke(state, config)
