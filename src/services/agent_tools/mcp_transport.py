"""Shared transport for calling AI Gateway MCP services as the signed-in user.

Used by the Genie One client and the generic Gateway MCP client: the user-bearer
auth, the ``DatabricksMCPClient`` builder that uses it, and the clean-worker-thread
timeout both run their calls under.
"""

from __future__ import annotations

import asyncio
import builtins
from collections.abc import AsyncGenerator, Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Final, TypeVar

import httpx

T = TypeVar("T")

_GROUP: Final = getattr(builtins, "BaseExceptionGroup", ())


def walk(exc: BaseException):
    """Yield *exc* and everything reachable through ``__cause__``, ``__context__`` and groups."""
    seen: set[int] = set()
    stack = [exc]
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        yield cur
        for nxt in (cur.__cause__, cur.__context__):
            if nxt is not None:
                stack.append(nxt)
        if _GROUP and isinstance(cur, _GROUP):
            stack.extend(cur.exceptions)


def http_status(exc: BaseException) -> int | None:
    """The HTTP status an exception carries (``httpx.HTTPStatusError``), else ``None``."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def leaf(exc: BaseException) -> BaseException:
    """The exception that says what failed: the first in the walk with an HTTP
    status, else the first that is neither a group nor a cancellation."""
    fallback: BaseException | None = None
    for cur in walk(exc):
        if http_status(cur) is not None:
            return cur
        if fallback is None and not (
            (_GROUP and isinstance(cur, _GROUP)) or isinstance(cur, asyncio.CancelledError)
        ):
            fallback = cur
    return fallback or exc


def describe(exc: BaseException) -> str:
    """``"<leaf type> (HTTP <status>): <leaf text>"``: what an error message says."""
    cause = leaf(exc)
    status = http_status(cause)
    head = type(cause).__name__ + (f" (HTTP {status})" if status is not None else "")
    text = str(cause)
    return f"{head}: {text}" if text else head


class UserBearerAuth(httpx.Auth):
    """The signed-in user's token on every request, and nothing else.

    It replaces databricks_mcp's ``DatabricksOAuthClientProvider``, which answers
    a 401 by starting an OAuth discovery flow (from an empty server URL) that dies
    on an unrelated ``httpx`` error, so a missing scope could not be told apart
    from any other failure.  Here a 401 or a 403 surfaces as
    ``httpx.HTTPStatusError`` with its status; an error body is read first,
    because ``raise_for_status`` leaves a streamed body unread and a scope message
    in it would be lost.  Only the header is read from the workspace client
    (static for a ``pat`` client), so one instance is safe to share across threads.
    """

    def __init__(self, workspace_client: Any) -> None:
        self._workspace_client = workspace_client

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers.update(self._workspace_client.config.authenticate())
        yield request

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        request.headers.update(self._workspace_client.config.authenticate())
        response = yield request
        if response.status_code >= 400:
            await response.aread()


def build_user_mcp_client(host: str, token: str, service_path: str) -> Any:
    """A ``DatabricksMCPClient`` for one Gateway service, as the user owning ``host`` and ``token``.

    Imported here, not at module level: the MCP stack is needed only when a
    service is actually called.
    """
    from databricks.sdk import WorkspaceClient
    from databricks_mcp import DatabricksMCPClient
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    class _UserMCPClient(DatabricksMCPClient):
        """``DatabricksMCPClient`` with :class:`UserBearerAuth` in place of its OAuth provider.

        The same sessions as the base's ``_get_tools_async`` and ``_call_tools_async``;
        only the auth differs.  ``call_tool`` / ``list_tools`` (their ``asyncio.run``
        and error handling) are the base's.
        """

        async def _session_run(self, operation: Callable[[Any], Any]) -> Any:
            async with httpx.AsyncClient(
                auth=UserBearerAuth(self.client),
                timeout=httpx.Timeout(30, read=300),
                follow_redirects=True,
            ) as http_client:
                async with streamable_http_client(self.server_url, http_client=http_client) as (
                    read_stream,
                    write_stream,
                    _,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        return await operation(session)

        async def _get_tools_async(self) -> Any:
            async def operation(session: Any) -> Any:
                return (await session.list_tools()).tools

            return await self._session_run(operation)

        async def _call_tools_async(
            self, tool_name: str, arguments: dict[str, Any] | None = None
        ) -> Any:
            async def operation(session: Any) -> Any:
                return await session.call_tool(tool_name, arguments)

            return await self._session_run(operation)

    workspace_client = WorkspaceClient(host=host, token=token, auth_type="pat")
    return _UserMCPClient(server_url=f"{host}{service_path}", workspace_client=workspace_client)


def run_with_timeout(
    fn: Callable[[], T], *, timeout_seconds: float, on_timeout: Callable[[], Exception]
) -> T:
    """Run *fn* in a clean worker thread; raise ``on_timeout()`` if it takes too long.

    A clean thread, because ``asyncio.run`` cannot run inside a running event loop.
    """
    # Not a `with` block: its exit would wait on a timed-out thread.
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(fn).result(timeout=timeout_seconds)
    except FuturesTimeoutError as exc:
        raise on_timeout() from exc
    finally:
        executor.shutdown(wait=False)
