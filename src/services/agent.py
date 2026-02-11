"""
LangChain agent for slide generation using Databricks LLMs and tools.

This module implements a simple LangChain wrapper that enables tool-using LLM
capabilities with MLflow tracing integration.
"""

import logging
import queue
import re
import uuid
from datetime import datetime
from typing import Any, Optional, Tuple

import mlflow
from bs4 import BeautifulSoup
from databricks_langchain import ChatDatabricks
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.core.databricks_client import (
    get_current_username,
    get_databricks_client,
    get_service_principal_folder,
    get_system_client,
    get_user_client,
)
from src.core.settings_db import get_settings
from src.domain.slide import Slide
from src.services.image_tools import SearchImagesInput, search_images
from src.services.tools import initialize_genie_conversation, query_genie_space
from src.utils.html_utils import extract_canvas_ids_from_script, split_script_by_canvas
from src.utils.js_validator import validate_and_fix_javascript

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Base exception for agent errors."""

    pass


class LLMInvocationError(AgentError):
    """Raised when LLM invocation fails."""

    pass


class ToolExecutionError(AgentError):
    """Raised when tool execution fails."""

    pass


class GenieQueryInput(BaseModel):
    """Input schema for Genie query tool."""

    query: str = Field(description="Natural language question")


class SlideGeneratorAgent:
    """
    Multi-turn LangChain agent for slide generation.

    This agent uses a Databricks-hosted LLM with access to tools (Genie)
    to generate HTML slide decks from natural language questions. Supports
    multi-turn conversations for iterative refinement and editing.

    The agent is intentionally simple - it doesn't orchestrate complex
    workflows. Instead, it relies on a well-crafted system prompt to
    guide the LLM through:
    1. Using tools to gather data
    2. Analyzing the data
    3. Constructing a narrative
    4. Generating HTML slides

    Multi-turn capabilities:
    - Session management for conversation state
    - ConversationBufferMemory for full history
    - Genie conversation_id persistence across turns

    All operations are traced via MLflow for observability.
    All intermediate steps are captured for chat interface display.
    """

    def __init__(self):
        """Initialize agent with LangChain model and tools."""
        logger.info("Initializing SlideGeneratorAgent")

        self.settings = get_settings()
        self.client = get_databricks_client()  # System client for non-user operations

        # Set up MLflow tracking (experiment created per-session)
        self._setup_mlflow_tracking()

        # Create LangChain prompt (model created per-request for user context)
        self.prompt = self._create_prompt()

        # Session storage for multi-turn conversations
        # Structure: {session_id: {chat_history, genie_conversation_id, experiment_id, experiment_url, username, metadata}}
        self.sessions: dict[str, dict[str, Any]] = {}

        logger.info("SlideGeneratorAgent initialized successfully")

    def _setup_mlflow_tracking(self) -> None:
        """Configure MLflow tracking URI only.
        
        Experiments are created per-session in create_session() to provide
        isolated tracking and user-specific permissions.
        """
        try:
            tracking_uri = "databricks"
            mlflow.set_tracking_uri(tracking_uri)
            logger.info("MLflow tracking configured", extra={"tracking_uri": tracking_uri})

            # Enable LangChain autologging
            try:
                mlflow.langchain.autolog()
                logger.info("MLflow LangChain autologging enabled")
            except Exception as e:
                logger.warning(f"Failed to enable MLflow LangChain autologging: {e}")
        except Exception as e:
            logger.warning(f"Failed to configure MLflow tracking: {e}")

    def _ensure_user_experiment(self, session_id: str, username: str) -> tuple[str, str]:
        """Ensure MLflow experiment exists for this user (one experiment per user).
        
        Creates an experiment if it doesn't exist, or returns the existing one.
        Experiment path:
        - Production: /Workspace/Users/{SP_CLIENT_ID}/{username}/ai-slide-generator
        - Local dev: /Workspace/Users/{username}/ai-slide-generator
        
        Args:
            session_id: Session identifier for logging
            username: User's email/username for path and permissions
            
        Returns:
            Tuple of (experiment_id, experiment_url)
        """
        import os

        # Determine experiment path based on environment
        sp_folder = get_service_principal_folder()
        
        if sp_folder:
            # Production: use service principal's folder
            experiment_path = f"{sp_folder}/{username}/ai-slide-generator"
        else:
            # Local development: use user's folder
            experiment_path = f"/Workspace/Users/{username}/ai-slide-generator"

        logger.info(
            f"Agent: Ensuring user MLflow experiment at path: {experiment_path}",
            extra={
                "session_id": session_id,
                "username": username,
                "experiment_path": experiment_path,
                "using_sp_folder": sp_folder is not None,
            },
        )

        try:
            # Check if experiment already exists
            experiment = mlflow.get_experiment_by_name(experiment_path)
            
            if experiment:
                experiment_id = experiment.experiment_id
                logger.info(
                    f"Using existing user experiment: {experiment_id}",
                    extra={"session_id": session_id, "experiment_path": experiment_path},
                )
            else:
                # Ensure parent folder exists before creating experiment
                if sp_folder:
                    from src.core.databricks_client import ensure_workspace_folder
                    parent_folder = f"{sp_folder}/{username}"
                    try:
                        ensure_workspace_folder(parent_folder)
                    except Exception as e:
                        logger.warning(f"Failed to create parent folder {parent_folder}: {e}")
                        # Continue anyway - experiment creation might still work
                
                # Create new experiment for user
                experiment_id = mlflow.create_experiment(experiment_path)
                logger.info(
                    f"Created new user experiment: {experiment_id}",
                    extra={"session_id": session_id, "experiment_path": experiment_path},
                )

                # Grant user CAN_MANAGE permission (only needed when using SP folder)
                if sp_folder:
                    self._grant_experiment_permission(experiment_id, username, session_id)

            # Construct experiment URL (ensure https:// prefix for proper linking)
            host = os.getenv("DATABRICKS_HOST", "").rstrip("/")
            if host and not host.startswith("http"):
                host = f"https://{host}"
            experiment_url = f"{host}/ml/experiments/{experiment_id}"

            return experiment_id, experiment_url

        except Exception as e:
            logger.error(
                f"Failed to ensure user experiment: {e}",
                extra={
                    "session_id": session_id,
                    "experiment_path": experiment_path,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise AgentError(f"Failed to create MLflow experiment: {e}") from e

    def _grant_experiment_permission(
        self, experiment_id: str, username: str, session_id: str
    ) -> None:
        """Grant CAN_MANAGE permission on experiment to user.
        
        Uses the Databricks SDK to set experiment permissions so users can
        view and manage their session's experiment data.
        
        Args:
            experiment_id: MLflow experiment ID
            username: User's email/username to grant permission to
            session_id: Session ID for logging context
        """
        from databricks.sdk.service.ml import (
            ExperimentAccessControlRequest,
            ExperimentPermissionLevel,
        )

        try:
            client = get_system_client()
            client.experiments.set_permissions(
                experiment_id=experiment_id,
                access_control_list=[
                    ExperimentAccessControlRequest(
                        user_name=username,
                        permission_level=ExperimentPermissionLevel.CAN_MANAGE,
                    )
                ],
            )
            logger.info(
                "Granted experiment permission",
                extra={
                    "session_id": session_id,
                    "experiment_id": experiment_id,
                    "username": username,
                    "permission": "CAN_MANAGE",
                },
            )
        except Exception as e:
            # Log warning but don't fail - user can still view via SP permissions
            logger.warning(
                f"Failed to grant experiment permission: {e}",
                extra={
                    "session_id": session_id,
                    "experiment_id": experiment_id,
                    "username": username,
                    "error": str(e),
                },
            )

    def _create_model(self) -> ChatDatabricks:
        """Create LangChain Databricks model with user context.

        Creates a new ChatDatabricks instance per request using the
        user-scoped WorkspaceClient. This ensures LLM calls are made
        with the authenticated user's permissions.
        """
        try:
            # Get user-scoped client (falls back to system client in local dev)
            user_client = get_user_client()

            model = ChatDatabricks(
                endpoint=self.settings.llm.endpoint,
                temperature=self.settings.llm.temperature,
                max_tokens=self.settings.llm.max_tokens,
                top_p=self.settings.llm.top_p,
                workspace_client=user_client,
            )

            logger.info(
                "ChatDatabricks model created with user context",
                extra={
                    "endpoint": self.settings.llm.endpoint,
                    "temperature": self.settings.llm.temperature,
                    "max_tokens": self.settings.llm.max_tokens,
                },
            )

            return model
        except Exception as e:
            raise AgentError(f"Failed to create ChatDatabricks model: {e}") from e

    def _create_tools_for_session(self, session_id: str) -> list[StructuredTool]:
        """Create LangChain tools with session_id bound via closure.

        This eliminates the race condition from using self.current_session_id
        by binding the session_id at tool creation time.

        When no Genie space is configured, returns an empty list and the agent
        runs in prompt-only mode without data query capabilities.

        Args:
            session_id: Session identifier to bind to the tool

        Returns:
            List of StructuredTool instances for this session (empty if no Genie)
        """
        # Image search tool (always available, not Genie-dependent)
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

        # Return image tool only if no Genie configured
        if not self.settings.genie:
            logger.info(
                "No Genie configured, running with image tools only",
                extra={"session_id": session_id},
            )
            return [image_search_tool]

        # Get session reference for use in closure
        session = self.sessions.get(session_id)
        if session is None:
            raise ToolExecutionError(f"Session not found: {session_id}")

        def _query_genie_wrapper(query: str) -> str:
            """
            Wrapper that auto-injects conversation_id from bound session.

            The session_id is captured via closure at tool creation time,
            eliminating race conditions from concurrent requests.
            """
            conversation_id = session["genie_conversation_id"]
            if conversation_id is None:
                # Initialize new Genie conversation (happens after profile reload)
                logger.info(
                    "Initializing new Genie conversation for session",
                    extra={"session_id": session_id},
                )
                try:
                    new_conv_id = initialize_genie_conversation()
                    session["genie_conversation_id"] = new_conv_id
                    conversation_id = new_conv_id
                    logger.info(
                        "New Genie conversation initialized",
                        extra={
                            "session_id": session_id,
                            "genie_conversation_id": conversation_id,
                        },
                    )
                except Exception as e:
                    logger.error(f"Failed to initialize Genie conversation: {e}")
                    raise ToolExecutionError(f"Failed to initialize Genie conversation: {e}") from e

            # Query Genie with automatic conversation_id
            result = query_genie_space(query, conversation_id)

            # Format response for LLM (no conversation_id exposed)
            response_parts = []

            if result.get('message'):
                response_parts.append(f"Genie response: {result['message']}")

            if result.get('data'):
                response_parts.append(f"Data retrieved:\n\n{result['data']}")

            if not response_parts:
                return "Query completed but no data or message was returned."

            return "\n\n".join(response_parts)

        genie_tool = StructuredTool.from_function(
            func=_query_genie_wrapper,
            name="query_genie_space",
            description=(
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
                f"DATA AVAILABLE:\n{self.settings.genie.description}"
            ),
            args_schema=GenieQueryInput,
        )

        logger.info("Tools created for session", extra={"session_id": session_id})
        return [genie_tool, image_search_tool]

    def _create_prompt(self) -> ChatPromptTemplate:
        """Create prompt template with system prompt from settings and chat history.
        
        Prompt structure (when all components present):
        1. Deck prompt (from library) - defines presentation type/content (WHAT to create)
        2. Slide style (from library) - defines visual appearance (HOW it should look)
        3. System prompt - defines technical generation rules (HOW to generate valid HTML/charts)
        4. Slide editing instructions - defines editing behavior
        
        The system prompt is tool-agnostic - the LLM discovers available tools
        through the tool binding mechanism, not the prompt.
        """
        deck_prompt = self.settings.prompts.get("deck_prompt", "")
        slide_style = self.settings.prompts.get("slide_style", "")
        system_prompt = self.settings.prompts.get("system_prompt", "")
        editing_prompt = self.settings.prompts.get("slide_editing_instructions", "")

        if not system_prompt:
            raise AgentError("System prompt not found in configuration")
        if not slide_style:
            raise AgentError("Slide style not found in configuration")

        # Build the complete system prompt
        prompt_parts = []
        
        # Deck prompt comes first - sets context for what type of presentation to create
        if deck_prompt:
            prompt_parts.append(f"PRESENTATION CONTEXT:\n{deck_prompt.strip()}")
        
        # Slide style defines visual appearance (user-controllable)
        if slide_style:
            prompt_parts.append(slide_style.strip())
        
        # Core system prompt for technical slide generation (hidden from regular users)
        prompt_parts.append(system_prompt.rstrip())
        
        # Editing instructions appended at the end
        if editing_prompt:
            prompt_parts.append(editing_prompt.strip())

        # Image tool instructions (conditional on image_guidelines)
        image_guidelines = self.settings.prompts.get("image_guidelines", "")

        image_section = (
            "IMAGE SUPPORT:\n"
            "You have access to user-uploaded images via the search_images tool.\n\n"
            "WHEN TO USE search_images:\n"
            "- Use search_images ONLY when the user explicitly requests images in their message\n"
            "- When the user attaches images to their message (image context will be provided)\n"
            "- Do NOT call search_images on every request — only when images are relevant\n\n"
            "HOW TO USE IMAGES:\n"
            '1. Call search_images to find matching images (try broad search first, then filter)\n'
            '2. Embed them using: <img src="{{image:ID}}" alt="description" />\n'
            '3. For CSS backgrounds: background-image: url(\'{{image:ID}}\');\n'
            '4. The system will replace {{image:ID}} with the actual image data\n\n'
            "IMPORTANT RULES:\n"
            "- NEVER guess or fabricate image IDs — only use IDs returned by search_images or image guidelines\n"
            "- DO NOT attempt to generate or guess base64 image data\n"
            "- If no images are found, generate slides without images rather than using fake IDs"
        )

        if image_guidelines.strip():
            image_section += (
                "\n\n"
                "IMAGE GUIDELINES (from slide style):\n"
                "Follow these instructions for which images to use. "
                "The image IDs listed here are pre-validated — use them directly without calling search_images.\n\n"
                f"{image_guidelines.strip()}"
            )

        prompt_parts.append(image_section)

        full_system_prompt = "\n\n".join(prompt_parts)

        # Escape curly braces to allow user prompts with HTML/JS/JSON content
        # LangChain's f-string template format interprets {var} as variables
        full_system_prompt = full_system_prompt.replace("{", "{{").replace("}", "}}")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", full_system_prompt),
                ("placeholder", "{chat_history}"),  # Conversation history for multi-turn
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )

        logger.info(
            "Prompt template created",
            extra={
                "has_deck_prompt": bool(deck_prompt),
                "has_slide_style": bool(slide_style),
                "has_editing_prompt": bool(editing_prompt),
            }
        )
        return prompt

    def _create_agent_executor(self, tools: list[StructuredTool]) -> AgentExecutor:
        """
        Create agent executor with model, tools, and prompt.

        Args:
            tools: List of tools to bind to this executor

        Returns:
            Configured AgentExecutor

        IMPORTANT: Set return_intermediate_steps=True to capture all
        messages for chat interface display.

        Note: Chat history is managed per-session and passed via agent_input.
        Model is created per-request to use user-scoped credentials.
        """
        try:
            # Create model per-request for user context (Genie/LLM permissions)
            model = self._create_model()

            # Create agent with session-specific tools
            agent = create_tool_calling_agent(model, tools, self.prompt)

            # Create executor with intermediate steps enabled
            agent_executor = AgentExecutor(
                agent=agent,
                tools=tools,
                return_intermediate_steps=True,
                verbose=True,
                max_iterations=1000,
                max_execution_time=self.settings.llm.timeout,
            )

            logger.info("Agent executor created")
            return agent_executor

        except Exception as e:
            raise AgentError(f"Failed to create agent executor: {e}") from e

    def create_session(self) -> dict[str, Any]:
        """
        Create a new conversation session with per-session MLflow experiment.

        Returns:
            Dictionary containing:
            - session_id: Unique session identifier
            - experiment_url: URL to the MLflow experiment for this session

        Each session maintains its own:
        - Chat message history
        - Genie conversation_id (initialized if Genie configured, None otherwise)
        - MLflow experiment (created in SP folder with user permissions)
        - Session metadata
        
        Note: Genie conversation is initialized upfront when configured.
        Sessions without Genie run in prompt-only mode.
        """
        session_id = str(uuid.uuid4())

        logger.info("Creating new session", extra={"session_id": session_id})

        # Get current username for experiment path and permissions
        try:
            username = get_current_username()
            logger.info(
                "Retrieved username for session",
                extra={"session_id": session_id, "username": username},
            )
        except Exception as e:
            logger.error(f"Failed to get current username: {e}")
            raise AgentError(f"Failed to get current username: {e}") from e

        # Ensure user's MLflow experiment exists (one per user)
        experiment_id = None
        experiment_url = None
        try:
            experiment_id, experiment_url = self._ensure_user_experiment(
                session_id, username
            )
            # Set as active experiment for this session
            mlflow.set_experiment(experiment_id=experiment_id)
        except Exception as e:
            logger.warning(
                f"Failed to ensure user experiment, continuing without MLflow: {e}",
                extra={"session_id": session_id, "error": str(e)},
            )

        # Initialize Genie conversation only if configured
        genie_conversation_id = None
        if self.settings.genie:
            try:
                genie_conversation_id = initialize_genie_conversation()
                logger.info(
                    "Genie conversation initialized for session",
                    extra={
                        "session_id": session_id,
                        "genie_conversation_id": genie_conversation_id,
                    },
                )
            except Exception as e:
                logger.error(f"Failed to initialize Genie conversation: {e}")
                raise AgentError(f"Failed to initialize Genie conversation: {e}") from e
        else:
            logger.info(
                "No Genie configured, session will run in prompt-only mode",
                extra={"session_id": session_id},
            )

        # Create chat history for this session
        chat_history = ChatMessageHistory()

        # Initialize session data with experiment info and metadata for MLflow tags
        profile_name = self.settings.profile_name or "default"
        session_timestamp = datetime.utcnow().isoformat()
        self.sessions[session_id] = {
            "chat_history": chat_history,
            "genie_conversation_id": genie_conversation_id,  # None if no Genie
            "experiment_id": experiment_id,
            "experiment_url": experiment_url,
            "username": username,
            "profile_name": profile_name,
            "created_at": session_timestamp,
            "message_count": 0,
        }

        logger.info(
            "Session created successfully",
            extra={
                "session_id": session_id,
                "experiment_id": experiment_id,
                "experiment_url": experiment_url,
            },
        )

        return {
            "session_id": session_id,
            "experiment_url": experiment_url,
        }

    def get_session(self, session_id: str) -> dict[str, Any]:
        """
        Retrieve session data.

        Args:
            session_id: Session identifier

        Returns:
            Session data dictionary

        Raises:
            AgentError: If session not found
        """
        if session_id not in self.sessions:
            raise AgentError(f"Session not found: {session_id}")

        return self.sessions[session_id]

    def clear_session(self, session_id: str) -> None:
        """
        Clear a conversation session.

        Args:
            session_id: Session identifier

        Raises:
            AgentError: If session not found
        """
        if session_id not in self.sessions:
            raise AgentError(f"Session not found: {session_id}")

        del self.sessions[session_id]
        logger.info("Cleared session", extra={"session_id": session_id})

    def list_sessions(self) -> list[str]:
        """
        List all active session IDs.

        Returns:
            List of session IDs
        """
        return list(self.sessions.keys())

    def _format_slide_context(
        self, slide_context: dict[str, Any], is_add_operation: bool = False
    ) -> str:
        """
        Format slide context for injection into the user message.

        Args:
            slide_context: Dict with 'indices' and 'slide_htmls' keys
            is_add_operation: Whether this is an "add slide" operation (RC2)

        Returns:
            Formatted string wrapped with slide-context markers
        """
        context_parts = ["<slide-context>"]
        for html in slide_context.get("slide_htmls", []):
            context_parts.append(html)
        context_parts.append("</slide-context>")

        # RC2: Add explicit instruction for "add" operations
        if is_add_operation:
            context_parts.append(
                "\n\nIMPORTANT: The user wants to ADD a new slide. "
                "Return ONLY the new slide(s) to be added - the system will automatically append them to the deck. "
                "Do NOT return the existing slides shown above - just the new slide content."
            )

        return "\n\n".join(context_parts)

    def _detect_add_intent(self, message: str) -> bool:
        """
        RC2: Detect if user wants to add a new slide rather than edit existing ones.

        Returns:
            True if message indicates adding/inserting a new slide
        """
        add_patterns = [
            r"\badd\b.*\bslide\b",
            r"\binsert\b.*\bslide\b",
            r"\bappend\b.*\bslide\b",
            r"\bnew\s+slide\b",
            r"\bcreate\b.*\bslide\b",
            r"\badd\b.*\bat\s+the\s+(bottom|end|top|beginning)\b",
            r"\bslide\b.*\bat\s+the\s+(bottom|end|top|beginning)\b",
            r"\badd\b.*\b(summary|conclusion|key\s*takeaway)",
        ]

        lower_message = message.lower()
        for pattern in add_patterns:
            if re.search(pattern, lower_message):
                logger.info(
                    "Detected add slide intent",
                    extra={"message": message[:50], "matched_pattern": pattern},
                )
                return True
        return False

    def _validate_editing_response(self, llm_response: str) -> Tuple[bool, str]:
        """
        RC1: Validate that LLM response contains valid slide HTML.

        Returns:
            (is_valid, error_message)
        """
        if not llm_response or not llm_response.strip():
            return False, "Empty response"

        # Check for conversational text patterns (LLM confusion)
        confusion_patterns = [
            "I understand",
            "I cannot",
            "I'm sorry",
            "I don't",
            "There are no slides",
            "slides have been deleted",
            "no slides to display",
            "I've removed",
            "I've deleted",
            "cannot be displayed",
        ]

        lower_response = llm_response.lower()
        for pattern in confusion_patterns:
            if (
                pattern.lower() in lower_response
                and '<div class="slide"' not in llm_response
            ):
                return (
                    False,
                    f"LLM returned conversational text instead of HTML: {pattern}",
                )

        # Check for at least one slide div
        soup = BeautifulSoup(llm_response, "html.parser")
        slide_divs = soup.find_all("div", class_="slide")
        if not slide_divs:
            return False, "No <div class='slide'> elements found in response"

        return True, ""

    def _deduplicate_canvas_ids(
        self, html_content: str, scripts: str
    ) -> Tuple[str, str]:
        """
        RC4: Generate unique canvas IDs to prevent collisions.

        Appends a short unique suffix to all canvas IDs in HTML and scripts.

        Returns:
            (updated_html, updated_scripts)
        """
        soup = BeautifulSoup(html_content, "html.parser")
        canvases = soup.find_all("canvas")

        if not canvases:
            return html_content, scripts

        suffix = uuid.uuid4().hex[:6]
        id_mapping: dict[str, str] = {}

        # Update canvas IDs in HTML
        for canvas in canvases:
            old_id = canvas.get("id")
            if old_id:
                new_id = f"{old_id}_{suffix}"
                id_mapping[old_id] = new_id
                canvas["id"] = new_id

        updated_html = str(soup)
        updated_scripts = scripts or ""

        # Update references in scripts
        for old_id, new_id in id_mapping.items():
            # Update getElementById calls
            updated_scripts = re.sub(
                rf"getElementById\s*\(\s*['\"]({re.escape(old_id)})['\"]\s*\)",
                f"getElementById('{new_id}')",
                updated_scripts,
            )
            # Update querySelector calls
            updated_scripts = re.sub(
                rf"querySelector\s*\(\s*['\"]#({re.escape(old_id)})['\"]\s*\)",
                f"querySelector('#{new_id}')",
                updated_scripts,
            )
            # Update Canvas comments
            updated_scripts = re.sub(
                rf"//\s*Canvas:\s*{re.escape(old_id)}\b",
                f"// Canvas: {new_id}",
                updated_scripts,
                flags=re.IGNORECASE,
            )

        logger.info(
            "Deduplicated canvas IDs",
            extra={
                "original_ids": list(id_mapping.keys()),
                "suffix": suffix,
            },
        )

        return updated_html, updated_scripts

    def _parse_slide_replacements(
        self,
        llm_response: str,
        original_indices: list[int],
    ) -> dict[str, Any]:
        """
        Parse LLM response to extract slide replacements.

        The LLM can return any number of slides. This method extracts all
        <div class="slide"> elements and returns them as Slide objects
        with scripts attached via canvas ID matching.

        Scripts are associated with slides by:
        1. Building a canvas-to-slide index from the replacement slides
        2. Splitting each script by canvas using split_script_by_canvas()
        3. Assigning each segment to the slide containing its canvas
        4. Fallback: assign to last slide if no canvas match

        Args:
            llm_response: Raw HTML response from LLM
            original_indices: List of original indices provided as context

        Returns:
            Dict with replacement details including Slide objects with scripts

        Raises:
            AgentError: If parsing fails or no slides found
        """
        if not llm_response or not llm_response.strip():
            raise AgentError("LLM response is empty; expected slide HTML output")

        soup = BeautifulSoup(llm_response, "html.parser")
        slide_divs = soup.find_all("div", class_="slide")
        replacement_css = self._extract_css_from_response(soup)

        if not slide_divs:
            raise AgentError(
                "No slide divs found in LLM response. Expected at least one "
                "<div class='slide'>...</div> block."
            )

        # Build slides and canvas-to-slide index
        replacement_slides: list[Slide] = []
        canvas_to_slide: dict[str, int] = {}
        canvas_ids: list[str] = []

        for idx, slide_div in enumerate(slide_divs):
            slide_html = str(slide_div)
            if not slide_html.strip():
                raise AgentError(f"Slide {idx} is empty")

            slide = Slide(html=slide_html, slide_id=f"slide_{idx}")
            replacement_slides.append(slide)

            # Index canvases in this slide
            for canvas in slide_div.find_all("canvas"):
                canvas_id = canvas.get("id")
                if canvas_id:
                    canvas_to_slide[canvas_id] = idx
                    canvas_ids.append(canvas_id)

        # Assign scripts to slides via canvas matching
        for script_tag in soup.find_all("script", src=False):
            script_text = script_tag.get_text() or ""
            if not script_text.strip():
                continue

            # Split multi-canvas scripts into per-canvas segments
            segments = split_script_by_canvas(script_text)

            for segment_text, segment_canvas_ids in segments:
                assigned = False
                for canvas_id in segment_canvas_ids:
                    if canvas_id in canvas_to_slide:
                        slide_idx = canvas_to_slide[canvas_id]
                        replacement_slides[slide_idx].scripts += segment_text.strip() + "\n"
                        assigned = True
                        break

                # Fallback: assign to last slide if no canvas match
                if not assigned and replacement_slides:
                    replacement_slides[-1].scripts += segment_text.strip() + "\n"

        # RC4: Deduplicate canvas IDs to prevent collisions
        for slide in replacement_slides:
            if "<canvas" in slide.html:
                slide.html, slide.scripts = self._deduplicate_canvas_ids(
                    slide.html, slide.scripts
                )

        # RC5: Validate and fix JavaScript syntax
        for idx, slide in enumerate(replacement_slides):
            if slide.scripts:
                fixed_script, was_fixed, error = validate_and_fix_javascript(
                    slide.scripts
                )
                if was_fixed:
                    slide.scripts = fixed_script
                    logger.info(
                        f"Fixed JavaScript syntax in slide {idx}",
                        extra={"slide_index": idx},
                    )
                elif error:
                    logger.warning(
                        f"JavaScript syntax error in slide {idx} could not be fixed: {error}",
                        extra={"slide_index": idx, "error": error},
                    )

        original_count = len(original_indices)
        replacement_count = len(replacement_slides)
        start_index = original_indices[0] if original_indices else 0

        # RC2: Log warning if replacement results in slide loss
        if replacement_count < original_count:
            net_loss = original_count - replacement_count
            logger.warning(
                f"Slide replacement results in net loss of {net_loss} slides",
                extra={
                    "original_count": original_count,
                    "replacement_count": replacement_count,
                    "net_loss": net_loss,
                },
            )

        logger.info(
            "Parsed slide replacements",
            extra={
                "original_count": original_count,
                "replacement_count": replacement_count,
                "start_index": start_index,
                "canvas_ids": canvas_ids,
            },
        )

        return {
            "replacement_slides": replacement_slides,  # Slide objects with scripts
            "replacement_css": replacement_css,
            "original_indices": original_indices,
            "start_index": start_index,
            "original_count": original_count,
            "replacement_count": replacement_count,
            "net_change": replacement_count - original_count,
            "success": True,
            "error": None,
            "operation": "edit",
            "canvas_ids": canvas_ids,
        }

    def _extract_css_from_response(self, soup: BeautifulSoup) -> str:
        """Extract CSS content from LLM response.
        
        Args:
            soup: BeautifulSoup parsed HTML
            
        Returns:
            Concatenated CSS from all <style> tags
        """
        css_parts = []
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                css_parts.append(style_tag.string.strip())
        return '\n'.join(css_parts)

    def _validate_canvas_scripts_in_html(self, html_content: str) -> None:
        """
        Ensure each canvas in a generated deck has Chart.js initialization.

        Args:
            html_content: Complete HTML returned by the LLM

        Raises:
            AgentError: If a canvas lacks a corresponding script
        """
        if not html_content:
            return

        soup = BeautifulSoup(html_content, "html.parser")
        canvases = soup.find_all("canvas")
        canvas_ids = [
            canvas.get("id")
            for canvas in canvases
            if canvas.get("id")
        ]

        if not canvas_ids:
            return

        script_text = "\n".join(
            script_tag.get_text() or ""
            for script_tag in soup.find_all("script")
        )

        referenced_ids = set(extract_canvas_ids_from_script(script_text))
        missing = [cid for cid in canvas_ids if cid not in referenced_ids]

        if missing:
            raise AgentError(
                "Generated deck includes canvas elements without Chart.js scripts. "
                f"Add document.getElementById('<id>') initializers for: {', '.join(missing)}"
            )

    def _format_messages_for_chat(
        self,
        question: str,
        intermediate_steps: list[tuple],
        final_output: str,
    ) -> list[dict]:
        """
        Format agent execution into chat messages.

        Args:
            question: User's question
            intermediate_steps: List of (AgentAction, observation) tuples
            final_output: Final HTML output

        Returns:
            List of chat messages for UI display
        """
        messages = []

        # User message
        messages.append(
            {
                "role": "user",
                "content": question,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        # Process intermediate steps
        for action, observation in intermediate_steps:
            # Assistant message with tool call
            messages.append(
                {
                    "role": "assistant",
                    "content": f"Using tool: {action.tool}",
                    "tool_call": {
                        "name": action.tool,
                        "arguments": action.tool_input,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

            # Tool response message
            messages.append(
                {
                    "role": "tool",
                    "content": str(observation),
                    "tool_call_id": action.tool,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

        # Final assistant message with HTML
        messages.append(
            {
                "role": "assistant",
                "content": final_output,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        return messages

    def generate_slides(
        self,
        question: str,
        session_id: str,
        slide_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate HTML slides from a natural language question (multi-turn support).

        Creates tools and agent executor per-request with session_id bound via closure
        to eliminate race conditions in concurrent multi-user scenarios.

        Args:
            question: Natural language question about data
            session_id: Session identifier for multi-turn conversation
            slide_context: Optional context for editing existing slides

        Returns:
            Dictionary containing:
                - html: HTML string containing complete slide deck
                - messages: List of all messages for chat interface
                - metadata: Execution metadata (tokens, latency, etc.)
                - session_id: Session identifier
                - genie_conversation_id: Genie conversation ID for context

        Raises:
            AgentError: If generation fails or session not found
        """
        start_time = datetime.utcnow()

        # Get session data
        session = self.get_session(session_id)
        chat_history = session["chat_history"]

        # Create tools with session_id bound via closure (thread-safe)
        tools = self._create_tools_for_session(session_id)
        agent_executor = self._create_agent_executor(tools)

        editing_mode = slide_context is not None
        is_add_operation = False

        if slide_context:
            # RC2: Detect if this is an "add slide" operation
            is_add_operation = self._detect_add_intent(question)
            context_str = self._format_slide_context(
                slide_context, is_add_operation=is_add_operation
            )
            full_question = f"{context_str}\n\n{question}"
            logger.info(
                "Slide editing mode",
                extra={
                    "session_id": session_id,
                    "selected_indices": slide_context.get("indices", []),
                    "slide_count": len(slide_context.get("indices", [])),
                    "is_add_operation": is_add_operation,
                },
            )
        else:
            full_question = question
            logger.info(
                "Slide generation mode",
                extra={
                    "question": question,
                    "session_id": session_id,
                    "message_count": session["message_count"],
                },
            )

        try:
            # Set session's experiment as active for tracing
            if session.get("experiment_id"):
                mlflow.set_experiment(experiment_id=session["experiment_id"])

            # Use mlflow.start_span for manual tracing
            with mlflow.start_span(name="generate_slides") as span:
                # Set custom attributes including session metadata for filtering
                span.set_attribute("question", question)
                span.set_attribute("session_id", session_id)
                span.set_attribute("profile_name", session.get("profile_name", "unknown"))
                span.set_attribute("session_timestamp", session.get("created_at", ""))
                span.set_attribute("model_endpoint", self.settings.llm.endpoint)
                span.set_attribute("message_count", session["message_count"])
                span.set_attribute("mode", "edit" if editing_mode else "generate")

                # Format input for agent with chat history
                agent_input = {
                    "input": full_question,
                    "chat_history": chat_history.messages,  # Pass chat history messages
                }

                # Invoke agent with session-specific executor
                result = agent_executor.invoke(agent_input)

                # Extract results
                html_output = result["output"]
                intermediate_steps = result.get("intermediate_steps", [])

                # RC1: Validate response in editing mode and retry if invalid
                if editing_mode:
                    is_valid, error_msg = self._validate_editing_response(html_output)

                    if not is_valid:
                        logger.warning(
                            f"Invalid editing response, retrying: {error_msg}",
                            extra={"session_id": session_id},
                        )

                        # Retry with stronger prompt
                        retry_prompt = (
                            f"{full_question}\n\n"
                            "IMPORTANT: You MUST respond with valid HTML slide divs. "
                            "Do NOT respond with conversational text. "
                            "Return ONLY <div class='slide'>...</div> elements with their content."
                        )

                        retry_result = agent_executor.invoke(
                            {
                                "input": retry_prompt,
                                "chat_history": chat_history.messages,
                            }
                        )
                        html_output = retry_result["output"]
                        intermediate_steps = retry_result.get(
                            "intermediate_steps", intermediate_steps
                        )

                        # Validate retry
                        is_valid, error_msg = self._validate_editing_response(
                            html_output
                        )
                        if not is_valid:
                            logger.error(
                                f"LLM failed to return valid slide HTML after retry: {error_msg}",
                                extra={"session_id": session_id},
                            )
                            raise AgentError(
                                f"LLM failed to return valid slide HTML after retry: {error_msg}"
                            )

                # Note: genie_conversation_id already stored in session during create_session()
                # No need to extract from tool responses anymore

                # Update chat history with this interaction
                chat_history.add_message(HumanMessage(content=full_question))
                chat_history.add_message(AIMessage(content=html_output))

                # Format messages for chat interface
                messages = self._format_messages_for_chat(
                    question=question,
                    intermediate_steps=intermediate_steps,
                    final_output=html_output,
                )

                # Update session metadata
                session["message_count"] += 1
                session["last_interaction"] = datetime.utcnow().isoformat()

                # Calculate metadata
                end_time = datetime.utcnow()
                latency = (end_time - start_time).total_seconds()

                replacement_info: dict[str, Any] | None = None
                parsed_output: dict[str, Any]

                if editing_mode:
                    assert slide_context is not None
                    replacement_info = self._parse_slide_replacements(
                        llm_response=html_output,
                        original_indices=slide_context.get("indices", []),
                    )
                    # RC2: Pass is_add_operation flag for backend handling
                    if replacement_info:
                        replacement_info["is_add_operation"] = is_add_operation
                    parsed_output = replacement_info
                else:
                    self._validate_canvas_scripts_in_html(html_output)
                    parsed_output = {"html": html_output, "type": "full_deck"}

                metadata = {
                    "latency_seconds": latency,
                    "tool_calls": len(intermediate_steps),
                    "timestamp": end_time.isoformat(),
                    "message_count": session["message_count"],
                    "mode": "edit" if editing_mode else "generate",
                }

                # Set span attributes
                span.set_attribute("output_length", len(html_output))
                span.set_attribute("tool_calls", len(intermediate_steps))
                span.set_attribute("latency_seconds", latency)
                span.set_attribute("status", "success")
                span.set_attribute("genie_conversation_id", session["genie_conversation_id"])
                if replacement_info:
                    span.set_attribute("replacement_count", replacement_info["replacement_count"])

                logger.info(
                    "Slide generation completed",
                    extra={
                        "session_id": session_id,
                        "latency_seconds": latency,
                        "tool_calls": len(intermediate_steps),
                        "output_length": len(html_output),
                        "message_count": session["message_count"],
                    },
                )

                return {
                    "html": html_output,
                    "messages": messages,
                    "metadata": metadata,
                    "session_id": session_id,
                    "genie_conversation_id": session["genie_conversation_id"],
                    "experiment_url": session.get("experiment_url"),
                    "replacement_info": replacement_info,
                    "parsed_output": parsed_output,
                }

        except TimeoutError as e:
            logger.error(f"LLM request timed out: {e}")
            raise LLMInvocationError(f"LLM request timed out: {e}") from e
        except Exception as e:
            logger.error(f"Slide generation failed: {e}", exc_info=True)
            raise AgentError(f"Slide generation failed: {e}") from e

    def generate_slides_streaming(
        self,
        question: str,
        session_id: str,
        callback_handler: BaseCallbackHandler,
        slide_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate HTML slides with streaming callback support.

        Same as generate_slides() but accepts a callback handler for
        real-time event emission during execution.

        Args:
            question: Natural language question about data
            session_id: Session identifier for multi-turn conversation
            callback_handler: Callback handler for streaming events
            slide_context: Optional context for editing existing slides

        Returns:
            Dictionary containing generation results

        Raises:
            AgentError: If generation fails or session not found
        """
        start_time = datetime.utcnow()

        # Get session data
        session = self.get_session(session_id)
        chat_history = session["chat_history"]

        # Create tools with session_id bound via closure (thread-safe)
        tools = self._create_tools_for_session(session_id)

        # Create agent executor with callback handler
        agent_executor = self._create_agent_executor_with_callbacks(
            tools, [callback_handler]
        )

        editing_mode = slide_context is not None
        is_add_operation = False

        if slide_context:
            # RC2: Detect if this is an "add slide" operation
            is_add_operation = self._detect_add_intent(question)
            context_str = self._format_slide_context(
                slide_context, is_add_operation=is_add_operation
            )
            full_question = f"{context_str}\n\n{question}"
            logger.info(
                "Slide editing mode (streaming)",
                extra={
                    "session_id": session_id,
                    "selected_indices": slide_context.get("indices", []),
                    "slide_count": len(slide_context.get("indices", [])),
                    "is_add_operation": is_add_operation,
                },
            )
        else:
            full_question = question
            logger.info(
                "Slide generation mode (streaming)",
                extra={
                    "question": question,
                    "session_id": session_id,
                    "message_count": session["message_count"],
                },
            )

        try:
            # Set session's experiment as active for tracing
            if session.get("experiment_id"):
                mlflow.set_experiment(experiment_id=session["experiment_id"])

            with mlflow.start_span(name="generate_slides_streaming") as span:
                # Set custom attributes including session metadata for filtering
                span.set_attribute("question", question)
                span.set_attribute("session_id", session_id)
                span.set_attribute("profile_name", session.get("profile_name", "unknown"))
                span.set_attribute("session_timestamp", session.get("created_at", ""))
                span.set_attribute("model_endpoint", self.settings.llm.endpoint)
                span.set_attribute("message_count", session["message_count"])
                span.set_attribute("mode", "edit" if editing_mode else "generate")
                span.set_attribute("streaming", True)

                agent_input = {
                    "input": full_question,
                    "chat_history": chat_history.messages,
                }

                # Invoke agent with callback handler passed via config
                result = agent_executor.invoke(
                    agent_input,
                    config={"callbacks": [callback_handler]},
                )

                html_output = result["output"]
                intermediate_steps = result.get("intermediate_steps", [])

                # RC1: Validate response in editing mode and retry if invalid
                if editing_mode:
                    is_valid, error_msg = self._validate_editing_response(html_output)

                    if not is_valid:
                        logger.warning(
                            f"Invalid editing response, retrying: {error_msg}",
                            extra={"session_id": session_id},
                        )

                        # Retry with stronger prompt
                        retry_prompt = (
                            f"{full_question}\n\n"
                            "IMPORTANT: You MUST respond with valid HTML slide divs. "
                            "Do NOT respond with conversational text. "
                            "Return ONLY <div class='slide'>...</div> elements with their content."
                        )

                        retry_result = agent_executor.invoke(
                            {
                                "input": retry_prompt,
                                "chat_history": chat_history.messages,
                            },
                            config={"callbacks": [callback_handler]},
                        )
                        html_output = retry_result["output"]
                        intermediate_steps = retry_result.get(
                            "intermediate_steps", intermediate_steps
                        )

                        # Validate retry
                        is_valid, error_msg = self._validate_editing_response(
                            html_output
                        )
                        if not is_valid:
                            logger.error(
                                f"LLM failed to return valid slide HTML after retry: {error_msg}",
                                extra={"session_id": session_id},
                            )
                            raise AgentError(
                                f"LLM failed to return valid slide HTML after retry: {error_msg}"
                            )

                # Update chat history
                chat_history.add_message(HumanMessage(content=full_question))
                chat_history.add_message(AIMessage(content=html_output))

                # Update session metadata
                session["message_count"] += 1
                session["last_interaction"] = datetime.utcnow().isoformat()

                # Calculate metadata
                end_time = datetime.utcnow()
                latency = (end_time - start_time).total_seconds()

                replacement_info: dict[str, Any] | None = None

                if editing_mode:
                    assert slide_context is not None
                    replacement_info = self._parse_slide_replacements(
                        llm_response=html_output,
                        original_indices=slide_context.get("indices", []),
                    )
                    # RC2: Pass is_add_operation flag for backend handling
                    if replacement_info:
                        replacement_info["is_add_operation"] = is_add_operation
                else:
                    self._validate_canvas_scripts_in_html(html_output)

                metadata = {
                    "latency_seconds": latency,
                    "tool_calls": len(intermediate_steps),
                    "timestamp": end_time.isoformat(),
                    "message_count": session["message_count"],
                    "mode": "edit" if editing_mode else "generate",
                    "streaming": True,
                }

                span.set_attribute("output_length", len(html_output))
                span.set_attribute("tool_calls", len(intermediate_steps))
                span.set_attribute("latency_seconds", latency)
                span.set_attribute("status", "success")
                span.set_attribute("genie_conversation_id", session["genie_conversation_id"])

                logger.info(
                    "Streaming slide generation completed",
                    extra={
                        "session_id": session_id,
                        "latency_seconds": latency,
                        "tool_calls": len(intermediate_steps),
                        "output_length": len(html_output),
                    },
                )

                return {
                    "html": html_output,
                    "metadata": metadata,
                    "session_id": session_id,
                    "genie_conversation_id": session["genie_conversation_id"],
                    "experiment_url": session.get("experiment_url"),
                    "replacement_info": replacement_info,
                }

        except TimeoutError as e:
            logger.error(f"LLM request timed out (streaming): {e}")
            raise LLMInvocationError(f"LLM request timed out: {e}") from e
        except Exception as e:
            logger.error(f"Streaming slide generation failed: {e}", exc_info=True)
            raise AgentError(f"Slide generation failed: {e}") from e

    def _create_agent_executor_with_callbacks(
        self,
        tools: list[StructuredTool],
        callbacks: list[BaseCallbackHandler],
    ) -> AgentExecutor:
        """
        Create agent executor with callback handlers for streaming.

        Args:
            tools: List of tools to bind to this executor
            callbacks: List of callback handlers for event streaming

        Returns:
            Configured AgentExecutor with callbacks

        Note: Model is created per-request to use user-scoped credentials.
        """
        try:
            # Create model per-request for user context (Genie/LLM permissions)
            model = self._create_model()

            agent = create_tool_calling_agent(model, tools, self.prompt)

            agent_executor = AgentExecutor(
                agent=agent,
                tools=tools,
                callbacks=callbacks,
                return_intermediate_steps=True,
                verbose=True,
                max_iterations=1000,
                max_execution_time=self.settings.llm.timeout,
            )

            logger.info("Agent executor created with streaming callbacks")
            return agent_executor

        except Exception as e:
            raise AgentError(f"Failed to create agent executor: {e}") from e


def create_agent() -> SlideGeneratorAgent:
    """
    Factory function to create a SlideGeneratorAgent instance.

    Returns:
        Configured SlideGeneratorAgent instance

    Raises:
        AgentError: If agent creation fails
    """
    return SlideGeneratorAgent()
