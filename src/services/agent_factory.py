"""Factory for building per-request SlideGeneratorAgent instances.

This module constructs a complete agent from an AgentConfig JSON blob,
replacing the singleton agent pattern with per-request construction.

The factory:
1. Creates the LLM model using fixed backend defaults
2. Builds tools from config.tools (Genie -> native LangChain tool, MCP -> warning)
3. Resolves prompts: config overrides first, then library lookups, then defaults
4. Returns an agent object compatible with ChatService's interface

RESOLUTION MOVED (ws4c C8). Steps 2 and 3 — tool registration, the slide-style
branch and prompt assembly — now live in :mod:`src.services.agent_resolution`, so
the graph path and this monolith path share ONE implementation of them rather than
two copies of a branch whose tombstone case has already shipped a defect once.
What stays here is agent CONSTRUCTION: :func:`_create_model` and
:func:`build_agent_for_request`.

The moved names are re-exported below and remain importable and patchable from
``src.services.agent_factory``: ``chat_service`` imports
``build_agent_for_request`` from here, and the six ``agent_factory`` unit suites
import ``_get_prompt_content`` / ``_build_tools`` from here. Patch targets for the
names ``_build_tools`` resolves internally (the tool builders, ``search_images``,
``_design_system_is_active``) must name ``src.services.agent_resolution`` instead —
patching them here would apply to an attribute the moved code no longer reads,
which silently intercepts nothing.
"""

import logging
from typing import Any

from src.api.schemas.agent_config import AgentConfig
from src.core.defaults import DEFAULT_CONFIG

# Re-export the three moved functions, and ONLY those. The PRIVATE names are the
# point: the suites and ws4d's cutover window import them from here. Names that
# never existed on this module (``resolve_style_source``, ``resolve_slide_style``,
# ``ResolvedStyle``) are deliberately NOT re-exported — a name re-exported for no
# caller is dead surface, and an AttributeError on a wrong patch target is a far
# better failure than a patch that applies and intercepts nothing.
from src.services.agent_resolution import (  # noqa: F401
    _build_tools,
    _design_system_is_active,
    _get_prompt_content,
)

logger = logging.getLogger(__name__)


def _create_model():
    """Create LangChain Databricks model using backend defaults.

    Uses the fixed LLM configuration from DEFAULT_CONFIG. LLM settings
    are NOT user-configurable — they are backend infrastructure defaults.

    Uses the system client (service principal) so that users do not need
    workspace-level permissions on the model serving endpoint.

    Returns:
        ChatDatabricks model instance
    """
    from databricks_langchain import ChatDatabricks

    from src.core.databricks_client import get_system_client

    llm_config = DEFAULT_CONFIG["llm"]
    system_client = get_system_client()

    model = ChatDatabricks(
        endpoint=llm_config["endpoint"],
        temperature=llm_config["temperature"],
        max_tokens=llm_config["max_tokens"],
        top_p=0.95,
        workspace_client=system_client,
    )

    logger.info(
        "Agent factory: ChatDatabricks model created",
        extra={
            "endpoint": llm_config["endpoint"],
            "temperature": llm_config["temperature"],
            "max_tokens": llm_config["max_tokens"],
        },
    )

    return model


def build_agent_for_request(
    config: AgentConfig,
    session_data: dict[str, Any],
    mode: str = "generate",
) -> "SlideGeneratorAgent":
    """Build a complete SlideGeneratorAgent for a single chat request.

    This is the main entry point for per-request agent construction.
    It creates the LLM, tools, and prompts from the AgentConfig, then
    returns an agent that ChatService can invoke.

    Args:
        config: AgentConfig parsed from the session's agent_config JSON
        session_data: Dict with at minimum:
            - session_id: str
            - genie_conversation_id: Optional[str]
        mode: ``"generate"`` or ``"edit"`` — controls which prompt
            modules are included in the system message.

    Returns:
        SlideGeneratorAgent configured for this request
    """
    from src.services.agent import SlideGeneratorAgent

    logger.info(
        "Building agent for request",
        extra={
            "session_id": session_data.get("session_id"),
            "tool_count": len(config.tools),
            "slide_style_id": config.slide_style_id,
            "design_system_id": config.design_system_id,
            "deck_prompt_id": config.deck_prompt_id,
            "mode": mode,
        },
    )

    # 1. Create the LLM model
    model = _create_model()

    # 2. Build tools from config
    tools = _build_tools(config, session_data)

    # 3. Resolve prompts (mode-aware)
    prompts = _get_prompt_content(config, mode=mode)

    # 4. Build agent with pre-built components
    agent = SlideGeneratorAgent(
        pre_built_model=model,
        pre_built_tools=tools,
        pre_built_prompts=prompts,
    )

    logger.info(
        "Agent built successfully",
        extra={
            "session_id": session_data.get("session_id"),
            "tool_names": [t.name for t in tools],
            "mode": mode,
        },
    )

    return agent
