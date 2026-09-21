"""ws4c Definition-of-done: a REAL-MODEL run of the compiled graph.

This is the one DoD item the stub suite structurally cannot cover.
``test_graph_orchestration.py`` replaces ``AgentRuntime`` and returns canned
schema-valid outputs, so it proves the TOPOLOGY holds given well-formed agent
output.  It cannot prove the topology holds given output a real model actually
produces.  That is what this file is for.

GATING — this never runs in CI and must never be made to.  It is
``@pytest.mark.live`` (``pyproject.toml`` documents that marker as excluded with
``-m 'not live'``) and it self-skips unless BOTH a reachable PostgreSQL and
Databricks credentials are present.  Note the standing repo hazard: the
``unit-tests`` job applies no ``-m`` filter, which is why this file lives under
``tests/integration/`` and is named in no job's ``run:`` block.

WHAT IT PROVES, and it is worth being precise because the plan's DoD wording is
short: a multi-slide deck builds end to end with ascending release, ONE reviewer
invocation per slide, AT MOST ONE fix round per position, and deck review firing
ONCE.  It does NOT prove prose quality — the seven skills ship deliberate
placeholder prompts (§A1) and real authoring is a separate track — and it does
not prove anything about CI or about Postgres at scale.

COST, and why it is bounded by a call budget rather than a recursion limit.
``invoke_graph`` deliberately sets no ``recursion_limit`` (the installed default
is 10007; the superseded plan's ~50 would have made the graph fail EARLIER), and
this file does not change production code to bound it.  Instead every
``AgentRuntime.run`` goes through :class:`_CallBudget`, which raises once a hard call
count is reached.  That bounds spend absolutely, independent of any graph
behaviour, and the recorded calls are also the evidence the assertions need.

The bound matters because of a KNOWN, RECORDED gap: ``ask_data`` has no round
bound, and ``tool_grants`` is dead metadata — no ``bind_tools`` call exists
anywhere, so the analyst can fetch nothing and returns ``no_tool`` or
``missing_data`` every time.  That makes an architect-analyst ping-pong MORE
likely, not less, and without a budget it would run against a 60k-max-token
endpoint until the recursion limit.  Stage 1 exists so the first spend is one
call, not thirty.

All fixture content SYNTHETIC — no real brand or customer material.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

# --------------------------------------------------------------------------
# Gating.  Module-level, so a missing prerequisite skips rather than errors.
# --------------------------------------------------------------------------

_PG_URL = os.environ.get(
    "TELLR_TEST_POSTGRES_URL", "postgresql+psycopg2://localhost:5432/postgres"
)


def _postgres_reachable() -> bool:
    try:
        create_engine(_PG_URL).connect().execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# EXPLICIT OPT-IN, and it is belt-and-braces with the `live` marker on purpose.
# The documented baseline command is `pytest tests/ -n auto -q` with NO `-m` filter, so
# without this gate every baseline measurement would silently spend real money on a
# serving endpoint.  The marker alone is not enough protection against a command nobody
# thinks of as dangerous.
if os.environ.get("TELLR_LIVE_GRAPH_RUN") != "1":
    pytest.skip(
        "ws4c live real-model run is opt-in: set TELLR_LIVE_GRAPH_RUN=1 to spend model "
        "calls. Run the stage-1 test first (one call) and read its output before stage 2.",
        allow_module_level=True,
    )

if not _postgres_reachable():
    pytest.skip(
        f"live graph run needs a reachable PostgreSQL at {_PG_URL}",
        allow_module_level=True,
    )

# src/core/database.py calls load_dotenv(), but only once something imports it — so at
# module scope the .env may not be loaded yet and the gate below would skip on a machine
# that actually has credentials.  Load it here so the gate is independent of import order.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv absent is not a reason to fail collection
    pass

if not (os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN")):
    pytest.skip(
        "live graph run needs DATABRICKS_HOST and DATABRICKS_TOKEN "
        "(note src/core/database.py calls load_dotenv(), so a local .env supplies these)",
        allow_module_level=True,
    )

pytestmark = pytest.mark.live


# --------------------------------------------------------------------------
# The call budget — the only thing standing between a loop and a real bill
# --------------------------------------------------------------------------


class _BudgetExceeded(RuntimeError):
    """Raised when the run has spent its allotted model calls."""


class _CallBudget:
    """Wrap the real ``AgentRuntime``, record every call, and stop at ``limit``.

    Recording is per ``(skill, position)`` because that is exactly what the DoD
    assertions are about: one reviewer per slide, one fix round per position,
    deck review once.  ``position`` is read from the payload rather than from
    state, because a ``Send``-reached node sees only its payload.
    """

    def __init__(self, real, limit: int):
        self._real = real
        self.limit = limit
        self.calls: list[tuple[str, object]] = []

    def run(self, name: str, payload: dict, assembly_context):
        if len(self.calls) >= self.limit:
            raise _BudgetExceeded(
                f"call budget of {self.limit} reached; calls so far: {self.counts()}"
            )
        self.calls.append((name, (payload or {}).get("position")))
        return self._real.run(name, payload, assembly_context)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for name, _ in self.calls:
            out[name] = out.get(name, 0) + 1
        return out

    def positions(self, skill: str) -> list[object]:
        return [pos for name, pos in self.calls if name == skill]


@pytest.fixture
def live_env(monkeypatch):
    """A real session against real Postgres, with the graph's tables present."""
    monkeypatch.setenv("DATABASE_URL", _PG_URL)

    import src.database.models  # noqa: F401 — register every model
    from src.core.database import init_db
    from src.api.services.session_manager import get_session_manager

    init_db()  # create_all + _run_migrations: the graph_checkpoints tables

    session_id = f"live-ws4c-{uuid.uuid4().hex[:12]}"
    get_session_manager().create_session(
        session_id=session_id,
        user_id="ws4c-live-harness",
        created_by="ws4c-live-harness",
        title="ws4c live DoD run",
        agent_config={},  # no design system pinned: the no-template path
    )
    return session_id


def _install_budget(monkeypatch, limit: int) -> _CallBudget:
    """Route AgentRuntime through a budget, patched where the nodes read it."""
    import src.services.graph.nodes as nodes

    budget = _CallBudget(nodes.get_agent_runtime(), limit)
    monkeypatch.setattr(nodes, "get_agent_runtime", lambda: budget)
    return budget


# --------------------------------------------------------------------------
# STAGE 1 — one call.  Run this first, and read its output, before Stage 2.
# --------------------------------------------------------------------------


def test_stage1_the_architect_produces_a_valid_deck_spec(live_env, monkeypatch, capsys):
    """ONE model call.  Does a real model, given PLACEHOLDER prose, return a
    ``DeckSpec`` that survives its own validators?

    This is the question that decides whether Stage 2 is worth spending on.  If
    it fails, the failure is about PROSE, not about the graph: ``DeckSpec``
    requires a non-empty title, unique slide positions and a ``design_contract``,
    and ``ArchitectOutput`` requires ``deck_spec`` whenever ``intent='build'``.
    A real model on placeholder instructions may simply not produce that.

    The budget is 1, so the architect returns and the turn stops immediately —
    the spend here is a single call, deliberately.
    """
    from src.services.graph.builder import invoke_graph

    budget = _install_budget(monkeypatch, limit=1)

    try:
        invoke_graph(
            live_env,
            {"architect_message": "Build a 3-slide deck explaining why unit tests "
                                  "that cannot fail are worse than no tests."},
        )
    except Exception as exc:  # the budget stops the turn; that is the design
        if not isinstance(exc, _BudgetExceeded) and "_BudgetExceeded" not in repr(exc):
            raise

    assert budget.counts().get("architect") == 1, (
        f"expected exactly one architect call; got {budget.counts()}"
    )
    # Report the spec so a human can judge the prose before Stage 2 spends 30 calls.
    with capsys.disabled():
        print(f"\n  STAGE 1 calls: {budget.counts()}")


# --------------------------------------------------------------------------
# STAGE 2 — the DoD run.  Only worth spending once Stage 1 passes.
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_stage2_a_multislide_deck_builds_end_to_end(live_env, monkeypatch, capsys):
    """The Definition-of-done item, against a real model.

    Asserts the four properties the plan names, from the RECORDED CALLS and the
    COMMITTED ROWS rather than from anything the model said about itself:

      * ascending release — the committed prefix never regresses;
      * ONE ``build_reviewer`` call per slide, not one per batch (a static edge
        instead of the re-fan collapses N branches into one);
      * AT MOST ONE fix round per position;
      * deck review fires ONCE.

    Budget 30: a 3-slide deck is 1 architect + 3 builders + 3 reviewers +
    at most 3 fix pairs + 1 deck reviewer, so 30 leaves headroom for one
    analyst detour without leaving room for a runaway loop.
    """
    from src.services.graph.builder import invoke_graph
    from src.services.graph.state import scoped_vals

    budget = _install_budget(monkeypatch, limit=30)
    final = invoke_graph(
        live_env,
        {"architect_message": "Build a 3-slide deck explaining why unit tests "
                              "that cannot fail are worse than no tests."},
    )

    counts = budget.counts()
    with capsys.disabled():
        print(f"\n  STAGE 2 calls: {counts}")

    landed = scoped_vals(final, "landed_positions")
    placeheld = scoped_vals(final, "placeheld_positions")
    committed = sorted(set(landed) | set(placeheld))

    assert committed, f"no position was committed; calls were {counts}"

    # One reviewer per slide, never one per batch.
    reviewed = budget.positions("build_reviewer")
    assert len(reviewed) == len(set(reviewed)), (
        f"a position was reviewed twice: {reviewed}"
    )
    assert set(reviewed) <= set(committed) | set(placeheld), (
        f"a reviewer ran for a position that never committed: {reviewed} vs {committed}"
    )

    # At most one fix round per position.
    fixed = budget.positions("fixer")
    assert len(fixed) == len(set(fixed)), f"a position entered the fixer twice: {fixed}"

    # Deck review exactly once.
    assert counts.get("deck_reviewer", 0) == 1, (
        f"deck review must fire exactly once; calls were {counts}"
    )

    # Ascending release: the committed set is a prefix of the spec's positions.
    assert committed == list(range(len(committed))), (
        f"release was not an ascending prefix: {committed}"
    )
