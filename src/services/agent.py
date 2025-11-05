"""
Slide generator agent with MLFlow tracing.

This module implements the main agent that orchestrates slide generation using
LLMs and tools, with comprehensive MLFlow tracking and tracing.
"""

import json
import time
from typing import Any, Optional

import mlflow
from mlflow.tracking import MlflowClient

from src.config.client import get_databricks_client
from src.config.settings import get_settings
from src.services.tools import format_tool_result_for_llm, get_tool_schema, query_genie_space


class SlideGeneratorError(Exception):
    """Raised when slide generation fails."""

    pass


class SlideGeneratorAgent:
    """
    Tool-using agent for generating slide presentations.

    This agent orchestrates the process of:
    1. Analyzing user intent
    2. Gathering data via tools (Genie)
    3. Constructing a narrative
    4. Generating HTML slides

    All steps are fully traced with MLFlow for observability.
    """

    def __init__(self):
        """Initialize the agent with Databricks client and settings."""
        self.client = get_databricks_client()
        self.settings = get_settings()
        self.mlflow_client = MlflowClient()

        # Set MLFlow experiment
        mlflow.set_experiment(self.settings.mlflow.experiment_name)

        # Configure tracing
        if self.settings.mlflow.tracing.enabled:
            mlflow.tracing.enable()

    @mlflow.trace(name="generate_slides", span_type="AGENT")
    def generate_slides(
        self,
        question: str,
        max_slides: Optional[int] = None,
        genie_space_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Generate a slide deck for the given question.

        This is the main entry point for slide generation. It orchestrates
        all steps and returns the final HTML output with metadata.

        Args:
            question: User's question about data
            max_slides: Maximum number of slides (defaults to config value)
            genie_space_id: Genie space ID (defaults to config value)

        Returns:
            Dictionary containing:
                - html: Complete HTML slide deck as string
                - metadata: Run metadata (run_id, trace_url, metrics, etc.)

        Raises:
            SlideGeneratorError: If generation fails

        Example:
            >>> agent = SlideGeneratorAgent()
            >>> result = agent.generate_slides("What were Q4 sales?")
            >>> print(result['metadata']['trace_url'])
        """
        start_time = time.time()
        max_slides = max_slides or self.settings.output.default_max_slides

        # Start MLFlow run
        with mlflow.start_run(run_name=f"slide-gen-{int(time.time())}") as run:

            # Log input parameters
            mlflow.log_params(
                {
                    "question": question[:200],  # Truncate for display
                    "max_slides": max_slides,
                    "genie_space_id": genie_space_id or self.settings.genie.space_id,
                    "model_endpoint": self.settings.llm.endpoint,
                    "temperature": self.settings.llm.temperature,
                    "max_tokens": self.settings.llm.max_tokens,
                }
            )

            try:
                # Step 1: Analyze intent
                intent = self._analyze_intent(question, max_slides)
                mlflow.log_dict(intent, "intent_analysis.json")

                # Step 2: Execute tool loop to gather data
                data_context = self._execute_tool_loop(question, genie_space_id)
                mlflow.log_dict(data_context, "data_context.json")

                # Step 3: Interpret data
                insights = self._interpret_data(data_context, question)
                mlflow.log_dict(insights, "insights.json")

                # Step 4: Construct narrative
                narrative = self._construct_narrative(insights, intent, max_slides)
                mlflow.log_dict(narrative, "narrative.json")

                # Step 5: Generate HTML
                html_output = self._generate_html(narrative)
                mlflow.log_text(html_output, "output.html")

                # Calculate metrics
                execution_time = time.time() - start_time
                slide_count = self._count_slides(narrative)

                # Log success metrics
                mlflow.log_metrics(
                    {
                        "success": 1,
                        "slide_count": slide_count,
                        "execution_time_seconds": execution_time,
                    }
                )

                # Generate trace URL
                trace_url = self._get_trace_url(run.info.run_id)

                return {
                    "html": html_output,
                    "metadata": {
                        "run_id": run.info.run_id,
                        "experiment_id": run.info.experiment_id,
                        "trace_url": trace_url,
                        "slide_count": slide_count,
                        "execution_time_seconds": execution_time,
                        "question": question,
                    },
                }

            except Exception as e:
                execution_time = time.time() - start_time

                # Log failure
                mlflow.log_metrics(
                    {
                        "success": 0,
                        "execution_time_seconds": execution_time,
                    }
                )
                mlflow.log_param("error_message", str(e))
                mlflow.log_param("error_type", type(e).__name__)

                raise SlideGeneratorError(f"Failed to generate slides: {e}") from e

    @mlflow.trace(name="analyze_intent", span_type="LLM")
    def _analyze_intent(self, question: str, max_slides: int) -> dict[str, Any]:
        """
        Analyze user intent to determine data requirements and slide structure.

        Args:
            question: User's question
            max_slides: Maximum slides allowed

        Returns:
            Dictionary with intent analysis results
        """
        prompt = self.settings.prompts["intent_analysis"].format(
            question=question,
            min_slides=self.settings.output.min_slides,
            max_slides=max_slides,
        )

        response = self._call_llm(
            messages=[{"role": "user", "content": prompt}],
            span_name="intent_analysis_llm",
            temperature=self.settings.llm.temperature,
        )

        # Parse JSON response
        try:
            intent = json.loads(response)
        except json.JSONDecodeError:
            # Fallback if LLM doesn't return valid JSON
            intent = {
                "data_requirements": ["Unknown"],
                "query_strategy": response[:500],
                "expected_insights": [],
                "suggested_slide_count": max_slides,
            }

        return intent

    @mlflow.trace(name="execute_tool_loop", span_type="AGENT")
    def _execute_tool_loop(
        self, question: str, genie_space_id: Optional[str]
    ) -> dict[str, Any]:
        """
        Execute agent tool loop to gather data via Genie.

        This implements a simple tool-calling loop where the agent decides
        what queries to make and when it has enough information.

        Args:
            question: User's question
            genie_space_id: Optional Genie space ID

        Returns:
            Dictionary containing all gathered data
        """
        tool_outputs = []
        conversation_id = None
        max_iterations = 5  # Prevent infinite loops

        for iteration in range(max_iterations):
            mlflow.set_span_attribute("iteration", iteration)

            # First iteration: query directly based on user question
            if iteration == 0:
                query = question
            else:
                # Subsequent iterations: decide if we need more data
                decision = self._decide_next_action(question, tool_outputs)

                if decision["action"] == "finish":
                    mlflow.set_span_attribute("finish_reason", "agent_decided")
                    break

                query = decision.get("query", question)

            # Execute Genie tool
            try:
                result = query_genie_space(
                    query=query,
                    conversation_id=conversation_id,
                    genie_space_id=genie_space_id,
                )

                tool_outputs.append(
                    {
                        "iteration": iteration,
                        "query": query,
                        "result": result,
                    }
                )

                # Update conversation ID for follow-up queries
                conversation_id = result["conversation_id"]

                # Log tool execution
                mlflow.log_metrics(
                    {
                        f"tool.genie.rows_retrieved.iter_{iteration}": result["row_count"],
                        f"tool.genie.execution_time.iter_{iteration}": result[
                            "execution_time_seconds"
                        ],
                    }
                )

            except Exception as e:
                mlflow.log_param(f"tool_error_iter_{iteration}", str(e))
                # Continue even if one query fails
                break

        # Log summary metrics
        mlflow.log_metrics(
            {
                "tool_calls_count": len(tool_outputs),
                "tool_iterations": iteration + 1,
            }
        )

        # Synthesize all tool outputs
        return self._synthesize_tool_outputs(tool_outputs)

    @mlflow.trace(name="decide_next_action", span_type="LLM")
    def _decide_next_action(
        self, question: str, tool_outputs: list[dict]
    ) -> dict[str, Any]:
        """
        Decide whether to make another tool call or finish.

        Args:
            question: Original user question
            tool_outputs: List of previous tool call results

        Returns:
            Dictionary with action decision
        """
        # Simple heuristic: finish after first successful query with data
        if tool_outputs and tool_outputs[-1]["result"]["row_count"] > 0:
            return {"action": "finish"}

        # Otherwise, try to refine the query
        return {"action": "query", "query": question}

    def _synthesize_tool_outputs(self, tool_outputs: list[dict]) -> dict[str, Any]:
        """
        Synthesize multiple tool outputs into a single context.

        Args:
            tool_outputs: List of tool call results

        Returns:
            Synthesized data context
        """
        if not tool_outputs:
            return {"data": [], "summary": "No data retrieved"}

        # Combine all data
        all_data = []
        for output in tool_outputs:
            all_data.extend(output["result"]["data"])

        return {
            "data": all_data,
            "row_count": len(all_data),
            "queries_executed": len(tool_outputs),
            "summary": f"Retrieved {len(all_data)} total rows from {len(tool_outputs)} queries",
        }

    @mlflow.trace(name="interpret_data", span_type="LLM")
    def _interpret_data(self, data_context: dict, question: str) -> dict[str, Any]:
        """
        Interpret data to extract insights.

        Args:
            data_context: Data gathered from tools
            question: Original user question

        Returns:
            Dictionary with insights
        """
        # Format data for LLM
        data_str = json.dumps(data_context["data"][:100], indent=2)  # Limit for context

        prompt = self.settings.prompts["data_interpretation"].format(
            data=data_str, question=question
        )

        response = self._call_llm(
            messages=[{"role": "user", "content": prompt}],
            span_name="data_interpretation_llm",
            temperature=self.settings.llm.temperature,
        )

        # Parse JSON response
        try:
            insights = json.loads(response)
        except json.JSONDecodeError:
            insights = {
                "key_findings": [response[:500]],
                "trends": [],
                "anomalies": [],
                "actionable_insights": [],
                "summary": response[:200],
            }

        return insights

    @mlflow.trace(name="construct_narrative", span_type="LLM")
    def _construct_narrative(
        self, insights: dict, intent: dict, max_slides: int
    ) -> dict[str, Any]:
        """
        Construct narrative structure for slides.

        Args:
            insights: Data insights
            intent: Intent analysis
            max_slides: Maximum slides

        Returns:
            Dictionary with narrative structure
        """
        prompt = self.settings.prompts["narrative_construction"].format(
            question=insights.get("summary", "Data Analysis"),
            insights=json.dumps(insights, indent=2),
            target_slides=max_slides,
        )

        response = self._call_llm(
            messages=[{"role": "user", "content": prompt}],
            span_name="narrative_construction_llm",
            temperature=self.settings.llm.temperature,
        )

        # Parse JSON response
        try:
            narrative = json.loads(response)
        except json.JSONDecodeError:
            # Fallback narrative
            narrative = {
                "title": "Data Analysis Results",
                "subtitle": "",
                "slides": [
                    {
                        "type": "title",
                        "title": "Data Analysis Results",
                        "content": insights.get("summary", ""),
                    }
                ],
            }

        return narrative

    @mlflow.trace(name="generate_html", span_type="LLM")
    def _generate_html(self, narrative: dict) -> str:
        """
        Generate HTML slide deck from narrative.

        Args:
            narrative: Narrative structure

        Returns:
            Complete HTML string
        """
        prompt = self.settings.prompts["html_generation"].format(
            narrative=json.dumps(narrative, indent=2),
            template_style=self.settings.output.html_template,
            include_metadata=self.settings.output.include_metadata,
        )

        html_output = self._call_llm(
            messages=[{"role": "user", "content": prompt}],
            span_name="html_generation_llm",
            temperature=0.4,  # Lower temperature for more consistent HTML
            max_tokens=8192,  # More tokens for complete HTML
        )

        return html_output

    @mlflow.trace(name="call_llm", span_type="LLM")
    def _call_llm(
        self,
        messages: list[dict],
        span_name: str = "llm_call",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Call LLM with automatic tracing of tokens and latency.

        Args:
            messages: List of message dictionaries
            span_name: Name for this LLM call span
            temperature: Override temperature
            max_tokens: Override max_tokens

        Returns:
            LLM response content
        """
        start_time = time.time()

        # Use override values or defaults
        temp = temperature if temperature is not None else self.settings.llm.temperature
        max_tok = max_tokens if max_tokens is not None else self.settings.llm.max_tokens

        try:
            # Call Foundation Model API via serving endpoint
            response = self.client.serving_endpoints.query(
                name=self.settings.llm.endpoint,
                inputs={
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": max_tok,
                },
            )

            latency = time.time() - start_time

            # Extract response and usage
            content = response.choices[0].message.content
            usage = response.usage if hasattr(response, "usage") else None

            if usage:
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens
                total_tokens = usage.total_tokens

                # Log LLM metrics
                mlflow.log_metrics(
                    {
                        f"{span_name}.latency_seconds": latency,
                        f"{span_name}.prompt_tokens": prompt_tokens,
                        f"{span_name}.completion_tokens": completion_tokens,
                        f"{span_name}.total_tokens": total_tokens,
                    }
                )

                # Calculate cost if tracking enabled
                if self.settings.mlflow.track_cost:
                    input_cost = (
                        prompt_tokens / 1_000_000
                    ) * self.settings.mlflow.cost_per_million_input_tokens
                    output_cost = (
                        completion_tokens / 1_000_000
                    ) * self.settings.mlflow.cost_per_million_output_tokens
                    total_cost = input_cost + output_cost

                    mlflow.log_metrics(
                        {
                            f"{span_name}.cost_input_usd": input_cost,
                            f"{span_name}.cost_output_usd": output_cost,
                            f"{span_name}.cost_total_usd": total_cost,
                        }
                    )

                # Set span attributes
                mlflow.set_span_attribute("llm.model", self.settings.llm.endpoint)
                mlflow.set_span_attribute("llm.prompt_tokens", prompt_tokens)
                mlflow.set_span_attribute("llm.completion_tokens", completion_tokens)
                mlflow.set_span_attribute("llm.total_tokens", total_tokens)
            else:
                mlflow.log_metrics({f"{span_name}.latency_seconds": latency})

            mlflow.set_span_attribute("llm.latency_seconds", latency)

            return content

        except Exception as e:
            latency = time.time() - start_time
            mlflow.log_metrics({f"{span_name}.latency_seconds": latency})
            mlflow.set_span_attribute("llm.error", str(e))
            raise

    def _count_slides(self, narrative: dict) -> int:
        """Count number of slides in narrative."""
        return len(narrative.get("slides", []))

    def _get_trace_url(self, run_id: str) -> str:
        """Generate URL to view trace in Databricks."""
        experiment_id = mlflow.get_experiment_by_name(
            self.settings.mlflow.experiment_name
        ).experiment_id

        return (
            f"{self.settings.databricks_host}/#mlflow/experiments/"
            f"{experiment_id}/runs/{run_id}/traces"
        )

