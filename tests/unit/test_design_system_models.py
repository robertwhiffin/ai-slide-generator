"""Unit tests for the structured Design System data model + hand-rolled migration.

Phase 1 of the Design System Library feature (see
``docs/technical/design-system-library-spec.md`` §6).

Coverage:
- The hand-rolled migration ``_migrate_design_system_tables`` creates the three
  additive tables idempotently and is dialect-safe on the SQLite used in tests.
- The schema-qualified / Postgres path (the migration's production purpose):
  tables are created inside a named schema and the child->parent FK cascades,
  and the models compile to the expected PostgreSQL DDL (JSONB/BYTEA/SERIAL,
  quoted ``group``, schema-qualified FK).
- ORM create/read round-trips for ``DesignSystem`` + its assets + its tokens.
- Byte-storage guardrails: binary bytes live ONLY in the dedicated asset table,
  and per-asset / per-bundle size-limit constants exist.
- Backward compatibility: the existing ``slide_style_library`` table and its
  ``style_content`` prompt-injection column are untouched by this migration.

All fixtures are SYNTHETIC (fake "Acme" brand, dummy hex, placeholder bytes) —
no real brand content, per the public-repo hygiene rule.
"""

import os
import tempfile
from unittest.mock import patch

import pytest
from sqlalchemy import LargeBinary, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base, _run_migrations, init_db

DESIGN_SYSTEM_TABLES = {"design_system", "design_system_asset", "design_system_token"}


@pytest.fixture
def sqlite_engine():
    """File-backed SQLite engine that survives connection open/close.

    ``engine.begin()`` closes its connection on exit, so an in-memory DB would be
    discarded between the migration call and the assertion.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


def _make_design_system(**overrides):
    """Build a synthetic DesignSystem ORM instance with sane defaults."""
    from src.database.models.design_system import DesignSystem

    fields = dict(
        name="Acme Design System",
        description="Synthetic fixture brand — not a real design system.",
        created_by="tester@example.com",
        published=True,
        is_default=False,
        manifest_json={"name": "Acme", "version": "1.0.0", "tokens": {"core": 1}},
        compiled_style_content=":root { --brand-primary: #123456; }",
    )
    fields.update(overrides)
    return DesignSystem(**fields)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class TestDesignSystemMigration:
    def test_migration_creates_tables_on_bare_db(self, sqlite_engine):
        """The hand-rolled migration creates all three tables on an empty DB."""
        from src.core.database import _migrate_design_system_tables

        with sqlite_engine.begin() as conn:
            _migrate_design_system_tables(conn, schema=None)

        names = set(inspect(sqlite_engine).get_table_names())
        assert DESIGN_SYSTEM_TABLES <= names

    def test_migration_is_idempotent(self, sqlite_engine):
        """Running the migration twice must not raise and leaves tables intact."""
        from src.core.database import _migrate_design_system_tables

        with sqlite_engine.begin() as conn:
            _migrate_design_system_tables(conn, schema=None)
        with sqlite_engine.begin() as conn:
            _migrate_design_system_tables(conn, schema=None)

        names = set(inspect(sqlite_engine).get_table_names())
        assert DESIGN_SYSTEM_TABLES <= names

    def test_run_migrations_end_to_end_is_idempotent(self, sqlite_engine):
        """Full _run_migrations (after create_all) is idempotent and yields tables."""
        Base.metadata.create_all(bind=sqlite_engine)
        _run_migrations(sqlite_engine, schema=None)
        _run_migrations(sqlite_engine, schema=None)

        names = set(inspect(sqlite_engine).get_table_names())
        assert DESIGN_SYSTEM_TABLES <= names

    def test_init_db_creates_tables(self, sqlite_engine):
        """init_db() (create_all + migrations) ensures the tables exist."""
        with patch("src.core.database.get_engine", return_value=sqlite_engine):
            init_db()

        names = set(inspect(sqlite_engine).get_table_names())
        assert DESIGN_SYSTEM_TABLES <= names

    def test_is_active_column_present_after_run_migrations(self, sqlite_engine):
        """Phase 3 soft-delete: design_system exposes an is_active column."""
        Base.metadata.create_all(bind=sqlite_engine)
        _run_migrations(sqlite_engine, schema=None)

        cols = {c["name"] for c in inspect(sqlite_engine).get_columns("design_system")}
        assert "is_active" in cols

    def test_soft_delete_migration_backfills_pre_existing_table(self, sqlite_engine):
        """When design_system predates the is_active column, the idempotent ALTER
        adds it (simulating a Lakebase table created by an earlier Phase 1/2 build).
        """
        from sqlalchemy import inspect as _inspect

        from src.core.database import _migrate_design_system_soft_delete

        # Build a design_system table WITHOUT is_active, mimicking an old deploy.
        with sqlite_engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE design_system (id INTEGER PRIMARY KEY, name VARCHAR(255))"
            ))

        with sqlite_engine.begin() as conn:
            _migrate_design_system_soft_delete(
                conn, _inspect(conn), schema=None, _qual=lambda t: f'"{t}"', is_sqlite=True
            )
            # Idempotent: a second run is a no-op and must not raise.
            _migrate_design_system_soft_delete(
                conn, _inspect(conn), schema=None, _qual=lambda t: f'"{t}"', is_sqlite=True
            )

        cols = {c["name"] for c in inspect(sqlite_engine).get_columns("design_system")}
        assert "is_active" in cols

    def test_asset_and_token_columns_present(self, sqlite_engine):
        """Migration-created tables expose the spec §6 columns."""
        from src.core.database import _migrate_design_system_tables

        with sqlite_engine.begin() as conn:
            _migrate_design_system_tables(conn, schema=None)

        insp = inspect(sqlite_engine)
        asset_cols = {c["name"] for c in insp.get_columns("design_system_asset")}
        token_cols = {c["name"] for c in insp.get_columns("design_system_token")}
        ds_cols = {c["name"] for c in insp.get_columns("design_system")}

        assert {
            "id",
            "design_system_id",
            "kind",
            "filename",
            "mime",
            "bytes",
            "width",
            "height",
            "size_bytes",
        } <= asset_cols
        assert {"id", "design_system_id", "group", "name", "value"} <= token_cols
        assert {
            "id",
            "name",
            "description",
            "created_by",
            "published",
            "is_default",
            "version",
            "created_at",
            "updated_at",
            "manifest_json",
            "compiled_style_content",
        } <= ds_cols


# ---------------------------------------------------------------------------
# ORM create / read round-trips
# ---------------------------------------------------------------------------


class TestDesignSystemModels:
    def test_design_system_round_trip_and_defaults(self, sqlite_engine):
        from src.database.models.design_system import DesignSystem

        Base.metadata.create_all(bind=sqlite_engine)
        with Session(sqlite_engine) as s:
            ds = _make_design_system()
            s.add(ds)
            s.commit()
            ds_id = ds.id
            # Client-side defaults applied on flush.
            assert ds.version == 1
            assert ds.published is True
            assert ds.is_default is False

        with Session(sqlite_engine) as s:
            got = s.get(DesignSystem, ds_id)
            assert got.name == "Acme Design System"
            assert got.compiled_style_content == ":root { --brand-primary: #123456; }"
            assert got.manifest_json["version"] == "1.0.0"
            assert got.created_at is not None
            assert got.updated_at is not None

    def test_asset_bytes_round_trip(self, sqlite_engine):
        from src.database.models.design_system import DesignSystemAsset

        Base.metadata.create_all(bind=sqlite_engine)
        placeholder = b"\x89PNG\r\n\x1a\n placeholder-bytes"
        with Session(sqlite_engine) as s:
            ds = _make_design_system()
            ds.assets.append(
                DesignSystemAsset(
                    kind="logo",
                    filename="acme-logo.png",
                    mime="image/png",
                    data=placeholder,
                    width=200,
                    height=80,
                    size_bytes=len(placeholder),
                )
            )
            s.add(ds)
            s.commit()
            ds_id = ds.id

        with Session(sqlite_engine) as s:
            asset = s.query(DesignSystemAsset).filter_by(design_system_id=ds_id).one()
            assert asset.data == placeholder
            assert asset.kind == "logo"
            assert asset.mime == "image/png"
            assert asset.width == 200
            assert asset.size_bytes == len(placeholder)

    def test_token_group_reserved_word_round_trip(self, sqlite_engine):
        """`group` is a SQL reserved word — verify it stores/reads correctly."""
        from src.database.models.design_system import DesignSystemToken

        Base.metadata.create_all(bind=sqlite_engine)
        with Session(sqlite_engine) as s:
            ds = _make_design_system()
            ds.tokens.append(DesignSystemToken(group="core", name="primary", value="#123456"))
            ds.tokens.append(DesignSystemToken(group="spacing", name="md", value="16px"))
            s.add(ds)
            s.commit()
            ds_id = ds.id

        with Session(sqlite_engine) as s:
            tokens = (
                s.query(DesignSystemToken)
                .filter_by(design_system_id=ds_id)
                .order_by(DesignSystemToken.name)
                .all()
            )
            assert {(t.group, t.name, t.value) for t in tokens} == {
                ("spacing", "md", "16px"),
                ("core", "primary", "#123456"),
            }

    def test_relationships_load_children(self, sqlite_engine):
        from src.database.models.design_system import (
            DesignSystem,
            DesignSystemAsset,
            DesignSystemToken,
        )

        Base.metadata.create_all(bind=sqlite_engine)
        with Session(sqlite_engine) as s:
            ds = _make_design_system()
            ds.assets.append(
                DesignSystemAsset(
                    kind="font",
                    filename="acme.woff2",
                    mime="font/woff2",
                    data=b"font-bytes",
                    size_bytes=10,
                )
            )
            ds.tokens.append(DesignSystemToken(group="core", name="ink", value="#000000"))
            s.add(ds)
            s.commit()
            ds_id = ds.id

        with Session(sqlite_engine) as s:
            got = s.get(DesignSystem, ds_id)
            assert len(got.assets) == 1
            assert len(got.tokens) == 1
            assert got.assets[0].filename == "acme.woff2"
            assert got.tokens[0].value == "#000000"

    def test_name_is_unique(self, sqlite_engine):
        Base.metadata.create_all(bind=sqlite_engine)
        with Session(sqlite_engine) as s:
            s.add(_make_design_system(name="Acme DS"))
            s.commit()
        with Session(sqlite_engine) as s:
            s.add(_make_design_system(name="Acme DS"))
            with pytest.raises(IntegrityError):
                s.commit()


# ---------------------------------------------------------------------------
# Byte-storage guardrails
# ---------------------------------------------------------------------------


class TestByteStorageGuardrails:
    def test_bytes_live_only_in_asset_table(self):
        from src.database.models.design_system import (
            DesignSystem,
            DesignSystemAsset,
            DesignSystemToken,
        )

        def has_binary_column(model):
            return any(isinstance(col.type, LargeBinary) for col in model.__table__.columns)

        assert has_binary_column(DesignSystemAsset)
        assert not has_binary_column(DesignSystem)
        assert not has_binary_column(DesignSystemToken)

    def test_size_limit_constants_defined(self):
        from src.database.models.design_system import (
            MAX_ASSET_SIZE_BYTES,
            MAX_BUNDLE_SIZE_BYTES,
        )

        assert MAX_ASSET_SIZE_BYTES > 0
        assert MAX_BUNDLE_SIZE_BYTES >= MAX_ASSET_SIZE_BYTES


# ---------------------------------------------------------------------------
# Backward compatibility with the existing slide-style prompt path
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_slide_style_library_still_works(self, sqlite_engine):
        """Existing slide styles keep round-tripping through style_content."""
        from src.database.models.slide_style_library import SlideStyleLibrary

        Base.metadata.create_all(bind=sqlite_engine)
        _run_migrations(sqlite_engine, schema=None)

        with Session(sqlite_engine) as s:
            style = SlideStyleLibrary(
                name="Acme Legacy Style",
                style_content="body { color: #000000; }",
            )
            s.add(style)
            s.commit()
            style_id = style.id

        with Session(sqlite_engine) as s:
            got = s.get(SlideStyleLibrary, style_id)
            assert got.style_content == "body { color: #000000; }"

    def test_slide_style_library_not_extended(self, sqlite_engine):
        """The design-system model is a NEW table; it must not add columns to
        slide_style_library (that would risk the existing prompt-injection path)."""
        Base.metadata.create_all(bind=sqlite_engine)
        _run_migrations(sqlite_engine, schema=None)

        cols = {c["name"] for c in inspect(sqlite_engine).get_columns("slide_style_library")}
        for design_system_only in (
            "manifest_json",
            "compiled_style_content",
            "published",
            "version",
        ):
            assert design_system_only not in cols


# ---------------------------------------------------------------------------
# Schema-qualified / PostgreSQL path (the migration's production purpose)
# ---------------------------------------------------------------------------


@pytest.fixture
def restore_ds_table_schema():
    """Restore the module-global ``Table.schema`` after a schema-qualified test.

    ``_migrate_design_system_tables`` sets ``Table.schema`` on the SHARED ORM
    metadata (mirroring ``init_db``). Left mutated, ``schema='app_data'`` would
    leak onto every later test's ``create_all`` and break the suite, so capture
    and restore the original values regardless of test outcome.
    """
    from src.database.models.design_system import (
        DesignSystem,
        DesignSystemAsset,
        DesignSystemToken,
    )

    tables = [
        DesignSystem.__table__,
        DesignSystemAsset.__table__,
        DesignSystemToken.__table__,
    ]
    original = [t.schema for t in tables]
    try:
        yield
    finally:
        for table, schema in zip(tables, original):
            table.schema = schema


class TestSchemaQualifiedMigration:
    SCHEMA = "app_data"  # matches the default LAKEBASE_SCHEMA

    def test_migration_creates_tables_in_named_schema(self, sqlite_engine, restore_ds_table_schema):
        """With ``schema=`` set, the tables are created inside that named schema
        and the child->parent FK cascades on delete.

        SQLite models the Lakebase schema via ``ATTACH DATABASE ... AS <schema>``.
        Everything runs on one connection because the attach alias, the
        ``PRAGMA foreign_keys`` setting, and the ``:memory:`` attached DB are all
        per-connection.
        """
        from src.core.database import _migrate_design_system_tables

        with sqlite_engine.connect() as conn:
            conn.execute(text(f"ATTACH DATABASE ':memory:' AS {self.SCHEMA}"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1

            _migrate_design_system_tables(conn, schema=self.SCHEMA)
            # Idempotent: a second run must not raise.
            _migrate_design_system_tables(conn, schema=self.SCHEMA)

            insp = inspect(conn)
            assert DESIGN_SYSTEM_TABLES <= set(insp.get_table_names(schema=self.SCHEMA))
            # Nothing leaked into the default (main) schema.
            assert not (DESIGN_SYSTEM_TABLES & set(insp.get_table_names()))

            # The reflected child FK is wired to the parent with ON DELETE CASCADE.
            (fk,) = insp.get_foreign_keys("design_system_asset", schema=self.SCHEMA)
            assert fk["referred_table"] == "design_system"
            assert fk["referred_schema"] == self.SCHEMA
            assert fk["options"].get("ondelete") == "CASCADE"

            # Runtime cascade: deleting the parent removes its assets.
            conn.execute(
                text(
                    f"INSERT INTO {self.SCHEMA}.design_system "
                    "(name, published, is_default, version, created_at, updated_at) "
                    "VALUES ('Acme DS', 0, 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            ds_id = conn.execute(text(f"SELECT id FROM {self.SCHEMA}.design_system")).scalar()
            conn.execute(
                text(
                    f"INSERT INTO {self.SCHEMA}.design_system_asset "
                    "(design_system_id, kind, filename, mime, bytes, size_bytes) "
                    "VALUES (:ds_id, 'logo', 'acme-logo.svg', 'image/svg+xml', :data, 4)"
                ),
                {"ds_id": ds_id, "data": b"svg!"},
            )
            assert (
                conn.execute(
                    text(f"SELECT COUNT(*) FROM {self.SCHEMA}.design_system_asset")
                ).scalar()
                == 1
            )
            conn.execute(
                text(f"DELETE FROM {self.SCHEMA}.design_system WHERE id = :ds_id"),
                {"ds_id": ds_id},
            )
            assert (
                conn.execute(
                    text(f"SELECT COUNT(*) FROM {self.SCHEMA}.design_system_asset")
                ).scalar()
                == 0
            )

    def test_postgres_dialect_ddl(self, restore_ds_table_schema):
        """The models compile to the intended PostgreSQL/Lakebase DDL when the
        schema is set: schema-qualified FK, JSONB/BYTEA/SERIAL types, quoted
        ``group`` reserved word."""
        from src.database.models.design_system import (
            DesignSystem,
            DesignSystemAsset,
            DesignSystemToken,
        )

        for model in (DesignSystem, DesignSystemAsset, DesignSystemToken):
            model.__table__.schema = self.SCHEMA

        pg = postgresql.dialect()
        ds_ddl = str(CreateTable(DesignSystem.__table__).compile(dialect=pg))
        asset_ddl = str(CreateTable(DesignSystemAsset.__table__).compile(dialect=pg))
        token_ddl = str(CreateTable(DesignSystemToken.__table__).compile(dialect=pg))

        # Child FKs are schema-qualified back to the parent, cascading on delete.
        assert f"REFERENCES {self.SCHEMA}.design_system (id) ON DELETE CASCADE" in asset_ddl
        assert f"REFERENCES {self.SCHEMA}.design_system (id) ON DELETE CASCADE" in token_ddl

        # Dialect-specific types render as expected.
        assert "manifest_json JSONB" in ds_ddl
        assert "bytes BYTEA" in asset_ddl
        assert "id SERIAL" in ds_ddl

        # `group` is a reserved word and must be double-quoted.
        assert '"group" VARCHAR' in token_ddl
