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
