"""Prompt parity through the public AgentRuntime seam.

The runtime receives the same scalar ``design_system_active`` fact that the shipped
graph already checkpoints. These tests pin the three style cases and prove that the
deep runtime module—not a graph node or the legacy agent-resolution module—owns
payload serialization and protected prompt assembly.
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE
from src.core.skills import load_skill
from src.services.agent_runtime import (
    AgentAssemblyContext,
    AgentModelConfiguration,
    AgentRuntime,
)
from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS


class PromptCaptureAdapter:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def invoke(
        self,
        *,
        configuration: AgentModelConfiguration,
        schema: type[BaseModel],
        prompt: str,
    ) -> BaseModel:
        self.prompts.append(prompt)
        return schema.model_construct()


def _assembled_prompt(
    agent_key: str,
    payload: dict,
    *,
    design_system_active: bool,
) -> str:
    model = PromptCaptureAdapter()
    result = AgentRuntime.compatibility(model_adapter=model).run(
        agent_key,
        payload,
        AgentAssemblyContext(design_system_active),
    )
    assert result.diagnostics.assembled_prompt == model.prompts[0]
    return model.prompts[0]


@pytest.fixture
def _db_session():
    """Sequential SQLite session for the real style-resolution branches."""
    import src.database.models  # noqa: F401 — register models with Base.metadata
    from src.core.database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _yield_session(session):
    @contextmanager
    def _cm():
        yield session

    return patch("src.core.database.get_db_session", _cm)


class TestAgentRuntimePromptAssembly:
    def test_payload_appears_in_assembled_prompt(self):
        prompt = _assembled_prompt(
            "builder",
            {"section": "introduction", "user_request": "create a title slide"},
            design_system_active=False,
        )

        assert "introduction" in prompt
        assert "create a title slide" in prompt

    def test_reviewer_receives_the_html_it_is_reviewing(self):
        prompt = _assembled_prompt(
            "build_reviewer",
            {"html": "<h1>Sales Results</h1>", "position": 0},
            design_system_active=False,
        )

        assert "Sales Results" in prompt

    def test_frame_constraints_injected_without_design_system(self):
        prompt = _assembled_prompt("builder", {}, design_system_active=False)
        assert _SLIDE_FRAME_CONSTRAINTS in prompt

    def test_frame_constraints_not_duplicated_with_design_system(self):
        prompt = _assembled_prompt("builder", {}, design_system_active=True)
        assert _SLIDE_FRAME_CONSTRAINTS not in prompt

    def test_design_system_precedence_present_only_when_active(self):
        active = _assembled_prompt("architect", {}, design_system_active=True)
        inactive = _assembled_prompt("architect", {}, design_system_active=False)

        assert DESIGN_SYSTEM_PRECEDENCE in active
        assert DESIGN_SYSTEM_PRECEDENCE not in inactive

    def test_all_three_style_cases_reach_the_runtime(self, _db_session):
        from src.api.schemas.agent_config import AgentConfig
        from src.database.models import SlideStyleLibrary
        from src.services.agent_resolution import resolve_style_source

        case1 = _assembled_prompt(
            "build_reviewer",
            {},
            design_system_active=True,
        )

        resolved2 = resolve_style_source(AgentConfig())
        assert resolved2.design_system_active is False
        case2 = _assembled_prompt(
            "build_reviewer",
            {},
            design_system_active=resolved2.design_system_active,
        )

        style = SlideStyleLibrary(
            name="Test Brand Style",
            style_content="BRAND-CSS",
            is_active=True,
        )
        _db_session.add(style)
        _db_session.commit()
        _db_session.refresh(style)
        with _yield_session(_db_session):
            resolved3 = resolve_style_source(AgentConfig(slide_style_id=style.id))

        assert resolved3.design_system_active is False
        case3 = _assembled_prompt(
            "build_reviewer",
            {},
            design_system_active=resolved3.design_system_active,
        )

        assert _SLIDE_FRAME_CONSTRAINTS not in case1
        assert DESIGN_SYSTEM_PRECEDENCE in case1
        for prompt in (case2, case3):
            assert _SLIDE_FRAME_CONSTRAINTS in prompt
            assert DESIGN_SYSTEM_PRECEDENCE not in prompt

    def test_code_owned_instructions_are_preserved_for_every_role(self):
        for agent_key in ("architect", "builder", "fixer"):
            prompt = _assembled_prompt(
                agent_key,
                {},
                design_system_active=False,
            )
            assert load_skill(agent_key).instructions in prompt


class TestSlideFrameConstraintsProvenance:
    def test_runtime_imports_frame_constraints_from_the_compiler(self):
        import src.services.agent_runtime as agent_runtime_module

        source = inspect.getsource(agent_runtime_module)
        assert (
            "from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS"
            in source
        )
