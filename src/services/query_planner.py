"""
Query Planner for Two-Stage Slide Generator.

Stage 1: Analyzes user request and generates all needed Genie queries upfront.
Uses a short, focused prompt to minimize token usage.

Reference: docs/TWO_STAGE_CSV_IMPLEMENTATION_PLAN.md
"""

import json
import logging
from typing import Any

from databricks_langchain import ChatDatabricks
from langchain_core.messages import HumanMessage, SystemMessage

from src.core.settings_db import get_settings
from src.services.prompts import PLANNING_PROMPT

logger = logging.getLogger(__name__)


class QueryPlanningError(Exception):
    """Raised when query planning fails."""
    pass


class QueryPlanner:
    """
    Stage 1: Plan all Genie queries upfront.
    
    Uses a short planning prompt (~800 tokens) to determine what data
    queries are needed, without any slide formatting instructions.
    """
    
    def __init__(self):
        """Initialize the query planner with LLM."""
        self.settings = get_settings()
        self.llm = self._create_llm()
        
        logger.info("QueryPlanner initialized")
    
    def _create_llm(self) -> ChatDatabricks:
        """Create LLM instance for planning (uses lower temperature for consistency)."""
        return ChatDatabricks(
            endpoint=self.settings.llm.endpoint,
            temperature=0.0,  # Low temperature for consistent planning
            max_tokens=1000,  # Planning output is small
        )
    
    def plan_queries(self, user_request: str) -> dict[str, Any]:
        """
        Generate all needed Genie queries for the user request.
        
        Args:
            user_request: The user's slide generation request
        
        Returns:
            Dict with:
                - queries: List of query strings
                - rationale: Explanation of data strategy
        
        Raises:
            QueryPlanningError: If planning fails or returns invalid response
        """
        logger.info(
            "Planning queries",
            extra={"request_preview": user_request[:100]}
        )
        
        # Build planning prompt with Genie description
        planning_prompt = PLANNING_PROMPT.format(
            genie_description=self.settings.genie.description
        )
        
        messages = [
            SystemMessage(content=planning_prompt),
            HumanMessage(content=user_request),
        ]
        
        try:
            # Single LLM call for planning
            response = self.llm.invoke(messages)
            content = response.content.strip()
            
            # Parse JSON response
            result = self._parse_planning_response(content)
            
            logger.info(
                "Query planning complete",
                extra={
                    "num_queries": len(result["queries"]),
                    "rationale": result.get("rationale", "")[:100],
                }
            )
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse planning response as JSON: {e}")
            raise QueryPlanningError(f"Invalid JSON response from planner: {e}") from e
        except Exception as e:
            logger.error(f"Query planning failed: {e}")
            raise QueryPlanningError(f"Query planning failed: {e}") from e
    
    def _parse_planning_response(self, content: str) -> dict[str, Any]:
        """
        Parse the LLM planning response.
        
        Handles cases where LLM wraps JSON in markdown code blocks.
        
        Args:
            content: Raw LLM response content
        
        Returns:
            Parsed dict with queries and rationale
        
        Raises:
            json.JSONDecodeError: If content is not valid JSON
            QueryPlanningError: If required fields are missing
        """
        # Strip markdown code blocks if present
        if content.startswith("```"):
            # Remove ```json and ``` markers
            lines = content.split("\n")
            # Find first and last ``` lines
            start_idx = 0
            end_idx = len(lines)
            for i, line in enumerate(lines):
                if line.startswith("```") and i == 0:
                    start_idx = 1
                elif line.startswith("```"):
                    end_idx = i
                    break
            content = "\n".join(lines[start_idx:end_idx])
        
        result = json.loads(content)
        
        # Validate required fields
        if "queries" not in result:
            raise QueryPlanningError("Planning response missing 'queries' field")
        
        if not isinstance(result["queries"], list):
            raise QueryPlanningError("'queries' must be a list")
        
        if len(result["queries"]) == 0:
            raise QueryPlanningError("Planning returned empty queries list")
        
        # Ensure rationale exists (optional but useful)
        if "rationale" not in result:
            result["rationale"] = ""
        
        return result

