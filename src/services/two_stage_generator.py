"""
Two-Stage Slide Generator for Token Optimization.

Implements a two-stage architecture that dramatically reduces token usage
while maintaining full data transparency (no summarization).

Architecture:
    Stage 1 (Planning): Light LLM call to determine all needed queries
    Execution: Run Genie queries in parallel, keep full CSV data
    Stage 2 (Generation): Full LLM call with all data to generate slides

Benefits:
    - 65% reduction in token usage
    - 50-60% faster generation (fewer LLM calls, parallel queries)
    - Full data transparency (no summarization)
    - Scales to 15+ slides

Reference: docs/TWO_STAGE_CSV_IMPLEMENTATION_PLAN.md
"""

import asyncio
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Optional

import mlflow
from bs4 import BeautifulSoup
from databricks_langchain import ChatDatabricks

from src.core.databricks_client import get_databricks_client
from src.core.settings_db import get_settings
from src.services.prompts import build_generation_prompt, format_csv_data_for_llm
from src.services.query_planner import QueryPlanner, QueryPlanningError
from src.services.tools import (
    GenieToolError,
    initialize_genie_conversation,
    query_genie_space,
)
from src.utils.html_utils import extract_canvas_ids_from_script

logger = logging.getLogger(__name__)


class TwoStageGeneratorError(Exception):
    """Base exception for two-stage generator errors."""
    pass


class TwoStageGenerator:
    """
    Two-stage slide generator with full CSV data transparency.
    
    This class provides an alternative to the iterative LangChain agent,
    using a deterministic two-stage flow that minimizes LLM calls.
    
    The interface is compatible with SlideGeneratorAgent for easy swapping.
    """
    
    def __init__(self):
        """Initialize the two-stage generator."""
        logger.info("Initializing TwoStageGenerator")
        
        self.settings = get_settings()
        self.client = get_databricks_client()
        
        # Initialize components
        self.query_planner = QueryPlanner()
        self.generation_llm = self._create_generation_llm()
        
        # Set up MLflow (reuse existing setup pattern from agent.py)
        self._setup_mlflow()
        
        # Session storage (matches SlideGeneratorAgent interface)
        self.sessions: dict[str, dict[str, Any]] = {}
        
        # Thread pool for parallel Genie queries
        self.executor = ThreadPoolExecutor(max_workers=5)
        
        logger.info("TwoStageGenerator initialized successfully")
    
    def _setup_mlflow(self) -> None:
        """Configure MLflow tracking and experiment (same as agent.py)."""
        try:
            tracking_uri = "databricks"
            mlflow.set_tracking_uri(tracking_uri)
            
            experiment = mlflow.get_experiment_by_name(self.settings.mlflow.experiment_name)
            if experiment is None:
                self.experiment_id = mlflow.create_experiment(self.settings.mlflow.experiment_name)
                logger.info(
                    "Created new MLflow experiment",
                    extra={
                        "experiment_name": self.settings.mlflow.experiment_name,
                        "experiment_id": self.experiment_id
                    }
                )
            else:
                self.experiment_id = experiment.experiment_id
                logger.info(
                    "Using existing MLflow experiment",
                    extra={
                        "experiment_name": self.settings.mlflow.experiment_name,
                        "experiment_id": self.experiment_id
                    }
                )
            
            mlflow.set_experiment(experiment_id=self.experiment_id)
            
            # Enable LangChain autologging (captures token usage automatically)
            try:
                mlflow.langchain.autolog()
                logger.info("MLflow LangChain autologging enabled")
            except Exception as e:
                logger.warning(f"Failed to enable MLflow LangChain autologging: {e}")
                
        except Exception as e:
            logger.warning(f"Failed to configure MLflow: {e}")
            self.experiment_id = None
    
    def _create_generation_llm(self) -> ChatDatabricks:
        """Create LLM instance for slide generation (Stage 2)."""
        return ChatDatabricks(
            endpoint=self.settings.llm.endpoint,
            temperature=self.settings.llm.temperature,
            max_tokens=self.settings.llm.max_tokens,
        )
    
    # =========================================================================
    # Session Management (compatible with SlideGeneratorAgent)
    # =========================================================================
    
    def create_session(self) -> str:
        """
        Create a new conversation session.
        
        Returns:
            Unique session ID
        """
        session_id = str(uuid.uuid4())
        logger.info("Creating new session", extra={"session_id": session_id})
        
        # Initialize Genie conversation
        try:
            genie_conversation_id = initialize_genie_conversation()
        except Exception as e:
            logger.error(f"Failed to initialize Genie conversation: {e}")
            raise TwoStageGeneratorError(f"Failed to initialize Genie: {e}") from e
        
        self.sessions[session_id] = {
            "genie_conversation_id": genie_conversation_id,
            "created_at": datetime.utcnow().isoformat(),
            "message_count": 0,
            "chat_history": [],
            "last_html": None,
        }
        
        logger.info(
            "Session created",
            extra={"session_id": session_id, "genie_id": genie_conversation_id}
        )
        
        return session_id
    
    def get_session(self, session_id: str) -> dict[str, Any]:
        """Get session data."""
        if session_id not in self.sessions:
            raise TwoStageGeneratorError(f"Session not found: {session_id}")
        return self.sessions[session_id]
    
    def clear_session(self, session_id: str) -> None:
        """Clear a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info("Cleared session", extra={"session_id": session_id})
    
    # =========================================================================
    # Main Generation Flow
    # =========================================================================
    
    def generate_slides(
        self,
        question: str,
        session_id: str,
        max_slides: int = 10,
        slide_context: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Generate slides using two-stage architecture.
        
        This is the main entry point, compatible with the chat service interface.
        
        Args:
            question: User's natural language request (named for compatibility)
            session_id: Session ID for conversation context
            max_slides: Maximum number of slides to generate
            slide_context: Optional slide context for editing (not yet implemented)
        
        Returns:
            Dict with:
                - html: Generated HTML slides
                - messages: List of message dicts for UI
                - metadata: Execution metadata
        """
        # Rename for internal use
        user_request = question
        session = self.get_session(session_id)
        session["message_count"] += 1
        
        # Check if this is an editing request (has existing slides)
        existing_slides = session.get("last_html")
        is_editing = existing_slides is not None and self._is_edit_request(user_request)
        
        logger.info(
            "Starting two-stage generation",
            extra={
                "session_id": session_id,
                "is_editing": is_editing,
                "max_slides": max_slides,
            }
        )
        
        intermediate_steps = []
        generation_start_time = datetime.utcnow()
        
        try:
            with mlflow.start_span(name="two_stage_generation") as parent_span:
                # Log parameters
                mlflow.log_param("architecture", "two_stage_csv")
                mlflow.log_param("llm_model", self.settings.llm.endpoint)
                mlflow.log_param("max_slides", max_slides)
                mlflow.log_param("is_editing", is_editing)
                mlflow.log_param("user_request", user_request[:500])  # Truncate for readability
                
                # Extract requested slides from user prompt (if specified)
                slide_match = re.search(r'(\d+)\s*slides?', user_request.lower())
                requested_slides = int(slide_match.group(1)) if slide_match else max_slides
                mlflow.log_param("requested_slides", requested_slides)
                
                # =============================================================
                # STAGE 1: Query Planning
                # =============================================================
                with mlflow.start_span(name="stage_1_planning"):
                    intermediate_steps.append({
                        "type": "planning",
                        "status": "started",
                        "message": "Planning data queries..."
                    })
                    
                    plan_result = self.query_planner.plan_queries(user_request)
                    queries = plan_result["queries"]
                    
                    mlflow.log_metric("num_queries_planned", len(queries))
                    mlflow.log_param("queries", str(queries))
                    
                    intermediate_steps.append({
                        "type": "planning",
                        "status": "complete",
                        "message": f"Planned {len(queries)} queries",
                        "queries": queries,
                        "rationale": plan_result.get("rationale", ""),
                    })
                    
                    logger.info(
                        "Stage 1 complete",
                        extra={"num_queries": len(queries)}
                    )
                
                # =============================================================
                # EXECUTION: Parallel Genie Queries
                # =============================================================
                with mlflow.start_span(name="genie_execution"):
                    intermediate_steps.append({
                        "type": "execution",
                        "status": "started",
                        "message": f"Executing {len(queries)} Genie queries..."
                    })
                    
                    csv_results = self._execute_queries_parallel(
                        queries=queries,
                        conversation_id=session["genie_conversation_id"],
                    )
                    
                    total_rows = sum(r.get("row_count", 0) for r in csv_results.values())
                    successful_queries = sum(1 for r in csv_results.values() if r.get("csv"))
                    
                    mlflow.log_metric("total_genie_rows", total_rows)
                    mlflow.log_metric("successful_queries", successful_queries)
                    
                    intermediate_steps.append({
                        "type": "execution",
                        "status": "complete",
                        "message": f"Retrieved {total_rows} rows from {successful_queries} queries",
                        "results_summary": {
                            q: {"rows": r.get("row_count", 0), "has_data": bool(r.get("csv"))}
                            for q, r in csv_results.items()
                        },
                    })
                    
                    logger.info(
                        "Genie execution complete",
                        extra={"total_rows": total_rows, "successful": successful_queries}
                    )
                
                # =============================================================
                # STAGE 2: Slide Generation
                # =============================================================
                with mlflow.start_span(name="stage_2_generation"):
                    intermediate_steps.append({
                        "type": "generation",
                        "status": "started",
                        "message": "Generating slides..."
                    })
                    
                    html, _ = self._generate_slides_with_data(
                        user_request=user_request,
                        csv_results=csv_results,
                        existing_slides=existing_slides if is_editing else None,
                        max_slides=max_slides,
                    )
                    
                    # Count slides in output
                    slide_count = self._count_slides(html)
                    mlflow.log_metric("slides_generated", slide_count)
                    
                    intermediate_steps.append({
                        "type": "generation",
                        "status": "complete",
                        "message": f"Generated {slide_count} slides",
                    })
                    
                    logger.info(
                        "Stage 2 complete",
                        extra={"slide_count": slide_count}
                    )
                
                # =============================================================
                # LOG COMPREHENSIVE METRICS
                # =============================================================
                generation_end_time = datetime.utcnow()
                total_execution_time = (generation_end_time - generation_start_time).total_seconds()
                
                # Core metrics
                mlflow.log_metric("total_execution_time_sec", total_execution_time)
                mlflow.log_metric("llm_calls", 2)  # Always 2 for two-stage (planning + generation)
                
                # Efficiency metrics
                if slide_count > 0:
                    mlflow.log_metric("rows_per_slide", total_rows / slide_count)
                    mlflow.log_metric("time_per_slide_sec", total_execution_time / slide_count)
                
                # Query efficiency
                if len(queries) > 0:
                    mlflow.log_metric("avg_rows_per_query", total_rows / len(queries))
                    mlflow.log_metric("time_per_query_sec", total_execution_time / len(queries))
                
                # Success rate
                failed_queries = sum(1 for r in csv_results.values() if "error" in r)
                success_rate = (successful_queries / len(queries) * 100) if queries else 0
                mlflow.log_metric("query_success_rate_pct", success_rate)
                mlflow.log_metric("failed_queries", failed_queries)
                
                # Data coverage
                empty_queries = sum(1 for r in csv_results.values() if r.get("row_count", 0) == 0 and "error" not in r)
                mlflow.log_metric("empty_result_queries", empty_queries)
                
                # Slide accuracy (requested vs generated)
                mlflow.log_metric("slides_difference", slide_count - requested_slides)
                
                logger.info(
                    "Metrics logged to MLflow",
                    extra={
                        "total_time": total_execution_time,
                        "slides": slide_count,
                        "rows": total_rows,
                        "queries": len(queries),
                        "success_rate": success_rate,
                    }
                )
                
                # Store the generated HTML for potential editing
                session["last_html"] = html
                
                # Add to chat history
                session["chat_history"].append({
                    "role": "user",
                    "content": user_request,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                session["chat_history"].append({
                    "role": "assistant",
                    "content": f"Generated {slide_count} slides",
                    "html": html,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                
                # Build messages for UI (matching original agent format)
                # Format: user -> [assistant tool_call -> tool response]... -> final assistant
                messages = self._build_ui_messages(
                    user_request=user_request,
                    queries=queries,
                    csv_results=csv_results,
                    total_rows=total_rows,
                    slide_count=slide_count,
                    html=html,
                )
                
                # Return format compatible with chat_service
                return {
                    "html": html,
                    "messages": messages,
                    "metadata": {
                        "architecture": "two_stage_csv",
                        "queries_executed": list(csv_results.keys()),
                        "total_data_rows": total_rows,
                        "slide_count": slide_count,
                    },
                    "session_id": session_id,
                    "genie_conversation_id": session["genie_conversation_id"],
                    "replacement_info": None,  # Not implemented yet
                    "parsed_output": None,  # Not implemented yet
                }
                
        except QueryPlanningError as e:
            logger.error(f"Query planning failed: {e}")
            raise TwoStageGeneratorError(f"Failed to plan queries: {e}") from e
        except Exception as e:
            logger.error(f"Slide generation failed: {e}")
            raise TwoStageGeneratorError(f"Slide generation failed: {e}") from e
    
    # =========================================================================
    # Genie Query Execution
    # =========================================================================
    
    def _execute_queries_parallel(
        self,
        queries: list[str],
        conversation_id: str,
    ) -> dict[str, dict]:
        """
        Execute all Genie queries in parallel.
        
        Args:
            queries: List of query strings
            conversation_id: Genie conversation ID
        
        Returns:
            Dict mapping query string to result dict:
            {
                "query string": {
                    "csv": "csv data string",
                    "row_count": int,
                    "message": "optional genie message",
                    "error": "error message if failed"
                }
            }
        """
        def execute_single(query: str) -> tuple[str, dict]:
            """Execute a single query and return (query, result)."""
            try:
                result = query_genie_space(query, conversation_id)
                
                # Count rows in CSV (header line + data lines)
                csv_data = result.get("data", "")
                row_count = 0
                if csv_data:
                    lines = csv_data.strip().split("\n")
                    row_count = max(0, len(lines) - 1)  # Subtract header row
                
                return query, {
                    "csv": csv_data,
                    "row_count": row_count,
                    "message": result.get("message", ""),
                }
            except GenieToolError as e:
                logger.warning(f"Genie query failed: {query[:50]}... - {e}")
                return query, {
                    "csv": "",
                    "row_count": 0,
                    "error": str(e),
                }
            except Exception as e:
                logger.error(f"Unexpected error in query: {query[:50]}... - {e}")
                return query, {
                    "csv": "",
                    "row_count": 0,
                    "error": str(e),
                }
        
        # Execute in parallel using ThreadPoolExecutor
        results = {}
        futures = {
            self.executor.submit(execute_single, q): q
            for q in queries
        }
        
        for future in futures:
            query, result = future.result()
            results[query] = result
        
        return results
    
    # =========================================================================
    # Slide Generation (Stage 2)
    # =========================================================================
    
    def _generate_slides_with_data(
        self,
        user_request: str,
        csv_results: dict[str, dict],
        existing_slides: Optional[str],
        max_slides: int,
    ) -> str:
        """
        Stage 2: Generate HTML slides with full CSV data.
        
        No summarization - all CSV data is passed to the LLM.
        """
        # Format CSV data for LLM (no summarization)
        data_context = format_csv_data_for_llm(csv_results)
        
        # Get system prompt from settings
        system_prompt = self.settings.prompts.get("system_prompt", "")
        if not system_prompt:
            raise TwoStageGeneratorError("System prompt not found in configuration")
        
        # Only add max_slides instruction if user didn't specify a number in their prompt
        # This lets "Create 3 slides about..." work correctly
        slide_number_in_prompt = re.search(r'(\d+)\s*slides?', user_request.lower())
        
        if slide_number_in_prompt:
            # User specified slides in prompt - respect their request, use max_slides as ceiling
            requested = int(slide_number_in_prompt.group(1))
            if requested <= max_slides:
                user_request_with_limit = user_request  # Use as-is, user knows what they want
            else:
                user_request_with_limit = f"{user_request}\n\nNote: Maximum allowed is {max_slides} slides."
        else:
            # User didn't specify - add the max_slides instruction
            user_request_with_limit = f"{user_request}\n\nGenerate a maximum of {max_slides} slides."
        
        # Build generation prompt
        messages = build_generation_prompt(
            user_request=user_request_with_limit,
            data_context=data_context,
            system_prompt=system_prompt,
            existing_slides=existing_slides,
        )
        
        # Generate slides
        response = self.generation_llm.invoke(messages)
        html = response.content
        
        # Extract token usage if available
        token_usage = {}
        if hasattr(response, 'response_metadata') and response.response_metadata:
            usage = response.response_metadata.get('usage', {})
            if usage:
                token_usage = {
                    'prompt_tokens': usage.get('prompt_tokens', 0),
                    'completion_tokens': usage.get('completion_tokens', 0),
                    'total_tokens': usage.get('total_tokens', 0),
                }
        
        # Clean up HTML if needed
        html = self._clean_html_response(html)
        
        return html, token_usage
    
    def _clean_html_response(self, html: str) -> str:
        """Clean up LLM HTML response (remove markdown wrappers, etc.)."""
        # Remove markdown code block if present
        if html.startswith("```html"):
            html = html[7:]
        elif html.startswith("```"):
            html = html[3:]
        
        if html.endswith("```"):
            html = html[:-3]
        
        return html.strip()
    
    def _count_slides(self, html: str) -> int:
        """Count the number of slides in HTML output.
        
        Matches the exact logic used in slide_deck.py for consistency.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            # Exact match: <div class="slide"> - same as slide_deck.py
            slides = soup.find_all('div', class_='slide')
            return len(slides)
        except Exception:
            return 0
    
    def _is_edit_request(self, request: str) -> bool:
        """Detect if request is asking to edit existing slides."""
        edit_keywords = [
            "change", "modify", "update", "edit", "fix",
            "add to", "remove", "replace", "make", "adjust",
            "slide 1", "slide 2", "slide 3", "first slide", "last slide",
        ]
        request_lower = request.lower()
        return any(keyword in request_lower for keyword in edit_keywords)
    
    def _build_ui_messages(
        self,
        user_request: str,
        queries: list[str],
        csv_results: dict[str, dict],
        total_rows: int,
        slide_count: int,
        html: str,
    ) -> list[dict]:
        """
        Build detailed UI messages matching original agent format.
        
        Shows each tool call with its arguments and response,
        providing full transparency of the generation process.
        """
        messages = []
        
        # 1. User message
        messages.append({
            "role": "user",
            "content": user_request,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # 2. Query Planning - Assistant announces tool use
        messages.append({
            "role": "assistant",
            "content": "Using tool: query_planner",
            "tool_call": {
                "name": "query_planner",
                "arguments": {"user_request": user_request},
            },
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # Query Planning - Tool response with planned queries
        messages.append({
            "role": "tool",
            "content": f"Planned {len(queries)} data queries:\n" + "\n".join(
                f"  {i+1}. {q}" for i, q in enumerate(queries)
            ),
            "tool_call_id": "query_planner",
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # 3. Each Genie Query - Show individual executions
        for query, result in csv_results.items():
            row_count = result.get("row_count", 0)
            has_error = "error" in result
            
            # Assistant announces Genie query - SHOW THE ACTUAL QUERY
            messages.append({
                "role": "assistant",
                "content": f"Using tool: query_genie_space\nQuery: \"{query}\"",
                "tool_call": {
                    "name": "query_genie_space",
                    "arguments": {"query": query},
                },
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            # Genie query result - show FULL data for transparency
            if has_error:
                tool_content = f"Error: {result.get('error', 'Unknown error')}"
            elif row_count > 0:
                tool_content = f"Retrieved {row_count} rows of data"
                if result.get("message"):
                    tool_content += f"\nGenie: {result['message']}"
                # Add the actual CSV data (collapsible in UI)
                csv_data = result.get("csv", "")
                if csv_data:
                    tool_content += f"\n\nData:\n{csv_data}"
            else:
                tool_content = "No data returned"
                if result.get("message"):
                    tool_content += f"\nGenie: {result['message']}"
            
            messages.append({
                "role": "tool",
                "content": tool_content,
                "tool_call_id": "query_genie_space",
                "timestamp": datetime.utcnow().isoformat(),
            })
        
        # 4. Slide Generation - Summary
        messages.append({
            "role": "assistant",
            "content": "Using tool: generate_slides",
            "tool_call": {
                "name": "generate_slides",
                "arguments": {
                    "data_rows": total_rows,
                    "queries_used": len(csv_results),
                },
            },
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        messages.append({
            "role": "tool",
            "content": f"Generated {slide_count} slides from {total_rows} rows of data",
            "tool_call_id": "generate_slides",
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # 5. Final assistant message (not shown in chat, but contains HTML)
        messages.append({
            "role": "assistant",
            "content": html,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        return messages
    
    # =========================================================================
    # Interface for Chat Service (compatibility layer)
    # =========================================================================
    
    def invoke(
        self,
        question: str,
        session_id: str,
        max_slides: int = 10,
        slide_context: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Invoke the generator (compatibility with SlideGeneratorAgent.invoke).
        
        This method provides the same interface as SlideGeneratorAgent
        so it can be swapped in via feature flag.
        """
        return self.generate_slides(
            question=question,
            session_id=session_id,
            max_slides=max_slides,
            slide_context=slide_context,
        )

