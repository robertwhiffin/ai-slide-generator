"""Provider-shaped replies for chat-model doubles (ws2a follow-up A).

``bind_structured_output_model`` binds the output schema as the one tool with
``tool_choice="auto"`` and parses the reply with ``PydanticToolsParser``, so a
chat-model double's ``bind_tools`` must hand back a Runnable whose output is
what a tool-calling provider returns: an ``AIMessage`` carrying one tool call
named after the schema.  These helpers build that reply; the parsing, and every
parse error, stay production's.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel


def tool_name(schema: type[BaseModel]) -> str:
    """The tool name the provider sees for ``schema`` (what the parser matches on)."""
    return convert_to_openai_tool(schema)["function"]["name"]


def tool_call_reply(schema: type[BaseModel], args: Mapping[str, Any] | BaseModel) -> AIMessage:
    """The reply of a provider that called the ``schema`` tool with ``args``.

    A model instance is sent as the keys it actually set, JSON-shaped, so the
    parsed result carries the same supplied keys the double was given.
    """
    if isinstance(args, BaseModel):
        args = args.model_dump(mode="json", exclude_unset=True)
    return AIMessage(
        content="",
        tool_calls=[
            {"name": tool_name(schema), "args": dict(args), "id": "call_0", "type": "tool_call"}
        ],
    )


def no_tool_call_reply(text: str = "I will not call the tool.") -> AIMessage:
    """The reply of a provider that answered in prose and called no tool."""
    return AIMessage(content=text)


def replying(reply: Callable[[Any], Any]) -> RunnableLambda:
    """A bound-model stand-in: ``reply(prompt)`` is the provider's reply."""
    return RunnableLambda(reply)


__all__ = ["no_tool_call_reply", "replying", "tool_call_reply", "tool_name"]
