"""Task 2: the ``gateway_mcp_connections`` table on real PostgreSQL.

``init_db()`` builds the global engine, so the first test points
``src.core.database.get_engine`` at the ``postgres_engine`` fixture's engine and
calls the real ``init_db()`` (T2.3). Idempotence re-runs the production ordering,
``Base.metadata.create_all`` then ``_run_migrations``, twice.

Self-skips when no PostgreSQL is reachable (``postgres_engine``).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import src.core.database as database
from src.core.database import Base, _run_migrations
from src.database.models import GatewayMcpConnection
from src.services import gateway_mcp_registry as registry

pytestmark = pytest.mark.postgres

TABLE = "gateway_mcp_connections"
LAKEDRAW = "db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw"
ADMIN = "admin@example.com"

EXPECTED_COLUMNS = {
    "id",
    "service_name",
    "display_name",
    "description",
    "agent",
    "instructions",
    "tool_allowlist",
    "enabled",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
}


def _columns(engine) -> dict[str, Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t"
            ),
            {"t": TABLE},
        ).all()
    return {name: (nullable, length) for name, nullable, length in rows}


def _schema_shape(engine) -> tuple:
    """Columns, indexes and unique constraints: what a second run must not change."""
    inspector = inspect(engine)
    return (
        sorted((c["name"], str(c["type"]), c["nullable"]) for c in inspector.get_columns(TABLE)),
        sorted(
            (i["name"], tuple(i["column_names"]), bool(i["unique"]))
            for i in inspector.get_indexes(TABLE)
        ),
        sorted(
            (u["name"], tuple(u["column_names"])) for u in inspector.get_unique_constraints(TABLE)
        ),
    )


def _orm_row(
    service_name: str, display_name: str, agent: str = "architect"
) -> GatewayMcpConnection:
    return GatewayMcpConnection(
        service_name=service_name,
        display_name=display_name,
        agent=agent,
        enabled=True,
        created_by=ADMIN,
        updated_by=ADMIN,
    )


def _create(db, service_name: str, **overrides: Any) -> registry.GatewayConnection:
    kwargs: dict[str, Any] = {
        "service_name": service_name,
        "display_name": "LakeDraw",
        "description": None,
        "agent": "architect",
        "instructions": None,
        "tool_allowlist": None,
        "enabled": True,
        "user": ADMIN,
    }
    kwargs.update(overrides)
    return registry.create_connection(db, **kwargs)


def test_table_created_by_init_db_and_unique_service(postgres_engine, monkeypatch) -> None:
    with postgres_engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{TABLE}"'))
    assert TABLE not in inspect(postgres_engine).get_table_names()
    monkeypatch.delenv("LAKEBASE_SCHEMA", raising=False)
    monkeypatch.setattr(database, "get_engine", lambda: postgres_engine)

    database.init_db()

    assert TABLE in inspect(postgres_engine).get_table_names()
    columns = _columns(postgres_engine)
    assert set(columns) == EXPECTED_COLUMNS
    assert columns["service_name"] == ("NO", 255)
    assert columns["display_name"] == ("NO", 120)
    assert columns["agent"] == ("NO", 32)
    assert columns["enabled"][0] == "NO"
    for nullable in ("description", "instructions", "tool_allowlist"):
        assert columns[nullable][0] == "YES", nullable

    factory = sessionmaker(bind=postgres_engine)
    with factory() as s:
        s.add(_orm_row(LAKEDRAW, "LakeDraw"))
        s.commit()
    with factory() as s:
        s.add(_orm_row(LAKEDRAW, "LakeDraw again", agent="data_analyst"))
        with pytest.raises(IntegrityError):
            s.commit()
    with factory() as s:
        assert s.scalars(select(GatewayMcpConnection.display_name)).all() == ["LakeDraw"]


def test_init_db_twice_is_idempotent(postgres_engine) -> None:
    factory = sessionmaker(bind=postgres_engine)
    with factory() as db:
        _create(db, LAKEDRAW, tool_allowlist=["draw", "render"], instructions="Diagrams only.")
        db.commit()
    shape_before = _schema_shape(postgres_engine)

    for _ in range(2):
        Base.metadata.create_all(bind=postgres_engine)
        _run_migrations(postgres_engine)

    assert _schema_shape(postgres_engine) == shape_before
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(GatewayMcpConnection)) == 1
        kept = registry.get_by_service(db, LAKEDRAW)
        assert kept is not None
        assert kept.tool_allowlist == ("draw", "render")
        assert kept.instructions == "Diagrams only."


def test_a_none_allowlist_is_stored_as_sql_null_and_a_list_as_json(postgres_engine) -> None:
    """``None`` means "every tool": it must be SQL NULL (so ``IS NULL`` finds it), not
    the JSON ``'null'`` literal a plain JSON column binds; a list stays a JSON array."""
    factory = sessionmaker(bind=postgres_engine)
    edit = {
        "display_name": "LakeDraw",
        "description": None,
        "agent": "architect",
        "instructions": None,
        "enabled": True,
        "user": ADMIN,
    }
    with factory() as db:
        _create(db, "main.a.none", tool_allowlist=None)
        listed = _create(db, "main.b.list", tool_allowlist=["draw"])
        cleared = _create(db, "main.c.cleared", tool_allowlist=["draw"])
        registry.update_connection(db, cleared.id, tool_allowlist=None, **edit)

    with postgres_engine.connect() as conn:
        stored = conn.execute(
            text(
                f'SELECT service_name, tool_allowlist IS NULL, tool_allowlist::text FROM "{TABLE}" '
                "ORDER BY service_name"
            )
        ).all()
    assert stored == [
        ("main.a.none", True, None),
        ("main.b.list", False, '["draw"]'),
        ("main.c.cleared", True, None),
    ]
    with factory() as db:
        assert {c.service_name: c.tool_allowlist for c in registry.list_connections(db)} == {
            "main.a.none": None,
            "main.b.list": ("draw",),
            "main.c.cleared": None,
        }
    assert listed.tool_allowlist == ("draw",)


def test_registry_maps_a_postgres_duplicate_to_duplicate_service_error(postgres_engine) -> None:
    factory = sessionmaker(bind=postgres_engine)
    with factory() as db:
        _create(db, LAKEDRAW, display_name="LakeDraw")
        db.commit()

    with factory() as db:
        with pytest.raises(registry.DuplicateServiceError):
            _create(db, LAKEDRAW, display_name="Copy", agent="data_analyst")

    with factory() as db:
        rows = registry.list_connections(db)
        assert [(c.service_name, c.display_name, c.agent) for c in rows] == [
            (LAKEDRAW, "LakeDraw", "architect")
        ]
        assert set(registry.enabled_by_service(db, [LAKEDRAW])) == {LAKEDRAW}
