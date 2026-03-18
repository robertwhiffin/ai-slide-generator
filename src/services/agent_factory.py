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
from pydantic import BaseModel, Field

from src.api.schemas.agent_config import AgentConfig, GenieTool, MCPTool
from src.core.defaults import DEFAULT_CONFIG, DEFAULT_SLIDE_STYLE
from src.services.image_tools import SearchImagesInput, search_images
from src.services.tools import initialize_genie_conversation, query_genie_space

logger = logging.getLogger(__name__)


class GenieQueryInput(BaseModel):
    """Input schema for Genie query tool."""

    query: str = Field(description="Natural language question")


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


def _build_genie_tool(
    genie_config: GenieTool,
    session_data: dict[str, Any],
    index: int = 1,
) -> StructuredTool:
    """Build a LangChain StructuredTool for a Genie space.

    The tool wraps query_genie_space with automatic conversation_id
    management via closure over session_data. Each Genie space gets
    its own conversation_id tracked under a per-space key.

    Args:
        genie_config: GenieTool config with space_id and space_name
        session_data: Mutable session dict (conversation_ids updated in place)
        index: 1-based index for unique tool naming when multiple Genie spaces

    Returns:
        StructuredTool for querying Genie
    """
    # Per-space conversation ID key
    conv_key = f"genie_conversation_id:{genie_config.space_id}"

    # Seed from the persisted conversation_id on the GenieTool config first
    if genie_config.conversation_id:
        session_data[conv_key] = genie_config.conversation_id
    # Fall back to the legacy single key if this is the first/only Genie space
    elif conv_key not in session_data and index == 1:
        legacy_id = session_data.get("genie_conversation_id")
        if legacy_id:
            session_data[conv_key] = legacy_id

    def _query_genie_wrapper(query: str) -> str:
        """Query Genie with auto-injected conversation_id from session."""
        conversation_id = session_data.get(conv_key)

        if conversation_id is None:
            logger.info(
                "Initializing Genie conversation for factory-built agent",
                extra={"space_id": genie_config.space_id},
            )
            try:
                new_conv_id = initialize_genie_conversation()
                session_data[conv_key] = new_conv_id
                # Also update the legacy key for backward compat
                session_data["genie_conversation_id"] = new_conv_id
                conversation_id = new_conv_id
            except Exception as e:
                logger.error(f"Failed to initialize Genie conversation: {e}")
                raise

        result = query_genie_space(query, conversation_id)

        response_parts = []
        if result.get("message"):
            response_parts.append(f"Genie response: {result['message']}")
        if result.get("data"):
            response_parts.append(f"Data retrieved:\n\n{result['data']}")
        if not response_parts:
            return "Query completed but no data or message was returned."
        return "\n\n".join(response_parts)

    description = (
        "Query Databricks Genie for data using natural language questions. "
        "Genie understands natural language and converts it to SQL - do not write SQL yourself.\n\n"
        "USAGE GUIDELINES:\n"
        "- Make multiple queries to gather comprehensive data (typically 5-8 strategic queries)\n"
        "- Use follow-up queries to drill deeper into interesting findings\n"
        "- Conversation context is automatically maintained across queries\n"
        "- If initial data is insufficient, query for more specific information\n\n"
        "WHEN TO STOP:\n"
        "- Once you have sufficient data, STOP calling this tool\n"
        "- Transition immediately to generating the HTML presentation\n"
        "- Do NOT make additional queries once you have enough information\n\n"
    )
    if genie_config.description:
        description += f"DATA AVAILABLE:\n{genie_config.description}"
    else:
        description += f"DATA AVAILABLE:\nGenie space '{genie_config.space_name}'"

    tool_name = "query_genie_space" if index == 1 else f"query_genie_space_{index}"

    return StructuredTool.from_function(
        func=_query_genie_wrapper,
        name=tool_name,
        description=description,
        args_schema=GenieQueryInput,
    )


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
            genie_tool = _build_genie_tool(tool_entry, session_data, genie_index)
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
                    "server_uri": tool_entry.server_uri,
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
