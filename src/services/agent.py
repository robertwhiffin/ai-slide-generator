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
from databricks_langchain import ChatDatabricks
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.config.client import get_databricks_client
from src.config.settings import get_settings
from src.services.tools import query_genie_space

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
    conversation_id: str | None = Field(
        default=None,
        description="Optional conversation ID to continue existing conversation",
    )


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

        # Create LangChain components
        self.model = self._create_model()
        self.tools = self._create_tools()
        self.prompt = self._create_prompt()
        self.agent_executor = self._create_agent_executor()

        # Session storage for multi-turn conversations
        # Structure: {session_id: {chat_history, genie_conversation_id, metadata}}
        self.sessions: dict[str, dict[str, Any]] = {}

        logger.info("SlideGeneratorAgent initialized successfully")

    def _setup_mlflow(self) -> None:
        """Configure MLflow tracking and experiment."""
        try:
            mlflow.set_tracking_uri(self.settings.mlflow.tracking_uri)
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
                    "tracking_uri": self.settings.mlflow.tracking_uri,
                    "experiment_name": self.settings.mlflow.experiment_name,
                    "experiment_id": self.experiment_id,
                },
            )
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

    def _create_tools(self) -> list[StructuredTool]:
        """Create LangChain tools from tools.py functions."""

        def _query_genie_wrapper(query: str, conversation_id: str | None = None) -> str:
            """Wrapper that returns formatted string for LLM consumption."""
            result = query_genie_space(query, conversation_id)
            # Return formatted string for LLM
            return (
                f"Data retrieved successfully:\n\n"
                f"{result['data']}\n\n"
                f"Conversation ID: {result['conversation_id']}\n\n"
                f"Use this conversation_id for follow-up queries to maintain context."
            )

        genie_tool = StructuredTool.from_function(
            func=_query_genie_wrapper,
            name="query_genie_space",
            description=(
                "Query Databricks Genie for data using natural language. "
                "Genie can understand natural language questions and convert them to SQL. "
                "Use this tool to retrieve data needed for the presentation. "
                "You can make multiple queries to gather comprehensive data. "
                "Use the conversation_id from previous responses for follow-up questions."
                f" Below is a description of the data available within the Genie space:\n\n {self.settings.genie.description}"
            ),
            args_schema=GenieQueryInput,
        )

        logger.info("Tools created", extra={"tool_count": 1})
        return [genie_tool]

    def _create_prompt(self) -> ChatPromptTemplate:
        """Create prompt template with system prompt from config and chat history."""
        system_prompt = self.settings.prompts.get("system_prompt", "")
        
        if not system_prompt:
            raise AgentError("System prompt not found in configuration")

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

    def _create_agent_executor(self) -> AgentExecutor:
        """
        Create agent executor with model, tools, and prompt.

        Returns:
            Configured AgentExecutor

        IMPORTANT: Set return_intermediate_steps=True to capture all
        messages for chat interface display.

        Note: Chat history is managed per-session and passed via agent_input.
        """
        try:
            # Create agent
            agent = create_tool_calling_agent(self.model, self.tools, self.prompt)

            # Create executor with intermediate steps enabled
            agent_executor = AgentExecutor(
                agent=agent,
                tools=self.tools,
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
        - Genie conversation_id for context continuity
        - Session metadata
        """
        session_id = str(uuid.uuid4())
        
        # Create chat history for this session
        chat_history = ChatMessageHistory()
        
        # Initialize session data
        self.sessions[session_id] = {
            "chat_history": chat_history,
            "genie_conversation_id": None,
            "created_at": datetime.utcnow().isoformat(),
            "message_count": 0,
        }
        
        logger.info("Created new session", extra={"session_id": session_id})
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
        max_slides: int = 10,
        genie_space_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate HTML slides from a natural language question (multi-turn support).

        Args:
            question: Natural language question about data
            session_id: Session identifier for multi-turn conversation
            max_slides: Maximum number of slides to generate
            genie_space_id: Optional Genie space ID (uses default if None)

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
        
        logger.info(
            "Starting slide generation",
            extra={
                "question": question,
                "session_id": session_id,
                "max_slides": max_slides,
                "message_count": session["message_count"],
            },
        )

        try:
            # Use mlflow.start_span for manual tracing
            with mlflow.start_span(name="generate_slides") as span:
                # Set custom attributes
                span.set_attribute("question", question)
                span.set_attribute("session_id", session_id)
                span.set_attribute("max_slides", max_slides)
                span.set_attribute("model_endpoint", self.settings.llm.endpoint)
                span.set_attribute("message_count", session["message_count"])

                # Format input for agent with chat history
                agent_input = {
                    "input": question,
                    "max_slides": max_slides,
                    "chat_history": chat_history.messages,  # Pass chat history messages
                }

                # Invoke agent
                result = self.agent_executor.invoke(agent_input)

                # Extract results
                html_output = result["output"]
                intermediate_steps = result.get("intermediate_steps", [])

                # Extract Genie conversation_id from tool responses
                genie_conversation_id = self._extract_genie_conversation_id(intermediate_steps)
                if genie_conversation_id:
                    session["genie_conversation_id"] = genie_conversation_id

                # Update chat history with this interaction
                chat_history.add_message(HumanMessage(content=question))
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

                metadata = {
                    "latency_seconds": latency,
                    "tool_calls": len(intermediate_steps),
                    "timestamp": end_time.isoformat(),
                    "message_count": session["message_count"],
                }

                # Set span attributes
                span.set_attribute("output_length", len(html_output))
                span.set_attribute("tool_calls", len(intermediate_steps))
                span.set_attribute("latency_seconds", latency)
                span.set_attribute("status", "success")
                if genie_conversation_id:
                    span.set_attribute("genie_conversation_id", genie_conversation_id)

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
                }

        except TimeoutError as e:
            logger.error(f"LLM request timed out: {e}")
            raise LLMInvocationError(f"LLM request timed out: {e}") from e
        except Exception as e:
            logger.error(f"Slide generation failed: {e}", exc_info=True)
            raise AgentError(f"Slide generation failed: {e}") from e

    def _extract_genie_conversation_id(self, intermediate_steps: list[tuple]) -> str | None:
        """
        Extract Genie conversation_id from tool responses.

        Args:
            intermediate_steps: List of (AgentAction, observation) tuples

        Returns:
            Conversation ID if found, None otherwise
        """
        for action, observation in intermediate_steps:
            if action.tool == "query_genie_space":
                # Parse the observation string to extract conversation_id
                observation_str = str(observation)
                if "Conversation ID:" in observation_str:
                    # Extract the ID from the formatted string
                    lines = observation_str.split("\n")
                    for line in lines:
                        if line.startswith("Conversation ID:"):
                            conv_id = line.replace("Conversation ID:", "").strip()
                            if conv_id:
                                return conv_id
        return None


def create_agent() -> SlideGeneratorAgent:
    """
    Factory function to create a SlideGeneratorAgent instance.

    Returns:
        Configured SlideGeneratorAgent instance

    Raises:
        AgentError: If agent creation fails
    """
    return SlideGeneratorAgent()
