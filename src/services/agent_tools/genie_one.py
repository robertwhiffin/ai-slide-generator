"""Genie One MCP client (ask / poll / result / cancel), deterministic figures and model text.

Calls the AI Gateway Genie One MCP service as the user. Figures are built from
result rows, never from model prose.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Final, Literal

from databricks.sdk.errors import PermissionDenied

from src.core.scope_errors import is_missing_scope_error
from src.domain.deck_spec import ResolvedFigure

logger = logging.getLogger(__name__)

GENIE_ONE_SERVICE_PATH: Final = "/ai-gateway/mcp-services/system.ai.genie_one_mcp"
GENIE_ONE_SOURCE: Final = "Genie One"

_CALL_TIMEOUT_SECONDS: Final = 60
_DENIED_MARKERS: Final = ("403", "Forbidden", "PERMISSION_DENIED")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class GenieOneError(Exception):
    """A Genie One call failed."""


class GenieOneAccessError(GenieOneError):
    """The user cannot use Genie One (missing OAuth scope or no access)."""

    def __init__(self, message: str, *, kind: Literal["missing_scope", "access_denied"]) -> None:
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


CallTool = Callable[[str, dict[str, Any]], Any]


def _walk(exc: BaseException):
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
        if isinstance(cur, BaseExceptionGroup):
            stack.extend(cur.exceptions)


def _has_denied_marker(text: str) -> bool:
    return any(marker in text for marker in _DENIED_MARKERS)


def _map_exception(exc: BaseException) -> GenieOneError:
    if isinstance(exc, GenieOneError):
        return exc
    # Missing scope first: its message also contains "403 Forbidden".
    if is_missing_scope_error(exc):
        return GenieOneAccessError(str(exc), kind="missing_scope")
    for cur in _walk(exc):
        if isinstance(cur, PermissionDenied) or _has_denied_marker(str(cur)):
            return GenieOneAccessError(str(cur), kind="access_denied")
    return GenieOneError(str(exc))


def _default_call_tool(host: str, token: str) -> CallTool:
    def call(name: str, args: dict[str, Any]) -> Any:
        def run() -> Any:
            from databricks.sdk import WorkspaceClient
            from databricks_mcp import DatabricksMCPClient

            ws_client = WorkspaceClient(host=host, token=token, auth_type="pat")
            client = DatabricksMCPClient(
                server_url=f"{host}{GENIE_ONE_SERVICE_PATH}", workspace_client=ws_client
            )
            return client.call_tool(name, args)

        # Not a `with` block: its exit would wait on a timed-out thread.
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            return executor.submit(run).result(timeout=_CALL_TIMEOUT_SECONDS)
        finally:
            executor.shutdown(wait=False)

    return call


def _result_text(result: Any) -> str:
    parts = [getattr(item, "text", None) for item in (getattr(result, "content", None) or [])]
    return "\n".join(p for p in parts if isinstance(p, str))


class GenieOneClient:
    def __init__(
        self,
        *,
        host: str,
        token: str,
        call_tool: CallTool | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_interval_seconds: float = 3.0,
    ) -> None:
        self._call_tool = call_tool or _default_call_tool(host, token)
        self._sleep = sleep
        self._clock = clock
        self._poll_interval = poll_interval_seconds

    def _call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Call a tool and return its structuredContent. Raise GenieOneError on failure."""
        try:
            result = self._call_tool(name, args)
        except Exception as exc:
            raise _map_exception(exc) from exc
        if getattr(result, "isError", False):
            text = _result_text(result)
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
        started = self._call("genie_ask", args)
        conv_id = started.get("conversation_id") or conversation_id or ""
        response_id = started.get("response_id") or ""
        ids = {"conversation_id": conv_id, "response_id": response_id}

        while True:
            polled = self._call("genie_poll_response", dict(ids))
            status = polled.get("status")
            if status != "in_progress":
                break
            if self._clock() >= deadline:
                self._cancel(conv_id)
                return GenieOneAnswer(conv_id, response_id, "timed_out", None, None, ())
            self._sleep(self._poll_interval)

        results: list[GenieOneQueryResult] = []
        if status == "completed":
            for item in polled.get("query_items") or []:
                fetched = self._fetch_item(ids, item)
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

    def _cancel(self, conversation_id: str) -> None:
        try:
            self._call("genie_cancel_response", {"conversation_id": conversation_id})
        except Exception:
            logger.warning("Genie One cancel failed (ignored)", exc_info=True)

    def _fetch_item(self, ids: dict[str, str], item: dict[str, Any]) -> GenieOneQueryResult | None:
        item_id = item.get("item_id", "")
        try:
            data = self._call("genie_get_query_result", {**ids, "item_id": item_id})
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
            for row in result.rows:
                for col, cell in list(zip(cols, row, strict=False))[1:]:
                    pairs.append((f"{col} ({cols[0]}={row[0]})", cell))
        else:
            pairs = [(f"{cols[0]} [{i + 1}]", row[0]) for i, row in enumerate(result.rows)]

        for key, cell in pairs:
            if len(figures) >= max_figures:
                return figures
            if key in taken:
                key = f"{key} (query {n})"
            taken.add(key)
            figures.append(ResolvedFigure(key=key, value=_cell(cell), source=GENIE_ONE_SOURCE))
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
