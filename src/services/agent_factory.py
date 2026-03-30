"""Factory for building per-request SlideGeneratorAgent instances.

This module constructs a complete agent from an AgentConfig JSON blob,
replacing the singleton agent pattern with per-request construction.

The factory:
1. Creates the LLM model using fixed backend defaults
2. Builds tools from config.tools (Genie -> native LangChain tool, MCP -> warning)
3. Resolves prompts: config overrides first, then library lookups, then defaults
4. Returns an agent object compatible with ChatService's interface
"""

import logging
from typing import Any, Optional

from langchain_core.tools import StructuredTool

from src.api.schemas.agent_config import AgentConfig, GenieTool, MCPTool
from src.core.defaults import DEFAULT_CONFIG, DEFAULT_SLIDE_STYLE
from src.services.image_tools import SearchImagesInput, search_images
from src.services.tools import (
    GenieQueryInput,
    build_genie_tool,
    initialize_genie_conversation,
    query_genie_space,
)

logger = logging.getLogger(__name__)


def _create_model():
    """Create LangChain Databricks model using backend defaults.

    Uses the fixed LLM configuration from DEFAULT_CONFIG. LLM settings
    are NOT user-configurable — they are backend infrastructure defaults.

    Returns:
        ChatDatabricks model instance
    """
    from databricks_langchain import ChatDatabricks

    from src.core.databricks_client import get_user_client

    llm_config = DEFAULT_CONFIG["llm"]
    user_client = get_user_client()

    model = ChatDatabricks(
        endpoint=llm_config["endpoint"],
        temperature=llm_config["temperature"],
        max_tokens=llm_config["max_tokens"],
        top_p=0.95,
        workspace_client=user_client,
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


def _get_prompt_content(
    config: AgentConfig,
) -> dict[str, Optional[str]]:
    """Resolve prompt content from AgentConfig, falling back to library lookups
    and then to backend defaults.

    Resolution order for each prompt field:
    1. Explicit value in config (system_prompt, slide_editing_instructions)
    2. Library lookup by ID (slide_style_id, deck_prompt_id)
    3. Backend defaults from DEFAULT_CONFIG / DEFAULT_SLIDE_STYLE

    Args:
        config: The AgentConfig for this request

    Returns:
        Dict with keys: system_prompt, slide_editing_instructions,
        deck_prompt, slide_style, image_guidelines
    """
    defaults = DEFAULT_CONFIG["prompts"]

    # Start with backend defaults
    system_prompt = defaults["system_prompt"]
    slide_editing_instructions = defaults["slide_editing_instructions"]
    slide_style = DEFAULT_SLIDE_STYLE
    deck_prompt = None
    image_guidelines = None

    # Override system_prompt if config provides one
    if config.system_prompt is not None:
        system_prompt = config.system_prompt

    # Override slide_editing_instructions if config provides one
    if config.slide_editing_instructions is not None:
        slide_editing_instructions = config.slide_editing_instructions

    # Resolve slide_style_id from library
    if config.slide_style_id is not None:
        try:
            from src.core.database import get_db_session
            from src.database.models import SlideStyleLibrary

            with get_db_session() as db:
                style = (
                    db.query(SlideStyleLibrary)
                    .filter_by(id=config.slide_style_id, is_active=True)
                    .first()
                )
                if style:
                    slide_style = style.style_content
                    image_guidelines = style.image_guidelines
                else:
                    logger.warning(
                        "Slide style not found or inactive, using default",
                        extra={"slide_style_id": config.slide_style_id},
                    )
        except Exception as e:
            logger.error(f"Failed to resolve slide_style_id: {e}")

    # Resolve deck_prompt_id from library
    if config.deck_prompt_id is not None:
        try:
            from src.core.database import get_db_session
            from src.database.models import SlideDeckPromptLibrary

            with get_db_session() as db:
                prompt = (
                    db.query(SlideDeckPromptLibrary)
                    .filter_by(id=config.deck_prompt_id, is_active=True)
                    .first()
                )
                if prompt:
                    deck_prompt = prompt.prompt_content
                else:
                    logger.warning(
                        "Deck prompt not found or inactive, skipping",
                        extra={"deck_prompt_id": config.deck_prompt_id},
                    )
        except Exception as e:
            logger.error(f"Failed to resolve deck_prompt_id: {e}")

    return {
        "system_prompt": system_prompt,
        "slide_editing_instructions": slide_editing_instructions,
        "deck_prompt": deck_prompt,
        "slide_style": slide_style,
        "image_guidelines": image_guidelines,
    }


def _build_tools(
    config: AgentConfig,
    session_data: dict[str, Any],
) -> list[StructuredTool]:
    """Build the list of LangChain tools from AgentConfig.

    Always includes search_images. Adds Genie tools for each GenieTool
    entry. Logs a warning for MCPTool entries (not yet supported).

    Args:
        config: AgentConfig with tool definitions
        session_data: Session dict for Genie conversation state

    Returns:
        List of StructuredTool instances
    """
    tools: list[StructuredTool] = []

    # Image search tool is always available
    image_search_tool = StructuredTool.from_function(
        func=search_images,
        name="search_images",
        description=(
            "Search for uploaded images to include in slides. "
            "Use when user mentions images, logos, or branding. "
            "Returns image metadata with IDs. "
            'To embed an image, use: <img src="{{image:ID}}" alt="description" />'
        ),
        args_schema=SearchImagesInput,
    )
    tools.append(image_search_tool)

    genie_index = 0
    for tool_entry in config.tools:
        if isinstance(tool_entry, GenieTool):
            genie_index += 1
            genie_tool = build_genie_tool(tool_entry, session_data, genie_index)
            tools.append(genie_tool)
            logger.info(
                "Added Genie tool",
                extra={
                    "space_id": tool_entry.space_id,
                    "space_name": tool_entry.space_name,
                    "tool_name": genie_tool.name,
                },
            )
        elif isinstance(tool_entry, MCPTool):
            logger.warning(
                "MCP tools not yet supported, skipping",
                extra={
                    "connection_name": tool_entry.connection_name,
                    "server_name": tool_entry.server_name,
                },
            )

    return tools


def build_agent_for_request(
    config: AgentConfig,
    session_data: dict[str, Any],
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

    Returns:
        SlideGeneratorAgent configured for this request
    """
    from src.services.agent import SlideGeneratorAgent

    logger.info(
        "Building agent for request",
        extra={
            "session_id": session_data.get("session_id"),
            "tool_count": len(config.tools),
            "has_custom_system_prompt": config.system_prompt is not None,
            "has_custom_editing_instructions": config.slide_editing_instructions is not None,
            "slide_style_id": config.slide_style_id,
            "deck_prompt_id": config.deck_prompt_id,
        },
    )

    # 1. Create the LLM model
    model = _create_model()

    # 2. Build tools from config
    tools = _build_tools(config, session_data)

    # 3. Resolve prompts
    prompts = _get_prompt_content(config)

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
        },
    )

    return agent
