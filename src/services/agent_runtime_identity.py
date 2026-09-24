"""Identity-only trace boundary for persisted AgentRuntime invocations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class AgentInvocationIdentity:
    graph_version: int
    graph_release_id: int
    agent_key: str
    agent_definition_revision_id: int
    content_hash: str
    # Collaboration provenance (#262 Task 4).  ``root_session_id`` is the
    # deck-OWNING session and ``actor_session_id`` the session the turn runs as;
    # on a contributor's turn they differ, and ``graph_release_id`` above is then
    # the ACTOR's pinned release, never the root's.  **IDs never select the
    # release** — ``AgentRuntime.run``'s second argument does — so these two are
    # inert for resolution and exist only to make a mutation attributable.
    #
    # Neither is Optional: a conversation with no persisted pin never reaches a
    # node at all (``invoke_graph`` raises ``ConversationPinMissingError`` first),
    # so there is no live path that would need a null identity (Ruling C-3).
    # They carry a default only because every caller outside the graph — the
    # runtime's own suites and the agentic gates — constructs
    # ``AgentAssemblyContext`` with one argument; the thing that stops a
    # *production* call site tracing blank is structural, and is asserted by
    # ``TestNoCallSiteMayTraceBlank`` in ``tests/unit/test_graph_nodes.py``.
    root_session_id: str = ""
    actor_session_id: str = ""


class AgentInvocationIdentitySink(Protocol):
    def invoke(
        self,
        identity: AgentInvocationIdentity,
        callback: Callable[[], BaseModel],
    ) -> BaseModel: ...


class RecordingAgentInvocationIdentitySink:
    def __init__(self) -> None:
        self.calls: list[AgentInvocationIdentity] = []
        self.error_classes: list[str] = []

    def invoke(
        self,
        identity: AgentInvocationIdentity,
        callback: Callable[[], BaseModel],
    ) -> BaseModel:
        self.calls.append(identity)
        try:
            return callback()
        except Exception as exc:
            self.error_classes.append(type(exc).__name__)
            raise


class LoggingAgentInvocationIdentitySink:
    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger

    def invoke(
        self,
        identity: AgentInvocationIdentity,
        callback: Callable[[], BaseModel],
    ) -> BaseModel:
        try:
            result = callback()
        except Exception as exc:
            self._logger.info(
                "persisted_agent_invocation",
                extra={
                    **identity.__dict__,
                    "outcome": "error",
                    "error_class": type(exc).__name__,
                },
            )
            raise
        self._logger.info(
            "persisted_agent_invocation",
            extra={
                **identity.__dict__,
                "outcome": "success",
                "error_class": None,
            },
        )
        return result
