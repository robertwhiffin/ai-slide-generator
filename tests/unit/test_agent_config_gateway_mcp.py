"""Task 3: the ``gateway_mcp`` agent-config tool entry and its save rule.

The entry is ``{"type": "gateway_mcp", "service_name": <catalog.schema.service>,
"display_name": <1-120 chars>}``; duplicates are keyed ``gateway_mcp:<service_name>``.

The save rule (PUT /agent-config and PATCH /agent-config/tools): a ``gateway_mcp``
entry that is NOT already in the stored config is refused with 422
``"gateway connection <service> is not available"`` unless its service is
registered AND enabled. Entries already stored are kept even after their
connection is deleted or disabled (Review Focus 1: the frontend PUTs the whole
config on every change, so a 422 there would wedge every later edit). The
registry is queried only for NEW entries, and not at all when there are none
(T3.2 / C2).

Harness:
  - an in-memory SQLite engine (``StaticPool``) with the full ORM metadata, bound as
    the PROCESS-WIDE engine and session factory (``src.core.database._engine`` /
    ``_session_local``), so every ``get_db_session()`` / ``get_db`` reaches it
    whichever module opens the session; an active ``GraphRelease`` row is seeded
    because the real ``SessionManager.get_session`` requires one;
  - a bare ``FastAPI()`` with only ``agent_config.router``; the deck-permission gate
    is a no-op (authz is covered by ``test_authz_agent_config.py``);
  - registry rows are written with the ``GatewayMcpConnection`` ORM model (Task 2);
  - registry READS are observed two ways, so neither import style escapes:
    spies on ``gateway_mcp_registry.{list_connections,get_by_service,enabled_by_service}``
    (patched on the registry module AND, if bound there, on the route module), and a
    SQLAlchemy ``before_cursor_execute`` listener recording every statement that
    names ``gateway_mcp_connections``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.api.routes import agent_config as agent_config_routes
from src.core.database import Base
from src.database.models import UserSession
from src.database.models.graph_configuration import GraphRelease

REPO_ROOT = Path(__file__).resolve().parents[2]

SID = "sess-gateway"
OWNER = "owner@example.com"
ADMIN = "admin@example.com"

LAKEDRAW = "main.tellr_mcp.lakedraw"
WEB_SEARCH = "system.ai.web_search"
GITHUB = "system.ai.github"

GENIE = {"type": "genie", "space_id": "g1", "space_name": "Sales"}


def _gw(service_name: str, display_name: str = "LakeDraw") -> dict[str, Any]:
    """A ``gateway_mcp`` tool entry exactly as the frontend sends it (and as it is stored)."""
    return {"type": "gateway_mcp", "service_name": service_name, "display_name": display_name}


LAKEDRAW_ENTRY = _gw(LAKEDRAW, "LakeDraw")
WEB_SEARCH_ENTRY = _gw(WEB_SEARCH, "Web search")
GITHUB_ENTRY = _gw(GITHUB, "GitHub")


def _not_available(service_name: str) -> dict[str, str]:
    return {"detail": f"gateway connection {service_name} is not available"}


def _keys(tools: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """The identity of each tool, in order: ``(type, service_name | space_id)``."""
    out = []
    for tool in tools:
        if tool["type"] == "gateway_mcp":
            out.append(("gateway_mcp", tool["service_name"]))
        elif tool["type"] == "genie":
            out.append(("genie", tool["space_id"]))
        else:
            out.append((tool["type"], ""))
    return out


def _gateway_entries(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in tools if t["type"] == "gateway_mcp"]


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def db_factory(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> sessionmaker:
    """The test engine, bound as the process-wide engine and session factory."""
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("src.core.database._engine", engine)
    monkeypatch.setattr("src.core.database._session_local", factory)
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(
            GraphRelease(
                id=300,
                version_number=1,
                release_note="gateway agent-config fixture release",
                published_by=ADMIN,
                published_at=now,
                effective_from=now,
            )
        )
        db.commit()
    return factory


@pytest.fixture
def http(db_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "src.api.routes.agent_config._check_deck_permission_for_session",
        lambda *a, **k: None,
    )
    app = FastAPI()
    app.include_router(agent_config_routes.router)
    return TestClient(app)


def _create_session(factory: sessionmaker, agent_config: dict[str, Any] | None) -> None:
    with factory() as db:
        db.add(UserSession(session_id=SID, created_by=OWNER, agent_config=agent_config))
        db.commit()


def _stored(factory: sessionmaker) -> dict[str, Any] | None:
    with factory() as db:
        return db.query(UserSession).filter_by(session_id=SID).one().agent_config


def _register(
    factory: sessionmaker,
    service_name: str,
    *,
    display_name: str = "LakeDraw",
    enabled: bool = True,
    agent: str = "architect",
) -> None:
    from src.database.models import GatewayMcpConnection

    with factory() as db:
        db.add(
            GatewayMcpConnection(
                service_name=service_name,
                display_name=display_name,
                description=None,
                agent=agent,
                instructions=None,
                tool_allowlist=None,
                enabled=enabled,
                created_by=ADMIN,
                updated_by=ADMIN,
            )
        )
        db.commit()


def _set_enabled(factory: sessionmaker, service_name: str, enabled: bool) -> None:
    from src.database.models import GatewayMcpConnection

    with factory() as db:
        row = db.query(GatewayMcpConnection).filter_by(service_name=service_name).one()
        row.enabled = enabled
        db.commit()


def _unregister(factory: sessionmaker, service_name: str) -> None:
    from src.database.models import GatewayMcpConnection

    with factory() as db:
        assert db.query(GatewayMcpConnection).filter_by(service_name=service_name).delete() == 1
        db.commit()


def _put(http: TestClient, body: dict[str, Any], session_id: str = SID):
    return http.put(f"/api/sessions/{session_id}/agent-config", json=body)


def _patch(http: TestClient, action: str, tool: dict[str, Any]):
    return http.patch(
        f"/api/sessions/{SID}/agent-config/tools", json={"action": action, "tool": tool}
    )


@dataclass
class _RegistryReads:
    """Every registry read the request made.

    ``calls``: ``(function, service names it was asked about)``; ``list_connections``
    is recorded as ``("*",)`` since it reads every row. ``statements``: every SQL
    statement that named the table, with its parameters.
    """

    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    statements: list[tuple[str, Any]] = field(default_factory=list)

    def asked_names(self) -> set[Any]:
        return {name for _, names in self.calls for name in names}

    def clear(self) -> None:
        self.calls.clear()
        self.statements.clear()


_REGISTRY_READERS = ("list_connections", "get_by_service", "enabled_by_service")


def _spy(reads: _RegistryReads, name: str, original: Any) -> Any:
    def spy(*args: Any, **kwargs: Any) -> Any:
        args_list = list(args)
        if name == "enabled_by_service":
            # Materialise the iterable so the original still sees every name.
            if len(args_list) >= 2:
                args_list[1] = list(args_list[1])
                asked = tuple(args_list[1])
            else:
                kwargs["service_names"] = list(kwargs.get("service_names", []))
                asked = tuple(kwargs["service_names"])
        elif name == "get_by_service":
            asked = (args_list[1] if len(args_list) >= 2 else kwargs.get("service_name"),)
        else:
            asked = ("*",)
        reads.calls.append((name, asked))
        return original(*args_list, **kwargs)

    return spy


@pytest.fixture
def registry_reads(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[_RegistryReads]:
    reads = _RegistryReads()

    def _on_execute(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        if "gateway_mcp_connections" in statement:
            reads.statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        from src.services import gateway_mcp_registry as registry
    except ImportError:  # Task 2 not landed: the SQL listener still observes every read
        registry = None
    if registry is not None:
        for name in _REGISTRY_READERS:
            spy = _spy(reads, name, getattr(registry, name))
            monkeypatch.setattr(registry, name, spy)
            # A route that bound the name at import time is spied too.
            if hasattr(agent_config_routes, name):
                monkeypatch.setattr(agent_config_routes, name, spy)
    try:
        yield reads
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


def _no_statement_mentions(reads: _RegistryReads, service_name: str) -> bool:
    return all(service_name not in repr(params) for _, params in reads.statements)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_gateway_entry_round_trips_and_duplicates_rejected() -> None:
    from src.api.schemas.agent_config import (
        AgentConfig,
        GatewayMcpTool,
        sanitize_agent_config_for_persist,
    )

    config = AgentConfig.model_validate({"tools": [LAKEDRAW_ENTRY]})
    assert len(config.tools) == 1
    assert isinstance(config.tools[0], GatewayMcpTool)
    # Exactly the three fields, unchanged, through the persist sanitiser...
    out = sanitize_agent_config_for_persist({"tools": [LAKEDRAW_ENTRY]})
    assert out is not None
    assert out["tools"] == [LAKEDRAW_ENTRY]
    # ...and through a dump/validate cycle.
    assert AgentConfig.model_validate(config.model_dump()).model_dump()["tools"] == [
        LAKEDRAW_ENTRY
    ]

    with pytest.raises(ValidationError, match=f"Duplicate tool: gateway_mcp:{LAKEDRAW}"):
        AgentConfig.model_validate({"tools": [LAKEDRAW_ENTRY, _gw(LAKEDRAW, "LakeDraw copy")]})


def test_gateway_duplicate_key_is_the_normalised_service_name_only() -> None:
    from src.api.schemas.agent_config import AgentConfig

    # Same service after normalisation, different display name: a duplicate.
    with pytest.raises(ValidationError, match=f"Duplicate tool: gateway_mcp:{LAKEDRAW}"):
        AgentConfig.model_validate(
            {"tools": [_gw("Main.Tellr_MCP.LakeDraw", "LakeDraw"), _gw(LAKEDRAW, "Lake Draw")]}
        )
    # Different services, and a UC MCP connection that happens to share the
    # name, are all distinct keys.
    config = AgentConfig.model_validate(
        {
            "tools": [
                LAKEDRAW_ENTRY,
                WEB_SEARCH_ENTRY,
                {"type": "mcp", "connection_name": LAKEDRAW, "server_name": "uc"},
                {"type": "genie_one"},
                GENIE,
            ]
        }
    )
    assert [t.type for t in config.tools] == [
        "gateway_mcp",
        "gateway_mcp",
        "mcp",
        "genie_one",
        "genie",
    ]


def test_gateway_service_name_is_normalised() -> None:
    from src.api.schemas.agent_config import AgentConfig

    config = AgentConfig.model_validate({"tools": [_gw("  Main.Tellr_MCP.LakeDraw  ")]})
    assert config.model_dump()["tools"] == [LAKEDRAW_ENTRY]


@pytest.mark.parametrize(
    "bad_name",
    ["a.b", "a.b.c.d", "a.b/c.d", "../x.y.z", "a b.c.d", "a..c", "", "   ", "main.x.y;drop"],
)
def test_gateway_service_name_is_validated(bad_name: str) -> None:
    from src.api.schemas.agent_config import AgentConfig

    # Positive control: the type exists and a good name validates, so the refusal
    # below is about the NAME, not an unknown tool type.
    AgentConfig.model_validate({"tools": [_gw(LAKEDRAW)]})
    with pytest.raises(ValidationError) as caught:
        AgentConfig.model_validate({"tools": [_gw(bad_name)]})
    # The error is raised inside the gateway_mcp member of the union.
    assert all("gateway_mcp" in err["loc"] for err in caught.value.errors()), caught.value.errors()


def test_gateway_display_name_is_1_to_120_chars() -> None:
    from src.api.schemas.agent_config import AgentConfig

    ok = AgentConfig.model_validate({"tools": [_gw(LAKEDRAW, "x" * 120)]})
    assert ok.model_dump()["tools"][0]["display_name"] == "x" * 120
    for bad in ("", "x" * 121):
        with pytest.raises(ValidationError):
            AgentConfig.model_validate({"tools": [_gw(LAKEDRAW, bad)]})
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(
            {"tools": [{"type": "gateway_mcp", "service_name": LAKEDRAW}]}
        )


def test_schema_module_imports_no_services_package() -> None:
    """C1: ``src.api.schemas.agent_config`` must not import ``src.services`` (circular:
    services/__init__ -> agent -> tools -> agent_bricks_tool -> agent_config). It takes
    ``validate_service_name`` from ``src.domain.gateway_service_name``. Run in a fresh
    interpreter so no earlier test's imports hide the problem."""
    probe = (
        "import json, sys\n"
        "import src.api.schemas.agent_config as m\n"
        "print(json.dumps({\n"
        "    'has_gateway_tool': hasattr(m, 'GatewayMcpTool'),\n"
        "    'services': sorted(n for n in sys.modules\n"
        "                       if n == 'src.services' or n.startswith('src.services.')),\n"
        "    'domain_validator': 'src.domain.gateway_service_name' in sys.modules,\n"
        "}))\n"
    )
    env = {**os.environ, "ENVIRONMENT": "test"}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == {"has_gateway_tool": True, "services": [], "domain_validator": True}


# ---------------------------------------------------------------------------
# PUT /api/sessions/{id}/agent-config
# ---------------------------------------------------------------------------


def test_put_rejects_new_unregistered_gateway_entry_422(
    http: TestClient, db_factory: sessionmaker
) -> None:
    stored = {"tools": [GENIE]}
    _create_session(db_factory, stored)
    _register(db_factory, WEB_SEARCH, display_name="Web search")  # some OTHER service is registered
    before = _stored(db_factory)

    response = _put(http, {"tools": [GENIE, LAKEDRAW_ENTRY]})

    assert response.status_code == 422, response.text
    assert response.json() == _not_available(LAKEDRAW)
    assert _stored(db_factory) == before


def test_put_rejects_new_disabled_gateway_entry_422(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _create_session(db_factory, {"tools": []})
    _register(db_factory, LAKEDRAW, enabled=False)
    before = _stored(db_factory)

    response = _put(http, {"tools": [LAKEDRAW_ENTRY]})

    assert response.status_code == 422, response.text
    assert response.json() == _not_available(LAKEDRAW)
    assert _stored(db_factory) == before


def test_put_accepts_new_registered_enabled_entry(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _create_session(db_factory, None)
    _register(db_factory, LAKEDRAW)

    response = _put(http, {"tools": [LAKEDRAW_ENTRY]})

    assert response.status_code == 200, response.text
    assert response.json()["tools"] == [LAKEDRAW_ENTRY]
    assert _stored(db_factory)["tools"] == [LAKEDRAW_ENTRY]


def test_put_normalises_the_service_name_before_the_registry_check(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _create_session(db_factory, {"tools": []})
    _register(db_factory, LAKEDRAW)

    response = _put(http, {"tools": [_gw(" Main.Tellr_MCP.LakeDraw ")]})

    assert response.status_code == 200, response.text
    assert _stored(db_factory)["tools"] == [LAKEDRAW_ENTRY]


def test_put_keeps_already_stored_entry_after_connection_deleted(
    http: TestClient, db_factory: sessionmaker
) -> None:
    """Review Focus 1: an admin deletes a connection a deck still has; the deck's
    config must stay saveable (the frontend PUTs the whole config on every edit)."""
    _create_session(db_factory, {"tools": []})
    _register(db_factory, LAKEDRAW)
    assert _put(http, {"tools": [LAKEDRAW_ENTRY]}).status_code == 200
    _unregister(db_factory, LAKEDRAW)

    # The same config plus an unrelated change.
    response = _put(http, {"tools": [LAKEDRAW_ENTRY, GENIE], "style_source": "user"})

    assert response.status_code == 200, response.text
    assert _keys(response.json()["tools"]) == [("gateway_mcp", LAKEDRAW), ("genie", "g1")]
    stored = _stored(db_factory)
    assert _keys(stored["tools"]) == [("gateway_mcp", LAKEDRAW), ("genie", "g1")]
    assert _gateway_entries(stored["tools"]) == [LAKEDRAW_ENTRY]
    assert stored["style_source"] == "user"


def test_put_keeps_already_stored_entry_after_connection_disabled(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _create_session(db_factory, {"tools": []})
    _register(db_factory, LAKEDRAW)
    assert _put(http, {"tools": [LAKEDRAW_ENTRY]}).status_code == 200
    _set_enabled(db_factory, LAKEDRAW, False)

    response = _put(http, {"tools": [GENIE, LAKEDRAW_ENTRY], "style_source": "user"})

    assert response.status_code == 200, response.text
    stored = _stored(db_factory)
    assert _keys(stored["tools"]) == [("genie", "g1"), ("gateway_mcp", LAKEDRAW)]
    assert stored["style_source"] == "user"


def test_put_treats_a_stored_service_as_stored_whatever_its_display_name(
    http: TestClient, db_factory: sessionmaker
) -> None:
    """"Already stored" is keyed by service name: a stored entry re-sent with a
    different display name is not NEW, so a gone connection does not 422 it."""
    _create_session(db_factory, {"tools": [LAKEDRAW_ENTRY]})  # LakeDraw is not registered

    response = _put(http, {"tools": [_gw(LAKEDRAW, "LakeDraw (legacy)")]})

    assert response.status_code == 200, response.text
    assert _stored(db_factory)["tools"] == [_gw(LAKEDRAW, "LakeDraw (legacy)")]


def test_put_with_only_stored_gateway_entries_does_not_read_the_registry(
    http: TestClient, db_factory: sessionmaker, registry_reads: _RegistryReads
) -> None:
    """T3.2: nothing is NEW, so the registry is not read at all (both stored
    connections are gone, so any lookup that mattered would also have refused)."""
    _create_session(db_factory, {"tools": [LAKEDRAW_ENTRY, WEB_SEARCH_ENTRY]})
    registry_reads.clear()

    response = _put(
        http, {"tools": [WEB_SEARCH_ENTRY, LAKEDRAW_ENTRY, GENIE], "style_source": "user"}
    )

    assert response.status_code == 200, response.text
    assert _keys(_stored(db_factory)["tools"]) == [
        ("gateway_mcp", WEB_SEARCH),
        ("gateway_mcp", LAKEDRAW),
        ("genie", "g1"),
    ]
    assert registry_reads.calls == []
    assert registry_reads.statements == []


def test_put_checks_only_new_entries_against_the_registry(
    http: TestClient, db_factory: sessionmaker, registry_reads: _RegistryReads
) -> None:
    """T3.2: stored LakeDraw (connection since deleted) is never looked up; a NEW
    entry is, and is refused or accepted on its own registry row."""
    _create_session(db_factory, {"tools": [LAKEDRAW_ENTRY]})  # LakeDraw is not registered
    before = _stored(db_factory)

    refused = _put(http, {"tools": [LAKEDRAW_ENTRY, GITHUB_ENTRY]})

    assert refused.status_code == 422, refused.text
    assert refused.json() == _not_available(GITHUB)
    assert _stored(db_factory) == before

    _register(db_factory, WEB_SEARCH, display_name="Web search")
    registry_reads.clear()

    accepted = _put(http, {"tools": [LAKEDRAW_ENTRY, WEB_SEARCH_ENTRY]})

    assert accepted.status_code == 200, accepted.text
    assert _stored(db_factory)["tools"] == [LAKEDRAW_ENTRY, WEB_SEARCH_ENTRY]
    assert registry_reads.statements, "the NEW entry must be checked against the registry"
    assert LAKEDRAW not in registry_reads.asked_names()
    assert _no_statement_mentions(registry_reads, LAKEDRAW)


def test_put_without_gateway_entries_never_reads_the_registry(
    http: TestClient, db_factory: sessionmaker, registry_reads: _RegistryReads
) -> None:
    """C2 / T3.2: a config with no gateway_mcp entry saves exactly as before,
    without touching the registry, even when it drops a stored gateway entry."""
    _create_session(db_factory, {"tools": [LAKEDRAW_ENTRY]})
    _register(db_factory, LAKEDRAW)
    registry_reads.clear()

    response = _put(http, {"tools": [GENIE], "style_source": "user"})

    assert response.status_code == 200, response.text
    assert _keys(_stored(db_factory)["tools"]) == [("genie", "g1")]
    assert registry_reads.calls == []
    assert registry_reads.statements == []


def test_put_gateway_entry_to_missing_session_is_404(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _register(db_factory, LAKEDRAW)

    response = _put(http, {"tools": [LAKEDRAW_ENTRY]}, session_id="no-such-session")

    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# PATCH /api/sessions/{id}/agent-config/tools
# ---------------------------------------------------------------------------


def test_patch_add_new_unregistered_gateway_entry_422(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _create_session(db_factory, None)
    _register(db_factory, WEB_SEARCH, display_name="Web search")

    response = _patch(http, "add", LAKEDRAW_ENTRY)

    assert response.status_code == 422, response.text
    assert response.json() == _not_available(LAKEDRAW)
    assert _stored(db_factory) is None


def test_patch_add_disabled_gateway_entry_422(http: TestClient, db_factory: sessionmaker) -> None:
    _create_session(db_factory, {"tools": [GENIE]})
    _register(db_factory, LAKEDRAW, enabled=False)
    before = _stored(db_factory)

    response = _patch(http, "add", LAKEDRAW_ENTRY)

    assert response.status_code == 422, response.text
    assert response.json() == _not_available(LAKEDRAW)
    assert _stored(db_factory) == before


def test_patch_add_registered_gateway_entry(http: TestClient, db_factory: sessionmaker) -> None:
    _create_session(db_factory, {"tools": [GENIE]})
    _register(db_factory, LAKEDRAW)

    response = _patch(http, "add", LAKEDRAW_ENTRY)

    assert response.status_code == 200, response.text
    assert _keys(response.json()["tools"]) == [("genie", "g1"), ("gateway_mcp", LAKEDRAW)]
    stored = _stored(db_factory)
    assert _keys(stored["tools"]) == [("genie", "g1"), ("gateway_mcp", LAKEDRAW)]
    assert _gateway_entries(stored["tools"]) == [LAKEDRAW_ENTRY]


def test_patch_add_an_already_stored_gateway_entry_is_a_duplicate_422(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _create_session(db_factory, {"tools": [LAKEDRAW_ENTRY]})  # LakeDraw is not registered
    before = _stored(db_factory)

    response = _patch(http, "add", LAKEDRAW_ENTRY)

    assert response.status_code == 422, response.text
    assert f"Duplicate tool: gateway_mcp:{LAKEDRAW}" in response.json()["detail"]
    assert _stored(db_factory) == before


def test_patch_remove_gateway_entry_by_key(http: TestClient, db_factory: sessionmaker) -> None:
    """T3.3: TWO gateway entries; removing one leaves the other. A ``_key`` that
    returns None for gateway entries would remove both (None == None)."""
    _create_session(db_factory, {"tools": [LAKEDRAW_ENTRY, WEB_SEARCH_ENTRY, GENIE]})
    # Neither connection is registered: removal must not depend on the registry.

    # Keyed by service name: a stale display name still matches.
    response = _patch(http, "remove", _gw(LAKEDRAW, "Renamed since"))

    assert response.status_code == 200, response.text
    assert _keys(response.json()["tools"]) == [("gateway_mcp", WEB_SEARCH), ("genie", "g1")]
    stored = _stored(db_factory)
    assert _keys(stored["tools"]) == [("gateway_mcp", WEB_SEARCH), ("genie", "g1")]
    assert _gateway_entries(stored["tools"]) == [WEB_SEARCH_ENTRY]

    response = _patch(http, "remove", WEB_SEARCH_ENTRY)

    assert response.status_code == 200, response.text
    assert _keys(_stored(db_factory)["tools"]) == [("genie", "g1")]


def test_patch_add_other_tool_keeps_stored_gateway_entry_without_reading_the_registry(
    http: TestClient, db_factory: sessionmaker, registry_reads: _RegistryReads
) -> None:
    _create_session(db_factory, {"tools": [LAKEDRAW_ENTRY]})  # LakeDraw is not registered
    registry_reads.clear()

    response = _patch(http, "add", GENIE)

    assert response.status_code == 200, response.text
    assert _keys(_stored(db_factory)["tools"]) == [("gateway_mcp", LAKEDRAW), ("genie", "g1")]
    assert registry_reads.calls == []
    assert registry_reads.statements == []


def test_patch_without_gateway_entries_never_reads_the_registry(
    http: TestClient, db_factory: sessionmaker, registry_reads: _RegistryReads
) -> None:
    _create_session(db_factory, {"tools": []})
    _register(db_factory, LAKEDRAW)
    registry_reads.clear()

    response = _patch(http, "add", GENIE)

    assert response.status_code == 200, response.text
    assert _keys(_stored(db_factory)["tools"]) == [("genie", "g1")]
    assert registry_reads.calls == []
    assert registry_reads.statements == []


# ---------------------------------------------------------------------------
# Legacy mode
# ---------------------------------------------------------------------------


def test_legacy_build_tools_ignores_gateway_entry() -> None:
    """Legacy mode ignores gateway_mcp: no tool, no error, and the UC MCP builder is
    never handed the entry. (A guard: ``_build_tools`` has no ``else``, so this
    assertion cannot fail before the implementation; T3.4.)"""
    from src.api.schemas.agent_config import AgentConfig
    from src.services import agent_resolution

    def _fake_genie_tool(entry, session_data, idx):  # noqa: ANN001, ANN202
        fake = MagicMock()
        fake.name = f"query_genie_space_{idx}"
        return fake

    def _no_uc_mcp(entry):  # noqa: ANN001, ANN202
        raise AssertionError(f"a gateway_mcp entry reached the UC MCP builder: {entry!r}")

    with (
        patch.object(agent_resolution, "build_genie_tool", side_effect=_fake_genie_tool),
        patch.object(agent_resolution, "build_mcp_tools", side_effect=_no_uc_mcp),
    ):
        without = agent_resolution._build_tools(
            AgentConfig.model_validate({"tools": [GENIE]}), {"session_id": "s1"}
        )
        with_gateway = agent_resolution._build_tools(
            AgentConfig.model_validate({"tools": [LAKEDRAW_ENTRY, GENIE, WEB_SEARCH_ENTRY]}),
            {"session_id": "s1"},
        )

    assert [t.name for t in with_gateway] == [t.name for t in without]
    assert "query_genie_space_1" in [t.name for t in without]
