"""The tools one agent invocation may call, and the budget it may spend on them.

An :class:`AgentToolset` rides the invocation's ``AgentAssemblyContext``.  When
one is present, ``AgentRuntime`` runs its tool-calling loop instead of the single
structured-output call: the model is bound to the output schema plus every tool
here, and code (not the prompt) enforces the call count and the wall-clock
budget.  The toolset is per-invocation state: the loop counts calls and keeps
every :class:`ToolAccessError` on it, so the node that built it can tell the
user which permission is missing.

This module is deliberately dependency-light (no LangChain, no runtime import),
so the runtime can name the type without an import cycle.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel

ToolAccessKind = Literal["missing_scope", "access_denied"]


class ToolAccessError(Exception):
    """A tool was refused for the signed-in user: a missing OAuth scope or a denied grant.

    The loop records it on :attr:`AgentToolset.access_errors` and answers the
    model in-band; it is never a provider failure.
    """

    def __init__(self, kind: ToolAccessKind, tool_name: str, message: str) -> None:
        super().__init__(message)
        self.kind: ToolAccessKind = kind
        self.tool_name = tool_name
        self.message = message


class AgentTool(Protocol):
    """One tool the model may call.  ``name``, ``description`` and ``args_schema``
    are what the model is shown; ``run`` gets the parsed arguments."""

    name: str
    description: str
    args_schema: type[BaseModel]

    def run(self, args: BaseModel, *, remaining_seconds: float) -> str: ...


@dataclass
class AgentToolset:
    """The tools and the code-enforced budget for one agent invocation.

    The clock starts at :meth:`start` (the loop calls it), not at construction:
    the node may build the toolset well before the model is first called.
    """

    tools: tuple[AgentTool, ...]
    max_calls: int = 3
    budget_seconds: float = 300.0
    clock: Callable[[], float] = time.monotonic
    calls_made: int = field(default=0, init=False)
    access_errors: list[ToolAccessError] = field(default_factory=list, init=False)
    _started_at: float | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        self._started_at = self.clock()

    def remaining_seconds(self) -> float:
        """Seconds left of the budget; the whole budget until :meth:`start` runs."""
        if self._started_at is None:
            return self.budget_seconds
        return self.budget_seconds - (self.clock() - self._started_at)

    def exhausted(self) -> bool:
        return self.calls_made >= self.max_calls or self.remaining_seconds() <= 0
