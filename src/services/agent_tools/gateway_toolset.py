"""Build an agent's AI Gateway MCP tools from a deck's ``gateway_mcp`` entries.

``build_gateway_tools`` joins the entries to the admin registry, lists each
service's tools as the signed-in user (in parallel, one worker per connection),
applies each allowlist, names the tools for the model, and reports every
connection it could not bind as a :class:`GatewayFailure`.

This module must not import ``src.core.skills``.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Final, Literal

from src.api.schemas.agent_config import GatewayMcpTool, MCPTool
from src.core.scope_errors import consent_message, oauth_scopes_from_token, scopes_grant
from src.services.agent_tools.gateway_mcp import (
    ConnectionMcpClient,
    GatewayMcpClient,
    GatewayMcpError,
    GatewayToolSpec,
)
from src.services.agent_tools.gateway_tool import (
    GatewayMcpAgentTool,
    GatewayToolContext,
    make_image_saver,
)
from src.services.agent_tools.toolset import AgentToolset
from src.services.gateway_mcp_registry import GatewayConnection

logger = logging.getLogger(__name__)

ARCHITECT_GATEWAY_MAX_CALLS: Final = 12
ARCHITECT_GATEWAY_BUDGET_SECONDS: Final = 360.0
ANALYST_GATEWAY_MAX_CALLS: Final = 6
ANALYST_GATEWAY_BUDGET_SECONDS: Final = 300.0
GATEWAY_TURN_DEADLINE_SECONDS: Final = 700.0

_GATEWAY_SCOPE: Final = "ai-gateway"
_MAX_NAME_LEN: Final = 64
#: Names the model already sees: Genie One's tool and the output-schema tools the
#: runtime loop binds beside the others.
_RESERVED_NAMES: Final = frozenset({"genie", "ArchitectOutput", "AnalystOutput", "generate_image"})
#: Genie Agent tools are named ``genie_agent_*``; no Gateway or connection tool may take that space.
_RESERVED_PREFIX: Final = "genie_agent_"
_UNSAFE_RE: Final = re.compile(r"[^A-Za-z0-9_-]")

FailureKind = Literal[
    "sign_in_required", "missing_scope", "access_denied", "not_found", "unavailable", "removed"
]


@dataclass(frozen=True)
class GatewayFailure:
    display_name: str
    service_name: str
    kind: FailureKind
    message: str | None
    sign_in_url: str | None
    source: Literal["gateway", "connection"] = "gateway"


@dataclass
class GatewayToolsetBuild:
    tools: tuple[GatewayMcpAgentTool, ...]
    failures: tuple[GatewayFailure, ...]
    #: model tool name -> (display_name, service_name)
    owners: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)
    #: keys (connection names) of the UC connection sources
    connection_keys: frozenset[str] = frozenset()

    def saved_tokens(self) -> list[str]:
        """Every image token the tools saved, each once."""
        seen: dict[str, None] = {}
        for tool in self.tools:
            for token in tool.saved_tokens:
                seen.setdefault(token)
        return list(seen)

    def access_failures(self, toolset: AgentToolset) -> list[GatewayFailure]:
        """One failure per connection the loop recorded a refusal for, first seen first."""
        out: dict[str, GatewayFailure] = {}
        for err in toolset.access_errors:
            owner = self.owners.get(err.tool_name)
            if owner is None or owner[1] in out:
                continue
            out[owner[1]] = GatewayFailure(
                display_name=owner[0],
                service_name=owner[1],
                kind=err.kind,
                message=err.message,
                sign_in_url=err.sign_in_url,
                source="connection" if owner[1] in self.connection_keys else "gateway",
            )
        return list(out.values())


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def _sanitise(name: str) -> str:
    return _UNSAFE_RE.sub("_", name)


def _slugs(services: Sequence[str]) -> dict[str, str]:
    """Each service's last part; the schema part is added where two share a last part."""
    last = {s: _sanitise(s.rsplit(".", 1)[-1]) for s in services}
    counts = Counter(last.values())
    slugs: dict[str, str] = {}
    for service in services:
        parts = service.split(".")
        if counts[last[service]] > 1 and len(parts) >= 2:
            slugs[service] = _sanitise(parts[-2]) + "_" + last[service]
        else:
            slugs[service] = last[service]
    return slugs


def model_tool_names(specs_by_service: Mapping[str, Sequence[str]]) -> dict[tuple[str, str], str]:
    """The model-facing name of each ``(service, tool)``.

    A tool keeps its own name if it is unique across the services (and is not a
    reserved name); otherwise it is ``slug__tool``.  Names are sanitised to
    ``[A-Za-z0-9_-]``, cut to 64 characters, and a clash after that gets ``_2``,
    ``_3``, and so on.
    """
    counts = Counter(tool for tools in specs_by_service.values() for tool in set(tools))
    slugs = _slugs(list(specs_by_service))
    taken: set[str] = set(_RESERVED_NAMES)
    names: dict[tuple[str, str], str] = {}
    for service, tools in specs_by_service.items():
        for tool in tools:
            if (service, tool) in names:
                continue
            clash = (
                counts[tool] > 1
                or tool in _RESERVED_NAMES
                or _sanitise(tool).startswith(_RESERVED_PREFIX)
            )
            base = _sanitise(f"{slugs[service]}__{tool}" if clash else tool)[:_MAX_NAME_LEN]
            name, n = base, 1
            while name in taken:
                n += 1
                suffix = f"_{n}"
                name = base[: _MAX_NAME_LEN - len(suffix)] + suffix
            taken.add(name)
            names[(service, tool)] = name
    return names


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    """One thing to list tools from: a Gateway registry row or a UC connection."""

    key: str
    display_name: str
    instructions: str | None
    allowlist: tuple[str, ...] | None
    is_connection: bool

    def failure(
        self, kind: FailureKind, message: str | None, sign_in_url: str | None = None
    ) -> GatewayFailure:
        return GatewayFailure(
            self.display_name,
            self.key,
            kind,
            message,
            sign_in_url,
            "connection" if self.is_connection else "gateway",
        )


def build_gateway_tools(
    entries: Sequence[GatewayMcpTool],
    *,
    agent: Literal["architect", "data_analyst"],
    registry: Mapping[str, GatewayConnection],
    host: str,
    token: str,
    user: str,
    on_call: Callable[[str], None],
    session_id: str | None,
    client_factory: Callable[..., GatewayMcpClient] = GatewayMcpClient,
    deadline_at: float | None = None,
    connections: Sequence[MCPTool] = (),
    connection_client_factory: Callable[..., GatewayMcpClient] = ConnectionMcpClient,
) -> GatewayToolsetBuild:
    """The Gateway tools of *agent* for a deck's *entries*, plus what could not be bound.

    An entry whose registry row is missing is ``removed`` (reported by the
    architect pass only, so the user is told once); a disabled row is ``removed``
    for its own agent only; a row for the other agent is skipped silently.

    *connections* are UC MCP connection entries; those of *agent* are bound beside the
    Gateway services (the ``ai-gateway`` scope pre-flight applies to Gateway rows only).
    """
    slots: list[GatewayFailure | GatewayConnection] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.service_name in seen:
            continue
        seen.add(entry.service_name)
        row = registry.get(entry.service_name)
        if row is None:
            if agent == "architect":
                slots.append(
                    GatewayFailure(entry.display_name, entry.service_name, "removed", None, None)
                )
            continue
        if row.agent != agent:
            continue
        if not row.enabled:
            slots.append(GatewayFailure(row.display_name, row.service_name, "removed", None, None))
            continue
        slots.append(row)

    scopes = oauth_scopes_from_token(token)
    lacks_gateway = scopes is not None and not scopes_grant(scopes, _GATEWAY_SCOPE)

    # A failure, or a source to list.  A Gateway row of a token without ai-gateway
    # fails here; connections never do.
    final_slots: list[GatewayFailure | _Source] = []
    for slot in slots:
        if isinstance(slot, GatewayFailure):
            final_slots.append(slot)
        elif lacks_gateway:
            final_slots.append(
                GatewayFailure(
                    slot.display_name,
                    slot.service_name,
                    "missing_scope",
                    "The sign-in token lacks the ai-gateway scope.",
                    None,
                )
            )
        else:
            final_slots.append(
                _Source(
                    slot.service_name,
                    slot.display_name,
                    slot.instructions,
                    slot.tool_allowlist,
                    False,
                )
            )

    service_names = {entry.service_name for entry in entries}
    seen_connections: set[str] = set()
    for conn in connections:
        if conn.agent != agent or conn.connection_name in seen_connections:
            continue
        seen_connections.add(conn.connection_name)
        if conn.connection_name in service_names:
            logger.warning(
                "Skipping MCP connection %s: its name is also an AI Gateway service",
                conn.connection_name,
            )
            continue
        final_slots.append(
            _Source(conn.connection_name, conn.server_name, conn.description, None, True)
        )

    sources = [slot for slot in final_slots if isinstance(slot, _Source)]
    clients: dict[str, GatewayMcpClient] = {
        src.key: (connection_client_factory if src.is_connection else client_factory)(
            host=host, token=token, service_name=src.key, token_scopes=scopes
        )
        for src in sources
    }

    def list_one(src: _Source) -> list[GatewayToolSpec] | GatewayFailure:
        try:
            specs = clients[src.key].list_tools()
        except GatewayMcpError as err:
            kind: FailureKind = "unavailable" if err.kind == "timeout" else err.kind
            return src.failure(kind, err.message, err.sign_in_url)
        except Exception as exc:  # noqa: BLE001 - one connection must not stop the others
            logger.warning("Listing %s failed", src.key, exc_info=True)
            return src.failure("unavailable", str(exc) or None)
        if src.allowlist is not None:
            allowed = set(src.allowlist)
            specs = [spec for spec in specs if spec.name in allowed]
        # Two tools of one name make the provider reject the whole model call, so a
        # name the service lists twice is bound once (its first listing).
        unique: dict[str, GatewayToolSpec] = {}
        for spec in specs:
            unique.setdefault(spec.name, spec)
        return list(unique.values())

    results: dict[str, list[GatewayToolSpec] | GatewayFailure] = {}
    if sources:
        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            futures = {src.key: pool.submit(list_one, src) for src in sources}
            results = {key: future.result() for key, future in futures.items()}

    failures: list[GatewayFailure] = []
    bound: dict[str, tuple[_Source, list[GatewayToolSpec]]] = {}
    for slot in final_slots:
        if isinstance(slot, GatewayFailure):
            failures.append(slot)
            continue
        result = results[slot.key]
        if isinstance(result, GatewayFailure):
            failures.append(result)
        else:
            bound[slot.key] = (slot, result)

    names = model_tool_names({s: [spec.name for spec in specs] for s, (_, specs) in bound.items()})
    tools: list[GatewayMcpAgentTool] = []
    owners: dict[str, tuple[str, str]] = {}
    for key, (src, specs) in bound.items():
        ctx = GatewayToolContext(
            display_name=src.display_name,
            service_name=key,
            client=clients[key],
            save_image=make_image_saver(user=user, service_name=key, display_name=src.display_name),
            on_call=on_call,
            session_id=session_id,
            deadline_at=deadline_at,
        )
        for spec in specs:
            name = names[(key, spec.name)]
            tools.append(
                GatewayMcpAgentTool(spec, ctx, model_name=name, description_prefix=src.instructions)
            )
            owners[name] = (src.display_name, key)
    return GatewayToolsetBuild(
        tools=tuple(tools),
        failures=tuple(failures),
        owners=owners,
        connection_keys=frozenset(src.key for src in sources if src.is_connection),
    )


# ---------------------------------------------------------------------------
# Budget and notices
# ---------------------------------------------------------------------------


def turn_budget(
    *,
    used_calls: int,
    used_seconds: float,
    max_calls: int,
    budget_seconds: float,
    turn_started_at: float | None,
    now: float,
    deadline_seconds: float = GATEWAY_TURN_DEADLINE_SECONDS,
) -> tuple[int, float]:
    """``(calls left, seconds left)`` of a turn's shared budget, never negative.

    The seconds are clipped to the turn deadline; with no *turn_started_at* the
    deadline does not apply.
    """
    calls = max(0, int(max_calls - used_calls))
    seconds = max(0.0, float(budget_seconds - used_seconds))
    if turn_started_at is not None:
        seconds = min(seconds, max(0.0, float(deadline_seconds - (now - turn_started_at))))
    return calls, seconds


def failure_notice(failure: GatewayFailure, *, oauth_client_id: str | None) -> str:
    """The chat notice for *failure* (exact copy from the spec)."""
    name, service = failure.display_name, failure.service_name
    if failure.kind == "sign_in_required":
        if failure.sign_in_url:
            return f"To use {name}, sign in here: {failure.sign_in_url} — then ask again."
        return f"To use {name}, sign in to {service} — then ask again."
    if failure.kind == "missing_scope":
        return consent_message(oauth_client_id=oauth_client_id)
    if failure.source == "connection" and failure.kind == "access_denied":
        return (
            f"You don't have access to {name} ({service}). "
            "Ask the connection's owner to grant you USE CONNECTION on it."
        )
    if failure.source == "connection" and failure.kind == "not_found":
        return (
            f"{name} ({service}) was not found on this workspace. "
            "Check the connection in Catalog Explorer."
        )
    if failure.kind == "access_denied":
        return f"You don't have access to {name} ({service}). Ask an admin to grant EXECUTE on it."
    if failure.kind == "removed":
        return f"{name} is no longer available."
    if failure.kind == "not_found":
        return (
            f"{name} ({service}) was not found on this workspace. "
            "Ask an admin to check the connection."
        )
    reason = failure.message or "no details available"
    return f"{name} is unavailable right now ({reason}). The deck was built without it."
