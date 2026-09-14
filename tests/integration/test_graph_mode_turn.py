"""ws4d D2 — a graph-mode turn driven through `send_message_streaming`.

What this suite adds over `test_graph_orchestration.py`
------------------------------------------------------
That suite drives `graph.invoke()` directly and pins the TOPOLOGY.  Everything
here goes in through the shipped chat entry point:

    ChatService.send_message_streaming(..., engine_mode="graph")

so it covers the join ws4c could not: the branch, the worker thread, the context
copy that carries the user's identity across it, the emitter queue the caller
creates, the COMPLETE event, and title generation.  `invoke_graph` itself is the
REAL one — only `get_graph()` is redirected onto the fixture's compiled graph
(built over a file-backed SQLite database with a real checkpointer), so the
turn_id minting, the `set_event_emitter` call and the `initiated_by` resolution
that make this path work are all exercised rather than stubbed.

The monolith is BOOBY-TRAPPED, not merely unasserted
----------------------------------------------------
`ChatService._build_agent_for_session` is patched to raise in every graph test.
The graph branch sits above it in `send_message_streaming`, so if the branch
were ever placed too late — or skipped — the turn dies loudly instead of
quietly running the wrong engine.  It is the earliest monolith-only step and it
is what a monolith turn cannot avoid; `generate_slides_streaming` (a METHOD on
`SlideGeneratorAgent`, never a module function) sits behind it and is never
reached in this environment because building an agent needs a workspace.

Two things deliberately NOT asserted here
-----------------------------------------
`slide_ready`, `slides_since_cursor` and `poll_chat` are Task 3's.  This suite
asserts that events LEAVE the graph before the turn ends (which is what the
thread buys), never a slide-specific event type.

The session's stored TITLE is not asserted, only the emitted `SESSION_TITLE`
event and the naming call, because two writers race for `UserSession.title` on a
graph turn — see `test_a_graph_mode_session_is_titled_on_turn_one`.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.chat_service import ChatService
from src.database.models.session import SessionSlide, SessionSlideDeck
from tests.integration.conftest_stub_skills import builder_html

AUTHOR = "graph-caller@example.com"
SEEDED_AUTHOR = "someone-who-came-before@example.com"
MESSAGE = "USE AGENT MODE build me a deck about puffins"
GENERATED_TITLE = "Puffins Of The North Atlantic"


class _MonolithReached(AssertionError):
    """Raised if a graph-mode turn ever reaches the monolith's agent build."""


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


class _GraphChatEnv:
    """`graph_turn_env` plus the shipped chat entry point on top of it.

    Surface:
      session_id      — the session (and the checkpointer's thread_id)
      recorder        — the SkillRecorder every test parametrises
      service         — a real ChatService
      titles          — messages `generate_session_title` was called with
      run(...)        — drive one turn, return the list of StreamEvents
      run_timed(...)  — as run(), plus the monotonic arrival time of each event
      rows()/deck_row()/seed_rows() — read/write the database directly
    """

    def __init__(self, env, service: ChatService, titles: List[str]):
        self._env = env
        self.service = service
        self.titles = titles

    # -- identity -----------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._env.session_id

    @property
    def recorder(self):
        return self._env.recorder

    @property
    def graph(self):
        return self._env.graph

    # -- driving ------------------------------------------------------------

    def _stream(self, *, engine_mode: str, is_first_message: bool):
        kwargs: Dict[str, Any] = {"session_id": self.session_id, "message": MESSAGE}
        if engine_mode is not None:
            kwargs["engine_mode"] = engine_mode
        kwargs["is_first_message_override"] = is_first_message
        return self.service.send_message_streaming(**kwargs)

    def run(
        self,
        *,
        engine_mode: Optional[str] = "graph",
        is_first_message: bool = True,
    ) -> List[StreamEvent]:
        return list(
            self._stream(engine_mode=engine_mode, is_first_message=is_first_message)
        )

    def run_timed(
        self,
        *,
        engine_mode: Optional[str] = "graph",
        is_first_message: bool = False,
    ) -> List[tuple]:
        """[(monotonic_arrival_time, event), ...] — one entry per yield.

        The time is taken by the CONSUMER as each event is pulled, which is the
        only place "arrived before the turn finished" is observable.
        """
        out: List[tuple] = []
        for event in self._stream(
            engine_mode=engine_mode, is_first_message=is_first_message
        ):
            out.append((time.monotonic(), event))
        return out

    # -- reading ------------------------------------------------------------

    def rows(self) -> List[SessionSlide]:
        return self._env.rows()

    def rows_by_position(self) -> Dict[int, SessionSlide]:
        return self._env.rows_by_position()

    def deck_row(self) -> Optional[SessionSlideDeck]:
        return self._env.deck_row()

    def deck_version(self) -> Optional[int]:
        deck = self.deck_row()
        return None if deck is None else deck.version

    # -- writing ------------------------------------------------------------

    def seed_deck_row(self) -> None:
        """Create the SessionSlideDeck row at version 1, with no slides.

        `graph_turn_env` creates only the UserSession, so without this the
        architect's write CREATES the deck row (version 1, no bump) and only the
        deck reviewer's write bumps it.  Both shapes are pinned — see
        `TestTwoDeckLevelWritesPerTurn`.
        """
        from src.database.models.session import UserSession

        db = self._env.factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == self.session_id)
                .one()
            )
            db.add(
                SessionSlideDeck(
                    session_id=owner.id,
                    title="Seeded Deck",
                    html_content="",
                    scripts_content=None,
                    slide_count=0,
                    version=1,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def seed_rows(self, positions: List[int], author: str = SEEDED_AUTHOR) -> None:
        """Insert committed slide rows authored by *author*, plus the deck row.

        Used by the UPDATE-vs-INSERT author discrimination: a graph write over
        one of these rows takes `_upsert_slide_row`'s partial UPDATE path, which
        PRESERVES an existing author when `modified_by` is None.
        """
        import uuid
        from datetime import datetime

        from src.database.models.session import UserSession

        self.seed_deck_row()
        db = self._env.factory()
        try:
            owner = (
                db.query(UserSession)
                .filter(UserSession.session_id == self.session_id)
                .one()
            )
            for position in positions:
                db.add(
                    SessionSlide(
                        session_id=owner.id,
                        position=position,
                        id=str(uuid.uuid4()),
                        slide_id=str(uuid.uuid4()),
                        html=f"<div class='slide'><p>seeded {position}</p></div>",
                        scripts="",
                        created_by=author,
                        created_at=datetime.utcnow(),
                        modified_by=author,
                        modified_at=datetime.utcnow(),
                    )
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


@pytest.fixture
def graph_chat_env(graph_turn_env, monkeypatch):
    """The compiled graph reached through the real `send_message_streaming`.

    What is redirected, and why each one has to be:

      `src.services.graph.builder.get_graph`
          `invoke_graph` runs for real; only the graph it fetches is the
          fixture's, so the turn uses a file-backed SQLite database and a real
          checkpointer instead of the production one.

      `src.core.database.get_db_session`
          `chat_service` imports it LAZILY inside several methods, so the module
          holds no own reference; the source attribute is the reachable target.
          Without it `resolve_active_design_system_id` and the image
          substitution would reach the operator's real database (`.env` leaks
          into test runs through `load_dotenv`).

      `src.core.settings_db.get_settings`
          `send_message_streaming` loads settings before anything else runs.

      the naming model
          `run_title_gen` builds a `ChatDatabricks` against a live workspace
          client.  `generate_session_title` is replaced by a recorder so the
          title path is exercised end to end without a model call.

      `ChatService._build_agent_for_session`
          the booby trap: raises if a graph turn ever reaches the monolith.
    """
    import contextlib

    from src.core.user_context import set_current_user

    env = graph_turn_env

    monkeypatch.setattr(
        "src.services.graph.builder.get_graph", lambda: env.graph
    )

    @contextlib.contextmanager
    def fake_get_db_session():
        db = env.factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr("src.core.database.get_db_session", fake_get_db_session)
    monkeypatch.setattr(
        "src.core.settings_db.get_settings", lambda: MagicMock(profile_id=None)
    )

    titles: List[str] = []

    def fake_generate_session_title(message, model):
        titles.append(message)
        return GENERATED_TITLE

    monkeypatch.setattr(
        "src.api.services.chat_service.generate_session_title",
        fake_generate_session_title,
    )
    monkeypatch.setattr(
        "src.core.databricks_client.get_user_client", lambda: MagicMock()
    )
    monkeypatch.setattr("databricks_langchain.ChatDatabricks", MagicMock())

    def explode(*args, **kwargs):
        raise _MonolithReached(
            "a graph-mode turn reached _build_agent_for_session: the graph "
            "branch is placed too late, or was not taken at all"
        )

    monkeypatch.setattr(ChatService, "_build_agent_for_session", explode)

    set_current_user(AUTHOR)
    try:
        yield _GraphChatEnv(env, ChatService(), titles)
    finally:
        set_current_user(None)


def _pin_the_design_contract(env, monkeypatch, *, ds_id=7, template_id=11):
    """Make the architect commit a PINNED spec, with brand bytes stubbed.

    Needed by exactly one assertion: the deck's `css` column.  On an UNPINNED
    deck `_resolve_brand` returns empty `token_css` and no style block, so
    `deterministic_css` is falsy, the architect deliberately OMITS `css` (passing
    `""` would ERASE an existing deck's stylesheet) and `aggregate_deck_css`
    returns `""`.  A non-empty `css` is therefore only reachable with a design
    system pinned, which is why this is a helper and not the default fixture.

    `resolve_style_source` is patched at its SOURCE module because
    `_resolve_brand` imports it inside the function body; `resolve_template_bytes`
    is patched on `graph.nodes`, where it is a module-level name.
    """
    from src.domain.deck_spec import DeckSpec
    from src.domain.skill_io import ArchitectOutput
    from src.services.agent_resolution import ResolvedStyle

    token_css = ":root { --brand-ws4d: #123456; }"
    style_block = ".slide { color: #123456; }"
    layout_html = (
        "<main class='deck'><section class='slide'><h1>A</h1></section></main>"
    )

    monkeypatch.setattr(
        "src.services.agent_resolution.resolve_style_source",
        lambda config: ResolvedStyle(
            slide_style="STUB STYLE PROSE",
            design_system_active=True,
            design_system_compiled=None,
            template_pinned=True,
            image_guidelines=None,
        ),
    )
    monkeypatch.setattr(
        "src.services.graph.nodes.resolve_template_bytes",
        lambda design_system_id, tpl_id: (layout_html, style_block, token_css),
    )

    recorder = env.recorder

    def call_skill_with_a_pinned_spec(name, payload, design_system_active):
        out = recorder(name, payload, design_system_active)
        if name == "architect" and getattr(out, "deck_spec", None) is not None:
            spec = DeckSpec.model_validate(
                {
                    **out.deck_spec.model_dump(),
                    "design_contract": {
                        "design_system_id": ds_id,
                        "template_id": template_id,
                        "slide_style_id": None,
                    },
                }
            )
            out = ArchitectOutput.model_validate(
                {**out.model_dump(), "deck_spec": spec.model_dump()}
            )
        return out

    monkeypatch.setattr(
        "src.services.graph.nodes.call_skill", call_skill_with_a_pinned_spec
    )
    return token_css


def _types(events: List[StreamEvent]) -> List[StreamEventType]:
    return [event.type for event in events]


# ---------------------------------------------------------------------------
# Rows and the eight deck-level columns
# ---------------------------------------------------------------------------


class TestAGraphModeTurnWritesTheDeck:
    """The turn produces a deck through the chat entry point, not just state."""

    def test_rows_are_written_at_every_declared_position(self, graph_chat_env):
        graph_chat_env.recorder.configure(slide_count=3)

        graph_chat_env.run()

        rows = graph_chat_env.rows()
        assert [row.position for row in rows] == [0, 1, 2]
        assert [row.html for row in rows] == [builder_html(p) for p in (0, 1, 2)]

    def test_the_deck_level_columns_are_all_written(self, graph_chat_env):
        """Seven of the eight, read back off the row.

        `css` is the eighth and needs a pinned design system to be non-empty —
        `test_css_is_written_on_a_pinned_deck` covers it.  `slide_count` is
        asserted against the ROW COUNT rather than against 3, because the F1a
        defect this pins was "rows committed, slide_count = 0".
        """
        graph_chat_env.recorder.configure(slide_count=3)

        graph_chat_env.run()

        deck = graph_chat_env.deck_row()
        assert deck is not None, "no deck row was created at all"
        assert deck.slide_count == len(graph_chat_env.rows())
        assert deck.title, "title"
        assert deck.deck_spec_json, "deck_spec"
        assert deck.html_content, "html_content"
        assert deck.scripts_content is not None, "scripts_content"
        assert deck.head_meta_json, "head_meta"
        assert deck.external_scripts_json, (
            "external_scripts is empty: its absence is SILENT — no exception, "
            "just blank charts in every export"
        )

    def test_external_scripts_carries_the_chart_js_url(self, graph_chat_env):
        """Non-emptiness alone would pass on a `[]`-shaped JSON string."""
        import json

        from src.domain.slide_deck import SlideDeck

        graph_chat_env.recorder.configure(slide_count=2)

        graph_chat_env.run()

        stored = json.loads(graph_chat_env.deck_row().external_scripts_json)
        assert SlideDeck.CHART_JS_URL in stored

    def test_css_is_written_on_a_pinned_deck(self, graph_chat_env, monkeypatch):
        """The §H defect: deck-level `css` left empty on a branded deck."""
        token_css = _pin_the_design_contract(graph_chat_env._env, monkeypatch)
        graph_chat_env.recorder.configure(slide_count=2)

        graph_chat_env.run()

        css = graph_chat_env.deck_row().css
        assert css, "the deck's css column is empty on a pinned deck"
        assert token_css.split("{")[0].strip() in css

    def test_the_users_message_is_what_the_architect_receives(self, graph_chat_env):
        """`architect_message` is the ONLY key this path seeds into the state.

        `GraphState` is exhaustive and drops undeclared keys silently, so a
        misnamed key would leave the architect with `message=None` and still
        build a deck — this is the assertion that catches that.
        """
        graph_chat_env.recorder.configure(slide_count=1)

        graph_chat_env.run()

        architect_calls = graph_chat_env.recorder.calls_for("architect")
        assert len(architect_calls) == 1
        assert architect_calls[0]["payload"]["message"] == MESSAGE


class TestTwoDeckLevelWritesPerTurn:
    """`architect_node` writes, then `deck_reviewer_node` writes. Two, per turn."""

    def test_an_existing_deck_row_is_bumped_twice(self, graph_chat_env):
        graph_chat_env.seed_deck_row()
        assert graph_chat_env.deck_version() == 1
        graph_chat_env.recorder.configure(slide_count=3)

        graph_chat_env.run()

        assert graph_chat_env.deck_version() == 3, (
            "expected two deck-level writes (architect, then deck reviewer), "
            "each bumping the version by one"
        )

    def test_a_brand_new_deck_is_created_then_bumped_once(self, graph_chat_env):
        """Still two WRITES; the first CREATES at version 1 rather than bumping.

        A test asserting `version == initial + 2` on a new session would fail,
        and the difference is the writer's documented create branch — not a
        missing write.
        """
        assert graph_chat_env.deck_row() is None
        graph_chat_env.recorder.configure(slide_count=3)

        graph_chat_env.run()

        assert graph_chat_env.deck_version() == 2


# ---------------------------------------------------------------------------
# Identity across the thread boundary
# ---------------------------------------------------------------------------


class TestTheAuthorSurvivesTheThread:
    """`contextvars` do not cross a bare `threading.Thread`.

    Without `ctx = contextvars.copy_context()` before the spawn,
    `get_current_user()` inside `invoke_graph` returns None, `initiated_by` is
    None, and `SlideWriter.write_slide(modified_by=None)` leaves the author NULL
    — on an INSERT only, with no exception and nothing in the logs.
    """

    def test_a_freshly_inserted_row_carries_the_calling_user(self, graph_chat_env):
        """INSERT: a position not previously present. THE guard for the copy."""
        graph_chat_env.recorder.configure(slide_count=3)

        graph_chat_env.run()

        rows = graph_chat_env.rows()
        assert rows, "no rows were inserted"
        for row in rows:
            assert row.created_by == AUTHOR, f"position {row.position} created_by"
            assert row.modified_by == AUTHOR, f"position {row.position} modified_by"

    def test_the_deck_row_is_stamped_with_the_calling_user(self, graph_chat_env):
        graph_chat_env.recorder.configure(slide_count=2)

        graph_chat_env.run()

        assert graph_chat_env.deck_row().modified_by == AUTHOR

    def test_an_update_never_leaves_a_null_author(self, graph_chat_env):
        """DELIBERATELY the WEAK form, and being weak is this test's job.

        `write_slide`'s partial UPDATE path PRESERVES the existing author when
        `modified_by` is None (final review F8: it used to null it
        unconditionally, so a reviewer rewriting HTML erased the author).  So an
        author guard phrased as "not NULL" and written against an UPDATE stays
        GREEN with the context copy removed — measured, not assumed.

        This test pins that preservation invariant AND stands as the
        discriminator for it: the INSERT test above is the only shape that can
        catch a missing `ctx.run`.  The strong form of the same assertion is
        `test_an_update_stamps_the_calling_user`, which does redden.
        """
        graph_chat_env.seed_rows([0, 1, 2])
        graph_chat_env.recorder.configure(slide_count=3)

        graph_chat_env.run()

        rows = graph_chat_env.rows_by_position()
        assert rows[0].html == builder_html(0), "the row was not rewritten at all"
        for position in (0, 1, 2):
            assert rows[position].modified_by is not None
            assert rows[position].created_by is not None

    def test_an_update_stamps_the_calling_user(self, graph_chat_env):
        """The strong form: the graph's write REPLACES the seeded author.

        `_upsert_slide_row`'s partial branch overwrites `created_by` too
        whenever the caller supplied one — `if created_by: existing.created_by =
        created_by` — so both columns move to the acting user on a rewrite.
        (`slide_repository.write_slide`'s docstring says created_by "is only
        consumed on INSERT"; that comment is stale, reported as a finding.)
        """
        graph_chat_env.seed_rows([0, 1, 2])
        graph_chat_env.recorder.configure(slide_count=3)

        graph_chat_env.run()

        for position, row in graph_chat_env.rows_by_position().items():
            assert row.modified_by == AUTHOR, f"position {position} modified_by"
            assert row.created_by == AUTHOR, f"position {position} created_by"


# ---------------------------------------------------------------------------
# Events leave the graph while the turn is still running
# ---------------------------------------------------------------------------


class TestEventsArriveWhileTheTurnRuns:
    """The thread + queue is the CONTRACT, not an implementation detail.

    A synchronous `invoke_graph(...)` blocks until the graph completes, so
    calling it inline inside the generator means nothing can be yielded until
    the deck is finished.  These assertions compare arrival times against the
    stub builders' own timings, so they fail on a direct call rather than
    merely on a missing event.
    """

    def test_the_architects_message_arrives_before_any_builder_starts(
        self, graph_chat_env
    ):
        env = graph_chat_env
        env.recorder.configure(
            slide_count=3, slow_positions={0, 1, 2}, slow_seconds=0.4
        )

        timed = env.run_timed()

        assistant_times = [
            at for at, event in timed if event.type == StreamEventType.ASSISTANT
        ]
        assert assistant_times, (
            f"no ASSISTANT event was yielded at all; got {_types([e for _, e in timed])}"
        )
        started = env.recorder.builder_started_at
        assert started, "no builder ran, so the timing comparison proves nothing"
        assert min(assistant_times) < min(started.values()), (
            "the first graph event only arrived after the builders had started: "
            "events are not leaving the graph as they happen, which means "
            "invoke_graph is blocking the generator"
        )

    def test_every_event_precedes_the_complete_event(self, graph_chat_env):
        env = graph_chat_env
        env.recorder.configure(
            slide_count=3, slow_positions={0, 1, 2}, slow_seconds=0.4
        )

        timed = env.run_timed()

        complete_at = [
            at for at, event in timed if event.type == StreamEventType.COMPLETE
        ]
        assert len(complete_at) == 1
        ended = env.recorder.builder_ended_at
        assert ended, "no builder ran"
        assert min(
            at for at, event in timed if event.type == StreamEventType.ASSISTANT
        ) < max(ended.values()) < complete_at[0]


class TestTheCompleteEvent:
    """The turn must finish with a COMPLETE, or nothing downstream sees a deck.

    `job_queue.process_chat_request` builds its stored result from the COMPLETE
    event alone; without one, `set_chat_request_result(request_id, None)` is
    what the poll endpoint delivers.
    """

    def test_complete_is_the_last_event_and_carries_the_deck(self, graph_chat_env):
        graph_chat_env.recorder.configure(slide_count=3)

        events = graph_chat_env.run(is_first_message=False)

        assert events[-1].type == StreamEventType.COMPLETE
        assert _types(events).count(StreamEventType.COMPLETE) == 1, (
            "more than one COMPLETE: the graph branch fell through into the "
            "monolith path, which yields a second one"
        )
        slides = events[-1].slides
        assert slides is not None, "COMPLETE carried no deck"
        assert len(slides["slides"]) == 3

    def test_complete_declares_which_engine_ran(self, graph_chat_env):
        graph_chat_env.recorder.configure(slide_count=1)

        events = graph_chat_env.run(is_first_message=False)

        assert events[-1].metadata == {"engine_mode": "graph"}


# ---------------------------------------------------------------------------
# Title generation
# ---------------------------------------------------------------------------


class TestGraphModeSessionsAreTitled:
    """A graph branch that bypasses the monolith bypasses title generation.

    Only the EVENT and the naming call are asserted, not the stored title:
    `architect_node`'s `write_deck_level_columns(title=spec.title)` also writes
    `UserSession.title`, so which of the two lands last is a race.  That race is
    reported as a finding rather than pinned here.
    """

    def test_a_graph_mode_session_is_titled_on_turn_one(self, graph_chat_env):
        graph_chat_env.recorder.configure(slide_count=1)

        events = graph_chat_env.run(is_first_message=True)

        titles = [
            event.session_title
            for event in events
            if event.type == StreamEventType.SESSION_TITLE
        ]
        assert titles == [GENERATED_TITLE]
        assert titles[0], "SESSION_TITLE arrived with an empty title"

    def test_the_naming_model_is_given_the_users_message(self, graph_chat_env):
        graph_chat_env.recorder.configure(slide_count=1)

        graph_chat_env.run(is_first_message=True)

        assert graph_chat_env.titles == [MESSAGE]

    def test_no_title_is_generated_on_a_later_turn(self, graph_chat_env):
        graph_chat_env.recorder.configure(slide_count=1)

        events = graph_chat_env.run(is_first_message=False)

        assert StreamEventType.SESSION_TITLE not in _types(events)
        assert graph_chat_env.titles == []

    def test_a_failing_naming_service_does_not_fail_the_turn(
        self, graph_chat_env, monkeypatch
    ):
        """A naming outage must not stall conversations."""
        def boom(message, model):
            raise RuntimeError("the naming endpoint is down")

        monkeypatch.setattr(
            "src.api.services.chat_service.generate_session_title", boom
        )
        graph_chat_env.recorder.configure(slide_count=2)

        events = graph_chat_env.run(is_first_message=True)

        assert events[-1].type == StreamEventType.COMPLETE
        assert StreamEventType.SESSION_TITLE not in _types(events)
        assert len(graph_chat_env.rows()) == 2


# ---------------------------------------------------------------------------
# The other engine, and the default
# ---------------------------------------------------------------------------


class TestTheMonolithIsUnaffected:
    """A monolith-mode turn still goes to the monolith, and the default is it."""

    def test_a_monolith_mode_turn_reaches_the_monolith(self, graph_chat_env):
        graph_chat_env.recorder.configure(slide_count=1)

        with pytest.raises(_MonolithReached):
            graph_chat_env.run(engine_mode="monolith")

        assert graph_chat_env.recorder.counts("architect") == 0
        assert graph_chat_env.rows() == []

    def test_omitting_the_parameter_reaches_the_monolith(self, graph_chat_env):
        """The default is monolith even though this session's first message
        carries the phrase — `send_message_streaming` must NEVER resolve the
        mode itself.  Resolving it here would put MCP, which drains through the
        same job queue, on the graph.
        """
        graph_chat_env.recorder.configure(slide_count=1)

        with pytest.raises(_MonolithReached):
            graph_chat_env.run(engine_mode=None)

        assert graph_chat_env.recorder.counts("architect") == 0

    def test_an_unknown_mode_string_reaches_the_monolith(self, graph_chat_env):
        """Fail closed: only the exact string `"graph"` selects the graph."""
        graph_chat_env.recorder.configure(slide_count=1)

        with pytest.raises(_MonolithReached):
            graph_chat_env.run(engine_mode="GRAPH")
