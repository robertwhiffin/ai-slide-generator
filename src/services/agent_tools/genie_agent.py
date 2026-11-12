"""Genie Agent (a Genie space) client over the Genie conversation API, and its agent tool.

Modelled on :mod:`genie_one`.  The client asks one space one question at a time, as
one user (the host and token are fixed on it), by sending a message and polling it
(never the SDK's ``*_and_wait``).  Every SDK call runs through
``mcp_transport.run_with_timeout`` so that a slow or retrying call cannot overrun
the question's deadline.  Figures come from result rows, never from model prose,
and everything the model sees is spotlighted.

This module must not import ``registry`` (which imports it) or ``src.core.skills``.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, Final

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import PermissionDenied
from pydantic import BaseModel, Field

from src.core.scope_errors import is_missing_scope_error, mentions_missing_scope, scopes_grant
from src.services.agent_tools.genie_one import (
    GENIE_AGENT_SOURCE_PREFIX,
    GenieOneAccessError,
    GenieOneAnswer,
    GenieOneError,
    GenieOneQueryResult,
    _error_body,
    render_answer_for_model,
)
from src.services.agent_tools.mcp_transport import describe as _describe
from src.services.agent_tools.mcp_transport import http_status as _http_status
from src.services.agent_tools.mcp_transport import run_with_timeout
from src.services.agent_tools.mcp_transport import walk as _walk
from src.services.agent_tools.toolset import ToolAccessError, ToolAccessKind
from src.utils.spotlight import neutralize_delimiters, spotlight

logger = logging.getLogger(__name__)

#: The OAuth scope the Genie conversation API requires of the user's token.
GENIE_AGENT_SCOPE: Final = "dashboards.genie"
GENIE_AGENT_MAX_QUESTIONS: Final = 3

#: The longest any one SDK call may take.
_CALL_TIMEOUT_SECONDS: Final = 60
#: A call gets what is left of its question's deadline plus this much.
_CALL_GRACE_SECONDS: Final = 10
_MAX_NAME_LEN: Final = 64
_NAME_PREFIX: Final = "genie_agent_"
_DONE_FAILED: Final = frozenset({"FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"})
_SPOTLIGHT_SOURCE: Final = "genie_agent"


def genie_agent_source(space_name: str) -> str:
    return GENIE_AGENT_SOURCE_PREFIX + neutralize_delimiters(space_name.strip() or "Genie Agent")


def genie_agent_tool_names(space_names: Sequence[str]) -> list[str]:
    """One model-facing name per space: ``genie_agent_<slug>``, unique, at most 64 characters."""
    taken: set[str] = set()
    names: list[str] = []
    for space_name in space_names:
        slug = re.sub(r"[^a-z0-9]+", "_", space_name.lower()).strip("_") or "space"
        base = (_NAME_PREFIX + slug)[:_MAX_NAME_LEN]
        name, n = base, 1
        while name in taken:
            n += 1
            suffix = f"_{n}"
            name = base[: _MAX_NAME_LEN - len(suffix)] + suffix
        taken.add(name)
        names.append(name)
    return names


class _CallTimedOutError(Exception):
    """An SDK call outlived the question's deadline (internal; ends the question)."""


def _is_denied(exc: BaseException) -> bool:
    return any(_http_status(c) == 403 or isinstance(c, PermissionDenied) for c in _walk(exc))


class GenieAgentClient:
    """Asks one Genie Agent one question at a time, as the user owning ``host`` and ``token``.

    ``token_scopes`` are the scopes the token says it carries, or ``None`` if unknown;
    with a known set lacking ``dashboards.genie``, a 403 is a missing scope.
    """

    def __init__(
        self,
        *,
        host: str,
        token: str,
        space_id: str,
        source: str,
        token_scopes: frozenset[str] | None = None,
        genie_factory: Callable[[str, str], Any] | None = None,
        poll_interval_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._host = host
        self._token = token
        self._space_id = space_id
        self._source = source
        self._factory = genie_factory
        self._poll_interval = poll_interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._lacks_scope = token_scopes is not None and not scopes_grant(
            token_scopes, GENIE_AGENT_SCOPE
        )
        self._lock = threading.Lock()
        self._genie_obj: Any = None

    def __repr__(self) -> str:
        return f"GenieAgentClient(space_id={self._space_id!r}, source={self._source!r})"

    def _genie(self) -> Any:
        with self._lock:
            if self._genie_obj is None:
                if self._factory is not None:
                    self._genie_obj = self._factory(self._host, self._token)
                else:
                    self._genie_obj = WorkspaceClient(
                        host=self._host, token=self._token, auth_type="pat"
                    ).genie
            return self._genie_obj

    def _map_exception(self, exc: BaseException) -> GenieOneError:
        if isinstance(exc, GenieOneError):
            return exc
        message = _describe(exc)
        chain = list(_walk(exc))
        if is_missing_scope_error(exc) or any(
            mentions_missing_scope(_error_body(c)) for c in chain
        ):
            return GenieOneAccessError(message, kind="missing_scope")
        if _is_denied(exc):
            if self._lacks_scope:
                return GenieOneAccessError(message, kind="missing_scope")
            return GenieOneAccessError(message, kind="access_denied")
        return GenieOneError(message)

    def _call(self, fn: Callable[[Any], Any], deadline: float) -> Any:
        """Run ``fn(genie)`` bounded by the deadline plus the grace, capped at 60 s."""
        remaining = max(0.0, deadline - self._clock())
        timeout = min(_CALL_TIMEOUT_SECONDS, remaining + _CALL_GRACE_SECONDS)
        try:
            return run_with_timeout(
                lambda: fn(self._genie()),
                timeout_seconds=timeout,
                on_timeout=_CallTimedOutError,
            )
        except _CallTimedOutError:
            raise
        except Exception as exc:
            mapped = self._map_exception(exc)
            logger.warning("Genie Agent call failed: %s", mapped, exc_info=exc)
            if mapped is exc:
                raise
            raise mapped from exc

    def ask(
        self, question: str, *, conversation_id: str | None, timeout_seconds: float
    ) -> GenieOneAnswer:
        deadline = self._clock() + timeout_seconds
        conv_id = conversation_id or ""
        msg_id = ""
        try:
            if conversation_id:
                sent = self._call(
                    lambda g: g.create_message(
                        space_id=self._space_id, conversation_id=conversation_id, content=question
                    ),
                    deadline,
                )
            else:
                sent = self._call(
                    lambda g: g.start_conversation(space_id=self._space_id, content=question),
                    deadline,
                )
            response = sent.response
            conv_id = getattr(response, "conversation_id", None) or conv_id
            msg_id = getattr(response, "message_id", None) or getattr(response, "id", None) or ""

            while True:
                message = self._call(
                    lambda g: g.get_message(
                        space_id=self._space_id, conversation_id=conv_id, message_id=msg_id
                    ),
                    deadline,
                )
                status = getattr(message.status, "value", message.status)
                if status == "COMPLETED" or status in _DONE_FAILED:
                    break
                if self._clock() >= deadline:
                    return self._answer(conv_id, msg_id, "timed_out", None, ())
                self._sleep(self._poll_interval)

            if status in _DONE_FAILED:
                return self._answer(conv_id, msg_id, "failed", None, ())
            return self._completed(message, conv_id, msg_id, deadline)
        except _CallTimedOutError:
            return self._answer(conv_id, msg_id, "timed_out", None, ())

    def _completed(
        self, message: Any, conv_id: str, msg_id: str, deadline: float
    ) -> GenieOneAnswer:
        final_answer: str | None = None
        results: list[GenieOneQueryResult] = []
        for attachment in message.attachments or []:
            if attachment.text is not None and final_answer is None:
                final_answer = attachment.text.content
            if attachment.query is not None:
                att_id = attachment.attachment_id
                fetched = self._call(
                    lambda g, a=att_id: g.get_message_attachment_query_result(
                        space_id=self._space_id,
                        conversation_id=conv_id,
                        message_id=msg_id,
                        attachment_id=a,
                    ),
                    deadline,
                )
                results.append(self._query_result(att_id, attachment.query.query, fetched))
        return self._answer(conv_id, msg_id, "completed", final_answer, tuple(results))

    @staticmethod
    def _query_result(att_id: str, sql: str | None, fetched: Any) -> GenieOneQueryResult:
        statement = fetched.statement_response
        manifest = getattr(statement, "manifest", None)
        schema = getattr(manifest, "schema", None)
        result = getattr(statement, "result", None)
        return GenieOneQueryResult(
            item_id=att_id,
            sql=sql,
            columns=tuple(c.name or "" for c in (getattr(schema, "columns", None) or [])),
            rows=tuple(tuple(r) for r in (getattr(result, "data_array", None) or [])),
            total_row_count=getattr(manifest, "total_row_count", None),
            truncated=bool(getattr(manifest, "truncated", False)),
        )

    def _answer(
        self,
        conv_id: str,
        msg_id: str,
        status: Any,
        final_answer: str | None,
        results: tuple[GenieOneQueryResult, ...],
    ) -> GenieOneAnswer:
        return GenieOneAnswer(
            conversation_id=conv_id,
            response_id=msg_id,
            status=status,
            final_answer=final_answer,
            deep_link=f"{self._host}/genie/rooms/{self._space_id}/chats/{conv_id}",
            query_results=results,
            source=self._source,
        )


class GenieAgentQuestion(BaseModel):
    """The one argument the model passes."""

    question: str = Field(
        ..., min_length=1, description="A natural-language question about the user's data."
    )


#: What the model is told about a refusal (code-owned; the server's text is only logged).
_ACCESS_REFUSED: Final[dict[ToolAccessKind, str]] = {
    "missing_scope": (
        "{space} refused the request: the user's sign-in to this app is missing "
        "a permission it needs. Asking again will not help."
    ),
    "access_denied": (
        "{space} refused the request: the user does not have permission to use "
        "this Genie Agent. Asking again will not help."
    ),
}
_QUESTIONS_SPENT: Final = (
    "Not asked: {space} has already been asked {n} questions for this request, "
    "the most allowed. Continue with the answers you have."
)


def _description(space_name: str, user_description: str | None, source: str, cap: int) -> str:
    parts = [
        f"Ask {space_name}, a Genie Agent (a curated Databricks data agent), about the user's data."
    ]
    if user_description and user_description.strip():
        parts.append(user_description.strip())
    parts.append(
        f"It answers with result tables. {space_name} is a natural-language analyst: ask the "
        "business question you would put to a human analyst, such as "
        '"What are the 10 most popular routes?" or "How did trip volume change month by month?". '
        "Do not name columns or tables unless the user named them, and do not specify SQL, "
        f"rounding, sort order or output format: {space_name} works out what data to use. "
        "Ask ONE question, read the answer, then decide whether a follow-up is needed. "
        f"Each question can take a few minutes, and you may ask at most {cap} per request."
    )
    parts.append(
        "Figures from its results are recorded automatically with source "
        f'"{source}"; list "{source}" in sources when you use them.'
    )
    return " ".join(parts)


class GenieAgentTool:
    """One Genie Agent as an ``AgentTool``; see ``GenieOneAgentTool`` for the shared contract."""

    args_schema = GenieAgentQuestion

    def __init__(
        self,
        client: GenieAgentClient,
        *,
        model_name: str,
        space_id: str,
        space_name: str,
        user_description: str | None,
        conversation_id: str | None,
        on_question: Callable[[str, str], None],
        session_id: str | None,
        max_questions: int = GENIE_AGENT_MAX_QUESTIONS,
    ) -> None:
        self._client = client
        self._on_question = on_question
        self._session_id = session_id
        self._max_questions = max_questions
        self._asked = 0
        self.name = model_name
        self.space_id = space_id
        self.space_name = space_name
        self.source = genie_agent_source(space_name)
        self.description = _description(space_name, user_description, self.source, max_questions)
        self.answers: list[GenieOneAnswer] = []
        self.stored_conversation_id = conversation_id
        self.conversation_id: str | None = conversation_id

    def run(self, args: BaseModel, *, remaining_seconds: float) -> str:
        question = args.question  # type: ignore[attr-defined]
        if self._asked >= self._max_questions:
            return _QUESTIONS_SPENT.format(space=self.space_name, n=self._max_questions)
        self._asked += 1
        try:
            self._on_question(self.space_name, question)
        except Exception:  # noqa: BLE001 - a progress line never stops the question
            logger.warning("Genie Agent progress line failed (ignored)", exc_info=True)
        try:
            answer = self._client.ask(
                question, conversation_id=self.conversation_id, timeout_seconds=remaining_seconds
            )
        except GenieOneAccessError as exc:
            logger.warning(
                "Genie Agent refused the request (%s): %s",
                exc.kind,
                exc,
                extra={"session_id": self._session_id},
            )
            raise ToolAccessError(
                exc.kind, self.name, _ACCESS_REFUSED[exc.kind].format(space=self.space_name)
            ) from exc
        except GenieOneError as exc:
            logger.warning(
                "Genie Agent call failed: %s", exc, extra={"session_id": self._session_id}
            )
            return spotlight(
                _SPOTLIGHT_SOURCE,
                f"{self.space_name} could not answer: {exc}",
                session_id=self._session_id,
            )
        self.answers.append(answer)
        if answer.conversation_id:
            self.conversation_id = answer.conversation_id
        return spotlight(
            _SPOTLIGHT_SOURCE, render_answer_for_model(answer), session_id=self._session_id
        )
