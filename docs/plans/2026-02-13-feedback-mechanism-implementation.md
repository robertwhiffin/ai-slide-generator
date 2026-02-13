# Feedback Mechanism Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every task - NO production code without a failing test first.

**Goal:** Add an AI-powered feedback widget, periodic satisfaction survey, and reporting API to tellr.

**Architecture:** Two new DB tables (`feedback_conversations`, `survey_responses`), a new FastAPI router (`/api/feedback/`), a lightweight LLM service for feedback chat, and React components (floating button + popover, survey modal). The feedback LLM endpoint is configured via `FEEDBACK_LLM_ENDPOINT` env var with fallback to the active profile's model.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React 19/TypeScript/Tailwind (frontend), ChatDatabricks (LLM), Playwright (frontend tests), pytest (backend tests).

**Design doc:** `docs/plans/2026-02-13-feedback-mechanism-design.md`

---

## Task 1: Database Models

**Files:**
- Create: `src/database/models/feedback.py`
- Modify: `src/database/models/__init__.py`
- Test: `tests/unit/test_feedback_models.py`

### Step 1: Write the failing test

Create `tests/unit/test_feedback_models.py`:

```python
"""Unit tests for feedback database models."""
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    # Import models to register them with Base
    from src.database.models.feedback import FeedbackConversation, SurveyResponse
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestFeedbackConversation:
    """Tests for FeedbackConversation model."""

    def test_create_feedback_conversation(self, db_session):
        """Test creating a feedback conversation record."""
        from src.database.models.feedback import FeedbackConversation

        feedback = FeedbackConversation(
            category="Bug Report",
            summary="Text unreadable on dark backgrounds",
            severity="High",
            raw_conversation=[
                {"role": "user", "content": "Text is hard to read"},
                {"role": "assistant", "content": "Can you clarify?"},
            ],
        )
        db_session.add(feedback)
        db_session.commit()

        result = db_session.query(FeedbackConversation).first()
        assert result is not None
        assert result.id is not None
        assert result.category == "Bug Report"
        assert result.summary == "Text unreadable on dark backgrounds"
        assert result.severity == "High"
        assert len(result.raw_conversation) == 2
        assert result.created_at is not None

    def test_feedback_conversation_table_name(self):
        """Test the table name is correct."""
        from src.database.models.feedback import FeedbackConversation
        assert FeedbackConversation.__tablename__ == "feedback_conversations"


class TestSurveyResponse:
    """Tests for SurveyResponse model."""

    def test_create_survey_response_full(self, db_session):
        """Test creating a survey response with all fields."""
        from src.database.models.feedback import SurveyResponse

        survey = SurveyResponse(
            star_rating=4,
            time_saved_minutes=120,
            nps_score=8,
        )
        db_session.add(survey)
        db_session.commit()

        result = db_session.query(SurveyResponse).first()
        assert result is not None
        assert result.id is not None
        assert result.star_rating == 4
        assert result.time_saved_minutes == 120
        assert result.nps_score == 8
        assert result.created_at is not None

    def test_create_survey_response_partial(self, db_session):
        """Test creating a survey response with only star rating (others nullable)."""
        from src.database.models.feedback import SurveyResponse

        survey = SurveyResponse(star_rating=3)
        db_session.add(survey)
        db_session.commit()

        result = db_session.query(SurveyResponse).first()
        assert result.star_rating == 3
        assert result.time_saved_minutes is None
        assert result.nps_score is None

    def test_survey_response_table_name(self):
        """Test the table name is correct."""
        from src.database.models.feedback import SurveyResponse
        assert SurveyResponse.__tablename__ == "survey_responses"
```

### Step 2: Run test to verify it fails

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pytest tests/unit/test_feedback_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.database.models.feedback'`

### Step 3: Write minimal implementation

Create `src/database/models/feedback.py`:

```python
"""Feedback and survey database models."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.types import JSON

from src.core.database import Base


class FeedbackConversation(Base):
    """Stores AI-assisted feedback conversations and their structured summaries."""

    __tablename__ = "feedback_conversations"

    id = Column(Integer, primary_key=True)
    category = Column(String(50), nullable=False)
    summary = Column(Text, nullable=False)
    severity = Column(String(10), nullable=False)
    raw_conversation = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "category IN ('Bug Report', 'Feature Request', 'UX Issue', 'Performance', 'Content Quality', 'Other')",
            name="check_feedback_category",
        ),
        CheckConstraint(
            "severity IN ('Low', 'Medium', 'High')",
            name="check_feedback_severity",
        ),
    )

    def __repr__(self):
        return f"<FeedbackConversation(id={self.id}, category='{self.category}', severity='{self.severity}')>"


class SurveyResponse(Base):
    """Stores periodic satisfaction survey responses."""

    __tablename__ = "survey_responses"

    id = Column(Integer, primary_key=True)
    star_rating = Column(Integer, nullable=False)
    time_saved_minutes = Column(Integer, nullable=True)
    nps_score = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("star_rating >= 1 AND star_rating <= 5", name="check_star_rating_range"),
        CheckConstraint(
            "time_saved_minutes IN (15, 30, 60, 120, 240, 480) OR time_saved_minutes IS NULL",
            name="check_time_saved_values",
        ),
        CheckConstraint(
            "nps_score >= 0 AND nps_score <= 10 OR nps_score IS NULL",
            name="check_nps_score_range",
        ),
    )

    def __repr__(self):
        return f"<SurveyResponse(id={self.id}, stars={self.star_rating}, nps={self.nps_score})>"
```

Update `src/database/models/__init__.py` - add to imports:

```python
from src.database.models.feedback import FeedbackConversation, SurveyResponse
```

Add to `__all__`:

```python
"FeedbackConversation",
"SurveyResponse",
```

### Step 4: Run test to verify it passes

```bash
python -m pytest tests/unit/test_feedback_models.py -v
```

Expected: All 5 tests PASS

### Step 5: Commit

```bash
git add src/database/models/feedback.py src/database/models/__init__.py tests/unit/test_feedback_models.py
git commit -m "feat: add FeedbackConversation and SurveyResponse database models"
```

---

## Task 2: Pydantic Schemas

**Files:**
- Create: `src/api/schemas/feedback.py`
- Test: `tests/unit/test_feedback_schemas.py`

### Step 1: Write the failing test

Create `tests/unit/test_feedback_schemas.py`:

```python
"""Unit tests for feedback Pydantic schemas."""
import pytest
from pydantic import ValidationError


class TestFeedbackChatRequest:
    """Tests for FeedbackChatRequest schema."""

    def test_valid_request(self):
        from src.api.schemas.feedback import FeedbackChatRequest

        req = FeedbackChatRequest(
            messages=[{"role": "user", "content": "This feature is broken"}]
        )
        assert len(req.messages) == 1
        assert req.messages[0]["role"] == "user"

    def test_empty_messages_rejected(self):
        from src.api.schemas.feedback import FeedbackChatRequest

        with pytest.raises(ValidationError):
            FeedbackChatRequest(messages=[])


class TestFeedbackSubmitRequest:
    """Tests for FeedbackSubmitRequest schema."""

    def test_valid_submit(self):
        from src.api.schemas.feedback import FeedbackSubmitRequest

        req = FeedbackSubmitRequest(
            category="Bug Report",
            summary="Text unreadable on dark backgrounds",
            severity="High",
            raw_conversation=[
                {"role": "user", "content": "Text is hard to read"},
                {"role": "assistant", "content": "Summary..."},
            ],
        )
        assert req.category == "Bug Report"
        assert req.severity == "High"

    def test_invalid_category_rejected(self):
        from src.api.schemas.feedback import FeedbackSubmitRequest

        with pytest.raises(ValidationError):
            FeedbackSubmitRequest(
                category="Invalid",
                summary="test",
                severity="High",
                raw_conversation=[],
            )

    def test_invalid_severity_rejected(self):
        from src.api.schemas.feedback import FeedbackSubmitRequest

        with pytest.raises(ValidationError):
            FeedbackSubmitRequest(
                category="Bug Report",
                summary="test",
                severity="Critical",
                raw_conversation=[],
            )


class TestSurveySubmitRequest:
    """Tests for SurveySubmitRequest schema."""

    def test_valid_full_survey(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        req = SurveySubmitRequest(
            star_rating=4,
            time_saved_minutes=120,
            nps_score=8,
        )
        assert req.star_rating == 4
        assert req.time_saved_minutes == 120
        assert req.nps_score == 8

    def test_partial_survey_only_stars(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        req = SurveySubmitRequest(star_rating=3)
        assert req.star_rating == 3
        assert req.time_saved_minutes is None
        assert req.nps_score is None

    def test_star_rating_out_of_range(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        with pytest.raises(ValidationError):
            SurveySubmitRequest(star_rating=6)

    def test_star_rating_zero_rejected(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        with pytest.raises(ValidationError):
            SurveySubmitRequest(star_rating=0)

    def test_nps_out_of_range(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        with pytest.raises(ValidationError):
            SurveySubmitRequest(star_rating=3, nps_score=11)

    def test_invalid_time_saved(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        with pytest.raises(ValidationError):
            SurveySubmitRequest(star_rating=3, time_saved_minutes=45)


class TestFeedbackChatResponse:
    """Tests for FeedbackChatResponse schema."""

    def test_response_with_summary_ready(self):
        from src.api.schemas.feedback import FeedbackChatResponse

        resp = FeedbackChatResponse(content="Here is the summary", summary_ready=True)
        assert resp.content == "Here is the summary"
        assert resp.summary_ready is True

    def test_response_defaults_summary_ready_false(self):
        from src.api.schemas.feedback import FeedbackChatResponse

        resp = FeedbackChatResponse(content="Tell me more")
        assert resp.summary_ready is False


class TestStatsReportResponse:
    """Tests for StatsReportResponse schema."""

    def test_weekly_stats(self):
        from src.api.schemas.feedback import WeeklyStats, StatsReportResponse, StatsTotals

        week = WeeklyStats(
            week_start="2026-02-09",
            week_end="2026-02-15",
            responses=14,
            avg_star_rating=4.2,
            avg_nps_score=8.1,
            total_time_saved_minutes=1920,
            time_saved_display="32 hours",
        )
        totals = StatsTotals(
            total_responses=14,
            avg_star_rating=4.2,
            avg_nps_score=8.1,
            total_time_saved_minutes=1920,
            time_saved_display="32 hours",
        )
        report = StatsReportResponse(weeks=[week], totals=totals)
        assert len(report.weeks) == 1
        assert report.totals.total_responses == 14
```

### Step 2: Run test to verify it fails

```bash
python -m pytest tests/unit/test_feedback_schemas.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.schemas.feedback'`

### Step 3: Write minimal implementation

Create `src/api/schemas/feedback.py`:

```python
"""Pydantic schemas for feedback endpoints."""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# --- Allowed values ---

FEEDBACK_CATEGORIES = [
    "Bug Report",
    "Feature Request",
    "UX Issue",
    "Performance",
    "Content Quality",
    "Other",
]

FEEDBACK_SEVERITIES = ["Low", "Medium", "High"]

ALLOWED_TIME_SAVED = [15, 30, 60, 120, 240, 480]


# --- Request schemas ---


class FeedbackChatRequest(BaseModel):
    """Request for the feedback chat endpoint."""

    messages: List[Dict[str, str]] = Field(
        ...,
        description="Conversation history as list of {role, content} dicts",
        min_length=1,
    )


class FeedbackSubmitRequest(BaseModel):
    """Request to submit confirmed feedback."""

    category: str = Field(..., description="Feedback category")
    summary: str = Field(..., description="AI-generated summary the user confirmed")
    severity: str = Field(..., description="Severity level")
    raw_conversation: List[Dict[str, str]] = Field(
        ..., description="Full conversation history"
    )

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in FEEDBACK_CATEGORIES:
            raise ValueError(f"Category must be one of: {FEEDBACK_CATEGORIES}")
        return value

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        if value not in FEEDBACK_SEVERITIES:
            raise ValueError(f"Severity must be one of: {FEEDBACK_SEVERITIES}")
        return value


class SurveySubmitRequest(BaseModel):
    """Request to submit a survey response."""

    star_rating: int = Field(..., ge=1, le=5, description="Star rating 1-5")
    time_saved_minutes: Optional[int] = Field(
        default=None, description="Time saved in minutes"
    )
    nps_score: Optional[int] = Field(
        default=None, ge=0, le=10, description="NPS score 0-10"
    )

    @field_validator("time_saved_minutes")
    @classmethod
    def validate_time_saved(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value not in ALLOWED_TIME_SAVED:
            raise ValueError(f"time_saved_minutes must be one of: {ALLOWED_TIME_SAVED}")
        return value


# --- Response schemas ---


class FeedbackChatResponse(BaseModel):
    """Response from the feedback chat endpoint."""

    content: str = Field(..., description="AI response text")
    summary_ready: bool = Field(
        default=False,
        description="Whether the AI has produced a confirmed summary",
    )


class FeedbackSubmitResponse(BaseModel):
    """Response after submitting feedback."""

    id: int
    message: str = "Feedback submitted successfully"


class SurveySubmitResponse(BaseModel):
    """Response after submitting a survey."""

    id: int
    message: str = "Survey response submitted successfully"


# --- Report schemas ---


class WeeklyStats(BaseModel):
    """Stats for a single week."""

    week_start: str
    week_end: str
    responses: int
    avg_star_rating: Optional[float]
    avg_nps_score: Optional[float]
    total_time_saved_minutes: int
    time_saved_display: str


class StatsTotals(BaseModel):
    """Overall totals across all weeks."""

    total_responses: int
    avg_star_rating: Optional[float]
    avg_nps_score: Optional[float]
    total_time_saved_minutes: int
    time_saved_display: str


class StatsReportResponse(BaseModel):
    """Response for the stats report endpoint."""

    weeks: List[WeeklyStats]
    totals: StatsTotals


class FeedbackSummaryResponse(BaseModel):
    """Response for the AI feedback summary endpoint."""

    period: str
    feedback_count: int
    summary: str
    category_breakdown: Dict[str, int]
    top_themes: List[str]
```

### Step 4: Run test to verify it passes

```bash
python -m pytest tests/unit/test_feedback_schemas.py -v
```

Expected: All tests PASS

### Step 5: Commit

```bash
git add src/api/schemas/feedback.py tests/unit/test_feedback_schemas.py
git commit -m "feat: add Pydantic schemas for feedback endpoints"
```

---

## Task 3: Feedback Service - Chat & Submit

**Files:**
- Create: `src/api/services/feedback_service.py`
- Test: `tests/unit/test_feedback_service.py`

### Step 1: Write the failing test

Create `tests/unit/test_feedback_service.py`:

```python
"""Unit tests for the feedback service."""
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    """In-memory SQLite for testing."""
    engine = create_engine("sqlite:///:memory:")
    from src.database.models.feedback import FeedbackConversation, SurveyResponse
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestFeedbackChat:
    """Tests for the feedback chat LLM call."""

    @patch("src.api.services.feedback_service.ChatDatabricks")
    def test_chat_returns_ai_response(self, mock_chat_class):
        """Test that chat calls the LLM and returns the response."""
        from src.api.services.feedback_service import FeedbackService

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.content = "Can you tell me more about that issue?"
        mock_model.invoke.return_value = mock_response
        mock_chat_class.return_value = mock_model

        service = FeedbackService(endpoint="test-endpoint")
        result = service.chat([{"role": "user", "content": "Something is broken"}])

        assert result["content"] == "Can you tell me more about that issue?"
        assert result["summary_ready"] is False

    @patch("src.api.services.feedback_service.ChatDatabricks")
    def test_chat_detects_feedback_confirmed(self, mock_chat_class):
        """Test that FEEDBACK_CONFIRMED sentinel sets summary_ready=True."""
        from src.api.services.feedback_service import FeedbackService

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.content = "FEEDBACK_CONFIRMED"
        mock_model.invoke.return_value = mock_response
        mock_chat_class.return_value = mock_model

        service = FeedbackService(endpoint="test-endpoint")
        result = service.chat([
            {"role": "user", "content": "Yes, that looks right"},
        ])

        assert result["summary_ready"] is True

    @patch("src.api.services.feedback_service.ChatDatabricks")
    def test_chat_prepends_system_prompt(self, mock_chat_class):
        """Test that the system prompt is prepended to the conversation."""
        from src.api.services.feedback_service import FeedbackService

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.content = "Tell me more"
        mock_model.invoke.return_value = mock_response
        mock_chat_class.return_value = mock_model

        service = FeedbackService(endpoint="test-endpoint")
        service.chat([{"role": "user", "content": "Bug report"}])

        # Verify invoke was called with messages starting with SystemMessage
        call_args = mock_model.invoke.call_args[0][0]
        from langchain_core.messages import SystemMessage
        assert isinstance(call_args[0], SystemMessage)


class TestFeedbackSubmit:
    """Tests for submitting feedback to the database."""

    def test_submit_feedback_creates_record(self, db_session):
        """Test that submitting feedback creates a DB record."""
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.submit_feedback(
            db=db_session,
            category="Bug Report",
            summary="Text unreadable on dark backgrounds",
            severity="High",
            raw_conversation=[
                {"role": "user", "content": "text is hard to read"},
            ],
        )

        assert result.id is not None
        assert result.category == "Bug Report"

        from src.database.models.feedback import FeedbackConversation
        count = db_session.query(FeedbackConversation).count()
        assert count == 1


class TestSurveySubmit:
    """Tests for submitting survey responses."""

    def test_submit_survey_creates_record(self, db_session):
        """Test that submitting a survey creates a DB record."""
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.submit_survey(
            db=db_session,
            star_rating=4,
            time_saved_minutes=120,
            nps_score=8,
        )

        assert result.id is not None
        assert result.star_rating == 4

        from src.database.models.feedback import SurveyResponse
        count = db_session.query(SurveyResponse).count()
        assert count == 1

    def test_submit_survey_partial(self, db_session):
        """Test partial survey (only star rating)."""
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.submit_survey(db=db_session, star_rating=5)

        assert result.star_rating == 5
        assert result.time_saved_minutes is None
        assert result.nps_score is None
```

### Step 2: Run test to verify it fails

```bash
python -m pytest tests/unit/test_feedback_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.services.feedback_service'`

### Step 3: Write minimal implementation

Create `src/api/services/feedback_service.py`:

```python
"""Service for AI-powered feedback and survey operations."""
import logging
import os
from typing import Any, Dict, List, Optional

from databricks_langchain import ChatDatabricks
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from src.database.models.feedback import FeedbackConversation, SurveyResponse

logger = logging.getLogger(__name__)

FEEDBACK_SYSTEM_PROMPT = """You are a feedback assistant for tellr, a presentation generation tool. Your job is to help users articulate their feedback clearly.

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
- If the user's initial message is already clear and specific, skip questions and go straight to the summary"""

FEEDBACK_CONFIRMED_SENTINEL = "FEEDBACK_CONFIRMED"


def get_feedback_endpoint() -> str:
    """Get the LLM endpoint for feedback, with fallback to profile config."""
    endpoint = os.environ.get("FEEDBACK_LLM_ENDPOINT")
    if endpoint:
        return endpoint

    # Fallback: try to get from active profile
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


class FeedbackService:
    """Handles feedback chat, submission, and survey operations."""

    def __init__(self, endpoint: Optional[str] = None):
        self.endpoint = endpoint or get_feedback_endpoint()

    def chat(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Send a feedback conversation to the LLM and return the response.

        Args:
            messages: Conversation history as list of {role, content} dicts.

        Returns:
            Dict with 'content' (str) and 'summary_ready' (bool).
        """
        model = ChatDatabricks(
            endpoint=self.endpoint,
            temperature=0.3,
            max_tokens=500,
        )

        # Build LangChain message list
        lc_messages = [SystemMessage(content=FEEDBACK_SYSTEM_PROMPT)]
        for msg in messages:
            if msg["role"] == "user":
                lc_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                lc_messages.append(AIMessage(content=msg["content"]))

        response = model.invoke(lc_messages)
        content = response.content.strip()

        summary_ready = FEEDBACK_CONFIRMED_SENTINEL in content

        return {
            "content": content,
            "summary_ready": summary_ready,
        }

    def submit_feedback(
        self,
        db: Session,
        category: str,
        summary: str,
        severity: str,
        raw_conversation: List[Dict[str, str]],
    ) -> FeedbackConversation:
        """Store confirmed feedback in the database.

        Args:
            db: SQLAlchemy session.
            category: Feedback category.
            summary: AI-generated summary.
            severity: Severity level.
            raw_conversation: Full conversation history.

        Returns:
            The created FeedbackConversation record.
        """
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
        """Store a survey response in the database.

        Args:
            db: SQLAlchemy session.
            star_rating: 1-5 star rating.
            time_saved_minutes: Time saved in minutes (nullable).
            nps_score: NPS score 0-10 (nullable).

        Returns:
            The created SurveyResponse record.
        """
        survey = SurveyResponse(
            star_rating=star_rating,
            time_saved_minutes=time_saved_minutes,
            nps_score=nps_score,
        )
        db.add(survey)
        db.commit()
        db.refresh(survey)
        return survey
```

### Step 4: Run test to verify it passes

```bash
python -m pytest tests/unit/test_feedback_service.py -v
```

Expected: All tests PASS

### Step 5: Commit

```bash
git add src/api/services/feedback_service.py tests/unit/test_feedback_service.py
git commit -m "feat: add FeedbackService with chat, submit, and survey methods"
```

---

## Task 4: Feedback Service - Reporting

**Files:**
- Modify: `src/api/services/feedback_service.py`
- Modify: `tests/unit/test_feedback_service.py`

### Step 1: Write the failing test

Add to `tests/unit/test_feedback_service.py`:

```python
from datetime import datetime, timedelta


class TestStatsReport:
    """Tests for the stats report aggregation."""

    def test_stats_report_empty(self, db_session):
        """Test stats report with no data returns empty weeks."""
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.get_stats_report(db=db_session, weeks=4)

        assert result["weeks"] == []
        assert result["totals"]["total_responses"] == 0

    def test_stats_report_with_data(self, db_session):
        """Test stats report aggregates correctly."""
        from src.api.services.feedback_service import FeedbackService
        from src.database.models.feedback import SurveyResponse

        # Add two survey responses
        db_session.add(SurveyResponse(star_rating=4, time_saved_minutes=60, nps_score=8))
        db_session.add(SurveyResponse(star_rating=2, time_saved_minutes=120, nps_score=6))
        db_session.commit()

        service = FeedbackService(endpoint="test-endpoint")
        result = service.get_stats_report(db=db_session, weeks=4)

        assert result["totals"]["total_responses"] == 2
        assert result["totals"]["avg_star_rating"] == 3.0
        assert result["totals"]["avg_nps_score"] == 7.0
        assert result["totals"]["total_time_saved_minutes"] == 180


class TestFeedbackSummaryReport:
    """Tests for the AI feedback summary report."""

    @patch("src.api.services.feedback_service.ChatDatabricks")
    def test_summary_report_with_feedback(self, mock_chat_class, db_session):
        """Test AI summary report generation."""
        from src.api.services.feedback_service import FeedbackService
        from src.database.models.feedback import FeedbackConversation

        # Add feedback records
        db_session.add(FeedbackConversation(
            category="Bug Report",
            summary="Text unreadable on dark backgrounds",
            severity="High",
            raw_conversation=[],
        ))
        db_session.add(FeedbackConversation(
            category="Feature Request",
            summary="Want Google Slides export",
            severity="Low",
            raw_conversation=[],
        ))
        db_session.commit()

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.content = '{"summary": "Two items of feedback received.", "top_themes": ["Dark mode readability", "Export options"]}'
        mock_model.invoke.return_value = mock_response
        mock_chat_class.return_value = mock_model

        service = FeedbackService(endpoint="test-endpoint")
        result = service.get_feedback_summary(db=db_session, weeks=4)

        assert result["feedback_count"] == 2
        assert result["category_breakdown"]["Bug Report"] == 1
        assert result["category_breakdown"]["Feature Request"] == 1

    def test_summary_report_empty(self, db_session):
        """Test AI summary with no feedback returns empty result."""
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.get_feedback_summary(db=db_session, weeks=4)

        assert result["feedback_count"] == 0
        assert result["summary"] == "No feedback received in this period."
```

### Step 2: Run test to verify it fails

```bash
python -m pytest tests/unit/test_feedback_service.py::TestStatsReport -v
python -m pytest tests/unit/test_feedback_service.py::TestFeedbackSummaryReport -v
```

Expected: FAIL with `AttributeError: 'FeedbackService' object has no attribute 'get_stats_report'`

### Step 3: Write minimal implementation

Add to `src/api/services/feedback_service.py` (inside the `FeedbackService` class):

```python
    def get_stats_report(self, db: Session, weeks: int = 12) -> Dict[str, Any]:
        """Generate weekly aggregated stats from survey responses.

        Args:
            db: SQLAlchemy session.
            weeks: Number of weeks of history to include.

        Returns:
            Dict with 'weeks' list and 'totals' object.
        """
        from sqlalchemy import func

        cutoff = datetime.utcnow() - timedelta(weeks=weeks)

        # Query all responses in the window
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

        # Group by week
        from collections import defaultdict
        weekly: Dict[str, list] = defaultdict(list)
        for r in responses:
            # Get the Monday of the week
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

            week_results.append({
                "week_start": week_start_str,
                "week_end": week_end.strftime("%Y-%m-%d"),
                "responses": len(items),
                "avg_star_rating": round(sum(stars) / len(stars), 1) if stars else None,
                "avg_nps_score": round(sum(nps_scores) / len(nps_scores), 1) if nps_scores else None,
                "total_time_saved_minutes": time_saved,
                "time_saved_display": _format_minutes(time_saved),
            })

        # Totals
        all_stars = [r.star_rating for r in responses]
        all_nps = [r.nps_score for r in responses if r.nps_score is not None]
        total_time = sum(r.time_saved_minutes or 0 for r in responses)

        return {
            "weeks": week_results,
            "totals": {
                "total_responses": len(responses),
                "avg_star_rating": round(sum(all_stars) / len(all_stars), 1) if all_stars else None,
                "avg_nps_score": round(sum(all_nps) / len(all_nps), 1) if all_nps else None,
                "total_time_saved_minutes": total_time,
                "time_saved_display": _format_minutes(total_time),
            },
        }

    def get_feedback_summary(self, db: Session, weeks: int = 4) -> Dict[str, Any]:
        """Generate an AI summary of feedback conversations.

        Args:
            db: SQLAlchemy session.
            weeks: Number of weeks of feedback to summarize.

        Returns:
            Dict with summary, category breakdown, and top themes.
        """
        import json

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

        # Category breakdown
        from collections import Counter
        category_counts = Counter(f.category for f in feedbacks)

        # Build context for LLM
        feedback_text = "\n".join(
            f"- [{f.category}] ({f.severity}) {f.summary}" for f in feedbacks
        )

        report_prompt = f"""Analyze the following user feedback for tellr and produce a JSON response with:
- "summary": A concise executive summary (3-5 sentences) covering top themes, severity patterns, and recommendations
- "top_themes": A list of 3-5 key themes extracted from the feedback

Feedback items:
{feedback_text}

Respond with valid JSON only."""

        model = ChatDatabricks(
            endpoint=self.endpoint,
            temperature=0.2,
            max_tokens=800,
        )
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
```

Add helper function outside the class:

```python
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
```

Also add the missing import at the top of the file:

```python
from datetime import datetime, timedelta
```

### Step 4: Run test to verify it passes

```bash
python -m pytest tests/unit/test_feedback_service.py -v
```

Expected: All tests PASS

### Step 5: Commit

```bash
git add src/api/services/feedback_service.py tests/unit/test_feedback_service.py
git commit -m "feat: add stats report and AI feedback summary to FeedbackService"
```

---

## Task 5: Feedback Router

**Files:**
- Create: `src/api/routes/feedback.py`
- Modify: `src/api/main.py`
- Test: `tests/unit/test_feedback_routes.py`

### Step 1: Write the failing test

Create `tests/unit/test_feedback_routes.py`:

```python
"""Unit tests for feedback API routes."""
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    from src.api.main import app
    return TestClient(app)


class TestFeedbackChatEndpoint:
    """Tests for POST /api/feedback/chat."""

    @patch("src.api.routes.feedback.FeedbackService")
    def test_chat_returns_response(self, mock_service_class, client):
        mock_instance = MagicMock()
        mock_instance.chat.return_value = {
            "content": "Tell me more about the issue.",
            "summary_ready": False,
        }
        mock_service_class.return_value = mock_instance

        response = client.post(
            "/api/feedback/chat",
            json={"messages": [{"role": "user", "content": "Something broke"}]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Tell me more about the issue."
        assert data["summary_ready"] is False

    def test_chat_empty_messages_rejected(self, client):
        response = client.post("/api/feedback/chat", json={"messages": []})
        assert response.status_code == 422


class TestFeedbackSubmitEndpoint:
    """Tests for POST /api/feedback/submit."""

    @patch("src.api.routes.feedback.FeedbackService")
    def test_submit_returns_id(self, mock_service_class, client):
        mock_instance = MagicMock()
        mock_record = Mock()
        mock_record.id = 42
        mock_instance.submit_feedback.return_value = mock_record
        mock_service_class.return_value = mock_instance

        response = client.post(
            "/api/feedback/submit",
            json={
                "category": "Bug Report",
                "summary": "Text unreadable",
                "severity": "High",
                "raw_conversation": [{"role": "user", "content": "broken"}],
            },
        )

        assert response.status_code == 200
        assert response.json()["id"] == 42


class TestSurveyEndpoint:
    """Tests for POST /api/feedback/survey."""

    @patch("src.api.routes.feedback.FeedbackService")
    def test_survey_submit(self, mock_service_class, client):
        mock_instance = MagicMock()
        mock_record = Mock()
        mock_record.id = 7
        mock_instance.submit_survey.return_value = mock_record
        mock_service_class.return_value = mock_instance

        response = client.post(
            "/api/feedback/survey",
            json={"star_rating": 4, "time_saved_minutes": 120, "nps_score": 8},
        )

        assert response.status_code == 200
        assert response.json()["id"] == 7

    def test_survey_invalid_star_rating(self, client):
        response = client.post(
            "/api/feedback/survey",
            json={"star_rating": 0},
        )
        assert response.status_code == 422


class TestStatsReportEndpoint:
    """Tests for GET /api/feedback/report/stats."""

    @patch("src.api.routes.feedback.FeedbackService")
    def test_stats_report(self, mock_service_class, client):
        mock_instance = MagicMock()
        mock_instance.get_stats_report.return_value = {
            "weeks": [],
            "totals": {
                "total_responses": 0,
                "avg_star_rating": None,
                "avg_nps_score": None,
                "total_time_saved_minutes": 0,
                "time_saved_display": "0 minutes",
            },
        }
        mock_service_class.return_value = mock_instance

        response = client.get("/api/feedback/report/stats")

        assert response.status_code == 200
        assert response.json()["totals"]["total_responses"] == 0

    @patch("src.api.routes.feedback.FeedbackService")
    def test_stats_report_custom_weeks(self, mock_service_class, client):
        mock_instance = MagicMock()
        mock_instance.get_stats_report.return_value = {
            "weeks": [],
            "totals": {
                "total_responses": 0,
                "avg_star_rating": None,
                "avg_nps_score": None,
                "total_time_saved_minutes": 0,
                "time_saved_display": "0 minutes",
            },
        }
        mock_service_class.return_value = mock_instance

        response = client.get("/api/feedback/report/stats?weeks=8")

        assert response.status_code == 200
        mock_instance.get_stats_report.assert_called_once()
```

### Step 2: Run test to verify it fails

```bash
python -m pytest tests/unit/test_feedback_routes.py -v
```

Expected: FAIL (route not found, 404s)

### Step 3: Write minimal implementation

Create `src/api/routes/feedback.py`:

```python
"""Feedback and survey API endpoints."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.api.schemas.feedback import (
    FeedbackChatRequest,
    FeedbackChatResponse,
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
    FeedbackSummaryResponse,
    StatsReportResponse,
    SurveySubmitRequest,
    SurveySubmitResponse,
)
from src.api.services.feedback_service import FeedbackService
from src.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("/chat", response_model=FeedbackChatResponse)
def feedback_chat(request: FeedbackChatRequest):
    """Send a message in the feedback conversation and get an AI response.

    The frontend sends the full conversation history each time.
    The backend prepends the system prompt and calls the LLM.
    """
    try:
        service = FeedbackService()
        result = service.chat(request.messages)
        return FeedbackChatResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        logger.error(f"Feedback chat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get feedback response",
        )


@router.post("/submit", response_model=FeedbackSubmitResponse)
def submit_feedback(
    request: FeedbackSubmitRequest,
    db: Session = Depends(get_db),
):
    """Submit confirmed feedback (raw conversation + structured summary)."""
    try:
        service = FeedbackService()
        record = service.submit_feedback(
            db=db,
            category=request.category,
            summary=request.summary,
            severity=request.severity,
            raw_conversation=request.raw_conversation,
        )
        return FeedbackSubmitResponse(id=record.id)
    except Exception as e:
        logger.error(f"Feedback submit error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit feedback",
        )


@router.post("/survey", response_model=SurveySubmitResponse)
def submit_survey(
    request: SurveySubmitRequest,
    db: Session = Depends(get_db),
):
    """Submit a satisfaction survey response."""
    try:
        service = FeedbackService()
        record = service.submit_survey(
            db=db,
            star_rating=request.star_rating,
            time_saved_minutes=request.time_saved_minutes,
            nps_score=request.nps_score,
        )
        return SurveySubmitResponse(id=record.id)
    except Exception as e:
        logger.error(f"Survey submit error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit survey",
        )


@router.get("/report/stats")
def get_stats_report(
    weeks: int = Query(default=12, ge=1, le=52),
    db: Session = Depends(get_db),
):
    """Get weekly aggregated stats from survey responses."""
    try:
        service = FeedbackService()
        return service.get_stats_report(db=db, weeks=weeks)
    except Exception as e:
        logger.error(f"Stats report error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate stats report",
        )


@router.get("/report/summary")
def get_feedback_summary(
    weeks: int = Query(default=4, ge=1, le=52),
    db: Session = Depends(get_db),
):
    """Get an AI-generated summary of feedback conversations."""
    try:
        service = FeedbackService()
        return service.get_feedback_summary(db=db, weeks=weeks)
    except Exception as e:
        logger.error(f"Feedback summary error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate feedback summary",
        )
```

Add to `src/api/main.py` - import and register:

```python
from src.api.routes import feedback
```

```python
app.include_router(feedback.router)
```

### Step 4: Run test to verify it passes

```bash
python -m pytest tests/unit/test_feedback_routes.py -v
```

Expected: All tests PASS

### Step 5: Commit

```bash
git add src/api/routes/feedback.py src/api/main.py tests/unit/test_feedback_routes.py
git commit -m "feat: add feedback router with chat, submit, survey, and report endpoints"
```

---

## Task 6: Frontend API Methods

**Files:**
- Modify: `frontend/src/services/api.ts`

### Step 1: Add API methods

Add these methods to the `api` object in `frontend/src/services/api.ts`:

```typescript
  // --- Feedback ---

  async feedbackChat(messages: Array<{ role: string; content: string }>): Promise<{ content: string; summary_ready: boolean }> {
    const response = await fetch(`${API_BASE_URL}/api/feedback/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(response.status, error.detail || 'Failed to send feedback message');
    }

    return response.json();
  },

  async submitFeedback(data: {
    category: string;
    summary: string;
    severity: string;
    raw_conversation: Array<{ role: string; content: string }>;
  }): Promise<{ id: number; message: string }> {
    const response = await fetch(`${API_BASE_URL}/api/feedback/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(response.status, error.detail || 'Failed to submit feedback');
    }

    return response.json();
  },

  async submitSurvey(data: {
    star_rating: number;
    time_saved_minutes?: number;
    nps_score?: number;
  }): Promise<{ id: number; message: string }> {
    const response = await fetch(`${API_BASE_URL}/api/feedback/survey`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(response.status, error.detail || 'Failed to submit survey');
    }

    return response.json();
  },
```

This task doesn't have a separate unit test since the API methods are thin wrappers around `fetch` - they will be tested via the Playwright integration tests in Tasks 9 and 10.

### Step 2: Commit

```bash
git add frontend/src/services/api.ts
git commit -m "feat: add feedback API methods (feedbackChat, submitFeedback, submitSurvey)"
```

---

## Task 7: Star Rating, NPS Scale, and Time Saved Components

**Files:**
- Create: `frontend/src/components/Feedback/StarRating.tsx`
- Create: `frontend/src/components/Feedback/NPSScale.tsx`
- Create: `frontend/src/components/Feedback/TimeSavedPills.tsx`

These are presentational sub-components used by the SurveyModal.

### Step 1: Create StarRating

Create `frontend/src/components/Feedback/StarRating.tsx`:

```tsx
/**
 * Star rating component (1-5 stars).
 * Stars fill on hover and click. Selected state is controlled by parent.
 */
import React, { useState } from 'react';

interface StarRatingProps {
  value: number | null;
  onChange: (rating: number) => void;
}

export const StarRating: React.FC<StarRatingProps> = ({ value, onChange }) => {
  const [hoverValue, setHoverValue] = useState<number | null>(null);

  const displayValue = hoverValue ?? value ?? 0;

  return (
    <div className="flex gap-1" data-testid="star-rating">
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          className="text-3xl transition-colors focus:outline-none"
          onMouseEnter={() => setHoverValue(star)}
          onMouseLeave={() => setHoverValue(null)}
          onClick={() => onChange(star)}
          data-testid={`star-${star}`}
          aria-label={`Rate ${star} out of 5`}
        >
          <span className={displayValue >= star ? 'text-yellow-400' : 'text-gray-300'}>
            ★
          </span>
        </button>
      ))}
    </div>
  );
};
```

### Step 2: Create NPSScale

Create `frontend/src/components/Feedback/NPSScale.tsx`:

```tsx
/**
 * NPS (Net Promoter Score) scale component (0-10).
 * Displays a row of numbered buttons with endpoint labels.
 */
import React from 'react';

interface NPSScaleProps {
  value: number | null;
  onChange: (score: number) => void;
}

export const NPSScale: React.FC<NPSScaleProps> = ({ value, onChange }) => {
  return (
    <div data-testid="nps-scale">
      <div className="flex gap-1">
        {Array.from({ length: 11 }, (_, i) => i).map((score) => (
          <button
            key={score}
            type="button"
            className={`w-9 h-9 rounded text-sm font-medium transition-colors focus:outline-none ${
              value === score
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
            onClick={() => onChange(score)}
            data-testid={`nps-${score}`}
            aria-label={`Score ${score} out of 10`}
          >
            {score}
          </button>
        ))}
      </div>
      <div className="flex justify-between mt-1 text-xs text-gray-500">
        <span>Not likely</span>
        <span>Very likely</span>
      </div>
    </div>
  );
};
```

### Step 3: Create TimeSavedPills

Create `frontend/src/components/Feedback/TimeSavedPills.tsx`:

```tsx
/**
 * Time saved pill button selector.
 * Single-select pills representing preset time values.
 */
import React from 'react';

const TIME_OPTIONS = [
  { label: '15 min', value: 15 },
  { label: '30 min', value: 30 },
  { label: '1 hr', value: 60 },
  { label: '2 hrs', value: 120 },
  { label: '4 hrs', value: 240 },
  { label: '8 hrs', value: 480 },
];

interface TimeSavedPillsProps {
  value: number | null;
  onChange: (minutes: number) => void;
}

export const TimeSavedPills: React.FC<TimeSavedPillsProps> = ({ value, onChange }) => {
  return (
    <div className="flex flex-wrap gap-2" data-testid="time-saved-pills">
      {TIME_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`px-4 py-2 rounded-full text-sm font-medium transition-colors focus:outline-none ${
            value === option.value
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
          onClick={() => onChange(option.value)}
          data-testid={`time-${option.value}`}
          aria-label={`${option.label} saved`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
};
```

### Step 4: Commit

```bash
git add frontend/src/components/Feedback/StarRating.tsx frontend/src/components/Feedback/NPSScale.tsx frontend/src/components/Feedback/TimeSavedPills.tsx
git commit -m "feat: add StarRating, NPSScale, and TimeSavedPills components"
```

---

## Task 8: Survey Modal

**Files:**
- Create: `frontend/src/components/Feedback/SurveyModal.tsx`
- Test: `frontend/tests/survey-modal.spec.ts`

### Step 1: Write the failing test

Create `frontend/tests/survey-modal.spec.ts`:

```typescript
import { test, expect, Page } from '@playwright/test';

/**
 * Set up minimal mocks for survey modal tests.
 */
async function setupMocks(page: Page) {
  // Mock the survey submission endpoint
  await page.route('http://127.0.0.1:8000/api/feedback/survey', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 1, message: 'Survey response submitted successfully' }),
    });
  });
}

test.describe('Survey Modal', () => {
  test('displays three survey sections', async ({ page }) => {
    await setupMocks(page);
    // Navigate to a page where survey could appear - will flesh out with trigger
    await page.goto('http://127.0.0.1:3000/help');

    // Programmatically trigger the survey modal for testing
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('test-show-survey'));
    });

    // Check for the three sections
    await expect(page.getByTestId('star-rating')).toBeVisible();
    await expect(page.getByTestId('time-saved-pills')).toBeVisible();
    await expect(page.getByTestId('nps-scale')).toBeVisible();
  });

  test('submit button disabled until star rating selected', async ({ page }) => {
    await setupMocks(page);
    await page.goto('http://127.0.0.1:3000/help');

    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('test-show-survey'));
    });

    // Submit should be disabled
    const submitBtn = page.getByTestId('survey-submit');
    await expect(submitBtn).toBeDisabled();

    // Click a star
    await page.getByTestId('star-3').click();

    // Submit should be enabled
    await expect(submitBtn).toBeEnabled();
  });

  test('closing modal dismisses it', async ({ page }) => {
    await setupMocks(page);
    await page.goto('http://127.0.0.1:3000/help');

    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('test-show-survey'));
    });

    await expect(page.getByTestId('survey-modal')).toBeVisible();

    // Close
    await page.getByTestId('survey-close').click();

    await expect(page.getByTestId('survey-modal')).not.toBeVisible();
  });
});
```

### Step 2: Verify test fails (no survey modal exists yet)

```bash
cd frontend && npx playwright test survey-modal.spec.ts
```

Expected: FAIL (survey modal elements not found)

### Step 3: Write minimal implementation

Create `frontend/src/components/Feedback/SurveyModal.tsx`:

```tsx
/**
 * Satisfaction survey modal.
 *
 * Collects: star rating (1-5), time saved (pill buttons), NPS (0-10).
 * Appears 60s after a generation, at most once per 7 days.
 */
import React, { useState } from 'react';
import { FiX } from 'react-icons/fi';
import { StarRating } from './StarRating';
import { TimeSavedPills } from './TimeSavedPills';
import { NPSScale } from './NPSScale';
import { api } from '../../services/api';

interface SurveyModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SurveyModal: React.FC<SurveyModalProps> = ({ isOpen, onClose }) => {
  const [starRating, setStarRating] = useState<number | null>(null);
  const [timeSaved, setTimeSaved] = useState<number | null>(null);
  const [npsScore, setNpsScore] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async () => {
    if (!starRating) return;

    setSubmitting(true);
    try {
      await api.submitSurvey({
        star_rating: starRating,
        time_saved_minutes: timeSaved ?? undefined,
        nps_score: npsScore ?? undefined,
      });
      setSubmitted(true);
      setTimeout(onClose, 1500);
    } catch (err) {
      console.error('Failed to submit survey:', err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50"
      data-testid="survey-modal"
    >
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 p-6 relative">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-600"
          data-testid="survey-close"
          aria-label="Close survey"
        >
          <FiX size={20} />
        </button>

        {submitted ? (
          <div className="text-center py-8">
            <p className="text-lg font-medium text-gray-900">Thank you for your feedback!</p>
          </div>
        ) : (
          <>
            <h2 className="text-xl font-semibold text-gray-900 mb-6">
              How&apos;s your experience with tellr?
            </h2>

            {/* Star Rating */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                How would you rate tellr?
              </label>
              <StarRating value={starRating} onChange={setStarRating} />
            </div>

            {/* Time Saved */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                How much time has tellr saved you today?
              </label>
              <TimeSavedPills value={timeSaved} onChange={setTimeSaved} />
            </div>

            {/* NPS */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                How likely are you to recommend tellr to a colleague?
              </label>
              <NPSScale value={npsScore} onChange={setNpsScore} />
            </div>

            {/* Submit */}
            <div className="flex justify-end">
              <button
                onClick={handleSubmit}
                disabled={!starRating || submitting}
                className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                data-testid="survey-submit"
              >
                {submitting ? 'Submitting...' : 'Submit'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
```

### Step 4: Run test to verify it passes

```bash
cd frontend && npx playwright test survey-modal.spec.ts
```

Expected: Tests PASS (after wiring into AppLayout - may need to defer full pass to Task 11)

### Step 5: Commit

```bash
git add frontend/src/components/Feedback/SurveyModal.tsx frontend/tests/survey-modal.spec.ts
git commit -m "feat: add SurveyModal with star rating, time saved, and NPS"
```

---

## Task 9: Feedback Button & Popover

**Files:**
- Create: `frontend/src/components/Feedback/FeedbackButton.tsx`
- Create: `frontend/src/components/Feedback/FeedbackPopover.tsx`
- Test: `frontend/tests/feedback-widget.spec.ts`

### Step 1: Write the failing test

Create `frontend/tests/feedback-widget.spec.ts`:

```typescript
import { test, expect, Page } from '@playwright/test';

async function setupMocks(page: Page) {
  await page.route('http://127.0.0.1:8000/api/feedback/chat', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        content: 'Can you tell me more about that?',
        summary_ready: false,
      }),
    });
  });

  await page.route('http://127.0.0.1:8000/api/feedback/submit', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 1, message: 'Feedback submitted successfully' }),
    });
  });

  // Mock all other required endpoints (profiles, sessions, etc.)
  await page.route('http://127.0.0.1:8000/api/settings/profiles', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ profiles: [], default_profile_id: null }),
    });
  });
}

test.describe('Feedback Widget', () => {
  test('feedback button is visible on page', async ({ page }) => {
    await setupMocks(page);
    await page.goto('http://127.0.0.1:3000/help');

    await expect(page.getByTestId('feedback-button')).toBeVisible();
  });

  test('clicking feedback button opens popover', async ({ page }) => {
    await setupMocks(page);
    await page.goto('http://127.0.0.1:3000/help');

    await page.getByTestId('feedback-button').click();

    await expect(page.getByTestId('feedback-popover')).toBeVisible();
    // Should show the greeting message
    await expect(page.getByText("What's on your mind?")).toBeVisible();
  });

  test('can send a message and receive AI response', async ({ page }) => {
    await setupMocks(page);
    await page.goto('http://127.0.0.1:3000/help');

    await page.getByTestId('feedback-button').click();
    await page.getByTestId('feedback-input').fill('The slides look broken');
    await page.getByTestId('feedback-send').click();

    // Should show the AI response
    await expect(page.getByText('Can you tell me more about that?')).toBeVisible();
  });

  test('closing popover hides it', async ({ page }) => {
    await setupMocks(page);
    await page.goto('http://127.0.0.1:3000/help');

    await page.getByTestId('feedback-button').click();
    await expect(page.getByTestId('feedback-popover')).toBeVisible();

    await page.getByTestId('feedback-popover-close').click();
    await expect(page.getByTestId('feedback-popover')).not.toBeVisible();
  });
});
```

### Step 2: Verify test fails

```bash
cd frontend && npx playwright test feedback-widget.spec.ts
```

Expected: FAIL (feedback elements not found)

### Step 3: Write minimal implementation

Create `frontend/src/components/Feedback/FeedbackButton.tsx`:

```tsx
/**
 * Floating feedback button (bottom-right corner).
 * Toggles the FeedbackPopover open/closed.
 */
import React, { useState } from 'react';
import { FiMessageSquare } from 'react-icons/fi';
import { FeedbackPopover } from './FeedbackPopover';

export const FeedbackButton: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      {/* Popover (rendered above the button) */}
      {isOpen && (
        <FeedbackPopover onClose={() => setIsOpen(false)} />
      )}

      {/* Floating button */}
      <button
        onClick={() => setIsOpen((prev) => !prev)}
        className="fixed bottom-6 right-6 z-[60] w-12 h-12 rounded-full bg-blue-600 text-white shadow-lg hover:bg-blue-700 transition-colors flex items-center justify-center"
        data-testid="feedback-button"
        aria-label="Send feedback"
      >
        <FiMessageSquare size={20} />
      </button>
    </>
  );
};
```

Create `frontend/src/components/Feedback/FeedbackPopover.tsx`:

```tsx
/**
 * Intercom-style feedback chat popover.
 *
 * Anchored above the feedback button in the bottom-right.
 * Contains a mini chat interface for AI-powered feedback collection.
 */
import React, { useState, useRef, useEffect } from 'react';
import { FiX, FiSend } from 'react-icons/fi';
import { api } from '../../services/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface FeedbackPopoverProps {
  onClose: () => void;
}

const GREETING = "What's on your mind? Tell me about your experience with tellr.";

export const FeedbackPopover: React.FC<FeedbackPopoverProps> = ({ onClose }) => {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: GREETING },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [summaryReady, setSummaryReady] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    const userMessage: Message = { role: 'user', content: trimmed };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput('');
    setLoading(true);

    try {
      // Send only user/assistant messages (exclude the initial greeting in conversation history)
      const conversationHistory = newMessages
        .filter((_, i) => i > 0 || newMessages[0].role === 'user')
        .map(({ role, content }) => ({ role, content }));

      const response = await api.feedbackChat(conversationHistory);

      if (response.summary_ready) {
        setSummaryReady(true);
        // Don't show the FEEDBACK_CONFIRMED sentinel
        // The last assistant message before confirmation is the summary
      } else {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: response.content },
        ]);
      }
    } catch (err) {
      console.error('Feedback chat error:', err);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitFeedback = async () => {
    // Parse the last assistant message for the structured summary
    const lastAssistantMsg = [...messages].reverse().find((m) => m.role === 'assistant');
    if (!lastAssistantMsg) return;

    // Extract category, summary, severity from the formatted message
    const categoryMatch = lastAssistantMsg.content.match(/\*\*Category:\*\*\s*(.+)/);
    const issueMatch = lastAssistantMsg.content.match(/\*\*Issue:\*\*\s*(.+)/);
    const severityMatch = lastAssistantMsg.content.match(/\*\*Severity:\*\*\s*(.+)/);
    const detailsMatch = lastAssistantMsg.content.match(/\*\*Details:\*\*\s*(.+)/);

    try {
      await api.submitFeedback({
        category: categoryMatch?.[1]?.trim() || 'Other',
        summary: issueMatch?.[1]?.trim() || lastAssistantMsg.content,
        severity: severityMatch?.[1]?.trim() || 'Medium',
        raw_conversation: messages.map(({ role, content }) => ({ role, content })),
      });
      setSubmitted(true);
      setTimeout(onClose, 2000);
    } catch (err) {
      console.error('Failed to submit feedback:', err);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      className="fixed bottom-20 right-6 z-[60] w-[360px] h-[450px] bg-white rounded-lg shadow-2xl border flex flex-col"
      data-testid="feedback-popover"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b bg-blue-600 rounded-t-lg">
        <h3 className="text-white font-medium">Share Feedback</h3>
        <button
          onClick={onClose}
          className="text-blue-200 hover:text-white"
          data-testid="feedback-popover-close"
          aria-label="Close feedback"
        >
          <FiX size={18} />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {submitted ? (
          <div className="text-center py-8">
            <p className="text-lg font-medium text-gray-900">Thank you for your feedback!</p>
          </div>
        ) : (
          <>
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                    msg.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-800'
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 px-3 py-2 rounded-lg text-sm text-gray-500">
                  Typing...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input / Submit */}
      {!submitted && (
        <div className="border-t p-3">
          {summaryReady ? (
            <button
              onClick={handleSubmitFeedback}
              className="w-full py-2 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-colors"
              data-testid="feedback-submit"
            >
              Submit Feedback
            </button>
          ) : (
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type your feedback..."
                className="flex-1 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                data-testid="feedback-input"
                disabled={loading}
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || loading}
                className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
                data-testid="feedback-send"
                aria-label="Send message"
              >
                <FiSend size={16} />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
```

### Step 4: Run test to verify it passes

```bash
cd frontend && npx playwright test feedback-widget.spec.ts
```

Expected: Tests PASS (after wiring into AppLayout - may need Task 11 first)

### Step 5: Commit

```bash
git add frontend/src/components/Feedback/FeedbackButton.tsx frontend/src/components/Feedback/FeedbackPopover.tsx frontend/tests/feedback-widget.spec.ts
git commit -m "feat: add FeedbackButton and FeedbackPopover components"
```

---

## Task 10: Survey Trigger Hook

**Files:**
- Create: `frontend/src/hooks/useSurveyTrigger.ts`

### Step 1: Write the hook

Create `frontend/src/hooks/useSurveyTrigger.ts`:

```typescript
/**
 * Hook to trigger the satisfaction survey popup.
 *
 * Logic:
 * - After a successful generation, checks localStorage for cooldown (7 days)
 * - If eligible, starts a 60-second timer
 * - If another generation starts during the timer, resets it
 * - After 60s idle, triggers the survey
 * - Writes timestamp to localStorage immediately (dismiss or complete both count)
 */
import { useState, useEffect, useRef, useCallback } from 'react';

const STORAGE_KEY = 'tellr_survey_last_shown';
const COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
const DELAY_MS = 60 * 1000; // 60 seconds

export const useSurveyTrigger = () => {
  const [showSurvey, setShowSurvey] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const isEligible = useCallback((): boolean => {
    const lastShown = localStorage.getItem(STORAGE_KEY);
    if (!lastShown) return true;

    const elapsed = Date.now() - parseInt(lastShown, 10);
    return elapsed >= COOLDOWN_MS;
  }, []);

  const markShown = useCallback(() => {
    localStorage.setItem(STORAGE_KEY, Date.now().toString());
  }, []);

  /**
   * Call this when a generation completes successfully.
   * Starts or resets the 60-second timer.
   */
  const onGenerationComplete = useCallback(() => {
    if (!isEligible()) return;

    // Reset timer if already running (new generation during countdown)
    clearTimer();

    timerRef.current = setTimeout(() => {
      markShown();
      setShowSurvey(true);
    }, DELAY_MS);
  }, [isEligible, clearTimer, markShown]);

  /**
   * Call this when a new generation starts.
   * Resets the timer to avoid interrupting active work.
   */
  const onGenerationStart = useCallback(() => {
    clearTimer();
  }, [clearTimer]);

  const closeSurvey = useCallback(() => {
    setShowSurvey(false);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => clearTimer();
  }, [clearTimer]);

  return {
    showSurvey,
    closeSurvey,
    onGenerationComplete,
    onGenerationStart,
  };
};
```

### Step 2: Commit

```bash
git add frontend/src/hooks/useSurveyTrigger.ts
git commit -m "feat: add useSurveyTrigger hook with 60s delay and 7-day cooldown"
```

---

## Task 11: Wire Into AppLayout

**Files:**
- Modify: `frontend/src/components/Layout/AppLayout.tsx`

### Step 1: Integrate components

In `frontend/src/components/Layout/AppLayout.tsx`:

**Add imports at the top:**

```typescript
import { FeedbackButton } from '../Feedback/FeedbackButton';
import { SurveyModal } from '../Feedback/SurveyModal';
import { useSurveyTrigger } from '../../hooks/useSurveyTrigger';
```

**Add the hook call** inside the `AppLayout` component function:

```typescript
const { showSurvey, closeSurvey, onGenerationComplete, onGenerationStart } = useSurveyTrigger();
```

**Wire `onGenerationComplete`** into the existing `onSlidesGenerated` callback (or equivalent). Find where generation completes and add:

```typescript
onGenerationComplete();
```

**Wire `onGenerationStart`** into the existing generation start handler. Find where generation starts and add:

```typescript
onGenerationStart();
```

**Add components to the JSX** at the bottom of the return, alongside the existing modals:

```tsx
{/* Feedback Widget */}
<FeedbackButton />

{/* Satisfaction Survey */}
<SurveyModal isOpen={showSurvey} onClose={closeSurvey} />
```

Also add a test event listener for the survey (so Playwright tests can trigger it):

```typescript
useEffect(() => {
  const handler = () => setShowSurveyOverride(true);
  window.addEventListener('test-show-survey', handler);
  return () => window.removeEventListener('test-show-survey', handler);
}, []);
```

(Use a separate `showSurveyOverride` state that ORs with `showSurvey` from the hook, only needed for testing.)

### Step 2: Run all frontend tests to verify

```bash
cd frontend && npx playwright test
```

Expected: All existing tests still pass, new feedback/survey tests pass.

### Step 3: Run all backend tests to verify

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
python -m pytest tests/ -v
```

Expected: All tests pass.

### Step 4: Commit

```bash
git add frontend/src/components/Layout/AppLayout.tsx
git commit -m "feat: wire FeedbackButton and SurveyModal into AppLayout"
```

---

## Summary

| Task | Description | New Files | Modified Files |
|------|-------------|-----------|----------------|
| 1 | Database models | `src/database/models/feedback.py`, test | `src/database/models/__init__.py` |
| 2 | Pydantic schemas | `src/api/schemas/feedback.py`, test | |
| 3 | Feedback service (chat/submit/survey) | `src/api/services/feedback_service.py`, test | |
| 4 | Feedback service (reports) | test | `src/api/services/feedback_service.py` |
| 5 | Feedback router | `src/api/routes/feedback.py`, test | `src/api/main.py` |
| 6 | Frontend API methods | | `frontend/src/services/api.ts` |
| 7 | UI sub-components | `StarRating.tsx`, `NPSScale.tsx`, `TimeSavedPills.tsx` | |
| 8 | Survey modal | `SurveyModal.tsx`, test | |
| 9 | Feedback button + popover | `FeedbackButton.tsx`, `FeedbackPopover.tsx`, test | |
| 10 | Survey trigger hook | `useSurveyTrigger.ts` | |
| 11 | Wire into AppLayout | | `AppLayout.tsx` |
