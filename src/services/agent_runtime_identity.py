"""Identity-only trace boundary for persisted AgentRuntime invocations."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable, Protocol

from src.services.agent_schema_types import JsonValue, ValidatedAgentOutput


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


@dataclass(frozen=True)
class AgentInvocationSuccess:
    """One *observed success*, distinct from the attempt recorded in ``calls``.

    ``calls`` is appended before the callback runs, so it records attempts and
    cannot distinguish an outcome.  Without this channel a test asserting that an
    invalid output "emits no success fields" passes vacuously, because no success
    field exists to be absent.  ``additional_fields`` is the registry's own frozen
    projection of the explicitly supplied, allowlisted optional values.
    """

    identity: AgentInvocationIdentity
    additional_fields: Mapping[str, JsonValue]


class AgentInvocationIdentitySink(Protocol):
    def invoke(
        self,
        identity: AgentInvocationIdentity,
        callback: Callable[[], ValidatedAgentOutput],
    ) -> ValidatedAgentOutput: ...


class RecordingAgentInvocationIdentitySink:
    """Test/compatibility sink recording attempts, successes and error classes.

    The three lists are deliberately separate outcome channels: ``calls`` is an
    attempt log appended *before* the callback, ``successes`` is appended only
    *after* the callback returns, and ``error_classes`` only when it raises.
    """

    def __init__(self) -> None:
        self.calls: list[AgentInvocationIdentity] = []
        self.successes: list[AgentInvocationSuccess] = []
        self.error_classes: list[str] = []

    def invoke(
        self,
        identity: AgentInvocationIdentity,
        callback: Callable[[], ValidatedAgentOutput],
    ) -> ValidatedAgentOutput:
        self.calls.append(identity)
        try:
            result = callback()
        except Exception as exc:
            self.error_classes.append(type(exc).__name__)
            raise
        self.successes.append(
            AgentInvocationSuccess(
                identity=identity,
                additional_fields=result.additional_fields,
            )
        )
        return result


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
    """Production sink logging identity, outcome, error class and optional values.

    Only the registry's allowlisted optional projection is logged, and only on the
    success path: the error record carries no success field at all, so prompt,
    payload and canonical model output never reach a log record.
    """

    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger

    def _permitted(self, identity: AgentInvocationIdentity) -> dict[str, object]:
        """Project exactly the permitted identity fields — never the whole dataclass."""
        return {field: getattr(identity, field) for field in _LOGGED_IDENTITY_FIELDS}

    def invoke(
        self,
        identity: AgentInvocationIdentity,
        callback: Callable[[], ValidatedAgentOutput],
    ) -> ValidatedAgentOutput:
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
                "additional_fields": result.additional_fields,
            },
        )
        return result
