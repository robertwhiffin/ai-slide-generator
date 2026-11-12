"""Generic AI Gateway MCP client (list tools / call a tool) with typed errors.

Calls any AI Gateway MCP service (``<catalog>.<schema>.<service>``) as the signed-in
user.  Every failure surfaces as :class:`GatewayMcpError` with a ``kind`` the caller
can act on (sign in, request a scope, ask for access, ...).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal
from urllib.parse import quote, urlsplit

from databricks.sdk.errors import NotFound, PermissionDenied
from mcp.shared.exceptions import McpError

from src.core.scope_errors import is_missing_scope_error, mentions_missing_scope, scopes_grant
from src.domain.gateway_service_name import validate_service_name
from src.services.agent_tools.mcp_transport import (
    build_user_mcp_client,
    describe,
    http_status,
    run_with_timeout,
    walk,
)

__all__ = [
    "CALL_TIMEOUT_SECONDS",
    "LIST_TIMEOUT_SECONDS",
    "ConnectionMcpClient",
    "GatewayErrorKind",
    "GatewayMcpClient",
    "GatewayMcpError",
    "GatewayProbe",
    "GatewayToolSpec",
    "connection_path",
    "connection_sign_in_url",
    "gateway_service_url",
    "map_connection_error",
    "map_gateway_error",
    "probe_service",
    "sign_in_url",
    "validate_service_name",
]

logger = logging.getLogger(__name__)

GatewayErrorKind = Literal[
    "sign_in_required", "missing_scope", "access_denied", "not_found", "timeout", "unavailable"
]

LIST_TIMEOUT_SECONDS: Final = 30
CALL_TIMEOUT_SECONDS: Final = 90

#: The OAuth scope the AI Gateway requires of the user's token.
_GATEWAY_SCOPE: Final = "ai-gateway"
#: JSON-RPC code the Gateway answers with when the user has not signed in to a service.
_NOT_SIGNED_IN_CODE: Final = -32006
#: mcp 1.27 reports an HTTP 404 on a session as this JSON-RPC error.
_SESSION_TERMINATED_CODE: Final = 32600
_SESSION_TERMINATED_TEXT: Final = "Session terminated"
_ORG_ID_HEADER: Final = "x-databricks-org-id"

_SIGN_IN_URL_RE: Final = re.compile(r"https://\S+/mcp-service-login\?\S+")
_CODE_RE: Final = re.compile(rf'"code"\s*:\s*{_NOT_SIGNED_IN_CODE}')
_DENIED_RE: Final = re.compile(r"\b403\b|Forbidden|PERMISSION_DENIED")
_NOT_FOUND_RE: Final = re.compile(r"not found|does not exist", re.IGNORECASE)
_NOT_SIGNED_IN_TEXT_RE: Final = re.compile(r"not signed in|mcp-service-login", re.IGNORECASE)


class GatewayMcpError(Exception):
    """A Gateway MCP call failed; ``kind`` says how."""

    def __init__(
        self, kind: GatewayErrorKind, message: str, *, sign_in_url: str | None = None
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.sign_in_url = sign_in_url


@dataclass(frozen=True)
class GatewayToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class GatewayProbe:
    state: Literal[
        "ready", "sign_in_required", "missing_scope", "access_denied", "not_found", "unavailable"
    ]
    tools: tuple[GatewayToolSpec, ...]
    sign_in_url: str | None
    detail: str | None


def _service_path(service_name: str) -> str:
    return f"/ai-gateway/mcp-services/{service_name}"


def gateway_service_url(host: str, service_name: str) -> str:
    return f"{host}{_service_path(service_name)}"


def _origin(url: str) -> tuple[str, str] | None:
    """``(scheme, authority)`` of *url*, lower-cased (``None`` if it does not parse).

    A trailing ``/`` is part of the path, so ``https://h/`` and ``https://h`` agree.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    return parts.scheme.lower(), parts.netloc.lower()


def _on_host(url: str, host: str) -> bool:
    """True if *url* has exactly *host*'s scheme and authority (user info and port included)."""
    origin = _origin(url)
    return origin is not None and origin == _origin(host)


def sign_in_url(
    host: str,
    service_name: str,
    *,
    message: str | None = None,
    workspace_id: str | None = None,
) -> str:
    """Where the user signs in to a service: the link in *message*, else a built one.

    The link in *message* is used only when it is on *host* itself.  The message
    can come from the service behind the Gateway, and the link is shown to the
    user as Tellr's own sign-in link, so a link anywhere else is ignored.
    """
    if message:
        found = _SIGN_IN_URL_RE.search(message)
        if found:
            url = found.group(0).rstrip(".,;)")
            if _on_host(url, host):
                return url
    url = f"{host}/mcp-service-login?name={service_name}"
    return f"{url}&o={workspace_id}" if workspace_id else url


def _response_text(exc: BaseException) -> str:
    """The whole error response body, if the call path read it (``""`` otherwise)."""
    try:
        text = exc.response.text  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - no response, or a streamed body nobody read
        return ""
    return text if isinstance(text, str) else ""


def _body_error(text: str) -> tuple[int | None, str | None]:
    """``(error.code, error.message)`` of a JSON-RPC error body (``None``s if it is not one)."""
    try:
        error = json.loads(text).get("error")
    except (ValueError, AttributeError):
        return None, None
    if not isinstance(error, dict):
        return None, None
    code, message = error.get("code"), error.get("message")
    return (
        code if isinstance(code, int) else None,
        message if isinstance(message, str) else None,
    )


_CONNECTION_PATH_PREFIX: Final = "/api/2.0/mcp/external/"
_CONNECTION_LINK_RE: Final = re.compile(r"https://\S+/explore/connections/\S+")
_CONNECTION_UNAUTH_RE: Final = re.compile(r'"error_code"\s*:\s*"UNAUTHENTICATED"')
_CONNECTION_LOGIN_TEXT: Final = "Please login first to the connection"
_LINK_TRAILING: Final = "\"'.,;)}\\"


def connection_path(connection_name: str) -> str:
    """The Unity Catalog proxy path of a connection (the name is one path segment)."""
    return _CONNECTION_PATH_PREFIX + quote(connection_name, safe="")


def connection_sign_in_url(host: str, connection_name: str, *, message: str | None = None) -> str:
    """Where the user signs in to a connection: the link in *message*, else a built one.

    As :func:`sign_in_url`, a link is used only when it is on *host* itself.
    """
    if message:
        found = _CONNECTION_LINK_RE.search(message)
        if found:
            url = found.group(0).rstrip(_LINK_TRAILING)
            if _on_host(url, host):
                return url
    return f"{host}/explore/connections/{quote(connection_name, safe='')}"


def _is_connection_signed_out(text: str) -> bool:
    return bool(_CONNECTION_UNAUTH_RE.search(text)) or _CONNECTION_LOGIN_TEXT in text


def map_connection_error(exc: BaseException, *, host: str, connection_name: str) -> GatewayMcpError:
    """Classify a failed call to a UC connection.

    Rule 0: any exception in the walk whose McpError message, response body or text
    says the user is not signed in is ``sign_in_required``.  Everything else follows
    :func:`map_gateway_error` (a connection needs no ``ai-gateway`` scope).
    """
    if isinstance(exc, GatewayMcpError):
        return exc
    for cur in walk(exc):
        body = _response_text(cur)
        candidates = [
            cur.error.message if isinstance(cur, McpError) else None,
            # A JSON-RPC error envelope: its message, unescaped, before the raw body.
            _body_error(body)[1],
            body,
            str(cur),
        ]
        for text in candidates:
            if text and _is_connection_signed_out(text):
                return GatewayMcpError(
                    "sign_in_required",
                    f"Not signed in to {connection_name}",
                    sign_in_url=connection_sign_in_url(host, connection_name, message=text),
                )
    return map_gateway_error(
        exc, host=host, service_name=connection_name, lacks_gateway_scope=False
    )


def _not_signed_in_url(chain: list[BaseException], host: str, service_name: str) -> str | None:
    """The sign-in link, if any exception in *chain* is a JSON-RPC "not signed in" (-32006)."""
    for cur in chain:
        message: str | None = None
        if isinstance(cur, McpError) and cur.error.code == _NOT_SIGNED_IN_CODE:
            message = cur.error.message
        else:
            body = _response_text(cur)
            code, body_message = _body_error(body)
            if code == _NOT_SIGNED_IN_CODE:
                message = body_message
            elif code is not None or not _CODE_RE.search(body):
                continue
        headers = getattr(getattr(cur, "response", None), "headers", None)
        workspace_id = headers.get(_ORG_ID_HEADER) if headers is not None else None
        return sign_in_url(host, service_name, message=message, workspace_id=workspace_id)
    return None


def _is_session_terminated(exc: BaseException) -> bool:
    return (
        isinstance(exc, McpError)
        and exc.error.code == _SESSION_TERMINATED_CODE
        and exc.error.message == _SESSION_TERMINATED_TEXT
    )


def map_gateway_error(
    exc: BaseException, *, host: str, service_name: str, lacks_gateway_scope: bool
) -> GatewayMcpError:
    """Classify a failed call; every rule looks at the whole cause/context/group walk.

    1. JSON-RPC code -32006 (an ``McpError``, or in a JSON error body): sign in required.
    2. A scope message, in any exception's text or in an error body: missing scope.
    3. Any other HTTP 401: missing scope.
    4. A 403 (the status, an SDK ``PermissionDenied``, or "403" / "Forbidden" /
       "PERMISSION_DENIED" in the text): missing scope when the token's scopes lack
       ``ai-gateway`` (*lacks_gateway_scope*), else access denied.
    5. A 404, an SDK ``NotFound``, "not found" / "does not exist" text, or mcp's
       "Session terminated" (its report of an HTTP 404): not found.
    6. Anything else: unavailable.
    """
    if isinstance(exc, GatewayMcpError):
        return exc
    message = describe(exc)
    chain = list(walk(exc))
    bodies = [_response_text(c) for c in chain]

    url = _not_signed_in_url(chain, host, service_name)
    if url is not None:
        return GatewayMcpError(
            "sign_in_required", f"Not signed in to {service_name}", sign_in_url=url
        )
    if is_missing_scope_error(exc) or any(mentions_missing_scope(b) for b in bodies):
        return GatewayMcpError("missing_scope", message)
    if any(http_status(c) == 401 for c in chain):
        return GatewayMcpError("missing_scope", message)
    if any(
        http_status(c) == 403 or isinstance(c, PermissionDenied) or _DENIED_RE.search(str(c))
        for c in chain
    ):
        return GatewayMcpError("missing_scope" if lacks_gateway_scope else "access_denied", message)
    if any(
        http_status(c) == 404 or isinstance(c, NotFound) or _is_session_terminated(c) for c in chain
    ) or any(_NOT_FOUND_RE.search(t) for t in [*map(str, chain), *bodies]):
        return GatewayMcpError("not_found", message)
    return GatewayMcpError("unavailable", message)


def _result_text(result: Any) -> str:
    parts = [getattr(item, "text", None) for item in (getattr(result, "content", None) or [])]
    return "\n".join(p for p in parts if isinstance(p, str))


class GatewayMcpClient:
    """Lists and calls the tools of one Gateway MCP service, as one user.

    ``token_scopes`` are the scopes the user's token says it carries
    (``oauth_scopes_from_token``), or ``None`` if unknown; with a known set that
    lacks ``ai-gateway``, a gateway 403 is a missing scope, not a denied grant.

    Only the async session methods of the MCP client are used (via ``asyncio.run``
    in a clean worker thread), so ``DatabricksMCPClient``'s sync wrappers, whose
    error handler re-sends an ``initialize`` to diagnose, never run.  The MCP
    client, and the ``WorkspaceClient`` inside it, are built once, inside the first
    call's worker thread so that call's timeout also covers the build.
    """

    def __init__(
        self,
        *,
        host: str,
        token: str,
        service_name: str,
        token_scopes: frozenset[str] | None = None,
        mcp_client_factory: Callable[[str, str, str], Any] | None = None,
    ) -> None:
        self._host = host
        self._token = token
        self._service_name = service_name
        self._lacks_gateway_scope = token_scopes is not None and not scopes_grant(
            token_scopes, _GATEWAY_SCOPE
        )
        self._factory = mcp_client_factory or build_user_mcp_client
        self._lock = threading.Lock()
        self._client: Any = None

    def _mcp_client(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = self._factory(self._host, self._token, self._path())
            return self._client

    def _path(self) -> str:
        return _service_path(self._service_name)

    def _map_error(self, exc: BaseException) -> GatewayMcpError:
        return map_gateway_error(
            exc,
            host=self._host,
            service_name=self._service_name,
            lacks_gateway_scope=self._lacks_gateway_scope,
        )

    def _signed_out(self, text: str) -> GatewayMcpError | None:
        """The error for an ``isError`` result that says the user is not signed in."""
        if _NOT_SIGNED_IN_TEXT_RE.search(text):
            return GatewayMcpError(
                "sign_in_required",
                f"Not signed in to {self._service_name}",
                sign_in_url=sign_in_url(self._host, self._service_name, message=text),
            )
        return None

    def _run(self, what: str, fn: Callable[[], Any], timeout_seconds: float) -> Any:
        """Run *fn* in a worker with a timeout; raise only ``GatewayMcpError``."""
        try:
            return run_with_timeout(
                fn,
                timeout_seconds=timeout_seconds,
                on_timeout=lambda: GatewayMcpError(
                    "timeout",
                    f"{self._service_name} did not respond within {timeout_seconds:g} seconds",
                ),
            )
        except GatewayMcpError:
            raise
        except Exception as exc:
            mapped = self._map_error(exc)
            if mapped.kind == "sign_in_required":
                # An expected user state (they have not signed in yet), not a fault:
                # one line, no traceback.
                logger.info(
                    "Gateway MCP %s on %s: the user is not signed in",
                    what,
                    self._service_name,
                )
            else:
                logger.warning(
                    "Gateway MCP %s on %s failed: %s",
                    what,
                    self._service_name,
                    mapped,
                    exc_info=exc,
                )
            raise mapped from exc

    def list_tools(self, *, timeout_seconds: float = LIST_TIMEOUT_SECONDS) -> list[GatewayToolSpec]:
        """The service's tools. Raise ``GatewayMcpError`` on failure."""

        def run() -> Any:
            return asyncio.run(self._mcp_client()._get_tools_async())

        tools = self._run("tools/list", run, timeout_seconds)
        return [
            GatewayToolSpec(
                name=tool.name, description=tool.description or "", input_schema=tool.inputSchema
            )
            for tool in tools
        ]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float = CALL_TIMEOUT_SECONDS,
    ) -> Any:
        """Call a tool and return mcp's ``CallToolResult``. Raise ``GatewayMcpError`` on failure.

        An ``isError`` result is returned for the model to read, unless it says the
        user is not signed in.
        """

        def run() -> Any:
            return asyncio.run(self._mcp_client()._call_tools_async(name, arguments))

        result = self._run(f"tools/call {name}", run, timeout_seconds)
        if getattr(result, "isError", False):
            text = _result_text(result)
            signed_out = self._signed_out(text)
            if signed_out is not None:
                raise signed_out
        return result


class ConnectionMcpClient(GatewayMcpClient):
    """The Gateway client over a UC connection proxy; ``service_name`` is the connection."""

    def _path(self) -> str:
        return connection_path(self._service_name)

    def _map_error(self, exc: BaseException) -> GatewayMcpError:
        return map_connection_error(exc, host=self._host, connection_name=self._service_name)

    def _signed_out(self, text: str) -> GatewayMcpError | None:
        if _is_connection_signed_out(text):
            return GatewayMcpError(
                "sign_in_required",
                f"Not signed in to {self._service_name}",
                sign_in_url=connection_sign_in_url(self._host, self._service_name, message=text),
            )
        return None


def probe_service(client: GatewayMcpClient) -> GatewayProbe:
    """Whether the user can use the service: ``ready`` with its tools, or why not."""
    try:
        tools = client.list_tools()
    except GatewayMcpError as err:
        state = "unavailable" if err.kind in ("timeout", "unavailable") else err.kind
        return GatewayProbe(state=state, tools=(), sign_in_url=err.sign_in_url, detail=err.message)
    return GatewayProbe(state="ready", tools=tuple(tools), sign_in_url=None, detail=None)
