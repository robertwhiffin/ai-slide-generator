"""#271 Task 6: the staged edit-to-rollback lifecycle journey (AC7, AC1 tripwire).

A helper module, not a test module (no ``test_`` prefix), so importing it collects
nothing.  ``test_graph_lifecycle_acceptance_postgres.py`` runs the whole journey;
Task 7 reuses it through ``run_to("S16")`` and Task 8 through ``run_to("S12")``.

What it is for
--------------
One Graph Configuration lifecycle, driven end to end through the SHIPPED routers
over a real PostgreSQL database: bootstrap, an old conversation, prompt/model
edits, a schema overlay, an assembly upgrade, an endpoint change, candidate test
runs, verdicts, readiness, preview, publish, pinned conversations, collaboration
history, release history, rollback and post-rollback pins.  Every stage asserts
an exact identity, key set or status, never a count alone.

Attribution
-----------
Each stage runs inside ``stage(S)``; any exception becomes a ``StageFailure``
labelled ``[<ticket>] <code> <name> via <seam>``, so a red run names the ticket
whose seam broke.  Each stage OPENS by ``require``-ing the exact output of the
stage it consumes; ``require`` labels its failure with the UPSTREAM stage, so a
wrong value is blamed on the stage that produced it.  A read of a code-owned
definition source after bootstrap (``CodeDefaultTripwire``) is labelled
``[AC1/#271]`` even when production code swallows the error.

The seam (C37/C50)
------------------
It extends #270's ``acceptance_stack`` (``test_graph_release_rollback_acceptance
_postgres.py``), importing it rather than copying it: the one admin router on
PostgreSQL, the fake-adapter workbench as the only ``get_agent_test_workbench``
override.  To it this module adds, and nothing else:

* the sessions router, on the same app (``client.app.include_router``);
* ``get_model_endpoint_catalog`` -> a ``FakeModelEndpointCatalog`` listing the two
  fake endpoint names (the discovery route's workspace client);
* ``SessionManager`` writes through the throwaway database (#270's
  ``_session_manager_on``), and ``src.core.database.get_db_session`` bound to the
  same session factory for the sessions routes' lazy imports (C50);
* the admin probe true only for the admin principal (C2), and the principal set
  per request, not per client (C2), for three principals: the admin, the
  conversation owner and a non-admin contributor with a ``CAN_VIEW`` grant;
* the deck-open usage event is a no-op (a best-effort background write to the
  conftest database, not part of any contract here).

Non-HTTP steps (each named at its site): pin and closing reads (S02, S11, S12,
S16, S18); the seeded ``old-root`` deck, agent-mode marker message and contributor
grant (C2); the two shared-deck mutations of S12b (C9, through
``SessionManager.save_slide_deck``); and the burned ``graph_release`` id before
the publish, so ids and version numbers diverge (v1 = id 1, id 2 burned,
v2 = id 3, v3 = id 4).
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
import sys
import types
import typing
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from src.api.routes import _authz
from src.api.routes import agent_definitions as agent_definition_routes
from src.api.routes import sessions as sessions_routes
from src.core.permission_context import PermissionContext, set_permission_context
from src.core.user_context import set_current_user
from src.database.models.deck_contributor import DeckContributor
from src.database.models.graph_configuration import GraphDraftAgent, GraphRelease
from src.database.models.session import UserSession
from src.domain.conversation_engine import AGENT_MODE_PHRASE
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.model_endpoint_catalog import (
    FakeModelEndpointCatalog,
    SystemModelDiscovery,
    SystemModelEndpoint,
)
from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter
from tests.fixtures.log_records import STANDARD_LOG_RECORD_ATTRS
from tests.integration.test_graph_release_publication_acceptance_postgres import (
    _mapping_rows,
    _pin_of,
    _release_ids,
)
from tests.integration.test_graph_release_rollback_acceptance_postgres import (
    _session_manager_on,
    acceptance_stack,
)

__all__ = [
    "ADMIN",
    "CONTRIBUTOR",
    "OWNER",
    "STAGES",
    "CodeDefaultRead",
    "CodeDefaultTripwire",
    "LifecycleJourney",
    "RecordedExchange",
    "Stage",
    "StageFailure",
    "acceptance_stack",
    "lifecycle_journey",
    "open_journey",
    "require",
    "stage",
]

ADMIN_PREFIX = "/api/admin/agent-definitions"
ADMIN = "lifecycle-admin@example.com"
OWNER = "lifecycle-owner@example.com"
CONTRIBUTOR = "contributor@example.com"

OPUS = "databricks-claude-opus-4-6"
SONNET = "system.ai.claude-sonnet-4-5"

#: #264's v2 builder schema contract and #265's v2 architect protected assembly,
#: as literals: a registry that silently re-derived either would change them.
BUILDER_SCHEMA_CONTRACT_V2_DIGEST = (
    "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad"
)
ARCHITECT_PROTECTED_ASSEMBLY_V2_DIGEST = (
    "fb651a0d28276a0daf7b0db09f2648eb6b50d9429a7100cfaf69e3fc2b08592a"
)
#: ``GraphConfiguration.bootstrap_v1``'s default actor: v1's ``published_by``.
BOOTSTRAP_ACTOR = "system:bootstrap"
CUSTOM_BLOCK_ID = "7c1f0a52-2b7e-4d7e-9a51-6f1d7e0c2b71"
CUSTOM_BLOCK_TEXT = "Lifecycle custom block: keep every slide to one idea."
ARCHITECT_SUFFIX = " Lifecycle A."
BUILDER_SUFFIX = " Lifecycle B."
CHANGED_ROLES = ["architect", "builder", "fixer"]
UNCHANGED_ROLES = ["data_analyst", "build_reviewer", "fix_reviewer", "deck_reviewer"]

#: Graph projection keys a conversation response must never carry (S02).
FORBIDDEN_CONVERSATION_KEYS = frozenset(
    {"graph_release_id", "prompt_text", "endpoint_name", "content_hash"}
)
#: ``SessionManager.create_session``'s exact response keys.
CREATE_SESSION_KEYS = frozenset(
    {
        "session_id",
        "user_id",
        "created_by",
        "title",
        "created_at",
        "graph_version",
        "active_graph_version",
        "is_older_than_active",
    }
)


# ---------------------------------------------------------------------------
# Stages and attribution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    code: str  # "S11"
    name: str  # "publish"
    ticket: str  # "#269"
    seam: str  # "POST /api/admin/agent-definitions/releases"

    @property
    def label(self) -> str:
        return f"{self.code} {self.name} via {self.seam}"


def _stages(*rows: tuple[str, str, str, str]) -> dict[str, Stage]:
    return {code: Stage(code, name, ticket, seam) for code, name, ticket, seam in rows}


STAGES: dict[str, Stage] = _stages(
    ("S01", "bootstrap", "#260", f"GET {ADMIN_PREFIX}/workbench"),
    ("S02", "old conversation", "#261", "POST /api/sessions"),
    ("S03", "edit prompts and model", "#263", f"PUT {ADMIN_PREFIX}/draft/{{agent_key}}"),
    (
        "S04",
        "overlay",
        "#264",
        f"POST {ADMIN_PREFIX}/draft/{{agent_key}}/schema-contract-upgrade",
    ),
    (
        "S05",
        "assembly",
        "#265",
        f"POST {ADMIN_PREFIX}/draft/{{agent_key}}/protected-assembly-upgrade",
    ),
    ("S06", "endpoint", "#266", f"GET {ADMIN_PREFIX}/model-endpoints"),
    ("S07", "test", "#267", f"POST {ADMIN_PREFIX}/draft/{{agent_key}}/test-runs"),
    ("S08", "approve", "#268", f"POST {ADMIN_PREFIX}/test-runs/{{run_id}}/verdict"),
    ("S09", "readiness", "#268", f"GET {ADMIN_PREFIX}/readiness"),
    ("S10", "preview", "#269", f"GET {ADMIN_PREFIX}/release-preview"),
    ("S11", "publish", "#269", f"POST {ADMIN_PREFIX}/releases"),
    ("S12", "pinned conversations", "#262", "POST /api/sessions/{session_id}/contribute"),
    (
        "S12b",
        "collaboration history",
        "#262",
        "GET /api/sessions/{session_id}/collaboration-history",
    ),
    ("S14", "history", "#270", f"GET {ADMIN_PREFIX}/releases"),
    ("S15", "rollback", "#270", f"POST {ADMIN_PREFIX}/releases/{{version_number}}/rollback"),
    ("S16", "post-rollback pins", "#270", "POST /api/sessions"),
    ("S18", "closing checks", "#271", "graph_release rows"),
)


class StageFailure(AssertionError):  # noqa: N818 (the interface name)
    """A journey failure, labelled with the ticket and stage it is attributed to."""


class CodeDefaultRead(AssertionError):  # noqa: N818
    """A code-owned definition source was read after Graph Version 1 was bootstrapped."""


#: The armed tripwire, if any; set through ``monkeypatch`` so teardown disarms it.
_ARMED_TRIPWIRE: CodeDefaultTripwire | None = None


def _tripwire_label(current: Stage, reads: list[str]) -> str:
    return (
        f"[AC1/#271] {current.label}: code-owned definition read after "
        f"Graph Version 1: {', '.join(reads)}"
    )


@contextmanager
def stage(current: Stage) -> Iterator[None]:
    """Run one stage; relabel any failure with the stage's ticket and seam.

    A ``StageFailure`` from a nested ``stage()`` or a ``require`` passes through
    unchanged, so the innermost (or upstream) label wins.  A code-owned read that
    happened during the stage wins over whatever failure it caused, and is still
    reported when production code swallowed it and the stage otherwise passed.
    """
    tripwire = _ARMED_TRIPWIRE
    before = len(tripwire.reads) if tripwire is not None else 0

    def new_reads() -> list[str]:
        return tripwire.reads[before:] if tripwire is not None else []

    try:
        yield
    except StageFailure:
        raise
    except Exception as exc:
        reads = new_reads()
        if reads or isinstance(exc, CodeDefaultRead):
            raise StageFailure(_tripwire_label(current, reads or [str(exc)])) from exc
        raise StageFailure(
            f"[{current.ticket}] {current.label}: {type(exc).__name__}: {exc}"
        ) from exc
    reads = new_reads()
    if reads:
        raise StageFailure(_tripwire_label(current, reads))


def require(upstream: Stage, condition: bool, detail: str) -> None:
    """Fail, labelled with the UPSTREAM stage, when its output is not as consumed."""
    if not condition:
        raise StageFailure(f"[{upstream.ticket}] {upstream.label}: {detail}")


# ---------------------------------------------------------------------------
# The AC1 tripwire
# ---------------------------------------------------------------------------


class _RaisingMapping(Mapping):
    """Stands in for ``src.core.skills._SKILLS``: every access is a recorded read."""

    def __init__(self, trip: Callable[[], None]) -> None:
        self._trip = trip

    def __getitem__(self, key: object) -> Any:
        self._trip()

    def __iter__(self) -> Iterator[Any]:
        self._trip()
        return iter(())

    def __len__(self) -> int:
        self._trip()
        return 0

    def __contains__(self, key: object) -> bool:
        self._trip()
        return False


class _RaisingModule(types.ModuleType):
    """Stands in for the manifest module in ``sys.modules``.

    Any non-dunder attribute read is a recorded read.  Dunder probes (``hasattr(m,
    "__path__")`` from the import system, ``__warningregistry__`` from warnings,
    tooling walking ``sys.modules``) are plain ``AttributeError`` so they record
    nothing.
    """

    def __init__(self, name: str, trip: Callable[[], None]) -> None:
        super().__init__(name)
        object.__setattr__(self, "_trip", trip)

    def __getattr__(self, attribute: str) -> Any:
        if attribute.startswith("__") and attribute.endswith("__"):
            raise AttributeError(attribute)
        self._trip()


class CodeDefaultTripwire:
    """After arm(), any read of a code-owned definition source or the bootstrap manifest raises.

    The compatibility runtime's two class targets were dropped in #271 Task 12,
    when the classes were deleted; ``test_lakebase_only_runtime_contract.py``
    pins that they cannot return.
    """

    def __init__(self) -> None:
        self.reads: list[str] = []

    def _tripper(self, name: str) -> Callable[[], None]:
        def trip() -> None:
            self.reads.append(name)
            raise CodeDefaultRead(f"code-owned definition read after Graph Version 1: {name}")

        return trip

    def _raiser(self, name: str) -> Callable[..., Any]:
        trip = self._tripper(name)

        def raiser(*_args: Any, **_kwargs: Any) -> Any:
            trip()

        return raiser

    def arm(self, monkeypatch) -> None:
        import src.core.skills as skills
        import src.services as services_package
        import src.services.graph_definition_manifest as manifest

        manifest_module = "src.services.agent_definition_manifest_v1"
        # Clear first: a by-name binding of the cached loader then misses the
        # cache and imports the manifest, which the swapped module traps.
        manifest.load_graph_v1_manifest.cache_clear()
        monkeypatch.setattr(skills, "load_skill", self._raiser("src.core.skills.load_skill"))
        # C6: ``load_skill`` indexes ``_SKILLS``, so trapping the mapping catches a
        # module-level ``from src.core.skills import load_skill`` binding too.
        monkeypatch.setattr(
            skills, "_SKILLS", _RaisingMapping(self._tripper("src.core.skills._SKILLS"))
        )
        monkeypatch.setattr(
            manifest,
            "load_graph_v1_manifest",
            self._raiser("src.services.graph_definition_manifest.load_graph_v1_manifest"),
        )
        stand_in = _RaisingModule(manifest_module, self._tripper(manifest_module))
        monkeypatch.setitem(sys.modules, manifest_module, stand_in)
        monkeypatch.setattr(
            services_package, "agent_definition_manifest_v1", stand_in, raising=False
        )
        monkeypatch.setattr(sys.modules[__name__], "_ARMED_TRIPWIRE", self)


# ---------------------------------------------------------------------------
# The journey
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordedExchange:
    id: str  # "S03-put-architect": the stage code, then a stage-local label
    method: str
    path: str
    request: JsonValue | None
    status: int
    body: JsonValue


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _captured_logs() -> Iterator[list[logging.LogRecord]]:
    """Every record any logger emits at INFO or above, for the block's duration."""
    root = logging.getLogger()
    handler = _LogCapture()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield handler.records
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in vars(record).items() if k not in STANDARD_LOG_RECORD_ATTRS}


@dataclass
class LifecycleJourney:
    factory: sessionmaker
    admin: TestClient  # admin router, authorized principal (same app as ``user``)
    user: TestClient  # sessions router, non-admin principals (same app as ``admin``)
    adapter: DeterministicFakeModelAdapter
    tripwire: CodeDefaultTripwire
    exchanges: list[RecordedExchange] = field(default_factory=list)  # for Task 10
    state: dict[str, Any] = field(default_factory=dict)  # ids produced by each stage
    workbench: Any = None
    completed: list[str] = field(default_factory=list)
    _current: Stage | None = None

    # -- driving ---------------------------------------------------------------

    def run_to(self, stage_code: str) -> LifecycleJourney:
        """Run every stage not yet run, in order, up to and including ``stage_code``."""
        order = list(STAGES)
        if stage_code not in STAGES:
            raise KeyError(f"unknown stage {stage_code!r}; stages are {order}")
        target = order.index(stage_code)
        for code in order[len(self.completed) : target + 1]:
            with self.in_stage(STAGES[code]):
                _STAGE_BODIES[code](self)
            self.completed.append(code)
        return self

    @contextmanager
    def in_stage(self, current: Stage) -> Iterator[None]:
        """Run a caller's own stage body (e.g. Task 7's S13/S17) with attribution.

        ``call()`` records its exchanges under ``current.code`` and any failure is
        labelled as ``stage(current)`` labels it.  The enclosing stage, if any, is
        restored on exit.  A caller stage is not appended to ``completed``, so
        ``run_to`` is unaffected.
        """
        previous = self._current
        self._current = current
        try:
            with stage(current):
                yield
        finally:
            self._current = previous

    def call(
        self,
        label: str,
        method: str,
        path: str,
        *,
        principal: str,
        expect: int,
        json: JsonValue | None = None,
    ) -> Any:
        """One HTTP exchange as ``principal``, recorded, with an exact status."""
        assert self._current is not None, "call() outside a stage"
        exchange_id = f"{self._current.code}-{label}"
        assert exchange_id not in {e.id for e in self.exchanges}, exchange_id
        set_current_user(principal)
        set_permission_context(PermissionContext(user_name=principal))
        response = self.admin.request(method, path, json=json)
        try:
            body: JsonValue = response.json()
        except ValueError:
            body = response.text
        self.exchanges.append(
            RecordedExchange(exchange_id, method, path, json, response.status_code, body)
        )
        assert response.status_code == expect, (
            f"{method} {path} as {principal}: expected {expect}, got "
            f"{response.status_code}: {response.text}"
        )
        return body

    def admin_call(self, label: str, method: str, path: str, *, expect: int, json=None) -> Any:
        return self.call(
            label, method, f"{ADMIN_PREFIX}{path}", principal=ADMIN, expect=expect, json=json
        )

    # -- UI reads (C1: every GET the UI makes after a save, run or verdict) ------

    def read_workbench(self, label: str) -> dict:
        return self.admin_call(label, "GET", "/workbench", expect=200)

    def read_readiness(self, label: str) -> dict:
        return self.admin_call(label, "GET", "/readiness", expect=200)

    def read_runs(self, label: str, test_case_id: int) -> dict:
        return self.admin_call(label, "GET", f"/test-cases/{test_case_id}/runs", expect=200)

    # -- database reads (pins and closing checks only) --------------------------

    def pins(self) -> dict[str, int | None]:
        with self.factory() as db:
            return {
                row.session_id: row.graph_release_id
                for row in db.scalars(select(UserSession).order_by(UserSession.id))
            }

    def pin_of(self, session_id: str) -> int | None:
        return _pin_of(self.factory, session_id)

    def draft_row(self, agent_key: str) -> dict[str, Any]:
        with self.factory() as db:
            row = db.get(GraphDraftAgent, {"graph_draft_id": 1, "agent_key": agent_key})
            return {
                column.key: getattr(row, column.key) for column in GraphDraftAgent.__table__.columns
            }

    def releases(self) -> list[tuple[int, int, bool]]:
        return _release_ids(self.factory)


def _node(workbench: dict, agent_key: str) -> dict:
    matches = [node for node in workbench["nodes"] if node["agent_key"] == agent_key]
    assert len(matches) == 1, [node["agent_key"] for node in workbench["nodes"]]
    return matches[0]


def _candidate(draft: dict, **changes: Any) -> dict:
    """The strict ``EditableModelDraftRequest`` for ``draft``, with ``changes`` applied."""
    candidate: dict[str, Any] = {
        "prompt_text": draft["prompt_text"],
        "model": {
            key: draft["model"][key]
            for key in ("endpoint_name", "temperature", "max_tokens", "top_p")
        },
    }
    model_changes = changes.pop("model", {})
    candidate["model"].update(model_changes)
    candidate.update(changes)
    return candidate


def _lock(j: LifecycleJourney) -> int:
    return j.state["lock"]


def _set_lock(j: LifecycleJourney, response: dict) -> int:
    j.state["lock"] = response["draft"]["lock_version"]
    return j.state["lock"]


# ---------------------------------------------------------------------------
# Stage bodies
# ---------------------------------------------------------------------------


def _s01_bootstrap(j: LifecycleJourney) -> None:
    body = j.read_workbench("workbench")
    active = body["active_release"]
    assert (active["release_id"], active["version_number"]) == (1, 1), active
    assert active["effective_to"] is None and active["previous_release_id"] is None, active
    editable = [node for node in body["nodes"] if node["execution_kind"] == "model"]
    assert [node["agent_key"] for node in editable] == list(GRAPH_V1_AGENT_KEYS)
    assert all(node["editable"] is True for node in editable)
    assert [node["changed"] for node in editable] == [False] * 7
    foreman = [node for node in body["nodes"] if node["execution_kind"] == "deterministic"]
    assert [
        (
            node["agent_key"],
            node["display_name"],
            node["editable"],
            node["changed"],
            node["published"],
            node["draft"],
        )
        for node in foreman
    ] == [("foreman", "Foreman", False, False, None, None)], foreman
    assert len(body["nodes"]) == 8, [node["agent_key"] for node in body["nodes"]]
    draft = body["draft"]
    assert (draft["base_release_id"], draft["base_version_number"]) == (1, 1), draft
    for node in editable:
        assert node["draft"]["candidate_hash"] == node["published"]["content_hash"], node[
            "agent_key"
        ]
        assert node["draft"]["base_revision_id"] == node["published"]["revision_id"]
    v1_mappings = _mapping_rows(j.factory, 1)
    assert v1_mappings == {node["agent_key"]: node["published"]["revision_id"] for node in editable}
    j.state.update(
        v1_id=1,
        lock0=draft["lock_version"],
        lock=draft["lock_version"],
        v1_mappings=v1_mappings,
        v1_hashes={node["agent_key"]: node["published"]["content_hash"] for node in editable},
        published={node["agent_key"]: node["published"] for node in editable},
    )
    assert j.state["lock0"] == 0, draft


def _seed_old_root_deck(j: LifecycleJourney) -> None:
    """C2: old-root carries a deck and an agent-mode marker, as a graph turn leaves it."""
    with _session_manager_on(j.factory) as manager:
        manager.add_message(
            "old-root", role="user", content=f"{AGENT_MODE_PHRASE} build the lifecycle deck"
        )
        manager.save_slide_deck(
            "old-root",
            "Lifecycle deck",
            '<div class="slide">One</div>',
            slide_count=1,
            deck_dict={
                "title": "Lifecycle deck",
                "css": ".slide{}",
                "external_scripts": [],
                "head_meta": {},
                "slides": [{"slide_id": "slide-one", "html": '<div class="slide">One</div>'}],
            },
        )


def _s02_old_conversation(j: LifecycleJourney) -> None:
    s01 = STAGES["S01"]
    require(s01, j.state.get("v1_id") == 1, f"v1 id is {j.state.get('v1_id')!r}, not 1")
    body = j.call(
        "post-old-root",
        "POST",
        "/api/sessions",
        principal=OWNER,
        expect=200,
        json={"session_id": "old-root", "graph_capable": True},
    )
    assert set(body) == CREATE_SESSION_KEYS, sorted(body)
    assert not FORBIDDEN_CONVERSATION_KEYS & set(body), sorted(body)
    assert (
        body["session_id"],
        body["created_by"],
        body["graph_version"],
        body["active_graph_version"],
        body["is_older_than_active"],
    ) == ("old-root", OWNER, 1, 1, False), body
    assert j.pin_of("old-root") == j.state["v1_id"]

    # C37: one control conversation with the DEFAULT body persists a null pin
    # (Task 8's legacy case consumes this exchange).
    control = j.call(
        "post-control-default-body",
        "POST",
        "/api/sessions",
        principal=OWNER,
        expect=200,
        json={"session_id": "control-legacy"},
    )
    assert (control["graph_version"], control["is_older_than_active"]) == (None, False), control
    assert j.pin_of("control-legacy") is None

    _seed_old_root_deck(j)
    assert j.pins() == {"old-root": 1, "control-legacy": None}


def _s03_edit(j: LifecycleJourney) -> None:
    s01 = STAGES["S01"]
    lock0 = j.state.get("lock0")
    require(s01, lock0 == 0, f"bootstrap lock is {lock0!r}, not 0")
    workbench = j.read_workbench("workbench-before-edit")
    require(s01, workbench["draft"]["lock_version"] == lock0, "lock moved before any save")
    fixer_before = j.draft_row("fixer")

    architect = _node(workbench, "architect")["draft"]
    request = {
        "lock_version": lock0,
        "candidate": _candidate(
            architect,
            prompt_text=architect["prompt_text"] + ARCHITECT_SUFFIX,
        ),
    }
    saved = j.admin_call("put-architect", "PUT", "/draft/architect", expect=200, json=request)
    assert _set_lock(j, saved) == lock0 + 1, saved["draft"]
    assert saved["changed"] is True
    assert saved["definition"]["prompt_text"] == architect["prompt_text"] + ARCHITECT_SUFFIX
    assert saved["definition"]["model"]["temperature"] == 0.7
    j.read_readiness("readiness-after-architect")

    builder = _node(workbench, "builder")["draft"]
    request = {
        "lock_version": lock0 + 1,
        "candidate": _candidate(builder, prompt_text=builder["prompt_text"] + BUILDER_SUFFIX),
    }
    saved = j.admin_call("put-builder", "PUT", "/draft/builder", expect=200, json=request)
    assert _set_lock(j, saved) == lock0 + 2, saved["draft"]
    j.state["builder_hash_s03"] = saved["definition"]["candidate_hash"]
    j.read_readiness("readiness-after-builder")

    fixer = _node(workbench, "fixer")["draft"]
    stale = j.admin_call(
        "put-fixer-stale",
        "PUT",
        "/draft/fixer",
        expect=409,
        json={
            "lock_version": lock0,
            "candidate": _candidate(fixer, prompt_text=fixer["prompt_text"] + " stale"),
        },
    )
    assert (stale["code"], stale["expected_lock_version"], stale["current_lock_version"]) == (
        "stale_draft",
        lock0,
        lock0 + 2,
    ), stale
    assert list(stale["server"]["definitions"]) == list(GRAPH_V1_AGENT_KEYS), stale["server"]
    assert stale["server"]["draft"]["lock_version"] == lock0 + 2
    assert j.draft_row("fixer") == fixer_before, "a stale PUT wrote the fixer draft"

    after = j.read_workbench("workbench-after-edit")
    assert {node["agent_key"]: node["changed"] for node in after["nodes"]} == {
        "architect": True,
        "data_analyst": False,
        "builder": True,
        "build_reviewer": False,
        "fixer": False,
        "fix_reviewer": False,
        "deck_reviewer": False,
        "foreman": False,
    }


def _s04_overlay(j: LifecycleJourney) -> None:
    s03 = STAGES["S03"]
    lock = _lock(j)
    require(s03, lock == j.state["lock0"] + 2, f"lock after S03 is {lock}, not L0+2")
    require(s03, "builder_hash_s03" in j.state, "S03 recorded no builder candidate hash")

    upgraded = j.admin_call(
        "post-builder-schema-contract-upgrade",
        "POST",
        "/draft/builder/schema-contract-upgrade",
        expect=200,
        json={"lock_version": lock},
    )
    lock = _set_lock(j, upgraded)
    assert upgraded["definition"]["schema_contract"] == {
        "version": 2,
        "digest": BUILDER_SCHEMA_CONTRACT_V2_DIGEST,
    }, upgraded["definition"]["schema_contract"]
    j.read_readiness("readiness-after-upgrade")

    builder = upgraded["definition"]
    saved = j.admin_call(
        "put-builder-overlay",
        "PUT",
        "/draft/builder",
        expect=200,
        json={
            "lock_version": lock,
            "candidate": _candidate(
                builder,
                schema_overlay={
                    "field_overrides": {},
                    "additional_optional_fields": ["diagnostic_notes"],
                },
            ),
        },
    )
    _set_lock(j, saved)
    definition = saved["definition"]
    assert definition["schema_overlay"] == {
        "field_overrides": {},
        "additional_optional_fields": ["diagnostic_notes"],
    }, definition["schema_overlay"]
    assert definition["schema_contract"] == {
        "version": 2,
        "digest": BUILDER_SCHEMA_CONTRACT_V2_DIGEST,
    }, definition["schema_contract"]
    assert definition["prompt_text"].endswith(BUILDER_SUFFIX), definition["prompt_text"][-80:]
    assert definition["candidate_hash"] != j.state["builder_hash_s03"], (
        "the overlay save did not change builder's candidate hash",
        definition["candidate_hash"],
    )
    row = j.draft_row("builder")
    assert (
        row["schema_overlay"],
        row["schema_contract_version"],
        row["schema_contract_digest"],
        row["candidate_hash"],
    ) == (
        {"field_overrides": {}, "additional_optional_fields": ["diagnostic_notes"]},
        2,
        BUILDER_SCHEMA_CONTRACT_V2_DIGEST,
        definition["candidate_hash"],
    ), row
    j.read_readiness("readiness-after-overlay")


def _s05_assembly(j: LifecycleJourney) -> None:
    s04 = STAGES["S04"]
    lock = _lock(j)
    require(s04, lock == j.state["lock0"] + 4, f"lock after S04 is {lock}, not L0+4")
    before = j.draft_row("architect")

    upgraded = j.admin_call(
        "post-architect-protected-assembly-upgrade",
        "POST",
        "/draft/architect/protected-assembly-upgrade",
        expect=200,
        json={"lock_version": lock},
    )
    lock = _set_lock(j, upgraded)
    architect = upgraded["definition"]
    assert architect["protected_assembly"] == {
        "version": 2,
        "digest": ARCHITECT_PROTECTED_ASSEMBLY_V2_DIGEST,
    }, architect["protected_assembly"]
    # C34 probe: the upgrade itself moves the rules to format 2 (so S10's architect
    # diff names ``assembly_rules`` even before the custom block); ``prompt_text``
    # is untouched.
    after_upgrade = j.draft_row("architect")
    j.state["s05_upgrade_rewrote"] = sorted(
        key for key in before if before[key] != after_upgrade[key]
    )
    assert j.state["s05_upgrade_rewrote"] == [
        "assembly_rules",
        "candidate_hash",
        "protected_assembly_digest",
        "protected_assembly_version",
    ], j.state["s05_upgrade_rewrote"]
    assert architect["assembly_rules"] == {"format_version": 2, "custom_blocks": []}
    j.read_readiness("readiness-after-upgrade")

    block = {
        "kind": "custom_text",
        "block_id": CUSTOM_BLOCK_ID,
        "anchor": "after_authored_prompt",
        "condition": "always",
        "text": CUSTOM_BLOCK_TEXT,
    }
    saved = j.admin_call(
        "put-architect-custom-block",
        "PUT",
        "/draft/architect",
        expect=200,
        json={
            "lock_version": lock,
            "candidate": _candidate(
                architect,
                assembly_rules={
                    "format_version": 2,
                    "custom_blocks": [
                        *architect["assembly_rules"]["custom_blocks"],
                        block,
                    ],
                },
            ),
        },
    )
    _set_lock(j, saved)
    definition = saved["definition"]
    assert definition["assembly_rules"] == {"format_version": 2, "custom_blocks": [block]}, (
        definition["assembly_rules"]
    )
    assert definition["protected_assembly"] == {
        "version": 2,
        "digest": ARCHITECT_PROTECTED_ASSEMBLY_V2_DIGEST,
    }, definition["protected_assembly"]
    assert definition["prompt_text"].endswith(ARCHITECT_SUFFIX), definition["prompt_text"][-80:]
    assert definition["model"]["temperature"] == 0.7, definition["model"]
    row = j.draft_row("architect")
    assert row["assembly_rules"] == {"format_version": 2, "custom_blocks": [block]}, row
    assert (row["protected_assembly_version"], row["protected_assembly_digest"]) == (
        2,
        ARCHITECT_PROTECTED_ASSEMBLY_V2_DIGEST,
    ), (row["protected_assembly_version"], row["protected_assembly_digest"])
    j.read_readiness("readiness-after-custom-block")


def _s06_endpoint(j: LifecycleJourney) -> None:
    s05 = STAGES["S05"]
    lock = _lock(j)
    require(s05, lock == j.state["lock0"] + 6, f"lock after S05 is {lock}, not L0+6")

    discovery = j.admin_call("get-model-endpoints", "GET", "/model-endpoints", expect=200)
    assert [item["name"] for item in discovery["items"]] == [OPUS, SONNET], discovery

    workbench = j.read_workbench("workbench-before-endpoint")
    fixer = _node(workbench, "fixer")["draft"]
    assert fixer["model"]["endpoint_name"] != SONNET, fixer["model"]
    saved = j.admin_call(
        "put-fixer-endpoint",
        "PUT",
        "/draft/fixer",
        expect=200,
        json={
            "lock_version": lock,
            "candidate": _candidate(fixer, model={"endpoint_name": SONNET}),
        },
    )
    _set_lock(j, saved)
    assert saved["definition"]["model"]["endpoint_name"] == SONNET, saved["definition"]["model"]
    assert j.draft_row("fixer")["endpoint_name"] == SONNET, j.draft_row("fixer")["endpoint_name"]
    j.read_readiness("readiness-after-endpoint")


def _required_case(j: LifecycleJourney, agent_key: str) -> dict:
    listing = j.admin_call(
        f"get-test-cases-{agent_key}", "GET", f"/test-cases?agent_key={agent_key}", expect=200
    )
    assert {item["agent_key"] for item in listing["items"]} == {agent_key}, listing
    required = [item for item in listing["items"] if item["is_required"] and item["is_active"]]
    assert len(required) == 1, [(item["id"], item["name"]) for item in listing["items"]]
    return required[0]


def _run_case(j: LifecycleJourney, label: str, agent_key: str, case_id: int) -> dict:
    run = j.admin_call(
        label,
        "POST",
        f"/draft/{agent_key}/test-runs",
        expect=201,
        json={"test_case_id": case_id, "lock_version": _lock(j)},
    )
    assert (run["run_kind"], run["agent_key"], run["test_case_id"]) == (
        "candidate",
        agent_key,
        case_id,
    ), run
    assert (
        run["execution_status"],
        run["deterministic_checks_passed"],
        run["verdict"],
        run["candidate_is_current"],
    ) == ("completed", True, None, True), run
    return run


def _s07_test(j: LifecycleJourney) -> None:
    s06 = STAGES["S06"]
    lock = _lock(j)
    require(s06, lock == j.state["lock0"] + 7, f"lock after S06 is {lock}, not L0+7")
    sink = j.workbench._runtime_override._identity_sink
    sink_calls_before = list(sink.calls)
    adapter_before = len(j.adapter.calls)

    # Ids are not versions or other ids: start run ids well clear of case ids, so a
    # run id confused with a case id (or a revision id) cannot pass by coincidence.
    with j.factory() as db:
        db.execute(text("SELECT setval(pg_get_serial_sequence('agent_test_run', 'id'), 100)"))
        db.commit()
    workbench = j.read_workbench("workbench-before-runs")
    j.state["cases"] = {}
    j.state["runs"] = {}
    with _captured_logs() as records:
        for agent_key in CHANGED_ROLES:
            case = _required_case(j, agent_key)
            j.state["cases"][agent_key] = case["id"]
            run = _run_case(j, f"post-run-{agent_key}", agent_key, case["id"])
            draft_hash = _node(workbench, agent_key)["draft"]["candidate_hash"]
            assert run["candidate_hash"] == draft_hash, (run["candidate_hash"], draft_hash)
            assert run["compared_release_id"] == j.state["v1_id"]
            assert run["compared_definition_revision_id"] == j.state["v1_mappings"][agent_key]
            j.state["runs"][agent_key] = run
            runs = j.read_runs(f"get-runs-{agent_key}", case["id"])
            assert [item["run_id"] for item in runs["items"]] == [run["run_id"]], runs
            j.read_readiness(f"readiness-after-run-{agent_key}")

    calls = j.adapter.calls[adapter_before:]
    assert [call.agent_key for call in calls] == CHANGED_ROLES
    architect_run = j.state["runs"]["architect"]
    assert calls[0].prompt == architect_run["assembled_prompt"]
    assert CUSTOM_BLOCK_TEXT in architect_run["assembled_prompt"]
    assert ARCHITECT_SUFFIX.strip() in architect_run["assembled_prompt"]
    assert calls[0].configuration.temperature == 0.7
    assert calls[2].configuration.endpoint_name == SONNET

    # C33/C48: a candidate run never reaches the production identity sink.
    assert sink.calls == sink_calls_before, "a candidate run reached the identity sink"
    assert [r for r in records if r.getMessage() == "persisted_agent_invocation"] == []
    candidate_records = [r for r in records if r.getMessage() == "agent_candidate_run"]
    assert [
        (set(_extras(r)), _extras(r)["agent_key"], _extras(r)["status"]) for r in candidate_records
    ] == [
        ({"agent_key", "status", "error_code", "error_class"}, key, "completed")
        for key in CHANGED_ROLES
    ], [_extras(r) for r in candidate_records]
    assert _lock(j) == lock, "a test run moved the draft lock"


def _verdict(j: LifecycleJourney, label: str, run_id: int, verdict: str, notes) -> dict:
    body = j.admin_call(
        label,
        "POST",
        f"/test-runs/{run_id}/verdict",
        expect=200,
        json={"verdict": verdict, "notes": notes},
    )
    assert (body["run_id"], body["verdict"], body["verdict_reviewer"], body["verdict_notes"]) == (
        run_id,
        verdict,
        ADMIN,
        notes,
    ), body
    return body


def _s08_approve(j: LifecycleJourney) -> None:
    s07 = STAGES["S07"]
    runs = j.state.get("runs", {})
    require(s07, list(runs) == CHANGED_ROLES, f"S07 runs are {list(runs)}")
    require(
        s07,
        all(run["execution_status"] == "completed" for run in runs.values()),
        "an S07 run did not complete",
    )

    _verdict(j, "reject-builder", runs["builder"]["run_id"], "rejected", "Lifecycle: rerun.")
    j.read_readiness("readiness-after-reject")
    _verdict(j, "approve-architect", runs["architect"]["run_id"], "approved", None)
    j.read_readiness("readiness-after-approve-architect")
    _verdict(j, "approve-fixer", runs["fixer"]["run_id"], "approved", None)
    j.read_readiness("readiness-after-approve-fixer")

    rerun = _run_case(j, "post-rerun-builder", "builder", j.state["cases"]["builder"])
    assert rerun["run_id"] > runs["builder"]["run_id"]
    j.state["builder_rerun"] = rerun
    listed = j.read_runs("get-runs-builder-after-rerun", j.state["cases"]["builder"])
    assert [(item["run_id"], item["verdict"]) for item in listed["items"]] == [
        (rerun["run_id"], None),
        (runs["builder"]["run_id"], "rejected"),
    ], listed


def _readiness_rows(body: dict) -> dict[str, list[tuple]]:
    return {
        agent["agent_key"]: [
            (case["test_case_id"], case["status"], case["run_id"], case["run_verdict"])
            for case in agent["cases"]
        ]
        for agent in body["agents"]
        if agent["is_changed_from_base"]
    }


def _s09_readiness(j: LifecycleJourney) -> None:
    s08 = STAGES["S08"]
    rerun = j.state.get("builder_rerun")
    require(s08, rerun is not None and rerun["verdict"] is None, "no unreviewed builder rerun")
    cases, runs = j.state["cases"], j.state["runs"]

    before = j.read_readiness("readiness-before-rerun-approval")
    assert _readiness_rows(before) == {
        "architect": [(cases["architect"], "approved", runs["architect"]["run_id"], "approved")],
        "builder": [(cases["builder"], "awaiting_review", rerun["run_id"], None)],
        "fixer": [(cases["fixer"], "approved", runs["fixer"]["run_id"], "approved")],
    }, before
    assert (before["all_ready"], before["blocking_agents"]) == (False, ["builder"]), before

    _verdict(j, "approve-builder-rerun", rerun["run_id"], "approved", None)
    after = j.read_readiness("readiness-after-rerun-approval")
    assert _readiness_rows(after) == {
        "architect": [(cases["architect"], "approved", runs["architect"]["run_id"], "approved")],
        "builder": [(cases["builder"], "approved", rerun["run_id"], "approved")],
        "fixer": [(cases["fixer"], "approved", runs["fixer"]["run_id"], "approved")],
    }, after
    assert (after["all_ready"], after["blocking_agents"]) == (True, []), after
    assert after["draft_lock_version"] == _lock(j)
    assert after["base_release_id"] == j.state["v1_id"]


def _s10_preview(j: LifecycleJourney) -> None:
    s09 = STAGES["S09"]
    require(s09, j.state.get("builder_rerun") is not None, "S09 left no builder rerun")
    preview = j.admin_call("get-release-preview", "GET", "/release-preview", expect=200)
    assert [item["agent_key"] for item in preview["changed"]] == CHANGED_ROLES, preview["changed"]
    assert preview["next_version_number"] == 2
    assert preview["publishable"] is True, preview
    assert preview["validation_issues"] == []
    assert preview["draft"]["lock_version"] == _lock(j)
    assert (
        preview["active_release"]["release_id"],
        preview["active_release"]["version_number"],
    ) == (j.state["v1_id"], 1)
    fields = {
        item["agent_key"]: [diff["field"] for diff in item["field_diffs"]]
        for item in preview["changed"]
    }
    # C34: exact field sets, in ``_DIFF_FIELDS`` order.
    assert fields == {
        "architect": [
            "prompt_text",
            "assembly_rules",
            "protected_assembly.version",
            "protected_assembly.digest",
        ],
        "builder": [
            "prompt_text",
            "schema_overlay",
            "schema_contract.version",
            "schema_contract.digest",
        ],
        "fixer": ["model.endpoint_name"],
    }, fields
    for item in preview["changed"]:
        key = item["agent_key"]
        assert item["published_revision_id"] == j.state["v1_mappings"][key]
        assert item["published_content_hash"] == j.state["v1_hashes"][key]
    architect_prompt = next(
        diff for diff in preview["changed"][0]["field_diffs"] if diff["field"] == "prompt_text"
    )
    assert architect_prompt == {
        "field": "prompt_text",
        "published": j.state["published"]["architect"]["prompt_text"],
        "candidate": j.state["published"]["architect"]["prompt_text"] + ARCHITECT_SUFFIX,
    }
    j.state["preview_hashes"] = {
        item["agent_key"]: item["candidate_hash"] for item in preview["changed"]
    }


def _burn_release_id(j: LifecycleJourney) -> int:
    """Burn one ``graph_release.id`` so ids and version numbers diverge from here on."""
    with j.factory() as db:
        burned = db.scalar(text("SELECT nextval(pg_get_serial_sequence('graph_release', 'id'))"))
        db.commit()
    return int(burned)


def _s11_publish(j: LifecycleJourney) -> None:
    s10 = STAGES["S10"]
    require(s10, list(j.state.get("preview_hashes", {})) == CHANGED_ROLES, "no S10 preview")
    mid = j.call(
        "post-mid-root",
        "POST",
        "/api/sessions",
        principal=OWNER,
        expect=200,
        json={"session_id": "mid-root", "graph_capable": True},
    )
    assert (mid["graph_version"], mid["is_older_than_active"]) == (1, False), mid
    assert j.pin_of("mid-root") == j.state["v1_id"]

    assert _burn_release_id(j) == 2, "the bootstrap did not leave id 2 next"

    lock = _lock(j)
    stale = j.admin_call(
        "post-release-stale",
        "POST",
        "/releases",
        expect=409,
        json={"lock_version": lock - 1, "release_note": "Stale lifecycle publish."},
    )
    assert (stale["code"], stale["expected_lock_version"], stale["current_lock_version"]) == (
        "stale_publication",
        lock - 1,
        lock,
    ), stale
    assert stale["active_release"] == {"release_id": j.state["v1_id"], "version_number": 1}

    published = j.admin_call(
        "post-release",
        "POST",
        "/releases",
        expect=200,
        json={"lock_version": lock, "release_note": "Lifecycle Graph Version 2."},
    )
    release = published["release"]
    assert (
        release["release_id"],
        release["version_number"],
        release["previous_release_id"],
        release["restored_from_release_id"],
        release["published_by"],
        release["effective_to"],
    ) == (3, 2, j.state["v1_id"], None, ADMIN, None), release
    assert published["previous_release_id"] == j.state["v1_id"]
    assert published["changed_agents"] == CHANGED_ROLES
    mappings = published["mappings"]
    assert list(mappings) == list(GRAPH_V1_AGENT_KEYS)
    v1 = j.state["v1_mappings"]
    for key in UNCHANGED_ROLES:
        assert (mappings[key]["reused"], mappings[key]["agent_definition_revision_id"]) == (
            True,
            v1[key],
        ), (key, mappings[key])
    for key in CHANGED_ROLES:
        assert mappings[key]["reused"] is False, (key, mappings[key])
        assert mappings[key]["agent_definition_revision_id"] not in v1.values(), key
        assert mappings[key]["content_hash"] == j.state["preview_hashes"][key], key
    runs = j.state["runs"]
    assert sorted(
        (
            item["agent_key"],
            item["agent_test_run_id"],
            item["test_case_id"],
            item["evidence_kind"],
            item["source_release_id"],
        )
        for item in published["evidence"]
    ) == sorted(
        [
            (
                "architect",
                runs["architect"]["run_id"],
                j.state["cases"]["architect"],
                "approval",
                None,
            ),
            (
                "builder",
                j.state["builder_rerun"]["run_id"],
                j.state["cases"]["builder"],
                "approval",
                None,
            ),
            ("fixer", runs["fixer"]["run_id"], j.state["cases"]["fixer"], "approval", None),
        ]
    ), published["evidence"]
    assert published["draft"]["base_release_id"] == 3
    _set_lock(j, published)
    j.state["v2_id"] = 3
    j.state["v2_mappings"] = _mapping_rows(j.factory, 3)
    assert j.state["v2_mappings"] == {
        key: mapping["agent_definition_revision_id"] for key, mapping in mappings.items()
    }
    assert j.releases() == [(1, 1, False), (3, 2, True)]
    assert j.pins() == {"old-root": 1, "control-legacy": None, "mid-root": 1}

    after = j.read_workbench("workbench-after-publish")
    assert after["active_release"]["release_id"] == 3
    assert [node["changed"] for node in after["nodes"]] == [False] * 8


def _grant_contributor(j: LifecycleJourney) -> None:
    """C2: a non-admin contributor with a deck-level ``CAN_VIEW`` grant on old-root."""
    with j.factory.begin() as db:
        root_pk = db.scalar(select(UserSession.id).where(UserSession.session_id == "old-root"))
        db.add(
            DeckContributor(
                user_session_id=root_pk,
                identity_type="USER",
                identity_id="lifecycle-contributor-id",
                identity_name=CONTRIBUTOR,
                permission_level="CAN_VIEW",
            )
        )


def _s12_pinned(j: LifecycleJourney) -> None:
    s11 = STAGES["S11"]
    require(s11, j.state.get("v2_id") == 3, f"v2 id is {j.state.get('v2_id')!r}, not 3")
    v1_id, v2_id = j.state["v1_id"], j.state["v2_id"]
    pins_before = j.pins()

    new_root = j.call(
        "post-new-root",
        "POST",
        "/api/sessions",
        principal=OWNER,
        expect=200,
        json={"session_id": "new-root", "graph_capable": True},
    )
    assert (
        new_root["graph_version"],
        new_root["active_graph_version"],
        new_root["is_older_than_active"],
    ) == (2, 2, False), new_root
    assert j.pin_of("new-root") == v2_id, ("new-root", j.pin_of("new-root"))

    _grant_contributor(j)
    contributor = j.call(
        "post-contribute-old-root",
        "POST",
        "/api/sessions/old-root/contribute",
        principal=CONTRIBUTOR,
        expect=200,
    )
    assert (
        contributor["parent_session_id"],
        contributor["created_by"],
        contributor["is_contributor_session"],
        contributor["my_permission"],
    ) == ("old-root", CONTRIBUTOR, True, "CAN_VIEW"), contributor
    assert j.pin_of(contributor["session_id"]) == v2_id, (
        "contributor",
        j.pin_of(contributor["session_id"]),
    )
    j.state["contributor_id"] = contributor["session_id"]

    duplicate = j.call(
        "post-duplicate-old-root",
        "POST",
        "/api/sessions/old-root/duplicate",
        principal=CONTRIBUTOR,
        expect=201,
    )
    assert (duplicate["source_session_id"], duplicate["created_by"]) == (
        "old-root",
        CONTRIBUTOR,
    ), duplicate
    assert j.pin_of(duplicate["session_id"]) == v2_id, (
        "duplicate",
        j.pin_of(duplicate["session_id"]),
    )
    j.state["duplicate_id"] = duplicate["session_id"]

    for session_id, label in (("old-root", "get-old-root"), ("mid-root", "get-mid-root")):
        body = j.call(label, "GET", f"/api/sessions/{session_id}", principal=OWNER, expect=200)
        assert not FORBIDDEN_CONVERSATION_KEYS & set(body), sorted(body)
        assert (
            body["graph_version"],
            body["active_graph_version"],
            body["is_older_than_active"],
        ) == (1, 2, True), (session_id, body)
    contributor_view = j.call(
        "get-contributor",
        "GET",
        f"/api/sessions/{contributor['session_id']}",
        principal=CONTRIBUTOR,
        expect=200,
    )
    assert (
        contributor_view["graph_version"],
        contributor_view["is_older_than_active"],
    ) == (2, False), contributor_view

    assert j.pins() == {
        **pins_before,
        "new-root": v2_id,
        contributor["session_id"]: v2_id,
        duplicate["session_id"]: v2_id,
    }, j.pins()
    assert pins_before == {"old-root": v1_id, "control-legacy": None, "mid-root": v1_id}, (
        pins_before
    )


def _s12b_collaboration_history(j: LifecycleJourney) -> None:
    """C9: a v1 and a v2 mutation of old-root's ONE deck, then the grouped history."""
    s12 = STAGES["S12"]
    contributor_id = j.state.get("contributor_id")
    require(
        s12,
        contributor_id is not None and j.pin_of(contributor_id) == j.state["v2_id"],
        "S12 left no v2-pinned contributor on old-root",
    )
    slides = [{"slide_id": "slide-one", "html": '<div class="slide">One, edited</div>'}]
    with _session_manager_on(j.factory) as manager:
        # The owner (pinned v1), then the contributor (pinned v2), on the same deck.
        manager.save_slide_deck(
            "old-root",
            "Lifecycle deck",
            slides[0]["html"],
            slide_count=1,
            deck_dict={
                "title": "Lifecycle deck",
                "css": ".slide{}",
                "external_scripts": [],
                "head_meta": {},
                "slides": slides,
            },
        )
        manager.save_slide_deck(
            contributor_id,
            "Lifecycle deck",
            '<div class="slide">One, contributor</div>',
            slide_count=1,
            deck_dict={
                "title": "Lifecycle deck",
                "css": ".slide{}",
                "external_scripts": [],
                "head_meta": {},
                "slides": [
                    {"slide_id": "slide-one", "html": '<div class="slide">One, contributor</div>'}
                ],
            },
        )
    history = j.call(
        "get-old-root-collaboration-history",
        "GET",
        "/api/sessions/old-root/collaboration-history",
        principal=OWNER,
        expect=200,
    )
    # C49: CollaborationHistoryResponse has no ``extra="forbid"``: exact key sets.
    assert set(history) == {"mixed_release_warning", "has_legacy_evidence", "groups"}, history
    assert (history["mixed_release_warning"], history["has_legacy_evidence"]) == (True, False)
    assert all(
        set(group) == {"actor_label", "graph_version", "mutation_count", "last_mutation_at"}
        for group in history["groups"]
    ), history["groups"]
    assert [(group["graph_version"], group["mutation_count"]) for group in history["groups"]] == [
        (2, 2),
        (1, 4),
    ], history["groups"]
    assert len({group["actor_label"] for group in history["groups"]}) == 2


def _s14_history(j: LifecycleJourney) -> None:
    s11 = STAGES["S11"]
    require(s11, j.releases() == [(1, 1, False), (3, 2, True)], f"releases {j.releases()}")
    v1 = {"release_id": j.state["v1_id"], "version_number": 1}
    v2 = {"release_id": j.state["v2_id"], "version_number": 2}

    history = j.admin_call("get-releases", "GET", "/releases", expect=200)
    assert history["active_release"] == v2
    assert [
        (
            e["release_id"],
            e["version_number"],
            e["is_active"],
            e["previous"],
            e["restored_from"],
            e["restored_by"],
            e["published_by"],
        )
        for e in history["releases"]
    ] == [
        (3, 2, True, v1, None, [], ADMIN),
        (1, 1, False, None, None, [], BOOTSTRAP_ACTOR),
    ], history["releases"]
    assert history["releases"][0]["changed_agents"] == CHANGED_ROLES
    assert history["releases"][1]["effective_to"] == history["releases"][0]["effective_from"]

    detail = j.admin_call("get-release-1", "GET", "/releases/1", expect=200)
    assert set(detail) == {"release", "definitions", "evidence"}, sorted(detail)
    assert list(detail["definitions"]) == list(GRAPH_V1_AGENT_KEYS), list(detail["definitions"])
    assert {
        key: definition["agent_definition_revision_id"]
        for key, definition in detail["definitions"].items()
    } == j.state["v1_mappings"]
    assert {
        key: definition["content_hash"] for key, definition in detail["definitions"].items()
    } == j.state["v1_hashes"]
    assert (detail["release"]["release_id"], detail["release"]["version_number"]) == (1, 1)
    assert detail["evidence"] == []

    # C35: history evidence names its origin as ``source`` (null for an approval).
    v2_detail = j.admin_call("get-release-2", "GET", "/releases/2", expect=200)
    runs, cases = j.state["runs"], j.state["cases"]
    assert [
        (
            e["agent_key"],
            e["agent_test_run_id"],
            e["test_case_id"],
            e["evidence_kind"],
            e["source"],
            e["verdict"],
            e["verdict_reviewer"],
        )
        for e in v2_detail["evidence"]
    ] == [
        (
            "architect",
            runs["architect"]["run_id"],
            cases["architect"],
            "approval",
            None,
            "approved",
            ADMIN,
        ),
        (
            "builder",
            j.state["builder_rerun"]["run_id"],
            cases["builder"],
            "approval",
            None,
            "approved",
            ADMIN,
        ),
        ("fixer", runs["fixer"]["run_id"], cases["fixer"], "approval", None, "approved", ADMIN),
    ], v2_detail["evidence"]
    assert "source_release_id" not in v2_detail["evidence"][0]

    comparison = j.admin_call(
        "get-release-1-comparison", "GET", "/releases/1/comparison", expect=200
    )
    assert (comparison["active_release"], comparison["release"]) == (v2, v1)
    assert [
        (a["agent_key"], a["same_revision"], a["active_revision_id"], a["historical_revision_id"])
        for a in comparison["agents"]
    ] == [
        (key, key not in CHANGED_ROLES, j.state["v2_mappings"][key], j.state["v1_mappings"][key])
        for key in GRAPH_V1_AGENT_KEYS
    ], comparison["agents"]

    missing = j.admin_call("get-release-99", "GET", "/releases/99", expect=404)
    assert missing == {"detail": "Graph Version not found"}, missing


def _s15_rollback(j: LifecycleJourney) -> None:
    s14 = STAGES["S14"]
    require(s14, j.state.get("v2_mappings") is not None, "no v2 mappings recorded")
    v1 = {"release_id": j.state["v1_id"], "version_number": 1}
    v2 = {"release_id": j.state["v2_id"], "version_number": 2}

    preview = j.admin_call(
        "get-rollback-preview-1", "GET", "/releases/1/rollback-preview", expect=200
    )
    assert (preview["source"], preview["active_release"]) == (v1, v2)
    assert (preview["next_version_number"], preview["restorable"], preview["blocked"]) == (
        3,
        True,
        None,
    ), preview
    assert (preview["issues"], preview["warnings"], preview["evidence"]) == ([], [], [])
    assert preview["draft_effect"] == {
        key: ("reset" if key in CHANGED_ROLES else "unchanged") for key in GRAPH_V1_AGENT_KEYS
    }, preview["draft_effect"]
    assert preview["lock_version"] == _lock(j)
    lock = preview["lock_version"]

    with _captured_logs() as records:
        stale = j.admin_call(
            "post-rollback-1-stale",
            "POST",
            "/releases/1/rollback",
            expect=409,
            json={"lock_version": lock - 1, "release_note": "Stale lifecycle rollback."},
        )
        assert (stale["code"], stale["active_release"]) == ("stale_rollback", v2), stale
        restored = j.admin_call(
            "post-rollback-1",
            "POST",
            "/releases/1/rollback",
            expect=200,
            json={"lock_version": lock, "release_note": "Roll back to Graph Version 1."},
        )
    release = restored["release"]
    assert (
        release["release_id"],
        release["version_number"],
        release["previous_release_id"],
        release["restored_from_release_id"],
    ) == (4, 3, j.state["v2_id"], j.state["v1_id"]), release
    assert restored["restored_from"] == v1
    assert restored["previous_release_id"] == j.state["v2_id"]
    assert restored["changed_agents"] == CHANGED_ROLES
    assert list(restored["mappings"]) == list(GRAPH_V1_AGENT_KEYS)
    assert {
        key: (m["reused"], m["agent_definition_revision_id"])
        for key, m in restored["mappings"].items()
    } == {key: (True, j.state["v1_mappings"][key]) for key in GRAPH_V1_AGENT_KEYS}
    # C19: v1 is the bootstrap release; it has no linked runs, so nothing is copied.
    assert restored["evidence"] == [], restored["evidence"]
    assert restored["draft_effect"] == preview["draft_effect"]
    _set_lock(j, restored)
    j.state["v3_id"] = 4

    # C35: one ``graph_release_rollback`` record per call, outcome and role keys only.
    rollback_records = [r for r in records if r.getMessage() == "graph_release_rollback"]
    assert [_extras(r) for r in rollback_records] == [
        {"outcome": "stale", "agent_keys": []},
        {"outcome": "restored", "agent_keys": CHANGED_ROLES},
    ], [_extras(r) for r in rollback_records]

    after = j.read_workbench("workbench-after-rollback")
    assert (after["active_release"]["release_id"], after["draft"]["base_release_id"]) == (4, 4)
    assert [node["changed"] for node in after["nodes"]] == [False] * 8


def _s16_post_rollback_pins(j: LifecycleJourney) -> None:
    s15 = STAGES["S15"]
    require(s15, j.state.get("v3_id") == 4, f"v3 id is {j.state.get('v3_id')!r}, not 4")
    body = j.call(
        "post-post-rollback-root",
        "POST",
        "/api/sessions",
        principal=OWNER,
        expect=200,
        json={"session_id": "post-rollback-root", "graph_capable": True},
    )
    assert (body["graph_version"], body["active_graph_version"], body["is_older_than_active"]) == (
        3,
        3,
        False,
    ), body
    assert j.pin_of("post-rollback-root") == j.state["v3_id"]

    new_root = j.call("get-new-root", "GET", "/api/sessions/new-root", principal=OWNER, expect=200)
    assert (
        new_root["graph_version"],
        new_root["active_graph_version"],
        new_root["is_older_than_active"],
    ) == (2, 3, True), new_root
    old_root = j.call("get-old-root", "GET", "/api/sessions/old-root", principal=OWNER, expect=200)
    assert (old_root["graph_version"], old_root["is_older_than_active"]) == (1, True), old_root
    assert j.pins() == {
        "old-root": 1,
        "control-legacy": None,
        "mid-root": 1,
        "new-root": 3,
        j.state["contributor_id"]: 3,
        j.state["duplicate_id"]: 3,
        "post-rollback-root": 4,
    }


def _s18_closing(j: LifecycleJourney) -> None:
    s16 = STAGES["S16"]
    require(s16, j.pin_of("post-rollback-root") == 4, "post-rollback-root is not on v3")
    with j.factory() as db:
        rows = list(db.scalars(select(GraphRelease).order_by(GraphRelease.id)))
        intervals = [(r.id, r.version_number, r.effective_from, r.effective_to) for r in rows]
    assert [(i, v, to is None) for i, v, _, to in intervals] == [
        (1, 1, False),
        (3, 2, False),
        (4, 3, True),
    ], intervals
    assert intervals[0][3] == intervals[1][2], "v1.to != v2.from"
    assert intervals[1][3] == intervals[2][2], "v2.to != v3.from"
    assert j.tripwire.reads == []


_STAGE_BODIES: dict[str, Callable[[LifecycleJourney], None]] = {
    "S01": _s01_bootstrap,
    "S02": _s02_old_conversation,
    "S03": _s03_edit,
    "S04": _s04_overlay,
    "S05": _s05_assembly,
    "S06": _s06_endpoint,
    "S07": _s07_test,
    "S08": _s08_approve,
    "S09": _s09_readiness,
    "S10": _s10_preview,
    "S11": _s11_publish,
    "S12": _s12_pinned,
    "S12b": _s12b_collaboration_history,
    "S14": _s14_history,
    "S15": _s15_rollback,
    "S16": _s16_post_rollback_pins,
    "S18": _s18_closing,
}
assert list(_STAGE_BODIES) == list(STAGES)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _fake_catalog() -> FakeModelEndpointCatalog:
    return FakeModelEndpointCatalog(
        discovery_outcomes=[
            SystemModelDiscovery(
                (
                    SystemModelEndpoint(OPUS, "Claude Opus 4.6", None, None),
                    SystemModelEndpoint(SONNET, "Claude Sonnet 4.5", None, None),
                )
            )
        ]
    )


def open_journey(
    factory: sessionmaker,
    client: TestClient,
    adapter: DeterministicFakeModelAdapter,
    monkeypatch,
    stack: contextlib.ExitStack,
) -> LifecycleJourney:
    """Extend ``acceptance_stack``'s app into the journey's harness, then arm the tripwire."""
    app = client.app
    app.include_router(sessions_routes.router)
    app.dependency_overrides[agent_definition_routes.get_model_endpoint_catalog] = _fake_catalog
    workbench = app.dependency_overrides[agent_definition_routes.get_agent_test_workbench]()

    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda user: user == ADMIN)
    _authz.reset_admin_cache()
    stack.enter_context(_session_manager_on(factory))
    import src.api.services.session_manager as session_manager_module

    # C50: the sessions routes' lazy ``from src.core.database import get_db_session``.
    monkeypatch.setattr("src.core.database.get_db_session", session_manager_module.get_db_session)
    monkeypatch.setattr(sessions_routes, "record_deck_retrieved", lambda *_args: None)
    stack.callback(set_permission_context, None)

    tripwire = CodeDefaultTripwire()
    tripwire.arm(monkeypatch)
    return LifecycleJourney(
        factory=factory,
        admin=client,
        user=client,
        adapter=adapter,
        tripwire=tripwire,
        workbench=workbench,
    )


@pytest.fixture
def lifecycle_journey(acceptance_stack, monkeypatch) -> Iterator[LifecycleJourney]:
    """A fresh journey over ``acceptance_stack``; call ``run_to(code)`` to drive it."""
    factory, client, adapter = acceptance_stack
    with contextlib.ExitStack() as stack:
        yield open_journey(factory, client, adapter, monkeypatch, stack)


# ---------------------------------------------------------------------------
# The recorded contract (Task 10, AC9): the journey's exchanges as the fixture the
# admin Playwright journey replays.  Additive: nothing above calls this.
# ---------------------------------------------------------------------------

CONTRACT_VERSION = 1
CONTRACT_PATH = Path(__file__).resolve().parents[2] / (
    "frontend/tests/fixtures/graphLifecycleContract.json"
)
CONTRACT_EXCHANGE_KEYS = (
    "id",
    "method",
    "path",
    "request",
    "status",
    "body",
    "response_model",
    "request_model",
)

#: Routes that read their body by hand (strict ``model_validate``), so FastAPI does
#: not know their request model.  Keyed by endpoint function name.
_MANUAL_REQUEST_MODELS: dict[str, str] = {
    "save_agent_definition_draft": "src.api.schemas.agent_definitions.DraftSaveRequest",
    "upgrade_agent_definition_protected_assembly": (
        "src.api.schemas.agent_definitions.DraftLockRequest"
    ),
    "upgrade_agent_definition_schema_contract": (
        "src.api.schemas.agent_definitions.DraftLockRequest"
    ),
    "execute_agent_candidate_test_run": (
        "src.api.schemas.agent_definitions.CandidateTestRunRequest"
    ),
    "record_agent_test_run_verdict": "src.api.schemas.agent_definitions.VerdictRequest",
    "publish_graph_release": "src.api.schemas.graph_releases.PublishReleaseRequest",
    "rollback_graph_release": "src.api.schemas.graph_release_history.RollbackRequest",
}
#: Statuses a route returns through a hand-built ``JSONResponse`` without declaring
#: them in ``responses=`` (``_conflict_response``'s 409).
_UNDECLARED_RESPONSE_MODELS: dict[tuple[str, int], str] = {
    ("save_agent_definition_draft", 409): (
        "src.api.schemas.agent_definitions.DraftSaveConflictResponse"
    ),
}


def _dotted(model: Any) -> str:
    return f"{model.__module__}.{model.__qualname__}"


def _route_for(method: str, path: str):
    from fastapi.routing import APIRoute
    from starlette.routing import Match

    scope = {"type": "http", "method": method, "path": path.split("?", 1)[0]}
    routes = [*agent_definition_routes.router.routes, *sessions_routes.router.routes]
    for route in routes:
        if isinstance(route, APIRoute) and route.matches(scope)[0] is Match.FULL:
            return route
    raise LookupError(f"no shipped route serves {method} {path}")


def _union_member_for(model: Any, body: Any) -> Any:
    """The member of a declared ``A | B`` response whose ``code`` literal is the body's."""
    members = typing.get_args(model)
    if not members:
        return model
    code = body.get("code") if isinstance(body, dict) else None
    matches = [
        member
        for member in members
        if code in typing.get_args(member.model_fields["code"].annotation)
    ]
    assert len(matches) == 1, (model, code)
    return matches[0]


def exchange_models(
    method: str, path: str, status: int, request: Any, body: Any
) -> tuple[str | None, str | None]:
    """``(response_model, request_model)`` dotted paths the SHIPPED route uses.

    ``None`` means that side has no model: the sessions routes' plain dicts (C21),
    FastAPI's ``{"detail": ...}`` errors, and an exchange that sent no body.
    """
    route = _route_for(method, path)
    name = route.endpoint.__name__
    if request is None:
        request_model: str | None = None
    elif name in _MANUAL_REQUEST_MODELS:
        request_model = _MANUAL_REQUEST_MODELS[name]
    elif route.body_field is not None:
        request_model = _dotted(route.body_field.type_)
    else:
        request_model = None

    success = route.status_code or 200
    if status == success:
        response = route.response_model
    elif (name, status) in _UNDECLARED_RESPONSE_MODELS:
        return _UNDECLARED_RESPONSE_MODELS[(name, status)], request_model
    else:
        declared = (route.responses or {}).get(status) or {}
        response = declared.get("model")
    if response is None:
        return None, request_model
    return _dotted(_union_member_for(response, body)), request_model


def build_contract(exchanges: list[RecordedExchange], recorded_at_commit: str) -> dict:
    """The contract document for ``exchanges``, in recording (stage) order."""
    rows = []
    for exchange in exchanges:
        response_model, request_model = exchange_models(
            exchange.method, exchange.path, exchange.status, exchange.request, exchange.body
        )
        row = {
            "id": exchange.id,
            "method": exchange.method,
            "path": exchange.path,
            "request": exchange.request,
            "status": exchange.status,
            "body": exchange.body,
            "response_model": response_model,
            "request_model": request_model,
        }
        assert tuple(row) == CONTRACT_EXCHANGE_KEYS
        rows.append(row)
    return {
        "contract_version": CONTRACT_VERSION,
        "recorded_at_commit": recorded_at_commit,
        "exchanges": rows,
    }


def _value_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _value_shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_value_shape(item) for item in value]
    return type(value).__name__


def contract_shape(contract: dict) -> list[tuple]:
    """Ids, methods, statuses, models and the recursive key structure; no values.

    Ids (session tokens, run ids) and timestamps are values, so two recordings of the
    same backend have the same shape.  Scalars become their JSON type name.
    """
    return [
        (
            row["id"],
            row["method"],
            row["status"],
            row["response_model"],
            row["request_model"],
            _value_shape(row["request"]),
            _value_shape(row["body"]),
        )
        for row in contract["exchanges"]
    ]


def _head_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=CONTRACT_PATH.parents[3],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class _ContractRecorder:
    """A pytest plugin: keeps the journey's exchanges once its test has passed."""

    def __init__(self) -> None:
        self.exchanges: list[RecordedExchange] | None = None

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item):
        result = yield  # re-raises when the journey failed, so nothing is kept
        journey = item.funcargs.get("lifecycle_journey")
        if isinstance(journey, LifecycleJourney) and journey.completed == list(STAGES):
            self.exchanges = list(journey.exchanges)
        return result


def write_contract(path: Path | str) -> int:
    """Run the Task 6 journey on a throwaway PostgreSQL database; write its contract.

    A developer command (``python -m tests.integration.graph_lifecycle_journey
    --write-contract <path>``), never run by a test.  It drives the journey test
    itself, so a recording exists only for a journey whose every stage passed.
    Returns a process exit code.
    """
    test = (
        CONTRACT_PATH.parents[3] / "tests/integration/test_graph_lifecycle_acceptance_postgres.py"
    )
    recorder = _ContractRecorder()
    code = pytest.main(
        [
            f"{test}::test_edit_test_approve_preview_publish_pin_rollback_lifecycle",
            "-q",
            "-p",
            "no:cacheprovider",
            "-rs",
        ],
        plugins=[recorder],
    )
    if code != 0 or recorder.exchanges is None:
        print(f"journey did not pass (pytest exit {code}); nothing written", file=sys.stderr)
        return int(code) or 1
    contract = build_contract(recorder.exchanges, _head_commit())
    Path(path).write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(contract['exchanges'])} exchanges to {path}")
    return 0


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m tests.integration.graph_lifecycle_journey")
    parser.add_argument("--write-contract", metavar="PATH", required=True, type=Path)
    return write_contract(parser.parse_args(argv).write_contract)


if __name__ == "__main__":
    # Run the importable module's copy, not ``__main__``'s: the journey test imports
    # ``tests.integration.graph_lifecycle_journey``, and the recorder's isinstance
    # check must see that module's ``LifecycleJourney``.
    from tests.integration.graph_lifecycle_journey import _main as _canonical_main

    raise SystemExit(_canonical_main())
