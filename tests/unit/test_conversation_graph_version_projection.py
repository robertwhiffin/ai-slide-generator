"""AC6: conversation endpoints expose Graph Version projection only (#271).

Asserts two things:

1.  The union of all JSON keys (recursively) across the six conversation
    endpoints contains ``graph_version``, ``active_graph_version`` and
    ``is_older_than_active``.  The first three come from create/get/list
    session responses; ``graph_version`` also appears in the
    ``CollaborationHistoryResponse`` group model.

2.  No response from any of the six endpoints exposes release-internal keys:
    ``graph_release_id``, ``agent_definition_revision_id``, ``content_hash``,
    ``prompt_text``, ``endpoint_name``, ``schema_overlay``, ``assembly_rules``,
    ``release_note``, ``published_by``.

Probes the actual response models where they exist
(``CollaborationHistoryResponse`` / ``CollaborationReleaseGroupResponse``)
and the plain-dict returns from the remaining ``SessionManager`` methods, per
Task 0-B's re-probe of #262 (C35).  The exact field names match C35: plain-
dict projection keys are ``session_manager.py:752-754, 787-789, 846-848,
1058-1060``; the history model field is
``CollaborationReleaseGroupResponse.graph_version``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — register ORM tables before create_all
from src.api.routes.sessions import (
    CollaborationHistoryResponse,
    CollaborationReleaseGroupResponse,
)
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import SessionSlideDeck, UserSession
from src.services.conversation_pins import PinnedRelease
from src.services.graph_configuration import GraphConfiguration

# ---------------------------------------------------------------------------
# AC6 key sets.
# ---------------------------------------------------------------------------

REQUIRED_PROJECTION_KEYS: frozenset[str] = frozenset(
    {"graph_version", "active_graph_version", "is_older_than_active"}
)
FORBIDDEN_RELEASE_KEYS: frozenset[str] = frozenset(
    {
        "graph_release_id",
        "agent_definition_revision_id",
        "content_hash",
        "prompt_text",
        "endpoint_name",
        "schema_overlay",
        "assembly_rules",
        "release_note",
        "published_by",
    }
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _all_keys(value: Any) -> set[str]:
    """Recursively collect every dict key from a JSON-shaped value."""
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value.keys())
        for v in value.values():
            keys |= _all_keys(v)
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys |= _all_keys(item)
    return keys


def _pydantic_all_field_names(model_class: type, _seen: set | None = None) -> set[str]:
    """Return all field names from a Pydantic model, recursing into nested models."""
    import typing

    import pydantic

    if _seen is None:
        _seen = set()
    if model_class in _seen:
        return set()
    _seen.add(model_class)

    names: set[str] = set()
    for fname, field in model_class.model_fields.items():
        names.add(fname)
        annotation = field.annotation
        # Unwrap list[X], List[X].
        origin = getattr(annotation, "__origin__", None)
        if origin is list:
            for arg in getattr(annotation, "__args__", ()):
                if isinstance(arg, type) and issubclass(arg, pydantic.BaseModel):
                    names |= _pydantic_all_field_names(arg, _seen)
        # Unwrap Optional[X] = Union[X, None].
        elif origin is typing.Union:
            for arg in getattr(annotation, "__args__", ()):
                if isinstance(arg, type) and issubclass(arg, pydantic.BaseModel):
                    names |= _pydantic_all_field_names(arg, _seen)
        elif isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel):
            names |= _pydantic_all_field_names(annotation, _seen)
    return names


def _managed_session(factory: sessionmaker):
    @contextlib.contextmanager
    def _ctx():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _ctx


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, expire_on_commit=False)
    # Bootstrap creates the v1 Graph Release, which is required by the
    # contributor and create-session paths.
    GraphConfiguration().bootstrap_v1(sf)
    try:
        yield sf
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Model-introspection tests (no DB needed).
# ---------------------------------------------------------------------------


def test_collaboration_history_response_model_carries_graph_version() -> None:
    """``graph_version`` must be reachable by recursive field walk of the model.

    ``CollaborationReleaseGroupResponse.graph_version`` is the per-group
    field that carries the pinned Graph Version number for each contributor
    (C35, Task 0-B re-probe of #262 history body).
    """
    fields = _pydantic_all_field_names(CollaborationHistoryResponse)
    assert "graph_version" in fields, (
        f"graph_version absent from CollaborationHistoryResponse field tree; "
        f"found: {sorted(fields)}"
    )


def test_collaboration_history_response_model_exposes_no_release_internals() -> None:
    """The collaboration-history model must not declare any release-internal key."""
    fields = _pydantic_all_field_names(CollaborationHistoryResponse)
    leaked = FORBIDDEN_RELEASE_KEYS & fields
    assert not leaked, (
        f"Release-internal fields found in CollaborationHistoryResponse model: {leaked}"
    )


def test_collaboration_release_group_response_carries_graph_version() -> None:
    """The group-level model carries graph_version (the per-contributor field)."""
    fields = set(CollaborationReleaseGroupResponse.model_fields)
    assert "graph_version" in fields
    assert not (FORBIDDEN_RELEASE_KEYS & fields), (
        f"Release-internal fields in CollaborationReleaseGroupResponse: "
        f"{FORBIDDEN_RELEASE_KEYS & fields}"
    )


# ---------------------------------------------------------------------------
# SessionManager plain-dict tests — the five non-model endpoints.
# ---------------------------------------------------------------------------


def test_create_and_get_and_list_session_responses_satisfy_projection(
    factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_session, get_session, list_sessions all carry the three projection keys."""
    monkeypatch.setattr(
        "src.api.services.session_manager.get_db_session",
        _managed_session(factory),
    )
    monkeypatch.setattr(
        "src.api.services.session_manager.lock_active_graph_release",
        lambda _db: PinnedRelease(release_id=1, graph_version=1),
    )

    manager = SessionManager()
    created = manager.create_session(session_id="proj-create", graph_capable=True)
    detail = manager.get_session("proj-create")

    # list_sessions needs at least one message to appear (query joins on messages).
    # Insert directly so we avoid importing chat_service.
    with factory.begin() as db:
        session_row = (
            db.query(UserSession).filter_by(session_id="proj-create").one()
        )
        from src.database.models.session import SessionMessage

        db.add(
            SessionMessage(
                session_id=session_row.id,
                role="user",
                content="include in list",
            )
        )
    listed = manager.list_sessions(created_by="unit-test@example.com")

    union = _all_keys(created) | _all_keys(detail) | _all_keys(listed)

    # --- required keys must be present ---
    missing = REQUIRED_PROJECTION_KEYS - union
    assert not missing, (
        f"Required projection keys absent from create/get/list responses: {missing}"
    )

    # --- release-internal keys must be absent ---
    for response, label in [
        (created, "create_session"),
        (detail, "get_session"),
        (listed, "list_sessions"),
    ]:
        leaked = FORBIDDEN_RELEASE_KEYS & _all_keys(response)
        assert not leaked, (
            f"{label} response exposes release-internal keys: {leaked}"
        )


def test_duplicate_session_response_exposes_no_release_internals(
    factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /{id}/duplicate must not expose any release-internal key.

    Duplicate does not carry graph_version (the caller calls GET after
    duplicating); the AC6 union test covers the required keys.
    """
    monkeypatch.setattr(
        "src.api.services.session_manager.get_db_session",
        _managed_session(factory),
    )
    monkeypatch.setattr(
        "src.api.services.session_manager.lock_active_graph_release",
        lambda _db: PinnedRelease(release_id=1, graph_version=1),
    )

    # Seed a source session with a slide deck directly (no HTTP).
    with factory.begin() as db:
        source = UserSession(
            session_id="proj-source",
            created_by="owner@example.com",
            graph_release_id=None,
        )
        db.add(source)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=source.id,
                title="Test Deck",
                html_content="<html></html>",
                scripts_content="",
                slide_count=1,
                version=1,
                modified_by="owner@example.com",
            )
        )

    manager = SessionManager()
    result = manager.duplicate_session(
        source_session_id="proj-source",
        created_by="duplicator@example.com",
        title="Duplicate",
    )

    leaked = FORBIDDEN_RELEASE_KEYS & _all_keys(result)
    assert not leaked, (
        f"duplicate_session response exposes release-internal keys: {leaked}"
    )


def test_contributor_session_response_exposes_no_release_internals(
    factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /{id}/contribute must not expose any release-internal key.

    The contributor response does not carry graph_version; the AC6 union test
    covers the required keys via the other endpoints.
    """
    monkeypatch.setattr(
        "src.api.services.session_manager.get_db_session",
        _managed_session(factory),
    )
    # Contributor creation always pins to the active release.
    monkeypatch.setattr(
        "src.api.services.session_manager.lock_active_graph_release",
        lambda _db: PinnedRelease(release_id=1, graph_version=1),
    )

    # Seed a parent session.
    with factory.begin() as db:
        parent = UserSession(
            session_id="proj-parent",
            created_by="owner@example.com",
            graph_release_id=1,
        )
        db.add(parent)

    manager = SessionManager()
    result = manager.get_or_create_contributor_session(
        parent_session_id="proj-parent",
        created_by="contributor@example.com",
    )

    leaked = FORBIDDEN_RELEASE_KEYS & _all_keys(result)
    assert not leaked, (
        f"get_or_create_contributor_session response exposes release-internal keys: "
        f"{leaked}"
    )


# ---------------------------------------------------------------------------
# Union test — all six endpoints together satisfy AC6.
# ---------------------------------------------------------------------------


def test_union_of_all_six_conversation_endpoint_keys_satisfies_ac6(
    factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The union of all JSON keys across the six endpoints satisfies AC6.

    Required keys must appear in the union (they come from create/get/list).
    Forbidden keys must not appear in any individual response or in the
    CollaborationHistoryResponse model.
    """
    monkeypatch.setattr(
        "src.api.services.session_manager.get_db_session",
        _managed_session(factory),
    )
    monkeypatch.setattr(
        "src.api.services.session_manager.lock_active_graph_release",
        lambda _db: PinnedRelease(release_id=1, graph_version=1),
    )

    # --- set up sessions ---
    with factory.begin() as db:
        source = UserSession(
            session_id="union-source",
            created_by="owner@example.com",
            graph_release_id=None,
        )
        db.add(source)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=source.id,
                title="Union Test Deck",
                html_content="<html></html>",
                scripts_content="",
                slide_count=1,
                version=1,
                modified_by="owner@example.com",
            )
        )
        parent = UserSession(
            session_id="union-parent",
            created_by="owner2@example.com",
            graph_release_id=1,
        )
        db.add(parent)

    manager = SessionManager()

    # 1. POST /api/sessions
    created = manager.create_session(session_id="union-created", graph_capable=True)
    # 2. GET /api/sessions/{id}
    detail = manager.get_session("union-created")
    # 3. GET /api/sessions — needs at least one message to be listed
    with factory.begin() as db:
        s = db.query(UserSession).filter_by(session_id="union-created").one()
        from src.database.models.session import SessionMessage

        db.add(SessionMessage(session_id=s.id, role="user", content="list me"))
    listed = manager.list_sessions(created_by="unit-test@example.com")
    # 4. POST /{id}/duplicate
    duplicated = manager.duplicate_session(
        source_session_id="union-source",
        created_by="dupl@example.com",
        title="Union Duplicate",
    )
    # 5. POST /{id}/contribute
    contributed = manager.get_or_create_contributor_session(
        parent_session_id="union-parent",
        created_by="contrib@example.com",
    )
    # 6. GET /{id}/collaboration-history — probed via the response model
    collab_model_fields = _pydantic_all_field_names(CollaborationHistoryResponse)

    # --- union ---
    union = (
        _all_keys(created)
        | _all_keys(detail)
        | _all_keys(listed)
        | _all_keys(duplicated)
        | _all_keys(contributed)
        | collab_model_fields
    )

    # Required keys must be in the union.
    missing = REQUIRED_PROJECTION_KEYS - union
    assert not missing, (
        f"AC6: required projection keys absent from the union of all six "
        f"conversation endpoints: {missing!r}"
    )

    # Forbidden keys must not be in the union.
    leaked = FORBIDDEN_RELEASE_KEYS & union
    assert not leaked, (
        f"AC6: release-internal keys exposed by one or more conversation "
        f"endpoints: {leaked!r}"
    )
