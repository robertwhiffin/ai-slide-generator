"""Tests for B2.5: dropping the retired ConfigPrompts columns and stripping the blobs.

Two halves, both destructive:

- ``src.core.database._migrate_drop_config_prompt_columns`` drops
  ``config_prompts.system_prompt`` and ``.slide_editing_instructions``.
- ``src.core.strip_retired_prompt_keys.strip_retired_prompt_keys`` removes the same two
  keys from every stored ``agent_config`` JSON blob on ``config_profiles`` and
  ``user_sessions``.

WHY THESE FIXTURES PUT THE COLUMNS BACK FIRST. The ORM no longer declares the two
columns, so ``create_all`` never creates them and a test run against a fresh schema
would pass with the migration deleted — the measured failure mode from B2.3, where
``create_all`` masked the migration twice. For a migration that DROPS, the only
trustworthy test is one whose database genuinely has the columns before the drop runs,
so every drop test here adds them explicitly first: with ``ALTER TABLE … ADD COLUMN``
where nullability is irrelevant, and by rebuilding ``config_prompts`` by hand where the
``NOT NULL``-with-no-default shape is the point (:class:`TestProfileCreationAfterDrop`).

The two retired names are spelled out literally in this file rather than imported from
the production constants: a test that iterates the production list cannot notice the
list losing an entry.

Everything here runs against real SQLite engines — no mocks. The ``agent_config``
reads that matter go through raw SQL, because that is the read path under test.
"""

import json
import logging

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, _migrate_drop_config_prompt_columns, _run_migrations
import src.database.models  # noqa: F401 — registers every model on Base.metadata
from src.core.strip_retired_prompt_keys import strip_retired_prompt_keys
from src.database.models.profile import ConfigProfile
from src.database.models.prompts import ConfigPrompts
from src.database.models.session import UserSession

# The two names under test, deliberately hard-coded (see module docstring).
RETIRED = ("system_prompt", "slide_editing_instructions")

# A raw INSERT for user_sessions: raw SQL is the only way to store an agent_config
# blob that will not parse, so it is also the only way to reach the skip path. The
# NOT NULL columns without Python-side defaults must be supplied by hand.
_RAW_SESSION_INSERT = (
    "INSERT INTO user_sessions "
    "(session_id, created_by, created_at, last_activity, is_processing, agent_config) "
    "VALUES (:sid, 'test-user@example.com', '2026-01-01 00:00:00', "
    "'2026-01-01 00:00:00', 0, :blob)"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_schema(engine) -> None:
    """Production ordering: create_all, then the migration chain."""
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)


def _add_retired_columns(engine) -> None:
    """Put the two retired columns back, simulating a pre-B2.5 database.

    Nullable here: SQLite rejects ``ADD COLUMN … NOT NULL`` without a default, and
    nullability is irrelevant to whether ``DROP COLUMN`` removes the column. The
    ``NOT NULL`` shape that production actually carries is exercised by
    :class:`TestProfileCreationAfterDrop`, which rebuilds the table instead.
    """
    with engine.begin() as conn:
        for name in RETIRED:
            conn.execute(text(f"ALTER TABLE config_prompts ADD COLUMN {name} TEXT"))
    assert set(RETIRED) <= _column_names(engine, "config_prompts"), (
        "fixture failed to add the retired columns; the drop test that follows "
        "would prove nothing"
    )


def _column_names(engine, table: str) -> set:
    """Column names for *table*, read through a fresh (uncached) inspector."""
    with engine.connect() as conn:
        return {c["name"] for c in sa_inspect(conn).get_columns(table)}


def _drop_directly(engine) -> None:
    """Call the migration helper alone, exactly as _run_migrations calls it."""
    _qual = lambda t: f'"{t}"'  # noqa: E731 — matches _run_migrations' own lambda
    with engine.begin() as conn:
        _migrate_drop_config_prompt_columns(
            conn, sa_inspect(conn), schema=None, _qual=_qual, is_sqlite=True
        )


def _raw_blob(engine, table: str, row_id: int) -> str:
    """Read one agent_config blob as TEXT, bypassing the column's result processor."""
    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT CAST(agent_config AS TEXT) FROM {table} WHERE id = :i"),
            {"i": row_id},
        ).scalar()


@pytest.fixture()
def sqlite_engine_pre_b25():
    """In-memory SQLite with the full schema AND the two retired columns present."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    _build_schema(engine)
    _add_retired_columns(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def blob_engine():
    """In-memory SQLite with the full schema, for the agent_config blob tests."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    _build_schema(engine)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Part 1 — the column drop
# ---------------------------------------------------------------------------


class TestColumnDrop:
    """The migration removes both columns from a database that has them, idempotently."""

    def test_both_columns_are_gone_after_the_migration(self, sqlite_engine_pre_b25):
        _drop_directly(sqlite_engine_pre_b25)

        cols = _column_names(sqlite_engine_pre_b25, "config_prompts")
        assert "system_prompt" not in cols, (
            "config_prompts.system_prompt survived _migrate_drop_config_prompt_columns"
        )
        assert "slide_editing_instructions" not in cols, (
            "config_prompts.slide_editing_instructions survived "
            "_migrate_drop_config_prompt_columns"
        )

    def test_the_surviving_columns_are_untouched(self, sqlite_engine_pre_b25):
        before = _column_names(sqlite_engine_pre_b25, "config_prompts") - set(RETIRED)
        _drop_directly(sqlite_engine_pre_b25)
        assert _column_names(sqlite_engine_pre_b25, "config_prompts") == before, (
            "the drop removed (or added) something other than the two retired columns"
        )

    def test_migration_is_idempotent_across_two_runs(self, sqlite_engine_pre_b25):
        """A second boot is a no-op: the presence guard skips the ALTER."""
        _drop_directly(sqlite_engine_pre_b25)
        after_first = _column_names(sqlite_engine_pre_b25, "config_prompts")

        _drop_directly(sqlite_engine_pre_b25)  # must not raise

        assert _column_names(sqlite_engine_pre_b25, "config_prompts") == after_first
        assert not set(RETIRED) & after_first

    def test_no_op_when_the_table_is_absent(self):
        """A deploy without config_prompts must be skipped, not crashed."""
        engine = create_engine("sqlite:///:memory:")
        try:
            _drop_directly(engine)  # empty database: no tables at all
        finally:
            engine.dispose()


class TestProfileCreationAfterDrop:
    """The ordering hazard, asserted rather than assumed.

    Both columns are ``Text NOT NULL`` with no default and the ORM no longer supplies
    a value, so on a database that still HAS them every profile insert fails. This
    rebuilds ``config_prompts`` in exactly that shape (SQLite cannot ADD a NOT NULL
    column without a default), proves the insert fails, runs the production migration
    chain, and proves the insert then succeeds. That is why the DROP lives inside
    ``_run_migrations`` — which ``init_db()`` runs — and not anywhere after
    ``seed_defaults()``.
    """

    _PRE_B25_DDL = """
        CREATE TABLE config_prompts (
            id INTEGER NOT NULL PRIMARY KEY,
            profile_id INTEGER NOT NULL,
            system_prompt TEXT NOT NULL,
            slide_editing_instructions TEXT NOT NULL,
            selected_deck_prompt_id INTEGER,
            selected_slide_style_id INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            UNIQUE (profile_id)
        )
    """

    @staticmethod
    def _create_profile_with_prompts(factory, name: str) -> None:
        db = factory()
        try:
            profile = ConfigProfile(name=name, description="hazard probe")
            db.add(profile)
            db.flush()
            db.add(ConfigPrompts(profile_id=profile.id, selected_slide_style_id=None))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def test_insert_fails_before_the_drop_and_succeeds_after(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'hazard.db'}")
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        try:
            _build_schema(engine)
            # Rebuild config_prompts in its pre-B2.5 shape: NOT NULL, no default.
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE config_prompts"))
                conn.execute(text(self._PRE_B25_DDL))
            assert set(RETIRED) <= _column_names(engine, "config_prompts")

            with pytest.raises(IntegrityError) as exc_info:
                self._create_profile_with_prompts(factory, "before-drop")
            assert "system_prompt" in str(exc_info.value), (
                "expected the NOT NULL violation named in corrections §20; got "
                f"{exc_info.value}"
            )

            # The production path: _run_migrations is what init_db() calls, and it
            # runs before seed_defaults() creates any profile.
            _run_migrations(engine)

            assert not set(RETIRED) & _column_names(engine, "config_prompts")
            self._create_profile_with_prompts(factory, "after-drop")

            db = factory()
            try:
                assert (
                    db.query(ConfigPrompts)
                    .join(ConfigProfile, ConfigProfile.id == ConfigPrompts.profile_id)
                    .filter(ConfigProfile.name == "after-drop")
                    .count()
                    == 1
                ), "profile creation did not survive the drop"
            finally:
                db.close()
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Part 2 — the blob strip
# ---------------------------------------------------------------------------


class TestBlobStrip:
    """The two keys leave every stored agent_config, and nothing else moves."""

    def test_both_tables_lose_the_keys(self, session_and_profile_with_legacy_blobs):
        """The shared fixture seeds one session row and one profile row with both keys."""
        fixture = session_and_profile_with_legacy_blobs

        changed = strip_retired_prompt_keys(fixture.session_local)

        assert changed == 2, (
            f"expected both rows (one session, one profile) stripped; got {changed}"
        )
        blobs = fixture.reload_blobs()
        for where, blob in blobs.items():
            assert blob == {"tools": []}, (
                f"{where} blob is {blob!r}, expected exactly {{'tools': []}} — the "
                "strip must remove the two retired keys and change nothing else"
            )

    def test_every_other_byte_is_preserved_and_a_lean_blob_does_not_inflate(
        self, blob_engine
    ):
        """Exact-blob assertion: unknown keys, nesting, and leanness all survive."""
        factory = sessionmaker(bind=blob_engine, expire_on_commit=False)
        rich = {
            "tools": ["genie", "images"],
            "system_prompt": "retired",
            "a_key_a_newer_writer_added": {"nested": [1, 2.5, None, True]},
            "slide_editing_instructions": "retired",
            "slide_style_id": 7,
        }
        lean = {"tools": []}

        db = factory()
        try:
            db.add(ConfigProfile(name="rich", agent_config=dict(rich)))
            db.add(ConfigProfile(name="lean", agent_config=dict(lean)))
            db.commit()
            rich_id = db.query(ConfigProfile).filter_by(name="rich").one().id
            lean_id = db.query(ConfigProfile).filter_by(name="lean").one().id
        finally:
            db.close()

        assert strip_retired_prompt_keys(factory) == 1, (
            "only the rich blob carries a retired key, so exactly one row changes"
        )

        expected_rich = {k: v for k, v in rich.items() if k not in RETIRED}
        assert json.loads(_raw_blob(blob_engine, "config_profiles", rich_id)) == (
            expected_rich
        ), "the strip altered something other than the two retired keys"
        assert json.loads(_raw_blob(blob_engine, "config_profiles", lean_id)) == lean, (
            "the lean blob INFLATED — the strip must not round-trip through a model "
            "that fills in defaults"
        )

    def test_strip_is_idempotent(self, session_and_profile_with_legacy_blobs):
        fixture = session_and_profile_with_legacy_blobs

        assert strip_retired_prompt_keys(fixture.session_local) == 2
        assert strip_retired_prompt_keys(fixture.session_local) == 0, (
            "a second run must report 0 rows changed"
        )
        assert fixture.reload_blobs()["profile"] == {"tools": []}

    def test_unparseable_blob_is_logged_and_skipped_not_raised(
        self, blob_engine, caplog
    ):
        """The row is inserted with RAW SQL: an ORM write cannot reproduce this.

        Reading such a blob through the ORM attribute raises ``JSONDecodeError`` in the
        result processor, outside any ``try`` the strip could place around it — which is
        why the strip reads the column as TEXT. This test is what makes the raw read
        load-bearing rather than stylistic.
        """
        factory = sessionmaker(bind=blob_engine, expire_on_commit=False)
        with blob_engine.begin() as conn:
            conn.execute(
                text(_RAW_SESSION_INSERT), {"sid": "unparseable", "blob": "{broken"}
            )
        db = factory()
        try:
            db.add(
                UserSession(
                    session_id="strippable",
                    created_by="test-user@example.com",
                    agent_config={"tools": [], "system_prompt": "retired"},
                )
            )
            db.commit()
        finally:
            db.close()

        # Confirm the bad row really is undecodable through the ORM: without that, this
        # test would pass even if the strip read via the ORM attribute.
        db = factory()
        try:
            with pytest.raises(json.JSONDecodeError):
                _ = (
                    db.query(UserSession)
                    .filter_by(session_id="unparseable")
                    .one()
                    .agent_config
                )
        finally:
            db.close()

        with caplog.at_level(logging.WARNING, logger="src.core.strip_retired_prompt_keys"):
            changed = strip_retired_prompt_keys(factory)

        assert changed == 1, (
            "the good row must still be stripped; one bad row must not abort the step"
        )
        assert any(
            "will not parse" in record.message for record in caplog.records
        ), f"the skipped row was not logged; records: {[r.message for r in caplog.records]}"

        # The bad blob is left exactly as it was found.
        with blob_engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT CAST(agent_config AS TEXT) FROM user_sessions "
                        "WHERE session_id = 'unparseable'"
                    )
                ).scalar()
                == "{broken"
            )
            good = conn.execute(
                text(
                    "SELECT CAST(agent_config AS TEXT) FROM user_sessions "
                    "WHERE session_id = 'strippable'"
                )
            ).scalar()
        assert json.loads(good) == {"tools": []}

    def test_non_object_blob_is_skipped_without_raising(self, blob_engine, caplog):
        """A JSON array parses fine but is not a config — skip and log, do not edit."""
        factory = sessionmaker(bind=blob_engine, expire_on_commit=False)
        with blob_engine.begin() as conn:
            conn.execute(text(_RAW_SESSION_INSERT), {"sid": "arr", "blob": "[1, 2]"})

        with caplog.at_level(logging.WARNING, logger="src.core.strip_retired_prompt_keys"):
            assert strip_retired_prompt_keys(factory) == 0

        assert any("not a JSON object" in r.message for r in caplog.records)
        with blob_engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT CAST(agent_config AS TEXT) FROM user_sessions "
                        "WHERE session_id = 'arr'"
                    )
                ).scalar()
                == "[1, 2]"
            )


# ---------------------------------------------------------------------------
# The whole ws4b migration chain
# ---------------------------------------------------------------------------


class TestFourMigrationChainAppliedTwice:
    """All four ws4b migrations, run twice against a fresh SQLite FILE, all still applied.

    The retired columns are put back after ``create_all`` so the fourth migration has
    real work to do on the first pass, rather than being masked by a schema that never
    had them.
    """

    def test_all_four_effects_present_after_two_runs(self, tmp_path):
        db_path = tmp_path / "chain.db"
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            Base.metadata.create_all(bind=engine)
            _add_retired_columns(engine)

            _run_migrations(engine)
            _run_migrations(engine)

            with engine.connect() as conn:
                tables = set(sa_inspect(conn).get_table_names())
            for table in ("graph_checkpoints", "graph_checkpoint_writes", "deck_reviews"):
                assert table in tables, (
                    f"{table} missing after two migration runs; found {sorted(tables)}"
                )

            deck_cols = _column_names(engine, "session_slide_decks")
            for col in ("spec_dirty_at", "spec_dirty_by", "spec_dirty_claimed_at"):
                assert col in deck_cols, f"{col} missing from session_slide_decks"

            prompt_cols = _column_names(engine, "config_prompts")
            assert "system_prompt" not in prompt_cols, (
                "config_prompts.system_prompt came back (or was never dropped) after "
                "two runs of the chain"
            )
            assert "slide_editing_instructions" not in prompt_cols, (
                "config_prompts.slide_editing_instructions came back (or was never "
                "dropped) after two runs of the chain"
            )
        finally:
            engine.dispose()
