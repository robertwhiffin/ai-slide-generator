"""
LangChain agent for slide generation using Databricks LLMs and tools.

This module implements a simple LangChain wrapper that enables tool-using LLM
capabilities with MLflow tracing integration.
"""

import logging
from datetime import datetime
from typing import Any

import mlflow
from databricks_langchain import ChatDatabricks
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
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
    Simple LangChain agent wrapper for slide generation.

    This agent uses a Databricks-hosted LLM with access to tools (Genie)
    to generate HTML slide decks from natural language questions.

    The agent is intentionally simple - it doesn't orchestrate complex
    workflows. Instead, it relies on a well-crafted system prompt to
    guide the LLM through:
    1. Using tools to gather data
    2. Analyzing the data
    3. Constructing a narrative
    4. Generating HTML slides

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
        """Create prompt template with system prompt from config."""
        system_prompt = self.settings.prompts.get("system_prompt", "")
        
        if not system_prompt:
            raise AgentError("System prompt not found in configuration")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                ("human", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )

        logger.info("Prompt template created")
        return prompt

    def _create_agent_executor(self) -> AgentExecutor:
        """
        Create agent executor with model, tools, and prompt.

        IMPORTANT: Set return_intermediate_steps=True to capture all
        messages for chat interface display.
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
        max_slides: int = 10,
        genie_space_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate HTML slides from a natural language question.

        Args:
            question: Natural language question about data
            max_slides: Maximum number of slides to generate
            genie_space_id: Optional Genie space ID (uses default if None)

        Returns:
            Dictionary containing:
                - html: HTML string containing complete slide deck
                - messages: List of all messages for chat interface
                - metadata: Execution metadata (tokens, latency, etc.)

        Raises:
            AgentError: If generation fails
        """
        start_time = datetime.utcnow()
        
        logger.info(
            "Starting slide generation",
            extra={
                "question": question,
                "max_slides": max_slides,
            },
        )

        try:
            # Use mlflow.start_span for manual tracing
            with mlflow.start_span(name="generate_slides") as span:
                # Set custom attributes
                span.set_attribute("question", question)
                span.set_attribute("max_slides", max_slides)
                span.set_attribute("model_endpoint", self.settings.llm.endpoint)

                # Format input for agent
                agent_input = {
                    "input": question,
                    "max_slides": max_slides,
                }

                # Invoke agent - LangChain operations traced automatically
                result = self.agent_executor.invoke(agent_input)

                # Extract results
                html_output = result["output"]
                intermediate_steps = result.get("intermediate_steps", [])

                # Format messages for chat interface
                messages = self._format_messages_for_chat(
                    question=question,
                    intermediate_steps=intermediate_steps,
                    final_output=html_output,
                )

                # Calculate metadata
                end_time = datetime.utcnow()
                latency = (end_time - start_time).total_seconds()

                metadata = {
                    "latency_seconds": latency,
                    "tool_calls": len(intermediate_steps),
                    "timestamp": end_time.isoformat(),
                }

                # Set span attributes
                span.set_attribute("output_length", len(html_output))
                span.set_attribute("tool_calls", len(intermediate_steps))
                span.set_attribute("latency_seconds", latency)
                span.set_attribute("status", "success")

                logger.info(
                    "Slide generation completed",
                    extra={
                        "latency_seconds": latency,
                        "tool_calls": len(intermediate_steps),
                        "output_length": len(html_output),
                    },
                )

                return {
                    "html": html_output,
                    "messages": messages,
                    "metadata": metadata,
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
