"""Service for AI-powered feedback and survey operations."""

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from databricks_langchain import ChatDatabricks
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from src.database.models.feedback import FeedbackConversation, SurveyResponse

logger = logging.getLogger(__name__)

FEEDBACK_SYSTEM_PROMPT = """You are a feedback assistant for tellr, a presentation generation tool.
Your job is to help users articulate their feedback clearly.

Rules:
- Ask at most 2 clarifying questions to understand the user's feedback
- Keep your responses short (1-2 sentences per question)
- After at most 2 clarifying questions, produce a structured summary
- Present the summary in this exact format:

**Summary**
- **Category:** [Bug Report | Feature Request | UX Issue | Performance | Content Quality | Other]
- **Issue:** [One sentence description]
- **Severity:** [Low | Medium | High]
- **Details:** [2-3 sentences with specifics]

Does this look right?

- If the user confirms, respond with exactly: "FEEDBACK_CONFIRMED"
- If the user corrects something, revise the summary and ask again
- If the user's initial message is already clear and specific, skip questions and go
  straight to the summary"""

FEEDBACK_CONFIRMED_SENTINEL = "FEEDBACK_CONFIRMED"


def get_feedback_endpoint() -> str:
    """Get the LLM endpoint for feedback, with fallback to profile config."""
    endpoint = os.environ.get("FEEDBACK_LLM_ENDPOINT")
    if endpoint:
        return endpoint
    try:
        from src.core.settings_db import get_settings

        settings = get_settings()
        return settings.llm.endpoint
    except Exception:
        logger.warning("No FEEDBACK_LLM_ENDPOINT set and no active profile found")
        raise ValueError(
            "No feedback LLM endpoint configured. "
            "Set FEEDBACK_LLM_ENDPOINT or configure an active profile."
        )


def _format_minutes(minutes: int) -> str:
    """Format minutes into a human-readable string."""
    if minutes == 0:
        return "0 minutes"
    hours = minutes // 60
    remaining = minutes % 60
    if hours == 0:
        return f"{remaining} minutes"
    if remaining == 0:
        return f"{hours} hours" if hours > 1 else "1 hour"
    return f"{hours} hours {remaining} minutes"


class FeedbackService:
    """Handles feedback chat, submission, and survey operations."""

    def __init__(self, endpoint: Optional[str] = None):
        self.endpoint = endpoint or get_feedback_endpoint()

    def chat(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Send a feedback conversation to the LLM and return the response."""
        model = ChatDatabricks(endpoint=self.endpoint, temperature=0.3, max_tokens=500)

        lc_messages = [SystemMessage(content=FEEDBACK_SYSTEM_PROMPT)]
        for msg in messages:
            if msg["role"] == "user":
                lc_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                lc_messages.append(AIMessage(content=msg["content"]))

        response = model.invoke(lc_messages)
        content = response.content.strip()
        summary_ready = FEEDBACK_CONFIRMED_SENTINEL in content

        return {"content": content, "summary_ready": summary_ready}

    def submit_feedback(
        self,
        db: Session,
        category: str,
        summary: str,
        severity: str,
        raw_conversation: List[Dict[str, str]],
    ) -> FeedbackConversation:
        """Store confirmed feedback in the database."""
        feedback = FeedbackConversation(
            category=category,
            summary=summary,
            severity=severity,
            raw_conversation=raw_conversation,
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)
        return feedback

    def submit_survey(
        self,
        db: Session,
        star_rating: int,
        time_saved_minutes: Optional[int] = None,
        nps_score: Optional[int] = None,
    ) -> SurveyResponse:
        """Store a survey response in the database."""
        survey = SurveyResponse(
            star_rating=star_rating,
            time_saved_minutes=time_saved_minutes,
            nps_score=nps_score,
        )
        db.add(survey)
        db.commit()
        db.refresh(survey)
        return survey

    def get_stats_report(self, db: Session, weeks: int = 12) -> Dict[str, Any]:
        """Generate weekly aggregated stats from survey responses."""
        cutoff = datetime.utcnow() - timedelta(weeks=weeks)
        responses = (
            db.query(SurveyResponse)
            .filter(SurveyResponse.created_at >= cutoff)
            .order_by(SurveyResponse.created_at.desc())
            .all()
        )

        if not responses:
            return {
                "weeks": [],
                "totals": {
                    "total_responses": 0,
                    "avg_star_rating": None,
                    "avg_nps_score": None,
                    "total_time_saved_minutes": 0,
                    "time_saved_display": "0 minutes",
                },
            }

        weekly: Dict[str, list] = defaultdict(list)
        for r in responses:
            week_start = r.created_at - timedelta(days=r.created_at.weekday())
            week_key = week_start.strftime("%Y-%m-%d")
            weekly[week_key].append(r)

        week_results = []
        for week_start_str in sorted(weekly.keys(), reverse=True):
            items = weekly[week_start_str]
            week_start = datetime.strptime(week_start_str, "%Y-%m-%d")
            week_end = week_start + timedelta(days=6)
            stars = [r.star_rating for r in items]
            nps_scores = [r.nps_score for r in items if r.nps_score is not None]
            time_saved = sum(r.time_saved_minutes or 0 for r in items)
            week_results.append(
                {
                    "week_start": week_start_str,
                    "week_end": week_end.strftime("%Y-%m-%d"),
                    "responses": len(items),
                    "avg_star_rating": round(sum(stars) / len(stars), 1) if stars else None,
                    "avg_nps_score": (
                        round(sum(nps_scores) / len(nps_scores), 1) if nps_scores else None
                    ),
                    "total_time_saved_minutes": time_saved,
                    "time_saved_display": _format_minutes(time_saved),
                }
            )

        all_stars = [r.star_rating for r in responses]
        all_nps = [r.nps_score for r in responses if r.nps_score is not None]
        total_time = sum(r.time_saved_minutes or 0 for r in responses)

        return {
            "weeks": week_results,
            "totals": {
                "total_responses": len(responses),
                "avg_star_rating": (
                    round(sum(all_stars) / len(all_stars), 1) if all_stars else None
                ),
                "avg_nps_score": (round(sum(all_nps) / len(all_nps), 1) if all_nps else None),
                "total_time_saved_minutes": total_time,
                "time_saved_display": _format_minutes(total_time),
            },
        }

    def get_feedback_summary(self, db: Session, weeks: int = 4) -> Dict[str, Any]:
        """Generate an AI summary of feedback conversations."""
        cutoff = datetime.utcnow() - timedelta(weeks=weeks)
        end_date = datetime.utcnow()
        feedbacks = (
            db.query(FeedbackConversation)
            .filter(FeedbackConversation.created_at >= cutoff)
            .order_by(FeedbackConversation.created_at.desc())
            .all()
        )
        period = f"{cutoff.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"

        if not feedbacks:
            return {
                "period": period,
                "feedback_count": 0,
                "summary": "No feedback received in this period.",
                "category_breakdown": {},
                "top_themes": [],
            }

        category_counts = Counter(f.category for f in feedbacks)
        feedback_text = "\n".join(f"- [{f.category}] ({f.severity}) {f.summary}" for f in feedbacks)

        report_prompt = f"""Analyze the following user feedback for tellr.
Produce a JSON response with:
- "summary": A concise executive summary (3-5 sentences)
- "top_themes": A list of 3-5 key themes

Feedback items:
{feedback_text}

Respond with valid JSON only."""

        model = ChatDatabricks(endpoint=self.endpoint, temperature=0.2, max_tokens=800)
        response = model.invoke([HumanMessage(content=report_prompt)])

        try:
            parsed = json.loads(response.content)
            summary = parsed.get("summary", response.content)
            top_themes = parsed.get("top_themes", [])
        except (json.JSONDecodeError, AttributeError):
            summary = response.content
            top_themes = []

        return {
            "period": period,
            "feedback_count": len(feedbacks),
            "summary": summary,
            "category_breakdown": dict(category_counts),
            "top_themes": top_themes,
        }
