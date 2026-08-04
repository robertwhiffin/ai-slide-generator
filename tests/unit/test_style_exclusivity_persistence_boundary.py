"""Style exclusivity must hold at the PERSISTENCE boundary, not the serializer.

``slide_style_id`` and ``design_system_id`` are mutually exclusive: generation
resolves the design system first, so a stored row carrying both disagrees with the
deck it produces.

Round 7 moved the rule from ``model_dump()`` to a ``@model_serializer``, on the
theory that a serializer is the one chokepoint every writer funnels through. It is
not. A serializer only governs writers who SERIALIZE THE MODEL, and four shapes of
writer never do:

* ``dict(model)`` — iterates the instance; calls no serializer at all;
* raw ORM attribute assignment — ``row.agent_config = {...}``;
* a SQLAlchemy bulk update — ``Query.update({"agent_config": {...}})``, which does
  not even fire mapper-level ``before_update`` events;
* ``SessionManager.create_session`` — handed a RAW dict it never parsed.

Each was patched individually (``create_session`` calls
``normalize_agent_config_dict``), which is the same per-call-site game one altitude
up: the next writer inherits nothing.

The invariant is a property of the STORED COLUMN, so it is enforced where the
column is written — a ``TypeDecorator`` on ``agent_config`` whose bind hook every
INSERT and UPDATE passes through, whatever produced the value. These tests measure
the BYTES POSTGRES/SQLITE ACTUALLY STORED (read back with raw SQL, never through
the ORM attribute), because a test that reads the ORM attribute back is measuring
its own in-memory input.

Semantics are unchanged and deliberately NOT a 422: DESIGN SYSTEM WINS, the slide
style is dropped, and legacy both-set rows HEAL on write. A 422 would wedge every
legacy both-set row on every save — the frontend PUTs the WHOLE config, so a user
sitting on such a row could not save an unrelated edit. That regression already
happened once.

All fixtures SYNTHETIC (invented ids and names).
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register every model with Base.metadata
from src.core.database import Base
from src.database.models.profile import ConfigProfile
from src.database.models.session import UserSession

_STYLE_ID = 7
_DS_ID = 9


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()


def _stored(engine, table, row_id):
    """The agent_config as the DATABASE holds it.

    Read with raw SQL on a SEPARATE connection-level round trip so the value is
    what was written, not what the ORM identity map remembers being handed.
    """
    with engine.connect() as conn:
        raw = conn.execute(
            text(f"SELECT agent_config FROM {table} WHERE id = :id"), {"id": row_id}
        ).scalar()
    if raw is None:
        return None
    return json.loads(raw) if isinstance(raw, str) else raw


def _authorities(stored):
    """Which style authorities survived into the stored blob."""
    if stored is None:
        return []
    return [
        field
        for field in ("slide_style_id", "design_system_id")
        if stored.get(field) is not None
    ]


def _both_set_dict():
    """A both-set config exactly as a hostile or legacy writer supplies it."""
    return {"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID}


def _assert_design_system_won(stored, *, writer):
    assert stored is not None, f"{writer}: nothing was stored"
    assert _authorities(stored) == ["design_system_id"], (
        f"{writer} persisted BOTH style authorities: {stored!r}. The design system "
        "must win and the slide style must be dropped."
    )
    assert stored.get("design_system_id") == _DS_ID, (
        f"{writer}: the design system must survive, got {stored!r}"
    )


# ---------------------------------------------------------------------------
# The five writers
# ---------------------------------------------------------------------------


class TestEveryWriterIsNormalized:
    """Each of these is a DIFFERENT way to reach the column, and every one of them
    must land normalized without the writer knowing the rule exists."""

    def test_pydantic_serializer_path(self, engine, db):
        """The path that already worked — it must keep working."""
        from src.api.schemas.agent_config import AgentConfig

        config = AgentConfig(slide_style_id=_STYLE_ID, design_system_id=_DS_ID)
        row = UserSession(session_id="synthetic-pydantic", agent_config=config.model_dump())
        db.add(row)
        db.commit()

        _assert_design_system_won(_stored(engine, "user_sessions", row.id), writer="model_dump()")

    def test_dict_of_model(self, engine, db):
        """``dict(model)`` iterates the instance and calls NO serializer."""
        from src.api.schemas.agent_config import AgentConfig

        config = AgentConfig(slide_style_id=_STYLE_ID, design_system_id=_DS_ID)
        raw = dict(config)
        assert raw["slide_style_id"] == _STYLE_ID, (
            "precondition: dict(model) is expected to bypass the serializer and "
            "carry both ids — that is what makes this test meaningful"
        )

        row = UserSession(session_id="synthetic-dict-model", agent_config=raw)
        db.add(row)
        db.commit()

        _assert_design_system_won(_stored(engine, "user_sessions", row.id), writer="dict(model)")

    def test_raw_orm_attribute_assignment(self, engine, db):
        """``row.agent_config = {...}`` on an EXISTING row (an UPDATE, not INSERT)."""
        row = UserSession(session_id="synthetic-raw-attr", agent_config=None)
        db.add(row)
        db.commit()

        row.agent_config = _both_set_dict()
        db.commit()

        _assert_design_system_won(
            _stored(engine, "user_sessions", row.id), writer="raw ORM assignment"
        )

    def test_bulk_update(self, engine, db):
        """A bulk ``Query.update()`` — it does not even fire mapper before_update."""
        row = UserSession(session_id="synthetic-bulk", agent_config=None)
        db.add(row)
        db.commit()
        row_id = row.id

        db.query(UserSession).filter(UserSession.id == row_id).update(
            {"agent_config": _both_set_dict()}, synchronize_session=False
        )
        db.commit()

        _assert_design_system_won(
            _stored(engine, "user_sessions", row_id), writer="bulk Query.update()"
        )

    def test_session_manager_create_session(self, engine):
        """``SessionManager.create_session`` is handed a RAW dict it never parses."""
        from src.api.services.session_manager import SessionManager

        session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        @contextmanager
        def _fake_get_db_session():
            db = session_local()
            try:
                yield db
                db.commit()
            finally:
                db.close()

        with patch(
            "src.api.services.session_manager.get_db_session", _fake_get_db_session
        ):
            SessionManager().create_session(
                session_id="synthetic-create-session",
                agent_config=_both_set_dict(),
            )

        with engine.connect() as conn:
            row_id = conn.execute(
                text("SELECT id FROM user_sessions WHERE session_id = :s"),
                {"s": "synthetic-create-session"},
            ).scalar_one()

        _assert_design_system_won(
            _stored(engine, "user_sessions", row_id),
            writer="SessionManager.create_session",
        )

    def test_profile_column_is_normalized_too(self, engine, db):
        """``config_profiles.agent_config`` holds the same kind of blob and is
        written by its own routes, so it carries the same invariant."""
        profile = ConfigProfile(name="Synthetic Profile", agent_config=_both_set_dict())
        db.add(profile)
        db.commit()

        _assert_design_system_won(
            _stored(engine, "config_profiles", profile.id), writer="profile insert"
        )


# ---------------------------------------------------------------------------
# The rule must be SURGICAL — normalizing must not become rewriting
# ---------------------------------------------------------------------------


class TestNormalizationIsSurgical:
    """A persistence-layer hook sees EVERY write, so it must change as little as
    possible. Routing each blob through ``AgentConfig`` would silently drop keys a
    newer writer stored and inflate a lean dict with every default — so the rule is
    applied to the dict itself."""

    def test_unknown_keys_survive(self, engine, db):
        """A key this model does not know about must not be destroyed in passing."""
        raw = {**_both_set_dict(), "a_key_a_newer_writer_stored": "keep me"}
        row = UserSession(session_id="synthetic-unknown-keys", agent_config=raw)
        db.add(row)
        db.commit()

        stored = _stored(engine, "user_sessions", row.id)
        _assert_design_system_won(stored, writer="unknown-key config")
        assert stored.get("a_key_a_newer_writer_stored") == "keep me", (
            f"the persistence hook destroyed an unrelated key: {stored!r}"
        )

    def test_a_config_with_only_a_slide_style_is_untouched(self, engine, db):
        """Nothing to reconcile means nothing changes — byte for byte."""
        raw = {"slide_style_id": _STYLE_ID, "style_source": "user", "tools": []}
        row = UserSession(session_id="synthetic-style-only", agent_config=raw)
        db.add(row)
        db.commit()

        assert _stored(engine, "user_sessions", row.id) == raw

    def test_a_config_with_only_a_design_system_is_untouched(self, engine, db):
        raw = {"design_system_id": _DS_ID, "template_id": 3}
        row = UserSession(session_id="synthetic-ds-only", agent_config=raw)
        db.add(row)
        db.commit()

        assert _stored(engine, "user_sessions", row.id) == raw

    def test_no_config_does_not_become_an_empty_config(self, engine, db):
        """``None`` is "no config at all", which is NOT an empty config.

        Whether the column holds SQL NULL (key omitted, ``default=None``) or the JSON
        scalar ``null`` (``None`` passed explicitly) is pre-existing SQLAlchemy JSON
        semantics and not this fix's business. What matters is that the normalizer
        does not invent a config where there was none — reading either form back must
        still be "nothing".
        """
        omitted = UserSession(session_id="synthetic-no-config-omitted")
        explicit = UserSession(session_id="synthetic-no-config-explicit", agent_config=None)
        db.add_all([omitted, explicit])
        db.commit()

        for row, how in ((omitted, "omitted"), (explicit, "explicit None")):
            assert _stored(engine, "user_sessions", row.id) is None, (
                f"agent_config {how} was turned into a config by the persistence hook"
            )

    def test_a_non_dict_blob_is_passed_through(self, engine, db):
        """The hook must not assume the shape. A list (a corrupt or foreign writer's
        value) has no exclusivity to enforce and must not raise on the way to the
        database — the column is JSON, not ``AgentConfig``."""
        row = UserSession(session_id="synthetic-non-dict", agent_config=[1, 2, 3])
        db.add(row)
        db.commit()

        assert _stored(engine, "user_sessions", row.id) == [1, 2, 3]

    def test_the_in_memory_object_is_not_mutated(self, engine, db):
        """Normalizing on the way OUT must not edit the caller's dict. A GET that
        happens to flush would otherwise silently rewrite a config the caller still
        holds a reference to."""
        raw = _both_set_dict()
        row = UserSession(session_id="synthetic-no-mutate", agent_config=raw)
        db.add(row)
        db.commit()

        assert raw == {"slide_style_id": _STYLE_ID, "design_system_id": _DS_ID}, (
            f"the caller's own dict was mutated by persisting it: {raw!r}"
        )


# ---------------------------------------------------------------------------
# Where the rule lives
# ---------------------------------------------------------------------------


class TestTheColumnCarriesTheRule:
    def test_both_agent_config_columns_use_the_normalizing_type(self):
        """The invariant is declared on the COLUMN, so a future model that stores an
        agent config gets it by declaring the same type — not by remembering a call."""
        from src.database.types import NormalizedAgentConfig

        for model in (UserSession, ConfigProfile):
            column_type = model.__table__.c.agent_config.type
            assert isinstance(column_type, NormalizedAgentConfig), (
                f"{model.__name__}.agent_config is a plain "
                f"{type(column_type).__name__}, so any writer that does not go "
                "through the Pydantic serializer can still persist both style "
                "authorities"
            )

    def test_the_stored_ddl_is_still_json(self, engine):
        """A TypeDecorator must not change the emitted column type — an existing
        deployment has to keep working with no migration."""
        from sqlalchemy.schema import CreateTable

        ddl = str(CreateTable(UserSession.__table__).compile(engine))
        assert "agent_config JSON" in ddl, (
            f"the agent_config column no longer emits as JSON:\n{ddl}"
        )
