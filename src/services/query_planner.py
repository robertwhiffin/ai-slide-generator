"""
Query Planner for Two-Stage Architecture (Stage 1).

This module handles the planning stage of slide generation,
where a lightweight LLM call determines all needed Genie queries upfront.

Benefits:
- Single LLM call instead of iterative tool calling
- Short prompt (~800 tokens vs ~4000 tokens)
- All queries known upfront for parallel execution
"""

import json
import logging
from typing import Any

from databricks_langchain import ChatDatabricks
from langchain_core.messages import HumanMessage, SystemMessage

from src.config.settings_db import get_settings

logger = logging.getLogger(__name__)


# Planning prompt - intentionally SHORT (~800 tokens)
# No HTML instructions, no Chart.js examples, no slide formatting
PLANNING_PROMPT = """You are a data analyst planning queries for a business presentation.

Given the user's request, identify what data queries are needed to create comprehensive slides.
Output a JSON object with a list of natural language queries for the Genie data system.

RULES:
1. Be comprehensive but efficient (typically 3-6 queries)
2. Each query should be specific and return actionable data
3. Consider these data needs:
   - Totals and summaries (e.g., "total spend by category")
   - Trends over time (e.g., "monthly spend for last 12 months")
   - Breakdowns (e.g., "spend by department/team/project")
   - Comparisons (e.g., "top 10 vs bottom 10")
   - Counts and metrics (e.g., "number of workspaces per team")

4. Do NOT include:
   - SQL queries (use natural language)
   - Duplicate queries
   - Overly broad queries

OUTPUT FORMAT (JSON only, no markdown):
{"queries": ["query 1", "query 2", "query 3"]}

EXAMPLES:

User: "Create slides about our cloud spend"
Output: {"queries": ["What is the total cloud spend by service?", "What is the monthly trend of cloud spend over the last 12 months?", "Which teams have the highest cloud spend?", "What are the top 10 most expensive resources?"]}

User: "Show me use case performance"
Output: {"queries": ["What are the top use cases by total spend?", "How many workspaces does each use case have?", "What is the monthly spend trend for each use case?", "Which use cases started recently?"]}
"""


class QueryPlanner:
    """
    Plans Genie queries for slide generation (Stage 1).
    
    This class uses a lightweight LLM call with a minimal prompt
    to determine all needed data queries upfront.
    """
    
    def __init__(self, llm: ChatDatabricks | None = None):
        """
        Initialize the query planner.
        
        Args:
            llm: Optional LLM instance. If None, creates one from settings.
        """
        self.settings = get_settings()
        self.llm = llm or self._create_llm()
    
    def _create_llm(self) -> ChatDatabricks:
        """Create LLM instance for planning."""
        return ChatDatabricks(
            endpoint=self.settings.llm.endpoint,
            temperature=0.3,  # Lower temperature for structured output
            max_tokens=1000,  # Planning output is small
        )
    
    async def plan_queries(self, user_request: str) -> dict[str, Any]:
        """
        Plan Genie queries based on user request.
        
        Args:
            user_request: The user's slide generation request
        
        Returns:
            Dictionary with:
            - queries: List of query strings
            - raw_response: The LLM's raw response
        
        Raises:
            QueryPlanningError: If planning fails
        """
        logger.info(
            "Planning queries for request",
            extra={"request_preview": user_request[:100]},
        )
        
        # Add Genie context to help LLM understand available data
        genie_context = f"\nAvailable data: {self.settings.genie.description}"
        
        messages = [
            SystemMessage(content=PLANNING_PROMPT + genie_context),
            HumanMessage(content=f"User request: {user_request}"),
        ]
        
        try:
            # Invoke LLM
            response = await self.llm.ainvoke(messages)
            raw_output = response.content
            
            # Parse JSON response
            queries = self._parse_response(raw_output)
            
            logger.info(
                "Query planning complete",
                extra={
                    "query_count": len(queries),
                    "queries": queries[:3],  # Log first 3
                },
            )
            
            return {
                "queries": queries,
                "raw_response": raw_output,
            }
            
        except Exception as e:
            logger.error(f"Query planning failed: {e}")
            raise QueryPlanningError(f"Failed to plan queries: {e}") from e
    
    def plan_queries_sync(self, user_request: str) -> dict[str, Any]:
        """
        Synchronous version of plan_queries.
        
        Args:
            user_request: The user's slide generation request
        
        Returns:
            Dictionary with queries and raw_response
        """
        logger.info(
            "Planning queries (sync) for request",
            extra={"request_preview": user_request[:100]},
        )
        
        genie_context = f"\nAvailable data: {self.settings.genie.description}"
        
        messages = [
            SystemMessage(content=PLANNING_PROMPT + genie_context),
            HumanMessage(content=f"User request: {user_request}"),
        ]
        
        try:
            response = self.llm.invoke(messages)
            raw_output = response.content
            queries = self._parse_response(raw_output)
            
            logger.info(
                "Query planning complete (sync)",
                extra={"query_count": len(queries)},
            )
            
            return {
                "queries": queries,
                "raw_response": raw_output,
            }
            
        except Exception as e:
            logger.error(f"Query planning failed: {e}")
            raise QueryPlanningError(f"Failed to plan queries: {e}") from e
    
    def _parse_response(self, raw_output: str) -> list[str]:
        """
        Parse LLM response to extract queries.
        
        Handles various output formats:
        - Clean JSON
        - JSON wrapped in markdown code blocks
        - JSON with extra text before/after
        """
        # Try direct JSON parse first
        try:
            parsed = json.loads(raw_output)
            return parsed.get("queries", [])
        except json.JSONDecodeError:
            pass
        
        # Try to extract JSON from markdown code block
        if "```" in raw_output:
            # Extract content between code fences
            parts = raw_output.split("```")
            for part in parts:
                # Remove 'json' language tag if present
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
                
                try:
                    parsed = json.loads(cleaned)
                    return parsed.get("queries", [])
                except json.JSONDecodeError:
                    continue
        
        # Try to find JSON object in text
        start = raw_output.find("{")
        end = raw_output.rfind("}") + 1
        
        if start != -1 and end > start:
            try:
                parsed = json.loads(raw_output[start:end])
                return parsed.get("queries", [])
            except json.JSONDecodeError:
                pass
        
        # Fallback: log warning and return empty
        logger.warning(
            "Failed to parse query plan, returning empty list",
            extra={"raw_output": raw_output[:200]},
        )
        return []


class QueryPlanningError(Exception):
    """Raised when query planning fails."""
    pass


# Module-level convenience function
def create_query_planner(llm: ChatDatabricks | None = None) -> QueryPlanner:
    """Create a QueryPlanner instance."""
    return QueryPlanner(llm=llm)

