"""Free-form brand fields must be UNCAPPED text (BLOCKING 4a).

The product requirement is that no brand data is ever turned away or silently
altered. Length caps on free-form brand fields violate it in three distinct ways,
all of which were still live:

1. The API validator REJECTED a 256-character token ``group``/``name``/``value``
   with ``string_too_long`` — and because a bundle import is one request, one long
   string failed the WHOLE import, costing every other token in the bundle.
2. ``design_system_service._resolve_name`` SILENTLY TRUNCATED an imported name to
   255 characters. Truncation is worse than rejection: the brand is stored under a
   name it never chose, with nothing to signal it.
3. The import path DISCARDED an unrecognized token group before storage — the
   author's group was replaced by an inferred one, so a token could not be
   persisted with its group intact.

Caps must be removed at BOTH layers in lockstep. A cap at either the ORM or the
Pydantic layer still turns the brand away, which is exactly how this reopened
after the previous round widened only the storage column.

Explicitly NOT relaxed: the per-asset / per-bundle BYTE limits (OOM guards, not
brand-data limits) and the system-controlled enum columns (``kind``, ``mime``,
``created_by``/``updated_by``) — those are not user brand text.

SQLite (used here) does not enforce declared VARCHAR length, so the meaningful
assertions are (a) the ORM column TYPE is unlimited Text, (b) the Pydantic
validator accepts, and (c) an end-to-end round-trip preserves the exact input
length. The Postgres column type is asserted separately from the ORM declaration.

All fixtures SYNTHETIC (invented brand names, dummy hex).
"""

import pytest
from sqlalchemy import String, Text, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base

#: Long enough to break every historical cap (50/100/255/1024).
_LONG = 1000

#: Free-form brand text with unicode, emoji and slashes — sanitize-not-reject must
#: still hold, so none of these may cause a rejection or an alteration.
_EXOTIC = "brand/セマンティック.颜色 🎨 Ünïcødé—em—dash "


def _long_text(prefix: str, *, exotic: str = _EXOTIC) -> str:
    """A *_LONG*-character free-form brand string containing exotic characters."""
    body = (exotic * ((_LONG // len(exotic)) + 1))[: _LONG - len(prefix)]
    out = prefix + body
    assert len(out) == _LONG
    return out


def _long_path_segment(prefix: str) -> str:
    """A *_LONG*-character brand string with NO slash.

    For the candidates derived from a PATH (the uploaded zip's filename, the bundle
    root folder), where a ``/`` legitimately delimits segments — those code paths
    take the last segment by design, which is path semantics, not truncation.
    """
    return _long_text(prefix, exotic=_EXOTIC.replace("/", "-"))


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


class TestOrmColumnsAreUncappedText:
    """Layer 1: the ORM declaration. ``Text`` has no length; ``String(n)`` does.

    This is what ``create_all`` uses for a fresh database and what the Postgres
    column type is derived from, so it is the authoritative half of the lockstep.
    """

    @pytest.mark.parametrize(
        "model_name,column_name",
        [
            ("DesignSystem", "name"),
            ("DesignSystem", "description"),
            ("DesignSystemToken", "group"),
            ("DesignSystemToken", "name"),
            ("DesignSystemToken", "value"),
            ("DesignSystemAsset", "filename"),
            ("DesignSystemFile", "path"),
            ("DesignSystemTemplate", "name"),
            ("DesignSystemTemplate", "entry_path"),
        ],
    )
    def test_free_form_brand_column_is_unlimited(self, model_name, column_name):
        import src.database.models.design_system as models

        column = getattr(models, model_name).__table__.columns[column_name]
        length = getattr(column.type, "length", None)

        assert length is None, (
            f"{model_name}.{column_name} is capped at {length} characters. A cap on "
            f"free-form brand text turns the brand away; it must be unlimited Text."
        )
        assert isinstance(column.type, Text), (
            f"{model_name}.{column_name} should be Text, got {column.type!r}"
        )

    @pytest.mark.parametrize(
        "model_name,column_name",
        [
            # System/compiler-controlled enums and identity strings — NOT brand text.
            ("DesignSystemAsset", "kind"),
            ("DesignSystemAsset", "mime"),
            ("DesignSystemFile", "kind"),
            ("DesignSystemFile", "mime"),
            ("DesignSystem", "created_by"),
            ("DesignSystem", "updated_by"),
        ],
    )
    def test_system_controlled_columns_keep_their_bounds(self, model_name, column_name):
        """The counter-assertion: uncapping must be SCOPED to brand text. These are
        enums the compiler/importer writes and identity strings the platform
        writes, so they stay bounded — an unbounded enum column is a defect, not a
        feature."""
        import src.database.models.design_system as models

        column = getattr(models, model_name).__table__.columns[column_name]

        assert isinstance(column.type, String), (
            f"{model_name}.{column_name} is system-controlled and should stay a "
            f"bounded String, got {column.type!r}"
        )
        assert getattr(column.type, "length", None) is not None


class TestPydanticValidatorsAreUncapped:
    """Layer 2: the API validator. A cap here rejects the brand before storage is
    ever reached, which is how this defect survived the storage-only widening."""

    @pytest.mark.parametrize("field", ["group", "name", "value"])
    def test_token_in_accepts_a_long_field(self, field):
        from src.api.routes.settings.design_systems import TokenIn

        payload = {"group": "core", "name": "tok", "value": "#0A0B0C"}
        payload[field] = _long_text(f"{field}-")

        token = TokenIn(**payload)

        assert len(getattr(token, field)) == _LONG, (
            f"TokenIn.{field} altered a {_LONG}-character brand string"
        )
        assert getattr(token, field) == payload[field]

    def test_token_in_still_rejects_empty_fields(self):
        """Uncapping the MAXIMUM must not remove the minimum: an empty token is
        malformed, not brand data."""
        from pydantic import ValidationError

        from src.api.routes.settings.design_systems import TokenIn

        for field in ("group", "name", "value"):
            payload = {"group": "core", "name": "tok", "value": "#0A0B0C"}
            payload[field] = ""
            with pytest.raises(ValidationError):
                TokenIn(**payload)

    def test_design_system_create_accepts_a_long_name(self):
        from src.api.routes.settings.design_systems import DesignSystemCreate

        name = _long_text("ds-")
        body = DesignSystemCreate(name=name)

        assert len(body.name) == _LONG
        assert body.name == name

    def test_design_system_update_accepts_a_long_name(self):
        from src.api.routes.settings.design_systems import DesignSystemUpdate

        name = _long_text("ds-upd-")
        body = DesignSystemUpdate(name=name)

        assert len(body.name) == _LONG

    def test_design_system_create_still_rejects_an_empty_name(self):
        from pydantic import ValidationError

        from src.api.routes.settings.design_systems import DesignSystemCreate

        with pytest.raises(ValidationError):
            DesignSystemCreate(name="")


class TestImportNeverTruncates:
    """``_resolve_name`` clamped every candidate to 255. Truncation stores the
    brand under a name it never chose, with no signal that it happened."""

    def test_an_explicit_name_override_is_not_truncated(self):
        from src.services.design_system_service import _resolve_name

        name = _long_text("override-")
        resolved = _resolve_name(name, {}, "")

        assert len(resolved) == len(name), (
            f"import SILENTLY TRUNCATED the name to {len(resolved)} characters"
        )
        assert resolved == name

    def test_a_manifest_name_is_not_truncated(self):
        from src.services.design_system_service import _resolve_name

        name = _long_text("manifest-")
        resolved = _resolve_name(None, {"name": name}, "")

        assert len(resolved) == len(name)
        assert resolved == name

    def test_a_readme_h1_name_is_not_truncated(self):
        from src.services.design_system_service import _resolve_name

        name = _long_text("readme-h1-")
        resolved = _resolve_name(None, {}, "", readme_h1=name)

        assert len(resolved) == len(name)

    def test_a_zip_filename_derived_name_is_not_truncated(self):
        from src.services.design_system_service import _resolve_name

        stem = _long_path_segment("zipname-")
        resolved = _resolve_name(None, {}, "", source_filename=f"{stem}.zip")

        assert len(resolved) == len(stem)
        assert resolved == stem

    def test_a_root_prefix_derived_name_is_not_truncated(self):
        from src.services.design_system_service import _resolve_name

        stem = _long_path_segment("rootdir-")
        resolved = _resolve_name(None, {}, f"{stem}/")

        assert len(resolved) == len(stem)

    def test_the_constant_fallback_still_applies(self):
        """No candidate at all still yields the constant, not an empty name."""
        from src.services.design_system_service import _resolve_name

        assert _resolve_name(None, {}, "") == "Imported Design System"


class TestImportPersistsEveryGroupIntact:
    """An unknown group was DISCARDED before storage: ``_canonicalize_token``
    honored only the seven canonical groups and otherwise replaced the author's
    group with an inferred one, so the token could not be persisted with its group
    intact."""

    def test_an_unknown_long_group_survives_canonicalization(self):
        from src.services.design_system_service import _canonicalize_token

        group = _long_text("group-")
        result = _canonicalize_token("tok-import", "#0A0B0C", None, group)

        assert result is not None
        assert result[0] == group, (
            f"the author's group was DISCARDED and replaced with {result[0]!r}"
        )

    def test_a_short_unknown_group_survives_too(self):
        """Not a length problem — ANY unrecognized group was replaced."""
        from src.services.design_system_service import _canonicalize_token

        result = _canonicalize_token("tok", "#0A0B0C", None, "brandish")

        assert result is not None
        assert result[0] == "brandish"

    def test_canonical_groups_still_resolve_canonically(self):
        """The control: recognized groups must keep their existing resolution, so
        the compiler's purpose-built emitters still receive them."""
        from src.services.design_system_service import _canonicalize_token

        for group in ("core", "accents", "ink", "tints", "type", "spacing", "shadow"):
            result = _canonicalize_token("tok", "#0A0B0C", None, group)
            assert result is not None and result[0] == group

    def test_group_casing_and_padding_still_normalize(self):
        """Recognized groups are matched case-insensitively, as before."""
        from src.services.design_system_service import _canonicalize_token

        result = _canonicalize_token("tok", "#0A0B0C", None, "  CORE ")
        assert result is not None and result[0] == "core"

    def test_kind_inference_still_applies_without_a_group(self):
        """With no group supplied, manifest ``kind`` still decides — uncapping must
        not disturb the inference chain."""
        from src.services.design_system_service import _canonicalize_token

        result = _canonicalize_token("tok", "16px", "spacing", None)
        assert result is not None and result[0] == "spacing"


class TestEndToEndRoundTripPreservesLength:
    """The assertion that actually matters on SQLite: a long value goes in, comes
    back byte-identical, compiles, and APPEARS in the artifact."""

    @pytest.mark.parametrize("field", ["group", "name", "value"])
    def test_a_long_token_field_round_trips_and_compiles(self, session, field):
        from src.database.models.design_system import DesignSystem, DesignSystemToken
        from src.services.design_system_compiler import compile_design_system

        values = {"group": "core", "name": "tok", "value": "#0A0B0C"}
        values[field] = _long_text(f"{field}-")

        ds = DesignSystem(name=f"Acme {field}", description="synthetic")
        ds.tokens.append(DesignSystemToken(**values))
        session.add(ds)
        session.commit()
        session.expire_all()

        reloaded = session.get(DesignSystem, ds.id)
        stored = getattr(reloaded.tokens[0], field)
        assert len(stored) == _LONG, (
            f"token.{field} was stored at {len(stored)} of {_LONG} characters"
        )
        assert stored == values[field]

        out = compile_design_system(reloaded)
        if field == "group":
            # The group NAME is deliberately never emitted (round-5 4b: a heading
            # must carry no user text), so what must appear is its TOKEN.
            assert f"- {values['name']}: {values['value']}" in out
        else:
            assert values[field] in out, (
                f"a {_LONG}-character token {field} did not reach the artifact"
            )

    def test_a_long_design_system_name_round_trips_and_compiles(self, session):
        from src.database.models.design_system import DesignSystem, DesignSystemToken
        from src.services.design_system_compiler import compile_design_system

        name = _long_text("dsname-")
        ds = DesignSystem(name=name, description="synthetic")
        ds.tokens.append(
            DesignSystemToken(group="core", name="primary", value="#123456")
        )
        session.add(ds)
        session.commit()
        session.expire_all()

        reloaded = session.get(DesignSystem, ds.id)
        assert len(reloaded.name) == _LONG
        assert reloaded.name == name
        # The header carries the name (sanitized, marker-shaped text removed — this
        # name contains none), so it must appear in full.
        assert name in compile_design_system(reloaded)

    def test_a_long_description_round_trips_and_compiles(self, session):
        from src.database.models.design_system import DesignSystem
        from src.services.design_system_compiler import compile_design_system

        description = _long_text("dsdesc-")
        ds = DesignSystem(name="Acme desc", description=description)
        session.add(ds)
        session.commit()
        session.expire_all()

        reloaded = session.get(DesignSystem, ds.id)
        assert len(reloaded.description) == _LONG
        assert description in compile_design_system(reloaded)

    def test_a_long_asset_filename_round_trips(self, session):
        from src.database.models.design_system import DesignSystem, DesignSystemAsset

        filename = _long_text("logo-") + ".svg"
        ds = DesignSystem(name="Acme asset", description="synthetic")
        ds.assets.append(
            DesignSystemAsset(
                kind="logo",
                filename=filename,
                mime="image/svg+xml",
                data=b"<svg/>",
                size_bytes=6,
            )
        )
        session.add(ds)
        session.commit()
        session.expire_all()

        reloaded = session.get(DesignSystem, ds.id)
        assert reloaded.assets[0].filename == filename

    def test_a_long_file_path_round_trips(self, session):
        from src.database.models.design_system import DesignSystem, DesignSystemFile

        path = _long_text("nested/") + "/README.md"
        ds = DesignSystem(name="Acme file", description="synthetic")
        ds.files.append(
            DesignSystemFile(
                path=path,
                kind="readme",
                mime="text/markdown",
                data=b"# Acme",
                size_bytes=6,
            )
        )
        session.add(ds)
        session.commit()
        session.expire_all()

        reloaded = session.get(DesignSystem, ds.id)
        assert reloaded.files[0].path == path

    def test_a_long_template_name_and_entry_path_round_trip(self, session):
        from src.database.models.design_system import (
            DesignSystem,
            DesignSystemTemplate,
        )

        name = _long_text("tpl-")
        entry_path = _long_text("templates/") + "/index.html"
        ds = DesignSystem(name="Acme tpl", description="synthetic")
        ds.templates.append(
            DesignSystemTemplate(
                name=name,
                entry_path=entry_path,
                layout_html="<div>synthetic</div>",
            )
        )
        session.add(ds)
        session.commit()
        session.expire_all()

        reloaded = session.get(DesignSystem, ds.id)
        assert reloaded.templates[0].name == name
        assert reloaded.templates[0].entry_path == entry_path


class TestByteLimitsAreUntouched:
    """The BYTE guards are OOM protection, not brand-data limits. Uncapping text
    must not have relaxed them."""

    def test_asset_and_bundle_byte_limits_still_exist(self):
        from src.database.models.design_system import (
            MAX_ASSET_SIZE_BYTES,
            MAX_BUNDLE_SIZE_BYTES,
        )

        assert MAX_ASSET_SIZE_BYTES > 0
        assert MAX_BUNDLE_SIZE_BYTES > 0
        assert MAX_BUNDLE_SIZE_BYTES == 500 * 1024 * 1024


class TestUncapMigration:
    """The hand-rolled migration, in the established pattern. Idempotent, safe on
    both dialects, and driven from one list of columns."""

    def test_migration_is_a_noop_on_sqlite(self):
        """Same dialect contract as the two widen migrations: SQLite does not
        enforce VARCHAR length and has no ``ALTER COLUMN TYPE``, so the helper
        returns early rather than attempting a statement SQLite cannot run. A long
        value still round-trips, which is why the early return is correct rather
        than a gap."""
        from sqlalchemy import create_engine, inspect, text
        from sqlalchemy.pool import StaticPool

        from src.core.database import Base, _migrate_uncap_brand_text_columns

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        long_group = "g" * _LONG
        with engine.begin() as conn:
            inspector = inspect(conn)
            _migrate_uncap_brand_text_columns(
                conn, inspector, None, lambda t: f'"{t}"', True
            )
            conn.execute(text(
                "INSERT INTO design_system "
                "(name, version, published, is_active, is_default, created_at, "
                "updated_at) VALUES ('Acme Uncap', 1, 0, 1, 0, CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            ))
            ds_id = conn.execute(text("SELECT id FROM design_system")).scalar()
            conn.execute(
                text(
                    'INSERT INTO design_system_token (design_system_id, "group", '
                    "name, value) VALUES (:ds, :grp, 'tok', '64px')"
                ),
                {"ds": ds_id, "grp": long_group},
            )
            got = conn.execute(text('SELECT "group" FROM design_system_token')).scalar()
        assert got == long_group
        engine.dispose()

    def test_migration_runs_twice_without_error(self):
        """Idempotency, asserted rather than assumed."""
        from sqlalchemy import create_engine, inspect
        from sqlalchemy.pool import StaticPool

        from src.core.database import Base, _migrate_uncap_brand_text_columns

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            inspector = inspect(conn)
            for _ in range(2):
                _migrate_uncap_brand_text_columns(
                    conn, inspector, None, lambda t: f'"{t}"', True
                )
        engine.dispose()

    def test_migration_is_registered_in_init_db(self):
        """A migration that is never called is not a migration. Pinned by reading
        the module source, since ``_run_migrations`` needs a live connection."""
        import inspect as inspect_mod

        import src.core.database as database_module

        source = inspect_mod.getsource(database_module)
        assert source.count("_migrate_uncap_brand_text_columns(") >= 2, (
            "the uncap migration must be CALLED from the migration runner, not "
            "merely defined"
        )

    def test_every_uncapped_orm_column_is_in_the_migration_list(self):
        """The ORM declaration and the migration must not drift: a column declared
        Text but absent from the migration list would stay VARCHAR on every
        already-provisioned database — exactly the half-fix that reopened this."""
        import src.database.models.design_system as models
        from src.core.database import _BRAND_TEXT_COLUMNS

        listed = set(_BRAND_TEXT_COLUMNS)
        # ``description``/``layout_html``/``token_css``/``compiled_style_content``
        # were ALREADY Text before this change, so they need no ALTER.
        already_text = {
            ("design_system", "description"),
            ("design_system", "compiled_style_content"),
            ("design_system_template", "description"),
            ("design_system_template", "layout_html"),
            ("design_system_template", "token_css"),
        }
        for model_name in (
            "DesignSystem",
            "DesignSystemAsset",
            "DesignSystemToken",
            "DesignSystemFile",
            "DesignSystemTemplate",
        ):
            table = getattr(models, model_name).__table__
            for column in table.columns:
                if not isinstance(column.type, Text):
                    continue
                key = (table.name, column.name)
                assert key in listed or key in already_text, (
                    f"{key} is declared Text but is not in _BRAND_TEXT_COLUMNS, so "
                    f"an existing database would keep its VARCHAR cap"
                )

    def test_system_controlled_columns_are_not_in_the_migration_list(self):
        """The counter-assertion: the migration must be SCOPED to brand text."""
        from src.core.database import _BRAND_TEXT_COLUMNS

        listed = set(_BRAND_TEXT_COLUMNS)
        for key in (
            ("design_system_asset", "kind"),
            ("design_system_asset", "mime"),
            ("design_system_file", "kind"),
            ("design_system_file", "mime"),
            ("design_system", "created_by"),
            ("design_system", "updated_by"),
        ):
            assert key not in listed, f"{key} is system-controlled, not brand text"

    def test_postgres_ddl_emits_text_not_varchar(self):
        """THE Postgres assertion. SQLite cannot show this — it does not enforce
        VARCHAR length — so the column type is verified by compiling the CREATE
        TABLE DDL against the PostgreSQL dialect, which is what a fresh Lakebase
        install runs, and by compiling the ALTER the migration issues."""
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.schema import CreateTable

        import src.database.models.design_system as models

        rendered = {
            table_name: str(
                CreateTable(getattr(models, model_name).__table__).compile(
                    dialect=postgresql.dialect()
                )
            )
            for model_name, table_name in (
                ("DesignSystem", "design_system"),
                ("DesignSystemToken", "design_system_token"),
                ("DesignSystemAsset", "design_system_asset"),
                ("DesignSystemFile", "design_system_file"),
                ("DesignSystemTemplate", "design_system_template"),
            )
        }

        expected_text_columns = {
            "design_system": ["name"],
            "design_system_token": ["group", "name", "value"],
            "design_system_asset": ["filename"],
            "design_system_file": ["path"],
            "design_system_template": ["name", "entry_path"],
        }
        for table_name, columns in expected_text_columns.items():
            ddl = rendered[table_name]
            for column in columns:
                # ``group`` is quoted in the DDL (reserved word); match either form.
                for candidate in (f"{column} TEXT", f'"{column}" TEXT'):
                    if candidate in ddl:
                        break
                else:
                    raise AssertionError(
                        f"PostgreSQL DDL for {table_name}.{column} is not TEXT:\n"
                        f"{ddl}"
                    )
                assert f"{column} VARCHAR" not in ddl
                assert f'"{column}" VARCHAR' not in ddl

        # The UNIQUE constraint on the now-TEXT name column is still emitted.
        assert "UNIQUE" in rendered["design_system"]

    def test_system_controlled_columns_stay_varchar_in_postgres_ddl(self):
        """Scope check at the DDL level too."""
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.schema import CreateTable

        import src.database.models.design_system as models

        ddl = str(
            CreateTable(models.DesignSystemAsset.__table__).compile(
                dialect=postgresql.dialect()
            )
        )
        assert "kind VARCHAR(50)" in ddl
        assert "mime VARCHAR(100)" in ddl
