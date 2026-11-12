"""Genie One MCP client (ask / poll / result / cancel), deterministic figures and model text.

Calls the AI Gateway Genie One MCP service as the user. Figures are built from
result rows, never from model prose.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

from databricks.sdk.errors import PermissionDenied

from src.core.scope_errors import is_missing_scope_error, mentions_missing_scope, scopes_grant
from src.domain.deck_spec import ResolvedFigure
from src.services.agent_tools.mcp_transport import (
    UserBearerAuth as _UserBearerAuth,  # noqa: F401 - the name tests and callers use
)
from src.services.agent_tools.mcp_transport import (
    build_user_mcp_client,
    run_with_timeout,
)
from src.services.agent_tools.mcp_transport import describe as _describe
from src.services.agent_tools.mcp_transport import http_status as _http_status
from src.services.agent_tools.mcp_transport import walk as _walk
from src.utils.spotlight import neutralize_delimiters

logger = logging.getLogger(__name__)

GENIE_ONE_SERVICE_PATH: Final = "/ai-gateway/mcp-services/system.ai.genie_one_mcp"
GENIE_ONE_SOURCE: Final = "Genie One"
#: Every Genie Agent source starts with this (``genie_agent.genie_agent_source``).
GENIE_AGENT_SOURCE_PREFIX: Final = "Genie Agent · "
#: The OAuth scope the AI Gateway requires of the user's token.
GENIE_ONE_SCOPE: Final = "ai-gateway"

#: The longest any one MCP call may take.
_CALL_TIMEOUT_SECONDS: Final = 60
#: Within a question, a call gets what is left of its deadline plus this much, so
#: a cancel or a result fetch made at the deadline still has time to answer.
_CALL_GRACE_SECONDS: Final = 10
#: How much of an error response's body is searched for a scope message.
_ERROR_BODY_CHARS: Final = 500
_DENIED_RE: Final = re.compile(r"\b403\b|Forbidden|PERMISSION_DENIED")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class GenieOneError(Exception):
    """A Genie One call failed."""


#: ``not_found`` is a Genie Agent's only (a deleted space, or one not shared with the
#: user: ``genie_agent._map_exception``); Genie One never raises it.
GenieAccessKind = Literal["missing_scope", "access_denied", "not_found"]


class GenieOneAccessError(GenieOneError):
    """The user cannot use Genie One (missing OAuth scope or no access), or a Genie Agent."""

    def __init__(self, message: str, *, kind: GenieAccessKind) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class GenieOneQueryResult:
    item_id: str
    sql: str | None
    columns: tuple[str, ...]
    rows: tuple[tuple[str | None, ...], ...]
    total_row_count: int | None
    truncated: bool


@dataclass(frozen=True)
class GenieOneAnswer:
    conversation_id: str
    response_id: str
    status: Literal["completed", "incomplete", "failed", "timed_out"]
    final_answer: str | None
    deep_link: str | None
    query_results: tuple[GenieOneQueryResult, ...]
    source: str = GENIE_ONE_SOURCE


def is_genie_source(source: str) -> bool:
    """True for the Genie One source or a Genie Agent source (code-built, never model text)."""
    return source == GENIE_ONE_SOURCE or source.startswith(GENIE_AGENT_SOURCE_PREFIX)


class CallTool(Protocol):
    """Calls one Genie One MCP tool and returns mcp's ``CallToolResult``.

    ``timeout_seconds`` bounds the call; past it, the call raises ``GenieOneError``.
    """

    def __call__(self, name: str, args: dict[str, Any], *, timeout_seconds: float) -> Any: ...


def _has_denied_marker(text: str) -> bool:
    return _DENIED_RE.search(text) is not None


def _error_body(exc: BaseException) -> str:
    """The error response's body, if the call path read it (``""`` otherwise)."""
    try:
        text = exc.response.text  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - no response, or a streamed body nobody read
        return ""
    return text[:_ERROR_BODY_CHARS] if isinstance(text, str) else ""


def _map_exception(exc: BaseException, *, lacks_gateway_scope: bool) -> GenieOneError:
    """Classify a failed call; every rule looks at the whole cause/context/group walk.

    1. A scope message, in any exception's text or in an error body: missing
       scope.  (Its text also says "403 Forbidden", so it is checked first.)
    2. Any HTTP 401: missing scope.
    3. A 403 (the status, an SDK ``PermissionDenied``, or "403" / "Forbidden" /
       "PERMISSION_DENIED" in the text): missing scope when the token's scopes
       are known and lack ``ai-gateway`` (*lacks_gateway_scope*), else a denied
       grant.  Unknown scopes leave a 403 a denied grant.
    """
    if isinstance(exc, GenieOneError):
        return exc
    message = _describe(exc)
    chain = list(_walk(exc))
    if is_missing_scope_error(exc) or any(mentions_missing_scope(_error_body(c)) for c in chain):
        return GenieOneAccessError(message, kind="missing_scope")
    if any(_http_status(c) == 401 for c in chain):
        return GenieOneAccessError(message, kind="missing_scope")
    if any(
        _http_status(c) == 403 or isinstance(c, PermissionDenied) or _has_denied_marker(str(c))
        for c in chain
    ):
        kind: Literal["missing_scope", "access_denied"] = (
            "missing_scope" if lacks_gateway_scope else "access_denied"
        )
        return GenieOneAccessError(message, kind=kind)
    return GenieOneError(message)


def _build_mcp_client(host: str, token: str) -> Any:
    """A ``DatabricksMCPClient`` for Genie One, as the user owning ``host`` and ``token``."""
    return build_user_mcp_client(host, token, GENIE_ONE_SERVICE_PATH)


class _McpCallTool:
    """The real call path: each call in a clean worker thread, with a timeout.

    The thread is needed because ``DatabricksMCPClient`` calls ``asyncio.run``,
    which cannot run inside a running event loop.  The MCP client, and the
    ``WorkspaceClient`` inside it, are built ONCE per instance (so once per
    ``GenieOneClient``), inside the first call's worker thread so that call's
    timeout also covers the host-metadata fetch construction makes, and are then
    reused by every later call.  Reuse across threads is safe: each call runs its
    own event loop and HTTP client, and the workspace client is only asked for the
    user's static bearer header.
    """

    def __init__(self, host: str, token: str) -> None:
        self._host = host
        self._token = token
        self._lock = threading.Lock()
        self._client: Any = None

    def _mcp_client(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = _build_mcp_client(self._host, self._token)
            return self._client

    def __call__(
        self, name: str, args: dict[str, Any], *, timeout_seconds: float = _CALL_TIMEOUT_SECONDS
    ) -> Any:
        def run() -> Any:
            return self._mcp_client().call_tool(name, args)

        return run_with_timeout(
            run,
            timeout_seconds=timeout_seconds,
            on_timeout=lambda: GenieOneError(
                f"Genie One did not respond within {timeout_seconds:g} seconds"
            ),
        )


def _default_call_tool(host: str, token: str) -> CallTool:
    return _McpCallTool(host, token)


def _result_text(result: Any) -> str:
    parts = [getattr(item, "text", None) for item in (getattr(result, "content", None) or [])]
    return "\n".join(p for p in parts if isinstance(p, str))


class GenieOneClient:
    """Asks Genie One one question at a time, as one user.

    ``token_scopes`` are the scopes the user's token says it carries
    (``oauth_scopes_from_token``), or ``None`` if unknown; with a known set that
    lacks ``ai-gateway``, a gateway 403 is a missing scope, not a denied grant.
    """

    def __init__(
        self,
        *,
        host: str,
        token: str,
        call_tool: CallTool | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = 3.0,
        token_scopes: frozenset[str] | None = None,
    ) -> None:
        self._call_tool = call_tool or _default_call_tool(host, token)
        self._sleep = sleep
        self._clock = clock
        self._poll_interval = poll_interval_seconds
        self._lacks_gateway_scope = token_scopes is not None and not scopes_grant(
            token_scopes, GENIE_ONE_SCOPE
        )

    def _timeout_for(self, deadline: float | None) -> float:
        """A call's timeout: at most 60 s, and no longer than the deadline plus the grace."""
        if deadline is None:
            return _CALL_TIMEOUT_SECONDS
        remaining = max(0.0, deadline - self._clock())
        return min(_CALL_TIMEOUT_SECONDS, remaining + _CALL_GRACE_SECONDS)

    def _call(
        self, name: str, args: dict[str, Any], *, deadline: float | None = None
    ) -> dict[str, Any]:
        """Call a tool and return its structuredContent. Raise GenieOneError on failure."""
        try:
            result = self._call_tool(name, args, timeout_seconds=self._timeout_for(deadline))
        except Exception as exc:
            mapped = _map_exception(exc, lacks_gateway_scope=self._lacks_gateway_scope)
            logger.warning("Genie One %s failed: %s", name, mapped, exc_info=exc)
            if mapped is exc:
                raise
            raise mapped from exc
        if getattr(result, "isError", False):
            text = _result_text(result)
            # A scope message first: it may also say 403.
            if mentions_missing_scope(text):
                raise GenieOneAccessError(text, kind="missing_scope")
            if _has_denied_marker(text):
                raise GenieOneAccessError(text, kind="access_denied")
            raise GenieOneError(text)
        structured = getattr(result, "structuredContent", None)
        return structured if isinstance(structured, dict) else {}

    def ask(
        self, question: str, *, conversation_id: str | None, timeout_seconds: float
    ) -> GenieOneAnswer:
        deadline = self._clock() + timeout_seconds
        args: dict[str, Any] = {"question": question}
        if conversation_id:
            args["conversation_id"] = conversation_id
        started = self._call("genie_ask", args, deadline=deadline)
        conv_id = started.get("conversation_id") or conversation_id or ""
        response_id = started.get("response_id") or ""
        ids = {"conversation_id": conv_id, "response_id": response_id}

        while True:
            try:
                polled = self._call("genie_poll_response", dict(ids), deadline=deadline)
            except GenieOneError:
                # The question may still be running: stop it (best effort).
                self._cancel(conv_id, deadline=deadline)
                raise
            status = polled.get("status")
            if status != "in_progress":
                break
            if self._clock() >= deadline:
                self._cancel(conv_id, deadline=deadline)
                return GenieOneAnswer(conv_id, response_id, "timed_out", None, None, ())
            self._sleep(self._poll_interval)

        results: list[GenieOneQueryResult] = []
        if status == "completed":
            for item in polled.get("query_items") or []:
                fetched = self._fetch_item(ids, item, deadline=deadline)
                if fetched is not None:
                    results.append(fetched)
        return GenieOneAnswer(
            conversation_id=conv_id,
            response_id=response_id,
            status=status,  # type: ignore[arg-type]
            final_answer=polled.get("final_answer"),
            deep_link=polled.get("deep_link"),
            query_results=tuple(results),
        )

    def _cancel(self, conversation_id: str, *, deadline: float | None = None) -> None:
        try:
            self._call(
                "genie_cancel_response", {"conversation_id": conversation_id}, deadline=deadline
            )
        except Exception:
            logger.warning("Genie One cancel failed (ignored)", exc_info=True)

    def _fetch_item(
        self, ids: dict[str, str], item: dict[str, Any], *, deadline: float | None = None
    ) -> GenieOneQueryResult | None:
        item_id = item.get("item_id", "")
        try:
            data = self._call(
                "genie_get_query_result", {**ids, "item_id": item_id}, deadline=deadline
            )
        except GenieOneAccessError:
            raise
        except GenieOneError as exc:
            logger.warning("Genie One query result %s skipped: %s", item_id, exc)
            return None
        return GenieOneQueryResult(
            item_id=item_id,
            sql=item.get("sql"),
            columns=tuple(c.get("name", "") for c in data.get("columns") or []),
            rows=tuple(tuple(r) for r in data.get("rows") or []),
            total_row_count=data.get("total_row_count"),
            truncated=bool(data.get("truncated")),
        )


def _cell(value: str | None) -> str:
    return "null" if value is None else str(value)


def _label_width(result: GenieOneQueryResult) -> int:
    """Shortest count of leading columns whose values are unique per row (0 if none)."""
    for k in range(1, len(result.columns)):
        labels = [tuple(row[:k]) for row in result.rows]
        if len(set(labels)) == len(labels):
            return k
    return 0


def figures_from_answer(answer: GenieOneAnswer, *, max_figures: int = 60) -> list[ResolvedFigure]:
    figures: list[ResolvedFigure] = []
    taken: set[str] = set()

    for n, result in enumerate(answer.query_results, start=1):
        if not result.rows or not result.columns:
            continue
        cols = result.columns
        pairs: list[tuple[str, str | None]] = []
        if len(result.rows) == 1:
            pairs = list(zip(cols, result.rows[0], strict=False))
        elif len(cols) >= 2:
            k = _label_width(result)
            for i, row in enumerate(result.rows):
                cells = list(zip(cols, row, strict=False))
                if k:
                    label = ", ".join(f"{c}={_cell(v)}" for c, v in cells[:k])
                    pairs.extend((f"{col} ({label})", cell) for col, cell in cells[k:])
                else:
                    pairs.extend((f"{col} [{i + 1}]", cell) for col, cell in cells[1:])
        else:
            pairs = [(f"{cols[0]} [{i + 1}]", row[0]) for i, row in enumerate(result.rows)]

        for key, cell in pairs:
            if len(figures) >= max_figures:
                return figures
            # Column names and cells are Genie One's output: no figure may carry a
            # real <untrusted-data> delimiter into a later spotlighted payload.
            key = neutralize_delimiters(key)
            if key in taken:
                key = f"{key} (query {n})"
            taken.add(key)
            figures.append(
                ResolvedFigure(
                    key=key, value=neutralize_delimiters(_cell(cell)), source=answer.source
                )
            )
    return figures


def render_answer_for_model(answer: GenieOneAnswer, *, max_rows: int = 50) -> str:
    lines = [f"Status: {answer.status}"]
    if answer.final_answer:
        lines += ["", _COMMENT_RE.sub("", answer.final_answer).strip()]
    for result in answer.query_results:
        lines.append("")
        if result.sql:
            lines.append(f"SQL: {result.sql}")
        lines.append("| " + " | ".join(result.columns) + " |")
        lines.append("| " + " | ".join("---" for _ in result.columns) + " |")
        for row in result.rows[:max_rows]:
            lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
        total = result.total_row_count if result.total_row_count is not None else len(result.rows)
        if len(result.rows) > max_rows or total > max_rows:
            lines.append(f"(showing {min(max_rows, len(result.rows))} of {total} rows)")
    return "\n".join(lines)
