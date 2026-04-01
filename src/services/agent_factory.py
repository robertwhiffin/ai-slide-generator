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

from src.api.schemas.agent_config import (
    AgentConfig, GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool,
)
from src.core.defaults import DEFAULT_CONFIG, DEFAULT_SLIDE_STYLE
from src.core.prompt_modules import build_editing_system_prompt, build_generation_system_prompt
from src.services.image_tools import SearchImagesInput, search_images
from src.services.tools import (
    GenieQueryInput,
    build_genie_tool,
    build_vector_tool,
    build_mcp_tools,
    build_model_endpoint_tool,
    build_agent_bricks_tool,
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
    mode: str = "generate",
) -> dict[str, Optional[str]]:
    """Resolve prompt content from AgentConfig, falling back to library lookups
    and then to backend defaults.

    When a custom ``system_prompt`` override is present in the config the
    caller takes full control and the modular assembly is skipped (same
    behaviour as before).  Otherwise prompt_modules builds a mode-specific
    system prompt so generation and editing each receive only the
    instructions they need.

    Resolution order for each prompt field:
    1. Explicit value in config (system_prompt, slide_editing_instructions)
    2. Library lookup by ID (slide_style_id, deck_prompt_id)
    3. Modular assembly via prompt_modules (mode-aware)
    4. Backend defaults from DEFAULT_CONFIG / DEFAULT_SLIDE_STYLE (legacy)

    Args:
        config: The AgentConfig for this request
        mode: ``"generate"`` or ``"edit"``

    Returns:
        Dict with keys: system_prompt, slide_editing_instructions,
        deck_prompt, slide_style, image_guidelines, pre_assembled
    """
    slide_style = DEFAULT_SLIDE_STYLE
    deck_prompt: Optional[str] = None
    image_guidelines: Optional[str] = None

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

    # --- Decide between modular assembly and legacy/override path ---

    has_custom_system_prompt = config.system_prompt is not None

    if has_custom_system_prompt:
        # User provided a full custom system_prompt — use legacy concatenation
        # path so _create_prompt in agent.py assembles it the old way.
        defaults = DEFAULT_CONFIG["prompts"]
        slide_editing_instructions = (
            config.slide_editing_instructions
            if config.slide_editing_instructions is not None
            else defaults["slide_editing_instructions"]
        )
        return {
            "system_prompt": config.system_prompt,
            "slide_editing_instructions": slide_editing_instructions,
            "deck_prompt": deck_prompt,
            "slide_style": slide_style,
            "image_guidelines": image_guidelines,
            "pre_assembled": False,
        }

    # No custom override — use modular prompt_modules assembly
    if mode == "edit":
        assembled = build_editing_system_prompt(
            slide_style=slide_style,
            deck_prompt=deck_prompt,
            image_guidelines=image_guidelines,
        )
    else:
        assembled = build_generation_system_prompt(
            slide_style=slide_style,
            deck_prompt=deck_prompt,
            image_guidelines=image_guidelines,
        )

    return {
        "system_prompt": assembled,
        "slide_editing_instructions": None,
        "deck_prompt": None,
        "slide_style": None,
        "image_guidelines": None,
        "pre_assembled": True,
    }


def _build_tools(
    config: AgentConfig,
    session_data: dict[str, Any],
) -> list[StructuredTool]:
    """Build the list of LangChain tools from AgentConfig.

    Always includes search_images. Handles all 5 tool types:
    GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool.

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
    vector_index = 0
    model_index = 0
    agent_index = 0

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
        elif isinstance(tool_entry, VectorIndexTool):
            vector_index += 1
            vector_tool = build_vector_tool(tool_entry, vector_index)
            tools.append(vector_tool)
            logger.info(
                "Added Vector Index tool",
                extra={
                    "index_name": tool_entry.index_name,
                    "tool_name": vector_tool.name,
                },
            )
        elif isinstance(tool_entry, MCPTool):
            mcp_tools = build_mcp_tools(tool_entry)
            tools.extend(mcp_tools)
            logger.info(
                "Added MCP tools",
                extra={
                    "connection_name": tool_entry.connection_name,
                    "server_name": tool_entry.server_name,
                    "tool_count": len(mcp_tools),
                },
            )
        elif isinstance(tool_entry, ModelEndpointTool):
            model_index += 1
            model_tool = build_model_endpoint_tool(tool_entry, model_index)
            tools.append(model_tool)
            logger.info(
                "Added Model Endpoint tool",
                extra={
                    "endpoint_name": tool_entry.endpoint_name,
                    "tool_name": model_tool.name,
                },
            )
        elif isinstance(tool_entry, AgentBricksTool):
            agent_index += 1
            agent_tool = build_agent_bricks_tool(tool_entry, agent_index)
            tools.append(agent_tool)
            logger.info(
                "Added Agent Bricks tool",
                extra={
                    "endpoint_name": tool_entry.endpoint_name,
                    "tool_name": agent_tool.name,
                },
            )

    return tools


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
            "has_custom_system_prompt": config.system_prompt is not None,
            "has_custom_editing_instructions": config.slide_editing_instructions is not None,
            "slide_style_id": config.slide_style_id,
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
