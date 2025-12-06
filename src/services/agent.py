"""
LangChain agent for slide generation using Databricks LLMs and tools.

This module implements a simple LangChain wrapper that enables tool-using LLM
capabilities with MLflow tracing integration.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

import mlflow
from bs4 import BeautifulSoup
from databricks_langchain import ChatDatabricks
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.core.databricks_client import get_databricks_client

from src.core.settings_db import get_settings
from src.services.tools import initialize_genie_conversation, query_genie_space
from src.utils.html_utils import extract_canvas_ids_from_script

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
        self.client = get_databricks_client()

        # Set up MLflow
        self._setup_mlflow()
        self.experiment_id=None

        # Create LangChain components (tools created per-request to bind session_id)
        self.model = self._create_model()
        self.prompt = self._create_prompt()

        # Session storage for multi-turn conversations
        # Structure: {session_id: {chat_history, genie_conversation_id, metadata}}
        self.sessions: dict[str, dict[str, Any]] = {}

        logger.info("SlideGeneratorAgent initialized successfully")

    def _setup_mlflow(self) -> None:
        """Configure MLflow tracking and experiment."""
        try:
            #mlflow.set_tracking_uri(self.settings.mlflow.tracking_uri)
            # Use the Databricks workspace for tracking
            tracking_uri = "databricks"
            mlflow.set_tracking_uri(tracking_uri)
            experiment = mlflow.get_experiment_by_name(self.settings.mlflow.experiment_name)
            if experiment is None:
                self.experiment_id = mlflow.create_experiment(self.settings.mlflow.experiment_name).experiment_id
                logger.info("Created new MLflow experiment", extra={"experiment_name": self.settings.mlflow.experiment_name, "experiment_id": self.experiment_id})
            else:
                self.experiment_id = experiment.experiment_id
                logger.info("MLflow experiment already exists", extra={"experiment_name": self.settings.mlflow.experiment_name, "experiment_id": self.experiment_id})
            mlflow.set_experiment(experiment_id=self.experiment_id)

            logger.info(
                "MLflow configured",
                extra={
                    #"tracking_uri": self.settings.mlflow.tracking_uri,
                    "tracking_uri": tracking_uri,
                    "experiment_name": self.settings.mlflow.experiment_name,
                    "experiment_id": self.experiment_id,
                },
            )
            # Enable LangChain autologging
            try:
                mlflow.langchain.autolog()
                logger.info("MLflow LangChain autologging enabled")
            except Exception as e:
                logger.error(f"Failed to enable MLflow LangChain autologging: {e}")
                pass
        except Exception as e:
            logger.warning(f"Failed to configure MLflow: {e}")
            # Continue without MLflow if it fails
            pass

    def _create_model(self) -> ChatDatabricks:
        """Create LangChain Databricks model."""
        try:
            model = ChatDatabricks(
                endpoint=self.settings.llm.endpoint,
                temperature=self.settings.llm.temperature,
                max_tokens=self.settings.llm.max_tokens,
                top_p=self.settings.llm.top_p,
            )

            logger.info(
                "ChatDatabricks model created",
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

        Args:
            session_id: Session identifier to bind to the tool

        Returns:
            List of StructuredTool instances for this session
        """
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
                "Query Databricks Genie for data using natural language. "
                "Genie can understand natural language questions and convert them to SQL. "
                "Use this tool to retrieve data needed for the presentation. "
                "You can make multiple queries to gather comprehensive data. "
                "The conversation context is automatically maintained across queries."
                f"\n\nData available in the Genie space:\n{self.settings.genie.description}"
            ),
            args_schema=GenieQueryInput,
        )

        logger.info("Tools created for session", extra={"session_id": session_id})
        return [genie_tool]

    def _create_prompt(self) -> ChatPromptTemplate:
        """Create prompt template with system prompt from settings and chat history."""
        system_prompt = self.settings.prompts.get("system_prompt", "")
        editing_prompt = self.settings.prompts.get("slide_editing_instructions", "")

        if not system_prompt:
            raise AgentError("System prompt not found in configuration")

        if editing_prompt:
            system_prompt = f"{system_prompt.rstrip()}\n\n{editing_prompt.strip()}"

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("placeholder", "{chat_history}"),  # Conversation history for multi-turn
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )

        logger.info("Prompt template created with chat history support")
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
        """
        try:
            # Create agent with session-specific tools
            agent = create_tool_calling_agent(self.model, tools, self.prompt)

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

    def create_session(self) -> str:
        """
        Create a new conversation session.

        Returns:
            Unique session ID

        Each session maintains its own:
        - Chat message history
        - Genie conversation_id (initialized immediately)
        - Session metadata
        
        Note: Genie conversation is initialized upfront to eliminate
        the need for the LLM to track conversation IDs.
        """
        session_id = str(uuid.uuid4())

        logger.info("Creating new session", extra={"session_id": session_id})

        # Initialize Genie conversation upfront
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

        # Create chat history for this session
        chat_history = ChatMessageHistory()

        # Initialize session data
        self.sessions[session_id] = {
            "chat_history": chat_history,
            "genie_conversation_id": genie_conversation_id,  # Set immediately
            "created_at": datetime.utcnow().isoformat(),
            "message_count": 0,
        }

        logger.info("Session created successfully", extra={"session_id": session_id})
        return session_id

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

    def _format_slide_context(self, slide_context: dict[str, Any]) -> str:
        """
        Format slide context for injection into the user message.

        Args:
            slide_context: Dict with 'indices' and 'slide_htmls' keys

        Returns:
            Formatted string wrapped with slide-context markers
        """
        context_parts = ["<slide-context>"]
        for html in slide_context.get("slide_htmls", []):
            context_parts.append(html)
        context_parts.append("</slide-context>")
        return "\n\n".join(context_parts)

    def _parse_slide_replacements(
        self,
        llm_response: str,
        original_indices: list[int],
    ) -> dict[str, Any]:
        """
        Parse LLM response to extract slide replacements.

        The LLM can return any number of slides. This method extracts all
        <div class="slide"> elements and returns them as replacements for the
        original contiguous block.

        Args:
            llm_response: Raw HTML response from LLM
            original_indices: List of original indices provided as context

        Returns:
            Dict with replacement details

        Raises:
            AgentError: If parsing fails or no slides found
        """
        if not llm_response or not llm_response.strip():
            raise AgentError("LLM response is empty; expected slide HTML output")

        soup = BeautifulSoup(llm_response, "html.parser")
        slide_divs = soup.find_all("div", class_="slide")
        script_blocks, script_canvas_ids = self._extract_script_blocks(soup)

        if not slide_divs:
            raise AgentError(
                "No slide divs found in LLM response. Expected at least one "
                "<div class='slide'>...</div> block."
            )

        replacement_slides = [str(slide) for slide in slide_divs]
        canvas_ids = self._extract_canvas_ids(slide_divs)

        for idx, slide_html in enumerate(replacement_slides):
            if not slide_html.strip():
                raise AgentError(f"Slide {idx} is empty")
            if 'class="slide"' not in slide_html:
                raise AgentError(f"Slide {idx} missing class='slide' wrapper")

        original_count = len(original_indices)
        replacement_count = len(replacement_slides)
        start_index = original_indices[0] if original_indices else 0

        logger.info(
            "Parsed slide replacements",
            extra={
                "original_count": original_count,
                "replacement_count": replacement_count,
                "start_index": start_index,
            },
        )

        return {
            "replacement_slides": replacement_slides,
            "replacement_scripts": "\n".join(script_blocks) if script_blocks else "",
            "original_indices": original_indices,
            "start_index": start_index,
            "original_count": original_count,
            "replacement_count": replacement_count,
            "net_change": replacement_count - original_count,
            "success": True,
            "error": None,
            "operation": "edit",
            "canvas_ids": canvas_ids,
            "script_canvas_ids": script_canvas_ids,
        }

    @staticmethod
    def _extract_canvas_ids(slide_divs: list[Any]) -> list[str]:
        """Collect canvas ids from the replacement slides."""
        ids: list[str] = []
        for slide in slide_divs:
            for canvas in slide.find_all("canvas"):
                canvas_id = canvas.get("id")
                if canvas_id:
                    ids.append(canvas_id)
        return ids

    def _extract_script_blocks(self, soup: BeautifulSoup) -> tuple[list[str], list[str]]:
        """
        Extract script blocks marked for slide replacements and collect canvas ids referenced.
        """
        script_blocks: list[str] = []
        script_canvas_ids: list[str] = []

        script_tags = soup.find_all("script")
        tagged_scripts = [tag for tag in script_tags if tag.get("data-slide-scripts") is not None]

        # Fallback: if no scripts were tagged, use trailing scripts after the slide blocks
        candidate_scripts = tagged_scripts
        if not candidate_scripts:
            candidate_scripts = script_tags

        for tag in candidate_scripts:
            script_text = tag.get_text() or ""
            script_canvas_ids.extend(extract_canvas_ids_from_script(script_text))

            if script_text.strip():
                script_blocks.append(script_text.strip())

        return script_blocks, script_canvas_ids

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

        if slide_context:
            context_str = self._format_slide_context(slide_context)
            full_question = f"{context_str}\n\n{question}"
            logger.info(
                "Slide editing mode",
                extra={
                    "session_id": session_id,
                    "selected_indices": slide_context.get("indices", []),
                    "slide_count": len(slide_context.get("indices", [])),
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
            # Use mlflow.start_span for manual tracing
            with mlflow.start_span(name="generate_slides") as span:
                # Set custom attributes
                span.set_attribute("question", question)
                span.set_attribute("session_id", session_id)
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
                    "replacement_info": replacement_info,
                    "parsed_output": parsed_output,
                }

        except TimeoutError as e:
            logger.error(f"LLM request timed out: {e}")
            raise LLMInvocationError(f"LLM request timed out: {e}") from e
        except Exception as e:
            logger.error(f"Slide generation failed: {e}", exc_info=True)
            raise AgentError(f"Slide generation failed: {e}") from e


def create_agent() -> SlideGeneratorAgent:
    """
    Factory function to create a SlideGeneratorAgent instance.

    Returns:
        Configured SlideGeneratorAgent instance

    Raises:
        AgentError: If agent creation fails
    """
    return SlideGeneratorAgent()
