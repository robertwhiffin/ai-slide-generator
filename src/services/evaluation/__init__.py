"""Evaluation services for slide verification using LLM as Judge.

This module provides LLM-based evaluation of slide data accuracy using
MLflow 3.x custom_prompt_judge API.
"""

from src.services.evaluation.llm_judge import (
    LLMJudgeResult,
    evaluate_with_judge,
    RATING_SCORES,
)

__all__ = [
    "LLMJudgeResult",
    "evaluate_with_judge",
    "RATING_SCORES",
]
