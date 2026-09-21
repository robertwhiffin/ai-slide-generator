"""Shared helpers for the C4 graph suites (nodes, routers, assembly).

Not auto-loaded — imported explicitly, following the ``conftest_design_system``
/ ``conftest_images`` precedent in this directory.

Design choice worth stating: the environment is a **real** SQLite database with
the production schema, not a fake writer.  Row writes, deck-level column writes,
deck-review persistence and chat messages all go through the shipped code, so a
test that asserts "the author is non-NULL" reads it back off a row rather than
asserting a kwarg was passed to a mock — the kwarg-discarded-before-it-reached
anything failure mode this repo has shipped twice.

Only two things are stubbed, and both because they reach a Databricks workspace:
``AgentRuntime`` (the model) and the brand resolvers (``resolve_style_source``,
``resolve_template_bytes``).  Both stubs RECORD their calls, because several
assertions are about whether they were called at all.
"""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, _run_migrations  # imported FIRST: importing
# src.database.models before src.core trips the pre-existing circular import
# (src.core.__init__ -> settings_db -> src.database.models).
import src.database.models  # noqa: E402,F401 — registers every ORM model on Base
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.domain.deck_spec import DeckSpec
from src.domain.finding import Finding, SlideReviewOutput
from src.domain.skill_io import ArchitectOutput, BuilderOutput, FixerOutput

DEFAULT_STYLE = "STUB STYLE PROSE"
TEMPLATE_LAYOUT = (
    "<main class='deck'>"
    "<section class='slide'><h1>Section A</h1></section>"
    "<section class='slide'><h1>Section B</h1></section>"
    "</main>"
)
TEMPLATE_STYLE_BLOCK = ".slide { color: #123456; }"
TEMPLATE_TOKEN_CSS = ":root { --brand: #123456; }"


# ---------------------------------------------------------------------------
# Spec construction
# ---------------------------------------------------------------------------


def make_spec(
    positions=(0, 1, 2),
    *,
    design_system_id: Optional[int] = None,
    template_id: Optional[int] = None,
    slide_style_id: Optional[int] = None,
    template_section_index: Optional[int] = 0,
    title: str = "Stub Deck",
) -> DeckSpec:
    """A valid ``DeckSpec`` over arbitrary (possibly non-contiguous) positions."""
    return DeckSpec(
        title=title,
        audience="Stub audience",
        purpose="Stub purpose",
        argument="Stub argument",
        call_to_action="Stub CTA",
        narrative_arc=["open", "middle", "close"],
        design_contract={
            "design_system_id": design_system_id,
            "template_id": template_id,
            "slide_style_id": slide_style_id,
        },
        resolved_data={"synthesis": "Stub synthesis", "figures": [], "gaps": []},
        slides=[
            {
                "position": p,
                "purpose": f"purpose-{p}",
                "content_brief": f"brief-{p}",
                "assumes": f"assumes-{p}",
                "hands_off": f"hands-off-{p}",
                "data_references": [],
                "template_section_index": template_section_index,
            }
            for p in positions
        ],
    )


def finding(
    criterion: str = "overflow",
    *,
    slide_index: int = 0,
    objective: Optional[bool] = None,
    message: str = "stub finding",
    category: Optional[str] = None,
    status: str = "open",
) -> Finding:
    """A ``Finding`` whose ``objective`` can deliberately disagree with CRITERIA."""
    from src.domain.finding import CRITERIA

    return Finding(
        id="unstamped",
        slide_index=slide_index,
        category=category or CRITERIA[criterion].category,
        criterion=criterion,
        message=message,
        objective=(
            CRITERIA[criterion].objective if objective is None else objective
        ),
        status=status,
    )


# ---------------------------------------------------------------------------
# AgentRuntime stub
# ---------------------------------------------------------------------------


class SkillStub:
    """Stands in for ``AgentRuntime``; records calls and returns per-role values.

    A handler may be a value or a callable taking ``(payload)``.  An unset skill
    name raises, so a node reaching a model this test did not intend to exercise
    fails loudly instead of receiving a MagicMock that satisfies every assertion.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._handlers: Dict[str, Any] = {}

    def set(self, name: str, handler: Any) -> None:
        self._handlers[name] = handler

    def calls_for(self, name: str) -> List[Dict[str, Any]]:
        return [c for c in self.calls if c["name"] == name]

    def run(self, name: str, payload: dict, assembly_context: Any) -> Any:
        design_system_active = assembly_context.design_system_active
        self.calls.append(
            {
                "name": name,
                "payload": payload,
                "design_system_active": design_system_active,
            }
        )
        if name not in self._handlers:
            raise AssertionError(
                f"SkillStub has no handler for {name!r}; this test did not "
                f"expect that skill to be invoked"
            )
        handler = self._handlers[name]
        output = handler(payload) if callable(handler) else handler
        return SimpleNamespace(output=output)


def architect_build(spec: DeckSpec, message: str = "Building your deck.") -> ArchitectOutput:
    return ArchitectOutput(intent="build", message=message, deck_spec=spec)


def builder_out(payload: dict, html: Optional[str] = None, scripts: str = "") -> BuilderOutput:
    position = payload["position"]
    return BuilderOutput(
        position=position,
        html=html if html is not None else f"<div class='slide'>slide {position}</div>",
        scripts=scripts,
    )


def fixer_out(payload: dict, html: Optional[str] = None) -> FixerOutput:
    position = payload["position"]
    return FixerOutput(
        position=position,
        html=html if html is not None else f"<div class='slide'>fixed {position}</div>",
        scripts="",
        changed=True,
        change_summary="stub fix",
    )


def review_out(position: int, findings: Optional[List[Finding]] = None) -> SlideReviewOutput:
    return SlideReviewOutput(
        slide_index=position,
        verdict="surfaced" if findings else "clean",
        findings=list(findings or []),
    )


# ---------------------------------------------------------------------------
# Brand-resolution stubs
# ---------------------------------------------------------------------------


class StyleStub:
    """Stands in for ``resolve_style_source``; records the configs it was given."""

    def __init__(self, design_system_active: bool = False) -> None:
        self.calls: List[Any] = []
        self.design_system_active = design_system_active
        self.slide_style = DEFAULT_STYLE

    def __call__(self, config):
        self.calls.append(config)
        from src.services.agent_resolution import ResolvedStyle

        return ResolvedStyle(
            slide_style=self.slide_style,
            design_system_active=self.design_system_active,
            design_system_compiled=None,
            template_pinned=False,
            image_guidelines=None,
        )


class TemplateStub:
    """Stands in for ``resolve_template_bytes``; records every (ds_id, tpl_id)."""

    def __init__(self) -> None:
        self.calls: List[tuple] = []
        self.layout = TEMPLATE_LAYOUT
        self.style_block = TEMPLATE_STYLE_BLOCK
        self.token_css = TEMPLATE_TOKEN_CSS

    def __call__(self, design_system_id, template_id):
        self.calls.append((design_system_id, template_id))
        return (self.layout, self.style_block, self.token_css)


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


class GraphEnv:
    """A real database plus the two recording stubs, wired into the graph modules."""

    def __init__(self, session_id: str, engine, factory, skills, style, template):
        self.session_id = session_id
        self.engine = engine
        self.factory = factory
        self.skills = skills
        self.style = style
        self.template = template

    # -- state construction -------------------------------------------------

    def state(self, **overrides) -> Dict[str, Any]:
        """A minimal turn state; override any key."""
        base: Dict[str, Any] = {
            "session_id": self.session_id,
            "turn_id": "turn-1",
            "initiated_by": "graph-user@example.com",
        }
        base.update(overrides)
        return base

    # -- row inspection -----------------------------------------------------

    def rows(self) -> List[SessionSlide]:
        db = self.factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == self.session_id)
                .one()
            )
            return (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == owner.id)
                .order_by(SessionSlide.position)
                .all()
            )
        finally:
            db.close()

    def deck_row(self) -> Optional[SessionSlideDeck]:
        db = self.factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == self.session_id)
                .one()
            )
            return (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner.id)
                .first()
            )
        finally:
            db.close()

    def messages(self) -> List[dict]:
        from src.api.services.session_manager import get_session_manager

        return get_session_manager().get_messages(self.session_id)

    def seed_slides(self, htmls: List[Any]) -> None:
        """Insert committed slide rows (and the deck row) directly.

        Each entry is either an HTML string or an ``(html, scripts)`` pair.
        """
        db = self.factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == self.session_id)
                .one()
            )
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner.id)
                .first()
            )
            if deck is None:
                deck = SessionSlideDeck(
                    session_id=owner.id,
                    html_content="",
                    scripts_content=None,
                    slide_count=len(htmls),
                    version=1,
                )
                db.add(deck)
            for position, entry in enumerate(htmls):
                html, scripts = entry if isinstance(entry, tuple) else (entry, "")
                db.add(
                    SessionSlide(
                        session_id=owner.id,
                        position=position,
                        id=str(uuid.uuid4()),
                        slide_id=str(uuid.uuid4()),
                        html=html,
                        scripts=scripts,
                    )
                )
            db.commit()
        finally:
            db.close()


def _fake_db(factory) -> Callable:
    @contextlib.contextmanager
    def _cm():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _cm


def _build_env(monkeypatch, url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)
    factory = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )

    session_id = f"graph-{uuid.uuid4().hex[:10]}"
    db = factory()
    try:
        db.add(UserSession(session_id=session_id, created_by="owner@example.com"))
        db.commit()
    finally:
        db.close()

    fake = _fake_db(factory)
    for target in (
        "src.api.services.slide_repository.get_db_session",
        "src.api.services.session_manager.get_db_session",
        "src.api.services.deck_level_writer.get_db_session",
        "src.services.graph.nodes.get_db_session",
    ):
        monkeypatch.setattr(target, fake)

    # SCIM display-name resolution runs on every get_slide_deck row read. It is
    # not what any C4 test is about, and a real WorkspaceClient here retries SCIM
    # calls and hangs, so it is neutralised rather than measured.
    monkeypatch.setattr(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    )

    skills = SkillStub()
    style = StyleStub()
    template = TemplateStub()
    monkeypatch.setattr("src.services.graph.nodes.get_agent_runtime", lambda: skills)
    monkeypatch.setattr(
        "src.services.agent_resolution.resolve_style_source", style
    )
    monkeypatch.setattr(
        "src.services.graph.nodes.resolve_template_bytes", template
    )

    return GraphEnv(session_id, engine, factory, skills, style, template)


@pytest.fixture
def graph_env(monkeypatch):
    """A real in-memory database, with AgentRuntime and brand resolvers stubbed.

    Single-threaded use only.  A compiled-graph run fans out across threads and
    needs ``graph_env_threadsafe``.
    """
    env = _build_env(monkeypatch, "sqlite:///:memory:")
    yield env
    env.engine.dispose()


@pytest.fixture
def graph_env_threadsafe(monkeypatch, tmp_path):
    """The same environment on a FILE-backed SQLite database.

    A compiled-graph run fans builders out across Pregel worker threads.
    ``sqlite:///:memory:`` gives each thread its own empty database (or, on a
    ``StaticPool``, hands two worker threads one connection and segfaults the
    interpreter — reproduced 3 of 3 runs on ws4b), so a graph run must be
    file-backed.
    """
    env = _build_env(monkeypatch, f"sqlite:///{tmp_path}/graph.db")
    yield env
    env.engine.dispose()
