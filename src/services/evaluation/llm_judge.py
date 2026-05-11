"""LLM as Judge for slide verification using MLflow 3.x.

This module provides LLM-based evaluation of slide data accuracy using
MLflow's genai.evaluate() API. It performs semantic comparison between Genie
source data and slide content, and creates proper Evaluation Runs in MLflow.

When ``mlflow.genai.evaluate`` fails due to blocked egress to
``*.storage.cloud.databricks.com``, inconsistent MLflow experiment state, or a
broken evaluation trace (e.g. ``NoneType`` … ``no attribute 'info'`` inside MLflow's harness),
Tellr falls back to a **direct** ChatDatabricks call (same rating rules) so
verification still returns a result without Evaluation Runs in MLflow.

MLflow Structure:
- inputs: Context about what's being verified
- outputs: The slide content (what LLM generated)
- expectations: The Genie source data (ground truth)
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import pandas as pd

from src.core.defaults import DEFAULT_CONFIG
from src.core.mlflow_tracing import configure_tracing_environment, create_databricks_experiment

logger = logging.getLogger(__name__)


# Rating type for feedback (RAG + unknown when source cannot support verification)
RatingType = Literal["green", "amber", "red", "unknown"]

# Rating to score mapping (RAG system; unknown → UI "Unable to verify")
# green: ≥80% - No issues detected
# amber: 50-79% - Review suggested
# red: <50% - Review required
# unknown: no substantive source data to compare (not the same as red)
RATING_SCORES: Dict[str, int] = {
    "green": 85,   # High confidence, no issues
    "amber": 65,   # Some concerns, review suggested
    "red": 25,     # Significant issues, review required
    "unknown": 0,  # Cannot verify — insufficient / non-substantive source
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
JUDGE_INSTRUCTIONS = (
    "You are verifying that a presentation slide accurately represents "
    "source data.\n\n"
    "## SOURCE DATA (Ground Truth)\n"
    "{{ expectations }}\n\n"
    "## SLIDE CONTENT (To Verify)\n"
    "{{ outputs }}\n\n"
    "## Evaluation Rules\n\n"
    "**These are NOT errors (same meaning, different format):**\n"
    "- 7,234,567 shown as \"7.2M\" or \"$7.2M\" or \"~7 million\" ✓\n"
    "- 0.15 shown as \"15%\" ✓\n"
    "- Reasonable rounding (7,234,567 → 7.2M is fine)\n"
    "- Adding currency symbols, commas, or units ✓\n"
    '- Calculations like "50% growth" from Q1=100, Q2=150 are CORRECT ✓\n\n'
    "**These ARE errors (actually wrong):**\n"
    "- Wrong numbers: source says 7M but slide shows 9M ✗\n"
    "- Swapped values: Q1 and Q2 data reversed ✗\n"
    "- Hallucinated data: numbers not in source ✗\n"
    '- Wrong calculations: if A=100, B=50, saying "A is 3x B" is wrong ✗\n'
    "- Missing critical data: key metrics completely absent ⚠\n\n"
    "## Choose ONE rating:\n\n"
    "- green: All numbers correctly represent the source data (no issues detected)\n"
    "- amber: Most numbers correct but some concerns - minor errors or important data "
    "missing (review suggested)\n"
    "- red: Significant issues **when substantive source data exists** — wrong numbers, "
    "hallucinated facts **contradicted by** the source, swapped values, or major omissions "
    "of data that **is present** in the source (review required)\n"
    "- unknown: **Cannot verify** — the source has **no substantive ground truth** to "
    "compare against. Examples: only empty or error-style messages (e.g. no rows, "
    "no images found matching your criteria, zero results), placeholders with no "
    "metrics or factual claims, or text that does not contain verifiable facts about "
    "the slide topic. **Do not use red** for this case: red means the slide conflicts "
    "with real source data, not that the slide is detailed while the source is empty.\n\n"
    "Provide your rating and explain your reasoning in 2-3 sentences."
)


_DIRECT_JUDGE_JSON_PROMPT = (
    "You are verifying that a presentation slide accurately represents "
    "source data.\n\n"
    "Return **only** valid JSON (no markdown fences), one object with keys:\n"
    '- "rating": one of "green", "amber", "red", "unknown"\n'
    '- "explanation": 2-3 sentences of reasoning\n\n'
    "## SOURCE DATA (Ground Truth)\n"
    "{genie_data}\n\n"
    "## SLIDE CONTENT (To Verify)\n"
    "{slide_content}\n\n"
    "## Rules (summary)\n"
    "- green: numbers and claims match source (formatting differences OK).\n"
    "- amber: mostly correct, minor issues or omissions.\n"
    "- red: use only when the source contains **substantive verifiable facts** and the "
    "slide **conflicts** with them (wrong numbers, contradictions, major omissions of "
    "data that **is** in the source).\n"
    "- unknown: the source is **not sufficient to verify** — e.g. only empty or "
    'no-result messages ("no images found", zero rows, errors with no metrics), or no '
    "real facts about the slide topic. **Do not use red** when the source is empty or "
    "non-substantive; use unknown (cannot verify).\n"
)


def _collect_exception_messages(exc: BaseException) -> str:
    """Flatten exception message text across ``__cause__`` and ``__context__`` chains."""
    parts: list[str] = []
    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack and len(seen) < 48:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        parts.append(str(e))
        if e.__cause__ is not None:
            stack.append(e.__cause__)
        ctx = getattr(e, "__context__", None)
        if ctx is not None and ctx is not e:
            stack.append(ctx)
    return " ".join(parts).lower()


def _mlflow_evaluate_should_use_direct_fallback(exc: BaseException) -> bool:
    """True when MLflow harness failed for infra reasons we can bypass with direct LLM."""
    blob = _collect_exception_messages(exc)
    if "storage.cloud.databricks.com" in blob and (
        "connection refused" in blob
        or "connectionerror" in blob
        or "newconnectionerror" in blob
        or "max retries" in blob
    ):
        return True
    if "resource_does_not_exist" in blob and "does not exist" in blob:
        return True
    # MLflow 3 genai.evaluate: if create_minimal_trace's get_trace returns None,
    # eval_item.trace stays None and harness._get_new_expectations hits trace.info.
    if "nonetype" in blob and "no attribute 'info'" in blob:
        return True
    return False


def _parse_judge_json_response(text: str) -> tuple[str, str]:
    """Parse model output into (rating, explanation)."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        data = json.loads(raw)
        rating = str(data.get("rating", "")).strip().lower()
        explanation = str(data.get("explanation", "")).strip()
        if rating in RATING_SCORES:
            return rating, explanation
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    m = re.search(r'"rating"\s*:\s*"(green|amber|red|unknown)"', text, re.IGNORECASE)
    if m:
        rating = m.group(1).lower()
        em = re.search(r'"explanation"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        expl = em.group(1) if em else text[:800]
        return rating, expl.replace("\\n", "\n")
    return "unknown", text[:800]


def _evaluate_with_judge_direct_llm(
    genie_data: str,
    slide_content: str,
    model: str,
    start_time: float,
    trace_id: Optional[str],
) -> LLMJudgeResult:
    """Run judge via ChatDatabricks only (no MLflow genai.evaluate / Evaluation Runs)."""
    from databricks_langchain import ChatDatabricks
    from langchain_core.messages import HumanMessage

    from src.core.databricks_client import get_system_client

    llm_config = DEFAULT_CONFIG["llm"]
    max_chars = 100_000
    gd = genie_data[:max_chars]
    sc = slide_content[:max_chars]
    prompt = _DIRECT_JUDGE_JSON_PROMPT.format(genie_data=gd, slide_content=sc)

    chat = ChatDatabricks(
        endpoint=model,
        temperature=0.2,
        max_tokens=min(2048, int(llm_config.get("max_tokens", 4096))),
        top_p=0.95,
        workspace_client=get_system_client(),
    )
    resp = chat.invoke([HumanMessage(content=prompt)])
    text = (getattr(resp, "content", None) or "").strip()
    rating, explanation = _parse_judge_json_response(text)
    score = RATING_SCORES.get(rating, 0)
    duration_ms = int((time.time() - start_time) * 1000)
    logger.info(
        "LLM judge direct fallback completed: rating=%s score=%s duration_ms=%s",
        rating,
        score,
        duration_ms,
    )
    return LLMJudgeResult(
        score=score,
        explanation=explanation,
        issues=[],
        rating=rating,
        duration_ms=duration_ms,
        error=False,
        trace_id=trace_id,
        run_id=None,
    )


async def evaluate_with_judge(
    genie_data: str,
    slide_content: str,
    model: str = DEFAULT_CONFIG["llm"]["endpoint"],
    trace_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    judge_backend: Optional[str] = None,
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
        experiment_id: Optional MLflow experiment ID to use (per-session experiment)
        judge_backend: ``direct`` (default) or ``mlflow``. When ``None``, reads
            ``llm_judge_backend`` from app settings (Admin Judge panel).

    Returns:
        LLMJudgeResult with score, explanation, issues, and metadata
    """
    start_time = time.time()

    from src.core.settings_db import get_settings, normalize_llm_judge_backend

    if judge_backend is None:
        try:
            resolved = normalize_llm_judge_backend(get_settings().llm_judge_backend)
        except Exception:
            resolved = "direct"
    else:
        resolved = normalize_llm_judge_backend(judge_backend)

    if resolved == "direct":
        logger.info("LLM judge: using direct ChatDatabricks backend (admin setting or caller)")
        return await asyncio.to_thread(
            _evaluate_with_judge_direct_llm,
            genie_data,
            slide_content,
            model,
            start_time,
            trace_id,
        )

    try:
        import mlflow
        from mlflow.genai import make_judge

        # Set tracking URI to Databricks (not local ./mlruns)
        mlflow.set_tracking_uri("databricks")
        configure_tracing_environment()
        logger.info("LLM judge: set MLflow tracking URI to databricks")

        # Use passed experiment_id (per-session) or compute user experiment path
        if experiment_id:
            logger.info(
                f"LLM judge: using per-session experiment_id: {experiment_id}"
            )
            mlflow.set_experiment(experiment_id=experiment_id)
        else:
            # Fallback: dynamically compute user's experiment path
            logger.warning("LLM judge: no experiment_id passed, computing user experiment path")
            from src.core.databricks_client import (
                get_current_username,
                get_service_principal_folder,
            )

            try:
                username = get_current_username()
                sp_folder = get_service_principal_folder()

                if sp_folder:
                    experiment_name = f"{sp_folder}/{username}/ai-slide-generator"
                else:
                    experiment_name = f"/Workspace/Users/{username}/ai-slide-generator"

                logger.info(f"LLM judge: computed experiment path: {experiment_name}")
            except Exception as e:
                logger.error(f"LLM judge: failed to get username for experiment: {e}")
                raise

            experiment = mlflow.get_experiment_by_name(experiment_name)
            if experiment is None:
                logger.warning(f"LLM judge: experiment not found, creating: {experiment_name}")

                # Ensure parent folder exists before creating experiment
                if sp_folder:
                    from src.core.databricks_client import ensure_workspace_folder
                    parent_folder = f"{sp_folder}/{username}"
                    try:
                        ensure_workspace_folder(parent_folder)
                    except Exception as e:
                        logger.warning(
                            "LLM judge: failed to create parent folder %s: %s",
                            parent_folder,
                            e,
                        )
                        # Continue anyway - experiment creation might still work

                experiment_id = create_databricks_experiment(experiment_name)
                logger.info(f"LLM judge: created experiment with ID: {experiment_id}")
            else:
                experiment_id = experiment.experiment_id
                logger.info(f"LLM judge: using existing experiment ID: {experiment_id}")
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
        try:
            eval_result = mlflow.genai.evaluate(
                data=eval_data,
                scorers=[accuracy_judge],
            )
        except Exception as eval_exc:
            if _mlflow_evaluate_should_use_direct_fallback(eval_exc):
                logger.warning(
                    "MLflow genai.evaluate failed (egress or MLflow state); "
                    "using direct LLM judge without Evaluation Runs. Error: %s",
                    eval_exc,
                )
                return await asyncio.to_thread(
                    _evaluate_with_judge_direct_llm,
                    genie_data,
                    slide_content,
                    model,
                    start_time,
                    trace_id,
                )
            raise

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
