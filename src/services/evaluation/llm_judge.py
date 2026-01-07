"""LLM as Judge for slide verification using MLflow 3.x.

This module provides LLM-based evaluation of slide data accuracy using
MLflow's genai.evaluate() API. It performs semantic comparison between Genie 
source data and slide content, and creates proper Evaluation Runs in MLflow.

MLflow Structure:
- inputs: Context about what's being verified
- outputs: The slide content (what LLM generated)
- expectations: The Genie source data (ground truth)
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# Rating type for feedback (RAG: Red/Amber/Green)
RatingType = Literal["green", "amber", "red"]

# Rating to score mapping (RAG system)
# green: ≥80% - No issues detected
# amber: 50-79% - Review suggested
# red: <50% - Review required
RATING_SCORES: Dict[str, int] = {
    "green": 85,   # High confidence, no issues
    "amber": 65,   # Some concerns, review suggested
    "red": 25,     # Significant issues, review required
}


@dataclass
class LLMJudgeResult:
    """Result from LLM judge evaluation."""

    score: float
    explanation: str
    issues: List[Dict[str, str]]
    rating: str
    duration_ms: int
    error: bool = False
    error_message: Optional[str] = None
    trace_id: Optional[str] = None
    run_id: Optional[str] = None  # MLflow run ID for evaluation runs

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "score": self.score,
            "explanation": self.explanation,
            "issues": self.issues,
            "rating": self.rating,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "error_message": self.error_message,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
        }


# Judge instructions template using proper MLflow variables:
# - {{ outputs }}: The slide content being evaluated  
# - {{ expectations }}: Dict containing source_data (ground truth)
JUDGE_INSTRUCTIONS = """You are verifying that a presentation slide accurately represents source data.

## SOURCE DATA (Ground Truth)
{{ expectations }}

## SLIDE CONTENT (To Verify)
{{ outputs }}

## Evaluation Rules

**These are NOT errors (same meaning, different format):**
- 7,234,567 shown as "7.2M" or "$7.2M" or "~7 million" ✓
- 0.15 shown as "15%" ✓
- Reasonable rounding (7,234,567 → 7.2M is fine)
- Adding currency symbols, commas, or units ✓
- Calculations like "50% growth" from Q1=100, Q2=150 are CORRECT ✓

**These ARE errors (actually wrong):**
- Wrong numbers: source says 7M but slide shows 9M ✗
- Swapped values: Q1 and Q2 data reversed ✗
- Hallucinated data: numbers not in source ✗
- Wrong calculations: if A=100, B=50, saying "A is 3x B" is wrong ✗
- Missing critical data: key metrics completely absent ⚠

## Choose ONE rating:

- green: All numbers correctly represent the source data (no issues detected)
- amber: Most numbers correct but some concerns - minor errors or important data missing (review suggested)
- red: Significant issues - wrong numbers, hallucinated data, swapped values, or major omissions (review required)

Provide your rating and explain your reasoning in 2-3 sentences."""


async def evaluate_with_judge(
    genie_data: str,
    slide_content: str,
    model: str = "databricks-claude-sonnet-4-5",
    trace_id: Optional[str] = None,
) -> LLMJudgeResult:
    """
    Run LLM judge evaluation on slide content using MLflow 3.x genai.evaluate().

    This creates a proper Evaluation Run in MLflow that appears in the
    Evaluations tab with proper structure:
    - inputs: Context about verification
    - outputs: Slide content (what to evaluate)
    - expectations: Genie data (ground truth)

    Args:
        genie_data: CSV/text data from Genie queries (source of truth)
        slide_content: HTML + scripts from slide to verify
        model: Databricks model endpoint name
        trace_id: Optional trace ID to link feedback

    Returns:
        LLMJudgeResult with score, explanation, issues, and metadata
    """
    start_time = time.time()

    try:
        import mlflow
        from mlflow.genai import make_judge
        from src.core.settings_db import get_settings

        # Set tracking URI to Databricks (not local ./mlruns)
        mlflow.set_tracking_uri("databricks")

        # Set the experiment (required for Databricks MLflow)
        settings = get_settings()
        experiment_name = settings.mlflow.experiment_name
        experiment = mlflow.get_experiment_by_name(experiment_name)
        if experiment is None:
            experiment_id = mlflow.create_experiment(experiment_name)
        else:
            experiment_id = experiment.experiment_id
        mlflow.set_experiment(experiment_id=experiment_id)

        # Create judge using outputs and expectations
        accuracy_judge = make_judge(
            name="numerical_accuracy",
            instructions=JUDGE_INSTRUCTIONS,
            model=f"databricks:/{model}",
            description="Evaluates numerical accuracy of slides against source data",
            feedback_value_type=RatingType,
        )

        # Create evaluation data with proper MLflow structure:
        # - inputs: Context/metadata about what's being verified
        # - outputs: The slide content (what the LLM generated)
        # - expectations: Dict with ground truth data to compare against
        eval_data = pd.DataFrame([{
            "inputs": {"task": "Verify slide numerical accuracy against source data"},
            "outputs": slide_content,
            "expectations": {"source_data": genie_data},
        }])

        # Run evaluation using mlflow.genai.evaluate() - THIS creates Evaluation Runs
        eval_result = mlflow.genai.evaluate(
            data=eval_data,
            scorers=[accuracy_judge],
        )

        # Extract results from evaluation
        run_id = eval_result.run_id
        mlflow_trace_id = None
        rating = "unknown"
        explanation = ""
        
        results_df = eval_result.result_df
        if results_df is not None and len(results_df) > 0:
            row = results_df.iloc[0]
            
            # Get the rating from the judge output column
            rating_col = "numerical_accuracy/value"
            if rating_col in row.index and pd.notna(row[rating_col]):
                rating = str(row[rating_col])
            
            # Get trace ID
            if "trace_id" in row.index and pd.notna(row["trace_id"]):
                mlflow_trace_id = str(row["trace_id"])
            
            # Try to get rationale from the rationale column first
            rationale_col = "numerical_accuracy/rationale"
            if rationale_col in row.index and pd.notna(row[rationale_col]):
                explanation = str(row[rationale_col])
            
            # Get rationale from assessments column - find the numerical_accuracy assessment
            if not explanation and "assessments" in row.index and row["assessments"]:
                assessments = row["assessments"]
                for assessment in assessments:
                    if isinstance(assessment, dict):
                        name = assessment.get("assessment_name", "")
                        if name == "numerical_accuracy":
                            # Rationale is in the 'rationale' field
                            if "rationale" in assessment:
                                explanation = str(assessment["rationale"])
                            elif "metadata" in assessment and assessment["metadata"]:
                                meta = assessment["metadata"]
                                if isinstance(meta, dict) and "rationale" in meta:
                                    explanation = str(meta["rationale"])
                            break

        # Convert rating to score
        score = RATING_SCORES.get(rating, 0)

        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"LLM judge evaluation completed: score={score}, rating={rating}, "
            f"duration={duration_ms}ms, run_id={run_id}"
        )

        return LLMJudgeResult(
            score=score,
            explanation=explanation,
            issues=[],
            rating=rating,
            duration_ms=duration_ms,
            error=False,
            trace_id=mlflow_trace_id or trace_id,
            run_id=run_id,
        )

    except ImportError as e:
        logger.error(f"MLflow import failed: {e}")
        return LLMJudgeResult(
            score=0,
            explanation="MLflow not available. Verification requires MLflow >= 3.6",
            issues=[{"type": "error", "detail": str(e)}],
            rating="error",
            duration_ms=int((time.time() - start_time) * 1000),
            error=True,
            error_message=str(e),
        )

    except Exception as e:
        logger.error(f"LLM judge evaluation failed: {e}", exc_info=True)
        return LLMJudgeResult(
            score=0,
            explanation=f"Evaluation failed: {str(e)}",
            issues=[{"type": "error", "detail": str(e)}],
            rating="error",
            duration_ms=int((time.time() - start_time) * 1000),
            error=True,
            error_message=str(e),
        )
