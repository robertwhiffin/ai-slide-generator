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


#: The EXACT identity fields a production invocation may log.  The contract is the
#: #260 PRD amendment, recorded verbatim at
#: ``docs/superpowers/plans/2026-09-22-conversation-pins-runtime-v1.md:21``: the sink
#: contains "**only** graph version, release ID, role, revision ID, content hash,
#: outcome, and error class; **it never logs payload, prompt, output, session/user
#: ID**, tools, or slide HTML".  Five fields come off the identity; ``outcome`` and
#: ``error_class`` are the sink's own, making seven emitted in total.
#:
#: This is an ALLOW-LIST and must stay one.  #262 widened ``AgentInvocationIdentity``
#: with ``root_session_id``/``actor_session_id`` so a shared-deck mutation is
#: attributable — the plan requires them on the IDENTITY, never in the LOG, and
#: "session/user ID" is the category it names as prohibited.  Spreading
#: ``identity.__dict__`` emitted both, and the guard meant to catch that asserted
#: ``not hasattr(record, "session_id")`` — an exact NAME, so two differently-named
#: session IDs walked past it with the suite green (Ruling C-32, which is C-24's
#: failure class one level up: a guard checking a name rather than a property).
#: An allow-list cannot be walked past by naming: a new identity field is omitted
#: from the log by default and has to be added here deliberately.
_LOGGED_IDENTITY_FIELDS = (
    "graph_version",
    "graph_release_id",
    "agent_key",
    "agent_definition_revision_id",
    "content_hash",
)


class LoggingAgentInvocationIdentitySink:
    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger

    def _permitted(self, identity: AgentInvocationIdentity) -> dict[str, object]:
        """Project exactly the permitted identity fields — never the whole dataclass."""
        return {field: getattr(identity, field) for field in _LOGGED_IDENTITY_FIELDS}

    def invoke(
        self,
        identity: AgentInvocationIdentity,
        callback: Callable[[], BaseModel],
    ) -> BaseModel:
        try:
            result = callback()
        except Exception as exc:
            # Both branches project through _permitted.  A guard on only one of
            # them would leave the other free to leak, and the error branch is the
            # one that runs when something has already gone wrong.
            self._logger.info(
                "persisted_agent_invocation",
                extra={
                    **self._permitted(identity),
                    "outcome": "error",
                    "error_class": type(exc).__name__,
                },
            )
            raise
        self._logger.info(
            "persisted_agent_invocation",
            extra={
                **self._permitted(identity),
                "outcome": "success",
                "error_class": None,
            },
        )
        return result
