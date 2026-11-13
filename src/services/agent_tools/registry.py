"""The tools an agent-mode invocation is handed, built from the actor's agent config.

Genie One, for the data analyst.  :func:`build_analyst_toolset` returns ``None``
when the config has no Genie One entry, and the analyst then runs exactly as it
did before tools existed.  The analyst's AI Gateway MCP tools, when it has any,
ride beside Genie One as ``extra_tools`` (built by ``gateway_toolset``); the
toolset then has the Gateway budget, and Genie One keeps its own question cap.

**Identity.**  The ``host`` and ``token`` passed in are the signed-in user's,
captured by the node in its own thread (``get_user_client()``).  They are fixed
on the client here, so nothing later reaches for an identity in a worker thread
where the request's ContextVars are not set.

**Untrusted output.**  Everything Genie One returns reaches the model only
through ``spotlight("genie_one", ...)``: an answer as
:func:`render_answer_for_model` renders it, and a failed call's text too.  An
access refusal reaches it as a code-owned sentence, never the server's text.

This module must not import ``src.core.skills``
(``test_lakebase_only_runtime_contract``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, Final

from pydantic import BaseModel, Field

from src.api.schemas.agent_config import AgentConfig, GenieOneTool, GenieTool
from src.core.scope_errors import oauth_scopes_from_token
from src.services.agent_tools.gateway_toolset import (
    ANALYST_GATEWAY_BUDGET_SECONDS,
    ANALYST_GATEWAY_MAX_CALLS,
)
from src.services.agent_tools.genie_agent import (
    GenieAgentClient,
    GenieAgentTool,
    genie_agent_source,
    genie_agent_tool_names,
)
from src.services.agent_tools.genie_one import (
    GenieOneAccessError,
    GenieOneAnswer,
    GenieOneClient,
    GenieOneError,
    render_answer_for_model,
)
from src.services.agent_tools.toolset import (
    AgentTool,
    AgentToolset,
    ToolAccessError,
    ToolAccessKind,
)
from src.services.generation_fence import TurnFencedError
from src.utils.spotlight import spotlight

logger = logging.getLogger(__name__)

#: The name the model is bound with.  The data analyst's (promote-locked) prompt
#: already names a ``genie`` tool, so Genie One answers to that name.
GENIE_TOOL_NAME: Final = "genie"

#: Per analyst run: at most this many questions, within this many seconds.
GENIE_ONE_MAX_QUESTIONS: Final = 3
GENIE_ONE_BUDGET_SECONDS: Final = 300.0

#: Genie One plans its own queries, so it is asked business questions, one at a
#: time (live, the analyst sent it a SQL-like spec of table, columns and ordering,
#: and two questions in one reply).  The runtime's loop runs only the first tool
#: call in a reply, to match.
GENIE_TOOL_DESCRIPTION: Final = (
    "Ask Genie One, the Databricks data agent, about the user's data; it answers "
    "with result tables. Genie One is a natural-language analyst: ask the business "
    'question you would ask a human analyst, such as "What are the 10 most popular '
    'routes?", "Which drop-off areas are busiest?" or "How did trip volume change '
    'month by month?". Do not name columns or tables unless the user named them, '
    "and do not specify SQL, rounding, sort order or output format: Genie One works "
    "out what data to use. Ask ONE question, read the answer, then decide whether a "
    "follow-up question is needed. Each question takes one to four minutes, and you "
    f"may ask at most {GENIE_ONE_MAX_QUESTIONS} per request. Figures from its results "
    'are recorded automatically with source "Genie One"; list "Genie One" in sources '
    "when you use them."
)

_SPOTLIGHT_SOURCE: Final = "genie_one"

#: What the model is told about a refusal.  Code-owned: the server's text is
#: logged, not handed to the model.  The node tells the user what to do.
_ACCESS_REFUSED: Final[dict[ToolAccessKind, str]] = {
    "missing_scope": (
        "Genie One refused the request: the user's sign-in to this app is missing "
        "a permission Genie One needs. Asking again will not help."
    ),
    "access_denied": (
        "Genie One refused the request: the user does not have permission to use "
        "Genie One. Asking again will not help."
    ),
}

#: What the model is told about a question past ``max_questions`` (code-owned).
_QUESTIONS_SPENT: Final = (
    "Not asked: Genie One has already been asked {n} questions for this request, "
    "the most allowed. Continue with the answers you have."
)


class GenieQuestion(BaseModel):
    """The one argument the model passes."""

    question: str = Field(
        ..., min_length=1, description="A natural-language question about the user's data."
    )


class GenieOneAgentTool:
    """Genie One as an ``AgentTool`` named ``genie``.

    Each call says its progress line (``on_question``) BEFORE asking, continues
    the conversation the previous answer opened, and keeps every answer in
    :attr:`answers`, in order, so the node builds figures from the result rows
    rather than from anything the model wrote.  :attr:`conversation_id` is the
    latest one, for the node to persist on the actor's row.

    ``max_questions`` caps the questions this tool asks, for a toolset whose own
    call budget is shared with other tools (the analyst's AI Gateway MCP tools):
    a question past it is answered without asking Genie One and without a
    progress line.  ``None`` (the default) asks every question, as before.
    """

    name = GENIE_TOOL_NAME
    description = GENIE_TOOL_DESCRIPTION
    args_schema = GenieQuestion

    def __init__(
        self,
        client: GenieOneClient,
        *,
        conversation_id: str | None,
        on_question: Callable[[str], None],
        session_id: str | None,
        max_questions: int | None = None,
    ) -> None:
        self._client = client
        self._on_question = on_question
        self._session_id = session_id
        self._max_questions = max_questions
        self._asked = 0
        self.answers: list[GenieOneAnswer] = []
        self.conversation_id: str | None = conversation_id

    def run(self, args: BaseModel, *, remaining_seconds: float) -> str:
        question = args.question  # type: ignore[attr-defined]
        if self._max_questions is not None and self._asked >= self._max_questions:
            return _QUESTIONS_SPENT.format(n=self._max_questions)
        self._asked += 1
        try:
            self._on_question(question)
        except TurnFencedError:
            # The progress row was refused: the turn was stopped, so the question
            # is never sent.
            raise
        except Exception:  # noqa: BLE001 - a progress line never stops the question
            logger.warning("Genie One progress line failed (ignored)", exc_info=True)
        try:
            answer = self._client.ask(
                question,
                conversation_id=self.conversation_id,
                timeout_seconds=remaining_seconds,
            )
        except GenieOneAccessError as exc:
            logger.warning(
                "Genie One refused the request (%s): %s",
                exc.kind,
                exc,
                extra={"session_id": self._session_id},
            )
            raise ToolAccessError(exc.kind, self.name, _ACCESS_REFUSED[exc.kind]) from exc
        except GenieOneError as exc:
            logger.warning("Genie One call failed: %s", exc, extra={"session_id": self._session_id})
            return spotlight(
                _SPOTLIGHT_SOURCE,
                f"Genie One could not answer: {exc}",
                session_id=self._session_id,
            )
        self.answers.append(answer)
        if answer.conversation_id:
            self.conversation_id = answer.conversation_id
        return spotlight(
            _SPOTLIGHT_SOURCE, render_answer_for_model(answer), session_id=self._session_id
        )


def build_analyst_toolset(
    agent_config: AgentConfig,
    *,
    host: str,
    token: str,
    on_question: Callable[[str], None],
    session_id: str | None,
    extra_tools: Sequence[AgentTool] = (),
) -> tuple[AgentToolset, GenieOneAgentTool] | None:
    """The data analyst's toolset for *agent_config*, or ``None`` without Genie One.

    The client runs as the user whose ``host`` and ``token`` these are, and
    knows the scopes that token says it carries (so a gateway 403 for a token
    without ``ai-gateway`` is a missing scope); the stored ``conversation_id``
    (that row's own) is continued.

    Without *extra_tools* the toolset is Genie One's alone, with its own budget
    (:data:`GENIE_ONE_MAX_QUESTIONS` / :data:`GENIE_ONE_BUDGET_SECONDS`), exactly
    as before.  With them (the analyst's AI Gateway MCP tools) it holds both and
    the Gateway budget, and Genie One still asks at most
    :data:`GENIE_ONE_MAX_QUESTIONS` questions.
    """
    entry = next((t for t in agent_config.tools if isinstance(t, GenieOneTool)), None)
    if entry is None:
        return None
    tool = GenieOneAgentTool(
        GenieOneClient(host=host, token=token, token_scopes=oauth_scopes_from_token(token)),
        conversation_id=entry.conversation_id,
        on_question=on_question,
        session_id=session_id,
        max_questions=GENIE_ONE_MAX_QUESTIONS if extra_tools else None,
    )
    if extra_tools:
        toolset = AgentToolset(
            tools=(tool, *extra_tools),
            max_calls=ANALYST_GATEWAY_MAX_CALLS,
            budget_seconds=ANALYST_GATEWAY_BUDGET_SECONDS,
        )
    else:
        toolset = AgentToolset(
            tools=(tool,),
            max_calls=GENIE_ONE_MAX_QUESTIONS,
            budget_seconds=GENIE_ONE_BUDGET_SECONDS,
        )
    return toolset, tool


def build_genie_agent_tools(
    agent_config: AgentConfig,
    *,
    host: str,
    token: str,
    on_question: Callable[[str, str], None],
    session_id: str | None,
    genie_factory: Callable[[str, str], Any] | None = None,
) -> tuple[GenieAgentTool, ...]:
    """One tool per Genie Agent (``GenieTool``) entry, in config order, as the user.

    Each client knows the scopes *token* says it carries, so a 403 for a token
    without ``dashboards.genie`` is a missing scope.
    """
    entries = [t for t in agent_config.tools if isinstance(t, GenieTool)]
    names = genie_agent_tool_names([e.space_name for e in entries])
    scopes = oauth_scopes_from_token(token)
    return tuple(
        GenieAgentTool(
            GenieAgentClient(
                host=host,
                token=token,
                space_id=entry.space_id,
                source=genie_agent_source(entry.space_name),
                token_scopes=scopes,
                genie_factory=genie_factory,
            ),
            model_name=name,
            space_id=entry.space_id,
            space_name=entry.space_name,
            user_description=entry.description,
            conversation_id=entry.conversation_id,
            on_question=on_question,
            session_id=session_id,
        )
        for entry, name in zip(entries, names, strict=True)
    )
